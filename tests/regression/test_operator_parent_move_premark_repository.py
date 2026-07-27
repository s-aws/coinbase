from __future__ import annotations

import hashlib
import json
import os
import re
from threading import Event, Thread
import uuid

import pytest
from psycopg2 import sql
from psycopg2.errors import RaiseException

from application.admin_api.operator_parent_move_premark_runtime import (
    OperatorParentMoveLifecycleCoordinator,
)
from database.database import PostgresDB
from database.operator_parent_move_premark import (
    GOAL_ID,
    OperatorParentMovePremarkConflict,
    OperatorParentMovePremarkError,
    OperatorParentMovePremarkRepository,
)


pytestmark = [pytest.mark.regression, pytest.mark.serial]

TEST_DB_HOST = os.environ.get("COINBASE_DB_HOST", "coinbase-test-postgres")
TEST_DB_PORT = int(os.environ.get("COINBASE_DB_PORT", "9876"))
TEST_DB_NAME = os.environ.get("COINBASE_DB_NAME", "postgres")
TEST_DB_USER = os.environ.get("COINBASE_DB_USER", "postgres")
TEST_DB_PASSWORD = os.environ.get("COINBASE_DB_PASSWORD", "postgres")
_SCHEMA = re.compile(r"^test_operator_parent_move_[0-9a-f]{32}$")
OTHER_SOURCE_ID = "33333333-3333-4333-8333-333333333333"


@pytest.fixture
def repository() -> OperatorParentMovePremarkRepository:
    schema = f"test_operator_parent_move_{uuid.uuid4().hex}"
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
    repo = OperatorParentMovePremarkRepository(database, schema=schema)
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
    return {
        "goal_id": GOAL_ID,
        "source_client_order_id": (
            "11111111-1111-4111-8111-111111111111"
        ),
        "reserved_successor_client_order_id": (
            "22222222-2222-4222-8222-222222222222"
        ),
        "portfolio_scope_sha256": "a" * 64,
        "product_id": "BTC-USDC",
        "side": "BUY",
        "base_size": "0.00001",
        "source_limit_price": "60000.00",
        "replacement_limit_price": "60001.00",
        "submitted_notional": "0.6000100",
        "possible_execution_notional": "0.6000100",
        "submitted_notional_cap": "3.10",
        "possible_execution_notional_cap": "1.00",
        "post_only": True,
        "zero_fill_proven": True,
        "system_owned": True,
    }


