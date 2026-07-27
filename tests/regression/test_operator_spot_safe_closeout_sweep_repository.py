from __future__ import annotations

import hashlib
import os
import uuid

import pytest
from psycopg2 import sql
from psycopg2.errors import RaiseException

from application.admin_api.operator_hotpoint_control import HOTPOINT_GOAL_ID
from application.admin_api.operator_spot_safe_closeout_sweep_policy import (
    build_operator_spot_safe_closeout_sweep_plan,
)
from database.database import PostgresDB
from database.operator_spot_safe_closeout_sweep import (
    OperatorSpotSafeCloseoutSweepConflict,
    OperatorSpotSafeCloseoutSweepRepository,
)


pytestmark = [pytest.mark.regression, pytest.mark.serial]

TEST_DB_HOST = os.environ.get(
    "COINBASE_DB_HOST",
    "coinbase-test-postgres",
)
TEST_DB_PORT = int(os.environ.get("COINBASE_DB_PORT", "9876"))
TEST_DB_NAME = os.environ.get("COINBASE_DB_NAME", "postgres")
TEST_DB_USER = os.environ.get("COINBASE_DB_USER", "postgres")
TEST_DB_PASSWORD = os.environ.get("COINBASE_DB_PASSWORD", "postgres")
PORTFOLIO_ID = "99999999-9999-4999-8999-999999999999"
PORTFOLIO_SHA256 = hashlib.sha256(PORTFOLIO_ID.encode()).hexdigest()
FILL_ROOT = "11111111-1111-4111-8111-111111111111"
FILL_CHILD = "22222222-2222-4222-8222-222222222222"
HOTPOINT_ROOT = "33333333-3333-4333-8333-333333333333"
HOTPOINT_CHILD = "44444444-4444-4444-8444-444444444444"
FILL_ROOT_EXCHANGE = "55555555-5555-4555-8555-555555555555"
FILL_CHILD_EXCHANGE = "66666666-6666-4666-8666-666666666666"
HOTPOINT_ROOT_EXCHANGE = "77777777-7777-4777-8777-777777777777"
HOTPOINT_CHILD_EXCHANGE = "88888888-8888-4888-8888-888888888888"


