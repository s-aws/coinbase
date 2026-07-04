from __future__ import annotations

import json
from types import SimpleNamespace

from tools import run_admin_api_futures_executor_boundary_smoke as smoke


def result(body: dict, status_code: int = 200) -> SimpleNamespace:
    return SimpleNamespace(status_code=status_code, body=body)


def ready_command_suite() -> dict:
    return {
        "type": "admin_futures_command_suite",
        "status": "evidence_ready",
        "command_routes_mode": "backend_admin_api_draft_only",
        "resolved_backend_contracts": [
            "futures_account_scope_contract",
            "futures_margin_collateral_risk_proof",
            "futures_reconciliation_contract",
            "futures_live_adapter_contract",
        ],
        "missing_backend_contracts": [],
        "futures_risk_proof_count": 4,
        "blocked_command_count": 4,
        "executable_command_count": 0,
        "futures_live_decision_evidence": {
            "service_decision_status": "ready",
            "matching_service_decision_id": "futures-us-cfm-live-service",
            "adapter_decision_ready_count": 4,
            "adapter_decision_missing_count": 0,
            "all_command_adapters_ready": True,
            "executor_boundary_status": "observed_live_disabled",
            "executor_boundary_ready": True,
            "first_blocker": "futures_executor_live_disabled",
            "live_coinbase_orders_ran": False,
        },
        "live_coinbase_orders_ran": False,
    }


def executor_rejected_command() -> dict:
    return {
        "type": "admin_api_command_result",
        "status": "rejected",
        "failure_stage": "futures_executor_live_disabled",
        "executor_decision_id": "futures-executor-futures-executor-boundary-place-draft",
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
    }


def confirmed_runtime_disabled_command() -> dict:
    return {
        "type": "admin_api_command_result",
        "status": "rejected",
        "failure_stage": "futures_live_runtime_disabled",
        "submission_event_id": "futures-executor-futures-executor-boundary-confirmed-place",
        "submitted_notional_usdc": "0",
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
    }


def confirmed_cancel_runtime_disabled_command() -> dict:
    return {
        "type": "admin_api_command_result",
        "status": "rejected",
        "command": "futures_cancel",
        "mutation_family": "futures_live_cancel",
        "failure_stage": "futures_live_runtime_disabled",
        "submission_event_id": "futures-executor-futures-executor-boundary-confirmed-cancel",
        "client_order_id": smoke.FUTURES_CANCEL_CLIENT_ORDER_ID,
        "submitted_notional_usdc": "0",
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
    }


def reconciliation_execution_boundary_command() -> dict:
    return {
        "type": "admin_api_command_result",
        "status": "not_implemented",
        "command": "futures_reconcile",
        "mutation_family": "futures_reconciliation_execution_boundary",
        "failure_stage": "futures_reconciliation_execution_disabled",
        "submission_event_id": "futures-executor-boundary-reconciliation",
        "futures_reconciliation_execution_boundary_id": (
            "futures-executor-boundary-reconciliation"
        ),
        "identity_key": "position_key",
        "identity_value": smoke.FUTURES_RECONCILIATION_POSITION_KEY,
        "reconciliation_execution_allowed": False,
        "reconciliation_execution_ran": False,
        "reconciliation_plan_required": True,
        "local_state_mutated": False,
        "exchange_state_mutated": False,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
    }


def audit_workbench() -> dict:
    return {
        "type": "admin_audit_workbench",
        "count": 3,
        "events": [
            {
                "event_id": "futures-executor-futures-executor-boundary-place-draft",
                "module": "futures_perpetuals",
                "source": "admin_api_futures_executor_boundary",
                "status": "rejected",
                "live_exchange_submitted": False,
            },
            {
                "event_id": "futures-executor-futures-executor-boundary-confirmed-place",
                "module": "futures_perpetuals",
                "source": "admin_api_futures_command_log",
                "status": "rejected",
                "live_exchange_submitted": False,
            },
            {
                "event_id": "futures-executor-futures-executor-boundary-confirmed-cancel",
                "module": "futures_perpetuals",
                "source": "admin_api_futures_command_log",
                "status": "rejected",
                "live_exchange_submitted": False,
            }
        ],
    }


def smoke_config(tmp_path) -> smoke.FuturesBoundarySmokeConfig:
    return smoke.FuturesBoundarySmokeConfig(
        state_dir=tmp_path / "state",
        summary_output=tmp_path / "futures-boundary.json",
        backend_contract_ref="abc1234",
    )


