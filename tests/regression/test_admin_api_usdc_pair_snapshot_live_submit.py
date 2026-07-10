from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from contextlib import nullcontext
from datetime import datetime, timezone
import json

import pytest

from tools import run_admin_api_usdc_pair_snapshot_live_submit as runner


@pytest.fixture(autouse=True)
def _stable_route_rate_window_for_runner_tests(monkeypatch):
    from api.v1.routes import automation as automation_routes

    monkeypatch.setattr(
        automation_routes,
        "USDC_PAIR_SNAPSHOT_DEFAULT_RATE_LIMIT_WINDOW_SECONDS",
        30,
    )


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


class _FailingFanoutExecutor:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def submit_and_cancel_all(self, **kwargs):
        self.calls.append(dict(kwargs))
        raise AssertionError(
            "fan-out executor must not run for proof-blocked state"
        )


def _fanout_buy_order_configuration(
    quote_size: str,
    *,
    limit_price: str = "31500.00",
) -> dict:
    return {
        "limit_limit_gtc": {
            "quote_size": quote_size,
            "limit_price": limit_price,
            "post_only": False,
        }
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
    assert summary["correlation_id"] == "corr-m58-runner"
    assert summary["live_submit_audit_id"]
    assert summary["submission_audit_id"] == summary["live_submit_audit_id"]

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
        "ready_no_live"
    )
    assert summary["run_state_live_wallet_reservation_ids"] == [
        "idem-m58-runner-wallet-reservation-btc_usdc"
    ]
    assert summary["run_state_live_wallet_reserved_notional_usdc"] == "1.00"
    assert summary["run_state_live_wallet_debit_ids"] == [
        "idem-m58-runner-wallet-debit-btc_usdc"
    ]
    assert summary["run_state_live_wallet_debited_notional_usdc"] == "1.00"
    assert summary["run_state_live_wallet_release_ids"] == [
        "idem-m58-runner-wallet-release-btc_usdc"
    ]
    assert summary["run_state_live_wallet_released_notional_usdc"] == "1.00"
    assert summary["run_state_live_wallet_reservation_blockers"] == []
    assert summary["run_state_product_live_wallet_reservation_status"] == (
        "ready_no_live"
    )
    assert summary["run_state_product_live_wallet_reservation_id"] == (
        "idem-m58-runner-wallet-reservation-btc_usdc"
    )
    assert summary["run_state_product_live_wallet_reserved_notional_usdc"] == "1.00"
    assert summary["run_state_product_live_wallet_debit_id"] == (
        "idem-m58-runner-wallet-debit-btc_usdc"
    )
    assert summary["run_state_product_live_wallet_debited_notional_usdc"] == "1.00"
    assert summary["run_state_product_live_wallet_release_id"] == (
        "idem-m58-runner-wallet-release-btc_usdc"
    )
    assert summary["run_state_product_live_wallet_released_notional_usdc"] == "1.00"
    assert summary["run_state_product_live_wallet_reservation_blockers"] == []
    assert summary["fanout_execution_status"] == "blocked"
    assert summary["fanout_blockers"] == [
        "fanout_execution_technically_blocked",
        "scheduler_blocked",
    ]
    assert summary["live_coinbase_execution"] == "submitted_cancelled"
    assert summary["submitted_notional_usdc"] == "1.00"
    assert summary["executed_notional_usdc"] == "0"
    assert summary["proof_chain_status_after_submission"] == "accepted"
    assert summary["proof_chain_blockers_after_submission"] == []

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
    assert (
        tmp_path
        / "state"
        / "admin_api_usdc_pair_snapshot_live_wallet_reservations.jsonl"
    ).exists()


