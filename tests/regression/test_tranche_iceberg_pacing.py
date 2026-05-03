"""Regression: tranche stealth orders must not burst-post slices.

Background (2026-05-03 incident)
=================================

After the snapshot-commit fix to ``should_trigger_reveal``, a tranche
stealth (SELL 10 BIP-20DEC30-CDE, tranches=[0.25,0.50,0.75,1.0])
posted all 4 slices within 1.2 seconds. The bridge polls at ~10 Hz;
the original ``_calculate_tranche_reveal_size`` had no pacing -- on
each tick it advanced ``revealed_size`` and returned the next slice,
so the bridge fired four placements back-to-back.

Same product, same MPID, same price, four near-simultaneous orders
of identical size. That is a trivial fingerprint for any
counterparty watching the tape -- the entire point of slicing
defeated.

Fix: ``TrancheRevealStrategy`` defaults to iceberg mode (one live
slice at a time), gated on the same
``anchor_repricing_state_json.active_placement_client_order_id``
SSOT used by the anchor reprice flow. ``iceberg_mode=False`` opt-out
preserves the old burst behaviour for callers that genuinely want
N visible orders.

A throttled INFO log (``stealth_reveal_no_slice``) fires at most
once per 30s per stealth when ``_calculate_reveal_size`` returns 0,
so an iceberg-locked stealth never silently no-ops at the bridge
poll rate (the same observability gap that stranded the 4b6d2185
order).
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.stealth_order_manager import StealthOrderManager


_STRATEGY_SRC = (
    Path(__file__).resolve().parents[2]
    / "business"
    / "stealth_reveal_strategy.py"
).read_text(encoding="utf-8")

_MANAGER_SRC = (
    Path(__file__).resolve().parents[2]
    / "core"
    / "stealth_order_manager.py"
).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Static-source guards
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_iceberg_mode_defaults_to_true():
    """``TrancheRevealStrategy`` must default ``iceberg_mode=True``.

    Burst behaviour is the 2026-05-03 bug. Flipping the default would
    silently re-enable it for every tranche order.
    """
    src = _STRATEGY_SRC
    # The default lives in the constructor; check the literal.
    assert 'cfg.get("iceberg_mode", True)' in src, (
        "TrancheRevealStrategy default for iceberg_mode must be True. "
        "See 2026-05-03 incident in this file's docstring."
    )


@pytest.mark.regression
def test_manager_size_calc_delegates_to_strategy():
    """``_calculate_reveal_size`` must dispatch to RevealStrategy.

    No inline ``if strategy_type == 'tranche'`` branching may remain
    in the manager -- that was the duplicated-rule shape that let the
    bug live in two places.
    """
    src = _MANAGER_SRC
    # The dead methods must be gone (not just unused).
    assert "_calculate_tranche_reveal_size" not in src, (
        "Stale tranche size method still in manager. "
        "Remove to avoid duplicated-rule drift."
    )
    assert "_calculate_adaptive_reveal_size" not in src, (
        "Stale adaptive size method still in manager. "
        "Remove to avoid duplicated-rule drift."
    )
    # The delegation import must be present.
    assert "from business.stealth_reveal_strategy import get_reveal_strategy" in src, (
        "Manager must delegate _calculate_reveal_size via get_reveal_strategy."
    )


@pytest.mark.regression
def test_no_slice_log_helper_present():
    """The throttled diagnostic must remain wired into the no-slice path."""
    src = _MANAGER_SRC
    assert "_maybe_log_no_slice" in src, (
        "Throttled no-slice diagnostic helper missing. "
        "Without it, an iceberg-locked stealth silently no-ops at "
        "the bridge poll rate -- same observability gap as 2026-05-03."
    )
    assert "stealth_reveal_no_slice" in src, (
        "stealth_reveal_no_slice event name missing. "
        "Operators / log scrapers depend on this stable event name."
    )


# ---------------------------------------------------------------------------
# Behavioural tests against the manager
# ---------------------------------------------------------------------------


def _bare_manager():
    """A StealthOrderManager built without DB or hooks for size-calc tests."""
    mgr = StealthOrderManager.__new__(StealthOrderManager)
    mgr.db_client = None
    mgr.log_callback = MagicMock()
    mgr._no_slice_log_emitted_at = {}
    mgr.in_memory_orders = {}
    mgr._market_cache = {}
    return mgr


def _tranche_order(**overrides):
    o = {
        "stealth_order_id": "sid-iceberg-1",
        "product_id": "BIP-20DEC30-CDE",
        "side": "SELL",
        "status": "TRIGGERED",
        "total_size": 10.0,
        "revealed_size": 0.0,
        "executed_size": 0.0,
        "remaining_size": 10.0,
        "anchor_repricing_state_json": {},
        "sizing_strategy_json": {
            "type": "tranche",
            "tranches": [0.25, 0.50, 0.75, 1.0],
        },
    }
    o.update(overrides)
    return o


@pytest.mark.regression
def test_tranche_default_locks_after_first_slice():
    """Default tranche config must lock once a placement is live.

    This is the direct behavioural regression for the 2026-05-03 burst.
    """
    mgr = _bare_manager()

    # Pre-placement: first call returns the first tranche slice.
    o = _tranche_order()
    first = mgr._calculate_reveal_size(o)
    assert first == pytest.approx(2.5)

    # Post-placement (active pointer set, no fill yet): lock.
    o["revealed_size"] = 2.5
    o["anchor_repricing_state_json"] = {
        "active_placement_client_order_id": "live-coid-1"
    }
    second = mgr._calculate_reveal_size(o)
    assert second == 0.0, (
        "Iceberg lock failed: tranche strategy returned a second slice "
        "while a placement is still live. This is the 2026-05-03 burst."
    )


@pytest.mark.regression
def test_tranche_lock_releases_when_active_pointer_cleared():
    """Once update_execution clears the active pointer, the next slice
    is allowed to post."""
    mgr = _bare_manager()
    o = _tranche_order(
        revealed_size=2.5,
        executed_size=2.5,
        anchor_repricing_state_json={},  # cleared by update_execution
    )
    assert mgr._calculate_reveal_size(o) == pytest.approx(2.5)


@pytest.mark.regression
def test_burst_mode_opt_out_preserves_pre_fix_behavior():
    """``iceberg_mode=False`` must reproduce the pre-fix burst path
    so any caller that explicitly opts in still works."""
    mgr = _bare_manager()
    o = _tranche_order()
    o["sizing_strategy_json"]["iceberg_mode"] = False
    # Active placement is irrelevant in burst mode.
    o["anchor_repricing_state_json"] = {
        "active_placement_client_order_id": "live-coid-1"
    }
    o["revealed_size"] = 2.5
    assert mgr._calculate_reveal_size(o) == pytest.approx(2.5)


@pytest.mark.regression
def test_no_slice_log_throttled_to_once_per_window():
    """Repeated no-slice calls must not produce one log per call.

    The bridge polls at ~10 Hz; without throttling an iceberg-locked
    stealth would emit ~10 lines/sec for the duration of the lock.
    """
    mgr = _bare_manager()
    order = _tranche_order()
    order["anchor_repricing_state_json"] = {
        "active_placement_client_order_id": "live-coid"
    }

    # First call: emits.
    mgr._maybe_log_no_slice("sid-iceberg-1", order)
    # Subsequent rapid calls: throttled.
    for _ in range(20):
        mgr._maybe_log_no_slice("sid-iceberg-1", order)

    info_calls = [
        c
        for c in mgr.log_callback.call_args_list
        if c.args and c.args[0] == "info"
    ]
    assert len(info_calls) == 1, (
        f"Throttle broken: emitted {len(info_calls)} no-slice lines "
        "instead of 1. At 10 Hz bridge polling this is a log-flood bug."
    )

    payload = info_calls[0].args[1]
    assert payload["event"] == "stealth_reveal_no_slice"
    assert payload["stealth_order_id"] == "sid-iceberg-1"
    assert payload["active_placement_client_order_id"] == "live-coid"


@pytest.mark.regression
def test_no_slice_log_emits_again_after_cooldown():
    """After the cooldown window passes, the next no-slice call must
    emit -- otherwise a long-lived lock would be invisible."""
    mgr = _bare_manager()
    order = _tranche_order()
    order["anchor_repricing_state_json"] = {
        "active_placement_client_order_id": "live-coid"
    }

    mgr._maybe_log_no_slice("sid-iceberg-1", order)
    # Manually rewind the timestamp past the cooldown.
    cooldown = StealthOrderManager._NO_SLICE_LOG_COOLDOWN_SECONDS
    mgr._no_slice_log_emitted_at["sid-iceberg-1"] = time.time() - cooldown - 1
    mgr._maybe_log_no_slice("sid-iceberg-1", order)

    info_calls = [
        c
        for c in mgr.log_callback.call_args_list
        if c.args and c.args[0] == "info"
    ]
    assert len(info_calls) == 2, (
        f"Cooldown reset failed: expected 2 emits across cooldown, "
        f"got {len(info_calls)}."
    )


@pytest.mark.regression
def test_partial_fill_external_cancel_fills_gap_not_next_tranche():
    """Cumulative semantics: if tranche 1 partial-fills and is then
    cancelled externally, the next slice fills the gap (not the next
    tranche). Operator chose option (a) in the 2026-05-03 review."""
    mgr = _bare_manager()
    o = _tranche_order(
        revealed_size=2.5,
        executed_size=1.8,
        anchor_repricing_state_json={},  # cleared after external cancel
    )
    slice_size = mgr._calculate_reveal_size(o)
    assert slice_size == pytest.approx(2.5 - 1.8), (
        f"Cumulative gap-fill broken: expected 0.7, got {slice_size}. "
        "Strategy must gate on executed_size in iceberg mode so a "
        "partial-fill-then-cancel rolls forward to refill, not skip."
    )
