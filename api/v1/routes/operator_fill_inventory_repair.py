"""Authenticated operator fill-ledger and inventory repair routes."""

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
from application.admin_api.operator_fill_inventory_repair import (
    OperatorFillInventoryRepairCaseCreateRequest,
    OperatorFillInventoryRepairCaseListResponse,
    OperatorFillInventoryRepairCaseResponse,
    OperatorFillInventoryRepairError,
    OperatorFillInventoryRepairLocalActionRequest,
    OperatorFillInventoryRepairRefreshRequest,
    OperatorFillInventoryRepairService,
    PUBLIC_FILL_INVENTORY_REPAIR_CODES,
    build_operator_fill_inventory_repair_case_item,
)
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiIdempotencyDecision,
    AdminApiPermission,
)
from database.operator_fill_inventory_repair import (
    OperatorFillInventoryRepairRepository,
    get_default_operator_fill_inventory_repair_repository,
)

from .orders import get_command_service


router = APIRouter()
_FIXED_CODE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
_EVIDENCE_ID = r"^[A-Za-z0-9._:-]{1,255}$"
READ_RESPONSES = {
    401: {
        "model": AdminApiErrorResponse,
        "description": "Missing or invalid Admin API authentication.",
    },
    403: {
        "model": AdminApiErrorResponse,
        "description": "Actor lacks fill repair read authority.",
    },
    404: {
        "model": AdminApiErrorResponse,
        "description": "Fill and inventory repair case was not found.",
    },
}
MUTATION_RESPONSES = {
    200: {
        "model": OperatorFillInventoryRepairCaseResponse,
        "description": "Repair action accepted or idempotently replayed.",
    },
    400: {
        "model": OperatorFillInventoryRepairCaseResponse,
        "description": "Repair action rejected before an authorized side effect.",
    },
    401: READ_RESPONSES[401],
    403: READ_RESPONSES[403],
    409: {
        "model": OperatorFillInventoryRepairCaseResponse,
        "description": "Repair revision or idempotency conflict.",
    },
}


def get_operator_fill_inventory_repair_repository(
) -> OperatorFillInventoryRepairRepository:
    return get_default_operator_fill_inventory_repair_repository()


def get_operator_fill_inventory_repair_service(
    command_service: Annotated[
        AdminApiCommandService,
        Depends(get_command_service),
    ],
    repository: Annotated[
        OperatorFillInventoryRepairRepository,
        Depends(get_operator_fill_inventory_repair_repository),
    ],
) -> OperatorFillInventoryRepairService:
    dependencies = command_service.dependencies
    return OperatorFillInventoryRepairService(
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
    service: OperatorFillInventoryRepairService,
    record: dict[str, Any],
) -> Any:
    events = service.repository.list_events(record["case_id"], limit=100)
    record_with_goal_budget = {
        **record,
        **service.repository.get_goal_budget(),
    }
    return build_operator_fill_inventory_repair_case_item(
        record_with_goal_budget,
        events=events,
        portfolio_binding_verified=service.portfolio_binding_verified(
            record_with_goal_budget
        ),
    )


def _fixed_error(exc: OperatorFillInventoryRepairError) -> str:
    return (
        exc.code
        if (
            _FIXED_CODE.fullmatch(exc.code)
            and exc.code in PUBLIC_FILL_INVENTORY_REPAIR_CODES
        )
        else "fill_inventory_internal_failure"
    )


def _status_code(response: OperatorFillInventoryRepairCaseResponse) -> int:
    if response.status is AdminApiCommandStatus.CONFLICT:
        return status.HTTP_409_CONFLICT
    if response.status is AdminApiCommandStatus.REJECTED:
        return status.HTTP_400_BAD_REQUEST
    return status.HTTP_200_OK


