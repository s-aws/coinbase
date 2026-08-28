"""Fail-closed startup ordering for stealth decision activation."""

import threading

from unittest.mock import Mock, patch

import pytest

import configuration
import main
import core.order_engine as order_engine_module
from core import startup_reconciler
from core.enums import EngineState
from core.runtime_controller import RuntimeController


pytestmark = pytest.mark.regression


def _bare_order_engine() -> main.OrderEngine:
    """Build only the lifecycle surface needed by deterministic race tests."""

    engine = object.__new__(main.OrderEngine)
    engine._lifecycle_lock = threading.RLock()
    engine._startup_claimed = False
    engine._background_threads_started = False
    engine._stop_cleanup_lock = threading.Lock()
    engine._shutdown_event = threading.Event()
    engine._market_tick_recorder = None
    engine._hotpoint_decay_sweeper = None
    engine.event_executor = Mock(name="event_executor")
    engine.fee_manager = None
    engine.subscription = type(
        "Subscription",
        (),
        {"channels": (), "product_ids": ()},
    )()
    engine.websocket_thread_maximum = 0
    return engine


def _actors():
    bridge = Mock(name="bridge")
    controller = Mock(name="controller")
    controller.state = EngineState.STARTING
    controller.is_stopping.return_value = False
    controller.complete_startup.return_value = True
    controller.start_startup_component.side_effect = (
        lambda _name, start, _stop: (start(), True)[1]
    )
    engine = Mock(name="engine")
    return bridge, controller, engine


def test_unavailable_reconciliation_result_blocks_activation_and_engine(
    monkeypatch,
) -> None:
    bridge, controller, engine = _actors()
    periodic_factory = Mock(name="PeriodicReconciler")
    monkeypatch.setattr(main, "run_startup_reconciliation", Mock(return_value=None))
    monkeypatch.setattr(main, "PeriodicReconciler", periodic_factory)

    with pytest.raises(RuntimeError, match="could not verify"):
        main._run_reconciled_engine(
            reconciler_disabled=False,
            stealth_bridge=bridge,
            controller=controller,
            engine=engine,
        )

    bridge.activate_decisions.assert_not_called()
    periodic_factory.assert_not_called()
    engine.run_forever.assert_not_called()
    controller.complete_startup.assert_not_called()


def test_reconciliation_exception_blocks_activation_and_engine(monkeypatch) -> None:
    bridge, controller, engine = _actors()
    reconcile = Mock(side_effect=RuntimeError("REST unavailable"))
    periodic_factory = Mock(name="PeriodicReconciler")
    monkeypatch.setattr(main, "run_startup_reconciliation", reconcile)
    monkeypatch.setattr(main, "PeriodicReconciler", periodic_factory)

    with pytest.raises(RuntimeError, match="REST unavailable"):
        main._run_reconciled_engine(
            reconciler_disabled=False,
            stealth_bridge=bridge,
            controller=controller,
            engine=engine,
        )

    bridge.activate_decisions.assert_not_called()
    periodic_factory.assert_not_called()
    engine.run_forever.assert_not_called()
    controller.complete_startup.assert_not_called()


def test_activation_failure_blocks_periodic_reconciler_and_engine(monkeypatch) -> None:
    bridge, controller, engine = _actors()
    bridge.activate_decisions.side_effect = RuntimeError("scheduler failed")
    periodic_factory = Mock(name="PeriodicReconciler")
    monkeypatch.setattr(
        main,
        "run_startup_reconciliation",
        Mock(return_value=object()),
    )
    monkeypatch.setattr(main, "PeriodicReconciler", periodic_factory)

    with pytest.raises(RuntimeError, match="scheduler failed"):
        main._run_reconciled_engine(
            reconciler_disabled=False,
            stealth_bridge=bridge,
            controller=controller,
            engine=engine,
        )

    periodic_factory.assert_not_called()
    engine.run_forever.assert_not_called()
    controller.complete_startup.assert_not_called()


def test_successful_startup_crosses_each_gate_in_order(monkeypatch) -> None:
    events = []
    bridge, controller, engine = _actors()
    periodic_reconciler = Mock(name="periodic_reconciler")
    periodic_factory = Mock(
        name="PeriodicReconciler",
        return_value=periodic_reconciler,
    )
    monkeypatch.setattr(
        main,
        "run_startup_reconciliation",
        Mock(side_effect=lambda **_kwargs: events.append("reconcile") or object()),
    )
    monkeypatch.setattr(main, "PeriodicReconciler", periodic_factory)
    bridge.activate_decisions.side_effect = lambda: events.append("activate")
    def start_startup_component(_name, start, _stop):
        events.append("register_periodic_stop")
        start()
        return True

    controller.start_startup_component.side_effect = start_startup_component
    periodic_reconciler.start.side_effect = lambda: events.append("periodic_start")
    controller.complete_startup.side_effect = (
        lambda: events.append("complete_startup") or True
    )

    def run_forever(*, on_background_threads_started):
        events.append("background_threads_started")
        on_background_threads_started()
        events.append("engine_wait")

    engine.run_forever.side_effect = run_forever

    main._run_reconciled_engine(
        reconciler_disabled=False,
        stealth_bridge=bridge,
        controller=controller,
        engine=engine,
    )

    assert events == [
        "reconcile",
        "activate",
        "register_periodic_stop",
        "periodic_start",
        "background_threads_started",
        "complete_startup",
        "engine_wait",
    ]
    periodic_factory.assert_called_once_with(auto_heal=True, audit_fills=True)
    controller.start_startup_component.assert_called_once_with(
        "periodic_reconciler",
        periodic_reconciler.start,
        periodic_reconciler.stop,
    )


