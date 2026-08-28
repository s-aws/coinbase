"""Regression tests for the runtime lifecycle controller.

These tests cover the contract that the rest of the engine relies on:

* state machine transitions are correct and one-way where required
* the admission gate rejects originating work in non-RUNNING states
* always-allowed categories (cancellations, fills) pass through
* in-flight tracking is exception-safe and notifies waiters
* the drain orchestrator invokes stop hooks, waits for in-flight work,
  and reports timeout cleanly when work doesn't complete in time

Run with::

    pytest tests/regression/test_runtime_controller.py -v
"""

from __future__ import annotations

import threading
import time
from unittest.mock import Mock

import pytest

from core.enums import EngineState
from core.runtime_controller import (
    INFLIGHT_DB_WRITE,
    INFLIGHT_FILL_PROCESSING,
    INFLIGHT_REST_CANCEL,
    INFLIGHT_REST_PLACE,
    INFLIGHT_STEALTH_REVEAL,
    EngineNotAdmittingError,
    RuntimeController,
    get_runtime_controller,
)


@pytest.fixture
def controller():
    """Fresh controller whose normal runtime startup has completed."""
    runtime = RuntimeController()
    assert runtime.complete_startup() is True
    return runtime


class TestStartupTransitions:
    """Startup is fail-closed until the sole readiness transition."""

    @pytest.mark.regression
    def test_initial_state_is_starting_and_non_admitting(self):
        runtime = RuntimeController()

        assert runtime.state is EngineState.STARTING
        assert runtime.is_admitting() is False
        assert runtime.is_stopping() is False
        assert runtime.lifecycle_snapshot() == (
            EngineState.STARTING,
            False,
            False,
        )
        assert runtime.startup_pause_pending() is False

    @pytest.mark.regression
    def test_starting_admission_matrix(self):
        runtime = RuntimeController()

        for category in (INFLIGHT_REST_PLACE, INFLIGHT_STEALTH_REVEAL):
            with pytest.raises(EngineNotAdmittingError) as exc_info:
                runtime.check_admission(category)
            assert exc_info.value.state is EngineState.STARTING

        for category in (
            INFLIGHT_REST_CANCEL,
            INFLIGHT_FILL_PROCESSING,
            INFLIGHT_DB_WRITE,
        ):
            runtime.check_admission(category)

    @pytest.mark.regression
    def test_complete_startup_opens_admission_once(self):
        runtime = RuntimeController()

        assert runtime.complete_startup() is True
        assert runtime.state is EngineState.RUNNING
        assert runtime.is_admitting() is True
        assert runtime.complete_startup() is False

    @pytest.mark.regression
    def test_startup_pause_is_sticky_and_cannot_resume_early(self):
        runtime = RuntimeController()

        assert runtime.request_pause() is True
        assert runtime.request_pause() is False
        assert runtime.state is EngineState.STARTING
        assert runtime.startup_pause_pending() is True
        assert runtime.resume() is False
        assert runtime.state is EngineState.STARTING

        assert runtime.complete_startup() is True
        assert runtime.state is EngineState.PAUSED
        assert runtime.startup_pause_pending() is False
        assert runtime.is_admitting() is False

    @pytest.mark.regression
    def test_shutdown_wins_over_late_startup_completion(self):
        runtime = RuntimeController()

        assert runtime.request_shutdown() is True
        assert runtime.state is EngineState.DRAINING
        assert runtime.complete_startup() is False
        assert runtime.state is EngineState.DRAINING
        assert runtime.is_admitting() is False

    @pytest.mark.regression
    def test_signal_intent_closes_startup_without_taking_state_lock(self):
        runtime = RuntimeController()
        start = Mock(name="start")
        stop = Mock(name="stop")
        late_stop = Mock(name="late_stop")

        runtime.request_shutdown_from_signal()

        assert runtime.state is EngineState.DRAINING
        assert runtime.is_stopping() is True
        assert runtime.is_admitting() is False
        assert runtime.lifecycle_snapshot() == (
            EngineState.DRAINING,
            False,
            True,
        )
        assert runtime.register_stop_hook("late", late_stop) is False
        late_stop.assert_called_once_with()
        assert runtime.start_startup_component("periodic", start, stop) is False
        start.assert_not_called()
        stop.assert_not_called()
        assert runtime.complete_startup() is False
        assert runtime.state is EngineState.DRAINING

    @pytest.mark.regression
    def test_pause_complete_race_always_finishes_paused(self):
        for _ in range(25):
            runtime = RuntimeController()
            start = threading.Barrier(3)

            def pause():
                start.wait()
                runtime.request_pause()

            def complete():
                start.wait()
                runtime.complete_startup()

            pause_thread = threading.Thread(target=pause)
            complete_thread = threading.Thread(target=complete)
            pause_thread.start()
            complete_thread.start()
            start.wait()
            pause_thread.join(timeout=1.0)
            complete_thread.join(timeout=1.0)

            assert not pause_thread.is_alive()
            assert not complete_thread.is_alive()
            assert runtime.state is EngineState.PAUSED
            assert runtime.is_admitting() is False

    @pytest.mark.regression
    def test_reset_restores_fresh_startup_latch(self):
        runtime = RuntimeController()
        runtime.request_pause()
        runtime.complete_startup()

        runtime._reset_for_tests()

        assert runtime.state is EngineState.STARTING
        assert runtime.startup_pause_pending() is False
        assert runtime.is_admitting() is False

    @pytest.mark.regression
    def test_startup_component_refuses_to_start_after_shutdown(self):
        runtime = RuntimeController()
        start_calls = []
        stop_calls = []
        runtime.request_shutdown()

        started = runtime.start_startup_component(
            "periodic",
            lambda: start_calls.append("start"),
            lambda: stop_calls.append("stop"),
        )

        assert started is False
        assert start_calls == []
        assert stop_calls == []

    @pytest.mark.regression
    def test_startup_component_register_and_start_precede_shutdown_hooks(self):
        runtime = RuntimeController()
        start_entered = threading.Event()
        release_start = threading.Event()
        events = []

        def start_component():
            events.append("start_entered")
            start_entered.set()
            assert release_start.wait(timeout=1.0)
            events.append("start_returned")

        starter = threading.Thread(
            target=lambda: runtime.start_startup_component(
                "periodic",
                start_component,
                lambda: events.append("stop"),
            )
        )
        drainer = threading.Thread(
            target=lambda: runtime.drain_and_stop(timeout_seconds=1.0)
        )

        starter.start()
        assert start_entered.wait(timeout=1.0)
        drainer.start()
        time.sleep(0.02)
        assert drainer.is_alive()
        release_start.set()
        starter.join(timeout=1.0)
        drainer.join(timeout=1.0)

        assert not starter.is_alive()
        assert not drainer.is_alive()
        assert events == ["start_entered", "start_returned", "stop"]
        assert runtime.state is EngineState.STOPPED

    @pytest.mark.regression
    def test_startup_component_failure_retains_cleanup_hook(self):
        runtime = RuntimeController()
        stop_calls = []

        with pytest.raises(RuntimeError, match="start failed"):
            runtime.start_startup_component(
                "periodic",
                lambda: (_ for _ in ()).throw(RuntimeError("start failed")),
                lambda: stop_calls.append("stop"),
            )

        assert runtime.state is EngineState.STARTING
        runtime.drain_and_stop(timeout_seconds=0.1)
        assert stop_calls == ["stop"]
        assert runtime.state is EngineState.STOPPED


