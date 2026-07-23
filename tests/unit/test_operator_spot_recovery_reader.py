from __future__ import annotations

import pytest

from application.admin_api.command_service import (
    CoinbaseFillReadbackError,
    read_authoritative_coinbase_fills,
)


class _RestClient:
    def __init__(self, pages: list[dict]) -> None:
        self.pages = list(pages)
        self.calls: list[dict] = []

    def list_fills(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self.pages[len(self.calls) - 1]


def test_logical_fill_read_completes_cursor_pages_without_retry() -> None:
    client = _RestClient(
        [
            {
                "fills": [
                    {
                        "order_id": "exchange-order",
                        "product_id": "BTC-USDC",
                    }
                ],
                "cursor": "next-page",
                "has_next": True,
            },
            {
                "fills": [
                    {
                        "order_id": "exchange-order",
                        "product_id": "BTC-USDC",
                    }
                ],
                "has_next": False,
            },
        ]
    )

    result = read_authoritative_coinbase_fills(
        client,
        exchange_order_id="exchange-order",
        product_id="BTC-USDC",
    )

    assert result == {
        "authoritative": True,
        "fill_count": 2,
        "page_count": 2,
        "pagination_complete": True,
    }
    assert client.calls == [
        {
            "order_id": "exchange-order",
            "product_id": "BTC-USDC",
            "limit": 100,
        },
        {
            "order_id": "exchange-order",
            "product_id": "BTC-USDC",
            "limit": 100,
            "cursor": "next-page",
        },
    ]


def test_logical_fill_read_rejects_repeated_cursor_without_third_call() -> None:
    client = _RestClient(
        [
            {
                "fills": [],
                "cursor": "repeat",
                "has_next": True,
            },
            {
                "fills": [],
                "cursor": "repeat",
                "has_next": True,
            },
        ]
    )

    with pytest.raises(
        CoinbaseFillReadbackError,
        match="repeated a cursor",
    ) as exc_info:
        read_authoritative_coinbase_fills(
            client,
            exchange_order_id="exchange-order",
            product_id="BTC-USDC",
        )

    assert exc_info.value.blocker == "fill_read_malformed_pagination"
    assert len(client.calls) == 2


def test_logical_fill_read_allows_authoritative_empty_catalog() -> None:
    client = _RestClient([{"fills": [], "has_next": False}])

    result = read_authoritative_coinbase_fills(
        client,
        exchange_order_id="exchange-order",
        product_id="BTC-USDC",
    )

    assert result["fill_count"] == 0
    assert result["page_count"] == 1
    assert len(client.calls) == 1