def _plan_sha(plan: dict[str, object] | None = None) -> str:
    value = _plan() if plan is None else plan
    return _sha(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _create_plan(
    repository: OperatorParentMovePremarkRepository,
) -> dict[str, object]:
    plan = _plan()
    return repository.create_plan(
        plan=plan,
        plan_sha256=_plan_sha(plan),
        actor_id="private-operator-marker",
        correlation_id="goal14-plan-correlation",
        idempotency_key="goal14-plan-key",
        premark_request_sha256=_sha("goal14-plan-request"),
        payload_sha256=_sha("goal14-plan-payload"),
    )


def _begin_execute(
    repository: OperatorParentMovePremarkRepository,
    *,
    suffix: str = "one",
) -> dict[str, object]:
    return repository.begin_execute(
        source_client_order_id=str(_plan()["source_client_order_id"]),
        expected_plan_sha256=_plan_sha(),
        actor_id="private-operator-marker",
        correlation_id=f"goal14-execute-{suffix}",
        idempotency_key=f"goal14-execute-key-{suffix}",
        payload_sha256=_sha(f"goal14-execute-payload-{suffix}"),
    )


def _active_cycle_number(
    repository: OperatorParentMovePremarkRepository,
) -> int:
    projection = repository.get_goal(
        str(_plan()["source_client_order_id"])
    )
    assert projection is not None
    value = projection["active_cycle_number"]
    assert isinstance(value, int)
    return value


def _source_cancelled(
    repository: OperatorParentMovePremarkRepository,
) -> None:
    repository.activate_source_follow_up_suppression(
        source_client_order_id=str(_plan()["source_client_order_id"]),
        correlation_id="goal14-execute-one",
    )
    repository.claim_source_cancel(
        source_client_order_id=str(_plan()["source_client_order_id"]),
        correlation_id="goal14-execute-one",
    )
    repository.mark_source_cancel_boundary_crossed(
        source_client_order_id=str(_plan()["source_client_order_id"]),
        correlation_id="goal14-execute-one",
    )
    repository.record_source_cancel_outcome(
        source_client_order_id=str(_plan()["source_client_order_id"]),
        correlation_id="goal14-execute-one",
        cycle_number=_active_cycle_number(repository),
        outcome="CANCELLED",
        diagnostic_code="operator_parent_move_source_cancelled",
        exchange_evidence_sha256="c" * 64,
    )


def _replacement_created(
    repository: OperatorParentMovePremarkRepository,
) -> None:
    _source_cancelled(repository)
    repository.claim_replacement_create(
        source_client_order_id=str(_plan()["source_client_order_id"]),
        correlation_id="goal14-execute-one",
    )
    repository.mark_replacement_create_boundary_crossed(
        source_client_order_id=str(_plan()["source_client_order_id"]),
        correlation_id="goal14-execute-one",
    )
    repository.record_replacement_create_outcome(
        source_client_order_id=str(_plan()["source_client_order_id"]),
        correlation_id="goal14-execute-one",
        cycle_number=_active_cycle_number(repository),
        outcome="ACCEPTED",
        diagnostic_code="operator_parent_move_replacement_accepted",
        exchange_evidence_sha256="b" * 64,
    )


def test_plan_is_durable_sanitized_and_exactly_idempotent(
    repository: OperatorParentMovePremarkRepository,
) -> None:
    created = _create_plan(repository)
    replayed = _create_plan(repository)
    restarted = OperatorParentMovePremarkRepository(
        repository.database,
        schema=repository.schema,
    )
    restarted.ensure_schema()
    restored = restarted.get_goal(
        str(_plan()["source_client_order_id"])
    )

    assert created["state"] == "PLANNED"
    assert replayed["command_replayed"] is True
    assert restored is not None
    assert restored["plan_sha256"] == _plan_sha()
    assert restored["source_client_order_id"] == str(
        _plan()["source_client_order_id"]
    )
    assert restored["reserved_successor_client_order_id"] == str(
        _plan()["reserved_successor_client_order_id"]
    )
    assert restored["latest_cycle_number"] == 1
    assert restored["latest_cycle_phase"] == "PLAN"
    assert restored["latest_cycle_status"] == "COMPLETED"
    assert restored["latest_cycle_correlation_id"] == (
        "goal14-plan-correlation"
    )
    assert restored["latest_cycle_actor_id_sha256"] == _sha(
        "private-operator-marker"
    )
    assert restored["latest_cycle_idempotency_key_sha256"] == _sha(
        "goal14-plan-key"
    )
    assert restored["latest_cycle_payload_sha256"] == _sha(
        "goal14-plan-payload"
    )
    assert re.fullmatch(
        r"[0-9a-f]{64}",
        str(restored["latest_cycle_evidence_sha256"]),
    )
    serialized = json.dumps(restored)
    assert "private-operator-marker" not in serialized
    assert "goal14-plan-key" not in serialized

    replayed_after_drift = repository.get_premark_replay(
        source_client_order_id=str(_plan()["source_client_order_id"]),
        actor_id="private-operator-marker",
        correlation_id="goal14-plan-correlation",
        idempotency_key="goal14-plan-key",
        premark_request_sha256=_sha("goal14-plan-request"),
    )
    assert replayed_after_drift is not None
    assert replayed_after_drift["command_replayed"] is True


def test_goal_global_readback_rejects_a_different_source_after_plan(
    repository: OperatorParentMovePremarkRepository,
) -> None:
    _create_plan(repository)

    with pytest.raises(
        OperatorParentMovePremarkConflict,
        match="operator_parent_move_goal_allowance_unavailable",
    ):
        repository.get_goal(OTHER_SOURCE_ID)


def test_idempotency_keys_are_hash_only_at_rest_and_legacy_columns_migrate(
    repository: OperatorParentMovePremarkRepository,
) -> None:
    _create_plan(repository)
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT plan_idempotency_key_sha256
            FROM {repository.prefix}operator_parent_move_premark_goal
            WHERE goal_id = %s
            """,
            (GOAL_ID,),
        )
        assert cursor.fetchone()[0] == _sha("goal14-plan-key")
        cursor.execute(
            f"""
            SELECT idempotency_key_sha256
            FROM {repository.prefix}operator_parent_move_premark_cycle
            WHERE goal_id = %s AND cycle_number = 1
            """,
            (GOAL_ID,),
        )
        assert cursor.fetchone()[0] == _sha("goal14-plan-key")
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name IN (
                  'operator_parent_move_premark_goal',
                  'operator_parent_move_premark_cycle'
              )
              AND column_name IN (
                  'plan_idempotency_key', 'idempotency_key'
              )
            """,
            (repository.schema,),
        )
        assert cursor.fetchall() == []

        cursor.execute(
            f"""
            ALTER TABLE {repository.prefix}operator_parent_move_premark_goal
            RENAME COLUMN plan_idempotency_key_sha256
            TO plan_idempotency_key
            """
        )
        cursor.execute(
            f"""
            ALTER TABLE {repository.prefix}operator_parent_move_premark_cycle
            RENAME COLUMN idempotency_key_sha256 TO idempotency_key
            """
        )
        cursor.execute(
            """
            SELECT c.relname, con.conname
            FROM pg_constraint AS con
            JOIN pg_class AS c ON c.oid = con.conrelid
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = %s
              AND c.relname IN (
                  'operator_parent_move_premark_goal',
                  'operator_parent_move_premark_cycle'
              )
              AND con.contype = 'c'
              AND pg_get_constraintdef(con.oid) LIKE '%%idempotency%%'
            """,
            (repository.schema,),
        )
        for table_name, constraint_name in cursor.fetchall():
            cursor.execute(
                sql.SQL("ALTER TABLE {}.{} DROP CONSTRAINT {}").format(
                    sql.Identifier(repository.schema),
                    sql.Identifier(table_name),
                    sql.Identifier(constraint_name),
                )
            )
        cursor.execute(
            f"""
            UPDATE {repository.prefix}operator_parent_move_premark_goal
            SET plan_idempotency_key = %s
            WHERE goal_id = %s
            """,
            ("goal14-plan-key", GOAL_ID),
        )
        cursor.execute(
            f"""
            UPDATE {repository.prefix}operator_parent_move_premark_cycle
            SET idempotency_key = %s
            WHERE goal_id = %s
            """,
            ("goal14-plan-key", GOAL_ID),
        )

    repository.ensure_schema()
    restored = repository.get_goal(str(_plan()["source_client_order_id"]))
    assert restored is not None
    assert restored["latest_cycle_idempotency_key_sha256"] == _sha(
        "goal14-plan-key"
    )


