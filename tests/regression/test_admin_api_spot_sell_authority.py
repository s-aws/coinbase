"""Regression coverage for Admin API direct spot SELL authority wiring."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest

from application.admin_api.command_service import AdminApiCommandService
from application.admin_api.models import (
    AdminApiActor,
    AdminApiCommandEnvelope,
    ManualOrderCommand,
    ManualOrderRequest,
)
from core.enums import (
    ActionConditionType,
    ActionGuardPhase,
    AdminApiCommandStatus,
    InventoryAuthorityStatus,
    OrderSide,
    OrderType,
    ProductType,
    StealthOrderStatus,
)


pytestmark = pytest.mark.regression


BTC_USDC_METADATA = {
    "product_id": "BTC-USDC",
    "product_type": ProductType.SPOT.value,
    "type": ProductType.SPOT.value,
    "base_currency": "BTC",
    "quote_currency": "USDC",
    "base_increment": "0.00000001",
    "quote_increment": "0.01",
    "price_increment": "0.01",
    "base_min_size": "0.00000001",
    "quote_min_size": "1",
}


class _FakeDb:
    def __init__(
        self,
        *,
        stealth_rows: list[dict[str, Any]] | None = None,
        fill_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.stealth_rows = stealth_rows or []
        self.fill_rows = fill_rows or []
        self.queries: list[tuple[str, Any]] = []

    def execute_query(self, query: str, params: Any = None) -> list[dict[str, Any]]:
        self.queries.append((query, params))
        if "FROM stealth_orders" in query:
            return self.stealth_rows
        if "FROM fill_ledger" in query:
            return self.fill_rows
        return []


class _FakeRestClient:
    def __init__(self) -> None:
        self.create_order_calls: list[dict[str, Any]] = []

    def create_order(self, **kwargs: Any) -> dict[str, Any]:
        self.create_order_calls.append(dict(kwargs))
        return {
            "success": True,
            "success_response": {"order_id": "exchange-spot-sell-authority"},
        }


class _FakeOrderEventPublisher:
    enabled = True

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def publish_event(self, **kwargs: Any) -> bool:
        self.events.append(dict(kwargs))
        return True


class _AdmittingRuntimeController:
    @contextmanager
    def track_inflight(self, _category: str):
        yield


def _patch_btc_usdc_product(monkeypatch: pytest.MonkeyPatch) -> None:
    import calculation.size_validation as size_validation
    import configuration

    metadata = {"BTC-USDC": BTC_USDC_METADATA}
    monkeypatch.setattr(configuration, "PRODUCT_METADATA", metadata, raising=False)
    monkeypatch.setattr(configuration, "SPOT_PRODUCT_IDS", ["BTC-USDC"], raising=False)
    monkeypatch.setattr(size_validation, "PRODUCT_METADATA", metadata, raising=False)


def _patch_inventory_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    import configuration

    monkeypatch.setattr(
        configuration,
        "SPOT_INVENTORY_BASELINES",
        [
            {
                "product_id": "BTC-USDC",
                "quantity": "0.50",
                "remaining_quantity": "0.50",
                "entry_price": "100.00",
                "source_id": "admin-api-test-baseline",
            }
        ],
        raising=False,
    )


def _hidden_budget_rows() -> list[dict[str, Any]]:
    return [
        {
            "stealth_order_id": "hidden-sell-budget",
            "product_id": "BTC-USDC",
            "side": OrderSide.SELL.value,
            "remaining_size": "0.10",
            "limit_price": "200.00",
            "status": StealthOrderStatus.HIDDEN.value,
        },
        {
            "stealth_order_id": "pending-buy-budget",
            "product_id": "BTC-USDC",
            "side": OrderSide.BUY.value,
            "remaining_size": "0.05",
            "limit_price": "200.00",
            "status": StealthOrderStatus.PENDING.value,
        },
        {
            "stealth_order_id": "revealed-ignored",
            "product_id": "BTC-USDC",
            "side": OrderSide.SELL.value,
            "remaining_size": "9.00",
            "limit_price": "200.00",
            "status": StealthOrderStatus.REVEALED.value,
        },
    ]


def test_admin_api_spot_planned_budget_reads_backend_stealth_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.v1.routes import orders as order_routes
    import database.order as order_db

    _patch_btc_usdc_product(monkeypatch)
    fake_db = _FakeDb(stealth_rows=_hidden_budget_rows())
    monkeypatch.setattr(order_db, "DB_CLIENT", fake_db, raising=False)

    budget = order_routes._get_admin_api_spot_planned_budget_commitments()

    assert budget == {"BTC": pytest.approx(0.10), "USDC": pytest.approx(10.0)}
    assert any("FROM stealth_orders" in query for query, _params in fake_db.queries)


def test_admin_api_spot_lot_authority_evaluator_uses_fill_ledger_repo_baselines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.v1.routes import orders as order_routes
    import business.fill_ledger as fill_ledger
    import database.order as order_db

    _patch_btc_usdc_product(monkeypatch)
    _patch_inventory_baseline(monkeypatch)
    fake_db = _FakeDb()
    monkeypatch.setattr(order_db, "DB_CLIENT", fake_db, raising=False)
    monkeypatch.setattr(
        fill_ledger.FillLedgerRepository,
        "_ensure_table_exists",
        lambda self: None,
    )

    evaluator = order_routes._get_admin_api_spot_lot_authority_evaluator()
    assert callable(evaluator)

    decision = evaluator(
        product_id="BTC-USDC",
        side=OrderSide.SELL.value,
        size=0.20,
        limit_price=200.00,
    )

    assert decision["allowed"] is True
    assert decision["status"] == InventoryAuthorityStatus.KNOWN_PROFITABLE.value
    assert decision["known_profitable_quantity"] == pytest.approx(0.50)
    assert any("FROM fill_ledger" in query for query, _params in fake_db.queries)


def test_admin_api_manual_spot_sell_consumes_backend_authority_before_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.v1.routes import orders as order_routes
    import business.fill_ledger as fill_ledger
    import business.order_event_stream as order_event_stream
    import configuration
    import core.action_condition_guard as guard_module
    import database.order as order_db

    _patch_btc_usdc_product(monkeypatch)
    _patch_inventory_baseline(monkeypatch)
    fake_db = _FakeDb(stealth_rows=_hidden_budget_rows())
    fake_rest_client = _FakeRestClient()
    fake_publisher = _FakeOrderEventPublisher()
    monkeypatch.setattr(order_db, "DB_CLIENT", fake_db, raising=False)
    monkeypatch.setattr(
        fill_ledger.FillLedgerRepository,
        "_ensure_table_exists",
        lambda self: None,
    )
    monkeypatch.setattr(configuration, "API_KEY", "test-key", raising=False)
    monkeypatch.setattr(configuration, "API_SECRET", "test-secret", raising=False)
    monkeypatch.setattr(configuration, "REST_CLIENT", fake_rest_client, raising=False)
    monkeypatch.setattr(
        configuration,
        "ACTION_CONDITION_GUARDS",
        {
            ActionConditionType.WALLET_AVAILABLE.value: {
                "enabled": True,
                "block_without_credentials": True,
            },
            ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value: {
                "enabled": True,
                "phases": [ActionGuardPhase.PLANNING.value],
            },
            "limits": [
                {
                    "name": "admin_api_direct_spot_sell_cap",
                    "product_type": ProductType.SPOT.value,
                    "side": OrderSide.SELL.value,
                    "max_notional": "100.00",
                    "phases": [ActionGuardPhase.PLANNING.value],
                }
            ],
        },
        raising=False,
    )
    monkeypatch.setattr(
        guard_module,
        "fetch_account_wallets",
        lambda: {"BTC": {"available_balance": {"value": "1.00"}}},
    )
    monkeypatch.setattr(
        order_event_stream,
        "OrderEventStreamPublisher",
        lambda _db_module: fake_publisher,
    )

    service = order_routes.get_command_service()
    service.dependencies.runtime_controller_factory = _AdmittingRuntimeController
    command = ManualOrderCommand(
        envelope=AdminApiCommandEnvelope(
            idempotency_key="idem-admin-api-spot-sell-authority",
            correlation_id="corr-admin-api-spot-sell-authority",
            operator_intent="prove_admin_api_spot_sell_authority",
            actor=AdminApiActor(actor_id="operator-test", roles=[]),
        ),
        request=ManualOrderRequest(
            client_order_id="client-admin-api-spot-sell-authority",
            product_id="BTC-USDC",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            base_size="0.20",
            limit_price="200.00",
            manual_live_acknowledgement=True,
        ),
        allow_live_execution=True,
    )

    response = service.place_manual_order(command)

    assert response.status == AdminApiCommandStatus.ACCEPTED
    assert response.live_exchange_submitted is True
    assert fake_rest_client.create_order_calls == [
        {
            "client_order_id": "client-admin-api-spot-sell-authority",
            "product_id": "BTC-USDC",
            "side": OrderSide.SELL.value,
            "order_configuration": {
                "limit_limit_gtc": {
                    "base_size": "0.2",
                    "limit_price": "200.00",
                    "post_only": False,
                }
            },
        }
    ]
    assert len(fake_publisher.events) == 1
    assert any("FROM stealth_orders" in query for query, _params in fake_db.queries)
    assert any("FROM fill_ledger" in query for query, _params in fake_db.queries)
