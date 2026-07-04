from __future__ import annotations

import pytest

from application.admin_api.mvp_service import AdminMvpDependencies, AdminMvpService
from tests.regression.test_admin_mvp_api import FakeAccountRestClient
from tools.run_admin_api_futures_live_cancel import (
    FuturesLiveCancelConfig,
    LiveCancelConfirmationError,
    build_futures_live_cancel_body,
    run_futures_live_cancel,
)


def test_futures_live_cancel_body_defaults_to_backend_controlled_acknowledgement():
    body = build_futures_live_cancel_body(
        FuturesLiveCancelConfig(
            confirm_live_cancel=True,
            client_order_id="client-futures-live-cancel-test",
        )
    )

    assert body == {
        "product_id": "AVP-20DEC30-CDE",
        "dry_run": False,
        "manual_live_acknowledgement": True,
        "operator_reason": "operator confirmed backend-controlled futures cancel",
    }


def test_futures_live_cancel_requires_explicit_confirmation_before_service_calls():
    rest_client = FakeAccountRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )

    with pytest.raises(LiveCancelConfirmationError):
        run_futures_live_cancel(
            service,
            FuturesLiveCancelConfig(
                confirm_live_cancel=False,
                client_order_id="client-futures-live-cancel-test",
            ),
        )

    assert rest_client.cancel_order_calls == []
    assert rest_client.create_order_calls == []
    assert service.store.service_decisions == {}
    assert service.store.live_adapter_decisions == {}


def test_futures_live_cancel_records_backend_evidence_before_rest_submission():
    rest_client = FakeAccountRestClient()
    rest_client.cancel_orders_response = {
        "results": [
            {
                "success": True,
                "order_id": "client-futures-live-cancel-test",
            }
        ]
    }
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )

    summary = run_futures_live_cancel(
        service,
        FuturesLiveCancelConfig(
            confirm_live_cancel=True,
            client_order_id="client-futures-live-cancel-test",
            product_id="AVP-20DEC30-CDE",
            idempotency_key="futures-live-cancel-test",
            correlation_id="futures-live-cancel-test-correlation",
            backend_contract_ref="backend-ref",
        ),
    )

    assert summary["status"] == "passed"
    assert summary["artifact_type"] == "coinbase_admin_api_futures_live_cancel"
    assert summary["live_coinbase_execution"] == "submitted"
    assert summary["submitted_notional_usdc"] == "0"
    assert summary["notional_usdc"] == "0"
    assert summary["final_status_code"] == 200
    assert summary["final_status"] == "accepted"
    assert summary["failure_stage"] is None
    assert summary["route"] == "/api/v1/futures/orders/client-futures-live-cancel-test/cancel"
    assert summary["client_order_id"] == "client-futures-live-cancel-test"
    assert summary["product_id"] == "AVP-20DEC30-CDE"
    assert summary["coinbase_cancel_submission_allowed"] is True
    assert summary["coinbase_cancel_identity_used"] == "client_order_id"
    assert summary["coinbase_cancel_order_read_attempted"] is False
    assert summary["coinbase_cancel_order_read_succeeded"] is False
    assert summary["exchange_order_id_present"] is False
    assert summary["cancel_result_present"] is True
    assert summary["cancel_result_success"] is True
    assert summary["live_exchange_submitted"] is True
    assert summary["live_coinbase_orders_ran"] is True
    assert summary["exchange_order_id_evidence_only"] is True
    assert summary["service_decision_status"] == "accepted"
    assert summary["adapter_decision_count"] == 4
    assert summary["audit_event_count"] == 1
    assert all(check["passed"] for check in summary["checks"])
    assert rest_client.cancel_order_calls == [
        {"order_ids": ["client-futures-live-cancel-test"]}
    ]
    assert rest_client.create_order_calls == []
