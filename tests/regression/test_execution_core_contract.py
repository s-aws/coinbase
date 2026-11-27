"""Contract coverage for the transport-neutral execution boundary."""

from dataclasses import FrozenInstanceError
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main
from bridges.stealth_order_bridge import StealthOrderBridge
from core.enums import EngineState, StealthOrderStatus
from core.execution_core import (
    ExecutionCore,
    RuntimeStatusSnapshot,
    RuntimeTransitionResult,
)
from core.stealth_order_manager import StealthOrderManager


pytestmark = pytest.mark.regression

ROOT_CLIENT_ORDER_ID = "6ea0b885-84b6-49ca-b7be-dfea7e0659d3"
SECOND_CLIENT_ORDER_ID = "5d5d24ee-6aec-4d5a-b6ba-1bc1f5696946"
PLACEMENT_CLIENT_ORDER_ID = "900f4219-657c-4a89-b7fc-305cf1926836"


class _RuntimeLifecycleStub:
    def __init__(self) -> None:
        self.state = EngineState.RUNNING

    def lifecycle_snapshot(self) -> tuple[EngineState, bool, bool]:
        return (
            self.state,
            self.state is EngineState.RUNNING,
            self.state in {EngineState.DRAINING, EngineState.STOPPED},
        )

    def request_pause(self) -> bool:
        if self.state is not EngineState.RUNNING:
            return False
        self.state = EngineState.PAUSED
        return True

    def resume(self) -> bool:
        if self.state is not EngineState.PAUSED:
            return False
        self.state = EngineState.RUNNING
        return True


def _manager_with_nested_orders() -> StealthOrderManager:
    manager = object.__new__(StealthOrderManager)
    manager.in_memory_orders = {
        ROOT_CLIENT_ORDER_ID: {
            "stealth_order_id": ROOT_CLIENT_ORDER_ID,
            "status": StealthOrderStatus.HIDDEN.value,
            "product_id": "BTC-USD",
            "created_at": datetime(2026, 11, 27, 1, 2, 3),
            "reveal_condition_json": {
                "type": "price_threshold",
                "price_threshold": 90_000.0,
            },
            "sizing_strategy_json": {
                "type": "fixed",
                "steps": [0.1, 0.2],
            },
            "revealed_orders": [
                {
                    "client_order_id": PLACEMENT_CLIENT_ORDER_ID,
                    "metadata": {"attempt": 1},
                }
            ],
        },
        SECOND_CLIENT_ORDER_ID: {
            "stealth_order_id": SECOND_CLIENT_ORDER_ID,
            "status": StealthOrderStatus.EXECUTED.value,
            "product_id": "ETH-USD",
            "reveal_condition_json": {"type": "immediate"},
            "revealed_orders": [],
        },
    }
    return manager


def _bridge_for(manager: StealthOrderManager) -> StealthOrderBridge:
    bridge = object.__new__(StealthOrderBridge)
    bridge.stealth_manager = manager
    return bridge


def test_runtime_admin_commands_return_immutable_typed_results() -> None:
    runtime = _RuntimeLifecycleStub()
    execution_core = ExecutionCore(
        runtime_controller=runtime,
        stealth_orders=_bridge_for(_manager_with_nested_orders()),
    )

    initial = execution_core.runtime_status()
    paused = execution_core.pause_runtime()
    duplicate_pause = execution_core.pause_runtime()
    resumed = execution_core.resume_runtime()

    assert initial == RuntimeStatusSnapshot(
        state=EngineState.RUNNING,
        is_admitting=True,
        is_stopping=False,
    )
    assert paused == RuntimeTransitionResult(
        accepted=True,
        runtime=RuntimeStatusSnapshot(
            state=EngineState.PAUSED,
            is_admitting=False,
            is_stopping=False,
        ),
    )
    assert duplicate_pause.accepted is False
    assert duplicate_pause.runtime.state is EngineState.PAUSED
    assert resumed.accepted is True
    assert resumed.runtime.state is EngineState.RUNNING

    with pytest.raises(FrozenInstanceError):
        paused.accepted = False


