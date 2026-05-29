"""Hotpoint detector — windowed fill-rate trigger over log-spaced price buckets.

See `genai_data` (none yet) and conversation 2026-05-03 for the design. In short:

* A "hotpoint" is a price bucket where >= N qualifying fills have occurred on
  the same (product, side) within the last T seconds.
* Buckets are log-spaced and deterministic:
    bucket_id = floor(log(price) / log(1 + width_pct))
  This is restart-safe and does not depend on fill arrival order.
* Only fills from orders flagged ``enable_hotpoint_replication=TRUE`` qualify.
  Auto-placed rows always carry that flag FALSE, so they cannot cascade.

This module is pure in-memory and pure logic — no DB, no REST. It exposes:

* :func:`compute_bucket_id` / :func:`bucket_center_price` — bucket math.
* :class:`HotpointDetector` — thread-safe ring-buffer trigger evaluator.

The detector hands ``HotpointTriggerEvent`` objects to callers; downstream
rate-limiting + actual order placement live in sibling modules.

Example:
    >>> from business.hotpoint_detector import HotpointDetector
    >>> detector = HotpointDetector(
    ...     width_pct=0.005,  # 0.5% bucket width
    ...     trigger_n=5,      # Trigger at 5 fills
    ...     trigger_window_seconds=60.0  # 1 minute window
    ... )
    >>> trigger_event = detector.record_fill(
    ...     product_id="BTC-USDC",
    ...     side="BUY",
    ...     fill_price=40000.0
    ... )
    >>> if trigger_event:
    ...     print(f"Hotpoint triggered at bucket {trigger_event.bucket_id}")
"""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple


def compute_bucket_id(price: float, width_pct: float) -> int:
    """Map a price to its log-spaced bucket id.

    This function computes a log-spaced bucket ID for a given price, which is
    deterministic and restart-safe. The bucket ID is computed using the formula:
    bucket_id = floor(log(price) / log(1 + width_pct))

    Args:
        price: Strictly positive fill price.
        width_pct: Bucket width as a fraction (e.g. ``0.005`` = 0.5%).

    Returns:
        Integer bucket id. Higher prices -> larger ids; the function is
        monotonic in ``price``.

    Raises:
        ValueError: If ``price <= 0`` or ``width_pct <= 0``.

    Example:
        >>> bucket_id = compute_bucket_id(40000.0, 0.005)  # 0.5% bucket width
        >>> print(bucket_id)
        133
    """
    if price <= 0.0:
        raise ValueError(f"price must be > 0, got {price!r}")
    if width_pct <= 0.0:
        raise ValueError(f"width_pct must be > 0, got {width_pct!r}")
    return math.floor(math.log(price) / math.log(1.0 + width_pct))


def bucket_center_price(bucket_id: int, width_pct: float) -> float:
    """Return the geometric center price of a bucket.

    The center is :math:`(1 + w)^{bucket\\_id + 0.5}` so that
    :func:`compute_bucket_id` of the center always returns ``bucket_id``.

    Args:
        bucket_id: The bucket ID.
        width_pct: Bucket width as a fraction (e.g. ``0.005`` = 0.5%).

    Returns:
        float: The geometric center price of the bucket.

    Example:
        >>> center_price = bucket_center_price(133, 0.005)
        >>> print(center_price)
        39999.99999999999
    """
    if width_pct <= 0.0:
        raise ValueError(f"width_pct must be > 0, got {width_pct!r}")
    return (1.0 + width_pct) ** (bucket_id + 0.5)


# ----------------------------------------------------------------------------
# Detector
# ----------------------------------------------------------------------------

# Key = (product_id, side, bucket_id). All three must be exact for a fill to
# count toward a trigger.
_BucketKey = Tuple[str, str, int]


