from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal
import os
import re
import uuid

import pytest
from psycopg2 import sql

from application.admin_api.operator_fill_triggered_follow_up_activation import (
    FillTriggeredActivationControlAction,
    FillTriggeredActivationControlState,
    FillTriggeredActivationTriggerState,
)
from database.database import PostgresDB
from database.operator_fill_triggered_follow_up_activation import (
    OperatorFillTriggeredFollowUpActivationRepository,
)


TEST_DB_HOST = os.environ.get("COINBASE_DB_HOST", "coinbase-test-postgres")
TEST_DB_PORT = int(os.environ.get("COINBASE_DB_PORT", "9876"))
TEST_DB_NAME = os.environ.get("COINBASE_DB_NAME", "postgres")
TEST_DB_USER = os.environ.get("COINBASE_DB_USER", "postgres")
TEST_DB_PASSWORD = os.environ.get("COINBASE_DB_PASSWORD", "postgres")
_SCHEMA_RE = re.compile(r"^test_fill_triggered_activation_[0-9a-f]{32}$")

SOURCE_ID = "00000000-0000-4000-8000-000000000091"
INTENT_ID = "00000000-0000-4000-8000-000000000092"
AUDIT_ID = "00000000-0000-4000-8000-000000000093"


def _database() -> PostgresDB:
    assert TEST_DB_HOST == "coinbase-test-postgres"
    assert TEST_DB_PORT == 9876
    return PostgresDB(
        host=TEST_DB_HOST,
        port=TEST_DB_PORT,
        database=TEST_DB_NAME,
        user=TEST_DB_USER,
        password=TEST_DB_PASSWORD,
    )


@dataclass
class _Harness:
    schema: str
    databases: list[PostgresDB] = field(default_factory=list)

    def repository(
        self,
    ) -> OperatorFillTriggeredFollowUpActivationRepository:
        database = _database()
        self.databases.append(database)
        return OperatorFillTriggeredFollowUpActivationRepository(
            database,
            schema=self.schema,
        )

    @property
    def database(self) -> PostgresDB:
        return self.databases[0]


