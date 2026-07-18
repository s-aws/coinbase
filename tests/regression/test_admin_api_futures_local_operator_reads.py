"""Installed HTTP contract for call-free Futures operator reads."""

from __future__ import annotations

import gc
import shutil

import pytest

from api.v1.routes import futures as futures_routes
from application.admin_api.mvp_service import AdminMvpDependencies, AdminMvpService
from core.enums import AdminApiRole
from tests.regression import test_admin_api_contract as contract


pytestmark = [pytest.mark.regression, pytest.mark.serial]


@pytest.fixture(autouse=True)
def _close_imported_contract_clients():
    yield
    while contract._ACTIVE_TEST_CLIENTS:
        client = contract._ACTIVE_TEST_CLIENTS.pop()
        try:
            client.app.dependency_overrides.clear()
        finally:
            client.close()
    gc.collect()
    while contract._ACTIVE_TEST_STORE_DIRS:
        shutil.rmtree(
            contract._ACTIVE_TEST_STORE_DIRS.pop(),
            ignore_errors=True,
        )


class _CoinbaseReadBomb:
    """Fail if an ordinary operator read reaches any Coinbase client method."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str):
        def unexpected_call(*_args, **_kwargs):
            self.calls.append(name)
            raise AssertionError(f"unexpected Coinbase call: {name}")

        return unexpected_call


def test_installed_futures_operator_reads_validate_call_free_local_evidence(
    monkeypatch: pytest.MonkeyPatch,
):
    client = contract._client(monkeypatch)
    rest_client = _CoinbaseReadBomb()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=rest_client,
            rest_client_available=True,
        )
    )
    client.app.dependency_overrides[
        futures_routes.get_authoritative_futures_read_service
    ] = lambda: service

    responses = {
        "account": client.get(
            "/api/v1/futures/account",
            headers=contract._headers(roles=AdminApiRole.VIEWER.value),
        ),
        "positions": client.get(
            "/api/v1/futures/positions?limit=10&offset=0",
            headers=contract._headers(roles=AdminApiRole.VIEWER.value),
        ),
        "position_detail": client.get(
            "/api/v1/futures/positions/futures-position-mock",
            headers=contract._headers(roles=AdminApiRole.VIEWER.value),
        ),
    }

    assert {name: response.status_code for name, response in responses.items()} == {
        "account": 200,
        "positions": 200,
        "position_detail": 200,
    }
    for response in responses.values():
        body = response.json()
        assert body["portfolio_binding"]["source"] == (
            "backend_admin_api_local_evidence"
        )
        assert body["portfolio_binding"]["freshness_status"] == (
            "local_sanitized_evidence"
        )
        assert body["readback_source"] == "backend_admin_api_local_evidence"
        assert body["coinbase_read_attempted"] is False
        assert body["live_coinbase_read_ran"] is False
        assert body["live_coinbase_orders_ran"] is False
    assert rest_client.calls == []
