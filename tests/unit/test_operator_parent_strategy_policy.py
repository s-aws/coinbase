from __future__ import annotations

from decimal import Decimal

import pytest

from application.admin_api.operator_parent_strategy import (
    OperatorParentStrategyError,
    evaluate_parent_strategy_delete,
    normalize_parent_strategy_terms,
)


def test_normalize_parent_strategy_terms_accepts_only_allowlisted_child_policy() -> None:
    terms = normalize_parent_strategy_terms(
        product_id="BTC-USDC",
        side="BUY",
        reference_size="0.00010000",
        reference_price="60000.00",
        target_movement="0.0050",
        target_movement_type="P",
        max_order_replacement=2,
        allow_partial_fills=True,
        child_order_type="LIMIT",
        child_time_in_force="GOOD_UNTIL_CANCELLED",
        child_post_only=True,
    )

    assert terms.product_id == "BTC-USDC"
    assert terms.side == "BUY"
    assert terms.reference_size == Decimal("0.0001")
    assert terms.reference_price == Decimal("60000")
    assert terms.target_movement == Decimal("0.005")
    assert terms.target_movement_type == "P"
    assert terms.max_order_replacement == 2
    assert terms.allow_partial_fills is True
    assert terms.child_order_type == "LIMIT"
    assert terms.child_time_in_force == "GOOD_UNTIL_CANCELLED"
    assert terms.child_post_only is True


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"product_id": "btc-usdc"}, "parent_strategy_product_invalid"),
        ({"side": "HOLD"}, "parent_strategy_side_invalid"),
        ({"reference_size": "0"}, "parent_strategy_reference_size_invalid"),
        ({"reference_price": "NaN"}, "parent_strategy_reference_price_invalid"),
        ({"target_movement": "-0.1"}, "parent_strategy_target_movement_invalid"),
        ({"target_movement_type": "TICKS"}, "parent_strategy_movement_type_invalid"),
        ({"max_order_replacement": -1}, "parent_strategy_replacement_limit_invalid"),
        ({"max_order_replacement": 101}, "parent_strategy_replacement_limit_invalid"),
        ({"child_order_type": "MARKET"}, "parent_strategy_child_policy_invalid"),
        (
            {"child_time_in_force": "IMMEDIATE_OR_CANCEL"},
            "parent_strategy_child_policy_invalid",
        ),
        ({"child_post_only": False}, "parent_strategy_child_policy_invalid"),
    ],
)
def test_normalize_parent_strategy_terms_fails_closed(
    overrides: dict[str, object],
    code: str,
) -> None:
    values: dict[str, object] = {
        "product_id": "BTC-USDC",
        "side": "BUY",
        "reference_size": "0.0001",
        "reference_price": "60000",
        "target_movement": "0.005",
        "target_movement_type": "P",
        "max_order_replacement": 2,
        "allow_partial_fills": False,
        "child_order_type": "LIMIT",
        "child_time_in_force": "GOOD_UNTIL_CANCELLED",
        "child_post_only": True,
    }
    values.update(overrides)

    with pytest.raises(OperatorParentStrategyError) as exc_info:
        normalize_parent_strategy_terms(**values)

    assert exc_info.value.code == code


def test_delete_policy_requires_deactivation_and_zero_dependency_evidence() -> None:
    allowed = evaluate_parent_strategy_delete(
        lifecycle_state="DEACTIVATED",
        unused_or_terminal=True,
        active_placement_count=0,
        child_count=0,
        unresolved_claim_count=0,
        reconciliation_required=False,
    )
    blocked = evaluate_parent_strategy_delete(
        lifecycle_state="DEACTIVATED",
        unused_or_terminal=True,
        active_placement_count=0,
        child_count=1,
        unresolved_claim_count=0,
        reconciliation_required=False,
    )

    assert allowed.allowed is True
    assert allowed.blockers == ()
    assert blocked.allowed is False
    assert blocked.blockers == ("parent_strategy_child_present",)


def test_delete_policy_reports_every_fixed_blocker_without_values() -> None:
    decision = evaluate_parent_strategy_delete(
        lifecycle_state="ACTIVE",
        unused_or_terminal=False,
        active_placement_count=1,
        child_count=2,
        unresolved_claim_count=3,
        reconciliation_required=True,
    )

    assert decision.allowed is False
    assert decision.blockers == (
        "parent_strategy_not_deactivated",
        "parent_strategy_parent_not_unused_or_terminal",
        "parent_strategy_active_placement_present",
        "parent_strategy_child_present",
        "parent_strategy_unresolved_claim_present",
        "parent_strategy_reconciliation_required",
    )
