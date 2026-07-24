from __future__ import annotations

import hashlib
import json
import os
import re
import uuid

import pytest
from psycopg2 import sql

from application.admin_api.operator_revealed_order_movement_service import (
    OperatorRevealedOrderMovementConflict,
)
from database.database import PostgresDB
from database.operator_revealed_order_movement import (
    OperatorRevealedOrderMovementRepository,
)


pytestmark = [pytest.mark.regression, pytest.mark.serial]

TEST_DB_HOST = os.environ.get("COINBASE_DB_HOST", "coinbase-test-postgres")
TEST_DB_PORT = int(os.environ.get("COINBASE_DB_PORT", "9876"))
TEST_DB_NAME = os.environ.get("COINBASE_DB_NAME", "postgres")
TEST_DB_USER = os.environ.get("COINBASE_DB_USER", "postgres")
TEST_DB_PASSWORD = os.environ.get("COINBASE_DB_PASSWORD", "postgres")
_SCHEMA = re.compile(r"^test_operator_revealed_move_[0-9a-f]{32}$")


@pytest.fixture
def repository() -> OperatorRevealedOrderMovementRepository:
    schema = f"test_operator_revealed_move_{uuid.uuid4().hex}"
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
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    repo = OperatorRevealedOrderMovementRepository(database, schema=schema)
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


def _plan() -> dict[str, object]:
    body: dict[str, object] = {
        "goal_id": "operator_revealed_order_movement_and_repricing_v1",
        "stealth_order_id": "11111111-1111-4111-8111-111111111111",
        "source_client_order_id": "22222222-2222-4222-8222-222222222222",
        "replacement_client_order_id": (
            "33333333-3333-4333-8333-333333333333"
        ),
        "source_exchange_order_id_sha256": "a" * 64,
        "product_id": "BTC-USDC",
        "side": "BUY",
        "base_size": "0.00001",
        "source_limit_price": "60000.00",
        "requested_limit_price": "60001.00",
        "replacement_limit_price": "60001.00",
        "price_increment": "0.01",
        "submitted_notional": "0.6000100",
        "possible_execution_notional": "0.6000100",
        "submitted_notional_cap": "3.10",
        "possible_execution_notional_cap": "1.00",
        "post_only": True,
        "zero_fill_proven": True,
        "profitability_proven": True,
    }
    body["plan_sha256"] = _sha(
        json.dumps(body, sort_keys=True, separators=(",", ":"))
    )
    return body


def _create_plan(
    repository: OperatorRevealedOrderMovementRepository,
) -> dict[str, object]:
    return repository.create_plan(
        plan=_plan(),
        actor_id="private-actor-marker",
        correlation_id="goal7-plan-correlation",
        idempotency_key="goal7-plan-key",
        payload_sha256=_sha("goal7-plan-payload"),
    )


def _begin(
    repository: OperatorRevealedOrderMovementRepository,
    *,
    suffix: str = "one",
) -> dict[str, object]:
    return repository.begin_execute(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        expected_plan_sha256=str(_plan()["plan_sha256"]),
        actor_id="operator",
        correlation_id=f"goal7-execute-{suffix}",
        idempotency_key=f"goal7-execute-key-{suffix}",
        payload_sha256=_sha(f"goal7-execute-payload-{suffix}"),
    )


def _return_wallet_read(
    repository: OperatorRevealedOrderMovementRepository,
    *,
    correlation_id: str,
) -> None:
    repository.claim_read(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        category="WALLET_PRE_CREATE",
        correlation_id=correlation_id,
    )
    repository.record_read(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        category="WALLET_PRE_CREATE",
        correlation_id=correlation_id,
        result_code="RETURNED",
    )


def test_plan_is_postgresql_durable_and_exact_replay_is_idempotent(
    repository: OperatorRevealedOrderMovementRepository,
) -> None:
    created = _create_plan(repository)
    replayed = _create_plan(repository)
    restarted = OperatorRevealedOrderMovementRepository(
        repository.database,
        schema=repository.schema,
    )
    restarted.ensure_schema()
    restored = restarted.get_goal(str(_plan()["stealth_order_id"]))

    assert created["state"] == "PLANNED"
    assert replayed["command_replayed"] is True
    assert restored is not None
    assert restored["plan_sha256"] == _plan()["plan_sha256"]
    assert "private-actor-marker" not in json.dumps(restored)
    assert "goal7-plan-key" not in json.dumps(restored)


def test_unknown_cancel_consumes_cancel_and_prohibits_create(
    repository: OperatorRevealedOrderMovementRepository,
) -> None:
    _create_plan(repository)
    _begin(repository)
    repository.claim_read(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        category="SOURCE_PRE_CANCEL",
        correlation_id="goal7-execute-one",
    )
    repository.record_read(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        category="SOURCE_PRE_CANCEL",
        correlation_id="goal7-execute-one",
        result_code="OPEN",
    )
    repository.claim_cancel(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        correlation_id="goal7-execute-one",
    )
    outcome = repository.record_cancel_outcome(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        outcome="UNKNOWN",
        diagnostic_code="operator_move_cancel_unknown",
    )

    assert outcome["state"] == "CANCEL_UNKNOWN"
    assert outcome["cancel_call_count"] == 1
    assert outcome["create_call_count"] == 0
    with pytest.raises(OperatorRevealedOrderMovementConflict):
        repository.claim_create(
            stealth_order_id=str(_plan()["stealth_order_id"]),
            correlation_id="goal7-execute-one",
        )


