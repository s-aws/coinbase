"""Regression: ``RepricingPolicy.compute_follow_up_price`` (post-fill
fingerprint-hiding RETREAT).

Pins the contract:

* Disabled policy AND enabled-but-explicit-zero-retreat both return
  ``anchor_price`` unchanged. Opt-OUT path (defaults are non-zero).
* Defaults are non-zero: every enabled policy that omits the retreat
  fields gets the documented opt-out behavior (5bps / 0.5 jitter).
* Non-zero retreat moves the follow-up AWAY from the anchor price:
  BUY -> lower, SELL -> higher. Never chases.
* Jitter is deterministic from the follow-up's ``client_order_id``
  (sha256-derived). Same coid + same anchor -> same follow-up price.
  Different coids -> different prices in the documented band.
* Jitter cannot flip retreat into chase even at the band's worst case
  (clamped to >= 0 in the helper).
* Always percent-based: same retreat fraction produces proportionally
  matching offsets at $50,000 and at $0.01.
* Helper does NOT tick-align (caller's job; pinned in the docstring,
  pinned by this test so callers stay aware).

Producer/consumer note: the storage layer
``StealthOrderManager._normalize_anchor_repricing_policy`` and the
on-disk JSONB shape both must keep ``follow_up_retreat_distance`` and
``follow_up_retreat_jitter``. ``test_repricing_policy.py``'s
round-trip test guards the on-disk shape; this file pins the runtime
behavior.
"""

from __future__ import annotations

import math

import pytest

from core.models import RepricingPolicy


def _enabled(**overrides) -> RepricingPolicy:
    """Build a minimally-enabled policy with retreat overrides.

    Pins ``follow_up_retreat_jitter=0`` by default so direction /
    magnitude tests are exact. Tests that exercise jitter override it
    explicitly.
    """
    base = {
        "enabled": True,
        "target_distance": 0.001,
        "max_distance": 0.005,
        "follow_up_retreat_jitter": 0.0,
    }
    base.update(overrides)
    return RepricingPolicy.from_dict(base)


# ---- opt-in / opt-out --------------------------------------------------------

def test_disabled_or_explicit_zero_is_no_op():
    """Disabled policy AND enabled-but-explicit-zero-retreat both return
    anchor_price unchanged. This is the documented opt-OUT path."""
    disabled = RepricingPolicy.disabled()
    assert disabled.compute_follow_up_price(
        anchor_price=100.0, side="BUY", follow_up_client_order_id="any"
    ) == 100.0

    zero_retreat = _enabled(follow_up_retreat_distance=0.0, follow_up_retreat_jitter=0.5)
    assert zero_retreat.compute_follow_up_price(
        anchor_price=100.0, side="BUY", follow_up_client_order_id="any"
    ) == 100.0


def test_defaults_are_opt_out_not_opt_in():
    """An enabled policy that omits retreat fields gets the non-zero
    defaults (5bps / 0.5 jitter). This is the opt-OUT design choice:
    every follow-up gets a small retreat unless explicitly disabled.

    Bypasses ``_enabled`` because that helper pins jitter=0 for the
    other tests; here we want to verify the from_dict default."""
    p = RepricingPolicy.from_dict({
        "enabled": True,
        "target_distance": 0.001,
        "max_distance": 0.005,
    })
    assert p.follow_up_retreat_distance == pytest.approx(0.0005)
    assert p.follow_up_retreat_jitter == pytest.approx(0.5)
    out = p.compute_follow_up_price(
        anchor_price=100.0, side="BUY", follow_up_client_order_id="coid-default"
    )
    # Effective retreat lands in [2.5bps, 7.5bps]; BUY moves DOWN.
    assert 99.925 <= out <= 99.975
    assert out != 100.0  # must not be a no-op


def test_disabled_policy_does_not_apply_retreat_even_with_default_distance():
    """A truly disabled policy (``enabled=False``) must NOT retreat,
    regardless of what dataclass defaults say. Otherwise users who
    explicitly disable anchor-repricing get surprise retreat behavior
    on follow-ups."""
    p = RepricingPolicy.disabled()
    # Sanity: dataclass defaults DO carry the opt-out values...
    assert p.follow_up_retreat_distance > 0
    # ...but the helper short-circuits on ``not self.enabled``.
    assert p.compute_follow_up_price(
        anchor_price=100.0, side="BUY", follow_up_client_order_id="x"
    ) == 100.0


# ---- direction (RETREAT, not chase) -----------------------------------------

def test_buy_retreat_posts_lower_than_anchor():
    p = _enabled(follow_up_retreat_distance=0.005)  # 50 bps
    out = p.compute_follow_up_price(
        anchor_price=100.0, side="BUY", follow_up_client_order_id="coid-1"
    )
    assert out == pytest.approx(99.5)


def test_sell_retreat_posts_higher_than_anchor():
    p = _enabled(follow_up_retreat_distance=0.005)
    out = p.compute_follow_up_price(
        anchor_price=100.0, side="SELL", follow_up_client_order_id="coid-1"
    )
    assert out == pytest.approx(100.5)


def test_unknown_side_treated_as_sell_side_retreat():
    """Defensive: if upstream hands us junk, retreat in the SELL
    direction (post higher) rather than crash. SELL is the safer
    default — never accidentally pays MORE than the fill (which would
    happen if BUY were the fallback)."""
    p = _enabled(follow_up_retreat_distance=0.005)
    out = p.compute_follow_up_price(
        anchor_price=100.0, side="", follow_up_client_order_id="coid-1"
    )
    assert out > 100.0


