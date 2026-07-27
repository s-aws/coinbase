"""Durable service orchestration for one reviewed direct-parent move.

The service owns local authorization, immutable-plan binding, ordered durable
claims, and value-blind runtime accounting.  It does not import the legacy
``MoveManager`` or a Coinbase SDK.  A wired runtime must enter the existing
canonical Spot command boundaries and invoke the supplied boundary callback
immediately before its one permitted exchange call.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from functools import wraps
import hashlib
import json
import re
from typing import Any, Callable, Mapping, Protocol
import uuid

from application.admin_api.operator_parent_move_premark_policy import (
    GOAL_ID,
    ParentMovePremarkPlan,
    ParentMovePremarkPolicyError,
    ParentMovePremarkPolicyTerms,
    build_parent_move_premark_plan,
    require_parent_move_premark_policy_terms,
)


_EVIDENCE_ID_RE = re.compile(r"^[A-Za-z0-9._:@|/-]{1,255}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DIAGNOSTIC_RE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
_OPERATOR_ROLES = frozenset({"admin", "trader", "operator"})


class OperatorParentMoveServiceError(ValueError):
    """A value-blind, fixed-code service rejection."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _ParentMovePreBoundaryAbort(Exception):
    def __init__(self, diagnostic_code: str) -> None:
        self.diagnostic_code = diagnostic_code
        super().__init__(diagnostic_code)


@dataclass(frozen=True, slots=True)
class ParentMoveCommandContext:
    actor_id: str
    roles: tuple[str, ...]
    idempotency_key: str
    correlation_id: str
    audit_id: str
    operator_intent: str


@dataclass(frozen=True, slots=True)
class ParentMovePremarkRequest:
    source_client_order_id: str
    requested_limit_price: str
    operator_reason: str
    confirm_premark: bool


@dataclass(frozen=True, slots=True)
class ParentMoveExecuteRequest:
    source_client_order_id: str
    expected_plan_sha256: str
    confirmation_sha256: str
    confirm_cancel_then_replace: bool


@dataclass(frozen=True, slots=True)
class ParentMoveSafeCloseoutRequest:
    source_client_order_id: str
    expected_plan_sha256: str
    confirmation_sha256: str
    confirm_exact_successor_cancel: bool


@dataclass(frozen=True, slots=True)
class ParentMoveRuntimeOutcome:
    """Sanitized result returned by a narrow canonical runtime adapter."""

    classification: str
    exchange_invoked: bool
    diagnostic_code: str
    exchange_evidence_sha256: str | None = None
    client_order_id: str | None = None
    parent_client_order_id: str | None = None


class ParentMoveOrderRepository(Protocol):
    def get_order(self, client_order_id: str) -> Mapping[str, Any] | None: ...