def test_legacy_missing_request_binding_is_explicitly_fail_closed(
    repository: OperatorParentMovePremarkRepository,
) -> None:
    _create_plan(repository)
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            ALTER TABLE
                {repository.prefix}operator_parent_move_premark_goal
            DROP COLUMN plan_request_sha256
            """
        )
        cursor.execute(
            f"""
            ALTER TABLE
                {repository.prefix}operator_parent_move_premark_goal
            DROP COLUMN plan_request_binding_legacy
            """
        )

    repository.ensure_schema()

    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT plan_request_sha256, plan_request_binding_legacy
            FROM {repository.prefix}operator_parent_move_premark_goal
            WHERE goal_id = %s
            """,
            (GOAL_ID,),
        )
        request_hash, legacy_binding = cursor.fetchone()
        assert re.fullmatch(r"[0-9a-f]{64}", request_hash)
        assert legacy_binding is True
        cursor.execute(
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name =
                  'operator_parent_move_premark_goal'
              AND column_name = 'plan_request_sha256'
            """,
            (repository.schema,),
        )
        assert cursor.fetchone()[0] == "NO"

    with pytest.raises(
        OperatorParentMovePremarkConflict,
        match=(
            "operator_parent_move_legacy_request_binding_unavailable"
        ),
    ):
        repository.get_premark_replay(
            source_client_order_id=str(
                _plan()["source_client_order_id"]
            ),
            actor_id="private-operator-marker",
            correlation_id="goal14-plan-correlation",
            idempotency_key="goal14-plan-key",
            premark_request_sha256=_sha("goal14-plan-request"),
        )


def test_plan_idempotency_conflicts_on_any_binding_drift(
    repository: OperatorParentMovePremarkRepository,
) -> None:
    _create_plan(repository)
    with pytest.raises(
        OperatorParentMovePremarkConflict,
        match="operator_parent_move_idempotency_conflict",
    ):
        repository.create_plan(
            plan=_plan(),
            plan_sha256=_plan_sha(),
            actor_id="different-operator",
            correlation_id="goal14-plan-correlation",
            idempotency_key="goal14-plan-key",
            premark_request_sha256=_sha("goal14-plan-request"),
            payload_sha256=_sha("goal14-plan-payload"),
        )


def test_plan_rejects_forbidden_raw_or_secret_fields(
    repository: OperatorParentMovePremarkRepository,
) -> None:
    for forbidden_key in (
        "raw_response",
        "exchange_order_id",
        "exception_message",
        "api_secret",
    ):
        plan = _plan()
        plan[forbidden_key] = "must-not-persist"
        with pytest.raises(
            OperatorParentMovePremarkError,
            match="operator_parent_move_plan_not_sanitized",
        ):
            repository.create_plan(
                plan=plan,
                plan_sha256=_plan_sha(plan),
                actor_id="operator",
                correlation_id=f"goal14-{forbidden_key}",
                idempotency_key=f"goal14-{forbidden_key}",
                premark_request_sha256=_sha(forbidden_key),
                payload_sha256=_sha(forbidden_key),
            )


def test_source_cancel_requires_durable_suppression_and_restart_consumes_boundary(
    repository: OperatorParentMovePremarkRepository,
) -> None:
    _create_plan(repository)
    _begin_execute(repository)
    source_id = str(_plan()["source_client_order_id"])

    assert repository.is_source_follow_up_suppressed(source_id) is False
    with pytest.raises(
        OperatorParentMovePremarkConflict,
        match="operator_parent_move_source_suppression_required",
    ):
        repository.claim_source_cancel(
            source_client_order_id=source_id,
            correlation_id="goal14-execute-one",
        )

    repository.activate_source_follow_up_suppression(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
    )
    assert repository.is_source_follow_up_suppressed(source_id) is True
    repository.claim_source_cancel(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
    )
    repository.mark_source_cancel_boundary_crossed(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
    )

    restarted = OperatorParentMovePremarkRepository(
        repository.database,
        schema=repository.schema,
    )
    restarted.ensure_schema()
    before_recovery = restarted.get_goal(source_id)
    assert before_recovery is not None
    assert before_recovery["state"] == "SOURCE_CANCEL_BOUNDARY_CROSSED"
    assert before_recovery["latest_cycle_status"] == "IN_FLIGHT"

    restarted.recover_stranded_work()
    restored = restarted.get_goal(source_id)

    assert restored is not None
    assert restored["state"] == "SOURCE_CANCEL_UNKNOWN"
    assert restored["source_cancel_allowance_consumed"] is True
    assert restored["source_cancel_call_count"] == 1
    assert restarted.is_source_follow_up_suppressed(source_id) is True
    with pytest.raises(
        OperatorParentMovePremarkConflict,
        match="operator_parent_move_mutation_allowance_unavailable",
    ):
        restarted.claim_source_cancel(
            source_client_order_id=source_id,
            correlation_id="goal14-execute-one",
        )
    assert restarted.acknowledge_source_cancel_event_suppression(source_id)
    assert restarted.is_source_follow_up_suppressed(source_id) is False
    assert restarted.should_suppress_source_cancel_follow_up(source_id)


def test_legacy_cleared_source_fence_is_rearmed_before_ingress(
    repository: OperatorParentMovePremarkRepository,
) -> None:
    _create_plan(repository)
    _begin_execute(repository)
    _replacement_created(repository)
    source_id = str(_plan()["source_client_order_id"])
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {repository.prefix}operator_parent_move_premark_goal
            SET source_follow_up_suppressed = FALSE,
                suppression_correlation_id = NULL
            WHERE goal_id = %s
            """,
            (GOAL_ID,),
        )
        cursor.execute(
            f"""
            ALTER TABLE
                {repository.prefix}operator_parent_move_premark_goal
            DROP COLUMN source_cancel_event_acknowledged
            """
        )

    restarted = OperatorParentMovePremarkRepository(
        repository.database,
        schema=repository.schema,
    )
    restarted.ensure_schema()

    restored = restarted.get_goal(source_id)
    assert restored is not None
    assert restored["source_follow_up_suppressed"] is True
    assert restored["source_cancel_event_acknowledged"] is False
    assert restarted.should_suppress_source_cancel_follow_up(source_id)
    assert restarted.acknowledge_source_cancel_event_suppression(source_id)
    assert restarted.is_source_follow_up_suppressed(source_id) is False
    assert restarted.should_suppress_source_cancel_follow_up(source_id)


