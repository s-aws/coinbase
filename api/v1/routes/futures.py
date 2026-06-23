"""Read-only futures/perpetual routes for the Admin API."""

from __future__ import annotations

from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, Header, Path, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from application.admin_api.auth import get_authenticated_actor, require_permission
from application.admin_api.approval import FileAdminApiApprovalStore
from application.admin_api.audit import FileAdminApiAuditStore
from application.admin_api.cap_guard import FileAdminApiCapGuardStore
from application.admin_api.command_service import AdminApiCommandService
from application.admin_api.futures_risk_proof import FileFuturesRiskProofStore
from application.admin_api.idempotency import FileIdempotencyStore
from application.admin_api.live_execution import AdminApiLiveExecutionService
from application.admin_api.models import (
    AdminApiActor,
    AdminApiCommandEnvelope,
    AdminApiCommandResponse,
    AdminApiErrorResponse,
    AdminFuturesAccountReadResponse,
    AdminFuturesCommandSuiteResponse,
    AdminFuturesPositionDetailResponse,
    AdminFuturesPositionListResponse,
    FuturesRiskProofDetailResponse,
    FuturesRiskProofListResponse,
    FuturesRiskProofRecordCommand,
    FuturesRiskProofRecordItem,
    FuturesRiskProofRecordRequest,
)
from application.admin_api.read_service import (
    AdminApiReadService,
    futures_command_suite_api_payload,
)
from application.admin_api.reconciliation import FileAdminApiReconciliationStore
from core.enums import (
    AdminApiActionClass,
    AdminApiPermission,
    AdminFuturesCommandAction,
    AdminFuturesCommandRiskProofKind,
)

from .orders import (
    COMMAND_ROUTE_RESPONSES,
    get_audit_store,
    get_approval_store,
    get_cap_guard_store,
    get_command_service,
    get_idempotency_store,
    get_live_execution_service,
    get_reconciliation_store,
    _build_envelope,
    _execute_idempotent_command,
    _idempotency_payload_hash,
)


router = APIRouter()

READ_ONLY_ROUTE_RESPONSES = {
    401: {
        "model": AdminApiErrorResponse,
        "description": "Missing or invalid Admin API authentication.",
    },
    403: {
        "model": AdminApiErrorResponse,
        "description": "Actor lacks the required Admin API permission.",
    },
}


def get_futures_risk_proof_store() -> FileFuturesRiskProofStore:
    """Return the append-only futures risk proof store."""

    return FileFuturesRiskProofStore()


def get_read_service(
    futures_risk_proof_store: Annotated[
        FileFuturesRiskProofStore,
        Depends(get_futures_risk_proof_store),
    ],
) -> AdminApiReadService:
    """Return the read-only Admin API status service."""

    return AdminApiReadService(futures_risk_proof_store=futures_risk_proof_store)


TReadModel = TypeVar("TReadModel", bound=BaseModel)


def _read_model_response(model: type[TReadModel], payload: object) -> JSONResponse:
    return JSONResponse(content=jsonable_encoder(model.model_validate(payload)))


def _risk_proof_record_item(record: object) -> FuturesRiskProofRecordItem:
    return FuturesRiskProofRecordItem.model_validate(
        record.model_dump(mode="json")
    )


