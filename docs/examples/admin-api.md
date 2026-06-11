# Admin API Examples

These examples describe the current enterprise Admin API contract. Mutating
HTTP endpoints are authenticated, permission-checked, idempotent, and audited,
then return `not_implemented`; they do not call Coinbase. Read-only spot
operator endpoints are available behind the same fail-closed auth dependency.

## Bootstrap And Session

Start the local backend target for frontend development:

```powershell
python tools\run_admin_api.py --dev-token local-admin-token
```

The runner binds `http://127.0.0.1:8787` by default and keeps mutating HTTP
routes live-disabled.

For frontend integration, set CORS to the exact local frontend origin:

```powershell
$env:COINBASE_ADMIN_API_CORS_ORIGINS = "http://127.0.0.1:3000"
```

The CORS contract is origin-allowlisted and permits `X-CSRF-Token` for
cookie/session or BFF bridge deployments. Current bearer-token bootstrap still
fails closed unless `COINBASE_ADMIN_API_BEARER_TOKEN` is configured on the
backend. When `COINBASE_ADMIN_API_CSRF_REQUIRED=true`, mutating `/api/v1/`
requests must include `X-CSRF-Token` matching
`COINBASE_ADMIN_API_CSRF_TOKEN`; read-only `GET` routes do not require it.

Use bootstrap and session reads to render environment, backend association,
live-action posture, and backend RBAC evidence. These routes do not require
idempotency headers and do not run Coinbase orders.
The active local verifier mode is `bootstrap_bearer`; configuring
`COINBASE_ADMIN_API_AUTH_MODE=oidc_jwt` currently fails closed until a
production verifier is implemented.

```powershell
Invoke-RestMethod `
  -Uri http://127.0.0.1:8787/api/v1/admin/bootstrap `
  -Headers @{
    Authorization = "Bearer local-admin-token"
    "X-Admin-Actor" = "viewer-001"
    "X-Admin-Roles" = "viewer"
  }
```

```http
GET /api/v1/admin/bootstrap
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Expected posture fields:

```json
{
  "type": "admin_bootstrap",
  "backend_repository": "s-aws/coinbase",
  "mutating_routes_live_disabled": true,
  "live_execution_enabled": false,
  "live_coinbase_orders_ran": false
}
```

```http
GET /api/v1/admin/session
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: trader-001
X-Admin-Roles: trader
```

The session response includes `actor`, `roles`, `permissions`, and
`bearer_token_visible_to_browser=false`.

```http
GET /api/v1/admin/csrf
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

This route returns the CSRF header name, whether CSRF is required, and the
token source/rotation policy. It never returns the token value.

## Cancel By Client Order ID

Current skeleton shape:

```http
POST /api/v1/orders/{client_order_id}/cancel
Authorization: Bearer <backend-verifiable-token>
Idempotency-Key: 018f1a2b-4b9c-7e20-9d39-7d6c4a5f1082
X-Correlation-Id: corr-20260610-001
X-Operator-Intent: operator_cancel
X-Admin-Actor: operator-001
X-Admin-Roles: trader
X-CSRF-Token: <configured-csrf-token-when-required>
```

Current backend behavior:

- parse the request through FastAPI/Pydantic
- authenticate actor and authorize `order:cancel`
- evaluate durable idempotency
- call the shared command service with HTTP live execution disabled
- write durable command audit evidence
- return `501` with `status: "not_implemented"`
- never call Coinbase

Future live execution must call the project Coinbase wrapper
`cancel_order(client_order_id)` after rate/cap policy is complete. The wrapper
must parse Coinbase cancel payloads and accept only explicit `success: true`
evidence as a successful exchange cancellation.

## Order Reads

Order reads are local/backend evidence routes. They are keyed by
`client_order_id`; exchange-native ids are exposed only as `exchange_order_id`
evidence.

```http
GET /api/v1/orders?product_id=BTC-USDC&order_status=OPEN&limit=50&offset=0
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

