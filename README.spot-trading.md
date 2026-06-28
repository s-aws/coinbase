# Spot Trading

Spot trading uses the same order lifecycle, stealth lifecycle, sizing, fee,
dashboard, and reconciliation paths as futures. There is no separate spot
engine.

## When To Use

Use spot products when the trade should settle against the spot wallet balance
instead of a Coinbase Derivatives position. Spot orders use base-asset size
increments and quote-notional minimums from `products.json`.

## Key Concepts

- `products.json` is the product catalog. Add spot products under `spot` and
  keep metadata under `metadata`.
- Product type must resolve to `ProductType.SPOT` through
  `configuration.normalize_product_type`.
- `ticker_to_trading` is only for products where ticker and tradable product IDs
  are genuinely different. Do not map `BTC-USD` to `BTC-USDC` unless the target
  product is live and tradable in Coinbase product metadata.
- Spot profitability uses the spot fee multiplier in `calculation/fee_manager.py`
  and does not apply derivatives per-contract fees.
- Spot wallet availability is checked by the action-condition guard during
  stealth planning and again immediately before reveal placement when Coinbase
  REST credentials are configured. Direct dashboard `place_order` also runs the
  planning-phase guard before REST submission. Wallet reads follow Coinbase
  account pagination before evaluating availability.
- Local planned-budget accounting subtracts HIDDEN, PENDING, and TRIGGERED spot
  stealth commitments from wallet availability before admitting another spot
  action. REVEALED orders are not counted locally because Coinbase wallet
  availability should already reflect the live exchange hold.
- Product capability policy keeps spot feature availability explicit. Spot
  direct placement, stealth planning, and stealth reveal are enabled; spot
  move/reprice replacement, cancel/re-entry, and hotpoint auto-placement are
  disabled by default until their spot-specific safety work is complete.
- Spot replacement guards are replace-aware. If spot move or revealed reprice
  is explicitly enabled, the guard checks only the net new wallet requirement
  above the existing Coinbase hold and rechecks immediately before canceling
  the live placement.
- Spot follow-ups are classified before creation. BUY-fill to SELL is treated
  as an `exit`; SELL-fill to BUY is treated as `rebuy` and is blocked unless
  `SPOT_FOLLOW_UP_POLICY_JSON` or `products.json::spot_follow_up_policy`
  explicitly enables it.
- Spot inventory authority separates wallet sellability from known profitable
  inventory. `SPOT_INVENTORY_BASELINES_JSON` or
  `products.json::spot_inventory_baselines` can import pre-existing inventory;
  baseline lots without positive known entry price are marked unknown cost
  basis and cannot satisfy known-profit checks. Imported baselines are also
  audited for source freshness metadata such as `source_updated_at`.
- Coinbase portfolio average cost basis can be read as a separate operational
  authority source for USDC spot coverage, P/L, drift review, and optional SELL
  admission. It is asset-level portfolio data mapped to eligible `BASE-USDC`
  products, not exact local FIFO lot evidence. When it is the actual SELL
  authority source, stale average-cost records or stale local-vs-Coinbase drift
  block that product.
- `known_inventory_available` is an optional action-condition guard. When
  enabled, spot `SELL` admission can require known profitable lots in addition
  to wallet availability. It is disabled by default.
- Dashboard spot readiness feedback is available through the
  `request_spot_readiness` websocket message and the Spot Readiness panel in
  `ui_stealth_orders_manager.html`. The panel shows capability reasons,
  guard phase coverage, wallet snapshot balances, planned local spot budget,
  and imported baseline inventory split between known and unknown cost basis.
- USDC-only portfolio sweep planning and durable P/L reporting live in
  [Spot Portfolio Sweep](README.spot-portfolio-sweep.md). That feature also
  owns sweep automation status, inventory coverage, fill-backfill recovery, and
  sweep recovery gates. USD pairs remain out of scope for that feature.
- Reusable campaign intake, dry-run matrices, release gates, durable campaign
  P/L snapshots, and dashboard campaign status live in
  [Spot Campaigns](README.spot-campaign.md). Campaigns render configs for the
  existing sweep live runner; they do not place live orders directly. SELL
  allowlist sweep configs expire quickly and must be regenerated immediately
  before live approval.
- Partial campaign runs can generate targeted retry configs for products that
  were not submitted. Retry configs still render to the existing sweep runner
  and still require explicit live approval before order placement.
- Planned skips, such as below-minimum quote-size products, are audit rows and
  not failed Coinbase submissions. They are not retry targets and do not block
  campaign readiness when all planned live orders submitted and reconciled.
