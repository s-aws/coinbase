"""Smoke test for order event stream hook integration.

This verifies that existing hook registries emit records into order_event_stream.
"""

from business.order_event_stream import OrderEventStreamPublisher
from integration.websocket_hooks import WebSocketHookRegistry
from integration.fill_event_hooks import FillEventHookRegistry
from integration.order_placement_hooks import OrderPlacementHookRegistry
from database import order as db_order


def main() -> None:
    ws_hooks = WebSocketHookRegistry()
    fill_hooks = FillEventHookRegistry()
    placement_hooks = OrderPlacementHookRegistry()

    publisher = OrderEventStreamPublisher(db_order)
    publisher.register_hook_integrations(
        websocket_hooks=ws_hooks,
        fill_event_hooks=fill_hooks,
        order_placement_hooks=placement_hooks,
    )

    # Trigger websocket status hook
    ws_hooks.call_post_order_status(
        "FILLED",
        {
            "client_order_id": "11111111-1111-1111-1111-111111111111",
            "order_id": "22222222-2222-2222-2222-222222222222",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "status": "FILLED",
            "price": "100000.00",
            "filled_size": "0.01000000",
        },
    )

    # Trigger fill post hook
    fill_hooks.call_post_fill_hooks(
        {
            "client_order_id": "11111111-1111-1111-1111-111111111111",
            "instrument": "BTC-USDC",
            "side": "BUY",
            "quantity": 0.01,
            "price": 100000.0,
            "fees": 2.5,
        },
        "33333333-3333-3333-3333-333333333333",
    )

    # Trigger order placement post hook
    placement_hooks.call_post_submission_hooks(
        {
            "client_order_id": "44444444-4444-4444-4444-444444444444",
            "product_id": "BTC-USDC",
            "side": "SELL",
            "limit_price": "100100.00",
            "size": "0.01000000",
        },
        {"success_response": {"order_id": "55555555-5555-5555-5555-555555555555"}},
    )

    rows = db_order.DB_CLIENT.execute_query(
        """
        SELECT event_type, source_channel, client_order_id
        FROM order_event_stream
        WHERE client_order_id IN (
            '11111111-1111-1111-1111-111111111111',
            '44444444-4444-4444-4444-444444444444'
        )
        ORDER BY id DESC
        LIMIT 10
        """
    )
    print(f"Inserted events: {len(rows)}")
    for row in rows:
        print(row)


if __name__ == "__main__":
    main()
