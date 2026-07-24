"""Goal-bound Hotpoint controls and one durable placement dispatch.

The operator controls a backend-owned kill switch and one bounded trigger
window.  Neither control nor run requests contain child order terms.  The
repository derives and claims one immutable plan before the exchange-facing
executor can be invoked.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import re
from typing import Any, Callable, Protocol


HOTPOINT_GOAL_ID = "operator_hotpoint_control_and_single_placement_v1"
HOTPOINT_CONTROL_OPERATOR_INTENT = "control_operator_hotpoint"
HOTPOINT_RUN_OPERATOR_INTENT = "run_operator_hotpoint_once"
HOTPOINT_SAFE_CLOSEOUT_OPERATOR_INTENT = "safe_closeout_operator_hotpoint_child"

HOTPOINT_MAX_SUBMITTED_NOTIONAL_USDC = Decimal("3.10")
HOTPOINT_MAX_POSSIBLE_EXECUTION_NOTIONAL_USDC = Decimal("1.00")
FUTURES_HOTPOINT_OPENING_CAP_USDC = Decimal("100")
FUTURES_HOTPOINT_EXPOSURE_CAP_USDC = Decimal("150")
FUTURES_HOTPOINT_TURNOVER_CAP_USDC = Decimal("300")

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class HotpointKillSwitchState(str, Enum):
    DISABLED = "DISABLED"
    ENABLED = "ENABLED"


class HotpointWindowState(str, Enum):
    NONE = "NONE"
    ARMED = "ARMED"
    CLAIMED = "CLAIMED"
    TERMINAL = "TERMINAL"
    DISARMED = "DISARMED"
    EXPIRED = "EXPIRED"

    @property
    def is_terminal(self) -> bool:
        return self in {
            HotpointWindowState.TERMINAL,
            HotpointWindowState.DISARMED,
            HotpointWindowState.EXPIRED,
        }


class HotpointCreateState(str, Enum):
    NOT_CLAIMED = "NOT_CLAIMED"
    CLAIMED = "CLAIMED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"

    @property
    def is_terminal(self) -> bool:
        return self in {
            HotpointCreateState.ACCEPTED,
            HotpointCreateState.REJECTED,
            HotpointCreateState.UNKNOWN,
        }


class HotpointCancelState(str, Enum):
    NOT_CLAIMED = "NOT_CLAIMED"
    CLAIMED = "CLAIMED"
    NOT_REQUIRED = "NOT_REQUIRED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"

    @property
    def is_terminal(self) -> bool:
        return self in {
            HotpointCancelState.NOT_REQUIRED,
            HotpointCancelState.ACCEPTED,
            HotpointCancelState.REJECTED,
            HotpointCancelState.UNKNOWN,
        }


class HotpointPlacementOutcome(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class HotpointControlAction(str, Enum):
    ENABLE = "ENABLE"
    DISABLE = "DISABLE"
    ARM = "ARM"
    DISARM = "DISARM"


@dataclass(frozen=True, slots=True)
class HotpointScopePolicy:
    """One domain-owned Hotpoint product, profile, sizing, and cap policy."""

    domain: str
    portfolio_profile_alias: str
    product_id: str
    max_submitted_notional_usdc: Decimal
    max_possible_execution_notional_usdc: Decimal
    max_turnover_notional_usdc: Decimal | None
    exact_size: Decimal | None
    strict_caps: bool


SPOT_HOTPOINT_SCOPE_POLICY = HotpointScopePolicy(
    domain="SPOT",
    portfolio_profile_alias="Test",
    product_id="BTC-USDC",
    max_submitted_notional_usdc=HOTPOINT_MAX_SUBMITTED_NOTIONAL_USDC,
    max_possible_execution_notional_usdc=(
        HOTPOINT_MAX_POSSIBLE_EXECUTION_NOTIONAL_USDC
    ),
    max_turnover_notional_usdc=None,
    exact_size=None,
    strict_caps=False,
)
FUTURES_HOTPOINT_SCOPE_POLICY = HotpointScopePolicy(
    domain="FUTURES",
    portfolio_profile_alias="Default",
    product_id="AVP-20DEC30-CDE",
    max_submitted_notional_usdc=FUTURES_HOTPOINT_OPENING_CAP_USDC,
    max_possible_execution_notional_usdc=FUTURES_HOTPOINT_EXPOSURE_CAP_USDC,
    max_turnover_notional_usdc=FUTURES_HOTPOINT_TURNOVER_CAP_USDC,
    exact_size=Decimal("1"),
    strict_caps=True,
)


@dataclass(frozen=True, slots=True)
class OperatorHotpointControlRecord:
    goal_id: str
    revision: int
    kill_switch_state: HotpointKillSwitchState
    window_state: HotpointWindowState
    parent_client_order_id: str | None
    product_id: str | None
    side: str | None
    window_id: str | None
    window_started_at: str | None
    window_expires_at: str | None
    create_state: HotpointCreateState
    cancel_state: HotpointCancelState
    create_exchange_invoked: bool | None
    cancel_exchange_invoked: bool | None
    placement_claim_id: str | None
    cancel_claim_id: str | None
    child_client_order_id: str | None
    diagnostic_code: str
    actor_id: str
    roles: tuple[str, ...]
    correlation_id: str
    audit_id: str
    recorded_at: str
    updated_at: str
    goal_create_claim_consumed: bool = False
    goal_create_claim_domain: str | None = None
    goal_cancel_claim_consumed: bool = False
    goal_cancel_claim_domain: str | None = None


@dataclass(frozen=True, slots=True)
class OperatorHotpointRequestContext:
    actor_id: str
    roles: tuple[str, ...]
    idempotency_key: str
    correlation_id: str
    audit_id: str
    operator_intent: str


@dataclass(frozen=True, slots=True)
class HotpointPlacementPlan:
    goal_id: str
    window_id: str
    placement_claim_id: str
    parent_client_order_id: str
    child_client_order_id: str
    product_id: str
    side: str
    base_size: Decimal
    limit_price: Decimal
    post_only: bool
    submitted_notional_usdc: Decimal
    possible_execution_notional_usdc: Decimal
    max_submitted_notional_usdc: Decimal
    max_possible_execution_notional_usdc: Decimal
    evidence_sha256: str
    portfolio_id: str
    actor_id: str
    roles: tuple[str, ...]
    correlation_id: str
    audit_id: str


@dataclass(frozen=True, slots=True)
class HotpointPlacementExecution:
    outcome: HotpointPlacementOutcome
    child_client_order_id: str | None
    diagnostic_code: str
    exchange_invoked: bool


@dataclass(frozen=True, slots=True)
class HotpointCancelPlan:
    goal_id: str
    cancel_claim_id: str
    placement_claim_id: str
    parent_client_order_id: str
    child_client_order_id: str
    product_id: str
    plan_sha256: str
    portfolio_id: str
    actor_id: str
    roles: tuple[str, ...]
    correlation_id: str
    audit_id: str


@dataclass(frozen=True, slots=True)
class HotpointCancelExecution:
    outcome: HotpointPlacementOutcome
    child_client_order_id: str | None
    diagnostic_code: str
    exchange_invoked: bool


class OperatorHotpointControlRepository(Protocol):
    def read(self) -> OperatorHotpointControlRecord: ...

    def list_eligible_parents(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, str]], int]: ...

    def transition_control(self, **kwargs: Any) -> OperatorHotpointControlRecord: ...

    def claim_placement(
        self,
        **kwargs: Any,
    ) -> tuple[OperatorHotpointControlRecord, HotpointPlacementPlan] | None: ...

    def finalize_placement(
        self,
        **kwargs: Any,
    ) -> OperatorHotpointControlRecord: ...

    def claim_cancel(
        self,
        **kwargs: Any,
    ) -> tuple[OperatorHotpointControlRecord, HotpointCancelPlan] | None: ...

    def finalize_cancel(
        self,
        **kwargs: Any,
    ) -> OperatorHotpointControlRecord: ...


class OperatorHotpointControlError(RuntimeError):
    """Fixed, value-blind application error."""

    def __init__(self, code: str, http_status_code: int) -> None:
        self.code = str(code)
        self.http_status_code = int(http_status_code)
        super().__init__(self.code)


def _required_text(value: object, *, code: str, maximum: int = 255) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > maximum:
        raise OperatorHotpointControlError(code, 422)
    return normalized


def _has_operator_role(roles: tuple[str, ...]) -> bool:
    return bool(
        {"admin", "trader"}.intersection(
            {str(role).strip().lower() for role in roles}
        )
    )


def _validate_context(
    context: OperatorHotpointRequestContext,
    *,
    operator_intent: str,
    code: str,
) -> OperatorHotpointRequestContext:
    if (
        not isinstance(context, OperatorHotpointRequestContext)
        or context.operator_intent != operator_intent
        or not _has_operator_role(context.roles)
    ):
        raise OperatorHotpointControlError(code, 422)
    _required_text(context.actor_id, code=code)
    _required_text(context.idempotency_key, code=code)
    _required_text(context.correlation_id, code=code)
    _required_text(context.audit_id, code=code, maximum=64)
    return context


def _validate_record(
    record: OperatorHotpointControlRecord,
    policy: HotpointScopePolicy,
) -> OperatorHotpointControlRecord:
    if (
        not isinstance(record, OperatorHotpointControlRecord)
        or record.goal_id != HOTPOINT_GOAL_ID
        or not isinstance(policy, HotpointScopePolicy)
        or (
            record.product_id is not None
            and record.product_id != policy.product_id
        )
        or type(record.revision) is not int
        or record.revision < 0
        or not isinstance(record.kill_switch_state, HotpointKillSwitchState)
        or not isinstance(record.window_state, HotpointWindowState)
        or not isinstance(record.create_state, HotpointCreateState)
        or not isinstance(record.cancel_state, HotpointCancelState)
        or (
            record.create_state is HotpointCreateState.CLAIMED
            and not record.placement_claim_id
        )
        or (
            record.create_state is HotpointCreateState.ACCEPTED
            and not record.child_client_order_id
        )
        or (
            record.goal_create_claim_consumed
            and record.goal_create_claim_domain not in {"SPOT", "FUTURES"}
        )
        or (
            record.goal_cancel_claim_consumed
            and record.goal_cancel_claim_domain != record.goal_create_claim_domain
        )
    ):
        raise OperatorHotpointControlError(
            "operator_hotpoint_record_invalid",
            503,
        )
    return record


def _cap_exceeded(
    value: Decimal,
    cap: Decimal,
    *,
    strict: bool,
) -> bool:
    return value >= cap if strict else value > cap


def _validate_plan(
    plan: HotpointPlacementPlan,
    policy: HotpointScopePolicy,
) -> HotpointPlacementPlan:
    if (
        not isinstance(plan, HotpointPlacementPlan)
        or plan.goal_id != HOTPOINT_GOAL_ID
        or not isinstance(policy, HotpointScopePolicy)
        or plan.product_id != policy.product_id
        or plan.side not in {"BUY", "SELL"}
        or plan.base_size <= 0
        or (
            policy.exact_size is not None
            and plan.base_size != policy.exact_size
        )
        or plan.limit_price <= 0
        or plan.post_only is not True
        or plan.submitted_notional_usdc
        != plan.base_size * plan.limit_price
        or plan.possible_execution_notional_usdc
        != plan.submitted_notional_usdc
        or plan.max_submitted_notional_usdc
        != policy.max_submitted_notional_usdc
        or plan.max_possible_execution_notional_usdc
        != policy.max_possible_execution_notional_usdc
        or _cap_exceeded(
            plan.submitted_notional_usdc,
            plan.max_submitted_notional_usdc,
            strict=policy.strict_caps,
        )
        or _cap_exceeded(
            plan.possible_execution_notional_usdc,
            plan.max_possible_execution_notional_usdc,
            strict=policy.strict_caps,
        )
        or (
            policy.max_turnover_notional_usdc is not None
            and _cap_exceeded(
                plan.submitted_notional_usdc,
                policy.max_turnover_notional_usdc,
                strict=policy.strict_caps,
            )
        )
        or not _SHA256_RE.fullmatch(plan.evidence_sha256)
        or not plan.portfolio_id
        or not plan.actor_id
        or not _has_operator_role(plan.roles)
        or not plan.correlation_id
        or not plan.audit_id
    ):
        raise OperatorHotpointControlError(
            "operator_hotpoint_plan_invalid",
            503,
        )
    return plan


def _validate_cancel_plan(
    plan: HotpointCancelPlan,
    policy: HotpointScopePolicy,
) -> HotpointCancelPlan:
    if (
        not isinstance(plan, HotpointCancelPlan)
        or plan.goal_id != HOTPOINT_GOAL_ID
        or not isinstance(policy, HotpointScopePolicy)
        or not plan.cancel_claim_id
        or not plan.placement_claim_id
        or not plan.parent_client_order_id
        or not plan.child_client_order_id
        or plan.product_id != policy.product_id
        or not _SHA256_RE.fullmatch(plan.plan_sha256)
        or not plan.portfolio_id
        or not plan.actor_id
        or not _has_operator_role(plan.roles)
        or not plan.correlation_id
        or not plan.audit_id
    ):
        raise OperatorHotpointControlError(
            "operator_hotpoint_cancel_plan_invalid",
            503,
        )
    return plan


class OperatorHotpointControlService:
    """Own local controls and the only one-child execution dispatch."""

    def __init__(
        self,
        *,
        repository: OperatorHotpointControlRepository,
        placement_executor: Callable[
            [HotpointPlacementPlan],
            HotpointPlacementExecution,
        ],
        cancel_executor: Callable[
            [HotpointCancelPlan],
            HotpointCancelExecution,
        ]
        | None = None,
        policy: HotpointScopePolicy = SPOT_HOTPOINT_SCOPE_POLICY,
        placement_execution_available: bool = True,
        cancel_execution_available: bool = True,
    ) -> None:
        self.repository = repository
        self.placement_executor = placement_executor
        self.cancel_executor = cancel_executor
        if not isinstance(policy, HotpointScopePolicy):
            raise ValueError("operator_hotpoint_scope_policy_invalid")
        self.policy = policy
        self.placement_execution_available = bool(
            placement_execution_available
        )
        self.cancel_execution_available = bool(cancel_execution_available)
        self.control_available = True

    def read(self) -> OperatorHotpointControlRecord:
        try:
            record = self.repository.read()
        except OperatorHotpointControlError:
            raise
        except Exception:
            raise OperatorHotpointControlError(
                "operator_hotpoint_backend_unavailable",
                503,
            ) from None
        return _validate_record(record, self.policy)

    def list_eligible_parents(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, str]], int]:
        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or type(offset) is not int
            or offset < 0
        ):
            raise OperatorHotpointControlError(
                "operator_hotpoint_pagination_invalid",
                422,
            )
        try:
            rows, total = self.repository.list_eligible_parents(
                limit=limit,
                offset=offset,
            )
        except Exception:
            raise OperatorHotpointControlError(
                "operator_hotpoint_parent_catalog_unavailable",
                503,
            ) from None
        if type(total) is not int or total < 0:
            raise OperatorHotpointControlError(
                "operator_hotpoint_parent_catalog_invalid",
                503,
            )
        public_rows: list[dict[str, str]] = []
        for row in rows:
            if (
                not isinstance(row, dict)
                or not row.get("client_order_id")
                or row.get("product_id") != self.policy.product_id
                or row.get("side") not in {"BUY", "SELL"}
                or row.get("status") != "OPEN"
            ):
                raise OperatorHotpointControlError(
                    "operator_hotpoint_parent_catalog_invalid",
                    503,
                )
            public_rows.append(
                {
                    "client_order_id": str(row["client_order_id"]),
                    "product_id": self.policy.product_id,
                    "side": str(row["side"]),
                    "status": "OPEN",
                }
            )
        return public_rows, total

    def control(
        self,
        *,
        action: HotpointControlAction,
        expected_revision: int,
        confirm_control_action: bool,
        authorize_one_bounded_trigger_window: bool = False,
        acknowledge_unknown_outcome_consumes_create_allowance: bool = False,
        acknowledge_backend_derives_child_terms: bool = False,
        context: OperatorHotpointRequestContext,
        parent_client_order_id: str | None = None,
    ) -> OperatorHotpointControlRecord:
        _validate_context(
            context,
            operator_intent=HOTPOINT_CONTROL_OPERATOR_INTENT,
            code="operator_hotpoint_control_authority_invalid",
        )
        if (
            not isinstance(action, HotpointControlAction)
            or type(expected_revision) is not int
            or expected_revision < 0
            or confirm_control_action is not True
        ):
            raise OperatorHotpointControlError(
                "operator_hotpoint_control_invalid",
                422,
            )
        delegated_authority = bool(
            authorize_one_bounded_trigger_window is True
            and acknowledge_unknown_outcome_consumes_create_allowance is True
            and acknowledge_backend_derives_child_terms is True
        )
        if action is HotpointControlAction.ENABLE and not delegated_authority:
            raise OperatorHotpointControlError(
                "operator_hotpoint_enable_authority_required",
                422,
            )
        if (
            action is not HotpointControlAction.ENABLE
            and any(
                (
                    authorize_one_bounded_trigger_window,
                    acknowledge_unknown_outcome_consumes_create_allowance,
                    acknowledge_backend_derives_child_terms,
                )
            )
        ):
            raise OperatorHotpointControlError(
                "operator_hotpoint_control_authority_invalid",
                422,
            )
        if action is HotpointControlAction.ARM:
            _required_text(
                parent_client_order_id,
                code="operator_hotpoint_parent_invalid",
                maximum=128,
            )
        kwargs: dict[str, Any] = {
            "action": action,
            "expected_revision": expected_revision,
            "authorize_one_bounded_trigger_window": (
                authorize_one_bounded_trigger_window
            ),
            "acknowledge_unknown_outcome_consumes_create_allowance": (
                acknowledge_unknown_outcome_consumes_create_allowance
            ),
            "acknowledge_backend_derives_child_terms": (
                acknowledge_backend_derives_child_terms
            ),
            "idempotency_key": context.idempotency_key,
            "actor_id": context.actor_id,
            "roles": context.roles,
            "correlation_id": context.correlation_id,
            "audit_id": context.audit_id,
        }
        if action is HotpointControlAction.ARM:
            kwargs["parent_client_order_id"] = parent_client_order_id
        try:
            record = self.repository.transition_control(**kwargs)
        except OperatorHotpointControlError:
            raise
        except Exception:
            raise OperatorHotpointControlError(
                "operator_hotpoint_control_unavailable",
                503,
            ) from None
        return _validate_record(record, self.policy)

    def run_once(
        self,
        *,
        context: OperatorHotpointRequestContext,
    ) -> OperatorHotpointControlRecord:
        _validate_context(
            context,
            operator_intent=HOTPOINT_RUN_OPERATOR_INTENT,
            code="operator_hotpoint_run_authority_invalid",
        )
        if not self.placement_execution_available:
            raise OperatorHotpointControlError(
                "operator_hotpoint_domain_execution_unavailable",
                503,
            )
        try:
            claim = self.repository.claim_placement(
                idempotency_key=context.idempotency_key,
                actor_id=context.actor_id,
                roles=context.roles,
                correlation_id=context.correlation_id,
                audit_id=context.audit_id,
            )
        except Exception:
            raise OperatorHotpointControlError(
                "operator_hotpoint_claim_unavailable",
                503,
            ) from None
        if claim is None:
            return self.read()
        claimed_record, plan = claim
        _validate_record(claimed_record, self.policy)
        plan = _validate_plan(plan, self.policy)
        if (
            claimed_record.create_state is not HotpointCreateState.CLAIMED
            or claimed_record.placement_claim_id
            != plan.placement_claim_id
            or claimed_record.parent_client_order_id
            != plan.parent_client_order_id
        ):
            raise OperatorHotpointControlError(
                "operator_hotpoint_claim_invalid",
                503,
            )
        try:
            execution = self.placement_executor(plan)
            if not isinstance(execution, HotpointPlacementExecution):
                raise TypeError("invalid execution result")
            outcome = execution.outcome
            exchange_invoked = execution.exchange_invoked
            child_id = execution.child_client_order_id
            diagnostic = execution.diagnostic_code
            if (
                outcome is HotpointPlacementOutcome.ACCEPTED
                and (
                    child_id != plan.child_client_order_id
                    or execution.exchange_invoked is not True
                )
            ):
                outcome = HotpointPlacementOutcome.UNKNOWN
                child_id = None
                diagnostic = "operator_hotpoint_create_outcome_unknown"
            elif outcome is not HotpointPlacementOutcome.ACCEPTED:
                child_id = None
        except Exception:
            outcome = HotpointPlacementOutcome.UNKNOWN
            exchange_invoked = None
            child_id = None
            diagnostic = "operator_hotpoint_create_outcome_unknown"
        if outcome is HotpointPlacementOutcome.UNKNOWN:
            diagnostic = "operator_hotpoint_create_outcome_unknown"
        elif outcome is HotpointPlacementOutcome.REJECTED:
            diagnostic = "operator_hotpoint_create_rejected"
        elif outcome is HotpointPlacementOutcome.ACCEPTED:
            diagnostic = "operator_hotpoint_create_accepted"
        else:
            raise OperatorHotpointControlError(
                "operator_hotpoint_execution_invalid",
                503,
            )
        try:
            result = self.repository.finalize_placement(
                placement_claim_id=plan.placement_claim_id,
                outcome=outcome,
                child_client_order_id=child_id,
                diagnostic_code=diagnostic,
                exchange_invoked=exchange_invoked,
            )
        except Exception:
            raise OperatorHotpointControlError(
                "operator_hotpoint_terminal_persistence_unknown",
                503,
            ) from None
        return _validate_record(result, self.policy)

    def safe_closeout(
        self,
        *,
        confirm_exact_child_safe_closeout: bool,
        acknowledge_unknown_outcome_consumes_cancel_allowance: bool,
        context: OperatorHotpointRequestContext,
    ) -> OperatorHotpointControlRecord:
        _validate_context(
            context,
            operator_intent=HOTPOINT_SAFE_CLOSEOUT_OPERATOR_INTENT,
            code="operator_hotpoint_cancel_authority_invalid",
        )
        if not self.cancel_execution_available:
            raise OperatorHotpointControlError(
                "operator_hotpoint_domain_cancel_unavailable",
                503,
            )
        if (
            confirm_exact_child_safe_closeout is not True
            or acknowledge_unknown_outcome_consumes_cancel_allowance is not True
            or self.cancel_executor is None
        ):
            raise OperatorHotpointControlError(
                "operator_hotpoint_cancel_authority_invalid",
                422,
            )
        try:
            claim = self.repository.claim_cancel(
                idempotency_key=context.idempotency_key,
                actor_id=context.actor_id,
                roles=context.roles,
                correlation_id=context.correlation_id,
                audit_id=context.audit_id,
            )
        except Exception:
            raise OperatorHotpointControlError(
                "operator_hotpoint_cancel_claim_unavailable",
                503,
            ) from None
        if claim is None:
            return self.read()
        claimed_record, plan = claim
        _validate_record(claimed_record, self.policy)
        plan = _validate_cancel_plan(plan, self.policy)
        if (
            claimed_record.cancel_state is not HotpointCancelState.CLAIMED
            or claimed_record.cancel_claim_id != plan.cancel_claim_id
            or claimed_record.child_client_order_id
            != plan.child_client_order_id
        ):
            raise OperatorHotpointControlError(
                "operator_hotpoint_cancel_claim_invalid",
                503,
            )
        try:
            execution = self.cancel_executor(plan)
            if not isinstance(execution, HotpointCancelExecution):
                raise TypeError("invalid cancel execution result")
            outcome = execution.outcome
            exchange_invoked = execution.exchange_invoked
            child_id = execution.child_client_order_id
            if (
                outcome is HotpointPlacementOutcome.ACCEPTED
                and (
                    child_id != plan.child_client_order_id
                    or execution.exchange_invoked is not True
                )
            ):
                outcome = HotpointPlacementOutcome.UNKNOWN
        except Exception:
            outcome = HotpointPlacementOutcome.UNKNOWN
            exchange_invoked = None
        diagnostic = {
            HotpointPlacementOutcome.ACCEPTED: (
                "operator_hotpoint_cancel_accepted"
            ),
            HotpointPlacementOutcome.REJECTED: (
                "operator_hotpoint_cancel_rejected"
            ),
            HotpointPlacementOutcome.UNKNOWN: (
                "operator_hotpoint_cancel_outcome_unknown"
            ),
        }.get(outcome)
        if diagnostic is None:
            raise OperatorHotpointControlError(
                "operator_hotpoint_cancel_execution_invalid",
                503,
            )
        try:
            result = self.repository.finalize_cancel(
                cancel_claim_id=plan.cancel_claim_id,
                outcome=outcome,
                diagnostic_code=diagnostic,
                exchange_invoked=exchange_invoked,
            )
        except Exception:
            raise OperatorHotpointControlError(
                "operator_hotpoint_cancel_terminal_persistence_unknown",
                503,
            ) from None
        return _validate_record(result, self.policy)
