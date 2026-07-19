"""Order command route adapters for the Admin API."""

from __future__ import annotations

import os
import uuid
import hashlib
import json
from typing import Annotated, Callable, Literal, NoReturn

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    status,
)
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from application.admin_api.audit import AdminApiAuditEvent, FileAdminApiAuditStore
from application.admin_api.approval import (
    FileAdminApiApprovalStore,
    evaluate_command_live_admission,
)
from application.admin_api.auth import get_authenticated_actor, require_permission
from application.admin_api.cap_guard import FileAdminApiCapGuardStore
from application.admin_api.command_runtime import build_admin_api_command_service
from application.admin_api.command_service import (
    AdminApiCommandService,
    CONTROLLED_FIRST_CHILD_CANCEL_OPERATOR_INTENT,
    CONTROLLED_FIRST_CHILD_REVEAL_OPERATOR_INTENT,
    CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT,
    CONTROLLED_V15_FIRST_CHILD_REVEAL_OPERATOR_INTENT,
)
from application.admin_api.spot_portfolio_binding import (
    DEFAULT_SPOT_PORTFOLIO_LABEL,
    SPOT_PORTFOLIO_ID_ENV,
    SPOT_PORTFOLIO_LABEL_ENV,
    serialize_public_spot_portfolio_scope,
)
from application.admin_api.idempotency import (
    FileIdempotencyStore,
    IdempotencyRecord,
    make_payload_hash,
    serialize_idempotent_command,
)
from application.admin_api.live_execution import (
    AdminApiLiveExecutionService,
    get_decision_backed_live_execution_service,
)
from application.admin_api.reconciliation import FileAdminApiReconciliationStore
from application.admin_api.stealth_exchange_truth import (
    FileStealthExchangeTruthProofStore,
)
from application.admin_api.stealth_mutation_claim import (
    FileStealthMutationClaimProofStore,
)
from application.admin_api.stealth_manager_policy import (
    FileStealthManagerInvocationPolicyProofStore,
)
from application.admin_api.stealth_coinbase_exchange_policy import (
    FileStealthCoinbaseExchangeSubmissionPolicyProofStore,
)
from application.admin_api.stealth_post_write_reconciliation_policy import (
    FileStealthPostWriteReconciliationExecutionPolicyProofStore,
)
from application.admin_api.stealth_state_mutation_policy import (
    FileStealthStateMutationPolicyProofStore,
)
from application.admin_api.stealth_recovery_proof import (
    FileStealthRecoveryProofStore,
)
from application.admin_api.stealth_reveal_trigger_proof import (
    FileStealthRevealTriggerProofStore,
)
from application.admin_api.stealth_reconciliation_proof import (
    FileStealthReconciliationProofStore,
)
from application.admin_api.stealth_cancel_replace_proof import (
    FileStealthCancelReplaceProofStore,
)
from application.admin_api.stealth_post_write_reconciliation import (
    FileStealthPostWriteExecutionJournalStore,
    FileStealthPostWriteReconciliationProofStore,
    FileStealthPostWriteReconciliationVerificationStore,
)
from application.admin_api.models import (
    AdminAdmissionPreviewResponse,
    AdminApiActor,
    AdminApiCommandEnvelope,
    AdminApiCommandResponse,
    AdminApiErrorResponse,
    AdminLiveAdmissionDecisionEvidence,
    AdminOrderDetailResponse,
    AdminOrderFollowUpMaterializationCancelRequest,
    AdminOrderFollowUpMaterializationCancelResponse,
    AdminOrderFollowUpMaterializationCommandResponse,
    AdminOrderFollowUpMaterializationReadResponse,
    AdminOrderFollowUpMaterializationRequest,
    AdminOrderFollowUpIntentAttachRequest,
    AdminOrderFollowUpIntentAttachResponse,
    AdminOrderFollowUpIntentReadResponse,
    AdminOrderFillFollowUpChildCancelReadinessResponse,
    AdminOrderFillFollowUpChildCancelRequest,
    AdminOrderFillFollowUpChainResponse,
    AdminOrderFillFollowUpLiveReadinessResponse,
    AdminOrderFillFollowUpReplayResponse,
    AdminOrderFillFollowUpTriggerCommand,
    AdminOrderFillFollowUpTriggerRequest,
    AdminOrderListResponse,
    CampaignExecutionCommand,
    CampaignExecutionRequest,
    CancelOrderCommand,
    CancelOrderRequest,
    ManualOrderCommand,
    ManualOrderRequest,
    ReconcileOrderCommand,
    ReconcileOrderRequest,
    SpotRecoveryApplyExecutionCommand,
    SpotRecoveryApplyExecutionRequest,
    SpotRecoveryExchangeStateProofCommand,
    SpotRecoveryExchangeStateProofRequest,
    SpotRecoveryExchangeStateSnapshotCommand,
    SpotRecoveryExchangeStateSnapshotRequest,
    SpotRecoveryReconciliationExecutionCommand,
    SpotRecoveryReconciliationExecutionRequest,
    SpotRecoveryReconciliationProofRecordCommand,
    SpotRecoveryReconciliationProofRecordRequest,
    SpotRecoveryRollbackExecutionCommand,
    SpotRecoveryRollbackExecutionRequest,
    SpotSweepAutomationRunCommand,
    SpotSweepAutomationRunRequest,
    SpotOrderFillReadbackResponse,
    StealthCommandAdmissionContextEvidence,
    StealthCommandSuiteAdmissionContextItem,
)
from application.admin_api.stealth_command_execution import (
    build_stealth_command_execution_contract,
)
from application.admin_api.read_service import AdminApiReadService
from application.admin_api.operator_follow_up_intent import (
    OperatorFollowUpIntentError,
    OperatorFollowUpIntentRequestContext,
    OperatorFollowUpIntentService,
    get_default_operator_follow_up_intent_service,
)
from application.admin_api.operator_follow_up_materialization import (
    AUTHORIZE_AND_MATERIALIZE_FOLLOW_UP_INTENT,
    SAFE_CLOSEOUT_MATERIALIZED_FOLLOW_UP_INTENT,
    OperatorFollowUpMaterializationError,
    OperatorFollowUpMaterializationRequestContext,
    OperatorFollowUpMaterializationService,
    get_default_operator_follow_up_materialization_service,
)
from application.admin_api.mvp_service import (
    AdminMvpRequestContext,
    AdminMvpService,
    get_admin_mvp_service,
)
from core.coinbase_execution_authority import (
    COINBASE_EXECUTION_SCOPE_SPOT_CANCEL,
    COINBASE_EXECUTION_SCOPE_SPOT_PLACE,
    canonical_coinbase_execution_scope,
)
from core.operator_follow_up_intent import operator_follow_up_intent_enabled
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiErrorCode,
    AdminApiErrorSeverity,
    AdminApiGateStatus,
    AdminApiIdempotencyDecision,
    AdminApiLiveAdmissionBlocker,
    AdminApiMutationFamilyType,
    AdminApiPermission,
    AdminApiStealthAdmissionContextField,
)


router = APIRouter()

_CANONICAL_UUID_PATH_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_VISIBLE_ASCII_HEADER_PATTERN = r"^[!-~]+$"

COMMAND_ROUTE_RESPONSES = {
    200: {
        "model": AdminApiCommandResponse,
        "description": "Command accepted or replayed after all backend gates pass.",
    },
    400: {
        "model": AdminApiCommandResponse,
        "description": "Command rejected before live exchange execution.",
    },
    401: {
        "model": AdminApiErrorResponse,
        "description": "Missing or invalid Admin API authentication.",
    },
    403: {
        "model": AdminApiErrorResponse,
        "description": "Actor lacks the required Admin API permission.",
    },
    409: {
        "model": AdminApiCommandResponse,
        "description": "Idempotency key conflict.",
    },
    501: {
        "model": AdminApiCommandResponse,
        "description": "Live HTTP execution is not implemented for this command.",
    },
}

SOURCE_DISABLED_COMMAND_ROUTE_RESPONSES = {
    401: {
        "model": AdminApiErrorResponse,
        "description": "Missing or invalid Admin API authentication.",
    },
    403: {
        "model": AdminApiErrorResponse,
        "description": "Actor lacks the required Admin API permission.",
    },
    501: {
        "model": AdminApiCommandResponse,
        "description": (
            "Fixed source-disabled response; no admission, replay, store, "
            "service, adapter, or Coinbase execution occurs."
        ),
    },
}

SPOT_RECOVERY_PROOF_ROUTE_RESPONSES = {
    200: {
        "model": AdminApiCommandResponse,
        "description": "Spot recovery proof record accepted or replayed after all backend prerequisites match.",
    },
    400: {
        "model": AdminApiCommandResponse,
        "description": "Spot recovery proof record rejected before local proof persistence.",
    },
    401: {
        "model": AdminApiErrorResponse,
        "description": "Missing or invalid Admin API authentication.",
    },
    403: {
        "model": AdminApiErrorResponse,
        "description": "Actor lacks the required spot recovery proof-record permission.",
    },
    409: {
        "model": AdminApiCommandResponse,
        "description": "Idempotency key conflict.",
    },
}

SPOT_RECOVERY_EXECUTION_ROUTE_RESPONSES = {
    200: {
        "model": AdminApiCommandResponse,
        "description": (
            "Spot recovery execution journal accepted or replayed after all "
            "backend prerequisites match."
        ),
    },
    400: {
        "model": AdminApiCommandResponse,
        "description": (
            "Spot recovery execution rejected before local journal persistence."
        ),
    },
    401: {
        "model": AdminApiErrorResponse,
        "description": "Missing or invalid Admin API authentication.",
    },
    403: {
        "model": AdminApiErrorResponse,
        "description": "Actor lacks the required spot recovery execute permission.",
    },
    409: {
        "model": AdminApiCommandResponse,
        "description": "Idempotency key conflict.",
    },
}

READ_ROUTE_RESPONSES = {
    401: {
        "model": AdminApiErrorResponse,
        "description": "Missing or invalid Admin API authentication.",
    },
    403: {
        "model": AdminApiErrorResponse,
        "description": "Actor lacks the required Admin API permission.",
    },
}

FOLLOW_UP_INTENT_READ_ROUTE_RESPONSES = {
    **READ_ROUTE_RESPONSES,
    404: {
        "model": AdminApiErrorResponse,
        "description": "The backend-owned source order was not found.",
    },
    409: {
        "model": AdminApiErrorResponse,
        "description": "Authoritative source eligibility evidence conflicts.",
    },
    503: {
        "model": AdminApiErrorResponse,
        "description": "Authoritative local eligibility evidence is unavailable.",
    },
}

FOLLOW_UP_INTENT_ATTACH_ROUTE_RESPONSES = {
    200: {
        "model": AdminOrderFollowUpIntentAttachResponse,
        "description": "The one durable intent was accepted or replayed.",
    },
    400: {
        "model": AdminApiErrorResponse,
        "description": "The exact attach request was rejected before persistence.",
    },
    401: READ_ROUTE_RESPONSES[401],
    403: READ_ROUTE_RESPONSES[403],
    404: {
        "model": AdminApiErrorResponse,
        "description": "The backend-owned source order was not found.",
    },
    409: {
        "model": AdminApiErrorResponse,
        "description": "Idempotency, source-slot, or semantic-claim conflict.",
    },
    422: {
        "model": AdminApiErrorResponse,
        "description": "Required headers or the acknowledgement are invalid.",
    },
    503: {
        "model": AdminApiErrorResponse,
        "description": "Authoritative local eligibility evidence is unavailable.",
    },
}

FOLLOW_UP_MATERIALIZATION_READ_ROUTE_RESPONSES = {
    **READ_ROUTE_RESPONSES,
    404: {
        "model": AdminApiErrorResponse,
        "description": "The backend-owned source order or attached intent was not found.",
    },
    409: {
        "model": AdminApiErrorResponse,
        "description": "The durable materialization evidence is inconsistent.",
    },
    503: {
        "model": AdminApiErrorResponse,
        "description": "Authoritative local materialization evidence is unavailable.",
    },
}

FOLLOW_UP_MATERIALIZATION_COMMAND_ROUTE_RESPONSES = {
    200: {
        "model": AdminOrderFollowUpMaterializationCommandResponse,
        "description": "The one-use Create boundary reached a durable classification.",
    },
    400: {
        "model": (
            AdminOrderFollowUpMaterializationCommandResponse
            | AdminApiErrorResponse
        ),
        "description": (
            "The Create boundary returned durable evidence, or explicit "
            "materialization authorization was rejected before a durable result."
        ),
    },
    401: READ_ROUTE_RESPONSES[401],
    403: READ_ROUTE_RESPONSES[403],
    404: FOLLOW_UP_MATERIALIZATION_READ_ROUTE_RESPONSES[404],
    409: {
        "model": (
            AdminOrderFollowUpMaterializationCommandResponse
            | AdminApiErrorResponse
        ),
        "description": (
            "The Create boundary returned durable evidence, or eligibility, "
            "idempotency, or the one-use boundary conflicts."
        ),
    },
    422: {
        "model": AdminApiErrorResponse,
        "description": "Required headers or fixed acknowledgements are invalid.",
    },
    503: FOLLOW_UP_MATERIALIZATION_READ_ROUTE_RESPONSES[503],
}

FOLLOW_UP_MATERIALIZATION_CANCEL_ROUTE_RESPONSES = {
    **FOLLOW_UP_MATERIALIZATION_COMMAND_ROUTE_RESPONSES,
    200: {
        "model": AdminOrderFollowUpMaterializationCancelResponse,
        "description": "The exact child closeout reached a durable classification.",
    },
    400: {
        "model": (
            AdminOrderFollowUpMaterializationCancelResponse
            | AdminApiErrorResponse
        ),
        "description": (
            "The Cancel boundary returned durable evidence, or explicit "
            "safe-closeout authorization was rejected before a durable result."
        ),
    },
    409: {
        "model": (
            AdminOrderFollowUpMaterializationCancelResponse
            | AdminApiErrorResponse
        ),
        "description": (
            "The Cancel boundary returned durable evidence, or safe-closeout "
            "idempotency or the one-use boundary conflicts."
        ),
    },
}


