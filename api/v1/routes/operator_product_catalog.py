"""Authenticated Product Catalog administration routes."""

from __future__ import annotations

import re
from typing import Annotated, Any, Callable, Literal

from fastapi import APIRouter, Depends, Header, Path, Query, status
from fastapi.responses import JSONResponse

from application.admin_api.auth import (
    get_authenticated_actor,
    require_permission,
)
from application.admin_api.command_service import AdminApiCommandService
from application.admin_api.models import AdminApiActor, AdminApiErrorResponse
from application.admin_api.operator_product_catalog import (
    OperatorProductCatalogError,
)
from application.admin_api.operator_product_catalog_service import (
    OperatorProductCatalogService,
    ProductCatalogApproveRequest,
    ProductCatalogLifecycleRequest,
    ProductCatalogListResponse,
    ProductCatalogMutationResponse,
    ProductCatalogRefreshRequest,
    ProductCatalogRevisionResponse,
    ProductCatalogRollbackRequest,
)
from core.enums import AdminApiPermission
from database.operator_product_catalog import (
    OperatorProductCatalogRepository,
    get_default_operator_product_catalog_repository,
)

from .orders import get_command_service


router = APIRouter()
_UUID = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$"
)
_PRODUCT_ID = r"^[A-Z0-9]{1,32}(?:-[A-Z0-9]{1,32}){1,3}$"
_EVIDENCE_ID = r"^[A-Za-z0-9._:-]{1,255}$"
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
READ_RESPONSES = {
    401: {
        "model": AdminApiErrorResponse,
        "description": "Missing or invalid Admin API authentication.",
    },
    403: {
        "model": AdminApiErrorResponse,
        "description": "Actor lacks Product Catalog read authority.",
    },
    404: {
        "model": AdminApiErrorResponse,
        "description": "Product Catalog revision was not found.",
    },
}
MUTATION_RESPONSES = {
    200: {
        "model": ProductCatalogMutationResponse,
        "description": "Catalog command accepted or idempotently replayed.",
    },
    400: {
        "model": ProductCatalogMutationResponse,
        "description": "Catalog command rejected before an authorized effect.",
    },
    401: READ_RESPONSES[401],
    403: READ_RESPONSES[403],
    409: {
        "model": ProductCatalogMutationResponse,
        "description": "Catalog revision, allowance, or idempotency conflict.",
    },
}


def get_operator_product_catalog_repository(
) -> OperatorProductCatalogRepository:
    return get_default_operator_product_catalog_repository()


def get_operator_product_catalog_service(
    command_service: Annotated[
        AdminApiCommandService,
        Depends(get_command_service),
    ],
    repository: Annotated[
        OperatorProductCatalogRepository,
        Depends(get_operator_product_catalog_repository),
    ],
) -> OperatorProductCatalogService:
    dependencies = command_service.dependencies
    return OperatorProductCatalogService(
        repository=repository,
        rest_client=dependencies.rest_client,
        rest_client_available=dependencies.rest_client_available,
    )