class ParentMoveGoalRepository(Protocol):
    def get_premark_replay(self, **kwargs: Any) -> Mapping[str, Any] | None: ...

    def get_execute_replay(self, **kwargs: Any) -> Mapping[str, Any] | None: ...

    def create_plan(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def get_goal(
        self, source_client_order_id: str
    ) -> Mapping[str, Any] | None: ...

    def begin_execute(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def begin_closeout(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def complete_cycle(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def activate_source_follow_up_suppression(
        self, **kwargs: Any
    ) -> Mapping[str, Any] | None: ...

    def finalize_source_follow_up_suppression(
        self, **kwargs: Any
    ) -> Mapping[str, Any] | None: ...

    def claim_source_cancel(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def mark_source_cancel_boundary_crossed(
        self, **kwargs: Any
    ) -> Mapping[str, Any] | None: ...

    def record_source_cancel_outcome(
        self, **kwargs: Any
    ) -> Mapping[str, Any]: ...

    def abort_source_cancel_before_boundary(
        self, **kwargs: Any
    ) -> Mapping[str, Any]: ...

    def claim_replacement_create(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def mark_replacement_create_boundary_crossed(
        self, **kwargs: Any
    ) -> Mapping[str, Any] | None: ...

    def record_replacement_create_outcome(
        self, **kwargs: Any
    ) -> Mapping[str, Any]: ...

    def abort_replacement_create_before_boundary(
        self, **kwargs: Any
    ) -> Mapping[str, Any]: ...

    def claim_successor_closeout_cancel(
        self, **kwargs: Any
    ) -> Mapping[str, Any]: ...

    def mark_successor_closeout_cancel_boundary_crossed(
        self, **kwargs: Any
    ) -> Mapping[str, Any] | None: ...

    def record_successor_closeout_cancel_outcome(
        self, **kwargs: Any
    ) -> Mapping[str, Any]: ...

    def abort_successor_closeout_cancel_before_boundary(
        self, **kwargs: Any
    ) -> Mapping[str, Any]: ...


class ParentMoveLifecycleCoordinator(Protocol):
    def exclusive(self) -> AbstractContextManager[None]: ...


class ParentMoveRuntime(Protocol):
    def cancel_source(
        self,
        plan: Mapping[str, Any],
        *,
        before_exchange_call: Callable[[], None],
    ) -> ParentMoveRuntimeOutcome: ...

    def create_successor(
        self,
        plan: Mapping[str, Any],
        *,
        before_exchange_call: Callable[[], None],
    ) -> ParentMoveRuntimeOutcome: ...

    def cancel_successor(
        self,
        plan: Mapping[str, Any],
        *,
        before_exchange_call: Callable[[], None],
    ) -> ParentMoveRuntimeOutcome: ...


def _exclusive_lifecycle(operation: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(operation)
    def serialized(
        self: "OperatorParentMovePremarkService",
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        with self.lifecycle_coordinator.exclusive():
            return operation(self, *args, **kwargs)

    return serialized


class OperatorParentMovePremarkService:
    """Coordinate premark, ordered Cancel/Create, and exact-child closeout."""

    def __init__(
        self,
        *,
        repository: ParentMoveGoalRepository,
        order_repository: ParentMoveOrderRepository,
        runtime: ParentMoveRuntime,
        lifecycle_coordinator: ParentMoveLifecycleCoordinator,
        policy_terms: ParentMovePremarkPolicyTerms | None = None,
        legacy_pending_move_checker: Callable[[str], bool],
        reserved_successor_client_order_id_factory: (
            Callable[[], str] | None
        ) = None,
        live_authority_terms_complete: Callable[[], bool] = lambda: False,
        execution_authority_checker: Callable[[], bool] = lambda: False,
    ) -> None:
        self.repository = repository
        self.order_repository = order_repository
        self.runtime = runtime
        self.lifecycle_coordinator = lifecycle_coordinator
        self.policy_terms = policy_terms or ParentMovePremarkPolicyTerms()
        self.legacy_pending_move_checker = legacy_pending_move_checker
        self.reserved_successor_client_order_id_factory = (
            reserved_successor_client_order_id_factory
        )
        self.live_authority_terms_complete = live_authority_terms_complete
        self.execution_authority_checker = execution_authority_checker

    def get_execution(
        self, source_client_order_id: str
    ) -> Mapping[str, Any] | None:
        return self.repository.get_goal(
            _canonical_uuid(source_client_order_id)
        )

    @_exclusive_lifecycle
    def premark(
        self,
        *,
        context: ParentMoveCommandContext,
        request: ParentMovePremarkRequest,
    ) -> Mapping[str, Any]:
        self._require_context(context, "premark_parent_move")
        if request.confirm_premark is not True:
            self._fail("operator_parent_move_premark_confirmation_required")
        if not (10 <= len(str(request.operator_reason)) <= 240):
            self._fail("operator_parent_move_operator_reason_invalid")
        # Validate injected policy authority before any order or ledger read.
        try:
            require_parent_move_premark_policy_terms(self.policy_terms)
        except ParentMovePremarkPolicyError as exc:
            self._fail(exc.code)
        source_id = _canonical_uuid(request.source_client_order_id)
        premark_request_sha256 = _hash_payload(
            {
                "source_client_order_id": source_id,
                "requested_limit_price": request.requested_limit_price,
                "operator_reason_sha256": hashlib.sha256(
                    request.operator_reason.encode("utf-8")
                ).hexdigest(),
                "audit_id_sha256": hashlib.sha256(
                    context.audit_id.encode("utf-8")
                ).hexdigest(),
                "confirm_premark": True,
            }
        )
        replay = self.repository.get_premark_replay(
            source_client_order_id=source_id,
            actor_id=context.actor_id,
            correlation_id=context.correlation_id,
            idempotency_key=context.idempotency_key,
            premark_request_sha256=premark_request_sha256,
        )
        if replay is not None:
            return replay
        source = self.order_repository.get_order(source_id)
        if source is None:
            self._fail("operator_parent_move_source_not_found")
        try:
            legacy_pending = bool(
                self.legacy_pending_move_checker(source_id)
            )
        except Exception:
            self._fail("operator_parent_move_legacy_pending_check_unknown")
        try:
            plan = build_parent_move_premark_plan(
                source=source,
                requested_limit_price=request.requested_limit_price,
                reserved_successor_client_order_id=(
                    str(self.reserved_successor_client_order_id_factory())
                    if self.reserved_successor_client_order_id_factory
                    is not None
                    else _deterministic_successor_client_order_id(
                        source_client_order_id=source_id,
                        idempotency_key=context.idempotency_key,
                    )
                ),
                policy_terms=self.policy_terms,
                legacy_pending_move=legacy_pending,
            )
        except ParentMovePremarkPolicyError as exc:
            self._fail(exc.code)
        plan_payload = plan.to_persisted_payload()
        payload_sha256 = _hash_payload(
            {
                "source_client_order_id": source_id,
                "requested_limit_price": request.requested_limit_price,
                "operator_reason_sha256": hashlib.sha256(
                    request.operator_reason.encode("utf-8")
                ).hexdigest(),
                "audit_id_sha256": hashlib.sha256(
                    context.audit_id.encode("utf-8")
                ).hexdigest(),
                "confirm_premark": True,
                "premark_request_sha256": premark_request_sha256,
                "plan_sha256": plan.plan_sha256,
            }
        )
        return self.repository.create_plan(
            plan=plan_payload,
            plan_sha256=plan.plan_sha256,
            actor_id=context.actor_id,
            correlation_id=context.correlation_id,
            idempotency_key=context.idempotency_key,
            premark_request_sha256=premark_request_sha256,
            payload_sha256=payload_sha256,
        )

    @_exclusive_lifecycle
    def execute(
        self,
        *,
        context: ParentMoveCommandContext,
        request: ParentMoveExecuteRequest,
    ) -> Mapping[str, Any]:
        self._require_context(context, "execute_parent_move")
        self._require_live_authority()
        source_id = _canonical_uuid(request.source_client_order_id)
        self._require_confirmation(
            confirmed=request.confirm_cancel_then_replace,
            expected_plan_sha256=request.expected_plan_sha256,
            confirmation_sha256=request.confirmation_sha256,
            code="operator_parent_move_execute_confirmation_required",
        )
        payload_sha256 = _hash_payload(
            {
                "source_client_order_id": source_id,
                "expected_plan_sha256": request.expected_plan_sha256,
                "confirmation_sha256": request.confirmation_sha256,
                "confirm_cancel_then_replace": True,
                "audit_id_sha256": hashlib.sha256(
                    context.audit_id.encode("utf-8")
                ).hexdigest(),
            }
        )
        replay = self.repository.get_execute_replay(
            source_client_order_id=source_id,
            expected_plan_sha256=request.expected_plan_sha256,
            actor_id=context.actor_id,
            correlation_id=context.correlation_id,
            idempotency_key=context.idempotency_key,
            payload_sha256=payload_sha256,
        )
        if replay is not None:
            return replay
        plan = self._load_plan(source_id, request.expected_plan_sha256)
        projection = self.repository.get_goal(source_id)
        resume_replacement_create = self._replacement_resume_ready(
            projection
        )
        if not resume_replacement_create:
            self._revalidate_source(plan)
        begun = self.repository.begin_execute(
            source_client_order_id=source_id,
            expected_plan_sha256=request.expected_plan_sha256,
            actor_id=context.actor_id,
            correlation_id=context.correlation_id,
            idempotency_key=context.idempotency_key,
            payload_sha256=payload_sha256,
        )
        if bool(begun.get("command_replayed")):
            return begun
        cycle_number = self._active_cycle_number(begun)
        if resume_replacement_create:
            if not self._replacement_resume_ready(begun):
                self._fail("operator_parent_move_execute_resume_conflict")
            result = begun
        else:
            self.repository.activate_source_follow_up_suppression(
                source_client_order_id=source_id,
                correlation_id=context.correlation_id,
            )
            self.repository.claim_source_cancel(
                source_client_order_id=source_id,
                correlation_id=context.correlation_id,
            )
            try:
                cancel = self._invoke_runtime(
                    operation=lambda before: self.runtime.cancel_source(
                        plan,
                        before_exchange_call=before,
                    ),
                    before_exchange_call=lambda: (
                        self.repository.mark_source_cancel_boundary_crossed(
                            source_client_order_id=source_id,
                            correlation_id=context.correlation_id,
                        )
                    ),
                    allowed=frozenset(
                        {"CANCELLED", "REJECTED", "UNKNOWN"}
                    ),
                    invalid_code=(
                        "operator_parent_move_source_cancel_pre_call_abort"
                    ),
                    expected_client_order_id=source_id,
                    expected_parent_client_order_id=None,
                )
            except _ParentMovePreBoundaryAbort as exc:
                result = self.repository.abort_source_cancel_before_boundary(
                    source_client_order_id=source_id,
                    correlation_id=context.correlation_id,
                    diagnostic_code=exc.diagnostic_code,
                )
                return self._complete_cycle(
                    source_id=source_id,
                    context=context,
                    diagnostic_code=exc.diagnostic_code,
                    fallback=result,
                )
            result = self.repository.record_source_cancel_outcome(
                source_client_order_id=source_id,
                correlation_id=context.correlation_id,
                cycle_number=cycle_number,
                outcome=cancel.classification,
                diagnostic_code=cancel.diagnostic_code,
                exchange_evidence_sha256=cancel.exchange_evidence_sha256,
            )
            if cancel.classification != "CANCELLED":
                if cancel.classification == "REJECTED":
                    self.repository.finalize_source_follow_up_suppression(
                        source_client_order_id=source_id,
                        diagnostic_code=(
                            "operator_parent_move_source_"
                            "suppression_finalized"
                        ),
                    )
                return self._complete_cycle(
                    source_id=source_id,
                    context=context,
                    diagnostic_code=cancel.diagnostic_code,
                    fallback=result,
                )
        self.repository.claim_replacement_create(
            source_client_order_id=source_id,
            correlation_id=context.correlation_id,
        )
        try:
            create = self._invoke_runtime(
                operation=lambda before: self.runtime.create_successor(
                    plan,
                    before_exchange_call=before,
                ),
                before_exchange_call=lambda: (
                    self.repository.mark_replacement_create_boundary_crossed(
                        source_client_order_id=source_id,
                        correlation_id=context.correlation_id,
                    )
                ),
                allowed=frozenset({"ACCEPTED", "REJECTED", "UNKNOWN"}),
                invalid_code=(
                    "operator_parent_move_replacement_create_pre_call_abort"
                ),
                expected_client_order_id=str(
                    plan["reserved_successor_client_order_id"]
                ),
                expected_parent_client_order_id=source_id,
            )
        except _ParentMovePreBoundaryAbort as exc:
            result = self.repository.abort_replacement_create_before_boundary(
                source_client_order_id=source_id,
                correlation_id=context.correlation_id,
                diagnostic_code=exc.diagnostic_code,
            )
            return self._complete_cycle(
                source_id=source_id,
                context=context,
                diagnostic_code=exc.diagnostic_code,
                fallback=result,
            )
        result = self.repository.record_replacement_create_outcome(
            source_client_order_id=source_id,
            correlation_id=context.correlation_id,
            cycle_number=cycle_number,
            outcome=create.classification,
            diagnostic_code=create.diagnostic_code,
            exchange_evidence_sha256=create.exchange_evidence_sha256,
        )
        return self._complete_cycle(
            source_id=source_id,
            context=context,
            diagnostic_code=create.diagnostic_code,
            fallback=result,
        )

    @_exclusive_lifecycle
    def safe_closeout(
        self,
        *,
        context: ParentMoveCommandContext,
        request: ParentMoveSafeCloseoutRequest,
    ) -> Mapping[str, Any]:
        self._require_context(
            context,
            "safe_closeout_parent_move_successor",
        )
        self._require_live_authority()
        source_id = _canonical_uuid(request.source_client_order_id)
        self._require_confirmation(
            confirmed=request.confirm_exact_successor_cancel,
            expected_plan_sha256=request.expected_plan_sha256,
            confirmation_sha256=request.confirmation_sha256,
            code="operator_parent_move_closeout_confirmation_required",
        )
        plan = self._load_plan(source_id, request.expected_plan_sha256)
        successor_id = str(plan["reserved_successor_client_order_id"])
        _canonical_uuid(successor_id)
        payload_sha256 = _hash_payload(
            {
                "source_client_order_id": source_id,
                "reserved_successor_client_order_id": successor_id,
                "expected_plan_sha256": request.expected_plan_sha256,
                "confirmation_sha256": request.confirmation_sha256,
                "confirm_exact_successor_cancel": True,
                "audit_id_sha256": hashlib.sha256(
                    context.audit_id.encode("utf-8")
                ).hexdigest(),
            }
        )
        begun = self.repository.begin_closeout(
            source_client_order_id=source_id,
            reserved_successor_client_order_id=successor_id,
            expected_plan_sha256=request.expected_plan_sha256,
            actor_id=context.actor_id,
            correlation_id=context.correlation_id,
            idempotency_key=context.idempotency_key,
            payload_sha256=payload_sha256,
        )
        if bool(begun.get("command_replayed")):
            return begun
        cycle_number = self._active_cycle_number(begun)
        self.repository.claim_successor_closeout_cancel(
            source_client_order_id=source_id,
            reserved_successor_client_order_id=successor_id,
            correlation_id=context.correlation_id,
        )
        try:
            closeout = self._invoke_runtime(
                operation=lambda before: self.runtime.cancel_successor(
                    plan,
                    before_exchange_call=before,
                ),
                before_exchange_call=lambda: (
                    self.repository
                    .mark_successor_closeout_cancel_boundary_crossed(
                        source_client_order_id=source_id,
                        reserved_successor_client_order_id=successor_id,
                        correlation_id=context.correlation_id,
                    )
                ),
                allowed=frozenset({"CANCELLED", "REJECTED", "UNKNOWN"}),
                invalid_code=(
                    "operator_parent_move_closeout_pre_call_abort"
                ),
                expected_client_order_id=successor_id,
                expected_parent_client_order_id=source_id,
            )
        except _ParentMovePreBoundaryAbort as exc:
            result = (
                self.repository
                .abort_successor_closeout_cancel_before_boundary(
                    source_client_order_id=source_id,
                    reserved_successor_client_order_id=successor_id,
                    correlation_id=context.correlation_id,
                    diagnostic_code=exc.diagnostic_code,
                )
            )
            return self._complete_cycle(
                source_id=source_id,
                context=context,
                diagnostic_code=exc.diagnostic_code,
                fallback=result,
            )
        result = self.repository.record_successor_closeout_cancel_outcome(
            source_client_order_id=source_id,
            reserved_successor_client_order_id=successor_id,
            correlation_id=context.correlation_id,
            cycle_number=cycle_number,
            outcome=closeout.classification,
            diagnostic_code=closeout.diagnostic_code,
            exchange_evidence_sha256=closeout.exchange_evidence_sha256,
        )
        return self._complete_cycle(
            source_id=source_id,
            context=context,
            diagnostic_code=closeout.diagnostic_code,
            fallback=result,
        )

    def _load_plan(
        self,
        source_id: str,
        expected_plan_sha256: str,
    ) -> Mapping[str, Any]:
        if _SHA256_RE.fullmatch(expected_plan_sha256) is None:
            self._fail("operator_parent_move_plan_binding_invalid")
        projection = self.repository.get_goal(source_id)
        if (
            projection is None
            or projection.get("plan_sha256") != expected_plan_sha256
            or not isinstance(projection.get("plan"), Mapping)
        ):
            self._fail("operator_parent_move_plan_binding_conflict")
        plan = dict(projection["plan"])
        if (
            plan.get("source_client_order_id") != source_id
            or _hash_payload(plan) != expected_plan_sha256
        ):
            self._fail("operator_parent_move_plan_binding_conflict")
        plan["plan_sha256"] = expected_plan_sha256
        return plan

    @staticmethod
    def _active_cycle_number(projection: Mapping[str, Any]) -> int:
        value = projection.get("active_cycle_number")
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 1
        ):
            raise OperatorParentMoveServiceError(
                "operator_parent_move_active_cycle_binding_invalid"
            )
        return value

    def _revalidate_source(self, plan: Mapping[str, Any]) -> None:
        source_id = str(plan["source_client_order_id"])
        source = self.order_repository.get_order(source_id)
        if source is None:
            self._fail("operator_parent_move_source_not_found")
        try:
            pending = bool(self.legacy_pending_move_checker(source_id))
            rebuilt = build_parent_move_premark_plan(
                source=source,
                requested_limit_price=str(plan["requested_limit_price"]),
                reserved_successor_client_order_id=str(
                    plan["reserved_successor_client_order_id"]
                ),
                policy_terms=self.policy_terms,
                legacy_pending_move=pending,
            )
        except ParentMovePremarkPolicyError as exc:
            self._fail(exc.code)
        except Exception:
            self._fail("operator_parent_move_source_revalidation_unknown")
        if rebuilt.plan_sha256 != plan.get("plan_sha256"):
            self._fail("operator_parent_move_source_revalidation_conflict")

    @staticmethod
    def _replacement_resume_ready(
        projection: Mapping[str, Any] | None,
    ) -> bool:
        return bool(
            projection
            and projection.get("state") == "SOURCE_CANCELLED"
            and projection.get("source_cancel_allowance_consumed") is True
            and projection.get("source_cancel_call_count") == 1
            and projection.get("replacement_create_allowance_consumed")
            is False
            and projection.get("replacement_create_call_count") == 0
            and (
                projection.get("source_follow_up_suppressed") is True
                or projection.get(
                    "source_cancel_event_acknowledged"
                )
                is True
            )
        )

    def _require_live_authority(self) -> None:
        try:
            require_parent_move_premark_policy_terms(self.policy_terms)
            live_terms_complete = (
                self.live_authority_terms_complete() is True
            )
        except ParentMovePremarkPolicyError as exc:
            self._fail(exc.code)
        except Exception:
            live_terms_complete = False
        if not live_terms_complete:
            self._fail(
                "operator_parent_move_live_authority_terms_incomplete"
            )
        try:
            execution_enabled = self.execution_authority_checker() is True
        except Exception:
            execution_enabled = False
        if not execution_enabled:
            self._fail("operator_parent_move_execution_authority_disabled")

    def _complete_cycle(
        self,
        *,
        source_id: str,
        context: ParentMoveCommandContext,
        diagnostic_code: str,
        fallback: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        completed = self.repository.complete_cycle(
            source_client_order_id=source_id,
            correlation_id=context.correlation_id,
            idempotency_key=context.idempotency_key,
            diagnostic_code=diagnostic_code,
        )
        return completed if completed is not None else fallback

    @classmethod
    def _invoke_runtime(
        cls,
        *,
        operation: Callable[
            [Callable[[], None]], ParentMoveRuntimeOutcome
        ],
        before_exchange_call: Callable[[], None],
        allowed: frozenset[str],
        invalid_code: str,
        expected_client_order_id: str,
        expected_parent_client_order_id: str | None,
    ) -> ParentMoveRuntimeOutcome:
        crossed = False

        def mark_boundary() -> None:
            nonlocal crossed
            if crossed:
                cls._fail(invalid_code)
            before_exchange_call()
            crossed = True

        try:
            outcome = operation(mark_boundary)
        except Exception:
            if not crossed:
                raise _ParentMovePreBoundaryAbort(invalid_code) from None
            return ParentMoveRuntimeOutcome(
                classification="UNKNOWN",
                exchange_invoked=crossed,
                diagnostic_code=invalid_code,
            )
        valid_outcome_type = isinstance(outcome, ParentMoveRuntimeOutcome)
        linked_return = bool(
            valid_outcome_type
            and crossed
            and outcome.classification
            in {"ACCEPTED", "CANCELLED", "REJECTED"}
        )
        linkage_valid = True
        if linked_return:
            try:
                actual_client_order_id = _canonical_uuid(
                    outcome.client_order_id
                )
                actual_parent_client_order_id = (
                    _canonical_uuid(outcome.parent_client_order_id)
                    if outcome.parent_client_order_id is not None
                    else None
                )
            except OperatorParentMoveServiceError:
                linkage_valid = False
            else:
                linkage_valid = (
                    actual_client_order_id == expected_client_order_id
                    and actual_parent_client_order_id
                    == expected_parent_client_order_id
                )
        elif valid_outcome_type and (
            outcome.client_order_id is not None
            or outcome.parent_client_order_id is not None
        ):
            linkage_valid = False
        if (
            not valid_outcome_type
            or outcome.classification not in allowed
            or outcome.exchange_invoked is not crossed
            or _DIAGNOSTIC_RE.fullmatch(outcome.diagnostic_code) is None
            or not linkage_valid
            or (
                linked_return
                and (
                    outcome.exchange_evidence_sha256 is None
                    or _SHA256_RE.fullmatch(
                        outcome.exchange_evidence_sha256
                    )
                    is None
                )
            )
            or (
                outcome.exchange_evidence_sha256 is not None
                and _SHA256_RE.fullmatch(
                    outcome.exchange_evidence_sha256
                )
                is None
            )
        ):
            if not crossed:
                raise _ParentMovePreBoundaryAbort(invalid_code)
            return ParentMoveRuntimeOutcome(
                classification="UNKNOWN",
                exchange_invoked=crossed,
                diagnostic_code=invalid_code,
            )
        return outcome

    @classmethod
    def _require_context(
        cls,
        context: ParentMoveCommandContext,
        expected_intent: str,
    ) -> None:
        roles = {str(role).strip().lower() for role in context.roles}
        if not roles.intersection(_OPERATOR_ROLES):
            cls._fail("operator_parent_move_permission_denied")
        if context.operator_intent != expected_intent:
            cls._fail("operator_parent_move_intent_invalid")
        if any(
            _EVIDENCE_ID_RE.fullmatch(str(value or "")) is None
            for value in (
                context.actor_id,
                context.idempotency_key,
                context.correlation_id,
                context.audit_id,
            )
        ):
            cls._fail("operator_parent_move_command_identity_invalid")

    @classmethod
    def _require_confirmation(
        cls,
        *,
        confirmed: bool,
        expected_plan_sha256: str,
        confirmation_sha256: str,
        code: str,
    ) -> None:
        if (
            confirmed is not True
            or _SHA256_RE.fullmatch(expected_plan_sha256) is None
            or _SHA256_RE.fullmatch(confirmation_sha256) is None
            or confirmation_sha256 == expected_plan_sha256
        ):
            cls._fail(code)

    @staticmethod
    def _fail(code: str) -> None:
        raise OperatorParentMoveServiceError(code)


def _canonical_uuid(value: Any) -> str:
    try:
        parsed = uuid.UUID(str(value or "").strip())
    except (AttributeError, TypeError, ValueError):
        raise OperatorParentMoveServiceError(
            "operator_parent_move_source_identity_invalid"
        ) from None
    canonical = str(parsed)
    if canonical != str(value or "").strip():
        raise OperatorParentMoveServiceError(
            "operator_parent_move_source_identity_invalid"
        )
    return canonical


def _hash_payload(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _deterministic_successor_client_order_id(
    *,
    source_client_order_id: str,
    idempotency_key: str,
) -> str:
    """Derive one stable UUIDv4-shaped reservation for an exact Premark key."""

    digest = hashlib.sha256(
        (
            f"{GOAL_ID}:reserved-successor:"
            f"{source_client_order_id}:{idempotency_key}"
        ).encode("utf-8")
    ).digest()
    return str(uuid.UUID(bytes=digest[:16], version=4))


__all__ = [
    "OperatorParentMovePremarkService",
    "OperatorParentMoveServiceError",
    "ParentMoveCommandContext",
    "ParentMoveExecuteRequest",
    "ParentMoveGoalRepository",
    "ParentMoveOrderRepository",
    "ParentMovePremarkRequest",
    "ParentMoveRuntime",
    "ParentMoveRuntimeOutcome",
    "ParentMoveSafeCloseoutRequest",
]
