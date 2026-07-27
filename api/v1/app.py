"""FastAPI application factory for the enterprise Admin API contract."""

from __future__ import annotations

import os
import uuid

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from application.admin_api.models import AdminApiErrorResponse
from core.enums import AdminApiErrorCode, AdminApiErrorSeverity

from .routes.admin import router as admin_router
from .routes.admission_audit import router as admission_audit_router
from .routes.automation import router as automation_router
from .routes.approvals import router as approvals_router
from .routes.cap_guard import router as cap_guard_router
from .routes.futures import router as futures_router
from .routes.follow_up_operations import router as follow_up_operations_router
from .routes.live_execution import router as live_execution_router
from .routes.movement_repricing import router as movement_repricing_router
from .routes.orders import router as orders_router
from .routes.operator_automation import router as operator_automation_router
from .routes.operator_fill_inventory_repair import (
    router as operator_fill_inventory_repair_router,
)
from .routes.operator_hotpoint import router as operator_hotpoint_router
from .routes.operator_product_catalog import (
    router as operator_product_catalog_router,
)
from .routes.operator_revealed_order_movement import (
    router as operator_revealed_order_movement_router,
)
from .routes.operator_parent_strategy import (
    router as operator_parent_strategy_router,
)
from .routes.operator_parent_move_premark import (
    router as operator_parent_move_premark_router,
)
from .routes.operator_stealth_definition import (
    router as operator_stealth_definition_router,
)
from .routes.operator_stealth_reveal import (
    router as operator_stealth_reveal_router,
)
from .routes.operator_single_order_reprice_now import (
    router as operator_single_order_reprice_now_router,
)
from .routes.operator_spot_safe_closeout_sweep import (
    router as operator_spot_safe_closeout_sweep_router,
)
from .routes.operator_spot_recovery import router as operator_spot_recovery_router
from .routes.reconciliation import router as reconciliation_router
from .routes.spot import router as spot_router
from .routes.stealth import router as stealth_router


_ADMIN_REQUIRED_AUTH_HEADERS = {"Authorization"}
_BOOTSTRAP_ACTOR_HEADERS = {
    "X-Admin-Actor": (
        "Required only for COINBASE_ADMIN_API_AUTH_MODE=bootstrap_bearer. "
        "Ignored in oidc_jwt mode because actor identity is derived from "
        "verified JWT claims."
    ),
    "X-Admin-Roles": (
        "Required only for COINBASE_ADMIN_API_AUTH_MODE=bootstrap_bearer. "
        "Ignored in oidc_jwt mode because role evidence is derived from "
        "verified JWT claims."
    ),
}
_CSRF_MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_TRUTHY_ENV_VALUES = {"1", "true", "yes"}
_MAX_OBSERVABILITY_ID_LENGTH = 255


def _safe_observability_id(value: object) -> str | None:
    """Accept only bounded visible-ASCII IDs before any response can echo them."""

    normalized = str(value or "")
    if not normalized or len(normalized) > _MAX_OBSERVABILITY_ID_LENGTH:
        return None
    if not normalized.isascii():
        return None
    if any(ord(character) < 33 or ord(character) > 126 for character in normalized):
        return None
    return normalized


def _request_ids(request: Request) -> tuple[str, str]:
    correlation_id = (
        _safe_observability_id(getattr(request.state, "correlation_id", None))
        or _safe_observability_id(request.headers.get("X-Correlation-Id"))
        or str(uuid.uuid4())
    )
    request_id = (
        _safe_observability_id(getattr(request.state, "request_id", None))
        or _safe_observability_id(request.headers.get("X-Request-Id"))
        or correlation_id
    )
    return correlation_id, request_id


def _error_code_for_status(status_code: int) -> AdminApiErrorCode:
    if status_code == status.HTTP_401_UNAUTHORIZED:
        return AdminApiErrorCode.AUTH_REQUIRED
    if status_code == status.HTTP_403_FORBIDDEN:
        return AdminApiErrorCode.PERMISSION_DENIED
    if status_code == status.HTTP_409_CONFLICT:
        return AdminApiErrorCode.IDEMPOTENCY_CONFLICT
    if status_code == status.HTTP_501_NOT_IMPLEMENTED:
        return AdminApiErrorCode.NOT_IMPLEMENTED
    if status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        return AdminApiErrorCode.BACKEND_UNAVAILABLE
    return AdminApiErrorCode.REQUEST_ERROR


