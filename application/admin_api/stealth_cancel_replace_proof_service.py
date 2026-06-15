"""Backend-owned stealth cancel/replace proof service."""

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
    StealthCancelReplaceProofRequest,
)
from .route_inventory import ADMIN_API_ROUTE_INVENTORY
from .stealth_cancel_replace_proof import (
    FileStealthCancelReplaceProofStore,
    StealthCancelReplaceProofRecord,
)


PROOF_ROUTE = "/api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proofs"
READBACK_ROUTE = "/api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proof"
PROOF_METHOD = "POST"
PROOF_SERVICE_METHOD = "record_stealth_cancel_replace_proof"

GUARDED_CANCEL_ROUTE = "/api/v1/stealth/orders/{stealth_order_id}/cancel"
GUARDED_CANCEL_SERVICE_METHOD = "cancel_stealth_order_by_stealth_order_id"
GUARDED_MOVE_ROUTE = "/api/v1/stealth/orders/{stealth_order_id}/move"
GUARDED_MOVE_SERVICE_METHOD = "move_stealth_order_by_stealth_order_id"
GUARDED_REPRICE_ROUTE = "/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice"
GUARDED_REPRICE_SERVICE_METHOD = "reprice_stealth_order_by_stealth_order_id"

GUARDED_COMMANDS: dict[
    AdminApiMutationFamilyType,
    tuple[str, str, bool],
] = {
    AdminApiMutationFamilyType.STEALTH_CANCEL: (
        GUARDED_CANCEL_ROUTE,
        GUARDED_CANCEL_SERVICE_METHOD,
        False,
    ),
    AdminApiMutationFamilyType.STEALTH_MOVE: (
        GUARDED_MOVE_ROUTE,
        GUARDED_MOVE_SERVICE_METHOD,
        True,
    ),
    AdminApiMutationFamilyType.MOVEMENT_REPRICE: (
        GUARDED_REPRICE_ROUTE,
        GUARDED_REPRICE_SERVICE_METHOD,
        True,
    ),
}


class StealthCancelReplaceProofError(ValueError):
    """Raised when stealth cancel/replace proof evidence is invalid."""


class AdminApiStealthCancelReplaceProofService:
    """Service boundary for append-only stealth cancel/replace proof evidence."""

    def record_proof(
        self,
        *,
        proof_store: FileStealthCancelReplaceProofStore,
        stealth_order_id: str,
        body: StealthCancelReplaceProofRequest,
        admission_decision: AdminLiveAdmissionDecisionEvidence,
        actor_id: str,
        operator_intent: str,
        idempotency_key: str,
        correlation_id: str,
        payload_hash: str,
        audit_id: str,
        now: datetime | None = None,
    ) -> StealthCancelReplaceProofRecord:
        recorded_at = _normalize_now(now)
        self._validate_route_inventory(
            route=PROOF_ROUTE,
            method=PROOF_METHOD,
            service_method=PROOF_SERVICE_METHOD,
        )
        self._validate_required({
            "guarded_payload_hash": body.guarded_payload_hash,
            "active_placement_evidence_ref": body.active_placement_evidence_ref,
            "cancel_replace_evidence_ref": body.cancel_replace_evidence_ref,
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
        proof_id = body.cancel_replace_proof_id or _stable_id(
            "stealth-cancel-replace-proof",
            route=PROOF_ROUTE,
            stealth_order_id=stealth_order_id,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
        )
        if proof_store.find_by_proof_id(proof_id) is not None:
            raise StealthCancelReplaceProofError(
                "Stealth cancel/replace proof already exists."
            )

        record = StealthCancelReplaceProofRecord(
            cancel_replace_proof_id=proof_id,
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
            active_placement_evidence_ref=body.active_placement_evidence_ref,
            mutation_claim_evidence_ref=body.mutation_claim_evidence_ref,
            cancel_replace_evidence_ref=body.cancel_replace_evidence_ref,
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
            raise StealthCancelReplaceProofError(
                "Stealth cancel/replace proof is missing required fields: "
                + ", ".join(missing)
            )

    @staticmethod
    def _validate_guarded_command_context(
        *,
        stealth_order_id: str,
        body: StealthCancelReplaceProofRequest,
    ) -> None:
        guarded = GUARDED_COMMANDS.get(body.guarded_mutation_family)
        if guarded is None:
            raise StealthCancelReplaceProofError(
                "Stealth cancel/replace proof guarded mutation family is not supported."
            )
        expected_route, expected_service_method, requires_claim = guarded
        checks = {
            "guarded_command_route": body.guarded_command_route == expected_route,
            "guarded_command_method": body.guarded_command_method == "POST",
            "guarded_service_method": (
                body.guarded_service_method == expected_service_method
            ),
            "stealth_order_id": body.stealth_order_id == stealth_order_id,
        }
        if requires_claim and not body.mutation_claim_evidence_ref:
            checks["mutation_claim_evidence_ref"] = False
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            raise StealthCancelReplaceProofError(
                "Stealth cancel/replace guarded command context did not match: "
                + ", ".join(failed)
            )

    @staticmethod
    def _validate_safe_proof(body: StealthCancelReplaceProofRequest) -> None:
        if not body.dry_run:
            raise StealthCancelReplaceProofError(
                "Stealth cancel/replace proof must be recorded as dry-run evidence."
            )
        if body.manual_live_acknowledgement:
            raise StealthCancelReplaceProofError(
                "Stealth cancel/replace proof cannot include live acknowledgement."
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
            raise StealthCancelReplaceProofError(
                "Stealth cancel/replace proof route is missing from route inventory."
            )
        if inventory_item.action_class != AdminApiActionClass.LOCAL_STATE_MUTATION:
            raise StealthCancelReplaceProofError(
                "Stealth cancel/replace proof route must be a local-state mutation."
            )
        if inventory_item.permission != AdminApiPermission.STEALTH_CANCEL_REPLACE_RECORD:
            raise StealthCancelReplaceProofError(
                "Stealth cancel/replace proof route must require "
                "stealth_cancel_replace:record."
            )
        if inventory_item.shared_method != service_method:
            raise StealthCancelReplaceProofError(
                "Stealth cancel/replace proof service method does not match route inventory."
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
                == AdminApiPermission.STEALTH_CANCEL_REPLACE_RECORD
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
            raise StealthCancelReplaceProofError(
                "Stealth cancel/replace proof prerequisites did not pass: "
                + ", ".join(failed)
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
