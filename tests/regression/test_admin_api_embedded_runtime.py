from __future__ import annotations

import asyncio
from pathlib import Path
from queue import Queue
import sys
from threading import Event, Lock
from types import SimpleNamespace

import pytest

import dashboard_server
from bridges.stealth_order_bridge import StealthOrderBridge
from application.admin_api.command_runtime import (
    AdminApiFillFollowUpRuntimeExecutor,
    get_admin_api_fill_follow_up_executor,
)
from application.admin_api.embedded_server import (
    DEFAULT_SHUTDOWN_TIMEOUT_SECONDS,
    EMBEDDED_ADMIN_API_ENABLED_ENV,
    EmbeddedAdminApiConfig,
    EmbeddedAdminApiReadinessGate,
    EmbeddedAdminApiStartupError,
    build_embedded_admin_api_config,
    prepare_embedded_admin_api_server,
)
from core.runtime_composition import (
    CanonicalOrderRuntime,
    build_canonical_order_runtime,
    hydrate_canonical_order_runtime,
)
from core.order_engine import OrderEngine
from core.runtime_controller import (
    INFLIGHT_FILL_PROCESSING,
    get_runtime_controller,
)


def _enabled_environment(**overrides: str) -> dict[str, str]:
    environment = {
        EMBEDDED_ADMIN_API_ENABLED_ENV: "true",
        "COINBASE_ADMIN_API_BEARER_TOKEN": "local-test-token",
    }
    environment.update(overrides)
    return environment


class _FakeUvicornServer:
    def __init__(self) -> None:
        self.started = False
        self.should_exit = False
        self.force_exit = False
        self.exited = Event()

    def run(self) -> None:
        self.started = True
        while not self.should_exit and not self.force_exit:
            self.exited.wait(0.01)
        self.exited.set()


@pytest.mark.regression
def test_canonical_runtime_composer_builds_one_wired_identity_after_schema():
    events: list[str] = []
    suppressed_source_ids: list[str] = []

    def suppression_checker(client_order_id: str) -> bool:
        suppressed_source_ids.append(client_order_id)
        return True

    suppression_acknowledger = lambda _client_order_id: True

    db_module = SimpleNamespace(
        DB_CLIENT=SimpleNamespace(),
        create_order_parent_table=lambda: events.append("schema:parent"),
        create_order_match_audit_table=lambda: events.append("schema:match"),
        create_order_moves_table=lambda: events.append("schema:moves"),
        create_order_follow_up_intent_tables=lambda: events.append(
            "schema:follow-up-intent"
        ),
    )
    manager = SimpleNamespace(profit_validator=None, fill_ledger_repo=None)

    def manager_factory(db_client):
        assert db_client is db_module.DB_CLIENT
        events.append("manager")
        return manager

    def bridge_factory(received_manager, received_engine):
        assert received_manager is manager
        assert received_engine is None
        events.append("bridge")
        return SimpleNamespace(
            stealth_manager=received_manager,
            order_engine=received_engine,
        )

    def engine_factory(**kwargs):
        events.append("engine")
        assert (
            kwargs["cancelled_follow_up_suppression_checker"]
            is suppression_checker
        )
        assert (
            kwargs["cancelled_follow_up_suppression_acknowledger"]
            is suppression_acknowledger
        )
        return SimpleNamespace(
            orderbook=kwargs["orderbook"],
            stealth_order_bridge=kwargs["stealth_order_bridge"],
            profit_validator=SimpleNamespace(),
            fill_repo=SimpleNamespace(),
        )

    orderbook = SimpleNamespace()
    runtime = build_canonical_order_runtime(
        orderbook=orderbook,
        db_module=db_module,
        subscription=SimpleNamespace(
            channels=[],
            retail_portfolio_id="11111111-2222-4333-8444-555555555555",
        ),
        api_key="test-key",
        api_secret="test-secret",
        order_post_only={"BUY": True, "SELL": True},
        stealth_order_manager_factory=manager_factory,
        stealth_order_bridge_factory=bridge_factory,
        order_engine_factory=engine_factory,
        cancelled_follow_up_suppression_checker=suppression_checker,
        cancelled_follow_up_suppression_acknowledger=(
            suppression_acknowledger
        ),
    )

    assert events == [
        "schema:parent",
        "schema:match",
        "schema:moves",
        "schema:follow-up-intent",
        "manager",
        "bridge",
        "engine",
    ]
    assert runtime.order_engine.orderbook is orderbook
    assert runtime.order_engine.stealth_order_bridge is runtime.stealth_order_bridge
    assert runtime.stealth_order_bridge.order_engine is runtime.order_engine
    assert runtime.stealth_order_bridge.stealth_manager is manager
    assert manager.profit_validator is runtime.order_engine.profit_validator
    assert manager.fill_ledger_repo is runtime.order_engine.fill_repo
    assert manager.expected_retail_portfolio_id == (
        "11111111-2222-4333-8444-555555555555"
    )
    assert suppressed_source_ids == []


