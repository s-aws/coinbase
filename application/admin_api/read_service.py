"""Read-only Admin API service wrappers."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any
import uuid

from core.enums import (
    ActionConditionType,
    ActionGuardPhase,
    AdminApiActionClass,
    AdminApiAuthMode,
    AdminAuditEvidenceSource,
    AdminAuditWorkbenchModule,
    AdminApiFunctionalityExposureStatus,
    AdminApiFunctionalityWorkflowType,
    AdminFuturesEvidenceSource,
    AdminFuturesEvidenceStatus,
    AdminFuturesPositionSide,
    AdminApiGateStatus,
    AdminApiHealthStatus,
    AdminApiLiveAdmissionAuditFact,
    AdminApiLiveAdmissionBlocker,
    AdminApiLiveApprovalStoreRequirement,
    AdminApiLiveApprovalSnapshotField,
    AdminApiLiveCapGuardRequirement,
    AdminApiLiveExecutionStatus,
    AdminApiLivePreflightCategory,
    AdminApiLiveReadinessPrecondition,
    AdminApiModuleSupportStatus,
    AdminMovementRepricingEvidenceType,
    AdminApiMutationFamilyType,
    AdminApiPermission,
    AdminApiRouteAvailability,
    AdminApiSessionStatus,
    AdminApiSpotCommandSuiteGapFamily,
    AdminApiStealthAdmissionContextField,
    AdminApiStealthAdmissionEvidence,
    AdminApiStealthCommandSuiteGapFamily,
    AdminApiVerifierReadinessStatus,
    OrderSide,
    ProductCapability,
    ProductType,
    SpotRecoveryCompletionState,
    SpotRecoveryRepairCategory,
    StealthOrderStatus,
    StealthMutationKind,
    AdminRiskEvidenceSource,
    AdminRiskEvidenceStatus,
)

from .approval import evaluate_live_execution_gate
from .audit import AdminApiAuditEvent, FileAdminApiAuditStore
from .auth import (
    build_oidc_jwt_readiness,
    check_oidc_jwks_reachability,
    configured_auth_mode,
)
from .live_execution import (
    DISABLED_LIVE_EXECUTION_SERVICE_SOURCE,
    DISABLED_STEALTH_LIVE_EXECUTION_ADAPTER_SOURCE,
    build_live_execution_adapter_contract,
)
from .models import (
    AdminApiActor,
    AdminAuditModuleSummaryItem,
    AdminAuditWorkbenchEventItem,
    AdminAuditWorkbenchReadResponse,
    AdminBootstrapResponse,
    AdminCapabilityItem,
    AdminCapabilityRegistryResponse,
    AdminCsrfContractResponse,
    AdminEnterpriseCommandGapItem,
    AdminEnterpriseFunctionalityInventoryItem,
    AdminEnterpriseMutationTaxonomyItem,
    AdminEnterpriseModuleActionPosture,
    AdminEnterpriseReadinessModuleItem,
    AdminEnterpriseReadinessResponse,
    AdminFrontendFixturesResponse,
    AdminFuturesAccountReadResponse,
    AdminLiveAdmissionAuditFactItem,
    AdminLiveAdmissionAuditTrailEvidence,
    AdminLiveCapGuardContractEvidence,
    AdminLiveCapGuardRequirementItem,
    AdminFuturesEvidenceItem,
    AdminFuturesPositionDetailResponse,
    AdminFuturesPositionListResponse,
    AdminFuturesPositionReadItem,
    AdminGateCheck,
    AdminGateReadResponse,
    AdminHealthResponse,
    AdminLiveApprovalStoreContractEvidence,
    AdminLiveApprovalStoreRequirementItem,
    AdminLiveApprovalSnapshotEvidence,
    AdminLiveApprovalSnapshotRequiredFieldItem,
    AdminLiveEnablementPathItem,
    AdminLivePreflightCheckItem,
    AdminLiveReadinessPreconditionItem,
    AdminLiveEnablementReadResponse,
    AdminMovementRepricingDetailResponse,
    AdminMovementRepricingEvidenceItem,
    AdminMovementRepricingListResponse,
    AdminMutationClaimEvidence,
    AdminOidcJwtReadinessResponse,
    AdminOrderDetailResponse,
    AdminOrderListResponse,
    AdminOrderReadItem,
    AdminReplacementSlotEvidence,
    AdminProductCapabilityDecisionItem,
    AdminRiskEvidenceItem,
    AdminRiskPolicyReadResponse,
    AdminRiskPolicyRuleItem,
    AdminRiskRejectionCategoryItem,
    AdminSessionResponse,
    AdminStealthOrderDetailResponse,
    AdminStealthActivePlacementAuditEvidence,
    AdminStealthMutationClaimAuditEvidence,
    AdminStealthRevealTriggerAuditEvidence,
    AdminStealthRevealSubmissionAuditEvidence,
    AdminStealthRevealReconciliationAuditEvidence,
    AdminStealthOrderListResponse,
    AdminStealthOrderReadItem,
    StealthActivePlacementExchangeTruthProofRecordItem,
    StealthActivePlacementExchangeTruthReadResponse,
    StealthActivePlacementExchangeTruthSnapshotRecordItem,
    StealthCoinbaseExchangeSubmissionPolicyProofRecordItem,
    StealthCoinbaseExchangeSubmissionPolicyReadResponse,
    StealthCreateLifecycleWriteGuardProofRecordItem,
    StealthCreateLifecycleWriteGuardReadResponse,
    StealthMutationClaimSnapshotProofRecordItem,
    StealthMutationClaimSnapshotReadResponse,
    StealthManagerInvocationPolicyProofRecordItem,
    StealthManagerInvocationPolicyReadResponse,
    StealthCancelReplaceProofReadResponse,
    StealthCancelReplaceProofRecordItem,
    StealthPostWriteExecutionJournalReadResponse,
    StealthPostWriteExecutionJournalRecordItem,
    StealthPostWriteReconciliationExecutionPolicyReadResponse,
    StealthPostWriteReconciliationExecutionPolicyProofRecordItem,
    StealthPostWriteReconciliationVerificationReadResponse,
    StealthPostWriteReconciliationVerificationRecordItem,
    StealthPostWriteReconciliationProofReadResponse,
    StealthPostWriteReconciliationProofRecordItem,
    StealthStateMutationPolicyReadResponse,
    StealthStateMutationPolicyProofRecordItem,
    StealthRevealTriggerProofReadResponse,
    StealthRevealTriggerProofRecordItem,
    StealthReconciliationProofReadResponse,
    StealthReconciliationProofRecordItem,
    StealthRecoveryProofReadResponse,
    StealthRecoveryProofRecordItem,
    SpotCommandSuiteCommandItem,
    SpotCommandSuiteCoverageGapEvidenceRouteItem,
    SpotCommandSuiteCoverageGapItem,
    SpotCommandSuiteProofRouteItem,
    SpotCommandSuiteResponse,
    SpotRecoveryApplyReviewResponse,
    SpotRecoveryCompletionRecordItem,
    SpotRecoveryCompletionStateItem,
    SpotRecoveryContractCandidateItem,
    SpotRecoveryContractGateItem,
    SpotRecoveryDryRunRepairPlanItem,
    SpotRecoveryExecutionRecordItem,
    SpotRecoveryExchangeStateSnapshotRecordItem,
    SpotRecoveryPreApplySnapshotItem,
    SpotRecoveryPreviewResponse,
    SpotRecoveryPreviewSourceItem,
    SpotRecoveryProofRecordItem,
    SpotRecoveryReconciliationExecutionBoundaryItem,
    SpotRecoveryReconciliationProofResponse,
    SpotRecoveryRepairResultRecordItem,
    SpotRecoveryRepairTargetItem,
    SpotRecoveryRollbackPlanResponse,
    SpotRecoveryStateRepairTaxonomyItem,
    StealthCommandSuiteCommandItem,
    StealthCommandSuiteAdmissionContextItem,
    StealthCommandSuiteAdmissionReadinessItem,
    StealthCommandSuiteAdmissionRequirementItem,
    StealthCommandSuiteCancelReplaceBoundaryItem,
    StealthCommandSuiteCoverageGapEvidenceRouteItem,
    StealthCommandSuiteCoverageGapItem,
    StealthCommandSuiteExchangeTruthItem,
    StealthCreateLifecycleWriteAuditEvidence,
    StealthCommandSuiteProofRouteItem,
    StealthCommandSuiteResponse,
)
from .route_inventory import ADMIN_API_ROUTE_INVENTORY
from .stealth_cancel_replace_boundary import (
    build_stealth_active_placement_cancel_replace_contract,
)
from .stealth_command_proof_routes import (
    build_stealth_command_specific_proof_route_contracts,
)
from .stealth_exchange_truth_boundary import (
    EXCHANGE_TRUTH_SURFACES_BY_FAMILY,
    build_stealth_active_placement_exchange_truth_contract,
)
from .spot_recovery_completion import (
    FileSpotRecoveryCompletionJournalStore,
    SpotRecoveryCompletionRecord,
)
from .spot_recovery_execution import (
    FileSpotRecoveryExecutionJournalStore,
    SpotRecoveryExecutionRecord,
)
from .spot_recovery_proof import FileSpotRecoveryProofStore, SpotRecoveryProofRecord
from .spot_recovery_snapshot import (
    FileSpotRecoverySnapshotStore,
    SpotRecoveryExchangeStateSnapshotRecord,
)
from .spot_recovery_repair import (
    FileSpotRecoveryRepairResultJournalStore,
    SpotRecoveryRepairResultRecord,
)
from .stealth_exchange_truth import (
    FileStealthExchangeTruthProofStore,
    FileStealthExchangeTruthSnapshotStore,
    StealthActivePlacementExchangeTruthProofRecord,
    StealthActivePlacementExchangeTruthSnapshotRecord,
)
from .stealth_lifecycle_write import (
    FileStealthLifecycleWriteGuardProofStore,
    StealthCreateLifecycleWriteGuardProofRecord,
)
from .stealth_lifecycle_execution import (
    build_stealth_create_lifecycle_write_execution_contract,
)
from .stealth_mutation_claim import (
    FileStealthMutationClaimProofStore,
    StealthMutationClaimSnapshotProofRecord,
)
from .stealth_manager_policy import (
    FileStealthManagerInvocationPolicyProofStore,
    StealthManagerInvocationPolicyProofRecord,
)
from .stealth_coinbase_exchange_policy import (
    FileStealthCoinbaseExchangeSubmissionPolicyProofStore,
    StealthCoinbaseExchangeSubmissionPolicyProofRecord,
)
from .stealth_state_mutation_policy import (
    FileStealthStateMutationPolicyProofStore,
    StealthStateMutationPolicyProofRecord,
)
from .stealth_post_write_reconciliation_policy import (
    FileStealthPostWriteReconciliationExecutionPolicyProofStore,
    StealthPostWriteReconciliationExecutionPolicyProofRecord,
)
from .stealth_reveal_trigger_proof import (
    FileStealthRevealTriggerProofStore,
    StealthRevealTriggerProofRecord,
)
from .stealth_recovery_proof import (
    FileStealthRecoveryProofStore,
    StealthRecoveryProofRecord,
)
from .stealth_reconciliation_proof import (
    FileStealthReconciliationProofStore,
    StealthReconciliationProofRecord,
)
from .stealth_cancel_replace_proof import (
    FileStealthCancelReplaceProofStore,
    StealthCancelReplaceProofRecord,
)
from .stealth_post_write_reconciliation import (
    FileStealthPostWriteExecutionJournalStore,
    StealthPostWriteExecutionJournalAcceptanceRecord,
    FileStealthPostWriteReconciliationProofStore,
    StealthPostWriteReconciliationProofRecord,
    FileStealthPostWriteReconciliationVerificationStore,
    StealthPostWriteReconciliationVerificationRecord,
    is_safe_stealth_post_write_execution_journal_record,
    is_safe_stealth_post_write_reconciliation_proof_record,
    is_safe_stealth_post_write_reconciliation_verification_record,
    post_write_execution_journal_matches_proof,
    post_write_reconciliation_verification_matches,
)


ROOT = Path(__file__).resolve().parents[2]
API_VERSION = "0.1.0"
SCHEMA_VERSION = "0.1.0"
AUTONOMOUS_APPROVED_PHASE_RANGE = "3501-3520"
LIVE_ENABLEMENT_QUOTE_CURRENCY = "USDC"
LIVE_ENABLEMENT_PRODUCT_SCOPE = (
    "cheapest Coinbase USDC spot product available to US customers"
)
LIVE_ENABLEMENT_MAX_SUBMITTED_NOTIONAL_USDC = "3.10"
LIVE_ENABLEMENT_MAX_EXECUTED_NOTIONAL_USDC = "1.00"


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_read_id(prefix: str, *parts: str) -> str:
    material = "|".join([prefix, *parts])
    return f"{prefix}:{uuid.uuid5(uuid.NAMESPACE_URL, material)}"


def _csrf_required() -> bool:
    return os.environ.get(
        "COINBASE_ADMIN_API_CSRF_REQUIRED",
        "",
    ).strip().lower() in {"1", "true", "yes"}


def _surface_method_and_path(surface: str) -> tuple[str, str]:
    first, _, rest = surface.partition(" ")
    if rest.startswith("/"):
        return first, rest
    if "WebSocket" in surface:
        return "WEBSOCKET", surface
    return "UNKNOWN", surface


def _route_availability(surface: str, action_class: AdminApiActionClass) -> AdminApiRouteAvailability:
    if "WebSocket" in surface:
        return AdminApiRouteAvailability.CONTRACT_PENDING
    if surface.startswith("POST /api/v1") and action_class in {
        AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
    }:
        return AdminApiRouteAvailability.LIVE_DISABLED
    return AdminApiRouteAvailability.AVAILABLE


def _frontend_safe(surface: str, action_class: AdminApiActionClass) -> bool:
    if "WebSocket" in surface:
        return False
    return action_class == AdminApiActionClass.READ_ONLY or surface.startswith("POST /api/v1")


def _live_enablement_module(path: str) -> str:
    if path.startswith("/api/v1/spot/") or path == "/api/v1/orders":
        return "spot"
    if path.startswith("/api/v1/stealth/"):
        return "stealth"
    if path.startswith("/api/v1/movement-repricing/"):
        return "movement_repricing"
    if path.startswith("/api/v1/orders/"):
        return "orders"
    return "admin"


def _enterprise_module_name(module_id: str) -> str:
    return {
        "admin_system_health": "Admin / System Health",
        "spot_operations": "Spot Operations",
        "futures_perpetuals": "Futures / Perpetuals",
        "stealth_orders": "Stealth Orders",
        "movement_repricing": "Order Movement / Repricing",
        "guard_risk_policy": "Guard / Risk Policy",
        "audit_workbench": "Audit Workbench",
        "legacy_dashboard_websocket": "Legacy Dashboard WebSocket",
    }.get(module_id, module_id)


def _enterprise_module_owner(module_id: str) -> str:
    return {
        "admin_system_health": "admin_api_contract",
        "spot_operations": "strategy",
        "futures_perpetuals": "admin_api_contract",
        "stealth_orders": "stealth_lifecycle",
        "movement_repricing": "stealth_lifecycle",
        "guard_risk_policy": "order_lifecycle",
        "audit_workbench": "admin_api_contract",
        "legacy_dashboard_websocket": "dashboard_contract",
    }.get(module_id, "admin_api_contract")


def _enterprise_module_identity_key(module_id: str, route: str) -> str:
    if module_id == "stealth_orders":
        return "stealth_order_id"
    if module_id == "movement_repricing":
        return "stealth_order_id"
    if module_id == "futures_perpetuals":
        return "position_key"
    if "spot/sweep/automation-runs" in route:
        return "sweep_config_id"
    if "campaign" in route:
        return "campaign_id"
    if module_id == "spot_operations":
        return "client_order_id"
    return "request_id"


def _enterprise_module_spot_boundary(module_id: str) -> str:
    if module_id == "spot_operations":
        return (
            "Spot-only wallet, USDC, no-shorting, inventory, cost-basis, "
            "and average-cost rules apply only to spot command authority."
        )
    if module_id == "futures_perpetuals":
        return (
            "Futures/perpetual authority is position, margin, leverage, "
            "collateral, liquidation, and reduce-only aware; spot inventory "
            "rules must not be reused."
        )
    if module_id in {"stealth_orders", "movement_repricing"}:
        return (
            "Stealth and movement/repricing authority is exchange-reality "
            "and mutation-claim based; spot wallet rules are not browser "
            "authority for these workflows."
        )
    return "No spot trading rule is generic platform authority."


def _live_governance_blockers(module_id: str, route: str) -> list[str]:
    blockers = [
        "post-live reconciliation evidence is not wired for this route",
        "explicit M8 live approval snapshot is not present for this route",
        "backend cap, guard, idempotency, operator-intent, and audit evidence must be enforced before live enablement",
    ]
    if module_id == "spot_operations":
        blockers.append(
            "spot wallet, inventory, no-shorting, and cost-basis authority must remain backend-owned"
        )
    if module_id == "stealth_orders":
        blockers.append(
            "stealth cancellation must account for active exchange placement reality before local state changes"
        )
    if module_id == "movement_repricing":
        blockers.append(
            "movement/repricing must use backend cancel/replace and mutation-claim handling before live repricing"
        )
    if "campaign" in route:
        blockers.append(
            "spot campaign execution must retain dry-run and sweep reconciliation evidence until live approval"
        )
    return blockers


def _preflight_check(
    *,
    name: str,
    category: AdminApiLivePreflightCategory,
    status: AdminApiGateStatus,
    owner: str,
    evidence: str,
    detail: str,
) -> AdminLivePreflightCheckItem:
    return AdminLivePreflightCheckItem(
        name=name,
        category=category,
        status=status,
        required=True,
        blocking=status == AdminApiGateStatus.BLOCKED,
        owner=owner,
        evidence=evidence,
        detail=detail,
    )


def _live_preflight_checks(
    *,
    module_id: str,
    route: str,
    shared_method: str,
) -> list[AdminLivePreflightCheckItem]:
    module_owner = _enterprise_module_owner(module_id)
    return [
        _preflight_check(
            name="auth_rbac",
            category=AdminApiLivePreflightCategory.AUTHORIZATION,
            status=AdminApiGateStatus.PASSED,
            owner="admin_api_contract",
            evidence="FastAPI route requires authenticated Admin API actor and backend RBAC.",
            detail="Live-shaped HTTP routes already fail closed without auth and permission evidence.",
        ),
        _preflight_check(
            name="idempotency_operator_intent",
            category=AdminApiLivePreflightCategory.IDEMPOTENCY,
            status=AdminApiGateStatus.PASSED,
            owner="admin_api_contract",
            evidence="Idempotency-Key, X-Operator-Intent, payload hash, and request id are captured before command service delegation.",
            detail="Current dry command contracts preserve replay/conflict evidence without placing Coinbase orders.",
        ),
        _preflight_check(
            name="durable_audit",
            category=AdminApiLivePreflightCategory.AUDIT,
            status=AdminApiGateStatus.PASSED,
            owner="admin_api_contract",
            evidence="Command audit events are written before live-disabled responses are returned.",
            detail="Audit id and correlation id are available as operator evidence for dry-submit review.",
        ),
        _preflight_check(
            name="browser_authority",
            category=AdminApiLivePreflightCategory.BROWSER_AUTHORITY,
            status=AdminApiGateStatus.PASSED,
            owner="admin_api_contract",
            evidence="Frontend authority is display_only and command workflows require backend capability evidence.",
            detail="The browser may show preflight evidence but must not approve, place, cancel, or reconcile live orders.",
        ),
        _preflight_check(
            name="approval_snapshot",
            category=AdminApiLivePreflightCategory.APPROVAL,
            status=AdminApiGateStatus.BLOCKED,
            owner="admin_api_contract",
            evidence="No explicit M8 live approval snapshot is present for this route.",
            detail=f"{route} remains live-disabled until route-specific approval evidence is durable.",
        ),
        _preflight_check(
            name="cap_guard_policy",
            category=AdminApiLivePreflightCategory.CAP_GUARD,
            status=AdminApiGateStatus.BLOCKED,
            owner=module_owner,
            evidence="Live cap and action-condition guard decisions are not yet wired as route-specific admission evidence.",
            detail="Guard, cap, wallet, position, and domain risk semantics must remain backend-owned before live enablement.",
        ),
        _preflight_check(
            name="live_execution_service",
            category=AdminApiLivePreflightCategory.LIVE_EXECUTION_SERVICE,
            status=AdminApiGateStatus.BLOCKED,
            owner=module_owner,
            evidence=f"{shared_method} is exposed only through the current live-disabled Admin API contract.",
            detail="No HTTP command route is admitted to live Coinbase execution in the enterprise Admin API path.",
        ),
        _preflight_check(
            name="post_live_reconciliation",
            category=AdminApiLivePreflightCategory.RECONCILIATION,
            status=AdminApiGateStatus.BLOCKED,
            owner=module_owner,
            evidence="Post-live reconciliation evidence is not wired for this route.",
            detail="A live path cannot be enabled until the exact route reports post-submit reconciliation evidence under cap.",
        ),
    ]


def _approval_snapshot_field(
    *,
    field: AdminApiLiveApprovalSnapshotField,
    expected_source: str,
    detail: str,
    expected_value: str | None = None,
) -> AdminLiveApprovalSnapshotRequiredFieldItem:
    return AdminLiveApprovalSnapshotRequiredFieldItem(
        field=field,
        status=AdminApiGateStatus.BLOCKED,
        required=True,
        expected_source=expected_source,
        expected_value=expected_value,
        detail=detail,
    )


def _live_approval_snapshot_evidence(
    *,
    method: str,
    route: str,
    module_id: str,
    identity_key: str,
    action_class: AdminApiActionClass,
    required_permission: AdminApiPermission | str,
) -> AdminLiveApprovalSnapshotEvidence:
    permission_value = (
        required_permission.value
        if isinstance(required_permission, AdminApiPermission)
        else str(required_permission)
    )
    fields = [
        _approval_snapshot_field(
            field=AdminApiLiveApprovalSnapshotField.ROUTE,
            expected_source="route_inventory",
            expected_value=route,
            detail="Approval must bind to the exact Admin API route.",
        ),
        _approval_snapshot_field(
            field=AdminApiLiveApprovalSnapshotField.METHOD,
            expected_source="route_inventory",
            expected_value=method,
            detail="Approval must bind to the exact HTTP method.",
        ),
        _approval_snapshot_field(
            field=AdminApiLiveApprovalSnapshotField.MODULE_ID,
            expected_source="route_inventory",
            expected_value=module_id,
            detail="Approval must bind to the backend-owned enterprise module id.",
        ),
        _approval_snapshot_field(
            field=AdminApiLiveApprovalSnapshotField.IDENTITY_KEY,
            expected_source="route_inventory",
            expected_value=identity_key,
            detail="Approval must bind to the module-specific command identity key.",
        ),
        _approval_snapshot_field(
            field=AdminApiLiveApprovalSnapshotField.IDENTITY_VALUE,
            expected_source="command_identity",
            detail="Approval must bind to the exact route or request identity value.",
        ),
        _approval_snapshot_field(
            field=AdminApiLiveApprovalSnapshotField.ACTION_CLASS,
            expected_source="route_inventory",
            expected_value=action_class.value,
            detail="Approval must bind to the live action class being requested.",
        ),
        _approval_snapshot_field(
            field=AdminApiLiveApprovalSnapshotField.REQUIRED_PERMISSION,
            expected_source="route_inventory",
            expected_value=permission_value,
            detail="Approval must name the backend permission required for the route.",
        ),
        _approval_snapshot_field(
            field=AdminApiLiveApprovalSnapshotField.REQUESTED_BY_ACTOR_ID,
            expected_source="authenticated_actor",
            detail="Approval must bind to the backend-authenticated requesting actor.",
        ),
        _approval_snapshot_field(
            field=AdminApiLiveApprovalSnapshotField.OPERATOR_INTENT,
            expected_source="command_headers",
            detail="Approval must bind to durable operator intent, not browser-only acknowledgement.",
        ),
        _approval_snapshot_field(
            field=AdminApiLiveApprovalSnapshotField.IDEMPOTENCY_KEY,
            expected_source="command_headers",
            detail="Approval must bind to the idempotency key for the submitted command.",
        ),
        _approval_snapshot_field(
            field=AdminApiLiveApprovalSnapshotField.PAYLOAD_HASH,
            expected_source="command_service",
            detail="Approval must bind to the command payload hash so payload drift is not approved.",
        ),
        _approval_snapshot_field(
            field=AdminApiLiveApprovalSnapshotField.APPROVED_BY_ACTOR_ID,
            expected_source="approval_store",
            detail="Approval must identify the backend-authenticated approver.",
        ),
        _approval_snapshot_field(
            field=AdminApiLiveApprovalSnapshotField.EXPIRES_AT,
            expected_source="approval_store",
            detail="Approval must expire and must not be treated as an evergreen browser switch.",
        ),
        _approval_snapshot_field(
            field=AdminApiLiveApprovalSnapshotField.CAP_GUARD_DECISION_REF,
            expected_source="guard_risk_policy",
            detail="Approval must bind to backend cap and guard decision evidence.",
        ),
        _approval_snapshot_field(
            field=AdminApiLiveApprovalSnapshotField.RECONCILIATION_PLAN_REF,
            expected_source="reconciliation_policy",
            detail="Approval must bind to post-live reconciliation evidence for the route.",
        ),
    ]
    return AdminLiveApprovalSnapshotEvidence(
        status=AdminApiGateStatus.BLOCKED,
        required=True,
        present=False,
        durable=False,
        route_specific=True,
        backend_owned=True,
        browser_authority="display_only",
        source="not_configured",
        required_field_count=len(fields),
        missing_required_field_count=len(fields),
        required_fields=fields,
        evidence=[
            "No durable route-specific approval snapshot is present.",
            "Approval must be backend-owned, route-specific, expiring, and payload-bound.",
            "Browser acknowledgement is not sufficient live execution approval.",
        ],
        detail=(
            f"{method} {route} remains live-disabled until a durable "
            "route-specific approval snapshot is present."
        ),
    )


def _approval_store_requirement(
    *,
    requirement: AdminApiLiveApprovalStoreRequirement,
    expected_source: str,
    detail: str,
    expected_value: str | None = None,
    status: AdminApiGateStatus = AdminApiGateStatus.PASSED,
) -> AdminLiveApprovalStoreRequirementItem:
    return AdminLiveApprovalStoreRequirementItem(
        requirement=requirement,
        status=status,
        required=True,
        expected_source=expected_source,
        expected_value=expected_value,
        detail=detail,
    )


def _live_approval_store_contract_evidence(
    *,
    method: str,
    route: str,
    module_id: str,
) -> AdminLiveApprovalStoreContractEvidence:
    requirements = [
        _approval_store_requirement(
            requirement=AdminApiLiveApprovalStoreRequirement.BACKEND_OWNED,
            expected_source="admin_api_approval_store",
            detail="Approval storage is owned by the backend approval store.",
        ),
        _approval_store_requirement(
            requirement=AdminApiLiveApprovalStoreRequirement.ROUTE_BOUND,
            expected_source="admin_api_approval_store",
            expected_value=route,
            detail="Approval records bind approval to the exact route.",
        ),
        _approval_store_requirement(
            requirement=AdminApiLiveApprovalStoreRequirement.METHOD_BOUND,
            expected_source="admin_api_approval_store",
            expected_value=method,
            detail="Approval records bind approval to the exact HTTP method.",
        ),
        _approval_store_requirement(
            requirement=AdminApiLiveApprovalStoreRequirement.MODULE_BOUND,
            expected_source="admin_api_approval_store",
            expected_value=module_id,
            detail="Approval records bind approval to the enterprise module id.",
        ),
        _approval_store_requirement(
            requirement=AdminApiLiveApprovalStoreRequirement.ACTOR_BOUND,
            expected_source="admin_api_approval_store",
            detail=(
                "Approval records store the backend-authenticated approving "
                "actor and bind the requesting actor for resolver checks."
            ),
        ),
        _approval_store_requirement(
            requirement=AdminApiLiveApprovalStoreRequirement.IDEMPOTENCY_BOUND,
            expected_source="admin_api_approval_store",
            detail="Approval records bind to the command idempotency key.",
        ),
        _approval_store_requirement(
            requirement=AdminApiLiveApprovalStoreRequirement.PAYLOAD_HASH_BOUND,
            expected_source="admin_api_approval_store",
            detail="Approval records bind to the submitted command payload hash.",
        ),
        _approval_store_requirement(
            requirement=AdminApiLiveApprovalStoreRequirement.EXPIRING,
            expected_source="admin_api_approval_store",
            detail="Approval records have explicit expiry and reject evergreen approval.",
        ),
        _approval_store_requirement(
            requirement=AdminApiLiveApprovalStoreRequirement.CAP_GUARD_BOUND,
            expected_source="admin_api_approval_store",
            detail="Approval records bind to backend cap and guard decision evidence references.",
        ),
        _approval_store_requirement(
            requirement=AdminApiLiveApprovalStoreRequirement.RECONCILIATION_BOUND,
            expected_source="admin_api_approval_store",
            detail="Approval records bind to planned post-live reconciliation evidence references.",
        ),
        _approval_store_requirement(
            requirement=AdminApiLiveApprovalStoreRequirement.APPEND_ONLY_AUDIT,
            expected_source="admin_api_approval_store",
            detail="Approval records are stored as append-only JSONL evidence.",
        ),
        _approval_store_requirement(
            requirement=AdminApiLiveApprovalStoreRequirement.BROWSER_AUTHORITY_REJECTED,
            expected_source="frontend_boundary",
            expected_value="display_only",
            detail="Approval storage must reject browser-only acknowledgement as live authority.",
        ),
    ]
    return AdminLiveApprovalStoreContractEvidence(
        status=AdminApiGateStatus.PASSED,
        required=True,
        configured=True,
        durable=True,
        backend_owned=True,
        browser_authority="display_only",
        source="admin_api_approval_store",
        requirement_count=len(requirements),
        missing_requirement_count=sum(
            1 for requirement in requirements if requirement.status != AdminApiGateStatus.PASSED
        ),
        requirements=requirements,
        evidence=[
            "Durable backend approval store contract is implemented.",
            "Approval records are backend-owned, route-bound, expiring, payload-bound, and append-only.",
            "No approval mutation endpoint or browser approval authority is exposed by this evidence.",
        ],
        detail=(
            f"{method} {route} has a durable approval store contract, but "
            "remains live-disabled until a route-specific approval snapshot, "
            "cap/guard decision, full admission audit trail, and reconciliation "
            "plan are linked."
        ),
    )


def _admission_audit_fact(
    *,
    fact: AdminApiLiveAdmissionAuditFact,
    expected_source: str,
    detail: str,
    expected_value: str | None = None,
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED,
) -> AdminLiveAdmissionAuditFactItem:
    return AdminLiveAdmissionAuditFactItem(
        fact=fact,
        status=status,
        required=True,
        expected_source=expected_source,
        expected_value=expected_value,
        detail=detail,
    )


def _live_admission_audit_trail_evidence(
    *,
    method: str,
    route: str,
    module_id: str,
    identity_key: str,
) -> AdminLiveAdmissionAuditTrailEvidence:
    facts = [
        _admission_audit_fact(
            fact=AdminApiLiveAdmissionAuditFact.ROUTE_ADMISSION_REQUESTED,
            expected_source="route_inventory",
            expected_value=f"{method} {route}",
            detail="Audit trail must record the exact route admission request.",
        ),
        _admission_audit_fact(
            fact=AdminApiLiveAdmissionAuditFact.APPROVAL_SNAPSHOT_LINKED,
            expected_source="approval_snapshot",
            detail="Audit trail must link the route-specific approval snapshot used for admission.",
        ),
        _admission_audit_fact(
            fact=AdminApiLiveAdmissionAuditFact.APPROVAL_STORE_DECISION_LINKED,
            expected_source="approval_store",
            detail=(
                "Audit trail must link the backend approval-store decision, "
                "approving actor, and requesting actor."
            ),
        ),
        _admission_audit_fact(
            fact=AdminApiLiveAdmissionAuditFact.CAP_GUARD_DECISION_LINKED,
            expected_source="guard_risk_policy",
            detail="Audit trail must link backend cap, wallet, position, and domain guard decisions.",
        ),
        _admission_audit_fact(
            fact=AdminApiLiveAdmissionAuditFact.PAYLOAD_HASH_LINKED,
            expected_source="command_service",
            detail="Audit trail must bind the admitted command to the submitted payload hash.",
        ),
        _admission_audit_fact(
            fact=AdminApiLiveAdmissionAuditFact.IDENTITY_KEY_LINKED,
            expected_source="route_inventory",
            expected_value=identity_key,
            detail="Audit trail must bind the command to the module-specific identity key.",
        ),
        _admission_audit_fact(
            fact=AdminApiLiveAdmissionAuditFact.COMMAND_ADMISSION_DECISION_RECORDED,
            expected_source="admin_api_audit_log",
            expected_value=module_id,
            detail="Append-only Admin API audit records now store the backend admission decision before Coinbase submission.",
            status=AdminApiGateStatus.PASSED,
        ),
        _admission_audit_fact(
            fact=AdminApiLiveAdmissionAuditFact.EXCHANGE_SUBMISSION_LINKED,
            expected_source="coinbase_adapter",
            detail="Audit trail must link the exchange submission result when live execution is admitted.",
        ),
        _admission_audit_fact(
            fact=AdminApiLiveAdmissionAuditFact.RECONCILIATION_RESULT_LINKED,
            expected_source="reconciliation_policy",
            detail="Audit trail must link post-live reconciliation evidence for the admitted route.",
        ),
        _admission_audit_fact(
            fact=AdminApiLiveAdmissionAuditFact.BROWSER_AUTHORITY_REJECTION_RECORDED,
            expected_source="frontend_boundary",
            expected_value="display_only",
            detail="Audit trail must record that browser acknowledgement is not live authority.",
        ),
    ]
    missing_fact_count = sum(
        1 for fact in facts if fact.status != AdminApiGateStatus.PASSED
    )
    return AdminLiveAdmissionAuditTrailEvidence(
        status=AdminApiGateStatus.BLOCKED,
        required=True,
        configured=False,
        append_only=True,
        backend_owned=True,
        browser_authority="display_only",
        source="admin_api_audit_log_partial",
        fact_count=len(facts),
        missing_fact_count=missing_fact_count,
        facts=facts,
        evidence=[
            "Command admission decisions are recorded in the append-only Admin API audit log.",
            "Full live admission remains blocked until approval, cap/guard, exchange submission, and reconciliation facts are linked.",
            "Browser evidence remains display-only and cannot write or satisfy admission audit facts.",
        ],
        detail=(
            f"{method} {route} remains live-disabled until the backend can "
            "write and verify the full append-only live-admission audit trail."
        ),
    )


def _cap_guard_domain_detail(module_id: str, route: str) -> str:
    if module_id == "spot_operations":
        if "campaign" in route:
            return (
                "Spot campaign guard must bind sweep/campaign caps, dry-run "
                "policy, product eligibility, wallet authority, SELL inventory "
                "authority, and reconciliation readiness to the submitted payload."
            )
        if route.endswith("/cancel"):
            return (
                "Spot cancel guard must bind client_order_id ownership, active "
                "placement evidence, idempotency, and no order_id substitution "
                "before a live cancel can be admitted."
            )
        return (
            "Spot order guard must bind notional caps, product capability, "
            "wallet budget, no-shorting SELL inventory authority, cost-basis "
            "policy, and manual live acknowledgement to the submitted payload."
        )
    if module_id == "stealth_orders":
        return (
            "Stealth cancel guard must bind stealth_order_id, active exchange "
            "placement reality, cancel/re-entry policy, and lifecycle lock "
            "evidence before a live cancel can be admitted."
        )
    if module_id == "movement_repricing":
        return (
            "Movement/repricing guard must bind stealth_order_id, mutation "
            "claim, cancel/replace policy, replacement budget delta, and "
            "exchange-reality evidence before live repricing can be admitted."
        )
    return (
        "Module-specific guard semantics must be defined by the owning backend "
        "module before live admission."
    )


def _cap_guard_requirement(
    *,
    requirement: AdminApiLiveCapGuardRequirement,
    expected_source: str,
    detail: str,
    expected_value: str | None = None,
) -> AdminLiveCapGuardRequirementItem:
    return AdminLiveCapGuardRequirementItem(
        requirement=requirement,
        status=AdminApiGateStatus.BLOCKED,
        required=True,
        expected_source=expected_source,
        expected_value=expected_value,
        detail=detail,
    )


def _live_cap_guard_contract_evidence(
    *,
    method: str,
    route: str,
    module_id: str,
    identity_key: str,
) -> AdminLiveCapGuardContractEvidence:
    requirements = [
        _cap_guard_requirement(
            requirement=AdminApiLiveCapGuardRequirement.BACKEND_OWNED,
            expected_source="guard_risk_policy",
            detail="Cap and guard decisions must be owned and enforced by the backend.",
        ),
        _cap_guard_requirement(
            requirement=AdminApiLiveCapGuardRequirement.ROUTE_BOUND,
            expected_source="route_inventory",
            expected_value=route,
            detail="Cap and guard decisions must bind to the exact Admin API route.",
        ),
        _cap_guard_requirement(
            requirement=AdminApiLiveCapGuardRequirement.METHOD_BOUND,
            expected_source="route_inventory",
            expected_value=method,
            detail="Cap and guard decisions must bind to the exact HTTP method.",
        ),
        _cap_guard_requirement(
            requirement=AdminApiLiveCapGuardRequirement.MODULE_BOUND,
            expected_source="route_inventory",
            expected_value=module_id,
            detail="Cap and guard decisions must bind to the enterprise module id.",
        ),
        _cap_guard_requirement(
            requirement=AdminApiLiveCapGuardRequirement.IDENTITY_BOUND,
            expected_source="route_inventory",
            expected_value=identity_key,
            detail="Cap and guard decisions must bind to the module-specific command identity.",
        ),
        _cap_guard_requirement(
            requirement=AdminApiLiveCapGuardRequirement.PAYLOAD_HASH_BOUND,
            expected_source="command_service",
            detail="Cap and guard decisions must bind to the submitted command payload hash.",
        ),
        _cap_guard_requirement(
            requirement=AdminApiLiveCapGuardRequirement.IDEMPOTENCY_BOUND,
            expected_source="command_headers",
            detail="Cap and guard decisions must bind to the command idempotency key.",
        ),
        _cap_guard_requirement(
            requirement=AdminApiLiveCapGuardRequirement.OPERATOR_INTENT_BOUND,
            expected_source="command_headers",
            detail="Cap and guard decisions must bind to backend-captured operator intent.",
        ),
        _cap_guard_requirement(
            requirement=AdminApiLiveCapGuardRequirement.NOTIONAL_CAP_BOUND,
            expected_source="guard_risk_policy",
            expected_value=LIVE_ENABLEMENT_MAX_SUBMITTED_NOTIONAL_USDC,
            detail="Cap and guard decisions must enforce approved submitted/executed notional caps.",
        ),
        _cap_guard_requirement(
            requirement=AdminApiLiveCapGuardRequirement.DOMAIN_GUARD_BOUND,
            expected_source="guard_risk_policy",
            detail=_cap_guard_domain_detail(module_id, route),
        ),
        _cap_guard_requirement(
            requirement=AdminApiLiveCapGuardRequirement.PRODUCT_SCOPE_BOUND,
            expected_source="route_inventory",
            expected_value=LIVE_ENABLEMENT_PRODUCT_SCOPE,
            detail="Cap and guard decisions must bind to the configured product scope for the route.",
        ),
        _cap_guard_requirement(
            requirement=AdminApiLiveCapGuardRequirement.APPROVAL_SNAPSHOT_BOUND,
            expected_source="approval_snapshot",
            detail="Cap and guard decisions must be referenced by the route-specific approval snapshot.",
        ),
        _cap_guard_requirement(
            requirement=AdminApiLiveCapGuardRequirement.ADMISSION_AUDIT_BOUND,
            expected_source="admission_audit_trail",
            detail="Cap and guard decisions must be recorded in the append-only admission audit trail.",
        ),
        _cap_guard_requirement(
            requirement=AdminApiLiveCapGuardRequirement.BROWSER_AUTHORITY_REJECTED,
            expected_source="frontend_boundary",
            expected_value="display_only",
            detail="Cap and guard decisions must reject browser-computed authority.",
        ),
    ]
    return AdminLiveCapGuardContractEvidence(
        status=AdminApiGateStatus.BLOCKED,
        required=True,
        configured=False,
        route_specific=True,
        backend_owned=True,
        browser_authority="display_only",
        source="not_configured",
        requirement_count=len(requirements),
        missing_requirement_count=len(requirements),
        requirements=requirements,
        evidence=[
            "No route-specific backend cap/guard decision contract is configured for this route.",
            "Cap/guard decisions must be backend-owned, route-bound, payload-bound, approval-linked, and admission-audit-linked.",
            "Browser-side wallet, margin, profitability, or cap calculations cannot satisfy live admission guards.",
        ],
        detail=(
            f"{method} {route} remains live-disabled until a route-specific "
            "backend cap/guard decision contract is implemented and configured."
        ),
    )


def _live_readiness_precondition(
    *,
    precondition: AdminApiLiveReadinessPrecondition,
    status: AdminApiGateStatus,
    configured: bool,
    source: str,
    expected_source: str,
    detail: str,
    blocker: AdminApiLiveAdmissionBlocker | None = None,
    evidence: list[str] | None = None,
) -> AdminLiveReadinessPreconditionItem:
    blocking = status == AdminApiGateStatus.BLOCKED
    return AdminLiveReadinessPreconditionItem(
        precondition=precondition,
        status=status,
        required=True,
        configured=configured,
        blocking=blocking,
        backend_owned=True,
        route_bound=True,
        source=source,
        expected_source=expected_source,
        blocker=blocker if blocking else None,
        browser_authority="display_only",
        bff_authority="forward_only_no_execution",
        evidence=list(evidence or []),
        detail=detail,
    )


def _live_readiness_preconditions(
    *,
    method: str,
    route: str,
    shared_method: str,
    approval_snapshot: AdminLiveApprovalSnapshotEvidence,
    approval_store_contract: AdminLiveApprovalStoreContractEvidence,
    admission_audit_trail: AdminLiveAdmissionAuditTrailEvidence,
    cap_guard_contract: AdminLiveCapGuardContractEvidence,
    live_execution_adapter: dict[str, Any],
) -> list[AdminLiveReadinessPreconditionItem]:
    adapter_configured = bool(live_execution_adapter.get("configured"))
    adapter_source = str(live_execution_adapter.get("source") or "not_configured")
    adapter_status = AdminApiGateStatus.PASSED if adapter_configured else AdminApiGateStatus.BLOCKED
    return [
        _live_readiness_precondition(
            precondition=AdminApiLiveReadinessPrecondition.APPROVAL_STORE_CONTRACT,
            status=approval_store_contract.status,
            configured=approval_store_contract.configured,
            source=approval_store_contract.source,
            expected_source="admin_api_approval_store",
            detail=approval_store_contract.detail,
            blocker=(
                None
                if approval_store_contract.configured
                else AdminApiLiveAdmissionBlocker.APPROVAL_STORE_MISSING
            ),
            evidence=approval_store_contract.evidence,
        ),
        _live_readiness_precondition(
            precondition=AdminApiLiveReadinessPrecondition.APPROVAL_SNAPSHOT,
            status=approval_snapshot.status,
            configured=approval_snapshot.present,
            source=approval_snapshot.source,
            expected_source="approval_snapshot",
            detail=approval_snapshot.detail,
            blocker=AdminApiLiveAdmissionBlocker.APPROVAL_SNAPSHOT_MISSING,
            evidence=approval_snapshot.evidence,
        ),
        _live_readiness_precondition(
            precondition=AdminApiLiveReadinessPrecondition.ADMISSION_AUDIT_TRAIL,
            status=admission_audit_trail.status,
            configured=admission_audit_trail.configured,
            source=admission_audit_trail.source,
            expected_source="admin_api_audit_log",
            detail=admission_audit_trail.detail,
            blocker=AdminApiLiveAdmissionBlocker.ADMISSION_AUDIT_MISSING,
            evidence=admission_audit_trail.evidence,
        ),
        _live_readiness_precondition(
            precondition=AdminApiLiveReadinessPrecondition.CAP_GUARD_CONTRACT,
            status=cap_guard_contract.status,
            configured=cap_guard_contract.configured,
            source=cap_guard_contract.source,
            expected_source="guard_risk_policy",
            detail=cap_guard_contract.detail,
            blocker=AdminApiLiveAdmissionBlocker.CAP_GUARD_MISSING,
            evidence=cap_guard_contract.evidence,
        ),
        _live_readiness_precondition(
            precondition=AdminApiLiveReadinessPrecondition.RECONCILIATION_PLAN,
            status=AdminApiGateStatus.BLOCKED,
            configured=False,
            source="not_configured",
            expected_source="reconciliation_policy",
            detail=(
                f"{method} {route} remains live-disabled until a route-specific "
                "post-live reconciliation plan is linked to approval, audit, "
                "and cap/guard evidence."
            ),
            blocker=AdminApiLiveAdmissionBlocker.RECONCILIATION_PLAN_MISSING,
            evidence=[
                "Reconciliation plan proof is required before live execution.",
                "The plan must be route-bound and payload-bound through backend evidence.",
            ],
        ),
        _live_readiness_precondition(
            precondition=AdminApiLiveReadinessPrecondition.LIVE_EXECUTION_ADAPTER,
            status=adapter_status,
            configured=adapter_configured,
            source=adapter_source,
            expected_source=f"AdminApiCommandService.{shared_method}",
            detail=str(live_execution_adapter.get("detail") or ""),
            blocker=(
                None
                if adapter_configured
                else AdminApiLiveAdmissionBlocker.LIVE_EXECUTION_DISABLED
            ),
            evidence=[
                str(item)
                for item in live_execution_adapter.get("evidence", [])
            ],
        ),
        _live_readiness_precondition(
            precondition=AdminApiLiveReadinessPrecondition.EXECUTION_INTENT_ENVELOPE,
            status=AdminApiGateStatus.PASSED,
            configured=True,
            source="command_admission",
            expected_source=f"AdminApiCommandService.{shared_method}",
            detail=(
                f"{method} {route} command admissions expose backend-owned "
                "execution intent evidence, but the intent remains "
                "non-executable while live execution is disabled."
            ),
            evidence=[
                "Execution intent binds route, actor, idempotency key, operator intent, and payload hash.",
                "Intent evidence is display-only and cannot be used by the browser or BFF as execution authority.",
            ],
        ),
        _live_readiness_precondition(
            precondition=AdminApiLiveReadinessPrecondition.BROWSER_BFF_BOUNDARY,
            status=AdminApiGateStatus.PASSED,
            configured=True,
            source="frontend_boundary",
            expected_source="backend_contract",
            detail=(
                "Browser and BFF authority is display-only/forward-only and "
                "cannot satisfy live admission or execute Coinbase orders."
            ),
            evidence=[
                "Browser authority remains display_only.",
                "BFF command forwarding remains forward_only_no_execution.",
            ],
        ),
        _live_readiness_precondition(
            precondition=AdminApiLiveReadinessPrecondition.LIVE_EXECUTION_SERVICE,
            status=AdminApiGateStatus.BLOCKED,
            configured=False,
            source=DISABLED_LIVE_EXECUTION_SERVICE_SOURCE,
            expected_source="admin_api_live_execution_service",
            detail=(
                f"{method} {route} is still bound to the disabled backend "
                "live execution service; no Coinbase adapter may run."
            ),
            blocker=AdminApiLiveAdmissionBlocker.LIVE_EXECUTION_DISABLED,
            evidence=[
                "The backend live execution service is intentionally disabled.",
                "No create, cancel, submit, execute, or Coinbase client method is exposed.",
            ],
        ),
    ]


def _path_id(method: str, path: str) -> str:
    normalized = path.strip("/").replace("/", ".").replace("{", "").replace("}", "")
    return f"{method.lower()}.{normalized}"


def _order_item_from_row(row: dict[str, Any]) -> AdminOrderReadItem:
    return AdminOrderReadItem(
        client_order_id=str(row.get("client_order_id") or ""),
        product_id=_string_or_none(row.get("product_id")),
        side=_string_or_none(row.get("side")),
        status=_string_or_none(row.get("status")),
        order_type=_string_or_none(row.get("order_type")),
        size=_string_or_none(row.get("size")),
        price=_string_or_none(row.get("price")),
        parent_client_order_id=_string_or_none(row.get("parent_order_id")),
        created_at=_string_or_none(row.get("created_at")),
        updated_at=_string_or_none(row.get("updated_at")),
        exchange_order_id=_string_or_none(
            row.get("exchange_order_id")
            or row.get("coinbase_order_id")
            or row.get("active_exchange_order_id")
        ),
        correlation_id=_string_or_none(row.get("correlation_id")),
        audit_id=_string_or_none(row.get("audit_id")),
    )


def _json_object_or_none(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return {"raw": value}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    return {"value": value}


def _json_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [
            dict(item) if isinstance(item, dict) else {"value": item}
            for item in value
        ]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return [{"raw": value}]
        if isinstance(parsed, list):
            return [
                dict(item) if isinstance(item, dict) else {"value": item}
                for item in parsed
            ]
        return [{"value": parsed}]
    return [{"value": value}]


def _stealth_item_from_row(row: dict[str, Any]) -> AdminStealthOrderReadItem:
    revealed_orders = _json_list(row.get("revealed_orders"))
    anchor_state = _json_object_or_none(row.get("anchor_repricing_state_json")) or {}
    active_placement_client_order_id = _string_or_none(
        anchor_state.get("active_placement_client_order_id")
        or anchor_state.get("active_placement_order_id")
        or anchor_state.get("active_placed_order_id")
    )
    active_exchange_order_id = _string_or_none(
        anchor_state.get("active_exchange_order_id")
    )
    return AdminStealthOrderReadItem(
        stealth_order_id=str(row.get("stealth_order_id") or ""),
        parent_stealth_order_id=_string_or_none(row.get("parent_order_id")),
        product_id=_string_or_none(row.get("product_id")),
        side=_string_or_none(row.get("side")),
        status=_string_or_none(row.get("status")),
        total_size=_string_or_none(row.get("total_size")),
        revealed_size=_string_or_none(row.get("revealed_size")),
        remaining_size=_string_or_none(row.get("remaining_size")),
        executed_size=_string_or_none(row.get("executed_size")),
        limit_price=_string_or_none(row.get("limit_price")),
        target_movement=_string_or_none(row.get("target_movement")),
        target_movement_type=_string_or_none(row.get("target_movement_type")),
        visibility_score=_string_or_none(row.get("visibility_score")),
        reveal_condition_type=_string_or_none(row.get("reveal_condition_type")),
        reveal_condition=_json_object_or_none(row.get("reveal_condition_json")),
        sizing_strategy=_json_object_or_none(row.get("sizing_strategy_json")),
        revealed_orders=revealed_orders,
        active_placement_client_order_id=active_placement_client_order_id,
        active_exchange_order_id=active_exchange_order_id,
        last_placement_at=_string_or_none(row.get("last_placement_at")),
        last_lifecycle_event=_string_or_none(row.get("last_lifecycle_event")),
        failure_reason=_string_or_none(row.get("failure_reason")),
        cancel_reentry_policy=_json_object_or_none(row.get("cancel_reentry_policy_json")),
        cancel_reentry_state=_json_object_or_none(row.get("cancel_reentry_state_json")),
        post_fill_retreat_policy=_json_object_or_none(row.get("post_fill_retreat_policy_json")),
        anchor_repricing_policy=_json_object_or_none(row.get("anchor_repricing_policy_json")),
        anchor_repricing_state=anchor_state,
        created_at=_string_or_none(row.get("created_at")),
        updated_at=_string_or_none(row.get("updated_at")),
    )


def _stealth_active_placement_audit(
    item: AdminStealthOrderReadItem,
) -> AdminStealthActivePlacementAuditEvidence:
    active_placement_present = bool(item.active_placement_client_order_id)
    required_contracts = [
        "stealth_active_placement_exchange_truth_snapshot_contract",
        "stealth_active_placement_exchange_truth_proof_contract",
        "stealth_active_placement_cancel_replace_audit",
        "stealth_active_placement_reconciliation_proof",
    ]
    blockers = [
        "coinbase_exchange_truth_read_disabled",
        "stealth_active_placement_cancel_replace_audit_missing",
        "stealth_active_placement_reconciliation_proof_missing",
    ]
    if not active_placement_present:
        blockers.insert(0, "active_placement_local_evidence_missing")

    detail = (
        "Active placement evidence is local stealth state only. It can explain "
        "why cancel, move, and reprice remain blocked, but it does not verify "
        "Coinbase exchange truth, cancel or replace orders, or allow lifecycle "
        "mutation."
    )
    return AdminStealthActivePlacementAuditEvidence(
        stealth_order_id=item.stealth_order_id,
        status=AdminApiGateStatus.BLOCKED,
        active_placement_present=active_placement_present,
        active_placement_client_order_id=item.active_placement_client_order_id,
        active_exchange_order_id=item.active_exchange_order_id,
        exchange_order_id_evidence_only=True,
        exchange_truth_verified=False,
        exchange_truth_source="local_stealth_state_only",
        coinbase_read_required=True,
        coinbase_read_ran=False,
        coinbase_order_cancel_submitted=False,
        lifecycle_mutation_allowed=False,
        required_for_mutation_families=[
            AdminApiMutationFamilyType.STEALTH_CANCEL,
            AdminApiMutationFamilyType.STEALTH_MOVE,
            AdminApiMutationFamilyType.MOVEMENT_REPRICE,
        ],
        read_evidence_routes=[
            "/api/v1/stealth/orders/{stealth_order_id}",
            (
                "/api/v1/stealth/orders/{stealth_order_id}/active-placement/"
                "exchange-truth-proof"
            ),
            "/api/v1/stealth/command-suite",
        ],
        required_contracts=required_contracts,
        missing_contracts=required_contracts,
        blockers=blockers,
        browser_authority="display_only",
        bff_authority="forward_only_no_execution",
        detail=detail,
    )


def _stealth_mutation_claim_audit(
    stealth_order_id: str,
) -> AdminStealthMutationClaimAuditEvidence:
    claims = _runtime_mutation_claims_for(stealth_order_id)
    runtime_claims_observed = any(claim.runtime_observed for claim in claims)
    active_claim_count = sum(1 for claim in claims if claim.state == "processing")
    claim_reader_source = (
        claims[0].source if claims else "runtime_stealth_manager_unavailable"
    )
    required_contracts = [
        "stealth_move_mutation_claim_snapshot_contract",
        "stealth_reprice_cooldown_claim_contract",
    ]
    blockers = [
        "stealth_move_mutation_claim_snapshot_contract_missing",
        "stealth_reprice_cooldown_claim_contract_missing",
    ]
    if not runtime_claims_observed:
        blockers.insert(0, "runtime_mutation_claim_snapshot_unavailable")

    return AdminStealthMutationClaimAuditEvidence(
        stealth_order_id=stealth_order_id,
        status=AdminApiGateStatus.BLOCKED,
        runtime_claims=claims,
        runtime_claims_observed=runtime_claims_observed,
        runtime_claim_count=len(claims),
        active_claim_count=active_claim_count,
        claim_reader_source=claim_reader_source,
        claim_reader_ran=claim_reader_source != "runtime_stealth_manager_unavailable",
        coinbase_read_ran=False,
        coinbase_order_cancel_submitted=False,
        lifecycle_mutation_allowed=False,
        required_for_mutation_families=[
            AdminApiMutationFamilyType.STEALTH_MOVE,
            AdminApiMutationFamilyType.MOVEMENT_REPRICE,
        ],
        read_evidence_routes=[
            "/api/v1/stealth/orders/{stealth_order_id}",
            "/api/v1/movement-repricing/stealth/{stealth_order_id}",
            "/api/v1/stealth/command-suite",
        ],
        required_contracts=required_contracts,
        missing_contracts=list(required_contracts),
        blockers=blockers,
        browser_authority="display_only",
        bff_authority="forward_only_no_execution",
        detail=(
            "Mutation-claim audit reuses the existing runtime claim reader as "
            "local evidence only. It does not acquire or release claims, call "
            "Coinbase, execute cancel/replace, mutate lifecycle state, or "
            "authorize browser/BFF execution."
        ),
    )


def _stealth_reveal_trigger_audit(
    item: AdminStealthOrderReadItem,
) -> AdminStealthRevealTriggerAuditEvidence:
    required_contracts = ["stealth_reveal_trigger_guard"]
    reveal_condition_present = bool(
        item.reveal_condition_type or item.reveal_condition
    )
    blockers = ["stealth_reveal_trigger_guard_missing"]
    if not reveal_condition_present:
        blockers.insert(0, "reveal_condition_local_evidence_missing")

    return AdminStealthRevealTriggerAuditEvidence(
        stealth_order_id=item.stealth_order_id,
        status=AdminApiGateStatus.BLOCKED,
        reveal_condition_present=reveal_condition_present,
        reveal_condition_type=item.reveal_condition_type,
        reveal_condition=item.reveal_condition,
        trigger_state_source="local_stealth_row_only",
        trigger_evaluation_ran=False,
        should_trigger_reveal_called=False,
        reveal_order_slice_called=False,
        coinbase_order_submit_ran=False,
        lifecycle_mutation_allowed=False,
        required_for_mutation_families=[AdminApiMutationFamilyType.STEALTH_REVEAL],
        read_evidence_routes=[
            "/api/v1/stealth/orders/{stealth_order_id}",
            "/api/v1/stealth/command-suite",
        ],
        required_contracts=required_contracts,
        missing_contracts=list(required_contracts),
        blockers=blockers,
        browser_authority="display_only",
        bff_authority="forward_only_no_execution",
        detail=(
            "Reveal-trigger audit reports local reveal condition evidence only. "
            "It does not evaluate live triggers, call should_trigger_reveal, "
            "call reveal_order_slice, submit Coinbase orders, mutate lifecycle "
            "state, or authorize browser/BFF execution."
        ),
    )


def _stealth_reveal_submission_audit(
    item: AdminStealthOrderReadItem,
) -> AdminStealthRevealSubmissionAuditEvidence:
    required_contracts = [
        "stealth_reveal_exchange_submission_adapter",
        "stealth_reveal_reconciliation_proof",
    ]
    existing_active_placement_present = bool(item.active_placement_client_order_id)
    blockers = [
        "stealth_reveal_exchange_submission_adapter_missing",
        "stealth_reveal_reconciliation_proof_missing",
        "live_execution_disabled",
    ]
    if existing_active_placement_present:
        blockers.insert(0, "existing_active_placement_local_evidence_present")

    return AdminStealthRevealSubmissionAuditEvidence(
        stealth_order_id=item.stealth_order_id,
        status=AdminApiGateStatus.BLOCKED,
        command_route="/api/v1/stealth/orders/{stealth_order_id}/reveal",
        service_method="reveal_stealth_order_by_stealth_order_id",
        reveal_manager_method="core/stealth_order_manager.py::reveal_order_slice",
        submission_adapter_configured=False,
        route_bound=True,
        backend_owned=True,
        existing_active_placement_present=existing_active_placement_present,
        active_placement_client_order_id=item.active_placement_client_order_id,
        active_exchange_order_id=item.active_exchange_order_id,
        exchange_order_id_evidence_only=True,
        reveal_order_slice_called=False,
        coinbase_order_submit_ran=False,
        coinbase_order_cancel_submitted=False,
        live_coinbase_read_ran=False,
        active_placement_created=False,
        lifecycle_mutation_allowed=False,
        reconciliation_required=True,
        reconciliation_executed=False,
        required_for_mutation_families=[AdminApiMutationFamilyType.STEALTH_REVEAL],
        read_evidence_routes=[
            "/api/v1/stealth/orders/{stealth_order_id}",
            "/api/v1/stealth/command-suite",
        ],
        required_contracts=required_contracts,
        missing_contracts=list(required_contracts),
        blockers=blockers,
        browser_authority="display_only",
        bff_authority="forward_only_no_execution",
        detail=(
            "Reveal submission-adapter audit maps the future backend-owned "
            "reveal path and local active-placement evidence only. It does "
            "not call reveal_order_slice, submit Coinbase orders, cancel "
            "placements, create active placements, mutate lifecycle state, "
            "execute reconciliation, or authorize browser/BFF execution."
        ),
    )


def _stealth_reveal_reconciliation_audit(
    item: AdminStealthOrderReadItem,
) -> AdminStealthRevealReconciliationAuditEvidence:
    required_contracts = ["stealth_reveal_reconciliation_proof"]
    blockers = [
        "stealth_reveal_reconciliation_proof_missing",
        "coinbase_exchange_truth_read_disabled",
    ]
    if not item.active_placement_client_order_id:
        blockers.insert(0, "active_placement_local_evidence_missing")

    return AdminStealthRevealReconciliationAuditEvidence(
        stealth_order_id=item.stealth_order_id,
        status=AdminApiGateStatus.BLOCKED,
        command_route="/api/v1/stealth/orders/{stealth_order_id}/reveal",
        reconciliation_required=True,
        reconciliation_plan_required=True,
        reconciliation_proof_required=True,
        reconciliation_plan_resolved=False,
        reconciliation_proof_resolved=False,
        reconciliation_plan_id=None,
        reconciliation_proof_id=None,
        active_placement_client_order_id=item.active_placement_client_order_id,
        active_exchange_order_id=item.active_exchange_order_id,
        exchange_order_id_evidence_only=True,
        coinbase_read_ran=False,
        reconciliation_executed=False,
        order_state_mutated=False,
        lifecycle_mutation_allowed=False,
        post_submit_reconciliation_satisfied=False,
        required_for_mutation_families=[AdminApiMutationFamilyType.STEALTH_REVEAL],
        read_evidence_routes=[
            "/api/v1/stealth/orders/{stealth_order_id}",
            "/api/v1/stealth/command-suite",
            "/api/v1/admin/reconciliation/plans",
        ],
        required_contracts=required_contracts,
        missing_contracts=list(required_contracts),
        blockers=blockers,
        browser_authority="display_only",
        bff_authority="forward_only_no_execution",
        detail=(
            "Reveal reconciliation audit reports missing backend-owned "
            "post-submit reconciliation proof for the reveal workflow. It "
            "does not read Coinbase, resolve reconciliation plans, write "
            "proof records, execute reconciliation, mutate order or lifecycle "
            "state, or authorize browser/BFF reveal execution."
        ),
    )


def _stealth_create_lifecycle_write_audit(
    *,
    required_gate_chain: list[str],
    missing_gate_chain: list[str],
    proof_routes: list[StealthCommandSuiteProofRouteItem],
) -> StealthCreateLifecycleWriteAuditEvidence:
    required_contracts = [
        "stealth_create_guard_contract",
        "stealth_create_admission_audit",
        "stealth_create_reconciliation_plan",
        "stealth_create_lifecycle_write_guard_proof",
        "stealth_create_lifecycle_write_execution_contract",
    ]
    blockers = [
        "stealth_create_lifecycle_write_guard_proof_missing",
        "stealth_create_lifecycle_write_execution_contract_missing",
        "stealth_create_guard_contract_missing",
        "stealth_create_admission_audit_missing",
        "stealth_create_reconciliation_plan_missing",
        "live_execution_disabled",
    ]
    return StealthCreateLifecycleWriteAuditEvidence(
        accepted_command_identity_keys=["stealth_order_id"],
        rejected_command_identity_keys=[
            "client_order_id",
            "active_placement_client_order_id",
            "exchange_order_id",
            "order_id",
        ],
        read_evidence_routes=[
            "/api/v1/stealth/orders",
            "/api/v1/stealth/orders/{stealth_order_id}/lifecycle-write-guard-proof",
            "/api/v1/stealth/command-suite",
            "/api/v1/admin/reconciliation/plans",
        ],
        lifecycle_write_contract_configured=True,
        required_contracts=required_contracts,
        missing_contracts=list(required_contracts),
        blockers=blockers,
        required_gate_chain=list(required_gate_chain),
        missing_gate_chain=list(missing_gate_chain),
        execution_contract=build_stealth_create_lifecycle_write_execution_contract(
            stealth_order_id=None,
            exact_command_context_present=False,
        ),
        proof_route_count=len(proof_routes),
        blocking_proof_route_count=sum(1 for route in proof_routes if route.blocking),
        proof_routes=proof_routes,
        evidence=[
            "Stealth create is exposed as a live-disabled Admin API command draft.",
            "Future execution must call the existing StealthOrderManager create path.",
            "This audit does not write stealth rows, order_parent rows, lifecycle events, or reconciliation evidence.",
            "This audit does not create approval, admission-audit, cap/guard, or reconciliation proof records.",
            "Browser and BFF surfaces remain display/forward only and cannot grant lifecycle-write authority.",
        ],
        detail=(
            "Create lifecycle-write evidence is read-only command-suite "
            "evidence. It records the missing backend contracts required "
            "before POST /api/v1/stealth/orders can invoke the existing "
            "StealthOrderManager create path or mutate local lifecycle state."
        ),
    )


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes"}:
            return True
        if normalized in {"0", "false", "no"}:
            return False
    return bool(value)


def _list_or_empty(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _runtime_order_engine() -> Any | None:
    bridge = _runtime_bridge()
    return getattr(bridge, "order_engine", None) if bridge else None


def _runtime_orderbook() -> Any | None:
    engine = _runtime_order_engine()
    orderbook = getattr(engine, "orderbook", None) if engine else None
    if orderbook is not None:
        return orderbook
    try:
        import configuration

        orderbook_proxy = getattr(configuration, "ORDERBOOK", None)
        return getattr(orderbook_proxy, "_real", None)
    except Exception:
        return None


def _dashboard_state_snapshot() -> dict[str, Any]:
    try:
        import dashboard_server

        engine_state = getattr(dashboard_server, "engine_state", None)
        state_lock = getattr(dashboard_server, "state_lock", None)
        if not isinstance(engine_state, dict) or state_lock is None:
            return {}
        with state_lock:
            return deepcopy(engine_state)
    except Exception:
        return {}


def _orderbook_product_metadata(orderbook: Any | None) -> dict[str, dict[str, Any]]:
    products = getattr(orderbook, "products", None)
    if products is None:
        products = getattr(orderbook, "product", None)
    if not isinstance(products, dict) and not hasattr(products, "items"):
        return {}
    metadata: dict[str, dict[str, Any]] = {}
    try:
        for product_id, payload in products.items():
            metadata[str(product_id)] = _dict_or_empty(payload)
    except Exception:
        return {}
    return metadata


def _products_json_metadata() -> dict[str, dict[str, Any]]:
    products_path = ROOT / "products.json"
    try:
        payload = json.loads(products_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    items: dict[str, dict[str, Any]] = {}
    for product_id, product_payload in metadata.items():
        item = _dict_or_empty(product_payload)
        if "product_type" not in item and "type" in item:
            item["product_type"] = item.get("type")
        item.setdefault("product_id", product_id)
        items[str(product_id)] = item
    return items


def _normalize_admin_product_type(
    product_id: str,
    product_metadata: dict[str, Any] | None,
) -> str:
    try:
        from calculation.resolver import normalize_product_type

        return normalize_product_type(
            {
                "product_id": product_id,
                "product_type": _dict_or_empty(product_metadata).get("product_type")
                or _dict_or_empty(product_metadata).get("type"),
            },
            products={product_id: _dict_or_empty(product_metadata)}
            if product_metadata
            else None,
        )
    except Exception:
        return ProductType.FUTURE.value if product_id.endswith("-CDE") else ProductType.SPOT.value


def _futures_product_metadata() -> dict[str, dict[str, Any]]:
    orderbook = _runtime_orderbook()
    metadata = _products_json_metadata()
    metadata.update(_orderbook_product_metadata(orderbook))
    return {
        product_id: payload
        for product_id, payload in metadata.items()
        if _normalize_admin_product_type(product_id, payload) == ProductType.FUTURE.value
    }


def _runtime_fee_info(product_id: str | None = None) -> dict[str, Any]:
    engine = _runtime_order_engine()
    fee_manager = getattr(engine, "fee_manager", None) if engine else None
    if fee_manager is not None:
        try:
            return _dict_or_empty(fee_manager.get_fee_info(product_id=product_id))
        except TypeError:
            try:
                return _dict_or_empty(fee_manager.get_fee_info())
            except Exception:
                pass
        except Exception:
            pass
    dashboard_snapshot = _dashboard_state_snapshot()
    engine_status = _dict_or_empty(dashboard_snapshot.get("engine_status"))
    return {
        key: engine_status.get(key)
        for key in (
            "margin_window_type",
            "overnight_margin_active",
            "effective_fee_rate",
            "target_movement_factor",
            "fee_regime_factor",
            "volume_ratio",
        )
        if key in engine_status
    }


def _snapshot_future_positions() -> tuple[dict[str, dict[str, Any]], AdminFuturesEvidenceSource]:
    orderbook = _runtime_orderbook()
    if orderbook is not None:
        try:
            snapshot = orderbook.snapshot_positions()
            futures_positions = _dict_or_empty(snapshot.get(ProductType.FUTURE.value))
            return {
                str(product_id): _dict_or_empty(position)
                for product_id, position in futures_positions.items()
            }, AdminFuturesEvidenceSource.RUNTIME_ORDERBOOK
        except Exception:
            pass
        try:
            items = orderbook.iter_future_positions()
            return {
                str(product_id): _dict_or_empty(position)
                for product_id, position in items
            }, AdminFuturesEvidenceSource.RUNTIME_ORDERBOOK
        except Exception:
            pass
    dashboard_snapshot = _dashboard_state_snapshot()
    positions = _dict_or_empty(dashboard_snapshot.get("positions"))
    if positions:
        products = _futures_product_metadata()
        filtered_positions: dict[str, dict[str, Any]] = {}
        for product_id, position in positions.items():
            normalized_product_id = str(product_id)
            normalized_position = _dict_or_empty(position)
            if normalized_product_id in products or (
                _normalize_admin_product_type(
                    normalized_product_id,
                    normalized_position,
                )
                == ProductType.FUTURE.value
            ):
                filtered_positions[normalized_product_id] = normalized_position
        return filtered_positions, AdminFuturesEvidenceSource.DASHBOARD_ENGINE_STATE
    return {}, AdminFuturesEvidenceSource.RUNTIME_UNAVAILABLE


def _decimal_string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _numeric_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _derive_position_side(position: dict[str, Any]) -> str | None:
    for field_name in ("side", "position_side", "position_direction"):
        value = position.get(field_name)
        if value:
            normalized = str(value).upper()
            if normalized in {
                AdminFuturesPositionSide.LONG.value,
                AdminFuturesPositionSide.SHORT.value,
            }:
                return normalized
    net_size = _numeric_float_or_none(position.get("net_size"))
    if net_size is not None:
        if net_size > 0:
            return AdminFuturesPositionSide.LONG.value
        if net_size < 0:
            return AdminFuturesPositionSide.SHORT.value
        return AdminFuturesPositionSide.FLAT.value
    return None


def _derive_number_of_contracts(position: dict[str, Any]) -> str | None:
    for field_name in ("number_of_contracts", "contracts", "size"):
        value = position.get(field_name)
        if value is not None:
            return str(value)
    net_size = _numeric_float_or_none(position.get("net_size"))
    if net_size is not None:
        return str(abs(net_size))
    return None


def _position_key(product_id: str, position: dict[str, Any]) -> str:
    portfolio_uuid = _string_or_none(position.get("portfolio_uuid")) or "runtime"
    return f"futures_position:{portfolio_uuid}:{product_id}"


def _futures_position_item_from_raw(
    *,
    product_id: str,
    position: dict[str, Any],
    product_metadata: dict[str, Any] | None,
    mandatory_fee_per_contract: str | None,
    source: AdminFuturesEvidenceSource,
) -> AdminFuturesPositionReadItem:
    position_side = _derive_position_side(position)
    number_of_contracts = _derive_number_of_contracts(position)
    open_order_side: str | None = None
    close_order_side: str | None = None
    if position_side in {
        AdminFuturesPositionSide.LONG.value,
        AdminFuturesPositionSide.SHORT.value,
    }:
        try:
            from configuration import determine_open_close_sides

            open_order_side, close_order_side = determine_open_close_sides(
                ProductType.FUTURE.value,
                position_side=position_side,
                position_size=_numeric_float_or_none(number_of_contracts),
            )
        except Exception:
            if position_side == AdminFuturesPositionSide.SHORT.value:
                open_order_side = OrderSide.SELL.value
                close_order_side = OrderSide.BUY.value
            else:
                open_order_side = OrderSide.BUY.value
                close_order_side = OrderSide.SELL.value

    position_pnl: dict[str, Any] = {}
    for field_name in ("unrealized_pnl", "realized_pnl"):
        if field_name in position:
            position_pnl[field_name] = position[field_name]

    return AdminFuturesPositionReadItem(
        position_key=_position_key(product_id, position),
        product_id=product_id,
        product_type=ProductType.FUTURE.value,
        portfolio_uuid=_string_or_none(position.get("portfolio_uuid")),
        position_side=position_side,
        number_of_contracts=number_of_contracts,
        net_size=_decimal_string_or_none(position.get("net_size")),
        entry_price=_decimal_string_or_none(position.get("entry_price")),
        entry_vwap=_decimal_string_or_none(position.get("entry_vwap")),
        current_price=_decimal_string_or_none(position.get("current_price")),
        margin_type=_string_or_none(position.get("margin_type")),
        margin_amount=_json_object_or_none(position.get("margin_amt")),
        leverage=_decimal_string_or_none(position.get("leverage")),
        liquidation_buffer_percentage=_decimal_string_or_none(
            position.get("liquidation_buffer_percentage")
        ),
        open_order_side=open_order_side,
        close_order_side=close_order_side,
        reduce_only_order_side=close_order_side,
        close_only_order_side=close_order_side,
        position_pnl=position_pnl or None,
        product_metadata=_dict_or_empty(product_metadata) or None,
        mandatory_fee_per_contract=mandatory_fee_per_contract,
        raw_position=dict(position),
        source=source,
        updated_at=_string_or_none(position.get("updated_at")),
    )


def _mandatory_fee_map(orderbook: Any | None) -> dict[str, dict[str, Any]]:
    fees = getattr(orderbook, "mandatory_fee_per_contract", None)
    if not isinstance(fees, dict) and not hasattr(fees, "items"):
        return {}
    try:
        return {
            str(product_id): _dict_or_empty(payload)
            for product_id, payload in fees.items()
        }
    except Exception:
        return {}


def _futures_position_items() -> list[AdminFuturesPositionReadItem]:
    products = _futures_product_metadata()
    positions, source = _snapshot_future_positions()
    orderbook = _runtime_orderbook()
    mandatory_fees = _mandatory_fee_map(orderbook)
    items: list[AdminFuturesPositionReadItem] = []
    for product_id, position in positions.items():
        product_metadata = products.get(product_id, {})
        metadata_product_type = _normalize_admin_product_type(
            product_id,
            product_metadata,
        ) if product_metadata else None
        position_product_type = _normalize_admin_product_type(product_id, position)
        if metadata_product_type and metadata_product_type != ProductType.FUTURE.value:
            continue
        if (
            not metadata_product_type
            and source == AdminFuturesEvidenceSource.DASHBOARD_ENGINE_STATE
            and position_product_type != ProductType.FUTURE.value
        ):
            continue
        fee_payload = mandatory_fees.get(product_id, {})
        items.append(
            _futures_position_item_from_raw(
                product_id=product_id,
                position=position,
                product_metadata=product_metadata,
                mandatory_fee_per_contract=_decimal_string_or_none(
                    fee_payload.get("mandatory_fee_per_contract")
                ),
                source=source,
            )
        )
    return items


def _futures_evidence(
    *,
    name: str,
    status: AdminFuturesEvidenceStatus,
    source: AdminFuturesEvidenceSource,
    value: Any | None = None,
    detail: str | None = None,
) -> AdminFuturesEvidenceItem:
    return AdminFuturesEvidenceItem(
        name=name,
        status=status,
        source=source,
        value=value,
        detail=detail,
    )


def _risk_evidence(
    *,
    name: str,
    status: AdminRiskEvidenceStatus,
    source: AdminRiskEvidenceSource,
    value: Any | None = None,
    detail: str | None = None,
) -> AdminRiskEvidenceItem:
    return AdminRiskEvidenceItem(
        name=name,
        status=status,
        source=source,
        value=value,
        detail=detail,
    )


def _normalize_guard_phases(value: Any) -> list[str]:
    if value is None:
        return [
            ActionGuardPhase.PLANNING.value,
            ActionGuardPhase.REVEAL.value,
        ]
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = [value]
    phases: list[str] = []
    for item in values:
        try:
            phase = ActionGuardPhase(str(item)).value
        except ValueError:
            phase = str(item)
        if phase not in phases:
            phases.append(phase)
    return phases


def _configured_limit_rules(policy: dict[str, Any]) -> list[AdminRiskPolicyRuleItem]:
    limits = policy.get("limits") or []
    if isinstance(limits, dict):
        limits = list(limits.values())
    if not isinstance(limits, list):
        return []

    items: list[AdminRiskPolicyRuleItem] = []
    for index, raw_rule in enumerate(limits):
        if not isinstance(raw_rule, dict):
            continue
        rule = dict(raw_rule)
        policy_id = str(rule.get("name") or f"limit_{index}")
        max_notional = rule.get(ActionConditionType.MAX_NOTIONAL.value)
        max_base_size = rule.get(ActionConditionType.MAX_BASE_SIZE.value)
        items.append(
            AdminRiskPolicyRuleItem(
                policy_id=policy_id,
                enabled=rule.get("enabled", True) is not False,
                product_id=_string_or_none(rule.get("product_id")),
                product_type=rule.get("product_type"),
                side=rule.get("side"),
                phases=_normalize_guard_phases(rule.get("phases")),
                max_notional=(
                    str(max_notional) if max_notional is not None else None
                ),
                max_base_size=(
                    str(max_base_size) if max_base_size is not None else None
                ),
                raw_rule=rule,
            )
        )
    return items


def _product_capability_decisions(
    product_id: str | None,
) -> tuple[list[AdminProductCapabilityDecisionItem], list[str]]:
    if not product_id:
        return [], []
    try:
        from core.product_capability import evaluate_product_capability
    except Exception as exc:
        return [], [f"import_error:{type(exc).__name__}: {exc}"]

    decisions: list[AdminProductCapabilityDecisionItem] = []
    errors: list[str] = []
    for capability in ProductCapability:
        try:
            decision = evaluate_product_capability(
                product_id=product_id,
                capability=capability,
            )
        except Exception as exc:
            errors.append(f"{capability.value}:{type(exc).__name__}: {exc}")
            continue
        decisions.append(
            AdminProductCapabilityDecisionItem(
                product_id=decision.product_id,
                product_type=decision.product_type,
                capability=capability,
                mode=decision.mode,
                allowed=decision.allowed,
                reason=decision.reason,
            )
        )
    return decisions, errors


def _risk_rejection_categories() -> list[AdminRiskRejectionCategoryItem]:
    return [
        AdminRiskRejectionCategoryItem(
            condition=ActionConditionType.MANUAL_LIVE_ACKNOWLEDGEMENT,
            source=AdminRiskEvidenceSource.ACTION_CONDITION_GUARD,
            applies_to_product_type=ProductType.SPOT,
            detail="Direct spot placement requires explicit manual live acknowledgement before REST submission.",
        ),
        AdminRiskRejectionCategoryItem(
            condition=ActionConditionType.DIRECT_SPOT_CAP_REQUIRED,
            source=AdminRiskEvidenceSource.ACTION_CONDITION_GUARD,
            applies_to_product_type=ProductType.SPOT,
            detail="Direct spot placement requires a planning-phase max_notional cap before REST submission.",
        ),
        AdminRiskRejectionCategoryItem(
            condition=ActionConditionType.MAX_NOTIONAL,
            source=AdminRiskEvidenceSource.ACTION_CONDITION_GUARD,
            detail="Configured max_notional rules block oversized actions before exchange work.",
        ),
        AdminRiskRejectionCategoryItem(
            condition=ActionConditionType.MAX_BASE_SIZE,
            source=AdminRiskEvidenceSource.ACTION_CONDITION_GUARD,
            detail="Configured max_base_size rules block oversized actions before exchange work.",
        ),
        AdminRiskRejectionCategoryItem(
            condition=ActionConditionType.WALLET_AVAILABLE,
            source=AdminRiskEvidenceSource.ACTION_CONDITION_GUARD,
            applies_to_product_type=ProductType.SPOT,
            detail="Spot wallet availability is evaluated at backend action boundaries only.",
        ),
        AdminRiskRejectionCategoryItem(
            condition=ActionConditionType.PLANNED_BUDGET_AVAILABLE,
            source=AdminRiskEvidenceSource.ACTION_CONDITION_GUARD,
            applies_to_product_type=ProductType.SPOT,
            detail="Spot planned budget commitments are subtracted at planning and reveal boundaries.",
        ),
        AdminRiskRejectionCategoryItem(
            condition=ActionConditionType.KNOWN_INVENTORY_AVAILABLE,
            source=AdminRiskEvidenceSource.SPOT_INVENTORY_AUTHORITY,
            applies_to_product_type=ProductType.SPOT,
            detail="Known profitable inventory authority applies only to spot SELL actions.",
        ),
        AdminRiskRejectionCategoryItem(
            condition=ActionConditionType.DURABLE_AUDIT_AVAILABLE,
            source=AdminRiskEvidenceSource.LIVE_EXECUTION_GATE,
            detail="Durable audit evidence is required before approved live command execution.",
        ),
    ]


def _query_admin_rows(
    query: str,
    params: tuple[Any, ...] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        from database import order as order_module

        rows = order_module.DB_CLIENT.execute_query(query, params) or []
        return [dict(row) for row in rows], None
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"


def _runtime_bridge() -> Any | None:
    try:
        import dashboard_server

        return getattr(dashboard_server, "stealth_order_bridge", None)
    except Exception:
        return None


def _runtime_mutation_claims_for(
    stealth_order_id: str | None,
) -> list[AdminMutationClaimEvidence]:
    if not stealth_order_id:
        return []
    bridge = _runtime_bridge()
    manager = getattr(bridge, "stealth_manager", None) if bridge else None
    snapshot_mutation_claims = (
        getattr(manager, "snapshot_mutation_claims", None) if manager else None
    )
    if not callable(snapshot_mutation_claims):
        return [
            AdminMutationClaimEvidence(
                kind=kind,
                state=None,
                runtime_observed=False,
                source="runtime_stealth_manager_unavailable",
            )
            for kind in StealthMutationKind
        ]
    try:
        claim_states = snapshot_mutation_claims(stealth_order_id)
    except Exception as exc:
        return [
            AdminMutationClaimEvidence(
                kind=kind,
                state=f"unavailable:{type(exc).__name__}",
                runtime_observed=False,
                source="stealth_manager.snapshot_mutation_claims_error",
            )
            for kind in StealthMutationKind
        ]
    claims: list[AdminMutationClaimEvidence] = []
    for kind in StealthMutationKind:
        claims.append(
            AdminMutationClaimEvidence(
                kind=kind,
                state=_string_or_none(claim_states.get(kind)),
                runtime_observed=True,
                source="stealth_manager.snapshot_mutation_claims",
            )
        )
    return claims


def _runtime_pending_replacement_claims(
    client_order_id: str | None,
) -> tuple[int | None, bool]:
    if not client_order_id:
        return None, False
    bridge = _runtime_bridge()
    engine = getattr(bridge, "order_engine", None) if bridge else None
    claims = getattr(engine, "_pending_replacement_claims", None) if engine else None
    if claims is None:
        return None, False
    lock = getattr(engine, "orderbook_lock", None)
    if lock is None:
        return None, False
    try:
        with lock:
            return _int_or_none(claims.get(client_order_id, 0)), True
    except Exception:
        return None, False


def _parent_order_row(client_order_id: str | None) -> dict[str, Any] | None:
    if not client_order_id:
        return None
    try:
        from database import order as order_module

        row = order_module.get_parent_order(client_order_id)
        return dict(row) if row else None
    except Exception:
        return None


def _stealth_order_row(stealth_order_id: str | None) -> dict[str, Any] | None:
    if not stealth_order_id:
        return None
    try:
        from database import order as order_module

        row = order_module.get_stealth_order_by_id(stealth_order_id)
        return dict(row) if row else None
    except Exception:
        return None


def _replacement_slot_evidence(
    client_order_id: str | None,
) -> AdminReplacementSlotEvidence | None:
    if not client_order_id:
        return None
    pending_claims, pending_observed = _runtime_pending_replacement_claims(
        client_order_id
    )
    row = _parent_order_row(client_order_id)
    if row:
        return AdminReplacementSlotEvidence(
            client_order_id=client_order_id,
            max_order_replacement=_int_or_none(row.get("max_order_replacement")),
            current_order_replacement=_int_or_none(
                row.get("current_order_replacement")
            ),
            pending_replacement_claims=pending_claims,
            pending_claims_runtime_observed=pending_observed,
            source="order_parent",
        )
    if pending_observed:
        return AdminReplacementSlotEvidence(
            client_order_id=client_order_id,
            pending_replacement_claims=pending_claims,
            pending_claims_runtime_observed=True,
            source="runtime_order_engine",
        )
    return AdminReplacementSlotEvidence(
        client_order_id=client_order_id,
        pending_replacement_claims=None,
        pending_claims_runtime_observed=False,
        source="order_parent_missing",
    )


def _replacement_slots_for(
    *client_order_ids: str | None,
) -> list[AdminReplacementSlotEvidence]:
    slots: list[AdminReplacementSlotEvidence] = []
    seen: set[str] = set()
    for client_order_id in client_order_ids:
        if not client_order_id or client_order_id in seen:
            continue
        seen.add(client_order_id)
        slot = _replacement_slot_evidence(client_order_id)
        if slot:
            slots.append(slot)
    return slots


def _parent_move_item_from_row(row: dict[str, Any]) -> AdminMovementRepricingEvidenceItem:
    original_parent_client_order_id = _string_or_none(
        row.get("original_parent_client_order_id")
    )
    new_parent_client_order_id = _string_or_none(row.get("new_parent_client_order_id"))
    move_on_cancel = _bool_or_none(row.get("move_on_cancel"))
    status = (
        "pending_move"
        if move_on_cancel and not new_parent_client_order_id
        else "completed_move"
    )
    parent_row = (
        _parent_order_row(original_parent_client_order_id)
        or _parent_order_row(new_parent_client_order_id)
        or {}
    )
    return AdminMovementRepricingEvidenceItem(
        evidence_id=f"parent_move:{row.get('id') or original_parent_client_order_id}",
        evidence_type=AdminMovementRepricingEvidenceType.PARENT_MOVE,
        client_order_id=original_parent_client_order_id,
        original_parent_client_order_id=original_parent_client_order_id,
        new_parent_client_order_id=new_parent_client_order_id,
        product_id=_string_or_none(parent_row.get("product_id")),
        side=_string_or_none(parent_row.get("side")),
        status=status,
        move_on_cancel=move_on_cancel,
        reason=_string_or_none(row.get("reason")),
        notes=_string_or_none(row.get("notes")),
        replacement_slots=_replacement_slots_for(
            original_parent_client_order_id,
            new_parent_client_order_id,
        ),
        created_at=_string_or_none(row.get("created_at")),
        moved_at=_string_or_none(row.get("moved_at")),
        source="order_moves",
    )


def _stealth_move_item_from_row(row: dict[str, Any]) -> AdminMovementRepricingEvidenceItem:
    stealth_order_id = _string_or_none(row.get("stealth_order_id"))
    stealth_row = _stealth_order_row(stealth_order_id) or {}
    new_placement_client_order_id = _string_or_none(
        row.get("new_placement_client_order_id")
    )
    old_placement_client_order_id = _string_or_none(
        row.get("old_placement_client_order_id")
    )
    return AdminMovementRepricingEvidenceItem(
        evidence_id=f"stealth_move:{row.get('id') or stealth_order_id}",
        evidence_type=AdminMovementRepricingEvidenceType.STEALTH_MOVE,
        client_order_id=new_placement_client_order_id or old_placement_client_order_id,
        stealth_order_id=stealth_order_id,
        product_id=_string_or_none(stealth_row.get("product_id")),
        side=_string_or_none(stealth_row.get("side")),
        status=_string_or_none(row.get("status")),
        reason=_string_or_none(row.get("reason")),
        notes=_string_or_none(row.get("notes")),
        old_placement_client_order_id=old_placement_client_order_id,
        old_exchange_order_id=_string_or_none(row.get("old_exchange_order_id")),
        old_submitted_price=_string_or_none(row.get("old_submitted_price")),
        new_placement_client_order_id=new_placement_client_order_id,
        new_exchange_order_id=_string_or_none(row.get("new_exchange_order_id")),
        new_submitted_price=_string_or_none(row.get("new_submitted_price")),
        mutation_claims=_runtime_mutation_claims_for(stealth_order_id),
        market_bid=_string_or_none(row.get("market_bid")),
        market_ask=_string_or_none(row.get("market_ask")),
        error_message=_string_or_none(row.get("error_message")),
        moved_at=_string_or_none(row.get("moved_at")),
        source="stealth_order_moves",
    )


def _stealth_repricing_item_from_row(
    row: dict[str, Any],
) -> AdminMovementRepricingEvidenceItem:
    stealth_order_id = _string_or_none(row.get("stealth_order_id"))
    parent_order_id = _string_or_none(row.get("parent_order_id"))
    anchor_state = _json_object_or_none(row.get("anchor_repricing_state_json")) or {}
    active_placement_client_order_id = _string_or_none(
        anchor_state.get("active_placement_client_order_id")
        or anchor_state.get("active_placement_order_id")
        or anchor_state.get("active_placed_order_id")
    )
    active_exchange_order_id = _string_or_none(
        anchor_state.get("active_exchange_order_id")
    )
    return AdminMovementRepricingEvidenceItem(
        evidence_id=f"stealth_repricing_state:{stealth_order_id}",
        evidence_type=AdminMovementRepricingEvidenceType.STEALTH_REPRICING_STATE,
        client_order_id=active_placement_client_order_id,
        stealth_order_id=stealth_order_id,
        product_id=_string_or_none(row.get("product_id")),
        side=_string_or_none(row.get("side")),
        status=_string_or_none(row.get("status")),
        active_placement_client_order_id=active_placement_client_order_id,
        active_exchange_order_id=active_exchange_order_id,
        active_exchange_price=_string_or_none(anchor_state.get("active_exchange_price")),
        target_movement=_string_or_none(row.get("target_movement")),
        target_movement_type=_string_or_none(row.get("target_movement_type")),
        replacement_slots=_replacement_slots_for(parent_order_id, stealth_order_id),
        mutation_claims=_runtime_mutation_claims_for(stealth_order_id),
        anchor_repricing_policy=_json_object_or_none(
            row.get("anchor_repricing_policy_json")
        ),
        anchor_repricing_state=anchor_state,
        reprice_history=_list_or_empty(anchor_state.get("reprice_history")),
        reprice_reason=_string_or_none(anchor_state.get("reprice_reason")),
        last_reprice_at=_string_or_none(anchor_state.get("last_reprice_at")),
        next_reprice_at=_string_or_none(anchor_state.get("next_reprice_at")),
        post_fill_retreat_offset=_string_or_none(
            anchor_state.get("post_fill_retreat_offset")
        ),
        created_at=_string_or_none(row.get("created_at")),
        updated_at=_string_or_none(row.get("updated_at")),
        source="stealth_orders",
    )


def _movement_evidence_type_value(
    evidence_type: AdminMovementRepricingEvidenceType | str | None,
) -> str | None:
    if evidence_type is None:
        return None
    if isinstance(evidence_type, AdminMovementRepricingEvidenceType):
        return evidence_type.value
    return str(evidence_type)


def _movement_item_matches(
    item: AdminMovementRepricingEvidenceItem,
    *,
    product_id: str | None,
    client_order_id: str | None,
    stealth_order_id: str | None,
    evidence_type: AdminMovementRepricingEvidenceType | str | None,
) -> bool:
    if product_id and item.product_id != product_id:
        return False
    if stealth_order_id and item.stealth_order_id != stealth_order_id:
        return False
    if evidence_type and item.evidence_type.value != _movement_evidence_type_value(
        evidence_type
    ):
        return False
    if client_order_id:
        client_fields = {
            item.client_order_id,
            item.original_parent_client_order_id,
            item.new_parent_client_order_id,
            item.old_placement_client_order_id,
            item.new_placement_client_order_id,
            item.active_placement_client_order_id,
        }
        if client_order_id not in client_fields:
            return False
    return True


def _audit_module_for_surface(
    surface: str,
    shared_method: str | None = None,
) -> AdminAuditWorkbenchModule:
    normalized = f"{surface} {shared_method or ''}".lower()
    if "/api/v1/admin/guard-risk-policy" in normalized:
        return AdminAuditWorkbenchModule.GUARD_RISK
    if "/api/v1/futures" in normalized:
        return AdminAuditWorkbenchModule.FUTURES_PERPETUALS
    if "/api/v1/movement-repricing" in normalized:
        return AdminAuditWorkbenchModule.MOVEMENT_REPRICING
    if "/api/v1/stealth" in normalized or "stealth" in normalized:
        return AdminAuditWorkbenchModule.STEALTH
    if "/api/v1/spot/campaign" in normalized or "campaign" in normalized:
        return AdminAuditWorkbenchModule.CAMPAIGNS
    if "/api/v1/spot" in normalized:
        return AdminAuditWorkbenchModule.SPOT
    if "/api/v1/orders" in normalized or "place_order" in normalized or "cancel_order" in normalized:
        return AdminAuditWorkbenchModule.ORDERS
    if "/api/v1/admin" in normalized:
        return AdminAuditWorkbenchModule.ADMIN
    return AdminAuditWorkbenchModule.ADMIN


def _audit_module_identity(module: AdminAuditWorkbenchModule) -> str:
    return {
        AdminAuditWorkbenchModule.ADMIN: "route_and_actor_evidence",
        AdminAuditWorkbenchModule.SPOT: "client_order_id",
        AdminAuditWorkbenchModule.ORDERS: "client_order_id",
        AdminAuditWorkbenchModule.STEALTH: "stealth_order_id",
        AdminAuditWorkbenchModule.MOVEMENT_REPRICING: "client_order_id_or_stealth_order_id",
        AdminAuditWorkbenchModule.FUTURES_PERPETUALS: "position_key",
        AdminAuditWorkbenchModule.GUARD_RISK: "policy_id_and_product_id",
        AdminAuditWorkbenchModule.CAMPAIGNS: "campaign_id",
    }[module]


def _audit_module_source(module: AdminAuditWorkbenchModule) -> AdminAuditEvidenceSource:
    return {
        AdminAuditWorkbenchModule.ADMIN: AdminAuditEvidenceSource.BACKEND_CONTRACT,
        AdminAuditWorkbenchModule.SPOT: AdminAuditEvidenceSource.ORDER_PARENT,
        AdminAuditWorkbenchModule.ORDERS: AdminAuditEvidenceSource.ORDER_PARENT,
        AdminAuditWorkbenchModule.STEALTH: AdminAuditEvidenceSource.STEALTH_ORDERS,
        AdminAuditWorkbenchModule.MOVEMENT_REPRICING: AdminAuditEvidenceSource.MOVEMENT_REPRICING,
        AdminAuditWorkbenchModule.FUTURES_PERPETUALS: AdminAuditEvidenceSource.FUTURES_POSITIONS,
        AdminAuditWorkbenchModule.GUARD_RISK: AdminAuditEvidenceSource.GUARD_RISK_POLICY,
        AdminAuditWorkbenchModule.CAMPAIGNS: AdminAuditEvidenceSource.ADMIN_API_AUDIT_LOG,
    }[module]


def _audit_module_note(module: AdminAuditWorkbenchModule) -> str:
    return {
        AdminAuditWorkbenchModule.ADMIN: "Admin/session/auth evidence only; no trading behavior.",
        AdminAuditWorkbenchModule.SPOT: "Spot audit identity remains client_order_id; wallet and lot authority stay backend-owned.",
        AdminAuditWorkbenchModule.ORDERS: "Order audit links use client_order_id; exchange order_id is evidence only.",
        AdminAuditWorkbenchModule.STEALTH: "Stealth audit links preserve stealth_order_id and active placement evidence.",
        AdminAuditWorkbenchModule.MOVEMENT_REPRICING: "Move/reprice evidence is read-only and cannot mutate live placements.",
        AdminAuditWorkbenchModule.FUTURES_PERPETUALS: "Futures/perpetual audit identity is position_key, not spot wallet inventory.",
        AdminAuditWorkbenchModule.GUARD_RISK: "Guard/risk rows are policy evidence, not browser authority.",
        AdminAuditWorkbenchModule.CAMPAIGNS: "Campaign command evidence remains live-disabled unless backend gates approve it.",
    }[module]


def _normalize_audit_module(
    module: AdminAuditWorkbenchModule | str | None,
) -> AdminAuditWorkbenchModule | None:
    if module is None:
        return None
    if isinstance(module, AdminAuditWorkbenchModule):
        return module
    try:
        return AdminAuditWorkbenchModule(str(module))
    except ValueError:
        return None


def _audit_module_summary() -> list[AdminAuditModuleSummaryItem]:
    order = [
        AdminAuditWorkbenchModule.ADMIN,
        AdminAuditWorkbenchModule.SPOT,
        AdminAuditWorkbenchModule.ORDERS,
        AdminAuditWorkbenchModule.STEALTH,
        AdminAuditWorkbenchModule.MOVEMENT_REPRICING,
        AdminAuditWorkbenchModule.FUTURES_PERPETUALS,
        AdminAuditWorkbenchModule.GUARD_RISK,
        AdminAuditWorkbenchModule.CAMPAIGNS,
    ]
    state: dict[AdminAuditWorkbenchModule, dict[str, Any]] = {
        module: {
            "read_route_count": 0,
            "command_route_count": 0,
            "evidence_sources": [
                AdminAuditEvidenceSource.ROUTE_INVENTORY,
                _audit_module_source(module),
            ],
            "routes": [],
        }
        for module in order
    }
    for item in ADMIN_API_ROUTE_INVENTORY:
        module = _audit_module_for_surface(item.surface, item.shared_method)
        method, path = _surface_method_and_path(item.surface)
        route_label = f"{method} {path}"
        if item.action_class == AdminApiActionClass.READ_ONLY:
            state[module]["read_route_count"] += 1
        else:
            state[module]["command_route_count"] += 1
        state[module]["routes"].append(route_label)

    return [
        AdminAuditModuleSummaryItem(
            module=module,
            read_route_count=state[module]["read_route_count"],
            command_route_count=state[module]["command_route_count"],
            live_enabled=False,
            primary_identity=_audit_module_identity(module),
            evidence_sources=list(dict.fromkeys(state[module]["evidence_sources"])),
            routes=state[module]["routes"],
            notes=_audit_module_note(module),
        )
        for module in order
    ]


def _audit_event_matches(
    item: AdminAuditWorkbenchEventItem,
    *,
    module: AdminAuditWorkbenchModule | None,
    product_id: str | None,
    client_order_id: str | None,
    correlation_id: str | None,
    audit_id: str | None,
) -> bool:
    if module and item.module != module:
        return False
    if product_id and item.product_id != product_id:
        return False
    if client_order_id and client_order_id not in _audit_event_client_order_ids(
        item
    ):
        return False
    if correlation_id and item.correlation_id != correlation_id and item.request_id != correlation_id:
        return False
    if audit_id and item.audit_id != audit_id:
        return False
    return True


def _audit_event_client_order_ids(item: AdminAuditWorkbenchEventItem) -> set[str]:
    values = {item.client_order_id} if item.client_order_id else set()
    if item.source == AdminAuditEvidenceSource.MOVEMENT_REPRICING:
        for key in (
            "original_parent_client_order_id",
            "new_parent_client_order_id",
            "old_placement_client_order_id",
            "new_placement_client_order_id",
            "active_placement_client_order_id",
        ):
            value = item.raw_event.get(key)
            if value is not None:
                values.add(str(value))
    return values


def _audit_event_from_command_event(
    event: AdminApiAuditEvent,
) -> AdminAuditWorkbenchEventItem:
    raw_event = event.model_dump(mode="json")
    return AdminAuditWorkbenchEventItem(
        event_id=event.audit_id,
        module=_audit_module_for_surface(event.endpoint),
        source=AdminAuditEvidenceSource.ADMIN_API_AUDIT_LOG,
        action_class=event.action_class,
        endpoint=event.endpoint,
        status=event.status.value,
        actor_id=event.actor_id,
        permission=event.permission,
        client_order_id=event.client_order_id,
        stealth_order_id=event.stealth_order_id,
        correlation_id=event.request_id,
        audit_id=event.audit_id,
        request_id=event.request_id,
        operator_intent=event.operator_intent,
        idempotency_key=event.idempotency_key,
        exchange_order_id=event.coinbase_order_id,
        recorded_at=event.recorded_at,
        message=event.message,
        admission_decision=(
            event.admission_decision.model_dump(mode="json")
            if event.admission_decision is not None
            else None
        ),
        raw_event=raw_event,
    )


def _audit_event_from_order_item(
    item: AdminOrderReadItem,
) -> AdminAuditWorkbenchEventItem:
    return AdminAuditWorkbenchEventItem(
        event_id=f"order:{item.client_order_id}",
        module=AdminAuditWorkbenchModule.ORDERS,
        source=AdminAuditEvidenceSource.ORDER_PARENT,
        action_class=AdminApiActionClass.READ_ONLY,
        endpoint="/api/v1/orders/{client_order_id}",
        status=item.status,
        client_order_id=item.client_order_id,
        product_id=item.product_id,
        correlation_id=item.correlation_id,
        audit_id=item.audit_id,
        exchange_order_id=item.exchange_order_id,
        recorded_at=item.updated_at or item.created_at,
        message="Local order row audit anchor.",
        raw_event=item.model_dump(mode="json"),
    )


def _audit_event_from_stealth_item(
    item: AdminStealthOrderReadItem,
) -> AdminAuditWorkbenchEventItem:
    return AdminAuditWorkbenchEventItem(
        event_id=f"stealth:{item.stealth_order_id}",
        module=AdminAuditWorkbenchModule.STEALTH,
        source=AdminAuditEvidenceSource.STEALTH_ORDERS,
        action_class=AdminApiActionClass.READ_ONLY,
        endpoint="/api/v1/stealth/orders/{stealth_order_id}",
        status=item.status,
        client_order_id=item.active_placement_client_order_id,
        stealth_order_id=item.stealth_order_id,
        product_id=item.product_id,
        exchange_order_id=item.active_exchange_order_id,
        recorded_at=item.updated_at or item.created_at,
        message="Stealth lifecycle audit anchor with active placement evidence.",
        raw_event=item.model_dump(mode="json"),
    )


def _audit_event_from_movement_item(
    item: AdminMovementRepricingEvidenceItem,
) -> AdminAuditWorkbenchEventItem:
    return AdminAuditWorkbenchEventItem(
        event_id=f"movement:{item.evidence_id}",
        module=AdminAuditWorkbenchModule.MOVEMENT_REPRICING,
        source=AdminAuditEvidenceSource.MOVEMENT_REPRICING,
        action_class=AdminApiActionClass.READ_ONLY,
        endpoint="/api/v1/movement-repricing/evidence",
        status=item.status,
        client_order_id=item.client_order_id
        or item.active_placement_client_order_id
        or item.new_placement_client_order_id
        or item.old_placement_client_order_id,
        stealth_order_id=item.stealth_order_id,
        product_id=item.product_id,
        exchange_order_id=item.active_exchange_order_id
        or item.new_exchange_order_id
        or item.old_exchange_order_id,
        recorded_at=item.updated_at or item.moved_at or item.created_at,
        message=f"Movement/repricing evidence: {item.evidence_type.value}.",
        raw_event=item.model_dump(mode="json"),
    )


def _audit_event_from_futures_position(
    item: AdminFuturesPositionReadItem,
) -> AdminAuditWorkbenchEventItem:
    return AdminAuditWorkbenchEventItem(
        event_id=f"futures:{item.position_key}",
        module=AdminAuditWorkbenchModule.FUTURES_PERPETUALS,
        source=AdminAuditEvidenceSource.FUTURES_POSITIONS,
        action_class=AdminApiActionClass.READ_ONLY,
        endpoint="/api/v1/futures/positions/{position_key}",
        status=item.position_side.value if item.position_side else None,
        position_key=item.position_key,
        product_id=item.product_id,
        recorded_at=item.updated_at,
        message="Futures/perpetual position audit anchor.",
        raw_event=item.model_dump(mode="json"),
    )


def _audit_event_from_guard_risk_policy(
    item: AdminRiskPolicyReadResponse,
) -> AdminAuditWorkbenchEventItem:
    return AdminAuditWorkbenchEventItem(
        event_id="guard_risk:policy",
        module=AdminAuditWorkbenchModule.GUARD_RISK,
        source=AdminAuditEvidenceSource.GUARD_RISK_POLICY,
        action_class=AdminApiActionClass.READ_ONLY,
        endpoint="/api/v1/admin/guard-risk-policy",
        status=item.live_execution_gate.status.value,
        product_id=_string_or_none(item.filters.get("product_id")),
        message="Backend guard/risk policy evidence; browser authority is not allowed.",
        raw_event=item.model_dump(mode="json"),
    )


def _spot_recovery_proof_item_from_record(
    record: SpotRecoveryProofRecord,
) -> SpotRecoveryProofRecordItem:
    return SpotRecoveryProofRecordItem(
        proof_id=record.proof_id,
        recorded_at=record.recorded_at,
        mutation_family=record.mutation_family,
        client_order_id=record.client_order_id,
        exchange_state_proof_id=record.exchange_state_proof_id,
        reconciliation_proof_id=record.reconciliation_proof_id,
        exchange_state_evidence_ref=record.exchange_state_evidence_ref,
        recovery_apply_audit_id=record.recovery_apply_audit_id,
        reconciliation_plan_id=record.reconciliation_plan_id,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        cap_guard_decision_id=record.cap_guard_decision_id,
        route=record.route,
        method=record.method,
        action_class=record.action_class,
        required_permission=record.required_permission,
        service_method=record.service_method,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        correlation_id=record.correlation_id,
        payload_hash=record.payload_hash,
        audit_id=record.audit_id,
        dry_run=record.dry_run,
        operator_reason=record.operator_reason,
        manual_live_acknowledgement=record.manual_live_acknowledgement,
        source=record.source,
        proof_persisted=record.proof_persisted,
        recovery_apply_executed=record.recovery_apply_executed,
        rollback_executed=record.rollback_executed,
        reconciliation_executed=record.reconciliation_executed,
        order_state_mutated=record.order_state_mutated,
        exchange_state_mutated=record.exchange_state_mutated,
        coinbase_rest_read_ran=record.coinbase_rest_read_ran,
        live_exchange_submitted=record.live_exchange_submitted,
        live_coinbase_orders_ran=record.live_coinbase_orders_ran,
        browser_authority=record.browser_authority,
        bff_authority=record.bff_authority,
        detail=(
            "Spot recovery proof record is backend-owned append-only local "
            "evidence. It is not browser exchange truth, recovery execution, "
            "reconciliation execution, order/exchange-state mutation, a "
            "Coinbase read, or Coinbase order submission."
        ),
    )


def _spot_recovery_snapshot_item_from_record(
    record: SpotRecoveryExchangeStateSnapshotRecord,
) -> SpotRecoveryExchangeStateSnapshotRecordItem:
    return SpotRecoveryExchangeStateSnapshotRecordItem(
        exchange_state_snapshot_id=record.exchange_state_snapshot_id,
        recorded_at=record.recorded_at,
        mutation_family=record.mutation_family,
        client_order_id=record.client_order_id,
        product_id=record.product_id,
        source_timestamp=record.source_timestamp,
        snapshot_source=record.snapshot_source,
        snapshot_evidence_ref=record.snapshot_evidence_ref,
        reconciliation_plan_id=record.reconciliation_plan_id,
        reconciliation_proof_id=record.reconciliation_proof_id,
        completion_id=record.completion_id,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        cap_guard_decision_id=record.cap_guard_decision_id,
        route=record.route,
        method=record.method,
        action_class=record.action_class,
        required_permission=record.required_permission,
        service_method=record.service_method,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        correlation_id=record.correlation_id,
        payload_hash=record.payload_hash,
        audit_id=record.audit_id,
        dry_run=record.dry_run,
        operator_reason=record.operator_reason,
        manual_live_acknowledgement=record.manual_live_acknowledgement,
        source=record.source,
        snapshot_recorded=record.snapshot_recorded,
        source_trusted=record.source_trusted,
        coinbase_read_attempted=record.coinbase_read_attempted,
        coinbase_read_succeeded=record.coinbase_read_succeeded,
        coinbase_rest_read_ran=record.coinbase_rest_read_ran,
        order_state_mutated=record.order_state_mutated,
        exchange_state_mutated=record.exchange_state_mutated,
        reconciliation_executed=record.reconciliation_executed,
        live_exchange_submitted=record.live_exchange_submitted,
        live_coinbase_orders_ran=record.live_coinbase_orders_ran,
        browser_authority=record.browser_authority,
        bff_authority=record.bff_authority,
        detail=(
            "Spot recovery exchange-state snapshot is backend-owned append-only "
            "local evidence. It is not browser exchange truth, a Coinbase read, "
            "order/exchange-state mutation, or reconciliation execution."
        ),
    )


def _stealth_exchange_truth_snapshot_item_from_record(
    record: StealthActivePlacementExchangeTruthSnapshotRecord,
) -> StealthActivePlacementExchangeTruthSnapshotRecordItem:
    return StealthActivePlacementExchangeTruthSnapshotRecordItem(
        exchange_truth_snapshot_id=record.exchange_truth_snapshot_id,
        recorded_at=record.recorded_at,
        mutation_family=record.mutation_family,
        stealth_order_id=record.stealth_order_id,
        active_placement_client_order_id=record.active_placement_client_order_id,
        active_exchange_order_id=record.active_exchange_order_id,
        product_id=record.product_id,
        source_timestamp=record.source_timestamp,
        evidence_source=record.evidence_source,
        snapshot_evidence_ref=record.snapshot_evidence_ref,
        reconciliation_plan_id=record.reconciliation_plan_id,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        cap_guard_decision_id=record.cap_guard_decision_id,
        route=record.route,
        method=record.method,
        action_class=record.action_class,
        required_permission=record.required_permission,
        service_method=record.service_method,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        correlation_id=record.correlation_id,
        payload_hash=record.payload_hash,
        audit_id=record.audit_id,
        dry_run=record.dry_run,
        operator_reason=record.operator_reason,
        manual_live_acknowledgement=record.manual_live_acknowledgement,
        source=record.source,
        snapshot_recorded=record.snapshot_recorded,
        exchange_truth_verified=record.exchange_truth_verified,
        coinbase_read_attempted=record.coinbase_read_attempted,
        coinbase_read_succeeded=record.coinbase_read_succeeded,
        coinbase_rest_read_ran=record.coinbase_rest_read_ran,
        coinbase_order_submitted=record.coinbase_order_submitted,
        coinbase_order_cancel_submitted=record.coinbase_order_cancel_submitted,
        active_placement_cancel_replace_ran=(
            record.active_placement_cancel_replace_ran
        ),
        reconciliation_executed=record.reconciliation_executed,
        order_state_mutated=record.order_state_mutated,
        lifecycle_state_mutated=record.lifecycle_state_mutated,
        exchange_state_mutated=record.exchange_state_mutated,
        live_exchange_submitted=record.live_exchange_submitted,
        live_coinbase_orders_ran=record.live_coinbase_orders_ran,
        browser_authority=record.browser_authority,
        bff_authority=record.bff_authority,
        detail=(
            "Stealth active-placement exchange-truth snapshot is backend-owned "
            "append-only local evidence. It is not browser exchange truth, a "
            "Coinbase read, cancel/replace, lifecycle mutation, or "
            "reconciliation execution."
        ),
    )


def _stealth_exchange_truth_proof_item_from_record(
    record: StealthActivePlacementExchangeTruthProofRecord,
) -> StealthActivePlacementExchangeTruthProofRecordItem:
    return StealthActivePlacementExchangeTruthProofRecordItem(
        exchange_truth_proof_id=record.exchange_truth_proof_id,
        recorded_at=record.recorded_at,
        mutation_family=record.mutation_family,
        stealth_order_id=record.stealth_order_id,
        exchange_truth_snapshot_id=record.exchange_truth_snapshot_id,
        active_placement_client_order_id=record.active_placement_client_order_id,
        active_exchange_order_id=record.active_exchange_order_id,
        exchange_truth_evidence_ref=record.exchange_truth_evidence_ref,
        reconciliation_plan_id=record.reconciliation_plan_id,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        cap_guard_decision_id=record.cap_guard_decision_id,
        route=record.route,
        method=record.method,
        action_class=record.action_class,
        required_permission=record.required_permission,
        service_method=record.service_method,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        correlation_id=record.correlation_id,
        payload_hash=record.payload_hash,
        audit_id=record.audit_id,
        dry_run=record.dry_run,
        operator_reason=record.operator_reason,
        manual_live_acknowledgement=record.manual_live_acknowledgement,
        source=record.source,
        proof_persisted=record.proof_persisted,
        exchange_truth_verified=record.exchange_truth_verified,
        coinbase_read_attempted=record.coinbase_read_attempted,
        coinbase_read_succeeded=record.coinbase_read_succeeded,
        coinbase_rest_read_ran=record.coinbase_rest_read_ran,
        coinbase_order_submitted=record.coinbase_order_submitted,
        coinbase_order_cancel_submitted=record.coinbase_order_cancel_submitted,
        active_placement_cancel_replace_ran=(
            record.active_placement_cancel_replace_ran
        ),
        reconciliation_executed=record.reconciliation_executed,
        order_state_mutated=record.order_state_mutated,
        lifecycle_state_mutated=record.lifecycle_state_mutated,
        exchange_state_mutated=record.exchange_state_mutated,
        live_exchange_submitted=record.live_exchange_submitted,
        live_coinbase_orders_ran=record.live_coinbase_orders_ran,
        browser_authority=record.browser_authority,
        bff_authority=record.bff_authority,
        detail=(
            "Stealth active-placement exchange-truth proof is backend-owned "
            "append-only evidence only. It remains exchange_truth_verified=false "
            "until a later backend-owned Coinbase or reconciliation authority "
            "proves active placement state."
        ),
    )


def _stealth_lifecycle_write_guard_item_from_record(
    record: StealthCreateLifecycleWriteGuardProofRecord,
) -> StealthCreateLifecycleWriteGuardProofRecordItem:
    return StealthCreateLifecycleWriteGuardProofRecordItem(
        lifecycle_write_guard_proof_id=record.lifecycle_write_guard_proof_id,
        recorded_at=record.recorded_at,
        mutation_family=record.mutation_family,
        stealth_order_id=record.stealth_order_id,
        guarded_command_route=record.guarded_command_route,
        guarded_command_method=record.guarded_command_method,
        guarded_service_method=record.guarded_service_method,
        guarded_actor_id=record.guarded_actor_id,
        guarded_operator_intent=record.guarded_operator_intent,
        guarded_idempotency_key=record.guarded_idempotency_key,
        guarded_payload_hash=record.guarded_payload_hash,
        product_id=record.product_id,
        side=record.side,
        total_size=record.total_size,
        limit_price=record.limit_price,
        evidence_source=record.evidence_source,
        guard_evidence_ref=record.guard_evidence_ref,
        reconciliation_plan_id=record.reconciliation_plan_id,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        cap_guard_decision_id=record.cap_guard_decision_id,
        route=record.route,
        method=record.method,
        action_class=record.action_class,
        required_permission=record.required_permission,
        service_method=record.service_method,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        correlation_id=record.correlation_id,
        payload_hash=record.payload_hash,
        audit_id=record.audit_id,
        dry_run=record.dry_run,
        operator_reason=record.operator_reason,
        manual_live_acknowledgement=record.manual_live_acknowledgement,
        source=record.source,
        proof_persisted=record.proof_persisted,
        lifecycle_write_guard_verified=record.lifecycle_write_guard_verified,
        manager_invocation_ran=record.manager_invocation_ran,
        stealth_row_write_ran=record.stealth_row_write_ran,
        order_parent_write_ran=record.order_parent_write_ran,
        lifecycle_event_dispatch_ran=record.lifecycle_event_dispatch_ran,
        local_lifecycle_mutation_ran=record.local_lifecycle_mutation_ran,
        coinbase_read_attempted=record.coinbase_read_attempted,
        coinbase_read_succeeded=record.coinbase_read_succeeded,
        coinbase_rest_read_ran=record.coinbase_rest_read_ran,
        coinbase_order_submitted=record.coinbase_order_submitted,
        coinbase_order_cancel_submitted=record.coinbase_order_cancel_submitted,
        active_placement_cancel_replace_ran=(
            record.active_placement_cancel_replace_ran
        ),
        reconciliation_executed=record.reconciliation_executed,
        order_state_mutated=record.order_state_mutated,
        lifecycle_state_mutated=record.lifecycle_state_mutated,
        exchange_state_mutated=record.exchange_state_mutated,
        live_exchange_submitted=record.live_exchange_submitted,
        live_coinbase_orders_ran=record.live_coinbase_orders_ran,
        browser_authority=record.browser_authority,
        bff_authority=record.bff_authority,
        detail=(
            "Stealth create lifecycle-write guard proof is backend-owned "
            "append-only evidence only. It does not invoke StealthOrderManager, "
            "write stealth/order_parent rows, dispatch lifecycle events, call "
            "Coinbase, or execute reconciliation."
        ),
    )


def _stealth_mutation_claim_proof_item_from_record(
    record: StealthMutationClaimSnapshotProofRecord,
) -> StealthMutationClaimSnapshotProofRecordItem:
    return StealthMutationClaimSnapshotProofRecordItem(
        mutation_claim_proof_id=record.mutation_claim_proof_id,
        recorded_at=record.recorded_at,
        mutation_family=record.mutation_family,
        stealth_order_id=record.stealth_order_id,
        guarded_command_route=record.guarded_command_route,
        guarded_command_method=record.guarded_command_method,
        guarded_service_method=record.guarded_service_method,
        guarded_actor_id=record.guarded_actor_id,
        guarded_operator_intent=record.guarded_operator_intent,
        guarded_idempotency_key=record.guarded_idempotency_key,
        guarded_payload_hash=record.guarded_payload_hash,
        mutation_kind=record.mutation_kind,
        claim_reader_source=record.claim_reader_source,
        runtime_claims_observed=record.runtime_claims_observed,
        runtime_claim_count=record.runtime_claim_count,
        active_claim_count=record.active_claim_count,
        evidence_source=record.evidence_source,
        snapshot_evidence_ref=record.snapshot_evidence_ref,
        reconciliation_plan_id=record.reconciliation_plan_id,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        cap_guard_decision_id=record.cap_guard_decision_id,
        route=record.route,
        method=record.method,
        action_class=record.action_class,
        required_permission=record.required_permission,
        service_method=record.service_method,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        correlation_id=record.correlation_id,
        payload_hash=record.payload_hash,
        audit_id=record.audit_id,
        dry_run=record.dry_run,
        operator_reason=record.operator_reason,
        manual_live_acknowledgement=record.manual_live_acknowledgement,
        source=record.source,
        proof_persisted=record.proof_persisted,
        mutation_claim_snapshot_verified=(
            record.mutation_claim_snapshot_verified
        ),
        manager_invocation_ran=record.manager_invocation_ran,
        claim_acquire_ran=record.claim_acquire_ran,
        claim_release_ran=record.claim_release_ran,
        coinbase_read_attempted=record.coinbase_read_attempted,
        coinbase_read_succeeded=record.coinbase_read_succeeded,
        coinbase_rest_read_ran=record.coinbase_rest_read_ran,
        coinbase_order_submitted=record.coinbase_order_submitted,
        coinbase_order_cancel_submitted=record.coinbase_order_cancel_submitted,
        active_placement_cancel_replace_ran=(
            record.active_placement_cancel_replace_ran
        ),
        reconciliation_executed=record.reconciliation_executed,
        order_state_mutated=record.order_state_mutated,
        lifecycle_state_mutated=record.lifecycle_state_mutated,
        exchange_state_mutated=record.exchange_state_mutated,
        live_exchange_submitted=record.live_exchange_submitted,
        live_coinbase_orders_ran=record.live_coinbase_orders_ran,
        browser_authority=record.browser_authority,
        bff_authority=record.bff_authority,
        detail=(
            "Stealth mutation-claim snapshot proof is backend-owned append-only "
            "evidence only. It does not acquire or release mutation claims, "
            "call Coinbase, cancel/replace placements, mutate lifecycle state, "
            "or execute reconciliation."
        ),
    )


def _stealth_reveal_trigger_proof_item_from_record(
    record: StealthRevealTriggerProofRecord,
) -> StealthRevealTriggerProofRecordItem:
    return StealthRevealTriggerProofRecordItem(
        reveal_trigger_proof_id=record.reveal_trigger_proof_id,
        recorded_at=record.recorded_at,
        mutation_family=record.mutation_family,
        stealth_order_id=record.stealth_order_id,
        guarded_command_route=record.guarded_command_route,
        guarded_command_method=record.guarded_command_method,
        guarded_service_method=record.guarded_service_method,
        guarded_actor_id=record.guarded_actor_id,
        guarded_operator_intent=record.guarded_operator_intent,
        guarded_idempotency_key=record.guarded_idempotency_key,
        guarded_payload_hash=record.guarded_payload_hash,
        reveal_condition_ref=record.reveal_condition_ref,
        trigger_evidence_ref=record.trigger_evidence_ref,
        condition_snapshot_ref=record.condition_snapshot_ref,
        evidence_source=record.evidence_source,
        reconciliation_plan_id=record.reconciliation_plan_id,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        cap_guard_decision_id=record.cap_guard_decision_id,
        route=record.route,
        method=record.method,
        action_class=record.action_class,
        required_permission=record.required_permission,
        service_method=record.service_method,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        correlation_id=record.correlation_id,
        payload_hash=record.payload_hash,
        audit_id=record.audit_id,
        dry_run=record.dry_run,
        operator_reason=record.operator_reason,
        manual_live_acknowledgement=record.manual_live_acknowledgement,
        source=record.source,
        proof_persisted=record.proof_persisted,
        reveal_trigger_verified=record.reveal_trigger_verified,
        manager_invocation_ran=record.manager_invocation_ran,
        trigger_evaluation_ran=record.trigger_evaluation_ran,
        should_trigger_reveal_called=record.should_trigger_reveal_called,
        reveal_order_slice_called=record.reveal_order_slice_called,
        coinbase_read_attempted=record.coinbase_read_attempted,
        coinbase_read_succeeded=record.coinbase_read_succeeded,
        coinbase_rest_read_ran=record.coinbase_rest_read_ran,
        coinbase_order_submitted=record.coinbase_order_submitted,
        coinbase_order_cancel_submitted=record.coinbase_order_cancel_submitted,
        active_placement_cancel_replace_ran=(
            record.active_placement_cancel_replace_ran
        ),
        reconciliation_executed=record.reconciliation_executed,
        order_state_mutated=record.order_state_mutated,
        lifecycle_state_mutated=record.lifecycle_state_mutated,
        exchange_state_mutated=record.exchange_state_mutated,
        live_exchange_submitted=record.live_exchange_submitted,
        live_coinbase_orders_ran=record.live_coinbase_orders_ran,
        browser_authority=record.browser_authority,
        bff_authority=record.bff_authority,
        detail=(
            "Stealth reveal-trigger proof is backend-owned append-only "
            "evidence only. It does not evaluate triggers, call "
            "should_trigger_reveal, call reveal_order_slice, invoke managers, "
            "call Coinbase, mutate lifecycle state, or execute reconciliation."
        ),
    )


def _stealth_manager_policy_proof_item_from_record(
    record: StealthManagerInvocationPolicyProofRecord,
) -> StealthManagerInvocationPolicyProofRecordItem:
    return StealthManagerInvocationPolicyProofRecordItem(
        manager_policy_proof_id=record.manager_policy_proof_id,
        recorded_at=record.recorded_at,
        mutation_family=record.mutation_family,
        stealth_order_id=record.stealth_order_id,
        guarded_command_route=record.guarded_command_route,
        guarded_command_method=record.guarded_command_method,
        guarded_service_method=record.guarded_service_method,
        guarded_mutation_family=record.guarded_mutation_family,
        guarded_actor_id=record.guarded_actor_id,
        guarded_operator_intent=record.guarded_operator_intent,
        guarded_idempotency_key=record.guarded_idempotency_key,
        guarded_payload_hash=record.guarded_payload_hash,
        manager_policy_ref=record.manager_policy_ref,
        mutation_lock_policy_ref=record.mutation_lock_policy_ref,
        exchange_reality_policy_ref=record.exchange_reality_policy_ref,
        evidence_source=record.evidence_source,
        reconciliation_plan_id=record.reconciliation_plan_id,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        cap_guard_decision_id=record.cap_guard_decision_id,
        route=record.route,
        method=record.method,
        action_class=record.action_class,
        required_permission=record.required_permission,
        service_method=record.service_method,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        correlation_id=record.correlation_id,
        payload_hash=record.payload_hash,
        audit_id=record.audit_id,
        dry_run=record.dry_run,
        operator_reason=record.operator_reason,
        manual_live_acknowledgement=record.manual_live_acknowledgement,
        source=record.source,
        proof_persisted=record.proof_persisted,
        manager_policy_verified=record.manager_policy_verified,
        manager_invocation_allowed=record.manager_invocation_allowed,
        manager_invocation_ran=record.manager_invocation_ran,
        mutation_lock_policy_verified=record.mutation_lock_policy_verified,
        exchange_reality_policy_verified=record.exchange_reality_policy_verified,
        coinbase_read_attempted=record.coinbase_read_attempted,
        coinbase_read_succeeded=record.coinbase_read_succeeded,
        coinbase_rest_read_ran=record.coinbase_rest_read_ran,
        coinbase_order_submitted=record.coinbase_order_submitted,
        coinbase_order_cancel_submitted=record.coinbase_order_cancel_submitted,
        active_placement_cancel_replace_ran=(
            record.active_placement_cancel_replace_ran
        ),
        reconciliation_executed=record.reconciliation_executed,
        order_state_mutated=record.order_state_mutated,
        lifecycle_state_mutated=record.lifecycle_state_mutated,
        exchange_state_mutated=record.exchange_state_mutated,
        live_exchange_submitted=record.live_exchange_submitted,
        live_coinbase_orders_ran=record.live_coinbase_orders_ran,
        browser_authority=record.browser_authority,
        bff_authority=record.bff_authority,
        detail=(
            "Stealth manager-invocation policy proof is backend-owned "
            "append-only evidence only. It does not invoke StealthOrderManager, "
            "call Coinbase, cancel or replace placements, mutate state, or "
            "execute reconciliation."
        ),
    )


def _stealth_recovery_proof_item_from_record(
    record: StealthRecoveryProofRecord,
) -> StealthRecoveryProofRecordItem:
    return StealthRecoveryProofRecordItem(
        recovery_proof_id=record.recovery_proof_id,
        recorded_at=record.recorded_at,
        mutation_family=record.mutation_family,
        stealth_order_id=record.stealth_order_id,
        guarded_command_route=record.guarded_command_route,
        guarded_command_method=record.guarded_command_method,
        guarded_service_method=record.guarded_service_method,
        guarded_actor_id=record.guarded_actor_id,
        guarded_operator_intent=record.guarded_operator_intent,
        guarded_idempotency_key=record.guarded_idempotency_key,
        guarded_payload_hash=record.guarded_payload_hash,
        recovery_evidence_ref=record.recovery_evidence_ref,
        recovery_plan_ref=record.recovery_plan_ref,
        evidence_source=record.evidence_source,
        reconciliation_plan_id=record.reconciliation_plan_id,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        cap_guard_decision_id=record.cap_guard_decision_id,
        route=record.route,
        method=record.method,
        action_class=record.action_class,
        required_permission=record.required_permission,
        service_method=record.service_method,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        correlation_id=record.correlation_id,
        payload_hash=record.payload_hash,
        audit_id=record.audit_id,
        dry_run=record.dry_run,
        operator_reason=record.operator_reason,
        manual_live_acknowledgement=record.manual_live_acknowledgement,
        source=record.source,
        proof_persisted=record.proof_persisted,
        recovery_proof_verified=record.recovery_proof_verified,
        manager_invocation_ran=record.manager_invocation_ran,
        recovery_plan_built=record.recovery_plan_built,
        recovery_repair_executed=record.recovery_repair_executed,
        rollback_executed=record.rollback_executed,
        coinbase_read_attempted=record.coinbase_read_attempted,
        coinbase_read_succeeded=record.coinbase_read_succeeded,
        coinbase_rest_read_ran=record.coinbase_rest_read_ran,
        coinbase_order_submitted=record.coinbase_order_submitted,
        coinbase_order_cancel_submitted=record.coinbase_order_cancel_submitted,
        active_placement_cancel_replace_ran=(
            record.active_placement_cancel_replace_ran
        ),
        reconciliation_executed=record.reconciliation_executed,
        order_state_mutated=record.order_state_mutated,
        lifecycle_state_mutated=record.lifecycle_state_mutated,
        exchange_state_mutated=record.exchange_state_mutated,
        live_exchange_submitted=record.live_exchange_submitted,
        live_coinbase_orders_ran=record.live_coinbase_orders_ran,
        browser_authority=record.browser_authority,
        bff_authority=record.bff_authority,
        detail=(
            "Stealth recovery proof is backend-owned append-only evidence only. "
            "It does not repair state, roll back state, invoke managers, call "
            "Coinbase, cancel/replace placements, mutate lifecycle state, or "
            "execute reconciliation."
        ),
    )


def _stealth_reconciliation_proof_item_from_record(
    record: StealthReconciliationProofRecord,
) -> StealthReconciliationProofRecordItem:
    return StealthReconciliationProofRecordItem(
        reconciliation_proof_id=record.reconciliation_proof_id,
        recorded_at=record.recorded_at,
        mutation_family=record.mutation_family,
        stealth_order_id=record.stealth_order_id,
        guarded_command_route=record.guarded_command_route,
        guarded_command_method=record.guarded_command_method,
        guarded_service_method=record.guarded_service_method,
        guarded_actor_id=record.guarded_actor_id,
        guarded_operator_intent=record.guarded_operator_intent,
        guarded_idempotency_key=record.guarded_idempotency_key,
        guarded_payload_hash=record.guarded_payload_hash,
        reconciliation_evidence_ref=record.reconciliation_evidence_ref,
        reconciliation_plan_ref=record.reconciliation_plan_ref,
        active_placement_evidence_ref=record.active_placement_evidence_ref,
        evidence_source=record.evidence_source,
        reconciliation_plan_id=record.reconciliation_plan_id,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        cap_guard_decision_id=record.cap_guard_decision_id,
        route=record.route,
        method=record.method,
        action_class=record.action_class,
        required_permission=record.required_permission,
        service_method=record.service_method,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        correlation_id=record.correlation_id,
        payload_hash=record.payload_hash,
        audit_id=record.audit_id,
        dry_run=record.dry_run,
        operator_reason=record.operator_reason,
        manual_live_acknowledgement=record.manual_live_acknowledgement,
        source=record.source,
        proof_persisted=record.proof_persisted,
        reconciliation_proof_verified=record.reconciliation_proof_verified,
        manager_invocation_ran=record.manager_invocation_ran,
        reconciliation_plan_built=record.reconciliation_plan_built,
        reconciliation_execution_ran=record.reconciliation_execution_ran,
        coinbase_read_attempted=record.coinbase_read_attempted,
        coinbase_read_succeeded=record.coinbase_read_succeeded,
        coinbase_rest_read_ran=record.coinbase_rest_read_ran,
        coinbase_order_submitted=record.coinbase_order_submitted,
        coinbase_order_cancel_submitted=record.coinbase_order_cancel_submitted,
        active_placement_cancel_replace_ran=(
            record.active_placement_cancel_replace_ran
        ),
        reconciliation_executed=record.reconciliation_executed,
        order_state_mutated=record.order_state_mutated,
        lifecycle_state_mutated=record.lifecycle_state_mutated,
        exchange_state_mutated=record.exchange_state_mutated,
        live_exchange_submitted=record.live_exchange_submitted,
        live_coinbase_orders_ran=record.live_coinbase_orders_ran,
        browser_authority=record.browser_authority,
        bff_authority=record.bff_authority,
        detail=(
            "Stealth reconciliation proof is backend-owned append-only "
            "evidence only. It does not execute reconciliation, invoke "
            "managers, call Coinbase, cancel/replace placements, mutate "
            "lifecycle state, or mutate order/exchange state."
        ),
    )


def _stealth_cancel_replace_proof_item_from_record(
    record: StealthCancelReplaceProofRecord,
) -> StealthCancelReplaceProofRecordItem:
    return StealthCancelReplaceProofRecordItem(
        cancel_replace_proof_id=record.cancel_replace_proof_id,
        recorded_at=record.recorded_at,
        mutation_family=record.mutation_family,
        stealth_order_id=record.stealth_order_id,
        guarded_command_route=record.guarded_command_route,
        guarded_command_method=record.guarded_command_method,
        guarded_service_method=record.guarded_service_method,
        guarded_mutation_family=record.guarded_mutation_family,
        guarded_actor_id=record.guarded_actor_id,
        guarded_operator_intent=record.guarded_operator_intent,
        guarded_idempotency_key=record.guarded_idempotency_key,
        guarded_payload_hash=record.guarded_payload_hash,
        active_placement_evidence_ref=record.active_placement_evidence_ref,
        mutation_claim_evidence_ref=record.mutation_claim_evidence_ref,
        cancel_replace_evidence_ref=record.cancel_replace_evidence_ref,
        evidence_source=record.evidence_source,
        reconciliation_plan_id=record.reconciliation_plan_id,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        cap_guard_decision_id=record.cap_guard_decision_id,
        route=record.route,
        method=record.method,
        action_class=record.action_class,
        required_permission=record.required_permission,
        service_method=record.service_method,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        correlation_id=record.correlation_id,
        payload_hash=record.payload_hash,
        audit_id=record.audit_id,
        dry_run=record.dry_run,
        operator_reason=record.operator_reason,
        manual_live_acknowledgement=record.manual_live_acknowledgement,
        source=record.source,
        proof_persisted=record.proof_persisted,
        cancel_replace_proof_verified=record.cancel_replace_proof_verified,
        manager_invocation_ran=record.manager_invocation_ran,
        cancel_replace_plan_built=record.cancel_replace_plan_built,
        coinbase_read_attempted=record.coinbase_read_attempted,
        coinbase_read_succeeded=record.coinbase_read_succeeded,
        coinbase_rest_read_ran=record.coinbase_rest_read_ran,
        coinbase_order_submitted=record.coinbase_order_submitted,
        coinbase_order_cancel_submitted=record.coinbase_order_cancel_submitted,
        active_placement_cancel_replace_ran=(
            record.active_placement_cancel_replace_ran
        ),
        reconciliation_executed=record.reconciliation_executed,
        order_state_mutated=record.order_state_mutated,
        lifecycle_state_mutated=record.lifecycle_state_mutated,
        exchange_state_mutated=record.exchange_state_mutated,
        live_exchange_submitted=record.live_exchange_submitted,
        live_coinbase_orders_ran=record.live_coinbase_orders_ran,
        browser_authority=record.browser_authority,
        bff_authority=record.bff_authority,
        detail=(
            "Stealth cancel/replace proof is backend-owned append-only "
            "evidence only. It does not invoke managers, call Coinbase, "
            "cancel or replace placements, mutate lifecycle/order/exchange "
            "state, or execute reconciliation."
        ),
    )


def _stealth_post_write_reconciliation_proof_item_from_record(
    record: StealthPostWriteReconciliationProofRecord,
) -> StealthPostWriteReconciliationProofRecordItem:
    return StealthPostWriteReconciliationProofRecordItem(
        post_write_reconciliation_proof_id=(
            record.post_write_reconciliation_proof_id
        ),
        recorded_at=record.recorded_at,
        mutation_family=record.mutation_family,
        stealth_order_id=record.stealth_order_id,
        guarded_command_route=record.guarded_command_route,
        guarded_command_method=record.guarded_command_method,
        guarded_service_method=record.guarded_service_method,
        guarded_mutation_family=record.guarded_mutation_family,
        guarded_actor_id=record.guarded_actor_id,
        guarded_operator_intent=record.guarded_operator_intent,
        guarded_idempotency_key=record.guarded_idempotency_key,
        guarded_payload_hash=record.guarded_payload_hash,
        route_bound_reconciliation_plan_ref=(
            record.route_bound_reconciliation_plan_ref
        ),
        post_write_execution_journal_ref=record.post_write_execution_journal_ref,
        post_write_completion_proof_ref=record.post_write_completion_proof_ref,
        evidence_source=record.evidence_source,
        reconciliation_plan_id=record.reconciliation_plan_id,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        cap_guard_decision_id=record.cap_guard_decision_id,
        route=record.route,
        method=record.method,
        action_class=record.action_class,
        required_permission=record.required_permission,
        service_method=record.service_method,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        correlation_id=record.correlation_id,
        payload_hash=record.payload_hash,
        audit_id=record.audit_id,
        dry_run=record.dry_run,
        operator_reason=record.operator_reason,
        manual_live_acknowledgement=record.manual_live_acknowledgement,
        source=record.source,
        proof_persisted=record.proof_persisted,
        post_write_reconciliation_verified=(
            record.post_write_reconciliation_verified
        ),
        route_bound_reconciliation_plan_recorded=(
            record.route_bound_reconciliation_plan_recorded
        ),
        execution_journal_accepted=record.execution_journal_accepted,
        completion_proof_recorded=record.completion_proof_recorded,
        manager_invocation_ran=record.manager_invocation_ran,
        reconciliation_plan_built=record.reconciliation_plan_built,
        reconciliation_execution_ran=record.reconciliation_execution_ran,
        coinbase_read_attempted=record.coinbase_read_attempted,
        coinbase_read_succeeded=record.coinbase_read_succeeded,
        coinbase_rest_read_ran=record.coinbase_rest_read_ran,
        coinbase_order_submitted=record.coinbase_order_submitted,
        coinbase_order_cancel_submitted=record.coinbase_order_cancel_submitted,
        active_placement_cancel_replace_ran=(
            record.active_placement_cancel_replace_ran
        ),
        reconciliation_executed=record.reconciliation_executed,
        order_state_mutated=record.order_state_mutated,
        lifecycle_state_mutated=record.lifecycle_state_mutated,
        exchange_state_mutated=record.exchange_state_mutated,
        live_exchange_submitted=record.live_exchange_submitted,
        live_coinbase_orders_ran=record.live_coinbase_orders_ran,
        browser_authority=record.browser_authority,
        bff_authority=record.bff_authority,
        detail=(
            "Stealth post-write reconciliation proof is backend-owned "
            "append-only evidence only. It records a reviewed plan, journal "
            "reference, and completion reference without invoking managers, "
            "calling Coinbase, mutating lifecycle/order/exchange state, or "
            "executing reconciliation."
        ),
    )


def _stealth_post_write_execution_journal_item_from_record(
    record: StealthPostWriteExecutionJournalAcceptanceRecord,
) -> StealthPostWriteExecutionJournalRecordItem:
    return StealthPostWriteExecutionJournalRecordItem(
        execution_journal_acceptance_id=record.execution_journal_acceptance_id,
        recorded_at=record.recorded_at,
        mutation_family=record.mutation_family,
        post_write_reconciliation_proof_id=(
            record.post_write_reconciliation_proof_id
        ),
        stealth_order_id=record.stealth_order_id,
        guarded_command_route=record.guarded_command_route,
        guarded_command_method=record.guarded_command_method,
        guarded_service_method=record.guarded_service_method,
        guarded_mutation_family=record.guarded_mutation_family,
        guarded_actor_id=record.guarded_actor_id,
        guarded_operator_intent=record.guarded_operator_intent,
        guarded_idempotency_key=record.guarded_idempotency_key,
        guarded_payload_hash=record.guarded_payload_hash,
        post_write_execution_journal_ref=record.post_write_execution_journal_ref,
        evidence_source=record.evidence_source,
        reconciliation_plan_id=record.reconciliation_plan_id,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        cap_guard_decision_id=record.cap_guard_decision_id,
        route=record.route,
        method=record.method,
        action_class=record.action_class,
        required_permission=record.required_permission,
        service_method=record.service_method,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        correlation_id=record.correlation_id,
        payload_hash=record.payload_hash,
        audit_id=record.audit_id,
        dry_run=record.dry_run,
        operator_reason=record.operator_reason,
        manual_live_acknowledgement=record.manual_live_acknowledgement,
        source=record.source,
        journal_acceptance_persisted=record.journal_acceptance_persisted,
        execution_journal_accepted=record.execution_journal_accepted,
        post_write_reconciliation_verified=(
            record.post_write_reconciliation_verified
        ),
        manager_invocation_ran=record.manager_invocation_ran,
        reconciliation_execution_ran=record.reconciliation_execution_ran,
        coinbase_read_attempted=record.coinbase_read_attempted,
        coinbase_read_succeeded=record.coinbase_read_succeeded,
        coinbase_rest_read_ran=record.coinbase_rest_read_ran,
        coinbase_order_submitted=record.coinbase_order_submitted,
        coinbase_order_cancel_submitted=record.coinbase_order_cancel_submitted,
        active_placement_cancel_replace_ran=(
            record.active_placement_cancel_replace_ran
        ),
        reconciliation_executed=record.reconciliation_executed,
        order_state_mutated=record.order_state_mutated,
        lifecycle_state_mutated=record.lifecycle_state_mutated,
        exchange_state_mutated=record.exchange_state_mutated,
        live_exchange_submitted=record.live_exchange_submitted,
        live_coinbase_orders_ran=record.live_coinbase_orders_ran,
        browser_authority=record.browser_authority,
        bff_authority=record.bff_authority,
        detail=(
            "Stealth post-write execution-journal acceptance is backend-owned "
            "append-only evidence only. It accepts the recorded journal "
            "reference for the exact proof context without invoking managers, "
            "calling Coinbase, mutating lifecycle/order/exchange state, or "
            "executing reconciliation."
        ),
    )


def _stealth_post_write_reconciliation_verification_item_from_record(
    record: StealthPostWriteReconciliationVerificationRecord,
    *,
    chain_verified: bool | None = None,
) -> StealthPostWriteReconciliationVerificationRecordItem:
    verified = (
        record.post_write_reconciliation_verified
        if chain_verified is None
        else chain_verified
    )
    return StealthPostWriteReconciliationVerificationRecordItem(
        reconciliation_verification_id=record.reconciliation_verification_id,
        recorded_at=record.recorded_at,
        mutation_family=record.mutation_family,
        post_write_reconciliation_proof_id=(
            record.post_write_reconciliation_proof_id
        ),
        execution_journal_acceptance_id=record.execution_journal_acceptance_id,
        stealth_order_id=record.stealth_order_id,
        guarded_command_route=record.guarded_command_route,
        guarded_command_method=record.guarded_command_method,
        guarded_service_method=record.guarded_service_method,
        guarded_mutation_family=record.guarded_mutation_family,
        guarded_actor_id=record.guarded_actor_id,
        guarded_operator_intent=record.guarded_operator_intent,
        guarded_idempotency_key=record.guarded_idempotency_key,
        guarded_payload_hash=record.guarded_payload_hash,
        post_write_execution_journal_ref=record.post_write_execution_journal_ref,
        post_write_completion_proof_ref=record.post_write_completion_proof_ref,
        reconciliation_verification_ref=record.reconciliation_verification_ref,
        evidence_source=record.evidence_source,
        reconciliation_plan_id=record.reconciliation_plan_id,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        cap_guard_decision_id=record.cap_guard_decision_id,
        route=record.route,
        method=record.method,
        action_class=record.action_class,
        required_permission=record.required_permission,
        service_method=record.service_method,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        correlation_id=record.correlation_id,
        payload_hash=record.payload_hash,
        audit_id=record.audit_id,
        dry_run=record.dry_run,
        operator_reason=record.operator_reason,
        manual_live_acknowledgement=record.manual_live_acknowledgement,
        source=record.source,
        verification_persisted=record.verification_persisted,
        execution_journal_accepted=record.execution_journal_accepted,
        post_write_reconciliation_verified=verified,
        manager_invocation_ran=record.manager_invocation_ran,
        reconciliation_execution_ran=record.reconciliation_execution_ran,
        coinbase_read_attempted=record.coinbase_read_attempted,
        coinbase_read_succeeded=record.coinbase_read_succeeded,
        coinbase_rest_read_ran=record.coinbase_rest_read_ran,
        coinbase_order_submitted=record.coinbase_order_submitted,
        coinbase_order_cancel_submitted=record.coinbase_order_cancel_submitted,
        active_placement_cancel_replace_ran=(
            record.active_placement_cancel_replace_ran
        ),
        reconciliation_executed=record.reconciliation_executed,
        order_state_mutated=record.order_state_mutated,
        lifecycle_state_mutated=record.lifecycle_state_mutated,
        exchange_state_mutated=record.exchange_state_mutated,
        live_exchange_submitted=record.live_exchange_submitted,
        live_coinbase_orders_ran=record.live_coinbase_orders_ran,
        browser_authority=record.browser_authority,
        bff_authority=record.bff_authority,
        detail=(
            "Stealth post-write reconciliation verification is backend-owned "
            "append-only evidence only. It verifies the proof and accepted "
            "journal chain without invoking managers, calling Coinbase, "
            "mutating lifecycle/order/exchange state, or executing "
            "reconciliation."
        ),
    )


def _matching_safe_stealth_post_write_reconciliation_verifications(
    *,
    proof_records: list[StealthPostWriteReconciliationProofRecord],
    journal_records: list[StealthPostWriteExecutionJournalAcceptanceRecord],
    verification_records: list[StealthPostWriteReconciliationVerificationRecord],
) -> list[StealthPostWriteReconciliationVerificationRecord]:
    """Return unique verifications that match an exact safe proof+journal chain."""

    matches: list[StealthPostWriteReconciliationVerificationRecord] = []
    seen_verification_ids: set[str] = set()
    for proof_record in proof_records:
        if not is_safe_stealth_post_write_reconciliation_proof_record(
            proof_record
        ):
            continue
        for journal_record in journal_records:
            if not is_safe_stealth_post_write_execution_journal_record(
                journal_record
            ):
                continue
            if not post_write_execution_journal_matches_proof(
                journal_record,
                proof_record,
            ):
                continue
            for verification_record in verification_records:
                if (
                    verification_record.reconciliation_verification_id
                    in seen_verification_ids
                ):
                    continue
                if not is_safe_stealth_post_write_reconciliation_verification_record(
                    verification_record
                ):
                    continue
                if not post_write_reconciliation_verification_matches(
                    verification_record,
                    proof_record,
                    journal_record,
                ):
                    continue
                matches.append(verification_record)
                seen_verification_ids.add(
                    verification_record.reconciliation_verification_id
                )
    return matches


def _spot_recovery_execution_item_from_record(
    record: SpotRecoveryExecutionRecord,
) -> SpotRecoveryExecutionRecordItem:
    return SpotRecoveryExecutionRecordItem(
        journal_id=record.journal_id,
        recorded_at=record.recorded_at,
        mutation_family=record.mutation_family,
        client_order_id=record.client_order_id,
        rollback_plan_id=record.rollback_plan_id,
        recovery_apply_audit_id=record.recovery_apply_audit_id,
        recovery_apply_journal_id=record.recovery_apply_journal_id,
        exchange_state_proof_id=record.exchange_state_proof_id,
        reconciliation_proof_id=record.reconciliation_proof_id,
        reconciliation_plan_id=record.reconciliation_plan_id,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        cap_guard_decision_id=record.cap_guard_decision_id,
        route=record.route,
        method=record.method,
        action_class=record.action_class,
        required_permission=record.required_permission,
        service_method=record.service_method,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        correlation_id=record.correlation_id,
        payload_hash=record.payload_hash,
        audit_id=record.audit_id,
        dry_run=record.dry_run,
        operator_reason=record.operator_reason,
        manual_live_acknowledgement=record.manual_live_acknowledgement,
        source=record.source,
        repair_journal_persisted=record.repair_journal_persisted,
        state_repair_requested=record.state_repair_requested,
        repair_guard_status=record.repair_guard_status,
        repair_guard_passed=record.repair_guard_passed,
        repair_guard_failures=record.repair_guard_failures,
        repair_guard_required_chain=record.repair_guard_required_chain,
        repair_target_id=record.repair_target_id,
        expected_repair_target_id=record.expected_repair_target_id,
        pre_apply_snapshot_id=record.pre_apply_snapshot_id,
        expected_pre_apply_snapshot_id=record.expected_pre_apply_snapshot_id,
        dry_run_repair_plan_id=record.dry_run_repair_plan_id,
        expected_dry_run_repair_plan_id=record.expected_dry_run_repair_plan_id,
        repair_result_id=record.repair_result_id,
        repair_result_journal_persisted=record.repair_result_journal_persisted,
        execution_journal_accepted=record.execution_journal_accepted,
        recovery_apply_journal_accepted=record.recovery_apply_journal_accepted,
        rollback_journal_accepted=record.rollback_journal_accepted,
        recovery_apply_executed=record.recovery_apply_executed,
        rollback_executed=record.rollback_executed,
        post_apply_reconciliation_required=record.post_apply_reconciliation_required,
        post_apply_reconciliation_satisfied=record.post_apply_reconciliation_satisfied,
        repair_intent_accepted=record.repair_intent_accepted,
        state_repair_executed=record.state_repair_executed,
        order_state_mutated=record.order_state_mutated,
        exchange_state_mutated=record.exchange_state_mutated,
        reconciliation_executed=record.reconciliation_executed,
        coinbase_order_submitted=record.coinbase_order_submitted,
        coinbase_rest_read_ran=record.coinbase_rest_read_ran,
        live_exchange_submitted=record.live_exchange_submitted,
        live_coinbase_orders_ran=record.live_coinbase_orders_ran,
        browser_authority=record.browser_authority,
        bff_authority=record.bff_authority,
        detail=(
            "Spot recovery execution journal is backend-owned append-only "
            "local repair intent evidence. It is not browser authority, "
            "reconciliation execution, order/exchange-state mutation, a "
            "Coinbase read, or Coinbase order submission."
        ),
    )


def _spot_recovery_repair_result_item_from_record(
    record: SpotRecoveryRepairResultRecord,
) -> SpotRecoveryRepairResultRecordItem:
    return SpotRecoveryRepairResultRecordItem(
        repair_result_id=record.repair_result_id,
        recorded_at=record.recorded_at,
        mutation_family=record.mutation_family,
        completion_state=record.completion_state,
        client_order_id=record.client_order_id,
        journal_id=record.journal_id,
        audit_id=record.audit_id,
        rollback_plan_id=record.rollback_plan_id,
        recovery_apply_audit_id=record.recovery_apply_audit_id,
        recovery_apply_journal_id=record.recovery_apply_journal_id,
        exchange_state_proof_id=record.exchange_state_proof_id,
        reconciliation_proof_id=record.reconciliation_proof_id,
        reconciliation_plan_id=record.reconciliation_plan_id,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        cap_guard_decision_id=record.cap_guard_decision_id,
        route=record.route,
        method=record.method,
        action_class=record.action_class,
        required_permission=record.required_permission,
        service_method=record.service_method,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        correlation_id=record.correlation_id,
        payload_hash=record.payload_hash,
        repair_target_id=record.repair_target_id,
        pre_apply_snapshot_id=record.pre_apply_snapshot_id,
        dry_run_repair_plan_id=record.dry_run_repair_plan_id,
        guard_passed=record.guard_passed,
        guard_failures=record.guard_failures,
        state_repair_executed=record.state_repair_executed,
        repair_applied=record.repair_applied,
        rollback_applied=record.rollback_applied,
        post_apply_reconciliation_completed=(
            record.post_apply_reconciliation_completed
        ),
        order_state_mutated=record.order_state_mutated,
        exchange_state_mutated=record.exchange_state_mutated,
        reconciliation_executed=record.reconciliation_executed,
        coinbase_rest_read_ran=record.coinbase_rest_read_ran,
        live_exchange_submitted=record.live_exchange_submitted,
        live_coinbase_orders_ran=record.live_coinbase_orders_ran,
        browser_authority=record.browser_authority,
        bff_authority=record.bff_authority,
        detail=record.detail,
    )


def _spot_recovery_completion_item_from_record(
    record: SpotRecoveryCompletionRecord,
) -> SpotRecoveryCompletionRecordItem:
    return SpotRecoveryCompletionRecordItem(
        completion_id=record.completion_id,
        recorded_at=record.recorded_at,
        mutation_family=record.mutation_family,
        completion_state=record.completion_state,
        client_order_id=record.client_order_id,
        repair_result_id=record.repair_result_id,
        journal_id=record.journal_id,
        audit_id=record.audit_id,
        reconciliation_proof_id=record.reconciliation_proof_id,
        proof_id=record.proof_id,
        proof_audit_id=record.proof_audit_id,
        reconciliation_plan_id=record.reconciliation_plan_id,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        cap_guard_decision_id=record.cap_guard_decision_id,
        route=record.route,
        method=record.method,
        action_class=record.action_class,
        required_permission=record.required_permission,
        service_method=record.service_method,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        correlation_id=record.correlation_id,
        payload_hash=record.payload_hash,
        guard_passed=record.guard_passed,
        guard_failures=record.guard_failures,
        post_apply_reconciliation_completed=(
            record.post_apply_reconciliation_completed
        ),
        reconciliation_proof_satisfied=record.reconciliation_proof_satisfied,
        fully_reconciled=record.fully_reconciled,
        order_state_mutated=record.order_state_mutated,
        exchange_state_mutated=record.exchange_state_mutated,
        reconciliation_executed=record.reconciliation_executed,
        coinbase_rest_read_ran=record.coinbase_rest_read_ran,
        live_exchange_submitted=record.live_exchange_submitted,
        live_coinbase_orders_ran=record.live_coinbase_orders_ran,
        browser_authority=record.browser_authority,
        bff_authority=record.bff_authority,
        detail=record.detail,
    )


def _stealth_coinbase_exchange_policy_proof_item_from_record(
    record: StealthCoinbaseExchangeSubmissionPolicyProofRecord,
) -> StealthCoinbaseExchangeSubmissionPolicyProofRecordItem:
    return StealthCoinbaseExchangeSubmissionPolicyProofRecordItem(
        coinbase_exchange_policy_proof_id=record.coinbase_exchange_policy_proof_id,
        recorded_at=record.recorded_at,
        mutation_family=record.mutation_family,
        stealth_order_id=record.stealth_order_id,
        guarded_command_route=record.guarded_command_route,
        guarded_command_method=record.guarded_command_method,
        guarded_service_method=record.guarded_service_method,
        guarded_mutation_family=record.guarded_mutation_family,
        guarded_actor_id=record.guarded_actor_id,
        guarded_operator_intent=record.guarded_operator_intent,
        guarded_idempotency_key=record.guarded_idempotency_key,
        guarded_payload_hash=record.guarded_payload_hash,
        exchange_submission_policy_ref=record.exchange_submission_policy_ref,
        coinbase_cancel_policy_ref=record.coinbase_cancel_policy_ref,
        live_coinbase_read_policy_ref=record.live_coinbase_read_policy_ref,
        live_cap_evidence_ref=record.live_cap_evidence_ref,
        evidence_source=record.evidence_source,
        reconciliation_plan_id=record.reconciliation_plan_id,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        cap_guard_decision_id=record.cap_guard_decision_id,
        route=record.route,
        method=record.method,
        action_class=record.action_class,
        required_permission=record.required_permission,
        service_method=record.service_method,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        correlation_id=record.correlation_id,
        payload_hash=record.payload_hash,
        audit_id=record.audit_id,
        dry_run=record.dry_run,
        operator_reason=record.operator_reason,
        manual_live_acknowledgement=record.manual_live_acknowledgement,
        source=record.source,
        proof_persisted=record.proof_persisted,
        exchange_submission_policy_verified=(
            record.exchange_submission_policy_verified
        ),
        coinbase_submit_allowed=record.coinbase_submit_allowed,
        coinbase_cancel_allowed=record.coinbase_cancel_allowed,
        live_coinbase_read_allowed=record.live_coinbase_read_allowed,
        live_cap_verified=record.live_cap_verified,
        manager_invocation_ran=record.manager_invocation_ran,
        coinbase_read_attempted=record.coinbase_read_attempted,
        coinbase_read_succeeded=record.coinbase_read_succeeded,
        coinbase_rest_read_ran=record.coinbase_rest_read_ran,
        coinbase_order_submitted=record.coinbase_order_submitted,
        coinbase_order_cancel_submitted=record.coinbase_order_cancel_submitted,
        active_placement_cancel_replace_ran=(
            record.active_placement_cancel_replace_ran
        ),
        reconciliation_executed=record.reconciliation_executed,
        order_state_mutated=record.order_state_mutated,
        lifecycle_state_mutated=record.lifecycle_state_mutated,
        exchange_state_mutated=record.exchange_state_mutated,
        live_exchange_submitted=record.live_exchange_submitted,
        live_coinbase_orders_ran=record.live_coinbase_orders_ran,
        browser_authority=record.browser_authority,
        bff_authority=record.bff_authority,
        detail=(
            "Stealth Coinbase exchange submission policy proof is "
            "backend-owned append-only evidence only. It does not submit, "
            "cancel, or read Coinbase orders, invoke managers, execute "
            "reconciliation, or mutate stealth/order/exchange state."
        ),
    )


def _stealth_state_mutation_policy_item_from_record(
    record: StealthStateMutationPolicyProofRecord,
) -> StealthStateMutationPolicyProofRecordItem:
    return StealthStateMutationPolicyProofRecordItem(
        state_mutation_policy_proof_id=record.state_mutation_policy_proof_id,
        recorded_at=record.recorded_at,
        mutation_family=record.mutation_family,
        stealth_order_id=record.stealth_order_id,
        guarded_command_route=record.guarded_command_route,
        guarded_command_method=record.guarded_command_method,
        guarded_service_method=record.guarded_service_method,
        guarded_mutation_family=record.guarded_mutation_family,
        guarded_actor_id=record.guarded_actor_id,
        guarded_operator_intent=record.guarded_operator_intent,
        guarded_idempotency_key=record.guarded_idempotency_key,
        guarded_payload_hash=record.guarded_payload_hash,
        state_mutation_policy_ref=record.state_mutation_policy_ref,
        lifecycle_state_policy_ref=record.lifecycle_state_policy_ref,
        order_state_policy_ref=record.order_state_policy_ref,
        exchange_state_policy_ref=record.exchange_state_policy_ref,
        post_write_reconciliation_policy_ref=(
            record.post_write_reconciliation_policy_ref
        ),
        evidence_source=record.evidence_source,
        reconciliation_plan_id=record.reconciliation_plan_id,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        cap_guard_decision_id=record.cap_guard_decision_id,
        route=record.route,
        method=record.method,
        action_class=record.action_class,
        required_permission=record.required_permission,
        service_method=record.service_method,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        correlation_id=record.correlation_id,
        payload_hash=record.payload_hash,
        audit_id=record.audit_id,
        dry_run=record.dry_run,
        operator_reason=record.operator_reason,
        manual_live_acknowledgement=record.manual_live_acknowledgement,
        source=record.source,
        proof_persisted=record.proof_persisted,
        state_mutation_policy_verified=record.state_mutation_policy_verified,
        state_mutation_allowed=record.state_mutation_allowed,
        lifecycle_state_mutation_allowed=(
            record.lifecycle_state_mutation_allowed
        ),
        order_state_mutation_allowed=record.order_state_mutation_allowed,
        exchange_state_mutation_allowed=record.exchange_state_mutation_allowed,
        manager_invocation_ran=record.manager_invocation_ran,
        reconciliation_plan_built=record.reconciliation_plan_built,
        reconciliation_execution_ran=record.reconciliation_execution_ran,
        coinbase_read_attempted=record.coinbase_read_attempted,
        coinbase_read_succeeded=record.coinbase_read_succeeded,
        coinbase_rest_read_ran=record.coinbase_rest_read_ran,
        coinbase_order_submitted=record.coinbase_order_submitted,
        coinbase_order_cancel_submitted=record.coinbase_order_cancel_submitted,
        active_placement_cancel_replace_ran=(
            record.active_placement_cancel_replace_ran
        ),
        reconciliation_executed=record.reconciliation_executed,
        order_state_mutated=record.order_state_mutated,
        lifecycle_state_mutated=record.lifecycle_state_mutated,
        exchange_state_mutated=record.exchange_state_mutated,
        live_exchange_submitted=record.live_exchange_submitted,
        live_coinbase_orders_ran=record.live_coinbase_orders_ran,
        browser_authority=record.browser_authority,
        bff_authority=record.bff_authority,
        detail=(
            "Stealth state-mutation policy proof is backend-owned append-only "
            "evidence only. It does not authorize or perform lifecycle, order, "
            "or exchange-state mutation, call Coinbase, invoke managers, "
            "cancel or replace placements, or execute reconciliation."
        ),
    )


def _stealth_post_write_reconciliation_policy_item_from_record(
    record: StealthPostWriteReconciliationExecutionPolicyProofRecord,
) -> StealthPostWriteReconciliationExecutionPolicyProofRecordItem:
    return StealthPostWriteReconciliationExecutionPolicyProofRecordItem(
        post_write_reconciliation_policy_proof_id=(
            record.post_write_reconciliation_policy_proof_id
        ),
        recorded_at=record.recorded_at,
        mutation_family=record.mutation_family,
        stealth_order_id=record.stealth_order_id,
        guarded_command_route=record.guarded_command_route,
        guarded_command_method=record.guarded_command_method,
        guarded_service_method=record.guarded_service_method,
        guarded_mutation_family=record.guarded_mutation_family,
        guarded_actor_id=record.guarded_actor_id,
        guarded_operator_intent=record.guarded_operator_intent,
        guarded_idempotency_key=record.guarded_idempotency_key,
        guarded_payload_hash=record.guarded_payload_hash,
        post_write_reconciliation_execution_policy_ref=(
            record.post_write_reconciliation_execution_policy_ref
        ),
        route_bound_reconciliation_plan_ref=(
            record.route_bound_reconciliation_plan_ref
        ),
        post_write_execution_journal_policy_ref=(
            record.post_write_execution_journal_policy_ref
        ),
        post_write_reconciliation_verification_policy_ref=(
            record.post_write_reconciliation_verification_policy_ref
        ),
        safe_reconciliation_chain_ref=record.safe_reconciliation_chain_ref,
        evidence_source=record.evidence_source,
        reconciliation_plan_id=record.reconciliation_plan_id,
        approval_snapshot_id=record.approval_snapshot_id,
        admission_audit_id=record.admission_audit_id,
        cap_guard_decision_id=record.cap_guard_decision_id,
        route=record.route,
        method=record.method,
        action_class=record.action_class,
        required_permission=record.required_permission,
        service_method=record.service_method,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        correlation_id=record.correlation_id,
        payload_hash=record.payload_hash,
        audit_id=record.audit_id,
        dry_run=record.dry_run,
        operator_reason=record.operator_reason,
        manual_live_acknowledgement=record.manual_live_acknowledgement,
        source=record.source,
        proof_persisted=record.proof_persisted,
        post_write_reconciliation_execution_policy_verified=(
            record.post_write_reconciliation_execution_policy_verified
        ),
        post_write_reconciliation_execution_allowed=(
            record.post_write_reconciliation_execution_allowed
        ),
        route_bound_reconciliation_plan_required=(
            record.route_bound_reconciliation_plan_required
        ),
        execution_journal_required=record.execution_journal_required,
        reconciliation_verification_required=(
            record.reconciliation_verification_required
        ),
        safe_reconciliation_chain_verified=(
            record.safe_reconciliation_chain_verified
        ),
        manager_invocation_ran=record.manager_invocation_ran,
        reconciliation_plan_built=record.reconciliation_plan_built,
        reconciliation_execution_ran=record.reconciliation_execution_ran,
        coinbase_read_attempted=record.coinbase_read_attempted,
        coinbase_read_succeeded=record.coinbase_read_succeeded,
        coinbase_rest_read_ran=record.coinbase_rest_read_ran,
        coinbase_order_submitted=record.coinbase_order_submitted,
        coinbase_order_cancel_submitted=record.coinbase_order_cancel_submitted,
        active_placement_cancel_replace_ran=(
            record.active_placement_cancel_replace_ran
        ),
        reconciliation_executed=record.reconciliation_executed,
        order_state_mutated=record.order_state_mutated,
        lifecycle_state_mutated=record.lifecycle_state_mutated,
        exchange_state_mutated=record.exchange_state_mutated,
        live_exchange_submitted=record.live_exchange_submitted,
        live_coinbase_orders_ran=record.live_coinbase_orders_ran,
        browser_authority=record.browser_authority,
        bff_authority=record.bff_authority,
        detail=(
            "Stealth post-write reconciliation execution policy proof is "
            "backend-owned append-only evidence only. It does not execute "
            "reconciliation, call Coinbase, invoke managers, cancel or "
            "replace placements, or mutate stealth/order/exchange state."
        ),
    )


class AdminApiReadService:
    """Read-only status service for operator views.

    The current implementation delegates to existing dashboard payload builders
    without using the dashboard WebSocket transport. These methods must remain
    read-only.
    """

    def __init__(
        self,
        *,
        spot_recovery_proof_store: FileSpotRecoveryProofStore | None = None,
        spot_recovery_snapshot_store: FileSpotRecoverySnapshotStore | None = None,
        spot_recovery_execution_store: (
            FileSpotRecoveryExecutionJournalStore | None
        ) = None,
        spot_recovery_repair_result_store: (
            FileSpotRecoveryRepairResultJournalStore | None
        ) = None,
        spot_recovery_completion_store: (
            FileSpotRecoveryCompletionJournalStore | None
        ) = None,
        stealth_exchange_truth_snapshot_store: (
            FileStealthExchangeTruthSnapshotStore | None
        ) = None,
        stealth_exchange_truth_proof_store: (
            FileStealthExchangeTruthProofStore | None
        ) = None,
        stealth_lifecycle_write_guard_proof_store: (
            FileStealthLifecycleWriteGuardProofStore | None
        ) = None,
        stealth_mutation_claim_proof_store: (
            FileStealthMutationClaimProofStore | None
        ) = None,
        stealth_manager_policy_proof_store: (
            FileStealthManagerInvocationPolicyProofStore | None
        ) = None,
        stealth_coinbase_exchange_policy_proof_store: (
            FileStealthCoinbaseExchangeSubmissionPolicyProofStore | None
        ) = None,
        stealth_state_mutation_policy_proof_store: (
            FileStealthStateMutationPolicyProofStore | None
        ) = None,
        stealth_post_write_reconciliation_policy_proof_store: (
            FileStealthPostWriteReconciliationExecutionPolicyProofStore | None
        ) = None,
        stealth_reveal_trigger_proof_store: (
            FileStealthRevealTriggerProofStore | None
        ) = None,
        stealth_recovery_proof_store: (
            FileStealthRecoveryProofStore | None
        ) = None,
        stealth_reconciliation_proof_store: (
            FileStealthReconciliationProofStore | None
        ) = None,
        stealth_cancel_replace_proof_store: (
            FileStealthCancelReplaceProofStore | None
        ) = None,
        stealth_post_write_reconciliation_proof_store: (
            FileStealthPostWriteReconciliationProofStore | None
        ) = None,
        stealth_post_write_execution_journal_store: (
            FileStealthPostWriteExecutionJournalStore | None
        ) = None,
        stealth_post_write_reconciliation_verification_store: (
            FileStealthPostWriteReconciliationVerificationStore | None
        ) = None,
    ) -> None:
        self.spot_recovery_proof_store = (
            spot_recovery_proof_store or FileSpotRecoveryProofStore()
        )
        self.spot_recovery_snapshot_store = (
            spot_recovery_snapshot_store or FileSpotRecoverySnapshotStore()
        )
        self.spot_recovery_execution_store = (
            spot_recovery_execution_store or FileSpotRecoveryExecutionJournalStore()
        )
        self.spot_recovery_repair_result_store = (
            spot_recovery_repair_result_store
            or FileSpotRecoveryRepairResultJournalStore()
        )
        self.spot_recovery_completion_store = (
            spot_recovery_completion_store
            or FileSpotRecoveryCompletionJournalStore()
        )
        self.stealth_exchange_truth_snapshot_store = (
            stealth_exchange_truth_snapshot_store
            or FileStealthExchangeTruthSnapshotStore()
        )
        self.stealth_exchange_truth_proof_store = (
            stealth_exchange_truth_proof_store or FileStealthExchangeTruthProofStore()
        )
        self.stealth_lifecycle_write_guard_proof_store = (
            stealth_lifecycle_write_guard_proof_store
            or FileStealthLifecycleWriteGuardProofStore()
        )
        self.stealth_mutation_claim_proof_store = (
            stealth_mutation_claim_proof_store
            or FileStealthMutationClaimProofStore()
        )
        self.stealth_manager_policy_proof_store = (
            stealth_manager_policy_proof_store
            or FileStealthManagerInvocationPolicyProofStore()
        )
        self.stealth_coinbase_exchange_policy_proof_store = (
            stealth_coinbase_exchange_policy_proof_store
            or FileStealthCoinbaseExchangeSubmissionPolicyProofStore()
        )
        self.stealth_state_mutation_policy_proof_store = (
            stealth_state_mutation_policy_proof_store
            or FileStealthStateMutationPolicyProofStore()
        )
        self.stealth_post_write_reconciliation_policy_proof_store = (
            stealth_post_write_reconciliation_policy_proof_store
            or FileStealthPostWriteReconciliationExecutionPolicyProofStore()
        )
        self.stealth_reveal_trigger_proof_store = (
            stealth_reveal_trigger_proof_store
            or FileStealthRevealTriggerProofStore()
        )
        self.stealth_recovery_proof_store = (
            stealth_recovery_proof_store
            or FileStealthRecoveryProofStore()
        )
        self.stealth_reconciliation_proof_store = (
            stealth_reconciliation_proof_store
            or FileStealthReconciliationProofStore()
        )
        self.stealth_cancel_replace_proof_store = (
            stealth_cancel_replace_proof_store
            or FileStealthCancelReplaceProofStore()
        )
        self.stealth_post_write_reconciliation_proof_store = (
            stealth_post_write_reconciliation_proof_store
            or FileStealthPostWriteReconciliationProofStore()
        )
        self.stealth_post_write_execution_journal_store = (
            stealth_post_write_execution_journal_store
            or FileStealthPostWriteExecutionJournalStore()
        )
        self.stealth_post_write_reconciliation_verification_store = (
            stealth_post_write_reconciliation_verification_store
            or FileStealthPostWriteReconciliationVerificationStore()
        )

    def build_admin_bootstrap(self) -> AdminBootstrapResponse:
        """Return backend association and live-action posture."""

        cors_configured = bool(os.environ.get("COINBASE_ADMIN_API_CORS_ORIGINS", "").strip())
        return AdminBootstrapResponse(
            backend_repository="s-aws/coinbase",
            api_version=API_VERSION,
            schema_version=SCHEMA_VERSION,
            environment=os.environ.get("COINBASE_ADMIN_API_ENVIRONMENT", "local"),
            mutating_routes_live_disabled=True,
            live_execution_enabled=False,
            auth_required=True,
            auth_mode=configured_auth_mode(),
            cors_configured=cors_configured,
            csrf_required=_csrf_required(),
            capabilities_route="/api/v1/admin/capabilities",
            session_route="/api/v1/admin/session",
        )

    def build_admin_health(self) -> AdminHealthResponse:
        """Return read-only API health without probing Coinbase."""

        diagnostics = []
        for item in ADMIN_API_ROUTE_INVENTORY:
            method, path = _surface_method_and_path(item.surface)
            if "WebSocket" in item.surface:
                continue
            availability = _route_availability(item.surface, item.action_class)
            diagnostics.append({
                "path": path,
                "method": method,
                "status": availability,
                "message": (
                    "Live execution disabled by backend contract"
                    if availability == AdminApiRouteAvailability.LIVE_DISABLED
                    else "Route contract is available"
                ),
            })
        failed_route_count = sum(
            1
            for diagnostic in diagnostics
            if diagnostic["status"] == AdminApiRouteAvailability.BACKEND_BLOCKED
        )
        return AdminHealthResponse(
            status=(
                AdminApiHealthStatus.BLOCKED
                if failed_route_count
                else AdminApiHealthStatus.HEALTHY
            ),
            api_version=API_VERSION,
            diagnostics=diagnostics,
            failed_route_count=failed_route_count,
        )

    def build_admin_session(
        self,
        *,
        actor: AdminApiActor,
        permissions: list[AdminApiPermission],
    ) -> AdminSessionResponse:
        """Return authenticated actor and permission evidence."""

        return AdminSessionResponse(
            status=AdminApiSessionStatus.SIGNED_IN,
            actor=actor,
            permissions=permissions,
            auth_mode=configured_auth_mode(),
        )

    def build_oidc_jwt_readiness(self) -> AdminOidcJwtReadinessResponse:
        """Return backend OIDC/JWT verifier readiness evidence."""

        readiness = build_oidc_jwt_readiness()
        jwks_reachability = "not_checked"
        jwks_failure_reason: str | None = None
        status = readiness.status
        failure_reason = readiness.failure_reason
        if not readiness.missing_env_vars:
            jwks_reachability, jwks_failure_reason = check_oidc_jwks_reachability()
            if jwks_reachability != "reachable":
                status = AdminApiVerifierReadinessStatus.BLOCKED
                failure_reason = jwks_failure_reason

        return AdminOidcJwtReadinessResponse(
            active_auth_mode=configured_auth_mode(),
            mode=readiness.mode,
            status=status,
            verifier_implemented=readiness.verifier_implemented,
            required_env_vars=list(readiness.required_env_vars),
            missing_env_vars=list(readiness.missing_env_vars),
            claims_contract=dict(readiness.claims_contract),
            failure_reason=failure_reason,
            jwks_reachability=jwks_reachability,
            jwks_failure_reason=jwks_failure_reason,
            live_coinbase_execution=readiness.live_coinbase_execution,
            notional_usdc=readiness.notional_usdc,
        )

    def build_admin_capabilities(self) -> AdminCapabilityRegistryResponse:
        """Return route capability metadata derived from the owned inventory."""

        capabilities: list[AdminCapabilityItem] = []
        for item in ADMIN_API_ROUTE_INVENTORY:
            method, path = _surface_method_and_path(item.surface)
            availability = _route_availability(item.surface, item.action_class)
            capabilities.append(
                AdminCapabilityItem(
                    module_id=item.module_id,
                    route=path,
                    method=method,
                    action_class=item.action_class,
                    permission=item.permission,
                    availability=availability,
                    live_enabled=False,
                    frontend_safe=_frontend_safe(item.surface, item.action_class),
                    shared_method=item.shared_method,
                    idempotency=item.idempotency,
                    approval=item.approval,
                    caps=item.caps,
                    audit=item.audit,
                    command_contract=method == "POST"
                    and item.action_class != AdminApiActionClass.READ_ONLY,
                    compatibility_mode=item.compatibility_mode,
                    parity_test=item.parity_test,
                    notes=(
                        "Compatibility-only legacy dashboard surface"
                        if "WebSocket" in item.surface
                        else "Backend-owned Admin API route"
                    ),
                )
            )
        return AdminCapabilityRegistryResponse(capabilities=capabilities)

    def build_enterprise_readiness(self) -> AdminEnterpriseReadinessResponse:
        """Return whole-platform M9 readiness evidence without running gates."""

        def route_groups(
            module_id: str,
        ) -> tuple[list[str], list[str], list[str], list[str]]:
            read_routes: list[str] = []
            command_routes: list[str] = []
            live_routes: list[str] = []
            evidence_routes: list[str] = []
            for item in ADMIN_API_ROUTE_INVENTORY:
                method, path = _surface_method_and_path(item.surface)
                if item.module_id != module_id:
                    continue
                route = f"{method} {path}"
                if item.action_class == AdminApiActionClass.READ_ONLY:
                    read_routes.append(route)
                    evidence_routes.append(path)
                else:
                    command_routes.append(route)
                if item.action_class in {
                    AdminApiActionClass.LIVE_EXCHANGE_PLACE,
                    AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
                }:
                    live_routes.append(route)
            return read_routes, command_routes, live_routes, sorted(set(evidence_routes))

        def action_posture(
            *,
            module_id: str,
            support_status: AdminApiModuleSupportStatus,
            read_routes: list[str],
            command_routes: list[str],
            live_routes: list[str],
            evidence_routes: list[str],
            unsupported_actions: list[str],
            command_gaps: list[AdminEnterpriseCommandGapItem],
        ) -> AdminEnterpriseModuleActionPosture:
            route_inventory_count = sum(
                1 for item in ADMIN_API_ROUTE_INVENTORY if item.module_id == module_id
            )
            route_module_id_status = (
                AdminApiGateStatus.PASSED
                if route_inventory_count > 0
                else AdminApiGateStatus.WARNING
            )
            return AdminEnterpriseModuleActionPosture(
                module_id=module_id,
                support_status=support_status,
                read_route_count=len(read_routes),
                command_route_count=len(command_routes),
                live_route_count=len(live_routes),
                evidence_route_count=len(evidence_routes),
                unsupported_action_count=len(unsupported_actions),
                command_gap_count=len(command_gaps),
                route_module_id_status=route_module_id_status,
                route_module_id_detail=(
                    f"{route_inventory_count} route inventory rows are bound to "
                    f"module_id={module_id}; enterprise readiness route lists are "
                    "derived from module_id, not path prefixes."
                ),
            )

        def module_item(
            *,
            module_id: str,
            module: str,
            primary_owner: str,
            support_status: AdminApiModuleSupportStatus,
            spot_rule_boundary: str,
            unsupported_actions: list[str] | None = None,
            command_gaps: list[AdminEnterpriseCommandGapItem] | None = None,
            identity_keys: list[str] | None = None,
            constraints: list[str] | None = None,
            verification: list[str] | None = None,
            backend_contract_refs: list[str] | None = None,
            frontend_contract_refs: list[str] | None = None,
            documentation_refs: list[str] | None = None,
        ) -> AdminEnterpriseReadinessModuleItem:
            normalized_unsupported_actions = unsupported_actions or []
            normalized_command_gaps = command_gaps or []
            read_routes, command_routes, live_routes, evidence_routes = route_groups(
                module_id
            )
            return AdminEnterpriseReadinessModuleItem(
                module_id=module_id,
                module=module,
                primary_owner=primary_owner,
                support_status=support_status,
                read_routes=read_routes,
                command_routes=command_routes,
                live_routes=live_routes,
                unsupported_actions=normalized_unsupported_actions,
                command_gaps=normalized_command_gaps,
                identity_keys=identity_keys or [],
                constraints=constraints or [],
                evidence_routes=evidence_routes,
                verification=verification or [],
                backend_contract_refs=backend_contract_refs or [],
                frontend_contract_refs=frontend_contract_refs or [],
                documentation_refs=documentation_refs or [],
                spot_rule_boundary=spot_rule_boundary,
                action_posture=action_posture(
                    module_id=module_id,
                    support_status=support_status,
                    read_routes=read_routes,
                    command_routes=command_routes,
                    live_routes=live_routes,
                    evidence_routes=evidence_routes,
                    unsupported_actions=normalized_unsupported_actions,
                    command_gaps=normalized_command_gaps,
                ),
            )

        def command_gap(
            *,
            action: str,
            status: AdminApiModuleSupportStatus,
            reason: str,
            required_backend_contract: str,
            frontend_boundary: str,
        ) -> AdminEnterpriseCommandGapItem:
            return AdminEnterpriseCommandGapItem(
                action=action,
                status=status,
                reason=reason,
                required_backend_contract=required_backend_contract,
                frontend_boundary=frontend_boundary,
            )

        def functionality_item(
            *,
            workflow_id: str,
            module_id: str,
            module: str,
            workflow_type: AdminApiFunctionalityWorkflowType,
            exposure_status: AdminApiFunctionalityExposureStatus,
            support_status: AdminApiModuleSupportStatus,
            summary: str,
            backend_supported: bool,
            admin_api_exposed: bool,
            frontend_exposed: bool,
            frontend_boundary: str,
            spot_rule_boundary: str,
            command_capable: bool = False,
            live_designated: bool = False,
            live_enabled: bool = False,
            read_routes: list[str] | None = None,
            command_routes: list[str] | None = None,
            recovery_routes: list[str] | None = None,
            automation_routes: list[str] | None = None,
            legacy_surfaces: list[str] | None = None,
            identity_keys: list[str] | None = None,
            backend_contract_refs: list[str] | None = None,
            frontend_contract_refs: list[str] | None = None,
            documentation_refs: list[str] | None = None,
            required_next_contract: str | None = None,
            blockers: list[str] | None = None,
        ) -> AdminEnterpriseFunctionalityInventoryItem:
            return AdminEnterpriseFunctionalityInventoryItem(
                workflow_id=workflow_id,
                module_id=module_id,
                module=module,
                workflow_type=workflow_type,
                exposure_status=exposure_status,
                support_status=support_status,
                summary=summary,
                backend_supported=backend_supported,
                admin_api_exposed=admin_api_exposed,
                frontend_exposed=frontend_exposed,
                command_capable=command_capable,
                live_designated=live_designated,
                live_enabled=live_enabled,
                read_routes=read_routes or [],
                command_routes=command_routes or [],
                recovery_routes=recovery_routes or [],
                automation_routes=automation_routes or [],
                legacy_surfaces=legacy_surfaces or [],
                identity_keys=identity_keys or [],
                backend_contract_refs=backend_contract_refs or [],
                frontend_contract_refs=frontend_contract_refs or [],
                documentation_refs=documentation_refs or [],
                required_next_contract=required_next_contract,
                blockers=blockers or [],
                frontend_boundary=frontend_boundary,
                spot_rule_boundary=spot_rule_boundary,
            )

        def route_inventory_item(surface: str):
            for item in ADMIN_API_ROUTE_INVENTORY:
                if item.surface == surface:
                    return item
            raise KeyError(f"Admin API route inventory surface not found: {surface}")

        def mutation_taxonomy_item(
            *,
            mutation_id: str,
            mutation_family: AdminApiMutationFamilyType,
            workflow_id: str,
            module_id: str,
            module: str,
            exposure_status: AdminApiFunctionalityExposureStatus,
            support_status: AdminApiModuleSupportStatus,
            summary: str,
            identity_keys: list[str],
            idempotency_contract: str,
            approval_contract: str,
            cap_guard_contract: str,
            admission_audit_contract: str,
            reconciliation_contract: str,
            owning_backend_service: str,
            frontend_boundary: str,
            spot_rule_boundary: str,
            command_surfaces: list[str] | None = None,
            related_workflow_ids: list[str] | None = None,
            action_classes: list[AdminApiActionClass] | None = None,
            required_permissions: list[AdminApiPermission | str] | None = None,
            payload_binding_fields: list[str] | None = None,
            shared_command_service_method: str | None = None,
            route_inventory_refs: list[str] | None = None,
            backend_contract_refs: list[str] | None = None,
            frontend_contract_refs: list[str] | None = None,
            documentation_refs: list[str] | None = None,
            required_next_contract: str | None = None,
            blockers: list[str] | None = None,
            idempotency_required: bool = True,
            operator_intent_required: bool = True,
            rbac_required: bool = True,
            approval_required: bool = True,
            cap_guard_required: bool = True,
            admission_audit_required: bool = True,
            reconciliation_required: bool = True,
            live_adapter_required: bool = True,
            bff_boundary: str | None = None,
            route_local_boundary: str | None = None,
        ) -> AdminEnterpriseMutationTaxonomyItem:
            normalized_surfaces = command_surfaces or []
            inventory_refs = route_inventory_refs or normalized_surfaces
            return AdminEnterpriseMutationTaxonomyItem(
                mutation_id=mutation_id,
                mutation_family=mutation_family,
                workflow_id=workflow_id,
                related_workflow_ids=related_workflow_ids or [],
                module_id=module_id,
                module=module,
                exposure_status=exposure_status,
                support_status=support_status,
                summary=summary,
                command_surfaces=normalized_surfaces,
                action_classes=action_classes or [],
                required_permissions=required_permissions or [],
                identity_keys=identity_keys,
                payload_binding_fields=payload_binding_fields
                or [
                    "endpoint",
                    "actor",
                    "operator_intent",
                    "body",
                    "path_params",
                ],
                idempotency_required=idempotency_required,
                idempotency_contract=idempotency_contract,
                operator_intent_required=operator_intent_required,
                rbac_required=rbac_required,
                approval_required=approval_required,
                approval_contract=approval_contract,
                cap_guard_required=cap_guard_required,
                cap_guard_contract=cap_guard_contract,
                admission_audit_required=admission_audit_required,
                admission_audit_contract=admission_audit_contract,
                reconciliation_required=reconciliation_required,
                reconciliation_contract=reconciliation_contract,
                live_adapter_required=live_adapter_required,
                owning_backend_service=owning_backend_service,
                shared_command_service_method=shared_command_service_method,
                route_inventory_refs=inventory_refs,
                backend_contract_refs=backend_contract_refs or [],
                frontend_contract_refs=frontend_contract_refs or [],
                documentation_refs=documentation_refs or [],
                required_next_contract=required_next_contract,
                blockers=blockers or [],
                frontend_boundary=frontend_boundary,
                bff_boundary=bff_boundary
                or (
                    "BFF may forward only to backend Admin API with server-held "
                    "credentials; it must not approve or execute this mutation."
                ),
                route_local_boundary=route_local_boundary
                or (
                    "FastAPI route adapters must bind auth, RBAC, idempotency, "
                    "audit, approval, cap/guard, and reconciliation evidence; "
                    "they must not implement route-local trading behavior."
                ),
                spot_rule_boundary=spot_rule_boundary,
            )

        def mutation_taxonomy_from_surface(
            *,
            surface: str,
            mutation_id: str,
            mutation_family: AdminApiMutationFamilyType,
            workflow_id: str,
            module: str,
            exposure_status: AdminApiFunctionalityExposureStatus,
            support_status: AdminApiModuleSupportStatus,
            summary: str,
            identity_keys: list[str],
            owning_backend_service: str,
            frontend_boundary: str,
            spot_rule_boundary: str,
            related_workflow_ids: list[str] | None = None,
            backend_contract_refs: list[str] | None = None,
            frontend_contract_refs: list[str] | None = None,
            documentation_refs: list[str] | None = None,
            required_next_contract: str | None = None,
            blockers: list[str] | None = None,
            bff_boundary: str | None = None,
            route_local_boundary: str | None = None,
            live_adapter_required: bool = True,
        ) -> AdminEnterpriseMutationTaxonomyItem:
            route_row = route_inventory_item(surface)
            return mutation_taxonomy_item(
                mutation_id=mutation_id,
                mutation_family=mutation_family,
                workflow_id=workflow_id,
                related_workflow_ids=related_workflow_ids,
                module_id=route_row.module_id,
                module=module,
                exposure_status=exposure_status,
                support_status=support_status,
                summary=summary,
                command_surfaces=[route_row.surface],
                action_classes=[route_row.action_class],
                required_permissions=[route_row.permission],
                identity_keys=identity_keys,
                idempotency_contract=route_row.idempotency,
                approval_contract=route_row.approval,
                cap_guard_contract=route_row.caps,
                admission_audit_contract=route_row.audit,
                reconciliation_contract=route_row.parity_test,
                owning_backend_service=owning_backend_service,
                shared_command_service_method=route_row.shared_method,
                route_inventory_refs=[route_row.surface],
                backend_contract_refs=backend_contract_refs,
                frontend_contract_refs=frontend_contract_refs,
                documentation_refs=documentation_refs,
                required_next_contract=required_next_contract,
                blockers=blockers,
                frontend_boundary=frontend_boundary,
                bff_boundary=bff_boundary
                or (
                    "BFF may forward only to backend Admin API with server-held "
                    "credentials; it must not approve or execute this mutation."
                ),
                route_local_boundary=route_local_boundary
                or (
                    "FastAPI route adapters must bind auth, RBAC, idempotency, "
                    "audit, approval, cap/guard, and reconciliation evidence; "
                    "they must not implement route-local trading behavior."
                ),
                spot_rule_boundary=spot_rule_boundary,
                live_adapter_required=live_adapter_required,
            )

        modules = [
            module_item(
                module_id="admin_system_health",
                module="Admin / System Health",
                primary_owner="admin_api_contract",
                support_status=AdminApiModuleSupportStatus.PLATFORM_READY,
                unsupported_actions=[
                    "browser-run backend tests",
                    "browser-held backend secrets",
                    "browser-side live execution authority",
                ],
                command_gaps=[
                    command_gap(
                        action="browser-side live execution authority",
                        status=AdminApiModuleSupportStatus.UNSUPPORTED,
                        reason=(
                            "Live execution authority belongs to backend approval, "
                            "cap, guard, audit, and reconciliation gates."
                        ),
                        required_backend_contract=(
                            "Approved backend live command contract with cap, guard, "
                            "audit, and reconciliation evidence."
                        ),
                        frontend_boundary=(
                            "The browser may display readiness evidence but must not "
                            "be the source of live-execution approval."
                        ),
                    ),
                ],
                identity_keys=[
                    "request_id",
                    "correlation_id",
                    "actor_id",
                    "audit_id",
                ],
                constraints=[
                    "Platform primitive only; no trading behavior lives in the frontend.",
                    "Release and regression gates are external evidence, not browser actions.",
                ],
                verification=[
                    "Admin API contract regression",
                    "frontend release gate",
                    "contextless platform review",
                ],
                backend_contract_refs=[
                    "application/admin_api/read_service.py::build_enterprise_readiness",
                    "application/admin_api/route_inventory.py::ADMIN_API_ROUTE_INVENTORY",
                    "api/v1/routes/admin.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::getAdminEnterpriseReadiness",
                    "src/shared/api/contracts/backendRuntime.ts::loadAdminRuntimeSnapshot",
                    "src/features/admin-shell/AdminShell.tsx",
                ],
                documentation_refs=[
                    "README.admin-api.md",
                    "docs/ADMIN_PLATFORM_ARCHITECTURE.md",
                    "docs/ADMIN_MODULE_CAPABILITY_MATRIX.md",
                    "docs/examples/admin-api.md",
                ],
                spot_rule_boundary=(
                    "Platform primitive. Spot wallet, USDC, cost-basis, and "
                    "no-shorting rules are not generic admin-system rules."
                ),
            ),
            module_item(
                module_id="spot_operations",
                module="Spot Operations",
                primary_owner="strategy",
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                unsupported_actions=[
                    "spot short selling",
                    "browser-side wallet or cost-basis authority",
                    "frontend live order placement without backend M8 approval",
                ],
                command_gaps=[
                    command_gap(
                        action="spot short selling",
                        status=AdminApiModuleSupportStatus.UNSUPPORTED,
                        reason="Spot accounts cannot sell assets the account does not hold.",
                        required_backend_contract=(
                            "No backend contract should enable spot short selling; "
                            "spot sell authority remains inventory-backed."
                        ),
                        frontend_boundary=(
                            "Do not model a spot short draft or bypass backend wallet "
                            "and inventory authority."
                        ),
                    ),
                    command_gap(
                        action="frontend live order placement without backend M8 approval",
                        status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                        reason=(
                            "Current spot command contracts are authenticated, "
                            "idempotent, audited, and live-disabled until backend "
                            "approval, cap, guard, and reconciliation gates admit them."
                        ),
                        required_backend_contract=(
                            "M8-approved live placement contract with durable approval "
                            "snapshot, cap evidence, guard decision, audit id, and "
                            "post-live reconciliation requirement."
                        ),
                        frontend_boundary=(
                            "Keep spot command UI in no-live dry-submit mode unless "
                            "backend capability evidence explicitly enables a live path."
                        ),
                    ),
                ],
                identity_keys=["client_order_id", "campaign_id", "sweep_config_id"],
                constraints=[
                    "USDC spot scope and no-shorting rules are spot-only.",
                    "Cost basis and inventory authority stay backend-owned.",
                ],
                verification=[
                    "spot readiness regression",
                    "Admin API contract regression",
                    "contextless spot order review",
                ],
                backend_contract_refs=[
                    "business/spot_portfolio_sweep.py",
                    "business/spot_inventory_authority.py",
                    "application/admin_api/command_service.py",
                    "api/v1/routes/orders.py::run_spot_sweep_automation",
                    "api/v1/routes/spot.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::getSpotReadiness",
                    "src/shared/api/contracts/backendApiClient.ts::executeSpotCampaign",
                    "src/shared/api/contracts/backendApiClient.ts::runSpotSweepAutomation",
                    "src/features/spot-ops/spotBackendAdapters.ts",
                ],
                documentation_refs=[
                    "README.spot-trading.md",
                    "README.spot-portfolio-sweep.md",
                    "README.spot-campaign.md",
                    "docs/examples/admin-api.md",
                ],
                spot_rule_boundary=(
                    "Spot rules apply here only: no short selling, USDC spot "
                    "scope, inventory authority, cost basis, and average-cost "
                    "evidence must not be copied into non-spot modules."
                ),
            ),
            module_item(
                module_id="futures_perpetuals",
                module="Futures / Perpetuals",
                primary_owner="admin_api_contract",
                support_status=AdminApiModuleSupportStatus.READ_ONLY_READY,
                unsupported_actions=[
                    "frontend futures placement",
                    "frontend futures cancel/close/reduce",
                    "spot inventory rules in futures workflows",
                ],
                command_gaps=[
                    command_gap(
                        action="frontend futures placement",
                        status=AdminApiModuleSupportStatus.NOT_MODELED,
                        reason=(
                            "Futures/perpetual placement needs backend-owned margin, "
                            "leverage, liquidation, reduce-only, collateral, and "
                            "approval contracts before UI drafting."
                        ),
                        required_backend_contract=(
                            "POST futures/perpetual placement contract with margin, "
                            "leverage, liquidation, reduce-only, cap, approval, audit, "
                            "and reconciliation evidence."
                        ),
                        frontend_boundary=(
                            "Do not add a futures/perpetual placement draft, "
                            "dry-submit, or BFF route until the backend contract and "
                            "capability row exist."
                        ),
                    ),
                    command_gap(
                        action="frontend futures cancel/close/reduce",
                        status=AdminApiModuleSupportStatus.NOT_MODELED,
                        reason=(
                            "Futures close/reduce behavior must be derived from backend "
                            "position side, margin, liquidation, and exchange contract "
                            "semantics before a command route exists."
                        ),
                        required_backend_contract=(
                            "POST futures/perpetual close or reduce contract keyed by "
                            "position identity with reduce-only, close-only, margin, "
                            "approval, cap, audit, and reconciliation evidence."
                        ),
                        frontend_boundary=(
                            "Do not add futures cancel, close, or reduce controls from "
                            "spot cancel patterns or exchange order id evidence."
                        ),
                    ),
                    command_gap(
                        action="spot inventory rules in futures workflows",
                        status=AdminApiModuleSupportStatus.UNSUPPORTED,
                        reason=(
                            "Futures/perpetual authority is position, margin, leverage, "
                            "collateral, and liquidation aware; spot inventory is not "
                            "a futures command source."
                        ),
                        required_backend_contract=(
                            "Futures/perpetual risk authority contract over position, "
                            "margin, collateral, funding, and liquidation evidence."
                        ),
                        frontend_boundary=(
                            "Do not copy spot inventory, no-shorting, USDC, average-cost, "
                            "or cost-basis rules into futures/perpetual workflows."
                        ),
                    ),
                ],
                identity_keys=["position_key"],
                constraints=[
                    "Position side and close/reduce semantics are backend-derived.",
                    "Funding remains not modeled until a backend contract is added.",
                ],
                verification=[
                    "Admin API contract regression",
                    "frontend route coverage",
                    "contextless non-spot review",
                ],
                backend_contract_refs=[
                    "application/admin_api/read_service.py::build_futures_account",
                    "application/admin_api/read_service.py::build_futures_positions",
                    "api/v1/routes/futures.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::getFuturesAccount",
                    "src/shared/api/contracts/backendRuntime.ts::loadFuturesPerpetualsReadSnapshot",
                    "src/features/admin-shell/AdminShell.tsx",
                ],
                documentation_refs=[
                    "README.futures-perpetuals.md",
                    "docs/ADMIN_MODULE_CAPABILITY_MATRIX.md",
                    "docs/examples/admin-api.md",
                ],
                spot_rule_boundary=(
                    "Spot inventory, USDC, no-shorting, cost-basis, and "
                    "average-cost rules are forbidden as futures/perpetual "
                    "authority. Futures require position, margin, leverage, "
                    "collateral, liquidation, and reduce-only backend contracts."
                ),
            ),
            module_item(
                module_id="stealth_orders",
                module="Stealth Orders",
                primary_owner="stealth_lifecycle",
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                unsupported_actions=[
                    "cancel by exchange order id",
                    "hide-again mutation for live revealed placements",
                    "browser-side active placement mutation",
                ],
                command_gaps=[
                    command_gap(
                        action="cancel by exchange order id",
                        status=AdminApiModuleSupportStatus.UNSUPPORTED,
                        reason=(
                            "Stealth cancellation is keyed by stealth_order_id in the "
                            "Admin API; active placement ids and exchange ids are evidence only."
                        ),
                        required_backend_contract=(
                            "Existing live-disabled stealth cancel contract keyed by "
                            "stealth_order_id, with exchange handling and reconciliation "
                            "before any live enablement."
                        ),
                        frontend_boundary=(
                            "Do not expose active placement client ids or exchange order "
                            "ids as cancellation inputs."
                        ),
                    ),
                    command_gap(
                        action="hide-again mutation for live revealed placements",
                        status=AdminApiModuleSupportStatus.NOT_MODELED,
                        reason=(
                            "A revealed stealth placement can become hidden only after "
                            "the active exchange placement is cancelled or reconciled."
                        ),
                        required_backend_contract=(
                            "Backend exchange-cancel and reconciliation contract that "
                            "proves live placement state before local stealth state changes."
                        ),
                        frontend_boundary=(
                            "Do not add a hide-again control or local stealth state "
                            "mutation path in the browser."
                        ),
                    ),
                ],
                identity_keys=["stealth_order_id", "client_order_id"],
                constraints=[
                    "Local state must reflect live exchange reality.",
                    "Cancel/re-entry policy is narrower than general hide-again behavior.",
                ],
                verification=[
                    "stealth regression",
                    "Admin API contract regression",
                    "contextless module review",
                ],
                backend_contract_refs=[
                    "core/stealth_order_manager.py",
                    "bridges/stealth_order_bridge.py",
                    "api/v1/routes/stealth.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::listStealthOrders",
                    "src/shared/api/contracts/backendApiClient.ts::cancelStealthOrderByStealthOrderId",
                    "src/features/admin-shell/AdminShell.tsx",
                ],
                documentation_refs=[
                    "docs/agents/AGENT_STEALTH_LIFECYCLE.md",
                    "docs/ADMIN_MODULE_CAPABILITY_MATRIX.md",
                    "docs/examples/admin-api.md",
                ],
                spot_rule_boundary=(
                    "Stealth identity and exchange-truth rules are module-owned. "
                    "Spot wallet rules apply only through backend guard/product "
                    "capability when the stealth plan is a spot order."
                ),
            ),
            module_item(
                module_id="movement_repricing",
                module="Order Movement / Repricing",
                primary_owner="stealth_lifecycle",
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                unsupported_actions=[
                    "frontend live repricing",
                    "cooldown clearing from command draft",
                    "revealed placement mutation without exchange handling",
                ],
                command_gaps=[
                    command_gap(
                        action="frontend live repricing",
                        status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                        reason=(
                            "Movement reprice is currently a live-disabled Admin API "
                            "draft keyed by stealth_order_id; approved live repricing "
                            "would be cancel/replace-shaped."
                        ),
                        required_backend_contract=(
                            "Backend live reprice contract with cancel/replace exchange "
                            "handling, mutation claims, cooldown policy, approval, cap, "
                            "audit, and reconciliation evidence."
                        ),
                        frontend_boundary=(
                            "Keep reprice in dry-submit review and do not call the legacy "
                            "dashboard repricer from the enterprise frontend."
                        ),
                    ),
                    command_gap(
                        action="cooldown clearing from command draft",
                        status=AdminApiModuleSupportStatus.UNSUPPORTED,
                        reason="A command draft cannot clear backend repricing cooldowns.",
                        required_backend_contract=(
                            "Backend policy-controlled cooldown mutation contract, if such "
                            "behavior is ever approved."
                        ),
                        frontend_boundary=(
                            "Do not expose cooldown-clearing inputs or local cooldown "
                            "mutation in command drafts."
                        ),
                    ),
                    command_gap(
                        action="revealed placement mutation without exchange handling",
                        status=AdminApiModuleSupportStatus.NOT_MODELED,
                        reason=(
                            "Revealed placements require existing exchange cancel/move/"
                            "reconcile handling before local state can change."
                        ),
                        required_backend_contract=(
                            "Backend exchange-reality path that claims, cancels or replaces, "
                            "audits, and reconciles active placements."
                        ),
                        frontend_boundary=(
                            "Do not mutate revealed placement state or anchor state from "
                            "browser code."
                        ),
                    ),
                ],
                identity_keys=["stealth_order_id", "client_order_id"],
                constraints=[
                    "Move/reprice claim locks remain backend-owned.",
                    "Reprice command is cancel/replace-shaped and live-disabled.",
                ],
                verification=[
                    "movement/repricing regression",
                    "Admin API contract regression",
                    "contextless module review",
                ],
                backend_contract_refs=[
                    "core/stealth_order_manager.py",
                    "business/move_manager.py",
                    "api/v1/routes/movement_repricing.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::listMovementRepricingEvidence",
                    "src/shared/api/contracts/backendApiClient.ts::repriceStealthOrderByStealthOrderId",
                    "src/features/admin-shell/AdminShell.tsx",
                ],
                documentation_refs=[
                    "README.movement-repricing.md",
                    "docs/ADMIN_MODULE_CAPABILITY_MATRIX.md",
                    "docs/examples/admin-api.md",
                ],
                spot_rule_boundary=(
                    "Movement/repricing must preserve exchange reality first. "
                    "Spot wallet replacement deltas are backend guard evidence "
                    "only and must not become browser authority."
                ),
            ),
            module_item(
                module_id="guard_risk_policy",
                module="Guard / Risk Policy",
                primary_owner="order_lifecycle",
                support_status=AdminApiModuleSupportStatus.PLATFORM_READY,
                unsupported_actions=[
                    "browser-side guard calculation",
                    "browser-side profitability authority",
                    "browser-side wallet or margin authority",
                ],
                command_gaps=[
                    command_gap(
                        action="browser-side guard calculation",
                        status=AdminApiModuleSupportStatus.UNSUPPORTED,
                        reason="Guard calculations are backend authority and policy evidence.",
                        required_backend_contract=(
                            "Backend guard/risk read or command contract that returns "
                            "policy decisions and audit evidence."
                        ),
                        frontend_boundary=(
                            "Do not turn guard/risk UI evidence into a browser approval "
                            "or preflight evaluator."
                        ),
                    ),
                    command_gap(
                        action="browser-side wallet or margin authority",
                        status=AdminApiModuleSupportStatus.UNSUPPORTED,
                        reason=(
                            "Wallet, inventory, margin, and position authority must be "
                            "checked at backend command/reveal/execution boundaries."
                        ),
                        required_backend_contract=(
                            "Backend authority contract over wallet, inventory, margin, "
                            "position, cap, and product capability evidence."
                        ),
                        frontend_boundary=(
                            "Do not make browser balances, margins, or cached read models "
                            "decide command eligibility."
                        ),
                    ),
                ],
                identity_keys=["policy_id", "product_id", "correlation_id"],
                constraints=[
                    "The browser may display guard evidence but must not decide authority.",
                ],
                verification=[
                    "guard/risk regression",
                    "Admin API contract regression",
                    "contextless guard/risk review",
                ],
                backend_contract_refs=[
                    "core/action_condition_guard.py",
                    "core/product_capability.py",
                    "api/v1/routes/admin.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::getGuardRiskPolicy",
                    "src/shared/api/contracts/backendRuntime.ts::loadGuardRiskPolicyReadSnapshot",
                    "src/features/admin-shell/AdminShell.tsx",
                ],
                documentation_refs=[
                    "README.guard-risk-policy.md",
                    "docs/ADMIN_MODULE_CAPABILITY_MATRIX.md",
                    "docs/examples/admin-api.md",
                ],
                spot_rule_boundary=(
                    "Guard/risk may report spot-specific policy evidence for "
                    "spot products, but the browser must not generalize those "
                    "rules to futures, stealth, movement, or audit workflows."
                ),
            ),
            module_item(
                module_id="audit_workbench",
                module="Audit Workbench",
                primary_owner="admin_api_contract",
                support_status=AdminApiModuleSupportStatus.PLATFORM_READY,
                unsupported_actions=[
                    "audit mutation",
                    "command replay",
                    "exchange-id cancellation or tracking authority",
                ],
                command_gaps=[
                    command_gap(
                        action="audit mutation",
                        status=AdminApiModuleSupportStatus.UNSUPPORTED,
                        reason=(
                            "Audit workbench is a read-only evidence surface and must not "
                            "rewrite audit history."
                        ),
                        required_backend_contract=(
                            "No frontend audit mutation contract is planned; backend audit "
                            "stores are command-side evidence."
                        ),
                        frontend_boundary=(
                            "Do not add audit mutation controls, command replay controls, "
                            "or feature-local audit fetch paths."
                        ),
                    ),
                    command_gap(
                        action="command replay",
                        status=AdminApiModuleSupportStatus.UNSUPPORTED,
                        reason=(
                            "Replaying a command from audit evidence would create a second "
                            "command path outside draft, idempotency, approval, and audit gates."
                        ),
                        required_backend_contract=(
                            "Any replay-like behavior would need a first-class backend "
                            "command contract with fresh operator intent, idempotency, "
                            "approval, cap, guard, and audit evidence."
                        ),
                        frontend_boundary=(
                            "Audit links may navigate to evidence only; they must not "
                            "submit or re-submit commands."
                        ),
                    ),
                ],
                identity_keys=[
                    "client_order_id",
                    "stealth_order_id",
                    "position_key",
                    "audit_id",
                    "correlation_id",
                ],
                constraints=[
                    "Exchange ids are evidence only and never application identity.",
                ],
                verification=[
                    "Admin API contract regression",
                    "frontend audit workbench tests",
                    "contextless audit review",
                ],
                backend_contract_refs=[
                    "application/admin_api/read_service.py::build_audit_workbench",
                    "application/admin_api/audit.py",
                    "api/v1/routes/admin.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::getAdminAuditWorkbench",
                    "src/shared/api/contracts/backendRuntime.ts::loadAuditWorkbenchReadSnapshot",
                    "src/features/admin-shell/AdminShell.tsx",
                ],
                documentation_refs=[
                    "README.audit-workbench.md",
                    "docs/ADMIN_MODULE_CAPABILITY_MATRIX.md",
                    "docs/examples/admin-api.md",
                ],
                spot_rule_boundary=(
                    "Audit can display spot evidence but cannot mutate, replay, "
                    "or promote spot identities into non-spot command authority."
                ),
            ),
            module_item(
                module_id="legacy_dashboard_websocket",
                module="Legacy Dashboard WebSocket",
                primary_owner="dashboard_contract",
                support_status=AdminApiModuleSupportStatus.UNSUPPORTED,
                unsupported_actions=[
                    "enterprise frontend direct WebSocket command execution",
                    "new admin module implementation through dashboard.py",
                ],
                command_gaps=[
                    command_gap(
                        action="enterprise frontend direct WebSocket command execution",
                        status=AdminApiModuleSupportStatus.UNSUPPORTED,
                        reason=(
                            "The legacy dashboard WebSocket is compatibility-only and is "
                            "not the enterprise admin command plane."
                        ),
                        required_backend_contract=(
                            "Backend-owned Admin API route through auth, RBAC, idempotency, "
                            "approval, caps, audit, and the shared command service."
                        ),
                        frontend_boundary=(
                            "Do not call dashboard.py or legacy dashboard WebSocket handlers "
                            "from enterprise frontend product UI."
                        ),
                    ),
                    command_gap(
                        action="new admin module implementation through dashboard.py",
                        status=AdminApiModuleSupportStatus.UNSUPPORTED,
                        reason=(
                            "New admin modules must start from backend-owned OpenAPI "
                            "contracts, not proof-of-concept dashboard handlers."
                        ),
                        required_backend_contract=(
                            "Backend-owned Admin API route, OpenAPI schema, route inventory, "
                            "tests, docs, and frontend generated-client sync."
                        ),
                        frontend_boundary=(
                            "Do not use dashboard.py as the implementation path for new "
                            "enterprise admin modules."
                        ),
                    ),
                ],
                identity_keys=["client_order_id"],
                constraints=[
                    "Legacy dashboard surfaces are compatibility-only and not the enterprise admin path.",
                ],
                verification=[
                    "command fetch guard",
                    "BFF command boundary tests",
                    "contextless enterprise boundary review",
                ],
                backend_contract_refs=[
                    "dashboard_server.py",
                    "docs/LIVE_ORDER_SURFACES.md",
                    "application/admin_api/command_service.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/adminBffProxy.ts",
                    "src/shared/api/contracts/mutationContracts.ts",
                    "src/features/command-workflows",
                ],
                documentation_refs=[
                    "docs/ADMIN_PLATFORM_ARCHITECTURE.md",
                    "docs/ADMIN_MODULE_CAPABILITY_MATRIX.md",
                    "docs/examples/admin-api.md",
                ],
                spot_rule_boundary=(
                    "Legacy dashboard behavior is compatibility-only. Spot "
                    "rules exposed there are not reusable enterprise frontend "
                    "authority and must be reintroduced only through Admin API contracts."
                ),
            ),
        ]
        functionality_inventory = [
            functionality_item(
                workflow_id="admin.platform_evidence",
                module_id="admin_system_health",
                module="Admin / System Health",
                workflow_type=AdminApiFunctionalityWorkflowType.PLATFORM_EVIDENCE,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_EXPOSED,
                support_status=AdminApiModuleSupportStatus.PLATFORM_READY,
                summary=(
                    "Backend-owned bootstrap, health, auth, capability, live-readiness, "
                    "release, fixture, and enterprise-readiness evidence."
                ),
                backend_supported=True,
                admin_api_exposed=True,
                frontend_exposed=True,
                read_routes=[
                    "GET /api/v1/admin/bootstrap",
                    "GET /api/v1/admin/health",
                    "GET /api/v1/admin/session",
                    "GET /api/v1/admin/oidc-readiness",
                    "GET /api/v1/admin/capabilities",
                    "GET /api/v1/admin/csrf",
                    "GET /api/v1/admin/live-enablement",
                    "GET /api/v1/admin/enterprise-readiness",
                    "GET /api/v1/admin/release-gate",
                    "GET /api/v1/admin/recovery-gate",
                    "GET /api/v1/admin/fill-ledger-health",
                    "GET /api/v1/admin/frontend-fixtures",
                    "GET /api/v1/admin/approvals",
                    "GET /api/v1/admin/approvals/requests/{approval_request_id}",
                    "GET /api/v1/admin/admission-audits",
                    "GET /api/v1/admin/admission-audits/{admission_audit_id}",
                    "GET /api/v1/admin/cap-guard/decisions",
                    "GET /api/v1/admin/cap-guard/decisions/{decision_id}",
                    "GET /api/v1/admin/reconciliation/plans",
                    "GET /api/v1/admin/reconciliation/plans/{plan_id}",
                ],
                identity_keys=["request_id", "correlation_id", "actor_id"],
                backend_contract_refs=[
                    "application/admin_api/read_service.py",
                    "api/v1/routes/admin.py",
                    "application/admin_api/route_inventory.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts",
                    "src/features/admin-shell/AdminShell.tsx",
                ],
                documentation_refs=[
                    "README.admin-api.md",
                    "docs/ADMIN_PLATFORM_ARCHITECTURE.md",
                ],
                frontend_boundary=(
                    "Display platform evidence only; do not run backend tests, hold "
                    "secrets, or approve live commands from the browser."
                ),
                spot_rule_boundary="Platform evidence is not a spot-rule source.",
            ),
            functionality_item(
                workflow_id="admin.approval_lifecycle",
                module_id="admin_system_health",
                module="Admin / System Health",
                workflow_type=AdminApiFunctionalityWorkflowType.COMMAND_DRAFT,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_EXPOSED,
                support_status=AdminApiModuleSupportStatus.PLATFORM_READY,
                summary=(
                    "Backend-owned approval request, decision, revoke, expiry, "
                    "and snapshot-linking lifecycle for future live admission."
                ),
                backend_supported=True,
                admin_api_exposed=True,
                frontend_exposed=True,
                command_capable=True,
                live_designated=False,
                read_routes=[
                    "GET /api/v1/admin/approvals",
                    "GET /api/v1/admin/approvals/requests/{approval_request_id}",
                ],
                command_routes=[
                    "POST /api/v1/admin/approvals/requests",
                    "POST /api/v1/admin/approvals/requests/{approval_request_id}/decisions",
                    "POST /api/v1/admin/approvals/{approval_id}/revoke",
                ],
                identity_keys=[
                    "approval_request_id",
                    "approval_id",
                    "client_order_id",
                    "stealth_order_id",
                    "campaign_id",
                    "position_key",
                ],
                backend_contract_refs=[
                    "application/admin_api/approval.py",
                    "application/admin_api/approval_service.py",
                    "api/v1/routes/approvals.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts",
                    "src/features/admin-shell/AdminShell.tsx",
                ],
                documentation_refs=[
                    "README.admin-api.md",
                    "docs/examples/admin-api.md",
                ],
                required_next_contract=(
                    "Cap/guard decision execution records must link to approved "
                    "snapshots before live command admission can proceed."
                ),
                blockers=[
                    "live_execution_disabled",
                    "cap_guard_missing",
                    "reconciliation_plan_missing",
                ],
                frontend_boundary=(
                    "The browser may request, display, and forward approval "
                    "decisions through backend contracts only; it must not become "
                    "approval authority or execute commands."
                ),
                spot_rule_boundary=(
                    "Approval lifecycle is a platform primitive. Spot wallet, "
                    "USDC, cost-basis, and no-shorting rules are not generic "
                    "approval rules."
                ),
            ),
            functionality_item(
                workflow_id="admin.admission_audits",
                module_id="admin_system_health",
                module="Admin / System Health",
                workflow_type=AdminApiFunctionalityWorkflowType.COMMAND_DRAFT,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_EXPOSED,
                support_status=AdminApiModuleSupportStatus.PLATFORM_READY,
                summary=(
                    "Backend-owned admission audit records that bind route, "
                    "identity, payload, approval snapshot, cap/guard reference, "
                    "reconciliation reference, and disabled live intent evidence "
                    "before command admission can advance."
                ),
                backend_supported=True,
                admin_api_exposed=True,
                frontend_exposed=True,
                command_capable=True,
                live_designated=False,
                read_routes=[
                    "GET /api/v1/admin/admission-audits",
                    "GET /api/v1/admin/admission-audits/{admission_audit_id}",
                ],
                command_routes=["POST /api/v1/admin/admission-audits"],
                identity_keys=[
                    "admission_audit_id",
                    "approval_snapshot_id",
                    "approval_cap_guard_decision_ref",
                    "approval_reconciliation_plan_ref",
                    "client_order_id",
                    "stealth_order_id",
                    "campaign_id",
                    "position_key",
                ],
                backend_contract_refs=[
                    "application/admin_api/audit.py",
                    "application/admin_api/admission_audit_service.py",
                    "api/v1/routes/admission_audit.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts",
                    "src/features/admin-shell/AdminShell.tsx",
                ],
                documentation_refs=[
                    "README.admin-api.md",
                    "docs/examples/admin-api.md",
                ],
                required_next_contract=(
                    "Reconciliation plan and proof runner must complete before "
                    "live command admission can proceed."
                ),
                blockers=[
                    "live_execution_disabled",
                    "cap_guard_missing",
                    "reconciliation_plan_missing",
                ],
                frontend_boundary=(
                    "The browser may display and forward admission audit records "
                    "only; it must not write browser audit history, claim "
                    "execution, or satisfy live admission without backend proof."
                ),
                spot_rule_boundary=(
                    "Admission audit records are platform evidence. Spot wallet, "
                    "USDC, cost-basis, and no-shorting rules remain route-specific "
                    "guard inputs, not generic audit rules."
                ),
            ),
            functionality_item(
                workflow_id="admin.cap_guard_decisions",
                module_id="admin_system_health",
                module="Admin / System Health",
                workflow_type=AdminApiFunctionalityWorkflowType.COMMAND_DRAFT,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_EXPOSED,
                support_status=AdminApiModuleSupportStatus.PLATFORM_READY,
                summary=(
                    "Backend-owned cap/guard decision records that bind route, "
                    "payload, actor, approval snapshot, admission audit, and "
                    "policy references for future live admission."
                ),
                backend_supported=True,
                admin_api_exposed=True,
                frontend_exposed=True,
                command_capable=True,
                live_designated=False,
                read_routes=[
                    "GET /api/v1/admin/cap-guard/decisions",
                    "GET /api/v1/admin/cap-guard/decisions/{decision_id}",
                ],
                command_routes=["POST /api/v1/admin/cap-guard/decisions"],
                identity_keys=[
                    "decision_id",
                    "approval_cap_guard_decision_ref",
                    "approval_snapshot_id",
                    "admission_audit_id",
                    "client_order_id",
                    "stealth_order_id",
                    "campaign_id",
                    "position_key",
                ],
                backend_contract_refs=[
                    "application/admin_api/cap_guard.py",
                    "application/admin_api/cap_guard_service.py",
                    "api/v1/routes/cap_guard.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts",
                    "src/features/admin-shell/AdminShell.tsx",
                ],
                documentation_refs=[
                    "README.admin-api.md",
                    "docs/examples/admin-api.md",
                ],
                required_next_contract=(
                    "Reconciliation plan and proof runner must complete before "
                    "live command admission can proceed."
                ),
                blockers=[
                    "live_execution_disabled",
                    "reconciliation_plan_missing",
                ],
                frontend_boundary=(
                    "The browser may display and forward cap/guard decision "
                    "records only; it must not evaluate wallet, margin, "
                    "profitability, inventory, or account-limit rules."
                ),
                spot_rule_boundary=(
                    "Cap/guard decision records are platform evidence. Spot "
                    "wallet, USDC, cost-basis, and no-shorting rules stay in "
                    "spot route-specific guard inputs."
                ),
            ),
            functionality_item(
                workflow_id="admin.reconciliation_plans",
                module_id="admin_system_health",
                module="Admin / System Health",
                workflow_type=AdminApiFunctionalityWorkflowType.COMMAND_DRAFT,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_EXPOSED,
                support_status=AdminApiModuleSupportStatus.PLATFORM_READY,
                summary=(
                    "Backend-owned reconciliation plan proof records that bind "
                    "route, payload, approval snapshot, admission audit, "
                    "cap/guard decision, reconciliation policy, product scope, "
                    "and no-live execution evidence for future command admission."
                ),
                backend_supported=True,
                admin_api_exposed=True,
                frontend_exposed=True,
                command_capable=True,
                live_designated=False,
                read_routes=[
                    "GET /api/v1/admin/reconciliation/plans",
                    "GET /api/v1/admin/reconciliation/plans/{plan_id}",
                ],
                command_routes=["POST /api/v1/admin/reconciliation/plans"],
                identity_keys=[
                    "plan_id",
                    "approval_reconciliation_plan_ref",
                    "approval_snapshot_id",
                    "admission_audit_id",
                    "cap_guard_decision_id",
                    "client_order_id",
                    "stealth_order_id",
                    "campaign_id",
                    "position_key",
                ],
                backend_contract_refs=[
                    "application/admin_api/reconciliation.py",
                    "application/admin_api/reconciliation_service.py",
                    "api/v1/routes/reconciliation.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts",
                    "src/features/admin-shell/AdminShell.tsx",
                ],
                documentation_refs=[
                    "README.admin-api.md",
                    "docs/examples/admin-api.md",
                ],
                required_next_contract=(
                    "Controlled live adapter pilot remains blocked until the "
                    "live service and route-specific adapter are explicitly "
                    "enabled under cap, approval, audit, and reconciliation proof."
                ),
                blockers=[
                    "live_execution_disabled",
                    "browser_authority_rejected",
                ],
                frontend_boundary=(
                    "The browser may display and forward reconciliation plan "
                    "records only; it must not execute reconciliation, mutate "
                    "order/exchange state, or mark submissions reconciled."
                ),
                spot_rule_boundary=(
                    "Reconciliation plan records are platform evidence. Spot "
                    "retained-inventory, fill-ledger, and USDC-specific rules "
                    "remain route-specific backend proof, not generic frontend "
                    "reconciliation authority."
                ),
            ),
            functionality_item(
                workflow_id="admin.live_service_decisions",
                module_id="admin_system_health",
                module="Admin / System Health",
                workflow_type=AdminApiFunctionalityWorkflowType.COMMAND_DRAFT,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_EXPOSED,
                support_status=AdminApiModuleSupportStatus.PLATFORM_READY,
                summary=(
                    "Backend-owned live-service decision evidence records that "
                    "document disabled service posture without enabling execution."
                ),
                backend_supported=True,
                admin_api_exposed=True,
                frontend_exposed=True,
                command_capable=True,
                live_designated=False,
                read_routes=[
                    "GET /api/v1/admin/live-execution/service-decisions",
                    "GET /api/v1/admin/live-execution/service-decisions/{decision_id}",
                ],
                command_routes=[
                    "POST /api/v1/admin/live-execution/service-decisions",
                ],
                identity_keys=[
                    "decision_id",
                    "deployment_ref",
                    "runtime_configuration_ref",
                ],
                backend_contract_refs=[
                    "application/admin_api/live_execution.py",
                    "application/admin_api/live_service_decision_service.py",
                    "api/v1/routes/live_execution.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts",
                    "src/shared/api/contracts/mutationContracts.ts",
                    "src/shared/api/contracts/adminBffProxy.ts",
                ],
                documentation_refs=[
                    "README.admin-api.md",
                    "docs/examples/admin-api.md",
                ],
                required_next_contract=(
                    "A future approved live enablement phase must provide "
                    "configured service, adapter, verification, and execution "
                    "authority evidence before live commands can run."
                ),
                blockers=[
                    "live_execution_disabled",
                    "live_service_enablement_missing",
                    "live_adapter_construction_missing",
                ],
                frontend_boundary=(
                    "The browser may display and forward disabled live-service "
                    "decision evidence only; it must not enable service, approve "
                    "Coinbase execution, or clear live-readiness blockers."
                ),
                spot_rule_boundary=(
                    "Live-service decision evidence is platform evidence. Spot "
                    "wallet, USDC, cost-basis, and no-shorting rules remain "
                    "route-specific guard inputs."
                ),
            ),
            functionality_item(
                workflow_id="spot.read_models",
                module_id="spot_operations",
                module="Spot Operations",
                workflow_type=AdminApiFunctionalityWorkflowType.READ_MODEL,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_EXPOSED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Spot readiness, order, sweep, P/L, cost-basis, campaign, and "
                    "direct-order audit reads are exposed through backend contracts."
                ),
                backend_supported=True,
                admin_api_exposed=True,
                frontend_exposed=True,
                read_routes=[
                    "GET /api/v1/orders",
                    "GET /api/v1/orders/{client_order_id}",
                    "GET /api/v1/spot/readiness",
                    "GET /api/v1/spot/sweep/status",
                    "GET /api/v1/spot/sweep/pnl",
                    "GET /api/v1/spot/cost-basis/status",
                    "GET /api/v1/spot/campaign/status",
                    "GET /api/v1/spot/direct-orders/{client_order_id}/audit",
                    "GET /api/v1/spot/recovery/preview",
                ],
                identity_keys=["client_order_id", "product_id", "campaign_id"],
                backend_contract_refs=[
                    "application/admin_api/read_service.py::build_spot_readiness",
                    "business/spot_portfolio_sweep.py",
                    "business/spot_inventory_authority.py",
                ],
                frontend_contract_refs=[
                    "src/features/spot-ops/spotBackendAdapters.ts",
                    "src/features/admin-shell/AdminShell.tsx",
                ],
                documentation_refs=[
                    "README.spot-trading.md",
                    "README.spot-portfolio-sweep.md",
                    "README.spot-campaign.md",
                ],
                frontend_boundary=(
                    "Display backend spot evidence; do not calculate wallet, cost-basis, "
                    "profitability, or sell authority in the browser."
                ),
                spot_rule_boundary=(
                    "Spot inventory, USDC scope, no shorting, and cost basis apply only "
                    "inside spot workflows."
                ),
            ),
            functionality_item(
                workflow_id="spot.order_command_drafts",
                module_id="spot_operations",
                module="Spot Operations",
                workflow_type=AdminApiFunctionalityWorkflowType.COMMAND_DRAFT,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Manual order, cancel by client_order_id, campaign execution, "
                    "and sweep automation commands are exposed as authenticated "
                    "live-disabled drafts."
                ),
                backend_supported=True,
                admin_api_exposed=True,
                frontend_exposed=True,
                command_capable=True,
                live_designated=True,
                command_routes=[
                    "POST /api/v1/orders",
                    "POST /api/v1/orders/{client_order_id}/cancel",
                    "POST /api/v1/spot/campaign/executions",
                    "POST /api/v1/spot/sweep/automation-runs",
                ],
                identity_keys=["client_order_id", "campaign_id", "sweep_config_id"],
                backend_contract_refs=[
                    "application/admin_api/command_service.py",
                    "api/v1/routes/orders.py",
                ],
                frontend_contract_refs=[
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                    "src/shared/api/contracts/backendApiClient.ts",
                ],
                documentation_refs=[
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/SPOT_ORDER_FRONTEND_FLOW.md",
                ],
                required_next_contract=(
                    "Approval, cap/guard, audit, reconciliation, and live adapter "
                    "admission must all pass before execution."
                ),
                blockers=[
                    "live_execution_disabled",
                    "approval_snapshot_missing",
                    "cap_guard_missing",
                    "reconciliation_plan_missing",
                ],
                frontend_boundary=(
                    "Keep buttons dry-submit/live-disabled unless backend capability "
                    "and live-enablement evidence explicitly admit execution."
                ),
                spot_rule_boundary="Spot commands must preserve no-shorting and inventory authority.",
            ),
            functionality_item(
                workflow_id="spot.sweep_automation_and_live_executor",
                module_id="spot_operations",
                module="Spot Operations",
                workflow_type=AdminApiFunctionalityWorkflowType.AUTOMATION,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Backend sweep planning, scheduling, safety policy, live executor, "
                    "run records, and reconciliation helpers exist; enterprise admin "
                    "currently exposes status, live-disabled campaign execution, "
                    "and a live-disabled sweep automation run contract."
                ),
                backend_supported=True,
                admin_api_exposed=True,
                frontend_exposed=True,
                command_capable=True,
                live_designated=True,
                command_routes=[
                    "POST /api/v1/spot/campaign/executions",
                    "POST /api/v1/spot/sweep/automation-runs",
                ],
                automation_routes=[
                    "tools/run_spot_portfolio_sweep_live.py",
                    "tools/run_spot_portfolio_sweep_dry_run.py",
                    "tools/run_spot_campaign.py",
                ],
                identity_keys=[
                    "campaign_id",
                    "config_id",
                    "sweep_config_id",
                    "client_order_id",
                ],
                backend_contract_refs=[
                    "business/spot_portfolio_sweep.py",
                    "business/spot_campaign.py",
                    "tools/run_spot_portfolio_sweep_live.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::executeSpotCampaign",
                    "src/shared/api/contracts/backendApiClient.ts::runSpotSweepAutomation",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                documentation_refs=[
                    "README.spot-campaign.md",
                    "README.spot-portfolio-sweep.md",
                    "docs/SPOT_READINESS_ROADMAP.md",
                ],
                required_next_contract=(
                    "Enterprise admin scheduling, approval, execution, recovery, and "
                    "reconciliation contracts for durable sweep runs."
                ),
                blockers=[
                    "live_execution_disabled",
                    "backend scheduling UI contract missing",
                    "approval and reconciliation contracts incomplete",
                ],
                frontend_boundary=(
                    "Show automation status and draft execution only; do not launch "
                    "live sweep tools or create a browser scheduler."
                ),
                spot_rule_boundary=(
                    "Sweep automation is spot-only and must keep USDC, inventory, "
                    "average-cost, and known-profitable sell authority inside backend gates."
                ),
            ),
            functionality_item(
                workflow_id="stealth.lifecycle_reads",
                module_id="stealth_orders",
                module="Stealth Orders",
                workflow_type=AdminApiFunctionalityWorkflowType.READ_MODEL,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_EXPOSED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth list/detail reads expose lifecycle, placement, policy, and "
                    "exchange-evidence state keyed by stealth_order_id."
                ),
                backend_supported=True,
                admin_api_exposed=True,
                frontend_exposed=True,
                read_routes=[
                    "GET /api/v1/stealth/orders",
                    "GET /api/v1/stealth/orders/{stealth_order_id}",
                ],
                identity_keys=["stealth_order_id", "client_order_id"],
                backend_contract_refs=[
                    "core/stealth_order_manager.py",
                    "application/admin_api/read_service.py::build_stealth_order_list",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::listStealthOrders",
                    "src/features/admin-shell/AdminShell.tsx",
                ],
                documentation_refs=[
                    "docs/agents/AGENT_STEALTH_LIFECYCLE.md",
                    "docs/ADMIN_MODULE_CAPABILITY_MATRIX.md",
                ],
                frontend_boundary=(
                    "Display stealth state only; active placement ids and exchange ids "
                    "are not browser mutation authority."
                ),
                spot_rule_boundary=(
                    "Spot guard evidence may apply to spot stealth orders only through "
                    "backend checks."
                ),
            ),
            functionality_item(
                workflow_id="stealth.create_command_draft",
                module_id="stealth_orders",
                module="Stealth Orders",
                workflow_type=AdminApiFunctionalityWorkflowType.COMMAND_DRAFT,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth create is exposed as a live-disabled local-state draft "
                    "keyed by stealth_order_id; it does not invoke the lifecycle "
                    "manager until planning and reconciliation gates are complete."
                ),
                backend_supported=True,
                admin_api_exposed=True,
                frontend_exposed=True,
                command_capable=True,
                live_designated=False,
                command_routes=["POST /api/v1/stealth/orders"],
                identity_keys=["stealth_order_id"],
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::create_stealth_order",
                    "application/admin_api/command_service.py::create_stealth_order",
                    "application/admin_api/stealth_lifecycle_execution.py::build_stealth_create_lifecycle_write_execution_contract",
                    "core/stealth_order_manager.py::create_stealth_order",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::createStealthOrder",
                ],
                documentation_refs=["docs/COMMAND_WORKFLOWS.md"],
                required_next_contract=(
                    "Backend lifecycle-write execution contract with exact "
                    "command context, planning guards, approval, cap/guard, "
                    "audit, reconciliation, live adapter, and post-write "
                    "recovery evidence before StealthOrderManager can be "
                    "invoked."
                ),
                blockers=[
                    "stealth_create_lifecycle_write_guard_proof_missing",
                    "stealth_create_lifecycle_write_execution_contract_missing",
                    "reconciliation_plan_missing",
                    "stealth_manager_invocation_disabled",
                ],
                frontend_boundary=(
                    "Do not create local stealth state from browser code; the "
                    "frontend may only display and dry-submit backend contract "
                    "evidence through the canonical live-disabled wrapper."
                ),
                spot_rule_boundary=(
                    "Spot wallet and no-shorting rules are backend guard inputs "
                    "only and cannot become generic stealth browser authority."
                ),
            ),
            functionality_item(
                workflow_id="stealth.cancel_command_draft",
                module_id="stealth_orders",
                module="Stealth Orders",
                workflow_type=AdminApiFunctionalityWorkflowType.COMMAND_DRAFT,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth cancel is exposed as a live-disabled draft keyed by "
                    "stealth_order_id and must preserve exchange-reality state."
                ),
                backend_supported=True,
                admin_api_exposed=True,
                frontend_exposed=True,
                command_capable=True,
                live_designated=True,
                command_routes=["POST /api/v1/stealth/orders/{stealth_order_id}/cancel"],
                identity_keys=["stealth_order_id"],
                backend_contract_refs=[
                    "application/admin_api/command_service.py::cancel_stealth_order_by_stealth_order_id",
                    "api/v1/routes/stealth.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::cancelStealthOrderByStealthOrderId",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                documentation_refs=["docs/COMMAND_WORKFLOWS.md"],
                required_next_contract=(
                    "Live exchange cancel, audit, cap, approval, and reconciliation "
                    "contract for active revealed placements."
                ),
                blockers=["live_execution_disabled", "exchange reality proof missing"],
                frontend_boundary=(
                    "Do not cancel by exchange order id or mutate active placement state "
                    "from the browser."
                ),
                spot_rule_boundary="Stealth identity rules are not spot inventory rules.",
            ),
            functionality_item(
                workflow_id="stealth.reveal_command_draft",
                module_id="stealth_orders",
                module="Stealth Orders",
                workflow_type=AdminApiFunctionalityWorkflowType.COMMAND_DRAFT,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth reveal is exposed as a live-disabled exchange-placement "
                    "draft keyed by stealth_order_id; it does not invoke the reveal "
                    "manager path or submit Coinbase orders until trigger, approval, "
                    "guard, and reconciliation evidence are complete."
                ),
                backend_supported=True,
                admin_api_exposed=True,
                frontend_exposed=True,
                command_capable=True,
                live_designated=True,
                live_enabled=False,
                command_routes=["POST /api/v1/stealth/orders/{stealth_order_id}/reveal"],
                identity_keys=["stealth_order_id"],
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::reveal_stealth_order_by_stealth_order_id",
                    "application/admin_api/command_service.py::reveal_stealth_order_by_stealth_order_id",
                    "core/stealth_order_manager.py::reveal_order_slice",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::revealStealthOrderByStealthOrderId",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                documentation_refs=["docs/COMMAND_WORKFLOWS.md"],
                required_next_contract=(
                    "Live reveal adapter with trigger evidence, approval, cap/guard, "
                    "active placement audit, Coinbase placement handling, and "
                    "post-live reconciliation before reveal_order_slice can run."
                ),
                blockers=[
                    "live_execution_disabled",
                    "trigger_evidence_missing",
                    "stealth_reveal_exchange_submission_adapter_missing",
                    "active_placement_audit_missing",
                    "reconciliation_proof_missing",
                ],
                frontend_boundary=(
                    "Do not invoke reveal_order_slice, submit Coinbase orders, or "
                    "mutate lifecycle state from browser code."
                ),
                spot_rule_boundary=(
                    "Spot wallet and no-shorting rules remain backend guard evidence "
                    "when the stealth product is spot; they are not browser authority."
                ),
            ),
            functionality_item(
                workflow_id="stealth.move_command_draft",
                module_id="stealth_orders",
                module="Stealth Orders",
                workflow_type=AdminApiFunctionalityWorkflowType.COMMAND_DRAFT,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth move is exposed as a live-disabled cancel/replace-shaped "
                    "draft keyed by stealth_order_id; it does not build a move plan, "
                    "execute cancel/replace, or mutate lifecycle state."
                ),
                backend_supported=True,
                admin_api_exposed=True,
                frontend_exposed=True,
                command_capable=True,
                live_designated=True,
                live_enabled=False,
                command_routes=["POST /api/v1/stealth/orders/{stealth_order_id}/move"],
                identity_keys=["stealth_order_id"],
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::move_stealth_order_by_stealth_order_id",
                    "application/admin_api/command_service.py::move_stealth_order_by_stealth_order_id",
                    "core/stealth_order_manager.py::build_stealth_move_plan",
                    "core/stealth_order_manager.py::execute_stealth_move",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::moveStealthOrderByStealthOrderId",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                documentation_refs=["docs/COMMAND_WORKFLOWS.md"],
                required_next_contract=(
                    "Live move adapter with mutation-claim ownership, active "
                    "placement cancel/replace, approval, cap/guard, audit, and "
                    "post-live reconciliation before execute_stealth_move can run."
                ),
                blockers=[
                    "live_execution_disabled",
                    "mutation_claim_proof_missing",
                    "stealth_move_cancel_replace_adapter_missing",
                    "active_placement_audit_missing",
                    "reconciliation_proof_missing",
                ],
                frontend_boundary=(
                    "Do not build move plans, execute cancel/replace, resolve active "
                    "placement ids, or mutate lifecycle state from browser code."
                ),
                spot_rule_boundary=(
                    "Spot wallet and no-shorting rules remain backend guard evidence "
                    "when the stealth product is spot; they are not browser authority."
                ),
            ),
            functionality_item(
                workflow_id="stealth.recovery_command_draft",
                module_id="stealth_orders",
                module="Stealth Orders",
                workflow_type=AdminApiFunctionalityWorkflowType.COMMAND_DRAFT,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth recovery is exposed as a live-disabled backend "
                    "contract keyed by stealth_order_id; it does not execute "
                    "repair, rollback, Coinbase reads, lifecycle mutation, or "
                    "reconciliation."
                ),
                backend_supported=True,
                admin_api_exposed=True,
                frontend_exposed=True,
                command_capable=True,
                live_designated=False,
                live_enabled=False,
                command_routes=[
                    "POST /api/v1/stealth/orders/{stealth_order_id}/recovery",
                ],
                identity_keys=["stealth_order_id"],
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::recover_stealth_order_by_stealth_order_id",
                    "application/admin_api/command_service.py::recover_stealth_order_by_stealth_order_id",
                    "core/stealth_order_manager.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::recoverStealthOrderByStealthOrderId",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                documentation_refs=["docs/COMMAND_WORKFLOWS.md"],
                required_next_contract=(
                    "Backend stealth recovery contract with active-placement "
                    "exchange truth, repair/rollback proof, approval, cap/guard, "
                    "audit, and reconciliation before any state repair can run."
                ),
                blockers=[
                    "live_execution_disabled",
                    "stealth_recovery_repair_result_contract_missing",
                    "stealth_recovery_rollback_contract_missing",
                    "active_placement_exchange_truth_missing",
                    "reconciliation_proof_missing",
                ],
                frontend_boundary=(
                    "Do not repair stealth state, rollback lifecycle records, "
                    "read Coinbase, or resolve active placements from the browser."
                ),
                spot_rule_boundary=(
                    "Spot recovery contracts are not reusable authority for "
                    "stealth recovery; spot guard evidence may apply only through "
                    "backend gates for spot products."
                ),
            ),
            functionality_item(
                workflow_id="stealth.reconciliation_command_draft",
                module_id="stealth_orders",
                module="Stealth Orders",
                workflow_type=AdminApiFunctionalityWorkflowType.COMMAND_DRAFT,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth reconciliation is exposed as a live-disabled "
                    "backend contract keyed by stealth_order_id; it does not "
                    "execute reconciliation, write proof records, mutate local "
                    "or exchange state, read Coinbase, or invoke the manager."
                ),
                backend_supported=True,
                admin_api_exposed=True,
                frontend_exposed=True,
                command_capable=True,
                live_designated=False,
                live_enabled=False,
                command_routes=[
                    "POST /api/v1/stealth/orders/{stealth_order_id}/reconciliation",
                ],
                identity_keys=["stealth_order_id"],
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::reconcile_stealth_order_by_stealth_order_id",
                    "application/admin_api/command_service.py::reconcile_stealth_order_by_stealth_order_id",
                    "application/admin_api/reconciliation.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::reconcileStealthOrderByStealthOrderId",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                documentation_refs=[
                    "docs/COMMAND_WORKFLOWS.md",
                    "README.reconciliation-plans.md",
                ],
                required_next_contract=(
                    "Backend stealth reconciliation execution contract with "
                    "plan/proof resolution, active-placement exchange truth, "
                    "approval, cap/guard, audit, lifecycle repair policy, and "
                    "post-execution proof before any reconciliation can run."
                ),
                blockers=[
                    "live_execution_disabled",
                    "stealth_reconciliation_plan_contract_missing",
                    "stealth_exchange_evidence_snapshot_contract_missing",
                    "stealth_reconciliation_executor_missing",
                    "active_placement_exchange_truth_missing",
                ],
                frontend_boundary=(
                    "Do not execute reconciliation, create proof authority, "
                    "read Coinbase, or mutate local/exchange state from browser code."
                ),
                spot_rule_boundary=(
                    "Spot reconciliation records are not reusable authority for "
                    "stealth reconciliation; stealth exchange-reality invariants "
                    "remain module-specific."
                ),
            ),
            functionality_item(
                workflow_id="movement.repricing_reads",
                module_id="movement_repricing",
                module="Order Movement / Repricing",
                workflow_type=AdminApiFunctionalityWorkflowType.READ_MODEL,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_EXPOSED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Movement/repricing evidence reads expose move records, stealth "
                    "details, replacement slots, mutation claims, and cooldown evidence."
                ),
                backend_supported=True,
                admin_api_exposed=True,
                frontend_exposed=True,
                read_routes=[
                    "GET /api/v1/movement-repricing/evidence",
                    "GET /api/v1/movement-repricing/orders/{client_order_id}",
                    "GET /api/v1/movement-repricing/stealth/{stealth_order_id}",
                ],
                identity_keys=["client_order_id", "stealth_order_id"],
                backend_contract_refs=[
                    "business/move_manager.py",
                    "core/stealth_order_manager.py",
                    "application/admin_api/read_service.py::build_movement_repricing_evidence",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::listMovementRepricingEvidence",
                    "src/features/admin-shell/AdminShell.tsx",
                ],
                documentation_refs=["README.movement-repricing.md"],
                frontend_boundary=(
                    "Display movement evidence only; do not clear cooldowns or mutate "
                    "revealed placements."
                ),
                spot_rule_boundary=(
                    "Spot replacement deltas are backend guard evidence only, not "
                    "browser authority."
                ),
            ),
            functionality_item(
                workflow_id="movement.reprice_command_draft",
                module_id="movement_repricing",
                module="Order Movement / Repricing",
                workflow_type=AdminApiFunctionalityWorkflowType.COMMAND_DRAFT,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth reprice is exposed as a live-disabled cancel/replace-shaped "
                    "draft keyed by stealth_order_id."
                ),
                backend_supported=True,
                admin_api_exposed=True,
                frontend_exposed=True,
                command_capable=True,
                live_designated=True,
                command_routes=[
                    "POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice",
                ],
                identity_keys=["stealth_order_id"],
                backend_contract_refs=[
                    "application/admin_api/command_service.py::reprice_stealth_order_by_stealth_order_id",
                    "api/v1/routes/movement_repricing.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::repriceStealthOrderByStealthOrderId",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                documentation_refs=["README.movement-repricing.md"],
                required_next_contract=(
                    "Backend live reprice contract with mutation claims, exchange "
                    "cancel/replace, approval, cap, audit, and reconciliation."
                ),
                blockers=["live_execution_disabled", "cancel/replace reconciliation missing"],
                frontend_boundary=(
                    "Keep as dry-submit evidence; do not call legacy dashboard repricer "
                    "or mutate cooldown state."
                ),
                spot_rule_boundary="No spot-only authority can approve movement/repricing.",
            ),
            functionality_item(
                workflow_id="futures.read_models",
                module_id="futures_perpetuals",
                module="Futures / Perpetuals",
                workflow_type=AdminApiFunctionalityWorkflowType.READ_MODEL,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_EXPOSED,
                support_status=AdminApiModuleSupportStatus.READ_ONLY_READY,
                summary=(
                    "Futures account and position read models are exposed with "
                    "position_key identity and position/risk evidence."
                ),
                backend_supported=True,
                admin_api_exposed=True,
                frontend_exposed=True,
                read_routes=[
                    "GET /api/v1/futures/account",
                    "GET /api/v1/futures/positions",
                    "GET /api/v1/futures/positions/{position_key}",
                ],
                identity_keys=["position_key"],
                backend_contract_refs=[
                    "application/admin_api/read_service.py::build_futures_account",
                    "application/admin_api/read_service.py::build_futures_positions",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::getFuturesAccount",
                    "src/features/admin-shell/AdminShell.tsx",
                ],
                documentation_refs=["README.futures-perpetuals.md"],
                frontend_boundary=(
                    "Display position/risk evidence only; do not infer close, reduce, "
                    "or placement commands."
                ),
                spot_rule_boundary=(
                    "Futures workflows must not use spot inventory, no-shorting, USDC, "
                    "or cost-basis authority."
                ),
            ),
            functionality_item(
                workflow_id="futures.commands_not_modeled",
                module_id="futures_perpetuals",
                module="Futures / Perpetuals",
                workflow_type=AdminApiFunctionalityWorkflowType.COMMAND_DRAFT,
                exposure_status=AdminApiFunctionalityExposureStatus.BACKEND_CONTRACT_REQUIRED,
                support_status=AdminApiModuleSupportStatus.NOT_MODELED,
                summary=(
                    "Futures placement, close, reduce, cancel, and funding workflows "
                    "are not modeled as Admin API commands yet."
                ),
                backend_supported=False,
                admin_api_exposed=False,
                frontend_exposed=False,
                command_capable=True,
                identity_keys=["position_key"],
                required_next_contract=(
                    "Backend command contracts over position side, margin, leverage, "
                    "liquidation, reduce-only, close-only, funding, cap, approval, audit, "
                    "and reconciliation evidence."
                ),
                blockers=["backend futures command contract missing"],
                backend_contract_refs=["api/v1/routes/futures.py"],
                frontend_contract_refs=["src/features/admin-shell/AdminShell.tsx"],
                documentation_refs=["README.futures-perpetuals.md"],
                frontend_boundary=(
                    "Do not add futures command drafts from spot order/cancel patterns."
                ),
                spot_rule_boundary="Spot rules are forbidden in futures command authority.",
            ),
            functionality_item(
                workflow_id="guard_risk.policy_evidence",
                module_id="guard_risk_policy",
                module="Guard / Risk Policy",
                workflow_type=AdminApiFunctionalityWorkflowType.PLATFORM_EVIDENCE,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_EXPOSED,
                support_status=AdminApiModuleSupportStatus.PLATFORM_READY,
                summary=(
                    "Backend guard/risk policy evidence is exposed as read-only "
                    "authority-source, limit, profitability, wallet, and rejection evidence."
                ),
                backend_supported=True,
                admin_api_exposed=True,
                frontend_exposed=True,
                read_routes=["GET /api/v1/admin/guard-risk-policy"],
                identity_keys=["policy_id", "product_id", "correlation_id"],
                backend_contract_refs=[
                    "core/action_condition_guard.py",
                    "core/product_capability.py",
                    "application/admin_api/read_service.py::build_guard_risk_policy",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::getGuardRiskPolicy",
                    "src/features/admin-shell/AdminShell.tsx",
                ],
                documentation_refs=["README.guard-risk-policy.md"],
                frontend_boundary=(
                    "Display backend guard evidence; never calculate guard, wallet, "
                    "inventory, margin, or profitability authority in the browser."
                ),
                spot_rule_boundary=(
                    "Spot-specific guard rows may be displayed but must not become "
                    "generic rules for non-spot workflows."
                ),
            ),
            functionality_item(
                workflow_id="audit.recovery_and_repair_evidence",
                module_id="audit_workbench",
                module="Audit Workbench",
                workflow_type=AdminApiFunctionalityWorkflowType.RECOVERY,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_EXPOSED,
                support_status=AdminApiModuleSupportStatus.PLATFORM_READY,
                summary=(
                    "Audit workbench, recovery gate, and fill-ledger health expose "
                    "read-only cross-module recovery and repair evidence."
                ),
                backend_supported=True,
                admin_api_exposed=True,
                frontend_exposed=True,
                read_routes=["GET /api/v1/admin/audit-workbench"],
                recovery_routes=[
                    "GET /api/v1/admin/recovery-gate",
                    "GET /api/v1/admin/fill-ledger-health",
                ],
                identity_keys=[
                    "client_order_id",
                    "stealth_order_id",
                    "position_key",
                    "audit_id",
                    "correlation_id",
                ],
                backend_contract_refs=[
                    "application/admin_api/read_service.py::build_audit_workbench",
                    "application/admin_api/read_service.py::build_recovery_gate",
                    "application/admin_api/read_service.py::build_fill_ledger_health",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::getAdminAuditWorkbench",
                    "src/features/admin-shell/AdminShell.tsx",
                ],
                documentation_refs=["README.audit-workbench.md"],
                required_next_contract=(
                    "Backend-owned repair mutation contracts before any ledger/audit "
                    "repair control is exposed."
                ),
                blockers=["repair mutation contract missing"],
                frontend_boundary=(
                    "Audit/recovery links are evidence only; do not mutate audit history, "
                    "repair ledgers, or replay commands from the browser."
                ),
                spot_rule_boundary="Audit may display spot rows but cannot promote spot identity.",
            ),
            functionality_item(
                workflow_id="audit.fill_ledger_repair_contract_required",
                module_id="audit_workbench",
                module="Audit Workbench",
                workflow_type=AdminApiFunctionalityWorkflowType.REPAIR,
                exposure_status=AdminApiFunctionalityExposureStatus.BACKEND_CONTRACT_REQUIRED,
                support_status=AdminApiModuleSupportStatus.NOT_MODELED,
                summary=(
                    "Fill-ledger repair tools and planning evidence exist outside the "
                    "enterprise Admin API mutation plane."
                ),
                backend_supported=True,
                admin_api_exposed=False,
                frontend_exposed=False,
                identity_keys=["client_order_id", "trade_id"],
                backend_contract_refs=[
                    "tools/run_spot_fill_ledger_repair.py",
                    "business/fill_reconciler.py",
                ],
                documentation_refs=["docs/SPOT_READINESS_ROADMAP.md"],
                required_next_contract=(
                    "Backend-owned repair command with RBAC, idempotency, audit, "
                    "dry-run preview, and reconciliation proof."
                ),
                blockers=["Admin API repair mutation contract missing"],
                frontend_boundary=(
                    "Do not expose ledger repair buttons until the backend mutation "
                    "contract exists."
                ),
                spot_rule_boundary=(
                    "Current repair tooling is spot/fill-ledger oriented and must not "
                    "be generalized to futures or stealth state mutation."
                ),
            ),
            functionality_item(
                workflow_id="legacy.dashboard_compatibility",
                module_id="legacy_dashboard_websocket",
                module="Legacy Dashboard WebSocket",
                workflow_type=AdminApiFunctionalityWorkflowType.LEGACY_COMPATIBILITY,
                exposure_status=AdminApiFunctionalityExposureStatus.COMPATIBILITY_ONLY,
                support_status=AdminApiModuleSupportStatus.UNSUPPORTED,
                summary=(
                    "Legacy dashboard WebSocket live surfaces exist for compatibility "
                    "but are not the enterprise admin command plane."
                ),
                backend_supported=True,
                admin_api_exposed=False,
                frontend_exposed=False,
                command_capable=True,
                live_designated=True,
                legacy_surfaces=[
                    "place_order WebSocket",
                    "place_hotpoint_test_order WebSocket",
                    "cancel_order WebSocket",
                ],
                identity_keys=["client_order_id"],
                backend_contract_refs=["dashboard_server.py", "docs/LIVE_ORDER_SURFACES.md"],
                frontend_contract_refs=["src/shared/api/contracts/adminBffProxy.ts"],
                documentation_refs=["docs/LIVE_ORDER_SURFACES.md"],
                required_next_contract=(
                    "Any enterprise replacement must be an Admin API route through "
                    "auth, RBAC, idempotency, approval, caps, audit, and reconciliation."
                ),
                blockers=["compatibility-only surface"],
                frontend_boundary=(
                    "Do not call legacy dashboard WebSocket command handlers from the "
                    "enterprise frontend."
                ),
                spot_rule_boundary=(
                    "Legacy spot behavior is not reusable frontend authority."
                ),
            ),
        ]
        approval_lifecycle_surfaces = [
            "POST /api/v1/admin/approvals/requests",
            "POST /api/v1/admin/approvals/requests/{approval_request_id}/decisions",
            "POST /api/v1/admin/approvals/{approval_id}/revoke",
        ]
        approval_lifecycle_rows = [
            route_inventory_item(surface)
            for surface in approval_lifecycle_surfaces
        ]
        admission_audit_surfaces = [
            "POST /api/v1/admin/admission-audits",
        ]
        admission_audit_rows = [
            route_inventory_item(surface)
            for surface in admission_audit_surfaces
        ]
        cap_guard_decision_surfaces = [
            "POST /api/v1/admin/cap-guard/decisions",
        ]
        cap_guard_decision_rows = [
            route_inventory_item(surface)
            for surface in cap_guard_decision_surfaces
        ]
        reconciliation_plan_surfaces = [
            "POST /api/v1/admin/reconciliation/plans",
        ]
        reconciliation_plan_rows = [
            route_inventory_item(surface)
            for surface in reconciliation_plan_surfaces
        ]
        mutation_taxonomy = [
            mutation_taxonomy_item(
                mutation_id="admin.approval_lifecycle",
                mutation_family=AdminApiMutationFamilyType.ADMIN_APPROVAL_LIFECYCLE,
                workflow_id="admin.approval_lifecycle",
                module_id="admin_system_health",
                module="Admin / System Health",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_EXPOSED,
                support_status=AdminApiModuleSupportStatus.PLATFORM_READY,
                summary=(
                    "Approval lifecycle is a backend-owned local-state mutation "
                    "family for request, decision, revoke, expiry, and snapshot "
                    "linking; it is not live execution authority by itself."
                ),
                command_surfaces=approval_lifecycle_surfaces,
                action_classes=[
                    row.action_class for row in approval_lifecycle_rows
                ],
                required_permissions=[
                    row.permission for row in approval_lifecycle_rows
                ],
                identity_keys=[
                    "approval_request_id",
                    "approval_id",
                    "client_order_id",
                    "stealth_order_id",
                    "campaign_id",
                    "position_key",
                ],
                payload_binding_fields=[
                    "route",
                    "method",
                    "module_id",
                    "identity_key",
                    "identity_value",
                    "action_class",
                    "required_permission",
                    "operator_intent",
                    "command_idempotency_key",
                    "payload_hash",
                    "cap_guard_decision_ref",
                    "reconciliation_plan_ref",
                ],
                idempotency_contract="required",
                approval_contract=(
                    "backend-owned append-only request/decision/revoke "
                    "lifecycle; browser approval is insufficient for execution"
                ),
                cap_guard_contract=(
                    "approved snapshots must bind cap_guard_decision_ref but "
                    "do not execute cap/guard checks"
                ),
                admission_audit_contract=(
                    "approval lifecycle mutations append Admin API audit events"
                ),
                reconciliation_contract=(
                    "approved snapshots must bind reconciliation_plan_ref; "
                    "reconciliation execution remains separate"
                ),
                owning_backend_service="application/admin_api/approval_service.py",
                shared_command_service_method=None,
                route_inventory_refs=approval_lifecycle_surfaces,
                backend_contract_refs=[
                    "application/admin_api/approval.py",
                    "application/admin_api/approval_service.py",
                    "api/v1/routes/approvals.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts",
                    "src/features/admin-shell/AdminShell.tsx",
                ],
                documentation_refs=[
                    "README.admin-api.md",
                    "docs/examples/admin-api.md",
                ],
                required_next_contract=(
                    "Cap/guard decision execution records must link to approved "
                    "snapshots before live command admission can proceed."
                ),
                blockers=[
                    "live_execution_disabled",
                    "cap_guard_missing",
                    "reconciliation_plan_missing",
                ],
                frontend_boundary=(
                    "The frontend may request and display approval lifecycle "
                    "state through generated contracts only; it must not become "
                    "approval authority, a live switch, or a command executor."
                ),
                bff_boundary=(
                    "BFF may forward only to backend approval lifecycle routes "
                    "with required mutation evidence; it must not approve or "
                    "execute commands."
                ),
                route_local_boundary=(
                    "Approval routes may append lifecycle and snapshot evidence "
                    "through the approval service only; they must not call "
                    "Coinbase or command execution adapters."
                ),
                spot_rule_boundary=(
                    "Approval lifecycle is a platform primitive. Spot wallet, "
                    "USDC, cost-basis, and no-shorting rules are not generic "
                    "approval rules."
                ),
                cap_guard_required=True,
                reconciliation_required=True,
                live_adapter_required=False,
            ),
            mutation_taxonomy_item(
                mutation_id="admin.admission_audits",
                mutation_family=AdminApiMutationFamilyType.ADMIN_ADMISSION_AUDIT,
                workflow_id="admin.admission_audits",
                module_id="admin_system_health",
                module="Admin / System Health",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_EXPOSED,
                support_status=AdminApiModuleSupportStatus.PLATFORM_READY,
                summary=(
                    "Admission audits are backend-owned append-only records that "
                    "link route, identity, payload, idempotency, approval "
                    "snapshot, expected cap/guard decision, expected "
                    "reconciliation plan, and disabled live intent evidence."
                ),
                command_surfaces=admission_audit_surfaces,
                action_classes=[
                    row.action_class for row in admission_audit_rows
                ],
                required_permissions=[
                    row.permission for row in admission_audit_rows
                ],
                identity_keys=[
                    "admission_audit_id",
                    "approval_snapshot_id",
                    "approval_cap_guard_decision_ref",
                    "approval_reconciliation_plan_ref",
                    "client_order_id",
                    "stealth_order_id",
                    "campaign_id",
                    "position_key",
                ],
                payload_binding_fields=[
                    "route",
                    "method",
                    "module_id",
                    "identity_key",
                    "identity_value",
                    "action_class",
                    "required_permission",
                    "service_method",
                    "actor_id",
                    "operator_intent",
                    "command_idempotency_key",
                    "payload_hash",
                    "approval_snapshot_id",
                    "approval_cap_guard_decision_ref",
                    "approval_reconciliation_plan_ref",
                    "allowed",
                    "status",
                    "reason",
                ],
                idempotency_contract="required",
                approval_contract=(
                    "records must reference a backend approval snapshot id; "
                    "they do not approve snapshots or commands"
                ),
                cap_guard_contract=(
                    "records bind expected cap/guard decision refs but do not "
                    "evaluate guards or create cap/guard decisions"
                ),
                admission_audit_contract=(
                    "accepted records append an exact resolver-eligible audit "
                    "event to the existing Admin API audit log"
                ),
                reconciliation_contract=(
                    "records bind expected reconciliation plan refs but do not "
                    "create, execute, or prove reconciliation"
                ),
                owning_backend_service="application/admin_api/admission_audit_service.py",
                shared_command_service_method=None,
                route_inventory_refs=admission_audit_surfaces,
                backend_contract_refs=[
                    "application/admin_api/audit.py",
                    "application/admin_api/admission_audit_service.py",
                    "api/v1/routes/admission_audit.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts",
                    "src/features/admin-shell/AdminShell.tsx",
                ],
                documentation_refs=[
                    "README.admin-api.md",
                    "docs/examples/admin-api.md",
                ],
                required_next_contract=(
                    "Reconciliation plan and proof runner must complete before "
                    "live command admission can advance."
                ),
                blockers=[
                    "live_execution_disabled",
                    "cap_guard_missing",
                    "reconciliation_plan_missing",
                ],
                frontend_boundary=(
                    "The frontend may record and display backend admission audit "
                    "records through generated contracts only; it must not write "
                    "browser audit history, approve commands, or claim execution."
                ),
                bff_boundary=(
                    "BFF may forward only to backend admission audit routes with "
                    "required mutation evidence; it must not create audit proof "
                    "or execute commands on its own."
                ),
                route_local_boundary=(
                    "Admission audit routes append evidence through the audit "
                    "service only; they must not call Coinbase, evaluate guards, "
                    "run reconciliation, or execute commands."
                ),
                spot_rule_boundary=(
                    "Admission audit records are platform evidence. Spot wallet, "
                    "USDC, cost-basis, and no-shorting rules remain route-specific "
                    "guard inputs, not generic admin audit rules."
                ),
                approval_required=True,
                cap_guard_required=True,
                reconciliation_required=True,
                live_adapter_required=False,
            ),
            mutation_taxonomy_item(
                mutation_id="admin.cap_guard_decisions",
                mutation_family=AdminApiMutationFamilyType.ADMIN_CAP_GUARD_DECISION,
                workflow_id="admin.cap_guard_decisions",
                module_id="admin_system_health",
                module="Admin / System Health",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_EXPOSED,
                support_status=AdminApiModuleSupportStatus.PLATFORM_READY,
                summary=(
                    "Cap/guard decisions are backend-owned append-only local-state "
                    "records that link route, payload, actor, approval snapshot, "
                    "and admission audit evidence before command admission can "
                    "consider cap/guard proof present."
                ),
                command_surfaces=cap_guard_decision_surfaces,
                action_classes=[
                    row.action_class for row in cap_guard_decision_rows
                ],
                required_permissions=[
                    row.permission for row in cap_guard_decision_rows
                ],
                identity_keys=[
                    "decision_id",
                    "approval_cap_guard_decision_ref",
                    "approval_snapshot_id",
                    "admission_audit_id",
                    "client_order_id",
                    "stealth_order_id",
                    "campaign_id",
                    "position_key",
                ],
                payload_binding_fields=[
                    "route",
                    "method",
                    "module_id",
                    "identity_key",
                    "identity_value",
                    "action_class",
                    "required_permission",
                    "service_method",
                    "actor_id",
                    "operator_intent",
                    "command_idempotency_key",
                    "payload_hash",
                    "approval_snapshot_id",
                    "approval_cap_guard_decision_ref",
                    "admission_audit_id",
                    "allowed",
                    "status",
                    "cap_policy_ref",
                    "guard_policy_ref",
                    "product_scope",
                ],
                idempotency_contract="required",
                approval_contract=(
                    "records must reference a backend approval snapshot id; "
                    "they do not create or approve snapshots"
                ),
                cap_guard_contract=(
                    "only allowed=true plus status=passed is resolver-eligible; "
                    "blocked or warning records remain durable fail-closed evidence"
                ),
                admission_audit_contract=(
                    "records must bind to an append-only admission audit id and "
                    "also append an Admin API audit event for the record mutation"
                ),
                reconciliation_contract=(
                    "cap/guard decisions do not create reconciliation plans; "
                    "future command admission must resolve reconciliation separately"
                ),
                owning_backend_service="application/admin_api/cap_guard_service.py",
                shared_command_service_method=None,
                route_inventory_refs=cap_guard_decision_surfaces,
                backend_contract_refs=[
                    "application/admin_api/cap_guard.py",
                    "application/admin_api/cap_guard_service.py",
                    "api/v1/routes/cap_guard.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts",
                    "src/features/admin-shell/AdminShell.tsx",
                ],
                documentation_refs=[
                    "README.admin-api.md",
                    "docs/examples/admin-api.md",
                ],
                required_next_contract=(
                    "Reconciliation plan and proof runner must complete before "
                    "live command admission can advance."
                ),
                blockers=[
                    "live_execution_disabled",
                    "reconciliation_plan_missing",
                ],
                frontend_boundary=(
                    "The frontend may record and display backend cap/guard "
                    "decision records through generated contracts only; it must "
                    "not evaluate wallet, margin, profitability, inventory, or "
                    "account-limit rules in the browser."
                ),
                bff_boundary=(
                    "BFF may forward only to backend cap/guard decision routes "
                    "with required mutation evidence; it must not evaluate or "
                    "override guard decisions."
                ),
                route_local_boundary=(
                    "Cap/guard routes append evidence through the cap_guard "
                    "service only; they must not call Coinbase, evaluate trading "
                    "guards, or execute commands."
                ),
                spot_rule_boundary=(
                    "Cap/guard decision records are platform evidence. Spot "
                    "wallet, USDC, cost-basis, and no-shorting rules remain "
                    "route-specific guard inputs, not generic admin rules."
                ),
                approval_required=True,
                cap_guard_required=True,
                reconciliation_required=True,
                live_adapter_required=False,
            ),
            mutation_taxonomy_item(
                mutation_id="admin.reconciliation_plans",
                mutation_family=AdminApiMutationFamilyType.ADMIN_RECONCILIATION_PLAN,
                workflow_id="admin.reconciliation_plans",
                module_id="admin_system_health",
                module="Admin / System Health",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_EXPOSED,
                support_status=AdminApiModuleSupportStatus.PLATFORM_READY,
                summary=(
                    "Reconciliation plans are backend-owned append-only "
                    "local-state records that link route, payload, approval "
                    "snapshot, admission audit, cap/guard decision, and "
                    "reconciliation policy proof before command admission can "
                    "consider reconciliation present."
                ),
                command_surfaces=reconciliation_plan_surfaces,
                action_classes=[
                    row.action_class for row in reconciliation_plan_rows
                ],
                required_permissions=[
                    row.permission for row in reconciliation_plan_rows
                ],
                identity_keys=[
                    "plan_id",
                    "approval_reconciliation_plan_ref",
                    "approval_snapshot_id",
                    "admission_audit_id",
                    "cap_guard_decision_id",
                    "client_order_id",
                    "stealth_order_id",
                    "campaign_id",
                    "position_key",
                ],
                payload_binding_fields=[
                    "route",
                    "method",
                    "module_id",
                    "identity_key",
                    "identity_value",
                    "action_class",
                    "required_permission",
                    "service_method",
                    "actor_id",
                    "operator_intent",
                    "command_idempotency_key",
                    "payload_hash",
                    "approval_snapshot_id",
                    "approval_reconciliation_plan_ref",
                    "admission_audit_id",
                    "cap_guard_decision_id",
                    "allowed",
                    "status",
                    "reconciliation_policy_ref",
                    "product_scope",
                ],
                idempotency_contract="required",
                approval_contract=(
                    "records must reference a backend approval snapshot id; "
                    "they do not create or approve snapshots"
                ),
                cap_guard_contract=(
                    "records must reference a backend cap/guard decision id; "
                    "they do not evaluate or override guard decisions"
                ),
                admission_audit_contract=(
                    "records must bind to an append-only admission audit id and "
                    "also append an Admin API audit event for the plan mutation"
                ),
                reconciliation_contract=(
                    "only allowed=true plus status=passed is resolver-eligible; "
                    "the record does not execute reconciliation or mutate "
                    "order/exchange state"
                ),
                owning_backend_service=(
                    "application/admin_api/reconciliation_service.py"
                ),
                shared_command_service_method=None,
                route_inventory_refs=reconciliation_plan_surfaces,
                backend_contract_refs=[
                    "application/admin_api/reconciliation.py",
                    "application/admin_api/reconciliation_service.py",
                    "api/v1/routes/reconciliation.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts",
                    "src/features/admin-shell/AdminShell.tsx",
                ],
                documentation_refs=[
                    "README.admin-api.md",
                    "docs/examples/admin-api.md",
                ],
                required_next_contract=(
                    "Controlled live adapter pilot must still keep live service "
                    "enablement and route-specific adapter admission explicit."
                ),
                blockers=[
                    "live_execution_disabled",
                    "browser_authority_rejected",
                ],
                frontend_boundary=(
                    "The frontend may record and display backend reconciliation "
                    "plan records through generated contracts only; it must not "
                    "execute reconciliation, mark exchange state reconciled, or "
                    "treat plan proof as Coinbase submission authority."
                ),
                bff_boundary=(
                    "BFF may forward only to backend reconciliation plan routes "
                    "with required mutation evidence; it must not create "
                    "reconciliation proof, run reconciliation, or execute commands "
                    "on its own."
                ),
                route_local_boundary=(
                    "Reconciliation plan routes append evidence through the "
                    "reconciliation service only; they must not call Coinbase, "
                    "run reconciliation, mutate order/exchange state, or execute "
                    "commands."
                ),
                spot_rule_boundary=(
                    "Reconciliation plan records are platform evidence. Spot "
                    "fill-ledger, retained-inventory, USDC, and no-shorting "
                    "rules remain route-specific backend proof."
                ),
                approval_required=True,
                cap_guard_required=True,
                reconciliation_required=True,
                live_adapter_required=False,
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/admin/live-execution/service-decisions",
                mutation_id="admin.live_service_decisions",
                mutation_family=AdminApiMutationFamilyType.ADMIN_LIVE_SERVICE_DECISION,
                workflow_id="admin.live_service_decisions",
                module="Admin / System Health",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_EXPOSED,
                support_status=AdminApiModuleSupportStatus.PLATFORM_READY,
                summary=(
                    "Live-service decision records are backend-owned append-only "
                    "local-state evidence for the disabled live service. They do "
                    "not enable service or live Coinbase execution."
                ),
                identity_keys=[
                    "decision_id",
                    "deployment_ref",
                    "runtime_configuration_ref",
                ],
                owning_backend_service=(
                    "application/admin_api/live_service_decision_service.py"
                ),
                frontend_boundary=(
                    "The frontend may record and display disabled live-service "
                    "decision evidence through generated contracts only; it must "
                    "not enable service, approve Coinbase execution, or clear "
                    "live-readiness blockers."
                ),
                spot_rule_boundary=(
                    "Live-service decision evidence is platform evidence. Spot "
                    "wallet, USDC, cost-basis, and no-shorting rules stay in "
                    "route-specific guard inputs."
                ),
                backend_contract_refs=[
                    "application/admin_api/live_execution.py",
                    "application/admin_api/live_service_decision_service.py",
                    "api/v1/routes/live_execution.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts",
                    "src/shared/api/contracts/mutationContracts.ts",
                    "src/shared/api/contracts/adminBffProxy.ts",
                ],
                documentation_refs=[
                    "README.admin-api.md",
                    "docs/examples/admin-api.md",
                ],
                required_next_contract=(
                    "Live service, route-specific adapter, verification, and "
                    "execution authority evidence must be approved before live "
                    "commands can run."
                ),
                blockers=[
                    "live_execution_disabled",
                    "live_service_enablement_missing",
                    "live_adapter_construction_missing",
                ],
                bff_boundary=(
                    "BFF may forward only to backend live-service decision routes "
                    "with required mutation evidence; it must not enable service "
                    "or execute commands."
                ),
                route_local_boundary=(
                    "Live-service decision routes append disabled decision "
                    "evidence only; they must not construct adapters, call "
                    "Coinbase, invoke managers, run reconciliation, or mutate "
                    "order state."
                ),
                live_adapter_required=False,
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/orders",
                mutation_id="spot.manual_order",
                mutation_family=AdminApiMutationFamilyType.SPOT_MANUAL_ORDER,
                workflow_id="spot.order_command_drafts",
                module="Spot Operations",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Manual spot order placement is a live-disabled Admin API "
                    "command family keyed by backend-supplied client_order_id."
                ),
                identity_keys=["client_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/orders.py::place_manual_order",
                    "application/admin_api/command_service.py::place_manual_order",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::createManualOrder",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                documentation_refs=["docs/COMMAND_WORKFLOWS.md"],
                required_next_contract=(
                    "Route-specific approval snapshot, cap/guard decision, "
                    "admission audit, reconciliation plan, and executable live "
                    "adapter must all pass before Coinbase placement."
                ),
                blockers=[
                    "live_execution_disabled",
                    "approval_snapshot_missing",
                    "cap_guard_missing",
                    "reconciliation_plan_missing",
                ],
                frontend_boundary=(
                    "The browser may draft and dry-submit through generated "
                    "contracts only; it must not submit Coinbase orders, compute "
                    "wallet authority, or bypass backend guards."
                ),
                spot_rule_boundary=(
                    "Spot-only no-shorting, USDC, wallet, lot, and cost-basis "
                    "authority must remain backend guard evidence."
                ),
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/orders/{client_order_id}/cancel",
                mutation_id="spot.order_cancel",
                mutation_family=AdminApiMutationFamilyType.SPOT_ORDER_CANCEL,
                workflow_id="spot.order_command_drafts",
                module="Spot Operations",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Spot cancel is keyed by client_order_id and must call the "
                    "project cancel_order(client_order_id) wrapper because Coinbase "
                    "accepts the client id for cancellation."
                ),
                identity_keys=["client_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/orders.py::cancel_order_by_client_order_id",
                    "application/admin_api/command_service.py::cancel_order_by_client_order_id",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::cancelOrderByClientOrderId",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                documentation_refs=[
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/agents/INVARIANTS.md",
                ],
                required_next_contract=(
                    "Backend cancel admission must link approval, cap/guard, audit, "
                    "exchange cancel evidence, and reconciliation by client_order_id."
                ),
                blockers=[
                    "live_execution_disabled",
                    "approval_snapshot_missing",
                    "cancel reconciliation proof missing",
                ],
                frontend_boundary=(
                    "Do not accept exchange order_id as the internal cancel identity; "
                    "frontend cancel evidence must stay client_order_id-scoped."
                ),
                spot_rule_boundary=(
                    "Spot cancel may release spot inventory holds only through backend "
                    "reconciliation; browser state is not wallet authority."
                ),
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/spot/campaign/executions",
                mutation_id="spot.campaign_execution",
                mutation_family=AdminApiMutationFamilyType.SPOT_CAMPAIGN_EXECUTION,
                workflow_id="spot.order_command_drafts",
                related_workflow_ids=["spot.sweep_automation_and_live_executor"],
                module="Spot Operations",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Spot campaign execution is the Admin API command family for "
                    "campaign and sweep automation review, still live-disabled."
                ),
                identity_keys=["campaign_id", "config_id", "client_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/orders.py::execute_spot_campaign",
                    "application/admin_api/command_service.py::execute_spot_campaign",
                    "business/spot_campaign.py",
                    "business/spot_portfolio_sweep.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::executeSpotCampaign",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                documentation_refs=[
                    "README.spot-campaign.md",
                    "README.spot-portfolio-sweep.md",
                ],
                required_next_contract=(
                    "Durable scheduler, run-limit, approval, cap/guard, audit, "
                    "execution, recovery, and reconciliation contracts for each run."
                ),
                blockers=[
                    "live_execution_disabled",
                    "backend scheduling UI contract missing",
                    "run reconciliation proof missing",
                ],
                frontend_boundary=(
                    "Do not launch live sweep tools or implement a browser scheduler; "
                    "only display/dry-submit backend campaign evidence."
                ),
                spot_rule_boundary=(
                    "Spot campaign automation must keep USDC scope, no-shorting, "
                    "inventory, and cost-basis authority inside backend gates."
                ),
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/spot/sweep/automation-runs",
                mutation_id="spot.sweep_automation",
                mutation_family=AdminApiMutationFamilyType.SPOT_SWEEP_AUTOMATION,
                workflow_id="spot.sweep_automation_and_live_executor",
                related_workflow_ids=["spot.order_command_drafts"],
                module="Spot Operations",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Spot sweep automation is a route-bound Admin API command "
                    "contract keyed by sweep_config_id, still live-disabled."
                ),
                identity_keys=["sweep_config_id", "config_id", "client_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/orders.py::run_spot_sweep_automation",
                    "application/admin_api/command_service.py::run_spot_sweep_automation",
                    "business/spot_portfolio_sweep.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::runSpotSweepAutomation",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                documentation_refs=[
                    "README.spot-portfolio-sweep.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                required_next_contract=(
                    "Durable sweep scheduler, run-limit, pause/resume, recovery, "
                    "execution, and reconciliation contracts must pass before "
                    "live Coinbase submission."
                ),
                blockers=[
                    "live_execution_disabled",
                    "sweep scheduler contract missing",
                    "run reconciliation proof missing",
                ],
                frontend_boundary=(
                    "Do not run sweep tools or implement a browser scheduler; "
                    "only dry-submit through the backend-owned command contract."
                ),
                spot_rule_boundary=(
                    "Sweep automation is spot-only and must keep USDC scope, "
                    "inventory, average-cost, and known-profitable sell authority "
                    "inside backend gates."
                ),
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/spot/recovery/apply-executions",
                mutation_id="spot.recovery_apply_execution",
                mutation_family=AdminApiMutationFamilyType.SPOT_RECOVERY_APPLY_EXECUTION,
                workflow_id="spot.recovery_workflow",
                related_workflow_ids=["spot.reconciliation_workflow"],
                module="Spot Operations",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Spot recovery apply execution is a route-bound disabled "
                    "Admin API command contract keyed by client_order_id."
                ),
                identity_keys=["client_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/orders.py::execute_spot_recovery_apply",
                    "application/admin_api/command_service.py::execute_spot_recovery_apply",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::executeSpotRecoveryApply",
                    "src/features/spot-ops/SpotReadOnlyViews.tsx",
                ],
                documentation_refs=["README.spot-trading.md", "docs/COMMAND_WORKFLOWS.md"],
                required_next_contract=(
                    "Backend repair application, rollback persistence, "
                    "exchange-state proof evidence, and post-apply "
                    "reconciliation must exist before recovery can mutate state."
                ),
                blockers=[
                    "live_execution_disabled",
                    "recovery_apply_executor_missing",
                    "exchange_state_proof_required",
                    "post_apply_reconciliation_missing",
                ],
                frontend_boundary=(
                    "The browser may dry-submit the backend contract only; it must "
                    "not apply repairs, mutate order state, or create recovery proof."
                ),
                route_local_boundary=(
                    "The route writes command audit/idempotency evidence only; it "
                    "must not call repair tools, mutate order state, or call Coinbase."
                ),
                spot_rule_boundary=(
                    "Spot recovery is spot-only operational repair evidence and "
                    "must not become a generic futures/perpetual repair model."
                ),
                live_adapter_required=False,
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/spot/recovery/rollback-executions",
                mutation_id="spot.recovery_rollback_execution",
                mutation_family=(
                    AdminApiMutationFamilyType.SPOT_RECOVERY_ROLLBACK_EXECUTION
                ),
                workflow_id="spot.recovery_workflow",
                related_workflow_ids=["spot.reconciliation_workflow"],
                module="Spot Operations",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Spot recovery rollback execution is a route-bound disabled "
                    "Admin API command contract keyed by client_order_id."
                ),
                identity_keys=["client_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/orders.py::execute_spot_recovery_rollback",
                    "application/admin_api/command_service.py::execute_spot_recovery_rollback",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::executeSpotRecoveryRollback",
                    "src/features/spot-ops/SpotReadOnlyViews.tsx",
                ],
                documentation_refs=["README.spot-trading.md", "docs/COMMAND_WORKFLOWS.md"],
                required_next_contract=(
                    "Backend rollback implementation and post-rollback "
                    "reconciliation proof must exist before rollback can mutate state."
                ),
                blockers=[
                    "live_execution_disabled",
                    "recovery_rollback_executor_missing",
                    "reconciliation_proof_required",
                ],
                frontend_boundary=(
                    "The browser may dry-submit the backend contract only; it must "
                    "not roll back order state or create recovery proof."
                ),
                route_local_boundary=(
                    "The route writes command audit/idempotency evidence only; it "
                    "must not call repair tools, mutate order state, or call Coinbase."
                ),
                spot_rule_boundary=(
                    "Spot rollback evidence is spot-only repair posture and must "
                    "not be copied into non-spot modules without module contracts."
                ),
                live_adapter_required=False,
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/spot/recovery/exchange-state-proofs",
                mutation_id="spot.recovery_exchange_state_proof",
                mutation_family=(
                    AdminApiMutationFamilyType.SPOT_RECOVERY_EXCHANGE_STATE_PROOF
                ),
                workflow_id="spot.reconciliation_workflow",
                related_workflow_ids=["spot.recovery_workflow"],
                module="Spot Operations",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Spot recovery exchange-state proof writing is a route-bound "
                    "Admin API proof record contract keyed by client_order_id."
                ),
                identity_keys=["client_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/orders.py::record_spot_recovery_exchange_state_proof",
                    "application/admin_api/command_service.py::record_spot_recovery_exchange_state_proof",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::recordSpotRecoveryExchangeStateProof",
                    "src/features/spot-ops/SpotReadOnlyViews.tsx",
                ],
                documentation_refs=["README.spot-trading.md", "docs/COMMAND_WORKFLOWS.md"],
                required_next_contract=(
                    "Backend exchange-state evidence capture must exist before "
                    "the proof writer can record exchange truth."
                ),
                blockers=[
                    "live_execution_disabled",
                    "exchange_state_capture_missing",
                ],
                frontend_boundary=(
                    "The browser may submit the backend record contract only; it "
                    "must not fetch Coinbase, capture exchange truth, or persist "
                    "proof outside the backend route."
                ),
                route_local_boundary=(
                    "The route writes append-only proof, command audit, and "
                    "idempotency evidence only; it must not fetch Coinbase or "
                    "mutate exchange/order state."
                ),
                spot_rule_boundary=(
                    "Spot exchange-state proof is a spot recovery contract; "
                    "futures/perpetual proof must be position/collateral-aware."
                ),
                live_adapter_required=False,
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/spot/recovery/exchange-state-snapshots",
                mutation_id="spot.recovery_exchange_state_snapshot",
                mutation_family=(
                    AdminApiMutationFamilyType.SPOT_RECOVERY_EXCHANGE_STATE_SNAPSHOT
                ),
                workflow_id="spot.reconciliation_workflow",
                related_workflow_ids=["spot.recovery_workflow"],
                module="Spot Operations",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Spot recovery exchange-state snapshot writing is a "
                    "route-bound Admin API evidence contract keyed by "
                    "client_order_id."
                ),
                identity_keys=[
                    "client_order_id",
                    "product_id",
                    "exchange_state_snapshot_id",
                ],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/orders.py::record_spot_recovery_exchange_state_snapshot",
                    "application/admin_api/command_service.py::record_spot_recovery_exchange_state_snapshot",
                    "application/admin_api/spot_recovery_snapshot.py",
                    "application/admin_api/spot_recovery_snapshot_service.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::recordSpotRecoveryExchangeStateSnapshot",
                    "src/features/spot-ops/SpotReadOnlyViews.tsx",
                ],
                documentation_refs=[
                    "README.spot-trading.md",
                    "README.reconciliation-plans.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                required_next_contract=(
                    "Backend live Coinbase read authority and reconciliation "
                    "executor contracts must exist before a snapshot can prove "
                    "exchange truth or drive state mutation."
                ),
                blockers=[
                    "live_execution_disabled",
                    "coinbase_live_read_disabled",
                    "reconciliation_executor_disabled",
                ],
                frontend_boundary=(
                    "The browser may submit the backend record contract only; "
                    "it must not fetch Coinbase, trust browser exchange state, "
                    "or persist snapshot evidence outside the backend route."
                ),
                route_local_boundary=(
                    "The route writes append-only local snapshot evidence, "
                    "command audit, and idempotency evidence only; it must not "
                    "read Coinbase, execute reconciliation, or mutate "
                    "exchange/order state."
                ),
                spot_rule_boundary=(
                    "Spot exchange-state snapshots are spot recovery evidence; "
                    "futures/perpetual snapshots must be position and "
                    "collateral aware."
                ),
                live_adapter_required=False,
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/spot/recovery/reconciliation-executions",
                mutation_id="spot.recovery_reconciliation_execution",
                mutation_family=(
                    AdminApiMutationFamilyType.SPOT_RECOVERY_RECONCILIATION_EXECUTION
                ),
                workflow_id="spot.reconciliation_workflow",
                related_workflow_ids=["spot.recovery_workflow"],
                module="Spot Operations",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Spot recovery reconciliation execution is a route-bound "
                    "disabled Admin API command contract keyed by client_order_id."
                ),
                identity_keys=["client_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/orders.py::execute_spot_recovery_reconciliation",
                    "application/admin_api/command_service.py::execute_spot_recovery_reconciliation",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::executeSpotRecoveryReconciliation",
                    "src/features/spot-ops/SpotReadOnlyViews.tsx",
                ],
                documentation_refs=[
                    "README.spot-trading.md",
                    "README.reconciliation-plans.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                required_next_contract=(
                    "Backend reconciliation executor and live Coinbase read "
                    "authority must exist before reconciliation can mutate "
                    "local order state or prove exchange truth."
                ),
                blockers=[
                    "live_execution_disabled",
                    "reconciliation_executor_disabled",
                    "coinbase_live_read_disabled",
                ],
                frontend_boundary=(
                    "The browser may dry-submit the backend contract only; it "
                    "must not execute reconciliation, compare Coinbase evidence, "
                    "or mutate order/exchange state."
                ),
                route_local_boundary=(
                    "The route writes command audit/idempotency evidence and "
                    "returns a fail-closed response only; it must not execute "
                    "reconciliation, mutate state, or call Coinbase."
                ),
                spot_rule_boundary=(
                    "Spot reconciliation execution is spot-specific operational "
                    "repair authority and must not be copied into non-spot "
                    "modules without module-specific contracts."
                ),
                live_adapter_required=False,
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/spot/recovery/reconciliation-proofs",
                mutation_id="spot.recovery_reconciliation_proof",
                mutation_family=(
                    AdminApiMutationFamilyType.SPOT_RECOVERY_RECONCILIATION_PROOF
                ),
                workflow_id="spot.reconciliation_workflow",
                related_workflow_ids=["spot.recovery_workflow"],
                module="Spot Operations",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Spot recovery reconciliation-proof writing is a route-bound "
                    "Admin API proof record contract keyed by client_order_id."
                ),
                identity_keys=["client_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/orders.py::record_spot_recovery_reconciliation_proof",
                    "application/admin_api/command_service.py::record_spot_recovery_reconciliation_proof",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::recordSpotRecoveryReconciliationProof",
                    "src/features/spot-ops/SpotReadOnlyViews.tsx",
                ],
                documentation_refs=[
                    "README.spot-trading.md",
                    "README.reconciliation-plans.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                required_next_contract=(
                    "Backend reconciliation execution must exist before "
                    "reconciliation proof can claim reconciliation execution."
                ),
                blockers=[
                    "live_execution_disabled",
                    "reconciliation_execution_missing",
                ],
                frontend_boundary=(
                    "The browser may submit the backend record contract only; it "
                    "must not execute reconciliation or create proof authority."
                ),
                route_local_boundary=(
                    "The route writes append-only proof, command audit, and "
                    "idempotency evidence only; it must not execute reconciliation, "
                    "mutate state, or call Coinbase."
                ),
                spot_rule_boundary=(
                    "Spot reconciliation proof is spot-specific and must not be "
                    "treated as a platform default for non-spot modules."
                ),
                live_adapter_required=False,
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/spot/pnl/checkpoints",
                mutation_id="spot.pnl_checkpoint",
                mutation_family=AdminApiMutationFamilyType.SPOT_PNL_CHECKPOINT,
                workflow_id="spot.pnl_checkpoint_records",
                related_workflow_ids=["spot.pnl_tracking_gap"],
                module="Spot Operations",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_EXPOSED,
                support_status=AdminApiModuleSupportStatus.PLATFORM_READY,
                summary=(
                    "Spot P/L checkpoint records are backend-owned local-state "
                    "review evidence over /api/v1/spot/sweep/pnl snapshots with "
                    "verified append-only Admin API audit-link readback."
                ),
                identity_keys=[
                    "checkpoint_id",
                    "audit_id",
                    "product_id",
                    "client_order_id",
                ],
                owning_backend_service=(
                    "application/admin_api/pnl_checkpoint_service.py"
                ),
                backend_contract_refs=[
                    "api/v1/routes/spot.py::record_spot_pnl_checkpoint",
                    "application/admin_api/pnl_checkpoint.py",
                    "application/admin_api/pnl_checkpoint_service.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::recordSpotPnlCheckpoint",
                    "src/features/spot-ops/SpotReadOnlyViews.tsx",
                ],
                documentation_refs=[
                    "README.spot-portfolio-sweep.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                required_next_contract=(
                    "Frontend checkpoint record form plus recovery and "
                    "reconciliation linkage before checkpoint evidence can "
                    "drive operator remediation workflows."
                ),
                blockers=[
                    "frontend checkpoint record form missing",
                    "reconciliation linkage missing",
                ],
                frontend_boundary=(
                    "The browser may display and forward checkpoint records only; "
                    "it must not create audit authority, calculate profitability, "
                    "approve sells, create tax accounting, run recovery or "
                    "reconciliation, or call Coinbase."
                ),
                spot_rule_boundary=(
                    "Spot P/L checkpoint evidence is operational review data only; "
                    "average-cost, lot authority, and known-profitable sell "
                    "authority remain backend guard inputs."
                ),
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/stealth/orders",
                mutation_id="stealth.create",
                mutation_family=AdminApiMutationFamilyType.STEALTH_CREATE,
                workflow_id="stealth.create_command_draft",
                module="Stealth Orders",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth create is a local lifecycle-write draft keyed by "
                    "stealth_order_id; the current Admin API route is fail-closed "
                    "and does not create hidden local state."
                ),
                identity_keys=["stealth_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::create_stealth_order",
                    "application/admin_api/command_service.py::create_stealth_order",
                    "application/admin_api/stealth_lifecycle_execution.py::build_stealth_create_lifecycle_write_execution_contract",
                    "core/stealth_order_manager.py::create_stealth_order",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::createStealthOrder",
                ],
                documentation_refs=[
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/agents/AGENT_STEALTH_LIFECYCLE.md",
                ],
                required_next_contract=(
                    "Lifecycle-write execution contract that proves exact "
                    "command context, planning guards, approval, cap/guard, "
                    "audit, reconciliation, live adapter, and post-write "
                    "recovery handling before invoking StealthOrderManager."
                ),
                blockers=[
                    "stealth_create_lifecycle_write_guard_proof_missing",
                    "stealth_create_lifecycle_write_execution_contract_missing",
                    "reconciliation_plan_missing",
                    "stealth_manager_invocation_disabled",
                ],
                frontend_boundary=(
                    "Do not create stealth orders or local lifecycle state from "
                    "browser code."
                ),
                spot_rule_boundary=(
                    "Stealth create is lifecycle authority; spot wallet rules are "
                    "backend guard evidence only."
                ),
            ),
            mutation_taxonomy_from_surface(
                surface=(
                    "POST /api/v1/stealth/orders/{stealth_order_id}/"
                    "lifecycle-write-guard-proofs"
                ),
                mutation_id="stealth.create_lifecycle_write_guard_proof",
                mutation_family=(
                    AdminApiMutationFamilyType
                    .STEALTH_CREATE_LIFECYCLE_WRITE_GUARD_PROOF
                ),
                workflow_id="stealth.create_lifecycle_write_guard_proof",
                module="Stealth Orders",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth create lifecycle-write guard proof recording is "
                    "append-only local evidence keyed by stealth_order_id; it "
                    "proves the create path is still no-live and no-write before "
                    "the execution contract exists."
                ),
                identity_keys=["stealth_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::record_stealth_create_lifecycle_write_guard_proof",
                    "application/admin_api/command_service.py::record_stealth_create_lifecycle_write_guard_proof",
                    "application/admin_api/stealth_lifecycle_write_service.py",
                    "application/admin_api/stealth_lifecycle_write.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::recordStealthCreateLifecycleWriteGuardProof",
                    "src/shared/api/contracts/commandDrySubmit.ts::drySubmitStealthLifecycleWriteGuardProof",
                    "src/features/stealth-orders/StealthOrdersReadModel.tsx",
                ],
                documentation_refs=[
                    "README.admin-api.md",
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/STEALTH_ORDER_READS.md",
                    "docs/examples/stealth-command-suite.md",
                ],
                required_next_contract=(
                    "Future create execution must prove lifecycle-write guard, "
                    "approval, admission audit, cap/guard, reconciliation, and "
                    "post-write recovery handling before invoking the stealth "
                    "manager or mutating lifecycle state."
                ),
                blockers=[
                    "live_execution_disabled",
                    "stealth_manager_invocation_disabled",
                    "stealth_create_lifecycle_write_execution_contract_missing",
                ],
                frontend_boundary=(
                    "Do not treat a browser-submitted proof record as stealth "
                    "create authority; it is display and backend-forwarded "
                    "evidence only."
                ),
                spot_rule_boundary=(
                    "Spot wallet and no-shorting rules remain backend guard "
                    "evidence; this proof record is not spot inventory or sell "
                    "authority."
                ),
                live_adapter_required=False,
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/stealth/orders/{stealth_order_id}/cancel",
                mutation_id="stealth.cancel",
                mutation_family=AdminApiMutationFamilyType.STEALTH_CANCEL,
                workflow_id="stealth.cancel_command_draft",
                module="Stealth Orders",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth cancel is keyed by stealth_order_id and must preserve "
                    "active placement/exchange-reality invariants."
                ),
                identity_keys=["stealth_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::cancel_stealth_order_by_stealth_order_id",
                    "application/admin_api/command_service.py::cancel_stealth_order_by_stealth_order_id",
                    "core/stealth_order_manager.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::cancelStealthOrderByStealthOrderId",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                documentation_refs=[
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/agents/AGENT_STEALTH_LIFECYCLE.md",
                ],
                required_next_contract=(
                    "Exchange cancel/reconcile path must prove active placement "
                    "handling before local stealth state changes."
                ),
                blockers=[
                    "live_execution_disabled",
                    "exchange reality proof missing",
                    "active placement reconciliation missing",
                ],
                frontend_boundary=(
                    "Do not cancel by exchange order id or mutate active placement "
                    "state from the browser."
                ),
                spot_rule_boundary=(
                    "Stealth authority is lifecycle/exchange-reality based; spot "
                    "wallet rules apply only through backend guards for spot products."
                ),
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/stealth/orders/{stealth_order_id}/reveal",
                mutation_id="stealth.reveal",
                mutation_family=AdminApiMutationFamilyType.STEALTH_REVEAL,
                workflow_id="stealth.reveal_command_draft",
                module="Stealth Orders",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth reveal is an exchange-placement-shaped draft keyed "
                    "by stealth_order_id; the current Admin API route is fail-closed "
                    "and does not call reveal_order_slice, Coinbase, or local "
                    "lifecycle mutation paths."
                ),
                identity_keys=["stealth_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::reveal_stealth_order_by_stealth_order_id",
                    "application/admin_api/command_service.py::reveal_stealth_order_by_stealth_order_id",
                    "core/stealth_order_manager.py::reveal_order_slice",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::revealStealthOrderByStealthOrderId",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                documentation_refs=[
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/agents/AGENT_STEALTH_LIFECYCLE.md",
                ],
                required_next_contract=(
                    "Reveal execution must prove trigger evidence, active placement "
                    "audit, approval, cap/guard, Coinbase placement handling, and "
                    "post-live reconciliation before invoking the lifecycle manager."
                ),
                blockers=[
                    "live_execution_disabled",
                    "trigger_evidence_missing",
                    "stealth_reveal_exchange_submission_adapter_missing",
                    "active placement reconciliation missing",
                ],
                frontend_boundary=(
                    "Do not reveal, place exchange orders, or mutate stealth "
                    "lifecycle state from the browser."
                ),
                spot_rule_boundary=(
                    "Stealth reveal remains lifecycle/exchange-placement authority; "
                    "spot wallet rules apply only through backend guards for spot products."
                ),
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/stealth/orders/{stealth_order_id}/move",
                mutation_id="stealth.move",
                mutation_family=AdminApiMutationFamilyType.STEALTH_MOVE,
                workflow_id="stealth.move_command_draft",
                module="Stealth Orders",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth move is a cancel/replace-shaped draft keyed by "
                    "stealth_order_id; the current Admin API route is fail-closed "
                    "and does not build a move plan, execute a cancel/replace, "
                    "or mutate local lifecycle state."
                ),
                identity_keys=["stealth_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::move_stealth_order_by_stealth_order_id",
                    "application/admin_api/command_service.py::move_stealth_order_by_stealth_order_id",
                    "core/stealth_order_manager.py::build_stealth_move_plan",
                    "core/stealth_order_manager.py::execute_stealth_move",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::moveStealthOrderByStealthOrderId",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                documentation_refs=[
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/agents/AGENT_STEALTH_LIFECYCLE.md",
                ],
                required_next_contract=(
                    "Move execution must prove mutation claim ownership, active "
                    "placement cancel/replace handling, approval, cap/guard, "
                    "audit, and post-live reconciliation before invoking the "
                    "lifecycle manager."
                ),
                blockers=[
                    "live_execution_disabled",
                    "mutation_claim_proof_missing",
                    "stealth_move_cancel_replace_adapter_missing",
                    "active placement reconciliation missing",
                ],
                frontend_boundary=(
                    "Do not move revealed stealth placements, resolve active "
                    "placement ids, or mutate stealth lifecycle state from the browser."
                ),
                spot_rule_boundary=(
                    "Stealth move remains lifecycle/exchange cancel-replace "
                    "authority; spot wallet rules apply only through backend guards "
                    "for spot products."
                ),
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/stealth/orders/{stealth_order_id}/recovery",
                mutation_id="stealth.recovery",
                mutation_family=AdminApiMutationFamilyType.STEALTH_RECOVERY,
                workflow_id="stealth.recovery_command_draft",
                module="Stealth Orders",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth recovery is a route-bound local-state recovery "
                    "draft keyed by stealth_order_id; it does not run repair, "
                    "rollback, Coinbase read, lifecycle mutation, or reconciliation."
                ),
                identity_keys=["stealth_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::recover_stealth_order_by_stealth_order_id",
                    "application/admin_api/command_service.py::recover_stealth_order_by_stealth_order_id",
                    "core/stealth_order_manager.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::recoverStealthOrderByStealthOrderId",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                documentation_refs=[
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/agents/AGENT_STEALTH_LIFECYCLE.md",
                ],
                required_next_contract=(
                    "Recovery execution must prove active-placement exchange "
                    "truth, repair/rollback proof, approval, cap/guard, audit, "
                    "and reconciliation before any local recovery state changes."
                ),
                blockers=[
                    "live_execution_disabled",
                    "stealth_recovery_preview_contract_missing",
                    "stealth_recovery_repair_result_contract_missing",
                    "stealth_recovery_rollback_contract_missing",
                    "active placement reconciliation missing",
                ],
                frontend_boundary=(
                    "Do not repair, rollback, read Coinbase, or mutate stealth "
                    "lifecycle state from the browser."
                ),
                spot_rule_boundary=(
                    "Spot recovery permissions and repair contracts do not "
                    "generalize to stealth recovery."
                ),
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/stealth/orders/{stealth_order_id}/reconciliation",
                mutation_id="stealth.reconciliation",
                mutation_family=AdminApiMutationFamilyType.STEALTH_RECONCILIATION,
                workflow_id="stealth.reconciliation_command_draft",
                module="Stealth Orders",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth reconciliation is a route-bound reconciliation "
                    "draft keyed by stealth_order_id; it does not execute "
                    "reconciliation, create proof authority, read Coinbase, or "
                    "mutate local/exchange state."
                ),
                identity_keys=["stealth_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::reconcile_stealth_order_by_stealth_order_id",
                    "application/admin_api/command_service.py::reconcile_stealth_order_by_stealth_order_id",
                    "application/admin_api/reconciliation.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::reconcileStealthOrderByStealthOrderId",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                documentation_refs=[
                    "docs/COMMAND_WORKFLOWS.md",
                    "README.reconciliation-plans.md",
                ],
                required_next_contract=(
                    "Reconciliation execution must prove route-bound plan/proof "
                    "evidence, active-placement exchange truth, approval, "
                    "cap/guard, audit, lifecycle repair policy, and post-execution "
                    "proof before any state transition can be recorded."
                ),
                blockers=[
                    "live_execution_disabled",
                    "stealth_reconciliation_plan_contract_missing",
                    "stealth_exchange_evidence_snapshot_contract_missing",
                    "stealth_reconciliation_executor_missing",
                    "active placement reconciliation missing",
                ],
                frontend_boundary=(
                    "Do not execute reconciliation, create proof records, read "
                    "Coinbase, or mutate local/exchange state from the browser."
                ),
                spot_rule_boundary=(
                    "Spot reconciliation records are not stealth reconciliation "
                    "authority; stealth exchange-reality policy remains separate."
                ),
            ),
            mutation_taxonomy_from_surface(
                surface=(
                    "POST /api/v1/stealth/orders/{stealth_order_id}/"
                    "active-placement/exchange-truth-snapshots"
                ),
                mutation_id="stealth.exchange_truth_snapshot",
                mutation_family=(
                    AdminApiMutationFamilyType
                    .STEALTH_ACTIVE_PLACEMENT_EXCHANGE_TRUTH_SNAPSHOT
                ),
                workflow_id="stealth.exchange_truth_snapshot_command_draft",
                module="Stealth Orders",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth active-placement exchange-truth snapshot recording "
                    "is append-only local evidence keyed by stealth_order_id; it "
                    "does not read Coinbase, verify exchange truth, cancel/replace "
                    "placements, execute reconciliation, or mutate lifecycle state."
                ),
                identity_keys=["stealth_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::record_stealth_active_placement_exchange_truth_snapshot",
                    "application/admin_api/command_service.py::record_stealth_active_placement_exchange_truth_snapshot",
                    "application/admin_api/stealth_exchange_truth_service.py",
                    "application/admin_api/stealth_exchange_truth.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::recordStealthActivePlacementExchangeTruthSnapshot",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                documentation_refs=[
                    "README.stealth-exchange-truth-proofs.md",
                    "docs/examples/stealth-exchange-truth-proofs.md",
                ],
                required_next_contract=(
                    "Future exchange-truth verification must be owned by backend "
                    "Coinbase read/reconciliation paths; this route records "
                    "evidence only and keeps exchange_truth_verified=false."
                ),
                blockers=[
                    "live_execution_disabled",
                    "coinbase_read_disabled",
                    "exchange_truth_verified_false",
                    "active placement reconciliation missing",
                ],
                frontend_boundary=(
                    "Do not treat browser-supplied active placement or exchange "
                    "ids as truth, cancel authority, reconciliation authority, or "
                    "lifecycle mutation input."
                ),
                spot_rule_boundary=(
                    "Spot wallet and inventory rules remain backend guard evidence; "
                    "snapshot recording is not sell authority or exchange truth."
                ),
            ),
            mutation_taxonomy_from_surface(
                surface=(
                    "POST /api/v1/stealth/orders/{stealth_order_id}/"
                    "active-placement/exchange-truth-proofs"
                ),
                mutation_id="stealth.exchange_truth_proof",
                mutation_family=(
                    AdminApiMutationFamilyType
                    .STEALTH_ACTIVE_PLACEMENT_EXCHANGE_TRUTH_PROOF
                ),
                workflow_id="stealth.exchange_truth_proof_command_draft",
                module="Stealth Orders",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth active-placement exchange-truth proof recording is "
                    "append-only local evidence linked to a prior snapshot and "
                    "keyed by stealth_order_id; it does not itself verify Coinbase "
                    "truth or authorize cancel/replace/reconciliation."
                ),
                identity_keys=["stealth_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::record_stealth_active_placement_exchange_truth_proof",
                    "application/admin_api/command_service.py::record_stealth_active_placement_exchange_truth_proof",
                    "application/admin_api/stealth_exchange_truth_service.py",
                    "application/admin_api/stealth_exchange_truth.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::recordStealthActivePlacementExchangeTruthProof",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                documentation_refs=[
                    "README.stealth-exchange-truth-proofs.md",
                    "docs/examples/stealth-exchange-truth-proofs.md",
                ],
                required_next_contract=(
                    "Future verified active-placement exchange truth must come "
                    "from backend Coinbase/reconciliation evidence, not from this "
                    "local proof-record route alone."
                ),
                blockers=[
                    "live_execution_disabled",
                    "coinbase_read_disabled",
                    "exchange_truth_verified_false",
                    "active placement reconciliation missing",
                ],
                frontend_boundary=(
                    "Do not use browser proof records as active-placement truth, "
                    "cancel authority, reconciliation authority, or lifecycle "
                    "mutation input."
                ),
                spot_rule_boundary=(
                    "Spot wallet and inventory rules remain backend guard evidence; "
                    "proof recording is not sell authority or exchange truth."
                ),
            ),
            mutation_taxonomy_from_surface(
                surface=(
                    "POST /api/v1/stealth/orders/{stealth_order_id}/"
                    "mutation-claim-proofs"
                ),
                mutation_id="stealth.mutation_claim_snapshot_proof",
                mutation_family=(
                    AdminApiMutationFamilyType.STEALTH_MUTATION_CLAIM_SNAPSHOT_PROOF
                ),
                workflow_id="stealth.mutation_claim_snapshot_proof_command_draft",
                module="Stealth Orders",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth mutation-claim snapshot proof recording is append-only "
                    "local evidence keyed by stealth_order_id and guarded command "
                    "context; it does not acquire/release claims, clear cooldowns, "
                    "cancel/replace placements, call Coinbase, execute "
                    "reconciliation, or mutate lifecycle state."
                ),
                identity_keys=["stealth_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::record_stealth_mutation_claim_snapshot_proof",
                    "application/admin_api/command_service.py::record_stealth_mutation_claim_snapshot_proof",
                    "application/admin_api/stealth_mutation_claim_service.py",
                    "application/admin_api/stealth_mutation_claim.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::recordStealthMutationClaimSnapshotProof",
                    "src/features/stealth-orders/StealthOrdersReadModel.tsx",
                ],
                documentation_refs=[
                    "README.admin-api.md",
                    "docs/examples/stealth-command-suite.md",
                ],
                required_next_contract=(
                    "Future executable move/reprice paths must continue to prove "
                    "claim ownership, claim release, cooldown, exchange "
                    "cancel/replace, approval, cap, audit, and reconciliation "
                    "through backend-owned contracts; this proof route is local "
                    "admission evidence only."
                ),
                blockers=[
                    "live_execution_disabled",
                    "claim_acquire_disabled",
                    "claim_release_disabled",
                    "cooldown_clearance_disabled",
                    "cancel/replace reconciliation missing",
                ],
                frontend_boundary=(
                    "Do not use browser proof records as claim ownership, claim "
                    "release proof, cooldown clearance, manager authority, "
                    "cancel/replace authority, reconciliation authority, or "
                    "lifecycle mutation input."
                ),
                spot_rule_boundary=(
                    "Spot wallet and inventory rules remain backend guard evidence; "
                    "mutation-claim proof recording is not sell authority or "
                    "exchange truth."
                ),
            ),
            mutation_taxonomy_from_surface(
                surface=(
                    "POST /api/v1/stealth/orders/{stealth_order_id}/"
                    "manager-invocation-policy-proofs"
                ),
                mutation_id="stealth.manager_invocation_policy_proof",
                mutation_family=(
                    AdminApiMutationFamilyType.STEALTH_MANAGER_INVOCATION_POLICY_PROOF
                ),
                workflow_id="stealth.manager_invocation_policy_proof_command_draft",
                module="Stealth Orders",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth manager-invocation policy proof recording is "
                    "append-only local evidence keyed by stealth_order_id and "
                    "guarded command context; it does not invoke managers, call "
                    "Coinbase, cancel or replace placements, execute "
                    "reconciliation, or mutate lifecycle state."
                ),
                identity_keys=["stealth_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::record_stealth_manager_invocation_policy_proof",
                    "application/admin_api/command_service.py::record_stealth_manager_invocation_policy_proof",
                    "application/admin_api/stealth_manager_policy_service.py",
                    "application/admin_api/stealth_manager_policy.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::recordStealthManagerInvocationPolicyProof",
                    "src/features/stealth-orders/StealthOrdersReadModel.tsx",
                ],
                documentation_refs=[
                    "README.admin-api.md",
                    "docs/examples/stealth-command-suite.md",
                ],
                required_next_contract=(
                    "Future executable stealth command paths must prove backend "
                    "manager-invocation policy, actual manager execution where "
                    "allowed, approval, cap, audit, and reconciliation through "
                    "backend-owned contracts; this proof route is local "
                    "admission evidence only."
                ),
                blockers=[
                    "live_execution_disabled",
                    "manager_invocation_disabled",
                    "coinbase_execution_disabled",
                    "cancel_replace_execution_disabled",
                    "reconciliation_execution_disabled",
                ],
                live_adapter_required=False,
                frontend_boundary=(
                    "Do not use browser proof records as manager invocation "
                    "authority, Coinbase authority, cancel/replace authority, "
                    "reconciliation authority, or lifecycle mutation input."
                ),
                route_local_boundary=(
                    "FastAPI route adapters must bind auth, RBAC, "
                    "idempotency, audit, approval, cap/guard, reconciliation "
                    "evidence, and guarded command context; they must not "
                    "invoke managers, call Coinbase, cancel or replace "
                    "placements, execute reconciliation, or mutate lifecycle "
                    "state."
                ),
                spot_rule_boundary=(
                    "Spot wallet and inventory rules remain backend guard "
                    "evidence; manager-invocation policy proof recording is "
                    "not sell authority or exchange truth."
                ),
            ),
            mutation_taxonomy_from_surface(
                surface=(
                    "POST /api/v1/stealth/orders/{stealth_order_id}/"
                    "coinbase-exchange-submission-policy-proofs"
                ),
                mutation_id="stealth.coinbase_exchange_submission_policy_proof",
                mutation_family=(
                    AdminApiMutationFamilyType.STEALTH_COINBASE_EXCHANGE_SUBMISSION_POLICY_PROOF
                ),
                workflow_id=(
                    "stealth.coinbase_exchange_submission_policy_proof_command_draft"
                ),
                module="Stealth Orders",
                exposure_status=(
                    AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED
                ),
                support_status=(
                    AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED
                ),
                summary=(
                    "Stealth Coinbase exchange submission-policy proof "
                    "recording is append-only local evidence keyed by "
                    "stealth_order_id and guarded command context; it does "
                    "not submit, cancel, or read Coinbase orders, invoke "
                    "managers, execute reconciliation, or mutate lifecycle "
                    "state."
                ),
                identity_keys=["stealth_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::record_stealth_coinbase_exchange_submission_policy_proof",
                    "application/admin_api/command_service.py::record_stealth_coinbase_exchange_submission_policy_proof",
                    "application/admin_api/stealth_coinbase_exchange_policy_service.py",
                    "application/admin_api/stealth_coinbase_exchange_policy.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::recordStealthCoinbaseExchangeSubmissionPolicyProof",
                    "src/features/stealth-orders/StealthOrdersReadModel.tsx",
                ],
                documentation_refs=[
                    "README.admin-api.md",
                    "docs/examples/stealth-command-suite.md",
                ],
                required_next_contract=(
                    "Future executable stealth command paths must prove "
                    "Coinbase submit/cancel/read policy, live-cap evidence, "
                    "approval, cap, audit, and reconciliation through "
                    "backend-owned contracts; this proof route is local "
                    "admission evidence only."
                ),
                blockers=[
                    "live_execution_disabled",
                    "coinbase_submit_disabled",
                    "coinbase_cancel_disabled",
                    "coinbase_read_disabled",
                    "reconciliation_execution_disabled",
                ],
                live_adapter_required=False,
                frontend_boundary=(
                    "Do not use browser proof records as Coinbase submit, "
                    "cancel, read, manager, reconciliation, or lifecycle "
                    "mutation authority."
                ),
                route_local_boundary=(
                    "FastAPI route adapters must bind auth, RBAC, "
                    "idempotency, audit, approval, cap/guard, reconciliation "
                    "evidence, and guarded command context; they must not "
                    "call Coinbase, invoke managers, cancel or replace "
                    "placements, execute reconciliation, or mutate lifecycle "
                    "state."
                ),
                spot_rule_boundary=(
                    "Spot wallet and inventory rules remain backend guard "
                    "evidence; Coinbase exchange policy proof recording is "
                    "not sell authority, exchange truth, or live execution."
                ),
            ),
            mutation_taxonomy_from_surface(
                surface=(
                    "POST /api/v1/stealth/orders/{stealth_order_id}/"
                    "state-mutation-policy-proofs"
                ),
                mutation_id="stealth.state_mutation_policy_proof",
                mutation_family=(
                    AdminApiMutationFamilyType.STEALTH_STATE_MUTATION_POLICY_PROOF
                ),
                workflow_id="stealth.state_mutation_policy_proof_command_draft",
                module="Stealth Orders",
                exposure_status=(
                    AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED
                ),
                support_status=(
                    AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED
                ),
                summary=(
                    "Stealth state-mutation policy proof recording is append-only "
                    "local evidence keyed by stealth_order_id and guarded command "
                    "context; it does not authorize or perform lifecycle, order, "
                    "or exchange-state mutation, call Coinbase, invoke managers, "
                    "cancel or replace placements, or execute reconciliation."
                ),
                identity_keys=["stealth_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::record_stealth_state_mutation_policy_proof",
                    "application/admin_api/command_service.py::record_stealth_state_mutation_policy_proof",
                    "application/admin_api/stealth_state_mutation_policy_service.py",
                    "application/admin_api/stealth_state_mutation_policy.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::recordStealthStateMutationPolicyProof",
                    "src/features/stealth-orders/StealthOrdersReadModel.tsx",
                ],
                documentation_refs=[
                    "README.stealth-state-mutation-policy.md",
                    "docs/examples/stealth-state-mutation-policy.md",
                ],
                required_next_contract=(
                    "Future executable stealth command paths must prove a "
                    "backend-owned exact-command resolver for this policy before "
                    "lifecycle, order, or exchange-state mutation can be "
                    "considered. This proof route is local admission evidence "
                    "only."
                ),
                blockers=[
                    "live_execution_disabled",
                    "state_mutation_policy_unverified",
                    "lifecycle_state_mutation_disabled",
                    "order_state_mutation_disabled",
                    "exchange_state_mutation_disabled",
                ],
                live_adapter_required=False,
                frontend_boundary=(
                    "Do not use browser proof records as state-mutation, "
                    "manager, Coinbase, cancel/replace, or reconciliation "
                    "execution authority."
                ),
                route_local_boundary=(
                    "FastAPI route adapters must bind auth, RBAC, idempotency, "
                    "audit, approval, cap/guard, reconciliation evidence, and "
                    "guarded command context; they must not mutate lifecycle, "
                    "order, or exchange state, call Coinbase, invoke managers, "
                    "cancel or replace placements, or execute reconciliation."
                ),
                spot_rule_boundary=(
                    "Spot wallet and inventory rules remain backend guard "
                    "evidence; state-mutation policy proof recording is not "
                    "sell authority, exchange truth, or live execution."
                ),
            ),
            mutation_taxonomy_from_surface(
                surface=(
                    "POST /api/v1/stealth/orders/{stealth_order_id}/"
                    "post-write-reconciliation-execution-policy-proofs"
                ),
                mutation_id=(
                    "stealth.post_write_reconciliation_execution_policy_proof"
                ),
                mutation_family=(
                    AdminApiMutationFamilyType.STEALTH_POST_WRITE_RECONCILIATION_EXECUTION_POLICY_PROOF
                ),
                workflow_id=(
                    "stealth.post_write_reconciliation_execution_policy_proof_command_draft"
                ),
                module="Stealth Orders",
                exposure_status=(
                    AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED
                ),
                support_status=(
                    AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED
                ),
                summary=(
                    "Stealth post-write reconciliation execution-policy proof "
                    "recording is append-only local evidence keyed by "
                    "stealth_order_id and guarded command context; it does not "
                    "execute reconciliation, call Coinbase, invoke managers, "
                    "cancel or replace placements, or mutate lifecycle state."
                ),
                identity_keys=["stealth_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::record_stealth_post_write_reconciliation_execution_policy_proof",
                    "application/admin_api/command_service.py::record_stealth_post_write_reconciliation_execution_policy_proof",
                    "application/admin_api/stealth_post_write_reconciliation_policy_service.py",
                    "application/admin_api/stealth_post_write_reconciliation_policy.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::recordStealthPostWriteReconciliationExecutionPolicyProof",
                    "src/features/stealth-orders/StealthOrdersReadModel.tsx",
                ],
                documentation_refs=[
                    "README.admin-api.md",
                    "README.stealth-post-write-reconciliation-execution-policy.md",
                    "docs/examples/stealth-post-write-reconciliation-execution-policy.md",
                ],
                required_next_contract=(
                    "Future executable stealth command paths must prove the "
                    "state-mutation policy and live adapter/service decisions "
                    "after this route-bound policy record; this proof route is "
                    "local admission evidence only."
                ),
                blockers=[
                    "live_execution_disabled",
                    "reconciliation_execution_disabled",
                    "safe_reconciliation_chain_unverified",
                    "state_mutation_policy_missing",
                ],
                live_adapter_required=False,
                frontend_boundary=(
                    "Do not use browser proof records as reconciliation "
                    "execution, manager, Coinbase, cancel/replace, or "
                    "lifecycle mutation authority."
                ),
                route_local_boundary=(
                    "FastAPI route adapters must bind auth, RBAC, idempotency, "
                    "audit, approval, cap/guard, reconciliation evidence, and "
                    "guarded command context; they must not execute "
                    "reconciliation, call Coinbase, invoke managers, cancel or "
                    "replace placements, or mutate lifecycle state."
                ),
                spot_rule_boundary=(
                    "Spot wallet and inventory rules remain backend guard "
                    "evidence; post-write reconciliation policy proof "
                    "recording is not sell authority, exchange truth, or live "
                    "execution."
                ),
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/stealth/orders/{stealth_order_id}/recovery-proofs",
                mutation_id="stealth.recovery_proof",
                mutation_family=AdminApiMutationFamilyType.STEALTH_RECOVERY_PROOF,
                workflow_id="stealth.recovery_proof_command_draft",
                module="Stealth Orders",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth recovery proof recording is append-only local "
                    "evidence keyed by stealth_order_id and guarded command "
                    "context; it does not repair state, roll back state, call "
                    "Coinbase, execute reconciliation, or mutate lifecycle state."
                ),
                identity_keys=["stealth_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::record_stealth_recovery_proof",
                    "application/admin_api/command_service.py::record_stealth_recovery_proof",
                    "application/admin_api/stealth_recovery_proof_service.py",
                    "application/admin_api/stealth_recovery_proof.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::recordStealthRecoveryProof",
                    "src/features/stealth-orders/StealthOrdersReadModel.tsx",
                ],
                documentation_refs=[
                    "README.admin-api.md",
                    "docs/examples/stealth-command-suite.md",
                ],
                required_next_contract=(
                    "Future executable recovery paths must prove backend "
                    "repair/rollback plans, exchange handling, approval, cap, "
                    "audit, and reconciliation through backend-owned contracts; "
                    "this proof route is local admission evidence only."
                ),
                blockers=[
                    "live_execution_disabled",
                    "repair_execution_disabled",
                    "rollback_execution_disabled",
                    "reconciliation_execution_disabled",
                    "post-recovery reconciliation missing",
                ],
                frontend_boundary=(
                    "Do not use browser proof records as recovery authority, "
                    "repair authority, rollback authority, reconciliation "
                    "authority, manager authority, or lifecycle mutation input."
                ),
                spot_rule_boundary=(
                    "Spot wallet and inventory rules remain backend guard "
                    "evidence; recovery proof recording is not sell authority "
                    "or exchange truth."
                ),
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/stealth/orders/{stealth_order_id}/reveal-trigger-proofs",
                mutation_id="stealth.reveal_trigger_proof",
                mutation_family=AdminApiMutationFamilyType.STEALTH_REVEAL_TRIGGER_PROOF,
                workflow_id="stealth.reveal_trigger_proof_command_draft",
                module="Stealth Orders",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth reveal-trigger proof recording is append-only "
                    "local evidence keyed by stealth_order_id and guarded "
                    "reveal command context; it does not evaluate triggers, "
                    "call should_trigger_reveal, call reveal_order_slice, "
                    "invoke managers, call Coinbase, execute reconciliation, "
                    "or mutate lifecycle state."
                ),
                identity_keys=["stealth_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::record_stealth_reveal_trigger_proof",
                    "application/admin_api/command_service.py::record_stealth_reveal_trigger_proof",
                    "application/admin_api/stealth_reveal_trigger_proof_service.py",
                    "application/admin_api/stealth_reveal_trigger_proof.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::recordStealthRevealTriggerProof",
                    "src/features/stealth-orders/StealthOrdersReadModel.tsx",
                ],
                documentation_refs=[
                    "README.admin-api.md",
                    "docs/examples/stealth-command-suite.md",
                ],
                required_next_contract=(
                    "Future executable reveal paths must prove backend trigger "
                    "evaluation, exchange submission handling, approval, cap, "
                    "audit, and reconciliation through backend-owned contracts; "
                    "this proof route is local admission evidence only."
                ),
                blockers=[
                    "live_execution_disabled",
                    "trigger_evaluation_disabled",
                    "reveal_order_slice_disabled",
                    "exchange_submission_disabled",
                    "post-reveal reconciliation missing",
                ],
                frontend_boundary=(
                    "Do not use browser proof records as trigger authority, "
                    "reveal authority, exchange submission authority, "
                    "manager authority, reconciliation authority, or lifecycle "
                    "mutation input."
                ),
                spot_rule_boundary=(
                    "Spot wallet and inventory rules remain backend guard "
                    "evidence; reveal-trigger proof recording is not sell "
                    "authority or exchange truth."
                ),
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/stealth/orders/{stealth_order_id}/reconciliation-proofs",
                mutation_id="stealth.reconciliation_proof",
                mutation_family=AdminApiMutationFamilyType.STEALTH_RECONCILIATION_PROOF,
                workflow_id="stealth.reconciliation_proof_command_draft",
                module="Stealth Orders",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth reconciliation proof recording is append-only "
                    "local evidence keyed by stealth_order_id and guarded "
                    "reconciliation command context; it does not execute "
                    "reconciliation, invoke managers, call Coinbase, cancel "
                    "or replace placements, mutate exchange state, or mutate "
                    "lifecycle state."
                ),
                identity_keys=["stealth_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::record_stealth_reconciliation_proof",
                    "application/admin_api/command_service.py::record_stealth_reconciliation_proof",
                    "application/admin_api/stealth_reconciliation_proof_service.py",
                    "application/admin_api/stealth_reconciliation_proof.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::recordStealthReconciliationProof",
                    "src/features/stealth-orders/StealthOrdersReadModel.tsx",
                ],
                documentation_refs=[
                    "README.admin-api.md",
                    "docs/examples/stealth-command-suite.md",
                ],
                required_next_contract=(
                    "Future executable reconciliation paths must prove backend "
                    "active-placement truth, reconciliation execution safety, "
                    "approval, cap, audit, and post-write reconciliation "
                    "through backend-owned contracts; this proof route is "
                    "local admission evidence only."
                ),
                blockers=[
                    "live_execution_disabled",
                    "reconciliation_execution_disabled",
                    "manager_invocation_disabled",
                    "active_placement_cancel_replace_disabled",
                    "post-reconciliation completion proof missing",
                ],
                frontend_boundary=(
                    "Do not use browser proof records as reconciliation "
                    "execution authority, manager authority, active-placement "
                    "cancel/replace authority, Coinbase authority, or "
                    "lifecycle mutation input."
                ),
                spot_rule_boundary=(
                    "Spot wallet and inventory rules remain backend guard "
                    "evidence; stealth reconciliation proof recording is not "
                    "sell authority or exchange truth."
                ),
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proofs",
                mutation_id="stealth.cancel_replace_proof",
                mutation_family=AdminApiMutationFamilyType.STEALTH_CANCEL_REPLACE_PROOF,
                workflow_id="stealth.cancel_replace_proof_command_draft",
                module="Stealth Orders",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth cancel/replace proof recording is append-only "
                    "local evidence keyed by stealth_order_id and guarded "
                    "cancel, move, or movement-reprice command context; it "
                    "does not invoke managers, call Coinbase, cancel or replace "
                    "placements, mutate exchange state, or mutate lifecycle state."
                ),
                identity_keys=["stealth_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::record_stealth_cancel_replace_proof",
                    "application/admin_api/command_service.py::record_stealth_cancel_replace_proof",
                    "application/admin_api/stealth_cancel_replace_proof_service.py",
                    "application/admin_api/stealth_cancel_replace_proof.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::recordStealthCancelReplaceProof",
                    "src/features/stealth-orders/StealthOrdersReadModel.tsx",
                ],
                documentation_refs=[
                    "README.admin-api.md",
                    "README.stealth-command-suite.md",
                    "docs/examples/stealth-command-suite.md",
                ],
                required_next_contract=(
                    "Future executable cancel/replace paths must prove "
                    "backend active-placement truth, mutation-claim authority "
                    "where required, actual cancel/replace completion, approval, "
                    "cap, audit, and post-write reconciliation through "
                    "backend-owned contracts; this proof route is local "
                    "admission evidence only."
                ),
                blockers=[
                    "live_execution_disabled",
                    "manager_invocation_disabled",
                    "active_placement_cancel_replace_disabled",
                    "coinbase_cancel_disabled",
                    "coinbase_submit_disabled",
                    "post-write reconciliation proof missing",
                ],
                frontend_boundary=(
                    "Do not use browser proof records as cancel authority, "
                    "replace authority, manager authority, active-placement "
                    "truth, Coinbase authority, or lifecycle mutation input."
                ),
                spot_rule_boundary=(
                    "Spot wallet and inventory rules remain backend guard "
                    "evidence; stealth cancel/replace proof recording is not "
                    "sell authority or exchange truth."
                ),
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-proofs",
                mutation_id="stealth.post_write_reconciliation_proof",
                mutation_family=AdminApiMutationFamilyType.STEALTH_POST_WRITE_RECONCILIATION_PROOF,
                workflow_id="stealth.post_write_reconciliation_proof_command_draft",
                module="Stealth Orders",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth post-write reconciliation proof recording is "
                    "append-only local evidence keyed by stealth_order_id and "
                    "guarded command context; it does not accept execution "
                    "journals as complete, execute reconciliation, invoke "
                    "managers, call Coinbase, cancel or replace placements, "
                    "mutate exchange state, or mutate lifecycle state."
                ),
                identity_keys=["stealth_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::record_stealth_post_write_reconciliation_proof",
                    "application/admin_api/command_service.py::record_stealth_post_write_reconciliation_proof",
                    "application/admin_api/stealth_post_write_reconciliation_service.py",
                    "application/admin_api/stealth_post_write_reconciliation.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::recordStealthPostWriteReconciliationProof",
                    "src/features/stealth-orders/StealthOrdersReadModel.tsx",
                ],
                documentation_refs=[
                    "README.admin-api.md",
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/STEALTH_ORDER_READS.md",
                    "docs/examples/stealth-command-suite.md",
                ],
                required_next_contract=(
                    "Future executable stealth command paths must prove "
                    "backend post-write reconciliation completion through "
                    "resolver, execution, and completion-verifier contracts; "
                    "this proof route is local admission evidence only."
                ),
                blockers=[
                    "live_execution_disabled",
                    "execution_journal_not_accepted",
                    "reconciliation_execution_disabled",
                    "completion_verifier_missing",
                    "post-write reconciliation prerequisite unsatisfied",
                ],
                frontend_boundary=(
                    "Do not use browser proof records as post-write "
                    "completion proof, reconciliation execution authority, "
                    "manager authority, active-placement cancel/replace "
                    "authority, Coinbase authority, or lifecycle mutation input."
                ),
                spot_rule_boundary=(
                    "Spot wallet and inventory rules remain backend guard "
                    "evidence; stealth post-write reconciliation proof "
                    "recording is not sell authority or exchange truth."
                ),
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/stealth/orders/{stealth_order_id}/post-write-execution-journals",
                mutation_id="stealth.post_write_execution_journal",
                mutation_family=AdminApiMutationFamilyType.STEALTH_POST_WRITE_EXECUTION_JOURNAL,
                workflow_id="stealth.post_write_execution_journal_command_draft",
                module="Stealth Orders",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth post-write execution-journal acceptance is "
                    "append-only local evidence keyed by stealth_order_id, "
                    "safe post-write proof id, and guarded command context; "
                    "it does not verify reconciliation, execute "
                    "reconciliation, invoke managers, call Coinbase, cancel "
                    "or replace placements, mutate exchange state, or mutate "
                    "lifecycle state."
                ),
                identity_keys=["stealth_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::record_stealth_post_write_execution_journal",
                    "application/admin_api/command_service.py::record_stealth_post_write_execution_journal",
                    "application/admin_api/stealth_post_write_reconciliation_service.py",
                    "application/admin_api/stealth_post_write_reconciliation.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::recordStealthPostWriteExecutionJournal",
                    "src/features/stealth-orders/StealthOrdersReadModel.tsx",
                ],
                documentation_refs=[
                    "README.admin-api.md",
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/STEALTH_ORDER_READS.md",
                    "docs/examples/stealth-command-suite.md",
                ],
                required_next_contract=(
                    "Future executable stealth command paths must still prove "
                    "verified post-write reconciliation and completion; this "
                    "journal acceptance route is local admission evidence only."
                ),
                blockers=[
                    "live_execution_disabled",
                    "post_write_reconciliation_not_verified",
                    "reconciliation_execution_disabled",
                    "completion_verifier_missing",
                    "post-write reconciliation prerequisite unsatisfied",
                ],
                frontend_boundary=(
                    "Do not use browser journal records as reconciliation "
                    "verification, command enablement, manager authority, "
                    "active-placement cancel/replace authority, Coinbase "
                    "authority, or lifecycle mutation input."
                ),
                spot_rule_boundary=(
                    "Spot wallet and inventory rules remain backend guard "
                    "evidence; stealth post-write execution-journal "
                    "acceptance is not sell authority or exchange truth."
                ),
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-verifications",
                mutation_id="stealth.post_write_reconciliation_verification",
                mutation_family=(
                    AdminApiMutationFamilyType.STEALTH_POST_WRITE_RECONCILIATION_VERIFICATION
                ),
                workflow_id="stealth.post_write_reconciliation_verification_command_draft",
                module="Stealth Orders",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Stealth post-write reconciliation verification is "
                    "append-only local evidence keyed by stealth_order_id, "
                    "safe proof id, accepted journal id, and guarded command "
                    "context; it verifies the local evidence chain without "
                    "executing reconciliation, invoking managers, calling "
                    "Coinbase, cancelling or replacing placements, or "
                    "mutating lifecycle/order/exchange state."
                ),
                identity_keys=["stealth_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/stealth.py::record_stealth_post_write_reconciliation_verification",
                    "application/admin_api/command_service.py::record_stealth_post_write_reconciliation_verification",
                    "application/admin_api/stealth_post_write_reconciliation_service.py",
                    "application/admin_api/stealth_post_write_reconciliation.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::recordStealthPostWriteReconciliationVerification",
                    "src/features/stealth-orders/StealthOrdersReadModel.tsx",
                ],
                documentation_refs=[
                    "README.admin-api.md",
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/STEALTH_ORDER_READS.md",
                    "docs/examples/stealth-command-suite.md",
                ],
                required_next_contract=(
                    "Future executable stealth command paths must still enable "
                    "the live adapter and executor after the exact proof, "
                    "journal, and verification chain resolves prerequisite "
                    "evidence; this verification route is local evidence only."
                ),
                blockers=[
                    "live_execution_disabled",
                    "post_write_reconciliation_executor_missing",
                    "reconciliation_execution_disabled",
                    "live_adapter_disabled",
                    "post-write reconciliation execution disabled",
                ],
                frontend_boundary=(
                    "Do not use browser verification records as command "
                    "enablement, manager authority, active-placement "
                    "cancel/replace authority, Coinbase authority, "
                    "reconciliation execution authority, or lifecycle "
                    "mutation input."
                ),
                spot_rule_boundary=(
                    "Spot wallet and inventory rules remain backend guard "
                    "evidence; stealth post-write verification is not sell "
                    "authority or exchange truth."
                ),
            ),
            mutation_taxonomy_from_surface(
                surface="POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice",
                mutation_id="movement.reprice",
                mutation_family=AdminApiMutationFamilyType.MOVEMENT_REPRICE,
                workflow_id="movement.reprice_command_draft",
                module="Order Movement / Repricing",
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                support_status=AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED,
                summary=(
                    "Movement/reprice is a cancel/replace-shaped mutation keyed by "
                    "stealth_order_id with mutation-claim and cooldown requirements."
                ),
                identity_keys=["stealth_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=[
                    "api/v1/routes/movement_repricing.py::reprice_stealth_order_by_stealth_order_id",
                    "application/admin_api/command_service.py::reprice_stealth_order_by_stealth_order_id",
                    "core/stealth_order_manager.py",
                    "business/move_manager.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::repriceStealthOrderByStealthOrderId",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                documentation_refs=["README.movement-repricing.md"],
                required_next_contract=(
                    "Backend live reprice contract with mutation claims, cooldown "
                    "handling, exchange cancel/replace, approval, cap, audit, and "
                    "reconciliation."
                ),
                blockers=[
                    "live_execution_disabled",
                    "mutation claim proof missing",
                    "cancel/replace reconciliation missing",
                ],
                frontend_boundary=(
                    "Do not clear cooldowns, bypass mutation claims, call legacy "
                    "dashboard repricing, or mutate revealed placement state."
                ),
                spot_rule_boundary=(
                    "Spot replacement-budget checks may apply only as backend guard "
                    "evidence; they cannot approve movement/repricing generically."
                ),
            ),
            mutation_taxonomy_item(
                mutation_id="futures.commands_contract_required",
                mutation_family=AdminApiMutationFamilyType.FUTURES_CONTRACT_REQUIRED,
                workflow_id="futures.commands_not_modeled",
                module_id="futures_perpetuals",
                module="Futures / Perpetuals",
                exposure_status=AdminApiFunctionalityExposureStatus.BACKEND_CONTRACT_REQUIRED,
                support_status=AdminApiModuleSupportStatus.NOT_MODELED,
                summary=(
                    "Futures placement, close, reduce-only, close-only, cancel, "
                    "funding, and collateral commands require backend-specific "
                    "contracts before any route or UI exists."
                ),
                identity_keys=["position_key", "product_id", "portfolio_id"],
                action_classes=[],
                required_permissions=[],
                idempotency_contract="backend futures idempotency contract missing",
                approval_contract="backend futures approval contract missing",
                cap_guard_contract=(
                    "backend futures margin, collateral, liquidation, reduce-only, "
                    "close-only, and funding guard contract missing"
                ),
                admission_audit_contract="backend futures admission audit contract missing",
                reconciliation_contract="backend futures reconciliation contract missing",
                owning_backend_service="backend futures/perpetual command service missing",
                backend_contract_refs=["api/v1/routes/futures.py"],
                frontend_contract_refs=["src/features/admin-shell/AdminShell.tsx"],
                documentation_refs=["README.futures-perpetuals.md"],
                required_next_contract=(
                    "Futures/perpetual command contracts over position side, margin, "
                    "collateral, liquidation, reduce-only, close-only, funding, "
                    "order, cancel, and reconciliation semantics."
                ),
                blockers=["backend futures command contract missing"],
                frontend_boundary=(
                    "Do not create futures command drafts by copying spot order, "
                    "wallet, no-shorting, or cost-basis behavior."
                ),
                spot_rule_boundary=(
                    "Spot rules are forbidden in futures/perpetual command authority."
                ),
                idempotency_required=False,
                operator_intent_required=False,
                rbac_required=False,
                approval_required=False,
                cap_guard_required=False,
                admission_audit_required=False,
                reconciliation_required=False,
                live_adapter_required=False,
            ),
            mutation_taxonomy_item(
                mutation_id="audit.fill_ledger_repair_contract_required",
                mutation_family=(
                    AdminApiMutationFamilyType.FILL_LEDGER_REPAIR_CONTRACT_REQUIRED
                ),
                workflow_id="audit.fill_ledger_repair_contract_required",
                module_id="audit_workbench",
                module="Audit Workbench",
                exposure_status=AdminApiFunctionalityExposureStatus.BACKEND_CONTRACT_REQUIRED,
                support_status=AdminApiModuleSupportStatus.NOT_MODELED,
                summary=(
                    "Fill-ledger repair requires a backend-owned preview, apply, audit, "
                    "and reconciliation contract before any admin repair control exists."
                ),
                identity_keys=["client_order_id", "trade_id", "audit_id"],
                action_classes=[AdminApiActionClass.LOCAL_STATE_MUTATION],
                required_permissions=[AdminApiPermission.CONFIG_UPDATE],
                idempotency_contract="backend repair idempotency contract missing",
                approval_contract="repair approval/preview contract missing",
                cap_guard_contract="repair policy and blast-radius guard contract missing",
                admission_audit_contract="append-only repair audit contract missing",
                reconciliation_contract="repair reconciliation/proof contract missing",
                owning_backend_service="backend fill-ledger repair service missing",
                backend_contract_refs=[
                    "tools/run_spot_fill_ledger_repair.py",
                    "business/fill_reconciler.py",
                ],
                documentation_refs=["docs/SPOT_READINESS_ROADMAP.md"],
                required_next_contract=(
                    "Backend repair command with dry-run preview, idempotency, RBAC, "
                    "append-only audit, bounded apply, rollback/proof, and "
                    "reconciliation evidence."
                ),
                blockers=["Admin API repair mutation contract missing"],
                frontend_boundary=(
                    "Do not expose ledger repair buttons until backend preview/apply "
                    "contracts exist."
                ),
                spot_rule_boundary=(
                    "Current repair tooling is spot/fill-ledger oriented and must "
                    "not mutate futures, stealth, or movement state."
                ),
                idempotency_required=False,
                operator_intent_required=False,
                rbac_required=False,
                approval_required=False,
                cap_guard_required=False,
                admission_audit_required=False,
                reconciliation_required=False,
                live_adapter_required=False,
            ),
            mutation_taxonomy_from_surface(
                surface="place_order WebSocket",
                mutation_id="legacy.dashboard_place",
                mutation_family=AdminApiMutationFamilyType.LEGACY_DASHBOARD_PLACE,
                workflow_id="legacy.dashboard_compatibility",
                module="Legacy Dashboard WebSocket",
                exposure_status=AdminApiFunctionalityExposureStatus.COMPATIBILITY_ONLY,
                support_status=AdminApiModuleSupportStatus.UNSUPPORTED,
                summary=(
                    "Legacy dashboard place_order WebSocket exists only as a "
                    "compatibility surface and is not the enterprise admin command plane."
                ),
                identity_keys=["client_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=["dashboard_server.py", "docs/LIVE_ORDER_SURFACES.md"],
                frontend_contract_refs=["src/shared/api/contracts/adminBffProxy.ts"],
                documentation_refs=["docs/LIVE_ORDER_SURFACES.md"],
                required_next_contract=(
                    "Any replacement must be an Admin API route through auth, RBAC, "
                    "idempotency, approval, caps, audit, reconciliation, and shared "
                    "command service."
                ),
                blockers=["compatibility-only surface"],
                frontend_boundary=(
                    "Enterprise frontend must not call legacy dashboard WebSocket "
                    "placement handlers."
                ),
                spot_rule_boundary="Legacy spot behavior is not frontend authority.",
            ),
            mutation_taxonomy_from_surface(
                surface="place_hotpoint_test_order WebSocket",
                mutation_id="legacy.dashboard_hotpoint",
                mutation_family=AdminApiMutationFamilyType.LEGACY_DASHBOARD_HOTPOINT,
                workflow_id="legacy.dashboard_compatibility",
                module="Legacy Dashboard WebSocket",
                exposure_status=AdminApiFunctionalityExposureStatus.COMPATIBILITY_ONLY,
                support_status=AdminApiModuleSupportStatus.UNSUPPORTED,
                summary=(
                    "Legacy hotpoint placement WebSocket exists only as a compatibility "
                    "surface and must not become enterprise frontend authority."
                ),
                identity_keys=["client_order_id"],
                owning_backend_service="dashboard compatibility adapter",
                backend_contract_refs=["dashboard_server.py", "docs/LIVE_ORDER_SURFACES.md"],
                frontend_contract_refs=["src/shared/api/contracts/adminBffProxy.ts"],
                documentation_refs=["docs/LIVE_ORDER_SURFACES.md"],
                required_next_contract=(
                    "Backend-owned Admin API command contract before any equivalent "
                    "enterprise UI path exists."
                ),
                blockers=["compatibility-only surface"],
                frontend_boundary=(
                    "Enterprise frontend must not call legacy dashboard hotpoint "
                    "WebSocket handlers."
                ),
                spot_rule_boundary="Legacy hotpoint behavior is not reusable spot authority.",
            ),
            mutation_taxonomy_from_surface(
                surface="cancel_order WebSocket",
                mutation_id="legacy.dashboard_cancel",
                mutation_family=AdminApiMutationFamilyType.LEGACY_DASHBOARD_CANCEL,
                workflow_id="legacy.dashboard_compatibility",
                module="Legacy Dashboard WebSocket",
                exposure_status=AdminApiFunctionalityExposureStatus.COMPATIBILITY_ONLY,
                support_status=AdminApiModuleSupportStatus.UNSUPPORTED,
                summary=(
                    "Legacy cancel_order WebSocket remains compatibility-only; "
                    "enterprise cancel authority belongs to Admin API client_order_id "
                    "contracts."
                ),
                identity_keys=["client_order_id"],
                owning_backend_service="application/admin_api/command_service.py",
                backend_contract_refs=["dashboard_server.py", "docs/LIVE_ORDER_SURFACES.md"],
                frontend_contract_refs=["src/shared/api/contracts/adminBffProxy.ts"],
                documentation_refs=["docs/LIVE_ORDER_SURFACES.md"],
                required_next_contract=(
                    "Use Admin API cancel routes and project cancel_order(client_order_id) "
                    "wrapper; do not add browser WebSocket cancel authority."
                ),
                blockers=["compatibility-only surface"],
                frontend_boundary=(
                    "Enterprise frontend must not call legacy dashboard WebSocket "
                    "cancel handlers."
                ),
                spot_rule_boundary="Legacy cancel behavior is not frontend spot authority.",
            ),
        ]
        unsupported_statuses = {
            AdminApiModuleSupportStatus.NOT_MODELED,
            AdminApiModuleSupportStatus.UNSUPPORTED,
        }
        security_checks = [
            AdminGateCheck(
                name="browser_authority_boundary",
                status=AdminApiGateStatus.PASSED,
                detail=(
                    "Enterprise admin frontend/Admin HTTP authority is backend_contract_only; "
                    "this path does not approve, place, cancel, or reconcile Coinbase "
                    "orders. Legacy browser live surfaces are compatibility-only and "
                    "documented in docs/LIVE_ORDER_SURFACES.md."
                ),
            ),
            AdminGateCheck(
                name="server_secret_boundary",
                status=AdminApiGateStatus.PASSED,
                detail="BFF mode keeps ADMIN_API_* authority server-side and rejects browser-supplied authority headers.",
            ),
            AdminGateCheck(
                name="command_bypass_boundary",
                status=AdminApiGateStatus.PASSED,
                detail="Command paths must use canonical Admin API wrappers, idempotency, RBAC, and audit evidence.",
            ),
            AdminGateCheck(
                name="live_execution_default",
                status=AdminApiGateStatus.PASSED,
                detail="Live Coinbase execution is disabled by default and this read route submits no orders.",
            ),
        ]
        release_checks = [
            AdminGateCheck(
                name="backend_regression_gate",
                status=AdminApiGateStatus.WARNING,
                detail="Run pytest tests\\regression\\ -v --tb=short after backend changes before release.",
            ),
            AdminGateCheck(
                name="frontend_release_gate",
                status=AdminApiGateStatus.WARNING,
                detail="Run npm run release:gate after frontend/API changes before release.",
            ),
            AdminGateCheck(
                name="contextless_review_gate",
                status=AdminApiGateStatus.WARNING,
                detail="Run backend, frontend, and module-onboarding contextless reviews before M9 release closure.",
            ),
            AdminGateCheck(
                name="module_capability_matrix",
                status=AdminApiGateStatus.PASSED,
                detail="Supported and unsupported module posture is exposed by this backend-owned contract.",
            ),
        ]
        supported_module_count = sum(
            1 for module in modules if module.support_status not in unsupported_statuses
        )
        unsupported_module_count = len(modules) - supported_module_count
        command_gap_count = sum(len(module.command_gaps) for module in modules)
        functionality_inventory_count = len(functionality_inventory)
        backend_supported_workflow_count = sum(
            1 for item in functionality_inventory if item.backend_supported
        )
        admin_exposed_workflow_count = sum(
            1 for item in functionality_inventory if item.admin_api_exposed
        )
        command_workflow_count = sum(
            1 for item in functionality_inventory if item.command_capable
        )
        live_designated_workflow_count = sum(
            1 for item in functionality_inventory if item.live_designated
        )
        recovery_workflow_count = sum(
            1
            for item in functionality_inventory
            if item.workflow_type == AdminApiFunctionalityWorkflowType.RECOVERY
        )
        automation_workflow_count = sum(
            1
            for item in functionality_inventory
            if item.workflow_type == AdminApiFunctionalityWorkflowType.AUTOMATION
        )
        repair_workflow_count = sum(
            1
            for item in functionality_inventory
            if item.workflow_type == AdminApiFunctionalityWorkflowType.REPAIR
        )
        mutation_taxonomy_count = len(mutation_taxonomy)
        route_bound_mutation_taxonomy_count = sum(
            1 for item in mutation_taxonomy if item.command_surfaces
        )
        live_disabled_mutation_count = sum(
            1
            for item in mutation_taxonomy
            if item.exposure_status
            == AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED
        )
        backend_contract_required_mutation_count = sum(
            1
            for item in mutation_taxonomy
            if item.exposure_status
            == AdminApiFunctionalityExposureStatus.BACKEND_CONTRACT_REQUIRED
        )
        compatibility_mutation_count = sum(
            1
            for item in mutation_taxonomy
            if item.exposure_status
            == AdminApiFunctionalityExposureStatus.COMPATIBILITY_ONLY
        )
        status = (
            AdminApiGateStatus.BLOCKED
            if any(
                check.status == AdminApiGateStatus.BLOCKED
                for check in [*security_checks, *release_checks]
            )
            else AdminApiGateStatus.WARNING
        )
        return AdminEnterpriseReadinessResponse(
            approved_phase_range=AUTONOMOUS_APPROVED_PHASE_RANGE,
            status=status,
            module_count=len(modules),
            supported_module_count=supported_module_count,
            unsupported_module_count=unsupported_module_count,
            command_gap_count=command_gap_count,
            module_registry_count=len(modules),
            module_action_posture_count=sum(
                1 for module in modules if module.action_posture is not None
            ),
            functionality_inventory_count=functionality_inventory_count,
            backend_supported_workflow_count=backend_supported_workflow_count,
            admin_exposed_workflow_count=admin_exposed_workflow_count,
            command_workflow_count=command_workflow_count,
            live_designated_workflow_count=live_designated_workflow_count,
            recovery_workflow_count=recovery_workflow_count,
            automation_workflow_count=automation_workflow_count,
            repair_workflow_count=repair_workflow_count,
            mutation_taxonomy_count=mutation_taxonomy_count,
            route_bound_mutation_taxonomy_count=route_bound_mutation_taxonomy_count,
            live_disabled_mutation_count=live_disabled_mutation_count,
            backend_contract_required_mutation_count=(
                backend_contract_required_mutation_count
            ),
            compatibility_mutation_count=compatibility_mutation_count,
            modules=modules,
            functionality_inventory=functionality_inventory,
            mutation_taxonomy=mutation_taxonomy,
            security_checks=security_checks,
            release_checks=release_checks,
        )

    def build_guard_risk_policy(
        self,
        *,
        product_id: str | None = None,
    ) -> AdminRiskPolicyReadResponse:
        """Return read-only guard/risk policy evidence without Coinbase reads."""

        from core.action_condition_guard import (
            get_action_condition_guard_policy,
            normalize_action_guard_known_inventory_policy,
            normalize_action_guard_wallet_policy,
            rest_credentials_configured,
        )
        from core.product_capability import get_product_capability_policy

        action_policy = get_action_condition_guard_policy()
        wallet_policy = normalize_action_guard_wallet_policy(action_policy)
        known_inventory_policy = normalize_action_guard_known_inventory_policy(
            action_policy
        )
        limit_rules = _configured_limit_rules(action_policy)
        product_capability_policy = get_product_capability_policy()
        live_gate = evaluate_live_execution_gate(allow_live_execution=False)

        action_policy_value = {
            "policy_configured": bool(action_policy),
            "wallet_available": wallet_policy,
            "known_inventory_available": known_inventory_policy,
            "limit_rule_count": len(limit_rules),
            "limit_policy_ids": [rule.policy_id for rule in limit_rules],
            "rest_credentials_configured": rest_credentials_configured(),
            "coinbase_wallet_fetch_performed": False,
            "decision_boundary": (
                "ActionConditionGuard.evaluate at planning/reveal/command "
                "boundaries; this read route reports policy only."
            ),
        }

        capability_decisions, capability_errors = _product_capability_decisions(product_id)
        capability_value: dict[str, Any] = {
            "configured_overrides": product_capability_policy,
            "decision_product_id": product_id,
            "decision_count": len(capability_decisions),
            "decision_error_count": len(capability_errors),
            "decision_errors": capability_errors,
            "conditional_modes_are_not_live_authority": True,
        }
        if not product_id:
            capability_value["decision_detail"] = (
                "Pass product_id to inspect product-specific capability "
                "decisions; defaults remain backend-owned."
            )

        authority_sources = [
            _risk_evidence(
                name="wallet_authority",
                status=(
                    AdminRiskEvidenceStatus.OBSERVED
                    if wallet_policy.get("enabled", True) is not False
                    else AdminRiskEvidenceStatus.NOT_MODELED
                ),
                source=AdminRiskEvidenceSource.ACTION_CONDITION_GUARD,
                value={
                    "policy": wallet_policy,
                    "coinbase_wallet_fetch_performed": False,
                },
                detail=(
                    "Spot wallet availability is evaluated by the backend "
                    "action guard at command/reveal boundaries; this route "
                    "does not fetch Coinbase wallets."
                ),
            ),
            _risk_evidence(
                name="planned_budget_authority",
                status=AdminRiskEvidenceStatus.OBSERVED,
                source=AdminRiskEvidenceSource.ACTION_CONDITION_GUARD,
                value={
                    "hidden_statuses_counted": [
                        StealthOrderStatus.HIDDEN.value,
                        StealthOrderStatus.PENDING.value,
                        StealthOrderStatus.TRIGGERED.value,
                    ],
                    "revealed_orders_excluded": True,
                },
                detail=(
                    "Local pre-exchange spot commitments are subtracted by "
                    "the existing planned-budget guard."
                ),
            ),
            _risk_evidence(
                name="spot_known_inventory_authority",
                status=(
                    AdminRiskEvidenceStatus.OBSERVED
                    if known_inventory_policy.get("enabled", False) is not False
                    else AdminRiskEvidenceStatus.NOT_MODELED
                ),
                source=AdminRiskEvidenceSource.SPOT_INVENTORY_AUTHORITY,
                value={"policy": known_inventory_policy},
                detail=(
                    "Known profitable inventory authority is spot SELL only; "
                    "it is not imported into futures/perpetual modules."
                ),
            ),
            _risk_evidence(
                name="position_authority",
                status=AdminRiskEvidenceStatus.OBSERVED,
                source=AdminRiskEvidenceSource.BACKEND_CONTRACT,
                value={
                    "futures_position_identity": "position_key",
                    "spot_inventory_identity": "client_order_id_and_lot_authority",
                },
                detail=(
                    "Position authority is product-domain specific. Futures "
                    "uses position evidence; spot uses wallet/lot authority."
                ),
            ),
        ]

        return AdminRiskPolicyReadResponse(
            filters={"product_id": product_id},
            action_condition_policy=_risk_evidence(
                name="action_condition_policy",
                status=AdminRiskEvidenceStatus.OBSERVED,
                source=AdminRiskEvidenceSource.ACTION_CONDITION_GUARD,
                value=action_policy_value,
                detail=(
                    "Configured guard policy and cap rules are exposed as "
                    "read-only evidence; no guard decision is trusted to the browser."
                ),
            ),
            configured_limit_rules=limit_rules,
            live_execution_gate=_risk_evidence(
                name="live_execution_gate",
                status=AdminRiskEvidenceStatus.FAIL_CLOSED,
                source=AdminRiskEvidenceSource.LIVE_EXECUTION_GATE,
                value=live_gate.model_dump(mode="json"),
                detail=(
                    "HTTP live execution remains fail-closed until approval, "
                    "cap evaluation, and durable audit gates are enforced."
                ),
            ),
            product_capability_policy=_risk_evidence(
                name="product_capability_policy",
                status=(
                    AdminRiskEvidenceStatus.UNAVAILABLE
                    if capability_errors
                    else AdminRiskEvidenceStatus.OBSERVED
                ),
                source=AdminRiskEvidenceSource.PRODUCT_CAPABILITY_POLICY,
                value=capability_value,
                detail=(
                    "Product capability decisions come from core.product_capability; "
                    "the frontend may display but not override them."
                ),
            ),
            product_capability_decisions=capability_decisions,
            profitability_policy=_risk_evidence(
                name="profitability_policy",
                status=AdminRiskEvidenceStatus.OBSERVED,
                source=AdminRiskEvidenceSource.PROFIT_VALIDATOR,
                value={
                    "validator": "calculation.profit_validator.ProfitValidator",
                    "product_specific": True,
                    "browser_calculation_allowed": False,
                    "known_contract_gaps": [
                        "futures_margin_validation",
                        "futures_liquidation_distance",
                        "perpetual_funding_cost_accounting",
                    ],
                },
                detail=(
                    "Profitability evidence is backend-owned and product-specific; "
                    "M4 exposes policy posture, not a browser calculator."
                ),
            ),
            authority_sources=authority_sources,
            rejection_categories=_risk_rejection_categories(),
        )

    def build_csrf_contract(self) -> AdminCsrfContractResponse:
        """Return CSRF posture without disclosing a token value."""

        return AdminCsrfContractResponse(csrf_required=_csrf_required())

    def build_live_enablement(self) -> AdminLiveEnablementReadResponse:
        """Return read-only M8 live-enablement posture and cap evidence."""

        paths: list[AdminLiveEnablementPathItem] = []
        for item in ADMIN_API_ROUTE_INVENTORY:
            method, path = _surface_method_and_path(item.surface)
            if method != "POST" or not path.startswith("/api/v1/"):
                continue
            if item.action_class not in {
                AdminApiActionClass.LIVE_EXCHANGE_PLACE,
                AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            }:
                continue
            preflight_checks = _live_preflight_checks(
                module_id=item.module_id,
                route=path,
                shared_method=item.shared_method,
            )
            identity_key = _enterprise_module_identity_key(item.module_id, path)
            approval_snapshot = _live_approval_snapshot_evidence(
                method=method,
                route=path,
                module_id=item.module_id,
                identity_key=identity_key,
                action_class=item.action_class,
                required_permission=item.permission,
            )
            approval_store_contract = _live_approval_store_contract_evidence(
                method=method,
                route=path,
                module_id=item.module_id,
            )
            admission_audit_trail = _live_admission_audit_trail_evidence(
                method=method,
                route=path,
                module_id=item.module_id,
                identity_key=identity_key,
            )
            cap_guard_contract = _live_cap_guard_contract_evidence(
                method=method,
                route=path,
                module_id=item.module_id,
                identity_key=identity_key,
            )
            live_execution_adapter = build_live_execution_adapter_contract(
                method=method,
                route=path,
                module_id=item.module_id,
                service_method=item.shared_method,
                action_class=item.action_class,
            )
            path_live_status = live_execution_adapter.get(
                "status",
                AdminApiLiveExecutionStatus.LIVE_DISABLED,
            )
            readiness_preconditions = _live_readiness_preconditions(
                method=method,
                route=path,
                shared_method=item.shared_method,
                approval_snapshot=approval_snapshot,
                approval_store_contract=approval_store_contract,
                admission_audit_trail=admission_audit_trail,
                cap_guard_contract=cap_guard_contract,
                live_execution_adapter=live_execution_adapter,
            )
            paths.append(
                AdminLiveEnablementPathItem(
                    path_id=_path_id(method, path),
                    route=path,
                    method=method,
                    module_id=item.module_id,
                    module=_enterprise_module_name(item.module_id),
                    module_owner=_enterprise_module_owner(item.module_id),
                    identity_key=identity_key,
                    action_class=item.action_class,
                    required_permission=item.permission,
                    shared_method=item.shared_method,
                    live_enabled=False,
                    live_eligible=False,
                    status=path_live_status,
                    governance_status=AdminApiGateStatus.BLOCKED,
                    approval_required=True,
                    cap_required=True,
                    guard_required=True,
                    audit_required=True,
                    idempotency_key_required=True,
                    operator_intent_required=True,
                    payload_hash_required=True,
                    request_id_required=True,
                    audit_id_required=True,
                    reconciliation_required=True,
                    browser_authority="display_only",
                    reconciliation_blockers=_live_governance_blockers(
                        item.module_id, path
                    ),
                    spot_rule_boundary=_enterprise_module_spot_boundary(
                        item.module_id
                    ),
                    product_scope=LIVE_ENABLEMENT_PRODUCT_SCOPE,
                    max_submitted_notional_usdc=LIVE_ENABLEMENT_MAX_SUBMITTED_NOTIONAL_USDC,
                    max_executed_notional_usdc=LIVE_ENABLEMENT_MAX_EXECUTED_NOTIONAL_USDC,
                    preflight_checks=preflight_checks,
                    blocking_preflight_check_count=sum(
                        1
                        for check in preflight_checks
                        if check.status == AdminApiGateStatus.BLOCKED
                    ),
                    passed_preflight_check_count=sum(
                        1
                        for check in preflight_checks
                        if check.status == AdminApiGateStatus.PASSED
                    ),
                    approval_snapshot=approval_snapshot,
                    approval_store_contract=approval_store_contract,
                    admission_audit_trail=admission_audit_trail,
                    cap_guard_contract=cap_guard_contract,
                    live_execution_adapter=live_execution_adapter,
                    readiness_preconditions=readiness_preconditions,
                    readiness_precondition_count=len(readiness_preconditions),
                    blocking_readiness_precondition_count=sum(
                        1
                        for precondition in readiness_preconditions
                        if precondition.blocking
                    ),
                    passed_readiness_precondition_count=sum(
                        1
                        for precondition in readiness_preconditions
                        if precondition.status == AdminApiGateStatus.PASSED
                    ),
                    evidence=[
                        "M4 guard/risk evidence required",
                        "M6 command contract proof required",
                        "M8 explicit live approval required",
                        "idempotency, operator intent, payload hash, request id, and audit id required",
                        "post-live reconciliation required",
                    ],
                    notes=(
                        "Current Admin API command contract is live-disabled; "
                        "this read route is governance evidence only and does "
                        "not grant browser command authority."
                    ),
                )
            )

        preflight_checks = [
            check
            for path in paths
            for check in path.preflight_checks
        ]
        approval_snapshots = [path.approval_snapshot for path in paths]
        approval_store_contracts = [
            path.approval_store_contract for path in paths
        ]
        admission_audit_trails = [
            path.admission_audit_trail for path in paths
        ]
        cap_guard_contracts = [
            path.cap_guard_contract for path in paths
        ]
        live_execution_adapters = [
            path.live_execution_adapter for path in paths
        ]
        readiness_preconditions = [
            precondition
            for path in paths
            for precondition in path.readiness_preconditions
        ]

        checks = [
            AdminGateCheck(
                name="m4_guard_risk_evidence",
                status=AdminApiGateStatus.PASSED,
                detail="/api/v1/admin/guard-risk-policy is available as read-only evidence.",
            ),
            AdminGateCheck(
                name="m6_command_contracts",
                status=AdminApiGateStatus.PASSED,
                detail="Command contracts exist but remain live-disabled until explicit M8 approval.",
            ),
            AdminGateCheck(
                name="live_execution_default",
                status=AdminApiGateStatus.PASSED,
                detail="Default live Coinbase execution is not_run with submitted/executed notional $0.",
            ),
            AdminGateCheck(
                name="reconciliation_gate",
                status=AdminApiGateStatus.BLOCKED,
                detail="No path is live-enabled until post-live reconciliation evidence is wired for that path.",
            ),
        ]

        return AdminLiveEnablementReadResponse(
            status=AdminApiLiveExecutionStatus.LIVE_DISABLED,
            approved_phase_range=AUTONOMOUS_APPROVED_PHASE_RANGE,
            default_live_coinbase_execution=AdminApiLiveExecutionStatus.NOT_RUN,
            submitted_notional_usdc="0",
            executed_notional_usdc="0",
            quote_currency=LIVE_ENABLEMENT_QUOTE_CURRENCY,
            product_scope=LIVE_ENABLEMENT_PRODUCT_SCOPE,
            max_submitted_notional_usdc=LIVE_ENABLEMENT_MAX_SUBMITTED_NOTIONAL_USDC,
            max_executed_notional_usdc=LIVE_ENABLEMENT_MAX_EXECUTED_NOTIONAL_USDC,
            retain_inventory=True,
            reconciliation_required=True,
            live_enabled_path_count=0,
            live_eligible_path_count=0,
            paths=paths,
            checks=checks,
            preflight_check_count=len(preflight_checks),
            blocking_preflight_check_count=sum(
                1
                for check in preflight_checks
                if check.status == AdminApiGateStatus.BLOCKED
            ),
            passed_preflight_check_count=sum(
                1
                for check in preflight_checks
                if check.status == AdminApiGateStatus.PASSED
            ),
            approval_snapshot_required_count=sum(
                1
                for snapshot in approval_snapshots
                if snapshot.required
            ),
            approval_snapshot_present_count=sum(
                1
                for snapshot in approval_snapshots
                if snapshot.present
            ),
            approval_snapshot_missing_count=sum(
                1
                for snapshot in approval_snapshots
                if not snapshot.present
            ),
            approval_snapshot_required_field_count=sum(
                snapshot.required_field_count
                for snapshot in approval_snapshots
            ),
            approval_snapshot_missing_field_count=sum(
                snapshot.missing_required_field_count
                for snapshot in approval_snapshots
            ),
            approval_store_required_count=sum(
                1
                for contract in approval_store_contracts
                if contract.required
            ),
            approval_store_configured_count=sum(
                1
                for contract in approval_store_contracts
                if contract.configured
            ),
            approval_store_missing_count=sum(
                1
                for contract in approval_store_contracts
                if not contract.configured
            ),
            approval_store_requirement_count=sum(
                contract.requirement_count
                for contract in approval_store_contracts
            ),
            approval_store_missing_requirement_count=sum(
                contract.missing_requirement_count
                for contract in approval_store_contracts
            ),
            admission_audit_required_count=sum(
                1
                for trail in admission_audit_trails
                if trail.required
            ),
            admission_audit_configured_count=sum(
                1
                for trail in admission_audit_trails
                if trail.configured
            ),
            admission_audit_missing_count=sum(
                1
                for trail in admission_audit_trails
                if not trail.configured
            ),
            admission_audit_fact_count=sum(
                trail.fact_count
                for trail in admission_audit_trails
            ),
            admission_audit_missing_fact_count=sum(
                trail.missing_fact_count
                for trail in admission_audit_trails
            ),
            cap_guard_required_count=sum(
                1
                for contract in cap_guard_contracts
                if contract.required
            ),
            cap_guard_configured_count=sum(
                1
                for contract in cap_guard_contracts
                if contract.configured
            ),
            cap_guard_missing_count=sum(
                1
                for contract in cap_guard_contracts
                if not contract.configured
            ),
            cap_guard_requirement_count=sum(
                contract.requirement_count
                for contract in cap_guard_contracts
            ),
            cap_guard_missing_requirement_count=sum(
                contract.missing_requirement_count
                for contract in cap_guard_contracts
            ),
            live_execution_adapter_required_count=sum(
                1 for contract in live_execution_adapters if contract.required
            ),
            live_execution_adapter_configured_count=sum(
                1 for contract in live_execution_adapters if contract.configured
            ),
            live_execution_adapter_missing_count=sum(
                1 for contract in live_execution_adapters if not contract.configured
            ),
            readiness_precondition_count=len(readiness_preconditions),
            blocking_readiness_precondition_count=sum(
                1
                for precondition in readiness_preconditions
                if precondition.blocking
            ),
            passed_readiness_precondition_count=sum(
                1
                for precondition in readiness_preconditions
                if precondition.status == AdminApiGateStatus.PASSED
            ),
        )

    def build_audit_workbench(
        self,
        *,
        module: AdminAuditWorkbenchModule | str | None = None,
        product_id: str | None = None,
        client_order_id: str | None = None,
        correlation_id: str | None = None,
        audit_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> AdminAuditWorkbenchReadResponse:
        """Return cross-module audit/correlation evidence without Coinbase reads."""

        normalized_module = _normalize_audit_module(module)
        normalized_limit = max(1, min(limit, 500))
        normalized_offset = max(0, offset)
        filters: dict[str, Any] = {
            "module": normalized_module.value if normalized_module else None,
            "product_id": product_id,
            "client_order_id": client_order_id,
            "correlation_id": correlation_id,
            "audit_id": audit_id,
            "limit": normalized_limit,
            "offset": normalized_offset,
        }
        if module is not None and normalized_module is None:
            filters["module_error"] = f"Unknown audit module: {module}"

        events: list[AdminAuditWorkbenchEventItem] = []
        source_errors: list[str] = []

        try:
            command_events = FileAdminApiAuditStore().read_recent(limit=500)
            events.extend(
                _audit_event_from_command_event(event)
                for event in command_events
            )
        except Exception as exc:
            source_errors.append(f"admin_api_audit_log:{type(exc).__name__}: {exc}")

        if normalized_module in {None, AdminAuditWorkbenchModule.ORDERS}:
            order_response = self.build_order_list(
                product_id=product_id,
                limit=500,
                offset=0,
            )
            if order_response.filters.get("backend_read_error"):
                source_errors.append(
                    f"orders:{order_response.filters['backend_read_error']}"
                )
            events.extend(
                _audit_event_from_order_item(item)
                for item in order_response.items
            )

        if normalized_module in {None, AdminAuditWorkbenchModule.STEALTH}:
            stealth_response = self.build_stealth_order_list(
                product_id=product_id,
                limit=500,
                offset=0,
            )
            if stealth_response.filters.get("backend_read_error"):
                source_errors.append(
                    f"stealth:{stealth_response.filters['backend_read_error']}"
                )
            events.extend(
                _audit_event_from_stealth_item(item)
                for item in stealth_response.items
            )

        if normalized_module in {None, AdminAuditWorkbenchModule.MOVEMENT_REPRICING}:
            movement_response = self.build_movement_repricing_evidence(
                product_id=product_id,
                client_order_id=client_order_id,
                limit=500,
                offset=0,
            )
            if movement_response.filters.get("backend_read_errors"):
                source_errors.extend(
                    f"movement_repricing:{error}"
                    for error in movement_response.filters["backend_read_errors"]
                )
            events.extend(
                _audit_event_from_movement_item(item)
                for item in movement_response.items
            )

        if normalized_module in {None, AdminAuditWorkbenchModule.FUTURES_PERPETUALS}:
            futures_response = self.build_futures_positions(
                product_id=product_id,
                limit=500,
                offset=0,
            )
            events.extend(
                _audit_event_from_futures_position(item)
                for item in futures_response.items
            )

        if normalized_module in {None, AdminAuditWorkbenchModule.GUARD_RISK}:
            events.append(
                _audit_event_from_guard_risk_policy(
                    self.build_guard_risk_policy(product_id=product_id)
                )
            )

        if source_errors:
            filters["source_errors"] = source_errors

        filtered = [
            item
            for item in events
            if _audit_event_matches(
                item,
                module=normalized_module,
                product_id=product_id,
                client_order_id=client_order_id,
                correlation_id=correlation_id,
                audit_id=audit_id,
            )
        ]
        page_items = filtered[normalized_offset:normalized_offset + normalized_limit]
        next_offset = normalized_offset + len(page_items)
        has_more = next_offset < len(filtered)
        return AdminAuditWorkbenchReadResponse(
            filters=filters,
            module_summary=_audit_module_summary(),
            events=page_items,
            pagination={
                "limit": normalized_limit,
                "offset": normalized_offset,
                "returned_count": len(page_items),
                "total_matching_count": len(filtered),
                "next_offset": next_offset if has_more else None,
                "has_more": has_more,
            },
        )

    def build_order_list(
        self,
        *,
        product_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> AdminOrderListResponse:
        """Return a read-only order list from local order_parent evidence."""

        normalized_limit = max(1, min(limit, 500))
        normalized_offset = max(0, offset)
        filters: dict[str, Any] = {
            "product_id": product_id,
            "status": status,
            "limit": normalized_limit,
            "offset": normalized_offset,
        }
        try:
            from database.order import get_parent_orders

            rows = get_parent_orders() or []
        except Exception as exc:
            filters["backend_read_error"] = f"{type(exc).__name__}: {exc}"
            rows = []

        filtered: list[dict[str, Any]] = []
        for row in rows:
            if product_id and row.get("product_id") != product_id:
                continue
            if status and str(row.get("status") or "").lower() != status.lower():
                continue
            filtered.append(row)
        page_rows = filtered[normalized_offset:normalized_offset + normalized_limit]
        items = [_order_item_from_row(row) for row in page_rows]
        next_offset = normalized_offset + len(items)
        has_more = next_offset < len(filtered)
        return AdminOrderListResponse(
            filters=filters,
            count=len(items),
            pagination={
                "limit": normalized_limit,
                "offset": normalized_offset,
                "returned_count": len(items),
                "total_matching_count": len(filtered),
                "next_offset": next_offset if has_more else None,
                "has_more": has_more,
            },
            items=items,
        )

    def build_order_detail(self, *, client_order_id: str) -> AdminOrderDetailResponse:
        """Return one read-only order row by ``client_order_id``."""

        try:
            from database.order import get_parent_order

            row = get_parent_order(client_order_id)
        except Exception:
            row = None
        return AdminOrderDetailResponse(
            client_order_id=client_order_id,
            found=row is not None,
            order=_order_item_from_row(row) if row else None,
        )

    def build_stealth_order_list(
        self,
        *,
        product_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> AdminStealthOrderListResponse:
        """Return read-only stealth order evidence from local persistence."""

        normalized_limit = max(1, min(limit, 500))
        normalized_offset = max(0, offset)
        filters: dict[str, Any] = {
            "product_id": product_id,
            "status": status,
            "limit": normalized_limit,
            "offset": normalized_offset,
        }
        try:
            from database import order as order_module

            rows = order_module.DB_CLIENT.execute_query(
                "SELECT * FROM stealth_orders ORDER BY updated_at DESC, created_at DESC"
            ) or []
        except Exception as exc:
            filters["backend_read_error"] = f"{type(exc).__name__}: {exc}"
            rows = []

        filtered: list[dict[str, Any]] = []
        for row in rows:
            if product_id and row.get("product_id") != product_id:
                continue
            if status and str(row.get("status") or "").lower() != status.lower():
                continue
            filtered.append(row)

        page_rows = filtered[normalized_offset:normalized_offset + normalized_limit]
        items = [_stealth_item_from_row(row) for row in page_rows]
        next_offset = normalized_offset + len(items)
        has_more = next_offset < len(filtered)
        return AdminStealthOrderListResponse(
            filters=filters,
            count=len(items),
            pagination={
                "limit": normalized_limit,
                "offset": normalized_offset,
                "returned_count": len(items),
                "total_matching_count": len(filtered),
                "next_offset": next_offset if has_more else None,
                "has_more": has_more,
            },
            items=items,
        )

    def build_stealth_order_detail(
        self,
        *,
        stealth_order_id: str,
    ) -> AdminStealthOrderDetailResponse:
        """Return one read-only stealth order row by ``stealth_order_id``."""

        try:
            from database.order import get_stealth_order_by_id

            row = get_stealth_order_by_id(stealth_order_id)
        except Exception:
            row = None
        item = _stealth_item_from_row(row) if row else None
        return AdminStealthOrderDetailResponse(
            stealth_order_id=stealth_order_id,
            found=row is not None,
            order=item,
            active_placement_audit=(
                _stealth_active_placement_audit(item) if item else None
            ),
            mutation_claim_audit=(
                _stealth_mutation_claim_audit(item.stealth_order_id) if item else None
            ),
            reveal_trigger_audit=(
                _stealth_reveal_trigger_audit(item) if item else None
            ),
            reveal_submission_audit=(
                _stealth_reveal_submission_audit(item) if item else None
            ),
            reveal_reconciliation_audit=(
                _stealth_reveal_reconciliation_audit(item) if item else None
            ),
        )

    def build_stealth_active_placement_exchange_truth(
        self,
        *,
        stealth_order_id: str,
    ) -> StealthActivePlacementExchangeTruthReadResponse:
        """Return persisted no-live active-placement exchange-truth evidence."""

        snapshots = [
            _stealth_exchange_truth_snapshot_item_from_record(record)
            for record in self.stealth_exchange_truth_snapshot_store.read_for_stealth_order_id(
                stealth_order_id,
                limit=20,
            )
        ]
        proofs = [
            _stealth_exchange_truth_proof_item_from_record(record)
            for record in self.stealth_exchange_truth_proof_store.read_for_stealth_order_id(
                stealth_order_id,
                limit=20,
            )
        ]
        latest_snapshot_id = (
            snapshots[0].exchange_truth_snapshot_id if snapshots else None
        )
        latest_proof_id = proofs[0].exchange_truth_proof_id if proofs else None
        missing_contracts = [
            "backend_coinbase_active_placement_read_authority",
            "stealth_active_placement_cancel_replace_audit",
            "stealth_active_placement_reconciliation_execution_proof",
        ]
        return StealthActivePlacementExchangeTruthReadResponse(
            approved_phase_range=AUTONOMOUS_APPROVED_PHASE_RANGE,
            stealth_order_id=stealth_order_id,
            status=AdminApiGateStatus.BLOCKED,
            exchange_truth_verified=False,
            persisted_snapshot_count=len(snapshots),
            persisted_snapshots=snapshots,
            persisted_proof_count=len(proofs),
            persisted_proofs=proofs,
            latest_exchange_truth_snapshot_id=latest_snapshot_id,
            latest_exchange_truth_proof_id=latest_proof_id,
            missing_contracts=missing_contracts,
            backend_owned=True,
            read_only=True,
            route_bound=True,
            coinbase_read_attempted=False,
            coinbase_read_succeeded=False,
            coinbase_rest_read_ran=False,
            coinbase_order_submitted=False,
            coinbase_order_cancel_submitted=False,
            active_placement_cancel_replace_ran=False,
            reconciliation_executed=False,
            order_state_mutated=False,
            lifecycle_state_mutated=False,
            exchange_state_mutated=False,
            live_exchange_submitted=False,
            live_coinbase_orders_ran=False,
            live_coinbase_read_ran=False,
            browser_authority="display_only",
            bff_authority="read_only_forward",
            detail=(
                "Persisted stealth active-placement exchange-truth records are "
                "backend-owned evidence only. They do not verify live Coinbase "
                "state, cancel or replace placements, execute reconciliation, "
                "or mutate stealth/order/exchange state."
            ),
        )

    def build_stealth_create_lifecycle_write_guard(
        self,
        *,
        stealth_order_id: str,
    ) -> StealthCreateLifecycleWriteGuardReadResponse:
        """Return persisted no-live create lifecycle-write guard evidence."""

        proofs = [
            _stealth_lifecycle_write_guard_item_from_record(record)
            for record in self.stealth_lifecycle_write_guard_proof_store.read_for_stealth_order_id(
                stealth_order_id,
                limit=20,
            )
        ]
        latest_proof_id = (
            proofs[0].lifecycle_write_guard_proof_id if proofs else None
        )
        missing_contracts = [
            "stealth_create_lifecycle_write_execution_contract",
            "stealth_create_manager_invocation_contract",
            "stealth_create_post_write_reconciliation_execution_proof",
        ]
        return StealthCreateLifecycleWriteGuardReadResponse(
            approved_phase_range=AUTONOMOUS_APPROVED_PHASE_RANGE,
            stealth_order_id=stealth_order_id,
            status=AdminApiGateStatus.BLOCKED,
            lifecycle_write_guard_verified=False,
            persisted_proof_count=len(proofs),
            persisted_proofs=proofs,
            latest_lifecycle_write_guard_proof_id=latest_proof_id,
            missing_contracts=missing_contracts,
            backend_owned=True,
            read_only=True,
            route_bound=True,
            proof_records_created=bool(proofs),
            manager_invocation_allowed=False,
            manager_invocation_ran=False,
            stealth_row_write_allowed=False,
            stealth_row_write_ran=False,
            order_parent_write_allowed=False,
            order_parent_write_ran=False,
            lifecycle_event_dispatch_allowed=False,
            lifecycle_event_dispatch_ran=False,
            local_lifecycle_mutation_allowed=False,
            local_lifecycle_mutation_ran=False,
            coinbase_read_attempted=False,
            coinbase_read_succeeded=False,
            coinbase_rest_read_ran=False,
            coinbase_order_submitted=False,
            coinbase_order_cancel_submitted=False,
            active_placement_cancel_replace_ran=False,
            reconciliation_required=True,
            reconciliation_executed=False,
            post_write_reconciliation_satisfied=False,
            order_state_mutated=False,
            lifecycle_state_mutated=False,
            exchange_state_mutated=False,
            live_exchange_submitted=False,
            live_coinbase_orders_ran=False,
            live_coinbase_read_ran=False,
            browser_authority="display_only",
            bff_authority="read_only_forward",
            detail=(
                "Persisted stealth create lifecycle-write guard records are "
                "backend-owned evidence only. They do not invoke the stealth "
                "manager, write stealth/order_parent rows, dispatch lifecycle "
                "events, call Coinbase, execute reconciliation, or mutate "
                "stealth/order/exchange state."
            ),
        )

    def build_stealth_mutation_claim_snapshot(
        self,
        *,
        stealth_order_id: str,
    ) -> StealthMutationClaimSnapshotReadResponse:
        """Return persisted no-live mutation-claim snapshot proof evidence."""

        proofs = [
            _stealth_mutation_claim_proof_item_from_record(record)
            for record in self.stealth_mutation_claim_proof_store.read_for_stealth_order_id(
                stealth_order_id,
                limit=20,
            )
        ]
        latest_proof_id = proofs[0].mutation_claim_proof_id if proofs else None
        missing_contracts = [
            "stealth_mutation_claim_acquire_contract",
            "stealth_mutation_claim_release_contract",
            "stealth_mutation_post_write_reconciliation_proof",
        ]
        return StealthMutationClaimSnapshotReadResponse(
            approved_phase_range=AUTONOMOUS_APPROVED_PHASE_RANGE,
            stealth_order_id=stealth_order_id,
            status=AdminApiGateStatus.BLOCKED,
            mutation_claim_snapshot_verified=False,
            persisted_proof_count=len(proofs),
            persisted_proofs=proofs,
            latest_mutation_claim_proof_id=latest_proof_id,
            missing_contracts=missing_contracts,
            backend_owned=True,
            read_only=True,
            route_bound=True,
            proof_records_created=bool(proofs),
            manager_invocation_allowed=False,
            manager_invocation_ran=False,
            claim_acquire_allowed=False,
            claim_acquire_ran=False,
            claim_release_allowed=False,
            claim_release_ran=False,
            coinbase_read_attempted=False,
            coinbase_read_succeeded=False,
            coinbase_rest_read_ran=False,
            coinbase_order_submitted=False,
            coinbase_order_cancel_submitted=False,
            active_placement_cancel_replace_ran=False,
            reconciliation_required=True,
            reconciliation_executed=False,
            order_state_mutated=False,
            lifecycle_state_mutated=False,
            exchange_state_mutated=False,
            live_exchange_submitted=False,
            live_coinbase_orders_ran=False,
            live_coinbase_read_ran=False,
            browser_authority="display_only",
            bff_authority="read_only_forward",
            detail=(
                "Persisted stealth mutation-claim snapshot records are "
                "backend-owned evidence only. They do not invoke the stealth "
                "manager, acquire or release claims, call Coinbase, cancel or "
                "replace placements, execute reconciliation, or mutate "
                "stealth/order/exchange state."
            ),
        )

    def build_stealth_recovery_proof(
        self,
        *,
        stealth_order_id: str,
    ) -> StealthRecoveryProofReadResponse:
        """Return persisted no-live recovery proof evidence."""

        proofs = [
            _stealth_recovery_proof_item_from_record(record)
            for record in self.stealth_recovery_proof_store.read_for_stealth_order_id(
                stealth_order_id,
                limit=20,
            )
        ]
        latest_proof_id = proofs[0].recovery_proof_id if proofs else None
        missing_contracts = [
            "stealth_recovery_repair_execution_contract",
            "stealth_recovery_rollback_execution_contract",
            "stealth_recovery_post_write_reconciliation_proof",
        ]
        return StealthRecoveryProofReadResponse(
            approved_phase_range=AUTONOMOUS_APPROVED_PHASE_RANGE,
            stealth_order_id=stealth_order_id,
            status=AdminApiGateStatus.BLOCKED,
            recovery_proof_verified=False,
            persisted_proof_count=len(proofs),
            persisted_proofs=proofs,
            latest_recovery_proof_id=latest_proof_id,
            missing_contracts=missing_contracts,
            backend_owned=True,
            read_only=True,
            route_bound=True,
            proof_records_created=bool(proofs),
            manager_invocation_allowed=False,
            manager_invocation_ran=False,
            recovery_plan_build_allowed=False,
            recovery_plan_built=False,
            recovery_repair_allowed=False,
            recovery_repair_executed=False,
            rollback_allowed=False,
            rollback_executed=False,
            coinbase_read_attempted=False,
            coinbase_read_succeeded=False,
            coinbase_rest_read_ran=False,
            coinbase_order_submitted=False,
            coinbase_order_cancel_submitted=False,
            active_placement_cancel_replace_ran=False,
            reconciliation_required=True,
            reconciliation_executed=False,
            order_state_mutated=False,
            lifecycle_state_mutated=False,
            exchange_state_mutated=False,
            live_exchange_submitted=False,
            live_coinbase_orders_ran=False,
            live_coinbase_read_ran=False,
            browser_authority="display_only",
            bff_authority="read_only_forward",
            detail=(
                "Persisted stealth recovery proof records are backend-owned "
                "evidence only. They do not repair state, roll back state, "
                "invoke managers, call Coinbase, cancel or replace placements, "
                "execute reconciliation, or mutate stealth/order/exchange state."
            ),
        )

    def build_stealth_reveal_trigger_proof(
        self,
        *,
        stealth_order_id: str,
    ) -> StealthRevealTriggerProofReadResponse:
        """Return persisted no-live reveal-trigger proof evidence."""

        proofs = [
            _stealth_reveal_trigger_proof_item_from_record(record)
            for record in (
                self.stealth_reveal_trigger_proof_store.read_for_stealth_order_id(
                    stealth_order_id,
                    limit=20,
                )
            )
        ]
        latest_proof_id = proofs[0].reveal_trigger_proof_id if proofs else None
        missing_contracts = [
            "stealth_reveal_trigger_execution_guard",
            "stealth_reveal_exchange_submission_adapter",
            "stealth_reveal_post_write_reconciliation_proof",
        ]
        return StealthRevealTriggerProofReadResponse(
            approved_phase_range=AUTONOMOUS_APPROVED_PHASE_RANGE,
            stealth_order_id=stealth_order_id,
            status=AdminApiGateStatus.BLOCKED,
            reveal_trigger_verified=False,
            persisted_proof_count=len(proofs),
            persisted_proofs=proofs,
            latest_reveal_trigger_proof_id=latest_proof_id,
            missing_contracts=missing_contracts,
            backend_owned=True,
            read_only=True,
            route_bound=True,
            proof_records_created=bool(proofs),
            manager_invocation_allowed=False,
            manager_invocation_ran=False,
            trigger_evaluation_allowed=False,
            trigger_evaluation_ran=False,
            should_trigger_reveal_allowed=False,
            should_trigger_reveal_called=False,
            reveal_order_slice_allowed=False,
            reveal_order_slice_called=False,
            coinbase_read_attempted=False,
            coinbase_read_succeeded=False,
            coinbase_rest_read_ran=False,
            coinbase_order_submitted=False,
            coinbase_order_cancel_submitted=False,
            active_placement_cancel_replace_ran=False,
            reconciliation_required=True,
            reconciliation_executed=False,
            order_state_mutated=False,
            lifecycle_state_mutated=False,
            exchange_state_mutated=False,
            live_exchange_submitted=False,
            live_coinbase_orders_ran=False,
            live_coinbase_read_ran=False,
            browser_authority="display_only",
            bff_authority="read_only_forward",
            detail=(
                "Persisted stealth reveal-trigger proof records are "
                "backend-owned evidence only. They do not evaluate triggers, "
                "call should_trigger_reveal, call reveal_order_slice, invoke "
                "managers, call Coinbase, execute reconciliation, or mutate "
                "stealth/order/exchange state."
            ),
        )

    def build_stealth_manager_invocation_policy(
        self,
        *,
        stealth_order_id: str,
    ) -> StealthManagerInvocationPolicyReadResponse:
        """Return persisted no-live manager-invocation policy evidence."""

        proofs = [
            _stealth_manager_policy_proof_item_from_record(record)
            for record in (
                self.stealth_manager_policy_proof_store.read_for_stealth_order_id(
                    stealth_order_id,
                    limit=20,
                )
            )
        ]
        latest_proof_id = proofs[0].manager_policy_proof_id if proofs else None
        missing_contracts = [
            "stealth_live_execution_service_policy",
            "stealth_live_execution_adapter_policy",
            "stealth_manager_invocation_execution_adapter",
            "stealth_post_write_reconciliation_execution_policy",
        ]
        return StealthManagerInvocationPolicyReadResponse(
            approved_phase_range=AUTONOMOUS_APPROVED_PHASE_RANGE,
            stealth_order_id=stealth_order_id,
            status=AdminApiGateStatus.BLOCKED,
            manager_policy_verified=False,
            persisted_proof_count=len(proofs),
            persisted_proofs=proofs,
            latest_manager_policy_proof_id=latest_proof_id,
            missing_contracts=missing_contracts,
            backend_owned=True,
            read_only=True,
            route_bound=True,
            proof_records_created=bool(proofs),
            manager_invocation_allowed=False,
            manager_invocation_ran=False,
            mutation_lock_policy_verified=False,
            exchange_reality_policy_verified=False,
            coinbase_read_attempted=False,
            coinbase_read_succeeded=False,
            coinbase_rest_read_ran=False,
            coinbase_order_submitted=False,
            coinbase_order_cancel_submitted=False,
            active_placement_cancel_replace_ran=False,
            reconciliation_required=True,
            reconciliation_executed=False,
            order_state_mutated=False,
            lifecycle_state_mutated=False,
            exchange_state_mutated=False,
            live_exchange_submitted=False,
            live_coinbase_orders_ran=False,
            live_coinbase_read_ran=False,
            browser_authority="display_only",
            bff_authority="read_only_forward",
            detail=(
                "Persisted stealth manager-invocation policy proof records are "
                "backend-owned evidence only. They do not invoke "
                "StealthOrderManager, call Coinbase, cancel or replace "
                "placements, execute reconciliation, or mutate "
                "stealth/order/exchange state."
            ),
        )

    def build_stealth_coinbase_exchange_submission_policy(
        self,
        *,
        stealth_order_id: str,
    ) -> StealthCoinbaseExchangeSubmissionPolicyReadResponse:
        """Return persisted no-live Coinbase exchange submission-policy evidence."""

        proofs = [
            _stealth_coinbase_exchange_policy_proof_item_from_record(record)
            for record in (
                self.stealth_coinbase_exchange_policy_proof_store.read_for_stealth_order_id(
                    stealth_order_id,
                    limit=20,
                )
            )
        ]
        latest_proof_id = (
            proofs[0].coinbase_exchange_policy_proof_id if proofs else None
        )
        missing_contracts = [
            "stealth_live_execution_service_policy",
            "stealth_live_execution_adapter_policy",
            "stealth_coinbase_exchange_submission_policy_resolver",
            "stealth_post_write_reconciliation_execution_policy",
        ]
        return StealthCoinbaseExchangeSubmissionPolicyReadResponse(
            approved_phase_range=AUTONOMOUS_APPROVED_PHASE_RANGE,
            stealth_order_id=stealth_order_id,
            status=AdminApiGateStatus.BLOCKED,
            exchange_submission_policy_verified=False,
            persisted_proof_count=len(proofs),
            persisted_proofs=proofs,
            latest_coinbase_exchange_policy_proof_id=latest_proof_id,
            missing_contracts=missing_contracts,
            backend_owned=True,
            read_only=True,
            route_bound=True,
            proof_records_created=bool(proofs),
            coinbase_submit_allowed=False,
            coinbase_cancel_allowed=False,
            live_coinbase_read_allowed=False,
            live_cap_verified=False,
            manager_invocation_ran=False,
            coinbase_read_attempted=False,
            coinbase_read_succeeded=False,
            coinbase_rest_read_ran=False,
            coinbase_order_submitted=False,
            coinbase_order_cancel_submitted=False,
            active_placement_cancel_replace_ran=False,
            reconciliation_required=True,
            reconciliation_executed=False,
            order_state_mutated=False,
            lifecycle_state_mutated=False,
            exchange_state_mutated=False,
            live_exchange_submitted=False,
            live_coinbase_orders_ran=False,
            live_coinbase_read_ran=False,
            browser_authority="display_only",
            bff_authority="read_only_forward",
            detail=(
                "Persisted stealth Coinbase exchange submission-policy proof "
                "records are backend-owned evidence only. They do not submit, "
                "cancel, or read Coinbase orders, invoke managers, execute "
                "reconciliation, or mutate stealth/order/exchange state."
            ),
        )

    def build_stealth_state_mutation_policy(
        self,
        *,
        stealth_order_id: str,
    ) -> StealthStateMutationPolicyReadResponse:
        """Return persisted no-live state-mutation policy evidence."""

        proofs = [
            _stealth_state_mutation_policy_item_from_record(record)
            for record in (
                self.stealth_state_mutation_policy_proof_store.read_for_stealth_order_id(
                    stealth_order_id,
                    limit=20,
                )
            )
        ]
        latest_proof_id = (
            proofs[0].state_mutation_policy_proof_id if proofs else None
        )
        missing_contracts = [
            "stealth_state_mutation_policy_resolver",
            "stealth_lifecycle_state_mutation_executor",
            "stealth_order_state_mutation_executor",
            "stealth_exchange_state_mutation_executor",
            "stealth_post_write_reconciliation_execution_policy",
        ]
        return StealthStateMutationPolicyReadResponse(
            approved_phase_range=AUTONOMOUS_APPROVED_PHASE_RANGE,
            stealth_order_id=stealth_order_id,
            status=AdminApiGateStatus.BLOCKED,
            state_mutation_policy_verified=False,
            persisted_proof_count=len(proofs),
            persisted_proofs=proofs,
            latest_state_mutation_policy_proof_id=latest_proof_id,
            missing_contracts=missing_contracts,
            backend_owned=True,
            read_only=True,
            route_bound=True,
            proof_records_created=bool(proofs),
            state_mutation_allowed=False,
            lifecycle_state_mutation_allowed=False,
            order_state_mutation_allowed=False,
            exchange_state_mutation_allowed=False,
            manager_invocation_allowed=False,
            manager_invocation_ran=False,
            reconciliation_plan_build_allowed=False,
            reconciliation_plan_built=False,
            reconciliation_execution_allowed=False,
            reconciliation_execution_ran=False,
            coinbase_read_attempted=False,
            coinbase_read_succeeded=False,
            coinbase_rest_read_ran=False,
            coinbase_order_submitted=False,
            coinbase_order_cancel_submitted=False,
            active_placement_cancel_replace_ran=False,
            reconciliation_required=True,
            reconciliation_executed=False,
            order_state_mutated=False,
            lifecycle_state_mutated=False,
            exchange_state_mutated=False,
            live_exchange_submitted=False,
            live_coinbase_orders_ran=False,
            live_coinbase_read_ran=False,
            browser_authority="display_only",
            bff_authority="read_only_forward",
            detail=(
                "Persisted stealth state-mutation policy proof records are "
                "backend-owned evidence only. They do not authorize or perform "
                "lifecycle, order, or exchange-state mutation, call Coinbase, "
                "invoke managers, cancel or replace placements, or execute "
                "reconciliation."
            ),
        )

    def build_stealth_post_write_reconciliation_execution_policy(
        self,
        *,
        stealth_order_id: str,
    ) -> StealthPostWriteReconciliationExecutionPolicyReadResponse:
        """Return persisted no-live post-write reconciliation policy evidence."""

        proofs = [
            _stealth_post_write_reconciliation_policy_item_from_record(record)
            for record in (
                self.stealth_post_write_reconciliation_policy_proof_store.read_for_stealth_order_id(
                    stealth_order_id,
                    limit=20,
                )
            )
        ]
        latest_proof_id = (
            proofs[0].post_write_reconciliation_policy_proof_id
            if proofs
            else None
        )
        missing_contracts = [
            "stealth_state_mutation_policy",
            "stealth_post_write_reconciliation_execution_adapter",
            "stealth_live_execution_service_policy",
            "stealth_live_execution_adapter_policy",
        ]
        return StealthPostWriteReconciliationExecutionPolicyReadResponse(
            approved_phase_range=AUTONOMOUS_APPROVED_PHASE_RANGE,
            stealth_order_id=stealth_order_id,
            status=AdminApiGateStatus.BLOCKED,
            post_write_reconciliation_execution_policy_verified=False,
            persisted_proof_count=len(proofs),
            persisted_proofs=proofs,
            latest_post_write_reconciliation_policy_proof_id=latest_proof_id,
            missing_contracts=missing_contracts,
            backend_owned=True,
            read_only=True,
            route_bound=True,
            proof_records_created=bool(proofs),
            post_write_reconciliation_execution_allowed=False,
            route_bound_reconciliation_plan_required=True,
            execution_journal_required=True,
            reconciliation_verification_required=True,
            safe_reconciliation_chain_verified=False,
            manager_invocation_allowed=False,
            manager_invocation_ran=False,
            reconciliation_plan_build_allowed=False,
            reconciliation_plan_built=False,
            reconciliation_execution_allowed=False,
            reconciliation_execution_ran=False,
            coinbase_read_attempted=False,
            coinbase_read_succeeded=False,
            coinbase_rest_read_ran=False,
            coinbase_order_submitted=False,
            coinbase_order_cancel_submitted=False,
            active_placement_cancel_replace_ran=False,
            reconciliation_required=True,
            reconciliation_executed=False,
            order_state_mutated=False,
            lifecycle_state_mutated=False,
            exchange_state_mutated=False,
            live_exchange_submitted=False,
            live_coinbase_orders_ran=False,
            live_coinbase_read_ran=False,
            browser_authority="display_only",
            bff_authority="read_only_forward",
            detail=(
                "Persisted stealth post-write reconciliation execution-policy "
                "records are backend-owned evidence only. They do not execute "
                "reconciliation, call Coinbase, invoke managers, cancel or "
                "replace placements, satisfy state-mutation policy, or mutate "
                "stealth/order/exchange state."
            ),
        )

    def build_stealth_reconciliation_proof(
        self,
        *,
        stealth_order_id: str,
    ) -> StealthReconciliationProofReadResponse:
        """Return persisted no-live reconciliation proof evidence."""

        proofs = [
            _stealth_reconciliation_proof_item_from_record(record)
            for record in (
                self.stealth_reconciliation_proof_store.read_for_stealth_order_id(
                    stealth_order_id,
                    limit=20,
                )
            )
        ]
        latest_proof_id = proofs[0].reconciliation_proof_id if proofs else None
        missing_contracts = [
            "stealth_reconciliation_executor",
            "stealth_reconciliation_completion_proof",
            "stealth_reconciliation_post_write_reconciliation_proof",
        ]
        return StealthReconciliationProofReadResponse(
            approved_phase_range=AUTONOMOUS_APPROVED_PHASE_RANGE,
            stealth_order_id=stealth_order_id,
            status=AdminApiGateStatus.BLOCKED,
            reconciliation_proof_verified=False,
            persisted_proof_count=len(proofs),
            persisted_proofs=proofs,
            latest_reconciliation_proof_id=latest_proof_id,
            missing_contracts=missing_contracts,
            backend_owned=True,
            read_only=True,
            route_bound=True,
            proof_records_created=bool(proofs),
            manager_invocation_allowed=False,
            manager_invocation_ran=False,
            reconciliation_plan_build_allowed=False,
            reconciliation_plan_built=False,
            reconciliation_execution_allowed=False,
            reconciliation_execution_ran=False,
            coinbase_read_attempted=False,
            coinbase_read_succeeded=False,
            coinbase_rest_read_ran=False,
            coinbase_order_submitted=False,
            coinbase_order_cancel_submitted=False,
            active_placement_cancel_replace_ran=False,
            reconciliation_required=True,
            reconciliation_executed=False,
            order_state_mutated=False,
            lifecycle_state_mutated=False,
            exchange_state_mutated=False,
            live_exchange_submitted=False,
            live_coinbase_orders_ran=False,
            live_coinbase_read_ran=False,
            browser_authority="display_only",
            bff_authority="read_only_forward",
            detail=(
                "Persisted stealth reconciliation proof records are "
                "backend-owned evidence only. They do not execute "
                "reconciliation, invoke managers, call Coinbase, cancel or "
                "replace placements, or mutate stealth/order/exchange state."
            ),
        )

    def build_stealth_cancel_replace_proof(
        self,
        *,
        stealth_order_id: str,
    ) -> StealthCancelReplaceProofReadResponse:
        """Return persisted no-live cancel/replace proof evidence."""

        proofs = [
            _stealth_cancel_replace_proof_item_from_record(record)
            for record in (
                self.stealth_cancel_replace_proof_store.read_for_stealth_order_id(
                    stealth_order_id,
                    limit=20,
                )
            )
        ]
        latest_proof_id = proofs[0].cancel_replace_proof_id if proofs else None
        missing_contracts = [
            "stealth_cancel_replace_executor",
            "stealth_cancel_replace_live_cancel_proof",
            "stealth_cancel_replace_post_write_reconciliation_proof",
        ]
        return StealthCancelReplaceProofReadResponse(
            approved_phase_range=AUTONOMOUS_APPROVED_PHASE_RANGE,
            stealth_order_id=stealth_order_id,
            status=AdminApiGateStatus.BLOCKED,
            cancel_replace_proof_verified=False,
            persisted_proof_count=len(proofs),
            persisted_proofs=proofs,
            latest_cancel_replace_proof_id=latest_proof_id,
            missing_contracts=missing_contracts,
            backend_owned=True,
            read_only=True,
            route_bound=True,
            proof_records_created=bool(proofs),
            manager_invocation_allowed=False,
            manager_invocation_ran=False,
            cancel_replace_plan_build_allowed=False,
            cancel_replace_plan_built=False,
            active_placement_cancel_replace_allowed=False,
            active_placement_cancel_replace_ran=False,
            coinbase_read_attempted=False,
            coinbase_read_succeeded=False,
            coinbase_rest_read_ran=False,
            coinbase_order_submitted=False,
            coinbase_order_cancel_submitted=False,
            reconciliation_required=True,
            reconciliation_executed=False,
            order_state_mutated=False,
            lifecycle_state_mutated=False,
            exchange_state_mutated=False,
            live_exchange_submitted=False,
            live_coinbase_orders_ran=False,
            live_coinbase_read_ran=False,
            browser_authority="display_only",
            bff_authority="read_only_forward",
            detail=(
                "Persisted stealth cancel/replace proof records are "
                "backend-owned evidence only. They do not invoke managers, "
                "call Coinbase, cancel or replace active placements, mutate "
                "lifecycle/order/exchange state, or execute reconciliation."
            ),
        )

    def build_stealth_post_write_reconciliation_proof(
        self,
        *,
        stealth_order_id: str,
    ) -> StealthPostWriteReconciliationProofReadResponse:
        """Return persisted no-live post-write reconciliation proof evidence."""

        proof_records = (
            self.stealth_post_write_reconciliation_proof_store.read_for_stealth_order_id(
                stealth_order_id,
                limit=20,
            )
        )
        proofs = [
            _stealth_post_write_reconciliation_proof_item_from_record(record)
            for record in proof_records
        ]
        journal_records = (
            self.stealth_post_write_execution_journal_store.read_for_stealth_order_id(
                stealth_order_id,
                limit=100,
            )
        )
        matching_journal_accepted = any(
            is_safe_stealth_post_write_reconciliation_proof_record(proof_record)
            and is_safe_stealth_post_write_execution_journal_record(journal_record)
            and post_write_execution_journal_matches_proof(
                journal_record,
                proof_record,
            )
            for proof_record in proof_records
            for journal_record in journal_records
        )
        verification_records = (
            self.stealth_post_write_reconciliation_verification_store.read_for_stealth_order_id(
                stealth_order_id,
                limit=100,
            )
        )
        matching_verifications = (
            _matching_safe_stealth_post_write_reconciliation_verifications(
                proof_records=proof_records,
                journal_records=journal_records,
                verification_records=verification_records,
            )
        )
        latest_proof_id = (
            proofs[0].post_write_reconciliation_proof_id if proofs else None
        )
        latest_verification_id = (
            matching_verifications[0].reconciliation_verification_id
            if matching_verifications
            else None
        )
        missing_contracts = [
            "stealth_post_write_reconciliation_execution_executor",
        ]
        if not matching_verifications:
            missing_contracts.insert(
                0,
                "stealth_post_write_reconciliation_verification_record",
            )
        proof_records_created = bool(proofs)
        return StealthPostWriteReconciliationProofReadResponse(
            approved_phase_range=AUTONOMOUS_APPROVED_PHASE_RANGE,
            stealth_order_id=stealth_order_id,
            status=AdminApiGateStatus.BLOCKED,
            post_write_reconciliation_verified=bool(matching_verifications),
            persisted_proof_count=len(proofs),
            persisted_proofs=proofs,
            latest_post_write_reconciliation_proof_id=latest_proof_id,
            missing_contracts=missing_contracts,
            backend_owned=True,
            read_only=True,
            route_bound=True,
            proof_records_created=proof_records_created,
            manager_invocation_allowed=False,
            manager_invocation_ran=False,
            route_bound_reconciliation_plan_recorded=proof_records_created,
            reconciliation_plan_build_allowed=False,
            reconciliation_plan_built=False,
            execution_journal_required=True,
            execution_journal_accepted=matching_journal_accepted,
            reconciliation_verification_required=True,
            reconciliation_verification_count=len(matching_verifications),
            latest_reconciliation_verification_id=latest_verification_id,
            completion_proof_required=True,
            completion_proof_recorded=proof_records_created,
            reconciliation_execution_allowed=False,
            reconciliation_execution_ran=False,
            coinbase_read_attempted=False,
            coinbase_read_succeeded=False,
            coinbase_rest_read_ran=False,
            coinbase_order_submitted=False,
            coinbase_order_cancel_submitted=False,
            active_placement_cancel_replace_ran=False,
            reconciliation_required=True,
            reconciliation_executed=False,
            order_state_mutated=False,
            lifecycle_state_mutated=False,
            exchange_state_mutated=False,
            live_exchange_submitted=False,
            live_coinbase_orders_ran=False,
            live_coinbase_read_ran=False,
            browser_authority="display_only",
            bff_authority="read_only_forward",
            detail=(
                "Persisted stealth post-write reconciliation proof records are "
                "backend-owned evidence only. They record reviewed plan, "
                "journal, and completion references. Only the exact safe proof, "
                "accepted journal, and verification chain may resolve "
                "post_write_reconciliation prerequisite evidence. The readback "
                "does not invoke managers, call Coinbase, mutate lifecycle/"
                "order/exchange state, or execute reconciliation."
            ),
        )

    def build_stealth_post_write_execution_journals(
        self,
        *,
        stealth_order_id: str,
    ) -> StealthPostWriteExecutionJournalReadResponse:
        """Return persisted no-live post-write execution-journal acceptances."""

        records = (
            self.stealth_post_write_execution_journal_store.read_for_stealth_order_id(
                stealth_order_id,
                limit=20,
            )
        )
        acceptances = [
            _stealth_post_write_execution_journal_item_from_record(record)
            for record in records
        ]
        proof_records = (
            self.stealth_post_write_reconciliation_proof_store.read_for_stealth_order_id(
                stealth_order_id,
                limit=100,
            )
        )
        matching_journal_records = [
            journal_record
            for proof_record in proof_records
            for journal_record in records
            if is_safe_stealth_post_write_reconciliation_proof_record(
                proof_record
            )
            and is_safe_stealth_post_write_execution_journal_record(
                journal_record
            )
            and post_write_execution_journal_matches_proof(
                journal_record,
                proof_record,
            )
        ]
        safe_acceptance_count = len({
            record.execution_journal_acceptance_id
            for record in matching_journal_records
        })
        verification_records = (
            self.stealth_post_write_reconciliation_verification_store.read_for_stealth_order_id(
                stealth_order_id,
                limit=100,
            )
        )
        matching_verifications = (
            _matching_safe_stealth_post_write_reconciliation_verifications(
                proof_records=proof_records,
                journal_records=records,
                verification_records=verification_records,
            )
        )
        latest_acceptance_id = (
            acceptances[0].execution_journal_acceptance_id
            if acceptances
            else None
        )
        latest_proof_id = (
            acceptances[0].post_write_reconciliation_proof_id
            if acceptances
            else None
        )
        latest_verification_id = (
            matching_verifications[0].reconciliation_verification_id
            if matching_verifications
            else None
        )
        missing_contracts = [
            "stealth_post_write_reconciliation_execution_executor",
        ]
        if not matching_verifications:
            missing_contracts.insert(
                0,
                "stealth_post_write_reconciliation_verification_record",
            )
        return StealthPostWriteExecutionJournalReadResponse(
            approved_phase_range=AUTONOMOUS_APPROVED_PHASE_RANGE,
            stealth_order_id=stealth_order_id,
            status=AdminApiGateStatus.BLOCKED,
            persisted_acceptance_count=len(acceptances),
            accepted_execution_journal_count=safe_acceptance_count,
            persisted_acceptances=acceptances,
            latest_execution_journal_acceptance_id=latest_acceptance_id,
            latest_post_write_reconciliation_proof_id=latest_proof_id,
            missing_contracts=missing_contracts,
            backend_owned=True,
            read_only=True,
            route_bound=True,
            execution_journal_required=True,
            execution_journal_accepted=safe_acceptance_count > 0,
            reconciliation_verification_required=True,
            reconciliation_verification_count=len(matching_verifications),
            latest_reconciliation_verification_id=latest_verification_id,
            post_write_reconciliation_verified=bool(matching_verifications),
            manager_invocation_allowed=False,
            manager_invocation_ran=False,
            reconciliation_execution_allowed=False,
            reconciliation_execution_ran=False,
            coinbase_read_attempted=False,
            coinbase_read_succeeded=False,
            coinbase_rest_read_ran=False,
            coinbase_order_submitted=False,
            coinbase_order_cancel_submitted=False,
            active_placement_cancel_replace_ran=False,
            reconciliation_required=True,
            reconciliation_executed=False,
            order_state_mutated=False,
            lifecycle_state_mutated=False,
            exchange_state_mutated=False,
            live_exchange_submitted=False,
            live_coinbase_orders_ran=False,
            live_coinbase_read_ran=False,
            browser_authority="display_only",
            bff_authority="read_only_forward",
            detail=(
                "Persisted stealth post-write execution-journal acceptances are "
                "backend-owned append-only evidence only. They accept a journal "
                "reference for a stored proof context. They require a matching "
                "verification before post_write_reconciliation prerequisite "
                "evidence can resolve, and do not invoke managers, call "
                "Coinbase, mutate lifecycle/order/exchange state, or execute "
                "reconciliation."
            ),
        )

    def build_stealth_post_write_reconciliation_verifications(
        self,
        *,
        stealth_order_id: str,
    ) -> StealthPostWriteReconciliationVerificationReadResponse:
        """Return persisted no-live post-write reconciliation verifications."""

        records = (
            self.stealth_post_write_reconciliation_verification_store.read_for_stealth_order_id(
                stealth_order_id,
                limit=20,
            )
        )
        proof_records = (
            self.stealth_post_write_reconciliation_proof_store.read_for_stealth_order_id(
                stealth_order_id,
                limit=100,
            )
        )
        journal_records = (
            self.stealth_post_write_execution_journal_store.read_for_stealth_order_id(
                stealth_order_id,
                limit=100,
            )
        )
        matching_verifications = (
            _matching_safe_stealth_post_write_reconciliation_verifications(
                proof_records=proof_records,
                journal_records=journal_records,
                verification_records=records,
            )
        )
        matching_verification_ids = {
            record.reconciliation_verification_id
            for record in matching_verifications
        }
        verifications = [
            _stealth_post_write_reconciliation_verification_item_from_record(
                record,
                chain_verified=(
                    record.reconciliation_verification_id
                    in matching_verification_ids
                ),
            )
            for record in records
        ]
        latest_matching_verification = (
            matching_verifications[0] if matching_verifications else None
        )
        safe_verification_count = len(matching_verifications)
        latest_verification_id = (
            latest_matching_verification.reconciliation_verification_id
            if latest_matching_verification is not None
            else None
        )
        latest_acceptance_id = (
            latest_matching_verification.execution_journal_acceptance_id
            if latest_matching_verification is not None
            else None
        )
        latest_proof_id = (
            latest_matching_verification.post_write_reconciliation_proof_id
            if latest_matching_verification is not None
            else None
        )
        missing_contracts = [
            "stealth_post_write_reconciliation_execution_executor",
        ]
        if not matching_verifications:
            missing_contracts.insert(
                0,
                "safe_matching_post_write_reconciliation_verification_chain",
            )
        return StealthPostWriteReconciliationVerificationReadResponse(
            approved_phase_range=AUTONOMOUS_APPROVED_PHASE_RANGE,
            stealth_order_id=stealth_order_id,
            status=AdminApiGateStatus.BLOCKED,
            persisted_verification_count=len(verifications),
            verified_post_write_reconciliation_count=safe_verification_count,
            persisted_verifications=verifications,
            latest_reconciliation_verification_id=latest_verification_id,
            latest_execution_journal_acceptance_id=latest_acceptance_id,
            latest_post_write_reconciliation_proof_id=latest_proof_id,
            missing_contracts=missing_contracts,
            backend_owned=True,
            read_only=True,
            route_bound=True,
            execution_journal_required=True,
            execution_journal_accepted=safe_verification_count > 0,
            reconciliation_verification_required=True,
            post_write_reconciliation_verified=safe_verification_count > 0,
            manager_invocation_allowed=False,
            manager_invocation_ran=False,
            reconciliation_execution_allowed=False,
            reconciliation_execution_ran=False,
            coinbase_read_attempted=False,
            coinbase_read_succeeded=False,
            coinbase_rest_read_ran=False,
            coinbase_order_submitted=False,
            coinbase_order_cancel_submitted=False,
            active_placement_cancel_replace_ran=False,
            reconciliation_required=True,
            reconciliation_executed=False,
            order_state_mutated=False,
            lifecycle_state_mutated=False,
            exchange_state_mutated=False,
            live_exchange_submitted=False,
            live_coinbase_orders_ran=False,
            live_coinbase_read_ran=False,
            browser_authority="display_only",
            bff_authority="read_only_forward",
            detail=(
                "Persisted stealth post-write reconciliation verifications are "
                "backend-owned append-only evidence only. They verify a safe "
                "proof plus accepted journal chain and may resolve only "
                "post_write_reconciliation prerequisite evidence. They do not "
                "invoke managers, call Coinbase, mutate lifecycle/order/"
                "exchange state, execute reconciliation, or satisfy live "
                "execution service/adapter prerequisites."
            ),
        )

    def build_stealth_command_suite(self) -> StealthCommandSuiteResponse:
        """Return read-only M55 stealth command-suite readiness evidence."""

        live_enablement = self.build_live_enablement()
        live_paths = {
            (path.method, path.route): path
            for path in live_enablement.paths
            if path.module_id in {"stealth_orders", "movement_repricing"}
        }
        inventory_by_surface = {
            item.surface: item for item in ADMIN_API_ROUTE_INVENTORY
        }
        proof_route_specs = (
            (
                AdminApiLivePreflightCategory.APPROVAL,
                "POST /api/v1/admin/approvals/requests",
                None,
                [
                    "README.admin-api.md",
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/examples/admin-api.md",
                ],
                (
                    "Create a backend-owned approval request bound to the exact "
                    "stealth route, method, actor, idempotency key, payload hash, "
                    "and command identity."
                ),
            ),
            (
                AdminApiLivePreflightCategory.APPROVAL,
                "POST /api/v1/admin/approvals/requests/{approval_request_id}/decisions",
                "approval_request_id",
                [
                    "README.admin-api.md",
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/examples/admin-api.md",
                ],
                (
                    "Record the backend approval decision. Browser approval "
                    "remains insufficient and does not execute the stealth command."
                ),
            ),
            (
                AdminApiLivePreflightCategory.AUDIT,
                "POST /api/v1/admin/admission-audits",
                None,
                [
                    "README.admission-audits.md",
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/examples/admission-audits.md",
                ],
                (
                    "Append exact admission audit evidence for the route-bound "
                    "stealth command. The writer cannot mark live admission allowed."
                ),
            ),
            (
                AdminApiLivePreflightCategory.CAP_GUARD,
                "POST /api/v1/admin/cap-guard/decisions",
                None,
                [
                    "README.cap-guard-decisions.md",
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/examples/cap-guard-decisions.md",
                ],
                (
                    "Record backend cap/guard evidence. The browser and BFF "
                    "must not evaluate stealth lifecycle, active placement, "
                    "or exchange-reality predicates."
                ),
            ),
            (
                AdminApiLivePreflightCategory.RECONCILIATION,
                "POST /api/v1/admin/reconciliation/plans",
                None,
                [
                    "README.reconciliation-plans.md",
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/examples/reconciliation-plans.md",
                ],
                (
                    "Record backend reconciliation requirements. This does not "
                    "execute reconciliation, cancel active placements, or mutate "
                    "stealth/order/exchange state."
                ),
            ),
            (
                AdminApiLivePreflightCategory.LIFECYCLE_WRITE_GUARD,
                (
                    "POST /api/v1/stealth/orders/{stealth_order_id}/"
                    "lifecycle-write-guard-proofs"
                ),
                "stealth_order_id",
                [
                    "README.admin-api.md",
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/STEALTH_ORDER_READS.md",
                ],
                (
                    "Record backend-owned lifecycle-write guard proof for a "
                    "stealth create command. This does not invoke the stealth "
                    "manager, write stealth/order_parent rows, dispatch "
                    "lifecycle events, call Coinbase, or execute reconciliation."
                ),
            ),
        )

        def proof_routes_for_command(
            command_identity_key: str,
            *,
            mutation_family: AdminApiMutationFamilyType | None = None,
            include_lifecycle_write_guard: bool = False,
        ) -> list[StealthCommandSuiteProofRouteItem]:
            proof_routes: list[StealthCommandSuiteProofRouteItem] = []
            for (
                gate,
                surface,
                route_identity_key,
                documentation_refs,
                detail,
            ) in proof_route_specs:
                if (
                    gate == AdminApiLivePreflightCategory.LIFECYCLE_WRITE_GUARD
                    and not include_lifecycle_write_guard
                ):
                    continue
                item = inventory_by_surface[surface]
                method, route = _surface_method_and_path(item.surface)
                proof_routes.append(
                    StealthCommandSuiteProofRouteItem(
                        gate=gate,
                        route=route,
                        method=method,
                        action_class=item.action_class,
                        required_permission=item.permission,
                        shared_method=item.shared_method,
                        status=AdminApiGateStatus.BLOCKED,
                        required=True,
                        blocking=True,
                        identity_key=(
                            command_identity_key
                            if route_identity_key is None
                            else route_identity_key
                        ),
                        command_identity_key=command_identity_key,
                        backend_owned=True,
                        route_bound=True,
                        browser_authority="display_only",
                        bff_authority="forward_only_no_execution",
                        documentation_refs=list(documentation_refs),
                        detail=detail,
                    )
                )
            if mutation_family is not None:
                proof_routes.extend(
                    build_stealth_command_specific_proof_route_contracts(
                        mutation_family=mutation_family,
                        command_identity_key=command_identity_key,
                    )
                )
            return proof_routes

        command_metadata = {
            AdminApiMutationFamilyType.STEALTH_CREATE: {
                "surface": "POST /api/v1/stealth/orders",
                "identity_key": "stealth_order_id",
                "exchange_truth_required": False,
                "active_placement_evidence_required": False,
                "backend_contract_refs": [
                    "api/v1/routes/stealth.py::create_stealth_order",
                    "application/admin_api/command_service.py::create_stealth_order",
                    "bridges/stealth_order_bridge.py",
                    "core/stealth_order_manager.py::create_stealth_order",
                ],
                "frontend_contract_refs": [
                    "src/shared/api/contracts/backendApiClient.ts::createStealthOrder",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                "documentation_refs": [
                    "README.admin-api.md",
                    "docs/agents/INVARIANTS.md",
                    "docs/STEALTH_ORDER_READS.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                "detail": (
                    "Stealth create is route-bound by stealth_order_id and "
                    "currently live-disabled. The contract records the proposed "
                    "hidden-order identity and request evidence, but it does "
                    "not invoke StealthOrderManager or mutate local lifecycle "
                    "state until backend lifecycle-write gates are complete."
                ),
            },
            AdminApiMutationFamilyType.STEALTH_CANCEL: {
                "surface": "POST /api/v1/stealth/orders/{stealth_order_id}/cancel",
                "identity_key": "stealth_order_id",
                "exchange_truth_required": True,
                "active_placement_evidence_required": True,
                "backend_contract_refs": [
                    "api/v1/routes/stealth.py::cancel_stealth_order_by_stealth_order_id",
                    "application/admin_api/command_service.py::cancel_stealth_order_by_stealth_order_id",
                    "bridges/stealth_order_bridge.py",
                    "core/stealth_order_manager.py",
                ],
                "frontend_contract_refs": [
                    "src/shared/api/contracts/backendApiClient.ts::cancelStealthOrder",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                "documentation_refs": [
                    "README.admin-api.md",
                    "docs/agents/INVARIANTS.md",
                    "docs/STEALTH_ORDER_READS.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                "detail": (
                    "Stealth cancel is route-bound by stealth_order_id and "
                    "currently live-disabled. Future execution must account for "
                    "any active Coinbase placement before local state changes."
                ),
            },
            AdminApiMutationFamilyType.STEALTH_REVEAL: {
                "surface": "POST /api/v1/stealth/orders/{stealth_order_id}/reveal",
                "identity_key": "stealth_order_id",
                "exchange_truth_required": True,
                "active_placement_evidence_required": False,
                "backend_contract_refs": [
                    "api/v1/routes/stealth.py::reveal_stealth_order_by_stealth_order_id",
                    "application/admin_api/command_service.py::reveal_stealth_order_by_stealth_order_id",
                    "bridges/stealth_order_bridge.py",
                    "core/stealth_order_manager.py::reveal_order_slice",
                ],
                "frontend_contract_refs": [
                    "src/shared/api/contracts/backendApiClient.ts::revealStealthOrderByStealthOrderId",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                "documentation_refs": [
                    "README.admin-api.md",
                    "docs/agents/INVARIANTS.md",
                    "docs/STEALTH_ORDER_READS.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                "detail": (
                    "Stealth reveal is route-bound by stealth_order_id and "
                    "currently live-disabled. Future execution must prove trigger "
                    "evidence, submit through the existing reveal path, and "
                    "reconcile any Coinbase placement before local lifecycle "
                    "state changes."
                ),
            },
            AdminApiMutationFamilyType.STEALTH_MOVE: {
                "surface": "POST /api/v1/stealth/orders/{stealth_order_id}/move",
                "identity_key": "stealth_order_id",
                "exchange_truth_required": True,
                "active_placement_evidence_required": True,
                "backend_contract_refs": [
                    "api/v1/routes/stealth.py::move_stealth_order_by_stealth_order_id",
                    "application/admin_api/command_service.py::move_stealth_order_by_stealth_order_id",
                    "bridges/stealth_order_bridge.py",
                    "core/stealth_order_manager.py::build_stealth_move_plan",
                    "core/stealth_order_manager.py::execute_stealth_move",
                ],
                "frontend_contract_refs": [
                    "src/shared/api/contracts/backendApiClient.ts::moveStealthOrderByStealthOrderId",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                "documentation_refs": [
                    "README.admin-api.md",
                    "docs/agents/INVARIANTS.md",
                    "docs/STEALTH_ORDER_READS.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                "detail": (
                    "Stealth move is route-bound by stealth_order_id and "
                    "currently live-disabled. Future execution must use the "
                    "existing move plan and execute path, prove mutation-claim "
                    "ownership, cancel/replace any active Coinbase placement, "
                    "and reconcile exchange reality before local lifecycle state "
                    "changes."
                ),
            },
            AdminApiMutationFamilyType.STEALTH_RECOVERY: {
                "surface": "POST /api/v1/stealth/orders/{stealth_order_id}/recovery",
                "identity_key": "stealth_order_id",
                "exchange_truth_required": True,
                "active_placement_evidence_required": True,
                "backend_contract_refs": [
                    "api/v1/routes/stealth.py::recover_stealth_order_by_stealth_order_id",
                    "application/admin_api/command_service.py::recover_stealth_order_by_stealth_order_id",
                    "bridges/stealth_order_bridge.py",
                    "core/stealth_order_manager.py",
                ],
                "frontend_contract_refs": [
                    "src/shared/api/contracts/backendApiClient.ts::recoverStealthOrderByStealthOrderId",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                "documentation_refs": [
                    "README.admin-api.md",
                    "docs/agents/INVARIANTS.md",
                    "docs/STEALTH_ORDER_READS.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                "detail": (
                    "Stealth recovery is route-bound by stealth_order_id and "
                    "currently live-disabled. Future execution must prove "
                    "active-placement exchange truth, repair/rollback proof, "
                    "audit, approval, cap/guard, and reconciliation before any "
                    "local lifecycle recovery state changes."
                ),
            },
            AdminApiMutationFamilyType.STEALTH_RECONCILIATION: {
                "surface": "POST /api/v1/stealth/orders/{stealth_order_id}/reconciliation",
                "identity_key": "stealth_order_id",
                "exchange_truth_required": True,
                "active_placement_evidence_required": True,
                "backend_contract_refs": [
                    "api/v1/routes/stealth.py::reconcile_stealth_order_by_stealth_order_id",
                    "application/admin_api/command_service.py::reconcile_stealth_order_by_stealth_order_id",
                    "application/admin_api/reconciliation.py",
                    "bridges/stealth_order_bridge.py",
                ],
                "frontend_contract_refs": [
                    "src/shared/api/contracts/backendApiClient.ts::reconcileStealthOrderByStealthOrderId",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                "documentation_refs": [
                    "README.reconciliation-plans.md",
                    "docs/agents/INVARIANTS.md",
                    "docs/STEALTH_ORDER_READS.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                "detail": (
                    "Stealth reconciliation is route-bound by stealth_order_id "
                    "and currently live-disabled. Future execution must prove "
                    "plan/proof evidence, active-placement exchange truth, "
                    "audit, approval, cap/guard, lifecycle repair policy, and "
                    "post-execution proof before any state transition."
                ),
            },
            AdminApiMutationFamilyType.MOVEMENT_REPRICE: {
                "surface": "POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice",
                "identity_key": "stealth_order_id",
                "exchange_truth_required": True,
                "active_placement_evidence_required": True,
                "backend_contract_refs": [
                    "api/v1/routes/movement_repricing.py::reprice_stealth_order_by_stealth_order_id",
                    "application/admin_api/command_service.py::reprice_stealth_order_by_stealth_order_id",
                    "bridges/stealth_order_bridge.py",
                    "core/stealth_order_manager.py",
                ],
                "frontend_contract_refs": [
                    "src/shared/api/contracts/backendApiClient.ts::repriceStealthOrder",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                "documentation_refs": [
                    "README.movement-repricing.md",
                    "docs/agents/INVARIANTS.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                "detail": (
                    "Stealth reprice is exposed through the movement/repricing "
                    "module as a live-disabled cancel/replace-shaped command. "
                    "It must not clear cooldowns, move live revealed placements, "
                    "or bypass mutation claims."
                ),
            },
        }
        read_routes = [
            item.surface
            for item in ADMIN_API_ROUTE_INVENTORY
            if item.action_class == AdminApiActionClass.READ_ONLY
            and item.module_id in {"stealth_orders", "movement_repricing"}
            and (
                item.module_id == "stealth_orders"
                or "stealth/{stealth_order_id}" in item.surface
            )
        ]

        commands: list[StealthCommandSuiteCommandItem] = []
        for mutation_family, metadata in command_metadata.items():
            inventory_item = inventory_by_surface[str(metadata["surface"])]
            method, route = _surface_method_and_path(inventory_item.surface)
            live_path = live_paths.get((method, route))
            if live_path is None:
                missing_gate_chain = [
                    "approval_snapshot",
                    "admission_audit",
                    "cap_guard_decision",
                    "reconciliation_plan",
                    "live_execution_disabled",
                ]
                if metadata.get("active_placement_evidence_required", True):
                    missing_gate_chain.insert(4, "active_placement_exchange_truth")
                else:
                    missing_gate_chain.insert(4, "lifecycle_write_guard")
                readiness_preconditions = []
                live_execution_status = AdminApiLiveExecutionStatus.LIVE_DISABLED
                live_adapter_configured = False
            else:
                missing_gate_chain = [
                    precondition.precondition.value
                    for precondition in live_path.readiness_preconditions
                    if precondition.blocking
                ]
                if (
                    metadata.get("active_placement_evidence_required", True)
                    and "active_placement_exchange_truth" not in missing_gate_chain
                ):
                    missing_gate_chain.append("active_placement_exchange_truth")
                if (
                    not metadata.get("active_placement_evidence_required", True)
                    and "lifecycle_write_guard" not in missing_gate_chain
                ):
                    missing_gate_chain.append("lifecycle_write_guard")
                readiness_preconditions = list(live_path.readiness_preconditions)
                live_execution_status = live_path.status
                live_adapter_configured = live_path.live_execution_adapter.configured
            required_gate_chain = [
                "idempotency",
                "operator_intent",
                "payload_hash",
                "approval_snapshot",
                "approval_store_contract",
                "admission_audit",
                "cap_guard_decision",
                "reconciliation_plan",
                "mutation_claim",
            ]
            if metadata.get("active_placement_evidence_required", True):
                required_gate_chain.append("active_placement_exchange_truth")
            else:
                required_gate_chain.append("lifecycle_write_guard")
            required_gate_chain.extend([
                "live_execution_adapter",
                "live_execution_service",
                "post_live_reconciliation",
            ])
            commands.append(
                StealthCommandSuiteCommandItem(
                    mutation_family=mutation_family,
                    route=route,
                    method=method,
                    identity_key=str(metadata["identity_key"]),
                    action_class=inventory_item.action_class,
                    required_permission=inventory_item.permission,
                    shared_method=inventory_item.shared_method,
                    status=AdminApiGateStatus.BLOCKED,
                    live_execution_status=live_execution_status,
                    live_enabled=False,
                    live_eligible=False,
                    executable=False,
                    live_adapter_configured=live_adapter_configured,
                    approval_required=True,
                    cap_guard_required=True,
                    admission_audit_required=True,
                    reconciliation_required=True,
                    idempotency_required=True,
                    operator_intent_required=True,
                    payload_hash_required=True,
                    exchange_truth_required=bool(
                        metadata.get("exchange_truth_required", True)
                    ),
                    active_placement_evidence_required=bool(
                        metadata.get("active_placement_evidence_required", True)
                    ),
                    backend_owned=True,
                    route_bound=True,
                    browser_authority="display_only",
                    bff_authority="forward_only_no_execution",
                    product_scope="stealth command scope",
                    stealth_rule_boundary=_enterprise_module_spot_boundary(
                        "stealth_orders"
                    ),
                    required_gate_chain=required_gate_chain,
                    missing_gate_chain=missing_gate_chain,
                    readiness_preconditions=readiness_preconditions,
                    readiness_precondition_count=len(readiness_preconditions),
                    blocking_readiness_precondition_count=sum(
                        1
                        for precondition in readiness_preconditions
                        if precondition.blocking
                    ),
                    passed_readiness_precondition_count=sum(
                        1
                        for precondition in readiness_preconditions
                        if precondition.status == AdminApiGateStatus.PASSED
                    ),
                    backend_contract_refs=list(metadata["backend_contract_refs"]),
                    frontend_contract_refs=list(metadata["frontend_contract_refs"]),
                    documentation_refs=list(metadata["documentation_refs"]),
                    proof_routes=proof_routes_for_command(
                        str(metadata["identity_key"]),
                        mutation_family=mutation_family,
                        include_lifecycle_write_guard=(
                            mutation_family
                            in {
                                AdminApiMutationFamilyType.STEALTH_CREATE,
                                AdminApiMutationFamilyType.STEALTH_REVEAL,
                            }
                        ),
                    ),
                    evidence=[
                        "Derived from ADMIN_API_ROUTE_INVENTORY and live-enablement readiness evidence.",
                        "Stealth command execution must use the existing stealth manager, bridge, mutation claims, and exchange-reality reconciliation path.",
                        "No browser, BFF, route-local, or Coinbase execution authority is added.",
                        "Exchange order ids are evidence only; stealth_order_id remains the command identity for these routes.",
                    ],
                    detail=str(metadata["detail"]),
                )
            )

        stealth_boundary = _enterprise_module_spot_boundary("stealth_orders")
        gap_required_gate_chain = [
            "route_inventory_contract",
            "idempotency",
            "operator_intent",
            "payload_hash",
            "approval_snapshot",
            "admission_audit",
            "cap_guard_decision",
            "reconciliation_plan",
            "mutation_claim",
            "active_placement_exchange_truth",
            "live_execution_adapter",
            "live_execution_service",
            "post_live_reconciliation",
        ]
        stealth_create_gate_chain = [
            "route_inventory_contract",
            "idempotency",
            "operator_intent",
            "payload_hash",
            "approval_snapshot",
            "admission_audit",
            "cap_guard_decision",
            "reconciliation_plan",
            "mutation_claim",
            "lifecycle_write_guard",
            "live_execution_adapter",
            "live_execution_service",
            "post_write_reconciliation",
        ]
        stealth_create_missing_gate_chain = [
            "approval_snapshot",
            "admission_audit",
            "cap_guard_decision",
            "reconciliation_plan",
            "lifecycle_write_guard",
            "live_execution_disabled",
        ]
        gap_evidence_route_docs = {
            "GET /api/v1/stealth/orders": [
                "docs/STEALTH_ORDER_READS.md",
                "docs/COMMAND_WORKFLOWS.md",
            ],
            "GET /api/v1/stealth/orders/{stealth_order_id}": [
                "docs/STEALTH_ORDER_READS.md",
                "docs/COMMAND_WORKFLOWS.md",
            ],
            "GET /api/v1/stealth/command-suite": [
                "docs/STEALTH_ORDER_READS.md",
                "docs/COMMAND_WORKFLOWS.md",
            ],
            (
                "GET /api/v1/stealth/orders/{stealth_order_id}/active-placement/"
                "exchange-truth-proof"
            ): [
                "README.stealth-exchange-truth-proofs.md",
                "docs/examples/stealth-exchange-truth-proofs.md",
            ],
            (
                "GET /api/v1/stealth/orders/{stealth_order_id}/"
                "reconciliation-proof"
            ): [
                "README.stealth-reconciliation-proofs.md",
                "docs/examples/stealth-reconciliation-proofs.md",
            ],
            (
                "GET /api/v1/stealth/orders/{stealth_order_id}/"
                "cancel-replace-proof"
            ): [
                "README.stealth-command-suite.md",
                "docs/examples/stealth-command-suite.md",
            ],
            (
                "GET /api/v1/stealth/orders/{stealth_order_id}/"
                "lifecycle-write-guard-proof"
            ): [
                "README.admin-api.md",
                "docs/COMMAND_WORKFLOWS.md",
                "docs/STEALTH_ORDER_READS.md",
            ],
            "GET /api/v1/admin/recovery-gate": [
                "README.admin-api.md",
                "docs/COMMAND_WORKFLOWS.md",
            ],
            "GET /api/v1/movement-repricing/stealth/{stealth_order_id}": [
                "README.movement-repricing.md",
                "docs/COMMAND_WORKFLOWS.md",
            ],
            "GET /api/v1/admin/reconciliation/plans": [
                "README.reconciliation-plans.md",
                "docs/examples/reconciliation-plans.md",
            ],
            "GET /api/v1/admin/reconciliation/plans/{plan_id}": [
                "README.reconciliation-plans.md",
                "docs/examples/reconciliation-plans.md",
            ],
        }

        def coverage_gap_evidence_routes(
            surfaces: list[str],
        ) -> list[StealthCommandSuiteCoverageGapEvidenceRouteItem]:
            evidence_routes: list[StealthCommandSuiteCoverageGapEvidenceRouteItem] = []
            for surface in surfaces:
                inventory_item = inventory_by_surface[surface]
                method, route = _surface_method_and_path(inventory_item.surface)
                evidence_routes.append(
                    StealthCommandSuiteCoverageGapEvidenceRouteItem(
                        route=route,
                        method=method,
                        action_class=inventory_item.action_class,
                        required_permission=inventory_item.permission,
                        shared_method=inventory_item.shared_method,
                        backend_owned=True,
                        browser_authority="display_only",
                        bff_authority="read_only_forward",
                        documentation_refs=list(
                            gap_evidence_route_docs.get(surface, ["docs/COMMAND_WORKFLOWS.md"])
                        ),
                        detail=(
                            "Existing read-only Admin API evidence route for "
                            "stealth command-suite readiness; it does not "
                            "create a command route, cancel placements, reveal "
                            "orders, execute reconciliation, or call Coinbase."
                        ),
                    )
                )
            return evidence_routes

        stealth_read_surfaces = list(
            EXCHANGE_TRUTH_SURFACES_BY_FAMILY[
                AdminApiMutationFamilyType.STEALTH_CREATE
            ]
        )
        stealth_detail_surfaces = list(
            EXCHANGE_TRUTH_SURFACES_BY_FAMILY[
                AdminApiMutationFamilyType.STEALTH_REVEAL
            ]
        )
        movement_stealth_surfaces = list(
            EXCHANGE_TRUTH_SURFACES_BY_FAMILY[
                AdminApiMutationFamilyType.STEALTH_MOVE
            ]
        )
        recovery_surfaces = list(
            EXCHANGE_TRUTH_SURFACES_BY_FAMILY[
                AdminApiMutationFamilyType.STEALTH_RECOVERY
            ]
        )
        reconciliation_surfaces = list(
            EXCHANGE_TRUTH_SURFACES_BY_FAMILY[
                AdminApiMutationFamilyType.STEALTH_RECONCILIATION
            ]
        )
        exchange_truth_checks: list[StealthCommandSuiteExchangeTruthItem] = []
        for mutation_family, metadata in command_metadata.items():
            inventory_item = inventory_by_surface[str(metadata["surface"])]
            method, route = _surface_method_and_path(inventory_item.surface)
            active_placement_required = bool(
                metadata.get("active_placement_evidence_required", True)
            )
            surfaces = list(EXCHANGE_TRUTH_SURFACES_BY_FAMILY[mutation_family])
            truth_contract = build_stealth_active_placement_exchange_truth_contract(
                mutation_family=mutation_family,
                route=route,
                method=method,
                identity_key=str(metadata["identity_key"]),
                exchange_truth_required=bool(
                    metadata.get("exchange_truth_required", True)
                ),
                active_placement_evidence_required=active_placement_required,
                current_read_evidence_routes=surfaces,
                current_read_evidence=coverage_gap_evidence_routes(surfaces),
            )
            if truth_contract is not None:
                exchange_truth_checks.append(truth_contract)

        cancel_replace_boundaries: list[StealthCommandSuiteCancelReplaceBoundaryItem] = []
        for mutation_family in (
            AdminApiMutationFamilyType.STEALTH_CANCEL,
            AdminApiMutationFamilyType.STEALTH_MOVE,
            AdminApiMutationFamilyType.MOVEMENT_REPRICE,
        ):
            metadata = command_metadata[mutation_family]
            inventory_item = inventory_by_surface[str(metadata["surface"])]
            method, route = _surface_method_and_path(inventory_item.surface)
            boundary = build_stealth_active_placement_cancel_replace_contract(
                mutation_family=mutation_family,
                route=route,
                method=method,
                identity_key=str(metadata["identity_key"]),
            )
            if boundary is not None:
                cancel_replace_boundaries.append(boundary)

        proof_route_evidence_names = {
            "create_approval_request": AdminApiStealthAdmissionEvidence.APPROVAL_REQUEST,
            "decide_approval_request": AdminApiStealthAdmissionEvidence.APPROVAL_DECISION,
            "record_admission_audit": AdminApiStealthAdmissionEvidence.ADMISSION_AUDIT,
            "record_cap_guard_decision": AdminApiStealthAdmissionEvidence.CAP_GUARD_DECISION,
            "record_reconciliation_plan": AdminApiStealthAdmissionEvidence.RECONCILIATION_PLAN,
            "record_stealth_create_lifecycle_write_guard_proof": (
                AdminApiStealthAdmissionEvidence.LIFECYCLE_WRITE_GUARD
            ),
            "record_stealth_mutation_claim_snapshot_proof": (
                AdminApiStealthAdmissionEvidence.MUTATION_CLAIM_SNAPSHOT
            ),
            "record_stealth_manager_invocation_policy_proof": (
                AdminApiStealthAdmissionEvidence.MANAGER_INVOCATION_POLICY
            ),
            "record_stealth_coinbase_exchange_submission_policy_proof": (
                AdminApiStealthAdmissionEvidence.COINBASE_EXCHANGE_SUBMISSION_POLICY
            ),
            "record_stealth_state_mutation_policy_proof": (
                AdminApiStealthAdmissionEvidence.STATE_MUTATION_POLICY
            ),
            "record_stealth_post_write_reconciliation_execution_policy_proof": (
                AdminApiStealthAdmissionEvidence.POST_WRITE_RECONCILIATION_EXECUTION_POLICY
            ),
            "record_stealth_recovery_proof": (
                AdminApiStealthAdmissionEvidence.RECOVERY_PROOF
            ),
            "record_stealth_reveal_trigger_proof": (
                AdminApiStealthAdmissionEvidence.REVEAL_TRIGGER_EVIDENCE
            ),
            "record_stealth_reconciliation_proof": (
                AdminApiStealthAdmissionEvidence.RECONCILIATION_PROOF
            ),
        }

        def admission_requirement_from_surface(
            *,
            surface: str,
            evidence_name: AdminApiStealthAdmissionEvidence,
            source: str,
            identity_key: str,
            detail: str,
            bff_authority: str = "forward_only_no_execution",
        ) -> StealthCommandSuiteAdmissionRequirementItem:
            inventory_item = inventory_by_surface[surface]
            method, route = _surface_method_and_path(inventory_item.surface)
            return StealthCommandSuiteAdmissionRequirementItem(
                evidence_name=evidence_name,
                source=source,
                route=route,
                method=method,
                action_class=inventory_item.action_class,
                required_permission=inventory_item.permission,
                shared_method=inventory_item.shared_method,
                identity_key=identity_key,
                command_identity_key="stealth_order_id",
                status=AdminApiGateStatus.BLOCKED,
                required=True,
                present=False,
                blocking=True,
                backend_owned=True,
                route_bound=True,
                browser_authority="display_only",
                bff_authority=bff_authority,
                detail=detail,
            )

        def admission_context_requirement(
            *,
            field_name: AdminApiStealthAdmissionContextField,
            source: str,
            present: bool,
            detail: str,
        ) -> StealthCommandSuiteAdmissionContextItem:
            return StealthCommandSuiteAdmissionContextItem(
                field_name=field_name,
                source=source,
                required=True,
                present=present,
                blocking=not present,
                backend_owned=True,
                route_bound=True,
                browser_authority="display_only",
                bff_authority="forward_only_no_execution",
                detail=detail,
            )

        static_context_details = {
            AdminApiStealthAdmissionContextField.ROUTE: (
                "Route is present from backend route inventory."
            ),
            AdminApiStealthAdmissionContextField.METHOD: (
                "Method is present from backend route inventory."
            ),
            AdminApiStealthAdmissionContextField.MODULE_ID: (
                "Module id is present from backend route inventory."
            ),
            AdminApiStealthAdmissionContextField.MUTATION_FAMILY: (
                "Mutation family is present from backend command metadata."
            ),
            AdminApiStealthAdmissionContextField.ACTION_CLASS: (
                "Action class is present from backend route inventory."
            ),
            AdminApiStealthAdmissionContextField.REQUIRED_PERMISSION: (
                "Required permission is present from backend route inventory."
            ),
        }
        command_envelope_context_details = {
            AdminApiStealthAdmissionContextField.STEALTH_ORDER_ID: (
                "A concrete stealth_order_id value must come from the command "
                "path before exact proof matching can run."
            ),
            AdminApiStealthAdmissionContextField.ACTOR_ID: (
                "Actor id must come from authenticated backend request context."
            ),
            AdminApiStealthAdmissionContextField.IDEMPOTENCY_KEY: (
                "Idempotency key must come from the mutating command request."
            ),
            AdminApiStealthAdmissionContextField.OPERATOR_INTENT: (
                "Operator intent must come from the mutating command request."
            ),
            AdminApiStealthAdmissionContextField.PAYLOAD_HASH: (
                "Payload hash must be computed by the backend admission path "
                "for the exact request body."
            ),
        }

        admission_readiness: list[StealthCommandSuiteAdmissionReadinessItem] = []
        exchange_truth_checks_by_route = {
            check.route: check for check in exchange_truth_checks
        }
        active_exchange_truth_surface = (
            "GET /api/v1/stealth/orders/{stealth_order_id}/active-placement/"
            "exchange-truth-proof"
        )
        cancel_replace_proof_surface = (
            "GET /api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proof"
        )
        cancel_replace_proof_families = {
            AdminApiMutationFamilyType.STEALTH_CANCEL,
            AdminApiMutationFamilyType.STEALTH_MOVE,
            AdminApiMutationFamilyType.MOVEMENT_REPRICE,
        }
        for command in commands:
            requirements: list[StealthCommandSuiteAdmissionRequirementItem] = []
            for proof_route in command.proof_routes:
                evidence_name = proof_route_evidence_names[proof_route.shared_method]
                requirements.append(
                    StealthCommandSuiteAdmissionRequirementItem(
                        evidence_name=evidence_name,
                        source="proof_route",
                        route=proof_route.route,
                        method=proof_route.method,
                        action_class=proof_route.action_class,
                        required_permission=proof_route.required_permission,
                        shared_method=proof_route.shared_method,
                        identity_key=proof_route.identity_key,
                        command_identity_key=proof_route.command_identity_key,
                        status=AdminApiGateStatus.BLOCKED,
                        required=True,
                        present=False,
                        blocking=True,
                        backend_owned=True,
                        route_bound=True,
                        browser_authority="display_only",
                        bff_authority="forward_only_no_execution",
                        detail=proof_route.detail,
                    )
                )
            if command.active_placement_evidence_required:
                requirements.append(
                    admission_requirement_from_surface(
                        surface=active_exchange_truth_surface,
                        evidence_name=(
                            AdminApiStealthAdmissionEvidence.ACTIVE_PLACEMENT_EXCHANGE_TRUTH
                        ),
                        source="exchange_truth_readback",
                        identity_key="stealth_order_id",
                        bff_authority="read_only_forward",
                        detail=(
                            "Read active-placement exchange-truth snapshot/proof "
                            "records for the exact stealth_order_id. These records "
                            "remain local evidence only and do not verify Coinbase truth."
                        ),
                    )
                )
            else:
                if not any(
                    requirement.evidence_name
                    == AdminApiStealthAdmissionEvidence.LIFECYCLE_WRITE_GUARD
                    for requirement in requirements
                ):
                    requirements.append(
                        admission_requirement_from_surface(
                            surface="GET /api/v1/stealth/command-suite",
                            evidence_name=(
                                AdminApiStealthAdmissionEvidence.LIFECYCLE_WRITE_GUARD
                            ),
                            source="lifecycle_write_readiness",
                            identity_key="stealth_order_id",
                            bff_authority="read_only_forward",
                            detail=(
                                "Read lifecycle-write readiness evidence for the "
                                "exact stealth command. This does not invoke "
                                "StealthOrderManager or mutate lifecycle state."
                            ),
                        )
                    )
            if command.mutation_family in cancel_replace_proof_families:
                requirements.append(
                    admission_requirement_from_surface(
                        surface=cancel_replace_proof_surface,
                        evidence_name=(
                            AdminApiStealthAdmissionEvidence.CANCEL_REPLACE_PROOF
                        ),
                        source="cancel_replace_proof_readback",
                        identity_key="stealth_order_id",
                        bff_authority="read_only_forward",
                        detail=(
                            "Read cancel/replace proof records for the exact "
                            "stealth_order_id and guarded cancel, move, or "
                            "reprice command. This remains local evidence only "
                            "and does not build plans, invoke managers, call "
                            "Coinbase, cancel/replace placements, execute "
                            "reconciliation, or mutate state."
                        ),
                    )
                )
            requirements.append(
                StealthCommandSuiteAdmissionRequirementItem(
                    evidence_name=AdminApiStealthAdmissionEvidence.LIVE_EXECUTION_ADAPTER,
                    source=DISABLED_STEALTH_LIVE_EXECUTION_ADAPTER_SOURCE,
                    route=command.route,
                    method=command.method,
                    action_class=command.action_class,
                    required_permission=command.required_permission,
                    shared_method=command.shared_method,
                    identity_key=command.identity_key,
                    command_identity_key="stealth_order_id",
                    status=AdminApiGateStatus.BLOCKED,
                    required=True,
                    present=False,
                    blocking=True,
                    backend_owned=True,
                    route_bound=True,
                    browser_authority="display_only",
                    bff_authority="forward_only_no_execution",
                    detail=(
                        "A backend live adapter must remain disabled until all "
                        "route-bound approval, audit, cap/guard, reconciliation, "
                        "and exchange-truth evidence is present."
                    ),
                )
            )
            requirements.append(
                admission_requirement_from_surface(
                    surface="POST /api/v1/admin/reconciliation/plans",
                    evidence_name=AdminApiStealthAdmissionEvidence.POST_LIVE_RECONCILIATION,
                    source="post_live_reconciliation_contract",
                    identity_key="stealth_order_id",
                    detail=(
                        "Post-live reconciliation proof must be planned before "
                        "execution and recorded after execution before a stealth "
                        "state transition can be considered complete."
                    ),
                )
            )
            truth_check = exchange_truth_checks_by_route[command.route]
            missing_evidence = [
                requirement.evidence_name.value
                for requirement in requirements
                if requirement.blocking
            ]
            context_requirements = [
                admission_context_requirement(
                    field_name=field_name,
                    source="route_inventory",
                    present=True,
                    detail=detail,
                )
                for field_name, detail in static_context_details.items()
            ] + [
                admission_context_requirement(
                    field_name=field_name,
                    source="command_envelope",
                    present=False,
                    detail=detail,
                )
                for field_name, detail in command_envelope_context_details.items()
            ]
            missing_context = [
                context.field_name.value
                for context in context_requirements
                if context.blocking
            ]
            admission_readiness.append(
                StealthCommandSuiteAdmissionReadinessItem(
                    mutation_family=command.mutation_family,
                    route=command.route,
                    method=command.method,
                    identity_key=command.identity_key,
                    command_identity_key="stealth_order_id",
                    action_class=command.action_class,
                    required_permission=command.required_permission,
                    shared_method=command.shared_method,
                    status=AdminApiGateStatus.BLOCKED,
                    live_execution_status=command.live_execution_status,
                    admission_allowed=False,
                    executable=False,
                    live_enabled=False,
                    live_adapter_invocation_allowed=False,
                    manager_invocation_allowed=False,
                    route_local_execution_allowed=False,
                    browser_authority="display_only",
                    bff_authority="forward_only_no_execution",
                    accepted_command_identity_keys=["stealth_order_id"],
                    rejected_command_identity_keys=[
                        "client_order_id",
                        "active_placement_client_order_id",
                        "exchange_order_id",
                        "order_id",
                    ],
                    required_evidence_count=len(requirements),
                    present_evidence_count=0,
                    missing_evidence_count=len(missing_evidence),
                    missing_evidence=missing_evidence,
                    requirements=requirements,
                    required_context_count=len(context_requirements),
                    present_context_count=sum(
                        1 for context in context_requirements if context.present
                    ),
                    missing_context_count=len(missing_context),
                    missing_context=missing_context,
                    context_requirements=context_requirements,
                    exact_context_present=False,
                    resolver_lookup_allowed=False,
                    resolver_lookup_ran=False,
                    proof_resolution_attempted=False,
                    active_placement_exchange_truth_required=(
                        truth_check.active_placement_evidence_required
                    ),
                    exchange_truth_verified=False,
                    lifecycle_write_guard_required=(
                        not truth_check.active_placement_evidence_required
                    ),
                    coinbase_read_ran=False,
                    coinbase_order_submitted=False,
                    coinbase_order_cancel_submitted=False,
                    active_placement_cancel_replace_ran=False,
                    reconciliation_executed=False,
                    lifecycle_state_mutated=False,
                    order_state_mutated=False,
                    exchange_state_mutated=False,
                    evidence=[
                        "Derived from existing command metadata, proof routes, exchange-truth checks, and disabled live-enablement posture.",
                        "All requirements are backend-owned and route-bound before execution can ever be considered.",
                        "Exact command-envelope context is required before any proof resolver lookup can run.",
                        "This read model does not approve, execute, reconcile, read Coinbase, or mutate stealth state.",
                    ],
                    detail=(
                        "Stealth command admission remains blocked until every "
                        "listed requirement is present for the exact route, "
                        "payload, actor, idempotency key, and stealth_order_id."
                    ),
                )
            )

        coverage_gaps = [
            StealthCommandSuiteCoverageGapItem(
                family=AdminApiStealthCommandSuiteGapFamily.STEALTH_CREATE_WORKFLOW,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                command_route="/api/v1/stealth/orders",
                current_read_evidence_routes=stealth_read_surfaces,
                current_read_evidence=coverage_gap_evidence_routes(stealth_read_surfaces),
                required_backend_contract=(
                    "Stealth create has a route-bound Admin API contract, but "
                    "still needs lifecycle-write admission, planning guard, "
                    "recovery, and reconciliation contracts before it can "
                    "invoke StealthOrderManager."
                ),
                required_gate_chain=stealth_create_gate_chain,
                missing_contracts=[
                    "stealth_create_guard_contract",
                    "stealth_create_admission_audit",
                    "stealth_create_reconciliation_plan",
                    "stealth_create_lifecycle_write_guard_proof",
                    "stealth_create_lifecycle_write_execution_contract",
                ],
                stealth_rule_boundary=stealth_boundary,
                documentation_refs=[
                    "docs/STEALTH_ORDER_READS.md",
                    "docs/agents/INVARIANTS.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                detail=(
                    "A live-disabled stealth create command route exists, but "
                    "it does not invoke StealthOrderManager or mutate local "
                    "lifecycle state."
                ),
            ),
            StealthCommandSuiteCoverageGapItem(
                family=AdminApiStealthCommandSuiteGapFamily.STEALTH_REVEAL_WORKFLOW,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                command_route="/api/v1/stealth/orders/{stealth_order_id}/reveal",
                current_read_evidence_routes=stealth_detail_surfaces,
                current_read_evidence=coverage_gap_evidence_routes(stealth_detail_surfaces),
                required_backend_contract=(
                    "Stealth reveal has a route-bound Admin API contract, but "
                    "still needs trigger evidence, exchange submission adapter, "
                    "active-placement audit, and reconciliation proof before it "
                    "can invoke the existing reveal path."
                ),
                required_gate_chain=gap_required_gate_chain,
                missing_contracts=[
                    "stealth_reveal_trigger_guard",
                    "stealth_reveal_exchange_submission_adapter",
                    "stealth_active_placement_audit",
                    "stealth_reveal_reconciliation_proof",
                ],
                stealth_rule_boundary=stealth_boundary,
                documentation_refs=[
                    "docs/STEALTH_ORDER_READS.md",
                    "docs/agents/INVARIANTS.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                detail=(
                    "A live-disabled stealth reveal command route exists, but "
                    "it does not invoke reveal_order_slice, submit Coinbase "
                    "orders, or mutate lifecycle state."
                ),
            ),
            StealthCommandSuiteCoverageGapItem(
                family=AdminApiStealthCommandSuiteGapFamily.STEALTH_CANCEL_EXCHANGE_HANDLING,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                command_route="/api/v1/stealth/orders/{stealth_order_id}/cancel",
                current_read_evidence_routes=stealth_detail_surfaces,
                current_read_evidence=coverage_gap_evidence_routes(stealth_detail_surfaces),
                required_backend_contract=(
                    "Live stealth cancel must cancel or reconcile any active "
                    "Coinbase placement through the existing cancel/move/reconcile "
                    "path before local stealth state changes."
                ),
                required_gate_chain=gap_required_gate_chain,
                missing_contracts=[
                    "stealth_cancel_active_placement_cancel_proof",
                    "stealth_cancel_exchange_reconciliation_proof",
                    "stealth_cancel_state_transition_audit",
                ],
                stealth_rule_boundary=stealth_boundary,
                documentation_refs=[
                    "README.admin-api.md",
                    "docs/agents/INVARIANTS.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                detail=(
                    "A live-disabled cancel command exists, but live cancel "
                    "cannot mark revealed orders cancelled until active exchange "
                    "placement reality is handled."
                ),
            ),
            StealthCommandSuiteCoverageGapItem(
                family=AdminApiStealthCommandSuiteGapFamily.STEALTH_MOVE_REVEALED_WORKFLOW,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                command_route="/api/v1/stealth/orders/{stealth_order_id}/move",
                current_read_evidence_routes=movement_stealth_surfaces,
                current_read_evidence=coverage_gap_evidence_routes(movement_stealth_surfaces),
                required_backend_contract=(
                    "Move-revealed has a route-bound Admin API contract, but "
                    "still needs mutation-claim ownership, active placement "
                    "cancel/replace proof, state-transition audit, and "
                    "reconciliation proof before it can invoke the existing "
                    "move path."
                ),
                required_gate_chain=gap_required_gate_chain,
                missing_contracts=[
                    "stealth_move_active_placement_cancel_replace_proof",
                    "stealth_move_mutation_claim_snapshot_contract",
                    "stealth_move_reconciliation_proof",
                ],
                stealth_rule_boundary=stealth_boundary,
                documentation_refs=[
                    "README.admin-api.md",
                    "docs/agents/INVARIANTS.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                detail=(
                    "A live-disabled stealth move command route exists, but it "
                    "does not build a move plan, execute cancel/replace, submit "
                    "Coinbase orders, or mutate lifecycle state."
                ),
            ),
            StealthCommandSuiteCoverageGapItem(
                family=AdminApiStealthCommandSuiteGapFamily.STEALTH_REPRICE_WORKFLOW,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                command_route="/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice",
                current_read_evidence_routes=movement_stealth_surfaces,
                current_read_evidence=coverage_gap_evidence_routes(movement_stealth_surfaces),
                required_backend_contract=(
                    "Reprice completion requires the movement/repricing claim, "
                    "cooldown, cancel/replace, active-placement audit, recovery, "
                    "and reconciliation contracts owned by M56."
                ),
                required_gate_chain=gap_required_gate_chain,
                missing_contracts=[
                    "stealth_reprice_active_placement_cancel_replace_proof",
                    "stealth_reprice_cooldown_claim_contract",
                    "stealth_reprice_reconciliation_proof",
                ],
                stealth_rule_boundary=stealth_boundary,
                documentation_refs=[
                    "README.movement-repricing.md",
                    "docs/agents/INVARIANTS.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                detail=(
                    "A live-disabled repricing command exists, but full reprice "
                    "completion belongs to the movement/repricing claim and "
                    "cancel/replace workflow."
                ),
            ),
            StealthCommandSuiteCoverageGapItem(
                family=AdminApiStealthCommandSuiteGapFamily.STEALTH_RECOVERY_WORKFLOW,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                command_route="/api/v1/stealth/orders/{stealth_order_id}/recovery",
                current_read_evidence_routes=recovery_surfaces,
                current_read_evidence=coverage_gap_evidence_routes(recovery_surfaces),
                required_backend_contract=(
                    "Stealth recovery has a route-bound Admin API contract, but "
                    "still needs backend-owned preview, proof, repair, rollback, "
                    "audit, active-placement, and reconciliation contracts before "
                    "any repair action can execute."
                ),
                required_gate_chain=gap_required_gate_chain,
                missing_contracts=[
                    "stealth_recovery_preview_contract",
                    "stealth_recovery_proof_writer",
                    "stealth_recovery_repair_result_contract",
                    "stealth_recovery_rollback_contract",
                ],
                stealth_rule_boundary=stealth_boundary,
                documentation_refs=[
                    "docs/STEALTH_ORDER_READS.md",
                    "docs/agents/INVARIANTS.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                detail=(
                    "A live-disabled stealth recovery command route exists, but "
                    "it does not execute repair, rollback, lifecycle mutation, "
                    "Coinbase reads, or reconciliation."
                ),
            ),
            StealthCommandSuiteCoverageGapItem(
                family=AdminApiStealthCommandSuiteGapFamily.STEALTH_RECONCILIATION_WORKFLOW,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                command_route="/api/v1/stealth/orders/{stealth_order_id}/reconciliation",
                current_read_evidence_routes=reconciliation_surfaces,
                current_read_evidence=coverage_gap_evidence_routes(reconciliation_surfaces),
                required_backend_contract=(
                    "Stealth reconciliation has a route-bound Admin API contract, "
                    "but still needs a stealth-specific execution contract that "
                    "can compare local lifecycle state with active Coinbase "
                    "placement evidence without browser or BFF state mutation."
                ),
                required_gate_chain=gap_required_gate_chain,
                missing_contracts=[
                    "stealth_reconciliation_plan_contract",
                    "stealth_exchange_evidence_snapshot_contract",
                    "stealth_reconciliation_executor",
                ],
                stealth_rule_boundary=stealth_boundary,
                documentation_refs=[
                    "README.reconciliation-plans.md",
                    "docs/examples/reconciliation-plans.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                detail=(
                    "A live-disabled stealth reconciliation command route exists, "
                    "but it does not execute reconciliation, write proof records, "
                    "read Coinbase, or mutate order/lifecycle/exchange state."
                ),
            ),
        ]

        return StealthCommandSuiteResponse(
            approved_phase_range=AUTONOMOUS_APPROVED_PHASE_RANGE,
            status=AdminApiGateStatus.BLOCKED,
            command_count=len(commands),
            blocked_command_count=sum(
                1 for command in commands if command.status == AdminApiGateStatus.BLOCKED
            ),
            live_enabled_command_count=sum(
                1 for command in commands if command.live_enabled
            ),
            executable_command_count=sum(1 for command in commands if command.executable),
            exchange_truth_required=True,
            browser_authority="display_only",
            bff_authority="forward_only_no_execution",
            submitted_notional_usdc="0",
            executed_notional_usdc="0",
            live_coinbase_orders_ran=False,
            live_coinbase_read_ran=False,
            exchange_truth_check_count=len(exchange_truth_checks),
            blocking_exchange_truth_check_count=sum(
                1
                for check in exchange_truth_checks
                if check.status == AdminApiGateStatus.BLOCKED
            ),
            active_placement_exchange_truth_required_count=sum(
                1
                for check in exchange_truth_checks
                if check.active_placement_evidence_required
            ),
            exchange_truth_checks=exchange_truth_checks,
            cancel_replace_boundary_count=len(cancel_replace_boundaries),
            blocking_cancel_replace_boundary_count=sum(
                1
                for boundary in cancel_replace_boundaries
                if boundary.status == AdminApiGateStatus.BLOCKED
            ),
            cancel_replace_boundaries=cancel_replace_boundaries,
            admission_readiness_count=len(admission_readiness),
            blocking_admission_readiness_count=sum(
                1
                for readiness in admission_readiness
                if readiness.status == AdminApiGateStatus.BLOCKED
            ),
            admission_readiness=admission_readiness,
            commands=commands,
            coverage_gap_count=len(coverage_gaps),
            coverage_gaps=coverage_gaps,
            create_lifecycle_write_audit=_stealth_create_lifecycle_write_audit(
                required_gate_chain=stealth_create_gate_chain,
                missing_gate_chain=stealth_create_missing_gate_chain,
                proof_routes=proof_routes_for_command(
                    "stealth_order_id",
                    include_lifecycle_write_guard=True,
                ),
            ),
            read_routes=read_routes,
            evidence=[
                "M55 starts with read-only stealth command-suite coverage before execution.",
                "Stealth create, reveal, cancel, move, reprice, recovery, and reconciliation remain backend-owned workflows.",
                "Revealed stealth orders cannot be marked hidden, cancelled, or moved by local mutation alone.",
                "No browser, BFF, route-local, or Coinbase execution authority is added.",
                "Live Coinbase execution and live Coinbase reads were not run for this evidence route.",
            ],
            message=(
                "Stealth command-suite coverage is backend-owned readiness evidence; "
                "live Coinbase execution remains disabled."
            ),
        )

    def build_movement_repricing_evidence(
        self,
        *,
        product_id: str | None = None,
        client_order_id: str | None = None,
        stealth_order_id: str | None = None,
        evidence_type: AdminMovementRepricingEvidenceType | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> AdminMovementRepricingListResponse:
        """Return read-only movement/repricing evidence from owned sources."""

        normalized_limit = max(1, min(limit, 500))
        normalized_offset = max(0, offset)
        filters: dict[str, Any] = {
            "product_id": product_id,
            "client_order_id": client_order_id,
            "stealth_order_id": stealth_order_id,
            "evidence_type": _movement_evidence_type_value(evidence_type),
            "limit": normalized_limit,
            "offset": normalized_offset,
        }
        read_errors: list[str] = []

        order_move_rows, error = _query_admin_rows(
            "SELECT * FROM order_moves ORDER BY created_at DESC, moved_at DESC"
        )
        if error:
            read_errors.append(f"order_moves:{error}")

        stealth_move_rows, error = _query_admin_rows(
            "SELECT * FROM stealth_order_moves ORDER BY moved_at DESC"
        )
        if error:
            read_errors.append(f"stealth_order_moves:{error}")

        stealth_rows, error = _query_admin_rows(
            "SELECT * FROM stealth_orders ORDER BY updated_at DESC, created_at DESC"
        )
        if error:
            read_errors.append(f"stealth_orders:{error}")
        if read_errors:
            filters["backend_read_errors"] = read_errors

        items: list[AdminMovementRepricingEvidenceItem] = []
        items.extend(_parent_move_item_from_row(row) for row in order_move_rows)
        items.extend(_stealth_move_item_from_row(row) for row in stealth_move_rows)
        items.extend(_stealth_repricing_item_from_row(row) for row in stealth_rows)

        filtered = [
            item
            for item in items
            if _movement_item_matches(
                item,
                product_id=product_id,
                client_order_id=client_order_id,
                stealth_order_id=stealth_order_id,
                evidence_type=evidence_type,
            )
        ]
        page_items = filtered[normalized_offset:normalized_offset + normalized_limit]
        next_offset = normalized_offset + len(page_items)
        has_more = next_offset < len(filtered)
        return AdminMovementRepricingListResponse(
            filters=filters,
            count=len(page_items),
            pagination={
                "limit": normalized_limit,
                "offset": normalized_offset,
                "returned_count": len(page_items),
                "total_matching_count": len(filtered),
                "next_offset": next_offset if has_more else None,
                "has_more": has_more,
            },
            items=page_items,
        )

    def build_movement_repricing_order_detail(
        self,
        *,
        client_order_id: str,
    ) -> AdminMovementRepricingDetailResponse:
        """Return movement/repricing evidence linked to one ``client_order_id``."""

        evidence = self.build_movement_repricing_evidence(
            client_order_id=client_order_id,
            limit=500,
            offset=0,
        )
        return AdminMovementRepricingDetailResponse(
            scope="client_order_id",
            client_order_id=client_order_id,
            found=bool(evidence.items),
            items=evidence.items,
        )

    def build_movement_repricing_stealth_detail(
        self,
        *,
        stealth_order_id: str,
    ) -> AdminMovementRepricingDetailResponse:
        """Return movement/repricing evidence linked to one ``stealth_order_id``."""

        evidence = self.build_movement_repricing_evidence(
            stealth_order_id=stealth_order_id,
            limit=500,
            offset=0,
        )
        return AdminMovementRepricingDetailResponse(
            scope="stealth_order_id",
            stealth_order_id=stealth_order_id,
            found=bool(evidence.items),
            items=evidence.items,
        )

    def build_futures_account(self) -> AdminFuturesAccountReadResponse:
        """Return read-only futures/perpetual account and risk evidence."""

        products = _futures_product_metadata()
        positions = _futures_position_items()
        configured_product_scope = sorted(products.keys())
        observed_position_scope = sorted({item.product_id for item in positions})
        fee_info = _runtime_fee_info()

        margin_value = {
            key: fee_info.get(key)
            for key in (
                "margin_window_type",
                "overnight_margin_active",
                "profit_validation_fee_rate",
                "effective_fee_rate",
                "target_movement_factor",
                "fee_regime_factor",
                "volume_ratio",
            )
            if key in fee_info
        }
        margin = (
            _futures_evidence(
                name="margin",
                status=AdminFuturesEvidenceStatus.OBSERVED,
                source=AdminFuturesEvidenceSource.FEE_MANAGER,
                value=margin_value,
                detail="Margin-window regime is observed from the runtime fee manager.",
            )
            if margin_value
            else _futures_evidence(
                name="margin",
                status=AdminFuturesEvidenceStatus.UNAVAILABLE,
                source=AdminFuturesEvidenceSource.RUNTIME_UNAVAILABLE,
                detail="No runtime fee-manager or margin-window evidence is currently available.",
            )
        )

        collateral_keys = (
            "futures_buying_power",
            "total_usd_balance",
            "cfm_usd_balance",
            "available_margin",
            "initial_margin",
            "total_open_orders_hold_amount",
        )
        collateral_value = {
            key: fee_info.get(key)
            for key in collateral_keys
            if fee_info.get(key) is not None
        }
        collateral = (
            _futures_evidence(
                name="collateral",
                status=AdminFuturesEvidenceStatus.OBSERVED,
                source=AdminFuturesEvidenceSource.FEE_MANAGER,
                value=collateral_value,
                detail="Collateral fields are present in runtime futures balance evidence.",
            )
            if collateral_value
            else _futures_evidence(
                name="collateral",
                status=AdminFuturesEvidenceStatus.UNAVAILABLE,
                source=AdminFuturesEvidenceSource.RUNTIME_UNAVAILABLE,
                detail="The engine does not currently retain a futures balance summary snapshot.",
            )
        )

        liquidation_keys = (
            "liquidation_threshold",
            "liquidation_buffer_amount",
            "liquidation_buffer_percentage",
        )
        liquidation_value = {
            key: fee_info.get(key)
            for key in liquidation_keys
            if fee_info.get(key) is not None
        }
        liquidation = (
            _futures_evidence(
                name="liquidation",
                status=AdminFuturesEvidenceStatus.OBSERVED,
                source=AdminFuturesEvidenceSource.FEE_MANAGER,
                value=liquidation_value,
                detail="Liquidation evidence is present in runtime futures balance evidence.",
            )
            if liquidation_value
            else _futures_evidence(
                name="liquidation",
                status=AdminFuturesEvidenceStatus.UNAVAILABLE,
                source=AdminFuturesEvidenceSource.RUNTIME_UNAVAILABLE,
                detail="Liquidation threshold and buffer are not retained in the current runtime snapshot.",
            )
        )

        pnl_items = [
            {
                "position_key": item.position_key,
                "product_id": item.product_id,
                "position_pnl": item.position_pnl,
            }
            for item in positions
            if item.position_pnl
        ]
        position_pnl = (
            _futures_evidence(
                name="position_pnl",
                status=AdminFuturesEvidenceStatus.OBSERVED,
                source=AdminFuturesEvidenceSource.RUNTIME_POSITIONS,
                value={"positions": pnl_items},
                detail="Position P/L is sourced from runtime futures position payloads.",
            )
            if pnl_items
            else _futures_evidence(
                name="position_pnl",
                status=AdminFuturesEvidenceStatus.UNAVAILABLE,
                source=AdminFuturesEvidenceSource.RUNTIME_UNAVAILABLE,
                detail="No runtime futures position P/L is currently available.",
            )
        )

        reduce_only_close_only = (
            _futures_evidence(
                name="reduce_only_close_only",
                status=AdminFuturesEvidenceStatus.OBSERVED,
                source=AdminFuturesEvidenceSource.POSITION_SIDE_DERIVATION,
                value={
                    item.position_key: {
                        "product_id": item.product_id,
                        "position_side": item.position_side,
                        "reduce_only_order_side": item.reduce_only_order_side,
                        "close_only_order_side": item.close_only_order_side,
                    }
                    for item in positions
                },
                detail=(
                    "Close/reduce sides are backend-derived from observed futures "
                    "position side; they are not exchange-observed order flags."
                ),
            )
            if positions
            else _futures_evidence(
                name="reduce_only_close_only",
                status=AdminFuturesEvidenceStatus.UNAVAILABLE,
                source=AdminFuturesEvidenceSource.RUNTIME_UNAVAILABLE,
                detail="No open futures positions are currently available for close-side derivation.",
            )
        )

        funding = _futures_evidence(
            name="funding",
            status=AdminFuturesEvidenceStatus.NOT_MODELED,
            source=AdminFuturesEvidenceSource.BACKEND_CONTRACT,
            detail="Funding-rate evidence is a named contract gap for M3; no browser or spot fallback is used.",
        )

        return AdminFuturesAccountReadResponse(
            configured_product_scope=configured_product_scope,
            observed_position_scope=observed_position_scope,
            collateral=collateral,
            margin=margin,
            funding=funding,
            liquidation=liquidation,
            reduce_only_close_only=reduce_only_close_only,
            position_pnl=position_pnl,
            position_count=len(positions),
        )

    def build_futures_positions(
        self,
        *,
        product_id: str | None = None,
        position_side: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> AdminFuturesPositionListResponse:
        """Return read-only futures/perpetual positions from runtime evidence."""

        normalized_limit = max(1, min(limit, 500))
        normalized_offset = max(0, offset)
        filters: dict[str, Any] = {
            "product_id": product_id,
            "position_side": position_side,
            "limit": normalized_limit,
            "offset": normalized_offset,
        }
        items = _futures_position_items()
        filtered: list[AdminFuturesPositionReadItem] = []
        for item in items:
            if product_id and item.product_id != product_id:
                continue
            if (
                position_side
                and str(item.position_side or "").upper() != position_side.upper()
            ):
                continue
            filtered.append(item)
        page_items = filtered[normalized_offset:normalized_offset + normalized_limit]
        next_offset = normalized_offset + len(page_items)
        has_more = next_offset < len(filtered)
        return AdminFuturesPositionListResponse(
            filters=filters,
            count=len(page_items),
            pagination={
                "limit": normalized_limit,
                "offset": normalized_offset,
                "returned_count": len(page_items),
                "total_matching_count": len(filtered),
                "next_offset": next_offset if has_more else None,
                "has_more": has_more,
            },
            items=page_items,
        )

    def build_futures_position_detail(
        self,
        *,
        position_key: str,
    ) -> AdminFuturesPositionDetailResponse:
        """Return one read-only futures/perpetual position by ``position_key``."""

        positions = _futures_position_items()
        for position in positions:
            if position.position_key == position_key:
                return AdminFuturesPositionDetailResponse(
                    position_key=position_key,
                    found=True,
                    position=position,
                )
        return AdminFuturesPositionDetailResponse(
            position_key=position_key,
            found=False,
            position=None,
        )

    def build_release_gate(self) -> AdminGateReadResponse:
        """Return release-gate evidence without running tests from the browser."""

        openapi_path = ROOT / "openapi" / "coinbase-admin-api.yaml"
        checks = [
            AdminGateCheck(
                name="openapi_schema_artifact",
                status=(
                    AdminApiGateStatus.PASSED
                    if openapi_path.exists()
                    else AdminApiGateStatus.BLOCKED
                ),
                detail=str(openapi_path),
            ),
            AdminGateCheck(
                name="backend_regression_gate",
                status=AdminApiGateStatus.NOT_APPLICABLE,
                detail="The browser may view release status, but it must not run pytest.",
            ),
            AdminGateCheck(
                name="live_coinbase_execution",
                status=AdminApiGateStatus.PASSED,
                detail="No live Coinbase execution is performed by this read route.",
            ),
        ]
        status = (
            AdminApiGateStatus.BLOCKED
            if any(check.status == AdminApiGateStatus.BLOCKED for check in checks)
            else AdminApiGateStatus.PASSED
        )
        return AdminGateReadResponse(
            type="admin_release_gate",
            status=status,
            checks=checks,
        )

    def build_recovery_gate(self) -> AdminGateReadResponse:
        """Return spot/direct-order recovery-readiness route evidence."""

        return AdminGateReadResponse(
            type="admin_recovery_gate",
            status=AdminApiGateStatus.PASSED,
            checks=[
                AdminGateCheck(
                    name="spot_direct_order_audit_route",
                    status=AdminApiGateStatus.PASSED,
                    detail="/api/v1/spot/direct-orders/{client_order_id}/audit is read-only.",
                ),
                AdminGateCheck(
                    name="non_spot_recovery_scope",
                    status=AdminApiGateStatus.NOT_APPLICABLE,
                    detail=(
                        "Non-spot recovery gates require module-specific backend "
                        "contracts; this route reports spot/direct-order recovery "
                        "readiness only."
                    ),
                ),
                AdminGateCheck(
                    name="repair_mutations",
                    status=AdminApiGateStatus.NOT_APPLICABLE,
                    detail="Recovery repair actions remain outside the frontend mutation surface.",
                ),
            ],
        )

    def build_fill_ledger_health(self) -> AdminGateReadResponse:
        """Return fill-ledger health posture without mutating ledger rows."""

        return AdminGateReadResponse(
            type="admin_fill_ledger_health",
            status=AdminApiGateStatus.PASSED,
            checks=[
                AdminGateCheck(
                    name="read_surface",
                    status=AdminApiGateStatus.PASSED,
                    detail="Fill-ledger health is exposed as a read-only contract.",
                ),
                AdminGateCheck(
                    name="repair_surface",
                    status=AdminApiGateStatus.NOT_APPLICABLE,
                    detail="Ledger repair remains CLI/operator controlled, not browser-triggered.",
                ),
                AdminGateCheck(
                    name="observed_at",
                    status=AdminApiGateStatus.PASSED,
                    detail=_now_iso(),
                ),
            ],
        )

    def build_frontend_fixtures(self) -> AdminFrontendFixturesResponse:
        """Return backend-owned fixtures for frontend mock alignment."""

        return AdminFrontendFixturesResponse(
            schema_version=SCHEMA_VERSION,
            fixtures={
                "admin.bootstrap": self.build_admin_bootstrap().model_dump(mode="json"),
                "admin.health": self.build_admin_health().model_dump(mode="json"),
                "admin.capabilities": self.build_admin_capabilities().model_dump(mode="json"),
                "admin.csrf": self.build_csrf_contract().model_dump(mode="json"),
                "admin.liveEnablement": self.build_live_enablement().model_dump(mode="json"),
                "admin.enterpriseReadiness": self.build_enterprise_readiness().model_dump(mode="json"),
                "orders.list": self.build_order_list().model_dump(mode="json"),
                "orders.detail.empty": self.build_order_detail(
                    client_order_id="00000000-0000-0000-0000-000000000000"
                ).model_dump(mode="json"),
                "movementRepricing.evidence": self.build_movement_repricing_evidence().model_dump(mode="json"),
                "movementRepricing.order.empty": self.build_movement_repricing_order_detail(
                    client_order_id="00000000-0000-0000-0000-000000000000"
                ).model_dump(mode="json"),
                "movementRepricing.stealth.empty": self.build_movement_repricing_stealth_detail(
                    stealth_order_id="00000000-0000-0000-0000-000000000000"
                ).model_dump(mode="json"),
                "futures.account": self.build_futures_account().model_dump(mode="json"),
                "futures.positions": self.build_futures_positions().model_dump(mode="json"),
                "futures.position.empty": self.build_futures_position_detail(
                    position_key="futures_position:runtime:UNKNOWN"
                ).model_dump(mode="json"),
                "admin.guardRiskPolicy": self.build_guard_risk_policy().model_dump(mode="json"),
                "admin.auditWorkbench": self.build_audit_workbench().model_dump(mode="json"),
                "admin.releaseGate": self.build_release_gate().model_dump(mode="json"),
                "admin.recoveryGate": self.build_recovery_gate().model_dump(mode="json"),
                "admin.fillLedgerHealth": self.build_fill_ledger_health().model_dump(mode="json"),
                "stealth.commandSuite": self.build_stealth_command_suite().model_dump(mode="json"),
                "spot.commandSuite": self.build_spot_command_suite().model_dump(mode="json"),
                "spot.recoveryPreview": self.build_spot_recovery_preview().model_dump(mode="json"),
                "spot.recoveryApplyReview": self.build_spot_recovery_apply_review().model_dump(mode="json"),
                "spot.recoveryRollbackPlan": self.build_spot_recovery_rollback_plan().model_dump(mode="json"),
                "spot.recoveryReconciliationProof": self.build_spot_recovery_reconciliation_proof().model_dump(mode="json"),
            },
        )

    def build_spot_command_suite(self) -> SpotCommandSuiteResponse:
        """Return read-only M54 spot command-suite readiness evidence."""

        live_enablement = self.build_live_enablement()
        live_paths = {
            (path.method, path.route): path
            for path in live_enablement.paths
            if path.module_id == "spot_operations"
        }
        inventory_by_surface = {
            item.surface: item for item in ADMIN_API_ROUTE_INVENTORY
        }
        proof_route_specs = (
            (
                AdminApiLivePreflightCategory.APPROVAL,
                "POST /api/v1/admin/approvals/requests",
                None,
                [
                    "README.admin-api.md",
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/examples/admin-api.md",
                ],
                (
                    "Create a backend-owned approval request bound to the exact "
                    "route, method, actor, idempotency key, payload hash, and "
                    "command identity."
                ),
            ),
            (
                AdminApiLivePreflightCategory.APPROVAL,
                "POST /api/v1/admin/approvals/requests/{approval_request_id}/decisions",
                "approval_request_id",
                [
                    "README.admin-api.md",
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/examples/admin-api.md",
                ],
                (
                    "Record the backend approval decision. Browser approval "
                    "remains insufficient and does not execute the command."
                ),
            ),
            (
                AdminApiLivePreflightCategory.AUDIT,
                "POST /api/v1/admin/admission-audits",
                None,
                [
                    "README.admission-audits.md",
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/examples/admission-audits.md",
                ],
                (
                    "Append exact admission audit evidence for the route-bound "
                    "command. The writer cannot mark live admission allowed."
                ),
            ),
            (
                AdminApiLivePreflightCategory.CAP_GUARD,
                "POST /api/v1/admin/cap-guard/decisions",
                None,
                [
                    "README.cap-guard-decisions.md",
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/examples/cap-guard-decisions.md",
                ],
                (
                    "Record backend cap/guard evidence. The browser and BFF "
                    "must not evaluate wallet, inventory, profitability, margin, "
                    "or account limits."
                ),
            ),
            (
                AdminApiLivePreflightCategory.RECONCILIATION,
                "POST /api/v1/admin/reconciliation/plans",
                None,
                [
                    "README.reconciliation-plans.md",
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/examples/reconciliation-plans.md",
                ],
                (
                    "Record backend reconciliation proof requirements. This "
                    "does not execute reconciliation or mutate order/exchange "
                    "state."
                ),
            ),
        )

        def proof_routes_for_command(
            command_identity_key: str,
        ) -> list[SpotCommandSuiteProofRouteItem]:
            proof_routes: list[SpotCommandSuiteProofRouteItem] = []
            for (
                gate,
                surface,
                route_identity_key,
                documentation_refs,
                detail,
            ) in proof_route_specs:
                item = inventory_by_surface[surface]
                method, route = _surface_method_and_path(item.surface)
                proof_routes.append(
                    SpotCommandSuiteProofRouteItem(
                        gate=gate,
                        route=route,
                        method=method,
                        action_class=item.action_class,
                        required_permission=item.permission,
                        shared_method=item.shared_method,
                        status=AdminApiGateStatus.BLOCKED,
                        required=True,
                        blocking=True,
                        identity_key=(
                            command_identity_key
                            if route_identity_key is None
                            else route_identity_key
                        ),
                        command_identity_key=command_identity_key,
                        backend_owned=True,
                        route_bound=True,
                        browser_authority="display_only",
                        bff_authority="forward_only_no_execution",
                        documentation_refs=list(documentation_refs),
                        detail=detail,
                    )
                )
            return proof_routes

        command_metadata = {
            AdminApiMutationFamilyType.SPOT_MANUAL_ORDER: {
                "surface": "POST /api/v1/orders",
                "identity_key": "client_order_id",
                "backend_contract_refs": [
                    "api/v1/routes/orders.py::place_manual_order",
                    "application/admin_api/command_service.py::place_manual_order",
                    "business/spot_inventory_authority.py",
                    "core/action_condition_guard.py",
                ],
                "frontend_contract_refs": [
                    "src/shared/api/contracts/backendApiClient.ts::createManualOrder",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                "documentation_refs": [
                    "README.admin-api.md",
                    "README.spot-trading.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                "detail": (
                    "Manual spot order placement is the M53 pilot route, but it "
                    "remains non-executable until approval, cap/guard, audit, "
                    "reconciliation, and live execution service admission pass."
                ),
            },
            AdminApiMutationFamilyType.SPOT_ORDER_CANCEL: {
                "surface": "POST /api/v1/orders/{client_order_id}/cancel",
                "identity_key": "client_order_id",
                "backend_contract_refs": [
                    "api/v1/routes/orders.py::cancel_order_by_client_order_id",
                    "application/admin_api/command_service.py::cancel_order_by_client_order_id",
                    "cancel_order(client_order_id)",
                ],
                "frontend_contract_refs": [
                    "src/shared/api/contracts/backendApiClient.ts::cancelOrderByClientOrderId",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                "documentation_refs": [
                    "README.admin-api.md",
                    "docs/agents/INVARIANTS.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                "detail": (
                    "Spot cancel is keyed by client_order_id. Coinbase accepts "
                    "that id through the project cancel_order(client_order_id) "
                    "wrapper, but Admin API live cancel remains disabled until "
                    "approval, audit, cap/guard, and reconciliation evidence pass."
                ),
            },
            AdminApiMutationFamilyType.SPOT_CAMPAIGN_EXECUTION: {
                "surface": "POST /api/v1/spot/campaign/executions",
                "identity_key": "campaign_id",
                "backend_contract_refs": [
                    "api/v1/routes/orders.py::execute_spot_campaign",
                    "application/admin_api/command_service.py::execute_spot_campaign",
                    "business/spot_campaign.py",
                    "business/spot_portfolio_sweep.py",
                ],
                "frontend_contract_refs": [
                    "src/shared/api/contracts/backendApiClient.ts::executeSpotCampaign",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                "documentation_refs": [
                    "README.spot-campaign.md",
                    "README.spot-portfolio-sweep.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                "detail": (
                    "Spot campaign execution remains a dry-run review contract. "
                    "Live campaign execution must still use backend-owned "
                    "campaign, sweep, approval, cap, audit, recovery, and "
                    "reconciliation contracts."
                ),
            },
            AdminApiMutationFamilyType.SPOT_SWEEP_AUTOMATION: {
                "surface": "POST /api/v1/spot/sweep/automation-runs",
                "identity_key": "sweep_config_id",
                "backend_contract_refs": [
                    "api/v1/routes/orders.py::run_spot_sweep_automation",
                    "application/admin_api/command_service.py::run_spot_sweep_automation",
                    "business/spot_portfolio_sweep.py",
                    "tools/run_spot_portfolio_sweep_live.py",
                ],
                "frontend_contract_refs": [
                    "src/shared/api/contracts/backendApiClient.ts::runSpotSweepAutomation",
                    "src/features/command-workflows/CommandWorkflowShell.tsx",
                ],
                "documentation_refs": [
                    "README.spot-portfolio-sweep.md",
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/examples/admin-api.md",
                ],
                "detail": (
                    "Spot sweep automation has a route-bound command contract, "
                    "but remains non-executable until durable scheduling, "
                    "run-limit, recovery, and reconciliation contracts are wired "
                    "through backend-owned gates."
                ),
            },
            AdminApiMutationFamilyType.SPOT_RECOVERY_APPLY_EXECUTION: {
                "surface": "POST /api/v1/spot/recovery/apply-executions",
                "identity_key": "client_order_id",
                "backend_contract_refs": [
                    "api/v1/routes/orders.py::execute_spot_recovery_apply",
                    "application/admin_api/command_service.py::execute_spot_recovery_apply",
                    "tools/run_spot_fill_ledger_repair.py",
                    "tools/run_spot_fill_backfill_recovery.py",
                ],
                "frontend_contract_refs": [
                    "src/shared/api/contracts/backendApiClient.ts::executeSpotRecoveryApply",
                    "src/features/spot-ops/SpotReadOnlyViews.tsx",
                ],
                "documentation_refs": [
                    "README.spot-trading.md",
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/examples/admin-api.md",
                ],
                "detail": (
                    "Spot recovery apply is now route-bound as a disabled "
                    "backend command contract keyed by client_order_id. It does "
                    "not apply repairs, mutate local order state, or call Coinbase."
                ),
            },
            AdminApiMutationFamilyType.SPOT_RECOVERY_ROLLBACK_EXECUTION: {
                "surface": "POST /api/v1/spot/recovery/rollback-executions",
                "identity_key": "client_order_id",
                "backend_contract_refs": [
                    "api/v1/routes/orders.py::execute_spot_recovery_rollback",
                    "application/admin_api/command_service.py::execute_spot_recovery_rollback",
                    "tools/run_spot_fill_ledger_repair.py",
                ],
                "frontend_contract_refs": [
                    "src/shared/api/contracts/backendApiClient.ts::executeSpotRecoveryRollback",
                    "src/features/spot-ops/SpotReadOnlyViews.tsx",
                ],
                "documentation_refs": [
                    "README.spot-trading.md",
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/examples/admin-api.md",
                ],
                "detail": (
                    "Spot recovery rollback is now route-bound as a disabled "
                    "backend command contract keyed by client_order_id. It does "
                    "not roll back local order state or call Coinbase."
                ),
            },
            AdminApiMutationFamilyType.SPOT_RECOVERY_EXCHANGE_STATE_PROOF: {
                "surface": "POST /api/v1/spot/recovery/exchange-state-proofs",
                "identity_key": "client_order_id",
                "backend_contract_refs": [
                    "api/v1/routes/orders.py::record_spot_recovery_exchange_state_proof",
                    "application/admin_api/command_service.py::record_spot_recovery_exchange_state_proof",
                    "application/admin_api/read_service.py::build_admin_audit_workbench",
                ],
                "frontend_contract_refs": [
                    "src/shared/api/contracts/backendApiClient.ts::recordSpotRecoveryExchangeStateProof",
                    "src/features/spot-ops/SpotReadOnlyViews.tsx",
                ],
                "documentation_refs": [
                    "README.spot-trading.md",
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/examples/admin-api.md",
                ],
                "detail": (
                    "Spot recovery exchange-state proof writing is route-bound "
                    "as an append-only backend command contract keyed by "
                    "client_order_id. It persists local proof evidence but does "
                    "not fetch Coinbase or mutate order/exchange state."
                ),
            },
            AdminApiMutationFamilyType.SPOT_RECOVERY_EXCHANGE_STATE_SNAPSHOT: {
                "surface": "POST /api/v1/spot/recovery/exchange-state-snapshots",
                "identity_key": "client_order_id",
                "backend_contract_refs": [
                    "api/v1/routes/orders.py::record_spot_recovery_exchange_state_snapshot",
                    "application/admin_api/command_service.py::record_spot_recovery_exchange_state_snapshot",
                    "application/admin_api/spot_recovery_snapshot.py",
                    "application/admin_api/spot_recovery_snapshot_service.py",
                ],
                "frontend_contract_refs": [
                    "src/shared/api/contracts/backendApiClient.ts::recordSpotRecoveryExchangeStateSnapshot",
                    "src/features/spot-ops/SpotReadOnlyViews.tsx",
                ],
                "documentation_refs": [
                    "README.spot-trading.md",
                    "README.reconciliation-plans.md",
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/examples/admin-api.md",
                ],
                "detail": (
                    "Spot recovery exchange-state snapshot writing is route-bound "
                    "as append-only backend evidence keyed by client_order_id. "
                    "It can record manual/test snapshot evidence for future "
                    "reconciliation review, but it does not read Coinbase, trust "
                    "browser exchange state, or mutate order/exchange state."
                ),
            },
            AdminApiMutationFamilyType.SPOT_RECOVERY_RECONCILIATION_EXECUTION: {
                "surface": "POST /api/v1/spot/recovery/reconciliation-executions",
                "identity_key": "client_order_id",
                "backend_contract_refs": [
                    "api/v1/routes/orders.py::execute_spot_recovery_reconciliation",
                    "application/admin_api/command_service.py::execute_spot_recovery_reconciliation",
                    "application/admin_api/reconciliation.py",
                ],
                "frontend_contract_refs": [
                    "src/shared/api/contracts/backendApiClient.ts::executeSpotRecoveryReconciliation",
                    "src/features/spot-ops/SpotReadOnlyViews.tsx",
                ],
                "documentation_refs": [
                    "README.spot-trading.md",
                    "README.reconciliation-plans.md",
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/examples/admin-api.md",
                ],
                "detail": (
                    "Spot recovery reconciliation execution is route-bound as "
                    "a disabled backend command contract keyed by "
                    "client_order_id. It returns fail-closed evidence and does "
                    "not execute reconciliation, mutate order/exchange state, "
                    "or call Coinbase."
                ),
            },
            AdminApiMutationFamilyType.SPOT_RECOVERY_RECONCILIATION_PROOF: {
                "surface": "POST /api/v1/spot/recovery/reconciliation-proofs",
                "identity_key": "client_order_id",
                "backend_contract_refs": [
                    "api/v1/routes/orders.py::record_spot_recovery_reconciliation_proof",
                    "application/admin_api/command_service.py::record_spot_recovery_reconciliation_proof",
                    "application/admin_api/reconciliation.py",
                ],
                "frontend_contract_refs": [
                    "src/shared/api/contracts/backendApiClient.ts::recordSpotRecoveryReconciliationProof",
                    "src/features/spot-ops/SpotReadOnlyViews.tsx",
                ],
                "documentation_refs": [
                    "README.spot-trading.md",
                    "README.reconciliation-plans.md",
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/examples/admin-api.md",
                ],
                "detail": (
                    "Spot recovery reconciliation-proof writing is route-bound "
                    "as an append-only backend command contract keyed by "
                    "client_order_id. It does not execute reconciliation or "
                    "mutate order/exchange state."
                ),
            },
        }
        read_routes = [
            item.surface
            for item in ADMIN_API_ROUTE_INVENTORY
            if item.module_id == "spot_operations"
            and item.action_class == AdminApiActionClass.READ_ONLY
        ]
        commands: list[SpotCommandSuiteCommandItem] = []
        for mutation_family, metadata in command_metadata.items():
            inventory_item = next(
                item
                for item in ADMIN_API_ROUTE_INVENTORY
                if item.surface == metadata["surface"]
            )
            method, route = _surface_method_and_path(inventory_item.surface)
            live_path = live_paths.get((method, route))
            if live_path is None:
                if mutation_family == AdminApiMutationFamilyType.SPOT_RECOVERY_EXCHANGE_STATE_PROOF:
                    missing_gate_chain = [
                        "approval_snapshot",
                        "admission_audit",
                        "cap_guard_decision",
                        "reconciliation_plan",
                        "exchange_state_capture_missing",
                    ]
                elif mutation_family == AdminApiMutationFamilyType.SPOT_RECOVERY_EXCHANGE_STATE_SNAPSHOT:
                    missing_gate_chain = [
                        "approval_snapshot",
                        "admission_audit",
                        "cap_guard_decision",
                        "reconciliation_plan",
                        "reconciliation_proof",
                        "completion_record",
                        "coinbase_live_read_disabled",
                    ]
                elif mutation_family == AdminApiMutationFamilyType.SPOT_RECOVERY_RECONCILIATION_EXECUTION:
                    missing_gate_chain = [
                        "approval_snapshot",
                        "admission_audit",
                        "cap_guard_decision",
                        "reconciliation_plan",
                        "reconciliation_proof",
                        "completion_record",
                        "exchange_state_snapshot",
                        "reconciliation_executor_disabled",
                        "coinbase_live_read_disabled",
                    ]
                elif mutation_family == AdminApiMutationFamilyType.SPOT_RECOVERY_RECONCILIATION_PROOF:
                    missing_gate_chain = [
                        "approval_snapshot",
                        "admission_audit",
                        "cap_guard_decision",
                        "reconciliation_plan",
                        "recovery_apply_audit_missing",
                        "reconciliation_execution_missing",
                    ]
                elif mutation_family == AdminApiMutationFamilyType.SPOT_RECOVERY_APPLY_EXECUTION:
                    missing_gate_chain = [
                        "approval_snapshot",
                        "admission_audit",
                        "cap_guard_decision",
                        "reconciliation_plan",
                        "live_execution_disabled",
                        "recovery_execution_disabled",
                        "post_apply_reconciliation_missing",
                    ]
                elif mutation_family == AdminApiMutationFamilyType.SPOT_RECOVERY_ROLLBACK_EXECUTION:
                    missing_gate_chain = [
                        "approval_snapshot",
                        "admission_audit",
                        "cap_guard_decision",
                        "reconciliation_plan",
                        "live_execution_disabled",
                        "recovery_execution_disabled",
                    ]
                else:
                    missing_gate_chain = [
                        "approval_snapshot",
                        "admission_audit",
                        "cap_guard_decision",
                        "reconciliation_plan",
                        "live_execution_disabled",
                    ]
                readiness_preconditions = []
                live_execution_status = AdminApiLiveExecutionStatus.LIVE_DISABLED
                live_adapter_configured = False
            else:
                missing_gate_chain = [
                    precondition.precondition.value
                    for precondition in live_path.readiness_preconditions
                    if precondition.blocking
                ]
                readiness_preconditions = list(live_path.readiness_preconditions)
                live_execution_status = live_path.status
                live_adapter_configured = live_path.live_execution_adapter.configured
            required_gate_chain = [
                "idempotency",
                "operator_intent",
                "payload_hash",
                "approval_snapshot",
                "approval_store_contract",
                "admission_audit",
                "cap_guard_decision",
                "reconciliation_plan",
                "live_execution_adapter",
                "live_execution_service",
                "post_live_reconciliation",
            ]
            commands.append(
                SpotCommandSuiteCommandItem(
                    mutation_family=mutation_family,
                    route=route,
                    method=method,
                    identity_key=str(metadata["identity_key"]),
                    action_class=inventory_item.action_class,
                    required_permission=inventory_item.permission,
                    shared_method=inventory_item.shared_method,
                    status=AdminApiGateStatus.BLOCKED,
                    live_execution_status=live_execution_status,
                    live_enabled=False,
                    live_eligible=False,
                    executable=False,
                    live_adapter_configured=live_adapter_configured,
                    approval_required=True,
                    cap_guard_required=True,
                    admission_audit_required=True,
                    reconciliation_required=True,
                    idempotency_required=True,
                    operator_intent_required=True,
                    payload_hash_required=True,
                    backend_owned=True,
                    route_bound=True,
                    browser_authority="display_only",
                    bff_authority="forward_only_no_execution",
                    product_scope="USDC spot command scope",
                    spot_rule_boundary=_enterprise_module_spot_boundary(
                        "spot_operations"
                    ),
                    required_gate_chain=required_gate_chain,
                    missing_gate_chain=missing_gate_chain,
                    readiness_preconditions=readiness_preconditions,
                    readiness_precondition_count=len(readiness_preconditions),
                    blocking_readiness_precondition_count=sum(
                        1
                        for precondition in readiness_preconditions
                        if precondition.blocking
                    ),
                    passed_readiness_precondition_count=sum(
                        1
                        for precondition in readiness_preconditions
                        if precondition.status == AdminApiGateStatus.PASSED
                    ),
                    backend_contract_refs=list(metadata["backend_contract_refs"]),
                    frontend_contract_refs=list(metadata["frontend_contract_refs"]),
                    documentation_refs=list(metadata["documentation_refs"]),
                    proof_routes=proof_routes_for_command(str(metadata["identity_key"])),
                    evidence=[
                        "Derived from ADMIN_API_ROUTE_INVENTORY and live-enablement readiness evidence.",
                        "Proof routes are derived from backend route inventory and remain local-state records until live admission passes.",
                        "No browser, BFF, route-local, or Coinbase execution authority is added.",
                        "Spot-only wallet, no-shorting, USDC, average-cost, and lot authority remain backend guard evidence.",
                    ],
                    detail=str(metadata["detail"]),
                )
            )

        spot_boundary = _enterprise_module_spot_boundary("spot_operations")
        gap_required_gate_chain = [
            "route_inventory_contract",
            "idempotency",
            "operator_intent",
            "payload_hash",
            "approval_snapshot",
            "admission_audit",
            "cap_guard_decision",
            "reconciliation_plan",
            "live_execution_adapter",
            "live_execution_service",
            "post_live_reconciliation",
        ]

        gap_evidence_route_docs = {
            "GET /api/v1/spot/sweep/status": [
                "README.spot-portfolio-sweep.md",
                "docs/COMMAND_WORKFLOWS.md",
            ],
            "GET /api/v1/spot/sweep/pnl": [
                "README.spot-portfolio-sweep.md",
                "docs/COMMAND_WORKFLOWS.md",
            ],
            "GET /api/v1/spot/cost-basis/status": [
                "README.spot-trading.md",
                "docs/COMMAND_WORKFLOWS.md",
            ],
            "GET /api/v1/spot/campaign/status": [
                "README.spot-campaign.md",
                "docs/COMMAND_WORKFLOWS.md",
            ],
            "GET /api/v1/spot/direct-orders/{client_order_id}/audit": [
                "README.spot-trading.md",
                "docs/OPERATOR_READ_MODELS.md",
            ],
            "GET /api/v1/spot/recovery/preview": [
                "README.spot-trading.md",
                "docs/COMMAND_WORKFLOWS.md",
                "docs/examples/admin-api.md",
            ],
            "GET /api/v1/spot/recovery/apply-review": [
                "README.spot-trading.md",
                "docs/COMMAND_WORKFLOWS.md",
                "docs/examples/admin-api.md",
            ],
            "GET /api/v1/spot/recovery/rollback-plan": [
                "README.spot-trading.md",
                "docs/COMMAND_WORKFLOWS.md",
                "docs/examples/admin-api.md",
            ],
            "GET /api/v1/spot/recovery/reconciliation-proof": [
                "README.spot-trading.md",
                "docs/COMMAND_WORKFLOWS.md",
                "docs/examples/admin-api.md",
            ],
            "GET /api/v1/admin/recovery-gate": [
                "README.admin-api.md",
                "docs/OPERATOR_READ_MODELS.md",
            ],
            "GET /api/v1/admin/reconciliation/plans": [
                "README.reconciliation-plans.md",
                "docs/examples/reconciliation-plans.md",
            ],
            "GET /api/v1/admin/reconciliation/plans/{plan_id}": [
                "README.reconciliation-plans.md",
                "docs/examples/reconciliation-plans.md",
            ],
            "GET /api/v1/spot/command-suite": [
                "docs/COMMAND_WORKFLOWS.md",
                "docs/examples/admin-api.md",
            ],
        }

        def coverage_gap_evidence_routes(
            surfaces: list[str],
        ) -> list[SpotCommandSuiteCoverageGapEvidenceRouteItem]:
            evidence_routes: list[SpotCommandSuiteCoverageGapEvidenceRouteItem] = []
            for surface in surfaces:
                inventory_item = inventory_by_surface[surface]
                method, route = _surface_method_and_path(inventory_item.surface)
                evidence_routes.append(
                    SpotCommandSuiteCoverageGapEvidenceRouteItem(
                        route=route,
                        method=method,
                        action_class=inventory_item.action_class,
                        required_permission=inventory_item.permission,
                        shared_method=inventory_item.shared_method,
                        backend_owned=True,
                        browser_authority="display_only",
                        bff_authority="read_only_forward",
                        documentation_refs=list(
                            gap_evidence_route_docs.get(surface, ["docs/COMMAND_WORKFLOWS.md"])
                        ),
                        detail=(
                            "Existing read-only Admin API evidence route for a "
                            "spot command-suite coverage gap; it does not create "
                            "a command route, execute reconciliation, or call Coinbase."
                        ),
                    )
                )
            return evidence_routes

        coverage_gaps = [
            SpotCommandSuiteCoverageGapItem(
                family=AdminApiSpotCommandSuiteGapFamily.SPOT_SWEEP_AUTOMATION,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                command_route="/api/v1/spot/sweep/automation-runs",
                current_read_evidence_routes=[
                    "GET /api/v1/spot/sweep/status",
                    "GET /api/v1/spot/campaign/status",
                    "GET /api/v1/spot/command-suite",
                ],
                current_read_evidence=coverage_gap_evidence_routes(
                    [
                        "GET /api/v1/spot/sweep/status",
                        "GET /api/v1/spot/campaign/status",
                        "GET /api/v1/spot/command-suite",
                    ]
                ),
                required_backend_contract=(
                    "Durable enterprise sweep scheduling, pause/resume, run-limit, "
                    "retry, execution-record, recovery, and reconciliation contract."
                ),
                required_gate_chain=gap_required_gate_chain,
                missing_contracts=[
                    "enterprise_sweep_scheduler_contract",
                    "sweep_run_limit_contract",
                    "sweep_pause_resume_contract",
                    "sweep_retry_recovery_contract",
                    "sweep_reconciliation_execution_contract",
                ],
                spot_rule_boundary=spot_boundary,
                documentation_refs=[
                    "README.spot-portfolio-sweep.md",
                    "README.spot-campaign.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                detail=(
                    "Sweep and campaign evidence is readable, but enterprise admin "
                    "sweep automation is not command-complete until durable "
                    "scheduler, run-limit, recovery, and reconciliation contracts "
                    "exist."
                ),
            ),
            SpotCommandSuiteCoverageGapItem(
                family=AdminApiSpotCommandSuiteGapFamily.SPOT_RECOVERY_WORKFLOW,
                exposure_status=AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED,
                command_route="/api/v1/spot/recovery/apply-executions",
                current_read_evidence_routes=[
                    "GET /api/v1/spot/recovery/preview",
                    "GET /api/v1/spot/recovery/apply-review",
                    "GET /api/v1/spot/recovery/rollback-plan",
                    "GET /api/v1/spot/recovery/reconciliation-proof",
                    "GET /api/v1/admin/recovery-gate",
                    "GET /api/v1/spot/direct-orders/{client_order_id}/audit",
                ],
                current_read_evidence=coverage_gap_evidence_routes(
                    [
                        "GET /api/v1/spot/recovery/preview",
                        "GET /api/v1/spot/recovery/apply-review",
                        "GET /api/v1/spot/recovery/rollback-plan",
                        "GET /api/v1/spot/recovery/reconciliation-proof",
                        "GET /api/v1/admin/recovery-gate",
                        "GET /api/v1/spot/direct-orders/{client_order_id}/audit",
                    ]
                ),
                required_backend_contract=(
                    "Spot recovery apply, rollback, exchange-state proof, "
                    "exchange-state snapshot, reconciliation-proof, and "
                    "guarded local repair result contracts with RBAC, "
                    "idempotency, append-only audit linkage, no-live execution "
                    "journals, guarded post-apply completion evidence, and "
                    "fail-closed reconciliation execution boundary evidence."
                ),
                required_gate_chain=[
                    "route_inventory_contract",
                    "recovery_preview",
                    "recovery_apply_review",
                    "idempotency",
                    "operator_intent",
                    "approval_snapshot",
                    "admission_audit",
                    "rollback_plan_contract",
                    "exchange_state_proof_record",
                    "exchange_state_snapshot_record",
                    "recovery_execution_journal",
                    "post_apply_reconciliation",
                    "post_apply_reconciliation_completion",
                    "reconciliation_execution_boundary",
                ],
                missing_contracts=[],
                spot_rule_boundary=spot_boundary,
                documentation_refs=[
                    "README.spot-trading.md",
                    "docs/OPERATOR_READ_MODELS.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                detail=(
                    "Spot recovery preview, recovery-gate, and direct-order audit "
                    "reads plus apply-review, rollback-plan, and reconciliation-proof "
                    "contract evidence now have backend proof record, no-live "
                    "execution journal, guarded local repair-result routes, "
                    "guarded post-apply completion evidence, and exchange-state "
                    "snapshot records. "
                    "They still do not roll back order state, execute "
                    "reconciliation, mutate order/exchange state, or call "
                    "Coinbase."
                ),
            ),
            SpotCommandSuiteCoverageGapItem(
                family=AdminApiSpotCommandSuiteGapFamily.SPOT_RECONCILIATION_WORKFLOW,
                exposure_status=AdminApiFunctionalityExposureStatus.BACKEND_CONTRACT_REQUIRED,
                command_route="/api/v1/spot/recovery/reconciliation-executions",
                current_read_evidence_routes=[
                    "GET /api/v1/spot/recovery/reconciliation-proof",
                    "GET /api/v1/admin/reconciliation/plans",
                    "GET /api/v1/admin/reconciliation/plans/{plan_id}",
                ],
                current_read_evidence=coverage_gap_evidence_routes(
                    [
                        "GET /api/v1/spot/recovery/reconciliation-proof",
                        "GET /api/v1/admin/reconciliation/plans",
                        "GET /api/v1/admin/reconciliation/plans/{plan_id}",
                    ]
                ),
                required_backend_contract=(
                    "Spot-specific reconciliation execution contract that can "
                    "compare backend order state with Coinbase evidence after "
                    "the disabled execution boundary route/service, backend "
                    "executor, and live Coinbase evidence read authority exist "
                    "without browser or BFF state mutation."
                ),
                required_gate_chain=[
                    "route_inventory_contract",
                    "reconciliation_plan",
                    "reconciliation_proof_contract",
                    "reconciliation_execution_boundary",
                    "exchange_evidence_snapshot",
                    "audit_link",
                    "proof_persistence",
                    "post_live_reconciliation",
                ],
                missing_contracts=[
                    "spot_reconciliation_execution_contract",
                    "spot_reconciliation_repair_policy_contract",
                ],
                spot_rule_boundary=spot_boundary,
                documentation_refs=[
                    "README.reconciliation-plans.md",
                    "docs/examples/reconciliation-plans.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                detail=(
                    "Reconciliation plan records are local-state evidence only. "
                    "The recovery reconciliation-proof read now exposes the "
                    "blocked execution boundary and disabled command route, "
                    "but plans and boundary evidence do not execute "
                    "reconciliation, mutate exchange/order state, or make "
                    "browser/BFF evidence authoritative."
                ),
            ),
        ]

        return SpotCommandSuiteResponse(
            approved_phase_range=AUTONOMOUS_APPROVED_PHASE_RANGE,
            status=AdminApiGateStatus.BLOCKED,
            command_count=len(commands),
            blocked_command_count=sum(
                1 for command in commands if command.status == AdminApiGateStatus.BLOCKED
            ),
            live_enabled_command_count=sum(
                1 for command in commands if command.live_enabled
            ),
            executable_command_count=sum(1 for command in commands if command.executable),
            spot_rules_platform_default=False,
            browser_authority="display_only",
            bff_authority="forward_only_no_execution",
            submitted_notional_usdc="0",
            executed_notional_usdc="0",
            commands=commands,
            coverage_gap_count=len(coverage_gaps),
            coverage_gaps=coverage_gaps,
            read_routes=read_routes,
            evidence=[
                "M54 starts with read-only spot command-suite coverage before execution.",
                "M54 gate linkage names backend proof routes for approval, admission audit, cap/guard, and reconciliation records.",
                "Manual order, cancel, and campaign command families remain live-blocked.",
                "Sweep automation, recovery workflow, and reconciliation workflow gaps remain explicit backend-owned evidence; spot recovery preview, apply-review, rollback-plan, reconciliation-proof, and execution-journal routes are backend-owned evidence while state repair and reconciliation execution remain blocked.",
                "Spot recovery reconciliation-proof readback exposes fail-closed reconciliation execution boundaries and backend-owned exchange-state snapshot rows while the executor and live Coinbase read authority remain blocked.",
                "Spot command readiness is not platform-wide authority for non-spot modules.",
            ],
            message=(
                "Spot command-suite coverage is backend-owned readiness evidence; "
                "live Coinbase execution remains disabled."
            ),
        )

    def build_spot_readiness(
        self,
        *,
        product_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        from dashboard_server import _build_spot_readiness_payload

        return _build_spot_readiness_payload(product_ids=product_ids)

    def build_spot_recovery_preview(
        self,
        *,
        state_file: str | None = None,
        run_id: str | None = None,
        config_id: str | None = None,
        client_order_id: str | None = None,
    ) -> SpotRecoveryPreviewResponse:
        """Return read-only spot recovery preview evidence."""

        from business.spot_portfolio_sweep import load_sweep_run_records
        from tools.run_spot_fill_backfill_recovery import DEFAULT_SWEEP_STATE_FILE
        from tools.run_spot_sweep_recovery_gate import build_sweep_recovery_gate_plan

        state_path = Path(state_file) if state_file else DEFAULT_SWEEP_STATE_FILE
        records = load_sweep_run_records(state_path)
        plan = build_sweep_recovery_gate_plan(
            records=records,
            state_file=state_path,
            run_id=run_id,
            config_id=config_id,
        )
        sweep_candidates: list[dict[str, Any]] = []
        for order in plan.get("backfill_orders") or []:
            if not isinstance(order, dict):
                continue
            identity_value = _string_or_none(order.get("client_order_id"))
            if not identity_value:
                continue
            sweep_candidates.append({
                "candidate_type": "fill_backfill",
                "identity_key": "client_order_id",
                "identity_value": identity_value,
                "preview_only": True,
                "required_next_contract": "spot_recovery_execution_journal",
            })

        direct_order_candidates: list[dict[str, Any]] = []
        if client_order_id:
            direct_order_candidates.append({
                "candidate_type": "direct_order_audit",
                "identity_key": "client_order_id",
                "identity_value": client_order_id,
                "preview_only": True,
                "required_next_contract": "spot_recovery_execution_journal",
            })

        sources = [
            SpotRecoveryPreviewSourceItem(
                name="sweep_recovery_gate_plan",
                status=(
                    AdminApiGateStatus.WARNING
                    if sweep_candidates
                    else AdminApiGateStatus.PASSED
                ),
                route="/api/v1/spot/recovery/preview",
                required_permission=AdminApiPermission.AUDIT_READ,
                shared_method="build_spot_recovery_preview",
                candidate_count=len(sweep_candidates),
                candidates=sweep_candidates,
                documentation_refs=[
                    "README.spot-portfolio-sweep.md",
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/examples/admin-api.md",
                ],
                detail=(
                    "Preview-only sweep recovery plan built from durable local "
                    "sweep records via build_sweep_recovery_gate_plan. Only "
                    "order-level rows with client_order_id become preview "
                    "candidates; run_id reconciliation evidence remains route "
                    "context, not candidate authority. No Coinbase reads, "
                    "Coinbase orders, repair apply, rollback, or reconciliation "
                    "execution ran."
                ),
            ),
            SpotRecoveryPreviewSourceItem(
                name="direct_order_audit_lookup",
                status=(
                    AdminApiGateStatus.WARNING
                    if direct_order_candidates
                    else AdminApiGateStatus.NOT_APPLICABLE
                ),
                route="/api/v1/spot/direct-orders/{client_order_id}/audit",
                required_permission=AdminApiPermission.AUDIT_READ,
                shared_method="build_spot_direct_order_audit",
                candidate_count=len(direct_order_candidates),
                candidates=direct_order_candidates,
                documentation_refs=[
                    "README.spot-trading.md",
                    "docs/OPERATOR_READ_MODELS.md",
                ],
                detail=(
                    "Direct-order recovery preview is keyed by client_order_id "
                    "and remains an audit lookup only. It does not cancel, "
                    "replace, backfill, repair, or reconcile orders."
                ),
            ),
            SpotRecoveryPreviewSourceItem(
                name="fill_ledger_health",
                status=AdminApiGateStatus.PASSED,
                route="/api/v1/admin/fill-ledger-health",
                required_permission=AdminApiPermission.AUDIT_READ,
                shared_method="build_fill_ledger_health",
                candidate_count=0,
                documentation_refs=[
                    "README.audit-workbench.md",
                    "docs/OPERATOR_READ_MODELS.md",
                ],
                detail=(
                    "Fill-ledger health is read-only evidence. Repair planning "
                    "or apply remains outside this preview route."
                ),
            ),
        ]
        candidate_count = sum(source.candidate_count for source in sources)
        return SpotRecoveryPreviewResponse(
            approved_phase_range=AUTONOMOUS_APPROVED_PHASE_RANGE,
            status=(
                AdminApiGateStatus.WARNING
                if candidate_count
                else AdminApiGateStatus.PASSED
            ),
            filters={
                "state_file": str(state_path),
                "run_id": run_id,
                "config_id": config_id,
                "client_order_id": client_order_id,
            },
            source_count=len(sources),
            candidate_count=candidate_count,
            sources=sources,
            current_read_evidence_routes=[
                "GET /api/v1/spot/recovery/preview",
                "GET /api/v1/spot/recovery/apply-review",
                "GET /api/v1/spot/recovery/rollback-plan",
                "GET /api/v1/spot/recovery/reconciliation-proof",
                "GET /api/v1/admin/recovery-gate",
                "GET /api/v1/admin/fill-ledger-health",
                "GET /api/v1/spot/direct-orders/{client_order_id}/audit",
            ],
            missing_contracts=[
            ],
            apply_review_contract_available=True,
            rollback_plan_contract_available=True,
            reconciliation_proof_contract_available=True,
            recovery_apply_available=True,
            rollback_plan_available=True,
            reconciliation_proof_available=True,
            spot_rule_boundary=_enterprise_module_spot_boundary("spot_operations"),
            detail=(
                "Spot recovery preview is backend-owned read-only evidence. It "
                "now links to read-only apply-review, rollback-plan, and "
                "reconciliation-proof contract evidence and backend-owned proof "
                "record plus execution-journal readback, but it does not apply "
                "state repairs, roll back order state, execute reconciliation, mutate "
                "order/exchange state, call Coinbase, or authorize browser/BFF "
                "recovery."
            ),
        )

    def _spot_recovery_contract_candidates(
        self,
        preview: SpotRecoveryPreviewResponse,
    ) -> list[SpotRecoveryContractCandidateItem]:
        candidates: list[SpotRecoveryContractCandidateItem] = []
        for source in preview.sources:
            for candidate in source.candidates:
                if candidate.get("identity_key") != "client_order_id":
                    continue
                identity_value = _string_or_none(candidate.get("identity_value"))
                if not identity_value:
                    continue
                candidates.append(
                    SpotRecoveryContractCandidateItem(
                        candidate_type=str(candidate.get("candidate_type", "unknown")),
                        identity_value=identity_value,
                        preview_source=source.name,
                        source_route=source.route,
                        preview_only=True,
                        detail=(
                            "Recovery contract evidence is keyed by client_order_id. "
                            "Exchange order ids, run ids, and config ids are context "
                            "only and are not internal recovery identities."
                        ),
                    )
                )
        return candidates

    def _spot_recovery_contract_routes(self) -> list[str]:
        return [
            "GET /api/v1/spot/recovery/preview",
            "GET /api/v1/spot/recovery/apply-review",
            "GET /api/v1/spot/recovery/rollback-plan",
            "GET /api/v1/spot/recovery/reconciliation-proof",
            "GET /api/v1/admin/recovery-gate",
            "GET /api/v1/admin/reconciliation/plans",
            "GET /api/v1/admin/reconciliation/plans/{plan_id}",
            "GET /api/v1/spot/direct-orders/{client_order_id}/audit",
        ]

    def _spot_recovery_filters(
        self,
        *,
        state_file: str | None,
        run_id: str | None,
        config_id: str | None,
        client_order_id: str | None,
    ) -> dict[str, Any]:
        return {
            "state_file": state_file,
            "run_id": run_id,
            "config_id": config_id,
            "client_order_id": client_order_id,
        }

    def _spot_recovery_contract_gate_evidence(
        self,
    ) -> list[SpotRecoveryContractGateItem]:
        return [
            SpotRecoveryContractGateItem(
                name="approval_snapshot",
                route="/api/v1/admin/approvals/requests",
                method="POST",
                action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
                required_permission=AdminApiPermission.APPROVAL_REQUEST,
                documentation_refs=[
                    "README.admin-api.md",
                    "docs/COMMAND_WORKFLOWS.md",
                    "docs/examples/admin-api.md",
                ],
                detail=(
                    "Recovery apply journal acceptance must bind an approval snapshot to the "
                    "exact client_order_id, route, payload hash, actor, and "
                    "operator intent. This route does not approve execution."
                ),
            ),
            SpotRecoveryContractGateItem(
                name="admission_audit",
                route="/api/v1/admin/admission-audits",
                method="POST",
                action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
                required_permission=AdminApiPermission.ADMISSION_AUDIT_RECORD,
                documentation_refs=[
                    "README.admission-audits.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                detail=(
                    "Recovery apply journal acceptance must append admission audit evidence "
                    "before a journal row is accepted. The audit record cannot mark live admission "
                    "allowed by itself."
                ),
            ),
            SpotRecoveryContractGateItem(
                name="cap_guard_decision",
                route="/api/v1/admin/cap-guard/decisions",
                method="POST",
                action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
                required_permission=AdminApiPermission.CAP_GUARD_RECORD,
                documentation_refs=[
                    "README.cap-guard-decisions.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                detail=(
                    "Recovery apply journal acceptance must link backend cap/guard evidence. "
                    "The browser and BFF must not evaluate wallet, inventory, "
                    "profitability, margin, or account limits."
                ),
            ),
            SpotRecoveryContractGateItem(
                name="rollback_plan_contract",
                route="/api/v1/spot/recovery/rollback-plan",
                method="GET",
                required_permission=AdminApiPermission.AUDIT_READ,
                documentation_refs=[
                    "README.spot-trading.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                detail=(
                    "Rollback-plan evidence is readable for review only. It does "
                    "not perform rollback or repair state."
                ),
            ),
            SpotRecoveryContractGateItem(
                name="reconciliation_proof_contract",
                route="/api/v1/spot/recovery/reconciliation-proof",
                method="GET",
                required_permission=AdminApiPermission.AUDIT_READ,
                documentation_refs=[
                    "README.reconciliation-plans.md",
                    "docs/COMMAND_WORKFLOWS.md",
                ],
                detail=(
                    "Reconciliation-proof evidence describes required proof fields "
                    "only. It does not write proof, execute reconciliation, or "
                    "mutate order/exchange state."
                ),
            ),
        ]

    def _spot_recovery_proof_records(
        self,
        *,
        client_order_id: str | None,
    ) -> list[SpotRecoveryProofRecordItem]:
        if client_order_id:
            records = self.spot_recovery_proof_store.read_for_client_order_id(
                client_order_id,
                limit=20,
            )
        else:
            records = self.spot_recovery_proof_store.read_recent(limit=20)
        return [_spot_recovery_proof_item_from_record(record) for record in records]

    def _spot_recovery_snapshot_records(
        self,
        *,
        client_order_id: str | None,
    ) -> list[SpotRecoveryExchangeStateSnapshotRecordItem]:
        if client_order_id:
            records = self.spot_recovery_snapshot_store.read_for_client_order_id(
                client_order_id,
                limit=20,
            )
        else:
            records = self.spot_recovery_snapshot_store.read_recent(limit=20)
        return [
            _spot_recovery_snapshot_item_from_record(record)
            for record in records
        ]

    def _spot_recovery_execution_records(
        self,
        *,
        client_order_id: str | None,
    ) -> list[SpotRecoveryExecutionRecordItem]:
        if client_order_id:
            records = self.spot_recovery_execution_store.read_for_client_order_id(
                client_order_id,
                limit=20,
            )
        else:
            records = self.spot_recovery_execution_store.read_recent(limit=20)
        items = [
            _spot_recovery_execution_item_from_record(record)
            for record in records
        ]
        proof_records = self._spot_recovery_proof_records(
            client_order_id=client_order_id
        )
        proof_by_apply_audit = {
            proof.recovery_apply_audit_id: proof
            for proof in proof_records
            if proof.recovery_apply_audit_id and proof.reconciliation_proof_id
        }
        hydrated: list[SpotRecoveryExecutionRecordItem] = []
        for item in items:
            proof = proof_by_apply_audit.get(item.audit_id)
            if proof is None:
                hydrated.append(item)
                continue
            hydrated.append(
                item.model_copy(
                    update={
                        "reconciliation_proof_id": proof.reconciliation_proof_id,
                        "post_apply_reconciliation_satisfied": True,
                    }
                )
            )
        return hydrated

    def _spot_recovery_repair_result_records(
        self,
        *,
        client_order_id: str | None,
    ) -> list[SpotRecoveryRepairResultRecordItem]:
        if client_order_id:
            records = self.spot_recovery_repair_result_store.read_for_client_order_id(
                client_order_id,
                limit=20,
            )
        else:
            records = self.spot_recovery_repair_result_store.read_recent(limit=20)
        return [
            _spot_recovery_repair_result_item_from_record(record)
            for record in records
        ]

    def _spot_recovery_completion_records(
        self,
        *,
        client_order_id: str | None,
    ) -> list[SpotRecoveryCompletionRecordItem]:
        if client_order_id:
            records = self.spot_recovery_completion_store.read_for_client_order_id(
                client_order_id,
                limit=20,
            )
        else:
            records = self.spot_recovery_completion_store.read_recent(limit=20)
        return [
            _spot_recovery_completion_item_from_record(record)
            for record in records
        ]

    def _spot_recovery_state_repair_taxonomy(
        self,
    ) -> list[SpotRecoveryStateRepairTaxonomyItem]:
        return [
            SpotRecoveryStateRepairTaxonomyItem(
                category=SpotRecoveryRepairCategory.FILL_BACKFILL_LEDGER,
                allowed_local_state_scope=["fill_ledger"],
                required_evidence=[
                    "client_order_id",
                    "exchange_state_proof_id",
                    "reconciliation_plan_id",
                    "pre_apply_snapshot_id",
                    "dry_run_repair_plan_id",
                ],
                rejected_mutations=[
                    "coinbase_rest_read",
                    "coinbase_order_submission",
                    "exchange_state_mutation",
                    "browser_repair_apply",
                ],
                fill_ledger_mutation_allowed=True,
                detail=(
                    "Fill-backfill ledger repair is an allowed local category "
                    "only after backend guard evidence exists. This read model "
                    "does not apply the repair."
                ),
            ),
            SpotRecoveryStateRepairTaxonomyItem(
                category=SpotRecoveryRepairCategory.DIRECT_ORDER_AUDIT_LINK,
                allowed_local_state_scope=["admin_api_audit_log"],
                required_evidence=[
                    "client_order_id",
                    "audit_id",
                    "approval_snapshot_id",
                    "admission_audit_id",
                    "cap_guard_decision_id",
                ],
                rejected_mutations=[
                    "coinbase_rest_read",
                    "coinbase_order_submission",
                    "exchange_state_mutation",
                    "browser_audit_writer",
                ],
                detail=(
                    "Direct-order audit linkage is backend-owned local "
                    "evidence only. It cannot become browser authority or "
                    "exchange truth."
                ),
            ),
            SpotRecoveryStateRepairTaxonomyItem(
                category=SpotRecoveryRepairCategory.RECOVERY_PROOF_LINKAGE,
                allowed_local_state_scope=["spot_recovery_proof_log"],
                required_evidence=[
                    "exchange_state_proof_id",
                    "reconciliation_proof_id",
                    "recovery_apply_audit_id",
                    "reconciliation_plan_id",
                ],
                rejected_mutations=[
                    "coinbase_rest_read",
                    "coinbase_order_submission",
                    "order_state_mutation",
                    "browser_proof_writer",
                ],
                detail=(
                    "Recovery proof linkage is append-only proof evidence. "
                    "It does not reconcile, repair, or mutate order state."
                ),
            ),
            SpotRecoveryStateRepairTaxonomyItem(
                category=(
                    SpotRecoveryRepairCategory.RECONCILIATION_COMPLETION_MARK
                ),
                allowed_local_state_scope=["reconciliation_evidence"],
                required_evidence=[
                    "reconciliation_proof_id",
                    "post_apply_state_snapshot_id",
                    "recovery_apply_journal_id",
                    "reconciliation_plan_id",
                ],
                rejected_mutations=[
                    "coinbase_rest_read",
                    "coinbase_order_submission",
                    "exchange_state_mutation",
                    "browser_reconciliation_execution",
                ],
                reconciliation_state_mutation_allowed=True,
                detail=(
                    "Reconciliation completion may only mark backend-owned "
                    "local completion after proof evidence exists; it is not "
                    "reconciliation execution."
                ),
            ),
        ]

    def _spot_recovery_target_evidence(
        self,
        *,
        candidates: list[SpotRecoveryContractCandidateItem],
        proof_records: list[SpotRecoveryProofRecordItem],
        execution_records: list[SpotRecoveryExecutionRecordItem],
        repair_result_records: list[SpotRecoveryRepairResultRecordItem],
        completion_records: list[SpotRecoveryCompletionRecordItem],
    ) -> tuple[
        list[SpotRecoveryRepairTargetItem],
        list[SpotRecoveryPreApplySnapshotItem],
        list[SpotRecoveryDryRunRepairPlanItem],
        list[SpotRecoveryCompletionStateItem],
    ]:
        targets: list[SpotRecoveryRepairTargetItem] = []
        snapshots: list[SpotRecoveryPreApplySnapshotItem] = []
        dry_run_plans: list[SpotRecoveryDryRunRepairPlanItem] = []
        completion_states: list[SpotRecoveryCompletionStateItem] = []

        candidate_by_client_order_id = {
            candidate.identity_value: candidate
            for candidate in candidates
        }
        for record in execution_records:
            if record.client_order_id not in candidate_by_client_order_id:
                candidate_by_client_order_id[record.client_order_id] = (
                    SpotRecoveryContractCandidateItem(
                        candidate_type="execution_journal_readback",
                        identity_value=record.client_order_id,
                        preview_source="spot_recovery_execution_journal",
                        source_route=record.route,
                        preview_only=False,
                        detail=(
                            "Execution journal readback created this repair "
                            "target; client_order_id remains the identity."
                        ),
                    )
                )
        for proof in proof_records:
            if proof.client_order_id not in candidate_by_client_order_id:
                candidate_by_client_order_id[proof.client_order_id] = (
                    SpotRecoveryContractCandidateItem(
                        candidate_type="proof_record_readback",
                        identity_value=proof.client_order_id,
                        preview_source="spot_recovery_proof_log",
                        source_route=proof.route,
                        preview_only=False,
                        detail=(
                            "Proof record readback created this repair target; "
                            "client_order_id remains the identity."
                        ),
                    )
                )
        for completion in completion_records:
            if completion.client_order_id not in candidate_by_client_order_id:
                candidate_by_client_order_id[completion.client_order_id] = (
                    SpotRecoveryContractCandidateItem(
                        candidate_type="completion_record_readback",
                        identity_value=completion.client_order_id,
                        preview_source="spot_recovery_completion_journal",
                        source_route=completion.route,
                        preview_only=False,
                        detail=(
                            "Completion record readback created this repair "
                            "target; client_order_id remains the identity."
                        ),
                    )
                )

        for client_order_id, candidate in sorted(
            candidate_by_client_order_id.items()
        ):
            related_executions = [
                record
                for record in execution_records
                if record.client_order_id == client_order_id
            ]
            related_proofs = [
                record
                for record in proof_records
                if record.client_order_id == client_order_id
            ]
            related_repair_results = [
                record
                for record in repair_result_records
                if record.client_order_id == client_order_id
            ]
            related_completions = [
                record
                for record in completion_records
                if record.client_order_id == client_order_id
            ]
            target_id = next(
                (
                    record.repair_target_id
                    for record in [*related_executions, *related_repair_results]
                    if record.repair_target_id
                ),
                _stable_read_id(
                    "spot-recovery-repair-target",
                    client_order_id,
                    candidate.candidate_type,
                ),
            )
            snapshot_id = next(
                (
                    record.pre_apply_snapshot_id
                    for record in [*related_executions, *related_repair_results]
                    if record.pre_apply_snapshot_id
                ),
                _stable_read_id(
                    "spot-recovery-pre-apply-snapshot",
                    client_order_id,
                    target_id,
                ),
            )
            dry_run_plan_id = next(
                (
                    record.dry_run_repair_plan_id
                    for record in [*related_executions, *related_repair_results]
                    if record.dry_run_repair_plan_id
                ),
                _stable_read_id(
                    "spot-recovery-dry-run-repair-plan",
                    client_order_id,
                    target_id,
                ),
            )
            latest_apply = next(
                (
                    record
                    for record in related_executions
                    if record.mutation_family
                    == AdminApiMutationFamilyType.SPOT_RECOVERY_APPLY_EXECUTION
                ),
                None,
            )
            latest_rollback = next(
                (
                    record
                    for record in related_executions
                    if record.mutation_family
                    == AdminApiMutationFamilyType.SPOT_RECOVERY_ROLLBACK_EXECUTION
                ),
                None,
            )
            reconciliation_proof_satisfied = any(
                proof.reconciliation_proof_id for proof in related_proofs
            ) or any(
                record.post_apply_reconciliation_satisfied
                for record in related_executions
            ) or any(
                record.reconciliation_proof_satisfied
                for record in related_completions
            )
            latest_completion = next(
                (
                    record
                    for record in related_completions
                    if record.post_apply_reconciliation_completed
                ),
                None,
            )
            fully_reconciled = latest_completion is not None
            repair_result = next(
                (record for record in related_repair_results if record.repair_applied),
                None,
            )
            rollback_result = next(
                (record for record in related_repair_results if record.rollback_applied),
                None,
            )
            state = SpotRecoveryCompletionState.REPAIR_BLOCKED
            if fully_reconciled:
                state = SpotRecoveryCompletionState.FULLY_RECONCILED
            elif rollback_result is not None:
                state = SpotRecoveryCompletionState.ROLLBACK_APPLIED
            elif repair_result is not None:
                state = SpotRecoveryCompletionState.REPAIR_APPLIED
            elif latest_rollback is not None:
                state = SpotRecoveryCompletionState.ROLLBACK_APPLIED
            elif reconciliation_proof_satisfied:
                state = (
                    SpotRecoveryCompletionState.RECONCILIATION_PROOF_SATISFIED
                )
            elif latest_apply is not None:
                state = SpotRecoveryCompletionState.JOURNAL_ACCEPTED
            elif candidate.preview_only:
                state = SpotRecoveryCompletionState.DRY_RUN_REPAIR_PLANNED

            execution_journal_ids = [
                record.journal_id for record in related_executions
            ]
            proof_ids = [record.proof_id for record in related_proofs]
            repair_result_ids = [
                record.repair_result_id for record in related_repair_results
            ]
            completion_ids = [
                record.completion_id for record in related_completions
            ]
            rollback_plan_ids = sorted({
                record.rollback_plan_id
                for record in related_executions
                if record.rollback_plan_id
            } | {f"rollback-plan:{client_order_id}"})
            audit_ids = sorted({
                record.audit_id
                for record in [*related_executions, *related_proofs]
                if record.audit_id
            })
            reconciliation_plan_ids = sorted({
                record.reconciliation_plan_id
                for record in [*related_executions, *related_proofs]
                if record.reconciliation_plan_id
            })

            categories = [SpotRecoveryRepairCategory.FILL_BACKFILL_LEDGER]
            if candidate.candidate_type == "direct_order_audit":
                categories = [SpotRecoveryRepairCategory.DIRECT_ORDER_AUDIT_LINK]
            if related_proofs:
                categories.append(SpotRecoveryRepairCategory.RECOVERY_PROOF_LINKAGE)
            if fully_reconciled:
                categories.append(
                    SpotRecoveryRepairCategory.RECONCILIATION_COMPLETION_MARK
                )

            targets.append(
                SpotRecoveryRepairTargetItem(
                    target_id=target_id,
                    client_order_id=client_order_id,
                    candidate_type=candidate.candidate_type,
                    preview_source=candidate.preview_source,
                    source_route=candidate.source_route,
                    categories=list(dict.fromkeys(categories)),
                    execution_journal_ids=execution_journal_ids,
                    repair_result_ids=repair_result_ids,
                    completion_ids=completion_ids,
                    latest_apply_journal_id=(
                        latest_apply.journal_id if latest_apply else None
                    ),
                    latest_rollback_journal_id=(
                        latest_rollback.journal_id if latest_rollback else None
                    ),
                    exchange_state_proof_ids=[
                        proof.exchange_state_proof_id
                        for proof in related_proofs
                        if proof.exchange_state_proof_id
                    ],
                    reconciliation_proof_ids=[
                        proof.reconciliation_proof_id
                        for proof in related_proofs
                        if proof.reconciliation_proof_id
                    ],
                    rollback_plan_ids=rollback_plan_ids,
                    audit_ids=audit_ids,
                    reconciliation_plan_ids=reconciliation_plan_ids,
                    pre_apply_snapshot_id=snapshot_id,
                    dry_run_repair_plan_id=dry_run_plan_id,
                    completion_state=state,
                    post_apply_reconciliation_completed=fully_reconciled,
                    fully_reconciled=fully_reconciled,
                    state_repair_available=bool(related_repair_results),
                    state_repair_executed=bool(related_repair_results),
                    detail=(
                        "Repair target is backend-owned evidence keyed by "
                        "client_order_id. Guarded local repair result evidence "
                        "is backend-only and does not use order_id."
                    ),
                )
            )
            snapshots.append(
                SpotRecoveryPreApplySnapshotItem(
                    snapshot_id=snapshot_id,
                    target_id=target_id,
                    client_order_id=client_order_id,
                    execution_journal_ids=execution_journal_ids,
                    proof_ids=proof_ids,
                    repair_result_ids=repair_result_ids,
                    rollback_plan_ids=rollback_plan_ids,
                    audit_ids=audit_ids,
                    reconciliation_plan_ids=reconciliation_plan_ids,
                    detail=(
                        "Pre-apply snapshot evidence is required before any "
                        "future local state repair can run. This snapshot is "
                        "not captured as mutable state in the current phase."
                    ),
                )
            )
            dry_run_plans.append(
                SpotRecoveryDryRunRepairPlanItem(
                    repair_plan_id=dry_run_plan_id,
                    target_id=target_id,
                    client_order_id=client_order_id,
                    categories=list(dict.fromkeys(categories)),
                    intended_local_mutations=[
                        category.value for category in dict.fromkeys(categories)
                    ],
                    rejected_mutations=[
                        "coinbase_rest_read",
                        "coinbase_order_submission",
                        "exchange_state_mutation",
                        "browser_repair_apply",
                    ],
                    required_guard_chain=[
                        "execution_journal",
                        "pre_apply_snapshot",
                        "exchange_state_proof",
                        "approval_snapshot",
                        "admission_audit",
                        "cap_guard_decision",
                        "reconciliation_plan",
                        "operator_intent",
                        "payload_hash",
                    ],
                    pre_apply_snapshot_id=snapshot_id,
                    detail=(
                        "Dry-run repair plan lists intended local categories "
                        "and rejected mutations only. It does not mutate order, "
                        "fill-ledger, reconciliation, or exchange state."
                    ),
                )
            )
            completion_states.append(
                SpotRecoveryCompletionStateItem(
                    client_order_id=client_order_id,
                    target_id=target_id,
                    state=state,
                    completion_id=(
                        latest_completion.completion_id
                        if latest_completion
                        else None
                    ),
                    journal_accepted=latest_apply is not None,
                    repair_applied=repair_result is not None,
                    rollback_applied=(
                        latest_rollback is not None or rollback_result is not None
                    ),
                    reconciliation_proof_satisfied=reconciliation_proof_satisfied,
                    post_apply_reconciliation_completed=fully_reconciled,
                    fully_reconciled=fully_reconciled,
                    detail=(
                        "Completion state is derived from backend proof, "
                        "journal, repair-result, and completion evidence. "
                        "Full reconciliation means only the guarded local "
                        "completion record exists; it is not reconciliation "
                        "execution or exchange mutation."
                    ),
                )
            )
        return targets, snapshots, dry_run_plans, completion_states

    def _spot_recovery_reconciliation_execution_boundaries(
        self,
        *,
        candidates: list[SpotRecoveryContractCandidateItem],
        snapshot_records: list[SpotRecoveryExchangeStateSnapshotRecordItem],
        proof_records: list[SpotRecoveryProofRecordItem],
        execution_records: list[SpotRecoveryExecutionRecordItem],
        repair_result_records: list[SpotRecoveryRepairResultRecordItem],
        completion_records: list[SpotRecoveryCompletionRecordItem],
    ) -> list[SpotRecoveryReconciliationExecutionBoundaryItem]:
        required_inputs = [
            "client_order_id",
            "product_id",
            "exchange_state_snapshot_id",
            "source_timestamp",
            "reconciliation_plan_id",
            "reconciliation_proof_id",
            "completion_id",
            "approval_snapshot_id",
            "admission_audit_id",
            "cap_guard_decision_id",
            "idempotency_key",
            "payload_hash",
            "operator_intent",
        ]

        def first_present(*values: str | None) -> str | None:
            return next((value for value in values if value), None)

        def attr(record: Any, name: str) -> str | None:
            if record is None:
                return None
            value = getattr(record, name, None)
            enum_value = getattr(value, "value", None)
            if enum_value is not None:
                return _string_or_none(enum_value)
            return _string_or_none(value)

        def first_record(
            records: list[Any],
            *,
            preferred: str | None = None,
        ) -> Any | None:
            if preferred is None:
                return records[0] if records else None
            return next(
                (record for record in records if bool(getattr(record, preferred))),
                records[0] if records else None,
            )

        client_order_ids = {
            candidate.identity_value
            for candidate in candidates
            if candidate.identity_key == "client_order_id"
        }
        client_order_ids.update(record.client_order_id for record in snapshot_records)
        client_order_ids.update(record.client_order_id for record in proof_records)
        client_order_ids.update(record.client_order_id for record in execution_records)
        client_order_ids.update(
            record.client_order_id for record in repair_result_records
        )
        client_order_ids.update(record.client_order_id for record in completion_records)

        boundaries: list[SpotRecoveryReconciliationExecutionBoundaryItem] = []
        for client_order_id in sorted(client_order_ids):
            related_completions = [
                record
                for record in completion_records
                if record.client_order_id == client_order_id
            ]
            related_proofs = [
                record
                for record in proof_records
                if record.client_order_id == client_order_id
            ]
            related_snapshots = [
                record
                for record in snapshot_records
                if record.client_order_id == client_order_id
            ]
            related_executions = [
                record
                for record in execution_records
                if record.client_order_id == client_order_id
            ]
            related_repair_results = [
                record
                for record in repair_result_records
                if record.client_order_id == client_order_id
            ]
            latest_completion = first_record(
                related_completions,
                preferred="post_apply_reconciliation_completed",
            )
            latest_proof = first_record(
                related_proofs,
                preferred="reconciliation_proof_id",
            )
            latest_snapshot = first_record(
                related_snapshots,
                preferred="exchange_state_snapshot_id",
            )
            latest_execution = next(
                (
                    record
                    for record in related_executions
                    if record.mutation_family
                    == AdminApiMutationFamilyType.SPOT_RECOVERY_APPLY_EXECUTION
                ),
                related_executions[0] if related_executions else None,
            )
            latest_repair_result = first_record(
                related_repair_results,
                preferred="repair_applied",
            )

            def evidence_value(name: str) -> str | None:
                return first_present(
                    attr(latest_snapshot, name),
                    attr(latest_completion, name),
                    attr(latest_proof, name),
                    attr(latest_repair_result, name),
                    attr(latest_execution, name),
                )

            product_id = evidence_value("product_id")
            exchange_state_snapshot_id = evidence_value("exchange_state_snapshot_id")
            source_timestamp = evidence_value("source_timestamp")
            snapshot_source = attr(latest_snapshot, "snapshot_source")
            snapshot_evidence_ref = attr(latest_snapshot, "snapshot_evidence_ref")
            reconciliation_plan_id = evidence_value("reconciliation_plan_id")
            reconciliation_proof_id = evidence_value("reconciliation_proof_id")
            approval_snapshot_id = evidence_value("approval_snapshot_id")
            admission_audit_id = evidence_value("admission_audit_id")
            cap_guard_decision_id = evidence_value("cap_guard_decision_id")
            idempotency_key = evidence_value("idempotency_key")
            payload_hash = evidence_value("payload_hash")
            operator_intent = evidence_value("operator_intent")
            completion_id = attr(latest_completion, "completion_id")
            repair_result_id = attr(latest_repair_result, "repair_result_id")
            journal_id = first_present(
                attr(latest_completion, "journal_id"),
                attr(latest_execution, "journal_id"),
            )
            input_values = {
                "client_order_id": client_order_id,
                "product_id": product_id,
                "exchange_state_snapshot_id": exchange_state_snapshot_id,
                "source_timestamp": source_timestamp,
                "reconciliation_plan_id": reconciliation_plan_id,
                "reconciliation_proof_id": reconciliation_proof_id,
                "completion_id": completion_id,
                "approval_snapshot_id": approval_snapshot_id,
                "admission_audit_id": admission_audit_id,
                "cap_guard_decision_id": cap_guard_decision_id,
                "idempotency_key": idempotency_key,
                "payload_hash": payload_hash,
                "operator_intent": operator_intent,
            }
            present_inputs = [
                name for name in required_inputs if input_values.get(name)
            ]
            missing_inputs = [
                name for name in required_inputs if name not in present_inputs
            ]
            boundary_id = _stable_read_id(
                "spot-recovery-reconciliation-execution-boundary",
                client_order_id,
                str(reconciliation_plan_id or ""),
                str(reconciliation_proof_id or ""),
                str(completion_id or ""),
                str(exchange_state_snapshot_id or ""),
            )
            blockers = [
                "spot_reconciliation_execution_contract_missing",
                "reconciliation_executor_disabled",
                "coinbase_live_read_disabled",
                "browser_bff_execution_authority_rejected",
            ]
            blockers.extend(f"{name}_missing" for name in missing_inputs)
            boundaries.append(
                SpotRecoveryReconciliationExecutionBoundaryItem(
                    boundary_id=boundary_id,
                    client_order_id=client_order_id,
                    command_route=(
                        "/api/v1/spot/recovery/reconciliation-executions"
                    ),
                    method="POST",
                    route_inventory_status=AdminApiGateStatus.PASSED,
                    action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
                    required_permission=AdminApiPermission.SPOT_RECOVERY_EXECUTE,
                    service_method="execute_spot_recovery_reconciliation",
                    product_id=product_id,
                    exchange_state_snapshot_id=exchange_state_snapshot_id,
                    source_timestamp=source_timestamp,
                    snapshot_source=snapshot_source,
                    snapshot_evidence_ref=snapshot_evidence_ref,
                    reconciliation_plan_id=reconciliation_plan_id,
                    reconciliation_proof_id=reconciliation_proof_id,
                    completion_id=completion_id,
                    repair_result_id=repair_result_id,
                    journal_id=journal_id,
                    approval_snapshot_id=approval_snapshot_id,
                    admission_audit_id=admission_audit_id,
                    cap_guard_decision_id=cap_guard_decision_id,
                    idempotency_key=idempotency_key,
                    payload_hash=payload_hash,
                    operator_intent=operator_intent,
                    required_inputs=required_inputs,
                    present_inputs=present_inputs,
                    missing_inputs=missing_inputs,
                    blockers=blockers,
                    missing_contracts=[
                        "spot_reconciliation_execution_contract",
                    ],
                    route_bound=True,
                    snapshot_recorded=latest_snapshot is not None,
                    source_trusted=(
                        latest_snapshot.source_trusted
                        if latest_snapshot is not None
                        else False
                    ),
                    coinbase_read_attempted=(
                        latest_snapshot.coinbase_read_attempted
                        if latest_snapshot is not None
                        else False
                    ),
                    coinbase_read_succeeded=(
                        latest_snapshot.coinbase_read_succeeded
                        if latest_snapshot is not None
                        else False
                    ),
                    detail=(
                        "Spot recovery reconciliation execution is blocked. "
                        "Completion/proof evidence may exist and a backend "
                        "route/service boundary plus snapshot contract are now "
                        "present, but the reconciliation executor, live Coinbase "
                        "read authority, and browser/BFF execution authority "
                        "remain unavailable."
                    ),
                )
            )
        return boundaries

    def build_spot_recovery_apply_review(
        self,
        *,
        state_file: str | None = None,
        run_id: str | None = None,
        config_id: str | None = None,
        client_order_id: str | None = None,
    ) -> SpotRecoveryApplyReviewResponse:
        """Return fail-closed Spot recovery apply-review contract evidence."""

        preview = self.build_spot_recovery_preview(
            state_file=state_file,
            run_id=run_id,
            config_id=config_id,
            client_order_id=client_order_id,
        )
        candidates = self._spot_recovery_contract_candidates(preview)
        persisted_executions = self._spot_recovery_execution_records(
            client_order_id=client_order_id
        )
        persisted_proofs = self._spot_recovery_proof_records(
            client_order_id=client_order_id
        )
        persisted_repair_results = self._spot_recovery_repair_result_records(
            client_order_id=client_order_id
        )
        persisted_completions = self._spot_recovery_completion_records(
            client_order_id=client_order_id
        )
        (
            repair_targets,
            pre_apply_snapshots,
            dry_run_repair_plans,
            completion_states,
        ) = self._spot_recovery_target_evidence(
            candidates=candidates,
            proof_records=persisted_proofs,
            execution_records=persisted_executions,
            repair_result_records=persisted_repair_results,
            completion_records=persisted_completions,
        )
        latest_apply_journal_id = next(
            (
                record.journal_id
                for record in persisted_executions
                if record.mutation_family
                == AdminApiMutationFamilyType.SPOT_RECOVERY_APPLY_EXECUTION
            ),
            None,
        )
        post_apply_satisfied_count = len({
            record.audit_id
            for record in persisted_executions
            if record.post_apply_reconciliation_satisfied
        } | {
            record.audit_id for record in persisted_completions
        })
        return SpotRecoveryApplyReviewResponse(
            approved_phase_range=AUTONOMOUS_APPROVED_PHASE_RANGE,
            status=AdminApiGateStatus.BLOCKED,
            filters=self._spot_recovery_filters(
                state_file=state_file,
                run_id=run_id,
                config_id=config_id,
                client_order_id=client_order_id,
            ),
            candidate_count=len(candidates),
            candidates=candidates,
            current_read_evidence_routes=self._spot_recovery_contract_routes(),
            required_gate_chain=[
                "client_order_id_identity",
                "approval_snapshot",
                "admission_audit",
                "cap_guard_decision",
                "rollback_plan_contract",
                "exchange_state_proof_record",
                "recovery_apply_execution_journal",
                "state_repair_taxonomy",
                "repair_target_model",
                "pre_apply_snapshot",
                "dry_run_repair_plan",
                "post_apply_reconciliation",
            ],
            contract_gate_evidence=self._spot_recovery_contract_gate_evidence(),
            state_repair_taxonomy=self._spot_recovery_state_repair_taxonomy(),
            repair_targets=repair_targets,
            pre_apply_snapshots=pre_apply_snapshots,
            dry_run_repair_plans=dry_run_repair_plans,
            completion_states=completion_states,
            persisted_execution_count=len(persisted_executions),
            persisted_executions=persisted_executions,
            persisted_repair_result_count=len(persisted_repair_results),
            persisted_repair_results=persisted_repair_results,
            latest_apply_journal_id=latest_apply_journal_id,
            latest_repair_result_id=(
                persisted_repair_results[0].repair_result_id
                if persisted_repair_results
                else None
            ),
            post_apply_reconciliation_satisfied_count=post_apply_satisfied_count,
            missing_contracts=[],
            state_repair_contract_available=True,
            spot_rule_boundary=_enterprise_module_spot_boundary("spot_operations"),
            detail=(
                "Spot recovery apply review is a backend-owned contract evidence "
                "route. It describes required gates, guarded local repair "
                "result evidence, append-only apply journal rows, and guarded "
                "post-apply completion evidence for candidate client_order_id "
                "values, but it does not mutate order/exchange state, execute "
                "reconciliation, call Coinbase, or authorize browser/BFF recovery."
            ),
        )

    def build_spot_recovery_rollback_plan(
        self,
        *,
        state_file: str | None = None,
        run_id: str | None = None,
        config_id: str | None = None,
        client_order_id: str | None = None,
    ) -> SpotRecoveryRollbackPlanResponse:
        """Return read-only Spot recovery rollback-plan contract evidence."""

        preview = self.build_spot_recovery_preview(
            state_file=state_file,
            run_id=run_id,
            config_id=config_id,
            client_order_id=client_order_id,
        )
        candidates = self._spot_recovery_contract_candidates(preview)
        persisted_executions = self._spot_recovery_execution_records(
            client_order_id=client_order_id
        )
        persisted_proofs = self._spot_recovery_proof_records(
            client_order_id=client_order_id
        )
        persisted_repair_results = self._spot_recovery_repair_result_records(
            client_order_id=client_order_id
        )
        persisted_completions = self._spot_recovery_completion_records(
            client_order_id=client_order_id
        )
        (
            repair_targets,
            pre_apply_snapshots,
            dry_run_repair_plans,
            completion_states,
        ) = self._spot_recovery_target_evidence(
            candidates=candidates,
            proof_records=persisted_proofs,
            execution_records=persisted_executions,
            repair_result_records=persisted_repair_results,
            completion_records=persisted_completions,
        )
        latest_rollback_journal_id = next(
            (
                record.journal_id
                for record in persisted_executions
                if record.mutation_family
                == AdminApiMutationFamilyType.SPOT_RECOVERY_ROLLBACK_EXECUTION
            ),
            None,
        )
        return SpotRecoveryRollbackPlanResponse(
            approved_phase_range=AUTONOMOUS_APPROVED_PHASE_RANGE,
            status=AdminApiGateStatus.BLOCKED,
            filters=self._spot_recovery_filters(
                state_file=state_file,
                run_id=run_id,
                config_id=config_id,
                client_order_id=client_order_id,
            ),
            candidate_count=len(candidates),
            candidates=candidates,
            current_read_evidence_routes=self._spot_recovery_contract_routes(),
            rollback_steps=[
                {
                    "name": "candidate_identity_snapshot",
                    "status": AdminApiGateStatus.BLOCKED.value,
                    "identity_key": "client_order_id",
                    "detail": "Snapshot the candidate identity before any state repair contract can run.",
                },
                {
                    "name": "pre_apply_state_snapshot",
                    "status": AdminApiGateStatus.PASSED.value,
                    "detail": "Capture backend-owned pre-apply intent in the append-only recovery execution journal without mutating order state.",
                },
                {
                    "name": "post_apply_reconciliation_requirement",
                    "status": AdminApiGateStatus.BLOCKED.value,
                    "detail": "Require reconciliation proof before a future recovery action can close.",
                },
            ],
            state_repair_taxonomy=self._spot_recovery_state_repair_taxonomy(),
            repair_targets=repair_targets,
            pre_apply_snapshots=pre_apply_snapshots,
            dry_run_repair_plans=dry_run_repair_plans,
            completion_states=completion_states,
            persisted_execution_count=len(persisted_executions),
            persisted_executions=persisted_executions,
            persisted_repair_result_count=len(persisted_repair_results),
            persisted_repair_results=persisted_repair_results,
            latest_rollback_journal_id=latest_rollback_journal_id,
            latest_repair_result_id=(
                persisted_repair_results[0].repair_result_id
                if persisted_repair_results
                else None
            ),
            missing_contracts=[],
            rollback_repair_contract_available=True,
            spot_rule_boundary=_enterprise_module_spot_boundary("spot_operations"),
            detail=(
                "Spot recovery rollback-plan evidence is read-only. It describes "
                "what the backend-owned rollback journal and guarded local "
                "repair-result contract capture, but it does not roll back "
                "order state, execute reconciliation, mutate exchange state, "
                "call Coinbase, or authorize browser/BFF rollback."
            ),
        )

    def build_spot_recovery_reconciliation_proof(
        self,
        *,
        state_file: str | None = None,
        run_id: str | None = None,
        config_id: str | None = None,
        client_order_id: str | None = None,
    ) -> SpotRecoveryReconciliationProofResponse:
        """Return read-only Spot recovery reconciliation-proof evidence."""

        preview = self.build_spot_recovery_preview(
            state_file=state_file,
            run_id=run_id,
            config_id=config_id,
            client_order_id=client_order_id,
        )
        candidates = self._spot_recovery_contract_candidates(preview)
        persisted_proofs = self._spot_recovery_proof_records(
            client_order_id=client_order_id
        )
        persisted_snapshots = self._spot_recovery_snapshot_records(
            client_order_id=client_order_id
        )
        persisted_executions = self._spot_recovery_execution_records(
            client_order_id=client_order_id
        )
        persisted_repair_results = self._spot_recovery_repair_result_records(
            client_order_id=client_order_id
        )
        persisted_completions = self._spot_recovery_completion_records(
            client_order_id=client_order_id
        )
        (
            repair_targets,
            pre_apply_snapshots,
            dry_run_repair_plans,
            completion_states,
        ) = self._spot_recovery_target_evidence(
            candidates=candidates,
            proof_records=persisted_proofs,
            execution_records=persisted_executions,
            repair_result_records=persisted_repair_results,
            completion_records=persisted_completions,
        )
        reconciliation_execution_boundaries = (
            self._spot_recovery_reconciliation_execution_boundaries(
                candidates=candidates,
                snapshot_records=persisted_snapshots,
                proof_records=persisted_proofs,
                execution_records=persisted_executions,
                repair_result_records=persisted_repair_results,
                completion_records=persisted_completions,
            )
        )
        latest_exchange_state_proof_id = next(
            (
                record.exchange_state_proof_id
                for record in persisted_proofs
                if record.exchange_state_proof_id
            ),
            None,
        )
        latest_reconciliation_proof_id = next(
            (
                record.reconciliation_proof_id
                for record in persisted_proofs
                if record.reconciliation_proof_id
            ),
            None,
        )
        latest_exchange_state_snapshot_id = next(
            (
                record.exchange_state_snapshot_id
                for record in persisted_snapshots
                if record.exchange_state_snapshot_id
            ),
            None,
        )
        latest_apply_journal_id = next(
            (
                record.journal_id
                for record in persisted_executions
                if record.mutation_family
                == AdminApiMutationFamilyType.SPOT_RECOVERY_APPLY_EXECUTION
            ),
            None,
        )
        latest_rollback_journal_id = next(
            (
                record.journal_id
                for record in persisted_executions
                if record.mutation_family
                == AdminApiMutationFamilyType.SPOT_RECOVERY_ROLLBACK_EXECUTION
            ),
            None,
        )
        post_apply_required_count = sum(
            1
            for record in persisted_executions
            if record.post_apply_reconciliation_required
        )
        post_apply_satisfied_count = len({
            record.audit_id
            for record in persisted_executions
            if record.post_apply_reconciliation_satisfied
        } | {
            record.audit_id for record in persisted_completions
        })
        post_apply_completed_count = sum(
            1
            for record in persisted_completions
            if record.post_apply_reconciliation_completed
        )
        return SpotRecoveryReconciliationProofResponse(
            approved_phase_range=AUTONOMOUS_APPROVED_PHASE_RANGE,
            status=AdminApiGateStatus.BLOCKED,
            filters=self._spot_recovery_filters(
                state_file=state_file,
                run_id=run_id,
                config_id=config_id,
                client_order_id=client_order_id,
            ),
            candidate_count=len(candidates),
            candidates=candidates,
            current_read_evidence_routes=self._spot_recovery_contract_routes(),
            required_proof_fields=[
                "client_order_id",
                "approval_snapshot_id",
                "admission_audit_id",
                "cap_guard_decision_id",
                "reconciliation_plan_id",
                "pre_apply_state_snapshot_id",
                "post_apply_state_snapshot_id",
                "exchange_state_snapshot_id",
                "operator_intent",
                "audit_id",
            ],
            state_repair_taxonomy=self._spot_recovery_state_repair_taxonomy(),
            repair_targets=repair_targets,
            pre_apply_snapshots=pre_apply_snapshots,
            dry_run_repair_plans=dry_run_repair_plans,
            completion_states=completion_states,
            persisted_proof_count=len(persisted_proofs),
            persisted_proofs=persisted_proofs,
            post_apply_reconciliation_completion_available=True,
            persisted_execution_count=len(persisted_executions),
            persisted_executions=persisted_executions,
            persisted_repair_result_count=len(persisted_repair_results),
            persisted_repair_results=persisted_repair_results,
            persisted_completion_count=len(persisted_completions),
            persisted_completions=persisted_completions,
            persisted_snapshot_count=len(persisted_snapshots),
            persisted_snapshots=persisted_snapshots,
            reconciliation_execution_boundary_available=True,
            reconciliation_execution_boundary_count=len(
                reconciliation_execution_boundaries
            ),
            reconciliation_execution_boundaries=(
                reconciliation_execution_boundaries
            ),
            latest_reconciliation_execution_boundary_id=(
                reconciliation_execution_boundaries[0].boundary_id
                if reconciliation_execution_boundaries
                else None
            ),
            latest_exchange_state_proof_id=latest_exchange_state_proof_id,
            latest_reconciliation_proof_id=latest_reconciliation_proof_id,
            latest_exchange_state_snapshot_id=latest_exchange_state_snapshot_id,
            latest_apply_journal_id=latest_apply_journal_id,
            latest_rollback_journal_id=latest_rollback_journal_id,
            latest_repair_result_id=(
                persisted_repair_results[0].repair_result_id
                if persisted_repair_results
                else None
            ),
            latest_completion_id=(
                persisted_completions[0].completion_id
                if persisted_completions
                else None
            ),
            post_apply_reconciliation_required_count=post_apply_required_count,
            post_apply_reconciliation_satisfied_count=post_apply_satisfied_count,
            post_apply_reconciliation_completed_count=post_apply_completed_count,
            missing_contracts=[
                "spot_reconciliation_execution_contract",
            ],
            exchange_state_snapshot_contract_available=True,
            spot_rule_boundary=_enterprise_module_spot_boundary("spot_operations"),
            detail=(
                "Spot recovery reconciliation-proof evidence lists required proof "
                "fields and reads backend-owned append-only proof and snapshot "
                "records. It does not execute reconciliation, mutate "
                "order/exchange state, call Coinbase, or authorize browser/BFF "
                "reconciliation."
            ),
        )

    def build_spot_sweep_status(self, *, state_file: str | None = None) -> dict[str, Any]:
        from dashboard_server import _build_spot_sweep_status_payload

        return _build_spot_sweep_status_payload(state_file=state_file)

    def build_spot_sweep_pnl(
        self,
        *,
        product_ids: list[str] | None = None,
        include_coinbase_average_cost: bool = False,
    ) -> dict[str, Any]:
        from dashboard_server import _build_spot_sweep_pnl_payload

        return _build_spot_sweep_pnl_payload(
            product_ids=product_ids,
            include_coinbase_average_cost=include_coinbase_average_cost,
        )

    def build_spot_cost_basis_status(
        self,
        *,
        state_file: str | None = None,
    ) -> dict[str, Any]:
        from dashboard_server import _build_spot_cost_basis_payload

        return _build_spot_cost_basis_payload(state_file=state_file)

    def build_spot_campaign_status(
        self,
        *,
        state_file: str | None = None,
    ) -> dict[str, Any]:
        from dashboard_server import _build_spot_campaign_payload

        return _build_spot_campaign_payload(state_file=state_file)

    def build_spot_direct_order_audit(
        self,
        *,
        client_order_id: str,
        include_events: bool = True,
        include_fills: bool = True,
        event_limit: int = 100,
        fill_limit: int = 1000,
    ) -> dict[str, Any]:
        from dashboard_server import _build_spot_direct_order_audit_payload

        return _build_spot_direct_order_audit_payload(
            client_order_id=client_order_id,
            include_events=include_events,
            include_fills=include_fills,
            event_limit=event_limit,
            fill_limit=fill_limit,
        )
