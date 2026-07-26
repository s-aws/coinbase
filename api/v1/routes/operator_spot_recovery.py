"""Authenticated operator Spot recovery case routes."""

from __future__ import annotations

import re
from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, status
from fastapi.responses import JSONResponse

from application.admin_api.audit import AdminApiAuditEvent, FileAdminApiAuditStore
from application.admin_api.auth import get_authenticated_actor, require_permission
from application.admin_api.command_service import AdminApiCommandService
from application.admin_api.idempotency import (
    FileIdempotencyStore,
    IdempotencyRecord,
    make_payload_hash,
)
from application.admin_api.models import AdminApiActor, AdminApiErrorResponse
from application.admin_api.operator_spot_recovery import (
    OperatorSpotRecoveryError,
    OperatorSpotRecoveryCaseCreateRequest,
    OperatorSpotRecoveryCaseListResponse,
    OperatorSpotRecoveryCaseResponse,
    OperatorSpotRecoveryLocalActionRequest,
    OperatorSpotRecoveryRefreshRequest,
    OperatorSpotRecoveryService,
    build_operator_spot_recovery_case_item,
)
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiIdempotencyDecision,
    AdminApiPermission,
)
from database.operator_spot_recovery import (
    OperatorSpotRecoveryRepository,
    get_default_operator_spot_recovery_repository,
)

from .orders import get_command_service


router = APIRouter()
_FIXED_CODE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")

READ_RESPONSES = {
    401: {
        "model": AdminApiErrorResponse,
        "description": "Missing or invalid Admin API authentication.",
    },
    403: {
        "model": AdminApiErrorResponse,
        "description": "Actor lacks recovery read authority.",
    },
    404: {
        "model": AdminApiErrorResponse,
        "description": "Recovery case was not found.",
    },
}
MUTATION_RESPONSES = {
    200: {
        "model": OperatorSpotRecoveryCaseResponse,
        "description": "Recovery action accepted or idempotently replayed.",
    },
    400: {
        "model": OperatorSpotRecoveryCaseResponse,
        "description": "Recovery action rejected before an authorized side effect.",
    },
    401: READ_RESPONSES[401],
    403: READ_RESPONSES[403],
    409: {
        "model": OperatorSpotRecoveryCaseResponse,
        "description": "Recovery revision or idempotency conflict.",
    },
}


def get_operator_spot_recovery_repository() -> OperatorSpotRecoveryRepository:
    return get_default_operator_spot_recovery_repository()


def get_operator_spot_recovery_service(
    command_service: Annotated[
        AdminApiCommandService,
        Depends(get_command_service),
    ],
    repository: Annotated[
        OperatorSpotRecoveryRepository,
        Depends(get_operator_spot_recovery_repository),
    ],
) -> OperatorSpotRecoveryService:
    dependencies = command_service.dependencies
    return OperatorSpotRecoveryService(
        repository=repository,
        rest_client=dependencies.rest_client,
        rest_client_available=dependencies.rest_client_available,
        configured_portfolio_id=dependencies.spot_portfolio_id,
    )


def get_idempotency_store() -> FileIdempotencyStore:
    return FileIdempotencyStore()


def get_audit_store() -> FileAdminApiAuditStore:
    return FileAdminApiAuditStore()


def _case_item(
    service: OperatorSpotRecoveryService,
    record: dict[str, Any],
) -> Any:
    events = service.repository.list_events(record["case_id"], limit=100)
    return build_operator_spot_recovery_case_item(
        record,
        events=events,
        portfolio_binding_verified=service.portfolio_binding_verified(record),
    )


def _status_code(response: OperatorSpotRecoveryCaseResponse) -> int:
    if response.status is AdminApiCommandStatus.CONFLICT:
        return status.HTTP_409_CONFLICT
    if response.status is AdminApiCommandStatus.REJECTED:
        return status.HTTP_400_BAD_REQUEST
    return status.HTTP_200_OK