@pytest.mark.regression
def test_canonical_runtime_hydration_is_strict_and_ordered():
    events: list[str] = []
    manager = SimpleNamespace(
        load_all_active_orders_from_db=lambda **kwargs: events.append(
            f"manager:{kwargs['raise_on_error']}"
        )
    )
    engine = SimpleNamespace(
        load_parent_child_order_ids=lambda **kwargs: events.append(
            f"links:{kwargs['force_log']}:{kwargs['raise_on_error']}"
        ),
        _hydrate_order_progress_tracker_from_db=lambda **kwargs: events.append(
            f"progress:{kwargs['raise_on_error']}"
        ),
    )

    hydrate_canonical_order_runtime(
        CanonicalOrderRuntime(
            order_engine=engine,
            stealth_order_bridge=SimpleNamespace(),
            stealth_order_manager=manager,
        )
    )

    assert events == ["manager:True", "links:True:True", "progress:True"]
    assert engine._canonical_state_strictly_hydrated is True


@pytest.mark.regression
def test_engine_startup_revalidates_prebound_hydration_strictly():
    events: list[str] = []
    engine = OrderEngine.__new__(OrderEngine)
    engine._canonical_state_strictly_hydrated = True
    engine.load_parent_child_order_ids = lambda **kwargs: events.append(
        f"links:{kwargs['force_log']}:{kwargs['raise_on_error']}"
    )
    engine._hydrate_order_progress_tracker_from_db = lambda **kwargs: events.append(
        f"progress:{kwargs['raise_on_error']}"
    )

    engine._hydrate_startup_order_state()

    assert events == ["links:True:True", "progress:True"]


@pytest.mark.regression
def test_canonical_runtime_hydration_fails_before_later_state_loads():
    def fail_manager_hydration(**_kwargs):
        raise RuntimeError("synthetic placement hydration failure")

    engine = SimpleNamespace(
        load_parent_child_order_ids=lambda **_kwargs: pytest.fail(
            "link hydration must not run after placement hydration failure"
        ),
        _hydrate_order_progress_tracker_from_db=lambda **_kwargs: pytest.fail(
            "progress hydration must not run after placement hydration failure"
        ),
    )

    with pytest.raises(RuntimeError, match="placement hydration failure"):
        hydrate_canonical_order_runtime(
            CanonicalOrderRuntime(
                order_engine=engine,
                stealth_order_bridge=SimpleNamespace(),
                stealth_order_manager=SimpleNamespace(
                    load_all_active_orders_from_db=fail_manager_hydration
                ),
            )
        )


@pytest.mark.regression
def test_strict_partial_progress_query_propagates_backend_failure(monkeypatch):
    import database.order as order_db

    def fail_query(*_args, **_kwargs):
        raise RuntimeError("synthetic partial progress read failure")

    monkeypatch.setattr(
        order_db,
        "DB_CLIENT",
        SimpleNamespace(execute_query=fail_query),
    )

    with pytest.raises(RuntimeError, match="partial progress read failure"):
        order_db.get_all_active_partial_fill_progress(raise_on_error=True)


@pytest.mark.regression
def test_embedded_admin_api_is_disabled_by_default():
    assert build_embedded_admin_api_config(environ={}) is None


@pytest.mark.regression
@pytest.mark.parametrize("disabled_value", ["0", "false", "no", "off"])
def test_embedded_admin_api_explicit_false_stays_disabled(disabled_value: str):
    assert (
        build_embedded_admin_api_config(
            environ={EMBEDDED_ADMIN_API_ENABLED_ENV: disabled_value}
        )
        is None
    )


@pytest.mark.regression
def test_embedded_admin_api_rejects_ambiguous_enablement():
    with pytest.raises(EmbeddedAdminApiStartupError, match="must be one of"):
        build_embedded_admin_api_config(
            environ={EMBEDDED_ADMIN_API_ENABLED_ENV: "sometimes"},
        )


@pytest.mark.regression
def test_embedded_admin_api_checks_auth_before_server_construction():
    server_factory_called = False

    def server_factory(_config, _app_gate):
        nonlocal server_factory_called
        server_factory_called = True
        return _FakeUvicornServer()

    with pytest.raises(
        EmbeddedAdminApiStartupError,
        match="COINBASE_ADMIN_API_BEARER_TOKEN is required",
    ):
        prepare_embedded_admin_api_server(
            order_engine=SimpleNamespace(handle_filled_order=lambda _order: None),
            stealth_order_bridge=SimpleNamespace(),
            stealth_order_manager=SimpleNamespace(),
            runtime_ready=True,
            environ={EMBEDDED_ADMIN_API_ENABLED_ENV: "true"},
            server_factory=server_factory,
        )

    assert server_factory_called is False


