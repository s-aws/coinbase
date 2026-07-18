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

import pytest

from core.enums import EngineState
from core.runtime_controller import (
    INFLIGHT_DB_WRITE,
    INFLIGHT_FILL_PROCESSING,
    INFLIGHT_OPERATOR_FOLLOW_UP_INTENT,
    INFLIGHT_REST_CANCEL,
    INFLIGHT_REST_PLACE,
    INFLIGHT_STEALTH_REVEAL,
    EngineNotAdmittingError,
    RuntimeController,
    get_runtime_controller,
)


@pytest.fixture
def controller():
    """Fresh, isolated controller instance for each test (no singleton sharing)."""
    return RuntimeController()


class TestStateTransitions:
    """The state machine is the contract. These must not regress."""

    @pytest.mark.regression
    def test_initial_state_is_running(self, controller):
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
        controller.check_admission(INFLIGHT_OPERATOR_FOLLOW_UP_INTENT)

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
        with pytest.raises(EngineNotAdmittingError):
            controller.check_admission(INFLIGHT_OPERATOR_FOLLOW_UP_INTENT)

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
