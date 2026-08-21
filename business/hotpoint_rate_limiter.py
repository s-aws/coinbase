"""Hotpoint rate limiter — per (product, side, bucket) sliding-window cap.

Pairs with :mod:`business.hotpoint_detector`. The detector decides "fire";
this limiter decides "may we actually place".

Restart safety
--------------
The limiter is in-memory but **rebuilt at startup** from
``order_parent`` rows where ``auto_placed_by_hotpoint = TRUE`` and
``created_at`` is inside the rate-limit window. This means an engine
restart during a hot period does not reset the counter to zero (which
would defeat the cap and create a runaway-liquidation risk per the
2026-05-03 design conversation).

The limiter does **not** persist counters of its own — `order_parent`
is the source of truth. New successful placements call
:meth:`HotpointRateLimiter.record_placement` synchronously after the
DB insert.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict, Iterable, Optional, Tuple


_BucketKey = Tuple[str, str, int]


@dataclass(frozen=True)
class HotpointRateLimitDecision:
    """Result of :meth:`HotpointRateLimiter.try_acquire`."""

    allowed: bool
    current_count: int
    cap: int
    reason: str  # "ok", "cap_reached"


class HotpointRateLimiter:
    """Sliding-window rate limiter over (product, side, bucket).

    Thread-safe. Each ``try_acquire`` is atomic: if the call returns
    ``allowed=True``, the slot is reserved. Callers MUST follow up with
    :meth:`commit` (after the placement succeeded and was inserted) or
    :meth:`rollback` (if placement failed). This avoids two threads racing
    past the cap before either has finished its REST call.
    """

    def __init__(
        self,
        *,
        cap_n: int,
        window_seconds: float,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        if cap_n < 1:
            raise ValueError(f"cap_n must be >= 1, got {cap_n!r}")
        if window_seconds <= 0.0:
            raise ValueError(f"window_seconds must be > 0, got {window_seconds!r}")
        self._cap = cap_n
        self._window_s = float(window_seconds)
        # Committed placements: timestamps of completed placements.
        self._placements: Dict[_BucketKey, Deque[float]] = defaultdict(deque)
        # In-flight placements that have acquired a slot but not yet
        # committed/rolled back. Counted toward the cap.
        self._in_flight: Dict[_BucketKey, int] = defaultdict(int)
        # A placement whose REST acceptance is indeterminate blocks the
        # complete key until the window expires. One ordinary committed slot
        # is insufficient when the configured cap is greater than one.
        self._quarantined_until: Dict[_BucketKey, float] = {}
        self._lock = threading.RLock()
        self._clock = clock or time.monotonic

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def try_acquire(
        self,
        *,
        product_id: str,
        side: str,
        bucket_id: int,
        now: Optional[float] = None,
    ) -> HotpointRateLimitDecision:
        """Reserve a placement slot if the cap allows.

        Returns a decision; on ``allowed=True`` the caller MUST eventually
        call :meth:`commit` or :meth:`rollback` for the same key.
        """
        key: _BucketKey = (product_id, side, bucket_id)
        ts = float(now) if now is not None else self._clock()
        with self._lock:
            self._evict_expired(key, ts)
            if self._quarantined_until.get(key, 0.0) > ts:
                return HotpointRateLimitDecision(
                    allowed=False,
                    current_count=self._cap,
                    cap=self._cap,
                    reason="acceptance_indeterminate",
                )
            current = len(self._placements[key]) + self._in_flight[key]
            if current >= self._cap:
                return HotpointRateLimitDecision(
                    allowed=False,
                    current_count=current,
                    cap=self._cap,
                    reason="cap_reached",
                )
            self._in_flight[key] += 1
            return HotpointRateLimitDecision(
                allowed=True,
                current_count=current + 1,
                cap=self._cap,
                reason="ok",
            )

    def commit(
        self,
        *,
        product_id: str,
        side: str,
        bucket_id: int,
        now: Optional[float] = None,
    ) -> None:
        """Convert an in-flight reservation into a recorded placement."""
        key: _BucketKey = (product_id, side, bucket_id)
        ts = float(now) if now is not None else self._clock()
        with self._lock:
            if self._in_flight[key] <= 0:
                # Defensive: nothing to commit. Treat as a record-only call.
                self._placements[key].append(ts)
                return
            self._in_flight[key] -= 1
            self._placements[key].append(ts)

    def rollback(
        self,
        *,
        product_id: str,
        side: str,
        bucket_id: int,
    ) -> None:
        """Release an in-flight reservation that did not result in placement."""
        key: _BucketKey = (product_id, side, bucket_id)
        with self._lock:
            if self._in_flight[key] > 0:
                self._in_flight[key] -= 1

    def quarantine(
        self,
        *,
        product_id: str,
        side: str,
        bucket_id: int,
        now: Optional[float] = None,
    ) -> None:
        """Block a key after exchange acceptance becomes indeterminate.

        The in-flight reservation is consumed by the quarantine. No further
        placement for the same product/side/bucket is admitted until the
        normal rate window expires.
        """
        key: _BucketKey = (product_id, side, bucket_id)
        ts = float(now) if now is not None else self._clock()
        with self._lock:
            if self._in_flight[key] > 0:
                self._in_flight[key] -= 1
            self._quarantined_until[key] = max(
                self._quarantined_until.get(key, 0.0),
                ts + self._window_s,
            )

    def record_placement(
        self,
        *,
        product_id: str,
        side: str,
        bucket_id: int,
        at_epoch: Optional[float] = None,
    ) -> None:
        """Record a placement directly (used by restart-rebuild).

        Does NOT consult the cap. Used when reconstructing state from
        ``order_parent`` rows — those rows were already accepted, the
        cap check happened at the time they were placed.
        """
        key: _BucketKey = (product_id, side, bucket_id)
        ts = float(at_epoch) if at_epoch is not None else self._clock()
        with self._lock:
            self._placements[key].append(ts)

    def current_count(
        self,
        *,
        product_id: str,
        side: str,
        bucket_id: int,
        now: Optional[float] = None,
    ) -> int:
        """Return the current in-window count (committed + in-flight)."""
        key: _BucketKey = (product_id, side, bucket_id)
        ts = float(now) if now is not None else self._clock()
        with self._lock:
            self._evict_expired(key, ts)
            if self._quarantined_until.get(key, 0.0) > ts:
                return self._cap
            return len(self._placements[key]) + self._in_flight[key]

    def reset(self) -> None:
        """Wipe all in-memory state. Tests only."""
        with self._lock:
            self._placements.clear()
            self._in_flight.clear()
            self._quarantined_until.clear()

    def hydrate(self, rows: Iterable[Tuple[str, str, int, float]]) -> int:
        """Populate placement timestamps from external rows.

        Args:
            rows: Iterable of ``(product_id, side, bucket_id, epoch_seconds)``
                tuples representing committed placements that should count
                toward the rate cap.

        Returns:
            Number of rows ingested.
        """
        n = 0
        with self._lock:
            for product_id, side, bucket_id, epoch in rows:
                self._placements[(product_id, side, bucket_id)].append(float(epoch))
                n += 1
        return n

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _evict_expired(self, key: _BucketKey, now_ts: float) -> None:
        if self._quarantined_until.get(key, 0.0) <= now_ts:
            self._quarantined_until.pop(key, None)
        cutoff = now_ts - self._window_s
        bucket = self._placements[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
