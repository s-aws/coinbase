"""Focused tests for the manager/DB/REST-independent scheduler primitive."""

from __future__ import annotations

import threading
import time

import pytest

from bridges.stealth_event_deadline_scheduler import (
    MarketEventQueueFullError,
    SchedulerStoppedError,
    StealthEventDeadlineScheduler,
)
from core.enums import MarketEventMode, StealthWakePurpose


class FakeClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def test_market_events_are_fifo_and_never_implicitly_coalesced() -> None:
    clock = FakeClock()
    scheduler = StealthEventDeadlineScheduler(clock=clock)

    sequences = [
        scheduler.publish_market_event("BTC-USD", {"price": price})
        for price in (101, 102, 103)
    ]

    batch = scheduler.run_due(now=clock.value)

    assert sequences == [1, 2, 3]
    assert [event.sequence for event in batch.market_events] == sequences
    assert [event.payload["price"] for event in batch.market_events] == [101, 102, 103]
    assert [event.product_id for event in batch.market_events] == [
        "BTC-USD",
        "BTC-USD",
        "BTC-USD",
    ]
    assert batch.deadline_wakes == ()


def test_stale_invalidation_uses_the_existing_market_fifo() -> None:
    clock = FakeClock()
    scheduler = StealthEventDeadlineScheduler(clock=clock)

    scheduler.publish_market_event("BTC-USD", {"price": 102})
    scheduler.publish_market_event(
        "BTC-USD",
        {"price": 99},
        mode=MarketEventMode.STALE_INVALIDATION,
    )
    scheduler.publish_market_event("BTC-USD", {"price": 103})

    events = scheduler.run_due(now=clock.value).market_events

    assert [event.sequence for event in events] == [1, 2, 3]
    assert [event.mode for event in events] == [
        MarketEventMode.NORMAL,
        MarketEventMode.STALE_INVALIDATION,
        MarketEventMode.NORMAL,
    ]
    assert events[1].contains_market_snapshot is False
    assert events[1].continuity_reset is False
    assert events[1].discarded_event_count == 0
    assert events[1].continuity_reset_counts == ()


def test_fake_clock_deadlines_fire_in_deadline_then_insertion_order() -> None:
    clock = FakeClock()
    scheduler = StealthEventDeadlineScheduler(clock=clock)

    later_generation = scheduler.schedule_deadline(
        "later", StealthWakePurpose.TIME_DELAY, 105.0
    )
    first_tie_generation = scheduler.schedule_deadline(
        "first-tie", StealthWakePurpose.CONDITION_HOLD, 103.0
    )
    second_tie_generation = scheduler.schedule_deadline(
        "second-tie", StealthWakePurpose.ADMISSION_RETRY, 103.0
    )

    assert scheduler.run_due(now=102.999).empty

    tie_batch = scheduler.run_due(now=103.0)
    assert [wake.stealth_order_id for wake in tie_batch.deadline_wakes] == [
        "first-tie",
        "second-tie",
    ]
    assert [wake.generation for wake in tie_batch.deadline_wakes] == [
        first_tie_generation,
        second_tie_generation,
    ]

    later_batch = scheduler.run_due(now=105.0)
    assert len(later_batch.deadline_wakes) == 1
    assert later_batch.deadline_wakes[0].stealth_order_id == "later"
    assert later_batch.deadline_wakes[0].generation == later_generation
    assert scheduler.active_deadline_count == 0


def test_rescheduled_deadline_makes_old_generation_a_noop() -> None:
    clock = FakeClock()
    scheduler = StealthEventDeadlineScheduler(clock=clock)
    purpose = StealthWakePurpose.CONDITION_HOLD

    old_generation = scheduler.schedule_deadline("sid-1", purpose, 101.0)
    new_generation = scheduler.schedule_deadline("sid-1", purpose, 105.0)

    assert new_generation == old_generation + 1
    assert scheduler.current_generation("sid-1", purpose) == new_generation
    assert scheduler.run_due(now=101.0).deadline_wakes == ()

    batch = scheduler.run_due(now=105.0)
    assert [(wake.stealth_order_id, wake.generation) for wake in batch.deadline_wakes] == [
        ("sid-1", new_generation)
    ]