def _json_response(
    response: OperatorSpotRecoveryCaseResponse,
    *,
    replayed: bool = False,
) -> JSONResponse:
    headers = {"X-Correlation-Id": response.correlation_id or ""}
    if replayed:
        headers["X-Idempotency-Replayed"] = "true"
    return JSONResponse(
        status_code=_status_code(response),
        content=response.model_dump(mode="json"),
        headers=headers,
    )


def _fixed_error(exc: OperatorSpotRecoveryError) -> str:
    return (
        exc.code
        if _FIXED_CODE.fullmatch(exc.code)
        else "recovery_internal_failure"
    )


def _record_audit(
    *,
    store: FileAdminApiAuditStore,
    actor: AdminApiActor,
    endpoint: str,
    correlation_id: str,
    operator_intent: str,
    idempotency_key: str,
    permission: AdminApiPermission,
    action_class: AdminApiActionClass,
    response: OperatorSpotRecoveryCaseResponse,
) -> str:
    return store.append(
        AdminApiAuditEvent(
            actor_id=actor.actor_id,
            action_class=action_class,
            permission=permission,
            endpoint=endpoint,
            request_id=correlation_id,
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            client_order_id=(
                response.case.client_order_id if response.case is not None else None
            ),
            live_exchange_submitted=False,
            live_coinbase_orders_ran=False,
            live_coinbase_read_ran=response.live_coinbase_read_ran,
            status=response.status,
            failure_stage=(
                "operator_spot_recovery"
                if response.status
                in {AdminApiCommandStatus.REJECTED, AdminApiCommandStatus.CONFLICT}
                else None
            ),
            message=response.message,
        )
    )


