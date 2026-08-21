"""One-shot REST diagnostic: fetch the live transaction_summary and
print BOTH the maker/taker rates AND whether the FeeManager is
actually picking them up.

Tells us whether the 40-bps default maker rate is hiding live data,
or whether the live fetch is silently broken and the default IS what
runs in production.

Usage (from repo root):
    .\\.venv\\Scripts\\python.exe genai_tools\\check_live_fee_tier.py
"""
from __future__ import annotations

import json
import sys
from typing import Any

from configuration import REST_CLIENT


def _dump(label: str, payload: Any) -> None:
    print(f"\n===== {label} =====")
    print(json.dumps(payload, indent=2, default=str))


def main() -> int:
    # 1) Raw transaction_summary so we see the EXACT shape Coinbase returns.
    try:
        summary = REST_CLIENT.get_transaction_summary()
    except Exception as exc:
        print(f"\nget_transaction_summary FAILED: {type(exc).__name__}: {exc}")
        print("If this fails, FeeManager will fall back to defaults on every refresh.")
        return 1

    _dump("transaction_summary (raw)", summary)

    # 2) Surface the fee_tier specifically — that's what FeeManager reads.
    fee_tier = (
        summary.get("fee_tier")
        if isinstance(summary, dict)
        else None
    )
    _dump("fee_tier subset", fee_tier)

    # 3) Now build a FeeManager and see what it ACTUALLY caches.
    from calculation.fee_manager import FeeManager
    mgr = FeeManager(REST_CLIENT, log_callback=lambda *_: None, orderbook=None)
    refreshed = mgr._refresh_fee_rate()
    _dump(
        "FeeManager state after refresh",
        {
            "_refresh_fee_rate_returned": refreshed,
            "cached_taker_fee_rate": mgr._taker_fee_rate,
            "cached_maker_fee_rate": mgr._maker_fee_rate,
            "DEFAULT_TAKER_FEE_RATE": FeeManager.DEFAULT_TAKER_FEE_RATE
                if hasattr(FeeManager, "DEFAULT_TAKER_FEE_RATE") else "n/a",
            "DEFAULT_MAKER_FEE_RATE": FeeManager.DEFAULT_MAKER_FEE_RATE,
        },
    )

    # 4) Compute what the validator would charge for a representative
    #    derivatives order (BIP, 10 contracts @ 78000) using each tier.
    if hasattr(mgr, "get_profit_validation_fee_rate"):
        try:
            taker_eff = mgr.get_profit_validation_fee_rate(
                product_id="BIP-20DEC30-CDE", post_only=False)
            maker_eff = mgr.get_profit_validation_fee_rate(
                product_id="BIP-20DEC30-CDE", post_only=True)
            notional = 10 * 78000.0
            _dump(
                "Effective fee rates the validator will use (BIP)",
                {
                    "post_only=False (taker) effective rate": taker_eff,
                    "post_only=True  (maker) effective rate": maker_eff,
                    "notional_assumed_for_demo": notional,
                    "round_trip_pct_fee_taker": notional * taker_eff * 2,
                    "round_trip_pct_fee_maker": notional * maker_eff * 2,
                    "real_per_side_per_contract_from_statement": 0.226,
                    "real_round_trip_pct_fee_at_1_bp_x_2": notional * 0.0001 * 2,
                },
            )
        except Exception as exc:
            print(f"\nget_profit_validation_fee_rate FAILED: {type(exc).__name__}: {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
