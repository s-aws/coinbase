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
dry-run order-plan evidence, generated frontend contract consumption, and
read-only order-plan display for a non-live planning slice. Planned rows now
surface backend price-source/freshness readback, run-cap readback,
proof-chain readiness records, and missing prerequisite blockers, and a
backend proof-refresh route can link exact durable approval lifecycle
snapshots back onto existing order-plan rows,
but the system still does not have enough contract evidence for live every-pair
automation.

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
- M58 single-product controlled-live submit/cancel tooling and read-only
  exchange readback/recovery evidence for one prior live submission. This is
  backend-only and does not authorize fan-out or scheduling. Phase E
  live-readiness now rechecks latest cap/guard submitted-notional and wallet
  availability evidence before marking the one-row submit route ready.
- M58 Phase F no-live allowlist-readiness and run-state evidence for explicit
  product sets. It records product-level failure isolation status, run
  rate-limit budget refs, retry budget status, cancel/recovery refs,
  partial-success status, retryable products, recovery-required products,
  queued/blocked product states, run lock, pause, abort, and a maximum 100
  USDC fan-out testing cap without submitting Coinbase orders or running a
  scheduler. Run-state evidence now records no-live run-cap allocation,
  allocated notional, cap remaining, cap overage, and cap-guard decision refs
  per product, plus no-live wallet allocation evidence derived from existing
  backend cap-guard wallet proofs. The cap-guard proof must cover the product's
  planned notional through both max-submitted and wallet-available notional, or
  run-state fails closed with `cap_guard_submitted_notional_exceeded` or
  `cap_guard_wallet_available_notional_exceeded` before allocation. Run-state
  evidence now also exposes live
  wallet reservation, debit, and release blockers as `missing_no_live`
  evidence for queued products. Run-state evidence now also requires exact
  Phase E live-readiness association for each queued product by `plan_id`,
  `product_id`, and `client_order_id`; missing or blocked live-readiness
  removes the product from the queued set before any future fan-out decision.
  Missing or reused run-lock refs, missing or reused runtime rate-limit window
  refs, runtime windows with more than five queued products, repeated attempts
  that exhaust per-product retry budget, and repeated attempts missing or
  reusing retry-backoff evidence now fail closed by removing queued products
  before cap/wallet allocation and recording `run_lock_ref_missing`,
  `run_lock_ref_conflict`, `rate_limit_window_ref_missing`,
  `rate_limit_window_ref_conflict`, `rate_limit_window_capacity_exceeded`,
  `retry_budget_exhausted`, `retry_backoff_ref_missing`, or
  `retry_backoff_ref_conflict`.
  Pause or abort requests now fail closed by removing queued products before
  cap/wallet allocation and recording `run_paused_no_live` or
  `run_aborted_no_live` blockers.
  Products blocked by cap allocation, wallet allocation, missing live-readiness,
  runtime controls, retry-budget exhaustion, retry-backoff blockers, pause, or
  abort no longer remain retryable or recovery-required in run-state evidence;
  their retry state is blocked, recovery is not required, and retry attempts are
  zero. Aggregate rate-limit, retry-budget, retry-backoff, recovery, and
  partial-success status now derive from final product state instead of stale
  pre-allocation readiness. Missing live wallet reservation/debit/release
  evidence blocks aggregate run-state fan-out readiness while preserving the
  queued product row for the one-selected-product handoff proof path. Reused
  no-live reservation refs with a different run/readiness binding fail closed
  with `live_wallet_reservation_ref_conflict`; reused debit or release refs
  across queued products or prior reservation records fail closed with
  `live_wallet_debit_ref_conflict` or `live_wallet_release_ref_conflict`.
  These reference conflicts remove affected rows from the queued set and zero
  their wallet allocation.
  Final-blocked products also clear stale cancel-recovery refs when recovery is
  not required.
  A backend-owned run-state-to-live-submit handoff route now requires one
  explicitly selected queued product with matching `ready_no_live` Phase E
  live-readiness, matching run-state/order-plan/live-readiness `plan_id` and
  `snapshot_run_id` association, ready parent and product live-wallet
  reservation/debit/release evidence revalidated against the latest reservation
  store record, latest live-readiness price-freshness timestamps/statuses and
  recomputed price-distance evidence still passed, latest cap-guard submitted
  notional and wallet evidence still passed, ready aggregate parent
  run-state/cap/wallet/live-readiness/notional/partial-success statuses,
  selected-product rate/cap/wallet
  allocation readiness, no selected-product blockers, plus recorded parent
  run-lock, runtime rate-limit, retry-budget/backoff, recovery evidence, and
  selected-product candidate readiness, cap-guard ref, and membership in the
  parent retryable/recovery-required sets before it can reuse the existing
  single-order submit/cancel path. Only `fanout_execution_not_approved` and
  `scheduler_blocked` may remain as parent fanout blockers for this handoff;
  any other parent fanout blocker rejects the handoff. This does not authorize
  live fan-out or scheduler behavior.
