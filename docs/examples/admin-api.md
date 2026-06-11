# Admin API Examples

These examples describe the current enterprise Admin API contract. Mutating
HTTP endpoints are authenticated, permission-checked, idempotent, and audited,
then return `not_implemented`; they do not call Coinbase. Read-only spot
operator endpoints are available behind the same fail-closed auth dependency.

The Admin API is the backend contract layer for the enterprise admin platform.
Spot is the first complete product module. Do not use spot wallet, USDC,
cost-basis, or no-shorting rules as generic admin behavior for
futures/perpetuals, stealth orders, repricing, or risk policy modules.

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
The local bootstrap verifier mode is `bootstrap_bearer`. Production-shaped
OIDC deployments use `COINBASE_ADMIN_API_AUTH_MODE=oidc_jwt`; that mode
verifies RS256 JWTs against configured issuer, audience, and JWKS settings
and derives actor/role evidence from claims.

OIDC/JWT readiness uses these backend environment names:

```powershell
$env:COINBASE_ADMIN_API_AUTH_MODE = "oidc_jwt"
$env:COINBASE_ADMIN_API_OIDC_ISSUER = "https://issuer.example.test"
$env:COINBASE_ADMIN_API_OIDC_AUDIENCE = "coinbase-admin-api"
$env:COINBASE_ADMIN_API_OIDC_JWKS_URL = "https://issuer.example.test/.well-known/jwks.json"
```

Missing values fail closed with `401`. Expected claim mapping is `sub` for
subject, `email` for email, `roles` for roles, `iss` for issuer, and `aud`
for audience. In OIDC mode the backend ignores browser-supplied
`X-Admin-Actor` and `X-Admin-Roles`; those values are derived from verified
JWT claims.

Run the no-live OIDC readiness smoke before treating production OIDC evidence
as available to the frontend release gate:

```powershell
python tools\run_admin_oidc_readiness_smoke.py --summary-only
```

Expected evidence:

- `ADMIN_OIDC_READINESS_SMOKE_SUMMARY` status `passed`
- missing OIDC config blocks
- configured temporary JWKS readiness reports `ready`
- `oidc_jwt` session claims define actor and roles
- live Coinbase execution not run; notional `$0`

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

```http
GET /api/v1/admin/oidc-readiness
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

This route returns backend OIDC verifier evidence for release checks:
active auth mode, required and missing OIDC settings, claim mapping, JWKS
reachability, and no-live notional posture.

## Cancel By Client Order ID

Current live-disabled command shape:

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
If durable row-level audit metadata exists, read items may also include
optional `correlation_id` and `audit_id` fields for operator audit navigation.
Those ids are not order identity and must not be used for cancellation.

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

Frontend read-model interactions over these rows are display-only. Local
filtering, sorting, selected detail panels, responsive table scrolling, and
audit anchors must use backend-shaped row data already loaded through the
Admin API. They must not create a second fetch path, use exchange
`order_id` as identity, or infer wallet/guard/execution authority in the
browser.

## Stealth Order Reads

Stealth reads are local/backend lifecycle evidence routes. They are keyed by
`stealth_order_id`. Active placement client ids and exchange order ids are
evidence fields only; the current enterprise Admin API does not expose stealth
create, cancel, reveal, hide, move, or reprice command routes.

```http
GET /api/v1/stealth/orders?product_id=BTC-USDC&stealth_status=REVEALED&limit=50&offset=0
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

```http
GET /api/v1/stealth/orders/{stealth_order_id}
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

Response rows include lifecycle and policy evidence such as `status`,
`revealed_orders`, `active_placement_client_order_id`,
`active_exchange_order_id`, `cancel_reentry_state`, and
`anchor_repricing_state`. These fields are display evidence for the admin
platform. They must not be used by a frontend to mutate stealth lifecycle
state or cancel a live placement.

## Movement And Repricing Reads

Movement/repricing reads expose existing durable and runtime-safe evidence.
They are not command routes. They do not move parent orders, premark moves,
trigger repricing, cancel Coinbase orders, or replace revealed stealth
placements.

```http
GET /api/v1/movement-repricing/evidence?product_id=BTC-USDC&evidence_type=stealth_repricing_state&limit=50&offset=0
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

```http
GET /api/v1/movement-repricing/orders/{client_order_id}
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

```http
GET /api/v1/movement-repricing/stealth/{stealth_order_id}
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

Response items may include parent move history from `order_moves`, stealth
move audit rows from `stealth_order_moves`, repricing state from
`stealth_orders.anchor_repricing_state_json`, replacement-slot evidence, and
runtime mutation claim evidence when the existing manager state is observable.
Exchange-native ids are exposed as exchange evidence only.

## Futures/Perpetuals Reads

Futures/perpetual reads expose backend-owned account, risk, and position
evidence. They are not command routes. They do not place, close, reduce,
cancel, or liquidate positions.

```http
GET /api/v1/futures/account
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

```http
GET /api/v1/futures/positions?product_id=BIP-20DEC30-CDE&position_side=LONG&limit=50&offset=0
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

```http
GET /api/v1/futures/positions/{position_key}
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: auditor-001
X-Admin-Roles: auditor
```