class TestAdmissionOpenHooks:
    """RUNNING notifications are level-triggered and lifecycle-safe."""

    @pytest.mark.regression
    def test_startup_transition_notifies_hooks_in_registration_order(self):
        runtime = RuntimeController()
        events = []

        for name in ("alpha", "beta"):
            assert runtime.register_admission_open_hook(
                name,
                lambda name=name: events.append(
                    (name, runtime.state, runtime.is_admitting())
                ),
            ) is True

        assert runtime.complete_startup() is True
        assert events == [
            ("alpha", EngineState.RUNNING, True),
            ("beta", EngineState.RUNNING, True),
        ]

        # A no-op readiness call is not another admission-open transition.
        assert runtime.complete_startup() is False
        assert len(events) == 2

    @pytest.mark.regression
    def test_startup_pause_defers_hook_until_each_real_resume(self):
        runtime = RuntimeController()
        calls = []
        assert runtime.register_admission_open_hook(
            "owner", lambda: calls.append(runtime.state)
        ) is True

        assert runtime.request_pause() is True
        assert runtime.complete_startup() is True
        assert runtime.state is EngineState.PAUSED
        assert calls == []

        assert runtime.resume() is True
        assert calls == [EngineState.RUNNING]
        assert runtime.resume() is False
        assert calls == [EngineState.RUNNING]

        assert runtime.request_pause() is True
        assert runtime.resume() is True
        assert calls == [EngineState.RUNNING, EngineState.RUNNING]

    @pytest.mark.regression
    def test_registration_while_running_invokes_immediately(self):
        runtime = RuntimeController()
        assert runtime.complete_startup() is True
        calls = []

        assert runtime.register_admission_open_hook(
            "late", lambda: calls.append(runtime.lifecycle_snapshot())
        ) is True

        assert calls == [(EngineState.RUNNING, True, False)]

    @pytest.mark.regression
    def test_hook_runs_outside_state_lock_and_pause_skips_remainder(self):
        runtime = RuntimeController()
        assert runtime.request_pause() is True
        assert runtime.complete_startup() is True

        first_entered = threading.Event()
        release_first = threading.Event()
        pause_finished = threading.Event()
        calls = []
        pause_results = []

        def first_hook():
            calls.append("first")
            first_entered.set()
            assert release_first.wait(timeout=1.0)

        def pause_while_hook_is_blocked():
            pause_results.append(runtime.request_pause())
            pause_finished.set()

        assert runtime.register_admission_open_hook("first", first_hook)
        assert runtime.register_admission_open_hook(
            "second", lambda: calls.append("second")
        )

        resume_thread = threading.Thread(target=runtime.resume)
        resume_thread.start()
        assert first_entered.wait(timeout=1.0)

        pause_thread = threading.Thread(target=pause_while_hook_is_blocked)
        pause_thread.start()
        lock_was_available = pause_finished.wait(timeout=0.5)
        release_first.set()
        resume_thread.join(timeout=1.0)
        pause_thread.join(timeout=1.0)

        assert lock_was_available is True
        assert not resume_thread.is_alive()
        assert not pause_thread.is_alive()
        assert pause_results == [True]
        assert runtime.state is EngineState.PAUSED
        assert calls == ["first"]

    @pytest.mark.regression
    def test_hook_exception_is_logged_and_does_not_block_later_hooks(
        self, caplog
    ):
        runtime = RuntimeController()
        calls = []

        def bad_hook():
            calls.append("bad")
            raise RuntimeError("hook failed")

        assert runtime.register_admission_open_hook("bad", bad_hook)
        assert runtime.register_admission_open_hook(
            "good", lambda: calls.append("good")
        )

        with caplog.at_level("ERROR", logger="RuntimeController"):
            assert runtime.complete_startup() is True

        assert calls == ["bad", "good"]
        assert runtime.state is EngineState.RUNNING
        assert "Admission-open hook 'bad' raised" in caplog.text

    @pytest.mark.regression
    def test_duplicate_rejected_and_unregister_is_idempotent(self):
        runtime = RuntimeController()
        hook = Mock(name="hook")
        assert runtime.register_admission_open_hook("owner", hook) is True

        with pytest.raises(ValueError, match="already registered"):
            runtime.register_admission_open_hook("owner", Mock())

        assert runtime.unregister_admission_open_hook("owner") is True
        assert runtime.unregister_admission_open_hook("owner") is False
        assert runtime.complete_startup() is True
        hook.assert_not_called()

    @pytest.mark.regression
    def test_reset_clears_registered_hooks(self):
        runtime = RuntimeController()
        hook = Mock(name="hook")
        assert runtime.register_admission_open_hook("owner", hook) is True

        runtime._reset_for_tests()

        assert runtime.complete_startup() is True
        hook.assert_not_called()

    @pytest.mark.regression
    @pytest.mark.parametrize("stopping_state", ["draining", "stopped", "signal"])
    def test_stopping_controller_rejects_registration(self, stopping_state):
        runtime = RuntimeController()
        if stopping_state == "draining":
            assert runtime.request_shutdown() is True
        elif stopping_state == "stopped":
            runtime.drain_and_stop(timeout_seconds=0.0)
            assert runtime.state is EngineState.STOPPED
        else:
            runtime.request_shutdown_from_signal()
            assert runtime.is_stopping() is True

        hook = Mock(name="hook")
        assert runtime.register_admission_open_hook("late", hook) is False
        hook.assert_not_called()


