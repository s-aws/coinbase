"""FastAPI application factory for the enterprise Admin API skeleton."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from .routes.orders import router as orders_router
from .routes.spot import router as spot_router


_ADMIN_AUTH_HEADERS = {
    "Authorization",
    "X-Admin-Actor",
    "X-Admin-Roles",
}


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
                if (
                    parameter.get("in") == "header"
                    and parameter.get("name") in _ADMIN_AUTH_HEADERS
                ):
                    parameter["required"] = True
    return schema


def create_app() -> FastAPI:
    """Create the Admin API app.

    The app currently exposes contract skeleton routes only. Live behavior must
    be added through shared command services after parity tests exist.
    """

    app = FastAPI(
        title="Coinbase Admin API",
        version="0.1.0",
        description=(
            "Enterprise API skeleton for the Coinbase trading engine. "
            "Routes do not submit Coinbase orders until shared-service extraction ships."
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
                "X-Operator-Intent",
            ],
    )
    app.include_router(orders_router, prefix="/api/v1", tags=["orders"])
    app.include_router(spot_router, prefix="/api/v1", tags=["spot"])

    def custom_openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema
        app.openapi_schema = _customize_openapi(app)
        return app.openapi_schema

    app.openapi = custom_openapi
    return app


app = create_app()
