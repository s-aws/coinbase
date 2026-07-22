"""Operator Automation orchestration and PostgreSQL adaptation.

This module imports no Coinbase SDK, Futures service, or legacy automation
runner. Durable repositories implement the narrow protocol below. The current
adapter is structurally source-gated before every eligibility or exchange
boundary because one canonical read lacks goal authority.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
from typing import Any, Callable, Mapping, Protocol
import uuid

from .automation_models import (
    AutomationControlAction,
    AutomationControlEventItem,
    AutomationControlEventListResponse,
    AutomationControlMutationResponse,
    AutomationControlPlaneItem,
    AutomationControlPlaneResponse,
    AutomationControlRequest,
    AutomationDefinitionCreateRequest,
    AutomationDefinitionDetailResponse,
    AutomationDefinitionEventItem,
    AutomationDefinitionEventListResponse,
    AutomationDefinitionItem,
    AutomationDefinitionLifecycleAction,
    AutomationDefinitionLifecycleRequest,
    AutomationDefinitionListResponse,
    AutomationDefinitionMutationResponse,
    AutomationDefinitionScheduleRequest,
    AutomationDefinitionState,
    AutomationDomain,
    AutomationEligibilityCycleMutationResponse,
    AutomationEligibilityRefreshActivity,
    AutomationEligibilityRefreshRequest,
    AutomationFilters,
    AutomationJobKind,
    AutomationMutationContext,
    AutomationMinimumSizeCandidatePreparationRequest,
    AutomationMinimumSizeCandidatePreparationResponse,
    AutomationAtomicMarketSnapshotAuthorizationRequest,
    AutomationAtomicMarketSnapshotMutationResponse,
    AutomationNearMarketCandidatePreparationRequest,
    AutomationNearMarketCandidatePreparationResponse,
    AutomationOneShotRunRequest,
    AutomationPreviewGatedSingleChildAuthorizationRequest,
    AutomationSingleChildAuthorizationRequest,
    AutomationSingleChildSafeCloseoutRequest,
    AutomationPagination,
    AutomationRunDetailResponse,
    AutomationRunEventItem,
    AutomationRunEventListResponse,
    AutomationRunFilters,
    AutomationRunItem,
    AutomationRunListResponse,
    AutomationRunMutationActivity,
    AutomationRunMutationResponse,
    AutomationRunState,
    domain_for_job_kind,
)
from .operator_spot_eligibility import (
    SPOT_ELIGIBILITY_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
    SPOT_ELIGIBILITY_NEAR_MARKET_V4_GOAL_KEY,
    SPOT_ELIGIBILITY_NEAR_MARKET_V5_GOAL_KEY,
    SPOT_ELIGIBILITY_NEAR_MARKET_V6_GOAL_KEY,
    SPOT_ELIGIBILITY_MINIMUM_SIZE_V7_GOAL_KEY,
    SPOT_ELIGIBILITY_MINIMUM_SIZE_V8_GOAL_KEY,
    SPOT_ELIGIBILITY_MINIMUM_SIZE_V9_GOAL_KEY,
    SPOT_ELIGIBILITY_ATOMIC_MARKET_SNAPSHOT_V10_GOAL_KEY,
    SPOT_ELIGIBILITY_ATOMIC_MARKET_SNAPSHOT_V11_GOAL_KEY,
    SPOT_ELIGIBILITY_ATOMIC_MARKET_SNAPSHOT_V12_GOAL_KEY,
    SPOT_ELIGIBILITY_PREVIEW_GATED_GOAL_KEY,
)


AUTOMATION_UNAVAILABLE = "automation_control_plane_unavailable"
AUTOMATION_NOT_FOUND = "automation_resource_not_found"
_SPOT_PREVIEW_MODE_BY_GOAL = {
    SPOT_ELIGIBILITY_PREVIEW_GATED_GOAL_KEY: "PREVIEW_GATED_V2",
    SPOT_ELIGIBILITY_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY: (
        "DOCUMENTED_MARKET_FRESHNESS_V3"
    ),
    SPOT_ELIGIBILITY_NEAR_MARKET_V4_GOAL_KEY: "NEAR_MARKET_POST_ONLY_V4",
    SPOT_ELIGIBILITY_NEAR_MARKET_V5_GOAL_KEY: "NEAR_MARKET_POST_ONLY_V5",
    SPOT_ELIGIBILITY_NEAR_MARKET_V6_GOAL_KEY: "NEAR_MARKET_POST_ONLY_V6",
    SPOT_ELIGIBILITY_MINIMUM_SIZE_V7_GOAL_KEY: "MINIMUM_SIZE_POST_ONLY_V7",
    SPOT_ELIGIBILITY_MINIMUM_SIZE_V8_GOAL_KEY: "MINIMUM_SIZE_POST_ONLY_V8",
    SPOT_ELIGIBILITY_MINIMUM_SIZE_V9_GOAL_KEY: "MINIMUM_SIZE_POST_ONLY_V9",
    SPOT_ELIGIBILITY_ATOMIC_MARKET_SNAPSHOT_V10_GOAL_KEY: (
        "ATOMIC_MARKET_SNAPSHOT_V10"
    ),
    SPOT_ELIGIBILITY_ATOMIC_MARKET_SNAPSHOT_V11_GOAL_KEY: (
        "ATOMIC_MARKET_SNAPSHOT_V11"
    ),
    SPOT_ELIGIBILITY_ATOMIC_MARKET_SNAPSHOT_V12_GOAL_KEY: (
        "ATOMIC_MARKET_SNAPSHOT_V12"
    ),
}
_SPOT_PREVIEW_GOAL_KEYS = frozenset(_SPOT_PREVIEW_MODE_BY_GOAL)
_SPOT_NEAR_MARKET_GOAL_KEYS = frozenset(
    {
        SPOT_ELIGIBILITY_NEAR_MARKET_V4_GOAL_KEY,
        SPOT_ELIGIBILITY_NEAR_MARKET_V5_GOAL_KEY,
        SPOT_ELIGIBILITY_NEAR_MARKET_V6_GOAL_KEY,
    }
)
_SPOT_MINIMUM_SIZE_GOAL_KEYS = frozenset(
    {
        SPOT_ELIGIBILITY_MINIMUM_SIZE_V7_GOAL_KEY,
        SPOT_ELIGIBILITY_MINIMUM_SIZE_V8_GOAL_KEY,
        SPOT_ELIGIBILITY_MINIMUM_SIZE_V9_GOAL_KEY,
    }
)
_SPOT_ATOMIC_MARKET_SNAPSHOT_GOAL_KEYS = frozenset(
    {
        SPOT_ELIGIBILITY_ATOMIC_MARKET_SNAPSHOT_V10_GOAL_KEY,
        SPOT_ELIGIBILITY_ATOMIC_MARKET_SNAPSHOT_V11_GOAL_KEY,
        SPOT_ELIGIBILITY_ATOMIC_MARKET_SNAPSHOT_V12_GOAL_KEY,
    }
)
_SPOT_ATOMIC_MARKET_SNAPSHOT_MODES = frozenset(
    _SPOT_PREVIEW_MODE_BY_GOAL[goal_key]
    for goal_key in _SPOT_ATOMIC_MARKET_SNAPSHOT_GOAL_KEYS
)
_SPOT_DYNAMIC_CAP_GOAL_KEYS = frozenset(
    {*_SPOT_MINIMUM_SIZE_GOAL_KEYS, *_SPOT_ATOMIC_MARKET_SNAPSHOT_GOAL_KEYS}
)


@dataclass(frozen=True)
class AutomationRepositoryPage:
    """One bounded repository page before strict public projection."""

    items: tuple[Mapping[str, Any], ...]
    total_count: int


@dataclass(frozen=True)
class AutomationRepositoryMutation:
    """One authoritative mutation result including replay evidence."""

    entity: Mapping[str, Any]
    audit_id: str
    correlation_id: str
    replayed: bool = False
    activity: AutomationRunMutationActivity | None = None


def _atomic_market_snapshot_read_activity(
    *,
    coinbase_api_call_count: int | None,
    call_count_exact: bool,
) -> AutomationRunMutationActivity:
    """Project request-local atomic eligibility reads without inventing calls."""

    exact_count = (
        coinbase_api_call_count
        if call_count_exact
        and type(coinbase_api_call_count) is int
        and coinbase_api_call_count >= 0
        else None
    )
    if call_count_exact and exact_count is None:
        raise ValueError("automation_atomic_market_snapshot_activity_invalid")
    return AutomationRunMutationActivity(
        operation="PREVIEW_GATED_CREATE",
        coinbase_api_call_count=exact_count,
        preview_call_count=0,
        read_call_count=exact_count,
        exchange_mutation_count=0,
        create_call_count=0,
        cancel_call_count=0,
        call_count_exact=call_count_exact,
    )


@dataclass(frozen=True)
class AutomationEligibilityRepositoryMutation(AutomationRepositoryMutation):
    """One run projection plus current-cycle read accounting."""

    coinbase_api_call_count: int | None = 0
    call_count_exact: bool = True


@dataclass(frozen=True, slots=True)
class SpotAutomationEligibilityExecutionBundle:
    """Request-local eligibility facts retained only until canonical admission."""

    cycle: Any
    snapshot: Any
    attempts: tuple[Any, ...]


class AutomationRepositoryError(RuntimeError):
    """Fixed repository error; implementations must not include private values."""

    def __init__(self, code: str) -> None:
        self.code = str(code)
        super().__init__(self.code)


class AutomationRepositoryConflict(AutomationRepositoryError):
    pass


class AutomationRepositoryNotFound(AutomationRepositoryError):
    pass


class AutomationRepositoryUnavailable(AutomationRepositoryError):
    pass


class OperatorAutomationRepository(Protocol):
    """Semantic persistence boundary; no route or exchange concepts."""

    def get_control_posture(self) -> Mapping[str, Any]: ...

    def list_definitions(
        self,
        *,
        domain: str | None,
        job_kind: str | None,
        lifecycle_state: str | None,
        limit: int,
        offset: int,
    ) -> AutomationRepositoryPage: ...

    def get_definition(self, definition_id: str) -> Mapping[str, Any] | None: ...

    def create_definition(
        self,
        *,
        definition: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation: ...

    def prepare_near_market_candidate(
        self,
        *,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation: ...

    def prepare_minimum_size_candidate(
        self,
        *,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation: ...

    def authorize_atomic_market_snapshot_candidate(
        self,
        *,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation: ...

    def transition_definition(
        self,
        *,
        definition_id: str,
        action: AutomationDefinitionLifecycleAction,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation: ...

    def set_schedule(
        self,
        *,
        definition_id: str,
        schedule: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation: ...

    def clear_schedule(
        self,
        *,
        definition_id: str,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation: ...

    def transition_control_posture(
        self,
        *,
        action: AutomationControlAction,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation: ...

    def claim_one_shot_run(
        self,
        *,
        definition_id: str,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation: ...

    def authorize_single_child(
        self,
        *,
        run_id: str,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation: ...

    def authorize_preview_gated_single_child(
        self,
        *,
        run_id: str,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation: ...

    def safe_closeout_single_child(
        self,
        *,
        run_id: str,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation: ...

    def refresh_spot_eligibility(
        self,
        *,
        run_id: str,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationEligibilityRepositoryMutation: ...

    def list_runs(
        self,
        *,
        definition_id: str | None,
        state: str | None,
        limit: int,
        offset: int,
    ) -> AutomationRepositoryPage: ...

    def get_run(self, run_id: str) -> Mapping[str, Any] | None: ...

    def list_run_events(
        self,
        *,
        run_id: str,
        limit: int,
        offset: int,
    ) -> AutomationRepositoryPage: ...

    def list_definition_events(
        self,
        *,
        definition_id: str,
        limit: int,
        offset: int,
    ) -> AutomationRepositoryPage: ...

    def list_control_events(
        self,
        *,
        limit: int,
        offset: int,
    ) -> AutomationRepositoryPage: ...


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _configured_spot_portfolio_hash() -> str:
    from application.admin_api.spot_portfolio_binding import (
        SPOT_PORTFOLIO_ID_ENV,
    )

    portfolio_id = os.environ.get(SPOT_PORTFOLIO_ID_ENV, "").strip()
    if not portfolio_id:
        raise AutomationRepositoryUnavailable(
            "automation_spot_portfolio_not_configured"
        )
    try:
        parsed = uuid.UUID(portfolio_id)
    except (AttributeError, TypeError, ValueError):
        raise AutomationRepositoryUnavailable(
            "automation_spot_portfolio_invalid"
        ) from None
    if str(parsed) != portfolio_id:
        raise AutomationRepositoryUnavailable(
            "automation_spot_portfolio_invalid"
        )
    return hashlib.sha256(portfolio_id.encode("utf-8")).hexdigest()


def _definition_allowed_actions(
    state: AutomationDefinitionState,
) -> list[str]:
    actions: dict[AutomationDefinitionState, list[str]] = {
        AutomationDefinitionState.DRAFT: [
            "ENABLE",
            "DISABLE",
            "SET_SCHEDULE",
            "CLEAR_SCHEDULE",
        ],
        AutomationDefinitionState.ENABLED: [
            "DISABLE",
            "PAUSE",
            "DRAIN",
            "SET_SCHEDULE",
            "CLEAR_SCHEDULE",
            "RUN_ONCE",
        ],
        AutomationDefinitionState.PAUSED: [
            "DISABLE",
            "RESUME",
            "DRAIN",
            "SET_SCHEDULE",
            "CLEAR_SCHEDULE",
        ],
        AutomationDefinitionState.DRAINING: [
            "DISABLE",
            "RESUME",
            "SET_SCHEDULE",
            "CLEAR_SCHEDULE",
        ],
        AutomationDefinitionState.DISABLED: [
            "ENABLE",
            "SET_SCHEDULE",
            "CLEAR_SCHEDULE",
        ],
    }
    return actions[state]


def _control_allowed_actions(posture: Any) -> list[str]:
    actions = {
        "ACTIVE": ["PAUSE", "DRAIN", "SHUTDOWN"],
        "PAUSED": ["RESUME", "DRAIN", "SHUTDOWN"],
        "DRAINING": ["RESUME", "SHUTDOWN"],
        "SHUTDOWN": ["RESUME"],
    }
    return actions[str(getattr(posture, "value", posture))]


class PostgresOperatorAutomationRepositoryAdapter:
    """Adapt typed store records to the narrow Admin API repository protocol."""

    def __init__(
        self,
        repository: Any,
        *,
        spot_eligibility_reader_factory: Callable[..., Any] | None = None,
        spot_profile_admission_coordinator: Any | None = None,
        spot_execution_eligibility_runner: Callable[..., Any] | None = None,
        spot_command_service: Any | None = None,
        spot_preview_invoker: Callable[..., Any] | None = None,
        spot_execution_scope_factory: Callable[[str], Any] | None = None,
        spot_near_market_preparation_runner: Callable[[], Any] | None = None,
        spot_minimum_size_preparation_runner: Callable[[], Any] | None = None,
        spot_atomic_market_snapshot_runner: Callable[..., Any] | None = None,
        spot_proof_chain_recorder: Callable[..., Mapping[str, Any]] | None = None,
        spot_live_admission_evaluator: Callable[..., Any] | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self._spot_eligibility_reader_factory = spot_eligibility_reader_factory
        self._spot_profile_admission_coordinator = (
            spot_profile_admission_coordinator
        )
        self._spot_execution_eligibility_runner = (
            spot_execution_eligibility_runner
        )
        self._spot_command_service = spot_command_service
        self._spot_preview_invoker = spot_preview_invoker
        self._spot_execution_scope_factory = spot_execution_scope_factory
        self._spot_near_market_preparation_runner = (
            spot_near_market_preparation_runner
        )
        self._spot_minimum_size_preparation_runner = (
            spot_minimum_size_preparation_runner
        )
        self._spot_atomic_market_snapshot_runner = (
            spot_atomic_market_snapshot_runner
        )
        self._spot_proof_chain_recorder = spot_proof_chain_recorder
        self._spot_live_admission_evaluator = spot_live_admission_evaluator
        self._spot_proof_stores: tuple[Any, Any, Any, Any] | None = None
        self._now_factory = now_factory or (
            lambda: datetime.now(timezone.utc)
        )

    @staticmethod
    def _call(operation: Any) -> Any:
        try:
            return operation()
        except Exception as exc:
            from database.operator_automation import (
                AutomationStoreConflict,
                AutomationStoreInvalid,
                AutomationStoreNotFound,
                AutomationStoreUnavailable,
            )

            if isinstance(exc, AutomationStoreConflict):
                raise AutomationRepositoryConflict(exc.code) from None
            if isinstance(exc, AutomationStoreNotFound):
                raise AutomationRepositoryNotFound(exc.code) from None
            if isinstance(
                exc,
                (AutomationStoreInvalid, AutomationStoreUnavailable),
            ):
                raise AutomationRepositoryUnavailable(exc.code) from None
            raise

    def _control_posture_value(self) -> str | None:
        getter = getattr(self.repository, "get_control_posture", None)
        if not callable(getter):
            return None
        record = self._call(getter)
        return str(
            getattr(
                getattr(record, "posture", None),
                "value",
                getattr(record, "posture", None),
            )
        )

    def _control_posture_active(self) -> bool:
        return self._control_posture_value() == "ACTIVE"

    def _require_active_control_posture(self) -> None:
        if not self._control_posture_active():
            raise AutomationRepositoryConflict(
                "automation_control_plane_not_active"
            )

    def _require_safe_closeout_control_posture(self) -> None:
        posture = self._control_posture_value()
        if posture == "SHUTDOWN":
            raise AutomationRepositoryConflict(
                "automation_control_plane_shutdown"
            )
        if posture not in {"ACTIVE", "PAUSED", "DRAINING"}:
            raise AutomationRepositoryConflict(
                "automation_control_plane_not_active"
            )

    @staticmethod
    def _command(
        *,
        context: AutomationMutationContext,
        payload: Mapping[str, Any],
        idempotency_key: str | None = None,
        operator_intent: str | None = None,
    ) -> Any:
        from database.operator_automation import AutomationMutationCommand

        return AutomationMutationCommand(
            idempotency_key=idempotency_key or context.idempotency_key,
            payload_sha256=_payload_sha256(payload),
            actor_id=context.actor_id,
            correlation_id=context.correlation_id,
            operator_intent=operator_intent or context.operator_intent,
        )

    @classmethod
    def _spot_invocation_start_command(
        cls,
        *,
        context: AutomationMutationContext,
        request: Mapping[str, Any],
        run_id: str,
        eligibility_cycle: int,
        plan_sha256: str,
        client_order_id: str,
        command_payload_sha256: str,
        operation: str,
        phase: str,
        operator_intent: str,
    ) -> Any:
        from application.admin_api.operator_spot_automation_runtime import (
            derive_spot_automation_phase_key,
        )

        return cls._command(
            context=context,
            idempotency_key=derive_spot_automation_phase_key(
                outer_idempotency_key=context.idempotency_key,
                run_id=run_id,
                plan_sha256=plan_sha256,
                phase=phase,
            ),
            operator_intent=operator_intent,
            payload={
                "operation": operation,
                "run_id": run_id,
                "eligibility_cycle": eligibility_cycle,
                "plan_sha256": plan_sha256,
                "client_order_id": client_order_id,
                "command_payload_sha256": command_payload_sha256,
                "operator_request_sha256": _payload_sha256(request),
                "actor_roles_sha256": _payload_sha256(
                    {"roles": sorted(set(context.roles))}
                ),
                "outer_operator_intent_sha256": _payload_sha256(
                    {"operator_intent": context.operator_intent}
                ),
            },
        )

    @staticmethod
    def _spot_execution_binding_matches(
        execution: Any,
        *,
        record: Any,
        plan: Any,
        goal_key: str,
        eligibility_cycle: int,
        client_order_id: str,
        require_cancel_allowance: bool = False,
    ) -> bool:
        try:
            expected_policy_revision = (
                5
                if goal_key in _SPOT_ATOMIC_MARKET_SNAPSHOT_GOAL_KEYS
                else 4
                if goal_key
                in {
                    SPOT_ELIGIBILITY_MINIMUM_SIZE_V7_GOAL_KEY,
                    SPOT_ELIGIBILITY_MINIMUM_SIZE_V8_GOAL_KEY,
                    SPOT_ELIGIBILITY_MINIMUM_SIZE_V9_GOAL_KEY,
                }
                else 3
                if goal_key
                in {
                    SPOT_ELIGIBILITY_NEAR_MARKET_V4_GOAL_KEY,
                    SPOT_ELIGIBILITY_NEAR_MARKET_V5_GOAL_KEY,
                    SPOT_ELIGIBILITY_NEAR_MARKET_V6_GOAL_KEY,
                }
                else 2
            )
            return bool(
                execution.run_id == record.run_id
                and execution.policy_revision
                == expected_policy_revision
                and execution.definition_id == record.definition_id
                and execution.definition_revision == record.definition_revision
                and execution.eligibility_cycle == eligibility_cycle
                and execution.plan_sha256 == plan.plan_sha256
                and execution.portfolio_id_sha256 == plan.portfolio_id_sha256
                and execution.product_id == plan.product_id
                and execution.client_order_id == client_order_id
                and execution.create_allowance_consumed
                and (
                    not require_cancel_allowance
                    or execution.cancel_allowance_consumed
                )
            )
        except (AttributeError, TypeError, ValueError):
            return False

    def _resolve_spot_command_service(self) -> Any:
        if self._spot_command_service is None:
            from application.admin_api.command_runtime import (
                build_admin_api_command_service,
            )

            self._spot_command_service = build_admin_api_command_service()
        return self._spot_command_service

    def _invoke_spot_preview(
        self,
        *,
        command_service: Any,
        plan: Any,
    ) -> Any:
        invoker = self._spot_preview_invoker
        if invoker is None:
            dependencies = getattr(command_service, "dependencies", None)
            rest_client = getattr(dependencies, "rest_client", None)
            if not bool(getattr(dependencies, "rest_client_available", False)):
                raise RuntimeError("automation_spot_preview_client_unavailable")
            invoker = getattr(rest_client, "preview_order", None)
        if not callable(invoker):
            raise RuntimeError("automation_spot_preview_client_unavailable")
        return invoker(
            product_id=plan.product_id,
            side=plan.side,
            order_configuration={
                "limit_limit_gtc": {
                    "base_size": plan.base_size,
                    "limit_price": plan.limit_price,
                    "post_only": bool(plan.post_only),
                }
            },
        )

    def _resolve_spot_profile_coordinator(self, command_service: Any) -> Any:
        coordinator = self._spot_profile_admission_coordinator
        service_coordinator = getattr(
            getattr(command_service, "dependencies", None),
            "spot_order_admission_coordinator",
            None,
        )
        if coordinator is None:
            coordinator = service_coordinator
        if coordinator is None or (
            service_coordinator is not None
            and coordinator is not service_coordinator
        ):
            raise AutomationRepositoryUnavailable(
                "automation_spot_profile_coordinator_mismatch"
            )
        return coordinator

    def _resolve_spot_execution_scope_factory(self) -> Callable[[str], Any]:
        if self._spot_execution_scope_factory is None:
            from core.coinbase_execution_authority import (
                canonical_coinbase_execution_scope,
            )

            self._spot_execution_scope_factory = (
                canonical_coinbase_execution_scope
            )
        return self._spot_execution_scope_factory

    def _close_exhausted_preliminary_eligibility(
        self,
        *,
        record: Any,
        cycle_number: int,
        goal_key: str,
        plan_sha256: str,
        context: AutomationMutationContext,
    ) -> Any | None:
        """Durably block a preview successor after its tenth preliminary cycle."""

        if not (
            cycle_number == 10
            and goal_key in _SPOT_PREVIEW_GOAL_KEYS
            and record.state
            is AutomationRunState.AWAITING_OPERATOR_AUTHORIZATION
            and record.diagnostic_code == "awaiting_operator_authorization"
            and not record.live_attempt_consumed
        ):
            return None
        idempotency_key = (
            "automation-internal-eligibility-exhausted-"
            + hashlib.sha256(
                (
                    f"{context.idempotency_key}:{record.run_id}:"
                    f"{plan_sha256}:{cycle_number}"
                ).encode("utf-8")
            ).hexdigest()
        )
        command = self._command(
            context=context,
            idempotency_key=idempotency_key,
            operator_intent=(
                "close_exhausted_preview_preliminary_eligibility"
            ),
            payload={
                "operation": (
                    "close_exhausted_preview_preliminary_eligibility"
                ),
                "run_id": record.run_id,
                "plan_sha256": plan_sha256,
                "cycle_number": cycle_number,
            },
        )
        return self._call(
            lambda: self.repository.transition_run(
                record.run_id,
                AutomationRunState.BLOCKED,
                diagnostic_code="automation_run_blocked",
                command=command,
            )
        )

    def _resolve_spot_proof_stores(self) -> tuple[Any, Any, Any, Any]:
        if self._spot_proof_stores is None:
            from application.admin_api.approval import FileAdminApiApprovalStore
            from application.admin_api.audit import FileAdminApiAuditStore
            from application.admin_api.cap_guard import FileAdminApiCapGuardStore
            from application.admin_api.reconciliation import (
                FileAdminApiReconciliationStore,
            )

            self._spot_proof_stores = (
                FileAdminApiApprovalStore(),
                FileAdminApiAuditStore(),
                FileAdminApiCapGuardStore(),
                FileAdminApiReconciliationStore(),
            )
        return self._spot_proof_stores

    def _record_spot_proof_chain(
        self,
        *,
        proof_context: Mapping[str, Any],
        command_kind: str,
        roles: tuple[str, ...],
        wallet_available_notional_usdc: Decimal,
    ) -> Mapping[str, Any]:
        if self._spot_proof_chain_recorder is not None:
            result = self._spot_proof_chain_recorder(
                proof_context=proof_context,
                command_kind=command_kind,
                roles=roles,
                wallet_available_notional_usdc=(
                    wallet_available_notional_usdc
                ),
            )
        else:
            from application.admin_api.mvp_service import get_admin_mvp_service

            approval, audit, cap, reconciliation = (
                self._resolve_spot_proof_stores()
            )
            result = get_admin_mvp_service().record_typed_spot_command_proof_chain(
                proof_context=proof_context,
                command_kind=command_kind,
                roles=roles,
                wallet_available_notional_usdc=(
                    wallet_available_notional_usdc
                ),
                approval_store=approval,
                audit_store=audit,
                cap_guard_store=cap,
                reconciliation_store=reconciliation,
            )
        if not isinstance(result, Mapping):
            raise AutomationRepositoryUnavailable(
                "automation_spot_proof_chain_invalid"
            )
        return result

    def _evaluate_spot_live_admission(
        self,
        *,
        proof_context: Mapping[str, Any],
        proof_chain: Mapping[str, Any],
    ) -> Any:
        if self._spot_live_admission_evaluator is not None:
            decision = self._spot_live_admission_evaluator(
                proof_context=proof_context,
                proof_chain=proof_chain,
            )
        else:
            from application.admin_api.approval import (
                evaluate_command_live_admission,
            )
            from application.admin_api.live_execution import (
                get_decision_backed_live_execution_service,
            )

            approval, audit, cap, reconciliation = (
                self._resolve_spot_proof_stores()
            )
            decision = evaluate_command_live_admission(
                route=str(proof_context["route"]),
                method=str(proof_context["method"]),
                module_id=str(proof_context["module_id"]),
                identity_key=str(proof_context["identity_key"]),
                identity_value=str(proof_context["identity_value"]),
                action_class=str(proof_context["action_class"]),
                required_permission=str(
                    proof_context["required_permission"]
                ),
                service_method=str(proof_context["service_method"]),
                actor_id=str(proof_context["actor_id"]),
                idempotency_key=str(
                    proof_context["command_idempotency_key"]
                ),
                operator_intent=str(proof_context["operator_intent"]),
                payload_hash=str(proof_context["payload_hash"]),
                approval_store=approval,
                audit_store=audit,
                cap_guard_store=cap,
                reconciliation_store=reconciliation,
                live_execution_service=(
                    get_decision_backed_live_execution_service()
                ),
                cap_guard_product_scope=str(
                    proof_context["product_scope"]
                ),
            )
        approval_record = proof_chain.get("approval")
        audit_record = proof_chain.get("admission_audit")
        cap_record = proof_chain.get("cap_guard")
        reconciliation_record = proof_chain.get("reconciliation_plan")
        exact = bool(
            getattr(decision, "allowed", False) is True
            and getattr(getattr(decision, "status", None), "value", None)
            == "passed"
            and getattr(decision, "live_exchange_submitted", None) is False
            and getattr(
                getattr(decision, "action_class", None),
                "value",
                getattr(decision, "action_class", None),
            )
            == proof_context["action_class"]
            and getattr(
                getattr(decision, "required_permission", None),
                "value",
                getattr(decision, "required_permission", None),
            )
            == proof_context["required_permission"]
            and all(
                getattr(decision, field_name, None)
                == proof_context[context_name]
                for field_name, context_name in (
                    ("route", "route"),
                    ("method", "method"),
                    ("module_id", "module_id"),
                    ("identity_key", "identity_key"),
                    ("identity_value", "identity_value"),
                    ("service_method", "service_method"),
                    ("actor_id", "actor_id"),
                    ("idempotency_key", "command_idempotency_key"),
                    ("operator_intent", "operator_intent"),
                    ("payload_hash", "payload_hash"),
                )
            )
            and isinstance(approval_record, Mapping)
            and isinstance(audit_record, Mapping)
            and isinstance(cap_record, Mapping)
            and isinstance(reconciliation_record, Mapping)
            and getattr(decision, "approval_snapshot_id", None)
            == approval_record.get("approval_id")
            and getattr(decision, "admission_audit_id", None)
            == audit_record.get("audit_id")
            and getattr(decision, "cap_guard_decision_id", None)
            == cap_record.get("decision_id")
            and getattr(decision, "reconciliation_plan_id", None)
            == reconciliation_record.get("plan_id")
        )
        if not exact:
            raise AutomationRepositoryConflict(
                "automation_spot_live_admission_blocked"
            )
        return decision

    @staticmethod
    def _spot_plan_terms(plan: Any, *, goal_key: str) -> Any:
        from application.admin_api.operator_spot_eligibility_reader import (
            SpotEligibilityPlanTerms,
        )

        return SpotEligibilityPlanTerms(
            plan_sha256=plan.plan_sha256,
            product_id=plan.product_id,
            side=plan.side,
            base_size=plan.base_size,
            limit_price=plan.limit_price,
            submitted_notional_usdc=plan.submitted_notional_usdc,
            possible_execution_notional_usdc=(
                plan.possible_execution_notional_usdc
            ),
            max_submitted_notional_usdc=(
                plan.max_submitted_notional_usdc
            ),
            max_possible_execution_notional_usdc=(
                plan.max_possible_execution_notional_usdc
            ),
            post_only=plan.post_only,
            policy_revision=(
                5
                if goal_key in _SPOT_ATOMIC_MARKET_SNAPSHOT_GOAL_KEYS
                else 4
                if goal_key in _SPOT_MINIMUM_SIZE_GOAL_KEYS
                else 3
                if goal_key in _SPOT_NEAR_MARKET_GOAL_KEYS
                else 2
            ),
        )

    def _run_spot_execution_eligibility(
        self,
        *,
        record: Any,
        plan: Any,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
        lease: Any,
    ) -> SpotAutomationEligibilityExecutionBundle:
        if self._spot_execution_eligibility_runner is not None:
            result = self._spot_execution_eligibility_runner(
                record=record,
                plan=plan,
                request=request,
                context=context,
                lease=lease,
            )
            if not isinstance(result, SpotAutomationEligibilityExecutionBundle):
                raise AutomationRepositoryUnavailable(
                    "automation_spot_eligibility_bundle_invalid"
                )
            return result

        from application.admin_api.operator_spot_eligibility import (
            SpotEligibilityCoordinator,
            SpotEligibilityCoordinatorConflict,
            SpotEligibilityRunContext,
        )
        from application.admin_api.operator_spot_eligibility_postgres import (
            PostgresSpotEligibilityLedger,
        )

        run_context = SpotEligibilityRunContext(
            run_id=str(record.run_id),
            definition_id=str(record.definition_id),
            definition_revision=int(record.definition_revision),
            plan_sha256=plan.plan_sha256,
            portfolio_id_sha256=plan.portfolio_id_sha256,
            correlation_id=context.correlation_id,
            goal_key=self._call(
                lambda: self.repository.get_spot_goal_key_for_run(
                    record.run_id
                )
            ),
        )
        reader_holder: list[Any] = []

        def build_reader() -> Any:
            if self._spot_eligibility_reader_factory is None or reader_holder:
                raise RuntimeError(
                    "automation_spot_eligibility_reader_unavailable"
                )
            reader = self._spot_eligibility_reader_factory(
                expected_context=run_context,
                plan=self._spot_plan_terms(plan, goal_key=run_context.goal_key),
            )
            reader_holder.append(reader)
            return reader

        ledger = PostgresSpotEligibilityLedger(
            repository=self.repository,
            mutation_context=context,
            request_payload=request,
            authorization_cycle=True,
        )
        try:
            cycle = self._call(
                lambda: SpotEligibilityCoordinator(
                    ledger=ledger,
                    reader_factory=build_reader,
                ).run(run_context)
            )
        except SpotEligibilityCoordinatorConflict as exc:
            raise AutomationRepositoryConflict(exc.code) from None
        if cycle.replayed or len(reader_holder) != 1:
            raise AutomationRepositoryConflict(
                "automation_spot_fresh_eligibility_required"
            )
        snapshot = reader_holder[0].execution_snapshot()
        attempts = self._call(
            lambda: self.repository.list_spot_eligibility_attempts(
                record.run_id,
                cycle_number=cycle.cycle_number,
            )
        )
        return SpotAutomationEligibilityExecutionBundle(
            cycle=cycle,
            snapshot=snapshot,
            attempts=tuple(attempts),
        )

    @staticmethod
    def _activity_from_classification(
        classification: Any,
        *,
        operation: str,
    ) -> AutomationRunMutationActivity:
        mutation_count = classification.mutation_call_count
        read_count = classification.read_call_count
        exact = bool(
            classification.mutation_call_count_exact
            and classification.read_call_count_exact
        )
        total = (
            mutation_count + read_count
            if exact
            and mutation_count is not None
            and read_count is not None
            else None
        )
        return AutomationRunMutationActivity(
            operation=operation,
            coinbase_api_call_count=total,
            read_call_count=(
                read_count
                if classification.read_call_count_exact
                else None
            ),
            exchange_mutation_count=(
                mutation_count
                if classification.mutation_call_count_exact
                else None
            ),
            create_call_count=(
                mutation_count
                if operation == "CREATE"
                and classification.mutation_call_count_exact
                else (0 if operation != "CREATE" else None)
            ),
            cancel_call_count=(
                mutation_count
                if operation == "SAFE_CLOSEOUT"
                and classification.mutation_call_count_exact
                else (0 if operation != "SAFE_CLOSEOUT" else None)
            ),
            call_count_exact=exact,
        )

    @staticmethod
    def _control(
        record: Any,
        *,
        atomic_market_snapshot_authorization_allowed: bool = False,
    ) -> Mapping[str, Any]:
        posture = str(getattr(record.posture, "value", record.posture))
        return {
            "posture": posture,
            "local_admission_enabled": posture == "ACTIVE",
            "recurring_worker_started": False,
            "live_scheduler_enabled": False,
            "coinbase_api_call_count": 0,
            "exchange_mutation_count": 0,
            "definition_create_allowed": False,
            "near_market_candidate_preparation_allowed": False,
            "minimum_size_candidate_preparation_allowed": False,
            "atomic_market_snapshot_authorization_allowed": (
                atomic_market_snapshot_authorization_allowed
            ),
            "allowed_actions": _control_allowed_actions(record.posture),
            "updated_at": record.updated_at,
        }

    def _definition(
        self,
        record: Any,
        plan: Any | None = None,
        *,
        spot_goal_run_claimed: bool = False,
        spot_goal_key: str | None = None,
        minimum_size_preparation: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        state = AutomationDefinitionState(
            str(getattr(record.lifecycle_state, "value", record.lifecycle_state))
        )
        schedule_mode = str(
            getattr(record.schedule_kind, "value", record.schedule_kind)
        )
        interval_seconds = record.interval_seconds
        interval_minutes = None
        if interval_seconds is not None:
            if interval_seconds % 60 != 0:
                raise ValueError("automation_schedule_interval_invalid")
            interval_minutes = interval_seconds // 60
        allowed_actions = _definition_allowed_actions(state)
        if record.due_reason == "control_plane_not_active":
            allowed_actions = [
                action for action in allowed_actions if action != "RUN_ONCE"
            ]
        if plan is not None and spot_goal_run_claimed:
            allowed_actions = [
                action for action in allowed_actions if action != "RUN_ONCE"
            ]
        single_child_order = None
        if plan is not None:
            single_child_order = {
                "side": plan.side,
                "base_size": plan.base_size,
                "limit_price": plan.limit_price,
                "order_type": "LIMIT",
                "time_in_force": "GOOD_UNTIL_CANCELLED",
                "post_only": plan.post_only,
            }
        return {
            "definition_id": record.definition_id,
            "revision": record.revision,
            "display_name": record.label,
            "domain": str(getattr(record.domain, "value", record.domain)),
            "job_kind": str(getattr(record.job_kind, "value", record.job_kind)),
            "lifecycle_state": state.value,
            "product_ids": list(record.product_ids),
            "spot_execution_mode": (
                _SPOT_PREVIEW_MODE_BY_GOAL.get(spot_goal_key)
                if plan is not None and spot_goal_key in _SPOT_PREVIEW_GOAL_KEYS
                else "CREATE_ONLY_V1"
                if plan is not None
                else None
            ),
            "single_child_order": single_child_order,
            "minimum_size_preparation": minimum_size_preparation,
            "schedule": {
                "mode": schedule_mode,
                "interval_minutes": interval_minutes,
                "next_review_at": record.next_review_at,
                "due": record.schedule_due,
            },
            "adapter_status": (
                "UNAVAILABLE"
                if plan is None
                else "SOURCE_GATED"
            ),
            "live_execution_available": False,
            "allowed_actions": allowed_actions,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    def _run(
        self,
        record: Any,
        *,
        eligibility_cycle_number: int | None = None,
    ) -> Mapping[str, Any]:
        plan = None
        attempts: tuple[Any, ...] = ()
        cycles: tuple[Any, ...] = ()
        execution = None
        spot_goal_key: str | None = None
        preview_goal = None
        eligibility_lifetime_call_count: int | None = 0
        eligibility_lifetime_call_count_exact = True
        if (
            str(getattr(record.job_kind, "value", record.job_kind))
            == AutomationJobKind.SPOT_CAMPAIGN.value
            and record.definition_revision is not None
        ):
            plan = self._call(
                lambda: self.repository.get_spot_single_child_plan(
                    record.definition_id,
                    record.definition_revision,
                )
            )
            spot_goal_key = self._call(
                lambda: self.repository.get_spot_goal_key_for_run(
                    record.run_id
                )
            )
            attempts = self._call(
                lambda: self.repository.list_spot_eligibility_attempts(
                    record.run_id,
                    cycle_number=None,
                )
            )
            cycles = self._call(
                lambda: self.repository.list_spot_eligibility_cycles(
                    goal_key=spot_goal_key
                )
            )
            execution = self._call(
                lambda: self.repository.get_spot_run_execution(record.run_id)
            )
            if spot_goal_key in _SPOT_PREVIEW_GOAL_KEYS:
                preview_goal = self._call(
                    lambda: self.repository.get_spot_preview_gated_goal(
                        goal_key=spot_goal_key,
                    )
                )
            eligibility_lifetime_call_count_exact = all(
                attempt.call_count_exact for attempt in attempts
            )
            eligibility_lifetime_call_count = (
                sum(
                    int(attempt.coinbase_api_call_count or 0)
                    for attempt in attempts
                )
                if eligibility_lifetime_call_count_exact
                else None
            )
        control_posture = (
            self._control_posture_value() if plan is not None else None
        )
        control_posture_active = control_posture == "ACTIVE"
        control_posture_allows_safe_closeout = control_posture in {
            "ACTIVE",
            "PAUSED",
            "DRAINING",
        }

        run_cycles = tuple(
            cycle
            for cycle in cycles
            if str(getattr(cycle, "run_id", "")) == str(record.run_id)
        )
        if eligibility_cycle_number is None:
            latest_cycle_record = max(
                run_cycles,
                key=lambda cycle: int(cycle.cycle_number),
                default=None,
            )
        else:
            if (
                type(eligibility_cycle_number) is not int
                or not 1 <= eligibility_cycle_number <= 10
            ):
                raise AutomationRepositoryUnavailable(
                    "automation_spot_eligibility_projection_cycle_invalid"
                )
            cycle_matches = tuple(
                cycle
                for cycle in run_cycles
                if int(cycle.cycle_number) == eligibility_cycle_number
            )
            if len(cycle_matches) != 1:
                raise AutomationRepositoryUnavailable(
                    "automation_spot_eligibility_projection_cycle_invalid"
                )
            latest_cycle_record = cycle_matches[0]
        latest_cycle = (
            int(latest_cycle_record.cycle_number)
            if latest_cycle_record is not None
            else None
        )
        current_attempts = tuple(
            attempt
            for attempt in attempts
            if attempt.cycle_number == latest_cycle
        )
        now = datetime.now(timezone.utc)

        def fresh_deadline(value: Any) -> datetime | None:
            if value is None:
                return None
            if isinstance(value, datetime):
                parsed = value
            elif isinstance(value, str):
                try:
                    parsed = datetime.fromisoformat(
                        value.replace("Z", "+00:00")
                    )
                except ValueError:
                    return None
            else:
                return None
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                return None
            return parsed.astimezone(timezone.utc)

        cycle_fresh_until = (
            fresh_deadline(latest_cycle_record.fresh_until)
            if latest_cycle_record is not None
            else None
        )
        current_cycle_fresh = bool(
            latest_cycle_record is not None
            and latest_cycle_record.state == "SUCCEEDED"
            and cycle_fresh_until is not None
            and now < cycle_fresh_until
        )
        plan_readback = None
        if plan is not None:
            portfolio_catalog_proven = any(
                attempt.category == "PORTFOLIO_CATALOG"
                and attempt.allowance_consumed
                and attempt.outcome == "SUCCEEDED"
                and attempt.eligible is True
                and attempt.call_count_exact
                and attempt.coinbase_api_call_count is not None
                and attempt.portfolio_id_sha256
                == plan.portfolio_id_sha256
                and (
                    fresh_deadline(attempt.fresh_until) is not None
                    and now < fresh_deadline(attempt.fresh_until)
                )
                for attempt in current_attempts
            )
            plan_readback = {
                "plan_sha256": plan.plan_sha256,
                "portfolio_scope": (
                    "Test"
                    if portfolio_catalog_proven
                    else "CONFIGURED_UNVERIFIED"
                ),
                "product_id": plan.product_id,
                "side": plan.side,
                "base_size": plan.base_size,
                "limit_price": plan.limit_price,
                "order_type": "LIMIT",
                "time_in_force": "GOOD_UNTIL_CANCELLED",
                "post_only": plan.post_only,
                "submitted_notional_usdc": plan.submitted_notional_usdc,
                "possible_execution_notional_usdc": (
                    plan.possible_execution_notional_usdc
                ),
                "max_submitted_notional_usdc": "3.10",
                "max_possible_execution_notional_usdc": (
                    plan.max_possible_execution_notional_usdc
                    if spot_goal_key in _SPOT_DYNAMIC_CAP_GOAL_KEYS
                    else "1.00"
                ),
            }

        eligibility = None
        if plan is not None:
            from database.operator_automation import (
                AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES,
            )

            public_category = {
                "API_KEY_PERMISSIONS": "api_key_permissions",
                "PORTFOLIO_CATALOG": "portfolio_catalog",
                "ACCOUNT_WALLET_BALANCES": "wallet_balances",
                "PRODUCT_METADATA": "product_metadata",
                "BEST_BID_ASK": "best_bid_ask",
                "FEE_SUMMARY": "fee_summary",
                "EXACT_ORDER_RECONCILIATION": "exact_order_reconciliation",
                "ACCOUNT_ACTIVE_SPOT_ORDER_CATALOG": "active_order_catalog",
            }

            successful_categories = {
                attempt.category
                for attempt in current_attempts
                if attempt.outcome == "SUCCEEDED"
                and attempt.eligible is True
                and attempt.allowance_consumed
                and (
                    attempt.category != "PORTFOLIO_CATALOG"
                    or attempt.portfolio_id_sha256
                    == plan.portfolio_id_sha256
                )
            }
            completed = [
                public_category[category]
                for category in AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES
                if category in successful_categories
            ]
            call_count_exact = bool(
                latest_cycle_record is None
                or latest_cycle_record.call_count_exact
            )
            call_count = (
                int(latest_cycle_record.coinbase_api_call_count)
                if latest_cycle_record is not None
                and latest_cycle_record.coinbase_api_call_count is not None
                and call_count_exact
                else (0 if latest_cycle_record is None else None)
            )
            eligible = bool(
                current_attempts
                and successful_categories
                == set(AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES)
                and current_cycle_fresh
            )
            if eligible:
                eligibility_blocker = None
            elif latest_cycle_record is None:
                eligibility_blocker = record.diagnostic_code
            elif latest_cycle_record.state == "OPEN":
                eligibility_blocker = (
                    "automation_spot_eligibility_cycle_in_progress"
                )
            elif (
                latest_cycle_record.state == "SUCCEEDED"
                and not current_cycle_fresh
            ):
                eligibility_blocker = "automation_spot_eligibility_stale"
            else:
                eligibility_blocker = latest_cycle_record.diagnostic_code
            eligibility = {
                "cycle_number": latest_cycle,
                "required_categories": list(
                    public_category[category]
                    for category in AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES
                ),
                "completed_categories": completed,
                "eligible": eligible,
                "blocker_code": eligibility_blocker,
                "coinbase_api_call_count": call_count,
                "call_count_exact": call_count_exact,
            }

        state_value = str(getattr(record.state, "value", record.state))
        adapter_status = {
            AutomationRunState.PREPARING.value: "PREPARING",
            AutomationRunState.AWAITING_OPERATOR_AUTHORIZATION.value: (
                "AWAITING_OPERATOR_AUTHORIZATION"
            ),
            AutomationRunState.BLOCKED.value: "BLOCKED",
            AutomationRunState.INVOCATION_STARTED.value: "INVOCATION_STARTED",
            AutomationRunState.ACTIVE.value: "ACTIVE",
            AutomationRunState.TERMINAL.value: "TERMINAL",
            AutomationRunState.UNKNOWN_CONSUMED.value: "UNKNOWN_CONSUMED",
        }.get(
            state_value,
            "SOURCE_GATED" if plan is not None else "UNAVAILABLE",
        )
        if plan is None:
            adapter_status = "UNAVAILABLE"
        preview_allowance_consumed = bool(
            preview_goal is not None
            and preview_goal.preview_allowance_consumed
        )
        preview_outcome = (
            preview_goal.preview_outcome if preview_goal is not None else None
        )
        preview_failure_class = (
            preview_goal.preview_failure_class
            if preview_goal is not None
            else None
        )
        preview_rejection_code = (
            preview_goal.preview_rejection_code
            if preview_goal is not None
            else None
        )
        preview_warning_present = (
            preview_goal.preview_warning_present
            if preview_goal is not None
            else None
        )
        preview_identity_retention = (
            "HASHED"
            if preview_goal is not None
            and preview_goal.preview_id_sha256 is not None
            else "WITHHELD"
            if preview_outcome == "ACCEPTED"
            else "UNAVAILABLE"
        )
        preview_call_count: int | None = (
            preview_goal.preview_call_count
            if preview_allowance_consumed
            else 0
        )
        preview_call_count_exact = bool(
            preview_goal is None
            or not preview_allowance_consumed
            or preview_goal.preview_call_count_exact
        )
        goal_latest_cycle = max(
            (int(cycle.cycle_number) for cycle in cycles),
            default=0,
        )
        eligibility_cycles_exhausted = bool(
            goal_latest_cycle >= 10
            and spot_goal_key in _SPOT_PREVIEW_GOAL_KEYS
            and record.state is AutomationRunState.BLOCKED
            and record.diagnostic_code
            == "automation_spot_eligibility_refresh_required"
            and execution is None
            and not record.live_attempt_consumed
            and not preview_allowance_consumed
        )
        effective_diagnostic_code = (
            "automation_spot_eligibility_cycles_exhausted"
            if eligibility_cycles_exhausted
            else record.diagnostic_code
        )
        if eligibility_cycles_exhausted and eligibility is not None:
            eligibility["blocker_code"] = effective_diagnostic_code
        call_count_exact = bool(
            eligibility_lifetime_call_count_exact
            and preview_call_count_exact
        )
        coinbase_api_call_count: int | None = (
            int(eligibility_lifetime_call_count or 0)
            + int(preview_call_count or 0)
            if plan is not None
            and call_count_exact
            and eligibility_lifetime_call_count is not None
            and preview_call_count is not None
            else record.coinbase_api_call_count
            if plan is None
            else None
        )
        create_call_count: int | None = record.create_call_count
        cancel_call_count: int | None = record.cancel_call_count
        reconciliation_call_count: int | None = 0
        child_terminal = None
        client_order_id = record.client_order_id
        if execution is not None:
            create_call_count = execution.create_call_count
            cancel_call_count = (
                execution.cancel_call_count
                if execution.cancel_allowance_consumed
                else 0
            )
            cancel_call_count_exact = (
                execution.cancel_call_count_exact
                if execution.cancel_allowance_consumed
                else True
            )
            create_read_call_count_exact = bool(
                execution.create_read_call_count_exact
            )
            cancel_read_call_count_exact = (
                bool(execution.cancel_read_call_count_exact)
                if execution.cancel_allowance_consumed
                else True
            )
            call_count_exact = bool(
                eligibility_lifetime_call_count_exact
                and eligibility_lifetime_call_count is not None
                and preview_call_count_exact
                and preview_call_count is not None
                and execution.create_call_count_exact
                and cancel_call_count_exact
                and create_read_call_count_exact
                and cancel_read_call_count_exact
            )
            reconciliation_call_count = (
                int(execution.create_read_call_count or 0)
                + int(execution.cancel_read_call_count or 0)
                if create_read_call_count_exact
                and cancel_read_call_count_exact
                else None
            )
            coinbase_api_call_count = (
                int(eligibility_lifetime_call_count or 0)
                + int(preview_call_count or 0)
                + int(execution.create_call_count or 0)
                + int(execution.cancel_call_count or 0)
                + int(reconciliation_call_count or 0)
                if call_count_exact
                else None
            )
            child_terminal = execution.child_terminal
            client_order_id = execution.client_order_id
        elif (
            record.state is AutomationRunState.UNKNOWN_CONSUMED
            and execution is None
            and preview_goal is None
        ):
            call_count_exact = False
            coinbase_api_call_count = None
            create_call_count = None
            cancel_call_count = 0
            reconciliation_call_count = None

        preliminary_authorization_available = bool(
            eligibility is not None
            and (
                eligibility["eligible"] is True
                or (
                    eligibility["eligible"] is False
                    and eligibility["blocker_code"]
                    == "automation_spot_eligibility_stale"
                    and eligibility["call_count_exact"] is True
                    and eligibility["cycle_number"] is not None
                    and eligibility["completed_categories"]
                    == eligibility["required_categories"]
                    and latest_cycle_record is not None
                    and latest_cycle_record.state == "SUCCEEDED"
                )
            )
        )
        preview_gated = preview_goal is not None
        authorization_checkpoint_ready = bool(
            (
                not preview_gated
                and record.diagnostic_code == "awaiting_operator_authorization"
                and not record.live_attempt_consumed
            )
            or (
                preview_gated
                and (
                    (
                        not preview_allowance_consumed
                        and record.diagnostic_code
                        == "awaiting_operator_authorization"
                        and not record.live_attempt_consumed
                    )
                    or (
                        preview_outcome == "ACCEPTED"
                        and record.diagnostic_code
                        == "automation_spot_preview_accepted_create_ready"
                        and record.live_attempt_consumed
                    )
                )
            )
        )
        authorize_execution_available = bool(
            control_posture_active
            and plan is not None
            and execution is None
            and record.state
            is AutomationRunState.AWAITING_OPERATOR_AUTHORIZATION
            and authorization_checkpoint_ready
            and eligibility is not None
            and preliminary_authorization_available
        )
        safe_closeout_execution_available = bool(
            control_posture_allows_safe_closeout
            and plan is not None
            and execution is not None
            and record.state is AutomationRunState.ACTIVE
            and record.diagnostic_code
            == "automation_spot_safe_closeout_ready"
            and execution.create_allowance_consumed
            and not execution.cancel_allowance_consumed
            and execution.create_read_call_count_exact
            and execution.create_read_call_count is not None
            and execution.create_read_call_count >= 1
            and execution.child_terminal is False
        )
        live_execution_available = bool(
            authorize_execution_available
            or safe_closeout_execution_available
        )
        refresh_available = bool(
            control_posture_active
            and plan is not None
            and record.state is AutomationRunState.BLOCKED
            and record.diagnostic_code
            in {
                "automation_active_order_catalog_read_not_authorized",
                "automation_spot_eligibility_refresh_required",
                "restart_pre_invocation_blocked",
            }
            and execution is None
            and not record.live_attempt_consumed
            and not preview_allowance_consumed
            and goal_latest_cycle < 10
            and not any(cycle.state == "OPEN" for cycle in cycles)
        )

        return {
            "run_id": record.run_id,
            "definition_id": record.definition_id,
            "domain": str(getattr(record.domain, "value", record.domain)),
            "job_kind": str(getattr(record.job_kind, "value", record.job_kind)),
            "trigger": "ONE_SHOT",
            "state": state_value,
            "diagnostic_code": effective_diagnostic_code,
            "adapter_status": adapter_status,
            "live_execution_available": live_execution_available,
            "live_attempt_consumed": record.live_attempt_consumed,
            "spot_execution_mode": (
                _SPOT_PREVIEW_MODE_BY_GOAL.get(spot_goal_key)
                if preview_goal is not None
                else "CREATE_ONLY_V1"
                if plan is not None
                else None
            ),
            "preview_allowance_consumed": preview_allowance_consumed,
            "preview_outcome": preview_outcome,
            "preview_failure_class": preview_failure_class,
            "preview_rejection_code": preview_rejection_code,
            "preview_warning_present": preview_warning_present,
            "preview_identity_retention": preview_identity_retention,
            "preview_call_count": preview_call_count,
            "coinbase_api_call_count": coinbase_api_call_count,
            "create_call_count": create_call_count,
            "cancel_call_count": cancel_call_count,
            "call_count_exact": call_count_exact,
            "client_order_id": client_order_id,
            "reconciliation_call_count": reconciliation_call_count,
            "create_allowance_consumed": bool(
                preview_goal.create_allowance_consumed
                if preview_goal is not None
                else execution is not None
                and execution.create_allowance_consumed
            ),
            "cancel_allowance_consumed": bool(
                preview_goal.cancel_allowance_consumed
                if preview_goal is not None
                else execution is not None
                and execution.cancel_allowance_consumed
            ),
            "child_terminal": child_terminal,
            "single_child_plan": plan_readback,
            "eligibility": eligibility,
            "allowed_actions": (
                ["SAFE_CLOSEOUT_CHILD"]
                if safe_closeout_execution_available
                else [
                    "AUTHORIZE_PREVIEW_GATED_SINGLE_CHILD"
                    if preview_gated
                    else "AUTHORIZE_SINGLE_CHILD"
                ]
                if authorize_execution_available
                else (["REFRESH_ELIGIBILITY"] if refresh_available else [])
            ),
            "audit_id": record.audit_id,
            "correlation_id": record.correlation_id,
            "claimed_at": record.claimed_at,
            "updated_at": record.updated_at,
        }

    @staticmethod
    def _event(record: Any) -> Mapping[str, Any]:
        return {
            "event_id": record.event_id,
            "run_id": record.run_id,
            "sequence": record.sequence,
            "from_state": (
                str(getattr(record.from_state, "value", record.from_state))
                if record.from_state is not None
                else None
            ),
            "state": str(getattr(record.to_state, "value", record.to_state)),
            "diagnostic_code": record.diagnostic_code,
            "audit_id": record.audit_id,
            "correlation_id": record.correlation_id,
            "recorded_at": record.recorded_at,
        }

    @staticmethod
    def _lifecycle_event(record: Any) -> Mapping[str, Any]:
        event = {
            "event_id": record.event_id,
            "from_state": record.from_state,
            "to_state": record.to_state,
            "diagnostic_code": record.diagnostic_code,
            "audit_id": record.audit_id,
            "correlation_id": record.correlation_id,
            "recorded_at": record.recorded_at,
        }
        if record.definition_id is not None:
            event["definition_id"] = record.definition_id
        return event

    @staticmethod
    def _mutation(result: Any, projector: Any) -> AutomationRepositoryMutation:
        return AutomationRepositoryMutation(
            entity=projector(result.entity),
            audit_id=result.audit_id,
            correlation_id=result.correlation_id,
            replayed=result.replayed,
        )

    def _spot_plan_for_record(self, record: Any) -> Any | None:
        """Read the exact plan revision already committed with the definition."""

        if record.job_kind is not AutomationJobKind.SPOT_CAMPAIGN:
            return None
        return self._call(
            lambda: self.repository.get_spot_single_child_plan(
                record.definition_id,
                record.revision,
            )
        )

    def _definition_with_plan(
        self,
        record: Any,
    ) -> Mapping[str, Any]:
        plan = None
        if record.job_kind is AutomationJobKind.SPOT_CAMPAIGN:
            plan = self._call(
                lambda: self.repository.get_spot_single_child_plan(
                    record.definition_id,
                    record.revision,
                )
            )
        spot_goal_key = None
        spot_goal_run_claimed = False
        if plan is not None:
            spot_goal_key = self._call(
                lambda: self.repository.get_spot_goal_key_for_definition(
                    record.definition_id
                )
            )
            spot_goal_run_claimed = self._call(
                lambda: self.repository.has_spot_single_child_run(
                    goal_key=spot_goal_key
                )
            )
        minimum_size_preparation = None
        if plan is not None and spot_goal_key in _SPOT_MINIMUM_SIZE_GOAL_KEYS:
            preparations = self._call(
                lambda: self.repository.list_spot_minimum_size_preparations()
            )
            preparation = next(
                (
                    item
                    for item in preparations
                    if item.definition_id == record.definition_id
                    and item.state == "MATERIALIZED"
                ),
                None,
            )
            if preparation is None:
                raise AutomationRepositoryUnavailable(
                    "automation_minimum_size_preparation_readback_unavailable"
                )
            minimum_size_preparation = {
                "policy_revision": (
                    "BTC_USDC_POST_ONLY_BEST_BID_MINIMUM_SIZE_V2"
                ),
                "boundary_classification": preparation.diagnostic_code,
                "cycle_number": preparation.cycle_number,
                "completed_categories": [
                    self._near_market_public_category(category)
                    for category in preparation.completed_categories
                ],
                "coinbase_api_call_count": (
                    preparation.coinbase_api_call_count
                ),
                "call_count_exact": preparation.call_count_exact,
                "max_submitted_notional_usdc": (
                    "3.10"
                ),
                "max_possible_execution_notional_usdc": (
                    plan.max_possible_execution_notional_usdc
                ),
            }
        return self._definition(
            record,
            plan,
            spot_goal_run_claimed=spot_goal_run_claimed,
            spot_goal_key=spot_goal_key,
            minimum_size_preparation=minimum_size_preparation,
        )

    def get_control_posture(self) -> Mapping[str, Any]:
        record = self._call(self.repository.get_control_posture)
        availability_reader = getattr(
            self.repository,
            "spot_atomic_market_snapshot_successor_available",
            None,
        )
        atomic_available = (
            bool(self._call(availability_reader))
            if callable(availability_reader)
            else False
        )
        return self._control(
            record,
            atomic_market_snapshot_authorization_allowed=atomic_available,
        )

    def list_definitions(
        self,
        *,
        domain: str | None,
        job_kind: str | None,
        lifecycle_state: str | None,
        limit: int,
        offset: int,
    ) -> AutomationRepositoryPage:
        page = self._call(
            lambda: self.repository.list_definitions(
                domain=AutomationDomain(domain) if domain is not None else None,
                job_kind=(
                    AutomationJobKind(job_kind) if job_kind is not None else None
                ),
                lifecycle_state=(
                    AutomationDefinitionState(lifecycle_state)
                    if lifecycle_state is not None
                    else None
                ),
                limit=limit,
                offset=offset,
            )
        )
        return AutomationRepositoryPage(
            items=tuple(
                self._definition_with_plan(item)
                for item in page.items
            ),
            total_count=page.total_count,
        )

    def get_definition(self, definition_id: str) -> Mapping[str, Any] | None:
        record = self._call(lambda: self.repository.get_definition(definition_id))
        if record is None:
            return None
        return self._definition_with_plan(record)

    @staticmethod
    def _near_market_public_category(category: str) -> str:
        return {
            "API_KEY_PERMISSIONS": "api_key_permissions",
            "PORTFOLIO_CATALOG": "portfolio_catalog",
            "ACCOUNT_WALLET_BALANCES": "wallet_balances",
            "PRODUCT_METADATA": "product_metadata",
            "BEST_BID_ASK": "best_bid_ask",
            "FEE_SUMMARY": "fee_summary",
        }[category]

    def _near_market_preparation_entity(self, record: Any) -> Mapping[str, Any]:
        definition = None
        if record.definition_id is not None:
            definition_record = self._call(
                lambda: self.repository.get_definition(record.definition_id)
            )
            if definition_record is None:
                raise AutomationRepositoryUnavailable(
                    "automation_near_market_definition_unavailable"
                )
            definition = self._definition_with_plan(definition_record)
        mode = _SPOT_PREVIEW_MODE_BY_GOAL.get(record.goal_key)
        if mode is None:
            raise AutomationRepositoryUnavailable(
                "automation_near_market_goal_binding_invalid"
            )
        return {
            "outcome": record.state,
            "candidate_version": record.candidate_version,
            "spot_execution_mode": mode,
            "cycle_number": record.cycle_number,
            "policy_revision": "BTC_USDC_POST_ONLY_BEST_BID_V1",
            "diagnostic_code": record.diagnostic_code,
            "completed_categories": [
                self._near_market_public_category(category)
                for category in record.completed_categories
            ],
            "coinbase_api_call_count": record.coinbase_api_call_count,
            "call_count_exact": record.call_count_exact,
            "definition": definition,
            "preview_call_count": 0,
            "create_call_count": 0,
            "cancel_call_count": 0,
        }

    def prepare_near_market_candidate(
        self,
        *,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation:
        """Claim one read cycle and atomically materialize backend-owned terms."""

        from database.operator_automation import (
            AutomationDefinitionCreateCommand,
            AutomationSpotNearMarketMaterializationEvidence,
            AutomationSpotSingleChildPlanTerms,
        )
        from application.admin_api.operator_spot_near_market_preparation import (
            NearMarketPreparationOutcome,
        )

        self._require_active_control_posture()
        claim_command = self._command(
            context=context,
            payload={
                "operation": "prepare_near_market_candidate",
                "request": request,
            },
        )
        claim = self._call(
            lambda: self.repository.start_spot_near_market_preparation(
                claim_command
            )
        )
        claimed = claim.entity
        if claim.replayed:
            if claimed.state == "CLAIMED":
                raise AutomationRepositoryConflict(
                    "automation_near_market_preparation_in_progress"
                )
            return AutomationRepositoryMutation(
                entity=self._near_market_preparation_entity(claimed),
                audit_id=claim.audit_id,
                correlation_id=claim.correlation_id,
                replayed=True,
            )

        runner = self._spot_near_market_preparation_runner
        if not callable(runner):
            result = None
        else:
            try:
                result = runner()
            except Exception:
                result = None
        if result is None:
            finalized = self._call(
                lambda: self.repository.finalize_spot_near_market_preparation(
                    cycle_number=claimed.cycle_number,
                    goal_key=claimed.goal_key,
                    state="UNKNOWN",
                    diagnostic_code=(
                        "automation_near_market_preparation_unknown"
                    ),
                    completed_categories=(),
                    coinbase_api_call_count=None,
                    call_count_exact=False,
                    evidence_sha256=None,
                    definition_id=None,
                )
            )
        elif result.outcome is NearMarketPreparationOutcome.MATERIALIZED:
            plan = result.plan
            if (
                plan is None
                or result.evidence_sha256 is None
                or result.coinbase_api_call_count is None
                or not result.call_count_exact
            ):
                raise AutomationRepositoryUnavailable(
                    "automation_near_market_preparation_result_invalid"
                )
            definition_command = AutomationDefinitionCreateCommand(
                **self._command(
                    context=context,
                    idempotency_key="near-market-definition:"
                    + hashlib.sha256(
                        json.dumps(
                            {
                                "actor_id": context.actor_id,
                                "cycle_number": claimed.cycle_number,
                                "goal_key": claimed.goal_key,
                                "source_idempotency_key": (
                                    context.idempotency_key
                                ),
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=True,
                        ).encode("utf-8")
                    ).hexdigest(),
                    operator_intent="materialize_near_market_candidate",
                    payload={
                        "operation": "materialize_near_market_candidate",
                        "candidate_version": claimed.candidate_version,
                        "cycle_number": claimed.cycle_number,
                        "goal_key": claimed.goal_key,
                        "policy_revision": plan.policy_revision,
                        "plan": {
                            "product_id": plan.product_id,
                            "side": plan.side,
                            "base_size": plan.base_size,
                            "limit_price": plan.limit_price,
                            "submitted_notional_usdc": (
                                plan.submitted_notional_usdc
                            ),
                            "possible_execution_notional_usdc": (
                                plan.possible_execution_notional_usdc
                            ),
                            "post_only": plan.post_only,
                        },
                    },
                ).__dict__,
                domain=AutomationDomain.SPOT,
                job_kind=AutomationJobKind.SPOT_CAMPAIGN,
                label=(
                    "BTC-USDC near-market successor "
                    f"V{claimed.candidate_version}"
                ),
                product_ids=("BTC-USDC",),
            )
            terms = AutomationSpotSingleChildPlanTerms(
                portfolio_id_sha256=_configured_spot_portfolio_hash(),
                product_id=plan.product_id,
                side=plan.side,
                base_size=plan.base_size,
                limit_price=plan.limit_price,
                submitted_notional_usdc=plan.submitted_notional_usdc,
                possible_execution_notional_usdc=(
                    plan.possible_execution_notional_usdc
                ),
                max_submitted_notional_usdc=(
                    plan.max_submitted_notional_usdc
                ),
                max_possible_execution_notional_usdc=(
                    plan.max_possible_execution_notional_usdc
                ),
                post_only=True,
            )
            try:
                created = self._call(
                    lambda: self.repository.create_definition(
                        definition_command,
                        spot_single_child_plan=terms,
                        spot_goal_key=claimed.goal_key,
                        spot_near_market_materialization=(
                            AutomationSpotNearMarketMaterializationEvidence(
                                cycle_number=claimed.cycle_number,
                                goal_key=claimed.goal_key,
                                diagnostic_code=(
                                    result.diagnostic_code
                                ),
                                completed_categories=tuple(
                                    result.completed_categories
                                ),
                                coinbase_api_call_count=(
                                    result.coinbase_api_call_count
                                ),
                                evidence_sha256=result.evidence_sha256,
                            )
                        ),
                    )
                )
            except Exception:
                finalized = self._call(
                    lambda: self.repository.finalize_spot_near_market_preparation(
                        cycle_number=claimed.cycle_number,
                        goal_key=claimed.goal_key,
                        state="UNKNOWN",
                        diagnostic_code=(
                            "automation_near_market_preparation_unknown"
                        ),
                        completed_categories=(),
                        coinbase_api_call_count=None,
                        call_count_exact=False,
                        evidence_sha256=None,
                        definition_id=None,
                    )
                )
            else:
                preparations = self._call(
                    lambda: self.repository.list_spot_near_market_preparations()
                )
                record = next(
                    (
                        item
                        for item in preparations
                        if item.cycle_number == claimed.cycle_number
                        and item.goal_key == claimed.goal_key
                    ),
                    None,
                )
                if record is None or record.state != "MATERIALIZED":
                    raise AutomationRepositoryUnavailable(
                        "automation_near_market_materialization_unavailable"
                    )
                finalized = AutomationRepositoryMutation(
                    entity=record,
                    audit_id=created.audit_id,
                    correlation_id=created.correlation_id,
                )
        else:
            finalized = self._call(
                lambda: self.repository.finalize_spot_near_market_preparation(
                    cycle_number=claimed.cycle_number,
                    goal_key=claimed.goal_key,
                    state=result.outcome.value,
                    diagnostic_code=result.diagnostic_code,
                    completed_categories=tuple(result.completed_categories),
                    coinbase_api_call_count=result.coinbase_api_call_count,
                    call_count_exact=result.call_count_exact,
                    evidence_sha256=result.evidence_sha256,
                    definition_id=None,
                )
            )
        return AutomationRepositoryMutation(
            entity=self._near_market_preparation_entity(finalized.entity),
            audit_id=finalized.audit_id,
            correlation_id=finalized.correlation_id,
            replayed=finalized.replayed,
        )

    def _minimum_size_preparation_entity(
        self,
        record: Any,
    ) -> Mapping[str, Any]:
        definition = None
        dynamic_cap = None
        if record.definition_id is not None:
            definition_record = self._call(
                lambda: self.repository.get_definition(record.definition_id)
            )
            if definition_record is None:
                raise AutomationRepositoryUnavailable(
                    "automation_minimum_size_definition_unavailable"
                )
            definition = self._definition_with_plan(definition_record)
            plan = self._call(
                lambda: self.repository.get_spot_single_child_plan(
                    definition_record.definition_id,
                    definition_record.revision,
                )
            )
            if plan is None:
                raise AutomationRepositoryUnavailable(
                    "automation_minimum_size_plan_unavailable"
                )
            dynamic_cap = plan.max_possible_execution_notional_usdc
        mode = _SPOT_PREVIEW_MODE_BY_GOAL.get(record.goal_key)
        if mode is None:
            raise AutomationRepositoryUnavailable(
                "automation_minimum_size_goal_binding_invalid"
            )
        boundary = (
            record.diagnostic_code
            if record.diagnostic_code.startswith("minimum_size_v4_")
            else None
        )
        return {
            "outcome": record.state,
            "candidate_version": record.candidate_version,
            "spot_execution_mode": mode,
            "cycle_number": record.cycle_number,
            "policy_revision": (
                "BTC_USDC_POST_ONLY_BEST_BID_MINIMUM_SIZE_V2"
            ),
            "boundary_classification": boundary,
            "diagnostic_code": record.diagnostic_code,
            "completed_categories": [
                self._near_market_public_category(category)
                for category in record.completed_categories
            ],
            "coinbase_api_call_count": record.coinbase_api_call_count,
            "call_count_exact": record.call_count_exact,
            "definition": definition,
            "max_submitted_notional_usdc": "3.10",
            "max_possible_execution_notional_usdc": dynamic_cap,
            "preview_call_count": 0,
            "create_call_count": 0,
            "cancel_call_count": 0,
        }

    def prepare_minimum_size_candidate(
        self,
        *,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation:
        """Claim one V7-V9 cycle and atomically persist derived terms."""

        from application.admin_api.operator_spot_minimum_size_preparation import (
            MinimumSizePreparationOutcome,
        )
        from database.operator_automation import (
            AutomationDefinitionCreateCommand,
            AutomationSpotMinimumSizeMaterializationEvidence,
            AutomationSpotSingleChildPlanTerms,
        )

        self._require_active_control_posture()
        claim_command = self._command(
            context=context,
            payload={
                "operation": "prepare_minimum_size_candidate",
                "request": request,
            },
        )
        claim = self._call(
            lambda: self.repository.start_spot_minimum_size_preparation(
                claim_command
            )
        )
        claimed = claim.entity
        if claim.replayed:
            if claimed.state == "CLAIMED":
                raise AutomationRepositoryConflict(
                    "automation_minimum_size_preparation_in_progress"
                )
            return AutomationRepositoryMutation(
                entity=self._minimum_size_preparation_entity(claimed),
                audit_id=claim.audit_id,
                correlation_id=claim.correlation_id,
                replayed=True,
            )

        runner = self._spot_minimum_size_preparation_runner
        try:
            result = runner() if callable(runner) else None
        except Exception:
            result = None
        if result is None:
            finalized = self._call(
                lambda: self.repository.finalize_spot_minimum_size_preparation(
                    cycle_number=claimed.cycle_number,
                    goal_key=claimed.goal_key,
                    state="UNKNOWN",
                    diagnostic_code=(
                        "automation_minimum_size_runner_composition_unknown"
                    ),
                    completed_categories=(),
                    coinbase_api_call_count=None,
                    call_count_exact=False,
                    evidence_sha256=None,
                    definition_id=None,
                )
            )
        elif result.outcome is MinimumSizePreparationOutcome.MATERIALIZED:
            plan = result.plan
            if (
                plan is None
                or result.evidence_sha256 is None
                or result.coinbase_api_call_count is None
                or not result.call_count_exact
            ):
                raise AutomationRepositoryUnavailable(
                    "automation_minimum_size_preparation_result_invalid"
                )
            definition_command = AutomationDefinitionCreateCommand(
                **self._command(
                    context=context,
                    idempotency_key="minimum-size-definition:"
                    + hashlib.sha256(
                        json.dumps(
                            {
                                "actor_id": context.actor_id,
                                "cycle_number": claimed.cycle_number,
                                "goal_key": claimed.goal_key,
                                "source_idempotency_key": (
                                    context.idempotency_key
                                ),
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=True,
                        ).encode("utf-8")
                    ).hexdigest(),
                    operator_intent="materialize_minimum_size_candidate",
                    payload={
                        "operation": "materialize_minimum_size_candidate",
                        "candidate_version": claimed.candidate_version,
                        "cycle_number": claimed.cycle_number,
                        "goal_key": claimed.goal_key,
                        "policy_revision": plan.policy_revision,
                        "plan": {
                            "product_id": plan.product_id,
                            "side": plan.side,
                            "base_size": plan.base_size,
                            "limit_price": plan.limit_price,
                            "submitted_notional_usdc": (
                                plan.submitted_notional_usdc
                            ),
                            "possible_execution_notional_usdc": (
                                plan.possible_execution_notional_usdc
                            ),
                            "max_possible_execution_notional_usdc": (
                                plan.max_possible_execution_notional_usdc
                            ),
                            "v4_boundary_classification": (
                                plan.v4_boundary_classification
                            ),
                            "post_only": plan.post_only,
                        },
                    },
                ).__dict__,
                domain=AutomationDomain.SPOT,
                job_kind=AutomationJobKind.SPOT_CAMPAIGN,
                label=(
                    "BTC-USDC minimum-size successor "
                    f"V{claimed.candidate_version}"
                ),
                product_ids=("BTC-USDC",),
            )
            terms = AutomationSpotSingleChildPlanTerms(
                portfolio_id_sha256=_configured_spot_portfolio_hash(),
                product_id=plan.product_id,
                side=plan.side,
                base_size=plan.base_size,
                limit_price=plan.limit_price,
                submitted_notional_usdc=plan.submitted_notional_usdc,
                possible_execution_notional_usdc=(
                    plan.possible_execution_notional_usdc
                ),
                max_submitted_notional_usdc=(
                    plan.max_submitted_notional_usdc
                ),
                max_possible_execution_notional_usdc=(
                    plan.max_possible_execution_notional_usdc
                ),
                post_only=True,
            )
            try:
                created = self._call(
                    lambda: self.repository.create_definition(
                        definition_command,
                        spot_single_child_plan=terms,
                        spot_goal_key=claimed.goal_key,
                        spot_minimum_size_materialization=(
                            AutomationSpotMinimumSizeMaterializationEvidence(
                                cycle_number=claimed.cycle_number,
                                goal_key=claimed.goal_key,
                                diagnostic_code=result.diagnostic_code,
                                completed_categories=tuple(
                                    result.completed_categories
                                ),
                                coinbase_api_call_count=(
                                    result.coinbase_api_call_count
                                ),
                                evidence_sha256=result.evidence_sha256,
                            )
                        ),
                    )
                )
            except Exception:
                finalized = self._call(
                    lambda: self.repository.finalize_spot_minimum_size_preparation(
                        cycle_number=claimed.cycle_number,
                        goal_key=claimed.goal_key,
                        state="UNKNOWN",
                        diagnostic_code=(
                            "automation_minimum_size_materialization_unknown"
                        ),
                        completed_categories=tuple(
                            result.completed_categories
                        ),
                        coinbase_api_call_count=None,
                        call_count_exact=False,
                        evidence_sha256=None,
                        definition_id=None,
                    )
                )
            else:
                preparations = self._call(
                    lambda: self.repository.list_spot_minimum_size_preparations()
                )
                record = next(
                    (
                        item
                        for item in preparations
                        if item.cycle_number == claimed.cycle_number
                        and item.goal_key == claimed.goal_key
                    ),
                    None,
                )
                if record is None or record.state != "MATERIALIZED":
                    raise AutomationRepositoryUnavailable(
                        "automation_minimum_size_materialization_unavailable"
                    )
                finalized = AutomationRepositoryMutation(
                    entity=record,
                    audit_id=created.audit_id,
                    correlation_id=created.correlation_id,
                )
        else:
            finalized = self._call(
                lambda: self.repository.finalize_spot_minimum_size_preparation(
                    cycle_number=claimed.cycle_number,
                    goal_key=claimed.goal_key,
                    state=result.outcome.value,
                    diagnostic_code=result.diagnostic_code,
                    completed_categories=tuple(result.completed_categories),
                    coinbase_api_call_count=result.coinbase_api_call_count,
                    call_count_exact=result.call_count_exact,
                    evidence_sha256=result.evidence_sha256,
                    definition_id=None,
                )
            )
        return AutomationRepositoryMutation(
            entity=self._minimum_size_preparation_entity(finalized.entity),
            audit_id=finalized.audit_id,
            correlation_id=finalized.correlation_id,
            replayed=finalized.replayed,
        )

    @staticmethod
    def _atomic_public_categories(categories: tuple[str, ...]) -> list[str]:
        mapping = {
            "API_KEY_PERMISSIONS": "api_key_permissions",
            "PORTFOLIO_CATALOG": "portfolio_catalog",
            "ACCOUNT_WALLET_BALANCES": "wallet_balances",
            "PRODUCT_METADATA": "product_metadata",
            "BEST_BID_ASK": "best_bid_ask",
            "FEE_SUMMARY": "fee_summary",
            "EXACT_ORDER_RECONCILIATION": "exact_order_reconciliation",
            "ACCOUNT_ACTIVE_SPOT_ORDER_CATALOG": "active_order_catalog",
        }
        try:
            return [mapping[category] for category in categories]
        except KeyError:
            raise AutomationRepositoryUnavailable(
                "automation_atomic_market_snapshot_evidence_invalid"
            ) from None

    def _atomic_market_snapshot_entity(
        self,
        record: Any,
        *,
        run: Mapping[str, Any] | None = None,
        diagnostic_code: str | None = None,
    ) -> Mapping[str, Any]:
        return {
            "outcome": record.state,
            "candidate_version": record.candidate_version,
            "cycle_number": record.cycle_number,
            "diagnostic_code": diagnostic_code or record.diagnostic_code,
            "completed_categories": self._atomic_public_categories(
                tuple(record.completed_categories)
            ),
            "coinbase_api_call_count": record.coinbase_api_call_count,
            "call_count_exact": record.call_count_exact,
            "market_snapshot_binding": (
                "HASHED"
                if record.market_snapshot_sha256 is not None
                else "UNAVAILABLE"
            ),
            "run": run,
        }

    def authorize_atomic_market_snapshot_candidate(
        self,
        *,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation:
        """Hold one profile lease across reads, binding, Preview, and Create."""

        configured_portfolio_id = str(
            os.environ.get("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID") or ""
        ).strip()
        if not configured_portfolio_id:
            raise AutomationRepositoryUnavailable(
                "automation_spot_portfolio_not_configured"
            )
        command_service = self._resolve_spot_command_service()
        profile_coordinator = self._resolve_spot_profile_coordinator(
            command_service
        )
        with profile_coordinator.claim(configured_portfolio_id) as lease:
            return self._authorize_atomic_market_snapshot_candidate_under_lease(
                request=request,
                context=context,
                configured_portfolio_id=configured_portfolio_id,
                command_service=command_service,
                admission_lease=lease,
            )

    def _authorize_atomic_market_snapshot_candidate_under_lease(
        self,
        *,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
        configured_portfolio_id: str,
        command_service: Any,
        admission_lease: Any,
    ) -> AutomationRepositoryMutation:
        """Claim, bind, Preview, and conditionally Create one V10-V12 child."""

        from application.admin_api.operator_spot_atomic_market_snapshot import (
            AtomicMarketSnapshotOutcome,
            run_atomic_market_snapshot_candidate,
        )
        from database.operator_automation import (
            AutomationSpotSingleChildPlanTerms,
        )

        self._require_active_control_posture()
        claim = self._call(
            lambda: self.repository.start_spot_atomic_market_snapshot_cycle(
                self._command(
                    context=context,
                    payload={
                        "operation": (
                            "authorize_atomic_market_snapshot_candidate"
                        ),
                        "request": request,
                    },
                )
            )
        )
        claimed = claim.entity
        if claim.replayed:
            if claimed.state == "CLAIMED":
                raise AutomationRepositoryConflict(
                    "automation_atomic_market_snapshot_cycle_in_progress"
                )
            recovered_unknown = None
            if (
                claimed.state == "MATERIALIZED"
                and claimed.run_id is not None
                and claimed.plan_sha256 is not None
                and claimed.client_order_id is not None
            ):
                checkpoint = self._call(
                    lambda: self.repository.get_spot_preview_gated_goal(
                        goal_key=claimed.goal_key
                    )
                )
                if checkpoint.preview_outcome is None:
                    from application.admin_api.operator_spot_automation_runtime import (
                        derive_spot_automation_phase_key,
                    )

                    recovered_unknown = self._call(
                        lambda: self.repository.finalize_spot_preview_invocation(
                            claimed.run_id,
                            outcome="UNKNOWN",
                            failure_class="TRANSPORT_UNKNOWN",
                            rejection_code=None,
                            warning_present=False,
                            preview_id_sha256=None,
                            preview_call_count=None,
                            call_count_exact=False,
                            command=self._command(
                                context=context,
                                idempotency_key=derive_spot_automation_phase_key(
                                    outer_idempotency_key=context.idempotency_key,
                                    run_id=claimed.run_id,
                                    plan_sha256=claimed.plan_sha256,
                                    phase="atomic-preview-restart-finalize",
                                ),
                                operator_intent=(
                                    "finalize_automation_spot_single_child_preview"
                                ),
                                payload={
                                    "operation": (
                                        "finalize_atomic_preview_restart_unknown"
                                    ),
                                    "run_id": claimed.run_id,
                                    "plan_sha256": claimed.plan_sha256,
                                    "client_order_id": claimed.client_order_id,
                                    "outcome": "UNKNOWN",
                                    "failure_class": "TRANSPORT_UNKNOWN",
                                    "preview_call_count": None,
                                    "call_count_exact": False,
                                },
                            ),
                        )
                    )
            run = None
            diagnostic = claimed.diagnostic_code
            if claimed.run_id is not None:
                current = self._call(
                    lambda: self.repository.get_run(claimed.run_id)
                )
                if current is None:
                    raise AutomationRepositoryUnavailable(
                        "automation_atomic_market_snapshot_run_unavailable"
                    )
                run = self._run(current)
                diagnostic = current.diagnostic_code
            return AutomationRepositoryMutation(
                entity=self._atomic_market_snapshot_entity(
                    claimed,
                    run=run,
                    diagnostic_code=diagnostic,
                ),
                audit_id=(
                    recovered_unknown.audit_id
                    if recovered_unknown is not None
                    else claim.audit_id
                ),
                correlation_id=(
                    recovered_unknown.correlation_id
                    if recovered_unknown is not None
                    else claim.correlation_id
                ),
                replayed=recovered_unknown is None,
                activity=(
                    AutomationRunMutationActivity(
                        operation="PREVIEW_GATED_CREATE",
                        coinbase_api_call_count=None,
                        preview_call_count=None,
                        read_call_count=claimed.coinbase_api_call_count,
                        exchange_mutation_count=0,
                        create_call_count=0,
                        cancel_call_count=0,
                        call_count_exact=False,
                    )
                    if recovered_unknown is not None
                    else AutomationRunMutationActivity()
                ),
            )

        definition_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        dependencies = getattr(command_service, "dependencies", None)
        rest_client = getattr(dependencies, "rest_client", None)
        runner = (
            self._spot_atomic_market_snapshot_runner
            or run_atomic_market_snapshot_candidate
        )
        try:
            result = runner(
                rest_client=rest_client,
                approved_portfolio_id=configured_portfolio_id,
                approved_portfolio_label="Test",
                definition_id=definition_id,
                run_id=run_id,
                goal_key=claimed.goal_key,
                candidate_version=claimed.candidate_version,
                cycle_number=claimed.cycle_number,
                correlation_id=context.correlation_id,
                now_factory=self._now_factory,
            )
        except Exception:
            result = None
        if result is None:
            finalized = self._call(
                lambda: self.repository.finalize_spot_atomic_market_snapshot_terminal(
                    cycle_number=claimed.cycle_number,
                    goal_key=claimed.goal_key,
                    state="UNKNOWN",
                    diagnostic_code=(
                        "automation_atomic_market_snapshot_runner_unknown"
                    ),
                    completed_categories=(),
                    coinbase_api_call_count=None,
                    call_count_exact=False,
                    evidence_sha256=None,
                )
            )
            return AutomationRepositoryMutation(
                entity=self._atomic_market_snapshot_entity(finalized.entity),
                audit_id=finalized.audit_id,
                correlation_id=finalized.correlation_id,
                activity=_atomic_market_snapshot_read_activity(
                    coinbase_api_call_count=None,
                    call_count_exact=False,
                ),
            )
        if result.outcome is not AtomicMarketSnapshotOutcome.MATERIALIZED:
            finalized = self._call(
                lambda: self.repository.finalize_spot_atomic_market_snapshot_terminal(
                    cycle_number=claimed.cycle_number,
                    goal_key=claimed.goal_key,
                    state=result.outcome.value,
                    diagnostic_code=result.diagnostic_code,
                    completed_categories=tuple(result.completed_categories),
                    coinbase_api_call_count=result.coinbase_api_call_count,
                    call_count_exact=result.call_count_exact,
                    evidence_sha256=result.evidence_sha256,
                )
            )
            return AutomationRepositoryMutation(
                entity=self._atomic_market_snapshot_entity(finalized.entity),
                audit_id=finalized.audit_id,
                correlation_id=finalized.correlation_id,
                activity=_atomic_market_snapshot_read_activity(
                    coinbase_api_call_count=result.coinbase_api_call_count,
                    call_count_exact=result.call_count_exact,
                ),
            )
        if (
            result.plan is None
            or result.plan_sha256 is None
            or result.client_order_id is None
            or result.market_snapshot_sha256 is None
            or result.evidence_sha256 is None
            or result.snapshot is None
        ):
            raise AutomationRepositoryUnavailable(
                "automation_atomic_market_snapshot_result_invalid"
            )
        plan = result.plan
        materialized = self._call(
            lambda: self.repository.materialize_spot_atomic_market_snapshot_and_claim_preview(
                cycle_number=claimed.cycle_number,
                goal_key=claimed.goal_key,
                definition_id=definition_id,
                run_id=run_id,
                terms=AutomationSpotSingleChildPlanTerms(
                    portfolio_id_sha256=_configured_spot_portfolio_hash(),
                    product_id=plan.product_id,
                    side=plan.side,
                    base_size=plan.base_size,
                    limit_price=plan.limit_price,
                    submitted_notional_usdc=(
                        plan.submitted_notional_usdc
                    ),
                    possible_execution_notional_usdc=(
                        plan.possible_execution_notional_usdc
                    ),
                    max_submitted_notional_usdc=(
                        plan.max_submitted_notional_usdc
                    ),
                    max_possible_execution_notional_usdc=(
                        plan.max_possible_execution_notional_usdc
                    ),
                    post_only=True,
                ),
                expected_plan_sha256=result.plan_sha256,
                expected_client_order_id=result.client_order_id,
                market_snapshot_sha256=result.market_snapshot_sha256,
                evidence_sha256=result.evidence_sha256,
                attempts=tuple(result.attempts),
            )
        )
        cycles = self._call(
            lambda: self.repository.list_spot_eligibility_cycles(
                goal_key=claimed.goal_key
            )
        )
        cycle = next(
            (
                item
                for item in cycles
                if item.cycle_number == claimed.cycle_number
            ),
            None,
        )
        if cycle is None:
            raise AutomationRepositoryUnavailable(
                "automation_atomic_market_snapshot_cycle_unavailable"
            )
        attempts = self._call(
            lambda: self.repository.list_spot_eligibility_attempts(
                run_id,
                cycle_number=claimed.cycle_number,
            )
        )
        bundle = SpotAutomationEligibilityExecutionBundle(
            cycle=cycle,
            snapshot=result.snapshot,
            attempts=tuple(attempts),
        )
        try:
            authorization = self._authorize_single_child_workflow(
                run_id=run_id,
                request={
                    **request,
                    "expected_plan_sha256": result.plan_sha256,
                },
                context=context,
                preview_gated=True,
                precomputed_bundle=bundle,
                admission_lease=admission_lease,
            )
        except Exception:
            # Once the atomic transaction consumes the Preview claim, any
            # failure whose exact network boundary cannot be proven must
            # terminally consume this candidate.  Never strand a claimed
            # candidate with preview_outcome=NULL or replay it.
            from application.admin_api.operator_spot_automation_runtime import (
                derive_spot_automation_phase_key,
            )

            checkpoint = self._call(
                lambda: self.repository.get_spot_preview_gated_goal(
                    goal_key=claimed.goal_key
                )
            )
            if checkpoint.preview_outcome is None:
                finalized_unknown = self._call(
                    lambda: self.repository.finalize_spot_preview_invocation(
                        run_id,
                        outcome="UNKNOWN",
                        failure_class="TRANSPORT_UNKNOWN",
                        rejection_code=None,
                        warning_present=False,
                        preview_id_sha256=None,
                        preview_call_count=None,
                        call_count_exact=False,
                        command=self._command(
                            context=context,
                            idempotency_key=derive_spot_automation_phase_key(
                                outer_idempotency_key=context.idempotency_key,
                                run_id=run_id,
                                plan_sha256=result.plan_sha256,
                                phase="atomic-preview-failure-finalize",
                            ),
                            operator_intent=(
                                "finalize_automation_spot_single_child_preview"
                            ),
                            payload={
                                "operation": (
                                    "finalize_atomic_automation_spot_preview_unknown"
                                ),
                                "run_id": run_id,
                                "plan_sha256": result.plan_sha256,
                                "client_order_id": result.client_order_id,
                                "outcome": "UNKNOWN",
                                "failure_class": "TRANSPORT_UNKNOWN",
                                "preview_call_count": None,
                                "call_count_exact": False,
                            },
                        ),
                    )
                )
                authorization = AutomationRepositoryMutation(
                    entity={},
                    audit_id=finalized_unknown.audit_id,
                    correlation_id=finalized_unknown.correlation_id,
                    replayed=False,
                    activity=AutomationRunMutationActivity(
                        operation="PREVIEW_GATED_CREATE",
                        coinbase_api_call_count=None,
                        preview_call_count=None,
                        read_call_count=result.coinbase_api_call_count,
                        exchange_mutation_count=0,
                        create_call_count=0,
                        cancel_call_count=0,
                        call_count_exact=False,
                    ),
                )
            else:
                raise
        current = self._call(lambda: self.repository.get_run(run_id))
        if current is None:
            raise AutomationRepositoryUnavailable(
                "automation_atomic_market_snapshot_run_unavailable"
            )
        return AutomationRepositoryMutation(
            entity=self._atomic_market_snapshot_entity(
                materialized.entity,
                run=self._run(current),
                diagnostic_code=current.diagnostic_code,
            ),
            audit_id=authorization.audit_id,
            correlation_id=authorization.correlation_id,
            replayed=False,
            activity=authorization.activity,
        )

    def create_definition(
        self,
        *,
        definition: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation:
        from database.operator_automation import AutomationDefinitionCreateCommand

        single_child = definition.get("single_child_order")
        portfolio_id_sha256 = (
            _configured_spot_portfolio_hash()
            if single_child is not None
            else None
        )
        command = AutomationDefinitionCreateCommand(
            idempotency_key=context.idempotency_key,
            payload_sha256=_payload_sha256(
                {"operation": "create_definition", "definition": definition}
            ),
            actor_id=context.actor_id,
            correlation_id=context.correlation_id,
            operator_intent=context.operator_intent,
            domain=AutomationDomain(str(definition["domain"])),
            job_kind=AutomationJobKind(str(definition["job_kind"])),
            label=str(definition["display_name"]),
            product_ids=tuple(str(item) for item in definition.get("product_ids", [])),
        )
        plan = None
        if single_child is not None:
            from database.operator_automation import (
                AUTOMATION_SPOT_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
                AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY,
                AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY,
                AutomationSpotSingleChildPlanTerms,
            )

            assert portfolio_id_sha256 is not None
            base_size = Decimal(str(single_child["base_size"]))
            limit_price = Decimal(str(single_child["limit_price"]))
            submitted = base_size * limit_price
            plan_terms = AutomationSpotSingleChildPlanTerms(
                portfolio_id_sha256=portfolio_id_sha256,
                product_id="BTC-USDC",
                side=str(single_child["side"]),
                base_size=str(single_child["base_size"]),
                limit_price=str(single_child["limit_price"]),
                submitted_notional_usdc=str(submitted),
                possible_execution_notional_usdc=str(submitted),
                max_submitted_notional_usdc="3.10",
                max_possible_execution_notional_usdc="1.00",
                post_only=bool(single_child["post_only"]),
            )
            result = self._call(
                lambda: self.repository.create_definition(
                    command,
                    spot_single_child_plan=plan_terms,
                    spot_goal_key=(
                        AUTOMATION_SPOT_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY
                        if definition.get("spot_execution_mode")
                        == "DOCUMENTED_MARKET_FRESHNESS_V3"
                        else AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY
                        if definition.get("spot_execution_mode")
                        == "PREVIEW_GATED_V2"
                        else AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY
                    ),
                )
            )
        else:
            result = self._call(lambda: self.repository.create_definition(command))
        return AutomationRepositoryMutation(
            entity=self._definition_with_plan(result.entity),
            audit_id=result.audit_id,
            correlation_id=result.correlation_id,
            replayed=result.replayed,
        )

    def transition_definition(
        self,
        *,
        definition_id: str,
        action: AutomationDefinitionLifecycleAction,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation:
        command = self._command(
            context=context,
            payload={
                "operation": "transition_definition",
                "definition_id": definition_id,
                "action": action.value,
                "request": request,
            },
        )
        result = self._call(
            lambda: self.repository.transition_definition(
                definition_id,
                action.value.lower(),
                command,
            )
        )
        return AutomationRepositoryMutation(
            entity=self._definition_with_plan(result.entity),
            audit_id=result.audit_id,
            correlation_id=result.correlation_id,
            replayed=result.replayed,
        )

    def set_schedule(
        self,
        *,
        definition_id: str,
        schedule: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation:
        from core.enums import OperatorAutomationScheduleKind

        mode = OperatorAutomationScheduleKind(str(schedule["mode"]))
        interval_minutes = schedule.get("interval_minutes")
        interval_seconds = (
            int(interval_minutes) * 60 if interval_minutes is not None else None
        )
        command = self._command(
            context=context,
            payload={
                "operation": "set_schedule",
                "definition_id": definition_id,
                "schedule": schedule,
            },
        )
        result = self._call(
            lambda: self.repository.set_schedule(
                definition_id,
                mode,
                interval_seconds=interval_seconds,
                command=command,
            )
        )
        return AutomationRepositoryMutation(
            entity=self._definition_with_plan(result.entity),
            audit_id=result.audit_id,
            correlation_id=result.correlation_id,
            replayed=result.replayed,
        )

    def clear_schedule(
        self,
        *,
        definition_id: str,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation:
        command = self._command(
            context=context,
            payload={
                "operation": "clear_schedule",
                "definition_id": definition_id,
                "request": request,
            },
        )
        result = self._call(
            lambda: self.repository.clear_schedule(definition_id, command)
        )
        return AutomationRepositoryMutation(
            entity=self._definition_with_plan(result.entity),
            audit_id=result.audit_id,
            correlation_id=result.correlation_id,
            replayed=result.replayed,
        )

    def transition_control_posture(
        self,
        *,
        action: AutomationControlAction,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation:
        command = self._command(
            context=context,
            payload={
                "operation": "transition_control_posture",
                "action": action.name,
                "request": request,
            },
        )
        result = self._call(
            lambda: self.repository.transition_control_posture(
                action.name.lower(),
                command,
            )
        )
        return self._mutation(result, self._control)

    def claim_one_shot_run(
        self,
        *,
        definition_id: str,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation:
        claim_command = self._command(
            context=context,
            payload={
                "operation": "claim_one_shot_run",
                "definition_id": definition_id,
                "request": request,
            },
        )
        claim = self._call(
            lambda: self.repository.claim_one_shot_run(
                definition_id,
                claim_command,
            )
        )
        current_claim = claim.entity
        if claim.replayed:
            current = self._call(
                lambda: self.repository.get_run(claim.entity.run_id)
            )
            if current is None:
                raise AutomationRepositoryUnavailable(
                    "automation_run_readback_unavailable"
                )
            current_claim = current
            if current.state not in {
                AutomationRunState.CLAIMED,
                AutomationRunState.PREPARING,
            }:
                return AutomationRepositoryMutation(
                    entity=self._run(current),
                    audit_id=current.audit_id,
                    correlation_id=claim.correlation_id,
                    replayed=True,
                )
        if (
            current_claim.job_kind is AutomationJobKind.SPOT_CAMPAIGN
            and current_claim.definition_revision is not None
        ):
            plan = self._call(
                lambda: self.repository.get_spot_single_child_plan(
                    current_claim.definition_id,
                    current_claim.definition_revision,
                )
            )
            if plan is not None:
                prepare_key = "automation-internal-prepare-" + hashlib.sha256(
                    f"{context.idempotency_key}:{current_claim.run_id}".encode(
                        "utf-8"
                    )
                ).hexdigest()
                prepare_command = self._command(
                    context=context,
                    idempotency_key=prepare_key,
                    operator_intent="prepare_automation_single_child_run",
                    payload={
                        "operation": "prepare_automation_single_child_run",
                        "run_id": current_claim.run_id,
                        "plan_sha256": plan.plan_sha256,
                    },
                )
                if current_claim.state is AutomationRunState.CLAIMED:
                    prepared = self._call(
                        lambda: self.repository.transition_run(
                            current_claim.run_id,
                            AutomationRunState.PREPARING,
                            diagnostic_code="preparing",
                            command=prepare_command,
                        )
                    )
                    current_claim = prepared.entity
                diagnostic_code = (
                    "automation_active_order_catalog_read_not_authorized"
                )
            else:
                diagnostic_code = "automation_single_child_plan_missing"
            block_key = "automation-internal-single-child-block-" + hashlib.sha256(
                f"{context.idempotency_key}:{current_claim.run_id}:{diagnostic_code}".encode(
                    "utf-8"
                )
            ).hexdigest()
            block_command = self._command(
                context=context,
                idempotency_key=block_key,
                operator_intent="block_automation_single_child_preflight",
                payload={
                    "operation": "block_automation_single_child_preflight",
                    "run_id": current_claim.run_id,
                    "diagnostic_code": diagnostic_code,
                },
            )
            blocked = self._call(
                lambda: self.repository.transition_run(
                    current_claim.run_id,
                    AutomationRunState.BLOCKED,
                    diagnostic_code=diagnostic_code,
                    command=block_command,
                )
            )
            return AutomationRepositoryMutation(
                entity=self._run(blocked.entity),
                audit_id=blocked.audit_id,
                correlation_id=blocked.correlation_id,
                replayed=claim.replayed,
            )
        internal_key = "automation-internal-block-" + hashlib.sha256(
            f"{context.idempotency_key}:{claim.entity.run_id}".encode("utf-8")
        ).hexdigest()
        block_command = self._command(
            context=context,
            idempotency_key=internal_key,
            operator_intent="finalize_automation_domain_adapter_unavailable",
            payload={
                "operation": "block_unavailable_domain_adapter",
                "run_id": claim.entity.run_id,
            },
        )
        blocked = self._call(
            lambda: self.repository.transition_run(
                claim.entity.run_id,
                AutomationRunState.BLOCKED,
                diagnostic_code="automation_domain_adapter_unavailable",
                command=block_command,
            )
        )
        return AutomationRepositoryMutation(
            entity=self._run(blocked.entity),
            audit_id=blocked.audit_id,
            correlation_id=blocked.correlation_id,
            replayed=claim.replayed,
        )

    def authorize_single_child(
        self,
        *,
        run_id: str,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation:
        return self._authorize_single_child_workflow(
            run_id=run_id,
            request=request,
            context=context,
            preview_gated=False,
        )

    def authorize_preview_gated_single_child(
        self,
        *,
        run_id: str,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation:
        return self._authorize_single_child_workflow(
            run_id=run_id,
            request=request,
            context=context,
            preview_gated=True,
        )

    def _authorize_single_child_workflow(
        self,
        *,
        run_id: str,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
        preview_gated: bool,
        precomputed_bundle: SpotAutomationEligibilityExecutionBundle | None = None,
        admission_lease: Any | None = None,
    ) -> AutomationRepositoryMutation:
        """Run fresh exact eligibility, then the goal-owned live boundary."""

        self._require_active_control_posture()
        record = self._call(lambda: self.repository.get_run(run_id))
        if record is None:
            raise AutomationRepositoryNotFound(AUTOMATION_NOT_FOUND)
        if (
            record.job_kind is not AutomationJobKind.SPOT_CAMPAIGN
            or record.definition_revision is None
        ):
            raise AutomationRepositoryConflict(
                "automation_single_child_run_ineligible"
            )
        plan = self._call(
            lambda: self.repository.get_spot_single_child_plan(
                record.definition_id,
                record.definition_revision,
            )
        )
        if plan is None:
            raise AutomationRepositoryConflict(
                "automation_single_child_plan_missing"
            )
        if request.get("expected_plan_sha256") != plan.plan_sha256:
            raise AutomationRepositoryConflict(
                "automation_single_child_plan_mismatch"
            )

        from database.operator_automation import (
            AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY,
        )

        goal_key = self._call(
            lambda: self.repository.get_spot_goal_key_for_run(run_id)
        )
        if (
            preview_gated
            and goal_key not in _SPOT_PREVIEW_GOAL_KEYS
        ) or (
            not preview_gated
            and goal_key != AUTOMATION_SPOT_LIVE_PROOF_GOAL_KEY
        ):
            raise AutomationRepositoryConflict(
                "automation_spot_execution_goal_mismatch"
            )
        preview_goal = (
            self._call(
                lambda: self.repository.get_spot_preview_gated_goal(
                    goal_key=goal_key,
                )
            )
            if preview_gated
            else None
        )
        if preview_goal is not None and preview_goal.preview_outcome in {
            "REJECTED",
            "UNKNOWN",
        }:
            current = self._call(lambda: self.repository.get_run(run_id))
            if current is None or preview_goal.bound_run_id != run_id:
                raise AutomationRepositoryUnavailable(
                    "automation_spot_preview_result_unavailable"
                )
            return AutomationRepositoryMutation(
                entity=self._run(current),
                audit_id=current.audit_id,
                correlation_id=current.correlation_id,
                replayed=True,
                activity=AutomationRunMutationActivity(),
            )

        from application.admin_api.operator_spot_automation_runtime import (
            SpotAutomationRuntimeBindingError,
            derive_spot_automation_phase_key,
            prepare_spot_automation_create_command,
        )

        existing_execution = self._call(
            lambda: self.repository.get_spot_run_execution(run_id)
        )
        if existing_execution is not None:
            try:
                prepared_replay = prepare_spot_automation_create_command(
                    run=record,
                    plan=plan,
                    client_order_id=existing_execution.client_order_id,
                    actor_id=context.actor_id,
                    roles=context.roles,
                    correlation_id=context.correlation_id,
                    operator_intent=context.operator_intent,
                    outer_idempotency_key=context.idempotency_key,
                    minimum_size_dynamic_cap=(
                        goal_key in _SPOT_DYNAMIC_CAP_GOAL_KEYS
                    ),
                )
            except SpotAutomationRuntimeBindingError:
                raise AutomationRepositoryUnavailable(
                    "automation_spot_execution_replay_invalid"
                ) from None
            replay = self._call(
                lambda: self.repository.start_spot_create_invocation(
                    run_id,
                    eligibility_cycle=existing_execution.eligibility_cycle,
                    command=self._spot_invocation_start_command(
                        context=context,
                        request=request,
                        run_id=run_id,
                        eligibility_cycle=existing_execution.eligibility_cycle,
                        plan_sha256=plan.plan_sha256,
                        client_order_id=existing_execution.client_order_id,
                        command_payload_sha256=prepared_replay.proof_context[
                            "payload_hash"
                        ],
                        operation="start_automation_spot_create",
                        phase="create-start",
                        operator_intent=(
                            "claim_automation_spot_single_child_create"
                        ),
                    ),
                )
            )
            if (
                not replay.replayed
                or not self._spot_execution_binding_matches(
                    replay.entity,
                    record=record,
                    plan=plan,
                    goal_key=goal_key,
                    eligibility_cycle=existing_execution.eligibility_cycle,
                    client_order_id=existing_execution.client_order_id,
                )
            ):
                raise AutomationRepositoryUnavailable(
                    "automation_spot_execution_replay_invalid"
                )
            current = self._call(lambda: self.repository.get_run(run_id))
            if current is None:
                raise AutomationRepositoryUnavailable(
                    "automation_spot_execution_replay_unavailable"
                )
            return AutomationRepositoryMutation(
                entity=self._run(current),
                audit_id=replay.audit_id,
                correlation_id=replay.correlation_id,
                replayed=True,
                activity=AutomationRunMutationActivity(),
            )
        initial_checkpoint = bool(
            record.state is AutomationRunState.AWAITING_OPERATOR_AUTHORIZATION
            and record.diagnostic_code == "awaiting_operator_authorization"
            and not record.live_attempt_consumed
        )
        accepted_preview_checkpoint = bool(
            preview_gated
            and preview_goal is not None
            and preview_goal.preview_outcome == "ACCEPTED"
            and preview_goal.bound_run_id == run_id
            and record.state
            is AutomationRunState.AWAITING_OPERATOR_AUTHORIZATION
            and record.diagnostic_code
            == "automation_spot_preview_accepted_create_ready"
            and record.live_attempt_consumed
        )
        atomic_preview_checkpoint = bool(
            preview_gated
            and goal_key in _SPOT_ATOMIC_MARKET_SNAPSHOT_GOAL_KEYS
            and preview_goal is not None
            and preview_goal.preview_allowance_consumed
            and preview_goal.preview_outcome is None
            and preview_goal.bound_run_id == run_id
            and preview_goal.plan_sha256 == plan.plan_sha256
            and record.state
            is AutomationRunState.AWAITING_OPERATOR_AUTHORIZATION
            and record.diagnostic_code
            == "automation_spot_preview_invocation_started"
            and record.live_attempt_consumed
        )
        if not (
            initial_checkpoint
            or accepted_preview_checkpoint
            or atomic_preview_checkpoint
        ):
            raise AutomationRepositoryConflict(
                "automation_single_child_run_not_authorizable"
            )

        from application.admin_api.operator_spot_automation_execution import (
            OperatorSpotAutomationExecutionClassification,
            OperatorSpotAutomationExecutionOperation,
            OperatorSpotAutomationExecutionOutcome,
            classify_canonical_spot_automation_create_response,
        )
        from application.admin_api.operator_spot_automation_runtime import (
            bind_spot_automation_create_command,
            build_spot_automation_create_admission,
        )
        from core.coinbase_execution_authority import (
            COINBASE_EXECUTION_SCOPE_SPOT_PLACE,
            COINBASE_EXECUTION_SCOPE_SPOT_PREVIEW,
            require_coinbase_execution_authority,
        )
        from application.admin_api.operator_spot_automation_preview import (
            SpotAutomationPreviewOutcome,
            classify_spot_automation_preview_exception,
            classify_spot_automation_preview_response,
            unknown_spot_automation_preview_classification,
        )

        command_service = self._resolve_spot_command_service()
        profile_coordinator = self._resolve_spot_profile_coordinator(
            command_service
        )
        configured_portfolio_id = str(
            os.environ.get("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID") or ""
        ).strip()
        if not configured_portfolio_id:
            raise AutomationRepositoryUnavailable(
                "automation_spot_portfolio_not_configured"
            )
        eligibility_context = context.model_copy(
            update={
                "idempotency_key": derive_spot_automation_phase_key(
                    outer_idempotency_key=context.idempotency_key,
                    run_id=run_id,
                    plan_sha256=plan.plan_sha256,
                    # The durable allocator owns both the goal-global cycle
                    # number and ten-cycle limit.  Keep this phase identity
                    # stable so an exact outer retry replays the completed
                    # cycle before reader construction instead of allocating
                    # another set of approved reads.
                    phase="authorization-cycle",
                )
            }
        )

        lease_context = (
            nullcontext(admission_lease)
            if admission_lease is not None
            else profile_coordinator.claim(configured_portfolio_id)
        )
        with lease_context as lease:
            try:
                if precomputed_bundle is not None:
                    if goal_key not in _SPOT_ATOMIC_MARKET_SNAPSHOT_GOAL_KEYS:
                        raise SpotAutomationRuntimeBindingError(
                            "spot_automation_precomputed_eligibility_invalid"
                        )
                    bundle = precomputed_bundle
                else:
                    bundle = self._run_spot_execution_eligibility(
                        record=record,
                        plan=plan,
                        request=request,
                        context=eligibility_context,
                        lease=lease,
                    )
                eligibility_read_call_count = (
                    bundle.cycle.coinbase_api_call_count
                )
                eligibility_read_call_count_exact = bool(
                    bundle.cycle.call_count_exact
                )
                planned_budget_fetcher = getattr(
                    getattr(command_service, "dependencies", None),
                    "planned_budget_fetcher",
                    None,
                )
                if not callable(planned_budget_fetcher):
                    raise SpotAutomationRuntimeBindingError(
                        "spot_automation_planned_budget_invalid"
                    )
                planned_budget = planned_budget_fetcher()
                admission = build_spot_automation_create_admission(
                    run=record,
                    plan=plan,
                    cycle=bundle.cycle,
                    snapshot=bundle.snapshot,
                    attempts=bundle.attempts,
                    lease=lease,
                    configured_portfolio_id=configured_portfolio_id,
                    planned_budget=planned_budget,
                    now=self._now_factory(),
                    goal_key=goal_key,
                )
                prepared = prepare_spot_automation_create_command(
                    run=record,
                    plan=plan,
                    client_order_id=admission.client_order_id,
                    actor_id=context.actor_id,
                    roles=context.roles,
                    correlation_id=context.correlation_id,
                    operator_intent=context.operator_intent,
                    outer_idempotency_key=context.idempotency_key,
                    minimum_size_dynamic_cap=(
                        goal_key in _SPOT_DYNAMIC_CAP_GOAL_KEYS
                    ),
                )
                wallet_notional = (
                    admission.wallet_evidence.available_balance
                    if admission.wallet_evidence.required_currency == "USDC"
                    else admission.wallet_evidence.available_balance
                    * admission.limit_price
                )
                proof_chain = self._record_spot_proof_chain(
                    proof_context=prepared.proof_context,
                    command_kind="manual",
                    roles=context.roles,
                    wallet_available_notional_usdc=wallet_notional,
                )
                self._evaluate_spot_live_admission(
                    proof_context=prepared.proof_context,
                    proof_chain=proof_chain,
                )
                command = bind_spot_automation_create_command(
                    prepared=prepared,
                    proof_chain=proof_chain,
                )
            except AutomationRepositoryConflict:
                raise
            except Exception:
                raise AutomationRepositoryConflict(
                    "automation_spot_create_admission_failed"
                ) from None

            preview_call_count_this_request: int | None = 0
            preview_call_count_exact_this_request = True
            if (
                preview_gated
                and preview_goal is not None
                and preview_goal.preview_outcome != "ACCEPTED"
            ):
                preview_start_command = self._spot_invocation_start_command(
                    context=context,
                    request=request,
                    run_id=run_id,
                    eligibility_cycle=bundle.cycle.cycle_number,
                    plan_sha256=plan.plan_sha256,
                    client_order_id=admission.client_order_id,
                    command_payload_sha256=prepared.proof_context[
                        "payload_hash"
                    ],
                    operation="start_automation_spot_preview",
                    phase="preview-start",
                    operator_intent=(
                        "claim_automation_spot_single_child_preview"
                    ),
                )
                try:
                    with self._resolve_spot_execution_scope_factory()(
                        COINBASE_EXECUTION_SCOPE_SPOT_PREVIEW
                    ):
                        if self._spot_preview_invoker is None:
                            require_coinbase_execution_authority(
                                expected_scope=(
                                    COINBASE_EXECUTION_SCOPE_SPOT_PREVIEW
                                )
                            )
                        atomic_preclaimed = bool(
                            goal_key
                            in _SPOT_ATOMIC_MARKET_SNAPSHOT_GOAL_KEYS
                            and atomic_preview_checkpoint
                        )
                        if atomic_preclaimed:
                            started_preview = None
                            started_goal = preview_goal
                        else:
                            started_preview = self._call(
                                lambda: self.repository.start_spot_preview_invocation(
                                    run_id,
                                    eligibility_cycle=(
                                        bundle.cycle.cycle_number
                                    ),
                                    command=preview_start_command,
                                )
                            )
                            started_goal = started_preview.entity
                        if (
                            started_goal.bound_run_id != run_id
                            or started_goal.eligibility_cycle
                            != bundle.cycle.cycle_number
                            or started_goal.plan_sha256 != plan.plan_sha256
                            or started_goal.portfolio_id_sha256
                            != plan.portfolio_id_sha256
                            or started_goal.product_id != plan.product_id
                            or started_goal.client_order_id
                            != admission.client_order_id
                            or not started_goal.preview_allowance_consumed
                            or started_goal.create_allowance_consumed
                        ):
                            raise AutomationRepositoryUnavailable(
                                "automation_spot_preview_claim_invalid"
                            )
                        if (
                            started_preview is not None
                            and started_preview.replayed
                        ):
                            preview_classification = (
                                unknown_spot_automation_preview_classification(
                                    transport_unknown=True
                                )
                            )
                        else:
                            try:
                                raw_preview = self._invoke_spot_preview(
                                    command_service=command_service,
                                    plan=plan,
                                )
                            except Exception as exc:
                                preview_classification = (
                                    classify_spot_automation_preview_exception(
                                        exc
                                    )
                                )
                            else:
                                try:
                                    preview_classification = (
                                        classify_spot_automation_preview_response(
                                            raw_preview,
                                            expected_base_size=plan.base_size,
                                            expected_quote_size=(
                                                plan.submitted_notional_usdc
                                            ),
                                        )
                                    )
                                except Exception:
                                    preview_classification = (
                                        unknown_spot_automation_preview_classification(
                                            transport_unknown=False
                                        )
                                    )
                except AutomationRepositoryError:
                    raise

                preview_finalize_payload = {
                    "operation": "finalize_automation_spot_preview",
                    "run_id": run_id,
                    "plan_sha256": plan.plan_sha256,
                    "client_order_id": admission.client_order_id,
                    "outcome": preview_classification.outcome.value,
                    "failure_class": (
                        preview_classification.failure_class.value
                    ),
                    "rejection_code": (
                        preview_classification.rejection_code.value
                        if preview_classification.rejection_code is not None
                        else None
                    ),
                    "warning_present": (
                        preview_classification.warning_present
                    ),
                    "preview_id_retained": (
                        "HASHED"
                        if preview_classification.preview_id_sha256
                        is not None
                        else "WITHHELD"
                    ),
                    "preview_call_count": (
                        preview_classification.preview_call_count
                    ),
                    "call_count_exact": (
                        preview_classification.preview_call_count_exact
                    ),
                }
                finalized_preview = self._call(
                    lambda: self.repository.finalize_spot_preview_invocation(
                        run_id,
                        outcome=preview_classification.outcome.value,
                        failure_class=(
                            preview_classification.failure_class.value
                        ),
                        rejection_code=(
                            preview_classification.rejection_code.value
                            if preview_classification.rejection_code is not None
                            else None
                        ),
                        warning_present=(
                            preview_classification.warning_present
                        ),
                        preview_id_sha256=(
                            preview_classification.preview_id_sha256
                        ),
                        preview_call_count=(
                            preview_classification.preview_call_count
                        ),
                        call_count_exact=(
                            preview_classification.preview_call_count_exact
                        ),
                        command=self._command(
                            context=context,
                            idempotency_key=derive_spot_automation_phase_key(
                                outer_idempotency_key=(
                                    context.idempotency_key
                                ),
                                run_id=run_id,
                                plan_sha256=plan.plan_sha256,
                                phase="preview-finalize",
                            ),
                            operator_intent=(
                                "finalize_automation_spot_single_child_preview"
                            ),
                            payload=preview_finalize_payload,
                        ),
                    )
                )
                preview_goal = finalized_preview.entity
                preview_call_count_this_request = (
                    preview_classification.preview_call_count
                )
                preview_call_count_exact_this_request = bool(
                    preview_classification.preview_call_count_exact
                )
                if (
                    preview_classification.outcome
                    is not SpotAutomationPreviewOutcome.ACCEPTED
                ):
                    current = self._call(
                        lambda: self.repository.get_run(run_id)
                    )
                    if current is None:
                        raise AutomationRepositoryUnavailable(
                            "automation_spot_preview_result_unavailable"
                        )
                    exact = bool(
                        eligibility_read_call_count_exact
                        and preview_classification.preview_call_count_exact
                    )
                    return AutomationRepositoryMutation(
                        entity=self._run(current),
                        audit_id=finalized_preview.audit_id,
                        correlation_id=(
                            finalized_preview.correlation_id
                        ),
                        replayed=False,
                        activity=AutomationRunMutationActivity(
                            operation="PREVIEW_GATED_CREATE",
                            coinbase_api_call_count=(
                                int(eligibility_read_call_count or 0)
                                + int(
                                    preview_classification.preview_call_count
                                    or 0
                                )
                                if exact
                                else None
                            ),
                            preview_call_count=(
                                preview_classification.preview_call_count
                            ),
                            read_call_count=(
                                eligibility_read_call_count
                                if eligibility_read_call_count_exact
                                else None
                            ),
                            exchange_mutation_count=0,
                            create_call_count=0,
                            cancel_call_count=0,
                            call_count_exact=exact,
                        ),
                    )

            start_command = self._spot_invocation_start_command(
                context=context,
                request=request,
                run_id=run_id,
                eligibility_cycle=bundle.cycle.cycle_number,
                plan_sha256=plan.plan_sha256,
                client_order_id=admission.client_order_id,
                command_payload_sha256=prepared.proof_context["payload_hash"],
                operation="start_automation_spot_create",
                phase="create-start",
                operator_intent="claim_automation_spot_single_child_create",
            )
            started = self._call(
                lambda: self.repository.start_spot_create_invocation(
                    run_id,
                    eligibility_cycle=bundle.cycle.cycle_number,
                    command=start_command,
                )
            )
            started_execution = started.entity
            if not self._spot_execution_binding_matches(
                started_execution,
                record=record,
                plan=plan,
                goal_key=goal_key,
                eligibility_cycle=bundle.cycle.cycle_number,
                client_order_id=admission.client_order_id,
            ):
                raise AutomationRepositoryUnavailable(
                    "automation_spot_create_claim_invalid"
                )
            if started.replayed:
                current = self._call(lambda: self.repository.get_run(run_id))
                if current is None:
                    raise AutomationRepositoryUnavailable(
                        "automation_spot_execution_replay_unavailable"
                    )
                return AutomationRepositoryMutation(
                    entity=self._run(current),
                    audit_id=started.audit_id,
                    correlation_id=started.correlation_id,
                    replayed=True,
                    activity=AutomationRunMutationActivity(),
                )

            try:
                with self._resolve_spot_execution_scope_factory()(
                    COINBASE_EXECUTION_SCOPE_SPOT_PLACE
                ):
                    response = command_service.place_manual_order(
                        command,
                        automation_admission=admission,
                    )
                if response.client_order_id != admission.client_order_id:
                    raise RuntimeError(
                        "automation_spot_create_response_identity_mismatch"
                    )
                classification = (
                    classify_canonical_spot_automation_create_response(
                        response
                    )
                )
            except Exception:
                classification = OperatorSpotAutomationExecutionClassification(
                    operation=OperatorSpotAutomationExecutionOperation.CREATE,
                    outcome=OperatorSpotAutomationExecutionOutcome.UNKNOWN,
                    child_terminal=None,
                    mutation_call_count=None,
                    mutation_call_count_exact=False,
                    read_call_count=None,
                    read_call_count_exact=False,
                )

            finalize_payload = {
                "operation": "finalize_automation_spot_create",
                "run_id": run_id,
                "plan_sha256": plan.plan_sha256,
                "client_order_id": admission.client_order_id,
                "outcome": classification.outcome.value,
                "mutation_call_count": classification.mutation_call_count,
                "mutation_call_count_exact": (
                    classification.mutation_call_count_exact
                ),
                "read_call_count": classification.read_call_count,
                "read_call_count_exact": (
                    classification.read_call_count_exact
                ),
                "child_terminal": classification.child_terminal,
            }
            finalized = self._call(
                lambda: self.repository.finalize_spot_create_invocation(
                    run_id,
                    outcome=classification.outcome.value,
                    child_terminal=(
                        False
                        if classification.outcome
                        is OperatorSpotAutomationExecutionOutcome.REJECTED
                        else classification.child_terminal
                    ),
                    coinbase_api_call_count=(
                        classification.mutation_call_count
                    ),
                    call_count_exact=(
                        classification.mutation_call_count_exact
                    ),
                    read_call_count=classification.read_call_count,
                    read_call_count_exact=(
                        classification.read_call_count_exact
                    ),
                    command=self._command(
                        context=context,
                        idempotency_key=derive_spot_automation_phase_key(
                            outer_idempotency_key=context.idempotency_key,
                            run_id=run_id,
                            plan_sha256=plan.plan_sha256,
                            phase="create-finalize",
                        ),
                        operator_intent=(
                            "finalize_automation_spot_single_child_create"
                        ),
                        payload=finalize_payload,
                    ),
                )
            )
            current = self._call(lambda: self.repository.get_run(run_id))
            if current is None:
                raise AutomationRepositoryUnavailable(
                    "automation_spot_create_result_unavailable"
                )
            if preview_gated:
                request_read_call_count_exact = bool(
                    eligibility_read_call_count_exact
                    and classification.read_call_count_exact
                )
                request_read_call_count = (
                    int(eligibility_read_call_count or 0)
                    + int(classification.read_call_count or 0)
                    if request_read_call_count_exact
                    else None
                )
                create_exact = bool(
                    eligibility_read_call_count_exact
                    and preview_call_count_exact_this_request
                    and classification.mutation_call_count_exact
                    and classification.read_call_count_exact
                )
                activity = AutomationRunMutationActivity(
                    operation="PREVIEW_GATED_CREATE",
                    coinbase_api_call_count=(
                        int(preview_call_count_this_request or 0)
                        + int(classification.mutation_call_count or 0)
                        + int(request_read_call_count or 0)
                        if create_exact
                        else None
                    ),
                    preview_call_count=preview_call_count_this_request,
                    read_call_count=request_read_call_count,
                    exchange_mutation_count=(
                        classification.mutation_call_count
                        if classification.mutation_call_count_exact
                        else None
                    ),
                    create_call_count=(
                        classification.mutation_call_count
                        if classification.mutation_call_count_exact
                        else None
                    ),
                    cancel_call_count=0,
                    call_count_exact=create_exact,
                )
            else:
                activity = self._activity_from_classification(
                    classification,
                    operation="CREATE",
                )
            return AutomationRepositoryMutation(
                entity=self._run(current),
                audit_id=finalized.audit_id,
                correlation_id=finalized.correlation_id,
                replayed=False,
                activity=activity,
            )

    def safe_closeout_single_child(
        self,
        *,
        run_id: str,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation:
        """Claim once and invoke only canonical exact-child safe closeout."""

        self._require_safe_closeout_control_posture()
        record = self._call(lambda: self.repository.get_run(run_id))
        if record is None:
            raise AutomationRepositoryNotFound(AUTOMATION_NOT_FOUND)
        if (
            record.job_kind is not AutomationJobKind.SPOT_CAMPAIGN
            or record.definition_revision is None
        ):
            raise AutomationRepositoryConflict(
                "automation_single_child_run_ineligible"
            )
        plan = self._call(
            lambda: self.repository.get_spot_single_child_plan(
                record.definition_id,
                record.definition_revision,
            )
        )
        if plan is None:
            raise AutomationRepositoryConflict(
                "automation_single_child_plan_missing"
            )
        if request.get("expected_plan_sha256") != plan.plan_sha256:
            raise AutomationRepositoryConflict(
                "automation_single_child_plan_mismatch"
            )

        from application.admin_api.operator_spot_automation_runtime import (
            SpotAutomationRuntimeBindingError,
            derive_spot_automation_phase_key,
            prepare_spot_automation_cancel_command,
        )

        execution = self._call(
            lambda: self.repository.get_spot_run_execution(run_id)
        )
        if execution is None:
            raise AutomationRepositoryConflict(
                "automation_spot_safe_closeout_not_eligible"
            )
        spot_goal_key = self._call(
            lambda: self.repository.get_spot_goal_key_for_run(run_id)
        )
        if execution.cancel_allowance_consumed:
            try:
                prepared_replay = prepare_spot_automation_cancel_command(
                    run=record,
                    plan=plan,
                    client_order_id=execution.client_order_id,
                    actor_id=context.actor_id,
                    roles=context.roles,
                    correlation_id=context.correlation_id,
                    operator_intent=context.operator_intent,
                    outer_idempotency_key=context.idempotency_key,
                    reason=str(request.get("reason") or ""),
                )
            except SpotAutomationRuntimeBindingError:
                raise AutomationRepositoryUnavailable(
                    "automation_spot_execution_replay_invalid"
                ) from None
            replay = self._call(
                lambda: self.repository.start_spot_cancel_invocation(
                    run_id,
                    client_order_id=execution.client_order_id,
                    command=self._spot_invocation_start_command(
                        context=context,
                        request=request,
                        run_id=run_id,
                        eligibility_cycle=execution.eligibility_cycle,
                        plan_sha256=plan.plan_sha256,
                        client_order_id=execution.client_order_id,
                        command_payload_sha256=prepared_replay.proof_context[
                            "payload_hash"
                        ],
                        operation="start_automation_spot_safe_closeout",
                        phase="cancel-start",
                        operator_intent=(
                            "claim_automation_spot_exact_child_safe_closeout"
                        ),
                    ),
                )
            )
            if (
                not replay.replayed
                or not self._spot_execution_binding_matches(
                    replay.entity,
                    record=record,
                    plan=plan,
                    goal_key=spot_goal_key,
                    eligibility_cycle=execution.eligibility_cycle,
                    client_order_id=execution.client_order_id,
                    require_cancel_allowance=True,
                )
            ):
                raise AutomationRepositoryUnavailable(
                    "automation_spot_execution_replay_invalid"
                )
            current = self._call(lambda: self.repository.get_run(run_id))
            if current is None:
                raise AutomationRepositoryUnavailable(
                    "automation_spot_execution_replay_unavailable"
                )
            return AutomationRepositoryMutation(
                entity=self._run(current),
                audit_id=replay.audit_id,
                correlation_id=replay.correlation_id,
                replayed=True,
                activity=AutomationRunMutationActivity(),
            )
        if (
            record.state is not AutomationRunState.ACTIVE
            or record.diagnostic_code != "automation_spot_safe_closeout_ready"
            or execution.create_outcome != "ACCEPTED"
            or execution.child_terminal is not False
            or not execution.create_allowance_consumed
        ):
            raise AutomationRepositoryConflict(
                "automation_spot_safe_closeout_not_eligible"
            )

        from application.admin_api.operator_spot_automation_execution import (
            OperatorSpotAutomationExecutionClassification,
            OperatorSpotAutomationExecutionOperation,
            OperatorSpotAutomationExecutionOutcome,
            classify_canonical_spot_automation_cancel_response,
        )
        from application.admin_api.operator_spot_automation_runtime import (
            bind_spot_automation_cancel_command,
            build_spot_automation_cancel_ownership,
        )
        from core.coinbase_execution_authority import (
            COINBASE_EXECUTION_SCOPE_SPOT_CANCEL,
        )

        command_service = self._resolve_spot_command_service()
        profile_coordinator = self._resolve_spot_profile_coordinator(
            command_service
        )
        configured_portfolio_id = str(
            os.environ.get("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID") or ""
        ).strip()
        if not configured_portfolio_id:
            raise AutomationRepositoryUnavailable(
                "automation_spot_portfolio_not_configured"
            )
        cycles = self._call(
            lambda: self.repository.list_spot_eligibility_cycles(
                goal_key=spot_goal_key
            )
        )
        cycle_matches = tuple(
            cycle
            for cycle in cycles
            if str(cycle.run_id) == run_id
            and int(cycle.cycle_number) == execution.eligibility_cycle
        )
        if len(cycle_matches) != 1:
            raise AutomationRepositoryUnavailable(
                "automation_spot_safe_closeout_eligibility_missing"
            )
        attempts = self._call(
            lambda: self.repository.list_spot_eligibility_attempts(
                run_id,
                cycle_number=execution.eligibility_cycle,
            )
        )

        with profile_coordinator.claim(configured_portfolio_id) as lease:
            try:
                ownership = build_spot_automation_cancel_ownership(
                    run=record,
                    plan=plan,
                    execution=execution,
                    eligibility_cycle=cycle_matches[0],
                    attempts=attempts,
                    lease=lease,
                    configured_portfolio_id=configured_portfolio_id,
                    now=self._now_factory(),
                    goal_key=spot_goal_key,
                )
                prepared = prepare_spot_automation_cancel_command(
                    run=record,
                    plan=plan,
                    client_order_id=execution.client_order_id,
                    actor_id=context.actor_id,
                    roles=context.roles,
                    correlation_id=context.correlation_id,
                    operator_intent=context.operator_intent,
                    outer_idempotency_key=context.idempotency_key,
                    reason=str(request.get("reason") or ""),
                )
                proof_chain = self._record_spot_proof_chain(
                    proof_context=prepared.proof_context,
                    command_kind="cancel",
                    roles=context.roles,
                    wallet_available_notional_usdc=Decimal("0"),
                )
                self._evaluate_spot_live_admission(
                    proof_context=prepared.proof_context,
                    proof_chain=proof_chain,
                )
                command = bind_spot_automation_cancel_command(
                    prepared=prepared,
                    proof_chain=proof_chain,
                )
            except AutomationRepositoryConflict:
                raise
            except Exception:
                raise AutomationRepositoryConflict(
                    "automation_spot_safe_closeout_admission_failed"
                ) from None

            started = self._call(
                lambda: self.repository.start_spot_cancel_invocation(
                    run_id,
                    client_order_id=execution.client_order_id,
                    command=self._spot_invocation_start_command(
                        context=context,
                        request=request,
                        run_id=run_id,
                        eligibility_cycle=execution.eligibility_cycle,
                        plan_sha256=plan.plan_sha256,
                        client_order_id=execution.client_order_id,
                        command_payload_sha256=prepared.proof_context[
                            "payload_hash"
                        ],
                        operation="start_automation_spot_safe_closeout",
                        phase="cancel-start",
                        operator_intent=(
                            "claim_automation_spot_exact_child_safe_closeout"
                        ),
                    ),
                )
            )
            if not self._spot_execution_binding_matches(
                started.entity,
                record=record,
                plan=plan,
                goal_key=spot_goal_key,
                eligibility_cycle=execution.eligibility_cycle,
                client_order_id=execution.client_order_id,
                require_cancel_allowance=True,
            ):
                raise AutomationRepositoryUnavailable(
                    "automation_spot_cancel_claim_invalid"
                )
            if started.replayed:
                current = self._call(lambda: self.repository.get_run(run_id))
                if current is None:
                    raise AutomationRepositoryUnavailable(
                        "automation_spot_execution_replay_unavailable"
                    )
                return AutomationRepositoryMutation(
                    entity=self._run(current),
                    audit_id=started.audit_id,
                    correlation_id=started.correlation_id,
                    replayed=True,
                    activity=AutomationRunMutationActivity(),
                )
            try:
                with self._resolve_spot_execution_scope_factory()(
                    COINBASE_EXECUTION_SCOPE_SPOT_CANCEL
                ):
                    response = command_service.cancel_order_by_client_order_id(
                        command,
                        automation_ownership=ownership,
                    )
                if response.client_order_id != execution.client_order_id:
                    raise RuntimeError(
                        "automation_spot_cancel_response_identity_mismatch"
                    )
                classification = (
                    classify_canonical_spot_automation_cancel_response(
                        response
                    )
                )
            except Exception:
                classification = OperatorSpotAutomationExecutionClassification(
                    operation=OperatorSpotAutomationExecutionOperation.CANCEL,
                    outcome=OperatorSpotAutomationExecutionOutcome.UNKNOWN,
                    child_terminal=None,
                    mutation_call_count=None,
                    mutation_call_count_exact=False,
                    read_call_count=None,
                    read_call_count_exact=False,
                )

            finalize_payload = {
                "operation": "finalize_automation_spot_safe_closeout",
                "run_id": run_id,
                "plan_sha256": plan.plan_sha256,
                "client_order_id": execution.client_order_id,
                "outcome": classification.outcome.value,
                "mutation_call_count": classification.mutation_call_count,
                "mutation_call_count_exact": (
                    classification.mutation_call_count_exact
                ),
                "read_call_count": classification.read_call_count,
                "read_call_count_exact": (
                    classification.read_call_count_exact
                ),
                "child_terminal": classification.child_terminal,
            }
            finalized = self._call(
                lambda: self.repository.finalize_spot_cancel_invocation(
                    run_id,
                    outcome=classification.outcome.value,
                    child_terminal=(
                        False
                        if classification.outcome
                        is OperatorSpotAutomationExecutionOutcome.REJECTED
                        else classification.child_terminal
                    ),
                    coinbase_api_call_count=(
                        classification.mutation_call_count
                    ),
                    call_count_exact=(
                        classification.mutation_call_count_exact
                    ),
                    read_call_count=classification.read_call_count,
                    read_call_count_exact=(
                        classification.read_call_count_exact
                    ),
                    command=self._command(
                        context=context,
                        idempotency_key=derive_spot_automation_phase_key(
                            outer_idempotency_key=context.idempotency_key,
                            run_id=run_id,
                            plan_sha256=plan.plan_sha256,
                            phase="cancel-finalize",
                        ),
                        operator_intent=(
                            "finalize_automation_spot_exact_child_safe_closeout"
                        ),
                        payload=finalize_payload,
                    ),
                )
            )
            current = self._call(lambda: self.repository.get_run(run_id))
            if current is None:
                raise AutomationRepositoryUnavailable(
                    "automation_spot_safe_closeout_result_unavailable"
                )
            return AutomationRepositoryMutation(
                entity=self._run(current),
                audit_id=finalized.audit_id,
                correlation_id=finalized.correlation_id,
                replayed=False,
                activity=self._activity_from_classification(
                    classification,
                    operation="SAFE_CLOSEOUT",
                ),
            )

    def refresh_spot_eligibility(
        self,
        *,
        run_id: str,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationEligibilityRepositoryMutation:
        """Run one exact eight-category cycle with bounded call accounting."""

        self._require_active_control_posture()
        record = self._call(lambda: self.repository.get_run(run_id))
        if record is None:
            raise AutomationRepositoryNotFound(AUTOMATION_NOT_FOUND)
        if (
            record.job_kind is not AutomationJobKind.SPOT_CAMPAIGN
            or record.definition_revision is None
            or record.live_attempt_consumed
        ):
            raise AutomationRepositoryConflict(
                "automation_spot_eligibility_run_ineligible"
            )
        plan = self._call(
            lambda: self.repository.get_spot_single_child_plan(
                record.definition_id,
                record.definition_revision,
            )
        )
        if plan is None:
            raise AutomationRepositoryConflict(
                "automation_single_child_plan_missing"
            )
        if request.get("expected_plan_sha256") != plan.plan_sha256:
            raise AutomationRepositoryConflict(
                "automation_single_child_plan_mismatch"
            )
        from application.admin_api.operator_spot_eligibility import (
            SpotEligibilityCoordinator,
            SpotEligibilityCoordinatorConflict,
            SpotEligibilityRunContext,
        )
        from application.admin_api.operator_spot_eligibility_postgres import (
            PostgresSpotEligibilityLedger,
        )

        run_context = SpotEligibilityRunContext(
            run_id=str(record.run_id),
            definition_id=str(record.definition_id),
            definition_revision=int(record.definition_revision),
            plan_sha256=plan.plan_sha256,
            portfolio_id_sha256=plan.portfolio_id_sha256,
            correlation_id=context.correlation_id,
            goal_key=self._call(
                lambda: self.repository.get_spot_goal_key_for_run(
                    record.run_id
                )
            ),
        )
        def build_reader() -> Any:
            if self._spot_eligibility_reader_factory is None:
                raise RuntimeError(
                    "automation_spot_eligibility_reader_unavailable"
                )
            return self._spot_eligibility_reader_factory(
                expected_context=run_context,
                plan=self._spot_plan_terms(plan, goal_key=run_context.goal_key),
            )
        ledger = PostgresSpotEligibilityLedger(
            repository=self.repository,
            mutation_context=context,
            request_payload=request,
        )
        try:
            cycle_result = self._call(
                lambda: SpotEligibilityCoordinator(
                    ledger=ledger,
                    reader_factory=build_reader,
                ).run(run_context)
            )
        except SpotEligibilityCoordinatorConflict as exc:
            raise AutomationRepositoryConflict(exc.code) from None

        current = self._call(lambda: self.repository.get_run(run_id))
        if current is None:
            raise AutomationRepositoryUnavailable(
                "automation_spot_eligibility_result_unavailable"
            )
        closeout = self._close_exhausted_preliminary_eligibility(
            record=current,
            cycle_number=cycle_result.cycle_number,
            goal_key=run_context.goal_key,
            plan_sha256=plan.plan_sha256,
            context=context,
        )
        if closeout is not None:
            current = closeout.entity
        cycles = self._call(
            lambda: self.repository.list_spot_eligibility_cycles(
                goal_key=run_context.goal_key
            )
        )
        matches = tuple(
            cycle
            for cycle in cycles
            if str(cycle.run_id) == run_id
            and int(cycle.cycle_number) == cycle_result.cycle_number
        )
        open_cycles = tuple(
            cycle
            for cycle in cycles
            if cycle.state == "OPEN"
        )
        terminal_result_applied = bool(
            (
                cycle_result.outcome.value == "SUCCEEDED"
                and current.state
                is AutomationRunState.AWAITING_OPERATOR_AUTHORIZATION
                and current.diagnostic_code == "awaiting_operator_authorization"
            )
            or (
                cycle_result.outcome.value in {"REJECTED", "UNKNOWN"}
                and current.state is AutomationRunState.BLOCKED
                and current.diagnostic_code
                == "automation_spot_eligibility_refresh_required"
            )
        )
        terminal_result_during_newer_cycle = bool(
            current.state is AutomationRunState.PREPARING
            and current.diagnostic_code
            in {
                "automation_spot_source_gate_resumed",
                "automation_spot_final_admission_started",
            }
            and len(open_cycles) == 1
            and str(open_cycles[0].run_id) == run_id
            and int(open_cycles[0].cycle_number) > cycle_result.cycle_number
            and open_cycles[0].plan_sha256 == plan.plan_sha256
        )
        terminal_exhaustion_applied = bool(
            cycle_result.cycle_number == 10
            and cycle_result.outcome.value == "SUCCEEDED"
            and run_context.goal_key in _SPOT_PREVIEW_GOAL_KEYS
            and current.state is AutomationRunState.BLOCKED
            and current.diagnostic_code == "automation_run_blocked"
        )
        if (
            len(matches) != 1
            or matches[0].state != cycle_result.outcome.value
            or not (
                terminal_result_applied
                or terminal_result_during_newer_cycle
                or terminal_exhaustion_applied
            )
        ):
            raise AutomationRepositoryUnavailable(
                "automation_spot_eligibility_result_unavailable"
            )
        cycle = matches[0]
        return AutomationEligibilityRepositoryMutation(
            entity=self._run(
                current,
                eligibility_cycle_number=cycle_result.cycle_number,
            ),
            audit_id=(
                current.audit_id
                if terminal_exhaustion_applied
                else cycle.audit_id
            ),
            correlation_id=(
                current.correlation_id
                if terminal_exhaustion_applied
                else cycle.correlation_id
            ),
            replayed=cycle_result.replayed,
            coinbase_api_call_count=cycle_result.coinbase_api_call_count,
            call_count_exact=cycle_result.call_count_exact,
        )

    def resume_spot_source_gated_run(
        self,
        *,
        run_id: str,
        expected_plan_sha256: str,
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation:
        """Expose a repository-only continuation primitive to future wiring."""

        command = self._command(
            context=context,
            payload={
                "operation": "resume_automation_spot_source_gated_run",
                "run_id": run_id,
                "expected_plan_sha256": expected_plan_sha256,
            },
        )
        result = self._call(
            lambda: self.repository.resume_spot_source_gated_run(
                run_id,
                expected_plan_sha256=expected_plan_sha256,
                command=command,
            )
        )
        entity = getattr(result.entity, "run", result.entity)
        return AutomationRepositoryMutation(
            entity=self._run(entity),
            audit_id=result.audit_id,
            correlation_id=result.correlation_id,
            replayed=result.replayed,
        )

    def list_runs(
        self,
        *,
        definition_id: str | None,
        state: str | None,
        limit: int,
        offset: int,
    ) -> AutomationRepositoryPage:
        page = self._call(
            lambda: self.repository.list_runs(
                definition_id=definition_id,
                state=AutomationRunState(state) if state is not None else None,
                limit=limit,
                offset=offset,
            )
        )
        return AutomationRepositoryPage(
            items=tuple(self._run(item) for item in page.items),
            total_count=page.total_count,
        )

    def get_run(self, run_id: str) -> Mapping[str, Any] | None:
        record = self._call(lambda: self.repository.get_run(run_id))
        return self._run(record) if record is not None else None

    def list_run_events(
        self,
        *,
        run_id: str,
        limit: int,
        offset: int,
    ) -> AutomationRepositoryPage:
        page = self._call(
            lambda: self.repository.list_run_events(
                run_id,
                limit=limit,
                offset=offset,
            )
        )
        return AutomationRepositoryPage(
            items=tuple(self._event(item) for item in page.items),
            total_count=page.total_count,
        )

    def list_definition_events(
        self,
        *,
        definition_id: str,
        limit: int,
        offset: int,
    ) -> AutomationRepositoryPage:
        page = self._call(
            lambda: self.repository.list_definition_events(
                definition_id,
                limit=limit,
                offset=offset,
            )
        )
        return AutomationRepositoryPage(
            items=tuple(self._lifecycle_event(item) for item in page.items),
            total_count=page.total_count,
        )

    def list_control_events(
        self,
        *,
        limit: int,
        offset: int,
    ) -> AutomationRepositoryPage:
        page = self._call(
            lambda: self.repository.list_control_events(
                limit=limit,
                offset=offset,
            )
        )
        return AutomationRepositoryPage(
            items=tuple(self._lifecycle_event(item) for item in page.items),
            total_count=page.total_count,
        )


@dataclass
class OperatorAutomationError(RuntimeError):
    """Value-blind public error classification."""

    code: str
    http_status_code: int

    def __str__(self) -> str:
        return self.code


def _pagination(*, page: AutomationRepositoryPage, limit: int, offset: int) -> AutomationPagination:
    if type(page.total_count) is not int or page.total_count < 0:
        raise ValueError("automation_repository_total_invalid")
    count = len(page.items)
    page_end = offset + count
    if count > limit or page.total_count < page_end:
        raise ValueError("automation_repository_page_invalid")
    has_more = page_end < page.total_count
    if has_more and count != limit:
        raise ValueError("automation_repository_partial_page_invalid")
    return AutomationPagination(
        limit=limit,
        offset=offset,
        returned_count=count,
        total_matching_count=page.total_count,
        next_offset=page_end if has_more else None,
        has_more=has_more,
    )


class OperatorAutomationService:
    """Validate repository evidence and expose fixed, local-only contracts."""

    def __init__(self, repository: OperatorAutomationRepository) -> None:
        self.repository = repository

    @staticmethod
    def _translate_error(exc: BaseException) -> OperatorAutomationError:
        if isinstance(exc, AutomationRepositoryConflict):
            return OperatorAutomationError(exc.code, 409)
        if isinstance(exc, AutomationRepositoryNotFound):
            return OperatorAutomationError(exc.code, 404)
        if isinstance(exc, AutomationRepositoryUnavailable):
            return OperatorAutomationError(exc.code, 503)
        return OperatorAutomationError(AUTOMATION_UNAVAILABLE, 503)

    def get_control_plane(self) -> AutomationControlPlaneResponse:
        try:
            item = AutomationControlPlaneItem.model_validate(
                self.repository.get_control_posture()
            )
            return AutomationControlPlaneResponse(control_plane=item)
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def authorize_atomic_market_snapshot_candidate(
        self,
        request: AutomationAtomicMarketSnapshotAuthorizationRequest,
        context: AutomationMutationContext,
    ) -> AutomationAtomicMarketSnapshotMutationResponse:
        try:
            result = self.repository.authorize_atomic_market_snapshot_candidate(
                request=request.model_dump(mode="json"),
                context=context,
            )
            return AutomationAtomicMarketSnapshotMutationResponse(
                **result.entity,
                replayed=result.replayed,
                audit_id=result.audit_id,
                correlation_id=result.correlation_id,
                activity=(result.activity or AutomationRunMutationActivity()),
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def prepare_minimum_size_candidate(
        self,
        request: AutomationMinimumSizeCandidatePreparationRequest,
        context: AutomationMutationContext,
    ) -> AutomationMinimumSizeCandidatePreparationResponse:
        try:
            result = self.repository.prepare_minimum_size_candidate(
                request=request.model_dump(mode="json"),
                context=context,
            )
            return AutomationMinimumSizeCandidatePreparationResponse(
                **result.entity,
                replayed=result.replayed,
                audit_id=result.audit_id,
                correlation_id=result.correlation_id,
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def list_definition_events(
        self,
        *,
        definition_id: str,
        limit: int,
        offset: int,
    ) -> AutomationDefinitionEventListResponse:
        try:
            page = self.repository.list_definition_events(
                definition_id=definition_id,
                limit=limit,
                offset=offset,
            )
            items = [
                AutomationDefinitionEventItem.model_validate(item)
                for item in page.items
            ]
            return AutomationDefinitionEventListResponse(
                definition_id=definition_id,
                count=len(items),
                pagination=_pagination(page=page, limit=limit, offset=offset),
                items=items,
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def list_control_events(
        self,
        *,
        limit: int,
        offset: int,
    ) -> AutomationControlEventListResponse:
        try:
            page = self.repository.list_control_events(
                limit=limit,
                offset=offset,
            )
            items = [
                AutomationControlEventItem.model_validate(item)
                for item in page.items
            ]
            return AutomationControlEventListResponse(
                count=len(items),
                pagination=_pagination(page=page, limit=limit, offset=offset),
                items=items,
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def list_definitions(
        self,
        *,
        domain: AutomationDomain | None,
        job_kind: AutomationJobKind | None,
        lifecycle_state: AutomationDefinitionState | None,
        limit: int,
        offset: int,
    ) -> AutomationDefinitionListResponse:
        try:
            if domain is not None and job_kind is not None:
                if domain is not domain_for_job_kind(job_kind):
                    raise OperatorAutomationError(
                        "automation_filter_domain_kind_mismatch",
                        422,
                    )
            page = self.repository.list_definitions(
                domain=domain.value if domain is not None else None,
                job_kind=job_kind.value if job_kind is not None else None,
                lifecycle_state=(
                    lifecycle_state.value if lifecycle_state is not None else None
                ),
                limit=limit,
                offset=offset,
            )
            items = [AutomationDefinitionItem.model_validate(item) for item in page.items]
            return AutomationDefinitionListResponse(
                filters=AutomationFilters(
                    domain=domain,
                    job_kind=job_kind,
                    lifecycle_state=lifecycle_state,
                    limit=limit,
                    offset=offset,
                ),
                count=len(items),
                pagination=_pagination(page=page, limit=limit, offset=offset),
                items=items,
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def get_definition(self, definition_id: str) -> AutomationDefinitionDetailResponse:
        try:
            record = self.repository.get_definition(definition_id)
            if record is None:
                raise OperatorAutomationError(AUTOMATION_NOT_FOUND, 404)
            return AutomationDefinitionDetailResponse(
                definition=AutomationDefinitionItem.model_validate(record)
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def create_definition(
        self,
        request: AutomationDefinitionCreateRequest,
        context: AutomationMutationContext,
    ) -> AutomationDefinitionMutationResponse:
        definition = request.model_dump(mode="json")
        definition["domain"] = domain_for_job_kind(request.job_kind).value
        return self._definition_mutation(
            lambda: self.repository.create_definition(
                definition=definition,
                context=context,
            )
        )

    def prepare_near_market_candidate(
        self,
        request: AutomationNearMarketCandidatePreparationRequest,
        context: AutomationMutationContext,
    ) -> AutomationNearMarketCandidatePreparationResponse:
        try:
            result = self.repository.prepare_near_market_candidate(
                request=request.model_dump(mode="json"),
                context=context,
            )
            return AutomationNearMarketCandidatePreparationResponse(
                **result.entity,
                replayed=result.replayed,
                audit_id=result.audit_id,
                correlation_id=result.correlation_id,
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def transition_definition(
        self,
        *,
        definition_id: str,
        action: AutomationDefinitionLifecycleAction,
        request: AutomationDefinitionLifecycleRequest,
        context: AutomationMutationContext,
    ) -> AutomationDefinitionMutationResponse:
        return self._definition_mutation(
            lambda: self.repository.transition_definition(
                definition_id=definition_id,
                action=action,
                request=request.model_dump(mode="json"),
                context=context,
            )
        )

    def set_definition_schedule(
        self,
        *,
        definition_id: str,
        request: AutomationDefinitionScheduleRequest,
        context: AutomationMutationContext,
    ) -> AutomationDefinitionMutationResponse:
        return self._definition_mutation(
            lambda: self.repository.set_schedule(
                definition_id=definition_id,
                schedule=request.model_dump(mode="json"),
                context=context,
            )
        )

    def clear_definition_schedule(
        self,
        *,
        definition_id: str,
        request: AutomationDefinitionLifecycleRequest,
        context: AutomationMutationContext,
    ) -> AutomationDefinitionMutationResponse:
        return self._definition_mutation(
            lambda: self.repository.clear_schedule(
                definition_id=definition_id,
                request=request.model_dump(mode="json"),
                context=context,
            )
        )

    def transition_control_posture(
        self,
        *,
        action: AutomationControlAction,
        request: AutomationControlRequest | Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationControlMutationResponse:
        validated_request = AutomationControlRequest.model_validate(request)
        try:
            result = self.repository.transition_control_posture(
                action=action,
                request=validated_request.model_dump(mode="json"),
                context=context,
            )
            return AutomationControlMutationResponse(
                control_plane=AutomationControlPlaneItem.model_validate(result.entity),
                replayed=result.replayed,
                audit_id=result.audit_id,
                correlation_id=result.correlation_id,
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def claim_one_shot_run(
        self,
        *,
        definition_id: str,
        request: AutomationOneShotRunRequest,
        context: AutomationMutationContext,
    ) -> AutomationRunMutationResponse:
        try:
            result = self.repository.claim_one_shot_run(
                definition_id=definition_id,
                request=request.model_dump(mode="json"),
                context=context,
            )
            return AutomationRunMutationResponse(
                run=AutomationRunItem.model_validate(result.entity),
                replayed=result.replayed,
                audit_id=result.audit_id,
                correlation_id=result.correlation_id,
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def authorize_single_child(
        self,
        *,
        run_id: str,
        request: AutomationSingleChildAuthorizationRequest,
        context: AutomationMutationContext,
    ) -> AutomationRunMutationResponse:
        try:
            result = self.repository.authorize_single_child(
                run_id=run_id,
                request=request.model_dump(mode="json"),
                context=context,
            )
            run = AutomationRunItem.model_validate(result.entity)
            return AutomationRunMutationResponse(
                run=run,
                replayed=result.replayed,
                audit_id=result.audit_id,
                correlation_id=result.correlation_id,
                activity=(
                    result.activity
                    or self._run_mutation_activity(
                        run=run,
                        replayed=result.replayed,
                        operation="CREATE",
                    )
                ),
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def authorize_preview_gated_single_child(
        self,
        *,
        run_id: str,
        request: AutomationPreviewGatedSingleChildAuthorizationRequest,
        context: AutomationMutationContext,
    ) -> AutomationRunMutationResponse:
        try:
            result = self.repository.authorize_preview_gated_single_child(
                run_id=run_id,
                request=request.model_dump(mode="json"),
                context=context,
            )
            run = AutomationRunItem.model_validate(result.entity)
            return AutomationRunMutationResponse(
                run=run,
                replayed=result.replayed,
                audit_id=result.audit_id,
                correlation_id=result.correlation_id,
                activity=(
                    result.activity
                    or self._run_mutation_activity(
                        run=run,
                        replayed=result.replayed,
                        operation="PREVIEW_GATED_CREATE",
                    )
                ),
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def safe_closeout_single_child(
        self,
        *,
        run_id: str,
        request: AutomationSingleChildSafeCloseoutRequest,
        context: AutomationMutationContext,
    ) -> AutomationRunMutationResponse:
        try:
            result = self.repository.safe_closeout_single_child(
                run_id=run_id,
                request=request.model_dump(mode="json"),
                context=context,
            )
            run = AutomationRunItem.model_validate(result.entity)
            return AutomationRunMutationResponse(
                run=run,
                replayed=result.replayed,
                audit_id=result.audit_id,
                correlation_id=result.correlation_id,
                activity=(
                    result.activity
                    or self._run_mutation_activity(
                        run=run,
                        replayed=result.replayed,
                        operation="SAFE_CLOSEOUT",
                    )
                ),
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def refresh_spot_eligibility(
        self,
        *,
        run_id: str,
        request: AutomationEligibilityRefreshRequest,
        context: AutomationMutationContext,
    ) -> AutomationEligibilityCycleMutationResponse:
        try:
            result = self.repository.refresh_spot_eligibility(
                run_id=run_id,
                request=request.model_dump(mode="json"),
                context=context,
            )
            return AutomationEligibilityCycleMutationResponse(
                run=AutomationRunItem.model_validate(result.entity),
                replayed=result.replayed,
                audit_id=result.audit_id,
                correlation_id=result.correlation_id,
                activity=AutomationEligibilityRefreshActivity(
                    coinbase_api_call_count=(
                        0 if result.replayed else result.coinbase_api_call_count
                    ),
                    call_count_exact=(
                        True if result.replayed else result.call_count_exact
                    ),
                ),
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    @staticmethod
    def _run_mutation_activity(
        *,
        run: AutomationRunItem,
        replayed: bool,
        operation: str,
    ) -> AutomationRunMutationActivity:
        if replayed:
            return AutomationRunMutationActivity()

        preview_count = (
            run.preview_call_count
            if operation == "PREVIEW_GATED_CREATE"
            else 0
        )
        create_count = (
            run.create_call_count
            if operation in {"CREATE", "PREVIEW_GATED_CREATE"}
            else 0
        )
        cancel_count = (
            run.cancel_call_count if operation == "SAFE_CLOSEOUT" else 0
        )
        if operation in {"CREATE", "PREVIEW_GATED_CREATE"}:
            read_count = run.reconciliation_call_count
        else:
            read_count = (
                None
                if run.reconciliation_call_count is None
                else max(run.reconciliation_call_count - 1, 0)
            )
        if run.call_count_exact:
            exchange_count = (
                None
                if create_count is None or cancel_count is None
                else create_count + cancel_count
            )
            total_count = (
                None
                if exchange_count is None
                or read_count is None
                or preview_count is None
                else exchange_count + read_count + preview_count
            )
            return AutomationRunMutationActivity(
                operation=operation,
                coinbase_api_call_count=total_count,
                preview_call_count=preview_count,
                read_call_count=read_count,
                exchange_mutation_count=exchange_count,
                create_call_count=create_count,
                cancel_call_count=cancel_count,
                call_count_exact=True,
            )

        exchange_count = (
            None
            if create_count is None or cancel_count is None
            else create_count + cancel_count
        )
        return AutomationRunMutationActivity(
            operation=operation,
            coinbase_api_call_count=None,
            preview_call_count=preview_count,
            read_call_count=read_count,
            exchange_mutation_count=exchange_count,
            create_call_count=create_count,
            cancel_call_count=cancel_count,
            call_count_exact=False,
        )

    def list_runs(
        self,
        *,
        definition_id: str | None,
        state: AutomationRunState | None,
        limit: int,
        offset: int,
    ) -> AutomationRunListResponse:
        try:
            page = self.repository.list_runs(
                definition_id=definition_id,
                state=state.value if state is not None else None,
                limit=limit,
                offset=offset,
            )
            items = [AutomationRunItem.model_validate(item) for item in page.items]
            return AutomationRunListResponse(
                filters=AutomationRunFilters(
                    definition_id=definition_id,
                    state=state,
                    limit=limit,
                    offset=offset,
                ),
                count=len(items),
                pagination=_pagination(page=page, limit=limit, offset=offset),
                items=items,
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def get_run(self, run_id: str) -> AutomationRunDetailResponse:
        try:
            record = self.repository.get_run(run_id)
            if record is None:
                raise OperatorAutomationError(AUTOMATION_NOT_FOUND, 404)
            return AutomationRunDetailResponse(run=AutomationRunItem.model_validate(record))
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def list_run_events(
        self,
        *,
        run_id: str,
        limit: int,
        offset: int,
    ) -> AutomationRunEventListResponse:
        try:
            page = self.repository.list_run_events(
                run_id=run_id,
                limit=limit,
                offset=offset,
            )
            items = [AutomationRunEventItem.model_validate(item) for item in page.items]
            if any(
                item.from_state is None
                and item.diagnostic_code
                == "automation_spot_preview_invocation_started"
                for item in items
            ):
                run = self.repository.get_run(run_id)
                if (
                    run is None
                    or AutomationRunItem.model_validate(run).spot_execution_mode
                    not in _SPOT_ATOMIC_MARKET_SNAPSHOT_MODES
                ):
                    raise AutomationRepositoryUnavailable(
                        "automation_run_event_atomic_genesis_invalid"
                    )
            return AutomationRunEventListResponse(
                run_id=run_id,
                count=len(items),
                pagination=_pagination(page=page, limit=limit, offset=offset),
                items=items,
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def _definition_mutation(self, operation: Any) -> AutomationDefinitionMutationResponse:
        try:
            result = operation()
            return AutomationDefinitionMutationResponse(
                definition=AutomationDefinitionItem.model_validate(result.entity),
                replayed=result.replayed,
                audit_id=result.audit_id,
                correlation_id=result.correlation_id,
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None


def _default_spot_eligibility_reader_factory(
    *,
    expected_context: Any,
    plan: Any,
) -> Any:
    """Resolve the canonical client only for an explicit refresh mutation."""

    from application.admin_api.operator_spot_eligibility_reader import (
        CoinbaseApprovedSpotEligibilityReader,
    )
    from configuration import REST_CLIENT

    portfolio_id = str(
        os.environ.get("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID") or ""
    ).strip()
    return CoinbaseApprovedSpotEligibilityReader(
        rest_client=REST_CLIENT,
        expected_context=expected_context,
        approved_portfolio_id=portfolio_id,
        approved_portfolio_label="Test",
        plan=plan,
    )


def _default_near_market_preparation_runner() -> Any:
    """Run exactly one claimed six-category preparation read without retry."""

    from application.admin_api.operator_spot_near_market_preparation import (
        run_near_market_candidate_preparation,
    )
    from configuration import REST_CLIENT

    portfolio_id = str(
        os.environ.get("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID") or ""
    ).strip()
    return run_near_market_candidate_preparation(
        rest_client=REST_CLIENT,
        approved_portfolio_id=portfolio_id,
        approved_portfolio_label="Test",
        now_factory=lambda: datetime.now(timezone.utc),
    )


def _default_minimum_size_preparation_runner() -> Any:
    """Run exactly one claimed six-category V7-V9 read without retry."""

    from application.admin_api.operator_spot_minimum_size_preparation import (
        run_minimum_size_candidate_preparation,
    )
    from configuration import REST_CLIENT

    portfolio_id = str(
        os.environ.get("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID") or ""
    ).strip()
    return run_minimum_size_candidate_preparation(
        rest_client=REST_CLIENT,
        approved_portfolio_id=portfolio_id,
        approved_portfolio_label="Test",
        now_factory=lambda: datetime.now(timezone.utc),
    )


def get_default_operator_automation_service() -> OperatorAutomationService:
    """Resolve the PostgreSQL repository lazily to keep imports local-only."""

    try:
        from database.operator_automation import (
            get_default_operator_automation_repository,
        )

        repository = get_default_operator_automation_repository()
        return OperatorAutomationService(
            PostgresOperatorAutomationRepositoryAdapter(
                repository,
                spot_eligibility_reader_factory=(
                    _default_spot_eligibility_reader_factory
                ),
                spot_near_market_preparation_runner=(
                    _default_near_market_preparation_runner
                ),
                spot_minimum_size_preparation_runner=(
                    _default_minimum_size_preparation_runner
                ),
            )
        )
    except Exception:
        raise OperatorAutomationError(AUTOMATION_UNAVAILABLE, 503) from None
