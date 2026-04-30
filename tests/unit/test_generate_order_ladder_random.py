"""Unit tests for ``genai_tools.generate_order_ladder`` random expansion."""
from __future__ import annotations

import random

import pytest

from genai_tools.generate_order_ladder import (
    _expand_per_rung_tokens,
    _expand_random_tokens,
    _has_per_rung_token,
    _parse_number,
    build_ladder,
)


def test_expand_random_tokens_replaces_single_token_within_range():
    rng = random.Random(42)
    out = _expand_random_tokens("-r(15)", rng)
    # Strip sign for range check.
    body = out.lstrip("+-")
    n = int(body)
    assert 0 <= n <= 15
    # Sign is preserved.
    assert out.startswith("-")


def test_expand_random_tokens_with_seed_is_reproducible():
    a = _expand_random_tokens("-r(15)", random.Random(123))
    b = _expand_random_tokens("-r(15)", random.Random(123))
    assert a == b


def test_expand_random_tokens_replaces_every_occurrence_independently():
    # Two tokens, same seed → both rolls deterministic, can differ.
    rng = random.Random(7)
    out = _expand_random_tokens("r(100)+r(100)", rng)
    # Just sanity: arithmetic-looking literal of two ints (or one int + ints).
    # No leftover r( token may remain.
    assert "r(" not in out


def test_expand_random_tokens_no_token_passthrough():
    assert _expand_random_tokens("-15", random.Random(0)) == "-15"
    assert _expand_random_tokens("+50", random.Random(0)) == "+50"
    assert _expand_random_tokens("0.5", random.Random(0)) == "0.5"


def test_expand_random_tokens_zero_upper_bound_returns_zero():
    out = _expand_random_tokens("r(0)", random.Random(0))
    assert out == "0"
    out = _expand_random_tokens("-r(0)", random.Random(0))
    assert out == "-0"


def test_expand_random_tokens_negative_upper_bound_rejected():
    with pytest.raises(ValueError):
        _expand_random_tokens("r(-5)", random.Random(0))


def test_expanded_output_parses_as_delta_when_signed():
    """End-to-end: ``-r(15)`` → expanded → parsed as a per-step delta."""
    expanded = _expand_random_tokens("-r(15)", random.Random(99))
    value, is_delta = _parse_number(expanded)
    assert is_delta is True
    assert -15.0 <= value <= 0.0


def test_expanded_output_parses_as_absolute_when_unsigned():
    expanded = _expand_random_tokens("r(15)", random.Random(99))
    value, is_delta = _parse_number(expanded)
    assert is_delta is False
    assert 0.0 <= value <= 15.0


# ---------------------------------------------------------------------------
# Per-rung jitter (rr(N))
# ---------------------------------------------------------------------------


def test_one_shot_regex_does_not_match_rr_tokens():
    """``r(N)`` substitution must leave ``rr(N)`` alone — they are
    different operators with different semantics. If the negative-
    lookbehind on the regex regresses, ``rr(15)`` would silently
    become ``r<rolled>)`` which is a malformed string."""
    rng = random.Random(0)
    out = _expand_random_tokens("rr(15)", rng)
    assert out == "rr(15)"


def test_has_per_rung_token_detects_rr_only():
    assert _has_per_rung_token("rr(5)") is True
    assert _has_per_rung_token("-rr(5)") is True
    assert _has_per_rung_token("r(5)") is False
    assert _has_per_rung_token("-15") is False


def test_expand_per_rung_tokens_replaces_independently_each_call():
    raw = "rr(100)"
    rng = random.Random(0)
    samples = [_expand_per_rung_tokens(raw, rng) for _ in range(50)]
    # Cardinality test: with 50 draws over [0,100], we expect at
    # least 5 distinct values. (Failing this would mean a stuck rng.)
    distinct = {int(s) for s in samples}
    assert len(distinct) >= 5
    for s in samples:
        n = int(s)
        assert 0 <= n <= 100


def test_build_ladder_per_rung_jitter_produces_distinct_rung_values():
    """End-to-end: a 10-rung ladder with ``-rr(50)`` jitter on
    ``limit_price`` must produce per-rung noise within the documented
    bound (NOT multiplied by the rung index — that would be a delta,
    not jitter)."""
    template = {"limit_price": 76000}
    rng = random.Random(123)
    rungs = build_ladder(
        template,
        count=10,
        deltas={},
        rung_jitter={"limit_price": (["limit_price"], "-rr(50)")},
        rng=rng,
    )
    prices = [r["limit_price"] for r in rungs]
    # Pure jitter contract: every rung is base + sign * jitter_i where
    # jitter_i ∈ [0, 50]. So all prices in [75950, 76000].
    assert all(75950 <= p <= 76000 for p in prices), prices
    # And there must be at least 3 distinct values across 10 rungs.
    assert len(set(prices)) >= 3, (
        f"Per-rung jitter produced suspiciously few distinct values: {prices}"
    )


def test_build_ladder_jitter_stacks_on_top_of_static_delta():
    """A static delta and per-rung jitter on the same key compose:
    the rung's deterministic value comes from the delta, then jitter
    is added on top as small noise. This is the typical use-case
    (laddered prices with small randomized offsets)."""
    template = {"limit_price": 76000}
    # Drift down 10 per rung, jitter ± 5 (here always subtract 0..5).
    rungs = build_ladder(
        template,
        count=5,
        deltas={"limit_price": (["limit_price"], -10.0, True)},
        rung_jitter={"limit_price": (["limit_price"], "-rr(5)")},
        rng=random.Random(0),
    )
    prices = [r["limit_price"] for r in rungs]
    # Rung i: drifted = 76000 - 10*i ∈ {76000, 75990, 75980, 75970, 75960}
    # Jittered: drifted - jitter_i where jitter_i ∈ [0,5]
    # So bounds per rung: [76000-10*i - 5, 76000-10*i].
    for i, p in enumerate(prices):
        upper = 76000 - 10 * i
        lower = upper - 5
        assert lower <= p <= upper, (
            f"rung {i}: price {p} outside [{lower}, {upper}]"
        )


def test_build_ladder_requires_rng_when_jitter_present():
    template = {"limit_price": 76000}
    with pytest.raises(ValueError, match="rng is required"):
        build_ladder(
            template, 3, {},
            rung_jitter={"limit_price": (["limit_price"], "+rr(5)")},
            rng=None,
        )


def test_build_ladder_jitter_seed_is_reproducible():
    template = {"limit_price": 76000}
    a = build_ladder(
        template, 5, {},
        rung_jitter={"limit_price": (["limit_price"], "-rr(50)")},
        rng=random.Random(42),
    )
    b = build_ladder(
        template, 5, {},
        rung_jitter={"limit_price": (["limit_price"], "-rr(50)")},
        rng=random.Random(42),
    )
    assert [r["limit_price"] for r in a] == [r["limit_price"] for r in b]
