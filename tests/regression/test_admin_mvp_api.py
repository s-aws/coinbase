from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from application.admin_api.mvp_service import (
    AdminMvpDependencies,
    AdminMvpRequestContext,
    AdminMvpService,
    live_coinbase_execution_enabled_from_env,
)
from tools import run_admin_api


PRE_COINBASE_FAILURE_STAGES = {
    "product_capability",
    "manual_live_acknowledgement",
    "direct_spot_cap_required",
    "known_inventory_required",
    "action_condition_guard",
    "durable_audit_required",
}


@dataclass
class FakeRestClient:
    create_order_calls: list[dict] = field(default_factory=list)

    def create_order(self, **kwargs):
        self.create_order_calls.append(kwargs)
        return {"success": True, "order_id": "exchange-order-live-1"}


def context(
    *,
    idempotency_key: str = "command-dry-order",
    operator_intent: str = "local_mvp_test",
) -> AdminMvpRequestContext:
    return AdminMvpRequestContext(
        idempotency_key=idempotency_key,
        correlation_id=f"{idempotency_key}-correlation",
        operator_intent=operator_intent,
        actor_id="operator-1",
        roles=("operator",),
    )


def manual_order_body() -> dict:
    return {
        "product_id": "BTC-USDC",
        "side": "BUY",
        "order_type": "MARKET",
        "quote_size": "1.00",
        "post_only": False,
        "manual_live_acknowledgement": True,
    }


def record_live_service_decision(service: AdminMvpService) -> None:
    result = service.record_live_service_decision(
        {
            "decision_id": "mvp-live-service",
            "status": "passed",
            "requested_service_status": "approval_required",
            "service_enabled": True,
            "live_coinbase_execution_approved": True,
            "max_submitted_notional_usdc": "3.10",
            "max_executed_notional_usdc": "1.00",
        },
        context(idempotency_key="live-service-decision"),
    )
    assert result.status_code == 200
    assert result.body["type"] == "admin_live_service_decision"
    assert result.body["status"] == "accepted"
    assert result.body["service_method"] == "record_live_service_decision"
    assert result.body["message"] == "Live-service decision recorded."
    assert result.body["audit_id"] == "audit-live-service-decision"
    assert result.body["live_coinbase_orders_ran"] is False
    decision = result.body["decision"]
    assert decision["route"] == "/api/v1/admin/live-execution/service-decisions"
    assert decision["method"] == "POST"
    assert decision["module_id"] == "admin_system_health"
    assert decision["required_permission"] == "config:update"
    assert decision["service_method"] == "record_live_service_decision"
    assert decision["live_execution_service_status"] == "approval_required"
    assert decision["live_exchange_submitted"] is False


def record_live_adapter_decision(service: AdminMvpService) -> None:
    result = service.record_live_adapter_decision(
        {
            "decision_id": "mvp-live-adapter",
            "status": "blocked",
            "requested_adapter_status": "live_disabled",
            "target_route": "/api/v1/orders",
            "target_method": "POST",
            "target_module_id": "spot_operations",
            "target_service_method": "place_manual_order",
            "adapter_reference": "AdminApiCommandService.place_manual_order",
            "adapter_constructed": False,
            "adapter_enabled": False,
            "construction_review_ref": "adapter-construction-review-disabled",
            "decision_reason": "Document disabled local MVP live-adapter posture.",
            "live_coinbase_execution_approved": False,
            "max_submitted_notional_usdc": "0",
            "max_executed_notional_usdc": "0",
        },
        context(idempotency_key="live-adapter-decision"),
    )
    assert result.status_code == 200
    assert result.body["type"] == "admin_live_adapter_decision"
    assert result.body["status"] == "accepted"
    assert result.body["service_method"] == "record_live_adapter_decision"
    assert result.body["message"] == "Live-adapter decision recorded."
    assert result.body["audit_id"] == "audit-live-adapter-decision"
    assert result.body["live_coinbase_orders_ran"] is False
    decision = result.body["decision"]
    assert decision["route"] == "/api/v1/admin/live-execution/adapter-decisions"
    assert decision["method"] == "POST"
    assert decision["module_id"] == "admin_system_health"
    assert decision["required_permission"] == "config:update"
    assert decision["service_method"] == "record_live_adapter_decision"
    assert decision["target_service_method"] == "place_manual_order"
    assert decision["adapter_constructed"] is False
    assert decision["live_exchange_submitted"] is False