def _execute(
    *,
    request: Request,
    body: dict[str, Any],
    actor: AdminApiActor,
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
    service: OperatorSpotRecoveryService,
    idempotency_store: FileIdempotencyStore,
    audit_store: FileAdminApiAuditStore,
    permission: AdminApiPermission,
    action_class: AdminApiActionClass,
    service_method: str,
    live_coinbase_read_ran: bool,
    operation: Callable[[], dict[str, Any]],
) -> JSONResponse:
    require_permission(actor, permission)
    endpoint = f"{request.method} {request.url.path}"
    if operator_intent != service_method:
        response = OperatorSpotRecoveryCaseResponse(
            status=AdminApiCommandStatus.REJECTED,
            required_permission=permission,
            service_method=service_method,
            message="recovery_operator_intent_invalid",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        response.audit_id = _record_audit(
            store=audit_store,
            actor=actor,
            endpoint=endpoint,
            correlation_id=correlation_id,
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            permission=permission,
            action_class=action_class,
            response=response,
        )
        return _json_response(response)
    payload_hash = make_payload_hash(
        {
            "endpoint": endpoint,
            "actor_id": actor.actor_id,
            "roles": [role.value for role in actor.roles],
            "operator_intent": operator_intent,
            "body": body,
        }
    )
    with idempotency_store.command_execution(idempotency_key=idempotency_key):
        check = idempotency_store.evaluate(
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
        )
        if check.decision is AdminApiIdempotencyDecision.REPLAY and check.record:
            response = OperatorSpotRecoveryCaseResponse.model_validate(
                check.record.response
            ).model_copy(update={"replayed": True})
            return _json_response(response, replayed=True)
        if check.decision is AdminApiIdempotencyDecision.CONFLICT:
            response = OperatorSpotRecoveryCaseResponse(
                status=AdminApiCommandStatus.CONFLICT,
                required_permission=permission,
                service_method=service_method,
                message="recovery_idempotency_conflict",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
            )
            response.audit_id = _record_audit(
                store=audit_store,
                actor=actor,
                endpoint=endpoint,
                correlation_id=correlation_id,
                operator_intent=operator_intent,
                idempotency_key=idempotency_key,
                permission=permission,
                action_class=action_class,
                response=response,
            )
            return _json_response(response)

        try:
            record = operation()
            response = OperatorSpotRecoveryCaseResponse(
                status=AdminApiCommandStatus.ACCEPTED,
                required_permission=permission,
                service_method=service_method,
                message=f"{service_method}_accepted",
                case=_case_item(service, record),
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                live_coinbase_read_ran=live_coinbase_read_ran,
            )
        except OperatorSpotRecoveryError as exc:
            code = _fixed_error(exc)
            command_status = (
                AdminApiCommandStatus.CONFLICT
                if code.endswith("_conflict")
                else AdminApiCommandStatus.REJECTED
            )
            response = OperatorSpotRecoveryCaseResponse(
                status=command_status,
                required_permission=permission,
                service_method=service_method,
                message=code,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
            )
        except Exception:
            response = OperatorSpotRecoveryCaseResponse(
                status=AdminApiCommandStatus.REJECTED,
                required_permission=permission,
                service_method=service_method,
                message="recovery_internal_failure",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
            )
        response.audit_id = _record_audit(
            store=audit_store,
            actor=actor,
            endpoint=endpoint,
            correlation_id=correlation_id,
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            permission=permission,
            action_class=action_class,
            response=response,
        )
        if response.status is AdminApiCommandStatus.ACCEPTED:
            idempotency_store.put_record(
                IdempotencyRecord(
                    idempotency_key=idempotency_key,
                    payload_hash=payload_hash,
                    client_order_id=(
                        response.case.client_order_id
                        if response.case is not None
                        else None
                    ),
                    status=response.status,
                    response=response.model_dump(mode="json"),
                    actor_id=actor.actor_id,
                    endpoint=endpoint,
                )
            )
        return _json_response(response)


@router.get(
    "/spot/recovery/cases",
    response_model=OperatorSpotRecoveryCaseListResponse,
    responses=READ_RESPONSES,
    summary="List durable operator Spot recovery cases",
)
def list_operator_spot_recovery_cases(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorSpotRecoveryService,
        Depends(get_operator_spot_recovery_service),
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUDIT_READ)
    records, total_count = service.list_cases(limit=limit, offset=offset)
    items = [_case_item(service, record) for record in records]
    next_offset = offset + len(items) if offset + len(items) < total_count else None
    payload = OperatorSpotRecoveryCaseListResponse(
        items=items,
        total_count=total_count,
        returned_count=len(items),
        limit=limit,
        offset=offset,
        next_offset=next_offset,
    )
    return JSONResponse(content=payload.model_dump(mode="json"))


@router.get(
    "/spot/recovery/cases/{case_id}",
    response_model=OperatorSpotRecoveryCaseResponse,
    responses=READ_RESPONSES,
    summary="Read one durable operator Spot recovery case",
)
def get_operator_spot_recovery_case(
    case_id: Annotated[str, Path(min_length=36, max_length=36)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorSpotRecoveryService,
        Depends(get_operator_spot_recovery_service),
    ],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUDIT_READ)
    try:
        record = service.get_case(case_id)
    except OperatorSpotRecoveryError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_fixed_error(exc),
        ) from None
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="recovery_internal_failure",
        ) from None
    payload = OperatorSpotRecoveryCaseResponse(
        status=AdminApiCommandStatus.ACCEPTED,
        required_permission=AdminApiPermission.AUDIT_READ,
        service_method="get_operator_spot_recovery_case",
        message="operator_spot_recovery_case_loaded",
        case=_case_item(service, record),
    )
    return JSONResponse(content=payload.model_dump(mode="json"))


@router.post(
    "/spot/recovery/cases",
    response_model=OperatorSpotRecoveryCaseResponse,
    responses=MUTATION_RESPONSES,
    summary="Create one operator-selected Spot recovery case",
)
def create_operator_spot_recovery_case(
    request: Request,
    body: OperatorSpotRecoveryCaseCreateRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorSpotRecoveryService,
        Depends(get_operator_spot_recovery_service),
    ],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
) -> JSONResponse:
    return _execute(
        request=request,
        body=body.model_dump(mode="json"),
        actor=actor,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        service=service,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        permission=AdminApiPermission.SPOT_RECOVERY_RECORD,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method="create_operator_spot_recovery_case",
        live_coinbase_read_ran=False,
        operation=lambda: service.create_case(
            client_order_id=body.client_order_id,
            actor_id=actor.actor_id,
            operator_reason=body.operator_reason,
            correlation_id=correlation_id,
        ),
    )


