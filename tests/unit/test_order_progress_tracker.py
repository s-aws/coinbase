"""Unit tests for ``business.order_progress.OrderProgressTracker``.

Pure-logic tests — no DB. Persistence integration is covered in step 4.
"""

import threading
from math import isclose

import pytest

from business.order_progress import OrderProgressTracker, OrderSnapshotDelta
from core.enums import OrderStatus


def _evt(**overrides):
    """Build a normalized WS order dict with sensible defaults."""
    base = {
        "client_order_id": "coid-1",
        "product_id": "BIP-20DEC30-CDE",
        "order_side": "SELL",
        "status": OrderStatus.OPEN.value,
        "cumulative_quantity": "0",
        "filled_value": "0",
        "total_fees": "0",
        "number_of_fills": 0,
        "leaves_quantity": "5",
        "completion_percentage": "0",
        "outstanding_hold_amount": "0",
        "avg_price": "78000",
        "limit_price": "78000",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Identity / replay / cold-start
# ---------------------------------------------------------------------------


def test_ingest_first_event_with_no_fills_returns_none():
    """A snapshot before any fill (cumulative=0, status=OPEN) is not actionable."""
    tracker = OrderProgressTracker()
    delta = tracker.ingest(_evt())
    assert delta is None


def test_ingest_first_real_match_returns_delta_with_full_size():
    tracker = OrderProgressTracker()
    delta = tracker.ingest(_evt(
        cumulative_quantity="1.0",
        filled_value="78000",
        total_fees="0.228",
        number_of_fills=1,
        leaves_quantity="4",
        completion_percentage="20",
    ))
    assert isinstance(delta, OrderSnapshotDelta)
    assert delta.is_new_match
    assert isclose(delta.size_delta, 1.0)
    assert isclose(delta.derived_price, 78000.0)
    assert isclose(delta.fee_delta, 0.228, abs_tol=1e-9)
    assert delta.snapshot_seq == 1


def test_ingest_replay_of_same_snapshot_returns_none():
    tracker = OrderProgressTracker()
    evt = _evt(cumulative_quantity="1.0", filled_value="78000", total_fees="0.228",
               number_of_fills=1, leaves_quantity="4", completion_percentage="20")
    first = tracker.ingest(evt)
    second = tracker.ingest(evt)
    assert first is not None
    assert second is None


def test_ingest_two_matches_yields_two_deltas_with_correct_decomposition():
    """The f2986f57 production scenario: 1.0 then 5.0 must produce 1.0 + 4.0."""
    tracker = OrderProgressTracker()
    d1 = tracker.ingest(_evt(
        cumulative_quantity="1.0", filled_value="78000", total_fees="0.228",
        number_of_fills=1, leaves_quantity="4", completion_percentage="20",
    ))
    d2 = tracker.ingest(_evt(
        cumulative_quantity="5.0", filled_value="390000", total_fees="1.14",
        number_of_fills=2, leaves_quantity="0", completion_percentage="100",
        status=OrderStatus.FILLED.value, outstanding_hold_amount="0",
    ))

    assert d1.is_new_match and d2.is_new_match
    assert isclose(d1.size_delta, 1.0)
    assert isclose(d2.size_delta, 4.0)
    assert isclose(d1.fee_delta + d2.fee_delta, 1.14, abs_tol=1e-9)
    assert isclose(d1.derived_price, 78000.0)
    assert isclose(d2.derived_price, 78000.0)
    # Distinct deterministic dedup keys.
    assert d1.derived_trade_key != d2.derived_trade_key
    assert d1.snapshot_seq == 1 and d2.snapshot_seq == 2


# ---------------------------------------------------------------------------
# Terminal handling
# ---------------------------------------------------------------------------


def test_terminal_status_without_counter_advance_emits_delta_for_audit():
    """Hold-clear FILLED replays must produce a non-match delta so the engine
    sees ``is_terminal`` and finalizes state. The delta carries no new size."""
    tracker = OrderProgressTracker()
    tracker.ingest(_evt(cumulative_quantity="5.0", filled_value="390000",
                        total_fees="1.14", number_of_fills=2, leaves_quantity="0"))
    terminal = tracker.ingest(_evt(
        cumulative_quantity="5.0", filled_value="390000", total_fees="1.14",
        number_of_fills=2, leaves_quantity="0",
        status=OrderStatus.FILLED.value, outstanding_hold_amount="0",
    ))
    assert terminal is not None
    assert not terminal.is_new_match
    assert terminal.is_terminal


def test_finalize_drops_state_and_lock():
    tracker = OrderProgressTracker()
    tracker.ingest(_evt(cumulative_quantity="1.0", filled_value="78000",
                        total_fees="0.228", number_of_fills=1, leaves_quantity="4"))
    assert tracker.get_record("coid-1") is not None
    tracker.finalize("coid-1", terminal_status="FILLED")
    assert tracker.get_record("coid-1") is None
    # Internal lock map must be cleared too.
    assert "coid-1" not in tracker._order_locks


# ---------------------------------------------------------------------------
# Carry math (partial-fill follow-ups)
# ---------------------------------------------------------------------------


def test_consume_carry_units_subtracts_min_order_size():
    tracker = OrderProgressTracker(min_order_size_resolver=lambda _pid: 1.0)
    tracker.ingest(_evt(cumulative_quantity="3.0", filled_value="234000",
                        total_fees="0.6", number_of_fills=1, leaves_quantity="2"))
    record_before = tracker.get_record("coid-1")
    assert isclose(record_before.carry_remainder_qty, 3.0)
    assert record_before.min_order_size == 1.0

    tracker.consume_carry_units("coid-1", units=2)

    record_after = tracker.get_record("coid-1")
    assert isclose(record_after.carry_remainder_qty, 1.0)
    assert record_after.partial_follow_ups_created == 2


def test_consume_carry_units_clamps_at_zero():
    tracker = OrderProgressTracker(min_order_size_resolver=lambda _pid: 1.0)
    tracker.ingest(_evt(cumulative_quantity="1.0", filled_value="78000",
                        total_fees="0.2", number_of_fills=1, leaves_quantity="4"))
    tracker.consume_carry_units("coid-1", units=99)
    record = tracker.get_record("coid-1")
    assert record.carry_remainder_qty == 0.0


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


def test_concurrent_ingest_of_same_snapshot_yields_exactly_one_delta():
    """Two threads racing on identical snapshots must produce one delta total —
    the second thread sees the watermark already advanced."""
    tracker = OrderProgressTracker()
    evt = _evt(cumulative_quantity="2.0", filled_value="156000",
               total_fees="0.5", number_of_fills=1, leaves_quantity="3")
    barrier = threading.Barrier(2)
    results = []

    def _worker():
        barrier.wait()
        results.append(tracker.ingest(evt))

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    non_none = [r for r in results if r is not None]
    assert len(non_none) == 1
    assert isclose(non_none[0].size_delta, 2.0)


# ---------------------------------------------------------------------------
# Hydration
# ---------------------------------------------------------------------------


def test_hydrate_restores_records_for_active_orders():
    tracker = OrderProgressTracker()
    rows = [{
        "client_order_id": "coid-X",
        "parent_client_order_id": "parent-X",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "original_order_size": "1.0",
        "min_order_size": "0.01",
        "last_cumulative_qty_processed": "0.5",
        "carry_remainder_qty": "0.0",
        "last_number_of_fills_seen": 3,
        "last_completion_pct_seen": "50",
        "partial_follow_ups_created": 5,
    }]
    tracker.hydrate(rows)
    record = tracker.get_record("coid-X")
    assert record is not None
    assert isclose(record.last_cumulative_qty_processed, 0.5)
    assert record.partial_follow_ups_created == 5

    # After hydration, an event at the same cumulative must be a no-op.
    assert tracker.ingest(_evt(
        client_order_id="coid-X", product_id="BTC-USDC", order_side="BUY",
        cumulative_quantity="0.5", number_of_fills=3, completion_percentage="50",
        leaves_quantity="0.5",
    )) is None
