"""Backend-owned Spot recovery execution journal service."""

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
    SpotRecoveryApplyExecutionRequest,
    SpotRecoveryRollbackExecutionRequest,
)
from .route_inventory import ADMIN_API_ROUTE_INVENTORY
from .spot_recovery_execution import (
    FileSpotRecoveryExecutionJournalStore,
    SpotRecoveryExecutionRecord,
)
from .spot_recovery_proof import FileSpotRecoveryProofStore


APPLY_ROUTE = "/api/v1/spot/recovery/apply-executions"
ROLLBACK_ROUTE = "/api/v1/spot/recovery/rollback-executions"
APPLY_METHOD = "POST"
ROLLBACK_METHOD = "POST"
APPLY_SERVICE_METHOD = "execute_spot_recovery_apply"
ROLLBACK_SERVICE_METHOD = "execute_spot_recovery_rollback"


class SpotRecoveryExecutionError(ValueError):
    """Raised when a Spot recovery execution journal record is invalid."""


class AdminApiSpotRecoveryExecutionService:
    """Service boundary for append-only Spot recovery apply/rollback journals."""

    def record_apply_execution(
        self,
        *,
        execution_store: FileSpotRecoveryExecutionJournalStore,
        proof_store: FileSpotRecoveryProofStore,
        body: SpotRecoveryApplyExecutionRequest,
        admission_decision: AdminLiveAdmissionDecisionEvidence,
        actor_id: str,
        operator_intent: str,
        idempotency_key: str,
        correlation_id: str,
        payload_hash: str,
        audit_id: str,
        now: datetime | None = None,
    ) -> SpotRecoveryExecutionRecord:
        recorded_at = _normalize_now(now)
        self._validate_route_inventory(
            route=APPLY_ROUTE,
            method=APPLY_METHOD,
            service_method=APPLY_SERVICE_METHOD,
        )
        self._validate_required({
            "rollback_plan_id": body.rollback_plan_id,
            "exchange_state_proof_id": body.exchange_state_proof_id,
            "reconciliation_plan_id": body.reconciliation_plan_id,
            "approval_snapshot_id": body.approval_snapshot_id,
            "admission_audit_id": body.admission_audit_id,
            "cap_guard_decision_id": body.cap_guard_decision_id,
        })
        self._validate_admission_prerequisites(
            admission_decision=admission_decision,
            body_client_order_id=body.client_order_id,
            route=APPLY_ROUTE,
            method=APPLY_METHOD,
            service_method=APPLY_SERVICE_METHOD,
            approval_snapshot_id=body.approval_snapshot_id,
            admission_audit_id=body.admission_audit_id,
            cap_guard_decision_id=body.cap_guard_decision_id,
            reconciliation_plan_id=body.reconciliation_plan_id,
        )
        exchange_state_record = proof_store.find_by_exchange_state_proof_id(
            body.exchange_state_proof_id
        )
        if exchange_state_record is None:
            raise SpotRecoveryExecutionError(
                "Referenced exchange-state proof was not found."
            )
        if exchange_state_record.client_order_id != body.client_order_id:
            raise SpotRecoveryExecutionError(
                "Referenced exchange-state proof client_order_id does not match."
            )
        if exchange_state_record.live_exchange_submitted:
            raise SpotRecoveryExecutionError(
                "Referenced exchange-state proof cannot include live execution."
            )

        journal_id = _stable_id(
            "spot-recovery-apply-journal",
            route=APPLY_ROUTE,
            client_order_id=body.client_order_id,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
        )
        if execution_store.find_by_journal_id(journal_id) is not None:
            raise SpotRecoveryExecutionError(
                "Spot recovery execution journal already exists."
            )

        record = SpotRecoveryExecutionRecord(
            journal_id=journal_id,
            recorded_at=recorded_at.isoformat(),
            mutation_family=AdminApiMutationFamilyType.SPOT_RECOVERY_APPLY_EXECUTION,
            client_order_id=body.client_order_id,
            rollback_plan_id=body.rollback_plan_id,
            exchange_state_proof_id=body.exchange_state_proof_id,
            reconciliation_plan_id=body.reconciliation_plan_id,
            approval_snapshot_id=body.approval_snapshot_id,
            admission_audit_id=body.admission_audit_id,
            cap_guard_decision_id=body.cap_guard_decision_id,
            route=APPLY_ROUTE,
            method=APPLY_METHOD,
            service_method=APPLY_SERVICE_METHOD,
            actor_id=actor_id,
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            payload_hash=payload_hash,
            audit_id=audit_id,
            dry_run=body.dry_run,
            operator_reason=body.operator_reason,
            manual_live_acknowledgement=body.manual_live_acknowledgement,
            execution_journal_accepted=True,
            recovery_apply_journal_accepted=True,
            rollback_journal_accepted=False,
            recovery_apply_executed=True,
            rollback_executed=False,
            post_apply_reconciliation_required=True,
            post_apply_reconciliation_satisfied=False,
        )
        execution_store.append(record)
        return record

    def record_rollback_execution(
        self,
        *,
        execution_store: FileSpotRecoveryExecutionJournalStore,
        body: SpotRecoveryRollbackExecutionRequest,
        admission_decision: AdminLiveAdmissionDecisionEvidence,
        actor_id: str,
        operator_intent: str,
        idempotency_key: str,
        correlation_id: str,
        payload_hash: str,
        audit_id: str,
        now: datetime | None = None,
    ) -> SpotRecoveryExecutionRecord:
        recorded_at = _normalize_now(now)
        self._validate_route_inventory(
            route=ROLLBACK_ROUTE,
            method=ROLLBACK_METHOD,
            service_method=ROLLBACK_SERVICE_METHOD,
        )
        self._validate_required({
            "rollback_plan_id": body.rollback_plan_id,
            "recovery_apply_audit_id": body.recovery_apply_audit_id,
            "reconciliation_plan_id": body.reconciliation_plan_id,
            "approval_snapshot_id": body.approval_snapshot_id,
            "admission_audit_id": body.admission_audit_id,
            "cap_guard_decision_id": body.cap_guard_decision_id,
        })
        self._validate_admission_prerequisites(
            admission_decision=admission_decision,
            body_client_order_id=body.client_order_id,
            route=ROLLBACK_ROUTE,
            method=ROLLBACK_METHOD,
            service_method=ROLLBACK_SERVICE_METHOD,
            approval_snapshot_id=body.approval_snapshot_id,
            admission_audit_id=body.admission_audit_id,
            cap_guard_decision_id=body.cap_guard_decision_id,
            reconciliation_plan_id=body.reconciliation_plan_id,
        )
        apply_record = execution_store.find_by_audit_id(body.recovery_apply_audit_id)
        if apply_record is None:
            raise SpotRecoveryExecutionError(
                "Referenced recovery apply execution journal was not found."
            )
        if (
            apply_record.mutation_family
            != AdminApiMutationFamilyType.SPOT_RECOVERY_APPLY_EXECUTION
        ):
            raise SpotRecoveryExecutionError(
                "Referenced recovery apply audit is not an apply journal."
            )
        if apply_record.client_order_id != body.client_order_id:
            raise SpotRecoveryExecutionError(
                "Referenced recovery apply journal client_order_id does not match."
            )
        if (
            execution_store.find_rollback_for_apply_audit(body.recovery_apply_audit_id)
            is not None
        ):
            raise SpotRecoveryExecutionError(
                "Referenced recovery apply journal already has a rollback."
            )

        journal_id = _stable_id(
            "spot-recovery-rollback-journal",
            route=ROLLBACK_ROUTE,
            client_order_id=body.client_order_id,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
        )
        if execution_store.find_by_journal_id(journal_id) is not None:
            raise SpotRecoveryExecutionError(
                "Spot recovery execution journal already exists."
            )

        record = SpotRecoveryExecutionRecord(
            journal_id=journal_id,
            recorded_at=recorded_at.isoformat(),
            mutation_family=(
                AdminApiMutationFamilyType.SPOT_RECOVERY_ROLLBACK_EXECUTION
            ),
            client_order_id=body.client_order_id,
            rollback_plan_id=body.rollback_plan_id,
            recovery_apply_audit_id=body.recovery_apply_audit_id,
            recovery_apply_journal_id=apply_record.journal_id,
            exchange_state_proof_id=apply_record.exchange_state_proof_id,
            reconciliation_plan_id=body.reconciliation_plan_id,
            approval_snapshot_id=body.approval_snapshot_id,
            admission_audit_id=body.admission_audit_id,
            cap_guard_decision_id=body.cap_guard_decision_id,
            route=ROLLBACK_ROUTE,
            method=ROLLBACK_METHOD,
            service_method=ROLLBACK_SERVICE_METHOD,
            actor_id=actor_id,
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            payload_hash=payload_hash,
            audit_id=audit_id,
            dry_run=body.dry_run,
            operator_reason=body.operator_reason,
            manual_live_acknowledgement=body.manual_live_acknowledgement,
            execution_journal_accepted=True,
            recovery_apply_journal_accepted=False,
            rollback_journal_accepted=True,
            recovery_apply_executed=False,
            rollback_executed=True,
            post_apply_reconciliation_required=False,
            post_apply_reconciliation_satisfied=(
                apply_record.post_apply_reconciliation_satisfied
            ),
        )
        execution_store.append(record)
        return record

    @staticmethod
    def _validate_required(fields: dict[str, str | None]) -> None:
        missing = [name for name, value in fields.items() if not value]
        if missing:
            raise SpotRecoveryExecutionError(
                "Spot recovery execution is missing required fields: "
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
            raise SpotRecoveryExecutionError(
                "Spot recovery execution route is missing from route inventory."
            )
        if inventory_item.action_class != AdminApiActionClass.LOCAL_STATE_MUTATION:
            raise SpotRecoveryExecutionError(
                "Spot recovery execution route must be a local-state mutation."
            )
        if inventory_item.permission != AdminApiPermission.SPOT_RECOVERY_EXECUTE:
            raise SpotRecoveryExecutionError(
                "Spot recovery execution route must require spot_recovery:execute."
            )
        if inventory_item.shared_method != service_method:
            raise SpotRecoveryExecutionError(
                "Spot recovery execution service method does not match route inventory."
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
                == AdminApiPermission.SPOT_RECOVERY_EXECUTE
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
            raise SpotRecoveryExecutionError(
                "Spot recovery execution prerequisites did not pass: "
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
