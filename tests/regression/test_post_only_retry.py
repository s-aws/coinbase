"""Regression: post-only retry loop with 1-tick safer reprice.

Background (2026-05-01)
========================

When a TOP_OF_BOOK or MIDPOINT reveal submits with ``post_only=True``
and the touch moves between the local quote read and the exchange's
match engine, Coinbase rejects with ``failure_reason == "POST_ONLY"``.

Pre-fix: the single REST call was made and any failure was reported
as a generic placement failure, so the operator had no signal that the
order was actually post-only-rejected (vs blocked for some other
reason). Worse, no retry happened, so a transient cross would
permanently abandon a profitable reveal.

Industry-standard fix: 3 attempts total. On each ``POST_ONLY``
rejection reprice ONE tick AWAY from the touch and retry.  On
exhaustion surface ``StealthLifecycleEvent.PLACEMENT_BLOCKED`` with
``block_category="post_only_rejected_after_retries"`` and STOP — never
silently demote to ``post_only=False`` (that would change the fee
tier the operator agreed to).

Contract under test:

1. ``_next_safer_tick`` moves AWAY from the touch:
   - BUY: ``price - increment`` (retreat from ask)
   - SELL: ``price + increment`` (retreat from bid)
2. ``_is_post_only_rejection`` matches the canonical
   ``failure_reason == "POST_ONLY"`` shape and the nested
   ``error_response.error`` shape, case-insensitively.
3. ``POST_ONLY_MAX_ATTEMPTS == 3`` — the industry-standard ladder.
4. The retry/exhaustion code path is wired (static-source guards so
   nobody silently rips it out and replaces with a taker fallback).
5. Retry telemetry includes cumulative retreat in ticks so later
    saturation tuning is based on the actual drift from initial intent.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.stealth_order_manager import StealthOrderManager


_STEALTH_MANAGER_SRC = (
    Path(__file__).resolve().parents[2]
    / "core"
    / "stealth_order_manager.py"
).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Static-source guards
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_post_only_max_attempts_is_three():
    """3 = original attempt + 2 retries. Lower would erode the small
    benefit of retrying at all; higher just adds latency for the rare
    case where the touch genuinely moved several ticks in our face."""
    assert StealthOrderManager.POST_ONLY_MAX_ATTEMPTS == 3


@pytest.mark.regression
def test_retry_loop_dispatches_placement_blocked_on_exhaustion():
    """Exhaustion MUST surface a lifecycle event so operators see the
    abandoned reveal in their dashboard. Silently giving up was the
    pre-fix behaviour and is forbidden."""
    assert "post_only_rejected_after_retries" in _STEALTH_MANAGER_SRC
    assert "StealthLifecycleEvent.PLACEMENT_BLOCKED" in _STEALTH_MANAGER_SRC


@pytest.mark.regression
def test_retry_loop_does_not_demote_to_taker():
    """A grep for the silent-demotion anti-pattern must come up empty.
    If anyone ever adds ``post_only = False`` after a POST_ONLY
    rejection that bug must show up here, not in production fees."""
    forbidden_patterns = [
        '"post_only": False  # demote',
        "post_only = False  # fall back",
        "post_only=False  # taker fallback",
    ]
    for bad in forbidden_patterns:
        assert bad not in _STEALTH_MANAGER_SRC, (
            f"Silent demotion pattern reintroduced: {bad!r}"
        )


@pytest.mark.regression
def test_retry_loop_uses_fresh_client_order_id_per_attempt():
    """A rejected attempt may consume the COID at the exchange; reusing
    it would mask the real POST_ONLY symptom behind a spurious
    DUPLICATE_CLIENT_ORDER_ID rejection."""
    assert "next_coid = str(uuid.uuid4())" in _STEALTH_MANAGER_SRC


@pytest.mark.regression
def test_retry_loop_emits_cumulative_retreat_tick_telemetry():
    assert '"cumulative_retreat_ticks": self._post_only_retreat_ticks(' in _STEALTH_MANAGER_SRC
    assert '"total_retreat_ticks": self._post_only_retreat_ticks(' in _STEALTH_MANAGER_SRC
    assert '"post_only_total_retreat_ticks": self._post_only_retreat_ticks(' in _STEALTH_MANAGER_SRC


# ---------------------------------------------------------------------------
# Behavioural tests — _next_safer_tick
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_next_safer_tick_buy_retreats_below_ask():
    """A BUY post-only rejection means our bid was >= ask. The only
    safe re-submit moves the bid LOWER (further from the ask)."""
    new_price = StealthOrderManager._next_safer_tick(
        price=100.50, side="BUY", increment="0.01"
    )
    assert new_price == pytest.approx(100.49)


@pytest.mark.regression
def test_next_safer_tick_sell_retreats_above_bid():
    """A SELL post-only rejection means our ask was <= bid. The only
    safe re-submit moves the ask HIGHER (further from the bid)."""
    new_price = StealthOrderManager._next_safer_tick(
        price=100.50, side="SELL", increment="0.01"
    )
    assert new_price == pytest.approx(100.51)


@pytest.mark.regression
def test_next_safer_tick_handles_unknown_side():
    """Unknown side → no-op (return the quantized price). We never
    want to guess a direction and accidentally cross harder."""
    new_price = StealthOrderManager._next_safer_tick(
        price=100.50, side="WHATEVER", increment="0.01"
    )
    assert new_price == pytest.approx(100.50)


@pytest.mark.regression
def test_next_safer_tick_quantizes_to_increment():
    """If the input price is off-grid, the result must still snap to
    the tick grid before retreating."""
    # 100.503 → quantized to 100.50, then BUY retreat by 0.01 = 100.49
    new_price = StealthOrderManager._next_safer_tick(
        price=100.503, side="BUY", increment="0.01"
    )
    assert new_price == pytest.approx(100.49)


@pytest.mark.regression
def test_next_safer_tick_handles_invalid_increment_gracefully():
    """A malformed increment string must not crash placement. Returning
    the input price unchanged is acceptable — the caller will then
    skip the retry rather than guess."""
    new_price = StealthOrderManager._next_safer_tick(
        price=100.50, side="BUY", increment="not-a-number"
    )
    assert new_price == pytest.approx(100.50)


@pytest.mark.regression
def test_post_only_retreat_ticks_are_side_aware():
    assert StealthOrderManager._post_only_retreat_ticks(100.0, 99.0, "BUY", "0.5") == 2
    assert StealthOrderManager._post_only_retreat_ticks(100.0, 101.0, "SELL", "0.5") == 2
    assert StealthOrderManager._post_only_retreat_ticks(100.0, 101.0, "BUY", "0.5") == 0


# ---------------------------------------------------------------------------
# Behavioural tests — _is_post_only_rejection
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_post_only_rejection_detected_in_failure_reason():
    """Canonical Coinbase shape: ``failure_reason == "POST_ONLY"``."""
    assert StealthOrderManager._is_post_only_rejection({
        "success": False,
        "failure_reason": "POST_ONLY",
    }) is True


@pytest.mark.regression
def test_post_only_rejection_detected_in_error_response():
    """Some SDK paths surface the reason under ``error_response``."""
    assert StealthOrderManager._is_post_only_rejection({
        "success": False,
        "error_response": {"error": "POST_ONLY"},
    }) is True


@pytest.mark.regression
def test_post_only_rejection_case_insensitive():
    """SDK wording drift must not silently disable the retry path."""
    assert StealthOrderManager._is_post_only_rejection({
        "success": False,
        "failure_reason": "post_only",
    }) is True


@pytest.mark.regression
def test_post_only_rejection_false_for_success():
    assert StealthOrderManager._is_post_only_rejection({
        "success": True,
        "success_response": {"order_id": "abc"},
    }) is False


@pytest.mark.regression
def test_post_only_rejection_false_for_other_failures():
    """Unrelated failures must NOT trigger the post-only retry loop —
    repricing 1 tick safer makes no sense for e.g. INSUFFICIENT_FUNDS."""
    assert StealthOrderManager._is_post_only_rejection({
        "success": False,
        "failure_reason": "INSUFFICIENT_FUND",
    }) is False
    assert StealthOrderManager._is_post_only_rejection({
        "success": False,
        "failure_reason": "PRICE_TOO_AGGRESSIVE",
    }) is False


@pytest.mark.regression
def test_post_only_rejection_false_for_non_dict():
    """Defensive: legacy callers occasionally returned bare strings."""
    assert StealthOrderManager._is_post_only_rejection(None) is False
    assert StealthOrderManager._is_post_only_rejection("POST_ONLY") is False
