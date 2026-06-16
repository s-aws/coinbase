"""Backend-owned stealth post-write reconciliation proof service."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from core.enums import (
    AdminApiActionClass,
    AdminApiGateStatus,
    AdminApiMutationFamilyType,
    AdminApiPermission,
)

from .models import (
    AdminLiveAdmissionDecisionEvidence,
    StealthPostWriteExecutionJournalRequest,
    StealthPostWriteReconciliationProofRequest,
    StealthPostWriteReconciliationVerificationRequest,
)
from .route_inventory import ADMIN_API_ROUTE_INVENTORY
from .stealth_post_write_reconciliation import (
    FileStealthPostWriteExecutionJournalStore,
    FileStealthPostWriteReconciliationProofStore,
    FileStealthPostWriteReconciliationVerificationStore,
    StealthPostWriteExecutionJournalAcceptanceRecord,
    StealthPostWriteReconciliationProofRecord,
    StealthPostWriteReconciliationVerificationRecord,
    is_safe_stealth_post_write_execution_journal_record,
    is_safe_stealth_post_write_reconciliation_proof_record,
    post_write_reconciliation_verification_matches,
    post_write_execution_journal_matches_proof,
)


PROOF_ROUTE = (
    "/api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-proofs"
)
READBACK_ROUTE = (
    "/api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-proof"
)
JOURNAL_ROUTE = (
    "/api/v1/stealth/orders/{stealth_order_id}/post-write-execution-journals"
)
JOURNAL_READBACK_ROUTE = (
    "/api/v1/stealth/orders/{stealth_order_id}/post-write-execution-journals"
)
VERIFICATION_ROUTE = (
    "/api/v1/stealth/orders/{stealth_order_id}/"
    "post-write-reconciliation-verifications"
)
VERIFICATION_READBACK_ROUTE = (
    "/api/v1/stealth/orders/{stealth_order_id}/"
    "post-write-reconciliation-verifications"
)
PROOF_METHOD = "POST"
READBACK_METHOD = "GET"
PROOF_SERVICE_METHOD = "record_stealth_post_write_reconciliation_proof"
JOURNAL_SERVICE_METHOD = "record_stealth_post_write_execution_journal"
JOURNAL_READBACK_SERVICE_METHOD = "build_stealth_post_write_execution_journals"
VERIFICATION_SERVICE_METHOD = (
    "record_stealth_post_write_reconciliation_verification"
)
VERIFICATION_READBACK_SERVICE_METHOD = (
    "build_stealth_post_write_reconciliation_verifications"
)

GUARDED_COMMANDS: dict[AdminApiMutationFamilyType, tuple[str, str]] = {
    AdminApiMutationFamilyType.STEALTH_CREATE: (
        "/api/v1/stealth/orders",
        "create_stealth_order",
    ),
    AdminApiMutationFamilyType.STEALTH_REVEAL: (
        "/api/v1/stealth/orders/{stealth_order_id}/reveal",
        "reveal_stealth_order_by_stealth_order_id",
    ),
    AdminApiMutationFamilyType.STEALTH_CANCEL: (
        "/api/v1/stealth/orders/{stealth_order_id}/cancel",
        "cancel_stealth_order_by_stealth_order_id",
    ),
    AdminApiMutationFamilyType.STEALTH_MOVE: (
        "/api/v1/stealth/orders/{stealth_order_id}/move",
        "move_stealth_order_by_stealth_order_id",
    ),
    AdminApiMutationFamilyType.MOVEMENT_REPRICE: (
        "/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice",
        "reprice_stealth_order_by_stealth_order_id",
    ),
    AdminApiMutationFamilyType.STEALTH_RECOVERY: (
        "/api/v1/stealth/orders/{stealth_order_id}/recovery",
        "recover_stealth_order_by_stealth_order_id",
    ),
    AdminApiMutationFamilyType.STEALTH_RECONCILIATION: (
        "/api/v1/stealth/orders/{stealth_order_id}/reconciliation",
        "reconcile_stealth_order_by_stealth_order_id",
    ),
}


class StealthPostWriteReconciliationProofError(ValueError):
    """Raised when stealth post-write reconciliation proof evidence is invalid."""


class StealthPostWriteExecutionJournalError(ValueError):
    """Raised when stealth post-write execution-journal evidence is invalid."""


class StealthPostWriteReconciliationVerificationError(ValueError):
    """Raised when stealth post-write reconciliation verification is invalid."""


class AdminApiStealthPostWriteReconciliationProofService:
    """Service boundary for append-only post-write reconciliation proof evidence."""

    def record_proof(
        self,
        *,
        proof_store: FileStealthPostWriteReconciliationProofStore,
        stealth_order_id: str,
        body: StealthPostWriteReconciliationProofRequest,
        admission_decision: AdminLiveAdmissionDecisionEvidence,
        actor_id: str,
        operator_intent: str,
        idempotency_key: str,
        correlation_id: str,
        payload_hash: str,
        audit_id: str,
        now: datetime | None = None,
    ) -> StealthPostWriteReconciliationProofRecord:
        recorded_at = _normalize_now(now)
        self._validate_route_inventory(
            route=PROOF_ROUTE,
            method=PROOF_METHOD,
            service_method=PROOF_SERVICE_METHOD,
        )
        self._validate_required({
            "guarded_payload_hash": body.guarded_payload_hash,
            "route_bound_reconciliation_plan_ref": (
                body.route_bound_reconciliation_plan_ref
            ),
            "post_write_execution_journal_ref": (
                body.post_write_execution_journal_ref
            ),
            "post_write_completion_proof_ref": body.post_write_completion_proof_ref,
            "reconciliation_plan_id": body.reconciliation_plan_id,
            "approval_snapshot_id": body.approval_snapshot_id,
            "admission_audit_id": body.admission_audit_id,
            "cap_guard_decision_id": body.cap_guard_decision_id,
        })
        self._validate_guarded_command_context(
            stealth_order_id=stealth_order_id,
            body=body,
        )
        self._validate_safe_proof(body)
        self._validate_admission_prerequisites(
            admission_decision=admission_decision,
            stealth_order_id=stealth_order_id,
            route=PROOF_ROUTE,
            method=PROOF_METHOD,
            service_method=PROOF_SERVICE_METHOD,
            approval_snapshot_id=body.approval_snapshot_id,
            admission_audit_id=body.admission_audit_id,
            cap_guard_decision_id=body.cap_guard_decision_id,
            reconciliation_plan_id=body.reconciliation_plan_id,
        )
        proof_id = body.post_write_reconciliation_proof_id or _stable_id(
            "stealth-post-write-reconciliation-proof",
            route=PROOF_ROUTE,
            stealth_order_id=stealth_order_id,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
        )
        if proof_store.find_by_proof_id(proof_id) is not None:
            raise StealthPostWriteReconciliationProofError(
                "Stealth post-write reconciliation proof already exists."
            )

        record = StealthPostWriteReconciliationProofRecord(
            post_write_reconciliation_proof_id=proof_id,
            recorded_at=recorded_at.isoformat(),
            stealth_order_id=stealth_order_id,
            guarded_command_route=body.guarded_command_route,
            guarded_command_method=body.guarded_command_method,
            guarded_service_method=body.guarded_service_method,
            guarded_mutation_family=body.guarded_mutation_family,
            guarded_actor_id=body.guarded_actor_id,
            guarded_operator_intent=body.guarded_operator_intent,
            guarded_idempotency_key=body.guarded_idempotency_key,
            guarded_payload_hash=body.guarded_payload_hash,
            route_bound_reconciliation_plan_ref=(
                body.route_bound_reconciliation_plan_ref
            ),
            post_write_execution_journal_ref=body.post_write_execution_journal_ref,
            post_write_completion_proof_ref=body.post_write_completion_proof_ref,
            evidence_source=body.evidence_source,
            reconciliation_plan_id=body.reconciliation_plan_id,
            approval_snapshot_id=body.approval_snapshot_id,
            admission_audit_id=body.admission_audit_id,
            cap_guard_decision_id=body.cap_guard_decision_id,
            route=PROOF_ROUTE,
            method=PROOF_METHOD,
            service_method=PROOF_SERVICE_METHOD,
            actor_id=actor_id,
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            payload_hash=payload_hash,
            audit_id=audit_id,
            dry_run=body.dry_run,
            operator_reason=body.operator_reason,
            manual_live_acknowledgement=body.manual_live_acknowledgement,
        )
        proof_store.append(record)
        return record

    @staticmethod
    def _validate_required(fields: dict[str, str | None]) -> None:
        missing = [name for name, value in fields.items() if not value]
        if missing:
            raise StealthPostWriteReconciliationProofError(
                "Stealth post-write reconciliation proof is missing required "
                "fields: " + ", ".join(missing)
            )

    @staticmethod
    def _validate_guarded_command_context(
        *,
        stealth_order_id: str,
        body: StealthPostWriteReconciliationProofRequest,
    ) -> None:
        guarded = GUARDED_COMMANDS.get(body.guarded_mutation_family)
        if guarded is None:
            raise StealthPostWriteReconciliationProofError(
                "Stealth post-write reconciliation guarded mutation family is "
                "not supported."
            )
        expected_route, expected_service_method = guarded
        checks = {
            "guarded_command_route": body.guarded_command_route == expected_route,
            "guarded_command_method": body.guarded_command_method == "POST",
            "guarded_service_method": (
                body.guarded_service_method == expected_service_method
            ),
            "stealth_order_id": body.stealth_order_id == stealth_order_id,
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            raise StealthPostWriteReconciliationProofError(
                "Stealth post-write reconciliation guarded command context did "
                "not match: " + ", ".join(failed)
            )

    @staticmethod
    def _validate_safe_proof(
        body: StealthPostWriteReconciliationProofRequest,
    ) -> None:
        if not body.dry_run:
            raise StealthPostWriteReconciliationProofError(
                "Stealth post-write reconciliation proof must be recorded as "
                "dry-run evidence."
            )
        if body.manual_live_acknowledgement:
            raise StealthPostWriteReconciliationProofError(
                "Stealth post-write reconciliation proof cannot include live "
                "acknowledgement."
            )

    @staticmethod
    def _validate_route_inventory(
        *,
        route: str,
        method: str,
        service_method: str,
    ) -> None:
        surface = f"{method} {route}"
        inventory_item = next(
            (item for item in ADMIN_API_ROUTE_INVENTORY if item.surface == surface),
            None,
        )
        if inventory_item is None:
            raise StealthPostWriteReconciliationProofError(
                "Stealth post-write reconciliation proof route is missing from "
                "route inventory."
            )
        if inventory_item.action_class != AdminApiActionClass.LOCAL_STATE_MUTATION:
            raise StealthPostWriteReconciliationProofError(
                "Stealth post-write reconciliation proof route must be a "
                "local-state mutation."
            )
        if inventory_item.permission != AdminApiPermission.RECONCILIATION_RECORD:
            raise StealthPostWriteReconciliationProofError(
                "Stealth post-write reconciliation proof route must require "
                "reconciliation:record."
            )
        if inventory_item.shared_method != service_method:
            raise StealthPostWriteReconciliationProofError(
                "Stealth post-write reconciliation proof service method does "
                "not match route inventory."
            )

    @staticmethod
    def _validate_admission_prerequisites(
        *,
        admission_decision: AdminLiveAdmissionDecisionEvidence,
        stealth_order_id: str,
        route: str,
        method: str,
        service_method: str,
        approval_snapshot_id: str | None,
        admission_audit_id: str | None,
        cap_guard_decision_id: str | None,
        reconciliation_plan_id: str | None,
    ) -> None:
        checks = {
            "route": admission_decision.route == route,
            "method": admission_decision.method == method,
            "module_id": admission_decision.module_id == "stealth_orders",
            "identity_key": admission_decision.identity_key == "stealth_order_id",
            "identity_value": admission_decision.identity_value == stealth_order_id,
            "action_class": (
                admission_decision.action_class
                == AdminApiActionClass.LOCAL_STATE_MUTATION
            ),
            "required_permission": (
                admission_decision.required_permission
                == AdminApiPermission.RECONCILIATION_RECORD
            ),
            "service_method": admission_decision.service_method == service_method,
            "approval_snapshot": (
                admission_decision.approval_snapshot_present
                and admission_decision.approval_snapshot_id == approval_snapshot_id
            ),
            "admission_audit": (
                admission_decision.admission_audit_present
                and admission_decision.admission_audit_id == admission_audit_id
            ),
            "cap_guard": (
                admission_decision.cap_guard_present
                and admission_decision.cap_guard_decision_id == cap_guard_decision_id
            ),
            "reconciliation_plan": (
                admission_decision.reconciliation_plan_present
                and admission_decision.reconciliation_plan_id == reconciliation_plan_id
            ),
            "no_live": admission_decision.live_exchange_submitted is False,
            "not_allowed": admission_decision.allowed is False,
            "live_disabled": admission_decision.status == AdminApiGateStatus.BLOCKED,
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            raise StealthPostWriteReconciliationProofError(
                "Stealth post-write reconciliation proof prerequisites did not "
                "pass: " + ", ".join(failed)
            )


class AdminApiStealthPostWriteExecutionJournalService:
    """Service boundary for append-only post-write journal acceptance evidence."""

    def record_execution_journal(
        self,
        *,
        journal_store: FileStealthPostWriteExecutionJournalStore,
        proof_store: FileStealthPostWriteReconciliationProofStore,
        stealth_order_id: str,
        body: StealthPostWriteExecutionJournalRequest,
        admission_decision: AdminLiveAdmissionDecisionEvidence,
        actor_id: str,
        operator_intent: str,
        idempotency_key: str,
        correlation_id: str,
        payload_hash: str,
        audit_id: str,
        now: datetime | None = None,
    ) -> StealthPostWriteExecutionJournalAcceptanceRecord:
        recorded_at = _normalize_now(now)
        AdminApiStealthPostWriteReconciliationProofService._validate_route_inventory(
            route=JOURNAL_ROUTE,
            method=PROOF_METHOD,
            service_method=JOURNAL_SERVICE_METHOD,
        )
        AdminApiStealthPostWriteReconciliationProofService._validate_required({
            "post_write_reconciliation_proof_id": (
                body.post_write_reconciliation_proof_id
            ),
            "guarded_payload_hash": body.guarded_payload_hash,
            "post_write_execution_journal_ref": (
                body.post_write_execution_journal_ref
            ),
            "reconciliation_plan_id": body.reconciliation_plan_id,
            "approval_snapshot_id": body.approval_snapshot_id,
            "admission_audit_id": body.admission_audit_id,
            "cap_guard_decision_id": body.cap_guard_decision_id,
        })
        AdminApiStealthPostWriteReconciliationProofService._validate_guarded_command_context(
            stealth_order_id=stealth_order_id,
            body=body,
        )
        self._validate_safe_journal(body)
        AdminApiStealthPostWriteReconciliationProofService._validate_admission_prerequisites(
            admission_decision=admission_decision,
            stealth_order_id=stealth_order_id,
            route=JOURNAL_ROUTE,
            method=PROOF_METHOD,
            service_method=JOURNAL_SERVICE_METHOD,
            approval_snapshot_id=body.approval_snapshot_id,
            admission_audit_id=body.admission_audit_id,
            cap_guard_decision_id=body.cap_guard_decision_id,
            reconciliation_plan_id=body.reconciliation_plan_id,
        )

        proof = proof_store.find_by_proof_id(
            body.post_write_reconciliation_proof_id
        )
        if proof is None:
            raise StealthPostWriteExecutionJournalError(
                "Stealth post-write execution journal requires an existing "
                "post-write reconciliation proof."
            )
        if not is_safe_stealth_post_write_reconciliation_proof_record(proof):
            raise StealthPostWriteExecutionJournalError(
                "Stealth post-write execution journal proof reference is not "
                "safe no-live evidence."
            )

        draft_record = StealthPostWriteExecutionJournalAcceptanceRecord(
            execution_journal_acceptance_id=(
                body.execution_journal_acceptance_id
                or _stable_id(
                    "stealth-post-write-execution-journal",
                    route=JOURNAL_ROUTE,
                    stealth_order_id=stealth_order_id,
                    proof_id=body.post_write_reconciliation_proof_id,
                    idempotency_key=idempotency_key,
                    payload_hash=payload_hash,
                )
            ),
            recorded_at=recorded_at.isoformat(),
            post_write_reconciliation_proof_id=(
                body.post_write_reconciliation_proof_id
            ),
            stealth_order_id=stealth_order_id,
            guarded_command_route=body.guarded_command_route,
            guarded_command_method=body.guarded_command_method,
            guarded_service_method=body.guarded_service_method,
            guarded_mutation_family=body.guarded_mutation_family,
            guarded_actor_id=body.guarded_actor_id,
            guarded_operator_intent=body.guarded_operator_intent,
            guarded_idempotency_key=body.guarded_idempotency_key,
            guarded_payload_hash=body.guarded_payload_hash,
            post_write_execution_journal_ref=body.post_write_execution_journal_ref,
            evidence_source=body.evidence_source,
            reconciliation_plan_id=body.reconciliation_plan_id,
            approval_snapshot_id=body.approval_snapshot_id,
            admission_audit_id=body.admission_audit_id,
            cap_guard_decision_id=body.cap_guard_decision_id,
            actor_id=actor_id,
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            payload_hash=payload_hash,
            audit_id=audit_id,
            dry_run=body.dry_run,
            operator_reason=body.operator_reason,
            manual_live_acknowledgement=body.manual_live_acknowledgement,
        )
        if not post_write_execution_journal_matches_proof(draft_record, proof):
            raise StealthPostWriteExecutionJournalError(
                "Stealth post-write execution journal context does not match "
                "the referenced post-write reconciliation proof."
            )
        if (
            journal_store.find_by_acceptance_id(
                draft_record.execution_journal_acceptance_id
            )
            is not None
        ):
            raise StealthPostWriteExecutionJournalError(
                "Stealth post-write execution journal acceptance already exists."
            )

        journal_store.append(draft_record)
        return draft_record

    @staticmethod
    def _validate_safe_journal(
        body: StealthPostWriteExecutionJournalRequest,
    ) -> None:
        if not body.dry_run:
            raise StealthPostWriteExecutionJournalError(
                "Stealth post-write execution journal must be recorded as "
                "dry-run evidence."
            )
        if body.manual_live_acknowledgement:
            raise StealthPostWriteExecutionJournalError(
                "Stealth post-write execution journal cannot include live "
                "acknowledgement."
            )


class AdminApiStealthPostWriteReconciliationVerificationService:
    """Service boundary for append-only post-write verification evidence."""

    def record_verification(
        self,
        *,
        verification_store: FileStealthPostWriteReconciliationVerificationStore,
        journal_store: FileStealthPostWriteExecutionJournalStore,
        proof_store: FileStealthPostWriteReconciliationProofStore,
        stealth_order_id: str,
        body: StealthPostWriteReconciliationVerificationRequest,
        admission_decision: AdminLiveAdmissionDecisionEvidence,
        actor_id: str,
        operator_intent: str,
        idempotency_key: str,
        correlation_id: str,
        payload_hash: str,
        audit_id: str,
        now: datetime | None = None,
    ) -> StealthPostWriteReconciliationVerificationRecord:
        recorded_at = _normalize_now(now)
        AdminApiStealthPostWriteReconciliationProofService._validate_route_inventory(
            route=VERIFICATION_ROUTE,
            method=PROOF_METHOD,
            service_method=VERIFICATION_SERVICE_METHOD,
        )
        AdminApiStealthPostWriteReconciliationProofService._validate_required({
            "post_write_reconciliation_proof_id": (
                body.post_write_reconciliation_proof_id
            ),
            "execution_journal_acceptance_id": (
                body.execution_journal_acceptance_id
            ),
            "guarded_payload_hash": body.guarded_payload_hash,
            "post_write_execution_journal_ref": (
                body.post_write_execution_journal_ref
            ),
            "post_write_completion_proof_ref": (
                body.post_write_completion_proof_ref
            ),
            "reconciliation_verification_ref": (
                body.reconciliation_verification_ref
            ),
            "reconciliation_plan_id": body.reconciliation_plan_id,
            "approval_snapshot_id": body.approval_snapshot_id,
            "admission_audit_id": body.admission_audit_id,
            "cap_guard_decision_id": body.cap_guard_decision_id,
        })
        AdminApiStealthPostWriteReconciliationProofService._validate_guarded_command_context(
            stealth_order_id=stealth_order_id,
            body=body,
        )
        self._validate_safe_verification(body)
        AdminApiStealthPostWriteReconciliationProofService._validate_admission_prerequisites(
            admission_decision=admission_decision,
            stealth_order_id=stealth_order_id,
            route=VERIFICATION_ROUTE,
            method=PROOF_METHOD,
            service_method=VERIFICATION_SERVICE_METHOD,
            approval_snapshot_id=body.approval_snapshot_id,
            admission_audit_id=body.admission_audit_id,
            cap_guard_decision_id=body.cap_guard_decision_id,
            reconciliation_plan_id=body.reconciliation_plan_id,
        )

        proof = proof_store.find_by_proof_id(
            body.post_write_reconciliation_proof_id
        )
        if proof is None:
            raise StealthPostWriteReconciliationVerificationError(
                "Stealth post-write reconciliation verification requires an "
                "existing post-write reconciliation proof."
            )
        if not is_safe_stealth_post_write_reconciliation_proof_record(proof):
            raise StealthPostWriteReconciliationVerificationError(
                "Stealth post-write reconciliation verification proof "
                "reference is not safe no-live evidence."
            )
        journal = journal_store.find_by_acceptance_id(
            body.execution_journal_acceptance_id
        )
        if journal is None:
            raise StealthPostWriteReconciliationVerificationError(
                "Stealth post-write reconciliation verification requires an "
                "existing execution-journal acceptance."
            )
        if not is_safe_stealth_post_write_execution_journal_record(journal):
            raise StealthPostWriteReconciliationVerificationError(
                "Stealth post-write reconciliation verification journal "
                "reference is not safe no-live evidence."
            )
        if not post_write_execution_journal_matches_proof(journal, proof):
            raise StealthPostWriteReconciliationVerificationError(
                "Stealth post-write reconciliation verification journal "
                "context does not match the referenced proof."
            )

        draft_record = StealthPostWriteReconciliationVerificationRecord(
            reconciliation_verification_id=(
                body.reconciliation_verification_id
                or _stable_id(
                    "stealth-post-write-reconciliation-verification",
                    route=VERIFICATION_ROUTE,
                    stealth_order_id=stealth_order_id,
                    proof_id=body.post_write_reconciliation_proof_id,
                    journal_id=body.execution_journal_acceptance_id,
                    idempotency_key=idempotency_key,
                    payload_hash=payload_hash,
                )
            ),
            recorded_at=recorded_at.isoformat(),
            post_write_reconciliation_proof_id=(
                body.post_write_reconciliation_proof_id
            ),
            execution_journal_acceptance_id=(
                body.execution_journal_acceptance_id
            ),
            stealth_order_id=stealth_order_id,
            guarded_command_route=body.guarded_command_route,
            guarded_command_method=body.guarded_command_method,
            guarded_service_method=body.guarded_service_method,
            guarded_mutation_family=body.guarded_mutation_family,
            guarded_actor_id=body.guarded_actor_id,
            guarded_operator_intent=body.guarded_operator_intent,
            guarded_idempotency_key=body.guarded_idempotency_key,
            guarded_payload_hash=body.guarded_payload_hash,
            post_write_execution_journal_ref=body.post_write_execution_journal_ref,
            post_write_completion_proof_ref=body.post_write_completion_proof_ref,
            reconciliation_verification_ref=body.reconciliation_verification_ref,
            evidence_source=body.evidence_source,
            reconciliation_plan_id=body.reconciliation_plan_id,
            approval_snapshot_id=body.approval_snapshot_id,
            admission_audit_id=body.admission_audit_id,
            cap_guard_decision_id=body.cap_guard_decision_id,
            actor_id=actor_id,
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            payload_hash=payload_hash,
            audit_id=audit_id,
            dry_run=body.dry_run,
            operator_reason=body.operator_reason,
            manual_live_acknowledgement=body.manual_live_acknowledgement,
        )
        if not post_write_reconciliation_verification_matches(
            draft_record,
            proof,
            journal,
        ):
            raise StealthPostWriteReconciliationVerificationError(
                "Stealth post-write reconciliation verification context does "
                "not match the referenced proof and journal."
            )
        if (
            verification_store.find_by_verification_id(
                draft_record.reconciliation_verification_id
            )
            is not None
        ):
            raise StealthPostWriteReconciliationVerificationError(
                "Stealth post-write reconciliation verification already exists."
            )

        verification_store.append(draft_record)
        return draft_record

    @staticmethod
    def _validate_safe_verification(
        body: StealthPostWriteReconciliationVerificationRequest,
    ) -> None:
        if not body.dry_run:
            raise StealthPostWriteReconciliationVerificationError(
                "Stealth post-write reconciliation verification must be "
                "recorded as dry-run evidence."
            )
        if body.manual_live_acknowledgement:
            raise StealthPostWriteReconciliationVerificationError(
                "Stealth post-write reconciliation verification cannot "
                "include live acknowledgement."
            )


def _stable_id(
    prefix: str,
    **parts: str,
) -> str:
    material = "|".join(f"{key}={value}" for key, value in sorted(parts.items()))
    return f"{prefix}-{uuid.uuid5(uuid.NAMESPACE_URL, material)}"


def _normalize_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)
