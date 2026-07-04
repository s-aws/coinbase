from __future__ import annotations

import pytest

from application.admin_api.mvp_service import AdminMvpDependencies, AdminMvpService
from tests.regression.test_admin_mvp_api import FakeAccountRestClient
from tools.run_admin_api_futures_live_submit import (
    FuturesLiveSubmitConfig,
    LiveSubmitConfirmationError,
    build_futures_live_submit_body,
    refresh_existing_futures_live_submit_summary,
    run_futures_live_submit,
    write_json,
)


def test_futures_live_submit_body_defaults_to_small_limit_buy():
    body = build_futures_live_submit_body(
        FuturesLiveSubmitConfig(confirm_live_submit=True, limit_price="100")
    )

    assert body == {
        "product_id": "AVP-20DEC30-CDE",
        "side": "BUY",
        "order_type": "LIMIT",
        "limit_price": "100",
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
    assert summary["notional_usdc"] == "69.20"
    assert summary["submitted_notional_usdc"] == "69.20"
    assert summary["final_status_code"] == 200
    assert summary["final_status"] == "accepted"
    assert summary["failure_stage"] is None
    assert summary["client_order_id"] == "futures-live-submit-test"
    assert summary["limit_price"] == "6.92"
    assert summary["contract_size"] == "10"
    assert summary["max_submitted_notional_usdc"] == "100.00"
    assert summary["max_executed_notional_usdc"] == "100.00"
    assert summary["live_exchange_submitted"] is True
    assert summary["live_coinbase_orders_ran"] is True
    assert summary["paired_sell_required"] is False
    assert summary["exchange_order_id_evidence_only"] is True
    assert summary["exchange_order_id_present"] is True
    assert summary["service_decision_status"] == "accepted"
    assert summary["adapter_decision_count"] == 4
    assert summary["cap_guard_decision_id"] == (
        "futures-cap-guard-futures-live-submit-test"
    )
    assert summary["reconciliation_plan_id"] == (
        "futures-reconciliation-futures-live-submit-test"
    )
    assert summary["audit_proof_chain_readback_present"] is True
    assert summary["audit_submission_event_id"] == summary["submission_event_id"]
    assert summary["audit_cap_guard_present"] is True
    assert summary["audit_cap_guard_decision_id"] == summary["cap_guard_decision_id"]
    assert summary["audit_cap_guard_source"] == "admin_api_cap_guard_log"
    assert summary["audit_cap_guard_recorded_at"]
    assert summary["audit_reconciliation_plan_present"] is True
    assert summary["audit_reconciliation_plan_id"] == summary["reconciliation_plan_id"]
    assert summary["audit_reconciliation_plan_source"] == (
        "admin_api_reconciliation_plan_log"
    )
    assert summary["audit_reconciliation_plan_recorded_at"]
    assert {
        item["name"]: item["passed"] for item in summary["checks"]
    }["futures_audit_workbench_proof_chain_readback"] is True
    assert all(check["passed"] for check in summary["checks"])
    assert rest_client.create_order_calls == [
        {
            "client_order_id": "futures-live-submit-test",
            "product_id": "AVP-20DEC30-CDE",
            "side": "BUY",
            "order_configuration": {
                "limit_limit_gtc": {
                    "base_size": "1",
                    "limit_price": "6.92",
                    "post_only": False,
                }
            },
        }
    ]
    assert rest_client.get_product_dict_calls == [
        "AVP-20DEC30-CDE",
        "AVP-20DEC30-CDE",
        "BIP-20DEC30-CDE",
    ]


def test_futures_live_submit_filters_audit_readback_to_submission_client_order_id():
    rest_client = FakeAccountRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )
    for index in range(12):
        decision_id = f"old-futures-command-{index}"
        service.store.futures_command_decisions[decision_id] = {
            "decision_id": decision_id,
            "identity_key": "client_order_id",
            "identity_value": f"old-futures-live-submit-{index}",
            "client_order_id": f"old-futures-live-submit-{index}",
            "route": "/api/v1/futures/orders",
            "status": "accepted",
            "live_exchange_submitted": True,
            "live_coinbase_orders_ran": True,
        }

    summary = run_futures_live_submit(
        service,
        FuturesLiveSubmitConfig(
            confirm_live_submit=True,
            idempotency_key="futures-live-submit-page-target",
            correlation_id="futures-live-submit-page-target-correlation",
        ),
    )

    assert summary["status"] == "passed"
    assert summary["audit_proof_chain_readback_present"] is True
    assert summary["audit_submission_event_id"] == summary["submission_event_id"]
    assert summary["audit_cap_guard_decision_id"] == summary["cap_guard_decision_id"]
    assert summary["audit_reconciliation_plan_id"] == summary["reconciliation_plan_id"]