def test_invalidation_is_generation_guarded_and_stale_heap_entry_never_fires() -> None:
    clock = FakeClock()
    scheduler = StealthEventDeadlineScheduler(clock=clock)
    purpose = StealthWakePurpose.ANCHOR_REPRICE

    generation = scheduler.schedule_deadline("sid-1", purpose, 101.0)
    replacement_generation = scheduler.schedule_deadline("sid-1", purpose, 102.0)

    # A stale owner cannot invalidate the replacement.
    assert scheduler.invalidate_deadline(
        "sid-1", purpose, expected_generation=generation
    ) is None
    assert scheduler.active_deadline_count == 1

    invalidated_generation = scheduler.invalidate_deadline(
        "sid-1", purpose, expected_generation=replacement_generation
    )
    assert invalidated_generation == replacement_generation + 1
    assert scheduler.active_deadline_count == 0
    assert scheduler.run_due(now=999.0).deadline_wakes == ()


def test_due_deadline_can_be_atomically_claimed_before_worker_dispatch() -> None:
    clock = FakeClock()
    scheduler = StealthEventDeadlineScheduler(clock=clock)
    purpose = StealthWakePurpose.ANCHOR_REPRICE

    scheduled_generation = scheduler.schedule_deadline(
        "sid-1",
        purpose,
        clock.value,
    )
    claim_generation = scheduler.claim_due_deadline("sid-1", purpose)

    assert claim_generation == scheduled_generation + 1
    assert scheduler.current_generation("sid-1", purpose) == claim_generation
    assert scheduler.active_deadline_count == 0
    assert scheduler.run_due(now=clock.value).deadline_wakes == ()
    assert scheduler.claim_due_deadline("sid-1", purpose) is None


def test_future_reschedule_revokes_a_worker_captured_deadline() -> None:
    scheduler = StealthEventDeadlineScheduler()
    captured = threading.Event()
    release_callback = threading.Event()
    callback_claims = []
    purpose = StealthWakePurpose.ANCHOR_REPRICE

    def delayed_callback(wake) -> None:
        captured.set()
        assert release_callback.wait(timeout=0.75)
        callback_claims.append(scheduler.claim_deadline_wake(wake))

    scheduler.start(
        on_market_event=lambda _event: None,
        on_deadline=delayed_callback,
    )

    try:
        scheduler.schedule_after("sid-1", purpose, 0)
        assert captured.wait(timeout=0.75)

        future_generation = scheduler.schedule_after("sid-1", purpose, 60)

        assert scheduler.claim_due_deadline("sid-1", purpose) is None
        release_callback.set()
        deadline = time.monotonic() + 0.75
        while not callback_claims and time.monotonic() < deadline:
            time.sleep(0.005)

        assert callback_claims == [None]
        assert scheduler.current_generation("sid-1", purpose) == (
            future_generation
        )
        assert scheduler.active_deadline_count == 1
    finally:
        release_callback.set()
        scheduler.stop(join_timeout=0.75)


def test_purposes_have_independent_generations_for_same_logical_order() -> None:
    clock = FakeClock()
    scheduler = StealthEventDeadlineScheduler(clock=clock)

    condition_generation = scheduler.schedule_deadline(
        "sid-1", StealthWakePurpose.CONDITION_HOLD, 101.0
    )
    anchor_generation = scheduler.schedule_deadline(
        "sid-1", StealthWakePurpose.ANCHOR_REPRICE, 101.0
    )

    batch = scheduler.run_due(now=101.0)
    assert [wake.purpose for wake in batch.deadline_wakes] == [
        StealthWakePurpose.CONDITION_HOLD,
        StealthWakePurpose.ANCHOR_REPRICE,
    ]
    assert [wake.generation for wake in batch.deadline_wakes] == [
        condition_generation,
        anchor_generation,
    ]


def test_synchronous_callbacks_run_outside_condition_and_can_schedule_more_work() -> None:
    clock = FakeClock()
    scheduler = StealthEventDeadlineScheduler(clock=clock)
    seen = []

    scheduler.schedule_deadline(
        "sid-1", StealthWakePurpose.CONDITION_HOLD, clock.value
    )

    def on_deadline(wake) -> None:
        seen.append(wake.stealth_order_id)
        scheduler.schedule_deadline(
            "sid-2", StealthWakePurpose.CONDITION_HOLD, clock.value
        )

    first = scheduler.run_due(now=clock.value, on_deadline=on_deadline)
    second = scheduler.run_due(now=clock.value, on_deadline=on_deadline)

    assert [wake.stealth_order_id for wake in first.deadline_wakes] == ["sid-1"]
    assert [wake.stealth_order_id for wake in second.deadline_wakes] == ["sid-2"]
    assert seen == ["sid-1", "sid-2"]


