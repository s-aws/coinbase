"""Shared action-condition guard for order admission boundaries.

This module owns account/action constraints that must be evaluated before an
order creates local state or exchange-visible work. Callers provide the action
shape and phase; the evaluator returns ``(True, None)`` or ``(False, details)``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, Optional, Tuple

from calculation.formatter import safe_float
from core.enums import (
    ActionConditionType,
    ActionGuardPhase,
    OrderSide,
    ProductType,
    StealthOrderStatus,
)


WalletFetcher = Callable[[], Dict[str, Any]]
CredentialCheck = Callable[[], bool]
PlannedBudgetFetcher = Callable[[], Dict[str, float]]
LotAuthorityEvaluator = Callable[..., Dict[str, Any]]

SPOT_PLANNED_BUDGET_STATUSES = frozenset({
    StealthOrderStatus.HIDDEN.value,
    StealthOrderStatus.PENDING.value,
    StealthOrderStatus.TRIGGERED.value,
})

SPOT_STANDING_BUY_LIMIT_RATIO = Decimal("0.5")
SPOT_STANDING_SELL_LIMIT_RATIO = Decimal("1.5")
SPOT_STANDING_MARKET_MAX_AGE_SECONDS = 30
SPOT_STANDING_MARKET_FUTURE_TOLERANCE_SECONDS = 0


def _coerce_utc_datetime(value: Any) -> datetime | None:
    """Return an aware UTC timestamp or ``None`` for invalid evidence."""

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        try:
            parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, TypeError, ValueError):
            return None
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def evaluate_spot_standing_price_limit(
    *,
    side: Any,
    limit_price: Any,
    best_bid: Any,
    market_source: Any,
    market_observed_at: Any = None,
    evaluated_at: Any = None,
) -> Dict[str, Any]:
    """Evaluate the operator's standing Spot price authority.

    The same fail-closed evaluator is used at manual admission and at the
    automatic direct-root child reveal boundary. A fresh ticker-sourced positive
    bid is mandatory; BUY prices must be at or below 50% of bid and SELL prices
    at or above 150% of bid.
    """

    try:
        bid = Decimal(str(best_bid or ""))
    except (InvalidOperation, TypeError, ValueError):
        bid = Decimal("0")
    try:
        requested = Decimal(str(limit_price or ""))
    except (InvalidOperation, TypeError, ValueError):
        requested = Decimal("0")

    source = str(market_source or "").lower()
    normalized_side = str(side or "").upper()
    observed_at = _coerce_utc_datetime(market_observed_at)
    decision_at = _coerce_utc_datetime(evaluated_at) or datetime.now(timezone.utc)
    market_age_seconds = (
        (decision_at - observed_at).total_seconds()
        if observed_at is not None
        else None
    )
    valid_bid = bid.is_finite() and bid > 0
    valid_requested_price = requested.is_finite() and requested > 0
    maximum_buy_price = (
        bid * SPOT_STANDING_BUY_LIMIT_RATIO if valid_bid else Decimal("0")
    )
    minimum_sell_price = (
        bid * SPOT_STANDING_SELL_LIMIT_RATIO if valid_bid else Decimal("0")
    )

    blocker = None
    if source != "ticker" or not valid_bid:
        blocker = "live_ticker_bid_unavailable"
    elif observed_at is None or market_age_seconds is None:
        blocker = "live_ticker_timestamp_unavailable"
    elif market_age_seconds < -SPOT_STANDING_MARKET_FUTURE_TOLERANCE_SECONDS:
        blocker = "live_ticker_timestamp_future"
    elif market_age_seconds > SPOT_STANDING_MARKET_MAX_AGE_SECONDS:
        blocker = "live_ticker_bid_stale"
    elif not valid_requested_price or normalized_side not in {
        OrderSide.BUY.value,
        OrderSide.SELL.value,
    }:
        blocker = "standing_price_limit_invalid_order"
    elif normalized_side == OrderSide.BUY.value:
        if requested > maximum_buy_price:
            blocker = "standing_price_limit_not_authorized"
    elif requested < minimum_sell_price:
        blocker = "standing_price_limit_not_authorized"

    return {
        "allowed": blocker is None,
        "source": source or None,
        "best_bid": str(bid) if valid_bid else None,
        "requested_limit_price": (
            str(requested) if valid_requested_price else None
        ),
        "maximum_limit_price": str(maximum_buy_price),
        "minimum_limit_price": str(minimum_sell_price),
        "buy_limit_ratio": str(SPOT_STANDING_BUY_LIMIT_RATIO),
        "sell_limit_ratio": str(SPOT_STANDING_SELL_LIMIT_RATIO),
        "market_observed_at": (
            observed_at.isoformat() if observed_at is not None else None
        ),
        "evaluated_at": decision_at.isoformat(),
        "market_age_seconds": (
            str(market_age_seconds) if market_age_seconds is not None else None
        ),
        "max_market_age_seconds": str(SPOT_STANDING_MARKET_MAX_AGE_SECONDS),
        "blocker": blocker,
    }


def get_action_condition_guard_policy(override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return configured action-condition policy.

    ``override`` is primarily for tests and dependency injection. Without it,
    the value is read from ``configuration.ACTION_CONDITION_GUARDS`` so runtime
    config stays centralized.
    """
    if override is not None:
        return override if isinstance(override, dict) else {}
    try:
        from configuration import ACTION_CONDITION_GUARDS
        policy = ACTION_CONDITION_GUARDS
    except Exception:
        policy = {}
    return policy if isinstance(policy, dict) else {}


