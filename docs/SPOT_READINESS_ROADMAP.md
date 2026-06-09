# Spot Readiness Roadmap

This roadmap tracks the work needed before spot-specific features should be
added on top of the trading engine. Spot uses the same canonical order,
stealth, dashboard, sizing, fee, and reconciliation paths as futures, but spot
cannot short inventory and does not have derivatives-style position semantics.

## Current State

Implemented:

- `BTC-USD` is configured as a spot product in `products.json`.
- Product type resolution uses `ProductType.SPOT` for configured spot products.
- Spot sizing uses product metadata for base increments and quote minimums.
- Spot profitability uses the spot fee multiplier.
- The shared action-condition guard runs for:
  - stealth planning
  - stealth reveal
  - manual stealth move planning and execution
  - revealed anchor reprice before cancel-and-replace
  - hidden anchor reprice as a planning-budget change
  - raw dashboard `place_order`
- The wallet guard checks spot base balance for `SELL` and spot quote balance
  for `BUY` when Coinbase REST credentials are configured. Coinbase account
  pagination is followed before wallet availability is evaluated.
- Configured artificial limits can apply to spot, futures, or both.
- Product capability policy is implemented through
  `core.product_capability.evaluate_product_capability`.
- Spot move/reprice replacement, cancel/re-entry, and hotpoint auto-placement
  are disabled by default before they can create local state or exchange work.
- If spot move/reprice replacement is explicitly enabled, replacement wallet
  checks evaluate only the net new requirement after crediting the active
  same-currency Coinbase hold. Execution rechecks before exchange cancel.
- Spot follow-up automation is classified by intent before local follow-up
  state is created.
- Fill-ledger lot reconstruction has a working repository read API.
- Imported spot inventory baselines can represent known-cost or unknown-cost
  pre-existing inventory.
- The optional `known_inventory_available` action guard can require known
  profitable lots for spot `SELL` admission. It is disabled by default.
- Dashboard spot readiness feedback reports capability modes, guard policy
  state, planned spot budget, and wallet snapshot metadata through
  `request_spot_readiness` and the stealth orders manager panel.
- Spot readiness feedback now also reports guard phase coverage, imported
  baseline inventory by known/unknown cost basis, and structured guard or
  capability details when planning rejects an action.
- Focused spot readiness regression gate is available through
  `python tools/run_spot_readiness_regression.py`.
- Browser smoke coverage for the spot readiness panel is available through
  `python tools/run_spot_readiness_browser_smoke.py`.
- Public-release readiness docs describe local, browser, sandbox, and approved
  live spot smoke gates.
- Approved live Coinbase USDC spot smoke tooling is available through
  `python tools/run_live_spot_usdc_smoke.py --approved-live-orders`.
- Paper-mode spot replay is covered in the focused spot readiness gate.
- USDC-only spot portfolio sweep dry-run planning is available through
  `python tools/run_spot_portfolio_sweep_dry_run.py`.
- Explicitly approved USDC-only spot portfolio sweep live execution is
  available through `python tools/run_spot_portfolio_sweep_live.py`.
- Durable run-if-due sweep automation records JSONL history under
  `runtime_state/spot_portfolio_sweeps.jsonl` by default.
- Durable spot portfolio P/L snapshot helpers can report by product, by all
  USDC spot products together, and since last purchase from fill-ledger rows.
- The dashboard exposes read-only sweep operator status through
  `request_spot_sweep_status` and the stealth orders manager panel.
- Sweep run reconciliation can append Coinbase order/fill evidence records to
  the durable sweep JSONL ledger without live-order approval.
- Sweep live execution supports explicit market IOC, limit GTC, and post-only
  limit GTC order policies.
- Sweep safety policy can block live runs before Coinbase submission when
  artificial per-run, per-order, product allow/deny, planned-count, or
  skipped-count limits are configured.
- Sweep P/L reports are available through `--pnl-report`,
  `request_spot_sweep_pnl`, and the dashboard P/L panel.
- Optional SELL sweep safety can require known profitable fill-ledger or
  imported baseline lots before live execution starts.
