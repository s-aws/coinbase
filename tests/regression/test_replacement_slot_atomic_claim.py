"""Regression: 2026-04-29 follow-up replacement-cap breach.

Background
==========

A SELL stealth order ``da7b8b66`` was placed with
``max_order_replacement = 1`` (default). It filled in five partial
matches over ~50ms. Five concurrent ``user_event_thread`` workers
each entered ``_create_partial_fill_follow_up``, each called
``can_create_follow_up_order`` (read-only check), each observed the
same stale ``current_order_replacement`` snapshot, and each passed
the gate. Four BUY follow-ups were created against the same parent
before the in-memory ``current_order_replacement`` finally caught up
and the cap engaged.

DB evidence (post-incident audit, ``order_parent`` row 78):

    max_order_replacement     = 1
    current_order_replacement = 4   ← cap breached 4×

Fix
===

``OrderEngine`` gained ``claim_replacement_slots(parent, n)`` —
atomic under ``orderbook_lock``, factors in pending claims as well
as the persisted ``current_order_replacement``. It is the single
gate for replacement-cap enforcement. Concurrent callers see one
winner and the rest get 0. ``_create_partial_fill_follow_up`` now
goes through this claim BEFORE any I/O. ``register_child_order``
consumes one pending claim when the child eventually registers, so
the gate stays accurate without double-counting.

These tests pin the contract:

1. Atomic-claim correctness under concurrency at the engine layer.
2. End-to-end: many concurrent ``_create_partial_fill_follow_up``
   calls produce at most ``max_order_replacement`` follow-up
   creations across the parent, regardless of carry availability.
"""
from __future__ import annotations

import threading
from unittest.mock import Mock

import pytest

from tests.unit.test_partial_fill_followups import (
    _build_engine_for_partial_fill_tests,
    _link_child_to_opted_in_parent,
)


# ---------------------------------------------------------------------------
# Engine-level: claim_replacement_slots atomicity
# ---------------------------------------------------------------------------


def _setup_parent(engine, parent_id, *, max_repl):
    engine.orderbook.parent_order_ids[parent_id] = {
        "allow_partial_fills": True,
        "orders": [],
        "target_movement": {"movement": 0.001, "type": "P"},
        "max_order_replacement": max_repl,
        "current_order_replacement": 0,
    }


@pytest.mark.regression
def test_claim_replacement_slots_caps_at_max():
    engine = _build_engine_for_partial_fill_tests()
    _setup_parent(engine, "p1", max_repl=3)

    assert engine.claim_replacement_slots("p1", 2) == 2
    assert engine.claim_replacement_slots("p1", 5) == 1   # only 1 left
    assert engine.claim_replacement_slots("p1", 10) == 0  # full


@pytest.mark.regression
def test_claim_replacement_slots_respects_existing_current():
    engine = _build_engine_for_partial_fill_tests()
    _setup_parent(engine, "p1", max_repl=5)
    engine.orderbook.parent_order_ids["p1"]["current_order_replacement"] = 3

    assert engine.claim_replacement_slots("p1", 10) == 2
    assert engine.claim_replacement_slots("p1", 1) == 0


@pytest.mark.regression
def test_release_replacement_slots_returns_capacity():
    engine = _build_engine_for_partial_fill_tests()
    _setup_parent(engine, "p1", max_repl=2)

    assert engine.claim_replacement_slots("p1", 2) == 2
    assert engine.claim_replacement_slots("p1", 1) == 0
    engine.release_replacement_slots("p1", 1)
    assert engine.claim_replacement_slots("p1", 5) == 1


@pytest.mark.regression
def test_register_child_order_consumes_pending_claim_no_double_count():
    """register_child_order must net-out the pending counter so the
    gate doesn't double-count the same slot once via pre-claim and
    again via the child registration."""
    engine = _build_engine_for_partial_fill_tests()
    _setup_parent(engine, "p1", max_repl=2)

    # Pre-claim 2 slots.
    assert engine.claim_replacement_slots("p1", 2) == 2

    # Mock the DB layer so register_child_order doesn't try to talk to PG.
    import database.order as dbo
    real_increment = dbo.increment_order_parent_replacement_count
    try:
        counts = {"calls": 0}
        def fake_increment(parent):
            counts["calls"] += 1
            return counts["calls"]
        dbo.increment_order_parent_replacement_count = fake_increment

        engine.register_child_order("c1", "p1")
        engine.register_child_order("c2", "p1")
    finally:
        dbo.increment_order_parent_replacement_count = real_increment

    parent = engine.orderbook.parent_order_ids["p1"]
    # current_order_replacement must equal exactly the number of
    # registered children (2), NOT 4 (which would be pre-claim 2 +
    # register 2 if the netting were missing).
    assert parent["current_order_replacement"] == 2
    # No pending claims left.
    assert engine._pending_replacement_claims.get("p1", 0) == 0
    # Cap is now full.
    assert engine.claim_replacement_slots("p1", 1) == 0


