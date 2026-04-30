"""Binance USDT-M perpetual public ticker WebSocket client.

Phase-1 read-only consumer: subscribes to ``<symbol>@bookTicker``
combined streams on ``fstream.binance.com``, parses each frame
into a ``VenueTick``, and forwards it to a ``CrossVenueAggregator``.

No authentication required — these are public market-data streams.

Design notes
------------
- Uses the ``websockets`` async library (already a project dep).
- Runs in its own daemon thread with its own asyncio loop, started
  by ``start()`` and stopped by ``stop()``. Mirrors the lifecycle
  shape of the existing engine background threads.
- Reconnects with exponential backoff on any disconnect / parse
  error. Binance documents a server-side disconnect at the 24h
  mark; this loop handles it transparently.
- Bounded outbound side effect: the only thing we touch on a hot
  message is ``aggregator.record_tick``. Anything heavier (logging
  per-frame, DB writes) would saturate at >100 msg/s/symbol.
- No on-frame logging. We log connection lifecycle events only.
  Per-message tracing is available via ``debug_callback`` for the
  Phase-1 measurement script.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Callable, Iterable, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from market_intel.cross_venue_aggregator import (
    CrossVenueAggregator,
    VenueTick,
)
from market_intel.venues import Venue, all_subscribed_symbols


logger = logging.getLogger(__name__)


# Public docs: https://binance-docs.github.io/apidocs/futures/en/#websocket-market-streams
# Combined stream form: wss://fstream.binance.com/stream?streams=btcusdt@bookTicker/ethusdt@bookTicker
_BINANCE_FSTREAM_BASE = "wss://fstream.binance.com/stream"

# Backoff bounds for reconnect loop. First retry is immediate; then
# 1s, 2s, 4s, 8s, capped at _BACKOFF_CAP_SECONDS. Resets to 0 after
# any successful connect that stays up >_BACKOFF_RESET_SECONDS.
_BACKOFF_INITIAL_SECONDS = 1.0
_BACKOFF_CAP_SECONDS = 30.0
_BACKOFF_RESET_SECONDS = 60.0


class BinancePerpTickerClient:
    """Background WS consumer for Binance USDT-M perp bookTicker.

    Single-instance per process. Subscribes to every symbol returned
    by ``all_subscribed_symbols(Venue.BINANCE_PERP)`` (driven by
    ``market_intel.venues.COINBASE_TO_EXTERNAL``) so adding new
    Coinbase products to the mapping table automatically extends
    the subscription on next restart.
    """

    def __init__(
        self,
        aggregator: CrossVenueAggregator,
        *,
        symbols: Optional[Iterable[str]] = None,
        debug_callback: Optional[Callable[[dict], None]] = None,
    ):
        self._aggregator = aggregator
        self._symbols = tuple(
            symbols if symbols is not None
            else all_subscribed_symbols(Venue.BINANCE_PERP)
        )
        self._debug_callback = debug_callback

        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._shutdown = threading.Event()
        self._started = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background thread + asyncio loop. Idempotent."""
        if self._started:
            return
        if not self._symbols:
            logger.info(
                "binance_perp_ticker: no symbols configured; not starting"
            )
            return
        self._started = True
        self._shutdown.clear()
        self._thread = threading.Thread(
            target=self._thread_main,
            name="binance_perp_ticker",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "binance_perp_ticker: started for %d symbol(s): %s",
            len(self._symbols), ", ".join(self._symbols),
        )

    def stop(self, timeout: float = 5.0) -> None:
        """Signal shutdown and wait briefly for the thread to exit."""
        if not self._started:
            return
        self._shutdown.set()
        loop = self._loop
        if loop is not None and loop.is_running():
            # Wake any in-flight ``recv()`` by closing the loop
            # asynchronously. The recv loop catches CancelledError
            # and returns cleanly.
            try:
                asyncio.run_coroutine_threadsafe(
                    self._cancel_all_tasks(), loop,
                )
            except RuntimeError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._started = False

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._run_forever())
        except Exception:
            logger.exception("binance_perp_ticker: thread crashed")
        finally:
            try:
                loop.close()
            except Exception:
                pass
            self._loop = None

    async def _cancel_all_tasks(self) -> None:
        for task in asyncio.all_tasks(loop=asyncio.get_event_loop()):
            if task is not asyncio.current_task():
                task.cancel()

    async def _run_forever(self) -> None:
        backoff = 0.0
        while not self._shutdown.is_set():
            connected_at: Optional[float] = None
            try:
                if backoff > 0:
                    await asyncio.sleep(backoff)
                connected_at = time.monotonic()
                await self._consume_once()
            except asyncio.CancelledError:
                return
            except ConnectionClosed as e:
                logger.warning(
                    "binance_perp_ticker: connection closed (%s); reconnecting",
                    e,
                )
            except Exception:
                logger.exception(
                    "binance_perp_ticker: consume loop error; reconnecting"
                )

            # Reset backoff if we held a connection long enough that
            # the disconnect probably wasn't symptomatic of a hard
            # failure (rate-limit, bad URL, etc.).
            uptime = (
                time.monotonic() - connected_at
                if connected_at is not None else 0.0
            )
            if uptime > _BACKOFF_RESET_SECONDS:
                backoff = _BACKOFF_INITIAL_SECONDS
            else:
                backoff = min(
                    max(backoff * 2.0, _BACKOFF_INITIAL_SECONDS),
                    _BACKOFF_CAP_SECONDS,
                )

    async def _consume_once(self) -> None:
        url = self._build_url()
        logger.info("binance_perp_ticker: connecting to %s", url)
        async with websockets.connect(
            url,
            ping_interval=20,    # Binance closes idle conns; keep alive
            ping_timeout=20,
            close_timeout=2,
            max_queue=1024,
        ) as ws:
            logger.info("binance_perp_ticker: connected")
            async for raw in ws:
                if self._shutdown.is_set():
                    return
                try:
                    self._handle_frame(raw)
                except Exception:
                    logger.exception(
                        "binance_perp_ticker: frame handler error"
                    )

    def _build_url(self) -> str:
        # Binance combined-stream URL form. Symbols must be lowercase
        # in the path; the payload echoes them in lowercase too.
        streams = "/".join(f"{s.lower()}@bookTicker" for s in self._symbols)
        return f"{_BINANCE_FSTREAM_BASE}?streams={streams}"

    def _handle_frame(self, raw: object) -> None:
        # ``websockets`` yields str for text frames; the combined-
        # stream wraps each event in {"stream": "...", "data": {...}}.
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="replace")
        if not isinstance(raw, str):
            return

        msg = json.loads(raw)
        data = msg.get("data") if isinstance(msg, dict) else None
        if not isinstance(data, dict):
            return

        # bookTicker payload (futures):
        #   {"e":"bookTicker","u":...,"s":"BTCUSDT","b":"...","B":"...",
        #    "a":"...","A":"...","T":...,"E":...}
        symbol = data.get("s")
        bid_str = data.get("b")
        ask_str = data.get("a")
        if not symbol or bid_str is None or ask_str is None:
            return

        try:
            bid = float(bid_str)
            ask = float(ask_str)
        except (TypeError, ValueError):
            return
        if bid <= 0 or ask <= 0 or ask < bid:
            return

        tick = VenueTick(
            venue=Venue.BINANCE_PERP,
            symbol=symbol,
            bid=bid,
            ask=ask,
            recv_monotonic=time.monotonic(),
        )
        self._aggregator.record_tick(tick)

        if self._debug_callback is not None:
            try:
                self._debug_callback(data)
            except Exception:
                logger.exception(
                    "binance_perp_ticker: debug_callback raised"
                )