@pytest.fixture
def repository() -> OperatorSpotSafeCloseoutSweepRepository:
    schema = f"test_operator_spot_sweep_{uuid.uuid4().hex}"
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
        prefix = sql.Identifier(schema)
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.order_parent (
                    client_order_id VARCHAR(64) PRIMARY KEY,
                    product_id VARCHAR(32) NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    parent_order_id VARCHAR(64),
                    ownership_provenance VARCHAR(64),
                    retail_portfolio_id UUID,
                    correlation_id VARCHAR(255),
                    audit_id VARCHAR(255),
                    exchange_order_id VARCHAR(64),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            ).format(prefix)
        )
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.order_event_stream (
                    event_id UUID PRIMARY KEY,
                    client_order_id VARCHAR(64),
                    order_id VARCHAR(64),
                    parent_client_order_id VARCHAR(64),
                    product_id VARCHAR(32),
                    event_type VARCHAR(64) NOT NULL,
                    source_channel VARCHAR(64),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            ).format(prefix)
        )
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.operator_follow_up_materialization_attempt (
                    materialization_id UUID PRIMARY KEY,
                    root_client_order_id VARCHAR(128) NOT NULL,
                    child_client_order_id UUID NOT NULL UNIQUE,
                    product_id VARCHAR(255) NOT NULL,
                    portfolio_id UUID NOT NULL,
                    portfolio_scope_sha256 CHAR(64) NOT NULL
                )
                """
            ).format(prefix)
        )
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.operator_follow_up_materialization_event (
                    event_sequence BIGSERIAL PRIMARY KEY,
                    materialization_id UUID NOT NULL,
                    state VARCHAR(48) NOT NULL,
                    diagnostic_code VARCHAR(96) NOT NULL,
                    exchange_order_id_sha256 CHAR(64),
                    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            ).format(prefix)
        )
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.operator_hotpoint_control (
                    goal_id VARCHAR(128) PRIMARY KEY,
                    parent_client_order_id VARCHAR(128),
                    child_client_order_id VARCHAR(128) UNIQUE,
                    product_id VARCHAR(32),
                    create_state VARCHAR(16) NOT NULL,
                    create_exchange_invoked BOOLEAN,
                    cancel_state VARCHAR(16) NOT NULL,
                    plan_evidence_sha256 CHAR(64),
                    trigger_portfolio_id_sha256 CHAR(64)
                )
                """
            ).format(prefix)
        )
    repo = OperatorSpotSafeCloseoutSweepRepository(
        database,
        schema=schema,
        configured_portfolio_id=PORTFOLIO_ID,
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


def _insert_candidates(
    repository: OperatorSpotSafeCloseoutSweepRepository,
) -> None:
    with repository.database.get_cursor() as cursor:
        for (
            root,
            child,
            provenance,
            root_status,
            root_exchange,
            child_exchange,
        ) in (
            (
                FILL_ROOT,
                FILL_CHILD,
                "ADMIN_FILL_FOLLOW_UP",
                "FILLED",
                FILL_ROOT_EXCHANGE,
                FILL_CHILD_EXCHANGE,
            ),
            (
                HOTPOINT_ROOT,
                HOTPOINT_CHILD,
                "ADMIN_HOTPOINT_CHILD",
                "OPEN",
                HOTPOINT_ROOT_EXCHANGE,
                HOTPOINT_CHILD_EXCHANGE,
            ),
        ):
            cursor.execute(
                f"""
                INSERT INTO {repository.prefix}order_parent (
                    client_order_id, product_id, status,
                    parent_order_id, ownership_provenance,
                    retail_portfolio_id, correlation_id, audit_id,
                    exchange_order_id
                ) VALUES (
                    %s, 'BTC-USDC', %s, NULL,
                    'ADMIN_MANUAL_ROOT', %s::uuid, %s, %s, %s
                )
                """,
                (
                    root,
                    root_status,
                    PORTFOLIO_ID,
                    f"corr-{root}",
                    f"audit-{root}",
                    root_exchange,
                ),
            )
            cursor.execute(
                f"""
                INSERT INTO {repository.prefix}order_parent (
                    client_order_id, product_id, status,
                    parent_order_id, ownership_provenance,
                    retail_portfolio_id, correlation_id, audit_id,
                    exchange_order_id
                ) VALUES (
                    %s, 'BTC-USDC', 'OPEN', %s, %s,
                    %s::uuid, %s, %s, %s
                )
                """,
                (
                    child,
                    root,
                    provenance,
                    PORTFOLIO_ID,
                    f"corr-{child}",
                    f"audit-{child}",
                    child_exchange,
                ),
            )
        materialization_id = str(uuid.uuid4())
        cursor.execute(
            f"""
            INSERT INTO
                {repository.prefix}operator_follow_up_materialization_attempt (
                materialization_id, root_client_order_id,
                child_client_order_id, product_id, portfolio_id,
                portfolio_scope_sha256
            ) VALUES (%s::uuid, %s, %s::uuid, 'BTC-USDC',
                      %s::uuid, %s)
            """,
            (
                materialization_id,
                FILL_ROOT,
                FILL_CHILD,
                PORTFOLIO_ID,
                PORTFOLIO_SHA256,
            ),
        )
        cursor.execute(
            f"""
            INSERT INTO
                {repository.prefix}operator_follow_up_materialization_event (
                materialization_id, state, diagnostic_code,
                exchange_order_id_sha256
            ) VALUES (
                %s::uuid, 'CREATE_ACCEPTED_NONTERMINAL',
                'materialized_child_active_cancel_available', %s
            )
            """,
            (
                materialization_id,
                hashlib.sha256(FILL_CHILD_EXCHANGE.encode()).hexdigest(),
            ),
        )
        cursor.execute(
            f"""
            INSERT INTO {repository.prefix}operator_hotpoint_control (
                goal_id, parent_client_order_id, child_client_order_id,
                product_id, create_state, create_exchange_invoked,
                cancel_state, plan_evidence_sha256,
                trigger_portfolio_id_sha256
            ) VALUES (
                %s, %s, %s, 'BTC-USDC', 'ACCEPTED', TRUE,
                'NOT_CLAIMED', %s, %s
            )
            """,
            (
                HOTPOINT_GOAL_ID,
                HOTPOINT_ROOT,
                HOTPOINT_CHILD,
                "f" * 64,
                PORTFOLIO_SHA256,
            ),
        )
        cursor.execute(
            f"""
            INSERT INTO {repository.prefix}order_event_stream (
                event_id, client_order_id, order_id,
                parent_client_order_id, product_id,
                event_type, source_channel
            ) VALUES (
                %s::uuid, %s, %s, %s, 'BTC-USDC',
                'order_submitted', 'rest_submit'
            )
            """,
            (
                str(uuid.uuid4()),
                HOTPOINT_CHILD,
                HOTPOINT_CHILD_EXCHANGE,
                HOTPOINT_ROOT,
            ),
        )


def _create(
    repository: OperatorSpotSafeCloseoutSweepRepository,
):
    candidates, _ = repository.list_candidates(limit=10, offset=0)
    plan = build_operator_spot_safe_closeout_sweep_plan(
        candidates=candidates,
        configured_portfolio_scope_sha256=PORTFOLIO_SHA256,
    )
    return repository.create_plan(
        plan=plan.to_persisted_payload(),
        plan_sha256=plan.plan_sha256,
        private_exchange_bindings=dict(plan.private_exchange_bindings),
        actor_id="private-operator",
        correlation_id="goal16-create-correlation",
        idempotency_key="private-goal16-key",
        payload_sha256="a" * 64,
        operator_reason_sha256="b" * 64,
        operator_intent="create_operator_spot_safe_closeout_sweep",
    )


def test_schema_upgrade_fails_closed_without_historical_replay_snapshot(
) -> None:
    schema = f"test_sweep_up_{uuid.uuid4().hex}"
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
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.operator_spot_safe_closeout_command (
                    command_id UUID PRIMARY KEY,
                    result_json JSONB
                )
                """
            ).format(sql.Identifier(schema))
        )
        cursor.execute(
            sql.SQL(
                """
                INSERT INTO {}.operator_spot_safe_closeout_command (
                    command_id, result_json
                ) VALUES (%s::uuid, NULL)
                """
            ).format(sql.Identifier(schema)),
            (str(uuid.uuid4()),),
        )
    repository = OperatorSpotSafeCloseoutSweepRepository(
        database,
        schema=schema,
        configured_portfolio_id=PORTFOLIO_ID,
    )
    try:
        with pytest.raises(
            OperatorSpotSafeCloseoutSweepConflict
        ) as exc:
            repository.ensure_schema()
        assert exc.value.code == (
            "operator_spot_sweep_replay_snapshot_unavailable"
        )
    finally:
        with database.get_cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(
                    sql.Identifier(schema)
                )
            )
        database.disconnect()


def test_candidates_require_durable_accepted_fill_and_hotpoint_predecessors(
    repository: OperatorSpotSafeCloseoutSweepRepository,
) -> None:
    _insert_candidates(repository)

    candidates, total = repository.list_candidates(limit=10, offset=0)

    assert total == 2
    assert {
        candidate["ownership_provenance"] for candidate in candidates
    } == {"ADMIN_FILL_FOLLOW_UP", "ADMIN_HOTPOINT_CHILD"}
    assert all(
        candidate["portfolio_scope_sha256"] == PORTFOLIO_SHA256
        for candidate in candidates
    )
    assert all(
        "exchange_order_id" not in candidate for candidate in candidates
    )
    assert not any(
        str(uuid.UUID(candidate["client_order_id"]))
        != candidate["client_order_id"]
        for candidate in candidates
    )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT status
            FROM {repository.prefix}order_parent
            WHERE client_order_id = %s
            """,
            (HOTPOINT_ROOT,),
        )
        assert cursor.fetchone()[0] == "OPEN"
        cursor.execute(
            f"""
            UPDATE {repository.prefix}order_parent
            SET status = 'FILLED'
            WHERE client_order_id = %s
            """,
            (HOTPOINT_ROOT,),
        )

    after_parent_terminal, _ = repository.list_candidates(
        limit=10,
        offset=0,
    )
    assert {
        candidate["client_order_id"]
        for candidate in after_parent_terminal
    } == {FILL_CHILD, HOTPOINT_CHILD}


