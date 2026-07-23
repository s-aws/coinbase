"""Authenticated local stealth-definition administration routes."""

from __future__ import annotations

import os
from typing import Annotated, Callable, Literal

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Path,
    Query,
    status,
)
from fastapi.responses import JSONResponse

from application.admin_api.auth import (
    get_authenticated_actor,
    require_permission,
)
from application.admin_api.models import AdminApiActor, AdminApiErrorResponse
from application.admin_api.operator_stealth_definition import (
    OperatorStealthDefinitionError,
)
from application.admin_api.operator_stealth_definition_service import (
    OperatorStealthDefinitionService,
    StealthDefinitionCancelRequest,
    StealthDefinitionClearRequest,
    StealthDefinitionCreateRequest,
    StealthDefinitionDetailResponse,
    StealthDefinitionEditRequest,
    StealthDefinitionExportRequest,
    StealthDefinitionImportApplyRequest,
    StealthDefinitionImportPreview,
    StealthDefinitionImportPreviewRequest,
    StealthDefinitionListResponse,
    StealthDefinitionMutationResponse,
    rejected_stealth_definition_mutation,
    safe_stealth_definition_code,
)
from core.enums import AdminApiPermission
from database.operator_stealth_definition import (
    get_default_operator_stealth_definition_repository,
)


OPERATOR_STEALTH_DEFINITIONS_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_STEALTH_DEFINITIONS_ENABLED"
)
_UUID = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_PRODUCT_ID = r"^[A-Z0-9]{1,32}(?:-[A-Z0-9]{1,32}){1,3}$"
_EVIDENCE_ID = r"^[A-Za-z0-9._:-]{1,255}$"


def require_operator_stealth_definitions_enabled() -> None:
    if os.environ.get(OPERATOR_STEALTH_DEFINITIONS_ENABLED_ENV) != "1":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator_stealth_definitions_disabled",
        )


router = APIRouter(
    dependencies=[Depends(require_operator_stealth_definitions_enabled)]
)

_READ_RESPONSES = {
    401: {"model": AdminApiErrorResponse},
    403: {"model": AdminApiErrorResponse},
    404: {"model": AdminApiErrorResponse},
    503: {"model": AdminApiErrorResponse},
}
_MUTATION_RESPONSES = {
    **_READ_RESPONSES,
    400: {"model": StealthDefinitionMutationResponse},
    409: {"model": StealthDefinitionMutationResponse},
}
_DefinitionId = Annotated[str, Path(pattern=_UUID)]
_PreviewId = Annotated[str, Path(pattern=_UUID)]
_Actor = Annotated[AdminApiActor, Depends(get_authenticated_actor)]
_IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", pattern=_EVIDENCE_ID),
]
_CorrelationId = Annotated[
    str,
    Header(alias="X-Correlation-Id", pattern=_EVIDENCE_ID),
]


def get_operator_stealth_definition_service(
) -> OperatorStealthDefinitionService:
    portfolio_id = str(
        os.environ.get("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID") or ""
    ).strip()
    try:
        return OperatorStealthDefinitionService(
            repository=(
                get_default_operator_stealth_definition_repository()
            ),
            configured_spot_portfolio_id=portfolio_id,
        )
    except OperatorStealthDefinitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=safe_stealth_definition_code(exc.code),
        ) from None
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="stealth_definition_service_unavailable",
        ) from None


_Service = Annotated[
    OperatorStealthDefinitionService,
    Depends(get_operator_stealth_definition_service),
]


@router.get(
    "/stealth/definitions",
    response_model=StealthDefinitionListResponse,
    responses=_READ_RESPONSES,
    summary="List local operator stealth definitions",
)
def list_operator_stealth_definitions(
    actor: _Actor,
    service: _Service,
    lifecycle_state: Annotated[
        Literal["DRAFT", "CANCELLED", "CLEARED"] | None,
        Query(),
    ] = None,
    product_id: Annotated[
        str | None,
        Query(pattern=_PRODUCT_ID),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    command_limit: Annotated[int, Query(ge=1, le=100)] = 25,
    command_offset: Annotated[int, Query(ge=0)] = 0,
) -> StealthDefinitionListResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return service.list_definitions(
        lifecycle_state=lifecycle_state,
        product_id=product_id,
        limit=limit,
        offset=offset,
        command_limit=command_limit,
        command_offset=command_offset,
    )


@router.get(
    "/stealth/definitions/{definition_id}",
    response_model=StealthDefinitionDetailResponse,
    responses=_READ_RESPONSES,
    summary="Review one local stealth definition and its events",
)
def get_operator_stealth_definition(
    definition_id: _DefinitionId,
    actor: _Actor,
    service: _Service,
    event_limit: Annotated[int, Query(ge=1, le=100)] = 25,
    event_offset: Annotated[int, Query(ge=0)] = 0,
) -> StealthDefinitionDetailResponse:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    try:
        return service.get_definition(
            definition_id=definition_id,
            event_limit=event_limit,
            event_offset=event_offset,
        )
    except OperatorStealthDefinitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=safe_stealth_definition_code(exc.code),
        ) from None


