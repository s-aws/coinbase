# Coinbase REST Reference Fixtures

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
| [accounts/get_account_request.json](accounts/get_account_request.json) | `authentication`, `description`, `endpoint`, `headers`, `method`, `notes`, `path_parameters` |
| [accounts/get_account_response.json](accounts/get_account_response.json) | `description`, `endpoint`, `example`, `method`, `response`, `status_codes` |
| [accounts/list_accounts_request.json](accounts/list_accounts_request.json) | `authentication`, `description`, `endpoint`, `headers`, `method`, `notes`, `query_parameters` |
| [accounts/list_accounts_response.json](accounts/list_accounts_response.json) | `description`, `endpoint`, `example`, `method`, `response`, `status_codes` |
| [conversions/convert_request.json](conversions/convert_request.json) | `authentication`, `description`, `endpoint`, `headers`, `method`, `notes`, `request_body` |
| [conversions/convert_response.json](conversions/convert_response.json) | `description`, `endpoint`, `example`, `method`, `response`, `status_codes` |
| [fees/get_fees_request.json](fees/get_fees_request.json) | `authentication`, `description`, `endpoint`, `headers`, `method`, `notes`, `project_filtered_requests`, `query_parameters`, `wrapper`, `wrapper_behavior` |
| [fees/get_fees_response.json](fees/get_fees_response.json) | `description`, `endpoint`, `fee_manager_consumption`, `fixed_cde_cost_scope`, `method`, `response`, `sanitized_example`, `status_codes` |
| [orders/cancel_order_request.json](orders/cancel_order_request.json) | `authentication`, `description`, `endpoint`, `headers`, `method`, `notes`, `path_parameters` |
| [orders/cancel_order_response.json](orders/cancel_order_response.json) | `description`, `endpoint`, `example`, `method`, `response`, `status_codes` |
| [orders/create_order_request.json](orders/create_order_request.json) | `authentication`, `description`, `endpoint`, `headers`, `method`, `notes`, `request_body` |
| [orders/create_order_response.json](orders/create_order_response.json) | `description`, `endpoint`, `example`, `method`, `response`, `status_codes` |
| [orders/list_fills_request.json](orders/list_fills_request.json) | `authentication`, `description`, `endpoint`, `headers`, `method`, `notes`, `query_parameters` |
| [orders/list_fills_response.json](orders/list_fills_response.json) | `description`, `endpoint`, `example`, `method`, `response`, `status_codes` |
| [orders/list_orders_request.json](orders/list_orders_request.json) | `authentication`, `description`, `endpoint`, `headers`, `method`, `notes`, `query_parameters` |
| [orders/list_orders_response.json](orders/list_orders_response.json) | `description`, `endpoint`, `example`, `method`, `response`, `status_codes` |
| [perpetuals/list_perpetual_orders_request.json](perpetuals/list_perpetual_orders_request.json) | `authentication`, `description`, `endpoint`, `headers`, `method`, `notes`, `query_parameters` |
| [perpetuals/list_perpetual_orders_response.json](perpetuals/list_perpetual_orders_response.json) | `description`, `endpoint`, `method`, `response`, `status_codes` |
| [perpetuals/list_perpetual_positions_request.json](perpetuals/list_perpetual_positions_request.json) | `authentication`, `description`, `endpoint`, `headers`, `method`, `notes`, `query_parameters` |
| [perpetuals/list_perpetual_positions_response.json](perpetuals/list_perpetual_positions_response.json) | `description`, `endpoint`, `example`, `method`, `response`, `status_codes` |
| [portfolios/get_portfolio_request.json](portfolios/get_portfolio_request.json) | `authentication`, `description`, `endpoint`, `headers`, `method`, `notes`, `path_parameters` |
| [portfolios/get_portfolio_response.json](portfolios/get_portfolio_response.json) | `description`, `endpoint`, `example`, `method`, `response`, `status_codes` |
| [portfolios/list_portfolios_request.json](portfolios/list_portfolios_request.json) | `authentication`, `description`, `endpoint`, `headers`, `method`, `notes`, `query_parameters` |
| [portfolios/list_portfolios_response.json](portfolios/list_portfolios_response.json) | `description`, `endpoint`, `method`, `response`, `status_codes` |
| [products/get_candles_request.json](products/get_candles_request.json) | `authentication`, `description`, `endpoint`, `headers`, `method`, `notes`, `path_parameters`, `query_parameters` |
| [products/get_candles_response.json](products/get_candles_response.json) | `description`, `endpoint`, `example`, `method`, `response`, `status_codes` |
| [products/get_product_request.json](products/get_product_request.json) | `authentication`, `description`, `endpoint`, `headers`, `method`, `notes`, `path_parameters` |
| [products/get_product_response.json](products/get_product_response.json) | `description`, `endpoint`, `example`, `method`, `response`, `status_codes` |
| [products/list_products_request.json](products/list_products_request.json) | `authentication`, `description`, `endpoint`, `headers`, `method`, `notes`, `query_parameters` |
| [products/list_products_response.json](products/list_products_response.json) | `description`, `endpoint`, `example`, `method`, `response`, `status_codes` |

## Reuse and updates

Read the exact file before reusing its schema/example. The external contract
tests commonly read an `example` member, while WebSocket references may carry
channel/auth/message metadata. Verify the source and test expectations rather
than assuming all files use one format.

Update fixtures only from reviewed endpoint/schema evidence or an intentional
test-contract change. Avoid committing captured credentials or account data.
Run the complete local gate in [tests/README.md](../tests/README.md); focused
test selections and external network runs require their documented opt-in.
