"""Typed, I/O-free construction for the one-child Spot Automation runtime.

The helpers in this module never call Coinbase.  They bind request-local
eligibility facts and durable Automation records to the existing canonical
Admin command types.  The orchestration layer remains responsible for the
profile lease, proof persistence, live admission, durable claim, and command
invocation boundaries.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import uuid
from typing import Any

from core.enums import (
    AdminApiActionClass,
    AdminApiPermission,
    AdminApiRole,
    OrderSide,
    OrderType,
    TimeInForce,
)

from .command_service import (
    SpotAutomationMarketEvidence,
    SpotAutomationWalletEvidence,
    SpotAutomationZeroActiveOrderEvidence,
    SpotProfileAdmissionLease,
    ValidatedSpotAutomationAdmissionEvidence,
    ValidatedSpotAutomationOwnershipEvidence,
)
from .models import (
    AdminApiActor,
    AdminApiCommandEnvelope,
    CancelOrderCommand,
    CancelOrderRequest,
    ManualOrderCommand,
    ManualOrderRequest,
)
from .operator_spot_eligibility import (
    APPROVED_SPOT_ELIGIBILITY_ORDER,
    SpotEligibilityCycleResult,
    SpotEligibilityReadOutcome,
    derive_spot_eligibility_client_order_id,
)
from .operator_spot_eligibility_reader import SpotEligibilityReadSnapshot
from .spot_portfolio_binding import SpotPortfolioBindingEvidence


CREATE_ROUTE = "/api/v1/orders"
CANCEL_ROUTE = "/api/v1/orders/{client_order_id}/cancel"
SPOT_AUTOMATION_MODULE = "spot_operations"
SPOT_AUTOMATION_PRODUCT = "BTC-USDC"
MAX_SUBMITTED_NOTIONAL_USDC = Decimal("3.10")
MAX_EXECUTED_NOTIONAL_USDC = Decimal("1.00")
_SHA256_CHARS = frozenset("0123456789abcdef")
_OWNERSHIP_LOCAL_FRESHNESS = timedelta(seconds=30)


class SpotAutomationRuntimeBindingError(RuntimeError):
    """Fixed, value-blind rejection for malformed or mismatched evidence."""


@dataclass(frozen=True, slots=True)
class PreparedSpotAutomationCommand:
    """Canonical command envelope and proof context before proof IDs exist."""

    envelope: AdminApiCommandEnvelope
    proof_context: Mapping[str, Any]
    manual_request: ManualOrderRequest | None = None
    cancel_request: CancelOrderRequest | None = None

    def __post_init__(self) -> None:
        if (self.manual_request is None) is (self.cancel_request is None):
            raise ValueError("spot_automation_prepared_command_invalid")


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _fixed_error(code: str) -> SpotAutomationRuntimeBindingError:
    return SpotAutomationRuntimeBindingError(code)


def _sha256(value: Any, *, code: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in _SHA256_CHARS for character in value)
    ):
        raise _fixed_error(code)
    return value


def _aware(value: Any, *, code: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise _fixed_error(code) from None
    else:
        raise _fixed_error(code)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _fixed_error(code)
    return parsed.astimezone(timezone.utc)


def _decimal(value: Any, *, code: str, positive: bool = False) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise _fixed_error(code) from None
    if not parsed.is_finite() or parsed < 0 or (positive and parsed <= 0):
        raise _fixed_error(code)
    return parsed


def _canonical_uuid(value: Any, *, code: str) -> str:
    try:
        parsed = uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError):
        raise _fixed_error(code) from None
    canonical = str(parsed)
    if canonical != value:
        raise _fixed_error(code)
    return canonical


def _payload_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def derive_spot_automation_phase_key(
    *,
    outer_idempotency_key: str,
    run_id: str,
    plan_sha256: str,
    phase: str,
) -> str:
    """Derive a non-secret, phase-specific idempotency identity."""

    if not outer_idempotency_key or not phase:
        raise _fixed_error("spot_automation_idempotency_binding_invalid")
    digest = hashlib.sha256(
        f"{outer_idempotency_key}:{run_id}:{plan_sha256}:{phase}".encode(
            "utf-8"
        )
    ).hexdigest()
    return f"automation-spot-{phase}-{digest}"


def _portfolio_binding(
    *,
    configured_portfolio_id: str,
    expected_portfolio_sha256: str,
    snapshot: Any | None = None,
) -> SpotPortfolioBindingEvidence:
    portfolio_id = _canonical_uuid(
        configured_portfolio_id,
        code="spot_automation_portfolio_binding_invalid",
    )
    expected_hash = _sha256(
        expected_portfolio_sha256,
        code="spot_automation_portfolio_binding_invalid",
    )
    if hashlib.sha256(portfolio_id.encode("utf-8")).hexdigest() != expected_hash:
        raise _fixed_error("spot_automation_portfolio_binding_mismatch")
    if snapshot is not None and (
        _field(snapshot, "retail_portfolio_id") != portfolio_id
        or _field(snapshot, "portfolio_id_sha256") != expected_hash
        or _field(snapshot, "label") != "Test"
        or _field(snapshot, "portfolio_type") != "CONSUMER"
        or _field(snapshot, "can_view") is not True
        or _field(snapshot, "can_trade") is not True
    ):
        raise _fixed_error("spot_automation_portfolio_binding_mismatch")
    return SpotPortfolioBindingEvidence(
        ready=True,
        blocker=None,
        expected_portfolio_id=portfolio_id,
        expected_portfolio_label="Test",
        expected_portfolio_type="CONSUMER",
        observed_portfolio_id=portfolio_id,
        observed_portfolio_label="Test",
        observed_portfolio_type="CONSUMER",
        can_view=True,
        can_trade=True,
    )


def _validated_attempts(
    *,
    run_id: str,
    cycle_number: int,
    portfolio_id_sha256: str,
    attempts: Sequence[Any],
) -> dict[str, Any]:
    expected = tuple(category.value for category in APPROVED_SPOT_ELIGIBILITY_ORDER)
    by_category: dict[str, Any] = {}
    for attempt in attempts:
        category = str(_field(attempt, "category", ""))
        if category in by_category:
            raise _fixed_error("spot_automation_eligibility_attempts_invalid")
        by_category[category] = attempt
    if set(by_category) != set(expected):
        raise _fixed_error("spot_automation_eligibility_attempts_invalid")
    for category in expected:
        attempt = by_category[category]
        portfolio_hash = _field(attempt, "portfolio_id_sha256")
        if (
            str(_field(attempt, "run_id", "")) != run_id
            or _field(attempt, "cycle_number") != cycle_number
            or _field(attempt, "allowance_consumed") is not True
            or _field(attempt, "outcome") != "SUCCEEDED"
            or _field(attempt, "eligible") is not True
            or _field(attempt, "call_count_exact") is not True
            or type(_field(attempt, "coinbase_api_call_count")) is not int
            or _field(attempt, "coinbase_api_call_count") < 1
            or (
                category == "PORTFOLIO_CATALOG"
                and portfolio_hash != portfolio_id_sha256
            )
            or (
                category != "PORTFOLIO_CATALOG"
                and portfolio_hash is not None
            )
        ):
            raise _fixed_error("spot_automation_eligibility_attempts_invalid")
        _aware(
            _field(attempt, "observed_at"),
            code="spot_automation_eligibility_attempts_invalid",
        )
        _aware(
            _field(attempt, "fresh_until"),
            code="spot_automation_eligibility_attempts_invalid",
        )
        _sha256(
            _field(attempt, "evidence_sha256"),
            code="spot_automation_eligibility_attempts_invalid",
        )
    return by_category


def build_spot_automation_create_admission(
    *,
    run: Any,
    plan: Any,
    cycle: SpotEligibilityCycleResult,
    snapshot: SpotEligibilityReadSnapshot,
    attempts: Sequence[Any],
    lease: SpotProfileAdmissionLease,
    configured_portfolio_id: str,
    planned_budget: Mapping[str, Any],
    now: datetime,
    goal_key: str = (
        "operator_spot_automation_single_child_execution_adapter_v1"
    ),
) -> ValidatedSpotAutomationAdmissionEvidence:
    """Join one fresh request-local eight-read cycle to canonical admission."""

    if not isinstance(cycle, SpotEligibilityCycleResult) or not isinstance(
        snapshot,
        SpotEligibilityReadSnapshot,
    ):
        raise _fixed_error("spot_automation_eligibility_bundle_invalid")
    current = _aware(now, code="spot_automation_clock_invalid")
    run_id = _canonical_uuid(
        _field(run, "run_id"),
        code="spot_automation_run_binding_invalid",
    )
    definition_id = _canonical_uuid(
        _field(run, "definition_id"),
        code="spot_automation_run_binding_invalid",
    )
    definition_revision = _field(run, "definition_revision")
    plan_sha256 = _sha256(
        _field(plan, "plan_sha256"),
        code="spot_automation_plan_binding_invalid",
    )
    portfolio_sha256 = _sha256(
        _field(plan, "portfolio_id_sha256"),
        code="spot_automation_plan_binding_invalid",
    )
    expected_client_order_id = derive_spot_eligibility_client_order_id(
        run_id=run_id,
        plan_sha256=plan_sha256,
        goal_key=goal_key,
    )
    expected_categories = tuple(APPROVED_SPOT_ELIGIBILITY_ORDER)
    base_size = _decimal(
        _field(plan, "base_size"),
        code="spot_automation_plan_binding_invalid",
        positive=True,
    )
    limit_price = _decimal(
        _field(plan, "limit_price"),
        code="spot_automation_plan_binding_invalid",
        positive=True,
    )
    submitted_notional = _decimal(
        _field(plan, "submitted_notional_usdc"),
        code="spot_automation_plan_binding_invalid",
        positive=True,
    )
    possible_execution_notional = _decimal(
        _field(plan, "possible_execution_notional_usdc"),
        code="spot_automation_plan_binding_invalid",
        positive=True,
    )
    submitted_cap = _decimal(
        _field(plan, "max_submitted_notional_usdc"),
        code="spot_automation_plan_binding_invalid",
        positive=True,
    )
    possible_execution_cap = _decimal(
        _field(plan, "max_possible_execution_notional_usdc"),
        code="spot_automation_plan_binding_invalid",
        positive=True,
    )
    if (
        type(definition_revision) is not int
        or definition_revision < 1
        or _field(run, "definition_id") != _field(plan, "definition_id")
        or definition_revision != _field(plan, "definition_revision")
        or _field(plan, "product_id") != SPOT_AUTOMATION_PRODUCT
        or submitted_cap != MAX_SUBMITTED_NOTIONAL_USDC
        or possible_execution_cap != MAX_EXECUTED_NOTIONAL_USDC
        or submitted_notional > MAX_SUBMITTED_NOTIONAL_USDC
        or possible_execution_notional > MAX_EXECUTED_NOTIONAL_USDC
        or possible_execution_notional > submitted_notional
        or submitted_notional != base_size * limit_price
        or _field(plan, "post_only") is not False
        or cycle.replayed
        or cycle.outcome is not SpotEligibilityReadOutcome.SUCCEEDED
        or not cycle.eligible
        or cycle.attempted_categories != expected_categories
        or cycle.completed_categories != expected_categories
        or not cycle.call_count_exact
        or type(cycle.coinbase_api_call_count) is not int
        or cycle.coinbase_api_call_count < len(expected_categories)
        or cycle.fresh_until is None
        or cycle.fresh_until <= current
        or cycle.client_order_id != expected_client_order_id
        or snapshot.cycle_number != cycle.cycle_number
        or snapshot.plan_sha256 != plan_sha256
        or snapshot.exact_order_absence.client_order_id
        != expected_client_order_id
        or snapshot.exact_order_absence.product_id != SPOT_AUTOMATION_PRODUCT
        or snapshot.market_reference.product_id != SPOT_AUTOMATION_PRODUCT
    ):
        raise _fixed_error("spot_automation_eligibility_binding_mismatch")

    by_category = _validated_attempts(
        run_id=run_id,
        cycle_number=cycle.cycle_number,
        portfolio_id_sha256=portfolio_sha256,
        attempts=attempts,
    )
    attempt_call_count = sum(
        int(_field(item, "coinbase_api_call_count"))
        for item in by_category.values()
    )
    deadlines = tuple(
        _aware(
            _field(item, "fresh_until"),
            code="spot_automation_eligibility_binding_mismatch",
        )
        for item in by_category.values()
    )
    if attempt_call_count != cycle.coinbase_api_call_count or min(deadlines) != (
        cycle.fresh_until.astimezone(timezone.utc)
    ):
        raise _fixed_error("spot_automation_eligibility_binding_mismatch")

    exact_attempt = by_category["EXACT_ORDER_RECONCILIATION"]
    active_attempt = by_category["ACCOUNT_ACTIVE_SPOT_ORDER_CATALOG"]
    market_attempt = by_category["BEST_BID_ASK"]
    wallet_attempt = by_category["ACCOUNT_WALLET_BALANCES"]
    exact_snapshot = snapshot.exact_order_absence
    active_snapshot = snapshot.active_order_catalog_absence
    if (
        exact_snapshot.page_count
        != _field(exact_attempt, "coinbase_api_call_count")
        or exact_snapshot.evidence_sha256
        != _field(exact_attempt, "evidence_sha256")
        or active_snapshot.portfolio_id_sha256 != portfolio_sha256
        or active_snapshot.product_type != "SPOT"
        or active_snapshot.page_count
        != _field(active_attempt, "coinbase_api_call_count")
        or active_snapshot.evidence_sha256
        != _field(active_attempt, "evidence_sha256")
        or snapshot.market_reference.observed_at.astimezone(timezone.utc)
        != _aware(
            _field(market_attempt, "observed_at"),
            code="spot_automation_market_binding_mismatch",
        )
    ):
        raise _fixed_error("spot_automation_eligibility_binding_mismatch")

    if not isinstance(planned_budget, Mapping) or any(
        not isinstance(currency, str)
        or currency != currency.upper()
        or not _decimal(
            amount,
            code="spot_automation_planned_budget_invalid",
        ).is_finite()
        for currency, amount in planned_budget.items()
    ):
        raise _fixed_error("spot_automation_planned_budget_invalid")

    side = str(_field(plan, "side", "")).upper()
    if side not in {OrderSide.BUY.value, OrderSide.SELL.value}:
        raise _fixed_error("spot_automation_plan_binding_invalid")
    required_currency = "USDC" if side == OrderSide.BUY.value else "BTC"
    required_wallet = snapshot.wallets.get(required_currency)
    if required_wallet is None:
        raise _fixed_error("spot_automation_wallet_binding_mismatch")
    btc_wallet = snapshot.wallets.get("BTC")
    planned_commitment = _decimal(
        planned_budget.get(required_currency, 0),
        code="spot_automation_planned_budget_invalid",
    )
    portfolio_binding = _portfolio_binding(
        configured_portfolio_id=configured_portfolio_id,
        expected_portfolio_sha256=portfolio_sha256,
        snapshot=snapshot.portfolio,
    )
    wallet_observed = _aware(
        _field(wallet_attempt, "observed_at"),
        code="spot_automation_wallet_binding_mismatch",
    )
    market_observed = snapshot.market_reference.observed_at.astimezone(
        timezone.utc
    )
    active_observed = _aware(
        _field(active_attempt, "observed_at"),
        code="spot_automation_active_order_binding_mismatch",
    )
    return ValidatedSpotAutomationAdmissionEvidence(
        run_id=run_id,
        definition_id=definition_id,
        definition_revision=definition_revision,
        plan_sha256=plan_sha256,
        client_order_id=expected_client_order_id,
        product_id=SPOT_AUTOMATION_PRODUCT,
        side=side,
        base_size=base_size,
        limit_price=limit_price,
        portfolio_id_sha256=portfolio_sha256,
        fresh_until=cycle.fresh_until.astimezone(timezone.utc),
        portfolio_binding=portfolio_binding,
        lease=lease,
        wallet_evidence=SpotAutomationWalletEvidence(
            required_currency=required_currency,
            available_balance=required_wallet.available_balance,
            planned_commitment=planned_commitment,
            known_inventory_available=btc_wallet is not None,
            known_inventory_base_size=(
                btc_wallet.available_balance
                if btc_wallet is not None
                else Decimal("0")
            ),
            observed_at=wallet_observed,
            fresh_until=_aware(
                _field(wallet_attempt, "fresh_until"),
                code="spot_automation_wallet_binding_mismatch",
            ),
            source="coinbase_account_wallet_refresh",
            evidence_sha256=str(_field(wallet_attempt, "evidence_sha256")),
        ),
        market_evidence=SpotAutomationMarketEvidence(
            best_bid=snapshot.market_reference.best_bid,
            best_ask=snapshot.market_reference.best_ask,
            observed_at=market_observed,
            fresh_until=_aware(
                _field(market_attempt, "fresh_until"),
                code="spot_automation_market_binding_mismatch",
            ),
            source="coinbase_rest_best_bid",
            evidence_sha256=str(_field(market_attempt, "evidence_sha256")),
        ),
        zero_active_order_evidence=SpotAutomationZeroActiveOrderEvidence(
            authoritative=True,
            open_order_count=0,
            logical_call_count=1,
            http_request_count=active_snapshot.page_count,
            call_count_exact=True,
            pagination_complete=True,
            page_count=active_snapshot.page_count,
            observed_at=active_observed,
            fresh_until=_aware(
                _field(active_attempt, "fresh_until"),
                code="spot_automation_active_order_binding_mismatch",
            ),
            evidence_sha256=active_snapshot.evidence_sha256,
        ),
    )


def build_spot_automation_cancel_ownership(
    *,
    run: Any,
    plan: Any,
    execution: Any,
    eligibility_cycle: Any,
    attempts: Sequence[Any],
    lease: SpotProfileAdmissionLease,
    configured_portfolio_id: str,
    now: datetime,
) -> ValidatedSpotAutomationOwnershipEvidence:
    """Build risk-reducing Cancel ownership from durable Create provenance."""

    current = _aware(now, code="spot_automation_clock_invalid")
    run_id = _canonical_uuid(
        _field(run, "run_id"),
        code="spot_automation_run_binding_invalid",
    )
    definition_id = _canonical_uuid(
        _field(run, "definition_id"),
        code="spot_automation_run_binding_invalid",
    )
    plan_sha256 = _sha256(
        _field(plan, "plan_sha256"),
        code="spot_automation_plan_binding_invalid",
    )
    portfolio_sha256 = _sha256(
        _field(plan, "portfolio_id_sha256"),
        code="spot_automation_plan_binding_invalid",
    )
    cycle_number = _field(execution, "eligibility_cycle")
    client_order_id = _canonical_uuid(
        _field(execution, "client_order_id"),
        code="spot_automation_client_order_binding_invalid",
    )
    run_state = _field(run, "state")
    if str(getattr(run_state, "value", run_state)) != "ACTIVE":
        raise _fixed_error("spot_automation_cancel_binding_invalid")
    if (
        _field(execution, "policy_revision") != 2
        or _field(execution, "run_id") != run_id
        or _field(execution, "definition_id") != definition_id
        or _field(execution, "definition_revision")
        != _field(plan, "definition_revision")
        or _field(execution, "plan_sha256") != plan_sha256
        or _field(execution, "portfolio_id_sha256") != portfolio_sha256
        or _field(execution, "product_id") != SPOT_AUTOMATION_PRODUCT
        or _field(execution, "create_allowance_consumed") is not True
        or _field(execution, "create_outcome") != "ACCEPTED"
        or _field(execution, "create_read_call_count_exact") is not True
        or type(_field(execution, "create_read_call_count")) is not int
        or _field(execution, "create_read_call_count") < 1
        or _field(execution, "cancel_allowance_consumed") is not False
        or _field(execution, "child_terminal") is not False
        or type(cycle_number) is not int
        or _field(eligibility_cycle, "cycle_number") != cycle_number
        or _field(eligibility_cycle, "policy_revision") != 2
        or _field(eligibility_cycle, "state") != "SUCCEEDED"
        or _field(eligibility_cycle, "run_id") != run_id
        or _field(eligibility_cycle, "plan_sha256") != plan_sha256
        or _field(eligibility_cycle, "portfolio_id_sha256")
        != portfolio_sha256
        or _field(eligibility_cycle, "client_order_id") != client_order_id
    ):
        raise _fixed_error("spot_automation_cancel_binding_invalid")
    _validated_attempts(
        run_id=run_id,
        cycle_number=cycle_number,
        portfolio_id_sha256=portfolio_sha256,
        attempts=attempts,
    )
    portfolio_binding = _portfolio_binding(
        configured_portfolio_id=configured_portfolio_id,
        expected_portfolio_sha256=portfolio_sha256,
    )
    return ValidatedSpotAutomationOwnershipEvidence(
        run_id=run_id,
        definition_id=definition_id,
        definition_revision=int(_field(plan, "definition_revision")),
        plan_sha256=plan_sha256,
        client_order_id=client_order_id,
        product_id=SPOT_AUTOMATION_PRODUCT,
        side=str(_field(plan, "side")).upper(),
        base_size=_decimal(
            _field(plan, "base_size"),
            code="spot_automation_plan_binding_invalid",
            positive=True,
        ),
        limit_price=_decimal(
            _field(plan, "limit_price"),
            code="spot_automation_plan_binding_invalid",
            positive=True,
        ),
        portfolio_id_sha256=portfolio_sha256,
        # This freshness covers the request-local revalidation of immutable
        # ownership and installed configuration.  The original Coinbase Test
        # binding remains durably proven by the exact successful cycle above.
        fresh_until=current + _OWNERSHIP_LOCAL_FRESHNESS,
        portfolio_binding=portfolio_binding,
        lease=lease,
    )


def _actor(*, actor_id: str, roles: Sequence[str]) -> AdminApiActor:
    try:
        typed_roles = [AdminApiRole(role) for role in roles]
    except ValueError:
        raise _fixed_error("spot_automation_actor_roles_invalid") from None
    if not typed_roles:
        raise _fixed_error("spot_automation_actor_roles_invalid")
    return AdminApiActor(actor_id=actor_id, roles=typed_roles)


def prepare_spot_automation_create_command(
    *,
    run: Any,
    plan: Any,
    client_order_id: str,
    actor_id: str,
    roles: Sequence[str],
    correlation_id: str,
    operator_intent: str,
    outer_idempotency_key: str,
) -> PreparedSpotAutomationCommand:
    plan_sha256 = _sha256(
        _field(plan, "plan_sha256"),
        code="spot_automation_plan_binding_invalid",
    )
    run_id = _canonical_uuid(
        _field(run, "run_id"),
        code="spot_automation_run_binding_invalid",
    )
    request = ManualOrderRequest(
        client_order_id=_canonical_uuid(
            client_order_id,
            code="spot_automation_client_order_binding_invalid",
        ),
        product_id=SPOT_AUTOMATION_PRODUCT,
        side=OrderSide(str(_field(plan, "side")).upper()),
        order_type=OrderType.LIMIT,
        base_size=str(_field(plan, "base_size")),
        limit_price=str(_field(plan, "limit_price")),
        post_only=bool(_field(plan, "post_only")),
        time_in_force=TimeInForce.GOOD_UNTIL_CANCELLED,
        manual_live_acknowledgement=True,
    )
    command_key = derive_spot_automation_phase_key(
        outer_idempotency_key=outer_idempotency_key,
        run_id=run_id,
        plan_sha256=plan_sha256,
        phase="create-command",
    )
    envelope = AdminApiCommandEnvelope(
        idempotency_key=command_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=_actor(actor_id=actor_id, roles=roles),
    )
    payload_hash = _payload_sha256(
        {
            "route": CREATE_ROUTE,
            "method": "POST",
            "run_id": run_id,
            "plan_sha256": plan_sha256,
            "body": request.model_dump(mode="json"),
        }
    )
    proof_context = {
        "route": CREATE_ROUTE,
        "method": "POST",
        "module_id": SPOT_AUTOMATION_MODULE,
        "identity_key": "client_order_id",
        "identity_value": client_order_id,
        "action_class": AdminApiActionClass.LIVE_EXCHANGE_PLACE.value,
        "required_permission": AdminApiPermission.ORDER_CREATE.value,
        "service_method": "place_manual_order",
        "actor_id": actor_id,
        "operator_intent": operator_intent,
        "command_idempotency_key": command_key,
        "correlation_id": correlation_id,
        "payload_hash": payload_hash,
        "product_scope": SPOT_AUTOMATION_PRODUCT,
    }
    return PreparedSpotAutomationCommand(
        envelope=envelope,
        proof_context=proof_context,
        manual_request=request,
    )


def bind_spot_automation_create_command(
    *,
    prepared: PreparedSpotAutomationCommand,
    proof_chain: Mapping[str, Any],
) -> ManualOrderCommand:
    if prepared.manual_request is None or proof_chain.get("status") != "passed":
        raise _fixed_error("spot_automation_proof_chain_invalid")
    approval = proof_chain.get("approval")
    audit = proof_chain.get("admission_audit")
    cap = proof_chain.get("cap_guard")
    if not all(isinstance(item, Mapping) for item in (approval, audit, cap)):
        raise _fixed_error("spot_automation_proof_chain_invalid")
    approval_id = str(approval.get("approval_id") or "")
    audit_id = str(audit.get("audit_id") or "")
    cap_id = str(cap.get("decision_id") or "")
    if not approval_id or not audit_id or not cap_id:
        raise _fixed_error("spot_automation_proof_chain_invalid")
    return ManualOrderCommand(
        envelope=prepared.envelope,
        request=prepared.manual_request,
        admin_approval_snapshot_id=approval_id,
        admin_cap_guard_decision_id=cap_id,
        admin_max_submitted_notional_usdc=str(MAX_SUBMITTED_NOTIONAL_USDC),
        admin_max_executed_notional_usdc=str(MAX_EXECUTED_NOTIONAL_USDC),
        admission_audit_id=audit_id,
        allow_live_execution=True,
    )


def prepare_spot_automation_cancel_command(
    *,
    run: Any,
    plan: Any,
    client_order_id: str,
    actor_id: str,
    roles: Sequence[str],
    correlation_id: str,
    operator_intent: str,
    outer_idempotency_key: str,
    reason: str,
) -> PreparedSpotAutomationCommand:
    plan_sha256 = _sha256(
        _field(plan, "plan_sha256"),
        code="spot_automation_plan_binding_invalid",
    )
    run_id = _canonical_uuid(
        _field(run, "run_id"),
        code="spot_automation_run_binding_invalid",
    )
    child_id = _canonical_uuid(
        client_order_id,
        code="spot_automation_client_order_binding_invalid",
    )
    request = CancelOrderRequest(
        reason=reason,
        manual_live_acknowledgement=True,
    )
    command_key = derive_spot_automation_phase_key(
        outer_idempotency_key=outer_idempotency_key,
        run_id=run_id,
        plan_sha256=plan_sha256,
        phase="cancel-command",
    )
    envelope = AdminApiCommandEnvelope(
        idempotency_key=command_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=_actor(actor_id=actor_id, roles=roles),
    )
    payload_hash = _payload_sha256(
        {
            "route": CANCEL_ROUTE,
            "method": "POST",
            "run_id": run_id,
            "plan_sha256": plan_sha256,
            "path": {"client_order_id": child_id},
            "body": request.model_dump(mode="json"),
        }
    )
    proof_context = {
        "route": CANCEL_ROUTE,
        "method": "POST",
        "module_id": SPOT_AUTOMATION_MODULE,
        "identity_key": "client_order_id",
        "identity_value": child_id,
        "action_class": AdminApiActionClass.LIVE_EXCHANGE_CANCEL.value,
        "required_permission": AdminApiPermission.ORDER_CANCEL.value,
        "service_method": "cancel_order_by_client_order_id",
        "actor_id": actor_id,
        "operator_intent": operator_intent,
        "command_idempotency_key": command_key,
        "correlation_id": correlation_id,
        "payload_hash": payload_hash,
        "product_scope": SPOT_AUTOMATION_PRODUCT,
    }
    return PreparedSpotAutomationCommand(
        envelope=envelope,
        proof_context=proof_context,
        cancel_request=request,
    )


def bind_spot_automation_cancel_command(
    *,
    prepared: PreparedSpotAutomationCommand,
    proof_chain: Mapping[str, Any],
) -> CancelOrderCommand:
    if prepared.cancel_request is None or proof_chain.get("status") != "passed":
        raise _fixed_error("spot_automation_proof_chain_invalid")
    return CancelOrderCommand(
        envelope=prepared.envelope,
        client_order_id=str(prepared.proof_context["identity_value"]),
        request=prepared.cancel_request,
        allow_live_execution=True,
    )


__all__ = [
    "CANCEL_ROUTE",
    "CREATE_ROUTE",
    "MAX_EXECUTED_NOTIONAL_USDC",
    "MAX_SUBMITTED_NOTIONAL_USDC",
    "PreparedSpotAutomationCommand",
    "SPOT_AUTOMATION_MODULE",
    "SPOT_AUTOMATION_PRODUCT",
    "SpotAutomationRuntimeBindingError",
    "bind_spot_automation_cancel_command",
    "bind_spot_automation_create_command",
    "build_spot_automation_cancel_ownership",
    "build_spot_automation_create_admission",
    "derive_spot_automation_phase_key",
    "prepare_spot_automation_cancel_command",
    "prepare_spot_automation_create_command",
]