- Approved live spot smoke tooling can run a four-action validation matrix:
  market BUY, post-only limit BUY cancel, post-only limit SELL cancel, and
  market SELL.
- Live smoke summaries are appended to a durable JSONL audit file and can
  backfill Coinbase REST fills into local `fill_ledger`.
- Sweep reconciliation compares Coinbase REST fill totals against local
  fill-ledger rows by `client_order_id` when the repository is available.
- Sweep live execution can load versioned JSON config files and validate them
  with read-only per-product explain output before live approval.
- The dashboard shows sweep order detail, fill-backfill counts, and richer
  per-product P/L detail rows.
- A read-only spot release gate command is available through
  `python tools/run_spot_release_gate.py`.
- Fill-ledger `client_order_id` schema is hardened for longer generated ids,
  including an idempotent migration for existing deployments.
- Fill-backfill recovery is available through
  `python tools/run_spot_fill_backfill_recovery.py`.
- Sweep inventory coverage reporting is available through
  `python tools/run_spot_portfolio_sweep_live.py --inventory-coverage`.
- Sweep config registry reporting is available through
  `python tools/run_spot_portfolio_sweep_live.py --config-registry`.
- Sweep P/L reports include a FIFO realized-lot operational reporting scope.
- Sweep recovery gating is available through
  `python tools/run_spot_sweep_recovery_gate.py`.
- The sweep examples document a Windows Task Scheduler recipe for invoking the
  run-if-due automation mode.
- A one-product approved live sweep canary has run against Coinbase, with
  submitted/executed notional reported, fill backfill appended, and
  reconciliation matched.
- The live canary exposed and fixed two spot-specific audit issues:
  order-specific fill fetch must not combine order-id and product filters, and
  fill-ledger price precision must preserve low-price spot fills.

Not yet solid enough for broad spot-specific features:

- External Coinbase sandbox/account checks remain opt-in and are not part of
  the default local regression gate.

## Guiding Rules

- Do not add a spot-only placement engine.
- Do not enable every futures/perpetual feature for spot by default.
- Do not let a planning wallet pass substitute for a reveal-time wallet check.
- Do not add naive wallet checks to live replacements before accounting for the
  active order being cancelled or replaced.
- Do not rely on lot-derived profitability until imported/external inventory
  and fill-ledger reconstruction are explicitly handled.
- Keep all internal linkage on `client_order_id`; use exchange `order_id` only
  for exchange calls and exchange evidence.

## Immediate Next Phases

These phases are intended for blanket approval as the next implementation
batch. Each phase should remain small enough to review independently, but the
sequence is designed so later spot-specific features have a reliable base.
Execution note: phases in this roadmap are approved for sequential
implementation; continue without stopping unless a material product, safety, or
architecture decision requires user input.

### Phase 1 - Product Capability Matrix

Status: implemented.

Add enum-backed product capability policy so spot support is explicit instead
of inherited from futures behavior.

Initial spot defaults:

- Enabled: guarded direct placement, stealth planning, stealth reveal, size
  validation, fee-aware profitability.
- Conditional: filled follow-ups, partial-fill follow-ups, same-side post-fill
  retreat.
- Disabled until audited: move/reprice replacement, cancel/re-entry, hotpoint
  auto-placement.
- Not applicable: futures short/open-close position flips, margin validation,
  liquidation checks, funding checks.

Acceptance:

- Product capability checks are reusable from dashboard, stealth, and strategy
  entry points.
- Unsupported spot actions fail before local state or exchange work is created.
- Regression tests prove futures behavior remains unchanged unless a capability
  is explicitly configured differently.

### Phase 2 - Spot Planned-Budget Reservation

Status: implemented.

Add local planned-budget accounting for hidden and pending spot orders. The
guard should consider account wallet availability minus already-planned local
spot commitments.

Budget rules:

- Spot `SELL` reserves base currency.
- Spot `BUY` reserves quote currency using `quote_size` when present, otherwise
  `size * limit_price`.
- Planning remains a stale preflight and reveal still rechecks Coinbase wallet
  state immediately before REST placement.
- External Coinbase/dashboard orders can still drain wallet state, so reveal
  blocks and retries instead of assuming the planned reservation is enough.
