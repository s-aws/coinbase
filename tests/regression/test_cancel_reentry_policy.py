from datetime import datetime, timedelta

import pytest

from business.cancel_reentry_policy import (
    CancelReentryPolicy,
    CancelReentryRuntimeState,
    compute_distance,
    evaluate_cancel_reentry,
)
from core.enums import CancelReentryDecision, CancelReentryState


def _policy(**overrides):
    data = {
        "enabled": True,
        "reference_price_source": "midpoint",
        "distance_type": "A",
        "cancel_distance": 8,
        "reentry_distance": 9,
        "cooldown_seconds": 0,
        "max_reentry_count": 0,
    }
    data.update(overrides)
    return CancelReentryPolicy.from_cancel_reentry_policy_dict(data)


def _order(side="SELL", status="REVEALED", executed_size=0):
    return {
        "side": side,
        "status": status,
        "limit_price": 100,
        "executed_size": executed_size,
    }


def _market(mid):
    return {"bid": mid - 0.5, "ask": mid + 0.5, "price": mid, "source": "ticker"}


@pytest.mark.regression
def test_sell_absolute_policy_cancels_then_reenters_with_hysteresis():
    policy = _policy(cancel_distance=8, reentry_distance=9)

    hold = evaluate_cancel_reentry(
        _order("SELL", "REVEALED"),
        _market(91),
        policy,
        CancelReentryRuntimeState(),
    )
    assert hold.decision == CancelReentryDecision.HOLD

    cancel = evaluate_cancel_reentry(
        _order("SELL", "REVEALED"),
        _market(92),
        policy,
        CancelReentryRuntimeState(),
    )
    assert cancel.decision == CancelReentryDecision.CANCEL

    state = CancelReentryRuntimeState(state=CancelReentryState.CANCELLED_BY_POLICY)
    still_cancelled = evaluate_cancel_reentry(_order("SELL", "HIDDEN"), _market(92), policy, state)
    assert still_cancelled.decision == CancelReentryDecision.HOLD

    reenter = evaluate_cancel_reentry(_order("SELL", "HIDDEN"), _market(91), policy, state)
    assert reenter.decision == CancelReentryDecision.REENTER


@pytest.mark.regression
def test_buy_distance_is_reference_minus_limit():
    policy = _policy(cancel_distance=8, reentry_distance=9)

    assert compute_distance("BUY", 100, 109, policy) == pytest.approx(9)
    cancel = evaluate_cancel_reentry(
        _order("BUY", "REVEALED"),
        _market(108),
        policy,
        CancelReentryRuntimeState(),
    )
    assert cancel.decision == CancelReentryDecision.CANCEL


@pytest.mark.regression
def test_reentry_distance_must_exceed_cancel_distance():
    with pytest.raises(ValueError, match="reentry_distance"):
        _policy(cancel_distance=8, reentry_distance=8)


@pytest.mark.regression
def test_filled_order_is_not_policy_cancelled():
    result = evaluate_cancel_reentry(
        _order("SELL", "REVEALED", executed_size=0.1),
        _market(92),
        _policy(),
        CancelReentryRuntimeState(),
    )
    assert result.decision == CancelReentryDecision.HOLD
    assert result.reason == "order_has_fill"


@pytest.mark.regression
def test_cooldown_and_reentry_cap_hold_reentry():
    last_cancel = datetime.utcnow().isoformat()
    state = CancelReentryRuntimeState(
        state=CancelReentryState.CANCELLED_BY_POLICY,
        last_cancel_at=last_cancel,
        reentry_count=1,
    )

    cooldown = evaluate_cancel_reentry(
        _order("SELL", "HIDDEN"),
        _market(90),
        _policy(cooldown_seconds=60),
        state,
        now=datetime.utcnow() + timedelta(seconds=10),
    )
    assert cooldown.decision == CancelReentryDecision.HOLD
    assert cooldown.reason == "cooldown_active"

    capped = evaluate_cancel_reentry(
        _order("SELL", "HIDDEN"),
        _market(90),
        _policy(max_reentry_count=1),
        state,
    )
    assert capped.decision == CancelReentryDecision.HOLD
    assert capped.reason == "max_reentry_count_reached"
