from __future__ import annotations

from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
import uuid

import database.order as order_db
import pytest
from core.enums import OrderOwnershipProvenance
from core.models import RevealExecutionPlan
from core.stealth_order_manager import (
    ControlledAdminChildRevealAuthority,
    StealthOrderManager,
)


TEST_PORTFOLIO_ID = "11111111-2222-4333-8444-555555555555"
DEFAULT_PORTFOLIO_ID = "f4dfdb77-aa88-53d0-9c37-da3a0762ce54"
ROOT_CORRELATION_ID = "corr-test-root"
ROOT_AUDIT_ID = "audit-test-root"


def _order_data() -> dict[str, object]:
    return {
        "stealth_order_id": "990e8400-e29b-41d4-a716-446655440000",
        "product_id": "BTC-USDC",
        "side": "SELL",
        "total_size": 0.01,
        "remaining_size": 0.01,
        "limit_price": 101.0,
        "status": "HIDDEN",
        "reveal_condition_type": "price",
        "reveal_condition_json": {"type": "price", "direction": "above"},
        "sizing_strategy_json": {"type": "fixed"},
        "reason": "follow_up_replacement",
        "notes": "filled follow-up",
        "parent_order_id": "880e8400-e29b-41d4-a716-446655440000",
        "anchor_repricing_policy_json": {},
        "anchor_repricing_state_json": {},
        "cancel_reentry_policy_json": {},
        "cancel_reentry_state_json": {},
        "post_fill_retreat_policy_json": {"enabled": False},
    }


class _AtomicCursor:
    def __init__(
        self,
        *,
        existing: bool = False,
        existing_child_portfolio_id: str = TEST_PORTFOLIO_ID,
        root_exists: bool = True,
        root_product_id: str = "BTC-USDC",
        root_parent_order_id: str | None = None,
        root_ownership_provenance: str | None = (
            OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
        ),
        root_portfolio_id: str | None = TEST_PORTFOLIO_ID,
        root_correlation_id: str | None = ROOT_CORRELATION_ID,
        root_audit_id: str | None = ROOT_AUDIT_ID,
    ) -> None:
        self.existing = existing
        self.existing_child_portfolio_id = existing_child_portfolio_id
        self.root_exists = root_exists
        self.root_product_id = root_product_id
        self.root_parent_order_id = root_parent_order_id
        self.root_ownership_provenance = root_ownership_provenance
        self.root_portfolio_id = root_portfolio_id
        self.root_correlation_id = root_correlation_id
        self.root_audit_id = root_audit_id
        self.executions: list[tuple[str, tuple[object, ...]]] = []
        self.description = []
        self._row = None

    def execute(self, query, params=()):
        normalized = " ".join(str(query).split())
        self.executions.append((normalized, tuple(params or ())))
        if normalized.startswith("SELECT product_id, parent_order_id"):
            self.description = [
                ("product_id",),
                ("parent_order_id",),
                ("ownership_provenance",),
                ("retail_portfolio_id",),
                ("correlation_id",),
                ("audit_id",),
            ]
            self._row = (
                self.root_product_id,
                self.root_parent_order_id,
                self.root_ownership_provenance,
                self.root_portfolio_id,
                self.root_correlation_id,
                self.root_audit_id,
            ) if self.root_exists else None
        elif normalized.startswith("SELECT id, product_id"):
            self.description = [
                ("id",),
                ("product_id",),
                ("side",),
                ("size",),
                ("price",),
                ("parent_order_id",),
                ("ownership_provenance",),
                ("retail_portfolio_id",),
                ("correlation_id",),
                ("audit_id",),
            ]
            self._row = (
                7,
                "BTC-USDC",
                "SELL",
                0.01,
                101.0,
                "880e8400-e29b-41d4-a716-446655440000",
                (
                    OrderOwnershipProvenance.ADMIN_FILL_FOLLOW_UP.value
                    if self.root_ownership_provenance
                    == OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
                    else self.root_ownership_provenance
                ),
                self.existing_child_portfolio_id,
                ROOT_CORRELATION_ID,
                ROOT_AUDIT_ID,
            ) if self.existing else None
        elif normalized.startswith("SELECT product_id, side, total_size"):
            self.description = [
                ("product_id",),
                ("side",),
                ("total_size",),
                ("limit_price",),
                ("parent_order_id",),
            ]
            self._row = (
                "BTC-USDC",
                "SELL",
                0.01,
                101.0,
                "880e8400-e29b-41d4-a716-446655440000",
            ) if self.existing else None
        elif normalized.startswith("INSERT INTO order_parent"):
            self.description = [("id",)]
            self._row = (7,)
        else:
            self.description = []
            self._row = None

    def fetchone(self):
        return self._row


