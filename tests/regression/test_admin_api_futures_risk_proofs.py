from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api.v1.app import create_app
from api.v1.routes import futures as futures_routes
from api.v1.routes.orders import _idempotency_payload_hash
from application.admin_api.approval import (
    AdminApiApprovalRecord,
    FileAdminApiApprovalStore,
)
from application.admin_api.audit import AdminApiAuditEvent, FileAdminApiAuditStore
from application.admin_api.cap_guard import (
    CapGuardDecisionRecord,
    FileAdminApiCapGuardStore,
)
from application.admin_api.command_service import (
    AdminApiCommandDependencies,
    AdminApiCommandService,
)
from application.admin_api.futures_risk_proof import FileFuturesRiskProofStore
from application.admin_api.futures_risk_proof_service import (
    AdminApiFuturesRiskProofService,
    FuturesRiskProofError,
)
from application.admin_api.idempotency import FileIdempotencyStore
from application.admin_api.live_execution import get_disabled_live_execution_service
from application.admin_api.models import (
    AdminApiActor,
    AdminLiveAdmissionDecisionEvidence,
    FuturesRiskProofRecordRequest,
)
from application.admin_api.reconciliation import (
    FileAdminApiReconciliationStore,
    ReconciliationPlanRecord,
)
from application.admin_api.route_inventory import ADMIN_API_ROUTE_INVENTORY
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiGateStatus,
    AdminApiLiveAdmissionBlocker,
    AdminApiPermission,
    AdminApiRole,
    AdminFuturesCommandAction,
    AdminFuturesCommandRiskProofKind,
    AdminFuturesRiskProofEvidenceSource,
)


PAYLOAD_HASH = "a" * 64


def _headers(*, roles: str = "viewer") -> dict[str, str]:
    return {
        "Authorization": "Bearer test-admin-token",
        "X-Admin-Actor": "operator-001",
        "X-Admin-Roles": roles,
    }


def _command_headers(
    *,
    idempotency_key: str,
    operator_intent: str,
    roles: str = AdminApiRole.ADMIN.value,
) -> dict[str, str]:
    headers = _headers(roles=roles)
    headers.update({
        "Idempotency-Key": idempotency_key,
        "X-Correlation-Id": "corr-futures-risk-proof-route-001",
        "X-Operator-Intent": operator_intent,
    })
    return headers


def _risk_proof_request() -> FuturesRiskProofRecordRequest:
    return FuturesRiskProofRecordRequest(
        command=AdminFuturesCommandAction.PLACE,
        proof_kind=AdminFuturesCommandRiskProofKind.MARGIN_COLLATERAL,
        proof_contract_ref="futures_place.margin_collateral.proof_contract",
        evidence_ref="futures_place.margin_collateral.runtime_margin_review",
        evidence_source=AdminFuturesRiskProofEvidenceSource.TEST_EVIDENCE,
        risk_evidence_refs=[
            "futures.account.margin",
            "futures.account.collateral",
        ],
        product_id="BIT-20DEC30-CDE",
        reconciliation_plan_id="futures-reconciliation-plan-001",
        approval_snapshot_id="futures-approval-snapshot-001",
        admission_audit_id="futures-admission-audit-001",
        cap_guard_decision_id="futures-cap-guard-001",
        operator_reason="focused regression proof",
    )