- Spot-specific feature requests should pass the local feature-intake gate
  before implementation. The gate requires exact USDC product scope, order
  sides, order policies, automation cadence, live approval rule, notional caps,
  inventory retention policy, and required audit evidence.
- Internal order tracking still uses `client_order_id`; Coinbase `order_id`
  remains exchange-facing only. Dashboard `cancel_order` is the explicit
  cancellation exception: callers must pass `client_order_id`, and the server
  calls this repo's `REST_CLIENT.cancel_order(client_order_id)` wrapper because
  Coinbase accepts the client id for that operation.
- The current boundary between legacy live WebSocket commands, read-only HTTP
  routes, and sweep/campaign execution is maintained in
  [Live Order Surfaces](docs/LIVE_ORDER_SURFACES.md).

## Supported Submission Surfaces

Spot Coinbase submission is intentionally limited to the existing order-entry
surfaces. A new spot feature should reuse one of these paths rather than adding
another REST placement path.

Scope note: direct dashboard and stealth placement use products configured in
`products.json`; the portfolio sweep and campaign features are intentionally
USDC-only even if `products.json` also contains USD-quoted spot products.
The checked-in `products.json` is intentionally a minimal local catalog and
does not represent all Coinbase spot products. Do not infer USDC sweep or
campaign coverage from that file.

Automation note: do not build scheduled or portfolio-wide spot automation on
raw dashboard `place_order`. Use USDC sweep/campaign when the workflow needs
dry-run validation, durable JSONL run evidence, retry planning, and
command-line reconciliation. Use stealth when the workflow needs a planned
local order that reveals later under the shared guard path.

### Spot Order Lifecycle Audit Matrix

| Surface | Planning/admission | Live exchange call | Durable evidence |
| --- | --- | --- | --- |
| Direct dashboard `place_order` | Product capability, size validation, planning-phase action guard | `REST_CLIENT.create_order` | `order_response`, `order_submitted` / `rest_submit`, later websocket/reconciliation/fill-ledger rows keyed by `client_order_id` |
| Admin API manual `POST /api/v1/orders` | Auth/RBAC, idempotency, approval, admission audit, cap/guard, reconciliation plan, manual acknowledgement, configured live-service gate, product capability, size validation, planning-phase action guard | `REST_CLIENT.create_order` only when every backend gate passes | `AdminApiCommandResponse`, `order_event_stream`, `post_submit_reconciliation`, direct-order audit route, later websocket/reconciliation/fill-ledger rows keyed by `client_order_id` |
| Admin API cancel `POST /api/v1/orders/{client_order_id}/cancel` | Auth/RBAC, idempotency, approval, admission audit, cap/guard, reconciliation plan, manual acknowledgement, configured live-service gate | `REST_CLIENT.cancel_order(client_order_id)` only when every backend gate passes | `AdminApiCommandResponse`, command audit, later exchange/order evidence remains tied to local `client_order_id` |
| Dashboard `cancel_order` | Requires `client_order_id` before REST | `REST_CLIENT.cancel_order(client_order_id)` | `cancel_response`; later exchange/order evidence remains tied to local `client_order_id` |
| Stealth reveal | Stored stealth plan, profitability, product capability, reveal-time action guard | `REST_CLIENT.place_limit_order` | `order_parent`, stealth reveal audit, placement pointers, event-stream evidence keyed by `client_order_id` |
| Hotpoint seed order | Runtime admission, hotpoint capability, size validation, planning-phase action guard, pre-inserted parent row | `REST_CLIENT.limit_order_gtc` | `order_parent`, `order_submitted` / `rest_submit`, hotpoint parent policy flags |
| USDC sweep live | USDC product selector, wallet-aware plan, safety policy, per-order action guard | `rest_client.create_order` | sweep JSONL run record, order reports, optional fill backfill, reconciliation by `client_order_id` |
| Campaign-rendered sweep | Campaign intake, config validation, dry-run matrix, release/readiness gates | none directly; renders to sweep live runner | campaign JSONL snapshots, equivalent sweep config, run index, P/L checkpoints |

