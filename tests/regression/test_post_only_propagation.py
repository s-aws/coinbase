"""Regression: ``post_only`` propagation across all profitability call sites.

Background (2026-05-01)
========================

The reveal-time profitability check was wired to derive ``post_only`` from
``RevealPricingPolicy``, but two sibling call sites were not:

1. ``StealthOrderManager._validate_anchor_reprice_profitability``
   (anchor reprice path) — silently used taker rate, over-rejecting
   TOP_OF_BOOK / MIDPOINT repricings.
2. ``OrderEngine`` follow-up creation pre-check — same bug for
   stealth follow-ups.

Root cause: the policy → ``post_only`` derivation rule was open-coded.
Fix: extract ``StealthOrderManager._resolve_post_only_from_policy`` and
route every site through it. This test file is the static guard that
prevents the duplication from creeping back.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_STEALTH_SRC = (_REPO_ROOT / "core" / "stealth_order_manager.py").read_text(
    encoding="utf-8"
)
_ENGINE_SRC = (_REPO_ROOT / "core" / "order_engine.py").read_text(encoding="utf-8")


def test_canonical_post_only_helper_exists():
    """Single source of truth helper must be defined on StealthOrderManager."""
    assert "def _resolve_post_only_from_policy(" in _STEALTH_SRC, (
        "Canonical helper _resolve_post_only_from_policy missing — "
        "do not re-inline post_only derivation at call sites."
    )
    # Helper must internally use implies_post_only (the enum-level rule).
    helper_match = re.search(
        r"def _resolve_post_only_from_policy\(.*?(?=\n    def )",
        _STEALTH_SRC,
        re.DOTALL,
    )
    assert helper_match is not None, "Helper body could not be located"
    assert "implies_post_only" in helper_match.group(0), (
        "Canonical helper must delegate to RevealPricingPolicy.implies_post_only()"
    )


def test_anchor_reprice_validator_passes_post_only():
    """Anchor-reprice profitability check must thread post_only."""
    fn_match = re.search(
        r"def _validate_anchor_reprice_profitability\(.*?(?=\n    def )",
        _STEALTH_SRC,
        re.DOTALL,
    )
    assert fn_match is not None, "_validate_anchor_reprice_profitability not found"
    body = fn_match.group(0)
    assert "_resolve_post_only_from_policy(" in body, (
        "Anchor-reprice path must derive post_only via canonical helper "
        "(was: silently passing taker rate, over-rejecting TOP_OF_BOOK reprices)."
    )
    assert "post_only=" in body, (
        "Anchor-reprice path must pass post_only= to validate_order_profitability"
    )


def test_pre_flight_feasibility_uses_canonical_helper():
    """Pre-flight feasibility must route through the canonical helper."""
    # The pre-flight method computes min-viable target movement; locate it
    # by the validate_order_profitability call site near
    # _compute_min_viable_target_movement.
    assert _STEALTH_SRC.count("_resolve_post_only_from_policy(") >= 2, (
        "Pre-flight feasibility was not refactored to the canonical helper "
        "(expect at least anchor-reprice + pre-flight call sites)."
    )


def test_no_inline_implies_post_only_outside_helper():
    """Static guard against duplicating the rule.

    ``implies_post_only`` should appear in: enum definition, the canonical
    helper, and ``build_reveal_execution_plan`` (which sets the field on
    the plan dataclass directly). Anywhere else is a duplication.
    """
    occurrences = [
        line for line in _STEALTH_SRC.splitlines()
        if "implies_post_only" in line
    ]
    # Allowed: helper body (1) + build_reveal_execution_plan (1).
    # If you add a new legitimate site, update this assertion AND prefer
    # the helper unless you're constructing a RevealExecutionPlan inline.
    assert len(occurrences) <= 3, (
        f"implies_post_only duplicated in {len(occurrences)} places — "
        f"prefer _resolve_post_only_from_policy(). Lines:\n"
        + "\n".join(occurrences)
    )


def test_order_engine_follow_up_threads_post_only():
    """Follow-up pre-check in order_engine must derive post_only from the
    parent stealth order's policy via the canonical helper."""
    # Locate the is_profitable call inside the follow-up creation block.
    pattern = re.compile(
        r"profit_validator\.is_profitable\((?P<args>.*?)\)",
        re.DOTALL,
    )
    matches = list(pattern.finditer(_ENGINE_SRC))
    assert matches, "is_profitable call not found in order_engine"
    # At least one call site must pass post_only.
    assert any("post_only" in m.group("args") for m in matches), (
        "order_engine follow-up pre-check must pass post_only= to "
        "is_profitable (was: silently using taker rate)."
    )
    # And it must derive via the canonical helper, not inline.
    assert "_resolve_post_only_from_policy(" in _ENGINE_SRC, (
        "order_engine must derive post_only via the canonical helper "
        "on the stealth manager — do not re-inline the rule here."
    )


def test_profitability_failure_warning_includes_post_only():
    """The production warning must surface post_only and policy so future
    incidents are diagnosable from logs alone."""
    # Find the warning emit block.
    block_match = re.search(
        r'"event":\s*"stealth_order_profitability_validation_failed".*?\}',
        _STEALTH_SRC,
        re.DOTALL,
    )
    assert block_match is not None, "warning emit block not found"
    body = block_match.group(0)
    assert '"post_only"' in body, (
        "Warning payload must include post_only for diagnosis"
    )
    assert '"reveal_pricing_policy"' in body, (
        "Warning payload must include reveal_pricing_policy for diagnosis"
    )
