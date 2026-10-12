"""Cross-venue market intelligence.

Aggregates public ticker streams from external crypto exchanges
(Binance, Bybit, OKX, ...) and exposes derived signals (consensus
mid, Coinbase-vs-world premium, short-term lead/lag) for terminal display.

The module collects read-only measurements without reveal-logic integration.
Missing fresh external data yields no signal; engine pricing remains separate.

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
