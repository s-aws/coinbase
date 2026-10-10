# Coinbase WebSocket Reference Fixtures

Inventory reconciled on 2026-10-09. These are stored examples and fixture
contracts, not a live Coinbase specification. Presence does not prove current
endpoint support, subscription validity, runtime routing, or coverage.

Use [the current local API contract](../genai_data/API_REFERENCE.md) and
[the WebSocket integration reference](../docs/COINBASE_WEBSOCKET_REFERENCE.md)
for project behavior. External execution follows
[the runbook](../docs/EXTERNAL_TESTING_RUNBOOK.md).

## Stored files

| Path | Top-level JSON keys |
| --- | --- |
| [authenticated/futures_balance_summary_message.json](authenticated/futures_balance_summary_message.json) | `caution`, `channel`, `description`, `example`, `field_descriptions`, `integration_strategy`, `key_metrics_for_bot`, `margin_level_types`, `margin_window_types`, `message_type`, `response_structure`, `risk_management_thresholds` |
| [authenticated/futures_balance_summary_subscription.json](authenticated/futures_balance_summary_subscription.json) | `channel`, `description`, `important`, `notes`, `related_channels`, `requires_authentication`, `send_interval`, `subscription_request`, `unsubscribe_request`, `use_case` |
| [authenticated/user_message.json](authenticated/user_message.json) | `channel`, `description`, `example`, `integration_with_bot`, `key_fields_for_trading_bot`, `message_type`, `message_types`, `order_status_lifecycle`, `positions_note`, `response`, `snapshot_completion` |
| [authenticated/user_subscription.json](authenticated/user_subscription.json) | `authentication_note`, `channel`, `description`, `important`, `initial_snapshot`, `notes`, `requires_authentication`, `send_interval`, `subscription_request`, `unsubscribe_request`, `use_case` |
| [public/candles_message.json](public/candles_message.json) | `channel`, `description`, `example`, `field_descriptions`, `integration`, `message_type`, `message_types`, `response_structure`, `timestamp_note` |
| [public/candles_subscription.json](public/candles_subscription.json) | `channel`, `description`, `notes`, `product_id_examples`, `requires_authentication`, `send_interval`, `subscription_request`, `unsubscribe_request`, `use_case` |
| [public/heartbeats_message.json](public/heartbeats_message.json) | `channel`, `description`, `example`, `field_descriptions`, `integration`, `message_type`, `notes`, `response_structure`, `send_interval` |
| [public/heartbeats_subscription.json](public/heartbeats_subscription.json) | `channel`, `description`, `notes`, `recommended_frequency`, `requires_authentication`, `subscription_request`, `unsubscribe_request`, `use_case` |
| [public/level2_message.json](public/level2_message.json) | `channel`, `description`, `example`, `field_descriptions`, `implementation_example`, `important_notes`, `integration`, `message_type`, `processing_strategy`, `response` |
| [public/level2_subscription.json](public/level2_subscription.json) | `channel`, `description`, `important`, `message_flow`, `notes`, `product_id_examples`, `requires_authentication`, `send_interval`, `subscription_request`, `unsubscribe_request`, `use_case` |
| [public/market_trades_message.json](public/market_trades_message.json) | `batching_behavior`, `channel`, `description`, `example`, `example_update_multiple_trades`, `field_descriptions`, `integration_notes`, `message_type`, `response_structure`, `send_interval`, `side_explanation`, `use_cases` |
| [public/market_trades_subscription.json](public/market_trades_subscription.json) | `batching`, `channel`, `description`, `notes`, `product_id_examples`, `requires_authentication`, `send_interval`, `subscription_request`, `unsubscribe_request`, `use_case` |
| [public/status_message.json](public/status_message.json) | `channel`, `description`, `example`, `field_descriptions`, `integration`, `message_type`, `response_structure`, `status_values` |
| [public/status_subscription.json](public/status_subscription.json) | `channel`, `description`, `notes`, `product_id_examples`, `requires_authentication`, `send_interval`, `subscription_request`, `unsubscribe_request`, `use_case`, `warning` |
| [public/ticker_batch_message.json](public/ticker_batch_message.json) | `channel`, `description`, `example`, `field_descriptions`, `fields_excluded_vs_ticker`, `integration`, `message_type`, `response_structure`, `send_interval`, `use_cases` |
| [public/ticker_batch_subscription.json](public/ticker_batch_subscription.json) | `channel`, `description`, `differences_from_ticker`, `notes`, `product_id_examples`, `requires_authentication`, `send_interval`, `subscription_request`, `unsubscribe_request`, `use_case` |
| [public/ticker_message.json](public/ticker_message.json) | `bid_ask_spread`, `channel`, `description`, `example`, `field_descriptions`, `high_frequency`, `integration`, `message_type`, `response`, `send_interval` |
| [public/ticker_subscription.json](public/ticker_subscription.json) | `channel`, `comparison_to_ticker_batch`, `description`, `notes`, `product_id_examples`, `requires_authentication`, `send_interval`, `subscription_request`, `unsubscribe_request`, `use_case` |

## Reuse and updates

Read the exact file before reusing its schema/example. The external contract
tests commonly read an `example` member, while WebSocket references may carry
channel/auth/message metadata. Verify the source and test expectations rather
than assuming all files use one format.

Update fixtures only from reviewed endpoint/schema evidence or an intentional
test-contract change. Avoid committing captured credentials or account data.
Run the complete local gate in [tests/README.md](../tests/README.md); focused
test selections and external network runs require their documented opt-in.
