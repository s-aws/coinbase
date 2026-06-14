"""Durable Spot recovery exchange-state snapshot helpers."""

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
    SpotRecoveryExchangeStateSnapshotSource,
)


class SpotRecoveryExchangeStateSnapshotRecord(BaseModel):
    """Append-only backend exchange-state snapshot evidence."""

    model_config = ConfigDict(extra="forbid")

    exchange_state_snapshot_id: str = Field(min_length=1)
    recorded_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    mutation_family: AdminApiMutationFamilyType = (
        AdminApiMutationFamilyType.SPOT_RECOVERY_EXCHANGE_STATE_SNAPSHOT
    )
    client_order_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    source_timestamp: str = Field(min_length=1)
    snapshot_source: SpotRecoveryExchangeStateSnapshotSource
    snapshot_evidence_ref: str = Field(min_length=1)
    reconciliation_plan_id: str = Field(min_length=1)
    reconciliation_proof_id: str = Field(min_length=1)
    completion_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    route: str = Field(min_length=1)
    method: str = Field(min_length=1)
    module_id: str = "spot_operations"
    action_class: AdminApiActionClass = AdminApiActionClass.LOCAL_STATE_MUTATION
    required_permission: AdminApiPermission = AdminApiPermission.SPOT_RECOVERY_RECORD
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
    source: str = "admin_api_spot_recovery_snapshot_log"
    snapshot_recorded: bool = True
    source_trusted: bool = False
    coinbase_read_attempted: bool = False
    coinbase_read_succeeded: bool = False
    coinbase_rest_read_ran: bool = False
    order_state_mutated: bool = False
    exchange_state_mutated: bool = False
    reconciliation_executed: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"


class FileSpotRecoverySnapshotStore:
    """Append-only JSONL Spot recovery exchange-state snapshot store."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get("COINBASE_ADMIN_API_SPOT_RECOVERY_SNAPSHOT_LOG_PATH")
            or Path("runtime_state") / "admin_api_spot_recovery_snapshots.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, record: SpotRecoveryExchangeStateSnapshotRecord) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.exchange_state_snapshot_id

    def read_recent(
        self,
        *,
        limit: int = 100,
    ) -> list[SpotRecoveryExchangeStateSnapshotRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[SpotRecoveryExchangeStateSnapshotRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(
                    SpotRecoveryExchangeStateSnapshotRecord.model_validate_json(line)
                )
            except ValueError:
                continue
            if len(records) >= normalized_limit:
                break
        return records

    def find_by_snapshot_id(
        self,
        exchange_state_snapshot_id: str,
    ) -> SpotRecoveryExchangeStateSnapshotRecord | None:
        """Return the latest snapshot record for the snapshot id."""

        for record in self.read_recent(limit=500):
            if record.exchange_state_snapshot_id == exchange_state_snapshot_id:
                return record
        return None

    def read_for_client_order_id(
        self,
        client_order_id: str,
        *,
        limit: int = 100,
    ) -> list[SpotRecoveryExchangeStateSnapshotRecord]:
        """Return recent snapshot records for one client order id."""

        records: list[SpotRecoveryExchangeStateSnapshotRecord] = []
        for record in self.read_recent(limit=500):
            if record.client_order_id != client_order_id:
                continue
            records.append(record)
            if len(records) >= max(1, min(limit, 500)):
                break
        return records