class _AtomicDb:
    def __init__(
        self,
        *,
        existing: bool = False,
        existing_child_portfolio_id: str = TEST_PORTFOLIO_ID,
        **cursor_kwargs,
    ) -> None:
        self.cursor = _AtomicCursor(
            existing=existing,
            existing_child_portfolio_id=existing_child_portfolio_id,
            **cursor_kwargs,
        )
        self.context_entries = 0

    @contextmanager
    def get_cursor(self):
        self.context_entries += 1
        yield self.cursor


def test_filled_follow_up_rows_are_written_in_one_atomic_cursor(monkeypatch):
    db = _AtomicDb()
    monkeypatch.setattr(order_db, "DB_CLIENT", db)

    result = order_db.persist_filled_follow_up_atomic(
        order=_order_data(),
        target_movement=0.001,
        target_movement_type="P",
    )

    assert result == (7, True)
    assert db.context_entries == 1
    sql = [query for query, _params in db.cursor.executions]
    assert sum(query.startswith("INSERT INTO order_parent") for query in sql) == 1
    assert sum(query.startswith("INSERT INTO stealth_orders") for query in sql) == 1
    parent_insert = next(
        params
        for query, params in db.cursor.executions
        if query.startswith("INSERT INTO order_parent")
    )
    assert parent_insert[-4:] == (
        OrderOwnershipProvenance.ADMIN_FILL_FOLLOW_UP.value,
        TEST_PORTFOLIO_ID,
        ROOT_CORRELATION_ID,
        ROOT_AUDIT_ID,
    )


def test_filled_follow_up_atomic_write_is_idempotent_for_existing_identity(
    monkeypatch,
):
    db = _AtomicDb(existing=True)
    monkeypatch.setattr(order_db, "DB_CLIENT", db)

    result = order_db.persist_filled_follow_up_atomic(
        order=_order_data(),
        target_movement=0.001,
        target_movement_type="P",
    )

    assert result == (7, False)
    assert not any(
        query.startswith("INSERT INTO")
        for query, _params in db.cursor.executions
    )


def test_filled_follow_up_rejects_existing_child_from_another_portfolio(
    monkeypatch,
):
    db = _AtomicDb(
        existing=True,
        existing_child_portfolio_id=DEFAULT_PORTFOLIO_ID,
    )
    monkeypatch.setattr(order_db, "DB_CLIENT", db)

    with pytest.raises(
        order_db.OrderPersistenceError,
        match="Existing order_parent row conflicts",
    ):
        order_db.persist_filled_follow_up_atomic(
            order=_order_data(),
            target_movement=0.001,
            target_movement_type="P",
        )

    assert not any(
        query.startswith("INSERT INTO")
        for query, _params in db.cursor.executions
    )


def test_legacy_null_provenance_stealth_root_remains_compatible(monkeypatch):
    db = _AtomicDb(
        root_ownership_provenance=None,
        root_portfolio_id=None,
        root_correlation_id=None,
        root_audit_id=None,
    )
    monkeypatch.setattr(order_db, "DB_CLIENT", db)

    assert order_db.persist_filled_follow_up_atomic(
        order=_order_data(),
        target_movement=0.001,
        target_movement_type="P",
    ) == (7, True)

    parent_insert = next(
        params
        for query, params in db.cursor.executions
        if query.startswith("INSERT INTO order_parent")
    )
    assert parent_insert[-4:] == (None, None, None, None)