def first_manual_submit(service: AdminMvpService) -> dict:
    result = service.submit_manual_order(
        manual_order_body(),
        context(idempotency_key="manual-order-proof-chain"),
    )
    assert result.status_code == 501
    assert result.body["status"] == "not_implemented"
    assert result.body["live_exchange_submitted"] is False
    assert result.body["live_coinbase_orders_ran"] is False
    assert result.body["notional_usdc"] == "1.00"
    admission = result.body["admission_decision"]
    assert admission["live_execution_service_status"] == "approval_required"
    assert "approval_snapshot_missing" in admission["blockers"]
    assert admission["identity_value"]
    assert admission["payload_hash"]
    return admission


def assert_local_mutation_did_not_submit_exchange(result_body: dict) -> None:
    assert result_body["live_exchange_submitted"] is False
    assert result_body["live_coinbase_orders_ran"] is False


def record_proof_chain(
    service: AdminMvpService,
    admission: dict,
    *,
    wallet_check_status: str | None = "passed",
    wallet_available_notional_usdc: str | None = "3.10",
) -> None:
    approval_request = service.create_approval_request(
        {
            "route": admission["route"],
            "method": admission["method"],
            "module_id": admission["module_id"],
            "identity_key": admission["identity_key"],
            "identity_value": admission["identity_value"],
            "action_class": admission["action_class"],
            "required_permission": admission["required_permission"],
            "operator_intent": admission["operator_intent"],
            "command_idempotency_key": admission["idempotency_key"],
            "payload_hash": admission["payload_hash"],
            "request_reason": "test approval",
        },
        context(idempotency_key="approval-request"),
    )
    assert approval_request.status_code == 200
    assert_local_mutation_did_not_submit_exchange(approval_request.body)
    requested_approval = approval_request.body["approval"]
    assert requested_approval["status"] == "requested"
    assert requested_approval["approval_id"] is None
    assert requested_approval["snapshot_linked"] is False
    assert requested_approval["live_exchange_submitted"] is False
    assert requested_approval["browser_authority"] == "display_only"
    assert requested_approval["bff_authority"] == "forward_only_no_execution"
    approval_request_id = requested_approval["approval_request_id"]

    approval_list = service.get_read_response("/api/v1/admin/approvals", {}, context())
    assert approval_list.body["type"] == "admin_approval_lifecycle_list"
    assert approval_list.body["returned_count"] == 1
    assert approval_list.body["total_count"] == 1
    assert approval_list.body["pending_count"] == 1
    assert approval_list.body["approved_count"] == 0
    assert approval_list.body["approvals"][0]["status"] == "requested"

    approval_detail = service.get_read_response(
        f"/api/v1/admin/approvals/requests/{approval_request_id}",
        {},
        context(),
    )
    assert approval_detail.body["type"] == "admin_approval_lifecycle"
    assert approval_detail.body["status"] == "accepted"
    assert approval_detail.body["service_method"] == "get_approval_request"
    assert approval_detail.body["approval"]["approval_request_id"] == approval_request_id

    approval_decision = service.decide_approval_request(
        approval_request_id,
        {
            "decision": "approved",
            "decision_reason": "test approval",
            "cap_guard_decision_ref": "cap-ref",
            "reconciliation_plan_ref": "recon-ref",
        },
        context(idempotency_key="approval-decision"),
    )
    assert approval_decision.status_code == 200
    assert_local_mutation_did_not_submit_exchange(approval_decision.body)
    approved_approval = approval_decision.body["approval"]
    assert approved_approval["status"] == "approved"
    assert approved_approval["snapshot_linked"] is True
    assert approved_approval["decision_actor_id"] == "operator-1"
    assert approved_approval["cap_guard_decision_ref"] == "cap-ref"
    assert approved_approval["reconciliation_plan_ref"] == "recon-ref"
    assert approved_approval["live_exchange_submitted"] is False
    approval_id = approved_approval["approval_id"]

    proof_base = {
        "route": admission["route"],
        "method": admission["method"],
        "module_id": admission["module_id"],
        "identity_key": admission["identity_key"],
        "identity_value": admission["identity_value"],
        "action_class": admission["action_class"],
        "required_permission": admission["required_permission"],
        "service_method": admission["service_method"],
        "actor_id": admission["actor_id"],
        "operator_intent": admission["operator_intent"],
        "command_idempotency_key": admission["idempotency_key"],
        "payload_hash": admission["payload_hash"],
        "approval_snapshot_id": approval_id,
    }
    admission_audit = service.record_admission_audit(
        {
            **proof_base,
            "allowed": False,
            "status": "blocked",
        },
        context(idempotency_key="admission-audit"),
    )
    assert admission_audit.status_code == 200
    assert_local_mutation_did_not_submit_exchange(admission_audit.body)
    admission_audit_id = admission_audit.body["admission_audit"]["admission_audit_id"]

    cap_guard_body = {
        **proof_base,
        "admission_audit_id": admission_audit_id,
        "allowed": True,
        "status": "passed",
        "max_submitted_notional_usdc": "3.10",
        "max_executed_notional_usdc": "1.00",
    }
    if wallet_check_status is not None:
        cap_guard_body["wallet_check_required"] = True
        cap_guard_body["wallet_check_status"] = wallet_check_status
        cap_guard_body["wallet_check_source"] = "backend_admin_cap_guard_test"
    if wallet_available_notional_usdc is not None:
        cap_guard_body["wallet_available_notional_usdc"] = wallet_available_notional_usdc

    cap_guard = service.record_cap_guard_decision(
        cap_guard_body,
        context(idempotency_key="cap-guard"),
    )
    assert cap_guard.status_code == 200
    assert_local_mutation_did_not_submit_exchange(cap_guard.body)
    assert cap_guard.body["decision"]["wallet_check_required"] is True
    assert cap_guard.body["decision"]["wallet_check_status"] == (
        wallet_check_status or "blocked"
    )
    cap_guard_decision_id = cap_guard.body["decision"]["decision_id"]

    reconciliation = service.record_reconciliation_plan(
        {
            **proof_base,
            "admission_audit_id": admission_audit_id,
            "cap_guard_decision_id": cap_guard_decision_id,
            "allowed": True,
            "status": "passed",
            "exchange_submission_required": True,
            "max_submitted_notional_usdc": "3.10",
            "max_executed_notional_usdc": "1.00",
        },
        context(idempotency_key="reconciliation"),
    )
    assert reconciliation.status_code == 200
    assert_local_mutation_did_not_submit_exchange(reconciliation.body)