def get_read_service() -> AdminApiReadService:
    """Return the read-only Admin API status service."""

    return AdminApiReadService()


def get_command_service(
    read_service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> AdminApiCommandService:
    """Return the shared command service boundary."""

    return build_admin_api_command_service(read_service_getter=lambda: read_service)


def get_idempotency_store() -> FileIdempotencyStore:
    """Return durable idempotency storage for command routes."""

    return FileIdempotencyStore()


def get_audit_store() -> FileAdminApiAuditStore:
    """Return durable command audit storage."""

    return FileAdminApiAuditStore()


def get_approval_store() -> FileAdminApiApprovalStore:
    """Return durable approval storage for command admission evidence."""

    return FileAdminApiApprovalStore()


def get_cap_guard_store() -> FileAdminApiCapGuardStore:
    """Return durable cap/guard decision storage for admission evidence."""

    return FileAdminApiCapGuardStore()


def get_reconciliation_store() -> FileAdminApiReconciliationStore:
    """Return durable reconciliation plan storage for admission evidence."""

    return FileAdminApiReconciliationStore()


def get_live_execution_service() -> AdminApiLiveExecutionService:
    """Return the backend-owned live execution service boundary."""

    return get_decision_backed_live_execution_service()


def get_mvp_service() -> AdminMvpService:
    """Return the backend-owned MVP read service boundary."""

    return get_admin_mvp_service()


def get_order_follow_up_intent_service() -> OperatorFollowUpIntentService:
    """Return the durable backend authority for the source's one intent slot."""

    return get_default_operator_follow_up_intent_service()


def get_order_follow_up_materialization_service(
) -> OperatorFollowUpMaterializationService:
    """Return the backend-owned one-use materialization coordinator."""

    return get_default_operator_follow_up_materialization_service()


def _follow_up_materialization_environment() -> str:
    """Bind live authority to backend deployment state, never browser input."""

    return (
        os.environ.get("COINBASE_ADMIN_API_ENVIRONMENT", "").strip()
        or os.environ.get("COINBASE_BACKEND_DEPLOYMENT_TIER", "").strip()
        or "local"
    )


def require_operator_follow_up_intent_enabled() -> None:
    """Fail closed until the checkpointed local-state feature is activated."""

    if not operator_follow_up_intent_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_follow_up_intent_disabled",
        )


def _read_response(payload: object) -> JSONResponse:
    return JSONResponse(content=jsonable_encoder(payload))


def _raise_follow_up_intent_error(exc: OperatorFollowUpIntentError) -> NoReturn:
    """Expose only the service's fixed value-blind diagnostic code."""

    raise HTTPException(
        status_code=exc.http_status_code,
        detail=exc.code,
    ) from exc


def _raise_follow_up_materialization_error(
    exc: OperatorFollowUpMaterializationError,
) -> NoReturn:
    """Expose only the materialization kernel's fixed value-blind code."""

    raise HTTPException(
        status_code=exc.http_status_code,
        detail=exc.code,
    ) from exc


_FOLLOW_UP_MATERIALIZATION_RECEIPT_MESSAGE = (
    "follow_up_materialization_authorization_received_for_evaluation"
)
_FOLLOW_UP_MATERIALIZATION_AUDIT_ENDPOINT = (
    "POST /api/v1/orders/{source_client_order_id}/follow-up-intent/materialization"
)
_FOLLOW_UP_MATERIALIZATION_CLOSEOUT_AUDIT_ENDPOINT = (
    "POST /api/v1/orders/{source_client_order_id}/follow-up-intent/"
    "materialization/safe-closeout"
)


def _follow_up_materialization_audit_id(
    *,
    phase: str,
    endpoint: str,
    actor: AdminApiActor,
    source_client_order_id: str,
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
    action_class: AdminApiActionClass,
    permission: AdminApiPermission,
) -> str:
    """Derive one stable audit identity without exposing request values."""

    payload = {
        "phase": phase,
        "endpoint": endpoint,
        "actor_id": actor.actor_id,
        "roles": sorted(role.value for role in actor.roles),
        "source_client_order_id": source_client_order_id,
        "idempotency_key": idempotency_key,
        "correlation_id": correlation_id,
        "operator_intent": operator_intent,
        "action_class": action_class.value,
        "permission": permission.value,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"coinbase://admin-api/follow-up-materialization-audit/{digest}",
        )
    )


def _same_audit_event(
    left: AdminApiAuditEvent,
    right: AdminApiAuditEvent,
) -> bool:
    return left.model_dump(exclude={"recorded_at"}) == right.model_dump(
        exclude={"recorded_at"}
    )


def _append_follow_up_materialization_audit(
    *,
    audit_store: FileAdminApiAuditStore,
    audit_id: str,
    actor: AdminApiActor,
    endpoint: str,
    source_client_order_id: str,
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
    action_class: AdminApiActionClass,
    permission: AdminApiPermission,
    status_value: AdminApiCommandStatus | Literal["received"],
    failure_stage: str,
    message: str,
    live_coinbase_read_ran: bool = False,
    live_coinbase_orders_ran: bool = False,
    live_exchange_submitted: bool = False,
) -> str:
    """Append one value-blind event idempotently without conflicting IDs."""

    event = AdminApiAuditEvent(
        audit_id=audit_id,
        actor_id=actor.actor_id,
        action_class=action_class,
        permission=permission,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        idempotency_key=idempotency_key,
        client_order_id=source_client_order_id,
        live_exchange_submitted=live_exchange_submitted,
        live_coinbase_orders_ran=live_coinbase_orders_ran,
        live_coinbase_read_ran=live_coinbase_read_ran,
        status=status_value,
        failure_stage=failure_stage,
        message=message,
    )
    existing = audit_store.find_unique_by_audit_id(audit_id)
    if existing is not None:
        if not _same_audit_event(existing, event):
            raise ValueError("follow_up_materialization_audit_id_conflict")
        return audit_id
    try:
        return audit_store.append_unique(event)
    except ValueError:
        existing = audit_store.find_unique_by_audit_id(audit_id)
        if existing is None or not _same_audit_event(existing, event):
            raise
        return audit_id


def _follow_up_materialization_error_code(
    http_status_code: int,
) -> AdminApiErrorCode:
    if http_status_code == status.HTTP_403_FORBIDDEN:
        return AdminApiErrorCode.PERMISSION_DENIED
    if http_status_code == status.HTTP_422_UNPROCESSABLE_ENTITY:
        return AdminApiErrorCode.VALIDATION_ERROR
    if http_status_code == status.HTTP_409_CONFLICT:
        return AdminApiErrorCode.IDEMPOTENCY_CONFLICT
    if http_status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        return AdminApiErrorCode.BACKEND_UNAVAILABLE
    return AdminApiErrorCode.REQUEST_ERROR


def _follow_up_materialization_error_severity(
    http_status_code: int,
) -> AdminApiErrorSeverity:
    if http_status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        return AdminApiErrorSeverity.ERROR
    return AdminApiErrorSeverity.WARNING


def _follow_up_materialization_error_response(
    *,
    http_status_code: int,
    diagnostic_code: str,
    correlation_id: str,
    audit_id: str | None,
    live_coinbase_orders_ran: bool = False,
) -> JSONResponse:
    body = AdminApiErrorResponse(
        code=_follow_up_materialization_error_code(http_status_code),
        message=diagnostic_code,
        severity=_follow_up_materialization_error_severity(http_status_code),
        correlation_id=correlation_id,
        audit_id=audit_id,
        live_coinbase_orders_ran=live_coinbase_orders_ran,
    )
    return JSONResponse(
        status_code=http_status_code,
        content=body.model_dump(mode="json"),
        headers={"X-Correlation-Id": correlation_id},
    )


def _record_follow_up_materialization_outcome_error(
    *,
    audit_store: FileAdminApiAuditStore,
    actor: AdminApiActor,
    endpoint: str,
    source_client_order_id: str,
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
    action_class: AdminApiActionClass,
    permission: AdminApiPermission,
    diagnostic_code: str,
    http_status_code: int,
    failure_stage: str,
    live_coinbase_read_ran: bool,
    live_coinbase_orders_ran: bool,
    live_exchange_submitted: bool,
) -> str:
    phase = f"outcome:{http_status_code}:{diagnostic_code}"
    audit_id = _follow_up_materialization_audit_id(
        phase=phase,
        endpoint=endpoint,
        actor=actor,
        source_client_order_id=source_client_order_id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        action_class=action_class,
        permission=permission,
    )
    return _append_follow_up_materialization_audit(
        audit_store=audit_store,
        audit_id=audit_id,
        actor=actor,
        endpoint=endpoint,
        source_client_order_id=source_client_order_id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        action_class=action_class,
        permission=permission,
        status_value=(
            AdminApiCommandStatus.CONFLICT
            if http_status_code == status.HTTP_409_CONFLICT
            else AdminApiCommandStatus.REJECTED
        ),
        failure_stage=failure_stage,
        message=diagnostic_code,
        live_coinbase_read_ran=live_coinbase_read_ran,
        live_coinbase_orders_ran=live_coinbase_orders_ran,
        live_exchange_submitted=live_exchange_submitted,
    )


def _follow_up_materialization_execution_evidence(
    exc: OperatorFollowUpMaterializationError,
) -> tuple[str, bool, bool, bool]:
    """Normalize service evidence without understating an unknown boundary."""

    evidence_is_complete = all(
        value is not None
        for value in (
            exc.live_coinbase_read_ran,
            exc.live_coinbase_orders_ran,
            exc.live_exchange_submitted,
        )
    )
    if not evidence_is_complete:
        return "exchange_boundary_outcome_unknown", True, True, True
    return (
        exc.failure_stage,
        bool(exc.live_coinbase_read_ran),
        bool(exc.live_coinbase_orders_ran),
        bool(exc.live_exchange_submitted),
    )


def _follow_up_materialization_response(payload: object) -> JSONResponse:
    """Return typed durable evidence with replay/correlation headers."""

    response_status = getattr(payload, "status", AdminApiCommandStatus.ACCEPTED)
    status_code = status.HTTP_200_OK
    if response_status == AdminApiCommandStatus.CONFLICT:
        status_code = status.HTTP_409_CONFLICT
    elif response_status == AdminApiCommandStatus.REJECTED:
        status_code = status.HTTP_400_BAD_REQUEST
    elif response_status == AdminApiCommandStatus.NOT_IMPLEMENTED:
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    headers: dict[str, str] = {}
    correlation_id = str(getattr(payload, "correlation_id", "") or "").strip()
    if correlation_id:
        headers["X-Correlation-Id"] = correlation_id
    if bool(getattr(payload, "replayed", False)):
        headers["X-Idempotency-Replayed"] = "true"
    content = (
        payload.model_dump(mode="json")
        if hasattr(payload, "model_dump")
        else jsonable_encoder(payload)
    )
    return JSONResponse(status_code=status_code, content=content, headers=headers)


def _follow_up_intent_attach_response(
    payload: AdminOrderFollowUpIntentAttachResponse,
) -> JSONResponse:
    """Map the typed local result without implying any exchange authority."""

    status_code = status.HTTP_200_OK
    if payload.status == AdminApiCommandStatus.CONFLICT:
        status_code = status.HTTP_409_CONFLICT
    elif payload.status == AdminApiCommandStatus.REJECTED:
        status_code = status.HTTP_400_BAD_REQUEST
    elif payload.status == AdminApiCommandStatus.NOT_IMPLEMENTED:
        status_code = status.HTTP_501_NOT_IMPLEMENTED
    headers = {"X-Correlation-Id": payload.correlation_id}
    if payload.replayed or payload.status == AdminApiCommandStatus.REPLAYED:
        headers["X-Idempotency-Replayed"] = "true"
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers=headers,
    )


def _admin_mvp_read_context(
    actor: AdminApiActor,
    *,
    idempotency_key: str | None,
    correlation_id: str | None,
    operator_intent: str | None,
) -> AdminMvpRequestContext:
    return AdminMvpRequestContext(
        idempotency_key=(idempotency_key or "admin-api-read").strip()
        or "admin-api-read",
        correlation_id=(correlation_id or "admin-api-correlation").strip()
        or "admin-api-correlation",
        operator_intent=(operator_intent or "read_spot_order_fill_readback").strip()
        or "read_spot_order_fill_readback",
        actor_id=actor.actor_id,
        roles=tuple(role.value for role in actor.roles),
    )


def _build_envelope(
    *,
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
    actor: AdminApiActor,
) -> AdminApiCommandEnvelope:
    return AdminApiCommandEnvelope(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
    )


def _http_status_for(response: AdminApiCommandResponse) -> int:
    if response.status == AdminApiCommandStatus.NOT_IMPLEMENTED:
        return status.HTTP_501_NOT_IMPLEMENTED
    if response.status == AdminApiCommandStatus.CONFLICT:
        return status.HTTP_409_CONFLICT
    if response.status == AdminApiCommandStatus.REJECTED:
        return status.HTTP_400_BAD_REQUEST
    return status.HTTP_200_OK


def _command_response(
    response: AdminApiCommandResponse,
    *,
    replayed: bool = False,
) -> JSONResponse:
    headers = {"X-Correlation-Id": response.correlation_id or ""}
    if replayed:
        headers["X-Idempotency-Replayed"] = "true"
    return JSONResponse(
        status_code=_http_status_for(response),
        content=response.model_dump(mode="json"),
        headers=headers,
    )