@pytest.mark.regression
def test_embedded_uvicorn_factory_is_single_process_and_bounded(monkeypatch):
    captured: dict[str, object] = {}

    class FakeConfig:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    class FakeServer:
        def __init__(self, config):
            self.config = config

    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        SimpleNamespace(Config=FakeConfig, Server=FakeServer),
    )
    from application.admin_api import embedded_server

    app_gate = EmbeddedAdminApiReadinessGate(
        lambda _scope, _receive, _send: None
    )
    server = embedded_server._build_uvicorn_server(
        EmbeddedAdminApiConfig(
            host="127.0.0.1",
            port=18787,
            graceful_shutdown_timeout_seconds=3.0,
        ),
        app_gate,
    )

    assert isinstance(server, FakeServer)
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 18787
    assert captured["workers"] == 1
    assert captured["reload"] is False
    assert captured["timeout_graceful_shutdown"] == 3.0
    assert captured["app"] is app_gate
    assert DEFAULT_SHUTDOWN_TIMEOUT_SECONDS > 30.0


@pytest.mark.regression
def test_embedded_readiness_gate_rejects_until_runtime_is_ready():
    delegated: list[bool] = []

    async def app(_scope, _receive, send):
        delegated.append(True)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    gate = EmbeddedAdminApiReadinessGate(app)

    async def request_once():
        messages: list[dict[str, object]] = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        await gate(
            {"type": "http", "method": "POST", "path": "/api/v1/orders"},
            receive,
            send,
        )
        return messages

    blocked_messages = asyncio.run(request_once())
    assert blocked_messages[0]["status"] == 503
    assert delegated == []

    gate.mark_runtime_ready()
    ready_messages = asyncio.run(request_once())
    assert ready_messages[0]["status"] == 204
    assert delegated == [True]


@pytest.mark.regression
def test_embedded_readiness_gate_revokes_mutations_when_monitoring_is_lost():
    delegated: list[bool] = []
    monitoring_ready = {"value": False}

    async def app(_scope, _receive, send):
        delegated.append(True)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    gate = EmbeddedAdminApiReadinessGate(
        app,
        mutation_readiness_check=lambda: monitoring_ready["value"],
    )
    gate.mark_runtime_ready()

    async def request_once():
        messages: list[dict[str, object]] = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        await gate(
            {"type": "http", "method": "POST", "path": "/api/v1/orders"},
            receive,
            send,
        )
        return messages

    assert asyncio.run(request_once())[0]["status"] == 503
    monitoring_ready["value"] = True
    assert asyncio.run(request_once())[0]["status"] == 204
    monitoring_ready["value"] = False
    assert asyncio.run(request_once())[0]["status"] == 503
    assert delegated == [True]


@pytest.mark.regression
def test_embedded_admin_api_uses_exact_registered_runtime_identity(monkeypatch):
    orderbook = SimpleNamespace(name="canonical-claim-authority")
    manager = SimpleNamespace(name="canonical-manager")
    engine = SimpleNamespace(
        orderbook=orderbook,
        handle_filled_order=lambda _order: None,
    )
    bridge = SimpleNamespace(order_engine=engine, stealth_manager=manager)
    engine.stealth_order_bridge = bridge
    fake_server = _FakeUvicornServer()
    monkeypatch.setattr(dashboard_server, "stealth_order_bridge", bridge)

    embedded = prepare_embedded_admin_api_server(
        order_engine=engine,
        stealth_order_bridge=bridge,
        stealth_order_manager=manager,
        runtime_ready=True,
        environ=_enabled_environment(),
        server_factory=lambda _config, _app_gate: fake_server,
        startup_timeout_seconds=0.5,
        shutdown_timeout_seconds=0.5,
    )

    assert embedded is not None
    executor = get_admin_api_fill_follow_up_executor()
    assert executor is not None
    assert executor.order_engine is engine
    assert executor.order_engine.orderbook is orderbook

    embedded.start()
    assert embedded.is_running is True
    assert embedded.runtime_ready is False
    embedded.mark_runtime_ready()
    assert embedded.runtime_ready is True
    embedded.start()

    embedded.stop()
    embedded.stop()
    assert fake_server.exited.wait(0.5) is True
    assert embedded.is_running is False


