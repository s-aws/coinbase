"""Regression coverage for paginated startup open-order reconciliation."""

from unittest.mock import MagicMock

import pytest


def _client():
    from external.coinbase_client import CoinbaseRestClient

    client = CoinbaseRestClient.__new__(CoinbaseRestClient)
    client._client = MagicMock()
    client._client.list_orders.return_value = {"orders": []}
    return client


@pytest.mark.regression
def test_list_orders_forwards_startup_pagination_cursor() -> None:
    client = _client()

    client.list_orders(order_status=["OPEN"], cursor="next-page")

    client._client.list_orders.assert_called_once_with(
        order_status=["OPEN"],
        cursor="next-page",
    )


@pytest.mark.regression
def test_list_orders_omits_unsupplied_cursor() -> None:
    client = _client()

    client.list_orders(order_status=["OPEN"])

    client._client.list_orders.assert_called_once_with(order_status=["OPEN"])
