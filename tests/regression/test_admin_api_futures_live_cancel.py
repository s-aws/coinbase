from __future__ import annotations

import json

import pytest

from application.admin_api.mvp_service import AdminMvpDependencies, AdminMvpService
from tests.regression.test_admin_mvp_api import FakeAccountRestClient
from tools.run_admin_api_futures_live_cancel import (
    FuturesLiveCancelConfig,
    LiveCancelConfirmationError,
    build_futures_live_cancel_body,
    refresh_existing_futures_live_cancel_summary,
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
    assert summary["operator_identity_key"] == "client_order_id"
    assert summary["coinbase_cancel_initial_identity_used"] == "client_order_id"
    assert summary["coinbase_cancel_initial_result_present"] is True
    assert summary["coinbase_cancel_initial_result_success"] is True
    assert summary["coinbase_cancel_fallback_attempted"] is False
    assert summary["coinbase_cancel_fallback_reason"] is None
    assert summary["coinbase_cancel_fallback_identity_used"] is None
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
    assert summary["cap_guard_decision_id"] == (
        "futures-cap-guard-futures-live-cancel-test"
    )
    assert summary["reconciliation_plan_id"] == (
        "futures-reconciliation-futures-live-cancel-test"
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
    assert rest_client.cancel_order_calls == [
        {"order_ids": ["client-futures-live-cancel-test"]}
    ]
    assert rest_client.create_order_calls == []


def test_futures_live_cancel_summary_audits_exchange_order_id_fallback():
    rest_client = FakeAccountRestClient()
    rest_client.cancel_orders_responses = [
        {
            "results": [
                {
                    "success": False,
                    "failure_reason": "UNKNOWN_CANCEL_ORDER",
                }
            ]
        },
        {
            "results": [
                {
                    "success": True,
                    "order_id": "exchange-futures-live-cancel-test",
                }
            ]
        },
    ]
    rest_client.list_orders_response = {
        "orders": [
            {
                "client_order_id": "client-futures-live-cancel-test",
                "order_id": "exchange-futures-live-cancel-test",
                "product_id": "AVP-20DEC30-CDE",
                "status": "OPEN",
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
    assert summary["client_order_id"] == "client-futures-live-cancel-test"
    assert summary["coinbase_cancel_identity_used"] == "exchange_order_id"
    assert summary["operator_identity_key"] == "client_order_id"
    assert summary["coinbase_cancel_initial_identity_used"] == "client_order_id"
    assert summary["coinbase_cancel_initial_result_present"] is True
    assert summary["coinbase_cancel_initial_result_success"] is False
    assert summary["coinbase_cancel_fallback_attempted"] is True
    assert (
        summary["coinbase_cancel_fallback_reason"]
        == "client_order_id_cancel_not_accepted"
    )
    assert summary["coinbase_cancel_fallback_identity_used"] == "exchange_order_id"
    assert summary["coinbase_cancel_order_read_attempted"] is True
    assert summary["coinbase_cancel_order_read_succeeded"] is True
    assert summary["exchange_order_id_present"] is True
    assert all(check["passed"] for check in summary["checks"])
    assert rest_client.cancel_order_calls == [
        {"order_ids": ["client-futures-live-cancel-test"]},
        {"order_ids": ["exchange-futures-live-cancel-test"]},
    ]


def test_futures_live_cancel_refreshes_existing_artifact_without_resubmitting(
    tmp_path,
):
    rest_client = FakeAccountRestClient()
    rest_client.cancel_orders_response = {
        "results": [
            {
                "success": True,
                "order_id": "client-futures-live-cancel-refresh",
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
    artifact_path = tmp_path / "futures-live-cancel.json"
    summary = run_futures_live_cancel(
        service,
        FuturesLiveCancelConfig(
            confirm_live_cancel=True,
            client_order_id="client-futures-live-cancel-refresh",
            product_id="AVP-20DEC30-CDE",
            idempotency_key="futures-live-cancel-refresh",
            correlation_id="futures-live-cancel-refresh-correlation",
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

    refreshed = refresh_existing_futures_live_cancel_summary(
        service,
        FuturesLiveCancelConfig(
            refresh_existing_artifact=True,
            summary_output=artifact_path,
            backend_contract_ref="current-ref",
            client_order_id="client-futures-live-cancel-refresh",
            idempotency_key="unrelated-refresh-key",
            correlation_id="futures-live-cancel-refresh-correlation",
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
    assert rest_client.cancel_order_calls == [
        {"order_ids": ["client-futures-live-cancel-refresh"]}
    ]
    assert rest_client.create_order_calls == []
