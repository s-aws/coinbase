from __future__ import annotations

import inspect
from decimal import Decimal

import pytest
from coinbase.rest import RESTClient
from coinbase.rest.types.orders_types import ListFillsResponse

from application.admin_api.operator_fill_inventory_repair import (
    FillInventoryCatalogSelector,
    FillInventoryRepairSelectorType,
    NormalizedFillCatalogEntry,
    OperatorFillInventoryRepairCaseCreateRequest,
    OperatorFillInventoryRepairEventItem,
    OperatorFillInventoryRepairService,
    build_fill_inventory_projection,
    read_operator_fill_catalog,
)
from business.spot_fill_ledger_health import analyze_spot_fill_ledger_rows


_PORTFOLIO_HASH = "a" * 64
_CLIENT_ORDER_ID = "8f1bf38c-90ad-4a7c-90fb-87cb56c72a80"


class _RestClient:
    def __init__(self, pages: list[dict]) -> None:
        self.pages = list(pages)
        self.calls: list[dict] = []

    def get_fills(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self.pages[len(self.calls) - 1]


def _entry(
    *,
    identity: str,
    side: str,
    quantity: str,
    price: str,
    fees: str,
    timestamp: str,
) -> NormalizedFillCatalogEntry:
    return NormalizedFillCatalogEntry(
        fill_identity_sha256=identity * 64,
        fill_identity_aliases_sha256=[identity * 64],
        exchange_order_id_sha256="e" * 64,
        client_order_id=_CLIENT_ORDER_ID,
        product_id="BTC-USDC",
        side=side,
        quantity=quantity,
        price=price,
        fees=fees,
        trade_time=timestamp,
        portfolio_id_sha256=_PORTFOLIO_HASH,
    )


def test_create_request_enforces_exact_selector_shape() -> None:
    order_request = OperatorFillInventoryRepairCaseCreateRequest(
        selector_type=FillInventoryRepairSelectorType.EXACT_ORDER,
        client_order_id=_CLIENT_ORDER_ID,
        operator_reason="repair exact order fills",
    )
    assert order_request.product_id is None

    product_request = OperatorFillInventoryRepairCaseCreateRequest(
        selector_type=FillInventoryRepairSelectorType.PRODUCT,
        product_id="BTC-USDC",
        operator_reason="repair product fills",
    )
    assert product_request.client_order_id is None

    window_request = OperatorFillInventoryRepairCaseCreateRequest(
        selector_type=FillInventoryRepairSelectorType.TIME_WINDOW,
        product_id="BTC-USDC",
        window_start="2026-07-22T00:00:00Z",
        window_end="2026-07-22T12:00:00Z",
        operator_reason="repair bounded window",
    )
    assert window_request.window_start is not None

    with pytest.raises(ValueError, match="fill_inventory_selector_invalid"):
        OperatorFillInventoryRepairCaseCreateRequest(
            selector_type=FillInventoryRepairSelectorType.EXACT_ORDER,
            product_id="BTC-USDC",
            operator_reason="missing exact client order",
        )

    with pytest.raises(ValueError, match="fill_inventory_window_too_wide"):
        OperatorFillInventoryRepairCaseCreateRequest(
            selector_type=FillInventoryRepairSelectorType.TIME_WINDOW,
            product_id="BTC-USDC",
            window_start="2026-07-01T00:00:00Z",
            window_end="2026-07-03T00:00:01Z",
            operator_reason="unbounded repair",
        )


def test_fill_catalog_reader_uses_each_cursor_once_and_hashes_private_ids() -> None:
    client = _RestClient(
        [
            {
                "fills": [
                    {
                        "entry_id": "private-entry-1",
                        "trade_id": "private-trade-1",
                        "order_id": "private-order-1",
                        "trade_time": "2026-07-22T01:00:00Z",
                        "price": "100",
                        "size": "0.01",
                        "commission": "0.02",
                        "product_id": "BTC-USDC",
                        "side": "BUY",
                        "size_in_quote": False,
                    }
                ],
                "cursor": "page-2",
                "has_next": True,
            },
            {
                "fills": [
                    {
                        "entry_id": "private-entry-2",
                        "trade_id": "private-trade-2",
                        "order_id": "private-order-1",
                        "trade_time": "2026-07-22T02:00:00Z",
                        "price": "110",
                        "size": "0.01",
                        "commission": "0.02",
                        "product_id": "BTC-USDC",
                        "side": "BUY",
                        "size_in_quote": False,
                    }
                ],
                "has_next": False,
            },
        ]
    )
    selector = FillInventoryCatalogSelector(
        selector_type=FillInventoryRepairSelectorType.TIME_WINDOW,
        product_id="BTC-USDC",
        window_start="2026-07-22T00:00:00Z",
        window_end="2026-07-22T12:00:00Z",
        portfolio_id_sha256=_PORTFOLIO_HASH,
    )

    page_claims: list[tuple[int, str | None]] = []
    result = read_operator_fill_catalog(
        client,
        selector=selector,
        retail_portfolio_id="11111111-2222-4333-8444-555555555555",
        resolve_system_order=lambda order_id, product_id: {
            "client_order_id": _CLIENT_ORDER_ID,
            "product_id": product_id,
            "portfolio_id_sha256": _PORTFOLIO_HASH,
            "system_owned": order_id == "private-order-1",
        },
        on_page_call=lambda ordinal, cursor_sha256: page_claims.append(
            (ordinal, cursor_sha256)
        ),
    )

    assert result.page_count == 2
    assert result.pagination_complete is True
    assert len(result.entries) == 2
    assert result.entries[0].fill_identity_sha256 != "private-entry-1"
    assert len(result.entries[0].fill_identity_aliases_sha256) == 2
    assert result.entries[0].fill_identity_sha256 in (
        result.entries[0].fill_identity_aliases_sha256
    )
    assert "private" not in result.model_dump_json()
    assert page_claims[0] == (1, None)
    assert page_claims[1][0] == 2
    assert len(page_claims[1][1] or "") == 64
    assert client.calls == [
        {
            "product_ids": ["BTC-USDC"],
            "start_sequence_timestamp": "2026-07-22T00:00:00Z",
            "end_sequence_timestamp": "2026-07-22T12:00:00Z",
            "retail_portfolio_id": "11111111-2222-4333-8444-555555555555",
            "limit": 100,
        },
        {
            "product_ids": ["BTC-USDC"],
            "start_sequence_timestamp": "2026-07-22T00:00:00Z",
            "end_sequence_timestamp": "2026-07-22T12:00:00Z",
            "retail_portfolio_id": "11111111-2222-4333-8444-555555555555",
            "limit": 100,
            "cursor": "page-2",
        },
    ]


def test_fill_catalog_reader_rejects_repeated_cursor_without_another_call() -> None:
    client = _RestClient(
        [
            {"fills": [], "cursor": "repeat", "has_next": True},
            {"fills": [], "cursor": "repeat", "has_next": True},
        ]
    )
    selector = FillInventoryCatalogSelector(
        selector_type=FillInventoryRepairSelectorType.PRODUCT,
        product_id="BTC-USDC",
        portfolio_id_sha256=_PORTFOLIO_HASH,
    )

    with pytest.raises(ValueError, match="fill_inventory_cursor_repeated"):
        read_operator_fill_catalog(
            client,
            selector=selector,
            retail_portfolio_id="11111111-2222-4333-8444-555555555555",
            resolve_system_order=lambda *_: None,
        )

    assert len(client.calls) == 2


def test_fill_catalog_reader_matches_the_pinned_sdk_get_fills_contract() -> None:
    parameters = inspect.signature(RESTClient.get_fills).parameters
    assert {
        "order_ids",
        "product_ids",
        "start_sequence_timestamp",
        "end_sequence_timestamp",
        "retail_portfolio_id",
        "limit",
        "cursor",
    }.issubset(parameters)

    client = _RestClient([{"fills": [], "has_next": False}])
    selector = FillInventoryCatalogSelector(
        selector_type=FillInventoryRepairSelectorType.EXACT_ORDER,
        product_id="BTC-USDC",
        client_order_id=_CLIENT_ORDER_ID,
        exchange_order_id="private-exchange-order",
        portfolio_id_sha256=_PORTFOLIO_HASH,
    )
    read_operator_fill_catalog(
        client,
        selector=selector,
        retail_portfolio_id="11111111-2222-4333-8444-555555555555",
        resolve_system_order=lambda *_: None,
    )

    assert client.calls == [
        {
            "order_ids": ["private-exchange-order"],
            "product_ids": ["BTC-USDC"],
            "retail_portfolio_id": (
                "11111111-2222-4333-8444-555555555555"
            ),
            "limit": 100,
        }
    ]


def test_fill_catalog_reader_accepts_pinned_sdk_string_quote_size() -> None:
    response = ListFillsResponse(
        {
            "fills": [
                {
                    "entry_id": "entry-quote-size",
                    "trade_id": "trade-quote-size",
                    "order_id": "order-quote-size",
                    "trade_time": "2026-07-22T01:00:00Z",
                    "price": "100",
                    "size": "1",
                    "commission": "0.01",
                    "product_id": "BTC-USDC",
                    "side": "BUY",
                    "size_in_quote": "true",
                }
            ],
            "cursor": "",
            "has_next": False,
        }
    )
    client = _RestClient([response])  # type: ignore[list-item]
    selector = FillInventoryCatalogSelector(
        selector_type=FillInventoryRepairSelectorType.PRODUCT,
        product_id="BTC-USDC",
        portfolio_id_sha256=_PORTFOLIO_HASH,
    )

    result = read_operator_fill_catalog(
        client,
        selector=selector,
        retail_portfolio_id="11111111-2222-4333-8444-555555555555",
        resolve_system_order=lambda order_id, product_id: {
            "client_order_id": _CLIENT_ORDER_ID,
            "product_id": product_id,
            "portfolio_id_sha256": _PORTFOLIO_HASH,
            "system_owned": order_id == "order-quote-size",
        },
    )

    assert result.entries[0].quantity == "0.01"


def test_fill_catalog_reader_rejects_unsupported_size_mode() -> None:
    client = _RestClient(
        [
            {
                "fills": [
                    {
                        "entry_id": "entry-invalid-mode",
                        "order_id": "order-invalid-mode",
                        "trade_time": "2026-07-22T01:00:00Z",
                        "price": "100",
                        "size": "0.01",
                        "commission": "0.01",
                        "product_id": "BTC-USDC",
                        "side": "BUY",
                        "size_in_quote": "unknown",
                    }
                ],
                "has_next": False,
            }
        ]
    )
    selector = FillInventoryCatalogSelector(
        selector_type=FillInventoryRepairSelectorType.PRODUCT,
        product_id="BTC-USDC",
        portfolio_id_sha256=_PORTFOLIO_HASH,
    )

    with pytest.raises(
        ValueError,
        match="fill_inventory_catalog_size_mode_invalid",
    ):
        read_operator_fill_catalog(
            client,
            selector=selector,
            retail_portfolio_id="11111111-2222-4333-8444-555555555555",
            resolve_system_order=lambda order_id, product_id: {
                "client_order_id": _CLIENT_ORDER_ID,
                "product_id": product_id,
                "portfolio_id_sha256": _PORTFOLIO_HASH,
                "system_owned": order_id == "order-invalid-mode",
            },
        )


def test_projection_entry_rejects_values_the_fill_schema_would_round() -> None:
    with pytest.raises(
        ValueError,
        match="fill_inventory_storage_precision_invalid",
    ):
        _entry(
            identity="f",
            side="BUY",
            quantity="0.000000001",
            price="100",
            fees="0",
            timestamp="2026-07-22T01:00:00Z",
        )


def test_missing_canonical_fill_adapter_does_not_claim_a_refresh_cycle() -> None:
    class _Repository:
        begin_calls = 0

        def begin_refresh(self, **_kwargs):
            self.begin_calls += 1
            raise AssertionError("refresh claim must not be reached")

    repository = _Repository()
    service = OperatorFillInventoryRepairService(
        repository=repository,  # type: ignore[arg-type]
        rest_client=object(),
        rest_client_available=True,
        configured_portfolio_id=(
            "11111111-2222-4333-8444-555555555555"
        ),
    )

    with pytest.raises(
        ValueError,
        match="fill_inventory_catalog_unavailable",
    ):
        service.refresh_case(
            case_id="0d756620-2ce5-4fd3-a24a-a14c4d8bf3c1",
            expected_revision=1,
            actor_id="operator",
            correlation_id="missing-adapter",
            manual_live_acknowledgement=True,
        )
    assert repository.begin_calls == 0


def test_fifo_projection_rebuilds_lots_cost_basis_and_operational_pnl() -> None:
    projection = build_fill_inventory_projection(
        product_id="BTC-USDC",
        entries=[
            _entry(
                identity="a",
                side="BUY",
                quantity="1",
                price="100",
                fees="1",
                timestamp="2026-07-22T01:00:00Z",
            ),
            _entry(
                identity="b",
                side="BUY",
                quantity="1",
                price="120",
                fees="1",
                timestamp="2026-07-22T02:00:00Z",
            ),
            _entry(
                identity="c",
                side="SELL",
                quantity="1.5",
                price="130",
                fees="1.5",
                timestamp="2026-07-22T03:00:00Z",
            ),
        ],
    )

    assert Decimal(projection.open_quantity) == Decimal("0.5")
    assert Decimal(projection.average_cost_basis) == Decimal("121")
    assert Decimal(projection.realized_operational_pnl) == Decimal("32")
    assert Decimal(projection.total_fees) == Decimal("3.5")
    assert projection.open_lot_count == 1
    assert Decimal(projection.lots[0].remaining_quantity) == Decimal("0.5")


def test_public_event_rejects_raw_or_private_evidence() -> None:
    with pytest.raises(ValueError, match="fill_inventory_event_evidence"):
        OperatorFillInventoryRepairEventItem(
            event_id="1b81ae1a-b569-49c0-8c45-09350778e89a",
            case_id="0d756620-2ce5-4fd3-a24a-a14c4d8bf3c1",
            event_type="CATALOG_REFRESH_FAILED",
            actor_id="withheld",
            correlation_id="fill-repair-correlation",
            evidence={"raw_response": "must-not-render"},
            recorded_at="2026-07-23T08:01:00Z",
        )


def test_hashed_import_identity_satisfies_reconciled_fill_health_evidence() -> None:
    report = analyze_spot_fill_ledger_rows(
        rows=[
            {
                "id": 1,
                "derived_trade_key": "derived",
                "exchange_trade_id": None,
                "exchange_entry_id": None,
                "exchange_fill_identity_sha256": "a" * 64,
                "client_order_id": _CLIENT_ORDER_ID,
                "instrument": "BTC-USDC",
                "side": "BUY",
                "quantity": "0.01",
                "price": "100",
                "fees": "0.01",
                "reconciliation_status": "RECONCILED",
            }
        ],
    )

    assert report["status"] == "passed"
    assert report["finding_count"] == 0
