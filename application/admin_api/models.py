"""Typed Admin API command contracts.

These models describe the enterprise API boundary. They do not submit orders
or mutate exchange state by themselves.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiPermission,
    OrderSide,
    OrderType,
    TimeInForce,
)


DecimalString = Annotated[
    str,
    Field(
        pattern=r"^-?(0|[1-9]\d*)(\.\d+)?$",
        description="Decimal value serialized as a string; floats are not part of the API contract.",
        examples=["1.00"],
    ),
]


class AdminApiActor(BaseModel):
    """Authenticated actor evidence supplied by future auth middleware."""

    model_config = ConfigDict(extra="forbid")

    actor_id: str = Field(min_length=1)
    roles: list[str] = Field(default_factory=list)


class AdminApiCommandEnvelope(BaseModel):
    """Headers and actor evidence common to mutating command routes."""

    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    actor: AdminApiActor


class ManualOrderRequest(BaseModel):
    """Manual order request shape for future enterprise placement."""

    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, examples=["BTC-USDC"])
    side: OrderSide
    order_type: OrderType
    base_size: DecimalString | None = None
    quote_size: DecimalString | None = None
    limit_price: DecimalString | None = None
    post_only: bool = False
    time_in_force: TimeInForce | None = None
    manual_live_acknowledgement: bool = False


class CancelOrderRequest(BaseModel):
    """Cancel request body keyed by path ``client_order_id``."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


class ManualOrderCommand(BaseModel):
    """Shared service command for manual placement."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    request: ManualOrderRequest


class CancelOrderCommand(BaseModel):
    """Shared service command for cancel-by-client-order-id."""

    model_config = ConfigDict(extra="forbid")

    envelope: AdminApiCommandEnvelope
    client_order_id: str = Field(min_length=1)
    request: CancelOrderRequest


class AdminApiCommandResponse(BaseModel):
    """Typed response returned by Admin API command adapters."""

    model_config = ConfigDict(extra="forbid")

    status: AdminApiCommandStatus
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission
    service_method: str
    message: str
    client_order_id: str | None = None
    correlation_id: str | None = None
    idempotency_key: str | None = None
    audit_id: str | None = None
    live_exchange_submitted: Literal[False] = False


class AdminApiRouteInventoryItem(BaseModel):
    """Route/message inventory row used by docs and regression tests."""

    model_config = ConfigDict(extra="forbid")

    surface: str
    action_class: AdminApiActionClass
    permission: AdminApiPermission | str
    idempotency: str
    approval: str
    caps: str
    audit: str
    shared_method: str
    parity_test: str
    compatibility_mode: str | None = None