@pytest.mark.regression
@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("runtime_not_ready", "canonical engine runtime is not ready"),
        ("registered_bridge", "registered stealth bridge"),
        ("bridge_engine", "canonical order engine"),
        ("engine_bridge", "engine does not reference the canonical stealth bridge"),
        ("bridge_manager", "canonical stealth manager"),
    ],
)
def test_embedded_admin_api_rejects_runtime_identity_mismatch(
    monkeypatch,
    mutation: str,
    message: str,
):
    manager = SimpleNamespace()
    engine = SimpleNamespace(
        orderbook=SimpleNamespace(),
        handle_filled_order=lambda _order: None,
    )
    bridge = SimpleNamespace(order_engine=engine, stealth_manager=manager)
    engine.stealth_order_bridge = bridge
    monkeypatch.setattr(dashboard_server, "stealth_order_bridge", bridge)
    runtime_ready = True
    supplied_manager = manager
    supplied_bridge = bridge
    supplied_engine = engine

    if mutation == "runtime_not_ready":
        runtime_ready = False
    elif mutation == "registered_bridge":
        monkeypatch.setattr(dashboard_server, "stealth_order_bridge", SimpleNamespace())
    elif mutation == "bridge_engine":
        supplied_engine = SimpleNamespace(
            orderbook=SimpleNamespace(),
            handle_filled_order=lambda _order: None,
            stealth_order_bridge=bridge,
        )
    elif mutation == "engine_bridge":
        engine.stealth_order_bridge = SimpleNamespace()
    elif mutation == "bridge_manager":
        supplied_manager = SimpleNamespace()

    with pytest.raises(EmbeddedAdminApiStartupError, match=message):
        prepare_embedded_admin_api_server(
            order_engine=supplied_engine,
            stealth_order_bridge=supplied_bridge,
            stealth_order_manager=supplied_manager,
            runtime_ready=runtime_ready,
            environ=_enabled_environment(),
            server_factory=lambda _config, _app_gate: _FakeUvicornServer(),
        )


@pytest.mark.regression
def test_embedded_admin_api_surfaces_server_thread_failure(monkeypatch):
    class FailingServer(_FakeUvicornServer):
        def run(self) -> None:
            raise SystemExit(1)

    manager = SimpleNamespace()
    engine = SimpleNamespace(
        orderbook=SimpleNamespace(),
        handle_filled_order=lambda _order: None,
    )
    bridge = SimpleNamespace(order_engine=engine, stealth_manager=manager)
    engine.stealth_order_bridge = bridge
    monkeypatch.setattr(dashboard_server, "stealth_order_bridge", bridge)
    embedded = prepare_embedded_admin_api_server(
        order_engine=engine,
        stealth_order_bridge=bridge,
        stealth_order_manager=manager,
        runtime_ready=True,
        environ=_enabled_environment(),
        server_factory=lambda _config, _app_gate: FailingServer(),
        startup_timeout_seconds=0.2,
        shutdown_timeout_seconds=0.2,
    )
    assert embedded is not None

    with pytest.raises(EmbeddedAdminApiStartupError, match="failed before startup"):
        embedded.start()


@pytest.mark.regression
def test_embedded_admin_api_unexpected_exit_triggers_runtime_shutdown(monkeypatch):
    class ExitAfterStartServer(_FakeUvicornServer):
        def run(self) -> None:
            self.started = True

    manager = SimpleNamespace()
    engine = SimpleNamespace(
        orderbook=SimpleNamespace(),
        handle_filled_order=lambda _order: None,
    )
    bridge = SimpleNamespace(order_engine=engine, stealth_manager=manager)
    engine.stealth_order_bridge = bridge
    monkeypatch.setattr(dashboard_server, "stealth_order_bridge", bridge)
    unexpected_exit = Event()
    embedded = prepare_embedded_admin_api_server(
        order_engine=engine,
        stealth_order_bridge=bridge,
        stealth_order_manager=manager,
        runtime_ready=True,
        environ=_enabled_environment(),
        server_factory=lambda _config, _app_gate: ExitAfterStartServer(),
        unexpected_exit_callback=lambda _failure: unexpected_exit.set(),
        startup_timeout_seconds=0.2,
        shutdown_timeout_seconds=0.2,
    )
    assert embedded is not None

    try:
        embedded.start()
    except EmbeddedAdminApiStartupError:
        pass

    assert unexpected_exit.wait(0.5) is True


@pytest.mark.regression
def test_fill_follow_up_executor_tracks_inflight_processing():
    controller = get_runtime_controller()
    controller._reset_for_tests()
    observed: list[int] = []

    def handle_filled_order(_order):
        observed.append(
            controller.inflight_snapshot().get(INFLIGHT_FILL_PROCESSING, 0)
        )

    executor = AdminApiFillFollowUpRuntimeExecutor(
        SimpleNamespace(
            handle_filled_order=handle_filled_order,
            orderbook=SimpleNamespace(
                follow_up_claim_state=lambda _kind, _client_order_id: "done"
            ),
        )
    )

    executor.trigger_filled_follow_up(
        order={"client_order_id": "placed-1"},
        context={"audit_correlation_id": "audit-1"},
    )

    assert observed == [1]
    assert controller.inflight_snapshot() == {}