@pytest.fixture
def repository_harness() -> _Harness:
    schema = f"test_fill_triggered_activation_{uuid.uuid4().hex}"
    assert _SCHEMA_RE.fullmatch(schema)
    database = _database()
    database.connect()
    with database.get_cursor() as cursor:
        identifier = sql.Identifier(schema)
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(identifier))
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.operator_follow_up_intent (
                    follow_up_intent_id UUID PRIMARY KEY,
                    source_client_order_id VARCHAR(128) UNIQUE NOT NULL,
                    terminal_result VARCHAR(32) NOT NULL,
                    actor_id VARCHAR(255) NOT NULL,
                    roles_json JSONB NOT NULL,
                    correlation_id VARCHAR(255) NOT NULL,
                    audit_id UUID NOT NULL,
                    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            ).format(identifier)
        )
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.order_parent (
                    client_order_id VARCHAR(128) PRIMARY KEY,
                    status VARCHAR(32) NOT NULL,
                    size NUMERIC NOT NULL
                )
                """
            ).format(identifier)
        )
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.fill_ledger (
                    client_order_id VARCHAR(128) NOT NULL,
                    quantity NUMERIC NOT NULL
                )
                """
            ).format(identifier)
        )
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.partial_fill_progress (
                    client_order_id VARCHAR(128) NOT NULL,
                    partial_follow_ups_created INTEGER NOT NULL DEFAULT 0
                )
                """
            ).format(identifier)
        )
        cursor.execute(
            sql.SQL(
                """
                INSERT INTO {}.operator_follow_up_intent (
                    follow_up_intent_id, source_client_order_id,
                    terminal_result, actor_id, roles_json,
                    correlation_id, audit_id
                ) VALUES (%s, %s, 'ATTACHED', 'operator-1',
                          '["admin","trader"]'::jsonb, 'attach-corr', %s)
                """
            ).format(identifier),
            (INTENT_ID, SOURCE_ID, AUDIT_ID),
        )
        cursor.execute(
            sql.SQL(
                """
                INSERT INTO {}.order_parent (client_order_id, status, size)
                VALUES (%s, 'FILLED', %s)
                """
            ).format(identifier),
            (SOURCE_ID, Decimal("0.01000000")),
        )
        cursor.execute(
            sql.SQL(
                """
                INSERT INTO {}.fill_ledger (client_order_id, quantity)
                VALUES (%s, %s)
                """
            ).format(identifier),
            (SOURCE_ID, Decimal("0.01000000")),
        )
    harness = _Harness(schema=schema, databases=[database])
    harness.repository().ensure_schema()
    try:
        yield harness
    finally:
        for extra in harness.databases[1:]:
            extra.disconnect()
        try:
            with database.get_cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(
                        sql.Identifier(schema)
                    )
                )
        finally:
            database.disconnect()


def _enable(
    repository: OperatorFillTriggeredFollowUpActivationRepository,
    *,
    expected_revision: int = 0,
    key: str = "enable-key",
):
    return repository.transition_control(
        source_client_order_id=SOURCE_ID,
        action=FillTriggeredActivationControlAction.ENABLE,
        expected_revision=expected_revision,
        authorize_single_fill_triggered_materialization=True,
        acknowledge_unknown_outcome_consumes_create_allowance=True,
        acknowledge_child_terms_are_backend_derived=True,
        idempotency_key=key,
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="enable-correlation",
        audit_id=AUDIT_ID,
    )


def test_control_commands_are_revision_bound_and_exactly_replayable(
    repository_harness: _Harness,
) -> None:
    repository = repository_harness.repository()
    assert repository.has_attached_intent(SOURCE_ID) is True
    assert repository.has_attached_intent("missing-source") is False
    initial = repository.read(SOURCE_ID)
    assert initial.control_state is FillTriggeredActivationControlState.DISABLED
    assert initial.trigger_state is FillTriggeredActivationTriggerState.UNCLAIMED
    assert initial.revision == 0

    enabled = _enable(repository)
    replayed = _enable(repository)
    assert enabled == replayed
    assert enabled.control_state is FillTriggeredActivationControlState.ENABLED
    assert enabled.revision == 1

    with pytest.raises(ValueError, match="fill_triggered_control_revision_conflict"):
        repository.transition_control(
            source_client_order_id=SOURCE_ID,
            action=FillTriggeredActivationControlAction.PAUSE,
            expected_revision=0,
            idempotency_key="pause-stale",
            actor_id="operator-1",
            roles=("admin",),
            correlation_id="pause-correlation",
            audit_id=AUDIT_ID,
        )


def test_full_fill_trigger_claim_has_exactly_one_concurrent_winner(
    repository_harness: _Harness,
) -> None:
    first = repository_harness.repository()
    second = repository_harness.repository()
    _enable(first)

    def claim(repository):
        return repository.claim_full_fill_trigger(
            source_client_order_id=SOURCE_ID,
            trigger_evidence_sha256="f" * 64,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, (first, second)))

    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    winner = winners[0]
    assert winner.trigger_state is FillTriggeredActivationTriggerState.CLAIMED
    assert winner.trigger_claim_id
    assert first.list_claimed() == (winner,)

    terminal = first.finalize_trigger(
        source_client_order_id=SOURCE_ID,
        trigger_claim_id=winner.trigger_claim_id,
        trigger_state=FillTriggeredActivationTriggerState.COMPLETED,
        materialization_state="CREATE_ACCEPTED_NONTERMINAL",
        child_client_order_id="00000000-0000-4000-8000-000000000094",
        diagnostic_code="fill_triggered_follow_up_create_accepted",
    )
    assert terminal.trigger_state is FillTriggeredActivationTriggerState.COMPLETED
    assert claim(second) is None


def test_claim_fails_closed_without_exact_full_fill_evidence(
    repository_harness: _Harness,
) -> None:
    repository = repository_harness.repository()
    _enable(repository)
    with repository_harness.database.get_cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "UPDATE {}.order_parent SET status = 'OPEN' "
                "WHERE client_order_id = %s"
            ).format(sql.Identifier(repository_harness.schema)),
            (SOURCE_ID,),
        )

    assert (
        repository.claim_full_fill_trigger(
            source_client_order_id=SOURCE_ID,
            trigger_evidence_sha256="e" * 64,
        )
        is None
    )
    assert repository.read(SOURCE_ID).trigger_state is (
        FillTriggeredActivationTriggerState.UNCLAIMED
    )