def test_scheduling_an_earlier_deadline_wakes_single_worker() -> None:
    # Keeping the fake clock fixed makes this deterministic: the worker first
    # has a 900-second wait target, then an immediately-due schedule notifies
    # the one Condition and forces it to recompute.
    clock = FakeClock()
    scheduler = StealthEventDeadlineScheduler(clock=clock)
    fired = threading.Event()
    seen = []

    scheduler.schedule_deadline(
        "far", StealthWakePurpose.TIME_DELAY, 1_000.0
    )
    worker = scheduler.start(
        on_market_event=lambda _event: None,
        on_deadline=lambda wake: (seen.append(wake.stealth_order_id), fired.set()),
    )

    scheduler.schedule_deadline(
        "early", StealthWakePurpose.ADMISSION_RETRY, clock.value
    )

    assert fired.wait(timeout=0.5), "earlier deadline did not wake scheduler worker"
    assert seen == ["early"]
    assert scheduler.stop(join_timeout=0.5) is True
    assert not worker.is_alive()


def test_stop_interrupts_long_wait_promptly_and_is_terminal() -> None:
    scheduler = StealthEventDeadlineScheduler()
    scheduler.schedule_after("sid-1", StealthWakePurpose.TIME_DELAY, 60.0)
    worker = scheduler.start(
        on_market_event=lambda _event: None,
        on_deadline=lambda _wake: None,
    )

    started = time.monotonic()
    stopped = scheduler.stop(join_timeout=0.5)
    elapsed = time.monotonic() - started

    assert stopped is True
    assert elapsed < 0.5
    assert not worker.is_alive()
    with pytest.raises(SchedulerStoppedError):
        scheduler.publish_market_event("BTC-USD", {"price": 100})
    with pytest.raises(SchedulerStoppedError):
        scheduler.schedule_deadline(
            "sid-2", StealthWakePurpose.TIME_DELAY, time.monotonic()
        )


def test_bounded_market_fifo_fails_loudly_instead_of_dropping_or_coalescing() -> None:
    scheduler = StealthEventDeadlineScheduler(market_queue_limit=2)
    scheduler.publish_market_event("BTC-USD", 1)
    scheduler.publish_market_event("BTC-USD", 2)

    with pytest.raises(MarketEventQueueFullError):
        scheduler.publish_market_event("BTC-USD", 3)

    batch = scheduler.run_due()
    assert [event.payload for event in batch.market_events] == [1, 2]


def test_due_deadline_dispatches_before_an_existing_market_backlog() -> None:
    clock = FakeClock()
    scheduler = StealthEventDeadlineScheduler(clock=clock)
    seen = []

    for price in range(100):
        scheduler.publish_market_event("BTC-USD", {"price": price})
    scheduler.schedule_deadline(
        "sid-due",
        StealthWakePurpose.TIME_DELAY,
        clock.value,
    )

    scheduler.run_due(
        now=clock.value,
        on_market_event=lambda event: seen.append(
            ("market", event.sequence)
        ),
        on_deadline=lambda wake: seen.append(
            ("deadline", wake.stealth_order_id)
        ),
    )

    assert seen[0] == ("deadline", "sid-due")


def test_worker_rechecks_deadlines_between_market_callbacks() -> None:
    scheduler = StealthEventDeadlineScheduler()
    callback_count = 0
    callback_lock = threading.Lock()
    deadline_fired = threading.Event()

    for price in range(100):
        scheduler.publish_market_event("BTC-USD", {"price": price})

    def on_market_event(_event) -> None:
        nonlocal callback_count
        with callback_lock:
            callback_count += 1
        time.sleep(0.003)

    scheduler.schedule_after(
        "sid-due",
        StealthWakePurpose.TIME_DELAY,
        0.01,
    )
    scheduler.start(
        on_market_event=on_market_event,
        on_deadline=lambda _wake: deadline_fired.set(),
    )

    assert deadline_fired.wait(timeout=0.5)
    with callback_lock:
        callbacks_before_deadline = callback_count
    assert callbacks_before_deadline < 10
    scheduler.stop(join_timeout=0.5)