@router.get(
    "/futures/command-suite",
    response_model=AdminFuturesCommandSuiteResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read futures and perpetual command contract readiness",
)
def get_futures_command_suite(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read blocked M57 futures/perpetual command contract evidence."""

    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_model_response(
        AdminFuturesCommandSuiteResponse,
        futures_command_suite_api_payload(service.build_futures_command_suite()),
    )


@router.get(
    "/futures/risk-proofs",
    response_model=FuturesRiskProofListResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read futures and perpetual risk proof records",
)
def list_futures_risk_proofs(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    proof_store: Annotated[
        FileFuturesRiskProofStore,
        Depends(get_futures_risk_proof_store),
    ],
    command: AdminFuturesCommandAction | None = None,
    proof_kind: AdminFuturesCommandRiskProofKind | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> JSONResponse:
    """Read persisted futures/perpetual risk proof evidence."""

    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    if command is None:
        records = proof_store.read_recent(limit=limit)
    else:
        records = proof_store.read_for_command(
            command=command,
            proof_kind=proof_kind,
            limit=limit,
        )
    if command is None and proof_kind is not None:
        records = [
            record
            for record in records
            if record.proof_kind == proof_kind
        ][:limit]
    response = FuturesRiskProofListResponse(
        filters={
            "command": command.value if command else None,
            "proof_kind": proof_kind.value if proof_kind else None,
            "limit": limit,
        },
        count=len(records),
        items=[_risk_proof_record_item(record) for record in records],
        proof_records_created=bool(records),
    )
    return _read_model_response(FuturesRiskProofListResponse, response)


@router.get(
    "/futures/risk-proofs/{futures_risk_proof_id}",
    response_model=FuturesRiskProofDetailResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read one futures or perpetual risk proof record",
)
def get_futures_risk_proof(
    futures_risk_proof_id: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    proof_store: Annotated[
        FileFuturesRiskProofStore,
        Depends(get_futures_risk_proof_store),
    ],
) -> JSONResponse:
    """Read one persisted futures/perpetual risk proof by proof id."""

    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    record = proof_store.find_by_proof_id(futures_risk_proof_id)
    response = FuturesRiskProofDetailResponse(
        futures_risk_proof_id=futures_risk_proof_id,
        found=record is not None,
        record=_risk_proof_record_item(record) if record is not None else None,
        proof_record_created=record is not None,
    )
    return _read_model_response(FuturesRiskProofDetailResponse, response)


@router.post(
    "/futures/risk-proofs",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_200_OK,
    responses=COMMAND_ROUTE_RESPONSES,
    summary="Record futures and perpetual risk proof evidence",
)
def record_futures_risk_proof(
    request: Request,
    body: FuturesRiskProofRecordRequest,
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
    """Route adapter for backend-owned no-live futures risk proofs."""

    endpoint = f"{request.method} {request.url.path}"
    envelope: AdminApiCommandEnvelope = _build_envelope(
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
    identity_value = f"{body.command.value}:{body.proof_kind.value}"
    return _execute_idempotent_command(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        endpoint=endpoint,
        request_id=correlation_id,
        operator_intent=operator_intent,
        permission=AdminApiPermission.FUTURES_RISK_PROOF_RECORD,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        service_method="record_futures_risk_proof",
        route_template="/api/v1/futures/risk-proofs",
        module_id="futures_perpetuals",
        identity_key="futures_risk_proof",
        identity_value=identity_value,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        approval_store=approval_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        live_execution_service=live_execution_service,
        command_runner_with_admission=lambda admission_decision: (
            service.record_futures_risk_proof(
                FuturesRiskProofRecordCommand(
                    envelope=envelope,
                    request=body,
                    admission_decision=admission_decision,
                )
            )
        ),
    )


@router.get(
    "/futures/account",
    response_model=AdminFuturesAccountReadResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read futures and perpetual account risk evidence",
)
def get_futures_account(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read futures/perpetual account evidence without mutating exchange state."""

    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_model_response(
        AdminFuturesAccountReadResponse,
        service.build_futures_account(),
    )


@router.get(
    "/futures/positions",
    response_model=AdminFuturesPositionListResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read futures and perpetual positions",
)
def list_futures_positions(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
    product_id: str | None = None,
    position_side: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    """Read futures/perpetual positions by position identity."""

    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_model_response(
        AdminFuturesPositionListResponse,
        service.build_futures_positions(
            product_id=product_id,
            position_side=position_side,
            limit=limit,
            offset=offset,
        ),
    )


@router.get(
    "/futures/positions/{position_key}",
    response_model=AdminFuturesPositionDetailResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="Read one futures or perpetual position by position_key",
)
def get_futures_position_by_position_key(
    position_key: Annotated[str, Path(min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[AdminApiReadService, Depends(get_read_service)],
) -> JSONResponse:
    """Read one futures/perpetual position by backend-defined position key."""

    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return _read_model_response(
        AdminFuturesPositionDetailResponse,
        service.build_futures_position_detail(position_key=position_key),
    )
