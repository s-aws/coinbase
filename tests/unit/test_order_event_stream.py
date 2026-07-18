"""Focused tests for OrderEventStreamPublisher stealth lifecycle auditing."""

from datetime import datetime

from business.order_event_stream import OrderEventStreamPublisher
from core.enums import StealthLifecycleEvent


class FakeDBModule:
    def __init__(self):
        self.created_event_stream_table = False
        self.created_lifecycle_history_table = False
        self.created_reveal_history_table = False
        self.created_snapshots_table = False
        self.created_partial_fill_progress_table = False
        self.inserted_events = []

    def create_order_event_stream_table(self):
        self.created_event_stream_table = True

    def create_stealth_order_lifecycle_history_table(self):
        self.created_lifecycle_history_table = True

    def create_stealth_order_reveal_history_table(self):
        self.created_reveal_history_table = True

    def create_stealth_order_snapshots_table(self):
        self.created_snapshots_table = True

    def create_partial_fill_progress_table(self):
        self.created_partial_fill_progress_table = True

    def insert_order_event(self, **kwargs):
        self.inserted_events.append(kwargs)
        return 1


def test_initialize_table_creates_lifecycle_history_table():
    db_module = FakeDBModule()

    publisher = OrderEventStreamPublisher(db_module)

    assert publisher.enabled is True
    assert db_module.created_event_stream_table is True
    assert db_module.created_lifecycle_history_table is True
    assert db_module.created_reveal_history_table is True
    assert db_module.created_snapshots_table is True


def test_stealth_lifecycle_hook_writes_history_and_updates_latest(monkeypatch):
    db_module = FakeDBModule()
    publisher = OrderEventStreamPublisher(db_module)

    captured = {
        "history": None,
        "snapshot": None,
        "latest": None,
    }

    def fake_insert_stealth_order_lifecycle_event(stealth_order_id, lifecycle_event, context):
        captured["history"] = {
            "stealth_order_id": stealth_order_id,
            "lifecycle_event": lifecycle_event,
            "context": context,
        }
        return 42

    def fake_update_stealth_order_lifecycle_event(stealth_order_id, lifecycle_event, failure_reason=None):
        captured["latest"] = {
            "stealth_order_id": stealth_order_id,
            "lifecycle_event": lifecycle_event,
            "failure_reason": failure_reason,
        }
        return True

    def fake_insert_stealth_order_snapshot(stealth_order_id, lifecycle_event, context):
        captured["snapshot"] = {
            "stealth_order_id": stealth_order_id,
            "lifecycle_event": lifecycle_event,
            "context": context,
        }
        return 77

    monkeypatch.setattr(
        "database.order.insert_stealth_order_lifecycle_event",
        fake_insert_stealth_order_lifecycle_event,
    )
    monkeypatch.setattr(
        "database.order.update_stealth_order_lifecycle_event",
        fake_update_stealth_order_lifecycle_event,
    )
    monkeypatch.setattr(
        "database.order.insert_stealth_order_snapshot",
        fake_insert_stealth_order_snapshot,
    )

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

    assert len(db_module.inserted_events) == 1
    assert db_module.inserted_events[0]["event_type"] == "stealth_condition_met"
    assert db_module.inserted_events[0]["raw_payload_json"]["lifecycle_event"] == "CONDITION_MET"

    assert captured["history"] is not None
    assert captured["history"]["stealth_order_id"] == "550e8400-e29b-41d4-a716-446655440000"
    assert captured["history"]["lifecycle_event"] == "CONDITION_MET"
    assert captured["history"]["context"]["status"] == "TRIGGERED"
    assert captured["history"]["context"]["exchange_order_id"] == "exchange-oid-123"

    assert captured["snapshot"] is not None
    assert captured["snapshot"]["lifecycle_event"] == "CONDITION_MET"
    assert captured["snapshot"]["context"]["status"] == "TRIGGERED"

    assert captured["latest"] is not None
    assert captured["latest"]["lifecycle_event"] == "CONDITION_MET"
    assert captured["latest"]["failure_reason"] is None


