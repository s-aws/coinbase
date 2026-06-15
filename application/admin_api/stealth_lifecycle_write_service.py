"""Backend-owned stealth create lifecycle-write guard proof service."""

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
    StealthCreateLifecycleWriteGuardProofRequest,
)
from .route_inventory import ADMIN_API_ROUTE_INVENTORY
from .stealth_lifecycle_write import (
    FileStealthLifecycleWriteGuardProofStore,
    StealthCreateLifecycleWriteGuardProofRecord,
)


PROOF_ROUTE = (
    "/api/v1/stealth/orders/{stealth_order_id}/"
    "lifecycle-write-guard-proofs"
)
READBACK_ROUTE = (
    "/api/v1/stealth/orders/{stealth_order_id}/"
    "lifecycle-write-guard-proof"
)
PROOF_METHOD = "POST"
PROOF_SERVICE_METHOD = "record_stealth_create_lifecycle_write_guard_proof"


class StealthLifecycleWriteGuardError(ValueError):
    """Raised when stealth lifecycle-write guard evidence is invalid."""


class AdminApiStealthLifecycleWriteGuardService:
    """Service boundary for append-only stealth lifecycle-write guard evidence."""

    def record_proof(
        self,
        *,
        proof_store: FileStealthLifecycleWriteGuardProofStore,
        stealth_order_id: str,
        body: StealthCreateLifecycleWriteGuardProofRequest,
        admission_decision: AdminLiveAdmissionDecisionEvidence,
        actor_id: str,
        operator_intent: str,
        idempotency_key: str,
        correlation_id: str,
        payload_hash: str,
        audit_id: str,
        now: datetime | None = None,
    ) -> StealthCreateLifecycleWriteGuardProofRecord:
        recorded_at = _normalize_now(now)
        self._validate_route_inventory(
            route=PROOF_ROUTE,
            method=PROOF_METHOD,
            service_method=PROOF_SERVICE_METHOD,
        )
        self._validate_required({
            "guarded_payload_hash": body.guarded_payload_hash,
            "product_id": body.product_id,
            "total_size": body.total_size,
            "limit_price": body.limit_price,
            "guard_evidence_ref": body.guard_evidence_ref,
            "reconciliation_plan_id": body.reconciliation_plan_id,
            "approval_snapshot_id": body.approval_snapshot_id,
            "admission_audit_id": body.admission_audit_id,
            "cap_guard_decision_id": body.cap_guard_decision_id,
        })
        self._validate_guarded_command_context(
            stealth_order_id=stealth_order_id,
            body=body,
        )
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
        proof_id = body.lifecycle_write_guard_proof_id or _stable_id(
            "stealth-lifecycle-write-guard-proof",
            route=PROOF_ROUTE,
            stealth_order_id=stealth_order_id,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
        )
        if proof_store.find_by_proof_id(proof_id) is not None:
            raise StealthLifecycleWriteGuardError(
                "Stealth lifecycle-write guard proof already exists."
            )

        record = StealthCreateLifecycleWriteGuardProofRecord(
            lifecycle_write_guard_proof_id=proof_id,
            recorded_at=recorded_at.isoformat(),
            stealth_order_id=stealth_order_id,
            guarded_actor_id=body.guarded_actor_id,
            guarded_operator_intent=body.guarded_operator_intent,
            guarded_idempotency_key=body.guarded_idempotency_key,
            guarded_payload_hash=body.guarded_payload_hash,
            product_id=body.product_id,
            side=body.side,
            total_size=body.total_size,
            limit_price=body.limit_price,
            evidence_source=body.evidence_source,
            guard_evidence_ref=body.guard_evidence_ref,
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
            raise StealthLifecycleWriteGuardError(
                "Stealth lifecycle-write guard proof is missing required fields: "
                + ", ".join(missing)
            )

    @staticmethod
    def _validate_guarded_command_context(
        *,
        stealth_order_id: str,
        body: StealthCreateLifecycleWriteGuardProofRequest,
    ) -> None:
        checks = {
            "guarded_command_route": body.guarded_command_route
            == "/api/v1/stealth/orders",
            "guarded_command_method": body.guarded_command_method == "POST",
            "guarded_service_method": body.guarded_service_method
            == "create_stealth_order",
            "stealth_order_id": body.stealth_order_id == stealth_order_id,
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            raise StealthLifecycleWriteGuardError(
                "Stealth lifecycle-write guarded create context did not match: "
                + ", ".join(failed)
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
            raise StealthLifecycleWriteGuardError(
                "Stealth lifecycle-write guard route is missing from route inventory."
            )
        if inventory_item.action_class != AdminApiActionClass.LOCAL_STATE_MUTATION:
            raise StealthLifecycleWriteGuardError(
                "Stealth lifecycle-write guard route must be a local-state mutation."
            )
        if (
            inventory_item.permission
            != AdminApiPermission.STEALTH_LIFECYCLE_WRITE_RECORD
        ):
            raise StealthLifecycleWriteGuardError(
                "Stealth lifecycle-write guard route must require "
                "stealth_lifecycle_write:record."
            )
        if inventory_item.shared_method != service_method:
            raise StealthLifecycleWriteGuardError(
                "Stealth lifecycle-write guard service method does not match route inventory."
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
                == AdminApiPermission.STEALTH_LIFECYCLE_WRITE_RECORD
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
            raise StealthLifecycleWriteGuardError(
                "Stealth lifecycle-write guard prerequisites did not pass: "
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
