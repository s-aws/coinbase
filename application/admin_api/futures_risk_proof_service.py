"""Backend-owned futures/perpetual risk proof service."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from core.enums import (
    AdminApiActionClass,
    AdminApiGateStatus,
    AdminApiPermission,
)

from .futures_risk_proof import (
    FileFuturesRiskProofStore,
    FuturesRiskProofRecord,
)
from .models import (
    AdminLiveAdmissionDecisionEvidence,
    FuturesRiskProofRecordRequest,
)
from .route_inventory import ADMIN_API_ROUTE_INVENTORY


PROOF_ROUTE = "/api/v1/futures/risk-proofs"
PROOF_METHOD = "POST"
PROOF_SERVICE_METHOD = "record_futures_risk_proof"


class FuturesRiskProofError(ValueError):
    """Raised when futures risk proof evidence is invalid."""


class AdminApiFuturesRiskProofService:
    """Service boundary for append-only futures/perpetual risk proof evidence."""

    def record_proof(
        self,
        *,
        proof_store: FileFuturesRiskProofStore,
        body: FuturesRiskProofRecordRequest,
        admission_decision: AdminLiveAdmissionDecisionEvidence,
        actor_id: str,
        operator_intent: str,
        idempotency_key: str,
        correlation_id: str,
        payload_hash: str,
        audit_id: str,
        now: datetime | None = None,
    ) -> FuturesRiskProofRecord:
        recorded_at = _normalize_now(now)
        self._validate_route_inventory(
            route=PROOF_ROUTE,
            method=PROOF_METHOD,
            service_method=PROOF_SERVICE_METHOD,
        )
        self._validate_required({
            "proof_contract_ref": body.proof_contract_ref,
            "evidence_ref": body.evidence_ref,
            "reconciliation_plan_id": body.reconciliation_plan_id,
            "approval_snapshot_id": body.approval_snapshot_id,
            "admission_audit_id": body.admission_audit_id,
            "cap_guard_decision_id": body.cap_guard_decision_id,
        })
        self._validate_safe_proof(body)
        self._validate_admission_prerequisites(
            admission_decision=admission_decision,
            route=PROOF_ROUTE,
            method=PROOF_METHOD,
            service_method=PROOF_SERVICE_METHOD,
            identity_value=_proof_identity(body),
            approval_snapshot_id=body.approval_snapshot_id,
            admission_audit_id=body.admission_audit_id,
            cap_guard_decision_id=body.cap_guard_decision_id,
            reconciliation_plan_id=body.reconciliation_plan_id,
        )
        proof_id = body.futures_risk_proof_id or _stable_id(
            "futures-risk-proof",
            route=PROOF_ROUTE,
            command=body.command.value,
            proof_kind=body.proof_kind.value,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
        )
        if proof_store.find_by_proof_id(proof_id) is not None:
            raise FuturesRiskProofError("Futures risk proof already exists.")

        record = FuturesRiskProofRecord(
            futures_risk_proof_id=proof_id,
            recorded_at=recorded_at.isoformat(),
            command=body.command,
            proof_kind=body.proof_kind,
            proof_contract_ref=body.proof_contract_ref,
            evidence_ref=body.evidence_ref,
            evidence_source=body.evidence_source,
            risk_evidence_refs=body.risk_evidence_refs,
            product_id=body.product_id,
            position_key=body.position_key,
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
        proof_store.append(record)
        return record

    @staticmethod
    def _validate_required(fields: dict[str, str | None]) -> None:
        missing = [name for name, value in fields.items() if not value]
        if missing:
            raise FuturesRiskProofError(
                "Futures risk proof is missing required fields: "
                + ", ".join(missing)
            )

    @staticmethod
    def _validate_safe_proof(body: FuturesRiskProofRecordRequest) -> None:
        if not body.dry_run:
            raise FuturesRiskProofError(
                "Futures risk proof must be recorded as dry-run evidence."
            )
        if body.manual_live_acknowledgement:
            raise FuturesRiskProofError(
                "Futures risk proof cannot include live acknowledgement."
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
            raise FuturesRiskProofError(
                "Futures risk proof route is missing from route inventory."
            )
        if inventory_item.action_class != AdminApiActionClass.LOCAL_STATE_MUTATION:
            raise FuturesRiskProofError(
                "Futures risk proof route must be a local-state mutation."
            )
        if inventory_item.permission != AdminApiPermission.FUTURES_RISK_PROOF_RECORD:
            raise FuturesRiskProofError(
                "Futures risk proof route must require futures_risk_proof:record."
            )
        if inventory_item.shared_method != service_method:
            raise FuturesRiskProofError(
                "Futures risk proof service method does not match route inventory."
            )

    @staticmethod
    def _validate_admission_prerequisites(
        *,
        admission_decision: AdminLiveAdmissionDecisionEvidence,
        route: str,
        method: str,
        service_method: str,
        identity_value: str,
        approval_snapshot_id: str | None,
        admission_audit_id: str | None,
        cap_guard_decision_id: str | None,
        reconciliation_plan_id: str | None,
    ) -> None:
        checks = {
            "route": admission_decision.route == route,
            "method": admission_decision.method == method,
            "module_id": admission_decision.module_id == "futures_perpetuals",
            "identity_key": admission_decision.identity_key == "futures_risk_proof",
            "identity_value": admission_decision.identity_value == identity_value,
            "action_class": (
                admission_decision.action_class
                == AdminApiActionClass.LOCAL_STATE_MUTATION
            ),
            "required_permission": (
                admission_decision.required_permission
                == AdminApiPermission.FUTURES_RISK_PROOF_RECORD
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
            raise FuturesRiskProofError(
                "Futures risk proof prerequisites did not pass: "
                + ", ".join(failed)
            )


def _proof_identity(body: FuturesRiskProofRecordRequest) -> str:
    return f"{body.command.value}:{body.proof_kind.value}"


def _stable_id(
    prefix: str,
    *,
    route: str,
    command: str,
    proof_kind: str,
    idempotency_key: str,
    payload_hash: str,
) -> str:
    material = "|".join([prefix, route, command, proof_kind, idempotency_key, payload_hash])
    return str(uuid.uuid5(uuid.NAMESPACE_URL, material))


def _normalize_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)
