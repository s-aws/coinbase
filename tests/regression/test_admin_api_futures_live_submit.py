from __future__ import annotations

import pytest

from application.admin_api.mvp_service import AdminMvpDependencies, AdminMvpService
from tests.regression.test_admin_mvp_api import FakeAccountRestClient
from tools.run_admin_api_futures_live_submit import (
    FuturesLiveSubmitConfig,
    LiveSubmitConfirmationError,
    build_futures_live_submit_body,
    run_futures_live_submit,
)


def test_futures_live_submit_body_defaults_to_small_limit_buy():
    body = build_futures_live_submit_body(
        FuturesLiveSubmitConfig(confirm_live_submit=True)
    )

    assert body == {
        "product_id": "BIP-20DEC30-CDE",
        "side": "BUY",
        "order_type": "LIMIT",
        "limit_price": "1",
        "size": "1",
        "post_only": False,
        "dry_run": False,
        "manual_live_acknowledgement": True,
    }


def test_futures_live_submit_requires_explicit_confirmation_before_service_calls():
    rest_client = FakeAccountRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )

    with pytest.raises(LiveSubmitConfirmationError):
        run_futures_live_submit(
            service,
            FuturesLiveSubmitConfig(confirm_live_submit=False),
        )

    assert rest_client.create_order_calls == []
    assert service.store.service_decisions == {}
    assert service.store.live_adapter_decisions == {}


def test_futures_live_submit_records_backend_evidence_before_rest_submission():
    rest_client = FakeAccountRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )

    summary = run_futures_live_submit(
        service,
        FuturesLiveSubmitConfig(
            confirm_live_submit=True,
            idempotency_key="futures-live-submit-test",
            correlation_id="futures-live-submit-test-correlation",
        ),
    )

    assert summary["status"] == "passed"
    assert summary["live_coinbase_execution"] == "submitted"
    assert summary["notional_usdc"] == "1.00"
    assert summary["submitted_notional_usdc"] == "1.00"
    assert summary["final_status_code"] == 200
    assert summary["final_status"] == "accepted"
    assert summary["failure_stage"] is None
    assert summary["client_order_id"] == "futures-live-submit-test"
    assert summary["live_exchange_submitted"] is True
    assert summary["live_coinbase_orders_ran"] is True
    assert summary["paired_sell_required"] is False
    assert summary["exchange_order_id_evidence_only"] is True
    assert summary["exchange_order_id_present"] is True
    assert summary["service_decision_status"] == "accepted"
    assert summary["adapter_decision_count"] == 4
    assert all(check["passed"] for check in summary["checks"])
    assert rest_client.create_order_calls == [
        {
            "client_order_id": "futures-live-submit-test",
            "product_id": "BIP-20DEC30-CDE",
            "side": "BUY",
            "order_configuration": {
                "limit_limit_gtc": {
                    "base_size": "1",
                    "limit_price": "1",
                    "post_only": False,
                }
            },
        }
    ]
