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
  basis and cannot satisfy known-profit checks.
- Coinbase portfolio average cost basis can be read as a separate operational
  authority source for USDC spot coverage, P/L, drift review, and optional SELL
  admission. It is asset-level portfolio data mapped to eligible `BASE-USDC`
  products, not exact local FIFO lot evidence.
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
  existing sweep live runner; they do not place live orders directly.
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
  remains exchange-facing only.

## Supported Submission Surfaces

Spot Coinbase submission is intentionally limited to the existing order-entry
surfaces. A new spot feature should reuse one of these paths rather than adding
another REST placement path.

Scope note: direct dashboard and stealth placement use products configured in
`products.json`; the portfolio sweep and campaign features are intentionally
USDC-only even if `products.json` also contains USD-quoted spot products.

- Direct dashboard `place_order` validates product capability, size, and the
  planning-phase action guard before calling `REST_CLIENT.create_order`.
  Quote-sized market BUYs validate `quote_size` directly against
  `quote_increment` and `quote_min_size`; base-sized orders validate and
  quantize `base_size`.
  The success response includes the generated `client_order_id` and Coinbase
  `order_id`, and the server writes an `order_submitted`/`rest_submit` row to
  `order_event_stream`; follow-on evidence comes from the dashboard log plus
  normal websocket, order lifecycle, reconciliation, and fill-ledger records
  keyed by `client_order_id`.
  Direct dashboard placement is an immediate manual order surface. It does not
  pre-insert `order_parent` or opt the order into automated follow-up policy
  state before submission; use stealth or sweep paths when a feature needs
  pre-submit parent policy state, managed reveal behavior, campaign accounting,
  or portfolio-wide automation.
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
  `rest_client.create_order` call. Live sweep placements use UUID
  `client_order_id` values, publish `order_submitted`/`rest_submit` evidence to
  `order_event_stream` when the local event stream is available, and write
  submitted orders, submitted notional, fill-backfill status, and
  reconciliation records to the durable sweep JSONL ledger.

`create_parent_order` is not live exchange placement. It is dashboard/local DB
CRUD that creates an `order_parent` row for operator-managed local state.

## Outputs And Artifacts

- Orders are still persisted in `order_parent`.
- Stealth plans are still persisted in `stealth_orders`.
- Product precision and minimums come from `products.json::metadata`.
- Dashboard product refresh updates `products.json`.

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
- Run `pytest tests/regression/ -v --tb=short` after non-agent-file changes.

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

This does not replace the required full regression command:
`pytest tests/regression/ -v --tb=short`.

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

## Roadmap

Spot trading is not yet treated as a blanket equivalent to futures/perpetuals.
Before adding spot-specific strategy features, follow the tracked
[Spot Readiness Roadmap](docs/SPOT_READINESS_ROADMAP.md).
