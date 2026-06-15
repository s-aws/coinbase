"""Backend-owned stealth active-placement exchange-truth record service."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from core.enums import (
    AdminApiActionClass,
    AdminApiGateStatus,
    AdminApiPermission,
)

from .models import (
    AdminLiveAdmissionDecisionEvidence,
    StealthActivePlacementExchangeTruthProofRequest,
    StealthActivePlacementExchangeTruthSnapshotRequest,
)
from .route_inventory import ADMIN_API_ROUTE_INVENTORY
from .stealth_exchange_truth import (
    FileStealthExchangeTruthProofStore,
    FileStealthExchangeTruthSnapshotStore,
    StealthActivePlacementExchangeTruthProofRecord,
    StealthActivePlacementExchangeTruthSnapshotRecord,
)


SNAPSHOT_ROUTE = (
    "/api/v1/stealth/orders/{stealth_order_id}/active-placement/"
    "exchange-truth-snapshots"
)
PROOF_ROUTE = (
    "/api/v1/stealth/orders/{stealth_order_id}/active-placement/"
    "exchange-truth-proofs"
)
READBACK_ROUTE = (
    "/api/v1/stealth/orders/{stealth_order_id}/active-placement/"
    "exchange-truth-proof"
)
SNAPSHOT_METHOD = "POST"
PROOF_METHOD = "POST"
SNAPSHOT_SERVICE_METHOD = "record_stealth_active_placement_exchange_truth_snapshot"
PROOF_SERVICE_METHOD = "record_stealth_active_placement_exchange_truth_proof"


class StealthExchangeTruthError(ValueError):
    """Raised when stealth active-placement exchange-truth evidence is invalid."""


class AdminApiStealthExchangeTruthService:
    """Service boundary for append-only stealth active-placement evidence."""

    def record_snapshot(
        self,
        *,
        snapshot_store: FileStealthExchangeTruthSnapshotStore,
        stealth_order_id: str,
        body: StealthActivePlacementExchangeTruthSnapshotRequest,
        admission_decision: AdminLiveAdmissionDecisionEvidence,
        actor_id: str,
        operator_intent: str,
        idempotency_key: str,
        correlation_id: str,
        payload_hash: str,
        audit_id: str,
        now: datetime | None = None,
    ) -> StealthActivePlacementExchangeTruthSnapshotRecord:
        recorded_at = _normalize_now(now)
        self._validate_route_inventory(
            route=SNAPSHOT_ROUTE,
            method=SNAPSHOT_METHOD,
            service_method=SNAPSHOT_SERVICE_METHOD,
        )
        self._validate_required({
            "source_timestamp": body.source_timestamp,
            "snapshot_evidence_ref": body.snapshot_evidence_ref,
            "reconciliation_plan_id": body.reconciliation_plan_id,
            "approval_snapshot_id": body.approval_snapshot_id,
            "admission_audit_id": body.admission_audit_id,
            "cap_guard_decision_id": body.cap_guard_decision_id,
        })
        self._validate_admission_prerequisites(
            admission_decision=admission_decision,
            stealth_order_id=stealth_order_id,
            route=SNAPSHOT_ROUTE,
            method=SNAPSHOT_METHOD,
            service_method=SNAPSHOT_SERVICE_METHOD,
            approval_snapshot_id=body.approval_snapshot_id,
            admission_audit_id=body.admission_audit_id,
            cap_guard_decision_id=body.cap_guard_decision_id,
            reconciliation_plan_id=body.reconciliation_plan_id,
        )
        snapshot_id = body.exchange_truth_snapshot_id or _stable_id(
            "stealth-exchange-truth-snapshot",
            route=SNAPSHOT_ROUTE,
            stealth_order_id=stealth_order_id,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
        )
        if snapshot_store.find_by_snapshot_id(snapshot_id) is not None:
            raise StealthExchangeTruthError(
                "Stealth active-placement exchange-truth snapshot already exists."
            )

        record = StealthActivePlacementExchangeTruthSnapshotRecord(
            exchange_truth_snapshot_id=snapshot_id,
            recorded_at=recorded_at.isoformat(),
            stealth_order_id=stealth_order_id,
            active_placement_client_order_id=body.active_placement_client_order_id,
            active_exchange_order_id=body.active_exchange_order_id,
            product_id=body.product_id,
            source_timestamp=body.source_timestamp,
            evidence_source=body.evidence_source,
            snapshot_evidence_ref=body.snapshot_evidence_ref,
            reconciliation_plan_id=body.reconciliation_plan_id,
            approval_snapshot_id=body.approval_snapshot_id,
            admission_audit_id=body.admission_audit_id,
            cap_guard_decision_id=body.cap_guard_decision_id,
            route=SNAPSHOT_ROUTE,
            method=SNAPSHOT_METHOD,
            service_method=SNAPSHOT_SERVICE_METHOD,
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
        snapshot_store.append(record)
        return record

    def record_proof(
        self,
        *,
        snapshot_store: FileStealthExchangeTruthSnapshotStore,
        proof_store: FileStealthExchangeTruthProofStore,
        stealth_order_id: str,
        body: StealthActivePlacementExchangeTruthProofRequest,
        admission_decision: AdminLiveAdmissionDecisionEvidence,
        actor_id: str,
        operator_intent: str,
        idempotency_key: str,
        correlation_id: str,
        payload_hash: str,
        audit_id: str,
        now: datetime | None = None,
    ) -> StealthActivePlacementExchangeTruthProofRecord:
        recorded_at = _normalize_now(now)
        self._validate_route_inventory(
            route=PROOF_ROUTE,
            method=PROOF_METHOD,
            service_method=PROOF_SERVICE_METHOD,
        )
        self._validate_required({
            "exchange_truth_snapshot_id": body.exchange_truth_snapshot_id,
            "exchange_truth_evidence_ref": body.exchange_truth_evidence_ref,
            "reconciliation_plan_id": body.reconciliation_plan_id,
            "approval_snapshot_id": body.approval_snapshot_id,
            "admission_audit_id": body.admission_audit_id,
            "cap_guard_decision_id": body.cap_guard_decision_id,
        })
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
        snapshot = snapshot_store.find_by_snapshot_id(body.exchange_truth_snapshot_id)
        if snapshot is None:
            raise StealthExchangeTruthError(
                "Referenced stealth active-placement exchange-truth snapshot was not found."
            )
        if snapshot.stealth_order_id != stealth_order_id:
            raise StealthExchangeTruthError(
                "Referenced exchange-truth snapshot stealth_order_id does not match."
            )
        proof_id = body.exchange_truth_proof_id or _stable_id(
            "stealth-exchange-truth-proof",
            route=PROOF_ROUTE,
            stealth_order_id=stealth_order_id,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
        )
        if proof_store.find_by_proof_id(proof_id) is not None:
            raise StealthExchangeTruthError(
                "Stealth active-placement exchange-truth proof already exists."
            )

        record = StealthActivePlacementExchangeTruthProofRecord(
            exchange_truth_proof_id=proof_id,
            recorded_at=recorded_at.isoformat(),
            stealth_order_id=stealth_order_id,
            exchange_truth_snapshot_id=body.exchange_truth_snapshot_id,
            active_placement_client_order_id=body.active_placement_client_order_id,
            active_exchange_order_id=body.active_exchange_order_id,
            exchange_truth_evidence_ref=body.exchange_truth_evidence_ref,
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
            raise StealthExchangeTruthError(
                "Stealth active-placement exchange-truth evidence is missing "
                "required fields: " + ", ".join(missing)
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
            raise StealthExchangeTruthError(
                "Stealth exchange-truth route is missing from route inventory."
            )
        if inventory_item.action_class != AdminApiActionClass.LOCAL_STATE_MUTATION:
            raise StealthExchangeTruthError(
                "Stealth exchange-truth route must be a local-state mutation."
            )
        if inventory_item.permission != AdminApiPermission.STEALTH_EXCHANGE_TRUTH_RECORD:
            raise StealthExchangeTruthError(
                "Stealth exchange-truth route must require stealth_exchange_truth:record."
            )
        if inventory_item.shared_method != service_method:
            raise StealthExchangeTruthError(
                "Stealth exchange-truth service method does not match route inventory."
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
                == AdminApiPermission.STEALTH_EXCHANGE_TRUTH_RECORD
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
            raise StealthExchangeTruthError(
                "Stealth active-placement exchange-truth prerequisites did not pass: "
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
    material = "|".join(
        [prefix, route, stealth_order_id, idempotency_key, payload_hash]
    )
    return f"{prefix}:{uuid.uuid5(uuid.NAMESPACE_URL, material)}"


def _normalize_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)
