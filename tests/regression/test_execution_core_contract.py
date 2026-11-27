"""Contract coverage for the transport-neutral execution boundary."""

from dataclasses import FrozenInstanceError
from datetime import datetime
from contextlib import contextmanager
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main
from bridges.stealth_order_bridge import StealthOrderBridge
from core.enums import (
    EngineState,
    OrderSide,
    StealthMoveReason,
    StealthOrderStatus,
    TargetMovementType,
)
from core.execution_core import (
    CreateStealthOrderRequest,
    CreateStealthOrderSpanRequest,
    ExecutionCore,
    ImportStealthOrdersRequest,
    MoveRevealedStealthOrderRequest,
    RehideStealthOrderRequest,
    RepriceStealthOrderRequest,
    RuntimeStatusSnapshot,
    RuntimeTransitionResult,
)
from core.models import StealthMoveResult
from core.runtime_controller import (
    INFLIGHT_APPLICATION_COMMAND,
    RuntimeController,
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

    @contextmanager
    def track_admitted_inflight(self, _category: str):
        if self.state is not EngineState.RUNNING:
            from core.runtime_controller import EngineNotAdmittingError

            raise EngineNotAdmittingError(self.state, _category)
        yield


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
        stealth_commands=_bridge_for(_manager_with_nested_orders()),
        stealth_queries=_bridge_for(_manager_with_nested_orders()),
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
        stealth_commands=_bridge_for(manager),
        stealth_queries=_bridge_for(manager),
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
        stealth_commands=bridge,
        stealth_queries=bridge,
    )
    assert runtime.execution_core is execution_core
    assert runtime.controller is controller
    assert runtime.stealth_bridge is bridge
    assert bridge.order_engine is engine
    assert manager.profit_validator is engine.profit_validator
    configure_dashboard.assert_called_once_with(
        orderbook=orderbook,
        execution_core=execution_core,
        state_publish_interval_seconds=1.0,
    )


def _originating_command_cases():
    create_request = CreateStealthOrderRequest(
        client_order_id=ROOT_CLIENT_ORDER_ID,
        product_id="BTC-USD",
        side=OrderSide.BUY,
        total_size=1.0,
        limit_price=100.0,
        reveal_condition={"type": "time_delay", "delay_seconds": 0},
    )
    return (
        (
            "create_stealth_order",
            lambda core: core.create_stealth_order(create_request),
        ),
        (
            "create_stealth_order_span",
            lambda core: core.create_stealth_order_span(
                CreateStealthOrderSpanRequest(span={"span_id": "span-1"})
            ),
        ),
        (
            "create_stealth_order",
            lambda core: core.import_stealth_orders(
                ImportStealthOrdersRequest(orders=(create_request,))
            ),
        ),
        (
            "rehide_stealth_order",
            lambda core: core.rehide_stealth_order(
                RehideStealthOrderRequest(
                    client_order_id=ROOT_CLIENT_ORDER_ID
                )
            ),
        ),
        (
            "reprice_stealth_order_now",
            lambda core: core.reprice_stealth_order_now(
                RepriceStealthOrderRequest(
                    client_order_id=ROOT_CLIENT_ORDER_ID
                )
            ),
        ),
        (
            "move_revealed_stealth_order",
            lambda core: core.move_revealed_stealth_order(
                MoveRevealedStealthOrderRequest(
                    client_order_id=ROOT_CLIENT_ORDER_ID,
                    new_limit_price=101.0,
                    new_target_movement=0.003,
                    new_target_movement_type=TargetMovementType.PERCENTAGE,
                    reason=StealthMoveReason.MANUAL_USER_MOVE,
                )
            ),
        ),
    )


def _command_port() -> Mock:
    commands = Mock(name="stealth_commands")
    commands.create_stealth_order.return_value = ROOT_CLIENT_ORDER_ID
    commands.create_stealth_order_span.return_value = {
        "span_id": "span-1",
        "status": "success",
    }
    commands.rehide_stealth_order.return_value = True
    commands.reprice_stealth_order_now.return_value = 1
    commands.move_revealed_stealth_order.return_value = (
        SimpleNamespace(
            old_exchange_order_id="exchange-old",
            new_configured_limit_price=101.0,
        ),
        StealthMoveResult(
            new_placement_client_order_id=PLACEMENT_CLIENT_ORDER_ID,
            new_exchange_order_id="exchange-new",
            new_submitted_price=101.0,
        ),
    )
    return commands


