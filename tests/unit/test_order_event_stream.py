"""Focused tests for OrderEventStreamPublisher stealth lifecycle auditing."""

from datetime import datetime

import pytest

from business.order_event_stream import OrderEventStreamPublisher
from core.enums import StealthLifecycleEvent


class FakeEventStreamPersistence:
    def __init__(self):
        self.created_event_stream_table = False
        self.created_lifecycle_history_table = False
        self.created_reveal_history_table = False
        self.created_snapshots_table = False
        self.created_partial_fill_progress_table = False
        self.inserted_events = []
        self.inserted_lifecycle_events = []
        self.inserted_snapshots = []
        self.updated_lifecycle_markers = []

    def ensure_event_stream_storage(self):
        self.created_event_stream_table = True
        self.created_lifecycle_history_table = True
        self.created_reveal_history_table = True
        self.created_snapshots_table = True
        self.created_partial_fill_progress_table = True

    def append_order_event(self, **kwargs):
        self.inserted_events.append(kwargs)
        return 1

    def append_stealth_lifecycle_event(self, **kwargs):
        self.inserted_lifecycle_events.append(kwargs)
        return 42

    def append_stealth_snapshot(self, **kwargs):
        self.inserted_snapshots.append(kwargs)
        return 77

    def update_stealth_lifecycle_marker(self, **kwargs):
        self.updated_lifecycle_markers.append(kwargs)
        return True


def test_initialize_table_creates_lifecycle_history_table():
    persistence = FakeEventStreamPersistence()

    publisher = OrderEventStreamPublisher(persistence)

    assert publisher.enabled is True
    assert persistence.created_event_stream_table is True
    assert persistence.created_lifecycle_history_table is True
    assert persistence.created_reveal_history_table is True
    assert persistence.created_snapshots_table is True
    assert persistence.created_partial_fill_progress_table is True


def test_initialize_table_failure_disables_event_stream():
    class FailingInitialization(FakeEventStreamPersistence):
        def ensure_event_stream_storage(self):
            raise RuntimeError("schema unavailable")

    publisher = OrderEventStreamPublisher(FailingInitialization())

    assert publisher.enabled is False


def test_publish_event_preserves_duplicate_and_error_as_false():
    class DuplicatePersistence(FakeEventStreamPersistence):
        def append_order_event(self, **kwargs):
            return None

    duplicate_publisher = OrderEventStreamPublisher(DuplicatePersistence())
    assert duplicate_publisher.publish_event(
        event_type="order_open",
        source_channel="ws_user",
        payload={"client_order_id": "cid-duplicate"},
        idempotency_key="duplicate-key",
    ) is False

    class FailingPersistence(FakeEventStreamPersistence):
        def append_order_event(self, **kwargs):
            raise RuntimeError("database unavailable")

    failing_publisher = OrderEventStreamPublisher(FailingPersistence())
    assert failing_publisher.publish_event(
        event_type="order_open",
        source_channel="ws_user",
        payload={"client_order_id": "cid-error"},
        idempotency_key="error-key",
    ) is False


def test_lifecycle_audit_writes_remain_independent_and_fail_soft():
    class FailingAuditPersistence(FakeEventStreamPersistence):
        def __init__(self):
            super().__init__()
            self.attempts = []

        def append_order_event(self, **kwargs):
            self.attempts.append("event")
            raise RuntimeError("event failed")

        def append_stealth_lifecycle_event(self, **kwargs):
            self.attempts.append("history")
            raise RuntimeError("history failed")

        def append_stealth_snapshot(self, **kwargs):
            self.attempts.append("snapshot")
            raise RuntimeError("snapshot failed")

        def update_stealth_lifecycle_marker(self, **kwargs):
            self.attempts.append("marker")
            raise RuntimeError("marker failed")

    persistence = FailingAuditPersistence()
    publisher = OrderEventStreamPublisher(persistence)

    publisher._stealth_lifecycle_hook(
        "550e8400-e29b-41d4-a716-446655440000",
        StealthLifecycleEvent.CONDITION_MET,
        {"status": "TRIGGERED", "timestamp": datetime(2026, 11, 28, 12, 0)},
    )

    assert persistence.attempts == ["event", "history", "snapshot", "marker"]