def normalize_action_guard_wallet_policy(policy: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize the optional ``wallet_available`` policy block."""
    raw = policy.get(ActionConditionType.WALLET_AVAILABLE.value)
    if raw is False:
        return {"enabled": False}
    if raw is True or raw is None:
        return {"enabled": True}
    if isinstance(raw, dict):
        wallet_policy = dict(raw)
        wallet_policy.setdefault("enabled", True)
        return wallet_policy
    return {"enabled": True}


def normalize_action_guard_known_inventory_policy(
    policy: Dict[str, Any],
) -> Dict[str, Any]:
    """Normalize the optional ``known_inventory_available`` policy block."""
    raw = policy.get(ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value)
    if raw is False or raw is None:
        return {"enabled": False}
    if raw is True:
        return {"enabled": True}
    if isinstance(raw, dict):
        inventory_policy = dict(raw)
        inventory_policy.setdefault("enabled", True)
        return inventory_policy
    return {"enabled": False}


def rest_credentials_configured() -> bool:
    """Return True when Coinbase REST credentials are configured."""
    try:
        from configuration import API_KEY, API_SECRET
        return bool(API_KEY and API_SECRET)
    except Exception:
        return False


def fetch_account_wallets() -> Dict[str, Any]:
    """Fetch account wallets through the canonical configuration helper."""
    from configuration import rest_get_account_wallets
    return rest_get_account_wallets()


def coerce_action_guard_phase(phase: Any) -> str:
    if isinstance(phase, ActionGuardPhase):
        return phase.value
    try:
        return ActionGuardPhase(str(phase)).value
    except ValueError:
        return str(phase or "")


def _phase_enabled(rule: Dict[str, Any], phase: str) -> bool:
    phases = rule.get("phases")
    if phases is None:
        return True
    if isinstance(phases, str):
        phases = [phases]
    allowed = {coerce_action_guard_phase(item) for item in (phases or [])}
    return phase in allowed


def _value_matches(configured: Any, actual: str) -> bool:
    if configured is None:
        return True
    if isinstance(configured, str):
        configured_values = [configured]
    elif isinstance(configured, (list, tuple, set)):
        configured_values = list(configured)
    else:
        configured_values = [configured]
    return str(actual or "").upper() in {
        str(item or "").upper() for item in configured_values
    }


def _resolve_product_context(
    product_id: str,
    *,
    product_metadata: Optional[Dict[str, Any]] = None,
    spot_product_ids: Optional[list[str]] = None,
) -> Dict[str, Any]:
    from configuration import get_trading_product_id, normalize_product_type

    if product_metadata is None:
        try:
            from configuration import PRODUCT_METADATA
            product_metadata = PRODUCT_METADATA
        except Exception:
            product_metadata = {}
    if spot_product_ids is None:
        try:
            from configuration import SPOT_PRODUCT_IDS
            spot_product_ids = SPOT_PRODUCT_IDS
        except Exception:
            spot_product_ids = []

    trading_product_id = get_trading_product_id(str(product_id or ""))
    metadata = (
        (product_metadata or {}).get(str(product_id or ""))
        or (product_metadata or {}).get(trading_product_id)
        or {}
    )
    product_type = normalize_product_type(
        {"product_id": trading_product_id},
        products=product_metadata or {},
    )
    metadata_product_type = (
        normalize_product_type(metadata, products=product_metadata or {})
        if metadata else ""
    )
    configured_spot_ids = set(spot_product_ids or [])
    return {
        "product_id": trading_product_id,
        "requested_product_id": product_id,
        "metadata": metadata,
        "product_type": product_type,
        "is_configured_spot": (
            trading_product_id in configured_spot_ids
            or metadata_product_type == ProductType.SPOT.value
        ),
    }


def _resolve_currencies(
    product_id: str,
    metadata: Dict[str, Any],
) -> Tuple[Optional[str], Optional[str]]:
    base_currency = metadata.get("base_currency") if isinstance(metadata, dict) else None
    quote_currency = metadata.get("quote_currency") if isinstance(metadata, dict) else None
    parts = str(product_id or "").split("-")
    if not base_currency and parts:
        base_currency = parts[0]
    if not quote_currency and len(parts) > 1:
        quote_currency = parts[1]
    return (
        str(base_currency).upper() if base_currency else None,
        str(quote_currency).upper() if quote_currency else None,
    )


def _extract_wallet_available_balance(wallet: Any) -> float:
    raw_balance = None
    if isinstance(wallet, dict):
        raw_balance = wallet.get("available_balance")
        if raw_balance is None:
            raw_balance = wallet.get("available")
    else:
        raw_balance = getattr(wallet, "available_balance", None)
        if raw_balance is None:
            raw_balance = getattr(wallet, "available", None)

    if isinstance(raw_balance, dict):
        raw_balance = (
            raw_balance.get("value")
            if raw_balance.get("value") is not None
            else raw_balance.get("amount")
        )
    return safe_float(raw_balance, default=0.0) or 0.0


def estimate_spot_budget_requirement(
    *,
    product_id: str,
    side: str,
    size: Optional[float] = None,
    limit_price: Optional[float] = None,
    quote_size: Optional[float] = None,
    product_metadata: Optional[Dict[str, Any]] = None,
    spot_product_ids: Optional[list[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Return the spot currency/amount needed by one order action.

    Spot sells reserve base currency. Spot buys reserve quote currency using
    ``quote_size`` when supplied, otherwise ``size * limit_price``.
    """
    try:
        side_value = OrderSide(str(side or "").upper()).value
    except ValueError:
        side_value = str(side or "").upper()

    context = _resolve_product_context(
        product_id,
        product_metadata=product_metadata,
        spot_product_ids=spot_product_ids,
    )
    if context["product_type"] != ProductType.SPOT.value:
        return None
    if not context.get("is_configured_spot"):
        return None

    base_currency, quote_currency = _resolve_currencies(
        context["product_id"],
        context["metadata"],
    )
    size_value = safe_float(size, default=0.0) or 0.0
    limit_price_value = safe_float(limit_price, default=0.0) or 0.0
    quote_size_value = safe_float(quote_size, default=0.0) or 0.0

    if side_value == OrderSide.SELL.value:
        required_currency = base_currency
        required_amount = size_value
    elif side_value == OrderSide.BUY.value:
        required_currency = quote_currency
        required_amount = quote_size_value if quote_size_value > 0 else (
            size_value * limit_price_value if limit_price_value > 0 else 0.0
        )
    else:
        return None

    if not required_currency or required_amount <= 0:
        return None

    return {
        "currency": str(required_currency).upper(),
        "amount": required_amount,
        "product_id": context["product_id"],
        "requested_product_id": context["requested_product_id"],
        "product_type": context["product_type"],
        "side": side_value,
    }


def estimate_spot_replacement_budget_delta(
    *,
    product_id: str,
    side: str,
    size: Optional[float] = None,
    limit_price: Optional[float] = None,
    quote_size: Optional[float] = None,
    existing_side: Optional[str] = None,
    existing_size: Optional[float] = None,
    existing_limit_price: Optional[float] = None,
    existing_quote_size: Optional[float] = None,
    product_metadata: Optional[Dict[str, Any]] = None,
    spot_product_ids: Optional[list[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Return the net new wallet requirement for a spot replacement.

    Coinbase wallet availability should already exclude the active order's
    hold. A same-currency, no-fill replacement only needs additional available
    balance for the amount above the existing hold.
    """
    new_requirement = estimate_spot_budget_requirement(
        product_id=product_id,
        side=side,
        size=size,
        limit_price=limit_price,
        quote_size=quote_size,
        product_metadata=product_metadata,
        spot_product_ids=spot_product_ids,
    )
    if not new_requirement:
        return None

    old_requirement = estimate_spot_budget_requirement(
        product_id=product_id,
        side=existing_side if existing_side is not None else side,
        size=existing_size,
        limit_price=existing_limit_price,
        quote_size=existing_quote_size,
        product_metadata=product_metadata,
        spot_product_ids=spot_product_ids,
    )

    new_currency = str(new_requirement.get("currency") or "").upper()
    new_amount = safe_float(new_requirement.get("amount"), default=0.0) or 0.0
    old_currency = (
        str((old_requirement or {}).get("currency") or "").upper()
        if old_requirement
        else None
    )
    old_amount = (
        safe_float((old_requirement or {}).get("amount"), default=0.0) or 0.0
        if old_requirement
        else 0.0
    )
    existing_credit = old_amount if old_currency == new_currency else 0.0
    required_delta = max(0.0, new_amount - existing_credit)

    return {
        "currency": new_currency,
        "amount": required_delta,
        "product_id": new_requirement["product_id"],
        "requested_product_id": new_requirement["requested_product_id"],
        "product_type": new_requirement["product_type"],
        "side": new_requirement["side"],
        "new_required": new_amount,
        "existing_required": old_amount,
        "existing_credit": existing_credit,
        "existing_currency": old_currency,
        "new_currency": new_currency,
    }


def collect_spot_planned_budget_commitments(
    orders: Any,
    *,
    exclude_stealth_order_id: Optional[str] = None,
    product_metadata: Optional[Dict[str, Any]] = None,
    spot_product_ids: Optional[list[str]] = None,
) -> Dict[str, float]:
    """Aggregate pre-exchange spot commitments from stealth order state.

    Only HIDDEN/PENDING/TRIGGERED orders count. REVEALED orders are omitted
    because the exchange placement should already be reflected in Coinbase
    wallet availability.
    """
    if isinstance(orders, dict):
        order_iterable = orders.values()
    else:
        order_iterable = orders or []

    excluded = str(exclude_stealth_order_id) if exclude_stealth_order_id else None
    commitments: Dict[str, float] = {}
    for order in order_iterable:
        if not isinstance(order, dict):
            continue
        stealth_order_id = str(order.get("stealth_order_id") or "")
        if excluded and stealth_order_id == excluded:
            continue
        status = str(order.get("status") or "").upper()
        if status not in SPOT_PLANNED_BUDGET_STATUSES:
            continue

        requirement = estimate_spot_budget_requirement(
            product_id=str(order.get("product_id") or ""),
            side=str(order.get("side") or ""),
            size=safe_float(order.get("remaining_size"), default=0.0) or 0.0,
            limit_price=safe_float(order.get("limit_price"), default=0.0) or 0.0,
            product_metadata=product_metadata,
            spot_product_ids=spot_product_ids,
        )
        if not requirement:
            continue
        currency = requirement["currency"]
        commitments[currency] = (
            commitments.get(currency, 0.0)
            + (safe_float(requirement.get("amount"), default=0.0) or 0.0)
        )
    return commitments


class ActionConditionGuard:
    """Evaluate configured account/action constraints for one order action."""

    def __init__(
        self,
        *,
        policy: Optional[Dict[str, Any]] = None,
        wallet_fetcher: Optional[WalletFetcher] = None,
        credentials_configured: Optional[CredentialCheck] = None,
        planned_budget_fetcher: Optional[PlannedBudgetFetcher] = None,
        lot_authority_evaluator: Optional[LotAuthorityEvaluator] = None,
        product_metadata: Optional[Dict[str, Any]] = None,
        spot_product_ids: Optional[list[str]] = None,
    ) -> None:
        self._policy_override = policy
        self._wallet_fetcher = wallet_fetcher or fetch_account_wallets
        self._credentials_configured = (
            credentials_configured or rest_credentials_configured
        )
        self._planned_budget_fetcher = planned_budget_fetcher
        self._lot_authority_evaluator = lot_authority_evaluator
        self._product_metadata = product_metadata
        self._spot_product_ids = spot_product_ids

    @property
    def policy(self) -> Dict[str, Any]:
        return get_action_condition_guard_policy(self._policy_override)

    def evaluate(
        self,
        *,
        phase: ActionGuardPhase,
        product_id: str,
        side: str,
        size: Optional[float] = None,
        limit_price: Optional[float] = None,
        quote_size: Optional[float] = None,
        client_order_id: Optional[str] = None,
        stealth_order_id: Optional[str] = None,
        parent_order_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Evaluate configured conditions for a planned or executable action."""
        phase_value = coerce_action_guard_phase(phase)
        try:
            side_value = OrderSide(str(side or "").upper()).value
        except ValueError:
            side_value = str(side or "").upper()

        size_value = safe_float(size, default=0.0) or 0.0
        limit_price_value = safe_float(limit_price, default=0.0) or 0.0
        quote_size_value = safe_float(quote_size, default=0.0) or 0.0
        context = _resolve_product_context(
            product_id,
            product_metadata=self._product_metadata,
            spot_product_ids=self._spot_product_ids,
        )
        context.update({
            "side": side_value,
            "phase": phase_value,
            "client_order_id": client_order_id,
            "stealth_order_id": stealth_order_id,
            "parent_order_id": parent_order_id,
        })

        failure = self._evaluate_limit_rules(
            phase=phase_value,
            context=context,
            size=size_value,
            limit_price=limit_price_value,
            quote_size=quote_size_value,
        )
        if failure is None:
            failure = self._evaluate_wallet_condition(
                phase=phase_value,
                context=context,
                size=size_value,
                limit_price=limit_price_value,
                quote_size=quote_size_value,
                parent_order_id=parent_order_id,
            )
        if failure is None:
            failure = self._evaluate_known_inventory_condition(
                phase=phase_value,
                context=context,
                size=size_value,
                limit_price=limit_price_value,
            )
        if failure is None:
            return True, None

        failure.update({
            "phase": phase_value,
            "product_id": context["product_id"],
            "product_type": context["product_type"],
            "side": side_value,
            "size": size_value,
            "limit_price": limit_price_value,
            "quote_size": quote_size_value,
            "client_order_id": client_order_id,
            "stealth_order_id": stealth_order_id,
            "parent_order_id": parent_order_id,
        })
        return False, failure

    def evaluate_replacement(
        self,
        *,
        phase: ActionGuardPhase,
        product_id: str,
        side: str,
        size: Optional[float] = None,
        limit_price: Optional[float] = None,
        quote_size: Optional[float] = None,
        existing_side: Optional[str] = None,
        existing_size: Optional[float] = None,
        existing_limit_price: Optional[float] = None,
        existing_quote_size: Optional[float] = None,
        client_order_id: Optional[str] = None,
        stealth_order_id: Optional[str] = None,
        parent_order_id: Optional[str] = None,
        replaced_client_order_id: Optional[str] = None,
        replaced_exchange_order_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Evaluate conditions for a cancel-and-replace action.

        Limit rules apply to the full new order. Spot wallet checks apply to
        the net new requirement after crediting the active same-currency hold.
        """
        phase_value = coerce_action_guard_phase(phase)
        try:
            side_value = OrderSide(str(side or "").upper()).value
        except ValueError:
            side_value = str(side or "").upper()

        existing_side_value = existing_side
        if existing_side_value is not None:
            try:
                existing_side_value = OrderSide(
                    str(existing_side_value or "").upper()
                ).value
            except ValueError:
                existing_side_value = str(existing_side_value or "").upper()

        size_value = safe_float(size, default=0.0) or 0.0
        limit_price_value = safe_float(limit_price, default=0.0) or 0.0
        quote_size_value = safe_float(quote_size, default=0.0) or 0.0
        existing_size_value = safe_float(existing_size, default=0.0) or 0.0
        existing_limit_price_value = (
            safe_float(existing_limit_price, default=0.0) or 0.0
        )
        existing_quote_size_value = (
            safe_float(existing_quote_size, default=0.0) or 0.0
        )
        context = _resolve_product_context(
            product_id,
            product_metadata=self._product_metadata,
            spot_product_ids=self._spot_product_ids,
        )
        context.update({
            "side": side_value,
            "phase": phase_value,
            "client_order_id": client_order_id,
            "stealth_order_id": stealth_order_id,
            "parent_order_id": parent_order_id,
            "replaced_client_order_id": replaced_client_order_id,
            "replaced_exchange_order_id": replaced_exchange_order_id,
        })

        failure = self._evaluate_limit_rules(
            phase=phase_value,
            context=context,
            size=size_value,
            limit_price=limit_price_value,
            quote_size=quote_size_value,
        )
        if failure is None:
            failure = self._evaluate_replacement_wallet_condition(
                phase=phase_value,
                context=context,
                size=size_value,
                limit_price=limit_price_value,
                quote_size=quote_size_value,
                existing_side=existing_side_value,
                existing_size=existing_size_value,
                existing_limit_price=existing_limit_price_value,
                existing_quote_size=existing_quote_size_value,
            )
        if failure is None:
            return True, None

        failure.update({
            "phase": phase_value,
            "product_id": context["product_id"],
            "product_type": context["product_type"],
            "side": side_value,
            "size": size_value,
            "limit_price": limit_price_value,
            "quote_size": quote_size_value,
            "existing_side": existing_side_value,
            "existing_size": existing_size_value,
            "existing_limit_price": existing_limit_price_value,
            "existing_quote_size": existing_quote_size_value,
            "client_order_id": client_order_id,
            "stealth_order_id": stealth_order_id,
            "parent_order_id": parent_order_id,
            "replaced_client_order_id": replaced_client_order_id,
            "replaced_exchange_order_id": replaced_exchange_order_id,
            "replacement": True,
        })
        return False, failure

    def _estimate_notional(
        self,
        *,
        product_type: str,
        metadata: Dict[str, Any],
        size: float,
        limit_price: float,
        quote_size: float,
    ) -> Optional[float]:
        if quote_size > 0:
            return quote_size
        if size <= 0 or limit_price <= 0:
            return None
        contract_size = safe_float((metadata or {}).get("contract_size"), default=None)
        multiplier = (
            contract_size
            if product_type == ProductType.FUTURE.value and contract_size
            else 1.0
        )
        return size * limit_price * multiplier

    def has_applicable_notional_cap(
        self,
        *,
        phase: ActionGuardPhase,
        product_id: str,
        side: str,
    ) -> bool:
        """Return True when a matching limit rule defines ``max_notional``."""
        phase_value = coerce_action_guard_phase(phase)
        try:
            side_value = OrderSide(str(side or "").upper()).value
        except ValueError:
            side_value = str(side or "").upper()
        context = _resolve_product_context(
            product_id,
            product_metadata=self._product_metadata,
            spot_product_ids=self._spot_product_ids,
        )
        context.update({
            "side": side_value,
            "phase": phase_value,
        })
        for _index, rule in self._matching_limit_rules(
            phase=phase_value,
            context=context,
        ):
            if safe_float(
                rule.get(ActionConditionType.MAX_NOTIONAL.value),
                default=None,
            ) is not None:
                return True
        return False

    def requires_known_inventory_for_sell(
        self,
        *,
        phase: ActionGuardPhase,
        product_id: str,
        side: str,
    ) -> bool:
        """Return True when policy requires known inventory for this SELL."""
        phase_value = coerce_action_guard_phase(phase)
        try:
            side_value = OrderSide(str(side or "").upper()).value
        except ValueError:
            side_value = str(side or "").upper()
        context = _resolve_product_context(
            product_id,
            product_metadata=self._product_metadata,
            spot_product_ids=self._spot_product_ids,
        )
        inventory_policy = normalize_action_guard_known_inventory_policy(
            self.policy
        )
        return (
            inventory_policy.get("enabled", False) is not False
            and _phase_enabled(inventory_policy, phase_value)
            and context["product_type"] == ProductType.SPOT.value
            and side_value == OrderSide.SELL.value
        )

    def _matching_limit_rules(
        self,
        *,
        phase: str,
        context: Dict[str, Any],
    ) -> list[tuple[int, Dict[str, Any]]]:
        limits = self.policy.get("limits") or []
        if isinstance(limits, dict):
            limits = list(limits.values())
        if not isinstance(limits, list):
            return []

        matches: list[tuple[int, Dict[str, Any]]] = []
        for index, rule in enumerate(limits):
            if not isinstance(rule, dict):
                continue
            if rule.get("enabled", True) is False:
                continue
            if not _phase_enabled(rule, phase):
                continue
            if not _value_matches(rule.get("product_id"), context["product_id"]):
                continue
            if not _value_matches(rule.get("product_type"), context["product_type"]):
                continue
            if not _value_matches(rule.get("side"), context["side"]):
                continue
            matches.append((index, rule))
        return matches

    def _evaluate_limit_rules(
        self,
        *,
        phase: str,
        context: Dict[str, Any],
        size: float,
        limit_price: float,
        quote_size: float,
    ) -> Optional[Dict[str, Any]]:
        notional = self._estimate_notional(
            product_type=context["product_type"],
            metadata=context["metadata"],
            size=size,
            limit_price=limit_price,
            quote_size=quote_size,
        )
        for index, rule in self._matching_limit_rules(
            phase=phase,
            context=context,
        ):
            max_base_size = safe_float(
                rule.get(ActionConditionType.MAX_BASE_SIZE.value),
                default=None,
            )
            if max_base_size is not None and size > max_base_size:
                return {
                    "condition": ActionConditionType.MAX_BASE_SIZE.value,
                    "block_category": ActionConditionType.MAX_BASE_SIZE.value,
                    "reason": (
                        f"order size {size} exceeds configured max_base_size "
                        f"{max_base_size}"
                    ),
                    "configured_limit": max_base_size,
                    "actual": size,
                    "rule_name": rule.get("name") or f"limit_{index}",
                }

            max_notional = safe_float(
                rule.get(ActionConditionType.MAX_NOTIONAL.value),
                default=None,
            )
            if max_notional is not None and notional is not None and notional > max_notional:
                return {
                    "condition": ActionConditionType.MAX_NOTIONAL.value,
                    "block_category": ActionConditionType.MAX_NOTIONAL.value,
                    "reason": (
                        f"order notional {notional} exceeds configured "
                        f"max_notional {max_notional}"
                    ),
                    "configured_limit": max_notional,
                    "actual": notional,
                    "rule_name": rule.get("name") or f"limit_{index}",
                }
        return None

    def _evaluate_wallet_condition(
        self,
        *,
        phase: str,
        context: Dict[str, Any],
        size: float,
        limit_price: float,
        quote_size: float,
        parent_order_id: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        wallet_policy = normalize_action_guard_wallet_policy(self.policy)
        if wallet_policy.get("enabled", True) is False:
            return None
        if not _phase_enabled(wallet_policy, phase):
            return None
        if (
            phase == ActionGuardPhase.PLANNING.value
            and parent_order_id
            and wallet_policy.get("check_follow_up_planning") is False
        ):
            return None

        requirement = estimate_spot_budget_requirement(
            product_id=context["product_id"],
            side=context["side"],
            size=size,
            limit_price=limit_price,
            quote_size=quote_size,
            product_metadata=self._product_metadata,
            spot_product_ids=self._spot_product_ids,
        )
        if not requirement:
            return None

        required_currency = requirement["currency"]
        required_amount = requirement["amount"]

        if not self._credentials_configured():
            if bool(wallet_policy.get("block_without_credentials", False)):
                return {
                    "condition": ActionConditionType.WALLET_AVAILABLE.value,
                    "block_category": ActionConditionType.WALLET_AVAILABLE.value,
                    "reason": "wallet check requires Coinbase REST credentials",
                    "currency": required_currency,
                    "required": required_amount,
                }
            return None

        try:
            wallets = self._wallet_fetcher()
        except Exception as exc:
            if bool(wallet_policy.get("fail_open_on_fetch_error", False)):
                return None
            return {
                "condition": ActionConditionType.WALLET_AVAILABLE.value,
                "block_category": ActionConditionType.WALLET_AVAILABLE.value,
                "reason": f"wallet check failed: {type(exc).__name__}: {exc}",
                "currency": required_currency,
                "required": required_amount,
            }

        wallet_lookup = {
            str(currency).upper(): wallet
            for currency, wallet in (wallets or {}).items()
        }
        available = _extract_wallet_available_balance(
            wallet_lookup.get(required_currency.upper())
        )
        epsilon = safe_float(wallet_policy.get("epsilon"), default=1e-12) or 0.0
        if available + epsilon < required_amount:
            return {
                "condition": ActionConditionType.WALLET_AVAILABLE.value,
                "block_category": ActionConditionType.WALLET_AVAILABLE.value,
                "reason": (
                    f"available {required_currency} balance {available} is below "
                    f"required {required_amount}"
                ),
                "currency": required_currency,
                "available": available,
                "required": required_amount,
            }

        planned_commitment = 0.0
        if self._planned_budget_fetcher is not None:
            try:
                planned_budget = self._planned_budget_fetcher() or {}
            except Exception as exc:
                if bool(wallet_policy.get("fail_open_on_planned_budget_error", False)):
                    planned_budget = {}
                else:
                    return {
                        "condition": ActionConditionType.PLANNED_BUDGET_AVAILABLE.value,
                        "block_category": ActionConditionType.PLANNED_BUDGET_AVAILABLE.value,
                        "reason": (
                            "planned budget check failed: "
                            f"{type(exc).__name__}: {exc}"
                        ),
                        "currency": required_currency,
                        "available": available,
                        "required": required_amount,
                    }
            planned_commitment = (
                safe_float(
                    planned_budget.get(str(required_currency).upper()),
                    default=0.0,
                )
                or 0.0
            )

        available_after_planned = available - planned_commitment
        if available_after_planned + epsilon >= required_amount:
            return None

        return {
            "condition": ActionConditionType.PLANNED_BUDGET_AVAILABLE.value,
            "block_category": ActionConditionType.PLANNED_BUDGET_AVAILABLE.value,
            "reason": (
                f"available {required_currency} balance {available} minus planned "
                f"commitment {planned_commitment} leaves {available_after_planned}, "
                f"below required {required_amount}"
            ),
            "currency": required_currency,
            "available": available,
            "planned_commitment": planned_commitment,
            "available_after_planned": available_after_planned,
            "required": required_amount,
        }

    def _evaluate_known_inventory_condition(
        self,
        *,
        phase: str,
        context: Dict[str, Any],
        size: float,
        limit_price: float,
    ) -> Optional[Dict[str, Any]]:
        inventory_policy = normalize_action_guard_known_inventory_policy(
            self.policy
        )
        if inventory_policy.get("enabled", False) is False:
            return None
        if not _phase_enabled(inventory_policy, phase):
            return None
        if context["product_type"] != ProductType.SPOT.value:
            return None
        if context["side"] != OrderSide.SELL.value:
            return None

        if self._lot_authority_evaluator is None:
            return {
                "condition": ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value,
                "block_category": (
                    ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value
                ),
                "reason": "known inventory authority evaluator is unavailable",
                "requested_size": size,
                "limit_price": limit_price,
            }

        try:
            decision = self._lot_authority_evaluator(
                product_id=context["product_id"],
                side=context["side"],
                size=size,
                limit_price=limit_price,
            )
        except Exception as exc:
            if bool(inventory_policy.get("fail_open_on_error", False)):
                return None
            return {
                "condition": ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value,
                "block_category": (
                    ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value
                ),
                "reason": (
                    "known inventory authority check failed: "
                    f"{type(exc).__name__}: {exc}"
                ),
                "requested_size": size,
                "limit_price": limit_price,
            }

        if hasattr(decision, "to_dict"):
            decision_data = decision.to_dict()
        elif isinstance(decision, dict):
            decision_data = dict(decision)
        else:
            decision_data = {"allowed": bool(decision)}

        if bool(decision_data.get("allowed", False)):
            return None

        return {
            "condition": ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value,
            "block_category": ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value,
            "reason": (
                decision_data.get("reason")
                or "known profitable inventory does not cover spot sell"
            ),
            "inventory_authority": decision_data,
            "requested_size": size,
            "limit_price": limit_price,
        }

    def _evaluate_replacement_wallet_condition(
        self,
        *,
        phase: str,
        context: Dict[str, Any],
        size: float,
        limit_price: float,
        quote_size: float,
        existing_side: Optional[str],
        existing_size: float,
        existing_limit_price: float,
        existing_quote_size: float,
    ) -> Optional[Dict[str, Any]]:
        wallet_policy = normalize_action_guard_wallet_policy(self.policy)
        if wallet_policy.get("enabled", True) is False:
            return None
        if not _phase_enabled(wallet_policy, phase):
            return None

        requirement = estimate_spot_replacement_budget_delta(
            product_id=context["product_id"],
            side=context["side"],
            size=size,
            limit_price=limit_price,
            quote_size=quote_size,
            existing_side=existing_side,
            existing_size=existing_size,
            existing_limit_price=existing_limit_price,
            existing_quote_size=existing_quote_size,
            product_metadata=self._product_metadata,
            spot_product_ids=self._spot_product_ids,
        )
        if not requirement:
            return None

        required_currency = requirement["currency"]
        required_amount = safe_float(requirement.get("amount"), default=0.0) or 0.0
        epsilon = safe_float(wallet_policy.get("epsilon"), default=1e-12) or 0.0
        if required_amount <= epsilon:
            return None

        if not self._credentials_configured():
            if bool(wallet_policy.get("block_without_credentials", False)):
                return {
                    "condition": ActionConditionType.WALLET_AVAILABLE.value,
                    "block_category": ActionConditionType.WALLET_AVAILABLE.value,
                    "reason": (
                        "replacement wallet check requires Coinbase REST "
                        "credentials"
                    ),
                    "currency": required_currency,
                    "required": required_amount,
                    "required_delta": required_amount,
                    "new_required": requirement.get("new_required"),
                    "existing_credit": requirement.get("existing_credit"),
                }
            return None

        try:
            wallets = self._wallet_fetcher()
        except Exception as exc:
            if bool(wallet_policy.get("fail_open_on_fetch_error", False)):
                return None
            return {
                "condition": ActionConditionType.WALLET_AVAILABLE.value,
                "block_category": ActionConditionType.WALLET_AVAILABLE.value,
                "reason": (
                    f"replacement wallet check failed: {type(exc).__name__}: {exc}"
                ),
                "currency": required_currency,
                "required": required_amount,
                "required_delta": required_amount,
                "new_required": requirement.get("new_required"),
                "existing_credit": requirement.get("existing_credit"),
            }

        wallet_lookup = {
            str(currency).upper(): wallet
            for currency, wallet in (wallets or {}).items()
        }
        available = _extract_wallet_available_balance(
            wallet_lookup.get(required_currency.upper())
        )
        if available + epsilon < required_amount:
            return {
                "condition": ActionConditionType.WALLET_AVAILABLE.value,
                "block_category": ActionConditionType.WALLET_AVAILABLE.value,
                "reason": (
                    f"available {required_currency} balance {available} is below "
                    f"net replacement requirement {required_amount}"
                ),
                "currency": required_currency,
                "available": available,
                "required": required_amount,
                "required_delta": required_amount,
                "new_required": requirement.get("new_required"),
                "existing_required": requirement.get("existing_required"),
                "existing_credit": requirement.get("existing_credit"),
                "existing_currency": requirement.get("existing_currency"),
            }

        planned_commitment = 0.0
        if self._planned_budget_fetcher is not None:
            try:
                planned_budget = self._planned_budget_fetcher() or {}
            except Exception as exc:
                if bool(wallet_policy.get("fail_open_on_planned_budget_error", False)):
                    planned_budget = {}
                else:
                    return {
                        "condition": (
                            ActionConditionType.PLANNED_BUDGET_AVAILABLE.value
                        ),
                        "block_category": (
                            ActionConditionType.PLANNED_BUDGET_AVAILABLE.value
                        ),
                        "reason": (
                            "replacement planned budget check failed: "
                            f"{type(exc).__name__}: {exc}"
                        ),
                        "currency": required_currency,
                        "available": available,
                        "required": required_amount,
                        "required_delta": required_amount,
                        "new_required": requirement.get("new_required"),
                        "existing_credit": requirement.get("existing_credit"),
                    }
            planned_commitment = (
                safe_float(
                    planned_budget.get(str(required_currency).upper()),
                    default=0.0,
                )
                or 0.0
            )

        available_after_planned = available - planned_commitment
        if available_after_planned + epsilon >= required_amount:
            return None

        return {
            "condition": ActionConditionType.PLANNED_BUDGET_AVAILABLE.value,
            "block_category": ActionConditionType.PLANNED_BUDGET_AVAILABLE.value,
            "reason": (
                f"available {required_currency} balance {available} minus planned "
                f"commitment {planned_commitment} leaves {available_after_planned}, "
                f"below net replacement requirement {required_amount}"
            ),
            "currency": required_currency,
            "available": available,
            "planned_commitment": planned_commitment,
            "available_after_planned": available_after_planned,
            "required": required_amount,
            "required_delta": required_amount,
            "new_required": requirement.get("new_required"),
            "existing_required": requirement.get("existing_required"),
            "existing_credit": requirement.get("existing_credit"),
            "existing_currency": requirement.get("existing_currency"),
        }
