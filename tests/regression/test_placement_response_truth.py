"""Regression guards for false-positive REST placement success."""

from business.placement_response import classify_placement_response
from core.enums import OrderPlacementOutcome


def test_exchange_rejection_cannot_be_classified_as_accepted():
    """A returned REST response is not itself proof of exchange acceptance."""

    result = classify_placement_response(
        {
            "success": False,
            "failure_reason": "INVALID_PRICE_PRECISION",
            "error_response": {"message": "price is not on the product tick"},
        },
        expected_client_order_id="2420417a-656c-41ae-8aae-ba0afd1862ac",
    )

    assert result.outcome is OrderPlacementOutcome.REJECTED
    assert result.accepted is False
    assert result.exchange_order_id is None
    assert result.failure_reason == "INVALID_PRICE_PRECISION"


def test_success_without_exchange_order_id_is_indeterminate_not_accepted():
    """Never reproduce a local 'placed' record with exchange_order_id=NULL."""

    result = classify_placement_response(
        {
            "success": True,
            "success_response": {
                "order_id": None,
                "client_order_id": "2420417a-656c-41ae-8aae-ba0afd1862ac",
            },
        },
        expected_client_order_id="2420417a-656c-41ae-8aae-ba0afd1862ac",
    )

    assert result.outcome is OrderPlacementOutcome.INDETERMINATE
    assert result.accepted is False
    assert result.exchange_order_id is None