def test_stealth_lifecycle_hook_writes_history_and_updates_latest():
    persistence = FakeEventStreamPersistence()
    publisher = OrderEventStreamPublisher(persistence)

    context = {
        "product_id": "BTC-USDC",
        "side": "BUY",
        "size": 0.5,
        "total_size": 1.0,
        "limit_price": 50000.0,
        "reason": "normal_placement",
        "status": "TRIGGERED",
        "reveal_condition_type": "price",
        "reveal_condition": {"type": "price", "direction": "below", "price_threshold": 50000.0},
        "timestamp": datetime(2026, 4, 25, 6, 30, 0),
        "placed_order_id": "oid-123",
        "exchange_order_id": "exchange-oid-123",
        "failure_reason": None,
    }

    publisher._stealth_lifecycle_hook(
        "550e8400-e29b-41d4-a716-446655440000",
        StealthLifecycleEvent.CONDITION_MET,
        context,
    )

    assert len(persistence.inserted_events) == 1
    assert persistence.inserted_events[0]["event_type"] == "stealth_condition_met"
    assert persistence.inserted_events[0]["raw_payload_json"]["lifecycle_event"] == "CONDITION_MET"

    history = persistence.inserted_lifecycle_events[0]
    assert history["stealth_order_id"] == "550e8400-e29b-41d4-a716-446655440000"
    assert history["lifecycle_event"] == "CONDITION_MET"
    assert history["context"]["status"] == "TRIGGERED"
    assert history["context"]["exchange_order_id"] == "exchange-oid-123"

    snapshot = persistence.inserted_snapshots[0]
    assert snapshot["lifecycle_event"] == "CONDITION_MET"
    assert snapshot["context"]["status"] == "TRIGGERED"

    latest = persistence.updated_lifecycle_markers[0]
    assert latest["lifecycle_event"] == "CONDITION_MET"
    assert latest["failure_reason"] is None


def test_stealth_lifecycle_hook_skips_snapshot_for_created():
    persistence = FakeEventStreamPersistence()
    publisher = OrderEventStreamPublisher(persistence)

    publisher._stealth_lifecycle_hook(
        "550e8400-e29b-41d4-a716-446655440000",
        StealthLifecycleEvent.CREATED,
        {"status": "HIDDEN", "timestamp": datetime(2026, 4, 25, 6, 30, 0)},
    )

    assert persistence.inserted_snapshots == []


def test_condition_reset_writes_a_state_snapshot():
    persistence = FakeEventStreamPersistence()
    publisher = OrderEventStreamPublisher(persistence)

    publisher._stealth_lifecycle_hook(
        "550e8400-e29b-41d4-a716-446655440000",
        StealthLifecycleEvent.CONDITION_RESET,
        {
            "status": "HIDDEN",
            "timestamp": datetime(2026, 8, 27, 12, 0, 0),
        },
    )

    assert len(persistence.inserted_snapshots) == 1
    snapshot = persistence.inserted_snapshots[0]
    assert snapshot["lifecycle_event"] == "CONDITION_RESET"
    assert snapshot["context"]["status"] == "HIDDEN"


