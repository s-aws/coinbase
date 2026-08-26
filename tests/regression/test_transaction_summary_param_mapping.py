"""Regression coverage for Coinbase transaction-summary filter forwarding."""

from unittest.mock import Mock

import pytest

from core import ContractExpiryType, ProductType, ProductVenue
from external.coinbase_client import CoinbaseRestClient


def _make_client():
    sdk_client = Mock()
    response = Mock()
    response.to_dict.return_value = {"fee_tier": {}}
    sdk_client.get_transaction_summary.return_value = response
    return CoinbaseRestClient(sdk_client), sdk_client


@pytest.mark.regression
def test_transaction_summary_preserves_no_argument_behavior():
    client, sdk_client = _make_client()

    result = client.get_transaction_summary()

    assert result == {"fee_tier": {}}
    sdk_client.get_transaction_summary.assert_called_once_with()


@pytest.mark.regression
def test_transaction_summary_forwards_exact_sdk_filter_kwargs():
    client, sdk_client = _make_client()

    client.get_transaction_summary(
        product_type=ProductType.FUTURE,
        contract_expiry_type=ContractExpiryType.EXPIRING,
        product_venue=ProductVenue.FCM,
    )

    sdk_client.get_transaction_summary.assert_called_once_with(
        product_type="FUTURE",
        contract_expiry_type="EXPIRING",
        product_venue="FCM",
    )


@pytest.mark.regression
def test_transaction_summary_omits_unsupplied_filter_kwargs():
    client, sdk_client = _make_client()

    client.get_transaction_summary(product_type=ProductType.FUTURE)

    sdk_client.get_transaction_summary.assert_called_once_with(
        product_type="FUTURE",
    )


@pytest.mark.regression
def test_product_venue_exports_approved_schedule_values():
    assert ProductVenue.CBE.value == "CBE"
    assert ProductVenue.FCM.value == "FCM"