def _json_response(
    response: OperatorFillInventoryRepairCaseResponse,
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


def _record_audit(
    *,
    store: FileAdminApiAuditStore,
    actor: AdminApiActor,
    endpoint: str,
    correlation_id: str,
    operator_intent: str,
    idempotency_key: str,
    permission: AdminApiPermission,
    response: OperatorFillInventoryRepairCaseResponse,
) -> str:
    return store.append(
        AdminApiAuditEvent(
            actor_id=actor.actor_id,
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            permission=permission,
            endpoint=endpoint,
            request_id=correlation_id,
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            client_order_id=(
                response.case.client_order_id
                if response.case is not None
                else None
            ),
            live_exchange_submitted=False,
            live_coinbase_orders_ran=False,
            # The legacy audit field is boolean. Conservatively account an
            # unknown post-claim read as potentially run; the response and
            # case event retain the exact UNKNOWN state.
            live_coinbase_read_ran=(
                response.live_coinbase_read_ran is not False
            ),
            status=response.status,
            failure_stage=(
                "operator_fill_inventory_repair"
                if response.status
                in {
                    AdminApiCommandStatus.REJECTED,
                    AdminApiCommandStatus.CONFLICT,
                }
                else None
            ),
            message=response.message,
        )
    )


def _failed_refresh_read_evidence(
    *,
    service: OperatorFillInventoryRepairService,
    body: dict[str, Any],
) -> tuple[bool | None, str]:
    """Recover durable call truth after a refresh handler raises."""

    case_id = body.get("case_id")
    expected_revision = body.get("expected_revision")
    if not isinstance(case_id, str):
        return None, "UNKNOWN_AFTER_PAGE_CLAIM"
    try:
        record = service.get_case(case_id)
    except Exception:
        return None, "UNKNOWN_AFTER_PAGE_CLAIM"
    if (
        isinstance(expected_revision, int)
        and int(record.get("revision") or 0) == expected_revision
    ):
        return False, "NOT_RUN"
    read_state = str(
        record.get("last_refresh_coinbase_read_state")
        or "UNKNOWN_AFTER_PAGE_CLAIM"
    )
    if read_state == "RETURNED":
        return True, read_state
    if read_state == "NOT_RUN":
        return False, read_state
    return None, "UNKNOWN_AFTER_PAGE_CLAIM"


def _execute(
    *,
    request: Request,
    body: dict[str, Any],
    actor: AdminApiActor,
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
    service: OperatorFillInventoryRepairService,
    idempotency_store: FileIdempotencyStore,
    audit_store: FileAdminApiAuditStore,
    permission: AdminApiPermission,
    service_method: str,
    live_coinbase_read_ran: bool,
    operation: Callable[[], dict[str, Any]],
) -> JSONResponse:
    require_permission(actor, permission)
    endpoint = f"{request.method} {request.url.path}"
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
            response = OperatorFillInventoryRepairCaseResponse.model_validate(
                check.record.response
            ).model_copy(update={"replayed": True})
            return _json_response(response, replayed=True)
        if check.decision is AdminApiIdempotencyDecision.CONFLICT:
            response = OperatorFillInventoryRepairCaseResponse(
                status=AdminApiCommandStatus.CONFLICT,
                required_permission=permission,
                service_method=service_method,
                message="fill_inventory_idempotency_conflict",
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
                response=response,
            )
            return _json_response(response)
        try:
            record = operation()
            read_state = (
                str(
                    record.get("last_refresh_coinbase_read_state")
                    or "NOT_RUN"
                )
                if live_coinbase_read_ran
                else "NOT_RUN"
            )
            read_ran: bool | None
            if read_state == "RETURNED":
                read_ran = True
            elif read_state == "UNKNOWN_AFTER_PAGE_CLAIM":
                read_ran = None
            else:
                read_ran = False
            response = OperatorFillInventoryRepairCaseResponse(
                status=AdminApiCommandStatus.ACCEPTED,
                required_permission=permission,
                service_method=service_method,
                message=f"{service_method}_accepted",
                case=_case_item(service, record),
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                live_coinbase_read_ran=read_ran,
                coinbase_read_state=read_state,
                live_coinbase_order_mutation_ran=False,
            )
        except OperatorFillInventoryRepairError as exc:
            code = _fixed_error(exc)
            response = OperatorFillInventoryRepairCaseResponse(
                status=(
                    AdminApiCommandStatus.CONFLICT
                    if code.endswith("_conflict")
                    else AdminApiCommandStatus.REJECTED
                ),
                required_permission=permission,
                service_method=service_method,
                message=code,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
            )
            if live_coinbase_read_ran:
                (
                    response.live_coinbase_read_ran,
                    response.coinbase_read_state,
                ) = _failed_refresh_read_evidence(
                    service=service,
                    body=body,
                )
        except Exception:
            response = OperatorFillInventoryRepairCaseResponse(
                status=AdminApiCommandStatus.REJECTED,
                required_permission=permission,
                service_method=service_method,
                message="fill_inventory_internal_failure",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
            )
            if live_coinbase_read_ran:
                (
                    response.live_coinbase_read_ran,
                    response.coinbase_read_state,
                ) = _failed_refresh_read_evidence(
                    service=service,
                    body=body,
                )
        response.audit_id = _record_audit(
            store=audit_store,
            actor=actor,
            endpoint=endpoint,
            correlation_id=correlation_id,
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            permission=permission,
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
    "/spot/fill-inventory-repair/cases",
    response_model=OperatorFillInventoryRepairCaseListResponse,
    responses=READ_RESPONSES,
    summary="List durable fill-ledger and inventory repair cases",
)
def list_operator_fill_inventory_repair_cases(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFillInventoryRepairService,
        Depends(get_operator_fill_inventory_repair_service),
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUDIT_READ)
    records, total_count = service.list_cases(limit=limit, offset=offset)
    items = [_case_item(service, record) for record in records]
    next_offset = offset + len(items) if offset + len(items) < total_count else None
    payload = OperatorFillInventoryRepairCaseListResponse(
        items=items,
        total_count=total_count,
        returned_count=len(items),
        limit=limit,
        offset=offset,
        next_offset=next_offset,
    )
    return JSONResponse(content=payload.model_dump(mode="json"))


@router.get(
    "/spot/fill-inventory-repair/cases/{case_id}",
    response_model=OperatorFillInventoryRepairCaseResponse,
    responses=READ_RESPONSES,
    summary="Read one durable fill-ledger and inventory repair case",
)
def get_operator_fill_inventory_repair_case(
    case_id: Annotated[str, Path(min_length=36, max_length=36)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFillInventoryRepairService,
        Depends(get_operator_fill_inventory_repair_service),
    ],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.AUDIT_READ)
    try:
        record = service.get_case(case_id)
    except OperatorFillInventoryRepairError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_fixed_error(exc),
        ) from None
    payload = OperatorFillInventoryRepairCaseResponse(
        status=AdminApiCommandStatus.ACCEPTED,
        required_permission=AdminApiPermission.AUDIT_READ,
        service_method="get_operator_fill_inventory_repair_case",
        message="operator_fill_inventory_repair_case_loaded",
        case=_case_item(service, record),
    )
    return JSONResponse(content=payload.model_dump(mode="json"))


