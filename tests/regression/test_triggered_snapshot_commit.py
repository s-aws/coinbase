"""Regression: TRIGGERED stealth orders must commit on the next bridge tick.

Background (2026-05-03 incident)
=================================

Stealth 4b6d2185 (SELL 10 BIP-20DEC30-CDE @ 78190, condition: price
above 78190 with 1s hold) was created at 04:43:41. At 04:45:51 the
ticker briefly touched 78195 (single last-trade tick on a 40-point
spread). The 1-second hold elapsed and at 04:45:52 the lifecycle
flipped CONDITION_MET / status TRIGGERED.

No placement followed. The ticker dropped back below 78190 within
seconds and every subsequent bridge tick called
``should_trigger_reveal`` -> ``evaluate_conditions`` -> live
``PriceThresholdEvaluator`` which returned ``(False, None)``. The
bridge's False branch is silent (no log, no lifecycle event), so the
order sat in TRIGGERED indefinitely with no audit trail.

This was a snapshot-vs-continuous semantics bug: the
``hold_duration_seconds`` gate exists specifically to filter ticker
noise. Re-running the same noise filter on every subsequent tick
defeats its purpose. Once TRIGGERED, the bridge must commit.

Fix: ``should_trigger_reveal`` short-circuits to ``(True, ...)`` when
status == TRIGGERED, bypassing live re-evaluation. Status is the
single source of truth for "condition has fired" \u2014 the evaluator
runs only to drive HIDDEN -> PENDING -> TRIGGERED transitions.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.enums import StealthOrderStatus
from core.stealth_order_manager import StealthOrderManager


_SRC = (
    Path(__file__).resolve().parents[2]
    / "core"
    / "stealth_order_manager.py"
).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Static-source guard (defense against silent regression)
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_should_trigger_reveal_has_triggered_short_circuit():
    """``should_trigger_reveal`` must short-circuit on TRIGGERED status
    BEFORE calling ``evaluate_conditions``. If a future refactor moves
    the evaluator call above the status check, the snapshot-commit
    contract is broken and TRIGGERED stealth orders can be silently
    stranded when the live condition de-asserts."""
    src = _SRC

    # Locate the should_trigger_reveal method body.
    marker = "def should_trigger_reveal(self, stealth_order_id: str)"
    idx = src.find(marker)
    assert idx != -1, "should_trigger_reveal definition missing"

    # Pull a generous body slice (next ~80 lines).
    body = src[idx : idx + 4000]

    # The TRIGGERED short-circuit must appear before the evaluator call.
    triggered_check_pos = body.find("StealthOrderStatus.TRIGGERED.value")
    evaluator_call_pos = body.find("self.evaluate_conditions(")
    assert triggered_check_pos != -1, (
        "TRIGGERED short-circuit removed from should_trigger_reveal. "
        "See 2026-05-03 incident in this file's docstring."
    )
    assert evaluator_call_pos != -1, "evaluate_conditions call missing"
    assert triggered_check_pos < evaluator_call_pos, (
        "TRIGGERED short-circuit must run BEFORE evaluate_conditions. "
        "Re-running the live condition on a TRIGGERED order silently "
        "strands placements when the triggering tick ages out."
    )


# ---------------------------------------------------------------------------
# Behavioral test
# ---------------------------------------------------------------------------


def _make_manager_with_triggered_order(condition_now_false: bool):
    """Build a StealthOrderManager with one TRIGGERED order whose live
    condition currently evaluates to ``not condition_now_false``."""
    mgr = StealthOrderManager.__new__(StealthOrderManager)
    mgr.in_memory_orders = {
        "sid-1": {
            "stealth_order_id": "sid-1",
            "product_id": "BIP-20DEC30-CDE",
            "side": "SELL",
            "total_size": 10.0,
            "remaining_size": 10.0,
            "limit_price": 78190.0,
            "status": StealthOrderStatus.TRIGGERED.value,
            "reveal_condition_type": "price",
            "reveal_condition_json": {
                "type": "price",
                "direction": "above",
                "price_threshold": 78190,
                "hold_duration_seconds": 1,
            },
            "condition_first_met_at": None,
            "condition_confirmed_at": None,
        }
    }
    mgr.db_client = None
    mgr.log_callback = MagicMock()
    # Market price contradicts the original trigger so a live
    # re-evaluation would return False.
    mgr._market_cache = {
        "BIP-20DEC30-CDE": {
            "product_id": "BIP-20DEC30-CDE",
            "price": 78180.0 if condition_now_false else 78200.0,
            "bid": 78155.0,
            "ask": 78195.0,
            "volume_1m": 0.0,
            "source": "ticker",
        }
    }
    return mgr


@pytest.mark.regression
def test_triggered_order_commits_even_when_live_condition_false():
    """Core invariant: a TRIGGERED stealth must report should_reveal=True
    even when the live evaluator would now return False. This is the
    exact 2026-05-03 stranded-order scenario."""
    mgr = _make_manager_with_triggered_order(condition_now_false=True)
    should_reveal, reason = mgr.should_trigger_reveal("sid-1")
    assert should_reveal is True, (
        f"TRIGGERED order failed to commit (reason={reason!r}). "
        "Snapshot-commit contract broken \u2014 see incident docstring."
    )
    assert reason and "snapshot" in reason.lower(), (
        f"Snapshot-commit reason missing or unclear: {reason!r}"
    )


@pytest.mark.regression
def test_terminal_status_still_blocks_reveal():
    """Snapshot-commit must not override EXECUTED/CANCELLED."""
    for terminal in (
        StealthOrderStatus.EXECUTED.value,
        StealthOrderStatus.CANCELLED.value,
    ):
        mgr = _make_manager_with_triggered_order(condition_now_false=True)
        mgr.in_memory_orders["sid-1"]["status"] = terminal
        should_reveal, reason = mgr.should_trigger_reveal("sid-1")
        assert should_reveal is False, (
            f"Terminal status {terminal} must block reveal "
            f"(got should_reveal=True, reason={reason!r})"
        )


@pytest.mark.regression
def test_remaining_size_zero_blocks_reveal_even_if_triggered():
    """remaining_size <= 0 takes precedence over snapshot commit so a
    fully-revealed order doesn't loop placing zero-size slices."""
    mgr = _make_manager_with_triggered_order(condition_now_false=False)
    mgr.in_memory_orders["sid-1"]["remaining_size"] = 0.0
    should_reveal, reason = mgr.should_trigger_reveal("sid-1")
    assert should_reveal is False
    assert "revealed" in (reason or "").lower()


@pytest.mark.regression
def test_hidden_order_still_runs_live_evaluation():
    """Status HIDDEN must continue to run the evaluator \u2014 the snapshot
    short-circuit applies only after the condition has fired."""
    mgr = _make_manager_with_triggered_order(condition_now_false=True)
    mgr.in_memory_orders["sid-1"]["status"] = StealthOrderStatus.HIDDEN.value
    should_reveal, reason = mgr.should_trigger_reveal("sid-1")
    # Live price (78180) is below threshold (78190) with direction=above
    # so the evaluator should return False.
    assert should_reveal is False