- Local planned budget is derived from current stealth state, not a separate
  mutable reservation table. HIDDEN, PENDING, and TRIGGERED spot orders count;
  REVEALED orders are omitted because Coinbase wallet availability should
  already reflect live exchange holds.

Acceptance:

- Multiple hidden spot orders cannot collectively overcommit available wallet
  balance.
- A wallet drain after planning blocks reveal before REST placement.
- Planned budget is released or reduced when hidden orders are cancelled,
  revealed, filled, reconciled closed, or otherwise terminal.

### Phase 3 - Spot Follow-Up Classification

Status: implemented.

Classify follow-up intent before creating a spot follow-up order.

Initial classes:

- `exit`: opposite-side order that sells acquired base or buys back intentionally
  held quote exposure.
- `rebuy`: buy after a spot sell, allowed only when configured as a strategy
  intent.
- `same_side_replacement`: same-side follow-up or retreat behavior, allowed only
  when explicitly enabled and budget-safe.
- `unsupported`: any ambiguous follow-up intent.

Default policy:

- `exit` is enabled.
- `rebuy` is disabled unless `SPOT_FOLLOW_UP_POLICY_JSON` or
  `products.json::spot_follow_up_policy` enables it.
- `same_side_replacement` is disabled unless explicitly enabled and the
  action-condition guard can satisfy wallet/planned-budget checks.

Acceptance:

- Spot follow-ups do not inherit futures short/close semantics.
- Unsupported spot follow-ups are blocked with a structured reason.
- Profitability checks still run for supported exit follow-ups.
- Existing futures/perpetual follow-up tests remain green.

### Phase 4 - Replace-Aware Action Guards

Status: implemented.

Extend action-condition guards for move/reprice/cancel-and-replace without
double-counting Coinbase holds.

Required behavior:

- Replacement actions must know the active placement being cancelled or
  replaced.
- Guarding must evaluate the net new requirement after the live placement is
  cancelled or otherwise accounted for.
- If the exchange cancel fails, local state remains conservative and the
  replacement is not treated as safe.

Acceptance:

- Move/reprice remains default-disabled for spot by product capability policy,
  but explicitly enabled spot replacements run replace-aware checks.
- Tests cover no-fill replacement, partial-fill rejection, cancel failure, and
  wallet delta evaluation.
- No revealed stealth order is marked hidden, moved, or replaced unless exchange
  truth has been handled through the existing lifecycle path.

### Phase 5 - Lot And External Inventory Authority

Status: implemented.

Harden lot/inventory support before any spot feature depends on "profitable
sell from known inventory."

Required work:

- Fix and test fill-ledger repository read APIs used by lot builders.
- Define how imported or pre-existing spot inventory enters the system.
- Separate wallet availability from cost-basis knowledge: a wallet can prove
  sellability, but not profitability.
- Add a baseline inventory import or explicit "unknown cost basis" state.

Acceptance:

- Spot sell admission can distinguish "wallet has asset" from "system knows
  profitable lots" through the optional `known_inventory_available`
  action-condition guard.
- Lot reconstruction is tested from fill ledger rows and imported baseline
  inventory.
- Unknown-cost inventory is never silently treated as profitable.

### Phase 6 - Dashboard Readiness Feedback

Status: implemented.

Expose spot readiness and guard state to operators.

Required UI/server feedback:

- Product type and capability status.
- Guard failure reason and phase.
- Planned-budget consumption by product/currency.
- Wallet availability snapshot age.
- Whether a spot action is disabled, conditional, or enabled.

Acceptance:

- Blocked spot actions produce actionable dashboard responses.
- Operators can request/read why an action is unavailable before submitting it.
- Dashboard remains a presentation layer; domain decisions stay in core/shared
  policy modules.

### Phase 7 - Spot Readiness Test Gate

Status: implemented.

Add a focused spot readiness test group and keep the full regression gate.

Required coverage:

- Product capability gates.
- Planned-budget overcommit.
- External wallet drain between planning and reveal.
- Direct dashboard and stealth parity.
- Spot follow-up classification.
- Replace-aware guard behavior.
- Lot reconstruction and unknown-cost handling.

Optional external checks:

- Coinbase sandbox/account spot wallet smoke.
- Product metadata refresh smoke for spot products.
- Dry-run or paper-mode scenario replay for spot workflows.
- Browser UI smoke for public-release readiness.

Acceptance:

- `pytest tests/regression/ -v --tb=short` passes.
- Focused spot readiness tests can be run independently.
- Browser smoke can be run independently when `pytest-playwright` and Chromium
  are installed.
- External tests remain opt-in and never become the default regression gate.

### Phase 8 - Public-Release Test Packaging

Status: implemented.

Document contributor/release gates for:

- required regression
- focused spot readiness regression
- Playwright browser smoke
- external sandbox tests
- explicitly approved live spot smoke

Acceptance:

- Public release readiness docs are linked from `docs/README.md`.
- Browser setup and smoke commands are documented.
- Live Coinbase spot smoke is documented as manual, explicit, and notional
  reporting required.

### Phase 9 - Approved Live Spot USDC Smoke

Status: implemented.

Add a manual live smoke runner for the cheapest eligible USDC spot pair.

Required behavior:

- Select online, tradable, USDC-quoted spot products by lowest
  `quote_min_size`, then lowest price.
- Require an explicit `--approved-live-orders` flag.
- Preview the market buy before submitting.
- Place a post-only limit order and cancel it.
- Place a minimum-notional market buy and either sell the acquired base amount
  or intentionally retain it with `--retain-inventory`.
- Print submitted/executed notional per live order and total notional.

Acceptance:

- The runner is not part of default regression or default CI.
- Live runs are reported with product, side/type, timestamp, and notional.
- Live runs that retain inventory report retained base size and do not need to
  zero out the account.
- Any failed or partial run reports enough order ids to reconcile manually.

### Phase 10 - Paper-Mode Spot Scenario Replay

Status: implemented.

Replay the full spot workflow locally without live exchange side effects:

- spot buy admission
- planned-budget reservation
- external wallet drain before reveal
- reveal block
- fill-ledger lot creation
- known-inventory spot sell admission

Acceptance:

- Scenario proves the spot safety path end to end without credentials.
- It remains deterministic and suitable for default regression.

### Phase 11 - Spot Operator UX Hardening

Status: implemented.

Improve operator feedback before enabling more spot-specific behavior:

- expose known vs unknown inventory status more clearly
- show imported baseline inventory source and cost-basis state
- make disabled/conditional capability reasons visible at action points
- surface planned-budget and wallet-drain blocks in a consistent UI shape

Acceptance:

- Operators can tell whether a spot sell is blocked by wallet availability,
  unknown cost basis, insufficient profitable lots, or product capability.
- UI remains a presentation layer over core guard/capability decisions.

### Phase 12 - USDC Spot Portfolio Sweep Foundation

Status: implemented for dry-run planning and durable reporting foundation.

Add the first requested spot-specific feature without enabling live automated
placement yet.

Implemented scope:

- USDC-quoted spot products only; USD duplicates remain out of scope.
- Eligible products require spot product type, USDC quote currency, tradable
  status, positive price/increments/minimums, and no cancel-only/view-only style
  exchange restrictions.
- Dry-run BUY planning sizes requested USDC notional per product and checks
  paginated USDC wallet availability.
- Dry-run SELL planning estimates base size from requested USDC notional and
  checks paginated base wallet availability per product.
- Automation cadence arguments can be previewed, but no scheduler is installed
  or started.
- P/L snapshot helpers report product, portfolio, and since-last-purchase views
  from durable fill-ledger rows plus mark prices.

Acceptance:

- The dry-run CLI reports `live_coinbase_orders_ran: false` and
  `live_order_notional_usdc: "0"`.
- No live order placement, preview, cancel, or state mutation exists in this
  phase.
- The focused spot readiness gate includes
  `tests/regression/test_spot_portfolio_sweep.py`.

### Phase 13 - Sweep Live Execution Admission

Status: implemented for market IOC sweep execution.

Add live execution only after the dry-run output is reviewed against real
account inventory.

Required behavior:

- Require an explicit live-approval flag.
- Use the canonical order placement path and shared action-condition guards.
- Report submitted/executed notional for every live order.
- Keep BUY quote-size and SELL base-size behavior consistent with the dry-run
  planner.
- Surface partial failures with enough product/client-order context to
  reconcile manually.

Implemented scope:

- `tools/run_spot_portfolio_sweep_live.py` requires
  `--approved-live-orders` before any Coinbase submission path.
- BUY sweep execution submits market IOC quote-size orders.
- SELL sweep execution submits market IOC base-size orders derived by the
  planner.
- Each planned item rechecks `ActionConditionGuard` immediately before
  `create_order`.
- Live summaries include submitted/executed notional and per-order ids.
- Partial, blocked, and failed items are recorded in the summary and durable
  run ledger.

### Phase 14 - Durable Sweep Automation

Status: implemented as run-if-due CLI automation.

Add recurring sweep execution only after live one-shot execution is stable.

Required behavior:

- Persist sweep run configuration, run attempts, per-product decisions, order
  ids, and terminal outcome.
- Enforce repeat interval and max-run limits durably across process restarts.
- Rebuild each run from fresh Coinbase product and wallet data.
- Provide a stop/disable path before any next scheduled run.

Implemented scope:

- Automation is not a daemon. A scheduler invokes
  `tools/run_spot_portfolio_sweep_live.py` periodically, and the tool runs at
  most one due sweep before exiting.
- `--repeat-every-hours` and `--max-runs` are enforced from the JSONL ledger.
- `--disable-automation` writes a stop record and exits without live orders.
- The default ledger path is gitignored: `runtime_state/spot_portfolio_sweeps.jsonl`.

### Phase 15 - Spot Sweep Operator Surface

Status: implemented.

Bring sweep plans, live run summaries, and automation ledger state into the
dashboard after the CLI path has enough operational use.

Implemented scope:

- `dashboard_server.py` responds to `request_spot_sweep_status` by reading the
  durable sweep JSONL ledger and summarizing config count, run count,
  submitted/executed notional, latest run, and latest reconciliation.
- `ui_stealth_orders_manager.html` shows a read-only Spot Sweep Status panel.
- Live sweep approval and execution remain CLI-only.
- The dashboard surface calls `business.spot_portfolio_sweep` helpers instead
  of implementing separate ledger logic.

### Phase 16 - Sweep Run Reconciliation

Status: implemented.

Add a durable verification path for completed sweep runs.

Implemented scope:

- `reconcile_sweep_run_record` reads recorded exchange order ids, fetches live
  Coinbase order/fill evidence, checks `client_order_id` when Coinbase returns
  it, and appends `sweep_reconciliation` records.
- `tools/run_spot_portfolio_sweep_live.py --reconcile` runs reconciliation
  without `--approved-live-orders` because it does not submit orders.
- Reconciliation records summarize matched, not-submitted, missing exchange
  order, client-order-id mismatch, and fetch-error counts.

### Phase 17 - Sweep P/L Reporting Surface

Status: implemented for reusable reporting core.

Expose P/L reporting without adding a second calculation path.

Implemented scope:

- `build_spot_portfolio_pnl_snapshot` remains the canonical cashflow plus
  mark-to-market P/L calculation for product, portfolio, since-last-purchase,
  and FIFO realized-lot operational scopes.
- `build_spot_portfolio_pnl_snapshot_from_repo` adapts the existing fill-ledger
  repository to that canonical P/L snapshot.
- The scope remains operational reporting, not tax accounting.

### Phase 18 - Sweep Safety Policy Configuration

Status: implemented.

Add artificial account/run safety limits that can be configured independently
of Coinbase wallet availability.

Implemented scope:

- `SpotPortfolioSweepSafetyPolicy` supports `max_total_notional_per_run`,
  `max_notional_per_order`, `max_planned_orders`, `max_skipped_orders`,
  `allow_products`, and `deny_products`.
- Live CLI safety is evaluated after wallet-aware planning and before the first
  Coinbase `create_order`.
- Safety blocks write durable failed run records with
  `live_coinbase_orders_ran: false` and zero submitted/executed notional.

### Phase 19 - Limit-Price Sweep Execution Policy

Status: implemented.

