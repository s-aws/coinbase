"""Regression: replacement-cap atomic claim + partial-fill bypass.

Two related contracts pinned here.

1. Atomic ``claim_replacement_slots`` (2026-04-29 incident)
   ----------------------------------------------------------
   ``can_create_follow_up_order`` was a read-only gate; concurrent
   threads each saw the same stale ``current_order_replacement``
   snapshot and breached the cap. Fix: ``claim_replacement_slots``
   atomically reserves a slot under ``orderbook_lock`` and accounts
   for in-flight pending claims. This API is still used by the
   cancel/full-fill follow-up path (``handle_filled_order``).

2. Partial-fill follow-ups bypass the cap (2026-04-30 incident)
   --------------------------------------------------------------
   With ``max_order_replacement = 1`` and ``allow_partial_fills =
   True``, a 10-unit SELL filled in 4 partials produced only 1 of 9
   needed BUY follow-ups: the cap, designed to limit *re-anchor*
   placements, also gated *completion* placements and stranded the
   operator with 9 un-hedged contracts. Fix: partial-fill follow-ups
   call ``register_child_order(..., bypass_replacement_cap=True)``
   and the cap is enforced only on the cancel/full-fill follow-up
   path. The carry budget (``claim_follow_up_units``) alone bounds
   the partial-fill spawn rate.
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
# End-to-end: partial-fill follow-ups must BYPASS the replacement cap
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_partial_fill_follow_up_bypasses_replacement_cap():
    """2026-04-30 incident: ``max_order_replacement = 1`` +
    ``allow_partial_fills = True`` left the operator with un-hedged
    exposure equal to the carry remainder. The cap exists for
    re-anchor placements (cancel / full-fill follow-ups), not for
    *completing* an existing partially-filled placement.

    Contract: with carry available for many follow-ups but
    ``max_order_replacement = 1`` (already exhausted by the
    original child), N concurrent
    ``_create_partial_fill_follow_up`` calls must collectively
    produce ``min(carry_units, follow_ups_due)`` follow-ups —
    NOT clamp at the replacement cap.
    """
    engine = _build_engine_for_partial_fill_tests()

    placed_coid = "race-coid-bypass"
    parent_coid = "race-parent-bypass"
    _link_child_to_opted_in_parent(engine, placed_coid, parent_coid)

    # Tighten the cap to 1 AND mark it already consumed by the
    # original child placement. This is the production scenario.
    engine.orderbook.parent_order_ids[parent_coid]["max_order_replacement"] = 1
    engine.orderbook.parent_order_ids[parent_coid]["current_order_replacement"] = 1

    # 9 carry units available — the carry, not the cap, must gate.
    engine.order_progress_tracker.hydrate([
        {
            "client_order_id": placed_coid,
            "parent_client_order_id": parent_coid,
            "product_id": "BIP-20DEC30-CDE",
            "side": "SELL",
            "original_order_size": 10.0,
            "min_order_size": 1.0,
            "carry_remainder_qty": 9.0,
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
        "stealth_order_id": parent_coid,
        "parent_order_id": None,
        "reveal_condition_json": {"type": "price", "direction": "below"},
        "follow_up_reveal_direction": "opposite",
    }
    follow_up_ids = []
    follow_up_lock = threading.Lock()

    def _create_fu(**kwargs):
        with follow_up_lock:
            i = len(follow_up_ids)
            fu_id = f"stealth-follow-up-bypass-{i}"
            follow_up_ids.append(fu_id)
            return fu_id

    stealth_manager.create_follow_up_stealth_order.side_effect = _create_fu
    engine.stealth_order_bridge = Mock(stealth_manager=stealth_manager)
    engine.db_helper.get_parent_order.return_value = {
        "target_movement": 0.001,
        "target_movement_type": "P",
    }

    # Stub register_child_order. The bypass kwarg MUST be honored:
    # current_order_replacement must NOT bump for partial-fill
    # follow-ups, otherwise this test trivially passes for the wrong
    # reason (the in-memory bump alone would gate concurrent threads).
    register_calls = []
    def fake_register(child, parent, bypass_replacement_cap=False):
        register_calls.append((child, parent, bypass_replacement_cap))
        # Honor the bypass contract: do not bump the counter.
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
            follow_ups_due=9,
        )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All 9 carry units consumed across the parent's chain, regardless
    # of how the work was sliced across the racing threads. The cap
    # must not have gated this even though it was already at max.
    total_units = sum(r for r in results if r is not None)
    assert total_units == 9, (
        f"Partial-fill follow-ups did not exhaust carry: only "
        f"{total_units} units consumed with 9 carry units available "
        f"and max_order_replacement=1 (already exhausted). "
        f"Per-thread results: {results}, follow-ups created: "
        f"{len(follow_up_ids)}. The cap is incorrectly gating "
        f"partial-fill completion placements again (2026-04-30 "
        f"stranded-exposure regression)."
    )
    # At least one follow-up was created (could be any number from 1
    # to 9 depending on thread interleaving — the atomic claim may
    # let one thread grab everything or N threads grab partial slices).
    assert len(follow_up_ids) >= 1

    # Every register call MUST be a bypass call.
    assert register_calls, "register_child_order was never called"
    assert all(call[2] is True for call in register_calls), (
        f"Partial-fill follow-up registered without "
        f"bypass_replacement_cap=True: {register_calls}. The bypass "
        f"contract is the entire point of the 2026-04-30 fix."
    )

    # Carry must be fully drained.
    record = engine.order_progress_tracker.get_record(placed_coid)
    assert float(record.carry_remainder_qty) == 0.0
