"""Atomic V10-V12 market-snapshot derivation before a single Preview claim."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from decimal import Decimal
import hashlib
import json
from typing import Any, Callable, Mapping
from uuid import UUID

from application.admin_api.command_service import (
    COINBASE_ACTIVE_SPOT_ORDER_QUERY,
    exact_coinbase_order_readback,
    read_authoritative_coinbase_orders,
)
from application.admin_api.operator_spot_eligibility import (
    APPROVED_SPOT_ELIGIBILITY_ORDER,
    SPOT_ELIGIBILITY_ATOMIC_MARKET_SNAPSHOT_GOAL_KEYS,
    derive_spot_eligibility_client_order_id,
)
from application.admin_api.operator_spot_eligibility_reader import (
    SpotEligibilityActiveOrderCatalogAbsenceSnapshot,
    SpotEligibilityExactOrderAbsenceSnapshot,
    SpotEligibilityMarketReferenceSnapshot,
    SpotEligibilityPortfolioBindingSnapshot,
    SpotEligibilityReadSnapshot,
    SpotEligibilityWalletSnapshot,
)
from application.admin_api.operator_spot_minimum_size_policy import (
    MINIMUM_SIZE_MAX_AGE,
    MINIMUM_SIZE_MAX_FUTURE_SKEW,
    MinimumSizeBuyPlan,
)
from application.admin_api.operator_spot_minimum_size_preparation import (
    MinimumSizePreparationOutcome,
    run_minimum_size_candidate_preparation,
)


_MAX_PAGES = 100
_FRESHNESS = timedelta(seconds=30)


class AtomicMarketSnapshotOutcome(str, Enum):
    MATERIALIZED = "MATERIALIZED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class AtomicMarketSnapshotAttempt:
    category: str
    coinbase_api_call_count: int
    observed_at: datetime
    fresh_until: datetime
    evidence_sha256: str


@dataclass(frozen=True, slots=True)
class AtomicMarketSnapshotResult:
    outcome: AtomicMarketSnapshotOutcome
    diagnostic_code: str
    completed_categories: tuple[str, ...]
    coinbase_api_call_count: int | None
    call_count_exact: bool
    evidence_sha256: str | None
    market_snapshot_sha256: str | None
    plan: MinimumSizeBuyPlan | None
    plan_sha256: str | None
    client_order_id: str | None
    attempts: tuple[AtomicMarketSnapshotAttempt, ...] = ()
    snapshot: SpotEligibilityReadSnapshot | None = field(default=None, repr=False)


def _hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def canonical_atomic_spot_plan_binding(
    *,
    definition_id: str,
    plan: MinimumSizeBuyPlan,
    portfolio_id_sha256: str,
) -> tuple[str, Mapping[str, Any]]:
    """Return the exact immutable plan hash used by PostgreSQL persistence."""

    if str(UUID(definition_id)) != definition_id:
        raise ValueError("atomic_market_snapshot_definition_invalid")
    def decimal_text(value: str) -> str:
        return format(Decimal(value).normalize(), "f")

    canonical = {
        "base_size": decimal_text(plan.base_size),
        "definition_id": definition_id,
        "definition_revision": 1,
        "limit_price": decimal_text(plan.limit_price),
        "max_possible_execution_notional_usdc": (
            decimal_text(plan.max_possible_execution_notional_usdc)
        ),
        "max_submitted_notional_usdc": decimal_text(
            plan.max_submitted_notional_usdc
        ),
        "portfolio_id_sha256": portfolio_id_sha256,
        "possible_execution_notional_usdc": (
            decimal_text(plan.possible_execution_notional_usdc)
        ),
        "post_only": True,
        "product_id": plan.product_id,
        "side": plan.side,
        "submitted_notional_usdc": decimal_text(plan.submitted_notional_usdc),
    }
    return _hash(canonical), canonical


def _terminal(
    outcome: AtomicMarketSnapshotOutcome,
    code: str,
    completed: list[str],
    call_count: int | None,
) -> AtomicMarketSnapshotResult:
    return AtomicMarketSnapshotResult(
        outcome=outcome,
        diagnostic_code=code,
        completed_categories=tuple(completed),
        coinbase_api_call_count=call_count,
        call_count_exact=call_count is not None,
        evidence_sha256=(
            _hash(
                {
                    "call_count": call_count,
                    "categories": completed,
                    "diagnostic_code": code,
                    "outcome": outcome.value,
                    "policy_revision": 5,
                }
            )
            if call_count is not None
            else None
        ),
        market_snapshot_sha256=None,
        plan=None,
        plan_sha256=None,
        client_order_id=None,
    )


def run_atomic_market_snapshot_candidate(
    *,
    rest_client: Any,
    approved_portfolio_id: str,
    approved_portfolio_label: str,
    definition_id: str,
    run_id: str,
    goal_key: str,
    candidate_version: int,
    cycle_number: int,
    correlation_id: str,
    now_factory: Callable[[], datetime],
    exact_order_reader: Callable[..., Mapping[str, Any]] = (
        exact_coinbase_order_readback
    ),
    active_order_reader: Callable[..., tuple[list[Mapping[str, Any]], Mapping[str, Any]]] = (
        read_authoritative_coinbase_orders
    ),
) -> AtomicMarketSnapshotResult:
    """Derive terms and finish the exact eight reads without network retry."""

    expected_version = 10 + sorted(
        SPOT_ELIGIBILITY_ATOMIC_MARKET_SNAPSHOT_GOAL_KEYS
    ).index(goal_key) if goal_key in SPOT_ELIGIBILITY_ATOMIC_MARKET_SNAPSHOT_GOAL_KEYS else -1
    try:
        if (
            candidate_version != expected_version
            or not 1 <= cycle_number <= 10
            or str(UUID(definition_id)) != definition_id
            or str(UUID(run_id)) != run_id
            or not correlation_id.strip()
        ):
            raise ValueError
        initial_now = now_factory().astimezone(timezone.utc)
    except Exception:
        return _terminal(
            AtomicMarketSnapshotOutcome.BLOCKED,
            "atomic_market_snapshot_configuration_invalid",
            [],
            0,
        )

    preparation = run_minimum_size_candidate_preparation(
        rest_client=rest_client,
        approved_portfolio_id=approved_portfolio_id,
        approved_portfolio_label=approved_portfolio_label,
        now_factory=lambda: initial_now,
    )
    completed = list(preparation.completed_categories)
    if preparation.outcome is not MinimumSizePreparationOutcome.MATERIALIZED:
        outcome = (
            AtomicMarketSnapshotOutcome.UNKNOWN
            if preparation.outcome is MinimumSizePreparationOutcome.UNKNOWN
            else AtomicMarketSnapshotOutcome.BLOCKED
        )
        return _terminal(
            outcome,
            preparation.diagnostic_code,
            completed,
            preparation.coinbase_api_call_count,
        )
    plan = preparation.plan
    observed = preparation.market_observed_at
    market_hash = preparation.market_snapshot_sha256
    available = preparation.available_usdc
    total = preparation.total_usdc
    best_bid = preparation.best_bid
    best_ask = preparation.best_ask
    if (
        plan is None
        or observed is None
        or market_hash is None
        or available is None
        or total is None
        or best_bid is None
        or best_ask is None
        or len(preparation.category_call_counts) != 6
    ):
        return _terminal(
            AtomicMarketSnapshotOutcome.UNKNOWN,
            "atomic_market_snapshot_derivation_unknown",
            completed,
            None,
        )
    portfolio_hash = hashlib.sha256(
        approved_portfolio_id.encode("utf-8")
    ).hexdigest()
    plan_sha256, _ = canonical_atomic_spot_plan_binding(
        definition_id=definition_id,
        plan=plan,
        portfolio_id_sha256=portfolio_hash,
    )
    client_order_id = derive_spot_eligibility_client_order_id(
        run_id=run_id,
        plan_sha256=plan_sha256,
        goal_key=goal_key,
    )
    call_count = int(preparation.coinbase_api_call_count or 0)
    try:
        exact = exact_order_reader(
            rest_client,
            client_order_id=client_order_id,
            product_id="BTC-USDC",
            product_type="SPOT",
            expected_retail_portfolio_id=approved_portfolio_id,
            maximum_list_pages=_MAX_PAGES,
        )
    except Exception:
        return _terminal(
            AtomicMarketSnapshotOutcome.UNKNOWN,
            "atomic_market_snapshot_exact_order_unknown",
            completed,
            None,
        )
    exact_pages = exact.get("page_count")
    if type(exact_pages) is not int or exact_pages < 1:
        return _terminal(
            AtomicMarketSnapshotOutcome.UNKNOWN,
            "atomic_market_snapshot_exact_order_unknown",
            completed,
            None,
        )
    call_count += exact_pages
    if not (
        exact.get("authoritative") is True
        and exact.get("pagination_complete") is True
        and exact.get("confirmed_absent") is True
        and exact.get("exact_identity_match") is False
        and exact.get("matched_order") is None
    ):
        return _terminal(
            AtomicMarketSnapshotOutcome.BLOCKED,
            "atomic_market_snapshot_exact_order_rejected",
            completed,
            call_count,
        )
    completed.append("EXACT_ORDER_RECONCILIATION")
    try:
        exact_observed_at = now_factory().astimezone(timezone.utc)
    except Exception:
        return _terminal(
            AtomicMarketSnapshotOutcome.UNKNOWN,
            "atomic_market_snapshot_clock_unknown",
            completed,
            None,
        )

    try:
        rows, pagination = active_order_reader(
            rest_client,
            order_status=list(COINBASE_ACTIVE_SPOT_ORDER_QUERY),
            product_type="SPOT",
            retail_portfolio_id=approved_portfolio_id,
            maximum_pages=_MAX_PAGES,
        )
    except Exception:
        return _terminal(
            AtomicMarketSnapshotOutcome.UNKNOWN,
            "atomic_market_snapshot_active_catalog_unknown",
            completed,
            None,
        )
    active_pages = pagination.get("page_count")
    if (
        type(active_pages) is not int
        or active_pages < 1
        or pagination.get("authoritative") is not True
        or pagination.get("pagination_complete") is not True
        or pagination.get("order_count") != len(rows)
    ):
        return _terminal(
            AtomicMarketSnapshotOutcome.UNKNOWN,
            "atomic_market_snapshot_active_catalog_unknown",
            completed,
            None,
        )
    call_count += active_pages
    if rows:
        return _terminal(
            AtomicMarketSnapshotOutcome.BLOCKED,
            "atomic_market_snapshot_active_order_rejected",
            completed,
            call_count,
        )
    completed.append("ACCOUNT_ACTIVE_SPOT_ORDER_CATALOG")

    try:
        active_observed_at = now_factory().astimezone(timezone.utc)
    except Exception:
        return _terminal(
            AtomicMarketSnapshotOutcome.UNKNOWN,
            "atomic_market_snapshot_clock_unknown",
            completed,
            None,
        )
    if observed - active_observed_at > MINIMUM_SIZE_MAX_FUTURE_SKEW:
        return _terminal(
            AtomicMarketSnapshotOutcome.BLOCKED,
            "atomic_market_snapshot_future",
            completed,
            call_count,
        )
    if active_observed_at - observed > MINIMUM_SIZE_MAX_AGE:
        return _terminal(
            AtomicMarketSnapshotOutcome.BLOCKED,
            "atomic_market_snapshot_stale",
            completed,
            call_count,
        )

    exact_hash = _hash(
        {
            "category": "EXACT_ORDER_RECONCILIATION",
            "client_order_id": client_order_id,
            "page_count": exact_pages,
            "confirmed_absent": True,
        }
    )
    active_hash = _hash(
        {
            "category": "ACCOUNT_ACTIVE_SPOT_ORDER_CATALOG",
            "page_count": active_pages,
            "active_order_count": 0,
            "portfolio_id_sha256": portfolio_hash,
        }
    )
    category_counts = (*preparation.category_call_counts, exact_pages, active_pages)
    category_names = tuple(category.value for category in APPROVED_SPOT_ELIGIBILITY_ORDER)
    evidence = _hash(
        {
            "candidate_version": candidate_version,
            "categories": category_names,
            "client_order_id": client_order_id,
            "cycle_number": cycle_number,
            "goal_key": goal_key,
            "market_snapshot_sha256": market_hash,
            "plan_sha256": plan_sha256,
            "portfolio_id_sha256": portfolio_hash,
            "policy_revision": 5,
        }
    )
    attempts = tuple(
        AtomicMarketSnapshotAttempt(
            category=category,
            coinbase_api_call_count=count,
            observed_at=(
                observed
                if category == "BEST_BID_ASK"
                else exact_observed_at
                if category == "EXACT_ORDER_RECONCILIATION"
                else active_observed_at
                if category == "ACCOUNT_ACTIVE_SPOT_ORDER_CATALOG"
                else initial_now
            ),
            fresh_until=(
                observed + _FRESHNESS
                if category == "BEST_BID_ASK"
                else exact_observed_at + _FRESHNESS
                if category == "EXACT_ORDER_RECONCILIATION"
                else active_observed_at + _FRESHNESS
                if category == "ACCOUNT_ACTIVE_SPOT_ORDER_CATALOG"
                else initial_now + _FRESHNESS
            ),
            evidence_sha256=(
                exact_hash
                if category == "EXACT_ORDER_RECONCILIATION"
                else active_hash
                if category == "ACCOUNT_ACTIVE_SPOT_ORDER_CATALOG"
                else _hash(
                    {
                        "category": category,
                        "market_snapshot_sha256": market_hash,
                        "plan_sha256": plan_sha256,
                    }
                )
            ),
        )
        for category, count in zip(category_names, category_counts, strict=True)
    )
    snapshot = SpotEligibilityReadSnapshot(
        cycle_number=cycle_number,
        plan_sha256=plan_sha256,
        portfolio=SpotEligibilityPortfolioBindingSnapshot(
            retail_portfolio_id=approved_portfolio_id,
            portfolio_id_sha256=portfolio_hash,
            label="Test",
            portfolio_type="CONSUMER",
            can_view=True,
            can_trade=True,
        ),
        wallets={
            "USDC": SpotEligibilityWalletSnapshot(
                currency="USDC",
                available_balance=Decimal(available),
                total_balance=Decimal(total),
            )
        },
        market_reference=SpotEligibilityMarketReferenceSnapshot(
            product_id="BTC-USDC",
            best_bid=best_bid,
            best_ask=best_ask,
            observed_at=observed,
            source="coinbase_rest_market_trade_snapshot",
        ),
        exact_order_absence=SpotEligibilityExactOrderAbsenceSnapshot(
            client_order_id=client_order_id,
            product_id="BTC-USDC",
            page_count=exact_pages,
            evidence_sha256=exact_hash,
        ),
        active_order_catalog_absence=(
            SpotEligibilityActiveOrderCatalogAbsenceSnapshot(
                portfolio_id_sha256=portfolio_hash,
                product_type="SPOT",
                page_count=active_pages,
                evidence_sha256=active_hash,
            )
        ),
    )
    return AtomicMarketSnapshotResult(
        outcome=AtomicMarketSnapshotOutcome.MATERIALIZED,
        diagnostic_code="atomic_market_snapshot_terms_bound",
        completed_categories=category_names,
        coinbase_api_call_count=call_count,
        call_count_exact=True,
        evidence_sha256=evidence,
        market_snapshot_sha256=market_hash,
        plan=plan,
        plan_sha256=plan_sha256,
        client_order_id=client_order_id,
        attempts=attempts,
        snapshot=snapshot,
    )