def preview_query(admission: dict) -> dict[str, str]:
    return {
        "route": admission["route"],
        "method": admission["method"],
        "module_id": admission["module_id"],
        "identity_key": admission["identity_key"],
        "identity_value": admission["identity_value"],
        "action_class": admission["action_class"],
        "required_permission": admission["required_permission"],
        "service_method": admission["service_method"],
        "actor_id": admission["actor_id"],
        "command_idempotency_key": admission["idempotency_key"],
        "operator_intent": admission["operator_intent"],
        "payload_hash": admission["payload_hash"],
    }


def test_admin_account_management_read_contract_exposes_local_operator_scope():
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=FakeRestClient(), rest_client_available=True)
    )

    result = service.get_read_response(
        "/api/v1/admin/account-management",
        {},
        context(idempotency_key="account-management-read"),
    )

    assert result.status_code == 200
    body = result.body
    assert body["type"] == "admin_account_management"
    assert body["module_id"] == "account_management"
    assert body["read_only"] is True
    assert body["browser_authority"] == "display_only"
    assert body["bff_authority"] == "forward_only_no_execution"
    assert body["environment"]["deployment_target"] == "coinbase-local"
    assert body["operator"]["actor_id"] == "operator-1"
    assert body["operator"]["roles"] == ["operator"]
    assert body["account_scope"]["scope_type"] == "local_admin_portfolio"
    assert body["portfolio_scope"]["portfolio_id"] == "local-admin-portfolio"
    assert body["wallet_inventory"]["currency"] == "USDC"
    assert body["wallet_inventory"]["freshness_status"] == "local_default_not_connected"
    assert body["wallet_inventory"]["available_notional_usdc"] == "0"
    assert body["coinbase_read_enabled"] is False
    assert body["live_coinbase_read_ran"] is False
    assert body["live_coinbase_orders_ran"] is False
    assert body["live_coinbase_execution"] == "not_run"
    assert body["notional_usdc"] == "0"
    assert body["audit"]["correlation_id"] == "account-management-read-correlation"
    assert body["audit"]["idempotency_key"] == "account-management-read"
    readiness = {item["name"]: item for item in body["command_readiness_prerequisites"]}
    assert readiness["rbac"]["status"] == "visible"
    assert readiness["wallet_inventory_evidence"]["status"] == "blocked"
    assert readiness["backend_admin_api_contract"]["status"] == "visible"

    capabilities = service.get_read_response("/api/v1/admin/capabilities", {}, context())
    account_capability = next(
        item
        for item in capabilities.body["capabilities"]
        if item["method"] == "GET"
        and item["route"] == "/api/v1/admin/account-management"
    )
    assert account_capability["module_id"] == "account_management"
    assert account_capability["frontend_safe"] is True
    assert account_capability["live_enabled"] is False

    readiness_response = service.get_read_response(
        "/api/v1/admin/enterprise-readiness",
        {},
        context(),
    )
    account_module = next(
        item
        for item in readiness_response.body["modules"]
        if item["module_id"] == "account_management"
    )
    assert account_module["support_status"] == "mvp_read_ready"
    assert account_module["read_routes"] == ["GET /api/v1/admin/account-management"]
    assert account_module["action_posture"]["browser_authority"] == "display_only"