def _running_execution_core(
    commands: Mock,
) -> tuple[RuntimeController, ExecutionCore]:
    controller = RuntimeController()
    assert controller.complete_startup() is True
    return controller, ExecutionCore(
        runtime_controller=controller,
        stealth_commands=commands,
        stealth_queries=Mock(name="stealth_queries"),
    )


@pytest.mark.parametrize(
    ("delegate_name", "invoke"),
    _originating_command_cases(),
)
@pytest.mark.parametrize("transition", ("pause", "shutdown"))
def test_lifecycle_transition_wins_before_every_originating_command(
    delegate_name,
    invoke,
    transition,
) -> None:
    commands = _command_port()
    controller, execution_core = _running_execution_core(commands)

    if transition == "pause":
        assert controller.request_pause() is True
        expected_state = EngineState.PAUSED
    else:
        assert controller.request_shutdown() is True
        expected_state = EngineState.DRAINING

    outcome = invoke(execution_core)

    assert outcome.admitted is False
    assert outcome.rejection is not None
    assert outcome.rejection.state is expected_state
    assert outcome.rejection.category == INFLIGHT_APPLICATION_COMMAND
    getattr(commands, delegate_name).assert_not_called()
    assert controller.total_inflight() == 0


@pytest.mark.parametrize(
    ("delegate_name", "invoke"),
    _originating_command_cases(),
)
def test_every_originating_command_may_finish_when_admission_wins(
    delegate_name,
    invoke,
) -> None:
    commands = _command_port()
    controller, execution_core = _running_execution_core(commands)
    entered = threading.Event()
    release = threading.Event()
    original = getattr(commands, delegate_name).return_value

    def block(*_args, **_kwargs):
        entered.set()
        assert release.wait(timeout=2.0)
        return original

    getattr(commands, delegate_name).side_effect = block
    captured = {}

    def run_command() -> None:
        try:
            captured["outcome"] = invoke(execution_core)
        except BaseException as exc:  # preserve worker evidence for assertion
            captured["error"] = exc

    worker = threading.Thread(target=run_command)
    worker.start()
    assert entered.wait(timeout=2.0)
    assert controller.inflight_snapshot() == {
        INFLIGHT_APPLICATION_COMMAND: 1
    }

    assert controller.request_pause() is True
    assert controller.state is EngineState.PAUSED
    assert controller.inflight_snapshot() == {
        INFLIGHT_APPLICATION_COMMAND: 1
    }

    release.set()
    worker.join(timeout=2.0)

    assert worker.is_alive() is False
    assert "error" not in captured
    assert captured["outcome"].admitted is True
    assert controller.total_inflight() == 0


def test_shutdown_drain_waits_for_an_admitted_application_command() -> None:
    commands = _command_port()
    controller, execution_core = _running_execution_core(commands)
    entered = threading.Event()
    release = threading.Event()

    def block_create(*_args, **_kwargs):
        entered.set()
        assert release.wait(timeout=2.0)
        return ROOT_CLIENT_ORDER_ID

    commands.create_stealth_order.side_effect = block_create
    request = _originating_command_cases()[0][1]
    command_thread = threading.Thread(
        target=lambda: request(execution_core)
    )
    command_thread.start()
    assert entered.wait(timeout=2.0)

    assert controller.request_shutdown() is True
    drain_result = {}
    drain_thread = threading.Thread(
        target=lambda: drain_result.setdefault(
            "value",
            controller.drain_and_stop(timeout_seconds=2.0),
        )
    )
    drain_thread.start()
    drain_thread.join(timeout=0.05)

    assert drain_thread.is_alive() is True
    assert controller.inflight_snapshot() == {
        INFLIGHT_APPLICATION_COMMAND: 1
    }

    release.set()
    command_thread.join(timeout=2.0)
    drain_thread.join(timeout=2.0)

    assert command_thread.is_alive() is False
    assert drain_thread.is_alive() is False
    assert drain_result["value"].drained_clean is True
    assert controller.state is EngineState.STOPPED
    assert controller.total_inflight() == 0


def test_originating_exception_releases_application_inflight_count() -> None:
    commands = _command_port()
    commands.create_stealth_order.side_effect = ValueError("forced failure")
    controller, execution_core = _running_execution_core(commands)
    invoke = _originating_command_cases()[0][1]

    with pytest.raises(ValueError, match="forced failure"):
        invoke(execution_core)

    assert controller.total_inflight() == 0