class TestStateTransitions:
    """The state machine is the contract. These must not regress."""

    @pytest.mark.regression
    def test_completed_startup_state_is_running(self, controller):
        assert controller.state is EngineState.RUNNING
        assert controller.is_admitting() is True
        assert controller.is_stopping() is False

    @pytest.mark.regression
    def test_pause_then_resume_round_trip(self, controller):
        assert controller.request_pause() is True
        assert controller.state is EngineState.PAUSED
        assert controller.is_admitting() is False

        assert controller.resume() is True
        assert controller.state is EngineState.RUNNING
        assert controller.is_admitting() is True

    @pytest.mark.regression
    def test_pause_is_idempotent(self, controller):
        assert controller.request_pause() is True
        # Second pause is a no-op and returns False.
        assert controller.request_pause() is False
        assert controller.state is EngineState.PAUSED

    @pytest.mark.regression
    def test_resume_only_works_from_paused(self, controller):
        # Resume from RUNNING is a no-op.
        assert controller.resume() is False
        assert controller.state is EngineState.RUNNING

    @pytest.mark.regression
    def test_shutdown_is_one_way(self, controller):
        assert controller.request_shutdown() is True
        assert controller.state is EngineState.DRAINING
        assert controller.is_stopping() is True

        # Cannot resume out of DRAINING.
        assert controller.resume() is False
        # Cannot pause out of DRAINING.
        assert controller.request_pause() is False

    @pytest.mark.regression
    def test_shutdown_from_paused_works(self, controller):
        controller.request_pause()
        assert controller.request_shutdown() is True
        assert controller.state is EngineState.DRAINING


