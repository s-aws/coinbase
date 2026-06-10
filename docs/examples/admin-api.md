# Admin API Examples

These examples describe the current enterprise Admin API skeleton and the
future behavior that must be implemented behind the shared command service.
The current endpoints return `not_implemented`; they do not call Coinbase.

## Cancel By Client Order ID

Current skeleton shape:

```http
POST /api/v1/orders/{client_order_id}/cancel
Idempotency-Key: 018f1a2b-4b9c-7e20-9d39-7d6c4a5f1082
X-Correlation-Id: corr-20260610-001
Authorization: Bearer <backend-verifiable-token>
```

Current backend behavior:

- parse the request through FastAPI/Pydantic
- call the shared command-service skeleton
- return `not_implemented`
- never call Coinbase

Future backend behavior:

- authenticate actor
- authorize cancel permission
- classify as `live_exchange_cancel`
- call the shared command service
- call the project Coinbase wrapper `cancel_order(client_order_id)`
- write durable audit evidence
- return typed command status

## Live Placement Approval

Current skeleton shape:

```json
{
  "product_id": "BTC-USDC",
  "side": "BUY",
  "order_type": "LIMIT",
  "quote_size": "1.00",
  "limit_price": "65000.00",
  "operator_intent": "manual_one_off",
  "manual_live_acknowledgement": true
}
```

Current backend behavior:

- parse the request through FastAPI/Pydantic
- call the shared command-service skeleton
- return `not_implemented`
- never call Coinbase

Future backend behavior:

- validate product capability and size
- run action-condition guards
- enforce live caps
- create or verify an approval snapshot
- mint one `client_order_id`
- persist idempotency and audit state
- submit to Coinbase only after all gates pass

## Idempotent Retry

If the same `Idempotency-Key` and same payload are sent again, the API should
return the original command result without minting a second `client_order_id`
or submitting a second Coinbase order.

If the same `Idempotency-Key` is reused with a different payload, the API
should return conflict.
