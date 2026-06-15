"""Backend-owned stealth mutation-claim snapshot proof service."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from core.enums import (
    AdminApiActionClass,
    AdminApiGateStatus,
    AdminApiPermission,
    StealthMutationKind,
)

from .models import (
    AdminLiveAdmissionDecisionEvidence,
    StealthMutationClaimSnapshotProofRequest,
)
from .route_inventory import ADMIN_API_ROUTE_INVENTORY
from .stealth_mutation_claim import (
    FileStealthMutationClaimProofStore,
    StealthMutationClaimSnapshotProofRecord,
)


PROOF_ROUTE = "/api/v1/stealth/orders/{stealth_order_id}/mutation-claim-proofs"
READBACK_ROUTE = "/api/v1/stealth/orders/{stealth_order_id}/mutation-claim-proof"
PROOF_METHOD = "POST"
PROOF_SERVICE_METHOD = "record_stealth_mutation_claim_snapshot_proof"

GUARDED_COMMANDS: dict[tuple[str, str], StealthMutationKind] = {
    (
        "/api/v1/stealth/orders/{stealth_order_id}/move",
        "move_stealth_order_by_stealth_order_id",
    ): StealthMutationKind.MOVE,
    (
        "/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice",
        "reprice_stealth_order_by_stealth_order_id",
    ): StealthMutationKind.REPRICE,
}


class StealthMutationClaimProofError(ValueError):
    """Raised when stealth mutation-claim proof evidence is invalid."""


class AdminApiStealthMutationClaimProofService:
    """Service boundary for append-only stealth mutation-claim proof evidence."""

    def record_proof(
        self,
        *,
        proof_store: FileStealthMutationClaimProofStore,
        stealth_order_id: str,
        body: StealthMutationClaimSnapshotProofRequest,
        admission_decision: AdminLiveAdmissionDecisionEvidence,
        actor_id: str,
        operator_intent: str,
        idempotency_key: str,
        correlation_id: str,
        payload_hash: str,
        audit_id: str,
        now: datetime | None = None,
    ) -> StealthMutationClaimSnapshotProofRecord:
        recorded_at = _normalize_now(now)
        self._validate_route_inventory(
            route=PROOF_ROUTE,
            method=PROOF_METHOD,
            service_method=PROOF_SERVICE_METHOD,
        )
        self._validate_required({
            "guarded_payload_hash": body.guarded_payload_hash,
            "claim_reader_source": body.claim_reader_source,
            "snapshot_evidence_ref": body.snapshot_evidence_ref,
            "reconciliation_plan_id": body.reconciliation_plan_id,
            "approval_snapshot_id": body.approval_snapshot_id,
            "admission_audit_id": body.admission_audit_id,
            "cap_guard_decision_id": body.cap_guard_decision_id,
        })
        self._validate_guarded_command_context(
            stealth_order_id=stealth_order_id,
            body=body,
        )
        self._validate_safe_snapshot(body)
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
        proof_id = body.mutation_claim_proof_id or _stable_id(
            "stealth-mutation-claim-proof",
            route=PROOF_ROUTE,
            stealth_order_id=stealth_order_id,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
        )
        if proof_store.find_by_proof_id(proof_id) is not None:
            raise StealthMutationClaimProofError(
                "Stealth mutation-claim snapshot proof already exists."
            )

        record = StealthMutationClaimSnapshotProofRecord(
            mutation_claim_proof_id=proof_id,
            recorded_at=recorded_at.isoformat(),
            stealth_order_id=stealth_order_id,
            guarded_command_route=body.guarded_command_route,
            guarded_command_method=body.guarded_command_method,
            guarded_service_method=body.guarded_service_method,
            guarded_actor_id=body.guarded_actor_id,
            guarded_operator_intent=body.guarded_operator_intent,
            guarded_idempotency_key=body.guarded_idempotency_key,
            guarded_payload_hash=body.guarded_payload_hash,
            mutation_kind=body.mutation_kind,
            claim_reader_source=body.claim_reader_source,
            runtime_claims_observed=body.runtime_claims_observed,
            runtime_claim_count=body.runtime_claim_count,
            active_claim_count=body.active_claim_count,
            evidence_source=body.evidence_source,
            snapshot_evidence_ref=body.snapshot_evidence_ref,
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
            raise StealthMutationClaimProofError(
                "Stealth mutation-claim snapshot proof is missing required fields: "
                + ", ".join(missing)
            )

    @staticmethod
    def _validate_guarded_command_context(
        *,
        stealth_order_id: str,
        body: StealthMutationClaimSnapshotProofRequest,
    ) -> None:
        expected_kind = GUARDED_COMMANDS.get(
            (body.guarded_command_route, body.guarded_service_method)
        )
        checks = {
            "guarded_command_method": body.guarded_command_method == "POST",
            "guarded_command": expected_kind is not None,
            "mutation_kind": (
                expected_kind is not None and body.mutation_kind == expected_kind
            ),
            "stealth_order_id": body.stealth_order_id == stealth_order_id,
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            raise StealthMutationClaimProofError(
                "Stealth mutation-claim guarded command context did not match: "
                + ", ".join(failed)
            )

    @staticmethod
    def _validate_safe_snapshot(
        body: StealthMutationClaimSnapshotProofRequest,
    ) -> None:
        if not body.runtime_claims_observed:
            raise StealthMutationClaimProofError(
                "Stealth mutation-claim proof requires observed runtime claims."
            )
        if body.active_claim_count != 0:
            raise StealthMutationClaimProofError(
                "Stealth mutation-claim proof requires zero active claims."
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
            raise StealthMutationClaimProofError(
                "Stealth mutation-claim proof route is missing from route inventory."
            )
        if inventory_item.action_class != AdminApiActionClass.LOCAL_STATE_MUTATION:
            raise StealthMutationClaimProofError(
                "Stealth mutation-claim proof route must be a local-state mutation."
            )
        if (
            inventory_item.permission
            != AdminApiPermission.STEALTH_MUTATION_CLAIM_RECORD
        ):
            raise StealthMutationClaimProofError(
                "Stealth mutation-claim proof route must require "
                "stealth_mutation_claim:record."
            )
        if inventory_item.shared_method != service_method:
            raise StealthMutationClaimProofError(
                "Stealth mutation-claim proof service method does not match route inventory."
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
                == AdminApiPermission.STEALTH_MUTATION_CLAIM_RECORD
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
            raise StealthMutationClaimProofError(
                "Stealth mutation-claim proof prerequisites did not pass: "
                + ", ".join(failed)
            )


def _stable_id(
    prefix: str,
    *,
    route: str,
    stealth_order_id: str,
    idempotency_key: str,
    payload_hash: str,
) -> str:
    material = "|".join([prefix, route, stealth_order_id, idempotency_key, payload_hash])
    return str(uuid.uuid5(uuid.NAMESPACE_URL, material))


def _normalize_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)
