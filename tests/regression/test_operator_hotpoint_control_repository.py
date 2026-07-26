"""PostgreSQL invariants for one bounded operator Hotpoint placement."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import os
import re
from types import SimpleNamespace
import uuid

import psycopg2
from psycopg2 import sql
import pytest

from application.admin_api.operator_futures_hotpoint_v2 import (
    FUTURES_HOTPOINT_POLICY_REVISION,
    FUTURES_HOTPOINT_POLICY_SHA256,
    OperatorFuturesHotpointV2Service,
)
from application.admin_api.operator_futures_manual_lifecycle import (
    FuturesManualRequestContext,
)
from application.admin_api.operator_hotpoint_control import (
    FUTURES_HOTPOINT_SCOPE_POLICY,
    FUTURES_HOTPOINT_GOAL_ID,
    HotpointCancelState,
    HotpointControlAction,
    HotpointCreateState,
    HotpointKillSwitchState,
    HotpointPlacementOutcome,
    HotpointWindowState,
)
from database.database import PostgresDB
from database.operator_hotpoint_control import OperatorHotpointControlRepository
from database.operator_futures_manual_lifecycle import (
    OperatorFuturesManualLifecycleRepository,
)
from core.enums import AdminFuturesManualCallOutcome


pytestmark = [pytest.mark.regression, pytest.mark.integration, pytest.mark.serial]

TEST_DB_HOST = "coinbase-test-postgres"
TEST_DB_PORT = 9876
TEST_DB_PASSWORD = os.environ.get("COINBASE_DB_PASSWORD", "postgres")
PORTFOLIO_ID = "11111111-2222-4333-8444-555555555555"
PARENT_ID = "11111111-1111-4111-8111-111111111111"
FUTURES_PARENT_ID = "22222222-2222-4222-8222-222222222222"
_SCHEMA_RE = re.compile(r"^test_operator_hotpoint_[0-9a-f]{32}$")


def _goal13_candidate(
    *,
    parent_id: str,
    window_id: str,
    trigger_evidence_sha256: str,
) -> dict[str, str]:
    return {
        "product_id": "AVP-20DEC30-CDE",
        "side": "BUY",
        "order_type": "LIMIT_GTC",
        "post_only": "true",
        "contract_count": "1",
        "limit_price": "4.99",
        "contract_size": "10",
        "product_price": "5",
        "reference_price": "5.01",
        "reference_price_source": (
            "max_product_price_and_fresh_best_ask"
        ),
        "price_increment": "0.01",
        "best_bid": "5.00",
        "best_ask": "5.01",
        "opening_reference_notional_usdc": "50.10",
        "maximum_exposure_reference_notional_usdc": "50.10",
        "buffered_close_reference_notional_usdc": "60.120",
        "branch_turnover_reference_notional_usdc": "110.220",
        "close_buffer_multiplier": "1.20",
        "opening_cap_usdc": "100",
        "exposure_cap_usdc": "150",
        "turnover_cap_usdc": "300",
        "product_policy_revision": str(
            FUTURES_HOTPOINT_POLICY_REVISION
        ),
        "product_policy_sha256": FUTURES_HOTPOINT_POLICY_SHA256,
        "hotpoint_parent_client_order_id": parent_id,
        "hotpoint_window_id": window_id,
        "hotpoint_trigger_evidence_sha256": (
            trigger_evidence_sha256
        ),
        "hotpoint_portfolio_id_sha256": hashlib.sha256(
            PORTFOLIO_ID.encode("utf-8")
        ).hexdigest(),
        "hotpoint_session_compatibility": "OPEN_24X7_GTC",
        "contract_expiry": "2030-12-20T00:00:00+00:00",
        "session_state": "FCM_TRADING_SESSION_STATE_OPEN",
        "session_is_open": "true",
        "after_hours_order_entry_disabled": "false",
        "session_closed_reason": "",
        "twenty_four_by_seven": "true",
        "maintenance_start": "",
        "maintenance_end": "",
        "session_observed_at": datetime.now(timezone.utc).isoformat(),
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }


def _database() -> PostgresDB:
    return PostgresDB(
        host=TEST_DB_HOST,
        port=TEST_DB_PORT,
        database="postgres",
        user="postgres",
        password=TEST_DB_PASSWORD,
    )


def _raw_connection():
    return psycopg2.connect(
        host=TEST_DB_HOST,
        port=TEST_DB_PORT,
        database="postgres",
        user="postgres",
        password=TEST_DB_PASSWORD,
    )


@pytest.fixture
def repository():
    schema = f"test_operator_hotpoint_{uuid.uuid4().hex}"
    assert _SCHEMA_RE.fullmatch(schema)
    admin = _database()
    admin.connect()
    with admin.get_cursor() as cursor:
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.order_parent (
                    id BIGSERIAL PRIMARY KEY,
                    client_order_id VARCHAR(128) UNIQUE NOT NULL,
                    product_id VARCHAR(255) NOT NULL,
                    side VARCHAR(10) NOT NULL,
                    size NUMERIC NOT NULL,
                    price NUMERIC NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    parent_order_id VARCHAR(128),
                    ownership_provenance VARCHAR(64),
                    retail_portfolio_id UUID,
                    auto_placed_by_hotpoint BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            ).format(sql.Identifier(schema))
        )
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.fill_ledger (
                    id BIGSERIAL PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    instrument VARCHAR(32) NOT NULL,
                    side VARCHAR(10) NOT NULL,
                    quantity NUMERIC NOT NULL,
                    price NUMERIC NOT NULL,
                    client_order_id VARCHAR(128) NOT NULL,
                    reconciliation_status VARCHAR(16) NOT NULL
                        DEFAULT 'WS_DERIVED',
                    exchange_fill_identity_sha256 CHAR(64)
                )
                """
            ).format(sql.Identifier(schema))
        )
        cursor.execute(
            sql.SQL(
                """
                INSERT INTO {}.order_parent (
                    client_order_id, product_id, side, size, price, status,
                    parent_order_id, ownership_provenance,
                    retail_portfolio_id, auto_placed_by_hotpoint
                ) VALUES (%s, 'BTC-USDC', 'BUY', 0.00003, 90000, 'OPEN',
                          NULL, 'ADMIN_MANUAL_ROOT', %s, FALSE)
                """
            ).format(sql.Identifier(schema)),
            (PARENT_ID, PORTFOLIO_ID),
        )
    repo_db = _database()
    repo = OperatorHotpointControlRepository(
        repo_db,
        schema=schema,
        configured_portfolio_id=PORTFOLIO_ID,
        product_metadata_provider=lambda _product_id: {
            "base_min_size": "0.00001",
            "base_increment": "0.00001",
            "price_increment": "0.01",
        },
        clock=lambda: datetime.now(timezone.utc),
    )
    repo.ensure_schema()
    try:
        yield repo
    finally:
        repo_db.disconnect()
        with admin.get_cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(
                    sql.Identifier(schema)
                )
            )
        admin.disconnect()