@pytest.mark.regression
def test_concurrent_claim_replacement_slots_never_exceeds_cap():
    """N threads racing to claim slots must collectively grant at
    most ``max_order_replacement`` slots — never one per thread.
    Pre-fix: every thread saw ``current=0`` snapshot and passed the
    can_create check, breaching the cap."""
    engine = _build_engine_for_partial_fill_tests()
    _setup_parent(engine, "p1", max_repl=1)

    n_threads = 16
    barrier = threading.Barrier(n_threads)
    granted = [0] * n_threads

    def worker(i):
        barrier.wait()
        granted[i] = engine.claim_replacement_slots("p1", 1)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    total = sum(granted)
    assert total == 1, (
        f"Concurrent claim_replacement_slots over-granted: {total} "
        f"slots awarded with max_order_replacement=1. Per-thread "
        f"grants: {granted}. This is the 2026-04-29 cap breach "
        f"regressing."
    )


# ---------------------------------------------------------------------------
# End-to-end: concurrent _create_partial_fill_follow_up vs cap
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_concurrent_partial_fill_follow_up_respects_replacement_cap():
    """Reproduces the production cap breach: with carry available
    for many follow-ups but ``max_order_replacement = 1``, N
    concurrent ``_create_partial_fill_follow_up`` calls must produce
    at most ONE follow-up creation, not N.

    Pre-fix (2026-04-29): four BUY follow-ups created against a
    parent whose cap was 1.
    """
    engine = _build_engine_for_partial_fill_tests()

    placed_coid = "race-coid-cap"
    parent_coid = "race-parent-cap"
    _link_child_to_opted_in_parent(engine, placed_coid, parent_coid)
    # Tighten the cap to 1 — the production scenario.
    engine.orderbook.parent_order_ids[parent_coid]["max_order_replacement"] = 1

    # Plenty of carry available — the cap, not the carry, must gate.
    engine.order_progress_tracker.hydrate([
        {
            "client_order_id": placed_coid,
            "parent_client_order_id": parent_coid,
            "product_id": "BIP-20DEC30-CDE",
            "side": "SELL",
            "original_order_size": 99.0,
            "min_order_size": 1.0,
            "carry_remainder_qty": 99.0,
            "partial_follow_ups_created": 0,
        }
    ])

    engine.resolve_parent_target_movement = Mock(
        return_value={"movement": 0.001, "type": "P"}
    )
    engine.compute_partial_fill_order_template = Mock(
        return_value={
            "start_price": "75635.0",
            "side": "BUY",
            "order_base_size": "1",
            "product_id": "BIP-20DEC30-CDE",
        }
    )

    stealth_manager = Mock()
    stealth_manager.find_stealth_order_by_placed_order_id.return_value = {
        "stealth_order_id": parent_coid,  # chain root == parent
        "parent_order_id": None,
        "reveal_condition_json": {"type": "price", "direction": "below"},
        "follow_up_reveal_direction": "opposite",
    }
    follow_up_ids = []
    follow_up_lock = threading.Lock()

    def _create_fu(**kwargs):
        with follow_up_lock:
            i = len(follow_up_ids)
            fu_id = f"stealth-follow-up-cap-{i}"
            follow_up_ids.append(fu_id)
            return fu_id

    stealth_manager.create_follow_up_stealth_order.side_effect = _create_fu
    engine.stealth_order_bridge = Mock(stealth_manager=stealth_manager)
    engine.db_helper.get_parent_order.return_value = {
        "target_movement": 0.001,
        "target_movement_type": "P",
    }
    # Stub register_child_order so we don't need a live DB. Still
    # consume the pending claim to keep the gate accurate.
    def fake_register(child, parent):
        with engine.orderbook_lock:
            pending = int(engine._pending_replacement_claims.get(parent, 0))
            if pending > 0:
                new_pending = pending - 1
                if new_pending == 0:
                    engine._pending_replacement_claims.pop(parent, None)
                else:
                    engine._pending_replacement_claims[parent] = new_pending
            engine.orderbook.parent_order_ids[parent]["current_order_replacement"] += 1
    engine.register_child_order = fake_register

    n_threads = 8
    barrier = threading.Barrier(n_threads)
    results = [None] * n_threads

    def worker(i):
        barrier.wait()
        results[i] = engine._create_partial_fill_follow_up(
            client_order_id=placed_coid,
            parent_client_order_id=parent_coid,
            min_order_size=1.0,
            follow_ups_due=99,
        )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Exactly ONE follow-up creation across all threads.
    assert len(follow_up_ids) == 1, (
        f"Replacement cap breached: {len(follow_up_ids)} follow-ups "
        f"created with max_order_replacement=1. Per-thread results: "
        f"{results}. This is the 2026-04-29 cap-breach bug regressing."
    )

    # Parent state reflects exactly one consumed slot, no leaked pending.
    parent = engine.orderbook.parent_order_ids[parent_coid]
    assert parent["current_order_replacement"] == 1
    assert engine._pending_replacement_claims.get(parent_coid, 0) == 0
