"""Smoke test for stealth-specific order event stream emissions via hook integration."""

from business.order_event_stream import OrderEventStreamPublisher
from integration.order_placement_hooks import OrderPlacementHookRegistry
from database import order as db_order


def main() -> None:
    placement_hooks = OrderPlacementHookRegistry()

    publisher = OrderEventStreamPublisher(db_order)
    publisher.register_hook_integrations(
        websocket_hooks=None,
        fill_event_hooks=None,
        order_placement_hooks=placement_hooks,
    )

    stealth_order = {
        "client_order_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "stealth_order_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "parent_order_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "product_id": "BTC-USDC",
        "side": "SELL",
        "limit_price": "100100.00",
        "base_size": "0.01000000",
        "reason": "follow_up_replacement",
        "reveal_number": 1,
        "reveal_condition_type": "price",
        "reveal_condition_json": {
            "type": "price",
            "direction": "above",
            "price_threshold": 100100.0,
            "hold_duration_seconds": 0,
        },
        "condition_confirmed_at": "2026-04-24T10:00:00",
    }

    placement_hooks.call_pre_submission_hooks(stealth_order)
    placement_hooks.call_post_submission_hooks(
        stealth_order,
        {"success_response": {"order_id": "cccccccc-cccc-cccc-cccc-cccccccccccc"}},
    )

    rows = db_order.DB_CLIENT.execute_query(
        """
        SELECT event_type, source_channel, client_order_id, stealth_order_id
        FROM order_event_stream
        WHERE client_order_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        ORDER BY id DESC
        LIMIT 10
        """
    )

    print(f"Inserted stealth events: {len(rows)}")
    for row in rows:
        print(row)


if __name__ == "__main__":
    main()