def _control(
    repository: OperatorHotpointControlRepository,
    *,
    action: HotpointControlAction,
    expected_revision: int,
    idempotency_key: str,
    parent_client_order_id: str | None = None,
):
    kwargs = {
        "action": action,
        "expected_revision": expected_revision,
        "authorize_one_bounded_trigger_window": (
            action is HotpointControlAction.ENABLE
        ),
        "acknowledge_unknown_outcome_consumes_create_allowance": (
            action is HotpointControlAction.ENABLE
        ),
        "acknowledge_backend_derives_child_terms": (
            action is HotpointControlAction.ENABLE
        ),
        "idempotency_key": idempotency_key,
        "actor_id": "operator-1",
        "roles": ("admin", "trader"),
        "correlation_id": f"corr-{idempotency_key}",
        "audit_id": str(uuid.uuid4()),
    }
    if parent_client_order_id is not None:
        kwargs["parent_client_order_id"] = parent_client_order_id
    return repository.transition_control(**kwargs)


def _prepare_goal13_trigger(
    repository,
    *,
    parent_size: str = "4",
    projection_size: str = "4",
    projection_filled_size: str = "0",
    clock=None,
    expect_arm_eligible: bool = True,
    configured_portfolio_id: str | None = PORTFOLIO_ID,
):
    with repository.db.get_cursor() as cursor:
        cursor.execute(
            f"""
            CREATE TABLE "{repository.schema}".
                operator_futures_order_projection (
                client_order_id VARCHAR(128) PRIMARY KEY,
                product_id VARCHAR(128) NOT NULL,
                side VARCHAR(8) NOT NULL,
                status VARCHAR(32) NOT NULL,
                order_type VARCHAR(32) NOT NULL,
                time_in_force VARCHAR(32) NOT NULL,
                size VARCHAR(128),
                filled_size VARCHAR(128),
                exchange_order_id_sha256 CHAR(64) NOT NULL,
                authoritatively_nonterminal BOOLEAN NOT NULL
            )
            """
        )
        cursor.execute(
            f"""
            INSERT INTO "{repository.schema}".order_parent (
                client_order_id, product_id, side, size, price, status,
                parent_order_id, ownership_provenance,
                retail_portfolio_id, auto_placed_by_hotpoint
            ) VALUES (
                %s, 'AVP-20DEC30-CDE', 'BUY', %s, 49, 'OPEN',
                NULL, 'ADMIN_MANUAL_ROOT', %s, FALSE
            )
            """,
            (FUTURES_PARENT_ID, parent_size, PORTFOLIO_ID),
        )
        cursor.execute(
            f"""
            INSERT INTO "{repository.schema}".
                operator_futures_order_projection (
                client_order_id, product_id, side, status, order_type,
                time_in_force, size, filled_size,
                exchange_order_id_sha256,
                authoritatively_nonterminal
            ) VALUES (
                %s, 'AVP-20DEC30-CDE', 'BUY', 'OPEN', 'LIMIT',
                'GOOD_UNTIL_CANCELLED', %s, %s, %s, TRUE
            )
            """,
            (
                FUTURES_PARENT_ID,
                projection_size,
                projection_filled_size,
                "a" * 64,
            ),
        )
    goal13 = OperatorHotpointControlRepository(
        repository.db,
        schema=repository.schema,
        configured_portfolio_id=configured_portfolio_id,
        product_metadata_provider=lambda _product_id: {
            "base_min_size": "1",
            "base_increment": "1",
            "price_increment": "0.01",
            "contract_size": "1",
        },
        policy=FUTURES_HOTPOINT_SCOPE_POLICY,
        goal_id=FUTURES_HOTPOINT_GOAL_ID,
        clock=clock or (lambda: datetime.now(timezone.utc)),
    )
    goal13.ensure_schema()
    enabled = _control(
        goal13,
        action=HotpointControlAction.ENABLE,
        expected_revision=0,
        idempotency_key="goal13-helper-enable",
    )
    if expect_arm_eligible:
        armed = _control(
            goal13,
            action=HotpointControlAction.ARM,
            expected_revision=enabled.revision,
            idempotency_key="goal13-helper-arm",
            parent_client_order_id=FUTURES_PARENT_ID,
        )
    else:
        with pytest.raises(
            ValueError,
            match="operator_hotpoint_parent_ineligible",
        ):
            _control(
                goal13,
                action=HotpointControlAction.ARM,
                expected_revision=enabled.revision,
                idempotency_key="goal13-helper-arm-ineligible",
                parent_client_order_id=FUTURES_PARENT_ID,
            )
        armed = None
    return goal13, armed


def _insert_goal13_fill(
    repository,
    *,
    created_at: str,
    ordinal: int,
    quantity: str = "1",
    price: str = "49.00",
) -> None:
    with repository.db.get_cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO "{repository.schema}".fill_ledger (
                created_at, instrument, side, quantity, price,
                client_order_id, reconciliation_status,
                exchange_fill_identity_sha256
            ) VALUES (
                %s, 'AVP-20DEC30-CDE', 'BUY', %s, %s, %s,
                'RECONCILED', %s
            )
            """,
            (
                created_at,
                quantity,
                price,
                FUTURES_PARENT_ID,
                format(ordinal, "064x"),
            ),
        )


@pytest.mark.parametrize(
    ("parent_size", "preexisting_filled_size", "eligible"),
    (
        ("6", "3", False),
        ("7", "3", True),
    ),
)
def test_goal13_parent_requires_capacity_beyond_three_future_increments(
    repository,
    parent_size,
    preexisting_filled_size,
    eligible,
) -> None:
    goal13, armed = _prepare_goal13_trigger(
        repository,
        parent_size=parent_size,
        projection_size=parent_size,
        projection_filled_size=preexisting_filled_size,
        expect_arm_eligible=eligible,
    )

    rows, total = goal13.list_eligible_parents(limit=25, offset=0)

    assert total == (1 if eligible else 0)
    assert bool(rows) is eligible
    assert (armed is not None) is eligible


def test_goal13_raw_id_free_trigger_binds_selected_parent_portfolio_hash(
    repository,
) -> None:
    goal13, armed = _prepare_goal13_trigger(
        repository,
        configured_portfolio_id=None,
    )
    assert armed is not None
    assert goal13.configured_portfolio_id is None
    for ordinal, price in enumerate(
        ("49.00", "49.01", "49.02"),
        start=1,
    ):
        _insert_goal13_fill(
            goal13,
            created_at=(
                datetime.fromisoformat(armed.window_started_at)
                + timedelta(seconds=ordinal)
            ).isoformat(),
            ordinal=ordinal,
            price=price,
        )
    with goal13.db.get_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE "{goal13.schema}".
                operator_futures_order_projection
               SET filled_size = '3'
             WHERE client_order_id = %s
            """,
            (FUTURES_PARENT_ID,),
        )

    _claimed, binding = goal13.claim_futures_trigger(
        expected_revision=armed.revision,
        expected_parent_client_order_id=FUTURES_PARENT_ID,
        idempotency_key="goal13-raw-id-free-run",
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="corr-goal13-raw-id-free-run",
        audit_id=str(uuid.uuid4()),
    )
    portfolio_hash = hashlib.sha256(
        PORTFOLIO_ID.encode("utf-8")
    ).hexdigest()
    assert binding.portfolio_id_sha256 == portfolio_hash

    candidate = _goal13_candidate(
        parent_id=FUTURES_PARENT_ID,
        window_id=str(armed.window_id),
        trigger_evidence_sha256=binding.trigger_evidence_sha256,
    )
    with goal13.db.get_cursor() as cursor:
        goal13.validate_futures_preview_invocation(
            cursor=cursor,
            candidate=candidate,
        )
        cursor.execute("SAVEPOINT goal13_wrong_portfolio_hash")
        with pytest.raises(
            ValueError,
            match=(
                "operator_futures_hotpoint_preview_invocation_"
                "not_authorized"
            ),
        ):
            goal13.validate_futures_preview_invocation(
                cursor=cursor,
                candidate={
                    **candidate,
                    "hotpoint_portfolio_id_sha256": "f" * 64,
                },
            )
        cursor.execute("ROLLBACK TO SAVEPOINT goal13_wrong_portfolio_hash")


