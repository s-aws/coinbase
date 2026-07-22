"""No-retry Coinbase reader for one V7-V9 minimum-size proposal."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
from inspect import getattr_static
from typing import Any, Callable, Mapping
from uuid import UUID

from core.operator_spot_minimum_size_evidence import (
    minimum_size_preparation_evidence_sha256,
)

from .operator_spot_minimum_size_policy import (
    MINIMUM_SIZE_POLICY_REVISION,
    MinimumSizeBuyPlan,
    MinimumSizePolicyBlocked,
    derive_minimum_size_buy_plan,
)


_CATEGORIES = (
    "API_KEY_PERMISSIONS",
    "PORTFOLIO_CATALOG",
    "ACCOUNT_WALLET_BALANCES",
    "PRODUCT_METADATA",
    "BEST_BID_ASK",
    "FEE_SUMMARY",
)


class MinimumSizePreparationOutcome(str, Enum):
    MATERIALIZED = "MATERIALIZED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class MinimumSizePreparationResult:
    outcome: MinimumSizePreparationOutcome
    diagnostic_code: str
    completed_categories: tuple[str, ...]
    coinbase_api_call_count: int | None
    call_count_exact: bool
    evidence_sha256: str | None
    plan: MinimumSizeBuyPlan | None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _field(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, Mapping) else getattr(
        value,
        name,
        default,
    )


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (AttributeError, InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _aware_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _result(
    *,
    outcome: MinimumSizePreparationOutcome,
    diagnostic_code: str,
    completed: list[str],
    call_count: int | None,
    plan: MinimumSizeBuyPlan | None = None,
    portfolio_id_sha256: str | None = None,
) -> MinimumSizePreparationResult:
    exact = call_count is not None
    evidence = None
    if exact:
        evidence = minimum_size_preparation_evidence_sha256(
            call_count=call_count,
            categories=completed,
            diagnostic_code=diagnostic_code,
            outcome=outcome.value,
            policy_revision=MINIMUM_SIZE_POLICY_REVISION,
            plan=(
                {
                    "base_size": plan.base_size,
                    "limit_price": plan.limit_price,
                    "max_possible_execution_notional_usdc": (
                        plan.max_possible_execution_notional_usdc
                    ),
                    "max_submitted_notional_usdc": (
                        plan.max_submitted_notional_usdc
                    ),
                    "possible_execution_notional_usdc": (
                        plan.possible_execution_notional_usdc
                    ),
                    "post_only": plan.post_only,
                    "portfolio_id_sha256": portfolio_id_sha256,
                    "product_id": plan.product_id,
                    "side": plan.side,
                    "submitted_notional_usdc": plan.submitted_notional_usdc,
                    "v4_boundary_classification": (
                        plan.v4_boundary_classification
                    ),
                }
                if plan is not None
                else None
            ),
        )
    return MinimumSizePreparationResult(
        outcome=outcome,
        diagnostic_code=diagnostic_code,
        completed_categories=tuple(completed),
        coinbase_api_call_count=call_count,
        call_count_exact=exact,
        evidence_sha256=evidence,
        plan=plan,
    )


def _blocked(
    code: str,
    *,
    completed: list[str],
    call_count: int,
) -> MinimumSizePreparationResult:
    return _result(
        outcome=MinimumSizePreparationOutcome.BLOCKED,
        diagnostic_code=code,
        completed=completed,
        call_count=call_count,
    )


def _unknown(
    completed: list[str],
    diagnostic_code: str = "automation_minimum_size_preparation_unknown",
) -> MinimumSizePreparationResult:
    return _result(
        outcome=MinimumSizePreparationOutcome.UNKNOWN,
        diagnostic_code=diagnostic_code,
        completed=completed,
        call_count=None,
    )


def run_minimum_size_candidate_preparation(
    *,
    rest_client: Any,
    approved_portfolio_id: str,
    approved_portfolio_label: str,
    now_factory: Callable[[], datetime],
) -> MinimumSizePreparationResult:
    """Read six approved categories once and derive no caller-owned term."""

    try:
        if (
            str(UUID(approved_portfolio_id)) != approved_portfolio_id
            or approved_portfolio_label != "Test"
            or rest_client is None
            or not callable(now_factory)
        ):
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        return _blocked(
            "automation_minimum_size_portfolio_configuration_invalid",
            completed=[],
            call_count=0,
        )

    completed: list[str] = []
    request_count = 0

    def method(name: str) -> tuple[Callable[..., Any] | None, bool]:
        missing = object()
        try:
            statically_missing = (
                getattr_static(rest_client, name, missing) is missing
            )
            dynamic_lookup = (
                getattr_static(type(rest_client), "__getattr__", missing)
                is not missing
            )
        except Exception:
            return None, True
        if statically_missing and not dynamic_lookup:
            return None, False
        try:
            value = getattr(rest_client, name)
        except Exception:
            return None, True
        return (value if callable(value) else None), False

    permissions_method, permissions_lookup_unknown = method(
        "get_api_key_permissions"
    )
    if permissions_lookup_unknown:
        return _unknown(
            completed,
            "automation_minimum_size_api_key_permissions_unknown",
        )
    if permissions_method is None:
        return _blocked(
            "automation_minimum_size_api_key_permissions_rejected",
            completed=completed,
            call_count=request_count,
        )
    try:
        permissions = _mapping(permissions_method())
        request_count += 1
    except Exception:
        return _unknown(
            completed,
            "automation_minimum_size_api_key_permissions_unknown",
        )
    if not (
        str(
            permissions.get("portfolio_uuid")
            or permissions.get("portfolio_id")
            or ""
        ).strip()
        == approved_portfolio_id
        and str(permissions.get("portfolio_type") or "").strip().upper()
        == "CONSUMER"
        and permissions.get("can_view") is True
        and permissions.get("can_trade") is True
    ):
        return _blocked(
            "automation_minimum_size_api_key_permissions_rejected",
            completed=completed,
            call_count=request_count,
        )
    completed.append(_CATEGORIES[0])

    portfolios_method, portfolios_lookup_unknown = method("list_portfolios")
    if portfolios_lookup_unknown:
        return _unknown(
            completed,
            "automation_minimum_size_portfolio_catalog_unknown",
        )
    if portfolios_method is None:
        return _blocked(
            "automation_minimum_size_portfolio_catalog_rejected",
            completed=completed,
            call_count=request_count,
        )
    try:
        portfolios = portfolios_method()
        request_count += 1
    except Exception:
        return _unknown(
            completed,
            "automation_minimum_size_portfolio_catalog_unknown",
        )
    matches = (
        [
            _mapping(row)
            for row in portfolios
            if str(_mapping(row).get("uuid") or "").strip()
            == approved_portfolio_id
        ]
        if isinstance(portfolios, list)
        else []
    )
    if not (
        len(matches) == 1
        and str(matches[0].get("name") or "").strip() == "Test"
        and str(matches[0].get("type") or "").strip().upper() == "CONSUMER"
    ):
        return _blocked(
            "automation_minimum_size_portfolio_catalog_rejected",
            completed=completed,
            call_count=request_count,
        )
    completed.append(_CATEGORIES[1])

    wallets_method, wallets_lookup_unknown = method(
        "get_account_wallets_strict"
    )
    if wallets_lookup_unknown:
        return _unknown(
            completed,
            "automation_minimum_size_wallet_balances_unknown",
        )
    if wallets_method is None:
        return _blocked(
            "automation_minimum_size_wallet_balances_rejected",
            completed=completed,
            call_count=request_count,
        )
    try:
        wallet_read = wallets_method()
    except Exception:
        return _unknown(
            completed,
            "automation_minimum_size_wallet_balances_unknown",
        )
    wallet_requests = _field(wallet_read, "request_count")
    wallet_pages = _field(wallet_read, "page_count")
    if (
        type(wallet_requests) is not int
        or wallet_requests < 1
        or type(wallet_pages) is not int
        or wallet_pages != wallet_requests
    ):
        return _unknown(
            completed,
            "automation_minimum_size_wallet_balances_unknown",
        )
    request_count += wallet_requests
    portfolio_ids = {
        str(item).strip()
        for item in (_field(wallet_read, "portfolio_ids", ()) or ())
        if str(item or "").strip()
    }
    wallets = _field(wallet_read, "wallets", {})
    wallet_map = wallets if isinstance(wallets, Mapping) else {}
    usdc = wallet_map.get("USDC")
    available_usdc = _decimal(_field(usdc, "available_balance"))
    total_usdc = _decimal(_field(usdc, "total_balance"))
    if not (
        _field(wallet_read, "complete") is True
        and _field(wallet_read, "blocker") is None
        and portfolio_ids == {approved_portfolio_id}
        and str(_field(usdc, "currency") or "").upper() == "USDC"
        and available_usdc is not None
        and total_usdc is not None
        and available_usdc >= 0
        and total_usdc >= available_usdc
    ):
        return _blocked(
            "automation_minimum_size_wallet_balances_rejected",
            completed=completed,
            call_count=request_count,
        )
    completed.append(_CATEGORIES[2])

    products_method, products_lookup_unknown = method("get_products_batch")
    if products_lookup_unknown:
        return _unknown(
            completed,
            "automation_minimum_size_product_metadata_unknown",
        )
    if products_method is None:
        return _blocked(
            "automation_minimum_size_product_metadata_rejected",
            completed=completed,
            call_count=request_count,
        )
    try:
        product_map = products_method(["BTC-USDC"])
        request_count += 1
    except Exception:
        return _unknown(
            completed,
            "automation_minimum_size_product_metadata_unknown",
        )
    products = product_map if isinstance(product_map, Mapping) else {}
    product = _mapping(products.get("BTC-USDC"))
    increment_names = (
        "base_increment",
        "quote_increment",
        "price_increment",
        "base_min_size",
        "quote_min_size",
    )
    increments = {name: _decimal(product.get(name)) for name in increment_names}
    if not (
        set(products) == {"BTC-USDC"}
        and product.get("product_id") == "BTC-USDC"
        and str(product.get("product_type") or "").upper() == "SPOT"
        and str(product.get("base_currency_id") or "").upper() == "BTC"
        and str(product.get("quote_currency_id") or "").upper() == "USDC"
        and str(product.get("status") or "").upper() == "ONLINE"
        and not any(
            product.get(flag) is True
            for flag in (
                "trading_disabled",
                "is_disabled",
                "cancel_only",
                "view_only",
                "auction_mode",
            )
        )
        and all(value is not None and value > 0 for value in increments.values())
    ):
        return _blocked(
            "automation_minimum_size_product_metadata_rejected",
            completed=completed,
            call_count=request_count,
        )
    completed.append(_CATEGORIES[3])

    market_method, market_lookup_unknown = method("get_market_trades")
    if market_lookup_unknown:
        return _unknown(
            completed,
            "automation_minimum_size_best_bid_ask_unknown",
        )
    if market_method is None:
        return _blocked(
            "automation_minimum_size_best_bid_ask_rejected",
            completed=completed,
            call_count=request_count,
        )
    try:
        market = _mapping(market_method(product_id="BTC-USDC", limit=1))
        request_count += 1
    except Exception:
        return _unknown(
            completed,
            "automation_minimum_size_best_bid_ask_unknown",
        )
    trades = market.get("trades")
    trade = (
        _mapping(trades[0])
        if isinstance(trades, list) and len(trades) == 1
        else {}
    )
    market_time = _aware_utc(trade.get("time"))
    if trade.get("product_id") != "BTC-USDC" or market_time is None:
        return _blocked(
            "automation_minimum_size_best_bid_ask_rejected",
            completed=completed,
            call_count=request_count,
        )
    completed.append(_CATEGORIES[4])

    fee_method, fee_lookup_unknown = method("get_spot_transaction_summary")
    if fee_lookup_unknown:
        return _unknown(
            completed,
            "automation_minimum_size_fee_summary_unknown",
        )
    if fee_method is None:
        return _blocked(
            "automation_minimum_size_fee_summary_rejected",
            completed=completed,
            call_count=request_count,
        )
    try:
        fee_summary = _mapping(fee_method())
        request_count += 1
    except Exception:
        return _unknown(
            completed,
            "automation_minimum_size_fee_summary_unknown",
        )
    fee_tier = _mapping(fee_summary.get("fee_tier"))
    maker_fee = _decimal(fee_tier.get("maker_fee_rate"))
    taker_fee = _decimal(fee_tier.get("taker_fee_rate"))
    if not (
        maker_fee is not None
        and taker_fee is not None
        and Decimal("0") <= maker_fee < Decimal("1")
        and Decimal("0") <= taker_fee < Decimal("1")
    ):
        return _blocked(
            "automation_minimum_size_fee_summary_rejected",
            completed=completed,
            call_count=request_count,
        )
    completed.append(_CATEGORIES[5])

    try:
        plan = derive_minimum_size_buy_plan(
            product_id="BTC-USDC",
            best_bid=market.get("best_bid"),
            best_ask=market.get("best_ask"),
            market_observed_at=market_time,
            evaluated_at=now_factory(),
            base_increment=increments["base_increment"],
            quote_increment=increments["quote_increment"],
            price_increment=increments["price_increment"],
            base_min_size=increments["base_min_size"],
            quote_min_size=increments["quote_min_size"],
            available_usdc=available_usdc,
            maker_fee_rate=maker_fee,
        )
    except MinimumSizePolicyBlocked as exc:
        return _blocked(
            str(exc),
            completed=completed,
            call_count=request_count,
        )
    except Exception:
        return _unknown(completed)
    return _result(
        outcome=MinimumSizePreparationOutcome.MATERIALIZED,
        diagnostic_code=plan.v4_boundary_classification,
        completed=completed,
        call_count=request_count,
        plan=plan,
        portfolio_id_sha256=hashlib.sha256(
            approved_portfolio_id.encode("utf-8")
        ).hexdigest(),
    )