@router.get(
    "/product-catalog",
    response_model=ProductCatalogListResponse,
    responses=READ_RESPONSES,
    summary="List immutable Product Catalog revisions",
)
def list_operator_product_catalog(
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorProductCatalogService,
        Depends(get_operator_product_catalog_service),
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    event_limit: Annotated[int, Query(ge=1, le=100)] = 25,
    event_offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return service.list_catalog(
        limit=limit,
        offset=offset,
        event_limit=event_limit,
        event_offset=event_offset,
    )


@router.get(
    "/product-catalog/revisions/{revision_id}",
    response_model=ProductCatalogRevisionResponse,
    responses=READ_RESPONSES,
    summary="Review one immutable Product Catalog revision and diff",
)
def get_operator_product_catalog_revision(
    revision_id: Annotated[str, Path(pattern=_UUID)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorProductCatalogService,
        Depends(get_operator_product_catalog_service),
    ],
) -> dict[str, Any]:
    require_permission(actor, AdminApiPermission.ANALYTICS_READ)
    return service.get_revision(revision_id=revision_id)


def _execute(
    *,
    actor: AdminApiActor,
    correlation_id: str,
    idempotency_key: str,
    service_method: Literal[
        "refresh_catalog",
        "approve_revision",
        "change_product_lifecycle",
        "rollback_revision",
    ],
    operation: Callable[[], ProductCatalogMutationResponse],
) -> JSONResponse:
    require_permission(actor, AdminApiPermission.CONFIG_UPDATE)
    try:
        response = operation()
    except OperatorProductCatalogError as exc:
        code = (
            exc.code
            if _SAFE_CODE.fullmatch(exc.code)
            else "product_catalog_internal_failure"
        )
        is_conflict = (
            "conflict" in code
            or "exhausted" in code
            or "idempotency" in code
        )
        response = ProductCatalogMutationResponse(
            status="conflict" if is_conflict else "rejected",
            message=code,
            service_method=service_method,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            local_state_mutated=False,
        )
    status_code = (
        status.HTTP_409_CONFLICT
        if response.status == "conflict"
        else status.HTTP_400_BAD_REQUEST
        if response.status == "rejected"
        else status.HTTP_200_OK
    )
    return JSONResponse(
        status_code=status_code,
        content=response.model_dump(mode="json"),
        headers={"X-Correlation-Id": correlation_id},
    )


@router.post(
    "/product-catalog/refresh",
    response_model=ProductCatalogMutationResponse,
    responses=MUTATION_RESPONSES,
    summary="Claim and read one no-retry logical Coinbase product catalog",
)
def refresh_operator_product_catalog(
    body: ProductCatalogRefreshRequest,
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorProductCatalogService,
        Depends(get_operator_product_catalog_service),
    ],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", pattern=_EVIDENCE_ID),
    ],
    correlation_id: Annotated[
        str,
        Header(alias="X-Correlation-Id", pattern=_EVIDENCE_ID),
    ],
    operator_intent: Annotated[
        Literal["refresh_operator_product_catalog"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    _ = operator_intent
    return _execute(
        actor=actor,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        service_method="refresh_catalog",
        operation=lambda: service.refresh_catalog(
            body=body,
            actor_id=actor.actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        ),
    )


@router.post(
    "/product-catalog/revisions/{revision_id}/approve",
    response_model=ProductCatalogMutationResponse,
    responses=MUTATION_RESPONSES,
    summary="Approve one exact reviewed Product Catalog revision",
)
def approve_operator_product_catalog_revision(
    body: ProductCatalogApproveRequest,
    revision_id: Annotated[str, Path(pattern=_UUID)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorProductCatalogService,
        Depends(get_operator_product_catalog_service),
    ],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", pattern=_EVIDENCE_ID),
    ],
    correlation_id: Annotated[
        str,
        Header(alias="X-Correlation-Id", pattern=_EVIDENCE_ID),
    ],
    operator_intent: Annotated[
        Literal["approve_operator_product_catalog_revision"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    _ = operator_intent
    return _execute(
        actor=actor,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        service_method="approve_revision",
        operation=lambda: service.approve_revision(
            revision_id=revision_id,
            body=body,
            actor_id=actor.actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        ),
    )


def _lifecycle(
    *,
    body: ProductCatalogLifecycleRequest,
    product_id: str,
    action: Literal["ENABLE", "DISABLE", "RETIRE"],
    actor: AdminApiActor,
    service: OperatorProductCatalogService,
    idempotency_key: str,
    correlation_id: str,
) -> JSONResponse:
    return _execute(
        actor=actor,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        service_method="change_product_lifecycle",
        operation=lambda: service.change_product_lifecycle(
            product_id=product_id,
            action=action,
            body=body,
            actor_id=actor.actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        ),
    )


@router.post(
    "/product-catalog/products/{product_id}/enable",
    response_model=ProductCatalogMutationResponse,
    responses=MUTATION_RESPONSES,
    summary="Enable one reviewed product in the administrative catalog",
)
def enable_operator_product_catalog_product(
    body: ProductCatalogLifecycleRequest,
    product_id: Annotated[str, Path(pattern=_PRODUCT_ID)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorProductCatalogService,
        Depends(get_operator_product_catalog_service),
    ],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", pattern=_EVIDENCE_ID),
    ],
    correlation_id: Annotated[
        str,
        Header(alias="X-Correlation-Id", pattern=_EVIDENCE_ID),
    ],
    operator_intent: Annotated[
        Literal["enable_operator_product_catalog_product"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    _ = operator_intent
    return _lifecycle(
        body=body,
        product_id=product_id,
        action="ENABLE",
        actor=actor,
        service=service,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )


@router.post(
    "/product-catalog/products/{product_id}/disable",
    response_model=ProductCatalogMutationResponse,
    responses=MUTATION_RESPONSES,
    summary="Disable one reviewed product in the administrative catalog",
)
def disable_operator_product_catalog_product(
    body: ProductCatalogLifecycleRequest,
    product_id: Annotated[str, Path(pattern=_PRODUCT_ID)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorProductCatalogService,
        Depends(get_operator_product_catalog_service),
    ],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", pattern=_EVIDENCE_ID),
    ],
    correlation_id: Annotated[
        str,
        Header(alias="X-Correlation-Id", pattern=_EVIDENCE_ID),
    ],
    operator_intent: Annotated[
        Literal["disable_operator_product_catalog_product"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    _ = operator_intent
    return _lifecycle(
        body=body,
        product_id=product_id,
        action="DISABLE",
        actor=actor,
        service=service,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )


@router.post(
    "/product-catalog/products/{product_id}/retire",
    response_model=ProductCatalogMutationResponse,
    responses=MUTATION_RESPONSES,
    summary="Retire one reviewed product from the administrative catalog",
)
def retire_operator_product_catalog_product(
    body: ProductCatalogLifecycleRequest,
    product_id: Annotated[str, Path(pattern=_PRODUCT_ID)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorProductCatalogService,
        Depends(get_operator_product_catalog_service),
    ],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", pattern=_EVIDENCE_ID),
    ],
    correlation_id: Annotated[
        str,
        Header(alias="X-Correlation-Id", pattern=_EVIDENCE_ID),
    ],
    operator_intent: Annotated[
        Literal["retire_operator_product_catalog_product"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    _ = operator_intent
    return _lifecycle(
        body=body,
        product_id=product_id,
        action="RETIRE",
        actor=actor,
        service=service,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )


@router.post(
    "/product-catalog/revisions/{target_revision_id}/rollback",
    response_model=ProductCatalogMutationResponse,
    responses=MUTATION_RESPONSES,
    summary="Restore an exact prior Product Catalog snapshot as a new revision",
)
def rollback_operator_product_catalog_revision(
    body: ProductCatalogRollbackRequest,
    target_revision_id: Annotated[str, Path(pattern=_UUID)],
    actor: Annotated[AdminApiActor, Depends(get_authenticated_actor)],
    service: Annotated[
        OperatorProductCatalogService,
        Depends(get_operator_product_catalog_service),
    ],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", pattern=_EVIDENCE_ID),
    ],
    correlation_id: Annotated[
        str,
        Header(alias="X-Correlation-Id", pattern=_EVIDENCE_ID),
    ],
    operator_intent: Annotated[
        Literal["rollback_operator_product_catalog_revision"],
        Header(alias="X-Operator-Intent"),
    ],
) -> JSONResponse:
    _ = operator_intent
    return _execute(
        actor=actor,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        service_method="rollback_revision",
        operation=lambda: service.rollback_revision(
            target_revision_id=target_revision_id,
            body=body,
            actor_id=actor.actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        ),
    )
