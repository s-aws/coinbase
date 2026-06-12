"""Durable cap/guard decision proof helpers for Admin API admission."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from threading import RLock
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from core.enums import AdminApiActionClass, AdminApiGateStatus, AdminApiPermission


class CapGuardDecisionRequest(BaseModel):
    """Exact command shape a cap/guard decision proof must match."""

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
    approval_cap_guard_decision_ref: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)


class CapGuardDecisionRecord(BaseModel):
    """Append-only backend cap/guard decision evidence."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    recorded_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
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
    admission_audit_id: str = Field(min_length=1)
    allowed: bool
    status: AdminApiGateStatus
    source: str = "admin_api_cap_guard_log"
    cap_policy_ref: str = Field(min_length=1)
    guard_policy_ref: str = Field(min_length=1)
    product_scope: str = Field(min_length=1)
    max_submitted_notional_usdc: str = Field(min_length=1)
    max_executed_notional_usdc: str = Field(min_length=1)
    reason: str


class CapGuardDecisionProof(BaseModel):
    """Immutable evidence that a backend cap/guard decision matches admission."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(min_length=1)
    recorded_at: str = Field(min_length=1)
    source: str = "admin_api_cap_guard_log"
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_policy_ref: str = Field(min_length=1)
    guard_policy_ref: str = Field(min_length=1)
    product_scope: str = Field(min_length=1)


class FileAdminApiCapGuardStore:
    """Append-only JSONL cap/guard decision store for future live admission."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get("COINBASE_ADMIN_API_CAP_GUARD_LOG_PATH")
            or Path("runtime_state") / "admin_api_cap_guard.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, record: CapGuardDecisionRecord) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.decision_id

    def read_recent(self, *, limit: int = 100) -> list[CapGuardDecisionRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[CapGuardDecisionRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(CapGuardDecisionRecord.model_validate_json(line))
            except ValueError:
                continue
            if len(records) >= normalized_limit:
                break
        return records

    def find_by_decision_id(self, decision_id: str) -> CapGuardDecisionRecord | None:
        """Return the latest record with the given decision id, if present."""

        for record in self.read_recent(limit=500):
            if record.decision_id == decision_id:
                return record
        return None

    def find_matching_decision(
        self,
        *,
        request: CapGuardDecisionRequest,
    ) -> CapGuardDecisionRecord | None:
        """Return an exact allowed cap/guard decision if one exists."""

        for record in self.read_recent(limit=500):
            if not record.allowed or record.status != AdminApiGateStatus.PASSED:
                continue
            if record.decision_id != request.approval_cap_guard_decision_ref:
                continue
            if (
                record.route == request.route
                and record.method == request.method
                and record.module_id == request.module_id
                and record.identity_key == request.identity_key
                and record.identity_value == request.identity_value
                and _enum_value(record.action_class)
                == _enum_value(request.action_class)
                and _enum_value(record.required_permission)
                == _enum_value(request.required_permission)
                and record.service_method == request.service_method
                and record.actor_id == request.actor_id
                and record.operator_intent == request.operator_intent
                and record.idempotency_key == request.idempotency_key
                and record.payload_hash == request.payload_hash
                and record.approval_snapshot_id == request.approval_snapshot_id
                and record.admission_audit_id == request.admission_audit_id
            ):
                return record
        return None


def resolve_cap_guard_decision(
    *,
    store: FileAdminApiCapGuardStore,
    request: CapGuardDecisionRequest,
) -> CapGuardDecisionProof | None:
    """Resolve exact backend-owned cap/guard proof for command admission.

    This does not evaluate guards, write approval records, reconcile, call
    Coinbase, or make browser evidence authoritative.
    """

    record = store.find_matching_decision(request=request)
    if record is None:
        return None
    return CapGuardDecisionProof(
        decision_id=record.decision_id,
        recorded_at=record.recorded_at,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        cap_policy_ref=record.cap_policy_ref,
        guard_policy_ref=record.guard_policy_ref,
        product_scope=record.product_scope,
    )


def _enum_value(value: AdminApiActionClass | AdminApiPermission | str) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return value
