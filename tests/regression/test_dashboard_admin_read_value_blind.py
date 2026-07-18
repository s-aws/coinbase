"""Value-blind failure contracts for legacy-backed public Admin reads."""

import json

import pytest


pytestmark = pytest.mark.regression

_PRIVATE_EXCEPTION_TEXT = (
    "raw-response api-key=private-key portfolio=private-portfolio "
    "client_order_id=private-client-order"
)


def _raise_private_runtime_error(*_args, **_kwargs):
    raise RuntimeError(_PRIVATE_EXCEPTION_TEXT)


def _assert_private_exception_text_absent(payload):
    serialized = json.dumps(payload, sort_keys=True)
    assert _PRIVATE_EXCEPTION_TEXT not in serialized
    assert "private-key" not in serialized
    assert "private-portfolio" not in serialized


def test_admin_spot_readiness_is_local_and_value_blind(monkeypatch):
    import dashboard_server

    from application.admin_api.read_service import AdminApiReadService

    monkeypatch.setattr(
        dashboard_server,
        "_build_spot_readiness_payload",
        _raise_private_runtime_error,
    )

    payload = AdminApiReadService().build_spot_readiness(
        product_ids=["BTC-USDC"],
    )

    assert payload["status"] == "blocked"
    assert payload["local_only"] is True
    assert payload["values_withheld"] is True
    assert payload["coinbase_read_attempted"] is False
    assert payload["live_coinbase_read_ran"] is False
    assert payload["wallet_snapshot"]["status"] == "withheld"
    _assert_private_exception_text_absent(payload)


@pytest.mark.parametrize(
    ("service_method", "patched_module", "patched_name", "expected_message"),
    [
        (
            "build_spot_sweep_status",
            "business.spot_portfolio_sweep",
            "load_sweep_run_records",
            "sweep status failed: exception_class:RuntimeError",
        ),
        (
            "build_spot_cost_basis_status",
            "business.spot_cost_basis",
            "load_cost_basis_snapshot_records",
            "cost-basis status failed: exception_class:RuntimeError",
        ),
        (
            "build_spot_campaign_status",
            "business.spot_campaign",
            "load_spot_campaign_snapshot_records",
            "campaign status failed: exception_class:RuntimeError",
        ),
    ],
)
def test_admin_local_spot_status_failures_are_value_blind(
    monkeypatch,
    service_method,
    patched_module,
    patched_name,
    expected_message,
):
    import importlib

    from application.admin_api.read_service import AdminApiReadService

    module = importlib.import_module(patched_module)
    monkeypatch.setattr(module, patched_name, _raise_private_runtime_error)

    payload = getattr(AdminApiReadService(), service_method)(
        state_file="synthetic-state.jsonl",
    )

    assert payload["status"] == "error"
    assert payload["message"] == expected_message
    _assert_private_exception_text_absent(payload)


def test_admin_spot_sweep_pnl_is_local_and_value_blind(monkeypatch):
    import dashboard_server

    from application.admin_api.read_service import AdminApiReadService

    monkeypatch.setattr(
        dashboard_server,
        "_build_spot_sweep_pnl_payload",
        _raise_private_runtime_error,
    )

    payload = AdminApiReadService().build_spot_sweep_pnl(
        product_ids=["BTC-USDC"],
    )

    assert payload["status"] == "blocked"
    assert payload["pnl_report"] is None
    assert payload["read_only_coinbase_requests"] == []
    assert payload["local_only"] is True
    assert payload["values_withheld"] is True
    assert payload["coinbase_read_attempted"] is False
    assert payload["live_coinbase_read_ran"] is False
    _assert_private_exception_text_absent(payload)


def test_admin_spot_direct_order_audit_failure_is_value_blind(monkeypatch):
    import dashboard_server

    from application.admin_api.read_service import AdminApiReadService

    monkeypatch.setattr(
        dashboard_server,
        "PostgresDB",
        _raise_private_runtime_error,
    )

    payload = AdminApiReadService().build_spot_direct_order_audit(
        client_order_id="synthetic-client-order",
    )

    assert payload["status"] == "error"
    assert payload["message"] == (
        "direct order audit failed: exception_class:RuntimeError"
    )
    _assert_private_exception_text_absent(payload)
