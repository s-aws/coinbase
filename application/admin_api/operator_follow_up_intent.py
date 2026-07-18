"""Typed Admin API service for one durable future follow-up intent.

The underlying repository is local PostgreSQL only.  This adapter never calls
Coinbase, invokes the order engine, creates a child, or executes the intent.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from typing import Any, Callable

from application.admin_api.audit import AdminApiAuditEvent, FileAdminApiAuditStore

from application.admin_api.models import (
    AdminOrderFollowUpIntentAttachRequest,
    AdminOrderFollowUpIntentAttachResponse,
    AdminOrderFollowUpIntentAuditBinding,
    AdminOrderFollowUpIntentEligibilityEvidence,
    AdminOrderFollowUpIntentItem,
    AdminOrderFollowUpIntentReadResponse,
)
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiPermission,
)
from core.operator_follow_up_intent import operator_follow_up_intent_enabled
from core.runtime_controller import (
    INFLIGHT_OPERATOR_FOLLOW_UP_INTENT,
    EngineNotAdmittingError,
    get_runtime_controller,
)
from database.order_follow_up_intent import (
    FOLLOW_UP_INTENT_AUDIT_ENDPOINT,
    FOLLOW_UP_INTENT_AUDIT_MESSAGE,
    FollowUpIntentAuditOutboxRecord,
    FollowUpIntentAttachResult,
    FollowUpIntentCommand,
    FollowUpIntentEligibility,
    FollowUpIntentReadback,
    FollowUpIntentRecord,
    FollowUpIntentStoreConflict,
    FollowUpIntentStoreError,
    FollowUpIntentStoreUnavailable,
    OperatorFollowUpIntentRepository,
    get_default_repository,
)


ATTACH_SINGLE_FOLLOW_UP_INTENT = "attach_single_follow_up_intent"
FOLLOW_UP_INTENT_AUDIT_PROJECTION_LIMIT = 100


class OperatorFollowUpIntentError(RuntimeError):
    """Fixed value-blind HTTP boundary error."""

    def __init__(self, code: str, http_status_code: int) -> None:
        self.code = str(code)
        self.http_status_code = int(http_status_code)
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class OperatorFollowUpIntentRequestContext:
    actor_id: str
    roles: tuple[str, ...]
    idempotency_key: str
    correlation_id: str
    operator_intent: str


def _payload_sha256(
    *,
    source_client_order_id: str,
    request: AdminOrderFollowUpIntentAttachRequest,
    context: OperatorFollowUpIntentRequestContext,
) -> str:
    payload = {
        "route": "/api/v1/orders/{source_client_order_id}/follow-up-intent",
        "source_client_order_id": source_client_order_id,
        "body": request.model_dump(mode="json"),
        "actor_id": context.actor_id,
        "operator_intent": context.operator_intent,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _environment() -> str:
    return (
        os.environ.get("COINBASE_ADMIN_API_ENVIRONMENT", "").strip()
        or os.environ.get("COINBASE_BACKEND_DEPLOYMENT_TIER", "").strip()
        or "local"
    )


def _eligibility_model(
    value: FollowUpIntentEligibility,
) -> AdminOrderFollowUpIntentEligibilityEvidence:
    return AdminOrderFollowUpIntentEligibilityEvidence(
        source_client_order_id=value.source_client_order_id,
        root_client_order_id=value.root_client_order_id,
        source_found=value.source_found,
        eligible=value.eligible,
        eligibility_status=value.eligibility_status,
        blockers=list(value.blockers),
        source_status=value.source_status,
        source_ownership_provenance=value.source_ownership_provenance,
        product_id=value.product_id,
        product_type=value.product_type,
        module_id="spot_operations",
        source_is_child=value.source_is_child,
        source_authoritative_zero_fill=value.source_authoritative_zero_fill,
        source_follow_up_child_absent=value.source_follow_up_child_absent,
        automatic_semantic_claim_absent=value.automatic_semantic_claim_absent,
        portfolio_scope_sha256=value.portfolio_scope_sha256,
        slot_limit=1,
        slot_used=value.slot_used,
        attachment_notional_usdc="0",
        submitted_notional_usdc="0",
        future_materialization_requires_fresh_authorization=True,
    )


def _intent_model(value: FollowUpIntentRecord) -> AdminOrderFollowUpIntentItem:
    return AdminOrderFollowUpIntentItem(
        follow_up_intent_id=value.follow_up_intent_id,
        claim_id=value.claim_id,
        source_client_order_id=value.source_client_order_id,
        root_client_order_id=value.root_client_order_id,
        trigger="FILLED",
        intent_kind="single_on_full_fill",
        semantic_intent=value.semantic_intent,
        derived_follow_up_side=value.derived_follow_up_side,
        state="ATTACHED",
        intent_sha256=value.intent_sha256,
        audit_id=value.audit_id,
        correlation_id=value.correlation_id,
        recorded_at=value.recorded_at,
        future_materialization_requires_fresh_authorization=True,
    )


def _audit_model(
    value: FollowUpIntentRecord,
) -> AdminOrderFollowUpIntentAuditBinding:
    return AdminOrderFollowUpIntentAuditBinding(
        actor_id=value.actor_id,
        environment=value.environment,
        portfolio_scope_sha256=value.portfolio_scope_sha256,
        source_client_order_id=value.source_client_order_id,
        root_client_order_id=value.root_client_order_id,
        intent_sha256=value.intent_sha256,
        claim_id=value.claim_id,
        terminal_result="ATTACHED",
    )


def _translate_store_error(exc: FollowUpIntentStoreError) -> OperatorFollowUpIntentError:
    if isinstance(exc, FollowUpIntentStoreUnavailable):
        return OperatorFollowUpIntentError(exc.code, 503)
    if isinstance(exc, FollowUpIntentStoreConflict):
        if exc.code == "source_order_not_found":
            return OperatorFollowUpIntentError(exc.code, 404)
        if exc.code == "source_client_order_id_invalid":
            return OperatorFollowUpIntentError(exc.code, 422)
        return OperatorFollowUpIntentError(exc.code, 409)
    return OperatorFollowUpIntentError("follow_up_intent_backend_unavailable", 503)


class OperatorFollowUpIntentService:
    """Map durable repository evidence into the public typed contract."""

    def __init__(
        self,
        repository: OperatorFollowUpIntentRepository | None = None,
        audit_store: Any | None = None,
        runtime_controller_factory: Callable[[], Any] = get_runtime_controller,
    ) -> None:
        self.repository = repository or get_default_repository()
        self.audit_store = audit_store or FileAdminApiAuditStore()
        self.runtime_controller_factory = runtime_controller_factory

    def _append_command_audit(
        self,
        *,
        context: OperatorFollowUpIntentRequestContext,
        source_client_order_id: str,
        status: AdminApiCommandStatus,
        failure_stage: str | None,
        message: str,
        audit_id: str | None = None,
    ) -> None:
        event_fields: dict[str, Any] = {
            "actor_id": context.actor_id,
            "action_class": AdminApiActionClass.LOCAL_STATE_MUTATION,
            "permission": AdminApiPermission.ORDER_CREATE,
            "endpoint": "/api/v1/orders/{source_client_order_id}/follow-up-intent",
            "request_id": context.correlation_id,
            "operator_intent": context.operator_intent,
            "idempotency_key": context.idempotency_key,
            "client_order_id": source_client_order_id,
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "live_coinbase_read_ran": False,
            "status": status,
            "failure_stage": failure_stage,
            "message": message,
        }
        if audit_id is not None:
            event_fields["audit_id"] = audit_id
        try:
            self.audit_store.append(AdminApiAuditEvent(**event_fields))
        except Exception:
            raise OperatorFollowUpIntentError(
                "follow_up_intent_audit_unavailable",
                503,
            ) from None

    @staticmethod
    def _expected_attached_command_audit(
        record: FollowUpIntentRecord,
    ) -> AdminApiAuditEvent:
        return AdminApiAuditEvent(
            audit_id=record.audit_id,
            recorded_at=record.recorded_at,
            actor_id=record.actor_id,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            permission=AdminApiPermission.ORDER_CREATE,
            endpoint=FOLLOW_UP_INTENT_AUDIT_ENDPOINT,
            request_id=record.correlation_id,
            operator_intent=ATTACH_SINGLE_FOLLOW_UP_INTENT,
            idempotency_key=record.idempotency_key,
            client_order_id=record.source_client_order_id,
            live_exchange_submitted=False,
            live_coinbase_orders_ran=False,
            live_coinbase_read_ran=False,
            status=AdminApiCommandStatus.ACCEPTED,
            failure_stage=None,
            message=FOLLOW_UP_INTENT_AUDIT_MESSAGE,
        )

    def _require_attached_audit_outbox(
        self,
        record: FollowUpIntentRecord,
    ) -> tuple[FollowUpIntentAuditOutboxRecord, AdminApiAuditEvent]:
        try:
            outbox = self.repository.read_audit_outbox(record.audit_id)
        except FollowUpIntentStoreUnavailable:
            raise OperatorFollowUpIntentError(
                "follow_up_intent_audit_unavailable",
                503,
            ) from None
        except FollowUpIntentStoreError:
            raise OperatorFollowUpIntentError(
                "follow_up_intent_audit_mismatch",
                503,
            ) from None
        except Exception:
            raise OperatorFollowUpIntentError(
                "follow_up_intent_audit_unavailable",
                503,
            ) from None
        event = self._validate_audit_outbox(outbox)
        expected = self._expected_attached_command_audit(record)
        if (
            outbox.follow_up_intent_id != record.follow_up_intent_id
            or outbox.source_client_order_id != record.source_client_order_id
            or outbox.recorded_at != record.recorded_at
            or event != expected
        ):
            raise OperatorFollowUpIntentError(
                "follow_up_intent_audit_mismatch",
                503,
            )
        return outbox, event

    @staticmethod
    def _validate_audit_outbox(
        outbox: FollowUpIntentAuditOutboxRecord,
    ) -> AdminApiAuditEvent:
        event_sha256 = hashlib.sha256(
            json.dumps(
                outbox.event,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        try:
            event = AdminApiAuditEvent.model_validate(outbox.event)
        except Exception:
            raise OperatorFollowUpIntentError(
                "follow_up_intent_audit_mismatch",
                503,
            ) from None
        if (
            outbox.audit_id != event.audit_id
            or outbox.source_client_order_id != event.client_order_id
            or outbox.recorded_at != event.recorded_at
            or outbox.event_sha256 != event_sha256
            or event.action_class != AdminApiActionClass.LOCAL_STATE_MUTATION
            or event.permission != AdminApiPermission.ORDER_CREATE
            or event.endpoint != FOLLOW_UP_INTENT_AUDIT_ENDPOINT
            or event.operator_intent != ATTACH_SINGLE_FOLLOW_UP_INTENT
            or event.status != AdminApiCommandStatus.ACCEPTED
            or event.failure_stage is not None
            or event.message != FOLLOW_UP_INTENT_AUDIT_MESSAGE
            or event.live_exchange_submitted
            or event.live_coinbase_orders_ran
            or event.live_coinbase_read_ran
        ):
            raise OperatorFollowUpIntentError(
                "follow_up_intent_audit_mismatch",
                503,
            )
        return event

    def _project_audit_outbox(
        self,
        outbox: FollowUpIntentAuditOutboxRecord,
        expected: AdminApiAuditEvent,
    ) -> None:
        find_exact = getattr(
            self.audit_store,
            "find_unique_by_audit_id",
            self.audit_store.find_by_audit_id,
        )
        append_exact = getattr(
            self.audit_store,
            "append_unique",
            self.audit_store.append,
        )
        try:
            existing = find_exact(outbox.audit_id)
        except Exception:
            raise OperatorFollowUpIntentError(
                "follow_up_intent_audit_unavailable",
                503,
            ) from None
        if existing is not None:
            try:
                normalized = AdminApiAuditEvent.model_validate(existing)
            except Exception:
                raise OperatorFollowUpIntentError(
                    "follow_up_intent_audit_mismatch",
                    503,
                ) from None
            if normalized != expected:
                raise OperatorFollowUpIntentError(
                    "follow_up_intent_audit_mismatch",
                    503,
                )
        else:
            try:
                appended_audit_id = append_exact(expected)
            except ValueError:
                raise OperatorFollowUpIntentError(
                    "follow_up_intent_audit_mismatch",
                    503,
                ) from None
            except Exception:
                raise OperatorFollowUpIntentError(
                    "follow_up_intent_audit_unavailable",
                    503,
                ) from None
            if str(appended_audit_id) != outbox.audit_id:
                raise OperatorFollowUpIntentError(
                    "follow_up_intent_audit_mismatch",
                    503,
                )
            try:
                appended = find_exact(outbox.audit_id)
            except Exception:
                raise OperatorFollowUpIntentError(
                    "follow_up_intent_audit_unavailable",
                    503,
                ) from None
            if appended is None:
                raise OperatorFollowUpIntentError(
                    "follow_up_intent_audit_unavailable",
                    503,
                )
            try:
                normalized = AdminApiAuditEvent.model_validate(appended)
            except Exception:
                raise OperatorFollowUpIntentError(
                    "follow_up_intent_audit_mismatch",
                    503,
                ) from None
            if normalized != expected:
                raise OperatorFollowUpIntentError(
                    "follow_up_intent_audit_mismatch",
                    503,
                )
        if outbox.projected_at is None:
            try:
                projected = self.repository.mark_audit_projected(
                    audit_id=outbox.audit_id,
                    event_sha256=outbox.event_sha256,
                )
            except FollowUpIntentStoreUnavailable:
                raise OperatorFollowUpIntentError(
                    "follow_up_intent_audit_unavailable",
                    503,
                ) from None
            except FollowUpIntentStoreError:
                raise OperatorFollowUpIntentError(
                    "follow_up_intent_audit_mismatch",
                    503,
                ) from None
            except Exception:
                raise OperatorFollowUpIntentError(
                    "follow_up_intent_audit_unavailable",
                    503,
                ) from None
            if (
                projected.audit_id != outbox.audit_id
                or projected.event_sha256 != outbox.event_sha256
                or projected.projected_at is None
            ):
                raise OperatorFollowUpIntentError(
                    "follow_up_intent_audit_mismatch",
                    503,
                )

    def _ensure_attached_command_audit(
        self,
        record: FollowUpIntentRecord,
    ) -> None:
        outbox, event = self._require_attached_audit_outbox(record)
        self._project_audit_outbox(outbox, event)

    def read(
        self,
        *,
        source_client_order_id: str,
    ) -> AdminOrderFollowUpIntentReadResponse:
        if not operator_follow_up_intent_enabled():
            raise OperatorFollowUpIntentError(
                "operator_follow_up_intent_disabled",
                503,
            )
        try:
            result: FollowUpIntentReadback = self.repository.read(
                source_client_order_id
            )
        except FollowUpIntentStoreError as exc:
            raise _translate_store_error(exc) from exc
        if not result.eligibility.source_found:
            raise OperatorFollowUpIntentError("source_order_not_found", 404)
        if result.record is not None:
            self._require_attached_audit_outbox(result.record)
        return AdminOrderFollowUpIntentReadResponse(
            source_client_order_id=source_client_order_id,
            root_client_order_id=result.eligibility.root_client_order_id,
            eligibility=_eligibility_model(result.eligibility),
            follow_up_intent=(
                _intent_model(result.record) if result.record is not None else None
            ),
            read_only=True,
            local_state_mutated=False,
            live_coinbase_read_ran=False,
            live_coinbase_orders_ran=False,
            order_engine_follow_up_handler_called=False,
            follow_up_child_created=False,
            reconciliation_ran=False,
            exchange_state_mutated=False,
        )

    def attach(
        self,
        *,
        source_client_order_id: str,
        request: AdminOrderFollowUpIntentAttachRequest,
        context: OperatorFollowUpIntentRequestContext,
    ) -> AdminOrderFollowUpIntentAttachResponse:
        if not operator_follow_up_intent_enabled():
            raise OperatorFollowUpIntentError(
                "operator_follow_up_intent_disabled",
                503,
            )
        if context.operator_intent != ATTACH_SINGLE_FOLLOW_UP_INTENT:
            raise OperatorFollowUpIntentError(
                "follow_up_intent_operator_intent_mismatch",
                400,
            )
        command = FollowUpIntentCommand(
            source_client_order_id=source_client_order_id,
            actor_id=context.actor_id,
            roles=context.roles,
            environment=_environment(),
            idempotency_key=context.idempotency_key,
            correlation_id=context.correlation_id,
            operator_intent=context.operator_intent,
            payload_sha256=_payload_sha256(
                source_client_order_id=source_client_order_id,
                request=request,
                context=context,
            ),
        )
        try:
            controller = self.runtime_controller_factory()
        except Exception:
            raise OperatorFollowUpIntentError(
                "follow_up_intent_runtime_unavailable",
                503,
            ) from None
        with controller.track_inflight(INFLIGHT_OPERATOR_FOLLOW_UP_INTENT):
            try:
                controller.check_admission(INFLIGHT_OPERATOR_FOLLOW_UP_INTENT)
            except EngineNotAdmittingError:
                raise OperatorFollowUpIntentError(
                    "follow_up_intent_runtime_not_admitting",
                    503,
                ) from None
            try:
                result: FollowUpIntentAttachResult = self.repository.attach(command)
            except FollowUpIntentStoreError as exc:
                self._append_command_audit(
                    context=context,
                    source_client_order_id=source_client_order_id,
                    status=(
                        AdminApiCommandStatus.CONFLICT
                        if exc.code in {
                            "idempotency_conflict",
                            "follow_up_intent_already_attached",
                        }
                        else AdminApiCommandStatus.REJECTED
                    ),
                    failure_stage=exc.code,
                    message="follow_up_intent_rejected",
                )
                raise _translate_store_error(exc) from exc
            self._ensure_attached_command_audit(result.record)

        eligibility = _eligibility_model(result.eligibility)
        intent = _intent_model(result.record)
        replayed = bool(result.replayed)
        return AdminOrderFollowUpIntentAttachResponse(
            status=(
                AdminApiCommandStatus.REPLAYED
                if replayed
                else AdminApiCommandStatus.ACCEPTED
            ),
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            required_permission=AdminApiPermission.ORDER_CREATE,
            service_method="attach_order_follow_up_intent",
            message=(
                "Single follow-up intent replayed from durable readback."
                if replayed
                else "Single follow-up intent attached."
            ),
            source_client_order_id=source_client_order_id,
            root_client_order_id=result.record.root_client_order_id,
            correlation_id=result.record.correlation_id,
            idempotency_key=result.record.idempotency_key,
            audit_id=result.record.audit_id,
            replayed=replayed,
            eligibility=eligibility,
            follow_up_intent=intent,
            audit_binding=_audit_model(result.record),
            local_state_mutated=not replayed,
            live_coinbase_read_ran=False,
            live_coinbase_orders_ran=False,
            live_exchange_submitted=False,
            order_engine_follow_up_handler_called=False,
            follow_up_child_created=False,
            reconciliation_ran=False,
            exchange_state_mutated=False,
            future_materialization_requires_fresh_authorization=True,
        )


def get_default_operator_follow_up_intent_service() -> OperatorFollowUpIntentService:
    return OperatorFollowUpIntentService()


def project_pending_operator_follow_up_intent_audits(
    *,
    repository: OperatorFollowUpIntentRepository | None = None,
    audit_store: Any | None = None,
    limit: int = FOLLOW_UP_INTENT_AUDIT_PROJECTION_LIMIT,
) -> dict[str, int | bool]:
    """Boundedly project canonical PostgreSQL outbox events into JSONL."""

    bounded_limit = max(1, min(int(limit), FOLLOW_UP_INTENT_AUDIT_PROJECTION_LIMIT))
    selected_repository = repository or get_default_repository()
    service = OperatorFollowUpIntentService(
        repository=selected_repository,
        audit_store=audit_store or FileAdminApiAuditStore(),
    )
    try:
        pending = selected_repository.list_unprojected_audit_outbox(
            limit=bounded_limit,
        )
    except Exception:
        return {
            "limit": bounded_limit,
            "scanned": 0,
            "projected": 0,
            "failed": 1,
            "scan_failed": True,
        }

    projected = 0
    failed = 0
    for outbox in pending:
        try:
            event = service._validate_audit_outbox(outbox)
            service._project_audit_outbox(outbox, event)
            projected += 1
        except OperatorFollowUpIntentError:
            failed += 1
    return {
        "limit": bounded_limit,
        "scanned": len(pending),
        "projected": projected,
        "failed": failed,
        "scan_failed": False,
    }
