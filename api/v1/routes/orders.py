"""Order command route adapters for the Admin API."""

from __future__ import annotations

import uuid
from typing import Annotated, Callable

from fastapi import APIRouter, Depends, Header, Path, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from application.admin_api.audit import AdminApiAuditEvent, FileAdminApiAuditStore
from application.admin_api.approval import (
    FileAdminApiApprovalStore,
    evaluate_command_live_admission,
)
from application.admin_api.auth import get_authenticated_actor, require_permission
from application.admin_api.cap_guard import FileAdminApiCapGuardStore
from application.admin_api.command_service import AdminApiCommandService
from application.admin_api.idempotency import (
    FileIdempotencyStore,
    IdempotencyRecord,
    make_payload_hash,
)
from application.admin_api.live_execution import (
    AdminApiLiveExecutionService,
    get_disabled_live_execution_service,
)
from application.admin_api.reconciliation import FileAdminApiReconciliationStore
from application.admin_api.models import (
    AdminApiActor,
    AdminApiCommandEnvelope,
    AdminApiCommandResponse,
    AdminApiErrorResponse,
    AdminLiveAdmissionDecisionEvidence,
    AdminOrderDetailResponse,
    AdminOrderListResponse,
    CampaignExecutionCommand,
    CampaignExecutionRequest,
    CancelOrderCommand,
    CancelOrderRequest,
    ManualOrderCommand,
    ManualOrderRequest,
    SpotRecoveryApplyExecutionCommand,
    SpotRecoveryApplyExecutionRequest,
    SpotRecoveryExchangeStateProofCommand,
    SpotRecoveryExchangeStateProofRequest,
    SpotRecoveryReconciliationExecutionCommand,
    SpotRecoveryReconciliationExecutionRequest,
    SpotRecoveryReconciliationProofRecordCommand,
    SpotRecoveryReconciliationProofRecordRequest,
    SpotRecoveryRollbackExecutionCommand,
    SpotRecoveryRollbackExecutionRequest,
    SpotSweepAutomationRunCommand,
    SpotSweepAutomationRunRequest,
)
from application.admin_api.read_service import AdminApiReadService
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiIdempotencyDecision,
    AdminApiPermission,
)


router = APIRouter()

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


def get_command_service() -> AdminApiCommandService:
    """Return the shared command service boundary."""

    return AdminApiCommandService()


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
    """Return the backend-owned disabled live execution service boundary."""

    return get_disabled_live_execution_service()


def get_read_service() -> AdminApiReadService:
    """Return the read-only Admin API status service."""

    return AdminApiReadService()


def _read_response(payload: object) -> JSONResponse:
    return JSONResponse(content=jsonable_encoder(payload))


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
        "status": response.status,
        "failure_stage": response.failure_stage,
        "message": response.message,
        "admission_decision": response.admission_decision,
    }
    if response.audit_id is not None:
        event_fields["audit_id"] = response.audit_id
    return audit_store.append(AdminApiAuditEvent(**event_fields))


def _idempotency_payload_hash(
    *,
    endpoint: str,
    actor: AdminApiActor,
    operator_intent: str,
    body: dict,
    path_params: dict | None = None,
) -> str:
    return make_payload_hash({
        "endpoint": endpoint,
        "actor_id": actor.actor_id,
        "roles": [role.value for role in actor.roles],
        "operator_intent": operator_intent,
        "body": body,
        "path_params": path_params or {},
    })


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
    command_runner: Callable[[], AdminApiCommandResponse] | None = None,
    command_runner_with_admission: Callable[
        [AdminLiveAdmissionDecisionEvidence],
        AdminApiCommandResponse,
    ] | None = None,
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
    )
    check = idempotency_store.evaluate(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
    )
    if check.decision == AdminApiIdempotencyDecision.REPLAY and check.record:
        payload = dict(check.record.response)
        response = AdminApiCommandResponse.model_validate(payload)
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

    The route is authenticated, idempotent, audited, and still live-disabled
    until enterprise approval/cap gates are completed.
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
    body = _manual_order_with_backend_identity(
        body=body,
        actor=actor,
        endpoint=endpoint,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
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
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        client_order_id=body.client_order_id,
        command_runner=lambda: service.place_manual_order(
            ManualOrderCommand(envelope=envelope, request=body)
        ),
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
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        client_order_id=client_order_id,
        command_runner=lambda: service.cancel_order_by_client_order_id(
            CancelOrderCommand(
                envelope=envelope,
                client_order_id=client_order_id,
                request=body,
            )
        ),
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