@pytest.mark.parametrize(
    ("cursor_kwargs", "message"),
    [
        ({"root_exists": False}, "root order_parent row is missing"),
        (
            {
                "root_ownership_provenance": (
                    OrderOwnershipProvenance.EXTERNAL_WS_OBSERVED.value
                )
            },
            "external root",
        ),
        (
            {
                "root_parent_order_id": (
                    "770e8400-e29b-41d4-a716-446655440000"
                )
            },
            "nested root",
        ),
        ({"root_product_id": "ETH-USDC"}, "product conflicts"),
        ({"root_portfolio_id": None}, "portfolio scope"),
        ({"root_correlation_id": None}, "correlation_id"),
        ({"root_audit_id": None}, "audit_id"),
    ],
)
def test_filled_follow_up_rejects_invalid_admin_root_authority(
    monkeypatch,
    cursor_kwargs,
    message,
):
    db = _AtomicDb(**cursor_kwargs)
    monkeypatch.setattr(order_db, "DB_CLIENT", db)

    with pytest.raises(order_db.OrderPersistenceError, match=message):
        order_db.persist_filled_follow_up_atomic(
            order=_order_data(),
            target_movement=0.001,
            target_movement_type="P",
        )

    assert not any(
        query.startswith("INSERT INTO")
        for query, _params in db.cursor.executions
    )


@pytest.mark.integration
@pytest.mark.serial
def test_filled_follow_up_atomic_write_round_trips_both_test_db_rows():
    order_db.create_order_parent_table()
    order_db.create_stealth_orders_table()
    root_id = str(uuid.uuid4())
    child_id = str(uuid.uuid4())
    order_db.insert_order_parent(
        client_order_id=root_id,
        product_id="BTC-USDC",
        side="BUY",
        size=0.01,
        price=100.0,
        target_movement=0.001,
        target_movement_type="P",
        max_order_replacement=11,
        status="FILLED",
        ownership_provenance=(
            OrderOwnershipProvenance.ADMIN_MANUAL_ROOT
        ),
        retail_portfolio_id=TEST_PORTFOLIO_ID,
        correlation_id=ROOT_CORRELATION_ID,
        audit_id=ROOT_AUDIT_ID,
    )
    order = _order_data()
    order["stealth_order_id"] = child_id
    order["parent_order_id"] = root_id

    try:
        first = order_db.persist_filled_follow_up_atomic(
            order=order,
            target_movement=0.001,
            target_movement_type="P",
        )
        second = order_db.persist_filled_follow_up_atomic(
            order=order,
            target_movement=0.001,
            target_movement_type="P",
        )
        parent_rows = order_db.DB_CLIENT.execute_query(
            "SELECT client_order_id, ownership_provenance, "
            "retail_portfolio_id, correlation_id, audit_id FROM order_parent "
            "WHERE client_order_id = %s",
            (child_id,),
        )
        stealth_rows = order_db.DB_CLIENT.execute_query(
            "SELECT stealth_order_id FROM stealth_orders WHERE stealth_order_id = %s",
            (child_id,),
        )

        assert first[1] is True
        assert second == (first[0], False)
        assert len(parent_rows) == 1
        assert str(parent_rows[0]["client_order_id"]) == child_id
        assert parent_rows[0]["ownership_provenance"] == (
            OrderOwnershipProvenance.ADMIN_FILL_FOLLOW_UP.value
        )
        assert str(parent_rows[0]["retail_portfolio_id"]) == TEST_PORTFOLIO_ID
        assert parent_rows[0]["correlation_id"] == ROOT_CORRELATION_ID
        assert parent_rows[0]["audit_id"] == ROOT_AUDIT_ID
        assert str(stealth_rows[0]["stealth_order_id"]) == child_id
    finally:
        with order_db.DB_CLIENT.get_cursor() as cursor:
            cursor.execute(
                "DELETE FROM stealth_orders WHERE stealth_order_id = %s",
                (child_id,),
            )
            cursor.execute(
                "DELETE FROM order_parent WHERE client_order_id IN (%s, %s)",
                (child_id, root_id),
            )