@pytest.mark.parametrize("claim_source", [False, True])
def test_restart_recovers_pre_boundary_execute_without_consuming_allowance(
    repository: OperatorParentMovePremarkRepository,
    claim_source: bool,
) -> None:
    _create_plan(repository)
    _begin_execute(repository)
    source_id = str(_plan()["source_client_order_id"])
    repository.activate_source_follow_up_suppression(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
    )
    if claim_source:
        repository.claim_source_cancel(
            source_client_order_id=source_id,
            correlation_id="goal14-execute-one",
        )

    restarted = OperatorParentMovePremarkRepository(
        repository.database,
        schema=repository.schema,
    )
    restarted.ensure_schema()
    restarted.recover_stranded_work()
    restored = restarted.get_goal(source_id)

    assert restored is not None
    assert restored["state"] == "PLANNED"
    assert restored["source_follow_up_suppressed"] is False
    assert restored["source_cancel_allowance_consumed"] is False
    assert restored["source_cancel_call_count"] == 0
    assert restored["latest_cycle_status"] == "COMPLETED"

    _begin_execute(restarted, suffix="two")
    restarted.activate_source_follow_up_suppression(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-two",
    )
    reclaimed = restarted.claim_source_cancel(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-two",
    )
    assert reclaimed["state"] == "SOURCE_CANCEL_CLAIMED"
    assert reclaimed["source_cancel_allowance_consumed"] is False


def test_execute_claims_are_ordered_nontransferable_and_exactly_once(
    repository: OperatorParentMovePremarkRepository,
) -> None:
    _create_plan(repository)
    _begin_execute(repository)
    _source_cancelled(repository)

    repository.claim_replacement_create(
        source_client_order_id=str(_plan()["source_client_order_id"]),
        correlation_id="goal14-execute-one",
    )
    repository.mark_replacement_create_boundary_crossed(
        source_client_order_id=str(_plan()["source_client_order_id"]),
        correlation_id="goal14-execute-one",
    )
    accepted = repository.record_replacement_create_outcome(
        source_client_order_id=str(_plan()["source_client_order_id"]),
        correlation_id="goal14-execute-one",
        cycle_number=_active_cycle_number(repository),
        outcome="ACCEPTED",
        diagnostic_code="operator_parent_move_replacement_accepted",
        exchange_evidence_sha256="b" * 64,
    )
    with pytest.raises(
        OperatorParentMovePremarkConflict,
        match="operator_parent_move_source_suppression_ack_required",
    ):
        repository.finalize_source_follow_up_suppression(
            source_client_order_id=str(_plan()["source_client_order_id"]),
            diagnostic_code=(
                "operator_parent_move_source_suppression_finalized"
            ),
        )
    acknowledged = (
        repository.acknowledge_source_cancel_event_suppression(
            str(_plan()["source_client_order_id"])
        )
    )

    assert accepted["state"] == "REPLACEMENT_CREATED"
    assert accepted["source_cancel_call_count"] == 1
    assert accepted["replacement_create_call_count"] == 1
    assert accepted["successor_closeout_cancel_call_count"] == 0
    assert acknowledged is True
    assert (
        repository.is_source_follow_up_suppressed(
            str(_plan()["source_client_order_id"])
        )
        is False
    )
    assert (
        repository.should_suppress_source_cancel_follow_up(
            str(_plan()["source_client_order_id"])
        )
        is True
    )
    with pytest.raises(
        OperatorParentMovePremarkConflict,
        match="operator_parent_move_mutation_allowance_unavailable",
    ):
        repository.claim_replacement_create(
            source_client_order_id=str(_plan()["source_client_order_id"]),
            correlation_id="goal14-execute-one",
        )


def test_exact_execute_replay_is_read_before_terminal_source_drift(
    repository: OperatorParentMovePremarkRepository,
) -> None:
    _create_plan(repository)
    _begin_execute(repository)
    _replacement_created(repository)
    source_id = str(_plan()["source_client_order_id"])
    repository.complete_cycle(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
        idempotency_key="goal14-execute-key-one",
        diagnostic_code="operator_parent_move_execute_completed",
    )

    replayed = repository.get_execute_replay(
        source_client_order_id=source_id,
        expected_plan_sha256=_plan_sha(),
        actor_id="private-operator-marker",
        correlation_id="goal14-execute-one",
        idempotency_key="goal14-execute-key-one",
        payload_sha256=_sha("goal14-execute-payload-one"),
    )

    assert replayed is not None
    assert replayed["state"] == "REPLACEMENT_CREATED"
    assert replayed["command_replayed"] is True
    assert replayed["cycle_count"] == 2
    assert replayed["latest_cycle_phase"] == "EXECUTE"
    assert replayed["latest_cycle_status"] == "COMPLETED"

    with pytest.raises(
        OperatorParentMovePremarkConflict,
        match="operator_parent_move_idempotency_conflict",
    ):
        repository.get_execute_replay(
            source_client_order_id=source_id,
            expected_plan_sha256=_plan_sha(),
            actor_id="private-operator-marker",
            correlation_id="goal14-execute-one",
            idempotency_key="goal14-execute-key-one",
            payload_sha256=_sha("different-execute-payload"),
        )