def test_worker_fatal_callback_runs_without_a_later_producer() -> None:
    scheduler = StealthEventDeadlineScheduler()
    fatal = threading.Event()
    errors = []

    def broken_clock() -> float:
        raise RuntimeError("synthetic clock failure")

    scheduler._clock = broken_clock
    worker = scheduler.start(
        on_market_event=lambda _event: None,
        on_deadline=lambda _wake: None,
        on_fatal=lambda error: (errors.append(error), fatal.set()),
    )

    assert fatal.wait(timeout=0.5)
    worker.join(timeout=0.5)
    assert not worker.is_alive()
    assert scheduler.stopped is True
    assert isinstance(scheduler.worker_error, RuntimeError)
    assert errors == [scheduler.worker_error]


def test_recovery_resets_only_products_with_discarded_events() -> None:
    scheduler = StealthEventDeadlineScheduler(market_queue_limit=2)
    scheduler.publish_market_event("PRODUCT-B", 1)
    scheduler.publish_market_event("PRODUCT-B", 2)

    scheduler.replace_pending_market_events_for_recovery("PRODUCT-A", 3)
    batch = scheduler.run_due()

    assert len(batch.market_events) == 1
    recovery_event = batch.market_events[0]
    assert recovery_event.product_id == "PRODUCT-A"
    assert recovery_event.payload == 3
    assert recovery_event.continuity_reset is True
    assert recovery_event.discarded_event_count == 2
    assert recovery_event.continuity_reset_counts == (("PRODUCT-B", 2),)


def test_repeated_recovery_remains_bounded_and_preserves_exact_loss_counts() -> None:
    scheduler = StealthEventDeadlineScheduler(market_queue_limit=1)
    scheduler.publish_market_event("PRODUCT-A", 1)

    first_discarded = scheduler.replace_pending_market_events_for_recovery(
        "PRODUCT-B",
        2,
    )
    assert len(first_discarded) == 1
    assert scheduler.pending_market_event_count == 1

    second_discarded = scheduler.replace_pending_market_events_for_recovery(
        "PRODUCT-C",
        3,
    )
    assert len(second_discarded) == 1
    assert scheduler.pending_market_event_count == 1

    batch = scheduler.run_due()
    assert len(batch.market_events) == 1
    recovery_event = batch.market_events[0]
    assert recovery_event.product_id == "PRODUCT-C"
    assert recovery_event.payload == 3
    assert recovery_event.discarded_event_count == 2
    assert recovery_event.continuity_reset_counts == (
        ("PRODUCT-A", 1),
        ("PRODUCT-B", 1),
    )


def test_recovery_does_not_count_an_opaque_reset_marker_as_a_lost_tick() -> None:
    scheduler = StealthEventDeadlineScheduler(market_queue_limit=1)
    scheduler.publish_market_continuity_reset(
        "PRODUCT-A",
        discarded_event_count=5,
    )

    scheduler.replace_pending_market_events_for_recovery(
        "PRODUCT-B",
        {"price": 2},
    )
    batch = scheduler.run_due()

    assert len(batch.market_events) == 1
    recovery_event = batch.market_events[0]
    assert recovery_event.contains_market_snapshot is True
    assert recovery_event.discarded_event_count == 5
    assert recovery_event.continuity_reset_counts == (("PRODUCT-A", 5),)


def test_recovery_counts_discarded_stale_invalidation_as_one_observation() -> None:
    scheduler = StealthEventDeadlineScheduler(market_queue_limit=1)
    scheduler.publish_market_event(
        "PRODUCT-A",
        {"price": 1},
        mode=MarketEventMode.STALE_INVALIDATION,
    )

    scheduler.replace_pending_market_events_for_recovery(
        "PRODUCT-B",
        {"price": 2},
    )
    recovery_event = scheduler.run_due().market_events[0]

    assert recovery_event.mode == MarketEventMode.NORMAL
    assert recovery_event.continuity_reset is True
    assert recovery_event.continuity_reset_counts == (("PRODUCT-A", 1),)


def test_enum_purpose_is_required_instead_of_magic_string() -> None:
    scheduler = StealthEventDeadlineScheduler()

    with pytest.raises(TypeError):
        scheduler.schedule_deadline("sid-1", "condition_hold", 1.0)  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        scheduler.publish_market_event(  # type: ignore[arg-type]
            "BTC-USD",
            {"price": 1},
            mode="stale_invalidation",
        )