def test_explicit_reconciler_disable_is_the_only_bypass(monkeypatch) -> None:
    bridge, controller, engine = _actors()
    reconcile = Mock(name="run_startup_reconciliation")
    periodic_factory = Mock(name="PeriodicReconciler")
    monkeypatch.setattr(main, "run_startup_reconciliation", reconcile)
    monkeypatch.setattr(main, "PeriodicReconciler", periodic_factory)

    main._run_reconciled_engine(
        reconciler_disabled=True,
        stealth_bridge=bridge,
        controller=controller,
        engine=engine,
    )

    reconcile.assert_not_called()
    bridge.activate_decisions.assert_called_once_with()
    periodic_factory.assert_not_called()
    controller.start_startup_component.assert_not_called()
    engine.run_forever.assert_called_once()
    assert callable(
        engine.run_forever.call_args.kwargs["on_background_threads_started"]
    )


@pytest.mark.parametrize(
    ("start_paused", "expected_state"),
    (
        (False, EngineState.RUNNING),
        (True, EngineState.PAUSED),
    ),
)
def test_application_exposes_dashboard_only_inside_starting_barrier(
    monkeypatch,
    start_paused,
    expected_state,
) -> None:
    events = []
    controller = RuntimeController()
    bridge = Mock(name="bridge")
    engine = Mock(name="engine")
    periodic = Mock(name="periodic")

    bridge.start.side_effect = lambda: events.append("bridge_hydrated")
    bridge.activate_decisions.side_effect = lambda: events.append("decisions_active")
    periodic.start.side_effect = lambda: events.append("periodic_started")
    monkeypatch.setattr(
        main,
        "set_stealth_order_bridge",
        lambda _bridge: events.append("bridge_published"),
    )
    monkeypatch.setattr(
        main,
        "_install_shutdown_signal_handlers",
        lambda _controller: events.append("signals_installed"),
    )

    def start_dashboard():
        assert controller.state is EngineState.STARTING
        assert controller.is_admitting() is False
        events.append("dashboard_exposed")

    def reconcile(**_kwargs):
        assert controller.state is EngineState.STARTING
        events.append("reconciled")
        return object()

    def run_forever(*, on_background_threads_started):
        assert controller.state is EngineState.STARTING
        events.append("background_threads_started")
        on_background_threads_started()
        events.append(f"ready_{controller.state.value}")

    monkeypatch.setattr(main, "start_dashboard_server", start_dashboard)
    monkeypatch.setattr(main, "run_startup_reconciliation", reconcile)
    monkeypatch.setattr(main, "PeriodicReconciler", Mock(return_value=periodic))
    engine.run_forever.side_effect = run_forever

    main._run_application(
        reconciler_disabled=False,
        start_paused=start_paused,
        stealth_bridge=bridge,
        controller=controller,
        engine=engine,
    )

    assert events == [
        "signals_installed",
        "bridge_published",
        "bridge_hydrated",
        "dashboard_exposed",
        "reconciled",
        "decisions_active",
        "periodic_started",
        "background_threads_started",
        f"ready_{expected_state.value}",
    ]
    assert controller.state is expected_state
    assert controller.is_admitting() is (expected_state is EngineState.RUNNING)


def test_signal_intent_closes_admission_before_drain_thread_runs(
    monkeypatch,
) -> None:
    import signal

    controller = RuntimeController()
    registered_handlers = {}
    dormant_thread = Mock(name="dormant_drain_thread")

    def register(signum, handler):
        registered_handlers[signum] = handler

    monkeypatch.setattr(signal, "signal", register)
    monkeypatch.setattr(threading, "Thread", Mock(return_value=dormant_thread))
    main._install_shutdown_signal_handlers(controller)

    registered_handlers[signal.SIGINT](signal.SIGINT, None)

    dormant_thread.start.assert_called_once_with()
    assert controller.state is EngineState.DRAINING
    assert controller.is_stopping() is True
    assert controller.is_admitting() is False
    assert controller.complete_startup() is False
    assert controller.state is EngineState.DRAINING


def test_admin_pause_during_reconciliation_survives_readiness(monkeypatch) -> None:
    controller = RuntimeController()
    bridge = Mock(name="bridge")
    engine = Mock(name="engine")

    monkeypatch.setattr(main, "set_stealth_order_bridge", Mock())
    monkeypatch.setattr(main, "start_dashboard_server", Mock())
    monkeypatch.setattr(main, "_install_shutdown_signal_handlers", Mock())
    monkeypatch.setattr(
        main,
        "run_startup_reconciliation",
        lambda **_kwargs: controller.request_pause() and object(),
    )
    monkeypatch.setattr(main, "PeriodicReconciler", Mock(return_value=Mock()))
    engine.run_forever.side_effect = (
        lambda *, on_background_threads_started: on_background_threads_started()
    )

    main._run_application(
        reconciler_disabled=False,
        start_paused=False,
        stealth_bridge=bridge,
        controller=controller,
        engine=engine,
    )

    assert controller.state is EngineState.PAUSED
    assert controller.is_admitting() is False


