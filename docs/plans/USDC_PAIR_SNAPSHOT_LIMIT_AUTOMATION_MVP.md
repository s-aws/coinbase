# USDC Pair Snapshot Limit Automation MVP

This durable plan records the approved direction for a future backend-owned
automation MVP that discovers eligible Coinbase spot `*-USDC` products,
captures a durable price snapshot for each product, and derives limit-order
plans at the captured snapshot price with per-product notional capped at `N`
or less.

The plan is intentionally not an implementation. It exists so future work can
move toward the automation idea without restoring legacy dashboard authority,
creating a second trading path, or bypassing the Admin API approval,
cap/guard, audit, live-service, and reconciliation chain.

## Current Status

The current Admin MVP has backend-owned no-live discovery, snapshot readback,
and dry-run order-plan evidence for a non-live planning slice, but not enough
contract evidence for live every-pair automation.

Available building blocks:

- Backend-only Coinbase credential resolution through environment variables or
  AWS Secrets Manager secret id `coinbase`.
- Backend product metadata and product-refresh surfaces.
- Existing spot campaign and portfolio-sweep source material.
- Backend manual spot limit-order payload and capped live-submit proof-chain
  patterns.
- M58 no-live Admin API route inventory, OpenAPI, append-only stores, audit,
  idempotency, snapshot readback, and dry-run order-plan readback for
  `usdc-pair-snapshot-runs`.
- Approval, admission audit, cap/guard, reconciliation-plan, live-service,
  idempotency, local deployment, and artifact evidence patterns.

Missing before live automation:

- Frontend generated-contract consumption and read-only order-plan display.
- Proof-chain integration for each planned order.
- A backend-owned price-source contract for every captured snapshot.
- Per-product and run-level notional caps that prevent wallet/balance
  overcommit.
- Proof-chain generation and replay behavior for every planned order.
- Rate-limit, retry, partial failure, pause/resume, abort, and recovery
  semantics.
- Focused backend tests, generated frontend contract consumption, release-gate
  evidence, and contextless review.

## Milestone Alignment

Primary milestone: M58 - Automation, Campaign, Scheduler, And Retry Suite.

Supporting milestones:

- M49-M52, for approval, cap/guard, admission audit, and reconciliation-plan
  prerequisites.
- M54, for spot command-suite semantics, manual-order proof chains, campaign
  and sweep source material, and spot-only USDC boundaries.
- M60, for release-candidate proof, live-cap evidence, and handoff.

This plan must not interrupt active Account/Wallet/Spot/Futures local Admin
delivery unless the user explicitly asks to prioritize it or the work directly
unblocks local operation.

## Authority Boundaries

- The backend owns product enumeration, price snapshots, sizing, guard checks,
  approval requirements, Coinbase reads/calls, retry logic, audit,
  reconciliation, and run state.
- Frontend may display run plans, skip reasons, proof-chain readiness,
  approval state, and final evidence only after generated Admin API contracts
  exist.
- BFF may forward authenticated Admin API requests only after backend
  contracts exist. It must not compute eligibility, prices, sizes, approvals,
  caps, wallet availability, retry policy, or Coinbase request bodies.
- No browser code may call Coinbase, parse Coinbase credentials, schedule
  automation loops, decide order admission, or treat refreshed product
  metadata as execution authority.
- `client_order_id` remains the operator-facing order identity. Coinbase
  `order_id` is exchange evidence only, except for existing wrapper paths that
  explicitly require exchange ids.

## Snapshot-To-Order Invariants

- `N` is the requested maximum notional per product. A planned order must use
  notional `<= N`, or the product must be skipped with a durable reason.
- A separate run-level cap must bound aggregate planned, submitted, and
  executed notional across all products.
- Each eligible product gets one immutable snapshot row per run.
- The planned limit price for a product is derived from that product's
  captured snapshot price, then quantized backend-side to the allowed price
  increment. No later browser or BFF repricing is allowed.
- If the snapshot is missing, stale, outside product constraints, below
  minimum size after quantization, or blocked by wallet/cap/approval evidence,
  the backend records a skipped or rejected row instead of inventing a price.
- Dry-run output must report `live_coinbase_orders_ran=false`,
  `live_coinbase_execution=not_run`, and notional `0`.
- Live output, when separately approved in a later phase, must report exact
  product ids, `client_order_id`s, submitted notional, executed notional,
  retained inventory, reconciliation result, audit ids, and Coinbase evidence.

## Target Operator Workflow

1. Operator chooses side policy, account/portfolio scope, product scope, and
   maximum notional `N` per product.
2. Backend discovers eligible Coinbase spot `*-USDC` products.
3. Backend captures a durable price snapshot for each eligible product.
4. Backend derives order-plan rows: product, side, requested notional,
   planned notional, snapshot price, limit price, base size, increments, skip
   reason, and proof-chain status.
5. Dry-run mode persists only snapshot, plan, audit, and skip evidence.
6. A later controlled-live pilot submits at most one explicitly selected
   product through the backend proof chain.
7. A later allowlist pilot broadens to a small explicit product set.
8. Full every-pair automation is enabled only after allowlist fan-out,
   recovery, retry, pause/resume, cap ledger, and contextless review pass.

Default posture is no-live. Live execution requires an explicit later phase,
operator acknowledgement, backend runtime opt-in, caps, approval, audit,
guard, reconciliation evidence, and release/live-cap evidence.

## Phase Plan

### Phase A - Contract Discovery Plan

Define the backend contract before UI or runner work.

Deliverables:

- Route inventory row for the automation run family.
- OpenAPI schemas for run request, run status, product snapshot row,
  order-plan row, skip reason, proof-chain status, and live-output evidence.
- Explicit request fields for max notional per product, side policy, product
  scope, account/portfolio scope, dry-run/live mode, idempotency,
  correlation id, and operator intent.
- Backend docs describing how eligible `*-USDC` products are discovered.

Required proof:

- Backend contract tests for schema shape and route inventory sync.
- Frontend generated-schema freshness after the contract exists.
- Capability matrix entry that keeps this under M58 automation.

Non-goals:

- No Coinbase order submission.
- No frontend planning logic.
- No scheduler.

### Phase B - Product And Price Snapshot Dry Run

Create a backend dry-run that discovers products and records durable snapshots
without creating order payloads.

Deliverables:

- Backend reads products and prices through approved Coinbase read boundaries.
- Each snapshot row records product id, quote currency, trading status,
  product type, increments, minimum sizes, price source, observed price,
  timestamp, and eligibility status.
- Each skipped row records a stable machine-readable skip reason.
- Snapshot output records no live Coinbase order execution and notional `0`.

Required proof:

- Backend tests for eligible, skipped, disabled, non-USDC, missing-price,
  stale-price, and minimum-size cases.
- Read-only frontend display tests after generated contracts exist.

Non-goals:

- No order payloads.
- No balance or wallet allocation decisions in the browser.

### Phase C - Dry-Run Order Plan

Derive backend-owned limit-order plans from the durable snapshot.

Backend status: implemented for no-live Admin API evidence. The backend now
records dry-run order-plan rows through
`POST /api/v1/automation/usdc-pair-snapshot-runs/{run_id}/order-plans` and
reads durable plans through
`GET /api/v1/automation/usdc-pair-snapshot-order-plans`. Frontend generated
contract consumption and read-only display remain pending.

Deliverables:

- Per-product planned `client_order_id`, idempotency key, quote size, base
  size, limit price, side, time-in-force, and notional cap evidence.
- Product-level rounding and quantization using backend product increments.
- Per-product planned notional `<= N`.
- Run-level cap checks so total planned notional cannot exceed configured
  bounds.
- Durable audit rows for planned, skipped, rejected, and replayed products.

Required proof:

- Backend tests for rounding, min quote/base size, price increment, total cap,
  per-product cap, duplicate run replay, and idempotency.
- Frontend read-only order-plan table using generated types.

Non-goals:

- No live Coinbase call.
- No browser-generated `client_order_id`.
- No parallel order construction path in the BFF.

### Phase D - Proof-Chain And Guard Integration

Attach existing Admin API proof-chain primitives to each planned order.

Deliverables:

- Approval request/decision requirement per run or per product, whichever the
  backend contract defines.
- Admission audit records linked to run id, product id, payload hash, actor,
  and idempotency key.
- Cap/guard decisions proving maximum submitted and executed notional.
- Reconciliation-plan records proving how the run will be audited and
  recovered.
- Live-service decision evidence that remains disabled unless an approved
  controlled-live phase opts in.

Required proof:

- Backend tests proving missing approval, audit, cap/guard, or reconciliation
  evidence blocks submission before Coinbase.
- Frontend tests proving proof-chain status is displayed as evidence only.
- Contextless review before any live pilot.

Non-goals:

- No frontend approval store.
- No browser guard, wallet, profitability, or inventory evaluation.

### Phase E - Single-Product Controlled-Live Pilot

Submit at most one explicitly selected product through the backend proof chain.

Entry requirements:

- Phases A-D complete and passing.
- User explicitly approves live pilot scope.
- Product, side, notional, maximum submitted notional, maximum executed
  notional, and stop conditions are written into phase evidence.
- Backend local deployment and release evidence prove current contract refs.

Deliverables:

- Backend tool or Admin API route that submits one product only.
- Live-output artifact with product id, `client_order_id`, submitted
  notional, executed notional, Coinbase result evidence, and proof-chain refs.
- Fail-closed behavior when any prerequisite is absent.

Required proof:

- Focused backend tests.
- Focused frontend evidence display tests if UI reads the artifact.
- Live-cap evidence with exact submitted/executed notional.
- Default release/deployment gates still report no-live and notional `0`.

Non-goals:

- No every-pair fan-out.
- No scheduler.
- No unattended live loop.

### Phase F - Allowlist Fan-Out Pilot

Broaden from one product to a small explicit allowlist.

Deliverables:

- Product-level failure isolation.
- Per-product and run-level rate-limit handling.
- Durable partial-success summary.
- Cancel/recovery evidence for open or uncertain orders.

Required proof:

- Backend tests for partial failure, replay, retry, and cap exhaustion.
- Operator-visible run summary and recovery state.
- Contextless review focused on automation/run-state boundaries.

Non-goals:

- No unbounded `*-USDC` universe.
- No time-based scheduler.

### Phase G - Full `*-USDC` Automation MVP

Enable all backend-eligible `*-USDC` products only after the allowlist pilot is
stable.

Deliverables:

- Backend-owned product universe resolution.
- Durable run lock so concurrent runs cannot overcommit.
- Global pause/resume/abort controls.
- Retry budget and backoff policy.
- Recovery and reconciliation workflow for submitted, rejected, unknown, and
  partially filled orders.
- Operator runbook and release evidence.

Required proof:

- Backend regression for automation, command, audit, and recovery behavior.
- Frontend release gate after UI exposure.
- Contextless review.
- Live-cap ledger proving product-level and total notional bounds.

Non-goals:

- No browser scheduler.
- No direct dashboard WebSocket authority.
- No Coinbase `order_id` as internal tracking identity.

## Data Model Sketch

Future backend contracts should include durable read models equivalent to:

- `automation_run_id`
- `snapshot_id`
- `product_id`
- `quote_currency`
- `side`
- `snapshot_price`
- `snapshot_price_source`
- `snapshot_captured_at`
- `requested_notional_usdc`
- `max_notional_per_product_usdc`
- `planned_notional_usdc`
- `run_max_submitted_notional_usdc`
- `run_max_executed_notional_usdc`
- `base_size`
- `quote_size`
- `limit_price`
- `price_increment`
- `base_increment`
- `quote_increment`
- `min_base_size`
- `min_quote_size`
- `eligibility_status`
- `skip_reason`
- `client_order_id`
- `idempotency_key`
- `correlation_id`
- `approval_request_id`
- `admission_audit_id`
- `cap_guard_decision_id`
- `reconciliation_plan_id`
- `live_service_decision_id`
- `live_exchange_submitted`
- `live_coinbase_orders_ran`
- `submitted_notional_usdc`
- `executed_notional_usdc`

The frontend may render these fields only after they appear in generated
Admin API types.

## Validation Gates

Minimum focused checks for future implementation:

- Backend contract tests for the automation route and OpenAPI schema.
- Backend unit tests for product eligibility, snapshot price source, sizing,
  caps, idempotency, and replay.
- Backend integration/smoke tests proving dry-run emits no live Coinbase
  order execution.
- Backend ownership check for architect-owned docs and tools.
- Frontend generated API freshness and route coverage after contracts exist.
- Frontend component/read-model tests for snapshot and run evidence.
- Frontend `npm run security:commands`.
- Frontend `npm run release:gate` before milestone/release/deployment
  closeout.
- Backend full regression before backend-association or release closeout.

## Required Legacy Review Before Implementation

Before implementing any backend-facing part of this plan, inspect current
backend `main` and backend `origin/prod` side by side for analogous product,
spot campaign, sweep, order, ticker/price, and audit behavior.

Likely source material:

- `dashboard_server.py`
- `business/spot_portfolio_sweep.py`
- `tools/run_spot_portfolio_sweep_live.py`
- `business/spot_campaign.py`
- `tools/run_spot_campaign.py`
- `api_reference/products`
- `api_reference/orders`
- relevant regression tests for product metadata, spot sweep, order placement,
  fills, and recovery

Treat legacy behavior as source material only. Do not recreate legacy
dashboard WebSocket command authority or place Coinbase calls outside backend
Admin API contracts.

## Stop Conditions

- Product eligibility or price source is ambiguous.
- Product minimums or increments make the requested notional invalid.
- The run would exceed per-order, per-product, run-level, wallet, or live-cap
  limits.
- Approval, admission audit, cap/guard, reconciliation, or live-service
  evidence is missing.
- Idempotency or replay behavior is not deterministic.
- Coinbase status is unknown and recovery evidence is absent.
- Any frontend or BFF code attempts to compute trading authority or call
  Coinbase.

## First Useful Non-Live Slice

The first implementation slice should be Phase A plus Phase B only:

- backend contract and route inventory for a dry-run snapshot;
- durable product snapshot rows with skip reasons;
- generated frontend types;
- read-only UI display of the snapshot evidence;
- proof that live Coinbase order execution remains `not_run` with notional
  `0`.

Do not start with live order fan-out. The smallest useful step is making the
backend produce and persist the automation snapshot that every later phase
depends on.
