from __future__ import annotations

import json
from types import SimpleNamespace

from tools import run_admin_api_account_reality_live_read_smoke as smoke


def result(body: dict, status_code: int = 200) -> SimpleNamespace:
    return SimpleNamespace(status_code=status_code, body=body)


def ready_read_results() -> dict[str, SimpleNamespace]:
    readiness = {
        "spot_account_ready": True,
        "spot_wallet_inventory_ready": True,
        "futures_account_scope_ready": True,
        "futures_observed_position_scope_ready": True,
        "futures_margin_collateral_ready": True,
        "usable_for_spot_admission": True,
        "usable_for_futures_risk": True,
    }
    return {
        "wallet": result(
            {
                "type": "admin_wallet",
                "status": "ready",
                "account_reality": {"status": "ready"},
                "readiness": readiness,
                "futures_risk_input": {
                    "status": "ready",
                    "currency": "USD",
                    "available_notional_usdc": "250.00",
                },
                "live_coinbase_orders_ran": False,
            }
        ),
        "futures_account": result(
            {
                "type": "admin_futures_account",
                "account_readiness": readiness,
                "collateral": {"status": "ready", "source": "backend_rest_client"},
                "margin": {"status": "ready", "source": "backend_rest_client"},
                "funding": {
                    "status": "ready",
                    "source": "backend_rest_client",
                    "value": {
                        "funding_applicability": "not_applicable_us_cfm",
                        "funding_required": False,
                        "intx_applicability": "not_applicable_us_account",
                    },
                },
                "liquidation": {
                    "status": "ready",
                    "source": "backend_rest_client",
                    "value": {
                        "liquidation_threshold_present": True,
                        "liquidation_buffer_present": True,
                    },
                },
                "reduce_only_close_only": {
                    "status": "ready",
                    "source": "runtime_positions",
                    "value": {
                        "position_side_observed_count": 1,
                        "backend_derives_close_reduce_side": True,
                    },
                },
                "command_routes_mode": "backend_admin_api_draft_only",
                "live_coinbase_orders_ran": False,
            }
        ),
        "futures_positions": result(
            {
                "type": "admin_futures_positions",
                "count": 1,
                "items": [
                    {
                        "position_key": "futures_position:runtime:BIP-20DEC30-CDE",
                        "product_id": "BIP-20DEC30-CDE",
                        "position_side": "LONG",
                        "number_of_contracts": "1",
                        "current_price": "123.45",
                        "entry_price": "100.00",
                        "raw_position": {"sensitive": "raw"},
                        "source": "runtime_positions",
                    }
                ],
                "read_only": True,
                "command_routes_mode": "backend_admin_api_blocked",
                "live_coinbase_orders_ran": False,
            }
        ),
        "futures_risk_proofs": result(
            {
                "type": "admin_futures_risk_proofs",
                "status": "ready",
                "count": 4,
                "proof_records_created": False,
                "proof_records_generated_from_account_snapshot": True,
                "command_routes_mode": "backend_admin_api_draft_only",
                "live_coinbase_orders_ran": False,
            }
        ),
        "futures_command_suite": result(
            {
                "type": "admin_futures_command_suite",
                "status": "evidence_ready",
                "command_routes_mode": "backend_admin_api_confirmed_live",
                "resolved_backend_contracts": [
                    "futures_account_scope_contract",
                    "futures_margin_collateral_risk_proof",
                    "futures_reconciliation_contract",
                    "futures_live_adapter_contract",
                ],
                "missing_backend_contracts": [],
                "futures_risk_proof_count": 4,
                "blocked_command_count": 1,
                "executable_command_count": 3,
                "futures_live_decision_evidence": {
                    "service_decision_status": "ready",
                    "adapter_decision_ready_count": 4,
                    "adapter_decision_missing_count": 0,
                    "executor_boundary_status": "live_enabled",
                    "first_blocker": None,
                },
                "futures_product_exposure_evidence": {
                    "status": "ready",
                    "max_submitted_notional_usdc": "100.00",
                    "product_count": 2,
                    "product_within_backend_cap_count": 1,
                    "any_product_within_backend_cap": True,
                    "next_required_operator_decision": (
                        "select_configured_us_cfm_product_within_cap"
                    ),
                    "items": [
                        {
                            "product_id": "AVP-20DEC30-CDE",
                            "status": "ready",
                            "metadata_read_status": "ready",
                            "minimum_contract_notional_usdc": "68.40",
                            "minimum_contract_notional_source": (
                                "backend_product_metadata"
                            ),
                            "within_backend_cap": True,
                        },
                        {
                            "product_id": "BIP-20DEC30-CDE",
                            "status": "blocked",
                            "metadata_read_status": "ready",
                            "minimum_contract_notional_usdc": "625.00",
                            "minimum_contract_notional_source": (
                                "backend_product_metadata"
                            ),
                            "within_backend_cap": False,
                        },
                    ],
                },
                "submitted_notional_usdc": "0",
                "executed_notional_usdc": "0",
                "live_coinbase_orders_ran": False,
            }
        ),
    }