def test_admin_futures_perpetuals_read_contract_exposes_blocked_mvp_evidence():
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=FakeRestClient(), rest_client_available=True)
    )

    account = service.get_read_response("/api/v1/futures/account", {}, context())
    assert account.status_code == 200
    account_body = account.body
    assert account_body["type"] == "admin_futures_account"
    assert account_body["configured_product_scope"] == ["BIP-20DEC30-CDE"]
    assert account_body["observed_position_scope"] == []
    assert account_body["position_count"] == 0
    assert account_body["collateral"]["status"] == "unavailable"
    assert account_body["margin"]["name"] == "margin"
    assert account_body["funding"]["status"] == "not_modeled"
    assert account_body["liquidation"]["source"] == "runtime_unavailable"
    assert account_body["reduce_only_close_only"]["status"] == "unavailable"
    assert account_body["position_pnl"]["status"] == "unavailable"
    assert account_body["read_only"] is True
    assert account_body["command_routes_mode"] == "backend_admin_api_blocked"
    assert account_body["live_coinbase_orders_ran"] is False

    positions = service.get_read_response(
        "/api/v1/futures/positions",
        {"limit": "2", "offset": "0"},
        context(),
    )
    assert positions.status_code == 200
    assert positions.body["type"] == "admin_futures_positions"
    assert positions.body["count"] == 0
    assert positions.body["items"] == []
    assert positions.body["pagination"]["limit"] == 2
    assert positions.body["read_only"] is True

    detail = service.get_read_response(
        "/api/v1/futures/positions/futures_position:runtime:BIP-20DEC30-CDE",
        {},
        context(),
    )
    assert detail.status_code == 200
    assert detail.body["type"] == "admin_futures_position_detail"
    assert detail.body["found"] is False
    assert detail.body["position"] is None

    command_suite = service.get_read_response(
        "/api/v1/futures/command-suite",
        {},
        context(),
    )
    assert command_suite.status_code == 200
    suite = command_suite.body
    assert suite["type"] == "admin_futures_command_suite"
    assert suite["module_id"] == "futures_perpetuals"
    assert suite["status"] == "blocked"
    assert suite["command_count"] == 4
    assert suite["blocked_command_count"] == 4
    assert suite["executable_command_count"] == 0
    assert suite["command_route_count"] == 4
    assert suite["command_draft_allowed_count"] == 4
    assert suite["spot_rule_authority"] is False
    assert suite["browser_authority"] == "display_only"
    assert suite["bff_authority"] == "forward_only_no_execution"
    assert suite["live_coinbase_orders_ran"] is False
    assert suite["submitted_notional_usdc"] == "0"
    assert suite["executed_notional_usdc"] == "0"
    assert "spot_no_shorting" in suite["forbidden_spot_assumptions"]
    assert "futures_margin_collateral_risk_proof" in suite["missing_backend_contracts"]
    commands = {command["command"]: command for command in suite["commands"]}
    assert set(commands) == {
        "futures_place",
        "futures_close_reduce",
        "futures_cancel",
        "futures_reconcile",
    }
    assert commands["futures_place"]["route"] == "/api/v1/futures/orders"
    assert commands["futures_place"]["status"] == "blocked"
    assert commands["futures_place"]["command_draft_allowed"] is True
    assert commands["futures_place"]["execution_allowed"] is False
    assert commands["futures_place"]["spot_rule_authority"] is False
    assert commands["futures_close_reduce"]["identity_key"] == "position_key"
    assert commands["futures_cancel"]["identity_key"] == "client_order_id"
    assert commands["futures_reconcile"]["action_class"] == "local_state_mutation"

    risk_proofs = service.get_read_response("/api/v1/futures/risk-proofs", {}, context())
    assert risk_proofs.status_code == 200
    assert risk_proofs.body["type"] == "admin_futures_risk_proofs"
    assert risk_proofs.body["module_id"] == "futures_perpetuals"
    assert risk_proofs.body["count"] == 0
    assert risk_proofs.body["proof_records_created"] is False
    assert risk_proofs.body["browser_authority"] == "display_only"
    assert risk_proofs.body["bff_authority"] == "forward_only_no_execution"

    capabilities = service.get_read_response("/api/v1/admin/capabilities", {}, context())
    futures_read_routes = {
        item["route"]
        for item in capabilities.body["capabilities"]
        if item["method"] == "GET" and item["module_id"] == "futures_perpetuals"
    }
    assert {
        "/api/v1/futures/command-suite",
        "/api/v1/futures/account",
        "/api/v1/futures/positions",
        "/api/v1/futures/positions/{position_key}",
        "/api/v1/futures/risk-proofs",
        "/api/v1/futures/risk-proofs/{futures_risk_proof_id}",
    }.issubset(futures_read_routes)

    readiness_response = service.get_read_response(
        "/api/v1/admin/enterprise-readiness",
        {},
        context(),
    )
    futures_module = next(
        item
        for item in readiness_response.body["modules"]
        if item["module_id"] == "futures_perpetuals"
    )
    assert futures_module["support_status"] == "mvp_read_ready"
    assert "GET /api/v1/futures/account" in futures_module["read_routes"]
    assert futures_module["action_posture"]["bff_authority"] == "forward_only_no_execution"


