"""Automation Admin API routes."""

from __future__ import annotations

from typing import Annotated, Callable
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from application.admin_api.audit import AdminApiAuditEvent, FileAdminApiAuditStore
from application.admin_api.auth import get_authenticated_actor, require_permission
from application.admin_api.idempotency import (
    FileIdempotencyStore,
    IdempotencyRecord,
    make_payload_hash,
)
from application.admin_api.models import (
    AdminApiActor,
    AdminApiErrorResponse,
    UsdcPairSnapshotOrderPlanItem,
    UsdcPairSnapshotOrderPlanListResponse,
    UsdcPairSnapshotOrderPlanRequest,
    UsdcPairSnapshotOrderPlanResponse,
    UsdcPairSnapshotRunItem,
    UsdcPairSnapshotRunListResponse,
    UsdcPairSnapshotRunRequest,
    UsdcPairSnapshotRunResponse,
)
from application.admin_api.usdc_pair_snapshot import (
    FileUsdcPairSnapshotOrderPlanStore,
    FileUsdcPairSnapshotRunStore,
)
from application.admin_api.usdc_pair_snapshot_service import (
    AdminApiUsdcPairSnapshotService,
    UsdcPairSnapshotError,
    item_from_record,
    order_plan_item_from_record,
)
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiIdempotencyDecision,
    AdminApiPermission,
)


router = APIRouter()

USDC_PAIR_SNAPSHOT_ENDPOINT = "POST /api/v1/automation/usdc-pair-snapshot-runs"
USDC_PAIR_SNAPSHOT_SERVICE_METHOD = "record_usdc_pair_snapshot_dry_run"
USDC_PAIR_SNAPSHOT_ORDER_PLAN_ENDPOINT = (
    "POST /api/v1/automation/usdc-pair-snapshot-runs/{run_id}/order-plans"
)
USDC_PAIR_SNAPSHOT_ORDER_PLAN_SERVICE_METHOD = (
    "record_usdc_pair_snapshot_order_plan"
)

AUTOMATION_ROUTE_RESPONSES = {
    200: {
        "model": UsdcPairSnapshotRunResponse,
        "description": "USDC pair snapshot dry-run evidence accepted or replayed.",
    },
    400: {
        "model": UsdcPairSnapshotRunResponse,
        "description": "USDC pair snapshot dry-run evidence rejected.",
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
        "model": UsdcPairSnapshotRunResponse,
        "description": "Idempotency key conflict.",
    },
}

ORDER_PLAN_ROUTE_RESPONSES = {
    200: {
        "model": UsdcPairSnapshotOrderPlanResponse,
        "description": "USDC pair snapshot order-plan evidence accepted or replayed.",
    },
    400: {
        "model": UsdcPairSnapshotOrderPlanResponse,
        "description": "USDC pair snapshot order-plan evidence rejected.",
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
        "model": UsdcPairSnapshotOrderPlanResponse,
        "description": "Idempotency key conflict.",
    },
}

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


def get_usdc_pair_snapshot_service() -> AdminApiUsdcPairSnapshotService:
    """Return the backend-owned M58 snapshot service."""

    return AdminApiUsdcPairSnapshotService()


def get_usdc_pair_snapshot_store() -> FileUsdcPairSnapshotRunStore:
    """Return durable M58 snapshot storage."""

    return FileUsdcPairSnapshotRunStore()


def get_usdc_pair_snapshot_order_plan_store() -> FileUsdcPairSnapshotOrderPlanStore:
    """Return durable M58 snapshot order-plan storage."""

    return FileUsdcPairSnapshotOrderPlanStore()


def get_idempotency_store() -> FileIdempotencyStore:
    """Return durable idempotency storage for automation mutations."""

    return FileIdempotencyStore()


def get_audit_store() -> FileAdminApiAuditStore:
    """Return durable audit storage for automation mutations."""

    return FileAdminApiAuditStore()


def _payload_hash(
    *,
    endpoint: str,
    actor: AdminApiActor,
    operator_intent: str,
    body: dict,
) -> str:
    return make_payload_hash({
        "endpoint": endpoint,
        "actor_id": actor.actor_id,
        "roles": [role.value for role in actor.roles],
        "operator_intent": operator_intent,
        "body": body,
    })


def _http_status(response: UsdcPairSnapshotRunResponse) -> int:
    if response.status == AdminApiCommandStatus.CONFLICT:
        return status.HTTP_409_CONFLICT
    if response.status == AdminApiCommandStatus.REJECTED:
        return status.HTTP_400_BAD_REQUEST
    return status.HTTP_200_OK


def _snapshot_response(
    response: UsdcPairSnapshotRunResponse,
    *,
    replayed: bool = False,
) -> JSONResponse:
    headers = {"X-Correlation-Id": response.correlation_id or ""}
    if replayed:
        headers["X-Idempotency-Replayed"] = "true"
    return JSONResponse(
        status_code=_http_status(response),
        content=response.model_dump(mode="json"),
        headers=headers,
    )


