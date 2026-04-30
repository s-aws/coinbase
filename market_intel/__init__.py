"""Cross-venue market intelligence.

Aggregates public ticker streams from external crypto exchanges
(Binance, Bybit, OKX, ...) and exposes derived signals (consensus
mid, Coinbase-vs-world premium, short-term lead/lag) intended to
*influence* Coinbase-side pricing decisions, never to replace them.

Phase 1 (current): read-only data collection + measurement. No
reveal-logic integration. The module is safe to import even when
external feeds are disabled — every consumer receives ``None`` when
no fresh data is available, and falls back to the engine's own
historical averaging.

See ``cross_venue_aggregator.CrossVenueAggregator`` for the single
entry point.
"""

from market_intel.cross_venue_aggregator import (
    CrossVenueAggregator,
    CrossVenueIntel,
    VenueTick,
)
from market_intel.venues import Venue

__all__ = [
    "CrossVenueAggregator",
    "CrossVenueIntel",
    "Venue",
    "VenueTick",
]