def _admission_decision(
    request: FuturesRiskProofRecordRequest,
) -> AdminLiveAdmissionDecisionEvidence:
    return AdminLiveAdmissionDecisionEvidence(
        status=AdminApiGateStatus.BLOCKED,
        allowed=False,
        route="/api/v1/futures/risk-proofs",
        method="POST",
        module_id="futures_perpetuals",
        identity_key="futures_risk_proof",
        identity_value=f"{request.command.value}:{request.proof_kind.value}",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        required_permission=AdminApiPermission.FUTURES_RISK_PROOF_RECORD,
        service_method="record_futures_risk_proof",
        actor_id="operator-001",
        idempotency_key="futures-risk-proof-idem-001",
        operator_intent="record futures risk proof evidence",
        payload_hash=PAYLOAD_HASH,
        approval_snapshot_required=True,
        approval_store_required=True,
        admission_audit_required=True,
        cap_guard_required=True,
        reconciliation_required=True,
        approval_snapshot_present=True,
        approval_snapshot_id=request.approval_snapshot_id,
        approval_snapshot_source="approval_store",
        approval_snapshot_approved_by_actor_id="risk-reviewer-001",
        approval_snapshot_requested_by_actor_id="operator-001",
        approval_snapshot_expires_at="2099-01-01T00:00:00+00:00",
        admission_audit_present=True,
        admission_audit_id=request.admission_audit_id,
        cap_guard_present=True,
        cap_guard_decision_id=request.cap_guard_decision_id,
        reconciliation_plan_present=True,
        reconciliation_plan_id=request.reconciliation_plan_id,
        browser_authority="rejected",
        live_exchange_submitted=False,
        blockers=[
            AdminApiLiveAdmissionBlocker.LIVE_EXECUTION_DISABLED,
            AdminApiLiveAdmissionBlocker.BROWSER_AUTHORITY_REJECTED,
        ],
        evidence=["futures risk proof append-only contract test evidence"],
        detail="Futures risk proof admission evidence remains live-disabled.",
    )


def _payload_hash_for_route(
    *,
    request: FuturesRiskProofRecordRequest,
    idempotency_key: str,
    operator_intent: str,
) -> str:
    del idempotency_key
    actor = AdminApiActor(
        actor_id="operator-001",
        roles=[AdminApiRole.ADMIN],
    )
    return _idempotency_payload_hash(
        endpoint="POST /api/v1/futures/risk-proofs",
        actor=actor,
        operator_intent=operator_intent,
        body=request.model_dump(mode="json"),
    )


def _append_futures_risk_proof_admission_chain(
    *,
    request: FuturesRiskProofRecordRequest,
    approval_store: FileAdminApiApprovalStore,
    audit_store: FileAdminApiAuditStore,
    cap_guard_store: FileAdminApiCapGuardStore,
    reconciliation_store: FileAdminApiReconciliationStore,
    idempotency_key: str,
    operator_intent: str,
    payload_hash: str,
) -> None:
    route = "/api/v1/futures/risk-proofs"
    method = "POST"
    module_id = "futures_perpetuals"
    identity_key = "futures_risk_proof"
    identity_value = f"{request.command.value}:{request.proof_kind.value}"
    action_class = AdminApiActionClass.LOCAL_STATE_MUTATION
    permission = AdminApiPermission.FUTURES_RISK_PROOF_RECORD
    service_method = "record_futures_risk_proof"
    approval = AdminApiApprovalRecord(
        approval_id=request.approval_snapshot_id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        approved_by_actor_id="risk-reviewer-001",
        requested_by_actor_id="operator-001",
        route=route,
        method=method,
        module_id=module_id,
        identity_key=identity_key,
        identity_value=identity_value,
        action_class=action_class,
        required_permission=permission,
        operator_intent=operator_intent,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        cap_guard_decision_ref=request.cap_guard_decision_id,
        reconciliation_plan_ref=request.reconciliation_plan_id,
    )
    approval_store.append(approval)
    admission_decision = AdminLiveAdmissionDecisionEvidence(
        status=AdminApiGateStatus.BLOCKED,
        allowed=False,
        route=route,
        method=method,
        module_id=module_id,
        identity_key=identity_key,
        identity_value=identity_value,
        action_class=action_class,
        required_permission=permission,
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
        approval_snapshot_id=approval.approval_id,
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
        evidence=["prior append-only futures risk-proof admission audit"],
        detail="Prior backend-owned futures risk-proof admission audit.",
    )
    audit_store.append(
        AdminApiAuditEvent(
            audit_id=request.admission_audit_id,
            actor_id="operator-001",
            action_class=action_class,
            permission=permission,
            endpoint=f"{method} {route}",
            request_id="corr-futures-risk-proof-admission",
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            approval_id=approval.approval_id,
            status=AdminApiCommandStatus.REJECTED,
            failure_stage="approval",
            message="Prior futures risk-proof admission audit.",
            admission_decision=admission_decision,
        )
    )
    cap_guard_store.append(
        CapGuardDecisionRecord(
            decision_id=request.cap_guard_decision_id,
            route=route,
            method=method,
            module_id=module_id,
            identity_key=identity_key,
            identity_value=identity_value,
            action_class=action_class,
            required_permission=permission,
            service_method=service_method,
            actor_id="operator-001",
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            approval_snapshot_id=approval.approval_id,
            admission_audit_id=request.admission_audit_id,
            allowed=True,
            status=AdminApiGateStatus.PASSED,
            cap_policy_ref="futures_risk_proof_cap:local_only",
            guard_policy_ref="futures_risk_proof_prerequisites",
            product_scope="futures risk proof local evidence",
            max_submitted_notional_usdc="0",
            max_executed_notional_usdc="0",
            reason="Exact backend-owned futures risk-proof cap/guard evidence.",
        )
    )
    reconciliation_store.append(
        ReconciliationPlanRecord(
            plan_id=request.reconciliation_plan_id,
            route=route,
            method=method,
            module_id=module_id,
            identity_key=identity_key,
            identity_value=identity_value,
            action_class=action_class,
            required_permission=permission,
            service_method=service_method,
            actor_id="operator-001",
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            approval_snapshot_id=approval.approval_id,
            admission_audit_id=request.admission_audit_id,
            cap_guard_decision_id=request.cap_guard_decision_id,
            allowed=True,
            status=AdminApiGateStatus.PASSED,
            reconciliation_policy_ref="futures_risk_proof_reconciliation:local_only",
            product_scope="futures risk proof local evidence",
            exchange_submission_required=False,
            post_submit_reconciliation_required=False,
            retained_inventory_required=False,
            max_submitted_notional_usdc="0",
            max_executed_notional_usdc="0",
            reason="Exact backend-owned futures risk-proof reconciliation evidence.",
        )
    )


