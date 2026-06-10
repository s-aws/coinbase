"""Durable audit contract models for Admin API command work."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from core.enums import AdminApiActionClass, AdminApiCommandStatus, AdminApiPermission


class AdminApiAuditEvent(BaseModel):
    """Audit evidence shape for accepted and rejected command attempts."""

    model_config = ConfigDict(extra="forbid")

    audit_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    recorded_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
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
    message: str | None = None


class FileAdminApiAuditStore:
    """Append-only JSONL audit store for Admin API command attempts."""

    def __init__(self, path: Path | str = Path("runtime_state") / "admin_api_audit.jsonl") -> None:
        self.path = Path(path)
        self._lock = RLock()

    def append(self, event: AdminApiAuditEvent) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(event.model_dump_json() + "\n")
            return event.audit_id
