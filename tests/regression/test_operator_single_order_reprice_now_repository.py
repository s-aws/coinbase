from __future__ import annotations

from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
import re
import uuid

import pytest
from psycopg2 import sql
from psycopg2.errors import RaiseException

from application.admin_api.operator_single_order_reprice_now_policy import (
    build_single_order_reprice_now_intent,
)
from application.admin_api.operator_single_order_reprice_now_models import (
    OperatorSingleOrderRepriceNowIntentRequest,
)
from application.admin_api.operator_single_order_reprice_now_service import (
    OperatorSingleOrderRepriceNowCommandContext,
    OperatorSingleOrderRepriceNowService,
)
from database.database import PostgresDB
from database.operator_single_order_reprice_now import (
    OperatorSingleOrderRepriceNowConflict,
    OperatorSingleOrderRepriceNowRepository,
)


pytestmark = [pytest.mark.regression, pytest.mark.serial]

TEST_DB_HOST = os.environ.get("COINBASE_DB_HOST", "coinbase-test-postgres")
TEST_DB_PORT = int(os.environ.get("COINBASE_DB_PORT", "9876"))
TEST_DB_NAME = os.environ.get("COINBASE_DB_NAME", "postgres")
TEST_DB_USER = os.environ.get("COINBASE_DB_USER", "postgres")
TEST_DB_PASSWORD = os.environ.get("COINBASE_DB_PASSWORD", "postgres")
_SCHEMA = re.compile(r"^test_operator_reprice_now_[0-9a-f]{32}$")
STEALTH_ID = "11111111-1111-4111-8111-111111111111"
SOURCE_ID = "22222222-2222-4222-8222-222222222222"
ACTOR = "private-operator-marker"
IDEMPOTENCY_KEY = "private-idempotency-marker"


@pytest.fixture
def repository() -> OperatorSingleOrderRepriceNowRepository:
    schema = f"test_operator_reprice_now_{uuid.uuid4().hex}"
    assert _SCHEMA.fullmatch(schema)
    database = PostgresDB(
        host=TEST_DB_HOST,
        port=TEST_DB_PORT,
        database=TEST_DB_NAME,
        user=TEST_DB_USER,
        password=TEST_DB_PASSWORD,
    )
    database.connect()
    with database.get_cursor() as cursor:
        cursor.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
        )
    repo = OperatorSingleOrderRepriceNowRepository(
        database,
        schema=schema,
    )
    repo.ensure_schema()
    try:
        yield repo
    finally:
        with database.get_cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(
                    sql.Identifier(schema)
                )
            )
        database.disconnect()


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _selection() -> dict[str, object]:
    return {
        "stealth_order_id": STEALTH_ID,
        "source_client_order_id": SOURCE_ID,
        "found": True,
        "eligible": True,
        "diagnostic_code": "operator_reprice_now_source_eligible",
        "definition_revision": 7,
        "definition_sha256": "a" * 64,
        "root_client_order_id": STEALTH_ID,
        "source_status": "REVEALED",
        "zero_fill_proven": True,
        "system_owned": True,
        "direct_parent": True,
        "source_evidence_sha256": "b" * 64,
    }


def _intent() -> dict[str, object]:
    built = build_single_order_reprice_now_intent(source=_selection())
    return asdict(built)


def _create(
    repository: OperatorSingleOrderRepriceNowRepository,
) -> dict[str, object]:
    return repository.create_intent(
        intent=_intent(),
        source_selection=_selection(),
        actor_id=ACTOR,
        correlation_id="goal15-correlation",
        idempotency_key=IDEMPOTENCY_KEY,
        payload_sha256="c" * 64,
        operator_reason_sha256="d" * 64,
    )


def test_intent_is_durable_private_and_exactly_replayable(
    repository: OperatorSingleOrderRepriceNowRepository,
) -> None:
    created = _create(repository)
    replayed = repository.get_intent_replay(
        stealth_order_id=STEALTH_ID,
        source_client_order_id=SOURCE_ID,
        actor_id=ACTOR,
        correlation_id="goal15-correlation",
        idempotency_key=IDEMPOTENCY_KEY,
        payload_sha256="c" * 64,
    )
    restarted = OperatorSingleOrderRepriceNowRepository(
        repository.database,
        schema=repository.schema,
    )
    restarted.ensure_schema()
    restored = restarted.get_intent(
        stealth_order_id=STEALTH_ID,
        source_client_order_id=SOURCE_ID,
    )

    assert created["state"] == "INTENT_PREPARED"
    assert replayed is not None
    assert replayed["command_replayed"] is True
    assert restored is not None
    assert restored["intent_sha256"] == created["intent_sha256"]
    assert restored["local_cycles_used"] == 1
    assert restored["latest_cycle_actor_id_sha256"] == _sha(ACTOR)
    assert restored["latest_cycle_idempotency_key_sha256"] == _sha(
        IDEMPOTENCY_KEY
    )
    assert ACTOR not in repr(restored)
    assert IDEMPOTENCY_KEY not in repr(restored)
    assert "exchange_order_id" not in repr(restored)
    assert restored["latest_cycle_evidence_sha256"] == (
        restored["events"][-1]["evidence_sha256"]
    )


def test_identical_create_after_first_commit_is_exact_replay(
    repository: OperatorSingleOrderRepriceNowRepository,
) -> None:
    first = _create(repository)
    second = _create(repository)

    assert second["command_replayed"] is True
    assert second["intent_sha256"] == first["intent_sha256"]


