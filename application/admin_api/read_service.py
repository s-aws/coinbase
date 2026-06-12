"""Read-only Admin API service wrappers."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from core.enums import (
    ActionConditionType,
    ActionGuardPhase,
    AdminApiActionClass,
    AdminApiAuthMode,
    AdminAuditEvidenceSource,
    AdminAuditWorkbenchModule,
    AdminFuturesEvidenceSource,
    AdminFuturesEvidenceStatus,
    AdminFuturesPositionSide,
    AdminApiGateStatus,
    AdminApiHealthStatus,
    AdminApiLiveAdmissionAuditFact,
    AdminApiLiveApprovalStoreRequirement,
    AdminApiLiveApprovalSnapshotField,
    AdminApiLiveCapGuardRequirement,
    AdminApiLiveExecutionStatus,
    AdminApiLivePreflightCategory,
    AdminApiModuleSupportStatus,
    AdminMovementRepricingEvidenceType,
    AdminApiPermission,
    AdminApiRouteAvailability,
    AdminApiSessionStatus,
    AdminApiVerifierReadinessStatus,
    OrderSide,
    ProductCapability,
    ProductType,
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
    AdminStealthOrderListResponse,
    AdminStealthOrderReadItem,
)
from .route_inventory import ADMIN_API_ROUTE_INVENTORY


ROOT = Path(__file__).resolve().parents[2]
API_VERSION = "0.1.0"
SCHEMA_VERSION = "0.1.0"
AUTONOMOUS_APPROVED_PHASE_RANGE = "1201-1220"
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
) -> AdminLiveApprovalStoreRequirementItem:
    return AdminLiveApprovalStoreRequirementItem(
        requirement=requirement,
        status=AdminApiGateStatus.BLOCKED,
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
            expected_source="approval_store",
            detail="Approval storage must be owned and enforced by the backend.",
        ),
        _approval_store_requirement(
            requirement=AdminApiLiveApprovalStoreRequirement.ROUTE_BOUND,
            expected_source="route_inventory",
            expected_value=route,
            detail="Approval storage must bind approval to the exact route.",
        ),
        _approval_store_requirement(
            requirement=AdminApiLiveApprovalStoreRequirement.METHOD_BOUND,
            expected_source="route_inventory",
            expected_value=method,
            detail="Approval storage must bind approval to the exact HTTP method.",
        ),
        _approval_store_requirement(
            requirement=AdminApiLiveApprovalStoreRequirement.MODULE_BOUND,
            expected_source="route_inventory",
            expected_value=module_id,
            detail="Approval storage must bind approval to the enterprise module id.",
        ),
        _approval_store_requirement(
            requirement=AdminApiLiveApprovalStoreRequirement.ACTOR_BOUND,
            expected_source="approval_store",
            detail="Approval storage must record the backend-authenticated approving actor.",
        ),
        _approval_store_requirement(
            requirement=AdminApiLiveApprovalStoreRequirement.IDEMPOTENCY_BOUND,
            expected_source="command_headers",
            detail="Approval storage must bind to the command idempotency key.",
        ),
        _approval_store_requirement(
            requirement=AdminApiLiveApprovalStoreRequirement.PAYLOAD_HASH_BOUND,
            expected_source="command_service",
            detail="Approval storage must bind to the submitted command payload hash.",
        ),
        _approval_store_requirement(
            requirement=AdminApiLiveApprovalStoreRequirement.EXPIRING,
            expected_source="approval_store",
            detail="Approval storage must enforce expiry and reject evergreen approval.",
        ),
        _approval_store_requirement(
            requirement=AdminApiLiveApprovalStoreRequirement.CAP_GUARD_BOUND,
            expected_source="guard_risk_policy",
            detail="Approval storage must bind to backend cap and guard decision evidence.",
        ),
        _approval_store_requirement(
            requirement=AdminApiLiveApprovalStoreRequirement.RECONCILIATION_BOUND,
            expected_source="reconciliation_policy",
            detail="Approval storage must bind to the planned post-live reconciliation evidence.",
        ),
        _approval_store_requirement(
            requirement=AdminApiLiveApprovalStoreRequirement.APPEND_ONLY_AUDIT,
            expected_source="audit_store",
            detail="Approval storage must write append-only audit evidence for approval decisions.",
        ),
        _approval_store_requirement(
            requirement=AdminApiLiveApprovalStoreRequirement.BROWSER_AUTHORITY_REJECTED,
            expected_source="frontend_boundary",
            expected_value="display_only",
            detail="Approval storage must reject browser-only acknowledgement as live authority.",
        ),
    ]
    return AdminLiveApprovalStoreContractEvidence(
        status=AdminApiGateStatus.BLOCKED,
        required=True,
        configured=False,
        durable=False,
        backend_owned=True,
        browser_authority="display_only",
        source="not_configured",
        requirement_count=len(requirements),
        missing_requirement_count=len(requirements),
        requirements=requirements,
        evidence=[
            "No durable backend approval store is configured for this route.",
            "Approval records must be backend-owned, route-bound, expiring, payload-bound, and audited.",
            "Browser acknowledgement is display-only and cannot satisfy approval-store requirements.",
        ],
        detail=(
            f"{method} {route} remains live-disabled until a backend approval "
            "store contract is implemented and configured."
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
            detail="Audit trail must link the backend approval-store decision and approving actor.",
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
    claim_ledger = getattr(manager, "_mutation_claims", None) if manager else None
    if claim_ledger is None:
        return [
            AdminMutationClaimEvidence(
                kind=kind,
                state=None,
                runtime_observed=False,
                source="runtime_stealth_manager_unavailable",
            )
            for kind in StealthMutationKind
        ]
    claims: list[AdminMutationClaimEvidence] = []
    for kind in StealthMutationKind:
        try:
            state = _string_or_none(claim_ledger.state(kind, stealth_order_id))
        except Exception as exc:
            state = f"unavailable:{type(exc).__name__}"
        claims.append(
            AdminMutationClaimEvidence(
                kind=kind,
                state=state,
                runtime_observed=True,
                source="stealth_manager._mutation_claims",
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


class AdminApiReadService:
    """Read-only status service for operator views.

    The current implementation delegates to existing dashboard payload builders
    without using the dashboard WebSocket transport. These methods must remain
    read-only.
    """

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
                identity_keys=["client_order_id"],
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
                    "api/v1/routes/spot.py",
                ],
                frontend_contract_refs=[
                    "src/shared/api/contracts/backendApiClient.ts::getSpotReadiness",
                    "src/shared/api/contracts/backendApiClient.ts::executeSpotCampaign",
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
            modules=modules,
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
                    status=AdminApiLiveExecutionStatus.LIVE_DISABLED,
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
        return AdminStealthOrderDetailResponse(
            stealth_order_id=stealth_order_id,
            found=row is not None,
            order=_stealth_item_from_row(row) if row else None,
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
            },
        )

    def build_spot_readiness(
        self,
        *,
        product_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        from dashboard_server import _build_spot_readiness_payload

        return _build_spot_readiness_payload(product_ids=product_ids)

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
