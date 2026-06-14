"""Backend-owned Spot recovery exchange-state snapshot record service."""

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
    SpotRecoveryExchangeStateSnapshotRequest,
)
from .route_inventory import ADMIN_API_ROUTE_INVENTORY
from .spot_recovery_snapshot import (
    FileSpotRecoverySnapshotStore,
    SpotRecoveryExchangeStateSnapshotRecord,
)


EXCHANGE_STATE_SNAPSHOT_ROUTE = "/api/v1/spot/recovery/exchange-state-snapshots"
EXCHANGE_STATE_SNAPSHOT_METHOD = "POST"
EXCHANGE_STATE_SNAPSHOT_SERVICE_METHOD = (
    "record_spot_recovery_exchange_state_snapshot"
)


class SpotRecoverySnapshotError(ValueError):
    """Raised when a Spot recovery exchange-state snapshot record is invalid."""


class AdminApiSpotRecoverySnapshotService:
    """Service boundary for append-only exchange-state snapshots."""

    def record_exchange_state_snapshot(
        self,
        *,
        store: FileSpotRecoverySnapshotStore,
        body: SpotRecoveryExchangeStateSnapshotRequest,
        admission_decision: AdminLiveAdmissionDecisionEvidence,
        actor_id: str,
        operator_intent: str,
        idempotency_key: str,
        correlation_id: str,
        payload_hash: str,
        audit_id: str,
        now: datetime | None = None,
    ) -> SpotRecoveryExchangeStateSnapshotRecord:
        recorded_at = _normalize_now(now)
        self._validate_route_inventory()
        self._validate_required({
            "product_id": body.product_id,
            "source_timestamp": body.source_timestamp,
            "snapshot_evidence_ref": body.snapshot_evidence_ref,
            "reconciliation_plan_id": body.reconciliation_plan_id,
            "reconciliation_proof_id": body.reconciliation_proof_id,
            "completion_id": body.completion_id,
            "approval_snapshot_id": body.approval_snapshot_id,
            "admission_audit_id": body.admission_audit_id,
            "cap_guard_decision_id": body.cap_guard_decision_id,
        })
        self._validate_admission_prerequisites(
            admission_decision=admission_decision,
            body=body,
        )
        snapshot_id = body.exchange_state_snapshot_id or _stable_id(
            "exchange-state-snapshot",
            client_order_id=body.client_order_id,
            product_id=body.product_id,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
        )
        if store.find_by_snapshot_id(snapshot_id) is not None:
            raise SpotRecoverySnapshotError(
                "Spot recovery exchange-state snapshot already exists."
            )

        record = SpotRecoveryExchangeStateSnapshotRecord(
            exchange_state_snapshot_id=snapshot_id,
            recorded_at=recorded_at.isoformat(),
            client_order_id=body.client_order_id,
            product_id=body.product_id,
            source_timestamp=body.source_timestamp,
            snapshot_source=body.snapshot_source,
            snapshot_evidence_ref=body.snapshot_evidence_ref,
            reconciliation_plan_id=body.reconciliation_plan_id,
            reconciliation_proof_id=body.reconciliation_proof_id,
            completion_id=body.completion_id,
            approval_snapshot_id=body.approval_snapshot_id,
            admission_audit_id=body.admission_audit_id,
            cap_guard_decision_id=body.cap_guard_decision_id,
            route=EXCHANGE_STATE_SNAPSHOT_ROUTE,
            method=EXCHANGE_STATE_SNAPSHOT_METHOD,
            service_method=EXCHANGE_STATE_SNAPSHOT_SERVICE_METHOD,
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
            raise SpotRecoverySnapshotError(
                "Spot recovery exchange-state snapshot is missing required fields: "
                + ", ".join(missing)
            )

    @staticmethod
    def _validate_route_inventory() -> None:
        surface = f"{EXCHANGE_STATE_SNAPSHOT_METHOD} {EXCHANGE_STATE_SNAPSHOT_ROUTE}"
        inventory_item = next(
            (item for item in ADMIN_API_ROUTE_INVENTORY if item.surface == surface),
            None,
        )
        if inventory_item is None:
            raise SpotRecoverySnapshotError(
                "Spot recovery exchange-state snapshot route is missing from route inventory."
            )
        if inventory_item.action_class != AdminApiActionClass.LOCAL_STATE_MUTATION:
            raise SpotRecoverySnapshotError(
                "Spot recovery exchange-state snapshot route must be a local-state mutation."
            )
        if inventory_item.permission != AdminApiPermission.SPOT_RECOVERY_RECORD:
            raise SpotRecoverySnapshotError(
                "Spot recovery exchange-state snapshot route must require spot_recovery:record."
            )
        if inventory_item.shared_method != EXCHANGE_STATE_SNAPSHOT_SERVICE_METHOD:
            raise SpotRecoverySnapshotError(
                "Spot recovery exchange-state snapshot service method does not match route inventory."
            )

    @staticmethod
    def _validate_admission_prerequisites(
        *,
        admission_decision: AdminLiveAdmissionDecisionEvidence,
        body: SpotRecoveryExchangeStateSnapshotRequest,
    ) -> None:
        checks = {
            "route": admission_decision.route == EXCHANGE_STATE_SNAPSHOT_ROUTE,
            "method": admission_decision.method == EXCHANGE_STATE_SNAPSHOT_METHOD,
            "module_id": admission_decision.module_id == "spot_operations",
            "identity_key": admission_decision.identity_key == "client_order_id",
            "identity_value": admission_decision.identity_value == body.client_order_id,
            "action_class": (
                admission_decision.action_class
                == AdminApiActionClass.LOCAL_STATE_MUTATION
            ),
            "required_permission": (
                admission_decision.required_permission
                == AdminApiPermission.SPOT_RECOVERY_RECORD
            ),
            "service_method": (
                admission_decision.service_method
                == EXCHANGE_STATE_SNAPSHOT_SERVICE_METHOD
            ),
            "approval_snapshot": (
                admission_decision.approval_snapshot_present
                and admission_decision.approval_snapshot_id
                == body.approval_snapshot_id
            ),
            "admission_audit": (
                admission_decision.admission_audit_present
                and admission_decision.admission_audit_id
                == body.admission_audit_id
            ),
            "cap_guard": (
                admission_decision.cap_guard_present
                and admission_decision.cap_guard_decision_id
                == body.cap_guard_decision_id
            ),
            "reconciliation_plan": (
                admission_decision.reconciliation_plan_present
                and admission_decision.reconciliation_plan_id
                == body.reconciliation_plan_id
            ),
            "no_live": admission_decision.live_exchange_submitted is False,
            "not_allowed": admission_decision.allowed is False,
            "live_disabled": admission_decision.status == AdminApiGateStatus.BLOCKED,
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            raise SpotRecoverySnapshotError(
                "Spot recovery exchange-state snapshot prerequisites did not pass: "
                + ", ".join(failed)
            )


def _stable_id(
    prefix: str,
    *,
    client_order_id: str,
    product_id: str,
    idempotency_key: str,
    payload_hash: str,
) -> str:
    material = "|".join([prefix, client_order_id, product_id, idempotency_key, payload_hash])
    return f"{prefix}:{uuid.uuid5(uuid.NAMESPACE_URL, material)}"


def _normalize_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)