def test_startup_failure_drains_every_started_component(monkeypatch) -> None:
    controller = RuntimeController()
    bridge = Mock(name="bridge")
    engine = Mock(name="engine")

    monkeypatch.setattr(main, "set_stealth_order_bridge", Mock())
    monkeypatch.setattr(main, "start_dashboard_server", Mock())
    monkeypatch.setattr(main, "_install_shutdown_signal_handlers", Mock())
    monkeypatch.setattr(
        main,
        "run_startup_reconciliation",
        Mock(side_effect=RuntimeError("REST unavailable")),
    )

    with pytest.raises(RuntimeError, match="REST unavailable"):
        main._run_application(
            reconciler_disabled=False,
            start_paused=False,
            stealth_bridge=bridge,
            controller=controller,
            engine=engine,
        )

    assert controller.state is EngineState.STOPPED
    bridge.stop.assert_called_once_with()
    engine.stop.assert_called_once_with()
    bridge.activate_decisions.assert_not_called()
    engine.run_forever.assert_not_called()


def test_hydration_failure_never_exposes_dashboard_or_later_stages(
    monkeypatch,
) -> None:
    controller = RuntimeController()
    bridge = Mock(name="bridge")
    engine = Mock(name="engine")
    bridge.start.side_effect = RuntimeError("hydration failed")
    dashboard = Mock(name="start_dashboard_server")
    reconcile = Mock(name="run_startup_reconciliation")
    periodic_factory = Mock(name="PeriodicReconciler")

    monkeypatch.setattr(main, "set_stealth_order_bridge", Mock())
    monkeypatch.setattr(main, "start_dashboard_server", dashboard)
    monkeypatch.setattr(main, "_install_shutdown_signal_handlers", Mock())
    monkeypatch.setattr(main, "run_startup_reconciliation", reconcile)
    monkeypatch.setattr(main, "PeriodicReconciler", periodic_factory)

    with pytest.raises(RuntimeError, match="hydration failed"):
        main._run_application(
            reconciler_disabled=False,
            start_paused=False,
            stealth_bridge=bridge,
            controller=controller,
            engine=engine,
        )

    assert controller.state is EngineState.STOPPED
    dashboard.assert_not_called()
    reconcile.assert_not_called()
    bridge.activate_decisions.assert_not_called()
    periodic_factory.assert_not_called()
    engine.run_forever.assert_not_called()
    bridge.stop.assert_called_once_with()
    engine.stop.assert_called_once_with()


def test_explicit_reconciler_bypass_reaches_readiness_without_audit(
    monkeypatch,
) -> None:
    controller = RuntimeController()
    bridge = Mock(name="bridge")
    engine = Mock(name="engine")
    reconcile = Mock(name="run_startup_reconciliation")
    periodic_factory = Mock(name="PeriodicReconciler")

    monkeypatch.setattr(main, "set_stealth_order_bridge", Mock())
    monkeypatch.setattr(main, "start_dashboard_server", Mock())
    monkeypatch.setattr(main, "_install_shutdown_signal_handlers", Mock())
    monkeypatch.setattr(main, "run_startup_reconciliation", reconcile)
    monkeypatch.setattr(main, "PeriodicReconciler", periodic_factory)
    engine.run_forever.side_effect = (
        lambda *, on_background_threads_started:
        on_background_threads_started()
    )

    main._run_application(
        reconciler_disabled=True,
        start_paused=False,
        stealth_bridge=bridge,
        controller=controller,
        engine=engine,
    )

    assert controller.state is EngineState.RUNNING
    assert controller.is_admitting() is True
    reconcile.assert_not_called()
    periodic_factory.assert_not_called()
    bridge.activate_decisions.assert_called_once_with()


def test_background_thread_start_failure_never_publishes_readiness(
    monkeypatch,
) -> None:
    controller = RuntimeController()
    bridge = Mock(name="bridge")
    engine = Mock(name="engine")
    periodic = Mock(name="periodic")

    monkeypatch.setattr(main, "set_stealth_order_bridge", Mock())
    monkeypatch.setattr(main, "start_dashboard_server", Mock())
    monkeypatch.setattr(main, "_install_shutdown_signal_handlers", Mock())
    monkeypatch.setattr(
        main,
        "run_startup_reconciliation",
        Mock(return_value=object()),
    )
    monkeypatch.setattr(main, "PeriodicReconciler", Mock(return_value=periodic))
    engine.run_forever.side_effect = RuntimeError("worker start failed")

    with pytest.raises(RuntimeError, match="worker start failed"):
        main._run_application(
            reconciler_disabled=False,
            start_paused=False,
            stealth_bridge=bridge,
            controller=controller,
            engine=engine,
        )

    assert controller.state is EngineState.STOPPED
    bridge.stop.assert_called_once_with()
    engine.stop.assert_called_once_with()
    periodic.stop.assert_called_once_with()


def test_shutdown_before_worker_readiness_cannot_reopen_admission(
    monkeypatch,
) -> None:
    controller = RuntimeController()
    engine = Mock(name="engine")
    monkeypatch.setattr(main, "PeriodicReconciler", Mock(return_value=Mock()))

    def run_forever(*, on_background_threads_started):
        controller.request_shutdown()
        try:
            on_background_threads_started()
        except Exception:
            engine.stop()
            raise

    engine.run_forever.side_effect = run_forever

    with pytest.raises(RuntimeError, match="readiness publication refused"):
        main._run_reconciled_engine(
            reconciler_disabled=True,
            stealth_bridge=None,
            controller=controller,
            engine=engine,
        )

    assert controller.state is EngineState.DRAINING
    assert controller.is_admitting() is False
    engine.stop.assert_called_once_with()


