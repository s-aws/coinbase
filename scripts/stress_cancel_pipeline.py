#!/usr/bin/env python3
"""Stress the exchange-free user-channel cancellation pipeline on Linux.

The workload traverses the authenticated envelope reducer, keyed dispatcher,
order engine, isolated PostgreSQL test database, and dashboard publisher.  It
never opens a Coinbase client and refuses the production PostgreSQL port.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import redirect_stdout
import gc
import io
import json
import os
from pathlib import Path
import sys
import threading
import time
import tracemalloc
from types import ModuleType, SimpleNamespace
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
MIB = 1024 * 1024


def _configure_isolated_database() -> None:
    host = os.environ.get("COINBASE_TEST_DB_HOST", "127.0.0.1")
    port = os.environ.get("COINBASE_TEST_DB_PORT", "9876")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError(f"refusing non-loopback test database host: {host}")
    if port == "5432":
        raise RuntimeError("refusing production PostgreSQL port 5432")

    os.environ["COINBASE_DB_HOST"] = host
    os.environ["COINBASE_DB_PORT"] = port
    os.environ["COINBASE_DB_NAME"] = os.environ.get(
        "COINBASE_TEST_DB_NAME",
        "postgres",
    )
    os.environ["COINBASE_DB_USER"] = os.environ.get(
        "COINBASE_TEST_DB_USER",
        "postgres",
    )
    os.environ["COINBASE_DB_PASSWORD"] = os.environ.get(
        "COINBASE_TEST_DB_PASSWORD",
        "postgres",
    )


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _install_offline_configuration() -> None:
    """Install only the configuration surface imported by the pipeline."""

    product = {
        "product_id": "BTC-USDC",
        "product_type": "SPOT",
        "base_increment": "0.00000001",
        "quote_increment": "0.01",
    }
    offline = ModuleType("configuration")
    offline.DEFAULT_MAX_ORDER_REPLACEMENT = 0
    offline.REST_CLIENT = None
    offline.apply_calculated_position_update = lambda *_args, **_kwargs: None
    offline.calculate_new_order_move_from_snapshot = lambda *_args, **_kwargs: {}
    offline.determine_open_close_sides = lambda *_args, **_kwargs: ("BUY", "SELL")
    offline.get_futures_positions = lambda: {}
    offline.get_product_metadata = (
        lambda product_id: product if product_id == "BTC-USDC" else None
    )
    offline.get_trading_product_id = lambda product_id: product_id
    offline.normalize_product_type = lambda *_args, **_kwargs: "SPOT"
    offline.rest_get_products = lambda: {}
    offline.safe_float = _safe_float
    offline.update_product_metadata = lambda _metadata: None
    sys.modules["configuration"] = offline


_configure_isolated_database()
_install_offline_configuration()

import dashboard_server  # noqa: E402
from core.enums import (  # noqa: E402
    ChannelType,
    OrderStatus,
    UserFeedPhase,
    WebSocketEventType,
)
from core.order_engine import OrderEngine  # noqa: E402
from core.orderbook import OrderBook as CoreOrderBook  # noqa: E402
from database import order as order_database  # noqa: E402
from database.schema import initialize_database_schema  # noqa: E402
from integration.websocket_hooks import WebSocketHookRegistry  # noqa: E402
from scripts.stress_cancel_burst import (  # noqa: E402
    FastDashboardClient,
    _current_rss_bytes,
    _fresh_dashboard_state,
    _open_fd_count,
    _positive_float,
    _positive_int,
    _wait_for_publisher,
)


class PipelineOrderBook(CoreOrderBook):
    """Expose the legacy live-dict surface consumed by OrderEngine."""

    def __init__(self) -> None:
        super().__init__(
            products={
                "BTC-USDC": {
                    "product_id": "BTC-USDC",
                    "product_type": "SPOT",
                    "base_increment": "0.00000001",
                    "quote_increment": "0.01",
                },
            },
            profit={
                "SPOT": {"BUY": 0.004, "SELL": 0.004},
                "FUTURE": {"BUY": 0.0012, "SELL": 0.0012},
            },
            should_replace={"FILLED": True, "CANCELLED": True},
            db_module=order_database,
        )
        self.default_max_order_replacement = 0

    @property
    def order(self):
        return self._orders

    @property
    def parent_order_ids(self):
        return self._parents

    @property
    def child_order_ids(self):
        return self._child_to_parent

    @property
    def positions(self):
        return self._positions

    @property
    def product(self):
        return self._products

    @property
    def db_module(self):
        return self._db_module

    @db_module.setter
    def db_module(self, value):
        self._db_module = value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stress user-channel cancellation processing on the test DB.",
    )
    parser.add_argument("--orders-per-batch", type=_positive_int, default=100)
    parser.add_argument("--batches", type=_positive_int, default=3)
    parser.add_argument("--warmup-orders", type=_positive_int, default=16)
    parser.add_argument("--settle-timeout-seconds", type=_positive_float, default=30.0)
    parser.add_argument("--idle-window-seconds", type=_positive_float, default=0.5)
    parser.add_argument("--max-wall-seconds", type=_positive_float, default=60.0)
    parser.add_argument("--max-cpu-seconds", type=_positive_float, default=45.0)
    parser.add_argument("--max-idle-cpu-seconds", type=_positive_float, default=0.05)
    parser.add_argument("--max-rss-growth-mib", type=_positive_float, default=64.0)
    parser.add_argument("--max-traced-growth-mib", type=_positive_float, default=24.0)
    return parser


def _make_cancelled_order(run_id: str, batch: int, index: int) -> dict[str, Any]:
    client_order_id = str(
        uuid5(NAMESPACE_URL, f"cancel-pipeline:{run_id}:{batch}:{index}")
    )
    return {
        "client_order_id": client_order_id,
        "order_id": str(
            uuid5(NAMESPACE_URL, f"cancel-pipeline-exchange:{run_id}:{batch}:{index}")
        ),
        "product_id": "BTC-USDC",
        "product_type": "SPOT",
        "status": OrderStatus.CANCELLED.value,
        "order_side": "BUY",
        "side": "BUY",
        "cumulative_quantity": "0",
        "leaves_quantity": "0",
        "filled_value": "0",
        "total_fees": "0",
        "number_of_fills": "0",
        "completion_percentage": "0",
        "outstanding_hold_amount": "0",
        "base_size": "1",
        "limit_price": "100.00",
    }


def _feed_envelope(
    engine: OrderEngine,
    *,
    generation: int,
    sequence_num: int,
    event: dict[str, Any],
) -> None:
    engine.on_user_message(
        json.dumps({
            "channel": ChannelType.USER.value,
            "sequence_num": sequence_num,
            "timestamp": "2026-11-22T12:00:00Z",
            "events": [event],
        }),
        generation=generation,
    )
    envelope = engine.event_queue[ChannelType.USER.value].get_nowait()
    try:
        engine.process_private_envelope(envelope)
    finally:
        engine.event_queue[ChannelType.USER.value].task_done()


async def _wait_for_engine_quiescence(
    engine: OrderEngine,
    timeout_seconds: float,
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while True:
        dispatcher = engine._user_order_dispatcher
        with dispatcher._lock:
            pending = dispatcher._pending_count
            queue_count = len(dispatcher._queues)
            active_count = len(dispatcher._active_keys)
        if pending == 0 and queue_count == 0 and active_count == 0:
            break
        if engine._user_feed_phase == UserFeedPhase.DESYNCHRONIZED:
            raise RuntimeError("user feed desynchronized during stress workload")
        if loop.time() >= deadline:
            raise TimeoutError("order pipeline did not quiesce")
        await asyncio.sleep(0.005)
    await _wait_for_publisher(timeout_seconds)


async def _run_batch(
    engine: OrderEngine,
    *,
    generation: int,
    sequence_num: int,
    run_id: str,
    batch: int,
    order_count: int,
    generated_ids: list[str],
    timeout_seconds: float,
) -> None:
    orders = [
        _make_cancelled_order(run_id, batch, index)
        for index in range(order_count)
    ]
    generated_ids.extend(order["client_order_id"] for order in orders)
    _feed_envelope(
        engine,
        generation=generation,
        sequence_num=sequence_num,
        event={
            "type": WebSocketEventType.PATCH.value,
            "orders": orders,
        },
    )
    await _wait_for_engine_quiescence(engine, timeout_seconds)


def _database_counts(client_order_ids: list[str]) -> dict[str, int]:
    def count(table: str, extra: str = "") -> int:
        rows = order_database.DB_CLIENT.execute_query(
            f"SELECT COUNT(*) AS count FROM {table} "
            f"WHERE client_order_id = ANY(%s) {extra}",
            (client_order_ids,),
        )
        return int(rows[0]["count"])

    return {
        "order_parent": count("order_parent"),
        "external_order_parent": count(
            "order_parent",
            "AND externally_created IS TRUE",
        ),
        "order_match_audit": count("order_match_audit"),
        "partial_fill_progress": count("partial_fill_progress"),
        "order_event_stream": count("order_event_stream"),
    }


def _cleanup_database(client_order_ids: list[str]) -> None:
    if not client_order_ids:
        return
    params = (client_order_ids,)
    for table in (
        "order_match_audit",
        "order_event_stream",
        "fill_ledger",
        "partial_fill_progress",
        "order_parent",
    ):
        order_database.DB_CLIENT.execute_update(
            f"DELETE FROM {table} WHERE client_order_id = ANY(%s)",
            params,
        )


async def _run_stress(args: argparse.Namespace) -> dict[str, Any]:
    initialize_database_schema()

    client = FastDashboardClient()
    dashboard_server.engine_state = _fresh_dashboard_state()
    dashboard_server.connected_clients = {client}
    dashboard_server.server_event_loop = asyncio.get_running_loop()
    dashboard_server._state_publish_scheduled = False
    dashboard_server._state_publish_dirty = False

    orderbook = PipelineOrderBook()
    subscription = SimpleNamespace(
        channels=(ChannelType.USER.value,),
        private_channels=(ChannelType.USER.value,),
        public_channels=(),
        product_ids=("BTC-USDC",),
    )
    max_workers = min(16, max(args.orders_per_batch, args.warmup_orders))
    engine = OrderEngine(
        orderbook=orderbook,
        db_module=order_database,
        subscription=subscription,
        api_key="offline",
        api_secret="offline",
        order_post_only={"BUY": False, "SELL": False},
        websocket_thread_maximum=1,
        max_workers=max_workers,
        queue_maxsize=max(1_000, args.orders_per_batch * 2),
        websocket_hooks=WebSocketHookRegistry(),
    )
    engine.logging_flags = {key: False for key in engine.logging_flags}

    generated_ids: list[str] = []
    run_id = str(uuid4())
    report: dict[str, Any] | None = None
    try:
        generation = engine._begin_user_stream_generation()
        _feed_envelope(
            engine,
            generation=generation,
            sequence_num=1,
            event={
                "type": WebSocketEventType.SNAPSHOT.value,
                "orders": [],
            },
        )
        if engine._user_feed_phase != UserFeedPhase.LIVE:
            raise RuntimeError("user feed did not reach LIVE after empty snapshot")

        await _run_batch(
            engine,
            generation=generation,
            sequence_num=2,
            run_id=run_id,
            batch=-1,
            order_count=args.warmup_orders,
            generated_ids=generated_ids,
            timeout_seconds=args.settle_timeout_seconds,
        )

        tracemalloc.start()
        gc.collect()
        rss_before = _current_rss_bytes()
        traced_before, _ = tracemalloc.get_traced_memory()
        threads_before = threading.active_count()
        fds_before = _open_fd_count()
        messages_before = client.messages_sent

        cpu_started = time.process_time()
        wall_started = time.perf_counter()
        for batch in range(args.batches):
            await _run_batch(
                engine,
                generation=generation,
                sequence_num=batch + 3,
                run_id=run_id,
                batch=batch,
                order_count=args.orders_per_batch,
                generated_ids=generated_ids,
                timeout_seconds=args.settle_timeout_seconds,
            )
        wall_seconds = time.perf_counter() - wall_started
        cpu_seconds = time.process_time() - cpu_started

        gc.collect()
        rss_after = _current_rss_bytes()
        traced_after, traced_peak = tracemalloc.get_traced_memory()
        threads_after = threading.active_count()
        fds_after = _open_fd_count()

        idle_cpu_started = time.process_time()
        await asyncio.sleep(args.idle_window_seconds)
        idle_cpu_seconds = time.process_time() - idle_cpu_started

        with engine._user_order_dispatcher._lock:
            dispatcher_pending = engine._user_order_dispatcher._pending_count
            dispatcher_queues = len(engine._user_order_dispatcher._queues)
            dispatcher_active = len(engine._user_order_dispatcher._active_keys)
        with orderbook._follow_up_ledger._lock:
            follow_up_claims = sum(
                len(slots)
                for slots in orderbook._follow_up_ledger._slots.values()
            )
        with engine.order_progress_tracker._records_lock:
            progress_records = len(engine.order_progress_tracker._records)
        with engine.order_progress_tracker._order_locks_guard:
            progress_locks = len(engine.order_progress_tracker._order_locks)

        database_counts = _database_counts(generated_ids)
        total_orders = args.warmup_orders + args.orders_per_batch * args.batches
        retained_orders = len(dashboard_server.engine_state["orders"])
        expected_retained_orders = min(
            total_orders,
            dashboard_server._MAX_TERMINAL_DASHBOARD_ORDERS,
        )
        current_task = asyncio.current_task()
        pending_tasks = sum(
            1
            for task in asyncio.all_tasks()
            if task is not current_task and not task.done()
        )

        measurements = {
            "wall_seconds": wall_seconds,
            "cpu_seconds": cpu_seconds,
            "one_core_cpu_utilization_percent": (
                cpu_seconds / wall_seconds * 100.0 if wall_seconds else 0.0
            ),
            "idle_cpu_seconds": idle_cpu_seconds,
            "rss_growth_bytes": max(0, rss_after - rss_before),
            "traced_growth_bytes": max(0, traced_after - traced_before),
            "traced_peak_growth_bytes": max(0, traced_peak - traced_before),
            "thread_growth": threads_after - threads_before,
            "fd_growth": fds_after - fds_before,
            "pending_asyncio_tasks": pending_tasks,
            "publisher_messages": client.messages_sent - messages_before,
            "publisher_scheduled": dashboard_server._state_publish_scheduled,
            "publisher_dirty": dashboard_server._state_publish_dirty,
            "retained_dashboard_orders": retained_orders,
            "retained_parent_entries": len(orderbook.parent_order_ids),
            "retained_live_orders": len(orderbook.order),
            "retained_follow_up_claims": follow_up_claims,
            "retained_coid_locks": len(engine._coid_handler_locks),
            "retained_progress_records": progress_records,
            "retained_progress_locks": progress_locks,
            "dispatcher_pending": dispatcher_pending,
            "dispatcher_queues": dispatcher_queues,
            "dispatcher_active_keys": dispatcher_active,
            "user_queue_depth": engine.event_queue[ChannelType.USER.value].qsize(),
            "user_feed_phase": engine._user_feed_phase.value,
            "database_counts": database_counts,
            "bytes_sent": client.bytes_sent,
        }
        limits = {
            "wall_seconds": args.max_wall_seconds,
            "cpu_seconds": args.max_cpu_seconds,
            "idle_cpu_seconds": args.max_idle_cpu_seconds,
            "rss_growth_bytes": int(args.max_rss_growth_mib * MIB),
            "traced_growth_bytes": int(args.max_traced_growth_mib * MIB),
            "thread_growth": max_workers,
            "fd_growth": 0,
            "pending_asyncio_tasks": 0,
        }
        violations = []
        for metric, limit in limits.items():
            if measurements[metric] > limit:
                violations.append(
                    f"{metric}: measured {measurements[metric]}, limit {limit}"
                )

        expected_zero = (
            "retained_parent_entries",
            "retained_live_orders",
            "retained_follow_up_claims",
            "retained_coid_locks",
            "retained_progress_records",
            "retained_progress_locks",
            "dispatcher_pending",
            "dispatcher_queues",
            "dispatcher_active_keys",
            "user_queue_depth",
        )
        for metric in expected_zero:
            if measurements[metric] != 0:
                violations.append(f"{metric}: expected 0, measured {measurements[metric]}")
        if retained_orders != expected_retained_orders:
            violations.append(
                "retained_dashboard_orders: expected "
                f"{expected_retained_orders}, measured {retained_orders}"
            )
        if engine._user_feed_phase != UserFeedPhase.LIVE:
            violations.append(
                f"user_feed_phase: expected live, measured {engine._user_feed_phase.value}"
            )
        if dashboard_server._state_publish_scheduled:
            violations.append("dashboard publisher remained scheduled")
        if dashboard_server._state_publish_dirty:
            violations.append("dashboard publisher remained dirty")

        for table in (
            "order_parent",
            "external_order_parent",
            "order_match_audit",
            "partial_fill_progress",
        ):
            if database_counts[table] != total_orders:
                violations.append(
                    f"{table}: expected {total_orders}, measured {database_counts[table]}"
                )
        if database_counts["order_event_stream"] < total_orders * 2:
            violations.append(
                "order_event_stream: expected at least "
                f"{total_orders * 2}, measured {database_counts['order_event_stream']}"
            )

        report = {
            "status": "fail" if violations else "pass",
            "scope": "synthetic_user_channel_to_database_to_dashboard_cancellation",
            "workload": {
                "orders_per_batch": args.orders_per_batch,
                "measured_batches": args.batches,
                "measured_cancellations": args.orders_per_batch * args.batches,
                "warmup_cancellations": args.warmup_orders,
            },
            "measurements": measurements,
            "limits": limits,
            "violations": violations,
        }
    finally:
        tracemalloc.stop()
        dashboard_server.connected_clients = set()
        engine.stop()
        engine.event_executor.shutdown(wait=True, cancel_futures=False)
        _cleanup_database(generated_ids)
        order_database.DB_CLIENT.disconnect()

    if report is None:
        raise RuntimeError("stress report was not produced")
    return report


def main() -> int:
    args = _build_parser().parse_args()
    # Schema initializers intentionally print progress. Keep stdout as one
    # machine-readable JSON document for the regression test and CI callers.
    with redirect_stdout(sys.stderr):
        report = asyncio.run(_run_stress(args))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