def test_pre_cancel_unknown_closes_without_consuming_cancel(
    repository: OperatorRevealedOrderMovementRepository,
) -> None:
    _create_plan(repository)
    _begin(repository)

    outcome = repository.record_cancel_outcome(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        outcome="UNKNOWN",
        diagnostic_code="operator_move_pre_cancel_read_unknown",
    )
    completed = repository.complete_command(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        phase="EXECUTE",
        correlation_id="goal7-execute-one",
        idempotency_key="goal7-execute-key-one",
    )

    assert outcome["state"] == "CANCEL_UNKNOWN"
    assert outcome["cancel_allowance_consumed"] is False
    assert outcome["cancel_call_count"] == 0
    assert outcome["create_call_count"] == 0
    assert completed["command_cycle_status"] == "COMPLETED"


def test_distinct_execute_cycle_is_blocked_while_one_cycle_is_in_flight(
    repository: OperatorRevealedOrderMovementRepository,
) -> None:
    _create_plan(repository)
    _begin(repository, suffix="one")

    with pytest.raises(
        OperatorRevealedOrderMovementConflict,
        match="operator_move_execute_in_flight",
    ):
        _begin(repository, suffix="two")


def test_cancelled_source_requires_proof_then_allows_one_replacement(
    repository: OperatorRevealedOrderMovementRepository,
) -> None:
    _create_plan(repository)
    _begin(repository)
    repository.claim_cancel(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        correlation_id="goal7-execute-one",
    )
    repository.record_cancel_outcome(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        outcome="CANCELLED",
        diagnostic_code="operator_move_source_cancelled",
    )
    _return_wallet_read(
        repository,
        correlation_id="goal7-execute-one",
    )
    repository.claim_read(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        category="SOURCE_POST_CANCEL",
        correlation_id="goal7-execute-one",
    )
    repository.record_read(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        category="SOURCE_POST_CANCEL",
        correlation_id="goal7-execute-one",
        result_code="CANCELLED",
    )
    repository.claim_create(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        correlation_id="goal7-execute-one",
    )
    accepted = repository.record_create_outcome(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        outcome="ACCEPTED",
        diagnostic_code="operator_move_replacement_accepted",
        replacement_exchange_order_id_sha256="b" * 64,
    )
    repository.claim_read(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        category="REPLACEMENT_POST_CREATE",
        correlation_id="goal7-execute-one",
    )
    repository.record_read(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        category="REPLACEMENT_POST_CREATE",
        correlation_id="goal7-execute-one",
        result_code="OPEN",
    )
    completed = repository.complete_command(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        phase="EXECUTE",
        correlation_id="goal7-execute-one",
        idempotency_key="goal7-execute-key-one",
    )

    assert accepted["state"] == "REPLACED"
    assert completed["cancel_call_count"] == 1
    assert completed["create_call_count"] == 1
    assert completed["read_call_count"] == 3
    assert completed["command_cycle_status"] == "COMPLETED"


def test_create_claim_requires_same_cycle_returned_wallet_read(
    repository: OperatorRevealedOrderMovementRepository,
) -> None:
    _create_plan(repository)
    _begin(repository)
    repository.claim_cancel(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        correlation_id="goal7-execute-one",
    )
    repository.record_cancel_outcome(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        outcome="CANCELLED",
        diagnostic_code="operator_move_source_cancelled",
    )

    with pytest.raises(
        OperatorRevealedOrderMovementConflict,
        match="operator_move_required_read_unavailable",
    ):
        repository.claim_create(
            stealth_order_id=str(_plan()["stealth_order_id"]),
            correlation_id="goal7-execute-one",
        )

    repository.claim_read(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        category="WALLET_PRE_CREATE",
        correlation_id="goal7-execute-one",
    )
    repository.record_read(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        category="WALLET_PRE_CREATE",
        correlation_id="goal7-execute-one",
        result_code="UNKNOWN",
    )
    with pytest.raises(
        OperatorRevealedOrderMovementConflict,
        match="operator_move_required_read_unavailable",
    ):
        repository.claim_create(
            stealth_order_id=str(_plan()["stealth_order_id"]),
            correlation_id="goal7-execute-one",
        )


def test_local_create_rejection_closes_without_consuming_create(
    repository: OperatorRevealedOrderMovementRepository,
) -> None:
    _create_plan(repository)
    _begin(repository)
    repository.claim_cancel(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        correlation_id="goal7-execute-one",
    )
    repository.record_cancel_outcome(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        outcome="CANCELLED",
        diagnostic_code="operator_move_source_cancelled",
    )

    rejected = repository.record_create_outcome(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        outcome="REJECTED",
        diagnostic_code="operator_move_replacement_rejected",
        replacement_exchange_order_id_sha256=None,
    )
    completed = repository.complete_command(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        phase="EXECUTE",
        correlation_id="goal7-execute-one",
        idempotency_key="goal7-execute-key-one",
    )

    assert rejected["state"] == "CREATE_REJECTED"
    assert rejected["cancel_call_count"] == 1
    assert rejected["create_allowance_consumed"] is False
    assert rejected["create_call_count"] == 0
    assert completed["command_cycle_status"] == "COMPLETED"