@router.post(
    "/spot/fill-inventory-repair/cases",
    response_model=OperatorFillInventoryRepairCaseResponse,
    responses=MUTATION_RESPONSES,
    summary="Create one bounded fill-ledger and inventory repair case",
)
def create_operator_fill_inventory_repair_case(
    request: Request,
    body: OperatorFillInventoryRepairCaseCreateRequest,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", pattern=_EVIDENCE_ID),
    ],
    correlation_id: Annotated[
        str,
        Header(alias="X-Correlation-Id", pattern=_EVIDENCE_ID),
    ],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFillInventoryRepairService,
        Depends(get_operator_fill_inventory_repair_service),
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
        permission=AdminApiPermission.SPOT_FILL_INVENTORY_REPAIR_RECORD,
        service_method="create_operator_fill_inventory_repair_case",
        live_coinbase_read_ran=False,
        operation=lambda: service.create_case(
            body=body,
            actor_id=actor.actor_id,
            correlation_id=correlation_id,
        ),
    )


@router.post(
    "/spot/fill-inventory-repair/cases/{case_id}/refresh",
    response_model=OperatorFillInventoryRepairCaseResponse,
    responses=MUTATION_RESPONSES,
    summary="Read one bounded no-retry Coinbase fill catalog",
)
def refresh_operator_fill_inventory_repair_case(
    request: Request,
    body: OperatorFillInventoryRepairRefreshRequest,
    case_id: Annotated[str, Path(min_length=36, max_length=36)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", pattern=_EVIDENCE_ID),
    ],
    correlation_id: Annotated[
        str,
        Header(alias="X-Correlation-Id", pattern=_EVIDENCE_ID),
    ],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFillInventoryRepairService,
        Depends(get_operator_fill_inventory_repair_service),
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
        permission=AdminApiPermission.SPOT_FILL_INVENTORY_REPAIR_EXECUTE,
        service_method="refresh_operator_fill_inventory_repair_case",
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
    body: OperatorFillInventoryRepairLocalActionRequest,
    case_id: str,
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
    actor: AdminApiActor,
    service: OperatorFillInventoryRepairService,
    idempotency_store: FileIdempotencyStore,
    audit_store: FileAdminApiAuditStore,
    action: str,
) -> JSONResponse:
    operation = service.apply_case if action == "apply" else service.rollback_case
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
        permission=AdminApiPermission.SPOT_FILL_INVENTORY_REPAIR_EXECUTE,
        service_method=f"{action}_operator_fill_inventory_repair_case",
        live_coinbase_read_ran=False,
        operation=lambda: operation(
            case_id=case_id,
            expected_revision=body.expected_revision,
            plan_sha256=body.plan_sha256,
            actor_id=actor.actor_id,
            operator_reason=body.operator_reason,
            correlation_id=correlation_id,
            operator_acknowledgement=body.operator_acknowledgement,
        ),
    )