def test_futures_risk_proof_service_persists_no_live_record(tmp_path) -> None:
    store = FileFuturesRiskProofStore(tmp_path / "futures_risk_proofs.jsonl")
    request = _risk_proof_request()

    record = AdminApiFuturesRiskProofService().record_proof(
        proof_store=store,
        body=request,
        admission_decision=_admission_decision(request),
        actor_id="operator-001",
        operator_intent="record futures risk proof evidence",
        idempotency_key="futures-risk-proof-idem-001",
        correlation_id="corr-futures-risk-proof-001",
        payload_hash=PAYLOAD_HASH,
        audit_id="audit-futures-risk-proof-001",
    )

    assert record.mutation_family.value == "futures_risk_proof"
    assert record.required_permission == AdminApiPermission.FUTURES_RISK_PROOF_RECORD
    assert record.proof_persisted is True
    assert record.risk_proof_accepted is False
    assert record.command_route_registered is False
    assert record.command_execution_allowed is False
    assert record.coinbase_order_submitted is False
    assert record.live_coinbase_orders_ran is False
    assert store.find_by_proof_id(record.futures_risk_proof_id) == record


def test_futures_risk_proof_identity_lookup_is_not_limited_to_recent_window(
    tmp_path,
) -> None:
    store = FileFuturesRiskProofStore(tmp_path / "futures_risk_proofs.jsonl")
    request = _risk_proof_request()
    service = AdminApiFuturesRiskProofService()
    old_record = service.record_proof(
        proof_store=store,
        body=request,
        admission_decision=_admission_decision(request),
        actor_id="operator-001",
        operator_intent="record futures risk proof evidence",
        idempotency_key="futures-risk-proof-old-idem",
        correlation_id="corr-futures-risk-proof-old",
        payload_hash=PAYLOAD_HASH,
        audit_id="audit-futures-risk-proof-old",
    )

    for index in range(501):
        store.append(
            old_record.model_copy(
                update={
                    "futures_risk_proof_id": f"futures-risk-proof-new-{index}",
                    "idempotency_key": f"futures-risk-proof-new-idem-{index}",
                    "correlation_id": f"corr-futures-risk-proof-new-{index}",
                    "audit_id": f"audit-futures-risk-proof-new-{index}",
                }
            )
        )

    assert all(
        record.futures_risk_proof_id != old_record.futures_risk_proof_id
        for record in store.read_recent(limit=500)
    )
    assert store.find_by_proof_id(old_record.futures_risk_proof_id) == old_record

    with pytest.raises(FuturesRiskProofError, match="already exists"):
        service.record_proof(
            proof_store=store,
            body=request.model_copy(
                update={
                    "futures_risk_proof_id": old_record.futures_risk_proof_id,
                }
            ),
            admission_decision=_admission_decision(request),
            actor_id="operator-001",
            operator_intent="record futures risk proof duplicate evidence",
            idempotency_key="futures-risk-proof-duplicate-idem",
            correlation_id="corr-futures-risk-proof-duplicate",
            payload_hash=PAYLOAD_HASH,
            audit_id="audit-futures-risk-proof-duplicate",
        )