def test_admin_mvp_read_contract_exposes_frontend_manual_order_readiness():
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=FakeRestClient(), rest_client_available=True)
    )
    record_live_service_decision(service)
    record_live_adapter_decision(service)

    capabilities = service.get_read_response("/api/v1/admin/capabilities", {}, context())
    manual_capability = next(
        item
        for item in capabilities.body["capabilities"]
        if item["method"] == "POST" and item["route"] == "/api/v1/orders"
    )
    cancel_capability = next(
        item
        for item in capabilities.body["capabilities"]
        if item["method"] == "POST"
        and item["route"] == "/api/v1/orders/{client_order_id}/cancel"
    )
    live_service_capability = next(
        item
        for item in capabilities.body["capabilities"]
        if item["method"] == "POST"
        and item["route"] == "/api/v1/admin/live-execution/service-decisions"
    )
    live_adapter_capability = next(
        item
        for item in capabilities.body["capabilities"]
        if item["method"] == "POST"
        and item["route"] == "/api/v1/admin/live-execution/adapter-decisions"
    )
    command_permissions = {
        item["route"]: item["permission"]
        for item in capabilities.body["capabilities"]
        if item["method"] == "POST"
    }
    assert manual_capability["availability"] == "available"
    assert manual_capability["live_enabled"] is True
    assert manual_capability["frontend_safe"] is True
    assert manual_capability["permission"] == "order:create"
    assert cancel_capability["live_enabled"] is False
    assert cancel_capability["permission"] == "order:cancel"
    assert live_service_capability["permission"] == "config:update"
    assert live_service_capability["shared_method"] == "record_live_service_decision"
    assert live_service_capability["frontend_safe"] is True
    assert live_service_capability["live_enabled"] is False
    assert live_adapter_capability["permission"] == "config:update"
    assert live_adapter_capability["shared_method"] == "record_live_adapter_decision"
    assert live_adapter_capability["frontend_safe"] is True
    assert live_adapter_capability["live_enabled"] is False
    assert command_permissions["/api/v1/admin/approvals/requests"] == "approval:request"
    assert (
        command_permissions[
            "/api/v1/admin/approvals/requests/{approval_request_id}/decisions"
        ]
        == "approval:manage"
    )
    assert command_permissions["/api/v1/admin/admission-audits"] == "admission_audit:record"
    assert command_permissions["/api/v1/admin/cap-guard/decisions"] == "cap_guard:record"
    assert command_permissions["/api/v1/admin/reconciliation/plans"] == "reconciliation:record"
    assert (
        command_permissions["/api/v1/admin/live-execution/adapter-decisions"]
        == "config:update"
    )

    service_decisions = service.get_read_response(
        "/api/v1/admin/live-execution/service-decisions",
        {},
        context(),
    )
    assert service_decisions.body["type"] == "admin_live_service_decision_list"
    assert service_decisions.body["total_count"] == 1
    assert service_decisions.body["returned_count"] == 1
    assert service_decisions.body["passed_count"] == 1
    assert service_decisions.body["live_coinbase_orders_ran"] is False

    service_detail = service.get_read_response(
        "/api/v1/admin/live-execution/service-decisions/mvp-live-service",
        {},
        context(),
    )
    assert service_detail.body["type"] == "admin_live_service_decision"
    assert service_detail.body["status"] == "accepted"
    assert service_detail.body["service_method"] == "get_live_service_decision"
    assert service_detail.body["decision"]["decision_id"] == "mvp-live-service"

    adapter_decisions = service.get_read_response(
        "/api/v1/admin/live-execution/adapter-decisions",
        {},
        context(),
    )
    assert adapter_decisions.body["type"] == "admin_live_adapter_decision_list"
    assert adapter_decisions.body["total_count"] == 1
    assert adapter_decisions.body["returned_count"] == 1
    assert adapter_decisions.body["blocked_count"] == 1
    assert adapter_decisions.body["constructed_count"] == 0
    assert adapter_decisions.body["live_coinbase_orders_ran"] is False

    adapter_detail = service.get_read_response(
        "/api/v1/admin/live-execution/adapter-decisions/mvp-live-adapter",
        {},
        context(),
    )
    assert adapter_detail.body["type"] == "admin_live_adapter_decision"
    assert adapter_detail.body["status"] == "accepted"
    assert adapter_detail.body["service_method"] == "get_live_adapter_decision"
    assert adapter_detail.body["decision"]["decision_id"] == "mvp-live-adapter"

    live_enablement = service.get_read_response(
        "/api/v1/admin/live-enablement",
        {},
        context(),
    )
    manual_path = next(
        path
        for path in live_enablement.body["paths"]
        if path["route"] == "/api/v1/orders"
    )
    assert live_enablement.body["status"] == "approval_required"
    assert live_enablement.body["live_enabled_path_count"] == 1
    assert manual_path["live_enabled"] is True
    assert manual_path["live_eligible"] is True
    assert manual_path["live_command_runtime_ready"] is True
    assert live_enablement.body["live_coinbase_orders_ran"] is False

    command_suite = service.get_read_response(
        "/api/v1/spot/command-suite",
        {},
        context(),
    )
    manual_command = next(
        command
        for command in command_suite.body["commands"]
        if command["route"] == "/api/v1/orders"
    )
    assert command_suite.body["live_enabled_command_count"] == 1
    assert manual_command["live_enabled"] is True
    assert manual_command["executable"] is False


