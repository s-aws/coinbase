from __future__ import annotations

from importlib.metadata import version
from types import SimpleNamespace

from coinbase.rest.types.orders_types import PreviewOrderResponse

from application.admin_api.operator_spot_automation_preview import (
    SpotAutomationPreviewFailureClass,
    SpotAutomationPreviewOutcome,
    SpotAutomationPreviewRejectionCode,
    classify_spot_automation_preview_response,
    unknown_spot_automation_preview_classification,
)


def _preview_response(**overrides: object) -> PreviewOrderResponse:
    values: dict[str, object] = {
        "order_total": "0.5005",
        "commission_total": "0.0005",
        "errs": [],
        "warning": [],
        "quote_size": "0.5",
        "base_size": "0.00001",
        "best_bid": "49999",
        "best_ask": "50000",
        "is_max": False,
        "preview_id": "private-preview-identifier",
    }
    values.update(overrides)
    return PreviewOrderResponse(values)


def test_pinned_sdk_preview_envelope_is_the_valid_shallow_boundary() -> None:
    assert version("coinbase-advanced-py") == "1.8.4"

    result = classify_spot_automation_preview_response(
        _preview_response(),
        expected_base_size="0.00001",
        expected_quote_size="0.5",
    )

    assert result.outcome is SpotAutomationPreviewOutcome.ACCEPTED


def test_attribute_compatible_non_sdk_envelope_is_rejected() -> None:
    result = classify_spot_automation_preview_response(
        SimpleNamespace(**_preview_response().to_dict()),
        expected_base_size="0.00001",
        expected_quote_size="0.5",
    )

    assert result.outcome is SpotAutomationPreviewOutcome.UNKNOWN
    assert (
        result.failure_class
        is SpotAutomationPreviewFailureClass.RESPONSE_SCHEMA_INVALID
    )


def test_schema_valid_error_free_preview_is_accepted_and_hashes_identity() -> None:
    result = classify_spot_automation_preview_response(
        _preview_response(warning=["SMALL_ORDER"]),
        expected_base_size="0.00001",
        expected_quote_size="0.5",
    )

    assert result.outcome is SpotAutomationPreviewOutcome.ACCEPTED
    assert result.failure_class is SpotAutomationPreviewFailureClass.NONE
    assert result.warning_present is True
    assert result.preview_id_sha256 is not None
    assert len(result.preview_id_sha256) == 64
    assert "private-preview-identifier" not in repr(result)


def test_documented_error_is_fixed_value_rejection_without_raw_value() -> None:
    result = classify_spot_automation_preview_response(
        _preview_response(errs=["PREVIEW_INSUFFICIENT_FUND"]),
        expected_base_size="0.00001",
        expected_quote_size="0.5",
    )

    assert result.outcome is SpotAutomationPreviewOutcome.REJECTED
    assert (
        result.failure_class
        is SpotAutomationPreviewFailureClass.DOCUMENTED_REJECTION
    )
    assert (
        result.rejection_code
        is SpotAutomationPreviewRejectionCode.INSUFFICIENT_FUNDS
    )
    assert result.preview_id_sha256 is None
    assert "PREVIEW_INSUFFICIENT_FUND" not in repr(result)


def test_documented_candidate_term_errors_use_fixed_actionable_codes() -> None:
    expected = {
        "PREVIEW_INVALID_SIZE_PRECISION": (
            SpotAutomationPreviewRejectionCode.SIZE_PRECISION
        ),
        "PREVIEW_INVALID_PRICE_PRECISION": (
            SpotAutomationPreviewRejectionCode.PRICE_PRECISION
        ),
        "PREVIEW_INVALID_BASE_SIZE_TOO_SMALL": (
            SpotAutomationPreviewRejectionCode.BASE_SIZE_TOO_SMALL
        ),
        "PREVIEW_INVALID_QUOTE_SIZE_TOO_SMALL": (
            SpotAutomationPreviewRejectionCode.QUOTE_SIZE_TOO_SMALL
        ),
        "PREVIEW_INVALID_LIMIT_PRICE_POST_ONLY": (
            SpotAutomationPreviewRejectionCode.POST_ONLY_LIMIT_PRICE
        ),
        "PREVIEW_MISSING_MARKET_TRADE_DATA": (
            SpotAutomationPreviewRejectionCode.MARKET_TRADE_DATA_MISSING
        ),
    }

    for documented_error, rejection_code in expected.items():
        result = classify_spot_automation_preview_response(
            _preview_response(errs=[documented_error]),
            expected_base_size="0.00001",
            expected_quote_size="0.5",
        )

        assert result.outcome is SpotAutomationPreviewOutcome.REJECTED
        assert result.rejection_code is rejection_code
        assert documented_error not in repr(result)


