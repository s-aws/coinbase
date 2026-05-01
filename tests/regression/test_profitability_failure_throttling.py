"""Regression: profitability-validation failures must be log-throttled
and must include actionable diagnostics.

Background (2026-04-30 incident)
=================================

A FUTURE stealth order (BIT-29MAY26-CDE SELL 10 contracts,
target_movement=0.001/P) entered a state where every reveal attempt
produced exactly the same projected loss (\u2248 -$1.49). The mandatory
$0.15/contract close fee was structurally above the configured target,
so the math could never clear regardless of where the slide moved the
limit price.

The stealth bridge polls reveal candidacy at ~10 Hz. Without throttling,
the WARN line ``stealth_order_profitability_validation_failed`` was
emitted ~10 times/second indefinitely \u2014 a stuck order produced ~36k
identical log lines per hour and drowned every other event.

Two changes guard against repeat:

1. **Cooldown.** The WARN is rate-limited to ~once per
   ``_PROFIT_FAILURE_LOG_COOLDOWN_SECONDS`` per unique
   (submitted_price, target_movement, target_movement_type) signature.
   Suppressed retries are counted and surfaced on the next emitted
   record so nothing is silently dropped.

2. **Actionable diagnostic.** The exception message now reports
   ``gross``, ``fees`` (split into ``pct`` + ``mandatory``), and a
   computed ``minimum viable`` target_movement so the operator can
   diagnose the configuration trap without re-deriving the math.
"""
from __future__ import annotations

from pathlib import Path

import pytest


_SRC = (
    Path(__file__).resolve().parents[2]
    / "core"
    / "stealth_order_manager.py"
).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Static-source guards (defense against silent regression in future commits)
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_profit_failure_cooldown_constant_exists():
    """The cooldown window must be a named constant so operators can
    audit/tune it without reading control flow."""
    assert "_PROFIT_FAILURE_LOG_COOLDOWN_SECONDS" in _SRC, (
        "Cooldown constant removed \u2014 reveal validation failures will "
        "spam the log at the bridge's poll rate (~10 Hz). See "
        "2026-04-30 incident in this file's docstring."
    )


@pytest.mark.regression
def test_should_emit_helper_exists_and_keys_are_underscore_prefixed():
    """The helper that gates emission MUST exist, and the state it
    stashes on the order dict MUST use the underscore-prefix
    convention so the persistence layer doesn't accidentally write it."""
    assert "_should_emit_profitability_failure" in _SRC, (
        "Throttle helper missing; cooldown will not engage."
    )
    for key in (
        "_profit_failure_signature",
        "_profit_failure_last_log_at",
        "_profit_failure_suppressed_since_last_log",
    ):
        assert key in _SRC, (
            f"Expected transient state key {key!r} missing; cooldown "
            "state must be stashed on the in-memory order dict."
        )


@pytest.mark.regression
def test_min_viable_target_movement_is_computed_for_diagnostic():
    """The diagnostic must compute and surface a minimum-viable
    target_movement so the operator gets the actionable answer in one
    log line rather than having to re-derive it."""
    assert "_compute_min_viable_target_movement" in _SRC, (
        "Min-viable diagnostic helper missing; operators will be left "
        "to reverse-engineer the fee math from raw numbers."
    )
    assert "minimum viable" in _SRC, (
        "Diagnostic message no longer surfaces the minimum-viable "
        "value; the WARN reverts to a number-only failure that hides "
        "the configuration trap."
    )


@pytest.mark.regression
def test_suppressed_repeats_count_is_emitted_with_log():
    """Cooldown must NOT silently drop information \u2014 the count of
    suppressed retries since the last emitted log MUST be included in
    the next emitted record."""
    assert "suppressed_repeats" in _SRC, (
        "Suppression counter not surfaced; operators will see one log "
        "line every cooldown window with no indication that hundreds "
        "of retries happened in between."
    )


# ---------------------------------------------------------------------------
# Behavioral tests
# ---------------------------------------------------------------------------


def _make_manager_with_helper():
    """Build a minimally-stubbed ``StealthOrderManager`` instance whose
    only responsibility for these tests is to expose the throttle
    helper. Avoids spinning up the full DB / orderbook stack."""
    from core import stealth_order_manager as som

    mgr = som.StealthOrderManager.__new__(som.StealthOrderManager)
    # Helper reads ``self.profit_validator`` only inside the min-viable
    # path; the throttle path doesn't touch it. Stub to None for both.
    mgr.profit_validator = None
    return mgr


class _StubPlan:
    """Minimal RevealExecutionPlan stand-in for the helper's needs."""
    def __init__(self, price: float, target: float, target_type: str = "P"):
        self.submitted_limit_price = price
        self.target_movement = target
        self.target_movement_type = target_type