STEALTH_COMMAND_CONTEXT_MUTATION_FAMILIES = {
    "create_stealth_order": AdminApiMutationFamilyType.STEALTH_CREATE,
    "reveal_stealth_order_by_stealth_order_id": (
        AdminApiMutationFamilyType.STEALTH_REVEAL
    ),
    "move_stealth_order_by_stealth_order_id": AdminApiMutationFamilyType.STEALTH_MOVE,
    "cancel_stealth_order_by_stealth_order_id": (
        AdminApiMutationFamilyType.STEALTH_CANCEL
    ),
    "recover_stealth_order_by_stealth_order_id": (
        AdminApiMutationFamilyType.STEALTH_RECOVERY
    ),
    "reconcile_stealth_order_by_stealth_order_id": (
        AdminApiMutationFamilyType.STEALTH_RECONCILIATION
    ),
    "reprice_stealth_order_by_stealth_order_id": (
        AdminApiMutationFamilyType.MOVEMENT_REPRICE
    ),
}


def _stealth_command_context_requirement(
    *,
    field_name: AdminApiStealthAdmissionContextField,
    source: str,
    detail: str,
) -> StealthCommandSuiteAdmissionContextItem:
    return StealthCommandSuiteAdmissionContextItem(
        field_name=field_name,
        source=source,
        required=True,
        present=True,
        blocking=False,
        backend_owned=True,
        route_bound=True,
        browser_authority="display_only",
        bff_authority="forward_only_no_execution",
        detail=detail,
    )