@pytest.mark.regression
def test_automatic_fill_handler_tracks_inflight_processing():
    controller = get_runtime_controller()
    controller._reset_for_tests()
    observed: list[int] = []
    engine = OrderEngine.__new__(OrderEngine)
    engine.handle_filled_order = lambda _order: observed.append(
        controller.inflight_snapshot().get(INFLIGHT_FILL_PROCESSING, 0)
    )

    engine._handle_filled_order_with_runtime_tracking(
        {"client_order_id": "placed-automatic-1"}
    )

    assert observed == [1]
    assert controller.inflight_snapshot() == {}


@pytest.mark.regression
def test_user_event_worker_drains_queued_fill_after_shutdown():
    controller = get_runtime_controller()
    controller._reset_for_tests()
    observed: list[int] = []
    engine = OrderEngine.__new__(OrderEngine)
    engine._shutdown_event = Event()
    engine._shutdown_event.set()
    engine._worker_queue_poll_seconds = 0.01
    engine._user_worker_drain_lock = Lock()
    engine._user_worker_drain_reserved = False
    engine.event_queue = {"user": Queue()}
    engine.event_queue["user"].put({"orders": []})
    engine.log_message = lambda *_args, **_kwargs: None
    engine.build_event_log_payload = lambda *_args, **_kwargs: {}
    engine.include_debug_fields = lambda **_kwargs: {}
    engine.process_user_event = lambda _event: observed.append(
        controller.inflight_snapshot().get(INFLIGHT_FILL_PROCESSING, 0)
    )

    engine._reserve_user_worker_drain()
    assert controller.inflight_snapshot()[INFLIGHT_FILL_PROCESSING] == 1
    worker = engine.generate_process_event_worker("user")
    worker()

    assert observed == [2]
    assert engine.event_queue["user"].empty()
    assert controller.inflight_snapshot() == {}
    source = Path("core/order_engine.py").read_text(encoding="utf-8-sig")
    assert "event_executor.submit(self.process_user_event" not in source


@pytest.mark.regression
def test_order_engine_monitoring_readiness_requires_authenticated_user_ack():
    engine = OrderEngine.__new__(OrderEngine)
    engine._websocket_monitoring_ready = Event()
    engine._websocket_monitoring_lock = Lock()
    engine._acknowledged_websocket_workers = set()
    engine.subscription = SimpleNamespace(
        channels=["heartbeats", "user"],
        product_ids=["BTC-USDC"],
    )
    engine._event_worker_threads = {
        "user": SimpleNamespace(is_alive=lambda: True),
    }
    engine._websocket_worker_threads = {
        "ws-0": SimpleNamespace(is_alive=lambda: True),
    }
    engine._websocket_worker_products = {"ws-0": ("BTC-USDC",)}
    engine._websocket_worker_channels = {"ws-0": ("heartbeats", "user")}
    engine._websocket_worker_transports = {"ws-0": lambda: True}

    assert engine.wait_for_event_monitoring_ready(timeout_seconds=0.01) is False
    assert engine._record_user_subscription_ack(
        {
            "channel": "subscriptions",
            "events": [
                {"subscriptions": {"heartbeats": ["heartbeats"]}}
            ],
        },
        websocket_worker_token="ws-0",
    ) is False
    assert engine.wait_for_event_monitoring_ready(timeout_seconds=0.01) is False
    assert engine._record_user_subscription_ack(
        {
            "channel": "subscriptions",
            "events": [
                {
                    "subscriptions": {
                        "heartbeats": ["heartbeats"],
                        "user": ["portfolio-1"],
                    }
                }
            ],
        },
        websocket_worker_token="ws-0",
    ) is True
    assert engine.wait_for_event_monitoring_ready(timeout_seconds=0.01) is True
    assert engine.is_event_monitoring_ready() is True

    engine._mark_websocket_worker_inactive("ws-0")
    assert engine.is_event_monitoring_ready() is False
    assert engine.wait_for_event_monitoring_ready(timeout_seconds=0.01) is False

    source = Path("core/order_engine.py").read_text(encoding="utf-8-sig")
    subscribe = source.index("ws_client.subscribe(")
    loop = source.index("while not self._shutdown_event.is_set()", subscribe)
    assert "self._websocket_monitoring_ready.set()" not in source[subscribe:loop]


