r"""One-shot diagnostic for Coinbase's product-filtered fee schedules.

The production fee cache deliberately keeps separate schedules for:

* ``SPOT`` / ``CBE``
* ``FUTURE`` / ``EXPIRING`` / ``FCM``

This tool prints the raw response for both requests, then builds a
``FeeManager`` through its public lifecycle and prints its public immutable
snapshots and fee quotes. It does not inspect deleted/private cache globals.

Usage (from the repository root on Windows):
    .\.venv\Scripts\python.exe genai_tools\check_live_fee_tier.py

The diagnostic is read-only: it fetches account fee metadata and does not
place orders or modify the database.
"""
from __future__ import annotations

import json
import sys
from enum import Enum
from pathlib import Path
from typing import Any, Dict

# Direct ``python genai_tools\check_live_fee_tier.py`` execution places only
# genai_tools/ on sys.path. Add the repository root before project imports so
# the documented Windows invocation works without PYTHONPATH configuration.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from configuration import REST_CLIENT
from core.constants import get_derivatives_per_side_fee
from core.enums import ContractExpiryType, ProductType, ProductVenue


SPOT_PRODUCT_ID = "BTC-USD"
FUTURE_PRODUCT_ID = "BIP-20DEC30-CDE"


def _dump(label: str, payload: Any) -> None:
    print(f"\n===== {label} =====")
    print(json.dumps(payload, indent=2, default=str, sort_keys=True))


def _enum_values(filters: Dict[str, Enum]) -> Dict[str, str]:
    return {name: value.value for name, value in filters.items()}


def _snapshot_payload(snapshot: Any) -> Dict[str, Any]:
    """Convert the public immutable FeeScheduleSnapshot to JSON-safe data."""
    return {
        "product_type": snapshot.product_type.value,
        "product_venue": snapshot.product_venue.value,
        "contract_expiry_type": (
            snapshot.contract_expiry_type.value
            if snapshot.contract_expiry_type is not None
            else None
        ),
        "maker_fee_rate": snapshot.maker_fee_rate,
        "taker_fee_rate": snapshot.taker_fee_rate,
        "pricing_tier": snapshot.pricing_tier,
        "has_cost_plus_commission": snapshot.has_cost_plus_commission,
        "has_promo_fee": snapshot.has_promo_fee,
        "source": snapshot.source.value,
        "last_attempt_at": (
            snapshot.last_attempt_at.isoformat()
            if snapshot.last_attempt_at is not None
            else None
        ),
        "last_success_at": (
            snapshot.last_success_at.isoformat()
            if snapshot.last_success_at is not None
            else None
        ),
        "consecutive_errors": snapshot.consecutive_errors,
        "last_error": snapshot.last_error,
    }


def _fetch_filtered_summaries() -> int:
    """Print both raw filtered summaries and return the failure count."""
    requests = (
        (
            "SPOT / CBE transaction_summary",
            {
                "product_type": ProductType.SPOT,
                "product_venue": ProductVenue.CBE,
            },
        ),
        (
            "FUTURE / EXPIRING / FCM transaction_summary",
            {
                "product_type": ProductType.FUTURE,
                "contract_expiry_type": ContractExpiryType.EXPIRING,
                "product_venue": ProductVenue.FCM,
            },
        ),
    )

    failures = 0
    for label, filters in requests:
        try:
            summary = REST_CLIENT.get_transaction_summary(**filters)
            _dump(
                label,
                {
                    "request_filters": _enum_values(filters),
                    "response": summary,
                    "fields_used_by_fee_manager": {
                        "fee_tier": (
                            summary.get("fee_tier")
                            if isinstance(summary, dict)
                            else None
                        ),
                        "has_cost_plus_commission": (
                            summary.get("has_cost_plus_commission")
                            if isinstance(summary, dict)
                            else None
                        ),
                        "has_promo_fee": (
                            summary.get("has_promo_fee")
                            if isinstance(summary, dict)
                            else None
                        ),
                    },
                },
            )
        except Exception as exc:
            failures += 1
            _dump(
                f"{label} FAILED",
                {
                    "request_filters": _enum_values(filters),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
    return failures


def _dump_manager_view() -> int:
    """Refresh through FeeManager's public lifecycle and print public views."""
    from calculation.fee_manager import FeeManager

    manager_logs = []
    manager = FeeManager(
        REST_CLIENT,
        log_callback=lambda level, payload: manager_logs.append(
            {"level": level, "payload": payload}
        ),
        orderbook=None,
    )

    try:
        # start() performs the immediate two-schedule refresh. stop() wakes the
        # background thread immediately; no private refresh method is needed.
        manager.start()

        product_views = {}
        fallback_snapshots = 0
        for label, product_id in (
            ("spot", SPOT_PRODUCT_ID),
            ("future", FUTURE_PRODUCT_ID),
        ):
            snapshot = manager.get_fee_schedule_snapshot(product_id)
            taker_quote = manager.get_profit_validation_fee_quote(
                product_id=product_id,
                post_only=False,
            )
            maker_quote = manager.get_profit_validation_fee_quote(
                product_id=product_id,
                post_only=True,
            )
            if snapshot.source.value != "coinbase":
                fallback_snapshots += 1

            product_views[label] = {
                "product_id": product_id,
                "snapshot": _snapshot_payload(snapshot),
                "quotes": {
                    "post_only_false_uses_taker": taker_quote.to_dict(),
                    "post_only_true_uses_maker": maker_quote.to_dict(),
                },
                "fee_info": manager.get_fee_info(product_id),
            }

        _dump(
            "FeeManager public snapshots and quotes",
            {
                "selection_rule": (
                    "post_only=True uses maker; every other order uses taker"
                ),
                "product_views": product_views,
                "refresh_logs": manager_logs,
            },
        )
        return fallback_snapshots
    finally:
        manager.stop()


def _dump_fixed_derivatives_costs() -> None:
    default_per_side = get_derivatives_per_side_fee(FUTURE_PRODUCT_ID)
    full_size_per_side = get_derivatives_per_side_fee("BTI-29MAY26-CDE")
    _dump(
        "Fixed CDE per-contract costs (separate from percentage quotes)",
        {
            "BIP_and_default_per_contract_side": default_per_side,
            "BIP_and_default_round_trip_per_contract": default_per_side * 2,
            "full_size_BTI_ETI_SLC_XRL_per_contract_side_legacy": (
                full_size_per_side
            ),
            "scope": (
                "BIP/default is settlement-confirmed at $0.12 per side; "
                "full-size remains the unchanged legacy $0.27 pending its own "
                "reconciliation"
            ),
            "database_action": "none; no correction or backfill is performed",
        },
    )


def main() -> int:
    failures = _fetch_filtered_summaries()
    failures += _dump_manager_view()
    _dump_fixed_derivatives_costs()

    if failures:
        print(
            f"\nDiagnostic completed with {failures} failed/fallback "
            "fee-schedule result(s)."
        )
        return 1

    print("\nDiagnostic completed with Coinbase-backed SPOT and FUTURE snapshots.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
