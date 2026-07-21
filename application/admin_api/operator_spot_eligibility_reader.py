"""Strict Coinbase readers for one approved operator Spot eligibility cycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from types import MappingProxyType
from typing import Any, Callable, Mapping
from uuid import UUID

from application.admin_api.command_service import (
    COINBASE_ACTIVE_SPOT_ORDER_QUERY,
    exact_coinbase_order_readback,
    read_authoritative_coinbase_orders,
)
from application.admin_api.operator_spot_eligibility import (
    SPOT_ELIGIBILITY_PRODUCT_ID,
    SpotEligibilityReadContext,
    SpotEligibilityReadOutcome,
    SpotEligibilityReadResult,
    SpotEligibilityRunContext,
    derive_spot_eligibility_client_order_id,
)
from core.action_condition_guard import evaluate_spot_standing_price_limit


_MAX_SUBMITTED_NOTIONAL_USDC = Decimal("3.10")
_MAX_POSSIBLE_EXECUTION_NOTIONAL_USDC = Decimal("1.00")
_MAX_EXACT_ORDER_PAGES = 100
_MAX_ACTIVE_ORDER_PAGES = 100


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        text = str(value).strip()
    except Exception:
        return None
    if not text or len(text) > 96:
        return None
    try:
        parsed = Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not parsed.is_finite():
        return None
    return parsed


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _aware_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text or len(text) > 80:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _evidence_hash(category: str, facts: Mapping[str, Any]) -> str:
    safe = {
        "category": category,
        **{
            str(key): value
            for key, value in facts.items()
            if value is None or isinstance(value, (str, int, bool))
        },
    }
    encoded = json.dumps(
        safe,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class SpotEligibilityPlanTerms:
    """Immutable backend plan values required by category validators."""

    plan_sha256: str
    product_id: str
    side: str
    base_size: str
    limit_price: str
    submitted_notional_usdc: str
    possible_execution_notional_usdc: str
    max_submitted_notional_usdc: str
    max_possible_execution_notional_usdc: str
    post_only: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.plan_sha256, str)
            or len(self.plan_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.plan_sha256)
        ):
            raise ValueError("spot_eligibility_reader_plan_hash_invalid")
        if self.product_id != SPOT_ELIGIBILITY_PRODUCT_ID:
            raise ValueError("spot_eligibility_reader_product_invalid")
        side = str(self.side).upper()
        if side not in {"BUY", "SELL"} or self.side != side:
            raise ValueError("spot_eligibility_reader_side_invalid")
        if type(self.post_only) is not bool or self.post_only is not False:
            raise ValueError("spot_eligibility_reader_post_only_invalid")
        base = _decimal(self.base_size)
        price = _decimal(self.limit_price)
        submitted = _decimal(self.submitted_notional_usdc)
        possible = _decimal(self.possible_execution_notional_usdc)
        submitted_cap = _decimal(self.max_submitted_notional_usdc)
        possible_cap = _decimal(self.max_possible_execution_notional_usdc)
        if (
            base is None
            or price is None
            or submitted is None
            or possible is None
            or min(base, price, submitted, possible) <= 0
            or submitted_cap != _MAX_SUBMITTED_NOTIONAL_USDC
            or possible_cap != _MAX_POSSIBLE_EXECUTION_NOTIONAL_USDC
            or base * price != submitted
            or submitted > submitted_cap
            or possible > possible_cap
            or possible > submitted
        ):
            raise ValueError("spot_eligibility_reader_plan_values_invalid")


@dataclass(frozen=True, slots=True, repr=False)
class SpotEligibilityPortfolioBindingSnapshot:
    """Transient exact Test-portfolio binding; never serialize or persist it."""

    retail_portfolio_id: str
    portfolio_id_sha256: str
    label: str
    portfolio_type: str
    can_view: bool
    can_trade: bool

    def __post_init__(self) -> None:
        try:
            parsed = UUID(self.retail_portfolio_id)
        except (AttributeError, TypeError, ValueError):
            raise ValueError("spot_eligibility_snapshot_portfolio_invalid") from None
        if (
            str(parsed) != self.retail_portfolio_id
            or not isinstance(self.portfolio_id_sha256, str)
            or len(self.portfolio_id_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.portfolio_id_sha256
            )
            or self.label != "Test"
            or self.portfolio_type != "CONSUMER"
            or self.can_view is not True
            or self.can_trade is not True
        ):
            raise ValueError("spot_eligibility_snapshot_portfolio_invalid")

    def __repr__(self) -> str:
        return "SpotEligibilityPortfolioBindingSnapshot(values=withheld)"


@dataclass(frozen=True, slots=True, repr=False)
class SpotEligibilityWalletSnapshot:
    """One immutable wallet balance retained only inside the request."""

    currency: str
    available_balance: Decimal
    total_balance: Decimal

    def __post_init__(self) -> None:
        if (
            self.currency not in {"BTC", "USDC"}
            or not isinstance(self.available_balance, Decimal)
            or not isinstance(self.total_balance, Decimal)
            or not self.available_balance.is_finite()
            or not self.total_balance.is_finite()
            or self.available_balance < 0
            or self.total_balance < self.available_balance
        ):
            raise ValueError("spot_eligibility_snapshot_wallet_invalid")

    def __repr__(self) -> str:
        return "SpotEligibilityWalletSnapshot(values=withheld)"


@dataclass(frozen=True, slots=True, repr=False)
class SpotEligibilityMarketReferenceSnapshot:
    """Typed BTC-USDC best-market evidence retained only for admission."""

    product_id: str
    best_bid: Decimal
    best_ask: Decimal
    observed_at: datetime

    def __post_init__(self) -> None:
        if (
            self.product_id != SPOT_ELIGIBILITY_PRODUCT_ID
            or not isinstance(self.best_bid, Decimal)
            or not isinstance(self.best_ask, Decimal)
            or not self.best_bid.is_finite()
            or not self.best_ask.is_finite()
            or self.best_bid <= 0
            or self.best_ask < self.best_bid
            or not isinstance(self.observed_at, datetime)
            or self.observed_at.tzinfo is None
            or self.observed_at.utcoffset() is None
        ):
            raise ValueError("spot_eligibility_snapshot_market_invalid")

    def __repr__(self) -> str:
        return "SpotEligibilityMarketReferenceSnapshot(values=withheld)"


@dataclass(frozen=True, slots=True, repr=False)
class SpotEligibilityExactOrderAbsenceSnapshot:
    """Typed proof that the deterministic child identity is absent."""

    client_order_id: str
    product_id: str
    page_count: int
    evidence_sha256: str

    def __post_init__(self) -> None:
        try:
            parsed = UUID(self.client_order_id)
        except (AttributeError, TypeError, ValueError):
            raise ValueError("spot_eligibility_snapshot_exact_absence_invalid") from None
        if (
            str(parsed) != self.client_order_id
            or self.product_id != SPOT_ELIGIBILITY_PRODUCT_ID
            or type(self.page_count) is not int
            or self.page_count < 1
            or not isinstance(self.evidence_sha256, str)
            or len(self.evidence_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.evidence_sha256
            )
        ):
            raise ValueError("spot_eligibility_snapshot_exact_absence_invalid")

    def __repr__(self) -> str:
        return "SpotEligibilityExactOrderAbsenceSnapshot(values=withheld)"


@dataclass(frozen=True, slots=True, repr=False)
class SpotEligibilityActiveOrderCatalogAbsenceSnapshot:
    """Typed proof of one complete account-wide zero-active-order catalog."""

    portfolio_id_sha256: str
    product_type: str
    page_count: int
    evidence_sha256: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.portfolio_id_sha256, str)
            or len(self.portfolio_id_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.portfolio_id_sha256
            )
            or self.product_type != "SPOT"
            or type(self.page_count) is not int
            or self.page_count < 1
            or not isinstance(self.evidence_sha256, str)
            or len(self.evidence_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.evidence_sha256
            )
        ):
            raise ValueError("spot_eligibility_snapshot_active_catalog_invalid")

    def __repr__(self) -> str:
        return "SpotEligibilityActiveOrderCatalogAbsenceSnapshot(values=withheld)"


@dataclass(frozen=True, slots=True, repr=False)
class SpotEligibilityReadSnapshot:
    """Read-only transient facts; this is evidence, not an execution gateway."""

    cycle_number: int
    plan_sha256: str
    portfolio: SpotEligibilityPortfolioBindingSnapshot
    wallets: Mapping[str, SpotEligibilityWalletSnapshot]
    market_reference: SpotEligibilityMarketReferenceSnapshot
    exact_order_absence: SpotEligibilityExactOrderAbsenceSnapshot
    active_order_catalog_absence: SpotEligibilityActiveOrderCatalogAbsenceSnapshot

    def __post_init__(self) -> None:
        if (
            type(self.cycle_number) is not int
            or not 1 <= self.cycle_number <= 10
            or not isinstance(self.plan_sha256, str)
            or len(self.plan_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.plan_sha256
            )
            or not isinstance(self.portfolio, SpotEligibilityPortfolioBindingSnapshot)
            or not isinstance(
                self.market_reference,
                SpotEligibilityMarketReferenceSnapshot,
            )
            or not isinstance(
                self.exact_order_absence,
                SpotEligibilityExactOrderAbsenceSnapshot,
            )
            or not isinstance(
                self.active_order_catalog_absence,
                SpotEligibilityActiveOrderCatalogAbsenceSnapshot,
            )
            or self.portfolio.portfolio_id_sha256
            != self.active_order_catalog_absence.portfolio_id_sha256
        ):
            raise ValueError("spot_eligibility_reader_snapshot_invalid")
        wallet_copy = dict(self.wallets)
        if (
            not wallet_copy
            or any(
                not isinstance(wallet, SpotEligibilityWalletSnapshot)
                or currency != wallet.currency
                for currency, wallet in wallet_copy.items()
            )
        ):
            raise ValueError("spot_eligibility_reader_snapshot_invalid")
        object.__setattr__(self, "wallets", MappingProxyType(wallet_copy))

    def __repr__(self) -> str:
        return "SpotEligibilityReadSnapshot(values=withheld)"


class CoinbaseApprovedSpotEligibilityReader:
    """One request-scoped, fail-closed adapter over the canonical REST client."""

    __slots__ = (
        "_active_order_catalog_absence",
        "_approved_portfolio_id",
        "_approved_portfolio_label",
        "_cycle_number",
        "_exact_order_absence",
        "_expected_context",
        "_market_reference",
        "_now_factory",
        "_permission_scope_ready",
        "_plan",
        "_portfolio_binding",
        "_rest_client",
        "_wallets",
    )

    def __init__(
        self,
        *,
        rest_client: Any,
        expected_context: SpotEligibilityRunContext,
        approved_portfolio_id: str,
        approved_portfolio_label: str,
        plan: SpotEligibilityPlanTerms,
        now_factory: Callable[[], datetime] = _utc_now,
    ) -> None:
        if rest_client is None:
            raise ValueError("spot_eligibility_reader_client_unavailable")
        if not isinstance(expected_context, SpotEligibilityRunContext):
            raise ValueError("spot_eligibility_reader_context_invalid")
        try:
            parsed_portfolio = UUID(approved_portfolio_id)
        except (AttributeError, TypeError, ValueError):
            raise ValueError("spot_eligibility_reader_portfolio_invalid") from None
        if str(parsed_portfolio) != approved_portfolio_id:
            raise ValueError("spot_eligibility_reader_portfolio_invalid")
        portfolio_hash = hashlib.sha256(
            approved_portfolio_id.encode("utf-8")
        ).hexdigest()
        if portfolio_hash != expected_context.portfolio_id_sha256:
            raise ValueError("spot_eligibility_reader_portfolio_mismatch")
        if approved_portfolio_label != "Test":
            raise ValueError("spot_eligibility_reader_portfolio_label_invalid")
        if not isinstance(plan, SpotEligibilityPlanTerms):
            raise ValueError("spot_eligibility_reader_plan_invalid")
        if plan.plan_sha256 != expected_context.plan_sha256:
            raise ValueError("spot_eligibility_reader_plan_mismatch")
        if not callable(now_factory):
            raise ValueError("spot_eligibility_reader_clock_invalid")
        self._rest_client = rest_client
        self._expected_context = expected_context
        self._approved_portfolio_id = approved_portfolio_id
        self._approved_portfolio_label = approved_portfolio_label
        self._plan = plan
        self._now_factory = now_factory
        self._permission_scope_ready = False
        self._cycle_number: int | None = None
        self._portfolio_binding: SpotEligibilityPortfolioBindingSnapshot | None = (
            None
        )
        self._wallets: Mapping[str, SpotEligibilityWalletSnapshot] | None = None
        self._market_reference: SpotEligibilityMarketReferenceSnapshot | None = (
            None
        )
        self._exact_order_absence: (
            SpotEligibilityExactOrderAbsenceSnapshot | None
        ) = None
        self._active_order_catalog_absence: (
            SpotEligibilityActiveOrderCatalogAbsenceSnapshot | None
        ) = None

    def __repr__(self) -> str:
        return "CoinbaseApprovedSpotEligibilityReader(scope=withheld)"

    def _now(self) -> datetime:
        value = self._now_factory()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("spot_eligibility_reader_clock_invalid")
        if value.utcoffset() is None:
            raise ValueError("spot_eligibility_reader_clock_invalid")
        return value.astimezone(timezone.utc)

    def _validate_context(self, context: SpotEligibilityReadContext) -> None:
        expected = self._expected_context
        expected_client_order_id = derive_spot_eligibility_client_order_id(
            run_id=expected.run_id,
            plan_sha256=expected.plan_sha256,
        )
        if (
            not isinstance(context, SpotEligibilityReadContext)
            or context.run_id != expected.run_id
            or context.definition_id != expected.definition_id
            or context.definition_revision != expected.definition_revision
            or context.plan_sha256 != expected.plan_sha256
            or context.portfolio_id_sha256 != expected.portfolio_id_sha256
            or context.correlation_id != expected.correlation_id
            or context.product_id != SPOT_ELIGIBILITY_PRODUCT_ID
            or context.client_order_id != expected_client_order_id
            or (
                self._cycle_number is not None
                and context.cycle_number != self._cycle_number
            )
        ):
            raise ValueError("spot_eligibility_reader_context_mismatch")
        if self._cycle_number is None:
            self._cycle_number = context.cycle_number

    def execution_snapshot(self) -> SpotEligibilityReadSnapshot:
        """Return complete transient typed facts without a serialization path."""

        if (
            not self._permission_scope_ready
            or self._cycle_number is None
            or self._portfolio_binding is None
            or self._wallets is None
            or self._market_reference is None
            or self._exact_order_absence is None
            or self._active_order_catalog_absence is None
        ):
            raise ValueError("spot_eligibility_reader_snapshot_incomplete")
        return SpotEligibilityReadSnapshot(
            cycle_number=self._cycle_number,
            plan_sha256=self._plan.plan_sha256,
            portfolio=self._portfolio_binding,
            wallets=self._wallets,
            market_reference=self._market_reference,
            exact_order_absence=self._exact_order_absence,
            active_order_catalog_absence=self._active_order_catalog_absence,
        )

    def _method(self, name: str) -> Callable[..., Any] | None:
        value = getattr(self._rest_client, name, None)
        return value if callable(value) else None

    def _succeeded(
        self,
        category: str,
        *,
        request_count: int,
        observed_at: datetime | None = None,
        facts: Mapping[str, Any] | None = None,
    ) -> SpotEligibilityReadResult:
        return SpotEligibilityReadResult(
            outcome=SpotEligibilityReadOutcome.SUCCEEDED,
            eligible=True,
            logical_call_count=1,
            http_request_count=request_count,
            call_count_exact=True,
            observed_at=observed_at or self._now(),
            evidence_sha256=_evidence_hash(category, facts or {"eligible": True}),
        )

    def _rejected(
        self,
        *,
        request_count: int,
        observed_at: datetime | None = None,
    ) -> SpotEligibilityReadResult:
        return SpotEligibilityReadResult(
            outcome=SpotEligibilityReadOutcome.REJECTED,
            eligible=False,
            logical_call_count=1,
            http_request_count=request_count,
            call_count_exact=True,
            observed_at=observed_at or self._now(),
        )

    def _unknown(
        self,
        *,
        observed_at: datetime | None = None,
    ) -> SpotEligibilityReadResult:
        return SpotEligibilityReadResult(
            outcome=SpotEligibilityReadOutcome.UNKNOWN,
            eligible=False,
            logical_call_count=1,
            http_request_count=None,
            call_count_exact=False,
            observed_at=observed_at or self._now(),
        )

    def read_api_key_permissions(
        self,
        context: SpotEligibilityReadContext,
    ) -> SpotEligibilityReadResult:
        self._validate_context(context)
        method = self._method("get_api_key_permissions")
        if method is None:
            return self._rejected(request_count=0)
        value = method()
        data = _mapping(value)
        observed_portfolio = str(
            data.get("portfolio_uuid") or data.get("portfolio_id") or ""
        ).strip()
        ready = bool(
            observed_portfolio == self._approved_portfolio_id
            and str(data.get("portfolio_type") or "").strip().upper()
            == "CONSUMER"
            and data.get("can_view") is True
            and data.get("can_trade") is True
        )
        self._permission_scope_ready = ready
        if not ready:
            self._portfolio_binding = None
        if not ready:
            return self._rejected(request_count=1)
        return self._succeeded(
            "API_KEY_PERMISSIONS",
            request_count=1,
            facts={
                "portfolio_matches": True,
                "portfolio_type": "CONSUMER",
                "can_view": True,
                "can_trade": True,
            },
        )

    def read_portfolio_catalog(
        self,
        context: SpotEligibilityReadContext,
    ) -> SpotEligibilityReadResult:
        self._validate_context(context)
        self._portfolio_binding = None
        method = self._method("list_portfolios")
        if method is None:
            return self._rejected(request_count=0)
        value = method()
        rows = value if isinstance(value, list) else None
        matches = (
            [
                _mapping(row)
                for row in rows
                if str(_mapping(row).get("uuid") or "").strip()
                == self._approved_portfolio_id
            ]
            if rows is not None
            else []
        )
        ready = bool(
            self._permission_scope_ready
            and rows is not None
            and len(matches) == 1
            and str(matches[0].get("name") or "").strip()
            == self._approved_portfolio_label
            and str(matches[0].get("type") or "").strip().upper()
            == "CONSUMER"
        )
        if not ready:
            return self._rejected(request_count=1)
        result = self._succeeded(
            "PORTFOLIO_CATALOG",
            request_count=1,
            facts={
                "exact_match_count": 1,
                "label_matches": True,
                "portfolio_type": "CONSUMER",
            },
        )
        self._portfolio_binding = SpotEligibilityPortfolioBindingSnapshot(
            retail_portfolio_id=self._approved_portfolio_id,
            portfolio_id_sha256=context.portfolio_id_sha256,
            label=self._approved_portfolio_label,
            portfolio_type="CONSUMER",
            can_view=True,
            can_trade=True,
        )
        return result

    def read_account_wallet_balances(
        self,
        context: SpotEligibilityReadContext,
    ) -> SpotEligibilityReadResult:
        self._validate_context(context)
        self._wallets = None
        method = self._method("get_account_wallets_strict")
        if method is None:
            return self._rejected(request_count=0)
        value = method()
        request_count = _field(value, "request_count")
        page_count = _field(value, "page_count")
        exact_count = (
            type(request_count) is int
            and request_count >= 1
            and type(page_count) is int
            and page_count == request_count
        )
        if not exact_count:
            raise ValueError("spot_eligibility_wallet_accounting_unknown")
        portfolios = {
            str(item).strip()
            for item in (_field(value, "portfolio_ids", ()) or ())
            if str(item or "").strip()
        }
        wallets = _field(value, "wallets", {})
        wallet_map = wallets if isinstance(wallets, Mapping) else {}
        required_currency = "USDC" if self._plan.side == "BUY" else "BTC"
        required_amount = _decimal(
            self._plan.submitted_notional_usdc
            if self._plan.side == "BUY"
            else self._plan.base_size
        )
        target = wallet_map.get(required_currency)
        available = _decimal(_field(target, "available_balance"))
        total = _decimal(_field(target, "total_balance"))
        ready = bool(
            _field(value, "complete") is True
            and _field(value, "blocker") is None
            and portfolios == {self._approved_portfolio_id}
            and str(_field(target, "currency") or "").strip().upper()
            == required_currency
            and required_amount is not None
            and available is not None
            and total is not None
            and available >= required_amount
            and total >= available
            and available >= 0
        )
        if not ready:
            return self._rejected(request_count=request_count)
        result = self._succeeded(
            "ACCOUNT_WALLET_BALANCES",
            request_count=request_count,
            facts={
                "complete": True,
                "page_count": page_count,
                "required_currency": required_currency,
                "sufficient": True,
            },
        )
        wallet_snapshots: dict[str, SpotEligibilityWalletSnapshot] = {}
        for currency in ("BTC", "USDC"):
            wallet = wallet_map.get(currency)
            available_value = _decimal(_field(wallet, "available_balance"))
            total_value = _decimal(_field(wallet, "total_balance"))
            observed_currency = str(_field(wallet, "currency") or "").upper()
            if (
                observed_currency == currency
                and available_value is not None
                and total_value is not None
                and available_value >= 0
                and total_value >= available_value
            ):
                wallet_snapshots[currency] = SpotEligibilityWalletSnapshot(
                    currency=currency,
                    available_balance=available_value,
                    total_balance=total_value,
                )
        self._wallets = MappingProxyType(wallet_snapshots)
        return result

    def read_product_metadata(
        self,
        context: SpotEligibilityReadContext,
    ) -> SpotEligibilityReadResult:
        self._validate_context(context)
        method = self._method("get_products_batch")
        if method is None:
            return self._rejected(request_count=0)
        value = method([SPOT_ELIGIBILITY_PRODUCT_ID])
        rows = value if isinstance(value, Mapping) else {}
        row = _mapping(rows.get(SPOT_ELIGIBILITY_PRODUCT_ID))
        increments = {
            name: _decimal(row.get(name))
            for name in (
                "base_increment",
                "quote_increment",
                "price_increment",
                "base_min_size",
                "quote_min_size",
            )
        }
        base = _decimal(self._plan.base_size)
        price = _decimal(self._plan.limit_price)
        submitted = _decimal(self._plan.submitted_notional_usdc)
        base_increment = increments["base_increment"]
        price_increment = increments["price_increment"]
        ready = bool(
            set(rows) == {SPOT_ELIGIBILITY_PRODUCT_ID}
            and row.get("product_id") == SPOT_ELIGIBILITY_PRODUCT_ID
            and str(row.get("product_type") or "").strip().upper() == "SPOT"
            and str(row.get("base_currency") or "").strip().upper() == "BTC"
            and str(row.get("quote_currency") or "").strip().upper() == "USDC"
            and str(row.get("status") or "").strip().upper() == "ONLINE"
            and not any(
                row.get(flag) is True
                for flag in (
                    "trading_disabled",
                    "is_disabled",
                    "cancel_only",
                    "view_only",
                    "auction_mode",
                )
            )
            and all(value is not None and value > 0 for value in increments.values())
            and base is not None
            and price is not None
            and submitted is not None
            and base_increment is not None
            and price_increment is not None
            and base % base_increment == 0
            and price % price_increment == 0
            and base >= increments["base_min_size"]
            and submitted >= increments["quote_min_size"]
        )
        if not ready:
            return self._rejected(request_count=1)
        return self._succeeded(
            "PRODUCT_METADATA",
            request_count=1,
            facts={
                "identity_matches": True,
                "product_type": "SPOT",
                "tradable": True,
                "plan_increments_valid": True,
            },
        )

    def read_best_bid_ask(
        self,
        context: SpotEligibilityReadContext,
    ) -> SpotEligibilityReadResult:
        self._validate_context(context)
        self._market_reference = None
        method = self._method("get_best_bid_ask")
        if method is None:
            return self._rejected(request_count=0)
        value = method(product_ids=[SPOT_ELIGIBILITY_PRODUCT_ID])
        pricebooks = _mapping(value).get("pricebooks")
        if not isinstance(pricebooks, list) or len(pricebooks) != 1:
            return self._rejected(request_count=1)
        row = _mapping(pricebooks[0])
        bids = row.get("bids")
        asks = row.get("asks")
        bid = (
            _decimal(_mapping(bids[0]).get("price"))
            if isinstance(bids, list) and bids
            else None
        )
        ask = (
            _decimal(_mapping(asks[0]).get("price"))
            if isinstance(asks, list) and asks
            else None
        )
        observed_at = _aware_utc(row.get("time"))
        standing = evaluate_spot_standing_price_limit(
            side=self._plan.side,
            limit_price=self._plan.limit_price,
            best_bid=bid,
            market_source="coinbase_rest_best_bid",
            market_observed_at=observed_at,
            evaluated_at=self._now(),
        )
        ready = bool(
            row.get("product_id") == SPOT_ELIGIBILITY_PRODUCT_ID
            and bid is not None
            and ask is not None
            and bid > 0
            and ask >= bid
            and observed_at is not None
            and standing.get("allowed") is True
        )
        if not ready:
            return self._rejected(
                request_count=1,
                observed_at=observed_at,
            )
        result = self._succeeded(
            "BEST_BID_ASK",
            request_count=1,
            observed_at=observed_at,
            facts={
                "identity_matches": True,
                "spread_valid": True,
                "standing_price_allowed": True,
            },
        )
        assert bid is not None and ask is not None and observed_at is not None
        self._market_reference = SpotEligibilityMarketReferenceSnapshot(
            product_id=SPOT_ELIGIBILITY_PRODUCT_ID,
            best_bid=bid,
            best_ask=ask,
            observed_at=observed_at,
        )
        return result

    def read_fee_summary(
        self,
        context: SpotEligibilityReadContext,
    ) -> SpotEligibilityReadResult:
        self._validate_context(context)
        method = self._method("get_spot_transaction_summary")
        if method is None:
            return self._rejected(request_count=0)
        value = method()
        fee_tier = _mapping(_mapping(value).get("fee_tier"))
        maker = _decimal(fee_tier.get("maker_fee_rate"))
        taker = _decimal(fee_tier.get("taker_fee_rate"))
        ready = bool(
            maker is not None
            and taker is not None
            and Decimal("0") <= maker < Decimal("1")
            and Decimal("0") <= taker < Decimal("1")
        )
        if not ready:
            return self._rejected(request_count=1)
        return self._succeeded(
            "FEE_SUMMARY",
            request_count=1,
            facts={"maker_fee_valid": True, "taker_fee_valid": True},
        )

    def read_exact_order_reconciliation(
        self,
        context: SpotEligibilityReadContext,
    ) -> SpotEligibilityReadResult:
        self._validate_context(context)
        self._exact_order_absence = None
        value = exact_coinbase_order_readback(
            self._rest_client,
            client_order_id=context.client_order_id,
            product_id=SPOT_ELIGIBILITY_PRODUCT_ID,
            product_type="SPOT",
            expected_retail_portfolio_id=self._approved_portfolio_id,
            maximum_list_pages=_MAX_EXACT_ORDER_PAGES,
        )
        page_count = value.get("page_count")
        if type(page_count) is not int or page_count < 1:
            raise ValueError("spot_eligibility_exact_order_accounting_unknown")
        ready = bool(
            value.get("authoritative") is True
            and value.get("pagination_complete") is True
            and value.get("confirmed_absent") is True
            and value.get("exact_identity_match") is False
            and value.get("matched_order") is None
        )
        if not ready:
            return self._rejected(request_count=page_count)
        result = self._succeeded(
            "EXACT_ORDER_RECONCILIATION",
            request_count=page_count,
            facts={
                "authoritative": True,
                "pagination_complete": True,
                "confirmed_absent": True,
                "page_count": page_count,
                "plan_sha256": context.plan_sha256,
                "portfolio_id_sha256": context.portfolio_id_sha256,
            },
        )
        assert result.evidence_sha256 is not None
        self._exact_order_absence = SpotEligibilityExactOrderAbsenceSnapshot(
            client_order_id=context.client_order_id,
            product_id=SPOT_ELIGIBILITY_PRODUCT_ID,
            page_count=page_count,
            evidence_sha256=result.evidence_sha256,
        )
        return result

    def read_account_active_spot_order_catalog(
        self,
        context: SpotEligibilityReadContext,
    ) -> SpotEligibilityReadResult:
        """Prove zero active Spot orders across the exact approved portfolio."""

        self._validate_context(context)
        self._active_order_catalog_absence = None
        if (
            not self._permission_scope_ready
            or self._portfolio_binding is None
            or self._method("list_orders") is None
        ):
            return self._rejected(request_count=0)
        observed_at = self._now()
        try:
            rows, pagination = read_authoritative_coinbase_orders(
                self._rest_client,
                order_status=list(COINBASE_ACTIVE_SPOT_ORDER_QUERY),
                product_type="SPOT",
                retail_portfolio_id=self._approved_portfolio_id,
                maximum_pages=_MAX_ACTIVE_ORDER_PAGES,
            )
        except Exception:
            return self._unknown(observed_at=observed_at)
        page_count = pagination.get("page_count")
        authoritative = bool(
            pagination.get("authoritative") is True
            and pagination.get("pagination_complete") is True
            and type(page_count) is int
            and page_count >= 1
            and pagination.get("order_count") == len(rows)
        )
        if not authoritative:
            return self._unknown(observed_at=observed_at)
        if rows:
            return self._rejected(
                request_count=page_count,
                observed_at=observed_at,
            )
        result = self._succeeded(
            "ACCOUNT_ACTIVE_SPOT_ORDER_CATALOG",
            request_count=page_count,
            observed_at=observed_at,
            facts={
                "authoritative": True,
                "pagination_complete": True,
                "page_count": page_count,
                "active_order_count": 0,
                "product_type": "SPOT",
                "plan_sha256": context.plan_sha256,
                "portfolio_id_sha256": context.portfolio_id_sha256,
            },
        )
        assert result.evidence_sha256 is not None
        self._active_order_catalog_absence = (
            SpotEligibilityActiveOrderCatalogAbsenceSnapshot(
                portfolio_id_sha256=context.portfolio_id_sha256,
                product_type="SPOT",
                page_count=page_count,
                evidence_sha256=result.evidence_sha256,
            )
        )
        return result