def test_startup_exception_finishes_drain_even_if_state_is_already_draining(
    monkeypatch,
) -> None:
    controller = RuntimeController()
    bridge = Mock(name="bridge")
    engine = Mock(name="engine")

    monkeypatch.setattr(main, "set_stealth_order_bridge", Mock())
    monkeypatch.setattr(main, "start_dashboard_server", Mock())
    monkeypatch.setattr(main, "_install_shutdown_signal_handlers", Mock())
    monkeypatch.setattr(
        main,
        "run_startup_reconciliation",
        Mock(return_value=object()),
    )
    monkeypatch.setattr(main, "PeriodicReconciler", Mock(return_value=Mock()))

    def fail_after_shutdown_request(*, on_background_threads_started):
        del on_background_threads_started
        controller.request_shutdown()
        raise RuntimeError("startup interrupted")

    engine.run_forever.side_effect = fail_after_shutdown_request

    with pytest.raises(RuntimeError, match="startup interrupted"):
        main._run_application(
            reconciler_disabled=False,
            start_paused=False,
            stealth_bridge=bridge,
            controller=controller,
            engine=engine,
        )

    assert controller.state is EngineState.STOPPED
    bridge.stop.assert_called_once_with()
    engine.stop.assert_called_once_with()


def test_order_engine_callback_runs_only_after_background_start() -> None:
    engine = _bare_order_engine()
    events = []
    engine.start_background_threads = lambda: events.append("background")
    engine._publish_engine_status = Mock(
        return_value={"engine_state": EngineState.STARTING.value}
    )

    def publish_readiness():
        events.append("callback")
        engine._shutdown_event.set()

    engine.run_forever(
        on_background_threads_started=publish_readiness,
    )

    assert events == ["background", "callback"]


def test_order_engine_start_failure_stops_partial_launch_before_readiness() -> None:
    engine = _bare_order_engine()
    engine._start_background_threads_unlocked = Mock(
        side_effect=RuntimeError("worker start failed")
    )
    readiness = Mock(name="readiness")

    with pytest.raises(RuntimeError, match="worker start failed"):
        engine.run_forever(on_background_threads_started=readiness)

    readiness.assert_not_called()
    assert engine._shutdown_event.is_set()
    assert engine.event_executor.shutdown.call_count == 2
    engine.event_executor.shutdown.assert_called_with(
        wait=False,
        cancel_futures=False,
    )


def test_order_engine_pre_stopped_launch_never_starts_or_publishes() -> None:
    engine = _bare_order_engine()
    engine._shutdown_event.set()
    engine._start_background_threads_unlocked = Mock(name="worker_launch")
    readiness = Mock(name="readiness")

    with pytest.raises(RuntimeError, match="refused after stop"):
        engine.run_forever(on_background_threads_started=readiness)

    engine._start_background_threads_unlocked.assert_not_called()
    readiness.assert_not_called()


def test_order_engine_stop_returns_while_startup_preparation_is_blocked() -> None:
    engine = _bare_order_engine()
    preparation_entered = threading.Event()
    release_preparation = threading.Event()
    readiness = Mock(name="readiness")
    startup_errors = []

    def blocked_preparation() -> None:
        preparation_entered.set()
        assert release_preparation.wait(timeout=1.0)

    engine._start_background_threads_unlocked = blocked_preparation

    def run() -> None:
        try:
            engine.run_forever(on_background_threads_started=readiness)
        except Exception as exc:
            startup_errors.append(exc)

    runner = threading.Thread(target=run)
    runner.start()
    assert preparation_entered.wait(timeout=1.0)

    stopper = threading.Thread(target=engine.stop)
    stopper.start()
    stopper.join(timeout=0.5)
    assert not stopper.is_alive()
    assert engine._shutdown_event.is_set()
    readiness.assert_not_called()

    release_preparation.set()
    runner.join(timeout=1.0)
    assert not runner.is_alive()
    assert len(startup_errors) == 1
    assert "interrupted by stop" in str(startup_errors[0])
    assert engine.event_executor.shutdown.call_count == 3
    engine.event_executor.shutdown.assert_called_with(
        wait=False,
        cancel_futures=False,
    )


def test_order_engine_background_startup_is_one_shot() -> None:
    engine = _bare_order_engine()
    launch = Mock(name="launch")
    engine._start_background_threads_unlocked = launch

    engine.start_background_threads()

    with pytest.raises(RuntimeError, match="already been attempted"):
        engine.start_background_threads()
    launch.assert_called_once_with()


def test_order_engine_stop_first_refuses_bounded_activation() -> None:
    engine = _bare_order_engine()
    activation = Mock(name="activation")
    engine.stop()

    with pytest.raises(RuntimeError, match="activation after stop"):
        engine._commit_startup_activation("synthetic-worker", activation)

    activation.assert_not_called()