def test_pre_boundary_rejection_is_terminal_without_consuming_call(
    repository: OperatorParentMovePremarkRepository,
) -> None:
    _create_plan(repository)
    _begin_execute(repository)
    source_id = str(_plan()["source_client_order_id"])
    repository.activate_source_follow_up_suppression(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
    )
    repository.claim_source_cancel(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
    )

    rejected = repository.record_source_cancel_outcome(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
        cycle_number=_active_cycle_number(repository),
        outcome="REJECTED",
        diagnostic_code="operator_parent_move_source_cancel_rejected",
    )
    finalized = repository.finalize_source_follow_up_suppression(
        source_client_order_id=source_id,
        diagnostic_code="operator_parent_move_source_suppression_finalized",
    )

    assert rejected["state"] == "SOURCE_CANCEL_REJECTED"
    assert rejected["source_cancel_allowance_consumed"] is False
    assert rejected["source_cancel_call_count"] == 0
    assert finalized["source_follow_up_suppressed"] is False


def test_crossed_success_outcome_requires_sanitized_exchange_evidence(
    repository: OperatorParentMovePremarkRepository,
) -> None:
    _create_plan(repository)
    _begin_execute(repository)
    source_id = str(_plan()["source_client_order_id"])
    repository.activate_source_follow_up_suppression(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
    )
    repository.claim_source_cancel(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
    )
    repository.mark_source_cancel_boundary_crossed(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
    )

    with pytest.raises(
        OperatorParentMovePremarkConflict,
        match="operator_parent_move_exchange_evidence_required",
    ):
        repository.record_source_cancel_outcome(
            source_client_order_id=source_id,
            correlation_id="goal14-execute-one",
            cycle_number=_active_cycle_number(repository),
            outcome="CANCELLED",
            diagnostic_code="operator_parent_move_source_cancelled",
        )


def test_pre_boundary_abort_releases_unconsumed_claim_for_later_cycle(
    repository: OperatorParentMovePremarkRepository,
) -> None:
    _create_plan(repository)
    _begin_execute(repository)
    source_id = str(_plan()["source_client_order_id"])
    repository.activate_source_follow_up_suppression(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
    )
    repository.claim_source_cancel(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
    )
    aborted = repository.abort_source_cancel_before_boundary(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
        diagnostic_code="operator_parent_move_source_cancel_pre_call_abort",
    )
    completed = repository.complete_cycle(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
        idempotency_key="goal14-execute-key-one",
        diagnostic_code="operator_parent_move_source_cancel_pre_call_abort",
    )

    assert aborted["state"] == "PLANNED"
    assert aborted["source_cancel_allowance_consumed"] is False
    assert aborted["source_cancel_call_count"] == 0
    assert aborted["source_follow_up_suppressed"] is False
    assert completed["latest_cycle_number"] == 2
    assert completed["latest_cycle_status"] == "COMPLETED"
    assert completed["latest_cycle_idempotency_key_sha256"] == _sha(
        "goal14-execute-key-one"
    )
    assert re.fullmatch(
        r"[0-9a-f]{64}",
        str(completed["latest_cycle_evidence_sha256"]),
    )

    _begin_execute(repository, suffix="two")
    repository.activate_source_follow_up_suppression(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-two",
    )
    reclaimed = repository.claim_source_cancel(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-two",
    )
    assert reclaimed["state"] == "SOURCE_CANCEL_CLAIMED"
    assert reclaimed["source_cancel_allowance_consumed"] is False


def test_stale_aborted_claim_outcome_cannot_resolve_reused_claim(
    repository: OperatorParentMovePremarkRepository,
) -> None:
    _create_plan(repository)
    first = _begin_execute(repository)
    source_id = str(_plan()["source_client_order_id"])
    first_cycle = int(first["active_cycle_number"])
    repository.activate_source_follow_up_suppression(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
    )
    repository.claim_source_cancel(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
    )
    repository.abort_source_cancel_before_boundary(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
        diagnostic_code="operator_parent_move_source_cancel_pre_call_abort",
    )
    repository.complete_cycle(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
        idempotency_key="goal14-execute-key-one",
        diagnostic_code="operator_parent_move_source_cancel_pre_call_abort",
    )

    second = _begin_execute(repository, suffix="two")
    second_cycle = int(second["active_cycle_number"])
    assert second_cycle > first_cycle
    repository.activate_source_follow_up_suppression(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-two",
    )
    repository.claim_source_cancel(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-two",
    )

    with pytest.raises(
        OperatorParentMovePremarkConflict,
        match="operator_parent_move_mutation_outcome_conflict",
    ):
        repository.record_source_cancel_outcome(
            source_client_order_id=source_id,
            correlation_id="goal14-execute-one",
            cycle_number=first_cycle,
            outcome="REJECTED",
            diagnostic_code="operator_parent_move_source_cancel_rejected",
        )

    unchanged = repository.get_goal(source_id)
    assert unchanged is not None
    assert unchanged["state"] == "SOURCE_CANCEL_CLAIMED"
    assert unchanged["active_cycle_number"] == second_cycle
    assert unchanged["source_cancel_allowance_consumed"] is False
    assert unchanged["source_cancel_call_count"] == 0

    exact = repository.record_source_cancel_outcome(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-two",
        cycle_number=second_cycle,
        outcome="REJECTED",
        diagnostic_code="operator_parent_move_source_cancel_rejected",
    )
    assert exact["state"] == "SOURCE_CANCEL_REJECTED"


