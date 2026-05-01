"""Unit tests for ``market_intel.cross_venue_aggregator``.

Pure-Python, no network. Uses an injected fake clock so timing-
dependent paths (staleness filter, lookback window) are
deterministic.
"""

from __future__ import annotations

import pytest

from market_intel.cross_venue_aggregator import (
    CrossVenueAggregator,
    VenueTick,
)
from market_intel.venues import COINBASE_TO_EXTERNAL, Venue


class _FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _tick(venue: Venue, symbol: str, mid: float, recv: float, spread: float = 1.0) -> VenueTick:
    half = spread / 2.0
    return VenueTick(
        venue=venue, symbol=symbol,
        bid=mid - half, ask=mid + half,
        recv_monotonic=recv,
    )


# ---------------------------------------------------------------------------
# Smoke / shape
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_record_and_latest_round_trip():
    clock = _FakeClock()
    agg = CrossVenueAggregator(clock=clock)
    t = _tick(Venue.BINANCE_PERP, "BTCUSDT", mid=70_000.0, recv=clock.now)
    agg.record_tick(t)
    assert agg.latest_tick(Venue.BINANCE_PERP, "BTCUSDT") is t


@pytest.mark.regression
def test_unknown_product_returns_none():
    agg = CrossVenueAggregator()
    assert agg.get_intel("NOT-A-PRODUCT") is None


@pytest.mark.regression
def test_no_ticks_returns_none_for_known_product():
    agg = CrossVenueAggregator()
    # BIP-20DEC30-CDE has external proxies configured, but we haven't
    # recorded any ticks yet.
    assert agg.get_intel("BIP-20DEC30-CDE") is None


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_stale_ticks_are_excluded():
    clock = _FakeClock()
    agg = CrossVenueAggregator(clock=clock, staleness_ms=500)
    agg.record_tick(_tick(Venue.BINANCE_PERP, "BTCUSDT", 70_000.0, clock.now))
    # Advance past the staleness window.
    clock.advance(1.0)
    assert agg.get_intel("BIP-20DEC30-CDE") is None


@pytest.mark.regression
def test_fresh_tick_produces_intel():
    clock = _FakeClock()
    agg = CrossVenueAggregator(clock=clock, staleness_ms=500)
    agg.record_tick(_tick(Venue.BINANCE_PERP, "BTCUSDT", 70_000.0, clock.now))
    intel = agg.get_intel("BIP-20DEC30-CDE", coinbase_mid=70_010.0)
    assert intel is not None
    assert intel.consensus_mid == 70_000.0
    assert intel.fresh_venue_count == 1
    assert intel.coinbase_premium_bps is not None
    # Coinbase is HIGHER than external -> external premium is NEGATIVE.
    assert intel.coinbase_premium_bps < 0
    assert intel.used_proxy is False


# ---------------------------------------------------------------------------
# Consensus across venues
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_consensus_is_median_across_venues():
    clock = _FakeClock()
    agg = CrossVenueAggregator(clock=clock)
    agg.record_tick(_tick(Venue.BINANCE_PERP, "BTCUSDT", 70_000.0, clock.now))
    agg.record_tick(_tick(Venue.BYBIT_PERP, "BTCUSDT", 70_010.0, clock.now))
    agg.record_tick(_tick(Venue.OKX_SWAP, "BTC-USDT-SWAP", 70_020.0, clock.now))
    intel = agg.get_intel("BIP-20DEC30-CDE", coinbase_mid=70_005.0)
    assert intel is not None
    assert intel.consensus_mid == 70_010.0  # median of 3
    assert intel.fresh_venue_count == 3
    assert intel.cross_venue_dispersion_bps is not None
    assert intel.cross_venue_dispersion_bps > 0


@pytest.mark.regression
def test_dispersion_none_with_single_venue():
    clock = _FakeClock()
    agg = CrossVenueAggregator(clock=clock)
    agg.record_tick(_tick(Venue.BINANCE_PERP, "BTCUSDT", 70_000.0, clock.now))
    intel = agg.get_intel("BIP-20DEC30-CDE", coinbase_mid=70_000.0)
    assert intel is not None
    assert intel.cross_venue_dispersion_bps is None