def _arm(repository: OperatorHotpointControlRepository):
    enabled = _control(
        repository,
        action=HotpointControlAction.ENABLE,
        expected_revision=0,
        idempotency_key="enable-1",
    )
    return _control(
        repository,
        action=HotpointControlAction.ARM,
        expected_revision=enabled.revision,
        idempotency_key="arm-1",
        parent_client_order_id=PARENT_ID,
    )


def _insert_trigger_fills(
    repository: OperatorHotpointControlRepository,
) -> None:
    with repository.db.get_cursor() as cursor:
        for price in ("90000.00", "90000.01", "90000.02"):
            cursor.execute(
                f"""
                INSERT INTO "{repository.schema}".fill_ledger (
                    instrument, side, quantity, price, client_order_id
                ) VALUES ('BTC-USDC', 'BUY', 0.00001, %s, %s)
                """,
                (price, PARENT_ID),
            )


def test_enable_and_arm_are_revision_bound_and_idempotent(repository) -> None:
    initial = repository.read()
    assert initial.revision == 0
    assert initial.kill_switch_state is HotpointKillSwitchState.DISABLED
    assert initial.window_state is HotpointWindowState.NONE

    armed = _arm(repository)
    assert armed.revision == 2
    assert armed.kill_switch_state is HotpointKillSwitchState.ENABLED
    assert armed.window_state is HotpointWindowState.ARMED
    assert armed.parent_client_order_id == PARENT_ID
    assert armed.product_id == "BTC-USDC"
    assert armed.window_id is not None

    replay = _control(
        repository,
        action=HotpointControlAction.ARM,
        expected_revision=1,
        idempotency_key="arm-1",
        parent_client_order_id=PARENT_ID,
    )
    assert replay == armed

    with pytest.raises(ValueError, match="operator_hotpoint_window_single_use"):
        _control(
            repository,
            action=HotpointControlAction.ARM,
            expected_revision=2,
            idempotency_key="arm-2",
            parent_client_order_id=PARENT_ID,
        )


def test_claim_derives_one_cap_safe_plan_and_has_one_concurrent_winner(
    repository,
) -> None:
    _arm(repository)
    _insert_trigger_fills(repository)

    def claim():
        return repository.claim_placement(
            idempotency_key=f"run-{uuid.uuid4()}",
            actor_id="operator-1",
            roles=("admin", "trader"),
            correlation_id=f"corr-{uuid.uuid4()}",
            audit_id=str(uuid.uuid4()),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: claim(), range(2)))

    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    record, plan = winners[0]
    assert record.create_state is HotpointCreateState.CLAIMED
    assert record.window_state is HotpointWindowState.CLAIMED
    assert plan.parent_client_order_id == PARENT_ID
    assert plan.child_client_order_id == record.child_client_order_id
    assert plan.product_id == "BTC-USDC"
    assert plan.side == "BUY"
    assert plan.portfolio_id == PORTFOLIO_ID
    assert plan.post_only is True
    assert plan.base_size == Decimal("0.00001")
    assert plan.submitted_notional_usdc <= Decimal("1.00")
    assert plan.possible_execution_notional_usdc <= Decimal("1.00")
    assert plan.max_submitted_notional_usdc == Decimal("3.10")
    assert plan.max_possible_execution_notional_usdc == Decimal("1.00")

    finalized = repository.finalize_placement(
        placement_claim_id=plan.placement_claim_id,
        outcome=HotpointPlacementOutcome.ACCEPTED,
        child_client_order_id=plan.child_client_order_id,
        diagnostic_code="operator_hotpoint_create_accepted",
        exchange_invoked=True,
    )
    assert finalized.window_state is HotpointWindowState.TERMINAL
    assert finalized.create_state is HotpointCreateState.ACCEPTED
    assert finalized.kill_switch_state is HotpointKillSwitchState.DISABLED

    assert claim() is None


def test_no_trigger_is_call_free_and_stranded_claim_recovers_unknown(
    repository,
) -> None:
    _arm(repository)
    assert (
        repository.claim_placement(
            idempotency_key="run-no-trigger",
            actor_id="operator-1",
            roles=("admin", "trader"),
            correlation_id="corr-no-trigger",
            audit_id=str(uuid.uuid4()),
        )
        is None
    )
    assert repository.read().window_state is HotpointWindowState.ARMED

    _insert_trigger_fills(repository)
    claimed = repository.claim_placement(
        idempotency_key="run-claimed",
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="corr-claimed",
        audit_id=str(uuid.uuid4()),
    )
    assert claimed is not None

    recovered = repository.recover_stranded_claim()
    assert recovered is not None
    assert recovered.window_state is HotpointWindowState.TERMINAL
    assert recovered.create_state is HotpointCreateState.UNKNOWN
    assert recovered.kill_switch_state is HotpointKillSwitchState.DISABLED
    assert recovered.diagnostic_code == "operator_hotpoint_create_outcome_unknown"


