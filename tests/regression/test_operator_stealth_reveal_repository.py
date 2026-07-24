from __future__ import annotations

import hashlib
import json
import os
import re
import uuid

import pytest
from psycopg2 import IntegrityError, sql

from database.database import PostgresDB
from database.operator_stealth_reveal import (
    OperatorStealthRevealConflict,
    OperatorStealthRevealRepository,
)


pytestmark = [pytest.mark.regression, pytest.mark.serial]

TEST_DB_HOST = os.environ.get("COINBASE_DB_HOST", "coinbase-test-postgres")
TEST_DB_PORT = int(os.environ.get("COINBASE_DB_PORT", "9876"))
TEST_DB_NAME = os.environ.get("COINBASE_DB_NAME", "postgres")
TEST_DB_USER = os.environ.get("COINBASE_DB_USER", "postgres")
TEST_DB_PASSWORD = os.environ.get("COINBASE_DB_PASSWORD", "postgres")
_SCHEMA = re.compile(r"^test_operator_stealth_reveal_[0-9a-f]{32}$")
DEFINITION_ID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def repository() -> OperatorStealthRevealRepository:
    schema = f"test_operator_stealth_reveal_{uuid.uuid4().hex}"
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
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.operator_stealth_definition (
                    definition_id UUID PRIMARY KEY,
                    portfolio_scope_sha256 CHAR(64) NOT NULL,
                    lifecycle_state TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    definition_sha256 CHAR(64) NOT NULL
                )
                """
            ).format(sql.Identifier(schema))
        )
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.stealth_orders (
                    stealth_order_id UUID PRIMARY KEY,
                    status VARCHAR(32) NOT NULL
                )
                """
            ).format(sql.Identifier(schema))
        )
        cursor.execute(
            sql.SQL(
                """
                INSERT INTO {}.operator_stealth_definition (
                    definition_id, portfolio_scope_sha256, lifecycle_state,
                    revision, definition_sha256
                ) VALUES (%s, %s, 'DRAFT', 2, %s)
                """
            ).format(sql.Identifier(schema)),
            (DEFINITION_ID, "a" * 64, "b" * 64),
        )
    repo = OperatorStealthRevealRepository(database, schema=schema)
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


def _begin(repository: OperatorStealthRevealRepository):
    return repository.begin_materialization(
        definition_id=DEFINITION_ID,
        expected_revision=2,
        expected_definition_sha256="b" * 64,
        expected_portfolio_scope_sha256="a" * 64,
        actor_id="operator",
        correlation_id="goal6-reveal-correlation",
        idempotency_key="goal6-reveal-key",
        payload_sha256=hashlib.sha256(b"goal6-reveal").hexdigest(),
    )