def test_multiple_documented_errors_are_value_blind_and_not_actionable() -> None:
    result = classify_spot_automation_preview_response(
        _preview_response(
            errs=[
                "PREVIEW_INVALID_SIZE_PRECISION",
                "PREVIEW_INSUFFICIENT_FUND",
            ]
        ),
        expected_base_size="0.00001",
        expected_quote_size="0.5",
    )

    assert result.outcome is SpotAutomationPreviewOutcome.REJECTED
    assert (
        result.rejection_code
        is SpotAutomationPreviewRejectionCode.MULTIPLE_DOCUMENTED
    )
    assert "PRECISION" not in repr(result)
    assert "INSUFFICIENT" not in repr(result)


def test_undocumented_preview_shaped_error_is_not_documented() -> None:
    result = classify_spot_automation_preview_response(
        _preview_response(errs=["PREVIEW_PRIVATE_FUTURE_REASON"]),
        expected_base_size="0.00001",
        expected_quote_size="0.5",
    )

    assert result.outcome is SpotAutomationPreviewOutcome.REJECTED
    assert (
        result.failure_class
        is SpotAutomationPreviewFailureClass.UNCLASSIFIED_REJECTION
    )
    assert result.rejection_code is None


def test_unrecognized_error_is_sanitized_rejection_without_echoing_input() -> None:
    result = classify_spot_automation_preview_response(
        _preview_response(errs=["withheld private error text"]),
        expected_base_size="0.00001",
        expected_quote_size="0.5",
    )

    assert result.outcome is SpotAutomationPreviewOutcome.REJECTED
    assert (
        result.failure_class
        is SpotAutomationPreviewFailureClass.UNCLASSIFIED_REJECTION
    )
    assert result.rejection_code is None
    assert "withheld" not in repr(result)


def test_converter_only_or_mapping_envelope_is_unknown_without_conversion() -> None:
    class ConverterOnly:
        def to_dict(self) -> dict[str, object]:
            raise AssertionError("converter must not be invoked")

    for response in (ConverterOnly(), _preview_response().__dict__):
        result = classify_spot_automation_preview_response(
            response,
            expected_base_size="0.00001",
            expected_quote_size="0.5",
        )
        assert result.outcome is SpotAutomationPreviewOutcome.UNKNOWN
        assert (
            result.failure_class
            is SpotAutomationPreviewFailureClass.RESPONSE_SCHEMA_INVALID
        )


def test_malformed_economics_identity_or_warning_fail_closed() -> None:
    responses = (
        _preview_response(base_size="0.00002"),
        _preview_response(order_total="not-a-number"),
        _preview_response(preview_id=123),
        _preview_response(warning=["private warning text"]),
        _preview_response(errs="PREVIEW_INVALID_PRODUCT_ID"),
        _preview_response(quote_size="0.6"),
        _preview_response(order_total="0.5006"),
        _preview_response(commission_total="0.0004"),
        _preview_response(is_max=True),
        _preview_response(best_bid="50001", best_ask="50000"),
    )

    for response in responses:
        result = classify_spot_automation_preview_response(
            response,
            expected_base_size="0.00001",
            expected_quote_size="0.5",
        )
        assert result.outcome is SpotAutomationPreviewOutcome.UNKNOWN
        assert (
            result.failure_class
            is SpotAutomationPreviewFailureClass.RESPONSE_SCHEMA_INVALID
        )
        assert result.preview_id_sha256 is None


def test_preview_identifier_may_be_withheld() -> None:
    result = classify_spot_automation_preview_response(
        _preview_response(preview_id=None),
        expected_base_size="0.00001",
        expected_quote_size="0.5",
    )

    assert result.outcome is SpotAutomationPreviewOutcome.ACCEPTED
    assert result.preview_id_sha256 is None


def test_transport_unknown_withholds_the_exact_wire_call_count() -> None:
    result = unknown_spot_automation_preview_classification(
        transport_unknown=True
    )

    assert result.outcome is SpotAutomationPreviewOutcome.UNKNOWN
    assert result.preview_call_count is None
    assert result.preview_call_count_exact is False
