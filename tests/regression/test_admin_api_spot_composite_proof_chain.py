from __future__ import annotations

import gc
from decimal import Decimal
import shutil
from unittest.mock import MagicMock

import pytest

from application.admin_api.idempotency import FileIdempotencyStore
from application.admin_api.approval import FileAdminApiApprovalStore
from application.admin_api.audit import FileAdminApiAuditStore
from application.admin_api.cap_guard import FileAdminApiCapGuardStore
from application.admin_api.cap_guard_service import AdminApiCapGuardDecisionService
from application.admin_api.live_execution import AdminApiLiveExecutionServiceState
from application.admin_api.models import AdminApiCommandResponse
from application.admin_api.mvp_service import (
    AdminMvpApiResult,
    AdminMvpRequestContext,
    AdminMvpService,
)
from application.admin_api.reconciliation import FileAdminApiReconciliationStore
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiGateStatus,
    AdminApiLiveExecutionStatus,
    AdminApiPermission,
    AdminApiRole,
)
from tests.regression import test_admin_api_contract as contract


pytestmark = [pytest.mark.regression, pytest.mark.serial]


@pytest.fixture(autouse=True)
def _close_imported_contract_clients():
    yield
    while contract._ACTIVE_TEST_CLIENTS:
        client = contract._ACTIVE_TEST_CLIENTS.pop()
        try:
            client.app.dependency_overrides.clear()
        finally:
            client.close()
    gc.collect()
    while contract._ACTIVE_TEST_STORE_DIRS:
        shutil.rmtree(
            contract._ACTIVE_TEST_STORE_DIRS.pop(),
            ignore_errors=True,
        )


def _assertion(kind: str) -> dict[str, str]:
    manual = kind == "manual"
    return {
        "route": (
            "/api/v1/orders"
            if manual
            else "/api/v1/orders/{client_order_id}/cancel"
        ),
        "method": "POST",
        "module_id": "spot_operations",
        "identity_key": "client_order_id",
        "identity_value": f"client-{kind}-route-proof",
        "action_class": (
            "live_exchange_place" if manual else "live_exchange_cancel"
        ),
        "required_permission": "order:create" if manual else "order:cancel",
        "service_method": (
            "place_manual_order"
            if manual
            else "cancel_order_by_client_order_id"
        ),
        "actor_id": "trader-proof-origin",
        "operator_intent": (
            "manual_one_off" if manual else "cancel_by_client_order_id"
        ),
        "command_idempotency_key": f"command-{kind}-route-proof",
        "payload_hash": ("c" if manual else "d") * 64,
    }


def _typed_success_body(kind: str, assertion: dict[str, str]) -> dict:
    manual = kind == "manual"
    typed_stores = {
        "required": True,
        "status": "passed",
        "source": "canonical_admin_api_typed_stores",
        "approval": {},
        "admission_audit": {},
        "cap_guard": {},
        "reconciliation_plan": {},
        "live_exchange_submitted": False,
    }
    evidence = (
        {
            "approval_request": {},
            "approval_snapshot": {},
            "admission_audit": {},
            "cap_guard": {},
            "reconciliation_plan": {},
            "typed_production_stores": typed_stores,
        }
        if manual
        else {
            "admission_audit": {},
            "cancel_proof_chain": {},
            "typed_production_stores": typed_stores,
        }
    )
    body = {
        "type": f"spot_{kind}_order_proof_chain_result",
        "status": "accepted",
        "route": f"/api/v1/spot/{kind}-order/proof-chain",
        "method": "POST",
        "module_id": "spot_operations",
        "action_class": "local_state_mutation",
        "required_permission": (
            "spot_manual_order_proof:record"
            if manual
            else "spot_order_cancel_proof:record"
        ),
        "service_method": f"record_spot_{kind}_order_proof_chain",
        "message": "Synthetic typed proof-chain response.",
        "target_route": assertion["route"],
        "target_method": "POST",
        "identity_key": "client_order_id",
        "identity_value": assertion["identity_value"],
        "command_idempotency_key": assertion["command_idempotency_key"],
        "payload_hash": assertion["payload_hash"],
        "proof_chain_status": "passed",
        "resolved_gate_chain": (
            [
                "approval_snapshot",
                "admission_audit",
                "cap_guard",
                "reconciliation_plan",
            ]
            if manual
            else ["cancel_proof_chain"]
        ),
        "missing_gate_chain": [],
        "admission_audit_id": f"audit-{kind}",
        "evidence": evidence,
        "correlation_id": f"correlation-{kind}",
        "idempotency_key": f"proof-{kind}-admin",
        "audit_id": f"proof-audit-{kind}",
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "live_exchange_submitted": False,
        "live_coinbase_execution": "not_run",
        "notional_usdc": "0",
        "live_coinbase_orders_ran": False,
    }
    if not manual:
        return {
            **body,
            "cancel_proof_chain_id": f"cancel-proof-{kind}",
            "coinbase_cancel_submission_allowed": False,
        }
    return {
        **body,
        "approval_request_id": "approval-request-manual",
        "approval_snapshot_id": "approval-manual",
        "cap_guard_decision_id": "cap-manual",
        "reconciliation_plan_id": "reconciliation-manual",
        "admission_decision": {
            "status": "passed",
            "allowed": True,
            "route": assertion["route"],
            "method": assertion["method"],
            "module_id": assertion["module_id"],
            "identity_key": assertion["identity_key"],
            "identity_value": assertion["identity_value"],
            "action_class": assertion["action_class"],
            "required_permission": assertion["required_permission"],
            "service_method": assertion["service_method"],
            "actor_id": assertion["actor_id"],
            "idempotency_key": assertion["command_idempotency_key"],
            "operator_intent": assertion["operator_intent"],
            "payload_hash": assertion["payload_hash"],
            "detail": "Synthetic admission decision.",
        },
        "wallet_check_source": "account_management_snapshot",
        "coinbase_order_submission_allowed": False,
    }