def test_global_shutdown_quiesces_engine_before_blocked_bridge_cleanup(
    monkeypatch,
) -> None:
    controller = RuntimeController()
    engine = _bare_order_engine()
    bridge_stop_entered = threading.Event()
    release_bridge_stop = threading.Event()
    activation = Mock(name="activation")
    published_statuses = []

    def blocked_bridge_stop() -> None:
        bridge_stop_entered.set()
        assert release_bridge_stop.wait(timeout=1.0)

    controller.register_stop_hook(
        "order_engine_quiesce",
        engine.prepare_for_global_drain,
    )
    controller.register_stop_hook("stealth_bridge", blocked_bridge_stop)
    controller.register_stop_hook("order_engine", engine.stop)
    monkeypatch.setattr(
        order_engine_module,
        "get_runtime_controller",
        lambda: controller,
    )
    monkeypatch.setattr(
        order_engine_module,
        "update_engine_status",
        lambda payload: published_statuses.append(dict(payload)),
    )

    drainer = threading.Thread(
        target=lambda: controller.drain_and_stop(timeout_seconds=1.0)
    )
    drainer.start()
    assert bridge_stop_entered.wait(timeout=1.0)
    assert controller.state is EngineState.DRAINING
    assert engine._shutdown_event.is_set()
    assert published_statuses[-1] == {
        "running": False,
        "engine_state": EngineState.DRAINING.value,
        "threads_active": 0,
    }

    with pytest.raises(RuntimeError, match="activation after stop"):
        engine._commit_startup_activation("late-worker", activation)
    activation.assert_not_called()

    release_bridge_stop.set()
    drainer.join(timeout=1.0)
    assert not drainer.is_alive()
    assert controller.state is EngineState.STOPPED


def test_running_shutdown_preserves_engine_workers_until_bridge_stops(
    monkeypatch,
) -> None:
    controller = RuntimeController()
    assert controller.complete_startup() is True
    engine = _bare_order_engine()
    engine._background_threads_started = True
    bridge_stop_entered = threading.Event()
    release_bridge_stop = threading.Event()
    published_statuses = []

    def blocked_bridge_stop() -> None:
        bridge_stop_entered.set()
        assert release_bridge_stop.wait(timeout=1.0)

    controller.register_stop_hook(
        "order_engine_quiesce",
        engine.prepare_for_global_drain,
    )
    controller.register_stop_hook("stealth_bridge", blocked_bridge_stop)
    controller.register_stop_hook("order_engine", engine.stop)
    monkeypatch.setattr(
        order_engine_module,
        "get_runtime_controller",
        lambda: controller,
    )
    monkeypatch.setattr(
        order_engine_module,
        "update_engine_status",
        lambda payload: published_statuses.append(dict(payload)),
    )

    drainer = threading.Thread(
        target=lambda: controller.drain_and_stop(timeout_seconds=1.0)
    )
    drainer.start()
    assert bridge_stop_entered.wait(timeout=1.0)
    assert controller.state is EngineState.DRAINING
    assert not engine._shutdown_event.is_set()
    assert published_statuses[-1] == {
        "running": False,
        "engine_state": EngineState.DRAINING.value,
    }

    release_bridge_stop.set()
    drainer.join(timeout=1.0)
    assert not drainer.is_alive()
    assert engine._shutdown_event.is_set()
    assert published_statuses[-1]["threads_active"] == 0
    assert controller.state is EngineState.STOPPED


def test_order_engine_readiness_commit_precedes_concurrent_stop() -> None:
    engine = _bare_order_engine()
    engine.start_background_threads = Mock(name="background_start")
    readiness_entered = threading.Event()
    release_readiness = threading.Event()
    stop_returned = threading.Event()

    def readiness() -> None:
        readiness_entered.set()
        assert release_readiness.wait(timeout=1.0)

    runner = threading.Thread(
        target=lambda: engine.run_forever(
            on_background_threads_started=readiness
        )
    )
    runner.start()
    assert readiness_entered.wait(timeout=1.0)

    stopper = threading.Thread(
        target=lambda: (engine.stop(), stop_returned.set())
    )
    stopper.start()
    assert stop_returned.wait(timeout=0.05) is False

    release_readiness.set()
    assert stop_returned.wait(timeout=1.0)
    stopper.join(timeout=1.0)
    runner.join(timeout=1.0)
    assert not stopper.is_alive()
    assert not runner.is_alive()
    assert engine._shutdown_event.is_set()


def test_engine_status_is_non_running_until_runtime_readiness(
    monkeypatch,
) -> None:
    controller = RuntimeController()
    engine = _bare_order_engine()
    engine._background_threads_started = True
    published = []
    monkeypatch.setattr(
        order_engine_module,
        "get_runtime_controller",
        lambda: controller,
    )
    monkeypatch.setattr(
        order_engine_module,
        "update_engine_status",
        lambda payload: published.append(dict(payload)),
    )

    engine._publish_engine_status(event_queue_depth=0)
    assert published[-1]["running"] is False
    assert published[-1]["engine_state"] == EngineState.STARTING.value

    assert controller.complete_startup() is True
    engine._publish_engine_status(event_queue_depth=0)
    assert published[-1]["running"] is True
    assert published[-1]["engine_state"] == EngineState.RUNNING.value

    assert controller.request_pause() is True
    engine._publish_engine_status(event_queue_depth=0)
    assert published[-1]["running"] is False
    assert published[-1]["engine_state"] == EngineState.PAUSED.value


