"""Backend-owned Spot recovery reconciliation completion evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from threading import RLock
import uuid

from pydantic import BaseModel, ConfigDict, Field

from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiGateStatus,
    AdminApiLiveExecutionStatus,
    AdminApiMutationFamilyType,
    AdminApiPermission,
    SpotRecoveryCompletionState,
)

from .audit import AdminApiAuditEvent
from .models import AdminLiveAdmissionDecisionEvidence
from .spot_recovery_execution import SpotRecoveryExecutionRecord
from .spot_recovery_proof import SpotRecoveryProofRecord
from .spot_recovery_proof_service import (
    RECONCILIATION_PROOF_METHOD,
    RECONCILIATION_PROOF_ROUTE,
    RECONCILIATION_PROOF_SERVICE_METHOD,
)
from .spot_recovery_repair import SpotRecoveryRepairResultRecord


COMPLETION_GUARD_CHAIN = [
    "reconciliation_proof",
    "apply_execution_journal",
    "repair_result",
    "recovery_apply_audit",
    "approval_snapshot",
    "admission_audit",
    "cap_guard_decision",
    "reconciliation_plan",
    "idempotency",
    "operator_intent",
    "payload_hash",
    "no_live_execution",
]


class SpotRecoveryCompletionGuardResult(BaseModel):
    """Fail-closed guard result for completion evidence recording."""

    model_config = ConfigDict(extra="forbid")

    client_order_id: str
    completion_id: str
    mutation_family: AdminApiMutationFamilyType = (
        AdminApiMutationFamilyType.SPOT_RECOVERY_RECONCILIATION_COMPLETION
    )
    completion_state: SpotRecoveryCompletionState = (
        SpotRecoveryCompletionState.REPAIR_BLOCKED
    )
    guard_status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED
    guard_passed: bool = False
    guard_failures: list[str] = Field(default_factory=list)
    required_guard_chain: list[str] = Field(
        default_factory=lambda: list(COMPLETION_GUARD_CHAIN)
    )
    repair_result_id: str | None = None
    journal_id: str | None = None
    audit_id: str | None = None
    reconciliation_proof_id: str | None = None
    proof_id: str | None = None
    proof_audit_id: str | None = None
    reconciliation_plan_id: str | None = None
    approval_snapshot_id: str | None = None
    admission_audit_id: str | None = None
    cap_guard_decision_id: str | None = None
    post_apply_reconciliation_completed: bool = False
    reconciliation_proof_satisfied: bool = False
    fully_reconciled: bool = False
    order_state_mutated: bool = False
    exchange_state_mutated: bool = False
    reconciliation_executed: bool = False
    coinbase_rest_read_ran: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str


class SpotRecoveryCompletionRecord(BaseModel):
    """Append-only evidence that post-apply reconciliation proof is complete."""

    model_config = ConfigDict(extra="forbid")

    completion_id: str
    recorded_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    mutation_family: AdminApiMutationFamilyType = (
        AdminApiMutationFamilyType.SPOT_RECOVERY_RECONCILIATION_COMPLETION
    )
    completion_state: SpotRecoveryCompletionState = (
        SpotRecoveryCompletionState.FULLY_RECONCILED
    )
    client_order_id: str = Field(min_length=1)
    repair_result_id: str = Field(min_length=1)
    journal_id: str = Field(min_length=1)
    audit_id: str = Field(min_length=1)
    reconciliation_proof_id: str = Field(min_length=1)
    proof_id: str = Field(min_length=1)
    proof_audit_id: str = Field(min_length=1)
    reconciliation_plan_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    route: str = RECONCILIATION_PROOF_ROUTE
    method: str = RECONCILIATION_PROOF_METHOD
    action_class: AdminApiActionClass = AdminApiActionClass.LOCAL_STATE_MUTATION
    required_permission: AdminApiPermission = AdminApiPermission.SPOT_RECOVERY_RECORD
    service_method: str = RECONCILIATION_PROOF_SERVICE_METHOD
    actor_id: str = Field(min_length=1)
    operator_intent: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    guard_passed: bool = True
    guard_failures: list[str] = Field(default_factory=list)
    post_apply_reconciliation_completed: bool = True
    reconciliation_proof_satisfied: bool = True
    fully_reconciled: bool = True
    order_state_mutated: bool = False
    exchange_state_mutated: bool = False
    reconciliation_executed: bool = False
    coinbase_rest_read_ran: bool = False
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False
    browser_authority: str = "display_only"
    bff_authority: str = "forward_only_no_execution"
    detail: str = (
        "Spot recovery post-apply reconciliation completion evidence was "
        "recorded after matching proof, apply journal, repair result, and "
        "admission evidence. This does not execute reconciliation, mutate "
        "order/exchange state, call Coinbase, or authorize browser/BFF "
        "execution."
    )


class FileSpotRecoveryCompletionJournalStore:
    """Append-only JSONL store for Spot recovery completion evidence."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get("COINBASE_ADMIN_API_SPOT_RECOVERY_COMPLETION_PATH")
            or Path("runtime_state") / "admin_api_spot_recovery_completion.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, record: SpotRecoveryCompletionRecord) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.completion_id

    def read_recent(self, *, limit: int = 100) -> list[SpotRecoveryCompletionRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[SpotRecoveryCompletionRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(SpotRecoveryCompletionRecord.model_validate_json(line))
            except ValueError:
                continue
            if len(records) >= normalized_limit:
                break
        return records

    def find_by_completion_id(
        self,
        completion_id: str,
    ) -> SpotRecoveryCompletionRecord | None:
        for record in self.read_recent(limit=500):
            if record.completion_id == completion_id:
                return record
        return None

    def find_by_reconciliation_proof_id(
        self,
        reconciliation_proof_id: str,
    ) -> SpotRecoveryCompletionRecord | None:
        for record in self.read_recent(limit=500):
            if record.reconciliation_proof_id == reconciliation_proof_id:
                return record
        return None

    def find_by_repair_result_id(
        self,
        repair_result_id: str,
    ) -> SpotRecoveryCompletionRecord | None:
        for record in self.read_recent(limit=500):
            if record.repair_result_id == repair_result_id:
                return record
        return None

    def read_for_client_order_id(
        self,
        client_order_id: str,
        *,
        limit: int = 100,
    ) -> list[SpotRecoveryCompletionRecord]:
        records: list[SpotRecoveryCompletionRecord] = []
        for record in self.read_recent(limit=500):
            if record.client_order_id != client_order_id:
                continue
            records.append(record)
            if len(records) >= max(1, min(limit, 500)):
                break
        return records


def build_spot_recovery_completion_id(
    *,
    client_order_id: str,
    repair_result_id: str | None,
    reconciliation_proof_id: str | None,
    reconciliation_plan_id: str | None,
) -> str:
    material = "|".join([
        "spot-recovery-reconciliation-completion",
        client_order_id,
        repair_result_id or "missing-repair-result",
        reconciliation_proof_id or "missing-reconciliation-proof",
        reconciliation_plan_id or "missing-reconciliation-plan",
    ])
    return (
        "spot-recovery-reconciliation-completion:"
        f"{uuid.uuid5(uuid.NAMESPACE_URL, material)}"
    )


def evaluate_spot_recovery_completion_guard(
    *,
    proof_record: SpotRecoveryProofRecord,
    apply_record: SpotRecoveryExecutionRecord | None,
    repair_result: SpotRecoveryRepairResultRecord | None,
    recovery_apply_audit: AdminApiAuditEvent | None,
    admission_decision: AdminLiveAdmissionDecisionEvidence,
    operator_intent: str,
    idempotency_key: str,
    payload_hash: str,
) -> SpotRecoveryCompletionGuardResult:
    completion_id = build_spot_recovery_completion_id(
        client_order_id=proof_record.client_order_id,
        repair_result_id=repair_result.repair_result_id if repair_result else None,
        reconciliation_proof_id=proof_record.reconciliation_proof_id,
        reconciliation_plan_id=proof_record.reconciliation_plan_id,
    )
    failures: list[str] = []

    if not proof_record.reconciliation_proof_id:
        failures.append("reconciliation_proof_missing")
    if proof_record.route != RECONCILIATION_PROOF_ROUTE:
        failures.append("proof_route_mismatch")
    if proof_record.method != RECONCILIATION_PROOF_METHOD:
        failures.append("proof_method_mismatch")
    if proof_record.service_method != RECONCILIATION_PROOF_SERVICE_METHOD:
        failures.append("proof_service_method_mismatch")
    if proof_record.required_permission != AdminApiPermission.SPOT_RECOVERY_RECORD:
        failures.append("proof_permission_mismatch")
    if proof_record.action_class != AdminApiActionClass.LOCAL_STATE_MUTATION:
        failures.append("proof_action_class_mismatch")
    if proof_record.operator_intent != operator_intent:
        failures.append("operator_intent_mismatch")
    if proof_record.idempotency_key != idempotency_key:
        failures.append("idempotency_key_mismatch")
    if proof_record.payload_hash != payload_hash:
        failures.append("payload_hash_mismatch")

    if apply_record is None:
        failures.append("apply_execution_journal_missing")
    else:
        if (
            apply_record.mutation_family
            != AdminApiMutationFamilyType.SPOT_RECOVERY_APPLY_EXECUTION
        ):
            failures.append("apply_journal_family_mismatch")
        if apply_record.client_order_id != proof_record.client_order_id:
            failures.append("apply_client_order_id_mismatch")
        if apply_record.audit_id != proof_record.recovery_apply_audit_id:
            failures.append("apply_audit_id_mismatch")
        if not apply_record.recovery_apply_journal_accepted:
            failures.append("apply_journal_not_accepted")
        if not apply_record.execution_journal_accepted:
            failures.append("execution_journal_not_accepted")
        if not apply_record.repair_result_journal_persisted:
            failures.append("repair_result_journal_not_persisted")
        if apply_record.reconciliation_plan_id != proof_record.reconciliation_plan_id:
            failures.append("apply_reconciliation_plan_mismatch")
        if apply_record.approval_snapshot_id != proof_record.approval_snapshot_id:
            failures.append("apply_approval_snapshot_mismatch")
        if apply_record.admission_audit_id != proof_record.admission_audit_id:
            failures.append("apply_admission_audit_mismatch")
        if apply_record.cap_guard_decision_id != proof_record.cap_guard_decision_id:
            failures.append("apply_cap_guard_mismatch")
        if apply_record.order_state_mutated:
            failures.append("apply_order_state_mutated")
        if apply_record.exchange_state_mutated:
            failures.append("apply_exchange_state_mutated")
        if apply_record.reconciliation_executed:
            failures.append("apply_reconciliation_executed")
        if apply_record.coinbase_rest_read_ran:
            failures.append("apply_coinbase_rest_read_ran")
        if apply_record.live_exchange_submitted:
            failures.append("apply_live_exchange_submitted")
        if apply_record.live_coinbase_orders_ran:
            failures.append("apply_live_coinbase_orders_ran")

    if repair_result is None:
        failures.append("repair_result_missing")
    else:
        if repair_result.client_order_id != proof_record.client_order_id:
            failures.append("repair_result_client_order_id_mismatch")
        if apply_record is not None:
            if repair_result.journal_id != apply_record.journal_id:
                failures.append("repair_result_journal_id_mismatch")
            if repair_result.audit_id != apply_record.audit_id:
                failures.append("repair_result_audit_id_mismatch")
            if repair_result.repair_result_id != apply_record.repair_result_id:
                failures.append("repair_result_id_mismatch")
        if not repair_result.guard_passed:
            failures.append("repair_result_guard_not_passed")
        if not repair_result.state_repair_executed:
            failures.append("repair_result_not_executed")
        if not repair_result.repair_applied:
            failures.append("repair_result_not_apply_side")
        if repair_result.rollback_applied:
            failures.append("repair_result_is_rollback_side")
        if repair_result.reconciliation_plan_id != proof_record.reconciliation_plan_id:
            failures.append("repair_reconciliation_plan_mismatch")
        if repair_result.approval_snapshot_id != proof_record.approval_snapshot_id:
            failures.append("repair_approval_snapshot_mismatch")
        if repair_result.admission_audit_id != proof_record.admission_audit_id:
            failures.append("repair_admission_audit_mismatch")
        if repair_result.cap_guard_decision_id != proof_record.cap_guard_decision_id:
            failures.append("repair_cap_guard_mismatch")
        if repair_result.order_state_mutated:
            failures.append("repair_order_state_mutated")
        if repair_result.exchange_state_mutated:
            failures.append("repair_exchange_state_mutated")
        if repair_result.reconciliation_executed:
            failures.append("repair_reconciliation_executed")
        if repair_result.coinbase_rest_read_ran:
            failures.append("repair_coinbase_rest_read_ran")
        if repair_result.live_exchange_submitted:
            failures.append("repair_live_exchange_submitted")
        if repair_result.live_coinbase_orders_ran:
            failures.append("repair_live_coinbase_orders_ran")

    if recovery_apply_audit is None:
        failures.append("recovery_apply_audit_missing")
    else:
        if recovery_apply_audit.audit_id != proof_record.recovery_apply_audit_id:
            failures.append("recovery_apply_audit_id_mismatch")
        if recovery_apply_audit.endpoint != "POST /api/v1/spot/recovery/apply-executions":
            failures.append("recovery_apply_audit_endpoint_mismatch")
        if recovery_apply_audit.permission != AdminApiPermission.SPOT_RECOVERY_EXECUTE:
            failures.append("recovery_apply_audit_permission_mismatch")
        if recovery_apply_audit.client_order_id != proof_record.client_order_id:
            failures.append("recovery_apply_audit_client_order_id_mismatch")
        if recovery_apply_audit.status not in {
            AdminApiCommandStatus.ACCEPTED,
            AdminApiCommandStatus.NOT_IMPLEMENTED,
        }:
            failures.append("recovery_apply_audit_status_mismatch")
        if recovery_apply_audit.live_execution_intent_ref is not None:
            failures.append("recovery_apply_audit_live_intent_present")

    expected_decision = {
        "route": admission_decision.route == RECONCILIATION_PROOF_ROUTE,
        "method": admission_decision.method == RECONCILIATION_PROOF_METHOD,
        "module_id": admission_decision.module_id == "spot_operations",
        "identity_key": admission_decision.identity_key == "client_order_id",
        "identity_value": (
            admission_decision.identity_value == proof_record.client_order_id
        ),
        "action_class": (
            admission_decision.action_class
            == AdminApiActionClass.LOCAL_STATE_MUTATION
        ),
        "required_permission": (
            admission_decision.required_permission
            == AdminApiPermission.SPOT_RECOVERY_RECORD
        ),
        "service_method": (
            admission_decision.service_method == RECONCILIATION_PROOF_SERVICE_METHOD
        ),
        "approval_snapshot": (
            admission_decision.approval_snapshot_present
            and admission_decision.approval_snapshot_id
            == proof_record.approval_snapshot_id
        ),
        "admission_audit": (
            admission_decision.admission_audit_present
            and admission_decision.admission_audit_id
            == proof_record.admission_audit_id
        ),
        "cap_guard": (
            admission_decision.cap_guard_present
            and admission_decision.cap_guard_decision_id
            == proof_record.cap_guard_decision_id
        ),
        "reconciliation_plan": (
            admission_decision.reconciliation_plan_present
            and admission_decision.reconciliation_plan_id
            == proof_record.reconciliation_plan_id
        ),
        "idempotency_key": admission_decision.idempotency_key == idempotency_key,
        "operator_intent": admission_decision.operator_intent == operator_intent,
        "payload_hash": admission_decision.payload_hash == payload_hash,
        "not_allowed": admission_decision.allowed is False,
        "live_disabled": admission_decision.status == AdminApiGateStatus.BLOCKED,
        "no_live": admission_decision.live_exchange_submitted is False,
    }
    failures.extend(
        f"admission_{name}_mismatch"
        for name, passed in expected_decision.items()
        if not passed
    )
    live_intent = admission_decision.live_execution_intent
    if live_intent is not None:
        if live_intent.executable:
            failures.append("admission_live_execution_intent_executable")
        if live_intent.prepared:
            failures.append("admission_live_execution_intent_prepared")
        if live_intent.live_exchange_submitted:
            failures.append("admission_live_execution_intent_submitted")
        if live_intent.status != AdminApiLiveExecutionStatus.LIVE_DISABLED:
            failures.append("admission_live_execution_intent_status_mismatch")
        if live_intent.route != RECONCILIATION_PROOF_ROUTE:
            failures.append("admission_live_execution_intent_route_mismatch")
        if live_intent.method != RECONCILIATION_PROOF_METHOD:
            failures.append("admission_live_execution_intent_method_mismatch")
        if live_intent.service_method != RECONCILIATION_PROOF_SERVICE_METHOD:
            failures.append("admission_live_execution_intent_service_mismatch")

    guard_passed = not failures
    return SpotRecoveryCompletionGuardResult(
        client_order_id=proof_record.client_order_id,
        completion_id=completion_id,
        completion_state=(
            SpotRecoveryCompletionState.FULLY_RECONCILED
            if guard_passed
            else SpotRecoveryCompletionState.REPAIR_BLOCKED
        ),
        guard_status=(
            AdminApiGateStatus.PASSED
            if guard_passed
            else AdminApiGateStatus.BLOCKED
        ),
        guard_passed=guard_passed,
        guard_failures=failures,
        repair_result_id=repair_result.repair_result_id if repair_result else None,
        journal_id=apply_record.journal_id if apply_record else None,
        audit_id=apply_record.audit_id if apply_record else None,
        reconciliation_proof_id=proof_record.reconciliation_proof_id,
        proof_id=proof_record.proof_id,
        proof_audit_id=proof_record.audit_id,
        reconciliation_plan_id=proof_record.reconciliation_plan_id,
        approval_snapshot_id=proof_record.approval_snapshot_id,
        admission_audit_id=proof_record.admission_audit_id,
        cap_guard_decision_id=proof_record.cap_guard_decision_id,
        post_apply_reconciliation_completed=guard_passed,
        reconciliation_proof_satisfied=guard_passed,
        fully_reconciled=guard_passed,
        detail=(
            "Post-apply reconciliation completion guard passed."
            if guard_passed
            else "Post-apply reconciliation completion guard blocked recording."
        ),
    )


def build_spot_recovery_completion_record(
    *,
    guard: SpotRecoveryCompletionGuardResult,
    actor_id: str,
    operator_intent: str,
    idempotency_key: str,
    correlation_id: str,
    payload_hash: str,
    now: datetime | None = None,
) -> SpotRecoveryCompletionRecord:
    if not guard.guard_passed:
        raise ValueError("Cannot build completion record from failed guard.")
    recorded_at = _normalize_now(now)
    return SpotRecoveryCompletionRecord(
        completion_id=guard.completion_id,
        recorded_at=recorded_at.isoformat(),
        client_order_id=guard.client_order_id,
        repair_result_id=str(guard.repair_result_id),
        journal_id=str(guard.journal_id),
        audit_id=str(guard.audit_id),
        reconciliation_proof_id=str(guard.reconciliation_proof_id),
        proof_id=str(guard.proof_id),
        proof_audit_id=str(guard.proof_audit_id),
        reconciliation_plan_id=str(guard.reconciliation_plan_id),
        approval_snapshot_id=str(guard.approval_snapshot_id),
        admission_audit_id=str(guard.admission_audit_id),
        cap_guard_decision_id=str(guard.cap_guard_decision_id),
        actor_id=actor_id,
        operator_intent=operator_intent,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload_hash=payload_hash,
        guard_passed=guard.guard_passed,
        guard_failures=guard.guard_failures,
    )


def _normalize_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)
