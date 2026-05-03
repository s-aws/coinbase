"""Hotpoint decay sweeper — cancel resting auto-placed orders in cooled buckets.

When a bucket stops being hot (zero qualifying fills inside the trigger
window), there is no live signal to keep extra inventory parked there. The
sweeper periodically scans ``order_parent`` for resting
``auto_placed_by_hotpoint=TRUE`` rows, computes each row's bucket, and
issues an exchange cancel for any whose bucket is now empty in the detector.

This is a passive shrink path; it never PLACES, only CANCELS.

Threading model
---------------
Single daemon thread, started via :meth:`HotpointDecaySweeper.start`. The
loop sleeps on the engine's ``shutdown_event`` so a clean shutdown halts
the sweeper promptly.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Optional

from business.hotpoint_detector import HotpointDetector, compute_bucket_id

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _CancelDecision:
    """One candidate row + the verdict for that row."""

    client_order_id: str
    product_id: str
    side: str
    bucket_id: int
    cancel: bool


class HotpointDecaySweeper:
    """Periodic cancel sweep for cooled hotpoint buckets."""

    def __init__(
        self,
        *,
        detector: HotpointDetector,
        width_pct: float,
        interval_seconds: float,
        list_open_fn: Callable[[], List[dict]],
        rest_client: Any,
        shutdown_event: Optional[threading.Event] = None,
        log_callback: Optional[Callable[[str, Any], None]] = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        if interval_seconds <= 0.0:
            raise ValueError(
                f"interval_seconds must be > 0, got {interval_seconds!r}"
            )
        if width_pct <= 0.0:
            raise ValueError(f"width_pct must be > 0, got {width_pct!r}")
        self._detector = detector
        self._width_pct = width_pct
        self._interval_s = float(interval_seconds)
        self._list_open_fn = list_open_fn
        self._rest_client = rest_client
        self._shutdown = shutdown_event or threading.Event()
        self._log = log_callback or (
            lambda level, msg: getattr(logger, level, logger.info)(msg)
        )
        self._clock = clock or time.monotonic
        self._thread: Optional[threading.Thread] = None
        self._sweeps_completed = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Launch the daemon thread. Idempotent."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            name="hotpoint_decay_sweeper",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Signal shutdown and wait briefly for the thread to exit."""
        self._shutdown.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def run_once(self, *, now: Optional[float] = None) -> List[_CancelDecision]:
        """Execute one sweep synchronously. Returns the decisions made.

        Public so tests don't need a thread.
        """
        ts = float(now) if now is not None else self._clock()
        try:
            rows = self._list_open_fn() or []
        except Exception as e:
            self._log("warning", {
                "event": "hotpoint_decay_list_failed",
                "error": f"{type(e).__name__}: {e}",
            })
            return []

        decisions: List[_CancelDecision] = []
        for row in rows:
            try:
                product_id = row["product_id"]
                side = row["side"]
                price = float(row["price"])
                client_order_id = row["client_order_id"]
            except (KeyError, TypeError, ValueError) as e:
                self._log("warning", {
                    "event": "hotpoint_decay_bad_row",
                    "row": dict(row) if hasattr(row, "items") else repr(row),
                    "error": str(e),
                })
                continue

            if price <= 0.0:
                continue

            bucket_id = compute_bucket_id(price, self._width_pct)
            in_window = self._detector.fills_in_window(
                product_id=product_id,
                side=side,
                bucket_id=bucket_id,
                now=ts,
            )
            cancel = in_window == 0
            decisions.append(_CancelDecision(
                client_order_id=client_order_id,
                product_id=product_id,
                side=side,
                bucket_id=bucket_id,
                cancel=cancel,
            ))

            if cancel:
                self._cancel_one(client_order_id)

        self._sweeps_completed += 1
        return decisions

    @property
    def sweeps_completed(self) -> int:
        return self._sweeps_completed

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _cancel_one(self, client_order_id: str) -> None:
        try:
            self._rest_client.cancel_orders(order_ids=[client_order_id])
            self._log("info", {
                "event": "hotpoint_decay_cancelled",
                "client_order_id": client_order_id,
            })
        except Exception as e:
            self._log("warning", {
                "event": "hotpoint_decay_cancel_failed",
                "client_order_id": client_order_id,
                "error": f"{type(e).__name__}: {e}",
            })

    def _run(self) -> None:
        while not self._shutdown.is_set():
            try:
                self.run_once()
            except Exception as e:
                self._log("error", {
                    "event": "hotpoint_decay_loop_unexpected",
                    "error": f"{type(e).__name__}: {e}",
                })
            if self._shutdown.wait(timeout=self._interval_s):
                return
