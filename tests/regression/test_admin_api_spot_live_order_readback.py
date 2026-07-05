from __future__ import annotations

from dataclasses import dataclass, field
import json

import pytest

import tools.run_admin_api_spot_live_order_readback as spot_readback
from tools.run_admin_api_spot_live_order_readback import (
    SpotLiveOrderReadbackConfig,
    run_spot_live_order_readback,
)


@dataclass
class FakeSpotReadbackRestClient:
    list_orders_response: dict = field(default_factory=dict)
    list_orders_responses_by_status: dict[str, dict] = field(default_factory=dict)
    list_fills_response: dict = field(default_factory=dict)
    list_orders_calls: list[dict] = field(default_factory=list)
    list_fills_calls: list[dict] = field(default_factory=list)

    def list_orders(self, **kwargs):
        self.list_orders_calls.append(kwargs)
        statuses = kwargs.get("order_status") or []
        status = statuses[0] if statuses else ""
        if status in self.list_orders_responses_by_status:
            return self.list_orders_responses_by_status[status]
        return self.list_orders_response

    def list_fills(self, **kwargs):
        self.list_fills_calls.append(kwargs)
        return self.list_fills_response


def write_manual_submit_artifact(
    tmp_path,
    *,
    client_order_id: str = "spot-live-submit-test",
    product_id: str = "BTC-USDC",
    exchange_order_id: str = "exchange-order-live-spot-1",
):
    artifact = tmp_path / "coinbase-backend-manual-live-submit.json"
    artifact.write_text(
        json.dumps(
            {
                "artifact_type": "coinbase_admin_api_manual_order_live_submit",
                "status": "passed",
                "client_order_id": client_order_id,
                "product_id": product_id,
                "coinbase_order_id": exchange_order_id,
                "live_exchange_submitted": True,
                "live_coinbase_execution": "submitted",
                "live_coinbase_orders_ran": True,
                "proof_chain_status": "passed",
                "approval_snapshot_id": "mvp-approval-spot-live",
                "admission_audit_id": "mvp-admission-audit-spot-live",
                "cap_guard_decision_id": "mvp-cap-guard-spot-live",
                "reconciliation_plan_id": "mvp-reconciliation-spot-live",
            }
        ),
        encoding="utf-8",
    )
    return artifact


def write_spot_cancel_seed_artifact(tmp_path):
    artifact = tmp_path / "coinbase-backend-spot-live-cancel.json"
    artifact.write_text(
        json.dumps(
            {
                "artifact_type": "coinbase_admin_api_spot_live_cancel",
                "status": "passed",
                "client_order_id": "spot-live-cancel-seed",
                "seed_order_client_order_id": "spot-live-cancel-seed",
                "seed_order_product_id": "USDT-USDC",
                "seed_order_coinbase_order_id": "exchange-order-live-seed",
                "seed_order_live_exchange_submitted": True,
                "seed_order_live_coinbase_orders_ran": True,
                "live_coinbase_execution": "submitted",
                "seed_order_proof_chain_status": "passed",
            }
        ),
        encoding="utf-8",
    )
    return artifact


def test_spot_live_order_readback_credential_gate_hydrates_from_backend_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environ: dict[str, str] = {}
    calls: list[dict[str, str]] = []

    def fake_ensure_live_coinbase_credentials(target: dict[str, str]) -> None:
        calls.append(target)
        target["COINBASE_API_KEY"] = "secret-manager-key"
        target["COINBASE_API_SECRET"] = "secret-manager-secret"

    monkeypatch.setattr(
        spot_readback,
        "ensure_live_coinbase_credentials",
        fake_ensure_live_coinbase_credentials,
    )

    spot_readback.assert_live_read_credentials_present(environ)

    assert calls == [environ]
    assert environ["COINBASE_API_KEY"] == "secret-manager-key"
    assert environ["COINBASE_API_SECRET"] == "secret-manager-secret"