def test_futures_risk_proof_readback_routes_return_store_records(
    monkeypatch,
    tmp_path,
) -> None:
    store = FileFuturesRiskProofStore(tmp_path / "futures_risk_proofs.jsonl")
    request = _risk_proof_request()
    record = AdminApiFuturesRiskProofService().record_proof(
        proof_store=store,
        body=request,
        admission_decision=_admission_decision(request),
        actor_id="operator-001",
        operator_intent="record futures risk proof evidence",
        idempotency_key="futures-risk-proof-idem-001",
        correlation_id="corr-futures-risk-proof-001",
        payload_hash=PAYLOAD_HASH,
        audit_id="audit-futures-risk-proof-001",
    )

    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-admin-token")
    app = create_app()
    app.dependency_overrides[futures_routes.get_futures_risk_proof_store] = (
        lambda: store
    )
    client = TestClient(app)

    list_response = client.get(
        "/api/v1/futures/risk-proofs",
        headers=_headers(),
    )
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["count"] == 1
    assert list_payload["proof_records_created"] is True
    assert list_payload["items"][0]["futures_risk_proof_id"] == (
        record.futures_risk_proof_id
    )
    assert list_payload["items"][0]["live_coinbase_orders_ran"] is False

    detail_response = client.get(
        f"/api/v1/futures/risk-proofs/{record.futures_risk_proof_id}",
        headers=_headers(),
    )
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["found"] is True
    assert detail_payload["record"]["command"] == AdminFuturesCommandAction.PLACE.value
    assert detail_payload["record"]["risk_proof_accepted"] is False