def test_account_reality_live_read_smoke_writes_redacted_ready_summary(tmp_path):
    summary = smoke.build_smoke_summary(
        read_results=ready_read_results(),
        applied_environment={smoke.run_admin_api.OS_TRUSTSTORE_ENV: "enabled"},
        started_at="2026-07-03T20:00:00Z",
        ended_at="2026-07-03T20:00:01Z",
        duration_seconds=1.2345,
        backend_git_commit="abc1234",
        backend_git_branch="codex/account-futures-mvp-local-cd",
        backend_contract_ref="abc1234",
        environ={"COINBASE_API_KEY": "present", "COINBASE_API_SECRET": "present"},
    )

    assert summary["artifact_type"] == "coinbase_admin_api_account_reality_live_read_smoke"
    assert summary["status"] == "passed"
    assert summary["truststore_status"] == "enabled"
    assert summary["credentials_present"] is True
    assert summary["live_coinbase_execution"] == "not_run"
    assert summary["notional_usdc"] == "0"
    assert summary["wallet"]["futures_available_notional_present"] is True
    assert summary["futures_account"]["funding_status"] == "ready"
    assert summary["futures_account"]["funding_applicability"] == "not_applicable_us_cfm"
    assert summary["futures_account"]["funding_required"] is False
    assert summary["futures_account"]["liquidation_status"] == "ready"
    assert summary["futures_account"]["liquidation_threshold_present"] is True
    assert summary["futures_account"]["liquidation_buffer_present"] is True
    assert summary["futures_account"]["reduce_only_close_only_status"] == "ready"
    assert summary["futures_account"]["position_side_observed_count"] == 1
    assert summary["futures_positions"]["count"] == 1
    assert summary["futures_positions"]["position_scope_present"] is True
    assert summary["futures_positions"]["position_side_present"] is True
    assert (
        summary["futures_command_suite"]["command_routes_mode"]
        == "backend_admin_api_confirmed_live"
    )
    assert summary["futures_command_suite"]["executable_command_count"] == 3
    assert (
        summary["futures_command_suite"]["product_exposure"][
            "any_product_within_backend_cap"
        ]
        is True
    )
    assert "available_notional_usdc" not in json.dumps(summary)
    assert "250.00" not in json.dumps(summary)
    assert "number_of_contracts" not in json.dumps(summary)
    assert "123.45" not in json.dumps(summary)
    assert "raw_position" not in json.dumps(summary)
    assert all(check["passed"] for check in summary["checks"])


