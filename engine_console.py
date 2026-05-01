"""Read-only ``top``-style console for the trading engine.

Connects to the running ``dashboard_server`` over ws://localhost:8765
and renders the live engine state with key-driven filters. Maintains
its own large in-process ring buffer of every log/event observed
since startup, so the visible scrollback is independent of the
dashboard server's small ``max_logs`` retention (currently 100).

This is a pure consumer — it places no orders, mutates no state,
sends no control messages back to the engine. Ctrl-C / 'q' exits
cleanly via prompt_toolkit's built-in SIGINT handler (avoids the
Windows console-signal pitfall noted in
``/memories/windows-signal-event-wait.md``).

Usage::

    python engine_console.py
    python engine_console.py --url ws://localhost:8765
    python engine_console.py --buffer-size 50000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

import websockets
from prompt_toolkit import Application
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension as D
from prompt_toolkit.styles import Style


# ---------------------------------------------------------------------------
# Filter state — pure data, easy to unit-test
# ---------------------------------------------------------------------------

LOG_LEVELS: Tuple[str, ...] = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
LEVEL_RANK: Dict[str, int] = {lvl: i for i, lvl in enumerate(LOG_LEVELS)}


@dataclass
class FilterState:
    """User-controlled filters applied at render time only.

    Never mutates source-of-truth state; every field here is consulted
    by the renderer when composing the visible view from the ring buffer
    and the latest snapshot.
    """

    product_filter: Optional[str] = None       # substring; None == all
    min_level: str = "INFO"                    # min log level (rank-based)
    event_excludes: Set[str] = field(default_factory=set)  # event names to hide
    search_substring: Optional[str] = None     # case-insensitive log search
    sort_stealth_by: str = "created"           # created | size | status
    show_orders: bool = True
    show_stealth: bool = True
    show_positions: bool = True
    paused: bool = False                       # freeze auto-scroll

    def reset(self) -> None:
        self.product_filter = None
        self.min_level = "INFO"
        self.event_excludes.clear()
        self.search_substring = None
        self.sort_stealth_by = "created"
        self.show_orders = True
        self.show_stealth = True
        self.show_positions = True
        self.paused = False

    def log_passes(self, level: str, message: str, context: Dict[str, Any]) -> bool:
        """True iff a log entry should be visible under the current filters."""
        if LEVEL_RANK.get(level.upper(), 0) < LEVEL_RANK.get(self.min_level, 0):
            return False
        # Event-name filter pulls from context["event"] if present; falls
        # back to the first whitespace-delimited token of the message.
        event_name = (context or {}).get("event")
        if not event_name:
            event_name = message.split(" ", 1)[0] if message else ""
        if event_name in self.event_excludes:
            return False
        if self.product_filter:
            haystack = message
            ctx_pid = (context or {}).get("product_id")
            if ctx_pid:
                haystack = f"{haystack} {ctx_pid}"
            if self.product_filter.lower() not in haystack.lower():
                return False
        if self.search_substring:
            if self.search_substring.lower() not in message.lower():
                return False
        return True


# ---------------------------------------------------------------------------
# Snapshot store — overwritten on each WS state_update
# ---------------------------------------------------------------------------

@dataclass
class Snapshot:
    connected: bool = False
    last_update_iso: Optional[str] = None
    engine_status: Dict[str, Any] = field(default_factory=dict)
    orders: Dict[str, Any] = field(default_factory=dict)
    positions: Dict[str, Any] = field(default_factory=dict)
    stealth_orders: Dict[str, Any] = field(default_factory=dict)
    seen_event_names: Set[str] = field(default_factory=set)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Renderer — pure composition of (Snapshot, Buffer, FilterState) → text
# ---------------------------------------------------------------------------


def _truncate(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    if n <= 1:
        return s[:n]
    return s[: n - 1] + "…"


def render_header(snapshot: Snapshot, url: str) -> FormattedText:
    conn = ("class:ok", "✓ connected") if snapshot.connected else ("class:err", "✗ disconnected")
    es = snapshot.engine_status or {}
    running = es.get("running")
    running_txt = "RUNNING" if running else "STOPPED" if running is False else "?"
    fee = es.get("effective_fee_rate")
    fee_txt = f"fee={fee*1e4:.2f}bps" if isinstance(fee, (int, float)) else "fee=?"
    queue = es.get("event_queue_depth", "?")
    threads = es.get("threads_active", "?")
    margin = es.get("margin_window_type") or "?"
    now = datetime.utcnow().strftime("%H:%M:%S")
    return FormattedText([
        ("class:title", " engine_console "),
        ("", "  "),
        ("class:dim", url + "  "),
        conn,
        ("class:dim", f"   utc={now}\n"),
        ("class:label", " Engine: "),
        ("class:value", f"{running_txt}"),
        ("class:dim", f"   threads={threads}  queue={queue}  {fee_txt}  margin={margin}"),
        ("", "\n"),
    ])


def render_positions(snapshot: Snapshot, fs: FilterState, width: int) -> FormattedText:
    if not fs.show_positions:
        return FormattedText([("class:dim", " (positions hidden — press 'P' to show)\n")])
    rows: List[Tuple[str, Any]] = []
    rows.append(("class:section", " POSITIONS\n"))
    if not snapshot.positions:
        rows.append(("class:dim", "   (none)\n"))
        return FormattedText(rows)
    rows.append(("class:thead", f"   {'product':<22}{'side':<8}{'qty':>10}{'avg_price':>14}{'unrealized':>14}\n"))
    for pid, pos in sorted(snapshot.positions.items()):
        if fs.product_filter and fs.product_filter.lower() not in pid.lower():
            continue
        side = str(pos.get("side") or pos.get("position_side") or "?")
        qty = pos.get("quantity") or pos.get("size") or 0
        avg = pos.get("avg_price") or pos.get("average_price") or 0
        upl = pos.get("unrealized_pnl") or pos.get("unrealized") or 0
        try:
            qty_s = f"{float(qty):>10.4f}"
        except (TypeError, ValueError):
            qty_s = f"{str(qty):>10}"
        try:
            avg_s = f"{float(avg):>14.4f}"
        except (TypeError, ValueError):
            avg_s = f"{str(avg):>14}"
        try:
            upl_s = f"{float(upl):>+14.2f}"
        except (TypeError, ValueError):
            upl_s = f"{str(upl):>14}"
        rows.append(("", f"   {_truncate(pid, 22):<22}{side:<8}{qty_s}{avg_s}{upl_s}\n"))
    return FormattedText(rows)


def render_stealth_orders(snapshot: Snapshot, fs: FilterState, width: int) -> FormattedText:
    if not fs.show_stealth:
        return FormattedText([("class:dim", " (stealth orders hidden — press 'S' to show)\n")])
    rows: List[Tuple[str, Any]] = []
    rows.append(("class:section", f" STEALTH ORDERS                                  [s] sort={fs.sort_stealth_by}\n"))
    items = list(snapshot.stealth_orders.items())
    if not items:
        rows.append(("class:dim", "   (none)\n"))
        return FormattedText(rows)
    if fs.sort_stealth_by == "size":
        items.sort(key=lambda kv: float(kv[1].get("total_size") or kv[1].get("size") or 0), reverse=True)
    elif fs.sort_stealth_by == "status":
        items.sort(key=lambda kv: str(kv[1].get("status") or ""))
    else:
        items.sort(key=lambda kv: str(kv[1].get("created_at") or kv[1].get("updated_at") or ""))
    rows.append(("class:thead", f"   {'stealth_id':<12}{'product':<20}{'side':<6}{'size':>10}  {'policy':<22}{'status':<10}\n"))
    shown = 0
    for sid, so in items:
        pid = str(so.get("product_id") or "")
        if fs.product_filter and fs.product_filter.lower() not in pid.lower():
            continue
        side = str(so.get("side") or "")
        size = so.get("total_size") or so.get("size") or 0
        policy = str(so.get("placement_type") or so.get("reveal_pricing_policy") or "")
        status = str(so.get("status") or "")
        try:
            size_s = f"{float(size):>10.4f}"
        except (TypeError, ValueError):
            size_s = f"{str(size):>10}"
        rows.append((
            "",
            f"   {_truncate(sid, 12):<12}{_truncate(pid, 20):<20}{side:<6}{size_s}  "
            f"{_truncate(policy, 22):<22}{_truncate(status, 10):<10}\n",
        ))
        shown += 1
        if shown >= 12:
            rows.append(("class:dim", f"   … {len(items) - shown} more (filtered out / truncated)\n"))
            break
    return FormattedText(rows)


def render_logs(
    buffer: Deque[Dict[str, Any]],
    fs: FilterState,
    width: int,
    height: int,
) -> FormattedText:
    rows: List[Tuple[str, Any]] = []
    filt_bits: List[str] = []
    if fs.product_filter:
        filt_bits.append(f"product={fs.product_filter}")
    filt_bits.append(f"level≥{fs.min_level}")
    if fs.event_excludes:
        filt_bits.append(f"hide={len(fs.event_excludes)}")
    if fs.search_substring:
        filt_bits.append(f"search={fs.search_substring!r}")
    filt_bits.append("PAUSED" if fs.paused else "live")
    visible: List[Dict[str, Any]] = [
        e for e in buffer
        if fs.log_passes(e.get("level", "INFO"), e.get("message", ""), e.get("context") or {})
    ]
    rows.append((
        "class:section",
        f" LOGS ({' '.join(filt_bits)})    [{len(visible)}/{len(buffer)} buffered]\n",
    ))
    # Show the tail that fits
    tail = visible[-height:] if height > 0 else visible
    for e in tail:
        ts = e.get("timestamp", "")[11:19]
        lvl = e.get("level", "INFO").upper()
        msg = e.get("message", "")
        style = {
            "ERROR": "class:err",
            "CRITICAL": "class:err",
            "WARNING": "class:warn",
            "INFO": "",
            "DEBUG": "class:dim",
        }.get(lvl, "")
        line = f" {ts} [{lvl:<5}] {msg}\n"
        rows.append((style, _truncate(line, width)))
        if not line.endswith("\n"):
            rows.append((style, "\n"))
    return FormattedText(rows)


def render_footer(fs: FilterState) -> FormattedText:
    return FormattedText([
        ("class:footer",
         " [f] product  [l] level  [e] hide-event  [/] search  [s] sort  "
         "[O/S/P] toggle sections  [p] pause  [r] reset  [?] help  [q] quit\n"),
    ])


# ---------------------------------------------------------------------------
# WebSocket consumer
# ---------------------------------------------------------------------------


async def ws_consumer(
    url: str,
    snapshot: Snapshot,
    buffer: Deque[Dict[str, Any]],
    invalidate: Any,
) -> None:
    """Long-lived consumer: connect, ingest state_update, redraw."""
    last_log_signature: Optional[str] = None
    seen_log_keys: Set[str] = set()
    backoff = 1.0
    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                snapshot.connected = True
                snapshot.error = None
                backoff = 1.0
                invalidate()
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("type") != "state_update":
                        continue
                    data = msg.get("data") or {}
                    snapshot.last_update_iso = msg.get("timestamp")
                    snapshot.engine_status = data.get("engine_status") or {}
                    snapshot.orders = data.get("orders") or {}
                    snapshot.positions = data.get("positions") or {}
                    snapshot.stealth_orders = data.get("stealth_orders") or {}
                    # Logs: dedup against what we've already buffered. The
                    # server keeps only ~100 entries; we keep the union of
                    # everything we've ever seen this session.
                    for entry in data.get("logs") or []:
                        key = (
                            f"{entry.get('timestamp')}|{entry.get('level')}|"
                            f"{entry.get('message')}"
                        )
                        if key in seen_log_keys:
                            continue
                        seen_log_keys.add(key)
                        buffer.append(entry)
                        # Track event names for the [e] picker
                        ctx = entry.get("context") or {}
                        ev = ctx.get("event") or (entry.get("message", "").split(" ", 1)[0])
                        if ev:
                            snapshot.seen_event_names.add(ev)
                    invalidate()
        except (OSError, websockets.exceptions.WebSocketException) as e:
            snapshot.connected = False
            snapshot.error = str(e)
            invalidate()
            await asyncio.sleep(min(backoff, 10.0))
            backoff = min(backoff * 1.5, 10.0)


# ---------------------------------------------------------------------------
# Application wiring
# ---------------------------------------------------------------------------


# Free-text input mode — when set, key handler routes chars into the buffer.
@dataclass
class InputPrompt:
    label: str = ""
    buffer: str = ""
    on_submit: Any = None  # Callable[[str], None]
    active: bool = False

    def start(self, label: str, on_submit) -> None:
        self.label = label
        self.buffer = ""
        self.on_submit = on_submit
        self.active = True

    def cancel(self) -> None:
        self.active = False
        self.label = ""
        self.buffer = ""
        self.on_submit = None

    def submit(self) -> None:
        cb, val = self.on_submit, self.buffer
        self.cancel()
        if cb is not None:
            cb(val)


def build_application(url: str, buffer_size: int) -> Application:
    snapshot = Snapshot()
    buffer: Deque[Dict[str, Any]] = deque(maxlen=buffer_size)
    fs = FilterState()
    prompt = InputPrompt()

    # ----- text controls -----
    def get_header_text():
        return render_header(snapshot, url)

    def get_main_text():
        # Width is approximate; FormattedTextControl wraps as needed.
        width = 120
        chunks: List[Tuple[str, str]] = []
        chunks.extend(render_positions(snapshot, fs, width))
        chunks.extend(render_stealth_orders(snapshot, fs, width))
        # Logs get whatever vertical room is left; we approximate with 30.
        chunks.extend(render_logs(buffer, fs, width, height=30))
        return FormattedText(chunks)

    def get_footer_text():
        if prompt.active:
            return FormattedText([
                ("class:prompt", f" {prompt.label}: {prompt.buffer}_  (Enter=apply, Esc=cancel)\n"),
            ])
        return render_footer(fs)

    header_ctrl = FormattedTextControl(text=get_header_text)
    main_ctrl = FormattedTextControl(text=get_main_text)
    footer_ctrl = FormattedTextControl(text=get_footer_text)

    layout = Layout(HSplit([
        Window(content=header_ctrl, height=D.exact(2), style="class:header"),
        Window(content=main_ctrl, wrap_lines=False),
        Window(content=footer_ctrl, height=D.exact(1), style="class:footerbar"),
    ]))

    # ----- key bindings -----
    kb = KeyBindings()

    @kb.add("c-c")
    @kb.add("q")
    def _(event):
        if prompt.active:
            return
        event.app.exit()

    @kb.add("?")
    def _(event):
        if prompt.active:
            return
        # Toggle by stuffing help into search; cleaner: dedicated overlay.
        # Keeping this MVP-simple: dump key map into the log buffer.
        buffer.append({
            "timestamp": datetime.utcnow().isoformat(),
            "level": "INFO",
            "message": "[help] f=product l=level e=hide-event /=search s=sort O/S/P=toggle p=pause r=reset q=quit",
            "context": {"event": "_help"},
        })
        event.app.invalidate()

    # ----- filter keys (only when no prompt active) -----
    def _guard(handler):
        def wrapped(event):
            if prompt.active:
                return
            handler(event)
        return wrapped

    @kb.add("f")
    def _(event):
        if prompt.active:
            return
        def apply(val: str):
            fs.product_filter = val.strip() or None
            event.app.invalidate()
        prompt.start("filter product (substring; empty=all)", apply)
        event.app.invalidate()

    @kb.add("l")
    @_guard
    def _(event):
        idx = LOG_LEVELS.index(fs.min_level) if fs.min_level in LOG_LEVELS else 1
        fs.min_level = LOG_LEVELS[(idx + 1) % len(LOG_LEVELS)]
        event.app.invalidate()

    @kb.add("e")
    def _(event):
        if prompt.active:
            return
        def apply(val: str):
            v = val.strip()
            if not v:
                fs.event_excludes.clear()
            elif v in fs.event_excludes:
                fs.event_excludes.discard(v)
            else:
                fs.event_excludes.add(v)
            event.app.invalidate()
        seen = ", ".join(sorted(snapshot.seen_event_names)[:10]) or "(none yet)"
        prompt.start(f"hide event-name (toggle; empty=clear all). seen: {seen}", apply)
        event.app.invalidate()

    @kb.add("/")
    def _(event):
        if prompt.active:
            return
        def apply(val: str):
            fs.search_substring = val.strip() or None
            event.app.invalidate()
        prompt.start("search log substring (empty=clear)", apply)
        event.app.invalidate()

    @kb.add("s")
    @_guard
    def _(event):
        order = ("created", "size", "status")
        idx = order.index(fs.sort_stealth_by) if fs.sort_stealth_by in order else 0
        fs.sort_stealth_by = order[(idx + 1) % len(order)]
        event.app.invalidate()

    @kb.add("O")
    @_guard
    def _(event):
        fs.show_orders = not fs.show_orders
        event.app.invalidate()

    @kb.add("S")
    @_guard
    def _(event):
        fs.show_stealth = not fs.show_stealth
        event.app.invalidate()

    @kb.add("P")
    @_guard
    def _(event):
        fs.show_positions = not fs.show_positions
        event.app.invalidate()

    @kb.add("p")
    @_guard
    def _(event):
        fs.paused = not fs.paused
        event.app.invalidate()

    @kb.add("r")
    @_guard
    def _(event):
        fs.reset()
        event.app.invalidate()

    # ----- prompt-mode keys -----
    @kb.add("enter")
    def _(event):
        if prompt.active:
            prompt.submit()
            event.app.invalidate()

    @kb.add("escape", eager=True)
    def _(event):
        if prompt.active:
            prompt.cancel()
            event.app.invalidate()

    @kb.add("backspace")
    def _(event):
        if prompt.active and prompt.buffer:
            prompt.buffer = prompt.buffer[:-1]
            event.app.invalidate()

    @kb.add("<any>")
    def _(event):
        if not prompt.active:
            return
        ch = event.data
        if ch and ch.isprintable():
            prompt.buffer += ch
            event.app.invalidate()

    style = Style.from_dict({
        "header": "bg:#222244 #ffffff",
        "footerbar": "bg:#444444 #dddddd",
        "title": "bold #ffff88",
        "label": "bold",
        "value": "#88ff88",
        "section": "bold #88ccff",
        "thead": "italic #aaaaaa",
        "ok": "#88ff88",
        "err": "#ff5555",
        "warn": "#ffaa55",
        "dim": "#888888",
        "footer": "#cccccc",
        "prompt": "bg:#222266 #ffffff",
    })

    app = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=True,
        style=style,
        refresh_interval=0.5,
    )

    # Stash the consumer task so the main entry point can launch it.
    app._engine_console_url = url           # type: ignore[attr-defined]
    app._engine_console_snapshot = snapshot  # type: ignore[attr-defined]
    app._engine_console_buffer = buffer      # type: ignore[attr-defined]
    return app


async def _run_async(url: str, buffer_size: int) -> None:
    app = build_application(url, buffer_size)
    snapshot: Snapshot = app._engine_console_snapshot           # type: ignore[attr-defined]
    buffer: Deque[Dict[str, Any]] = app._engine_console_buffer  # type: ignore[attr-defined]

    def invalidate() -> None:
        try:
            app.invalidate()
        except Exception:
            pass

    consumer = asyncio.create_task(ws_consumer(url, snapshot, buffer, invalidate))
    try:
        await app.run_async()
    finally:
        consumer.cancel()
        try:
            await consumer
        except (asyncio.CancelledError, Exception):
            pass


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only top-style console for the trading engine."
    )
    parser.add_argument("--url", default="ws://localhost:8765", help="Dashboard WS URL")
    parser.add_argument(
        "--buffer-size",
        type=int,
        default=20000,
        help="Max log entries kept in local ring buffer (default: 20000).",
    )
    args = parser.parse_args(argv)
    try:
        asyncio.run(_run_async(args.url, args.buffer_size))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