def _read_response(payload: object) -> JSONResponse:
    return JSONResponse(content=jsonable_encoder(payload))


def _snapshot_list_response(
    *,
    store: FileUsdcPairSnapshotRunStore,
    limit: int,
) -> UsdcPairSnapshotRunListResponse:
    runs = [item_from_record(record) for record in store.read_recent(limit=limit)]
    return UsdcPairSnapshotRunListResponse(
        runs=runs,
        returned_count=len(runs),
        total_count=store.count_records(),
        latest_run_id=runs[0].run_id if runs else None,
        returned_eligible_count=sum(run.eligible_count for run in runs),
        returned_skipped_count=sum(run.skipped_count for run in runs),
    )


def _order_plan_http_status(response: UsdcPairSnapshotOrderPlanResponse) -> int:
    if response.status == AdminApiCommandStatus.CONFLICT:
        return status.HTTP_409_CONFLICT
    if response.status == AdminApiCommandStatus.REJECTED:
        return status.HTTP_400_BAD_REQUEST
    return status.HTTP_200_OK


def _order_plan_response(
    response: UsdcPairSnapshotOrderPlanResponse,
    *,
    replayed: bool = False,
) -> JSONResponse:
    headers = {"X-Correlation-Id": response.correlation_id or ""}
    if replayed:
        headers["X-Idempotency-Replayed"] = "true"
    return JSONResponse(
        status_code=_order_plan_http_status(response),
        content=response.model_dump(mode="json"),
        headers=headers,
    )


def _order_plan_list_response(
    *,
    store: FileUsdcPairSnapshotOrderPlanStore,
    limit: int,
) -> UsdcPairSnapshotOrderPlanListResponse:
    plans = [
        order_plan_item_from_record(record) for record in store.read_recent(limit=limit)
    ]
    return UsdcPairSnapshotOrderPlanListResponse(
        plans=plans,
        returned_count=len(plans),
        total_count=store.count_records(),
        latest_plan_id=plans[0].plan_id if plans else None,
        returned_planned_count=sum(plan.planned_count for plan in plans),
        returned_skipped_count=sum(plan.skipped_count for plan in plans),
        returned_rejected_count=sum(plan.rejected_count for plan in plans),
    )


def _base_response(
    *,
    status_value: AdminApiCommandStatus,
    message: str,
    correlation_id: str,
    idempotency_key: str,
    run: UsdcPairSnapshotRunItem | None = None,
    audit_id: str | None = None,
    failure_stage: str | None = None,
) -> UsdcPairSnapshotRunResponse:
    return UsdcPairSnapshotRunResponse(
        status=status_value,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        required_permission=AdminApiPermission.CAMPAIGN_EXECUTE,
        service_method=USDC_PAIR_SNAPSHOT_SERVICE_METHOD,
        message=message,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        audit_id=audit_id,
        run=run,
        failure_stage=failure_stage,
    )


def _order_plan_base_response(
    *,
    status_value: AdminApiCommandStatus,
    message: str,
    correlation_id: str,
    idempotency_key: str,
    plan: UsdcPairSnapshotOrderPlanItem | None = None,
    audit_id: str | None = None,
    failure_stage: str | None = None,
) -> UsdcPairSnapshotOrderPlanResponse:
    return UsdcPairSnapshotOrderPlanResponse(
        status=status_value,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        required_permission=AdminApiPermission.CAMPAIGN_EXECUTE,
        service_method=USDC_PAIR_SNAPSHOT_ORDER_PLAN_SERVICE_METHOD,
        message=message,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        audit_id=audit_id,
        plan=plan,
        failure_stage=failure_stage,
    )


def _record_audit(
    *,
    audit_store: FileAdminApiAuditStore,
    actor: AdminApiActor,
    request_id: str,
    operator_intent: str,
    response: UsdcPairSnapshotRunResponse,
    audit_id: str | None = None,
) -> str:
    event_fields = {
        "actor_id": actor.actor_id,
        "action_class": response.action_class,
        "permission": response.required_permission,
        "endpoint": USDC_PAIR_SNAPSHOT_ENDPOINT,
        "request_id": request_id,
        "operator_intent": operator_intent,
        "idempotency_key": response.idempotency_key,
        "status": response.status,
        "failure_stage": response.failure_stage,
        "message": response.message,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
    }
    if audit_id is not None:
        event_fields["audit_id"] = audit_id
    return audit_store.append(AdminApiAuditEvent(**event_fields))