@pytest.mark.regression
def test_first_failure_emits_subsequent_identical_failures_suppressed(monkeypatch):
    """The first call with a given signature returns True (emit). The
    second call within the cooldown with the SAME signature returns
    False (suppress) and bumps the suppressed-count."""
    from core import stealth_order_manager as som

    mgr = _make_manager_with_helper()
    order: dict = {}
    plan = _StubPlan(price=76802.5, target=0.001, target_type="P")

    monkeypatch.setattr(som.time, "monotonic", lambda: 1_000.0)
    assert mgr._should_emit_profitability_failure("sid-1", order, plan) is True
    assert order.get("_profit_failure_suppressed_since_last_log") == 0

    # Same signature, 1 second later (well inside cooldown) \u2014 suppress.
    monkeypatch.setattr(som.time, "monotonic", lambda: 1_001.0)
    assert mgr._should_emit_profitability_failure("sid-1", order, plan) is False
    assert order["_profit_failure_suppressed_since_last_log"] == 1

    # Two more suppressed calls bump the counter.
    assert mgr._should_emit_profitability_failure("sid-1", order, plan) is False
    assert mgr._should_emit_profitability_failure("sid-1", order, plan) is False
    assert order["_profit_failure_suppressed_since_last_log"] == 3


@pytest.mark.regression
def test_signature_change_re_emits_immediately(monkeypatch):
    """When the slide moves the limit price (or the target changes),
    the signature flips and the new failure must emit immediately
    rather than be suppressed under the previous signature's cooldown."""
    from core import stealth_order_manager as som

    mgr = _make_manager_with_helper()
    order: dict = {}

    monkeypatch.setattr(som.time, "monotonic", lambda: 1_000.0)
    assert mgr._should_emit_profitability_failure(
        "sid-1", order, _StubPlan(price=76802.5, target=0.001),
    ) is True

    # Same time, different price \u2014 must emit (signature changed).
    assert mgr._should_emit_profitability_failure(
        "sid-1", order, _StubPlan(price=76805.0, target=0.001),
    ) is True
    # Counter resets on emit.
    assert order["_profit_failure_suppressed_since_last_log"] == 0


@pytest.mark.regression
def test_emission_resumes_after_cooldown_expires(monkeypatch):
    """Once the cooldown window passes, the same signature must emit
    again so operators get periodic confirmation that the situation
    is still stuck."""
    from core import stealth_order_manager as som

    mgr = _make_manager_with_helper()
    order: dict = {}
    plan = _StubPlan(price=76802.5, target=0.001)

    monkeypatch.setattr(som.time, "monotonic", lambda: 1_000.0)
    assert mgr._should_emit_profitability_failure("sid-1", order, plan) is True

    # 30s in \u2014 still suppressed.
    monkeypatch.setattr(som.time, "monotonic", lambda: 1_030.0)
    assert mgr._should_emit_profitability_failure("sid-1", order, plan) is False

    # Just past cooldown (60s) \u2014 must emit again.
    monkeypatch.setattr(som.time, "monotonic", lambda: 1_061.0)
    assert mgr._should_emit_profitability_failure("sid-1", order, plan) is True


@pytest.mark.regression
def test_min_viable_target_percentage_recovers_break_even():
    """For percentage targets, the helper must report a value such
    that ``move_pct * filled_price * effective_size \u2248 total_fees``."""
    mgr = _make_manager_with_helper()
    # 76802.5 * 10 = 768025 notional. Fees of $9.17 \u2192 viable target \u2248
    # 9.17 / 768025 \u2248 0.0000119 (P).
    out = mgr._compute_min_viable_target_movement(
        parent_filled_price=76802.5,
        order_size=10.0,
        target_movement_type="P",
        total_fees=9.17,
        product_id="BIT-29MAY26-CDE",
    )
    assert out is not None
    expected = 9.17 / (76802.5 * 10.0)
    assert abs(out - expected) < 1e-12


@pytest.mark.regression
def test_min_viable_target_absolute_recovers_break_even():
    """For absolute targets, viable = total_fees / effective_size."""
    mgr = _make_manager_with_helper()
    out = mgr._compute_min_viable_target_movement(
        parent_filled_price=76802.5,
        order_size=10.0,
        target_movement_type="A",
        total_fees=9.17,
        product_id="BIT-29MAY26-CDE",
    )
    assert out is not None
    assert abs(out - (9.17 / 10.0)) < 1e-12


@pytest.mark.regression
def test_min_viable_returns_none_on_invalid_inputs():
    """The diagnostic helper is best-effort; it must return None
    rather than raise when inputs are unusable."""
    mgr = _make_manager_with_helper()
    assert mgr._compute_min_viable_target_movement(
        parent_filled_price=0.0, order_size=10.0,
        target_movement_type="P", total_fees=9.17,
        product_id="BIT-29MAY26-CDE",
    ) is None
    assert mgr._compute_min_viable_target_movement(
        parent_filled_price=76802.5, order_size=0.0,
        target_movement_type="P", total_fees=9.17,
        product_id="BIT-29MAY26-CDE",
    ) is None
    assert mgr._compute_min_viable_target_movement(
        parent_filled_price=76802.5, order_size=10.0,
        target_movement_type="P", total_fees=0.0,
        product_id="BIT-29MAY26-CDE",
    ) is None