@pytest.mark.parametrize(
    ("kind", "request_model", "response_model", "request_literals"),
    [
        (
            "manual",
            "SpotManualOrderProofChainRequest",
            "SpotManualOrderProofChainResponse",
            {
                "route": "/api/v1/orders",
                "method": "POST",
                "module_id": "spot_operations",
                "identity_key": "client_order_id",
                "action_class": "live_exchange_place",
                "required_permission": "order:create",
                "service_method": "place_manual_order",
            },
        ),
        (
            "cancel",
            "SpotCancelOrderProofChainRequest",
            "SpotCancelOrderProofChainResponse",
            {
                "route": "/api/v1/orders/{client_order_id}/cancel",
                "method": "POST",
                "module_id": "spot_operations",
                "identity_key": "client_order_id",
                "action_class": "live_exchange_cancel",
                "required_permission": "order:cancel",
                "service_method": "cancel_order_by_client_order_id",
            },
        ),
    ],
)
def test_spot_composite_proof_routes_publish_required_typed_contracts(
    kind,
    request_model,
    response_model,
    request_literals,
):
    schema = contract.create_app().openapi()
    operation = schema["paths"][f"/api/v1/spot/{kind}-order/proof-chain"]["post"]
    request_body = operation["requestBody"]

    assert request_body["required"] is True
    assert request_body["content"]["application/json"]["schema"]["$ref"] == (
        f"#/components/schemas/{request_model}"
    )
    request_schema = schema["components"]["schemas"][request_model]
    assert set(request_schema["required"]) == {
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
    }
    for field, literal in request_literals.items():
        assert request_schema["properties"][field]["const"] == literal
    assert request_schema["properties"]["payload_hash"]["pattern"] == (
        "^[0-9a-f]{64}$"
    )

    assert operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"] == f"#/components/schemas/{response_model}"
    response_schema = schema["components"]["schemas"][response_model]
    assert response_schema["additionalProperties"] is False
    assert {
        "type",
        "status",
        "route",
        "method",
        "module_id",
        "action_class",
        "required_permission",
        "service_method",
        "message",
        "target_route",
        "target_method",
        "identity_key",
        "identity_value",
        "command_idempotency_key",
        "payload_hash",
        "proof_chain_status",
        "resolved_gate_chain",
        "missing_gate_chain",
        "evidence",
        "correlation_id",
        "idempotency_key",
        "audit_id",
        "browser_authority",
        "bff_authority",
        "live_exchange_submitted",
        "live_coinbase_execution",
        "notional_usdc",
        "live_coinbase_orders_ran",
    }.issubset(response_schema["required"])
    evidence_model = (
        "SpotManualOrderProofChainEvidence"
        if kind == "manual"
        else "SpotCancelOrderProofChainEvidence"
    )
    assert response_schema["properties"]["evidence"]["$ref"] == (
        f"#/components/schemas/{evidence_model}"
    )
    evidence_schema = schema["components"]["schemas"][evidence_model]
    assert evidence_schema["additionalProperties"] is False
    expected_evidence_fields = (
        {
            "approval_request",
            "approval_snapshot",
            "admission_audit",
            "cap_guard",
            "reconciliation_plan",
            "typed_production_stores",
        }
        if kind == "manual"
        else {
            "admission_audit",
            "cancel_proof_chain",
            "typed_production_stores",
        }
    )
    assert set(evidence_schema["required"]) == expected_evidence_fields
    assert evidence_schema["properties"]["typed_production_stores"]["$ref"] == (
        "#/components/schemas/SpotProofChainTypedProductionStores"
    )
    typed_store_schema = schema["components"]["schemas"][
        "SpotProofChainTypedProductionStores"
    ]
    assert typed_store_schema["additionalProperties"] is False
    assert set(typed_store_schema["required"]) == {
        "required",
        "status",
        "source",
        "approval",
        "admission_audit",
        "cap_guard",
        "reconciliation_plan",
        "live_exchange_submitted",
    }


