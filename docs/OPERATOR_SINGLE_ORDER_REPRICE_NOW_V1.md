# Operator Single-Order Reprice Now V1

Goal `operator_single_order_reprice_now_v1` installs one authenticated,
operator-actionable local workflow for preparing a Reprice Now intent against
one exact canonical system-owned, zero-fill, `REVEALED` Stealth placement.

## Current boundary

The installed Goal 15 action is `PREPARE_REPRICE_NOW`. The operator identifies
the exact placement with both `stealth_order_id` and `client_order_id`, reviews
backend-owned local source evidence, and confirms one immutable intent. The
browser supplies no product, portfolio, price, size, notional, or cap term.

The backend:

- resolves the source through the canonical Goal 7 Stealth manager pattern;
- requires exact local `REVEALED`, zero-fill, no-partial-fill, configured
  portfolio, active-placement, and direct-parent evidence;
- uses the raw exchange identity only ephemerally inside that resolver;
- exposes and persists no raw exchange identity or exchange-identity hash;
- requires the browser to echo the sanitized `source_evidence_sha256`, current
  definition revision, and definition hash to prevent stale-selection use;
- deterministically reserves one RFC 4122 UUIDv5 successor while accepting
  only canonical UUIDv4 source identities;
- persists one immutable non-market intent in its own PostgreSQL ledger;
- stores actor and idempotency evidence only as SHA-256 values; and
- exposes fixed sanitized lifecycle events and exact zero exchange-call
  accounting.

The readback deliberately reports:

```text
market_terms_bound=false
cap_policy_bound=false
live_authority_terms_complete=false
source_cancel_call_count=0
replacement_create_call_count=0
total_exchange_call_count=0
```

`POST .../execute-reprice-now` is a visible future action, but returns fixed
HTTP 409 diagnostic
`operator_reprice_now_live_authority_terms_incomplete` before service,
PostgreSQL ledger, runtime, or Coinbase access. Both live allowances remain
unconsumed. No global automatic repricer, ticker repricer, background worker,
partial-fill path, or product-wide action is enabled.

## Routes

- `GET /api/v1/movement-repricing/stealth/{stealth_order_id}/placements/{client_order_id}/reprice-now`
- `POST /api/v1/movement-repricing/stealth/{stealth_order_id}/placements/{client_order_id}/reprice-now-intents`
- `POST /api/v1/movement-repricing/stealth/{stealth_order_id}/placements/{client_order_id}/execute-reprice-now`

The GET route requires analytics read permission. Both POST routes require
backend `order:cancel` and `order:create` permissions. Preparing uses exact
header `X-Operator-Intent: prepare_single_order_reprice_now`; the disabled
execute contract uses
`X-Operator-Intent: execute_single_order_reprice_now`.

## Legacy comparison

Read-only source comparison inspected:

- `origin/prod:dashboard_server.py`, whose
  `reprice_now_stealth_order` handler cleared a cooldown and invoked
  product-wide anchor repricing; and
- `origin/prod:core/stealth_order_manager.py`, whose anchor-repricing loop owns
  broader product processing and live placement mutation.

Neither behavior was restored. The current legacy dashboard
`reprice_now_stealth_order` message is source-disabled before bridge, manager,
runtime-controller, or product-wide processing. The Admin API translates only
the narrow local intent-reservation primitive. Current
`application/admin_api/operator_revealed_order_movement_runtime.py` supplied
the canonical local source-resolution pattern; Goal 15 does not borrow Goal 7
ledger rows, claims, or exchange allowances.

## Validation scope

Focused coverage includes pure policy, source resolver, service replay order,
PostgreSQL restart/idempotency and zero-call constraints, authenticated routes,
startup schema wiring, dashboard source-disable behavior, generated OpenAPI,
route inventory, ownership, and compile checks. All tests use synthetic or
local PostgreSQL evidence and make no Coinbase or other network call.

Terminal focused validation passed 126 backend tests and 168 frontend tests.
The complete backend regression passed 1,345 parallel-safe tests with 6 skips
and 1,020 serial tests with 150 intentional skips. The frontend release gate
passed 1,963 unit/component tests and 30 managed Playwright scenarios,
including packaged and installed deployment validation. Independent safety and
blind-contextless audits both returned `PASS`. No Goal 15 Coinbase call or
exchange mutation occurred.
