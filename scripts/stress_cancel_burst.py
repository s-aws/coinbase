#!/usr/bin/env python3
"""Measure dashboard resource bounds during synthetic cancellation bursts.

This is deliberately exchange-free: it exercises the in-process dashboard
publication and retention path that previously amplified high-velocity order
updates.  The regression suite separately covers cancellation deduplication in
the order engine.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
from pathlib import Path
import sys
import threading
import time
import tracemalloc
from types import ModuleType
from typing import Any
from uuid import NAMESPACE_URL, uuid5


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# dashboard_server imports these configuration symbols for operator commands.
# This harness never executes those commands, and importing the real
# configuration module would perform Coinbase startup reads before the stress
# workload begins. Install the narrow interface the dashboard import requires
# so this process is provably exchange-free.
if "configuration" not in sys.modules:
    offline_configuration = ModuleType("configuration")
    offline_configuration.REST_CLIENT = None
    offline_configuration.rest_get_products = lambda: {}
    offline_configuration.update_product_metadata = lambda _metadata: None
    offline_configuration.get_product_metadata = lambda _product_id: None
    sys.modules["configuration"] = offline_configuration

import dashboard_server  # noqa: E402
from core.enums import OrderStatus  # noqa: E402


MIB = 1024 * 1024


class FastDashboardClient:
    """Minimal non-retaining WebSocket stand-in for the delivery hot path."""

    def __init__(self) -> None:
        self.messages_sent = 0
        self.bytes_sent = 0
        self.closed = False

    async def send(self, message: str) -> None:
        self.messages_sent += 1
        self.bytes_sent += len(message)
        await asyncio.sleep(0)

    async def close(self, **_kwargs: Any) -> None:
        self.closed = True


def _fresh_dashboard_state() -> dict[str, Any]:
    return {
        "orders": {},
        "positions": {},
        "stealth_orders": {},
        "engine_status": {},
        "logs": [],
        "market_metrics": {},
    }


def _current_rss_bytes() -> int:
    """Read current resident memory from Linux procfs."""

    with open("/proc/self/status", encoding="utf-8") as status_file:
        for line in status_file:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    raise RuntimeError("VmRSS is unavailable in /proc/self/status")


def _open_fd_count() -> int:
    return len(os.listdir("/proc/self/fd"))


def _emit_cancellation_batch(batch_number: int, orders_per_batch: int) -> None:
    status = OrderStatus.CANCELLED.value
    for index in range(orders_per_batch):
        client_order_id = str(
            uuid5(
                NAMESPACE_URL,
                f"dashboard-cancel-stress-{batch_number}-{index}",
            )
        )
        dashboard_server.update_order(
            client_order_id,
            {
                "client_order_id": client_order_id,
                "status": status,
            },
        )
        dashboard_server.add_log_entry(
            "INFO",
            f"Synthetic cancellation {client_order_id}",
        )


async def _wait_for_publisher(timeout_seconds: float) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while (
        dashboard_server._state_publish_scheduled
        or dashboard_server._state_publish_dirty
    ):
        if loop.time() >= deadline:
            raise TimeoutError("dashboard publisher did not quiesce")
        await asyncio.sleep(0.001)
    await asyncio.sleep(0)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stress the bounded dashboard cancellation-update path.",
    )
    parser.add_argument("--orders-per-batch", type=_positive_int, default=1_000)
    parser.add_argument("--batches", type=_positive_int, default=20)
    parser.add_argument("--settle-timeout-seconds", type=_positive_float, default=5.0)
    parser.add_argument("--idle-window-seconds", type=_positive_float, default=0.5)
    parser.add_argument("--max-wall-seconds", type=_positive_float, default=30.0)
    parser.add_argument("--max-cpu-seconds", type=_positive_float, default=15.0)
    parser.add_argument("--max-idle-cpu-seconds", type=_positive_float, default=0.05)
    parser.add_argument("--max-rss-growth-mib", type=_positive_float, default=64.0)
    parser.add_argument(
        "--max-traced-growth-mib",
        type=_positive_float,
        default=16.0,
    )
    parser.add_argument(
        "--max-traced-peak-growth-mib",
        type=_positive_float,
        default=32.0,
    )
    return parser


async def _run_stress(args: argparse.Namespace) -> dict[str, Any]:
    client = FastDashboardClient()
    dashboard_server.engine_state = _fresh_dashboard_state()
    dashboard_server.connected_clients = {client}
    dashboard_server.server_event_loop = asyncio.get_running_loop()
    dashboard_server._state_publish_scheduled = False
    dashboard_server._state_publish_dirty = False

    tracemalloc.start()

    # Warm the serializer and fill the bounded terminal-order history before
    # taking the baseline. Measured batches then replace an equal-size working
    # set instead of confusing normal one-time allocation with a leak.
    warmup_batches = (
        dashboard_server._MAX_TERMINAL_DASHBOARD_ORDERS
        + args.orders_per_batch
        - 1
    ) // args.orders_per_batch
    for warmup_batch in range(warmup_batches):
        _emit_cancellation_batch(-(warmup_batch + 1), args.orders_per_batch)
        await _wait_for_publisher(args.settle_timeout_seconds)
    gc.collect()

    rss_before = _current_rss_bytes()
    traced_before, _ = tracemalloc.get_traced_memory()
    tracemalloc.reset_peak()
    threads_before = threading.active_count()
    fds_before = _open_fd_count()
    messages_before = client.messages_sent

    cpu_started = time.process_time()
    wall_started = time.perf_counter()
    for batch_number in range(args.batches):
        _emit_cancellation_batch(batch_number, args.orders_per_batch)
        await _wait_for_publisher(args.settle_timeout_seconds)
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

    current_task = asyncio.current_task()
    pending_tasks = sum(
        1
        for task in asyncio.all_tasks()
        if task is not current_task and not task.done()
    )
    retained_orders = len(dashboard_server.engine_state["orders"])
    retained_logs = len(dashboard_server.engine_state["logs"])
    publisher_messages = client.messages_sent - messages_before

    expected_orders = dashboard_server._MAX_TERMINAL_DASHBOARD_ORDERS
    rss_growth = max(0, rss_after - rss_before)
    traced_growth = max(0, traced_after - traced_before)
    traced_peak_growth = max(0, traced_peak - traced_before)

    limits = {
        "wall_seconds": args.max_wall_seconds,
        "cpu_seconds": args.max_cpu_seconds,
        "idle_cpu_seconds": args.max_idle_cpu_seconds,
        "rss_growth_bytes": int(args.max_rss_growth_mib * MIB),
        "traced_growth_bytes": int(args.max_traced_growth_mib * MIB),
        "traced_peak_growth_bytes": int(args.max_traced_peak_growth_mib * MIB),
        "pending_asyncio_tasks": 0,
        "thread_growth": 0,
        "fd_growth": 0,
        "publisher_messages": args.batches,
        "retained_orders": expected_orders,
        "retained_logs": dashboard_server.max_logs,
    }
    measurements = {
        "wall_seconds": wall_seconds,
        "cpu_seconds": cpu_seconds,
        "one_core_cpu_utilization_percent": (
            cpu_seconds / wall_seconds * 100.0 if wall_seconds else 0.0
        ),
        "idle_cpu_seconds": idle_cpu_seconds,
        "rss_before_bytes": rss_before,
        "rss_after_bytes": rss_after,
        "rss_growth_bytes": rss_growth,
        "traced_growth_bytes": traced_growth,
        "traced_peak_growth_bytes": traced_peak_growth,
        "pending_asyncio_tasks": pending_tasks,
        "thread_growth": threads_after - threads_before,
        "fd_growth": fds_after - fds_before,
        "publisher_messages": publisher_messages,
        "publisher_scheduled": dashboard_server._state_publish_scheduled,
        "publisher_dirty": dashboard_server._state_publish_dirty,
        "retained_orders": retained_orders,
        "retained_logs": retained_logs,
        "bytes_sent": client.bytes_sent,
    }

    violations = []
    for metric in (
        "wall_seconds",
        "cpu_seconds",
        "idle_cpu_seconds",
        "rss_growth_bytes",
        "traced_growth_bytes",
        "traced_peak_growth_bytes",
        "pending_asyncio_tasks",
        "thread_growth",
        "fd_growth",
        "publisher_messages",
        "retained_orders",
        "retained_logs",
    ):
        measured = measurements[metric]
        limit = limits[metric]
        if metric in {"publisher_messages", "retained_orders", "retained_logs"}:
            if measured != limit:
                violations.append(f"{metric}: measured {measured}, expected {limit}")
        elif measured > limit:
            violations.append(f"{metric}: measured {measured}, limit {limit}")

    if measurements["publisher_scheduled"]:
        violations.append("publisher remained scheduled after the idle window")
    if measurements["publisher_dirty"]:
        violations.append("publisher remained dirty after the idle window")

    tracemalloc.stop()
    return {
        "status": "fail" if violations else "pass",
        "scope": "synthetic_dashboard_cancellation_publication",
        "workload": {
            "orders_per_batch": args.orders_per_batch,
            "measured_batches": args.batches,
            "measured_cancellations": args.orders_per_batch * args.batches,
            "warmup_batches": warmup_batches,
            "warmup_cancellations": args.orders_per_batch * warmup_batches,
        },
        "measurements": measurements,
        "limits": limits,
        "violations": violations,
    }


def main() -> int:
    args = _build_parser().parse_args()
    report = asyncio.run(_run_stress(args))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