def test_admin_mvp_proof_chain_admits_manual_order_but_default_stays_pre_coinbase():
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=FakeRestClient(), rest_client_available=True)
    )
    record_live_service_decision(service)
    admission = first_manual_submit(service)
    record_proof_chain(service, admission)

    preview = service.preview_admission(preview_query(admission), context())
    assert preview.status_code == 200
    assert preview.body["admission_decision"]["status"] == "passed"
    assert preview.body["admission_decision"]["allowed"] is True
    assert preview.body["live_exchange_submitted"] is False
    assert preview.body["live_coinbase_orders_ran"] is False

    admitted_submit = service.submit_manual_order(
        manual_order_body(),
        context(idempotency_key="manual-order-proof-chain"),
    )
    assert admitted_submit.status_code == 400
    assert admitted_submit.body["status"] == "rejected"
    assert admitted_submit.body["failure_stage"] in PRE_COINBASE_FAILURE_STAGES
    assert admitted_submit.body["admission_decision"]["status"] == "passed"
    assert admitted_submit.body["admission_decision"]["allowed"] is True
    assert admitted_submit.body["live_command_runtime_ready"] is True
    assert admitted_submit.body["live_exchange_submitted"] is False
    assert admitted_submit.body["live_coinbase_orders_ran"] is False
    assert admitted_submit.body["notional_usdc"] == "1.00"


