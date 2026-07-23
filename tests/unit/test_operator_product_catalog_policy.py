from __future__ import annotations

import inspect

import pytest
from coinbase.rest import RESTClient

from application.admin_api.operator_product_catalog import (
    OperatorProductCatalogError,
    ProductCatalogLifecycle,
    ProductCatalogNormalizedItem,
    ProductCatalogReadResult,
    build_product_catalog_diff,
    normalize_product_catalog_item,
    read_operator_product_catalog,
)
from application.admin_api.route_inventory import ADMIN_API_ROUTE_INVENTORY


class _CatalogClient:
    def __init__(self, pages: list[dict]) -> None:
        self.pages = list(pages)
        self.calls: list[dict] = []

    def get_product_catalog_page(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self.pages[len(self.calls) - 1]


def _raw_product(
    product_id: str = "BTC-USDC",
    *,
    status: str = "online",
    trading_disabled: bool = False,
) -> dict:
    return {
        "product_id": product_id,
        "product_type": "SPOT",
        "base_currency_id": "BTC",
        "quote_currency_id": "USDC",
        "base_increment": "0.00000001",
        "quote_increment": "0.01",
        "price_increment": "0.01",
        "base_min_size": "0.00001",
        "base_max_size": "10",
        "quote_min_size": "1",
        "quote_max_size": "1000000",
        "display_name": "BTC-USDC",
        "status": status,
        "is_disabled": trading_disabled,
        "trading_disabled": trading_disabled,
        "cancel_only": False,
        "limit_only": False,
        "post_only": False,
        "view_only": False,
        "retail_portfolio_id": "private-portfolio-id",
        "private_extension": {"secret": "must-not-survive"},
        "price": "65000",
        "mid_market_price": "65000.01",
    }


def test_normalizer_allowlists_stable_documented_metadata() -> None:
    item = normalize_product_catalog_item(_raw_product())

    assert item == ProductCatalogNormalizedItem(
        product_id="BTC-USDC",
        product_type="SPOT",
        base_currency="BTC",
        quote_currency="USDC",
        base_increment="0.00000001",
        quote_increment="0.01",
        price_increment="0.01",
        base_min_size="0.00001",
        base_max_size="10",
        quote_min_size="1",
        quote_max_size="1000000",
        display_name="BTC-USDC",
        exchange_status="ONLINE",
        exchange_disabled=False,
        cancel_only=False,
        limit_only=False,
        post_only=False,
        view_only=False,
        lifecycle=ProductCatalogLifecycle.PENDING,
    )
    serialized = item.model_dump_json()
    assert "private-portfolio-id" not in serialized
    assert "must-not-survive" not in serialized
    assert "65000" not in serialized


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("product_id", "../BTC-USDC", "product_catalog_product_id_invalid"),
        ("product_type", "UNKNOWN", "product_catalog_product_type_invalid"),
        ("base_increment", "0", "product_catalog_increment_invalid"),
        ("quote_min_size", "NaN", "product_catalog_decimal_invalid"),
    ],
)
def test_normalizer_fails_closed_on_invalid_metadata(
    field: str,
    value: object,
    code: str,
) -> None:
    raw = _raw_product()
    raw[field] = value

    with pytest.raises(OperatorProductCatalogError, match=code):
        normalize_product_catalog_item(raw)


def test_catalog_reader_claims_each_cursor_once_without_retry() -> None:
    client = _CatalogClient(
        [
            {
                "products": [_raw_product()],
                "num_products": 1,
                "pagination": {
                    "has_next": True,
                    "next_cursor": "private-next-cursor",
                },
            },
            {
                "products": [
                    _raw_product(
                        "ETH-USDC",
                        status="OFFLINE",
                        trading_disabled=True,
                    )
                    | {
                        "base_currency_id": "ETH",
                        "display_name": "ETH-USDC",
                    }
                ],
                "num_products": 1,
                "pagination": {
                    "has_next": False,
                    "next_cursor": "",
                },
            },
        ]
    )
    claimed: list[tuple[int, str | None]] = []
    returned: list[int] = []

    result = read_operator_product_catalog(
        client,
        on_page_call=lambda ordinal, cursor_sha256: claimed.append(
            (ordinal, cursor_sha256)
        ),
        on_page_returned=returned.append,
    )

    assert result == ProductCatalogReadResult(
        products=[
            normalize_product_catalog_item(_raw_product()),
            normalize_product_catalog_item(
                _raw_product(
                    "ETH-USDC",
                    status="OFFLINE",
                    trading_disabled=True,
                )
                | {
                    "base_currency_id": "ETH",
                    "display_name": "ETH-USDC",
                }
            ),
        ],
        page_count=2,
        pagination_complete=True,
    )
    assert claimed[0] == (1, None)
    assert claimed[1][0] == 2
    assert len(claimed[1][1] or "") == 64
    assert returned == [1, 2]
    assert client.calls == [
        {"limit": 100, "get_tradability_status": True},
        {
            "limit": 100,
            "get_tradability_status": True,
            "cursor": "private-next-cursor",
        },
    ]
    assert "private-next-cursor" not in result.model_dump_json()