@pytest.mark.regression
def test_order_engine_monitoring_readiness_rejects_dead_user_worker():
    engine = OrderEngine.__new__(OrderEngine)
    engine._websocket_monitoring_ready = Event()
    engine._websocket_monitoring_lock = Lock()
    engine._acknowledged_websocket_workers = set()
    engine.subscription = SimpleNamespace(
        channels=["user"],
        product_ids=["BTC-USDC"],
    )
    engine._event_worker_threads = {
        "user": SimpleNamespace(is_alive=lambda: False),
    }
    engine._websocket_worker_threads = {
        "ws-0": SimpleNamespace(is_alive=lambda: True),
    }
    engine._websocket_worker_products = {"ws-0": ("BTC-USDC",)}
    engine._websocket_worker_channels = {"ws-0": ("user",)}
    engine._websocket_worker_transports = {"ws-0": lambda: True}

    assert engine._record_user_subscription_ack(
        {
            "channel": "subscriptions",
            "events": [
                {"subscriptions": {"user": ["portfolio-1"]}}
            ],
        },
        websocket_worker_token="ws-0",
    ) is False
    assert engine.wait_for_event_monitoring_ready(timeout_seconds=0.01) is False


@pytest.mark.regression
def test_order_engine_monitoring_readiness_revokes_when_user_worker_exits():
    controller = get_runtime_controller()
    controller._reset_for_tests()
    lost: list[str] = []
    engine = OrderEngine.__new__(OrderEngine)
    engine._shutdown_event = Event()
    engine._websocket_monitoring_ready = Event()
    engine._websocket_monitoring_ready.set()
    engine._websocket_monitoring_lock = Lock()
    engine._acknowledged_websocket_workers = {"ws-0"}
    engine._event_worker_threads = {
        "user": SimpleNamespace(is_alive=lambda: False),
    }
    engine._websocket_worker_threads = {
        "ws-0": SimpleNamespace(is_alive=lambda: True),
    }
    engine._event_monitoring_lost_callback = lambda: lost.append("lost")
    engine._event_monitoring_loss_reported = False

    assert engine.is_event_monitoring_ready() is False
    assert engine.wait_for_event_monitoring_ready(timeout_seconds=0.01) is False
    assert lost == ["lost"]
    controller._reset_for_tests()


@pytest.mark.regression
def test_order_engine_monitoring_readiness_revokes_when_transport_closes():
    controller = get_runtime_controller()
    controller._reset_for_tests()
    transport_open = {"value": True}
    lost: list[str] = []
    engine = OrderEngine.__new__(OrderEngine)
    engine._shutdown_event = Event()
    engine._websocket_monitoring_ready = Event()
    engine._websocket_monitoring_lock = Lock()
    engine._acknowledged_websocket_workers = set()
    engine.subscription = SimpleNamespace(
        channels=["user"],
        product_ids=["BTC-USDC"],
    )
    engine._event_worker_threads = {
        "user": SimpleNamespace(is_alive=lambda: True),
    }
    engine._websocket_worker_threads = {
        "ws-0": SimpleNamespace(is_alive=lambda: True),
    }
    engine._websocket_worker_products = {"ws-0": ("BTC-USDC",)}
    engine._websocket_worker_channels = {"ws-0": ("user",)}
    engine._websocket_worker_transports = {
        "ws-0": lambda: transport_open["value"],
    }
    engine._event_monitoring_lost_callback = lambda: lost.append("lost")
    engine._event_monitoring_loss_reported = False

    assert engine._record_user_subscription_ack(
        {
            "channel": "subscriptions",
            "events": [
                {"subscriptions": {"user": ["portfolio-1"]}}
            ],
        },
        websocket_worker_token="ws-0",
    ) is True
    assert engine.is_event_monitoring_ready() is True

    transport_open["value"] = False
    assert engine.is_event_monitoring_ready() is False
    assert engine.wait_for_event_monitoring_ready(timeout_seconds=0.01) is False
    assert lost == ["lost"]
    controller._reset_for_tests()


@pytest.mark.regression
def test_last_acknowledged_websocket_exit_triggers_fail_closed_callback():
    controller = get_runtime_controller()
    controller._reset_for_tests()
    lost: list[str] = []
    engine = OrderEngine.__new__(OrderEngine)
    engine._shutdown_event = Event()
    engine._websocket_monitoring_ready = Event()
    engine._websocket_monitoring_ready.set()
    engine._websocket_monitoring_lock = Lock()
    engine._acknowledged_websocket_workers = {"ws-0"}
    engine._websocket_worker_threads = {
        "ws-0": SimpleNamespace(is_alive=lambda: True),
    }
    engine._websocket_worker_products = {"ws-0": ("BTC-USDC",)}
    engine._websocket_worker_channels = {"ws-0": ("user",)}
    engine._websocket_worker_transports = {"ws-0": lambda: False}
    engine._event_monitoring_lost_callback = lambda: lost.append("lost")
    engine._event_monitoring_loss_reported = False

    engine._mark_websocket_worker_inactive("ws-0")

    assert lost == ["lost"]
    assert engine._websocket_monitoring_ready.is_set() is False
    controller._reset_for_tests()