def test_spot_live_order_readback_proves_order_and_fills_by_client_order_id(tmp_path):
    submission_artifact = write_manual_submit_artifact(tmp_path)
    rest_client = FakeSpotReadbackRestClient(
        list_orders_response={
            "orders": [
                {
                    "client_order_id": "spot-live-submit-test",
                    "order_id": "exchange-order-live-spot-1",
                    "product_id": "BTC-USDC",
                    "status": "FILLED",
                    "filled_size": "0.00001",
                    "average_filled_price": "100000",
                }
            ]
        },
        list_fills_response={
            "fills": [
                {
                    "entry_id": "entry-spot-1",
                    "trade_id": "trade-spot-1",
                    "order_id": "exchange-order-live-spot-1",
                    "product_id": "BTC-USDC",
                    "size": "1.00000",
                    "size_in_quote": True,
                    "price": "100000",
                    "commission": "0.01",
                }
            ],
            "has_next": False,
        },
    )

    summary = run_spot_live_order_readback(
        rest_client,
        SpotLiveOrderReadbackConfig(
            client_order_id="spot-live-submit-test",
            product_id="BTC-USDC",
            submission_artifact=submission_artifact,
            backend_contract_ref="backend-ref",
            require_submission_artifact=True,
        ),
    )

    assert summary["status"] == "passed"
    assert summary["live_coinbase_execution"] == "not_run"
    assert summary["live_coinbase_read_ran"] is True
    assert summary["live_coinbase_orders_ran"] is False
    assert summary["read_only"] is True
    assert summary["client_order_id"] == "spot-live-submit-test"
    assert summary["product_id"] == "BTC-USDC"
    assert summary["order_status"] == "FILLED"
    assert summary["order_found"] is True
    assert summary["exchange_order_id_present"] is True
    assert summary["exchange_order_id_evidence_only"] is True
    assert summary["exchange_order_id"] == "exchange-order-live-spot-1"
    assert summary["fill_count"] == 1
    assert summary["fill_read_status"] == "filled"
    assert summary["executed_notional_usdc"] == "1.00000"
    assert summary["submitted_notional_usdc"] == "0"
    assert summary["notional_usdc"] == "0"
    assert summary["operator_identity_key"] == "client_order_id"
    assert summary["submission_artifact_present"] is True
    assert summary["submission_artifact_status"] == "passed"
    assert summary["submission_artifact_matches_client_order_id"] is True
    assert summary["submission_artifact_matches_product_id"] is True
    assert summary["submission_artifact_live_exchange_submitted"] is True
    assert summary["submission_artifact_live_coinbase_execution"] == "submitted"
    assert summary["submission_artifact_exchange_order_id_matches_readback"] is True
    assert summary["submission_artifact_cap_guard_decision_id"] == (
        "mvp-cap-guard-spot-live"
    )
    assert {
        "spot_submission_artifact_present",
        "spot_submission_artifact_matches_client_order_id",
        "spot_submission_artifact_exchange_order_id_matches_readback",
    }.issubset({check["name"] for check in summary["checks"]})
    assert all(check["passed"] for check in summary["checks"])
    assert rest_client.list_orders_calls == [{"order_status": ["FILLED"]}]
    assert rest_client.list_fills_calls == [
        {"order_id": "exchange-order-live-spot-1", "limit": 100}
    ]


def test_spot_live_order_readback_passes_for_found_order_without_fills(tmp_path):
    submission_artifact = write_manual_submit_artifact(tmp_path)
    rest_client = FakeSpotReadbackRestClient(
        list_orders_response={
            "orders": [
                {
                    "client_order_id": "spot-live-submit-test",
                    "order_id": "exchange-order-live-spot-1",
                    "product_id": "BTC-USDC",
                    "status": "EXPIRED",
                    "filled_size": "0",
                }
            ]
        },
        list_fills_response={"fills": [], "has_next": False},
    )

    summary = run_spot_live_order_readback(
        rest_client,
        SpotLiveOrderReadbackConfig(
            client_order_id="spot-live-submit-test",
            product_id="BTC-USDC",
            submission_artifact=submission_artifact,
            backend_contract_ref="backend-ref",
            require_submission_artifact=True,
        ),
    )

    assert summary["status"] == "passed"
    assert summary["order_status"] == "EXPIRED"
    assert summary["fill_count"] == 0
    assert summary["fill_read_status"] == "not_filled"
    assert summary["executed_notional_usdc"] == "0"
    assert all(check["passed"] for check in summary["checks"])


def test_spot_live_order_readback_accepts_spot_cancel_seed_artifact(tmp_path):
    submission_artifact = write_spot_cancel_seed_artifact(tmp_path)
    rest_client = FakeSpotReadbackRestClient(
        list_orders_response={
            "orders": [
                {
                    "client_order_id": "spot-live-cancel-seed",
                    "order_id": "exchange-order-live-seed",
                    "product_id": "USDT-USDC",
                    "status": "OPEN",
                }
            ]
        },
        list_fills_response={"fills": [], "has_next": False},
    )

    summary = run_spot_live_order_readback(
        rest_client,
        SpotLiveOrderReadbackConfig(
            submission_artifact=submission_artifact,
            backend_contract_ref="backend-ref",
            require_submission_artifact=True,
        ),
    )

    assert summary["status"] == "passed"
    assert summary["submission_artifact_type"] == "coinbase_admin_api_spot_live_cancel"
    assert summary["client_order_id"] == "spot-live-cancel-seed"
    assert summary["product_id"] == "USDT-USDC"
    assert summary["exchange_order_id"] == "exchange-order-live-seed"
    assert summary["submission_artifact_matches_client_order_id"] is True
    assert summary["submission_artifact_matches_product_id"] is True


def test_spot_live_order_readback_fails_when_fill_order_id_does_not_match(tmp_path):
    submission_artifact = write_manual_submit_artifact(tmp_path)
    rest_client = FakeSpotReadbackRestClient(
        list_orders_response={
            "orders": [
                {
                    "client_order_id": "spot-live-submit-test",
                    "order_id": "exchange-order-live-spot-1",
                    "product_id": "BTC-USDC",
                    "status": "FILLED",
                }
            ]
        },
        list_fills_response={
            "fills": [
                {
                    "entry_id": "entry-spot-1",
                    "trade_id": "trade-spot-1",
                    "order_id": "different-exchange-order",
                    "product_id": "BTC-USDC",
                    "size": "0.00001",
                    "price": "100000",
                }
            ],
            "has_next": False,
        },
    )

    summary = run_spot_live_order_readback(
        rest_client,
        SpotLiveOrderReadbackConfig(
            client_order_id="spot-live-submit-test",
            product_id="BTC-USDC",
            submission_artifact=submission_artifact,
            backend_contract_ref="backend-ref",
            require_submission_artifact=True,
        ),
    )

    assert summary["status"] == "failed"
    assert summary["fill_order_id_matches_exchange_order_id"] is False
    failed = [check["name"] for check in summary["checks"] if not check["passed"]]
    assert "spot_fills_match_exchange_order_id_when_present" in failed
