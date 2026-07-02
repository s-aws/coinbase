from __future__ import annotations

from application.admin_api.mvp_service import AdminMvpDependencies, AdminMvpService
from tests.regression.test_admin_mvp_api import (
    FakeRestClient,
    context,
    first_manual_submit,
    manual_order_body,
    preview_query,
    record_live_service_decision,
    record_proof_chain,
)


def test_admin_api_order_live_execution_service_dependency_reads_decision_log():
    rest_client = FakeRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )
    admission = first_manual_submit(service)
    record_proof_chain(service, admission)

    blocked = service.submit_manual_order(
        manual_order_body(),
        context(idempotency_key="manual-order-proof-chain"),
    )
    assert blocked.status_code == 400
    assert blocked.body["failure_stage"] == "durable_audit_required"
    assert blocked.body["live_exchange_submitted"] is False
    assert rest_client.create_order_calls == []

    record_live_service_decision(service)

    accepted = service.submit_manual_order(
        manual_order_body(),
        context(idempotency_key="manual-order-proof-chain"),
    )
    assert accepted.status_code == 200
    assert accepted.body["status"] == "accepted"
    assert accepted.body["live_exchange_submitted"] is True
    assert accepted.body["live_coinbase_execution"] == "submitted"
    assert accepted.body["notional_usdc"] == "1.00"
    assert rest_client.create_order_calls


def test_read_surfaces_expose_controlled_live_manual_order_from_backend_decision():
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
    assert manual_capability["frontend_safe"] is True
    assert manual_capability["live_enabled"] is True
    assert manual_capability["permission"] == "order:create"

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
    assert manual_path["live_enabled"] is True
    assert manual_path["live_eligible"] is True
    assert manual_path["live_command_runtime_ready"] is True


def test_admin_api_manual_order_route_passes_backend_admission_to_command_service():
    service = AdminMvpService(
        AdminMvpDependencies(rest_client=FakeRestClient(), rest_client_available=True)
    )
    record_live_service_decision(service)
    admission = first_manual_submit(service)
    record_proof_chain(service, admission)

    preview = service.preview_admission(preview_query(admission), context())

    assert preview.status_code == 200
    assert preview.body["admission_decision"]["allowed"] is True
    assert preview.body["admission_decision"]["status"] == "passed"
    assert preview.body["admission_decision"]["identity_value"] == admission["identity_value"]
    assert preview.body["live_exchange_submitted"] is False


def test_admin_api_manual_order_route_executes_through_backend_runtime_dependencies():
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

    result = service.submit_manual_order(
        manual_order_body(),
        context(idempotency_key="manual-order-proof-chain"),
    )

    assert result.status_code == 200
    assert result.body["status"] == "accepted"
    assert result.body["client_order_id"] == admission["identity_value"]
    assert result.body["coinbase_order_id"] == "exchange-order-live-1"
    assert result.body["live_exchange_submitted"] is True
    assert result.body["live_coinbase_orders_ran"] is True
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


def test_admin_api_manual_order_route_blocks_admitted_quote_above_backend_cap():
    rest_client = FakeRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )
    record_live_service_decision(service)
    body = manual_order_body()
    body["quote_size"] = "5.00"
    first_submit = service.submit_manual_order(
        body,
        context(idempotency_key="manual-order-proof-chain"),
    )
    assert first_submit.status_code == 501
    admission = first_submit.body["admission_decision"]
    record_proof_chain(service, admission)

    result = service.submit_manual_order(
        body,
        context(idempotency_key="manual-order-proof-chain"),
    )

    assert result.status_code == 400
    assert result.body["status"] == "rejected"
    assert result.body["failure_stage"] == "direct_spot_cap_required"
    assert result.body["live_exchange_submitted"] is False
    assert result.body["live_coinbase_orders_ran"] is False
    assert rest_client.create_order_calls == []
