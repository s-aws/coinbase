"""Regression: 2026-04-29 duplicate-buy / over-buy incident.

Background
==========

A 100-unit SELL order on BIP-20DEC30-CDE filled in 6 partial matches
(13 + 12 + 16 + 29 + 29 + 1 = 100) over a few hundred milliseconds.
Six WS deltas arrived on six worker threads. The original code path:

1. ``OrderProgressTracker.ingest()`` correctly serialised carry
   accumulation under a per-order lock (carry climbed 13 -> 25 -> 41 ->
   70 -> 99 -> 100).
2. ``OrderProgressTracker.get_record()`` then handed out a *snapshot
   copy* of the record to each WS worker.
3. Each ``_create_partial_fill_follow_up`` call read the snapshot's
   ``carry_remainder_qty`` and computed
   ``follow_ups_due = int(carry / min_size)``.
4. The slow REST-place call ran outside the per-order lock.
5. ``consume_carry_units`` was called AFTER the place returned.

The race window between step 2 and step 5 meant five concurrent worker
threads all observed ``carry == 100`` and each spawned a 100-unit
follow-up BUY. Net result: 500 units bought when only 100 were due,
all of which subsequently filled at 76490-76495 -> direct realised loss.

Fix
===

``OrderProgressTracker`` gained ``claim_follow_up_units(coid, max)``,
which atomically computes available units, decrements carry, and bumps
``partial_follow_ups_created`` under the per-order lock and returns
the actual reservation. ``_create_partial_fill_follow_up`` now claims
units BEFORE the REST-place call. Concurrent threads observe the
already-reduced carry and back off (claim returns 0).

These tests pin the contract:

1. Atomic-claim correctness under concurrency at the tracker layer.
2. End-to-end: many concurrent
   ``_create_partial_fill_follow_up`` calls produce at most ONE
   follow-up creation per unit of carry, never one per concurrent call.
"""
from __future__ import annotations

import threading
from math import isclose
from unittest.mock import Mock

import pytest

from business.order_progress import OrderProgressTracker
from tests.unit.test_partial_fill_followups import (
    _build_engine_for_partial_fill_tests,
    _link_child_to_opted_in_parent,
)


# ---------------------------------------------------------------------------
# Tracker-level: atomic claim under contention
# ---------------------------------------------------------------------------


def _make_tracker_with_carry(
    coid: str, *, total: float, min_size: float, parent: str = "parent-x"
) -> OrderProgressTracker:
    tracker = OrderProgressTracker(
        min_order_size_resolver=lambda product_id: min_size,
        parent_resolver=lambda c: parent,
    )
    tracker.hydrate([
        {
            "client_order_id": coid,
            "parent_client_order_id": parent,
            "product_id": "BIP-20DEC30-CDE",
            "side": "SELL",
            "original_order_size": total,
            "min_order_size": min_size,
            "carry_remainder_qty": total,
            "partial_follow_ups_created": 0,
        }
    ])
    return tracker


@pytest.mark.regression
def test_claim_follow_up_units_is_atomic_under_concurrent_threads():
    """Many concurrent threads each requesting the maximum claim must
    collectively never reserve more units than ``carry / min_size``.

    Without the atomic claim, each thread would independently observe
    the same large carry value and over-reserve; with the claim, the
    grand total is bounded by what was actually available."""
    coid = "race-1"
    available_units = 100  # carry = 100, min_size = 1 -> 100 units available
    tracker = _make_tracker_with_carry(coid, total=100.0, min_size=1.0)

    n_threads = 12
    requested_per_thread = 100  # each thread asks for the max
    barrier = threading.Barrier(n_threads)
    claimed = [0] * n_threads

    def worker(i: int) -> None:
        barrier.wait()  # release all together to maximise contention
        claimed[i] = tracker.claim_follow_up_units(coid, max_units=requested_per_thread)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    total_claimed = sum(claimed)
    assert total_claimed == available_units, (
        f"Atomic claim bug: {n_threads} threads collectively reserved "
        f"{total_claimed} units when only {available_units} were available. "
        f"Per-thread claims: {claimed}. See 2026-04-29 over-buy incident."
    )

    record = tracker.get_record(coid)
    assert record is not None
    assert isclose(record.carry_remainder_qty, 0.0, abs_tol=1e-9), (
        f"Carry remainder must be exhausted after claims; got "
        f"{record.carry_remainder_qty}"
    )
    assert record.partial_follow_ups_created == available_units


@pytest.mark.regression
def test_claim_follow_up_units_returns_zero_when_carry_exhausted():
    """Once the carry is drained, subsequent claims must return 0 \u2014 not
    re-issue the same units."""
    coid = "race-2"
    tracker = _make_tracker_with_carry(coid, total=5.0, min_size=1.0)

    first = tracker.claim_follow_up_units(coid, max_units=5)
    second = tracker.claim_follow_up_units(coid, max_units=5)
    third = tracker.claim_follow_up_units(coid, max_units=5)

    assert first == 5
    assert second == 0
    assert third == 0