- Direct dashboard `place_order` validates product capability, size, and the
  planning-phase action guard before calling `REST_CLIENT.create_order`.
  For spot products, it also requires
  `params.manual_live_acknowledgement=true`; missing acknowledgement blocks
  before REST submission.
  Quote-sized market BUYs validate `quote_size` directly against
  `quote_increment` and `quote_min_size`; base-sized orders validate and
  quantize `base_size`.
  The success response includes the generated `client_order_id` and Coinbase
  `order_id`, and the server writes an `order_submitted`/`rest_submit` row to
  `order_event_stream`. The success response also includes an `audit_command`
  that runs the read-only direct-order audit by `client_order_id`; follow-on
  evidence comes from the dashboard log plus normal websocket, order lifecycle,
  reconciliation, and fill-ledger records keyed by `client_order_id`.
  Direct dashboard placement and Admin API manual placement are immediate manual
  order surfaces. They do not pre-insert `order_parent` or opt the order into
  automated follow-up policy state before submission; use stealth or sweep paths
  when a feature needs pre-submit parent policy state, managed reveal behavior,
  campaign accounting, portfolio-wide automation, or scheduled execution.
  There is no direct-order dry-run equivalent for raw `place_order`; use the
  sweep/campaign dry-run tools when a dry-runable spot order workflow is
  required.
  Direct orders can be inspected with:
  `python tools\run_spot_direct_order_audit.py --client-order-id <client_order_id>`.
  The dashboard can return the same local audit with
  `request_spot_direct_order_audit` and `params.client_order_id`.
  These are read-only local evidence audits, not retry or automation wrappers.
  In direct-audit output, `live_coinbase_orders_ran` and
  `audit_command_live_coinbase_orders_ran` mean the audit command itself did
  not submit orders. Use `audited_order_live_submission_evidence`,
  `audited_order_estimated_submitted_notional_usdc`, and
  `audited_order_fill_notional_usdc` for evidence about the already-submitted
  order being audited.
  Direct orders still rely on the normal dashboard response,
  `order_event_stream` submission evidence, websocket/order lifecycle handling,
  fill-ledger rows, and the shared reconciliation/fill-audit paths keyed by
  `client_order_id`.
  Read-only recovery evidence for audited direct orders is available through
  `GET /api/v1/spot/recovery/preview?client_order_id=<client_order_id>`,
  `GET /api/v1/spot/recovery/apply-review?client_order_id=<client_order_id>`,
  `GET /api/v1/spot/recovery/rollback-plan?client_order_id=<client_order_id>`,
  and
  `GET /api/v1/spot/recovery/reconciliation-proof?client_order_id=<client_order_id>`.
  Those Admin API routes report candidates, gate dependencies, rollback
  prerequisites, and proof-field requirements; they do not apply repair rows,
  roll back local state, write proof/snapshot records, execute reconciliation,
  mutate order or exchange state, call Coinbase, or authorize browser/BFF
  recovery. Backend-owned proof and snapshot POST contracts are separate
  local-state evidence routes and remain no-live.
  Use sweep or campaign execution when the workflow needs a self-contained
  JSONL run ledger, retry plan, and command-line reconciliation wrapper.
  Manual direct-order checklist before sending `place_order`:
  confirm the product is intentionally configured/tradable, confirm the order
  side and base or quote notional, confirm the planning guard policy is the one
  intended for this account, set `manual_live_acknowledgement=true`, and for
  spot `SELL` confirm the known-profit authority policy. Direct spot live
  placement requires an explicit planning-phase `max_notional` action-condition
  cap before REST submission. Direct spot `SELL` also requires
  `known_inventory_available` to be enabled and supported by
  fill-ledger/imported known-cost authority. Admin API manual placement supplies
  that authority from the shared fill-ledger repository and configured imported
  baselines, and supplies planned-budget accounting from durable
  `stealth_orders` rows. Direct spot placement also
  requires an enabled local `order_event_stream` publisher before REST
  submission so the `client_order_id` can be audited after the exchange call.
  For operator validation of the Admin API direct SELL authority path without
  Coinbase execution, run
  `python tools\run_admin_api_manual_spot_sell_validation.py --summary-only`.
  That runner uses the same Admin API route and shared command service with a
  fake REST client; it must report live Coinbase execution as not run with
  submitted/executed notional `0`.
  Use a regenerated strict SELL allowlist through sweep/campaign instead of raw
  `place_order` when the operator needs portfolio-wide profit-authority
  evidence, per-run caps, skipped-order accounting, or repeatable execution.
  Raw direct spot `SELL` should be limit-priced. A direct market SELL does not
  supply a positive operator-selected sale price for the known-inventory
  authority check, so it should be treated as fail-closed under the direct spot
  guard. Use sweep/campaign for market-style portfolio SELLs because those
  runners build mark-aware plan and explain rows before submission.
  The repository does not ship a default account cap in `products.json` because
  that would silently choose risk limits for every local account. Operators must
  set `ACTION_CONDITION_GUARDS_JSON` or
  `products.json::action_condition_guards` before using raw direct spot orders;
  see [Action Condition Guard Examples](docs/examples/action-condition-guards.md).
