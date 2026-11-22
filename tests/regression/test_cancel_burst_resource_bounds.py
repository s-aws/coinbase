"""Regression coverage for cancellation-burst resource boundaries."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
from threading import Lock
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import NAMESPACE_URL, uuid5

import pytest

import dashboard_server
from core.enums import OrderStatus
from tests.unit.test_partial_fill_followups import (
    _build_engine_for_partial_fill_tests,
)


pytestmark = pytest.mark.regression


def _fresh_dashboard_state() -> dict:
    return {
        "orders": {},
        "positions": {},
        "stealth_orders": {},
        "engine_status": {},
        "logs": [],
        "market_metrics": {},
    }


@pytest.fixture
def dashboard_burst_case(monkeypatch):
    client = Mock()
    client.send = AsyncMock()
    client.close = AsyncMock()
    monkeypatch.setattr(dashboard_server, "engine_state", _fresh_dashboard_state())
    monkeypatch.setattr(dashboard_server, "connected_clients", {client})
    monkeypatch.setattr(dashboard_server, "server_event_loop", object())
    monkeypatch.setattr(dashboard_server, "_state_publish_scheduled", False)
    monkeypatch.setattr(dashboard_server, "_state_publish_dirty", False)
    monkeypatch.setattr(dashboard_server, "_ticker_publish_scheduled", False)
    monkeypatch.setattr(dashboard_server, "_pending_ticker_updates", {})
    return client


def test_order_and_log_burst_schedules_one_state_publisher(
    dashboard_burst_case,
    monkeypatch,
):
    scheduled = []

    def capture(coroutine, _loop):
        scheduled.append(coroutine)
        return Mock()

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", capture)

    for index in range(100):
        dashboard_server.update_order(
            f"order-{index}",
            {"status": OrderStatus.CANCELLED.value},
        )
        dashboard_server.add_log_entry("INFO", f"cancelled {index}")

    assert len(scheduled) == 1
    assert dashboard_server._state_publish_scheduled is True
    assert dashboard_server._state_publish_dirty is True
    assert len(dashboard_server.engine_state["orders"]) == 100
    assert len(dashboard_server.engine_state["logs"]) == dashboard_server.max_logs

    scheduled[0].close()


def test_state_mutation_during_send_gets_one_follow_up_snapshot(
    dashboard_burst_case,
    monkeypatch,
):
    calls = 0

    async def broadcast_once():
        nonlocal calls
        calls += 1
        if calls == 1:
            dashboard_server._trigger_broadcast()

    monkeypatch.setattr(dashboard_server, "_async_broadcast_state", broadcast_once)
    monkeypatch.setattr(
        asyncio,
        "run_coroutine_threadsafe",
        Mock(side_effect=AssertionError("a second publisher was scheduled")),
    )
    dashboard_server._state_publish_scheduled = True
    dashboard_server._state_publish_dirty = True

    with asyncio.Runner() as runner:
        runner.run(dashboard_server._drain_state_broadcasts())

    assert calls == 2
    assert dashboard_server._state_publish_scheduled is False
    assert dashboard_server._state_publish_dirty is False


def test_lagging_dashboard_client_is_disconnected_after_send_timeout(
    dashboard_burst_case,
    monkeypatch,
):
    client = dashboard_burst_case
    send_started = asyncio.Event()

    async def stalled_send(_message):
        send_started.set()
        await asyncio.Event().wait()

    client.send.side_effect = stalled_send
    monkeypatch.setattr(
        dashboard_server,
        "_DASHBOARD_CLIENT_SEND_TIMEOUT_SECONDS",
        0.001,
    )

    async def exercise_timeout():
        with pytest.raises(asyncio.TimeoutError):
            await dashboard_server._send_dashboard_message(client, "payload")
        assert send_started.is_set()

    with asyncio.Runner() as runner:
        runner.run(exercise_timeout())

    assert client not in dashboard_server.connected_clients
    client.close.assert_awaited_once_with(
        code=1013,
        reason="Dashboard client could not keep up",
    )


def test_ticker_burst_retains_only_latest_update_per_product(
    dashboard_burst_case,
    monkeypatch,
):
    scheduled = []

    def capture(coroutine, _loop):
        scheduled.append(coroutine)
        return Mock()

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", capture)

    for price in range(1, 101):
        dashboard_server.broadcast_ticker("BTC-USDC", float(price))
        dashboard_server.broadcast_ticker("ETH-USDC", float(price * 2))

    assert len(scheduled) == 1
    assert set(dashboard_server._pending_ticker_updates) == {
        "BTC-USDC",
        "ETH-USDC",
    }
    assert dashboard_server._pending_ticker_updates["BTC-USDC"]["price"] == 100.0
    assert dashboard_server._pending_ticker_updates["ETH-USDC"]["price"] == 200.0

    scheduled[0].close()


def test_spread_samples_use_constant_space_without_dashboard_clients(monkeypatch):
    monkeypatch.setattr(dashboard_server, "spread_data", {})

    for _ in range(100_000):
        dashboard_server.record_spread_tick("BTC-USDC", 100.0, 102.0)

    accumulator = dashboard_server.spread_data["BTC-USDC"]
    assert accumulator["sample_count"] == 100_000
    assert not any(isinstance(value, list) for value in accumulator.values())

    assert dashboard_server._take_spread_snapshot() == [{
        "product_id": "BTC-USDC",
        "bid": 100.0,
        "ask": 102.0,
        "mid": 101.0,
    }]
    assert accumulator["sample_count"] == 0


def test_stealth_snapshot_releases_state_lock_before_parent_lookup(monkeypatch):
    class ObservedLock:
        held = False

        def __enter__(self):
            self.held = True

        def __exit__(self, *_args):
            self.held = False

    observed_lock = ObservedLock()
    client = Mock()
    client.send = AsyncMock()
    monkeypatch.setattr(dashboard_server, "state_lock", observed_lock)
    monkeypatch.setattr(dashboard_server, "engine_state", _fresh_dashboard_state())
    dashboard_server.engine_state["stealth_orders"] = {
        "root-order": {"stealth_order_id": "root-order"},
    }

    def enrich(orders):
        assert observed_lock.held is False
        return orders

    monkeypatch.setattr(
        dashboard_server,
        "_enrich_stealth_orders_with_parent_data",
        enrich,
    )

    with asyncio.Runner() as runner:
        runner.run(dashboard_server.send_stealth_orders_snapshot(client))

    client.send.assert_awaited_once()


def test_stealth_parent_enrichment_uses_one_bulk_query(monkeypatch):
    from database import order as order_database

    bulk_lookup = Mock(return_value=[{
        "client_order_id": "root-order",
        "target_movement": 0.01,
        "target_movement_type": "P",
        "max_order_replacement": 5,
    }])
    monkeypatch.setattr(
        order_database,
        "get_parent_orders_by_client_ids",
        bulk_lookup,
    )
    orders = {
        f"child-{index}": {
            "stealth_order_id": f"child-{index}",
            "parent_order_id": "root-order",
        }
        for index in range(100)
    }

    enriched = dashboard_server._enrich_stealth_orders_with_parent_data(orders)

    bulk_lookup.assert_called_once()
    assert len(bulk_lookup.call_args.args[0]) == 1
    assert all(
        order["parent_max_order_replacements"] == 5
        for order in enriched.values()
    )


def test_bulk_parent_lookup_deduplicates_ids_and_uses_one_database_query(monkeypatch):
    from database import order as order_database

    execute_query = Mock(return_value=[])
    monkeypatch.setattr(order_database.DB_CLIENT, "execute_query", execute_query)

    assert order_database.get_parent_orders_by_client_ids([
        "root-a",
        "root-a",
        "root-b",
        "",
    ]) == []

    execute_query.assert_called_once_with(
        "SELECT * FROM order_parent WHERE client_order_id = ANY(%s)",
        (["root-a", "root-b"],),
    )


def test_dashboard_retains_active_orders_and_bounds_terminal_history(monkeypatch):
    monkeypatch.setattr(dashboard_server, "engine_state", _fresh_dashboard_state())
    monkeypatch.setattr(dashboard_server, "connected_clients", set())

    terminal_count = dashboard_server._MAX_TERMINAL_DASHBOARD_ORDERS + 100
    for index in range(terminal_count):
        dashboard_server.update_order(
            f"terminal-{index}",
            {"status": OrderStatus.CANCELLED.value},
        )
    dashboard_server.update_order(
        "still-open",
        {"status": OrderStatus.OPEN.value},
    )

    orders = dashboard_server.engine_state["orders"]
    terminal_orders = [
        order
        for order in orders.values()
        if order["status"] == OrderStatus.CANCELLED.value
    ]
    assert len(terminal_orders) == dashboard_server._MAX_TERMINAL_DASHBOARD_ORDERS
    assert "terminal-0" not in orders
    assert "still-open" in orders


def test_duplicate_delivery_of_100_cancellations_creates_one_follow_up_per_root():
    """Replay the historical three-socket cancellation fanout in one burst."""

    engine = _build_engine_for_partial_fill_tests()
    engine.logging_flags = {
        log_type: False for log_type in engine.logging_flags
    }

    placements = []
    placement_to_root = {}
    stealth_records = {}
    for index in range(100):
        placement = str(uuid5(NAMESPACE_URL, f"cancel-placement-{index}"))
        root = str(uuid5(NAMESPACE_URL, f"cancel-root-{index}"))
        placements.append(placement)
        placement_to_root[placement] = root
        stealth_records[placement] = {
            "stealth_order_id": root,
            "product_id": "BIP-20DEC30-CDE",
            "side": "SELL",
            "parent_order_id": None,
        }
        engine.orderbook.child_order_ids[placement] = root
        engine.orderbook.parent_order_ids[root] = {
            "allow_partial_fills": False,
            "orders": [placement],
            "target_movement": {"movement": 0.001, "type": "P"},
            "max_order_replacement": 1,
            "current_order_replacement": 0,
            "externally_created": False,
        }

    engine.orderbook.should_replace = {"FILLED": True, "CANCELLED": True}
    engine.compute_order_template = Mock(return_value={
        "product_id": "BIP-20DEC30-CDE",
        "side": "SELL",
        "order_base_size": 1.0,
        "start_price": 100.0,
    })
    engine.child_order_already_exists = Mock(return_value=False)
    engine.resolve_parent_client_order_id = Mock(
        side_effect=lambda placement: (
            placement_to_root[placement],
            placement_to_root[placement],
        )
    )

    creation_counts = {}
    creation_lock = Lock()

    def create_follow_up_stealth_order(**kwargs):
        root = kwargs["original_stealth_order_id"]
        with creation_lock:
            creation_counts[root] = creation_counts.get(root, 0) + 1
        return str(uuid5(NAMESPACE_URL, f"cancel-follow-up-{root}"))

    manager = SimpleNamespace(
        find_stealth_order_by_placed_order_id=stealth_records.get,
    )
    engine.stealth_order_bridge = SimpleNamespace(
        stealth_manager=manager,
        update_execution=lambda **_kwargs: True,
        create_follow_up_stealth_order=create_follow_up_stealth_order,
    )

    cancelled_rows = [
        {
            "client_order_id": placement,
            "product_id": "BIP-20DEC30-CDE",
            "side": "SELL",
            "status": OrderStatus.CANCELLED.value,
            "price": 100.0,
        }
        for _duplicate_delivery in range(3)
        for placement in placements
    ]

    with patch("database.order.has_pending_move", return_value=False), patch(
        "database.order.get_parent_order",
        return_value={
            "target_movement": 0.001,
            "target_movement_type": "P",
        },
    ), patch(
        "database.order.increment_order_parent_replacement_count",
        return_value=1,
    ):
        with ThreadPoolExecutor(max_workers=16) as executor:
            list(executor.map(engine.handle_cancelled_order, cancelled_rows))

    assert len(creation_counts) == 100
    assert set(creation_counts.values()) == {1}
    assert engine._pending_replacement_claims == {}
    assert all(
        parent["current_order_replacement"] == 1
        for parent in engine.orderbook.parent_order_ids.values()
    )


def test_linux_cancel_stress_harness_reports_quiescent_bounded_state():
    project_root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts" / "stress_cancel_burst.py"),
            "--orders-per-batch",
            "100",
            "--batches",
            "2",
            "--idle-window-seconds",
            "0.05",
        ],
        cwd=project_root,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    report = json.loads(completed.stdout)
    assert report["status"] == "pass"
    assert report["measurements"]["pending_asyncio_tasks"] == 0
    assert report["measurements"]["publisher_scheduled"] is False
    assert report["measurements"]["retained_orders"] == 1_000


def test_linux_cancel_pipeline_stress_releases_per_order_runtime_state():
    project_root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts" / "stress_cancel_pipeline.py"),
            "--orders-per-batch",
            "5",
            "--batches",
            "2",
            "--warmup-orders",
            "4",
            "--idle-window-seconds",
            "0.05",
        ],
        cwd=project_root,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    report = json.loads(completed.stdout)
    assert report["status"] == "pass"
    measurements = report["measurements"]
    assert measurements["user_feed_phase"] == "live"
    assert measurements["retained_parent_entries"] == 0
    assert measurements["retained_follow_up_claims"] == 0
    assert measurements["retained_coid_locks"] == 0
    assert measurements["dispatcher_pending"] == 0