def test_hotpoint_candidate_rejects_wrong_goal_and_forged_event_linkage(
    repository: OperatorSpotSafeCloseoutSweepRepository,
) -> None:
    _insert_candidates(repository)
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {repository.prefix}operator_hotpoint_control
            SET goal_id = 'unrelated_goal'
            WHERE child_client_order_id = %s
            """,
            (HOTPOINT_CHILD,),
        )

    candidates, _ = repository.list_candidates(limit=10, offset=0)
    assert {
        candidate["client_order_id"] for candidate in candidates
    } == {FILL_CHILD}

    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {repository.prefix}operator_hotpoint_control
            SET goal_id = %s
            WHERE child_client_order_id = %s
            """,
            (HOTPOINT_GOAL_ID, HOTPOINT_CHILD),
        )
        cursor.execute(
            f"""
            UPDATE {repository.prefix}order_event_stream
            SET order_id = %s
            WHERE client_order_id = %s
            """,
            (FILL_CHILD_EXCHANGE, HOTPOINT_CHILD),
        )

    candidates, _ = repository.list_candidates(limit=10, offset=0)
    assert {
        candidate["client_order_id"] for candidate in candidates
    } == {FILL_CHILD}


def test_fill_candidate_rejects_mismatched_or_later_unknown_evidence(
    repository: OperatorSpotSafeCloseoutSweepRepository,
) -> None:
    _insert_candidates(repository)
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE
                {repository.prefix}operator_follow_up_materialization_event
            SET exchange_order_id_sha256 = %s
            """,
            ("f" * 64,),
        )

    candidates, _ = repository.list_candidates(limit=10, offset=0)
    assert {
        candidate["client_order_id"] for candidate in candidates
    } == {HOTPOINT_CHILD}

    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE
                {repository.prefix}operator_follow_up_materialization_event
            SET exchange_order_id_sha256 = %s
            """,
            (
                hashlib.sha256(
                    FILL_CHILD_EXCHANGE.encode()
                ).hexdigest(),
            ),
        )
        cursor.execute(
            f"""
            INSERT INTO
                {repository.prefix}operator_follow_up_materialization_event (
                materialization_id, state, diagnostic_code,
                exchange_order_id_sha256
            )
            SELECT materialization_id, 'CREATE_UNKNOWN',
                   'materialized_child_unknown', %s
            FROM
                {repository.prefix}operator_follow_up_materialization_attempt
            """,
            (
                hashlib.sha256(
                    FILL_CHILD_EXCHANGE.encode()
                ).hexdigest(),
            ),
        )

    candidates, _ = repository.list_candidates(limit=10, offset=0)
    assert {
        candidate["client_order_id"] for candidate in candidates
    } == {HOTPOINT_CHILD}


