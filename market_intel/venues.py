"""External venue identifiers + Coinbase-product symbol mapping.

Single source of truth for "which Coinbase product corresponds to
which symbol on each external venue". Kept tiny and explicit on
purpose — getting a symbol mapping wrong silently corrupts every
downstream signal, so we want auditable per-product entries rather
than a clever auto-derivation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional


class Venue(str, Enum):
    """External (non-Coinbase) venues we may stream public ticker
    data from. ``COINBASE`` is included so downstream code can mark
    its own ticks with the same enum without a special case."""

    COINBASE = "COINBASE"
    BINANCE_PERP = "BINANCE_PERP"   # USDT-M futures (fstream.binance.com)
    BYBIT_PERP = "BYBIT_PERP"       # linear perps (stream.bybit.com)
    OKX_SWAP = "OKX_SWAP"           # ws.okx.com swap


@dataclass(frozen=True)
class ExternalSymbol:
    """A single (venue, symbol) pair that proxies a Coinbase product.

    ``is_proxy`` is True when the external symbol is not a perfect
    apples-to-apples match — most commonly when a Coinbase dated
    future (e.g. ``BIT-29MAY26-CDE``) is proxied by the corresponding
    perpetual on the external venue. Consumers should down-weight
    proxy ticks (basis can drift) but not discard them.
    """

    venue: Venue
    symbol: str
    is_proxy: bool = False
    proxy_reason: Optional[str] = None


# Coinbase product → list of external (venue, symbol) proxies.
#
# IMPORTANT: only list mappings that are *apples-to-apples* in
# instrument type. Cross-venue perp data does NOT price a Coinbase
# dated future (BIT-29MAY26-CDE etc.) — the BIP↔BIT basis on
# Coinbase itself was $200 a month ago and ~$400 now, which means
# any "external perp → dated future" proxy would inject a stale,
# direction-biased signal exactly when basis matters most.
#
# Dated futures should be priced by:
#   external perp (apples-to-apples) → Coinbase perp (apples-to-apples)
#                                    → Coinbase dated future (basis-adjusted)
# That second hop belongs in a separate intra-Coinbase basis tracker,
# not in this table. Until that exists, dated futures simply have no
# cross-venue coverage and consumers fall back to Coinbase-only data.
#
# Add new mappings here as new venues come online. Empty list = no
# external coverage available (consumers must treat as "no signal").
COINBASE_TO_EXTERNAL: Dict[str, list] = {
    # ----- BTC perp (apples-to-apples) -----
    "BIP-20DEC30-CDE": [
        ExternalSymbol(Venue.BINANCE_PERP, "BTCUSDT"),
        ExternalSymbol(Venue.BYBIT_PERP, "BTCUSDT"),
        ExternalSymbol(Venue.OKX_SWAP, "BTC-USDT-SWAP"),
    ],

    # ----- Other perps (deferred until BTC pipeline is proven out) -----
    # Phase 1 scope is BTC-only. Re-enable as separate commits with
    # their own measurement / regression coverage. Leaving the
    # mappings inline (commented) so the format stays obvious.
    # "ETP-20DEC30-CDE": [
    #     ExternalSymbol(Venue.BINANCE_PERP, "ETHUSDT"),
    #     ExternalSymbol(Venue.BYBIT_PERP, "ETHUSDT"),
    #     ExternalSymbol(Venue.OKX_SWAP, "ETH-USDT-SWAP"),
    # ],
    # "PAU-20DEC30-CDE": [
    #     ExternalSymbol(Venue.BINANCE_PERP, "PAXGUSDT"),
    # ],

    # ----- Dated futures: intentionally NO external mappings -----
    # See the docstring above. Intra-Coinbase basis tracker lives
    # elsewhere (TBD) and is the correct way to price these from BIP.
    # "BIT-29MAY26-CDE": [],
    # "ET-29MAY26-CDE":  [],
    # "GOL-27MAY26-CDE": [],
}


def get_external_symbols(coinbase_product_id: str) -> list:
    """Return external (venue, symbol) proxies for a Coinbase product.

    Returns an empty list when no proxies are configured. Callers must
    treat empty as "no external coverage" — never as an error — so the
    engine continues to function when intel is unavailable.
    """
    return list(COINBASE_TO_EXTERNAL.get(coinbase_product_id, []))


def all_subscribed_symbols(venue: Venue) -> list:
    """Return the deduplicated list of symbols that should be
    subscribed on ``venue`` to cover every configured Coinbase
    product. Used by the per-venue WS clients at startup.
    """
    seen: set = set()
    ordered: list = []
    for proxies in COINBASE_TO_EXTERNAL.values():
        for proxy in proxies:
            if proxy.venue != venue:
                continue
            if proxy.symbol in seen:
                continue
            seen.add(proxy.symbol)
            ordered.append(proxy.symbol)
    return ordered