def test_restart_finalizes_known_rejected_source_suppression(
    repository: OperatorParentMovePremarkRepository,
) -> None:
    _create_plan(repository)
    begun = _begin_execute(repository)
    source_id = str(_plan()["source_client_order_id"])
    cycle_number = int(begun["active_cycle_number"])
    repository.activate_source_follow_up_suppression(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
    )
    repository.claim_source_cancel(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
    )
    rejected = repository.record_source_cancel_outcome(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
        cycle_number=cycle_number,
        outcome="REJECTED",
        diagnostic_code="operator_parent_move_source_cancel_rejected",
    )
    assert rejected["source_follow_up_suppressed"] is True

    restarted = OperatorParentMovePremarkRepository(
        repository.database,
        schema=repository.schema,
    )
    restarted.ensure_schema()
    before_recovery = restarted.get_goal(source_id)
    assert before_recovery is not None
    assert before_recovery["state"] == "SOURCE_CANCEL_REJECTED"
    assert before_recovery["source_follow_up_suppressed"] is True
    assert before_recovery["latest_cycle_status"] == "IN_FLIGHT"

    restarted.recover_stranded_work()
    restored = restarted.get_goal(source_id)
    assert restored is not None
    assert restored["state"] == "SOURCE_CANCEL_REJECTED"
    assert restored["source_follow_up_suppressed"] is False
    assert restored["source_cancel_allowance_consumed"] is False
    assert restored["source_cancel_call_count"] == 0
    assert restored["latest_cycle_status"] == "COMPLETED"


def test_recovery_waits_for_live_lifecycle_owner(
    repository: OperatorParentMovePremarkRepository,
    tmp_path,
) -> None:
    _create_plan(repository)
    begun = _begin_execute(repository)
    source_id = str(_plan()["source_client_order_id"])
    cycle_number = int(begun["active_cycle_number"])
    first = OperatorParentMoveLifecycleCoordinator(lock_root=tmp_path)
    second = OperatorParentMoveLifecycleCoordinator(lock_root=tmp_path)
    recovery_started = Event()
    recovery_finished = Event()
    recovery_errors: list[type[BaseException]] = []
    restarted = OperatorParentMovePremarkRepository(
        repository.database,
        schema=repository.schema,
    )
    restarted.ensure_schema()

    def recover() -> None:
        recovery_started.set()
        try:
            with second.exclusive():
                restarted.recover_stranded_work()
        except BaseException as exc:
            recovery_errors.append(type(exc))
        finally:
            recovery_finished.set()

    with first.exclusive():
        repository.activate_source_follow_up_suppression(
            source_client_order_id=source_id,
            correlation_id="goal14-execute-one",
        )
        repository.claim_source_cancel(
            source_client_order_id=source_id,
            correlation_id="goal14-execute-one",
        )
        repository.mark_source_cancel_boundary_crossed(
            source_client_order_id=source_id,
            correlation_id="goal14-execute-one",
        )
        recovery_thread = Thread(target=recover)
        recovery_thread.start()
        assert recovery_started.wait(timeout=2)
        assert recovery_finished.wait(timeout=0.1) is False
        still_active = repository.get_goal(source_id)
        assert still_active is not None
        assert still_active["state"] == "SOURCE_CANCEL_BOUNDARY_CROSSED"
        repository.record_source_cancel_outcome(
            source_client_order_id=source_id,
            correlation_id="goal14-execute-one",
            cycle_number=cycle_number,
            outcome="UNKNOWN",
            diagnostic_code="operator_parent_move_source_cancel_unknown",
        )
        repository.complete_cycle(
            source_client_order_id=source_id,
            correlation_id="goal14-execute-one",
            idempotency_key="goal14-execute-key-one",
            diagnostic_code="operator_parent_move_source_cancel_unknown",
        )

    assert recovery_finished.wait(timeout=2)
    recovery_thread.join(timeout=2)
    assert recovery_thread.is_alive() is False
    assert recovery_errors == []
    restored = repository.get_goal(source_id)
    assert restored is not None
    assert restored["state"] == "SOURCE_CANCEL_UNKNOWN"
    assert restored["latest_cycle_status"] == "COMPLETED"


def test_restart_keeps_unknown_source_suppression_fail_closed(
    repository: OperatorParentMovePremarkRepository,
) -> None:
    _create_plan(repository)
    begun = _begin_execute(repository)
    source_id = str(_plan()["source_client_order_id"])
    repository.activate_source_follow_up_suppression(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
    )
    repository.claim_source_cancel(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
    )
    repository.record_source_cancel_outcome(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
        cycle_number=int(begun["active_cycle_number"]),
        outcome="UNKNOWN",
        diagnostic_code="operator_parent_move_source_cancel_unknown",
    )

    restarted = OperatorParentMovePremarkRepository(
        repository.database,
        schema=repository.schema,
    )
    restarted.ensure_schema()
    restarted.recover_stranded_work()
    restored = restarted.get_goal(source_id)

    assert restored is not None
    assert restored["state"] == "SOURCE_CANCEL_UNKNOWN"
    assert restored["source_follow_up_suppressed"] is True
    assert restored["latest_cycle_status"] == "COMPLETED"


@pytest.mark.parametrize("cancel_event_acknowledged", [False, True])
def test_restart_recovers_replacement_claim_for_create_only_resume(
    repository: OperatorParentMovePremarkRepository,
    cancel_event_acknowledged: bool,
) -> None:
    _create_plan(repository)
    _begin_execute(repository)
    _source_cancelled(repository)
    source_id = str(_plan()["source_client_order_id"])
    if cancel_event_acknowledged:
        assert repository.acknowledge_source_cancel_event_suppression(
            source_id
        )
    repository.claim_replacement_create(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
    )

    restarted = OperatorParentMovePremarkRepository(
        repository.database,
        schema=repository.schema,
    )
    restarted.ensure_schema()
    restarted.recover_stranded_work()
    restored = restarted.get_goal(source_id)

    assert restored is not None
    assert restored["state"] == "SOURCE_CANCELLED"
    assert restored["source_cancel_allowance_consumed"] is True
    assert restored["source_cancel_call_count"] == 1
    assert restored["replacement_create_allowance_consumed"] is False
    assert restored["replacement_create_call_count"] == 0
    assert restored["source_cancel_event_acknowledged"] is (
        cancel_event_acknowledged
    )
    assert restarted.should_suppress_source_cancel_follow_up(source_id)

    resumed = _begin_execute(restarted, suffix="two")
    assert resumed["state"] == "SOURCE_CANCELLED"
    reclaimed = restarted.claim_replacement_create(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-two",
    )
    assert reclaimed["state"] == "REPLACEMENT_CREATE_CLAIMED"