Add explicit limit execution policies without changing the default market path.

Implemented scope:

- `--order-type market_ioc` remains the default.
- `--order-type limit_gtc` and `--order-type limit_gtc_post_only` use the
  rounded planned base size for both BUY and SELL.
- `--limit-price-offset-bps` prices BUY limits above the current product mark
  and SELL limits below the mark, rounded to the product price increment.
- The action-condition guard evaluates the exact base size and limit price
  that will be sent to Coinbase.

### Phase 20 - Real Sweep P/L Surface

Status: implemented.

Wire P/L reporting into operator-facing surfaces.

Implemented scope:

- `build_spot_portfolio_pnl_report` builds one canonical report from Coinbase
  public USDC spot marks plus local fill-ledger rows.
- `tools/run_spot_portfolio_sweep_live.py --pnl-report` prints the read-only
  report without live-order approval.
- `dashboard_server.py` responds to `request_spot_sweep_pnl`, and the stealth
  orders manager shows a read-only Spot Sweep P/L panel.
- The report includes cashflow, mark-to-market, since-last-purchase, and FIFO
  realized-lot operational views. It is not tax accounting.

### Phase 21 - Read-Only Sweep Reconciliation Trial

Status: implemented as a CLI/dashboard-ready read path.

Validate reconciliation without submitting orders.

Implemented scope:

- `--reconcile` remains independent of `--approved-live-orders`.
- Reconciliation records are appended to the same JSONL ledger as sweep runs.
- Operator status displays the latest reconciliation summary per config.

### Phase 22 - Approved Live Spot Validation Matrix

Status: implemented in tooling; live execution remains manual and explicit.

Add a small real-Coinbase validation matrix for spot order types.

Implemented scope:

- `tools/run_live_spot_usdc_smoke.py --validation-matrix` selects the cheapest
  previewable USDC spot product and runs market BUY, post-only limit BUY
  cancel, post-only limit SELL cancel, and market SELL.
- The summary reports every live order and submitted/executed notional.
- `--retain-inventory` skips the final market SELL when acquired base should
  remain in the account for future tests.

### Phase 23 - SELL Sweep Known-Inventory Policy

Status: implemented.

Add an optional profitability authority policy for portfolio SELL sweeps.

Implemented scope:

- `SpotPortfolioSweepSafetyPolicy` supports
  `require_known_profitable_inventory`.
- The live CLI exposes this through `--require-known-profitable-inventory`.
- When enabled for SELL, each planned sweep item must be covered by known
  profitable fill-ledger or imported baseline lots at the planned market
  estimate or exact limit price.
- Wallet balance remains necessary but is not treated as profit authority.

### Phase 24 - Public Release Sweep Runbook Hardening

Status: implemented.

Document public-safe operating modes and failure handling.

Implemented scope:

- The feature README and examples document read-only P/L, reconciliation,
  safety caps, known-inventory SELL gating, and the live validation matrix.
- The external testing runbook documents live matrix use and the requirement to
  report all submitted/executed notional.

### Phase 25 - Durable Live Smoke Audit

Status: implemented.

Persist approved live spot smoke summaries to a JSONL audit file.

Implemented scope:

- `tools/run_live_spot_usdc_smoke.py` appends each live summary to
  `runtime_state/live_spot_usdc_smoke.jsonl` by default.
- The summary records product selection, every order, retained inventory,
  submitted/executed notional, fill-backfill result, and audit file path.

### Phase 26 - Fill Ledger Backfill From Live Smoke

Status: implemented.

Backfill Coinbase REST fills from approved live smoke orders into
`fill_ledger`.

Implemented scope:

- `business.spot_fill_backfill` converts Coinbase REST fills into deterministic
  fill-ledger rows keyed by `client_order_id`, exchange order id, and fill id.
- Backfill is idempotent and reports appended, duplicate/accepted, skipped, and
  error status.

### Phase 27 - Sweep Fill Reconciliation To Fill Ledger

Status: implemented.

Tie sweep reconciliation to local fill-ledger evidence.

Implemented scope:

- `reconcile_sweep_run_record` compares Coinbase REST fill base/notional totals
  with local fill-ledger rows by `client_order_id` when available.