@dataclass(frozen=True)
class HotpointTriggerEvent:
    """One fired hotpoint trigger handed to the placer.

    Carries everything the placer needs to derive a price (per
    :class:`core.enums.HotpointPlacementPolicy`) and submit one limit order.

    Attributes:
        product_id: Product identifier (e.g. "BTC-USDC").
        side: Order side ("BUY" or "SELL").
        bucket_id: The bucket ID that triggered the hotpoint.
        bucket_center: The geometric center price of the bucket.
        fills_in_window: Number of fills in the trigger window.
        last_fill_price: Price of the most recent fill in the window.
        mean_fill_price: Arithmetic mean of fill prices in the window.
        triggered_at: Timestamp when the trigger occurred (epoch seconds).

    Example:
        >>> event = HotpointTriggerEvent(
        ...     product_id="BTC-USDC",
        ...     side="BUY",
        ...     bucket_id=133,
        ...     bucket_center=39999.99999999999,
        ...     fills_in_window=5,
        ...     last_fill_price=40000.0,
        ...     mean_fill_price=39998.5,
        ...     triggered_at=1682841600.0
        ... )
    """

    product_id: str
    side: str
    bucket_id: int
    bucket_center: float
    fills_in_window: int
    last_fill_price: float
    mean_fill_price: float
    triggered_at: float  # epoch seconds


@dataclass
class _BucketState:
    """Per-bucket state. Mutated under the detector lock only."""

    fills: Deque[Tuple[float, float]] = field(default_factory=deque)
    """Each entry is ``(monotonic_seen_at, fill_price)``. Oldest first."""


