from __future__ import annotations

import json
from pathlib import Path

from application.admin_api.usdc_pair_snapshot import (
    FileUsdcPairSnapshotOrderPlanLiveSubmitStore,
    UsdcPairSnapshotOrderPlanLiveSubmitRecord,
)
from tools import run_admin_api_usdc_pair_snapshot_live_readback as readback
from tools.run_admin_api_usdc_pair_snapshot_live_submit import (
    apply_usdc_pair_state_environment,
)


class FakeM58ReadbackRestClient:
    def __init__(self) -> None:
        self.get_order_calls: list[str] = []
        self.list_orders_calls: list[dict] = []

    def get_order(self, order_id):
        self.get_order_calls.append(order_id)
        return {
            "order": {
                "order_id": order_id,
                "client_order_id": "m58-live-plan-BTC-USDC",
                "product_id": "BTC-USDC",
                "status": "CANCELLED",
                "filled_size": "0",
                "filled_value": "0",
                "total_fees": "0",
                "outstanding_hold_amount": "0",
            }
        }

    def list_orders(self, **kwargs):
        self.list_orders_calls.append(dict(kwargs))
        return {"orders": [], "has_next": False}


def m58_submission_artifact(tmp_path: Path) -> Path:
    path = tmp_path / "m58-live-submit.json"
    path.write_text(
        json.dumps(
            {
                "artifact_type": (
                    "coinbase_admin_api_m58_usdc_snapshot_live_submit"
                ),
                "status": "failed",
                "submission_id": "m58-live-submission",
                "readiness_id": "m58-live-readiness",
                "plan_id": "m58-live-plan",
                "product_id": "BTC-USDC",
                "client_order_id": "m58-live-plan-BTC-USDC",
                "coinbase_order_id": "exchange-order-1",
                "coinbase_order_id_evidence_only": True,
                "submitted_notional_usdc": "1.09",
                "executed_notional_usdc": "0",
                "live_exchange_submitted": True,
                "live_coinbase_orders_ran": True,
                "live_coinbase_execution": "submitted_cancel_failed",
            }
        ),
        encoding="utf-8",
    )
    return path


def m58_submission_record(**overrides) -> UsdcPairSnapshotOrderPlanLiveSubmitRecord:
    values = {
        "submission_id": "m58-live-submission",
        "readiness_id": "m58-live-readiness",
        "plan_id": "m58-live-plan",
        "snapshot_run_id": "m58-live-snapshot",
        "product_id": "BTC-USDC",
        "client_order_id": "m58-live-plan-BTC-USDC",
        "submitted_at": "2026-07-06T19:57:38Z",
        "cancelled_at": "2026-07-06T19:57:39Z",
        "side": "BUY",
        "order_count": 1,
        "single_order_only": True,
        "submitted_notional_usdc": "1.09",
        "executed_notional_usdc": "0",
        "max_executed_notional_usdc": "0.01",
        "intended_limit_price": "31800.00",
        "reference_bid_price": "63780.00",
        "last_filled_price": "63780.00",
        "cancel_before_additional_orders": True,
        "additional_orders_blocked": True,
        "cancel_submitted": False,
        "cancel_rollback_complete": False,
        "cancel_rollback_plan_ref": "m58-cancel-before-additional-orders",
        "full_snapshot_fill_test": False,
        "approval_snapshot_id": "approval-1",
        "admission_audit_id": "admission-1",
        "cap_guard_decision_id": "cap-1",
        "reconciliation_plan_id": "recon-1",
        "live_service_decision_id": "live-service-1",
        "coinbase_order_id": "exchange-order-1",
        "coinbase_order_id_evidence_only": True,
        "order_configuration": {
            "limit_limit_gtc": {
                "quote_size": "1.09",
                "limit_price": "31800.00",
                "post_only": False,
            }
        },
        "submit_result": {"success": True},
        "cancel_result": {"success": False},
        "operator_stop_conditions": [
            "cancel that client_order_id before any additional order"
        ],
        "actor_id": "operator-001",
        "operator_intent": "m58_usdc_snapshot_live_submit",
        "idempotency_key": "idem-m58-live-submit",
        "payload_hash": "a" * 64,
        "audit_id": "audit-1",
        "operator_notes": "failed cancel seed",
        "live_exchange_submitted": True,
        "live_coinbase_orders_ran": True,
        "live_coinbase_execution": "submitted_cancel_failed",
        "notional_usdc": "1.09",
        "detail": "seed failed cancel record",
    }
    values.update(overrides)
    return UsdcPairSnapshotOrderPlanLiveSubmitRecord(**values)


