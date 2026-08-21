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
exhaustion surfaces ``StealthLifecycleEvent.REVEAL_FAILED`` and terminal
``StealthOrderStatus.ERROR`` and STOPS — never
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
def test_retry_loop_records_terminal_failure_on_exhaustion():
    """Exhaustion must use the shared terminal failure path."""
    assert "stealth_order_post_only_retries_exhausted" in _STEALTH_MANAGER_SRC
    assert "_record_terminal_placement_failure" in _STEALTH_MANAGER_SRC
    assert "StealthLifecycleEvent.REVEAL_FAILED" in _STEALTH_MANAGER_SRC


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


# ---------------------------------------------------------------------------
# Behavioural tests — _next_safer_tick
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_next_safer_tick_buy_retreats_below_ask(monkeypatch):
    """A BUY post-only rejection means our bid was >= ask. The only
    safe re-submit moves the bid LOWER (further from the ask)."""
    from configuration import PRODUCT_METADATA
    monkeypatch.setitem(PRODUCT_METADATA, "TEST-USD", {"price_increment": "0.01"})
    new_price = StealthOrderManager._next_safer_tick(
        price=100.50, side="BUY", product_id="TEST-USD"
    )
    assert new_price == pytest.approx(100.49)


@pytest.mark.regression
def test_next_safer_tick_sell_retreats_above_bid(monkeypatch):
    """A SELL post-only rejection means our ask was <= bid. The only
    safe re-submit moves the ask HIGHER (further from the bid)."""
    from configuration import PRODUCT_METADATA
    monkeypatch.setitem(PRODUCT_METADATA, "TEST-USD", {"price_increment": "0.01"})
    new_price = StealthOrderManager._next_safer_tick(
        price=100.50, side="SELL", product_id="TEST-USD"
    )
    assert new_price == pytest.approx(100.51)


@pytest.mark.regression
def test_next_safer_tick_rejects_unknown_side(monkeypatch):
    """Unknown side must fail closed instead of guessing a direction."""
    from configuration import PRODUCT_METADATA
    monkeypatch.setitem(PRODUCT_METADATA, "TEST-USD", {"price_increment": "0.01"})
    with pytest.raises(ValueError, match="unsupported order side"):
        StealthOrderManager._next_safer_tick(
            price=100.50, side="WHATEVER", product_id="TEST-USD"
        )


@pytest.mark.regression
def test_next_safer_tick_quantizes_to_increment(monkeypatch):
    """If the input price is off-grid, the result must still snap to
    the tick grid before retreating."""
    # 100.503 → quantized to 100.50, then BUY retreat by 0.01 = 100.49
    from configuration import PRODUCT_METADATA
    monkeypatch.setitem(PRODUCT_METADATA, "TEST-USD", {"price_increment": "0.01"})
    new_price = StealthOrderManager._next_safer_tick(
        price=100.503, side="BUY", product_id="TEST-USD"
    )
    assert new_price == pytest.approx(100.49)


@pytest.mark.regression
def test_next_safer_tick_rejects_invalid_increment(monkeypatch):
    """Malformed metadata must fail closed rather than return a raw price."""
    from configuration import PRODUCT_METADATA
    monkeypatch.setitem(
        PRODUCT_METADATA,
        "TEST-USD",
        {"price_increment": "not-a-number"},
    )
    with pytest.raises(ValueError, match="invalid price_increment"):
        StealthOrderManager._next_safer_tick(
            price=100.50, side="BUY", product_id="TEST-USD"
        )


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
def test_post_only_rejection_detected_in_scalar_error_response():
    """A scalar SDK error envelope must not raise after classification."""
    assert StealthOrderManager._is_post_only_rejection({
        "success": False,
        "error_response": "POST_ONLY",
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