def test_stealth_lifecycle_hook_skips_snapshot_for_created(monkeypatch):
    db_module = FakeDBModule()
    publisher = OrderEventStreamPublisher(db_module)

    called = {"snapshot": 0}

    monkeypatch.setattr(
        "database.order.insert_stealth_order_lifecycle_event",
        lambda stealth_order_id, lifecycle_event, context: 1,
    )
    monkeypatch.setattr(
        "database.order.update_stealth_order_lifecycle_event",
        lambda stealth_order_id, lifecycle_event, failure_reason=None: True,
    )
    monkeypatch.setattr(
        "database.order.insert_stealth_order_snapshot",
        lambda stealth_order_id, lifecycle_event, context: called.__setitem__("snapshot", called["snapshot"] + 1),
    )

    publisher._stealth_lifecycle_hook(
        "550e8400-e29b-41d4-a716-446655440000",
        StealthLifecycleEvent.CREATED,
        {"status": "HIDDEN", "timestamp": datetime(2026, 4, 25, 6, 30, 0)},
    )

    assert called["snapshot"] == 0


def test_publish_event_enriches_payload_with_fee_manager_audit():
    db_module = FakeDBModule()
    publisher = OrderEventStreamPublisher(db_module)

    publisher.set_fee_info_provider(
        lambda product_id=None: {
            "taker_fee_rate": 0.006,
            "profit_validation_fee_rate": 0.012,
            "target_movement_factor": 1.1,
            "fee_regime_factor": 1.2,
            "volume_ratio": 0.75,
            "overnight_margin_active": False,
            "margin_window_type": "INTRADAY",
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
            "trigger_payload": {"reason": "unit_test"},
        },
        idempotency_key="ws:OPEN:cid-1:OPEN",
        status_to="OPEN",
    )

    assert ok is True
    assert len(db_module.inserted_events) == 1

    inserted = db_module.inserted_events[0]
    fee_audit = inserted["raw_payload_json"].get("fee_manager_audit")
    assert fee_audit is not None
    assert fee_audit["product_id"] == "BTC-USDC"
    assert fee_audit["taker_fee_rate"] == 0.006
    assert fee_audit["margin_window_type"] == "INTRADAY"
    assert inserted["trigger_payload_json"]["fee_manager_audit"]["fee_regime_factor"] == 1.2


def test_publish_event_value_blinds_database_exception_log(monkeypatch):
    private_marker = "PRIVATE-EVENT-PUBLISH-DB-MARKER"
    warnings = []
    db_module = FakeDBModule()
    publisher = OrderEventStreamPublisher(db_module)

    def fail_insert(**_kwargs):
        raise RuntimeError(private_marker)

    db_module.insert_order_event = fail_insert
    monkeypatch.setattr(
        "business.order_event_stream.logger.warning",
        warnings.append,
    )

    ok = publisher.publish_event(
        event_type="order_submitted",
        source_channel="rest_submit",
        payload={"client_order_id": "client-order-id"},
        idempotency_key="submit:client-order-id",
    )

    assert ok is False
    assert warnings
    assert private_marker not in " ".join(warnings)
    assert "exception_class:RuntimeError" in " ".join(warnings)


def test_lifecycle_persistence_exception_logs_are_value_blind(monkeypatch):
    private_marker = "PRIVATE-EVENT-LIFECYCLE-DB-MARKER"
    warnings = []
    publisher = OrderEventStreamPublisher(FakeDBModule())

    def fail_write(**_kwargs):
        raise RuntimeError(private_marker)

    monkeypatch.setattr(
        "database.order.insert_stealth_order_lifecycle_event",
        fail_write,
    )
    monkeypatch.setattr(
        "database.order.insert_stealth_order_snapshot",
        fail_write,
    )
    monkeypatch.setattr(
        "database.order.update_stealth_order_lifecycle_event",
        fail_write,
    )
    monkeypatch.setattr(
        "business.order_event_stream.logger.warning",
        warnings.append,
    )

    publisher._stealth_lifecycle_hook(
        "stealth-order-id",
        StealthLifecycleEvent.CONDITION_MET,
        {"status": "TRIGGERED"},
    )

    assert len(warnings) == 3
    assert private_marker not in " ".join(warnings)
    assert all("exception_class:RuntimeError" in warning for warning in warnings)