def _plan_sha(plan: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _plan() -> dict[str, object]:
    return {
        "product_id": "BTC-USDC",
        "side": "BUY",
        "base_size": "0.00001",
        "limit_price": "60000",
        "configured_limit_price": "60000",
        "submitted_limit_price": "60000",
        "reveal_pricing_policy": "top_of_book",
        "reveal_price_source": "best_bid",
        "fallback_used": False,
        "market_source": "ticker",
        "market_bid": "60000",
        "market_ask": "60001",
        "target_movement": "0.005",
        "target_movement_type": "P",
        "target_movement_source": "operator_definition",
        "post_only": True,
    }


def _record_revealed(repository: OperatorStealthRevealRepository) -> None:
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {repository.prefix}stealth_orders (
                stealth_order_id, status
            ) VALUES (%s, 'HIDDEN')
            """,
            (DEFINITION_ID,),
        )
    repository.record_materialized(DEFINITION_ID)
    plan = _plan()
    admission_sha256 = "c" * 64
    repository.record_prepreview_admission(
        DEFINITION_ID,
        plan=plan,
        plan_sha256=_plan_sha(plan),
        admission_sha256=admission_sha256,
    )
    repository.claim_preview(
        DEFINITION_ID,
        plan=plan,
        plan_sha256=_plan_sha(plan),
        admission_sha256=admission_sha256,
    )
    repository.record_preview_outcome(
        DEFINITION_ID,
        outcome="ACCEPTED",
        diagnostic_code="operator_stealth_preview_accepted",
    )
    repository.claim_create(DEFINITION_ID)
    repository.record_create_outcome(
        DEFINITION_ID,
        outcome="ACCEPTED",
        diagnostic_code="operator_stealth_create_accepted",
        exchange_order_id_sha256="d" * 64,
    )


def test_exact_claim_opens_only_one_runtime_identity_window(
    repository: OperatorStealthRevealRepository,
) -> None:
    with pytest.raises(IntegrityError):
        with repository.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO {repository.prefix}stealth_orders (
                    stealth_order_id, status
                ) VALUES (%s, 'HIDDEN')
                """,
                (DEFINITION_ID,),
            )

    claimed = _begin(repository)
    replay = _begin(repository)
    assert claimed["state"] == "MATERIALIZING"
    assert replay["command_replayed"] is True

    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {repository.prefix}stealth_orders (
                stealth_order_id, status
            ) VALUES (%s, 'HIDDEN')
            """,
            (DEFINITION_ID,),
        )
    materialized = repository.record_materialized(DEFINITION_ID)
    assert materialized["state"] == "MATERIALIZED"

    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            DELETE FROM {repository.prefix}stealth_orders
            WHERE stealth_order_id = %s
            """,
            (DEFINITION_ID,),
        )
    with pytest.raises(IntegrityError):
        with repository.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO {repository.prefix}stealth_orders (
                    stealth_order_id, status
                ) VALUES (%s, 'HIDDEN')
                """,
                (DEFINITION_ID,),
            )


def test_preview_create_cancel_allowances_are_distinct_and_single_use(
    repository: OperatorStealthRevealRepository,
) -> None:
    _begin(repository)
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {repository.prefix}stealth_orders (
                stealth_order_id, status
            ) VALUES (%s, 'HIDDEN')
            """,
            (DEFINITION_ID,),
        )
    repository.record_materialized(DEFINITION_ID)
    plan = _plan()
    admission_sha256 = "c" * 64
    repository.record_prepreview_admission(
        DEFINITION_ID,
        plan=plan,
        plan_sha256=_plan_sha(plan),
        admission_sha256=admission_sha256,
    )
    preview = repository.claim_preview(
        DEFINITION_ID,
        plan=plan,
        plan_sha256=_plan_sha(plan),
        admission_sha256=admission_sha256,
    )
    assert preview["preview_allowance_consumed"] is True
    assert preview["preview_call_count"] == 1
    with pytest.raises(OperatorStealthRevealConflict):
        repository.claim_preview(
            DEFINITION_ID,
            plan=plan,
            plan_sha256=_plan_sha(plan),
            admission_sha256=admission_sha256,
        )

    accepted = repository.record_preview_outcome(
        DEFINITION_ID,
        outcome="ACCEPTED",
        diagnostic_code="operator_stealth_preview_accepted",
    )
    assert accepted["state"] == "PREVIEW_ACCEPTED"
    create = repository.claim_create(DEFINITION_ID)
    assert create["create_allowance_consumed"] is True
    assert create["create_call_count"] == 1
    revealed = repository.record_create_outcome(
        DEFINITION_ID,
        outcome="ACCEPTED",
        diagnostic_code="operator_stealth_create_accepted",
        exchange_order_id_sha256="d" * 64,
    )
    assert revealed["state"] == "REVEALED"
    cancel = repository.claim_cancel(DEFINITION_ID)
    assert cancel["cancel_allowance_consumed"] is True
    assert cancel["cancel_call_count"] == 1
    closed = repository.record_cancel_outcome(
        DEFINITION_ID,
        outcome="CANCELLED",
        diagnostic_code="operator_stealth_cancel_confirmed",
    )
    assert closed["state"] == "CANCELLED"
    assert closed["preview_call_count"] == 1
    assert closed["create_call_count"] == 1
    assert closed["cancel_call_count"] == 1