class TestAdmissionGate:
    """The admission gate is what actually keeps new orders out during pause."""

    @pytest.mark.regression
    def test_originating_work_passes_when_running(self, controller):
        # Should not raise.
        controller.check_admission(INFLIGHT_REST_PLACE)
        controller.check_admission(INFLIGHT_STEALTH_REVEAL)

    @pytest.mark.regression
    def test_originating_work_rejected_when_paused(self, controller):
        controller.request_pause()
        with pytest.raises(EngineNotAdmittingError) as exc_info:
            controller.check_admission(INFLIGHT_REST_PLACE)
        assert exc_info.value.state is EngineState.PAUSED
        assert exc_info.value.category == INFLIGHT_REST_PLACE

    @pytest.mark.regression
    def test_originating_work_rejected_when_draining(self, controller):
        controller.request_shutdown()
        with pytest.raises(EngineNotAdmittingError):
            controller.check_admission(INFLIGHT_STEALTH_REVEAL)

    @pytest.mark.regression
    def test_cancellations_always_allowed_until_stopped(self, controller):
        # Cancellations must work in every non-terminal state so operators
        # can wind down existing positions during pause/drain.
        for transition in (controller.request_pause, controller.request_shutdown):
            fresh = RuntimeController()
            transition_method = getattr(fresh, transition.__name__)
            transition_method()
            # Should not raise.
            fresh.check_admission(INFLIGHT_REST_CANCEL)
            fresh.check_admission(INFLIGHT_FILL_PROCESSING)
            fresh.check_admission(INFLIGHT_DB_WRITE)

    @pytest.mark.regression
    def test_nothing_admitted_after_stopped(self, controller):
        controller.drain_and_stop(timeout_seconds=0.1)
        assert controller.state is EngineState.STOPPED
        # Even cancellations are blocked once fully stopped.
        with pytest.raises(EngineNotAdmittingError):
            controller.check_admission(INFLIGHT_REST_CANCEL)
        with pytest.raises(EngineNotAdmittingError):
            controller.check_admission(INFLIGHT_REST_PLACE)