- `tools/run_admin_api_usdc_pair_snapshot_live_submit.py` can use
  `--submit-from-run-state` to record the one-product allowlist-readiness and
  run-state evidence, then call the backend run-state handoff route. It remains
  one invocation, one selected product, one order, immediate submit/cancel, and
  no scheduler. Its local summary records the run-state live wallet reservation
  blockers as no-live evidence.
- Backend proof-refresh mutation for existing order plans that resolves exact,
  unexpired, non-revoked approval lifecycle snapshots without browser
  authority or live execution, and can link exact durable admission-audit
  evidence from the backend audit store plus exact passed cap/guard evidence
  from the backend cap guard store, exact passed reconciliation-plan evidence
  from the backend reconciliation store, and exact disabled live-service
  decision evidence from the backend live-service decision store. The refreshed
  row remains blocked with `live_service_decision_disabled` and no Coinbase
  execution. Backend regression coverage now proves row-scoped refresh and
  idempotent replay across multi-product plans. Backend M58 proof records now
  persist run id, order-plan id, product id, account/portfolio scope, notional
  scope, and snapshot/limit price evidence for each planned row.
- Frontend generated-contract consumption and read-only display of M58
  snapshot/order-plan evidence, including proof-chain readiness blockers,
  backend proof-record references, backend price-source/freshness readback,
  backend run-cap readback, and generated proof-decision states (`present`,
  `missing`, `disabled`, or `not_required`) without browser admission logic.
- Approval, admission audit, cap/guard, reconciliation-plan, live-service,
  idempotency, local deployment, and artifact evidence patterns.

Missing before live automation:

- Live-grade price-source freshness, acceptance, and staleness gates for every
  planned product in fan-out. The single-product Phase E live-readiness route
  now records reference-bid and last-filled source/timestamp evidence and fails
  closed when either reference is missing, stale, invalid, or future-dated.
- Multi-product wallet allocation controls that prevent wallet/balance
  overcommit during fan-out. Phase F run-state now proves no-live run-cap
  allocation and no-live wallet allocation from existing cap-guard wallet
  proofs, but it still does not fetch live wallet balance, reserve/debit
  funds, release reservations, or authorize multi-product live fan-out. The
  run-state contract now records `live_wallet_reservation_status` and
  `live_wallet_reservation_blockers` so this missing live-wallet layer is
  durable evidence, not a chat-only caveat. Phase F run-state now requires
  matching Phase E live-readiness evidence before a product can be queued in
  no-live rehearsal, and the single-product Phase E live-readiness route fails
  closed when the latest backend cap/guard proof does not cover the submitted
  notional or required wallet availability. The one-selected-product run-state
  handoff can reuse that submit/cancel proof chain, but it still does not
  reserve/debit wallet balance or authorize multi-product live fan-out.
- Durable approval, admission-audit, cap/guard, reconciliation, and enabled
  live-service decisions for every planned order.
- Runtime fan-out rate-limit handling, retry execution, partial failure,
  pause/resume, abort, and recovery semantics beyond the no-live run-state
  rehearsal.
- Release-gate evidence and contextless review for any live pilot.

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
contract consumption and read-only display are implemented. Order-plan rows
carry the backend snapshot price source, freshness/acceptance statuses, and
run-cap status/remaining notional as readback evidence.

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

