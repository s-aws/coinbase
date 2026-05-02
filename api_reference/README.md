> Documentation status (2026-05-02): **Supplemental (non-canonical active reference)**
> This file is useful operational context but is not the canonical source of truth.
> Canonical living docs remain under genai_data/.
# Coinbase Advanced Trade API Reference Library

This directory contains a structured collection of Coinbase Advanced Trade API REST endpoint request/response schemas. Use this library as a quick reference when developing features or debugging API integrations.

## Directory Structure

```
api_reference/
├── accounts/           # Account management and balance operations
├── orders/            # Order placement, management, and history
├── products/          # Product information and market data
├── portfolios/        # Portfolio management and breakdowns
├── fees/              # Fee schedules and tier information
├── perpetuals/        # Futures/perpetual trading
├── conversions/       # Currency conversion operations
└── README.md          # This file
```

## Naming Convention

Each endpoint is documented with TWO files:

- **`{endpoint_name}_request.json`** - Request parameters, headers, authentication requirements
- **`{endpoint_name}_response.json`** - Response structure, field types, examples, status codes

### Examples

- `list_accounts_request.json` / `list_accounts_response.json`
- `create_order_request.json` / `create_order_response.json`
- `list_perpetual_positions_request.json` / `list_perpetual_positions_response.json`

## File Structure Conventions

### Request Files

Each request file includes:
- **endpoint**: Full endpoint path (GET, POST, etc.)
- **method**: HTTP method (GET, POST, DELETE, etc.)
- **description**: What the endpoint does
- **path_parameters**: Path variables (if any)
- **query_parameters**: Query string parameters with types and descriptions
- **request_body**: POST/PATCH body structure (if applicable)
- **headers**: Required/optional headers
- **authentication**: Authentication type (Bearer token, etc.)
- **notes**: Important usage information

### Response Files

Each response file includes:
- **endpoint**: Full endpoint path
- **method**: HTTP method
- **description**: Response structure details
- **response**: Full response body structure with field descriptions
- **status_codes**: HTTP status codes and meanings
- **example**: Real-world example (when applicable)

## Quick Reference by Category

### Accounts (`accounts/`)
- `list_accounts` - Get all trading accounts
- `get_account` - Get specific account details

### Orders (`orders/`)
- `create_order` - Place a new limit or market order
- `list_orders` - Get historical orders with pagination
- `list_fills` - Get order fill/execution history
- `cancel_order` - Cancel an open order

### Products (`products/`)
- `list_products` - Get all available products
- `get_product` - Get specific product details
- `get_candles` - Get OHLC candlestick data

### Portfolios (`portfolios/`)
- `list_portfolios` - Get all portfolios
- `get_portfolio` - Get portfolio details and breakdown

### Perpetuals/Futures (`perpetuals/`)
- `list_perpetual_orders` - Get open futures orders
- `list_perpetual_positions` - Get active futures positions

### Fees (`fees/`)
- `get_fees` - Get current fee schedule and tier

### Conversions (`conversions/`)
- `convert` - Convert between stablecoin currencies

## Integration Guide

### Using with Your Trading Bot

1. **Order Placement**: Reference `orders/create_order_request.json` for required fields and `orders/create_order_response.json` for expected response structure

2. **Position Tracking**: Use `perpetuals/list_perpetual_positions_response.json` to understand position object structure

3. **Product Info**: Reference `products/get_product_response.json` when building product selection or validation logic

4. **Fee Calculations**: Check `fees/get_fees_response.json` for tier and rate structures

### Example Usage in Code

```python
# From orders/create_order_request.json
order_payload = {
    "client_order_id": "550e8400-e29b-41d4-a716-446655440000",
    "product_id": "BTC-USD",
    "side": "BUY",
    "order_configuration": {
        "limit_order_config": {
            "base_size": "0.25",
            "limit_price": "42500.50",
            "post_only": True
        }
    }
}

# Expected response structure from orders/create_order_response.json
response = {
    "success": True,
    "order_id": "7c4a3d3e-e8f2-4e7a-9c1d-5a6e9f2b8c1d",
    "status": "OPEN",
    # ... see create_order_response.json for full structure
}
```

## Common Field Types

- **string**: Text value
- **integer**: Whole number
- **string (decimal)**: Numeric value as string for precision (common in finance APIs)
- **string (UUID)**: UUID format identifier
- **string (enum)**: One of predefined values (see enum array)
- **string (ISO8601)**: Timestamp in ISO 8601 format (e.g., "2024-01-15T10:30:45.123Z")
- **boolean**: True/False

## Authentication

All endpoints require OAuth2 Bearer token authentication:

```
Authorization: Bearer <access_token>
```

Content-Type is always `application/json`.

## Error Handling

Standard HTTP status codes:
- **200**: Success
- **400**: Bad Request (invalid parameters)
- **401**: Unauthorized (invalid/expired token)
- **403**: Forbidden (insufficient permissions)
- **404**: Not Found (resource doesn't exist)
- **429**: Too Many Requests (rate limit exceeded)

## Pagination

Endpoints that return lists typically support pagination using:
- **limit**: Maximum results per page
- **after** / **before**: Cursor-based pagination
- **has_next**: Boolean indicating more results available

## Rate Limiting

Coinbase Advanced Trade API has rate limits based on:
- Endpoint tier (standard, advanced, etc.)
- User's trading volume tier
- Requests per second

See official Coinbase documentation for current rate limits.

## Updates & Maintenance

This reference library tracks the Coinbase Advanced Trade API v1 specification. Keep files synchronized with:
- https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api
- API changelog for deprecations or new endpoints

## Related Files in Project

- **main.py**: Uses these endpoints via `configuration.py`
- **configuration.py**: REST API implementation with actual HTTP calls
- **order.py**: Order placement helpers
- **database/order.py**: Persists API responses to PostgreSQL

## Next Steps

1. Extend this library with additional endpoints (deposits, withdrawals, etc.)
2. Create webhook/event schemas when adding WebSocket documentation
3. Add error response examples for common failure scenarios
4. Build API client wrapper generation from these schemas