class TestInflightTracking:
    """In-flight tracking guarantees that drains wait for critical sections."""

    @pytest.mark.regression
    def test_increments_and_decrements(self, controller):
        assert controller.total_inflight() == 0
        with controller.track_inflight(INFLIGHT_REST_PLACE):
            assert controller.total_inflight() == 1
            assert controller.inflight_snapshot() == {INFLIGHT_REST_PLACE: 1}
        assert controller.total_inflight() == 0
        assert controller.inflight_snapshot() == {}

    @pytest.mark.regression
    def test_decrements_on_exception(self, controller):
        with pytest.raises(ValueError):
            with controller.track_inflight(INFLIGHT_REST_PLACE):
                raise ValueError("boom")
        # Counter must drop to zero even when the wrapped block raises.
        assert controller.total_inflight() == 0

    @pytest.mark.regression
    def test_unadmitted_tracking_is_rejected_after_stopped(self, controller):
        controller.drain_and_stop(timeout_seconds=0.1)

        with pytest.raises(EngineNotAdmittingError) as exc_info:
            with controller.track_inflight(INFLIGHT_DB_WRITE):
                pass

        assert exc_info.value.state is EngineState.STOPPED
        assert controller.total_inflight() == 0

    @pytest.mark.regression
    def test_atomic_admission_registers_work_before_pause(self, controller):
        with controller.track_admitted_inflight(INFLIGHT_REST_PLACE):
            assert controller.inflight_snapshot() == {
                INFLIGHT_REST_PLACE: 1
            }
            assert controller.request_pause() is True
            assert controller.state is EngineState.PAUSED
            assert controller.inflight_snapshot() == {
                INFLIGHT_REST_PLACE: 1
            }

        assert controller.total_inflight() == 0

    @pytest.mark.regression
    def test_atomic_admission_rejects_work_after_pause(self, controller):
        assert controller.request_pause() is True

        with pytest.raises(EngineNotAdmittingError):
            with controller.track_admitted_inflight(INFLIGHT_REST_PLACE):
                pytest.fail("paused work must not enter the admitted context")

        assert controller.total_inflight() == 0

    @pytest.mark.regression
    def test_concurrent_increments(self, controller):
        # Drive 50 threads through the context manager simultaneously and
        # confirm the counter ends at zero with no lost decrements.
        N = 50
        ready = threading.Event()

        def worker():
            ready.wait()
            with controller.track_inflight(INFLIGHT_FILL_PROCESSING):
                time.sleep(0.01)

        threads = [threading.Thread(target=worker) for _ in range(N)]
        for t in threads:
            t.start()
        ready.set()
        for t in threads:
            t.join()

        assert controller.total_inflight() == 0


