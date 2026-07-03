from __future__ import annotations

import pytest

from application.admin_api.mvp_service import AdminMvpDependencies, AdminMvpService
from tests.regression.test_admin_mvp_api import FakeAccountRestClient, FakeRestClient
from tools.run_admin_api_manual_order_live_submit import (
    ManualLiveSubmitConfig,
    LiveSubmitConfirmationError,
    build_manual_order_body,
    run_manual_live_submit,
)


def test_manual_live_submit_body_defaults_to_small_limit_ioc_buy():
    body = build_manual_order_body(ManualLiveSubmitConfig(confirm_live_submit=True))

    assert body == {
        "product_id": "BTC-USDC",
        "side": "BUY",
        "order_type": "LIMIT",
        "quote_size": "1.00",
        "limit_price": "1000000.00",
        "time_in_force": "IOC",
        "post_only": False,
        "manual_live_acknowledgement": True,
    }


def test_manual_live_submit_requires_explicit_confirmation_before_service_calls():
    rest_client = FakeRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )

    with pytest.raises(LiveSubmitConfirmationError):
        run_manual_live_submit(service, ManualLiveSubmitConfig(confirm_live_submit=False))

    assert rest_client.create_order_calls == []


def test_manual_live_submit_records_admin_proof_chain_before_backend_rest_submission():
    rest_client = FakeAccountRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )

    summary = run_manual_live_submit(
        service,
        ManualLiveSubmitConfig(
            confirm_live_submit=True,
            idempotency_key="manual-live-submit-test",
            correlation_id="manual-live-submit-test-correlation",
        ),
    )

    assert summary["status"] == "passed"
    assert summary["live_coinbase_execution"] == "submitted"
    assert summary["notional_usdc"] == "1.00"
    assert summary["proof_chain_status"] == "passed"
    assert summary["final_status_code"] == 200
    assert summary["final_status"] == "accepted"
    assert summary["live_exchange_submitted"] is True
    assert summary["live_coinbase_orders_ran"] is True
    assert summary["paired_sell_required"] is False
    assert summary["coinbase_order_id"] == "exchange-order-live-1"
    assert rest_client.create_order_calls == [
        {
            "client_order_id": summary["client_order_id"],
            "product_id": "BTC-USDC",
            "side": "BUY",
            "order_configuration": {
                "sor_limit_ioc": {
                    "quote_size": "1.00",
                    "limit_price": "1000000.00",
                },
            },
        }
    ]