@pytest.mark.regression
def test_intentional_shutdown_does_not_report_monitoring_loss():
    controller = get_runtime_controller()
    controller._reset_for_tests()
    controller.request_shutdown()
    lost: list[str] = []
    engine = OrderEngine.__new__(OrderEngine)
    engine._shutdown_event = Event()
    engine._websocket_monitoring_ready = Event()
    engine._websocket_monitoring_ready.set()
    engine._websocket_monitoring_lock = Lock()
    engine._acknowledged_websocket_workers = {"ws-0"}
    engine._websocket_worker_threads = {
        "ws-0": SimpleNamespace(is_alive=lambda: True),
    }
    engine._websocket_worker_products = {"ws-0": ("BTC-USDC",)}
    engine._websocket_worker_channels = {"ws-0": ("user",)}
    engine._websocket_worker_transports = {"ws-0": lambda: False}
    engine._event_monitoring_lost_callback = lambda: lost.append("lost")
    engine._event_monitoring_loss_reported = False

    engine._mark_websocket_worker_inactive("ws-0")

    assert lost == []
    controller._reset_for_tests()


@pytest.mark.regression
def test_websocket_ack_correlates_exact_outbound_subscription(monkeypatch):
    import core.order_engine as order_engine_module

    engine = OrderEngine.__new__(OrderEngine)
    engine.api_key = "test-key"
    engine.api_secret = "test-secret"
    engine._shutdown_event = Event()
    engine._shutdown_event.set()
    engine._websocket_monitoring_ready = Event()
    engine._websocket_monitoring_lock = Lock()
    engine._acknowledged_websocket_workers = set()
    engine._event_worker_threads = {
        "user": SimpleNamespace(is_alive=lambda: True),
    }
    engine._websocket_worker_threads = {
        "ws-0": SimpleNamespace(is_alive=lambda: True),
    }
    engine._websocket_worker_products = {
        "ws-0": ("BTC-USDC", "ETH-USDC"),
    }
    engine._websocket_worker_channels = {
        "ws-0": ("heartbeats", "user"),
    }
    engine._websocket_worker_transports = {}
    engine.subscription = SimpleNamespace(
        product_ids=["MUTATED-USDC"],
        channels=["ticker"],
    )
    observed: dict[str, object] = {}

    class FakeSdkClient:
        def __init__(self, **kwargs):
            self.on_message = kwargs["on_message"]
            self.open = False
            observed["sdk_retry"] = kwargs["retry"]

        def _is_websocket_open(self):
            return self.open

    class FakeWebSocketClient:
        def __init__(self, sdk_client):
            self.sdk_client = sdk_client

        def connect(self):
            self.sdk_client.open = True
            observed["connected"] = True

        def subscribe(self, *, products, channels):
            observed["products"] = products
            observed["channels"] = channels
            self.sdk_client.on_message(
                '{"channel":"subscriptions","events":['
                '{"subscriptions":{"user":["portfolio-1"]}}]}'
            )
            observed["ready_during_connection"] = (
                engine.is_event_monitoring_ready()
            )

    monkeypatch.setattr(order_engine_module, "WSClient", FakeSdkClient)
    monkeypatch.setattr(
        order_engine_module,
        "CoinbaseWebSocketClient",
        FakeWebSocketClient,
    )

    engine.connect_to_websocket(
        websocket_worker_token="ws-0",
        subscribed_products=("BTC-USDC", "ETH-USDC"),
        subscribed_channels=("heartbeats", "user"),
    )

    assert observed == {
        "sdk_retry": False,
        "connected": True,
        "products": ["BTC-USDC", "ETH-USDC"],
        "channels": ["heartbeats", "user"],
        "ready_during_connection": True,
    }
    assert engine.is_event_monitoring_ready() is False


@pytest.mark.regression
def test_ticker_policy_mutations_stop_when_runtime_is_draining():
    controller = get_runtime_controller()
    controller._reset_for_tests()
    controller.request_shutdown()
    calls: list[str] = []
    bridge = StealthOrderBridge.__new__(StealthOrderBridge)
    bridge._update_market_cache = lambda *_args: calls.append("cache")
    bridge.stealth_manager = SimpleNamespace(
        process_cancel_reentry_for_product=lambda _product_id: calls.append(
            "cancel_reentry"
        ),
        process_anchor_repricing_for_product=lambda _product_id: calls.append(
            "anchor_reprice"
        ),
    )

    bridge.process_ticker_update(
        "BTC-USD",
        {
            "price": "100",
            "best_bid": "99",
            "best_ask": "101",
            "volume_24_h": "1440",
        },
    )

    assert calls == ["cache"]
    controller._reset_for_tests()