def test_futures_live_submit_refreshes_existing_artifact_without_second_order(tmp_path):
    rest_client = FakeAccountRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )
    artifact_path = tmp_path / "futures-live-submit.json"
    summary = run_futures_live_submit(
        service,
        FuturesLiveSubmitConfig(
            confirm_live_submit=True,
            idempotency_key="futures-live-submit-refresh",
            correlation_id="futures-live-submit-refresh-correlation",
            summary_output=artifact_path,
        ),
    )
    stale_summary = {
        **summary,
        "status": "failed",
        "audit_proof_chain_readback_present": False,
        "audit_submission_event_id": None,
        "audit_cap_guard_present": None,
        "audit_cap_guard_decision_id": None,
        "audit_cap_guard_source": None,
        "audit_cap_guard_recorded_at": None,
        "audit_reconciliation_plan_present": None,
        "audit_reconciliation_plan_id": None,
        "audit_reconciliation_plan_source": None,
        "audit_reconciliation_plan_recorded_at": None,
        "checks": [
            {
                **check,
                "passed": (
                    False
                    if check["name"]
                    == "futures_audit_workbench_proof_chain_readback"
                    else check["passed"]
                ),
            }
            for check in summary["checks"]
        ],
    }
    write_json(artifact_path, stale_summary)

    refreshed = refresh_existing_futures_live_submit_summary(
        service,
        FuturesLiveSubmitConfig(
            refresh_existing_artifact=True,
            summary_output=artifact_path,
            idempotency_key="futures-live-submit-refresh",
            correlation_id="futures-live-submit-refresh-correlation",
        ),
    )

    assert refreshed["status"] == "passed"
    assert refreshed["refreshed_existing_artifact"] is True
    assert refreshed["refresh_live_coinbase_execution"] == "not_run"
    assert refreshed["refresh_notional_usdc"] == "0"
    assert refreshed["audit_proof_chain_readback_present"] is True
    assert refreshed["audit_submission_event_id"] == refreshed["submission_event_id"]
    assert refreshed["audit_cap_guard_decision_id"] == refreshed["cap_guard_decision_id"]
    assert (
        refreshed["audit_reconciliation_plan_id"]
        == refreshed["reconciliation_plan_id"]
    )
    assert len(rest_client.create_order_calls) == 1


def test_futures_live_submit_refresh_reconstructs_missing_artifact_from_state(tmp_path):
    rest_client = FakeAccountRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )
    missing_artifact_path = tmp_path / "deleted-futures-live-submit.json"
    run_futures_live_submit(
        service,
        FuturesLiveSubmitConfig(
            confirm_live_submit=True,
            idempotency_key="futures-live-submit-reconstruct",
            correlation_id="futures-live-submit-reconstruct-correlation",
            summary_output=missing_artifact_path,
        ),
    )

    refreshed = refresh_existing_futures_live_submit_summary(
        service,
        FuturesLiveSubmitConfig(
            refresh_existing_artifact=True,
            refresh_client_order_id="futures-live-submit-reconstruct",
            summary_output=missing_artifact_path,
            idempotency_key="unrelated-refresh-key",
            correlation_id="futures-live-submit-reconstruct-correlation",
        ),
    )

    assert refreshed["status"] == "passed"
    assert refreshed["client_order_id"] == "futures-live-submit-reconstruct"
    assert refreshed["live_coinbase_execution"] == "submitted"
    assert refreshed["refresh_live_coinbase_execution"] == "not_run"
    assert refreshed["audit_proof_chain_readback_present"] is True
    assert refreshed["audit_submission_event_id"] == refreshed["submission_event_id"]
    assert refreshed["audit_cap_guard_decision_id"] == refreshed["cap_guard_decision_id"]
    assert (
        refreshed["audit_reconciliation_plan_id"]
        == refreshed["reconciliation_plan_id"]
    )
    assert len(rest_client.create_order_calls) == 1