def _severity_for_status(status_code: int) -> AdminApiErrorSeverity:
    if status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        return AdminApiErrorSeverity.ERROR
    if status_code in {
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_409_CONFLICT,
    }:
        return AdminApiErrorSeverity.WARNING
    return AdminApiErrorSeverity.ERROR


def _error_headers(correlation_id: str, request_id: str) -> dict[str, str]:
    return {
        "X-Correlation-Id": correlation_id,
        "X-Request-Id": request_id,
        "X-Live-Execution-Enabled": "false",
    }


def _csrf_required() -> bool:
    return (
        os.environ.get("COINBASE_ADMIN_API_CSRF_REQUIRED", "").strip().lower()
        in _TRUTHY_ENV_VALUES
    )


def _configured_csrf_token() -> str | None:
    token = os.environ.get("COINBASE_ADMIN_API_CSRF_TOKEN")
    token = token.strip() if token else ""
    return token or None


def _csrf_error_response(correlation_id: str, request_id: str) -> JSONResponse:
    body = AdminApiErrorResponse(
        code=AdminApiErrorCode.PERMISSION_DENIED,
        message="Invalid or missing Admin API CSRF token",
        severity=AdminApiErrorSeverity.WARNING,
        correlation_id=correlation_id,
    )
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content=body.model_dump(mode="json"),
        headers=_error_headers(correlation_id, request_id),
    )


def _customize_openapi(app: FastAPI) -> dict:
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            for parameter in operation.get("parameters", []):
                if parameter.get("in") != "header":
                    continue
                header_name = parameter.get("name")
                if header_name in _ADMIN_REQUIRED_AUTH_HEADERS:
                    parameter["required"] = True
                    continue
                description = _BOOTSTRAP_ACTOR_HEADERS.get(header_name)
                if description:
                    parameter["required"] = False
                    parameter["description"] = description
    _deduplicate_schema_enums(schema)
    return schema


def _deduplicate_schema_enums(value: object) -> None:
    """Remove duplicate enum values from generated OpenAPI fragments."""

    if isinstance(value, dict):
        enum_values = value.get("enum")
        if isinstance(enum_values, list):
            deduplicated: list[object] = []
            for enum_value in enum_values:
                if enum_value not in deduplicated:
                    deduplicated.append(enum_value)
            value["enum"] = deduplicated
        for child in value.values():
            _deduplicate_schema_enums(child)
        return
    if isinstance(value, list):
        for child in value:
            _deduplicate_schema_enums(child)