def test_rejected_preview_never_opens_create_allowance(
    repository: OperatorStealthRevealRepository,
) -> None:
    _begin(repository)
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {repository.prefix}stealth_orders (
                stealth_order_id, status
            ) VALUES (%s, 'HIDDEN')
            """,
            (DEFINITION_ID,),
        )
    repository.record_materialized(DEFINITION_ID)
    plan = _plan()
    admission_sha256 = "c" * 64
    repository.record_prepreview_admission(
        DEFINITION_ID,
        plan=plan,
        plan_sha256=_plan_sha(plan),
        admission_sha256=admission_sha256,
    )
    repository.claim_preview(
        DEFINITION_ID,
        plan=plan,
        plan_sha256=_plan_sha(plan),
        admission_sha256=admission_sha256,
    )
    rejected = repository.record_preview_outcome(
        DEFINITION_ID,
        outcome="REJECTED",
        diagnostic_code="operator_stealth_preview_rejected",
    )

    assert rejected["state"] == "PREVIEW_REJECTED"
    assert rejected["create_allowance_consumed"] is False
    with pytest.raises(OperatorStealthRevealConflict):
        repository.claim_create(DEFINITION_ID)


def test_preview_accepted_survives_startup_and_claims_one_resume_cycle(
    repository: OperatorStealthRevealRepository,
) -> None:
    _begin(repository)
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {repository.prefix}stealth_orders (
                stealth_order_id, status
            ) VALUES (%s, 'HIDDEN')
            """,
            (DEFINITION_ID,),
        )
    repository.record_materialized(DEFINITION_ID)
    plan = _plan()
    repository.record_prepreview_admission(
        DEFINITION_ID,
        plan=plan,
        plan_sha256=_plan_sha(plan),
        admission_sha256="c" * 64,
    )
    repository.claim_preview(
        DEFINITION_ID,
        plan=plan,
        plan_sha256=_plan_sha(plan),
        admission_sha256="c" * 64,
    )
    repository.record_preview_outcome(
        DEFINITION_ID,
        outcome="ACCEPTED",
        diagnostic_code="operator_stealth_preview_accepted",
    )

    repository.ensure_schema()
    recovered = repository.get_goal(DEFINITION_ID)
    assert recovered["state"] == "PREVIEW_ACCEPTED"
    assert recovered["create_allowance_consumed"] is False

    cycle = repository.begin_command_cycle(
        DEFINITION_ID,
        phase="RESUME_CREATE",
        actor_id="operator",
        correlation_id="goal6-resume-correlation",
        idempotency_key="goal6-resume-key",
        payload_sha256="d" * 64,
    )
    replay = repository.begin_command_cycle(
        DEFINITION_ID,
        phase="RESUME_CREATE",
        actor_id="operator",
        correlation_id="goal6-resume-correlation",
        idempotency_key="goal6-resume-key",
        payload_sha256="d" * 64,
    )
    after_restart = repository.begin_command_cycle(
        DEFINITION_ID,
        phase="RESUME_CREATE",
        actor_id="operator",
        correlation_id="goal6-resume-correlation-2",
        idempotency_key="goal6-resume-key-2",
        payload_sha256="e" * 64,
    )

    assert cycle["command_replayed"] is False
    assert replay["command_replayed"] is True
    assert after_restart["command_replayed"] is False
    persisted = repository.get_goal(DEFINITION_ID)
    assert persisted["correlation_id"] == "goal6-resume-correlation-2"
    assert persisted["command_idempotency_key_sha256"] == hashlib.sha256(
        b"goal6-resume-key-2"
    ).hexdigest()


