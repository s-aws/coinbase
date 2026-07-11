"""Focused tests for REST-authoritative Spot fill-ledger conversion."""

from business.spot_fill_backfill import fill_ledger_from_rest_fill


def test_fill_ledger_from_rest_fill_preserves_opaque_non_uuid_trade_id() -> None:
    opaque_trade_id = "trade-67890"

    ledger_row = fill_ledger_from_rest_fill(
        fill={
            "entry_id": "entry-12345",
            "trade_id": opaque_trade_id,
            "order_id": "exchange-order-1",
            "trade_time": "2026-07-11T12:00:00Z",
            "price": "100000.01",
            "size": "0.00001250",
            "commission": "0.00750000",
            "side": "BUY",
            "product_id": "BTC-USDC",
            "size_in_quote": False,
        },
        client_order_id="11111111-2222-4333-8444-555555555555",
        exchange_order_id="exchange-order-1",
        product_id="BTC-USDC",
        side="BUY",
        fallback_index=0,
    )

    assert ledger_row is not None
    assert ledger_row.exchange_trade_id == opaque_trade_id
