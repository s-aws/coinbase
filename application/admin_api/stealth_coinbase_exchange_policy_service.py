"""Backend-owned stealth Coinbase exchange submission-policy proof service."""

from __future__ import annotations

from dataclasses import dataclass
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
    StealthCoinbaseExchangeSubmissionPolicyProofRequest,
)
from .route_inventory import ADMIN_API_ROUTE_INVENTORY
from .stealth_coinbase_exchange_policy import (
    FileStealthCoinbaseExchangeSubmissionPolicyProofStore,
    StealthCoinbaseExchangeSubmissionPolicyProofRecord,
)


PROOF_ROUTE = (
    "/api/v1/stealth/orders/{stealth_order_id}/"
    "coinbase-exchange-submission-policy-proofs"
)
READBACK_ROUTE = (
    "/api/v1/stealth/orders/{stealth_order_id}/"
    "coinbase-exchange-submission-policy"
)
PROOF_METHOD = "POST"
PROOF_SERVICE_METHOD = "record_stealth_coinbase_exchange_submission_policy_proof"


@dataclass(frozen=True)
class GuardedCoinbaseExchangePolicyCommand:
    """Allowed command context for Coinbase exchange policy proof evidence."""

    route: str
    service_method: str
    mutation_family: AdminApiMutationFamilyType


GUARDED_COINBASE_EXCHANGE_POLICY_COMMANDS: tuple[
    GuardedCoinbaseExchangePolicyCommand,
    ...,
] = (
    GuardedCoinbaseExchangePolicyCommand(
        route="/api/v1/stealth/orders",
        service_method="create_stealth_order",
        mutation_family=AdminApiMutationFamilyType.STEALTH_CREATE,
    ),
    GuardedCoinbaseExchangePolicyCommand(
        route="/api/v1/stealth/orders/{stealth_order_id}/reveal",
        service_method="reveal_stealth_order_by_stealth_order_id",
        mutation_family=AdminApiMutationFamilyType.STEALTH_REVEAL,
    ),
    GuardedCoinbaseExchangePolicyCommand(
        route="/api/v1/stealth/orders/{stealth_order_id}/cancel",
        service_method="cancel_stealth_order_by_stealth_order_id",
        mutation_family=AdminApiMutationFamilyType.STEALTH_CANCEL,
    ),
    GuardedCoinbaseExchangePolicyCommand(
        route="/api/v1/stealth/orders/{stealth_order_id}/move",
        service_method="move_stealth_order_by_stealth_order_id",
        mutation_family=AdminApiMutationFamilyType.STEALTH_MOVE,
    ),
    GuardedCoinbaseExchangePolicyCommand(
        route="/api/v1/stealth/orders/{stealth_order_id}/recovery",
        service_method="recover_stealth_order_by_stealth_order_id",
        mutation_family=AdminApiMutationFamilyType.STEALTH_RECOVERY,
    ),
    GuardedCoinbaseExchangePolicyCommand(
        route="/api/v1/stealth/orders/{stealth_order_id}/reconciliation",
        service_method="reconcile_stealth_order_by_stealth_order_id",
        mutation_family=AdminApiMutationFamilyType.STEALTH_RECONCILIATION,
    ),
    GuardedCoinbaseExchangePolicyCommand(
        route="/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice",
        service_method="reprice_stealth_order_by_stealth_order_id",
        mutation_family=AdminApiMutationFamilyType.MOVEMENT_REPRICE,
    ),
)


class StealthCoinbaseExchangeSubmissionPolicyError(ValueError):
    """Raised when Coinbase exchange submission-policy evidence is invalid."""