def test_catalog_reader_rejects_repeated_cursor_without_third_call() -> None:
    client = _CatalogClient(
        [
            {
                "products": [],
                "pagination": {"has_next": True, "next_cursor": "repeat"},
            },
            {
                "products": [],
                "pagination": {"has_next": True, "next_cursor": "repeat"},
            },
        ]
    )

    with pytest.raises(
        OperatorProductCatalogError,
        match="product_catalog_cursor_repeated",
    ):
        read_operator_product_catalog(client)

    assert len(client.calls) == 2


def test_catalog_reader_rejects_duplicate_product_identity() -> None:
    client = _CatalogClient(
        [
            {
                "products": [_raw_product(), _raw_product()],
                "pagination": {"has_next": False},
            }
        ]
    )

    with pytest.raises(
        OperatorProductCatalogError,
        match="product_catalog_product_duplicate",
    ):
        read_operator_product_catalog(client)


def test_catalog_diff_preserves_existing_lifecycle_and_disables_new_rows() -> None:
    current = [
        normalize_product_catalog_item(_raw_product()).model_copy(
            update={"lifecycle": ProductCatalogLifecycle.ENABLED}
        ),
        normalize_product_catalog_item(
            _raw_product("SOL-USDC")
            | {
                "base_currency_id": "SOL",
                "display_name": "SOL-USDC",
            }
        ).model_copy(update={"lifecycle": ProductCatalogLifecycle.DISABLED}),
    ]
    refreshed = [
        normalize_product_catalog_item(
            _raw_product() | {"base_min_size": "0.00002"}
        ),
        normalize_product_catalog_item(
            _raw_product("ETH-USDC")
            | {
                "base_currency_id": "ETH",
                "display_name": "ETH-USDC",
            }
        ),
    ]

    diff = build_product_catalog_diff(current=current, refreshed=refreshed)

    by_id = {item.product_id: item for item in diff.snapshot}
    assert by_id["BTC-USDC"].lifecycle is ProductCatalogLifecycle.ENABLED
    assert by_id["ETH-USDC"].lifecycle is ProductCatalogLifecycle.PENDING
    assert by_id["SOL-USDC"].lifecycle is ProductCatalogLifecycle.RETIRED
    assert diff.added_product_ids == ["ETH-USDC"]
    assert diff.changed_product_ids == ["BTC-USDC"]
    assert diff.removed_product_ids == ["SOL-USDC"]
    assert diff.diff_sha256


def test_reader_matches_pinned_sdk_catalog_contract() -> None:
    parameters = inspect.signature(RESTClient.get_products).parameters
    assert {
        "limit",
        "product_ids",
        "get_tradability_status",
        "kwargs",
    }.issubset(parameters)


def test_product_catalog_routes_have_backend_authority_inventory() -> None:
    entries = {
        item.surface: item
        for item in ADMIN_API_ROUTE_INVENTORY
        if item.module_id == "account_management"
        and item.surface.startswith(
            ("GET /api/v1/product-catalog", "POST /api/v1/product-catalog")
        )
    }

    assert set(entries) == {
        "GET /api/v1/product-catalog",
        "GET /api/v1/product-catalog/revisions/{revision_id}",
        "POST /api/v1/product-catalog/refresh",
        "POST /api/v1/product-catalog/revisions/{revision_id}/approve",
        "POST /api/v1/product-catalog/products/{product_id}/enable",
        "POST /api/v1/product-catalog/products/{product_id}/disable",
        "POST /api/v1/product-catalog/products/{product_id}/retire",
        "POST /api/v1/product-catalog/revisions/{target_revision_id}/rollback",
    }
    assert all(
        entry.action_class
        in {
            "read_only",
            "local_state_mutation",
        }
        for entry in entries.values()
    )