def test_exact_accepted_child_cancel_is_claimed_once_and_recoverable(
    repository,
) -> None:
    _arm(repository)
    _insert_trigger_fills(repository)
    claimed = repository.claim_placement(
        idempotency_key="run-for-cancel",
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="corr-create",
        audit_id=str(uuid.uuid4()),
    )
    assert claimed is not None
    _record, placement = claimed
    repository.finalize_placement(
        placement_claim_id=placement.placement_claim_id,
        outcome=HotpointPlacementOutcome.ACCEPTED,
        child_client_order_id=placement.child_client_order_id,
        diagnostic_code="operator_hotpoint_create_accepted",
        exchange_invoked=True,
    )
    with repository.db.get_cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO "{repository.schema}".order_parent (
                client_order_id, product_id, side, size, price, status,
                parent_order_id, ownership_provenance,
                retail_portfolio_id, auto_placed_by_hotpoint
            ) VALUES (%s, 'BTC-USDC', 'BUY', %s, %s, 'OPEN',
                      %s, 'ADMIN_HOTPOINT_CHILD', %s, TRUE)
            """,
            (
                placement.child_client_order_id,
                placement.base_size,
                placement.limit_price,
                PARENT_ID,
                PORTFOLIO_ID,
            ),
        )

    cancel_claim = repository.claim_cancel(
        idempotency_key="cancel-1",
        actor_id="operator-2",
        roles=("admin",),
        correlation_id="corr-cancel",
        audit_id=str(uuid.uuid4()),
    )
    assert cancel_claim is not None
    record, plan = cancel_claim
    assert record.cancel_state is HotpointCancelState.CLAIMED
    assert plan.child_client_order_id == placement.child_client_order_id
    assert plan.parent_client_order_id == PARENT_ID
    assert plan.plan_sha256 == placement.evidence_sha256
    assert plan.portfolio_id == PORTFOLIO_ID

    recovered = repository.recover_stranded_claim()
    assert recovered is not None
    assert recovered.cancel_state is HotpointCancelState.UNKNOWN
    assert recovered.diagnostic_code == (
        "operator_hotpoint_cancel_outcome_unknown"
    )
    assert (
        repository.claim_cancel(
            idempotency_key="cancel-2",
            actor_id="operator-2",
            roles=("admin",),
            correlation_id="corr-cancel-2",
            audit_id=str(uuid.uuid4()),
        )
        is None
    )


def test_futures_scope_uses_distinct_durable_control_and_one_contract_v3_plan(
    repository,
) -> None:
    with repository.db.get_cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO "{repository.schema}".order_parent (
                client_order_id, product_id, side, size, price, status,
                parent_order_id, ownership_provenance,
                retail_portfolio_id, auto_placed_by_hotpoint
            ) VALUES (
                %s, 'AVP-20DEC30-CDE', 'BUY', 1, 49, 'OPEN',
                NULL, 'ADMIN_MANUAL_ROOT', %s, FALSE
            )
            """,
            (FUTURES_PARENT_ID, PORTFOLIO_ID),
        )

    futures = OperatorHotpointControlRepository(
        repository.db,
        schema=repository.schema,
        configured_portfolio_id=PORTFOLIO_ID,
        product_metadata_provider=lambda _product_id: {
            "base_min_size": "1",
            "base_increment": "0.25",
            "price_increment": "0.01",
            "contract_size": "1",
        },
        policy=FUTURES_HOTPOINT_SCOPE_POLICY,
        clock=lambda: datetime.now(timezone.utc),
    )
    futures.ensure_schema()
    enabled = _control(
        futures,
        action=HotpointControlAction.ENABLE,
        expected_revision=0,
        idempotency_key="futures-enable-1",
    )
    armed = _control(
        futures,
        action=HotpointControlAction.ARM,
        expected_revision=enabled.revision,
        idempotency_key="futures-arm-1",
        parent_client_order_id=FUTURES_PARENT_ID,
    )
    with repository.db.get_cursor() as cursor:
        for price in ("49.00", "49.01", "49.02"):
            cursor.execute(
                f"""
                INSERT INTO "{repository.schema}".fill_ledger (
                    instrument, side, quantity, price, client_order_id
                ) VALUES ('AVP-20DEC30-CDE', 'BUY', 1, %s, %s)
                """,
                (price, FUTURES_PARENT_ID),
            )

    claim = futures.claim_placement(
        idempotency_key="futures-run-1",
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="corr-futures-run-1",
        audit_id=str(uuid.uuid4()),
    )

    assert claim is not None
    record, plan = claim
    assert armed.product_id == "AVP-20DEC30-CDE"
    assert record.create_state is HotpointCreateState.CLAIMED
    assert plan.product_id == "AVP-20DEC30-CDE"
    assert plan.base_size == Decimal("1")
    assert plan.max_submitted_notional_usdc == Decimal("100")
    assert plan.max_possible_execution_notional_usdc == Decimal("150")
    assert plan.submitted_notional_usdc < Decimal("100")
    assert repository.read().revision == 0