def test_futures_executor_boundary_smoke_writes_no_live_summary(tmp_path):
    summary = smoke.build_summary(
        config=smoke_config(tmp_path),
        started_at="2026-07-04T00:00:00Z",
        duration_seconds=1.234,
        live_service=result({"status": "accepted"}),
        adapters=[result({"status": "accepted"}) for _ in smoke.FUTURES_ADAPTER_DECISIONS],
        command_suite=ready_command_suite(),
        command_result=executor_rejected_command(),
        command_status_code=400,
        confirmed_command_result=confirmed_runtime_disabled_command(),
        confirmed_command_status_code=400,
        confirmed_cancel_command_result=confirmed_cancel_runtime_disabled_command(),
        confirmed_cancel_command_status_code=400,
        reconciliation_command_result=reconciliation_execution_boundary_command(),
        reconciliation_command_status_code=501,
        audit_workbench=audit_workbench(),
    )

    assert summary["artifact_type"] == smoke.ARTIFACT_TYPE
    assert summary["status"] == "passed"
    assert summary["live_coinbase_execution"] == "not_run"
    assert summary["notional_usdc"] == "0"
    assert summary["executor_boundary_status"] == "observed_live_disabled"
    assert summary["executor_boundary_ready"] is True
    assert summary["first_blocker"] == "futures_executor_live_disabled"
    assert summary["command_status"] == "rejected"
    assert summary["command_status_code"] == 400
    assert summary["confirmed_command_status"] == "rejected"
    assert summary["confirmed_command_status_code"] == 400
    assert summary["confirmed_failure_stage"] == "futures_live_runtime_disabled"
    assert summary["confirmed_live_exchange_submitted"] is False
    assert summary["confirmed_live_coinbase_orders_ran"] is False
    assert summary["confirmed_cancel_command_status"] == "rejected"
    assert summary["confirmed_cancel_command_status_code"] == 400
    assert summary["confirmed_cancel_failure_stage"] == "futures_live_runtime_disabled"
    assert summary["confirmed_cancel_client_order_id"] == smoke.FUTURES_CANCEL_CLIENT_ORDER_ID
    assert summary["confirmed_cancel_live_exchange_submitted"] is False
    assert summary["confirmed_cancel_live_coinbase_orders_ran"] is False
    assert summary["reconciliation_command_status"] == "not_implemented"
    assert summary["reconciliation_command_status_code"] == 501
    assert summary["reconciliation_failure_stage"] == (
        "futures_reconciliation_execution_disabled"
    )
    assert summary["reconciliation_position_key"] == smoke.FUTURES_RECONCILIATION_POSITION_KEY
    assert summary["reconciliation_execution_allowed"] is False
    assert summary["reconciliation_execution_ran"] is False
    assert summary["reconciliation_live_exchange_submitted"] is False
    assert summary["reconciliation_live_coinbase_orders_ran"] is False
    assert summary["live_coinbase_orders_ran"] is False
    assert all(check["passed"] for check in summary["checks"])
    assert {
        "futures_confirmed_place_rejected_before_coinbase",
        "futures_confirmed_place_event_recorded",
        "futures_confirmed_cancel_rejected_before_coinbase",
        "futures_confirmed_cancel_event_recorded",
        "futures_reconciliation_execution_boundary_recorded",
        "futures_reconciliation_execution_not_run",
    }.issubset({check["name"] for check in summary["checks"]})


def test_futures_executor_boundary_smoke_fails_without_ready_adapter(tmp_path):
    command_suite = ready_command_suite()
    command_suite["futures_live_decision_evidence"] = {
        **command_suite["futures_live_decision_evidence"],
        "adapter_decision_ready_count": 3,
        "adapter_decision_missing_count": 1,
        "all_command_adapters_ready": False,
        "executor_boundary_status": "pending_live_decision",
        "executor_boundary_ready": False,
        "first_blocker": "execution_disabled",
    }

    summary = smoke.build_summary(
        config=smoke_config(tmp_path),
        started_at="2026-07-04T00:00:00Z",
        duration_seconds=1,
        live_service=result({"status": "accepted"}),
        adapters=[result({"status": "accepted"}) for _ in smoke.FUTURES_ADAPTER_DECISIONS],
        command_suite=command_suite,
        command_result=executor_rejected_command(),
        command_status_code=400,
        confirmed_command_result=confirmed_runtime_disabled_command(),
        confirmed_command_status_code=400,
        confirmed_cancel_command_result=confirmed_cancel_runtime_disabled_command(),
        confirmed_cancel_command_status_code=400,
        reconciliation_command_result=reconciliation_execution_boundary_command(),
        reconciliation_command_status_code=501,
        audit_workbench=audit_workbench(),
    )

    failed = {check["name"] for check in summary["checks"] if not check["passed"]}
    assert summary["status"] == "failed"
    assert "futures_all_adapters_ready" in failed
    assert "futures_executor_boundary_ready" in failed
    assert "futures_executor_disabled_blocker" in failed