- Reconciliation summaries include fill-ledger match status counts.
- Live sweep execution backfills REST fills after submitted orders unless
  `--skip-fill-backfill` is supplied.

### Phase 28 - Sweep Config File Format

Status: implemented.

Add a stable config-file entry point for repeatable sweep definitions.

Implemented scope:

- `tools/run_spot_portfolio_sweep_live.py --config-file <path>` accepts
  version `1` JSON with side, quote notional, product cap, order policy,
  cadence, max runs, config id, and safety policy.
- CLI values override config-file fields where supplied.

### Phase 29 - Config Validation And Dry-Run Explain

Status: implemented.

Validate config files without live order approval.

Implemented scope:

- `--validate-config` rebuilds a fresh wallet-aware plan, evaluates safety, and
  prints plan explain rows.
- It uses Coinbase read calls only and does not submit orders.

### Phase 30 - Lot-Aware SELL Dry-Run Details

Status: implemented.

Show why SELL sweep rows are or are not supported by profitable inventory.

Implemented scope:

- Plan explain rows include SELL lot authority details when local fill-ledger
  or imported baseline lots are available.
- Unknown/unavailable cost-basis state is explicit; wallet balance is not
  treated as profit authority.

### Phase 31 - Dashboard P/L Detail View

Status: implemented.

Expose more of the existing P/L snapshot in the operator UI.

Implemented scope:

- The Spot Sweep P/L panel shows up to eight product detail rows sorted by
  absolute P/L impact, including total P/L, net base, and since-last-purchase
  P/L.

### Phase 32 - Dashboard Sweep Run Detail View

Status: implemented.

Expose sweep order and fill-backfill details in the operator UI.

Implemented scope:

- Operator status includes recent run details, latest run order rows, and
  fill-backfill counts.
- The Spot Sweep Status panel renders latest order rows and backfill totals.

### Phase 33 - Public Release Spot Gate Command

Status: implemented.

Package read-only release checks behind one command.

Implemented scope:

- `python tools/run_spot_release_gate.py` runs the focused spot readiness gate
  and prints `SPOT_RELEASE_GATE_SUMMARY`.
- Optional flags include browser smoke and read-only Coinbase-backed status/P/L
  checks.
- The command never submits live Coinbase orders.

### Phase 34 - Live Matrix Reconciliation Gate

Status: implemented; live execution remains explicit.

Add a live pass/fail gate for the approved validation matrix.

Implemented scope:

- `python tools/run_live_spot_usdc_smoke.py --approved-live-orders --validation-matrix --reconciliation-gate`
  runs the live matrix and fails if executed market orders cannot fetch REST
  fills and backfill local fill-ledger evidence.
- Live runs must still report product, every order, submitted notional, and
  executed notional.

### Phase 35 - Failure Mode Runbook

Status: implemented.

Document what to do when live/read-only checks fail.

Implemented scope:

- The external testing runbook documents backfill failures, retained inventory,
  live matrix reporting, and reconciliation-gate usage.
- The feature examples document config validation, release gating, and
  fill-backfill controls.

### Phase 36 - Spot Automation Readiness Review

Status: implemented.

Summarize the current automation readiness boundary.

Review:

- Confident spot automation now has wallet-aware planning, execution-time guard
  checks, artificial run caps, durable run history, fill backfill, P/L reporting,
  read-only config validation, dashboard status, and explicit live gates.
- Remaining risk is operational, not architectural: Coinbase/account read
  errors, local DB availability for fill-ledger evidence, market slippage on
  market IOC orders, and feature misuse with too-large notional caps.
- Spot-specific strategy work should build on the sweep config/explain and
  fill-ledger authority paths instead of adding separate placement or P/L logic.

### Phase 37 - Fill Ledger Schema Hardening

Status: implemented.

Harden the fill-ledger schema for generated live client order ids.

Implemented scope:

- `fill_ledger.client_order_id` now uses `VARCHAR(128)` in both creation paths.
- Existing deployments self-migrate with an idempotent
  `ALTER TABLE fill_ledger ALTER COLUMN client_order_id TYPE VARCHAR(128)`.