def test_create_revalidates_stale_candidate_in_locked_transaction(
    repository: OperatorSpotSafeCloseoutSweepRepository,
) -> None:
    _insert_candidates(repository)
    candidates, _ = repository.list_candidates(limit=10, offset=0)
    plan = build_operator_spot_safe_closeout_sweep_plan(
        candidates=candidates,
        configured_portfolio_scope_sha256=PORTFOLIO_SHA256,
    )
    other_connection = PostgresDB(
        host=TEST_DB_HOST,
        port=TEST_DB_PORT,
        database=TEST_DB_NAME,
        user=TEST_DB_USER,
        password=TEST_DB_PASSWORD,
    )
    other_connection.connect()
    try:
        with other_connection.get_cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE {repository.prefix}order_parent
                SET status = 'FILLED'
                WHERE client_order_id = %s
                """,
                (FILL_CHILD,),
            )
    finally:
        other_connection.disconnect()

    with pytest.raises(OperatorSpotSafeCloseoutSweepConflict) as exc:
        repository.create_plan(
            plan=plan.to_persisted_payload(),
            plan_sha256=plan.plan_sha256,
            private_exchange_bindings=dict(
                plan.private_exchange_bindings
            ),
            actor_id="private-operator",
            correlation_id="goal16-stale-create",
            idempotency_key="goal16-stale-create",
            payload_sha256="a" * 64,
            operator_reason_sha256="b" * 64,
            operator_intent=(
                "create_operator_spot_safe_closeout_sweep"
            ),
        )

    assert exc.value.code == (
        "operator_spot_sweep_candidate_evidence_conflict"
    )
    assert repository.goal_is_bound() is False


def test_plan_items_events_are_immutable_and_projection_is_restart_safe(
    repository: OperatorSpotSafeCloseoutSweepRepository,
) -> None:
    _insert_candidates(repository)
    created = _create(repository)
    current_plan = repository.get_current_plan()

    assert current_plan is not None
    assert current_plan["sweep_id"] == created["sweep_id"]
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            """
            SELECT attribute.attnotnull
            FROM pg_attribute attribute
            WHERE attribute.attrelid = to_regclass(%s)
              AND attribute.attname = 'result_json'
              AND attribute.attnum > 0
              AND NOT attribute.attisdropped
            """,
            (
                f"{repository.schema}."
                "operator_spot_safe_closeout_command",
            ),
        )
        assert cursor.fetchone()[0] is True

    immutable_tables = {
        "operator_spot_safe_closeout_plan": "goal_id = goal_id",
        "operator_spot_safe_closeout_plan_item": (
            "position = position"
        ),
        "operator_spot_safe_closeout_event": (
            "diagnostic_code = diagnostic_code"
        ),
        "operator_spot_safe_closeout_command": "action = action",
    }
    truncate_dependencies = {
        "operator_spot_safe_closeout_plan": [
            "operator_spot_safe_closeout_plan_item",
            "operator_spot_safe_closeout_projection",
            "operator_spot_safe_closeout_item_projection",
            "operator_spot_safe_closeout_event",
            "operator_spot_safe_closeout_command",
        ],
        "operator_spot_safe_closeout_plan_item": [
            "operator_spot_safe_closeout_item_projection"
        ],
        "operator_spot_safe_closeout_event": [
            "operator_spot_safe_closeout_command"
        ],
        "operator_spot_safe_closeout_command": [],
    }
    for table, assignment in immutable_tables.items():
        with repository.database.get_cursor() as cursor:
            with pytest.raises(RaiseException):
                cursor.execute(
                    f"UPDATE {repository.prefix}{table} "
                    f"SET {assignment}"
                )
        with repository.database.get_cursor() as cursor:
            with pytest.raises(RaiseException):
                cursor.execute(
                    f"DELETE FROM {repository.prefix}{table}"
                )
        with repository.database.get_cursor() as cursor:
            with pytest.raises(RaiseException):
                truncate_tables = ", ".join(
                    f"{repository.prefix}{candidate}"
                    for candidate in [
                        table,
                        *truncate_dependencies[table],
                    ]
                )
                cursor.execute(
                    f"TRUNCATE {truncate_tables}"
                )
    with repository.database.get_cursor() as cursor:
        for table in immutable_tables:
            cursor.execute(
                f"SELECT COUNT(*) FROM {repository.prefix}{table}"
            )
            assert cursor.fetchone()[0] >= 1

    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {repository.prefix}operator_spot_safe_closeout_projection
            SET state = 'IN_PROGRESS'
            WHERE sweep_id = %s::uuid
            """,
            (created["sweep_id"],),
        )
        cursor.execute(
            f"""
            UPDATE
                {repository.prefix}operator_spot_safe_closeout_item_projection
            SET state = 'IN_FLIGHT'
            WHERE sweep_id = %s::uuid AND position = 1
            """,
            (created["sweep_id"],),
        )
    repository.recover_stranded_work()
    recovered = repository.get_plan(sweep_id=created["sweep_id"])

    assert recovered["state"] == "QUARANTINED"
    assert all(
        item["state"] not in {"PENDING", "IN_FLIGHT", "UNKNOWN"}
        for item in recovered["items"]
    )
    assert all(
        item["state"] == "QUARANTINED"
        for item in recovered["items"]
    )
    assert recovered["events"][-1]["event_type"] == "SWEEP_QUARANTINED"
    assert recovered["latest_evidence_sha256"] == (
        recovered["events"][-1]["evidence_sha256"]
    )
    assert recovered["correlation_id"] == (
        "operator_spot_sweep_restart_recovery"
    )
    with pytest.raises(OperatorSpotSafeCloseoutSweepConflict) as exc:
        repository.apply_local_action(
            sweep_id=created["sweep_id"],
            action="RESUME",
            expected_revision=recovered["revision"],
            expected_plan_sha256=recovered["plan_sha256"],
            actor_id="operator",
            correlation_id="goal16-resume-after-quarantine",
            idempotency_key="goal16-resume-after-quarantine",
            payload_sha256="c" * 64,
            operator_reason_sha256="d" * 64,
            operator_intent="resume_operator_spot_safe_closeout_sweep",
        )
    assert exc.value.code == "operator_spot_sweep_resume_unavailable"