# ---------------------------------------------------------------------------
# Proxy preference
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_non_proxy_venues_preferred_when_both_available(monkeypatch):
    """When a Coinbase product has both apples-to-apples and proxy
    external mappings, the non-proxy ticks must drive the consensus
    and ``used_proxy`` must be False. We patch the mapping table so
    this test doesn't depend on which production products happen to
    have proxy entries (currently none — see venues.py)."""
    from market_intel import cross_venue_aggregator as cva
    from market_intel.venues import ExternalSymbol

    custom = {
        "TEST-MIXED": [
            ExternalSymbol(Venue.BINANCE_PERP, "BTCUSDT"),  # non-proxy
            ExternalSymbol(
                Venue.BYBIT_PERP, "BTCUSDT", is_proxy=True,
                proxy_reason="test_proxy",
            ),
        ],
        "TEST-PROXY-ONLY": [
            ExternalSymbol(
                Venue.BYBIT_PERP, "BTCUSDT", is_proxy=True,
                proxy_reason="test_proxy",
            ),
        ],
    }
    monkeypatch.setattr(cva, "get_external_symbols",
                        lambda pid: list(custom.get(pid, [])))

    clock = _FakeClock()
    agg = CrossVenueAggregator(clock=clock)
    # Different mids per venue so we can prove which one drove consensus.
    agg.record_tick(_tick(Venue.BINANCE_PERP, "BTCUSDT", 70_000.0, clock.now))
    agg.record_tick(_tick(Venue.BYBIT_PERP,   "BTCUSDT", 71_000.0, clock.now))

    # Mixed product: non-proxy wins → consensus is Binance mid.
    mixed = agg.get_intel("TEST-MIXED", coinbase_mid=70_000.0)
    assert mixed is not None
    assert mixed.consensus_mid == 70_000.0
    assert mixed.used_proxy is False

    # Proxy-only product: must fall back to proxy ticks and flag it.
    proxy_only = agg.get_intel("TEST-PROXY-ONLY", coinbase_mid=71_000.0)
    assert proxy_only is not None
    assert proxy_only.consensus_mid == 71_000.0
    assert proxy_only.used_proxy is True


# ---------------------------------------------------------------------------
# Premium sign
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_premium_positive_when_external_higher():
    clock = _FakeClock()
    agg = CrossVenueAggregator(clock=clock)
    agg.record_tick(_tick(Venue.BINANCE_PERP, "BTCUSDT", 70_100.0, clock.now))
    intel = agg.get_intel("BIP-20DEC30-CDE", coinbase_mid=70_000.0)
    assert intel is not None
    assert intel.coinbase_premium_bps is not None
    # External is +100 over Coinbase on a base of 70_000 = ~14.28 bps.
    assert 14.0 < intel.coinbase_premium_bps < 15.0


@pytest.mark.regression
def test_premium_none_without_coinbase_mid():
    clock = _FakeClock()
    agg = CrossVenueAggregator(clock=clock)
    agg.record_tick(_tick(Venue.BINANCE_PERP, "BTCUSDT", 70_000.0, clock.now))
    intel = agg.get_intel("BIP-20DEC30-CDE")  # no coinbase_mid
    assert intel is not None
    assert intel.consensus_mid == 70_000.0
    assert intel.coinbase_premium_bps is None
    assert intel.short_term_lead_bps is None


# ---------------------------------------------------------------------------
# Short-term lead/lag
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_short_term_lead_positive_when_external_trending_up():
    clock = _FakeClock()
    agg = CrossVenueAggregator(clock=clock, lookback_seconds=2.0, staleness_ms=5_000)
    # Older anchor inside the lookback window.
    agg.record_tick(_tick(Venue.BINANCE_PERP, "BTCUSDT", 70_000.0, clock.now))
    clock.advance(1.0)
    # Newer tick — external moved up.
    agg.record_tick(_tick(Venue.BINANCE_PERP, "BTCUSDT", 70_100.0, clock.now))
    intel = agg.get_intel("BIP-20DEC30-CDE", coinbase_mid=70_100.0)
    assert intel is not None
    assert intel.short_term_lead_bps is not None
    assert intel.short_term_lead_bps > 0


@pytest.mark.regression
def test_short_term_lead_none_with_single_tick():
    clock = _FakeClock()
    agg = CrossVenueAggregator(clock=clock)
    agg.record_tick(_tick(Venue.BINANCE_PERP, "BTCUSDT", 70_000.0, clock.now))
    intel = agg.get_intel("BIP-20DEC30-CDE", coinbase_mid=70_000.0)
    assert intel is not None
    assert intel.short_term_lead_bps is None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_invalid_construction_args_raise():
    with pytest.raises(ValueError):
        CrossVenueAggregator(ring_size=1)
    with pytest.raises(ValueError):
        CrossVenueAggregator(staleness_ms=0)
    with pytest.raises(ValueError):
        CrossVenueAggregator(lookback_seconds=0)


# ---------------------------------------------------------------------------
# Mapping table sanity
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_mapping_table_has_no_duplicates_per_product():
    """Each Coinbase product should map to at most one entry per
    venue. Duplicates would skew the median."""
    for cb_product, proxies in COINBASE_TO_EXTERNAL.items():
        venues_seen = [p.venue for p in proxies]
        assert len(venues_seen) == len(set(venues_seen)), (
            f"{cb_product} has duplicate venues in mapping: {venues_seen}"
        )
