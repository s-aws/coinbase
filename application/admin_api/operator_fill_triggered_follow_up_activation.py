"""Durable controls and exactly-once dispatch for one attached follow-up intent.

This application boundary never accepts child order terms from the browser.
Control commands only arm or disarm an existing backend-owned intent.  A
separate full-fill dispatcher may invoke the canonical materialization service
after the PostgreSQL repository returns the sole durable trigger claim.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from enum import Enum
import os
import re
import threading
from typing import Any, Callable, Protocol

from application.admin_api.operator_follow_up_materialization import (
    MaterializationAuthorization,
    OperatorFollowUpMaterializationError,
    OperatorFollowUpMaterializationRequestContext,
)


FILL_TRIGGERED_FOLLOW_UP_GOAL_ID = (
    "operator_fill_triggered_follow_up_activation_v1"
)
CONTROL_FILL_TRIGGERED_FOLLOW_UP = "control_fill_triggered_follow_up"
MATERIALIZE_ENABLED_FILL_TRIGGERED_FOLLOW_UP = (
    "materialize_enabled_fill_triggered_follow_up"
)
SAFE_CLOSEOUT_FILL_TRIGGERED_FOLLOW_UP = (
    "safe_closeout_fill_triggered_follow_up"
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class FillTriggeredActivationControlState(str, Enum):
    DISABLED = "DISABLED"
    ENABLED = "ENABLED"
    PAUSED = "PAUSED"
    DRAINING = "DRAINING"
    DRAINED = "DRAINED"


class FillTriggeredActivationTriggerState(str, Enum):
    UNCLAIMED = "UNCLAIMED"
    CLAIMED = "CLAIMED"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"

    @property
    def is_claimed(self) -> bool:
        return self is not FillTriggeredActivationTriggerState.UNCLAIMED

    @property
    def is_terminal(self) -> bool:
        return self in {
            FillTriggeredActivationTriggerState.COMPLETED,
            FillTriggeredActivationTriggerState.BLOCKED,
            FillTriggeredActivationTriggerState.UNKNOWN,
        }


class FillTriggeredActivationControlAction(str, Enum):
    ENABLE = "ENABLE"
    DISABLE = "DISABLE"
    PAUSE = "PAUSE"
    DRAIN = "DRAIN"


@dataclass(frozen=True, slots=True)
class FillTriggeredActivationRecord:
    goal_id: str
    source_client_order_id: str
    follow_up_intent_id: str
    control_state: FillTriggeredActivationControlState
    trigger_state: FillTriggeredActivationTriggerState
    revision: int
    delegated_create_authority: bool
    trigger_claim_id: str | None
    trigger_evidence_sha256: str | None
    materialization_state: str | None
    child_client_order_id: str | None
    diagnostic_code: str
    actor_id: str
    roles: tuple[str, ...]
    correlation_id: str
    audit_id: str
    recorded_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class FillTriggeredActivationRequestContext:
    actor_id: str
    roles: tuple[str, ...]
    idempotency_key: str
    correlation_id: str
    audit_id: str
    operator_intent: str


class FillTriggeredActivationRepository(Protocol):
    def read(
        self,
        source_client_order_id: str,
    ) -> FillTriggeredActivationRecord: ...

    def transition_control(self, **kwargs: Any) -> FillTriggeredActivationRecord: ...

    def claim_full_fill_trigger(
        self,
        **kwargs: Any,
    ) -> FillTriggeredActivationRecord | None: ...

    def finalize_trigger(self, **kwargs: Any) -> FillTriggeredActivationRecord: ...


class FillTriggeredFollowUpActivationError(RuntimeError):
    """Fixed value-blind application error."""

    def __init__(self, code: str, http_status_code: int) -> None:
        self.code = str(code)
        self.http_status_code = int(http_status_code)
        super().__init__(self.code)


def _required_text(value: object, *, code: str, maximum: int = 255) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > maximum:
        raise FillTriggeredFollowUpActivationError(code, 422)
    return normalized


def _validate_record(
    record: FillTriggeredActivationRecord,
    *,
    source_client_order_id: str,
) -> FillTriggeredActivationRecord:
    if (
        not isinstance(record, FillTriggeredActivationRecord)
        or record.goal_id != FILL_TRIGGERED_FOLLOW_UP_GOAL_ID
        or record.source_client_order_id != source_client_order_id
        or not record.follow_up_intent_id
        or type(record.revision) is not int
        or record.revision < 0
        or (
            record.trigger_state.is_claimed
            and (
                not record.trigger_claim_id
                or not _SHA256_RE.fullmatch(
                    str(record.trigger_evidence_sha256 or "")
                )
            )
            or (
                record.control_state
                is FillTriggeredActivationControlState.ENABLED
                and record.delegated_create_authority is not True
            )
        )
    ):
        raise FillTriggeredFollowUpActivationError(
            "fill_triggered_follow_up_record_invalid",
            503,
        )
    return record


def _materialization_result_fields(
    value: object,
) -> tuple[str, str | None, str]:
    if isinstance(value, dict):
        state = str(value.get("materialization_state") or "").strip()
        child_id = str(value.get("child_client_order_id") or "").strip() or None
        diagnostic = str(value.get("diagnostic_code") or "").strip()
    else:
        attempt = getattr(value, "attempt", None)
        state = str(
            getattr(attempt, "current_state", None)
            or getattr(value, "materialization_state", "")
        ).strip()
        child_id = str(
            getattr(value, "child_client_order_id", None)
            or getattr(attempt, "child_client_order_id", "")
        ).strip() or None
        diagnostic = str(
            getattr(value, "message", None)
            or getattr(value, "diagnostic_code", "")
        ).strip()
    if not state or not diagnostic:
        raise FillTriggeredFollowUpActivationError(
            "fill_triggered_follow_up_materialization_invalid",
            503,
        )
    return state, child_id, diagnostic


def _project_canonical_materialization_attempt(
    attempt: object,
) -> tuple[
    str,
    str | None,
    str,
    FillTriggeredActivationTriggerState,
]:
    state = str(getattr(attempt, "current_state", "") or "").upper()
    child_id = str(
        getattr(attempt, "child_client_order_id", "") or ""
    ).strip() or None
    if state in {
        "CREATE_ACCEPTED",
        "CREATE_ACCEPTED_NONTERMINAL",
        "CREATE_ACCEPTED_TERMINAL",
        "CANCEL_INVOCATION_STARTED",
        "CANCEL_ACCEPTED_NONTERMINAL",
        "CANCEL_ACCEPTED_TERMINAL",
        "CANCEL_EXPLICITLY_REJECTED",
        "CANCEL_UNKNOWN_CONSUMED",
        "CHILD_ALREADY_TERMINAL",
        "CHILD_ALREADY_TERMINAL_NO_CANCEL",
    }:
        return (
            state,
            child_id,
            "fill_triggered_follow_up_create_accepted",
            FillTriggeredActivationTriggerState.COMPLETED,
        )
    if state in {
        "KNOWN_NOT_INVOKED",
        "PREPARED",
        "CREATE_REJECTED",
        "CREATE_EXPLICITLY_REJECTED",
    }:
        return (
            state,
            child_id,
            "fill_triggered_follow_up_materialization_blocked",
            FillTriggeredActivationTriggerState.BLOCKED,
        )
    return (
        state or "UNKNOWN",
        child_id,
        "fill_triggered_follow_up_outcome_unknown",
        FillTriggeredActivationTriggerState.UNKNOWN,
    )


class GoalBoundFillTriggeredFollowUpMaterializer:
    """Adapt one durable trigger claim to the canonical materialization kernel."""

    def __init__(
        self,
        *,
        kernel_service: Any,
        environment: str,
        invocation_guard_already_held: bool = False,
    ) -> None:
        self.kernel_service = kernel_service
        self.invocation_guard_already_held = invocation_guard_already_held
        self.environment = _required_text(
            environment,
            code="fill_triggered_follow_up_environment_invalid",
            maximum=64,
        )

    def materialize(
        self,
        *,
        source_client_order_id: str,
        activation: FillTriggeredActivationRecord,
    ) -> dict[str, str | None]:
        source_id = _required_text(
            source_client_order_id,
            code="fill_triggered_follow_up_source_invalid",
            maximum=128,
        )
        activation = _validate_record(
            activation,
            source_client_order_id=source_id,
        )
        if (
            activation.control_state
            is not FillTriggeredActivationControlState.ENABLED
            or activation.delegated_create_authority is not True
            or activation.trigger_state
            is not FillTriggeredActivationTriggerState.CLAIMED
            or not activation.trigger_claim_id
        ):
            raise FillTriggeredFollowUpActivationError(
                "fill_triggered_follow_up_claim_invalid",
                503,
            )
        materialize = (
            self.kernel_service.materialize_under_existing_invocation_guard
            if self.invocation_guard_already_held
            else self.kernel_service.materialize
        )
        result = materialize(
            source_client_order_id=source_id,
            request=MaterializationAuthorization(
                authorize_materialization_of_attached_intent=True,
                acknowledge_unknown_outcome_consumes_create_allowance=True,
                acknowledge_child_terms_are_backend_derived=True,
            ),
            context=OperatorFollowUpMaterializationRequestContext(
                actor_id=activation.actor_id,
                roles=activation.roles,
                idempotency_key=(
                    f"fill-triggered:{activation.trigger_claim_id}:create"
                ),
                correlation_id=activation.correlation_id,
                operator_intent=MATERIALIZE_ENABLED_FILL_TRIGGERED_FOLLOW_UP,
                audit_id=activation.audit_id,
                environment=self.environment,
            ),
        )
        record = getattr(result, "record", None)
        raw_state = getattr(record, "state", None)
        state = str(getattr(raw_state, "value", raw_state) or "").strip()
        child_id = str(
            getattr(record, "child_client_order_id", "") or ""
        ).strip()
        diagnostic = str(
            getattr(result, "diagnostic_code", "")
            or getattr(record, "diagnostic_code", "")
        ).strip()
        if not state or not child_id or not diagnostic:
            raise FillTriggeredFollowUpActivationError(
                "fill_triggered_follow_up_materialization_invalid",
                503,
            )
        return {
            "materialization_state": state,
            "child_client_order_id": child_id,
            "diagnostic_code": diagnostic,
        }


class FillTriggeredFollowUpActivationService:
    """Own control transitions and one automatic full-fill dispatch."""

    def __init__(
        self,
        *,
        repository: FillTriggeredActivationRepository,
        materializer_factory: Callable[[], Any],
        recovery_reader: Callable[[str], object | None] | None = None,
        invocation_guard_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self.repository = repository
        self.materializer_factory = materializer_factory
        self.recovery_reader = recovery_reader
        self.invocation_guard_factory = (
            invocation_guard_factory
            if invocation_guard_factory is not None
            else lambda _source_id: nullcontext()
        )

    def read(
        self,
        *,
        source_client_order_id: str,
    ) -> FillTriggeredActivationRecord:
        source_id = _required_text(
            source_client_order_id,
            code="fill_triggered_follow_up_source_invalid",
            maximum=128,
        )
        try:
            record = self.repository.read(source_id)
        except FillTriggeredFollowUpActivationError:
            raise
        except Exception:
            raise FillTriggeredFollowUpActivationError(
                "fill_triggered_follow_up_backend_unavailable",
                503,
            ) from None
        return _validate_record(record, source_client_order_id=source_id)

    def control(
        self,
        *,
        source_client_order_id: str,
        action: FillTriggeredActivationControlAction,
        expected_revision: int,
        confirm_control_action: bool,
        authorize_single_fill_triggered_materialization: bool = False,
        acknowledge_unknown_outcome_consumes_create_allowance: bool = False,
        acknowledge_child_terms_are_backend_derived: bool = False,
        context: FillTriggeredActivationRequestContext,
    ) -> FillTriggeredActivationRecord:
        source_id = _required_text(
            source_client_order_id,
            code="fill_triggered_follow_up_source_invalid",
            maximum=128,
        )
        if (
            not isinstance(action, FillTriggeredActivationControlAction)
            or type(expected_revision) is not int
            or expected_revision < 0
            or confirm_control_action is not True
            or not isinstance(context, FillTriggeredActivationRequestContext)
            or context.operator_intent != CONTROL_FILL_TRIGGERED_FOLLOW_UP
            or not {"admin", "trader"}.intersection(
                {str(role).lower() for role in context.roles}
            )
        ):
            raise FillTriggeredFollowUpActivationError(
                "fill_triggered_follow_up_control_invalid",
                422,
            )
        delegated_authority = (
            authorize_single_fill_triggered_materialization is True
            and acknowledge_unknown_outcome_consumes_create_allowance is True
            and acknowledge_child_terms_are_backend_derived is True
        )
        if (
            action is FillTriggeredActivationControlAction.ENABLE
            and not delegated_authority
        ):
            raise FillTriggeredFollowUpActivationError(
                "fill_triggered_follow_up_enable_authority_required",
                422,
            )
        if (
            action is not FillTriggeredActivationControlAction.ENABLE
            and (
                authorize_single_fill_triggered_materialization is not False
                or acknowledge_unknown_outcome_consumes_create_allowance
                is not False
                or acknowledge_child_terms_are_backend_derived is not False
            )
        ):
            raise FillTriggeredFollowUpActivationError(
                "fill_triggered_follow_up_control_authority_invalid",
                422,
            )
        _required_text(
            context.actor_id,
            code="fill_triggered_follow_up_actor_invalid",
            maximum=255,
        )
        _required_text(
            context.idempotency_key,
            code="fill_triggered_follow_up_idempotency_invalid",
            maximum=255,
        )
        _required_text(
            context.correlation_id,
            code="fill_triggered_follow_up_correlation_invalid",
            maximum=255,
        )
        _required_text(
            context.audit_id,
            code="fill_triggered_follow_up_audit_invalid",
            maximum=64,
        )
        try:
            record = self.repository.transition_control(
                source_client_order_id=source_id,
                action=action,
                expected_revision=expected_revision,
                authorize_single_fill_triggered_materialization=(
                    authorize_single_fill_triggered_materialization
                ),
                acknowledge_unknown_outcome_consumes_create_allowance=(
                    acknowledge_unknown_outcome_consumes_create_allowance
                ),
                acknowledge_child_terms_are_backend_derived=(
                    acknowledge_child_terms_are_backend_derived
                ),
                idempotency_key=context.idempotency_key,
                actor_id=context.actor_id,
                roles=context.roles,
                correlation_id=context.correlation_id,
                audit_id=context.audit_id,
            )
        except FillTriggeredFollowUpActivationError:
            raise
        except Exception:
            raise FillTriggeredFollowUpActivationError(
                "fill_triggered_follow_up_control_unavailable",
                503,
            ) from None
        return _validate_record(record, source_client_order_id=source_id)

    def dispatch_authoritative_full_fill(
        self,
        *,
        source_client_order_id: str,
        trigger_evidence_sha256: str,
    ) -> FillTriggeredActivationRecord:
        source_id = _required_text(
            source_client_order_id,
            code="fill_triggered_follow_up_source_invalid",
            maximum=128,
        )
        try:
            with self.invocation_guard_factory(source_id):
                return self._dispatch_authoritative_full_fill_under_guard(
                    source_client_order_id=source_id,
                    trigger_evidence_sha256=trigger_evidence_sha256,
                )
        except FillTriggeredFollowUpActivationError:
            raise
        except Exception:
            raise FillTriggeredFollowUpActivationError(
                "fill_triggered_follow_up_invocation_guard_unavailable",
                503,
            ) from None

    def _dispatch_authoritative_full_fill_under_guard(
        self,
        *,
        source_client_order_id: str,
        trigger_evidence_sha256: str,
    ) -> FillTriggeredActivationRecord:
        source_id = _required_text(
            source_client_order_id,
            code="fill_triggered_follow_up_source_invalid",
            maximum=128,
        )
        evidence_hash = str(trigger_evidence_sha256 or "").lower()
        if not _SHA256_RE.fullmatch(evidence_hash):
            raise FillTriggeredFollowUpActivationError(
                "fill_triggered_follow_up_trigger_evidence_invalid",
                422,
            )
        try:
            claimed = self.repository.claim_full_fill_trigger(
                source_client_order_id=source_id,
                trigger_evidence_sha256=evidence_hash,
            )
        except Exception:
            raise FillTriggeredFollowUpActivationError(
                "fill_triggered_follow_up_claim_unavailable",
                503,
            ) from None
        if claimed is None:
            return self.read(source_client_order_id=source_id)
        claimed = _validate_record(claimed, source_client_order_id=source_id)
        if (
            claimed.control_state
            is not FillTriggeredActivationControlState.ENABLED
            or claimed.trigger_state
            is not FillTriggeredActivationTriggerState.CLAIMED
            or not claimed.trigger_claim_id
        ):
            raise FillTriggeredFollowUpActivationError(
                "fill_triggered_follow_up_claim_invalid",
                503,
            )
        try:
            materializer = self.materializer_factory()
            result = materializer.materialize(
                source_client_order_id=source_id,
                activation=claimed,
            )
            state, child_id, diagnostic = _materialization_result_fields(result)
            terminal_state = (
                FillTriggeredActivationTriggerState.UNKNOWN
                if "UNKNOWN" in state.upper()
                else FillTriggeredActivationTriggerState.BLOCKED
                if "REJECTED" in state.upper() or "BLOCKED" in state.upper()
                else FillTriggeredActivationTriggerState.COMPLETED
            )
            diagnostic = (
                "fill_triggered_follow_up_outcome_unknown"
                if terminal_state is FillTriggeredActivationTriggerState.UNKNOWN
                else "fill_triggered_follow_up_materialization_blocked"
                if terminal_state is FillTriggeredActivationTriggerState.BLOCKED
                else "fill_triggered_follow_up_create_accepted"
            )
        except OperatorFollowUpMaterializationError as exc:
            recovered = None
            if self.recovery_reader is not None:
                try:
                    recovered = self.recovery_reader(source_id)
                except Exception:
                    recovered = None
            if recovered is not None:
                state, child_id, diagnostic, terminal_state = (
                    _project_canonical_materialization_attempt(recovered)
                )
            elif exc.live_exchange_submitted is False:
                state = "BLOCKED"
                child_id = None
                diagnostic = (
                    "fill_triggered_follow_up_materialization_blocked"
                )
                terminal_state = FillTriggeredActivationTriggerState.BLOCKED
            else:
                state = "UNKNOWN"
                child_id = None
                diagnostic = "fill_triggered_follow_up_outcome_unknown"
                terminal_state = FillTriggeredActivationTriggerState.UNKNOWN
        except Exception:
            state = "UNKNOWN"
            child_id = None
            diagnostic = "fill_triggered_follow_up_outcome_unknown"
            terminal_state = FillTriggeredActivationTriggerState.UNKNOWN
        try:
            finalized = self.repository.finalize_trigger(
                source_client_order_id=source_id,
                trigger_claim_id=claimed.trigger_claim_id,
                trigger_state=terminal_state,
                materialization_state=state,
                child_client_order_id=child_id,
                diagnostic_code=diagnostic,
            )
        except Exception:
            raise FillTriggeredFollowUpActivationError(
                "fill_triggered_follow_up_terminal_persistence_unknown",
                503,
            ) from None
        return _validate_record(finalized, source_client_order_id=source_id)


def recover_stranded_fill_triggered_follow_ups(
    *,
    repository: Any,
    native_repository: Any,
) -> int:
    """Terminalize post-crash claims under the canonical goal invocation lock."""

    recovered_count = 0
    for candidate in repository.list_claimed():
        source_id = str(candidate.source_client_order_id)
        with native_repository.follow_up_live_proof_invocation_guard(
            goal_id=FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
            source_client_order_id=source_id,
        ):
            current = repository.read(source_id)
            if (
                current.trigger_state
                is not FillTriggeredActivationTriggerState.CLAIMED
                or not current.trigger_claim_id
            ):
                continue
            readback = native_repository.read_materialization(
                source_id,
                live_proof_goal_id=FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
            )
            attempt = getattr(readback, "attempt", None)
            if attempt is None:
                state = "KNOWN_NOT_INVOKED"
                child_id = None
                diagnostic = (
                    "fill_triggered_follow_up_materialization_blocked"
                )
                terminal_state = FillTriggeredActivationTriggerState.BLOCKED
            else:
                state, child_id, diagnostic, terminal_state = (
                    _project_canonical_materialization_attempt(attempt)
                )
            repository.finalize_trigger(
                source_client_order_id=source_id,
                trigger_claim_id=current.trigger_claim_id,
                trigger_state=terminal_state,
                materialization_state=state,
                child_client_order_id=child_id,
                diagnostic_code=diagnostic,
            )
            recovered_count += 1
    return recovered_count


_DEFAULT_SERVICE: FillTriggeredFollowUpActivationService | None = None
_DEFAULT_SERVICE_LOCK = threading.Lock()
_DEFAULT_MATERIALIZATION_FACADE: Any | None = None
_DEFAULT_MATERIALIZATION_FACADE_LOCK = threading.Lock()


def get_default_fill_triggered_follow_up_materialization_service() -> Any:
    """Return the Goal 8-bound canonical facade without invoking Coinbase."""

    global _DEFAULT_MATERIALIZATION_FACADE
    if _DEFAULT_MATERIALIZATION_FACADE is None:
        with _DEFAULT_MATERIALIZATION_FACADE_LOCK:
            if _DEFAULT_MATERIALIZATION_FACADE is None:
                from application.admin_api.operator_follow_up_materialization_runtime import (
                    build_default_operator_follow_up_materialization_service,
                )

                _DEFAULT_MATERIALIZATION_FACADE = (
                    build_default_operator_follow_up_materialization_service(
                        live_proof_goal_id=FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
                        materialization_operator_intent=(
                            MATERIALIZE_ENABLED_FILL_TRIGGERED_FOLLOW_UP
                        ),
                        safe_closeout_operator_intent=(
                            SAFE_CLOSEOUT_FILL_TRIGGERED_FOLLOW_UP
                        ),
                    )
                )
    return _DEFAULT_MATERIALIZATION_FACADE


def _build_goal_bound_materializer() -> GoalBoundFillTriggeredFollowUpMaterializer:
    facade = get_default_fill_triggered_follow_up_materialization_service()
    return GoalBoundFillTriggeredFollowUpMaterializer(
        kernel_service=facade.service,
        invocation_guard_already_held=True,
        environment=(
            str(os.environ.get("COINBASE_ADMIN_API_ENVIRONMENT") or "").strip()
            or "controlled_live"
        ),
    )


def _read_goal8_materialization_attempt(source_client_order_id: str) -> object | None:
    from database.order_follow_up_intent import get_default_repository

    return get_default_repository().read_materialization(
        source_client_order_id,
        live_proof_goal_id=FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
    ).attempt


def get_default_fill_triggered_follow_up_activation_service(
) -> FillTriggeredFollowUpActivationService:
    global _DEFAULT_SERVICE
    if _DEFAULT_SERVICE is None:
        with _DEFAULT_SERVICE_LOCK:
            if _DEFAULT_SERVICE is None:
                from database.operator_fill_triggered_follow_up_activation import (
                    get_default_operator_fill_triggered_follow_up_activation_repository,
                )
                from database.order_follow_up_intent import get_default_repository

                native_repository = get_default_repository()

                _DEFAULT_SERVICE = FillTriggeredFollowUpActivationService(
                    repository=(
                        get_default_operator_fill_triggered_follow_up_activation_repository()
                    ),
                    materializer_factory=_build_goal_bound_materializer,
                    recovery_reader=_read_goal8_materialization_attempt,
                    invocation_guard_factory=lambda source_id: (
                        native_repository.follow_up_live_proof_invocation_guard(
                            goal_id=FILL_TRIGGERED_FOLLOW_UP_GOAL_ID,
                            source_client_order_id=source_id,
                        )
                    ),
                )
    return _DEFAULT_SERVICE