```http
GET /api/v1/orders/{client_order_id}
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

The response model does not contain an `order_id` identity field. If exchange
evidence is known, it appears as `exchange_order_id` with
`exchange_order_id_evidence_only=true`. List responses include pagination
metadata: `limit`, `offset`, `returned_count`, `total_matching_count`,
`next_offset`, and `has_more`.

## Live Placement Approval

Current skeleton shape:

```json
{
  "product_id": "BTC-USDC",
  "side": "BUY",
  "order_type": "LIMIT",
  "quote_size": "1.00",
  "limit_price": "65000.00",
  "manual_live_acknowledgement": true
}
```

Required headers for that placement include:

```http
Authorization: Bearer <backend-verifiable-token>
Idempotency-Key: 018f1a2b-4b9c-7e20-9d39-7d6c4a5f1083
X-Correlation-Id: corr-20260610-002
X-Operator-Intent: manual_one_off
X-Admin-Actor: trader-001
X-Admin-Roles: trader
X-CSRF-Token: <configured-csrf-token-when-required>
```

Current backend behavior:

- parse the request through FastAPI/Pydantic
- authenticate actor and authorize `order:create`
- evaluate durable idempotency
- write durable command audit evidence
- return `501` with `status: "not_implemented"`
- never call Coinbase

Future backend behavior:

- validate product capability and size
- run action-condition guards
- enforce live caps
- create or verify an approval snapshot
- mint one `client_order_id`
- persist idempotency and audit state
- submit to Coinbase only after all gates pass

## Campaign Execution Command

Campaign execution is now a backend-owned command route, but live execution is
still disabled.

```http
POST /api/v1/spot/campaign/executions
Authorization: Bearer <backend-verifiable-token>
Idempotency-Key: 018f1a2b-4b9c-7e20-9d39-7d6c4a5f1084
X-Correlation-Id: corr-20260610-003
X-Operator-Intent: campaign_execute
X-Admin-Actor: trader-001
X-Admin-Roles: trader
Content-Type: application/json
X-CSRF-Token: <configured-csrf-token-when-required>
```

```json
{
  "campaign_id": "usdc-sweep-001",
  "side": "BUY",
  "quote_notional_per_product": "1.00",
  "product_ids": ["BTC-USDC", "ETH-USDC"],
  "dry_run": false,
  "manual_live_acknowledgement": true
}
```

Current response behavior:

- authorize `campaign:execute`
- evaluate idempotency
- write command audit evidence
- return `501` with `service_method: "execute_spot_campaign"`
- include approval/cap guard evidence
- never call Coinbase

## Idempotent Retry

If the same `Idempotency-Key` and same payload are sent again, the API should
return the original command result without minting a second `client_order_id`
or submitting a second Coinbase order.

If the same `Idempotency-Key` is reused with a different payload, the API
should return conflict.

## Read-Only Spot Operator Routes

Read-only routes require `Authorization`, `X-Admin-Actor`, and
`X-Admin-Roles`. They do not require `Idempotency-Key`.
Missing or invalid auth returns `401`; insufficient role evidence returns
`403`.

```http
GET /api/v1/spot/readiness?product_id=BTC-USDC
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Current read-only routes:

- `GET /api/v1/admin/bootstrap`
- `GET /api/v1/admin/health`
- `GET /api/v1/admin/session`
- `GET /api/v1/admin/capabilities`
- `GET /api/v1/admin/csrf`
- `GET /api/v1/admin/release-gate`
- `GET /api/v1/admin/recovery-gate`
- `GET /api/v1/admin/fill-ledger-health`
- `GET /api/v1/admin/frontend-fixtures`
- `GET /api/v1/orders`
- `GET /api/v1/orders/{client_order_id}`
- `GET /api/v1/spot/readiness`
- `GET /api/v1/spot/sweep/status`
- `GET /api/v1/spot/sweep/pnl`
- `GET /api/v1/spot/cost-basis/status`
- `GET /api/v1/spot/campaign/status`
- `GET /api/v1/spot/direct-orders/{client_order_id}/audit`

## Structured Errors

Auth, RBAC, and validation errors return JSON bodies shaped for frontend
display:

```json
{
  "code": "auth_required",
  "message": "Invalid Admin API bearer token",
  "severity": "warning",
  "correlation_id": "corr-20260610-004",
  "live_coinbase_orders_ran": false
}
```

Every response includes `X-Correlation-Id`, `X-Request-Id`,
`X-Admin-Api-Version`, and `X-Live-Execution-Enabled`.

## Frontend Smoke Commands

From `C:\coinbase-frontend`, use dry-run smoke commands to validate the route
inventory without contacting a live backend:

```powershell
npm run smoke:read:dry
npm run smoke:command:dry
npm run smoke:bff:dry
npm run release:check
npm run release:artifact
```

Against a local Admin API, configure `ADMIN_API_BASE_URL`,
`ADMIN_API_BEARER_TOKEN`, `ADMIN_API_ACTOR`, and `ADMIN_API_ROLES`. If backend
CSRF is required, also configure `ADMIN_API_CSRF_TOKEN`, then run:

```powershell
npm run smoke:read
npm run smoke:command
```

The command smoke expects `501` live-disabled responses and reports live
Coinbase execution as not run with notional `$0`.

For same-origin BFF smoke, start the frontend with `NEXT_PUBLIC_ADMIN_API_MODE=bff`
and server-only `ADMIN_API_*` variables, then run:

```powershell
$env:FRONTEND_BASE_URL = "http://127.0.0.1:3000"
npm run smoke:bff
```

BFF smoke reads through `/api/admin/api/v1/...` and posts to BFF command
routes expecting backend `501` live-disabled responses. It must report live
Coinbase execution as not run with notional `$0`.

The BFF copies only documented response-evidence headers back to browser code:
`Content-Type`, `X-Correlation-Id`, `X-Request-Id`,
`X-Admin-Api-Version`, `X-Live-Execution-Enabled`, and
`X-Idempotency-Replayed`. Missing BFF server authority should be handled as
`admin_bff_proxy_error`, not as a trading approval or Coinbase execution
failure.