@pytest.mark.parametrize("claim_closeout", [False, True])
def test_restart_recovers_pre_boundary_closeout_without_consuming_allowance(
    repository: OperatorParentMovePremarkRepository,
    claim_closeout: bool,
) -> None:
    _create_plan(repository)
    _begin_execute(repository)
    _replacement_created(repository)
    source_id = str(_plan()["source_client_order_id"])
    successor_id = str(_plan()["reserved_successor_client_order_id"])
    assert repository.acknowledge_source_cancel_event_suppression(source_id)
    repository.complete_cycle(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
        idempotency_key="goal14-execute-key-one",
        diagnostic_code="operator_parent_move_execute_completed",
    )
    repository.begin_closeout(
        source_client_order_id=source_id,
        reserved_successor_client_order_id=successor_id,
        expected_plan_sha256=_plan_sha(),
        actor_id="operator",
        correlation_id="goal14-closeout-one",
        idempotency_key="goal14-closeout-key-one",
        payload_sha256=_sha("goal14-closeout-payload-one"),
    )
    if claim_closeout:
        repository.claim_successor_closeout_cancel(
            source_client_order_id=source_id,
            reserved_successor_client_order_id=successor_id,
            correlation_id="goal14-closeout-one",
        )

    restarted = OperatorParentMovePremarkRepository(
        repository.database,
        schema=repository.schema,
    )
    restarted.ensure_schema()
    restarted.recover_stranded_work()
    restored = restarted.get_goal(source_id)

    assert restored is not None
    assert restored["state"] == "REPLACEMENT_CREATED"
    assert restored["successor_closeout_cancel_allowance_consumed"] is False
    assert restored["successor_closeout_cancel_call_count"] == 0
    assert restored["latest_cycle_status"] == "COMPLETED"

    restarted.begin_closeout(
        source_client_order_id=source_id,
        reserved_successor_client_order_id=successor_id,
        expected_plan_sha256=_plan_sha(),
        actor_id="operator",
        correlation_id="goal14-closeout-two",
        idempotency_key="goal14-closeout-key-two",
        payload_sha256=_sha("goal14-closeout-payload-two"),
    )
    reclaimed = restarted.claim_successor_closeout_cancel(
        source_client_order_id=source_id,
        reserved_successor_client_order_id=successor_id,
        correlation_id="goal14-closeout-two",
    )
    assert reclaimed["state"] == "SUCCESSOR_CLOSEOUT_CANCEL_CLAIMED"


def test_closeout_is_bound_to_reserved_successor_and_unknown_on_restart(
    repository: OperatorParentMovePremarkRepository,
) -> None:
    _create_plan(repository)
    _begin_execute(repository)
    _replacement_created(repository)
    assert repository.acknowledge_source_cancel_event_suppression(
        str(_plan()["source_client_order_id"])
    )
    repository.complete_cycle(
        source_client_order_id=str(_plan()["source_client_order_id"]),
        correlation_id="goal14-execute-one",
        idempotency_key="goal14-execute-key-one",
        diagnostic_code="operator_parent_move_execute_completed",
    )
    repository.begin_closeout(
        source_client_order_id=str(_plan()["source_client_order_id"]),
        reserved_successor_client_order_id=str(
            _plan()["reserved_successor_client_order_id"]
        ),
        expected_plan_sha256=_plan_sha(),
        actor_id="operator",
        correlation_id="goal14-closeout-one",
        idempotency_key="goal14-closeout-key-one",
        payload_sha256=_sha("goal14-closeout-payload-one"),
    )
    repository.claim_successor_closeout_cancel(
        source_client_order_id=str(_plan()["source_client_order_id"]),
        reserved_successor_client_order_id=str(
            _plan()["reserved_successor_client_order_id"]
        ),
        correlation_id="goal14-closeout-one",
    )
    repository.mark_successor_closeout_cancel_boundary_crossed(
        source_client_order_id=str(_plan()["source_client_order_id"]),
        reserved_successor_client_order_id=str(
            _plan()["reserved_successor_client_order_id"]
        ),
        correlation_id="goal14-closeout-one",
    )

    restarted = OperatorParentMovePremarkRepository(
        repository.database,
        schema=repository.schema,
    )
    restarted.ensure_schema()
    restarted.recover_stranded_work()
    restored = restarted.get_goal(
        str(_plan()["source_client_order_id"])
    )

    assert restored is not None
    assert restored["state"] == "SUCCESSOR_CLOSEOUT_CANCEL_UNKNOWN"
    assert restored["successor_closeout_cancel_allowance_consumed"] is True
    assert restored["successor_closeout_cancel_call_count"] == 1