# ---- determinism / jitter ---------------------------------------------------

def test_same_coid_produces_same_price():
    """Determinism: replayable for audit. Same inputs -> same output."""
    p = _enabled(follow_up_retreat_distance=0.005, follow_up_retreat_jitter=0.4)
    a = p.compute_follow_up_price(
        anchor_price=100.0, side="BUY", follow_up_client_order_id="abc"
    )
    b = p.compute_follow_up_price(
        anchor_price=100.0, side="BUY", follow_up_client_order_id="abc"
    )
    assert a == b


def test_different_coids_produce_different_prices():
    """Spread the fingerprint across follow-ups; identical coids would
    re-create the same exact pattern and defeat the point."""
    p = _enabled(follow_up_retreat_distance=0.005, follow_up_retreat_jitter=0.4)
    prices = {
        p.compute_follow_up_price(
            anchor_price=100.0, side="BUY", follow_up_client_order_id=f"coid-{i}"
        )
        for i in range(20)
    }
    # 20 distinct coids should produce many distinct prices (sha256 is
    # ~uniform; we leave headroom for the rare collision so this stays
    # non-flaky).
    assert len(prices) >= 15


def test_jitter_stays_within_documented_band():
    """Effective retreat lands in [d * (1 - jitter), d * (1 + jitter)]."""
    distance = 0.005
    jitter = 0.4
    p = _enabled(follow_up_retreat_distance=distance, follow_up_retreat_jitter=jitter)

    fill = 100.0
    min_retreat = distance * (1 - jitter)  # 0.003
    max_retreat = distance * (1 + jitter)  # 0.007
    min_price_buy = fill - fill * max_retreat  # 99.30
    max_price_buy = fill - fill * min_retreat  # 99.70

    for i in range(50):
        out = p.compute_follow_up_price(
            anchor_price=fill, side="BUY", follow_up_client_order_id=f"coid-{i}"
        )
        assert min_price_buy <= out <= max_price_buy, (
            f"coid-{i}: {out} outside band [{min_price_buy}, {max_price_buy}]"
        )


def test_jitter_cannot_flip_retreat_into_chase():
    """Even at extreme jitter (clamped to 1.0 by from_dict), the
    BUY follow-up price must never EXCEED anchor_price (would be a chase),
    and the SELL follow-up must never go BELOW anchor_price."""
    p = _enabled(
        follow_up_retreat_distance=0.005,
        follow_up_retreat_jitter=10.0,  # will be clamped to 1.0
    )
    assert p.follow_up_retreat_jitter == 1.0  # clamp pinned

    for i in range(100):
        coid = f"coid-{i}"
        buy = p.compute_follow_up_price(
            anchor_price=100.0, side="BUY", follow_up_client_order_id=coid
        )
        sell = p.compute_follow_up_price(
            anchor_price=100.0, side="SELL", follow_up_client_order_id=coid
        )
        assert buy <= 100.0, f"BUY chased on coid {coid}: {buy} > 100"
        assert sell >= 100.0, f"SELL chased on coid {coid}: {sell} < 100"


# ---- scale-invariance -------------------------------------------------------

def test_percent_based_scales_across_price_magnitudes():
    """50bps retreat is 50bps whether the asset trades at $0.01 or $50,000.
    This is why the design picked PERCENT only (no ABSOLUTE knob)."""
    p = _enabled(follow_up_retreat_distance=0.005, follow_up_retreat_jitter=0.0)
    btc = p.compute_follow_up_price(
        anchor_price=50_000.0, side="BUY", follow_up_client_order_id="x"
    )
    micro = p.compute_follow_up_price(
        anchor_price=0.01, side="BUY", follow_up_client_order_id="x"
    )
    # Both retreat exactly 50 bps below their respective fill prices.
    assert btc == pytest.approx(50_000.0 * (1 - 0.005))
    assert micro == pytest.approx(0.01 * (1 - 0.005))


# ---- input clamping ---------------------------------------------------------

def test_negative_distance_clamped_to_zero():
    """Garbage in -> safe no-op out, NOT a chase."""
    p = _enabled(follow_up_retreat_distance=-0.5)
    assert p.follow_up_retreat_distance == 0.0
    assert p.compute_follow_up_price(
        anchor_price=100.0, side="BUY", follow_up_client_order_id="x"
    ) == 100.0


def test_jitter_clamped_to_unit_interval():
    p_neg = _enabled(follow_up_retreat_distance=0.005, follow_up_retreat_jitter=-0.5)
    assert p_neg.follow_up_retreat_jitter == 0.0
    p_huge = _enabled(follow_up_retreat_distance=0.005, follow_up_retreat_jitter=99.0)
    assert p_huge.follow_up_retreat_jitter == 1.0


# ---- explicit non-promise ---------------------------------------------------

def test_helper_does_not_tick_align():
    """The helper is a pricing primitive, not an order-placement helper.
    Tick alignment is the caller's responsibility (per the docstring).
    Pinned here so callers stay aware of the contract."""
    p = _enabled(follow_up_retreat_distance=0.005, follow_up_retreat_jitter=0.0)
    out = p.compute_follow_up_price(
        anchor_price=99.99, side="BUY", follow_up_client_order_id="x"
    )
    # 99.99 * (1 - 0.005) = 99.49005 -- not aligned to any common tick.
    # If the helper ever starts tick-aligning, this test will catch it
    # and the docstring + caller chain need updating together.
    assert not math.isclose(out, round(out, 2))