@pytest.mark.parametrize(
    ("start_paused", "expected_state", "expected_running"),
    (
        (False, EngineState.RUNNING, True),
        (True, EngineState.PAUSED, False),
    ),
)
def test_run_forever_readiness_publishes_operational_status_once(
    monkeypatch,
    start_paused,
    expected_state,
    expected_running,
) -> None:
    controller = RuntimeController()
    if start_paused:
        assert controller.request_pause() is True
    engine = _bare_order_engine()
    engine.start_background_threads = lambda: setattr(
        engine,
        "_background_threads_started",
        True,
    )
    published = []
    logs = []
    readiness_published = threading.Event()
    readiness_logged = threading.Event()

    def update_status(payload) -> None:
        published.append(dict(payload))
        readiness_published.set()

    def add_log(level, message) -> None:
        logs.append((level, message))
        readiness_logged.set()

    monkeypatch.setattr(
        order_engine_module,
        "get_runtime_controller",
        lambda: controller,
    )
    monkeypatch.setattr(
        order_engine_module,
        "update_engine_status",
        update_status,
    )
    monkeypatch.setattr(order_engine_module, "add_log_entry", add_log)

    runner = threading.Thread(
        target=lambda: engine.run_forever(
            on_background_threads_started=controller.complete_startup,
        )
    )
    runner.start()
    assert readiness_published.wait(timeout=1.0)
    assert readiness_logged.wait(timeout=1.0)

    assert controller.state is expected_state
    assert published == [{
        "threads_active": 2,
        "event_queue_depth": 0,
        "running": expected_running,
        "engine_state": expected_state.value,
    }]
    assert logs == [(
        "INFO",
        f"Trading engine startup complete ({expected_state.value})",
    )]

    engine.stop()
    runner.join(timeout=1.0)
    assert not runner.is_alive()


def test_stop_cannot_be_overwritten_by_stale_monitor_status(
    monkeypatch,
) -> None:
    controller = RuntimeController()
    assert controller.complete_startup() is True
    engine = _bare_order_engine()
    engine._background_threads_started = True
    build_entered = threading.Event()
    release_build = threading.Event()
    published = []

    def blocked_build(_event_queue_depth):
        build_entered.set()
        assert release_build.wait(timeout=1.0)
        return {"threads_active": 4, "event_queue_depth": 0}

    engine._build_engine_status_payload = blocked_build
    monkeypatch.setattr(
        order_engine_module,
        "get_runtime_controller",
        lambda: controller,
    )
    monkeypatch.setattr(
        order_engine_module,
        "update_engine_status",
        lambda payload: published.append(dict(payload)),
    )

    monitor = threading.Thread(
        target=lambda: engine._publish_engine_status(event_queue_depth=0)
    )
    monitor.start()
    assert build_entered.wait(timeout=1.0)

    controller.request_shutdown()
    engine.stop()
    assert published[-1]["running"] is False

    release_build.set()
    monitor.join(timeout=1.0)

    assert not monitor.is_alive()
    assert published[-1]["running"] is False
    assert published[-1]["engine_state"] == EngineState.DRAINING.value
    assert all(payload["running"] is False for payload in published)


def test_order_engine_stop_retries_component_cleanup(monkeypatch) -> None:
    controller = RuntimeController()
    engine = _bare_order_engine()
    fee_manager = Mock(name="fee_manager")
    fee_manager.stop.side_effect = [RuntimeError("first stop failed"), None]
    engine.fee_manager = fee_manager
    monkeypatch.setattr(
        order_engine_module,
        "get_runtime_controller",
        lambda: controller,
    )
    monkeypatch.setattr(order_engine_module, "update_engine_status", Mock())

    engine.stop()
    engine.stop()

    assert engine._shutdown_event.is_set()
    assert fee_manager.stop.call_count == 2
    assert engine.event_executor.shutdown.call_count == 2


def test_order_engine_stop_during_fee_refresh_prevents_websocket_start(
    monkeypatch,
) -> None:
    engine = _bare_order_engine()
    engine.load_parent_child_order_ids = Mock(return_value=True)
    engine._hydrate_order_progress_tracker_from_db = Mock()
    engine._build_engine_status_payload = Mock(return_value={})
    engine._start_hotpoint_background = Mock()
    engine.reconcile_parent_child_order_ids_periodically = lambda **_kwargs: None
    engine._monitor_engine_status = lambda: None
    engine.rotate_seen_events_buckets = lambda: None
    engine.subscription = type("Subscription", (), {"channels": ()})()
    engine.websocket_thread_maximum = 2
    engine.connect_to_websocket = Mock(name="connect_to_websocket")

    refresh_entered = threading.Event()
    release_refresh = threading.Event()
    fee_stopped = threading.Event()

    class BlockingFeeManager:
        def start_periodic_refresh(self):
            return True

        def refresh_now(self):
            refresh_entered.set()
            assert release_refresh.wait(timeout=1.0)
            return True

        def stop(self):
            fee_stopped.set()

    engine.fee_manager = BlockingFeeManager()
    started_names = []
    original_start_thread = engine._start_owned_thread

    def record_start(**kwargs):
        started_names.append(kwargs["name"])
        return original_start_thread(**kwargs)

    engine._start_owned_thread = record_start
    monkeypatch.setattr(order_engine_module, "MARKET_TICK_RECORDER_AVAILABLE", False)
    monkeypatch.setattr(order_engine_module, "MARKET_METRICS_AVAILABLE", False)
    monkeypatch.setattr(order_engine_module, "update_engine_status", Mock())
    monkeypatch.setattr(order_engine_module, "add_log_entry", Mock())
    readiness = Mock(name="readiness")
    startup_errors = []

    def run() -> None:
        try:
            engine.run_forever(on_background_threads_started=readiness)
        except Exception as exc:
            startup_errors.append(exc)

    runner = threading.Thread(target=run)
    runner.start()
    assert refresh_entered.wait(timeout=1.0)
    assert all(not name.startswith("websocket_thread_") for name in started_names)

    stopper = threading.Thread(target=engine.stop)
    stopper.start()
    stopper.join(timeout=0.5)
    assert not stopper.is_alive()
    assert fee_stopped.is_set()
    readiness.assert_not_called()

    release_refresh.set()
    runner.join(timeout=1.0)
    assert not runner.is_alive()
    assert len(startup_errors) == 1
    assert "initial fee refresh" in str(startup_errors[0])
    assert all(not name.startswith("websocket_thread_") for name in started_names)
    engine.connect_to_websocket.assert_not_called()


