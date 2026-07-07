from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from contextlib import nullcontext
from datetime import datetime, timezone
import json

import pytest

from tools import run_admin_api_usdc_pair_snapshot_live_submit as runner


class _FakeLiveExecutor:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def submit_and_cancel(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {
            "coinbase_order_id": "exchange-m58-runner-test-1",
            "submit_result": {
                "success": True,
                "order_id": "exchange-m58-runner-test-1",
                "client_order_id": kwargs["client_order_id"],
            },
            "cancel_result": {
                "success": True,
                "client_order_id": kwargs["client_order_id"],
            },
            "submitted_at": "2026-07-06T15:00:00+00:00",
            "cancelled_at": "2026-07-06T15:00:01+00:00",
            "order_configuration": kwargs["order_configuration"],
            "live_exchange_submitted": True,
            "live_coinbase_orders_ran": True,
            "live_coinbase_execution": "submitted_cancelled",
            "executed_notional_usdc": "0",
        }


def _config(tmp_path: Path, **overrides) -> runner.UsdcPairSnapshotLiveSubmitConfig:
    values = {
        "confirm_live_submit": True,
        "product_id": "BTC-USDC",
        "side": "BUY",
        "submitted_notional_usdc": "1.00",
        "max_executed_notional_usdc": "0.01",
        "reference_bid_price": "100.00",
        "reference_bid_price_source": "coinbase_advanced_trade.best_bid",
        "reference_bid_price_captured_at": (
            datetime.now(timezone.utc).isoformat()
        ),
        "last_filled_price": "100.00",
        "last_filled_price_source": "coinbase_advanced_trade.last_trade",
        "last_filled_price_captured_at": datetime.now(timezone.utc).isoformat(),
        "intended_limit_price": "50.00",
        "state_dir": str(tmp_path / "state"),
        "summary_output": str(tmp_path / "summary.json"),
        "run_id": "m58-runner-snapshot",
        "plan_id": "m58-runner-plan",
        "readiness_id": "m58-runner-readiness",
        "submission_id": "m58-runner-submission",
        "idempotency_prefix": "idem-m58-runner",
        "correlation_id": "corr-m58-runner",
        "actor_id": "operator-001",
        "roles": ("admin", "trader"),
    }
    values.update(overrides)
    return runner.UsdcPairSnapshotLiveSubmitConfig(**values)


def test_usdc_pair_snapshot_live_runner_requires_confirmation(tmp_path):
    config = _config(tmp_path, confirm_live_submit=False)

    with pytest.raises(runner.LiveSubmitConfirmationError):
        runner.validate_live_submit_config(config)


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"submitted_notional_usdc": "10.01"}, "must not exceed"),
        ({"full_snapshot_fill_test": True}, "manual review"),
        ({"intended_limit_price": "95.00"}, "BUY intended_limit_price"),
    ],
)
def test_usdc_pair_snapshot_live_runner_fails_closed(tmp_path, override, message):
    config = _config(tmp_path, **override)

    with pytest.raises(ValueError, match=message):
        runner.validate_live_submit_config(config)


