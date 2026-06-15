"""Durable stealth create lifecycle-write guard evidence helpers."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from threading import RLock

from pydantic import BaseModel, ConfigDict, Field

from core.enums import (
    AdminApiActionClass,
    AdminApiMutationFamilyType,
    AdminApiPermission,
    OrderSide,
    StealthLifecycleWriteGuardEvidenceSource,
)


class StealthCreateLifecycleWriteGuardProofRecord(BaseModel):
    """Append-only backend stealth create lifecycle-write guard evidence."""

    model_config = ConfigDict(extra="forbid")

    lifecycle_write_guard_proof_id: str = Field(min_length=1)
    recorded_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    mutation_family: AdminApiMutationFamilyType = (
        AdminApiMutationFamilyType.STEALTH_CREATE_LIFECYCLE_WRITE_GUARD_PROOF
    )
    stealth_order_id: str = Field(min_length=1)
    guarded_command_route: str = "/api/v1/stealth/orders"
    guarded_command_method: str = "POST"
    guarded_service_method: str = "create_stealth_order"
    guarded_actor_id: str = Field(min_length=1)
    guarded_operator_intent: str = Field(min_length=1)
    guarded_idempotency_key: str = Field(min_length=1)
    guarded_payload_hash: str = Field(min_length=64, max_length=64)
    product_id: str = Field(min_length=1)
    side: OrderSide
    total_size: str = Field(min_length=1)
    limit_price: str = Field(min_length=1)
    evidence_source: StealthLifecycleWriteGuardEvidenceSource
    guard_evidence_ref: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    reconciliation_plan_id: str = Field(min_length=1)
    route: str = Field(min_length=1)
    method: str = Field(min_length=1)
    module_id: str = "stealth_orders"
    action_class: AdminApiActionClass = AdminApiActionClass.LOCAL_STATE_MUTATION
    required_permission: AdminApiPermission = (
        AdminApiPermission.STEALTH_LIFECYCLE_WRITE_RECORD
    )
    service_method: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    audit_id: str = Field(min_length=1)
    dry_run: bool = True
    operator_reason: str | None = None
    manual_live_acknowledgement: bool = False
    source: str = "admin_api_stealth_lifecycle_write_guard_proof_log"
    proof_persisted: bool = True
    lifecycle_write_guard_verified: bool = False
    manager_invocation_ran: bool = False
    stealth_row_write_ran: bool = False
    order_parent_write_ran: bool = False
    lifecycle_event_dispatch_ran: bool = False
    local_lifecycle_mutation_ran: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    coinbase_order_submitted: bool = False
    coinbase_order_cancel_submitted: bool = False
    active_placement_cancel_replace_ran: bool = False
    reconciliation_executed: bool = False
    order_state_mutated: bool = False
    lifecycle_state_mutated: bool = False
    exchange_state_mutated: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"


class FileStealthLifecycleWriteGuardProofStore:
    """Append-only JSONL stealth lifecycle-write guard proof store."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get(
                "COINBASE_ADMIN_API_STEALTH_LIFECYCLE_WRITE_GUARD_PROOF_LOG_PATH"
            )
            or Path("runtime_state")
            / "admin_api_stealth_lifecycle_write_guard_proofs.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, record: StealthCreateLifecycleWriteGuardProofRecord) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.lifecycle_write_guard_proof_id

    def read_recent(
        self,
        *,
        limit: int = 100,
    ) -> list[StealthCreateLifecycleWriteGuardProofRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[StealthCreateLifecycleWriteGuardProofRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(
                    StealthCreateLifecycleWriteGuardProofRecord.model_validate_json(
                        line
                    )
                )
            except ValueError:
                continue
            if len(records) >= normalized_limit:
                break
        return records

    def find_by_proof_id(
        self,
        lifecycle_write_guard_proof_id: str,
    ) -> StealthCreateLifecycleWriteGuardProofRecord | None:
        """Return the latest lifecycle-write guard proof record for the id."""

        for record in self.read_recent(limit=500):
            if (
                record.lifecycle_write_guard_proof_id
                == lifecycle_write_guard_proof_id
            ):
                return record
        return None

    def read_for_stealth_order_id(
        self,
        stealth_order_id: str,
        *,
        limit: int = 100,
    ) -> list[StealthCreateLifecycleWriteGuardProofRecord]:
        """Return recent lifecycle-write guard proofs for one stealth order id."""

        records: list[StealthCreateLifecycleWriteGuardProofRecord] = []
        for record in self.read_recent(limit=500):
            if record.stealth_order_id != stealth_order_id:
                continue
            records.append(record)
            if len(records) >= max(1, min(limit, 500)):
                break
        return records
