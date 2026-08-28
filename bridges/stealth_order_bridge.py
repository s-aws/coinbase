"""Stealth Order Bridge - Integrates the unified order system with OrderEngine.

Provides background tasks for:
- Condition evaluation (checks if reveal conditions are met)
- Reveal trigger management (executes reveals when conditions trigger)
- Database reconciliation (syncs in-memory state with PostgreSQL)

The bridge connects StealthOrderManager (responsible for order creation and state)
with OrderEngine (responsible for event processing and follow-up creation).
"""

import math
import threading
import time
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, Tuple

from bridges.stealth_event_deadline_scheduler import (
    DeadlineWake,
    MarketEvent,
    MarketEventQueueFullError,
    SchedulerItem,
    SchedulerStoppedError,
    StealthEventDeadlineScheduler,
)
from business.stealth_condition_evaluator import get_evaluator
from core.enums import (
    RevealConditionType,
    StealthOrderStatus,
    StealthWakePurpose,
)
from core.stealth_order_manager import StealthOrderManager
from core.models import MarketData, RepricingPolicy
from core.runtime_controller import (
    INFLIGHT_REST_PLACE,
    INFLIGHT_STEALTH_REVEAL,
    EngineNotAdmittingError,
    get_runtime_controller,
)
from calculation.formatter import safe_float
from logging_service import get_logger


logger = get_logger("StealthOrderBridge")