def create_app() -> FastAPI:
    """Create the Admin API app.

    The app exposes read-only operator routes plus fail-closed mutating command
    routes. Mutating HTTP routes already use shared command services for parity,
    but live Coinbase execution remains disabled by the approval gate.
    """

    app = FastAPI(
        title="Coinbase Admin API",
        version="0.1.0",
        description=(
            "Enterprise API for the Coinbase trading engine. Read-only operator "
            "routes are active; mutating HTTP routes use shared command "
            "services but remain live-disabled by the approval gate."
        ),
    )
    cors_origins = [
        origin.strip()
        for origin in os.environ.get("COINBASE_ADMIN_API_CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "Idempotency-Key",
                "X-Admin-Actor",
                "X-Admin-Roles",
                "X-Correlation-Id",
                "X-CSRF-Token",
                "X-Request-Id",
                "X-Operator-Intent",
            ],
        )

    @app.middleware("http")
    async def add_observability_headers(request: Request, call_next):
        correlation_id = (
            _safe_observability_id(request.headers.get("X-Correlation-Id"))
            or str(uuid.uuid4())
        )
        request_id = (
            _safe_observability_id(request.headers.get("X-Request-Id"))
            or correlation_id
        )
        request.state.correlation_id = correlation_id
        request.state.request_id = request_id
        if (
            _csrf_required()
            and request.method.upper() in _CSRF_MUTATION_METHODS
            and request.url.path.startswith("/api/v1/")
        ):
            expected_csrf_token = _configured_csrf_token()
            submitted_csrf_token = request.headers.get("X-CSRF-Token")
            if not expected_csrf_token or submitted_csrf_token != expected_csrf_token:
                return _csrf_error_response(correlation_id, request_id)
        response = await call_next(request)
        if "X-Correlation-Id" not in response.headers:
            response.headers["X-Correlation-Id"] = correlation_id
        if "X-Request-Id" not in response.headers:
            response.headers["X-Request-Id"] = request_id
        if "X-Admin-Api-Version" not in response.headers:
            response.headers["X-Admin-Api-Version"] = app.version
        if "X-Live-Execution-Enabled" not in response.headers:
            response.headers["X-Live-Execution-Enabled"] = "false"
        return response

    @app.exception_handler(HTTPException)
    async def admin_http_exception_handler(
        request: Request,
        exc: HTTPException,
    ) -> JSONResponse:
        correlation_id, request_id = _request_ids(request)
        message = str(exc.detail) if exc.detail else "Admin API request failed"
        body = AdminApiErrorResponse(
            code=_error_code_for_status(exc.status_code),
            message=message,
            severity=_severity_for_status(exc.status_code),
            correlation_id=correlation_id,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=body.model_dump(mode="json"),
            headers=_error_headers(correlation_id, request_id),
        )

    @app.exception_handler(RequestValidationError)
    async def admin_validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        correlation_id, request_id = _request_ids(request)
        first_error = exc.errors()[0] if exc.errors() else {}
        loc = first_error.get("loc") or []
        field_path = ".".join(str(part) for part in loc if part != "body") or None
        message = str(first_error.get("msg") or "Request validation failed")
        body = AdminApiErrorResponse(
            code=AdminApiErrorCode.VALIDATION_ERROR,
            message=message,
            severity=AdminApiErrorSeverity.ERROR,
            field_path=field_path,
            correlation_id=correlation_id,
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=body.model_dump(mode="json"),
            headers=_error_headers(correlation_id, request_id),
        )

    app.include_router(admin_router, prefix="/api/v1", tags=["admin"])
    app.include_router(
        automation_router,
        prefix="/api/v1",
        tags=["automation"],
    )
    app.include_router(
        admission_audit_router,
        prefix="/api/v1",
        tags=["admission-audit"],
    )
    app.include_router(approvals_router, prefix="/api/v1", tags=["approvals"])
    app.include_router(cap_guard_router, prefix="/api/v1", tags=["cap-guard"])
    app.include_router(
        reconciliation_router,
        prefix="/api/v1",
        tags=["reconciliation"],
    )
    app.include_router(
        live_execution_router,
        prefix="/api/v1",
        tags=["live-execution"],
    )
    app.include_router(futures_router, prefix="/api/v1", tags=["futures"])
    app.include_router(
        follow_up_operations_router,
        prefix="/api/v1",
        tags=["follow-up-operations"],
    )
    app.include_router(
        movement_repricing_router,
        prefix="/api/v1",
        tags=["movement-repricing"],
    )
    app.include_router(orders_router, prefix="/api/v1", tags=["orders"])
    app.include_router(
        operator_automation_router,
        prefix="/api/v1",
        tags=["operator-automation"],
    )
    app.include_router(
        operator_spot_recovery_router,
        prefix="/api/v1",
        tags=["operator-spot-recovery"],
    )
    app.include_router(
        operator_fill_inventory_repair_router,
        prefix="/api/v1",
        tags=["operator-fill-inventory-repair"],
    )
    app.include_router(
        operator_hotpoint_router,
        prefix="/api/v1",
        tags=["operator-hotpoint"],
    )
    app.include_router(
        operator_product_catalog_router,
        prefix="/api/v1",
        tags=["operator-product-catalog"],
    )
    app.include_router(
        operator_parent_strategy_router,
        prefix="/api/v1",
        tags=["operator-parent-strategy"],
    )
    app.include_router(
        operator_parent_move_premark_router,
        prefix="/api/v1",
        tags=["operator-parent-move-premark"],
    )
    app.include_router(
        operator_stealth_definition_router,
        prefix="/api/v1",
        tags=["operator-stealth-definition"],
    )
    app.include_router(
        operator_stealth_reveal_router,
        prefix="/api/v1",
        tags=["operator-stealth-reveal"],
    )
    app.include_router(
        operator_revealed_order_movement_router,
        prefix="/api/v1",
        tags=["operator-revealed-order-movement"],
    )
    app.include_router(
        operator_single_order_reprice_now_router,
        prefix="/api/v1",
        tags=["operator-single-order-reprice-now"],
    )
    app.include_router(
        operator_spot_safe_closeout_sweep_router,
        prefix="/api/v1",
        tags=["operator-spot-safe-closeout-sweep"],
    )
    app.include_router(spot_router, prefix="/api/v1", tags=["spot"])
    app.include_router(stealth_router, prefix="/api/v1", tags=["stealth"])

    def custom_openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema
        app.openapi_schema = _customize_openapi(app)
        return app.openapi_schema

    app.openapi = custom_openapi
    return app


app = create_app()