def test_publish_event_enriches_payload_with_fee_manager_audit():
    persistence = FakeEventStreamPersistence()
    publisher = OrderEventStreamPublisher(persistence)

    publisher.set_fee_info_provider(
        lambda product_id=None: {
            "product_type": "SPOT",
            "product_venue": "CBE",
            "taker_fee_rate": 0.006,
            "maker_fee_rate": 0.004,
            "profit_validation_fee_rate": 0.012,
            "profit_validation_fee_rate_taker": 0.012,
            "profit_validation_fee_rate_maker": 0.008,
            "target_movement_factor": 1.1,
            "fee_regime_factor": 1.2,
            "fee_validation_factor": 1.2,
            "volume_ratio": 0.75,
            "overnight_margin_active": False,
            "margin_window_type": "INTRADAY",
            "pricing_tier": "Advanced 8",
            "fee_schedule_source": "coinbase",
            "last_updated": "2026-04-25T06:30:00",
            "is_stale": False,
            "product_echo": product_id,
        }
    )

    ok = publisher.publish_event(
        event_type="order_open",
        source_channel="ws_user",
        payload={
            "client_order_id": "cid-1",
            "product_id": "BTC-USDC",
            "post_only": True,
            "trigger_payload": {"reason": "unit_test"},
        },
        idempotency_key="ws:OPEN:cid-1:OPEN",
        status_to="OPEN",
    )

    assert ok is True
    assert len(persistence.inserted_events) == 1

    inserted = persistence.inserted_events[0]
    fee_audit = inserted["raw_payload_json"].get("fee_manager_audit")
    assert fee_audit is not None
    assert fee_audit["product_id"] == "BTC-USDC"
    assert fee_audit["taker_fee_rate"] == 0.006
    assert fee_audit["maker_fee_rate"] == 0.004
    assert fee_audit["selected_exchange_fee_rate"] == 0.004
    assert fee_audit["selected_profit_validation_fee_rate"] == 0.008
    assert fee_audit["liquidity_assumption"] == "maker"
    assert fee_audit["fee_schedule_source"] == "coinbase"
    assert fee_audit["margin_window_type"] == "INTRADAY"
    assert inserted["trigger_payload_json"]["fee_manager_audit"]["fee_regime_factor"] == 1.2


@pytest.mark.parametrize(
    ("post_only", "expected_liquidity", "expected_rate"),
    [
        (True, "maker", 0.004),
        ("true", "maker", 0.004),
        (" TRUE ", "maker", 0.004),
        (False, "taker", 0.006),
        ("false", "taker", 0.006),
        (None, "taker", 0.006),
        ("not-a-boolean", "taker", 0.006),
    ],
)
def test_fee_audit_parses_local_and_websocket_post_only_values(
    post_only,
    expected_liquidity,
    expected_rate,
):
    publisher = OrderEventStreamPublisher(FakeEventStreamPersistence())
    publisher.set_fee_info_provider(
        lambda product_id=None: {
            "product_type": "SPOT",
            "product_venue": "CBE",
            "taker_fee_rate": 0.006,
            "maker_fee_rate": 0.004,
            "profit_validation_fee_rate_taker": 0.006,
            "profit_validation_fee_rate_maker": 0.004,
        }
    )

    audit = publisher._build_fee_manager_audit_context({
        "product_id": "BTC-USDC",
        "post_only": post_only,
    })

    assert audit["liquidity_assumption"] == expected_liquidity
    assert audit["selected_exchange_fee_rate"] == expected_rate
    assert audit["selected_profit_validation_fee_rate"] == expected_rate


def test_post_submission_hook_publishes_only_explicitly_accepted_placement():
    persistence = FakeEventStreamPersistence()
    publisher = OrderEventStreamPublisher(persistence)
    order = {
        "client_order_id": "placement-cid-1",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "price": 50000.0,
        "size": 0.1,
    }

    publisher._post_submission_hook(
        order,
        {
            "success": True,
            "success_response": {
                "order_id": "exchange-order-1",
                "client_order_id": "placement-cid-1",
            },
        },
    )

    assert len(persistence.inserted_events) == 1
    inserted = persistence.inserted_events[0]
    assert inserted["event_type"] == "order_submitted"
    assert inserted["client_order_id"] == "placement-cid-1"
    assert inserted["order_id"] == "exchange-order-1"


@pytest.mark.parametrize(
    "result",
    [
        {
            "success": False,
            "error_response": {"message": "invalid price increment"},
        },
        {"success": True, "success_response": {}},
        {
            "success": True,
            "success_response": {
                "order_id": "exchange-order-2",
                "client_order_id": "different-client-id",
            },
        },
        {"success_response": {"order_id": "exchange-order-3"}},
    ],
)
def test_post_submission_hook_does_not_publish_unaccepted_placement(result):
    persistence = FakeEventStreamPersistence()
    publisher = OrderEventStreamPublisher(persistence)

    publisher._post_submission_hook(
        {
            "client_order_id": "expected-client-id",
            "product_id": "BTC-USDC",
        },
        result,
    )

    assert persistence.inserted_events == []
