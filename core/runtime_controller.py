"""Runtime lifecycle controller for graceful pause / resume / shutdown.

Industry-standard "quiesce -> drain -> stop" model for trading engines.
This is the single source of truth for engine lifecycle state. Every
entry point that originates new work (REST order placement, stealth
reveal, dashboard order creation) must consult the controller via
``check_admission`` before proceeding, and every critical section that
must complete before shutdown must be wrapped in ``track_inflight``. When
the admission decision and start of tracked work must be one atomic boundary,
callers use ``track_admitted_inflight``.

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
- ``_drain_lock`` (Lock): gives stop-hook execution and terminal publication
  one owner across signal, dashboard, and startup-failure callers.
- ``_late_stop_hooks_zero`` (Condition on ``_state_lock``): prevents a hook
  registered during DRAINING from outliving normal STOPPED publication.

The state and in-flight locks have a strict ordering: ``_state_lock`` is
acquired first when both are needed, never the reverse. Registration through
``track_inflight`` briefly holds that pair so its final zero check shares one
atomic boundary with STOPPED publication; neither lock is held around user
code.
"""

from __future__ import annotations

import math
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
INFLIGHT_STOP_HOOK = "stop_hook"


def validate_drain_timeout_seconds(value: object) -> float:
    """Return one finite, non-negative drain timeout.

    This boundary is shared by the runtime API and dashboard payload handling
    so NaN/infinity can never reach ``Condition.wait`` and strand DRAINING.
    """

    error_message = (
        "drain timeout must be a finite non-negative number within the "
        "platform wait limit"
    )
    if isinstance(value, bool):
        raise ValueError(error_message)
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(error_message) from exc
    if (
        not math.isfinite(timeout)
        or timeout < 0.0
        or timeout > threading.TIMEOUT_MAX
    ):
        raise ValueError(error_message)
    return timeout


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
        # Fail closed until the process entry point has completed hydration,
        # reconciliation, scheduler activation, and worker startup.  Tests or
        # embedded consumers that intentionally bypass main.py must call
        # ``complete_startup`` before originating work.
        self._state: EngineState = EngineState.STARTING
        self._state_lock = threading.RLock()
        self._startup_pause_requested = False
        # A Python signal handler cannot safely re-enter ``_state_lock`` on the
        # interrupted main thread. This plain sticky flag is its lock-free
        # admission-close handoff; the drain worker performs the real state
        # transition and cleanup afterward.
        self._shutdown_intent_requested = False

        self._inflight: Dict[str, int] = {}
        self._inflight_lock = threading.RLock()
        self._inflight_zero = threading.Condition(self._inflight_lock)

        # Subsystem stop hooks registered by main.py (e.g. stealth bridge).
        # Called in registration order during drain.
        self._stop_hooks: List[tuple] = []  # list of (name, callable)
        # Only one caller may own stop-hook execution and the terminal state
        # transition. Signal, dashboard, and startup-failure paths can race.
        self._drain_lock = threading.Lock()
        # A recursive drain from a stop hook must fail fast instead of making
        # the owning thread deadlock on the non-reentrant drain lock.
        self._drain_owner_thread_id: Optional[int] = None
        self._last_drain_result: Optional[DrainResult] = None
        # Hooks registered after DRAINING begins execute on their registering
        # thread. The owning drain waits for them before terminal publication.
        self._late_stop_hooks = 0
        self._late_stop_hooks_zero = threading.Condition(self._state_lock)
        # Detect drain recursion from both owning and DRAINING-time late hooks.
        self._stop_hook_context = threading.local()

    # ------------------------------------------------------------------
    # State accessors
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_lifecycle_snapshot(
        raw_state: EngineState,
        shutdown_intent_requested: bool,
    ) -> tuple[EngineState, bool, bool]:
        """Derive one internally consistent state/admission/stop snapshot."""

        effective_state = raw_state
        if (
            shutdown_intent_requested
            and raw_state not in (EngineState.DRAINING, EngineState.STOPPED)
        ):
            effective_state = EngineState.DRAINING
        is_admitting = (
            not shutdown_intent_requested
            and raw_state is EngineState.RUNNING
        )
        is_stopping = (
            shutdown_intent_requested
            or raw_state in (EngineState.DRAINING, EngineState.STOPPED)
        )
        return effective_state, is_admitting, is_stopping

    @property
    def state(self) -> EngineState:
        """Current effective lifecycle state (snapshot, lock-free read)."""
        return self._derive_lifecycle_snapshot(
            self._state,
            self._shutdown_intent_requested,
        )[0]

    def is_admitting(self) -> bool:
        """True iff the engine is RUNNING and accepting new work."""
        return self._derive_lifecycle_snapshot(
            self._state,
            self._shutdown_intent_requested,
        )[1]

    def is_stopping(self) -> bool:
        """True iff a shutdown has been requested (DRAINING or STOPPED)."""
        return self._derive_lifecycle_snapshot(
            self._state,
            self._shutdown_intent_requested,
        )[2]

    def lifecycle_snapshot(self) -> tuple[EngineState, bool, bool]:
        """Return coherent ``(state, is_admitting, is_stopping)`` values."""

        with self._state_lock:
            return self._derive_lifecycle_snapshot(
                self._state,
                self._shutdown_intent_requested,
            )

    def startup_pause_pending(self) -> bool:
        """Return whether STARTING will complete into PAUSED."""
        with self._state_lock:
            return (
                self._state is EngineState.STARTING
                and not self._shutdown_intent_requested
                and self._startup_pause_requested
            )

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
        state = self.state
        if state is EngineState.STOPPED:
            raise EngineNotAdmittingError(state, category)
        if category in _ALWAYS_ALLOWED:
            return
        if state is not EngineState.RUNNING:
            raise EngineNotAdmittingError(state, category)

    # ------------------------------------------------------------------
    # In-flight tracking
    # ------------------------------------------------------------------

    def _register_inflight_with_state_lock(
        self,
        category: str,
    ) -> None:
        """Increment one category while the caller owns ``_state_lock``."""

        with self._inflight_lock:
            self._inflight[category] = self._inflight.get(category, 0) + 1

    def _release_inflight(self, category: str) -> None:
        """Decrement one category and notify the shared zero waiter."""

        with self._inflight_lock:
            remaining = self._inflight.get(category, 0) - 1
            if remaining <= 0:
                self._inflight.pop(category, None)
            else:
                self._inflight[category] = remaining
            if not self._inflight:
                self._inflight_zero.notify_all()

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
        # DRAINING still permits completion/cancel/fill work, but registration
        # must share the terminal state boundary so no new operation can enter
        # after the drain atomically publishes STOPPED.
        with self._state_lock:
            state = self.state
            if state is EngineState.STOPPED:
                raise EngineNotAdmittingError(state, category)
            self._register_inflight_with_state_lock(category)
        try:
            yield
        finally:
            self._release_inflight(category)

    @contextmanager
    def track_admitted_inflight(self, category: str) -> Iterator[None]:
        """Atomically admit originating work and register it as in flight.

        The state lock is held across the admission check and counter
        increment. A concurrent pause/shutdown therefore has only two valid
        outcomes: it wins first and this context raises, or this work is
        registered before the state transition and may finish as pre-existing
        in-flight work. User code runs without either controller lock held.
        """

        with self._state_lock:
            self.check_admission(category)
            self._register_inflight_with_state_lock(category)

        try:
            yield
        finally:
            self._release_inflight(category)

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

    def complete_startup(self) -> bool:
        """Publish startup readiness as RUNNING or a latched PAUSED state.

        This is the sole service-admission transition out of STARTING.  A
        pause requested while startup was in progress is consumed here and
        cannot be bypassed by the automatic readiness transition.  Shutdown
        always wins: this method never resurrects DRAINING or STOPPED.

        Returns True when STARTING was completed, otherwise False.
        """
        with self._state_lock:
            if self._state is not EngineState.STARTING:
                logger.info(
                    f"complete_startup ignored: state is {self._state.value}"
                )
                return False

            if self._shutdown_intent_requested:
                self._state = EngineState.DRAINING
                logger.info(
                    "Engine state: STARTING -> DRAINING "
                    "(signal shutdown won readiness)"
                )
                return False

            if self._startup_pause_requested:
                self._state = EngineState.PAUSED
                self._startup_pause_requested = False
                logger.info(
                    "Engine state: STARTING -> PAUSED "
                    "(startup pause request honored)"
                )
            else:
                self._state = EngineState.RUNNING
                logger.info("Engine state: STARTING -> RUNNING")
        return True

    def request_pause(self) -> bool:
        """Request a soft pause without opening an early-startup resume path.

        During STARTING the first request is latched while state remains
        STARTING.  ``complete_startup`` will then publish PAUSED instead of
        RUNNING.  Remaining in STARTING ensures ``resume`` cannot admit work
        before startup readiness.

        From RUNNING this transitions RUNNING -> PAUSING -> PAUSED. Returns
        True if a new pause request was accepted, otherwise False.

        Soft pause: stops admitting *new* orders. WS, fills, and cancels
        keep flowing so existing positions remain manageable.
        """
        with self._state_lock:
            if self._shutdown_intent_requested:
                logger.info("request_pause ignored: shutdown intent requested")
                return False
            if self._state is EngineState.STARTING:
                if self._startup_pause_requested:
                    logger.info(
                        "request_pause ignored: startup pause already requested"
                    )
                    return False
                self._startup_pause_requested = True
                logger.info(
                    "Engine startup pause requested; remaining STARTING "
                    "until readiness completes"
                )
                return True
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
            if self._shutdown_intent_requested:
                logger.info("resume ignored: shutdown intent requested")
                return False
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
            self._shutdown_intent_requested = True
            if self._state in (EngineState.DRAINING, EngineState.STOPPED):
                logger.info(
                    f"request_shutdown ignored: state is {self._state.value}"
                )
                return False
            previous = self._state
            self._state = EngineState.DRAINING
            logger.info(f"Engine state: {previous.value} -> DRAINING")
        return True

    def request_shutdown_from_signal(self) -> None:
        """Close admission from a Python signal handler without taking locks.

        The handler may interrupt the main thread while it owns
        ``_state_lock``. A plain attribute assignment is therefore the entire
        operation; the delegated drain thread calls :meth:`request_shutdown`
        for the serialized state transition.
        """

        self._shutdown_intent_requested = True

    # ------------------------------------------------------------------
    # Drain orchestration
    # ------------------------------------------------------------------

    def register_stop_hook(self, name: str, hook: Callable[[], None]) -> bool:
        """Register a subsystem stop callback to be invoked during drain.

        Hooks are called in registration order at the start of
        ``drain_and_stop``. Each hook should be idempotent and bounded
        (return promptly; do its own joining with timeout).

        Registration is lifecycle-aware. If draining has already begun, the
        hook is invoked immediately outside the state lock instead of being
        queued behind a stop-hook snapshot that may already have been taken.

        Returns True when queued for the owning drain, or False when invoked
        immediately because the runtime was already stopping.
        """
        with self._state_lock:
            # Use the effective state so the lock-free signal handoff has the
            # same lifecycle semantics as the serialized DRAINING transition.
            state = self.state
            if state not in (EngineState.DRAINING, EngineState.STOPPED):
                self._stop_hooks.append((name, hook))
                logger.info(f"Registered stop hook: {name}")
                return True
            track_for_drain = state is EngineState.DRAINING
            if track_for_drain:
                self._late_stop_hooks += 1

        logger.info(
            f"Runtime already {state.value}; invoking late stop hook "
            f"{name!r} immediately"
        )
        try:
            self._invoke_stop_hook(name, hook)
        finally:
            if track_for_drain:
                with self._state_lock:
                    self._late_stop_hooks -= 1
                    if self._late_stop_hooks == 0:
                        self._late_stop_hooks_zero.notify_all()
        return False

    def start_startup_component(
        self,
        name: str,
        start: Callable[[], None],
        stop: Callable[[], None],
    ) -> bool:
        """Register then start one short-lived startup action atomically.

        This helper is intentionally limited to bounded ``start`` methods
        such as spawning the periodic reconciler thread. Holding the state
        lock makes shutdown observe exactly one of two outcomes: it wins
        before registration and no component starts, or it runs afterward
        with the fully registered component in its hook snapshot.

        Returns False without starting when the runtime is no longer
        STARTING. A start exception propagates while retaining the stop hook
        so the startup-failure drain can clean partial initialization.
        """
        with self._state_lock:
            if (
                self._state is not EngineState.STARTING
                or self._shutdown_intent_requested
            ):
                logger.info(
                    f"Startup component {name!r} refused: state is "
                    f"{self.state.value}"
                )
                return False
            self._stop_hooks.append((name, stop))
            logger.info(f"Registered stop hook: {name}")
            start()
            return True

    def _invoke_stop_hook(self, name: str, hook: Callable[[], None]) -> None:
        """Invoke one bounded idempotent stop hook without controller locks."""
        previous_depth = getattr(self._stop_hook_context, "depth", 0)
        self._stop_hook_context.depth = previous_depth + 1
        try:
            logger.info(f"Drain: invoking stop hook {name!r}")
            hook()
        except Exception:
            logger.exception(f"Drain: stop hook {name!r} raised")
        finally:
            self._stop_hook_context.depth = previous_depth

    def wait_drain(self, timeout_seconds: float) -> bool:
        """Block until in-flight count reaches zero or timeout expires.

        Returns True if drained cleanly, False on timeout.
        """
        timeout_seconds = validate_drain_timeout_seconds(timeout_seconds)
        deadline = monotonic() + timeout_seconds
        with self._inflight_lock:
            while self._inflight:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return False
                self._inflight_zero.wait(timeout=remaining)
        return True

    def _mark_stopped_with_snapshot(
        self,
    ) -> tuple[bool, Dict[str, int], int]:
        """Atomically close registration and snapshot unfinished work."""

        with self._state_lock:
            with self._inflight_lock:
                inflight = dict(self._inflight)
                late_hooks = self._late_stop_hooks
                self._state = EngineState.STOPPED
                logger.info("Engine state: DRAINING -> STOPPED")
        return not inflight and late_hooks == 0, inflight, late_hooks

    def _wait_for_terminal_quiescence(
        self,
        timeout_seconds: float,
    ) -> tuple[bool, Dict[str, int], int]:
        """Wait for inflight work and late hooks, then atomically stop.

        Inflight registration and the final zero check share state->inflight
        lock order. Work may still begin during DRAINING, but it either joins
        this wait or observes STOPPED and is rejected.
        """
        deadline = monotonic() + timeout_seconds
        while True:
            remaining = max(0.0, deadline - monotonic())
            if not self.wait_drain(remaining):
                return self._mark_stopped_with_snapshot()

            with self._state_lock:
                while self._late_stop_hooks:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        return self._mark_stopped_with_snapshot()
                    self._late_stop_hooks_zero.wait(timeout=remaining)

                # ``track_inflight`` needs state_lock before inflight_lock.
                # Holding both makes zero-check + STOPPED one boundary.
                with self._inflight_lock:
                    if not self._inflight:
                        self._state = EngineState.STOPPED
                        logger.info("Engine state: DRAINING -> STOPPED")
                        return True, {}, 0

            if monotonic() >= deadline:
                return self._mark_stopped_with_snapshot()

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
        timeout_seconds = validate_drain_timeout_seconds(timeout_seconds)
        if getattr(self._stop_hook_context, "depth", 0):
            raise RuntimeError(
                "drain_and_stop cannot be called from stop-hook execution"
            )
        current_thread_id = threading.get_ident()
        with self._state_lock:
            if self._drain_owner_thread_id == current_thread_id:
                raise RuntimeError(
                    "drain_and_stop cannot be called recursively from its "
                    "own stop-hook execution"
                )

        with self._drain_lock:
            if self._last_drain_result is not None:
                return self._last_drain_result

            with self._state_lock:
                self._drain_owner_thread_id = current_thread_id
            try:
                started = monotonic()
                deadline = started + timeout_seconds
                state_before = self._state
                self.request_shutdown()  # idempotent; ensures DRAINING

                # Snapshot hooks under lock, then invoke without holding it. A
                # later registration observes DRAINING and invokes itself rather
                # than being stranded behind this snapshot.
                with self._state_lock:
                    hooks = list(self._stop_hooks)

                for name, hook in hooks:
                    self._invoke_stop_hook(name, hook)

                drained, inflight_at_timeout, late_hooks_at_timeout = (
                    self._wait_for_terminal_quiescence(
                        max(0.0, deadline - monotonic())
                    )
                )
                if late_hooks_at_timeout:
                    inflight_at_timeout[INFLIGHT_STOP_HOOK] = (
                        late_hooks_at_timeout
                    )
                if not drained:
                    logger.warning(
                        f"Drain timed out after {timeout_seconds:.1f}s with "
                        "in-flight operations remaining: "
                        f"{inflight_at_timeout}"
                    )
                else:
                    logger.info(
                        "Drain completed cleanly (no in-flight operations)"
                    )

                result = DrainResult(
                    state_before=state_before,
                    state_after=self._state,
                    duration_seconds=monotonic() - started,
                    drained_clean=drained,
                    inflight_at_timeout=inflight_at_timeout,
                )
                self._last_drain_result = result
                return result
            finally:
                with self._state_lock:
                    self._drain_owner_thread_id = None

    # ------------------------------------------------------------------
    # Test support
    # ------------------------------------------------------------------

    def _reset_for_tests(self) -> None:
        """Reset to a fresh STARTING state. ONLY for test fixtures."""
        with self._drain_lock:
            with self._state_lock:
                self._state = EngineState.STARTING
                self._startup_pause_requested = False
                self._shutdown_intent_requested = False
                self._stop_hooks.clear()
                self._drain_owner_thread_id = None
                self._last_drain_result = None
                self._late_stop_hooks = 0
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
