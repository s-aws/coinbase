from __future__ import annotations

import pytest

from application.admin_api.mvp_service import (
    AdminMvpDependencies,
    AdminMvpEvidenceLog,
    AdminMvpRequestContext,
    AdminMvpService,
)
from tests.regression.test_admin_mvp_api import FakeAccountRestClient, FakeRestClient
import tools.run_admin_api_manual_order_live_submit as manual_live_submit
from tools.run_admin_api_manual_order_live_submit import (
    LiveSubmitCapExceededError,
    LiveSubmitConfirmationError,
    ManualLiveSubmitConfig,
    apply_manual_live_submit_state_environment,
    build_manual_order_body,
    run_manual_live_submit,
)


def test_manual_live_submit_body_defaults_to_small_limit_ioc_buy():
    body = build_manual_order_body(ManualLiveSubmitConfig(confirm_live_submit=True))

    assert body == {
        "product_id": "BTC-USDC",
        "side": "BUY",
        "order_type": "LIMIT",
        "quote_size": "1.00",
        "limit_price": "1000000.00",
        "time_in_force": "IOC",
        "post_only": False,
        "manual_live_acknowledgement": True,
    }


def test_manual_live_submit_credential_gate_hydrates_from_backend_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environ: dict[str, str] = {}
    calls: list[dict[str, str]] = []

    def fake_ensure_live_coinbase_credentials(target: dict[str, str]) -> None:
        calls.append(target)
        target["COINBASE_API_KEY"] = "secret-manager-key"
        target["COINBASE_API_SECRET"] = "secret-manager-secret"

    monkeypatch.setattr(
        manual_live_submit,
        "ensure_live_coinbase_credentials",
        fake_ensure_live_coinbase_credentials,
    )

    manual_live_submit.assert_live_credentials_present(environ)

    assert calls == [environ]
    assert environ["COINBASE_API_KEY"] == "secret-manager-key"
    assert environ["COINBASE_API_SECRET"] == "secret-manager-secret"


def test_manual_live_submit_requires_explicit_confirmation_before_service_calls():
    rest_client = FakeRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )

    with pytest.raises(LiveSubmitConfirmationError):
        run_manual_live_submit(service, ManualLiveSubmitConfig(confirm_live_submit=False))

    assert rest_client.create_order_calls == []


def test_manual_live_submit_records_admin_proof_chain_before_backend_rest_submission():
    rest_client = FakeAccountRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )

    summary = run_manual_live_submit(
        service,
        ManualLiveSubmitConfig(
            confirm_live_submit=True,
            idempotency_key="manual-live-submit-test",
            correlation_id="manual-live-submit-test-correlation",
        ),
    )

    assert summary["status"] == "passed"
    assert summary["live_coinbase_execution"] == "submitted"
    assert summary["notional_usdc"] == "1.00"
    assert summary["proof_chain_status"] == "passed"
    assert summary["final_status_code"] == 200
    assert summary["final_status"] == "accepted"
    assert summary["live_exchange_submitted"] is True
    assert summary["live_coinbase_orders_ran"] is True
    assert summary["paired_sell_required"] is False
    assert summary["coinbase_order_id"] == "exchange-order-live-1"
    assert rest_client.create_order_calls == [
        {
            "client_order_id": summary["client_order_id"],
            "product_id": "BTC-USDC",
            "side": "BUY",
            "order_configuration": {
                "sor_limit_ioc": {
                    "quote_size": "1.00",
                    "limit_price": "1000000.00",
                },
            },
        }
    ]


def test_manual_live_submit_blocks_when_state_would_exceed_submitted_cap(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "admin_api_audit.jsonl").write_text(
        (
            '{"collection":"spot_command_decisions","record":{'
            '"action_class":"live_exchange_place",'
            '"status":"accepted",'
            '"live_exchange_submitted":true,'
            '"live_coinbase_orders_ran":true,'
            '"notional_usdc":"2.50",'
            '"client_order_id":"previous-manual-live"'
            "}}\n"
        ),
        encoding="utf-8",
    )
    rest_client = FakeAccountRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )

    with pytest.raises(LiveSubmitCapExceededError, match="Manual live submit would exceed"):
        run_manual_live_submit(
            service,
            ManualLiveSubmitConfig(
                confirm_live_submit=True,
                quote_size="1.00",
                max_submitted_notional_usdc="3.10",
                state_dir=str(state_dir),
            ),
        )

    assert rest_client.create_order_calls == []


def test_manual_live_submit_persists_local_admin_evidence_for_restart(tmp_path):
    environ: dict[str, str] = {}
    applied_paths = apply_manual_live_submit_state_environment(tmp_path, environ)
    rest_client = FakeAccountRestClient()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        ),
        evidence_log=AdminMvpEvidenceLog.from_env(environ),
    )

    summary = run_manual_live_submit(
        service,
        ManualLiveSubmitConfig(
            confirm_live_submit=True,
            idempotency_key="manual-live-submit-persisted-test",
            correlation_id="manual-live-submit-persisted-test-correlation",
        ),
    )

    restarted_service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=FakeAccountRestClient(),
            rest_client_available=True,
        ),
        evidence_log=AdminMvpEvidenceLog.from_env(environ),
    )
    health = restarted_service.get_read_response(
        "/api/v1/admin/health",
        {},
        AdminMvpRequestContext(
            idempotency_key="read-persisted-live-submit",
            correlation_id="read-persisted-live-submit-correlation",
            operator_intent="read_admin_api",
            actor_id="operator-1",
            roles=("operator",),
        ),
    )

    assert summary["status"] == "passed"
    assert summary["live_coinbase_execution"] == "submitted"
    assert health.body["live_coinbase_orders_ran"] is True
    assert health.body["live_coinbase_execution"] == "submitted"
    assert health.body["notional_usdc"] == "1.00"
    assert all(path.endswith(".jsonl") for path in applied_paths.values())
