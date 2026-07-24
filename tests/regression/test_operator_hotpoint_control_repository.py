"""PostgreSQL invariants for one bounded operator Hotpoint placement."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
import os
import re
import uuid

import psycopg2
from psycopg2 import sql
import pytest

from application.admin_api.operator_hotpoint_control import (
    FUTURES_HOTPOINT_SCOPE_POLICY,
    HotpointCancelState,
    HotpointControlAction,
    HotpointCreateState,
    HotpointKillSwitchState,
    HotpointPlacementOutcome,
    HotpointWindowState,
)
from database.database import PostgresDB
from database.operator_hotpoint_control import OperatorHotpointControlRepository


pytestmark = [pytest.mark.regression, pytest.mark.integration, pytest.mark.serial]

TEST_DB_HOST = "coinbase-test-postgres"
TEST_DB_PORT = 9876
TEST_DB_PASSWORD = os.environ.get("COINBASE_DB_PASSWORD", "postgres")
PORTFOLIO_ID = "11111111-2222-4333-8444-555555555555"
PARENT_ID = "11111111-1111-4111-8111-111111111111"
FUTURES_PARENT_ID = "22222222-2222-4222-8222-222222222222"
_SCHEMA_RE = re.compile(r"^test_operator_hotpoint_[0-9a-f]{32}$")


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
                    client_order_id VARCHAR(128) NOT NULL
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
            "base_increment": "1",
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
