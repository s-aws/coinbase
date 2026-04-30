"""Thread-safe aggregator for cross-venue ticker data.

Single source of truth for "what is the current external view of
this Coinbase product". Per-venue WS clients call ``record_tick``
on every bookTicker update; downstream consumers (historical
averager, reveal logic) call ``get_intel`` to read a snapshot
``CrossVenueIntel`` for a Coinbase product.

Design constraints (Phase 1):
- **Read-only side effects.** No mutation of orderbook / pricing
  state. This module returns a value object; consumers decide
  whether to act on it.
- **Fail-soft.** Missing / stale / contradictory data returns
  ``None`` from ``get_intel``; never raises to the caller.
- **Bounded memory.** Per-(venue, symbol) ring buffer with a
  small fixed cap (default 64 ticks) used only for short-term
  lead/lag computation.
- **Lock discipline.** Single ``threading.RLock`` over the whole
  aggregator. Tick rate from 3-4 venues × ~5 symbols × ~50ms
  cadence is well under 1k ops/sec — fine for a coarse lock.
  Per-key locking would be premature optimization.
"""

from __future__ import annotations

import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

from market_intel.venues import (
    COINBASE_TO_EXTERNAL,
    ExternalSymbol,
    Venue,
    get_external_symbols,
)


@dataclass(frozen=True)
class VenueTick:
    """A single bookTicker observation from one venue.

    ``recv_monotonic`` is the local monotonic clock at receipt and
    is the ONLY timestamp used for staleness checks. Wall-clock
    fields from venue payloads are wildly inconsistent (some send
    server time, some send match time, some don't send any) and
    aren't safe to compare across venues.
    """

    venue: Venue
    symbol: str
    bid: float
    ask: float
    recv_monotonic: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_bps(self) -> float:
        m = self.mid
        if m <= 0:
            return 0.0
        return (self.ask - self.bid) / m * 10_000.0


@dataclass(frozen=True)
class CrossVenueIntel:
    """Snapshot of cross-venue signal for ONE Coinbase product.

    Audit-friendly: every field that influenced a decision is
    captured so downstream log records can replay the reasoning.
    Mirrors the integrated-by-design pattern used elsewhere
    (e.g. ``RevealExecutionPlan``).
    """

    coinbase_product_id: str
    # Median external mid across fresh, non-proxy venues (or all
    # fresh venues if no non-proxy venues are available). ``None``
    # when no fresh data exists.
    consensus_mid: Optional[float]
    # (consensus_mid - coinbase_mid) / coinbase_mid in basis points.
    # Positive = external venues are higher than Coinbase. ``None``
    # when either side is missing.
    coinbase_premium_bps: Optional[float]
    # Mid-change rate over the last ``lookback_seconds`` seconds,
    # in bps, averaged across fresh external venues. Positive =
    # external venues are trending up faster than Coinbase. ``None``
    # when insufficient history.
    short_term_lead_bps: Optional[float]
    # Number of external venues whose latest tick is fresher than
    # ``staleness_ms``. Confidence proxy.
    fresh_venue_count: int
    # Stdev of fresh external mids, in bps of the consensus. High
    # value = venues disagree → lower confidence in consensus.
    cross_venue_dispersion_bps: Optional[float]
    # Per-venue snapshot for audit / debugging. Empty when no
    # venues had fresh data.
    venue_mids: Dict[Venue, float] = field(default_factory=dict)
    # Whether the consensus had to fall back to proxy venues
    # (e.g. dated future priced off a perp). Consumers should
    # down-weight when True.
    used_proxy: bool = False