def _record_order_plan_audit(
    *,
    audit_store: FileAdminApiAuditStore,
    actor: AdminApiActor,
    request_id: str,
    operator_intent: str,
    response: UsdcPairSnapshotOrderPlanResponse,
    audit_id: str | None = None,
) -> str:
    event_fields = {
        "actor_id": actor.actor_id,
        "action_class": response.action_class,
        "permission": response.required_permission,
        "endpoint": USDC_PAIR_SNAPSHOT_ORDER_PLAN_ENDPOINT,
        "request_id": request_id,
        "operator_intent": operator_intent,
        "idempotency_key": response.idempotency_key,
        "status": response.status,
        "failure_stage": response.failure_stage,
        "message": response.message,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
    }
    if audit_id is not None:
        event_fields["audit_id"] = audit_id
    return audit_store.append(AdminApiAuditEvent(**event_fields))


def _execute_idempotent_snapshot(
    *,
    idempotency_key: str,
    payload_hash: str,
    actor: AdminApiActor,
    request_id: str,
    operator_intent: str,
    idempotency_store: FileIdempotencyStore,
    audit_store: FileAdminApiAuditStore,
    operation: Callable[[str], UsdcPairSnapshotRunItem],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.CAMPAIGN_EXECUTE)
    check = idempotency_store.evaluate(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
    )
    if check.decision == AdminApiIdempotencyDecision.REPLAY and check.record:
        return _snapshot_response(
            UsdcPairSnapshotRunResponse.model_validate(check.record.response),
            replayed=True,
        )
    if check.decision == AdminApiIdempotencyDecision.CONFLICT:
        response = _base_response(
            status_value=AdminApiCommandStatus.CONFLICT,
            message="Idempotency-Key was already used with a different payload.",
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            failure_stage="idempotency",
        )
        response.audit_id = _record_audit(
            audit_store=audit_store,
            actor=actor,
            request_id=request_id,
            operator_intent=operator_intent,
            response=response,
        )
        return _snapshot_response(response)

    try:
        audit_id = str(uuid4())
        run = operation(audit_id)
        response = _base_response(
            status_value=AdminApiCommandStatus.ACCEPTED,
            message="USDC pair snapshot dry-run evidence accepted.",
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            audit_id=audit_id,
            run=run,
        )
    except UsdcPairSnapshotError as exc:
        response = _base_response(
            status_value=AdminApiCommandStatus.REJECTED,
            message=str(exc),
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            failure_stage="usdc_pair_snapshot",
        )
    response.audit_id = _record_audit(
        audit_store=audit_store,
        actor=actor,
        request_id=request_id,
        operator_intent=operator_intent,
        response=response,
        audit_id=response.audit_id,
    )
    if response.status == AdminApiCommandStatus.ACCEPTED:
        idempotency_store.put_record(
            IdempotencyRecord(
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
                status=response.status,
                response=response.model_dump(mode="json"),
                actor_id=actor.actor_id,
                endpoint=USDC_PAIR_SNAPSHOT_ENDPOINT,
            )
        )
    return _snapshot_response(response)


def _execute_idempotent_order_plan(
    *,
    idempotency_key: str,
    payload_hash: str,
    actor: AdminApiActor,
    request_id: str,
    operator_intent: str,
    idempotency_store: FileIdempotencyStore,
    audit_store: FileAdminApiAuditStore,
    operation: Callable[[str], UsdcPairSnapshotOrderPlanItem],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.CAMPAIGN_EXECUTE)
    check = idempotency_store.evaluate(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
    )
    if check.decision == AdminApiIdempotencyDecision.REPLAY and check.record:
        return _order_plan_response(
            UsdcPairSnapshotOrderPlanResponse.model_validate(
                check.record.response
            ),
            replayed=True,
        )
    if check.decision == AdminApiIdempotencyDecision.CONFLICT:
        response = _order_plan_base_response(
            status_value=AdminApiCommandStatus.CONFLICT,
            message="Idempotency-Key was already used with a different payload.",
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            failure_stage="idempotency",
        )
        response.audit_id = _record_order_plan_audit(
            audit_store=audit_store,
            actor=actor,
            request_id=request_id,
            operator_intent=operator_intent,
            response=response,
        )
        return _order_plan_response(response)

    try:
        audit_id = str(uuid4())
        plan = operation(audit_id)
        response = _order_plan_base_response(
            status_value=AdminApiCommandStatus.ACCEPTED,
            message="USDC pair snapshot order-plan evidence accepted.",
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            audit_id=audit_id,
            plan=plan,
        )
    except UsdcPairSnapshotError as exc:
        response = _order_plan_base_response(
            status_value=AdminApiCommandStatus.REJECTED,
            message=str(exc),
            correlation_id=request_id,
            idempotency_key=idempotency_key,
            failure_stage="usdc_pair_snapshot_order_plan",
        )
    response.audit_id = _record_order_plan_audit(
        audit_store=audit_store,
        actor=actor,
        request_id=request_id,
        operator_intent=operator_intent,
        response=response,
        audit_id=response.audit_id,
    )
    if response.status == AdminApiCommandStatus.ACCEPTED:
        idempotency_store.put_record(
            IdempotencyRecord(
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
                status=response.status,
                response=response.model_dump(mode="json"),
                actor_id=actor.actor_id,
                endpoint=USDC_PAIR_SNAPSHOT_ORDER_PLAN_ENDPOINT,
            )
        )
    return _order_plan_response(response)