@pytest.mark.integration
@pytest.mark.serial
def test_direct_root_follow_up_round_trips_profile_and_trace_fields():
    order_db.create_order_parent_table()
    order_db.create_stealth_orders_table()
    root_id = str(uuid.uuid4())
    manager = StealthOrderManager(db_client=order_db.DB_CLIENT)
    order_db.insert_order_parent(
        client_order_id=root_id,
        product_id="BTC-USDC",
        side="BUY",
        size=0.00002,
        price=50000.0,
        target_movement=0.001,
        target_movement_type="P",
        max_order_replacement=11,
        status="FILLED",
        ownership_provenance=(
            OrderOwnershipProvenance.ADMIN_MANUAL_ROOT
        ),
        retail_portfolio_id=TEST_PORTFOLIO_ID,
        correlation_id=ROOT_CORRELATION_ID,
        audit_id=ROOT_AUDIT_ID,
    )

    child_id = manager.create_direct_root_fill_follow_up_stealth_order(
        root_parent_client_order_id=root_id,
        source_client_order_id=root_id,
        product_id="BTC-USDC",
        source_side="BUY",
        side="SELL",
        total_size=0.00002,
        limit_price=50100.0,
        target_movement=0.001,
        target_movement_type="P",
    )

    try:
        rows = order_db.DB_CLIENT.execute_query(
            "SELECT client_order_id, parent_order_id, ownership_provenance, "
            "retail_portfolio_id, correlation_id, audit_id FROM order_parent "
            "WHERE client_order_id = %s",
            (child_id,),
        )
        assert len(rows) == 1
        assert str(rows[0]["client_order_id"]) == child_id
        assert str(rows[0]["parent_order_id"]) == root_id
        assert rows[0]["ownership_provenance"] == (
            OrderOwnershipProvenance.ADMIN_FILL_FOLLOW_UP.value
        )
        assert str(rows[0]["retail_portfolio_id"]) == TEST_PORTFOLIO_ID
        assert rows[0]["correlation_id"] == ROOT_CORRELATION_ID
        assert rows[0]["audit_id"] == ROOT_AUDIT_ID
    finally:
        with order_db.DB_CLIENT.get_cursor() as cursor:
            if child_id:
                cursor.execute(
                    "DELETE FROM stealth_orders WHERE stealth_order_id = %s",
                    (child_id,),
                )
            cursor.execute(
                "DELETE FROM order_parent WHERE client_order_id IN (%s, %s)",
                (child_id, root_id),
            )