def test_shutdown_after_fee_worker_commit_skips_initial_fee_rest(
    monkeypatch,
) -> None:
    controller = RuntimeController()
    engine = _bare_order_engine()
    engine.load_parent_child_order_ids = Mock(return_value=True)
    engine._hydrate_order_progress_tracker_from_db = Mock()
    engine._build_engine_status_payload = Mock(return_value={})
    engine._start_hotpoint_background = Mock()
    engine.reconcile_parent_child_order_ids_periodically = lambda **_kwargs: None
    engine._monitor_engine_status = lambda: None
    engine.rotate_seen_events_buckets = lambda: None
    engine.connect_to_websocket = Mock(name="connect_to_websocket")
    engine.subscription = type("Subscription", (), {"channels": ()})()
    engine.websocket_thread_maximum = 2

    fee_manager = Mock(name="fee_manager")

    def start_periodic_refresh() -> bool:
        controller.request_shutdown()
        return True

    fee_manager.start_periodic_refresh.side_effect = start_periodic_refresh
    engine.fee_manager = fee_manager

    monkeypatch.setattr(
        order_engine_module,
        "get_runtime_controller",
        lambda: controller,
    )
    monkeypatch.setattr(
        order_engine_module,
        "MARKET_TICK_RECORDER_AVAILABLE",
        False,
    )
    monkeypatch.setattr(order_engine_module, "MARKET_METRICS_AVAILABLE", False)
    monkeypatch.setattr(order_engine_module, "update_engine_status", Mock())

    with pytest.raises(RuntimeError, match="before initial fee refresh"):
        engine.start_background_threads()

    fee_manager.start_periodic_refresh.assert_called_once_with()
    fee_manager.refresh_now.assert_not_called()
    engine.connect_to_websocket.assert_not_called()


def test_pre_stopped_websocket_worker_never_connects(monkeypatch) -> None:
    engine = _bare_order_engine()
    engine._shutdown_event.set()
    sdk_factory = Mock(name="WSClient")
    wrapper_factory = Mock(name="CoinbaseWebSocketClient")
    monkeypatch.setattr(order_engine_module, "WSClient", sdk_factory)
    monkeypatch.setattr(
        order_engine_module,
        "CoinbaseWebSocketClient",
        wrapper_factory,
    )

    engine.connect_to_websocket()

    sdk_factory.assert_not_called()
    wrapper_factory.assert_not_called()


def _websocket_engine() -> main.OrderEngine:
    engine = _bare_order_engine()
    engine.api_key = "test-key"
    engine.api_secret = "test-secret"
    engine.on_open = Mock(name="on_open")
    engine.on_message = Mock(name="on_message")
    engine.subscription = type(
        "Subscription",
        (),
        {"channels": ("ticker",), "product_ids": ("BTC-USDC",)},
    )()
    engine.log_message = Mock(name="log_message")
    engine.build_event_log_payload = Mock(return_value={})
    return engine


def test_websocket_stop_after_connect_disconnects_without_subscribing(
    monkeypatch,
) -> None:
    engine = _websocket_engine()
    wrapper = Mock(name="websocket_wrapper")
    wrapper.connect.side_effect = engine._shutdown_event.set
    monkeypatch.setattr(order_engine_module, "WSClient", Mock())
    monkeypatch.setattr(
        order_engine_module,
        "CoinbaseWebSocketClient",
        Mock(return_value=wrapper),
    )

    engine.connect_to_websocket()

    wrapper.connect.assert_called_once_with()
    wrapper.subscribe.assert_not_called()
    wrapper.disconnect.assert_called_once_with()


def test_websocket_normal_loop_exit_disconnects_owned_client(
    monkeypatch,
) -> None:
    engine = _websocket_engine()
    wrapper = Mock(name="websocket_wrapper")
    wrapper.sleep_with_exception_check.return_value = True
    monkeypatch.setattr(order_engine_module, "WSClient", Mock())
    monkeypatch.setattr(
        order_engine_module,
        "CoinbaseWebSocketClient",
        Mock(return_value=wrapper),
    )

    engine.connect_to_websocket()

    wrapper.connect.assert_called_once_with()
    wrapper.subscribe.assert_called_once_with(
        products=("BTC-USDC",),
        channels=("ticker",),
    )
    wrapper.disconnect.assert_called_once_with()


def test_websocket_connect_failure_preserves_error_and_disconnects(
    monkeypatch,
) -> None:
    engine = _websocket_engine()
    wrapper = Mock(name="websocket_wrapper")
    wrapper.connect.side_effect = RuntimeError("SDK open failed")
    monkeypatch.setattr(order_engine_module, "WSClient", Mock())
    monkeypatch.setattr(
        order_engine_module,
        "CoinbaseWebSocketClient",
        Mock(return_value=wrapper),
    )

    with pytest.raises(RuntimeError, match="SDK open failed"):
        engine.connect_to_websocket()

    wrapper.subscribe.assert_not_called()
    wrapper.disconnect.assert_called_once_with()