class AdminApiStealthCoinbaseExchangeSubmissionPolicyService:
    """Service boundary for append-only Coinbase exchange policy evidence."""

    def record_proof(
        self,
        *,
        proof_store: FileStealthCoinbaseExchangeSubmissionPolicyProofStore,
        stealth_order_id: str,
        body: StealthCoinbaseExchangeSubmissionPolicyProofRequest,
        admission_decision: AdminLiveAdmissionDecisionEvidence,
        actor_id: str,
        operator_intent: str,
        idempotency_key: str,
        correlation_id: str,
        payload_hash: str,
        audit_id: str,
        now: datetime | None = None,
    ) -> StealthCoinbaseExchangeSubmissionPolicyProofRecord:
        recorded_at = _normalize_now(now)
        self._validate_route_inventory(
            route=PROOF_ROUTE,
            method=PROOF_METHOD,
            service_method=PROOF_SERVICE_METHOD,
        )
        self._validate_required({
            "guarded_payload_hash": body.guarded_payload_hash,
            "exchange_submission_policy_ref": body.exchange_submission_policy_ref,
            "coinbase_cancel_policy_ref": body.coinbase_cancel_policy_ref,
            "live_coinbase_read_policy_ref": body.live_coinbase_read_policy_ref,
            "live_cap_evidence_ref": body.live_cap_evidence_ref,
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
        proof_id = body.coinbase_exchange_policy_proof_id or _stable_id(
            "stealth-coinbase-exchange-policy-proof",
            route=PROOF_ROUTE,
            stealth_order_id=stealth_order_id,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
        )
        if proof_store.find_by_proof_id(proof_id) is not None:
            raise StealthCoinbaseExchangeSubmissionPolicyError(
                "Stealth Coinbase exchange policy proof already exists."
            )

        record = StealthCoinbaseExchangeSubmissionPolicyProofRecord(
            coinbase_exchange_policy_proof_id=proof_id,
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
            exchange_submission_policy_ref=body.exchange_submission_policy_ref,
            coinbase_cancel_policy_ref=body.coinbase_cancel_policy_ref,
            live_coinbase_read_policy_ref=body.live_coinbase_read_policy_ref,
            live_cap_evidence_ref=body.live_cap_evidence_ref,
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
            raise StealthCoinbaseExchangeSubmissionPolicyError(
                "Stealth Coinbase exchange policy proof is missing required fields: "
                + ", ".join(missing)
            )

    @staticmethod
    def _validate_guarded_command_context(
        *,
        stealth_order_id: str,
        body: StealthCoinbaseExchangeSubmissionPolicyProofRequest,
    ) -> None:
        guarded_command = next(
            (
                command
                for command in GUARDED_COINBASE_EXCHANGE_POLICY_COMMANDS
                if command.route == body.guarded_command_route
            ),
            None,
        )
        checks = {
            "guarded_command_route": guarded_command is not None,
            "guarded_command_method": body.guarded_command_method == "POST",
            "guarded_service_method": (
                guarded_command is not None
                and body.guarded_service_method == guarded_command.service_method
            ),
            "guarded_mutation_family": (
                guarded_command is not None
                and body.guarded_mutation_family == guarded_command.mutation_family
            ),
            "stealth_order_id": body.stealth_order_id == stealth_order_id,
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            raise StealthCoinbaseExchangeSubmissionPolicyError(
                "Stealth Coinbase exchange guarded command context did not match: "
                + ", ".join(failed)
            )

    @staticmethod
    def _validate_safe_proof(
        body: StealthCoinbaseExchangeSubmissionPolicyProofRequest,
    ) -> None:
        if not body.dry_run:
            raise StealthCoinbaseExchangeSubmissionPolicyError(
                "Stealth Coinbase exchange policy proof must be dry-run evidence."
            )
        if body.manual_live_acknowledgement:
            raise StealthCoinbaseExchangeSubmissionPolicyError(
                "Stealth Coinbase exchange policy proof cannot include live acknowledgement."
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
            raise StealthCoinbaseExchangeSubmissionPolicyError(
                "Stealth Coinbase exchange policy route is missing from route inventory."
            )
        if inventory_item.action_class != AdminApiActionClass.LOCAL_STATE_MUTATION:
            raise StealthCoinbaseExchangeSubmissionPolicyError(
                "Stealth Coinbase exchange policy route must be a local-state mutation."
            )
        if (
            inventory_item.permission
            != AdminApiPermission.STEALTH_COINBASE_EXCHANGE_POLICY_RECORD
        ):
            raise StealthCoinbaseExchangeSubmissionPolicyError(
                "Stealth Coinbase exchange policy route must require "
                "stealth_coinbase_exchange_policy:record."
            )
        if inventory_item.shared_method != service_method:
            raise StealthCoinbaseExchangeSubmissionPolicyError(
                "Stealth Coinbase exchange policy service method does not match route inventory."
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
                == AdminApiPermission.STEALTH_COINBASE_EXCHANGE_POLICY_RECORD
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
            raise StealthCoinbaseExchangeSubmissionPolicyError(
                "Stealth Coinbase exchange policy prerequisites did not pass: "
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