@pytest.mark.parametrize("kind", ["manual", "cancel"])
def test_trader_cannot_self_approve_composite_spot_proof_chain(
    monkeypatch,
    kind,
):
    from api.v1.routes import spot as spot_routes

    client = contract._client(monkeypatch)
    service = AdminMvpService()
    monkeypatch.setattr(spot_routes, "get_admin_mvp_service", lambda: service)
    route = f"/api/v1/spot/{kind}-order/proof-chain"

    response = client.post(
        route,
        headers=contract._headers(
            idempotency_key=f"proof-{kind}-trader",
            operator_intent=f"record_{kind}_proof_chain",
            roles=AdminApiRole.TRADER.value,
        ),
        json=_assertion(kind),
    )

    assert response.status_code == 403
    assert service.store.admission_audits == {}
    assert service.store.reconciliation_plans == {}


@pytest.mark.parametrize("kind", ["manual", "cancel"])
def test_admin_composite_spot_proof_route_passes_durable_command_store(
    monkeypatch,
    tmp_path,
    kind,
):
    from api.v1.routes import spot as spot_routes

    client = contract._client(monkeypatch)
    command_store = FileIdempotencyStore(tmp_path / f"{kind}-commands.jsonl")
    client.app.dependency_overrides[spot_routes.get_idempotency_store] = (
        lambda: command_store
    )
    service = MagicMock()
    recorder = getattr(service, f"record_spot_{kind}_order_proof_chain")
    body = _assertion(kind)
    recorder.return_value = AdminMvpApiResult(
        status_code=200,
        body=_typed_success_body(kind, body),
    )
    monkeypatch.setattr(spot_routes, "get_admin_mvp_service", lambda: service)

    response = client.post(
        f"/api/v1/spot/{kind}-order/proof-chain",
        headers=contract._headers(
            idempotency_key=f"proof-{kind}-admin",
            operator_intent=f"record_{kind}_proof_chain",
            roles=AdminApiRole.ADMIN.value,
        ),
        json=body,
    )

    assert response.status_code == 200
    call = recorder.call_args
    assert call.args[0] == body
    assert call.kwargs["command_idempotency_store"] is command_store


