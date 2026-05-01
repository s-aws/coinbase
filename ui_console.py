"""Console UI for the trading engine.

Standalone consumer of the existing dashboard WebSocket (ws://localhost:8765),
mirroring the same producer/consumer paradigm as the ui_*.html files. No
engine changes, no shared locks, no parallel state — read-only render of the
``state_update`` broadcast that the engine already publishes.

Run from repo root in a separate terminal alongside the engine:

    py -3.13 ui_console.py                       # default: cross-venue ON
    py -3.13 ui_console.py --host 1.2.3.4        # remote dashboard host
    py -3.13 ui_console.py --port 9000           # custom dashboard port
    py -3.13 ui_console.py --no-cross-venue      # disable Binance perp WS

Quit with Ctrl+C. The dashboard view auto-reconnects on disconnect; the
cross-venue Binance feed reconnects independently with its own backoff.

Layout (top to bottom):

  ┌─ Engine ─────────────────────────────────────────────────────────────┐
  │ status • threads • fee regime • last update                          │
  └──────────────────────────────────────────────────────────────────────┘
  ┌─ Cross-Venue (Coinbase perp vs world) ───────────────────────────────┐
  │ product • CB mid • ext mid • premium $/bps • 1m/5m/15m premium avg   │
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
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, Optional, Tuple

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

# Cross-venue intel (Phase 1: Binance USDT-M perp). Owned entirely by
# this consumer — no engine coupling — and toggleable via --no-cross-venue.
# Heavy imports happen lazily inside ``CrossVenueMonitor.start`` so that
# disabling the feed (or running on a host without ``websockets`` available
# for the external feed) doesn't break the dashboard view.
from market_intel.venues import COINBASE_TO_EXTERNAL, Venue


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


# ---- Cross-Venue Monitor (Phase 1) ----------------------------------------
#
# Standalone, ui_console-owned tracker of (Coinbase mid vs external
# venue mid). Runs the Binance USDT-M perp WS client in a background
# thread + asyncio loop, samples the cross-venue aggregator on every
# render tick, and keeps a small per-product rolling history of
# ``(timestamp, coinbase_mid, external_mid, premium_bps)`` so the panel
# can show 1m / 5m / 15m premium averages alongside the live snapshot.
#
# Design choices:
#   * The monitor lives entirely inside ui_console: zero engine
#     coupling, zero shared state with the dashboard server.
#   * Coinbase mid is taken from the existing ``market_metrics``
#     broadcast (``data.market_metrics[product_id].price``). No new
#     producer wiring needed.
#   * History buffers are bounded (``maxlen``) so the consumer can run
#     for hours without memory growth.
#   * Reads/writes to the history are guarded by a per-monitor lock
#     because the WS client thread feeds the aggregator while the
#     asyncio render loop reads from it via ``snapshot()``.

# Keep at most ~3 hours of 1-second samples per product. 3*3600 = 10_800
# entries * ~5 products * ~32 bytes/entry ~= 1.7 MiB worst case.
_HISTORY_MAXLEN = 3 * 60 * 60
# Sample at most once per second per product even if render runs faster
# (rich Live refreshes at 4 Hz). Prevents unnecessary lock contention
# and keeps the rolling-average windows well-defined.
_HISTORY_SAMPLE_INTERVAL_SECONDS = 1.0


class CrossVenueMonitor:
    """Owns the external WS client + aggregator + rolling history.

    Lifecycle:
        monitor = CrossVenueMonitor()
        monitor.start()
        ...
        # Each render tick:
        monitor.observe_coinbase_mids({"BIP-20DEC30-CDE": 70_005.0, ...})
        snapshot = monitor.snapshot({...})
        # render snapshot
        ...
        monitor.stop()
    """

    def __init__(self):
        self._enabled = False
        self._aggregator = None
        self._clients: list = []
        self._lock = threading.Lock()
        # product_id -> deque[(monotonic_ts, coinbase_mid, external_mid, premium_bps)]
        self._history: Dict[str, Deque[Tuple[float, float, float, float]]] = {}
        # Last sample monotonic timestamp per product, to enforce the
        # ~1Hz sampling rate independently of render frequency.
        self._last_sample_ts: Dict[str, float] = {}

    def start(self) -> None:
        """Spin up every external venue WS client + in-process aggregator.

        Imports the heavy modules lazily so ``--no-cross-venue`` users
        don't pay the cost of pulling in the external WS dependency
        graph just to render the engine state.

        Fail-soft startup: each per-venue client is started independently.
        A failure to construct or start one venue does NOT prevent the
        others from running, and the monitor stays enabled as long as at
        least one venue is up. Each client has its own background
        reconnect loop, so a transient outage of one venue self-heals
        without operator intervention. The aggregator's ``get_intel``
        contract already returns ``None`` on missing/stale data, so the
        consumer side does not need to know which venues are alive.
        """
        from external.binance_perp_ws import BinancePerpTickerClient
        from external.bybit_perp_ws import BybitPerpTickerClient
        from external.okx_swap_ws import OkxSwapTickerClient
        from market_intel.cross_venue_aggregator import CrossVenueAggregator

        self._aggregator = CrossVenueAggregator()
        self._clients = []

        venue_factories = [
            ("binance_perp", BinancePerpTickerClient),
            ("bybit_perp",   BybitPerpTickerClient),
            ("okx_swap",     OkxSwapTickerClient),
        ]
        started = 0
        for name, factory in venue_factories:
            try:
                client = factory(self._aggregator)
                client.start()
            except Exception as e:
                # Fail-soft: log and continue with the remaining venues.
                # ``logger`` isn't configured for the console UI, so
                # surface to stderr where the operator can see it.
                print(
                    f"WARN: cross-venue {name} failed to start ({e!r}); "
                    "continuing with remaining venues.",
                    file=sys.stderr,
                )
                continue
            self._clients.append(client)
            started += 1

        if started == 0:
            # No venue came up — leave monitor disabled so the panel
            # renders the "feed disabled" row instead of an empty grid.
            self._enabled = False
            raise RuntimeError(
                "no external venue WS clients could be started"
            )
        self._enabled = True

    def stop(self) -> None:
        for client in self._clients:
            try:
                client.stop(timeout=2.0)
            except Exception:
                pass
        self._clients = []
        self._enabled = False

    def observe_coinbase_mids(self, mids: Dict[str, Optional[float]]) -> None:
        """Feed the latest Coinbase-side mid per product (from the
        dashboard ``market_metrics`` broadcast). Updates the rolling
        history for every configured product that has both a Coinbase
        mid and a fresh external consensus.

        Safe to call on every render tick — internal rate-limit gates
        actual history writes to ~1 Hz per product.
        """
        if not self._enabled or self._aggregator is None:
            return

        now = time.monotonic()
        with self._lock:
            for product_id in COINBASE_TO_EXTERNAL.keys():
                cb_mid = mids.get(product_id)
                if cb_mid is None:
                    continue
                try:
                    cb_mid_f = float(cb_mid)
                except (TypeError, ValueError):
                    continue
                if cb_mid_f <= 0:
                    continue

                last = self._last_sample_ts.get(product_id, 0.0)
                if (now - last) < _HISTORY_SAMPLE_INTERVAL_SECONDS:
                    continue

                intel = self._aggregator.get_intel(product_id, coinbase_mid=cb_mid_f)
                if (intel is None
                        or intel.consensus_mid is None
                        or intel.coinbase_premium_bps is None):
                    continue

                history = self._history.get(product_id)
                if history is None:
                    history = deque(maxlen=_HISTORY_MAXLEN)
                    self._history[product_id] = history
                history.append(
                    (now, cb_mid_f, intel.consensus_mid, intel.coinbase_premium_bps)
                )
                self._last_sample_ts[product_id] = now

    def snapshot(self, coinbase_mids: Dict[str, Optional[float]]) -> Dict[str, Dict[str, Any]]:
        """Render-ready dict keyed by Coinbase product id.

        Each entry contains coinbase_mid, external_mid, premium_dollars,
        premium_bps, fresh_venue_count, dispersion_bps, used_proxy,
        plus the rolling premium averages (avg_premium_bps_1m / _5m /
        _15m, each may be None when insufficient history exists).
        """
        if not self._enabled or self._aggregator is None:
            return {}

        out: Dict[str, Dict[str, Any]] = {}
        now = time.monotonic()
        with self._lock:
            for product_id in sorted(COINBASE_TO_EXTERNAL.keys()):
                cb_mid_raw = coinbase_mids.get(product_id)
                try:
                    cb_mid = float(cb_mid_raw) if cb_mid_raw is not None else None
                except (TypeError, ValueError):
                    cb_mid = None

                intel = self._aggregator.get_intel(product_id, coinbase_mid=cb_mid)
                if intel is None and cb_mid is None:
                    continue

                premium_dollars = None
                if (intel is not None
                        and intel.consensus_mid is not None
                        and cb_mid is not None):
                    premium_dollars = intel.consensus_mid - cb_mid

                history = self._history.get(product_id)
                # Per-venue mids surfaced for the side-by-side panel
                # view. Keys are ``Venue`` enum values so the renderer
                # can index them without a string-mapping dance.
                # Missing venues are simply absent from the dict (the
                # renderer treats absence as "—").
                venue_mids = dict(intel.venue_mids) if intel else {}
                out[product_id] = {
                    "coinbase_mid": cb_mid,
                    "external_mid": intel.consensus_mid if intel else None,
                    "venue_mids": venue_mids,
                    "premium_dollars": premium_dollars,
                    "premium_bps": intel.coinbase_premium_bps if intel else None,
                    "fresh_venue_count": intel.fresh_venue_count if intel else 0,
                    "dispersion_bps": intel.cross_venue_dispersion_bps if intel else None,
                    "used_proxy": intel.used_proxy if intel else False,
                    "avg_premium_bps_1m":  self._window_avg(history, now, 60.0),
                    "avg_premium_bps_5m":  self._window_avg(history, now, 300.0),
                    "avg_premium_bps_15m": self._window_avg(history, now, 900.0),
                    "sample_count": len(history) if history else 0,
                }
        return out

    @staticmethod
    def _window_avg(
        history: Optional[Deque[Tuple[float, float, float, float]]],
        now: float,
        window_seconds: float,
    ) -> Optional[float]:
        if not history:
            return None
        cutoff = now - window_seconds
        running_sum = 0.0
        n = 0
        for ts, _cb, _ext, premium_bps in history:
            if ts < cutoff:
                continue
            running_sum += premium_bps
            n += 1
        if n == 0:
            return None
        return running_sum / n


# Order in which per-venue columns are rendered. Stable so operators
# can trust column position across renders. Add new venues to the end
# rather than re-ordering, to preserve muscle memory.
_PANEL_VENUE_ORDER: Tuple[Venue, ...] = (
    Venue.BINANCE_PERP,
    Venue.BYBIT_PERP,
    Venue.OKX_SWAP,
)
_PANEL_VENUE_LABELS: Dict[Venue, str] = {
    Venue.BINANCE_PERP: "Binance",
    Venue.BYBIT_PERP:   "Bybit",
    Venue.OKX_SWAP:     "OKX",
}


def render_cross_venue_panel(snapshot: Dict[str, Dict[str, Any]], enabled: bool) -> Panel:
    """Render the Coinbase-perp-vs-world monitor panel.

    Per-venue mids are shown side-by-side with the aggregated
    consensus (median) so the operator can eyeball venue agreement
    and spot a single-venue outlier without leaving the console.
    """
    table = Table(expand=True, show_lines=False, header_style="bold cyan")
    table.add_column("product", width=18)
    table.add_column("CB mid", justify="right", width=12)
    for venue in _PANEL_VENUE_ORDER:
        table.add_column(_PANEL_VENUE_LABELS[venue], justify="right", width=11)
    table.add_column("consensus", justify="right", width=12)
    table.add_column("prem $", justify="right", width=10)
    table.add_column("bps", justify="right", width=8)
    table.add_column("1m avg", justify="right", width=8)
    table.add_column("5m avg", justify="right", width=8)
    table.add_column("15m avg", justify="right", width=8)
    table.add_column("venues", justify="right", width=6)

    # Total column count drives the placeholder rows below; recompute
    # so adding a venue here doesn't silently break the empty-state
    # rendering.
    _empty_cells = [""] * (len(_PANEL_VENUE_ORDER) + 9)

    if not enabled:
        table.add_row("—", "cross-venue feed disabled (--no-cross-venue)",
                      *_empty_cells)
        return Panel(table, title="Cross-Venue (Coinbase perp vs world)",
                     border_style="cyan", padding=(0, 1))

    if not snapshot:
        table.add_row("—", "waiting for first ticks…", *_empty_cells)
        return Panel(table, title="Cross-Venue (Coinbase perp vs world)",
                     border_style="cyan", padding=(0, 1))

    def _fmt_signed(v, digits: int) -> Text:
        if v is None:
            return Text("—", style="dim")
        try:
            f = float(v)
        except (TypeError, ValueError):
            return Text("—", style="dim")
        style = "green" if f > 0 else ("red" if f < 0 else "white")
        return Text(f"{f:+.{digits}f}", style=style)

    for product_id, entry in snapshot.items():
        venues = entry.get("fresh_venue_count") or 0
        venues_str = (
            f"{venues}*" if entry.get("used_proxy") else str(venues)
        )
        venue_mids = entry.get("venue_mids") or {}
        per_venue_cells = [
            fmt_num(venue_mids.get(v), 2) for v in _PANEL_VENUE_ORDER
        ]
        table.add_row(
            product_id,
            fmt_num(entry.get("coinbase_mid"), 2),
            *per_venue_cells,
            fmt_num(entry.get("external_mid"), 2),
            _fmt_signed(entry.get("premium_dollars"), 2),
            _fmt_signed(entry.get("premium_bps"), 2),
            _fmt_signed(entry.get("avg_premium_bps_1m"), 2),
            _fmt_signed(entry.get("avg_premium_bps_5m"), 2),
            _fmt_signed(entry.get("avg_premium_bps_15m"), 2),
            venues_str,
        )

    return Panel(
        table,
        title=f"Cross-Venue (Coinbase perp vs world) — {len(snapshot)} product(s)",
        border_style="cyan", padding=(0, 1),
    )


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


def build_layout(state: Dict[str, Any], status_text: str, cross_venue_snapshot: Dict[str, Dict[str, Any]], cross_venue_enabled: bool) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="engine", size=5),
        Layout(name="metrics", ratio=2),
        Layout(name="cross_venue", size=8),
        Layout(name="stealth", ratio=2),
        Layout(name="logs", ratio=1),
        Layout(name="status", size=1),
    )
    layout["engine"].update(render_engine_panel(state.get("engine_status") or {}))
    layout["metrics"].update(render_market_metrics_panel(state.get("market_metrics") or {}))
    layout["cross_venue"].update(
        render_cross_venue_panel(cross_venue_snapshot, cross_venue_enabled)
    )
    layout["stealth"].update(render_stealth_panel(state.get("stealth_orders") or {}))
    layout["logs"].update(render_logs_panel(state.get("logs") or []))
    layout["status"].update(Text(status_text, style="dim"))
    return layout


async def run(host: str, port: int, monitor: Optional["CrossVenueMonitor"]) -> None:
    """Connect to the dashboard WS and render forever, reconnecting as needed.

    ``monitor`` may be ``None`` when --no-cross-venue is set; the panel
    then renders a single 'feed disabled' row.
    """
    console = Console()
    state: Dict[str, Any] = {}
    url = f"ws://{host}:{port}"
    cross_venue_enabled = monitor is not None

    def _coinbase_mids_from_state() -> Dict[str, Optional[float]]:
        # Producer/consumer contract: market_metrics broadcast carries
        # the latest Coinbase mid as ``price`` on each product entry.
        # See business/market_metrics.py::MarketMetricsTracker.snapshot.
        result: Dict[str, Optional[float]] = {}
        for pid, entry in (state.get("market_metrics") or {}).items():
            if isinstance(entry, dict):
                result[pid] = entry.get("price")
        return result

    def _cross_venue_snapshot() -> Dict[str, Dict[str, Any]]:
        if monitor is None:
            return {}
        mids = _coinbase_mids_from_state()
        monitor.observe_coinbase_mids(mids)
        return monitor.snapshot(mids)

    with Live(build_layout(state, f"connecting to {url}…",
                           _cross_venue_snapshot(), cross_venue_enabled),
              console=console, screen=True, refresh_per_second=4) as live:

        while True:
            try:
                async with websockets.connect(url, max_size=8 * 1024 * 1024) as ws:
                    live.update(build_layout(
                        state, f"connected • {url}",
                        _cross_venue_snapshot(), cross_venue_enabled,
                    ))

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
                        live.update(build_layout(
                            state, f"connected • {url} • {ts}",
                            _cross_venue_snapshot(), cross_venue_enabled,
                        ))

            except (OSError, websockets.exceptions.WebSocketException) as e:
                live.update(build_layout(
                    state,
                    f"disconnected ({type(e).__name__}: {e}) • retrying in 2s…",
                    _cross_venue_snapshot(), cross_venue_enabled,
                ))
                await asyncio.sleep(2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Console UI for the trading engine.")
    parser.add_argument("--host", default="localhost",
                        help="Dashboard WebSocket host (default: localhost)")
    parser.add_argument("--port", type=int, default=8765,
                        help="Dashboard WebSocket port (default: 8765)")
    parser.add_argument("--no-cross-venue", action="store_true",
                        help=("Disable the Binance perp WS feed and the "
                              "Cross-Venue panel. Useful for offline use "
                              "or when running on a host without outbound "
                              "internet access."))
    args = parser.parse_args()

    monitor: Optional[CrossVenueMonitor] = None
    if not args.no_cross_venue:
        monitor = CrossVenueMonitor()
        try:
            monitor.start()
        except Exception as e:
            # Don't let an external-feed problem kill the dashboard
            # view — fall back to disabled state and continue.
            print(f"WARN: cross-venue monitor failed to start ({e!r}); "
                  "continuing with feed disabled.", file=sys.stderr)
            monitor = None

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
        asyncio.run(run(args.host, args.port, monitor))
    except KeyboardInterrupt:
        return 0
    finally:
        if monitor is not None:
            monitor.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
