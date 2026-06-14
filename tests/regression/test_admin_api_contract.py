from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from api.v1.app import create_app
from application.admin_api.auth import (
    OidcJwtVerificationError,
    actor_has_permission,
    build_oidc_jwt_readiness,
    oidc_jwt_required_env_vars,
    verify_oidc_jwt,
)
from application.admin_api import command_service
from application.admin_api.command_service import (
    AdminApiCommandDependencies,
    AdminApiCommandService,
)
from application.admin_api.approval import (
    AdminApiApprovalLifecycleEvent,
    AdminApiApprovalRecord,
    ApprovalSnapshotRequest,
    FileAdminApiApprovalStore,
    resolve_approval_snapshot,
)
from application.admin_api.approval_service import AdminApiApprovalLifecycleService
from application.admin_api.audit import AdminApiAuditEvent, FileAdminApiAuditStore
from application.admin_api.audit import (
    AdmissionAuditTrailRequest,
    resolve_admission_audit_trail,
)
from application.admin_api.cap_guard import (
    CapGuardDecisionRequest,
    CapGuardDecisionRecord,
    FileAdminApiCapGuardStore,
    resolve_cap_guard_decision,
)
from application.admin_api.reconciliation import (
    FileAdminApiReconciliationStore,
    ReconciliationPlanRecord,
    ReconciliationPlanRequest,
    resolve_reconciliation_plan,
)
from application.admin_api.pnl_checkpoint import (
    FileSpotPnlCheckpointStore,
    SpotPnlCheckpointRecord,
)
from application.admin_api.spot_recovery_execution import (
    FileSpotRecoveryExecutionJournalStore,
)
from application.admin_api.spot_recovery_completion import (
    FileSpotRecoveryCompletionJournalStore,
)
from application.admin_api.spot_recovery_proof import (
    FileSpotRecoveryProofStore,
    SpotRecoveryProofRecord,
)
from application.admin_api.spot_recovery_snapshot import (
    FileSpotRecoverySnapshotStore,
)
from application.admin_api.spot_recovery_repair import (
    FileSpotRecoveryRepairResultJournalStore,
    build_spot_recovery_repair_ids,
)
from application.admin_api.idempotency import (
    FileIdempotencyStore,
    IdempotencyRecord,
    evaluate_idempotency,
    make_payload_hash,
)
from application.admin_api.live_execution import (
    DisabledAdminApiLiveExecutionService,
    build_disabled_live_execution_adapter_contract,
    build_disabled_live_execution_intent,
    build_live_execution_adapter_contract,
    get_disabled_live_execution_service,
)
from application.admin_api.models import (
    AdminApiActor,
    AdminApprovalRequestCreateRequest,
    AdminLiveAdmissionDecisionEvidence,
    ManualOrderRequest,
    SpotRecoveryApplyExecutionRequest,
    SpotRecoveryExchangeStateProofRequest,
    SpotRecoveryExchangeStateSnapshotRequest,
    SpotRecoveryReconciliationExecutionRequest,
    SpotRecoveryReconciliationProofRecordRequest,
    SpotRecoveryRollbackExecutionRequest,
)
from application.admin_api.route_inventory import ADMIN_API_ROUTE_INVENTORY
from core.enums import (
    AdminApiActionClass,
    AdminApiApprovalLifecycleEventType,
    AdminApiApprovalLifecycleStatus,
    AdminApiAuthMode,
    AdminAuditEvidenceSource,
    AdminAuditWorkbenchModule,
    AdminApiCommandRoutesMode,
    AdminApiCommandStatus,
    AdminApiErrorCode,
    AdminApiFunctionalityExposureStatus,
    AdminApiFunctionalityWorkflowType,
    AdminApiGateStatus,
    AdminApiIdempotencyDecision,
    AdminApiLiveAdmissionBlocker,
    AdminApiLiveExecutionStatus,
    AdminApiLivePreflightCategory,
    AdminApiLiveReadinessPrecondition,
    AdminApiMutationFamilyType,
    AdminApiModuleSupportStatus,
    AdminApiPermission,
    AdminApiRole,
    AdminApiSpotCommandSuiteGapFamily,
    AdminApiStealthCommandSuiteGapFamily,
    AdminApiVerifierReadinessStatus,
    StealthMutationKind,
    SpotRecoveryExchangeStateSnapshotSource,
    SpotRecoveryCompletionState,
    SpotRecoveryRepairCategory,
)
from tools.generate_admin_api_openapi import generate_openapi_schema
from tools.export_admin_api_route_inventory import (
    ROUTE_INVENTORY_EXPORT_PATH,
    build_admin_api_route_inventory_export,
    write_admin_api_route_inventory_export,
)
from tools.run_admin_oidc_readiness_smoke import (
    SUMMARY_PREFIX as ADMIN_OIDC_READINESS_SMOKE_SUMMARY_PREFIX,
    build_admin_oidc_readiness_smoke_summary,
    build_parser as build_admin_oidc_readiness_smoke_parser,
)


ROOT = Path(__file__).resolve().parents[2]
OPENAPI_PATH = ROOT / "openapi" / "coinbase-admin-api.yaml"
ROUTE_INVENTORY_DOC = ROOT / "docs" / "plans" / "ADMIN_API_ROUTE_INVENTORY.md"


def _headers(
    *,
    idempotency_key: str = "idem-001",
    operator_intent: str = "manual_one_off",
    roles: str = AdminApiRole.TRADER.value,
) -> dict[str, str]:
    return {
        "Authorization": "Bearer test-admin-token",
        "Idempotency-Key": idempotency_key,
        "X-Correlation-Id": "corr-001",
        "X-Operator-Intent": operator_intent,
        "X-Admin-Actor": "operator-001",
        "X-Admin-Roles": roles,
    }


def _store_dir() -> Path:
    path = ROOT / "runtime_state" / "test_admin_api_contract" / str(uuid4())
    path.mkdir(parents=True, exist_ok=True)
    return path


def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from api.v1.routes import admission_audit as admission_audit_routes
    from api.v1.routes import approvals as approval_routes
    from api.v1.routes import cap_guard as cap_guard_routes
    from api.v1.routes import orders as order_routes
    from api.v1.routes import reconciliation as reconciliation_routes
    from api.v1.routes import spot as spot_routes

    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-admin-token")
    app = create_app()
    store_dir = _store_dir()
    idempotency_store = FileIdempotencyStore(store_dir / "idempotency.jsonl")
    audit_store = FileAdminApiAuditStore(store_dir / "audit.jsonl")
    approval_store = FileAdminApiApprovalStore(store_dir / "approvals.jsonl")
    cap_guard_store = FileAdminApiCapGuardStore(store_dir / "cap_guard.jsonl")
    reconciliation_store = FileAdminApiReconciliationStore(
        store_dir / "reconciliation.jsonl"
    )
    pnl_checkpoint_store = FileSpotPnlCheckpointStore(
        store_dir / "spot_pnl_checkpoints.jsonl"
    )
    spot_recovery_proof_store = FileSpotRecoveryProofStore(
        store_dir / "spot_recovery_proofs.jsonl"
    )
    spot_recovery_snapshot_store = FileSpotRecoverySnapshotStore(
        store_dir / "spot_recovery_snapshots.jsonl"
    )
    spot_recovery_execution_store = FileSpotRecoveryExecutionJournalStore(
        store_dir / "spot_recovery_execution_journal.jsonl"
    )
    spot_recovery_repair_result_store = FileSpotRecoveryRepairResultJournalStore(
        store_dir / "spot_recovery_repair_results.jsonl"
    )
    spot_recovery_completion_store = FileSpotRecoveryCompletionJournalStore(
        store_dir / "spot_recovery_completion.jsonl"
    )
    order_command_service = AdminApiCommandService(
        AdminApiCommandDependencies(
            spot_recovery_proof_store_getter=lambda: spot_recovery_proof_store,
            spot_recovery_snapshot_store_getter=lambda: spot_recovery_snapshot_store,
            spot_recovery_execution_store_getter=lambda: (
                spot_recovery_execution_store
            ),
            spot_recovery_repair_result_store_getter=lambda: (
                spot_recovery_repair_result_store
            ),
            spot_recovery_completion_store_getter=lambda: (
                spot_recovery_completion_store
            ),
            audit_store_getter=lambda: audit_store,
        )
    )
    app.dependency_overrides[order_routes.get_idempotency_store] = (
        lambda: idempotency_store
    )
    app.dependency_overrides[order_routes.get_command_service] = (
        lambda: order_command_service
    )
    app.dependency_overrides[order_routes.get_audit_store] = lambda: audit_store
    app.dependency_overrides[order_routes.get_approval_store] = lambda: approval_store
    app.dependency_overrides[order_routes.get_cap_guard_store] = (
        lambda: cap_guard_store
    )
    app.dependency_overrides[order_routes.get_reconciliation_store] = (
        lambda: reconciliation_store
    )
    app.dependency_overrides[approval_routes.get_idempotency_store] = (
        lambda: idempotency_store
    )
    app.dependency_overrides[approval_routes.get_audit_store] = lambda: audit_store
    app.dependency_overrides[approval_routes.get_approval_store] = lambda: approval_store
    app.dependency_overrides[admission_audit_routes.get_idempotency_store] = (
        lambda: idempotency_store
    )
    app.dependency_overrides[admission_audit_routes.get_audit_store] = (
        lambda: audit_store
    )
    app.dependency_overrides[cap_guard_routes.get_idempotency_store] = (
        lambda: idempotency_store
    )
    app.dependency_overrides[cap_guard_routes.get_audit_store] = lambda: audit_store
    app.dependency_overrides[cap_guard_routes.get_cap_guard_store] = (
        lambda: cap_guard_store
    )
    app.dependency_overrides[reconciliation_routes.get_idempotency_store] = (
        lambda: idempotency_store
    )
    app.dependency_overrides[reconciliation_routes.get_audit_store] = (
        lambda: audit_store
    )
    app.dependency_overrides[reconciliation_routes.get_reconciliation_store] = (
        lambda: reconciliation_store
    )
    app.dependency_overrides[spot_routes.get_idempotency_store] = (
        lambda: idempotency_store
    )
    app.dependency_overrides[spot_routes.get_audit_store] = lambda: audit_store
    app.dependency_overrides[spot_routes.get_spot_pnl_checkpoint_store] = (
        lambda: pnl_checkpoint_store
    )
    app.dependency_overrides[spot_routes.get_read_service] = lambda: (
        spot_routes.AdminApiReadService(
            spot_recovery_proof_store=spot_recovery_proof_store,
            spot_recovery_snapshot_store=spot_recovery_snapshot_store,
            spot_recovery_execution_store=spot_recovery_execution_store,
            spot_recovery_repair_result_store=spot_recovery_repair_result_store,
            spot_recovery_completion_store=spot_recovery_completion_store,
        )
    )
    client = TestClient(app)
    client.admin_api_test_store_dir = store_dir
    client.admin_api_test_idempotency_store = idempotency_store
    client.admin_api_test_audit_store = audit_store
    client.admin_api_test_approval_store = approval_store
    client.admin_api_test_cap_guard_store = cap_guard_store
    client.admin_api_test_reconciliation_store = reconciliation_store
    client.admin_api_test_pnl_checkpoint_store = pnl_checkpoint_store
    client.admin_api_test_spot_recovery_proof_store = spot_recovery_proof_store
    client.admin_api_test_spot_recovery_snapshot_store = (
        spot_recovery_snapshot_store
    )
    client.admin_api_test_spot_recovery_execution_store = (
        spot_recovery_execution_store
    )
    client.admin_api_test_spot_recovery_repair_result_store = (
        spot_recovery_repair_result_store
    )
    client.admin_api_test_spot_recovery_completion_store = (
        spot_recovery_completion_store
    )
    return client


def _manual_order_payload(
    quote_size: str = "1.00",
    client_order_id: str | None = None,
) -> dict:
    payload = {
        "product_id": "BTC-USDC",
        "side": "BUY",
        "order_type": "LIMIT",
        "quote_size": quote_size,
        "limit_price": "65000.00",
        "manual_live_acknowledgement": True,
    }
    if client_order_id is not None:
        payload["client_order_id"] = client_order_id
    return payload


def _assert_disabled_live_execution_intent(
    intent: dict,
    *,
    route: str,
    method: str,
    module_id: str,
    service_method: str,
    identity_key: str,
    identity_value: str | None,
) -> None:
    assert intent["required"] is True
    assert intent["prepared"] is False
    assert intent["backend_owned"] is True
    assert intent["route_bound"] is True
    assert intent["payload_bound"] is True
    assert intent["idempotency_bound"] is True
    assert intent["executable"] is False
    assert intent["status"] == "live_disabled"
    assert intent["source"] == "disabled_backend_service"
    assert intent["missing_reason"] == "live_execution_disabled"
    assert intent["route"] == route
    assert intent["method"] == method
    assert intent["module_id"] == module_id
    assert intent["service_method"] == service_method
    assert intent["adapter_reference"] == f"AdminApiCommandService.{service_method}"
    assert intent["identity_key"] == identity_key
    assert intent["identity_value"] == identity_value
    assert intent["browser_authority"] == "display_only"
    assert intent["bff_authority"] == "forward_only_no_execution"
    assert intent["live_exchange_submitted"] is False
    assert "live_execution_disabled" in intent["blockers"]
    assert "browser_authority_rejected" in intent["blockers"]
    assert len(intent["payload_hash"]) == 64
    assert "disabled execution intent" in intent["detail"]


def _manual_order_approval_payload(
    *,
    actor_id: str = "operator-001",
    roles: list[str] | None = None,
    operator_intent: str = "manual_one_off",
    client_order_id: str = "client-approved",
    idempotency_key: str = "idem-approved",
) -> dict:
    return {
        "endpoint": "POST /api/v1/orders",
        "actor_id": actor_id,
        "roles": roles or [AdminApiRole.TRADER.value],
        "operator_intent": operator_intent,
        "body": ManualOrderRequest.model_validate(
            _manual_order_payload(client_order_id=client_order_id)
        ).model_dump(mode="json"),
        "path_params": {},
    }


def _approval_request_payload(
    *,
    client_order_id: str = "client-approved",
    idempotency_key: str = "idem-approved",
    operator_intent: str = "manual_one_off",
    payload_hash: str | None = None,
) -> dict:
    return {
        "route": "/api/v1/orders",
        "method": "POST",
        "module_id": "spot_operations",
        "identity_key": "client_order_id",
        "identity_value": client_order_id,
        "action_class": AdminApiActionClass.LIVE_EXCHANGE_PLACE.value,
        "required_permission": AdminApiPermission.ORDER_CREATE.value,
        "operator_intent": operator_intent,
        "command_idempotency_key": idempotency_key,
        "payload_hash": payload_hash
        or make_payload_hash(
            _manual_order_approval_payload(
                operator_intent=operator_intent,
                client_order_id=client_order_id,
                idempotency_key=idempotency_key,
            )
        ),
        "request_reason": "operator wants a bounded manual order approval",
    }


def _append_manual_order_approval(
    *,
    store: FileAdminApiApprovalStore,
    now: datetime,
    client_order_id: str = "client-approved",
    idempotency_key: str = "idem-approved",
    operator_intent: str = "manual_one_off",
    requested_by_actor_id: str = "operator-001",
    payload_hash: str | None = None,
) -> AdminApiApprovalRecord:
    record = AdminApiApprovalRecord(
        expires_at=now + timedelta(minutes=5),
        approved_by_actor_id="approver-001",
        requested_by_actor_id=requested_by_actor_id,
        route="/api/v1/orders",
        method="POST",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value=client_order_id,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.ORDER_CREATE,
        operator_intent=operator_intent,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash
        or make_payload_hash(
            _manual_order_approval_payload(
                operator_intent=operator_intent,
                client_order_id=client_order_id,
                idempotency_key=idempotency_key,
            )
        ),
        cap_guard_decision_ref="cap-guard-approval-001",
        reconciliation_plan_ref="reconciliation-approval-001",
    )
    store.append(record)
    return record


def _append_manual_order_admission_audit(
    *,
    store: FileAdminApiAuditStore,
    approval: AdminApiApprovalRecord,
    client_order_id: str = "client-approved",
    idempotency_key: str = "idem-approved",
    operator_intent: str = "manual_one_off",
    payload_hash: str | None = None,
) -> AdminApiAuditEvent:
    resolved_payload_hash = payload_hash or make_payload_hash(
        _manual_order_approval_payload(
            operator_intent=operator_intent,
            client_order_id=client_order_id,
            idempotency_key=idempotency_key,
        )
    )
    event = AdminApiAuditEvent(
        actor_id="operator-001",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        permission=AdminApiPermission.ORDER_CREATE,
        endpoint="POST /api/v1/orders",
        request_id="corr-audit-proof",
        operator_intent=operator_intent,
        idempotency_key=idempotency_key,
        approval_id=approval.approval_id,
        client_order_id=client_order_id,
        status=AdminApiCommandStatus.NOT_IMPLEMENTED,
        failure_stage="approval",
        message="Prior route-bound command admission audit proof.",
        admission_decision=AdminLiveAdmissionDecisionEvidence(
            status=AdminApiGateStatus.BLOCKED,
            allowed=False,
            route="/api/v1/orders",
            method="POST",
            module_id="spot_operations",
            identity_key="client_order_id",
            identity_value=client_order_id,
            action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            required_permission=AdminApiPermission.ORDER_CREATE,
            service_method="place_manual_order",
            actor_id="operator-001",
            idempotency_key=idempotency_key,
            operator_intent=operator_intent,
            payload_hash=resolved_payload_hash,
            approval_snapshot_required=True,
            approval_store_required=True,
            admission_audit_required=True,
            cap_guard_required=True,
            reconciliation_required=True,
            approval_snapshot_present=True,
            approval_snapshot_id=approval.approval_id,
            approval_snapshot_source="approval_store",
            approval_snapshot_approved_by_actor_id=approval.approved_by_actor_id,
            approval_snapshot_requested_by_actor_id=approval.requested_by_actor_id,
            approval_snapshot_expires_at=approval.expires_at.isoformat(),
            browser_authority="rejected",
            live_exchange_submitted=False,
            blockers=[
                AdminApiLiveAdmissionBlocker.LIVE_EXECUTION_DISABLED,
                AdminApiLiveAdmissionBlocker.ADMISSION_AUDIT_MISSING,
                AdminApiLiveAdmissionBlocker.CAP_GUARD_MISSING,
                AdminApiLiveAdmissionBlocker.RECONCILIATION_PLAN_MISSING,
                AdminApiLiveAdmissionBlocker.BROWSER_AUTHORITY_REJECTED,
            ],
            evidence=["prior append-only command admission audit"],
            detail="Prior backend-owned admission audit proof.",
        ),
    )
    store.append(event)
    return event


def _admission_audit_payload(
    *,
    approval: AdminApiApprovalRecord,
    client_order_id: str = "client-approved",
    idempotency_key: str = "idem-approved",
    operator_intent: str = "manual_one_off",
    payload_hash: str | None = None,
    allowed: bool = False,
    status: AdminApiGateStatus = AdminApiGateStatus.BLOCKED,
) -> dict:
    return {
        "route": "/api/v1/orders",
        "method": "POST",
        "module_id": "spot_operations",
        "identity_key": "client_order_id",
        "identity_value": client_order_id,
        "action_class": AdminApiActionClass.LIVE_EXCHANGE_PLACE.value,
        "required_permission": AdminApiPermission.ORDER_CREATE.value,
        "service_method": "place_manual_order",
        "actor_id": "operator-001",
        "operator_intent": operator_intent,
        "command_idempotency_key": idempotency_key,
        "payload_hash": payload_hash
        or make_payload_hash(
            _manual_order_approval_payload(
                operator_intent=operator_intent,
                client_order_id=client_order_id,
                idempotency_key=idempotency_key,
            )
        ),
        "approval_snapshot_id": approval.approval_id,
        "approval_snapshot_approved_by_actor_id": approval.approved_by_actor_id,
        "approval_snapshot_requested_by_actor_id": approval.requested_by_actor_id,
        "approval_snapshot_expires_at": approval.expires_at.isoformat(),
        "approval_cap_guard_decision_ref": approval.cap_guard_decision_ref,
        "approval_reconciliation_plan_ref": approval.reconciliation_plan_ref,
        "allowed": allowed,
        "status": status.value,
        "reason": "Exact backend-owned admission audit proof for route tests.",
    }


def _append_manual_order_cap_guard_decision(
    *,
    store: FileAdminApiCapGuardStore,
    approval: AdminApiApprovalRecord,
    audit_event: AdminApiAuditEvent,
    client_order_id: str = "client-approved",
    idempotency_key: str = "idem-approved",
    operator_intent: str = "manual_one_off",
    payload_hash: str | None = None,
    allowed: bool = True,
    status: AdminApiGateStatus = AdminApiGateStatus.PASSED,
) -> CapGuardDecisionRecord:
    record = CapGuardDecisionRecord(
        decision_id=approval.cap_guard_decision_ref,
        route="/api/v1/orders",
        method="POST",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value=client_order_id,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.ORDER_CREATE,
        service_method="place_manual_order",
        actor_id="operator-001",
        operator_intent=operator_intent,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash
        or make_payload_hash(
            _manual_order_approval_payload(
                operator_intent=operator_intent,
                client_order_id=client_order_id,
                idempotency_key=idempotency_key,
            )
        ),
        approval_snapshot_id=approval.approval_id,
        admission_audit_id=audit_event.audit_id,
        allowed=allowed,
        status=status,
        cap_policy_ref="submitted_notional_cap:3.10",
        guard_policy_ref="action_condition_guard:manual_order",
        product_scope="USDC spot product scope",
        max_submitted_notional_usdc="3.10",
        max_executed_notional_usdc="1.00",
        reason="Exact backend-owned cap/guard proof for no-live admission tests.",
    )
    store.append(record)
    return record


def _cap_guard_decision_payload(
    *,
    approval: AdminApiApprovalRecord,
    audit_event: AdminApiAuditEvent,
    client_order_id: str = "client-approved",
    idempotency_key: str = "idem-approved",
    operator_intent: str = "manual_one_off",
    payload_hash: str | None = None,
    allowed: bool = True,
    status: AdminApiGateStatus = AdminApiGateStatus.PASSED,
) -> dict:
    return {
        "route": "/api/v1/orders",
        "method": "POST",
        "module_id": "spot_operations",
        "identity_key": "client_order_id",
        "identity_value": client_order_id,
        "action_class": AdminApiActionClass.LIVE_EXCHANGE_PLACE.value,
        "required_permission": AdminApiPermission.ORDER_CREATE.value,
        "service_method": "place_manual_order",
        "actor_id": "operator-001",
        "operator_intent": operator_intent,
        "command_idempotency_key": idempotency_key,
        "payload_hash": payload_hash
        or make_payload_hash(
            _manual_order_approval_payload(
                operator_intent=operator_intent,
                client_order_id=client_order_id,
                idempotency_key=idempotency_key,
            )
        ),
        "approval_snapshot_id": approval.approval_id,
        "approval_cap_guard_decision_ref": approval.cap_guard_decision_ref,
        "admission_audit_id": audit_event.audit_id,
        "allowed": allowed,
        "status": status.value,
        "cap_policy_ref": "submitted_notional_cap:3.10",
        "guard_policy_ref": "action_condition_guard:manual_order",
        "product_scope": "USDC spot product scope",
        "max_submitted_notional_usdc": "3.10",
        "max_executed_notional_usdc": "1.00",
        "reason": "Exact backend-owned cap/guard decision for route tests.",
    }


def _append_manual_order_reconciliation_plan(
    *,
    store: FileAdminApiReconciliationStore,
    approval: AdminApiApprovalRecord,
    audit_event: AdminApiAuditEvent,
    cap_guard: CapGuardDecisionRecord,
    client_order_id: str = "client-approved",
    idempotency_key: str = "idem-approved",
    operator_intent: str = "manual_one_off",
    payload_hash: str | None = None,
    allowed: bool = True,
    status: AdminApiGateStatus = AdminApiGateStatus.PASSED,
) -> ReconciliationPlanRecord:
    record = ReconciliationPlanRecord(
        plan_id=approval.reconciliation_plan_ref,
        route="/api/v1/orders",
        method="POST",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value=client_order_id,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.ORDER_CREATE,
        service_method="place_manual_order",
        actor_id="operator-001",
        operator_intent=operator_intent,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash
        or make_payload_hash(
            _manual_order_approval_payload(
                operator_intent=operator_intent,
                client_order_id=client_order_id,
                idempotency_key=idempotency_key,
            )
        ),
        approval_snapshot_id=approval.approval_id,
        admission_audit_id=audit_event.audit_id,
        cap_guard_decision_id=cap_guard.decision_id,
        allowed=allowed,
        status=status,
        reconciliation_policy_ref="post_submit_reconciliation:manual_order",
        product_scope="USDC spot product scope",
        max_submitted_notional_usdc="3.10",
        max_executed_notional_usdc="1.00",
        reason="Exact backend-owned reconciliation plan proof for no-live admission tests.",
    )
    store.append(record)
    return record


def _reconciliation_plan_payload(
    *,
    approval: AdminApiApprovalRecord,
    audit_event: AdminApiAuditEvent,
    cap_guard: CapGuardDecisionRecord,
    client_order_id: str = "client-approved",
    idempotency_key: str = "idem-approved",
    operator_intent: str = "manual_one_off",
    payload_hash: str | None = None,
    allowed: bool = True,
    status: AdminApiGateStatus = AdminApiGateStatus.PASSED,
) -> dict:
    return {
        "route": "/api/v1/orders",
        "method": "POST",
        "module_id": "spot_operations",
        "identity_key": "client_order_id",
        "identity_value": client_order_id,
        "action_class": AdminApiActionClass.LIVE_EXCHANGE_PLACE.value,
        "required_permission": AdminApiPermission.ORDER_CREATE.value,
        "service_method": "place_manual_order",
        "actor_id": "operator-001",
        "operator_intent": operator_intent,
        "command_idempotency_key": idempotency_key,
        "payload_hash": payload_hash
        or make_payload_hash(
            _manual_order_approval_payload(
                operator_intent=operator_intent,
                client_order_id=client_order_id,
                idempotency_key=idempotency_key,
            )
        ),
        "approval_snapshot_id": approval.approval_id,
        "approval_reconciliation_plan_ref": approval.reconciliation_plan_ref,
        "admission_audit_id": audit_event.audit_id,
        "cap_guard_decision_id": cap_guard.decision_id,
        "allowed": allowed,
        "status": status.value,
        "reconciliation_policy_ref": "post_submit_reconciliation:manual_order",
        "product_scope": "USDC spot product scope",
        "exchange_submission_required": True,
        "post_submit_reconciliation_required": True,
        "retained_inventory_required": True,
        "max_submitted_notional_usdc": "3.10",
        "max_executed_notional_usdc": "1.00",
        "reason": "Exact backend-owned reconciliation plan for route tests.",
    }


def _spot_recovery_proof_payload_hash(
    *,
    endpoint: str,
    body: dict,
    model: type[
        SpotRecoveryExchangeStateProofRequest
        | SpotRecoveryReconciliationProofRecordRequest
    ],
    operator_intent: str = "spot_recovery_contract_review",
    roles: list[str] | None = None,
) -> str:
    return make_payload_hash({
        "endpoint": endpoint,
        "actor_id": "operator-001",
        "roles": roles or [AdminApiRole.TRADER.value],
        "operator_intent": operator_intent,
        "body": model.model_validate(body).model_dump(mode="json"),
        "path_params": {},
    })


def _spot_recovery_snapshot_payload_hash(
    *,
    endpoint: str,
    body: dict,
    operator_intent: str = "spot_recovery_contract_review",
    roles: list[str] | None = None,
) -> str:
    return make_payload_hash({
        "endpoint": endpoint,
        "actor_id": "operator-001",
        "roles": roles or [AdminApiRole.TRADER.value],
        "operator_intent": operator_intent,
        "body": SpotRecoveryExchangeStateSnapshotRequest.model_validate(
            body
        ).model_dump(mode="json"),
        "path_params": {},
    })


def _spot_recovery_execution_payload_hash(
    *,
    endpoint: str,
    body: dict,
    model: type[
        SpotRecoveryApplyExecutionRequest
        | SpotRecoveryRollbackExecutionRequest
        | SpotRecoveryReconciliationExecutionRequest
    ],
    operator_intent: str = "spot_recovery_contract_review",
    roles: list[str] | None = None,
) -> str:
    return make_payload_hash({
        "endpoint": endpoint,
        "actor_id": "operator-001",
        "roles": roles or [AdminApiRole.TRADER.value],
        "operator_intent": operator_intent,
        "body": model.model_validate(body).model_dump(mode="json"),
        "path_params": {},
    })


def _append_spot_recovery_execution_admission_chain(
    *,
    approval_store: FileAdminApiApprovalStore,
    audit_store: FileAdminApiAuditStore,
    cap_guard_store: FileAdminApiCapGuardStore,
    reconciliation_store: FileAdminApiReconciliationStore,
    route: str,
    service_method: str,
    client_order_id: str,
    idempotency_key: str,
    operator_intent: str,
    payload_hash: str,
    approval_snapshot_id: str,
    admission_audit_id: str,
    cap_guard_decision_id: str,
    reconciliation_plan_id: str,
) -> tuple[AdminApiApprovalRecord, AdminApiAuditEvent, CapGuardDecisionRecord, ReconciliationPlanRecord]:
    now = datetime.now(timezone.utc)
    approval = AdminApiApprovalRecord(
        approval_id=approval_snapshot_id,
        expires_at=now + timedelta(minutes=5),
        approved_by_actor_id="approver-001",
        requested_by_actor_id="operator-001",
        route=route,
        method="POST",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value=client_order_id,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        required_permission=AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        operator_intent=operator_intent,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        cap_guard_decision_ref=cap_guard_decision_id,
        reconciliation_plan_ref=reconciliation_plan_id,
    )
    approval_store.append(approval)
    admission_decision = AdminLiveAdmissionDecisionEvidence(
        status=AdminApiGateStatus.BLOCKED,
        allowed=False,
        route=route,
        method="POST",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value=client_order_id,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        required_permission=AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        service_method=service_method,
        actor_id="operator-001",
        idempotency_key=idempotency_key,
        operator_intent=operator_intent,
        payload_hash=payload_hash,
        approval_snapshot_required=True,
        approval_store_required=True,
        admission_audit_required=True,
        cap_guard_required=True,
        reconciliation_required=True,
        approval_snapshot_present=True,
        approval_snapshot_id=approval_snapshot_id,
        approval_snapshot_source="approval_store",
        approval_snapshot_approved_by_actor_id=approval.approved_by_actor_id,
        approval_snapshot_requested_by_actor_id=approval.requested_by_actor_id,
        approval_snapshot_expires_at=approval.expires_at.isoformat(),
        admission_audit_present=False,
        cap_guard_present=False,
        reconciliation_plan_present=False,
        browser_authority="rejected",
        live_exchange_submitted=False,
        blockers=[
            AdminApiLiveAdmissionBlocker.LIVE_EXECUTION_DISABLED,
            AdminApiLiveAdmissionBlocker.BROWSER_AUTHORITY_REJECTED,
        ],
        evidence=["prior append-only spot recovery execution admission audit"],
        detail="Prior backend-owned spot recovery execution admission audit.",
    )
    audit_event = AdminApiAuditEvent(
        audit_id=admission_audit_id,
        actor_id="operator-001",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        endpoint=f"POST {route}",
        request_id="corr-spot-recovery-execution-admission",
        operator_intent=operator_intent,
        idempotency_key=idempotency_key,
        approval_id=approval_snapshot_id,
        client_order_id=client_order_id,
        status=AdminApiCommandStatus.REJECTED,
        failure_stage="approval",
        message="Prior spot recovery execution admission audit.",
        admission_decision=admission_decision,
    )
    audit_store.append(audit_event)
    cap_guard = CapGuardDecisionRecord(
        decision_id=cap_guard_decision_id,
        route=route,
        method="POST",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value=client_order_id,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        required_permission=AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        service_method=service_method,
        actor_id="operator-001",
        operator_intent=operator_intent,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        approval_snapshot_id=approval_snapshot_id,
        admission_audit_id=admission_audit_id,
        allowed=True,
        status=AdminApiGateStatus.PASSED,
        cap_policy_ref="spot_recovery_execution_cap:local_only",
        guard_policy_ref="spot_recovery_execution_prerequisites",
        product_scope="USDC spot recovery execution scope",
        max_submitted_notional_usdc="0",
        max_executed_notional_usdc="0",
        reason="Exact backend-owned execution cap/guard evidence.",
    )
    cap_guard_store.append(cap_guard)
    reconciliation = ReconciliationPlanRecord(
        plan_id=reconciliation_plan_id,
        route=route,
        method="POST",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value=client_order_id,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        required_permission=AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        service_method=service_method,
        actor_id="operator-001",
        operator_intent=operator_intent,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        approval_snapshot_id=approval_snapshot_id,
        admission_audit_id=admission_audit_id,
        cap_guard_decision_id=cap_guard_decision_id,
        allowed=True,
        status=AdminApiGateStatus.PASSED,
        reconciliation_policy_ref="spot_recovery_execution_reconciliation",
        product_scope="USDC spot recovery execution scope",
        exchange_submission_required=False,
        post_submit_reconciliation_required=True,
        retained_inventory_required=True,
        max_submitted_notional_usdc="0",
        max_executed_notional_usdc="0",
        reason="Exact backend-owned execution reconciliation plan.",
    )
    reconciliation_store.append(reconciliation)
    return approval, audit_event, cap_guard, reconciliation


def _append_spot_recovery_proof_admission_chain(
    *,
    approval_store: FileAdminApiApprovalStore,
    audit_store: FileAdminApiAuditStore,
    cap_guard_store: FileAdminApiCapGuardStore,
    reconciliation_store: FileAdminApiReconciliationStore,
    route: str,
    service_method: str,
    client_order_id: str,
    idempotency_key: str,
    operator_intent: str,
    payload_hash: str,
    approval_snapshot_id: str,
    admission_audit_id: str,
    cap_guard_decision_id: str,
    reconciliation_plan_id: str,
) -> tuple[AdminApiApprovalRecord, AdminApiAuditEvent, CapGuardDecisionRecord, ReconciliationPlanRecord]:
    now = datetime.now(timezone.utc)
    approval = AdminApiApprovalRecord(
        approval_id=approval_snapshot_id,
        expires_at=now + timedelta(minutes=5),
        approved_by_actor_id="approver-001",
        requested_by_actor_id="operator-001",
        route=route,
        method="POST",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value=client_order_id,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        required_permission=AdminApiPermission.SPOT_RECOVERY_RECORD,
        operator_intent=operator_intent,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        cap_guard_decision_ref=cap_guard_decision_id,
        reconciliation_plan_ref=reconciliation_plan_id,
    )
    approval_store.append(approval)
    admission_decision = AdminLiveAdmissionDecisionEvidence(
        status=AdminApiGateStatus.BLOCKED,
        allowed=False,
        route=route,
        method="POST",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value=client_order_id,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        required_permission=AdminApiPermission.SPOT_RECOVERY_RECORD,
        service_method=service_method,
        actor_id="operator-001",
        idempotency_key=idempotency_key,
        operator_intent=operator_intent,
        payload_hash=payload_hash,
        approval_snapshot_required=True,
        approval_store_required=True,
        admission_audit_required=True,
        cap_guard_required=True,
        reconciliation_required=True,
        approval_snapshot_present=True,
        approval_snapshot_id=approval_snapshot_id,
        approval_snapshot_source="approval_store",
        approval_snapshot_approved_by_actor_id=approval.approved_by_actor_id,
        approval_snapshot_requested_by_actor_id=approval.requested_by_actor_id,
        approval_snapshot_expires_at=approval.expires_at.isoformat(),
        admission_audit_present=False,
        cap_guard_present=False,
        reconciliation_plan_present=False,
        browser_authority="rejected",
        live_exchange_submitted=False,
        blockers=[
            AdminApiLiveAdmissionBlocker.LIVE_EXECUTION_DISABLED,
            AdminApiLiveAdmissionBlocker.BROWSER_AUTHORITY_REJECTED,
        ],
        evidence=["prior append-only spot recovery proof admission audit"],
        detail="Prior backend-owned spot recovery proof admission audit.",
    )
    audit_event = AdminApiAuditEvent(
        audit_id=admission_audit_id,
        actor_id="operator-001",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.SPOT_RECOVERY_RECORD,
        endpoint=f"POST {route}",
        request_id="corr-spot-recovery-proof-admission",
        operator_intent=operator_intent,
        idempotency_key=idempotency_key,
        approval_id=approval_snapshot_id,
        client_order_id=client_order_id,
        status=AdminApiCommandStatus.REJECTED,
        failure_stage="approval",
        message="Prior spot recovery proof admission audit.",
        admission_decision=admission_decision,
    )
    audit_store.append(audit_event)
    cap_guard = CapGuardDecisionRecord(
        decision_id=cap_guard_decision_id,
        route=route,
        method="POST",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value=client_order_id,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        required_permission=AdminApiPermission.SPOT_RECOVERY_RECORD,
        service_method=service_method,
        actor_id="operator-001",
        operator_intent=operator_intent,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        approval_snapshot_id=approval_snapshot_id,
        admission_audit_id=admission_audit_id,
        allowed=True,
        status=AdminApiGateStatus.PASSED,
        cap_policy_ref="spot_recovery_proof_record_cap:local_only",
        guard_policy_ref="spot_recovery_proof_prerequisites",
        product_scope="USDC spot recovery proof scope",
        max_submitted_notional_usdc="0",
        max_executed_notional_usdc="0",
        reason="Exact backend-owned proof-record cap/guard evidence.",
    )
    cap_guard_store.append(cap_guard)
    reconciliation = ReconciliationPlanRecord(
        plan_id=reconciliation_plan_id,
        route=route,
        method="POST",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value=client_order_id,
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        required_permission=AdminApiPermission.SPOT_RECOVERY_RECORD,
        service_method=service_method,
        actor_id="operator-001",
        operator_intent=operator_intent,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        approval_snapshot_id=approval_snapshot_id,
        admission_audit_id=admission_audit_id,
        cap_guard_decision_id=cap_guard_decision_id,
        allowed=True,
        status=AdminApiGateStatus.PASSED,
        reconciliation_policy_ref="spot_recovery_proof_record_reconciliation",
        product_scope="USDC spot recovery proof scope",
        exchange_submission_required=False,
        post_submit_reconciliation_required=False,
        retained_inventory_required=True,
        max_submitted_notional_usdc="0",
        max_executed_notional_usdc="0",
        reason="Exact backend-owned proof-record reconciliation plan.",
    )
    reconciliation_store.append(reconciliation)
    return approval, audit_event, cap_guard, reconciliation


def _append_spot_recovery_apply_audit(
    *,
    audit_store: FileAdminApiAuditStore,
    audit_id: str,
    client_order_id: str,
) -> AdminApiAuditEvent:
    event = AdminApiAuditEvent(
        audit_id=audit_id,
        actor_id="operator-001",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        endpoint="POST /api/v1/spot/recovery/apply-executions",
        request_id="corr-spot-recovery-apply",
        operator_intent="spot_recovery_contract_review",
        idempotency_key="spot-recovery-apply-audit-idem",
        client_order_id=client_order_id,
        status=AdminApiCommandStatus.NOT_IMPLEMENTED,
        failure_stage="approval",
        message="Prior no-live recovery apply audit evidence.",
    )
    audit_store.append(event)
    return event


def _legacy_manual_order_payload(quote_size: str = "1.00") -> dict:
    return {
        "product_id": "BTC-USDC",
        "side": "BUY",
        "order_type": "LIMIT",
        "quote_size": quote_size,
        "limit_price": "65000.00",
        "manual_live_acknowledgement": True,
    }


def _oidc_env() -> dict[str, str]:
    return {
        "COINBASE_ADMIN_API_OIDC_ISSUER": "https://issuer.example.test",
        "COINBASE_ADMIN_API_OIDC_AUDIENCE": "coinbase-admin-api",
        "COINBASE_ADMIN_API_OIDC_JWKS_URL": "https://issuer.example.test/jwks.json",
    }


def _oidc_keypair(kid: str = "test-key-1"):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk["kid"] = kid
    jwk["alg"] = "RS256"
    jwk["use"] = "sig"
    return private_key, {"keys": [jwk]}


def _oidc_token(
    private_key,
    *,
    kid: str = "test-key-1",
    issuer: str = "https://issuer.example.test",
    audience: str = "coinbase-admin-api",
    subject: str = "user-oidc-001",
    roles: list[str] | str | None = None,
    expires_delta: timedelta | None = timedelta(minutes=5),
) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": subject,
        "email": f"{subject}@example.test",
        "iss": issuer,
        "aud": audience,
        "iat": now,
    }
    if expires_delta is not None:
        claims["exp"] = now + expires_delta
    if roles is not None:
        claims["roles"] = roles
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )


@pytest.mark.regression
def test_admin_api_openapi_schema_file_matches_generated_contract():
    generated = generate_openapi_schema(OPENAPI_PATH)
    written = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))

    assert written == generated
    assert "/api/v1/orders" in written["paths"]
    assert "/api/v1/orders/{client_order_id}" in written["paths"]
    assert "/api/v1/orders/{client_order_id}/cancel" in written["paths"]
    assert "/api/v1/stealth/orders" in written["paths"]
    assert "/api/v1/stealth/orders/{stealth_order_id}" in written["paths"]
    assert "/api/v1/stealth/command-suite" in written["paths"]
    assert "/api/v1/stealth/orders/{stealth_order_id}/reveal" in written["paths"]
    assert "/api/v1/stealth/orders/{stealth_order_id}/cancel" in written["paths"]
    assert "/api/v1/movement-repricing/evidence" in written["paths"]
    assert "/api/v1/movement-repricing/orders/{client_order_id}" in written["paths"]
    assert "/api/v1/movement-repricing/stealth/{stealth_order_id}" in written["paths"]
    assert (
        "/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice"
        in written["paths"]
    )
    assert "/api/v1/futures/account" in written["paths"]
    assert "/api/v1/futures/positions" in written["paths"]
    assert "/api/v1/futures/positions/{position_key}" in written["paths"]
    assert "/api/v1/admin/guard-risk-policy" in written["paths"]
    assert "/api/v1/admin/audit-workbench" in written["paths"]
    assert "/api/v1/spot/campaign/executions" in written["paths"]
    assert "/api/v1/spot/sweep/automation-runs" in written["paths"]
    assert "/api/v1/admin/bootstrap" in written["paths"]
    assert "/api/v1/admin/health" in written["paths"]
    assert "/api/v1/admin/session" in written["paths"]
    assert "/api/v1/admin/oidc-readiness" in written["paths"]
    assert "/api/v1/admin/capabilities" in written["paths"]
    assert "/api/v1/admin/csrf" in written["paths"]
    assert "/api/v1/admin/live-enablement" in written["paths"]
    assert "/api/v1/admin/enterprise-readiness" in written["paths"]
    assert "/api/v1/admin/release-gate" in written["paths"]
    assert "/api/v1/admin/recovery-gate" in written["paths"]
    assert "/api/v1/admin/fill-ledger-health" in written["paths"]
    assert "/api/v1/admin/frontend-fixtures" in written["paths"]
    assert "/api/v1/spot/command-suite" in written["paths"]
    assert "/api/v1/spot/readiness" in written["paths"]
    assert "/api/v1/spot/direct-orders/{client_order_id}/audit" in written["paths"]
    assert written["info"]["title"] == "Coinbase Admin API"
    order_operation = written["paths"]["/api/v1/orders"]["post"]
    header_params = {
        param["name"]: param
        for param in order_operation["parameters"]
        if param["in"] == "header"
    }
    assert header_params["Authorization"]["required"] is True
    for header_name in ("X-Admin-Actor", "X-Admin-Roles"):
        assert header_params[header_name]["required"] is False
        assert "bootstrap_bearer" in header_params[header_name]["description"]
        assert "oidc_jwt" in header_params[header_name]["description"]
    for status_code in ("200", "400", "401", "403", "409", "501"):
        assert status_code in order_operation["responses"]
    stealth_create_operation = written["paths"]["/api/v1/stealth/orders"]["post"]
    for status_code in ("200", "400", "401", "403", "409", "501"):
        assert status_code in stealth_create_operation["responses"]
    cancel_operation = written["paths"]["/api/v1/orders/{client_order_id}/cancel"][
        "post"
    ]
    assert "200" in cancel_operation["responses"]
    assert "501" in cancel_operation["responses"]
    stealth_cancel_operation = written["paths"][
        "/api/v1/stealth/orders/{stealth_order_id}/cancel"
    ]["post"]
    assert "200" in stealth_cancel_operation["responses"]
    assert "501" in stealth_cancel_operation["responses"]
    stealth_command_suite_operation = written["paths"]["/api/v1/stealth/command-suite"][
        "get"
    ]
    assert "200" in stealth_command_suite_operation["responses"]
    assert "content" in stealth_command_suite_operation["responses"]["200"]
    assert "401" in stealth_command_suite_operation["responses"]
    assert "403" in stealth_command_suite_operation["responses"]
    movement_reprice_operation = written["paths"][
        "/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice"
    ]["post"]
    assert "200" in movement_reprice_operation["responses"]
    assert "501" in movement_reprice_operation["responses"]
    campaign_operation = written["paths"]["/api/v1/spot/campaign/executions"]["post"]
    assert "200" in campaign_operation["responses"]
    assert "501" in campaign_operation["responses"]
    sweep_operation = written["paths"]["/api/v1/spot/sweep/automation-runs"]["post"]
    assert "200" in sweep_operation["responses"]
    assert "501" in sweep_operation["responses"]
    for recovery_command_path in (
        "/api/v1/spot/recovery/apply-executions",
        "/api/v1/spot/recovery/rollback-executions",
    ):
        recovery_command_operation = written["paths"][recovery_command_path]["post"]
        assert "200" in recovery_command_operation["responses"]
        assert "400" in recovery_command_operation["responses"]
        assert "501" not in recovery_command_operation["responses"]
    for recovery_proof_path in (
        "/api/v1/spot/recovery/exchange-state-snapshots",
        "/api/v1/spot/recovery/exchange-state-proofs",
        "/api/v1/spot/recovery/reconciliation-proofs",
    ):
        recovery_proof_operation = written["paths"][recovery_proof_path]["post"]
        assert "200" in recovery_proof_operation["responses"]
        assert "400" in recovery_proof_operation["responses"]
        assert "501" not in recovery_proof_operation["responses"]
        assert "proof record" in (
            recovery_proof_operation["responses"]["200"]["description"].lower()
        )
    spot_readiness_operation = written["paths"]["/api/v1/spot/readiness"]["get"]
    assert "200" in spot_readiness_operation["responses"]
    assert "content" in spot_readiness_operation["responses"]["200"]
    assert "401" in spot_readiness_operation["responses"]
    assert "403" in spot_readiness_operation["responses"]
    spot_command_suite_operation = written["paths"]["/api/v1/spot/command-suite"][
        "get"
    ]
    assert "200" in spot_command_suite_operation["responses"]
    assert "content" in spot_command_suite_operation["responses"]["200"]
    assert "401" in spot_command_suite_operation["responses"]
    assert "403" in spot_command_suite_operation["responses"]
    spot_recovery_preview_operation = written["paths"][
        "/api/v1/spot/recovery/preview"
    ]["get"]
    assert "200" in spot_recovery_preview_operation["responses"]
    assert "content" in spot_recovery_preview_operation["responses"]["200"]
    assert "401" in spot_recovery_preview_operation["responses"]
    assert "403" in spot_recovery_preview_operation["responses"]
    for recovery_contract_path in (
        "/api/v1/spot/recovery/apply-review",
        "/api/v1/spot/recovery/rollback-plan",
        "/api/v1/spot/recovery/reconciliation-proof",
    ):
        recovery_contract_operation = written["paths"][recovery_contract_path]["get"]
        assert "200" in recovery_contract_operation["responses"]
        assert "content" in recovery_contract_operation["responses"]["200"]
        assert "401" in recovery_contract_operation["responses"]
        assert "403" in recovery_contract_operation["responses"]
    order_item_schema = written["components"]["schemas"]["AdminOrderReadItem"]
    assert "client_order_id" in order_item_schema["properties"]
    assert "order_id" not in order_item_schema["properties"]
    assert "exchange_order_id" in order_item_schema["properties"]
    assert "correlation_id" in order_item_schema["properties"]
    assert "audit_id" in order_item_schema["properties"]
    order_list_schema = written["components"]["schemas"]["AdminOrderListResponse"]
    assert "pagination" in order_list_schema["properties"]
    stealth_item_schema = written["components"]["schemas"]["AdminStealthOrderReadItem"]
    assert "stealth_order_id" in stealth_item_schema["properties"]
    assert "active_placement_client_order_id" in stealth_item_schema["properties"]
    assert "active_exchange_order_id" in stealth_item_schema["properties"]
    assert "exchange_order_id_evidence_only" in stealth_item_schema["properties"]
    assert "order_id" not in stealth_item_schema["properties"]
    stealth_detail_schema = written["components"]["schemas"][
        "AdminStealthOrderDetailResponse"
    ]
    assert "active_placement_audit" in stealth_detail_schema["properties"]
    assert "AdminStealthActivePlacementAuditEvidence" in written["components"]["schemas"]
    active_placement_audit_schema = written["components"]["schemas"][
        "AdminStealthActivePlacementAuditEvidence"
    ]
    assert "active_placement_client_order_id" in active_placement_audit_schema[
        "properties"
    ]
    assert "exchange_truth_verified" in active_placement_audit_schema["properties"]
    assert "coinbase_read_ran" in active_placement_audit_schema["properties"]
    assert "lifecycle_mutation_allowed" in active_placement_audit_schema["properties"]
    assert "mutation_claim_audit" in stealth_detail_schema["properties"]
    assert "AdminStealthMutationClaimAuditEvidence" in written["components"]["schemas"]
    mutation_claim_audit_schema = written["components"]["schemas"][
        "AdminStealthMutationClaimAuditEvidence"
    ]
    assert "runtime_claims" in mutation_claim_audit_schema["properties"]
    assert "runtime_claims_observed" in mutation_claim_audit_schema["properties"]
    assert "active_claim_count" in mutation_claim_audit_schema["properties"]
    assert "lifecycle_mutation_allowed" in mutation_claim_audit_schema["properties"]
    assert "reveal_trigger_audit" in stealth_detail_schema["properties"]
    assert "AdminStealthRevealTriggerAuditEvidence" in written["components"]["schemas"]
    reveal_trigger_audit_schema = written["components"]["schemas"][
        "AdminStealthRevealTriggerAuditEvidence"
    ]
    assert "reveal_condition_present" in reveal_trigger_audit_schema["properties"]
    assert "trigger_evaluation_ran" in reveal_trigger_audit_schema["properties"]
    assert "reveal_order_slice_called" in reveal_trigger_audit_schema["properties"]
    assert "coinbase_order_submit_ran" in reveal_trigger_audit_schema["properties"]
    assert "reveal_submission_audit" in stealth_detail_schema["properties"]
    assert "AdminStealthRevealSubmissionAuditEvidence" in written["components"][
        "schemas"
    ]
    reveal_submission_audit_schema = written["components"]["schemas"][
        "AdminStealthRevealSubmissionAuditEvidence"
    ]
    assert "command_route" in reveal_submission_audit_schema["properties"]
    assert "reveal_manager_method" in reveal_submission_audit_schema["properties"]
    assert "submission_adapter_configured" in reveal_submission_audit_schema[
        "properties"
    ]
    assert "reveal_order_slice_called" in reveal_submission_audit_schema["properties"]
    assert "coinbase_order_submit_ran" in reveal_submission_audit_schema["properties"]
    assert "active_placement_created" in reveal_submission_audit_schema["properties"]
    command_response_schema = written["components"]["schemas"]["AdminApiCommandResponse"]
    assert "stealth_order_id" in command_response_schema["properties"]
    assert "admission_decision" in command_response_schema["properties"]
    assert "AdminLiveAdmissionDecisionEvidence" in written["components"]["schemas"]
    stealth_create_request_schema = written["components"]["schemas"][
        "StealthCreateRequest"
    ]
    assert "stealth_order_id" in stealth_create_request_schema["properties"]
    assert "reveal_condition" in stealth_create_request_schema["required"]
    assert "manual_live_acknowledgement" in stealth_create_request_schema["properties"]
    stealth_reveal_request_schema = written["components"]["schemas"][
        "StealthRevealRequest"
    ]
    assert "reason" in stealth_reveal_request_schema["properties"]
    assert "manual_live_acknowledgement" in stealth_reveal_request_schema["properties"]
    assert "order_id" not in stealth_reveal_request_schema["properties"]
    stealth_list_schema = written["components"]["schemas"]["AdminStealthOrderListResponse"]
    assert "pagination" in stealth_list_schema["properties"]
    assert "command_routes_mode" in stealth_list_schema["properties"]
    stealth_command_suite_schema = written["components"]["schemas"][
        "StealthCommandSuiteResponse"
    ]
    assert "commands" in stealth_command_suite_schema["properties"]
    assert "coverage_gaps" in stealth_command_suite_schema["properties"]
    assert "exchange_truth_required" in stealth_command_suite_schema["properties"]
    assert "exchange_truth_checks" in stealth_command_suite_schema["properties"]
    assert "exchange_truth_check_count" in stealth_command_suite_schema["properties"]
    movement_item_schema = written["components"]["schemas"][
        "AdminMovementRepricingEvidenceItem"
    ]
    assert "client_order_id" in movement_item_schema["properties"]
    assert "original_parent_client_order_id" in movement_item_schema["properties"]
    assert "stealth_order_id" in movement_item_schema["properties"]
    assert "mutation_claims" in movement_item_schema["properties"]
    assert "replacement_slots" in movement_item_schema["properties"]
    assert "active_placement_client_order_id" in movement_item_schema["properties"]
    assert "active_exchange_order_id" in movement_item_schema["properties"]
    assert "exchange_order_id_evidence_only" in movement_item_schema["properties"]
    assert "order_id" not in movement_item_schema["properties"]
    movement_list_schema = written["components"]["schemas"][
        "AdminMovementRepricingListResponse"
    ]
    assert "command_routes_mode" in movement_list_schema["properties"]
    futures_position_schema = written["components"]["schemas"][
        "AdminFuturesPositionReadItem"
    ]
    assert "position_key" in futures_position_schema["properties"]
    assert "product_id" in futures_position_schema["properties"]
    assert "client_order_id" not in futures_position_schema["properties"]
    assert "order_id" not in futures_position_schema["properties"]
    assert "cost_basis" not in futures_position_schema["properties"]
    futures_account_schema = written["components"]["schemas"][
        "AdminFuturesAccountReadResponse"
    ]
    assert "collateral" in futures_account_schema["properties"]
    assert "margin" in futures_account_schema["properties"]
    assert "funding" in futures_account_schema["properties"]
    assert "liquidation" in futures_account_schema["properties"]
    assert "command_routes_mode" in futures_account_schema["properties"]
    risk_policy_schema = written["components"]["schemas"][
        "AdminRiskPolicyReadResponse"
    ]
    assert "action_condition_policy" in risk_policy_schema["properties"]
    assert "configured_limit_rules" in risk_policy_schema["properties"]
    assert "live_execution_gate" in risk_policy_schema["properties"]
    assert "product_capability_policy" in risk_policy_schema["properties"]
    assert "product_capability_decisions" in risk_policy_schema["properties"]
    assert "profitability_policy" in risk_policy_schema["properties"]
    assert "authority_sources" in risk_policy_schema["properties"]
    assert "rejection_categories" in risk_policy_schema["properties"]
    live_path_schema = written["components"]["schemas"][
        "AdminLiveEnablementPathItem"
    ]
    assert "approval_snapshot" in live_path_schema["properties"]
    assert "approval_store_contract" in live_path_schema["properties"]
    assert "admission_audit_trail" in live_path_schema["properties"]
    assert "cap_guard_contract" in live_path_schema["properties"]
    assert "readiness_preconditions" in live_path_schema["properties"]
    assert "readiness_precondition_count" in live_path_schema["properties"]
    assert "blocking_readiness_precondition_count" in live_path_schema["properties"]
    assert "passed_readiness_precondition_count" in live_path_schema["properties"]
    live_response_schema = written["components"]["schemas"][
        "AdminLiveEnablementReadResponse"
    ]
    assert "admission_audit_required_count" in live_response_schema["properties"]
    assert "admission_audit_configured_count" in live_response_schema["properties"]
    assert "admission_audit_missing_count" in live_response_schema["properties"]
    assert "admission_audit_fact_count" in live_response_schema["properties"]
    assert "admission_audit_missing_fact_count" in live_response_schema["properties"]
    assert "cap_guard_required_count" in live_response_schema["properties"]
    assert "cap_guard_configured_count" in live_response_schema["properties"]
    assert "cap_guard_missing_count" in live_response_schema["properties"]
    assert "cap_guard_requirement_count" in live_response_schema["properties"]
    assert "cap_guard_missing_requirement_count" in live_response_schema["properties"]
    assert "readiness_precondition_count" in live_response_schema["properties"]
    assert "blocking_readiness_precondition_count" in live_response_schema["properties"]
    assert "passed_readiness_precondition_count" in live_response_schema["properties"]
    audit_workbench_schema = written["components"]["schemas"][
        "AdminAuditWorkbenchReadResponse"
    ]
    assert "module_summary" in audit_workbench_schema["properties"]
    assert "events" in audit_workbench_schema["properties"]
    audit_event_schema = written["components"]["schemas"][
        "AdminAuditWorkbenchEventItem"
    ]
    assert "client_order_id" in audit_event_schema["properties"]
    assert "exchange_order_id" in audit_event_schema["properties"]
    assert "exchange_order_id_evidence_only" in audit_event_schema["properties"]
    assert "operator_intent" in audit_event_schema["properties"]
    assert "admission_decision" in audit_event_schema["properties"]
    assert "order_id" not in audit_event_schema["properties"]
    spot_readiness_schema = written["components"]["schemas"]["SpotReadinessResponse"]
    assert "products" in spot_readiness_schema["properties"]
    assert "wallet_snapshot" in spot_readiness_schema["properties"]
    spot_command_suite_schema = written["components"]["schemas"][
        "SpotCommandSuiteResponse"
    ]
    assert "commands" in spot_command_suite_schema["properties"]
    assert "blocked_command_count" in spot_command_suite_schema["properties"]
    assert "spot_rules_platform_default" in spot_command_suite_schema["properties"]
    spot_recovery_preview_schema = written["components"]["schemas"][
        "SpotRecoveryPreviewResponse"
    ]
    assert "sources" in spot_recovery_preview_schema["properties"]
    assert "missing_contracts" in spot_recovery_preview_schema["properties"]
    assert "apply_review_contract_available" in spot_recovery_preview_schema[
        "properties"
    ]
    for schema_name in (
        "SpotRecoveryApplyReviewResponse",
        "SpotRecoveryRollbackPlanResponse",
        "SpotRecoveryReconciliationProofResponse",
    ):
        assert schema_name in written["components"]["schemas"]
        assert "candidates" in written["components"]["schemas"][schema_name][
            "properties"
        ]
        assert "missing_contracts" in written["components"]["schemas"][schema_name][
            "properties"
        ]
    for schema_name in (
        "SpotRecoveryApplyExecutionRequest",
        "SpotRecoveryRollbackExecutionRequest",
        "SpotRecoveryExchangeStateProofRequest",
        "SpotRecoveryExchangeStateSnapshotRequest",
        "SpotRecoveryReconciliationExecutionRequest",
        "SpotRecoveryReconciliationProofRecordRequest",
    ):
        assert schema_name in written["components"]["schemas"]
        assert "client_order_id" in written["components"]["schemas"][schema_name][
            "properties"
        ]
        assert "order_id" not in written["components"]["schemas"][schema_name][
            "properties"
        ]
    spot_pnl_schema = written["components"]["schemas"]["SpotSweepPnlResponse"]
    assert "pnl_report" in spot_pnl_schema["properties"]
    for schema_name, component_schema in written["components"]["schemas"].items():
        enum_values = component_schema.get("enum")
        if enum_values is not None:
            assert len(enum_values) == len(set(enum_values)), schema_name


@pytest.mark.regression
def test_admin_api_route_inventory_export_file_matches_generated_contract():
    generated = write_admin_api_route_inventory_export(ROUTE_INVENTORY_EXPORT_PATH)
    written = json.loads(ROUTE_INVENTORY_EXPORT_PATH.read_text(encoding="utf-8"))

    assert written == generated
    assert generated == build_admin_api_route_inventory_export()
    command_routes = {
        (item["method"], item["path"]): item
        for item in written["routes"]
        if item["command_contract"]
    }
    assert command_routes[("POST", "/api/v1/orders")] == {
        "module_id": "spot_operations",
        "surface": "POST /api/v1/orders",
        "method": "POST",
        "path": "/api/v1/orders",
        "action_class": AdminApiActionClass.LIVE_EXCHANGE_PLACE.value,
        "permission": AdminApiPermission.ORDER_CREATE.value,
        "idempotency": "required",
        "approval": "required",
        "caps": "required",
        "audit": "required",
        "shared_method": "place_manual_order",
        "parity_test": "HTTP vs place_order guard/result parity",
        "compatibility_mode": None,
        "command_contract": True,
    }
    assert command_routes[
        ("POST", "/api/v1/orders/{client_order_id}/cancel")
    ]["shared_method"] == "cancel_order_by_client_order_id"
    assert command_routes[
        ("POST", "/api/v1/orders/{client_order_id}/cancel")
    ]["module_id"] == "spot_operations"
    assert command_routes[("POST", "/api/v1/stealth/orders")] == {
        "module_id": "stealth_orders",
        "surface": "POST /api/v1/stealth/orders",
        "method": "POST",
        "path": "/api/v1/stealth/orders",
        "action_class": AdminApiActionClass.LOCAL_STATE_MUTATION.value,
        "permission": AdminApiPermission.ORDER_CREATE.value,
        "idempotency": "required",
        "approval": "required by current HTTP live-disabled gate",
        "caps": "required for planning guards before lifecycle writes",
        "audit": "required",
        "shared_method": "create_stealth_order",
        "parity_test": (
            "stealth_order_id identity; no local stealth state mutation until "
            "lifecycle-write gates are complete"
        ),
        "compatibility_mode": None,
        "command_contract": True,
    }
    assert command_routes[
        ("POST", "/api/v1/stealth/orders/{stealth_order_id}/reveal")
    ] == {
        "module_id": "stealth_orders",
        "surface": "POST /api/v1/stealth/orders/{stealth_order_id}/reveal",
        "method": "POST",
        "path": "/api/v1/stealth/orders/{stealth_order_id}/reveal",
        "action_class": AdminApiActionClass.LIVE_EXCHANGE_PLACE.value,
        "permission": AdminApiPermission.ORDER_CREATE.value,
        "idempotency": "required",
        "approval": "required by current HTTP live-disabled gate",
        "caps": (
            "required for trigger, placement, guard, and reconciliation evidence"
        ),
        "audit": "required",
        "shared_method": "reveal_stealth_order_by_stealth_order_id",
        "parity_test": (
            "stealth_order_id identity; no reveal placement or lifecycle "
            "mutation until exchange-submission gates are complete"
        ),
        "compatibility_mode": None,
        "command_contract": True,
    }
    assert command_routes[
        ("POST", "/api/v1/spot/campaign/executions")
    ]["permission"] == AdminApiPermission.CAMPAIGN_EXECUTE.value
    route_modules = {
        item["path"]: item["module_id"]
        for item in written["routes"]
        if item["path"]
    }
    assert route_modules["/api/v1/admin/bootstrap"] == "admin_system_health"
    assert route_modules["/api/v1/admin/guard-risk-policy"] == "guard_risk_policy"
    assert route_modules["/api/v1/admin/audit-workbench"] == "audit_workbench"
    assert route_modules["/api/v1/futures/account"] == "futures_perpetuals"
    assert route_modules["/api/v1/stealth/orders"] == "stealth_orders"
    assert route_modules["/api/v1/stealth/orders/{stealth_order_id}/reveal"] == (
        "stealth_orders"
    )
    assert route_modules["/api/v1/stealth/command-suite"] == "stealth_orders"
    assert (
        route_modules["/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice"]
        == "movement_repricing"
    )
    assert route_modules["/api/v1/spot/readiness"] == "spot_operations"
    assert route_modules["/api/v1/spot/command-suite"] == "spot_operations"
    websocket_modules = {
        item["surface"]: item["module_id"]
        for item in written["routes"]
        if item["path"] is None
    }
    assert set(websocket_modules.values()) == {"legacy_dashboard_websocket"}


@pytest.mark.regression
def test_admin_api_mutating_routes_fail_closed_without_auth(monkeypatch):
    monkeypatch.delenv("COINBASE_ADMIN_API_BEARER_TOKEN", raising=False)
    client = _client(monkeypatch)
    monkeypatch.delenv("COINBASE_ADMIN_API_BEARER_TOKEN", raising=False)

    response = client.post(
        "/api/v1/orders",
        headers={k: v for k, v in _headers().items() if k != "Authorization"},
        json=_manual_order_payload(),
    )

    assert response.status_code == 401
    assert response.json()["code"] == AdminApiErrorCode.AUTH_REQUIRED.value
    assert response.headers["x-live-execution-enabled"] == "false"
    assert response.headers["x-correlation-id"]


@pytest.mark.regression
def test_admin_api_oidc_auth_mode_fails_closed_without_required_config(monkeypatch):
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", AdminApiAuthMode.OIDC_JWT.value)
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-admin-token")
    for key in oidc_jwt_required_env_vars():
        monkeypatch.delenv(key, raising=False)
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/admin/bootstrap",
        headers={"Authorization": "Bearer invalid-unverified-token"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == AdminApiErrorCode.AUTH_REQUIRED.value
    assert "OIDC/JWT verifier is not configured" in response.json()["message"]
    assert response.headers["x-live-execution-enabled"] == "false"


@pytest.mark.regression
def test_admin_api_oidc_auth_mode_accepts_valid_jwt_and_uses_claim_roles(
    monkeypatch,
):
    from application.admin_api import auth as auth_module

    private_key, jwks = _oidc_keypair()
    token = _oidc_token(private_key, roles=[AdminApiRole.VIEWER.value])
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", AdminApiAuthMode.OIDC_JWT.value)
    for key, value in _oidc_env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(auth_module, "_fetch_oidc_jwks", lambda _: jwks)
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/admin/session",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Admin-Actor": "forged-browser-actor",
            "X-Admin-Roles": AdminApiRole.ADMIN.value,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["actor"] == {
        "actor_id": "user-oidc-001",
        "roles": [AdminApiRole.VIEWER.value],
    }
    assert payload["auth_mode"] == AdminApiAuthMode.OIDC_JWT.value
    assert payload["bearer_token_visible_to_browser"] is False
    assert AdminApiPermission.ANALYTICS_READ.value in payload["permissions"]
    assert AdminApiPermission.ORDER_CREATE.value not in payload["permissions"]


@pytest.mark.regression
def test_admin_api_oidc_readiness_reports_required_env_and_no_live_boundary(monkeypatch):
    for key in oidc_jwt_required_env_vars():
        monkeypatch.delenv(key, raising=False)

    readiness = build_oidc_jwt_readiness()

    assert readiness.mode == AdminApiAuthMode.OIDC_JWT
    assert readiness.status == AdminApiVerifierReadinessStatus.BLOCKED
    assert readiness.verifier_implemented is True
    assert readiness.required_env_vars == (
        "COINBASE_ADMIN_API_OIDC_ISSUER",
        "COINBASE_ADMIN_API_OIDC_AUDIENCE",
        "COINBASE_ADMIN_API_OIDC_JWKS_URL",
    )
    assert readiness.missing_env_vars == readiness.required_env_vars
    assert readiness.live_coinbase_execution == "not_run"
    assert readiness.notional_usdc == "0"
    assert readiness.to_dict() == {
        "mode": "oidc_jwt",
        "status": "blocked",
        "verifier_implemented": True,
        "required_env_vars": [
            "COINBASE_ADMIN_API_OIDC_ISSUER",
            "COINBASE_ADMIN_API_OIDC_AUDIENCE",
            "COINBASE_ADMIN_API_OIDC_JWKS_URL",
        ],
        "missing_env_vars": [
            "COINBASE_ADMIN_API_OIDC_ISSUER",
            "COINBASE_ADMIN_API_OIDC_AUDIENCE",
            "COINBASE_ADMIN_API_OIDC_JWKS_URL",
        ],
        "claims_contract": {
            "subject": "sub",
            "email": "email",
            "roles": "roles",
            "issuer": "iss",
            "audience": "aud",
        },
        "failure_reason": "Admin API OIDC/JWT verifier is not configured",
        "live_coinbase_execution": "not_run",
        "notional_usdc": "0",
    }

    monkeypatch.setenv("COINBASE_ADMIN_API_OIDC_ISSUER", "https://issuer.example.test")
    monkeypatch.setenv("COINBASE_ADMIN_API_OIDC_AUDIENCE", "coinbase-admin-api")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OIDC_JWKS_URL",
        "https://issuer.example.test/.well-known/jwks.json",
    )

    configured_readiness = build_oidc_jwt_readiness()

    assert configured_readiness.status == AdminApiVerifierReadinessStatus.READY
    assert configured_readiness.missing_env_vars == ()
    assert configured_readiness.failure_reason is None


@pytest.mark.regression
def test_admin_api_oidc_readiness_route_reports_env_jwks_and_no_live(monkeypatch):
    from application.admin_api import auth as auth_module

    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-admin-token")
    for key in oidc_jwt_required_env_vars():
        monkeypatch.delenv(key, raising=False)
    client = TestClient(create_app())

    missing_response = client.get(
        "/api/v1/admin/oidc-readiness",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )

    assert missing_response.status_code == 200
    missing_payload = missing_response.json()
    assert missing_payload["type"] == "admin_oidc_jwt_readiness"
    assert missing_payload["active_auth_mode"] == AdminApiAuthMode.BOOTSTRAP_BEARER.value
    assert missing_payload["mode"] == AdminApiAuthMode.OIDC_JWT.value
    assert missing_payload["status"] == AdminApiVerifierReadinessStatus.BLOCKED.value
    assert missing_payload["verifier_implemented"] is True
    assert missing_payload["missing_env_vars"] == list(oidc_jwt_required_env_vars())
    assert missing_payload["jwks_reachability"] == "not_checked"
    assert missing_payload["live_coinbase_execution"] == "not_run"
    assert missing_payload["notional_usdc"] == "0"
    assert missing_payload["live_coinbase_orders_ran"] is False

    for key, value in _oidc_env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(auth_module, "_fetch_oidc_jwks", lambda _: {"keys": []})

    ready_response = client.get(
        "/api/v1/admin/oidc-readiness",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )

    assert ready_response.status_code == 200
    ready_payload = ready_response.json()
    assert ready_payload["status"] == AdminApiVerifierReadinessStatus.READY.value
    assert ready_payload["missing_env_vars"] == []
    assert ready_payload["failure_reason"] is None
    assert ready_payload["jwks_reachability"] == "reachable"
    assert ready_payload["jwks_failure_reason"] is None


@pytest.mark.regression
def test_admin_api_oidc_verifier_maps_roles_from_jwt_claims():
    private_key, jwks = _oidc_keypair()
    token = _oidc_token(private_key, roles="viewer,trader")

    actor = verify_oidc_jwt(token, env=_oidc_env(), jwks=jwks)

    assert actor.actor_id == "user-oidc-001"
    assert actor.roles == [AdminApiRole.VIEWER, AdminApiRole.TRADER]


@pytest.mark.regression
@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda key: _oidc_token(
                rsa.generate_private_key(public_exponent=65537, key_size=2048),
                roles=[AdminApiRole.VIEWER.value],
            ),
            "Invalid Admin API OIDC/JWT token",
        ),
        (
            lambda key: _oidc_token(
                key,
                issuer="https://wrong-issuer.example.test",
                roles=[AdminApiRole.VIEWER.value],
            ),
            "Invalid Admin API OIDC/JWT issuer",
        ),
        (
            lambda key: _oidc_token(
                key,
                audience="wrong-audience",
                roles=[AdminApiRole.VIEWER.value],
            ),
            "Invalid Admin API OIDC/JWT audience",
        ),
        (
            lambda key: _oidc_token(
                key,
                roles=[AdminApiRole.VIEWER.value],
                expires_delta=timedelta(minutes=-1),
            ),
            "Expired Admin API OIDC/JWT token",
        ),
        (
            lambda key: _oidc_token(key, roles=None),
            "Missing Admin API role evidence",
        ),
        (
            lambda key: _oidc_token(
                key,
                roles=[AdminApiRole.VIEWER.value],
                expires_delta=None,
            ),
            "Missing required Admin API OIDC/JWT claim",
        ),
    ],
)
def test_admin_api_oidc_verifier_fails_closed_for_invalid_tokens(mutator, message):
    private_key, jwks = _oidc_keypair()
    token = mutator(private_key)

    with pytest.raises(OidcJwtVerificationError, match=message):
        verify_oidc_jwt(token, env=_oidc_env(), jwks=jwks)


@pytest.mark.regression
def test_admin_api_oidc_route_fails_closed_when_jwks_fetch_fails(monkeypatch):
    from application.admin_api import auth as auth_module

    private_key, _jwks = _oidc_keypair()
    token = _oidc_token(private_key, roles=[AdminApiRole.VIEWER.value])
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", AdminApiAuthMode.OIDC_JWT.value)
    for key, value in _oidc_env().items():
        monkeypatch.setenv(key, value)

    def _raise_fetch_error(_url: str):
        raise OidcJwtVerificationError("Unable to fetch Admin API OIDC/JWT JWKS")

    monkeypatch.setattr(auth_module, "_fetch_oidc_jwks", _raise_fetch_error)
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/admin/session",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == AdminApiErrorCode.AUTH_REQUIRED.value
    assert "Unable to fetch Admin API OIDC/JWT JWKS" in response.json()["message"]
    assert response.headers["x-live-execution-enabled"] == "false"


@pytest.mark.regression
def test_admin_api_oidc_readiness_smoke_is_no_live_and_covers_required_steps():
    args = build_admin_oidc_readiness_smoke_parser().parse_args(["--summary-only"])

    assert args.summary_only is True
    assert ADMIN_OIDC_READINESS_SMOKE_SUMMARY_PREFIX == (
        "ADMIN_OIDC_READINESS_SMOKE_SUMMARY "
    )

    summary = build_admin_oidc_readiness_smoke_summary()

    assert summary["status"] == AdminApiGateStatus.PASSED.value
    assert summary["live_coinbase_orders_ran"] is False
    assert summary["live_order_notional_usdc"] == "0"
    assert {step["name"] for step in summary["steps"]} == {
        "missing_config_readiness_blocks",
        "configured_readiness_reports_reachable_jwks",
        "oidc_session_uses_verified_claim_roles",
    }
    assert all(step["passed"] is True for step in summary["steps"])


@pytest.mark.regression
def test_admin_api_mutating_routes_fail_closed_on_rbac_denial(monkeypatch):
    client = _client(monkeypatch)

    response = client.post(
        "/api/v1/orders",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
        json=_manual_order_payload(),
    )

    assert response.status_code == 403


@pytest.mark.regression
def test_admin_api_cors_is_limited_to_configured_frontend_origins(monkeypatch):
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-admin-token")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_CORS_ORIGINS",
        "http://127.0.0.1:3000,https://admin.example.test",
    )
    client = TestClient(create_app())

    allowed = client.options(
        "/api/v1/admin/bootstrap",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": (
                "Authorization,X-Admin-Actor,X-Admin-Roles,X-CSRF-Token"
            ),
        },
    )
    denied = client.options(
        "/api/v1/admin/bootstrap",
        headers={
            "Origin": "https://unapproved.example.test",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
    assert "X-CSRF-Token" in allowed.headers["access-control-allow-headers"]
    assert "access-control-allow-origin" not in denied.headers


@pytest.mark.regression
def test_admin_api_csrf_is_enforced_for_mutations_when_configured(monkeypatch):
    monkeypatch.setenv("COINBASE_ADMIN_API_CSRF_REQUIRED", "true")
    monkeypatch.setenv("COINBASE_ADMIN_API_CSRF_TOKEN", "csrf-test-token")
    client = _client(monkeypatch)

    read_response = client.get(
        "/api/v1/admin/bootstrap",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    missing_csrf = client.post(
        "/api/v1/orders",
        headers=_headers(),
        json=_manual_order_payload(),
    )
    accepted_csrf = client.post(
        "/api/v1/orders",
        headers={**_headers(idempotency_key="idem-csrf-ok"), "X-CSRF-Token": "csrf-test-token"},
        json=_manual_order_payload(),
    )

    assert read_response.status_code == 200
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == AdminApiErrorCode.PERMISSION_DENIED.value
    assert missing_csrf.headers["x-live-execution-enabled"] == "false"
    assert accepted_csrf.status_code == 501
    assert accepted_csrf.json()["live_exchange_submitted"] is False


@pytest.mark.regression
def test_admin_api_create_manual_order_contract_is_not_implemented_and_not_live(
    monkeypatch,
):
    client = _client(monkeypatch)

    response = client.post(
        "/api/v1/orders",
        headers=_headers(),
        json=_manual_order_payload(),
    )

    assert response.status_code == 501
    payload = response.json()
    assert payload["status"] == AdminApiCommandStatus.NOT_IMPLEMENTED.value
    assert payload["action_class"] == AdminApiActionClass.LIVE_EXCHANGE_PLACE.value
    assert payload["required_permission"] == AdminApiPermission.ORDER_CREATE.value
    assert payload["service_method"] == "place_manual_order"
    client_order_id = payload["client_order_id"]
    assert client_order_id
    assert payload["live_exchange_submitted"] is False
    assert payload["failure_stage"] == "approval"
    assert payload["guard"]["approval_snapshot_required"] is True
    assert payload["guard"]["cap_evaluation_required"] is True
    assert payload["guard"]["live_execution_enabled"] is False
    admission = payload["admission_decision"]
    assert admission["status"] == AdminApiGateStatus.BLOCKED.value
    assert admission["allowed"] is False
    assert admission["route"] == "/api/v1/orders"
    assert admission["method"] == "POST"
    assert admission["module_id"] == "spot_operations"
    assert admission["identity_key"] == "client_order_id"
    assert admission["identity_value"] == client_order_id
    assert admission["service_method"] == "place_manual_order"
    assert admission["actor_id"] == "operator-001"
    assert admission["idempotency_key"] == "idem-001"
    assert admission["operator_intent"] == "manual_one_off"
    assert len(admission["payload_hash"]) == 64
    assert admission["approval_snapshot_required"] is True
    assert admission["approval_store_required"] is True
    assert admission["admission_audit_required"] is True
    assert admission["cap_guard_required"] is True
    assert admission["reconciliation_required"] is True
    assert admission["approval_snapshot_present"] is False
    assert admission["approval_snapshot_id"] is None
    assert admission["approval_snapshot_source"] == "missing"
    assert admission["approval_snapshot_missing_reason"] == (
        "no_matching_unexpired_snapshot"
    )
    assert admission["admission_audit_present"] is False
    assert admission["admission_audit_id"] is None
    assert admission["admission_audit_source"] == "missing"
    assert admission["admission_audit_recorded_at"] is None
    assert admission["admission_audit_missing_reason"] == "approval_snapshot_missing"
    assert admission["cap_guard_present"] is False
    assert admission["cap_guard_decision_id"] is None
    assert admission["cap_guard_source"] == "missing"
    assert admission["cap_guard_recorded_at"] is None
    assert admission["cap_guard_missing_reason"] == "approval_snapshot_missing"
    assert admission["reconciliation_plan_present"] is False
    assert admission["reconciliation_plan_id"] is None
    assert admission["reconciliation_plan_source"] == "missing"
    assert admission["reconciliation_plan_recorded_at"] is None
    assert admission["reconciliation_plan_missing_reason"] == (
        "approval_snapshot_missing"
    )
    assert admission["live_execution_service_required"] is True
    assert admission["live_execution_service_present"] is True
    assert admission["live_execution_service_status"] == "live_disabled"
    assert admission["live_execution_service_source"] == "disabled_backend_service"
    assert admission["live_execution_service_missing_reason"] == (
        "live_execution_disabled"
    )
    assert admission["browser_authority"] == "rejected"
    assert admission["live_exchange_submitted"] is False
    _assert_disabled_live_execution_intent(
        admission["live_execution_intent"],
        route="/api/v1/orders",
        method="POST",
        module_id="spot_operations",
        service_method="place_manual_order",
        identity_key="client_order_id",
        identity_value=client_order_id,
    )
    assert "approval_store_missing" not in admission["blockers"]
    assert "approval_snapshot_missing" in admission["blockers"]
    assert "cap_guard_missing" in admission["blockers"]
    assert payload["guard"]["admission_decision"] == admission
    assert payload["audit_id"]
    assert response.headers["x-correlation-id"] == "corr-001"


@pytest.mark.regression
def test_admin_api_approval_snapshot_resolution_is_evidence_only(monkeypatch):
    client = _client(monkeypatch)
    now = datetime.now(timezone.utc)
    client_order_id = "client-approved"
    idempotency_key = "idem-approved"
    approval = _append_manual_order_approval(
        store=client.admin_api_test_approval_store,
        now=now,
        client_order_id=client_order_id,
        idempotency_key=idempotency_key,
    )

    response = client.post(
        "/api/v1/orders",
        headers=_headers(idempotency_key=idempotency_key),
        json=_manual_order_payload(client_order_id=client_order_id),
    )

    assert response.status_code == 501
    payload = response.json()
    admission = payload["admission_decision"]
    assert payload["live_exchange_submitted"] is False
    assert payload["client_order_id"] == client_order_id
    assert payload["failure_stage"] == "approval"
    assert admission["allowed"] is False
    assert admission["identity_key"] == "client_order_id"
    assert admission["identity_value"] == client_order_id
    assert admission["approval_snapshot_present"] is True
    assert admission["approval_snapshot_id"] == approval.approval_id
    assert admission["approval_snapshot_source"] == "approval_store"
    assert admission["approval_snapshot_approved_by_actor_id"] == "approver-001"
    assert admission["approval_snapshot_requested_by_actor_id"] == "operator-001"
    assert admission["approval_snapshot_expires_at"] == approval.expires_at.isoformat()
    assert admission["approval_snapshot_missing_reason"] is None
    assert admission["admission_audit_present"] is False
    assert admission["admission_audit_id"] is None
    assert admission["admission_audit_source"] == "missing"
    assert admission["admission_audit_recorded_at"] is None
    assert admission["admission_audit_missing_reason"] == "no_matching_admission_audit"
    assert admission["cap_guard_present"] is False
    assert admission["cap_guard_decision_id"] is None
    assert admission["cap_guard_source"] == "missing"
    assert admission["cap_guard_recorded_at"] is None
    assert admission["cap_guard_missing_reason"] == "admission_audit_missing"
    assert admission["reconciliation_plan_present"] is False
    assert admission["reconciliation_plan_id"] is None
    assert admission["reconciliation_plan_source"] == "missing"
    assert admission["reconciliation_plan_recorded_at"] is None
    assert admission["reconciliation_plan_missing_reason"] == "admission_audit_missing"
    assert "approval_snapshot_missing" not in admission["blockers"]
    assert "live_execution_disabled" in admission["blockers"]
    assert "admission_audit_missing" in admission["blockers"]
    assert "cap_guard_missing" in admission["blockers"]
    assert "reconciliation_plan_missing" in admission["blockers"]
    assert "browser_authority_rejected" in admission["blockers"]
    assert payload["guard"]["admission_decision"] == admission
    assert payload["audit_id"]


@pytest.mark.regression
def test_admin_api_admission_audit_resolution_is_evidence_only(monkeypatch):
    client = _client(monkeypatch)
    now = datetime.now(timezone.utc)
    client_order_id = "client-audit-approved"
    idempotency_key = "idem-audit-approved"
    approval = _append_manual_order_approval(
        store=client.admin_api_test_approval_store,
        now=now,
        client_order_id=client_order_id,
        idempotency_key=idempotency_key,
    )
    audit_event = _append_manual_order_admission_audit(
        store=client.admin_api_test_audit_store,
        approval=approval,
        client_order_id=client_order_id,
        idempotency_key=idempotency_key,
    )

    response = client.post(
        "/api/v1/orders",
        headers=_headers(idempotency_key=idempotency_key),
        json=_manual_order_payload(client_order_id=client_order_id),
    )

    assert response.status_code == 501
    payload = response.json()
    admission = payload["admission_decision"]
    assert payload["live_exchange_submitted"] is False
    assert payload["client_order_id"] == client_order_id
    assert payload["failure_stage"] == "approval"
    assert admission["allowed"] is False
    assert admission["approval_snapshot_present"] is True
    assert admission["approval_snapshot_id"] == approval.approval_id
    assert admission["admission_audit_present"] is True
    assert admission["admission_audit_id"] == audit_event.audit_id
    assert admission["admission_audit_source"] == "admin_api_audit_log"
    assert admission["admission_audit_recorded_at"] == audit_event.recorded_at
    assert admission["admission_audit_missing_reason"] is None
    assert admission["cap_guard_present"] is False
    assert admission["cap_guard_decision_id"] is None
    assert admission["cap_guard_source"] == "missing"
    assert admission["cap_guard_recorded_at"] is None
    assert admission["cap_guard_missing_reason"] == "no_matching_cap_guard_decision"
    assert admission["reconciliation_plan_present"] is False
    assert admission["reconciliation_plan_id"] is None
    assert admission["reconciliation_plan_source"] == "missing"
    assert admission["reconciliation_plan_recorded_at"] is None
    assert admission["reconciliation_plan_missing_reason"] == "cap_guard_missing"
    assert "approval_snapshot_missing" not in admission["blockers"]
    assert "admission_audit_missing" not in admission["blockers"]
    assert "live_execution_disabled" in admission["blockers"]
    assert "cap_guard_missing" in admission["blockers"]
    assert "reconciliation_plan_missing" in admission["blockers"]
    assert "browser_authority_rejected" in admission["blockers"]
    assert payload["guard"]["admission_decision"] == admission
    assert payload["audit_id"]

    audit_rows = [
        json.loads(line)
        for line in (client.admin_api_test_store_dir / "audit.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert audit_rows[-1]["approval_id"] == approval.approval_id
    assert audit_rows[-1]["admission_decision"]["admission_audit_id"] == (
        audit_event.audit_id
    )


@pytest.mark.regression
def test_admin_api_cap_guard_resolution_is_evidence_only(monkeypatch):
    client = _client(monkeypatch)
    now = datetime.now(timezone.utc)
    client_order_id = "client-cap-guard-approved"
    idempotency_key = "idem-cap-guard-approved"
    approval = _append_manual_order_approval(
        store=client.admin_api_test_approval_store,
        now=now,
        client_order_id=client_order_id,
        idempotency_key=idempotency_key,
    )
    audit_event = _append_manual_order_admission_audit(
        store=client.admin_api_test_audit_store,
        approval=approval,
        client_order_id=client_order_id,
        idempotency_key=idempotency_key,
    )
    cap_guard = _append_manual_order_cap_guard_decision(
        store=client.admin_api_test_cap_guard_store,
        approval=approval,
        audit_event=audit_event,
        client_order_id=client_order_id,
        idempotency_key=idempotency_key,
    )

    response = client.post(
        "/api/v1/orders",
        headers=_headers(idempotency_key=idempotency_key),
        json=_manual_order_payload(client_order_id=client_order_id),
    )

    assert response.status_code == 501
    payload = response.json()
    admission = payload["admission_decision"]
    assert payload["live_exchange_submitted"] is False
    assert payload["client_order_id"] == client_order_id
    assert payload["failure_stage"] == "approval"
    assert admission["allowed"] is False
    assert admission["approval_snapshot_present"] is True
    assert admission["approval_snapshot_id"] == approval.approval_id
    assert admission["admission_audit_present"] is True
    assert admission["admission_audit_id"] == audit_event.audit_id
    assert admission["cap_guard_present"] is True
    assert admission["cap_guard_decision_id"] == cap_guard.decision_id
    assert admission["cap_guard_source"] == "admin_api_cap_guard_log"
    assert admission["cap_guard_recorded_at"] == cap_guard.recorded_at
    assert admission["cap_guard_missing_reason"] is None
    assert admission["reconciliation_plan_present"] is False
    assert admission["reconciliation_plan_id"] is None
    assert admission["reconciliation_plan_source"] == "missing"
    assert admission["reconciliation_plan_recorded_at"] is None
    assert admission["reconciliation_plan_missing_reason"] == (
        "no_matching_reconciliation_plan"
    )
    assert "approval_snapshot_missing" not in admission["blockers"]
    assert "admission_audit_missing" not in admission["blockers"]
    assert "cap_guard_missing" not in admission["blockers"]
    assert "live_execution_disabled" in admission["blockers"]
    assert "reconciliation_plan_missing" in admission["blockers"]
    assert "browser_authority_rejected" in admission["blockers"]
    assert payload["guard"]["admission_decision"] == admission
    assert payload["audit_id"]

    audit_rows = [
        json.loads(line)
        for line in (client.admin_api_test_store_dir / "audit.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert audit_rows[-1]["approval_id"] == approval.approval_id
    assert audit_rows[-1]["admission_decision"]["cap_guard_decision_id"] == (
        cap_guard.decision_id
    )


@pytest.mark.regression
def test_admin_api_reconciliation_plan_resolution_is_evidence_only(monkeypatch):
    client = _client(monkeypatch)
    now = datetime.now(timezone.utc)
    client_order_id = "client-reconciliation-approved"
    idempotency_key = "idem-reconciliation-approved"
    approval = _append_manual_order_approval(
        store=client.admin_api_test_approval_store,
        now=now,
        client_order_id=client_order_id,
        idempotency_key=idempotency_key,
    )
    audit_event = _append_manual_order_admission_audit(
        store=client.admin_api_test_audit_store,
        approval=approval,
        client_order_id=client_order_id,
        idempotency_key=idempotency_key,
    )
    cap_guard = _append_manual_order_cap_guard_decision(
        store=client.admin_api_test_cap_guard_store,
        approval=approval,
        audit_event=audit_event,
        client_order_id=client_order_id,
        idempotency_key=idempotency_key,
    )
    reconciliation_plan = _append_manual_order_reconciliation_plan(
        store=client.admin_api_test_reconciliation_store,
        approval=approval,
        audit_event=audit_event,
        cap_guard=cap_guard,
        client_order_id=client_order_id,
        idempotency_key=idempotency_key,
    )

    response = client.post(
        "/api/v1/orders",
        headers=_headers(idempotency_key=idempotency_key),
        json=_manual_order_payload(client_order_id=client_order_id),
    )

    assert response.status_code == 501
    payload = response.json()
    admission = payload["admission_decision"]
    assert payload["live_exchange_submitted"] is False
    assert payload["client_order_id"] == client_order_id
    assert payload["failure_stage"] == "approval"
    assert admission["allowed"] is False
    assert admission["approval_snapshot_present"] is True
    assert admission["approval_snapshot_id"] == approval.approval_id
    assert admission["admission_audit_present"] is True
    assert admission["admission_audit_id"] == audit_event.audit_id
    assert admission["cap_guard_present"] is True
    assert admission["cap_guard_decision_id"] == cap_guard.decision_id
    assert admission["reconciliation_plan_present"] is True
    assert admission["reconciliation_plan_id"] == reconciliation_plan.plan_id
    assert admission["reconciliation_plan_source"] == (
        "admin_api_reconciliation_plan_log"
    )
    assert admission["reconciliation_plan_recorded_at"] == (
        reconciliation_plan.recorded_at
    )
    assert admission["reconciliation_plan_missing_reason"] is None
    assert admission["live_execution_service_required"] is True
    assert admission["live_execution_service_present"] is True
    assert admission["live_execution_service_status"] == "live_disabled"
    assert admission["live_execution_service_source"] == "disabled_backend_service"
    assert admission["live_execution_service_missing_reason"] == (
        "live_execution_disabled"
    )
    assert "approval_snapshot_missing" not in admission["blockers"]
    assert "admission_audit_missing" not in admission["blockers"]
    assert "cap_guard_missing" not in admission["blockers"]
    assert "reconciliation_plan_missing" not in admission["blockers"]
    assert "live_execution_disabled" in admission["blockers"]
    assert "browser_authority_rejected" in admission["blockers"]
    assert payload["guard"]["admission_decision"] == admission
    assert payload["audit_id"]

    audit_rows = [
        json.loads(line)
        for line in (client.admin_api_test_store_dir / "audit.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert audit_rows[-1]["approval_id"] == approval.approval_id
    assert audit_rows[-1]["admission_decision"]["reconciliation_plan_id"] == (
        reconciliation_plan.plan_id
    )


@pytest.mark.regression
def test_admin_api_cancel_contract_is_keyed_by_client_order_id(monkeypatch):
    client = _client(monkeypatch)

    response = client.post(
        "/api/v1/orders/client-abc/cancel",
        headers=_headers(),
        json={"reason": "operator_request"},
    )

    assert response.status_code == 501
    payload = response.json()
    assert payload["status"] == AdminApiCommandStatus.NOT_IMPLEMENTED.value
    assert payload["action_class"] == AdminApiActionClass.LIVE_EXCHANGE_CANCEL.value
    assert payload["required_permission"] == AdminApiPermission.ORDER_CANCEL.value
    assert payload["service_method"] == "cancel_order_by_client_order_id"
    assert payload["client_order_id"] == "client-abc"
    assert payload["live_exchange_submitted"] is False
    assert payload["failure_stage"] == "approval"
    assert payload["guard"]["approval_snapshot_required"] is True
    assert payload["guard"]["cap_evaluation_required"] is True
    assert payload["admission_decision"]["route"] == (
        "/api/v1/orders/{client_order_id}/cancel"
    )
    assert payload["admission_decision"]["identity_key"] == "client_order_id"
    assert payload["admission_decision"]["identity_value"] == "client-abc"
    assert payload["admission_decision"]["approval_snapshot_present"] is False
    assert payload["admission_decision"]["approval_snapshot_missing_reason"] == (
        "no_matching_unexpired_snapshot"
    )
    assert payload["admission_decision"]["service_method"] == (
        "cancel_order_by_client_order_id"
    )


@pytest.mark.regression
def test_admin_api_stealth_create_contract_is_fail_closed_and_no_live(monkeypatch):
    client = _client(monkeypatch)

    response = client.post(
        "/api/v1/stealth/orders",
        headers=_headers(idempotency_key="idem-stealth-create"),
        json={
            "stealth_order_id": "stealth-create-abc",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "total_size": "0.001",
            "limit_price": "50000",
            "reveal_condition": {"type": "time_delay", "delay_seconds": 60},
            "sizing_strategy": {"type": "fixed"},
            "target_movement": "0.002",
            "target_movement_type": "P",
            "manual_live_acknowledgement": True,
        },
    )

    assert response.status_code == 501
    payload = response.json()
    assert payload["status"] == AdminApiCommandStatus.NOT_IMPLEMENTED.value
    assert payload["action_class"] == AdminApiActionClass.LOCAL_STATE_MUTATION.value
    assert payload["required_permission"] == AdminApiPermission.ORDER_CREATE.value
    assert payload["service_method"] == "create_stealth_order"
    assert payload["client_order_id"] is None
    assert payload["stealth_order_id"] == "stealth-create-abc"
    assert payload["coinbase_order_id"] is None
    assert payload["live_exchange_submitted"] is False
    assert payload["failure_stage"] == "approval"
    assert payload["guard"]["approval_snapshot_required"] is True
    assert payload["guard"]["cap_evaluation_required"] is True
    assert payload["admission_decision"]["route"] == "/api/v1/stealth/orders"
    assert payload["admission_decision"]["module_id"] == "stealth_orders"
    assert payload["admission_decision"]["identity_key"] == "stealth_order_id"
    assert payload["admission_decision"]["identity_value"] == "stealth-create-abc"
    assert payload["admission_decision"]["action_class"] == (
        AdminApiActionClass.LOCAL_STATE_MUTATION.value
    )
    assert payload["data"]["identity_key"] == "stealth_order_id"
    assert payload["data"]["product_id"] == "BTC-USDC"
    assert payload["data"]["side"] == "BUY"
    assert payload["data"]["stealth_manager_invoked"] is False
    assert payload["data"]["local_state_mutated"] is False
    assert payload["data"]["coinbase_order_submitted"] is False
    assert payload["data"]["exchange_order_id_evidence_only"] is True


@pytest.mark.regression
def test_admin_api_stealth_reveal_contract_is_fail_closed_and_no_live(monkeypatch):
    client = _client(monkeypatch)

    response = client.post(
        "/api/v1/stealth/orders/stealth-reveal-abc/reveal",
        headers=_headers(idempotency_key="idem-stealth-reveal"),
        json={
            "reason": "trigger_window_open",
            "manual_live_acknowledgement": True,
        },
    )

    assert response.status_code == 501
    payload = response.json()
    assert payload["status"] == AdminApiCommandStatus.NOT_IMPLEMENTED.value
    assert payload["action_class"] == AdminApiActionClass.LIVE_EXCHANGE_PLACE.value
    assert payload["required_permission"] == AdminApiPermission.ORDER_CREATE.value
    assert payload["service_method"] == "reveal_stealth_order_by_stealth_order_id"
    assert payload["client_order_id"] is None
    assert payload["stealth_order_id"] == "stealth-reveal-abc"
    assert payload["coinbase_order_id"] is None
    assert payload["live_exchange_submitted"] is False
    assert payload["failure_stage"] == "approval"
    assert payload["guard"]["approval_snapshot_required"] is True
    assert payload["guard"]["cap_evaluation_required"] is True
    assert payload["admission_decision"]["route"] == (
        "/api/v1/stealth/orders/{stealth_order_id}/reveal"
    )
    assert payload["admission_decision"]["module_id"] == "stealth_orders"
    assert payload["admission_decision"]["identity_key"] == "stealth_order_id"
    assert payload["admission_decision"]["identity_value"] == "stealth-reveal-abc"
    assert payload["admission_decision"]["action_class"] == (
        AdminApiActionClass.LIVE_EXCHANGE_PLACE.value
    )
    assert payload["data"]["identity_key"] == "stealth_order_id"
    assert payload["data"]["reason"] == "trigger_window_open"
    assert payload["data"]["manual_live_acknowledgement"] is True
    assert payload["data"]["requires_trigger_evidence"] is True
    assert payload["data"]["active_placement_client_order_id"] is None
    assert payload["data"]["exchange_order_id_evidence_only"] is True
    assert payload["data"]["reveal_order_slice_invoked"] is False
    assert payload["data"]["stealth_manager_invoked"] is False
    assert payload["data"]["local_state_mutated"] is False
    assert payload["data"]["coinbase_order_submitted"] is False


@pytest.mark.regression
def test_admin_api_stealth_move_contract_is_fail_closed_and_no_live(monkeypatch):
    client = _client(monkeypatch)

    response = client.post(
        "/api/v1/stealth/orders/stealth-move-abc/move",
        headers=_headers(idempotency_key="idem-stealth-move"),
        json={
            "new_limit_price": "50100.00",
            "reason": "operator_requested_move",
            "manual_live_acknowledgement": True,
        },
    )

    assert response.status_code == 501
    payload = response.json()
    assert payload["status"] == AdminApiCommandStatus.NOT_IMPLEMENTED.value
    assert payload["action_class"] == AdminApiActionClass.LIVE_EXCHANGE_CANCEL.value
    assert payload["required_permission"] == AdminApiPermission.ORDER_CANCEL.value
    assert payload["service_method"] == "move_stealth_order_by_stealth_order_id"
    assert payload["client_order_id"] is None
    assert payload["stealth_order_id"] == "stealth-move-abc"
    assert payload["coinbase_order_id"] is None
    assert payload["live_exchange_submitted"] is False
    assert payload["failure_stage"] == "approval"
    assert payload["guard"]["approval_snapshot_required"] is True
    assert payload["guard"]["cap_evaluation_required"] is True
    assert payload["admission_decision"]["route"] == (
        "/api/v1/stealth/orders/{stealth_order_id}/move"
    )
    assert payload["admission_decision"]["module_id"] == "stealth_orders"
    assert payload["admission_decision"]["identity_key"] == "stealth_order_id"
    assert payload["admission_decision"]["identity_value"] == "stealth-move-abc"
    assert payload["admission_decision"]["action_class"] == (
        AdminApiActionClass.LIVE_EXCHANGE_CANCEL.value
    )
    assert payload["data"]["identity_key"] == "stealth_order_id"
    assert payload["data"]["new_limit_price"] == "50100.00"
    assert payload["data"]["reason"] == "operator_requested_move"
    assert payload["data"]["manual_live_acknowledgement"] is True
    assert payload["data"]["mutation_kind"] == "move"
    assert payload["data"]["active_placement_client_order_id"] is None
    assert payload["data"]["exchange_order_id_evidence_only"] is True
    assert payload["data"]["build_stealth_move_plan_invoked"] is False
    assert payload["data"]["execute_stealth_move_invoked"] is False
    assert payload["data"]["stealth_manager_invoked"] is False
    assert payload["data"]["cancel_replace_submitted"] is False
    assert payload["data"]["local_state_mutated"] is False
    assert payload["data"]["coinbase_order_submitted"] is False


@pytest.mark.regression
def test_admin_api_stealth_cancel_contract_is_keyed_by_stealth_order_id(monkeypatch):
    client = _client(monkeypatch)

    response = client.post(
        "/api/v1/stealth/orders/stealth-abc/cancel",
        headers=_headers(idempotency_key="idem-stealth-cancel"),
        json={"reason": "operator_request"},
    )

    assert response.status_code == 501
    payload = response.json()
    assert payload["status"] == AdminApiCommandStatus.NOT_IMPLEMENTED.value
    assert payload["action_class"] == AdminApiActionClass.LIVE_EXCHANGE_CANCEL.value
    assert payload["required_permission"] == AdminApiPermission.ORDER_CANCEL.value
    assert payload["service_method"] == "cancel_stealth_order_by_stealth_order_id"
    assert payload["client_order_id"] is None
    assert payload["stealth_order_id"] == "stealth-abc"
    assert payload["coinbase_order_id"] is None
    assert payload["live_exchange_submitted"] is False
    assert payload["failure_stage"] == "approval"
    assert payload["guard"]["approval_snapshot_required"] is True
    assert payload["guard"]["cap_evaluation_required"] is True
    assert payload["admission_decision"]["route"] == (
        "/api/v1/stealth/orders/{stealth_order_id}/cancel"
    )
    assert payload["admission_decision"]["module_id"] == "stealth_orders"
    assert payload["admission_decision"]["identity_key"] == "stealth_order_id"
    assert payload["data"]["identity_key"] == "stealth_order_id"
    assert payload["data"]["active_placement_client_order_id"] is None
    assert payload["data"]["exchange_order_id_evidence_only"] is True


@pytest.mark.regression
def test_admin_api_movement_reprice_contract_is_keyed_by_stealth_order_id(monkeypatch):
    client = _client(monkeypatch)

    response = client.post(
        "/api/v1/movement-repricing/stealth/stealth-abc/reprice",
        headers=_headers(idempotency_key="idem-movement-reprice"),
        json={"reason": "operator_requested_reprice"},
    )

    assert response.status_code == 501
    payload = response.json()
    assert payload["status"] == AdminApiCommandStatus.NOT_IMPLEMENTED.value
    assert payload["action_class"] == AdminApiActionClass.LIVE_EXCHANGE_CANCEL.value
    assert payload["required_permission"] == AdminApiPermission.ORDER_CANCEL.value
    assert payload["service_method"] == "reprice_stealth_order_by_stealth_order_id"
    assert payload["client_order_id"] is None
    assert payload["stealth_order_id"] == "stealth-abc"
    assert payload["coinbase_order_id"] is None
    assert payload["live_exchange_submitted"] is False
    assert payload["failure_stage"] == "approval"
    assert payload["guard"]["approval_snapshot_required"] is True
    assert payload["guard"]["cap_evaluation_required"] is True
    assert payload["admission_decision"]["route"] == (
        "/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice"
    )
    assert payload["admission_decision"]["module_id"] == "movement_repricing"
    assert payload["admission_decision"]["identity_key"] == "stealth_order_id"
    assert payload["data"]["identity_key"] == "stealth_order_id"
    assert payload["data"]["mutation_kind"] == "reprice"
    assert payload["data"]["active_placement_client_order_id"] is None
    assert payload["data"]["exchange_order_id_evidence_only"] is True
    assert payload["data"]["cooldown_cleared"] is False
    assert payload["data"]["stealth_manager_invoked"] is False


@pytest.mark.regression
def test_admin_api_campaign_execution_contract_is_not_implemented_and_not_live(
    monkeypatch,
):
    client = _client(monkeypatch)

    response = client.post(
        "/api/v1/spot/campaign/executions",
        headers=_headers(idempotency_key="idem-campaign"),
        json={
            "campaign_id": "usdc-sweep-001",
            "side": "BUY",
            "quote_notional_per_product": "1.00",
            "product_ids": ["BTC-USDC", "ETH-USDC"],
            "dry_run": False,
            "manual_live_acknowledgement": True,
        },
    )

    assert response.status_code == 501
    payload = response.json()
    assert payload["status"] == AdminApiCommandStatus.NOT_IMPLEMENTED.value
    assert payload["required_permission"] == AdminApiPermission.CAMPAIGN_EXECUTE.value
    assert payload["service_method"] == "execute_spot_campaign"
    assert payload["live_exchange_submitted"] is False
    assert payload["failure_stage"] == "approval"
    assert payload["admission_decision"]["route"] == "/api/v1/spot/campaign/executions"
    assert payload["admission_decision"]["identity_key"] == "campaign_id"
    assert payload["admission_decision"]["required_permission"] == (
        AdminApiPermission.CAMPAIGN_EXECUTE.value
    )
    assert payload["data"]["campaign_id"] == "usdc-sweep-001"
    assert payload["data"]["product_count"] == 2
    assert payload["audit_id"]


@pytest.mark.regression
def test_admin_api_spot_sweep_automation_contract_is_not_implemented_and_not_live(
    monkeypatch,
):
    client = _client(monkeypatch)

    response = client.post(
        "/api/v1/spot/sweep/automation-runs",
        headers=_headers(idempotency_key="idem-sweep-automation"),
        json={
            "sweep_config_id": "spot-sweep-usdc-hourly",
            "side": "BUY",
            "quote_notional_per_product": "1.00",
            "repeat_every_hours": "6",
            "max_runs": 2,
            "max_products": 3,
            "max_total_notional_per_run": "3.00",
            "max_notional_per_order": "1.00",
            "max_planned_orders": 3,
            "run_if_due": True,
            "dry_run": False,
            "manual_live_acknowledgement": True,
        },
    )

    assert response.status_code == 501
    payload = response.json()
    assert payload["status"] == AdminApiCommandStatus.NOT_IMPLEMENTED.value
    assert payload["action_class"] == AdminApiActionClass.LIVE_EXCHANGE_PLACE.value
    assert payload["required_permission"] == AdminApiPermission.SPOT_SWEEP_EXECUTE.value
    assert payload["service_method"] == "run_spot_sweep_automation"
    assert payload["live_exchange_submitted"] is False
    assert payload["failure_stage"] == "approval"
    assert payload["admission_decision"]["route"] == (
        "/api/v1/spot/sweep/automation-runs"
    )
    assert payload["admission_decision"]["identity_key"] == "sweep_config_id"
    assert payload["admission_decision"]["required_permission"] == (
        AdminApiPermission.SPOT_SWEEP_EXECUTE.value
    )
    assert payload["data"]["sweep_config_id"] == "spot-sweep-usdc-hourly"
    assert payload["data"]["sweep_runner_invoked"] is False
    assert payload["audit_id"]


@pytest.mark.regression
def test_admin_api_idempotency_replays_same_response(monkeypatch):
    client = _client(monkeypatch)
    headers = _headers(idempotency_key="idem-replay")

    first = client.post("/api/v1/orders", headers=headers, json=_manual_order_payload())
    second = client.post("/api/v1/orders", headers=headers, json=_manual_order_payload())

    assert first.status_code == 501
    assert second.status_code == 501
    assert second.headers["x-idempotency-replayed"] == "true"
    assert second.json() == first.json()


@pytest.mark.regression
def test_admin_api_idempotency_conflicts_on_payload_drift(monkeypatch):
    client = _client(monkeypatch)
    headers = _headers(idempotency_key="idem-conflict")

    first = client.post("/api/v1/orders", headers=headers, json=_manual_order_payload("1.00"))
    second = client.post("/api/v1/orders", headers=headers, json=_manual_order_payload("2.00"))

    assert first.status_code == 501
    assert second.status_code == 409
    assert second.json()["status"] == AdminApiCommandStatus.CONFLICT.value

    stealth_headers = _headers(idempotency_key="idem-stealth-conflict")
    stealth_first = client.post(
        "/api/v1/stealth/orders/stealth-abc/cancel",
        headers=stealth_headers,
        json={"reason": "operator_request"},
    )
    stealth_second = client.post(
        "/api/v1/stealth/orders/stealth-abc/cancel",
        headers=stealth_headers,
        json={"reason": "operator_request_changed"},
    )

    assert stealth_first.status_code == 501
    assert stealth_second.status_code == 409
    stealth_conflict = stealth_second.json()
    assert stealth_conflict["status"] == AdminApiCommandStatus.CONFLICT.value
    assert stealth_conflict["stealth_order_id"] == "stealth-abc"
    assert stealth_conflict["client_order_id"] is None
    audit_rows = [
        json.loads(line)
        for line in (client.admin_api_test_store_dir / "audit.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert audit_rows[-1]["stealth_order_id"] == "stealth-abc"
    assert audit_rows[-1]["client_order_id"] is None
    assert audit_rows[-1]["operator_intent"] == "manual_one_off"

    movement_headers = _headers(idempotency_key="idem-movement-conflict")
    movement_first = client.post(
        "/api/v1/movement-repricing/stealth/stealth-abc/reprice",
        headers=movement_headers,
        json={"reason": "operator_request"},
    )
    movement_second = client.post(
        "/api/v1/movement-repricing/stealth/stealth-abc/reprice",
        headers=movement_headers,
        json={"reason": "operator_request_changed"},
    )

    assert movement_first.status_code == 501
    assert movement_second.status_code == 409
    movement_conflict = movement_second.json()
    assert movement_conflict["status"] == AdminApiCommandStatus.CONFLICT.value
    assert movement_conflict["stealth_order_id"] == "stealth-abc"
    assert movement_conflict["client_order_id"] is None
    audit_rows = [
        json.loads(line)
        for line in (client.admin_api_test_store_dir / "audit.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert audit_rows[-1]["stealth_order_id"] == "stealth-abc"
    assert audit_rows[-1]["client_order_id"] is None
    assert audit_rows[-1]["operator_intent"] == "manual_one_off"


@pytest.mark.regression
def test_admin_api_idempotency_conflicts_on_operator_intent_drift(monkeypatch):
    client = _client(monkeypatch)
    first_headers = _headers(
        idempotency_key="idem-intent-conflict",
        operator_intent="manual_one_off",
    )
    second_headers = _headers(
        idempotency_key="idem-intent-conflict",
        operator_intent="changed_operator_intent",
    )

    first = client.post(
        "/api/v1/movement-repricing/stealth/stealth-abc/reprice",
        headers=first_headers,
        json={"reason": "operator_request"},
    )
    second = client.post(
        "/api/v1/movement-repricing/stealth/stealth-abc/reprice",
        headers=second_headers,
        json={"reason": "operator_request"},
    )

    assert first.status_code == 501
    assert second.status_code == 409
    payload = second.json()
    assert payload["status"] == AdminApiCommandStatus.CONFLICT.value
    assert payload["stealth_order_id"] == "stealth-abc"
    audit_rows = [
        json.loads(line)
        for line in (client.admin_api_test_store_dir / "audit.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert audit_rows[-1]["operator_intent"] == "changed_operator_intent"


@pytest.mark.regression
def test_admin_api_command_audit_is_durable(monkeypatch):
    client = _client(monkeypatch)

    response = client.post(
        "/api/v1/orders/client-abc/cancel",
        headers=_headers(idempotency_key="idem-audit"),
        json={"reason": "operator_request"},
    )

    assert response.status_code == 501
    audit_rows = [
        json.loads(line)
        for line in (client.admin_api_test_store_dir / "audit.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert audit_rows
    assert audit_rows[-1]["actor_id"] == "operator-001"
    assert audit_rows[-1]["client_order_id"] == "client-abc"
    assert audit_rows[-1]["permission"] == AdminApiPermission.ORDER_CANCEL.value
    assert audit_rows[-1]["operator_intent"] == "manual_one_off"
    assert audit_rows[-1]["admission_decision"]["route"] == (
        "/api/v1/orders/{client_order_id}/cancel"
    )
    assert audit_rows[-1]["admission_decision"]["identity_key"] == "client_order_id"
    assert audit_rows[-1]["admission_decision"]["idempotency_key"] == "idem-audit"
    assert audit_rows[-1]["admission_decision"]["operator_intent"] == "manual_one_off"
    assert len(audit_rows[-1]["admission_decision"]["payload_hash"]) == 64
    assert audit_rows[-1]["admission_decision"]["live_exchange_submitted"] is False
    _assert_disabled_live_execution_intent(
        audit_rows[-1]["admission_decision"]["live_execution_intent"],
        route="/api/v1/orders/{client_order_id}/cancel",
        method="POST",
        module_id="spot_operations",
        service_method="cancel_order_by_client_order_id",
        identity_key="client_order_id",
        identity_value="client-abc",
    )
    assert "admission_audit_missing" in audit_rows[-1]["admission_decision"]["blockers"]

    stealth_response = client.post(
        "/api/v1/stealth/orders/stealth-abc/cancel",
        headers=_headers(idempotency_key="idem-stealth-audit"),
        json={"reason": "operator_request"},
    )

    assert stealth_response.status_code == 501
    audit_rows = [
        json.loads(line)
        for line in (client.admin_api_test_store_dir / "audit.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert audit_rows[-1]["endpoint"] == "POST /api/v1/stealth/orders/stealth-abc/cancel"
    assert audit_rows[-1]["stealth_order_id"] == "stealth-abc"
    assert audit_rows[-1]["client_order_id"] is None
    assert audit_rows[-1]["permission"] == AdminApiPermission.ORDER_CANCEL.value
    assert audit_rows[-1]["operator_intent"] == "manual_one_off"
    assert audit_rows[-1]["admission_decision"]["route"] == (
        "/api/v1/stealth/orders/{stealth_order_id}/cancel"
    )
    assert audit_rows[-1]["admission_decision"]["identity_key"] == "stealth_order_id"
    idempotency_rows = [
        json.loads(line)
        for line in (client.admin_api_test_store_dir / "idempotency.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert idempotency_rows[-1]["stealth_order_id"] == "stealth-abc"
    assert idempotency_rows[-1]["client_order_id"] is None

    movement_response = client.post(
        "/api/v1/movement-repricing/stealth/stealth-abc/reprice",
        headers=_headers(idempotency_key="idem-movement-audit"),
        json={"reason": "operator_requested_reprice"},
    )

    assert movement_response.status_code == 501
    audit_rows = [
        json.loads(line)
        for line in (client.admin_api_test_store_dir / "audit.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert audit_rows[-1]["endpoint"] == (
        "POST /api/v1/movement-repricing/stealth/stealth-abc/reprice"
    )
    assert audit_rows[-1]["stealth_order_id"] == "stealth-abc"
    assert audit_rows[-1]["client_order_id"] is None
    assert audit_rows[-1]["permission"] == AdminApiPermission.ORDER_CANCEL.value
    assert audit_rows[-1]["operator_intent"] == "manual_one_off"
    assert audit_rows[-1]["admission_decision"]["route"] == (
        "/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice"
    )
    assert audit_rows[-1]["admission_decision"]["module_id"] == "movement_repricing"
    assert audit_rows[-1]["admission_decision"]["identity_key"] == "stealth_order_id"
    idempotency_rows = [
        json.loads(line)
        for line in (client.admin_api_test_store_dir / "idempotency.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert idempotency_rows[-1]["stealth_order_id"] == "stealth-abc"
    assert idempotency_rows[-1]["client_order_id"] is None


@pytest.mark.regression
def test_admin_api_openapi_cancel_request_does_not_accept_order_id():
    schema = create_app().openapi()
    cancel_body_ref = schema["paths"]["/api/v1/orders/{client_order_id}/cancel"][
        "post"
    ]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    model_name = cancel_body_ref.rsplit("/", 1)[-1]
    cancel_schema = schema["components"]["schemas"][model_name]

    assert "client_order_id" not in cancel_schema.get("properties", {})
    assert "order_id" not in cancel_schema.get("properties", {})
    assert "client_order_id" in str(
        schema["paths"]["/api/v1/orders/{client_order_id}/cancel"]["post"]["parameters"]
    )

    stealth_create_body_ref = schema["paths"]["/api/v1/stealth/orders"]["post"][
        "requestBody"
    ]["content"]["application/json"]["schema"]["$ref"]
    stealth_create_model_name = stealth_create_body_ref.rsplit("/", 1)[-1]
    stealth_create_schema = schema["components"]["schemas"][stealth_create_model_name]
    assert "stealth_order_id" in stealth_create_schema.get("properties", {})
    assert "client_order_id" not in stealth_create_schema.get("properties", {})
    assert "order_id" not in stealth_create_schema.get("properties", {})
    assert "reveal_condition" in stealth_create_schema.get("required", [])

    stealth_cancel_body_ref = schema["paths"][
        "/api/v1/stealth/orders/{stealth_order_id}/cancel"
    ]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    stealth_model_name = stealth_cancel_body_ref.rsplit("/", 1)[-1]
    stealth_cancel_schema = schema["components"]["schemas"][stealth_model_name]
    assert "stealth_order_id" not in stealth_cancel_schema.get("properties", {})
    assert "client_order_id" not in stealth_cancel_schema.get("properties", {})
    assert "order_id" not in stealth_cancel_schema.get("properties", {})
    assert "stealth_order_id" in str(
        schema["paths"]["/api/v1/stealth/orders/{stealth_order_id}/cancel"]["post"]["parameters"]
    )

    movement_reprice_body_ref = schema["paths"][
        "/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice"
    ]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    movement_reprice_model_name = movement_reprice_body_ref.rsplit("/", 1)[-1]
    movement_reprice_schema = schema["components"]["schemas"][
        movement_reprice_model_name
    ]
    assert "stealth_order_id" not in movement_reprice_schema.get("properties", {})
    assert "client_order_id" not in movement_reprice_schema.get("properties", {})
    assert "order_id" not in movement_reprice_schema.get("properties", {})
    assert "stealth_order_id" in str(
        schema["paths"][
            "/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice"
        ]["post"]["parameters"]
    )


@pytest.mark.regression
def test_admin_api_openapi_recovery_execution_legacy_flags_are_described():
    schema = create_app().openapi()
    schemas = schema["components"]["schemas"]
    execution_properties = schemas["SpotRecoveryExecutionRecordItem"]["properties"]
    proof_properties = schemas["SpotRecoveryProofRecordItem"]["properties"]

    assert "journal acceptance only" in execution_properties[
        "recovery_apply_executed"
    ]["description"]
    assert "does not mean state repair executed" in execution_properties[
        "recovery_apply_executed"
    ]["description"]
    assert "prefer execution_journal_accepted" in execution_properties[
        "recovery_apply_executed"
    ]["description"]
    assert "does not mean rollback mutated order or exchange state" in (
        execution_properties["rollback_executed"]["description"]
    )
    assert "guarded local repair-result contract was accepted" in (
        execution_properties["state_repair_executed"]["description"]
    )
    assert "journal/proof acceptance only" in proof_properties[
        "recovery_apply_executed"
    ]["description"]
    assert "rollback journal/proof acceptance only" in proof_properties[
        "rollback_executed"
    ]["description"]


@pytest.mark.regression
def test_admin_api_examples_keep_operator_intent_in_headers():
    doc = (ROOT / "docs" / "examples" / "admin-api.md").read_text(encoding="utf-8")
    assert "X-Operator-Intent: manual_one_off" in doc
    command_examples = doc.split("## Approval Lifecycle", maxsplit=1)[0]
    approval_lifecycle_examples = doc.split("## Approval Lifecycle", maxsplit=1)[1]
    assert '"operator_intent":' not in command_examples
    assert '"operator_intent":' in approval_lifecycle_examples


@pytest.mark.regression
def test_admin_api_idempotency_contract_replays_same_hash_and_conflicts_on_drift():
    payload_hash = make_payload_hash({"product_id": "BTC-USDC", "quote_size": "1.00"})
    record = IdempotencyRecord(
        idempotency_key="idem-001",
        payload_hash=payload_hash,
        client_order_id="client-001",
        status=AdminApiCommandStatus.NOT_IMPLEMENTED,
        response={"status": "not_implemented"},
    )

    assert evaluate_idempotency(
        existing=None,
        idempotency_key="idem-001",
        payload_hash=payload_hash,
    ).decision == AdminApiIdempotencyDecision.NEW
    assert evaluate_idempotency(
        existing=record,
        idempotency_key="idem-001",
        payload_hash=payload_hash,
    ).decision == AdminApiIdempotencyDecision.REPLAY
    assert evaluate_idempotency(
        existing=record,
        idempotency_key="idem-001",
        payload_hash=make_payload_hash({"product_id": "BTC-USDC", "quote_size": "2.00"}),
    ).decision == AdminApiIdempotencyDecision.CONFLICT


@pytest.mark.regression
def test_admin_api_approval_store_is_append_only_expiring_and_payload_bound():
    store = FileAdminApiApprovalStore(_store_dir() / "approvals.jsonl")
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    record = AdminApiApprovalRecord(
        expires_at=now + timedelta(minutes=5),
        approved_by_actor_id="approver-001",
        requested_by_actor_id="operator-001",
        route="/api/v1/orders",
        method="POST",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value="client-001",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.ORDER_CREATE,
        operator_intent="manual_one_off",
        idempotency_key="idem-approval",
        payload_hash="a" * 64,
        cap_guard_decision_ref="cap-guard-001",
        reconciliation_plan_ref="reconciliation-001",
        approval_reason="bounded canary approval",
    )

    approval_id = store.append(record)

    rows = store.read_recent()
    assert len(rows) == 1
    assert rows[0].approval_id == approval_id
    assert rows[0].payload_hash == "a" * 64
    assert rows[0].required_permission == AdminApiPermission.ORDER_CREATE

    match = store.find_matching(
        route="/api/v1/orders",
        method="POST",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value="client-001",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.ORDER_CREATE,
        requested_by_actor_id="operator-001",
        operator_intent="manual_one_off",
        idempotency_key="idem-approval",
        payload_hash="a" * 64,
        now=now,
    )
    assert match is not None
    assert match.approval_id == approval_id

    assert store.find_matching(
        route="/api/v1/orders",
        method="POST",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value="client-001",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.ORDER_CREATE,
        requested_by_actor_id="operator-001",
        operator_intent="manual_one_off",
        idempotency_key="idem-approval",
        payload_hash="b" * 64,
        now=now,
    ) is None
    assert store.find_matching(
        route="/api/v1/orders",
        method="POST",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value="client-001",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        required_permission=AdminApiPermission.ORDER_CREATE,
        requested_by_actor_id="operator-001",
        operator_intent="manual_one_off",
        idempotency_key="idem-approval",
        payload_hash="a" * 64,
        now=now,
    ) is None
    assert store.find_matching(
        route="/api/v1/orders",
        method="POST",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value="client-001",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.ORDER_CANCEL,
        requested_by_actor_id="operator-001",
        operator_intent="manual_one_off",
        idempotency_key="idem-approval",
        payload_hash="a" * 64,
        now=now,
    ) is None
    assert store.find_matching(
        route="/api/v1/orders",
        method="POST",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value="client-001",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.ORDER_CREATE,
        requested_by_actor_id="operator-002",
        operator_intent="manual_one_off",
        idempotency_key="idem-approval",
        payload_hash="a" * 64,
        now=now,
    ) is None
    assert store.find_matching(
        route="/api/v1/orders",
        method="POST",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value="client-001",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.ORDER_CREATE,
        requested_by_actor_id="operator-001",
        operator_intent="manual_one_off",
        idempotency_key="idem-approval",
        payload_hash="a" * 64,
        now=now + timedelta(minutes=10),
    ) is None

    legacy_store = FileAdminApiApprovalStore(_store_dir() / "legacy_approvals.jsonl")
    legacy_payload = json.loads(record.model_dump_json())
    legacy_payload.pop("requested_by_actor_id")
    legacy_store.path.parent.mkdir(parents=True, exist_ok=True)
    legacy_store.path.write_text(json.dumps(legacy_payload) + "\n", encoding="utf-8")
    assert legacy_store.read_recent() == []
    assert (
        legacy_store.find_matching(
            route="/api/v1/orders",
            method="POST",
            module_id="spot_operations",
            identity_key="client_order_id",
            identity_value="client-001",
            action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            required_permission=AdminApiPermission.ORDER_CREATE,
            requested_by_actor_id="operator-001",
            operator_intent="manual_one_off",
            idempotency_key="idem-approval",
            payload_hash="a" * 64,
            now=now,
        )
        is None
    )


@pytest.mark.regression
def test_admin_api_approval_lifecycle_routes_create_approve_replay_and_conflict(monkeypatch):
    client = _client(monkeypatch)
    request_headers = _headers(
        idempotency_key="approval-request-idem",
        operator_intent="request_manual_order_approval",
        roles=AdminApiRole.TRADER.value,
    )
    request_body = _approval_request_payload()

    created = client.post(
        "/api/v1/admin/approvals/requests",
        headers=request_headers,
        json=request_body,
    )

    assert created.status_code == 200
    created_payload = created.json()
    assert created_payload["status"] == "accepted"
    assert created_payload["required_permission"] == "approval:request"
    assert created_payload["service_method"] == "create_approval_request"
    assert created_payload["live_exchange_submitted"] is False
    assert created_payload["live_coinbase_orders_ran"] is False
    approval_request = created_payload["approval"]
    assert approval_request["status"] == "requested"
    assert approval_request["approval_id"] is None
    assert approval_request["requested_by_actor_id"] == "operator-001"
    assert approval_request["identity_key"] == "client_order_id"
    assert approval_request["identity_value"] == "client-approved"
    assert approval_request["command_idempotency_key"] == "idem-approved"
    assert approval_request["snapshot_linked"] is False
    assert approval_request["live_execution_authority"] is False
    assert approval_request["browser_authority"] == "display_only"

    approval_request_id = approval_request["approval_request_id"]
    listed = client.get(
        "/api/v1/admin/approvals",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    assert listed.status_code == 200
    list_payload = listed.json()
    assert list_payload["pending_count"] == 1
    assert list_payload["approved_count"] == 0
    assert list_payload["live_coinbase_orders_ran"] is False
    assert list_payload["approvals"][0]["approval_request_id"] == approval_request_id

    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    decision_headers = _headers(
        idempotency_key="approval-decision-idem",
        operator_intent="approve_manual_order_snapshot",
        roles=AdminApiRole.ADMIN.value,
    )
    decision_body = {
        "decision": AdminApiApprovalLifecycleStatus.APPROVED.value,
        "decision_reason": "bounded canary approval",
        "expires_at": expires_at,
        "cap_guard_decision_ref": "cap-guard-approval-001",
        "reconciliation_plan_ref": "reconciliation-approval-001",
    }

    decided = client.post(
        f"/api/v1/admin/approvals/requests/{approval_request_id}/decisions",
        headers=decision_headers,
        json=decision_body,
    )

    assert decided.status_code == 200
    decision_payload = decided.json()
    assert decision_payload["required_permission"] == "approval:manage"
    approved = decision_payload["approval"]
    assert approved["status"] == "approved"
    assert approved["approval_id"]
    assert approved["decision_actor_id"] == "operator-001"
    assert approved["snapshot_linked"] is True
    assert approved["live_execution_authority"] is False

    snapshot = resolve_approval_snapshot(
        store=client.admin_api_test_approval_store,
        request=ApprovalSnapshotRequest(
            route="/api/v1/orders",
            method="POST",
            module_id="spot_operations",
            identity_key="client_order_id",
            identity_value="client-approved",
            action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            required_permission=AdminApiPermission.ORDER_CREATE,
            requested_by_actor_id="operator-001",
            operator_intent="manual_one_off",
            idempotency_key="idem-approved",
            payload_hash=request_body["payload_hash"],
        ),
        now=datetime.now(timezone.utc),
    )
    assert snapshot is not None
    assert snapshot.approval_id == approved["approval_id"]

    replayed = client.post(
        f"/api/v1/admin/approvals/requests/{approval_request_id}/decisions",
        headers=decision_headers,
        json=decision_body,
    )
    assert replayed.status_code == 200
    assert replayed.headers["X-Idempotency-Replayed"] == "true"
    assert replayed.json()["approval"]["approval_id"] == approved["approval_id"]

    conflict_body = dict(decision_body)
    conflict_body["decision_reason"] = "changed reason"
    conflict = client.post(
        f"/api/v1/admin/approvals/requests/{approval_request_id}/decisions",
        headers=decision_headers,
        json=conflict_body,
    )
    assert conflict.status_code == 409
    assert conflict.json()["status"] == "conflict"

    audit_rows = client.admin_api_test_audit_store.read_recent(limit=20)
    assert any(row.permission == AdminApiPermission.APPROVAL_REQUEST for row in audit_rows)
    assert any(row.permission == AdminApiPermission.APPROVAL_MANAGE for row in audit_rows)


@pytest.mark.regression
def test_admin_api_approval_lifecycle_revoke_blocks_snapshot_resolution(monkeypatch):
    client = _client(monkeypatch)
    request_body = _approval_request_payload(client_order_id="client-revoke")
    created = client.post(
        "/api/v1/admin/approvals/requests",
        headers=_headers(
            idempotency_key="approval-request-revoke-idem",
            operator_intent="request_revoke_fixture",
            roles=AdminApiRole.TRADER.value,
        ),
        json=request_body,
    )
    approval_request_id = created.json()["approval"]["approval_request_id"]
    decision = client.post(
        f"/api/v1/admin/approvals/requests/{approval_request_id}/decisions",
        headers=_headers(
            idempotency_key="approval-decision-revoke-idem",
            operator_intent="approve_revoke_fixture",
            roles=AdminApiRole.ADMIN.value,
        ),
        json={
            "decision": AdminApiApprovalLifecycleStatus.APPROVED.value,
            "decision_reason": "temporary approval",
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            "cap_guard_decision_ref": "cap-guard-revoke-001",
            "reconciliation_plan_ref": "reconciliation-revoke-001",
        },
    )
    approval_id = decision.json()["approval"]["approval_id"]

    revoked = client.post(
        f"/api/v1/admin/approvals/{approval_id}/revoke",
        headers=_headers(
            idempotency_key="approval-revoke-idem",
            operator_intent="revoke_snapshot",
            roles=AdminApiRole.ADMIN.value,
        ),
        json={"revoke_reason": "operator cancelled the approval"},
    )

    assert revoked.status_code == 200
    revoked_approval = revoked.json()["approval"]
    assert revoked_approval["status"] == "revoked"
    assert revoked_approval["approval_id"] == approval_id
    assert revoked_approval["snapshot_linked"] is False
    assert revoked_approval["revoked_by_actor_id"] == "operator-001"
    assert client.admin_api_test_approval_store.approval_is_revoked(approval_id) is True
    assert (
        resolve_approval_snapshot(
            store=client.admin_api_test_approval_store,
            request=ApprovalSnapshotRequest(
                route="/api/v1/orders",
                method="POST",
                module_id="spot_operations",
                identity_key="client_order_id",
                identity_value="client-revoke",
                action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
                required_permission=AdminApiPermission.ORDER_CREATE,
                requested_by_actor_id="operator-001",
                operator_intent="manual_one_off",
                idempotency_key="idem-approved",
                payload_hash=request_body["payload_hash"],
            ),
            now=datetime.now(timezone.utc),
        )
        is None
    )

    revoked_list = client.get(
        "/api/v1/admin/approvals?lifecycle_status=revoked",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    assert revoked_list.status_code == 200
    assert revoked_list.json()["returned_count"] == 1
    assert revoked_list.json()["revoked_count"] == 1


@pytest.mark.regression
def test_admin_api_approval_lifecycle_rbac_and_expiry_are_fail_closed(monkeypatch):
    client = _client(monkeypatch)
    created = client.post(
        "/api/v1/admin/approvals/requests",
        headers=_headers(
            idempotency_key="approval-request-rbac-idem",
            operator_intent="request_rbac_fixture",
            roles=AdminApiRole.TRADER.value,
        ),
        json=_approval_request_payload(client_order_id="client-rbac"),
    )
    approval_request_id = created.json()["approval"]["approval_request_id"]

    denied = client.post(
        f"/api/v1/admin/approvals/requests/{approval_request_id}/decisions",
        headers=_headers(
            idempotency_key="approval-decision-denied-idem",
            operator_intent="unauthorized_approval_decision",
            roles=AdminApiRole.TRADER.value,
        ),
        json={
            "decision": AdminApiApprovalLifecycleStatus.APPROVED.value,
            "decision_reason": "should fail",
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            "cap_guard_decision_ref": "cap-guard-denied",
            "reconciliation_plan_ref": "reconciliation-denied",
        },
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "permission_denied"

    service = AdminApiApprovalLifecycleService()
    store = FileAdminApiApprovalStore(_store_dir() / "expired_approval.jsonl")
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    request_item = service.create_request(
        store=store,
        body=AdminApprovalRequestCreateRequest.model_validate(
            _approval_request_payload(client_order_id="client-expired")
        ),
        actor_id="operator-001",
        now=now,
    )
    store.append(
        AdminApiApprovalRecord(
            created_at=now,
            expires_at=now + timedelta(minutes=1),
            approved_by_actor_id="approver-001",
            requested_by_actor_id="operator-001",
            route="/api/v1/orders",
            method="POST",
            module_id="spot_operations",
            identity_key="client_order_id",
            identity_value="client-expired",
            action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            required_permission=AdminApiPermission.ORDER_CREATE,
            operator_intent="manual_one_off",
            idempotency_key="idem-approved",
            payload_hash=_approval_request_payload(client_order_id="client-expired")[
                "payload_hash"
            ],
            cap_guard_decision_ref="cap-guard-expired",
            reconciliation_plan_ref="reconciliation-expired",
        )
    )
    store.append_lifecycle_event(
        AdminApiApprovalLifecycleEvent(
            event_type=AdminApiApprovalLifecycleEventType.DECISION_RECORDED,
            recorded_at=now,
            approval_request_id=request_item.approval_request_id,
            approval_id=store.read_recent(limit=1)[0].approval_id,
            status=AdminApiApprovalLifecycleStatus.APPROVED,
            actor_id="approver-001",
            route="/api/v1/orders",
            method="POST",
            module_id="spot_operations",
            identity_key="client_order_id",
            identity_value="client-expired",
            action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            required_permission=AdminApiPermission.ORDER_CREATE,
            requested_by_actor_id="operator-001",
            operator_intent="manual_one_off",
            idempotency_key="idem-approved",
            payload_hash=_approval_request_payload(client_order_id="client-expired")[
                "payload_hash"
            ],
            expires_at=now + timedelta(minutes=1),
            cap_guard_decision_ref="cap-guard-expired",
            reconciliation_plan_ref="reconciliation-expired",
        )
    )

    expired_items = service.list_approvals(
        store=store,
        status_filter=AdminApiApprovalLifecycleStatus.EXPIRED,
        now=now + timedelta(minutes=2),
    )
    assert len(expired_items) == 1
    assert expired_items[0].status == AdminApiApprovalLifecycleStatus.EXPIRED
    assert expired_items[0].snapshot_linked is False
    assert (
        resolve_approval_snapshot(
            store=store,
            request=ApprovalSnapshotRequest(
                route="/api/v1/orders",
                method="POST",
                module_id="spot_operations",
                identity_key="client_order_id",
                identity_value="client-expired",
                action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
                required_permission=AdminApiPermission.ORDER_CREATE,
                requested_by_actor_id="operator-001",
                operator_intent="manual_one_off",
                idempotency_key="idem-approved",
                payload_hash=_approval_request_payload(client_order_id="client-expired")[
                    "payload_hash"
                ],
            ),
            now=now + timedelta(minutes=2),
        )
        is None
    )


@pytest.mark.regression
def test_admin_api_approval_snapshot_resolver_is_exact_and_identity_generic():
    store = FileAdminApiApprovalStore(_store_dir() / "approval_snapshots.jsonl")
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    store.append(
        AdminApiApprovalRecord(
            expires_at=now + timedelta(minutes=5),
            approved_by_actor_id="approver-002",
            requested_by_actor_id="operator-002",
            route="/api/v1/futures/positions/position-001/reduce",
            method="POST",
            module_id="futures_perpetuals",
            identity_key="position_id",
            identity_value="position-001",
            action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            required_permission=AdminApiPermission.ORDER_CREATE,
            operator_intent="reduce_position",
            idempotency_key="idem-futures-reduce",
            payload_hash="c" * 64,
            cap_guard_decision_ref="cap-guard-futures-001",
            reconciliation_plan_ref="reconciliation-futures-001",
        )
    )

    request = ApprovalSnapshotRequest(
        route="/api/v1/futures/positions/position-001/reduce",
        method="POST",
        module_id="futures_perpetuals",
        identity_key="position_id",
        identity_value="position-001",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.ORDER_CREATE,
        requested_by_actor_id="operator-002",
        operator_intent="reduce_position",
        idempotency_key="idem-futures-reduce",
        payload_hash="c" * 64,
    )

    snapshot = resolve_approval_snapshot(store=store, request=request, now=now)

    assert snapshot is not None
    assert snapshot.identity_key == "position_id"
    assert snapshot.identity_value == "position-001"
    assert snapshot.client_order_id is None
    assert snapshot.actor_id == "approver-002"
    assert snapshot.requested_by_actor_id == "operator-002"
    assert snapshot.cap_guard_decision_ref == "cap-guard-futures-001"
    assert snapshot.reconciliation_plan_ref == "reconciliation-futures-001"

    drift_updates = [
        {"route": "/api/v1/futures/positions/position-002/reduce"},
        {"method": "PUT"},
        {"module_id": "spot_operations"},
        {"identity_key": "client_order_id"},
        {"identity_value": "position-002"},
        {"action_class": AdminApiActionClass.LIVE_EXCHANGE_CANCEL},
        {"required_permission": AdminApiPermission.ORDER_CANCEL},
        {"requested_by_actor_id": "operator-003"},
        {"operator_intent": "close_position"},
        {"idempotency_key": "idem-futures-reduce-2"},
        {"payload_hash": "d" * 64},
    ]
    for update in drift_updates:
        assert (
            resolve_approval_snapshot(
                store=store,
                request=request.model_copy(update=update),
                now=now,
            )
            is None
        )
    assert resolve_approval_snapshot(
        store=store,
        request=request,
        now=now + timedelta(minutes=10),
    ) is None


@pytest.mark.regression
def test_admin_api_admission_audit_routes_record_replay_and_resolve(monkeypatch):
    client = _client(monkeypatch)
    approval = _append_manual_order_approval(
        store=client.admin_api_test_approval_store,
        now=datetime.now(timezone.utc),
        client_order_id="client-admission-audit-route",
    )
    body = _admission_audit_payload(
        approval=approval,
        client_order_id="client-admission-audit-route",
    )
    headers = _headers(
        idempotency_key="admission-audit-record-idem",
        operator_intent="record_manual_order_admission_audit",
        roles=AdminApiRole.ADMIN.value,
    )

    created = client.post(
        "/api/v1/admin/admission-audits",
        headers=headers,
        json=body,
    )

    assert created.status_code == 200
    created_payload = created.json()
    assert created_payload["status"] == "accepted"
    assert created_payload["required_permission"] == "admission_audit:record"
    assert created_payload["service_method"] == "record_admission_audit"
    assert created_payload["live_exchange_submitted"] is False
    assert created_payload["live_coinbase_orders_ran"] is False
    admission_audit = created_payload["admission_audit"]
    admission_audit_id = admission_audit["admission_audit_id"]
    assert created_payload["audit_id"] == admission_audit_id
    assert admission_audit["approval_snapshot_id"] == approval.approval_id
    assert (
        admission_audit["approval_cap_guard_decision_ref"]
        == approval.cap_guard_decision_ref
    )
    assert (
        admission_audit["approval_reconciliation_plan_ref"]
        == approval.reconciliation_plan_ref
    )
    assert admission_audit["live_execution_intent_ref"] == (
        "AdminApiCommandService.place_manual_order"
    )
    assert admission_audit["resolver_eligible"] is True
    assert admission_audit["allowed"] is False
    assert admission_audit["status"] == AdminApiGateStatus.BLOCKED.value
    assert admission_audit["admission_decision"]["live_exchange_submitted"] is False
    assert "admission_audit_missing" in admission_audit["admission_decision"]["blockers"]

    listed = client.get(
        "/api/v1/admin/admission-audits",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    assert listed.status_code == 200
    list_payload = listed.json()
    assert list_payload["returned_count"] == 1
    assert list_payload["total_count"] == 1
    assert list_payload["blocked_count"] == 1
    assert list_payload["passed_count"] == 0
    assert list_payload["resolver_eligible_count"] == 1
    assert list_payload["live_coinbase_orders_ran"] is False

    detail = client.get(
        f"/api/v1/admin/admission-audits/{admission_audit_id}",
        headers=_headers(roles=AdminApiRole.AUDITOR.value),
    )
    assert detail.status_code == 200
    assert detail.json()["admission_audit"]["admission_audit_id"] == admission_audit_id

    proof = resolve_admission_audit_trail(
        store=client.admin_api_test_audit_store,
        request=AdmissionAuditTrailRequest(
            route="/api/v1/orders",
            method="POST",
            module_id="spot_operations",
            identity_key="client_order_id",
            identity_value="client-admission-audit-route",
            action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            required_permission=AdminApiPermission.ORDER_CREATE,
            service_method="place_manual_order",
            actor_id="operator-001",
            operator_intent="manual_one_off",
            idempotency_key="idem-approved",
            payload_hash=body["payload_hash"],
            approval_snapshot_id=approval.approval_id,
        ),
    )
    assert proof is not None
    assert proof.audit_id == admission_audit_id
    assert proof.source == "admin_api_audit_log"

    replayed = client.post(
        "/api/v1/admin/admission-audits",
        headers=headers,
        json=body,
    )
    assert replayed.status_code == 200
    assert replayed.headers["X-Idempotency-Replayed"] == "true"
    assert replayed.json()["admission_audit"]["admission_audit_id"] == (
        admission_audit_id
    )

    conflict_body = dict(body)
    conflict_body["reason"] = "changed reason"
    conflict = client.post(
        "/api/v1/admin/admission-audits",
        headers=headers,
        json=conflict_body,
    )
    assert conflict.status_code == 409
    assert conflict.json()["status"] == "conflict"


@pytest.mark.regression
def test_admin_api_admission_audit_routes_fail_closed(monkeypatch):
    client = _client(monkeypatch)
    approval = _append_manual_order_approval(
        store=client.admin_api_test_approval_store,
        now=datetime.now(timezone.utc),
        client_order_id="client-admission-audit-denied",
    )
    body = _admission_audit_payload(
        approval=approval,
        client_order_id="client-admission-audit-denied",
    )

    denied = client.post(
        "/api/v1/admin/admission-audits",
        headers=_headers(
            idempotency_key="admission-audit-record-denied-idem",
            operator_intent="unauthorized_admission_audit_record",
            roles=AdminApiRole.TRADER.value,
        ),
        json=body,
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "permission_denied"

    allowed = dict(body)
    allowed["allowed"] = True
    allowed["status"] = AdminApiGateStatus.PASSED.value
    rejected = client.post(
        "/api/v1/admin/admission-audits",
        headers=_headers(
            idempotency_key="admission-audit-record-allowed-idem",
            operator_intent="record_allowed_admission_audit",
            roles=AdminApiRole.ADMIN.value,
        ),
        json=allowed,
    )
    assert rejected.status_code == 400
    assert rejected.json()["status"] == "rejected"
    assert "cannot mark live admission allowed" in rejected.json()["message"]
    assert client.admin_api_test_audit_store.find_matching_admission_audit(
        request=AdmissionAuditTrailRequest(
            route="/api/v1/orders",
            method="POST",
            module_id="spot_operations",
            identity_key="client_order_id",
            identity_value="client-admission-audit-denied",
            action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            required_permission=AdminApiPermission.ORDER_CREATE,
            service_method="place_manual_order",
            actor_id="operator-001",
            operator_intent="manual_one_off",
            idempotency_key="idem-approved",
            payload_hash=body["payload_hash"],
            approval_snapshot_id=approval.approval_id,
        )
    ) is None

    read_only = dict(body)
    read_only.update({
        "route": "/api/v1/admin/bootstrap",
        "method": "GET",
        "module_id": "admin_system_health",
        "identity_key": "request_id",
        "identity_value": "corr-001",
        "action_class": AdminApiActionClass.READ_ONLY.value,
        "required_permission": AdminApiPermission.ANALYTICS_READ.value,
        "service_method": "build_admin_bootstrap",
    })
    rejected_read_only = client.post(
        "/api/v1/admin/admission-audits",
        headers=_headers(
            idempotency_key="admission-audit-record-read-only-idem",
            operator_intent="record_read_only_admission_audit",
            roles=AdminApiRole.ADMIN.value,
        ),
        json=read_only,
    )
    assert rejected_read_only.status_code == 400
    assert rejected_read_only.json()["status"] == "rejected"
    assert "only valid for live-shaped command routes" in (
        rejected_read_only.json()["message"]
    )


@pytest.mark.regression
def test_admin_api_cap_guard_decision_routes_record_replay_and_resolve(monkeypatch):
    client = _client(monkeypatch)
    approval = _append_manual_order_approval(
        store=client.admin_api_test_approval_store,
        now=datetime.now(timezone.utc),
        client_order_id="client-cap-guard-route",
    )
    audit_event = _append_manual_order_admission_audit(
        store=client.admin_api_test_audit_store,
        approval=approval,
        client_order_id="client-cap-guard-route",
    )
    body = _cap_guard_decision_payload(
        approval=approval,
        audit_event=audit_event,
        client_order_id="client-cap-guard-route",
    )
    headers = _headers(
        idempotency_key="cap-guard-record-idem",
        operator_intent="record_manual_order_cap_guard",
        roles=AdminApiRole.ADMIN.value,
    )

    created = client.post(
        "/api/v1/admin/cap-guard/decisions",
        headers=headers,
        json=body,
    )

    assert created.status_code == 200
    created_payload = created.json()
    assert created_payload["status"] == "accepted"
    assert created_payload["required_permission"] == "cap_guard:record"
    assert created_payload["service_method"] == "record_cap_guard_decision"
    assert created_payload["live_exchange_submitted"] is False
    assert created_payload["live_coinbase_orders_ran"] is False
    decision = created_payload["decision"]
    assert decision["decision_id"] == approval.cap_guard_decision_ref
    assert decision["approval_snapshot_id"] == approval.approval_id
    assert decision["admission_audit_id"] == audit_event.audit_id
    assert decision["resolver_eligible"] is True
    assert decision["browser_authority"] == "display_only"
    assert decision["bff_authority"] == "forward_only_no_execution"

    listed = client.get(
        "/api/v1/admin/cap-guard/decisions",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    assert listed.status_code == 200
    list_payload = listed.json()
    assert list_payload["returned_count"] == 1
    assert list_payload["total_count"] == 1
    assert list_payload["passed_count"] == 1
    assert list_payload["blocked_count"] == 0
    assert list_payload["warning_count"] == 0
    assert list_payload["resolver_eligible_count"] == 1
    assert list_payload["live_coinbase_orders_ran"] is False

    detail = client.get(
        f"/api/v1/admin/cap-guard/decisions/{approval.cap_guard_decision_ref}",
        headers=_headers(roles=AdminApiRole.AUDITOR.value),
    )
    assert detail.status_code == 200
    assert detail.json()["decision"]["decision_id"] == approval.cap_guard_decision_ref

    proof = resolve_cap_guard_decision(
        store=client.admin_api_test_cap_guard_store,
        request=CapGuardDecisionRequest(
            route="/api/v1/orders",
            method="POST",
            module_id="spot_operations",
            identity_key="client_order_id",
            identity_value="client-cap-guard-route",
            action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            required_permission=AdminApiPermission.ORDER_CREATE,
            service_method="place_manual_order",
            actor_id="operator-001",
            operator_intent="manual_one_off",
            idempotency_key="idem-approved",
            payload_hash=body["payload_hash"],
            approval_snapshot_id=approval.approval_id,
            approval_cap_guard_decision_ref=approval.cap_guard_decision_ref,
            admission_audit_id=audit_event.audit_id,
        ),
    )
    assert proof is not None
    assert proof.decision_id == approval.cap_guard_decision_ref
    assert proof.source == "admin_api_cap_guard_log"

    replayed = client.post(
        "/api/v1/admin/cap-guard/decisions",
        headers=headers,
        json=body,
    )
    assert replayed.status_code == 200
    assert replayed.headers["X-Idempotency-Replayed"] == "true"
    assert replayed.json()["decision"]["decision_id"] == approval.cap_guard_decision_ref

    conflict_body = dict(body)
    conflict_body["reason"] = "changed reason"
    conflict = client.post(
        "/api/v1/admin/cap-guard/decisions",
        headers=headers,
        json=conflict_body,
    )
    assert conflict.status_code == 409
    assert conflict.json()["status"] == "conflict"

    audit_rows = client.admin_api_test_audit_store.read_recent(limit=20)
    assert any(row.permission == AdminApiPermission.CAP_GUARD_RECORD for row in audit_rows)


@pytest.mark.regression
def test_admin_api_cap_guard_decision_routes_fail_closed(monkeypatch):
    client = _client(monkeypatch)
    approval = _append_manual_order_approval(
        store=client.admin_api_test_approval_store,
        now=datetime.now(timezone.utc),
        client_order_id="client-cap-guard-denied",
    )
    audit_event = _append_manual_order_admission_audit(
        store=client.admin_api_test_audit_store,
        approval=approval,
        client_order_id="client-cap-guard-denied",
    )
    body = _cap_guard_decision_payload(
        approval=approval,
        audit_event=audit_event,
        client_order_id="client-cap-guard-denied",
    )

    denied = client.post(
        "/api/v1/admin/cap-guard/decisions",
        headers=_headers(
            idempotency_key="cap-guard-record-denied-idem",
            operator_intent="unauthorized_cap_guard_record",
            roles=AdminApiRole.TRADER.value,
        ),
        json=body,
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "permission_denied"

    inconsistent = dict(body)
    inconsistent["status"] = AdminApiGateStatus.BLOCKED.value
    rejected = client.post(
        "/api/v1/admin/cap-guard/decisions",
        headers=_headers(
            idempotency_key="cap-guard-record-inconsistent-idem",
            operator_intent="record_inconsistent_cap_guard",
            roles=AdminApiRole.ADMIN.value,
        ),
        json=inconsistent,
    )
    assert rejected.status_code == 400
    assert rejected.json()["status"] == "rejected"
    assert "allowed must be true only for passed" in rejected.json()["message"]
    assert client.admin_api_test_cap_guard_store.read_recent() == []

    blocked = _cap_guard_decision_payload(
        approval=approval,
        audit_event=audit_event,
        client_order_id="client-cap-guard-denied",
        allowed=False,
        status=AdminApiGateStatus.BLOCKED,
    )
    recorded_block = client.post(
        "/api/v1/admin/cap-guard/decisions",
        headers=_headers(
            idempotency_key="cap-guard-record-blocked-idem",
            operator_intent="record_blocked_cap_guard",
            roles=AdminApiRole.ADMIN.value,
        ),
        json=blocked,
    )
    assert recorded_block.status_code == 200
    assert recorded_block.json()["decision"]["resolver_eligible"] is False
    assert (
        resolve_cap_guard_decision(
            store=client.admin_api_test_cap_guard_store,
            request=CapGuardDecisionRequest(
                route="/api/v1/orders",
                method="POST",
                module_id="spot_operations",
                identity_key="client_order_id",
                identity_value="client-cap-guard-denied",
                action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
                required_permission=AdminApiPermission.ORDER_CREATE,
                service_method="place_manual_order",
                actor_id="operator-001",
                operator_intent="manual_one_off",
                idempotency_key="idem-approved",
                payload_hash=blocked["payload_hash"],
                approval_snapshot_id=approval.approval_id,
                approval_cap_guard_decision_ref=approval.cap_guard_decision_ref,
                admission_audit_id=audit_event.audit_id,
            ),
        )
        is None
    )

    mismatch = _cap_guard_decision_payload(
        approval=approval,
        audit_event=audit_event,
        client_order_id="client-cap-guard-other",
    )
    mismatch["module_id"] = "futures_perpetuals"
    rejected_mismatch = client.post(
        "/api/v1/admin/cap-guard/decisions",
        headers=_headers(
            idempotency_key="cap-guard-record-mismatch-idem",
            operator_intent="record_mismatched_cap_guard",
            roles=AdminApiRole.ADMIN.value,
        ),
        json=mismatch,
    )
    assert rejected_mismatch.status_code == 400
    assert rejected_mismatch.json()["status"] == "rejected"
    assert "module_id does not match" in rejected_mismatch.json()["message"]


@pytest.mark.regression
def test_admin_api_reconciliation_plan_routes_record_replay_and_resolve(monkeypatch):
    client = _client(monkeypatch)
    approval = _append_manual_order_approval(
        store=client.admin_api_test_approval_store,
        now=datetime.now(timezone.utc),
        client_order_id="client-reconciliation-route",
    )
    audit_event = _append_manual_order_admission_audit(
        store=client.admin_api_test_audit_store,
        approval=approval,
        client_order_id="client-reconciliation-route",
    )
    cap_guard = _append_manual_order_cap_guard_decision(
        store=client.admin_api_test_cap_guard_store,
        approval=approval,
        audit_event=audit_event,
        client_order_id="client-reconciliation-route",
    )
    body = _reconciliation_plan_payload(
        approval=approval,
        audit_event=audit_event,
        cap_guard=cap_guard,
        client_order_id="client-reconciliation-route",
    )
    headers = _headers(
        idempotency_key="reconciliation-plan-record-idem",
        operator_intent="record_manual_order_reconciliation_plan",
        roles=AdminApiRole.ADMIN.value,
    )

    created = client.post(
        "/api/v1/admin/reconciliation/plans",
        headers=headers,
        json=body,
    )

    assert created.status_code == 200
    created_payload = created.json()
    assert created_payload["status"] == "accepted"
    assert created_payload["required_permission"] == "reconciliation:record"
    assert created_payload["service_method"] == "record_reconciliation_plan"
    assert created_payload["reconciliation_execution_ran"] is False
    assert created_payload["order_exchange_state_mutated"] is False
    assert created_payload["live_exchange_submitted"] is False
    assert created_payload["live_coinbase_orders_ran"] is False
    plan = created_payload["plan"]
    assert plan["plan_id"] == approval.reconciliation_plan_ref
    assert plan["approval_snapshot_id"] == approval.approval_id
    assert plan["admission_audit_id"] == audit_event.audit_id
    assert plan["cap_guard_decision_id"] == cap_guard.decision_id
    assert plan["resolver_eligible"] is True
    assert plan["browser_authority"] == "display_only"
    assert plan["bff_authority"] == "forward_only_no_execution"
    assert plan["reconciliation_execution_ran"] is False
    assert plan["order_exchange_state_mutated"] is False

    listed = client.get(
        "/api/v1/admin/reconciliation/plans",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    assert listed.status_code == 200
    list_payload = listed.json()
    assert list_payload["returned_count"] == 1
    assert list_payload["total_count"] == 1
    assert list_payload["passed_count"] == 1
    assert list_payload["blocked_count"] == 0
    assert list_payload["warning_count"] == 0
    assert list_payload["resolver_eligible_count"] == 1
    assert list_payload["reconciliation_execution_ran"] is False
    assert list_payload["live_coinbase_orders_ran"] is False

    detail = client.get(
        f"/api/v1/admin/reconciliation/plans/{approval.reconciliation_plan_ref}",
        headers=_headers(roles=AdminApiRole.AUDITOR.value),
    )
    assert detail.status_code == 200
    assert detail.json()["plan"]["plan_id"] == approval.reconciliation_plan_ref

    proof = resolve_reconciliation_plan(
        store=client.admin_api_test_reconciliation_store,
        request=ReconciliationPlanRequest(
            route="/api/v1/orders",
            method="POST",
            module_id="spot_operations",
            identity_key="client_order_id",
            identity_value="client-reconciliation-route",
            action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            required_permission=AdminApiPermission.ORDER_CREATE,
            service_method="place_manual_order",
            actor_id="operator-001",
            operator_intent="manual_one_off",
            idempotency_key="idem-approved",
            payload_hash=body["payload_hash"],
            approval_snapshot_id=approval.approval_id,
            approval_reconciliation_plan_ref=approval.reconciliation_plan_ref,
            admission_audit_id=audit_event.audit_id,
            cap_guard_decision_id=cap_guard.decision_id,
        ),
    )
    assert proof is not None
    assert proof.plan_id == approval.reconciliation_plan_ref
    assert proof.source == "admin_api_reconciliation_plan_log"

    replayed = client.post(
        "/api/v1/admin/reconciliation/plans",
        headers=headers,
        json=body,
    )
    assert replayed.status_code == 200
    assert replayed.headers["X-Idempotency-Replayed"] == "true"
    assert replayed.json()["plan"]["plan_id"] == approval.reconciliation_plan_ref

    conflict_body = dict(body)
    conflict_body["reason"] = "changed reason"
    conflict = client.post(
        "/api/v1/admin/reconciliation/plans",
        headers=headers,
        json=conflict_body,
    )
    assert conflict.status_code == 409
    assert conflict.json()["status"] == "conflict"

    audit_rows = client.admin_api_test_audit_store.read_recent(limit=20)
    assert any(
        row.permission == AdminApiPermission.RECONCILIATION_RECORD
        for row in audit_rows
    )


@pytest.mark.regression
def test_admin_api_reconciliation_plan_routes_fail_closed(monkeypatch):
    client = _client(monkeypatch)
    approval = _append_manual_order_approval(
        store=client.admin_api_test_approval_store,
        now=datetime.now(timezone.utc),
        client_order_id="client-reconciliation-denied",
    )
    audit_event = _append_manual_order_admission_audit(
        store=client.admin_api_test_audit_store,
        approval=approval,
        client_order_id="client-reconciliation-denied",
    )
    cap_guard = _append_manual_order_cap_guard_decision(
        store=client.admin_api_test_cap_guard_store,
        approval=approval,
        audit_event=audit_event,
        client_order_id="client-reconciliation-denied",
    )
    body = _reconciliation_plan_payload(
        approval=approval,
        audit_event=audit_event,
        cap_guard=cap_guard,
        client_order_id="client-reconciliation-denied",
    )

    denied = client.post(
        "/api/v1/admin/reconciliation/plans",
        headers=_headers(
            idempotency_key="reconciliation-plan-record-denied-idem",
            operator_intent="unauthorized_reconciliation_plan_record",
            roles=AdminApiRole.TRADER.value,
        ),
        json=body,
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "permission_denied"

    inconsistent = dict(body)
    inconsistent["status"] = AdminApiGateStatus.BLOCKED.value
    rejected = client.post(
        "/api/v1/admin/reconciliation/plans",
        headers=_headers(
            idempotency_key="reconciliation-plan-record-inconsistent-idem",
            operator_intent="record_inconsistent_reconciliation_plan",
            roles=AdminApiRole.ADMIN.value,
        ),
        json=inconsistent,
    )
    assert rejected.status_code == 400
    assert rejected.json()["status"] == "rejected"
    assert "allowed must be true only for passed" in rejected.json()["message"]
    assert client.admin_api_test_reconciliation_store.read_recent() == []

    blocked = _reconciliation_plan_payload(
        approval=approval,
        audit_event=audit_event,
        cap_guard=cap_guard,
        client_order_id="client-reconciliation-denied",
        allowed=False,
        status=AdminApiGateStatus.BLOCKED,
    )
    recorded_block = client.post(
        "/api/v1/admin/reconciliation/plans",
        headers=_headers(
            idempotency_key="reconciliation-plan-record-blocked-idem",
            operator_intent="record_blocked_reconciliation_plan",
            roles=AdminApiRole.ADMIN.value,
        ),
        json=blocked,
    )
    assert recorded_block.status_code == 200
    assert recorded_block.json()["plan"]["resolver_eligible"] is False
    assert (
        resolve_reconciliation_plan(
            store=client.admin_api_test_reconciliation_store,
            request=ReconciliationPlanRequest(
                route="/api/v1/orders",
                method="POST",
                module_id="spot_operations",
                identity_key="client_order_id",
                identity_value="client-reconciliation-denied",
                action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
                required_permission=AdminApiPermission.ORDER_CREATE,
                service_method="place_manual_order",
                actor_id="operator-001",
                operator_intent="manual_one_off",
                idempotency_key="idem-approved",
                payload_hash=blocked["payload_hash"],
                approval_snapshot_id=approval.approval_id,
                approval_reconciliation_plan_ref=approval.reconciliation_plan_ref,
                admission_audit_id=audit_event.audit_id,
                cap_guard_decision_id=cap_guard.decision_id,
            ),
        )
        is None
    )

    mismatch = _reconciliation_plan_payload(
        approval=approval,
        audit_event=audit_event,
        cap_guard=cap_guard,
        client_order_id="client-reconciliation-other",
    )
    mismatch["module_id"] = "futures_perpetuals"
    rejected_mismatch = client.post(
        "/api/v1/admin/reconciliation/plans",
        headers=_headers(
            idempotency_key="reconciliation-plan-record-mismatch-idem",
            operator_intent="record_mismatched_reconciliation_plan",
            roles=AdminApiRole.ADMIN.value,
        ),
        json=mismatch,
    )
    assert rejected_mismatch.status_code == 400
    assert rejected_mismatch.json()["status"] == "rejected"
    assert "module_id does not match" in rejected_mismatch.json()["message"]

    read_only = dict(body)
    read_only.update({
        "route": "/api/v1/admin/bootstrap",
        "method": "GET",
        "module_id": "admin_system_health",
        "identity_key": "request_id",
        "identity_value": "corr-001",
        "action_class": AdminApiActionClass.READ_ONLY.value,
        "required_permission": AdminApiPermission.ANALYTICS_READ.value,
        "service_method": "build_admin_bootstrap",
    })
    rejected_read_only = client.post(
        "/api/v1/admin/reconciliation/plans",
        headers=_headers(
            idempotency_key="reconciliation-plan-record-read-only-idem",
            operator_intent="record_read_only_reconciliation_plan",
            roles=AdminApiRole.ADMIN.value,
        ),
        json=read_only,
    )
    assert rejected_read_only.status_code == 400
    assert rejected_read_only.json()["status"] == "rejected"
    assert "only valid for live-shaped command routes" in (
        rejected_read_only.json()["message"]
    )


@pytest.mark.regression
def test_admin_api_cap_guard_decision_resolver_is_exact_and_identity_generic():
    store = FileAdminApiCapGuardStore(_store_dir() / "cap_guard.jsonl")
    record = CapGuardDecisionRecord(
        decision_id="cap-guard-futures-001",
        route="/api/v1/futures/positions/position-001/reduce",
        method="POST",
        module_id="futures_perpetuals",
        identity_key="position_id",
        identity_value="position-001",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.ORDER_CREATE,
        service_method="reduce_futures_position",
        actor_id="operator-002",
        operator_intent="reduce_position",
        idempotency_key="idem-futures-reduce",
        payload_hash="c" * 64,
        approval_snapshot_id="approval-futures-001",
        admission_audit_id="audit-futures-001",
        allowed=True,
        status=AdminApiGateStatus.PASSED,
        cap_policy_ref="submitted_notional_cap:3.10",
        guard_policy_ref="futures_margin_guard",
        product_scope="futures/perpetual configured product scope",
        max_submitted_notional_usdc="3.10",
        max_executed_notional_usdc="1.00",
        reason="Backend-owned futures cap/guard proof.",
    )
    store.append(record)
    store.append(record.model_copy(update={
        "decision_id": "cap-guard-denied",
        "allowed": False,
        "status": AdminApiGateStatus.BLOCKED,
    }))

    request = CapGuardDecisionRequest(
        route="/api/v1/futures/positions/position-001/reduce",
        method="POST",
        module_id="futures_perpetuals",
        identity_key="position_id",
        identity_value="position-001",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.ORDER_CREATE,
        service_method="reduce_futures_position",
        actor_id="operator-002",
        operator_intent="reduce_position",
        idempotency_key="idem-futures-reduce",
        payload_hash="c" * 64,
        approval_snapshot_id="approval-futures-001",
        approval_cap_guard_decision_ref="cap-guard-futures-001",
        admission_audit_id="audit-futures-001",
    )

    proof = resolve_cap_guard_decision(store=store, request=request)

    assert proof is not None
    assert proof.decision_id == "cap-guard-futures-001"
    assert proof.approval_snapshot_id == "approval-futures-001"
    assert proof.admission_audit_id == "audit-futures-001"
    assert proof.product_scope == "futures/perpetual configured product scope"

    drift_updates = [
        {"route": "/api/v1/futures/positions/position-002/reduce"},
        {"method": "PUT"},
        {"module_id": "spot_operations"},
        {"identity_key": "client_order_id"},
        {"identity_value": "position-002"},
        {"action_class": AdminApiActionClass.LIVE_EXCHANGE_CANCEL},
        {"required_permission": AdminApiPermission.ORDER_CANCEL},
        {"service_method": "close_futures_position"},
        {"actor_id": "operator-003"},
        {"operator_intent": "close_position"},
        {"idempotency_key": "idem-futures-reduce-2"},
        {"payload_hash": "d" * 64},
        {"approval_snapshot_id": "approval-futures-002"},
        {"approval_cap_guard_decision_ref": "cap-guard-denied"},
        {"admission_audit_id": "audit-futures-002"},
    ]
    for update in drift_updates:
        assert (
            resolve_cap_guard_decision(
                store=store,
                request=request.model_copy(update=update),
            )
            is None
        )


@pytest.mark.regression
def test_admin_api_reconciliation_plan_resolver_is_exact_and_identity_generic():
    store = FileAdminApiReconciliationStore(_store_dir() / "reconciliation.jsonl")
    record = ReconciliationPlanRecord(
        plan_id="reconciliation-futures-001",
        route="/api/v1/futures/positions/position-001/reduce",
        method="POST",
        module_id="futures_perpetuals",
        identity_key="position_id",
        identity_value="position-001",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.ORDER_CREATE,
        service_method="reduce_futures_position",
        actor_id="operator-002",
        operator_intent="reduce_position",
        idempotency_key="idem-futures-reduce",
        payload_hash="c" * 64,
        approval_snapshot_id="approval-futures-001",
        admission_audit_id="audit-futures-001",
        cap_guard_decision_id="cap-guard-futures-001",
        allowed=True,
        status=AdminApiGateStatus.PASSED,
        reconciliation_policy_ref="futures_position_reconciliation",
        product_scope="futures/perpetual configured product scope",
        max_submitted_notional_usdc="3.10",
        max_executed_notional_usdc="1.00",
        reason="Backend-owned futures reconciliation plan proof.",
    )
    store.append(record)
    store.append(record.model_copy(update={
        "plan_id": "reconciliation-denied",
        "allowed": False,
        "status": AdminApiGateStatus.BLOCKED,
    }))

    request = ReconciliationPlanRequest(
        route="/api/v1/futures/positions/position-001/reduce",
        method="POST",
        module_id="futures_perpetuals",
        identity_key="position_id",
        identity_value="position-001",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.ORDER_CREATE,
        service_method="reduce_futures_position",
        actor_id="operator-002",
        operator_intent="reduce_position",
        idempotency_key="idem-futures-reduce",
        payload_hash="c" * 64,
        approval_snapshot_id="approval-futures-001",
        approval_reconciliation_plan_ref="reconciliation-futures-001",
        admission_audit_id="audit-futures-001",
        cap_guard_decision_id="cap-guard-futures-001",
    )

    proof = resolve_reconciliation_plan(store=store, request=request)

    assert proof is not None
    assert proof.plan_id == "reconciliation-futures-001"
    assert proof.approval_snapshot_id == "approval-futures-001"
    assert proof.admission_audit_id == "audit-futures-001"
    assert proof.cap_guard_decision_id == "cap-guard-futures-001"
    assert proof.product_scope == "futures/perpetual configured product scope"

    drift_updates = [
        {"route": "/api/v1/futures/positions/position-002/reduce"},
        {"method": "PUT"},
        {"module_id": "spot_operations"},
        {"identity_key": "client_order_id"},
        {"identity_value": "position-002"},
        {"action_class": AdminApiActionClass.LIVE_EXCHANGE_CANCEL},
        {"required_permission": AdminApiPermission.ORDER_CANCEL},
        {"service_method": "close_futures_position"},
        {"actor_id": "operator-003"},
        {"operator_intent": "close_position"},
        {"idempotency_key": "idem-futures-reduce-2"},
        {"payload_hash": "d" * 64},
        {"approval_snapshot_id": "approval-futures-002"},
        {"approval_reconciliation_plan_ref": "reconciliation-denied"},
        {"admission_audit_id": "audit-futures-002"},
        {"cap_guard_decision_id": "cap-guard-futures-002"},
    ]
    for update in drift_updates:
        assert (
            resolve_reconciliation_plan(
                store=store,
                request=request.model_copy(update=update),
            )
            is None
        )


@pytest.mark.regression
def test_admin_api_disabled_live_execution_service_is_evidence_only():
    service = get_disabled_live_execution_service()
    state = service.admission_state()
    adapter = build_disabled_live_execution_adapter_contract(
        method="POST",
        route="/api/v1/orders",
        module_id="spot_operations",
        service_method="place_manual_order",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
    )
    intent = build_disabled_live_execution_intent(
        method="POST",
        route="/api/v1/orders",
        module_id="spot_operations",
        identity_key="client_order_id",
        identity_value="client-abc",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.ORDER_CREATE,
        service_method="place_manual_order",
        actor_id="operator-001",
        idempotency_key="idem-001",
        operator_intent="manual_one_off",
        payload_hash="a" * 64,
        blockers=[
            AdminApiLiveAdmissionBlocker.LIVE_EXECUTION_DISABLED,
            AdminApiLiveAdmissionBlocker.BROWSER_AUTHORITY_REJECTED,
        ],
        live_execution_state=state,
    )

    assert isinstance(service, DisabledAdminApiLiveExecutionService)
    assert state.required is True
    assert state.present is True
    assert state.status.value == "live_disabled"
    assert state.source == "disabled_backend_service"
    assert state.missing_reason == "live_execution_disabled"
    assert not hasattr(service, "create_order")
    assert not hasattr(service, "cancel_order")
    assert not hasattr(service, "execute")
    assert not hasattr(service, "submit")
    assert adapter["route"] == "/api/v1/orders"
    assert adapter["method"] == "POST"
    assert adapter["module_id"] == "spot_operations"
    assert adapter["service_method"] == "place_manual_order"
    assert adapter["adapter_reference"] == "AdminApiCommandService.place_manual_order"
    assert adapter["status"].value == "live_disabled"
    assert adapter["source"] == "disabled_backend_service"
    assert adapter["missing_reason"] == "live_execution_disabled"
    assert adapter["executable"] is False
    assert adapter["browser_authority"] == "display_only"
    assert adapter["bff_authority"] == "forward_only_no_execution"
    assert adapter["forbidden_methods"] == [
        "create_order",
        "cancel_order",
        "execute",
        "submit",
        "coinbase_client",
    ]
    assert intent["route"] == "/api/v1/orders"
    assert intent["method"] == "POST"
    assert intent["service_method"] == "place_manual_order"
    assert intent["adapter_reference"] == "AdminApiCommandService.place_manual_order"
    assert intent["prepared"] is False
    assert intent["executable"] is False
    assert intent["status"].value == "live_disabled"
    assert intent["source"] == "disabled_backend_service"
    assert intent["missing_reason"] == "live_execution_disabled"
    assert intent["browser_authority"] == "display_only"
    assert intent["bff_authority"] == "forward_only_no_execution"
    assert intent["live_exchange_submitted"] is False


@pytest.mark.regression
def test_admin_api_m53_pilot_adapter_is_single_route_dry_run_only():
    pilot = build_live_execution_adapter_contract(
        method="POST",
        route="/api/v1/orders",
        module_id="spot_operations",
        service_method="place_manual_order",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
    )
    non_pilot = build_live_execution_adapter_contract(
        method="POST",
        route="/api/v1/orders/{client_order_id}/cancel",
        module_id="spot_operations",
        service_method="cancel_order_by_client_order_id",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
    )

    assert pilot["configured"] is True
    assert pilot["route"] == "/api/v1/orders"
    assert pilot["method"] == "POST"
    assert pilot["service_method"] == "place_manual_order"
    assert pilot["adapter_reference"] == "AdminApiCommandService.place_manual_order"
    assert pilot["status"] == AdminApiLiveExecutionStatus.APPROVAL_REQUIRED
    assert pilot["source"] == "m53_backend_pilot_dry_run"
    assert pilot["missing_reason"] == "pilot_dry_run_only"
    assert pilot["executable"] is False
    assert pilot["browser_authority"] == "display_only"
    assert pilot["bff_authority"] == "forward_only_no_execution"
    assert pilot["forbidden_methods"] == [
        "create_order",
        "cancel_order",
        "execute",
        "submit",
        "coinbase_client",
    ]
    assert any("dry-run only" in item for item in pilot["evidence"])
    assert "non-executable" in pilot["detail"]

    assert non_pilot["configured"] is False
    assert non_pilot["status"] == AdminApiLiveExecutionStatus.LIVE_DISABLED
    assert non_pilot["source"] == "disabled_backend_service"
    assert non_pilot["missing_reason"] == "live_execution_disabled"
    assert non_pilot["executable"] is False


@pytest.mark.regression
def test_admin_api_routes_have_no_direct_coinbase_path_and_dashboard_delegates():
    service_source = inspect.getsource(command_service)
    route_source = "\n".join(
        [
            inspect.getsource(__import__("api.v1.routes.orders", fromlist=[""])),
            inspect.getsource(__import__("api.v1.routes.stealth", fromlist=[""])),
            inspect.getsource(
                __import__("api.v1.routes.movement_repricing", fromlist=[""])
            ),
        ]
    )
    import dashboard_server

    dashboard_source = inspect.getsource(dashboard_server.handle_client_message)

    route_forbidden_tokens = [
        "REST_CLIENT",
        "CoinbaseRestClient",
        "external.coinbase",
        "create_order(",
        "limit_order_gtc(",
        "cancel_orders(",
        "process_anchor_repricing_for_product(",
    ]
    for token in route_forbidden_tokens:
        assert token not in route_source
    assert "dashboard_server" not in service_source
    assert "cancel_orders(" not in service_source
    assert "_dashboard_command_service().place_manual_order" in dashboard_source
    assert "_dashboard_command_service().cancel_order_by_client_order_id" in dashboard_source
    assert "_dashboard_command_service().place_hotpoint_test_order" in dashboard_source
    assert "REST_CLIENT.limit_order_gtc" not in dashboard_source
    assert "_coinbase_order_response_to_dict" not in dashboard_source


@pytest.mark.regression
def test_admin_api_read_only_spot_routes_are_auth_gated(monkeypatch):
    client = _client(monkeypatch)

    response = client.get("/api/v1/spot/readiness")

    assert response.status_code == 401

    response = client.get("/api/v1/spot/command-suite")

    assert response.status_code == 401

    response = client.get("/api/v1/stealth/command-suite")

    assert response.status_code == 401


@pytest.mark.regression
def test_admin_api_read_only_spot_readiness_uses_read_service(monkeypatch):
    from api.v1.routes import spot as spot_routes

    client = _client(monkeypatch)
    service = SimpleNamespace(
        build_spot_readiness=lambda product_ids=None: {
            "type": "spot_readiness",
            "status": "success",
            "products": product_ids or [],
        }
    )
    client.app.dependency_overrides[spot_routes.get_read_service] = lambda: service

    response = client.get(
        "/api/v1/spot/readiness?product_id=BTC-USDC",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )

    assert response.status_code == 200
    assert response.json()["products"] == ["BTC-USDC"]


@pytest.mark.regression
def test_admin_api_stealth_command_suite_is_read_only_backend_evidence(monkeypatch):
    client = _client(monkeypatch)

    response = client.get(
        "/api/v1/stealth/command-suite",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "stealth_command_suite"
    assert payload["status"] == AdminApiGateStatus.BLOCKED.value
    assert payload["module_id"] == "stealth_orders"
    assert payload["approved_phase_range"] == "2141-2160"
    assert payload["command_count"] == 5
    assert payload["blocked_command_count"] == 5
    assert payload["live_enabled_command_count"] == 0
    assert payload["executable_command_count"] == 0
    assert payload["coverage_gap_count"] == 7
    assert payload["exchange_truth_check_count"] == 5
    assert payload["blocking_exchange_truth_check_count"] == 5
    assert payload["active_placement_exchange_truth_required_count"] == 3
    assert payload["exchange_truth_required"] is True
    assert payload["browser_authority"] == "display_only"
    assert payload["bff_authority"] == "forward_only_no_execution"
    assert payload["live_coinbase_orders_ran"] is False
    assert payload["live_coinbase_read_ran"] is False
    assert payload["submitted_notional_usdc"] == "0"
    assert payload["executed_notional_usdc"] == "0"

    command_routes = {command["route"]: command for command in payload["commands"]}
    assert set(command_routes) == {
        "/api/v1/stealth/orders",
        "/api/v1/stealth/orders/{stealth_order_id}/reveal",
        "/api/v1/stealth/orders/{stealth_order_id}/move",
        "/api/v1/stealth/orders/{stealth_order_id}/cancel",
        "/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice",
    }
    for command in command_routes.values():
        assert command["identity_key"] == "stealth_order_id"
        assert command["status"] == AdminApiGateStatus.BLOCKED.value
        assert command["live_enabled"] is False
        assert command["executable"] is False
        assert command["backend_owned"] is True
        assert command["browser_authority"] == "display_only"
        assert command["bff_authority"] == "forward_only_no_execution"
        assert command["proof_routes"]
        for proof_route in command["proof_routes"]:
            assert proof_route["command_identity_key"] == "stealth_order_id"
            assert proof_route["backend_owned"] is True
            assert proof_route["browser_authority"] == "display_only"
            assert proof_route["bff_authority"] == "forward_only_no_execution"
    create_command = command_routes["/api/v1/stealth/orders"]
    assert create_command["mutation_family"] == (
        AdminApiMutationFamilyType.STEALTH_CREATE.value
    )
    assert create_command["action_class"] == AdminApiActionClass.LOCAL_STATE_MUTATION.value
    assert create_command["required_permission"] == AdminApiPermission.ORDER_CREATE.value
    assert create_command["shared_method"] == "create_stealth_order"
    assert create_command["exchange_truth_required"] is False
    assert create_command["active_placement_evidence_required"] is False
    assert "lifecycle_write_guard" in create_command["required_gate_chain"]
    assert "lifecycle_write_guard" in create_command["missing_gate_chain"]
    assert "active_placement_exchange_truth" not in create_command["missing_gate_chain"]

    reveal_command = command_routes[
        "/api/v1/stealth/orders/{stealth_order_id}/reveal"
    ]
    assert reveal_command["mutation_family"] == (
        AdminApiMutationFamilyType.STEALTH_REVEAL.value
    )
    assert reveal_command["action_class"] == AdminApiActionClass.LIVE_EXCHANGE_PLACE.value
    assert reveal_command["required_permission"] == AdminApiPermission.ORDER_CREATE.value
    assert reveal_command["shared_method"] == "reveal_stealth_order_by_stealth_order_id"
    assert reveal_command["exchange_truth_required"] is True
    assert reveal_command["active_placement_evidence_required"] is False
    assert "lifecycle_write_guard" in reveal_command["required_gate_chain"]
    assert "lifecycle_write_guard" in reveal_command["missing_gate_chain"]
    assert "active_placement_exchange_truth" not in reveal_command["missing_gate_chain"]

    move_command = command_routes[
        "/api/v1/stealth/orders/{stealth_order_id}/move"
    ]
    assert move_command["mutation_family"] == (
        AdminApiMutationFamilyType.STEALTH_MOVE.value
    )
    assert move_command["action_class"] == AdminApiActionClass.LIVE_EXCHANGE_CANCEL.value
    assert move_command["required_permission"] == AdminApiPermission.ORDER_CANCEL.value
    assert move_command["shared_method"] == "move_stealth_order_by_stealth_order_id"
    assert move_command["exchange_truth_required"] is True
    assert move_command["active_placement_evidence_required"] is True
    assert "active_placement_exchange_truth" in move_command["required_gate_chain"]
    assert "active_placement_exchange_truth" in move_command["missing_gate_chain"]

    for route in (
        "/api/v1/stealth/orders/{stealth_order_id}/cancel",
        "/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice",
    ):
        assert command_routes[route]["exchange_truth_required"] is True
        assert command_routes[route]["active_placement_evidence_required"] is True
        assert "active_placement_exchange_truth" in command_routes[route][
            "required_gate_chain"
        ]
        assert "active_placement_exchange_truth" in command_routes[route][
            "missing_gate_chain"
        ]

    exchange_truth_checks = {
        item["route"]: item for item in payload["exchange_truth_checks"]
    }
    assert set(exchange_truth_checks) == set(command_routes)
    for route, check in exchange_truth_checks.items():
        command = command_routes[route]
        assert check["mutation_family"] == command["mutation_family"]
        assert check["method"] == command["method"]
        assert check["identity_key"] == "stealth_order_id"
        assert check["command_identity_key"] == "stealth_order_id"
        assert check["status"] == AdminApiGateStatus.BLOCKED.value
        assert check["accepted_command_identity_keys"] == ["stealth_order_id"]
        assert "client_order_id" in check["rejected_command_identity_keys"]
        assert "exchange_order_id" in check["rejected_command_identity_keys"]
        assert "order_id" in check["rejected_command_identity_keys"]
        assert check["active_placement_client_order_id_authority"] == "evidence_only"
        assert check["exchange_order_id_authority"] == "evidence_only"
        assert check["backend_owned"] is True
        assert check["route_bound"] is True
        assert check["browser_authority"] == "display_only"
        assert check["bff_authority"] == "forward_only_no_execution"
        assert check["live_enabled"] is False
        assert check["executable"] is False
        assert check["live_coinbase_orders_ran"] is False
        assert check["live_coinbase_read_ran"] is False
        assert check["current_read_evidence_routes"]
        assert [
            f"{item['method']} {item['route']}" for item in check["current_read_evidence"]
        ] == check["current_read_evidence_routes"]
        assert check["required_contracts"] == check["missing_contracts"]
    assert (
        exchange_truth_checks["/api/v1/stealth/orders"][
            "active_placement_evidence_required"
        ]
        is False
    )
    assert (
        exchange_truth_checks[
            "/api/v1/stealth/orders/{stealth_order_id}/reveal"
        ]["active_placement_evidence_required"]
        is False
    )
    for route in (
        "/api/v1/stealth/orders/{stealth_order_id}/cancel",
        "/api/v1/stealth/orders/{stealth_order_id}/move",
        "/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice",
    ):
        assert exchange_truth_checks[route]["active_placement_evidence_required"] is True
        assert "active_placement_exchange_truth" in exchange_truth_checks[route][
            "required_gate_chain"
        ]

    coverage_gaps = {item["family"]: item for item in payload["coverage_gaps"]}
    assert set(coverage_gaps) == {
        AdminApiStealthCommandSuiteGapFamily.STEALTH_CREATE_WORKFLOW.value,
        AdminApiStealthCommandSuiteGapFamily.STEALTH_REVEAL_WORKFLOW.value,
        AdminApiStealthCommandSuiteGapFamily.STEALTH_CANCEL_EXCHANGE_HANDLING.value,
        AdminApiStealthCommandSuiteGapFamily.STEALTH_MOVE_REVEALED_WORKFLOW.value,
        AdminApiStealthCommandSuiteGapFamily.STEALTH_REPRICE_WORKFLOW.value,
        AdminApiStealthCommandSuiteGapFamily.STEALTH_RECOVERY_WORKFLOW.value,
        AdminApiStealthCommandSuiteGapFamily.STEALTH_RECONCILIATION_WORKFLOW.value,
    }
    for gap in coverage_gaps.values():
        assert gap["status"] == AdminApiGateStatus.BLOCKED.value
        assert gap["backend_owned"] is True
        assert gap["browser_authority"] == "display_only"
        assert gap["bff_authority"] == "forward_only_no_execution"
        assert "exchange-reality" in gap["stealth_rule_boundary"]
        if gap["family"] == AdminApiStealthCommandSuiteGapFamily.STEALTH_CREATE_WORKFLOW.value:
            assert "lifecycle_write_guard" in gap["required_gate_chain"]
            assert "active_placement_exchange_truth" not in gap["required_gate_chain"]
        else:
            assert "active_placement_exchange_truth" in gap["required_gate_chain"]
        assert gap["missing_contracts"]
        assert gap["current_read_evidence_routes"]
        assert [
            f"{item['method']} {item['route']}" for item in gap["current_read_evidence"]
        ] == gap["current_read_evidence_routes"]
        for evidence_route in gap["current_read_evidence"]:
            assert evidence_route["action_class"] == AdminApiActionClass.READ_ONLY.value
            assert evidence_route["backend_owned"] is True
            assert evidence_route["browser_authority"] == "display_only"
            assert evidence_route["bff_authority"] == "read_only_forward"
            assert evidence_route["shared_method"]
            assert evidence_route["documentation_refs"]
    create_gap = coverage_gaps[
        AdminApiStealthCommandSuiteGapFamily.STEALTH_CREATE_WORKFLOW.value
    ]
    assert create_gap["exposure_status"] == (
        AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED.value
    )
    assert create_gap["command_route"] == "/api/v1/stealth/orders"
    assert "stealth_create_lifecycle_write_contract" in create_gap["missing_contracts"]
    assert create_gap["detail"].endswith("mutate local lifecycle state.")
    reveal_gap = coverage_gaps[
        AdminApiStealthCommandSuiteGapFamily.STEALTH_REVEAL_WORKFLOW.value
    ]
    assert reveal_gap["exposure_status"] == (
        AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED.value
    )
    assert reveal_gap["command_route"] == (
        "/api/v1/stealth/orders/{stealth_order_id}/reveal"
    )
    assert "stealth_reveal_admin_route" not in reveal_gap["missing_contracts"]
    assert "stealth_reveal_trigger_guard" in reveal_gap["missing_contracts"]
    assert reveal_gap["detail"].endswith("or mutate lifecycle state.")
    move_gap = coverage_gaps[
        AdminApiStealthCommandSuiteGapFamily.STEALTH_MOVE_REVEALED_WORKFLOW.value
    ]
    assert move_gap["exposure_status"] == (
        AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED.value
    )
    assert move_gap["command_route"] == "/api/v1/stealth/orders/{stealth_order_id}/move"
    assert "stealth_move_revealed_admin_route" not in move_gap["missing_contracts"]
    assert (
        "stealth_move_mutation_claim_snapshot_contract"
        in move_gap["missing_contracts"]
    )
    assert move_gap["detail"].endswith("or mutate lifecycle state.")
    assert (
        coverage_gaps[
            AdminApiStealthCommandSuiteGapFamily.STEALTH_CANCEL_EXCHANGE_HANDLING.value
        ]["command_route"]
        == "/api/v1/stealth/orders/{stealth_order_id}/cancel"
    )
    assert (
        coverage_gaps[AdminApiStealthCommandSuiteGapFamily.STEALTH_REPRICE_WORKFLOW.value][
            "command_route"
        ]
        == "/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice"
    )


@pytest.mark.regression
def test_admin_api_spot_command_suite_is_read_only_backend_evidence(monkeypatch):
    client = _client(monkeypatch)

    response = client.get(
        "/api/v1/spot/command-suite",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "spot_command_suite"
    assert payload["status"] == AdminApiGateStatus.BLOCKED.value
    assert payload["module_id"] == "spot_operations"
    assert payload["command_count"] == 10
    assert payload["blocked_command_count"] == 10
    assert payload["live_enabled_command_count"] == 0
    assert payload["executable_command_count"] == 0
    assert payload["coverage_gap_count"] == 3
    assert payload["spot_rules_platform_default"] is False
    assert payload["browser_authority"] == "display_only"
    assert payload["bff_authority"] == "forward_only_no_execution"
    assert payload["live_coinbase_orders_ran"] is False
    assert payload["submitted_notional_usdc"] == "0"
    assert payload["executed_notional_usdc"] == "0"

    coverage_gaps = {item["family"]: item for item in payload["coverage_gaps"]}
    assert set(coverage_gaps) == {
        AdminApiSpotCommandSuiteGapFamily.SPOT_SWEEP_AUTOMATION.value,
        AdminApiSpotCommandSuiteGapFamily.SPOT_RECOVERY_WORKFLOW.value,
        AdminApiSpotCommandSuiteGapFamily.SPOT_RECONCILIATION_WORKFLOW.value,
    }
    for gap in coverage_gaps.values():
        assert gap["status"] == AdminApiGateStatus.BLOCKED.value
        assert gap["backend_owned"] is True
        assert gap["browser_authority"] == "display_only"
        assert gap["bff_authority"] == "forward_only_no_execution"
        assert "Spot-only" in gap["spot_rule_boundary"]
        assert gap["current_read_evidence_routes"]
        assert gap["current_read_evidence"]
        assert [
            f"{item['method']} {item['route']}" for item in gap["current_read_evidence"]
        ] == gap["current_read_evidence_routes"]
        for evidence_route in gap["current_read_evidence"]:
            assert evidence_route["method"] == "GET"
            assert evidence_route["action_class"] == AdminApiActionClass.READ_ONLY.value
            assert evidence_route["backend_owned"] is True
            assert evidence_route["browser_authority"] == "display_only"
            assert evidence_route["bff_authority"] == "read_only_forward"
            assert evidence_route["shared_method"]
            assert evidence_route["documentation_refs"]
        assert gap["required_backend_contract"]
        assert gap["required_gate_chain"]
        if gap["family"] != AdminApiSpotCommandSuiteGapFamily.SPOT_RECOVERY_WORKFLOW.value:
            assert gap["missing_contracts"]
        assert "docs/COMMAND_WORKFLOWS.md" in gap["documentation_refs"]
    sweep_gap = coverage_gaps[
        AdminApiSpotCommandSuiteGapFamily.SPOT_SWEEP_AUTOMATION.value
    ]
    assert (
        sweep_gap["exposure_status"]
        == AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED.value
    )
    assert sweep_gap["command_route"] == "/api/v1/spot/sweep/automation-runs"
    assert "GET /api/v1/spot/sweep/status" in sweep_gap["current_read_evidence_routes"]
    assert "enterprise_sweep_scheduler_contract" in sweep_gap["missing_contracts"]
    assert (
        coverage_gaps[AdminApiSpotCommandSuiteGapFamily.SPOT_RECONCILIATION_WORKFLOW.value][
            "command_route"
        ]
        == "/api/v1/spot/recovery/reconciliation-executions"
    )
    assert AdminApiSpotCommandSuiteGapFamily.SPOT_PNL_TRACKING.value not in coverage_gaps
    recovery_gap = coverage_gaps[
        AdminApiSpotCommandSuiteGapFamily.SPOT_RECOVERY_WORKFLOW.value
    ]
    assert (
        recovery_gap["exposure_status"]
        == AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED.value
    )
    assert recovery_gap["command_route"] == "/api/v1/spot/recovery/apply-executions"
    assert "GET /api/v1/spot/recovery/preview" in recovery_gap[
        "current_read_evidence_routes"
    ]
    assert "GET /api/v1/spot/recovery/apply-review" in recovery_gap[
        "current_read_evidence_routes"
    ]
    assert "GET /api/v1/spot/recovery/rollback-plan" in recovery_gap[
        "current_read_evidence_routes"
    ]
    assert "GET /api/v1/spot/recovery/reconciliation-proof" in recovery_gap[
        "current_read_evidence_routes"
    ]
    assert "GET /api/v1/admin/recovery-gate" in recovery_gap[
        "current_read_evidence_routes"
    ]
    assert "spot_recovery_preview_contract" not in recovery_gap["missing_contracts"]
    assert "spot_recovery_apply_contract" not in recovery_gap["missing_contracts"]
    assert "spot_recovery_rollback_contract" not in recovery_gap["missing_contracts"]
    assert "spot_recovery_reconciliation_contract" not in recovery_gap[
        "missing_contracts"
    ]
    assert "spot_recovery_apply_execution_contract" not in recovery_gap[
        "missing_contracts"
    ]
    assert "spot_recovery_rollback_execution_contract" not in recovery_gap[
        "missing_contracts"
    ]
    assert "spot_recovery_reconciliation_proof_writer_contract" not in recovery_gap[
        "missing_contracts"
    ]
    assert "spot_recovery_state_repair_contract" not in recovery_gap[
        "missing_contracts"
    ]
    assert "spot_recovery_post_apply_reconciliation_completion" not in recovery_gap[
        "missing_contracts"
    ]
    assert "post_apply_reconciliation_completion" in recovery_gap[
        "required_gate_chain"
    ]
    assert "spot_recovery_proof_persistence_contract" not in recovery_gap[
        "missing_contracts"
    ]
    reconciliation_gap = coverage_gaps[
        AdminApiSpotCommandSuiteGapFamily.SPOT_RECONCILIATION_WORKFLOW.value
    ]
    assert "GET /api/v1/spot/recovery/reconciliation-proof" in reconciliation_gap[
        "current_read_evidence_routes"
    ]
    assert "GET /api/v1/admin/reconciliation/plans" in reconciliation_gap[
        "current_read_evidence_routes"
    ]
    assert "spot_recovery_reconciliation_proof_writer_contract" not in (
        reconciliation_gap["missing_contracts"]
    )
    assert "spot_exchange_state_proof_persistence_contract" not in (
        reconciliation_gap["missing_contracts"]
    )

    commands = {item["mutation_family"]: item for item in payload["commands"]}
    assert set(commands) == {
        AdminApiMutationFamilyType.SPOT_MANUAL_ORDER.value,
        AdminApiMutationFamilyType.SPOT_ORDER_CANCEL.value,
        AdminApiMutationFamilyType.SPOT_CAMPAIGN_EXECUTION.value,
        AdminApiMutationFamilyType.SPOT_SWEEP_AUTOMATION.value,
        AdminApiMutationFamilyType.SPOT_RECOVERY_APPLY_EXECUTION.value,
        AdminApiMutationFamilyType.SPOT_RECOVERY_ROLLBACK_EXECUTION.value,
        AdminApiMutationFamilyType.SPOT_RECOVERY_EXCHANGE_STATE_PROOF.value,
        AdminApiMutationFamilyType.SPOT_RECOVERY_EXCHANGE_STATE_SNAPSHOT.value,
        AdminApiMutationFamilyType.SPOT_RECOVERY_RECONCILIATION_EXECUTION.value,
        AdminApiMutationFamilyType.SPOT_RECOVERY_RECONCILIATION_PROOF.value,
    }
    manual = commands[AdminApiMutationFamilyType.SPOT_MANUAL_ORDER.value]
    assert manual["route"] == "/api/v1/orders"
    assert manual["method"] == "POST"
    assert manual["identity_key"] == "client_order_id"
    assert manual["shared_method"] == "place_manual_order"
    assert manual["live_adapter_configured"] is True
    assert manual["live_enabled"] is False
    assert manual["executable"] is False
    assert manual["status"] == AdminApiGateStatus.BLOCKED.value
    assert (
        manual["live_execution_status"]
        == AdminApiLiveExecutionStatus.APPROVAL_REQUIRED.value
    )
    assert "approval_snapshot" in manual["required_gate_chain"]
    assert "live_execution_service" in manual["missing_gate_chain"]
    assert manual["readiness_precondition_count"] == len(
        manual["readiness_preconditions"]
    )
    assert manual["blocking_readiness_precondition_count"] == sum(
        1 for item in manual["readiness_preconditions"] if item["blocking"]
    )
    assert manual["passed_readiness_precondition_count"] == sum(
        1
        for item in manual["readiness_preconditions"]
        if item["status"] == AdminApiGateStatus.PASSED.value
    )
    manual_preconditions = {
        item["precondition"]: item for item in manual["readiness_preconditions"]
    }
    assert set(manual_preconditions) == {
        AdminApiLiveReadinessPrecondition.APPROVAL_STORE_CONTRACT.value,
        AdminApiLiveReadinessPrecondition.APPROVAL_SNAPSHOT.value,
        AdminApiLiveReadinessPrecondition.ADMISSION_AUDIT_TRAIL.value,
        AdminApiLiveReadinessPrecondition.CAP_GUARD_CONTRACT.value,
        AdminApiLiveReadinessPrecondition.RECONCILIATION_PLAN.value,
        AdminApiLiveReadinessPrecondition.LIVE_EXECUTION_ADAPTER.value,
        AdminApiLiveReadinessPrecondition.EXECUTION_INTENT_ENVELOPE.value,
        AdminApiLiveReadinessPrecondition.BROWSER_BFF_BOUNDARY.value,
        AdminApiLiveReadinessPrecondition.LIVE_EXECUTION_SERVICE.value,
    }
    assert manual_preconditions[
        AdminApiLiveReadinessPrecondition.LIVE_EXECUTION_ADAPTER.value
    ]["configured"] is True
    assert manual_preconditions[
        AdminApiLiveReadinessPrecondition.BROWSER_BFF_BOUNDARY.value
    ]["status"] == AdminApiGateStatus.PASSED.value
    assert manual_preconditions[
        AdminApiLiveReadinessPrecondition.LIVE_EXECUTION_SERVICE.value
    ]["source"] == "disabled_backend_service"
    assert all(
        item["browser_authority"] == "display_only"
        and item["bff_authority"] == "forward_only_no_execution"
        for item in manual["readiness_preconditions"]
    )
    assert "Spot-only" in manual["spot_rule_boundary"]
    manual_proof_routes = {
        f"{item['method']} {item['route']}": item
        for item in manual["proof_routes"]
    }
    assert {
        "POST /api/v1/admin/approvals/requests",
        "POST /api/v1/admin/approvals/requests/{approval_request_id}/decisions",
        "POST /api/v1/admin/admission-audits",
        "POST /api/v1/admin/cap-guard/decisions",
        "POST /api/v1/admin/reconciliation/plans",
    } == set(manual_proof_routes)
    assert {
        item["gate"] for item in manual["proof_routes"]
    } == {
        AdminApiLivePreflightCategory.APPROVAL.value,
        AdminApiLivePreflightCategory.AUDIT.value,
        AdminApiLivePreflightCategory.CAP_GUARD.value,
        AdminApiLivePreflightCategory.RECONCILIATION.value,
    }
    for proof_route in manual["proof_routes"]:
        assert proof_route["status"] == AdminApiGateStatus.BLOCKED.value
        assert proof_route["required"] is True
        assert proof_route["blocking"] is True
        assert proof_route["backend_owned"] is True
        assert proof_route["route_bound"] is True
        assert proof_route["browser_authority"] == "display_only"
        assert proof_route["bff_authority"] == "forward_only_no_execution"
        assert proof_route["command_identity_key"] == "client_order_id"
    assert (
        manual_proof_routes[
            "POST /api/v1/admin/approvals/requests/{approval_request_id}/decisions"
        ]["identity_key"]
        == "approval_request_id"
    )
    assert (
        manual_proof_routes["POST /api/v1/admin/cap-guard/decisions"][
            "required_permission"
        ]
        == AdminApiPermission.CAP_GUARD_RECORD.value
    )

    cancel = commands[AdminApiMutationFamilyType.SPOT_ORDER_CANCEL.value]
    assert cancel["route"] == "/api/v1/orders/{client_order_id}/cancel"
    assert cancel["identity_key"] == "client_order_id"
    assert cancel["live_adapter_configured"] is False
    assert (
        cancel["live_execution_status"]
        == AdminApiLiveExecutionStatus.LIVE_DISABLED.value
    )
    assert "cancel_order(client_order_id)" in cancel["backend_contract_refs"]
    assert all(
        item["command_identity_key"] == "client_order_id"
        for item in cancel["proof_routes"]
    )
    assert any(
        item["shared_method"] == "record_reconciliation_plan"
        for item in cancel["proof_routes"]
    )

    campaign = commands[AdminApiMutationFamilyType.SPOT_CAMPAIGN_EXECUTION.value]
    assert campaign["route"] == "/api/v1/spot/campaign/executions"
    assert campaign["identity_key"] == "campaign_id"
    assert campaign["live_adapter_configured"] is False
    assert "business/spot_campaign.py" in campaign["backend_contract_refs"]
    assert all(
        item["command_identity_key"] == "campaign_id"
        for item in campaign["proof_routes"]
    )

    sweep = commands[AdminApiMutationFamilyType.SPOT_SWEEP_AUTOMATION.value]
    assert sweep["route"] == "/api/v1/spot/sweep/automation-runs"
    assert sweep["identity_key"] == "sweep_config_id"
    assert sweep["required_permission"] == AdminApiPermission.SPOT_SWEEP_EXECUTE.value
    assert sweep["shared_method"] == "run_spot_sweep_automation"
    assert sweep["live_adapter_configured"] is False
    assert "business/spot_portfolio_sweep.py" in sweep["backend_contract_refs"]
    assert all(
        item["command_identity_key"] == "sweep_config_id"
        for item in sweep["proof_routes"]
    )
    recovery_commands = {
        AdminApiMutationFamilyType.SPOT_RECOVERY_APPLY_EXECUTION.value: (
            "/api/v1/spot/recovery/apply-executions",
            "execute_spot_recovery_apply",
            AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        ),
        AdminApiMutationFamilyType.SPOT_RECOVERY_ROLLBACK_EXECUTION.value: (
            "/api/v1/spot/recovery/rollback-executions",
            "execute_spot_recovery_rollback",
            AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        ),
        AdminApiMutationFamilyType.SPOT_RECOVERY_EXCHANGE_STATE_PROOF.value: (
            "/api/v1/spot/recovery/exchange-state-proofs",
            "record_spot_recovery_exchange_state_proof",
            AdminApiPermission.SPOT_RECOVERY_RECORD,
        ),
        AdminApiMutationFamilyType.SPOT_RECOVERY_EXCHANGE_STATE_SNAPSHOT.value: (
            "/api/v1/spot/recovery/exchange-state-snapshots",
            "record_spot_recovery_exchange_state_snapshot",
            AdminApiPermission.SPOT_RECOVERY_RECORD,
        ),
        AdminApiMutationFamilyType.SPOT_RECOVERY_RECONCILIATION_EXECUTION.value: (
            "/api/v1/spot/recovery/reconciliation-executions",
            "execute_spot_recovery_reconciliation",
            AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        ),
        AdminApiMutationFamilyType.SPOT_RECOVERY_RECONCILIATION_PROOF.value: (
            "/api/v1/spot/recovery/reconciliation-proofs",
            "record_spot_recovery_reconciliation_proof",
            AdminApiPermission.SPOT_RECOVERY_RECORD,
        ),
    }
    for family, (route, shared_method, required_permission) in recovery_commands.items():
        recovery_command = commands[family]
        assert recovery_command["route"] == route
        assert recovery_command["method"] == "POST"
        assert recovery_command["identity_key"] == "client_order_id"
        assert recovery_command["action_class"] == AdminApiActionClass.LOCAL_STATE_MUTATION.value
        assert (
            recovery_command["required_permission"]
            == required_permission.value
        )
        assert recovery_command["shared_method"] == shared_method
        assert recovery_command["live_adapter_configured"] is False
        assert recovery_command["live_enabled"] is False
        assert recovery_command["executable"] is False
        assert (
            recovery_command["live_execution_status"]
            == AdminApiLiveExecutionStatus.LIVE_DISABLED.value
        )
        assert "spot recovery" in recovery_command["detail"].lower()
        assert all(
            item["command_identity_key"] == "client_order_id"
            for item in recovery_command["proof_routes"]
        )


@pytest.mark.regression
def test_admin_api_spot_routes_preserve_typed_read_payload_fields(monkeypatch):
    from api.v1.routes import spot as spot_routes

    client = _client(monkeypatch)
    service = SimpleNamespace(
        build_spot_sweep_pnl=lambda product_ids=None, include_coinbase_average_cost=False: {
            "type": "spot_sweep_pnl",
            "status": "success",
            "pnl_report": {
                "snapshot": {
                    "products": [{"product_id": "BTC-USDC", "total_pnl": "1.23"}],
                    "portfolio": {"total_pnl": "1.23"},
                }
            },
            "read_only_coinbase_requests": ["accounts"],
            "backend_extra_evidence": {"kept": True},
            "live_coinbase_orders_ran": False,
        },
        build_spot_direct_order_audit=lambda **kwargs: {
            "type": "spot_direct_order_audit",
            "status": "success",
            "client_order_id": kwargs["client_order_id"],
            "audit": {"audit_is_read_only": True},
            "events": [{"event_type": "order_submitted"}],
            "fills": [{"fill_id": "fill-001"}],
            "live_coinbase_orders_ran": False,
        },
    )
    client.app.dependency_overrides[spot_routes.get_read_service] = lambda: service

    pnl_response = client.get(
        "/api/v1/spot/sweep/pnl?product_id=BTC-USDC&include_coinbase_average_cost=true",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    audit_response = client.get(
        "/api/v1/spot/direct-orders/client-abc/audit",
        headers=_headers(roles=AdminApiRole.AUDITOR.value),
    )

    assert pnl_response.status_code == 200
    assert pnl_response.json()["pnl_report"]["snapshot"]["products"][0]["product_id"] == "BTC-USDC"
    assert pnl_response.json()["read_only_coinbase_requests"] == ["accounts"]
    assert pnl_response.json()["backend_extra_evidence"] == {"kept": True}
    assert audit_response.status_code == 200
    assert audit_response.json()["client_order_id"] == "client-abc"
    assert audit_response.json()["audit"]["audit_is_read_only"] is True
    assert audit_response.json()["events"][0]["event_type"] == "order_submitted"


@pytest.mark.regression
def test_admin_api_spot_pnl_checkpoint_routes_record_replay_and_read(monkeypatch):
    client = _client(monkeypatch)
    body = {
        "checkpoint_id": "spot-pnl-checkpoint-001",
        "scope": "portfolio",
        "product_ids": ["BTC-USDC", "ETH-USDC"],
        "pnl_snapshot": {
            "portfolio": {"total_pnl": "1.23"},
            "products": [{"product_id": "BTC-USDC", "total_pnl": "0.50"}],
        },
        "average_cost_snapshot": {"source": "coinbase_average_cost"},
        "source_report_route": "/api/v1/spot/sweep/pnl",
        "review_status": "warning",
        "operator_notes": "Operator reviewed P/L checkpoint evidence.",
    }

    denied = client.post(
        "/api/v1/spot/pnl/checkpoints",
        json=body,
        headers=_headers(
            idempotency_key="spot-pnl-checkpoint-denied",
            operator_intent="record_spot_pnl_checkpoint",
            roles=AdminApiRole.VIEWER.value,
        ),
    )
    assert denied.status_code == 403

    created = client.post(
        "/api/v1/spot/pnl/checkpoints",
        json=body,
        headers=_headers(
            idempotency_key="spot-pnl-checkpoint-idem",
            operator_intent="record_spot_pnl_checkpoint",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["status"] == AdminApiCommandStatus.ACCEPTED.value
    assert payload["required_permission"] == AdminApiPermission.SPOT_PNL_RECORD.value
    assert payload["service_method"] == "record_spot_pnl_checkpoint"
    assert payload["profitability_authority"] is False
    assert payload["sell_authority"] is False
    assert payload["checkpoint_is_tax_accounting"] is False
    assert payload["live_exchange_submitted"] is False
    assert payload["live_coinbase_orders_ran"] is False
    checkpoint = payload["checkpoint"]
    assert checkpoint["checkpoint_id"] == "spot-pnl-checkpoint-001"
    assert checkpoint["review_status"] == AdminApiGateStatus.WARNING.value
    assert checkpoint["source_report_route"] == "/api/v1/spot/sweep/pnl"
    assert checkpoint["profitability_authority"] is False
    assert checkpoint["sell_authority"] is False
    assert checkpoint["checkpoint_is_tax_accounting"] is False
    assert checkpoint["average_cost_reviewed"] is True
    assert checkpoint["average_cost_review_source"] == "coinbase_average_cost"
    assert "not sell authority" in checkpoint["average_cost_review_detail"]
    assert "browser guard evidence" in checkpoint["average_cost_review_detail"]
    assert payload["audit_id"]
    assert checkpoint["audit_id"] == payload["audit_id"]
    assert checkpoint["audit_linked"] is True
    assert checkpoint["audit_source"] == "admin_api_audit_log"
    assert "review evidence only" in checkpoint["audit_detail"]
    assert checkpoint["recovery_linked"] is True
    assert checkpoint["recovery_source"] == "admin_recovery_gate"
    assert checkpoint["recovery_routes"] == [
        "/api/v1/admin/recovery-gate",
        "/api/v1/admin/fill-ledger-health",
    ]
    assert "read-only recovery triage evidence" in checkpoint["recovery_detail"]
    assert "does not execute recovery" in checkpoint["recovery_detail"]
    assert "apply repairs" in checkpoint["recovery_detail"]
    assert "call Coinbase" in checkpoint["recovery_detail"]
    assert checkpoint["reconciliation_linked"] is True
    assert checkpoint["reconciliation_source"] == "admin_reconciliation_plans"
    assert checkpoint["reconciliation_routes"] == [
        "/api/v1/admin/reconciliation/plans",
        "/api/v1/admin/reconciliation/plans/{plan_id}",
    ]
    assert "read-only reconciliation plan evidence" in (
        checkpoint["reconciliation_detail"]
    )
    assert "does not execute reconciliation" in checkpoint[
        "reconciliation_detail"
    ]
    assert "mutate order or exchange state" in checkpoint["reconciliation_detail"]
    assert "call Coinbase" in checkpoint["reconciliation_detail"]
    audit_event = client.admin_api_test_audit_store.find_by_audit_id(payload["audit_id"])
    assert audit_event is not None
    assert audit_event.idempotency_key == "spot-pnl-checkpoint-idem"
    assert audit_event.operator_intent == "record_spot_pnl_checkpoint"

    replayed = client.post(
        "/api/v1/spot/pnl/checkpoints",
        json=body,
        headers=_headers(
            idempotency_key="spot-pnl-checkpoint-idem",
            operator_intent="record_spot_pnl_checkpoint",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert replayed.status_code == 200
    assert replayed.headers["X-Idempotency-Replayed"] == "true"
    assert replayed.json()["checkpoint"]["checkpoint_id"] == "spot-pnl-checkpoint-001"
    assert replayed.json()["checkpoint"]["audit_id"] == payload["audit_id"]
    assert replayed.json()["checkpoint"]["recovery_linked"] is True
    assert replayed.json()["checkpoint"]["reconciliation_linked"] is True

    conflict = client.post(
        "/api/v1/spot/pnl/checkpoints",
        json={**body, "operator_notes": "changed"},
        headers=_headers(
            idempotency_key="spot-pnl-checkpoint-idem",
            operator_intent="record_spot_pnl_checkpoint",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert conflict.status_code == 409
    assert conflict.json()["status"] == AdminApiCommandStatus.CONFLICT.value

    listed = client.get(
        "/api/v1/spot/pnl/checkpoints",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    assert listed.status_code == 200
    assert listed.json()["total_count"] == 1
    assert listed.json()["warning_count"] == 1
    assert listed.json()["average_cost_review_count"] == 1
    assert listed.json()["audit_linked_count"] == 1
    assert listed.json()["recovery_linked_count"] == 1
    assert listed.json()["reconciliation_linked_count"] == 1
    assert listed.json()["live_coinbase_orders_ran"] is False

    detail = client.get(
        "/api/v1/spot/pnl/checkpoints/spot-pnl-checkpoint-001",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    assert detail.status_code == 200
    assert detail.json()["read_only"] is True
    assert detail.json()["checkpoint"]["checkpoint_id"] == "spot-pnl-checkpoint-001"
    assert detail.json()["checkpoint"]["average_cost_reviewed"] is True
    assert detail.json()["checkpoint"]["audit_id"] == payload["audit_id"]
    assert detail.json()["checkpoint"]["audit_linked"] is True
    assert detail.json()["checkpoint"]["recovery_linked"] is True
    assert detail.json()["checkpoint"]["recovery_source"] == "admin_recovery_gate"
    assert detail.json()["checkpoint"]["reconciliation_linked"] is True
    assert (
        detail.json()["checkpoint"]["reconciliation_source"]
        == "admin_reconciliation_plans"
    )

    client.admin_api_test_pnl_checkpoint_store.append(
        SpotPnlCheckpointRecord(
            checkpoint_id="spot-pnl-checkpoint-unverified-audit",
            scope="portfolio",
            product_ids=["ETH-USDC"],
            pnl_snapshot={"portfolio": {"total_pnl": "0.10"}},
            average_cost_snapshot={"source": "coinbase_average_cost"},
            source_report_route="/api/v1/spot/sweep/pnl",
            review_status=AdminApiGateStatus.WARNING,
            actor_id="operator-001",
            operator_intent="record_spot_pnl_checkpoint",
            idempotency_key="spot-pnl-checkpoint-unverified-audit",
            payload_hash="a" * 64,
            audit_id="missing-spot-pnl-checkpoint-audit",
            operator_notes="Stored checkpoint has an audit id without an audit row.",
        )
    )
    client.admin_api_test_audit_store.append(
        AdminApiAuditEvent(
            audit_id="missing-spot-pnl-checkpoint-audit",
            actor_id="operator-001",
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            permission=AdminApiPermission.ORDER_CREATE,
            endpoint="POST /api/v1/orders",
            request_id="corr-mismatched-audit",
            operator_intent="record_spot_pnl_checkpoint",
            idempotency_key="spot-pnl-checkpoint-unverified-audit",
            status=AdminApiCommandStatus.ACCEPTED,
            message="Mismatched audit row must not verify checkpoint linkage.",
        )
    )
    unverified_detail = client.get(
        "/api/v1/spot/pnl/checkpoints/spot-pnl-checkpoint-unverified-audit",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    assert unverified_detail.status_code == 200
    unverified_checkpoint = unverified_detail.json()["checkpoint"]
    assert unverified_checkpoint["audit_id"] == "missing-spot-pnl-checkpoint-audit"
    assert unverified_checkpoint["audit_linked"] is False
    assert unverified_checkpoint["audit_source"] is None
    assert "no matching append-only Admin API audit event" in (
        unverified_checkpoint["audit_detail"]
    )
    assert unverified_checkpoint["recovery_linked"] is True
    assert unverified_checkpoint["recovery_source"] == "admin_recovery_gate"
    assert unverified_checkpoint["reconciliation_linked"] is True
    assert (
        unverified_checkpoint["reconciliation_source"]
        == "admin_reconciliation_plans"
    )
    listed_after_unverified = client.get(
        "/api/v1/spot/pnl/checkpoints",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    assert listed_after_unverified.status_code == 200
    assert listed_after_unverified.json()["total_count"] == 2
    assert listed_after_unverified.json()["audit_linked_count"] == 1
    assert listed_after_unverified.json()["recovery_linked_count"] == 2
    assert listed_after_unverified.json()["reconciliation_linked_count"] == 2

    legacy_body = {
        **body,
        "checkpoint_id": "spot-pnl-checkpoint-legacy-replay",
    }
    legacy_payload_hash = make_payload_hash({
        "endpoint": "POST /api/v1/spot/pnl/checkpoints",
        "actor_id": "operator-001",
        "roles": [AdminApiRole.TRADER.value],
        "operator_intent": "record_spot_pnl_checkpoint",
        "body": legacy_body,
        "path_params": {},
    })
    legacy_response = {
        "type": "spot_pnl_checkpoint",
        "status": AdminApiCommandStatus.ACCEPTED.value,
        "required_permission": AdminApiPermission.SPOT_PNL_RECORD.value,
        "service_method": "record_spot_pnl_checkpoint",
        "message": "Spot P/L checkpoint accepted.",
        "checkpoint": {
            "checkpoint_id": "spot-pnl-checkpoint-legacy-replay",
            "recorded_at": "2026-01-01T00:00:00+00:00",
            "scope": "portfolio",
            "product_ids": ["BTC-USDC"],
            "pnl_snapshot": legacy_body["pnl_snapshot"],
            "average_cost_snapshot": legacy_body["average_cost_snapshot"],
            "average_cost_reviewed": True,
            "average_cost_review_source": "coinbase_average_cost",
            "average_cost_review_detail": "legacy average-cost detail",
            "source_report_route": "/api/v1/spot/sweep/pnl",
            "review_status": AdminApiGateStatus.WARNING.value,
            "actor_id": "operator-001",
            "operator_intent": "record_spot_pnl_checkpoint",
            "idempotency_key": "spot-pnl-checkpoint-legacy-replay",
            "payload_hash": legacy_payload_hash,
            "source": "admin_api_spot_pnl_checkpoint_log",
            "operator_notes": legacy_body["operator_notes"],
            "detail": "legacy checkpoint detail",
        },
        "correlation_id": "corr-001",
        "idempotency_key": "spot-pnl-checkpoint-legacy-replay",
    }
    client.admin_api_test_idempotency_store.put_record(
        IdempotencyRecord(
            idempotency_key="spot-pnl-checkpoint-legacy-replay",
            payload_hash=legacy_payload_hash,
            status=AdminApiCommandStatus.ACCEPTED,
            response=legacy_response,
            actor_id="operator-001",
            endpoint="POST /api/v1/spot/pnl/checkpoints",
        )
    )
    legacy_replay = client.post(
        "/api/v1/spot/pnl/checkpoints",
        json=legacy_body,
        headers=_headers(
            idempotency_key="spot-pnl-checkpoint-legacy-replay",
            operator_intent="record_spot_pnl_checkpoint",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert legacy_replay.status_code == 200
    assert legacy_replay.headers["X-Idempotency-Replayed"] == "true"
    legacy_checkpoint = legacy_replay.json()["checkpoint"]
    assert legacy_checkpoint["audit_linked"] is False
    assert "legacy local checkpoint evidence" in legacy_checkpoint["audit_detail"]
    assert legacy_checkpoint["recovery_linked"] is False
    assert legacy_checkpoint["recovery_source"] is None
    assert legacy_checkpoint["recovery_routes"] == []
    assert "does not include recovery-link evidence" in (
        legacy_checkpoint["recovery_detail"]
    )
    assert legacy_checkpoint["reconciliation_linked"] is False
    assert legacy_checkpoint["reconciliation_source"] is None
    assert legacy_checkpoint["reconciliation_routes"] == []
    assert "does not include reconciliation-plan link evidence" in (
        legacy_checkpoint["reconciliation_detail"]
    )

    rejected = client.post(
        "/api/v1/spot/pnl/checkpoints",
        json={
            **body,
            "checkpoint_id": "spot-pnl-checkpoint-002",
            "source_report_route": "/api/v1/futures/positions",
        },
        headers=_headers(
            idempotency_key="spot-pnl-checkpoint-rejected",
            operator_intent="record_spot_pnl_checkpoint",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert rejected.status_code == 400
    assert "must reference /api/v1/spot/sweep/pnl" in rejected.json()["message"]
    assert client.admin_api_test_pnl_checkpoint_store.find_by_checkpoint_id(
        "spot-pnl-checkpoint-002"
    ) is None

    rejected_empty_average_cost = client.post(
        "/api/v1/spot/pnl/checkpoints",
        json={
            **body,
            "checkpoint_id": "spot-pnl-checkpoint-003",
            "average_cost_snapshot": {},
        },
        headers=_headers(
            idempotency_key="spot-pnl-checkpoint-empty-average-cost",
            operator_intent="record_spot_pnl_checkpoint",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert rejected_empty_average_cost.status_code == 400
    assert (
        "average_cost_snapshot must be non-empty"
        in rejected_empty_average_cost.json()["message"]
    )


@pytest.mark.regression
def test_admin_api_backend_rbac_matches_frontend_role_hints():
    viewer = AdminApiActor(actor_id="viewer-001", roles=[AdminApiRole.VIEWER])
    operator = AdminApiActor(actor_id="operator-001", roles=[AdminApiRole.OPERATOR])
    trader = AdminApiActor(actor_id="trader-001", roles=[AdminApiRole.TRADER])
    emergency = AdminApiActor(actor_id="emergency-001", roles=[AdminApiRole.EMERGENCY])

    assert actor_has_permission(viewer, AdminApiPermission.ANALYTICS_READ)
    assert actor_has_permission(viewer, AdminApiPermission.AUDIT_READ)
    assert actor_has_permission(viewer, AdminApiPermission.CAMPAIGN_READ)
    assert not actor_has_permission(viewer, AdminApiPermission.ORDER_CREATE)
    assert not actor_has_permission(viewer, AdminApiPermission.SPOT_SWEEP_EXECUTE)
    assert not actor_has_permission(viewer, AdminApiPermission.SPOT_PNL_RECORD)
    assert not actor_has_permission(viewer, AdminApiPermission.SPOT_RECOVERY_EXECUTE)
    assert not actor_has_permission(viewer, AdminApiPermission.SPOT_RECOVERY_RECORD)
    assert actor_has_permission(operator, AdminApiPermission.RUNTIME_PAUSE)
    assert actor_has_permission(operator, AdminApiPermission.RUNTIME_RESUME)
    assert not actor_has_permission(operator, AdminApiPermission.ORDER_CANCEL)
    assert not actor_has_permission(operator, AdminApiPermission.SPOT_SWEEP_EXECUTE)
    assert not actor_has_permission(operator, AdminApiPermission.SPOT_RECOVERY_EXECUTE)
    assert not actor_has_permission(operator, AdminApiPermission.SPOT_RECOVERY_RECORD)
    assert actor_has_permission(trader, AdminApiPermission.CAMPAIGN_EXECUTE)
    assert actor_has_permission(trader, AdminApiPermission.SPOT_SWEEP_EXECUTE)
    assert actor_has_permission(trader, AdminApiPermission.SPOT_PNL_RECORD)
    assert actor_has_permission(trader, AdminApiPermission.SPOT_RECOVERY_EXECUTE)
    assert actor_has_permission(trader, AdminApiPermission.SPOT_RECOVERY_RECORD)
    assert not actor_has_permission(emergency, AdminApiPermission.ORDER_CANCEL)
    assert not actor_has_permission(emergency, AdminApiPermission.SPOT_RECOVERY_EXECUTE)
    assert not actor_has_permission(emergency, AdminApiPermission.SPOT_RECOVERY_RECORD)
    assert actor_has_permission(emergency, AdminApiPermission.RUNTIME_SHUTDOWN)


@pytest.mark.regression
def test_admin_api_admin_read_routes_return_backend_contracts(monkeypatch):
    client = _client(monkeypatch)
    headers = _headers(roles=AdminApiRole.VIEWER.value)

    bootstrap = client.get("/api/v1/admin/bootstrap", headers=headers)
    health = client.get("/api/v1/admin/health", headers=headers)
    session = client.get("/api/v1/admin/session", headers=headers)
    capabilities = client.get("/api/v1/admin/capabilities", headers=headers)
    csrf = client.get("/api/v1/admin/csrf", headers=headers)
    live_enablement = client.get("/api/v1/admin/live-enablement", headers=headers)
    enterprise_readiness = client.get(
        "/api/v1/admin/enterprise-readiness",
        headers=headers,
    )
    release_gate = client.get("/api/v1/admin/release-gate", headers=headers)
    recovery_gate = client.get("/api/v1/admin/recovery-gate", headers=headers)
    fill_ledger_health = client.get(
        "/api/v1/admin/fill-ledger-health",
        headers=headers,
    )
    spot_recovery_preview = client.get(
        "/api/v1/spot/recovery/preview?client_order_id=client-order-mock",
        headers=headers,
    )
    frontend_fixtures = client.get(
        "/api/v1/admin/frontend-fixtures",
        headers=headers,
    )

    assert bootstrap.status_code == 200
    assert bootstrap.json()["backend_repository"] == "s-aws/coinbase"
    assert bootstrap.json()["mutating_routes_live_disabled"] is True
    assert bootstrap.json()["live_coinbase_orders_ran"] is False
    assert bootstrap.json()["auth_mode"] == AdminApiAuthMode.BOOTSTRAP_BEARER.value
    assert health.status_code == 200
    assert health.json()["failed_route_count"] == 0
    assert health.json()["live_coinbase_orders_ran"] is False
    assert session.status_code == 200
    assert AdminApiPermission.AUDIT_READ.value in session.json()["permissions"]
    assert session.json()["auth_mode"] == AdminApiAuthMode.BOOTSTRAP_BEARER.value
    assert session.json()["bearer_token_visible_to_browser"] is False
    assert capabilities.status_code == 200
    routes = {item["route"] for item in capabilities.json()["capabilities"]}
    assert "/api/v1/spot/campaign/executions" in routes
    assert "/api/v1/spot/sweep/automation-runs" in routes
    assert "/api/v1/admin/bootstrap" in routes
    assert "/api/v1/admin/csrf" in routes
    assert "/api/v1/admin/live-enablement" in routes
    assert "/api/v1/admin/enterprise-readiness" in routes
    route_modules = {
        item["route"]: item["module_id"]
        for item in capabilities.json()["capabilities"]
    }
    assert route_modules["/api/v1/admin/bootstrap"] == "admin_system_health"
    assert route_modules["/api/v1/spot/readiness"] == "spot_operations"
    assert route_modules["/api/v1/spot/recovery/preview"] == "spot_operations"
    assert route_modules["/api/v1/futures/account"] == "futures_perpetuals"
    assert route_modules["/api/v1/stealth/orders"] == "stealth_orders"
    assert (
        route_modules["/api/v1/movement-repricing/evidence"]
        == "movement_repricing"
    )
    assert route_modules["/api/v1/admin/guard-risk-policy"] == "guard_risk_policy"
    assert route_modules["/api/v1/admin/audit-workbench"] == "audit_workbench"
    command_capabilities = {
        (item["method"], item["route"]): item
        for item in capabilities.json()["capabilities"]
        if item["command_contract"]
    }
    assert command_capabilities[("POST", "/api/v1/orders")] == {
        "module_id": "spot_operations",
        "route": "/api/v1/orders",
        "method": "POST",
        "action_class": AdminApiActionClass.LIVE_EXCHANGE_PLACE.value,
        "permission": AdminApiPermission.ORDER_CREATE.value,
        "availability": "live_disabled",
        "live_enabled": False,
        "frontend_safe": True,
        "shared_method": "place_manual_order",
        "idempotency": "required",
        "approval": "required",
        "caps": "required",
        "audit": "required",
        "command_contract": True,
        "compatibility_mode": None,
        "parity_test": "HTTP vs place_order guard/result parity",
        "notes": "Backend-owned Admin API route",
    }
    assert command_capabilities[
        ("POST", "/api/v1/orders/{client_order_id}/cancel")
    ]["shared_method"] == "cancel_order_by_client_order_id"
    assert command_capabilities[
        ("POST", "/api/v1/orders/{client_order_id}/cancel")
    ]["module_id"] == "spot_operations"
    assert command_capabilities[
        ("POST", "/api/v1/spot/campaign/executions")
    ]["permission"] == AdminApiPermission.CAMPAIGN_EXECUTE.value
    assert command_capabilities[
        ("POST", "/api/v1/spot/sweep/automation-runs")
    ]["permission"] == AdminApiPermission.SPOT_SWEEP_EXECUTE.value
    assert command_capabilities[
        ("POST", "/api/v1/spot/sweep/automation-runs")
    ]["shared_method"] == "run_spot_sweep_automation"
    assert csrf.status_code == 200
    assert csrf.json() == {
        "type": "admin_csrf_contract",
        "csrf_required": False,
        "csrf_header_name": "X-CSRF-Token",
        "token_issued_by_backend": False,
        "token_visible_to_browser": False,
        "token_source": "session_or_bff_boundary",
        "rotation_policy": "rotate_on_session_or_deploy_secret_change",
        "live_coinbase_orders_ran": False,
    }
    assert live_enablement.status_code == 200
    live_payload = live_enablement.json()
    assert live_payload["type"] == "admin_live_enablement"
    assert live_payload["status"] == "live_disabled"
    assert live_payload["approved_phase_range"] == "2141-2160"
    assert live_payload["default_live_coinbase_execution"] == "not_run"
    assert live_payload["submitted_notional_usdc"] == "0"
    assert live_payload["executed_notional_usdc"] == "0"
    assert live_payload["max_submitted_notional_usdc"] == "3.10"
    assert live_payload["max_executed_notional_usdc"] == "1.00"
    assert live_payload["live_enabled_path_count"] == 0
    assert live_payload["live_eligible_path_count"] == 0
    assert live_payload["preflight_check_count"] == 64
    assert live_payload["blocking_preflight_check_count"] == 32
    assert live_payload["passed_preflight_check_count"] == 32
    assert live_payload["approval_snapshot_required_count"] == 8
    assert live_payload["approval_snapshot_present_count"] == 0
    assert live_payload["approval_snapshot_missing_count"] == 8
    assert live_payload["approval_snapshot_required_field_count"] == 120
    assert live_payload["approval_snapshot_missing_field_count"] == 120
    assert live_payload["approval_store_required_count"] == 8
    assert live_payload["approval_store_configured_count"] == 8
    assert live_payload["approval_store_missing_count"] == 0
    assert live_payload["approval_store_requirement_count"] == 96
    assert live_payload["approval_store_missing_requirement_count"] == 0
    assert live_payload["admission_audit_required_count"] == 8
    assert live_payload["admission_audit_configured_count"] == 0
    assert live_payload["admission_audit_missing_count"] == 8
    assert live_payload["admission_audit_fact_count"] == 80
    assert live_payload["admission_audit_missing_fact_count"] == 72
    assert live_payload["cap_guard_required_count"] == 8
    assert live_payload["cap_guard_configured_count"] == 0
    assert live_payload["cap_guard_missing_count"] == 8
    assert live_payload["cap_guard_requirement_count"] == 112
    assert live_payload["cap_guard_missing_requirement_count"] == 112
    assert live_payload["live_execution_adapter_required_count"] == 8
    assert live_payload["live_execution_adapter_configured_count"] == 1
    assert live_payload["live_execution_adapter_missing_count"] == 7
    assert live_payload["readiness_precondition_count"] == 72
    assert live_payload["blocking_readiness_precondition_count"] == 47
    assert live_payload["passed_readiness_precondition_count"] == 25
    assert live_payload["live_coinbase_orders_ran"] is False
    live_routes = {item["route"]: item for item in live_payload["paths"]}
    assert "/api/v1/orders" in live_routes
    assert "/api/v1/orders/{client_order_id}/cancel" in live_routes
    assert "/api/v1/stealth/orders/{stealth_order_id}/reveal" in live_routes
    assert "/api/v1/stealth/orders/{stealth_order_id}/move" in live_routes
    assert "/api/v1/stealth/orders/{stealth_order_id}/cancel" in live_routes
    assert (
        "/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice"
        in live_routes
    )
    assert "/api/v1/spot/campaign/executions" in live_routes
    assert "/api/v1/spot/sweep/automation-runs" in live_routes
    assert (
        live_routes["/api/v1/spot/sweep/automation-runs"]["identity_key"]
        == "sweep_config_id"
    )
    assert all(item["live_enabled"] is False for item in live_routes.values())
    assert live_routes["/api/v1/orders"]["status"] == "approval_required"
    assert all(
        item["status"] == "live_disabled"
        for route, item in live_routes.items()
        if route != "/api/v1/orders"
    )
    assert all(item["governance_status"] == "blocked" for item in live_routes.values())
    assert all(item["browser_authority"] == "display_only" for item in live_routes.values())
    assert all(item["capability_source"] == "GET /api/v1/admin/capabilities" for item in live_routes.values())
    assert all(item["readiness_source"] == "GET /api/v1/admin/enterprise-readiness" for item in live_routes.values())
    assert all(item["idempotency_key_required"] is True for item in live_routes.values())
    assert all(item["operator_intent_required"] is True for item in live_routes.values())
    assert all(item["payload_hash_required"] is True for item in live_routes.values())
    assert all(item["request_id_required"] is True for item in live_routes.values())
    assert all(item["audit_id_required"] is True for item in live_routes.values())
    assert all(item["reconciliation_blockers"] for item in live_routes.values())
    assert all(len(item["preflight_checks"]) == 8 for item in live_routes.values())
    assert all(
        item["approval_snapshot"]["status"] == "blocked"
        for item in live_routes.values()
    )
    assert all(
        item["approval_snapshot"]["required"] is True
        for item in live_routes.values()
    )
    assert all(
        item["approval_snapshot"]["present"] is False
        for item in live_routes.values()
    )
    assert all(
        item["approval_snapshot"]["durable"] is False
        for item in live_routes.values()
    )
    assert all(
        item["approval_snapshot"]["route_specific"] is True
        for item in live_routes.values()
    )
    assert all(
        item["approval_snapshot"]["backend_owned"] is True
        for item in live_routes.values()
    )
    assert all(
        item["approval_snapshot"]["browser_authority"] == "display_only"
        for item in live_routes.values()
    )
    assert all(
        item["approval_snapshot"]["required_field_count"] == 15
        for item in live_routes.values()
    )
    assert all(
        item["approval_snapshot"]["missing_required_field_count"] == 15
        for item in live_routes.values()
    )
    assert all(
        len(item["approval_snapshot"]["required_fields"]) == 15
        for item in live_routes.values()
    )
    assert all(
        item["approval_store_contract"]["status"] == "passed"
        for item in live_routes.values()
    )
    assert all(
        item["approval_store_contract"]["required"] is True
        for item in live_routes.values()
    )
    assert all(
        item["approval_store_contract"]["configured"] is True
        for item in live_routes.values()
    )
    assert all(
        item["approval_store_contract"]["durable"] is True
        for item in live_routes.values()
    )
    assert all(
        item["approval_store_contract"]["backend_owned"] is True
        for item in live_routes.values()
    )
    assert all(
        item["approval_store_contract"]["browser_authority"] == "display_only"
        for item in live_routes.values()
    )
    assert all(
        item["approval_store_contract"]["requirement_count"] == 12
        for item in live_routes.values()
    )
    assert all(
        item["approval_store_contract"]["missing_requirement_count"] == 0
        for item in live_routes.values()
    )
    assert all(
        len(item["approval_store_contract"]["requirements"]) == 12
        for item in live_routes.values()
    )
    assert all(
        item["admission_audit_trail"]["status"] == "blocked"
        for item in live_routes.values()
    )
    assert all(
        item["admission_audit_trail"]["required"] is True
        for item in live_routes.values()
    )
    assert all(
        item["admission_audit_trail"]["configured"] is False
        for item in live_routes.values()
    )
    assert all(
        item["admission_audit_trail"]["append_only"] is True
        for item in live_routes.values()
    )
    assert all(
        item["admission_audit_trail"]["backend_owned"] is True
        for item in live_routes.values()
    )
    assert all(
        item["admission_audit_trail"]["browser_authority"] == "display_only"
        for item in live_routes.values()
    )
    assert all(
        item["admission_audit_trail"]["fact_count"] == 10
        for item in live_routes.values()
    )
    assert all(
        item["admission_audit_trail"]["missing_fact_count"] == 9
        for item in live_routes.values()
    )
    assert all(
        len(item["admission_audit_trail"]["facts"]) == 10
        for item in live_routes.values()
    )
    assert all(
        item["cap_guard_contract"]["status"] == "blocked"
        for item in live_routes.values()
    )
    assert all(
        item["cap_guard_contract"]["required"] is True
        for item in live_routes.values()
    )
    assert all(
        item["cap_guard_contract"]["configured"] is False
        for item in live_routes.values()
    )
    assert all(
        item["cap_guard_contract"]["route_specific"] is True
        for item in live_routes.values()
    )
    assert all(
        item["cap_guard_contract"]["backend_owned"] is True
        for item in live_routes.values()
    )
    assert all(
        item["cap_guard_contract"]["browser_authority"] == "display_only"
        for item in live_routes.values()
    )
    assert all(
        item["cap_guard_contract"]["requirement_count"] == 14
        for item in live_routes.values()
    )
    assert all(
        item["cap_guard_contract"]["missing_requirement_count"] == 14
        for item in live_routes.values()
    )
    assert all(
        len(item["cap_guard_contract"]["requirements"]) == 14
        for item in live_routes.values()
    )
    assert live_routes["/api/v1/orders"]["live_execution_adapter"]["status"] == (
        "approval_required"
    )
    assert all(
        item["live_execution_adapter"]["status"] == "live_disabled"
        for route, item in live_routes.items()
        if route != "/api/v1/orders"
    )
    assert all(
        item["live_execution_adapter"]["required"] is True
        for item in live_routes.values()
    )
    assert live_routes["/api/v1/orders"]["live_execution_adapter"]["configured"] is True
    assert all(
        item["live_execution_adapter"]["configured"] is False
        for route, item in live_routes.items()
        if route != "/api/v1/orders"
    )
    assert all(
        item["live_execution_adapter"]["backend_owned"] is True
        for item in live_routes.values()
    )
    assert all(
        item["live_execution_adapter"]["route_bound"] is True
        for item in live_routes.values()
    )
    assert all(
        item["live_execution_adapter"]["executable"] is False
        for item in live_routes.values()
    )
    assert all(
        item["live_execution_adapter"]["browser_authority"] == "display_only"
        for item in live_routes.values()
    )
    assert all(
        item["live_execution_adapter"]["bff_authority"] == "forward_only_no_execution"
        for item in live_routes.values()
    )
    assert live_routes["/api/v1/orders"]["live_execution_adapter"]["source"] == (
        "m53_backend_pilot_dry_run"
    )
    assert live_routes["/api/v1/orders"]["live_execution_adapter"]["missing_reason"] == (
        "pilot_dry_run_only"
    )
    assert all(
        item["live_execution_adapter"]["source"] == "disabled_backend_service"
        for route, item in live_routes.items()
        if route != "/api/v1/orders"
    )
    assert all(
        item["live_execution_adapter"]["missing_reason"] == "live_execution_disabled"
        for route, item in live_routes.items()
        if route != "/api/v1/orders"
    )
    assert all(
        item["live_execution_adapter"]["forbidden_methods"]
        == ["create_order", "cancel_order", "execute", "submit", "coinbase_client"]
        for item in live_routes.values()
    )
    assert all(
        len(item["readiness_preconditions"]) == 9
        for item in live_routes.values()
    )
    assert all(
        item["readiness_precondition_count"] == 9
        for item in live_routes.values()
    )
    assert live_routes["/api/v1/orders"]["blocking_readiness_precondition_count"] == 5
    assert live_routes["/api/v1/orders"]["passed_readiness_precondition_count"] == 4
    assert all(
        item["blocking_readiness_precondition_count"] == 6
        for route, item in live_routes.items()
        if route != "/api/v1/orders"
    )
    assert all(
        item["passed_readiness_precondition_count"] == 3
        for route, item in live_routes.items()
        if route != "/api/v1/orders"
    )
    assert all(
        precondition["browser_authority"] == "display_only"
        for item in live_routes.values()
        for precondition in item["readiness_preconditions"]
    )
    assert all(
        precondition["bff_authority"] == "forward_only_no_execution"
        for item in live_routes.values()
        for precondition in item["readiness_preconditions"]
    )
    assert all(
        item["blocking_preflight_check_count"] == 4
        for item in live_routes.values()
    )
    assert all(
        item["passed_preflight_check_count"] == 4
        for item in live_routes.values()
    )
    assert live_routes["/api/v1/orders"]["module_id"] == "spot_operations"
    assert live_routes["/api/v1/orders"]["module"] == "Spot Operations"
    assert live_routes["/api/v1/orders"]["module_owner"] == "strategy"
    assert live_routes["/api/v1/orders"]["identity_key"] == "client_order_id"
    assert "Spot-only wallet" in live_routes["/api/v1/orders"]["spot_rule_boundary"]
    spot_adapter = live_routes["/api/v1/orders"]["live_execution_adapter"]
    assert spot_adapter["route"] == "/api/v1/orders"
    assert spot_adapter["method"] == "POST"
    assert spot_adapter["module_id"] == "spot_operations"
    assert spot_adapter["service_method"] == "place_manual_order"
    assert spot_adapter["adapter_reference"] == "AdminApiCommandService.place_manual_order"
    assert spot_adapter["action_class"] == "live_exchange_place"
    assert spot_adapter["configured"] is True
    assert spot_adapter["status"] == "approval_required"
    assert spot_adapter["source"] == "m53_backend_pilot_dry_run"
    assert spot_adapter["missing_reason"] == "pilot_dry_run_only"
    assert "non-executable" in spot_adapter["detail"]
    spot_readiness = {
        precondition["precondition"]: precondition
        for precondition in live_routes["/api/v1/orders"]["readiness_preconditions"]
    }
    assert set(spot_readiness) == {
        "approval_store_contract",
        "approval_snapshot",
        "admission_audit_trail",
        "cap_guard_contract",
        "reconciliation_plan",
        "live_execution_adapter",
        "execution_intent_envelope",
        "browser_bff_boundary",
        "live_execution_service",
    }
    assert spot_readiness["approval_store_contract"]["status"] == "passed"
    assert spot_readiness["approval_store_contract"]["configured"] is True
    assert spot_readiness["approval_store_contract"]["blocking"] is False
    assert spot_readiness["approval_store_contract"]["blocker"] is None
    assert spot_readiness["approval_snapshot"]["status"] == "blocked"
    assert spot_readiness["approval_snapshot"]["configured"] is False
    assert spot_readiness["approval_snapshot"]["blocking"] is True
    assert spot_readiness["approval_snapshot"]["blocker"] == "approval_snapshot_missing"
    assert spot_readiness["admission_audit_trail"]["blocker"] == "admission_audit_missing"
    assert spot_readiness["cap_guard_contract"]["blocker"] == "cap_guard_missing"
    assert spot_readiness["reconciliation_plan"]["blocker"] == "reconciliation_plan_missing"
    assert spot_readiness["live_execution_adapter"]["status"] == "passed"
    assert spot_readiness["live_execution_adapter"]["configured"] is True
    assert spot_readiness["live_execution_adapter"]["blocking"] is False
    assert spot_readiness["live_execution_adapter"]["blocker"] is None
    assert spot_readiness["live_execution_adapter"]["expected_source"] == (
        "AdminApiCommandService.place_manual_order"
    )
    assert spot_readiness["execution_intent_envelope"]["status"] == "passed"
    assert spot_readiness["execution_intent_envelope"]["configured"] is True
    assert spot_readiness["execution_intent_envelope"]["blocking"] is False
    assert spot_readiness["execution_intent_envelope"]["blocker"] is None
    assert spot_readiness["browser_bff_boundary"]["status"] == "passed"
    assert spot_readiness["browser_bff_boundary"]["configured"] is True
    assert spot_readiness["browser_bff_boundary"]["blocking"] is False
    assert spot_readiness["live_execution_service"]["blocker"] == "live_execution_disabled"
    assert spot_readiness["live_execution_service"]["source"] == "disabled_backend_service"
    spot_preflight = {
        check["name"]: check
        for check in live_routes["/api/v1/orders"]["preflight_checks"]
    }
    assert spot_preflight["auth_rbac"]["category"] == "authorization"
    assert spot_preflight["auth_rbac"]["status"] == "passed"
    assert spot_preflight["idempotency_operator_intent"]["status"] == "passed"
    assert spot_preflight["durable_audit"]["status"] == "passed"
    assert spot_preflight["browser_authority"]["status"] == "passed"
    assert spot_preflight["approval_snapshot"]["status"] == "blocked"
    assert spot_preflight["cap_guard_policy"]["status"] == "blocked"
    assert spot_preflight["live_execution_service"]["status"] == "blocked"
    assert spot_preflight["post_live_reconciliation"]["status"] == "blocked"
    assert all(check["required"] is True for check in spot_preflight.values())
    assert all(
        check["blocking"] is (check["status"] == "blocked")
        for check in spot_preflight.values()
    )
    spot_approval = live_routes["/api/v1/orders"]["approval_snapshot"]
    assert spot_approval["source"] == "not_configured"
    assert "route-specific approval snapshot" in spot_approval["detail"]
    spot_approval_fields = {
        field["field"]: field for field in spot_approval["required_fields"]
    }
    assert spot_approval_fields["route"]["expected_value"] == "/api/v1/orders"
    assert spot_approval_fields["route"]["expected_source"] == "route_inventory"
    assert spot_approval_fields["method"]["expected_value"] == "POST"
    assert spot_approval_fields["module_id"]["expected_value"] == "spot_operations"
    assert spot_approval_fields["identity_key"]["expected_value"] == "client_order_id"
    assert spot_approval_fields["identity_value"]["expected_source"] == "command_identity"
    assert spot_approval_fields["action_class"]["expected_value"] == "live_exchange_place"
    assert spot_approval_fields["required_permission"]["expected_value"] == "order:create"
    assert spot_approval_fields["requested_by_actor_id"]["expected_source"] == "authenticated_actor"
    assert spot_approval_fields["approved_by_actor_id"]["expected_source"] == "approval_store"
    assert spot_approval_fields["expires_at"]["expected_source"] == "approval_store"
    assert spot_approval_fields["cap_guard_decision_ref"]["expected_source"] == "guard_risk_policy"
    assert spot_approval_fields["reconciliation_plan_ref"]["expected_source"] == "reconciliation_policy"
    assert all(field["status"] == "blocked" for field in spot_approval_fields.values())
    assert all(field["required"] is True for field in spot_approval_fields.values())
    spot_store = live_routes["/api/v1/orders"]["approval_store_contract"]
    assert spot_store["source"] == "admin_api_approval_store"
    assert "approval store" in spot_store["detail"]
    spot_store_requirements = {
        requirement["requirement"]: requirement
        for requirement in spot_store["requirements"]
    }
    assert spot_store_requirements["backend_owned"]["expected_source"] == "admin_api_approval_store"
    assert spot_store_requirements["route_bound"]["expected_source"] == "admin_api_approval_store"
    assert spot_store_requirements["route_bound"]["expected_value"] == "/api/v1/orders"
    assert spot_store_requirements["method_bound"]["expected_value"] == "POST"
    assert spot_store_requirements["module_bound"]["expected_value"] == "spot_operations"
    assert spot_store_requirements["actor_bound"]["expected_source"] == "admin_api_approval_store"
    assert spot_store_requirements["idempotency_bound"]["expected_source"] == "admin_api_approval_store"
    assert spot_store_requirements["payload_hash_bound"]["expected_source"] == "admin_api_approval_store"
    assert spot_store_requirements["expiring"]["expected_source"] == "admin_api_approval_store"
    assert spot_store_requirements["cap_guard_bound"]["expected_source"] == "admin_api_approval_store"
    assert spot_store_requirements["reconciliation_bound"]["expected_source"] == "admin_api_approval_store"
    assert spot_store_requirements["append_only_audit"]["expected_source"] == "admin_api_approval_store"
    assert spot_store_requirements["browser_authority_rejected"]["expected_value"] == "display_only"
    assert all(
        requirement["status"] == "passed"
        for requirement in spot_store_requirements.values()
    )
    assert all(
        requirement["required"] is True
        for requirement in spot_store_requirements.values()
    )
    spot_admission_audit = live_routes["/api/v1/orders"]["admission_audit_trail"]
    assert spot_admission_audit["source"] == "admin_api_audit_log_partial"
    assert "live-admission audit trail" in spot_admission_audit["detail"]
    spot_admission_facts = {
        fact["fact"]: fact
        for fact in spot_admission_audit["facts"]
    }
    assert spot_admission_facts["route_admission_requested"]["expected_source"] == (
        "route_inventory"
    )
    assert spot_admission_facts["route_admission_requested"]["expected_value"] == (
        "POST /api/v1/orders"
    )
    assert spot_admission_facts["approval_snapshot_linked"]["expected_source"] == (
        "approval_snapshot"
    )
    assert spot_admission_facts["approval_store_decision_linked"]["expected_source"] == (
        "approval_store"
    )
    assert spot_admission_facts["cap_guard_decision_linked"]["expected_source"] == (
        "guard_risk_policy"
    )
    assert spot_admission_facts["payload_hash_linked"]["expected_source"] == (
        "command_service"
    )
    assert spot_admission_facts["identity_key_linked"]["expected_value"] == (
        "client_order_id"
    )
    assert (
        spot_admission_facts["command_admission_decision_recorded"]["expected_value"]
        == "spot_operations"
    )
    assert spot_admission_facts["command_admission_decision_recorded"][
        "expected_source"
    ] == "admin_api_audit_log"
    assert (
        spot_admission_facts["command_admission_decision_recorded"]["status"]
        == "passed"
    )
    assert spot_admission_facts["exchange_submission_linked"]["expected_source"] == (
        "coinbase_adapter"
    )
    assert spot_admission_facts["reconciliation_result_linked"]["expected_source"] == (
        "reconciliation_policy"
    )
    assert (
        spot_admission_facts["browser_authority_rejection_recorded"]["expected_value"]
        == "display_only"
    )
    assert all(
        fact["status"] == "blocked"
        for name, fact in spot_admission_facts.items()
        if name != "command_admission_decision_recorded"
    )
    assert all(
        fact["required"] is True
        for fact in spot_admission_facts.values()
    )
    spot_cap_guard = live_routes["/api/v1/orders"]["cap_guard_contract"]
    assert spot_cap_guard["source"] == "not_configured"
    assert "cap/guard decision contract" in spot_cap_guard["detail"]
    spot_cap_requirements = {
        requirement["requirement"]: requirement
        for requirement in spot_cap_guard["requirements"]
    }
    assert spot_cap_requirements["backend_owned"]["expected_source"] == "guard_risk_policy"
    assert spot_cap_requirements["route_bound"]["expected_value"] == "/api/v1/orders"
    assert spot_cap_requirements["method_bound"]["expected_value"] == "POST"
    assert spot_cap_requirements["module_bound"]["expected_value"] == "spot_operations"
    assert spot_cap_requirements["identity_bound"]["expected_value"] == "client_order_id"
    assert spot_cap_requirements["payload_hash_bound"]["expected_source"] == "command_service"
    assert spot_cap_requirements["idempotency_bound"]["expected_source"] == "command_headers"
    assert spot_cap_requirements["operator_intent_bound"]["expected_source"] == "command_headers"
    assert spot_cap_requirements["notional_cap_bound"]["expected_source"] == "guard_risk_policy"
    assert spot_cap_requirements["notional_cap_bound"]["expected_value"] == "3.10"
    assert spot_cap_requirements["domain_guard_bound"]["expected_source"] == "guard_risk_policy"
    assert "Spot order guard" in spot_cap_requirements["domain_guard_bound"]["detail"]
    assert spot_cap_requirements["product_scope_bound"]["expected_source"] == "route_inventory"
    assert spot_cap_requirements["approval_snapshot_bound"]["expected_source"] == "approval_snapshot"
    assert spot_cap_requirements["admission_audit_bound"]["expected_source"] == "admission_audit_trail"
    assert spot_cap_requirements["browser_authority_rejected"]["expected_value"] == "display_only"
    assert all(
        requirement["status"] == "blocked"
        for requirement in spot_cap_requirements.values()
    )
    assert all(
        requirement["required"] is True
        for requirement in spot_cap_requirements.values()
    )
    assert live_routes["/api/v1/stealth/orders/{stealth_order_id}/cancel"]["module_id"] == "stealth_orders"
    assert live_routes["/api/v1/stealth/orders/{stealth_order_id}/cancel"]["identity_key"] == "stealth_order_id"
    assert live_routes["/api/v1/stealth/orders/{stealth_order_id}/move"]["module_id"] == "stealth_orders"
    assert live_routes["/api/v1/stealth/orders/{stealth_order_id}/move"]["identity_key"] == "stealth_order_id"
    assert (
        "active exchange placement reality"
        in " ".join(
            live_routes["/api/v1/stealth/orders/{stealth_order_id}/cancel"][
                "reconciliation_blockers"
            ]
        )
    )
    assert (
        live_routes["/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice"][
            "module_id"
        ]
        == "movement_repricing"
    )
    assert (
        "cancel/replace"
        in " ".join(
            live_routes[
                "/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice"
            ]["reconciliation_blockers"]
        )
    )
    assert live_routes["/api/v1/spot/campaign/executions"]["identity_key"] == "campaign_id"
    assert enterprise_readiness.status_code == 200
    enterprise_payload = enterprise_readiness.json()
    assert enterprise_payload["type"] == "admin_enterprise_readiness"
    assert enterprise_payload["candidate"] == "enterprise_admin_m9"
    assert enterprise_payload["approved_phase_range"] == "2141-2160"
    assert enterprise_payload["status"] == AdminApiGateStatus.WARNING.value
    assert enterprise_payload["frontend_authority"] == "backend_contract_only"
    assert enterprise_payload["live_posture"] == "live_disabled"
    assert enterprise_payload["default_live_coinbase_execution"] == "not_run"
    assert enterprise_payload["submitted_notional_usdc"] == "0"
    assert enterprise_payload["executed_notional_usdc"] == "0"
    assert enterprise_payload["read_only"] is True
    assert enterprise_payload["live_coinbase_orders_ran"] is False
    assert enterprise_payload["command_gap_count"] >= 10
    assert enterprise_payload["module_registry_count"] == enterprise_payload["module_count"]
    assert enterprise_payload["module_action_posture_count"] == enterprise_payload["module_count"]
    assert enterprise_payload["functionality_inventory_count"] == len(
        enterprise_payload["functionality_inventory"]
    )
    assert enterprise_payload["functionality_inventory_count"] >= 14
    assert enterprise_payload["backend_supported_workflow_count"] >= 13
    assert enterprise_payload["admin_exposed_workflow_count"] >= 11
    assert enterprise_payload["command_workflow_count"] >= 6
    assert enterprise_payload["live_designated_workflow_count"] >= 5
    assert enterprise_payload["recovery_workflow_count"] >= 1
    assert enterprise_payload["automation_workflow_count"] >= 1
    assert enterprise_payload["repair_workflow_count"] >= 1
    assert enterprise_payload["mutation_taxonomy_count"] == len(
        enterprise_payload["mutation_taxonomy"]
    )
    assert enterprise_payload["mutation_taxonomy_count"] >= 10
    assert enterprise_payload["route_bound_mutation_taxonomy_count"] >= 8
    assert enterprise_payload["live_disabled_mutation_count"] >= 5
    assert enterprise_payload["backend_contract_required_mutation_count"] >= 2
    assert enterprise_payload["compatibility_mutation_count"] >= 3
    inventory_by_id = {
        item["workflow_id"]: item
        for item in enterprise_payload["functionality_inventory"]
    }
    taxonomy_by_id = {
        item["mutation_id"]: item for item in enterprise_payload["mutation_taxonomy"]
    }
    assert {
        "admin.approval_lifecycle",
        "admin.admission_audits",
        "admin.cap_guard_decisions",
        "admin.reconciliation_plans",
        "spot.manual_order",
        "spot.order_cancel",
        "spot.campaign_execution",
        "stealth.create",
        "stealth.reveal",
        "stealth.move",
        "stealth.cancel",
        "movement.reprice",
        "futures.commands_contract_required",
        "audit.fill_ledger_repair_contract_required",
        "legacy.dashboard_place",
        "legacy.dashboard_hotpoint",
        "legacy.dashboard_cancel",
    } <= set(taxonomy_by_id)
    command_surfaces = [
        item.surface
        for item in ADMIN_API_ROUTE_INVENTORY
        if item.action_class != AdminApiActionClass.READ_ONLY
    ]
    taxonomy_surfaces = [
        surface
        for item in enterprise_payload["mutation_taxonomy"]
        for surface in item["command_surfaces"]
    ]
    assert sorted(taxonomy_surfaces) == sorted(command_surfaces)
    assert len(taxonomy_surfaces) == len(set(taxonomy_surfaces))
    assert {
        "admin.platform_evidence",
        "admin.approval_lifecycle",
        "admin.admission_audits",
        "admin.cap_guard_decisions",
        "admin.reconciliation_plans",
        "spot.read_models",
        "spot.order_command_drafts",
        "spot.sweep_automation_and_live_executor",
        "stealth.lifecycle_reads",
        "stealth.create_command_draft",
        "stealth.reveal_command_draft",
        "stealth.move_command_draft",
        "stealth.cancel_command_draft",
        "movement.repricing_reads",
        "movement.reprice_command_draft",
        "futures.read_models",
        "futures.commands_not_modeled",
        "guard_risk.policy_evidence",
        "audit.recovery_and_repair_evidence",
        "audit.fill_ledger_repair_contract_required",
        "legacy.dashboard_compatibility",
    } <= set(inventory_by_id)
    spot_command_inventory = inventory_by_id["spot.order_command_drafts"]
    assert spot_command_inventory["workflow_type"] == (
        AdminApiFunctionalityWorkflowType.COMMAND_DRAFT.value
    )
    assert spot_command_inventory["exposure_status"] == (
        AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED.value
    )
    assert spot_command_inventory["command_capable"] is True
    assert spot_command_inventory["live_designated"] is True
    assert spot_command_inventory["live_enabled"] is False
    assert spot_command_inventory["live_coinbase_execution"] == "not_run"
    assert "client_order_id" in spot_command_inventory["identity_keys"]
    assert "POST /api/v1/orders/{client_order_id}/cancel" in (
        spot_command_inventory["command_routes"]
    )
    assert "no-shorting" in spot_command_inventory["spot_rule_boundary"]
    stealth_create_inventory = inventory_by_id["stealth.create_command_draft"]
    assert stealth_create_inventory["workflow_type"] == (
        AdminApiFunctionalityWorkflowType.COMMAND_DRAFT.value
    )
    assert stealth_create_inventory["exposure_status"] == (
        AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED.value
    )
    assert stealth_create_inventory["command_capable"] is True
    assert stealth_create_inventory["frontend_exposed"] is True
    assert stealth_create_inventory["live_designated"] is False
    assert "POST /api/v1/stealth/orders" in stealth_create_inventory["command_routes"]
    assert "stealth_order_id" in stealth_create_inventory["identity_keys"]
    stealth_reveal_inventory = inventory_by_id["stealth.reveal_command_draft"]
    assert stealth_reveal_inventory["workflow_type"] == (
        AdminApiFunctionalityWorkflowType.COMMAND_DRAFT.value
    )
    assert stealth_reveal_inventory["exposure_status"] == (
        AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED.value
    )
    assert stealth_reveal_inventory["command_capable"] is True
    assert stealth_reveal_inventory["frontend_exposed"] is True
    assert stealth_reveal_inventory["live_designated"] is True
    assert "POST /api/v1/stealth/orders/{stealth_order_id}/reveal" in (
        stealth_reveal_inventory["command_routes"]
    )
    assert "stealth_order_id" in stealth_reveal_inventory["identity_keys"]
    stealth_move_inventory = inventory_by_id["stealth.move_command_draft"]
    assert stealth_move_inventory["workflow_type"] == (
        AdminApiFunctionalityWorkflowType.COMMAND_DRAFT.value
    )
    assert stealth_move_inventory["exposure_status"] == (
        AdminApiFunctionalityExposureStatus.ADMIN_DRAFT_LIVE_DISABLED.value
    )
    assert stealth_move_inventory["command_capable"] is True
    assert stealth_move_inventory["frontend_exposed"] is True
    assert stealth_move_inventory["live_designated"] is True
    assert "POST /api/v1/stealth/orders/{stealth_order_id}/move" in (
        stealth_move_inventory["command_routes"]
    )
    assert "stealth_order_id" in stealth_move_inventory["identity_keys"]
    stealth_create_taxonomy = taxonomy_by_id["stealth.create"]
    assert stealth_create_taxonomy["mutation_family"] == (
        AdminApiMutationFamilyType.STEALTH_CREATE.value
    )
    assert stealth_create_taxonomy["action_classes"] == [
        AdminApiActionClass.LOCAL_STATE_MUTATION.value
    ]
    assert "POST /api/v1/stealth/orders" in stealth_create_taxonomy["command_surfaces"]
    assert "stealth_manager_invocation_disabled" in stealth_create_taxonomy["blockers"]
    stealth_move_taxonomy = taxonomy_by_id["stealth.move"]
    assert stealth_move_taxonomy["mutation_family"] == (
        AdminApiMutationFamilyType.STEALTH_MOVE.value
    )
    assert stealth_move_taxonomy["action_classes"] == [
        AdminApiActionClass.LIVE_EXCHANGE_CANCEL.value
    ]
    assert "POST /api/v1/stealth/orders/{stealth_order_id}/move" in (
        stealth_move_taxonomy["command_surfaces"]
    )
    assert "stealth_move_cancel_replace_adapter_missing" in (
        stealth_move_taxonomy["blockers"]
    )
    approval_inventory = inventory_by_id["admin.approval_lifecycle"]
    assert approval_inventory["workflow_type"] == (
        AdminApiFunctionalityWorkflowType.COMMAND_DRAFT.value
    )
    assert approval_inventory["exposure_status"] == (
        AdminApiFunctionalityExposureStatus.ADMIN_EXPOSED.value
    )
    assert approval_inventory["command_capable"] is True
    assert approval_inventory["live_designated"] is False
    assert "POST /api/v1/admin/approvals/requests" in (
        approval_inventory["command_routes"]
    )
    assert "browser may request" in approval_inventory["frontend_boundary"]
    admission_audit_inventory = inventory_by_id["admin.admission_audits"]
    assert admission_audit_inventory["workflow_type"] == (
        AdminApiFunctionalityWorkflowType.COMMAND_DRAFT.value
    )
    assert admission_audit_inventory["exposure_status"] == (
        AdminApiFunctionalityExposureStatus.ADMIN_EXPOSED.value
    )
    assert admission_audit_inventory["command_capable"] is True
    assert admission_audit_inventory["live_designated"] is False
    assert "POST /api/v1/admin/admission-audits" in (
        admission_audit_inventory["command_routes"]
    )
    assert "must not write browser audit history" in (
        admission_audit_inventory["frontend_boundary"]
    )
    cap_guard_inventory = inventory_by_id["admin.cap_guard_decisions"]
    assert cap_guard_inventory["workflow_type"] == (
        AdminApiFunctionalityWorkflowType.COMMAND_DRAFT.value
    )
    assert cap_guard_inventory["exposure_status"] == (
        AdminApiFunctionalityExposureStatus.ADMIN_EXPOSED.value
    )
    assert cap_guard_inventory["command_capable"] is True
    assert cap_guard_inventory["live_designated"] is False
    assert "POST /api/v1/admin/cap-guard/decisions" in (
        cap_guard_inventory["command_routes"]
    )
    assert "must not evaluate wallet" in cap_guard_inventory["frontend_boundary"]
    reconciliation_inventory = inventory_by_id["admin.reconciliation_plans"]
    assert reconciliation_inventory["workflow_type"] == (
        AdminApiFunctionalityWorkflowType.COMMAND_DRAFT.value
    )
    assert reconciliation_inventory["exposure_status"] == (
        AdminApiFunctionalityExposureStatus.ADMIN_EXPOSED.value
    )
    assert reconciliation_inventory["command_capable"] is True
    assert reconciliation_inventory["live_designated"] is False
    assert "POST /api/v1/admin/reconciliation/plans" in (
        reconciliation_inventory["command_routes"]
    )
    assert "must not execute reconciliation" in (
        reconciliation_inventory["frontend_boundary"]
    )
    futures_command_inventory = inventory_by_id["futures.commands_not_modeled"]
    assert futures_command_inventory["exposure_status"] == (
        AdminApiFunctionalityExposureStatus.BACKEND_CONTRACT_REQUIRED.value
    )
    assert futures_command_inventory["support_status"] == (
        AdminApiModuleSupportStatus.NOT_MODELED.value
    )
    assert futures_command_inventory["admin_api_exposed"] is False
    assert futures_command_inventory["frontend_exposed"] is False
    assert "Spot rules are forbidden" in futures_command_inventory[
        "spot_rule_boundary"
    ]
    legacy_inventory = inventory_by_id["legacy.dashboard_compatibility"]
    assert legacy_inventory["exposure_status"] == (
        AdminApiFunctionalityExposureStatus.COMPATIBILITY_ONLY.value
    )
    assert legacy_inventory["admin_api_exposed"] is False
    assert legacy_inventory["live_designated"] is True
    assert "place_order WebSocket" in legacy_inventory["legacy_surfaces"]
    repair_inventory = inventory_by_id[
        "audit.fill_ledger_repair_contract_required"
    ]
    assert repair_inventory["workflow_type"] == (
        AdminApiFunctionalityWorkflowType.REPAIR.value
    )
    assert repair_inventory["exposure_status"] == (
        AdminApiFunctionalityExposureStatus.BACKEND_CONTRACT_REQUIRED.value
    )
    assert "Admin API repair mutation contract missing" in repair_inventory[
        "blockers"
    ]
    spot_cancel_taxonomy = taxonomy_by_id["spot.order_cancel"]
    assert spot_cancel_taxonomy["mutation_family"] == (
        AdminApiMutationFamilyType.SPOT_ORDER_CANCEL.value
    )
    assert spot_cancel_taxonomy["workflow_id"] == "spot.order_command_drafts"
    assert spot_cancel_taxonomy["command_surfaces"] == [
        "POST /api/v1/orders/{client_order_id}/cancel"
    ]
    assert spot_cancel_taxonomy["required_permissions"] == ["order:cancel"]
    assert spot_cancel_taxonomy["identity_keys"] == ["client_order_id"]
    assert spot_cancel_taxonomy["idempotency_required"] is True
    assert spot_cancel_taxonomy["rbac_required"] is True
    assert spot_cancel_taxonomy["approval_required"] is True
    assert spot_cancel_taxonomy["cap_guard_required"] is True
    assert spot_cancel_taxonomy["admission_audit_required"] is True
    assert spot_cancel_taxonomy["reconciliation_required"] is True
    assert spot_cancel_taxonomy["route_local_execution_allowed"] is False
    assert spot_cancel_taxonomy["browser_authority"] == "display_only"
    assert "cancel_order(client_order_id)" in spot_cancel_taxonomy["summary"]
    assert "exchange order_id" in spot_cancel_taxonomy["frontend_boundary"]
    approval_taxonomy = taxonomy_by_id["admin.approval_lifecycle"]
    assert approval_taxonomy["mutation_family"] == (
        AdminApiMutationFamilyType.ADMIN_APPROVAL_LIFECYCLE.value
    )
    assert approval_taxonomy["workflow_id"] == "admin.approval_lifecycle"
    assert approval_taxonomy["command_surfaces"] == [
        "POST /api/v1/admin/approvals/requests",
        "POST /api/v1/admin/approvals/requests/{approval_request_id}/decisions",
        "POST /api/v1/admin/approvals/{approval_id}/revoke",
    ]
    assert approval_taxonomy["action_classes"] == ["local_state_mutation"] * 3
    assert approval_taxonomy["required_permissions"] == [
        "approval:request",
        "approval:manage",
        "approval:manage",
    ]
    assert approval_taxonomy["live_adapter_required"] is False
    assert approval_taxonomy["route_local_execution_allowed"] is False
    assert "must not become approval authority" in approval_taxonomy[
        "frontend_boundary"
    ]
    admission_audit_taxonomy = taxonomy_by_id["admin.admission_audits"]
    assert admission_audit_taxonomy["mutation_family"] == (
        AdminApiMutationFamilyType.ADMIN_ADMISSION_AUDIT.value
    )
    assert admission_audit_taxonomy["workflow_id"] == "admin.admission_audits"
    assert admission_audit_taxonomy["command_surfaces"] == [
        "POST /api/v1/admin/admission-audits",
    ]
    assert admission_audit_taxonomy["action_classes"] == ["local_state_mutation"]
    assert admission_audit_taxonomy["required_permissions"] == [
        "admission_audit:record"
    ]
    assert admission_audit_taxonomy["live_adapter_required"] is False
    assert admission_audit_taxonomy["route_local_execution_allowed"] is False
    assert "must not create audit proof" in admission_audit_taxonomy["bff_boundary"]
    cap_guard_taxonomy = taxonomy_by_id["admin.cap_guard_decisions"]
    assert cap_guard_taxonomy["mutation_family"] == (
        AdminApiMutationFamilyType.ADMIN_CAP_GUARD_DECISION.value
    )
    assert cap_guard_taxonomy["workflow_id"] == "admin.cap_guard_decisions"
    assert cap_guard_taxonomy["command_surfaces"] == [
        "POST /api/v1/admin/cap-guard/decisions",
    ]
    assert cap_guard_taxonomy["action_classes"] == ["local_state_mutation"]
    assert cap_guard_taxonomy["required_permissions"] == ["cap_guard:record"]
    assert cap_guard_taxonomy["live_adapter_required"] is False
    assert cap_guard_taxonomy["route_local_execution_allowed"] is False
    assert "must not evaluate or override" in cap_guard_taxonomy["bff_boundary"]
    assert "Spot wallet" in cap_guard_taxonomy["spot_rule_boundary"]
    reconciliation_taxonomy = taxonomy_by_id["admin.reconciliation_plans"]
    assert reconciliation_taxonomy["mutation_family"] == (
        AdminApiMutationFamilyType.ADMIN_RECONCILIATION_PLAN.value
    )
    assert reconciliation_taxonomy["workflow_id"] == "admin.reconciliation_plans"
    assert reconciliation_taxonomy["command_surfaces"] == [
        "POST /api/v1/admin/reconciliation/plans",
    ]
    assert reconciliation_taxonomy["action_classes"] == ["local_state_mutation"]
    assert reconciliation_taxonomy["required_permissions"] == [
        "reconciliation:record"
    ]
    assert reconciliation_taxonomy["live_adapter_required"] is False
    assert reconciliation_taxonomy["route_local_execution_allowed"] is False
    assert "must not create reconciliation proof" in (
        reconciliation_taxonomy["bff_boundary"]
    )
    assert "Spot fill-ledger" in reconciliation_taxonomy["spot_rule_boundary"]
    futures_taxonomy = taxonomy_by_id["futures.commands_contract_required"]
    assert futures_taxonomy["exposure_status"] == (
        AdminApiFunctionalityExposureStatus.BACKEND_CONTRACT_REQUIRED.value
    )
    assert futures_taxonomy["command_surfaces"] == []
    assert futures_taxonomy["idempotency_required"] is False
    assert futures_taxonomy["approval_required"] is False
    assert "backend futures command contract missing" in futures_taxonomy["blockers"]
    assert "Spot rules are forbidden" in futures_taxonomy["spot_rule_boundary"]
    repair_taxonomy = taxonomy_by_id["audit.fill_ledger_repair_contract_required"]
    assert repair_taxonomy["mutation_family"] == (
        AdminApiMutationFamilyType.FILL_LEDGER_REPAIR_CONTRACT_REQUIRED.value
    )
    assert repair_taxonomy["action_classes"] == ["local_state_mutation"]
    assert repair_taxonomy["required_permissions"] == ["config:update"]
    assert repair_taxonomy["command_surfaces"] == []
    assert "preview/apply" in repair_taxonomy["frontend_boundary"]
    legacy_taxonomy = taxonomy_by_id["legacy.dashboard_place"]
    assert legacy_taxonomy["exposure_status"] == (
        AdminApiFunctionalityExposureStatus.COMPATIBILITY_ONLY.value
    )
    assert legacy_taxonomy["command_surfaces"] == ["place_order WebSocket"]
    assert legacy_taxonomy["required_permissions"] == ["compatibility policy"]
    assert "compatibility-only surface" in legacy_taxonomy["blockers"]
    assert "must not call legacy dashboard" in legacy_taxonomy["frontend_boundary"]
    registry_by_id = {
        item["module_id"]: item for item in enterprise_payload["modules"]
    }
    assert set(registry_by_id) == {
        "admin_system_health",
        "spot_operations",
        "futures_perpetuals",
        "stealth_orders",
        "movement_repricing",
        "guard_risk_policy",
        "audit_workbench",
        "legacy_dashboard_websocket",
    }
    for module in enterprise_payload["modules"]:
        assert module["primary_owner"]
        assert module["backend_contract_refs"]
        assert module["frontend_contract_refs"]
        assert module["documentation_refs"]
        assert module["spot_rule_boundary"]
        posture = module["action_posture"]
        assert posture["module_id"] == module["module_id"]
        assert posture["support_status"] == module["support_status"]
        assert posture["read_route_count"] == len(module["read_routes"])
        assert posture["command_route_count"] == len(module["command_routes"])
        assert posture["live_route_count"] == len(module["live_routes"])
        assert posture["evidence_route_count"] == len(module["evidence_routes"])
        assert posture["unsupported_action_count"] == len(module["unsupported_actions"])
        assert posture["command_gap_count"] == len(module["command_gaps"])
        assert posture["route_module_id_status"] == AdminApiGateStatus.PASSED.value
        assert "derived from module_id, not path prefixes" in (
            posture["route_module_id_detail"]
        )
        assert posture["frontend_authority"] == "backend_contract_only"
        assert posture["live_coinbase_execution"] == "not_run"
        assert posture["notional_usdc"] == "0"
    module_statuses = {
        item["module"]: item["support_status"]
        for item in enterprise_payload["modules"]
    }
    assert module_statuses["Admin / System Health"] == (
        AdminApiModuleSupportStatus.PLATFORM_READY.value
    )
    assert module_statuses["Spot Operations"] == (
        AdminApiModuleSupportStatus.COMMAND_DRAFT_LIVE_DISABLED.value
    )
    assert module_statuses["Futures / Perpetuals"] == (
        AdminApiModuleSupportStatus.READ_ONLY_READY.value
    )
    assert module_statuses["Legacy Dashboard WebSocket"] == (
        AdminApiModuleSupportStatus.UNSUPPORTED.value
    )
    assert enterprise_payload["supported_module_count"] >= 7
    assert enterprise_payload["unsupported_module_count"] == 1
    spot_module = next(
        item
        for item in enterprise_payload["modules"]
        if item["module"] == "Spot Operations"
    )
    assert "spot short selling" in spot_module["unsupported_actions"]
    assert "client_order_id" in spot_module["identity_keys"]
    assert "sweep_config_id" in spot_module["identity_keys"]
    assert "POST /api/v1/orders" in spot_module["command_routes"]
    assert "POST /api/v1/spot/sweep/automation-runs" in spot_module["command_routes"]
    assert "POST /api/v1/spot/pnl/checkpoints" in spot_module["command_routes"]
    assert "GET /api/v1/spot/command-suite" in spot_module["read_routes"]
    assert (
        "POST /api/v1/spot/recovery/apply-executions"
        in spot_module["command_routes"]
    )
    assert (
        "POST /api/v1/spot/recovery/rollback-executions"
        in spot_module["command_routes"]
    )
    assert (
        "POST /api/v1/spot/recovery/exchange-state-proofs"
        in spot_module["command_routes"]
    )
    assert (
        "POST /api/v1/spot/recovery/exchange-state-snapshots"
        in spot_module["command_routes"]
    )
    assert (
        "POST /api/v1/spot/recovery/reconciliation-executions"
        in spot_module["command_routes"]
    )
    assert (
        "POST /api/v1/spot/recovery/reconciliation-proofs"
        in spot_module["command_routes"]
    )
    assert "GET /api/v1/spot/recovery/apply-review" in spot_module["read_routes"]
    assert "GET /api/v1/spot/recovery/rollback-plan" in spot_module["read_routes"]
    assert (
        "GET /api/v1/spot/recovery/reconciliation-proof"
        in spot_module["read_routes"]
    )
    assert "GET /api/v1/spot/pnl/checkpoints" in spot_module["read_routes"]
    assert (
        "GET /api/v1/spot/pnl/checkpoints/{checkpoint_id}"
        in spot_module["read_routes"]
    )
    assert spot_module["action_posture"]["read_route_count"] == 15
    assert spot_module["action_posture"]["command_route_count"] == 11
    assert spot_module["action_posture"]["live_route_count"] == 4
    assert spot_module["action_posture"]["command_gap_count"] == 2
    admin_module = registry_by_id["admin_system_health"]
    assert "GET /api/v1/admin/guard-risk-policy" not in admin_module["read_routes"]
    assert "GET /api/v1/admin/audit-workbench" not in admin_module["read_routes"]
    assert "GET /api/v1/admin/approvals" in admin_module["read_routes"]
    assert "POST /api/v1/admin/approvals/requests" in admin_module["command_routes"]
    assert admin_module["action_posture"]["read_route_count"] == 20
    assert admin_module["action_posture"]["command_route_count"] == 6
    assert registry_by_id["guard_risk_policy"]["read_routes"] == [
        "GET /api/v1/admin/guard-risk-policy"
    ]
    assert registry_by_id["guard_risk_policy"]["action_posture"][
        "read_route_count"
    ] == 1
    assert registry_by_id["audit_workbench"]["read_routes"] == [
        "GET /api/v1/admin/audit-workbench"
    ]
    assert registry_by_id["audit_workbench"]["action_posture"][
        "read_route_count"
    ] == 1
    assert registry_by_id["legacy_dashboard_websocket"]["action_posture"][
        "command_route_count"
    ] == 3
    futures_module = next(
        item
        for item in enterprise_payload["modules"]
        if item["module"] == "Futures / Perpetuals"
    )
    assert futures_module["module_id"] == "futures_perpetuals"
    assert futures_module["primary_owner"] == "admin_api_contract"
    assert "forbidden" in futures_module["spot_rule_boundary"]
    assert "margin" in futures_module["spot_rule_boundary"]
    assert "README.futures-perpetuals.md" in futures_module["documentation_refs"]
    futures_gaps = {
        item["action"]: item for item in futures_module["command_gaps"]
    }
    assert futures_gaps["frontend futures placement"] == {
        "action": "frontend futures placement",
        "status": AdminApiModuleSupportStatus.NOT_MODELED.value,
        "reason": "Futures/perpetual placement needs backend-owned margin, leverage, liquidation, reduce-only, collateral, and approval contracts before UI drafting.",
        "required_backend_contract": "POST futures/perpetual placement contract with margin, leverage, liquidation, reduce-only, cap, approval, audit, and reconciliation evidence.",
        "frontend_boundary": "Do not add a futures/perpetual placement draft, dry-submit, or BFF route until the backend contract and capability row exist.",
        "live_coinbase_execution": "not_run",
        "notional_usdc": "0",
    }
    assert futures_gaps["frontend futures cancel/close/reduce"]["status"] == (
        AdminApiModuleSupportStatus.NOT_MODELED.value
    )
    assert futures_gaps["frontend futures cancel/close/reduce"]["notional_usdc"] == "0"
    assert "spot inventory" in futures_gaps["spot inventory rules in futures workflows"][
        "frontend_boundary"
    ]
    assert all(check["status"] == "passed" for check in enterprise_payload["security_checks"])
    browser_boundary = next(
        check
        for check in enterprise_payload["security_checks"]
        if check["name"] == "browser_authority_boundary"
    )
    assert "Enterprise admin frontend/Admin HTTP" in browser_boundary["detail"]
    assert "docs/LIVE_ORDER_SURFACES.md" in browser_boundary["detail"]
    assert {
        check["name"]
        for check in enterprise_payload["release_checks"]
        if check["status"] == "warning"
    } >= {
        "backend_regression_gate",
        "frontend_release_gate",
        "contextless_review_gate",
    }
    assert release_gate.status_code == 200
    release_payload = release_gate.json()
    assert release_payload["type"] == "admin_release_gate"
    assert release_payload["status"] == AdminApiGateStatus.PASSED.value
    assert release_payload["read_only"] is True
    assert release_payload["live_coinbase_orders_ran"] is False
    assert {check["name"] for check in release_payload["checks"]} >= {
        "openapi_schema_artifact",
        "backend_regression_gate",
        "live_coinbase_execution",
    }
    assert recovery_gate.status_code == 200
    recovery_payload = recovery_gate.json()
    assert recovery_payload["type"] == "admin_recovery_gate"
    assert recovery_payload["status"] == AdminApiGateStatus.PASSED.value
    assert recovery_payload["read_only"] is True
    assert recovery_payload["live_coinbase_orders_ran"] is False
    recovery_checks = {check["name"]: check for check in recovery_payload["checks"]}
    assert "spot_direct_order_audit_route" in recovery_checks
    assert "non_spot_recovery_scope" in recovery_checks
    assert recovery_checks["non_spot_recovery_scope"]["status"] == (
        AdminApiGateStatus.NOT_APPLICABLE.value
    )
    assert "spot/direct-order recovery readiness only" in (
        recovery_checks["non_spot_recovery_scope"]["detail"]
    )
    assert fill_ledger_health.status_code == 200
    fill_ledger_payload = fill_ledger_health.json()
    assert fill_ledger_payload["type"] == "admin_fill_ledger_health"
    assert fill_ledger_payload["status"] == AdminApiGateStatus.PASSED.value
    assert fill_ledger_payload["read_only"] is True
    assert fill_ledger_payload["live_coinbase_orders_ran"] is False
    assert {check["name"] for check in fill_ledger_payload["checks"]} >= {
        "read_surface",
        "repair_surface",
        "observed_at",
    }
    assert spot_recovery_preview.status_code == 200
    recovery_preview_payload = spot_recovery_preview.json()
    assert recovery_preview_payload["type"] == "spot_recovery_preview"
    assert recovery_preview_payload["module_id"] == "spot_operations"
    assert recovery_preview_payload["approved_phase_range"] == "2141-2160"
    assert recovery_preview_payload["read_only"] is True
    assert recovery_preview_payload["backend_owned"] is True
    assert recovery_preview_payload["browser_authority"] == "display_only"
    assert recovery_preview_payload["bff_authority"] == "read_only_forward"
    assert recovery_preview_payload["live_coinbase_orders_ran"] is False
    assert recovery_preview_payload["live_coinbase_read_ran"] is False
    assert recovery_preview_payload["apply_review_contract_available"] is True
    assert recovery_preview_payload["rollback_plan_contract_available"] is True
    assert recovery_preview_payload["reconciliation_proof_contract_available"] is True
    assert recovery_preview_payload["recovery_apply_available"] is True
    assert recovery_preview_payload["rollback_plan_available"] is True
    assert recovery_preview_payload["reconciliation_proof_available"] is True
    assert recovery_preview_payload["submitted_notional_usdc"] == "0"
    assert recovery_preview_payload["executed_notional_usdc"] == "0"
    assert recovery_preview_payload["source_count"] >= 3
    assert recovery_preview_payload["candidate_count"] >= 1
    assert "GET /api/v1/spot/recovery/preview" in recovery_preview_payload[
        "current_read_evidence_routes"
    ]
    assert "GET /api/v1/spot/recovery/apply-review" in recovery_preview_payload[
        "current_read_evidence_routes"
    ]
    assert "GET /api/v1/spot/recovery/rollback-plan" in recovery_preview_payload[
        "current_read_evidence_routes"
    ]
    assert (
        "GET /api/v1/spot/recovery/reconciliation-proof"
        in recovery_preview_payload["current_read_evidence_routes"]
    )
    assert "spot_recovery_preview_contract" not in recovery_preview_payload[
        "missing_contracts"
    ]
    assert "spot_recovery_apply_contract" not in recovery_preview_payload[
        "missing_contracts"
    ]
    assert "spot_recovery_state_repair_contract" not in recovery_preview_payload[
        "missing_contracts"
    ]
    assert "spot_recovery_post_apply_reconciliation_completion" not in (
        recovery_preview_payload["missing_contracts"]
    )
    recovery_preview_sources = {
        source["name"]: source for source in recovery_preview_payload["sources"]
    }
    assert all(
        source["live_coinbase_orders_ran"] is False
        for source in recovery_preview_sources.values()
    )
    assert all(
        source["live_coinbase_read_ran"] is False
        for source in recovery_preview_sources.values()
    )
    assert all(
        candidate["identity_key"] == "client_order_id"
        for source in recovery_preview_sources.values()
        for candidate in source["candidates"]
    )
    assert recovery_preview_sources["sweep_recovery_gate_plan"]["shared_method"] == (
        "build_spot_recovery_preview"
    )
    assert recovery_preview_sources["direct_order_audit_lookup"]["candidate_count"] == 1
    assert recovery_preview_sources["fill_ledger_health"]["route"] == (
        "/api/v1/admin/fill-ledger-health"
    )
    assert frontend_fixtures.status_code == 200
    frontend_fixture_payload = frontend_fixtures.json()
    assert frontend_fixture_payload["live_coinbase_orders_ran"] is False
    fixture_keys = set(frontend_fixture_payload["fixtures"])
    assert {
        "admin.releaseGate",
        "admin.recoveryGate",
        "admin.fillLedgerHealth",
        "spot.commandSuite",
        "spot.recoveryPreview",
        "spot.recoveryApplyReview",
        "spot.recoveryRollbackPlan",
        "spot.recoveryReconciliationProof",
    } <= fixture_keys
    assert "release.gate" not in fixture_keys
    assert "recovery.gate" not in fixture_keys
    assert "fillLedger.health" not in fixture_keys


@pytest.mark.regression
def test_admin_api_spot_recovery_preview_candidates_use_client_order_id(
    monkeypatch, tmp_path
):
    import business.spot_portfolio_sweep as spot_sweep_module
    import tools.run_spot_sweep_recovery_gate as recovery_gate_module

    from application.admin_api.read_service import AdminApiReadService

    monkeypatch.setattr(
        spot_sweep_module,
        "load_sweep_run_records",
        lambda _state_path: [],
    )
    monkeypatch.setattr(
        recovery_gate_module,
        "build_sweep_recovery_gate_plan",
        lambda **_kwargs: {
            "runs_needing_reconciliation": ["run-level-evidence"],
            "backfill_orders": [
                {
                    "client_order_id": "client-order-backfill",
                    "order_id": "exchange-order-evidence",
                },
                {"order_id": "exchange-order-without-client-id"},
            ],
        },
    )

    response = AdminApiReadService().build_spot_recovery_preview(
        state_file=str(tmp_path / "spot-sweeps.jsonl"),
    )
    sweep_source = next(
        source for source in response.sources if source.name == "sweep_recovery_gate_plan"
    )

    assert sweep_source.candidate_count == 1
    assert sweep_source.candidates == [
        {
            "candidate_type": "fill_backfill",
            "identity_key": "client_order_id",
            "identity_value": "client-order-backfill",
            "preview_only": True,
            "required_next_contract": "spot_recovery_execution_journal",
        }
    ]
    preview_json = json.dumps(response.model_dump(mode="json"))
    assert '"identity_key": "run_id"' not in preview_json
    assert '"identity_key": "order_id"' not in preview_json
    assert "exchange_order_id" not in preview_json


@pytest.mark.regression
def test_admin_api_spot_recovery_preview_does_not_call_live_or_apply_helpers(
    monkeypatch, tmp_path
):
    import business.spot_fill_ledger_health as fill_ledger_health_module
    import business.spot_portfolio_sweep as spot_sweep_module
    import configuration
    import tools.run_spot_fill_backfill_recovery as backfill_recovery_module
    import tools.run_spot_sweep_recovery_gate as recovery_gate_module

    from application.admin_api.read_service import AdminApiReadService

    def poison(*_args, **_kwargs):
        raise AssertionError("recovery preview must not call live/read/apply helpers")

    monkeypatch.setattr(configuration, "get_rest_client", poison)
    monkeypatch.setattr(spot_sweep_module, "reconcile_sweep_run_record", poison)
    monkeypatch.setattr(recovery_gate_module, "reconcile_sweep_run_record", poison)
    monkeypatch.setattr(
        recovery_gate_module,
        "backfill_fill_ledger_from_order_reports",
        poison,
    )
    monkeypatch.setattr(
        backfill_recovery_module,
        "backfill_fill_ledger_from_order_reports",
        poison,
    )
    monkeypatch.setattr(
        fill_ledger_health_module,
        "build_spot_fill_ledger_repair_actions",
        poison,
    )
    monkeypatch.setattr(
        fill_ledger_health_module,
        "apply_spot_fill_ledger_repair_actions",
        poison,
    )

    state_file = tmp_path / "sweep-runs.jsonl"
    state_file.write_text(
        json.dumps({
            "record_type": "sweep_run",
            "run_id": "run-needs-recovery",
            "config_id": "config-needs-recovery",
            "execution": {
                "fill_backfill": {
                    "orders": [
                        {
                            "client_order_id": "client-order-preview",
                            "exchange_order_id": "exchange-order-evidence",
                            "status": "error",
                        }
                    ]
                }
            },
        })
        + "\n",
        encoding="utf-8",
    )

    response = AdminApiReadService().build_spot_recovery_preview(
        state_file=str(state_file),
        client_order_id="client-order-preview",
    )
    assert response.live_coinbase_orders_ran is False
    assert response.live_coinbase_read_ran is False
    assert all(source.live_coinbase_orders_ran is False for source in response.sources)
    assert all(source.live_coinbase_read_ran is False for source in response.sources)

    client = _client(monkeypatch)
    http_response = client.get(
        "/api/v1/spot/recovery/preview",
        params={
            "state_file": str(state_file),
            "client_order_id": "client-order-preview",
        },
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    assert http_response.status_code == 200
    payload = http_response.json()
    assert payload["live_coinbase_orders_ran"] is False
    assert payload["live_coinbase_read_ran"] is False
    assert payload["submitted_notional_usdc"] == "0"
    assert payload["executed_notional_usdc"] == "0"


@pytest.mark.regression
def test_admin_api_spot_recovery_contract_routes_are_read_only_and_client_id_bound(
    monkeypatch, tmp_path
):
    import business.spot_fill_ledger_health as fill_ledger_health_module
    import business.spot_portfolio_sweep as spot_sweep_module
    import configuration
    import tools.run_spot_fill_backfill_recovery as backfill_recovery_module
    import tools.run_spot_sweep_recovery_gate as recovery_gate_module

    from application.admin_api.read_service import AdminApiReadService

    def poison(*_args, **_kwargs):
        raise AssertionError("recovery contract routes must not execute recovery")

    monkeypatch.setattr(configuration, "get_rest_client", poison)
    monkeypatch.setattr(spot_sweep_module, "reconcile_sweep_run_record", poison)
    monkeypatch.setattr(recovery_gate_module, "reconcile_sweep_run_record", poison)
    monkeypatch.setattr(
        recovery_gate_module,
        "backfill_fill_ledger_from_order_reports",
        poison,
    )
    monkeypatch.setattr(
        backfill_recovery_module,
        "backfill_fill_ledger_from_order_reports",
        poison,
    )
    monkeypatch.setattr(
        fill_ledger_health_module,
        "apply_spot_fill_ledger_repair_actions",
        poison,
    )

    state_file = tmp_path / "sweep-runs.jsonl"
    state_file.write_text(
        json.dumps({
            "record_type": "sweep_run",
            "run_id": "run-needs-recovery",
            "config_id": "config-needs-recovery",
            "execution": {
                "fill_backfill": {
                    "orders": [
                        {
                            "client_order_id": "client-order-preview",
                            "exchange_order_id": "exchange-order-evidence",
                            "status": "error",
                        }
                    ]
                }
            },
        })
        + "\n",
        encoding="utf-8",
    )

    service = AdminApiReadService()
    apply_review = service.build_spot_recovery_apply_review(
        state_file=str(state_file),
        client_order_id="client-order-preview",
    )
    rollback_plan = service.build_spot_recovery_rollback_plan(
        state_file=str(state_file),
        client_order_id="client-order-preview",
    )
    reconciliation_proof = service.build_spot_recovery_reconciliation_proof(
        state_file=str(state_file),
        client_order_id="client-order-preview",
    )

    assert apply_review.type == "spot_recovery_apply_review"
    assert apply_review.status == AdminApiGateStatus.BLOCKED
    assert apply_review.apply_review_contract_available is True
    assert apply_review.recovery_apply_available is True
    assert "spot_recovery_post_apply_reconciliation_completion" not in (
        apply_review.missing_contracts
    )
    assert "spot_recovery_state_repair_contract" not in (
        apply_review.missing_contracts
    )
    assert apply_review.state_repair_contract_available is True
    assert {gate.name for gate in apply_review.contract_gate_evidence} >= {
        "approval_snapshot",
        "admission_audit",
        "cap_guard_decision",
        "rollback_plan_contract",
        "reconciliation_proof_contract",
    }
    assert rollback_plan.type == "spot_recovery_rollback_plan"
    assert rollback_plan.rollback_plan_contract_available is True
    assert rollback_plan.rollback_execution_available is True
    assert rollback_plan.rollback_repair_contract_available is True
    assert rollback_plan.missing_contracts == []
    assert reconciliation_proof.type == "spot_recovery_reconciliation_proof"
    assert reconciliation_proof.reconciliation_proof_contract_available is True
    assert reconciliation_proof.exchange_state_proof_writer_available is True
    assert reconciliation_proof.reconciliation_proof_writer_available is True
    assert reconciliation_proof.proof_persistence_available is True
    assert reconciliation_proof.persisted_proof_count == 0
    assert "exchange_state_snapshot_id" in reconciliation_proof.required_proof_fields
    assert reconciliation_proof.reconciliation_execution_available is False
    assert reconciliation_proof.reconciliation_execution_boundary_available is True
    assert reconciliation_proof.reconciliation_execution_boundary_count >= 1
    execution_boundary = reconciliation_proof.reconciliation_execution_boundaries[0]
    assert execution_boundary.client_order_id == "client-order-preview"
    assert execution_boundary.status == AdminApiGateStatus.BLOCKED
    assert execution_boundary.mutation_family == (
        AdminApiMutationFamilyType.SPOT_RECOVERY_RECONCILIATION_EXECUTION
    )
    assert execution_boundary.command_route == (
        "/api/v1/spot/recovery/reconciliation-executions"
    )
    assert execution_boundary.method == "POST"
    assert execution_boundary.route_inventory_status == AdminApiGateStatus.PASSED
    assert execution_boundary.service_method == (
        "execute_spot_recovery_reconciliation"
    )
    assert execution_boundary.action_class == (
        AdminApiActionClass.LOCAL_STATE_MUTATION
    )
    assert execution_boundary.required_permission == (
        AdminApiPermission.SPOT_RECOVERY_EXECUTE
    )
    assert execution_boundary.future_action_class == (
        AdminApiActionClass.LOCAL_STATE_MUTATION
    )
    assert execution_boundary.future_required_permission == (
        AdminApiPermission.SPOT_RECOVERY_EXECUTE
    )
    assert "client_order_id" in execution_boundary.present_inputs
    assert "completion_id" in execution_boundary.missing_inputs
    assert "spot_reconciliation_execution_contract" in (
        execution_boundary.missing_contracts
    )
    assert "spot_reconciliation_execution_contract_missing" in (
        execution_boundary.blockers
    )
    assert "reconciliation_executor_disabled" in execution_boundary.blockers
    assert "spot_reconciliation_execution_route_missing" not in (
        execution_boundary.blockers
    )
    assert "spot_reconciliation_execution_service_missing" not in (
        execution_boundary.blockers
    )
    assert execution_boundary.noop_review_allowed is True
    assert execution_boundary.route_bound is True
    assert execution_boundary.local_state_reconciliation_allowed is False
    assert execution_boundary.order_state_mutation_allowed is False
    assert execution_boundary.exchange_state_mutation_allowed is False
    assert execution_boundary.coinbase_rest_read_allowed is False
    assert execution_boundary.coinbase_order_submission_allowed is False
    assert execution_boundary.reconciliation_executed is False
    assert execution_boundary.coinbase_rest_read_ran is False
    assert execution_boundary.live_coinbase_orders_ran is False
    assert execution_boundary.browser_authority == "display_only"
    assert execution_boundary.bff_authority == "forward_only_no_execution"
    assert "spot_reconciliation_execution_contract" in (
        reconciliation_proof.missing_contracts
    )
    assert "spot_recovery_proof_persistence_contract" not in (
        reconciliation_proof.missing_contracts
    )
    for payload in (apply_review, rollback_plan, reconciliation_proof):
        assert payload.state_repair_taxonomy_available is True
        assert payload.repair_target_model_available is True
        assert payload.pre_apply_snapshot_required is True
        assert payload.dry_run_repair_plan_available is True
        assert payload.state_repair_taxonomy
        taxonomy_by_category = {
            item.category: item for item in payload.state_repair_taxonomy
        }
        assert SpotRecoveryRepairCategory.FILL_BACKFILL_LEDGER in taxonomy_by_category
        assert taxonomy_by_category[
            SpotRecoveryRepairCategory.FILL_BACKFILL_LEDGER
        ].fill_ledger_mutation_allowed is True
        assert all(
            item.coinbase_read_allowed is False
            and item.coinbase_submission_allowed is False
            and item.exchange_state_mutation_allowed is False
            and item.browser_authority == "display_only"
            for item in payload.state_repair_taxonomy
        )
        assert payload.repair_targets
        repair_target = payload.repair_targets[0]
        assert repair_target.identity_key == "client_order_id"
        assert repair_target.client_order_id == "client-order-preview"
        assert repair_target.state_repair_available is False
        assert repair_target.state_repair_executed is False
        assert repair_target.order_state_mutated is False
        assert repair_target.exchange_state_mutated is False
        assert repair_target.completion_state in {
            SpotRecoveryCompletionState.DRY_RUN_REPAIR_PLANNED,
            SpotRecoveryCompletionState.REPAIR_BLOCKED,
        }
        assert payload.pre_apply_snapshots
        assert payload.pre_apply_snapshots[0].client_order_id == (
            "client-order-preview"
        )
        assert payload.pre_apply_snapshots[0].required_before_state_repair is True
        assert payload.pre_apply_snapshots[0].snapshot_captured is False
        assert payload.dry_run_repair_plans
        dry_run_plan = payload.dry_run_repair_plans[0]
        assert dry_run_plan.client_order_id == "client-order-preview"
        assert dry_run_plan.executable is False
        assert dry_run_plan.state_repair_executed is False
        assert dry_run_plan.exchange_state_mutated is False
        assert "coinbase_rest_read" in dry_run_plan.rejected_mutations
        assert "pre_apply_snapshot" in dry_run_plan.required_guard_chain
        assert payload.completion_states
        assert payload.completion_states[0].client_order_id == (
            "client-order-preview"
        )
        assert payload.completion_states[0].repair_applied is False
        assert payload.completion_states[0].fully_reconciled is False
        assert payload.live_coinbase_orders_ran is False
        assert payload.live_coinbase_read_ran is False
        assert payload.submitted_notional_usdc == "0"
        assert payload.executed_notional_usdc == "0"
        assert payload.read_only is True
        assert payload.browser_authority == "display_only"
        assert payload.bff_authority == "read_only_forward"
        assert payload.candidate_count >= 1
        assert all(candidate.identity_key == "client_order_id" for candidate in payload.candidates)
        serialized = json.dumps(payload.model_dump(mode="json"))
        assert '"identity_key": "order_id"' not in serialized
        assert "exchange_order_id" not in serialized

    client = _client(monkeypatch)
    for path in (
        "/api/v1/spot/recovery/apply-review",
        "/api/v1/spot/recovery/rollback-plan",
        "/api/v1/spot/recovery/reconciliation-proof",
    ):
        http_response = client.get(
            path,
            params={
                "state_file": str(state_file),
                "client_order_id": "client-order-preview",
            },
            headers=_headers(roles=AdminApiRole.VIEWER.value),
        )
        assert http_response.status_code == 200
        body = http_response.json()
        assert body["read_only"] is True
        assert body["recovery_apply_available"] is True
        assert body["live_coinbase_orders_ran"] is False
        assert body["live_coinbase_read_ran"] is False
        assert body["submitted_notional_usdc"] == "0"
        assert body["executed_notional_usdc"] == "0"
        assert all(
            candidate["identity_key"] == "client_order_id"
            for candidate in body["candidates"]
        )
        if path.endswith("/reconciliation-proof"):
            assert body["reconciliation_execution_available"] is False
            assert body["reconciliation_execution_boundary_available"] is True
            assert body["reconciliation_execution_boundary_count"] >= 1
            assert body["reconciliation_execution_boundaries"][0][
                "client_order_id"
            ] == "client-order-preview"
            assert body["reconciliation_execution_boundaries"][0][
                "reconciliation_executed"
            ] is False


@pytest.mark.regression
def test_admin_api_spot_recovery_execution_journals_are_prerequisite_gated(
    monkeypatch,
):
    import configuration

    def poison(*_args, **_kwargs):
        raise AssertionError("recovery command contracts must not contact Coinbase")

    monkeypatch.setattr(configuration, "get_rest_client", poison)

    client = _client(monkeypatch)
    client_order_id = "client-order-preview"
    apply_path = "/api/v1/spot/recovery/apply-executions"
    rollback_path = "/api/v1/spot/recovery/rollback-executions"
    apply_body = {
        "client_order_id": client_order_id,
        "rollback_plan_id": "rollback-plan-apply-001",
        "approval_snapshot_id": "approval-apply-001",
        "admission_audit_id": "admission-audit-apply-001",
        "cap_guard_decision_id": "cap-guard-apply-001",
        "reconciliation_plan_id": "reconciliation-plan-apply-001",
        "exchange_state_proof_id": "exchange-state-proof-001",
        "dry_run": True,
        "operator_reason": "contract evidence only",
        "manual_live_acknowledgement": False,
    }

    denied = client.post(
        apply_path,
        json=apply_body,
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    assert denied.status_code == 403
    assert denied.json()["live_coinbase_orders_ran"] is False

    rejected_order_id = client.post(
        apply_path,
        json={**apply_body, "order_id": "exchange-order-id"},
        headers=_headers(
            idempotency_key="spot-recovery-order-id-rejected",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert rejected_order_id.status_code == 422

    missing_prerequisites = client.post(
        apply_path,
        json=apply_body,
        headers=_headers(
            idempotency_key="spot-recovery-apply-missing-prereq",
            operator_intent="spot_recovery_contract_review",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert missing_prerequisites.status_code == 400
    missing_payload = missing_prerequisites.json()
    assert missing_payload["status"] == AdminApiCommandStatus.REJECTED.value
    assert missing_payload["failure_stage"] == "execution_prerequisite"
    assert missing_payload["data"]["repair_journal_persisted"] is False
    assert missing_payload["data"]["execution_journal_accepted"] is False
    assert missing_payload["data"]["recovery_apply_journal_accepted"] is False
    assert missing_payload["data"]["rollback_journal_accepted"] is False
    assert missing_payload["data"]["state_repair_executed"] is False
    assert missing_payload["data"]["coinbase_order_submitted"] is False
    assert missing_payload["data"]["coinbase_rest_read_ran"] is False
    assert missing_payload["data"]["order_state_mutated"] is False
    assert missing_payload["data"]["exchange_state_mutated"] is False

    client.admin_api_test_spot_recovery_proof_store.append(
        SpotRecoveryProofRecord(
            proof_id="exchange-state-proof-001",
            mutation_family=(
                AdminApiMutationFamilyType.SPOT_RECOVERY_EXCHANGE_STATE_PROOF
            ),
            client_order_id=client_order_id,
            exchange_state_proof_id="exchange-state-proof-001",
            exchange_state_evidence_ref="audit-workbench-ref-001",
            reconciliation_plan_id="reconciliation-plan-proof-source-001",
            approval_snapshot_id="approval-proof-source-001",
            admission_audit_id="admission-audit-proof-source-001",
            cap_guard_decision_id="cap-guard-proof-source-001",
            route="/api/v1/spot/recovery/exchange-state-proofs",
            method="POST",
            service_method="record_spot_recovery_exchange_state_proof",
            actor_id="operator-001",
            operator_intent="spot_recovery_contract_review",
            idempotency_key="spot-recovery-proof-source",
            correlation_id="corr-spot-recovery-proof-source",
            payload_hash="a" * 64,
            audit_id="audit-proof-source-001",
        )
    )

    apply_idempotency_key = "spot-recovery-apply-001"
    apply_payload_hash = _spot_recovery_execution_payload_hash(
        endpoint=f"POST {apply_path}",
        body=apply_body,
        model=SpotRecoveryApplyExecutionRequest,
    )
    _append_spot_recovery_execution_admission_chain(
        approval_store=client.admin_api_test_approval_store,
        audit_store=client.admin_api_test_audit_store,
        cap_guard_store=client.admin_api_test_cap_guard_store,
        reconciliation_store=client.admin_api_test_reconciliation_store,
        route=apply_path,
        service_method="execute_spot_recovery_apply",
        client_order_id=client_order_id,
        idempotency_key=apply_idempotency_key,
        operator_intent="spot_recovery_contract_review",
        payload_hash=apply_payload_hash,
        approval_snapshot_id=apply_body["approval_snapshot_id"],
        admission_audit_id=apply_body["admission_audit_id"],
        cap_guard_decision_id=apply_body["cap_guard_decision_id"],
        reconciliation_plan_id=apply_body["reconciliation_plan_id"],
    )
    apply_response = client.post(
        apply_path,
        json=apply_body,
        headers=_headers(
            idempotency_key=apply_idempotency_key,
            operator_intent="spot_recovery_contract_review",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert apply_response.status_code == 200
    apply_payload = apply_response.json()
    assert apply_payload["status"] == AdminApiCommandStatus.ACCEPTED.value
    assert apply_payload["service_method"] == "execute_spot_recovery_apply"
    assert apply_payload["action_class"] == AdminApiActionClass.LOCAL_STATE_MUTATION.value
    assert apply_payload["required_permission"] == (
        AdminApiPermission.SPOT_RECOVERY_EXECUTE.value
    )
    assert apply_payload["client_order_id"] == client_order_id
    assert apply_payload["idempotency_key"] == apply_idempotency_key
    assert apply_payload["live_exchange_submitted"] is False
    assert apply_payload["admission_decision"]["allowed"] is False
    assert apply_payload["admission_decision"]["approval_snapshot_present"] is True
    assert apply_payload["admission_decision"]["admission_audit_present"] is True
    assert apply_payload["admission_decision"]["cap_guard_present"] is True
    assert apply_payload["admission_decision"]["reconciliation_plan_present"] is True
    assert apply_payload["data"]["mutation_family"] == (
        AdminApiMutationFamilyType.SPOT_RECOVERY_APPLY_EXECUTION.value
    )
    assert apply_payload["data"]["repair_journal_persisted"] is True
    assert apply_payload["data"]["execution_journal_accepted"] is True
    assert apply_payload["data"]["recovery_apply_journal_accepted"] is True
    assert apply_payload["data"]["rollback_journal_accepted"] is False
    assert apply_payload["data"]["repair_intent_accepted"] is True
    assert apply_payload["data"]["recovery_apply_executed"] is True
    assert apply_payload["data"]["rollback_executed"] is False
    assert apply_payload["data"]["state_repair_executed"] is False
    assert apply_payload["data"]["post_apply_reconciliation_required"] is True
    assert apply_payload["data"]["post_apply_reconciliation_satisfied"] is False
    assert apply_payload["data"]["proof_persisted"] is False
    assert apply_payload["data"]["coinbase_order_submitted"] is False
    assert apply_payload["data"]["coinbase_rest_read_ran"] is False
    assert apply_payload["data"]["order_state_mutated"] is False
    assert apply_payload["data"]["exchange_state_mutated"] is False
    assert apply_payload["data"]["browser_authority"] == "display_only"
    assert apply_payload["data"]["bff_authority"] == "forward_only_no_execution"
    assert '"order_id"' not in json.dumps(apply_payload)

    apply_replay = client.post(
        apply_path,
        json=apply_body,
        headers=_headers(
            idempotency_key=apply_idempotency_key,
            operator_intent="spot_recovery_contract_review",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert apply_replay.status_code == 200
    assert apply_replay.headers["X-Idempotency-Replayed"] == "true"
    assert apply_replay.json()["status"] == AdminApiCommandStatus.ACCEPTED.value
    assert apply_replay.json()["data"]["journal_id"] == (
        apply_payload["data"]["journal_id"]
    )

    rejected_repair_body = {
        **apply_body,
        "rollback_plan_id": "rollback-plan-apply-repair-bad",
        "reconciliation_plan_id": "reconciliation-plan-apply-repair-bad",
        "state_repair_requested": True,
        "repair_target_id": "wrong-repair-target",
        "pre_apply_snapshot_id": "wrong-snapshot",
        "dry_run_repair_plan_id": "wrong-dry-run-plan",
    }
    rejected_repair_idempotency_key = "spot-recovery-apply-repair-bad"
    rejected_repair_payload_hash = _spot_recovery_execution_payload_hash(
        endpoint=f"POST {apply_path}",
        body=rejected_repair_body,
        model=SpotRecoveryApplyExecutionRequest,
    )
    _append_spot_recovery_execution_admission_chain(
        approval_store=client.admin_api_test_approval_store,
        audit_store=client.admin_api_test_audit_store,
        cap_guard_store=client.admin_api_test_cap_guard_store,
        reconciliation_store=client.admin_api_test_reconciliation_store,
        route=apply_path,
        service_method="execute_spot_recovery_apply",
        client_order_id=client_order_id,
        idempotency_key=rejected_repair_idempotency_key,
        operator_intent="spot_recovery_contract_review",
        payload_hash=rejected_repair_payload_hash,
        approval_snapshot_id=rejected_repair_body["approval_snapshot_id"],
        admission_audit_id=rejected_repair_body["admission_audit_id"],
        cap_guard_decision_id=rejected_repair_body["cap_guard_decision_id"],
        reconciliation_plan_id=rejected_repair_body["reconciliation_plan_id"],
    )
    rejected_repair = client.post(
        apply_path,
        json=rejected_repair_body,
        headers=_headers(
            idempotency_key=rejected_repair_idempotency_key,
            operator_intent="spot_recovery_contract_review",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert rejected_repair.status_code == 400
    assert rejected_repair.json()["failure_stage"] == "execution_prerequisite"
    assert "repair guard rejected" in rejected_repair.json()["message"]

    guarded_apply_body = {
        **apply_body,
        "rollback_plan_id": "rollback-plan-apply-repair-001",
        "reconciliation_plan_id": "reconciliation-plan-apply-repair-001",
        "approval_snapshot_id": "approval-apply-repair-001",
        "admission_audit_id": "admission-audit-apply-repair-001",
        "cap_guard_decision_id": "cap-guard-apply-repair-001",
        "state_repair_requested": True,
    }
    repair_ids = build_spot_recovery_repair_ids(
        client_order_id=client_order_id,
        mutation_family=(
            AdminApiMutationFamilyType.SPOT_RECOVERY_APPLY_EXECUTION
        ),
        rollback_plan_id=guarded_apply_body["rollback_plan_id"],
        evidence_id=guarded_apply_body["exchange_state_proof_id"],
        reconciliation_plan_id=guarded_apply_body["reconciliation_plan_id"],
    )
    guarded_apply_body.update(
        {
            "repair_target_id": repair_ids.repair_target_id,
            "pre_apply_snapshot_id": repair_ids.pre_apply_snapshot_id,
            "dry_run_repair_plan_id": repair_ids.dry_run_repair_plan_id,
        }
    )
    guarded_apply_idempotency_key = "spot-recovery-apply-repair-001"
    guarded_apply_payload_hash = _spot_recovery_execution_payload_hash(
        endpoint=f"POST {apply_path}",
        body=guarded_apply_body,
        model=SpotRecoveryApplyExecutionRequest,
    )
    _append_spot_recovery_execution_admission_chain(
        approval_store=client.admin_api_test_approval_store,
        audit_store=client.admin_api_test_audit_store,
        cap_guard_store=client.admin_api_test_cap_guard_store,
        reconciliation_store=client.admin_api_test_reconciliation_store,
        route=apply_path,
        service_method="execute_spot_recovery_apply",
        client_order_id=client_order_id,
        idempotency_key=guarded_apply_idempotency_key,
        operator_intent="spot_recovery_contract_review",
        payload_hash=guarded_apply_payload_hash,
        approval_snapshot_id=guarded_apply_body["approval_snapshot_id"],
        admission_audit_id=guarded_apply_body["admission_audit_id"],
        cap_guard_decision_id=guarded_apply_body["cap_guard_decision_id"],
        reconciliation_plan_id=guarded_apply_body["reconciliation_plan_id"],
    )
    guarded_apply_response = client.post(
        apply_path,
        json=guarded_apply_body,
        headers=_headers(
            idempotency_key=guarded_apply_idempotency_key,
            operator_intent="spot_recovery_contract_review",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert guarded_apply_response.status_code == 200
    guarded_apply_payload = guarded_apply_response.json()
    assert guarded_apply_payload["data"]["repair_guard_passed"] is True
    assert guarded_apply_payload["data"]["repair_guard_failures"] == []
    assert guarded_apply_payload["data"]["repair_result_journal_persisted"] is True
    assert guarded_apply_payload["data"]["repair_result_id"] == (
        repair_ids.repair_result_id
    )
    assert guarded_apply_payload["data"]["state_repair_executed"] is True
    assert guarded_apply_payload["data"]["order_state_mutated"] is False
    assert guarded_apply_payload["data"]["exchange_state_mutated"] is False
    assert guarded_apply_payload["data"]["reconciliation_executed"] is False
    assert guarded_apply_payload["data"]["coinbase_order_submitted"] is False
    assert guarded_apply_payload["data"]["coinbase_rest_read_ran"] is False

    rollback_body = {
        "client_order_id": client_order_id,
        "rollback_plan_id": "rollback-plan-rollback-001",
        "recovery_apply_audit_id": apply_payload["audit_id"],
        "approval_snapshot_id": "approval-rollback-001",
        "admission_audit_id": "admission-audit-rollback-001",
        "cap_guard_decision_id": "cap-guard-rollback-001",
        "reconciliation_plan_id": "reconciliation-plan-rollback-001",
        "dry_run": True,
        "operator_reason": "contract evidence rollback only",
        "manual_live_acknowledgement": False,
    }
    rollback_idempotency_key = "spot-recovery-rollback-001"
    rollback_payload_hash = _spot_recovery_execution_payload_hash(
        endpoint=f"POST {rollback_path}",
        body=rollback_body,
        model=SpotRecoveryRollbackExecutionRequest,
    )
    _append_spot_recovery_execution_admission_chain(
        approval_store=client.admin_api_test_approval_store,
        audit_store=client.admin_api_test_audit_store,
        cap_guard_store=client.admin_api_test_cap_guard_store,
        reconciliation_store=client.admin_api_test_reconciliation_store,
        route=rollback_path,
        service_method="execute_spot_recovery_rollback",
        client_order_id=client_order_id,
        idempotency_key=rollback_idempotency_key,
        operator_intent="spot_recovery_contract_review",
        payload_hash=rollback_payload_hash,
        approval_snapshot_id=rollback_body["approval_snapshot_id"],
        admission_audit_id=rollback_body["admission_audit_id"],
        cap_guard_decision_id=rollback_body["cap_guard_decision_id"],
        reconciliation_plan_id=rollback_body["reconciliation_plan_id"],
    )
    rollback_response = client.post(
        rollback_path,
        json=rollback_body,
        headers=_headers(
            idempotency_key=rollback_idempotency_key,
            operator_intent="spot_recovery_contract_review",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert rollback_response.status_code == 200
    rollback_payload = rollback_response.json()
    assert rollback_payload["status"] == AdminApiCommandStatus.ACCEPTED.value
    assert rollback_payload["service_method"] == "execute_spot_recovery_rollback"
    assert rollback_payload["data"]["mutation_family"] == (
        AdminApiMutationFamilyType.SPOT_RECOVERY_ROLLBACK_EXECUTION.value
    )
    assert rollback_payload["data"]["repair_journal_persisted"] is True
    assert rollback_payload["data"]["execution_journal_accepted"] is True
    assert rollback_payload["data"]["recovery_apply_journal_accepted"] is False
    assert rollback_payload["data"]["rollback_journal_accepted"] is True
    assert rollback_payload["data"]["rollback_executed"] is True
    assert rollback_payload["data"]["recovery_apply_audit_id"] == apply_payload["audit_id"]
    assert rollback_payload["data"]["recovery_apply_journal_id"] == (
        apply_payload["data"]["journal_id"]
    )
    assert rollback_payload["data"]["post_apply_reconciliation_required"] is False
    assert rollback_payload["data"]["state_repair_executed"] is False
    assert rollback_payload["data"]["coinbase_order_submitted"] is False
    assert rollback_payload["data"]["coinbase_rest_read_ran"] is False
    assert rollback_payload["data"]["order_state_mutated"] is False
    assert rollback_payload["data"]["exchange_state_mutated"] is False

    audit_rows = client.admin_api_test_audit_store.read_recent(limit=20)
    recovery_audit_rows = [
        row
        for row in audit_rows
        if row.permission == AdminApiPermission.SPOT_RECOVERY_EXECUTE
        and row.endpoint
        in (
            "POST /api/v1/spot/recovery/apply-executions",
            "POST /api/v1/spot/recovery/rollback-executions",
        )
        and row.request_id == "corr-001"
    ]
    assert len(recovery_audit_rows) == 5
    accepted_rows = [
        row
        for row in recovery_audit_rows
        if row.status == AdminApiCommandStatus.ACCEPTED
    ]
    assert len(accepted_rows) == 3
    assert all(row.coinbase_order_id is None for row in recovery_audit_rows)
    assert all(
        row.admission_decision is not None and row.admission_decision.allowed is False
        for row in recovery_audit_rows
    )
    journal_records = client.admin_api_test_spot_recovery_execution_store.read_recent(
        limit=20
    )
    assert len(journal_records) == 3
    assert {record.audit_id for record in journal_records} == {
        apply_payload["audit_id"],
        guarded_apply_payload["audit_id"],
        rollback_payload["audit_id"],
    }
    repair_result_records = (
        client.admin_api_test_spot_recovery_repair_result_store.read_recent(limit=20)
    )
    assert len(repair_result_records) == 1
    assert repair_result_records[0].repair_result_id == repair_ids.repair_result_id
    assert repair_result_records[0].state_repair_executed is True
    assert repair_result_records[0].order_state_mutated is False
    assert repair_result_records[0].exchange_state_mutated is False
    readback = client.get(
        "/api/v1/spot/recovery/reconciliation-proof",
        params={"client_order_id": client_order_id},
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    assert readback.status_code == 200
    readback_payload = readback.json()
    assert readback_payload["execution_journal_available"] is True
    assert readback_payload["persisted_execution_count"] == 3
    assert readback_payload["persisted_repair_result_count"] == 1
    assert readback_payload["latest_repair_result_id"] == repair_ids.repair_result_id
    assert readback_payload["latest_apply_journal_id"] == (
        guarded_apply_payload["data"]["journal_id"]
    )
    assert readback_payload["latest_rollback_journal_id"] == (
        rollback_payload["data"]["journal_id"]
    )
    assert readback_payload["post_apply_reconciliation_required_count"] == 2
    assert readback_payload["repair_target_model_available"] is True
    assert readback_payload["pre_apply_snapshot_required"] is True
    assert readback_payload["dry_run_repair_plan_available"] is True
    assert readback_payload["repair_targets"]
    readback_target = readback_payload["repair_targets"][0]
    assert readback_target["client_order_id"] == client_order_id
    assert readback_target["identity_key"] == "client_order_id"
    assert apply_payload["data"]["journal_id"] in (
        readback_target["execution_journal_ids"]
    )
    assert rollback_payload["data"]["journal_id"] in (
        readback_target["execution_journal_ids"]
    )
    assert repair_ids.repair_result_id in readback_target["repair_result_ids"]
    assert readback_target["state_repair_executed"] is True
    assert readback_target["order_state_mutated"] is False
    assert readback_target["exchange_state_mutated"] is False
    assert readback_payload["pre_apply_snapshots"]
    assert readback_payload["pre_apply_snapshots"][0]["snapshot_captured"] is False
    assert readback_payload["dry_run_repair_plans"]
    assert readback_payload["dry_run_repair_plans"][0]["executable"] is False
    assert "coinbase_order_submission" in (
        readback_payload["dry_run_repair_plans"][0]["rejected_mutations"]
    )
    assert readback_payload["completion_states"]
    assert readback_payload["completion_states"][0]["repair_applied"] is True
    assert readback_payload["completion_states"][0]["rollback_applied"] is True
    assert readback_payload["completion_states"][0]["fully_reconciled"] is False


@pytest.mark.regression
def test_admin_api_spot_recovery_proof_routes_persist_replay_and_read_back(
    monkeypatch,
):
    import configuration

    def poison(*_args, **_kwargs):
        raise AssertionError("recovery proof routes must not contact Coinbase")

    monkeypatch.setattr(configuration, "get_rest_client", poison)

    client = _client(monkeypatch)
    exchange_body = {
        "client_order_id": "client-order-preview",
        "exchange_state_proof_id": "exchange-state-proof-001",
        "exchange_state_evidence_ref": "audit-workbench-ref-001",
        "reconciliation_plan_id": "reconciliation-plan-exchange-001",
        "approval_snapshot_id": "approval-exchange-001",
        "admission_audit_id": "admission-audit-exchange-001",
        "cap_guard_decision_id": "cap-guard-exchange-001",
        "dry_run": True,
        "operator_reason": "contract evidence only",
        "manual_live_acknowledgement": False,
    }
    reconciliation_body = {
        "client_order_id": "client-order-preview",
        "exchange_state_proof_id": "exchange-state-proof-001",
        "reconciliation_proof_id": "reconciliation-proof-001",
        "recovery_apply_audit_id": "recovery-apply-audit-001",
        "reconciliation_plan_id": "reconciliation-plan-proof-001",
        "approval_snapshot_id": "approval-proof-001",
        "admission_audit_id": "admission-audit-proof-001",
        "cap_guard_decision_id": "cap-guard-proof-001",
        "dry_run": True,
        "operator_reason": "contract evidence only",
        "manual_live_acknowledgement": False,
    }

    denied = client.post(
        "/api/v1/spot/recovery/exchange-state-proofs",
        json=exchange_body,
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    assert denied.status_code == 403
    assert denied.json()["live_coinbase_orders_ran"] is False

    rejected_order_id = client.post(
        "/api/v1/spot/recovery/exchange-state-proofs",
        json={**exchange_body, "order_id": "exchange-order-id"},
        headers=_headers(
            idempotency_key="spot-recovery-proof-order-id-rejected",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert rejected_order_id.status_code == 422

    missing_prereq = client.post(
        "/api/v1/spot/recovery/exchange-state-proofs",
        json=exchange_body,
        headers=_headers(
            idempotency_key="spot-recovery-exchange-missing-prereq",
            operator_intent="spot_recovery_contract_review",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert missing_prereq.status_code == 400
    assert missing_prereq.json()["status"] == AdminApiCommandStatus.REJECTED.value
    assert missing_prereq.json()["required_permission"] == (
        AdminApiPermission.SPOT_RECOVERY_RECORD.value
    )
    assert missing_prereq.json()["data"]["proof_persisted"] is False
    assert client.admin_api_test_spot_recovery_proof_store.read_recent() == []

    exchange_payload_hash = _spot_recovery_proof_payload_hash(
        endpoint="POST /api/v1/spot/recovery/exchange-state-proofs",
        body=exchange_body,
        model=SpotRecoveryExchangeStateProofRequest,
    )
    _append_spot_recovery_proof_admission_chain(
        approval_store=client.admin_api_test_approval_store,
        audit_store=client.admin_api_test_audit_store,
        cap_guard_store=client.admin_api_test_cap_guard_store,
        reconciliation_store=client.admin_api_test_reconciliation_store,
        route="/api/v1/spot/recovery/exchange-state-proofs",
        service_method="record_spot_recovery_exchange_state_proof",
        client_order_id="client-order-preview",
        idempotency_key="spot-recovery-exchange-proof-001",
        operator_intent="spot_recovery_contract_review",
        payload_hash=exchange_payload_hash,
        approval_snapshot_id="approval-exchange-001",
        admission_audit_id="admission-audit-exchange-001",
        cap_guard_decision_id="cap-guard-exchange-001",
        reconciliation_plan_id="reconciliation-plan-exchange-001",
    )
    exchange_created = client.post(
        "/api/v1/spot/recovery/exchange-state-proofs",
        json=exchange_body,
        headers=_headers(
            idempotency_key="spot-recovery-exchange-proof-001",
            operator_intent="spot_recovery_contract_review",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert exchange_created.status_code == 200
    exchange_payload = exchange_created.json()
    assert exchange_payload["status"] == AdminApiCommandStatus.ACCEPTED.value
    assert exchange_payload["required_permission"] == (
        AdminApiPermission.SPOT_RECOVERY_RECORD.value
    )
    assert exchange_payload["data"]["proof_id"] == "exchange-state-proof-001"
    assert exchange_payload["data"]["exchange_state_proof_recorded"] is True
    assert exchange_payload["data"]["proof_persisted"] is True
    assert exchange_payload["data"]["coinbase_rest_read_ran"] is False
    assert exchange_payload["data"]["order_state_mutated"] is False
    assert exchange_payload["data"]["exchange_state_mutated"] is False
    assert exchange_payload["live_exchange_submitted"] is False
    assert '"order_id"' not in json.dumps(exchange_payload)

    exchange_replay = client.post(
        "/api/v1/spot/recovery/exchange-state-proofs",
        json=exchange_body,
        headers=_headers(
            idempotency_key="spot-recovery-exchange-proof-001",
            operator_intent="spot_recovery_contract_review",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert exchange_replay.status_code == 200
    assert exchange_replay.headers["X-Idempotency-Replayed"] == "true"
    assert exchange_replay.json()["audit_id"] == exchange_payload["audit_id"]

    _append_spot_recovery_apply_audit(
        audit_store=client.admin_api_test_audit_store,
        audit_id="recovery-apply-audit-001",
        client_order_id="client-order-preview",
    )
    reconciliation_payload_hash = _spot_recovery_proof_payload_hash(
        endpoint="POST /api/v1/spot/recovery/reconciliation-proofs",
        body=reconciliation_body,
        model=SpotRecoveryReconciliationProofRecordRequest,
    )
    _append_spot_recovery_proof_admission_chain(
        approval_store=client.admin_api_test_approval_store,
        audit_store=client.admin_api_test_audit_store,
        cap_guard_store=client.admin_api_test_cap_guard_store,
        reconciliation_store=client.admin_api_test_reconciliation_store,
        route="/api/v1/spot/recovery/reconciliation-proofs",
        service_method="record_spot_recovery_reconciliation_proof",
        client_order_id="client-order-preview",
        idempotency_key="spot-recovery-reconciliation-proof-001",
        operator_intent="spot_recovery_contract_review",
        payload_hash=reconciliation_payload_hash,
        approval_snapshot_id="approval-proof-001",
        admission_audit_id="admission-audit-proof-001",
        cap_guard_decision_id="cap-guard-proof-001",
        reconciliation_plan_id="reconciliation-plan-proof-001",
    )
    reconciliation_created = client.post(
        "/api/v1/spot/recovery/reconciliation-proofs",
        json=reconciliation_body,
        headers=_headers(
            idempotency_key="spot-recovery-reconciliation-proof-001",
            operator_intent="spot_recovery_contract_review",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert reconciliation_created.status_code == 200
    reconciliation_payload = reconciliation_created.json()
    assert reconciliation_payload["status"] == AdminApiCommandStatus.ACCEPTED.value
    assert reconciliation_payload["required_permission"] == (
        AdminApiPermission.SPOT_RECOVERY_RECORD.value
    )
    assert reconciliation_payload["data"]["proof_id"] == "reconciliation-proof-001"
    assert reconciliation_payload["data"]["reconciliation_proof_recorded"] is True
    assert (
        reconciliation_payload["data"][
            "post_apply_reconciliation_completion_recorded"
        ]
        is False
    )
    assert reconciliation_payload["data"]["completion_guard_passed"] is False
    assert "apply_execution_journal_missing" in (
        reconciliation_payload["data"]["completion_guard_failures"]
    )
    assert reconciliation_payload["data"]["reconciliation_executed"] is False
    assert reconciliation_payload["data"]["proof_persisted"] is True
    assert reconciliation_payload["data"]["coinbase_rest_read_ran"] is False
    assert reconciliation_payload["data"]["order_state_mutated"] is False
    assert reconciliation_payload["data"]["exchange_state_mutated"] is False

    proof_records = client.admin_api_test_spot_recovery_proof_store.read_recent()
    assert [record.proof_id for record in proof_records] == [
        "reconciliation-proof-001",
        "exchange-state-proof-001",
    ]
    assert client.admin_api_test_spot_recovery_completion_store.read_recent() == []
    readback = client.get(
        "/api/v1/spot/recovery/reconciliation-proof",
        params={"client_order_id": "client-order-preview"},
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    assert readback.status_code == 200
    readback_payload = readback.json()
    assert readback_payload["persisted_proof_count"] == 2
    assert readback_payload["persisted_completion_count"] == 0
    assert readback_payload["post_apply_reconciliation_completion_available"] is True
    assert readback_payload["latest_completion_id"] is None
    assert readback_payload["latest_exchange_state_proof_id"] == (
        "exchange-state-proof-001"
    )
    assert readback_payload["latest_reconciliation_proof_id"] == (
        "reconciliation-proof-001"
    )
    assert all(
        proof["required_permission"] == AdminApiPermission.SPOT_RECOVERY_RECORD.value
        for proof in readback_payload["persisted_proofs"]
    )
    assert readback_payload["live_coinbase_orders_ran"] is False
    assert readback_payload["live_coinbase_read_ran"] is False

    audit_rows = client.admin_api_test_audit_store.read_recent(limit=40)
    proof_audit_rows = [
        row
        for row in audit_rows
        if row.permission == AdminApiPermission.SPOT_RECOVERY_RECORD
        and row.endpoint
        in {
            "POST /api/v1/spot/recovery/exchange-state-proofs",
            "POST /api/v1/spot/recovery/reconciliation-proofs",
        }
    ]
    assert {row.audit_id for row in proof_audit_rows} >= {
        exchange_payload["audit_id"],
        reconciliation_payload["audit_id"],
    }
    assert all(row.coinbase_order_id is None for row in proof_audit_rows)
    assert all(
        row.admission_decision is not None
        and row.admission_decision.live_exchange_submitted is False
        for row in proof_audit_rows
    )


@pytest.mark.regression
def test_admin_api_spot_recovery_exchange_state_snapshot_records_are_no_live(
    monkeypatch,
):
    import configuration

    def poison(*_args, **_kwargs):
        raise AssertionError("snapshot boundary must not contact Coinbase")

    monkeypatch.setattr(configuration, "get_rest_client", poison)

    client = _client(monkeypatch)
    snapshot_path = "/api/v1/spot/recovery/exchange-state-snapshots"
    snapshot_body = {
        "client_order_id": "client-order-snapshot",
        "product_id": "BTC-USDC",
        "exchange_state_snapshot_id": "exchange-state-snapshot-001",
        "source_timestamp": "2026-06-13T00:00:00+00:00",
        "snapshot_source": SpotRecoveryExchangeStateSnapshotSource.TEST_EVIDENCE.value,
        "snapshot_evidence_ref": "local-snapshot-evidence-ref-001",
        "reconciliation_plan_id": "reconciliation-plan-snapshot-001",
        "reconciliation_proof_id": "reconciliation-proof-snapshot-001",
        "completion_id": "completion-snapshot-001",
        "approval_snapshot_id": "approval-snapshot-001",
        "admission_audit_id": "admission-audit-snapshot-001",
        "cap_guard_decision_id": "cap-guard-snapshot-001",
        "dry_run": True,
        "operator_reason": "snapshot contract evidence only",
        "manual_live_acknowledgement": False,
    }

    denied = client.post(
        snapshot_path,
        json=snapshot_body,
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    assert denied.status_code == 403
    assert denied.json()["live_coinbase_orders_ran"] is False

    rejected_order_id = client.post(
        snapshot_path,
        json={**snapshot_body, "order_id": "exchange-order-id"},
        headers=_headers(
            idempotency_key="spot-recovery-snapshot-order-id-rejected",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert rejected_order_id.status_code == 422

    missing_prereq = client.post(
        snapshot_path,
        json=snapshot_body,
        headers=_headers(
            idempotency_key="spot-recovery-snapshot-missing-prereq",
            operator_intent="spot_recovery_contract_review",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert missing_prereq.status_code == 400
    assert missing_prereq.json()["status"] == AdminApiCommandStatus.REJECTED.value
    assert missing_prereq.json()["data"]["snapshot_recorded"] is False
    assert missing_prereq.json()["data"]["coinbase_read_attempted"] is False
    assert client.admin_api_test_spot_recovery_snapshot_store.read_recent() == []

    snapshot_payload_hash = _spot_recovery_snapshot_payload_hash(
        endpoint=f"POST {snapshot_path}",
        body=snapshot_body,
    )
    _append_spot_recovery_proof_admission_chain(
        approval_store=client.admin_api_test_approval_store,
        audit_store=client.admin_api_test_audit_store,
        cap_guard_store=client.admin_api_test_cap_guard_store,
        reconciliation_store=client.admin_api_test_reconciliation_store,
        route=snapshot_path,
        service_method="record_spot_recovery_exchange_state_snapshot",
        client_order_id=snapshot_body["client_order_id"],
        idempotency_key="spot-recovery-snapshot-001",
        operator_intent="spot_recovery_contract_review",
        payload_hash=snapshot_payload_hash,
        approval_snapshot_id=snapshot_body["approval_snapshot_id"],
        admission_audit_id=snapshot_body["admission_audit_id"],
        cap_guard_decision_id=snapshot_body["cap_guard_decision_id"],
        reconciliation_plan_id=snapshot_body["reconciliation_plan_id"],
    )
    snapshot_created = client.post(
        snapshot_path,
        json=snapshot_body,
        headers=_headers(
            idempotency_key="spot-recovery-snapshot-001",
            operator_intent="spot_recovery_contract_review",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert snapshot_created.status_code == 200
    snapshot_payload = snapshot_created.json()
    assert snapshot_payload["status"] == AdminApiCommandStatus.ACCEPTED.value
    assert snapshot_payload["required_permission"] == (
        AdminApiPermission.SPOT_RECOVERY_RECORD.value
    )
    assert snapshot_payload["data"]["exchange_state_snapshot_id"] == (
        "exchange-state-snapshot-001"
    )
    assert snapshot_payload["data"]["product_id"] == "BTC-USDC"
    assert snapshot_payload["data"]["source_timestamp"] == (
        "2026-06-13T00:00:00+00:00"
    )
    assert snapshot_payload["data"]["snapshot_recorded"] is True
    assert snapshot_payload["data"]["source_trusted"] is False
    assert snapshot_payload["data"]["coinbase_read_attempted"] is False
    assert snapshot_payload["data"]["coinbase_read_succeeded"] is False
    assert snapshot_payload["data"]["coinbase_rest_read_ran"] is False
    assert snapshot_payload["data"]["order_state_mutated"] is False
    assert snapshot_payload["data"]["exchange_state_mutated"] is False
    assert snapshot_payload["data"]["reconciliation_executed"] is False
    assert snapshot_payload["live_exchange_submitted"] is False
    assert '"order_id"' not in json.dumps(snapshot_payload)

    snapshot_replay = client.post(
        snapshot_path,
        json=snapshot_body,
        headers=_headers(
            idempotency_key="spot-recovery-snapshot-001",
            operator_intent="spot_recovery_contract_review",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert snapshot_replay.status_code == 200
    assert snapshot_replay.headers["X-Idempotency-Replayed"] == "true"
    assert snapshot_replay.json()["audit_id"] == snapshot_payload["audit_id"]

    snapshot_records = (
        client.admin_api_test_spot_recovery_snapshot_store.read_recent()
    )
    assert [record.exchange_state_snapshot_id for record in snapshot_records] == [
        "exchange-state-snapshot-001"
    ]
    assert snapshot_records[0].client_order_id == "client-order-snapshot"
    assert snapshot_records[0].product_id == "BTC-USDC"
    assert snapshot_records[0].coinbase_read_attempted is False
    assert snapshot_records[0].coinbase_read_succeeded is False

    readback = client.get(
        "/api/v1/spot/recovery/reconciliation-proof",
        params={"client_order_id": "client-order-snapshot"},
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    assert readback.status_code == 200
    readback_payload = readback.json()
    assert readback_payload["exchange_state_snapshot_contract_available"] is True
    assert readback_payload["persisted_snapshot_count"] == 1
    assert readback_payload["latest_exchange_state_snapshot_id"] == (
        "exchange-state-snapshot-001"
    )
    persisted_snapshot = readback_payload["persisted_snapshots"][0]
    assert persisted_snapshot["client_order_id"] == "client-order-snapshot"
    assert persisted_snapshot["product_id"] == "BTC-USDC"
    assert persisted_snapshot["snapshot_source"] == (
        SpotRecoveryExchangeStateSnapshotSource.TEST_EVIDENCE.value
    )
    assert persisted_snapshot["source_trusted"] is False
    assert persisted_snapshot["coinbase_read_attempted"] is False
    assert persisted_snapshot["coinbase_read_succeeded"] is False
    assert persisted_snapshot["coinbase_rest_read_ran"] is False
    boundary = readback_payload["reconciliation_execution_boundaries"][0]
    assert boundary["exchange_state_snapshot_id"] == "exchange-state-snapshot-001"
    assert boundary["product_id"] == "BTC-USDC"
    assert boundary["source_timestamp"] == "2026-06-13T00:00:00+00:00"
    assert boundary["snapshot_recorded"] is True
    assert boundary["source_trusted"] is False
    assert "exchange_state_snapshot_id_missing" not in boundary["blockers"]
    assert "coinbase_evidence_snapshot_contract_missing" not in boundary["blockers"]
    assert "coinbase_live_read_disabled" in boundary["blockers"]
    assert boundary["coinbase_rest_read_allowed"] is False
    assert boundary["coinbase_rest_read_ran"] is False
    assert readback_payload["live_coinbase_orders_ran"] is False
    assert readback_payload["live_coinbase_read_ran"] is False
    assert '"order_id"' not in json.dumps(readback_payload)

    audit_rows = client.admin_api_test_audit_store.read_recent(limit=40)
    snapshot_audit_rows = [
        row
        for row in audit_rows
        if row.permission == AdminApiPermission.SPOT_RECOVERY_RECORD
        and row.endpoint == f"POST {snapshot_path}"
    ]
    assert {row.audit_id for row in snapshot_audit_rows} >= {
        snapshot_payload["audit_id"]
    }
    assert all(row.coinbase_order_id is None for row in snapshot_audit_rows)
    assert all(
        row.admission_decision is not None
        and row.admission_decision.live_exchange_submitted is False
        for row in snapshot_audit_rows
    )


@pytest.mark.regression
def test_admin_api_spot_recovery_reconciliation_proof_records_completion(
    monkeypatch,
):
    import configuration

    def poison(*_args, **_kwargs):
        raise AssertionError("recovery completion must not contact Coinbase")

    monkeypatch.setattr(configuration, "get_rest_client", poison)

    client = _client(monkeypatch)
    client_order_id = "client-order-completion"
    exchange_path = "/api/v1/spot/recovery/exchange-state-proofs"
    apply_path = "/api/v1/spot/recovery/apply-executions"
    proof_path = "/api/v1/spot/recovery/reconciliation-proofs"
    reconciliation_execution_path = (
        "/api/v1/spot/recovery/reconciliation-executions"
    )
    shared_approval_id = "approval-completion-001"
    shared_admission_audit_id = "admission-audit-completion-001"
    shared_cap_guard_id = "cap-guard-completion-001"
    shared_reconciliation_plan_id = "reconciliation-plan-completion-001"

    exchange_body = {
        "client_order_id": client_order_id,
        "exchange_state_proof_id": "exchange-state-proof-completion-001",
        "exchange_state_evidence_ref": "audit-workbench-ref-completion-001",
        "reconciliation_plan_id": shared_reconciliation_plan_id,
        "approval_snapshot_id": shared_approval_id,
        "admission_audit_id": shared_admission_audit_id,
        "cap_guard_decision_id": shared_cap_guard_id,
        "dry_run": True,
        "operator_reason": "completion contract evidence only",
        "manual_live_acknowledgement": False,
    }
    exchange_idempotency_key = "spot-recovery-exchange-completion-001"
    exchange_payload_hash = _spot_recovery_proof_payload_hash(
        endpoint=f"POST {exchange_path}",
        body=exchange_body,
        model=SpotRecoveryExchangeStateProofRequest,
    )
    _append_spot_recovery_proof_admission_chain(
        approval_store=client.admin_api_test_approval_store,
        audit_store=client.admin_api_test_audit_store,
        cap_guard_store=client.admin_api_test_cap_guard_store,
        reconciliation_store=client.admin_api_test_reconciliation_store,
        route=exchange_path,
        service_method="record_spot_recovery_exchange_state_proof",
        client_order_id=client_order_id,
        idempotency_key=exchange_idempotency_key,
        operator_intent="spot_recovery_contract_review",
        payload_hash=exchange_payload_hash,
        approval_snapshot_id=shared_approval_id,
        admission_audit_id=shared_admission_audit_id,
        cap_guard_decision_id=shared_cap_guard_id,
        reconciliation_plan_id=shared_reconciliation_plan_id,
    )
    exchange_created = client.post(
        exchange_path,
        json=exchange_body,
        headers=_headers(
            idempotency_key=exchange_idempotency_key,
            operator_intent="spot_recovery_contract_review",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert exchange_created.status_code == 200

    apply_body = {
        "client_order_id": client_order_id,
        "rollback_plan_id": "rollback-plan-completion-001",
        "approval_snapshot_id": shared_approval_id,
        "admission_audit_id": shared_admission_audit_id,
        "cap_guard_decision_id": shared_cap_guard_id,
        "reconciliation_plan_id": shared_reconciliation_plan_id,
        "exchange_state_proof_id": exchange_body["exchange_state_proof_id"],
        "state_repair_requested": True,
        "dry_run": True,
        "operator_reason": "completion contract evidence only",
        "manual_live_acknowledgement": False,
    }
    repair_ids = build_spot_recovery_repair_ids(
        client_order_id=client_order_id,
        mutation_family=(
            AdminApiMutationFamilyType.SPOT_RECOVERY_APPLY_EXECUTION
        ),
        rollback_plan_id=apply_body["rollback_plan_id"],
        evidence_id=apply_body["exchange_state_proof_id"],
        reconciliation_plan_id=apply_body["reconciliation_plan_id"],
    )
    apply_body.update({
        "repair_target_id": repair_ids.repair_target_id,
        "pre_apply_snapshot_id": repair_ids.pre_apply_snapshot_id,
        "dry_run_repair_plan_id": repair_ids.dry_run_repair_plan_id,
    })
    apply_idempotency_key = "spot-recovery-apply-completion-001"
    apply_payload_hash = _spot_recovery_execution_payload_hash(
        endpoint=f"POST {apply_path}",
        body=apply_body,
        model=SpotRecoveryApplyExecutionRequest,
    )
    _append_spot_recovery_execution_admission_chain(
        approval_store=client.admin_api_test_approval_store,
        audit_store=client.admin_api_test_audit_store,
        cap_guard_store=client.admin_api_test_cap_guard_store,
        reconciliation_store=client.admin_api_test_reconciliation_store,
        route=apply_path,
        service_method="execute_spot_recovery_apply",
        client_order_id=client_order_id,
        idempotency_key=apply_idempotency_key,
        operator_intent="spot_recovery_contract_review",
        payload_hash=apply_payload_hash,
        approval_snapshot_id=shared_approval_id,
        admission_audit_id=shared_admission_audit_id,
        cap_guard_decision_id=shared_cap_guard_id,
        reconciliation_plan_id=shared_reconciliation_plan_id,
    )
    apply_created = client.post(
        apply_path,
        json=apply_body,
        headers=_headers(
            idempotency_key=apply_idempotency_key,
            operator_intent="spot_recovery_contract_review",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert apply_created.status_code == 200
    apply_payload = apply_created.json()
    assert apply_payload["data"]["repair_result_id"] == repair_ids.repair_result_id
    assert apply_payload["data"]["repair_result_journal_persisted"] is True
    assert apply_payload["data"]["state_repair_executed"] is True
    assert apply_payload["data"]["reconciliation_executed"] is False

    reconciliation_body = {
        "client_order_id": client_order_id,
        "exchange_state_proof_id": exchange_body["exchange_state_proof_id"],
        "reconciliation_proof_id": "reconciliation-proof-completion-001",
        "recovery_apply_audit_id": apply_payload["audit_id"],
        "reconciliation_plan_id": shared_reconciliation_plan_id,
        "approval_snapshot_id": shared_approval_id,
        "admission_audit_id": shared_admission_audit_id,
        "cap_guard_decision_id": shared_cap_guard_id,
        "dry_run": True,
        "operator_reason": "completion contract evidence only",
        "manual_live_acknowledgement": False,
    }
    reconciliation_idempotency_key = "spot-recovery-proof-completion-001"
    reconciliation_payload_hash = _spot_recovery_proof_payload_hash(
        endpoint=f"POST {proof_path}",
        body=reconciliation_body,
        model=SpotRecoveryReconciliationProofRecordRequest,
    )
    _append_spot_recovery_proof_admission_chain(
        approval_store=client.admin_api_test_approval_store,
        audit_store=client.admin_api_test_audit_store,
        cap_guard_store=client.admin_api_test_cap_guard_store,
        reconciliation_store=client.admin_api_test_reconciliation_store,
        route=proof_path,
        service_method="record_spot_recovery_reconciliation_proof",
        client_order_id=client_order_id,
        idempotency_key=reconciliation_idempotency_key,
        operator_intent="spot_recovery_contract_review",
        payload_hash=reconciliation_payload_hash,
        approval_snapshot_id=shared_approval_id,
        admission_audit_id=shared_admission_audit_id,
        cap_guard_decision_id=shared_cap_guard_id,
        reconciliation_plan_id=shared_reconciliation_plan_id,
    )
    reconciliation_created = client.post(
        proof_path,
        json=reconciliation_body,
        headers=_headers(
            idempotency_key=reconciliation_idempotency_key,
            operator_intent="spot_recovery_contract_review",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert reconciliation_created.status_code == 200
    reconciliation_payload = reconciliation_created.json()
    completion_id = reconciliation_payload["data"]["completion_id"]
    assert reconciliation_payload["data"]["reconciliation_proof_recorded"] is True
    assert (
        reconciliation_payload["data"][
            "post_apply_reconciliation_completion_recorded"
        ]
        is True
    )
    assert reconciliation_payload["data"]["completion_guard_passed"] is True
    assert reconciliation_payload["data"]["completion_guard_failures"] == []
    assert reconciliation_payload["data"]["post_apply_reconciliation_completed"] is True
    assert reconciliation_payload["data"]["fully_reconciled"] is True
    assert reconciliation_payload["data"]["reconciliation_executed"] is False
    assert reconciliation_payload["data"]["order_state_mutated"] is False
    assert reconciliation_payload["data"]["exchange_state_mutated"] is False
    assert reconciliation_payload["data"]["coinbase_rest_read_ran"] is False

    completion_records = (
        client.admin_api_test_spot_recovery_completion_store.read_recent(limit=20)
    )
    assert len(completion_records) == 1
    completion_record = completion_records[0]
    assert completion_record.completion_id == completion_id
    assert completion_record.mutation_family == (
        AdminApiMutationFamilyType.SPOT_RECOVERY_RECONCILIATION_COMPLETION
    )
    assert completion_record.completion_state == (
        SpotRecoveryCompletionState.FULLY_RECONCILED
    )
    assert completion_record.client_order_id == client_order_id
    assert completion_record.repair_result_id == repair_ids.repair_result_id
    assert completion_record.journal_id == apply_payload["data"]["journal_id"]
    assert completion_record.audit_id == apply_payload["audit_id"]
    assert completion_record.reconciliation_proof_id == (
        reconciliation_body["reconciliation_proof_id"]
    )
    assert completion_record.proof_audit_id == reconciliation_payload["audit_id"]
    assert completion_record.post_apply_reconciliation_completed is True
    assert completion_record.reconciliation_proof_satisfied is True
    assert completion_record.fully_reconciled is True
    assert completion_record.reconciliation_executed is False
    assert completion_record.order_state_mutated is False
    assert completion_record.exchange_state_mutated is False
    assert completion_record.live_coinbase_orders_ran is False

    snapshot_path = "/api/v1/spot/recovery/exchange-state-snapshots"
    snapshot_body = {
        "client_order_id": client_order_id,
        "product_id": "BTC-USDC",
        "exchange_state_snapshot_id": "exchange-state-snapshot-completion-001",
        "source_timestamp": "2026-06-13T00:00:00+00:00",
        "snapshot_source": SpotRecoveryExchangeStateSnapshotSource.TEST_EVIDENCE.value,
        "snapshot_evidence_ref": "local-snapshot-evidence-ref-completion-001",
        "reconciliation_plan_id": shared_reconciliation_plan_id,
        "reconciliation_proof_id": reconciliation_body["reconciliation_proof_id"],
        "completion_id": completion_id,
        "approval_snapshot_id": shared_approval_id,
        "admission_audit_id": shared_admission_audit_id,
        "cap_guard_decision_id": shared_cap_guard_id,
        "dry_run": True,
        "operator_reason": "completion snapshot contract evidence only",
        "manual_live_acknowledgement": False,
    }
    snapshot_idempotency_key = "spot-recovery-snapshot-completion-001"
    snapshot_payload_hash = _spot_recovery_snapshot_payload_hash(
        endpoint=f"POST {snapshot_path}",
        body=snapshot_body,
    )
    _append_spot_recovery_proof_admission_chain(
        approval_store=client.admin_api_test_approval_store,
        audit_store=client.admin_api_test_audit_store,
        cap_guard_store=client.admin_api_test_cap_guard_store,
        reconciliation_store=client.admin_api_test_reconciliation_store,
        route=snapshot_path,
        service_method="record_spot_recovery_exchange_state_snapshot",
        client_order_id=client_order_id,
        idempotency_key=snapshot_idempotency_key,
        operator_intent="spot_recovery_contract_review",
        payload_hash=snapshot_payload_hash,
        approval_snapshot_id=shared_approval_id,
        admission_audit_id=shared_admission_audit_id,
        cap_guard_decision_id=shared_cap_guard_id,
        reconciliation_plan_id=shared_reconciliation_plan_id,
    )
    snapshot_created = client.post(
        snapshot_path,
        json=snapshot_body,
        headers=_headers(
            idempotency_key=snapshot_idempotency_key,
            operator_intent="spot_recovery_contract_review",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert snapshot_created.status_code == 200
    assert snapshot_created.json()["data"]["snapshot_recorded"] is True
    assert snapshot_created.json()["data"]["coinbase_rest_read_ran"] is False

    readback = client.get(
        "/api/v1/spot/recovery/reconciliation-proof",
        params={"client_order_id": client_order_id},
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    assert readback.status_code == 200
    readback_payload = readback.json()
    assert readback_payload["persisted_completion_count"] == 1
    assert readback_payload["latest_completion_id"] == completion_id
    assert readback_payload["post_apply_reconciliation_completed_count"] == 1
    assert readback_payload["post_apply_reconciliation_satisfied_count"] == 1
    assert readback_payload["post_apply_reconciliation_required_count"] == 1
    assert readback_payload["post_apply_reconciliation_completion_available"] is True
    assert readback_payload["persisted_snapshot_count"] == 1
    assert readback_payload["exchange_state_snapshot_contract_available"] is True
    assert readback_payload["latest_exchange_state_snapshot_id"] == (
        snapshot_body["exchange_state_snapshot_id"]
    )
    assert readback_payload["persisted_snapshots"][0][
        "exchange_state_snapshot_id"
    ] == snapshot_body["exchange_state_snapshot_id"]
    assert readback_payload["persisted_completions"][0]["completion_id"] == completion_id
    assert readback_payload["persisted_completions"][0]["fully_reconciled"] is True
    assert readback_payload["persisted_completions"][0]["reconciliation_executed"] is False
    assert readback_payload["repair_targets"][0]["completion_ids"] == [completion_id]
    assert readback_payload["repair_targets"][0]["fully_reconciled"] is True
    assert readback_payload["completion_states"][0]["completion_id"] == completion_id
    assert readback_payload["completion_states"][0]["fully_reconciled"] is True
    assert readback_payload["completion_states"][0]["state"] == (
        SpotRecoveryCompletionState.FULLY_RECONCILED.value
    )
    assert readback_payload["reconciliation_execution_available"] is False
    assert readback_payload["reconciliation_execution_boundary_available"] is True
    assert readback_payload["reconciliation_execution_boundary_count"] == 1
    execution_boundary = readback_payload["reconciliation_execution_boundaries"][0]
    assert execution_boundary["client_order_id"] == client_order_id
    assert execution_boundary["status"] == AdminApiGateStatus.BLOCKED.value
    assert execution_boundary["mutation_family"] == (
        AdminApiMutationFamilyType.SPOT_RECOVERY_RECONCILIATION_EXECUTION.value
    )
    assert execution_boundary["completion_id"] == completion_id
    assert execution_boundary["command_route"] == (
        "/api/v1/spot/recovery/reconciliation-executions"
    )
    assert execution_boundary["method"] == "POST"
    assert execution_boundary["route_inventory_status"] == (
        AdminApiGateStatus.PASSED.value
    )
    assert execution_boundary["service_method"] == (
        "execute_spot_recovery_reconciliation"
    )
    assert execution_boundary["action_class"] == (
        AdminApiActionClass.LOCAL_STATE_MUTATION.value
    )
    assert execution_boundary["required_permission"] == (
        AdminApiPermission.SPOT_RECOVERY_EXECUTE.value
    )
    assert execution_boundary["future_action_class"] == (
        AdminApiActionClass.LOCAL_STATE_MUTATION.value
    )
    assert execution_boundary["future_required_permission"] == (
        AdminApiPermission.SPOT_RECOVERY_EXECUTE.value
    )
    assert execution_boundary["reconciliation_proof_id"] == (
        reconciliation_body["reconciliation_proof_id"]
    )
    assert execution_boundary["reconciliation_plan_id"] == (
        shared_reconciliation_plan_id
    )
    assert execution_boundary["exchange_state_snapshot_id"] == (
        snapshot_body["exchange_state_snapshot_id"]
    )
    assert execution_boundary["product_id"] == "BTC-USDC"
    assert execution_boundary["snapshot_recorded"] is True
    assert execution_boundary["coinbase_read_attempted"] is False
    assert execution_boundary["approval_snapshot_id"] == shared_approval_id
    assert execution_boundary["admission_audit_id"] == shared_admission_audit_id
    assert execution_boundary["cap_guard_decision_id"] == shared_cap_guard_id
    assert execution_boundary["idempotency_key"] == snapshot_idempotency_key
    assert execution_boundary["payload_hash"] == snapshot_payload_hash
    assert execution_boundary["operator_intent"] == "spot_recovery_contract_review"
    assert execution_boundary["missing_inputs"] == []
    assert "spot_reconciliation_execution_contract" in (
        execution_boundary["missing_contracts"]
    )
    assert "reconciliation_executor_disabled" in execution_boundary["blockers"]
    assert "coinbase_live_read_disabled" in execution_boundary["blockers"]
    assert "coinbase_evidence_snapshot_contract_missing" not in (
        execution_boundary["blockers"]
    )
    assert "spot_reconciliation_execution_route_missing" not in (
        execution_boundary["blockers"]
    )
    assert "spot_reconciliation_execution_service_missing" not in (
        execution_boundary["blockers"]
    )
    assert execution_boundary["route_bound"] is True
    assert execution_boundary["read_only"] is True
    assert execution_boundary["local_state_reconciliation_allowed"] is False
    assert execution_boundary["order_state_mutation_allowed"] is False
    assert execution_boundary["exchange_state_mutation_allowed"] is False
    assert execution_boundary["coinbase_rest_read_allowed"] is False
    assert execution_boundary["coinbase_order_submission_allowed"] is False
    assert execution_boundary["reconciliation_executed"] is False
    assert execution_boundary["coinbase_rest_read_ran"] is False
    assert execution_boundary["live_coinbase_orders_ran"] is False
    assert readback_payload["latest_reconciliation_execution_boundary_id"] == (
        execution_boundary["boundary_id"]
    )
    assert "spot_reconciliation_execution_contract" in (
        readback_payload["missing_contracts"]
    )
    assert readback_payload["live_coinbase_orders_ran"] is False
    assert readback_payload["live_coinbase_read_ran"] is False
    assert '"order_id"' not in json.dumps(readback_payload)

    reconciliation_execution_body = {
        "client_order_id": client_order_id,
        "product_id": "BTC-USDC",
        "exchange_state_snapshot_id": snapshot_body["exchange_state_snapshot_id"],
        "reconciliation_plan_id": shared_reconciliation_plan_id,
        "reconciliation_proof_id": reconciliation_body["reconciliation_proof_id"],
        "completion_id": completion_id,
        "approval_snapshot_id": shared_approval_id,
        "admission_audit_id": shared_admission_audit_id,
        "cap_guard_decision_id": shared_cap_guard_id,
        "dry_run": True,
        "operator_reason": "disabled reconciliation execution boundary only",
        "manual_live_acknowledgement": False,
    }
    rejected_order_id_body = {
        **reconciliation_execution_body,
        "order_id": "exchange-order-id-is-not-internal-identity",
    }
    rejected_order_id = client.post(
        reconciliation_execution_path,
        json=rejected_order_id_body,
        headers=_headers(
            idempotency_key="spot-recovery-reconcile-exec-order-id",
            operator_intent="spot_recovery_contract_review",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert rejected_order_id.status_code == 422

    viewer_rejected = client.post(
        reconciliation_execution_path,
        json=reconciliation_execution_body,
        headers=_headers(
            idempotency_key="spot-recovery-reconcile-exec-viewer",
            operator_intent="spot_recovery_contract_review",
            roles=AdminApiRole.VIEWER.value,
        ),
    )
    assert viewer_rejected.status_code == 403

    reconciliation_execution_idempotency_key = (
        "spot-recovery-reconcile-exec-completion-001"
    )
    reconciliation_execution_payload_hash = _spot_recovery_execution_payload_hash(
        endpoint=f"POST {reconciliation_execution_path}",
        body=reconciliation_execution_body,
        model=SpotRecoveryReconciliationExecutionRequest,
    )
    _append_spot_recovery_execution_admission_chain(
        approval_store=client.admin_api_test_approval_store,
        audit_store=client.admin_api_test_audit_store,
        cap_guard_store=client.admin_api_test_cap_guard_store,
        reconciliation_store=client.admin_api_test_reconciliation_store,
        route=reconciliation_execution_path,
        service_method="execute_spot_recovery_reconciliation",
        client_order_id=client_order_id,
        idempotency_key=reconciliation_execution_idempotency_key,
        operator_intent="spot_recovery_contract_review",
        payload_hash=reconciliation_execution_payload_hash,
        approval_snapshot_id=shared_approval_id,
        admission_audit_id=shared_admission_audit_id,
        cap_guard_decision_id=shared_cap_guard_id,
        reconciliation_plan_id=shared_reconciliation_plan_id,
    )
    reconciliation_execution_response = client.post(
        reconciliation_execution_path,
        json=reconciliation_execution_body,
        headers=_headers(
            idempotency_key=reconciliation_execution_idempotency_key,
            operator_intent="spot_recovery_contract_review",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert reconciliation_execution_response.status_code == 400
    reconciliation_execution_payload = reconciliation_execution_response.json()
    assert reconciliation_execution_payload["status"] == (
        AdminApiCommandStatus.REJECTED.value
    )
    assert reconciliation_execution_payload["service_method"] == (
        "execute_spot_recovery_reconciliation"
    )
    assert reconciliation_execution_payload["action_class"] == (
        AdminApiActionClass.LOCAL_STATE_MUTATION.value
    )
    assert reconciliation_execution_payload["required_permission"] == (
        AdminApiPermission.SPOT_RECOVERY_EXECUTE.value
    )
    assert reconciliation_execution_payload["client_order_id"] == client_order_id
    assert reconciliation_execution_payload["live_exchange_submitted"] is False
    assert reconciliation_execution_payload["failure_stage"] == (
        "execution_prerequisite"
    )
    assert reconciliation_execution_payload["admission_decision"]["allowed"] is (
        False
    )
    assert reconciliation_execution_payload["data"]["mutation_family"] == (
        AdminApiMutationFamilyType.SPOT_RECOVERY_RECONCILIATION_EXECUTION.value
    )
    assert reconciliation_execution_payload["data"]["completion_id"] == completion_id
    assert reconciliation_execution_payload["data"]["product_id"] == "BTC-USDC"
    assert reconciliation_execution_payload["data"]["exchange_state_snapshot_id"] == (
        snapshot_body["exchange_state_snapshot_id"]
    )
    assert reconciliation_execution_payload["data"]["reconciliation_proof_id"] == (
        reconciliation_body["reconciliation_proof_id"]
    )
    assert reconciliation_execution_payload["data"][
        "reconciliation_execution_route_bound"
    ] is True
    assert reconciliation_execution_payload["data"][
        "reconciliation_execution_service_available"
    ] is False
    assert reconciliation_execution_payload["data"][
        "reconciliation_execution_contract_available"
    ] is False
    assert reconciliation_execution_payload["data"][
        "coinbase_evidence_snapshot_contract_available"
    ] is True
    assert reconciliation_execution_payload["data"]["reconciliation_executed"] is (
        False
    )
    assert reconciliation_execution_payload["data"]["order_state_mutated"] is False
    assert reconciliation_execution_payload["data"]["exchange_state_mutated"] is False
    assert reconciliation_execution_payload["data"]["coinbase_rest_read_ran"] is False
    assert reconciliation_execution_payload["data"]["coinbase_order_submitted"] is (
        False
    )
    assert reconciliation_execution_payload["data"]["browser_authority"] == (
        "display_only"
    )
    assert reconciliation_execution_payload["data"]["bff_authority"] == (
        "forward_only_no_execution"
    )
    assert '"order_id"' not in json.dumps(reconciliation_execution_payload)

    reconciliation_execution_replay = client.post(
        reconciliation_execution_path,
        json=reconciliation_execution_body,
        headers=_headers(
            idempotency_key=reconciliation_execution_idempotency_key,
            operator_intent="spot_recovery_contract_review",
            roles=AdminApiRole.TRADER.value,
        ),
    )
    assert reconciliation_execution_replay.status_code == 400
    assert (
        reconciliation_execution_replay.headers["X-Idempotency-Replayed"]
        == "true"
    )
    assert reconciliation_execution_replay.json()["audit_id"] == (
        reconciliation_execution_payload["audit_id"]
    )

    execution_audit_rows = [
        row
        for row in client.admin_api_test_audit_store.read_recent(limit=80)
        if row.endpoint
        == "POST /api/v1/spot/recovery/reconciliation-executions"
        and row.request_id == "corr-001"
    ]
    assert len(execution_audit_rows) == 1
    assert execution_audit_rows[0].permission == (
        AdminApiPermission.SPOT_RECOVERY_EXECUTE
    )
    assert execution_audit_rows[0].coinbase_order_id is None
    assert execution_audit_rows[0].admission_decision is not None
    assert execution_audit_rows[0].admission_decision.live_exchange_submitted is (
        False
    )

    apply_review = client.get(
        "/api/v1/spot/recovery/apply-review",
        params={"client_order_id": client_order_id},
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    assert apply_review.status_code == 200
    apply_review_payload = apply_review.json()
    assert apply_review_payload["missing_contracts"] == []
    assert apply_review_payload["completion_states"][0]["fully_reconciled"] is True


@pytest.mark.regression
def test_admin_api_spot_recovery_preview_docs_and_inventory_boundaries_exist():
    from application.admin_api.read_service import AdminApiReadService

    response = AdminApiReadService().build_spot_recovery_preview()
    documentation_refs = set()
    for source in response.sources:
        documentation_refs.update(source.documentation_refs)

    assert "docs/OPERATOR_READ_MODELS.md" in documentation_refs
    for documentation_ref in documentation_refs:
        assert (ROOT / documentation_ref).exists(), documentation_ref

    route_inventory_item = next(
        item
        for item in ADMIN_API_ROUTE_INVENTORY
        if item.surface == "GET /api/v1/spot/recovery/preview"
    )
    assert "Coinbase read" in route_inventory_item.parity_test
    assert "Coinbase REST placement" in route_inventory_item.parity_test


@pytest.mark.regression
def test_admin_api_order_read_routes_use_read_service_and_client_order_id(monkeypatch):
    from api.v1.routes import orders as order_routes

    client = _client(monkeypatch)
    service = SimpleNamespace(
        build_order_list=lambda product_id=None, status=None, limit=100, offset=0: {
            "type": "admin_order_list",
            "filters": {
                "product_id": product_id,
                "status": status,
                "limit": limit,
                "offset": offset,
            },
            "count": 1,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "returned_count": 1,
                "total_matching_count": 2,
                "next_offset": offset + 1,
                "has_more": True,
            },
            "items": [
                {
                    "client_order_id": "client-abc",
                    "product_id": "BTC-USDC",
                    "exchange_order_id": "coinbase-evidence-001",
                    "exchange_order_id_evidence_only": True,
                    "correlation_id": "corr-order-read",
                    "audit_id": "audit-order-read",
                }
            ],
            "read_only": True,
            "live_coinbase_orders_ran": False,
        },
        build_order_detail=lambda client_order_id: {
            "type": "admin_order_detail",
            "client_order_id": client_order_id,
            "found": True,
            "order": {
                "client_order_id": client_order_id,
                "exchange_order_id": "coinbase-evidence-001",
                "exchange_order_id_evidence_only": True,
                "correlation_id": "corr-order-detail",
                "audit_id": "audit-order-detail",
            },
            "read_only": True,
            "live_coinbase_orders_ran": False,
        },
    )
    client.app.dependency_overrides[order_routes.get_read_service] = lambda: service

    list_response = client.get(
        "/api/v1/orders?product_id=BTC-USDC&order_status=OPEN&limit=10&offset=20",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    detail_response = client.get(
        "/api/v1/orders/client-abc",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )

    assert list_response.status_code == 200
    assert list_response.json()["filters"]["offset"] == 20
    assert list_response.json()["pagination"]["next_offset"] == 21
    assert list_response.json()["items"][0]["client_order_id"] == "client-abc"
    assert list_response.json()["items"][0]["exchange_order_id_evidence_only"] is True
    assert list_response.json()["items"][0]["correlation_id"] == "corr-order-read"
    assert list_response.json()["items"][0]["audit_id"] == "audit-order-read"
    assert "order_id" not in list_response.json()["items"][0]
    assert detail_response.status_code == 200
    assert detail_response.json()["client_order_id"] == "client-abc"
    assert detail_response.json()["order"]["correlation_id"] == "corr-order-detail"
    assert detail_response.json()["order"]["audit_id"] == "audit-order-detail"
    assert "order_id" not in detail_response.json()["order"]


@pytest.mark.regression
def test_admin_api_order_list_read_service_returns_pagination_metadata(monkeypatch):
    import database.order as order_module

    from application.admin_api.read_service import AdminApiReadService

    rows = [
        {
            "client_order_id": f"client-{index}",
            "product_id": "BTC-USDC",
            "status": "OPEN",
            "correlation_id": f"corr-{index}",
            "audit_id": f"audit-{index}",
        }
        for index in range(5)
    ]
    monkeypatch.setattr(order_module, "get_parent_orders", lambda: rows)

    response = AdminApiReadService().build_order_list(
        product_id="BTC-USDC",
        status="OPEN",
        limit=2,
        offset=1,
    )

    assert response.count == 2
    assert [item.client_order_id for item in response.items] == ["client-1", "client-2"]
    assert response.items[0].correlation_id == "corr-1"
    assert response.items[0].audit_id == "audit-1"
    assert response.pagination.limit == 2
    assert response.pagination.offset == 1
    assert response.pagination.returned_count == 2
    assert response.pagination.total_matching_count == 5
    assert response.pagination.next_offset == 3
    assert response.pagination.has_more is True


@pytest.mark.regression
def test_admin_api_stealth_read_routes_use_read_service_without_commands(monkeypatch):
    from api.v1.routes import stealth as stealth_routes

    client = _client(monkeypatch)
    service = SimpleNamespace(
        build_stealth_order_list=lambda product_id=None, status=None, limit=100, offset=0: {
            "type": "admin_stealth_order_list",
            "filters": {
                "product_id": product_id,
                "status": status,
                "limit": limit,
                "offset": offset,
            },
            "count": 1,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "returned_count": 1,
                "total_matching_count": 1,
                "next_offset": None,
                "has_more": False,
            },
            "items": [
                {
                    "stealth_order_id": "stealth-abc",
                    "product_id": "BTC-USDC",
                    "status": "REVEALED",
                    "active_placement_client_order_id": "placement-client-1",
                    "active_exchange_order_id": "exchange-evidence-1",
                    "exchange_order_id_evidence_only": True,
                }
            ],
            "read_only": True,
            "command_routes_mode": AdminApiCommandRoutesMode.LIVE_DISABLED.value,
            "live_coinbase_orders_ran": False,
        },
        build_stealth_order_detail=lambda stealth_order_id: {
            "type": "admin_stealth_order_detail",
            "stealth_order_id": stealth_order_id,
            "found": True,
            "order": {
                "stealth_order_id": stealth_order_id,
                "active_placement_client_order_id": "placement-client-1",
                "active_exchange_order_id": "exchange-evidence-1",
                "exchange_order_id_evidence_only": True,
            },
            "active_placement_audit": {
                "stealth_order_id": stealth_order_id,
                "status": AdminApiGateStatus.BLOCKED.value,
                "active_placement_present": True,
                "active_placement_client_order_id": "placement-client-1",
                "active_exchange_order_id": "exchange-evidence-1",
                "exchange_order_id_evidence_only": True,
                "exchange_truth_verified": False,
                "exchange_truth_source": "local_stealth_state_only",
                "coinbase_read_required": True,
                "coinbase_read_ran": False,
                "coinbase_order_cancel_submitted": False,
                "lifecycle_mutation_allowed": False,
                "required_for_mutation_families": [
                    AdminApiMutationFamilyType.STEALTH_CANCEL.value,
                    AdminApiMutationFamilyType.STEALTH_MOVE.value,
                    AdminApiMutationFamilyType.MOVEMENT_REPRICE.value,
                ],
                "read_evidence_routes": [
                    "/api/v1/stealth/orders/{stealth_order_id}",
                    "/api/v1/stealth/command-suite",
                ],
                "required_contracts": [
                    "stealth_active_placement_exchange_truth_read_contract",
                    "stealth_active_placement_cancel_replace_audit",
                    "stealth_active_placement_reconciliation_proof",
                ],
                "missing_contracts": [
                    "stealth_active_placement_exchange_truth_read_contract",
                    "stealth_active_placement_cancel_replace_audit",
                    "stealth_active_placement_reconciliation_proof",
                ],
                "blockers": [
                    "coinbase_exchange_truth_read_disabled",
                    "stealth_active_placement_cancel_replace_audit_missing",
                    "stealth_active_placement_reconciliation_proof_missing",
                ],
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                "detail": "Active placement audit remains no-live.",
            },
            "mutation_claim_audit": {
                "stealth_order_id": stealth_order_id,
                "status": AdminApiGateStatus.BLOCKED.value,
                "runtime_claims": [
                    {
                        "kind": StealthMutationKind.MOVE.value,
                        "state": None,
                        "runtime_observed": False,
                        "source": "runtime_stealth_manager_unavailable",
                    },
                    {
                        "kind": StealthMutationKind.REPRICE.value,
                        "state": None,
                        "runtime_observed": False,
                        "source": "runtime_stealth_manager_unavailable",
                    },
                    {
                        "kind": StealthMutationKind.RETREAT.value,
                        "state": None,
                        "runtime_observed": False,
                        "source": "runtime_stealth_manager_unavailable",
                    },
                ],
                "runtime_claims_observed": False,
                "runtime_claim_count": 3,
                "active_claim_count": 0,
                "claim_reader_source": "runtime_stealth_manager_unavailable",
                "claim_reader_ran": False,
                "coinbase_read_ran": False,
                "coinbase_order_cancel_submitted": False,
                "lifecycle_mutation_allowed": False,
                "required_for_mutation_families": [
                    AdminApiMutationFamilyType.STEALTH_MOVE.value,
                    AdminApiMutationFamilyType.MOVEMENT_REPRICE.value,
                ],
                "read_evidence_routes": [
                    "/api/v1/stealth/orders/{stealth_order_id}",
                    "/api/v1/movement-repricing/stealth/{stealth_order_id}",
                    "/api/v1/stealth/command-suite",
                ],
                "required_contracts": [
                    "stealth_move_mutation_claim_snapshot_contract",
                    "stealth_reprice_cooldown_claim_contract",
                ],
                "missing_contracts": [
                    "stealth_move_mutation_claim_snapshot_contract",
                    "stealth_reprice_cooldown_claim_contract",
                ],
                "blockers": [
                    "runtime_mutation_claim_snapshot_unavailable",
                    "stealth_move_mutation_claim_snapshot_contract_missing",
                    "stealth_reprice_cooldown_claim_contract_missing",
                ],
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                "detail": "Mutation-claim audit remains no-live.",
            },
            "reveal_trigger_audit": {
                "stealth_order_id": stealth_order_id,
                "status": AdminApiGateStatus.BLOCKED.value,
                "reveal_condition_present": True,
                "reveal_condition_type": "price_threshold",
                "reveal_condition": {"type": "price_threshold"},
                "trigger_state_source": "local_stealth_row_only",
                "trigger_evaluation_ran": False,
                "should_trigger_reveal_called": False,
                "reveal_order_slice_called": False,
                "coinbase_order_submit_ran": False,
                "lifecycle_mutation_allowed": False,
                "required_for_mutation_families": [
                    AdminApiMutationFamilyType.STEALTH_REVEAL.value,
                ],
                "read_evidence_routes": [
                    "/api/v1/stealth/orders/{stealth_order_id}",
                    "/api/v1/stealth/command-suite",
                ],
                "required_contracts": ["stealth_reveal_trigger_guard"],
                "missing_contracts": ["stealth_reveal_trigger_guard"],
                "blockers": ["stealth_reveal_trigger_guard_missing"],
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                "detail": "Reveal-trigger audit remains no-live.",
            },
            "reveal_submission_audit": {
                "stealth_order_id": stealth_order_id,
                "status": AdminApiGateStatus.BLOCKED.value,
                "command_route": "/api/v1/stealth/orders/{stealth_order_id}/reveal",
                "service_method": "reveal_stealth_order_by_stealth_order_id",
                "reveal_manager_method": (
                    "core/stealth_order_manager.py::reveal_order_slice"
                ),
                "submission_adapter_configured": False,
                "route_bound": True,
                "backend_owned": True,
                "existing_active_placement_present": True,
                "active_placement_client_order_id": "placement-client-1",
                "active_exchange_order_id": "exchange-evidence-1",
                "exchange_order_id_evidence_only": True,
                "reveal_order_slice_called": False,
                "coinbase_order_submit_ran": False,
                "coinbase_order_cancel_submitted": False,
                "live_coinbase_read_ran": False,
                "active_placement_created": False,
                "lifecycle_mutation_allowed": False,
                "reconciliation_required": True,
                "reconciliation_executed": False,
                "required_for_mutation_families": [
                    AdminApiMutationFamilyType.STEALTH_REVEAL.value,
                ],
                "read_evidence_routes": [
                    "/api/v1/stealth/orders/{stealth_order_id}",
                    "/api/v1/stealth/command-suite",
                ],
                "required_contracts": [
                    "stealth_reveal_exchange_submission_adapter",
                    "stealth_reveal_reconciliation_proof",
                ],
                "missing_contracts": [
                    "stealth_reveal_exchange_submission_adapter",
                    "stealth_reveal_reconciliation_proof",
                ],
                "blockers": [
                    "existing_active_placement_local_evidence_present",
                    "stealth_reveal_exchange_submission_adapter_missing",
                    "stealth_reveal_reconciliation_proof_missing",
                    "live_execution_disabled",
                ],
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                "detail": "Reveal submission-adapter audit remains no-live.",
            },
            "read_only": True,
            "command_routes_mode": AdminApiCommandRoutesMode.LIVE_DISABLED.value,
            "live_coinbase_orders_ran": False,
        },
    )
    client.app.dependency_overrides[stealth_routes.get_read_service] = lambda: service

    list_response = client.get(
        "/api/v1/stealth/orders?product_id=BTC-USDC&stealth_status=REVEALED&limit=10&offset=0",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    detail_response = client.get(
        "/api/v1/stealth/orders/stealth-abc",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )

    assert list_response.status_code == 200
    assert list_response.json()["filters"]["status"] == "REVEALED"
    assert list_response.json()["command_routes_mode"] == (
        AdminApiCommandRoutesMode.LIVE_DISABLED.value
    )
    assert list_response.json()["items"][0]["stealth_order_id"] == "stealth-abc"
    assert list_response.json()["items"][0]["active_placement_client_order_id"] == (
        "placement-client-1"
    )
    assert list_response.json()["items"][0]["active_exchange_order_id"] == (
        "exchange-evidence-1"
    )
    assert list_response.json()["items"][0]["exchange_order_id_evidence_only"] is True
    assert "order_id" not in list_response.json()["items"][0]
    assert detail_response.status_code == 200
    assert detail_response.json()["order"]["stealth_order_id"] == "stealth-abc"
    assert detail_response.json()["command_routes_mode"] == (
        AdminApiCommandRoutesMode.LIVE_DISABLED.value
    )
    audit = detail_response.json()["active_placement_audit"]
    assert audit["active_placement_present"] is True
    assert audit["active_placement_client_order_id"] == "placement-client-1"
    assert audit["active_exchange_order_id"] == "exchange-evidence-1"
    assert audit["exchange_truth_verified"] is False
    assert audit["coinbase_read_required"] is True
    assert audit["coinbase_read_ran"] is False
    assert audit["coinbase_order_cancel_submitted"] is False
    assert audit["lifecycle_mutation_allowed"] is False
    assert audit["required_for_mutation_families"] == [
        AdminApiMutationFamilyType.STEALTH_CANCEL.value,
        AdminApiMutationFamilyType.STEALTH_MOVE.value,
        AdminApiMutationFamilyType.MOVEMENT_REPRICE.value,
    ]
    assert audit["required_contracts"] == audit["missing_contracts"]
    mutation_claim_audit = detail_response.json()["mutation_claim_audit"]
    assert mutation_claim_audit["runtime_claims_observed"] is False
    assert mutation_claim_audit["runtime_claim_count"] == 3
    assert mutation_claim_audit["active_claim_count"] == 0
    assert mutation_claim_audit["claim_reader_source"] == (
        "runtime_stealth_manager_unavailable"
    )
    assert mutation_claim_audit["claim_reader_ran"] is False
    assert mutation_claim_audit["coinbase_read_ran"] is False
    assert mutation_claim_audit["coinbase_order_cancel_submitted"] is False
    assert mutation_claim_audit["lifecycle_mutation_allowed"] is False
    assert mutation_claim_audit["required_for_mutation_families"] == [
        AdminApiMutationFamilyType.STEALTH_MOVE.value,
        AdminApiMutationFamilyType.MOVEMENT_REPRICE.value,
    ]
    assert mutation_claim_audit["required_contracts"] == (
        mutation_claim_audit["missing_contracts"]
    )
    reveal_trigger_audit = detail_response.json()["reveal_trigger_audit"]
    assert reveal_trigger_audit["reveal_condition_present"] is True
    assert reveal_trigger_audit["reveal_condition_type"] == "price_threshold"
    assert reveal_trigger_audit["trigger_state_source"] == "local_stealth_row_only"
    assert reveal_trigger_audit["trigger_evaluation_ran"] is False
    assert reveal_trigger_audit["should_trigger_reveal_called"] is False
    assert reveal_trigger_audit["reveal_order_slice_called"] is False
    assert reveal_trigger_audit["coinbase_order_submit_ran"] is False
    assert reveal_trigger_audit["lifecycle_mutation_allowed"] is False
    assert reveal_trigger_audit["required_for_mutation_families"] == [
        AdminApiMutationFamilyType.STEALTH_REVEAL.value,
    ]
    assert reveal_trigger_audit["required_contracts"] == (
        reveal_trigger_audit["missing_contracts"]
    )
    reveal_submission_audit = detail_response.json()["reveal_submission_audit"]
    assert reveal_submission_audit["command_route"] == (
        "/api/v1/stealth/orders/{stealth_order_id}/reveal"
    )
    assert reveal_submission_audit["service_method"] == (
        "reveal_stealth_order_by_stealth_order_id"
    )
    assert reveal_submission_audit["reveal_manager_method"].endswith(
        "::reveal_order_slice"
    )
    assert reveal_submission_audit["submission_adapter_configured"] is False
    assert reveal_submission_audit["route_bound"] is True
    assert reveal_submission_audit["backend_owned"] is True
    assert reveal_submission_audit["existing_active_placement_present"] is True
    assert reveal_submission_audit["active_placement_client_order_id"] == (
        "placement-client-1"
    )
    assert reveal_submission_audit["active_exchange_order_id"] == "exchange-evidence-1"
    assert reveal_submission_audit["reveal_order_slice_called"] is False
    assert reveal_submission_audit["coinbase_order_submit_ran"] is False
    assert reveal_submission_audit["coinbase_order_cancel_submitted"] is False
    assert reveal_submission_audit["live_coinbase_read_ran"] is False
    assert reveal_submission_audit["active_placement_created"] is False
    assert reveal_submission_audit["lifecycle_mutation_allowed"] is False
    assert reveal_submission_audit["reconciliation_required"] is True
    assert reveal_submission_audit["reconciliation_executed"] is False
    assert reveal_submission_audit["required_for_mutation_families"] == [
        AdminApiMutationFamilyType.STEALTH_REVEAL.value,
    ]
    assert reveal_submission_audit["required_contracts"] == (
        reveal_submission_audit["missing_contracts"]
    )
    assert "existing_active_placement_local_evidence_present" in (
        reveal_submission_audit["blockers"]
    )
    assert reveal_submission_audit["browser_authority"] == "display_only"
    assert reveal_submission_audit["bff_authority"] == "forward_only_no_execution"
    assert detail_response.json()["live_coinbase_orders_ran"] is False


@pytest.mark.regression
def test_admin_api_stealth_read_service_maps_placement_and_exchange_evidence(monkeypatch):
    import database.order as order_module

    from application.admin_api.read_service import AdminApiReadService

    rows = [
        {
            "stealth_order_id": "stealth-root",
            "parent_order_id": None,
            "product_id": "BTC-USDC",
            "side": "BUY",
            "status": "REVEALED",
            "total_size": "2.00",
            "revealed_size": "1.00",
            "remaining_size": "1.00",
            "executed_size": "0.25",
            "limit_price": "65000.00",
            "visibility_score": "0.42",
            "reveal_condition_type": "price",
            "reveal_condition_json": {"price_threshold": "65000.00"},
            "sizing_strategy_json": {"type": "tranche"},
            "revealed_orders": [
                {
                    "placed_order_id": "placement-client-old",
                    "exchange_order_id": "exchange-old",
                },
                {
                    "placed_order_id": "placement-client-latest",
                    "exchange_order_id": "exchange-latest",
                },
            ],
            "anchor_repricing_policy_json": {"enabled": True},
            "anchor_repricing_state_json": {
                "active_placement_client_order_id": "placement-client-active",
                "active_exchange_order_id": "exchange-active",
            },
            "cancel_reentry_policy_json": {"enabled": True},
            "cancel_reentry_state_json": {"state": "watching"},
            "post_fill_retreat_policy_json": {"enabled": False},
            "last_lifecycle_event": "revealed",
            "failure_reason": None,
            "created_at": "2026-06-11T10:00:00Z",
            "updated_at": "2026-06-11T10:05:00Z",
        },
        {
            "stealth_order_id": "stealth-other",
            "product_id": "ETH-USDC",
            "status": "HIDDEN",
        },
    ]
    monkeypatch.setattr(
        order_module,
        "DB_CLIENT",
        SimpleNamespace(execute_query=lambda _query: rows),
    )
    monkeypatch.setattr(
        order_module,
        "get_stealth_order_by_id",
        lambda stealth_order_id: rows[0] if stealth_order_id == "stealth-root" else None,
    )

    service = AdminApiReadService()
    list_response = service.build_stealth_order_list(
        product_id="BTC-USDC",
        status="REVEALED",
        limit=10,
        offset=0,
    )
    detail_response = service.build_stealth_order_detail(stealth_order_id="stealth-root")

    assert list_response.type == "admin_stealth_order_list"
    assert list_response.count == 1
    assert list_response.pagination.total_matching_count == 1
    assert list_response.command_routes_mode == AdminApiCommandRoutesMode.LIVE_DISABLED
    item = list_response.items[0]
    assert item.stealth_order_id == "stealth-root"
    assert item.active_placement_client_order_id == "placement-client-active"
    assert item.active_exchange_order_id == "exchange-active"
    assert item.exchange_order_id_evidence_only is True
    assert item.revealed_orders[-1]["placed_order_id"] == "placement-client-latest"
    assert item.anchor_repricing_policy == {"enabled": True}
    assert item.cancel_reentry_state == {"state": "watching"}
    assert item.source == "stealth_orders"
    assert detail_response.found is True
    assert detail_response.order is not None
    assert detail_response.order.stealth_order_id == "stealth-root"
    assert detail_response.active_placement_audit is not None
    audit = detail_response.active_placement_audit
    assert audit.status == AdminApiGateStatus.BLOCKED
    assert audit.active_placement_present is True
    assert audit.active_placement_client_order_id == "placement-client-active"
    assert audit.active_exchange_order_id == "exchange-active"
    assert audit.exchange_truth_verified is False
    assert audit.coinbase_read_required is True
    assert audit.coinbase_read_ran is False
    assert audit.coinbase_order_cancel_submitted is False
    assert audit.lifecycle_mutation_allowed is False
    assert audit.required_for_mutation_families == [
        AdminApiMutationFamilyType.STEALTH_CANCEL,
        AdminApiMutationFamilyType.STEALTH_MOVE,
        AdminApiMutationFamilyType.MOVEMENT_REPRICE,
    ]
    assert audit.required_contracts == audit.missing_contracts
    assert "coinbase_exchange_truth_read_disabled" in audit.blockers
    assert "active_placement_local_evidence_missing" not in audit.blockers
    assert detail_response.mutation_claim_audit is not None
    mutation_audit = detail_response.mutation_claim_audit
    assert mutation_audit.status == AdminApiGateStatus.BLOCKED
    assert mutation_audit.runtime_claims_observed is False
    assert mutation_audit.runtime_claim_count == 3
    assert mutation_audit.active_claim_count == 0
    assert mutation_audit.claim_reader_source == "runtime_stealth_manager_unavailable"
    assert mutation_audit.coinbase_read_ran is False
    assert mutation_audit.coinbase_order_cancel_submitted is False
    assert mutation_audit.lifecycle_mutation_allowed is False
    assert mutation_audit.required_for_mutation_families == [
        AdminApiMutationFamilyType.STEALTH_MOVE,
        AdminApiMutationFamilyType.MOVEMENT_REPRICE,
    ]
    assert mutation_audit.required_contracts == mutation_audit.missing_contracts
    assert "runtime_mutation_claim_snapshot_unavailable" in mutation_audit.blockers
    assert detail_response.reveal_trigger_audit is not None
    trigger_audit = detail_response.reveal_trigger_audit
    assert trigger_audit.status == AdminApiGateStatus.BLOCKED
    assert trigger_audit.reveal_condition_present is True
    assert trigger_audit.reveal_condition_type == "price"
    assert trigger_audit.reveal_condition == {"price_threshold": "65000.00"}
    assert trigger_audit.trigger_state_source == "local_stealth_row_only"
    assert trigger_audit.trigger_evaluation_ran is False
    assert trigger_audit.should_trigger_reveal_called is False
    assert trigger_audit.reveal_order_slice_called is False
    assert trigger_audit.coinbase_order_submit_ran is False
    assert trigger_audit.lifecycle_mutation_allowed is False
    assert trigger_audit.required_for_mutation_families == [
        AdminApiMutationFamilyType.STEALTH_REVEAL,
    ]
    assert trigger_audit.required_contracts == trigger_audit.missing_contracts
    assert "stealth_reveal_trigger_guard_missing" in trigger_audit.blockers
    assert detail_response.reveal_submission_audit is not None
    submission_audit = detail_response.reveal_submission_audit
    assert submission_audit.status == AdminApiGateStatus.BLOCKED
    assert submission_audit.command_route == (
        "/api/v1/stealth/orders/{stealth_order_id}/reveal"
    )
    assert submission_audit.service_method == "reveal_stealth_order_by_stealth_order_id"
    assert submission_audit.reveal_manager_method.endswith("::reveal_order_slice")
    assert submission_audit.submission_adapter_configured is False
    assert submission_audit.route_bound is True
    assert submission_audit.backend_owned is True
    assert submission_audit.existing_active_placement_present is True
    assert submission_audit.active_placement_client_order_id == "placement-client-active"
    assert submission_audit.active_exchange_order_id == "exchange-active"
    assert submission_audit.exchange_order_id_evidence_only is True
    assert submission_audit.reveal_order_slice_called is False
    assert submission_audit.coinbase_order_submit_ran is False
    assert submission_audit.coinbase_order_cancel_submitted is False
    assert submission_audit.live_coinbase_read_ran is False
    assert submission_audit.active_placement_created is False
    assert submission_audit.lifecycle_mutation_allowed is False
    assert submission_audit.reconciliation_required is True
    assert submission_audit.reconciliation_executed is False
    assert submission_audit.required_for_mutation_families == [
        AdminApiMutationFamilyType.STEALTH_REVEAL,
    ]
    assert submission_audit.required_contracts == submission_audit.missing_contracts
    assert "existing_active_placement_local_evidence_present" in (
        submission_audit.blockers
    )
    assert "stealth_reveal_exchange_submission_adapter_missing" in (
        submission_audit.blockers
    )
    assert detail_response.live_coinbase_orders_ran is False


@pytest.mark.regression
def test_admin_api_stealth_read_service_does_not_promote_historical_reveals_to_active(monkeypatch):
    import database.order as order_module

    from application.admin_api.read_service import AdminApiReadService

    rows = [
        {
            "stealth_order_id": "stealth-terminal",
            "product_id": "BTC-USDC",
            "status": "FILLED",
            "revealed_orders": [
                {
                    "placed_order_id": "historical-placement-client",
                    "exchange_order_id": "historical-exchange-evidence",
                }
            ],
            "anchor_repricing_state_json": {},
            "last_lifecycle_event": "filled",
        }
    ]
    monkeypatch.setattr(
        order_module,
        "DB_CLIENT",
        SimpleNamespace(execute_query=lambda _query: rows),
    )
    monkeypatch.setattr(
        order_module,
        "get_stealth_order_by_id",
        lambda stealth_order_id: rows[0] if stealth_order_id == "stealth-terminal" else None,
    )

    service = AdminApiReadService()
    list_response = service.build_stealth_order_list(limit=10, offset=0)
    detail_response = service.build_stealth_order_detail(
        stealth_order_id="stealth-terminal"
    )

    item = list_response.items[0]
    assert item.stealth_order_id == "stealth-terminal"
    assert item.revealed_orders[0]["placed_order_id"] == "historical-placement-client"
    assert item.active_placement_client_order_id is None
    assert item.active_exchange_order_id is None
    assert detail_response.order is not None
    assert detail_response.order.active_placement_client_order_id is None
    assert detail_response.order.active_exchange_order_id is None
    assert detail_response.active_placement_audit is not None
    audit = detail_response.active_placement_audit
    assert audit.active_placement_present is False
    assert audit.active_placement_client_order_id is None
    assert audit.active_exchange_order_id is None
    assert audit.exchange_truth_verified is False
    assert audit.coinbase_read_ran is False
    assert audit.lifecycle_mutation_allowed is False
    assert "active_placement_local_evidence_missing" in audit.blockers
    assert detail_response.mutation_claim_audit is not None
    mutation_audit = detail_response.mutation_claim_audit
    assert mutation_audit.runtime_claims_observed is False
    assert mutation_audit.active_claim_count == 0
    assert mutation_audit.lifecycle_mutation_allowed is False
    assert detail_response.reveal_trigger_audit is not None
    trigger_audit = detail_response.reveal_trigger_audit
    assert trigger_audit.reveal_condition_present is False
    assert trigger_audit.trigger_evaluation_ran is False
    assert trigger_audit.should_trigger_reveal_called is False
    assert trigger_audit.reveal_order_slice_called is False
    assert trigger_audit.coinbase_order_submit_ran is False
    assert trigger_audit.lifecycle_mutation_allowed is False
    assert "reveal_condition_local_evidence_missing" in trigger_audit.blockers
    assert detail_response.reveal_submission_audit is not None
    submission_audit = detail_response.reveal_submission_audit
    assert submission_audit.existing_active_placement_present is False
    assert submission_audit.active_placement_client_order_id is None
    assert submission_audit.active_exchange_order_id is None
    assert submission_audit.reveal_order_slice_called is False
    assert submission_audit.coinbase_order_submit_ran is False
    assert submission_audit.coinbase_order_cancel_submitted is False
    assert submission_audit.live_coinbase_read_ran is False
    assert submission_audit.active_placement_created is False
    assert submission_audit.lifecycle_mutation_allowed is False
    assert submission_audit.reconciliation_executed is False
    assert "existing_active_placement_local_evidence_present" not in (
        submission_audit.blockers
    )
    assert "stealth_reveal_exchange_submission_adapter_missing" in (
        submission_audit.blockers
    )


@pytest.mark.regression
def test_admin_api_stealth_detail_mutation_claim_audit_uses_runtime_snapshot(monkeypatch):
    import dashboard_server
    import database.order as order_module

    from application.admin_api.read_service import AdminApiReadService

    row = {
        "stealth_order_id": "stealth-claim-root",
        "product_id": "BTC-USDC",
        "status": "REVEALED",
        "anchor_repricing_state_json": {
            "active_placement_client_order_id": "placement-claim",
            "active_exchange_order_id": "exchange-claim",
        },
    }
    monkeypatch.setattr(
        order_module,
        "get_stealth_order_by_id",
        lambda stealth_order_id: row
        if stealth_order_id == "stealth-claim-root"
        else None,
    )

    observed: list[tuple[StealthMutationKind, str]] = []

    class RuntimeManager:
        def snapshot_mutation_claims(self, stealth_order_id):
            states = {}
            for kind in StealthMutationKind:
                observed.append((kind, stealth_order_id))
                states[kind] = self._state(kind, stealth_order_id)
            return states

        def _state(self, kind, stealth_order_id):
            if kind == StealthMutationKind.MOVE and stealth_order_id == "stealth-claim-root":
                return "processing"
            return None

    runtime_bridge = SimpleNamespace(stealth_manager=RuntimeManager())
    monkeypatch.setattr(dashboard_server, "stealth_order_bridge", runtime_bridge)

    detail_response = AdminApiReadService().build_stealth_order_detail(
        stealth_order_id="stealth-claim-root"
    )

    assert detail_response.mutation_claim_audit is not None
    audit = detail_response.mutation_claim_audit
    assert audit.runtime_claims_observed is True
    assert audit.runtime_claim_count == 3
    assert audit.active_claim_count == 1
    assert audit.claim_reader_source == "stealth_manager.snapshot_mutation_claims"
    assert audit.claim_reader_ran is True
    assert audit.coinbase_read_ran is False
    assert audit.coinbase_order_cancel_submitted is False
    assert audit.lifecycle_mutation_allowed is False
    assert audit.required_for_mutation_families == [
        AdminApiMutationFamilyType.STEALTH_MOVE,
        AdminApiMutationFamilyType.MOVEMENT_REPRICE,
    ]
    claims_by_kind = {claim.kind: claim for claim in audit.runtime_claims}
    assert claims_by_kind[StealthMutationKind.MOVE].state == "processing"
    assert claims_by_kind[StealthMutationKind.MOVE].runtime_observed is True
    assert claims_by_kind[StealthMutationKind.REPRICE].state is None
    assert "runtime_mutation_claim_snapshot_unavailable" not in audit.blockers
    assert "stealth_move_mutation_claim_snapshot_contract_missing" in audit.blockers
    assert observed == [
        (StealthMutationKind.MOVE, "stealth-claim-root"),
        (StealthMutationKind.REPRICE, "stealth-claim-root"),
        (StealthMutationKind.RETREAT, "stealth-claim-root"),
    ]


@pytest.mark.regression
def test_admin_api_stealth_detail_mutation_claim_audit_reports_snapshot_errors(
    monkeypatch,
):
    import dashboard_server
    import database.order as order_module

    from application.admin_api.read_service import AdminApiReadService

    row = {
        "stealth_order_id": "stealth-claim-error",
        "product_id": "BTC-USDC",
        "status": "REVEALED",
    }
    monkeypatch.setattr(
        order_module,
        "get_stealth_order_by_id",
        lambda stealth_order_id: row
        if stealth_order_id == "stealth-claim-error"
        else None,
    )

    class RuntimeManager:
        def snapshot_mutation_claims(self, stealth_order_id):
            raise RuntimeError(f"snapshot unavailable for {stealth_order_id}")

    monkeypatch.setattr(
        dashboard_server,
        "stealth_order_bridge",
        SimpleNamespace(stealth_manager=RuntimeManager()),
    )

    detail_response = AdminApiReadService().build_stealth_order_detail(
        stealth_order_id="stealth-claim-error"
    )

    assert detail_response.mutation_claim_audit is not None
    audit = detail_response.mutation_claim_audit
    assert audit.runtime_claims_observed is False
    assert audit.claim_reader_source == "stealth_manager.snapshot_mutation_claims_error"
    assert audit.claim_reader_ran is True
    assert "runtime_mutation_claim_snapshot_unavailable" in audit.blockers
    assert all(claim.runtime_observed is False for claim in audit.runtime_claims)
    assert all(claim.state == "unavailable:RuntimeError" for claim in audit.runtime_claims)


@pytest.mark.regression
def test_admin_api_movement_repricing_read_routes_use_read_service_without_commands(
    monkeypatch,
):
    from api.v1.routes import movement_repricing as movement_routes

    client = _client(monkeypatch)
    service = SimpleNamespace(
        build_movement_repricing_evidence=lambda **kwargs: {
            "type": "admin_movement_repricing_evidence",
            "filters": kwargs,
            "count": 1,
            "pagination": {
                "limit": kwargs["limit"],
                "offset": kwargs["offset"],
                "returned_count": 1,
                "total_matching_count": 1,
                "next_offset": None,
                "has_more": False,
            },
            "items": [
                {
                    "evidence_id": "stealth_repricing_state:stealth-abc",
                    "evidence_type": "stealth_repricing_state",
                    "stealth_order_id": "stealth-abc",
                    "client_order_id": "placement-client-1",
                    "active_placement_client_order_id": "placement-client-1",
                    "active_exchange_order_id": "exchange-evidence-1",
                    "exchange_order_id_evidence_only": True,
                    "mutation_claims": [
                        {
                            "kind": "move",
                            "state": "processing",
                            "runtime_observed": True,
                            "source": "stealth_manager.snapshot_mutation_claims",
                        }
                    ],
                    "replacement_slots": [
                        {
                            "client_order_id": "parent-1",
                            "max_order_replacement": 3,
                            "current_order_replacement": 1,
                            "pending_replacement_claims": 0,
                            "pending_claims_runtime_observed": True,
                            "source": "order_parent",
                        }
                    ],
                    "source": "stealth_orders",
                }
            ],
            "read_only": True,
            "command_routes_mode": "live_disabled",
            "live_coinbase_orders_ran": False,
        },
        build_movement_repricing_order_detail=lambda client_order_id: {
            "type": "admin_movement_repricing_detail",
            "scope": "client_order_id",
            "client_order_id": client_order_id,
            "stealth_order_id": None,
            "found": True,
            "items": [
                {
                    "evidence_id": "parent_move:1",
                    "evidence_type": "parent_move",
                    "client_order_id": client_order_id,
                    "original_parent_client_order_id": client_order_id,
                    "exchange_order_id_evidence_only": True,
                    "source": "order_moves",
                }
            ],
            "read_only": True,
            "command_routes_mode": "live_disabled",
            "live_coinbase_orders_ran": False,
        },
        build_movement_repricing_stealth_detail=lambda stealth_order_id: {
            "type": "admin_movement_repricing_detail",
            "scope": "stealth_order_id",
            "client_order_id": None,
            "stealth_order_id": stealth_order_id,
            "found": True,
            "items": [
                {
                    "evidence_id": "stealth_move:2",
                    "evidence_type": "stealth_move",
                    "stealth_order_id": stealth_order_id,
                    "old_exchange_order_id": "old-exchange-evidence",
                    "new_exchange_order_id": "new-exchange-evidence",
                    "exchange_order_id_evidence_only": True,
                    "source": "stealth_order_moves",
                }
            ],
            "read_only": True,
            "command_routes_mode": "live_disabled",
            "live_coinbase_orders_ran": False,
        },
    )
    client.app.dependency_overrides[movement_routes.get_read_service] = lambda: service

    list_response = client.get(
        (
            "/api/v1/movement-repricing/evidence"
            "?product_id=BTC-USDC&stealth_order_id=stealth-abc"
            "&client_order_id=placement-client-1&evidence_type=stealth_repricing_state"
            "&limit=10&offset=0"
        ),
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    order_response = client.get(
        "/api/v1/movement-repricing/orders/parent-1",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    stealth_response = client.get(
        "/api/v1/movement-repricing/stealth/stealth-abc",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )

    assert list_response.status_code == 200
    assert list_response.json()["command_routes_mode"] == "live_disabled"
    assert list_response.json()["items"][0]["stealth_order_id"] == "stealth-abc"
    assert list_response.json()["items"][0]["mutation_claims"][0]["kind"] == "move"
    assert list_response.json()["items"][0]["replacement_slots"][0][
        "client_order_id"
    ] == "parent-1"
    assert "order_id" not in list_response.json()["items"][0]
    assert order_response.status_code == 200
    assert order_response.json()["client_order_id"] == "parent-1"
    assert order_response.json()["items"][0]["evidence_type"] == "parent_move"
    assert stealth_response.status_code == 200
    assert stealth_response.json()["stealth_order_id"] == "stealth-abc"
    assert stealth_response.json()["items"][0]["evidence_type"] == "stealth_move"
    assert stealth_response.json()["live_coinbase_orders_ran"] is False


@pytest.mark.regression
def test_admin_api_movement_repricing_read_service_maps_durable_and_runtime_evidence(
    monkeypatch,
):
    import database.order as order_module

    from application.admin_api.read_service import AdminApiReadService
    from core.enums import StealthMutationKind

    parent_rows = {
        "parent-old": {
            "client_order_id": "parent-old",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "max_order_replacement": 4,
            "current_order_replacement": 2,
        },
        "parent-new": {
            "client_order_id": "parent-new",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "max_order_replacement": 4,
            "current_order_replacement": 0,
        },
    }
    order_move_rows = [
        {
            "id": 1,
            "original_parent_client_order_id": "parent-old",
            "new_parent_client_order_id": "parent-new",
            "move_on_cancel": False,
            "moved_at": "2026-06-11T10:00:00Z",
            "reason": "user_move",
            "notes": "operator move",
            "created_at": "2026-06-11T09:59:00Z",
        }
    ]
    stealth_move_rows = [
        {
            "id": 2,
            "stealth_order_id": "stealth-root",
            "old_placement_client_order_id": "placement-old",
            "old_exchange_order_id": "exchange-old",
            "old_submitted_price": "100.00",
            "new_placement_client_order_id": "placement-new",
            "new_exchange_order_id": "exchange-new",
            "new_submitted_price": "101.00",
            "reason": "manual_user_move",
            "status": "completed",
            "market_bid": "100.90",
            "market_ask": "101.10",
            "moved_at": "2026-06-11T10:05:00Z",
        }
    ]
    stealth_rows = [
        {
            "stealth_order_id": "stealth-root",
            "parent_order_id": "parent-old",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "status": "REVEALED",
            "target_movement": "0.005",
            "target_movement_type": "P",
            "anchor_repricing_policy_json": {"enabled": True},
            "anchor_repricing_state_json": {
                "active_placement_client_order_id": "placement-new",
                "active_exchange_order_id": "exchange-new",
                "active_exchange_price": "101.00",
                "last_reprice_at": "2026-06-11T10:05:00Z",
                "next_reprice_at": "2026-06-11T10:06:00Z",
                "reprice_reason": "reference_price_updated",
                "reprice_history": ["2026-06-11T10:05:00Z"],
                "post_fill_retreat_offset": "0.25",
            },
            "updated_at": "2026-06-11T10:05:00Z",
        }
    ]

    def execute_query(query, params=None):
        if "FROM order_moves" in query:
            return order_move_rows
        if "FROM stealth_order_moves" in query:
            return stealth_move_rows
        if "FROM stealth_orders" in query:
            return stealth_rows
        return []

    class RuntimeManager:
        def snapshot_mutation_claims(self, stealth_order_id):
            return {
                kind: self._state(kind, stealth_order_id)
                for kind in StealthMutationKind
            }

        def _state(self, kind, stealth_order_id):
            if kind == StealthMutationKind.REPRICE and stealth_order_id == "stealth-root":
                return "processing"
            return None

    runtime_manager = RuntimeManager()
    class RuntimeLock:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return None

    runtime_engine = SimpleNamespace(
        orderbook_lock=RuntimeLock(),
        _pending_replacement_claims={"parent-old": 1},
    )
    runtime_bridge = SimpleNamespace(
        stealth_manager=runtime_manager,
        order_engine=runtime_engine,
    )
    monkeypatch.setattr(
        order_module,
        "DB_CLIENT",
        SimpleNamespace(execute_query=execute_query),
    )
    monkeypatch.setattr(
        order_module,
        "get_parent_order",
        lambda client_order_id: parent_rows.get(client_order_id),
    )
    monkeypatch.setattr(
        order_module,
        "get_stealth_order_by_id",
        lambda stealth_order_id: stealth_rows[0]
        if stealth_order_id == "stealth-root"
        else None,
    )
    import dashboard_server

    monkeypatch.setattr(dashboard_server, "stealth_order_bridge", runtime_bridge)

    response = AdminApiReadService().build_movement_repricing_evidence(
        product_id="BTC-USDC",
        limit=10,
        offset=0,
    )

    assert response.type == "admin_movement_repricing_evidence"
    assert response.command_routes_mode == AdminApiCommandRoutesMode.LIVE_DISABLED
    assert response.live_coinbase_orders_ran is False
    evidence_by_type = {item.evidence_type.value: item for item in response.items}
    parent_move = evidence_by_type["parent_move"]
    assert parent_move.original_parent_client_order_id == "parent-old"
    assert parent_move.new_parent_client_order_id == "parent-new"
    assert parent_move.replacement_slots[0].client_order_id == "parent-old"
    assert parent_move.replacement_slots[0].pending_replacement_claims == 1
    stealth_move = evidence_by_type["stealth_move"]
    assert stealth_move.old_exchange_order_id == "exchange-old"
    assert stealth_move.new_exchange_order_id == "exchange-new"
    assert stealth_move.exchange_order_id_evidence_only is True
    reprice_state = evidence_by_type["stealth_repricing_state"]
    assert reprice_state.client_order_id == "placement-new"
    assert reprice_state.active_placement_client_order_id == "placement-new"
    assert reprice_state.active_exchange_order_id == "exchange-new"
    assert reprice_state.reprice_history == ["2026-06-11T10:05:00Z"]
    assert reprice_state.mutation_claims[1].kind == StealthMutationKind.REPRICE
    assert reprice_state.mutation_claims[1].state == "processing"
    assert reprice_state.exchange_order_id_evidence_only is True


@pytest.mark.regression
def test_admin_api_futures_read_routes_use_read_service_without_commands(monkeypatch):
    from api.v1.routes import futures as futures_routes

    client = _client(monkeypatch)
    service = SimpleNamespace(
        build_futures_account=lambda: {
            "type": "admin_futures_account",
            "configured_product_scope": ["BIP-20DEC30-CDE"],
            "observed_position_scope": ["BIP-20DEC30-CDE"],
            "collateral": {
                "name": "collateral",
                "status": "unavailable",
                "source": "runtime_unavailable",
                "detail": "No futures balance summary has been observed.",
            },
            "margin": {
                "name": "margin",
                "status": "observed",
                "source": "fee_manager",
                "value": {
                    "margin_window_type": "FCM_MARGIN_WINDOW_TYPE_OVERNIGHT",
                    "overnight_margin_active": True,
                },
            },
            "funding": {
                "name": "funding",
                "status": "not_modeled",
                "source": "backend_contract",
            },
            "liquidation": {
                "name": "liquidation",
                "status": "unavailable",
                "source": "runtime_unavailable",
            },
            "reduce_only_close_only": {
                "name": "reduce_only_close_only",
                "status": "observed",
                "source": "position_side_derivation",
            },
            "position_pnl": {
                "name": "position_pnl",
                "status": "observed",
                "source": "runtime_positions",
            },
            "position_count": 1,
            "read_only": True,
            "command_routes_mode": "not_modeled",
            "live_coinbase_orders_ran": False,
        },
        build_futures_positions=lambda **kwargs: {
            "type": "admin_futures_positions",
            "filters": kwargs,
            "count": 1,
            "pagination": {
                "limit": kwargs["limit"],
                "offset": kwargs["offset"],
                "returned_count": 1,
                "total_matching_count": 1,
                "next_offset": None,
                "has_more": False,
            },
            "items": [
                {
                    "position_key": "futures_position:runtime:BIP-20DEC30-CDE",
                    "product_id": "BIP-20DEC30-CDE",
                    "product_type": "FUTURE",
                    "position_side": "LONG",
                    "number_of_contracts": "2",
                    "open_order_side": "BUY",
                    "close_order_side": "SELL",
                    "reduce_only_order_side": "SELL",
                    "close_only_order_side": "SELL",
                    "source": "runtime_orderbook",
                }
            ],
            "read_only": True,
            "command_routes_mode": "not_modeled",
            "live_coinbase_orders_ran": False,
        },
        build_futures_position_detail=lambda position_key: {
            "type": "admin_futures_position_detail",
            "position_key": position_key,
            "found": True,
            "position": {
                "position_key": position_key,
                "product_id": "BIP-20DEC30-CDE",
                "product_type": "FUTURE",
                "position_side": "LONG",
                "number_of_contracts": "2",
                "open_order_side": "BUY",
                "close_order_side": "SELL",
                "reduce_only_order_side": "SELL",
                "close_only_order_side": "SELL",
                "source": "runtime_orderbook",
            },
            "read_only": True,
            "command_routes_mode": "not_modeled",
            "live_coinbase_orders_ran": False,
        },
    )
    client.app.dependency_overrides[futures_routes.get_read_service] = lambda: service

    account_response = client.get(
        "/api/v1/futures/account",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    positions_response = client.get(
        "/api/v1/futures/positions?product_id=BIP-20DEC30-CDE&position_side=LONG&limit=10&offset=0",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )
    detail_response = client.get(
        "/api/v1/futures/positions/futures_position%3Aruntime%3ABIP-20DEC30-CDE",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )

    assert account_response.status_code == 200
    assert account_response.json()["command_routes_mode"] == "not_modeled"
    assert account_response.json()["margin"]["status"] == "observed"
    assert positions_response.status_code == 200
    position = positions_response.json()["items"][0]
    assert position["position_key"] == "futures_position:runtime:BIP-20DEC30-CDE"
    assert position["close_order_side"] == "SELL"
    assert "client_order_id" not in position
    assert "cost_basis" not in position
    assert detail_response.status_code == 200
    assert detail_response.json()["position_key"] == (
        "futures_position:runtime:BIP-20DEC30-CDE"
    )
    assert detail_response.json()["live_coinbase_orders_ran"] is False


@pytest.mark.regression
def test_admin_api_futures_read_service_maps_runtime_positions_without_spot_rules(
    monkeypatch,
):
    from application.admin_api.read_service import AdminApiReadService

    class FakeOrderBook:
        products = {
            "BIP-20DEC30-CDE": {
                "product_id": "BIP-20DEC30-CDE",
                "product_type": "FUTURE",
                "display_name": "BTC PERP",
                "price_increment": "5",
                "base_increment": "1",
                "future_product_details": {"contract_size": "0.01"},
            },
            "BTC-USDC": {
                "product_id": "BTC-USDC",
                "product_type": "SPOT",
            },
        }
        mandatory_fee_per_contract = {
            "BIP-20DEC30-CDE": {"mandatory_fee_per_contract": "0.34"}
        }

        def snapshot_positions(self):
            return {
                "FUTURE": {
                    "BIP-20DEC30-CDE": {
                        "product_id": "BIP-20DEC30-CDE",
                        "side": "LONG",
                        "number_of_contracts": "2",
                        "entry_price": "100000.00",
                        "current_price": "100250.00",
                        "unrealized_pnl": {"value": "5.00", "currency": "USD"},
                    }
                }
            }

    class FakeFeeManager:
        def get_fee_info(self, product_id=None):
            return {
                "margin_window_type": "FCM_MARGIN_WINDOW_TYPE_OVERNIGHT",
                "overnight_margin_active": True,
                "profit_validation_fee_rate": 0.001,
                "target_movement_factor": 0.85,
            }

    import dashboard_server

    monkeypatch.setattr(
        dashboard_server,
        "stealth_order_bridge",
        SimpleNamespace(
            order_engine=SimpleNamespace(
                orderbook=FakeOrderBook(),
                fee_manager=FakeFeeManager(),
            )
        ),
    )

    service = AdminApiReadService()
    account = service.build_futures_account()
    positions = service.build_futures_positions(limit=10, offset=0)
    detail = service.build_futures_position_detail(
        position_key="futures_position:runtime:BIP-20DEC30-CDE"
    )

    assert account.type == "admin_futures_account"
    assert account.command_routes_mode == "not_modeled"
    assert "BIP-20DEC30-CDE" in account.configured_product_scope
    assert "BTC-USDC" not in account.configured_product_scope
    assert account.observed_position_scope == ["BIP-20DEC30-CDE"]
    assert account.margin.status.value == "observed"
    assert account.margin.value["margin_window_type"] == (
        "FCM_MARGIN_WINDOW_TYPE_OVERNIGHT"
    )
    assert account.collateral.status.value == "unavailable"
    assert account.funding.status.value == "not_modeled"
    assert account.live_coinbase_orders_ran is False

    assert positions.count == 1
    item = positions.items[0]
    assert item.position_key == "futures_position:runtime:BIP-20DEC30-CDE"
    assert item.product_id == "BIP-20DEC30-CDE"
    assert item.product_type == "FUTURE"
    assert item.position_side == "LONG"
    assert item.open_order_side == "BUY"
    assert item.close_order_side == "SELL"
    assert item.reduce_only_order_side == "SELL"
    assert item.close_only_order_side == "SELL"
    assert item.position_pnl == {"unrealized_pnl": {"value": "5.00", "currency": "USD"}}
    dumped = item.model_dump(mode="json")
    assert "client_order_id" not in dumped
    assert "cost_basis" not in dumped
    assert detail.found is True
    assert detail.position is not None
    assert detail.position.position_key == item.position_key


@pytest.mark.regression
def test_admin_api_futures_dashboard_fallback_does_not_promote_unknown_spot_rows(
    monkeypatch,
):
    from application.admin_api.read_service import AdminApiReadService

    import dashboard_server

    monkeypatch.setattr(dashboard_server, "stealth_order_bridge", None)
    with dashboard_server.state_lock:
        previous_positions = dashboard_server.engine_state.get("positions")
        dashboard_server.engine_state["positions"] = {
            "BTC-USDC": {
                "product_id": "BTC-USDC",
                "side": "LONG",
                "number_of_contracts": "2",
            },
            "BIP-20DEC30-CDE": {
                "product_id": "BIP-20DEC30-CDE",
                "product_type": "FUTURE",
                "side": "LONG",
                "number_of_contracts": "1",
            },
        }

    try:
        response = AdminApiReadService().build_futures_positions(limit=10, offset=0)
    finally:
        with dashboard_server.state_lock:
            if previous_positions is None:
                dashboard_server.engine_state.pop("positions", None)
            else:
                dashboard_server.engine_state["positions"] = previous_positions

    assert response.count == 1
    assert response.items[0].product_id == "BIP-20DEC30-CDE"
    assert response.items[0].product_type.value == "FUTURE"
    dumped = response.model_dump(mode="json")
    assert "BTC-USDC" not in str(dumped)


@pytest.mark.regression
def test_admin_api_guard_risk_policy_route_uses_read_service_without_commands(
    monkeypatch,
):
    from api.v1.routes import admin as admin_routes

    client = _client(monkeypatch)
    captured: dict[str, str | None] = {}

    def build_guard_risk_policy(product_id=None):
        captured["product_id"] = product_id
        return {
            "type": "admin_guard_risk_policy",
            "filters": {"product_id": product_id},
            "action_condition_policy": {
                "name": "action_condition_policy",
                "status": "observed",
                "source": "action_condition_guard",
                "value": {"policy_configured": True},
            },
            "configured_limit_rules": [
                {
                    "policy_id": "spot_cap",
                    "enabled": True,
                    "product_type": "SPOT",
                    "side": "BUY",
                    "phases": ["planning"],
                    "max_notional": "25",
                    "raw_rule": {"name": "spot_cap"},
                }
            ],
            "live_execution_gate": {
                "name": "live_execution_gate",
                "status": "fail_closed",
                "source": "live_execution_gate",
                "value": {"allowed": False},
            },
            "product_capability_policy": {
                "name": "product_capability_policy",
                "status": "observed",
                "source": "product_capability_policy",
                "value": {"decision_product_id": product_id},
            },
            "product_capability_decisions": [
                {
                    "product_id": "BTC-USDC",
                    "product_type": "SPOT",
                    "capability": "direct_placement",
                    "mode": "enabled",
                    "allowed": True,
                    "reason": "direct placement enabled",
                }
            ],
            "profitability_policy": {
                "name": "profitability_policy",
                "status": "observed",
                "source": "profit_validator",
                "value": {"browser_calculation_allowed": False},
            },
            "authority_sources": [
                {
                    "name": "wallet_authority",
                    "status": "observed",
                    "source": "action_condition_guard",
                    "value": {"coinbase_wallet_fetch_performed": False},
                }
            ],
            "rejection_categories": [
                {
                    "condition": "wallet_available",
                    "source": "action_condition_guard",
                    "applies_to_product_type": "SPOT",
                    "blocks_before_exchange": True,
                    "detail": "backend wallet guard",
                }
            ],
            "read_only": True,
            "command_routes_mode": "not_modeled",
            "live_coinbase_orders_ran": False,
            "live_coinbase_read_ran": False,
        }

    service = SimpleNamespace(build_guard_risk_policy=build_guard_risk_policy)
    client.app.dependency_overrides[admin_routes.get_read_service] = lambda: service

    response = client.get(
        "/api/v1/admin/guard-risk-policy?product_id=BTC-USDC",
        headers=_headers(roles=AdminApiRole.VIEWER.value),
    )

    assert response.status_code == 200
    payload = response.json()
    assert captured["product_id"] == "BTC-USDC"
    assert payload["read_only"] is True
    assert payload["command_routes_mode"] == "not_modeled"
    assert payload["live_coinbase_orders_ran"] is False
    assert payload["live_coinbase_read_ran"] is False
    assert payload["live_execution_gate"]["status"] == "fail_closed"
    assert payload["configured_limit_rules"][0]["policy_id"] == "spot_cap"
    assert payload["product_capability_decisions"][0]["capability"] == (
        "direct_placement"
    )


@pytest.mark.regression
def test_admin_api_guard_risk_policy_read_service_reports_backend_authority_without_wallet_fetch(
    monkeypatch,
):
    import configuration
    import core.action_condition_guard as guard_module
    from application.admin_api.read_service import AdminApiReadService

    monkeypatch.setattr(
        configuration,
        "ACTION_CONDITION_GUARDS",
        {
            "wallet_available": {"enabled": True, "block_without_credentials": True},
            "known_inventory_available": {
                "enabled": True,
                "phases": ["planning"],
            },
            "limits": [
                {
                    "name": "spot_buy_cap",
                    "product_type": "SPOT",
                    "side": "BUY",
                    "max_notional": "25",
                    "phases": ["planning"],
                },
                {
                    "name": "future_contract_cap",
                    "product_type": "FUTURE",
                    "max_base_size": "10",
                    "phases": ["planning", "reveal"],
                },
            ],
        },
        raising=False,
    )
    monkeypatch.setattr(
        configuration,
        "PRODUCT_CAPABILITIES",
        {"product_type": {"SPOT": {"move_revealed": "disabled"}}},
        raising=False,
    )
    monkeypatch.setattr(
        guard_module,
        "fetch_account_wallets",
        lambda: (_ for _ in ()).throw(AssertionError("wallet fetch not allowed")),
    )

    response = AdminApiReadService().build_guard_risk_policy(
        product_id="BTC-USDC"
    )

    assert response.type == "admin_guard_risk_policy"
    assert response.read_only is True
    assert response.live_coinbase_orders_ran is False
    assert response.live_coinbase_read_ran is False
    assert response.action_condition_policy.source == "action_condition_guard"
    assert response.action_condition_policy.value["policy_configured"] is True
    assert response.action_condition_policy.value["coinbase_wallet_fetch_performed"] is False
    assert response.live_execution_gate.status == "fail_closed"
    assert response.live_execution_gate.value["allowed"] is False
    assert response.live_execution_gate.value["cap_evaluation_required"] is True
    assert {rule.policy_id for rule in response.configured_limit_rules} == {
        "spot_buy_cap",
        "future_contract_cap",
    }
    assert any(
        decision.capability == "direct_placement"
        for decision in response.product_capability_decisions
    )
    assert response.profitability_policy.value["browser_calculation_allowed"] is False
    assert "futures_margin_validation" in (
        response.profitability_policy.value["known_contract_gaps"]
    )
    authority = {item.name: item for item in response.authority_sources}
    assert authority["wallet_authority"].value["coinbase_wallet_fetch_performed"] is False
    assert authority["spot_known_inventory_authority"].source == (
        "spot_inventory_authority"
    )
    rejection_conditions = {item.condition for item in response.rejection_categories}
    assert "wallet_available" in rejection_conditions
    assert "known_inventory_available" in rejection_conditions


@pytest.mark.regression
def test_admin_api_guard_risk_policy_surfaces_capability_evaluation_errors(
    monkeypatch,
):
    import core.product_capability as capability_module
    from application.admin_api.read_service import AdminApiReadService

    def fail_evaluate_product_capability(*args, **kwargs):
        raise RuntimeError("capability evaluator unavailable")

    monkeypatch.setattr(
        capability_module,
        "evaluate_product_capability",
        fail_evaluate_product_capability,
    )

    response = AdminApiReadService().build_guard_risk_policy(
        product_id="BTC-USDC"
    )

    assert response.product_capability_decisions == []
    assert response.product_capability_policy.status == "unavailable"
    assert response.product_capability_policy.value["decision_count"] == 0
    assert response.product_capability_policy.value["decision_error_count"] >= 1
    assert any(
        "capability evaluator unavailable" in error
        for error in response.product_capability_policy.value["decision_errors"]
    )
    assert response.live_coinbase_orders_ran is False
    assert response.live_coinbase_read_ran is False


@pytest.mark.regression
def test_admin_api_audit_workbench_route_uses_read_service_without_commands(
    monkeypatch,
):
    from api.v1.routes import admin as admin_routes

    client = _client(monkeypatch)
    captured: dict[str, object] = {}

    def build_audit_workbench(**kwargs):
        captured.update(kwargs)
        return {
            "type": "admin_audit_workbench",
            "filters": kwargs,
            "module_summary": [
                {
                    "module": "orders",
                    "read_route_count": 2,
                    "command_route_count": 2,
                    "live_enabled": False,
                    "primary_identity": "client_order_id",
                    "evidence_sources": ["route_inventory", "order_parent"],
                    "routes": ["/api/v1/orders"],
                    "notes": "Order audit links use client_order_id.",
                }
            ],
            "events": [
                {
                    "event_id": "audit-001",
                    "module": "orders",
                    "source": "admin_api_audit_log",
                    "action_class": "live_exchange_cancel",
                    "endpoint": "/api/v1/orders/client-abc/cancel",
                    "status": "not_implemented",
                    "actor_id": "operator-001",
                    "permission": "order:cancel",
                    "client_order_id": "client-abc",
                    "correlation_id": "corr-001",
                    "audit_id": "audit-001",
                    "request_id": "corr-001",
                    "exchange_order_id_evidence_only": True,
                    "live_coinbase_orders_ran": False,
                    "raw_event": {},
                }
            ],
            "pagination": {
                "limit": kwargs["limit"],
                "offset": kwargs["offset"],
                "returned_count": 1,
                "total_matching_count": 1,
                "next_offset": None,
                "has_more": False,
            },
            "read_only": True,
            "command_routes_mode": "evidence_only",
            "live_coinbase_orders_ran": False,
            "live_coinbase_read_ran": False,
        }

    service = SimpleNamespace(build_audit_workbench=build_audit_workbench)
    client.app.dependency_overrides[admin_routes.get_read_service] = lambda: service

    response = client.get(
        "/api/v1/admin/audit-workbench"
        "?module=orders&product_id=BTC-USDC&client_order_id=client-abc"
        "&correlation_id=corr-001&audit_id=audit-001&limit=10&offset=5",
        headers=_headers(roles=AdminApiRole.AUDITOR.value),
    )

    assert response.status_code == 200
    assert captured == {
        "module": AdminAuditWorkbenchModule.ORDERS,
        "product_id": "BTC-USDC",
        "client_order_id": "client-abc",
        "correlation_id": "corr-001",
        "audit_id": "audit-001",
        "limit": 10,
        "offset": 5,
    }
    payload = response.json()
    assert payload["read_only"] is True
    assert payload["command_routes_mode"] == "evidence_only"
    assert payload["live_coinbase_orders_ran"] is False
    assert payload["live_coinbase_read_ran"] is False
    assert payload["events"][0]["client_order_id"] == "client-abc"
    assert "order_id" not in payload["events"][0]


@pytest.mark.regression
def test_admin_api_audit_workbench_read_service_normalizes_cross_module_evidence(
    monkeypatch,
):
    import database.order as order_module
    from application.admin_api.audit import AdminApiAuditEvent, FileAdminApiAuditStore
    from application.admin_api.read_service import AdminApiReadService

    audit_path = _store_dir() / "audit.jsonl"
    audit_store = FileAdminApiAuditStore(audit_path)
    audit_store.append(
        AdminApiAuditEvent(
            actor_id="operator-001",
            action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            permission=AdminApiPermission.ORDER_CANCEL,
            endpoint="/api/v1/orders/client-abc/cancel",
            request_id="corr-001",
            operator_intent="manual_one_off",
            idempotency_key="idem-001",
            client_order_id="client-abc",
            coinbase_order_id="exchange-evidence-001",
            status=AdminApiCommandStatus.NOT_IMPLEMENTED,
            failure_stage="approval",
            message="cancel live disabled",
            admission_decision=AdminLiveAdmissionDecisionEvidence(
                status=AdminApiGateStatus.BLOCKED,
                allowed=False,
                route="/api/v1/orders/{client_order_id}/cancel",
                method="POST",
                module_id="spot_operations",
                identity_key="client_order_id",
                action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
                required_permission=AdminApiPermission.ORDER_CANCEL,
                service_method="cancel_order_by_client_order_id",
                actor_id="operator-001",
                idempotency_key="idem-001",
                operator_intent="manual_one_off",
                payload_hash="1" * 64,
                live_execution_service_present=True,
                live_execution_service_source="disabled_backend_service",
                live_exchange_submitted=False,
                blockers=["admission_audit_missing"],
                evidence=["append-only command admission audit"],
                detail="HTTP live execution is blocked.",
            ),
        )
    )
    monkeypatch.setenv("COINBASE_ADMIN_API_AUDIT_LOG_PATH", str(audit_path))
    monkeypatch.setattr(
        order_module,
        "get_parent_orders",
        lambda: [
            {
                "client_order_id": "client-abc",
                "product_id": "BTC-USDC",
                "status": "OPEN",
                "exchange_order_id": "exchange-evidence-001",
                "correlation_id": "corr-001",
                "audit_id": "audit-order-001",
                "updated_at": "2026-06-11T12:00:00Z",
            }
        ],
    )

    response = AdminApiReadService().build_audit_workbench(
        module=AdminAuditWorkbenchModule.ORDERS,
        client_order_id="client-abc",
        correlation_id="corr-001",
        limit=10,
        offset=0,
    )

    assert response.type == "admin_audit_workbench"
    assert response.read_only is True
    assert response.live_coinbase_orders_ran is False
    assert response.live_coinbase_read_ran is False
    assert response.pagination.total_matching_count == 2
    modules = {item.module for item in response.module_summary}
    assert AdminAuditWorkbenchModule.ORDERS in modules
    assert AdminAuditWorkbenchModule.FUTURES_PERPETUALS in modules
    events_by_source = {item.source: item for item in response.events}
    assert events_by_source[AdminAuditEvidenceSource.ADMIN_API_AUDIT_LOG].audit_id
    assert events_by_source[AdminAuditEvidenceSource.ADMIN_API_AUDIT_LOG].request_id == (
        "corr-001"
    )
    assert (
        events_by_source[AdminAuditEvidenceSource.ADMIN_API_AUDIT_LOG].operator_intent
        == "manual_one_off"
    )
    assert events_by_source[
        AdminAuditEvidenceSource.ADMIN_API_AUDIT_LOG
    ].admission_decision == {
        "status": AdminApiGateStatus.BLOCKED.value,
        "allowed": False,
        "route": "/api/v1/orders/{client_order_id}/cancel",
        "method": "POST",
        "module_id": "spot_operations",
        "identity_key": "client_order_id",
        "identity_value": None,
        "action_class": AdminApiActionClass.LIVE_EXCHANGE_CANCEL.value,
        "required_permission": AdminApiPermission.ORDER_CANCEL.value,
        "service_method": "cancel_order_by_client_order_id",
        "actor_id": "operator-001",
        "idempotency_key": "idem-001",
        "operator_intent": "manual_one_off",
        "payload_hash": "1" * 64,
        "approval_snapshot_required": True,
        "approval_store_required": True,
        "admission_audit_required": True,
        "cap_guard_required": True,
        "reconciliation_required": True,
        "approval_snapshot_present": False,
        "approval_snapshot_id": None,
        "approval_snapshot_source": "missing",
        "approval_snapshot_approved_by_actor_id": None,
        "approval_snapshot_requested_by_actor_id": None,
        "approval_snapshot_expires_at": None,
        "approval_snapshot_missing_reason": None,
        "admission_audit_present": False,
        "admission_audit_id": None,
        "admission_audit_source": "missing",
        "admission_audit_recorded_at": None,
        "admission_audit_missing_reason": None,
        "cap_guard_present": False,
        "cap_guard_decision_id": None,
        "cap_guard_source": "missing",
        "cap_guard_recorded_at": None,
        "cap_guard_missing_reason": None,
        "reconciliation_plan_present": False,
        "reconciliation_plan_id": None,
        "reconciliation_plan_source": "missing",
        "reconciliation_plan_recorded_at": None,
        "reconciliation_plan_missing_reason": None,
        "live_execution_service_required": True,
        "live_execution_service_present": True,
        "live_execution_service_status": "live_disabled",
        "live_execution_service_source": "disabled_backend_service",
        "live_execution_service_missing_reason": "live_execution_disabled",
        "browser_authority": "rejected",
        "live_exchange_submitted": False,
        "live_execution_intent": None,
        "blockers": ["admission_audit_missing"],
        "evidence": ["append-only command admission audit"],
        "detail": "HTTP live execution is blocked.",
    }
    assert events_by_source[AdminAuditEvidenceSource.ORDER_PARENT].client_order_id == (
        "client-abc"
    )
    for event in response.events:
        assert event.exchange_order_id_evidence_only is True
        assert event.live_coinbase_orders_ran is False
        assert "order_id" not in event.model_dump(mode="json")


@pytest.mark.regression
def test_admin_api_audit_workbench_preserves_movement_client_alias_filters(
    monkeypatch,
):
    from application.admin_api import read_service as read_service_module
    from application.admin_api.read_service import AdminApiReadService

    def fake_query(query, params=None):
        if "FROM order_moves" in query:
            return [
                {
                    "id": 1,
                    "original_parent_client_order_id": "parent-old",
                    "new_parent_client_order_id": "parent-new",
                    "move_on_cancel": False,
                    "created_at": "2026-06-11T11:00:00Z",
                    "moved_at": "2026-06-11T11:01:00Z",
                }
            ], None
        if "FROM stealth_order_moves" in query:
            return [], None
        if "FROM stealth_orders" in query:
            return [], None
        return [], None

    monkeypatch.setattr(read_service_module, "_query_admin_rows", fake_query)
    monkeypatch.setattr(read_service_module, "_parent_order_row", lambda client_order_id: {
        "client_order_id": client_order_id,
        "product_id": "BTC-USDC",
        "side": "BUY",
    })

    response = AdminApiReadService().build_audit_workbench(
        module=AdminAuditWorkbenchModule.MOVEMENT_REPRICING,
        client_order_id="parent-new",
        limit=10,
        offset=0,
    )

    assert response.pagination.total_matching_count == 1
    event = response.events[0]
    assert event.module == AdminAuditWorkbenchModule.MOVEMENT_REPRICING
    assert event.client_order_id == "parent-old"
    assert event.raw_event["new_parent_client_order_id"] == "parent-new"
    assert event.exchange_order_id_evidence_only is True
    assert "order_id" not in event.model_dump(mode="json")


@pytest.mark.regression
def test_admin_api_route_inventory_names_required_shared_methods_and_doc():
    rows = {item.surface: item for item in ADMIN_API_ROUTE_INVENTORY}
    doc = ROUTE_INVENTORY_DOC.read_text(encoding="utf-8")

    assert rows["POST /api/v1/orders"].shared_method == "place_manual_order"
    assert rows["POST /api/v1/orders"].action_class == AdminApiActionClass.LIVE_EXCHANGE_PLACE
    assert rows["POST /api/v1/orders/{client_order_id}/cancel"].shared_method == (
        "cancel_order_by_client_order_id"
    )
    assert rows["POST /api/v1/orders/{client_order_id}/cancel"].action_class == (
        AdminApiActionClass.LIVE_EXCHANGE_CANCEL
    )
    assert rows["GET /api/v1/orders"].shared_method == "build_order_list"
    assert rows["GET /api/v1/orders/{client_order_id}"].shared_method == (
        "build_order_detail"
    )
    assert rows["GET /api/v1/stealth/orders"].shared_method == (
        "build_stealth_order_list"
    )
    assert rows["GET /api/v1/stealth/orders/{stealth_order_id}"].shared_method == (
        "build_stealth_order_detail"
    )
    assert rows["POST /api/v1/stealth/orders"].shared_method == (
        "create_stealth_order"
    )
    assert rows["POST /api/v1/stealth/orders"].action_class == (
        AdminApiActionClass.LOCAL_STATE_MUTATION
    )
    assert rows["POST /api/v1/stealth/orders/{stealth_order_id}/cancel"].shared_method == (
        "cancel_stealth_order_by_stealth_order_id"
    )
    assert rows["POST /api/v1/stealth/orders/{stealth_order_id}/cancel"].action_class == (
        AdminApiActionClass.LIVE_EXCHANGE_CANCEL
    )
    assert rows["GET /api/v1/movement-repricing/evidence"].shared_method == (
        "build_movement_repricing_evidence"
    )
    assert rows[
        "GET /api/v1/movement-repricing/orders/{client_order_id}"
    ].shared_method == "build_movement_repricing_order_detail"
    assert rows[
        "GET /api/v1/movement-repricing/stealth/{stealth_order_id}"
    ].shared_method == "build_movement_repricing_stealth_detail"
    assert rows[
        "POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice"
    ].shared_method == "reprice_stealth_order_by_stealth_order_id"
    assert rows[
        "POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice"
    ].action_class == AdminApiActionClass.LIVE_EXCHANGE_CANCEL
    assert rows["GET /api/v1/futures/account"].shared_method == (
        "build_futures_account"
    )
    assert rows["GET /api/v1/futures/positions"].shared_method == (
        "build_futures_positions"
    )
    assert rows["GET /api/v1/futures/positions/{position_key}"].shared_method == (
        "build_futures_position_detail"
    )
    assert rows["GET /api/v1/admin/guard-risk-policy"].shared_method == (
        "build_guard_risk_policy"
    )
    assert rows["GET /api/v1/admin/audit-workbench"].shared_method == (
        "build_audit_workbench"
    )
    assert rows["GET /api/v1/admin/audit-workbench"].permission == (
        AdminApiPermission.AUDIT_READ
    )
    assert rows["POST /api/v1/spot/campaign/executions"].shared_method == (
        "execute_spot_campaign"
    )
    assert rows["POST /api/v1/spot/sweep/automation-runs"].shared_method == (
        "run_spot_sweep_automation"
    )
    assert rows["POST /api/v1/spot/sweep/automation-runs"].permission == (
        AdminApiPermission.SPOT_SWEEP_EXECUTE
    )
    assert rows["GET /api/v1/admin/bootstrap"].shared_method == "build_admin_bootstrap"
    assert rows["GET /api/v1/admin/oidc-readiness"].shared_method == (
        "build_oidc_jwt_readiness"
    )
    assert rows["GET /api/v1/admin/capabilities"].shared_method == (
        "build_admin_capabilities"
    )
    assert rows["GET /api/v1/admin/csrf"].shared_method == "build_csrf_contract"
    assert rows["GET /api/v1/admin/live-enablement"].shared_method == (
        "build_live_enablement"
    )
    enterprise_readiness_route = rows["GET /api/v1/admin/enterprise-readiness"]
    assert enterprise_readiness_route.shared_method == "build_enterprise_readiness"
    assert "structured command-gap" in enterprise_readiness_route.parity_test
    spot_recovery_preview_route = rows["GET /api/v1/spot/recovery/preview"]
    assert spot_recovery_preview_route.shared_method == "build_spot_recovery_preview"
    assert spot_recovery_preview_route.action_class == AdminApiActionClass.READ_ONLY
    assert spot_recovery_preview_route.permission == AdminApiPermission.AUDIT_READ
    assert spot_recovery_preview_route.caps == (
        "read-only spot recovery preview evidence"
    )
    assert "Coinbase read" in spot_recovery_preview_route.parity_test
    assert "Coinbase REST placement" in spot_recovery_preview_route.parity_test
    spot_recovery_apply_review_route = rows[
        "GET /api/v1/spot/recovery/apply-review"
    ]
    assert spot_recovery_apply_review_route.shared_method == (
        "build_spot_recovery_apply_review"
    )
    assert spot_recovery_apply_review_route.action_class == (
        AdminApiActionClass.READ_ONLY
    )
    assert spot_recovery_apply_review_route.permission == AdminApiPermission.AUDIT_READ
    assert "recovery apply" in spot_recovery_apply_review_route.parity_test
    assert "Coinbase REST placement" in spot_recovery_apply_review_route.parity_test
    spot_recovery_rollback_plan_route = rows[
        "GET /api/v1/spot/recovery/rollback-plan"
    ]
    assert spot_recovery_rollback_plan_route.shared_method == (
        "build_spot_recovery_rollback_plan"
    )
    assert spot_recovery_rollback_plan_route.permission == AdminApiPermission.AUDIT_READ
    assert "rollback execution" in spot_recovery_rollback_plan_route.parity_test
    spot_recovery_reconciliation_proof_route = rows[
        "GET /api/v1/spot/recovery/reconciliation-proof"
    ]
    assert spot_recovery_reconciliation_proof_route.shared_method == (
        "build_spot_recovery_reconciliation_proof"
    )
    assert (
        spot_recovery_reconciliation_proof_route.permission
        == AdminApiPermission.AUDIT_READ
    )
    assert "proof writing" in spot_recovery_reconciliation_proof_route.parity_test
    recovery_command_routes = {
        "POST /api/v1/spot/recovery/apply-executions": (
            "execute_spot_recovery_apply",
            "apply execution persists append-only",
            AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        ),
        "POST /api/v1/spot/recovery/rollback-executions": (
            "execute_spot_recovery_rollback",
            "rollback execution persists append-only",
            AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        ),
        "POST /api/v1/spot/recovery/exchange-state-proofs": (
            "record_spot_recovery_exchange_state_proof",
            "exchange-state proof writing persists append-only",
            AdminApiPermission.SPOT_RECOVERY_RECORD,
        ),
        "POST /api/v1/spot/recovery/exchange-state-snapshots": (
            "record_spot_recovery_exchange_state_snapshot",
            "exchange-state snapshot writing persists append-only",
            AdminApiPermission.SPOT_RECOVERY_RECORD,
        ),
        "POST /api/v1/spot/recovery/reconciliation-executions": (
            "execute_spot_recovery_reconciliation",
            "reconciliation execution is route-bound",
            AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        ),
        "POST /api/v1/spot/recovery/reconciliation-proofs": (
            "record_spot_recovery_reconciliation_proof",
            "reconciliation proof writing persists append-only",
            AdminApiPermission.SPOT_RECOVERY_RECORD,
        ),
    }
    for surface, (
        shared_method,
        parity_fragment,
        required_permission,
    ) in recovery_command_routes.items():
        route = rows[surface]
        assert route.shared_method == shared_method
        assert route.action_class == AdminApiActionClass.LOCAL_STATE_MUTATION
        assert route.permission == required_permission
        assert route.idempotency == "required"
        assert route.approval == "required"
        assert route.caps == "required"
        assert route.audit == "required"
        assert parity_fragment in route.parity_test
        assert "Coinbase" in route.parity_test
    markdown_inventory_rows = {}
    for line in doc.splitlines():
        if not line.startswith("| `"):
            continue
        columns = [column.strip() for column in line.strip().strip("|").split("|")]
        if len(columns) < 9:
            continue
        markdown_inventory_rows[columns[0].strip("`")] = columns
    spot_recovery_preview_doc_row = markdown_inventory_rows[
        "GET /api/v1/spot/recovery/preview"
    ]
    assert spot_recovery_preview_doc_row[1].strip("`") == (
        spot_recovery_preview_route.action_class.value
    )
    assert spot_recovery_preview_doc_row[2].strip("`") == (
        spot_recovery_preview_route.permission.value
    )
    assert spot_recovery_preview_doc_row[5] == spot_recovery_preview_route.caps
    assert spot_recovery_preview_doc_row[7].strip("`") == (
        spot_recovery_preview_route.shared_method
    )
    assert spot_recovery_preview_doc_row[8] == (
        spot_recovery_preview_route.parity_test
    )
    for route in (
        spot_recovery_apply_review_route,
        spot_recovery_rollback_plan_route,
        spot_recovery_reconciliation_proof_route,
    ):
        doc_row = markdown_inventory_rows[route.surface]
        assert doc_row[1].strip("`") == route.action_class.value
        assert doc_row[2].strip("`") == route.permission.value
        assert doc_row[5] == route.caps
        assert doc_row[7].strip("`") == route.shared_method
        assert doc_row[8] == route.parity_test
    for route in (rows[surface] for surface in recovery_command_routes):
        doc_row = markdown_inventory_rows[route.surface]
        assert doc_row[1].strip("`") == route.action_class.value
        assert doc_row[2].strip("`") == route.permission.value
        assert doc_row[5] == route.caps
        assert doc_row[7].strip("`") == route.shared_method
        assert doc_row[8] == route.parity_test
    assert rows["GET /api/v1/admin/admission-audits"].shared_method == (
        "list_admission_audits"
    )
    assert rows["GET /api/v1/admin/admission-audits"].permission == (
        AdminApiPermission.ADMISSION_AUDIT_READ
    )
    assert rows[
        "GET /api/v1/admin/admission-audits/{admission_audit_id}"
    ].shared_method == "get_admission_audit"
    assert rows["POST /api/v1/admin/admission-audits"].shared_method == (
        "record_admission_audit"
    )
    assert rows["POST /api/v1/admin/admission-audits"].permission == (
        AdminApiPermission.ADMISSION_AUDIT_RECORD
    )
    assert rows["GET /api/v1/admin/cap-guard/decisions"].shared_method == (
        "list_cap_guard_decisions"
    )
    assert rows["GET /api/v1/admin/cap-guard/decisions"].permission == (
        AdminApiPermission.CAP_GUARD_READ
    )
    assert rows[
        "GET /api/v1/admin/cap-guard/decisions/{decision_id}"
    ].shared_method == "get_cap_guard_decision"
    assert rows["POST /api/v1/admin/cap-guard/decisions"].shared_method == (
        "record_cap_guard_decision"
    )
    assert rows["POST /api/v1/admin/cap-guard/decisions"].permission == (
        AdminApiPermission.CAP_GUARD_RECORD
    )
    assert rows["place_hotpoint_test_order WebSocket"].shared_method == (
        "place_hotpoint_test_order"
    )
    assert rows["place_hotpoint_test_order WebSocket"].action_class == (
        AdminApiActionClass.LIVE_EXCHANGE_PLACE
    )
    assert "compatibility_only" in doc
    assert "cancel_order_by_client_order_id" in doc
    assert "place_manual_order" in doc
    assert "place_hotpoint_test_order" in doc
    assert "execute_spot_campaign" in doc
    assert "run_spot_sweep_automation" in doc
    assert "build_admin_bootstrap" in doc
    assert "build_oidc_jwt_readiness" in doc
    assert "build_csrf_contract" in doc
    assert "build_live_enablement" in doc
    assert "build_enterprise_readiness" in doc
    assert "list_admission_audits" in doc
    assert "record_admission_audit" in doc
    assert "list_cap_guard_decisions" in doc
    assert "record_cap_guard_decision" in doc
    assert "structured command-gap" in doc
    assert "build_order_list" in doc
    assert "build_stealth_order_list" in doc
    assert "build_stealth_order_detail" in doc
    assert "cancel_stealth_order_by_stealth_order_id" in doc
    assert "build_movement_repricing_evidence" in doc
    assert "build_movement_repricing_order_detail" in doc
    assert "build_movement_repricing_stealth_detail" in doc
    assert "reprice_stealth_order_by_stealth_order_id" in doc
    assert "build_futures_account" in doc
    assert "build_futures_positions" in doc
    assert "build_futures_position_detail" in doc
    assert "build_guard_risk_policy" in doc
    assert "build_audit_workbench" in doc


@pytest.mark.regression
def test_admin_api_route_inventory_and_openapi_paths_stay_in_sync():
    schema = generate_openapi_schema(OPENAPI_PATH)
    inventory_http_surfaces = {
        item.surface
        for item in ADMIN_API_ROUTE_INVENTORY
        if item.surface.split(" ", 1)[0] in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    }
    schema_http_surfaces = {
        f"{method.upper()} {path}"
        for path, operations in schema["paths"].items()
        for method in operations
        if method in {"get", "post", "put", "patch", "delete"}
    }

    assert "GET /api/v1/admin/oidc-readiness" in inventory_http_surfaces
    assert "GET /api/v1/admin/oidc-readiness" in schema_http_surfaces
    assert "GET /api/v1/stealth/orders" in inventory_http_surfaces
    assert "GET /api/v1/stealth/orders" in schema_http_surfaces
    assert "GET /api/v1/movement-repricing/evidence" in inventory_http_surfaces
    assert "GET /api/v1/movement-repricing/evidence" in schema_http_surfaces
    assert (
        "POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice"
        in inventory_http_surfaces
    )
    assert (
        "POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice"
        in schema_http_surfaces
    )
    assert "GET /api/v1/futures/account" in inventory_http_surfaces
    assert "GET /api/v1/futures/account" in schema_http_surfaces
    assert "GET /api/v1/futures/positions" in inventory_http_surfaces
    assert "GET /api/v1/futures/positions" in schema_http_surfaces
    assert "GET /api/v1/futures/positions/{position_key}" in inventory_http_surfaces
    assert "GET /api/v1/futures/positions/{position_key}" in schema_http_surfaces
    assert "GET /api/v1/admin/guard-risk-policy" in inventory_http_surfaces
    assert "GET /api/v1/admin/guard-risk-policy" in schema_http_surfaces
    assert "GET /api/v1/admin/audit-workbench" in inventory_http_surfaces
    assert "GET /api/v1/admin/audit-workbench" in schema_http_surfaces
    assert "GET /api/v1/admin/enterprise-readiness" in inventory_http_surfaces
    assert "GET /api/v1/admin/enterprise-readiness" in schema_http_surfaces
    assert "GET /api/v1/admin/admission-audits" in inventory_http_surfaces
    assert "GET /api/v1/admin/admission-audits" in schema_http_surfaces
    assert (
        "GET /api/v1/admin/admission-audits/{admission_audit_id}"
        in inventory_http_surfaces
    )
    assert (
        "GET /api/v1/admin/admission-audits/{admission_audit_id}"
        in schema_http_surfaces
    )
    assert "POST /api/v1/admin/admission-audits" in inventory_http_surfaces
    assert "POST /api/v1/admin/admission-audits" in schema_http_surfaces
    assert "GET /api/v1/admin/cap-guard/decisions" in inventory_http_surfaces
    assert "GET /api/v1/admin/cap-guard/decisions" in schema_http_surfaces
    assert (
        "GET /api/v1/admin/cap-guard/decisions/{decision_id}"
        in inventory_http_surfaces
    )
    assert (
        "GET /api/v1/admin/cap-guard/decisions/{decision_id}"
        in schema_http_surfaces
    )
    assert "POST /api/v1/admin/cap-guard/decisions" in inventory_http_surfaces
    assert "POST /api/v1/admin/cap-guard/decisions" in schema_http_surfaces
    assert schema_http_surfaces == inventory_http_surfaces