def _build_stealth_command_admission_context(
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> StealthCommandAdmissionContextEvidence | None:
    mutation_family = STEALTH_COMMAND_CONTEXT_MUTATION_FAMILIES.get(
        admission_decision.service_method
    )
    if (
        mutation_family is None
        or admission_decision.identity_key != "stealth_order_id"
        or not admission_decision.identity_value
    ):
        return None

    requirements = [
        _stealth_command_context_requirement(
            field_name=AdminApiStealthAdmissionContextField.ROUTE,
            source="route_inventory",
            detail="Route is present from the exact backend command route.",
        ),
        _stealth_command_context_requirement(
            field_name=AdminApiStealthAdmissionContextField.METHOD,
            source="route_inventory",
            detail="Method is present from the exact backend command route.",
        ),
        _stealth_command_context_requirement(
            field_name=AdminApiStealthAdmissionContextField.MODULE_ID,
            source="route_inventory",
            detail="Module id is present from backend route metadata.",
        ),
        _stealth_command_context_requirement(
            field_name=AdminApiStealthAdmissionContextField.MUTATION_FAMILY,
            source="command_metadata",
            detail="Mutation family is present from backend command metadata.",
        ),
        _stealth_command_context_requirement(
            field_name=AdminApiStealthAdmissionContextField.ACTION_CLASS,
            source="route_inventory",
            detail="Action class is present from backend route metadata.",
        ),
        _stealth_command_context_requirement(
            field_name=AdminApiStealthAdmissionContextField.REQUIRED_PERMISSION,
            source="route_inventory",
            detail="Required permission is present from backend route metadata.",
        ),
        _stealth_command_context_requirement(
            field_name=AdminApiStealthAdmissionContextField.STEALTH_ORDER_ID,
            source="command_envelope",
            detail="Stealth order id is present from the exact command path or request.",
        ),
        _stealth_command_context_requirement(
            field_name=AdminApiStealthAdmissionContextField.ACTOR_ID,
            source="command_envelope",
            detail="Actor id is present from authenticated backend request context.",
        ),
        _stealth_command_context_requirement(
            field_name=AdminApiStealthAdmissionContextField.IDEMPOTENCY_KEY,
            source="command_envelope",
            detail="Idempotency key is present from the mutating command request.",
        ),
        _stealth_command_context_requirement(
            field_name=AdminApiStealthAdmissionContextField.OPERATOR_INTENT,
            source="command_envelope",
            detail="Operator intent is present from the mutating command request.",
        ),
        _stealth_command_context_requirement(
            field_name=AdminApiStealthAdmissionContextField.PAYLOAD_HASH,
            source="command_envelope",
            detail="Payload hash is computed by the backend for the exact request body.",
        ),
    ]
    return StealthCommandAdmissionContextEvidence(
        mutation_family=mutation_family,
        route=admission_decision.route,
        method=admission_decision.method,
        module_id=admission_decision.module_id,
        identity_value=admission_decision.identity_value,
        action_class=admission_decision.action_class,
        required_permission=admission_decision.required_permission,
        service_method=admission_decision.service_method,
        required_context_count=len(requirements),
        present_context_count=len(requirements),
        missing_context_count=0,
        missing_context=[],
        context_requirements=requirements,
        exact_context_present=True,
        resolver_lookup_allowed=True,
        resolver_lookup_ran=True,
        proof_resolution_attempted=True,
        admission_decision_attached=True,
        admission_allowed=admission_decision.allowed,
        executable=False,
        live_enabled=False,
        coinbase_read_ran=False,
        coinbase_order_submitted=False,
        coinbase_order_cancel_submitted=False,
        active_placement_cancel_replace_ran=False,
        reconciliation_executed=False,
        lifecycle_state_mutated=False,
        order_state_mutated=False,
        exchange_state_mutated=False,
        browser_authority="display_only",
        bff_authority="forward_only_no_execution",
        detail=(
            "Exact command-envelope context is present for backend admission "
            "evidence lookup, but live execution remains blocked."
        ),
    )


def _attach_stealth_execution_posture(
    response: AdminApiCommandResponse,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    *,
    stealth_exchange_truth_proof_store: FileStealthExchangeTruthProofStore | None = None,
    stealth_mutation_claim_proof_store: FileStealthMutationClaimProofStore | None = None,
    stealth_manager_policy_proof_store: (
        FileStealthManagerInvocationPolicyProofStore | None
    ) = None,
    stealth_coinbase_exchange_policy_proof_store: (
        FileStealthCoinbaseExchangeSubmissionPolicyProofStore | None
    ) = None,
    stealth_post_write_reconciliation_policy_proof_store: (
        FileStealthPostWriteReconciliationExecutionPolicyProofStore | None
    ) = None,
    stealth_state_mutation_policy_proof_store: (
        FileStealthStateMutationPolicyProofStore | None
    ) = None,
    stealth_recovery_proof_store: FileStealthRecoveryProofStore | None = None,
    stealth_reveal_trigger_proof_store: (
        FileStealthRevealTriggerProofStore | None
    ) = None,
    stealth_reconciliation_proof_store: (
        FileStealthReconciliationProofStore | None
    ) = None,
    stealth_cancel_replace_proof_store: (
        FileStealthCancelReplaceProofStore | None
    ) = None,
    stealth_post_write_reconciliation_proof_store: (
        FileStealthPostWriteReconciliationProofStore | None
    ) = None,
    stealth_post_write_execution_journal_store: (
        FileStealthPostWriteExecutionJournalStore | None
    ) = None,
    stealth_post_write_reconciliation_verification_store: (
        FileStealthPostWriteReconciliationVerificationStore | None
    ) = None,
) -> None:
    """Attach typed no-live execution posture for eligible stealth commands."""

    contract = build_stealth_command_execution_contract(
        admission_decision,
        stealth_exchange_truth_proof_store=stealth_exchange_truth_proof_store,
        stealth_mutation_claim_proof_store=stealth_mutation_claim_proof_store,
        stealth_manager_policy_proof_store=stealth_manager_policy_proof_store,
        stealth_coinbase_exchange_policy_proof_store=(
            stealth_coinbase_exchange_policy_proof_store
        ),
        stealth_post_write_reconciliation_policy_proof_store=(
            stealth_post_write_reconciliation_policy_proof_store
        ),
        stealth_state_mutation_policy_proof_store=(
            stealth_state_mutation_policy_proof_store
        ),
        stealth_recovery_proof_store=stealth_recovery_proof_store,
        stealth_reveal_trigger_proof_store=stealth_reveal_trigger_proof_store,
        stealth_reconciliation_proof_store=stealth_reconciliation_proof_store,
        stealth_cancel_replace_proof_store=stealth_cancel_replace_proof_store,
        stealth_post_write_reconciliation_proof_store=(
            stealth_post_write_reconciliation_proof_store
        ),
        stealth_post_write_execution_journal_store=(
            stealth_post_write_execution_journal_store
        ),
        stealth_post_write_reconciliation_verification_store=(
            stealth_post_write_reconciliation_verification_store
        ),
    )
    response.stealth_command_execution_contract = contract
    if contract is None or not isinstance(response.data, dict):
        return
    response.data.update({
        "stealth_command_execution_contract_available": (
            contract.execution_contract_available
        ),
        "stealth_command_execution_allowed": contract.execution_allowed,
        "stealth_command_execution_blockers": contract.blockers,
        "resolved_stealth_command_execution_prerequisites": (
            contract.resolved_prerequisites
        ),
        "missing_stealth_command_execution_prerequisites": (
            contract.missing_prerequisites
        ),
    })


def _record_audit(
    *,
    audit_store: FileAdminApiAuditStore,
    actor: AdminApiActor,
    endpoint: str,
    request_id: str,
    operator_intent: str,
    response: AdminApiCommandResponse,
) -> str:
    event_fields = {
        "actor_id": actor.actor_id,
        "action_class": response.action_class,
        "permission": response.required_permission,
        "endpoint": endpoint,
        "request_id": request_id,
        "operator_intent": operator_intent,
        "idempotency_key": response.idempotency_key,
        "approval_id": (
            response.admission_decision.approval_snapshot_id
            if response.admission_decision is not None
            else None
        ),
        "client_order_id": response.client_order_id,
        "stealth_order_id": response.stealth_order_id,
        "coinbase_order_id": response.coinbase_order_id,
        "live_exchange_submitted": response.live_exchange_submitted,
        "live_coinbase_orders_ran": response.live_coinbase_orders_ran,
        "live_coinbase_read_ran": response.live_coinbase_read_ran,
        "live_command_runtime_enabled": response.live_command_runtime_enabled,
        "live_command_rest_client_available": response.live_command_rest_client_available,
        "live_command_runtime_ready": response.live_command_runtime_ready,
        "live_command_runtime_missing_reason": (
            response.live_command_runtime_missing_reason
        ),
        "live_command_runtime_source": response.live_command_runtime_source,
        "status": response.status,
        "failure_stage": response.failure_stage,
        "message": response.message,
        "admission_decision": response.admission_decision,
    }
    if response.audit_id is not None:
        event_fields["audit_id"] = response.audit_id
    return audit_store.append(AdminApiAuditEvent(**event_fields))


@serialize_idempotent_command
def _execute_idempotent_local_command(
    *,
    idempotency_key: str,
    payload_hash: str,
    actor: AdminApiActor,
    endpoint: str,
    request_id: str,
    operator_intent: str,
    permission: AdminApiPermission,
    action_class: AdminApiActionClass,
    service_method: str,
    client_order_id: str,
    idempotency_store: FileIdempotencyStore,
    audit_store: FileAdminApiAuditStore,
    command_runner: Callable[[], AdminApiCommandResponse],
) -> JSONResponse:
    """Run one audited local mutation without live-exchange admission proofs."""

    require_permission(actor, permission)
    check = idempotency_store.evaluate(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
    )
    if check.decision == AdminApiIdempotencyDecision.REPLAY and check.record:
        response = AdminApiCommandResponse.model_validate(check.record.response)
        return _command_response(response, replayed=True)
    if check.decision == AdminApiIdempotencyDecision.CONFLICT:
        response = AdminApiCommandResponse(
            status=AdminApiCommandStatus.CONFLICT,
            action_class=action_class,
            required_permission=permission,
            service_method=service_method,
            message="Idempotency-Key was already used with a different payload.",
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            client_order_id=client_order_id,
            failure_stage="idempotency",
        )
        response.audit_id = _record_audit(
            audit_store=audit_store,
            actor=actor,
            endpoint=endpoint,
            request_id=request_id,
            operator_intent=operator_intent,
            response=response,
        )
        return _command_response(response)

    response = command_runner()
    if (
        response.action_class != action_class
        or response.required_permission != permission
        or response.service_method != service_method
        or response.client_order_id != client_order_id
    ):
        raise RuntimeError("local_command_response_contract_mismatch")
    response.audit_id = _record_audit(
        audit_store=audit_store,
        actor=actor,
        endpoint=endpoint,
        request_id=request_id,
        operator_intent=operator_intent,
        response=response,
    )
    idempotency_store.put_record(
        IdempotencyRecord(
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            client_order_id=response.client_order_id,
            stealth_order_id=response.stealth_order_id,
            status=response.status,
            response=response.model_dump(mode="json"),
            actor_id=actor.actor_id,
            endpoint=endpoint,
        )
    )
    return _command_response(response)


def _attach_portfolio_scope_evidence(
    response: AdminApiCommandResponse,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
) -> None:
    """Attach one route-bound scope and its proof-chain references."""

    expected_scope = dict(admission_decision.execution_scope or {})
    if not expected_scope:
        return
    observed_scope = {}
    if isinstance(response.data, dict):
        candidate = response.data.get("portfolio_scope")
        if isinstance(candidate, dict):
            observed_scope = dict(candidate)
    portfolio_scope = {**expected_scope, **observed_scope}
    portfolio_scope["scope_consistent"] = bool(
        observed_scope.get("status") == "matched"
        and observed_scope.get("ready") is True
        and observed_scope.get("product_family")
        == expected_scope.get("product_family")
        and observed_scope.get("profile_alias")
        == expected_scope.get("profile_alias")
    )
    portfolio_scope["proof_bindings"] = {
        "payload_hash": admission_decision.payload_hash,
        "approval_snapshot_id": admission_decision.approval_snapshot_id,
        "admission_audit_id": admission_decision.admission_audit_id,
        "cap_guard_decision_id": admission_decision.cap_guard_decision_id,
        "reconciliation_plan_id": admission_decision.reconciliation_plan_id,
    }
    response.portfolio_scope = portfolio_scope


def _idempotency_payload_hash(
    *,
    endpoint: str,
    actor: AdminApiActor,
    operator_intent: str,
    body: dict,
    path_params: dict | None = None,
    backend_execution_scope: dict | None = None,
) -> str:
    payload = {
        "endpoint": endpoint,
        "actor_id": actor.actor_id,
        "roles": [role.value for role in actor.roles],
        "operator_intent": operator_intent,
        "body": body,
        "path_params": path_params or {},
    }
    if backend_execution_scope is not None:
        payload["backend_execution_scope"] = backend_execution_scope
    return make_payload_hash(payload)


def _manual_order_backend_execution_scope() -> dict:
    """Return immutable backend scope committed into manual-order proofs."""

    return {
        "product_family": "SPOT",
        "portfolio_id": os.environ.get(SPOT_PORTFOLIO_ID_ENV),
        "profile_alias": (
            os.environ.get(SPOT_PORTFOLIO_LABEL_ENV, "").strip()
            or DEFAULT_SPOT_PORTFOLIO_LABEL
        ),
        "selection_authority": "cdp_api_key_permissioned_portfolio",
        "request_portfolio_override_allowed": False,
    }


def _manual_order_with_backend_identity(
    *,
    body: ManualOrderRequest,
    actor: AdminApiActor,
    endpoint: str,
    idempotency_key: str,
    payload_hash: str,
) -> ManualOrderRequest:
    """Attach a stable backend-owned client id before admission checks."""

    if body.client_order_id:
        return body

    material = "|".join(
        [
            "coinbase-admin-api",
            "manual-order",
            endpoint,
            actor.actor_id,
            idempotency_key,
            payload_hash,
        ]
    )
    return body.model_copy(
        update={"client_order_id": str(uuid.uuid5(uuid.NAMESPACE_URL, material))}
    )


def _manual_order_admin_cap_guard_context(
    *,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    cap_guard_store: FileAdminApiCapGuardStore,
) -> tuple[str | None, str | None]:
    """Return the exact Admin cap/guard notional context for manual order submit."""

    if (
        not admission_decision.allowed
        or not admission_decision.cap_guard_present
        or not admission_decision.cap_guard_decision_id
    ):
        return None, None

    record = cap_guard_store.find_by_decision_id(
        admission_decision.cap_guard_decision_id
    )
    if (
        record is None
        or not record.allowed
        or record.status != AdminApiGateStatus.PASSED
    ):
        return None, None

    same_command = (
        record.route == admission_decision.route
        and record.method == admission_decision.method
        and record.module_id == admission_decision.module_id
        and record.identity_key == admission_decision.identity_key
        and record.identity_value == admission_decision.identity_value
        and _enum_text(record.action_class)
        == _enum_text(admission_decision.action_class)
        and _enum_text(record.required_permission)
        == _enum_text(admission_decision.required_permission)
        and record.service_method == admission_decision.service_method
        and record.actor_id == admission_decision.actor_id
        and record.operator_intent == admission_decision.operator_intent
        and record.idempotency_key == admission_decision.idempotency_key
        and record.payload_hash == admission_decision.payload_hash
        and record.approval_snapshot_id == admission_decision.approval_snapshot_id
        and record.admission_audit_id == admission_decision.admission_audit_id
    )
    if not same_command:
        return None, None

    return record.decision_id, record.max_submitted_notional_usdc


def _manual_order_admin_cap_guard_limits(
    *,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    cap_guard_store: FileAdminApiCapGuardStore,
) -> tuple[str | None, str | None, str | None]:
    """Return exact submitted and possible-execution ceilings for placement."""

    decision_id, submitted = _manual_order_admin_cap_guard_context(
        admission_decision=admission_decision,
        cap_guard_store=cap_guard_store,
    )
    if decision_id is None:
        return None, None, None
    record = cap_guard_store.find_by_decision_id(decision_id)
    if record is None:
        return None, None, None
    return (
        decision_id,
        submitted,
        record.max_executed_notional_usdc,
    )


def _fill_follow_up_cap_guard_wallet_context(
    *,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    cap_guard_store: FileAdminApiCapGuardStore,
) -> dict[str, str | None]:
    """Return wallet proof evidence from the exact fill-follow-up cap/guard row."""

    if (
        not admission_decision.cap_guard_present
        or not admission_decision.cap_guard_decision_id
    ):
        return {}

    record = cap_guard_store.find_by_decision_id(
        admission_decision.cap_guard_decision_id
    )
    if (
        record is None
        or not record.allowed
        or record.status != AdminApiGateStatus.PASSED
    ):
        return {}

    same_command = (
        record.route == admission_decision.route
        and record.method == admission_decision.method
        and record.module_id == admission_decision.module_id
        and record.identity_key == admission_decision.identity_key
        and record.identity_value == admission_decision.identity_value
        and _enum_text(record.action_class)
        == _enum_text(admission_decision.action_class)
        and _enum_text(record.required_permission)
        == _enum_text(admission_decision.required_permission)
        and record.service_method == admission_decision.service_method
        and record.actor_id == admission_decision.actor_id
        and record.operator_intent == admission_decision.operator_intent
        and record.idempotency_key == admission_decision.idempotency_key
        and record.payload_hash == admission_decision.payload_hash
        and record.approval_snapshot_id == admission_decision.approval_snapshot_id
        and record.admission_audit_id == admission_decision.admission_audit_id
    )
    if not same_command:
        return {}

    return {
        "cap_guard_wallet_proof_ref": f"cap_guard_wallet:{record.decision_id}",
        "cap_guard_wallet_check_status": _enum_text(record.wallet_check_status),
        "cap_guard_wallet_available_notional_usdc": (
            record.wallet_available_notional_usdc
        ),
        "cap_guard_wallet_check_source": record.wallet_check_source,
    }


def _enum_text(value: object) -> str:
    enum_value = getattr(value, "value", value)
    return str(enum_value)


def _should_retry_non_live_controlled_order_after_admission(
    *,
    record: IdempotencyRecord,
    response: AdminApiCommandResponse,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    endpoint: str,
    payload_hash: str,
    operator_intent: str,
    action_class: AdminApiActionClass,
    permission: AdminApiPermission,
    service_method: str,
    route_template: str,
    module_id: str,
    identity_key: str,
) -> bool:
    """Return whether a prior no-live place/cancel may run after admission passes."""

    previous_admission = response.admission_decision
    manual_place = (
        endpoint == "POST /api/v1/orders"
        and route_template == "/api/v1/orders"
        and service_method == "place_manual_order"
        and action_class == AdminApiActionClass.LIVE_EXCHANGE_PLACE
        and permission == AdminApiPermission.ORDER_CREATE
    )
    root_cancel = (
        endpoint.startswith("POST /api/v1/orders/")
        and endpoint.endswith("/cancel")
        and route_template == "/api/v1/orders/{client_order_id}/cancel"
        and service_method == "cancel_order_by_client_order_id"
        and action_class == AdminApiActionClass.LIVE_EXCHANGE_CANCEL
        and permission == AdminApiPermission.ORDER_CANCEL
    )
    root_first_child_cancel = (
        endpoint
        == (
            "POST /api/v1/orders/"
            f"{admission_decision.identity_value}/fill-follow-up/child-cancel"
        )
        and route_template
        == (
            "/api/v1/orders/{root_client_order_id}/fill-follow-up/"
            "child-cancel"
        )
        and service_method
        == "cancel_order_fill_follow_up_child_by_root_client_order_id"
        and action_class == AdminApiActionClass.LIVE_EXCHANGE_CANCEL
        and permission == AdminApiPermission.ORDER_CANCEL
        and operator_intent
        == CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT
    )
    controlled_first_child_reveal = (
        endpoint
        == (
            "POST /api/v1/stealth/orders/"
            f"{admission_decision.identity_value}/reveal"
        )
        and route_template
        == "/api/v1/stealth/orders/{stealth_order_id}/reveal"
        and service_method == "reveal_stealth_order_by_stealth_order_id"
        and action_class == AdminApiActionClass.LIVE_EXCHANGE_PLACE
        and permission == AdminApiPermission.ORDER_CREATE
        and operator_intent
        in {
            CONTROLLED_FIRST_CHILD_REVEAL_OPERATOR_INTENT,
            CONTROLLED_V15_FIRST_CHILD_REVEAL_OPERATOR_INTENT,
        }
    )
    controlled_first_child_cancel = (
        endpoint
        == (
            "POST /api/v1/stealth/orders/"
            f"{admission_decision.identity_value}/cancel"
        )
        and route_template
        == "/api/v1/stealth/orders/{stealth_order_id}/cancel"
        and service_method == "cancel_stealth_order_by_stealth_order_id"
        and action_class == AdminApiActionClass.LIVE_EXCHANGE_CANCEL
        and permission == AdminApiPermission.ORDER_CANCEL
        and operator_intent
        in {
            CONTROLLED_FIRST_CHILD_CANCEL_OPERATOR_INTENT,
            CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT,
        }
    )
    controlled_first_child = (
        (controlled_first_child_reveal or controlled_first_child_cancel)
        and module_id == "stealth_orders"
        and identity_key == "stealth_order_id"
    )
    root_order_action = (
        (manual_place or root_cancel or root_first_child_cancel)
        and module_id == "spot_operations"
        and identity_key == "client_order_id"
    )
    response_identity_matches = (
        root_order_action
        and response.client_order_id == admission_decision.identity_value
    ) or (
        controlled_first_child
        and response.stealth_order_id == admission_decision.identity_value
    )
    transient_root_cancel_readiness = bool(
        root_first_child_cancel
        and response_identity_matches
        and record.endpoint == endpoint
        and record.payload_hash == payload_hash
        and record.status == AdminApiCommandStatus.REJECTED
        and response.status == AdminApiCommandStatus.REJECTED
        and (
            response.failure_stage == "root_child_cancel_readiness"
            or (
                isinstance(response.data, dict)
                and isinstance(response.data.get("semantic_claim"), dict)
                and response.data["semantic_claim"].get("outcome")
                == "claimed"
                and response.data["semantic_claim"].get(
                    "reconciliation_required"
                )
                is False
            )
        )
        and response.action_class == action_class
        and response.required_permission == permission
        and response.service_method == service_method
        and response.live_exchange_submitted is False
        and response.live_coinbase_orders_ran is False
        and previous_admission is not None
        and previous_admission.allowed is True
        and previous_admission.route == route_template
        and previous_admission.method == "POST"
        and previous_admission.module_id == module_id
        and previous_admission.identity_key == identity_key
        and previous_admission.identity_value
        == admission_decision.identity_value
        and previous_admission.action_class == action_class
        and previous_admission.required_permission == permission
        and previous_admission.service_method == service_method
        and previous_admission.operator_intent == operator_intent
        and previous_admission.payload_hash == payload_hash
        and previous_admission.live_exchange_submitted is False
        and admission_decision.allowed is True
        and admission_decision.route == route_template
        and admission_decision.method == "POST"
        and admission_decision.module_id == module_id
        and admission_decision.identity_key == identity_key
        and admission_decision.identity_value
        == previous_admission.identity_value
        and admission_decision.action_class == action_class
        and admission_decision.required_permission == permission
        and admission_decision.service_method == service_method
        and admission_decision.operator_intent == operator_intent
        and admission_decision.payload_hash == payload_hash
        and admission_decision.live_exchange_submitted is False
    )
    if transient_root_cancel_readiness:
        return True
    semantic_claim = (
        response.data.get("semantic_claim")
        if isinstance(response.data, dict)
        and isinstance(response.data.get("semantic_claim"), dict)
        else {}
    )
    post_boundary_root_cancel_reconciliation = bool(
        root_first_child_cancel
        and response_identity_matches
        and record.endpoint == endpoint
        and record.payload_hash == payload_hash
        and record.status == AdminApiCommandStatus.REJECTED
        and response.status == AdminApiCommandStatus.REJECTED
        and semantic_claim.get("outcome") == "unknown"
        and semantic_claim.get("reconciliation_required") is True
        and previous_admission is not None
        and previous_admission.allowed is True
        and previous_admission.route == route_template
        and previous_admission.method == "POST"
        and previous_admission.module_id == module_id
        and previous_admission.identity_key == identity_key
        and previous_admission.identity_value
        == admission_decision.identity_value
        and previous_admission.action_class == action_class
        and previous_admission.required_permission == permission
        and previous_admission.service_method == service_method
        and previous_admission.operator_intent == operator_intent
        and previous_admission.payload_hash == payload_hash
        and admission_decision.allowed is True
        and admission_decision.route == route_template
        and admission_decision.method == "POST"
        and admission_decision.module_id == module_id
        and admission_decision.identity_key == identity_key
        and admission_decision.identity_value
        == previous_admission.identity_value
        and admission_decision.action_class == action_class
        and admission_decision.required_permission == permission
        and admission_decision.service_method == service_method
        and admission_decision.operator_intent == operator_intent
        and admission_decision.payload_hash == payload_hash
    )
    if post_boundary_root_cancel_reconciliation:
        return True
    return (
        (root_order_action or controlled_first_child)
        and response_identity_matches
        and record.endpoint == endpoint
        and record.payload_hash == payload_hash
        and record.status == AdminApiCommandStatus.NOT_IMPLEMENTED
        and response.status == AdminApiCommandStatus.NOT_IMPLEMENTED
        and response.action_class == action_class
        and response.required_permission == permission
        and response.service_method == service_method
        and response.live_exchange_submitted is False
        and response.live_coinbase_orders_ran is False
        and previous_admission is not None
        and previous_admission.allowed is False
        and previous_admission.route == route_template
        and previous_admission.method == "POST"
        and previous_admission.module_id == module_id
        and previous_admission.identity_key == identity_key
        and previous_admission.identity_value == admission_decision.identity_value
        and previous_admission.action_class == action_class
        and previous_admission.required_permission == permission
        and previous_admission.service_method == service_method
        and previous_admission.operator_intent == operator_intent
        and previous_admission.payload_hash == payload_hash
        and previous_admission.live_exchange_submitted is False
        and admission_decision.allowed is True
        and admission_decision.route == route_template
        and admission_decision.method == "POST"
        and admission_decision.module_id == module_id
        and admission_decision.identity_key == identity_key
        and admission_decision.action_class == action_class
        and admission_decision.required_permission == permission
        and admission_decision.service_method == service_method
        and admission_decision.operator_intent == operator_intent
        and admission_decision.live_exchange_submitted is False
    )


@serialize_idempotent_command
def _execute_idempotent_command(
    *,
    idempotency_key: str,
    payload_hash: str,
    actor: AdminApiActor,
    endpoint: str,
    request_id: str,
    operator_intent: str,
    permission: AdminApiPermission,
    action_class: AdminApiActionClass,
    service_method: str,
    route_template: str,
    module_id: str,
    identity_key: str,
    identity_value: str | None,
    idempotency_store: FileIdempotencyStore,
    audit_store: FileAdminApiAuditStore,
    approval_store: FileAdminApiApprovalStore,
    cap_guard_store: FileAdminApiCapGuardStore,
    reconciliation_store: FileAdminApiReconciliationStore,
    live_execution_service: AdminApiLiveExecutionService,
    execution_scope: dict | None = None,
    stealth_exchange_truth_proof_store: FileStealthExchangeTruthProofStore | None = None,
    stealth_mutation_claim_proof_store: FileStealthMutationClaimProofStore | None = None,
    stealth_manager_policy_proof_store: (
        FileStealthManagerInvocationPolicyProofStore | None
    ) = None,
    stealth_coinbase_exchange_policy_proof_store: (
        FileStealthCoinbaseExchangeSubmissionPolicyProofStore | None
    ) = None,
    stealth_post_write_reconciliation_policy_proof_store: (
        FileStealthPostWriteReconciliationExecutionPolicyProofStore | None
    ) = None,
    stealth_state_mutation_policy_proof_store: (
        FileStealthStateMutationPolicyProofStore | None
    ) = None,
    stealth_recovery_proof_store: FileStealthRecoveryProofStore | None = None,
    stealth_reveal_trigger_proof_store: (
        FileStealthRevealTriggerProofStore | None
    ) = None,
    stealth_reconciliation_proof_store: (
        FileStealthReconciliationProofStore | None
    ) = None,
    stealth_cancel_replace_proof_store: (
        FileStealthCancelReplaceProofStore | None
    ) = None,
    stealth_post_write_reconciliation_proof_store: (
        FileStealthPostWriteReconciliationProofStore | None
    ) = None,
    stealth_post_write_execution_journal_store: (
        FileStealthPostWriteExecutionJournalStore | None
    ) = None,
    stealth_post_write_reconciliation_verification_store: (
        FileStealthPostWriteReconciliationVerificationStore | None
    ) = None,
    command_runner: Callable[[], AdminApiCommandResponse] | None = None,
    command_runner_with_admission: Callable[
        [AdminLiveAdmissionDecisionEvidence],
        AdminApiCommandResponse,
    ] | None = None,
    admission_override: Callable[
        [AdminLiveAdmissionDecisionEvidence],
        AdminLiveAdmissionDecisionEvidence,
    ] | None = None,
    cap_guard_product_scope: str | None = None,
    client_order_id: str | None = None,
    stealth_order_id: str | None = None,
) -> JSONResponse:
    require_permission(actor, permission)
    admission_decision = evaluate_command_live_admission(
        route=route_template,
        method=endpoint.split(" ", 1)[0],
        module_id=module_id,
        identity_key=identity_key,
        identity_value=identity_value,
        action_class=action_class,
        required_permission=permission,
        service_method=service_method,
        actor_id=actor.actor_id,
        idempotency_key=idempotency_key,
        operator_intent=operator_intent,
        payload_hash=payload_hash,
        approval_store=approval_store,
        audit_store=audit_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        cap_guard_product_scope=cap_guard_product_scope,
    )
    unsupported_live_route = (
        AdminApiLiveAdmissionBlocker.UNSUPPORTED_LIVE_ROUTE
        in admission_decision.blockers
    )
    if (
        admission_override is not None
        and not admission_decision.allowed
        and not unsupported_live_route
    ):
        admission_decision = admission_override(admission_decision)
    public_execution_scope = (
        serialize_public_spot_portfolio_scope(execution_scope)
        if execution_scope is not None
        else None
    )
    if public_execution_scope is not None and cap_guard_product_scope is not None:
        public_execution_scope["product_scope"] = cap_guard_product_scope
    admission_decision.execution_scope = public_execution_scope
    check = idempotency_store.evaluate(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
    )
    if check.decision == AdminApiIdempotencyDecision.REPLAY and check.record:
        payload = dict(check.record.response)
        response = AdminApiCommandResponse.model_validate(payload)
        if not _should_retry_non_live_controlled_order_after_admission(
            record=check.record,
            response=response,
            admission_decision=admission_decision,
            endpoint=endpoint,
            payload_hash=payload_hash,
            operator_intent=operator_intent,
            action_class=action_class,
            permission=permission,
            service_method=service_method,
            route_template=route_template,
            module_id=module_id,
            identity_key=identity_key,
        ):
            return _command_response(response, replayed=True)
    if check.decision == AdminApiIdempotencyDecision.CONFLICT:
        response = AdminApiCommandResponse(
            status=AdminApiCommandStatus.CONFLICT,
            action_class=action_class,
            required_permission=permission,
            service_method=service_method,
            message="Idempotency-Key was already used with a different payload.",
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            client_order_id=client_order_id,
            stealth_order_id=stealth_order_id,
            admission_decision=admission_decision,
            failure_stage="idempotency",
        )
        _attach_portfolio_scope_evidence(response, admission_decision)
        response.stealth_admission_context = _build_stealth_command_admission_context(
            admission_decision
        )
        _attach_stealth_execution_posture(
            response,
            admission_decision,
            stealth_exchange_truth_proof_store=stealth_exchange_truth_proof_store,
            stealth_mutation_claim_proof_store=stealth_mutation_claim_proof_store,
            stealth_manager_policy_proof_store=stealth_manager_policy_proof_store,
            stealth_coinbase_exchange_policy_proof_store=(
                stealth_coinbase_exchange_policy_proof_store
            ),
            stealth_post_write_reconciliation_policy_proof_store=(
                stealth_post_write_reconciliation_policy_proof_store
            ),
            stealth_state_mutation_policy_proof_store=(
                stealth_state_mutation_policy_proof_store
            ),
            stealth_recovery_proof_store=stealth_recovery_proof_store,
            stealth_reveal_trigger_proof_store=stealth_reveal_trigger_proof_store,
            stealth_reconciliation_proof_store=stealth_reconciliation_proof_store,
            stealth_cancel_replace_proof_store=stealth_cancel_replace_proof_store,
            stealth_post_write_reconciliation_proof_store=(
                stealth_post_write_reconciliation_proof_store
            ),
            stealth_post_write_execution_journal_store=(
                stealth_post_write_execution_journal_store
            ),
            stealth_post_write_reconciliation_verification_store=(
                stealth_post_write_reconciliation_verification_store
            ),
        )
        response.audit_id = _record_audit(
            audit_store=audit_store,
            actor=actor,
            endpoint=endpoint,
            request_id=request_id,
            operator_intent=operator_intent,
            response=response,
        )
        return _command_response(response)

    if command_runner_with_admission is not None:
        response = command_runner_with_admission(admission_decision)
    elif command_runner is not None:
        response = command_runner()
    else:
        raise ValueError("A command runner is required.")
    response.admission_decision = admission_decision
    _attach_portfolio_scope_evidence(response, admission_decision)
    response.stealth_admission_context = _build_stealth_command_admission_context(
        admission_decision
    )
    _attach_stealth_execution_posture(
        response,
        admission_decision,
        stealth_exchange_truth_proof_store=stealth_exchange_truth_proof_store,
        stealth_mutation_claim_proof_store=stealth_mutation_claim_proof_store,
        stealth_manager_policy_proof_store=stealth_manager_policy_proof_store,
        stealth_coinbase_exchange_policy_proof_store=(
            stealth_coinbase_exchange_policy_proof_store
        ),
        stealth_post_write_reconciliation_policy_proof_store=(
            stealth_post_write_reconciliation_policy_proof_store
        ),
        stealth_state_mutation_policy_proof_store=(
            stealth_state_mutation_policy_proof_store
        ),
        stealth_recovery_proof_store=stealth_recovery_proof_store,
        stealth_reveal_trigger_proof_store=stealth_reveal_trigger_proof_store,
        stealth_reconciliation_proof_store=stealth_reconciliation_proof_store,
        stealth_cancel_replace_proof_store=stealth_cancel_replace_proof_store,
        stealth_post_write_reconciliation_proof_store=(
            stealth_post_write_reconciliation_proof_store
        ),
        stealth_post_write_execution_journal_store=(
            stealth_post_write_execution_journal_store
        ),
        stealth_post_write_reconciliation_verification_store=(
            stealth_post_write_reconciliation_verification_store
        ),
    )
    if response.guard is None:
        response.guard = {}
    response.guard["admission_decision"] = admission_decision.model_dump(mode="json")
    response.audit_id = _record_audit(
        audit_store=audit_store,
        actor=actor,
        endpoint=endpoint,
        request_id=request_id,
        operator_intent=operator_intent,
        response=response,
    )
    idempotency_store.put_record(
        IdempotencyRecord(
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            client_order_id=response.client_order_id,
            stealth_order_id=response.stealth_order_id,
            status=response.status,
            response=response.model_dump(mode="json"),
            actor_id=actor.actor_id,
            endpoint=endpoint,
        )
    )
    return _command_response(response)


@router.get(
    "/orders",
    response_model=AdminOrderListResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read local orders keyed by client_order_id",
)
def list_orders(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
    product_id: str | None = None,
    order_status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    """Read local order_parent evidence without contacting Coinbase."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_response(
        service.build_order_list(
            product_id=product_id,
            status=order_status,
            limit=limit,
            offset=offset,
        )
    )


@router.get(
    "/orders/{client_order_id}",
    response_model=AdminOrderDetailResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read one local order by client_order_id",
)
def get_order_by_client_order_id(
    client_order_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read one local order row by client_order_id."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_response(service.build_order_detail(client_order_id=client_order_id))


@router.get(
    "/orders/{source_client_order_id}/follow-up-intent",
    response_model=AdminOrderFollowUpIntentReadResponse,
    responses=FOLLOW_UP_INTENT_READ_ROUTE_RESPONSES,
    summary="Read one backend-owned future follow-up intent slot",
)
def get_order_follow_up_intent(
    source_client_order_id: Annotated[
        str,
        Path(
            min_length=36,
            max_length=36,
            pattern=_CANONICAL_UUID_PATH_PATTERN,
        ),
    ],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    _feature_enabled: Annotated[
        None,
        Depends(require_operator_follow_up_intent_enabled),
    ],
    service: Annotated[
        OperatorFollowUpIntentService,
        Depends(get_order_follow_up_intent_service),
    ],
) -> JSONResponse:
    """Read authoritative local eligibility and intent evidence only."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    try:
        payload = service.read(source_client_order_id=source_client_order_id)
    except OperatorFollowUpIntentError as exc:
        _raise_follow_up_intent_error(exc)
    return _read_response(payload)


@router.post(
    "/orders/{source_client_order_id}/follow-up-intent",
    response_model=AdminOrderFollowUpIntentAttachResponse,
    status_code=status.HTTP_200_OK,
    responses=FOLLOW_UP_INTENT_ATTACH_ROUTE_RESPONSES,
    summary="Attach one durable future follow-up intent without executing it",
)
def attach_order_follow_up_intent(
    body: AdminOrderFollowUpIntentAttachRequest,
    source_client_order_id: Annotated[
        str,
        Path(
            min_length=36,
            max_length=36,
            pattern=_CANONICAL_UUID_PATH_PATTERN,
        ),
    ],
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=255,
            pattern=_VISIBLE_ASCII_HEADER_PATTERN,
        ),
    ],
    correlation_id: Annotated[
        str,
        Header(
            alias="X-Correlation-Id",
            min_length=1,
            max_length=255,
            pattern=_VISIBLE_ASCII_HEADER_PATTERN,
        ),
    ],
    operator_intent: Annotated[
        Literal["attach_single_follow_up_intent"],
        Header(alias="X-Operator-Intent"),
    ],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    _feature_enabled: Annotated[
        None,
        Depends(require_operator_follow_up_intent_enabled),
    ],
    service: Annotated[
        OperatorFollowUpIntentService,
        Depends(get_order_follow_up_intent_service),
    ],
) -> JSONResponse:
    """Persist one backend-derived slot after atomic eligibility validation."""

    require_permission(actor, AdminApiPermission.ORDER_CREATE)
    context = OperatorFollowUpIntentRequestContext(
        actor_id=actor.actor_id,
        roles=tuple(role.value for role in actor.roles),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
    )
    try:
        payload = service.attach(
            source_client_order_id=source_client_order_id,
            request=body,
            context=context,
        )
    except OperatorFollowUpIntentError as exc:
        _raise_follow_up_intent_error(exc)
    return _follow_up_intent_attach_response(payload)