@pytest.mark.regression
def test_release_follow_up_units_refunds_a_failed_claim():
    """A failed REST place call must be refundable so the next WS delta
    can re-attempt the follow-up."""
    coid = "race-3"
    tracker = _make_tracker_with_carry(coid, total=10.0, min_size=1.0)

    claimed = tracker.claim_follow_up_units(coid, max_units=4)
    assert claimed == 4

    record = tracker.get_record(coid)
    assert record is not None
    assert isclose(record.carry_remainder_qty, 6.0, abs_tol=1e-9)
    assert record.partial_follow_ups_created == 4

    tracker.release_follow_up_units(coid, claimed)

    record = tracker.get_record(coid)
    assert record is not None
    assert isclose(record.carry_remainder_qty, 10.0, abs_tol=1e-9)
    assert record.partial_follow_ups_created == 0

    # And the refunded units must be re-claimable.
    re_claim = tracker.claim_follow_up_units(coid, max_units=10)
    assert re_claim == 10


# ---------------------------------------------------------------------------
# End-to-end: concurrent _create_partial_fill_follow_up calls
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_concurrent_create_partial_fill_follow_up_does_not_overspawn():
    """Reproduces the production over-buy: an already-accumulated carry
    of 100 units exposed via the snapshot must produce at most ONE
    follow-up creation across N concurrent worker threads, not N copies.

    Pre-fix: each of N concurrent calls observed
    ``carry_remainder_qty == 100`` from the read-only snapshot and each
    spawned a 100-unit follow-up. The exact pattern from the
    2026-04-29 incident.
    """
    engine = _build_engine_for_partial_fill_tests()

    placed_coid = "race-coid-1"
    parent_coid = "race-parent-1"
    _link_child_to_opted_in_parent(engine, placed_coid, parent_coid)

    # Seed the tracker so the per-order record has 100 units of carry
    # available (matches the production incident exactly: 100-unit
    # SELL filled in multiple partial matches).
    engine.order_progress_tracker.hydrate([
        {
            "client_order_id": placed_coid,
            "parent_client_order_id": parent_coid,
            "product_id": "BIP-20DEC30-CDE",
            "side": "SELL",
            "original_order_size": 100.0,
            "min_order_size": 1.0,
            "carry_remainder_qty": 100.0,
            "partial_follow_ups_created": 0,
        }
    ])

    # Make can_create_follow_up_order generous so the only gating factor
    # is the atomic-claim contention.
    engine.can_create_follow_up_order = Mock(
        return_value=(
            True,
            {"max_order_replacement": 1000, "current_order_replacement": 0},
        )
    )
    engine.resolve_parent_target_movement = Mock(
        return_value={"movement": 0.001, "type": "P"}
    )
    engine.compute_partial_fill_order_template = Mock(
        return_value={
            "start_price": "76525.0",
            "side": "BUY",
            "order_base_size": "100",
            "product_id": "BIP-20DEC30-CDE",
        }
    )
    engine.register_child_order = Mock()

    stealth_manager = Mock()
    stealth_manager.find_stealth_order_by_placed_order_id.return_value = {
        "stealth_order_id": "stealth-parent-race",
        "reveal_condition_json": {"type": "price", "direction": "above"},
        "follow_up_reveal_direction": "opposite",
    }
    # Each call returns a unique follow-up id so we can count creations.
    follow_up_ids = []
    follow_up_ids_lock = threading.Lock()

    def _create_fu(**kwargs):
        with follow_up_ids_lock:
            i = len(follow_up_ids)
            fu_id = f"stealth-follow-up-{i}"
            follow_up_ids.append((fu_id, kwargs.get("total_size")))
            return fu_id

    stealth_manager.create_follow_up_stealth_order.side_effect = _create_fu
    engine.stealth_order_bridge = Mock(stealth_manager=stealth_manager)
    engine.db_helper.get_parent_order.return_value = {
        "target_movement": 0.001,
        "target_movement_type": "P",
    }

    # Fire many concurrent invocations. Pre-fix: each would spawn a
    # 100-unit follow-up. Post-fix: claim is atomic, so the FIRST
    # winning claim grabs all 100 units and subsequent claims see 0
    # carry remaining and return without spawning.
    n_threads = 8
    barrier = threading.Barrier(n_threads)
    results = [None] * n_threads

    def worker(i: int) -> None:
        barrier.wait()
        results[i] = engine._create_partial_fill_follow_up(
            client_order_id=placed_coid,
            parent_client_order_id=parent_coid,
            min_order_size=1.0,
            follow_ups_due=100,
        )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    total_units_created = sum(r for r in results if r)
    assert total_units_created == 100, (
        f"Concurrent partial-fill follow-up creators over-spawned: "
        f"created {total_units_created} units when carry was only 100. "
        f"Per-thread results: {results}. "
        f"This is the 2026-04-29 over-buy bug regressing."
    )

    # Sum of follow-up sizes across all stealth_manager calls must equal
    # the original carry. Pre-fix this would have been N * 100.
    total_follow_up_size = sum(float(size or 0) for _, size in follow_up_ids)
    assert isclose(total_follow_up_size, 100.0, abs_tol=1e-9), (
        f"Sum of created follow-up sizes is {total_follow_up_size}, "
        f"expected 100.0. Per-call sizes: "
        f"{[(fid, sz) for fid, sz in follow_up_ids]}. "
        f"This is the 2026-04-29 over-buy bug regressing."
    )

    # Carry must be drained.
    record = engine.order_progress_tracker.get_record(placed_coid)
    assert record is not None
    assert isclose(record.carry_remainder_qty, 0.0, abs_tol=1e-9)
    assert record.partial_follow_ups_created == 100