@router.post(
    "/spot/recovery/cases/{case_id}/refresh",
    response_model=OperatorSpotRecoveryCaseResponse,
    responses=MUTATION_RESPONSES,
    summary="Refresh one case from exact Coinbase order and fill truth",
)
def refresh_operator_spot_recovery_case(
    request: Request,
    body: OperatorSpotRecoveryRefreshRequest,
    case_id: Annotated[str, Path(min_length=36, max_length=36)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorSpotRecoveryService,
        Depends(get_operator_spot_recovery_service),
    ],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
) -> JSONResponse:
    return _execute(
        request=request,
        body={"case_id": case_id, **body.model_dump(mode="json")},
        actor=actor,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        service=service,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        permission=AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method="refresh_operator_spot_recovery_case",
        live_coinbase_read_ran=True,
        operation=lambda: service.refresh_case(
            case_id=case_id,
            expected_revision=body.expected_revision,
            actor_id=actor.actor_id,
            correlation_id=correlation_id,
            manual_live_acknowledgement=body.manual_live_acknowledgement,
        ),
    )


def _local_action(
    *,
    request: Request,
    body: OperatorSpotRecoveryLocalActionRequest,
    case_id: str,
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
    actor: AdminApiActor,
    service: OperatorSpotRecoveryService,
    idempotency_store: FileIdempotencyStore,
    audit_store: FileAdminApiAuditStore,
    service_method: str,
) -> JSONResponse:
    operation = (
        service.apply_case
        if service_method == "apply_operator_spot_recovery_case"
        else service.rollback_case
    )
    return _execute(
        request=request,
        body={"case_id": case_id, **body.model_dump(mode="json")},
        actor=actor,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        service=service,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        permission=AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method=service_method,
        live_coinbase_read_ran=False,
        operation=lambda: operation(
            case_id=case_id,
            expected_revision=body.expected_revision,
            actor_id=actor.actor_id,
            operator_reason=body.operator_reason,
            correlation_id=correlation_id,
            operator_acknowledgement=body.operator_acknowledgement,
        ),
    )


@router.post(
    "/spot/recovery/cases/{case_id}/apply",
    response_model=OperatorSpotRecoveryCaseResponse,
    responses=MUTATION_RESPONSES,
    summary="Apply one reviewed local recovery repair",
)
def apply_operator_spot_recovery_case(
    request: Request,
    body: OperatorSpotRecoveryLocalActionRequest,
    case_id: Annotated[str, Path(min_length=36, max_length=36)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorSpotRecoveryService,
        Depends(get_operator_spot_recovery_service),
    ],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
) -> JSONResponse:
    return _local_action(
        request=request,
        body=body,
        case_id=case_id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
        service=service,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        service_method="apply_operator_spot_recovery_case",
    )


@router.post(
    "/spot/recovery/cases/{case_id}/rollback",
    response_model=OperatorSpotRecoveryCaseResponse,
    responses=MUTATION_RESPONSES,
    summary="Safely roll back one reviewed local recovery repair",
)
def rollback_operator_spot_recovery_case(
    request: Request,
    body: OperatorSpotRecoveryLocalActionRequest,
    case_id: Annotated[str, Path(min_length=36, max_length=36)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorSpotRecoveryService,
        Depends(get_operator_spot_recovery_service),
    ],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
) -> JSONResponse:
    return _local_action(
        request=request,
        body=body,
        case_id=case_id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=actor,
        service=service,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        service_method="rollback_operator_spot_recovery_case",
    )
