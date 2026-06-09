"""Build a read-only USDC spot portfolio sweep dry run.

This tool reads Coinbase public product metadata and authenticated account
wallet balances. It does not place, preview, cancel, or modify live orders.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from coinbase.rest import RESTClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from business.spot_portfolio_sweep import build_usdc_portfolio_sweep_plan
from core.enums import OrderSide
from external.coinbase_client import (
    coinbase_sdk_response_to_dict,
    list_all_account_dicts,
)


SUMMARY_PREFIX = "SPOT_PORTFOLIO_SWEEP_DRY_RUN "


def _load_public_products() -> list[dict[str, Any]]:
    client = RESTClient(rate_limit_headers=True)
    response = coinbase_sdk_response_to_dict(
        client.get_public_products(
            product_type="SPOT",
            get_all_products=True,
            get_tradability_status=True,
        )
    )
    return list(response.get("products") or [])


def _load_wallets() -> dict[str, dict[str, Any]]:
    client = RESTClient(
        api_key=os.environ["COINBASE_API_KEY"],
        api_secret=os.environ["COINBASE_API_SECRET"],
        rate_limit_headers=True,
    )
    wallets: dict[str, dict[str, Any]] = {}
    for account in list_all_account_dicts(client):
        if account.get("deleted_at") is not None:
            continue
        currency = str(account.get("currency") or "").upper()
        if not currency:
            continue
        wallets[currency] = account
    return wallets


def _automation_preview(
    *,
    repeat_every_hours: Decimal | None,
    max_runs: int | None,
    plan: dict[str, Any],
) -> dict[str, Any] | None:
    if repeat_every_hours is None and max_runs is None:
        return None
    planned_per_run = Decimal(str(plan.get("estimated_planned_quote_notional") or "0"))
    runs = int(max_runs or 0)
    return {
        "repeat_every_hours": str(repeat_every_hours),
        "max_runs": runs,
        "estimated_planned_quote_notional_per_run": str(planned_per_run),
        "estimated_max_quote_notional": str(planned_per_run * runs),
        "live_scheduler_enabled": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read Coinbase account/product data and print a dry-run plan for "
            "USDC-quoted spot portfolio sweeps."
        )
    )
    parser.add_argument(
        "--side",
        required=True,
        choices=[OrderSide.BUY.value, OrderSide.SELL.value],
        help="Sweep side to plan.",
    )
    parser.add_argument(
        "--quote-notional",
        required=True,
        type=Decimal,
        help="Requested USDC notional per eligible crypto-USDC pair.",
    )
    parser.add_argument(
        "--max-products",
        type=int,
        default=None,
        help="Optional cap on eligible products included in this dry run.",
    )
    parser.add_argument(
        "--repeat-every-hours",
        type=Decimal,
        default=None,
        help=(
            "Optional automation cadence to preview. This dry run does not "
            "install or start a scheduler."
        ),
    )
    parser.add_argument(
        "--max-runs",
        type=int,
        default=None,
        help=(
            "Optional maximum run count for automation preview. Requires "
            "--repeat-every-hours."
        ),
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Omit per-product items from the JSON output.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.quote_notional <= 0:
        parser.error("--quote-notional must be greater than 0")
    if args.max_products is not None and args.max_products <= 0:
        parser.error("--max-products must be greater than 0")
    if args.repeat_every_hours is not None and args.repeat_every_hours <= 0:
        parser.error("--repeat-every-hours must be greater than 0")
    if args.max_runs is not None and args.max_runs <= 0:
        parser.error("--max-runs must be greater than 0")
    if (args.repeat_every_hours is None) != (args.max_runs is None):
        parser.error("--repeat-every-hours and --max-runs must be supplied together")
    if not os.environ.get("COINBASE_API_KEY") or not os.environ.get("COINBASE_API_SECRET"):
        parser.error("COINBASE_API_KEY and COINBASE_API_SECRET are required")

    products = _load_public_products()
    wallets = _load_wallets()
    plan = build_usdc_portfolio_sweep_plan(
        side=args.side,
        quote_notional=args.quote_notional,
        products=products,
        wallets=wallets,
        max_products=args.max_products,
    ).to_dict()
    if args.summary_only:
        plan.pop("items", None)

    summary = {
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "read_only_coinbase_requests": [
            "get_public_products",
            "get_accounts",
        ],
        "plan": plan,
        "automation_preview": _automation_preview(
            repeat_every_hours=args.repeat_every_hours,
            max_runs=args.max_runs,
            plan=plan,
        ),
    }
    print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