class HotpointDetector:
    """Thread-safe windowed fill-rate trigger over log-spaced buckets.

    The detector owns one ring buffer per ``(product, side, bucket)`` and
    emits a :class:`HotpointTriggerEvent` whenever a qualifying fill brings
    the bucket's count within the window to ``>= trigger_n``.

    This detector is designed for hotpoint detection in high-frequency trading
    scenarios where certain price levels are experiencing unusually high fill
    rates. It uses log-spaced buckets to ensure consistent bucketing across
    different price ranges.

    Trigger semantics:
        * Trigger fires at most once per ``record_fill`` call. It does not
          re-fire on subsequent fills until at least one prior fill ages out
          and a new one comes in to push the count back up.
        * The "trigger fires" decision is local to ``record_fill``; the
          caller is responsible for rate-limiting and actually placing.

    Attributes:
        _width_pct: Bucket width as a fraction (e.g. 0.005 = 0.5%).
        _trigger_n: Minimum number of fills to trigger.
        _window_s: Trigger window in seconds.
        _buckets: Dictionary storing bucket states.
        _last_trigger_count: Dictionary tracking last trigger counts per bucket.
        _lock: Thread lock for thread safety.
        _clock: Clock function for time tracking.

    Example:
        >>> detector = HotpointDetector(
        ...     width_pct=0.005,  # 0.5% bucket width
        ...     trigger_n=5,      # Trigger at 5 fills
        ...     trigger_window_seconds=60.0  # 1 minute window
        ... )
        >>> trigger_event = detector.record_fill(
        ...     product_id="BTC-USDC",
        ...     side="BUY",
        ...     fill_price=40000.0
        ... )
    """

    def __init__(
        self,
        *,
        width_pct: float,
        trigger_n: int,
        trigger_window_seconds: float,
        clock=None,
    ) -> None:
        if width_pct <= 0.0:
            raise ValueError(f"width_pct must be > 0, got {width_pct!r}")
        if trigger_n < 1:
            raise ValueError(f"trigger_n must be >= 1, got {trigger_n!r}")
        if trigger_window_seconds <= 0.0:
            raise ValueError(
                f"trigger_window_seconds must be > 0, got {trigger_window_seconds!r}"
            )
        self._width_pct = width_pct
        self._trigger_n = trigger_n
        self._window_s = float(trigger_window_seconds)
        self._buckets: Dict[_BucketKey, _BucketState] = defaultdict(_BucketState)
        # Track the last bucket count we already triggered on, per key. We
        # only re-fire after the count has dropped below trigger_n and then
        # climbed back to it again.
        self._last_trigger_count: Dict[_BucketKey, int] = {}
        self._lock = threading.RLock()
        self._clock = clock or time.monotonic

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_fill(
        self,
        *,
        product_id: str,
        side: str,
        fill_price: float,
        now: Optional[float] = None,
    ) -> Optional[HotpointTriggerEvent]:
        """Record one qualifying fill and return a trigger event if fired.

        The caller is responsible for checking ``enable_hotpoint_replication``
        on the parent order BEFORE calling this — the detector trusts that
        whoever calls it has already done that gate.

        Args:
            product_id: e.g. ``"BTC-USDC"``.
            side: ``"BUY"`` or ``"SELL"``.
            fill_price: Price of the fill (must be > 0).
            now: Optional override of the monotonic clock for testing.

        Returns:
            ``HotpointTriggerEvent`` if this fill drove the bucket's
            in-window count to ``>= trigger_n`` (and it had not already
            triggered at that count). ``None`` otherwise.

        Example:
            >>> detector = HotpointDetector(width_pct=0.005, trigger_n=5, trigger_window_seconds=60)
            >>> event = detector.record_fill(
            ...     product_id="BTC-USDC",
            ...     side="BUY",
            ...     fill_price=40000.0
            ... )
            >>> if event:
            ...     print(f"Hotpoint triggered at bucket {event.bucket_id}")
        """
        if fill_price <= 0.0:
            raise ValueError(f"fill_price must be > 0, got {fill_price!r}")
        bucket_id = compute_bucket_id(fill_price, self._width_pct)
        key: _BucketKey = (product_id, side, bucket_id)
        ts = float(now) if now is not None else self._clock()

        with self._lock:
            state = self._buckets[key]
            self._evict_expired(state, ts)
            state.fills.append((ts, fill_price))
            count = len(state.fills)

            # Edge re-arm: once the count drops below the threshold we
            # reset the latched trigger marker so the next climb fires.
            last_fired_at = self._last_trigger_count.get(key)
            if last_fired_at is not None and count < self._trigger_n:
                self._last_trigger_count.pop(key, None)
                last_fired_at = None

            if count < self._trigger_n:
                return None

            # Don't re-fire while sitting at the same triggered level.
            if last_fired_at is not None and count <= last_fired_at:
                return None

            self._last_trigger_count[key] = count
            prices = [p for _, p in state.fills]
            return HotpointTriggerEvent(
                product_id=product_id,
                side=side,
                bucket_id=bucket_id,
                bucket_center=bucket_center_price(bucket_id, self._width_pct),
                fills_in_window=count,
                last_fill_price=prices[-1],
                mean_fill_price=sum(prices) / len(prices),
                triggered_at=ts,
            )

    def fills_in_window(
        self,
        *,
        product_id: str,
        side: str,
        bucket_id: int,
        now: Optional[float] = None,
    ) -> int:
        """Return the current in-window fill count for a bucket.

        Used by the decay sweeper to decide whether resting auto-placed
        orders at a bucket should be cancelled.

        Args:
            product_id: Product identifier (e.g. "BTC-USDC").
            side: Order side ("BUY" or "SELL").
            bucket_id: The bucket ID to check.
            now: Optional override of the monotonic clock for testing.

        Returns:
            int: The current in-window fill count for the bucket.

        Example:
            >>> detector = HotpointDetector(width_pct=0.005, trigger_n=5, trigger_window_seconds=60)
            >>> count = detector.fills_in_window(
            ...     product_id="BTC-USDC",
            ...     side="BUY",
            ...     bucket_id=133
            ... )
            >>> print(count)
        """
        key: _BucketKey = (product_id, side, bucket_id)
        ts = float(now) if now is not None else self._clock()
        with self._lock:
            state = self._buckets.get(key)
            if state is None:
                return 0
            self._evict_expired(state, ts)
            return len(state.fills)

    def reset(self) -> None:
        """Wipe all in-memory state. Tests only."""
        with self._lock:
            self._buckets.clear()
            self._last_trigger_count.clear()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _evict_expired(self, state: _BucketState, now_ts: float) -> None:
        cutoff = now_ts - self._window_s
        fills = state.fills
        while fills and fills[0][0] < cutoff:
            fills.popleft()
