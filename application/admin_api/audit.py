"""Durable audit contract models for Admin API command work."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from core.enums import AdminApiActionClass, AdminApiCommandStatus, AdminApiPermission

from .models import AdminLiveAdmissionDecisionEvidence


_AUDIT_FILE_LOCK = RLock()


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
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    live_coinbase_read_ran: bool = False
    live_command_runtime_enabled: bool | None = None
    live_command_rest_client_available: bool | None = None
    live_command_runtime_ready: bool | None = None
    live_command_runtime_missing_reason: str | None = None
    live_command_runtime_source: str | None = None
    status: AdminApiCommandStatus | Literal["received"]
    failure_stage: str | None = None
    message: str | None = None
    admission_decision: AdminLiveAdmissionDecisionEvidence | None = None
    approval_cap_guard_decision_ref: str | None = None
    approval_reconciliation_plan_ref: str | None = None
    live_execution_intent_ref: str | None = None


class AdmissionAuditTrailRequest(BaseModel):
    """Exact command shape a live-admission audit proof must match."""

    model_config = ConfigDict(extra="forbid")

    route: str = Field(min_length=1)
    method: str = Field(min_length=1)
    module_id: str = Field(min_length=1)
    identity_key: str = Field(min_length=1)
    identity_value: str = Field(min_length=1)
    action_class: AdminApiActionClass
    required_permission: AdminApiPermission | str
    service_method: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    approval_snapshot_id: str = Field(min_length=1)


class AdmissionAuditProof(BaseModel):
    """Immutable evidence that an append-only audit row matches admission."""

    model_config = ConfigDict(extra="forbid")

    audit_id: str = Field(min_length=1)
    recorded_at: str = Field(min_length=1)
    source: str = "admin_api_audit_log"
    approval_snapshot_id: str = Field(min_length=1)


class FileAdminApiAuditStore:
    """Append-only JSONL audit store for Admin API command attempts."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get("COINBASE_ADMIN_API_AUDIT_LOG_PATH")
            or Path("runtime_state") / "admin_api_audit.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = _AUDIT_FILE_LOCK

    def _find_unique_by_audit_id_unlocked(
        self,
        audit_id: str,
    ) -> AdminApiAuditEvent | None:
        if not self.path.exists():
            return None
        matched: AdminApiAuditEvent | None = None
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    event = AdminApiAuditEvent.model_validate_json(line)
                except ValueError:
                    continue
                if event.audit_id != audit_id:
                    continue
                if matched is not None and matched != event:
                    raise ValueError("admin_api_audit_id_conflict")
                matched = event
        return matched

    def append(self, event: AdminApiAuditEvent) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(event.model_dump_json() + "\n")
            return event.audit_id

    def append_unique(self, event: AdminApiAuditEvent) -> str:
        """Append one exact canonical event, idempotently by audit id."""

        with self._lock:
            existing = self._find_unique_by_audit_id_unlocked(event.audit_id)
            if existing is not None:
                if existing != event:
                    raise ValueError("admin_api_audit_id_conflict")
                return event.audit_id
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

    def find_matching_admission_audit(
        self,
        *,
        request: AdmissionAuditTrailRequest,
    ) -> AdminApiAuditEvent | None:
        """Return an exact prior admission audit event if one exists."""

        for event in self.read_recent(limit=500):
            decision = event.admission_decision
            if decision is None:
                continue
            if decision.approval_snapshot_id != request.approval_snapshot_id:
                continue
            if (
                decision.route == request.route
                and decision.method == request.method
                and decision.module_id == request.module_id
                and decision.identity_key == request.identity_key
                and decision.identity_value == request.identity_value
                and _enum_value(decision.action_class)
                == _enum_value(request.action_class)
                and _enum_value(decision.required_permission)
                == _enum_value(request.required_permission)
                and decision.service_method == request.service_method
                and decision.actor_id == request.actor_id
                and decision.operator_intent == request.operator_intent
                and decision.idempotency_key == request.idempotency_key
                and decision.payload_hash == request.payload_hash
            ):
                return event
        return None

    def find_by_audit_id(self, audit_id: str) -> AdminApiAuditEvent | None:
        """Return the latest recent audit event with the given id, if present."""

        for event in self.read_recent(limit=500):
            if event.audit_id == audit_id:
                return event
        return None

    def find_unique_by_audit_id(
        self,
        audit_id: str,
    ) -> AdminApiAuditEvent | None:
        """Return one full-file exact event or reject conflicting duplicates."""

        with self._lock:
            return self._find_unique_by_audit_id_unlocked(audit_id)


def resolve_admission_audit_trail(
    *,
    store: FileAdminApiAuditStore,
    request: AdmissionAuditTrailRequest,
) -> AdmissionAuditProof | None:
    """Resolve exact backend-owned audit evidence for command admission.

    This does not write audit records, admit live execution, call Coinbase, or
    make browser evidence authoritative.
    """

    event = store.find_matching_admission_audit(request=request)
    if event is None:
        return None
    return AdmissionAuditProof(
        audit_id=event.audit_id,
        recorded_at=event.recorded_at,
        approval_snapshot_id=request.approval_snapshot_id,
    )


def _enum_value(value: AdminApiActionClass | AdminApiPermission | str) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return value
