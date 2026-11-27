"""Coinbase REST resource construction and startup snapshot adapters."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from coinbase.rest import RESTClient

from core.exceptions import CoinbaseAPIError
from external.coinbase_client import CoinbaseRestClient


class StartupRestClient(Protocol):
    """Narrow REST capability used while composing the runtime."""

    def get_product_dict(self, product_id: str) -> Any: ...

    def list_futures_positions(self) -> Any: ...


def build_rest_client(
    api_key: str | None,
    api_secret: str | None,
) -> CoinbaseRestClient:
    """Construct the authenticated Coinbase REST adapter without network I/O."""

    sdk_client = RESTClient(
        api_key=api_key,
        api_secret=api_secret,
        rate_limit_headers=True,
    )
    return CoinbaseRestClient(sdk_client)


def fetch_products(
    rest_client: StartupRestClient,
    product_ids: Iterable[str],
) -> dict[str, dict[str, Any]]:
    """Fetch configured products and reject malformed venue responses."""

    products: dict[str, dict[str, Any]] = {}
    for requested_product_id in product_ids:
        item = rest_client.get_product_dict(requested_product_id)
        if not isinstance(item, Mapping):
            raise CoinbaseAPIError(
                "Coinbase returned a malformed product response",
                api_error_code="malformed_product_response",
            )
        product = dict(item)
        product_id = product.get("product_id")
        if not product_id:
            raise CoinbaseAPIError(
                "Coinbase product response omitted product_id",
                api_error_code="malformed_product_response",
            )
        if product.get("trading_disabled") is False:
            products[str(product_id)] = product
    return products


def fetch_futures_positions(
    rest_client: StartupRestClient,
) -> dict[str, dict[str, Any]]:
    """Fetch and normalize the current futures-position snapshot."""

    response = rest_client.list_futures_positions()
    raw = response.to_dict() if hasattr(response, "to_dict") else response
    if not isinstance(raw, Mapping):
        raise CoinbaseAPIError(
            "Coinbase returned a malformed futures positions response",
            api_error_code="malformed_futures_positions_response",
        )
    positions = raw.get("positions", [])
    if not isinstance(positions, list):
        raise CoinbaseAPIError(
            "Coinbase futures positions response omitted a positions list",
            api_error_code="malformed_futures_positions_response",
        )
    return {
        str(position["product_id"]): dict(position)
        for position in positions
        if isinstance(position, Mapping) and position.get("product_id")
    }
