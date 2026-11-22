#!/usr/bin/env python3
"""Stress private-feed reconnect fencing and database-backed restart recovery."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import redirect_stdout
import gc
import json
from pathlib import Path
import sys
import threading
import time
import tracemalloc
from typing import Any
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.stress_cancel_pipeline import (
    MIB,
    _cleanup_database,
    _feed_envelope,
    _make_cancelled_order,
    _wait_for_engine_quiescence,
    build_pipeline_engine,
)
from scripts.stress_cancel_burst import (
    FastDashboardClient,
    _current_rss_bytes,
    _fresh_dashboard_state,
    _open_fd_count,
    _positive_float,
    _positive_int,
    _wait_for_publisher,
)

import dashboard_server
from core.enums import ChannelType, OrderStatus, UserFeedPhase, WebSocketEventType
from database import order as order_database
from database.schema import initialize_database_schema


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stress user-feed reconnect and process-restart recovery.",
    )
    parser.add_argument("--reconnect-cycles", type=_positive_int, default=100)
    parser.add_argument("--restart-orders", type=_positive_int, default=100)
    parser.add_argument("--orders-per-envelope", type=_positive_int, default=25)
    parser.add_argument("--settle-timeout-seconds", type=_positive_float, default=30.0)
    parser.add_argument("--idle-window-seconds", type=_positive_float, default=0.5)
    parser.add_argument("--max-wall-seconds", type=_positive_float, default=60.0)
    parser.add_argument("--max-reconnect-seconds", type=_positive_float, default=10.0)
    parser.add_argument("--max-recovery-seconds", type=_positive_float, default=30.0)
    parser.add_argument("--max-idle-cpu-seconds", type=_positive_float, default=0.05)
    parser.add_argument("--max-rss-growth-mib", type=_positive_float, default=64.0)
    parser.add_argument("--max-traced-growth-mib", type=_positive_float, default=24.0)
    return parser


def _wire_message(sequence_num: int, event: dict[str, Any]) -> str:
    return json.dumps({
        "channel": ChannelType.USER.value,
        "sequence_num": sequence_num,
        "timestamp": "2026-11-22T12:00:00Z",
        "events": [event],
    })


def _open_order(run_id: str, index: int) -> dict[str, Any]:
    order = _make_cancelled_order(run_id, 0, index)
    order.update({
        "status": OrderStatus.OPEN.value,
        "leaves_quantity": "1",
    })
    return order


def _chunks(values: list[dict[str, Any]], size: int):
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _database_status_count(client_order_ids: list[str], status: str) -> int:
    rows = order_database.DB_CLIENT.execute_query(
        "SELECT COUNT(*) AS count FROM order_parent "
        "WHERE client_order_id = ANY(%s) "
        "AND externally_created IS TRUE AND status = %s",
        (client_order_ids, status),
    )
    return int(rows[0]["count"])


def _stop_engine(engine) -> None:
    if engine is None:
        return
    engine.stop()
    engine.event_executor.shutdown(wait=True, cancel_futures=False)


async def _send_live_batches(
    engine,
    *,
    generation: int,
    first_sequence: int,
    orders: list[dict[str, Any]],
    orders_per_envelope: int,
    timeout_seconds: float,
) -> int:
    sequence = first_sequence
    for batch in _chunks(orders, orders_per_envelope):
        _feed_envelope(
            engine,
            generation=generation,
            sequence_num=sequence,
            event={
                "type": WebSocketEventType.PATCH.value,
                "orders": batch,
            },
        )
        await _wait_for_engine_quiescence(engine, timeout_seconds)
        sequence += 1
    return sequence


def _hydrate_snapshot(
    engine,
    *,
    generation: int,
    orders: list[dict[str, Any]],
) -> int:
    sequence = 1
    pages = list(_chunks(orders, 50))
    if not pages:
        pages = [[]]
    for index, page in enumerate(pages):
        _feed_envelope(
            engine,
            generation=generation,
            sequence_num=sequence,
            event={
                "type": (
                    WebSocketEventType.SNAPSHOT.value
                    if index == 0
                    else WebSocketEventType.PATCH.value
                ),
                "orders": page,
            },
        )
        sequence += 1
    if pages and len(pages[-1]) == 50:
        _feed_envelope(
            engine,
            generation=generation,
            sequence_num=sequence,
            event={
                "type": WebSocketEventType.PATCH.value,
                "orders": [],
            },
        )
        sequence += 1
    return sequence


async def _run_stress(args: argparse.Namespace) -> dict[str, Any]:
    initialize_database_schema()
    client = FastDashboardClient()
    dashboard_server.engine_state = _fresh_dashboard_state()
    dashboard_server.connected_clients = {client}
    dashboard_server.server_event_loop = asyncio.get_running_loop()
    dashboard_server._state_publish_scheduled = False
    dashboard_server._state_publish_dirty = False

    run_id = str(uuid4())
    open_orders = [_open_order(run_id, index) for index in range(args.restart_orders)]
    client_order_ids = [order["client_order_id"] for order in open_orders]
    cancelled_orders = [
        {
            **order,
            "status": OrderStatus.CANCELLED.value,
            "leaves_quantity": "0",
        }
        for order in open_orders
    ]

    engine = None
    restart_engine = None
    report: dict[str, Any] | None = None
    tracemalloc.start()
    gc.collect()
    rss_before = _current_rss_bytes()
    traced_before, _ = tracemalloc.get_traced_memory()
    threads_before = threading.active_count()
    fds_before = _open_fd_count()
    wall_started = time.perf_counter()
    try:
        engine, orderbook = build_pipeline_engine(
            max_workers=min(16, args.restart_orders),
            queue_maxsize=max(1_000, args.restart_orders * 2),
        )
        reconnect_event = threading.Event()
        generation = engine._begin_user_stream_generation(reconnect_event)
        _hydrate_snapshot(engine, generation=generation, orders=[])
        if engine._user_feed_phase is not UserFeedPhase.LIVE:
            raise RuntimeError("initial empty snapshot did not enter LIVE")

        reconnect_started = time.perf_counter()
        stale_messages_dropped = 0
        for _cycle in range(args.reconnect_cycles):
            engine.on_user_message(
                _wire_message(
                    3,
                    {"type": WebSocketEventType.PATCH.value, "orders": []},
                ),
                generation=generation,
            )
            if (
                engine._user_feed_phase is not UserFeedPhase.DESYNCHRONIZED
                or not reconnect_event.is_set()
            ):
                raise RuntimeError("sequence gap did not request reconnect")

            old_generation = generation
            reconnect_event = threading.Event()
            generation = engine._begin_user_stream_generation(reconnect_event)
            queue_depth = engine.event_queue[ChannelType.USER.value].qsize()
            engine.on_user_message(
                _wire_message(
                    2,
                    {"type": WebSocketEventType.PATCH.value, "orders": []},
                ),
                generation=old_generation,
            )
            if engine.event_queue[ChannelType.USER.value].qsize() != queue_depth:
                raise RuntimeError("stale generation message entered reducer queue")
            stale_messages_dropped += 1
            _hydrate_snapshot(engine, generation=generation, orders=[])
            if engine._user_feed_phase is not UserFeedPhase.LIVE:
                raise RuntimeError("new generation did not recover to LIVE")
        reconnect_seconds = time.perf_counter() - reconnect_started

        next_sequence = await _send_live_batches(
            engine,
            generation=generation,
            first_sequence=2,
            orders=open_orders,
            orders_per_envelope=args.orders_per_envelope,
            timeout_seconds=args.settle_timeout_seconds,
        )
        if next_sequence <= 2:
            raise RuntimeError("active order workload was not submitted")
        if _database_status_count(client_order_ids, OrderStatus.OPEN.value) != args.restart_orders:
            raise RuntimeError("active external orders were not persisted before restart")
        if len(orderbook.parent_order_ids) != args.restart_orders:
            raise RuntimeError("active parent cache did not match persisted workload")

        _stop_engine(engine)
        engine = None
        del orderbook
        gc.collect()

        recovery_started = time.perf_counter()
        restart_engine, restart_orderbook = build_pipeline_engine(
            max_workers=min(16, args.restart_orders),
            queue_maxsize=max(1_000, args.restart_orders * 2),
        )
        restart_engine.load_parent_child_order_ids()
        missing_reloaded_parents = set(client_order_ids).difference(
            restart_orderbook.parent_order_ids
        )
        if missing_reloaded_parents:
            raise RuntimeError(
                "restart did not reload every generated active parent: "
                f"missing {len(missing_reloaded_parents)}"
            )
        if not all(
            restart_orderbook.parent_order_ids[client_order_id].get(
                "externally_created"
            ) is True
            for client_order_id in client_order_ids
        ):
            raise RuntimeError("restart lost external-order provenance")

        restart_generation = restart_engine._begin_user_stream_generation(
            threading.Event()
        )
        next_sequence = _hydrate_snapshot(
            restart_engine,
            generation=restart_generation,
            orders=open_orders,
        )
        if restart_engine._user_feed_phase is not UserFeedPhase.LIVE:
            raise RuntimeError("restart snapshot did not enter LIVE")
        if len(restart_orderbook.order) != args.restart_orders:
            raise RuntimeError("restart snapshot did not hydrate every live order")
        recovery_seconds = time.perf_counter() - recovery_started

        await _send_live_batches(
            restart_engine,
            generation=restart_generation,
            first_sequence=next_sequence,
            orders=cancelled_orders,
            orders_per_envelope=args.orders_per_envelope,
            timeout_seconds=args.settle_timeout_seconds,
        )
        await _wait_for_publisher(args.settle_timeout_seconds)
        if _database_status_count(
            client_order_ids,
            OrderStatus.CANCELLED.value,
        ) != args.restart_orders:
            raise RuntimeError("recovered orders did not persist terminal status")

        with restart_engine._user_order_dispatcher._lock:
            dispatcher_pending = restart_engine._user_order_dispatcher._pending_count
            dispatcher_queues = len(restart_engine._user_order_dispatcher._queues)
            dispatcher_active = len(restart_engine._user_order_dispatcher._active_keys)
        with restart_orderbook._follow_up_ledger._lock:
            follow_up_claims = sum(
                len(slots)
                for slots in restart_orderbook._follow_up_ledger._slots.values()
            )
        active_generation = restart_engine._user_stream_generation
        user_feed_phase = restart_engine._user_feed_phase
        user_queue_depth = restart_engine.event_queue[
            ChannelType.USER.value
        ].qsize()
        retained_generated_parent_entries = sum(
            client_order_id in restart_orderbook.parent_order_ids
            for client_order_id in client_order_ids
        )
        retained_generated_live_orders = sum(
            client_order_id in restart_orderbook.order
            for client_order_id in client_order_ids
        )
        retained_coid_locks = len(restart_engine._coid_handler_locks)
        retained_generation_inflight = len(
            restart_engine._user_generation_inflight
        )

        # A process-restart test must prove the replacement engine's worker
        # pool also shuts down. Measure threads only after releasing it.
        _stop_engine(restart_engine)
        restart_engine = None
        await _wait_for_publisher(args.settle_timeout_seconds)
        del restart_orderbook
        gc.collect()
        rss_after = _current_rss_bytes()
        traced_after, traced_peak = tracemalloc.get_traced_memory()
        idle_cpu_started = time.process_time()
        await asyncio.sleep(args.idle_window_seconds)
        idle_cpu_seconds = time.process_time() - idle_cpu_started
        wall_seconds = time.perf_counter() - wall_started

        measurements = {
            "wall_seconds": wall_seconds,
            "reconnect_seconds": reconnect_seconds,
            "recovery_seconds": recovery_seconds,
            "idle_cpu_seconds": idle_cpu_seconds,
            "rss_growth_bytes": max(0, rss_after - rss_before),
            "traced_growth_bytes": max(0, traced_after - traced_before),
            "traced_peak_growth_bytes": max(0, traced_peak - traced_before),
            "thread_growth": threading.active_count() - threads_before,
            "fd_growth": _open_fd_count() - fds_before,
            "stale_messages_dropped": stale_messages_dropped,
            "active_generation": active_generation,
            "user_feed_phase": user_feed_phase.value,
            "user_queue_depth": user_queue_depth,
            "dispatcher_pending": dispatcher_pending,
            "dispatcher_queues": dispatcher_queues,
            "dispatcher_active_keys": dispatcher_active,
            "retained_generated_parent_entries": retained_generated_parent_entries,
            "retained_generated_live_orders": retained_generated_live_orders,
            "retained_follow_up_claims": follow_up_claims,
            "retained_coid_locks": retained_coid_locks,
            "retained_generation_inflight": retained_generation_inflight,
            "publisher_scheduled": dashboard_server._state_publish_scheduled,
            "publisher_dirty": dashboard_server._state_publish_dirty,
            "publisher_messages": client.messages_sent,
            "bytes_sent": client.bytes_sent,
        }
        limits = {
            "wall_seconds": args.max_wall_seconds,
            "reconnect_seconds": args.max_reconnect_seconds,
            "recovery_seconds": args.max_recovery_seconds,
            "idle_cpu_seconds": args.max_idle_cpu_seconds,
            "rss_growth_bytes": int(args.max_rss_growth_mib * MIB),
            "traced_growth_bytes": int(args.max_traced_growth_mib * MIB),
            "thread_growth": 0,
            "fd_growth": 0,
        }
        violations = [
            f"{metric}: measured {measurements[metric]}, limit {limit}"
            for metric, limit in limits.items()
            if measurements[metric] > limit
        ]
        expected_zero = (
            "user_queue_depth",
            "dispatcher_pending",
            "dispatcher_queues",
            "dispatcher_active_keys",
            "retained_generated_parent_entries",
            "retained_generated_live_orders",
            "retained_follow_up_claims",
            "retained_coid_locks",
            "retained_generation_inflight",
        )
        for metric in expected_zero:
            if measurements[metric] != 0:
                violations.append(
                    f"{metric}: expected 0, measured {measurements[metric]}"
                )
        if stale_messages_dropped != args.reconnect_cycles:
            violations.append(
                "stale_messages_dropped: expected "
                f"{args.reconnect_cycles}, measured {stale_messages_dropped}"
            )
        if user_feed_phase is not UserFeedPhase.LIVE:
            violations.append(
                "user_feed_phase: expected live, measured "
                f"{user_feed_phase.value}"
            )
        if dashboard_server._state_publish_scheduled:
            violations.append("dashboard publisher remained scheduled")
        if dashboard_server._state_publish_dirty:
            violations.append("dashboard publisher remained dirty")

        report = {
            "status": "fail" if violations else "pass",
            "scope": "private_feed_reconnect_and_database_restart_recovery",
            "workload": {
                "reconnect_cycles": args.reconnect_cycles,
                "restart_orders": args.restart_orders,
                "orders_per_envelope": args.orders_per_envelope,
            },
            "measurements": measurements,
            "limits": limits,
            "violations": violations,
        }
    finally:
        dashboard_server.connected_clients = set()
        _stop_engine(engine)
        _stop_engine(restart_engine)
        _cleanup_database(client_order_ids)
        order_database.DB_CLIENT.disconnect()
        tracemalloc.stop()

    if report is None:
        raise RuntimeError("recovery stress report was not produced")
    return report


def main() -> int:
    args = _build_parser().parse_args()
    with redirect_stdout(sys.stderr):
        report = asyncio.run(_run_stress(args))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