def test_read_claim_is_counted_before_call_and_replayed_without_retry(
    repository: OperatorStealthRevealRepository,
) -> None:
    _begin(repository)

    claimed = repository.claim_read_call(
        DEFINITION_ID,
        category="REVEAL_PORTFOLIO_BINDING",
        correlation_id="goal6-eligibility-cycle-1",
        wire_call=False,
    )
    replayed_started = repository.claim_read_call(
        DEFINITION_ID,
        category="REVEAL_PORTFOLIO_BINDING",
        correlation_id="goal6-eligibility-cycle-1",
        wire_call=False,
    )

    assert claimed["invoke_required"] is True
    assert claimed["call_state"] == "STARTED"
    assert replayed_started["invoke_required"] is False
    assert replayed_started["call_state"] == "STARTED"
    assert claimed["wire_call_count"] == 0
    assert repository.get_goal(DEFINITION_ID)["read_call_count"] == 0

    recorded = repository.record_read_call_outcome(
        DEFINITION_ID,
        category="REVEAL_PORTFOLIO_BINDING",
        correlation_id="goal6-eligibility-cycle-1",
        result_code="READY",
    )
    replayed_returned = repository.claim_read_call(
        DEFINITION_ID,
        category="REVEAL_PORTFOLIO_BINDING",
        correlation_id="goal6-eligibility-cycle-1",
        wire_call=False,
    )

    assert recorded["call_state"] == "RETURNED"
    assert recorded["result_code"] == "READY"
    assert replayed_returned["invoke_required"] is False
    assert replayed_returned["result_code"] == "READY"
    assert repository.get_goal(DEFINITION_ID)["read_call_count"] == 0

    wire = repository.claim_read_call(
        DEFINITION_ID,
        category="REVEAL_API_KEY_PERMISSIONS",
        correlation_id="goal6-eligibility-cycle-1",
        wire_call=True,
    )
    assert wire["wire_call_count"] == 1
    assert repository.get_goal(DEFINITION_ID)["read_call_count"] == 1


def test_closeout_command_binding_allows_same_payload_cycles_only_before_claim(
    repository: OperatorStealthRevealRepository,
) -> None:
    _begin(repository)
    _record_revealed(repository)
    payload_sha256 = hashlib.sha256(b"goal6-closeout").hexdigest()

    claimed = repository.begin_closeout(
        DEFINITION_ID,
        actor_id="operator",
        correlation_id="goal6-closeout-correlation",
        idempotency_key="goal6-closeout-key",
        payload_sha256=payload_sha256,
    )
    replayed = repository.begin_closeout(
        DEFINITION_ID,
        actor_id="operator",
        correlation_id="goal6-closeout-correlation",
        idempotency_key="goal6-closeout-key",
        payload_sha256=payload_sha256,
    )

    assert claimed["command_replayed"] is False
    assert claimed["correlation_id"] == "goal6-closeout-correlation"
    assert replayed["command_replayed"] is True
    next_cycle = repository.begin_closeout(
        DEFINITION_ID,
        actor_id="operator",
        correlation_id="goal6-closeout-correlation-2",
        idempotency_key="goal6-closeout-key-2",
        payload_sha256=payload_sha256,
    )
    assert next_cycle["command_replayed"] is False
    with pytest.raises(OperatorStealthRevealConflict):
        repository.begin_closeout(
            DEFINITION_ID,
            actor_id="operator",
            correlation_id="goal6-closeout-correlation-3",
            idempotency_key="goal6-closeout-key-3",
            payload_sha256=hashlib.sha256(b"changed-closeout").hexdigest(),
        )

    repository.claim_cancel(DEFINITION_ID)
    with pytest.raises(OperatorStealthRevealConflict):
        repository.begin_closeout(
            DEFINITION_ID,
            actor_id="operator",
            correlation_id="goal6-closeout-correlation-4",
            idempotency_key="goal6-closeout-key-4",
            payload_sha256=payload_sha256,
        )


def test_command_cycles_are_exact_replayable_and_goal_global(
    repository: OperatorStealthRevealRepository,
) -> None:
    _begin(repository)
    payload_sha256 = hashlib.sha256(b"goal6-reveal").hexdigest()

    first = repository.begin_command_cycle(
        DEFINITION_ID,
        phase="REVEAL",
        actor_id="operator",
        correlation_id="goal6-cycle-1",
        idempotency_key="goal6-cycle-key-1",
        payload_sha256=payload_sha256,
    )
    replay = repository.begin_command_cycle(
        DEFINITION_ID,
        phase="REVEAL",
        actor_id="operator",
        correlation_id="goal6-cycle-1",
        idempotency_key="goal6-cycle-key-1",
        payload_sha256=payload_sha256,
    )
    second = repository.begin_command_cycle(
        DEFINITION_ID,
        phase="REVEAL",
        actor_id="operator",
        correlation_id="goal6-cycle-2",
        idempotency_key="goal6-cycle-key-2",
        payload_sha256=payload_sha256,
    )

    assert first == {"cycle_number": 1, "command_replayed": False}
    assert replay == {"cycle_number": 1, "command_replayed": True}
    assert second == {"cycle_number": 2, "command_replayed": False}