def test_stealth_query_is_enum_filtered_and_deeply_detached() -> None:
    manager = _manager_with_nested_orders()
    execution_core = ExecutionCore(
        runtime_controller=_RuntimeLifecycleStub(),
        stealth_orders=_bridge_for(manager),
    )

    hidden = execution_core.snapshot_stealth_orders(
        StealthOrderStatus.HIDDEN
    )

    assert set(hidden) == {ROOT_CLIENT_ORDER_ID}
    assert hidden[ROOT_CLIENT_ORDER_ID]["stealth_order_id"] == (
        ROOT_CLIENT_ORDER_ID
    )

    hidden[ROOT_CLIENT_ORDER_ID]["reveal_condition_json"][
        "price_threshold"
    ] = 1.0
    hidden[ROOT_CLIENT_ORDER_ID]["sizing_strategy_json"]["steps"].append(
        0.3
    )
    hidden[ROOT_CLIENT_ORDER_ID]["revealed_orders"][0]["metadata"][
        "attempt"
    ] = 99

    authoritative = manager.in_memory_orders[ROOT_CLIENT_ORDER_ID]
    assert authoritative["reveal_condition_json"]["price_threshold"] == (
        90_000.0
    )
    assert authoritative["sizing_strategy_json"]["steps"] == [0.1, 0.2]
    assert authoritative["revealed_orders"][0]["metadata"]["attempt"] == 1

    with pytest.raises(TypeError, match="StealthOrderStatus"):
        execution_core.snapshot_stealth_orders("HIDDEN")


def test_serializable_orders_are_detached_from_authoritative_state() -> None:
    manager = _manager_with_nested_orders()

    serialized = manager.get_serializable_orders()

    assert serialized[ROOT_CLIENT_ORDER_ID]["created_at"] == (
        "2026-11-27T01:02:03"
    )
    serialized[ROOT_CLIENT_ORDER_ID]["reveal_condition_json"][
        "price_threshold"
    ] = 1.0
    serialized[ROOT_CLIENT_ORDER_ID]["revealed_orders"][0]["metadata"][
        "attempt"
    ] = 99

    authoritative = manager.in_memory_orders[ROOT_CLIENT_ORDER_ID]
    assert authoritative["reveal_condition_json"]["price_threshold"] == (
        90_000.0
    )
    assert authoritative["revealed_orders"][0]["metadata"]["attempt"] == 1


def test_main_composes_one_execution_core_from_existing_owners(
    monkeypatch,
) -> None:
    rest_client = object()
    db_client = object()
    orderbook = Mock(name="orderbook")
    manager = Mock(name="stealth_manager")
    bridge = Mock(name="stealth_bridge")
    engine = Mock(name="engine")
    engine.profit_validator = object()
    controller = Mock(name="runtime_controller")
    execution_core = object()
    execution_core_factory = Mock(
        name="ExecutionCore",
        return_value=execution_core,
    )
    configure_dashboard = Mock(name="configure_runtime_dependencies")
    subscription = object()
    subscription_type = Mock(name="Subscription")
    subscription_type.from_products.return_value = subscription

    settings = SimpleNamespace(
        api_key="test-key",
        api_secret="test-secret",
        products=SimpleNamespace(ticker_to_trading={}),
        order_post_only=True,
        dashboard_state_publish_interval_seconds=1.0,
    )

    monkeypatch.setattr(main, "build_rest_client", Mock(return_value=rest_client))
    monkeypatch.setattr(main, "order_db", SimpleNamespace(DB_CLIENT=db_client))
    monkeypatch.setattr(main, "_load_startup_products", Mock(return_value={}))
    monkeypatch.setattr(main, "_load_startup_positions", Mock(return_value={}))
    monkeypatch.setattr(main, "OrderBook", Mock(return_value=orderbook))
    monkeypatch.setattr(
        main,
        "get_global_placement_hook_registry",
        Mock(return_value=object()),
    )
    monkeypatch.setattr(
        main,
        "StealthOrderManager",
        Mock(return_value=manager),
    )
    monkeypatch.setattr(
        main,
        "StealthOrderBridge",
        Mock(return_value=bridge),
    )
    monkeypatch.setattr(main, "OrderEngine", Mock(return_value=engine))
    monkeypatch.setattr(main, "Subscription", subscription_type)
    monkeypatch.setattr(
        main,
        "get_runtime_controller",
        Mock(return_value=controller),
    )
    monkeypatch.setattr(main, "ExecutionCore", execution_core_factory)
    monkeypatch.setattr(
        main,
        "configure_runtime_dependencies",
        configure_dashboard,
    )

    runtime = main.build_application_runtime(settings)

    execution_core_factory.assert_called_once_with(
        runtime_controller=controller,
        stealth_orders=bridge,
    )
    assert runtime.execution_core is execution_core
    assert runtime.controller is controller
    assert runtime.stealth_bridge is bridge
    assert bridge.order_engine is engine
    assert manager.profit_validator is engine.profit_validator
    configure_dashboard.assert_called_once_with(
        orderbook=orderbook,
        state_publish_interval_seconds=1.0,
    )
