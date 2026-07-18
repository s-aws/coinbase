from __future__ import annotations

import json

import pytest

from application.admin_api.mvp_service import (
    AdminMvpDependencies,
    AdminMvpEvidenceLog,
    AdminMvpService,
    AdminMvpStore,
)
from core.coinbase_execution_authority import (
    SOURCE_DISABLED_COINBASE_EXECUTION_ERROR,
)
from tests.regression.test_admin_mvp_api import FakeAccountRestClient
from tools import run_admin_api_futures_live_submit as live_submit_cli


CLIENT_ORDER_ID = "historical-futures-submit-client"
SUBMISSION_EVENT_ID = "historical-futures-submit-event"
CAP_GUARD_ID = "historical-futures-submit-cap"
RECONCILIATION_PLAN_ID = "historical-futures-submit-reconciliation"
RECORDED_AT = "2026-01-01T00:00:00Z"


def _historical_store() -> AdminMvpStore:
    store = AdminMvpStore()
    store.cap_guard_decisions[CAP_GUARD_ID] = {"recorded_at": RECORDED_AT}
    store.reconciliation_plans[RECONCILIATION_PLAN_ID] = {
        "recorded_at": RECORDED_AT,
    }
    store.futures_command_decisions[SUBMISSION_EVENT_ID] = {
        "decision_id": SUBMISSION_EVENT_ID,
        "mutation_family": "futures_live_place",
        "identity_key": "product_id",
        "identity_value": "AVP-20DEC30-CDE",
        "client_order_id": CLIENT_ORDER_ID,
        "status": "accepted",
        "recorded_at": RECORDED_AT,
        "cap_guard_present": True,
        "cap_guard_decision_id": CAP_GUARD_ID,
        "reconciliation_plan_present": True,
        "reconciliation_plan_id": RECONCILIATION_PLAN_ID,
        "live_exchange_submitted": True,
        "live_coinbase_orders_ran": True,
        "live_coinbase_execution": "submitted",
        "submitted_notional_usdc": "69.20",
        "exchange_order_id_evidence_only": True,
    }
    return store


def _historical_service(
    rest_client: FakeAccountRestClient,
) -> AdminMvpService:
    return AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
        ),
        store=_historical_store(),
        evidence_log=AdminMvpEvidenceLog(),
    )


def _historical_artifact() -> dict[str, object]:
    return {
        "schema_version": "1",
        "artifact_type": live_submit_cli.ARTIFACT_TYPE,
        "status": "failed",
        "backend_git_commit": "historical-ref",
        "backend_git_branch": "historical",
        "backend_contract_ref": "historical-ref",
        "product_id": "AVP-20DEC30-CDE",
        "client_order_id": CLIENT_ORDER_ID,
        "submission_event_id": SUBMISSION_EVENT_ID,
        "cap_guard_present": True,
        "cap_guard_decision_id": CAP_GUARD_ID,
        "reconciliation_plan_present": True,
        "reconciliation_plan_id": RECONCILIATION_PLAN_ID,
        "live_coinbase_execution": "submitted",
        "submitted_notional_usdc": "69.20",
        "notional_usdc": "69.20",
        "checks": [
            {"name": "historical_terminal_submit_evidence", "passed": True},
            {
                "name": "futures_audit_workbench_proof_chain_readback",
                "passed": False,
            },
        ],
    }


def _assert_no_coinbase_rest_calls(rest_client: FakeAccountRestClient) -> None:
    assert rest_client.create_order_calls == []
    assert rest_client.cancel_order_calls == []
    assert rest_client.close_position_calls == []
    assert rest_client.list_orders_calls == []
    assert rest_client.list_fills_calls == []
    assert rest_client.get_account_wallets_calls == 0
    assert rest_client.get_api_key_permissions_calls == 0
    assert rest_client.list_portfolios_calls == 0
    assert rest_client.get_futures_positions_calls == 0
    assert rest_client.get_futures_margin_collateral_snapshot_calls == 0
    assert rest_client.get_product_dict_calls == []
    assert rest_client.get_transaction_summary_calls == 0


def test_historical_futures_submit_body_serializer_remains_stable():
    body = live_submit_cli.build_futures_live_submit_body(
        live_submit_cli.FuturesLiveSubmitConfig(
            limit_price="6.92",
            leverage="3",
            margin_type="CROSS",
            retail_portfolio_id="portfolio-test-1",
        )
    )

    assert body == {
        "product_id": "AVP-20DEC30-CDE",
        "side": "BUY",
        "order_type": "LIMIT",
        "limit_price": "6.92",
        "size": "1",
        "post_only": False,
        "dry_run": False,
        "manual_live_acknowledgement": True,
        "leverage": "3",
        "margin_type": "CROSS",
        "retail_portfolio_id": "portfolio-test-1",
    }