def test_create_and_closeout_pre_boundary_aborts_preserve_allowances(
    repository: OperatorParentMovePremarkRepository,
) -> None:
    _create_plan(repository)
    _begin_execute(repository)
    _source_cancelled(repository)
    source_id = str(_plan()["source_client_order_id"])
    successor_id = str(_plan()["reserved_successor_client_order_id"])
    repository.claim_replacement_create(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
    )
    create_aborted = repository.abort_replacement_create_before_boundary(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
        diagnostic_code=(
            "operator_parent_move_replacement_create_pre_call_abort"
        ),
    )
    assert create_aborted["state"] == "SOURCE_CANCELLED"
    assert create_aborted["replacement_create_allowance_consumed"] is False
    with pytest.raises(
        OperatorParentMovePremarkConflict,
        match="operator_parent_move_mutation_allowance_unavailable",
    ):
        repository.claim_replacement_create(
            source_client_order_id=source_id,
            correlation_id="goal14-execute-one",
        )
    repository.complete_cycle(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-one",
        idempotency_key="goal14-execute-key-one",
        diagnostic_code=(
            "operator_parent_move_replacement_create_pre_call_abort"
        ),
    )
    _begin_execute(repository, suffix="two")
    repository.claim_replacement_create(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-two",
    )
    repository.mark_replacement_create_boundary_crossed(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-two",
    )
    repository.record_replacement_create_outcome(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-two",
        cycle_number=_active_cycle_number(repository),
        outcome="ACCEPTED",
        diagnostic_code="operator_parent_move_replacement_accepted",
        exchange_evidence_sha256="b" * 64,
    )
    assert repository.acknowledge_source_cancel_event_suppression(source_id)
    repository.complete_cycle(
        source_client_order_id=source_id,
        correlation_id="goal14-execute-two",
        idempotency_key="goal14-execute-key-two",
        diagnostic_code="operator_parent_move_execute_completed",
    )
    repository.begin_closeout(
        source_client_order_id=source_id,
        reserved_successor_client_order_id=successor_id,
        expected_plan_sha256=_plan_sha(),
        actor_id="operator",
        correlation_id="goal14-closeout-abort",
        idempotency_key="goal14-closeout-abort",
        payload_sha256=_sha("goal14-closeout-abort"),
    )
    repository.claim_successor_closeout_cancel(
        source_client_order_id=source_id,
        reserved_successor_client_order_id=successor_id,
        correlation_id="goal14-closeout-abort",
    )
    closeout_aborted = (
        repository.abort_successor_closeout_cancel_before_boundary(
            source_client_order_id=source_id,
            reserved_successor_client_order_id=successor_id,
            correlation_id="goal14-closeout-abort",
            diagnostic_code=(
                "operator_parent_move_closeout_cancel_pre_call_abort"
            ),
        )
    )
    assert closeout_aborted["state"] == "REPLACEMENT_CREATED"
    assert (
        closeout_aborted[
            "successor_closeout_cancel_allowance_consumed"
        ]
        is False
    )
    with pytest.raises(
        OperatorParentMovePremarkConflict,
        match="operator_parent_move_mutation_allowance_unavailable",
    ):
        repository.claim_successor_closeout_cancel(
            source_client_order_id=source_id,
            reserved_successor_client_order_id=successor_id,
            correlation_id="goal14-closeout-abort",
        )
    repository.complete_cycle(
        source_client_order_id=source_id,
        correlation_id="goal14-closeout-abort",
        idempotency_key="goal14-closeout-abort",
        diagnostic_code=(
            "operator_parent_move_closeout_cancel_pre_call_abort"
        ),
    )
    repository.begin_closeout(
        source_client_order_id=source_id,
        reserved_successor_client_order_id=successor_id,
        expected_plan_sha256=_plan_sha(),
        actor_id="operator",
        correlation_id="goal14-closeout-two",
        idempotency_key="goal14-closeout-two",
        payload_sha256=_sha("goal14-closeout-two"),
    )
    repository.claim_successor_closeout_cancel(
        source_client_order_id=source_id,
        reserved_successor_client_order_id=successor_id,
        correlation_id="goal14-closeout-two",
    )


def test_command_replay_and_ten_cycle_budget_are_durable(
    repository: OperatorParentMovePremarkRepository,
) -> None:
    _create_plan(repository)
    first = _begin_execute(repository)
    replayed = _begin_execute(repository)

    assert first["active_cycle_number"] == 2
    assert replayed["command_replayed"] is True
    repository.complete_cycle(
        source_client_order_id=str(_plan()["source_client_order_id"]),
        correlation_id="goal14-execute-one",
        idempotency_key="goal14-execute-key-one",
        diagnostic_code="operator_parent_move_execute_ineligible",
    )
    for number in range(2, 10):
        _begin_execute(repository, suffix=str(number))
        repository.complete_cycle(
            source_client_order_id=str(_plan()["source_client_order_id"]),
            correlation_id=f"goal14-execute-{number}",
            idempotency_key=f"goal14-execute-key-{number}",
            diagnostic_code="operator_parent_move_execute_ineligible",
        )

    with pytest.raises(
        OperatorParentMovePremarkConflict,
        match="operator_parent_move_cycle_allowance_unavailable",
    ):
        _begin_execute(repository, suffix="ten")


def test_events_are_append_only_and_readback_is_call_free(
    repository: OperatorParentMovePremarkRepository,
) -> None:
    _create_plan(repository)
    source_id = str(_plan()["source_client_order_id"])
    before = repository.get_goal(source_id)
    events, total = repository.list_events(
        source_client_order_id=source_id,
        limit=25,
        offset=0,
    )
    after = repository.get_goal(source_id)

    assert before == after
    assert total == 1
    assert events[0]["event_type"] == "PLAN_CREATED"
    assert "private-operator-marker" not in json.dumps(events)
    with repository.database.get_cursor() as cursor:
        with pytest.raises(RaiseException):
            cursor.execute(
                f"""
                UPDATE {repository.prefix}operator_parent_move_premark_event
                SET diagnostic_code = 'operator_parent_move_tampered'
                """
            )
    with repository.database.get_cursor() as cursor:
        with pytest.raises(RaiseException):
            cursor.execute(
                f"""
                DELETE FROM
                    {repository.prefix}operator_parent_move_premark_event
                """
            )
