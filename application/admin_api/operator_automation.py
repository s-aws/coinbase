"""Repository-only application service for operator automation controls.

This module is a local orchestration boundary.  It intentionally imports no
Coinbase SDK, Spot execution service, Futures service, or legacy automation
runner.  Durable repositories implement the narrow protocol below.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Protocol

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
    AutomationFilters,
    AutomationJobKind,
    AutomationMutationContext,
    AutomationOneShotRunRequest,
    AutomationPagination,
    AutomationRunDetailResponse,
    AutomationRunEventItem,
    AutomationRunEventListResponse,
    AutomationRunFilters,
    AutomationRunItem,
    AutomationRunListResponse,
    AutomationRunMutationResponse,
    AutomationRunState,
    domain_for_job_kind,
)


AUTOMATION_UNAVAILABLE = "automation_control_plane_unavailable"
AUTOMATION_NOT_FOUND = "automation_resource_not_found"


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

    def __init__(self, repository: Any) -> None:
        self.repository = repository

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

    @staticmethod
    def _control(record: Any) -> Mapping[str, Any]:
        posture = str(getattr(record.posture, "value", record.posture))
        return {
            "posture": posture,
            "local_admission_enabled": posture == "ACTIVE",
            "recurring_worker_started": False,
            "live_scheduler_enabled": False,
            "coinbase_api_call_count": 0,
            "exchange_mutation_count": 0,
            "definition_create_allowed": False,
            "allowed_actions": _control_allowed_actions(record.posture),
            "updated_at": record.updated_at,
        }

    @staticmethod
    def _definition(record: Any) -> Mapping[str, Any]:
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
        return {
            "definition_id": record.definition_id,
            "revision": record.revision,
            "display_name": record.label,
            "domain": str(getattr(record.domain, "value", record.domain)),
            "job_kind": str(getattr(record.job_kind, "value", record.job_kind)),
            "lifecycle_state": state.value,
            "product_ids": list(record.product_ids),
            "schedule": {
                "mode": schedule_mode,
                "interval_minutes": interval_minutes,
                "next_review_at": record.next_review_at,
                "due": record.schedule_due,
            },
            "adapter_status": "UNAVAILABLE",
            "live_execution_available": False,
            "allowed_actions": allowed_actions,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    @staticmethod
    def _run(record: Any) -> Mapping[str, Any]:
        return {
            "run_id": record.run_id,
            "definition_id": record.definition_id,
            "domain": str(getattr(record.domain, "value", record.domain)),
            "job_kind": str(getattr(record.job_kind, "value", record.job_kind)),
            "trigger": "ONE_SHOT",
            "state": str(getattr(record.state, "value", record.state)),
            "diagnostic_code": record.diagnostic_code,
            "adapter_status": "UNAVAILABLE",
            "live_attempt_consumed": record.live_attempt_consumed,
            "coinbase_api_call_count": record.coinbase_api_call_count,
            "create_call_count": record.create_call_count,
            "cancel_call_count": record.cancel_call_count,
            "client_order_id": record.client_order_id,
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

    def get_control_posture(self) -> Mapping[str, Any]:
        record = self._call(self.repository.get_control_posture)
        return self._control(record)

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
            items=tuple(self._definition(item) for item in page.items),
            total_count=page.total_count,
        )

    def get_definition(self, definition_id: str) -> Mapping[str, Any] | None:
        record = self._call(lambda: self.repository.get_definition(definition_id))
        return self._definition(record) if record is not None else None

    def create_definition(
        self,
        *,
        definition: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation:
        from database.operator_automation import AutomationDefinitionCreateCommand

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
        result = self._call(lambda: self.repository.create_definition(command))
        return self._mutation(result, self._definition)

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
        return self._mutation(result, self._definition)

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
        return self._mutation(result, self._definition)

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
        return self._mutation(result, self._definition)

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
        if claim.replayed:
            current = self._call(
                lambda: self.repository.get_run(claim.entity.run_id)
            )
            if current is not None and current.state is not AutomationRunState.CLAIMED:
                return AutomationRepositoryMutation(
                    entity=self._run(current),
                    audit_id=current.audit_id,
                    correlation_id=claim.correlation_id,
                    replayed=True,
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


@dataclass(frozen=True)
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


def get_default_operator_automation_service() -> OperatorAutomationService:
    """Resolve the PostgreSQL repository lazily to keep imports local-only."""

    try:
        from database.operator_automation import (
            get_default_operator_automation_repository,
        )

        repository = get_default_operator_automation_repository()
        return OperatorAutomationService(
            PostgresOperatorAutomationRepositoryAdapter(repository)
        )
    except Exception:
        raise OperatorAutomationError(AUTOMATION_UNAVAILABLE, 503) from None
