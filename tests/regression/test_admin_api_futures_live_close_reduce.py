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
from tools import run_admin_api_futures_live_close_reduce as close_reduce_cli


CLIENT_ORDER_ID = "historical-futures-close-reduce-client"
POSITION_KEY = "futures_position:default:AVP-20DEC30-CDE"
SUBMISSION_EVENT_ID = "historical-futures-close-reduce-event"
CAP_GUARD_ID = "historical-futures-close-reduce-cap"
RECONCILIATION_PLAN_ID = "historical-futures-close-reduce-reconciliation"
RECORDED_AT = "2026-01-01T00:00:00Z"


def _historical_service(
    rest_client: FakeAccountRestClient,
) -> AdminMvpService:
    store = AdminMvpStore()
    store.cap_guard_decisions[CAP_GUARD_ID] = {"recorded_at": RECORDED_AT}
    store.reconciliation_plans[RECONCILIATION_PLAN_ID] = {
        "recorded_at": RECORDED_AT,
    }
    store.futures_command_decisions[SUBMISSION_EVENT_ID] = {
        "decision_id": SUBMISSION_EVENT_ID,
        "mutation_family": "futures_live_close_reduce",
        "identity_key": "position_key",
        "identity_value": POSITION_KEY,
        "client_order_id": CLIENT_ORDER_ID,
        "status": "accepted",
        "recorded_at": RECORDED_AT,
        "cap_guard_present": True,
        "cap_guard_decision_id": CAP_GUARD_ID,
        "reconciliation_plan_present": True,
        "reconciliation_plan_id": RECONCILIATION_PLAN_ID,
        "live_exchange_submitted": True,
        "live_coinbase_orders_ran": True,
    }
    return AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
        ),
        store=store,
        evidence_log=AdminMvpEvidenceLog(),
    )


def _historical_artifact() -> dict[str, object]:
    return {
        "schema_version": "1",
        "artifact_type": close_reduce_cli.ARTIFACT_TYPE,
        "status": "failed",
        "backend_git_commit": "historical-ref",
        "backend_git_branch": "historical",
        "backend_contract_ref": "historical-ref",
        "position_key": POSITION_KEY,
        "product_id": "AVP-20DEC30-CDE",
        "client_order_id": CLIENT_ORDER_ID,
        "submission_event_id": SUBMISSION_EVENT_ID,
        "cap_guard_present": True,
        "cap_guard_decision_id": CAP_GUARD_ID,
        "reconciliation_plan_present": True,
        "reconciliation_plan_id": RECONCILIATION_PLAN_ID,
        "live_coinbase_execution": "submitted",
        "submitted_notional_usdc": "69.30",
        "notional_usdc": "69.30",
        "checks": [
            {
                "name": "historical_terminal_close_reduce_evidence",
                "passed": True,
            },
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


def test_historical_futures_close_reduce_body_serializer_remains_stable():
    body = close_reduce_cli.build_futures_live_close_reduce_body(
        close_reduce_cli.FuturesLiveCloseReduceConfig(
            position_key=POSITION_KEY,
            limit_price="6.93",
        )
    )

    assert body == {
        "position_key": POSITION_KEY,
        "product_id": "AVP-20DEC30-CDE",
        "limit_price": "6.93",
        "size": "1",
        "dry_run": False,
        "manual_live_acknowledgement": True,
        "operator_reason": (
            "operator confirmed backend-controlled futures close/reduce"
        ),
    }


def test_futures_close_reduce_cli_is_source_disabled_before_state_service_or_sdk(
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
        close_reduce_cli,
        "apply_manual_live_submit_state_environment",
        forbidden("state_environment"),
    )
    monkeypatch.setattr(
        close_reduce_cli,
        "apply_runner_environment",
        forbidden("runner_environment"),
    )
    monkeypatch.setattr(
        close_reduce_cli,
        "get_admin_mvp_service",
        forbidden("credential_service_sdk"),
    )

    with pytest.raises(SystemExit) as error:
        close_reduce_cli.main(["--confirm-live-close-reduce"])

    assert error.value.code == 2
    assert SOURCE_DISABLED_COINBASE_EXECUTION_ERROR in capsys.readouterr().err
    assert calls == []


def test_futures_close_reduce_cli_refreshes_sanitized_artifact_without_coinbase_calls(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    rest_client = FakeAccountRestClient()
    service = _historical_service(rest_client)
    artifact_path = tmp_path / "futures-live-close-reduce.json"
    artifact_path.write_text(
        json.dumps(_historical_artifact(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        close_reduce_cli,
        "apply_manual_live_submit_state_environment",
        lambda _state_dir: None,
    )
    monkeypatch.setattr(close_reduce_cli, "apply_runner_environment", lambda: None)
    monkeypatch.setattr(close_reduce_cli, "get_admin_mvp_service", lambda: service)

    exit_code = close_reduce_cli.main(
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
