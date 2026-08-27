"""Thread-safe event and deadline scheduling for stealth-order orchestration.

This module deliberately contains no database, REST-client, or order-manager
dependencies.  It coordinates *when* an owning bridge thread should inspect
work; it does not decide what the work means and never executes an order.

The scheduler has two input lanes:

* market events are retained in publication order in a FIFO; repeated events
  for the same product are not silently coalesced;
* deadlines live in one monotonic min-heap.  A deadline is identified by
  ``(stealth_order_id, wake_purpose, generation)``.  Rescheduling or
  invalidating a logical key advances its generation, making older heap
  entries harmless stale records.

One :class:`threading.Condition` protects all mutable state and wakes a
consumer for a new market event, an earlier deadline, invalidation, or stop.
There is never a ``threading.Timer`` per order.  A caller may either use the
synchronous :meth:`take_due` / :meth:`run_due` seams (including with a fake
monotonic clock) or start one optional worker thread with :meth:`start`.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import heapq
import math
import threading
import time
from typing import Any, Callable, Deque, Dict, Optional, Tuple, Union

from core.enums import StealthWakePurpose


class SchedulerStoppedError(RuntimeError):
    """Raised when new work is submitted after terminal scheduler stop."""


class MarketEventQueueFullError(RuntimeError):
    """Raised rather than silently dropping an ordered market event."""


@dataclass(frozen=True, slots=True)
class MarketEvent:
    """One immutable scheduler envelope around an opaque market payload.

    The payload itself is intentionally opaque.  Callers that require snapshot
    immutability should publish an immutable value or their own defensive copy.
    """

    sequence: int
    product_id: str
    payload: Any
    published_monotonic: float
    contains_market_snapshot: bool = True
    continuity_reset: bool = False
    discarded_event_count: int = 0
    continuity_reset_counts: Tuple[Tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class DeadlineWake:
    """A valid, due generation removed from the monotonic deadline heap."""

    stealth_order_id: str
    purpose: StealthWakePurpose
    generation: int
    deadline_monotonic: float


@dataclass(frozen=True, slots=True)
class SchedulerBatch:
    """Ready work captured atomically from both scheduler lanes."""

    market_events: Tuple[MarketEvent, ...] = ()
    deadline_wakes: Tuple[DeadlineWake, ...] = ()

    @property
    def empty(self) -> bool:
        return not self.market_events and not self.deadline_wakes


SchedulerItem = Union[MarketEvent, DeadlineWake]
MarketEventHandler = Callable[[MarketEvent], None]
DeadlineWakeHandler = Callable[[DeadlineWake], None]
SchedulerErrorHandler = Callable[[Exception, SchedulerItem], None]
SchedulerFatalHandler = Callable[[Exception], None]


# Heap tuple fields: deadline, insertion sequence (stable tie-breaker), logical
# order id, enum purpose, and generation.
_HeapEntry = Tuple[float, int, str, StealthWakePurpose, int]
# Active tuple fields: deadline, insertion sequence, generation.
_ActiveDeadline = Tuple[float, int, int]
_DeadlineKey = Tuple[str, StealthWakePurpose]


class StealthEventDeadlineScheduler:
    """Coordinate ordered market events and generational monotonic deadlines.

    ``stop()`` is terminal.  This is intentional: restarting a scheduler while
    old producer references still exist makes generation ownership ambiguous.

    Args:
        clock: Monotonic seconds provider.  Inject a mutable fake clock for
            deterministic calls to :meth:`take_due` or :meth:`run_due`.
        market_queue_limit: Optional positive bound.  A full FIFO raises
            :class:`MarketEventQueueFullError`; events are never silently
            overwritten or coalesced.
        thread_name: Name used by the optional single worker thread.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        market_queue_limit: Optional[int] = None,
        thread_name: str = "StealthEventDeadlineScheduler",
    ) -> None:
        if not callable(clock):
            raise TypeError("clock must be callable")
        if market_queue_limit is not None:
            if isinstance(market_queue_limit, bool) or market_queue_limit <= 0:
                raise ValueError("market_queue_limit must be a positive integer")
            market_queue_limit = int(market_queue_limit)

        self._clock = clock
        self._market_queue_limit = market_queue_limit
        self._thread_name = str(thread_name)

        # One condition is the sole state lock and wake-up primitive.
        self._condition = threading.Condition(threading.RLock())
        self._market_events: Deque[MarketEvent] = deque()
        self._deadline_heap: list[_HeapEntry] = []
        self._deadline_generations: Dict[_DeadlineKey, int] = {}
        self._active_deadlines: Dict[_DeadlineKey, _ActiveDeadline] = {}
        # Wakes removed by the autonomous worker remain claimable until their
        # callback completes.  This closes the narrow handoff window where a
        # live ticker can arrive after an anchor deadline was removed from the
        # heap but before the bridge callback has published its due marker.
        self._worker_captured_deadlines: Dict[_DeadlineKey, DeadlineWake] = {}

        self._next_sequence = 0
        self._stopped = False
        self._worker: Optional[threading.Thread] = None
        self._worker_error: Optional[Exception] = None

    # ------------------------------------------------------------------
    # Validation and sequence helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_stealth_order_id(stealth_order_id: str) -> str:
        if not isinstance(stealth_order_id, str) or not stealth_order_id.strip():
            raise ValueError("stealth_order_id must be a non-empty string")
        return stealth_order_id

    @staticmethod
    def _validate_purpose(purpose: StealthWakePurpose) -> StealthWakePurpose:
        if not isinstance(purpose, StealthWakePurpose):
            raise TypeError("purpose must be a StealthWakePurpose enum value")
        return purpose

    @staticmethod
    def _validate_deadline(deadline_monotonic: float) -> float:
        try:
            deadline = float(deadline_monotonic)
        except (TypeError, ValueError) as exc:
            raise ValueError("deadline_monotonic must be a finite number") from exc
        if not math.isfinite(deadline):
            raise ValueError("deadline_monotonic must be a finite number")
        return deadline

    def _new_sequence_locked(self) -> int:
        self._next_sequence += 1
        return self._next_sequence

    def _require_running_locked(self) -> None:
        if self._stopped:
            raise SchedulerStoppedError("scheduler has been stopped")

    # ------------------------------------------------------------------
    # Producer API
    # ------------------------------------------------------------------

    def publish_market_event(
        self,
        product_id: str,
        payload: Any = None,
    ) -> int:
        """Append one market event and return its global insertion sequence.

        Events for the same product remain distinct and ordered.  The method is
        non-blocking; a configured full queue raises instead of dropping data.
        """

        if not isinstance(product_id, str) or not product_id.strip():
            raise ValueError("product_id must be a non-empty string")

        with self._condition:
            self._require_running_locked()
            if (
                self._market_queue_limit is not None
                and len(self._market_events) >= self._market_queue_limit
            ):
                raise MarketEventQueueFullError(
                    f"market event FIFO is full ({self._market_queue_limit})"
                )

            sequence = self._new_sequence_locked()
            self._market_events.append(
                MarketEvent(
                    sequence=sequence,
                    product_id=product_id,
                    payload=payload,
                    published_monotonic=float(self._clock()),
                    contains_market_snapshot=True,
                    continuity_reset=False,
                    discarded_event_count=0,
                    continuity_reset_counts=(),
                )
            )
            self._condition.notify_all()
            return sequence

    def publish_market_continuity_reset(
        self,
        product_id: str,
        payload: Any = None,
        *,
        discarded_event_count: int = 1,
    ) -> int:
        """Append an explicit upstream-loss marker to the market FIFO.

        This is distinct from ordinary publication: the owner has proof that
        one or more earlier events for ``product_id`` were lost before reaching
        this scheduler.  Queue bounds still apply, allowing the bridge to use
        the same loud whole-backlog recovery as ordinary overflow.
        """

        if not isinstance(product_id, str) or not product_id.strip():
            raise ValueError("product_id must be a non-empty string")
        if (
            isinstance(discarded_event_count, bool)
            or not isinstance(discarded_event_count, int)
            or discarded_event_count <= 0
        ):
            raise ValueError("discarded_event_count must be a positive integer")

        with self._condition:
            self._require_running_locked()
            if (
                self._market_queue_limit is not None
                and len(self._market_events) >= self._market_queue_limit
            ):
                raise MarketEventQueueFullError(
                    f"market event FIFO is full ({self._market_queue_limit})"
                )

            sequence = self._new_sequence_locked()
            self._market_events.append(
                MarketEvent(
                    sequence=sequence,
                    product_id=product_id,
                    payload=payload,
                    published_monotonic=float(self._clock()),
                    contains_market_snapshot=False,
                    continuity_reset=True,
                    discarded_event_count=int(discarded_event_count),
                    continuity_reset_counts=(
                        (product_id, int(discarded_event_count)),
                    ),
                )
            )
            self._condition.notify_all()
            return sequence

    def replace_pending_market_events_for_recovery(
        self,
        product_id: str,
        payload: Any = None,
        *,
        additional_discarded_event_count: int = 0,
        contains_market_snapshot: bool = True,
    ) -> Tuple[MarketEvent, ...]:
        """Atomically replace the queued backlog with one recovery event.

        Normal publication never drops or coalesces events.  This method is a
        deliberately loud recovery seam for the owner after
        :class:`MarketEventQueueFullError`: the bridge can record the exact
        loss while publishing one aggregate continuity boundary in the same
        critical section.  ``contains_market_snapshot`` distinguishes a
        retained ticker from a control-only reset without inspecting the
        opaque payload.  Events already captured by the consumer are not in
        this queue and are allowed to finish before that boundary.
        """

        if not isinstance(product_id, str) or not product_id.strip():
            raise ValueError("product_id must be a non-empty string")
        if (
            isinstance(additional_discarded_event_count, bool)
            or not isinstance(additional_discarded_event_count, int)
            or additional_discarded_event_count < 0
        ):
            raise ValueError(
                "additional_discarded_event_count must be a non-negative integer"
            )
        if not isinstance(contains_market_snapshot, bool):
            raise TypeError("contains_market_snapshot must be a bool")

        with self._condition:
            self._require_running_locked()
            discarded = tuple(self._market_events)
            self._market_events.clear()

            discarded_counts: Dict[str, int] = {}

            def add_discarded_count(
                discarded_product_id: str,
                discarded_count: int,
            ) -> None:
                if discarded_count <= 0:
                    return
                discarded_counts[discarded_product_id] = (
                    discarded_counts.get(discarded_product_id, 0)
                    + discarded_count
                )

            for event in discarded:
                inherited_counts = event.continuity_reset_counts
                if inherited_counts:
                    for inherited_product_id, inherited_count in inherited_counts:
                        add_discarded_count(
                            inherited_product_id,
                            inherited_count,
                        )
                elif event.continuity_reset:
                    add_discarded_count(
                        event.product_id,
                        event.discarded_event_count,
                    )

                if event.contains_market_snapshot:
                    # The queued snapshot itself is also being discarded.  A
                    # control-only marker carries prior loss but is not another
                    # missing market observation.
                    add_discarded_count(event.product_id, 1)

            add_discarded_count(
                product_id,
                additional_discarded_event_count,
            )

            # One aggregate boundary preserves a hard queue bound even when
            # the discarded backlog spans more products than the configured
            # capacity.  When present, the current publication is the sole
            # retained market snapshot; every other affected product waits for
            # its next tick after the bridge consumes its reset count.
            sequence = self._new_sequence_locked()
            reset_count_items = tuple(discarded_counts.items())
            self._market_events.append(
                MarketEvent(
                    sequence=sequence,
                    product_id=product_id,
                    payload=payload,
                    published_monotonic=float(self._clock()),
                    contains_market_snapshot=contains_market_snapshot,
                    continuity_reset=bool(reset_count_items),
                    discarded_event_count=sum(discarded_counts.values()),
                    continuity_reset_counts=reset_count_items,
                )
            )
            self._condition.notify_all()
            return discarded

    def schedule_deadline(
        self,
        stealth_order_id: str,
        purpose: StealthWakePurpose,
        deadline_monotonic: float,
    ) -> int:
        """Schedule or replace one logical deadline and return its generation.

        Replacement advances the key's generation.  The previous heap entry is
        not edited in place; it becomes stale and will be discarded without
        producing a wake.  Every schedule notifies the condition, which is
        essential when the new deadline is earlier than the worker's current
        wait target.
        """

        order_id = self._validate_stealth_order_id(stealth_order_id)
        wake_purpose = self._validate_purpose(purpose)
        deadline = self._validate_deadline(deadline_monotonic)
        key = (order_id, wake_purpose)

        with self._condition:
            self._require_running_locked()
            generation = self._deadline_generations.get(key, 0) + 1
            self._deadline_generations[key] = generation
            sequence = self._new_sequence_locked()
            active = (deadline, sequence, generation)
            self._active_deadlines[key] = active
            heapq.heappush(
                self._deadline_heap,
                (deadline, sequence, order_id, wake_purpose, generation),
            )
            self._compact_deadline_heap_locked()
            self._condition.notify_all()
            return generation

    def schedule_after(
        self,
        stealth_order_id: str,
        purpose: StealthWakePurpose,
        delay_seconds: float,
    ) -> int:
        """Schedule relative to the injected monotonic clock."""

        try:
            delay = float(delay_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError("delay_seconds must be a finite non-negative number") from exc
        if not math.isfinite(delay) or delay < 0:
            raise ValueError("delay_seconds must be a finite non-negative number")
        return self.schedule_deadline(
            stealth_order_id,
            purpose,
            float(self._clock()) + delay,
        )

    def invalidate_deadline(
        self,
        stealth_order_id: str,
        purpose: StealthWakePurpose,
        *,
        expected_generation: Optional[int] = None,
    ) -> Optional[int]:
        """Invalidate a logical deadline and return the new generation.

        When ``expected_generation`` is supplied, invalidation is a
        compare-and-invalidate operation.  A stale caller receives ``None`` and
        cannot accidentally cancel a newer schedule.
        """

        order_id = self._validate_stealth_order_id(stealth_order_id)
        wake_purpose = self._validate_purpose(purpose)
        key = (order_id, wake_purpose)

        with self._condition:
            self._require_running_locked()
            current = self._deadline_generations.get(key, 0)
            if expected_generation is not None and current != expected_generation:
                return None

            generation = current + 1
            self._deadline_generations[key] = generation
            self._active_deadlines.pop(key, None)
            self._compact_deadline_heap_locked()
            # Invalidating the previous earliest entry must also wake a waiter
            # so that it can recompute its timeout from the new heap head.
            self._condition.notify_all()
            return generation

    def claim_deadline_wake(self, wake: DeadlineWake) -> Optional[int]:
        """Atomically claim one delivered wake and return its claim generation.

        A deadline callback and a live-ticker fast path may race to own the
        same logical anchor wake.  Advancing the generation here is the single
        compare-and-claim operation: exactly one owner succeeds, and a later
        callback for the captured generation becomes stale.
        """

        if not isinstance(wake, DeadlineWake):
            raise TypeError("wake must be a DeadlineWake")
        order_id = self._validate_stealth_order_id(wake.stealth_order_id)
        purpose = self._validate_purpose(wake.purpose)
        key = (order_id, purpose)

        with self._condition:
            if self._stopped:
                return None
            current = self._deadline_generations.get(key, 0)
            if current != wake.generation:
                return None

            claim_generation = current + 1
            self._deadline_generations[key] = claim_generation
            self._active_deadlines.pop(key, None)
            captured = self._worker_captured_deadlines.get(key)
            if captured is not None and captured.generation == wake.generation:
                self._worker_captured_deadlines.pop(key, None)
            self._compact_deadline_heap_locked()
            self._condition.notify_all()
            return claim_generation

    def claim_due_deadline(
        self,
        stealth_order_id: str,
        purpose: StealthWakePurpose,
        *,
        now: Optional[float] = None,
    ) -> Optional[int]:
        """Claim an active or worker-captured deadline that is already due.

        This is intentionally a deadline-lane operation, not a second timer.
        It lets the live ticker path atomically observe an anchor deadline even
        when the autonomous consumer has removed that wake from the heap but
        has not yet dispatched its bridge callback.
        """

        order_id = self._validate_stealth_order_id(stealth_order_id)
        wake_purpose = self._validate_purpose(purpose)
        effective_now = self._validate_deadline(
            self._clock() if now is None else now
        )
        key = (order_id, wake_purpose)

        with self._condition:
            self._require_running_locked()
            current = self._deadline_generations.get(key, 0)
            active = self._active_deadlines.get(key)
            captured = self._worker_captured_deadlines.get(key)
            active_due = bool(
                active is not None
                and active[2] == current
                and active[0] <= effective_now
            )
            captured_due = bool(
                captured is not None
                and captured.generation == current
                and captured.deadline_monotonic <= effective_now
            )
            if not active_due and not captured_due:
                return None

            claim_generation = current + 1
            self._deadline_generations[key] = claim_generation
            self._active_deadlines.pop(key, None)
            if captured_due:
                self._worker_captured_deadlines.pop(key, None)
            self._compact_deadline_heap_locked()
            self._condition.notify_all()
            return claim_generation

    # ------------------------------------------------------------------
    # Ready-work collection
    # ------------------------------------------------------------------

    def _entry_is_active_locked(self, entry: _HeapEntry) -> bool:
        deadline, sequence, order_id, purpose, generation = entry
        active = self._active_deadlines.get((order_id, purpose))
        return active == (deadline, sequence, generation)

    def _prune_stale_head_locked(self) -> None:
        while self._deadline_heap:
            if self._entry_is_active_locked(self._deadline_heap[0]):
                return
            heapq.heappop(self._deadline_heap)

    def _compact_deadline_heap_locked(self) -> None:
        """Bound stale-entry growth without changing active deadline order."""

        active_count = len(self._active_deadlines)
        heap_count = len(self._deadline_heap)
        # Small heaps are cheaper to prune lazily.  Compact once stale entries
        # dominate a non-trivial heap (common when one order is repriced often).
        if heap_count < 64 or heap_count <= max(1, active_count * 2):
            return

        rebuilt: list[_HeapEntry] = []
        for (order_id, purpose), (deadline, sequence, generation) in (
            self._active_deadlines.items()
        ):
            rebuilt.append(
                (deadline, sequence, order_id, purpose, generation)
            )
        heapq.heapify(rebuilt)
        self._deadline_heap = rebuilt

    def _collect_ready_locked(
        self,
        now: float,
        *,
        market_event_limit: Optional[int] = None,
        track_worker_capture: bool = False,
    ) -> SchedulerBatch:
        if market_event_limit is None:
            market_events = tuple(self._market_events)
            self._market_events.clear()
        else:
            market_events = tuple(
                self._market_events.popleft()
                for _ in range(min(market_event_limit, len(self._market_events)))
            )

        deadline_wakes = []
        self._prune_stale_head_locked()
        while self._deadline_heap and self._deadline_heap[0][0] <= now:
            deadline, _sequence, order_id, purpose, generation = heapq.heappop(
                self._deadline_heap
            )
            key = (order_id, purpose)
            active = self._active_deadlines.get(key)
            if active != (deadline, _sequence, generation):
                self._prune_stale_head_locked()
                continue

            self._active_deadlines.pop(key, None)
            wake = DeadlineWake(
                stealth_order_id=order_id,
                purpose=purpose,
                generation=generation,
                deadline_monotonic=deadline,
            )
            deadline_wakes.append(wake)
            if track_worker_capture:
                self._worker_captured_deadlines[key] = wake
            self._prune_stale_head_locked()

        return SchedulerBatch(
            market_events=market_events,
            deadline_wakes=tuple(deadline_wakes),
        )

    def take_due(self, *, now: Optional[float] = None) -> SchedulerBatch:
        """Synchronously remove all currently ready work.

        ``now`` is an explicit fake-clock seam.  When omitted, the injected
        monotonic clock is read exactly once for deadline eligibility.  Pending
        market events are always ready and retain FIFO order.
        """

        effective_now = self._validate_deadline(
            self._clock() if now is None else now
        )
        with self._condition:
            if self._stopped:
                return SchedulerBatch()
            return self._collect_ready_locked(effective_now)

    def _dispatch_batch(
        self,
        batch: SchedulerBatch,
        on_market_event: Optional[MarketEventHandler],
        on_deadline: Optional[DeadlineWakeHandler],
        on_error: Optional[SchedulerErrorHandler],
    ) -> None:
        # Due deadlines have priority over the market FIFO.  CONDITION_HOLD is
        # only a marker, while the other deadline lanes are independent of
        # ordered price evidence.  Processing them first prevents a hot ticker
        # backlog from delaying an already-due admission/time/anchor wake.
        for item in batch.deadline_wakes:
            try:
                if on_deadline is not None:
                    on_deadline(item)
            except Exception as exc:
                if on_error is None:
                    raise
                on_error(exc, item)
            finally:
                with self._condition:
                    captured = self._worker_captured_deadlines.get(
                        (item.stealth_order_id, item.purpose)
                    )
                    if (
                        captured is not None
                        and captured.generation == item.generation
                    ):
                        self._worker_captured_deadlines.pop(
                            (item.stealth_order_id, item.purpose),
                            None,
                        )

        for item in batch.market_events:
            if on_market_event is None:
                continue
            try:
                on_market_event(item)
            except Exception as exc:
                if on_error is None:
                    raise
                on_error(exc, item)

    def run_due(
        self,
        *,
        now: Optional[float] = None,
        on_market_event: Optional[MarketEventHandler] = None,
        on_deadline: Optional[DeadlineWakeHandler] = None,
        on_error: Optional[SchedulerErrorHandler] = None,
    ) -> SchedulerBatch:
        """Synchronously take and optionally dispatch all ready work.

        The returned batch always exposes exactly what was removed, making this
        method deterministic in unit tests even when no callbacks are supplied.
        Callbacks run outside the scheduler condition and may safely publish or
        schedule subsequent work.
        """

        batch = self.take_due(now=now)
        self._dispatch_batch(batch, on_market_event, on_deadline, on_error)
        return batch

    # ------------------------------------------------------------------
    # Blocking / worker API
    # ------------------------------------------------------------------

    def _next_wait_timeout_locked(self, now: float) -> Optional[float]:
        self._prune_stale_head_locked()
        if not self._deadline_heap:
            return None
        return max(0.0, self._deadline_heap[0][0] - now)

    def wait_for_due(
        self,
        *,
        market_event_limit: Optional[int] = None,
        _track_worker_capture: bool = False,
    ) -> Optional[SchedulerBatch]:
        """Block until ready work exists or stop is requested.

        Returns ``None`` after terminal stop.  This method is suitable as the
        wait primitive for a bridge-owned thread as an alternative to
        :meth:`start`.
        """

        with self._condition:
            while True:
                if self._stopped:
                    return None

                now = self._validate_deadline(self._clock())
                self._prune_stale_head_locked()
                deadline_due = bool(
                    self._deadline_heap
                    and self._deadline_heap[0][0] <= now
                )
                if self._market_events or deadline_due:
                    return self._collect_ready_locked(
                        now,
                        market_event_limit=market_event_limit,
                        track_worker_capture=_track_worker_capture,
                    )

                self._condition.wait(
                    timeout=self._next_wait_timeout_locked(now)
                )

    def run_forever(
        self,
        *,
        on_market_event: MarketEventHandler,
        on_deadline: DeadlineWakeHandler,
        on_error: Optional[SchedulerErrorHandler] = None,
        on_fatal: Optional[SchedulerFatalHandler] = None,
    ) -> None:
        """Run the blocking consumer loop in the current thread."""

        if not callable(on_market_event) or not callable(on_deadline):
            raise TypeError("run_forever requires callable market and deadline handlers")

        try:
            while True:
                # One market callback per collection bounds priority inversion:
                # a deadline that becomes due while a ticker is being handled
                # is reconsidered before the next queued ticker.
                batch = self.wait_for_due(
                    market_event_limit=1,
                    _track_worker_capture=True,
                )
                if batch is None:
                    return
                self._dispatch_batch(
                    batch,
                    on_market_event,
                    on_deadline,
                    on_error,
                )
        except Exception as exc:
            # Fail closed and retain the exception for supervisory inspection.
            # A callback supplied via ``on_error`` can absorb individual handler
            # errors and keep this loop alive.
            with self._condition:
                self._worker_error = exc
                self._stopped = True
                self._condition.notify_all()
            if on_fatal is not None:
                try:
                    on_fatal(exc)
                except Exception:
                    # The original worker exception remains authoritative; a
                    # supervisory callback must not hide or replace it.
                    pass

    def start(
        self,
        *,
        on_market_event: MarketEventHandler,
        on_deadline: DeadlineWakeHandler,
        on_error: Optional[SchedulerErrorHandler] = None,
        on_fatal: Optional[SchedulerFatalHandler] = None,
        daemon: bool = True,
    ) -> threading.Thread:
        """Start the scheduler's one optional worker thread."""

        if not callable(on_market_event) or not callable(on_deadline):
            raise TypeError("start requires callable market and deadline handlers")
        if on_error is not None and not callable(on_error):
            raise TypeError("on_error must be callable when provided")
        if on_fatal is not None and not callable(on_fatal):
            raise TypeError("on_fatal must be callable when provided")

        with self._condition:
            self._require_running_locked()
            if self._worker is not None and self._worker.is_alive():
                raise RuntimeError("scheduler worker is already running")

            worker = threading.Thread(
                target=self.run_forever,
                kwargs={
                    "on_market_event": on_market_event,
                    "on_deadline": on_deadline,
                    "on_error": on_error,
                    "on_fatal": on_fatal,
                },
                name=self._thread_name,
                daemon=daemon,
            )
            self._worker = worker
            worker.start()
            return worker

    def stop(self, *, join_timeout: Optional[float] = 1.0) -> bool:
        """Request terminal stop, wake a waiting worker, and optionally join.

        Returns ``True`` when no worker remains alive.  A handler already
        running in user code is cooperative and cannot be forcibly interrupted.
        """

        if join_timeout is not None and join_timeout < 0:
            raise ValueError("join_timeout must be non-negative or None")

        with self._condition:
            self._stopped = True
            self._condition.notify_all()
            worker = self._worker

        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=join_timeout)
        return worker is None or not worker.is_alive()

    # ------------------------------------------------------------------
    # Read-only diagnostics
    # ------------------------------------------------------------------

    @property
    def stopped(self) -> bool:
        with self._condition:
            return self._stopped

    @property
    def worker_error(self) -> Optional[Exception]:
        with self._condition:
            return self._worker_error

    @property
    def pending_market_event_count(self) -> int:
        with self._condition:
            return len(self._market_events)

    @property
    def active_deadline_count(self) -> int:
        with self._condition:
            return len(self._active_deadlines)

    def current_generation(
        self,
        stealth_order_id: str,
        purpose: StealthWakePurpose,
    ) -> int:
        order_id = self._validate_stealth_order_id(stealth_order_id)
        wake_purpose = self._validate_purpose(purpose)
        with self._condition:
            return self._deadline_generations.get((order_id, wake_purpose), 0)

    @property
    def next_deadline_monotonic(self) -> Optional[float]:
        with self._condition:
            self._prune_stale_head_locked()
            if not self._deadline_heap:
                return None
            return self._deadline_heap[0][0]


__all__ = [
    "DeadlineWake",
    "MarketEvent",
    "MarketEventQueueFullError",
    "SchedulerBatch",
    "SchedulerStoppedError",
    "StealthEventDeadlineScheduler",
    "StealthWakePurpose",
]