class StealthOrderBridge:
    """Bridges StealthOrderManager with OrderEngine.
    
    Runs background tasks to evaluate conditions and trigger reveals
    based on market data updates.
    """
    
    _MARKET_EVENT_QUEUE_LIMIT = 10_000
    _COMPATIBILITY_RECHECK_SECONDS = 0.1
    _ADMISSION_RETRY_SECONDS = 0.1
    _OVERDUE_DEADLINE_RETRY_SECONDS = 0.1
    _CONDITION_WAKE_PURPOSES = (
        StealthWakePurpose.CONDITION_HOLD,
        StealthWakePurpose.TIME_DELAY,
        StealthWakePurpose.ADMISSION_RETRY,
        StealthWakePurpose.COMPATIBILITY_RECHECK,
    )
    _CONTINUOUS_MARKET_CONDITION_TYPES = {
        RevealConditionType.PRICE_THRESHOLD.value,
        RevealConditionType.SPREAD.value,
    }

    def __init__(
        self,
        stealth_manager: StealthOrderManager,
        order_engine,
        *,
        scheduler: Optional[StealthEventDeadlineScheduler] = None,
    ):
        """
        Initialize the stealth order bridge.
        
        Args:
            stealth_manager: StealthOrderManager instance
            order_engine: OrderEngine instance for market data and order placement
        """
        self.stealth_manager = stealth_manager
        self.order_engine = order_engine
        # Pass order_engine's log_message to stealth_manager for consistent logging
        if hasattr(order_engine, 'log_message'):
            self.stealth_manager.log_callback = order_engine.log_message
        self.evaluation_thread = None
        self.reconciliation_thread = None
        self.running = False
        # Drives interruptible sleeps in the background loops so stop()
        # collapses near-instantly instead of waiting out the current
        # tick. Set by stop() / cleared on (re)start.
        self._shutdown_event = threading.Event()
        # Startup hydration may run before exchange/local reconciliation.  The
        # scheduler can accept derived deadlines during that window, but its
        # single consumer is deliberately not started until main.py declares
        # reconciliation complete via activate_decisions().
        self._decisions_ready = threading.Event()
        self._scheduler_failure_lock = threading.Lock()
        self._scheduler_failure_reported = False
        self._market_event_time_lock = threading.RLock()
        self._last_market_event_time: Dict[str, datetime] = {}
        self._order_action_locks_guard = threading.Lock()
        self._order_action_locks: Dict[str, threading.RLock] = {}
        # Anchor deadlines do not execute exchange/database work on the
        # decision worker.  They only mark an order due; the next live ticker
        # for that product consumes the marker on the historical ticker path.
        # Lock order is always anchor handoff -> scheduler Condition.  The
        # reentrant form lets full-order rebuilds call the one anchor-lane
        # helper while keeping invalidation+replacement atomic to ticker
        # claims.
        self._anchor_due_lock = threading.RLock()
        # Value = (claimed generation, original monotonic deadline). Keeping
        # deadline eligibility in the handoff prevents a ticker received just
        # before expiry from being treated as the first post-deadline ticker if
        # slower dashboard/metrics work lets the worker publish the marker.
        self._anchor_due_generations: Dict[str, Tuple[int, float]] = {}
        self.scheduler = scheduler or StealthEventDeadlineScheduler(
            market_queue_limit=self._MARKET_EVENT_QUEUE_LIMIT,
            thread_name="StealthOrderBridge-Evaluator",
        )
        self.stealth_manager.set_schedule_invalidation_callback(
            self._handle_order_schedule_change
        )
    
    def start(self):
        """Start background evaluation and reconciliation threads.
        
        Initializes local state and reconciliation.  Decision processing is
        activated separately, after startup exchange reconciliation, by
        :meth:`activate_decisions`.
        """
        if self.running:
            return

        self.stealth_manager.set_schedule_invalidation_callback(
            self._handle_order_schedule_change
        )

        # Load existing stealth orders from database.  Zero rows is valid, but
        # a failed/partial load is not: activating decisions from an incomplete
        # local snapshot would violate the startup safety barrier.
        loaded_count = self.stealth_manager.load_all_active_orders_from_db()
        if not getattr(
            self.stealth_manager,
            "_last_hydration_complete",
            True,
        ):
            self.stealth_manager.set_schedule_invalidation_callback(None)
            raise RuntimeError(
                "Stealth order database hydration did not complete"
            )
        logger.info(f"Loaded {loaded_count} existing stealth orders from database")

        self._shutdown_event.clear()
        self._decisions_ready.clear()
        with self._scheduler_failure_lock:
            self._scheduler_failure_reported = False
        self.running = True
        
        # Start reconciliation thread (sync with database every 30s)
        self.reconciliation_thread = threading.Thread(
            target=self.reconcile_stealth_orders_periodically,
            kwargs={"interval_seconds": 30},
            daemon=True,
            name="StealthOrderBridge-Reconciliation"
        )
        self.reconciliation_thread.start()
        
        logger.info(
            "Stealth order bridge started; decision scheduler awaiting "
            "startup reconciliation"
        )

    def activate_decisions(self) -> None:
        """Start the single scheduler consumer after startup reconciliation."""

        if not self.running:
            raise RuntimeError("Stealth order bridge must be started before activation")
        if self._decisions_ready.is_set():
            return

        # Build disposable scheduling state from the manager's authoritative
        # hydrated snapshot before allowing the worker to consume anything.
        for stealth_order_id in self.stealth_manager.snapshot_active_stealth_orders():
            # Startup is strict: unlike a runtime invalidation callback, one
            # malformed/unschedulable active row must block readiness rather
            # than leave an apparently healthy but incomplete decision set.
            self._schedule_order(str(stealth_order_id))

        # Strict schedule construction is complete. Publish readiness before
        # starting the consumer so prequeued events/zero deadlines cannot run
        # in a set-after-start gap. Any start/death path clears it again.
        self._decisions_ready.set()
        try:
            self.evaluation_thread = self.scheduler.start(
                on_market_event=self._handle_market_event,
                on_deadline=self._handle_deadline_wake,
                on_error=self._handle_scheduler_error,
                on_fatal=self._handle_scheduler_fatal,
                daemon=True,
            )
        except Exception:
            self._decisions_ready.clear()
            raise
        if (
            self.scheduler.stopped
            or not self.evaluation_thread.is_alive()
        ):
            self._decisions_ready.clear()
            worker_error = self.scheduler.worker_error
            raise RuntimeError(
                "Stealth decision scheduler failed during activation"
                + (
                    f": {type(worker_error).__name__}: {worker_error}"
                    if worker_error is not None
                    else ""
                )
            )
        logger.info("Stealth decision scheduler activated")
    
    def stop(self):
        """Stop background evaluation and reconciliation threads.

        Idempotent. Sets the shared shutdown event so loops exit at the
        next interruptible wait point (not at the end of the current
        sleep tick), then joins each thread with a generous safety
        ceiling. Typical observed shutdown latency is < 100ms.
        """
        if not self.running and not self._shutdown_event.is_set():
            return
        self.running = False
        self._shutdown_event.set()
        self._decisions_ready.clear()
        with self._anchor_due_lock:
            self._anchor_due_generations.clear()
        self.stealth_manager.set_schedule_invalidation_callback(None)
        self.scheduler.stop(join_timeout=5)
        if hasattr(self, 'reconciliation_thread') and self.reconciliation_thread:
            self.reconciliation_thread.join(timeout=5)
        logger.info("Stealth order bridge stopped")

    def _invalidate_order_deadlines(self, stealth_order_id: str) -> None:
        """Invalidate every derived wake for one logical client_order_id."""

        self._invalidate_condition_deadlines(stealth_order_id)
        with self._anchor_due_lock:
            self._anchor_due_generations.pop(stealth_order_id, None)
            try:
                self.scheduler.invalidate_deadline(
                    stealth_order_id,
                    StealthWakePurpose.ANCHOR_REPRICE,
                )
            except SchedulerStoppedError:
                self._fail_closed_scheduler(
                    "deadline invalidation rejected by stopped scheduler"
                )

    def _invalidate_condition_deadlines(self, stealth_order_id: str) -> None:
        """Invalidate condition/reveal wakes without touching anchor cadence."""

        for purpose in self._CONDITION_WAKE_PURPOSES:
            try:
                self.scheduler.invalidate_deadline(stealth_order_id, purpose)
            except SchedulerStoppedError:
                self._fail_closed_scheduler(
                    "condition invalidation rejected by stopped scheduler"
                )
                return

    @staticmethod
    def _seconds_until(deadline_utc: Optional[datetime]) -> Optional[float]:
        if deadline_utc is None:
            return None
        parsed = StealthOrderManager._parse_runtime_datetime(deadline_utc)
        if parsed is None:
            return None
        return max(0.0, (parsed - datetime.utcnow()).total_seconds())

    def _schedule_order(
        self,
        stealth_order_id: str,
        *,
        minimum_condition_delay: float = 0.0,
        defer_overdue_continuous: bool = False,
    ) -> None:
        """Rebuild all disposable deadlines from one authoritative order row."""

        with self._get_order_action_lock(stealth_order_id):
            self._schedule_order_locked(
                stealth_order_id,
                minimum_condition_delay=minimum_condition_delay,
                defer_overdue_continuous=defer_overdue_continuous,
            )

    def _schedule_order_locked(
        self,
        stealth_order_id: str,
        *,
        minimum_condition_delay: float = 0.0,
        defer_overdue_continuous: bool = False,
    ) -> None:
        """Rebuild one order while its bridge action lock is held."""

        # Condition and anchor lanes have independent ownership.  Leave the
        # existing anchor deadline live while rebuilding the condition lane;
        # `_schedule_anchor_wake` then swaps the anchor generation atomically
        # with respect to ticker claims.
        self._invalidate_condition_deadlines(stealth_order_id)

        order = self.stealth_manager.in_memory_orders.get(stealth_order_id)
        self._schedule_condition_wake(
            stealth_order_id,
            order=order,
            minimum_delay=minimum_condition_delay,
            defer_overdue_continuous=defer_overdue_continuous,
            invalidate_existing=False,
        )
        self._schedule_anchor_wake(
            stealth_order_id,
            order=order,
            minimum_delay=minimum_condition_delay,
            invalidate_existing=True,
        )

    def _schedule_condition_wake(
        self,
        stealth_order_id: str,
        *,
        order: Optional[Dict[str, Any]] = None,
        minimum_delay: float = 0.0,
        defer_overdue_continuous: bool = False,
        invalidate_existing: bool = True,
    ) -> None:
        """Rebuild only condition/admission wakes for one logical order."""

        if invalidate_existing:
            self._invalidate_condition_deadlines(stealth_order_id)
        if order is None:
            order = self.stealth_manager.in_memory_orders.get(stealth_order_id)
        if not order:
            return
        if order.get("status") in {
            StealthOrderStatus.ERROR.value,
            StealthOrderStatus.EXECUTED.value,
            StealthOrderStatus.CANCELLED.value,
        }:
            return
        if float(order.get("remaining_size", 0) or 0) <= 0:
            return

        status = order.get("status")
        condition_type = str(
            order.get("reveal_condition_type")
            or RevealConditionType.TIME_DELAY.value
        ).lower()
        condition_config = order.get("reveal_condition_json") or {}

        if status == StealthOrderStatus.TRIGGERED.value:
            self.scheduler.schedule_after(
                stealth_order_id,
                StealthWakePurpose.ADMISSION_RETRY,
                max(minimum_delay, self._ADMISSION_RETRY_SECONDS),
            )
        else:
            evaluator = get_evaluator(condition_type)
            deadline = evaluator.resolve_stable_deadline(
                condition_config,
                order,
            )
            if not deadline.valid:
                raise ValueError(
                    f"Invalid {condition_type} condition for "
                    f"{stealth_order_id}: {deadline.reason}"
                )
            if deadline.available:
                delay = self._seconds_until(deadline.deadline_utc)
                if delay is not None:
                    is_continuous = condition_type in {
                        RevealConditionType.PRICE_THRESHOLD.value,
                        RevealConditionType.SPREAD.value,
                    }
                    if not (
                        is_continuous
                        and defer_overdue_continuous
                        and delay <= 0
                    ):
                        purpose = (
                            StealthWakePurpose.CONDITION_HOLD
                            if is_continuous
                            else StealthWakePurpose.TIME_DELAY
                        )
                        self.scheduler.schedule_after(
                            stealth_order_id,
                            purpose,
                            max(delay, minimum_delay),
                        )
            elif (
                deadline.supported
                and condition_type == RevealConditionType.TIME_DELAY.value
            ):
                # A fixed time condition without a usable creation/deadline
                # timestamp has no event that can ever repair it.  Startup
                # activation must fail closed instead of declaring readiness
                # with an unscheduled active order.
                raise ValueError(
                    f"Cannot schedule fixed time condition for "
                    f"{stealth_order_id}: {deadline.reason}"
                )
            elif not deadline.supported:
                # Existing jitter/volume/ratio/composite semantics remain on
                # one compatibility cadence; they are not redefined here.
                self.scheduler.schedule_after(
                    stealth_order_id,
                    StealthWakePurpose.COMPATIBILITY_RECHECK,
                    max(
                        minimum_delay,
                        self._COMPATIBILITY_RECHECK_SECONDS,
                    ),
                )

    def _schedule_anchor_wake(
        self,
        stealth_order_id: str,
        *,
        order: Optional[Dict[str, Any]] = None,
        minimum_delay: float = 0.0,
        invalidate_existing: bool = True,
    ) -> None:
        """Rebuild only the anchor deadline, preserving condition cadence."""

        with self._anchor_due_lock:
            if invalidate_existing:
                self._anchor_due_generations.pop(stealth_order_id, None)
                try:
                    self.scheduler.invalidate_deadline(
                        stealth_order_id,
                        StealthWakePurpose.ANCHOR_REPRICE,
                    )
                except SchedulerStoppedError:
                    self._fail_closed_scheduler(
                        "anchor invalidation rejected by stopped scheduler"
                    )
                    return
            if order is None:
                order = self.stealth_manager.in_memory_orders.get(
                    stealth_order_id
                )
            if not order:
                return
            if order.get("status") in {
                StealthOrderStatus.ERROR.value,
                StealthOrderStatus.EXECUTED.value,
                StealthOrderStatus.CANCELLED.value,
            }:
                return
            if (
                order.get("status") != StealthOrderStatus.REVEALED.value
                and float(order.get("remaining_size", 0) or 0) <= 0
            ):
                return

            policy = RepricingPolicy.from_dict(
                order.get("anchor_repricing_policy_json")
            )
            anchor_eligible = (
                policy.enabled
                and (
                    order.get("status") != StealthOrderStatus.REVEALED.value
                    or policy.allow_revealed_reprice
                )
            )
            if anchor_eligible:
                state = order.get("anchor_repricing_state_json") or {}
                next_reprice_at = StealthOrderManager._parse_runtime_datetime(
                    state.get("next_reprice_at")
                )
                anchor_delay = self._seconds_until(next_reprice_at)
                if anchor_delay is None:
                    anchor_delay = minimum_delay
                try:
                    self.scheduler.schedule_after(
                        stealth_order_id,
                        StealthWakePurpose.ANCHOR_REPRICE,
                        max(anchor_delay, minimum_delay),
                    )
                except SchedulerStoppedError:
                    self._fail_closed_scheduler(
                        "anchor scheduling rejected by stopped scheduler"
                    )
                    return

    def _handle_order_schedule_change(self, stealth_order_id: str) -> None:
        """Nonblocking manager callback: invalidate and rebuild one order."""

        order_id = str(stealth_order_id)
        try:
            self._schedule_order(order_id)
        except SchedulerStoppedError:
            self._fail_closed_scheduler(
                "order scheduling rejected by stopped scheduler"
            )
            return
        except Exception:
            logger.exception(
                "Failed to rebuild stealth schedule for %s",
                order_id,
            )
            self._fail_closed_scheduler(
                f"failed to rebuild schedule for {order_id}"
            )

    def _get_order_action_lock(self, stealth_order_id: str) -> threading.RLock:
        """Serialize reveal/reprice/cancel actions for one logical order."""

        with self._order_action_locks_guard:
            lock = self._order_action_locks.get(stealth_order_id)
            if lock is None:
                lock = threading.RLock()
                self._order_action_locks[stealth_order_id] = lock
            return lock

    def _evaluate_scheduled_order(
        self,
        stealth_order_id: str,
        *,
        market_data: Optional[Dict[str, Any]] = None,
        evaluation_time: Optional[datetime] = None,
        allow_committed_reveal: bool = False,
        defer_overdue_continuous: bool = False,
    ) -> None:
        with self._get_order_action_lock(stealth_order_id):
            self._evaluate_scheduled_order_locked(
                stealth_order_id,
                market_data=market_data,
                evaluation_time=evaluation_time,
                allow_committed_reveal=allow_committed_reveal,
                defer_overdue_continuous=defer_overdue_continuous,
            )

    def _evaluate_scheduled_order_locked(
        self,
        stealth_order_id: str,
        *,
        market_data: Optional[Dict[str, Any]] = None,
        evaluation_time: Optional[datetime] = None,
        allow_committed_reveal: bool = False,
        defer_overdue_continuous: bool = False,
    ) -> None:
        """Run one manager-owned decision and, when admitted, one reveal."""

        order_before = self.stealth_manager.in_memory_orders.get(stealth_order_id)
        if not order_before:
            self._invalidate_order_deadlines(stealth_order_id)
            return
        status_before = order_before.get("status")
        controller = get_runtime_controller()
        reveal_attempted_or_deferred = False

        try:
            should_reveal, reason = self.stealth_manager.should_trigger_reveal(
                stealth_order_id,
                market_data=market_data,
                evaluation_time=evaluation_time,
            )
            order_after = self.stealth_manager.in_memory_orders.get(
                stealth_order_id
            ) or {}
            became_triggered = (
                status_before != StealthOrderStatus.TRIGGERED.value
                and order_after.get("status") == StealthOrderStatus.TRIGGERED.value
            )

            # A ticker burst must not turn one committed condition into many
            # immediate REST attempts.  The first transition may place now;
            # subsequent attempts are owned by ADMISSION_RETRY deadlines.
            if should_reveal and (became_triggered or allow_committed_reveal):
                reveal_attempted_or_deferred = True
                if not controller.is_admitting():
                    logger.debug(
                        "Reveal deferred (engine state %s): %s",
                        controller.state.value,
                        stealth_order_id,
                    )
                    return

                logger.debug(
                    "Stealth order %s ready to reveal: %s",
                    stealth_order_id,
                    reason,
                )
                try:
                    # Admission and in-flight registration must be one
                    # state-lock boundary. The optimistic check above keeps
                    # the common paused path cheap, while this context closes
                    # the race where pause wins immediately afterward.
                    with controller.track_admitted_inflight(
                        INFLIGHT_STEALTH_REVEAL
                    ):
                        client_order_id = (
                            self.stealth_manager.reveal_order_slice(
                                stealth_order_id
                            )
                        )
                        if client_order_id:
                            logger.debug(
                                "Revealed slice: %s", client_order_id
                            )
                            self.record_reveal_event(
                                stealth_order_id,
                                client_order_id,
                                reason or "Reveal condition met",
                            )
                except EngineNotAdmittingError:
                    logger.debug(
                        "Reveal deferred after atomic admission closed "
                        "(engine state %s): %s",
                        controller.state.value,
                        stealth_order_id,
                    )
                    return
        finally:
            order_after_final = self.stealth_manager.in_memory_orders.get(
                stealth_order_id
            )
            terminal_after = (
                order_after_final is None
                or order_after_final.get("status")
                in {
                    StealthOrderStatus.ERROR.value,
                    StealthOrderStatus.EXECUTED.value,
                    StealthOrderStatus.CANCELLED.value,
                }
            )
            status_changed = (
                order_after_final is None
                or order_after_final.get("status") != status_before
            )
            if terminal_after:
                self._invalidate_order_deadlines(stealth_order_id)
            elif reveal_attempted_or_deferred:
                self._schedule_condition_wake(
                    stealth_order_id,
                    order=order_after_final,
                    minimum_delay=self._ADMISSION_RETRY_SECONDS,
                    defer_overdue_continuous=defer_overdue_continuous,
                )
            elif status_changed:
                # The manager callback normally scheduled this transition.
                # Rebuilding just the condition lane also keeps fake/embedded
                # managers safe without perturbing an independent anchor wake.
                self._schedule_condition_wake(
                    stealth_order_id,
                    order=order_after_final,
                    defer_overdue_continuous=defer_overdue_continuous,
                )

    def _handle_market_event(self, event: MarketEvent) -> None:
        if not self._decisions_ready.is_set():
            return

        snapshot = dict(event.payload or {})
        if event.continuity_reset:
            reset_failures = []
            reset_counts = event.continuity_reset_counts or (
                (event.product_id, event.discarded_event_count),
            )
            for reset_product_id, discarded_count in reset_counts:
                if not self._decisions_ready.is_set():
                    return
                for stealth_order_id in (
                    self.stealth_manager.snapshot_active_stealth_orders(
                        reset_product_id
                    )
                ):
                    if not self._decisions_ready.is_set():
                        return
                    with self._get_order_action_lock(stealth_order_id):
                        if not self._decisions_ready.is_set():
                            return
                        order = self.stealth_manager.in_memory_orders.get(
                            stealth_order_id,
                            {},
                        )
                        if order.get("status") not in {
                            StealthOrderStatus.HIDDEN.value,
                            StealthOrderStatus.PENDING.value,
                        }:
                            continue
                        try:
                            self.stealth_manager.reset_continuous_condition(
                                stealth_order_id,
                                reason=(
                                    "Ordered market-event continuity reset "
                                    f"({discarded_count} {reset_product_id} "
                                    "market events unavailable)"
                                ),
                                market_data={
                                    "source": "continuity_reset",
                                    "time": snapshot.get("time"),
                                },
                                evaluation_time=snapshot.get("time"),
                            )
                        except Exception as reset_error:
                            reset_failures.append(
                                (stealth_order_id, reset_error)
                            )
            if reset_failures:
                for failed_order_id, reset_error in reset_failures:
                    logger.error(
                        "Continuous-condition reset failed for %s at an "
                        "ordered market continuity boundary: %s",
                        failed_order_id,
                        reset_error,
                        exc_info=(
                            type(reset_error),
                            reset_error,
                            reset_error.__traceback__,
                        ),
                    )
                first_order_id, first_error = reset_failures[0]
                self._latch_continuity_failure(
                    first_error,
                    context=(
                        "market-event continuity reset for "
                        f"{first_order_id}"
                    ),
                )
                # The retained snapshot must not start/confirm a hold after a
                # continuity boundary failed to persist for any affected SID.
                raise first_error
        if not event.contains_market_snapshot:
            return

        event_time = StealthOrderManager._parse_runtime_datetime(
            snapshot.get("time")
        )
        reset_failure: Optional[Exception] = None
        for stealth_order_id in self.stealth_manager.snapshot_active_stealth_orders(
            event.product_id
        ):
            if not self._decisions_ready.is_set():
                break
            with self._get_order_action_lock(stealth_order_id):
                if not self._decisions_ready.is_set():
                    break
                order = self.stealth_manager.in_memory_orders.get(
                    stealth_order_id
                )
                if not self._condition_uses_market_event(order):
                    continue
                try:
                    self._evaluate_scheduled_order_locked(
                        stealth_order_id,
                        market_data=snapshot,
                        evaluation_time=event_time,
                        allow_committed_reveal=False,
                    )
                except Exception as error:
                    # One malformed order must not suppress the same websocket
                    # event for every other local order on the product. For a
                    # continuous hold, however, the failed evaluation consumed
                    # an ordered observation without proving truth. Restart
                    # that order's hold while the same SID ownership is held.
                    self._handle_scheduler_error(error, event)
                    order_after_error = (
                        self.stealth_manager.in_memory_orders.get(
                            stealth_order_id,
                            {},
                        )
                    )
                    if (
                        order_after_error.get("reveal_condition_type")
                        in self._CONTINUOUS_MARKET_CONDITION_TYPES
                        and order_after_error.get("status")
                        in {
                            StealthOrderStatus.HIDDEN.value,
                            StealthOrderStatus.PENDING.value,
                        }
                    ):
                        try:
                            self.stealth_manager.reset_continuous_condition(
                                stealth_order_id,
                                reason=(
                                    "Continuous condition evaluation failed "
                                    "for ordered market event: "
                                    f"{type(error).__name__}: {error}"
                                ),
                                market_data=snapshot,
                                evaluation_time=event_time,
                            )
                        except Exception as reset_error:
                            # Preserve peer isolation, then latch after every
                            # same-product order consumes this boundary.
                            if reset_failure is None:
                                reset_failure = reset_error

        if reset_failure is not None:
            self._latch_continuity_failure(
                reset_failure,
                context="continuous-condition evaluation recovery",
            )
            raise reset_failure

    def _latch_continuity_failure(
        self,
        error: Exception,
        *,
        context: str,
    ) -> None:
        """Make an unpersisted continuity boundary terminal until restart."""

        self._decisions_ready.clear()
        # stop() is safe on the scheduler worker itself; it marks the scheduler
        # terminal and skips a self-join. Restart/reconciliation must rebuild
        # authoritative state before ordered evidence can be trusted again.
        self.scheduler.stop(join_timeout=0)
        self._fail_closed_scheduler(
            f"{context} failed with {type(error).__name__}: {error}"
        )

    @classmethod
    def _condition_uses_market_event(
        cls,
        order: Optional[Dict[str, Any]],
    ) -> bool:
        """Return whether this condition belongs on the ordered ticker lane.

        Price/spread continuity must consume every ordered ticker.  A fixed
        (non-jittered) time delay may also use a ticker to observe that its
        stable deadline has passed.  Mutable volume/ratio/composite evaluators
        and jittered time conditions stay exclusively on the retained
        compatibility cadence; calling them from both lanes would change their
        pre-existing stateful semantics.
        """

        if not order or order.get("status") not in {
            StealthOrderStatus.HIDDEN.value,
            StealthOrderStatus.PENDING.value,
        }:
            return False
        if float(order.get("remaining_size", 0) or 0) <= 0:
            return False

        condition_type = str(
            order.get("reveal_condition_type")
            or RevealConditionType.TIME_DELAY.value
        ).lower()
        if condition_type in cls._CONTINUOUS_MARKET_CONDITION_TYPES:
            return True
        if condition_type != RevealConditionType.TIME_DELAY.value:
            return False

        deadline = get_evaluator(condition_type).resolve_stable_deadline(
            order.get("reveal_condition_json") or {},
            order,
        )
        return deadline.supported

    def _handle_deadline_wake(self, wake: DeadlineWake) -> None:
        if not self._decisions_ready.is_set():
            return

        # ``take_due`` captures both lanes before dispatching them.  A market
        # event from that same batch can invalidate/rebuild this logical wake,
        # so generation ownership must be checked again at callback time.
        if wake.purpose == StealthWakePurpose.ANCHOR_REPRICE:
            # The ticker path can claim the same due wake directly while this
            # callback is waiting to run.  Hold the handoff lock across the
            # scheduler CAS and marker publication so there is no observable
            # gap between owning the wake and making it available to a ticker.
            with self._anchor_due_lock:
                claimed_generation = self.scheduler.claim_deadline_wake(wake)
                if claimed_generation is None:
                    return
                self._anchor_due_generations[
                    wake.stealth_order_id
                ] = (claimed_generation, wake.deadline_monotonic)
            return

        with self._get_order_action_lock(wake.stealth_order_id):
            if not self._decisions_ready.is_set():
                return
            if self.scheduler.current_generation(
                wake.stealth_order_id,
                wake.purpose,
            ) != wake.generation:
                return

            if wake.purpose == StealthWakePurpose.CONDITION_HOLD:
                # A timer proves only that elapsed time passed; it cannot prove
                # the price/spread stayed true. Leave the order PENDING and let
                # the next ordered websocket snapshot confirm or reset it.
                return

            try:
                self._evaluate_scheduled_order_locked(
                    wake.stealth_order_id,
                    allow_committed_reveal=(
                        wake.purpose == StealthWakePurpose.ADMISSION_RETRY
                    ),
                )
            finally:
                # The consumed wake and its replacement are one per-SID
                # ownership transaction. A concurrent persisted update cannot
                # publish a newer schedule and then be overwritten here.
                if self._decisions_ready.is_set():
                    self._schedule_condition_wake(
                        wake.stealth_order_id,
                        minimum_delay=self._OVERDUE_DEADLINE_RETRY_SECONDS,
                    )

    def _handle_scheduler_error(
        self,
        error: Exception,
        item: SchedulerItem,
    ) -> None:
        logger.error(
            "Stealth scheduler item failed (%s): %s",
            type(item).__name__,
            error,
            exc_info=(type(error), error, error.__traceback__),
        )

    def _handle_scheduler_fatal(self, error: Exception) -> None:
        """Autonomously pause if the sole decision worker exits."""

        self._decisions_ready.clear()
        self._fail_closed_scheduler(
            f"decision worker exited with {type(error).__name__}: {error}"
        )

    def _fail_closed_scheduler(self, reason: str) -> None:
        """Keep a terminal decision-worker failure fail-closed.

        The first report owns the diagnostic log. Later rejected publications
        remain supervisory evidence: if an operator resumed the runtime while
        the terminal scheduler is still dead, pause it again without flooding
        the same failure log.
        """

        if not self.running or self._shutdown_event.is_set():
            return
        self._decisions_ready.clear()
        # A failed authoritative schedule cannot coexist safely with continued
        # condition/admission callbacks. Terminally stop the sole worker; a
        # restart plus hydration/reconciliation is the recovery boundary.
        self.scheduler.stop(join_timeout=0)
        with self._scheduler_failure_lock:
            first_report = not self._scheduler_failure_reported
            if first_report:
                self._scheduler_failure_reported = True

        if first_report:
            worker_error = self.scheduler.worker_error
            logger.error(
                "Stealth decision scheduler failed; pausing originating work: "
                "%s (worker_error=%r)",
                reason,
                worker_error,
            )

        controller = get_runtime_controller()
        if first_report or controller.is_admitting():
            controller.request_pause()
    
    def reconcile_stealth_orders_periodically(self, interval_seconds: int = 30) -> None:
        """Periodically load stealth orders from database and sync with memory.
        
        Runs in daemon thread, loops forever. Ensures that orders created
        externally (via other clients or processes) are loaded and tracked.
        
        Args:
            interval_seconds: Sleep duration between syncs (default 30).
            
        Returns:
            None (infinite loop)
        """
        while self.running:
            try:
                self._reconcile_stealth_orders(force_log=False)
            except Exception as e:
                logger.error(f"Stealth order reconciliation error: {e}")

            # Interruptible sleep: stop() wakes us immediately rather
            # than waiting out the full reconciliation interval.
            if self._shutdown_event.wait(timeout=interval_seconds):
                break
    
    def _reconcile_stealth_orders(self, force_log: bool = False) -> bool:
        """Load active stealth orders from database and merge with in-memory state.
        
        Args:
            force_log: Whether to log reconciliation events
            
        Returns:
            True if state changed, False if already in sync
        """
        if force_log:
            logger.info("Stealth order reconciliation started")
        
        try:
            # Load all active orders from database
            loaded_count = 0
            changed = False
            
            # Get current in-memory order IDs
            with self.stealth_manager._get_orders_cache_lock():
                current_ids = set(
                    self.stealth_manager.in_memory_orders.keys()
                )
            
            # Query database for active orders
            if self.stealth_manager.db_client:
                try:
                    db_results = self.stealth_manager.db_client.execute_query(
                        """SELECT stealth_order_id FROM stealth_orders 
                           WHERE status IN ('HIDDEN', 'PENDING', 'TRIGGERED', 'REVEALED')"""
                    )
                    
                    db_ids = set(str(row['stealth_order_id']) for row in db_results)
                    
                    # Find new orders in database that aren't in memory
                    new_ids = db_ids - current_ids
                    
                    if new_ids:
                        logger.info(f"Found {len(new_ids)} new stealth orders in database")
                        
                        # Load each new order from database
                        for order_id in new_ids:
                            try:
                                # Use the manager's canonical lazy-load path;
                                # it inserts under the creation lock and emits
                                # the one order-schedule invalidation callback.
                                order_data = self.stealth_manager._get_stealth_order(order_id)
                                if order_data:
                                    loaded_count += 1
                                    changed = True
                            except Exception as e:
                                logger.error(f"Failed to load order {order_id}: {e}")
                    
                    if force_log or changed:
                        logger.info(
                            f"Stealth order reconciliation complete - "
                            f"database: {len(db_ids)}, memory: {len(self.stealth_manager.in_memory_orders)}, "
                            f"loaded: {loaded_count}"
                        )
                    
                    return changed
                    
                except Exception as e:
                    logger.error(f"Database query failed during reconciliation: {e}")
                    return False
            
            return False
            
        except Exception as e:
            logger.error(f"Reconciliation error: {e}")
            return False
    
    @staticmethod
    def _build_ticker_market_snapshot(
        trading_product_id: str,
        ticker_data: Dict[str, Any],
        *,
        event_time: Optional[Any] = None,
    ) -> MarketData:
        """Normalize one Coinbase ticker without mutating shared state."""

        normalized_event_time = StealthOrderManager._parse_runtime_datetime(
            event_time
        ) or StealthOrderManager._parse_runtime_datetime(
            ticker_data.get("time")
        ) or datetime.utcnow()
        return {
            "product_id": trading_product_id,
            "price": safe_float(ticker_data.get("price"), 0),
            "bid": safe_float(ticker_data.get("best_bid"), 0),
            "ask": safe_float(ticker_data.get("best_ask"), 0),
            "volume_1m": (
                safe_float(ticker_data.get("volume_24_h"), 0) / 1440
            ),
            "time": normalized_event_time,
            "source": "ticker",
        }

    def reprice_stealth_order_now(self, stealth_order_id: str) -> int:
        """Run one operator-requested anchor reprice and rebuild its deadline."""

        if not self._decisions_ready.is_set():
            raise RuntimeError(
                "Stealth decisions are not active; startup reconciliation "
                "must complete before manual repricing"
            )

        with self._get_order_action_lock(stealth_order_id):
            order = self.stealth_manager.in_memory_orders.get(stealth_order_id)
            if not order:
                raise KeyError(f"Stealth order not found: {stealth_order_id}")

            policy = RepricingPolicy.from_dict(
                order.get("anchor_repricing_policy_json")
            )
            if not policy.enabled:
                raise ValueError("Anchor repricing is not enabled for this order")

            active_statuses = {
                StealthOrderStatus.HIDDEN.value,
                StealthOrderStatus.PENDING.value,
                StealthOrderStatus.TRIGGERED.value,
                StealthOrderStatus.REVEALED.value,
            }
            if order.get("status") not in active_statuses:
                raise ValueError(
                    f"Order status {order.get('status')} is not repriceable"
                )

            state = self.stealth_manager._normalize_anchor_repricing_state(
                order.get("anchor_repricing_state_json")
            )
            state.pop("next_reprice_at", None)
            order["anchor_repricing_state_json"] = state

            try:
                return int(
                    self.stealth_manager.process_anchor_repricing_for_product(
                        order.get("product_id", ""),
                        stealth_order_ids=(stealth_order_id,),
                    )
                    or 0
                )
            finally:
                self._schedule_anchor_wake(
                    stealth_order_id,
                    minimum_delay=self._OVERDUE_DEADLINE_RETRY_SECONDS,
                )

    def update_price_condition(
        self,
        stealth_order_id: str,
        *,
        price_threshold: float,
        hold_duration_seconds: Optional[int] = None,
    ) -> bool:
        """Serialize persistence, hold reset, and schedule publication."""

        with self._get_order_action_lock(stealth_order_id):
            updated = self.stealth_manager.update_price_condition(
                stealth_order_id,
                price_threshold=price_threshold,
                hold_duration_seconds=hold_duration_seconds,
            )
            if not updated:
                raise ValueError(
                    "Price condition was not found or is not editable: "
                    f"{stealth_order_id}"
                )
            return True

    def publish_ticker_update(
        self,
        product_id: str,
        ticker_data: Dict[str, Any],
        *,
        event_time: Optional[Any] = None,
    ) -> str:
        """
        Publish one ordered websocket snapshot to the decision scheduler.
        
        Cache replacement happens before queue publication, so deadline wakes
        always see at least this snapshot.  The FIFO retains the event itself
        for continuous-hold semantics; repeated product ticks are not silently
        coalesced.
        
        Args:
            product_id: Product that was updated (may be ticker product like BTC-USD)
            ticker_data: Latest ticker data from Coinbase
        """
        from configuration import get_trading_product_id
        
        # Convert ticker product to trading product if necessary
        trading_product_id = get_trading_product_id(product_id)
        
        market_data = self._build_ticker_market_snapshot(
            trading_product_id,
            ticker_data,
            event_time=event_time,
        )

        event_time_utc = market_data["time"]
        with self._market_event_time_lock:
            previous_event_time = self._last_market_event_time.get(
                trading_product_id
            )
            stale_event = (
                previous_event_time is not None
                and event_time_utc < previous_event_time
            )
            if not stale_event:
                self._last_market_event_time[trading_product_id] = (
                    event_time_utc
                )

            if stale_event:
                # The timestamp decision, cache replacement, and FIFO append
                # are one publication transaction.  Otherwise two direct
                # producers can both pass the timestamp check and then append
                # in the opposite order.
                self.publish_market_continuity_reset(
                    trading_product_id,
                    discarded_event_count=1,
                    event_time=event_time_utc,
                )
                logger.warning(
                    "Discarded out-of-order ticker for %s: event_time=%s, "
                    "last_event_time=%s",
                    trading_product_id,
                    event_time_utc.isoformat(),
                    previous_event_time.isoformat(),
                )
                return trading_product_id

            self._update_market_cache(trading_product_id, market_data)
            try:
                self.scheduler.publish_market_event(
                    trading_product_id,
                    dict(market_data),
                )
            except MarketEventQueueFullError as error:
                # Explicit recovery favors the newest snapshot.  Clearing the
                # queued backlog is observable (count logged), and the replacement
                # event resets continuous holds in FIFO order on the decision
                # thread before it is evaluated as a fresh starting point.
                recovery_snapshot = dict(market_data)
                discarded = (
                    self.scheduler.replace_pending_market_events_for_recovery(
                        trading_product_id,
                        recovery_snapshot,
                    )
                )
                logger.error(
                    "Stealth market-event FIFO overflow for %s; discarded %d "
                    "queued events and enqueued a continuity reset: %s",
                    trading_product_id,
                    len(discarded),
                    error,
                )
            except SchedulerStoppedError:
                if self.running:
                    self._fail_closed_scheduler(
                        "ticker publication rejected for "
                        f"{trading_product_id}"
                    )
        return trading_product_id

    def publish_market_continuity_reset(
        self,
        product_id: str,
        *,
        discarded_event_count: int,
        event_time: Optional[Any] = None,
    ) -> str:
        """Publish a fail-closed marker for ticker loss upstream of this bridge."""

        from configuration import get_trading_product_id

        trading_product_id = get_trading_product_id(product_id)
        marker = {
            "product_id": trading_product_id,
            "price": 0.0,
            "bid": 0.0,
            "ask": 0.0,
            "volume_1m": 0.0,
            "time": (
                StealthOrderManager._parse_runtime_datetime(event_time)
                or datetime.utcnow()
            ),
            "source": "continuity_reset",
        }
        try:
            self.scheduler.publish_market_continuity_reset(
                trading_product_id,
                marker,
                discarded_event_count=discarded_event_count,
            )
        except MarketEventQueueFullError as error:
            discarded = self.scheduler.replace_pending_market_events_for_recovery(
                trading_product_id,
                marker,
                additional_discarded_event_count=discarded_event_count,
                contains_market_snapshot=False,
            )
            logger.error(
                "Stealth market-event FIFO overflow while publishing an "
                "upstream continuity reset for %s; discarded %d queued "
                "events: %s",
                trading_product_id,
                len(discarded),
                error,
            )
        except SchedulerStoppedError:
            if self.running:
                self._fail_closed_scheduler(
                    "continuity-reset publication rejected for "
                    f"{trading_product_id}"
                )
        return trading_product_id

    def process_due_anchor_repricing(
        self,
        product_id: str,
        ticker_data: Dict[str, Any],
        *,
        event_time: Optional[Any] = None,
        received_monotonic: Optional[float] = None,
    ) -> int:
        """Process anchor deadlines only in response to a live ticker.

        The scheduler worker marks logical orders due without performing REST
        or database work.  This method is called later in the existing ticker
        path, scopes each manager invocation to one ``stealth_order_id``, and
        always rebuilds that order's disposable anchor deadline afterward.
        """

        from configuration import get_trading_product_id

        # The startup barrier is authoritative inside the bridge, not merely
        # an assumption about main.py ordering. Pre-activation heap entries
        # must remain untouched until reconciliation and strict scheduling
        # validation have completed.
        if not self._decisions_ready.is_set():
            return 0

        receipt_monotonic = (
            time.monotonic()
            if received_monotonic is None
            else float(received_monotonic)
        )
        if not math.isfinite(receipt_monotonic):
            raise ValueError("received_monotonic must be a finite number")

        # A due anchor is originating cancel-and-replace work.  Keep its handoff
        # marker intact while paused/draining so the first live ticker after
        # resume can process it; do not cancel a resting order while placement
        # admission is closed.
        controller = get_runtime_controller()
        if not controller.is_admitting():
            return 0

        trading_product_id = get_trading_product_id(product_id)
        market_data = self._build_ticker_market_snapshot(
            trading_product_id,
            ticker_data,
            event_time=event_time,
        )

        with self._market_event_time_lock:
            latest_event_time = self._last_market_event_time.get(
                trading_product_id
            )
        if (
            latest_event_time is not None
            and market_data["time"] < latest_event_time
        ):
            return 0

        # A live ticker is itself allowed to claim a due anchor deadline from
        # the central heap.  This covers the exact interval after the scheduler
        # worker captured a wake but before its callback published the handoff
        # marker; it does not create a second timer or evaluate wall-clock work
        # independently of the scheduler.
        active_product_order_ids = tuple(
            self.stealth_manager.snapshot_active_stealth_orders(
                trading_product_id
            )
        )

        with self._anchor_due_lock:
            for stealth_order_id in active_product_order_ids:
                if not controller.is_admitting():
                    break
                if stealth_order_id in self._anchor_due_generations:
                    continue
                try:
                    claimed_generation = self.scheduler.claim_due_deadline(
                        stealth_order_id,
                        StealthWakePurpose.ANCHOR_REPRICE,
                        now=receipt_monotonic,
                    )
                except SchedulerStoppedError:
                    return 0
                if claimed_generation is not None:
                    self._anchor_due_generations[
                        stealth_order_id
                    ] = (claimed_generation, receipt_monotonic)

            due_order_ids = sorted(
                stealth_order_id
                for stealth_order_id, (
                    _generation,
                    deadline_monotonic,
                ) in (
                    self._anchor_due_generations.items()
                )
                if (
                    self.stealth_manager.in_memory_orders.get(
                        stealth_order_id,
                        {},
                    ).get("product_id")
                    == trading_product_id
                    and receipt_monotonic >= deadline_monotonic
                )
            )

        processed = 0
        for stealth_order_id in due_order_ids:
            if (
                not self._decisions_ready.is_set()
                or not controller.is_admitting()
            ):
                break

            # Consume only this SID's marker. Every later SID remains in the
            # handoff map if admission closes during this action.
            with self._anchor_due_lock:
                handoff = self._anchor_due_generations.get(stealth_order_id)
                if handoff is None:
                    continue
                generation, deadline_monotonic = handoff
                order = self.stealth_manager.in_memory_orders.get(
                    stealth_order_id,
                    {},
                )
                if (
                    order.get("product_id") != trading_product_id
                    or receipt_monotonic < deadline_monotonic
                ):
                    continue
                if (
                    not self._decisions_ready.is_set()
                    or not controller.is_admitting()
                ):
                    break
                self._anchor_due_generations.pop(stealth_order_id, None)

            # Readiness/admission can change immediately after the marker is
            # removed. Before the generation CAS, restoring the exact marker
            # is safe if no newer authoritative schedule superseded it.
            if (
                not self._decisions_ready.is_set()
                or not controller.is_admitting()
            ):
                with self._anchor_due_lock:
                    if (
                        stealth_order_id not in self._anchor_due_generations
                        and self.scheduler.current_generation(
                            stealth_order_id,
                            StealthWakePurpose.ANCHOR_REPRICE,
                        )
                        == generation
                    ):
                        self._anchor_due_generations[
                            stealth_order_id
                        ] = handoff
                break

            try:
                claimed_generation = self.scheduler.invalidate_deadline(
                    stealth_order_id,
                    StealthWakePurpose.ANCHOR_REPRICE,
                    expected_generation=generation,
                )
            except SchedulerStoppedError:
                with self._anchor_due_lock:
                    if (
                        stealth_order_id not in self._anchor_due_generations
                        and self.scheduler.current_generation(
                            stealth_order_id,
                            StealthWakePurpose.ANCHOR_REPRICE,
                        )
                        == generation
                    ):
                        self._anchor_due_generations[
                            stealth_order_id
                        ] = handoff
                return processed
            if claimed_generation is None:
                # A newer authoritative schedule revoked this due marker
                # after it was copied from the handoff map.
                continue

            # The CAS consumed the handoff generation. If admission closes at
            # this boundary, restore an overdue heap wake rather than losing
            # the logical action.
            if (
                not self._decisions_ready.is_set()
                or not controller.is_admitting()
            ):
                if not self._decisions_ready.is_set():
                    with self._anchor_due_lock:
                        if (
                            stealth_order_id
                            not in self._anchor_due_generations
                            and self.scheduler.current_generation(
                                stealth_order_id,
                                StealthWakePurpose.ANCHOR_REPRICE,
                            )
                            == claimed_generation
                        ):
                            self._anchor_due_generations[
                                stealth_order_id
                            ] = (
                                claimed_generation,
                                deadline_monotonic,
                            )
                else:
                    self._schedule_anchor_wake(
                        stealth_order_id,
                        minimum_delay=0.0,
                    )
                break

            action_started = False
            admission_deferred = False
            readiness_deferred = False
            try:
                with self._get_order_action_lock(stealth_order_id):
                    if not self._decisions_ready.is_set():
                        readiness_deferred = True
                    elif not controller.is_admitting():
                        admission_deferred = True
                    else:
                        try:
                            # Admission and in-flight registration are one
                            # state-lock boundary. Pause either wins first, or
                            # this action is already tracked before pause.
                            with controller.track_admitted_inflight(
                                INFLIGHT_REST_PLACE
                            ):
                                if not self._decisions_ready.is_set():
                                    readiness_deferred = True
                                else:
                                    action_started = True
                                    processed += int(
                                        self.stealth_manager.process_anchor_repricing_for_product(
                                            trading_product_id,
                                            stealth_order_ids=(stealth_order_id,),
                                            market_data=market_data,
                                        )
                                        or 0
                                    )
                        except EngineNotAdmittingError:
                            admission_deferred = True
            except Exception:
                logger.exception(
                    "Anchor repricing failed for %s on live ticker %s",
                    stealth_order_id,
                    trading_product_id,
                )
            finally:
                if action_started:
                    self._schedule_anchor_wake(
                        stealth_order_id,
                        minimum_delay=self._OVERDUE_DEADLINE_RETRY_SECONDS,
                    )
                elif readiness_deferred:
                    with self._anchor_due_lock:
                        if (
                            stealth_order_id
                            not in self._anchor_due_generations
                            and self.scheduler.current_generation(
                                stealth_order_id,
                                StealthWakePurpose.ANCHOR_REPRICE,
                            )
                            == claimed_generation
                        ):
                            self._anchor_due_generations[
                                stealth_order_id
                            ] = (
                                claimed_generation,
                                deadline_monotonic,
                            )
                elif admission_deferred:
                    self._schedule_anchor_wake(
                        stealth_order_id,
                        minimum_delay=0.0,
                    )
            if readiness_deferred or admission_deferred:
                break
        return processed

    def process_ticker_update(
        self,
        product_id: str,
        ticker_data: Dict[str, Any],
    ) -> str:
        """Compatibility wrapper for callers using the historical method."""

        received_monotonic = time.monotonic()
        trading_product_id = self.publish_ticker_update(product_id, ticker_data)
        self.process_due_anchor_repricing(
            product_id,
            ticker_data,
            received_monotonic=received_monotonic,
        )
        return trading_product_id
    
    def record_reveal_event(self, stealth_order_id: str, client_order_id: str, reason: str):
        """Record a reveal event to the database."""
        order = self.stealth_manager._get_stealth_order(stealth_order_id)
        
        if not order:
            return
        
        reveal_data = {
            "stealth_order_id": stealth_order_id,
            "reveal_number": len(order["revealed_orders"]),
            "placed_order_id": client_order_id,
            "reveal_trigger_reason": reason,
            "timestamp": datetime.utcnow(),
        }
        
        # Persist to database
        self._save_reveal_event_to_db(reveal_data)
    
    def get_stealth_orders(self, status: str = None) -> Dict[str, Dict[str, Any]]:
        """
        Get all stealth orders, optionally filtered by status.
        
        Args:
            status: Optional status filter (HIDDEN, PENDING, TRIGGERED, REVEALED, EXECUTED, CANCELLED)
            
        Returns:
            Dict mapping stealth_order_id to order data
        """
        with self.stealth_manager._get_orders_cache_lock():
            all_orders = dict(self.stealth_manager.in_memory_orders)
        
        if status:
            return {
                sid: order for sid, order in all_orders.items()
                if order.get("status") == status
            }
        
        return all_orders
    
    def create_stealth_order(
        self,
        stealth_order_id: Optional[str] = None,
        **kwargs,
    ) -> str:
        """Convenience method to create stealth order.
        
        Args:
            stealth_order_id: Optional UUID for the stealth order. If not provided, one will be generated.
            **kwargs: Additional arguments passed to stealth_manager.create_stealth_order()
            
        Returns:
            The stealth_order_id (either provided or newly generated)
        """
        order_id = (
            str(stealth_order_id)
            if stealth_order_id
            else str(uuid.uuid4())
        )
        with self._get_order_action_lock(order_id):
            return self.stealth_manager.create_stealth_order(
                stealth_order_id=order_id,
                **kwargs,
            )

    def create_follow_up_stealth_order(
        self,
        follow_up_stealth_order_id: Optional[str] = None,
        **kwargs,
    ) -> Optional[str]:
        """Serialize a complete follow-up factory transaction by its new SID."""

        order_id = (
            str(follow_up_stealth_order_id)
            if follow_up_stealth_order_id
            else str(uuid.uuid4())
        )
        with self._get_order_action_lock(order_id):
            return self.stealth_manager.create_follow_up_stealth_order(
                follow_up_stealth_order_id=order_id,
                **kwargs,
            )

    def sync_exchange_order_id_for_placed_order(
        self,
        placed_order_id: str,
        exchange_order_id: str,
    ) -> bool:
        """Serialize websocket exchange-ID enrichment with SID decisions."""

        order = self.stealth_manager.find_stealth_order_by_placed_order_id(
            placed_order_id
        )
        if not order:
            return False
        stealth_order_id = order.get("stealth_order_id")
        if not stealth_order_id:
            return False

        with self._get_order_action_lock(str(stealth_order_id)):
            current_order = (
                self.stealth_manager.find_stealth_order_by_placed_order_id(
                    placed_order_id
                )
            )
            if (
                not current_order
                or current_order.get("stealth_order_id") != stealth_order_id
            ):
                return False
            return self.stealth_manager.sync_exchange_order_id_for_placed_order(
                placed_order_id,
                exchange_order_id,
            )

    def update_execution(
        self,
        stealth_order_id: str,
        executed_size: float,
        order_status: str = StealthOrderStatus.EXECUTED.value,
    ) -> None:
        """Serialize websocket terminal execution state with SID decisions."""

        with self._get_order_action_lock(stealth_order_id):
            self.stealth_manager.update_execution(
                stealth_order_id=stealth_order_id,
                executed_size=executed_size,
                order_status=order_status,
            )
    
    def cancel_stealth_order(
        self,
        stealth_order_id: str,
        reason: str = "User cancelled",
        cancel_exchange: bool = True,
    ) -> bool:
        """Cancel a stealth order (and, by default, its live exchange order)."""
        with self._get_order_action_lock(stealth_order_id):
            return self.stealth_manager.cancel_stealth_order(
                stealth_order_id, reason, cancel_exchange=cancel_exchange
            )
    
    # ===================== PRIVATE METHODS =====================
    
    def _update_market_cache(self, product_id: str, market_data: MarketData):
        """Update market data cache for evaluators."""
        self.stealth_manager.publish_market_data(product_id, market_data)
    
    def _save_reveal_event_to_db(self, reveal_data: Dict[str, Any]):
        """Save reveal event to stealth_order_reveal_history table."""
        # SQL INSERT implementation would go here
        pass