- Regression coverage asserts the widened schema and migration are present.

### Phase 38 - Backfill Error Recovery Command

Status: implemented.

Add a non-order-submitting recovery command for missed REST-fill backfill.

Implemented scope:

- `tools/run_spot_fill_backfill_recovery.py` reads live smoke and sweep JSONL
  audit records.
- `--dry-run` reports candidate and eligible order counts without Coinbase
  calls or DB writes.
- Non-dry-run mode reuses the existing idempotent
  `backfill_fill_ledger_from_order_reports` path.
- Summaries report zero live Coinbase order notional.

### Phase 39 - Durable Inventory Coverage Report

Status: implemented.

Report whether account inventory is explained by local fill-ledger or imported
baseline evidence.

Implemented scope:

- `build_spot_inventory_coverage_report` compares eligible USDC spot wallets
  against known and unknown local lot evidence.
- Coverage statuses distinguish covered, unknown-cost-basis, wallet-only,
  no-wallet-balance, and unavailable evidence.
- `tools/run_spot_portfolio_sweep_live.py --inventory-coverage` exposes the
  report without live-order approval.

### Phase 40 - Realized P/L Lot Exit Tracking

Status: implemented.

Add realized operational P/L from known FIFO lot exits.

Implemented scope:

- P/L snapshots include `SpotPortfolioPnlScope.REALIZED_LOT`.
- Product and portfolio reports include FIFO realized P/L, matched sell base,
  unmatched sell base, open base, and realized exit count.
- Unmatched sells remain explicit unknown-cost-basis exits. The report is not
  tax accounting.

### Phase 41 - Sweep Config Registry

Status: implemented.

Expose durable sweep configuration state separately from raw run status.

Implemented scope:

- `build_sweep_config_registry` summarizes config id, disabled state, run
  counts, latest run, latest reconciliation, and latest fill-backfill state.
- `tools/run_spot_portfolio_sweep_live.py --config-registry` prints the
  registry without Coinbase calls or live approval.

### Phase 42 - Automation Supervisor Recipe

Status: implemented.

Document a concrete supervisor pattern for recurring sweep automation.

Implemented scope:

- The sweep examples include a Windows Task Scheduler recipe that invokes the
  run-if-due CLI with a versioned config file.
- The docs clarify that Task Scheduler starts the process only; the CLI still
  enforces approval, cadence, max runs, safety policy, action guard, fill
  backfill, and the durable run ledger.

### Phase 43 - Sweep Recovery And Reconciliation Gate

Status: implemented.

Add a read/write local recovery gate for durable sweep audit state.

Implemented scope:

- `tools/run_spot_sweep_recovery_gate.py` plans missing reconciliation and
  fill-backfill retry work from the sweep JSONL ledger.
- `--dry-run` reports pending recovery work with no Coinbase calls or DB writes.
- Non-dry-run mode appends missing `sweep_reconciliation` records and retries
  fill-ledger backfill through existing helper paths.
- The gate reports zero live Coinbase order notional and fails when recovery
  leaves reconciliation or fill-backfill errors.

### Phase 44 - Small Live Sweep Canary

Status: implemented.

Run a minimal approved live sweep through the production sweep path.

Implemented scope:

- Read-only validation confirmed a one-product BUY sweep plan before live
  order submission.
- A one-product market IOC BUY sweep was submitted with explicit
  `--approved-live-orders`.
- Live summaries reported submitted and executed USDC notional.
- Fill backfill appended Coinbase REST fill evidence into `fill_ledger`.
- Read-only reconciliation matched Coinbase order/fill evidence against the
  local fill ledger by `client_order_id`.
- The canary exposed and fixed:
  - order-specific fill lookup now uses order id alone instead of combining
    order and product filters rejected by Coinbase;
  - `fill_ledger.price` now uses high-scale decimal precision for low-price
    spot products.

## Deferred Until After Readiness

- Spot-specific strategy features that depend on lot-aware exits.
- Auto-hotpoint placement for spot.
- Spot move/reprice UX beyond explicit disabled/conditional feedback.
- Tax/reporting semantics for realized spot lots.
- Multi-currency quote balancing beyond the configured product metadata.