class TestDrain:
    """Drain orchestration must wait for in-flight work and call stop hooks."""

    @pytest.mark.regression
    def test_clean_drain_with_no_inflight(self, controller):
        result = controller.drain_and_stop(timeout_seconds=0.5)
        assert result.drained_clean is True
        assert result.state_after is EngineState.STOPPED
        assert result.inflight_at_timeout == {}

    @pytest.mark.regression
    def test_drain_invokes_registered_stop_hooks(self, controller):
        called = []

        controller.register_stop_hook("alpha", lambda: called.append("alpha"))
        controller.register_stop_hook("beta", lambda: called.append("beta"))

        controller.drain_and_stop(timeout_seconds=0.5)
        # Hooks invoked in registration order.
        assert called == ["alpha", "beta"]

    @pytest.mark.regression
    def test_drain_continues_when_a_hook_raises(self, controller):
        called = []

        def bad_hook():
            called.append("bad")
            raise RuntimeError("hook explosion")

        controller.register_stop_hook("bad", bad_hook)
        controller.register_stop_hook("good", lambda: called.append("good"))

        # Must not propagate hook exceptions; subsequent hooks still run.
        result = controller.drain_and_stop(timeout_seconds=0.5)
        assert called == ["bad", "good"]
        assert result.state_after is EngineState.STOPPED

    @pytest.mark.regression
    def test_late_hook_is_invoked_while_owning_drain_is_in_progress(
        self,
        controller,
    ):
        first_entered = threading.Event()
        release_first = threading.Event()
        called = []

        def first_hook():
            called.append("first_entered")
            first_entered.set()
            assert release_first.wait(timeout=1.0)
            called.append("first_returned")

        controller.register_stop_hook("first", first_hook)
        drain_thread = threading.Thread(
            target=lambda: controller.drain_and_stop(timeout_seconds=1.0)
        )
        drain_thread.start()
        assert first_entered.wait(timeout=1.0)

        queued = controller.register_stop_hook(
            "late",
            lambda: called.append("late"),
        )
        assert queued is False
        assert called == ["first_entered", "late"]

        release_first.set()
        drain_thread.join(timeout=1.0)
        assert not drain_thread.is_alive()
        assert called == ["first_entered", "late", "first_returned"]
        assert controller.state is EngineState.STOPPED

    @pytest.mark.regression
    def test_hook_registered_after_stopped_is_invoked_immediately(
        self,
        controller,
    ):
        controller.drain_and_stop(timeout_seconds=0.1)
        called = []

        queued = controller.register_stop_hook(
            "late",
            lambda: called.append("late"),
        )

        assert queued is False
        assert called == ["late"]

    @pytest.mark.regression
    def test_drain_waits_for_hook_registered_while_draining(
        self,
        controller,
    ):
        owner_hook_entered = threading.Event()
        release_owner_hook = threading.Event()
        late_hook_entered = threading.Event()
        release_late_hook = threading.Event()

        def owner_hook():
            owner_hook_entered.set()
            assert release_owner_hook.wait(timeout=1.0)

        def late_hook():
            late_hook_entered.set()
            assert release_late_hook.wait(timeout=1.0)

        controller.register_stop_hook("owner", owner_hook)
        drain_thread = threading.Thread(
            target=lambda: controller.drain_and_stop(timeout_seconds=1.0)
        )
        late_thread = threading.Thread(
            target=lambda: controller.register_stop_hook("late", late_hook)
        )

        drain_thread.start()
        assert owner_hook_entered.wait(timeout=1.0)
        late_thread.start()
        assert late_hook_entered.wait(timeout=1.0)
        release_owner_hook.set()
        time.sleep(0.02)

        assert drain_thread.is_alive()
        assert controller.state is EngineState.DRAINING

        release_late_hook.set()
        late_thread.join(timeout=1.0)
        drain_thread.join(timeout=1.0)
        assert not late_thread.is_alive()
        assert not drain_thread.is_alive()
        assert controller.state is EngineState.STOPPED

    @pytest.mark.regression
    def test_late_stop_hook_cannot_reenter_owning_drain(
        self,
        controller,
    ):
        owner_entered = threading.Event()
        release_owner = threading.Event()
        nested_errors = []

        def owner_hook():
            owner_entered.set()
            assert release_owner.wait(timeout=1.0)

        def late_hook():
            try:
                controller.drain_and_stop(timeout_seconds=0.5)
            except RuntimeError as exc:
                nested_errors.append(str(exc))

        controller.register_stop_hook("owner", owner_hook)
        drain_thread = threading.Thread(
            target=lambda: controller.drain_and_stop(timeout_seconds=1.0)
        )
        drain_thread.start()
        assert owner_entered.wait(timeout=1.0)

        late_thread = threading.Thread(
            target=lambda: controller.register_stop_hook("late", late_hook)
        )
        late_thread.start()
        late_thread.join(timeout=1.0)
        assert not late_thread.is_alive()
        assert nested_errors == [
            "drain_and_stop cannot be called from stop-hook execution"
        ]

        release_owner.set()
        drain_thread.join(timeout=1.0)
        assert not drain_thread.is_alive()
        assert controller.state is EngineState.STOPPED

    @pytest.mark.regression
    def test_work_started_during_late_hook_joins_same_terminal_wait(
        self,
        controller,
    ):
        owner_entered = threading.Event()
        release_owner = threading.Event()
        late_entered = threading.Event()
        release_late = threading.Event()
        work_entered = threading.Event()
        release_work = threading.Event()
        results = []

        def owner_hook():
            owner_entered.set()
            assert release_owner.wait(timeout=1.0)

        def late_hook():
            late_entered.set()
            assert release_late.wait(timeout=1.0)

        def late_work():
            with controller.track_inflight(INFLIGHT_DB_WRITE):
                work_entered.set()
                assert release_work.wait(timeout=1.0)

        controller.register_stop_hook("owner", owner_hook)
        drain_thread = threading.Thread(
            target=lambda: results.append(
                controller.drain_and_stop(timeout_seconds=1.0)
            )
        )
        drain_thread.start()
        assert owner_entered.wait(timeout=1.0)

        late_hook_thread = threading.Thread(
            target=lambda: controller.register_stop_hook("late", late_hook)
        )
        late_hook_thread.start()
        assert late_entered.wait(timeout=1.0)
        release_owner.set()

        work_thread = threading.Thread(target=late_work)
        work_thread.start()
        assert work_entered.wait(timeout=1.0)
        release_late.set()
        late_hook_thread.join(timeout=1.0)
        time.sleep(0.02)

        assert drain_thread.is_alive()
        assert controller.state is EngineState.DRAINING
        assert controller.inflight_snapshot() == {INFLIGHT_DB_WRITE: 1}

        release_work.set()
        work_thread.join(timeout=1.0)
        drain_thread.join(timeout=1.0)
        assert not work_thread.is_alive()
        assert not drain_thread.is_alive()
        assert len(results) == 1
        assert results[0].drained_clean is True
        assert results[0].inflight_at_timeout == {}
        assert controller.state is EngineState.STOPPED

    @pytest.mark.regression
    def test_concurrent_drains_have_one_owner_and_invoke_hooks_once(
        self,
        controller,
    ):
        hook_entered = threading.Event()
        release_hook = threading.Event()
        called = []
        results = []

        def hook():
            called.append("hook")
            hook_entered.set()
            assert release_hook.wait(timeout=1.0)

        controller.register_stop_hook("only", hook)

        def drain():
            results.append(controller.drain_and_stop(timeout_seconds=1.0))

        first = threading.Thread(target=drain)
        second = threading.Thread(target=drain)
        first.start()
        assert hook_entered.wait(timeout=1.0)
        second.start()
        time.sleep(0.02)
        assert called == ["hook"]
        release_hook.set()
        first.join(timeout=1.0)
        second.join(timeout=1.0)

        assert not first.is_alive()
        assert not second.is_alive()
        assert called == ["hook"]
        assert len(results) == 2
        assert results[0] is results[1]

    @pytest.mark.regression
    def test_recursive_drain_from_stop_hook_fails_fast(self, controller):
        nested_errors = []

        def recursive_hook():
            try:
                controller.drain_and_stop(timeout_seconds=0.1)
            except RuntimeError as exc:
                nested_errors.append(str(exc))

        controller.register_stop_hook("recursive", recursive_hook)

        result = controller.drain_and_stop(timeout_seconds=0.5)

        assert result.state_after is EngineState.STOPPED
        assert result.drained_clean is True
        assert nested_errors == [
            "drain_and_stop cannot be called from stop-hook execution"
        ]

    @pytest.mark.regression
    @pytest.mark.parametrize(
        "timeout",
        (
            float("nan"),
            float("inf"),
            1e308,
            -1.0,
            True,
            "not-a-number",
        ),
    )
    def test_invalid_timeout_is_rejected_before_state_change(
        self,
        controller,
        timeout,
    ):
        state_before = controller.state
        with pytest.raises(ValueError, match="finite non-negative"):
            controller.drain_and_stop(timeout_seconds=timeout)

        assert controller.state is state_before

    @pytest.mark.regression
    def test_drain_waits_for_inflight_work(self, controller):
        # Hold an in-flight slot for ~150 ms then release. The drain
        # call should block until release, then transition to STOPPED.
        release_at = time.monotonic() + 0.15

        def worker():
            with controller.track_inflight(INFLIGHT_REST_PLACE):
                while time.monotonic() < release_at:
                    time.sleep(0.01)

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        # Give the worker a moment to enter the context manager.
        time.sleep(0.02)

        result = controller.drain_and_stop(timeout_seconds=2.0)
        t.join(timeout=1.0)

        assert result.drained_clean is True
        assert result.duration_seconds >= 0.1
        assert result.state_after is EngineState.STOPPED

    @pytest.mark.regression
    def test_drain_reports_timeout_when_inflight_will_not_finish(self, controller):
        # Acquire an in-flight slot and never release it within the
        # timeout window — the drain must time out and report exactly
        # which categories are still in flight.
        gate = threading.Event()
        entered = threading.Event()

        def stuck_worker():
            with controller.track_inflight(INFLIGHT_STEALTH_REVEAL):
                entered.set()
                gate.wait(timeout=2.0)

        t = threading.Thread(target=stuck_worker, daemon=True)
        t.start()
        assert entered.wait(timeout=1.0)

        try:
            result = controller.drain_and_stop(timeout_seconds=0.2)
            assert result.drained_clean is False
            assert result.inflight_at_timeout == {INFLIGHT_STEALTH_REVEAL: 1}
            assert result.state_after is EngineState.STOPPED
        finally:
            gate.set()
            t.join(timeout=1.0)


class TestSingleton:
    """The module-level accessor must return one shared instance."""

    @pytest.mark.regression
    def test_get_runtime_controller_returns_singleton(self):
        a = get_runtime_controller()
        b = get_runtime_controller()
        assert a is b
        # Reset so we don't pollute other tests sharing the singleton.
        a._reset_for_tests()