@router.post(
    "/spot/fill-inventory-repair/cases/{case_id}/apply",
    response_model=OperatorFillInventoryRepairCaseResponse,
    responses=MUTATION_RESPONSES,
    summary="Apply one reviewed local missing-fill import batch",
)
def apply_operator_fill_inventory_repair_case(
    request: Request,
    body: OperatorFillInventoryRepairLocalActionRequest,
    case_id: Annotated[str, Path(min_length=36, max_length=36)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", pattern=_EVIDENCE_ID),
    ],
    correlation_id: Annotated[
        str,
        Header(alias="X-Correlation-Id", pattern=_EVIDENCE_ID),
    ],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFillInventoryRepairService,
        Depends(get_operator_fill_inventory_repair_service),
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
        action="apply",
    )


@router.post(
    "/spot/fill-inventory-repair/cases/{case_id}/rollback",
    response_model=OperatorFillInventoryRepairCaseResponse,
    responses=MUTATION_RESPONSES,
    summary="Roll back the exact applied local import batch",
)
def rollback_operator_fill_inventory_repair_case(
    request: Request,
    body: OperatorFillInventoryRepairLocalActionRequest,
    case_id: Annotated[str, Path(min_length=36, max_length=36)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", pattern=_EVIDENCE_ID),
    ],
    correlation_id: Annotated[
        str,
        Header(alias="X-Correlation-Id", pattern=_EVIDENCE_ID),
    ],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorFillInventoryRepairService,
        Depends(get_operator_fill_inventory_repair_service),
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
        action="rollback",
    )