def test_spot_and_futures_share_one_goal_global_create_allowance(
    repository,
) -> None:
    with repository.db.get_cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO "{repository.schema}".order_parent (
                client_order_id, product_id, side, size, price, status,
                parent_order_id, ownership_provenance,
                retail_portfolio_id, auto_placed_by_hotpoint
            ) VALUES (
                %s, 'AVP-20DEC30-CDE', 'BUY', 1, 49, 'OPEN',
                NULL, 'ADMIN_MANUAL_ROOT', %s, FALSE
            )
            """,
            (FUTURES_PARENT_ID, PORTFOLIO_ID),
        )
    futures = OperatorHotpointControlRepository(
        repository.db,
        schema=repository.schema,
        configured_portfolio_id=PORTFOLIO_ID,
        product_metadata_provider=lambda _product_id: {
            "base_min_size": "1",
            "base_increment": "1",
            "price_increment": "0.01",
            "contract_size": "1",
        },
        policy=FUTURES_HOTPOINT_SCOPE_POLICY,
        clock=lambda: datetime.now(timezone.utc),
    )
    futures.ensure_schema()
    _arm(repository)
    futures_enabled = _control(
        futures,
        action=HotpointControlAction.ENABLE,
        expected_revision=0,
        idempotency_key="global-futures-enable",
    )
    _control(
        futures,
        action=HotpointControlAction.ARM,
        expected_revision=futures_enabled.revision,
        idempotency_key="global-futures-arm",
        parent_client_order_id=FUTURES_PARENT_ID,
    )
    _insert_trigger_fills(repository)
    with repository.db.get_cursor() as cursor:
        for price in ("49.00", "49.01", "49.02"):
            cursor.execute(
                f"""
                INSERT INTO "{repository.schema}".fill_ledger (
                    instrument, side, quantity, price, client_order_id
                ) VALUES ('AVP-20DEC30-CDE', 'BUY', 1, %s, %s)
                """,
                (price, FUTURES_PARENT_ID),
            )

    spot_claim = repository.claim_placement(
        idempotency_key="global-spot-run",
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="corr-global-spot-run",
        audit_id=str(uuid.uuid4()),
    )
    futures_claim = futures.claim_placement(
        idempotency_key="global-futures-run",
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="corr-global-futures-run",
        audit_id=str(uuid.uuid4()),
    )

    assert spot_claim is not None
    assert futures_claim is None
    assert repository.read().goal_create_claim_consumed is True
    assert repository.read().goal_create_claim_domain == "SPOT"
    assert futures.read().goal_create_claim_consumed is True
    assert futures.read().goal_create_claim_domain == "SPOT"
    assert futures.read().create_state is HotpointCreateState.NOT_CLAIMED


def test_goal13_futures_trigger_is_projection_backed_reconciled_and_separate(
    repository,
) -> None:
    with repository.db.get_cursor() as cursor:
        cursor.execute(
            f"""
            CREATE TABLE "{repository.schema}".
                operator_futures_order_projection (
                client_order_id VARCHAR(128) PRIMARY KEY,
                product_id VARCHAR(128) NOT NULL,
                side VARCHAR(8) NOT NULL,
                status VARCHAR(32) NOT NULL,
                order_type VARCHAR(32) NOT NULL,
                time_in_force VARCHAR(32) NOT NULL,
                size VARCHAR(128),
                filled_size VARCHAR(128),
                exchange_order_id_sha256 CHAR(64) NOT NULL,
                authoritatively_nonterminal BOOLEAN NOT NULL
            )
            """
        )
        cursor.execute(
            f"""
            INSERT INTO "{repository.schema}".order_parent (
                client_order_id, product_id, side, size, price, status,
                parent_order_id, ownership_provenance,
                retail_portfolio_id, auto_placed_by_hotpoint
            ) VALUES (
                %s, 'AVP-20DEC30-CDE', 'BUY', 4.0, 49, 'OPEN',
                NULL, 'ADMIN_MANUAL_ROOT', %s, FALSE
            )
            """,
            (FUTURES_PARENT_ID, PORTFOLIO_ID),
        )
        cursor.execute(
            f"""
            INSERT INTO "{repository.schema}".
                operator_futures_order_projection (
                client_order_id, product_id, side, status, order_type,
                time_in_force, size, filled_size,
                exchange_order_id_sha256,
                authoritatively_nonterminal
            ) VALUES (
                %s, 'AVP-20DEC30-CDE', 'BUY', 'OPEN', 'LIMIT',
                'GOOD_UNTIL_CANCELLED', '4.0', '0.000', %s, TRUE
            )
            """,
            (FUTURES_PARENT_ID, "a" * 64),
        )

    goal13 = OperatorHotpointControlRepository(
        repository.db,
        schema=repository.schema,
        configured_portfolio_id=PORTFOLIO_ID,
        product_metadata_provider=lambda _product_id: {
            "base_min_size": "1",
            "base_increment": "1",
            "price_increment": "0.01",
            "contract_size": "1",
        },
        policy=FUTURES_HOTPOINT_SCOPE_POLICY,
        goal_id=FUTURES_HOTPOINT_GOAL_ID,
        clock=lambda: datetime.now(timezone.utc),
    )
    goal13.ensure_schema()
    rows, total = goal13.list_eligible_parents(limit=25, offset=0)
    assert total == 1
    assert rows == [
        {
            "client_order_id": FUTURES_PARENT_ID,
            "product_id": "AVP-20DEC30-CDE",
            "side": "BUY",
            "status": "OPEN",
        }
    ]
    enabled = _control(
        goal13,
        action=HotpointControlAction.ENABLE,
        expected_revision=0,
        idempotency_key="goal13-enable",
    )
    armed = _control(
        goal13,
        action=HotpointControlAction.ARM,
        expected_revision=enabled.revision,
        idempotency_key="goal13-arm",
        parent_client_order_id=FUTURES_PARENT_ID,
    )
    with repository.db.get_cursor() as cursor:
        for ordinal, price in enumerate(
            ("49.00", "49.01", "49.02"),
            start=1,
        ):
            cursor.execute(
                f"""
                INSERT INTO "{repository.schema}".fill_ledger (
                    created_at, instrument, side, quantity, price,
                    client_order_id, reconciliation_status,
                    exchange_fill_identity_sha256
                ) VALUES (
                    %s::timestamptz + (%s * interval '1 second'),
                    'AVP-20DEC30-CDE', 'BUY', 1, %s, %s,
                    'RECONCILED', %s
                )
                """,
                (
                    armed.window_started_at,
                    ordinal,
                    price,
                    FUTURES_PARENT_ID,
                    format(ordinal, "064x"),
                ),
            )
        cursor.execute(
            f"""
            UPDATE "{repository.schema}".
                operator_futures_order_projection
               SET filled_size = '3.000'
             WHERE client_order_id = %s
            """,
            (FUTURES_PARENT_ID,),
        )

    trigger_readback = goal13.read_futures_trigger_readback()
    assert trigger_readback["trigger_fill_count"] == 3
    assert re.fullmatch(
        r"[0-9a-f]{64}",
        str(trigger_readback["trigger_evidence_sha256"]),
    )
    assert trigger_readback["window_id_sha256"] == hashlib.sha256(
        str(armed.window_id).encode("utf-8")
    ).hexdigest()
    claimed, binding = goal13.claim_futures_trigger(
        expected_revision=armed.revision,
        expected_parent_client_order_id=FUTURES_PARENT_ID,
        idempotency_key="goal13-run",
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="corr-goal13-run",
        audit_id=str(uuid.uuid4()),
    )

    assert claimed.goal_id == FUTURES_HOTPOINT_GOAL_ID
    assert claimed.window_state is HotpointWindowState.ARMED
    assert claimed.create_state is HotpointCreateState.NOT_CLAIMED
    assert claimed.goal_create_claim_consumed is False
    assert binding.parent_client_order_id == FUTURES_PARENT_ID
    assert re.fullmatch(r"[0-9a-f]{64}", binding.trigger_evidence_sha256)
    assert goal13.revalidate_futures_trigger(binding) is True
    with pytest.raises(
        ValueError,
        match="operator_futures_hotpoint_idempotency_conflict",
    ):
        goal13.claim_futures_trigger(
            expected_revision=armed.revision,
            expected_parent_client_order_id=FUTURES_PARENT_ID,
            idempotency_key="goal13-run",
            actor_id="different-operator",
            roles=("admin", "trader"),
            correlation_id="corr-goal13-run",
            audit_id=claimed.audit_id,
        )
    with pytest.raises(
        ValueError,
        match="operator_futures_hotpoint_trigger_owner_active",
    ):
        goal13.claim_futures_trigger(
            expected_revision=claimed.revision,
            expected_parent_client_order_id=FUTURES_PARENT_ID,
            idempotency_key="goal13-run-cycle-2",
            actor_id="operator-2",
            roles=("admin", "trader"),
            correlation_id="corr-goal13-run-cycle-2",
            audit_id=str(uuid.uuid4()),
        )
    coherent = goal13.read()
    assert coherent.actor_id == "operator-1"
    assert coherent.correlation_id == "corr-goal13-run"
    create_claim_id = str(uuid.uuid4())
    child_client_order_id = (
        "operator-futures-hotpoint-v2-"
        f"{uuid.uuid4()}"
    )
    with repository.db.get_cursor() as cursor:
        cursor.execute("SAVEPOINT goal13_create_invocation")
        goal13.validate_futures_create_invocation(
            cursor=cursor,
            candidate=_goal13_candidate(
                parent_id=FUTURES_PARENT_ID,
                window_id=str(armed.window_id),
                trigger_evidence_sha256=(
                    binding.trigger_evidence_sha256
                ),
            ),
            claim_id=create_claim_id,
            client_order_id=child_client_order_id,
        )
        cursor.execute(
            f"""
            SELECT window_state, create_state, placement_claim_id,
                   child_client_order_id, create_exchange_invoked
              FROM {goal13._table('operator_hotpoint_control')}
             WHERE goal_id = %s
            """,
            (FUTURES_HOTPOINT_GOAL_ID,),
        )
        sealed = cursor.fetchone()
        assert sealed == (
            "CLAIMED",
            "CLAIMED",
            create_claim_id,
            child_client_order_id,
            True,
        )
        cursor.execute(
            f"""
            SELECT create_claim_id, create_claim_domain
              FROM "{repository.schema}".operator_hotpoint_goal_allowance
             WHERE goal_id = %s
            """,
            (FUTURES_HOTPOINT_GOAL_ID,),
        )
        allowance = cursor.fetchone()
        assert allowance is not None
        assert str(allowance[0]) == create_claim_id
        assert allowance[1] == "FUTURES"
        cursor.execute("ROLLBACK TO SAVEPOINT goal13_create_invocation")
    assert goal13.read().create_state is HotpointCreateState.NOT_CLAIMED
    assert goal13.read().goal_create_claim_consumed is False
    with pytest.raises(
        ValueError,
        match="operator_futures_hotpoint_preview_required",
    ):
        goal13.claim_placement(
            idempotency_key="goal13-legacy-create-forbidden",
            actor_id="operator-1",
            roles=("admin", "trader"),
            correlation_id="corr-goal13-legacy-create-forbidden",
            audit_id=str(uuid.uuid4()),
        )
    disabled = _control(
        goal13,
        action=HotpointControlAction.DISABLE,
        expected_revision=claimed.revision,
        idempotency_key="goal13-disable-after-trigger",
    )
    assert disabled.kill_switch_state is HotpointKillSwitchState.DISABLED
    assert goal13.revalidate_futures_trigger(binding) is False
    with repository.db.get_cursor() as cursor:
        candidate = _goal13_candidate(
            parent_id=FUTURES_PARENT_ID,
            window_id=str(armed.window_id),
            trigger_evidence_sha256=(
                binding.trigger_evidence_sha256
            ),
        )
        with pytest.raises(
            ValueError,
            match=(
                "operator_futures_hotpoint_preview_invocation_"
                "not_authorized"
            ),
        ):
            goal13.validate_futures_preview_invocation(
                cursor=cursor,
                candidate=candidate,
            )
        with pytest.raises(
            ValueError,
            match=(
                "operator_futures_hotpoint_create_invocation_"
                "not_authorized"
            ),
        ):
            goal13.validate_futures_create_invocation(
                cursor=cursor,
                candidate=candidate,
                claim_id=str(uuid.uuid4()),
                client_order_id=(
                    "operator-futures-hotpoint-v2-"
                    f"{uuid.uuid4()}"
                ),
            )
    blocked = goal13.read()
    assert blocked.create_state is HotpointCreateState.NOT_CLAIMED
    assert blocked.create_exchange_invoked is None
    assert blocked.goal_create_claim_consumed is False
    assert repository.read().revision == 0


def test_goal13_restart_releases_terminal_eligible_prepreview_trigger_owner(
    repository,
) -> None:
    goal13, armed = _prepare_goal13_trigger(repository)
    started = datetime.fromisoformat(str(armed.window_started_at))
    for ordinal in range(1, 4):
        _insert_goal13_fill(
            repository,
            created_at=(started + timedelta(seconds=ordinal)).isoformat(),
            ordinal=ordinal,
            price=f"49.{ordinal:02d}",
        )
    with repository.db.get_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE "{repository.schema}".
                operator_futures_order_projection
               SET filled_size = '3'
             WHERE client_order_id = %s
            """,
            (FUTURES_PARENT_ID,),
        )

    lifecycle = OperatorFuturesManualLifecycleRepository(
        _database(),
        schema=repository.schema,
        configured_portfolio_id=PORTFOLIO_ID,
        goal_id=FUTURES_HOTPOINT_GOAL_ID,
        eligibility_evidence_validator=lambda _result: None,
        claim_validator=lambda **_kwargs: None,
        preview_invocation_validator=lambda **_kwargs: None,
        create_invocation_validator=lambda **_kwargs: None,
        client_order_id_prefix="operator-futures-hotpoint-v2-",
    )
    lifecycle.ensure_schema()
    try:
        owner_context = FuturesManualRequestContext(
            actor_id="operator-owner",
            roles=("admin", "trader"),
            expected_revision=armed.revision,
            idempotency_key="goal13-eligible-prepreview-owner",
            correlation_id="corr-goal13-eligible-prepreview-owner",
            audit_id=str(uuid.uuid4()),
            operator_intent=(
                "preview_submit_and_safe_closeout_one_futures_order"
            ),
        )
        command = lifecycle.claim_hotpoint_external_command(
            action="RUN_ONCE",
            context=owner_context,
            request_payload={"expected_revision": armed.revision},
        )
        claimed, _binding = goal13.claim_futures_trigger(
            expected_revision=armed.revision,
            expected_parent_client_order_id=FUTURES_PARENT_ID,
            idempotency_key=owner_context.idempotency_key,
            actor_id=owner_context.actor_id,
            roles=owner_context.roles,
            correlation_id=owner_context.correlation_id,
            audit_id=owner_context.audit_id,
        )
        with lifecycle.db.get_cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE "{repository.schema}".
                    operator_futures_manual_goal
                   SET cycles_used = 1,
                       active_cycle_number = NULL,
                       eligibility_outcome = 'ELIGIBLE',
                       preview_outcome = 'NOT_RUN',
                       create_outcome = 'NOT_RUN'
                 WHERE goal_id = %s
                """,
                (FUTURES_HOTPOINT_GOAL_ID,),
            )
        lifecycle.finish_hotpoint_external_command(
            command_id=command.command_id,
            outcome="UNKNOWN",
            result_snapshot=None,
            error_code=(
                "operator_futures_hotpoint_command_outcome_unknown"
            ),
            http_status_code=503,
        )
    finally:
        lifecycle.db.disconnect()

    restarted_db = _database()
    restarted = OperatorHotpointControlRepository(
        restarted_db,
        schema=repository.schema,
        configured_portfolio_id=PORTFOLIO_ID,
        product_metadata_provider=lambda _product_id: {
            "base_min_size": "1",
            "base_increment": "1",
            "price_increment": "0.01",
            "contract_size": "1",
        },
        policy=FUTURES_HOTPOINT_SCOPE_POLICY,
        goal_id=FUTURES_HOTPOINT_GOAL_ID,
        clock=lambda: datetime.now(timezone.utc),
    )
    try:
        restarted.ensure_schema()
        successor, _binding = restarted.claim_futures_trigger(
            expected_revision=claimed.revision,
            expected_parent_client_order_id=FUTURES_PARENT_ID,
            idempotency_key="goal13-eligible-prepreview-successor",
            actor_id="operator-successor",
            roles=("admin", "trader"),
            correlation_id="corr-goal13-eligible-prepreview-successor",
            audit_id=str(uuid.uuid4()),
        )
        assert successor.correlation_id == (
            "corr-goal13-eligible-prepreview-successor"
        )
        assert successor.create_state is HotpointCreateState.NOT_CLAIMED
        assert successor.goal_create_claim_consumed is False
    finally:
        restarted_db.disconnect()


def test_goal13_does_not_trigger_across_different_hotpoint_buckets(
    repository,
) -> None:
    with repository.db.get_cursor() as cursor:
        cursor.execute(
            f"""
            CREATE TABLE "{repository.schema}".
                operator_futures_order_projection (
                client_order_id VARCHAR(128) PRIMARY KEY,
                product_id VARCHAR(128) NOT NULL,
                side VARCHAR(8) NOT NULL,
                status VARCHAR(32) NOT NULL,
                order_type VARCHAR(32) NOT NULL,
                time_in_force VARCHAR(32) NOT NULL,
                size VARCHAR(128),
                filled_size VARCHAR(128),
                exchange_order_id_sha256 CHAR(64) NOT NULL,
                authoritatively_nonterminal BOOLEAN NOT NULL
            )
            """
        )
        cursor.execute(
            f"""
            INSERT INTO "{repository.schema}".order_parent (
                client_order_id, product_id, side, size, price, status,
                parent_order_id, ownership_provenance,
                retail_portfolio_id, auto_placed_by_hotpoint
            ) VALUES (
                %s, 'AVP-20DEC30-CDE', 'BUY', 4, 49, 'OPEN',
                NULL, 'ADMIN_MANUAL_ROOT', %s, FALSE
            )
            """,
            (FUTURES_PARENT_ID, PORTFOLIO_ID),
        )
        cursor.execute(
            f"""
            INSERT INTO "{repository.schema}".
                operator_futures_order_projection (
                client_order_id, product_id, side, status, order_type,
                time_in_force, size, filled_size,
                exchange_order_id_sha256,
                authoritatively_nonterminal
            ) VALUES (
                %s, 'AVP-20DEC30-CDE', 'BUY', 'OPEN', 'LIMIT',
                'GOOD_UNTIL_CANCELLED', '4', '0', %s, TRUE
            )
            """,
            (FUTURES_PARENT_ID, "a" * 64),
        )
    goal13 = OperatorHotpointControlRepository(
        repository.db,
        schema=repository.schema,
        configured_portfolio_id=PORTFOLIO_ID,
        product_metadata_provider=lambda _product_id: {
            "base_increment": "1",
        },
        policy=FUTURES_HOTPOINT_SCOPE_POLICY,
        goal_id=FUTURES_HOTPOINT_GOAL_ID,
        clock=lambda: datetime.now(timezone.utc),
    )
    goal13.ensure_schema()
    enabled = _control(
        goal13,
        action=HotpointControlAction.ENABLE,
        expected_revision=0,
        idempotency_key="goal13-buckets-enable",
    )
    armed = _control(
        goal13,
        action=HotpointControlAction.ARM,
        expected_revision=enabled.revision,
        idempotency_key="goal13-buckets-arm",
        parent_client_order_id=FUTURES_PARENT_ID,
    )
    with repository.db.get_cursor() as cursor:
        for ordinal, price in enumerate(("49", "50", "51"), start=1):
            cursor.execute(
                f"""
                INSERT INTO "{repository.schema}".fill_ledger (
                    created_at, instrument, side, quantity, price,
                    client_order_id, reconciliation_status,
                    exchange_fill_identity_sha256
                ) VALUES (
                    %s::timestamptz + (%s * interval '1 second'),
                    'AVP-20DEC30-CDE', 'BUY', 1, %s, %s,
                    'RECONCILED', %s
                )
                """,
                (
                    armed.window_started_at,
                    ordinal,
                    price,
                    FUTURES_PARENT_ID,
                    format(ordinal, "064x"),
                ),
            )
        cursor.execute(
            f"""
            UPDATE "{repository.schema}".
                operator_futures_order_projection
               SET filled_size = '3'
             WHERE client_order_id = %s
            """,
            (FUTURES_PARENT_ID,),
        )
    with pytest.raises(
        ValueError,
        match="operator_futures_hotpoint_trigger_not_satisfied",
    ):
        goal13.claim_futures_trigger(
            expected_revision=armed.revision,
            expected_parent_client_order_id=FUTURES_PARENT_ID,
            idempotency_key="goal13-buckets-run",
            actor_id="operator-1",
            roles=("admin", "trader"),
            correlation_id="corr-goal13-buckets-run",
            audit_id=str(uuid.uuid4()),
        )
    trigger_readback = goal13.read_futures_trigger_readback()
    assert trigger_readback["trigger_fill_count"] == 1
    assert trigger_readback["trigger_evidence_sha256"] is None
    assert goal13.read().create_state is HotpointCreateState.NOT_CLAIMED


def test_goal13_read_materializes_expiry_at_exact_sixty_second_boundary(
    repository,
) -> None:
    now = [datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)]
    goal13, armed = _prepare_goal13_trigger(
        repository,
        clock=lambda: now[0],
    )
    started = datetime.fromisoformat(str(armed.window_started_at))

    now[0] = started + timedelta(seconds=60) - timedelta(microseconds=1)
    before = goal13.read()
    assert before.window_state is HotpointWindowState.ARMED
    assert before.revision == armed.revision

    now[0] = started + timedelta(seconds=60)
    exact = goal13.read()
    assert exact.window_state is HotpointWindowState.EXPIRED
    assert exact.revision == armed.revision + 1
    assert exact.diagnostic_code == (
        "operator_futures_hotpoint_window_expired"
    )
    actions = OperatorFuturesHotpointV2Service._allowed_actions(
        exact,
        SimpleNamespace(
            preview_outcome=AdminFuturesManualCallOutcome.NOT_RUN,
            active_cycle_number=None,
            cycles_used=0,
            client_order_id=None,
            execution_claim_id=None,
            create_outcome=AdminFuturesManualCallOutcome.NOT_RUN,
            create_exchange_invoked=None,
            reconciliation_outcome=(
                AdminFuturesManualCallOutcome.NOT_RUN
            ),
        ),
        trigger_fill_count=3,
        trigger_evidence_sha256="b" * 64,
    )
    assert actions == ("DISABLE",)

    now[0] = started + timedelta(seconds=61)
    after = goal13.read()
    assert after.window_state is HotpointWindowState.EXPIRED
    assert after.revision == exact.revision


@pytest.mark.parametrize(
    ("parent_size", "projection_filled_size", "fills", "code"),
    (
        (
            "4",
            "1",
            (("window", "0.5"),),
            "operator_futures_hotpoint_fill_conservation_invalid",
        ),
        (
            "4",
            "4",
            (
                ("window", "1"),
                ("window", "1"),
                ("window", "1"),
                ("window", "1"),
            ),
            "operator_futures_hotpoint_parent_projection_invalid",
        ),
        (
            "4",
            "5",
            (
                ("window", "1"),
                ("window", "1"),
                ("window", "1"),
                ("window", "1"),
                ("window", "1"),
            ),
            "operator_futures_hotpoint_parent_projection_invalid",
        ),
        (
            "5",
            "4",
            (
                ("before", "2"),
                ("window", "1"),
                ("window", "1"),
                ("window", "1"),
            ),
            "operator_futures_hotpoint_fill_conservation_invalid",
        ),
    ),
)
def test_goal13_trigger_rejects_nonconserved_parent_fill_evidence(
    repository,
    parent_size,
    projection_filled_size,
    fills,
    code,
) -> None:
    goal13, armed = _prepare_goal13_trigger(
        repository,
        parent_size=parent_size,
        projection_size=parent_size,
    )
    started = datetime.fromisoformat(str(armed.window_started_at))
    for ordinal, (placement, quantity) in enumerate(fills, start=1):
        observed = (
            started - timedelta(seconds=1)
            if placement == "before"
            else started + timedelta(seconds=ordinal)
        )
        _insert_goal13_fill(
            repository,
            created_at=observed.isoformat(),
            ordinal=ordinal,
            quantity=quantity,
            price=f"49.{ordinal:02d}",
        )
    with repository.db.get_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE "{repository.schema}".
                operator_futures_order_projection
               SET filled_size = %s
             WHERE client_order_id = %s
            """,
            (projection_filled_size, FUTURES_PARENT_ID),
        )

    with pytest.raises(ValueError, match=code):
        goal13.read_futures_trigger_readback()
    assert goal13.read().create_state is HotpointCreateState.NOT_CLAIMED
    assert goal13.read().goal_create_claim_consumed is False


