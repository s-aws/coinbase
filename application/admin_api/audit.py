"""Durable audit contract models for Admin API command work."""

from __future__ import annotations

from datetime import datetime, timezone
import os
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
    operator_intent: str | None = None
    idempotency_key: str | None = None
    approval_id: str | None = None
    client_order_id: str | None = None
    stealth_order_id: str | None = None
    coinbase_order_id: str | None = None
    status: AdminApiCommandStatus
    failure_stage: str | None = None
    message: str | None = None


class FileAdminApiAuditStore:
    """Append-only JSONL audit store for Admin API command attempts."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get("COINBASE_ADMIN_API_AUDIT_LOG_PATH")
            or Path("runtime_state") / "admin_api_audit.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, event: AdminApiAuditEvent) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(event.model_dump_json() + "\n")
            return event.audit_id

    def read_recent(self, *, limit: int = 100) -> list[AdminApiAuditEvent]:
        """Return recent audit events from the append-only JSONL store."""

        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        events: list[AdminApiAuditEvent] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                events.append(AdminApiAuditEvent.model_validate_json(line))
            except ValueError:
                continue
            if len(events) >= normalized_limit:
                break
        return events
