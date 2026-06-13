"""Durable reconciliation plan proof helpers for Admin API admission."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from threading import RLock
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from core.enums import AdminApiActionClass, AdminApiGateStatus, AdminApiPermission


class ReconciliationPlanRequest(BaseModel):
    """Exact command shape a reconciliation plan proof must match."""

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
    approval_reconciliation_plan_ref: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)


class ReconciliationPlanRecord(BaseModel):
    """Append-only backend reconciliation plan evidence."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
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
    cap_guard_decision_id: str = Field(min_length=1)
    allowed: bool
    status: AdminApiGateStatus
    source: str = "admin_api_reconciliation_plan_log"
    reconciliation_policy_ref: str = Field(min_length=1)
    product_scope: str = Field(min_length=1)
    exchange_submission_required: bool = True
    post_submit_reconciliation_required: bool = True
    retained_inventory_required: bool = True
    max_submitted_notional_usdc: str = Field(min_length=1)
    max_executed_notional_usdc: str = Field(min_length=1)
    reason: str


class ReconciliationPlanProof(BaseModel):
    """Immutable evidence that a backend reconciliation plan matches admission."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(min_length=1)
    recorded_at: str = Field(min_length=1)
    source: str = "admin_api_reconciliation_plan_log"
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    reconciliation_policy_ref: str = Field(min_length=1)
    product_scope: str = Field(min_length=1)


class FileAdminApiReconciliationStore:
    """Append-only JSONL reconciliation plan store for future live admission."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get("COINBASE_ADMIN_API_RECONCILIATION_LOG_PATH")
            or Path("runtime_state") / "admin_api_reconciliation_plan.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, record: ReconciliationPlanRecord) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.plan_id

    def read_recent(self, *, limit: int = 100) -> list[ReconciliationPlanRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[ReconciliationPlanRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(ReconciliationPlanRecord.model_validate_json(line))
            except ValueError:
                continue
            if len(records) >= normalized_limit:
                break
        return records

    def find_by_plan_id(self, plan_id: str) -> ReconciliationPlanRecord | None:
        """Return the latest record with the given reconciliation plan id."""

        for record in self.read_recent(limit=500):
            if record.plan_id == plan_id:
                return record
        return None

    def find_matching_plan(
        self,
        *,
        request: ReconciliationPlanRequest,
    ) -> ReconciliationPlanRecord | None:
        """Return an exact allowed reconciliation plan if one exists."""

        for record in self.read_recent(limit=500):
            if not record.allowed or record.status != AdminApiGateStatus.PASSED:
                continue
            if record.plan_id != request.approval_reconciliation_plan_ref:
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
                and record.cap_guard_decision_id == request.cap_guard_decision_id
            ):
                return record
        return None


def resolve_reconciliation_plan(
    *,
    store: FileAdminApiReconciliationStore,
    request: ReconciliationPlanRequest,
) -> ReconciliationPlanProof | None:
    """Resolve exact backend-owned reconciliation plan proof for admission.

    This does not submit to Coinbase, run reconciliation, mutate orders, or
    make browser evidence authoritative.
    """

    record = store.find_matching_plan(request=request)
    if record is None:
        return None
    return ReconciliationPlanProof(
        plan_id=record.plan_id,
        recorded_at=record.recorded_at,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        cap_guard_decision_id=record.cap_guard_decision_id,
        reconciliation_policy_ref=record.reconciliation_policy_ref,
        product_scope=record.product_scope,
    )


def _enum_value(value: AdminApiActionClass | AdminApiPermission | str) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return value
