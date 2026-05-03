"""Unit tests for the RevealStrategy interface and concrete strategies.

Pure size-computation tests; no DB, no manager wiring. The
manager-integration regression lives in
``tests/regression/test_tranche_iceberg_pacing.py``.
"""
from __future__ import annotations

import pytest

from business.stealth_reveal_strategy import (
    AdaptiveRevealStrategy,
    FixedRevealStrategy,
    TrancheRevealStrategy,
    get_reveal_strategy,
)


# ---------------------------------------------------------------------------
# Fixed
# ---------------------------------------------------------------------------


def _order(**overrides):
    base = {
        "stealth_order_id": "sid-1",
        "product_id": "BIP-20DEC30-CDE",
        "side": "SELL",
        "total_size": 10.0,
        "revealed_size": 0.0,
        "executed_size": 0.0,
        "remaining_size": 10.0,
        "anchor_repricing_state_json": {},
    }
    base.update(overrides)
    return base


def test_fixed_returns_total_on_first_call():
    s = FixedRevealStrategy()
    assert s.next_slice_size(_order()) == 10.0


def test_fixed_returns_zero_after_reveal():
    s = FixedRevealStrategy()
    assert s.next_slice_size(_order(revealed_size=10.0)) == 0.0


def test_fixed_returns_zero_for_zero_total():
    s = FixedRevealStrategy()
    assert s.next_slice_size(_order(total_size=0.0)) == 0.0


# ---------------------------------------------------------------------------
# Adaptive
# ---------------------------------------------------------------------------


def _adaptive(**cfg):
    return AdaptiveRevealStrategy(
        config=cfg,
        market_volume_provider=lambda product, window: 1000.0,
        baseline_volume_provider=lambda product: 1000.0,
    )


def test_adaptive_basic_proportional():
    s = _adaptive(reveal_multiplier=0.1, max_reveal_percentage=0.5)
    # base_size defaults to total_size (10), volume_ratio=1.0,
    # multiplier=0.1 -> 1.0
    assert s.next_slice_size(_order()) == pytest.approx(1.0)


def test_adaptive_capped_by_max_pct():
    s = _adaptive(reveal_multiplier=10.0, max_reveal_percentage=0.3)
    # Uncapped would be 10*1*10 = 100; capped at 30% of total=3.0.
    assert s.next_slice_size(_order()) == pytest.approx(3.0)


def test_adaptive_capped_by_remaining():
    s = _adaptive(reveal_multiplier=10.0, max_reveal_percentage=1.0)
    # Capped uncapped=100 -> max(10) -> remaining (set low).
    assert s.next_slice_size(_order(remaining_size=2.0)) == 2.0


def test_adaptive_zero_when_remaining_zero():
    s = _adaptive()
    assert s.next_slice_size(_order(remaining_size=0.0)) == 0.0


# ---------------------------------------------------------------------------
# Tranche - iceberg mode (default)
# ---------------------------------------------------------------------------


def _iceberg(**cfg):
    cfg.setdefault("tranches", [0.25, 0.50, 0.75, 1.0])
    return TrancheRevealStrategy(cfg)


def test_iceberg_first_slice_uses_first_tranche():
    s = _iceberg()
    assert s.next_slice_size(_order()) == pytest.approx(2.5)


def test_iceberg_locked_when_active_placement_exists():
    """The core 2026-05-03 fix: while a placement is live, return 0."""
    s = _iceberg()
    o = _order()
    o["anchor_repricing_state_json"] = {
        "active_placement_client_order_id": "live-coid"
    }
    assert s.next_slice_size(o) == 0.0


def test_iceberg_advances_to_next_tranche_after_full_fill():
    """After tranche 1 fills, next call posts tranche 2's slice."""
    s = _iceberg()
    o = _order(revealed_size=2.5, executed_size=2.5)
    # active pointer cleared (set by update_execution on EXECUTED).
    assert s.next_slice_size(o) == pytest.approx(2.5)