def test_account_reality_live_read_smoke_fails_when_futures_risk_is_blocked():
    read_results = ready_read_results()
    read_results["wallet"].body["readiness"]["futures_margin_collateral_ready"] = False
    read_results["wallet"].body["readiness"]["futures_observed_position_scope_ready"] = False
    read_results["wallet"].body["readiness"]["usable_for_futures_risk"] = False
    read_results["wallet"].body["futures_risk_input"] = {
        "status": "blocked",
        "currency": "USD",
        "available_notional_usdc": "0",
    }
    read_results["futures_account"].body["collateral"]["status"] = "blocked"
    read_results["futures_account"].body["funding"]["status"] = "unavailable"
    read_results["futures_account"].body["liquidation"]["status"] = "unavailable"
    read_results["futures_account"].body["reduce_only_close_only"]["status"] = "unavailable"
    read_results["futures_positions"].body["count"] = 0
    read_results["futures_positions"].body["items"] = []
    read_results["futures_risk_proofs"].body["status"] = "blocked"
    read_results["futures_command_suite"].body["status"] = "blocked"
    read_results["futures_command_suite"].body["missing_backend_contracts"] = [
        "futures_margin_collateral_risk_proof"
    ]

    summary = smoke.build_smoke_summary(
        read_results=read_results,
        applied_environment={smoke.run_admin_api.OS_TRUSTSTORE_ENV: "enabled"},
        started_at="2026-07-03T20:00:00Z",
        ended_at="2026-07-03T20:00:01Z",
        duration_seconds=1,
        backend_git_commit="abc1234",
        backend_git_branch="codex/account-futures-mvp-local-cd",
        backend_contract_ref="abc1234",
        environ={"COINBASE_API_KEY": "present", "COINBASE_API_SECRET": "present"},
    )

    failed = {check["name"] for check in summary["checks"] if not check["passed"]}
    assert summary["status"] == "failed"
    assert "wallet_futures_risk_input_ready" in failed
    assert "futures_observed_position_scope_ready" in failed
    assert "futures_positions_scope_readback" in failed
    assert "futures_account_funding_ready" in failed
    assert "futures_account_liquidation_ready" in failed
    assert "futures_account_reduce_close_ready" in failed
    assert "futures_margin_collateral_ready" in failed
    assert "futures_command_suite_evidence_ready" in failed


def test_account_reality_live_read_smoke_main_writes_artifact(monkeypatch, tmp_path):
    class FakeService:
        def record_live_service_decision(self, body, context):
            return result({"decision": {"decision_id": body["decision_id"]}})

        def record_live_adapter_decision(self, body, context):
            return result({"decision": {"decision_id": body["decision_id"]}})

        def get_read_response(self, route, query, context):
            route_map = {
                "/api/v1/admin/wallet": "wallet",
                "/api/v1/futures/account": "futures_account",
                "/api/v1/futures/positions": "futures_positions",
                "/api/v1/futures/risk-proofs": "futures_risk_proofs",
                "/api/v1/futures/command-suite": "futures_command_suite",
            }
            return ready_read_results()[route_map[route]]

    monkeypatch.setattr(smoke, "get_admin_mvp_service", lambda: FakeService())
    monkeypatch.setattr(
        smoke,
        "apply_runner_environment",
        lambda: {smoke.run_admin_api.OS_TRUSTSTORE_ENV: "enabled"},
    )
    monkeypatch.setattr(
        smoke,
        "read_git_value",
        lambda args, fallback="unknown": {
            ("rev-parse", "--short", "HEAD"): "abc1234",
            ("rev-parse", "--abbrev-ref", "HEAD"): "codex/account-futures-mvp-local-cd",
        }.get(tuple(args), fallback),
    )
    monkeypatch.setenv("COINBASE_API_KEY", "present")
    monkeypatch.setenv("COINBASE_API_SECRET", "present")
    summary_path = tmp_path / "account-reality-smoke.json"

    exit_code = smoke.main(["--summary-output", str(summary_path)])

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert summary["status"] == "passed"
    assert summary["backend_git_commit"] == "abc1234"
    assert summary["backend_git_branch"] == "codex/account-futures-mvp-local-cd"
