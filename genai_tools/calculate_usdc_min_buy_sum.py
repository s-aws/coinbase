"""Create Coinbase USDC minimum-size buy snapshots.

This utility uses Coinbase's public market product feed. It does not read
accounts, place orders, or require API credentials. When P/L-adjusted notional
mode is enabled, it reads the local fill ledger through the existing spot P/L
report path and scales the planned BUY notional per product.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PRODUCTS_URL = "https://api.coinbase.com/api/v3/brokerage/market/products"
USER_AGENT = "coinbase-min-buy-sum/1.0"
EXCLUDED_TRADE_FLAGS = ("is_disabled", "trading_disabled", "cancel_only", "view_only", "auction_mode")
DEFAULT_PLANNED_QUOTE_NOTIONAL = Decimal("5")
PNL_REPORT_SOURCE_NONE = "none"
PNL_REPORT_SOURCE_FILE = "file"
PNL_REPORT_SOURCE_LOCAL_FILL_LEDGER = "local_fill_ledger"
PNL_REPORT_SOURCE_COINBASE_AVERAGE_COST = "coinbase_average_cost"
PNL_SOURCE_MISSING = "missing"
PNL_SOURCE_AVERAGE_COST = "average_cost"
PNL_SOURCE_FILL_LEDGER = "fill_ledger"


@dataclass(frozen=True)
class ProductMinimum:
    product_id: str
    base_currency: str
    quote_currency: str
    base_increment: Decimal
    price_increment: Decimal
    base_min_size: Decimal
    quote_min_size: Decimal
    current_price: Decimal
    min_base_notional: Decimal
    executable_min_notional: Decimal
    status: str
    limit_only: bool
    post_only: bool


@dataclass(frozen=True)
class ProductPnlAdjustment:
    product_id: str
    source: str
    pnl_amount: Decimal
    basis_amount: Decimal
    adjustment_ratio: Decimal


def decimal_from_field(product: dict[str, Any], field: str) -> Decimal | None:
    value = product.get(field)
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def decimal_from_value(value: Any) -> Decimal | None:
    if isinstance(value, Mapping) and "value" in value:
        value = value.get("value")
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def decimal_to_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def neutral_pnl_adjustment(product_id: str) -> ProductPnlAdjustment:
    return ProductPnlAdjustment(
        product_id=product_id,
        source=PNL_SOURCE_MISSING,
        pnl_amount=Decimal("0"),
        basis_amount=Decimal("0"),
        adjustment_ratio=Decimal("0"),
    )


def pnl_adjustment_for_product(
    product_id: str,
    pnl_adjustments: Mapping[str, ProductPnlAdjustment],
) -> ProductPnlAdjustment:
    return pnl_adjustments.get(product_id.upper(), neutral_pnl_adjustment(product_id))


def pnl_adjustment_from_values(
    *,
    product_id: str,
    source: str,
    pnl_amount: Decimal | None,
    basis_amount: Decimal | None,
) -> ProductPnlAdjustment | None:
    if not product_id or pnl_amount is None or basis_amount is None or basis_amount <= 0:
        return None
    return ProductPnlAdjustment(
        product_id=product_id,
        source=source,
        pnl_amount=pnl_amount,
        basis_amount=basis_amount,
        adjustment_ratio=pnl_amount / basis_amount,
    )


def load_json_document(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8").strip()
    json_start = text.find("{")
    if json_start < 0:
        raise ValueError(f"{path} does not contain a JSON object")
    data = json.loads(text[json_start:])
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def spot_pnl_report_from_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    report = payload.get("pnl_report")
    if isinstance(report, Mapping):
        return report
    return payload


def build_local_spot_pnl_report(
    *,
    products: list[dict[str, Any]],
    product_ids: list[str],
) -> tuple[Mapping[str, Any], str]:
    from business.fill_ledger import FillLedgerRepository
    from business.spot_cost_basis import fetch_coinbase_average_cost_records
    from business.spot_portfolio_sweep import build_spot_portfolio_pnl_report
    from database.database import PostgresDB

    cost_basis = {}
    if os.getenv("COINBASE_API_KEY") and os.getenv("COINBASE_API_SECRET"):
        import configuration

        cost_basis = fetch_coinbase_average_cost_records(
            rest_client=configuration.get_rest_client(),
            products=products,
        )

    report = build_spot_portfolio_pnl_report(
        fill_ledger_repo=FillLedgerRepository(PostgresDB()),
        products=products,
        product_ids=product_ids,
        coinbase_average_costs=(
            cost_basis.get("records") if cost_basis else None
        ),
    )
    source = (
        PNL_REPORT_SOURCE_COINBASE_AVERAGE_COST
        if cost_basis and cost_basis.get("records")
        else PNL_REPORT_SOURCE_LOCAL_FILL_LEDGER
    )
    return report, source


def pnl_adjustments_from_report(report: Mapping[str, Any]) -> dict[str, ProductPnlAdjustment]:
    adjustments: dict[str, ProductPnlAdjustment] = {}

    average_cost = report.get("average_cost_pnl")
    if isinstance(average_cost, Mapping):
        for row in average_cost.get("products") or []:
            if not isinstance(row, Mapping):
                continue
            product_id = str(row.get("product_id") or "").upper()
            adjustment = pnl_adjustment_from_values(
                product_id=product_id,
                source=PNL_SOURCE_AVERAGE_COST,
                pnl_amount=decimal_from_value(row.get("unrealized_pnl")),
                basis_amount=decimal_from_value(row.get("cost_basis")),
            )
            if adjustment is not None:
                adjustments[product_id] = adjustment

    snapshot = report.get("snapshot")
    if isinstance(snapshot, Mapping):
        for row in snapshot.get("products") or []:
            if not isinstance(row, Mapping):
                continue
            product_id = str(row.get("product_id") or "").upper()
            if product_id in adjustments:
                continue
            adjustment = pnl_adjustment_from_values(
                product_id=product_id,
                source=PNL_SOURCE_FILL_LEDGER,
                pnl_amount=decimal_from_value(row.get("total_pnl")),
                basis_amount=decimal_from_value(row.get("buy_notional")),
            )
            if adjustment is not None:
                adjustments[product_id] = adjustment

    return adjustments


def load_pnl_adjustments(report_path: Path | None) -> dict[str, ProductPnlAdjustment]:
    if report_path is None:
        return {}
    return pnl_adjustments_from_report(spot_pnl_report_from_payload(load_json_document(report_path)))


def round_up_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    if increment <= 0:
        return value
    return (value / increment).to_integral_value(rounding=ROUND_CEILING) * increment


def get_json(url: str, params: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    request_url = f"{url}?{urlencode(params)}"
    request = Request(request_url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout_seconds) as response:
        return json.load(response)


def fetch_products(page_limit: int, timeout_seconds: float) -> list[dict[str, Any]]:
    data = get_json(
        PRODUCTS_URL,
        {
            "product_type": "SPOT",
            "get_all_products": "true",
        },
        timeout_seconds,
    )
    products = data.get("products") or []
    if products:
        return products

    products: list[dict[str, Any]] = []
    offset = 0

    while True:
        data = get_json(
            PRODUCTS_URL,
            {
                "limit": page_limit,
                "offset": offset,
                "product_type": "SPOT",
            },
            timeout_seconds,
        )
        batch = data.get("products") or []
        products.extend(batch)

        if len(batch) < page_limit:
            return products
        offset += page_limit


def dedupe_products(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for product in products:
        product_id = product.get("product_id")
        if product_id:
            unique[str(product_id)] = product
    return list(unique.values())


def is_eligible_product(product: dict[str, Any], quote: str, venue: str) -> bool:
    if product.get("product_type") != "SPOT":
        return False
    if product.get("quote_currency_id") != quote:
        return False
    if product.get("product_venue") != venue:
        return False
    if product.get("status") != "online":
        return False
    return not any(product.get(flag) is True for flag in EXCLUDED_TRADE_FLAGS)


def build_minimum(product: dict[str, Any]) -> ProductMinimum | None:
    base_increment = decimal_from_field(product, "base_increment")
    price_increment = decimal_from_field(product, "price_increment")
    base_min_size = decimal_from_field(product, "base_min_size")
    quote_min_size = decimal_from_field(product, "quote_min_size")
    current_price = decimal_from_field(product, "price")

    if (
        base_increment is None
        or price_increment is None
        or base_min_size is None
        or quote_min_size is None
        or current_price is None
    ):
        return None
    if base_increment <= 0 or price_increment <= 0 or base_min_size <= 0 or quote_min_size < 0 or current_price <= 0:
        return None

    min_base_notional = base_min_size * current_price
    executable_min_notional = max(min_base_notional, quote_min_size)

    return ProductMinimum(
        product_id=str(product["product_id"]),
        base_currency=str(product.get("base_currency_id") or ""),
        quote_currency=str(product.get("quote_currency_id") or ""),
        base_increment=base_increment,
        price_increment=price_increment,
        base_min_size=base_min_size,
        quote_min_size=quote_min_size,
        current_price=current_price,
        min_base_notional=min_base_notional,
        executable_min_notional=executable_min_notional,
        status=str(product.get("status") or ""),
        limit_only=bool(product.get("limit_only")),
        post_only=bool(product.get("post_only")),
    )


def collect_minimums(
    products: list[dict[str, Any]],
    quote: str,
    venue: str,
) -> tuple[list[ProductMinimum], int]:
    minimums: list[ProductMinimum] = []
    skipped_missing_required_fields = 0

    for product in products:
        if not is_eligible_product(product, quote=quote, venue=venue):
            continue
        minimum = build_minimum(product)
        if minimum is None:
            skipped_missing_required_fields += 1
            continue
        minimums.append(minimum)

    return minimums, skipped_missing_required_fields


def planned_quote_notional(
    *,
    product: ProductMinimum,
    default_quote_notional: Decimal,
    pnl_adjustment: ProductPnlAdjustment,
    pnl_adjusted_notional_enabled: bool,
) -> Decimal:
    if not pnl_adjusted_notional_enabled:
        return product.quote_min_size
    pnl_adjusted = default_quote_notional * (Decimal("1") + pnl_adjustment.adjustment_ratio)
    return max(product.quote_min_size, pnl_adjusted)


def quote_min_buy_notional(
    product: ProductMinimum,
    *,
    default_quote_notional: Decimal,
    pnl_adjustment: ProductPnlAdjustment,
    pnl_adjusted_notional_enabled: bool,
) -> Decimal:
    target_quote_notional = planned_quote_notional(
        product=product,
        default_quote_notional=default_quote_notional,
        pnl_adjustment=pnl_adjustment,
        pnl_adjusted_notional_enabled=pnl_adjusted_notional_enabled,
    )
    raw_base_size = target_quote_notional / product.current_price
    base_size = max(product.base_min_size, round_up_to_increment(raw_base_size, product.base_increment))
    return base_size * product.current_price


def sort_minimums(
    minimums: list[ProductMinimum],
    sort_by: str,
    *,
    default_quote_notional: Decimal,
    pnl_adjustments: Mapping[str, ProductPnlAdjustment],
    pnl_adjusted_notional_enabled: bool,
) -> list[ProductMinimum]:
    if sort_by == "product_id":
        return sorted(minimums, key=lambda item: item.product_id)
    if sort_by == "min_base_notional":
        return sorted(minimums, key=lambda item: (item.min_base_notional, item.product_id))
    if sort_by == "executable_min_notional":
        return sorted(minimums, key=lambda item: (item.executable_min_notional, item.product_id))
    if sort_by == "quote_min_buy_notional":
        return sorted(
            minimums,
            key=lambda item: (
                quote_min_buy_notional(
                    item,
                    default_quote_notional=default_quote_notional,
                    pnl_adjustment=pnl_adjustment_for_product(item.product_id, pnl_adjustments),
                    pnl_adjusted_notional_enabled=pnl_adjusted_notional_enabled,
                ),
                item.product_id,
            ),
        )
    raise ValueError(f"Unsupported sort key: {sort_by}")


def quote_min_buy_plan(
    product: ProductMinimum,
    taker_fee_rate: Decimal,
    *,
    default_quote_notional: Decimal,
    pnl_adjustment: ProductPnlAdjustment,
    pnl_adjusted_notional_enabled: bool,
) -> dict[str, Decimal]:
    pnl_adjusted_quote_notional = default_quote_notional * (
        Decimal("1") + pnl_adjustment.adjustment_ratio
    )
    planned_quote_notional_value = planned_quote_notional(
        product=product,
        default_quote_notional=default_quote_notional,
        pnl_adjustment=pnl_adjustment,
        pnl_adjusted_notional_enabled=pnl_adjusted_notional_enabled,
    )
    quote_min_base_size_estimate = planned_quote_notional_value / product.current_price
    quote_min_base_size_rounded_up = max(
        product.base_min_size,
        round_up_to_increment(quote_min_base_size_estimate, product.base_increment),
    )
    quote_min_buy_notional_value = quote_min_base_size_rounded_up * product.current_price
    taker_fee_estimate = quote_min_buy_notional_value * taker_fee_rate

    return {
        "default_quote_notional": default_quote_notional,
        "pnl_adjusted_quote_notional": pnl_adjusted_quote_notional,
        "planned_quote_notional": planned_quote_notional_value,
        "quote_min_base_size_estimate": quote_min_base_size_estimate,
        "quote_min_base_size_rounded_up": quote_min_base_size_rounded_up,
        "quote_min_buy_notional": quote_min_buy_notional_value,
        "taker_fee_estimate": taker_fee_estimate,
        "quote_min_buy_total_with_taker_fee": quote_min_buy_notional_value + taker_fee_estimate,
    }


def product_to_row(
    product: ProductMinimum,
    taker_fee_rate: Decimal,
    *,
    default_quote_notional: Decimal,
    pnl_adjustment: ProductPnlAdjustment,
    pnl_adjusted_notional_enabled: bool,
) -> dict[str, str]:
    buy_plan = quote_min_buy_plan(
        product,
        taker_fee_rate,
        default_quote_notional=default_quote_notional,
        pnl_adjustment=pnl_adjustment,
        pnl_adjusted_notional_enabled=pnl_adjusted_notional_enabled,
    )
    pnl_multiplier = Decimal("1") + pnl_adjustment.adjustment_ratio
    row = {
        "product_id": product.product_id,
        "side": "BUY",
        "liquidity_model": "taker",
        "base_currency": product.base_currency,
        "quote_currency": product.quote_currency,
        "current_price": decimal_to_text(product.current_price),
        "snapshot_limit_price": decimal_to_text(product.current_price),
        "base_increment": decimal_to_text(product.base_increment),
        "price_increment": decimal_to_text(product.price_increment),
        "base_min_size": decimal_to_text(product.base_min_size),
        "quote_min_size": decimal_to_text(product.quote_min_size),
        "order_quote_size": decimal_to_text(buy_plan["planned_quote_notional"]),
        "min_base_notional": decimal_to_text(product.min_base_notional),
        "executable_min_notional": decimal_to_text(product.executable_min_notional),
        "quote_min_base_size_estimate": decimal_to_text(buy_plan["quote_min_base_size_estimate"]),
        "quote_min_base_size_rounded_up": decimal_to_text(buy_plan["quote_min_base_size_rounded_up"]),
        "order_base_size_at_snapshot_price": decimal_to_text(buy_plan["quote_min_base_size_rounded_up"]),
        "quote_min_buy_notional": decimal_to_text(buy_plan["quote_min_buy_notional"]),
        "order_notional_at_snapshot_price": decimal_to_text(buy_plan["quote_min_buy_notional"]),
        "taker_fee_rate": decimal_to_text(taker_fee_rate),
        "taker_fee_estimate": decimal_to_text(buy_plan["taker_fee_estimate"]),
        "quote_min_buy_total_with_taker_fee": decimal_to_text(buy_plan["quote_min_buy_total_with_taker_fee"]),
        "estimated_total_quote_with_taker_fee": decimal_to_text(buy_plan["quote_min_buy_total_with_taker_fee"]),
        "status": product.status,
        "limit_only": str(product.limit_only).lower(),
        "post_only": str(product.post_only).lower(),
    }
    if pnl_adjusted_notional_enabled:
        row.update({
            "default_quote_notional": decimal_to_text(default_quote_notional),
            "pnl_source": pnl_adjustment.source,
            "pnl_amount": decimal_to_text(pnl_adjustment.pnl_amount),
            "pnl_basis_notional": decimal_to_text(pnl_adjustment.basis_amount),
            "pnl_adjustment_ratio": decimal_to_text(pnl_adjustment.adjustment_ratio),
            "pnl_adjustment_multiplier": decimal_to_text(pnl_multiplier),
            "pnl_adjusted_quote_notional": decimal_to_text(buy_plan["pnl_adjusted_quote_notional"]),
            "planned_quote_notional": decimal_to_text(buy_plan["planned_quote_notional"]),
        })
    return row


def build_result(
    minimums: list[ProductMinimum],
    *,
    quote: str,
    venue: str,
    raw_fetched_product_count: int,
    unique_fetched_product_count: int,
    skipped_missing_required_fields: int,
    taker_fee_rate: Decimal,
    default_quote_notional: Decimal,
    pnl_adjustments: Mapping[str, ProductPnlAdjustment],
    pnl_report_path: Path | None,
    pnl_report_source: str,
    pnl_adjusted_notional_enabled: bool,
) -> dict[str, Any]:
    sum_min_base_notional = sum((item.min_base_notional for item in minimums), Decimal("0"))
    sum_executable_min_notional = sum((item.executable_min_notional for item in minimums), Decimal("0"))
    buy_plans = [
        quote_min_buy_plan(
            item,
            taker_fee_rate,
            default_quote_notional=default_quote_notional,
            pnl_adjustment=pnl_adjustment_for_product(item.product_id, pnl_adjustments),
            pnl_adjusted_notional_enabled=pnl_adjusted_notional_enabled,
        )
        for item in minimums
    ]
    sum_planned_quote_notional = sum(
        (plan["planned_quote_notional"] for plan in buy_plans),
        Decimal("0"),
    )
    sum_quote_min_buy_notional = sum(
        (plan["quote_min_buy_notional"] for plan in buy_plans),
        Decimal("0"),
    )
    sum_taker_fee_estimate = sum_quote_min_buy_notional * taker_fee_rate
    sum_quote_min_buy_total_with_taker_fee = sum_quote_min_buy_notional + sum_taker_fee_estimate
    products_with_pnl_adjustment_count = len(
        [item for item in minimums if item.product_id.upper() in pnl_adjustments]
    )

    result = {
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": PRODUCTS_URL,
        "filters": {
            "product_type": "SPOT",
            "quote_currency_id": quote,
            "product_venue": venue,
            "status": "online",
            "excluded_flags": list(EXCLUDED_TRADE_FLAGS),
        },
        "raw_fetched_product_count": raw_fetched_product_count,
        "unique_fetched_product_count": unique_fetched_product_count,
        "eligible_product_count": len(minimums),
        "skipped_missing_required_fields": skipped_missing_required_fields,
        "taker_fee_rate": decimal_to_text(taker_fee_rate),
        "sum_min_base_notional": decimal_to_text(sum_min_base_notional),
        "sum_executable_min_notional": decimal_to_text(sum_executable_min_notional),
        "sum_quote_min_buy_notional": decimal_to_text(sum_quote_min_buy_notional),
        "sum_taker_fee_estimate": decimal_to_text(sum_taker_fee_estimate),
        "sum_quote_min_buy_total_with_taker_fee": decimal_to_text(sum_quote_min_buy_total_with_taker_fee),
        "products": [
            product_to_row(
                item,
                taker_fee_rate,
                default_quote_notional=default_quote_notional,
                pnl_adjustment=pnl_adjustment_for_product(item.product_id, pnl_adjustments),
                pnl_adjusted_notional_enabled=pnl_adjusted_notional_enabled,
            )
            for item in minimums
        ],
        "execution_note": (
            "Snapshot only. This file does not place orders. For quote-size market buys, "
            "use order_quote_size. For limit-style consumers, use snapshot_limit_price "
            "and order_base_size_at_snapshot_price, but a snapshot-price limit is not "
            "guaranteed to execute as taker unless it crosses the live ask."
        ),
    }
    if pnl_adjusted_notional_enabled:
        result.update({
            "pnl_adjusted_notional_enabled": True,
            "default_quote_notional": decimal_to_text(default_quote_notional),
            "pnl_report_path": str(pnl_report_path) if pnl_report_path else None,
            "pnl_report_source": pnl_report_source,
            "products_with_pnl_adjustment_count": products_with_pnl_adjustment_count,
            "products_missing_pnl_count": len(minimums) - products_with_pnl_adjustment_count,
            "sum_planned_quote_notional": decimal_to_text(sum_planned_quote_notional),
            "execution_note": (
                result["execution_note"]
                + " Missing product P/L rows use the default_quote_notional without adjustment."
            ),
        })
    return result


def write_csv(result: dict[str, Any], output_path: Path | None) -> None:
    fieldnames = [
        "product_id",
        "side",
        "liquidity_model",
        "base_currency",
        "quote_currency",
        "current_price",
        "snapshot_limit_price",
        "base_increment",
        "price_increment",
        "base_min_size",
        "quote_min_size",
    ]
    if result.get("pnl_adjusted_notional_enabled"):
        fieldnames.extend([
            "default_quote_notional",
            "pnl_source",
            "pnl_amount",
            "pnl_basis_notional",
            "pnl_adjustment_ratio",
            "pnl_adjustment_multiplier",
            "pnl_adjusted_quote_notional",
            "planned_quote_notional",
        ])
    fieldnames.extend([
        "order_quote_size",
        "min_base_notional",
        "executable_min_notional",
        "quote_min_base_size_estimate",
        "quote_min_base_size_rounded_up",
        "order_base_size_at_snapshot_price",
        "quote_min_buy_notional",
        "order_notional_at_snapshot_price",
        "taker_fee_rate",
        "taker_fee_estimate",
        "quote_min_buy_total_with_taker_fee",
        "estimated_total_quote_with_taker_fee",
        "status",
        "limit_only",
        "post_only",
    ])
    stream = output_path.open("w", newline="", encoding="utf-8") if output_path else sys.stdout
    try:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(result["products"])
    finally:
        if output_path:
            stream.close()


def write_json(result: dict[str, Any], output_path: Path | None) -> None:
    payload = json.dumps(result, indent=2)
    if output_path:
        output_path.write_text(payload + "\n", encoding="utf-8")
        return
    print(payload)


def write_text_summary(result: dict[str, Any], include_products: bool, output_path: Path | None) -> None:
    lines = [
        f"Fetched at: {result['fetched_at']}",
        f"Source: {result['source']}",
        f"Fetched products: {result['unique_fetched_product_count']} unique ({result['raw_fetched_product_count']} raw)",
        f"Eligible {result['filters']['quote_currency_id']} products: {result['eligible_product_count']}",
        f"Literal base-min notional sum: {result['sum_min_base_notional']} {result['filters']['quote_currency_id']}",
        f"Executable quote-min floor sum: {result['sum_executable_min_notional']} {result['filters']['quote_currency_id']}",
        f"Quote-min buy notional at snapshot prices: {result['sum_quote_min_buy_notional']} {result['filters']['quote_currency_id']}",
        f"Taker fee estimate at {result['taker_fee_rate']}: {result['sum_taker_fee_estimate']} {result['filters']['quote_currency_id']}",
        (
            "Quote-min buy total with taker fee: "
            f"{result['sum_quote_min_buy_total_with_taker_fee']} {result['filters']['quote_currency_id']}"
        ),
        "",
        "Note: quote-min buy rows round base size up to base_increment at the snapshot price.",
        "Snapshot output includes order_quote_size for a separate quote-size buy function.",
        "A limit buy at the snapshot price is not guaranteed to execute as taker; crossing the live ask is what makes it taker.",
    ]
    if result.get("pnl_adjusted_notional_enabled"):
        lines[6:6] = [
            f"P/L-adjusted notional mode: enabled",
            f"P/L report source: {result['pnl_report_source']}",
            f"Default quote notional: {result['default_quote_notional']} {result['filters']['quote_currency_id']}",
            f"Products with P/L adjustment: {result['products_with_pnl_adjustment_count']}",
            f"Products missing P/L adjustment: {result['products_missing_pnl_count']}",
            f"Planned quote notional before base-increment rounding: {result['sum_planned_quote_notional']} {result['filters']['quote_currency_id']}",
        ]

    if include_products:
        product_columns = [
            "product_id",
            "current_price",
            "base_min_size",
            "quote_min_size",
        ]
        if result.get("pnl_adjusted_notional_enabled"):
            product_columns.extend([
                "default_quote_notional",
                "pnl_source",
                "pnl_amount",
                "pnl_basis_notional",
                "pnl_adjustment_ratio",
                "pnl_adjustment_multiplier",
                "pnl_adjusted_quote_notional",
                "planned_quote_notional",
            ])
        product_columns.extend([
            "order_quote_size",
            "snapshot_limit_price",
            "quote_min_base_size_rounded_up",
            "quote_min_buy_notional",
            "taker_fee_estimate",
            "quote_min_buy_total_with_taker_fee",
        ])
        lines.extend(
            [
                "",
                ",".join(product_columns),
            ]
        )
        for row in result["products"]:
            lines.append(",".join(row[column] for column in product_columns))

    payload = "\n".join(lines)
    if output_path:
        output_path.write_text(payload + "\n", encoding="utf-8")
        return
    print(payload)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch Coinbase public market products, sum minimum-size costs, and "
            "emit a quote-minimum BUY snapshot for a separate purchase command."
        )
    )
    parser.add_argument("--quote", default="USDC", help="Quote currency to include. Default: USDC.")
    parser.add_argument("--venue", default="CBE", help="Coinbase product venue to include. Default: CBE.")
    parser.add_argument("--page-limit", type=int, default=250, help="Fallback API page size. Default: 250.")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds. Default: 30.")
    parser.add_argument(
        "--sort-by",
        choices=("product_id", "min_base_notional", "executable_min_notional", "quote_min_buy_notional"),
        default="product_id",
        help="Product row sort order. Default: product_id.",
    )
    parser.add_argument(
        "--taker-fee-rate",
        default="0.0010",
        help="Taker fee rate as a decimal for estimates. Default: 0.0010 (10 bps).",
    )
    parser.add_argument(
        "--pnl-adjusted-notional",
        action="store_true",
        help=(
            "Enable the new planned-notional mode: start from --default-notional "
            "and scale each product by its spot P/L ratio from the local fill-ledger "
            "P/L report."
        ),
    )
    parser.add_argument(
        "--default-notional",
        default=decimal_to_text(DEFAULT_PLANNED_QUOTE_NOTIONAL),
        help="Base quote notional used with --pnl-adjusted-notional. Default: 5.",
    )
    parser.add_argument(
        "--pnl-report",
        type=Path,
        help=(
            "Optional existing spot P/L report JSON override for --pnl-adjusted-notional. "
            "Accepts raw report payloads or wrapper payloads containing pnl_report."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("text", "json", "csv"),
        default="text",
        help="Output format. Default: text.",
    )
    parser.add_argument("--out", type=Path, help="Optional output path.")
    parser.add_argument(
        "--include-products",
        action="store_true",
        help="In text format, include one CSV-style line per product.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.page_limit <= 0:
        print("--page-limit must be positive", file=sys.stderr)
        return 2
    try:
        taker_fee_rate = Decimal(str(args.taker_fee_rate))
    except InvalidOperation:
        print("--taker-fee-rate must be a decimal, e.g. 0.0010", file=sys.stderr)
        return 2
    if taker_fee_rate < 0:
        print("--taker-fee-rate must be non-negative", file=sys.stderr)
        return 2
    try:
        default_quote_notional = Decimal(str(args.default_notional))
    except InvalidOperation:
        print("--default-notional must be a decimal, e.g. 5", file=sys.stderr)
        return 2
    if default_quote_notional <= 0:
        print("--default-notional must be positive", file=sys.stderr)
        return 2
    pnl_adjusted_notional_enabled = bool(args.pnl_adjusted_notional or args.pnl_report)

    raw_products = fetch_products(page_limit=args.page_limit, timeout_seconds=args.timeout)
    products = dedupe_products(raw_products)
    minimums, skipped_missing_required_fields = collect_minimums(
        products,
        quote=args.quote.upper(),
        venue=args.venue.upper(),
    )
    pnl_report_source = PNL_REPORT_SOURCE_NONE
    pnl_adjustments: dict[str, ProductPnlAdjustment] = {}
    if pnl_adjusted_notional_enabled:
        try:
            if args.pnl_report:
                pnl_report_source = PNL_REPORT_SOURCE_FILE
                pnl_adjustments = load_pnl_adjustments(args.pnl_report)
            else:
                report, pnl_report_source = build_local_spot_pnl_report(
                    products=products,
                    product_ids=[item.product_id for item in minimums],
                )
                pnl_adjustments = pnl_adjustments_from_report(report)
        except Exception as exc:
            print(f"Failed to build spot P/L adjustments: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
    minimums = sort_minimums(
        minimums,
        args.sort_by,
        default_quote_notional=default_quote_notional,
        pnl_adjustments=pnl_adjustments,
        pnl_adjusted_notional_enabled=pnl_adjusted_notional_enabled,
    )

    result = build_result(
        minimums,
        quote=args.quote.upper(),
        venue=args.venue.upper(),
        raw_fetched_product_count=len(raw_products),
        unique_fetched_product_count=len(products),
        skipped_missing_required_fields=skipped_missing_required_fields,
        taker_fee_rate=taker_fee_rate,
        default_quote_notional=default_quote_notional,
        pnl_adjustments=pnl_adjustments,
        pnl_report_path=args.pnl_report,
        pnl_report_source=pnl_report_source,
        pnl_adjusted_notional_enabled=pnl_adjusted_notional_enabled,
    )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)

    if args.format == "csv":
        write_csv(result, args.out)
    elif args.format == "json":
        write_json(result, args.out)
    else:
        write_text_summary(result, include_products=args.include_products, output_path=args.out)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