@pytest.mark.parametrize("kind", ["manual", "cancel"])
def test_admin_composite_spot_proof_chain_admits_same_command_key_through_typed_stores(
    monkeypatch,
    kind,
):
    from api.v1.routes import orders as order_routes
    from api.v1.routes import spot as spot_routes

    class LiveEnabledAdmissionService:
        def admission_state(self) -> AdminApiLiveExecutionServiceState:
            return AdminApiLiveExecutionServiceState(
                required=True,
                present=True,
                status=AdminApiLiveExecutionStatus.APPROVAL_REQUIRED,
                source="synthetic_composite_proof_test",
                missing_reason=None,
                max_submitted_notional_usdc="3.10",
                max_executed_notional_usdc="1.00",
            )

    class RecordingCommandService:
        def __init__(self) -> None:
            self.commands = []

        def place_manual_order(self, command):
            self.commands.append(command)
            return _command_response(
                kind="manual",
                command=command,
                allowed=command.allow_live_execution,
            )

        def cancel_order_by_client_order_id(self, command):
            self.commands.append(command)
            return _command_response(
                kind="cancel",
                command=command,
                allowed=command.allow_live_execution,
            )

    def _command_response(*, kind, command, allowed):
        manual = kind == "manual"
        client_order_id = (
            command.request.client_order_id if manual else command.client_order_id
        )
        return AdminApiCommandResponse(
            status=(
                AdminApiCommandStatus.ACCEPTED
                if allowed
                else AdminApiCommandStatus.NOT_IMPLEMENTED
            ),
            action_class=(
                AdminApiActionClass.LIVE_EXCHANGE_PLACE
                if manual
                else AdminApiActionClass.LIVE_EXCHANGE_CANCEL
            ),
            required_permission=(
                AdminApiPermission.ORDER_CREATE
                if manual
                else AdminApiPermission.ORDER_CANCEL
            ),
            service_method=(
                "place_manual_order"
                if manual
                else "cancel_order_by_client_order_id"
            ),
            message="Synthetic route runner; no Coinbase call.",
            client_order_id=client_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
            live_exchange_submitted=False,
            live_coinbase_orders_ran=False,
            failure_stage=None if allowed else "approval",
            data={"allow_live_execution_seen": allowed},
        )

    monkeypatch.setenv(
        "COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID",
        "11111111-2222-4333-8444-555555555555",
    )
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_LABEL", "Test")
    client = contract._client(monkeypatch)
    command_service = RecordingCommandService()
    client.app.dependency_overrides[order_routes.get_command_service] = (
        lambda: command_service
    )
    client.app.dependency_overrides[order_routes.get_live_execution_service] = (
        lambda: LiveEnabledAdmissionService()
    )
    client.app.dependency_overrides[spot_routes.get_approval_store] = (
        lambda: client.admin_api_test_approval_store
    )
    client.app.dependency_overrides[spot_routes.get_audit_store] = (
        lambda: client.admin_api_test_audit_store
    )
    client.app.dependency_overrides[spot_routes.get_cap_guard_store] = (
        lambda: client.admin_api_test_cap_guard_store
    )
    client.app.dependency_overrides[spot_routes.get_reconciliation_store] = (
        lambda: client.admin_api_test_reconciliation_store
    )
    client.app.dependency_overrides[
        spot_routes.get_composite_proof_cap_guard_service
    ] = lambda: AdminApiCapGuardDecisionService(
        wallet_evidence_resolver=lambda _product: Decimal("3.10")
    )

    command_key = f"typed-composite-{kind}-command"
    operator_intent = (
        "manual_one_off" if kind == "manual" else "cancel_before_another_order"
    )
    command_headers = contract._headers(
        idempotency_key=command_key,
        operator_intent=operator_intent,
        roles=f"{AdminApiRole.ADMIN.value},{AdminApiRole.TRADER.value}",
    )
    if kind == "manual":
        command_route = "/api/v1/orders"
        command_body = {
            "product_id": "BTC-USDC",
            "side": "BUY",
            "order_type": "LIMIT",
            "base_size": "0.00001",
            "limit_price": "50000.00",
            "post_only": True,
            "time_in_force": "GOOD_UNTIL_CANCELLED",
            "manual_live_acknowledgement": True,
        }
    else:
        command_route = "/api/v1/orders/client-typed-composite-cancel/cancel"
        command_body = {
            "reason": "cancel_before_another_order",
            "manual_live_acknowledgement": True,
        }

    first = client.post(command_route, headers=command_headers, json=command_body)

    assert first.status_code == 501
    first_payload = first.json()
    first_admission = first_payload["admission_decision"]
    assert first_admission["allowed"] is False
    assert first_payload["live_exchange_submitted"] is False
    assert len(command_service.commands) == 1

    assertion = {
        "route": first_admission["route"],
        "method": first_admission["method"],
        "module_id": first_admission["module_id"],
        "identity_key": first_admission["identity_key"],
        "identity_value": first_admission["identity_value"],
        "action_class": first_admission["action_class"],
        "required_permission": first_admission["required_permission"],
        "service_method": first_admission["service_method"],
        "actor_id": first_admission["actor_id"],
        "operator_intent": first_admission["operator_intent"],
        "command_idempotency_key": first_admission["idempotency_key"],
        "payload_hash": first_admission["payload_hash"],
        # These hostile values must never select durable proof ids or caps.
        "approval_snapshot_id": "browser-chosen-approval",
        "cap_guard_decision_id": "browser-chosen-cap",
        "reconciliation_plan_id": "browser-chosen-plan",
        "max_submitted_notional_usdc": "999999",
        "max_executed_notional_usdc": "999999",
    }
    proof_headers = contract._headers(
        idempotency_key=f"typed-composite-{kind}-proof",
        operator_intent=f"record_{kind}_proof_chain",
        roles=f"{AdminApiRole.ADMIN.value},{AdminApiRole.TRADER.value}",
    )
    proof = client.post(
        f"/api/v1/spot/{kind}-order/proof-chain",
        headers=proof_headers,
        json=assertion,
    )

    assert proof.status_code == 200
    proof_payload = proof.json()
    assert proof_payload["proof_chain_status"] == AdminApiGateStatus.PASSED.value
    assert "browser-chosen" not in repr(proof_payload)
    approval_record = client.admin_api_test_approval_store.read_recent(limit=10)[0]
    assert approval_record.requested_by_actor_id == "operator-001"
    assert approval_record.approved_by_actor_id == "operator-001"
    cap_record = client.admin_api_test_cap_guard_store.read_recent(limit=10)[0]
    expected_caps = ("3.10", "1.00") if kind == "manual" else ("0", "0")
    assert (
        cap_record.max_submitted_notional_usdc,
        cap_record.max_executed_notional_usdc,
    ) == expected_caps
    assert client.admin_api_test_reconciliation_store.read_recent(limit=10)

    second = client.post(command_route, headers=command_headers, json=command_body)

    assert second.status_code == 200
    second_payload = second.json()
    assert second.headers.get("X-Idempotency-Replayed") is None
    assert second_payload["admission_decision"]["allowed"] is True
    assert second_payload["data"]["allow_live_execution_seen"] is True
    assert second_payload["live_exchange_submitted"] is False
    assert len(command_service.commands) == 2