def test_admin_mvp_explicit_live_execution_flows_through_backend_service_only():
    rest_client = FakeRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )
    record_live_service_decision(service)
    admission = first_manual_submit(service)
    record_proof_chain(service, admission)

    live_submit = service.submit_manual_order(
        manual_order_body(),
        context(idempotency_key="manual-order-proof-chain"),
    )

    assert live_submit.status_code == 200
    assert live_submit.body["status"] == "accepted"
    assert live_submit.body["live_exchange_submitted"] is True
    assert live_submit.body["live_coinbase_orders_ran"] is True
    assert live_submit.body["notional_usdc"] == "1.00"
    assert live_submit.body["coinbase_order_id"] == "exchange-order-live-1"
    assert rest_client.create_order_calls == [
        {
            "client_order_id": admission["identity_value"],
            "product_id": "BTC-USDC",
            "side": "BUY",
            "order_configuration": {
                "market_market_ioc": {"quote_size": "1.00"},
            },
        }
    ]


@pytest.mark.parametrize(
    ("wallet_check_status", "wallet_available_notional_usdc"),
    [
        (None, None),
        ("passed", "0.50"),
    ],
)
def test_admin_mvp_live_execution_requires_backend_wallet_inventory_evidence(
    wallet_check_status: str | None,
    wallet_available_notional_usdc: str | None,
):
    rest_client = FakeRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )
    record_live_service_decision(service)
    admission = first_manual_submit(service)
    record_proof_chain(
        service,
        admission,
        wallet_check_status=wallet_check_status,
        wallet_available_notional_usdc=wallet_available_notional_usdc,
    )

    live_submit = service.submit_manual_order(
        manual_order_body(),
        context(idempotency_key="manual-order-proof-chain"),
    )

    assert live_submit.status_code == 400
    assert live_submit.body["status"] == "rejected"
    assert live_submit.body["failure_stage"] == "known_inventory_required"
    assert live_submit.body["live_exchange_submitted"] is False
    assert live_submit.body["live_coinbase_orders_ran"] is False
    assert rest_client.create_order_calls == []


def test_admin_mvp_runner_matches_frontend_local_stack_contract():
    args = run_admin_api.parse_args(["--dev-token", "local-admin-token"])

    assert args.host == "127.0.0.1"
    assert args.port == 8787
    assert args.cors_origins == ("http://127.0.0.1:3000",)

    environ: dict[str, str] = {}
    applied = run_admin_api.apply_local_environment(args, environ=environ)

    assert environ[run_admin_api.AUTH_TOKEN_ENV] == "local-admin-token"
    assert environ[run_admin_api.CORS_ORIGINS_ENV] == "http://127.0.0.1:3000"
    assert environ[run_admin_api.ENVIRONMENT_ENV] == "local"
    assert applied[run_admin_api.AUTH_TOKEN_ENV] == "set_from_dev_token"


def test_admin_mvp_live_execution_env_requires_coinbase_specific_opt_in(monkeypatch):
    monkeypatch.delenv("COINBASE_ADMIN_LIVE_COINBASE_EXECUTION", raising=False)
    monkeypatch.delenv(
        "COINBASE_ADMIN_API_LIVE_COINBASE_EXECUTION_ENABLED",
        raising=False,
    )
    monkeypatch.setenv("COINBASE_ADMIN_API_LIVE_EXECUTION_ENABLED", "true")

    assert live_coinbase_execution_enabled_from_env() is False

    monkeypatch.setenv("COINBASE_ADMIN_API_LIVE_COINBASE_EXECUTION_ENABLED", "true")

    assert live_coinbase_execution_enabled_from_env() is True