def test_completed_command_cycle_persists_exact_terminal_evidence(
    repository: OperatorStealthRevealRepository,
) -> None:
    _begin(repository)
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {repository.prefix}stealth_orders (
                stealth_order_id, status
            ) VALUES (%s, 'HIDDEN')
            """,
            (DEFINITION_ID,),
        )
    repository.record_materialized(DEFINITION_ID)
    payload_sha256 = hashlib.sha256(b"goal6-reveal").hexdigest()
    repository.begin_command_cycle(
        DEFINITION_ID,
        phase="REVEAL",
        actor_id="operator",
        correlation_id="goal6-reveal-correlation",
        idempotency_key="goal6-reveal-key",
        payload_sha256=payload_sha256,
    )
    repository.record_condition_not_ready(DEFINITION_ID)

    completed = repository.record_command_completion(
        DEFINITION_ID,
        phase="REVEAL",
        correlation_id="goal6-reveal-correlation",
        idempotency_key="goal6-reveal-key",
    )

    assert completed["command_cycle_status"] == "COMPLETED"
    assert completed["command_cycle_phase"] == "REVEAL"
    assert completed["command_cycle_number"] == 1
    assert completed["command_cycle_correlation_id"] == (
        "goal6-reveal-correlation"
    )
    assert completed["command_cycle_idempotency_key_sha256"] == (
        hashlib.sha256(b"goal6-reveal-key").hexdigest()
    )
    assert completed["command_cycle_payload_sha256"] == payload_sha256
    assert completed["command_cycle_terminal_goal_state"] == "MATERIALIZED"
    assert completed["command_cycle_terminal_diagnostic_code"] == (
        "operator_stealth_condition_not_ready"
    )
    assert completed["command_cycle_preview_call_count"] == 0
    assert completed["command_cycle_create_call_count"] == 0
    assert completed["command_cycle_cancel_call_count"] == 0
    assert completed["command_cycle_read_call_count"] == 0
    assert re.fullmatch(
        r"[0-9a-f]{64}",
        completed["command_cycle_evidence_sha256"],
    )

    repository.ensure_schema()
    recovered = repository.get_goal(DEFINITION_ID)
    assert recovered["command_cycle_status"] == "COMPLETED"
    assert recovered["command_cycle_evidence_sha256"] == (
        completed["command_cycle_evidence_sha256"]
    )


def test_command_cycle_cannot_complete_while_live_call_is_claimed(
    repository: OperatorStealthRevealRepository,
) -> None:
    _begin(repository)
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {repository.prefix}stealth_orders (
                stealth_order_id, status
            ) VALUES (%s, 'HIDDEN')
            """,
            (DEFINITION_ID,),
        )
    repository.record_materialized(DEFINITION_ID)
    payload_sha256 = hashlib.sha256(b"goal6-reveal").hexdigest()
    repository.begin_command_cycle(
        DEFINITION_ID,
        phase="REVEAL",
        actor_id="operator",
        correlation_id="goal6-reveal-correlation",
        idempotency_key="goal6-reveal-key",
        payload_sha256=payload_sha256,
    )
    plan = _plan()
    repository.record_prepreview_admission(
        DEFINITION_ID,
        plan=plan,
        plan_sha256=_plan_sha(plan),
        admission_sha256="c" * 64,
    )
    repository.claim_preview(
        DEFINITION_ID,
        plan=plan,
        plan_sha256=_plan_sha(plan),
        admission_sha256="c" * 64,
    )

    with pytest.raises(
        OperatorStealthRevealConflict,
        match="operator_stealth_command_completion_unavailable",
    ):
        repository.record_command_completion(
            DEFINITION_ID,
            phase="REVEAL",
            correlation_id="goal6-reveal-correlation",
            idempotency_key="goal6-reveal-key",
        )

    in_flight = repository.get_goal(DEFINITION_ID)
    assert in_flight["command_cycle_status"] == "IN_FLIGHT"
    assert in_flight["command_cycle_evidence_sha256"] is None
