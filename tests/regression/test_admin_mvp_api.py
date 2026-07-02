from __future__ import annotations

from dataclasses import dataclass, field

from application.admin_api.mvp_service import (
    AdminMvpDependencies,
    AdminMvpRequestContext,
    AdminMvpService,
)


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
    assert result.body["status"] == "accepted"
    assert result.body["live_coinbase_orders_ran"] is False


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


def record_proof_chain(service: AdminMvpService, admission: dict) -> None:
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
    approval_request_id = approval_request.body["approval"]["approval_request_id"]

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
    approval_id = approval_decision.body["approval"]["approval_id"]

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
    admission_audit_id = admission_audit.body["admission_audit"]["admission_audit_id"]

    cap_guard = service.record_cap_guard_decision(
        {
            **proof_base,
            "admission_audit_id": admission_audit_id,
            "allowed": True,
            "status": "passed",
            "max_submitted_notional_usdc": "3.10",
            "max_executed_notional_usdc": "1.00",
        },
        context(idempotency_key="cap-guard"),
    )
    assert cap_guard.status_code == 200
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


def test_admin_mvp_read_contract_exposes_frontend_manual_order_readiness():
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=FakeRestClient(), rest_client_available=True)
    )
    record_live_service_decision(service)

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
    assert manual_capability["availability"] == "available"
    assert manual_capability["live_enabled"] is True
    assert manual_capability["frontend_safe"] is True
    assert cancel_capability["live_enabled"] is False

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