Account responses separate configured product metadata from observed runtime
position coverage:

- `configured_product_scope`
- `observed_position_scope`

Position rows are keyed by `position_key`. Do not replace that key with spot
wallet identity, `client_order_id`, or Coinbase `order_id`. Close/reduce sides
are backend-derived from observed position side and are not exchange-observed
reduce-only or close-only order flags. Funding-rate evidence is currently
`not_modeled`.

## Guard/Risk Policy Reads

Guard/risk policy reads expose backend-owned policy posture. They are not
command routes and they do not approve live execution, run wallet checks,
calculate profitability in the browser, or contact Coinbase.

```http
GET /api/v1/admin/guard-risk-policy?product_id=BTC-USDC
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

The response includes `action_condition_policy`, `configured_limit_rules`,
`live_execution_gate`, `product_capability_policy`,
`product_capability_decisions`, `profitability_policy`, `authority_sources`,
and `rejection_categories`.

Expected safety posture:

- `read_only=true`
- `command_routes_mode="not_modeled"`
- `live_coinbase_orders_ran=false`
- `live_coinbase_read_ran=false`

Do not use this route as a browser preflight approval endpoint. Actual command
acceptance/rejection remains in the backend command service path.

## Audit Workbench Reads

Audit workbench reads expose backend-owned cross-module evidence. They are not
command routes and they do not mutate audit history, replay commands, call
Coinbase, or approve live execution.

```http
GET /api/v1/admin/audit-workbench?module=orders&client_order_id=client-order-001
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: auditor
```

The response includes `module_summary`, `events`, `filters`, `pagination`,
and no-live posture fields. Order events are keyed by `client_order_id`.
Stealth events use `stealth_order_id`. Futures/perpetual events use
`position_key`. Exchange-native ids appear only as exchange evidence.

Expected safety posture:

- `read_only=true`
- `command_routes_mode="evidence_only"`
- `live_coinbase_orders_ran=false`
- `live_coinbase_read_ran=false`

## Live Placement Approval

Current live-disabled command shape:

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

Read-only routes always require `Authorization`. In `bootstrap_bearer` mode
they also require `X-Admin-Actor` and `X-Admin-Roles`. In `oidc_jwt` mode the
backend derives actor and roles from verified JWT claims and ignores those
bootstrap headers. Read routes do not require `Idempotency-Key`. Missing or
invalid auth returns `401`; insufficient role evidence returns `403`.

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
- `GET /api/v1/admin/oidc-readiness`
- `GET /api/v1/admin/capabilities`
- `GET /api/v1/admin/csrf`
- `GET /api/v1/admin/guard-risk-policy`
- `GET /api/v1/admin/audit-workbench`
- `GET /api/v1/admin/release-gate`
- `GET /api/v1/admin/recovery-gate`
- `GET /api/v1/admin/fill-ledger-health`
- `GET /api/v1/admin/frontend-fixtures`
- `GET /api/v1/orders`
- `GET /api/v1/orders/{client_order_id}`
- `GET /api/v1/stealth/orders`
- `GET /api/v1/stealth/orders/{stealth_order_id}`
- `GET /api/v1/movement-repricing/evidence`
- `GET /api/v1/movement-repricing/orders/{client_order_id}`
- `GET /api/v1/movement-repricing/stealth/{stealth_order_id}`
- `GET /api/v1/futures/account`
- `GET /api/v1/futures/positions`
- `GET /api/v1/futures/positions/{position_key}`
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

From `C:\coinbase-frontend`, use the canonical release-hardening gate to
validate the route inventory, artifact evidence, runtime evidence, autonomous
queue posture, tests, and dry smokes without contacting Coinbase:

```powershell
npm run release:gate
```

Against a local Admin API, configure `ADMIN_API_BASE_URL`,
`ADMIN_API_BEARER_TOKEN`, `ADMIN_API_ACTOR_ID`, and `ADMIN_API_ROLES`. If
backend CSRF is required, also configure `ADMIN_API_CSRF_TOKEN`, then run:

```powershell
npm run smoke:read
npm run smoke:command
```

Direct frontend smoke scripts still accept `ADMIN_API_ACTOR` as a legacy
fallback, but `ADMIN_API_ACTOR_ID` is the canonical actor variable shared with
BFF mode.

The command smoke expects `501` live-disabled responses and reports live
Coinbase execution as not run with notional `$0`.

The frontend release artifact bundle includes:

- `artifacts/release-readiness.json`
- `artifacts/deployment-package-manifest.json`
- `artifacts/observability-drill.json`
- `artifacts/synthetic-probes.json`
- `artifacts/public-release-checklist.json`
- `artifacts/runtime-evidence.json`

Those artifacts are no-live deployment evidence. They are not approval for
live Coinbase execution and not backend approval to place or cancel Coinbase
orders.
The autonomous queue remains part of the no-live release gate, and these
artifacts are not approval for live Coinbase execution.

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

The frontend deployment package manifest and observability drill are no-live
evidence artifacts. `server_env_static` BFF authority is local/staging evidence
only; production readiness is conditional on frontend `backend_oidc_jwt` BFF
mode and backend `oidc_jwt` verifier configuration.
