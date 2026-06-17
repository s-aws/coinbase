"""Durable stealth state-mutation policy proof helpers."""

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
    StealthStateMutationPolicyEvidenceSource,
)


class StealthStateMutationPolicyProofRecord(BaseModel):
    """Append-only backend stealth state-mutation policy evidence."""

    model_config = ConfigDict(extra="forbid")

    state_mutation_policy_proof_id: str = Field(min_length=1)
    recorded_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    mutation_family: AdminApiMutationFamilyType = (
        AdminApiMutationFamilyType.STEALTH_STATE_MUTATION_POLICY_PROOF
    )
    stealth_order_id: str = Field(min_length=1)
    guarded_command_route: str = Field(min_length=1)
    guarded_command_method: str = "POST"
    guarded_service_method: str = Field(min_length=1)
    guarded_mutation_family: AdminApiMutationFamilyType
    guarded_actor_id: str = Field(min_length=1)
    guarded_operator_intent: str = Field(min_length=1)
    guarded_idempotency_key: str = Field(min_length=1)
    guarded_payload_hash: str = Field(min_length=64, max_length=64)
    state_mutation_policy_ref: str = Field(min_length=1)
    lifecycle_state_policy_ref: str = Field(min_length=1)
    order_state_policy_ref: str = Field(min_length=1)
    exchange_state_policy_ref: str = Field(min_length=1)
    post_write_reconciliation_policy_ref: str = Field(min_length=1)
    evidence_source: StealthStateMutationPolicyEvidenceSource
    reconciliation_plan_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    route: str = Field(min_length=1)
    method: str = Field(min_length=1)
    module_id: str = "stealth_orders"
    action_class: AdminApiActionClass = AdminApiActionClass.LOCAL_STATE_MUTATION
    required_permission: AdminApiPermission = (
        AdminApiPermission.STEALTH_STATE_MUTATION_POLICY_RECORD
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
    source: str = "admin_api_stealth_state_mutation_policy_log"
    proof_persisted: bool = True
    state_mutation_policy_verified: bool = False
    state_mutation_allowed: bool = False
    lifecycle_state_mutation_allowed: bool = False
    order_state_mutation_allowed: bool = False
    exchange_state_mutation_allowed: bool = False
    manager_invocation_ran: bool = False
    reconciliation_plan_built: bool = False
    reconciliation_execution_ran: bool = False
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


class FileStealthStateMutationPolicyProofStore:
    """Append-only JSONL stealth state-mutation policy proof store."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get(
                "COINBASE_ADMIN_API_STEALTH_STATE_MUTATION_POLICY_LOG_PATH"
            )
            or Path("runtime_state")
            / "admin_api_stealth_state_mutation_policy_proofs.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, record: StealthStateMutationPolicyProofRecord) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.state_mutation_policy_proof_id

    def read_recent(
        self,
        *,
        limit: int = 100,
    ) -> list[StealthStateMutationPolicyProofRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[StealthStateMutationPolicyProofRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(
                    StealthStateMutationPolicyProofRecord.model_validate_json(line)
                )
            except ValueError:
                continue
            if len(records) >= normalized_limit:
                break
        return records

    def find_by_proof_id(
        self,
        state_mutation_policy_proof_id: str,
    ) -> StealthStateMutationPolicyProofRecord | None:
        """Return the latest state-mutation policy proof record for the id."""

        for record in self.read_recent(limit=500):
            if record.state_mutation_policy_proof_id == state_mutation_policy_proof_id:
                return record
        return None

    def read_for_stealth_order_id(
        self,
        stealth_order_id: str,
        *,
        limit: int = 100,
    ) -> list[StealthStateMutationPolicyProofRecord]:
        """Return recent state-mutation policy records for one stealth order."""

        records: list[StealthStateMutationPolicyProofRecord] = []
        for record in self.read_recent(limit=500):
            if record.stealth_order_id != stealth_order_id:
                continue
            records.append(record)
            if len(records) >= max(1, min(limit, 500)):
                break
        return records