Status: implemented through exact proof refresh and controlled-live
submit/cancel contracts. Planned order rows expose
`proof_chain_status=blocked`, a backend approval request id, admission audit,
cap/guard, reconciliation, and live-service proof refs. A backend
proof-refresh route can replace `approval_snapshot_missing` with an exact
approval snapshot from durable approval lifecycle storage and can replace
`admission_audit_blocked` only when exact backend audit-store evidence exists.
It can also replace `cap_guard_decision_blocked` only when exact passed backend
cap/guard-store evidence matches the planned row notional scope, and
`reconciliation_plan_blocked` only when exact passed backend
reconciliation-store evidence matches the planned row notional scope. It can
link exact disabled live-service evidence as `live_service_decision_disabled`
or exact enabled live-service evidence as `live_submission_missing` until a
matching controlled-live submit/cancel artifact exists. Once a one-row live
submit/cancel artifact matches the enabled live-service decision, proof refresh
can set that row to `proof_chain_status=accepted` with live Coinbase
submission and cancel evidence. Backend regression coverage proves that
multi-row proof refresh links only the product row with exact durable evidence,
rejects out-of-scope cap/reconciliation notional evidence, keeps idempotent
replay stable even if later evidence is recorded, blocks full snapshot fill
tests pending manual review, and accepts only one controlled-live submission
per readiness record. A blind contextless review passed for
explicit-operator-approved single-product controlled-live planning only; fan-out
and scheduler behavior remain blocked.

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

Backend status: route and durable runner implemented. The route
`POST /api/v1/automation/usdc-pair-snapshot-order-plans/{plan_id}/live-submit`
submits one backend-owned order-plan row and immediately cancels by the same
`client_order_id`. The operator runner
`tools/run_admin_api_usdc_pair_snapshot_live_submit.py` builds the one-row
snapshot/order-plan/proof/readiness sequence, requires
`--confirm-live-submit`, enforces a submitted-notional cap of `<= 10` USDC,
requires far-from-market pricing, records a live-output artifact, and fails
closed unless `COINBASE_ADMIN_API_LIVE_EXECUTION_ENABLED=true` is already set
for the process. Phase E live-readiness records reference-bid and last-filled
source/timestamp/freshness evidence and rejects stale, invalid, future-dated,
or missing market references before submit/cancel can run. It also re-reads
the latest cap/guard proof by decision id and rejects readiness when the
submitted notional exceeds the approved cap or required wallet availability.
The read-only recovery runner
`tools/run_admin_api_usdc_pair_snapshot_live_readback.py` reads the prior
Coinbase order by exchange order id, verifies cancelled/non-filled/no open
order evidence, and can append local recovery evidence without submitting or
cancelling any order.

Latest live evidence: on 2026-07-06, the backend submitted one BTC-USDC BUY
order for `1.09` USDC planned notional at `31800.00`, received Coinbase order
id `d7ef7a10-d170-4155-b713-d3ea9396dcf5`, recovered cancellation by exchange
order id after client-id cancellation returned `UNKNOWN_CANCEL_ORDER`, and
verified exchange readback as `CANCELLED` with `0` filled value, `0` fees, and
`0` open BTC-USDC orders. Durable evidence artifacts:
`artifacts/coinbase-backend-m58-usdc-live-submit-20260706-2001.json`,
`artifacts/coinbase-backend-m58-usdc-live-submit-20260706-2001-recovery.json`,
`artifacts/coinbase-backend-m58-usdc-live-submit-20260706-2001-proof-refresh.json`,
and
`artifacts/coinbase-backend-m58-usdc-live-submit-20260706-2001-exchange-readback.json`.
On 2026-07-06, durable read-only recovery tooling also emitted
`artifacts/coinbase-backend-m58-usdc-live-readback-20260706-2001.json` and
appended
`m58-live-btc-usdc-20260706-2001-submission-readback-recovery`. The backend
proof row is accepted with `live_coinbase_execution=submitted_cancelled`.

Latest repeated live evidence: on 2026-07-06T22:00Z, the backend submitted one
BTC-USDC BUY order for `1.09` USDC planned notional at `32224.00`, with
reference bid and last-filled price `64449.36`, received Coinbase order id
`8720bff2-687f-43d3-bd30-fe9ef0a8939b`, cancelled the same
`client_order_id`, and recorded `proof_chain_status_after_submission=accepted`
with no proof-chain blockers. Readback immediately verified exchange status
`CANCELLED`, executed notional `0`, and `0` open BTC-USDC orders. Durable local
evidence artifacts:
`artifacts/coinbase-backend-m58-usdc-live-submit-20260706-2200.json` and
`artifacts/coinbase-backend-m58-usdc-live-readback-20260706-2200.json`.

