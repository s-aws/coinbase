from __future__ import annotations

from decimal import Decimal

import pytest

from application.admin_api.operator_stealth_definition import (
    OperatorStealthDefinitionError,
    classify_stealth_definition_runtime,
    normalize_stealth_definition_terms,
)


def _terms(**overrides: object):
    values: dict[str, object] = {
        "name": "BTC patient bid",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "total_size": "0.0001",
        "limit_price": "60000.00",
        "reveal_condition_type": "PRICE",
        "reveal_price_threshold": "59000.00",
        "reveal_direction": "BELOW",
        "hold_duration_seconds": 5,
        "delay_seconds": None,
        "reveal_pricing_policy": "CONFIGURED_LIMIT",
        "sizing_mode": "FIXED",
        "follow_up_reveal_direction": "OPPOSITE",
        "target_movement": "0.005",
        "target_movement_type": "P",
        "max_order_replacements": 2,
        "allow_partial_fills": False,
        "post_only": True,
    }
    values.update(overrides)
    return normalize_stealth_definition_terms(**values)


def test_normalizes_allowlisted_unrevealed_definition_terms() -> None:
    terms = _terms()

    assert terms.product_id == "BTC-USDC"
    assert terms.side == "BUY"
    assert terms.total_size == Decimal("0.0001")
    assert terms.limit_price == Decimal("6E+4")
    assert terms.reveal_price_threshold == Decimal("5.9E+4")
    assert terms.reveal_direction == "BELOW"
    assert terms.post_only is True


def test_time_delay_condition_forbids_price_fields() -> None:
    terms = _terms(
        reveal_condition_type="TIME_DELAY",
        reveal_price_threshold=None,
        reveal_direction=None,
        hold_duration_seconds=0,
        delay_seconds=60,
    )

    assert terms.delay_seconds == 60
    assert terms.reveal_price_threshold is None


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"product_id": "btc-usdc"}, "stealth_definition_product_invalid"),
        ({"side": "HOLD"}, "stealth_definition_side_invalid"),
        ({"total_size": "0"}, "stealth_definition_total_size_invalid"),
        ({"limit_price": "NaN"}, "stealth_definition_limit_price_invalid"),
        (
            {"reveal_condition_type": "SPREAD"},
            "stealth_definition_reveal_condition_invalid",
        ),
        (
            {"reveal_price_threshold": None},
            "stealth_definition_price_condition_invalid",
        ),
        (
            {"delay_seconds": 1},
            "stealth_definition_price_condition_invalid",
        ),
        (
            {"reveal_pricing_policy": "MARKET"},
            "stealth_definition_pricing_policy_invalid",
        ),
        (
            {"sizing_mode": "VOLUME"},
            "stealth_definition_sizing_mode_invalid",
        ),
        (
            {"follow_up_reveal_direction": "CHAIN"},
            "stealth_definition_follow_up_direction_invalid",
        ),
        (
            {"target_movement": "-1"},
            "stealth_definition_target_movement_invalid",
        ),
        (
            {"max_order_replacements": 101},
            "stealth_definition_replacement_limit_invalid",
        ),
        (
            {"post_only": False},
            "stealth_definition_post_only_required",
        ),
    ],
)
def test_invalid_terms_fail_closed_with_fixed_codes(
    overrides: dict[str, object],
    code: str,
) -> None:
    with pytest.raises(OperatorStealthDefinitionError) as exc_info:
        _terms(**overrides)

    assert exc_info.value.code == code


@pytest.mark.parametrize(
    ("runtime_status", "classification", "navigation"),
    [
        (None, "UNMATERIALIZED", None),
        ("HIDDEN", "ACTIVE", "REVEAL_CLOSEOUT"),
        ("PENDING", "ACTIVE", "REVEAL_CLOSEOUT"),
        ("TRIGGERED", "ACTIVE", "REVEAL_CLOSEOUT"),
        ("REVEALED", "REVEALED", "MOVEMENT_REPRICING"),
        ("EXECUTED", "TERMINAL", "REVEAL_CLOSEOUT"),
        ("CANCELLED", "TERMINAL", "REVEAL_CLOSEOUT"),
        ("UNKNOWN", "UNKNOWN", "REVEAL_CLOSEOUT"),
    ],
)
def test_runtime_classification_blocks_any_materialized_definition(
    runtime_status: str | None,
    classification: str,
    navigation: str | None,
) -> None:
    decision = classify_stealth_definition_runtime(runtime_status)

    assert decision.classification == classification
    assert decision.blocked_navigation == navigation
    assert decision.local_mutation_allowed is (runtime_status is None)