@pytest.mark.integration
@pytest.mark.serial
def test_admin_child_standing_block_persists_and_surfaces_in_chain_readback(
    monkeypatch,
):
    import application.admin_api.read_service as read_service
    import configuration

    order_db.create_order_parent_table()
    order_db.create_stealth_orders_table()
    root_id = str(uuid.uuid4())
    child_id = None
    manager = StealthOrderManager(
        db_client=order_db.DB_CLIENT,
        log_callback=MagicMock(),
    )
    manager.expected_retail_portfolio_id = TEST_PORTFOLIO_ID
    manager._dispatch_lifecycle_event = MagicMock()
    order_db.insert_order_parent(
        client_order_id=root_id,
        product_id="BTC-USDC",
        side="BUY",
        size=0.01,
        price=100.0,
        target_movement=0.001,
        target_movement_type="P",
        max_order_replacement=11,
        status="FILLED",
        ownership_provenance=(
            OrderOwnershipProvenance.ADMIN_MANUAL_ROOT
        ),
        retail_portfolio_id=TEST_PORTFOLIO_ID,
        correlation_id=ROOT_CORRELATION_ID,
        audit_id=ROOT_AUDIT_ID,
    )

    try:
        child_id = manager.create_direct_root_fill_follow_up_stealth_order(
            root_parent_client_order_id=root_id,
            source_client_order_id=root_id,
            product_id="BTC-USDC",
            source_side="BUY",
            side="SELL",
            total_size=0.01,
            limit_price=101.0,
            target_movement=0.001,
            target_movement_type="P",
        )
        assert child_id is not None

        manager.profit_validator = None
        manager._calculate_reveal_size = MagicMock(return_value=0.01)
        manager.build_reveal_execution_plan = MagicMock(
            return_value=RevealExecutionPlan(
                configured_limit_price=101.0,
                submitted_limit_price=101.0,
                reveal_pricing_policy="configured_limit",
                reveal_price_source="configured_limit",
                fallback_used=False,
                market_source="ticker",
                market_bid=100.0,
                market_ask=100.1,
                post_only=False,
            )
        )
        manager._evaluate_action_condition_guard = MagicMock(
            return_value=(True, None)
        )
        manager._get_current_market_data = MagicMock(
            return_value={
                "price": 100.05,
                "bid": 100.0,
                "ask": 100.1,
                "volume_1m": 5.0,
                "source": "ticker",
            }
        )
        manager._get_price_increment = MagicMock(return_value=0.01)
        manager.order_placement_hooks = SimpleNamespace(
            call_pre_submission_hooks=MagicMock(),
            call_post_submission_hooks=MagicMock(),
        )
        fake_controller = SimpleNamespace(
            check_admission=MagicMock(),
            track_inflight=lambda _kind: nullcontext(),
        )
        monkeypatch.setattr(
            "core.stealth_order_manager.get_runtime_controller",
            lambda: fake_controller,
        )
        rest_client = SimpleNamespace(place_limit_order=MagicMock())
        monkeypatch.setattr(configuration, "REST_CLIENT", rest_client)
        manager._consume_controlled_admin_child_reveal_authority = MagicMock(
            return_value=(True, None)
        )
        controlled_authority = ControlledAdminChildRevealAuthority(
            stealth_order_id=child_id,
            root_client_order_id=root_id,
            prepared_limit_price=101.0,
            total_size=0.01,
            reference_notional_usdc=1.01,
            market_bid="100.0",
            market_source="ticker",
            market_observed_at=datetime.now(timezone.utc),
            portfolio_id=TEST_PORTFOLIO_ID,
            correlation_id=ROOT_CORRELATION_ID,
            root_audit_id=ROOT_AUDIT_ID,
            authority_id="authority-standing-block",
            approval_snapshot_id="approval-standing-block",
            admission_audit_id="admission-standing-block",
            cap_guard_decision_id="cap-standing-block",
            reconciliation_plan_id="reconciliation-standing-block",
            batch_id="batch-standing-block",
            batch_slot=1,
        )

        assert manager.reveal_order_slice(
            child_id, controlled_admin_authority=controlled_authority
        ) is None
        rest_client.place_limit_order.assert_not_called()

        persisted = order_db.DB_CLIENT.execute_query(
            "SELECT last_lifecycle_event, failure_reason "
            "FROM stealth_orders WHERE stealth_order_id = %s",
            (child_id,),
        )
        assert persisted[0]["last_lifecycle_event"] == "PLACEMENT_BLOCKED"
        assert "standing price authority" in persisted[0]["failure_reason"]

        monkeypatch.setenv(
            "COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID",
            TEST_PORTFOLIO_ID,
        )
        monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_LABEL", "Test")
        monkeypatch.setattr(
            read_service,
            "_runtime_follow_up_claim_state",
            lambda _client_order_id: ("done", "test.claim_state", True),
        )
        monkeypatch.setattr(
            read_service,
            "_runtime_fill_follow_up_execution_adapter_state",
            lambda: (True, "test.execution_adapter"),
        )
        monkeypatch.setattr(
            configuration,
            "rest_get_products",
            lambda: {
                "BTC-USDC": {
                    "product_id": "BTC-USDC",
                    "product_type": "SPOT",
                    "future_product_details": {},
                }
            },
        )

        chain = read_service.AdminApiReadService().build_order_fill_follow_up_chain(
            client_order_id=root_id
        )
        child = next(
            item
            for item in chain.follow_up_children
            if item.client_order_id == child_id
        )
        assert child.ownership_provenance == (
            OrderOwnershipProvenance.ADMIN_FILL_FOLLOW_UP
        )
        assert child.last_lifecycle_event.value == "PLACEMENT_BLOCKED"
        assert "standing price authority" in str(child.failure_reason)
        assert f"follow_up_child_placement_blocked:{child_id}" in chain.blockers
    finally:
        with order_db.DB_CLIENT.get_cursor() as cursor:
            if child_id:
                cursor.execute(
                    "DELETE FROM stealth_orders WHERE stealth_order_id = %s",
                    (child_id,),
                )
            cursor.execute(
                "DELETE FROM order_parent WHERE client_order_id IN (%s, %s)",
                (child_id, root_id),
            )