Latest minimum-size live evidence: on 2026-07-06T22:10Z, the backend submitted
one BTC-USDC BUY order at `32144.31` against best bid/last-filled
`64288.63`. The operator requested `1.00` USDC, the runner raised only the
dry-run planning cap to `1.01` so Coinbase minimum-size rounding produced a
valid order-plan row, the live route submitted `1.00` USDC, executed `0`, and
cancelled the same `client_order_id`. Exchange readback verified status
`CANCELLED`, executed notional `0`, and `0` open BTC-USDC orders. Durable
local evidence artifacts:
`artifacts/coinbase-backend-m58-usdc-live-submit-20260706-2210.json` and
`artifacts/coinbase-backend-m58-usdc-live-readback-20260706-2210.json`.

Latest live freshness evidence: on 2026-07-06T22:23Z, the backend submitted
one BTC-USDC BUY order at `32125.89` against Coinbase best bid `64251.78`
captured at `2026-07-06T22:23:49.220801Z` and latest trade `64251.78`
captured at `2026-07-06T22:23:49.596245Z`. Live-readiness persisted
`reference_bid_price_source=coinbase_advanced_trade.best_bid`,
`last_filled_price_source=coinbase_advanced_trade.last_trade`, and fresh
status for both references before submit/cancel ran. The route submitted
`1.00` USDC, executed `0`, cancelled the same `client_order_id`, and exchange
readback verified `CANCELLED`, executed notional `0`, and `0` open BTC-USDC
orders. Durable local evidence artifacts:
`artifacts/coinbase-backend-m58-usdc-live-submit-20260706-2223.json` and
`artifacts/coinbase-backend-m58-usdc-live-readback-20260706-2223.json`.

Latest expanded-scope live evidence: on 2026-07-06T23:25Z, after the active
goal was expanded to include bounded live execution, the backend submitted one
BTC-USDC BUY order for `1.00` USDC submitted notional at `32028.95` against
Coinbase best bid and latest trade `64057.9`. Coinbase returned order id
`029cac7e-f2c8-4c5d-98b3-1905be4650df`; the backend cancelled the same
`client_order_id`, recorded `live_coinbase_execution=submitted_cancelled`,
`executed_notional_usdc=0`, `cancel_rollback_complete=true`, and
`proof_chain_status_after_submission=accepted` with no proof-chain blockers.
Readback verified exchange status `CANCELLED`, executed notional `0`, and `0`
open BTC-USDC orders. Durable local evidence artifacts:
`artifacts/coinbase-backend-m58-usdc-live-submit-20260706-232520.json` and
`artifacts/coinbase-backend-m58-usdc-live-readback-20260706-232520.json`.

Latest run-state handoff live evidence: on 2026-07-07T01:11Z, the backend
runner used `--submit-from-run-state` and run-state id
`m58-usdc-run-state-live-BTC-USDC-20260707-011114-run-state` to hand off one
queued BTC-USDC product with matching `ready_no_live` Phase E readiness. The
backend submitted one BTC-USDC BUY order for `1.00` USDC submitted notional at
`32004.51` against Coinbase best bid and latest trade `64009.02`. Coinbase
returned order id `8d0ceffa-dc64-4b24-b808-a3f9082f758c`; the backend
cancelled the same `client_order_id`, recorded
`live_coinbase_execution=submitted_cancelled`, `executed_notional_usdc=0`,
`cancel_rollback_complete=true`, and
`proof_chain_status_after_submission=accepted` with no proof-chain blockers.
Run-state fan-out execution remained blocked with
`fanout_execution_not_approved` and `scheduler_blocked`. Readback verified
exchange status `CANCELLED`, executed notional `0`, and `0` open BTC-USDC
orders. Durable local evidence artifacts:
`artifacts/coinbase-backend-m58-usdc-live-submit-20260707-011114-run-state.json`
and
`artifacts/coinbase-backend-m58-usdc-live-readback-20260707-011114-run-state.json`.

Entry requirements:

- Phases A-D complete and passing.
- User explicitly approves live pilot scope.
- Product, side, notional, maximum submitted notional, maximum executed
  notional, and stop conditions are written into phase evidence.
- Backend local deployment and release evidence prove current contract refs.

Deliverables:

- Backend tool or Admin API route that submits one product only.
- Backend read-only tool that can verify exchange cancellation/non-fill state
  for the prior one-product live submission and append local recovery evidence.
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