def test_futures_executor_boundary_smoke_disables_inherited_live_runtime(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("COINBASE_ADMIN_API_LIVE_COINBASE_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("COINBASE_ADMIN_LIVE_COINBASE_EXECUTION", "true")
    monkeypatch.setattr(
        smoke.run_admin_api,
        "apply_local_environment",
        lambda args: {"truststore": "enabled"},
    )
    monkeypatch.setattr(
        smoke,
        "apply_manual_live_submit_state_environment",
        lambda state_dir: {"state_dir": str(state_dir)},
    )

    applied = smoke.apply_runner_environment(smoke_config(tmp_path))

    assert "COINBASE_ADMIN_API_LIVE_COINBASE_EXECUTION_ENABLED" not in smoke.os.environ
    assert "COINBASE_ADMIN_LIVE_COINBASE_EXECUTION" not in smoke.os.environ
    assert applied["COINBASE_ADMIN_API_LIVE_COINBASE_EXECUTION_ENABLED"] == "disabled"


def test_futures_executor_boundary_smoke_main_writes_artifact(monkeypatch, tmp_path):
    class FakeService:
        def record_live_service_decision(self, body, context):
            return result({"decision": {"decision_id": body["decision_id"]}})

        def record_live_adapter_decision(self, body, context):
            return result({"decision": {"decision_id": body["decision_id"]}})

        def get_read_response(self, route, query, context):
            if route == "/api/v1/futures/command-suite":
                return result(ready_command_suite())
            if route == "/api/v1/admin/audit-workbench":
                return result(audit_workbench())
            raise AssertionError(f"unexpected route: {route}")

        def submit_futures_command(self, path, body, context):
            if path == smoke.FUTURES_CANCEL_COMMAND_ROUTE:
                assert body["product_id"] == smoke.FUTURES_PRODUCT_ID
                assert context.idempotency_key == "futures-executor-boundary-confirmed-cancel"
                assert body["manual_live_acknowledgement"] is True
                assert body.get("order_id") is None
                return result(confirmed_cancel_runtime_disabled_command(), status_code=400)
            if path == smoke.FUTURES_RECONCILIATION_COMMAND_ROUTE:
                assert context.idempotency_key == "futures-executor-boundary-reconciliation"
                assert body["manual_live_acknowledgement"] is True
                assert body["reconciliation_reason"] == "executor_boundary_reconciliation_review"
                return result(reconciliation_execution_boundary_command(), status_code=501)
            assert path == smoke.FUTURES_COMMAND_ROUTE
            assert body["product_id"] == smoke.FUTURES_PRODUCT_ID
            if body.get("dry_run") is False:
                assert body["manual_live_acknowledgement"] is True
                return result(confirmed_runtime_disabled_command(), status_code=400)
            return result(executor_rejected_command(), status_code=400)

    monkeypatch.setattr(smoke, "get_admin_mvp_service", lambda: FakeService())
    monkeypatch.setattr(smoke, "apply_runner_environment", lambda config: {})
    monkeypatch.setattr(
        smoke,
        "read_git_value",
        lambda args, fallback="unknown": {
            ("rev-parse", "--short", "HEAD"): "abc1234",
            ("rev-parse", "--abbrev-ref", "HEAD"): "codex/account-futures-mvp-local-cd",
        }.get(tuple(args), fallback),
    )
    summary_path = tmp_path / "futures-boundary.json"

    exit_code = smoke.main(
        [
            "--summary-output",
            str(summary_path),
            "--state-dir",
            str(tmp_path / "state"),
            "--backend-contract-ref",
            "abc1234",
        ]
    )

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert summary["status"] == "passed"
    assert summary["backend_contract_ref"] == "abc1234"
    assert summary["backend_git_commit"] == "abc1234"
    assert summary["backend_git_branch"] == "codex/account-futures-mvp-local-cd"
    assert summary["confirmed_failure_stage"] == "futures_live_runtime_disabled"
    assert summary["confirmed_cancel_failure_stage"] == "futures_live_runtime_disabled"
    assert summary["confirmed_cancel_client_order_id"] == smoke.FUTURES_CANCEL_CLIENT_ORDER_ID
    assert summary["reconciliation_failure_stage"] == (
        "futures_reconciliation_execution_disabled"
    )
