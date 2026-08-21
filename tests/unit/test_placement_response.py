"""Unit tests for the pure exchange-placement response classifier."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from business.placement_response import (
    PlacementClassification,
    classify_placement_response,
)
from core.enums import OrderPlacementOutcome


EXPECTED_COID = "client-order-123"


def test_accepts_explicit_success_with_nested_order_id_and_matching_coid():
    result = classify_placement_response(
        {
            "success": True,
            "success_response": {
                "order_id": " exchange-order-456 ",
                "client_order_id": f" {EXPECTED_COID} ",
            },
        },
        expected_client_order_id=EXPECTED_COID,
    )

    assert result == PlacementClassification(
        outcome=OrderPlacementOutcome.ACCEPTED,
        exchange_order_id="exchange-order-456",
        returned_client_order_id=EXPECTED_COID,
    )
    assert result.accepted is True


def test_accepts_when_success_response_omits_returned_coid():
    result = classify_placement_response(
        {
            "success": True,
            "success_response": {"order_id": "exchange-order-456"},
        },
        expected_client_order_id=EXPECTED_COID,
    )

    assert result.outcome is OrderPlacementOutcome.ACCEPTED
    assert result.returned_client_order_id is None


def test_accepts_sdk_response_via_to_dict():
    class FakeSdkResponse:
        def to_dict(self):
            return {
                "success": True,
                "success_response": {
                    "order_id": "exchange-order-456",
                    "client_order_id": EXPECTED_COID,
                },
            }

    result = classify_placement_response(
        FakeSdkResponse(),
        expected_client_order_id=EXPECTED_COID,
    )

    assert result.outcome is OrderPlacementOutcome.ACCEPTED


@pytest.mark.parametrize(
    ("response", "expected_reason"),
    [
        ({"success": False, "failure_reason": "INVALID_PRICE_PRECISION"},
         "INVALID_PRICE_PRECISION"),
        ({"success": False, "error_response": {"error": "POST_ONLY"}},
         "POST_ONLY"),
        ({"success": False, "error_response": {"preview_failure_reason": "PREVIEW"}},
         "PREVIEW"),
        ({"success": False, "error_response": {"message": "Bad request"}},
         "Bad request"),
        ({"success": False},
         "exchange rejected placement without a failure reason"),
    ],
)
def test_explicit_false_is_rejected_with_safe_failure_reason(response, expected_reason):
    result = classify_placement_response(
        response,
        expected_client_order_id=EXPECTED_COID,
    )

    assert result.outcome is OrderPlacementOutcome.REJECTED
    assert result.accepted is False
    assert result.exchange_order_id is None
    assert result.failure_reason == expected_reason


def test_explicit_false_wins_over_a_contradictory_success_envelope():
    result = classify_placement_response(
        {
            "success": False,
            "success_response": {
                "order_id": "must-not-be-used",
                "client_order_id": EXPECTED_COID,
            },
        },
        expected_client_order_id=EXPECTED_COID,
    )

    assert result.outcome is OrderPlacementOutcome.REJECTED
    assert result.exchange_order_id is None


@pytest.mark.parametrize(
    "response",
    [
        None,
        [],
        {},
        {"success": "true", "success_response": {"order_id": "exchange-order"}},
        {"success": 1, "success_response": {"order_id": "exchange-order"}},
    ],
)
def test_malformed_or_non_boolean_success_is_indeterminate(response):
    result = classify_placement_response(
        response,
        expected_client_order_id=EXPECTED_COID,
    )

    assert result.outcome is OrderPlacementOutcome.INDETERMINATE
    assert result.accepted is False
    assert result.failure_reason


@pytest.mark.parametrize(
    "response",
    [
        {"success": True},
        {"success": True, "success_response": None},
        {"success": True, "success_response": {}},
        {"success": True, "success_response": {"order_id": None}},
        {"success": True, "success_response": {"order_id": "   "}},
        # A legacy top-level id does not satisfy the Coinbase response contract.
        {"success": True, "order_id": "top-level-is-not-accepted"},
    ],
)
def test_success_without_usable_nested_order_id_is_indeterminate(response):
    result = classify_placement_response(
        response,
        expected_client_order_id=EXPECTED_COID,
    )

    assert result.outcome is OrderPlacementOutcome.INDETERMINATE
    assert result.exchange_order_id is None


def test_mismatched_returned_client_order_id_is_indeterminate():
    result = classify_placement_response(
        {
            "success": True,
            "success_response": {
                "order_id": "exchange-order-456",
                "client_order_id": "different-client-order",
            },
        },
        expected_client_order_id=EXPECTED_COID,
    )

    assert result.outcome is OrderPlacementOutcome.INDETERMINATE
    assert result.exchange_order_id == "exchange-order-456"
    assert result.returned_client_order_id == "different-client-order"
    assert "does not match" in result.failure_reason


@pytest.mark.parametrize("returned_coid", [None, "", "   ", 123])
def test_present_but_invalid_returned_client_order_id_is_indeterminate(returned_coid):
    result = classify_placement_response(
        {
            "success": True,
            "success_response": {
                "order_id": "exchange-order-456",
                "client_order_id": returned_coid,
            },
        },
        expected_client_order_id=EXPECTED_COID,
    )

    assert result.outcome is OrderPlacementOutcome.INDETERMINATE


@pytest.mark.parametrize("expected_coid", [None, "", "   ", 123])
def test_invalid_expected_client_order_id_is_indeterminate(expected_coid):
    result = classify_placement_response(
        {
            "success": True,
            "success_response": {"order_id": "exchange-order-456"},
        },
        expected_client_order_id=expected_coid,
    )

    assert result.outcome is OrderPlacementOutcome.INDETERMINATE


def test_exception_is_indeterminate_and_reason_is_single_line_and_bounded():
    exception = TimeoutError("response\nunknown " + ("x" * 700))

    result = classify_placement_response(
        expected_client_order_id=EXPECTED_COID,
        exception=exception,
    )

    assert result.outcome is OrderPlacementOutcome.INDETERMINATE
    assert result.failure_reason.startswith("TimeoutError: response unknown")
    assert "\n" not in result.failure_reason
    assert len(result.failure_reason) == 512


def test_nested_objects_are_not_stringified_into_rejection_reason():
    result = classify_placement_response(
        {
            "success": False,
            "failure_reason": {"api_secret": "must-not-be-persisted"},
            "error_response": {"context": {"token": "also-secret"}},
        },
        expected_client_order_id=EXPECTED_COID,
    )

    assert result.outcome is OrderPlacementOutcome.REJECTED
    assert result.failure_reason == "exchange rejected placement without a failure reason"
    assert "secret" not in result.failure_reason


def test_broken_sdk_to_dict_is_indeterminate_without_propagating():
    class BrokenSdkResponse:
        def to_dict(self):
            raise ValueError("untrusted response contents")

    result = classify_placement_response(
        BrokenSdkResponse(),
        expected_client_order_id=EXPECTED_COID,
    )

    assert result.outcome is OrderPlacementOutcome.INDETERMINATE
    assert result.failure_reason == "placement response to_dict failed: ValueError"


def test_classification_is_immutable():
    result = classify_placement_response(
        {"success": False, "failure_reason": "POST_ONLY"},
        expected_client_order_id=EXPECTED_COID,
    )

    with pytest.raises(FrozenInstanceError):
        result.failure_reason = "silently accepted"