@router.get(
    "/orders/{source_client_order_id}/follow-up-intent/materialization",
    response_model=AdminOrderFollowUpMaterializationReadResponse,
    responses=FOLLOW_UP_MATERIALIZATION_READ_ROUTE_RESPONSES,
    summary="Read local follow-up materialization eligibility and one-use state",
)
def get_order_follow_up_materialization(
    source_client_order_id: Annotated[
        str,
        Path(
            min_length=36,
            max_length=36,
            pattern=_CANONICAL_UUID_PATH_PATTERN,
        ),
    ],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    _feature_enabled: Annotated[
        None,
        Depends(require_operator_follow_up_intent_enabled),
    ],
    service: Annotated[
        OperatorFollowUpMaterializationService,
        Depends(get_order_follow_up_materialization_service),
    ],
) -> JSONResponse:
    """Read PostgreSQL evidence only; this GET cannot contact Coinbase."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    try:
        payload = service.read(source_client_order_id=source_client_order_id)
    except OperatorFollowUpMaterializationError as exc:
        _raise_follow_up_materialization_error(exc)
    return _read_response(payload)


@router.post(
    "/orders/{source_client_order_id}/follow-up-intent/materialization",
    response_model=AdminOrderFollowUpMaterializationCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=FOLLOW_UP_MATERIALIZATION_COMMAND_ROUTE_RESPONSES,
    summary="Explicitly authorize one attached follow-up intent materialization",
)
def materialize_order_follow_up_intent(
    body: AdminOrderFollowUpMaterializationRequest,
    source_client_order_id: Annotated[
        str,
        Path(
            min_length=36,
            max_length=36,
            pattern=_CANONICAL_UUID_PATH_PATTERN,
        ),
    ],
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=255,
            pattern=_VISIBLE_ASCII_HEADER_PATTERN,
        ),
    ],
    correlation_id: Annotated[
        str,
        Header(
            alias="X-Correlation-Id",
            min_length=1,
            max_length=255,
            pattern=_VISIBLE_ASCII_HEADER_PATTERN,
        ),
    ],
    operator_intent: Annotated[
        Literal["authorize_and_materialize_follow_up_intent"],
        Header(alias="X-Operator-Intent"),
    ],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    _feature_enabled: Annotated[
        None,
        Depends(require_operator_follow_up_intent_enabled),
    ],
    service: Annotated[
        OperatorFollowUpMaterializationService,
        Depends(get_order_follow_up_materialization_service),
    ],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
) -> JSONResponse:
    """Forward only fixed acknowledgements and authenticated operator context."""

    action_class = AdminApiActionClass.LIVE_EXCHANGE_PLACE
    permission = AdminApiPermission.ORDER_CREATE
    endpoint = _FOLLOW_UP_MATERIALIZATION_AUDIT_ENDPOINT
    receipt_audit_id = _follow_up_materialization_audit_id(
        phase="authorization_received_for_evaluation",
        endpoint=endpoint,
        actor=actor,
        source_client_order_id=source_client_order_id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        action_class=action_class,
        permission=permission,
    )
    try:
        _append_follow_up_materialization_audit(
            audit_store=audit_store,
            audit_id=receipt_audit_id,
            actor=actor,
            endpoint=endpoint,
            source_client_order_id=source_client_order_id,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            operator_intent=operator_intent,
            action_class=action_class,
            permission=permission,
            status_value="received",
            failure_stage="authorization_received_for_evaluation",
            message=_FOLLOW_UP_MATERIALIZATION_RECEIPT_MESSAGE,
        )
    except Exception:
        return _follow_up_materialization_error_response(
            http_status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            diagnostic_code="follow_up_materialization_audit_unavailable",
            correlation_id=correlation_id,
            audit_id=None,
        )
    context = OperatorFollowUpMaterializationRequestContext(
        actor_id=actor.actor_id,
        roles=tuple(role.value for role in actor.roles),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        audit_id=receipt_audit_id,
        environment=_follow_up_materialization_environment(),
    )
    try:
        require_permission(actor, permission)
        payload = service.materialize(
            source_client_order_id=source_client_order_id,
            request=body,
            context=context,
        )
    except HTTPException as exc:
        materialization_error = OperatorFollowUpMaterializationError(
            str(exc.detail),
            exc.status_code,
            failure_stage="pre_exchange_evaluation",
            live_coinbase_read_ran=False,
            live_coinbase_orders_ran=False,
            live_exchange_submitted=False,
        )
        failure_stage, live_read_ran, live_orders_ran, live_submitted = (
            _follow_up_materialization_execution_evidence(materialization_error)
        )
        try:
            outcome_audit_id = _record_follow_up_materialization_outcome_error(
                audit_store=audit_store,
                actor=actor,
                endpoint=endpoint,
                source_client_order_id=source_client_order_id,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                operator_intent=operator_intent,
                action_class=action_class,
                permission=permission,
                diagnostic_code=materialization_error.code,
                http_status_code=materialization_error.http_status_code,
                failure_stage=failure_stage,
                live_coinbase_read_ran=live_read_ran,
                live_coinbase_orders_ran=live_orders_ran,
                live_exchange_submitted=live_submitted,
            )
        except Exception:
            return _follow_up_materialization_error_response(
                http_status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                diagnostic_code="follow_up_materialization_audit_unavailable",
                correlation_id=correlation_id,
                audit_id=receipt_audit_id,
                live_coinbase_orders_ran=live_orders_ran,
            )
        return _follow_up_materialization_error_response(
            http_status_code=materialization_error.http_status_code,
            diagnostic_code=materialization_error.code,
            correlation_id=correlation_id,
            audit_id=outcome_audit_id,
            live_coinbase_orders_ran=live_orders_ran,
        )
    except OperatorFollowUpMaterializationError as exc:
        failure_stage, live_read_ran, live_orders_ran, live_submitted = (
            _follow_up_materialization_execution_evidence(exc)
        )
        try:
            outcome_audit_id = _record_follow_up_materialization_outcome_error(
                audit_store=audit_store,
                actor=actor,
                endpoint=endpoint,
                source_client_order_id=source_client_order_id,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                operator_intent=operator_intent,
                action_class=action_class,
                permission=permission,
                diagnostic_code=exc.code,
                http_status_code=exc.http_status_code,
                failure_stage=failure_stage,
                live_coinbase_read_ran=live_read_ran,
                live_coinbase_orders_ran=live_orders_ran,
                live_exchange_submitted=live_submitted,
            )
        except Exception:
            return _follow_up_materialization_error_response(
                http_status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                diagnostic_code="follow_up_materialization_audit_unavailable",
                correlation_id=correlation_id,
                audit_id=receipt_audit_id,
                live_coinbase_orders_ran=live_orders_ran,
            )
        return _follow_up_materialization_error_response(
            http_status_code=exc.http_status_code,
            diagnostic_code=exc.code,
            correlation_id=correlation_id,
            audit_id=outcome_audit_id,
            live_coinbase_orders_ran=live_orders_ran,
        )
    if (
        str(getattr(payload, "audit_id", "")) != receipt_audit_id
        or str(getattr(getattr(payload, "attempt", None), "audit_id", ""))
        != receipt_audit_id
    ):
        return _follow_up_materialization_error_response(
            http_status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            diagnostic_code="follow_up_materialization_audit_binding_conflict",
            correlation_id=correlation_id,
            audit_id=receipt_audit_id,
            live_coinbase_orders_ran=True,
        )
    return _follow_up_materialization_response(payload)


@router.post(
    "/orders/{source_client_order_id}/follow-up-intent/materialization/safe-closeout",
    response_model=AdminOrderFollowUpMaterializationCancelResponse,
    status_code=status.HTTP_200_OK,
    responses=FOLLOW_UP_MATERIALIZATION_CANCEL_ROUTE_RESPONSES,
    summary="Authorize at most one Cancel for the exact materialized child",
)
def safe_closeout_materialized_follow_up_intent(
    body: AdminOrderFollowUpMaterializationCancelRequest,
    source_client_order_id: Annotated[
        str,
        Path(
            min_length=36,
            max_length=36,
            pattern=_CANONICAL_UUID_PATH_PATTERN,
        ),
    ],
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=255,
            pattern=_VISIBLE_ASCII_HEADER_PATTERN,
        ),
    ],
    correlation_id: Annotated[
        str,
        Header(
            alias="X-Correlation-Id",
            min_length=1,
            max_length=255,
            pattern=_VISIBLE_ASCII_HEADER_PATTERN,
        ),
    ],
    operator_intent: Annotated[
        Literal["safe_closeout_materialized_follow_up_intent"],
        Header(alias="X-Operator-Intent"),
    ],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    _feature_enabled: Annotated[
        None,
        Depends(require_operator_follow_up_intent_enabled),
    ],
    service: Annotated[
        OperatorFollowUpMaterializationService,
        Depends(get_order_follow_up_materialization_service),
    ],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
) -> JSONResponse:
    """Resolve the exact child in the backend; no exchange ID is accepted."""

    action_class = AdminApiActionClass.LIVE_EXCHANGE_CANCEL
    permission = AdminApiPermission.ORDER_CANCEL
    endpoint = _FOLLOW_UP_MATERIALIZATION_CLOSEOUT_AUDIT_ENDPOINT
    receipt_audit_id = _follow_up_materialization_audit_id(
        phase="authorization_received_for_evaluation",
        endpoint=endpoint,
        actor=actor,
        source_client_order_id=source_client_order_id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        action_class=action_class,
        permission=permission,
    )
    try:
        _append_follow_up_materialization_audit(
            audit_store=audit_store,
            audit_id=receipt_audit_id,
            actor=actor,
            endpoint=endpoint,
            source_client_order_id=source_client_order_id,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            operator_intent=operator_intent,
            action_class=action_class,
            permission=permission,
            status_value="received",
            failure_stage="authorization_received_for_evaluation",
            message=_FOLLOW_UP_MATERIALIZATION_RECEIPT_MESSAGE,
        )
    except Exception:
        return _follow_up_materialization_error_response(
            http_status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            diagnostic_code="follow_up_materialization_audit_unavailable",
            correlation_id=correlation_id,
            audit_id=None,
        )
    context = OperatorFollowUpMaterializationRequestContext(
        actor_id=actor.actor_id,
        roles=tuple(role.value for role in actor.roles),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        audit_id=receipt_audit_id,
        environment=_follow_up_materialization_environment(),
    )
    try:
        require_permission(actor, permission)
        payload = service.safe_closeout(
            source_client_order_id=source_client_order_id,
            request=body,
            context=context,
        )
    except HTTPException as exc:
        materialization_error = OperatorFollowUpMaterializationError(
            str(exc.detail),
            exc.status_code,
            failure_stage="pre_exchange_evaluation",
            live_coinbase_read_ran=False,
            live_coinbase_orders_ran=False,
            live_exchange_submitted=False,
        )
        failure_stage, live_read_ran, live_orders_ran, live_submitted = (
            _follow_up_materialization_execution_evidence(materialization_error)
        )
        try:
            outcome_audit_id = _record_follow_up_materialization_outcome_error(
                audit_store=audit_store,
                actor=actor,
                endpoint=endpoint,
                source_client_order_id=source_client_order_id,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                operator_intent=operator_intent,
                action_class=action_class,
                permission=permission,
                diagnostic_code=materialization_error.code,
                http_status_code=materialization_error.http_status_code,
                failure_stage=failure_stage,
                live_coinbase_read_ran=live_read_ran,
                live_coinbase_orders_ran=live_orders_ran,
                live_exchange_submitted=live_submitted,
            )
        except Exception:
            return _follow_up_materialization_error_response(
                http_status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                diagnostic_code="follow_up_materialization_audit_unavailable",
                correlation_id=correlation_id,
                audit_id=receipt_audit_id,
                live_coinbase_orders_ran=live_orders_ran,
            )
        return _follow_up_materialization_error_response(
            http_status_code=materialization_error.http_status_code,
            diagnostic_code=materialization_error.code,
            correlation_id=correlation_id,
            audit_id=outcome_audit_id,
            live_coinbase_orders_ran=live_orders_ran,
        )
    except OperatorFollowUpMaterializationError as exc:
        failure_stage, live_read_ran, live_orders_ran, live_submitted = (
            _follow_up_materialization_execution_evidence(exc)
        )
        try:
            outcome_audit_id = _record_follow_up_materialization_outcome_error(
                audit_store=audit_store,
                actor=actor,
                endpoint=endpoint,
                source_client_order_id=source_client_order_id,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                operator_intent=operator_intent,
                action_class=action_class,
                permission=permission,
                diagnostic_code=exc.code,
                http_status_code=exc.http_status_code,
                failure_stage=failure_stage,
                live_coinbase_read_ran=live_read_ran,
                live_coinbase_orders_ran=live_orders_ran,
                live_exchange_submitted=live_submitted,
            )
        except Exception:
            return _follow_up_materialization_error_response(
                http_status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                diagnostic_code="follow_up_materialization_audit_unavailable",
                correlation_id=correlation_id,
                audit_id=receipt_audit_id,
                live_coinbase_orders_ran=live_orders_ran,
            )
        return _follow_up_materialization_error_response(
            http_status_code=exc.http_status_code,
            diagnostic_code=exc.code,
            correlation_id=correlation_id,
            audit_id=outcome_audit_id,
            live_coinbase_orders_ran=live_orders_ran,
        )
    if (
        str(getattr(payload, "audit_id", "")) != receipt_audit_id
        or str(getattr(getattr(payload, "attempt", None), "audit_id", ""))
        != receipt_audit_id
    ):
        return _follow_up_materialization_error_response(
            http_status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            diagnostic_code="follow_up_materialization_audit_binding_conflict",
            correlation_id=correlation_id,
            audit_id=receipt_audit_id,
            live_coinbase_orders_ran=True,
        )
    return _follow_up_materialization_response(payload)


@router.post(
    "/orders/{client_order_id}/reconciliation",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Reconcile one durable Spot root from authoritative Coinbase readback",
)
def reconcile_order_by_client_order_id(
    request: Request,
    body: ReconcileOrderRequest,
    client_order_id: Annotated[str, Path(min_length=1)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
) -> JSONResponse:
    """Run one bounded readback action and synchronize only the matching root."""

    endpoint = f"{request.method} {request.url.path}"
    execution_scope = _manual_order_backend_execution_scope()
    envelope = _build_envelope(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
    )
    payload_hash = _idempotency_payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
        path_params={"client_order_id": client_order_id},
        backend_execution_scope=execution_scope,
    )
    audit_id = str(uuid.uuid4())
    return _execute_idempotent_local_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.ORDER_CANCEL,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method="reconcile_order_by_client_order_id",
        client_order_id=client_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        command_runner=lambda: service.reconcile_order_by_client_order_id(
            ReconcileOrderCommand(
                envelope=envelope,
                audit_id=audit_id,
                client_order_id=client_order_id,
                request=body,
                allow_live_read=True,
            )
        ),
    )


@router.get(
    "/orders/{client_order_id}/fill-readback",
    response_model=SpotOrderFillReadbackResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read locally persisted Spot fill evidence by client_order_id",
)
def get_spot_order_fill_readback(
    client_order_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminMvpService, Depends(get_mvp_service)],
    product_id: str | None = None,
    backend_contract_ref: str | None = None,
    fill_limit: Annotated[int, Query(ge=1, le=500)] = 100,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
    operator_intent: Annotated[str | None, Header(alias="X-Operator-Intent")] = None,
) -> JSONResponse:
    """Read sanitized durable Spot fill evidence with zero Coinbase calls/writes."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    query: dict[str, str] = {"fill_limit": str(fill_limit)}
    if product_id is not None:
        query["product_id"] = product_id
    if backend_contract_ref is not None:
        query["backend_contract_ref"] = backend_contract_ref
    result = service.get_read_response(
        f"/api/v1/orders/{client_order_id}/fill-readback",
        query,
        _admin_mvp_read_context(
            actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            operator_intent=operator_intent,
        ),
    )
    return JSONResponse(
        status_code=result.status_code,
        content=jsonable_encoder(result.body),
        headers=result.headers,
    )