def test_futures_submit_cli_is_source_disabled_before_state_service_or_sdk(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    calls: list[str] = []

    def forbidden(name: str):
        def fail(*_args, **_kwargs):
            calls.append(name)
            raise AssertionError(f"{name} must not run")

        return fail

    monkeypatch.setattr(
        live_submit_cli,
        "apply_manual_live_submit_state_environment",
        forbidden("state_environment"),
    )
    monkeypatch.setattr(
        live_submit_cli,
        "apply_runner_environment",
        forbidden("runner_environment"),
    )
    monkeypatch.setattr(
        live_submit_cli,
        "get_admin_mvp_service",
        forbidden("credential_service_sdk"),
    )

    with pytest.raises(SystemExit) as error:
        live_submit_cli.main(["--confirm-live-submit"])

    assert error.value.code == 2
    assert SOURCE_DISABLED_COINBASE_EXECUTION_ERROR in capsys.readouterr().err
    assert calls == []


def test_futures_submit_cli_refreshes_sanitized_artifact_without_coinbase_calls(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    rest_client = FakeAccountRestClient()
    service = _historical_service(rest_client)
    artifact_path = tmp_path / "futures-live-submit.json"
    artifact_path.write_text(
        json.dumps(_historical_artifact(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        live_submit_cli,
        "apply_manual_live_submit_state_environment",
        lambda _state_dir: None,
    )
    monkeypatch.setattr(live_submit_cli, "apply_runner_environment", lambda: None)
    monkeypatch.setattr(live_submit_cli, "get_admin_mvp_service", lambda: service)

    exit_code = live_submit_cli.main(
        [
            "--refresh-existing-artifact",
            "--summary-output",
            str(artifact_path),
            "--client-order-id",
            CLIENT_ORDER_ID,
            "--backend-contract-ref",
            "current-ref",
        ]
    )

    refreshed = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert refreshed["status"] == "passed"
    assert refreshed["refreshed_existing_artifact"] is True
    assert refreshed["refresh_live_coinbase_execution"] == "not_run"
    assert refreshed["refresh_notional_usdc"] == "0"
    assert refreshed["backend_contract_ref"] == "current-ref"
    assert refreshed["client_order_id"] == CLIENT_ORDER_ID
    assert refreshed["audit_submission_event_id"] == SUBMISSION_EVENT_ID
    assert refreshed["audit_cap_guard_decision_id"] == CAP_GUARD_ID
    assert (
        refreshed["audit_reconciliation_plan_id"] == RECONCILIATION_PLAN_ID
    )
    assert {
        item["name"]: item["passed"] for item in refreshed["checks"]
    }["futures_audit_workbench_proof_chain_readback"] is True
    _assert_no_coinbase_rest_calls(rest_client)


def test_futures_submit_refresh_reconstructs_missing_artifact_from_local_state(
    tmp_path,
):
    rest_client = FakeAccountRestClient()
    service = _historical_service(rest_client)
    artifact_path = tmp_path / "missing-futures-live-submit.json"

    refreshed = live_submit_cli.refresh_existing_futures_live_submit_summary(
        service,
        live_submit_cli.FuturesLiveSubmitConfig(
            refresh_existing_artifact=True,
            summary_output=artifact_path,
            backend_contract_ref="current-ref",
            refresh_client_order_id=CLIENT_ORDER_ID,
            correlation_id="historical-refresh-correlation",
        ),
    )

    assert refreshed["status"] == "passed"
    assert refreshed["refreshed_existing_artifact"] is True
    assert refreshed["refresh_live_coinbase_execution"] == "not_run"
    assert refreshed["refresh_notional_usdc"] == "0"
    assert refreshed["client_order_id"] == CLIENT_ORDER_ID
    assert refreshed["audit_submission_event_id"] == SUBMISSION_EVENT_ID
    assert refreshed["audit_cap_guard_decision_id"] == CAP_GUARD_ID
    assert (
        refreshed["audit_reconciliation_plan_id"] == RECONCILIATION_PLAN_ID
    )
    assert not artifact_path.exists()
    _assert_no_coinbase_rest_calls(rest_client)