def test_usdc_pair_snapshot_live_runner_records_submit_cancel_sequence(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-admin-token")
    config = _config(tmp_path)
    fake_executor = _FakeLiveExecutor()

    summary = runner.run_usdc_pair_snapshot_live_submit(
        config,
        live_executor=fake_executor,
        require_runtime_ready=False,
        require_credentials=False,
    )

    assert summary["status"] == "passed"
    assert summary["live_coinbase_execution"] == "submitted_cancelled"
    assert summary["live_exchange_submitted"] is True
    assert summary["live_coinbase_orders_ran"] is True
    assert summary["operator_requested_notional_usdc"] == "1.00"
    assert summary["requested_notional_usdc"] == "1.00"
    assert summary["reference_bid_price_source"] == (
        "coinbase_advanced_trade.best_bid"
    )
    assert summary["reference_bid_price_freshness_status"] == "fresh"
    assert summary["last_filled_price_source"] == (
        "coinbase_advanced_trade.last_trade"
    )
    assert summary["last_filled_price_freshness_status"] == "fresh"
    assert summary["submitted_notional_usdc"] == "1.00"
    assert summary["executed_notional_usdc"] == "0"
    assert summary["proof_chain_status_after_submission"] == "accepted"
    assert summary["proof_chain_blockers_after_submission"] == []
    assert summary["readiness_id"] == "m58-runner-readiness"
    assert summary["submission_id"] == "m58-runner-submission"

    assert len(fake_executor.calls) == 1
    live_call = fake_executor.calls[0]
    assert live_call["client_order_id"] == "m58-runner-plan-BTC-USDC"
    assert live_call["product_id"] == "BTC-USDC"
    assert live_call["side"] == "BUY"
    assert live_call["cancel_client_order_id"] == "m58-runner-plan-BTC-USDC"
    assert live_call["order_configuration"] == {
        "limit_limit_gtc": {
            "quote_size": "1.00",
            "limit_price": "50.00",
            "post_only": False,
        }
    }

    assert (tmp_path / "state" / "admin_api_usdc_pair_snapshot_runs.jsonl").exists()
    assert (
        tmp_path
        / "state"
        / "admin_api_usdc_pair_snapshot_order_plan_live_submit.jsonl"
    ).exists()


def test_usdc_pair_snapshot_live_runner_can_submit_from_run_state_handoff(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-admin-token")
    config = _config(
        tmp_path,
        submit_from_run_state=True,
        allowlist_readiness_id="m58-runner-allowlist-readiness",
        run_state_id="m58-runner-run-state",
    )
    fake_executor = _FakeLiveExecutor()

    summary = runner.run_usdc_pair_snapshot_live_submit(
        config,
        live_executor=fake_executor,
        require_runtime_ready=False,
        require_credentials=False,
    )

    assert summary["status"] == "passed"
    assert summary["live_submit_source"] == "allowlist_run_state"
    assert summary["allowlist_readiness_id"] == "m58-runner-allowlist-readiness"
    assert summary["run_state_id"] == "m58-runner-run-state"
    assert summary["run_state_status"] == "ready_no_live"
    assert summary["run_state_queued_product_ids"] == ["BTC-USDC"]
    assert summary["run_state_live_readiness_id"] == "m58-runner-readiness"
    assert summary["run_state_live_wallet_reservation_status"] == (
        "missing_no_live"
    )
    assert summary["run_state_live_wallet_reservation_blockers"] == [
        "live_wallet_reservation_missing",
        "live_wallet_debit_missing",
        "live_wallet_release_missing",
    ]
    assert summary["run_state_product_live_wallet_reservation_status"] == (
        "missing_no_live"
    )
    assert summary["run_state_product_live_wallet_reservation_blockers"] == [
        "live_wallet_reservation_missing",
        "live_wallet_debit_missing",
        "live_wallet_release_missing",
    ]
    assert summary["fanout_execution_status"] == "blocked"
    assert summary["fanout_blockers"] == [
        "fanout_execution_not_approved",
        "scheduler_blocked",
        "live_wallet_reservation_missing",
    ]
    assert summary["live_coinbase_execution"] == "submitted_cancelled"
    assert summary["submitted_notional_usdc"] == "1.00"
    assert summary["executed_notional_usdc"] == "0"

    assert len(fake_executor.calls) == 1
    assert fake_executor.calls[0]["client_order_id"] == "m58-runner-plan-BTC-USDC"

    assert (
        tmp_path
        / "state"
        / "admin_api_usdc_pair_snapshot_order_plan_allowlist_readiness.jsonl"
    ).exists()
    assert (
        tmp_path
        / "state"
        / "admin_api_usdc_pair_snapshot_allowlist_run_states.jsonl"
    ).exists()


def test_usdc_pair_snapshot_live_runner_bumps_minimum_request_for_high_price(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-admin-token")
    config = _config(
        tmp_path,
        reference_bid_price="64449.36",
        last_filled_price="64449.36",
        intended_limit_price="32224.00",
        submitted_notional_usdc="1.00",
    )
    fake_executor = _FakeLiveExecutor()

    summary = runner.run_usdc_pair_snapshot_live_submit(
        config,
        live_executor=fake_executor,
        require_runtime_ready=False,
        require_credentials=False,
    )

    assert summary["status"] == "passed"
    assert summary["operator_requested_notional_usdc"] == "1.00"
    assert summary["requested_notional_usdc"] == "1.01"
    assert summary["submitted_notional_usdc"] == "1.00"
    assert summary["executed_notional_usdc"] == "0"
    assert summary["live_coinbase_execution"] == "submitted_cancelled"
    assert fake_executor.calls[0]["order_configuration"] == {
        "limit_limit_gtc": {
            "quote_size": "1.00",
            "limit_price": "32224.00",
            "post_only": False,
        }
    }

    snapshot_rows = [
        json.loads(line)
        for line in (
            tmp_path / "state" / "admin_api_usdc_pair_snapshot_runs.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    plan_rows = [
        json.loads(line)
        for line in (
            tmp_path / "state" / "admin_api_usdc_pair_snapshot_order_plans.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    assert snapshot_rows[-1]["max_notional_per_product_usdc"] == "1.01"
    assert snapshot_rows[-1]["snapshot_rows"][0]["requested_notional_usdc"] == "1.01"
    planned_row = plan_rows[-1]["order_plan_rows"][0]
    assert planned_row["requested_notional_usdc"] == "1.01"
    assert planned_row["quote_size"] == "1.00"
    assert planned_row["planned_notional_usdc"] == "1.00"

    readiness_rows = [
        json.loads(line)
        for line in (
            tmp_path
            / "state"
            / "admin_api_usdc_pair_snapshot_order_plan_live_readiness.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    readiness = readiness_rows[-1]
    assert readiness["reference_bid_price_source"] == (
        "coinbase_advanced_trade.best_bid"
    )
    assert readiness["reference_bid_price_freshness_status"] == "fresh"
    assert readiness["last_filled_price_source"] == (
        "coinbase_advanced_trade.last_trade"
    )
    assert readiness["last_filled_price_freshness_status"] == "fresh"


def test_usdc_pair_snapshot_live_executor_falls_back_to_exchange_order_id(
    monkeypatch,
):
    from application.admin_api import usdc_pair_snapshot_live_execution as live_exec

    class FakeController:
        def track_inflight(self, _operation):
            return nullcontext()

    class FakeClient:
        def __init__(self) -> None:
            self.cancel_order_calls: list[str] = []
            self.exchange_cancel_calls: list[str] = []

        def create_order(self, **_kwargs):
            return {
                "success": True,
                "success_response": {
                    "order_id": "exchange-order-1",
                    "client_order_id": "client-order-1",
                },
            }

        def cancel_order(self, client_order_id):
            self.cancel_order_calls.append(client_order_id)
            return False

        def cancel_order_by_exchange_order_id(self, order_id):
            self.exchange_cancel_calls.append(order_id)
            return True

    fake_client = FakeClient()
    monkeypatch.setattr(
        live_exec.UsdcPairSnapshotLiveOrderExecutor,
        "_hydrate_backend_coinbase_credentials",
        staticmethod(lambda: None),
    )
    monkeypatch.setattr(
        live_exec,
        "build_admin_api_command_runtime_readiness",
        lambda: SimpleNamespace(runtime_ready=True, missing_reason=None),
    )
    monkeypatch.setattr(
        live_exec,
        "load_admin_api_rest_client",
        lambda: SimpleNamespace(available=True, client=fake_client),
    )
    monkeypatch.setattr(
        live_exec,
        "get_runtime_controller",
        lambda: FakeController(),
    )

    result = live_exec.UsdcPairSnapshotLiveOrderExecutor().submit_and_cancel(
        client_order_id="client-order-1",
        product_id="BTC-USDC",
        side="BUY",
        order_configuration={
            "limit_limit_gtc": {
                "quote_size": "1.09",
                "limit_price": "31800.00",
                "post_only": False,
            }
        },
        submitted_notional_usdc="1.09",
        max_executed_notional_usdc="0.01",
        cancel_client_order_id="client-order-1",
    )

    assert fake_client.cancel_order_calls == ["client-order-1"]
    assert fake_client.exchange_cancel_calls == ["exchange-order-1"]
    assert result["cancel_submitted"] is True
    assert result["cancel_rollback_complete"] is True
    assert result["live_coinbase_execution"] == "submitted_cancelled"
    assert result["cancel_result"]["success"] is True
    assert result["cancel_result"]["fallback_order_id"] == "exchange-order-1"
    assert result["cancel_result"]["initial_cancel_result"]["success"] is False