@pytest.mark.parametrize("value", ("1", "TRUE", "yes", "On"))
def test_engine_start_paused_truthy_values(monkeypatch, value) -> None:
    monkeypatch.setenv("ENGINE_START_PAUSED", value)
    assert main._read_strict_boolean_env(
        "ENGINE_START_PAUSED",
        default=True,
    ) is True


@pytest.mark.parametrize("value", ("0", "false", "NO", "off"))
def test_engine_start_paused_explicit_false_values(monkeypatch, value) -> None:
    monkeypatch.setenv("ENGINE_START_PAUSED", value)
    assert main._read_strict_boolean_env(
        "ENGINE_START_PAUSED",
        default=True,
    ) is False


@pytest.mark.parametrize("value", (None, "", "   "))
def test_engine_start_paused_unset_or_blank_uses_safe_default(
    monkeypatch,
    value,
) -> None:
    if value is None:
        monkeypatch.delenv("ENGINE_START_PAUSED", raising=False)
    else:
        monkeypatch.setenv("ENGINE_START_PAUSED", value)
    assert main._read_strict_boolean_env(
        "ENGINE_START_PAUSED",
        default=True,
    ) is True


def test_engine_start_paused_invalid_value_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("ENGINE_START_PAUSED", "sometimes")
    with pytest.raises(RuntimeError, match="ENGINE_START_PAUSED"):
        main._read_strict_boolean_env(
            "ENGINE_START_PAUSED",
            default=True,
        )


class _QueryDB:
    def __init__(self, rows=None, error=None):
        self.rows = rows
        self.error = error

    def execute_query(self, _sql, _params=None):
        if self.error is not None:
            raise self.error
        return list(self.rows or ())

    def disconnect(self):
        return None


def test_local_open_query_failure_makes_reconciliation_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        startup_reconciler,
        "_fetch_exchange_open_client_order_ids",
        lambda: {"exchange-coid"},
    )
    with patch(
        "database.database.PostgresDB",
        return_value=_QueryDB(error=RuntimeError("local DB unavailable")),
    ):
        report = startup_reconciler.run_startup_reconciliation()

    assert report is None


def test_all_local_id_query_failure_makes_reconciliation_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        startup_reconciler,
        "_fetch_exchange_open_client_order_ids",
        lambda: {"known-coid"},
    )
    with patch(
        "database.database.PostgresDB",
        side_effect=(
            _QueryDB(rows=[{"client_order_id": "known-coid", "status": "OPEN"}]),
            _QueryDB(error=RuntimeError("all-local query unavailable")),
        ),
    ):
        report = startup_reconciler.run_startup_reconciliation()

    assert report is None


class _RestClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def list_orders(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self.response


@pytest.mark.parametrize(
    "response",
    (
        None,
        {},
        {"success": False, "orders": []},
    ),
)
def test_malformed_exchange_response_cannot_be_treated_as_zero_open_orders(
    monkeypatch,
    response,
) -> None:
    monkeypatch.setattr(configuration, "REST_CLIENT", _RestClient(response))
    auto_heal = Mock(name="apply_auto_heal")
    monkeypatch.setattr(startup_reconciler, "apply_auto_heal", auto_heal)

    report = startup_reconciler.run_startup_reconciliation(auto_heal=True)

    assert report is None
    auto_heal.assert_not_called()


def test_explicit_empty_exchange_orders_list_is_authoritative(monkeypatch) -> None:
    monkeypatch.setattr(
        configuration,
        "REST_CLIENT",
        _RestClient({"orders": []}),
    )

    assert startup_reconciler._fetch_exchange_open_client_order_ids() == set()


def test_exchange_open_orders_are_exhaustively_paginated(monkeypatch) -> None:
    class PagedRestClient:
        def __init__(self):
            self.calls = []
            self.pages = iter(
                (
                    {
                        "orders": [{"client_order_id": "coid-a"}],
                        "has_next": True,
                        "cursor": "cursor-1",
                    },
                    {
                        "orders": [{"client_order_id": "coid-b"}],
                        "has_next": False,
                        "cursor": None,
                    },
                )
            )

        def list_orders(self, **kwargs):
            self.calls.append(dict(kwargs))
            return next(self.pages)

    rest_client = PagedRestClient()
    monkeypatch.setattr(configuration, "REST_CLIENT", rest_client)

    assert startup_reconciler._fetch_exchange_open_client_order_ids() == {
        "coid-a",
        "coid-b",
    }
    assert rest_client.calls == [
        {"order_status": ["OPEN"]},
        {"order_status": ["OPEN"], "cursor": "cursor-1"},
    ]


@pytest.mark.parametrize(
    "response",
    (
        {"orders": [], "has_next": True, "cursor": None},
        {"orders": [], "has_next": "true", "cursor": "cursor-1"},
    ),
)
def test_malformed_exchange_pagination_fails_closed(
    monkeypatch,
    response,
) -> None:
    monkeypatch.setattr(configuration, "REST_CLIENT", _RestClient(response))

    with pytest.raises(RuntimeError):
        startup_reconciler._fetch_exchange_open_client_order_ids()