def test_m58_live_readback_verifies_cancelled_non_fill_order(tmp_path):
    artifact = m58_submission_artifact(tmp_path)
    rest_client = FakeM58ReadbackRestClient()

    summary = readback.run_usdc_pair_snapshot_live_readback(
        rest_client,
        readback.UsdcPairSnapshotLiveReadbackConfig(
            submission_artifact=artifact,
            require_submission_artifact=True,
        ),
    )

    assert summary["status"] == "passed"
    assert summary["read_only"] is True
    assert summary["live_coinbase_read_ran"] is True
    assert summary["live_coinbase_orders_ran"] is False
    assert summary["live_coinbase_execution"] == "not_run"
    assert summary["client_order_id"] == "m58-live-plan-BTC-USDC"
    assert summary["exchange_order_id"] == "exchange-order-1"
    assert summary["order_status"] == "CANCELLED"
    assert summary["order_cancelled"] is True
    assert summary["executed_notional_usdc"] == "0"
    assert summary["total_fees"] == "0"
    assert summary["open_product_order_count"] == 0
    assert summary["m58_non_fill_cancel_verified"] is True
    assert summary["recovery_record_appended"] is False
    assert all(check["passed"] for check in summary["checks"])
    assert rest_client.get_order_calls == ["exchange-order-1"]
    assert rest_client.list_orders_calls == [
        {"product_ids": ["BTC-USDC"], "order_status": ["OPEN"], "limit": 20}
    ]


def test_m58_live_readback_validates_artifact_when_record_loaded(tmp_path):
    artifact = m58_submission_artifact(tmp_path)
    state_dir = tmp_path / "state"
    apply_usdc_pair_state_environment(state_dir)
    store = FileUsdcPairSnapshotOrderPlanLiveSubmitStore()
    store.append(m58_submission_record())
    rest_client = FakeM58ReadbackRestClient()

    summary = readback.run_usdc_pair_snapshot_live_readback(
        rest_client,
        readback.UsdcPairSnapshotLiveReadbackConfig(
            submission_id="m58-live-submission",
            submission_artifact=artifact,
            state_dir=state_dir,
            require_submission_artifact=True,
        ),
    )

    assert summary["status"] == "passed"
    assert summary["submission_record_present"] is True
    assert summary["submission_artifact_present"] is True
    assert all(check["passed"] for check in summary["checks"])


def test_m58_live_readback_appends_recovery_record(tmp_path):
    state_dir = tmp_path / "state"
    apply_usdc_pair_state_environment(state_dir)
    store = FileUsdcPairSnapshotOrderPlanLiveSubmitStore()
    store.append(m58_submission_record())
    rest_client = FakeM58ReadbackRestClient()

    summary = readback.run_usdc_pair_snapshot_live_readback(
        rest_client,
        readback.UsdcPairSnapshotLiveReadbackConfig(
            submission_id="m58-live-submission",
            state_dir=state_dir,
            append_recovery_record=True,
        ),
    )

    assert summary["status"] == "passed"
    assert summary["recovery_record_appended"] is True
    assert summary["recovery_submission_id"] == (
        "m58-live-submission-readback-recovery"
    )

    recovery = store.find_by_submission_id(
        "m58-live-submission-readback-recovery"
    )
    assert recovery is not None
    assert recovery.cancel_submitted is True
    assert recovery.cancel_rollback_complete is True
    assert recovery.live_coinbase_execution == "submitted_cancelled"
    assert recovery.executed_notional_usdc == "0"
    assert recovery.cancel_result["order_readback_status"] == "CANCELLED"