def test_typed_spot_proof_chain_resumes_after_partial_durable_write(tmp_path):
    """A crash between store appends must be recoverable with the same proof."""

    class FailFirstApprovalWrite(FileAdminApiApprovalStore):
        def append_lifecycle_event(self, event):
            raise RuntimeError("synthetic process loss after cap persistence")

    service = AdminMvpService()
    proof_context = {
        **_assertion("manual"),
        "product_scope": "BTC-USDC",
    }
    record_ids = {
        "approval_request_id": "mvp-manual-approval-request-resume",
        "approval_snapshot_id": "mvp-manual-approval-resume",
        "admission_audit_id": "mvp-manual-admission-audit-resume",
        "cap_guard_decision_id": "mvp-manual-cap-guard-resume",
        "reconciliation_plan_id": "mvp-manual-reconciliation-resume",
    }
    context = AdminMvpRequestContext(
        idempotency_key="proof-manual-resume",
        correlation_id="correlation-manual-resume",
        operator_intent="record_manual_proof_chain",
        actor_id="operator-001",
        roles=(AdminApiRole.ADMIN.value,),
    )
    approval_path = tmp_path / "approvals.jsonl"
    cap_store = FileAdminApiCapGuardStore(tmp_path / "caps.jsonl")
    audit_store = FileAdminApiAuditStore(tmp_path / "audit.jsonl")
    reconciliation_store = FileAdminApiReconciliationStore(
        tmp_path / "reconciliation.jsonl"
    )
    cap_service = AdminApiCapGuardDecisionService(
        wallet_evidence_resolver=lambda _product: Decimal("3.10")
    )

    first = service._record_typed_spot_proof_chain_evidence(
        context=context,
        proof_context=proof_context,
        record_ids=record_ids,
        command_kind="manual",
        approval_store=FailFirstApprovalWrite(approval_path),
        audit_store=audit_store,
        cap_guard_store=cap_store,
        reconciliation_store=reconciliation_store,
        cap_guard_service=cap_service,
    )

    assert first["status"] == "blocked"
    assert first["blocker"] == "typed_approval_persistence_failed:RuntimeError"
    assert cap_store.find_by_decision_id(record_ids["cap_guard_decision_id"])
    assert not FileAdminApiApprovalStore(approval_path).find_by_approval_id(
        record_ids["approval_snapshot_id"]
    )

    recovered = service._record_typed_spot_proof_chain_evidence(
        context=context,
        proof_context=proof_context,
        record_ids=record_ids,
        command_kind="manual",
        approval_store=FileAdminApiApprovalStore(approval_path),
        audit_store=audit_store,
        cap_guard_store=cap_store,
        reconciliation_store=reconciliation_store,
        cap_guard_service=cap_service,
    )

    assert recovered["status"] == "passed"
    assert recovered["source"] == "canonical_admin_api_typed_stores"
    assert recovered["cap_guard"]["decision_id"] == record_ids[
        "cap_guard_decision_id"
    ]
    assert recovered["approval"]["approval_id"] == record_ids[
        "approval_snapshot_id"
    ]
    assert recovered["admission_audit"]["audit_id"] == record_ids[
        "admission_audit_id"
    ]
    assert recovered["reconciliation_plan"]["plan_id"] == record_ids[
        "reconciliation_plan_id"
    ]