- Dashboard `cancel_order` is a manual cancellation surface. It accepts
  top-level `client_order_id` or `params.client_order_id`, rejects requests that
  provide only `order_id`, and calls `REST_CLIENT.cancel_order(client_order_id)`.
  Do not resolve this dashboard action to exchange `order_id`; raw batch
  `cancel_orders(order_ids=[...])` remains the exchange-id-oriented API.
- Hotpoint Manager `place_hotpoint_test_order` is also a live dashboard
  submission surface. It exists only to seed hotpoint detection with a normal
  limit order whose parent row has `enable_hotpoint_replication=TRUE`.
  It is runtime-admission gated, validates
  `ProductCapability.HOTPOINT_AUTO_PLACEMENT`, validates size, runs the
  planning-phase action guard, pre-inserts the parent row, calls
  `REST_CLIENT.limit_order_gtc`, and records `order_submitted`/`rest_submit`
  evidence when the local event stream is available. Spot products are blocked
  by default because `HOTPOINT_AUTO_PLACEMENT` is disabled for spot unless
  explicitly configured.
- Stealth orders are planned through `create_stealth_order`. Live placement
  happens only during reveal, where the manager rechecks profitability,
  capability, and wallet conditions, pre-inserts the placement `order_parent`
  row, calls `REST_CLIENT.place_limit_order`, and records reveal/placement
  lifecycle audit evidence. If REST placement fails or Coinbase rejects the
  placement, reveal records a failed audit event but does not consume revealed
  size, set active placement pointers, or return a placement id.
- USDC portfolio sweep live execution runs through
  `tools/run_spot_portfolio_sweep_live.py --approved-live-orders`. The sweep
  planner rechecks the action guard immediately before each
  `rest_client.create_order` call. Live SELL sweeps require
  `--require-known-profitable-inventory`, so wallet balance alone cannot
  authorize a live SELL sweep. Live sweep placements use UUID
  `client_order_id` values, publish `order_submitted`/`rest_submit` evidence to
  `order_event_stream` when the local event stream is available, and write
  submitted orders, submitted notional, fill-backfill status, and
  reconciliation records to the durable sweep JSONL ledger.

`create_parent_order` is not live exchange placement. It is dashboard/local DB
CRUD that creates an `order_parent` row for operator-managed local state.

## Disabled And Conditional Spot Features

Spot is not a blanket futures/perpetual equivalent. The current supported spot
surfaces are direct dashboard placement, stealth planning/reveal, USDC sweep
execution, and campaign-rendered sweep execution through the existing sweep
runner.

Disabled by default for spot:

- Move/reprice replacement. It can be explicitly enabled by product capability,
  but then it must use the replace-aware action guard, credit the active
  Coinbase hold, reject partial-fill replacement, and leave local state
  conservative if exchange cancel fails.
- Cancel/re-entry. The shared policy is only a no-fill revealed-placement
  policy, not general hide-again behavior. Treat spot use as disabled unless
  product capability and policy are explicitly configured and the existing
  cancel/re-entry path is used end to end.
- Hotpoint auto-placement. The hotpoint seed order path is runtime-admission,
  capability, size, and action-guard gated. Spot remains blocked by default
  unless `HOTPOINT_AUTO_PLACEMENT` is explicitly enabled for spot.

Conditional for spot:

- BUY-fill to SELL follow-up is an exit and may use the existing follow-up path
  when profitability and action guards pass.
- SELL-fill to BUY follow-up is a rebuy and is blocked unless
  `SPOT_FOLLOW_UP_POLICY_JSON` or `products.json::spot_follow_up_policy`
  explicitly enables rebuy intent.
- Same-side replacement or retreat is blocked unless the relevant capability or
  policy is explicitly enabled and the action-condition guard admits the
  replacement.

Not disabled:

- Dashboard `cancel_order` by `client_order_id` is a supported manual
  cancellation surface.
- USDC sweep and campaign automation are the supported automatable spot
  surfaces; campaigns still render to the sweep live runner and do not create a
  second placement engine.

## Outputs And Artifacts

- Orders are still persisted in `order_parent`.
- Stealth plans are still persisted in `stealth_orders`.
- Product precision and minimums come from `products.json::metadata`.
- Dashboard product refresh updates `products.json`.
- Direct manual order audit is available through
  `request_spot_direct_order_audit` and
  `tools/run_spot_direct_order_audit.py`.

