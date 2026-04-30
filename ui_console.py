"""Console UI for the trading engine.

Standalone consumer of the existing dashboard WebSocket (ws://localhost:8765),
mirroring the same producer/consumer paradigm as the ui_*.html files. No
engine changes, no shared locks, no parallel state — read-only render of the
``state_update`` broadcast that the engine already publishes.

Run from repo root in a separate terminal alongside the engine:

    py -3.13 ui_console.py                    # connect to ws://localhost:8765
    py -3.13 ui_console.py --host 1.2.3.4     # remote host
    py -3.13 ui_console.py --port 9000        # custom port

Quit with Ctrl+C. The view auto-reconnects on disconnect.

Layout (top to bottom):

  ┌─ Engine ─────────────────────────────────────────────────────────────┐
  │ status • threads • fee regime • last update                          │
  └──────────────────────────────────────────────────────────────────────┘
  ┌─ Stealth Orders (active) ────────────────────────────────────────────┐
  │ id • product • side • size • status • limit • target • reprices      │
  └──────────────────────────────────────────────────────────────────────┘
  ┌─ Logs (last 20) ─────────────────────────────────────────────────────┐
  │ ts level message                                                     │
  └──────────────────────────────────────────────────────────────────────┘

What this DOES NOT do (by design — keeps the consumer thin):
  - Place / cancel / modify orders. Use the HTML UI or CLI tools.
  - Aggregate market history. Use ui_slide_calibration_chart.html.
  - Display per-product market averages. The dashboard broadcast does not
    currently surface raw ticker data; if/when it does, this UI can render
    it without engine changes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
from datetime import datetime
from typing import Any, Dict, Optional

import websockets
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Canonical normalizer for stealth-order anchor repricing config. Using
# the dataclass keeps this consumer aligned with every other reader and
# satisfies the static-source guard in
# tests/regression/test_repricing_policy.py.
from core.models import RepricingPolicy


# Mirrors core.enums.StealthOrderStatus active set; same definition the HTML
# UIs use. Producer/consumer contract — keep aligned.
ACTIVE_STATUSES = {"HIDDEN", "PENDING", "TRIGGERED", "REVEALED"}


def _fmt_minutes_label(m: int) -> str:
    if m < 60:
        return f"{m}m"
    if m < 1440:
        return f"{m / 60:.0f}h"
    return f"{m / 1440:.1f}d"


def fmt_num(v: Any, digits: int = 2) -> str:
    if v is None:
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    if n != n:  # NaN
        return "—"
    return f"{n:.{digits}f}"


def fmt_int(v: Any) -> str:
    if v is None:
        return "—"
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return str(v)


def short_id(value: Any, n: int = 8) -> str:
    s = str(value or "")
    return s[:n] if s else "—"


def render_engine_panel(engine_status: Dict[str, Any]) -> Panel:
    running = bool(engine_status.get("running"))
    state_text = Text("RUNNING", style="bold green") if running else Text("STOPPED", style="bold red")

    line1 = Text.assemble(
        ("state ", "dim"), state_text,
        ("  threads ", "dim"), (str(engine_status.get("threads_active", "—")), "white"),
        ("  queue ", "dim"), (str(engine_status.get("event_queue_depth", "—")), "white"),
    )
    line2 = Text.assemble(
        ("taker fee ", "dim"), (fmt_num(engine_status.get("taker_fee_rate"), 4), "white"),
        ("  effective ", "dim"), (fmt_num(engine_status.get("effective_fee_rate"), 4), "white"),
        ("  target× ", "dim"), (fmt_num(engine_status.get("target_movement_factor"), 3), "white"),
        ("  fee× ", "dim"), (fmt_num(engine_status.get("fee_regime_factor"), 3), "white"),
        ("  vol ratio ", "dim"), (fmt_num(engine_status.get("volume_ratio"), 3), "white"),
    )
    overnight = engine_status.get("overnight_margin_active")
    margin = engine_status.get("margin_window_type")
    line3 = Text.assemble(
        ("margin ", "dim"),
        (str(margin or "—"), "yellow" if overnight else "white"),
        ("  overnight ", "dim"),
        ("yes" if overnight else "no", "yellow" if overnight else "white"),
        ("  last update ", "dim"),
        (str(engine_status.get("last_update") or "—"), "white"),
    )

    body = Text("\n").join([line1, line2, line3])
    return Panel(body, title="Engine", border_style="cyan", padding=(0, 1))


def render_stealth_panel(stealth_orders: Dict[str, Any]) -> Panel:
    table = Table(expand=True, show_lines=False, header_style="bold cyan")
    table.add_column("id", width=10, style="dim")
    table.add_column("product", width=18)
    table.add_column("side", width=4)
    table.add_column("size", justify="right", width=10)
    table.add_column("status", width=10)
    table.add_column("limit", justify="right", width=12)
    table.add_column("target", justify="right", width=10)
    table.add_column("repx", justify="right", width=6)
    table.add_column("policy", width=12)

    rows = []
    for sid, order in (stealth_orders or {}).items():
        if not isinstance(order, dict):
            continue
        status = str(order.get("status") or "").upper()
        if status not in ACTIVE_STATUSES:
            continue

        side = str(order.get("side") or "").upper()
        side_style = "green" if side == "BUY" else "red" if side == "SELL" else "white"

        target = order.get("target_movement")
        target_type = order.get("target_movement_type") or "P"
        target_str = (
            f"{fmt_num(target, 4)}{'%' if target_type == 'P' else ''}"
            if target is not None else "—"
        )

        state = order.get("anchor_repricing_state_json") or {}
        policy = RepricingPolicy.coerce(order.get("anchor_repricing_policy_json"))
        repx = len(state.get("reprice_history") or [])
        policy_label = (
            policy.reference_price_source.value
            if policy.enabled else "off"
        )

        status_styles = {
            "HIDDEN": "dim",
            "PENDING": "yellow",
            "TRIGGERED": "magenta",
            "REVEALED": "bold green",
        }

        rows.append((
            order.get("created_at") or "",
            short_id(sid),
            order.get("product_id") or "—",
            Text(side or "—", style=side_style),
            fmt_num(order.get("total_size"), 4),
            Text(status, style=status_styles.get(status, "white")),
            fmt_num(order.get("limit_price"), 2),
            target_str,
            str(repx),
            policy_label,
        ))

    # Stable order: most-recent first. created_at can be missing on legacy
    # rows so fall back to short id for a deterministic tiebreak.
    rows.sort(key=lambda r: (r[0] or "", r[1]), reverse=True)

    if not rows:
        table.add_row("—", "no active stealth orders", "", "", "", "", "", "", "")
    else:
        for _, *cells in rows:
            table.add_row(*cells)

    return Panel(table, title=f"Stealth Orders (active: {len(rows)})",
                 border_style="cyan", padding=(0, 1))


def render_market_metrics_panel(metrics: Dict[str, Any]) -> Panel:
    """Render the per-product window-averages grid.

    Producer/consumer contract: this reads the shape produced by
    ``business/market_metrics.py::MarketMetricsTracker.snapshot()`` —
    keep aligned. Each window cell shows the percent change of current
    price vs the window mean (green = price above avg, red = below).

    Columns are derived from whatever windows the server sends — the
    server picks the preset (standard / fibonacci) via
    ``$MARKET_METRICS_WINDOWS``, and the console just renders it. This
    keeps producer and consumer in lock-step (P2 rule #12).
    """
    # Column set is the union of window-minute keys across all products,
    # sorted ascending. In practice every product carries the same set
    # because they share a tracker, but using a union keeps the panel
    # robust to a stale snapshot mid-preset-switch.
    column_minutes = sorted({
        int(w.get("minutes"))
        for entry in (metrics or {}).values()
        if isinstance(entry, dict)
        for w in (entry.get("windows") or [])
        if isinstance(w, dict) and w.get("minutes") is not None
    })

    table = Table(expand=True, show_lines=False, header_style="bold cyan")
    table.add_column("product", width=18)
    table.add_column("price", justify="right", width=12)
    for w in column_minutes:
        table.add_column(_fmt_minutes_label(w), justify="right", width=8)

    if not metrics or not column_minutes:
        empty = ["—", "no ticker data yet"] + ["" for _ in column_minutes]
        table.add_row(*empty)
        return Panel(table, title="Market Metrics (Δ% vs avg)",
                     border_style="cyan", padding=(0, 1))

    # Sort products alphabetically so layout stays stable across ticks.
    for product_id in sorted(metrics.keys()):
        entry = metrics.get(product_id) or {}
        price = entry.get("price")
        # Index window deltas by minute size for O(1) lookup.
        windows_by_min = {
            int(w.get("minutes")): w
            for w in (entry.get("windows") or [])
            if isinstance(w, dict) and w.get("minutes") is not None
        }
        cells = [product_id, fmt_num(price, 4)]
        for w_min in column_minutes:
            w = windows_by_min.get(w_min)
            if w is None:
                cells.append(Text("—", style="dim"))
                continue
            delta = w.get("delta_pct")
            if delta is None:
                cells.append(Text("—", style="dim"))
                continue
            try:
                d = float(delta)
            except (TypeError, ValueError):
                cells.append(Text("—", style="dim"))
                continue
            style = "green" if d > 0 else ("red" if d < 0 else "white")
            cells.append(Text(f"{d:+.2f}%", style=style))
        table.add_row(*cells)

    return Panel(table,
                 title=f"Market Metrics ({len(metrics)} products • Δ% vs avg)",
                 border_style="cyan", padding=(0, 1))


def render_logs_panel(logs: list, limit: int = 20) -> Panel:
    table = Table(expand=True, show_header=False, padding=(0, 1), box=None)
    table.add_column(width=19, style="dim")  # ts
    table.add_column(width=8)                 # level
    table.add_column(ratio=1, no_wrap=False)  # message

    level_styles = {
        "ERROR":   "bold red",
        "WARNING": "yellow",
        "INFO":    "white",
        "DEBUG":   "dim",
    }

    # Engine state stores logs oldest-first; show the tail.
    tail = (logs or [])[-limit:]
    if not tail:
        table.add_row("", "", Text("no log entries yet", style="dim"))
    else:
        for entry in tail:
            ts = str(entry.get("timestamp") or "")[:19]
            level = str(entry.get("level") or "INFO").upper()
            msg = str(entry.get("message") or "")
            table.add_row(ts, Text(level, style=level_styles.get(level, "white")), msg)

    return Panel(table, title=f"Logs (last {limit})",
                 border_style="cyan", padding=(0, 1))


def build_layout(state: Dict[str, Any], status_text: str) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="engine", size=5),
        Layout(name="metrics", ratio=2),
        Layout(name="stealth", ratio=2),
        Layout(name="logs", ratio=1),
        Layout(name="status", size=1),
    )
    layout["engine"].update(render_engine_panel(state.get("engine_status") or {}))
    layout["metrics"].update(render_market_metrics_panel(state.get("market_metrics") or {}))
    layout["stealth"].update(render_stealth_panel(state.get("stealth_orders") or {}))
    layout["logs"].update(render_logs_panel(state.get("logs") or []))
    layout["status"].update(Text(status_text, style="dim"))
    return layout


async def run(host: str, port: int) -> None:
    """Connect to the dashboard WS and render forever, reconnecting as needed."""
    console = Console()
    state: Dict[str, Any] = {}
    url = f"ws://{host}:{port}"

    with Live(build_layout(state, f"connecting to {url}…"),
              console=console, screen=True, refresh_per_second=4) as live:

        while True:
            try:
                async with websockets.connect(url, max_size=8 * 1024 * 1024) as ws:
                    live.update(build_layout(state, f"connected • {url}"))

                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            continue

                        # The dashboard publishes several message types; we
                        # only need state_update for the live render. Other
                        # message types are no-ops here, matching the read-
                        # only contract documented in the module docstring.
                        if msg.get("type") != "state_update":
                            continue

                        data = msg.get("data") or {}
                        state["engine_status"]   = data.get("engine_status") or {}
                        state["market_metrics"]  = data.get("market_metrics") or {}
                        state["stealth_orders"]  = data.get("stealth_orders") or {}
                        state["logs"]            = data.get("logs") or []

                        ts = msg.get("timestamp") or datetime.utcnow().isoformat()
                        live.update(build_layout(state, f"connected • {url} • {ts}"))

            except (OSError, websockets.exceptions.WebSocketException) as e:
                live.update(build_layout(
                    state,
                    f"disconnected ({type(e).__name__}: {e}) • retrying in 2s…"
                ))
                await asyncio.sleep(2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Console UI for the trading engine.")
    parser.add_argument("--host", default="localhost",
                        help="Dashboard WebSocket host (default: localhost)")
    parser.add_argument("--port", type=int, default=8765,
                        help="Dashboard WebSocket port (default: 8765)")
    args = parser.parse_args()

    # On Windows, threading.Event.wait() / Lock.acquire() with no timeout
    # block SIGINT delivery (see /memories/windows-signal-event-wait.md).
    # asyncio handles this correctly via KeyboardInterrupt during await
    # points, so we install no special handler and rely on Ctrl+C bubbling
    # out of asyncio.run.
    if sys.platform != "win32":
        loop_signal = getattr(asyncio, "get_event_loop", None)
        # No-op placeholder — kept for parity if POSIX users want SIGTERM.
        del loop_signal

    try:
        asyncio.run(run(args.host, args.port))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
