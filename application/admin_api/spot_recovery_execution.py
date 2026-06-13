"""Durable Spot recovery execution journal for Admin API local evidence."""

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
)


class SpotRecoveryExecutionRecord(BaseModel):
    """Append-only backend Spot recovery apply/rollback journal evidence."""

    model_config = ConfigDict(extra="forbid")

    journal_id: str = Field(min_length=1)
    recorded_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    mutation_family: AdminApiMutationFamilyType
    client_order_id: str = Field(min_length=1)
    rollback_plan_id: str = Field(min_length=1)
    recovery_apply_audit_id: str | None = None
    recovery_apply_journal_id: str | None = None
    exchange_state_proof_id: str | None = None
    reconciliation_proof_id: str | None = None
    reconciliation_plan_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    route: str = Field(min_length=1)
    method: str = Field(min_length=1)
    module_id: str = "spot_operations"
    action_class: AdminApiActionClass = AdminApiActionClass.LOCAL_STATE_MUTATION
    required_permission: AdminApiPermission = AdminApiPermission.SPOT_RECOVERY_EXECUTE
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
    source: str = "admin_api_spot_recovery_execution_journal"
    repair_journal_persisted: bool = True
    execution_journal_accepted: bool = Field(
        default=True,
        description=(
            "Append-only local execution journal acceptance. This is evidence "
            "only and does not imply state repair, rollback mutation, "
            "reconciliation execution, or Coinbase activity."
        ),
    )
    recovery_apply_journal_accepted: bool = Field(
        default=False,
        description=(
            "True when the accepted journal row is a recovery-apply journal. "
            "Prefer this over legacy recovery_apply_executed for new consumers."
        ),
    )
    rollback_journal_accepted: bool = Field(
        default=False,
        description=(
            "True when the accepted journal row is a rollback journal. Prefer "
            "this over legacy rollback_executed for new consumers."
        ),
    )
    recovery_apply_executed: bool = Field(
        default=False,
        description=(
            "Legacy compatibility flag for recovery apply journal acceptance "
            "only. This does not mean state repair executed; prefer "
            "execution_journal_accepted, recovery_apply_journal_accepted, and "
            "state_repair_executed."
        ),
    )
    rollback_executed: bool = Field(
        default=False,
        description=(
            "Legacy compatibility flag for rollback journal acceptance only. "
            "This does not mean rollback mutated order or exchange state; "
            "prefer execution_journal_accepted, rollback_journal_accepted, and "
            "state_repair_executed."
        ),
    )
    post_apply_reconciliation_required: bool = True
    post_apply_reconciliation_satisfied: bool = False
    repair_intent_accepted: bool = True
    state_repair_executed: bool = Field(
        default=False,
        description=(
            "True only when backend state repair actually executed. Current "
            "no-live recovery journals must leave this false."
        ),
    )
    order_state_mutated: bool = Field(
        default=False,
        description="True only when backend order state was actually mutated.",
    )
    exchange_state_mutated: bool = Field(
        default=False,
        description="True only when backend exchange state was actually mutated.",
    )
    reconciliation_executed: bool = Field(
        default=False,
        description="True only when backend reconciliation execution actually ran.",
    )
    coinbase_order_submitted: bool = False
    coinbase_rest_read_ran: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"


class FileSpotRecoveryExecutionJournalStore:
    """Append-only JSONL Spot recovery apply/rollback journal store."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get("COINBASE_ADMIN_API_SPOT_RECOVERY_EXECUTION_JOURNAL_PATH")
            or Path("runtime_state") / "admin_api_spot_recovery_execution_journal.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, record: SpotRecoveryExecutionRecord) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.journal_id

    def read_recent(self, *, limit: int = 100) -> list[SpotRecoveryExecutionRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[SpotRecoveryExecutionRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(SpotRecoveryExecutionRecord.model_validate_json(line))
            except ValueError:
                continue
            if len(records) >= normalized_limit:
                break
        return records

    def find_by_journal_id(
        self,
        journal_id: str,
    ) -> SpotRecoveryExecutionRecord | None:
        """Return the latest execution journal record with the given id."""

        for record in self.read_recent(limit=500):
            if record.journal_id == journal_id:
                return record
        return None

    def find_by_audit_id(self, audit_id: str) -> SpotRecoveryExecutionRecord | None:
        """Return the latest execution journal record with the given audit id."""

        for record in self.read_recent(limit=500):
            if record.audit_id == audit_id:
                return record
        return None

    def find_rollback_for_apply_audit(
        self,
        recovery_apply_audit_id: str,
    ) -> SpotRecoveryExecutionRecord | None:
        """Return the latest rollback journal linked to an apply audit id."""

        for record in self.read_recent(limit=500):
            if (
                record.mutation_family
                == AdminApiMutationFamilyType.SPOT_RECOVERY_ROLLBACK_EXECUTION
                and record.recovery_apply_audit_id == recovery_apply_audit_id
            ):
                return record
        return None

    def read_for_client_order_id(
        self,
        client_order_id: str,
        *,
        limit: int = 100,
    ) -> list[SpotRecoveryExecutionRecord]:
        """Return recent execution journal records for one client order id."""

        records: list[SpotRecoveryExecutionRecord] = []
        for record in self.read_recent(limit=500):
            if record.client_order_id != client_order_id:
                continue
            records.append(record)
            if len(records) >= max(1, min(limit, 500)):
                break
        return records
