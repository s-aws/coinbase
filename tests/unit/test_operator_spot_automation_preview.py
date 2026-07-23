from __future__ import annotations

from importlib.metadata import version
import socket
from types import SimpleNamespace

from coinbase.rest.types.orders_types import PreviewOrderResponse
from requests import Response
from requests.exceptions import (
    ConnectTimeout,
    ConnectionError as RequestsConnectionError,
    ContentDecodingError,
    HTTPError,
    InvalidURL,
    JSONDecodeError as RequestsJSONDecodeError,
    ProxyError,
    ReadTimeout,
    SSLError,
    Timeout,
    TooManyRedirects,
)

from application.admin_api.operator_spot_automation_preview import (
    SpotAutomationPreviewFailureClass,
    SpotAutomationPreviewInvocationStage,
    SpotAutomationPreviewOutcome,
    SpotAutomationPreviewRejectionCode,
    classify_spot_automation_preview_exception,
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


def _response_exception(
    exception_type: type[HTTPError] | type[TooManyRedirects],
    status_code: int,
) -> Exception:
    response = Response()
    response.status_code = status_code
    response._content = b"withheld-private-response"
    return exception_type("withheld-private-exception", response=response)


def test_http_response_failures_are_exact_fixed_value_blind_boundaries() -> None:
    expected = (
        (HTTPError, 400, SpotAutomationPreviewFailureClass.HTTP_CLIENT_RESPONSE),
        (HTTPError, 500, SpotAutomationPreviewFailureClass.HTTP_SERVER_RESPONSE),
        (
            TooManyRedirects,
            302,
            SpotAutomationPreviewFailureClass.HTTP_REDIRECT_RESPONSE,
        ),
    )

    for exception_type, status_code, failure_class in expected:
        result = classify_spot_automation_preview_exception(
            _response_exception(exception_type, status_code)
        )

        assert result.outcome is SpotAutomationPreviewOutcome.UNKNOWN
        assert result.failure_class is failure_class
        assert result.preview_call_count == 1
        assert result.preview_call_count_exact is True
        assert "withheld" not in repr(result)


def test_transport_exception_remains_inexact_and_value_blind() -> None:
    result = classify_spot_automation_preview_exception(
        Timeout("withheld-private-exception")
    )

    assert result.outcome is SpotAutomationPreviewOutcome.UNKNOWN
    assert (
        result.failure_class
        is SpotAutomationPreviewFailureClass.TRANSPORT_UNKNOWN
    )
    assert result.preview_call_count is None
    assert result.preview_call_count_exact is False
    assert "withheld" not in repr(result)


def test_future_preview_request_composition_failure_is_exact_and_value_blind() -> None:
    result = classify_spot_automation_preview_exception(
        InvalidURL("withheld-private-exception"),
        stage=SpotAutomationPreviewInvocationStage.REQUEST_COMPOSITION,
    )

    assert result.outcome is SpotAutomationPreviewOutcome.UNKNOWN
    assert (
        result.failure_class
        is SpotAutomationPreviewFailureClass.REQUEST_COMPOSITION_FAILURE
    )
    assert result.preview_call_count == 0
    assert result.preview_call_count_exact is True
    assert "withheld" not in repr(result)


def test_future_preview_sdk_and_transport_failures_are_type_only() -> None:
    expected = (
        (
            RuntimeError("withheld-private-exception"),
            SpotAutomationPreviewFailureClass.SDK_INVOCATION_UNKNOWN,
            None,
            False,
        ),
        (
            socket.gaierror("withheld-private-exception"),
            SpotAutomationPreviewFailureClass.DNS_RESOLUTION_FAILURE,
            0,
            True,
        ),
        (
            ConnectionRefusedError("withheld-private-exception"),
            SpotAutomationPreviewFailureClass.TCP_CONNECTION_FAILURE,
            0,
            True,
        ),
        (
            ConnectTimeout("withheld-private-exception"),
            SpotAutomationPreviewFailureClass.CONNECT_TIMEOUT,
            0,
            True,
        ),
        (
            SSLError("withheld-private-exception"),
            SpotAutomationPreviewFailureClass.TLS_OR_CERTIFICATE_FAILURE,
            None,
            False,
        ),
        (
            ProxyError("withheld-private-exception"),
            SpotAutomationPreviewFailureClass.PROXY_FAILURE,
            0,
            True,
        ),
        (
            ReadTimeout("withheld-private-exception"),
            SpotAutomationPreviewFailureClass.READ_TIMEOUT,
            1,
            True,
        ),
        (
            ConnectionResetError("withheld-private-exception"),
            SpotAutomationPreviewFailureClass.CONNECTION_RESET,
            None,
            False,
        ),
        (
            RequestsConnectionError("withheld-private-exception"),
            SpotAutomationPreviewFailureClass.TRANSPORT_UNKNOWN,
            None,
            False,
        ),
    )

    for exception, failure_class, call_count, exact in expected:
        result = classify_spot_automation_preview_exception(exception)

        assert result.outcome is SpotAutomationPreviewOutcome.UNKNOWN
        assert result.failure_class is failure_class
        assert result.preview_call_count == call_count
        assert result.preview_call_count_exact is exact
        assert "withheld" not in repr(result)


def test_future_preview_response_decode_failure_is_distinct_from_schema() -> None:
    result = classify_spot_automation_preview_exception(
        ContentDecodingError("withheld-private-exception")
    )

    assert result.outcome is SpotAutomationPreviewOutcome.UNKNOWN
    assert (
        result.failure_class
        is SpotAutomationPreviewFailureClass.RESPONSE_DECODING_FAILURE
    )
    assert result.preview_call_count == 1
    assert result.preview_call_count_exact is True
    assert "withheld" not in repr(result)


def test_response_json_decode_failure_is_exact_schema_invalid_evidence() -> None:
    result = classify_spot_automation_preview_exception(
        RequestsJSONDecodeError(
            "withheld-private-exception",
            "withheld-private-response",
            0,
        )
    )

    assert result.outcome is SpotAutomationPreviewOutcome.UNKNOWN
    assert (
        result.failure_class
        is SpotAutomationPreviewFailureClass.RESPONSE_DECODING_FAILURE
    )
    assert result.preview_call_count == 1
    assert result.preview_call_count_exact is True
    assert "withheld" not in repr(result)
