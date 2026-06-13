"""Backend-owned Spot recovery proof record service."""

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
    SpotRecoveryExchangeStateProofRequest,
    SpotRecoveryReconciliationProofRecordRequest,
)
from .route_inventory import ADMIN_API_ROUTE_INVENTORY
from .spot_recovery_proof import FileSpotRecoveryProofStore, SpotRecoveryProofRecord


EXCHANGE_STATE_PROOF_ROUTE = "/api/v1/spot/recovery/exchange-state-proofs"
RECONCILIATION_PROOF_ROUTE = "/api/v1/spot/recovery/reconciliation-proofs"
EXCHANGE_STATE_PROOF_METHOD = "POST"
RECONCILIATION_PROOF_METHOD = "POST"
EXCHANGE_STATE_PROOF_SERVICE_METHOD = "record_spot_recovery_exchange_state_proof"
RECONCILIATION_PROOF_SERVICE_METHOD = "record_spot_recovery_reconciliation_proof"


class SpotRecoveryProofError(ValueError):
    """Raised when a Spot recovery proof record is invalid."""


class AdminApiSpotRecoveryProofService:
    """Service boundary for append-only Spot recovery proof records."""

    def record_exchange_state_proof(
        self,
        *,
        store: FileSpotRecoveryProofStore,
        body: SpotRecoveryExchangeStateProofRequest,
        admission_decision: AdminLiveAdmissionDecisionEvidence,
        actor_id: str,
        operator_intent: str,
        idempotency_key: str,
        correlation_id: str,
        payload_hash: str,
        audit_id: str,
        now: datetime | None = None,
    ) -> SpotRecoveryProofRecord:
        recorded_at = _normalize_now(now)
        self._validate_route_inventory(
            route=EXCHANGE_STATE_PROOF_ROUTE,
            method=EXCHANGE_STATE_PROOF_METHOD,
            service_method=EXCHANGE_STATE_PROOF_SERVICE_METHOD,
        )
        self._validate_required(
            {
                "exchange_state_evidence_ref": body.exchange_state_evidence_ref,
                "reconciliation_plan_id": body.reconciliation_plan_id,
                "approval_snapshot_id": body.approval_snapshot_id,
                "admission_audit_id": body.admission_audit_id,
                "cap_guard_decision_id": body.cap_guard_decision_id,
            }
        )
        self._validate_admission_prerequisites(
            admission_decision=admission_decision,
            body_client_order_id=body.client_order_id,
            route=EXCHANGE_STATE_PROOF_ROUTE,
            method=EXCHANGE_STATE_PROOF_METHOD,
            service_method=EXCHANGE_STATE_PROOF_SERVICE_METHOD,
            approval_snapshot_id=body.approval_snapshot_id,
            admission_audit_id=body.admission_audit_id,
            cap_guard_decision_id=body.cap_guard_decision_id,
            reconciliation_plan_id=body.reconciliation_plan_id,
        )
        exchange_state_proof_id = body.exchange_state_proof_id or _stable_id(
            "exchange-state-proof",
            route=EXCHANGE_STATE_PROOF_ROUTE,
            client_order_id=body.client_order_id,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
        )
        proof_id = exchange_state_proof_id
        if store.find_by_proof_id(proof_id) is not None:
            raise SpotRecoveryProofError("Spot recovery proof already exists.")

        record = SpotRecoveryProofRecord(
            proof_id=proof_id,
            recorded_at=recorded_at.isoformat(),
            mutation_family=AdminApiMutationFamilyType.SPOT_RECOVERY_EXCHANGE_STATE_PROOF,
            client_order_id=body.client_order_id,
            exchange_state_proof_id=exchange_state_proof_id,
            exchange_state_evidence_ref=body.exchange_state_evidence_ref,
            reconciliation_plan_id=str(body.reconciliation_plan_id),
            approval_snapshot_id=str(body.approval_snapshot_id),
            admission_audit_id=str(body.admission_audit_id),
            cap_guard_decision_id=str(body.cap_guard_decision_id),
            route=EXCHANGE_STATE_PROOF_ROUTE,
            method=EXCHANGE_STATE_PROOF_METHOD,
            service_method=EXCHANGE_STATE_PROOF_SERVICE_METHOD,
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
        store.append(record)
        return record

    def record_reconciliation_proof(
        self,
        *,
        store: FileSpotRecoveryProofStore,
        body: SpotRecoveryReconciliationProofRecordRequest,
        admission_decision: AdminLiveAdmissionDecisionEvidence,
        actor_id: str,
        operator_intent: str,
        idempotency_key: str,
        correlation_id: str,
        payload_hash: str,
        audit_id: str,
        now: datetime | None = None,
    ) -> SpotRecoveryProofRecord:
        recorded_at = _normalize_now(now)
        self._validate_route_inventory(
            route=RECONCILIATION_PROOF_ROUTE,
            method=RECONCILIATION_PROOF_METHOD,
            service_method=RECONCILIATION_PROOF_SERVICE_METHOD,
        )
        self._validate_required(
            {
                "exchange_state_proof_id": body.exchange_state_proof_id,
                "recovery_apply_audit_id": body.recovery_apply_audit_id,
                "reconciliation_plan_id": body.reconciliation_plan_id,
                "approval_snapshot_id": body.approval_snapshot_id,
                "admission_audit_id": body.admission_audit_id,
                "cap_guard_decision_id": body.cap_guard_decision_id,
            }
        )
        self._validate_admission_prerequisites(
            admission_decision=admission_decision,
            body_client_order_id=body.client_order_id,
            route=RECONCILIATION_PROOF_ROUTE,
            method=RECONCILIATION_PROOF_METHOD,
            service_method=RECONCILIATION_PROOF_SERVICE_METHOD,
            approval_snapshot_id=body.approval_snapshot_id,
            admission_audit_id=body.admission_audit_id,
            cap_guard_decision_id=body.cap_guard_decision_id,
            reconciliation_plan_id=body.reconciliation_plan_id,
        )
        exchange_state_record = store.find_by_exchange_state_proof_id(
            str(body.exchange_state_proof_id)
        )
        if exchange_state_record is None:
            raise SpotRecoveryProofError(
                "Referenced exchange-state proof was not found."
            )
        if exchange_state_record.client_order_id != body.client_order_id:
            raise SpotRecoveryProofError(
                "Referenced exchange-state proof client_order_id does not match."
            )
        reconciliation_proof_id = body.reconciliation_proof_id or _stable_id(
            "reconciliation-proof",
            route=RECONCILIATION_PROOF_ROUTE,
            client_order_id=body.client_order_id,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
        )
        proof_id = reconciliation_proof_id
        if store.find_by_proof_id(proof_id) is not None:
            raise SpotRecoveryProofError("Spot recovery proof already exists.")

        record = SpotRecoveryProofRecord(
            proof_id=proof_id,
            recorded_at=recorded_at.isoformat(),
            mutation_family=AdminApiMutationFamilyType.SPOT_RECOVERY_RECONCILIATION_PROOF,
            client_order_id=body.client_order_id,
            exchange_state_proof_id=body.exchange_state_proof_id,
            reconciliation_proof_id=reconciliation_proof_id,
            recovery_apply_audit_id=body.recovery_apply_audit_id,
            reconciliation_plan_id=str(body.reconciliation_plan_id),
            approval_snapshot_id=str(body.approval_snapshot_id),
            admission_audit_id=str(body.admission_audit_id),
            cap_guard_decision_id=str(body.cap_guard_decision_id),
            route=RECONCILIATION_PROOF_ROUTE,
            method=RECONCILIATION_PROOF_METHOD,
            service_method=RECONCILIATION_PROOF_SERVICE_METHOD,
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
        store.append(record)
        return record

    @staticmethod
    def _validate_required(fields: dict[str, str | None]) -> None:
        missing = [name for name, value in fields.items() if not value]
        if missing:
            raise SpotRecoveryProofError(
                "Spot recovery proof is missing required fields: "
                + ", ".join(missing)
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
            raise SpotRecoveryProofError(
                "Spot recovery proof route is missing from route inventory."
            )
        if inventory_item.action_class != AdminApiActionClass.LOCAL_STATE_MUTATION:
            raise SpotRecoveryProofError(
                "Spot recovery proof route must be a local-state mutation."
            )
        if inventory_item.permission != AdminApiPermission.SPOT_RECOVERY_RECORD:
            raise SpotRecoveryProofError(
                "Spot recovery proof route must require spot_recovery:record."
            )
        if inventory_item.shared_method != service_method:
            raise SpotRecoveryProofError(
                "Spot recovery proof service method does not match route inventory."
            )

    @staticmethod
    def _validate_admission_prerequisites(
        *,
        admission_decision: AdminLiveAdmissionDecisionEvidence,
        body_client_order_id: str,
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
            "module_id": admission_decision.module_id == "spot_operations",
            "identity_key": admission_decision.identity_key == "client_order_id",
            "identity_value": admission_decision.identity_value == body_client_order_id,
            "action_class": (
                admission_decision.action_class
                == AdminApiActionClass.LOCAL_STATE_MUTATION
            ),
            "required_permission": (
                admission_decision.required_permission
                == AdminApiPermission.SPOT_RECOVERY_RECORD
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
                and admission_decision.reconciliation_plan_id
                == reconciliation_plan_id
            ),
            "no_live": admission_decision.live_exchange_submitted is False,
            "not_allowed": admission_decision.allowed is False,
            "live_disabled": admission_decision.status == AdminApiGateStatus.BLOCKED,
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            raise SpotRecoveryProofError(
                "Spot recovery proof prerequisites did not pass: "
                + ", ".join(failed)
            )


def _stable_id(
    prefix: str,
    *,
    route: str,
    client_order_id: str,
    idempotency_key: str,
    payload_hash: str,
) -> str:
    material = "|".join([prefix, route, client_order_id, idempotency_key, payload_hash])
    return f"{prefix}:{uuid.uuid5(uuid.NAMESPACE_URL, material)}"


def _normalize_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)