@pytest.mark.regression
def test_main_binds_embedded_api_before_starting_live_producers():
    source = Path("main.py").read_text(encoding="utf-8-sig")

    association = source.index("set_stealth_order_bridge(stealth_bridge)")
    hydration = source.index("hydrate_canonical_order_runtime(runtime)")
    preparation = source.index(
        "embedded_admin_api_server = prepare_embedded_admin_api_server("
    )
    reconciliation = source.index("run_startup_reconciliation(")
    api_start = source.index("embedded_admin_api_server.start()")
    bridge_start = source.index("stealth_bridge.start()", api_start)
    api_stop = source.index(
        'controller.register_stop_hook("admin_api", embedded_admin_api_server.stop)'
    )
    bridge_stop = source.index('"stealth_bridge", stealth_bridge.stop')
    engine_stop = source.index('controller.register_stop_hook("order_engine", engine.stop)')
    hotpoint_disable = source.index("engine.set_hotpoint_auto_place_enabled(False)")
    monitoring = source.index("engine.wait_for_event_monitoring_ready(", api_start)
    mark_ready = source.index("embedded_admin_api_server.mark_runtime_ready()", monitoring)
    monitoring_loss_callback = source.index(
        "def handle_embedded_event_monitoring_lost()"
    )
    monitoring_loss_shutdown = source.index(
        "controller.request_shutdown()",
        monitoring_loss_callback,
    )
    monitoring_loss_drain_thread = source.index(
        "Thread(",
        monitoring_loss_shutdown,
    )
    run_forever = source.index(
        "engine.run_forever(on_started=mark_embedded_admin_api_runtime_ready)",
        api_start,
    )

    assert association < hotpoint_disable < hydration < preparation < reconciliation < api_start
    assert api_start < monitoring < bridge_start < mark_ready < run_forever
    assert (
        monitoring_loss_callback
        < monitoring_loss_shutdown
        < monitoring_loss_drain_thread
    )
    assert preparation < api_stop < bridge_stop < engine_stop
    assert "periodic_reconciler.start()" in source[:run_forever]
    assert "controller.drain_and_stop" in source
    assert "embedded_admin_api_server.stop()" in source[run_forever:]


@pytest.mark.regression
def test_main_embedded_runtime_fails_closed_without_clean_startup_reconciliation():
    source = Path("main.py").read_text(encoding="utf-8-sig")

    assert "startup_reconciliation_report = run_startup_reconciliation(" in source
    assert "fail_on_drift=embedded_admin_api_requested" in source
    assert "and startup_reconciliation_report is None" in source
    assert "Embedded Admin API requires successful startup reconciliation" in source


@pytest.mark.regression
def test_main_embedded_spot_runtime_requires_test_profile_before_composition():
    source = Path("main.py").read_text(encoding="utf-8-sig")

    portfolio_binding = source.index("require_spot_test_portfolio_binding(")
    runtime_composition = source.index("runtime = build_canonical_order_runtime(")
    reconciliation = source.index("run_startup_reconciliation(")

    assert portfolio_binding < runtime_composition < reconciliation
    assert "expected_portfolio_id=os.environ.get(SPOT_PORTFOLIO_ID_ENV)" in source
    assert "rest_client=get_rest_client()" in source
    assert "subscription=embedded_runtime_subscription" in source
    assert "product_ids = spot_product_ids" in source
    assert "derivatives_product_ids = []" in source
    assert '"futures_balance_summary"' in source
    parent_move_runtime_initialization = source.index(
        "initialize_operator_parent_move_premark_runtime()"
    )
    suppression_binding = source.index(
        "get_default_operator_parent_move_premark_goal_repository()"
    )
    assert (
        parent_move_runtime_initialization
        < suppression_binding
        < runtime_composition
    )
    assert (
        "COINBASE_ADMIN_API_OPERATOR_PARENT_MOVE_PREMARK_ENABLED"
        not in source[
            parent_move_runtime_initialization:runtime_composition
        ]
    )
    assert (
        "cancelled_follow_up_suppression_checker=("
        in source[runtime_composition:]
    )
    assert (
        "cancelled_follow_up_suppression_acknowledger=("
        in source[runtime_composition:]
    )


@pytest.mark.regression
def test_standalone_admin_api_remains_fail_closed_without_process_local_engine(
    monkeypatch,
):
    monkeypatch.setattr(dashboard_server, "stealth_order_bridge", None)

    assert get_admin_api_fill_follow_up_executor() is None


@pytest.mark.regression
def test_embedded_server_does_not_construct_or_enable_trading_paths():
    from application.admin_api import embedded_server

    source = Path(embedded_server.__file__).read_text(encoding="utf-8")

    assert "OrderEngine(" not in source
    assert "start_dashboard_server" not in source
    assert "handle_client_message" not in source
    assert "CoinbaseRestClient" not in source
    assert ".create_order(" not in source
    assert ".place_limit_order(" not in source
    assert "COINBASE_ADMIN_API_LIVE_EXECUTION_ENABLED" not in source
    assert "COINBASE_ADMIN_API_LIVE_COINBASE_EXECUTION_ENABLED" not in source