Backend status: no-live readiness and run-state contracts implemented. The
backend can record explicit allowlist readiness, per-product failure isolation
status, run rate-limit budget refs, retry budget status, cancel/recovery refs,
partial-success status, retryable products, recovery-required products,
queued/blocked product states, run lock, pause, abort, and a maximum 100 USDC
fan-out testing cap. It also records no-live run-cap allocation evidence:
planned notional, allocated notional, cap remaining, cap overage, and
per-product allocation status, plus cap-guard decision refs. It also records
no-live wallet allocation status, available wallet proof, allocated wallet
notional, remaining wallet capacity, blockers, and wallet-check source derived
from existing backend cap-guard records, plus explicit live wallet reservation
status and blockers showing missing reservation, debit, and release semantics
for queued no-live products. It also records no-live live-readiness association
status, ready/missing/blocked product ids, live-readiness blockers, and
per-product readiness ids/sources. Queued products must have exact matching
Phase E live-readiness evidence for `plan_id`, `product_id`, and
`client_order_id`, with preflight and submit-route readiness passing and no
Coinbase execution. Wallet allocation now requires the cap-guard record to
match the run-state route, method, module, action, permission, service method,
`client_order_id`, and product scope, and to prove max-submitted plus
wallet-available notional that covers the product's planned notional. Rows with
missing, mismatched, blocked, invalid, optional, or under-notional wallet/cap
proof, or missing/blocked live-readiness proof, are blocked in no-live
run-state evidence and are removed from queued product ids before any future
fan-out decision. Missing or reused run-lock refs,
missing or reused runtime rate-limit window refs, runtime windows with more
than five queued products, retry-budget exhaustion, and missing or reused
retry-backoff refs remove queued products before cap/wallet allocation and
record `run_lock_ref_missing`, `run_lock_ref_conflict`,
`rate_limit_window_ref_missing`, `rate_limit_window_ref_conflict`,
`rate_limit_window_capacity_exceeded`, `retry_budget_exhausted`,
`retry_backoff_ref_missing`, or `retry_backoff_ref_conflict`.
Pause or abort requests also remove queued products before cap/wallet
allocation and record `run_paused_no_live` or `run_aborted_no_live` blockers.
Products blocked by cap allocation, wallet allocation, missing live-readiness,
runtime controls, retry-budget exhaustion, retry-backoff blockers, pause, or
abort are not counted as retryable or recovery-required, and
aggregate readiness statuses fail closed when no product remains queued.
Final-blocked products clear stale cancel-recovery refs when recovery is not
required. Missing live wallet reservation/debit/release evidence also keeps the
aggregate run-state blocked for fan-out while preserving queued product rows for
the one-selected-product handoff proof path. Reused no-live reservation refs
with a different run/readiness binding fail closed with
`live_wallet_reservation_ref_conflict`; reused debit or release refs across
queued products or prior reservation records fail closed with
`live_wallet_debit_ref_conflict` or `live_wallet_release_ref_conflict`. These
reference conflicts remove affected rows from queued product ids and zero their
wallet allocation. This evidence remains
`fanout_readiness_status=blocked`, `fanout_execution_status=blocked`,
`live_coinbase_execution=not_run`, and notional `0`; it does not submit
Coinbase orders, fan out execution, fetch/reserve/debit live wallet balance,
or run a scheduler.
The backend can also hand off one explicitly selected queued product from a
run-state to the existing Phase E submit/cancel route only when the product row
has matching `ready_no_live` live-readiness evidence by `client_order_id`, the
run-state/order-plan/live-readiness `plan_id` and `snapshot_run_id` association
is current, the latest wallet reservation/debit/release record still matches
the selected run-state/product/notional tuple, latest live-readiness freshness
timestamps/statuses, far-from-bid evidence, and snapshot non-fill evidence still
pass after recomputation, latest cap-guard submitted-notional and wallet checks
still cover the selected notional, and the parent run-state has ready aggregate
status, recorded run-lock evidence, is not paused/aborted, and has ready runtime rate-limit,
retry-budget/backoff, recovery evidence, selected-product rate/cap/wallet
allocation readiness, and no selected-product blockers, plus selected-product
candidate readiness, cap-guard ref, and membership in the parent
retryable/recovery-required sets;
this remains a single-order controlled-live path, not fan-out automation.
The backend live-submit runner can exercise this same handoff with
`--submit-from-run-state`, recording the selected product's run-state id and
queued live-readiness association in the local artifact before stopping after
submit/cancel evidence.

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

## Next Useful Non-Live Slice

The current Phase D slice displays disabled live-service proof references and
generated proof-chain decision evidence as read-only backend evidence. Backend
proof refresh now requires exact approval, admission audit, cap/guard,
reconciliation, disabled live-service, row-scoped notional, and no-live
submission evidence before clearing any corresponding blocker. Focused EC2
validation still reports `live_coinbase_execution=not_run` and notional `0`.

