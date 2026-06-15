"""No-live post-write reconciliation boundary evidence for stealth commands."""

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
    StealthPostWriteReconciliationEvidenceSource,
)

from .live_execution import (
    EXECUTION_BOUNDARY_AUTHORITY,
    POST_WRITE_RECONCILIATION_METHOD,
    POST_WRITE_RECONCILIATION_ROUTE,
    POST_WRITE_RECONCILIATION_SOURCE,
)
from .models import (
    AdminLiveAdmissionDecisionEvidence,
    StealthPostWriteReconciliationBoundaryEvidence,
    StealthPostWriteReconciliationCompletionVerifierEvidence,
)


POST_WRITE_RECONCILIATION_REQUIRED_EVIDENCE: tuple[str, ...] = (
    "route_bound_reconciliation_plan",
    "post_write_execution_journal",
    "post_write_completion_proof",
)

POST_WRITE_RECONCILIATION_COMPLETION_REQUIRED_EVIDENCE: tuple[str, ...] = (
    "safe_post_write_reconciliation_proof",
    "accepted_execution_journal",
    "verified_post_write_reconciliation",
)


class StealthPostWriteReconciliationProofRecord(BaseModel):
    """Append-only backend stealth post-write reconciliation proof evidence."""

    model_config = ConfigDict(extra="forbid")

    post_write_reconciliation_proof_id: str = Field(min_length=1)
    recorded_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    mutation_family: AdminApiMutationFamilyType = (
        AdminApiMutationFamilyType.STEALTH_POST_WRITE_RECONCILIATION_PROOF
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
    route_bound_reconciliation_plan_ref: str = Field(min_length=1)
    post_write_execution_journal_ref: str = Field(min_length=1)
    post_write_completion_proof_ref: str = Field(min_length=1)
    evidence_source: StealthPostWriteReconciliationEvidenceSource
    reconciliation_plan_id: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    admission_audit_id: str = Field(min_length=1)
    cap_guard_decision_id: str = Field(min_length=1)
    route: str = Field(min_length=1)
    method: str = Field(min_length=1)
    module_id: str = "stealth_orders"
    action_class: AdminApiActionClass = AdminApiActionClass.LOCAL_STATE_MUTATION
    required_permission: AdminApiPermission = AdminApiPermission.RECONCILIATION_RECORD
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
    source: str = "admin_api_stealth_post_write_reconciliation_proof_log"
    proof_persisted: bool = True
    post_write_reconciliation_verified: bool = False
    route_bound_reconciliation_plan_recorded: bool = True
    execution_journal_accepted: bool = False
    completion_proof_recorded: bool = True
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


class FileStealthPostWriteReconciliationProofStore:
    """Append-only JSONL stealth post-write reconciliation proof store."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured_path = (
            path
            or os.environ.get(
                "COINBASE_ADMIN_API_STEALTH_POST_WRITE_RECONCILIATION_PROOF_LOG_PATH"
            )
            or Path("runtime_state")
            / "admin_api_stealth_post_write_reconciliation_proofs.jsonl"
        )
        self.path = Path(configured_path)
        self._lock = RLock()

    def append(self, record: StealthPostWriteReconciliationProofRecord) -> str:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record.post_write_reconciliation_proof_id

    def read_recent(
        self,
        *,
        limit: int = 100,
    ) -> list[StealthPostWriteReconciliationProofRecord]:
        normalized_limit = max(1, min(limit, 500))
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[StealthPostWriteReconciliationProofRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(
                    StealthPostWriteReconciliationProofRecord.model_validate_json(
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
        post_write_reconciliation_proof_id: str,
    ) -> StealthPostWriteReconciliationProofRecord | None:
        """Return the latest post-write reconciliation proof record for the id."""

        for record in self.read_recent(limit=500):
            if (
                record.post_write_reconciliation_proof_id
                == post_write_reconciliation_proof_id
            ):
                return record
        return None

    def read_for_stealth_order_id(
        self,
        stealth_order_id: str,
        *,
        limit: int = 100,
    ) -> list[StealthPostWriteReconciliationProofRecord]:
        """Return recent post-write reconciliation proofs for one stealth order id."""

        records: list[StealthPostWriteReconciliationProofRecord] = []
        for record in self.read_recent(limit=500):
            if record.stealth_order_id != stealth_order_id:
                continue
            records.append(record)
            if len(records) >= max(1, min(limit, 500)):
                break
        return records


def build_stealth_post_write_reconciliation_boundary(
    *,
    mutation_family: AdminApiMutationFamilyType,
    command_route: str,
    service_method: str,
    stealth_order_id: str | None,
    admission_decision: AdminLiveAdmissionDecisionEvidence | None,
) -> StealthPostWriteReconciliationBoundaryEvidence:
    """Build fail-closed post-write reconciliation boundary evidence."""

    exact_context_present = admission_decision is not None
    return StealthPostWriteReconciliationBoundaryEvidence(
        mutation_family=mutation_family,
        command_route=command_route,
        service_method=service_method,
        stealth_order_id=stealth_order_id,
        command_context_bound=exact_context_present,
        payload_bound=exact_context_present,
        idempotency_bound=exact_context_present,
        operator_intent_bound=exact_context_present,
        idempotency_key=(
            admission_decision.idempotency_key
            if admission_decision is not None
            else None
        ),
        payload_hash=(
            admission_decision.payload_hash
            if admission_decision is not None
            else None
        ),
        operator_intent=(
            admission_decision.operator_intent
            if admission_decision is not None
            else None
        ),
        post_write_reconciliation_route=POST_WRITE_RECONCILIATION_ROUTE,
        post_write_reconciliation_method=POST_WRITE_RECONCILIATION_METHOD,
        post_write_reconciliation_source=POST_WRITE_RECONCILIATION_SOURCE,
        post_write_reconciliation_missing_reason=(
            "post_write_reconciliation_missing"
        ),
        required_evidence=list(POST_WRITE_RECONCILIATION_REQUIRED_EVIDENCE),
        missing_evidence=list(POST_WRITE_RECONCILIATION_REQUIRED_EVIDENCE),
        execution_boundary_authority=EXECUTION_BOUNDARY_AUTHORITY,
        evidence=[
            "Post-write reconciliation remains a backend-owned route-bound requirement.",
            "The boundary names the reconciliation-plan writer but does not record a plan.",
            "The boundary does not execute reconciliation or mutate order, lifecycle, or exchange state.",
            "Browser and BFF layers may display the boundary but cannot satisfy it.",
        ],
        detail=(
            f"{command_route} must be followed by a backend-owned "
            f"{POST_WRITE_RECONCILIATION_METHOD} "
            f"{POST_WRITE_RECONCILIATION_ROUTE} plan and completion proof before "
            "a future stealth write can be considered complete. This evidence "
            "does not run that plan, execute reconciliation, call Coinbase, or "
            "mutate local state."
        ),
    )


def is_safe_stealth_post_write_reconciliation_proof_record(
    record: StealthPostWriteReconciliationProofRecord,
) -> bool:
    """Return whether a proof record is no-live/no-mutation evidence only."""

    return (
        record.proof_persisted is True
        and record.route_bound_reconciliation_plan_recorded is True
        and record.execution_journal_accepted is False
        and record.completion_proof_recorded is True
        and record.post_write_reconciliation_verified is False
        and record.manager_invocation_ran is False
        and record.reconciliation_plan_built is False
        and record.reconciliation_execution_ran is False
        and record.coinbase_read_attempted is False
        and record.coinbase_read_succeeded is False
        and record.coinbase_rest_read_ran is False
        and record.coinbase_order_submitted is False
        and record.coinbase_order_cancel_submitted is False
        and record.active_placement_cancel_replace_ran is False
        and record.reconciliation_executed is False
        and record.order_state_mutated is False
        and record.lifecycle_state_mutated is False
        and record.exchange_state_mutated is False
        and record.live_exchange_submitted is False
        and record.live_coinbase_orders_ran is False
        and record.browser_authority == "display_only"
        and record.bff_authority == "forward_only_no_execution"
    )


def build_stealth_post_write_completion_verifier_contract(
    *,
    mutation_family: AdminApiMutationFamilyType,
    command_route: str,
    service_method: str,
    stealth_order_id: str | None,
    admission_decision: AdminLiveAdmissionDecisionEvidence | None,
    proof_record: StealthPostWriteReconciliationProofRecord | None,
) -> StealthPostWriteReconciliationCompletionVerifierEvidence:
    """Build fail-closed completion verifier evidence for post-write reconciliation."""

    exact_context_present = admission_decision is not None
    proof_safe = (
        proof_record is not None
        and is_safe_stealth_post_write_reconciliation_proof_record(proof_record)
    )
    missing_evidence: list[str] = []
    if not proof_safe:
        missing_evidence.append("safe_post_write_reconciliation_proof")
    if proof_record is None or proof_record.execution_journal_accepted is False:
        missing_evidence.append("accepted_execution_journal")
    if (
        proof_record is None
        or proof_record.post_write_reconciliation_verified is False
    ):
        missing_evidence.append("verified_post_write_reconciliation")

    return StealthPostWriteReconciliationCompletionVerifierEvidence(
        mutation_family=mutation_family,
        command_route=command_route,
        service_method=service_method,
        stealth_order_id=stealth_order_id,
        command_context_bound=exact_context_present,
        payload_bound=exact_context_present,
        idempotency_bound=exact_context_present,
        operator_intent_bound=exact_context_present,
        idempotency_key=(
            admission_decision.idempotency_key
            if admission_decision is not None
            else None
        ),
        payload_hash=(
            admission_decision.payload_hash
            if admission_decision is not None
            else None
        ),
        operator_intent=(
            admission_decision.operator_intent
            if admission_decision is not None
            else None
        ),
        post_write_reconciliation_proof_id=(
            proof_record.post_write_reconciliation_proof_id
            if proof_record is not None
            else None
        ),
        post_write_proof_found=proof_record is not None,
        post_write_proof_safe=proof_safe,
        execution_journal_accepted=(
            proof_record.execution_journal_accepted
            if proof_record is not None
            else False
        ),
        post_write_reconciliation_verified=(
            proof_record.post_write_reconciliation_verified
            if proof_record is not None
            else False
        ),
        completion_proof_recorded=(
            proof_record.completion_proof_recorded
            if proof_record is not None
            else False
        ),
        required_evidence=list(
            POST_WRITE_RECONCILIATION_COMPLETION_REQUIRED_EVIDENCE
        ),
        missing_evidence=missing_evidence,
        execution_boundary_authority=EXECUTION_BOUNDARY_AUTHORITY,
        evidence=[
            "Completion verifier evidence is backend-owned and fail-closed.",
            "A found post-write proof id is not sufficient to satisfy execution.",
            "Accepted execution-journal evidence and verified post-write reconciliation remain required.",
            "The verifier does not invoke managers, call Coinbase, execute reconciliation, or mutate state.",
        ],
        detail=(
            f"{command_route} post-write reconciliation completion remains "
            "blocked until a safe proof record is paired with accepted "
            "execution-journal evidence and verified post-write reconciliation. "
            "This verifier is read-only evidence and grants no browser, BFF, "
            "Coinbase, manager, reconciliation, or state-mutation authority."
        ),
    )
