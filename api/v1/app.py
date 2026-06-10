"""FastAPI application factory for the enterprise Admin API skeleton."""

from __future__ import annotations

from fastapi import FastAPI

from .routes.orders import router as orders_router


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
    app.include_router(orders_router, prefix="/api/v1", tags=["orders"])
    return app


app = create_app()