@router.get(
    "/automation/usdc-pair-snapshot-runs",
    response_model=UsdcPairSnapshotRunListResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="List backend-owned USDC pair snapshot dry-run evidence",
)
def list_usdc_pair_snapshot_runs(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    snapshot_store: Annotated[
        FileUsdcPairSnapshotRunStore,
        Depends(get_usdc_pair_snapshot_store),
    ],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> JSONResponse:
    """Read durable M58 dry-run snapshot evidence without Coinbase calls."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_response(_snapshot_list_response(store=snapshot_store, limit=limit))


@router.get(
    "/automation/usdc-pair-snapshot-order-plans",
    response_model=UsdcPairSnapshotOrderPlanListResponse,
    responses=READ_ONLY_ROUTE_RESPONSES,
    summary="List backend-owned USDC pair snapshot order-plan evidence",
)
def list_usdc_pair_snapshot_order_plans(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    order_plan_store: Annotated[
        FileUsdcPairSnapshotOrderPlanStore,
        Depends(get_usdc_pair_snapshot_order_plan_store),
    ],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> JSONResponse:
    """Read durable M58 dry-run order-plan evidence without Coinbase calls."""

    require_permission(actor, AdminApiPermission.AUDIT_READ)
    return _read_response(
        _order_plan_list_response(store=order_plan_store, limit=limit)
    )


@router.post(
    "/automation/usdc-pair-snapshot-runs",
    response_model=UsdcPairSnapshotRunResponse,
    status_code=status.HTTP_200_OK,
    responses=AUTOMATION_ROUTE_RESPONSES,
    summary="Record backend-owned USDC pair snapshot dry-run evidence",
)
def record_usdc_pair_snapshot_dry_run(
    request: Request,
    body: UsdcPairSnapshotRunRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        AdminApiUsdcPairSnapshotService,
        Depends(get_usdc_pair_snapshot_service),
    ],
    snapshot_store: Annotated[
        FileUsdcPairSnapshotRunStore,
        Depends(get_usdc_pair_snapshot_store),
    ],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
) -> JSONResponse:
    """Record M58 dry-run product snapshot rows without Coinbase order calls."""

    endpoint = f"{request.method} {request.url.path}"
    payload_hash = _payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
    )
    return _execute_idempotent_snapshot(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        request_id=correlation_id,
        operator_intent=operator_intent,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        operation=lambda audit_id: service.record_snapshot_run(
            store=snapshot_store,
            body=body,
            actor_id=actor.actor_id,
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            audit_id=audit_id,
        ),
    )


@router.post(
    "/automation/usdc-pair-snapshot-runs/{run_id}/order-plans",
    response_model=UsdcPairSnapshotOrderPlanResponse,
    status_code=status.HTTP_200_OK,
    responses=ORDER_PLAN_ROUTE_RESPONSES,
    summary="Record backend-owned USDC pair snapshot order-plan evidence",
)
def record_usdc_pair_snapshot_order_plan(
    request: Request,
    run_id: str,
    body: UsdcPairSnapshotOrderPlanRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        AdminApiUsdcPairSnapshotService,
        Depends(get_usdc_pair_snapshot_service),
    ],
    snapshot_store: Annotated[
        FileUsdcPairSnapshotRunStore,
        Depends(get_usdc_pair_snapshot_store),
    ],
    order_plan_store: Annotated[
        FileUsdcPairSnapshotOrderPlanStore,
        Depends(get_usdc_pair_snapshot_order_plan_store),
    ],
    idempotency_store: Annotated[FileIdempotencyStore, Depends(get_idempotency_store)],
    audit_store: Annotated[FileAdminApiAuditStore, Depends(get_audit_store)],
) -> JSONResponse:
    """Record M58 dry-run limit-order plan rows without Coinbase order calls."""

    endpoint = f"{request.method} {request.url.path}"
    payload_hash = _payload_hash(
        endpoint=endpoint,
        actor=actor,
        operator_intent=operator_intent,
        body=body.model_dump(mode="json"),
    )
    return _execute_idempotent_order_plan(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        actor=actor,
        request_id=correlation_id,
        operator_intent=operator_intent,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
        operation=lambda audit_id: service.record_order_plan(
            snapshot_store=snapshot_store,
            order_plan_store=order_plan_store,
            run_id=run_id,
            body=body,
            actor_id=actor.actor_id,
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            audit_id=audit_id,
        ),
    )
