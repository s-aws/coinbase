"""OKX v5 SWAP public ticker WebSocket client.

Phase-1 read-only consumer: subscribes to the ``tickers`` channel
on ``ws.okx.com:8443/ws/v5/public`` for every configured swap
``instId``, parses each frame into a ``VenueTick``, and forwards
it to a ``CrossVenueAggregator``.

No authentication required — these are public market-data streams.

Design notes
------------
- Mirrors the lifecycle and reconnect/backoff shape of the Binance
  and Bybit clients deliberately. A base class will be extracted
  only after this third venue lands and the variation surface is
  visible (per duplicated-rule guidance).
- OKX v5 keepalive: the server expects ANY message within 30s or
  it closes the socket. ``websockets.connect(ping_interval=20)``
  emits WS protocol pings, but OKX docs explicitly call for an
  application-level text ``"ping"`` (server replies with text
  ``"pong"``). We send the text ping every 20s as a background
  task; the WS protocol ping is left enabled as belt-and-braces.
- OKX ``tickers`` payload uses ``bidPx`` / ``askPx`` as strings.
- Subscribe-ack and pong frames carry no ``arg``/``data`` and are
  ignored by the frame handler.
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


# Public docs: https://www.okx.com/docs-v5/en/#order-book-trading-market-data-ws-tickers-channel
_OKX_PUBLIC_WS = "wss://ws.okx.com:8443/ws/v5/public"

# OKX-recommended keepalive interval (server idle timeout is ~30s).
_OKX_PING_INTERVAL_SECONDS = 20.0

# Backoff bounds for reconnect loop (mirrors sibling clients).
_BACKOFF_INITIAL_SECONDS = 1.0
_BACKOFF_CAP_SECONDS = 30.0
_BACKOFF_RESET_SECONDS = 60.0


class OkxSwapTickerClient:
    """Background WS consumer for OKX v5 SWAP tickers.

    Single-instance per process. Subscribes to every instId returned
    by ``all_subscribed_symbols(Venue.OKX_SWAP)``.
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
            else all_subscribed_symbols(Venue.OKX_SWAP)
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
            logger.info("okx_swap_ticker: no symbols configured; not starting")
            return
        self._started = True
        self._shutdown.clear()
        self._thread = threading.Thread(
            target=self._thread_main,
            name="okx_swap_ticker",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "okx_swap_ticker: started for %d instId(s): %s",
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
            logger.exception("okx_swap_ticker: thread crashed")
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
                    "okx_swap_ticker: connection closed (%s); reconnecting", e,
                )
            except Exception:
                logger.exception(
                    "okx_swap_ticker: consume loop error; reconnecting"
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
        logger.info("okx_swap_ticker: connecting to %s", _OKX_PUBLIC_WS)
        async with websockets.connect(
            _OKX_PUBLIC_WS,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=2,
            max_queue=1024,
        ) as ws:
            sub = {
                "op": "subscribe",
                "args": [
                    {"channel": "tickers", "instId": s}
                    for s in self._symbols
                ],
            }
            await ws.send(json.dumps(sub))
            logger.info(
                "okx_swap_ticker: connected; subscribed to %d instId(s)",
                len(self._symbols),
            )

            ping_task = asyncio.create_task(self._ping_loop(ws))
            try:
                async for raw in ws:
                    if self._shutdown.is_set():
                        return
                    try:
                        self._handle_frame(raw)
                    except Exception:
                        logger.exception(
                            "okx_swap_ticker: frame handler error"
                        )
            finally:
                ping_task.cancel()
                try:
                    await ping_task
                except (asyncio.CancelledError, Exception):
                    pass

    async def _ping_loop(self, ws) -> None:
        """Send the OKX-recommended app-level text ``"ping"`` every
        ~20s. Server replies with text ``"pong"`` which arrives via
        the main recv loop and is ignored as a no-data frame.
        """
        try:
            while not self._shutdown.is_set():
                await asyncio.sleep(_OKX_PING_INTERVAL_SECONDS)
                try:
                    await ws.send("ping")
                except (ConnectionClosed, RuntimeError):
                    return
        except asyncio.CancelledError:
            return

    def _handle_frame(self, raw: object) -> None:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="replace")
        if not isinstance(raw, str):
            return

        # Server replies "pong" to our text ping; nothing to do.
        if raw == "pong":
            return

        msg = json.loads(raw)
        if not isinstance(msg, dict):
            return

        # Subscribe-ack frames have ``event`` set and no ``data``.
        if "data" not in msg:
            return

        arg = msg.get("arg")
        if not isinstance(arg, dict) or arg.get("channel") != "tickers":
            return

        data = msg.get("data")
        if not isinstance(data, list) or not data:
            return

        for entry in data:
            if not isinstance(entry, dict):
                continue
            symbol = entry.get("instId")
            bid_str = entry.get("bidPx")
            ask_str = entry.get("askPx")
            if not symbol or bid_str in (None, "") or ask_str in (None, ""):
                continue
            try:
                bid = float(bid_str)
                ask = float(ask_str)
            except (TypeError, ValueError):
                continue
            if bid <= 0 or ask <= 0 or ask < bid:
                continue

            tick = VenueTick(
                venue=Venue.OKX_SWAP,
                symbol=symbol,
                bid=bid,
                ask=ask,
                recv_monotonic=time.monotonic(),
            )
            self._aggregator.record_tick(tick)

            if self._debug_callback is not None:
                try:
                    self._debug_callback(entry)
                except Exception:
                    logger.exception(
                        "okx_swap_ticker: debug_callback raised"
                    )