def test_exact_replay_and_ten_cycle_cap_do_not_reapply_mutation(
    repository: OperatorSpotSafeCloseoutSweepRepository,
) -> None:
    _insert_candidates(repository)
    created = _create(repository)
    replay = repository.get_command_replay(
        action="CREATE",
        sweep_id=None,
        actor_id="private-operator",
        correlation_id="goal16-create-correlation",
        idempotency_key="private-goal16-key",
        payload_sha256="a" * 64,
    )
    assert replay is not None
    assert replay["command_replayed"] is True
    assert replay["revision"] == created["revision"]

    current = created
    for index in range(2, 11):
        action = "PAUSE" if current["state"] == "READY" else "RESUME"
        current = repository.apply_local_action(
            sweep_id=created["sweep_id"],
            action=action,
            expected_revision=current["revision"],
            expected_plan_sha256=current["plan_sha256"],
            actor_id="operator",
            correlation_id=f"goal16-cycle-{index}",
            idempotency_key=f"goal16-key-{index}",
            payload_sha256=f"{index:x}".rjust(64, "0"),
            operator_reason_sha256="d" * 64,
            operator_intent=(
                f"{action.lower()}_operator_spot_safe_closeout_sweep"
            ),
        )
    assert current["local_cycles_used"] == 10

    create_replay_after_later_commands = repository.get_command_replay(
        action="CREATE",
        sweep_id=None,
        actor_id="private-operator",
        correlation_id="goal16-create-correlation",
        idempotency_key="private-goal16-key",
        payload_sha256="a" * 64,
    )
    assert create_replay_after_later_commands is not None
    assert create_replay_after_later_commands["command_replayed"] is True
    assert create_replay_after_later_commands["revision"] == 1
    assert create_replay_after_later_commands["state"] == "READY"
    assert create_replay_after_later_commands["latest_action"] == "CREATE"
    assert len(create_replay_after_later_commands["events"]) == 1
    assert all(
        item["state"] == "PENDING"
        for item in create_replay_after_later_commands["items"]
    )
    assert create_replay_after_later_commands[
        "latest_payload_sha256"
    ] == "a" * 64
    assert create_replay_after_later_commands["correlation_id"] == (
        "goal16-create-correlation"
    )

    pause_replay_after_later_commands = repository.get_command_replay(
        action="PAUSE",
        sweep_id=created["sweep_id"],
        actor_id="operator",
        correlation_id="goal16-cycle-2",
        idempotency_key="goal16-key-2",
        payload_sha256=f"{2:x}".rjust(64, "0"),
    )
    assert pause_replay_after_later_commands is not None
    assert pause_replay_after_later_commands["revision"] == 2
    assert pause_replay_after_later_commands["state"] == "PAUSED"
    assert pause_replay_after_later_commands["latest_action"] == "PAUSE"
    assert len(pause_replay_after_later_commands["events"]) == 2
    assert pause_replay_after_later_commands["correlation_id"] == (
        "goal16-cycle-2"
    )

    with pytest.raises(OperatorSpotSafeCloseoutSweepConflict) as exc:
        repository.apply_local_action(
            sweep_id=created["sweep_id"],
            action="ABORT",
            expected_revision=current["revision"],
            expected_plan_sha256=current["plan_sha256"],
            actor_id="operator",
            correlation_id="goal16-cycle-11",
            idempotency_key="goal16-key-11",
            payload_sha256="e" * 64,
            operator_reason_sha256="f" * 64,
            operator_intent="abort_operator_spot_safe_closeout_sweep",
        )
    assert exc.value.code == "operator_spot_sweep_cycle_cap_reached"
    unchanged = repository.get_plan(sweep_id=created["sweep_id"])
    assert unchanged["revision"] == current["revision"]


