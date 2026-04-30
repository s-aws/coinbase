"""Bybit v5 linear perpetual public ticker WebSocket client.

Phase-1 read-only consumer: subscribes to ``tickers.<SYMBOL>`` on
``stream.bybit.com/v5/public/linear``, parses each frame into a
``VenueTick``, and forwards it to a ``CrossVenueAggregator``.

No authentication required — these are public market-data streams.

Design notes
------------
- Mirrors the lifecycle and reconnect/backoff shape of
  ``BinancePerpTickerClient`` deliberately. Two near-identical
  implementations is acceptable; a base class will be extracted only
  after the third venue lands and the variation surface is visible
  (per duplicated-rule guidance).
- Bybit v5 ``tickers`` frames come in two ``type`` flavors:
    * ``snapshot`` — full payload (all fields populated)
    * ``delta``    — only changed fields populated
  We keep the latest known (bid, ask) per symbol and merge each
  delta on top, so consumers always see a fully-resolved tick.
- Ping handling: ``websockets.connect(ping_interval=20)`` sends WS
  protocol ping frames. Bybit also accepts an application-level
  ``{"op":"ping"}`` heartbeat, but the protocol ping suffices to
  keep the connection alive within the documented 20s idle window.
- No on-frame logging. Per-message tracing available via
  ``debug_callback`` for the Phase-1 measurement script.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Callable, Dict, Iterable, Optional, Tuple

import websockets
from websockets.exceptions import ConnectionClosed

from market_intel.cross_venue_aggregator import (
    CrossVenueAggregator,
    VenueTick,
)
from market_intel.venues import Venue, all_subscribed_symbols


logger = logging.getLogger(__name__)


# Public docs: https://bybit-exchange.github.io/docs/v5/websocket/public/ticker
_BYBIT_LINEAR_WS = "wss://stream.bybit.com/v5/public/linear"

# Backoff bounds for reconnect loop (mirrors Binance client).
_BACKOFF_INITIAL_SECONDS = 1.0
_BACKOFF_CAP_SECONDS = 30.0
_BACKOFF_RESET_SECONDS = 60.0


class BybitPerpTickerClient:
    """Background WS consumer for Bybit v5 linear perp tickers.

    Single-instance per process. Subscribes to every symbol returned
    by ``all_subscribed_symbols(Venue.BYBIT_PERP)``.
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
            else all_subscribed_symbols(Venue.BYBIT_PERP)
        )
        self._debug_callback = debug_callback

        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._shutdown = threading.Event()
        self._started = False

        # symbol -> (bid, ask). Cleared on every reconnect because a
        # fresh snapshot frame will arrive from the server before any
        # delta. Without the reset, a stale bid/ask from before the
        # disconnect could be merged with a delta from after.
        self._last_bid_ask: Dict[str, Tuple[float, float]] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background thread + asyncio loop. Idempotent."""
        if self._started:
            return
        if not self._symbols:
            logger.info(
                "bybit_perp_ticker: no symbols configured; not starting"
            )
            return
        self._started = True
        self._shutdown.clear()
        self._thread = threading.Thread(
            target=self._thread_main,
            name="bybit_perp_ticker",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "bybit_perp_ticker: started for %d symbol(s): %s",
            len(self._symbols), ", ".join(self._symbols),
        )

    def stop(self, timeout: float = 5.0) -> None:
        """Signal shutdown and wait briefly for the thread to exit."""
        if not self._started:
            return
        self._shutdown.set()
        loop = self._loop
        if loop is not None and loop.is_running():
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
            logger.exception("bybit_perp_ticker: thread crashed")
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
                # Drop stale per-symbol state; the new connection will
                # send a fresh snapshot before any delta.
                self._last_bid_ask.clear()
                connected_at = time.monotonic()
                await self._consume_once()
            except asyncio.CancelledError:
                return
            except ConnectionClosed as e:
                logger.warning(
                    "bybit_perp_ticker: connection closed (%s); reconnecting",
                    e,
                )
            except Exception:
                logger.exception(
                    "bybit_perp_ticker: consume loop error; reconnecting"
                )

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
        logger.info("bybit_perp_ticker: connecting to %s", _BYBIT_LINEAR_WS)
        async with websockets.connect(
            _BYBIT_LINEAR_WS,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=2,
            max_queue=1024,
        ) as ws:
            sub = {
                "op": "subscribe",
                "args": [f"tickers.{s}" for s in self._symbols],
            }
            await ws.send(json.dumps(sub))
            logger.info(
                "bybit_perp_ticker: connected; subscribed to %d topic(s)",
                len(self._symbols),
            )

            async for raw in ws:
                if self._shutdown.is_set():
                    return
                try:
                    self._handle_frame(raw)
                except Exception:
                    logger.exception(
                        "bybit_perp_ticker: frame handler error"
                    )

    def _handle_frame(self, raw: object) -> None:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="replace")
        if not isinstance(raw, str):
            return

        msg = json.loads(raw)
        if not isinstance(msg, dict):
            return

        # Subscribe-ack and ping responses don't carry a "topic"; ignore.
        topic = msg.get("topic")
        if not isinstance(topic, str) or not topic.startswith("tickers."):
            return

        data = msg.get("data")
        if not isinstance(data, dict):
            return

        symbol = data.get("symbol") or topic.split(".", 1)[1]
        if not isinstance(symbol, str) or not symbol:
            return

        # Merge delta on top of the last known (bid, ask) for the symbol.
        # Snapshot frames carry both fields; delta frames may carry one,
        # both, or neither (size-only updates have neither).
        prev = self._last_bid_ask.get(symbol)
        prev_bid = prev[0] if prev else None
        prev_ask = prev[1] if prev else None

        bid = self._parse_price(data.get("bid1Price"), prev_bid)
        ask = self._parse_price(data.get("ask1Price"), prev_ask)

        if bid is None or ask is None:
            # Insufficient state to emit a tick yet; wait for the next
            # frame that fills in the missing side.
            return
        if bid <= 0 or ask <= 0 or ask < bid:
            return

        self._last_bid_ask[symbol] = (bid, ask)

        tick = VenueTick(
            venue=Venue.BYBIT_PERP,
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
                    "bybit_perp_ticker: debug_callback raised"
                )

    @staticmethod
    def _parse_price(value: object, fallback: Optional[float]) -> Optional[float]:
        """Parse a Bybit price string. Empty / missing → fallback
        (used to carry forward the previous side on a delta that
        only updated the opposite side)."""
        if value is None or value == "":
            return fallback
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback
