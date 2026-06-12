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

```http
GET /api/v1/admin/capabilities
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Command capability rows are derived from `ADMIN_API_ROUTE_INVENTORY` and
include `action_class`, `permission`, `shared_method`, `idempotency`,
`approval`, `caps`, `audit`, `command_contract`, and `parity_test`. They are
metadata for frontend validation and diagnostics only; they do not enable live
Coinbase execution. `frontend_safe=true` means the row is safe for Admin
frontend/BFF contract exposure under backend authority, not that the command
is safe or approved for live trading.

The checked-in export
`openapi/coinbase-admin-api-route-inventory.json` is generated from the same
inventory and is the artifact consumed by frontend route-coverage checks.
Each route inventory artifact row includes `module_id`; frontend checks use it
to prove route ownership, not to authorize browser-side trading behavior.

```http
GET /api/v1/admin/live-enablement
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Expected M8 readiness posture:

```json
{
  "type": "admin_live_enablement",
  "status": "live_disabled",
  "approved_phase_range": "1001-1020",
  "default_live_coinbase_execution": "not_run",
  "submitted_notional_usdc": "0",
  "executed_notional_usdc": "0",
  "quote_currency": "USDC",
  "product_scope": "cheapest Coinbase USDC spot product available to US customers",
  "max_submitted_notional_usdc": "3.10",
  "max_executed_notional_usdc": "1.00",
  "retain_inventory": true,
  "reconciliation_required": true,
  "live_enabled_path_count": 0,
  "live_eligible_path_count": 0,
  "paths": [
    {
      "path_id": "post.api.v1.orders",
      "route": "/api/v1/orders",
      "method": "POST",
      "module": "spot",
      "action_class": "live_exchange_place",
      "required_permission": "order:create",
      "shared_method": "place_manual_order",
      "live_enabled": false,
      "live_eligible": false,
      "status": "live_disabled",
      "approval_required": true,
      "cap_required": true,
      "guard_required": true,
      "audit_required": true,
      "reconciliation_required": true,
      "product_scope": "cheapest Coinbase USDC spot product available to US customers",
      "max_submitted_notional_usdc": "3.10",
      "max_executed_notional_usdc": "1.00",
      "evidence": [
        "M4 guard/risk evidence required",
        "M6 command contract proof required",
        "M8 explicit live approval required",
        "post-live reconciliation required"
      ],
      "notes": "Current Admin API command contract is live-disabled; this read route is eligibility evidence only."
    }
  ],
  "checks": [
    {
      "name": "live_execution_default",
      "status": "passed",
      "detail": "Default live Coinbase execution is not_run with submitted/executed notional $0."
    },
    {
      "name": "reconciliation_gate",
      "status": "blocked",
      "detail": "No path is live-enabled until post-live reconciliation evidence is wired for that path."
    }
  ],
  "read_only": true,
  "live_coinbase_orders_ran": false
}
```

This route is evidence only. It lists command paths that could later be
considered for controlled live enablement, but every current path remains
`live_enabled=false` until explicit live approval, cap, guard, audit, and
reconciliation gates pass.

```http
GET /api/v1/admin/enterprise-readiness
Authorization: Bearer <backend-verifiable-token>
X-Admin-Actor: viewer-001
X-Admin-Roles: viewer
```

Expected M9/M21/M23/M24 enterprise readiness posture:

```json
{
  "type": "admin_enterprise_readiness",
  "candidate": "enterprise_admin_m9",
  "approved_phase_range": "1001-1020",
  "status": "warning",
  "supported_module_count": 7,
  "unsupported_module_count": 1,
  "command_gap_count": 17,
  "module_registry_count": 8,
  "module_action_posture_count": 8,
  "modules": [
    {
      "module_id": "spot_operations",
      "module": "Spot Operations",
      "primary_owner": "strategy",
      "support_status": "command_draft_live_disabled",
      "unsupported_actions": [
        "spot short selling",
        "browser-side wallet or cost-basis authority",
        "frontend live order placement without backend M8 approval"
      ],
      "command_gaps": [
        {
          "action": "spot short selling",
          "status": "unsupported",
          "reason": "Spot accounts cannot sell assets the account does not hold.",
          "required_backend_contract": "No backend contract should enable spot short selling; spot sell authority remains inventory-backed.",
          "frontend_boundary": "Do not model a spot short draft or bypass backend wallet and inventory authority.",
          "live_coinbase_execution": "not_run",
          "notional_usdc": "0"
        }
      ],
      "identity_keys": ["client_order_id"],
      "backend_contract_refs": [
        "business/spot_portfolio_sweep.py",
        "business/spot_inventory_authority.py",
        "application/admin_api/command_service.py",
        "api/v1/routes/spot.py"
      ],
      "frontend_contract_refs": [
        "src/shared/api/contracts/backendApiClient.ts::getSpotReadiness",
        "src/shared/api/contracts/backendApiClient.ts::executeSpotCampaign",
        "src/features/spot-ops/spotBackendAdapters.ts"
      ],
      "documentation_refs": [
        "README.spot-trading.md",
        "README.spot-portfolio-sweep.md",
        "README.spot-campaign.md",
        "docs/examples/admin-api.md"
      ],
      "spot_rule_boundary": "Spot rules apply here only: no short selling, USDC spot scope, inventory authority, cost basis, and average-cost evidence must not be copied into non-spot modules.",
      "action_posture": {
        "module_id": "spot_operations",
        "support_status": "command_draft_live_disabled",
        "read_route_count": 8,
        "command_route_count": 3,
        "live_route_count": 3,
        "evidence_route_count": 8,
        "unsupported_action_count": 3,
        "command_gap_count": 2,
        "route_module_id_status": "passed",
        "route_module_id_detail": "11 route inventory rows are bound to module_id=spot_operations; enterprise readiness route lists are derived from module_id, not path prefixes.",
        "frontend_authority": "backend_contract_only",
        "live_coinbase_execution": "not_run",
        "notional_usdc": "0"
      }
    },
    {
      "module_id": "futures_perpetuals",
      "module": "Futures / Perpetuals",
      "primary_owner": "admin_api_contract",
      "support_status": "read_only_ready",
      "unsupported_actions": [
        "frontend futures placement",
        "frontend futures cancel/close/reduce",
        "spot inventory rules in futures workflows"
      ],
      "command_gaps": [
        {
          "action": "frontend futures placement",
          "status": "not_modeled",
          "reason": "Futures/perpetual placement needs backend-owned margin, leverage, liquidation, reduce-only, collateral, and approval contracts before UI drafting.",
          "required_backend_contract": "POST futures/perpetual placement contract with margin, leverage, liquidation, reduce-only, cap, approval, audit, and reconciliation evidence.",
          "frontend_boundary": "Do not add a futures/perpetual placement draft, dry-submit, or BFF route until the backend contract and capability row exist.",
          "live_coinbase_execution": "not_run",
          "notional_usdc": "0"
        }
      ],
      "identity_keys": ["position_key"],
      "backend_contract_refs": [
        "application/admin_api/read_service.py::build_futures_account",
        "application/admin_api/read_service.py::build_futures_positions",
        "api/v1/routes/futures.py"
      ],
      "frontend_contract_refs": [
        "src/shared/api/contracts/backendApiClient.ts::getFuturesAccount",
        "src/shared/api/contracts/backendRuntime.ts::loadFuturesPerpetualsReadSnapshot",
        "src/features/admin-shell/AdminShell.tsx"
      ],
      "documentation_refs": [
        "README.futures-perpetuals.md",
        "docs/ADMIN_MODULE_CAPABILITY_MATRIX.md",
        "docs/examples/admin-api.md"
      ],
      "spot_rule_boundary": "Spot inventory, USDC, no-shorting, cost-basis, and average-cost rules are forbidden as futures/perpetual authority. Futures require position, margin, leverage, collateral, liquidation, and reduce-only backend contracts.",
      "action_posture": {
        "module_id": "futures_perpetuals",
        "support_status": "read_only_ready",
        "read_route_count": 3,
        "command_route_count": 0,
        "live_route_count": 0,
        "evidence_route_count": 3,
        "unsupported_action_count": 3,
        "command_gap_count": 3,
        "route_module_id_status": "passed",
        "route_module_id_detail": "3 route inventory rows are bound to module_id=futures_perpetuals; enterprise readiness route lists are derived from module_id, not path prefixes.",
        "frontend_authority": "backend_contract_only",
        "live_coinbase_execution": "not_run",
        "notional_usdc": "0"
      }
    },
    {
      "module_id": "legacy_dashboard_websocket",
      "module": "Legacy Dashboard WebSocket",
      "primary_owner": "dashboard_contract",
      "support_status": "unsupported",
      "unsupported_actions": [
        "enterprise frontend direct WebSocket command execution",
        "new admin module implementation through dashboard.py"
      ],
      "command_gaps": [
        {
          "action": "enterprise frontend direct WebSocket command execution",
          "status": "unsupported",
          "reason": "The legacy dashboard WebSocket is compatibility-only and is not the enterprise admin command plane.",
          "required_backend_contract": "Backend-owned Admin API route through auth, RBAC, idempotency, approval, caps, audit, and the shared command service.",
          "frontend_boundary": "Do not call dashboard.py or legacy dashboard WebSocket handlers from enterprise frontend product UI.",
          "live_coinbase_execution": "not_run",
          "notional_usdc": "0"
        }
      ],
      "identity_keys": ["client_order_id"],
      "backend_contract_refs": [
        "dashboard_server.py",
        "docs/LIVE_ORDER_SURFACES.md",
        "application/admin_api/command_service.py"
      ],
      "frontend_contract_refs": [
        "src/shared/api/contracts/adminBffProxy.ts",
        "src/shared/api/contracts/mutationContracts.ts",
        "src/features/command-workflows"
      ],
      "documentation_refs": [
        "docs/ADMIN_PLATFORM_ARCHITECTURE.md",
        "docs/ADMIN_MODULE_CAPABILITY_MATRIX.md",
        "docs/examples/admin-api.md"
      ],
      "spot_rule_boundary": "Legacy dashboard behavior is compatibility-only. Spot rules exposed there are not reusable enterprise frontend authority and must be reintroduced only through Admin API contracts.",
      "action_posture": {
        "module_id": "legacy_dashboard_websocket",
        "support_status": "unsupported",
        "read_route_count": 0,
        "command_route_count": 3,
        "live_route_count": 3,
        "evidence_route_count": 0,
        "unsupported_action_count": 2,
        "command_gap_count": 2,
        "route_module_id_status": "passed",
        "route_module_id_detail": "3 route inventory rows are bound to module_id=legacy_dashboard_websocket; enterprise readiness route lists are derived from module_id, not path prefixes.",
        "frontend_authority": "backend_contract_only",
        "live_coinbase_execution": "not_run",
        "notional_usdc": "0"
      }
    }
  ],
  "security_checks": [
    {
      "name": "browser_authority_boundary",
      "status": "passed",
      "detail": "Enterprise admin frontend/Admin HTTP authority is backend_contract_only; this path does not approve, place, cancel, or reconcile Coinbase orders. Legacy browser live surfaces are compatibility-only and documented in docs/LIVE_ORDER_SURFACES.md."
    }
  ],
  "release_checks": [
    {
      "name": "frontend_release_gate",
      "status": "warning",
      "detail": "Run npm run release:gate after frontend/API changes before release."
    }
  ],
  "frontend_authority": "backend_contract_only",
  "live_posture": "live_disabled",
  "default_live_coinbase_execution": "not_run",
  "submitted_notional_usdc": "0",
  "executed_notional_usdc": "0",
  "read_only": true,
  "live_coinbase_orders_ran": false
}
```