def test_concurrent_identical_first_prepare_resolves_source_once_and_replays(
    repository: OperatorSingleOrderRepriceNowRepository,
) -> None:
    class _Definitions:
        calls = 0

        def get_definition(self, stealth_order_id: str):
            assert stealth_order_id == STEALTH_ID
            self.calls += 1
            return {
                "definition_id": STEALTH_ID,
                "revision": 7,
                "definition_sha256": "a" * 64,
            }

    class _Resolver:
        calls = 0

        def resolve(self, **_kwargs):
            self.calls += 1
            return _selection()

    definitions = _Definitions()
    resolver = _Resolver()
    service = OperatorSingleOrderRepriceNowService(
        definition_repository=definitions,
        repository=repository,
        source_resolver=resolver,
    )
    body = OperatorSingleOrderRepriceNowIntentRequest(
        expected_definition_revision=7,
        expected_definition_sha256="a" * 64,
        expected_source_evidence_sha256="b" * 64,
        operator_reason="Operator reviewed the exact source.",
        confirm_prepare_reprice_now_intent=True,
    )
    context = OperatorSingleOrderRepriceNowCommandContext(
        actor_id=ACTOR,
        roles=("trader",),
        correlation_id="goal15-correlation",
        idempotency_key=IDEMPOTENCY_KEY,
        operator_intent="prepare_single_order_reprice_now",
    )

    def prepare():
        return service.prepare_reprice_now_intent(
            stealth_order_id=STEALTH_ID,
            source_client_order_id=SOURCE_ID,
            body=body,
            context=context,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: prepare(), range(2)))

    assert {result.intent_sha256 for result in results} == {
        results[0].intent_sha256
    }
    assert sum(result.command_replayed for result in results) == 1
    assert definitions.calls == 1
    assert resolver.calls == 1


def test_same_goal_cannot_bind_another_source(
    repository: OperatorSingleOrderRepriceNowRepository,
) -> None:
    _create(repository)
    other = _selection()
    other["source_client_order_id"] = (
        "44444444-4444-4444-8444-444444444444"
    )
    other["source_evidence_sha256"] = "e" * 64
    other_intent = asdict(
        build_single_order_reprice_now_intent(source=other)
    )

    with pytest.raises(OperatorSingleOrderRepriceNowConflict) as exc:
        repository.create_intent(
            intent=other_intent,
            source_selection=other,
            actor_id=ACTOR,
            correlation_id="goal15-other",
            idempotency_key="goal15-other-key",
            payload_sha256="f" * 64,
            operator_reason_sha256="1" * 64,
        )

    assert exc.value.code == "operator_reprice_now_goal_already_bound"


def test_different_source_readback_is_value_blind_goal_binding(
    repository: OperatorSingleOrderRepriceNowRepository,
) -> None:
    _create(repository)
    other_stealth = "44444444-4444-4444-8444-444444444444"
    other_source = "55555555-5555-4555-8555-555555555555"

    readback = repository.get_intent(
        stealth_order_id=other_stealth,
        source_client_order_id=other_source,
    )

    assert readback == {
        "goal_bound_elsewhere": True,
        "local_cycles_used": 1,
    }
    assert STEALTH_ID not in repr(readback)
    assert SOURCE_ID not in repr(readback)
    assert repository.goal_is_bound() is True


def test_zero_exchange_call_constraints_are_database_enforced(
    repository: OperatorSingleOrderRepriceNowRepository,
) -> None:
    _create(repository)

    with pytest.raises(
        RaiseException,
        match="operator_reprice_now_immutable_ledger",
    ):
        with repository.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE
                    {repository.prefix}operator_single_order_reprice_now_goal
                SET source_cancel_call_count = 1
                WHERE goal_id = %s
                """,
                ("operator_single_order_reprice_now_v1",),
            )


@pytest.mark.parametrize(
    "table_suffix",
    [
        "goal",
        "cycle",
        "event",
    ],
)
@pytest.mark.parametrize(
    "operation",
    [
        "UPDATE",
        "DELETE",
        "TRUNCATE",
    ],
)
def test_intent_cycle_and_event_evidence_are_database_immutable(
    repository: OperatorSingleOrderRepriceNowRepository,
    table_suffix: str,
    operation: str,
) -> None:
    _create(repository)
    table = (
        f"{repository.prefix}operator_single_order_reprice_now_"
        f"{table_suffix}"
    )
    timestamp_column = {
        "goal": "updated_at",
        "cycle": "completed_at",
        "event": "recorded_at",
    }[table_suffix]
    statement = {
        "UPDATE": (
            f"UPDATE {table} SET {timestamp_column} = {timestamp_column}"
        ),
        "DELETE": f"DELETE FROM {table}",
        "TRUNCATE": f"TRUNCATE TABLE {table} CASCADE",
    }[operation]

    with pytest.raises(
        RaiseException,
        match="operator_reprice_now_immutable_ledger",
    ):
        with repository.database.get_cursor() as cursor:
            cursor.execute(statement)

    restored = repository.get_intent(
        stealth_order_id=STEALTH_ID,
        source_client_order_id=SOURCE_ID,
    )
    assert restored is not None
    assert restored["state"] == "INTENT_PREPARED"
    assert len(restored["events"]) == 1


def test_immutable_triggers_are_restart_safe(
    repository: OperatorSingleOrderRepriceNowRepository,
) -> None:
    _create(repository)

    repository.ensure_schema()
    repository.ensure_schema()

    with pytest.raises(
        RaiseException,
        match="operator_reprice_now_immutable_ledger",
    ):
        with repository.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                DELETE FROM
                    {repository.prefix}operator_single_order_reprice_now_event
                """
            )
