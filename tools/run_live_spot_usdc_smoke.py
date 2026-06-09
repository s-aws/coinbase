"""Run an explicitly approved live Coinbase USDC spot smoke test.

This tool places real Coinbase Advanced Trade orders. It is intentionally kept
outside the default regression and external test gates.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_UP
from pathlib import Path
from typing import Any

from coinbase.rest import RESTClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from external.coinbase_client import coinbase_sdk_response_to_dict
from core.enums import SpotFillBackfillStatus, SpotLiveReconciliationGateStatus


SUMMARY_PREFIX = "LIVE_COINBASE_SPOT_SMOKE_SUMMARY "
DEFAULT_AUDIT_FILE = Path("runtime_state") / "live_spot_usdc_smoke.jsonl"


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True))
        handle.write("\n")


@dataclass
class LiveOrderReport:
    label: str
    product_id: str
    order_type: str
    side: str
    client_order_id: str
    exchange_order_id: str | None
    submitted_notional_usdc: str
    executed_notional_usdc: str
    status: str
    base_size: str | None = None
    response_success: bool | None = None
    error: str | None = None


def _decimal(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _format_decimal(value: Decimal) -> str:
    value = value.normalize()
    if value == value.to_integral():
        return str(value.quantize(Decimal("1")))
    return format(value, "f")


def _round_up_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    if increment <= 0:
        return value
    return (value / increment).to_integral_value(rounding=ROUND_UP) * increment


def _round_down_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    if increment <= 0:
        return value
    return (value / increment).to_integral_value(rounding=ROUND_DOWN) * increment


def _client_order_id(prefix: str) -> str:
    client_order_id = f"{prefix}-{uuid.uuid4().hex}"
    if len(client_order_id) > 40:
        raise ValueError("live smoke client_order_id prefix is too long")
    return client_order_id


def _dict(response: Any) -> Any:
    return coinbase_sdk_response_to_dict(response)


def _load_live_usdc_products(public_client: RESTClient) -> list[dict[str, Any]]:
    response = _dict(
        public_client.get_public_products(
            product_type="SPOT",
            get_all_products=True,
            get_tradability_status=True,
        )
    )
    products = []
    for product in response.get("products") or []:
        if product.get("quote_currency_id") != "USDC":
            continue
        if product.get("product_type") != "SPOT":
            continue
        if product.get("status") != "online":
            continue
        if any(
            product.get(flag)
            for flag in (
                "trading_disabled",
                "is_disabled",
                "cancel_only",
                "limit_only",
                "post_only",
                "view_only",
                "auction_mode",
            )
        ):
            continue
        price = _decimal(product.get("price"))
        quote_min = _decimal(product.get("quote_min_size"), "Infinity")
        if price <= 0 or not quote_min.is_finite():
            continue
        products.append(product)
    return sorted(
        products,
        key=lambda product: (
            _decimal(product.get("quote_min_size"), "Infinity"),
            _decimal(product.get("price")),
            product.get("product_id") or "",
        ),
    )


def _first_previewable_product(
    client: RESTClient,
    products: list[dict[str, Any]],
    requested_quote_size: Decimal | None,
) -> tuple[dict[str, Any], Decimal, dict[str, Any]]:
    errors = []
    for product in products:
        quote_increment = _decimal(product.get("quote_increment"), "0.01")
        quote_min = _decimal(product.get("quote_min_size"), "1")
        quote_size = requested_quote_size or quote_min
        quote_size = max(quote_size, quote_min)
        quote_size = _round_up_to_increment(quote_size, quote_increment)
        try:
            preview = _dict(
                client.preview_market_order_buy(
                    product_id=product["product_id"],
                    quote_size=_format_decimal(quote_size),
                )
            )
        except Exception as exc:  # pragma: no cover - live integration path
            errors.append((product.get("product_id"), str(exc).splitlines()[0]))
            continue
        if preview.get("errs"):
            errors.append((product.get("product_id"), str(preview.get("errs"))))
            continue
        return product, quote_size, preview
    raise RuntimeError(f"No previewable live USDC spot product found: {errors[:5]}")


def _extract_order(response: dict[str, Any]) -> dict[str, Any]:
    if isinstance(response.get("order"), dict):
        return response["order"]
    return response


def _extract_order_id(response: dict[str, Any]) -> str | None:
    success = response.get("success_response") or {}
    return success.get("order_id") or response.get("order_id")


def _response_success(response: dict[str, Any]) -> bool | None:
    success = response.get("success")
    if isinstance(success, bool):
        return success
    if response.get("success_response"):
        return True
    if response.get("error_response") or response.get("failure_reason"):
        return False
    return None


def _poll_order(client: RESTClient, order_id: str, timeout_seconds: float = 15.0) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = _extract_order(_dict(client.get_order(order_id)))
        status = str(last.get("status") or "").upper()
        if status in {"FILLED", "CANCELLED", "EXPIRED", "FAILED", "REJECTED"}:
            return last
        time.sleep(0.5)
    return last


def _fills_notional_and_size(
    client: RESTClient,
    product_id: str,
    order_id: str,
) -> tuple[Decimal, Decimal]:
    fills = _dict(
        client.get_fills(
            order_ids=[order_id],
            limit=100,
        )
    ).get("fills") or []
    total_size = Decimal("0")
    total_notional = Decimal("0")
    for fill in fills:
        size = _decimal(fill.get("size") or fill.get("base_size"))
        price = _decimal(fill.get("price"))
        if fill.get("size_in_quote") is True:
            total_notional += size
            if price > 0:
                total_size += size / price
            continue
        total_size += size
        total_notional += size * price
    return total_size, total_notional


def _order_executed_notional(
    client: RESTClient,
    product_id: str,
    order_id: str | None,
    fallback_order: dict[str, Any] | None = None,
) -> tuple[Decimal, Decimal]:
    if not order_id:
        return Decimal("0"), Decimal("0")
    fill_size, fill_notional = _fills_notional_and_size(client, product_id, order_id)
    if fill_notional > 0:
        return fill_size, fill_notional
    order = fallback_order or _poll_order(client, order_id)
    size = _decimal(
        order.get("filled_size")
        or order.get("filled_value")
        or order.get("cumulative_quantity")
    )
    average_price = _decimal(order.get("average_filled_price"))
    return size, size * average_price


def _submit_limit_cancel_smoke(
    client: RESTClient,
    product: dict[str, Any],
    quote_size: Decimal,
    market_preview: dict[str, Any],
) -> LiveOrderReport:
    product_id = product["product_id"]
    price_increment = _decimal(product.get("price_increment"), "0.01")
    base_increment = _decimal(product.get("base_increment"), "0.00000001")
    best_bid = _decimal(market_preview.get("best_bid") or product.get("price"))
    limit_price = max(price_increment, best_bid - price_increment)
    limit_price = _round_down_to_increment(limit_price, price_increment)
    if limit_price <= 0:
        limit_price = price_increment

    base_size = _round_up_to_increment(quote_size / limit_price, base_increment)
    submitted_notional = base_size * limit_price
    client_order_id = _client_order_id("lslb")
    response: dict[str, Any] = {}
    order_id: str | None = None
    status = "unknown"
    error: str | None = None

    try:
        response = _dict(
            client.limit_order_gtc(
                client_order_id=client_order_id,
                product_id=product_id,
                side="BUY",
                base_size=_format_decimal(base_size),
                limit_price=_format_decimal(limit_price),
                post_only=True,
            )
        )
        order_id = _extract_order_id(response)
        status = "submitted"
        if order_id:
            try:
                client.cancel_orders([order_id])
            finally:
                status = _poll_order(client, order_id, timeout_seconds=10).get(
                    "status",
                    "cancel_requested",
                )
    except Exception as exc:  # pragma: no cover - live integration path
        error = str(exc).splitlines()[0]
        status = "error"

    _, executed_notional = _order_executed_notional(client, product_id, order_id)
    return LiveOrderReport(
        label="post_only_limit_buy_cancel",
        product_id=product_id,
        order_type="limit_gtc_post_only",
        side="BUY",
        client_order_id=client_order_id,
        exchange_order_id=order_id,
        submitted_notional_usdc=_format_decimal(submitted_notional),
        executed_notional_usdc=_format_decimal(executed_notional),
        status=str(status),
        response_success=_response_success(response),
        error=error,
    )


def _submit_limit_sell_cancel_smoke(
    client: RESTClient,
    product: dict[str, Any],
    base_size: Decimal,
    market_preview: dict[str, Any],
) -> LiveOrderReport:
    product_id = product["product_id"]
    price_increment = _decimal(product.get("price_increment"), "0.01")
    base_increment = _decimal(product.get("base_increment"), "0.00000001")
    best_ask = _decimal(market_preview.get("best_ask") or product.get("price"))
    limit_price = _round_up_to_increment(best_ask + price_increment, price_increment)
    sell_size = _round_down_to_increment(base_size, base_increment)
    submitted_notional = sell_size * limit_price
    client_order_id = _client_order_id("lsls")
    response: dict[str, Any] = {}
    order_id: str | None = None
    status = "unknown"
    error: str | None = None

    if sell_size <= 0:
        return LiveOrderReport(
            label="post_only_limit_sell_cancel",
            product_id=product_id,
            order_type="limit_gtc_post_only",
            side="SELL",
            client_order_id=client_order_id,
            exchange_order_id=None,
            submitted_notional_usdc="0",
            executed_notional_usdc="0",
            status="skipped",
            base_size="0",
            response_success=None,
            error="No rounded base inventory available for limit sell smoke.",
        )

    try:
        response = _dict(
            client.limit_order_gtc(
                client_order_id=client_order_id,
                product_id=product_id,
                side="SELL",
                base_size=_format_decimal(sell_size),
                limit_price=_format_decimal(limit_price),
                post_only=True,
            )
        )
        order_id = _extract_order_id(response)
        status = "submitted"
        if order_id:
            try:
                client.cancel_orders([order_id])
            finally:
                status = _poll_order(client, order_id, timeout_seconds=10).get(
                    "status",
                    "cancel_requested",
                )
    except Exception as exc:  # pragma: no cover - live integration path
        error = str(exc).splitlines()[0]
        status = "error"

    _, executed_notional = _order_executed_notional(client, product_id, order_id)
    return LiveOrderReport(
        label="post_only_limit_sell_cancel",
        product_id=product_id,
        order_type="limit_gtc_post_only",
        side="SELL",
        client_order_id=client_order_id,
        exchange_order_id=order_id,
        submitted_notional_usdc=_format_decimal(submitted_notional),
        executed_notional_usdc=_format_decimal(executed_notional),
        status=str(status),
        base_size=_format_decimal(sell_size),
        response_success=_response_success(response),
        error=error,
    )


def _submit_market_round_trip_smoke(
    client: RESTClient,
    product: dict[str, Any],
    quote_size: Decimal,
    *,
    retain_inventory: bool = False,
) -> list[LiveOrderReport]:
    product_id = product["product_id"]
    base_increment = _decimal(product.get("base_increment"), "0.00000001")
    quote_text = _format_decimal(quote_size)

    buy_client_order_id = _client_order_id("lsmb")
    buy_response = _dict(
        client.market_order_buy(
            client_order_id=buy_client_order_id,
            product_id=product_id,
            quote_size=quote_text,
        )
    )
    buy_order_id = _extract_order_id(buy_response)
    buy_order = _poll_order(client, buy_order_id) if buy_order_id else {}
    bought_size, buy_executed_notional = _order_executed_notional(
        client,
        product_id,
        buy_order_id,
        buy_order,
    )
    buy_report = LiveOrderReport(
        label="market_buy",
        product_id=product_id,
        order_type="market_ioc",
        side="BUY",
        client_order_id=buy_client_order_id,
        exchange_order_id=buy_order_id,
        submitted_notional_usdc=quote_text,
        executed_notional_usdc=_format_decimal(buy_executed_notional),
        status=str(buy_order.get("status") or "submitted"),
        base_size=_format_decimal(bought_size),
        response_success=_response_success(buy_response),
    )

    sell_size = _round_down_to_increment(bought_size, base_increment)
    if retain_inventory:
        return [
            buy_report,
            LiveOrderReport(
                label="market_sell",
                product_id=product_id,
                order_type="market_ioc",
                side="SELL",
                client_order_id="",
                exchange_order_id=None,
                submitted_notional_usdc="0",
                executed_notional_usdc="0",
                status="skipped_retained_inventory",
                base_size=_format_decimal(sell_size),
                response_success=None,
                error=(
                    "Market sell skipped by --retain-inventory; acquired base "
                    "is intentionally left in the account."
                ),
            ),
        ]
    if sell_size <= 0:
        return [
            buy_report,
            LiveOrderReport(
                label="market_sell",
                product_id=product_id,
                order_type="market_ioc",
                side="SELL",
                client_order_id="",
                exchange_order_id=None,
                submitted_notional_usdc="0",
                executed_notional_usdc="0",
                status="skipped",
                base_size="0",
                response_success=None,
                error="No filled base size available to sell after market buy.",
            ),
        ]

    sell_client_order_id = _client_order_id("lsms")
    sell_response = _dict(
        client.market_order_sell(
            client_order_id=sell_client_order_id,
            product_id=product_id,
            base_size=_format_decimal(sell_size),
        )
    )
    sell_order_id = _extract_order_id(sell_response)
    sell_order = _poll_order(client, sell_order_id) if sell_order_id else {}
    _, sell_executed_notional = _order_executed_notional(
        client,
        product_id,
        sell_order_id,
        sell_order,
    )
    submitted_sell_notional = sell_size * _decimal(
        sell_order.get("average_filled_price") or product.get("price")
    )
    sell_report = LiveOrderReport(
        label="market_sell",
        product_id=product_id,
        order_type="market_ioc",
        side="SELL",
        client_order_id=sell_client_order_id,
        exchange_order_id=sell_order_id,
        submitted_notional_usdc=_format_decimal(submitted_sell_notional),
        executed_notional_usdc=_format_decimal(sell_executed_notional),
        status=str(sell_order.get("status") or "submitted"),
        base_size=_format_decimal(sell_size),
        response_success=_response_success(sell_response),
    )
    return [buy_report, sell_report]


def _submit_validation_matrix_smoke(
    client: RESTClient,
    product: dict[str, Any],
    quote_size: Decimal,
    market_preview: dict[str, Any],
    *,
    retain_inventory: bool = False,
) -> list[LiveOrderReport]:
    product_id = product["product_id"]
    base_increment = _decimal(product.get("base_increment"), "0.00000001")
    quote_text = _format_decimal(quote_size)

    buy_client_order_id = _client_order_id("lmb")
    buy_response = _dict(
        client.market_order_buy(
            client_order_id=buy_client_order_id,
            product_id=product_id,
            quote_size=quote_text,
        )
    )
    buy_order_id = _extract_order_id(buy_response)
    buy_order = _poll_order(client, buy_order_id) if buy_order_id else {}
    bought_size, buy_executed_notional = _order_executed_notional(
        client,
        product_id,
        buy_order_id,
        buy_order,
    )
    reports = [
        LiveOrderReport(
            label="matrix_market_buy",
            product_id=product_id,
            order_type="market_ioc",
            side="BUY",
            client_order_id=buy_client_order_id,
            exchange_order_id=buy_order_id,
            submitted_notional_usdc=quote_text,
            executed_notional_usdc=_format_decimal(buy_executed_notional),
            status=str(buy_order.get("status") or "submitted"),
            base_size=_format_decimal(bought_size),
            response_success=_response_success(buy_response),
        )
    ]

    reports.append(
        _submit_limit_cancel_smoke(
            client,
            product,
            quote_size,
            market_preview,
        )
    )

    sell_size = _round_down_to_increment(bought_size, base_increment)
    reports.append(
        _submit_limit_sell_cancel_smoke(
            client,
            product,
            sell_size,
            market_preview,
        )
    )

    if retain_inventory:
        reports.append(
            LiveOrderReport(
                label="matrix_market_sell",
                product_id=product_id,
                order_type="market_ioc",
                side="SELL",
                client_order_id="",
                exchange_order_id=None,
                submitted_notional_usdc="0",
                executed_notional_usdc="0",
                status="skipped_retained_inventory",
                base_size=_format_decimal(sell_size),
                response_success=None,
                error=(
                    "Market sell skipped by --retain-inventory; acquired base "
                    "is intentionally left in the account."
                ),
            )
        )
        return reports

    if sell_size <= 0:
        reports.append(
            LiveOrderReport(
                label="matrix_market_sell",
                product_id=product_id,
                order_type="market_ioc",
                side="SELL",
                client_order_id="",
                exchange_order_id=None,
                submitted_notional_usdc="0",
                executed_notional_usdc="0",
                status="skipped",
                base_size="0",
                response_success=None,
                error="No filled base size available to sell after market buy.",
            )
        )
        return reports

    sell_client_order_id = _client_order_id("lms")
    sell_response = _dict(
        client.market_order_sell(
            client_order_id=sell_client_order_id,
            product_id=product_id,
            base_size=_format_decimal(sell_size),
        )
    )
    sell_order_id = _extract_order_id(sell_response)
    sell_order = _poll_order(client, sell_order_id) if sell_order_id else {}
    _, sell_executed_notional = _order_executed_notional(
        client,
        product_id,
        sell_order_id,
        sell_order,
    )
    submitted_sell_notional = sell_size * _decimal(
        sell_order.get("average_filled_price") or product.get("price")
    )
    reports.append(
        LiveOrderReport(
            label="matrix_market_sell",
            product_id=product_id,
            order_type="market_ioc",
            side="SELL",
            client_order_id=sell_client_order_id,
            exchange_order_id=sell_order_id,
            submitted_notional_usdc=_format_decimal(submitted_sell_notional),
            executed_notional_usdc=_format_decimal(sell_executed_notional),
            status=str(sell_order.get("status") or "submitted"),
            base_size=_format_decimal(sell_size),
            response_success=_response_success(sell_response),
        )
    )
    return reports


def _build_summary(
    *,
    product: dict[str, Any],
    quote_size: Decimal,
    preview: dict[str, Any],
    reports: list[LiveOrderReport],
) -> dict[str, Any]:
    total_submitted = sum(
        _decimal(report.submitted_notional_usdc) for report in reports
    )
    total_executed = sum(
        _decimal(report.executed_notional_usdc) for report in reports
    )
    retained_base_by_product: dict[str, str] = {}
    for report in reports:
        if report.status != "skipped_retained_inventory":
            continue
        retained = _decimal(report.base_size)
        if retained <= 0:
            continue
        current = _decimal(retained_base_by_product.get(report.product_id))
        retained_base_by_product[report.product_id] = _format_decimal(
            current + retained
        )
    return {
        "live_coinbase_orders_ran": True,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "product_selection": {
            "product_id": product.get("product_id"),
            "selection_rule": (
                "lowest quote_min_size, then lowest price, among online "
                "tradable USDC-quoted SPOT products previewable for this account"
            ),
            "quote_min_size": product.get("quote_min_size"),
            "quote_size_used": _format_decimal(quote_size),
            "price_at_selection": product.get("price"),
            "base_increment": product.get("base_increment"),
            "quote_increment": product.get("quote_increment"),
            "market_preview_best_bid": preview.get("best_bid"),
            "market_preview_best_ask": preview.get("best_ask"),
        },
        "orders": [asdict(report) for report in reports],
        "retained_base_by_product": retained_base_by_product,
        "total_submitted_notional_usdc": _format_decimal(total_submitted),
        "total_executed_notional_usdc": _format_decimal(total_executed),
    }


def _backfill_live_smoke_fills(
    *,
    client: RESTClient,
    reports: list[LiveOrderReport],
) -> dict[str, Any]:
    try:
        from business.fill_ledger import FillLedgerRepository
        from business.spot_fill_backfill import (
            backfill_fill_ledger_from_order_reports,
        )
        from database.database import PostgresDB

        return backfill_fill_ledger_from_order_reports(
            fill_ledger_repo=FillLedgerRepository(PostgresDB()),
            rest_client=client,
            order_reports=[asdict(report) for report in reports],
        )
    except Exception as exc:  # pragma: no cover - depends on local DB wiring
        return {
            "total_order_count": len(reports),
            "total_fetched_fill_count": 0,
            "total_appended_fill_count": 0,
            "total_skipped_fill_count": 0,
            "orders": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


def _build_reconciliation_gate(summary: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    backfill = summary.get("fill_backfill") or {}
    if backfill.get("error"):
        failures.append(f"fill backfill failed: {backfill['error']}")

    backfill_by_order = {
        order.get("exchange_order_id"): order
        for order in backfill.get("orders") or []
        if isinstance(order, dict) and order.get("exchange_order_id")
    }
    market_reports = [
        order
        for order in summary.get("orders") or []
        if isinstance(order, dict)
        and "market" in str(order.get("label") or "")
        and order.get("exchange_order_id")
        and _decimal(order.get("executed_notional_usdc")) > 0
    ]
    if not market_reports:
        failures.append("no executed market order was available to reconcile")
    for report in market_reports:
        order_id = report.get("exchange_order_id")
        backfill_order = backfill_by_order.get(order_id)
        if not backfill_order:
            failures.append(f"missing fill-ledger backfill report for {order_id}")
            continue
        if int(backfill_order.get("fetched_fill_count") or 0) <= 0:
            failures.append(f"no REST fills fetched for {order_id}")
        if backfill_order.get("status") == SpotFillBackfillStatus.ERROR.value:
            failures.append(
                f"fill-ledger backfill errored for {order_id}: "
                f"{backfill_order.get('error') or 'unknown error'}"
            )

    return {
        "status": (
            SpotLiveReconciliationGateStatus.FAILED.value
            if failures
            else SpotLiveReconciliationGateStatus.PASSED.value
        ),
        "checked_order_count": len(market_reports),
        "total_fetched_fill_count": backfill.get("total_fetched_fill_count", 0),
        "total_appended_fill_count": backfill.get("total_appended_fill_count", 0),
        "failures": failures,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Place explicitly approved live Coinbase USDC spot smoke orders "
            "and print notional reporting."
        )
    )
    parser.add_argument(
        "--approved-live-orders",
        action="store_true",
        help="Required. Confirms this run may place real Coinbase orders.",
    )
    parser.add_argument(
        "--quote-size",
        type=Decimal,
        default=None,
        help="Optional USDC market-buy quote size. Defaults to selected product quote_min_size.",
    )
    parser.add_argument(
        "--skip-limit",
        action="store_true",
        help="Skip the post-only limit submit/cancel smoke.",
    )
    parser.add_argument(
        "--skip-market",
        action="store_true",
        help="Skip the market buy/sell round-trip smoke.",
    )
    parser.add_argument(
        "--validation-matrix",
        action="store_true",
        help=(
            "Run market BUY, post-only limit BUY cancel, post-only limit SELL "
            "cancel, and market SELL on the selected cheapest USDC product."
        ),
    )
    parser.add_argument(
        "--audit-file",
        type=Path,
        default=DEFAULT_AUDIT_FILE,
        help="Durable JSONL audit file for live smoke summaries.",
    )
    parser.add_argument(
        "--skip-fill-backfill",
        action="store_true",
        help="Skip REST-fill backfill into fill_ledger after live smoke orders.",
    )
    parser.add_argument(
        "--reconciliation-gate",
        action="store_true",
        help="Require validation-matrix REST fills to reconcile into fill_ledger and exit nonzero on failure.",
    )
    parser.add_argument(
        "--retain-inventory",
        action="store_true",
        help=(
            "After the market buy, skip the market sell and intentionally "
            "leave acquired base inventory in the account for future sell tests."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.approved_live_orders:
        parser.error("--approved-live-orders is required because this places live orders")
    if args.validation_matrix and (args.skip_limit or args.skip_market):
        parser.error("--validation-matrix cannot be combined with --skip-limit or --skip-market")
    if args.reconciliation_gate and not args.validation_matrix:
        parser.error("--reconciliation-gate requires --validation-matrix")
    if args.reconciliation_gate and args.skip_fill_backfill:
        parser.error("--reconciliation-gate cannot be combined with --skip-fill-backfill")
    if not args.validation_matrix and args.skip_limit and args.skip_market:
        parser.error("At least one of limit or market smoke must run")
    if not os.environ.get("COINBASE_API_KEY") or not os.environ.get("COINBASE_API_SECRET"):
        parser.error("COINBASE_API_KEY and COINBASE_API_SECRET are required")

    client = RESTClient(
        api_key=os.environ["COINBASE_API_KEY"],
        api_secret=os.environ["COINBASE_API_SECRET"],
        rate_limit_headers=True,
    )
    public_client = RESTClient(rate_limit_headers=True)
    product, quote_size, preview = _first_previewable_product(
        client,
        _load_live_usdc_products(public_client),
        args.quote_size,
    )

    reports: list[LiveOrderReport] = []
    if args.validation_matrix:
        reports.extend(
            _submit_validation_matrix_smoke(
                client,
                product,
                quote_size,
                preview,
                retain_inventory=args.retain_inventory,
            )
        )
    elif not args.skip_limit:
        reports.append(
            _submit_limit_cancel_smoke(
                client,
                product,
                quote_size,
                preview,
            )
        )
    if not args.validation_matrix and not args.skip_market:
        reports.extend(
            _submit_market_round_trip_smoke(
                client,
                product,
                quote_size,
                retain_inventory=args.retain_inventory,
            )
        )

    summary = _build_summary(
        product=product,
        quote_size=quote_size,
        preview=preview,
        reports=reports,
    )
    summary["fill_backfill"] = (
        {
            "skipped": True,
            "reason": "--skip-fill-backfill supplied",
        }
        if args.skip_fill_backfill
        else _backfill_live_smoke_fills(client=client, reports=reports)
    )
    summary["audit_file"] = str(args.audit_file)
    if args.reconciliation_gate:
        summary["reconciliation_gate"] = _build_reconciliation_gate(summary)
    _append_jsonl(args.audit_file, {
        "record_type": "live_spot_usdc_smoke",
        **summary,
    })
    print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
    if (
        args.reconciliation_gate
        and summary["reconciliation_gate"]["status"]
        != SpotLiveReconciliationGateStatus.PASSED.value
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