@router.get(
    "/orders/{client_order_id}/fill-follow-up/replay",
    response_model=AdminOrderFillFollowUpReplayResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Replay local fill follow-up decision evidence without live execution",
)
def get_order_fill_follow_up_replay(
    client_order_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Replay local fill follow-up evidence without mutating order state."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_response(
        service.build_order_fill_follow_up_replay(client_order_id=client_order_id)
    )


@router.get(
    "/orders/{client_order_id}/fill-follow-up/live-readiness",
    response_model=AdminOrderFillFollowUpLiveReadinessResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read guarded fill follow-up live-readiness blockers",
)
def get_order_fill_follow_up_live_readiness(
    client_order_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read fill follow-up live-readiness without acquiring claims or executing."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_response(
        service.build_order_fill_follow_up_live_readiness(
            client_order_id=client_order_id
        )
    )


@router.get(
    "/orders/{client_order_id}/fill-follow-up/chain",
    response_model=AdminOrderFillFollowUpChainResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read fill follow-up parent/child chain evidence",
)
def get_order_fill_follow_up_chain(
    client_order_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read fill follow-up parent/child chain evidence without executing."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_response(
        service.build_order_fill_follow_up_chain(client_order_id=client_order_id)
    )


@router.get(
    "/orders/{root_client_order_id}/fill-follow-up/child-cancel/readiness",
    response_model=AdminOrderFillFollowUpChildCancelReadinessResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Read historical selected-child cancel evidence as source-disabled",
)
def get_order_fill_follow_up_child_cancel_readiness(
    root_client_order_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
    controlled_plan_sha256: Annotated[
        str | None,
        Query(pattern=r"^[0-9a-f]{64}$"),
    ] = None,
) -> JSONResponse:
    """Resolve child and sealed plan authority without browser child identity."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    payload = service.build_order_fill_follow_up_child_cancel_readiness(
        root_client_order_id=root_client_order_id,
        controlled_plan_sha256=controlled_plan_sha256,
    )
    blockers = list(payload.blockers)
    if "source_disabled_not_implemented" not in blockers:
        blockers.append("source_disabled_not_implemented")
    payload = payload.model_copy(
        update={
            "ready": False,
            "readiness_status": "source_disabled",
            "backend_decision": "blocked",
            "blockers": blockers,
            "browser_authority": "display_only",
            "detail": (
                "Historical local evidence is display-only. Selected-chain "
                "child cancellation and exchange revalidation are "
                "source-disabled in the installed operator runtime."
            ),
        }
    )
    return _read_response(payload)


@router.post(
    "/orders/{root_client_order_id}/fill-follow-up/child-cancel",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    responses=SOURCE_DISABLED_COMMAND_ROUTE_RESPONSES,
    summary="Return fixed source-disabled selected-child cancel evidence",
)
def cancel_order_fill_follow_up_child_by_root_client_order_id(
    body: AdminOrderFillFollowUpChildCancelRequest,
    root_client_order_id: Annotated[str, Path(min_length=1)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
) -> JSONResponse:
    """Reject selected-child cancellation before any executable dependency."""

    require_permission(actor, AdminApiPermission.ORDER_CANCEL)
    del body, operator_intent
    return _command_response(
        AdminApiCommandResponse(
            status=AdminApiCommandStatus.NOT_IMPLEMENTED,
            action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            required_permission=AdminApiPermission.ORDER_CANCEL,
            service_method=(
                "cancel_order_fill_follow_up_child_by_root_client_order_id"
            ),
            message=(
                "Selected-chain compatibility cancellation is source-disabled in the "
                "installed operator runtime; supported cancellation is limited to "
                "manual Spot root cancel and explicit exact materialized-child "
                "safe-closeout."
            ),
            client_order_id=root_client_order_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            live_exchange_submitted=False,
            live_coinbase_orders_ran=False,
            live_coinbase_read_ran=False,
            data={
                "source_disabled": True,
                "browser_authority": "display_only",
                "bff_authority": "source_disabled_not_forwarded",
                "local_state_mutated": False,
                "exchange_mutation_attempted": False,
            },
            failure_stage="source_disabled_not_implemented",
        )
    )


@router.get(
    "/orders/{client_order_id}/fill-follow-up/trigger-preview",
    response_model=AdminAdmissionPreviewResponse,
    responses=READ_ROUTE_RESPONSES,
    summary="Preview the exact fill follow-up trigger admission context",
)
def preview_order_fill_follow_up_trigger_admission(
    request: Request,
    client_order_id: Annotated[str, Path(min_length=1)],
    command_idempotency_key: Annotated[str, Query(min_length=1)],
    operator_intent: Annotated[str, Query(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    cap_guard_store: Annotated[FileAdminApiCapGuardStore, Depends(get_cap_guard_store)],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    live_execution_service: Annotated[
        AdminApiLiveExecutionService,
        Depends(get_live_execution_service),
    ],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
    fill_testing_approval_id: Annotated[str | None, Query(min_length=1)] = None,
    wallet_proof_ref: Annotated[str | None, Query(min_length=1)] = None,
    cap_guard_decision_id: Annotated[str | None, Query(min_length=1)] = None,
    reconciliation_plan_id: Annotated[str | None, Query(min_length=1)] = None,
    audit_correlation_id: Annotated[str | None, Query(min_length=1)] = None,
    confirm_duplicate_claim_protection: bool = False,
    operator_notes: Annotated[str | None, Query(min_length=1)] = None,
) -> JSONResponse:
    """Return fill follow-up trigger admission evidence without executing."""

    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    body = AdminOrderFillFollowUpTriggerRequest(
        fill_testing_approval_id=fill_testing_approval_id,
        wallet_proof_ref=wallet_proof_ref,
        cap_guard_decision_id=cap_guard_decision_id,
        reconciliation_plan_id=reconciliation_plan_id,
        audit_correlation_id=audit_correlation_id,
        confirm_duplicate_claim_protection=confirm_duplicate_claim_protection,
        operator_notes=operator_notes,
    )
    trigger_path = request.url.path.replace(
        "/fill-follow-up/trigger-preview",
        "/fill-follow-up/trigger",
    )
    payload_hash = _idempotency_payload_hash(
        endpoint=f"POST {trigger_path}",
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json", exclude_none=True),
        path_params={"client_order_id": client_order_id},
    )
    decision = evaluate_command_live_admission(
        route="/api/v1/orders/{client_order_id}/fill-follow-up/trigger",
        method="POST",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value=client_order_id,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        required_permission=AdminApiPermission.ORDER_CREATE,
        service_method="trigger_order_fill_follow_up",
        actor_id=actor.actor_id,
        idempotency_key=command_idempotency_key,
        operator_intent=operator_intent,
        payload_hash=payload_hash,
        approval_store=approval_store,
        audit_store=audit_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
    )
    payload = AdminAdmissionPreviewResponse(
        message="Fill follow-up trigger admission preview loaded.",
        admission_decision=decision,
        data=service.preview_order_fill_follow_up_trigger(
            AdminOrderFillFollowUpTriggerCommand(
                envelope=AdminApiCommandEnvelope(
                    idempotency_key=command_idempotency_key,
                    correlation_id=command_idempotency_key,
                    operator_intent=operator_intent,
                    actor=actor,
                ),
                client_order_id=client_order_id,
                request=body,
                admission_decision=decision,
                **_fill_follow_up_cap_guard_wallet_context(
                    admission_decision=decision,
                    cap_guard_store=cap_guard_store,
                ),
            )
        ),
    )
    return JSONResponse(content=payload.model_dump(mode="json"))


@router.post(
    "/orders/{client_order_id}/fill-follow-up/trigger",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Attempt a guarded fill follow-up trigger through the shared command service",
)
def trigger_order_fill_follow_up(
    request: Request,
    body: AdminOrderFillFollowUpTriggerRequest,
    client_order_id: Annotated[str, Path(min_length=1)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
    cap_guard_store: Annotated[FileAdminApiCapGuardStore, Depends(get_cap_guard_store)],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    live_execution_service: Annotated[
        AdminApiLiveExecutionService,
        Depends(get_live_execution_service),
    ],
) -> JSONResponse:
    """Route adapter for fail-closed fill-triggered follow-up attempts."""

    endpoint = f"{request.method} {request.url.path}"
    envelope = _build_envelope(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
    )
    payload_hash = _idempotency_payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json", exclude_none=True),
        path_params={"client_order_id": client_order_id},
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.ORDER_CREATE,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method="trigger_order_fill_follow_up",
        route_template="/api/v1/orders/{client_order_id}/fill-follow-up/trigger",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value=client_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        client_order_id=client_order_id,
        command_runner_with_admission=lambda admission_decision: (
            service.trigger_order_fill_follow_up(
                AdminOrderFillFollowUpTriggerCommand(
                    envelope=envelope,
                    client_order_id=client_order_id,
                    request=body,
                    admission_decision=admission_decision,
                    **_fill_follow_up_cap_guard_wallet_context(
                        admission_decision=admission_decision,
                        cap_guard_store=cap_guard_store,
                    ),
                )
            )
        ),
    )


@router.post(
    "/orders",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Create a manual order through the shared command service",
)
def create_manual_order(
    request: Request,
    body: ManualOrderRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
    cap_guard_store: Annotated[FileAdminApiCapGuardStore, Depends(get_cap_guard_store)],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    live_execution_service: Annotated[
        AdminApiLiveExecutionService,
        Depends(get_live_execution_service),
    ],
) -> JSONResponse:
    """Route adapter for manual placement.

    The route is authenticated, idempotent, and audited. It can reach the
    installed controlled-live service only after the exact backend authority,
    runtime, approval, cap/wallet, reconciliation, and product gates pass.
    """

    endpoint = f"{request.method} {request.url.path}"
    execution_scope = _manual_order_backend_execution_scope()
    envelope = _build_envelope(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
    )
    payload_hash = _idempotency_payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
        backend_execution_scope=execution_scope,
    )
    body = _manual_order_with_backend_identity(
        body=body,
        actor=actor,
        endpoint=endpoint,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
    )

    def run_manual_order_with_admission(
        admission_decision: AdminLiveAdmissionDecisionEvidence,
    ) -> AdminApiCommandResponse:
        (
            cap_guard_decision_id,
            admin_max_notional,
            admin_max_executed_notional,
        ) = (
            _manual_order_admin_cap_guard_limits(
                admission_decision=admission_decision,
                cap_guard_store=cap_guard_store,
            )
        )
        with canonical_coinbase_execution_scope(
            COINBASE_EXECUTION_SCOPE_SPOT_PLACE
        ):
            return service.place_manual_order(
                ManualOrderCommand(
                    envelope=envelope,
                    request=body,
                    admin_approval_snapshot_id=(
                        admission_decision.approval_snapshot_id
                    ),
                    admin_cap_guard_decision_id=cap_guard_decision_id,
                    admin_max_submitted_notional_usdc=admin_max_notional,
                    admin_max_executed_notional_usdc=(
                        admin_max_executed_notional
                    ),
                    admission_audit_id=admission_decision.admission_audit_id,
                    allow_live_execution=admission_decision.allowed,
                )
            )

    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.ORDER_CREATE,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        service_method="place_manual_order",
        route_template="/api/v1/orders",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value=body.client_order_id,
        execution_scope=execution_scope,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        cap_guard_product_scope=body.product_id,
        client_order_id=body.client_order_id,
        command_runner_with_admission=run_manual_order_with_admission,
    )


@router.post(
    "/orders/{client_order_id}/cancel",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Cancel an order by client_order_id through the shared command service",
)
def cancel_order_by_client_order_id(
    request: Request,
    body: CancelOrderRequest,
    client_order_id: Annotated[str, Path(min_length=1)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
    cap_guard_store: Annotated[FileAdminApiCapGuardStore, Depends(get_cap_guard_store)],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    live_execution_service: Annotated[
        AdminApiLiveExecutionService,
        Depends(get_live_execution_service),
    ],
) -> JSONResponse:
    """Route adapter for cancel-by-client-order-id."""

    endpoint = f"{request.method} {request.url.path}"
    execution_scope = _manual_order_backend_execution_scope()
    envelope = _build_envelope(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
    )
    payload_hash = _idempotency_payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
        path_params={"client_order_id": client_order_id},
        backend_execution_scope=execution_scope,
    )

    def run_cancel_with_admission(
        admission_decision: AdminLiveAdmissionDecisionEvidence,
    ) -> AdminApiCommandResponse:
        with canonical_coinbase_execution_scope(
            COINBASE_EXECUTION_SCOPE_SPOT_CANCEL
        ):
            return service.cancel_order_by_client_order_id(
                CancelOrderCommand(
                    envelope=envelope,
                    client_order_id=client_order_id,
                    request=body,
                    allow_live_execution=admission_decision.allowed,
                )
            )

    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.ORDER_CANCEL,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        service_method="cancel_order_by_client_order_id",
        route_template="/api/v1/orders/{client_order_id}/cancel",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value=client_order_id,
        execution_scope=execution_scope,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        client_order_id=client_order_id,
        command_runner_with_admission=run_cancel_with_admission,
    )


@router.post(
    "/spot/campaign/executions",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Execute a spot campaign through the shared command service",
)
def execute_spot_campaign(
    request: Request,
    body: CampaignExecutionRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
    cap_guard_store: Annotated[FileAdminApiCapGuardStore, Depends(get_cap_guard_store)],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    live_execution_service: Annotated[
        AdminApiLiveExecutionService,
        Depends(get_live_execution_service),
    ],
) -> JSONResponse:
    """Route adapter for future campaign execution.

    The route has the command envelope, idempotency, audit, RBAC, and fail-closed
    live gate, but it does not submit Coinbase orders.
    """

    endpoint = f"{request.method} {request.url.path}"
    envelope = _build_envelope(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
    )
    payload_hash = _idempotency_payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.CAMPAIGN_EXECUTE,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        service_method="execute_spot_campaign",
        route_template="/api/v1/spot/campaign/executions",
        module_id="spot_operations",
        identity_key="campaign_id",
        identity_value=body.campaign_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        command_runner=lambda: service.execute_spot_campaign(
            CampaignExecutionCommand(envelope=envelope, request=body)
        ),
    )


@router.post(
    "/spot/sweep/automation-runs",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Run a spot sweep automation through the shared command service",
)
def run_spot_sweep_automation(
    request: Request,
    body: SpotSweepAutomationRunRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
    cap_guard_store: Annotated[FileAdminApiCapGuardStore, Depends(get_cap_guard_store)],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    live_execution_service: Annotated[
        AdminApiLiveExecutionService,
        Depends(get_live_execution_service),
    ],
) -> JSONResponse:
    """Route adapter for future spot sweep automation execution.

    The route has the command envelope, idempotency, audit, RBAC, and fail-closed
    live gate, but it does not run sweep tools or submit Coinbase orders.
    """

    endpoint = f"{request.method} {request.url.path}"
    envelope = _build_envelope(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
    )
    payload_hash = _idempotency_payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.SPOT_SWEEP_EXECUTE,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        service_method="run_spot_sweep_automation",
        route_template="/api/v1/spot/sweep/automation-runs",
        module_id="spot_operations",
        identity_key="sweep_config_id",
        identity_value=body.sweep_config_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        command_runner=lambda: service.run_spot_sweep_automation(
            SpotSweepAutomationRunCommand(envelope=envelope, request=body)
        ),
    )


def _execute_spot_recovery_contract(
    *,
    request: Request,
    body: (
        SpotRecoveryApplyExecutionRequest
        | SpotRecoveryRollbackExecutionRequest
        | SpotRecoveryExchangeStateProofRequest
        | SpotRecoveryExchangeStateSnapshotRequest
        | SpotRecoveryReconciliationExecutionRequest
        | SpotRecoveryReconciliationProofRecordRequest
    ),
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
    actor: AdminApiActor,
    permission: AdminApiPermission,
    service_method: str,
    route_template: str,
    service: AdminApiCommandService,
    idempotency_store: FileIdempotencyStore,
    audit_store: FileAdminApiAuditStore,
    approval_store: FileAdminApiApprovalStore,
    cap_guard_store: FileAdminApiCapGuardStore,
    reconciliation_store: FileAdminApiReconciliationStore,
    live_execution_service: AdminApiLiveExecutionService,
    command_runner: Callable[[AdminApiCommandEnvelope], AdminApiCommandResponse],
    command_runner_with_admission: Callable[
        [AdminApiCommandEnvelope, AdminLiveAdmissionDecisionEvidence],
        AdminApiCommandResponse,
    ] | None = None,
) -> JSONResponse:
    endpoint = f"{request.method} {request.url.path}"
    envelope = _build_envelope(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
    )
    payload_hash = _idempotency_payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
    )
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=permission,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method=service_method,
        route_template=route_template,
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value=body.client_order_id,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        command_runner=(
            None
            if command_runner_with_admission is not None
            else lambda: command_runner(envelope)
        ),
        command_runner_with_admission=(
            (
                lambda admission_decision: command_runner_with_admission(
                    envelope,
                    admission_decision,
                )
            )
            if command_runner_with_admission is not None
            else None
        ),
        client_order_id=body.client_order_id,
    )


@router.post(
    "/spot/recovery/apply-executions",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=SPOT_RECOVERY_EXECUTION_ROUTE_RESPONSES,
    summary="Apply a spot recovery plan through the shared command service",
)
def execute_spot_recovery_apply(
    request: Request,
    body: SpotRecoveryApplyExecutionRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
    cap_guard_store: Annotated[FileAdminApiCapGuardStore, Depends(get_cap_guard_store)],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    live_execution_service: Annotated[
        AdminApiLiveExecutionService,
        Depends(get_live_execution_service),
    ],
) -> JSONResponse:
    """Route adapter for future spot recovery apply execution."""

    return _execute_spot_recovery_contract(
        request=request,
        body=body,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
        permission=AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        service_method="execute_spot_recovery_apply",
        route_template="/api/v1/spot/recovery/apply-executions",
        service=service,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        command_runner=lambda envelope: service.execute_spot_recovery_apply(
            SpotRecoveryApplyExecutionCommand(envelope=envelope, request=body)
        ),
        command_runner_with_admission=lambda envelope, admission_decision: (
            service.execute_spot_recovery_apply(
                SpotRecoveryApplyExecutionCommand(
                    envelope=envelope,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.post(
    "/spot/recovery/rollback-executions",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=SPOT_RECOVERY_EXECUTION_ROUTE_RESPONSES,
    summary="Rollback a spot recovery apply through the shared command service",
)
def execute_spot_recovery_rollback(
    request: Request,
    body: SpotRecoveryRollbackExecutionRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
    cap_guard_store: Annotated[FileAdminApiCapGuardStore, Depends(get_cap_guard_store)],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    live_execution_service: Annotated[
        AdminApiLiveExecutionService,
        Depends(get_live_execution_service),
    ],
) -> JSONResponse:
    """Route adapter for future spot recovery rollback execution."""

    return _execute_spot_recovery_contract(
        request=request,
        body=body,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
        permission=AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        service_method="execute_spot_recovery_rollback",
        route_template="/api/v1/spot/recovery/rollback-executions",
        service=service,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        command_runner=lambda envelope: service.execute_spot_recovery_rollback(
            SpotRecoveryRollbackExecutionCommand(envelope=envelope, request=body)
        ),
        command_runner_with_admission=lambda envelope, admission_decision: (
            service.execute_spot_recovery_rollback(
                SpotRecoveryRollbackExecutionCommand(
                    envelope=envelope,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.post(
    "/spot/recovery/reconciliation-executions",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=SPOT_RECOVERY_EXECUTION_ROUTE_RESPONSES,
    summary=(
        "Attempt spot recovery reconciliation execution through the shared "
        "command service"
    ),
)
def execute_spot_recovery_reconciliation(
    request: Request,
    body: SpotRecoveryReconciliationExecutionRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
    cap_guard_store: Annotated[FileAdminApiCapGuardStore, Depends(get_cap_guard_store)],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    live_execution_service: Annotated[
        AdminApiLiveExecutionService,
        Depends(get_live_execution_service),
    ],
) -> JSONResponse:
    """Route-bound reconciliation execution boundary; executor remains disabled."""

    return _execute_spot_recovery_contract(
        request=request,
        body=body,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
        permission=AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        service_method="execute_spot_recovery_reconciliation",
        route_template="/api/v1/spot/recovery/reconciliation-executions",
        service=service,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        command_runner=lambda envelope: service.execute_spot_recovery_reconciliation(
            SpotRecoveryReconciliationExecutionCommand(
                envelope=envelope,
                request=body,
            )
        ),
        command_runner_with_admission=lambda envelope, admission_decision: (
            service.execute_spot_recovery_reconciliation(
                SpotRecoveryReconciliationExecutionCommand(
                    envelope=envelope,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.post(
    "/spot/recovery/exchange-state-proofs",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=SPOT_RECOVERY_PROOF_ROUTE_RESPONSES,
    summary="Record spot recovery exchange-state proof through the shared command service",
)
def record_spot_recovery_exchange_state_proof(
    request: Request,
    body: SpotRecoveryExchangeStateProofRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
    cap_guard_store: Annotated[FileAdminApiCapGuardStore, Depends(get_cap_guard_store)],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    live_execution_service: Annotated[
        AdminApiLiveExecutionService,
        Depends(get_live_execution_service),
    ],
) -> JSONResponse:
    """Route adapter for future spot recovery exchange-state proof writing."""

    return _execute_spot_recovery_contract(
        request=request,
        body=body,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
        permission=AdminApiPermission.SPOT_RECOVERY_RECORD,
        service_method="record_spot_recovery_exchange_state_proof",
        route_template="/api/v1/spot/recovery/exchange-state-proofs",
        service=service,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        command_runner=lambda envelope: service.record_spot_recovery_exchange_state_proof(
            SpotRecoveryExchangeStateProofCommand(
                envelope=envelope,
                request=body,
            )
        ),
        command_runner_with_admission=lambda envelope, admission_decision: (
            service.record_spot_recovery_exchange_state_proof(
                SpotRecoveryExchangeStateProofCommand(
                    envelope=envelope,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.post(
    "/spot/recovery/exchange-state-snapshots",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=SPOT_RECOVERY_PROOF_ROUTE_RESPONSES,
    summary="Record spot recovery exchange-state snapshot through the shared command service",
)
def record_spot_recovery_exchange_state_snapshot(
    request: Request,
    body: SpotRecoveryExchangeStateSnapshotRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
    cap_guard_store: Annotated[FileAdminApiCapGuardStore, Depends(get_cap_guard_store)],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    live_execution_service: Annotated[
        AdminApiLiveExecutionService,
        Depends(get_live_execution_service),
    ],
) -> JSONResponse:
    """Route adapter for backend-owned no-live exchange-state snapshots."""

    return _execute_spot_recovery_contract(
        request=request,
        body=body,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
        permission=AdminApiPermission.SPOT_RECOVERY_RECORD,
        service_method="record_spot_recovery_exchange_state_snapshot",
        route_template="/api/v1/spot/recovery/exchange-state-snapshots",
        service=service,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        command_runner=lambda envelope: (
            service.record_spot_recovery_exchange_state_snapshot(
                SpotRecoveryExchangeStateSnapshotCommand(
                    envelope=envelope,
                    request=body,
                )
            )
        ),
        command_runner_with_admission=lambda envelope, admission_decision: (
            service.record_spot_recovery_exchange_state_snapshot(
                SpotRecoveryExchangeStateSnapshotCommand(
                    envelope=envelope,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.post(
    "/spot/recovery/reconciliation-proofs",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=SPOT_RECOVERY_PROOF_ROUTE_RESPONSES,
    summary="Record spot recovery reconciliation proof through the shared command service",
)
def record_spot_recovery_reconciliation_proof(
    request: Request,
    body: SpotRecoveryReconciliationProofRecordRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiCommandService, Depends(get_command_service)],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
    approval_store: Annotated[FileAdminApiApprovalStore, Depends(get_approval_store)],
    cap_guard_store: Annotated[FileAdminApiCapGuardStore, Depends(get_cap_guard_store)],
    reconciliation_store: Annotated[
        FileAdminApiReconciliationStore,
        Depends(get_reconciliation_store),
    ],
    live_execution_service: Annotated[
        AdminApiLiveExecutionService,
        Depends(get_live_execution_service),
    ],
) -> JSONResponse:
    """Route adapter for future spot recovery reconciliation-proof writing."""

    return _execute_spot_recovery_contract(
        request=request,
        body=body,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
        permission=AdminApiPermission.SPOT_RECOVERY_RECORD,
        service_method="record_spot_recovery_reconciliation_proof",
        route_template="/api/v1/spot/recovery/reconciliation-proofs",
        service=service,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        command_runner=lambda envelope: (
            service.record_spot_recovery_reconciliation_proof(
                SpotRecoveryReconciliationProofRecordCommand(
                    envelope=envelope,
                    request=body,
                )
            )
        ),
        command_runner_with_admission=lambda envelope, admission_decision: (
            service.record_spot_recovery_reconciliation_proof(
                SpotRecoveryReconciliationProofRecordCommand(
                    envelope=envelope,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )
