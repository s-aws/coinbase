from __future__ import annotations

import pytest

from application.admin_api.mvp_service import (
    AdminMvpDependencies,
    AdminMvpEvidenceLog,
    AdminMvpService,
    AdminMvpStore,
)
from tests.regression.test_admin_mvp_api import FakeAccountRestClient
from tools.run_admin_api_spot_live_cancel import (
    LiveCapExceededError,
    LiveCancelConfirmationError,
    SpotLiveCancelConfig,
    build_spot_live_cancel_body,
    run_spot_live_cancel,
)


def _isolated_service(rest_client, *, uuid_factory=None):
    optional = {"uuid_factory": uuid_factory} if uuid_factory is not None else {}
    return AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
            **optional,
        ),
        store=AdminMvpStore(),
        evidence_log=AdminMvpEvidenceLog(),
    )


def test_spot_live_cancel_body_defaults_to_backend_controlled_acknowledgement():
    body = build_spot_live_cancel_body(
        SpotLiveCancelConfig(
            confirm_live_cancel=True,
            client_order_id="client-spot-live-cancel-test",
        )
    )

    assert body["manual_live_acknowledgement"] is True
    assert body["reason"] == "operator_requested_cancel"
    assert body["operator_reason"] == "operator confirmed backend-controlled spot cancel"
    assert isinstance(body["payload_hash"], str)
    assert len(body["payload_hash"]) == 64


def test_spot_live_cancel_requires_explicit_confirmation_before_service_calls():
    rest_client = FakeAccountRestClient()
    service = _isolated_service(rest_client)

    with pytest.raises(LiveCancelConfirmationError):
        run_spot_live_cancel(
            service,
            SpotLiveCancelConfig(
                confirm_live_cancel=False,
                client_order_id="client-spot-live-cancel-test",
            ),
        )

    assert rest_client.cancel_order_calls == []
    assert rest_client.create_order_calls == []
    assert service.store.service_decisions == {}
    assert service.store.spot_command_decisions == {}


def test_spot_live_cancel_records_backend_evidence_before_rest_submission():
    rest_client = FakeAccountRestClient()
    rest_client.cancel_orders_response = {
        "results": [
            {
                "success": True,
                "order_id": "client-spot-live-cancel-test",
            }
        ]
    }
    service = _isolated_service(rest_client)

    summary = run_spot_live_cancel(
        service,
        SpotLiveCancelConfig(
            confirm_live_cancel=True,
            client_order_id="client-spot-live-cancel-test",
            idempotency_key="spot-live-cancel-test",
            correlation_id="spot-live-cancel-test-correlation",
            backend_contract_ref="backend-ref",
        ),
    )

    assert summary["status"] == "passed"
    assert summary["artifact_type"] == "coinbase_admin_api_spot_live_cancel"
    assert summary["client_order_id"] == "client-spot-live-cancel-test"
    assert summary["backend_contract_ref"] == "backend-ref"
    assert summary["proof_chain_status"] == "passed"
    assert summary["cancel_order_proof_chain_status"] == "passed"
    assert summary["cancel_order_missing_gate_count"] == 0
    assert summary["final_status"] == "accepted"
    assert summary["final_status_code"] == 200
    assert summary["failure_stage"] is None
    assert summary["coinbase_cancel_submission_allowed"] is True
    assert summary["cancel_result_success"] is True
    assert summary["live_exchange_submitted"] is True
    assert summary["live_coinbase_orders_ran"] is True
    assert summary["live_coinbase_execution"] == "submitted"
    assert summary["notional_usdc"] == "0"
    assert summary["submitted_notional_usdc"] == "0"
    assert summary["executed_notional_usdc"] == "0"
    assert summary["audit_event_count"] >= 1
    assert summary["command_suite_status"] in {"ready", "approval_required"}
    assert {
        check["name"]: check["passed"] for check in summary["checks"]
    }["spot_live_cancel_accepted"] is True
    assert all(check["passed"] for check in summary["checks"])
    assert rest_client.cancel_order_calls == [
        {"order_ids": ["client-spot-live-cancel-test"]}
    ]
    assert rest_client.create_order_calls == []


