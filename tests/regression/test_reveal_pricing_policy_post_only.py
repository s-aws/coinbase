"""Regression: ``RevealPricingPolicy.implies_post_only`` is the single
source of truth for the policy → ``post_only`` mapping.

Background (2026-05-01)
========================

Before the maker/taker split, the reveal submission path hard-coded
``post_only=False`` for every reveal regardless of policy. That made
TOP_OF_BOOK and MIDPOINT reveals pay the taker fee tier even when the
operator's intent was clearly to rest as a maker.

Contract under test:

1. ``TOP_OF_BOOK`` and ``MIDPOINT`` imply ``post_only=True``.
2. ``CONFIGURED_LIMIT`` implies ``post_only=False`` (the caller has
   taken explicit price responsibility and may want to cross).
3. The ``RevealExecutionPlan`` dataclass carries a ``post_only`` field
   so the build-time decision survives all the way to submission.
4. The reveal submission dict in ``stealth_order_manager.py`` reads
   ``post_only`` from the plan (no longer hard-coded).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.enums import RevealPricingPolicy
from core.models import RevealExecutionPlan


_STEALTH_MANAGER_SRC = (
    Path(__file__).resolve().parents[2]
    / "core"
    / "stealth_order_manager.py"
).read_text(encoding="utf-8")


_MODELS_SRC = (
    Path(__file__).resolve().parents[2]
    / "core"
    / "models.py"
).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Static-source guards
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_reveal_execution_plan_has_post_only_field():
    """``RevealExecutionPlan`` must persist ``post_only`` so the
    build-time decision survives to the submission site."""
    assert "post_only" in _MODELS_SRC
    # Sanity: the field must show up in to_dict() so audit logs see it.
    assert "'post_only'" in _MODELS_SRC


@pytest.mark.regression
def test_submission_dict_reads_post_only_from_plan_not_hardcoded():
    """The reveal submission dict must NOT hard-code ``post_only=False``.
    A grep for the previous bug pattern should return zero hits."""
    # Allow the True/False literals to appear elsewhere; what's banned
    # is the specific hard-coded reveal submission line.
    bad_pattern = '"post_only": False  # Match'
    assert bad_pattern not in _STEALTH_MANAGER_SRC
    # And the new pattern must appear.
    assert 'reveal_plan' in _STEALTH_MANAGER_SRC
    assert 'post_only' in _STEALTH_MANAGER_SRC


# ---------------------------------------------------------------------------
# Behavioural tests
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_top_of_book_implies_post_only():
    assert RevealPricingPolicy.TOP_OF_BOOK.implies_post_only() is True


@pytest.mark.regression
def test_midpoint_implies_post_only():
    assert RevealPricingPolicy.MIDPOINT.implies_post_only() is True


@pytest.mark.regression
def test_configured_limit_does_not_imply_post_only():
    assert RevealPricingPolicy.CONFIGURED_LIMIT.implies_post_only() is False


@pytest.mark.regression
def test_reveal_execution_plan_post_only_default_false():
    """``post_only`` must default to ``False`` so any code that builds
    a plan without thinking about post_only stays safe (taker)."""
    plan = RevealExecutionPlan(
        configured_limit_price=100.0,
        submitted_limit_price=100.0,
        reveal_pricing_policy="configured_limit",
        reveal_price_source="configured_limit",
        fallback_used=False,
    )
    assert plan.post_only is False


@pytest.mark.regression
def test_reveal_execution_plan_post_only_round_trips_through_to_dict():
    plan = RevealExecutionPlan(
        configured_limit_price=100.0,
        submitted_limit_price=99.5,
        reveal_pricing_policy="top_of_book",
        reveal_price_source="ticker_best_ask",
        fallback_used=False,
        post_only=True,
    )
    payload = plan.to_dict()
    assert payload.get("post_only") is True
