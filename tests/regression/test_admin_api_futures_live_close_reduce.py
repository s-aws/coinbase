from __future__ import annotations

import json

import pytest

from application.admin_api.mvp_service import (
    AdminMvpDependencies,
    AdminMvpEvidenceLog,
    AdminMvpService,
    AdminMvpStore,
)
from tests.regression.test_admin_mvp_api import FakeAccountRestClient
from tools.run_admin_api_futures_live_close_reduce import (
    FuturesLiveCloseReduceConfig,
    LiveCloseReduceConfirmationError,
    build_futures_live_close_reduce_body,
    refresh_existing_futures_live_close_reduce_summary,
    run_futures_live_close_reduce,
)


def test_futures_live_close_reduce_body_requires_authoritative_avp_position_key():
    body = build_futures_live_close_reduce_body(
        FuturesLiveCloseReduceConfig(
            confirm_live_close_reduce=True,
            position_key="futures_position:portfolio-real-1:AVP-20DEC30-CDE",
            limit_price="6.93",
        )
    )

    assert body == {
        "position_key": "futures_position:portfolio-real-1:AVP-20DEC30-CDE",
        "product_id": "AVP-20DEC30-CDE",
        "limit_price": "6.93",
        "size": "1",
        "dry_run": False,
        "manual_live_acknowledgement": True,
        "operator_reason": "operator confirmed backend-controlled futures close/reduce",
    }


def test_futures_live_close_reduce_requires_explicit_confirmation_before_service_calls():
    rest_client = FakeAccountRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        ),
        store=AdminMvpStore(),
        evidence_log=AdminMvpEvidenceLog(),
    )

    with pytest.raises(LiveCloseReduceConfirmationError):
        run_futures_live_close_reduce(
            service,
            FuturesLiveCloseReduceConfig(confirm_live_close_reduce=False),
        )

    assert rest_client.close_position_calls == []
    assert rest_client.create_order_calls == []
    assert rest_client.cancel_order_calls == []
    assert service.store.service_decisions == {}
    assert service.store.live_adapter_decisions == {}


def test_futures_live_close_reduce_records_backend_evidence_before_rest_submission():
    rest_client = FakeAccountRestClient()
    rest_client.futures_positions["AVP-20DEC30-CDE"] = {
        "product_id": "AVP-20DEC30-CDE",
        "side": "LONG",
        "number_of_contracts": "1",
        "current_price": "6.93",
        "entry_price": "6.86",
    }
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        ),
        store=AdminMvpStore(),
        evidence_log=AdminMvpEvidenceLog(),
    )

    summary = run_futures_live_close_reduce(
        service,
        FuturesLiveCloseReduceConfig(
            confirm_live_close_reduce=True,
            idempotency_key="futures-live-close-reduce-test",
            correlation_id="futures-live-close-reduce-test-correlation",
        ),
    )

    assert summary["status"] == "passed"
    assert summary["live_coinbase_execution"] == "submitted"
    assert summary["notional_usdc"] == "69.30"
    assert summary["submitted_notional_usdc"] == "69.30"
    assert summary["final_status_code"] == 200
    assert summary["final_status"] == "accepted"
    assert summary["failure_stage"] is None
    assert summary["position_key"] == (
        "futures_position:portfolio-real-1:AVP-20DEC30-CDE"
    )
    assert summary["product_id"] == "AVP-20DEC30-CDE"
    assert summary["client_order_id"] == "futures-live-close-reduce-test"
    assert summary["limit_price"] == "6.93"
    assert summary["size"] == "1"
    assert summary["contract_size"] == "10"
    assert summary["max_submitted_notional_usdc"] == "100.00"
    assert summary["max_executed_notional_usdc"] == "100.00"
    assert summary["position_read_found"] is True
    assert summary["position_read_side_present"] is True
    assert summary["position_read_contracts_at_least_requested"] is True
    assert summary["live_exchange_submitted"] is True
    assert summary["live_coinbase_orders_ran"] is True
    assert summary["exchange_order_id_evidence_only"] is True
    assert summary["exchange_order_id_present"] is True
    assert summary["service_decision_status"] == "accepted"
    assert summary["adapter_decision_count"] == 4
    assert summary["cap_guard_decision_id"] == (
        "futures-cap-guard-futures-live-close-reduce-test"
    )
    assert summary["reconciliation_plan_id"] == (
        "futures-reconciliation-futures-live-close-reduce-test"
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
    assert rest_client.close_position_calls == [
        {
            "client_order_id": "futures-live-close-reduce-test",
            "product_id": "AVP-20DEC30-CDE",
            "size": "1",
        }
    ]
    assert rest_client.create_order_calls == []
    assert rest_client.cancel_order_calls == []


def test_futures_live_close_reduce_refreshes_existing_artifact_without_resubmitting(
    tmp_path,
):
    rest_client = FakeAccountRestClient()
    rest_client.futures_positions["AVP-20DEC30-CDE"] = {
        "product_id": "AVP-20DEC30-CDE",
        "side": "LONG",
        "number_of_contracts": "1",
        "current_price": "6.93",
        "entry_price": "6.86",
    }
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        ),
        store=AdminMvpStore(),
        evidence_log=AdminMvpEvidenceLog(),
    )
    artifact_path = tmp_path / "futures-live-close-reduce.json"
    summary = run_futures_live_close_reduce(
        service,
        FuturesLiveCloseReduceConfig(
            confirm_live_close_reduce=True,
            idempotency_key="futures-live-close-reduce-refresh",
            correlation_id="futures-live-close-reduce-refresh-correlation",
            backend_contract_ref="old-ref",
            summary_output=artifact_path,
        ),
    )
    stale_summary = {
        **summary,
        "backend_git_commit": "old-ref",
        "backend_contract_ref": "old-ref",
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
    artifact_path.write_text(
        json.dumps(stale_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    refreshed = refresh_existing_futures_live_close_reduce_summary(
        service,
        FuturesLiveCloseReduceConfig(
            refresh_existing_artifact=True,
            summary_output=artifact_path,
            backend_contract_ref="current-ref",
            idempotency_key="unrelated-refresh-key",
            correlation_id="futures-live-close-reduce-refresh-correlation",
        ),
    )

    assert refreshed["status"] == "passed"
    assert refreshed["refreshed_existing_artifact"] is True
    assert refreshed["refresh_live_coinbase_execution"] == "not_run"
    assert refreshed["refresh_notional_usdc"] == "0"
    assert refreshed["backend_contract_ref"] == "current-ref"
    assert refreshed["audit_proof_chain_readback_present"] is True
    assert refreshed["audit_submission_event_id"] == refreshed["submission_event_id"]
    assert refreshed["audit_cap_guard_decision_id"] == refreshed["cap_guard_decision_id"]
    assert (
        refreshed["audit_reconciliation_plan_id"]
        == refreshed["reconciliation_plan_id"]
    )
    assert {
        item["name"]: item["passed"] for item in refreshed["checks"]
    }["futures_audit_workbench_proof_chain_readback"] is True
    assert len(rest_client.close_position_calls) == 1
    assert rest_client.create_order_calls == []
    assert rest_client.cancel_order_calls == []