@router.get(
    "/stealth/definition-import-previews/{preview_id}",
    response_model=StealthDefinitionImportPreview,
    responses=_READ_RESPONSES,
    summary="Read one durable stealth-definition import preview",
)
def get_operator_stealth_definition_import_preview(
    preview_id: _PreviewId,
    actor: _Actor,
    service: _Service,
) -> StealthDefinitionImportPreview:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    try:
        return service.get_import_preview(preview_id=preview_id)
    except OperatorStealthDefinitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=safe_stealth_definition_code(exc.code),
        ) from None


def _execute(
    *,
    actor: AdminApiActor,
    service_method: Literal[
        "create_definition",
        "edit_definition",
        "cancel_definition",
        "clear_definitions",
        "export_definitions",
        "preview_import",
        "apply_import",
    ],
    correlation_id: str,
    idempotency_key: str,
    operation: Callable[[], StealthDefinitionMutationResponse],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.CONFIG_UPDATE)
    try:
        response = operation()
    except OperatorStealthDefinitionError as exc:
        response = rejected_stealth_definition_mutation(
            service_method=service_method,
            code=exc.code,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
    return JSONResponse(
        status_code=(
            status.HTTP_409_CONFLICT
            if response.status == "conflict"
            else status.HTTP_400_BAD_REQUEST
            if response.status == "rejected"
            else status.HTTP_200_OK
        ),
        content=response.model_dump(mode="json"),
        headers={"X-Correlation-Id": correlation_id},
    )


@router.post(
    "/stealth/definitions",
    response_model=StealthDefinitionMutationResponse,
    responses=_MUTATION_RESPONSES,
    summary="Create one local unrevealed stealth definition",
)
def create_operator_stealth_definition(
    body: StealthDefinitionCreateRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["create_stealth_definition"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    _ = operator_intent
    return _execute(
        actor=actor,
        service_method="create_definition",
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        operation=lambda: service.create_definition(
            body=body,
            actor_id=actor.actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        ),
    )


@router.post(
    "/stealth/definitions/{definition_id}/edit",
    response_model=StealthDefinitionMutationResponse,
    responses=_MUTATION_RESPONSES,
    summary="Edit one exact unrevealed stealth-definition revision",
)
def edit_operator_stealth_definition(
    definition_id: _DefinitionId,
    body: StealthDefinitionEditRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["edit_stealth_definition"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    _ = operator_intent
    return _execute(
        actor=actor,
        service_method="edit_definition",
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        operation=lambda: service.edit_definition(
            definition_id=definition_id,
            body=body,
            actor_id=actor.actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        ),
    )


@router.post(
    "/stealth/definitions/{definition_id}/cancel",
    response_model=StealthDefinitionMutationResponse,
    responses=_MUTATION_RESPONSES,
    summary="Cancel one exact unrevealed local stealth definition",
)
def cancel_operator_stealth_definition(
    definition_id: _DefinitionId,
    body: StealthDefinitionCancelRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["cancel_stealth_definition"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    _ = operator_intent
    return _execute(
        actor=actor,
        service_method="cancel_definition",
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        operation=lambda: service.cancel_definition(
            definition_id=definition_id,
            body=body,
            actor_id=actor.actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        ),
    )


@router.post(
    "/stealth/definitions/clear",
    response_model=StealthDefinitionMutationResponse,
    responses=_MUTATION_RESPONSES,
    summary="Clear an exact set of unrevealed local stealth definitions",
)
def clear_operator_stealth_definitions(
    body: StealthDefinitionClearRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["clear_stealth_definitions"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    _ = operator_intent
    return _execute(
        actor=actor,
        service_method="clear_definitions",
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        operation=lambda: service.clear_definitions(
            body=body,
            actor_id=actor.actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        ),
    )


@router.post(
    "/stealth/definition-exports",
    response_model=StealthDefinitionMutationResponse,
    responses=_MUTATION_RESPONSES,
    summary="Export an exact set of unrevealed stealth definitions",
)
def export_operator_stealth_definitions(
    body: StealthDefinitionExportRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["export_stealth_definitions"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    _ = operator_intent
    return _execute(
        actor=actor,
        service_method="export_definitions",
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        operation=lambda: service.export_definitions(
            body=body,
            actor_id=actor.actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        ),
    )


@router.post(
    "/stealth/definition-import-previews",
    response_model=StealthDefinitionMutationResponse,
    responses=_MUTATION_RESPONSES,
    summary="Validate and durably preview one stealth-definition import",
)
def preview_operator_stealth_definition_import(
    body: StealthDefinitionImportPreviewRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["preview_stealth_definition_import"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    _ = operator_intent
    return _execute(
        actor=actor,
        service_method="preview_import",
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        operation=lambda: service.preview_import(
            body=body,
            actor_id=actor.actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        ),
    )


@router.post(
    "/stealth/definition-import-previews/{preview_id}/apply",
    response_model=StealthDefinitionMutationResponse,
    responses=_MUTATION_RESPONSES,
    summary="Apply one exact valid stealth-definition import preview",
)
def apply_operator_stealth_definition_import(
    preview_id: _PreviewId,
    body: StealthDefinitionImportApplyRequest,
    actor: _Actor,
    service: _Service,
    idempotency_key: _IdempotencyKey,
    correlation_id: _CorrelationId,
    operator_intent: Annotated[
        Literal["apply_stealth_definition_import"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    _ = operator_intent
    return _execute(
        actor=actor,
        service_method="apply_import",
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        operation=lambda: service.apply_import(
            preview_id=preview_id,
            body=body,
            actor_id=actor.actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        ),
    )