The next non-live decision is operator-scoped: either approve the aggregate
proof-chain readback field names/formulas below, or approve moving to Phase E
single-product controlled-live planning. Do not implement live execution,
fan-out, or scheduler behavior from this plan without explicit operator
approval for the concrete live scope.

Proposed aggregate count fields, pending operator approval:

- Plan item: `proof_chain_planned_count`,
  `proof_chain_blocked_count`, `proof_chain_live_disabled_count`,
  `proof_chain_missing_evidence_count`, and
  `proof_chain_not_applicable_count`.
- List response: same fields prefixed with `returned_`.
- Formula source: count only existing `order_plan_rows` fields. Planned means
  `plan_status == "planned"`. Blocked means
  `proof_chain_status == "blocked"`. Live-disabled means
  `proof_chain_blockers` contains `live_service_decision_disabled`. Missing
  evidence means `proof_chain_blockers` contains any blocker other than
  `live_service_decision_disabled`. Not-applicable means
  `proof_chain_status == "not_applicable"`.
- These counts are readback evidence only. They must not authorize frontend
  actions, clear backend blockers, enable live-service decisions, submit
  Coinbase orders, or replace row-level proof references.

Do not start multiple live orders or live fan-out until Phase D proof-chain
evidence, contextless review, and explicit operator approval for that concrete
controlled-live scope all pass.

As of 2026-07-07, Phase E single-product controlled-live submit/cancel evidence
exists, a Phase F one-selected-product run-state handoff live submit/cancel has
passed with exchange readback, and Phase F no-live allowlist-readiness/run-state
evidence includes backend run-cap allocation, exact cap-guard association,
exact per-product live-readiness association, and fail-closed wallet
allocation, while live wallet reservation/debit/release blockers are exposed
as missing no-live evidence. Under-notional cap-guard max-submitted or
wallet-available proof now fails closed before wallet allocation. Pause/abort
no-live runtime-control evidence now fails closed by clearing queued products
and recording explicit blockers.
Missing or reused run-lock refs, missing or reused runtime rate-limit window
refs, runtime windows with more than five queued products, retry-budget
exhaustion, and missing or reused retry-backoff refs also fail closed before
cap/wallet allocation.
Missing live wallet reservation/debit/release evidence now blocks aggregate
run-state fan-out readiness while preserving queued product rows for the
one-selected-product handoff proof path. Reused no-live reservation refs with a
different run/readiness binding now fail closed with
`live_wallet_reservation_ref_conflict`; reused debit or release refs across
queued products or prior reservation records fail closed with explicit wallet
reference conflict blockers and zero affected wallet allocation.
The run-state live-submit handoff also rejects missing, blocked, or stale latest
parent/product live-wallet reservation/debit/release evidence, blocked parent
run-lock, pause/abort, rate-limit, retry-budget/backoff, or recovery evidence
before any executor call, rejects blocked aggregate parent run-state/cap/wallet/
live-readiness/notional/partial-success statuses, rejects stale selected-product
price-freshness timestamp/status or recomputed price-distance evidence, rejects
stale selected-product cap-guard submitted-notional or wallet evidence, rejects
stale selected-product rate/cap/wallet allocation evidence, rejects non-empty
selected-product
blockers, rejects unexpected parent fanout blockers other than
`fanout_execution_not_approved` and `scheduler_blocked`, rejects stale
selected-product candidate/cap-guard refs, rejects stale run-state/order-plan/
live-readiness `plan_id` or `snapshot_run_id` association, and rejects stale
parent retryable/recovery-required product sets that omit the selected product.
Blocked product rows are no longer reported as retryable or recovery-required.
Aggregate run-state status fields now fail closed when final product state has
no queued products.
Final-blocked product rows also clear stale cancel-recovery refs when recovery
is not required.
A blind contextless review on 2026-07-06 passed the M58 no-live Phase F
authority-boundary questions and confirmed the change set is a domain module
under Automation / Campaign / Scheduler, not a reusable admin platform
primitive. The review also confirmed future live fan-out remains unsafe and
blocked until every product has live-grade price freshness, exact approval,
admission, cap/guard, reconciliation, enabled live-service evidence,
multi-product wallet controls, runtime fan-out/retry/recovery semantics,
release-gate evidence, and another contextless review.
