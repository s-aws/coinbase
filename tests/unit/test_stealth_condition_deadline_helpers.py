"""Deterministic tests for production stealth-condition schedule helpers."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from business.stealth_condition_evaluator import (
    CumulativeVolumeEvaluator,
    CompositeEvaluator,
    PriceThresholdEvaluator,
    ProductRatioEvaluator,
    SpreadEvaluator,
    TimeDelayEvaluator,
    get_evaluator,
)
from core.enums import RevealConditionType


UTC = timezone.utc


def test_price_hold_deadline_and_truth_are_read_only() -> None:
    evaluator = PriceThresholdEvaluator()
    first_met = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)
    condition = {
        "price_threshold": 100.0,
        "direction": "below",
        "hold_duration_seconds": 2,
    }
    order = {"condition_first_met_at": first_met}
    original_condition = deepcopy(condition)
    original_order = deepcopy(order)

    deadline = evaluator.resolve_stable_deadline(condition, order)
    met = evaluator.evaluate_truth({"price": 99.0}, condition, order)
    equal = evaluator.evaluate_truth({"price": 100.0}, condition, order)
    unavailable = evaluator.evaluate_truth({"price": 0}, condition, order)

    assert deadline.available is True
    assert deadline.deadline_utc == first_met + timedelta(seconds=2)
    assert met.known is True
    assert met.truth is True
    assert equal.known is True
    assert equal.truth is False
    assert unavailable.known is False
    assert unavailable.truth is None
    assert condition == original_condition
    assert order == original_order


def test_price_hold_without_first_met_state_has_no_stable_deadline() -> None:
    result = PriceThresholdEvaluator().resolve_stable_deadline(
        {"price_threshold": 100.0, "hold_duration_seconds": 2},
        {"condition_first_met_at": None},
    )

    assert result.supported is True
    assert result.stable is False
    assert result.available is False
    assert result.deadline_utc is None
    assert "condition_first_met_at" in result.reason


def test_price_hold_validates_duration_before_first_true_event() -> None:
    result = PriceThresholdEvaluator().resolve_stable_deadline(
        {
            "price_threshold": 100.0,
            "direction": "below",
            "hold_duration_seconds": "invalid",
        },
        {"condition_first_met_at": None},
    )

    assert result.valid is False
    assert result.available is False
    assert "hold_duration_seconds" in result.reason


def test_spread_hold_deadline_and_inclusive_truth_are_read_only() -> None:
    evaluator = SpreadEvaluator()
    first_met = datetime(2026, 8, 27, 13, 0, 0)
    condition = {"max_spread": 0.5, "hold_duration_seconds": 3.5}
    order = {"condition_first_met_at": first_met}
    original_condition = deepcopy(condition)
    original_order = deepcopy(order)

    deadline = evaluator.resolve_stable_deadline(condition, order)
    equal = evaluator.evaluate_truth(
        {"bid": 100.0, "ask": 100.5}, condition, order
    )
    too_wide = evaluator.evaluate_truth(
        {"bid": 100.0, "ask": 100.5001}, condition, order
    )
    unavailable = evaluator.evaluate_truth(
        {"bid": 0, "ask": 100.5}, condition, order
    )

    assert deadline.available is True
    assert deadline.deadline_utc == first_met + timedelta(seconds=3.5)
    assert equal.truth is True
    assert too_wide.truth is False
    assert unavailable.known is False
    assert unavailable.truth is None
    assert condition == original_condition
    assert order == original_order


def test_non_jitter_time_deadline_uses_injected_now_at_exact_boundary() -> None:
    evaluator = TimeDelayEvaluator()
    created_at = datetime(2026, 8, 27, 14, 0, 0, tzinfo=UTC)
    condition = {"delay_seconds": 15, "jitter_seconds": 0}
    order = {"created_at": created_at}

    deadline = evaluator.resolve_stable_deadline(condition, order)
    before = evaluator.evaluate_truth(
        {},
        condition,
        order,
        now_utc=created_at + timedelta(seconds=14, microseconds=999999),
    )
    exact = evaluator.evaluate_truth(
        {}, condition, order, now_utc=created_at + timedelta(seconds=15)
    )

    assert deadline.available is True
    assert deadline.deadline_utc == created_at + timedelta(seconds=15)
    assert before.truth is False
    assert exact.truth is True


def test_time_truth_aligns_aware_now_with_naive_utc_timestamp() -> None:
    evaluator = TimeDelayEvaluator()
    created_at = datetime(2026, 8, 27, 15, 0, 0)

    result = evaluator.evaluate_truth(
        {},
        {"delay_seconds": 10},
        {"created_at": created_at},
        now_utc=datetime(2026, 8, 27, 15, 0, 10, tzinfo=UTC),
    )

    assert result.known is True
    assert result.truth is True


def test_jittered_time_delay_reports_no_stable_deadline_or_truth() -> None:
    evaluator = TimeDelayEvaluator()
    condition = {"delay_seconds": 15, "jitter_seconds": 2}
    order = {"created_at": datetime(2026, 8, 27, 14, 0, 0)}

    deadline = evaluator.resolve_stable_deadline(condition, order)
    truth = evaluator.evaluate_truth(
        {},
        condition,
        order,
        now_utc=datetime(2026, 8, 27, 14, 1, 0),
    )

    assert deadline.supported is False
    assert deadline.stable is False
    assert deadline.available is False
    assert deadline.deadline_utc is None
    assert "jitter" in deadline.reason.lower()
    assert truth.supported is False
    assert truth.truth is None
    assert "jitter" in truth.reason.lower()


def test_jittered_time_delay_evaluates_numeric_strings_consistently() -> None:
    evaluator = TimeDelayEvaluator()

    met, _reason = evaluator.evaluate(
        {},
        {"delay_seconds": "1", "jitter_seconds": "2"},
        {"created_at": datetime.utcnow() - timedelta(seconds=10)},
    )

    assert met is True


@pytest.mark.parametrize(
    ("condition", "order", "reason_fragment"),
    (
        ({"delay_seconds": 1, "jitter_seconds": 2}, {}, "created_at"),
        (
            {"delay_seconds": "bad", "jitter_seconds": 2},
            {"created_at": datetime(2026, 8, 27)},
            "numeric",
        ),
        (
            {"delay_seconds": 1, "jitter_seconds": float("inf")},
            {"created_at": datetime(2026, 8, 27)},
            "finite",
        ),
    ),
)
def test_jittered_time_delay_still_reports_invalid_configuration(
    condition,
    order,
    reason_fragment,
) -> None:
    result = TimeDelayEvaluator().resolve_stable_deadline(condition, order)

    assert result.valid is False
    assert result.available is False
    assert reason_fragment in result.reason


@pytest.mark.parametrize(
    ("condition_type", "condition"),
    (
        (
            RevealConditionType.CUMULATIVE_VOLUME.value,
            {
                "product_id": "PRODUCT-A",
                "price_level": 100,
                "volume_threshold": 5,
            },
        ),
        (
            RevealConditionType.PRODUCT_RATIO.value,
            {
                "product_a": "PRODUCT-A",
                "product_b": "PRODUCT-B",
                "ratio_threshold": 1.0,
                "direction": "below",
            },
        ),
        (
            RevealConditionType.COMPOSITE.value,
            {
                "operator": "AND",
                "conditions": [
                    {
                        "type": RevealConditionType.PRICE_THRESHOLD.value,
                        "price_threshold": 100,
                        "direction": "above",
                        "hold_duration_seconds": 0,
                    }
                ],
            },
        ),
    ),
)
def test_stateful_ratio_and_composite_report_deadline_absence(
    condition_type: str,
    condition,
) -> None:
    evaluator = get_evaluator(condition_type)

    deadline = evaluator.resolve_stable_deadline(condition, {})
    truth = evaluator.evaluate_truth({}, {}, {}, now_utc=datetime(2026, 8, 27))

    assert deadline.valid is True
    assert deadline.supported is False
    assert deadline.stable is False
    assert deadline.available is False
    assert deadline.deadline_utc is None
    assert type(evaluator).__name__ in deadline.reason
    assert truth.supported is False
    assert truth.truth is None
    assert type(evaluator).__name__ in truth.reason


@pytest.mark.parametrize(
    ("evaluator", "condition", "reason_fragment"),
    (
        (CumulativeVolumeEvaluator(), {}, "product_id"),
        (
            CumulativeVolumeEvaluator(),
            {
                "product_id": "PRODUCT-A",
                "price_level": float("nan"),
                "volume_threshold": 5,
            },
            "price_level",
        ),
        (
            ProductRatioEvaluator(),
            {
                "product_a": "PRODUCT-A",
                "product_b": "PRODUCT-B",
                "ratio_threshold": "not-a-number",
            },
            "ratio_threshold",
        ),
        (CompositeEvaluator(), {"conditions": {}}, "conditions list"),
        (
            CompositeEvaluator(),
            {"conditions": [{"type": None}]},
            "type must be a string",
        ),
        (
            CompositeEvaluator(),
            {
                "conditions": [
                    {
                        "type": RevealConditionType.PRICE_THRESHOLD.value,
                        "direction": "above",
                    }
                ]
            },
            "price_threshold",
        ),
    ),
)
def test_unsupported_conditions_still_validate_configuration(
    evaluator,
    condition,
    reason_fragment,
) -> None:
    result = evaluator.resolve_stable_deadline(condition, {})

    assert result.valid is False
    assert result.supported is False
    assert result.available is False
    assert reason_fragment in result.reason


def test_compatibility_validation_preserves_legacy_fallback_semantics() -> None:
    cumulative = CumulativeVolumeEvaluator()
    cumulative_condition = {
        # Legacy evaluation only requires presence/non-None and interpolates
        # this value into a string bucket key.
        "product_id": "",
        "price_level": 100,
        "volume_threshold": 1,
    }
    ratio = ProductRatioEvaluator()
    ratio_condition = {
        "product_a": "PRODUCT-A",
        "product_b": "PRODUCT-B",
        "ratio_threshold": 1,
        # The legacy evaluator treats every non-below value as ABOVE.
        "direction": "legacy-above",
    }
    composite = CompositeEvaluator()
    composite_condition = {
        # The legacy evaluator treats every non-AND value as OR and skips
        # unknown child names.
        "operator": "legacy-or",
        "conditions": [
            {"type": "unknown"},
            {
                "type": RevealConditionType.PRODUCT_RATIO.value,
                **ratio_condition,
            },
        ],
    }

    cumulative_validation = cumulative.resolve_stable_deadline(
        cumulative_condition,
        {},
    )
    cumulative_none = cumulative.resolve_stable_deadline(
        {**cumulative_condition, "product_id": None},
        {},
    )
    ratio_validation = ratio.resolve_stable_deadline(ratio_condition, {})
    composite_validation = composite.resolve_stable_deadline(
        composite_condition,
        {},
    )
    met, _reason = composite.evaluate(
        {"price_a": 2.0, "price_b": 1.0},
        composite_condition,
        {},
    )

    assert cumulative_validation.valid is True
    assert cumulative_none.valid is False
    assert ratio_validation.valid is True
    assert composite_validation.valid is True
    assert met is True


def test_composite_evaluates_validated_numeric_strings_consistently() -> None:
    evaluator = CompositeEvaluator()
    condition = {
        "operator": "AND",
        "conditions": [
            {
                "type": RevealConditionType.PRICE_THRESHOLD.value,
                "price_threshold": "100",
                "direction": "above",
                "hold_duration_seconds": "0",
            },
            {
                "type": RevealConditionType.SPREAD.value,
                "max_spread": "2",
                "hold_duration_seconds": "0",
            },
        ],
    }
    order = {
        "created_at": datetime.utcnow(),
        "condition_first_met_at": datetime.utcnow() - timedelta(seconds=1),
    }

    validation = evaluator.resolve_stable_deadline(condition, order)
    met, _reason = evaluator.evaluate(
        {"price": 101.0, "bid": 100.0, "ask": 101.0},
        condition,
        order,
    )

    assert validation.valid is True
    assert validation.supported is False
    assert met is True