def test_goal13_preview_and_create_revalidate_every_parent_authority_field(
    repository,
) -> None:
    goal13, armed = _prepare_goal13_trigger(repository)
    started = datetime.fromisoformat(str(armed.window_started_at))
    for ordinal in range(1, 4):
        _insert_goal13_fill(
            repository,
            created_at=(started + timedelta(seconds=ordinal)).isoformat(),
            ordinal=ordinal,
            price=f"49.{ordinal:02d}",
        )
    with repository.db.get_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE "{repository.schema}".
                operator_futures_order_projection
               SET filled_size = '3'
             WHERE client_order_id = %s
            """,
            (FUTURES_PARENT_ID,),
        )
    claimed, binding = goal13.claim_futures_trigger(
        expected_revision=armed.revision,
        expected_parent_client_order_id=FUTURES_PARENT_ID,
        idempotency_key="goal13-boundary-owner",
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="corr-goal13-boundary-owner",
        audit_id=str(uuid.uuid4()),
    )
    candidate = _goal13_candidate(
        parent_id=FUTURES_PARENT_ID,
        window_id=str(armed.window_id),
        trigger_evidence_sha256=binding.trigger_evidence_sha256,
    )
    mutations = (
        (
            "order_parent",
            "product_id = 'BIP-20DEC30-CDE'",
        ),
        ("order_parent", "side = 'SELL'"),
        ("order_parent", "status = 'FILLED'"),
        ("order_parent", "parent_order_id = 'other-parent'"),
        ("order_parent", "ownership_provenance = 'UNKNOWN'"),
        (
            "order_parent",
            (
                "retail_portfolio_id = "
                "'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'"
            ),
        ),
        ("order_parent", "auto_placed_by_hotpoint = TRUE"),
        ("order_parent", "size = 5"),
        (
            "operator_futures_order_projection",
            "product_id = 'BIP-20DEC30-CDE'",
        ),
        ("operator_futures_order_projection", "side = 'SELL'"),
        ("operator_futures_order_projection", "status = 'FILLED'"),
        ("operator_futures_order_projection", "order_type = 'MARKET'"),
        (
            "operator_futures_order_projection",
            "time_in_force = 'IMMEDIATE_OR_CANCEL'",
        ),
        ("operator_futures_order_projection", "size = '4.5'"),
        ("operator_futures_order_projection", "filled_size = '4'"),
        (
            "operator_futures_order_projection",
            "authoritatively_nonterminal = FALSE",
        ),
    )
    with repository.db.get_cursor() as cursor:
        for index, (table, assignment) in enumerate(mutations):
            savepoint = f"goal13_parent_mutation_{index}"
            cursor.execute(f"SAVEPOINT {savepoint}")
            cursor.execute(
                f"""
                UPDATE "{repository.schema}".{table}
                   SET {assignment}
                 WHERE client_order_id = %s
                """,
                (FUTURES_PARENT_ID,),
            )
            with pytest.raises(
                ValueError,
                match=(
                    "operator_futures_hotpoint_preview_invocation_"
                    "not_authorized"
                ),
            ):
                goal13.validate_futures_preview_invocation(
                    cursor=cursor,
                    candidate=candidate,
                )
            with pytest.raises(
                ValueError,
                match=(
                    "operator_futures_hotpoint_create_invocation_"
                    "not_authorized"
                ),
            ):
                goal13.validate_futures_create_invocation(
                    cursor=cursor,
                    candidate=candidate,
                    claim_id=str(uuid.uuid4()),
                    client_order_id=(
                        "operator-futures-hotpoint-v2-"
                        f"{uuid.uuid4()}"
                    ),
                )
            cursor.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
    unchanged = goal13.read()
    assert unchanged.revision == claimed.revision
    assert unchanged.create_state is HotpointCreateState.NOT_CLAIMED
    assert unchanged.create_exchange_invoked is None
    assert unchanged.goal_create_claim_consumed is False


def test_goal13_latched_trigger_readback_survives_parent_terminalization(
    repository,
) -> None:
    goal13, armed = _prepare_goal13_trigger(repository)
    started = datetime.fromisoformat(str(armed.window_started_at))
    for ordinal in range(1, 4):
        _insert_goal13_fill(
            repository,
            created_at=(started + timedelta(seconds=ordinal)).isoformat(),
            ordinal=ordinal,
            price=f"49.{ordinal:02d}",
        )
    with repository.db.get_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE "{repository.schema}".
                operator_futures_order_projection
               SET filled_size = '3'
             WHERE client_order_id = %s
            """,
            (FUTURES_PARENT_ID,),
        )
    _claimed, binding = goal13.claim_futures_trigger(
        expected_revision=armed.revision,
        expected_parent_client_order_id=FUTURES_PARENT_ID,
        idempotency_key="goal13-latched-readback-owner",
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="corr-goal13-latched-readback-owner",
        audit_id=str(uuid.uuid4()),
    )
    expected = {
        "trigger_fill_count": 3,
        "trigger_evidence_sha256": binding.trigger_evidence_sha256,
        "window_id_sha256": hashlib.sha256(
            str(armed.window_id).encode("utf-8")
        ).hexdigest(),
    }

    with repository.db.get_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE "{repository.schema}".order_parent
               SET status = 'FILLED'
             WHERE client_order_id = %s
            """,
            (FUTURES_PARENT_ID,),
        )
        cursor.execute(
            f"""
            UPDATE "{repository.schema}".
                operator_futures_order_projection
               SET status = 'FILLED',
                   filled_size = size,
                   authoritatively_nonterminal = FALSE
             WHERE client_order_id = %s
            """,
            (FUTURES_PARENT_ID,),
        )

    # Parent authority is revoked before the Preview boundary, so RUN remains
    # fail closed; the already-latched evidence remains readable.
    assert goal13.revalidate_futures_trigger(binding) is False
    with repository.db.get_cursor() as cursor:
        with pytest.raises(
            ValueError,
            match=(
                "operator_futures_hotpoint_preview_invocation_"
                "not_authorized"
            ),
        ):
            goal13.validate_futures_preview_invocation(
                cursor=cursor,
                candidate=_goal13_candidate(
                    parent_id=FUTURES_PARENT_ID,
                    window_id=str(armed.window_id),
                    trigger_evidence_sha256=(
                        binding.trigger_evidence_sha256
                    ),
                ),
            )
    assert goal13.read_futures_trigger_readback() == expected

    terminal = goal13.close_futures_control_after_attempt()
    assert terminal.window_state is HotpointWindowState.TERMINAL
    assert goal13.read_futures_trigger_readback() == expected

    restarted = OperatorHotpointControlRepository(
        repository.db,
        schema=repository.schema,
        configured_portfolio_id=PORTFOLIO_ID,
        product_metadata_provider=lambda _product_id: {
            "base_min_size": "1",
            "base_increment": "1",
            "price_increment": "0.01",
            "contract_size": "1",
        },
        policy=FUTURES_HOTPOINT_SCOPE_POLICY,
        goal_id=FUTURES_HOTPOINT_GOAL_ID,
        clock=lambda: datetime.now(timezone.utc),
    )
    restarted.ensure_schema()
    assert restarted.read_futures_trigger_readback() == expected
