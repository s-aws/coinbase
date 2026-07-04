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


def audit_workbench() -> dict:
    return {
        "type": "admin_audit_workbench",
        "count": 2,
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
    assert summary["live_coinbase_orders_ran"] is False
    assert all(check["passed"] for check in summary["checks"])
    assert {
        "futures_confirmed_place_rejected_before_coinbase",
        "futures_confirmed_place_event_recorded",
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
        audit_workbench=audit_workbench(),
    )

    failed = {check["name"] for check in summary["checks"] if not check["passed"]}
    assert summary["status"] == "failed"
    assert "futures_all_adapters_ready" in failed
    assert "futures_executor_boundary_ready" in failed
    assert "futures_executor_disabled_blocker" in failed


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