def test_futures_risk_proof_post_route_records_through_shared_admission(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-admin-token")
    proof_store = FileFuturesRiskProofStore(tmp_path / "futures_risk_proofs.jsonl")
    idempotency_store = FileIdempotencyStore(tmp_path / "idempotency.jsonl")
    audit_store = FileAdminApiAuditStore(tmp_path / "audit.jsonl")
    approval_store = FileAdminApiApprovalStore(tmp_path / "approvals.jsonl")
    cap_guard_store = FileAdminApiCapGuardStore(tmp_path / "cap_guard.jsonl")
    reconciliation_store = FileAdminApiReconciliationStore(
        tmp_path / "reconciliation.jsonl"
    )
    command_service = AdminApiCommandService(
        AdminApiCommandDependencies(
            futures_risk_proof_store_getter=lambda: proof_store,
            audit_store_getter=lambda: audit_store,
            uuid_factory=lambda: "futures-risk-proof-command-audit",
        )
    )
    app = create_app()
    app.dependency_overrides[futures_routes.get_futures_risk_proof_store] = (
        lambda: proof_store
    )
    app.dependency_overrides[futures_routes.get_idempotency_store] = (
        lambda: idempotency_store
    )
    app.dependency_overrides[futures_routes.get_audit_store] = lambda: audit_store
    app.dependency_overrides[futures_routes.get_approval_store] = (
        lambda: approval_store
    )
    app.dependency_overrides[futures_routes.get_cap_guard_store] = (
        lambda: cap_guard_store
    )
    app.dependency_overrides[futures_routes.get_reconciliation_store] = (
        lambda: reconciliation_store
    )
    app.dependency_overrides[futures_routes.get_live_execution_service] = (
        get_disabled_live_execution_service
    )
    app.dependency_overrides[futures_routes.get_command_service] = (
        lambda: command_service
    )
    request = _risk_proof_request()
    idempotency_key = "futures-risk-proof-route-idem"
    operator_intent = "record futures risk proof evidence"
    payload_hash = _payload_hash_for_route(
        request=request,
        idempotency_key=idempotency_key,
        operator_intent=operator_intent,
    )
    _append_futures_risk_proof_admission_chain(
        request=request,
        approval_store=approval_store,
        audit_store=audit_store,
        cap_guard_store=cap_guard_store,
        reconciliation_store=reconciliation_store,
        idempotency_key=idempotency_key,
        operator_intent=operator_intent,
        payload_hash=payload_hash,
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/futures/risk-proofs",
        headers=_command_headers(
            idempotency_key=idempotency_key,
            operator_intent=operator_intent,
        ),
        json=request.model_dump(mode="json"),
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["status"] == AdminApiCommandStatus.ACCEPTED.value
    assert payload["required_permission"] == "futures_risk_proof:record"
    assert payload["service_method"] == "record_futures_risk_proof"
    assert payload["live_exchange_submitted"] is False
    admission = payload["guard"]["admission_decision"]
    assert admission["approval_snapshot_present"] is True
    assert admission["admission_audit_present"] is True
    assert admission["cap_guard_present"] is True
    assert admission["reconciliation_plan_present"] is True
    data = payload["data"]
    assert data["proof_persisted"] is True
    assert data["risk_proof_accepted"] is False
    assert data["command_route_registered"] is False
    assert data["command_draft_created"] is False
    assert data["command_execution_allowed"] is False
    assert data["coinbase_order_submitted"] is False
    assert data["coinbase_order_cancel_submitted"] is False
    assert data["live_coinbase_orders_ran"] is False
    assert data["reconciliation_executed"] is False
    assert data["order_state_mutated"] is False
    assert data["exchange_state_mutated"] is False
    assert data["browser_authority"] == "display_only"
    assert data["bff_authority"] == "forward_only_no_execution"
    assert proof_store.read_recent(limit=10)[0].futures_risk_proof_id == (
        data["futures_risk_proof_id"]
    )
    assert idempotency_store.get_record(idempotency_key) is not None


def test_futures_risk_proof_routes_are_inventory_and_openapi_bound(
    monkeypatch,
) -> None:
    surfaces = {item.surface: item for item in ADMIN_API_ROUTE_INVENTORY}
    post_surface = "POST /api/v1/futures/risk-proofs"
    assert surfaces[post_surface].permission == (
        AdminApiPermission.FUTURES_RISK_PROOF_RECORD
    )
    assert surfaces[post_surface].shared_method == "record_futures_risk_proof"
    assert surfaces[post_surface].action_class == (
        AdminApiActionClass.LOCAL_STATE_MUTATION
    )
    assert (
        surfaces["GET /api/v1/futures/risk-proofs"].shared_method
        == "list_futures_risk_proofs"
    )

    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-admin-token")
    schema = create_app().openapi()
    assert "/api/v1/futures/risk-proofs" in schema["paths"]
    assert "post" in schema["paths"]["/api/v1/futures/risk-proofs"]
    assert "get" in schema["paths"]["/api/v1/futures/risk-proofs"]
    assert (
        "/api/v1/futures/risk-proofs/{futures_risk_proof_id}"
        in schema["paths"]
    )