def test_restart_quarantine_is_audited_past_operator_cycle_cap(
    repository: OperatorSpotSafeCloseoutSweepRepository,
) -> None:
    _insert_candidates(repository)
    created = _create(repository)
    current = created
    for index in range(2, 11):
        action = "PAUSE" if current["state"] == "READY" else "RESUME"
        current = repository.apply_local_action(
            sweep_id=created["sweep_id"],
            action=action,
            expected_revision=current["revision"],
            expected_plan_sha256=current["plan_sha256"],
            actor_id="operator",
            correlation_id=f"goal16-cap-recovery-{index}",
            idempotency_key=f"goal16-cap-recovery-{index}",
            payload_sha256=f"{index + 16:x}".rjust(64, "0"),
            operator_reason_sha256="d" * 64,
            operator_intent=(
                f"{action.lower()}_operator_spot_safe_closeout_sweep"
            ),
        )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {repository.prefix}operator_spot_safe_closeout_projection
            SET state = 'IN_PROGRESS'
            WHERE sweep_id = %s::uuid
            """,
            (created["sweep_id"],),
        )
        cursor.execute(
            f"""
            UPDATE
                {repository.prefix}operator_spot_safe_closeout_item_projection
            SET state = 'UNKNOWN'
            WHERE sweep_id = %s::uuid AND position = 1
            """,
            (created["sweep_id"],),
        )

    repository.recover_stranded_work()
    recovered = repository.get_plan(sweep_id=created["sweep_id"])

    assert recovered["state"] == "QUARANTINED"
    assert recovered["local_cycles_used"] == 10
    assert recovered["revision"] == 11
    assert len(recovered["events"]) == 11
    assert recovered["events"][-1]["event_type"] == "SWEEP_QUARANTINED"