def test_iceberg_partial_fill_then_external_cancel_fills_gap():
    """Cumulative semantics (option a from the design review).

    Scenario: tranche 1 posted at 2.5, exchange filled 1.8, then was
    cancelled externally (clears active pointer). Next slice should
    be sized to refill the gap up to the current cumulative target,
    NOT to advance to the next tranche.
    """
    s = _iceberg()
    o = _order(revealed_size=2.5, executed_size=1.8)
    # First uncrossed cumulative target from executed=1.8 is 2.5.
    assert s.next_slice_size(o) == pytest.approx(2.5 - 1.8)


def test_iceberg_partial_fill_past_first_tranche():
    """Executed has crossed tranche 1; next slice fills toward tranche 2."""
    s = _iceberg()
    o = _order(revealed_size=2.5, executed_size=2.6)
    # First uncrossed target from executed=2.6 is 5.0.
    assert s.next_slice_size(o) == pytest.approx(5.0 - 2.6)


def test_iceberg_returns_zero_when_all_tranches_filled():
    s = _iceberg()
    o = _order(revealed_size=10.0, executed_size=10.0)
    assert s.next_slice_size(o) == 0.0


def test_iceberg_default_is_true():
    """Iceberg mode must default to True even with no explicit config.

    Burst behavior was the 2026-05-03 bug; making it the default would
    perpetuate it.
    """
    s = TrancheRevealStrategy({})  # NO iceberg_mode key
    o = _order()
    o["anchor_repricing_state_json"] = {
        "active_placement_client_order_id": "live-coid"
    }
    assert s.next_slice_size(o) == 0.0, (
        "Iceberg mode must default to True. Burst behavior is a bug, "
        "not a feature; see 2026-05-03 incident."
    )


# ---------------------------------------------------------------------------
# Tranche - burst mode (backward compat)
# ---------------------------------------------------------------------------


def test_burst_mode_ignores_active_placement():
    s = TrancheRevealStrategy({"iceberg_mode": False})
    o = _order()
    o["anchor_repricing_state_json"] = {
        "active_placement_client_order_id": "live-coid"
    }
    # Burst mode does NOT lock; first tranche still fires.
    assert s.next_slice_size(o) == pytest.approx(2.5)


def test_burst_mode_advances_via_revealed_size():
    """Burst mode preserves pre-2026-05-03 behavior: gates on
    revealed_size, not executed_size, so consecutive calls march
    through the schedule even with zero fills."""
    s = TrancheRevealStrategy({"iceberg_mode": False})
    # After 1st post: revealed=2.5, executed still=0 -> next slice
    # for tranche 2 = 5.0 - 2.5 = 2.5.
    assert s.next_slice_size(
        _order(revealed_size=2.5, executed_size=0.0)
    ) == pytest.approx(2.5)
    # After 4th post: revealed=10 -> 0.
    assert s.next_slice_size(
        _order(revealed_size=10.0, executed_size=0.0)
    ) == 0.0


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_factory_dispatches_correctly():
    assert isinstance(get_reveal_strategy("fixed", {}), FixedRevealStrategy)
    assert isinstance(
        get_reveal_strategy(
            "adaptive",
            {},
            market_volume_provider=lambda *_: 0.0,
            baseline_volume_provider=lambda *_: 1.0,
        ),
        AdaptiveRevealStrategy,
    )
    assert isinstance(get_reveal_strategy("tranche", {}), TrancheRevealStrategy)


def test_factory_unknown_falls_back_to_fixed():
    assert isinstance(
        get_reveal_strategy("nonexistent", {}), FixedRevealStrategy
    )


def test_factory_none_falls_back_to_fixed():
    assert isinstance(get_reveal_strategy(None, {}), FixedRevealStrategy)


def test_factory_adaptive_requires_providers():
    with pytest.raises(ValueError, match="market_volume_provider"):
        get_reveal_strategy("adaptive", {})