def test_typed_spot_proof_chain_persists_backend_derived_execution_cap(
    tmp_path,
) -> None:
    service = AdminMvpService()
    proof_context = {
        **_assertion("manual"),
        "product_scope": "BTC-USDC",
        "correlation_id": "correlation-minimum-size-proof",
        "max_submitted_notional_usdc": "3.10",
        "max_executed_notional_usdc": "1.01",
    }
    cap_store = FileAdminApiCapGuardStore(tmp_path / "caps.jsonl")
    reconciliation_store = FileAdminApiReconciliationStore(
        tmp_path / "reconciliation.jsonl"
    )

    result = service.record_typed_spot_command_proof_chain(
        proof_context=proof_context,
        command_kind="manual",
        roles=(AdminApiRole.ADMIN.value,),
        wallet_available_notional_usdc=Decimal("1.01"),
        approval_store=FileAdminApiApprovalStore(
            tmp_path / "approvals.jsonl"
        ),
        audit_store=FileAdminApiAuditStore(tmp_path / "audit.jsonl"),
        cap_guard_store=cap_store,
        reconciliation_store=reconciliation_store,
    )

    assert result["status"] == "passed", result
    cap = cap_store.read_recent(limit=1)[0]
    reconciliation = reconciliation_store.read_recent(limit=1)[0]
    assert cap.max_submitted_notional_usdc == "3.10"
    assert cap.max_executed_notional_usdc == "1.01"
    assert cap.wallet_available_notional_usdc == "1.01"
    assert reconciliation.max_submitted_notional_usdc == "3.10"
    assert reconciliation.max_executed_notional_usdc == "1.01"


def test_typed_spot_proof_chain_preserves_dynamic_policy_at_one_usdc(
    tmp_path,
) -> None:
    service = AdminMvpService()
    proof_context = {
        **_assertion("manual"),
        "product_scope": "BTC-USDC",
        "correlation_id": "correlation-minimum-size-zero-fee-proof",
        "max_submitted_notional_usdc": "3.10",
        "max_executed_notional_usdc": "1.00",
        "minimum_size_dynamic_cap": True,
    }
    cap_store = FileAdminApiCapGuardStore(tmp_path / "caps.jsonl")

    result = service.record_typed_spot_command_proof_chain(
        proof_context=proof_context,
        command_kind="manual",
        roles=(AdminApiRole.ADMIN.value,),
        wallet_available_notional_usdc=Decimal("1.00"),
        approval_store=FileAdminApiApprovalStore(
            tmp_path / "approvals.jsonl"
        ),
        audit_store=FileAdminApiAuditStore(tmp_path / "audit.jsonl"),
        cap_guard_store=cap_store,
        reconciliation_store=FileAdminApiReconciliationStore(
            tmp_path / "reconciliation.jsonl"
        ),
    )

    assert result["status"] == "passed", result
    cap = cap_store.read_recent(limit=1)[0]
    assert cap.cap_policy_ref == (
        "submitted_notional_cap:3.10;"
        "minimum_size_dynamic_execution_cap:1.00"
    )
    assert cap.wallet_available_notional_usdc == "1.00"
