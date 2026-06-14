"""Backend-owned Spot recovery local repair guard and result evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from threading import RLock
import uuid

from pydantic import BaseModel, ConfigDict, Field

from core.enums import (
    AdminApiActionClass,
    AdminApiGateStatus,
    AdminApiMutationFamilyType,
    AdminApiPermission,
    SpotRecoveryCompletionState,
)


REPAIR_GUARD_CHAIN = [
    "execution_journal",
    "pre_apply_snapshot",
    "repair_target",
    "dry_run_repair_plan",
    "exchange_state_proof",
    "approval_snapshot",
    "admission_audit",
    "cap_guard_decision",
    "reconciliation_plan",
    "idempotency",
    "operator_intent",
    "payload_hash",
]


class SpotRecoveryRepairIds(BaseModel):
    """Deterministic ids required by the repair mutation guard."""

    model_config = ConfigDict(extra="forbid")

    repair_target_id: str
    pre_apply_snapshot_id: str
    dry_run_repair_plan_id: str
    repair_result_id: str


class SpotRecoveryRepairGuardResult(BaseModel):
    """Fail-closed evidence for a local Spot recovery repair attempt."""

    model_config = ConfigDict(extra="forbid")

    client_order_id: str
    mutation_family: AdminApiMutationFamilyType
    guard_status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    guard_passed: bool = False
    state_repair_requested: bool = False
    guard_failures: list[str] = Field(default_factory=list)
    required_guard_chain: list[str] = Field(default_factory=lambda: list(REPAIR_GUARD_CHAIN))
    repair_target_id: str | None = None
    expected_repair_target_id: str
    pre_apply_snapshot_id: str | None = None
    expected_pre_apply_snapshot_id: str
    dry_run_repair_plan_id: str | None = None
    expected_dry_run_repair_plan_id: str
    repair_result_id: str
    state_repair_executed: bool = Field(
        default=False,
        description=(
            "True only for accepted guarded local repair-result evidence. This "
            "does not imply order-state mutation, exchange-state mutation, "
            "reconciliation execution, Coinbase REST reads, or Coinbase order "
            "submission."
        ),
    )
    order_state_mutated: bool = Field(
        default=False,
        description="Guard evaluation does not mutate backend order state.",
    )
    exchange_state_mutated: bool = Field(
        default=False,
        description="Guard evaluation does not mutate exchange state.",
    )
    reconciliation_executed: bool = Field(
        default=False,
        description="Guard evaluation does not execute reconciliation.",
    )
    coinbase_rest_read_ran: bool = Field(
        default=False,
        description="Guard evaluation does not read Coinbase REST.",
    )
    live_exchange_submitted: bool = Field(
        default=False,
        description="Guard evaluation does not submit exchange orders.",
    )
    live_coinbase_orders_ran: bool = Field(
        default=False,
        description="Guard evaluation does not submit Coinbase orders.",
    )
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class SpotRecoveryRepairResultRecord(BaseModel):
    """Append-only evidence for a guarded local Spot recovery repair result."""

    model_config = ConfigDict(extra="forbid")

    repair_result_id: str
    recorded_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    mutation_family: AdminApiMutationFamilyType
    completion_state: SpotRecoveryCompletionState
    client_order_id: str = Field(min_length=1)
    journal_id: str = Field(min_length=1)
    audit_id: str = Field(min_length=1)
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
    action_class: AdminApiActionClass = AdminApiActionClass.LOCAL_STATE_MUTATION
    required_permission: AdminApiPermission = AdminApiPermission.SPOT_RECOVERY_EXECUTE
    service_method: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    repair_target_id: str = Field(min_length=1)
    pre_apply_snapshot_id: str = Field(min_length=1)
    dry_run_repair_plan_id: str = Field(min_length=1)
    guard_passed: bool = True
    guard_failures: list[str] = Field(default_factory=list)
    state_repair_executed: bool = Field(
        default=True,
        description=(
            "True for guarded local repair-result records accepted into "
            "backend recovery-state evidence. This does not imply order-state "
            "mutation, exchange-state mutation, reconciliation execution, "
            "Coinbase REST reads, or Coinbase order submission."
        ),
    )
    repair_applied: bool = Field(
        default=False,
        description=(
            "True when this local repair-result record represents the apply "
            "side of the recovery-state contract, not an order/exchange "
            "state mutation."
        ),
    )
    rollback_applied: bool = Field(
        default=False,
        description=(
            "True when this local repair-result record represents the "
            "rollback side of the recovery-state contract, not an "
            "order/exchange state mutation."
        ),
    )
    post_apply_reconciliation_completed: bool = False
    order_state_mutated: bool = False
    exchange_state_mutated: bool = False
    reconciliation_executed: bool = False
    coinbase_rest_read_ran: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str = (
        "Guarded Spot recovery local repair evidence was recorded without "
        "Coinbase reads, Coinbase submissions, browser authority, order-state "
        "mutation, exchange-state mutation, or reconciliation execution."
    )


class FileSpotRecoveryRepairResultJournalStore:
    """Append-only JSONL store for guarded Spot recovery repair results."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get("COINBASE_ADMIN_API_SPOT_RECOVERY_REPAIR_RESULT_PATH")
            or Path("runtime_state") / "admin_api_spot_recovery_repair_results.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, record: SpotRecoveryRepairResultRecord) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.repair_result_id

    def read_recent(self, *, limit: int = 100) -> list[SpotRecoveryRepairResultRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[SpotRecoveryRepairResultRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(SpotRecoveryRepairResultRecord.model_validate_json(line))
            except ValueError:
                continue
            if len(records) >= normalized_limit:
                break
        return records

    def find_by_repair_result_id(
        self,
        repair_result_id: str,
    ) -> SpotRecoveryRepairResultRecord | None:
        for record in self.read_recent(limit=500):
            if record.repair_result_id == repair_result_id:
                return record
        return None

    def find_by_journal_id(
        self,
        journal_id: str,
    ) -> SpotRecoveryRepairResultRecord | None:
        for record in self.read_recent(limit=500):
            if record.journal_id == journal_id:
                return record
        return None

    def read_for_client_order_id(
        self,
        client_order_id: str,
        *,
        limit: int = 100,
    ) -> list[SpotRecoveryRepairResultRecord]:
        records: list[SpotRecoveryRepairResultRecord] = []
        for record in self.read_recent(limit=500):
            if record.client_order_id != client_order_id:
                continue
            records.append(record)
            if len(records) >= max(1, min(limit, 500)):
                break
        return records


def build_spot_recovery_repair_ids(
    *,
    client_order_id: str,
    mutation_family: AdminApiMutationFamilyType,
    rollback_plan_id: str,
    evidence_id: str | None,
    reconciliation_plan_id: str,
) -> SpotRecoveryRepairIds:
    """Return deterministic ids required by the repair mutation guard."""

    target_id = _stable_repair_id(
        "spot-recovery-repair-target",
        client_order_id,
        mutation_family.value,
        rollback_plan_id,
        evidence_id or "missing-evidence",
        reconciliation_plan_id,
    )
    snapshot_id = _stable_repair_id(
        "spot-recovery-pre-apply-snapshot",
        client_order_id,
        target_id,
    )
    dry_run_plan_id = _stable_repair_id(
        "spot-recovery-dry-run-repair-plan",
        client_order_id,
        target_id,
        snapshot_id,
    )
    result_id = _stable_repair_id(
        "spot-recovery-repair-result",
        client_order_id,
        mutation_family.value,
        target_id,
        dry_run_plan_id,
    )
    return SpotRecoveryRepairIds(
        repair_target_id=target_id,
        pre_apply_snapshot_id=snapshot_id,
        dry_run_repair_plan_id=dry_run_plan_id,
        repair_result_id=result_id,
    )


def evaluate_spot_recovery_repair_guard(
    *,
    client_order_id: str,
    mutation_family: AdminApiMutationFamilyType,
    rollback_plan_id: str,
    evidence_id: str | None,
    reconciliation_plan_id: str,
    state_repair_requested: bool,
    repair_target_id: str | None,
    pre_apply_snapshot_id: str | None,
    dry_run_repair_plan_id: str | None,
    execution_journal_accepted: bool,
    exchange_state_proof_present: bool,
    approval_snapshot_present: bool,
    admission_audit_present: bool,
    cap_guard_present: bool,
    reconciliation_plan_present: bool,
    idempotency_key: str,
    operator_intent: str,
    payload_hash: str,
) -> SpotRecoveryRepairGuardResult:
    ids = build_spot_recovery_repair_ids(
        client_order_id=client_order_id,
        mutation_family=mutation_family,
        rollback_plan_id=rollback_plan_id,
        evidence_id=evidence_id,
        reconciliation_plan_id=reconciliation_plan_id,
    )
    failures: list[str] = []
    if not state_repair_requested:
        failures.append("state_repair_not_requested")
    if repair_target_id != ids.repair_target_id:
        failures.append("repair_target_id_mismatch")
    if pre_apply_snapshot_id != ids.pre_apply_snapshot_id:
        failures.append("pre_apply_snapshot_id_mismatch")
    if dry_run_repair_plan_id != ids.dry_run_repair_plan_id:
        failures.append("dry_run_repair_plan_id_mismatch")
    if not execution_journal_accepted:
        failures.append("execution_journal_missing")
    if not exchange_state_proof_present:
        failures.append("exchange_state_proof_missing")
    if not approval_snapshot_present:
        failures.append("approval_snapshot_missing")
    if not admission_audit_present:
        failures.append("admission_audit_missing")
    if not cap_guard_present:
        failures.append("cap_guard_decision_missing")
    if not reconciliation_plan_present:
        failures.append("reconciliation_plan_missing")
    if not idempotency_key:
        failures.append("idempotency_missing")
    if not operator_intent:
        failures.append("operator_intent_missing")
    if len(payload_hash) != 64:
        failures.append("payload_hash_invalid")

    guard_passed = not failures
    return SpotRecoveryRepairGuardResult(
        client_order_id=client_order_id,
        mutation_family=mutation_family,
        guard_status=(
            AdminApiGateStatus.PASSED if guard_passed else AdminApiGateStatus.BLOCKED
        ),
        guard_passed=guard_passed,
        state_repair_requested=state_repair_requested,
        guard_failures=failures,
        repair_target_id=repair_target_id,
        expected_repair_target_id=ids.repair_target_id,
        pre_apply_snapshot_id=pre_apply_snapshot_id,
        expected_pre_apply_snapshot_id=ids.pre_apply_snapshot_id,
        dry_run_repair_plan_id=dry_run_repair_plan_id,
        expected_dry_run_repair_plan_id=ids.dry_run_repair_plan_id,
        repair_result_id=ids.repair_result_id,
        state_repair_executed=guard_passed,
        detail=(
            "Spot recovery repair guard passed for backend-owned local repair "
            "evidence."
            if guard_passed
            else "Spot recovery repair guard is blocked: " + ", ".join(failures)
        ),
    )


def _stable_repair_id(prefix: str, *parts: str) -> str:
    material = "|".join([prefix, *parts])
    return f"{prefix}:{uuid.uuid5(uuid.NAMESPACE_URL, material)}"
