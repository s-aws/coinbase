"""Regression contracts for optional per-rung span repricing policies."""

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SPAN_BUILDER = REPO_ROOT / "ui_order_span_builder.html"


def _slice_between(source: str, start: str, end: str) -> str:
    start_index = source.index(start)
    end_index = source.index(end, start_index)
    return source[start_index:end_index]


def _input_tag(source: str, element_id: str) -> str:
    match = re.search(
        rf'<input\b[^>]*\bid="{re.escape(element_id)}"[^>]*>',
        source,
    )
    assert match is not None, f"Missing input #{element_id}"
    return match.group(0)


@pytest.mark.regression
def test_span_repricing_is_optional_and_uses_canonical_defaults():
    html = SPAN_BUILDER.read_text(encoding="utf-8")
    manager_html = (REPO_ROOT / "ui_stealth_orders_manager.html").read_text(
        encoding="utf-8"
    )

    enable_tag = _input_tag(html, "enable_anchor_repricing")
    assert "checked" not in enable_tag
    assert "checked" not in _input_tag(manager_html, "enable_anchor_repricing")
    assert 'id="anchor-repricing-fields" class="policy-panel hidden"' in html

    expected_defaults = {
        "anchor_target_distance": 'value="0.01"',
        "anchor_max_distance": 'value="0.05"',
        "anchor_min_price_change": 'value="0.01"',
        "anchor_hysteresis_bps": 'value="5"',
        "anchor_min_reprice_interval_seconds": 'value="30"',
        "anchor_max_reprices_per_hour": 'value="20"',
        "anchor_max_step_per_reprice": 'value="5"',
        "anchor_follow_up_retreat_distance": 'value="0.0005"',
        "anchor_follow_up_retreat_jitter": 'value="0.5"',
    }
    for element_id, expected_value in expected_defaults.items():
        assert expected_value in _input_tag(html, element_id)
        assert expected_value in _input_tag(manager_html, element_id)

    assert '<option value="midpoint" selected>Midpoint</option>' in html
    assert '<option value="P" selected>Percentage (%)</option>' in html
    assert '<option value="adaptive" selected>Adaptive</option>' in html
    assert '<option value="60" selected>60</option>' in html
    assert "checked" in _input_tag(html, "anchor_post_only_required")

    builder = _slice_between(
        html,
        "function buildAnchorRepricingPolicy()",
        "function buildIndexedAnchorRepricingPolicy(",
    )
    assert "if (!enabled)" in builder
    assert "return { enabled: false };" in builder
    for policy_key in (
        "reference_price_source",
        "distance_type",
        "target_distance",
        "max_distance",
        "update_mode",
        "fixed_interval_seconds",
        "min_price_change",
        "hysteresis_bps",
        "min_reprice_interval_seconds",
        "max_reprices_per_hour",
        "post_only_required",
        "slide_mode",
        "max_step_per_reprice",
        "follow_up_retreat_distance",
        "follow_up_retreat_jitter",
    ):
        assert f"{policy_key}:" in builder

    manager_builder = _slice_between(
        manager_html,
        "function buildAnchorRepricingPolicy()",
        "const WS_URL",
    )
    assert {
        key
        for key in re.findall(r"^\s{16}([a-z_]+):", builder, flags=re.MULTILINE)
    } == {
        key
        for key in re.findall(
            r"^\s{16}([a-z_]+):", manager_builder, flags=re.MULTILINE
        )
    }


@pytest.mark.regression
def test_span_repricing_offsets_only_distances_with_the_shared_index_helper():
    html = SPAN_BUILDER.read_text(encoding="utf-8")
    indexed_builder = _slice_between(
        html,
        "function buildIndexedAnchorRepricingPolicy(",
        "function getAnchorRepricingValidationError(",
    )

    assert "const absoluteOffset = Math.abs(priceStep) * spanIndex;" in indexed_builder
    assert "basePolicy.distance_type === 'A'" in indexed_builder
    assert ": absoluteOffset / startPrice;" in indexed_builder
    assert "target_distance: basePolicy.target_distance + distanceOffset" in indexed_builder
    assert "max_distance: basePolicy.max_distance + distanceOffset" in indexed_builder
    assert "priceDirection" not in indexed_builder
    assert "side" not in indexed_builder
    assert "...basePolicy" in indexed_builder

    preview = _slice_between(
        html,
        "function generatePreview(",
        "function calculateSizes(",
    )
    assert "buildIndexedAnchorRepricingPolicy(baseAnchorPolicy, i, priceStep, startPrice)" in preview
    assert "formatAnchorRepricingPreview(anchorPolicy)" in preview


@pytest.mark.regression
def test_every_span_order_gets_a_fresh_policy_before_delayed_send():
    html = SPAN_BUILDER.read_text(encoding="utf-8")
    assert html.count(
        "anchor_repricing_policy: buildIndexedAnchorRepricingPolicy("
    ) == 2
    create_span = _slice_between(
        html,
        "function createOrderSpan()",
        "function createIndependentParents(",
    )
    assert "anchor_repricing_policy: buildAnchorRepricingPolicy()" in create_span

    independent = _slice_between(
        html,
        "function createIndependentParents(",
        "function createParentWithChildren(",
    )
    parent_children = _slice_between(
        html,
        "function createParentWithChildren(",
        "function customizeRevealConditionForPrice(",
    )

    for creation_path in (independent, parent_children):
        policy_position = creation_path.index(
            "anchor_repricing_policy: buildIndexedAnchorRepricingPolicy("
        )
        send_position = creation_path.index("setTimeout(() =>")
        assert policy_position < send_position
        assert "formData.anchor_repricing_policy," in creation_path
        assert "formData.price_step," in creation_path
        assert "formData.start_price" in creation_path


@pytest.mark.regression
def test_disabled_repricing_bypasses_validation_and_reset_restores_opt_in_state():
    html = SPAN_BUILDER.read_text(encoding="utf-8")
    validation = _slice_between(
        html,
        "function getAnchorRepricingValidationError(",
        "function formatAnchorRepricingPreview(",
    )
    disabled_guard = validation.index("if (!basePolicy.enabled)")
    disabled_return = validation.index("return null;", disabled_guard)
    numeric_validation = validation.index("const numericValues")
    assert disabled_guard < disabled_return < numeric_validation
    assert "!Number.isInteger(basePolicy.fixed_interval_seconds)" in validation
    assert "basePolicy.min_price_change < 0" in validation
    assert "basePolicy.hysteresis_bps < 0" in validation
    assert "!Number.isInteger(basePolicy.min_reprice_interval_seconds)" in validation
    assert "!Number.isInteger(basePolicy.max_reprices_per_hour)" in validation
    assert "basePolicy.max_step_per_reprice < 0" in validation
    assert "basePolicy.slide_mode && basePolicy.max_step_per_reprice <= 0" in validation
    assert "basePolicy.follow_up_retreat_distance < 0" in validation
    assert "basePolicy.follow_up_retreat_jitter > 1" in validation

    reset = _slice_between(
        html,
        "function resetForm()",
        "function updateOrdersTable()",
    )
    assert "document.getElementById('enable_anchor_repricing').checked = false;" in reset
    assert "document.getElementById('anchor_target_distance').value = '0.01';" in reset
    assert "document.getElementById('anchor_max_distance').value = '0.05';" in reset
    assert "toggleAnchorRepricingFields();" in reset