class CrossVenueAggregator:
    """Thread-safe ring-buffered store of recent venue ticks plus
    derived-signal queries.

    Lifecycle:
        agg = CrossVenueAggregator()
        # WS clients call this on every update:
        agg.record_tick(VenueTick(...))
        # Engine reads this on every reveal / averaging step:
        intel = agg.get_intel("BIP-20DEC30-CDE")
        if intel and intel.fresh_venue_count >= 2:
            ...
    """

    def __init__(
        self,
        *,
        ring_size: int = 64,
        staleness_ms: int = 500,
        lookback_seconds: float = 1.0,
        prefer_non_proxy: bool = True,
        clock=time.monotonic,
    ):
        if ring_size < 2:
            raise ValueError("ring_size must be >= 2 for lead/lag computation")
        if staleness_ms <= 0:
            raise ValueError("staleness_ms must be positive")
        if lookback_seconds <= 0:
            raise ValueError("lookback_seconds must be positive")

        self._ring_size = ring_size
        self._staleness_seconds = staleness_ms / 1000.0
        self._lookback_seconds = lookback_seconds
        self._prefer_non_proxy = prefer_non_proxy
        self._clock = clock

        self._lock = threading.RLock()
        # (venue, symbol) -> deque[VenueTick] (newest at the right)
        self._ticks: Dict[Tuple[Venue, str], Deque[VenueTick]] = {}

    # ------------------------------------------------------------------
    # Writers — called from WS client threads
    # ------------------------------------------------------------------

    def record_tick(self, tick: VenueTick) -> None:
        """Record a single ticker update. Safe to call from any
        thread; called once per Binance/Bybit/OKX bookTicker frame.
        """
        key = (tick.venue, tick.symbol)
        with self._lock:
            ring = self._ticks.get(key)
            if ring is None:
                ring = deque(maxlen=self._ring_size)
                self._ticks[key] = ring
            ring.append(tick)

    # ------------------------------------------------------------------
    # Readers — called from engine threads
    # ------------------------------------------------------------------

    def latest_tick(self, venue: Venue, symbol: str) -> Optional[VenueTick]:
        """Most recent tick for a (venue, symbol). ``None`` if never
        seen. No staleness filtering — caller decides."""
        with self._lock:
            ring = self._ticks.get((venue, symbol))
            if not ring:
                return None
            return ring[-1]

    def get_intel(
        self,
        coinbase_product_id: str,
        coinbase_mid: Optional[float] = None,
    ) -> Optional[CrossVenueIntel]:
        """Compute derived cross-venue signal for a Coinbase product.

        Args:
            coinbase_product_id: e.g. ``"BIP-20DEC30-CDE"``.
            coinbase_mid: Coinbase-side mid (bid+ask)/2 if the caller
                has it handy. Required for ``coinbase_premium_bps``
                and for the lead-lag computation. When ``None`` those
                fields are ``None`` but consensus_mid is still returned.

        Returns:
            ``CrossVenueIntel`` or ``None`` if no external venues are
            configured for this product OR no fresh ticks are
            available. Callers must treat ``None`` as "no signal,
            fall back to your existing logic" — never as an error.
        """
        proxies = get_external_symbols(coinbase_product_id)
        if not proxies:
            return None

        now = self._clock()
        fresh: List[Tuple[ExternalSymbol, VenueTick]] = []
        with self._lock:
            for proxy in proxies:
                ring = self._ticks.get((proxy.venue, proxy.symbol))
                if not ring:
                    continue
                latest = ring[-1]
                if (now - latest.recv_monotonic) > self._staleness_seconds:
                    continue
                fresh.append((proxy, latest))

        if not fresh:
            return None

        # Prefer non-proxy ticks when both kinds are available.
        # Falls back to proxy-only if that's all we have.
        used_proxy = False
        if self._prefer_non_proxy:
            non_proxy = [(p, t) for (p, t) in fresh if not p.is_proxy]
            if non_proxy:
                contributing = non_proxy
            else:
                contributing = fresh
                used_proxy = True
        else:
            contributing = fresh
            used_proxy = any(p.is_proxy for (p, _) in fresh)

        mids = [t.mid for (_, t) in contributing]
        consensus_mid = statistics.median(mids)
        venue_mids: Dict[Venue, float] = {}
        for (proxy, tick) in contributing:
            # If a venue appears twice (shouldn't, but be defensive)
            # keep the first occurrence.
            venue_mids.setdefault(proxy.venue, tick.mid)

        if len(mids) >= 2 and consensus_mid > 0:
            stdev_abs = statistics.pstdev(mids)
            dispersion_bps = stdev_abs / consensus_mid * 10_000.0
        else:
            dispersion_bps = None

        if coinbase_mid is not None and coinbase_mid > 0:
            premium_bps = (consensus_mid - coinbase_mid) / coinbase_mid * 10_000.0
        else:
            premium_bps = None

        lead_bps = self._compute_short_term_lead_bps(
            contributing, coinbase_mid, now,
        )

        return CrossVenueIntel(
            coinbase_product_id=coinbase_product_id,
            consensus_mid=consensus_mid,
            coinbase_premium_bps=premium_bps,
            short_term_lead_bps=lead_bps,
            fresh_venue_count=len({p.venue for (p, _) in contributing}),
            cross_venue_dispersion_bps=dispersion_bps,
            venue_mids=venue_mids,
            used_proxy=used_proxy,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _compute_short_term_lead_bps(
        self,
        contributing: List[Tuple[ExternalSymbol, VenueTick]],
        coinbase_mid: Optional[float],
        now: float,
    ) -> Optional[float]:
        """Per-venue mid % change over the lookback window, averaged
        across venues, then expressed in bps relative to a Coinbase-
        anchored baseline (so the sign means "external moved more
        than Coinbase did").

        Returns ``None`` when we lack enough history or a Coinbase
        anchor to make the comparison meaningful.
        """
        if coinbase_mid is None or coinbase_mid <= 0:
            return None

        cutoff = now - self._lookback_seconds
        per_venue_changes: List[float] = []

        with self._lock:
            for (proxy, latest) in contributing:
                ring = self._ticks.get((proxy.venue, proxy.symbol))
                if not ring or len(ring) < 2:
                    continue
                # Find the oldest tick still inside the lookback
                # window (or the oldest in the ring if all are within).
                anchor: Optional[VenueTick] = None
                for tick in ring:
                    if tick.recv_monotonic >= cutoff:
                        anchor = tick
                        break
                if anchor is None or anchor is latest:
                    continue
                if anchor.mid <= 0:
                    continue
                pct_change = (latest.mid - anchor.mid) / anchor.mid
                per_venue_changes.append(pct_change)

        if not per_venue_changes:
            return None

        avg_external_pct = sum(per_venue_changes) / len(per_venue_changes)
        # Convert to bps. We don't have Coinbase tick history here so
        # this is "how much external venues moved over the window";
        # the sign is what matters for the lead/lag interpretation.
        # (A future revision can wire Coinbase tick history through
        # the same aggregator under Venue.COINBASE.)
        return avg_external_pct * 10_000.0

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def venue_health(self) -> Dict[Tuple[Venue, str], Dict]:
        """Snapshot of last-seen-age and tick count per (venue, symbol).
        Intended for the dashboard / operator probes, not the hot path.
        """
        now = self._clock()
        out: Dict[Tuple[Venue, str], Dict] = {}
        with self._lock:
            for key, ring in self._ticks.items():
                if not ring:
                    continue
                latest = ring[-1]
                out[key] = {
                    "tick_count": len(ring),
                    "age_seconds": now - latest.recv_monotonic,
                    "bid": latest.bid,
                    "ask": latest.ask,
                    "spread_bps": latest.spread_bps,
                }
        return out
