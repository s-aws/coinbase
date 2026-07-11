# Live Order Surfaces

This project has several operator and test surfaces. They do not have equal
live authority, and a backend-only live runner is not proof that the matching
HTTP or browser workflow is live-capable.

Current work is goal id `legacy_fill_follow_up_operator_slice`. Default release
and deployment checks are no-live and must report live Coinbase execution as
not run with notional `0`.

## Admin HTTP Surfaces

- `POST /api/v1/orders` is the live-capable manual Spot placement route. It may
  pass `allow_live_execution=true` to the shared command service only after the
  route-bound backend admission decision allows the exact request. The command
  service still enforces runtime opt-in, product capability, size, wallet,
  inventory/no-short, notional cap, audit, event-stream, and Coinbase response
  checks.
- `POST /api/v1/orders/{client_order_id}/cancel` is currently live-disabled at
  the HTTP adapter. It calls the shared cancel service without
  `allow_live_execution=true`, so the service returns fail-closed evidence
  before Coinbase cancellation.
- `POST /api/v1/orders/{client_order_id}/fill-follow-up/trigger` is a guarded
  no-live local-state compatibility route. It can invoke the existing
  fill-follow-up executor after exact prerequisites and must prove one accepted
  child through parent/child readback. It does not submit or cancel Coinbase
  orders and is not automatic fill-event processing.
- Futures place, close/reduce, and cancel HTTP routes remain no-live command
  drafts. Their shared command-service methods return disabled evidence and do
  not invoke the backend-only futures live executor.
- Stealth create/reveal/move/cancel/recovery/reconciliation, movement reprice,
  campaign, and sweep HTTP command routes remain route-specific no-live or
  local-evidence surfaces unless their current route inventory says otherwise.

## Backend-Only Controlled-Live Tools

The following manual tools can exercise backend-owned controlled-live paths
after explicit confirmation and route-specific proof setup. They do not grant
browser authority or change the HTTP posture above:

- Spot manual order submit, cancel, and order readback tools under `tools/`;
- Futures place, close/reduce, cancel, and fill-readback tools under `tools/`;
- one selected M58 USDC snapshot order submit/cancel/readback path; and
- the proof-gated M58 fan-out executor boundary, which remains parked under the
  current MVP goal and must fail closed unless every route proof clears.

Each live run must record the actual product, `client_order_id`, environment,
account or portfolio scope, submitted/executed notional, backend decisions,
audit ids, and cancel/rollback/readback result.

## Legacy Compatibility Surfaces

- Dashboard WebSocket `place_order` and `cancel_order` remain compatibility
  surfaces over the shared backend behavior path.
- Dashboard `place_hotpoint_test_order` is a compatibility seed-order surface
  and is not current Admin product authority.
- Spot portfolio sweep live tooling remains a backend CLI surface. Campaign UI
  does not itself place Coinbase orders.

New frontend product work must use generated Admin API contracts and canonical
BFF wrappers. Do not use the dashboard WebSocket, a backend CLI, or an exchange
`order_id` as a shortcut around route authority.

## Current Fill/Follow-Up Boundary

The guarded no-live operator chain is implemented. Automatic/live fill-event
parity uses the same authority as every other live order: the current goal's
explicit side, price, notional, rate, and cancellation limits plus
backend-owned authorization, wallet/cap, duplicate-order, audit-correlation,
reconciliation, rollback, and readback gates. Whether an order fills is an
outcome, not a separate permission category. Fan-out, scheduler,
retry/runtime-control, wallet-ledger, and ladder/grid work is parked and cannot
make itself current by producing more evidence about its own blockers.