def test_restart_marks_claimed_cancel_unknown_and_closes_cycle(
    repository: OperatorRevealedOrderMovementRepository,
) -> None:
    _create_plan(repository)
    _begin(repository)
    repository.claim_read(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        category="SOURCE_PRE_CANCEL",
        correlation_id="goal7-execute-one",
    )
    repository.record_read(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        category="SOURCE_PRE_CANCEL",
        correlation_id="goal7-execute-one",
        result_code="OPEN",
    )
    repository.claim_cancel(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        correlation_id="goal7-execute-one",
    )

    restarted = OperatorRevealedOrderMovementRepository(
        repository.database,
        schema=repository.schema,
    )
    restarted.ensure_schema()
    restored = restarted.get_goal(str(_plan()["stealth_order_id"]))

    assert restored is not None
    assert restored["state"] == "CANCEL_UNKNOWN"
    assert restored["cancel_call_count"] == 1
    assert restored["create_call_count"] == 0
    assert restored["read_call_count"] == 1
    assert restored["command_cycle_status"] == "COMPLETED"
    assert restored["command_cycle_evidence_sha256"] is not None


def test_restart_marks_started_pre_cancel_read_unknown_and_closes_goal(
    repository: OperatorRevealedOrderMovementRepository,
) -> None:
    _create_plan(repository)
    _begin(repository)
    repository.claim_read(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        category="SOURCE_PRE_CANCEL",
        correlation_id="goal7-execute-one",
    )

    restarted = OperatorRevealedOrderMovementRepository(
        repository.database,
        schema=repository.schema,
    )
    restarted.ensure_schema()
    restored = restarted.get_goal(str(_plan()["stealth_order_id"]))

    assert restored is not None
    assert restored["state"] == "CANCEL_UNKNOWN"
    assert restored["diagnostic_code"] == (
        "operator_move_pre_cancel_read_unknown"
    )
    assert restored["cancel_allowance_consumed"] is False
    assert restored["cancel_call_count"] == 0
    assert restored["read_call_count"] == 1
    assert restored["command_cycle_status"] == "COMPLETED"


def test_restart_marks_started_wallet_read_unknown_and_prohibits_create(
    repository: OperatorRevealedOrderMovementRepository,
) -> None:
    _create_plan(repository)
    _begin(repository)
    repository.claim_cancel(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        correlation_id="goal7-execute-one",
    )
    repository.record_cancel_outcome(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        outcome="CANCELLED",
        diagnostic_code="operator_move_source_cancelled",
    )
    repository.claim_read(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        category="WALLET_PRE_CREATE",
        correlation_id="goal7-execute-one",
    )

    restarted = OperatorRevealedOrderMovementRepository(
        repository.database,
        schema=repository.schema,
    )
    restarted.ensure_schema()
    restored = restarted.get_goal(str(_plan()["stealth_order_id"]))

    assert restored is not None
    assert restored["state"] == "CREATE_UNKNOWN"
    assert restored["diagnostic_code"] == (
        "operator_move_wallet_read_unknown"
    )
    assert restored["create_allowance_consumed"] is False
    assert restored["create_call_count"] == 0
    assert restored["command_cycle_status"] == "COMPLETED"


def test_restart_after_confirmed_cancel_preserves_create_resume(
    repository: OperatorRevealedOrderMovementRepository,
) -> None:
    _create_plan(repository)
    _begin(repository)
    repository.claim_cancel(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        correlation_id="goal7-execute-one",
    )
    repository.record_cancel_outcome(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        outcome="CANCELLED",
        diagnostic_code="operator_move_source_cancelled",
    )

    restarted = OperatorRevealedOrderMovementRepository(
        repository.database,
        schema=repository.schema,
    )
    restarted.ensure_schema()
    restored = restarted.get_goal(str(_plan()["stealth_order_id"]))
    resumed = _begin(restarted, suffix="two")
    _return_wallet_read(
        restarted,
        correlation_id="goal7-execute-two",
    )
    restarted.claim_create(
        stealth_order_id=str(_plan()["stealth_order_id"]),
        correlation_id="goal7-execute-two",
    )

    assert restored is not None
    assert restored["state"] == "SOURCE_CANCELLED"
    assert restored["command_cycle_status"] == "COMPLETED"
    assert resumed["state"] == "SOURCE_CANCELLED"
    assert resumed["command_cycle_number"] == 3
    claimed = restarted.get_goal(str(_plan()["stealth_order_id"]))
    assert claimed is not None
    assert claimed["state"] == "CREATE_CLAIMED"
    assert claimed["cancel_call_count"] == 1
    assert claimed["create_call_count"] == 1