This route is module and release-candidate evidence only. Warning release
checks mean the external gate still has to be run; they are not browser-side
approval or live execution authority.

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
Content-Type: application/json

{"reason":"operator_requested_cancel"}
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

## Stealth Cancel By Stealth Order ID

Current live-disabled command shape:

```http
POST /api/v1/stealth/orders/{stealth_order_id}/cancel
Authorization: Bearer <backend-verifiable-token>
Idempotency-Key: 018f1a2b-4b9c-7e20-9d39-7d6c4a5f1083
X-Correlation-Id: corr-20260610-002
X-Operator-Intent: operator_stealth_cancel
X-Admin-Actor: operator-001
X-Admin-Roles: trader
X-CSRF-Token: <configured-csrf-token-when-required>
```

Current backend behavior:

- parse the request through FastAPI/Pydantic
- authenticate actor and authorize `order:cancel`
- evaluate durable idempotency
- call the shared command service with HTTP live execution disabled
- write durable command audit evidence with `stealth_order_id`
- return `501` with `status: "not_implemented"`
- never call Coinbase
- never mark a revealed placement hidden/cancelled or mutate stealth lifecycle
  state

This command draft is keyed by `stealth_order_id`. Active placement client ids
and exchange order ids are evidence only. Future live execution must reconcile
the live placement through the existing stealth lifecycle exchange-handling
path before local state can change.

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
evidence fields only. The current enterprise Admin API exposes only the
live-disabled stealth cancel draft above; stealth create, reveal, hide, move,
and reprice command routes are not modeled.

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

## Movement And Repricing

Movement/repricing reads expose existing durable and runtime-safe evidence.
The read routes do not move parent orders, premark moves, trigger repricing,
cancel Coinbase orders, or replace revealed stealth placements.

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

Movement repricing has one live-disabled command draft:

```http
POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice
Authorization: Bearer <backend-verifiable-token>
Idempotency-Key: idem-movement-reprice-001
X-Correlation-Id: corr-movement-reprice-001
X-Operator-Intent: movement_reprice_review
X-Admin-Actor: trader-001
X-Admin-Roles: trader
Content-Type: application/json

{"reason":"operator_requested_reprice"}
```

The request identity is the path `stealth_order_id`. Do not send
`client_order_id` or `order_id` in the body. The current response is HTTP
`501` with `status="not_implemented"`, durable audit/idempotency evidence,
`live_exchange_submitted=false`, and `data.stealth_manager_invoked=false`.
It does not clear repricing cooldowns, invoke the live dashboard repricer,
cancel placements, or call Coinbase.

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
- `command_routes_mode="live_disabled"`
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

If the same `Idempotency-Key` and same command payload are sent again for the
same endpoint, path identity, actor/roles, and operator intent, the API should
return the original command result without minting a second `client_order_id`
or submitting a second Coinbase order.

If the same `Idempotency-Key` is reused with a different payload, path
identity, actor/roles, or `X-Operator-Intent`, the API should return conflict.

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
