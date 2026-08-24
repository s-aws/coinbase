"""Regression contracts for configurable zero-second price-condition holds."""

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _slice_between(source: str, start: str, end: str) -> str:
    start_index = source.index(start)
    end_index = source.index(end, start_index)
    return source[start_index:end_index]


def _assert_input_attributes(source: str, field_name: str, expected: set[str]) -> None:
    tag_match = re.search(
        rf'<input\b[^>]*(?:id|name)="{re.escape(field_name)}"[^>]*>',
        source,
    )
    assert tag_match is not None, f"Missing input for {field_name}"
    tag = tag_match.group(0)
    for attribute in expected:
        assert attribute in tag


@pytest.mark.regression
def test_span_builder_emits_operator_selected_zero_price_hold():
    html = (REPO_ROOT / "ui_order_span_builder.html").read_text(encoding="utf-8")
    price_fields = _slice_between(
        html,
        "<!-- Price Threshold Fields -->",
        "<!-- Spread Fields -->",
    )
    build_condition = _slice_between(
        html,
        "function buildRevealCondition()",
        "function resetForm()",
    )

    _assert_input_attributes(
        price_fields,
        "price_hold_duration_seconds",
        {'value="0"', 'min="0"', 'step="1"'},
    )
    assert "readNonNegativeWholeSeconds(" in build_condition
    assert "'price_hold_duration_seconds'," in build_condition
    assert "hold_duration_seconds: holdDuration" in build_condition
    assert "hold_duration_seconds: 2" not in build_condition
    assert "document.getElementById('price_hold_duration_seconds').value = '0';" in html
    assert html.count("}, i * 200);") == 2


@pytest.mark.regression
def test_manager_emits_and_displays_explicit_zero_price_hold():
    html = (REPO_ROOT / "ui_stealth_orders_manager.html").read_text(encoding="utf-8")
    price_template = _slice_between(
        html,
        "const conditionTemplates = {\n            price: `",
        "            cumulative_volume: `",
    )
    build_condition = _slice_between(
        html,
        "function buildRevealCondition()",
        "document.getElementById('condition_type').addEventListener",
    )
    price_display = _slice_between(
        html,
        "case 'price':",
        "case 'cumulative_volume':",
    )

    _assert_input_attributes(
        price_template,
        "hold_duration_seconds",
        {'value="0"', 'min="0"', 'step="1"', "required"},
    )
    assert "field.name && field.value !== ''" in build_condition
    assert "!Number.isInteger(holdDuration) || holdDuration < 0" in build_condition
    assert "condition.hold_duration_seconds = holdDuration;" in build_condition
    assert "reveal_condition: revealCondition" in html
    assert (
        "conditionJson.hold_duration_seconds !== undefined && "
        "conditionJson.hold_duration_seconds !== null"
        in price_display
    )
    assert "Hold: ${conditionJson.hold_duration_seconds}s" in price_display
    assert "if (conditionJson.hold_duration_seconds)" not in price_display
