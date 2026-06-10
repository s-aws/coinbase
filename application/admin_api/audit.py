"""Durable audit contract models for Admin API command work."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.enums import AdminApiActionClass, AdminApiCommandStatus, AdminApiPermission


class AdminApiAuditEvent(BaseModel):
    """Audit evidence shape for accepted and rejected command attempts."""

    model_config = ConfigDict(extra="forbid")

    actor_id: str = Field(min_length=1)
    action_class: AdminApiActionClass
    permission: AdminApiPermission
    endpoint: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    idempotency_key: str | None = None
    approval_id: str | None = None
    client_order_id: str | None = None
    coinbase_order_id: str | None = None
    status: AdminApiCommandStatus
    failure_stage: str | None = None

