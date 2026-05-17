"""Runtime lifecycle controller for graceful pause / resume / shutdown.

Industry-standard "quiesce -> drain -> stop" model for trading engines.
This is the single source of truth for engine lifecycle state. Every
entry point that originates new work (REST order placement, stealth
reveal, dashboard order creation) must consult the controller via
``check_admission`` before proceeding, and every critical section that
must complete before shutdown must be wrapped in ``track_inflight``.

Design follows the integrated-by-design pattern: one shared state
object, one builder, exposed via ``get_runtime_controller()``.

State machine and admission rules are documented on
``core.enums.EngineState``.

Threading model
---------------
- ``_state_lock`` (RLock): guards state transitions.
- ``_inflight_lock`` (RLock): guards the per-category in-flight counters.
- ``_inflight_zero`` (Condition on ``_inflight_lock``): notified whenever
  the total in-flight count reaches zero, so ``wait_drain`` can return
  without polling.

The two locks have a strict ordering: ``_state_lock`` is acquired first
when both are needed, never the reverse. Callers of ``track_inflight``
only hold ``_inflight_lock`` for the increment/decrement, never around
user code, so there is no risk of deadlock with module-level locks.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import monotonic
from typing import Callable, Dict, Iterator, List, Optional

from core.enums import EngineState
from logging_service import get_logger


logger = get_logger("RuntimeController")


# Categories used by ``track_inflight``. Defined as constants so callers
# don't pass magic strings (per project rule P2 #5).
INFLIGHT_REST_PLACE = "rest_order_placement"
INFLIGHT_REST_CANCEL = "rest_order_cancellation"
INFLIGHT_FILL_PROCESSING = "fill_processing"
INFLIGHT_STEALTH_REVEAL = "stealth_reveal"
INFLIGHT_DB_WRITE = "db_write"


class EngineNotAdmittingError(RuntimeError):
    """Raised when work is rejected because the engine is not in RUNNING state.

    Attributes:
        state: Current engine state at time of rejection.
        category: Admission category that was rejected.
    """

    def __init__(self, state: EngineState, category: str) -> None:
        super().__init__(
            f"Engine refused {category!r}: state is {state.value} (not RUNNING)"
        )
        self.state = state
        self.category = category


# Categories that are *always* allowed even while paused/draining.
# Cancellations and fill processing are explicitly allowed so the engine
# can wind down existing positions safely.
_ALWAYS_ALLOWED = frozenset({
    INFLIGHT_REST_CANCEL,
    INFLIGHT_FILL_PROCESSING,
    INFLIGHT_DB_WRITE,
})


@dataclass
class DrainResult:
    """Outcome of a drain operation, captured for logging/audit."""

    state_before: EngineState
    state_after: EngineState
    duration_seconds: float
    drained_clean: bool
    inflight_at_timeout: Dict[str, int] = field(default_factory=dict)


class RuntimeController:
    """Singleton controller for engine lifecycle state and in-flight tracking.

    Use ``get_runtime_controller()`` to obtain the shared instance — do
    not construct this class directly outside of tests.
    """

    def __init__(self) -> None:
        self._state: EngineState = EngineState.RUNNING
        self._state_lock = threading.RLock()

        self._inflight: Dict[str, int] = {}
        self._inflight_lock = threading.RLock()
        self._inflight_zero = threading.Condition(self._inflight_lock)

        # Subsystem stop hooks registered by main.py (e.g. stealth bridge).
        # Called in registration order during drain.
        self._stop_hooks: List[tuple] = []  # list of (name, callable)

    # ------------------------------------------------------------------
    # State accessors
    # ------------------------------------------------------------------

    @property
    def state(self) -> EngineState:
        """Current engine lifecycle state (lock-guarded snapshot)."""
        with self._state_lock:
            return self._state

    def is_admitting(self) -> bool:
        """True iff the engine is RUNNING and accepting new work."""
        with self._state_lock:
            return self._state is EngineState.RUNNING

    def is_stopping(self) -> bool:
        """True iff a shutdown has been requested (DRAINING or STOPPED)."""
        with self._state_lock:
            return self._state in (EngineState.DRAINING, EngineState.STOPPED)

    # ------------------------------------------------------------------
    # Admission gate
    # ------------------------------------------------------------------

    def check_admission(self, category: str) -> None:
        """Raise ``EngineNotAdmittingError`` if ``category`` is not allowed now.

        Always-allowed categories (cancellations, fill processing, DB
        writes for in-flight work) pass through regardless of state until
        STOPPED. Originating categories (new order placement, stealth
        reveal of new slices) are gated on RUNNING.
        """
        with self._state_lock:
            state = self._state
        if state is EngineState.STOPPED:
            raise EngineNotAdmittingError(state, category)
        if category in _ALWAYS_ALLOWED:
            return
        if state is not EngineState.RUNNING:
            raise EngineNotAdmittingError(state, category)

    # ------------------------------------------------------------------
    # In-flight tracking
    # ------------------------------------------------------------------

    @contextmanager
    def track_inflight(self, category: str) -> Iterator[None]:
        """Mark a critical section as in-flight for the duration of the block.

        Wraps any operation that must complete (or be allowed to fail
        cleanly) before the engine shuts down — for example REST order
        placement or a multi-statement DB write.

        Does NOT call ``check_admission``; callers that need both should
        call ``check_admission`` first, then enter the context manager.
        That separation keeps cancellation / fill paths trackable even
        while the engine is paused.

        Always decrements on exit, even on exception, and notifies any
        waiter blocked in ``wait_drain``.
        """
        with self._inflight_lock:
            self._inflight[category] = self._inflight.get(category, 0) + 1
        try:
            yield
        finally:
            with self._inflight_lock:
                remaining = self._inflight.get(category, 0) - 1
                if remaining <= 0:
                    self._inflight.pop(category, None)
                else:
                    self._inflight[category] = remaining
                if not self._inflight:
                    self._inflight_zero.notify_all()

    def inflight_snapshot(self) -> Dict[str, int]:
        """Return a copy of current in-flight counters (for status / drain logs)."""
        with self._inflight_lock:
            return dict(self._inflight)

    def total_inflight(self) -> int:
        """Total in-flight operations across all categories."""
        with self._inflight_lock:
            return sum(self._inflight.values())

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def request_pause(self) -> bool:
        """Transition RUNNING -> PAUSING -> PAUSED (soft pause).

        Returns True if the transition was performed, False if the engine
        was not RUNNING (already paused / draining / stopped).

        Soft pause: stops admitting *new* orders. WS, fills, and cancels
        keep flowing so existing positions remain manageable.
        """
        with self._state_lock:
            if self._state is not EngineState.RUNNING:
                logger.info(
                    f"request_pause ignored: state is {self._state.value}"
                )
                return False
            self._state = EngineState.PAUSING
            logger.info("Engine state: RUNNING -> PAUSING (soft pause)")
            self._state = EngineState.PAUSED
            logger.info("Engine state: PAUSING -> PAUSED")
        return True

    def resume(self) -> bool:
        """Transition PAUSED -> RUNNING.

        Returns True if the transition was performed, False if the engine
        was not PAUSED.
        """
        with self._state_lock:
            if self._state is not EngineState.PAUSED:
                logger.info(f"resume ignored: state is {self._state.value}")
                return False
            self._state = EngineState.RUNNING
            logger.info("Engine state: PAUSED -> RUNNING")
        return True

    def request_shutdown(self) -> bool:
        """Transition any non-terminal state -> DRAINING.

        Returns True if the transition was performed, False if the engine
        was already DRAINING or STOPPED. This only flips the state — call
        ``drain_and_stop`` to perform the orchestrated drain.
        """
        with self._state_lock:
            if self._state in (EngineState.DRAINING, EngineState.STOPPED):
                logger.info(
                    f"request_shutdown ignored: state is {self._state.value}"
                )
                return False
            previous = self._state
            self._state = EngineState.DRAINING
            logger.info(f"Engine state: {previous.value} -> DRAINING")
        return True

    def _mark_stopped(self) -> None:
        with self._state_lock:
            self._state = EngineState.STOPPED
            logger.info("Engine state: DRAINING -> STOPPED")

    # ------------------------------------------------------------------
    # Drain orchestration
    # ------------------------------------------------------------------

    def register_stop_hook(self, name: str, hook: Callable[[], None]) -> None:
        """Register a subsystem stop callback to be invoked during drain.

        Hooks are called in registration order at the start of
        ``drain_and_stop``. Each hook should be idempotent and bounded
        (return promptly; do its own joining with timeout).
        """
        with self._state_lock:
            self._stop_hooks.append((name, hook))
            logger.info(f"Registered stop hook: {name}")

    def wait_drain(self, timeout_seconds: float) -> bool:
        """Block until in-flight count reaches zero or timeout expires.

        Returns True if drained cleanly, False on timeout.
        """
        deadline = monotonic() + timeout_seconds
        with self._inflight_lock:
            while self._inflight:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return False
                self._inflight_zero.wait(timeout=remaining)
        return True

    def drain_and_stop(self, timeout_seconds: float = 30.0) -> DrainResult:
        """Perform the full drain sequence and transition to STOPPED.

        Order of operations (industry standard for trading engines):
          1. Flip state to DRAINING (admission gate now rejects new orders).
          2. Invoke every registered subsystem stop hook (e.g. stealth
             bridge background loops). Hooks should stop *producers*
             before consumers.
          3. Wait for all tracked in-flight operations to complete, up to
             ``timeout_seconds``. Cancellations and fill processing are
             still allowed during this window so existing orders settle.
          4. Mark state STOPPED.
        """
        started = monotonic()
        state_before = self.state
        self.request_shutdown()  # idempotent; ensures DRAINING

        # Snapshot hooks under lock, then invoke without holding it.
        with self._state_lock:
            hooks = list(self._stop_hooks)

        for name, hook in hooks:
            try:
                logger.info(f"Drain: invoking stop hook {name!r}")
                hook()
            except Exception:
                logger.exception(f"Drain: stop hook {name!r} raised")

        drained = self.wait_drain(timeout_seconds)
        inflight_at_timeout = {} if drained else self.inflight_snapshot()
        if not drained:
            logger.warning(
                f"Drain timed out after {timeout_seconds:.1f}s with "
                f"in-flight operations remaining: {inflight_at_timeout}"
            )
        else:
            logger.info("Drain completed cleanly (no in-flight operations)")

        self._mark_stopped()
        return DrainResult(
            state_before=state_before,
            state_after=self._state,
            duration_seconds=monotonic() - started,
            drained_clean=drained,
            inflight_at_timeout=inflight_at_timeout,
        )

    # ------------------------------------------------------------------
    # Test support
    # ------------------------------------------------------------------

    def _reset_for_tests(self) -> None:
        """Reset to a fresh RUNNING state. ONLY for test fixtures."""
        with self._state_lock:
            self._state = EngineState.RUNNING
            self._stop_hooks.clear()
        with self._inflight_lock:
            self._inflight.clear()
            self._inflight_zero.notify_all()


_singleton: Optional[RuntimeController] = None
_singleton_lock = threading.Lock()


def get_runtime_controller() -> RuntimeController:
    """Return the process-wide RuntimeController singleton."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = RuntimeController()
    return _singleton