def test_usdc_pair_snapshot_live_runner_records_fail_closed_fanout_boundary(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-admin-token")
    config = _config(
        tmp_path,
        attempt_live_fanout_from_run_state=True,
        allowlist_readiness_id="m58-runner-allowlist-readiness",
        run_state_id="m58-runner-run-state",
    )
    fake_fanout_executor = _FailingFanoutExecutor()

    summary = runner.run_usdc_pair_snapshot_live_submit(
        config,
        fanout_executor=fake_fanout_executor,
        require_runtime_ready=False,
        require_credentials=False,
    )

    assert summary["status"] == "passed"
    assert summary["live_submit_source"] == "allowlist_run_state_fanout"
    assert summary["live_submit_route_status"] == "rejected"
    assert summary["live_submit_failure_stage"] == (
        "usdc_pair_snapshot_allowlist_run_state_live_fanout_submit"
    )
    assert summary["fanout_submit_attempted"] is True
    assert summary["fanout_submit_expected_blocked"] is True
    assert summary["submission_count"] == 0
    assert summary["submissions"] == []
    assert summary["submission_id"] is None
    assert summary["submitted_notional_usdc"] is None
    assert summary["executed_notional_usdc"] is None
    assert summary["live_exchange_submitted"] is False
    assert summary["live_coinbase_orders_ran"] is False
    assert summary["live_coinbase_execution"] == "not_run"
    assert summary["notional_usdc"] == "0"
    assert "runtime_fanout_worker_missing" in summary["live_submit_message"]
    assert fake_fanout_executor.calls == []


def test_usdc_pair_snapshot_live_runner_scopes_default_recovery_ref_per_run(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-admin-token")
    summaries = []
    fake_executor = _FakeLiveExecutor()

    for suffix in ("first", "second"):
        prefix = f"idem-m58-runner-{suffix}"
        config = _config(
            tmp_path,
            submit_from_run_state=True,
            idempotency_prefix=prefix,
            run_id=f"m58-runner-snapshot-{suffix}",
            plan_id=f"m58-runner-plan-{suffix}",
            readiness_id=f"m58-runner-readiness-{suffix}",
            submission_id=f"m58-runner-submission-{suffix}",
            allowlist_readiness_id=f"m58-runner-allowlist-readiness-{suffix}",
            run_state_id=f"m58-runner-run-state-{suffix}",
            run_rate_limit_budget_ref=f"{prefix}-rate-limit-budget",
            run_lock_ref=f"{prefix}-run-lock",
            rate_limit_window_ref=f"{prefix}-rate-limit-window",
        )
        summaries.append(
            runner.run_usdc_pair_snapshot_live_submit(
                config,
                live_executor=fake_executor,
                require_runtime_ready=False,
                require_credentials=False,
            )
        )

    assert [summary["status"] for summary in summaries] == ["passed", "passed"]
    assert summaries[0]["cancel_rollback_plan_ref"] == (
        "idem-m58-runner-first-cancel-before-additional-orders"
    )
    assert summaries[1]["cancel_rollback_plan_ref"] == (
        "idem-m58-runner-second-cancel-before-additional-orders"
    )
    assert summaries[0]["allowlist_cancel_recovery_plan_ref"] == (
        summaries[0]["cancel_rollback_plan_ref"]
    )
    assert summaries[1]["allowlist_cancel_recovery_plan_ref"] == (
        summaries[1]["cancel_rollback_plan_ref"]
    )
    assert len(fake_executor.calls) == 2


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


def test_usdc_pair_snapshot_live_executor_records_immediate_filled_value(
    monkeypatch,
):
    from application.admin_api import usdc_pair_snapshot_live_execution as live_exec

    class FakeController:
        def track_inflight(self, _operation):
            return nullcontext()

    class FakeClient:
        def create_order(self, **_kwargs):
            return {
                "success": True,
                "success_response": {
                    "order_id": "exchange-order-filled",
                    "filled_value": "0.005",
                },
            }

        def cancel_order(self, _client_order_id):
            return True

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
        lambda: SimpleNamespace(available=True, client=FakeClient()),
    )
    monkeypatch.setattr(
        live_exec,
        "get_runtime_controller",
        lambda: FakeController(),
    )

    result = live_exec.UsdcPairSnapshotLiveOrderExecutor().submit_and_cancel(
        client_order_id="client-order-filled",
        product_id="BTC-USDC",
        side="BUY",
        order_configuration={
            "limit_limit_gtc": {
                "quote_size": "1.00",
                "limit_price": "31500.00",
                "post_only": False,
            }
        },
        submitted_notional_usdc="1.00",
        max_executed_notional_usdc="0.01",
        cancel_client_order_id="client-order-filled",
    )

    assert result["coinbase_order_id"] == "exchange-order-filled"
    assert result["cancel_submitted"] is True
    assert result["cancel_rollback_complete"] is False
    assert result["live_coinbase_execution"] == "submitted_cancel_failed"
    assert result["executed_notional_usdc"] == "0.005"


def test_usdc_pair_snapshot_live_fanout_executor_runs_sequential_submit_cancel():
    from application.admin_api import usdc_pair_snapshot_live_execution as live_exec

    class FakeOrderExecutor:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def submit_and_cancel(self, **kwargs):
            self.calls.append(dict(kwargs))
            return {
                "coinbase_order_id": f"exchange-{kwargs['client_order_id']}",
                "submit_result": {
                    "success": True,
                    "client_order_id": kwargs["client_order_id"],
                },
                "cancel_result": {
                    "success": True,
                    "client_order_id": kwargs["client_order_id"],
                },
                "submitted_at": "2026-07-09T10:00:00+00:00",
                "cancelled_at": "2026-07-09T10:00:01+00:00",
                "order_configuration": kwargs["order_configuration"],
                "live_exchange_submitted": True,
                "live_coinbase_orders_ran": True,
                "live_coinbase_execution": "submitted_cancelled",
                "submitted_notional_usdc": kwargs["submitted_notional_usdc"],
                "executed_notional_usdc": "0",
                "max_executed_notional_usdc": kwargs[
                    "max_executed_notional_usdc"
                ],
            }

    fake_order_executor = FakeOrderExecutor()
    executor = live_exec.UsdcPairSnapshotLiveFanoutExecutor(
        order_executor=fake_order_executor
    )

    result = executor.submit_and_cancel_all(
        orders=[
            {
                "client_order_id": "client-order-1",
                "product_id": "BTC-USDC",
                "side": "BUY",
                "order_configuration": {
                    "limit_limit_gtc": {
                        "quote_size": "1.00",
                        "limit_price": "31500.00",
                        "post_only": False,
                    },
                },
                "submitted_notional_usdc": "1.00",
                "max_executed_notional_usdc": "0.01",
                "cancel_client_order_id": "client-order-1",
            },
            {
                "client_order_id": "client-order-2",
                "product_id": "ETH-USDC",
                "side": "BUY",
                "order_configuration": {
                    "limit_limit_gtc": {
                        "quote_size": "1.50",
                        "limit_price": "1500.00",
                        "post_only": False,
                    },
                },
                "submitted_notional_usdc": "1.50",
                "max_executed_notional_usdc": "0.01",
                "cancel_client_order_id": "client-order-2",
            },
        ],
        max_orders_per_second=5,
    )

    assert [call["client_order_id"] for call in fake_order_executor.calls] == [
        "client-order-1",
        "client-order-2",
    ]
    assert result["requested_order_count"] == 2
    assert result["order_count"] == 2
    assert result["submitted_notional_usdc"] == "2.50"
    assert result["executed_notional_usdc"] == "0"
    assert result["cancel_submitted"] is True
    assert result["cancel_rollback_complete"] is True
    assert result["live_exchange_submitted"] is True
    assert result["live_coinbase_orders_ran"] is True
    assert result["live_coinbase_execution"] == "submitted_cancelled"
    assert [order["client_order_id"] for order in result["orders"]] == [
        "client-order-1",
        "client-order-2",
    ]


def test_usdc_pair_snapshot_live_fanout_executor_stops_after_cancel_failure():
    from application.admin_api import usdc_pair_snapshot_live_execution as live_exec

    class FakeOrderExecutor:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def submit_and_cancel(self, **kwargs):
            self.calls.append(dict(kwargs))
            return {
                "coinbase_order_id": f"exchange-{kwargs['client_order_id']}",
                "submit_result": {"success": True},
                "cancel_result": {"success": False},
                "order_configuration": kwargs["order_configuration"],
                "live_exchange_submitted": True,
                "live_coinbase_orders_ran": True,
                "live_coinbase_execution": "submitted_cancel_failed",
                "submitted_notional_usdc": kwargs["submitted_notional_usdc"],
                "executed_notional_usdc": "0",
                "max_executed_notional_usdc": kwargs[
                    "max_executed_notional_usdc"
                ],
                "cancel_submitted": False,
                "cancel_rollback_complete": False,
            }

    fake_order_executor = FakeOrderExecutor()
    executor = live_exec.UsdcPairSnapshotLiveFanoutExecutor(
        order_executor=fake_order_executor
    )

    result = executor.submit_and_cancel_all(
        orders=[
            {
                "client_order_id": "client-order-1",
                "product_id": "BTC-USDC",
                "side": "BUY",
                "order_configuration": _fanout_buy_order_configuration("1.00"),
                "submitted_notional_usdc": "1.00",
                "max_executed_notional_usdc": "0.01",
                "cancel_client_order_id": "client-order-1",
            },
            {
                "client_order_id": "client-order-2",
                "product_id": "ETH-USDC",
                "side": "BUY",
                "order_configuration": _fanout_buy_order_configuration("1.50"),
                "submitted_notional_usdc": "1.50",
                "max_executed_notional_usdc": "0.01",
                "cancel_client_order_id": "client-order-2",
            },
        ],
        max_orders_per_second=5,
    )

    assert [call["client_order_id"] for call in fake_order_executor.calls] == [
        "client-order-1"
    ]
    assert result["requested_order_count"] == 2
    assert result["order_count"] == 1
    assert result["submitted_notional_usdc"] == "1.00"
    assert result["cancel_submitted"] is False
    assert result["cancel_rollback_complete"] is False
    assert result["additional_orders_blocked"] is True
    assert result["live_coinbase_execution"] == "submitted_cancel_failed"


def test_usdc_pair_snapshot_live_fanout_executor_stops_after_any_execution():
    from application.admin_api import usdc_pair_snapshot_live_execution as live_exec

    class FakeOrderExecutor:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def submit_and_cancel(self, **kwargs):
            self.calls.append(dict(kwargs))
            return {
                "coinbase_order_id": f"exchange-{kwargs['client_order_id']}",
                "submit_result": {
                    "success": True,
                    "client_order_id": kwargs["client_order_id"],
                },
                "cancel_result": {
                    "success": True,
                    "client_order_id": kwargs["client_order_id"],
                },
                "order_configuration": kwargs["order_configuration"],
                "live_exchange_submitted": True,
                "live_coinbase_orders_ran": True,
                "live_coinbase_execution": "submitted_cancelled",
                "submitted_notional_usdc": kwargs["submitted_notional_usdc"],
                "executed_notional_usdc": "0.005",
                "max_executed_notional_usdc": kwargs[
                    "max_executed_notional_usdc"
                ],
                "cancel_submitted": True,
                "cancel_rollback_complete": True,
            }

    fake_order_executor = FakeOrderExecutor()
    executor = live_exec.UsdcPairSnapshotLiveFanoutExecutor(
        order_executor=fake_order_executor
    )

    result = executor.submit_and_cancel_all(
        orders=[
            {
                "client_order_id": "client-order-1",
                "product_id": "BTC-USDC",
                "side": "BUY",
                "order_configuration": _fanout_buy_order_configuration("1.00"),
                "submitted_notional_usdc": "1.00",
                "max_executed_notional_usdc": "0.01",
                "cancel_client_order_id": "client-order-1",
            },
            {
                "client_order_id": "client-order-2",
                "product_id": "ETH-USDC",
                "side": "BUY",
                "order_configuration": _fanout_buy_order_configuration("1.50"),
                "submitted_notional_usdc": "1.50",
                "max_executed_notional_usdc": "0.01",
                "cancel_client_order_id": "client-order-2",
            },
        ],
        max_orders_per_second=5,
    )

    assert [call["client_order_id"] for call in fake_order_executor.calls] == [
        "client-order-1"
    ]
    assert result["requested_order_count"] == 2
    assert result["order_count"] == 1
    assert result["submitted_notional_usdc"] == "1.00"
    assert result["executed_notional_usdc"] == "0.005"
    assert result["cancel_submitted"] is False
    assert result["cancel_rollback_complete"] is False
    assert result["additional_orders_blocked"] is True
    assert result["live_coinbase_execution"] == "submitted_cancel_failed"


def test_usdc_pair_snapshot_live_fanout_executor_stops_after_missing_execution_evidence():
    from application.admin_api import usdc_pair_snapshot_live_execution as live_exec

    class MissingExecutionEvidenceOrderExecutor:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def submit_and_cancel(self, **kwargs):
            self.calls.append(dict(kwargs))
            return {
                "coinbase_order_id": f"exchange-{kwargs['client_order_id']}",
                "client_order_id": kwargs["client_order_id"],
                "product_id": kwargs["product_id"],
                "side": kwargs["side"],
                "submit_result": {"success": True},
                "cancel_result": {"success": True},
                "cancel_submitted": True,
                "cancel_rollback_complete": True,
                "submitted_notional_usdc": kwargs["submitted_notional_usdc"],
                "max_executed_notional_usdc": kwargs[
                    "max_executed_notional_usdc"
                ],
                "live_exchange_submitted": True,
                "live_coinbase_orders_ran": True,
                "live_coinbase_execution": "submitted_cancelled",
            }

    fake_order_executor = MissingExecutionEvidenceOrderExecutor()
    executor = live_exec.UsdcPairSnapshotLiveFanoutExecutor(
        order_executor=fake_order_executor
    )

    result = executor.submit_and_cancel_all(
        orders=[
            {
                "client_order_id": "client-order-1",
                "product_id": "BTC-USDC",
                "side": "BUY",
                "order_configuration": _fanout_buy_order_configuration("1.00"),
                "submitted_notional_usdc": "1.00",
                "max_executed_notional_usdc": "0.01",
                "cancel_client_order_id": "client-order-1",
            },
            {
                "client_order_id": "client-order-2",
                "product_id": "ETH-USDC",
                "side": "BUY",
                "order_configuration": _fanout_buy_order_configuration("1.50"),
                "submitted_notional_usdc": "1.50",
                "max_executed_notional_usdc": "0.01",
                "cancel_client_order_id": "client-order-2",
            },
        ],
        max_orders_per_second=5,
    )

    assert [call["client_order_id"] for call in fake_order_executor.calls] == [
        "client-order-1"
    ]
    assert result["requested_order_count"] == 2
    assert result["order_count"] == 1
    assert result["submitted_notional_usdc"] == "1.00"
    assert result["executed_notional_usdc"] == "0"
    assert result["executed_notional_evidence_status"] == "missing_or_invalid"
    assert result["cancel_submitted"] is False
    assert result["cancel_rollback_complete"] is False
    assert result["additional_orders_blocked"] is True
    assert result["live_coinbase_execution"] == "submitted_cancel_failed"
    order = result["orders"][0]
    assert order["executed_notional_usdc"] == "0"
    assert order["executed_notional_evidence_status"] == "missing_or_invalid"
    assert order["cancel_submitted"] is True
    assert order["cancel_rollback_complete"] is False
    assert order["live_coinbase_execution"] == "submitted_cancel_failed"


def test_usdc_pair_snapshot_live_fanout_executor_rejects_mismatched_execution_evidence():
    from application.admin_api import usdc_pair_snapshot_live_execution as live_exec

    class FakeOrderExecutor:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def submit_and_cancel(self, **kwargs):
            self.calls.append(dict(kwargs))
            return {
                "client_order_id": "wrong-client-order-id",
                "product_id": "ETH-USDC",
                "side": kwargs["side"],
                "coinbase_order_id": "exchange-wrong-client-order-id",
                "submit_result": {"success": True},
                "cancel_result": {"success": True},
                "order_configuration": kwargs["order_configuration"],
                "live_exchange_submitted": True,
                "live_coinbase_orders_ran": True,
                "live_coinbase_execution": "submitted_cancelled",
                "submitted_notional_usdc": kwargs["submitted_notional_usdc"],
                "executed_notional_usdc": "0",
                "max_executed_notional_usdc": kwargs[
                    "max_executed_notional_usdc"
                ],
                "cancel_submitted": True,
                "cancel_rollback_complete": True,
            }

    fake_order_executor = FakeOrderExecutor()
    executor = live_exec.UsdcPairSnapshotLiveFanoutExecutor(
        order_executor=fake_order_executor
    )

    with pytest.raises(
        live_exec.UsdcPairSnapshotLiveExecutionError,
        match="mismatched execution evidence",
    ):
        executor.submit_and_cancel_all(
            orders=[
                {
                    "client_order_id": "client-order-1",
                    "product_id": "BTC-USDC",
                    "side": "BUY",
                    "order_configuration": _fanout_buy_order_configuration("1.00"),
                    "submitted_notional_usdc": "1.00",
                    "max_executed_notional_usdc": "0.01",
                    "cancel_client_order_id": "client-order-1",
                },
                {
                    "client_order_id": "client-order-2",
                    "product_id": "ETH-USDC",
                    "side": "BUY",
                    "order_configuration": _fanout_buy_order_configuration("1.50"),
                    "submitted_notional_usdc": "1.50",
                    "max_executed_notional_usdc": "0.01",
                    "cancel_client_order_id": "client-order-2",
                },
            ],
            max_orders_per_second=5,
        )

    assert [call["client_order_id"] for call in fake_order_executor.calls] == [
        "client-order-1"
    ]


def test_usdc_pair_snapshot_live_fanout_executor_enforces_order_rate_cap():
    from application.admin_api import usdc_pair_snapshot_live_execution as live_exec

    class FakeOrderExecutor:
        def submit_and_cancel(self, **_kwargs):
            raise AssertionError("fan-out executor must fail before submission")

    executor = live_exec.UsdcPairSnapshotLiveFanoutExecutor(
        order_executor=FakeOrderExecutor()
    )
    orders = [
        {
            "client_order_id": f"client-order-{index}",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "order_configuration": _fanout_buy_order_configuration("1.00"),
            "submitted_notional_usdc": "1.00",
            "max_executed_notional_usdc": "0.01",
            "cancel_client_order_id": f"client-order-{index}",
        }
        for index in range(6)
    ]

    with pytest.raises(
        live_exec.UsdcPairSnapshotLiveExecutionError,
        match="5 orders per second",
    ):
        executor.submit_and_cancel_all(orders=orders, max_orders_per_second=5)


def test_usdc_pair_snapshot_live_fanout_executor_enforces_total_notional_cap():
    from application.admin_api import usdc_pair_snapshot_live_execution as live_exec

    class FakeOrderExecutor:
        def submit_and_cancel(self, **_kwargs):
            raise AssertionError("fan-out executor must fail before submission")

    executor = live_exec.UsdcPairSnapshotLiveFanoutExecutor(
        order_executor=FakeOrderExecutor()
    )

    with pytest.raises(
        live_exec.UsdcPairSnapshotLiveExecutionError,
        match="maximum fan-out notional",
    ):
        executor.submit_and_cancel_all(
            orders=[
                {
                    "client_order_id": "client-order-1",
                    "product_id": "BTC-USDC",
                    "side": "BUY",
                    "order_configuration": _fanout_buy_order_configuration("60.00"),
                    "submitted_notional_usdc": "60.00",
                    "max_executed_notional_usdc": "0.01",
                    "cancel_client_order_id": "client-order-1",
                },
                {
                    "client_order_id": "client-order-2",
                    "product_id": "ETH-USDC",
                    "side": "BUY",
                    "order_configuration": _fanout_buy_order_configuration("40.01"),
                    "submitted_notional_usdc": "40.01",
                    "max_executed_notional_usdc": "0.01",
                    "cancel_client_order_id": "client-order-2",
                },
            ],
            max_orders_per_second=5,
        )


def test_usdc_pair_snapshot_live_fanout_executor_requires_quote_size_match():
    from application.admin_api import usdc_pair_snapshot_live_execution as live_exec

    class FakeOrderExecutor:
        def submit_and_cancel(self, **_kwargs):
            raise AssertionError("fan-out executor must fail before submission")

    executor = live_exec.UsdcPairSnapshotLiveFanoutExecutor(
        order_executor=FakeOrderExecutor()
    )

    with pytest.raises(
        live_exec.UsdcPairSnapshotLiveExecutionError,
        match="quote_size must match submitted notional",
    ):
        executor.submit_and_cancel_all(
            orders=[
                {
                    "client_order_id": "client-order-mismatch",
                    "product_id": "BTC-USDC",
                    "side": "BUY",
                    "order_configuration": _fanout_buy_order_configuration("1.01"),
                    "submitted_notional_usdc": "1.00",
                    "max_executed_notional_usdc": "0.01",
                    "cancel_client_order_id": "client-order-mismatch",
                },
            ],
            max_orders_per_second=5,
        )


def test_usdc_pair_snapshot_live_fanout_executor_requires_explicit_limit_shape():
    from application.admin_api import usdc_pair_snapshot_live_execution as live_exec

    class FakeOrderExecutor:
        def submit_and_cancel(self, **_kwargs):
            raise AssertionError("fan-out executor must fail before submission")

    executor = live_exec.UsdcPairSnapshotLiveFanoutExecutor(
        order_executor=FakeOrderExecutor()
    )

    with pytest.raises(
        live_exec.UsdcPairSnapshotLiveExecutionError,
        match="requires limit_price evidence",
    ):
        executor.submit_and_cancel_all(
            orders=[
                {
                    "client_order_id": "client-order-missing-limit-price",
                    "product_id": "BTC-USDC",
                    "side": "BUY",
                    "order_configuration": {
                        "limit_limit_gtc": {
                            "quote_size": "1.00",
                            "post_only": False,
                        }
                    },
                    "submitted_notional_usdc": "1.00",
                    "max_executed_notional_usdc": "0.01",
                    "cancel_client_order_id": (
                        "client-order-missing-limit-price"
                    ),
                },
            ],
            max_orders_per_second=5,
        )

    with pytest.raises(
        live_exec.UsdcPairSnapshotLiveExecutionError,
        match="requires explicit post_only false evidence",
    ):
        executor.submit_and_cancel_all(
            orders=[
                {
                    "client_order_id": "client-order-post-only",
                    "product_id": "BTC-USDC",
                    "side": "BUY",
                    "order_configuration": {
                        "limit_limit_gtc": {
                            "quote_size": "1.00",
                            "limit_price": "31500.00",
                            "post_only": True,
                        }
                    },
                    "submitted_notional_usdc": "1.00",
                    "max_executed_notional_usdc": "0.01",
                    "cancel_client_order_id": "client-order-post-only",
                },
            ],
            max_orders_per_second=5,
        )


def test_usdc_pair_snapshot_live_fanout_executor_rejects_unproved_scope_shape():
    from application.admin_api import usdc_pair_snapshot_live_execution as live_exec

    class FakeOrderExecutor:
        def submit_and_cancel(self, **_kwargs):
            raise AssertionError("fan-out executor must fail before submission")

    executor = live_exec.UsdcPairSnapshotLiveFanoutExecutor(
        order_executor=FakeOrderExecutor()
    )

    with pytest.raises(
        live_exec.UsdcPairSnapshotLiveExecutionError,
        match="only supports BUY side",
    ):
        executor.submit_and_cancel_all(
            orders=[
                {
                    "client_order_id": "client-order-sell",
                    "product_id": "BTC-USDC",
                    "side": "SELL",
                    "order_configuration": {
                        "limit_limit_gtc": {
                            "base_size": "0.01",
                            "limit_price": "94500.00",
                            "post_only": False,
                        }
                    },
                    "submitted_notional_usdc": "1.00",
                    "max_executed_notional_usdc": "0.01",
                    "cancel_client_order_id": "client-order-sell",
                },
            ],
            max_orders_per_second=5,
        )

    with pytest.raises(
        live_exec.UsdcPairSnapshotLiveExecutionError,
        match="requires a USDC spot product_id",
    ):
        executor.submit_and_cancel_all(
            orders=[
                {
                    "client_order_id": "client-order-usd-product",
                    "product_id": "BTC-USD",
                    "side": "BUY",
                    "order_configuration": {
                        "limit_limit_gtc": {
                            "quote_size": "1.00",
                            "limit_price": "31500.00",
                            "post_only": False,
                        }
                    },
                    "submitted_notional_usdc": "1.00",
                    "max_executed_notional_usdc": "0.01",
                    "cancel_client_order_id": "client-order-usd-product",
                },
            ],
            max_orders_per_second=5,
        )


def test_usdc_pair_snapshot_live_fanout_executor_requires_notional_evidence():
    from application.admin_api import usdc_pair_snapshot_live_execution as live_exec

    class FakeOrderExecutor:
        def submit_and_cancel(self, **_kwargs):
            raise AssertionError("fan-out executor must fail before submission")

    executor = live_exec.UsdcPairSnapshotLiveFanoutExecutor(
        order_executor=FakeOrderExecutor()
    )

    with pytest.raises(
        live_exec.UsdcPairSnapshotLiveExecutionError,
        match="requires positive submitted fan-out notional evidence",
    ):
        executor.submit_and_cancel_all(
            orders=[
                {
                    "client_order_id": "client-order-zero-notional",
                    "product_id": "BTC-USDC",
                    "side": "BUY",
                    "order_configuration": _fanout_buy_order_configuration("0"),
                    "submitted_notional_usdc": "0",
                    "max_executed_notional_usdc": "0.01",
                    "cancel_client_order_id": "client-order-zero-notional",
                },
            ],
            max_orders_per_second=5,
        )


def test_usdc_pair_snapshot_live_fanout_executor_rejects_duplicate_order_identity():
    from application.admin_api import usdc_pair_snapshot_live_execution as live_exec

    class FakeOrderExecutor:
        def submit_and_cancel(self, **_kwargs):
            raise AssertionError("fan-out executor must fail before submission")

    executor = live_exec.UsdcPairSnapshotLiveFanoutExecutor(
        order_executor=FakeOrderExecutor()
    )

    with pytest.raises(
        live_exec.UsdcPairSnapshotLiveExecutionError,
        match="duplicate client_order_id",
    ):
        executor.submit_and_cancel_all(
            orders=[
                {
                    "client_order_id": "client-order-duplicate",
                    "product_id": "BTC-USDC",
                    "side": "BUY",
                    "order_configuration": _fanout_buy_order_configuration("1.00"),
                    "submitted_notional_usdc": "1.00",
                    "max_executed_notional_usdc": "0.01",
                    "cancel_client_order_id": "client-order-duplicate",
                },
                {
                    "client_order_id": "client-order-duplicate",
                    "product_id": "ETH-USDC",
                    "side": "BUY",
                    "order_configuration": _fanout_buy_order_configuration("1.50"),
                    "submitted_notional_usdc": "1.50",
                    "max_executed_notional_usdc": "0.01",
                    "cancel_client_order_id": "client-order-duplicate",
                },
            ],
            max_orders_per_second=5,
        )

    with pytest.raises(
        live_exec.UsdcPairSnapshotLiveExecutionError,
        match="duplicate product_id",
    ):
        executor.submit_and_cancel_all(
            orders=[
                {
                    "client_order_id": "client-order-1",
                    "product_id": "BTC-USDC",
                    "side": "BUY",
                    "order_configuration": _fanout_buy_order_configuration("1.00"),
                    "submitted_notional_usdc": "1.00",
                    "max_executed_notional_usdc": "0.01",
                    "cancel_client_order_id": "client-order-1",
                },
                {
                    "client_order_id": "client-order-2",
                    "product_id": "btc-usdc",
                    "side": "BUY",
                    "order_configuration": _fanout_buy_order_configuration("1.50"),
                    "submitted_notional_usdc": "1.50",
                    "max_executed_notional_usdc": "0.01",
                    "cancel_client_order_id": "client-order-2",
                },
            ],
            max_orders_per_second=5,
        )

    with pytest.raises(
        live_exec.UsdcPairSnapshotLiveExecutionError,
        match="max executed fan-out notional cannot exceed submitted",
    ):
        executor.submit_and_cancel_all(
            orders=[
                {
                    "client_order_id": "client-order-max-exceeds-submitted",
                    "product_id": "BTC-USDC",
                    "side": "BUY",
                    "order_configuration": _fanout_buy_order_configuration("1.00"),
                    "submitted_notional_usdc": "1.00",
                    "max_executed_notional_usdc": "1.01",
                    "cancel_client_order_id": (
                        "client-order-max-exceeds-submitted"
                    ),
                },
            ],
            max_orders_per_second=5,
        )

    with pytest.raises(
        live_exec.UsdcPairSnapshotLiveExecutionError,
        match="requires valid max executed fan-out notional evidence",
    ):
        executor.submit_and_cancel_all(
            orders=[
                {
                    "client_order_id": "client-order-invalid-max-executed",
                    "product_id": "BTC-USDC",
                    "side": "BUY",
                    "order_configuration": _fanout_buy_order_configuration("1.00"),
                    "submitted_notional_usdc": "1.00",
                    "max_executed_notional_usdc": "not-a-decimal",
                    "cancel_client_order_id": (
                        "client-order-invalid-max-executed"
                    ),
                },
            ],
            max_orders_per_second=5,
        )