## Safety Constraints

- Do not add a spot-only placement path.
- Do not hard-code spot product IDs, increments, or fee rules in strategy code.
- Do not bypass `core.product_capability.evaluate_product_capability` from new
  order-entry, replacement, or strategy surfaces.
- Validate base-sized orders with
  `calculation.size_validation.validate_and_quantize_size` before placement.
  Validate quote-sized market BUYs with
  `calculation.size_validation.validate_quote_size`.
- Do not treat a planning wallet pass as sufficient for reveal. External
  Coinbase/dashboard orders can consume wallet balance after planning, so reveal
  must recheck.
- Do not add mutable spot reservation state unless derived planned-budget
  accounting from stealth order status and remaining size is proven insufficient.
- Do not let spot follow-ups inherit futures short/close semantics. Route new
  follow-up behavior through `core.spot_follow_up_policy`.
- Do not apply full-order wallet checks to no-fill spot replacements. Use the
  shared replacement action guard so Coinbase holds are credited and cancel
  failure leaves local state conservative.
- Do not treat wallet inventory as profitable inventory. Wallet balance proves
  sellability; only fill-ledger or imported known-cost lots can prove known
  profitable inventory by default. Coinbase average cost can satisfy SELL
  authority only through an explicit opt-in path with an extra profit buffer.
- Do not resolve dashboard `cancel_order` to exchange `order_id`. The dashboard
  contract is `client_order_id` in, `REST_CLIENT.cancel_order(client_order_id)`
  out.
- Run focused tests for ordinary spot changes. Run full `tests/regression/`
  only before durable milestone closeout, public/release-candidate handoff, or
  explicit request; prefer `python tools/run_parallel_regression.py --workers 4`.

## Examples

See [Spot Trading Examples](docs/examples/spot-trading.md).
For USDC-only portfolio sweep dry runs, see
[Spot Portfolio Sweep Examples](docs/examples/spot-portfolio-sweep.md).
For reusable campaign gates, see
[Spot Campaign Examples](docs/examples/spot-campaign.md).
For account-level guard configuration, see
[Action Condition Guards](README.action-condition-guards.md).
For spot feature intake, see
[Spot Feature Intake Examples](docs/examples/spot-feature-intake.md).

Validate a proposed spot-specific feature with:

```powershell
python tools/run_spot_feature_intake_gate.py --request-file runtime_state/spot_feature_request.json --summary-only
```

## Test Gate

Run the focused spot readiness gate with:

```powershell
python tools/run_spot_readiness_regression.py
```

Run the optional browser smoke gate with:

```powershell
python tools/run_spot_readiness_browser_smoke.py
```

The browser gate uses `pytest-playwright` and installed Chromium to open
`ui_stealth_orders_manager.html`, verify the readiness request is sent, and
verify a dashboard-shaped readiness payload renders in the panel.

Run the manual contextless blind-agent readability gate before treating new spot
order behavior as ready. The prompt and pass/fail rubric are in
[Spot Contextless Agent Testing](docs/SPOT_CONTEXTLESS_AGENT_TESTING.md). If a
fresh agent cannot explain the canonical spot order path from repo context
alone, fix the docs or code organization and rerun the same blind prompt.

This does not replace the required full regression closeout gate when a durable
milestone, public/release candidate, or deployment approval is being marked
complete: `python tools/run_parallel_regression.py --workers 4`.

Run the read-only spot release wrapper with:

```powershell
python tools/run_spot_release_gate.py
```

Approved live Coinbase spot smoke is available as a manual release-readiness
check:

```powershell
python tools/run_live_spot_usdc_smoke.py --approved-live-orders
```

For the approved live matrix plus fill-ledger reconciliation gate:

```powershell
python tools/run_live_spot_usdc_smoke.py --approved-live-orders --validation-matrix --reconciliation-gate
```

This command places real Coinbase spot orders and prints submitted/executed
notional in `LIVE_COINBASE_SPOT_SMOKE_SUMMARY`. Add `--retain-inventory` when
the bought base should remain in the account for future sell-path tests.
The smoke runner uses short prefixed `client_order_id` values to keep its
standalone smoke records recognizable and under Coinbase length limits. Do not
copy that pattern into sweep/campaign live execution, which uses UUID
`client_order_id` values and records sweep identity in ledger/event fields.

## Roadmap

Spot trading is not yet treated as a blanket equivalent to futures/perpetuals.
Before adding spot-specific strategy features, follow the tracked
[Spot Readiness Roadmap](docs/SPOT_READINESS_ROADMAP.md).