def test_spot_live_cancel_can_seed_resting_gtc_order_before_cancel():
    rest_client = FakeAccountRestClient()
    rest_client.create_order_response = {
        "success": True,
        "success_response": {"order_id": "seed-exchange-order-1"},
    }
    rest_client.cancel_orders_response = {
        "results": [
            {
                "success": True,
                "order_id": "spot-live-cancel-seed-test-order",
            }
        ]
    }
    service = _isolated_service(
        rest_client,
        uuid_factory=lambda: "spot-live-cancel-seed-test-order",
    )

    summary = run_spot_live_cancel(
        service,
        SpotLiveCancelConfig(
            confirm_live_cancel=True,
            seed_resting_order=True,
            idempotency_key="spot-live-cancel-seed-test",
            correlation_id="spot-live-cancel-seed-test-correlation",
            seed_product_id="BTC-USDC",
            seed_base_size="0.0002",
            seed_limit_price="5000.00",
            backend_contract_ref="backend-ref",
        ),
    )

    assert summary["status"] == "passed"
    assert summary["seed_resting_order"] is True
    assert summary["seed_order_status"] == "accepted"
    assert summary["seed_order_live_exchange_submitted"] is True
    assert summary["seed_order_client_order_id"] == "spot-live-cancel-seed-test-order"
    assert summary["seed_order_submitted_notional_usdc"] == "1.00"
    assert summary["seed_order_coinbase_order_id"] == "seed-exchange-order-1"
    assert summary["client_order_id"] == "spot-live-cancel-seed-test-order"
    assert summary["final_status"] == "accepted"
    assert summary["notional_usdc"] == "0"
    assert summary["submitted_notional_usdc"] == "0"
    assert summary["executed_notional_usdc"] == "0"
    assert all(check["passed"] for check in summary["checks"])
    assert rest_client.create_order_calls == [
        {
            "client_order_id": "spot-live-cancel-seed-test-order",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "order_configuration": {
                "limit_limit_gtc": {
                    "base_size": "0.0002",
                    "limit_price": "5000.00",
                    "post_only": True,
                },
            },
        }
    ]
    assert rest_client.cancel_order_calls == [
        {"order_ids": ["spot-live-cancel-seed-test-order"]}
    ]


def test_spot_live_cancel_blocks_seed_when_state_would_exceed_submitted_cap(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "admin_api_audit.jsonl").write_text(
        (
            '{"collection":"spot_command_decisions","record":{'
            '"action_class":"live_exchange_place",'
            '"status":"accepted",'
            '"live_exchange_submitted":true,'
            '"live_coinbase_orders_ran":true,'
            '"notional_usdc":"2.00",'
            '"client_order_id":"previous-live-seed"'
            "}}\n"
        ),
        encoding="utf-8",
    )
    rest_client = FakeAccountRestClient()
    service = _isolated_service(
        rest_client,
        uuid_factory=lambda: "spot-live-cancel-seed-over-cap",
    )

    with pytest.raises(LiveCapExceededError, match="Spot live cancel seed would exceed"):
        run_spot_live_cancel(
            service,
            SpotLiveCancelConfig(
                confirm_live_cancel=True,
                seed_resting_order=True,
                state_dir=state_dir,
                seed_product_id="USDT-USDC",
                seed_base_size="2.00",
                seed_limit_price="0.9980",
                seed_max_submitted_notional_usdc="3.10",
                backend_contract_ref="backend-ref",
            ),
        )

    assert rest_client.create_order_calls == []
    assert rest_client.cancel_order_calls == []


def test_spot_live_cancel_summary_records_exchange_id_fallback_when_needed():
    rest_client = FakeAccountRestClient()
    rest_client.create_order_response = {
        "success": True,
        "success_response": {"order_id": "exchange-spot-live-cancel-seed"},
    }
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
                    "order_id": "exchange-spot-live-cancel-seed",
                }
            ]
        },
    ]
    rest_client.list_orders_response = {
        "orders": [
            {
                "client_order_id": "spot-live-cancel-seed-fallback-order",
                "order_id": "exchange-spot-live-cancel-seed",
                "product_id": "USDT-USDC",
                "status": "OPEN",
            }
        ]
    }
    service = _isolated_service(
        rest_client,
        uuid_factory=lambda: "spot-live-cancel-seed-fallback-order",
    )

    summary = run_spot_live_cancel(
        service,
        SpotLiveCancelConfig(
            confirm_live_cancel=True,
            seed_resting_order=True,
            idempotency_key="spot-live-cancel-seed-fallback",
            correlation_id="spot-live-cancel-seed-fallback-correlation",
            seed_product_id="USDT-USDC",
            seed_base_size="2.00",
            seed_limit_price="0.9980",
            backend_contract_ref="backend-ref",
        ),
    )

    assert summary["status"] == "passed"
    assert summary["client_order_id"] == "spot-live-cancel-seed-fallback-order"
    assert summary["seed_order_coinbase_order_id"] == "exchange-spot-live-cancel-seed"
    assert summary["coinbase_cancel_identity_used"] == "exchange_order_id"
    assert summary["operator_identity_key"] == "client_order_id"
    assert summary["coinbase_cancel_initial_identity_used"] == "client_order_id"
    assert summary["coinbase_cancel_initial_result_success"] is False
    assert summary["coinbase_cancel_fallback_attempted"] is True
    assert summary["coinbase_cancel_fallback_identity_used"] == "exchange_order_id"
    assert summary["coinbase_cancel_order_read_attempted"] is True
    assert summary["coinbase_cancel_order_read_succeeded"] is True
    assert summary["exchange_order_id_present"] is True
    assert summary["exchange_order_id_evidence_only"] is True
    assert all(check["passed"] for check in summary["checks"])
    assert rest_client.cancel_order_calls == [
        {"order_ids": ["spot-live-cancel-seed-fallback-order"]},
        {"order_ids": ["exchange-spot-live-cancel-seed"]},
    ]
    assert rest_client.list_orders_calls == [{"order_status": ["OPEN"]}]
