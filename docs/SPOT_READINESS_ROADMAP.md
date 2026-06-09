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
- Sweep inventory coverage and P/L reporting can optionally include Coinbase
  portfolio average cost basis as an explicit source separate from exact local
  fill-ledger lots.
- SELL sweep authority can optionally use Coinbase average cost basis with an
  extra configured profit buffer. This remains disabled by default.
- Cost-basis drift auditing can compare local fill-ledger average basis with
  Coinbase average basis without submitting orders.
- Sweep config registry reporting is available through
  `python tools/run_spot_portfolio_sweep_live.py --config-registry`.
- Sweep P/L reports include a FIFO realized-lot operational reporting scope.
- Fill-ledger rows loaded from the DB normalize `product_id` from `instrument`
  when the schema has no separate product-id column, so P/L grouping remains
  reproducible from persisted fill evidence.
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
- Spot campaign BUY rollout has run through one-product, five-product,
  recovered ten-product, 25-product, and all-eligible USDC stages. The
  all-eligible stage submitted 385 live orders for 385 USDC planned notional,
  skipped two below-minimum products, and passed recovery reconciliation.
- Scheduled live BUY automation has run two approved 5-product canary runs
  with `max_runs: 2`, UUID Coinbase-facing `client_order_id` values,
  submission evidence recorded, fill backfill appended, and recovery
  reconciliation matched. The two BUY runs submitted `10` USDC total notional
  and executed `9.9160518` USDC.
- A small approved live SELL canary has run for `ACX-USDC` using exact
  fill-ledger known-profitable authority, not Coinbase average-cost authority.
  It submitted `1.04975` USDC notional, executed `1.04732262479` USDC, appended
  one fill, and passed recovery reconciliation.
- Post-canary P/L review for `ACX-USDC` now shows local fill-ledger P/L,
  FIFO realized-lot P/L, since-last-purchase P/L, and Coinbase average-cost
  P/L in the same read-only report. These remain operational reports, not tax
  accounting.
- Campaign dashboard status now exposes a read-only operator summary with
  readiness, due state, lock state, recovery state, planned skips, live run
  state, submitted/executed notional, and P/L summary.
- The next all-USDC spot campaign feature intake is captured in
  `docs/examples/spot-feature-intake-usdc-campaign.json` and passes the local
  feature-intake gate.
- The contextless blind-agent gate passed on 2026-06-09 for the current spot
  order path, including dashboard direct placement, stealth reveal, USDC sweep
  live execution, campaign orchestration, `client_order_id` invariants, and
  reconciliation.

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
- Keep spot order behavior understandable to a contextless reader. New spot
  order behavior must pass the blind-agent readability gate in
  `docs/SPOT_CONTEXTLESS_AGENT_TESTING.md`; if it fails, fix docs or code
  organization before broadening the feature.

## Persistent Readiness Gates

These gates apply to every future spot phase that changes order creation,
planning, admission, live execution, campaign automation, inventory authority,
or reconciliation:

- Required regression:
  `pytest tests/regression/ -v --tb=short`.
- Focused spot readiness where relevant:
  `python tools/run_spot_readiness_regression.py`.
- Read-only release/campaign gates before live order approval.
- Explicit live approval and notional reporting for every Coinbase order test.
- Contextless blind-agent readability test from
  `docs/SPOT_CONTEXTLESS_AGENT_TESTING.md`.

The blind-agent gate passes only when a fresh agent can identify the canonical
spot order path, safety gates, live approval boundary, `client_order_id`
invariant, campaign/sweep split, wallet-vs-cost-basis distinction, and
reconciliation path without being coached.

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

### Phase 45 - Spot Feature Intake Gate

Status: implemented.

Require a concrete, auditable request before building the next spot-specific
feature.

Implemented scope:

- `tools/run_spot_feature_intake_gate.py` validates local JSON feature
  requests without Coinbase calls.
- The gate requires exact USDC product scope, US-customer availability,
  order sides, order policies, automation cadence, live approval rule, notional
  caps, inventory retention policy, and minimum audit evidence.
- Incomplete intake reports `phase_50_ready: false`; passing intake reports
  `phase_50_ready: true`.
- Examples live in `docs/examples/spot-feature-intake.md`.

### Phase 46 - Fill-Ledger Data Health Audit

Status: implemented.

Add a local audit surface for fill-ledger evidence used by spot inventory,
P/L, and reconciliation.

Implemented scope:

- `business.spot_fill_ledger_health` analyzes USDC fill-ledger rows for
  zero-price, zero-notional, missing `client_order_id`, non-positive quantity,
  and reconciled rows without exchange evidence.
- `tools/run_spot_fill_ledger_health.py` runs the audit and prints
  `SPOT_FILL_LEDGER_HEALTH`.
- The audit is read-only, does not call Coinbase, and reports zero live order
  notional.

### Phase 47 - Fill-Ledger Repair Command

Status: implemented.

Add an explicit repair path for suspicious local spot fill rows.

Implemented scope:

- `tools/run_spot_fill_ledger_repair.py --plan-only` reports repair candidates
  from local evidence only.
- Non-plan dry runs fetch Coinbase REST fills read-only for already-recorded
  exchange order ids and plan exact row corrections.
- `--apply` is required before local `fill_ledger` rows are updated.
- Repairs target a single row by `id` and `derived_trade_key`, keeping
  corrections narrow and auditable.
- The command never submits Coinbase orders.

### Phase 48 - Durable Recovery And Correction Records

Status: implemented.

Make recovery and correction evidence first-class durable state.

Implemented scope:

- Sweep recovery gate runs append `sweep_recovery` records when they attempt
  reconciliation or fill-backfill recovery.
- Sweep operator status/config registry exposes latest recovery status when a
  recovery record is scoped to a config.
- Fill-ledger repair runs append records to
  `runtime_state/spot_fill_ledger_repairs.jsonl` when `--apply` is used, or
  when dry-run evidence is explicitly requested with `--record-dry-run`.

### Phase 49 - Inventory Coverage Baseline Review

Status: implemented in tooling; current account baseline should be refreshed
with a read-only run when credentials are available.

Implemented scope:

- Existing `--inventory-coverage` remains the baseline review command for
  wallet inventory versus fill-ledger/imported evidence.
- The recommended baseline command is:
  `python tools/run_spot_portfolio_sweep_live.py --inventory-coverage --summary-only`.
- The command reads Coinbase wallets and product metadata, writes no orders,
  and reports zero live order notional.

### Phase 50 - First Post-Readiness Spot-Specific Feature

Status: superseded by Phases 51-60 cost-basis authority hardening before the
first larger spot-specific feature.

Do not implement this by guessing the feature. The next spot-specific feature
should start only after `tools/run_spot_feature_intake_gate.py` passes for the
actual request. The implementation should reuse existing sweep planning,
action-condition guards, live approval, fill-backfill, P/L, and recovery
surfaces unless the request proves those paths are insufficient.

### Phase 51 - Coinbase Cost-Basis Source Verification

Status: implemented.

Verify that Coinbase portfolio data exposes average cost basis in a form that
can be used safely as an operational authority input.

Implemented scope:

- Official Coinbase Advanced Trade portfolio endpoints were checked for
  portfolio listing and portfolio breakdown support.
- The local SDK wrapper now uses `get_portfolios` and
  `get_portfolio_breakdown` when available.
- The verified data shape is asset-level `spot_positions`; USDC product ids
  are derived by matching each asset to eligible `BASE-USDC` products.

### Phase 52 - Cost-Basis Authority Vocabulary

Status: implemented.

Make cost-basis source and status explicit instead of overloading wallet or
lot coverage states.

Implemented scope:

- Shared enums now include Coinbase average cost as an inventory lot source,
  SELL authority status, coverage status, P/L scope, cost-basis source, and
  cost-basis status.
- Imported baselines preserve their `lot_source`, so average-cost baselines
  cannot be confused with local fill-ledger lots.

### Phase 53 - Coinbase Average-Cost Import

Status: implemented.

Add a read-only import path for Coinbase portfolio average cost.

Implemented scope:

- `business.spot_cost_basis` parses Coinbase portfolio breakdown
  `spot_positions` into USDC product records.
- Available records can be converted into known-cost baseline lots tagged with
  `InventoryLotSource.COINBASE_AVERAGE_COST`.
- `tools/run_spot_portfolio_sweep_live.py --cost-basis-baseline` reports the
  imported baseline without live-order approval.

### Phase 54 - Inventory Coverage With Average-Cost Authority

Status: implemented.

Improve account inventory coverage reporting without treating average-cost
authority as exact local lot evidence.

Implemented scope:

- `--inventory-coverage --include-coinbase-average-cost` adds Coinbase average
  cost records to the coverage report.
- Coverage status can now distinguish local covered inventory, imported
  unknown-cost inventory, Coinbase average-cost coverage, wallet-only balances,
  no wallet balance, and unavailable evidence.

### Phase 55 - Optional Average-Cost SELL Authority

Status: implemented and disabled by default.

Allow Coinbase average cost to satisfy SELL profitability authority only when
the operator explicitly opts in.

Implemented scope:

- Sweep safety policy supports `allow_coinbase_average_cost_basis` and
  `coinbase_average_cost_profit_buffer_pct`.
- The live CLI exposes `--allow-coinbase-average-cost-basis` and
  `--coinbase-average-cost-profit-buffer-pct`.
- SELL authority first checks exact local/imported known lots. Coinbase
  average-cost lots are considered only after that path fails and only when
  the opt-in flag is enabled.

### Phase 56 - Average-Cost P/L Scope

Status: implemented.

Add average-cost P/L as a separate operational reporting scope.

Implemented scope:

- `build_spot_portfolio_pnl_report` can include `average_cost_pnl` when
  Coinbase average-cost records are supplied.
- CLI P/L uses `--pnl-report --include-coinbase-average-cost`.
- Dashboard P/L accepts `include_coinbase_average_cost` as an opt-in request
  parameter and keeps the default public-mark/local-fill report unchanged.

### Phase 57 - Cost-Basis Operator Visibility

Status: implemented for CLI and dashboard P/L request payloads.

Surface average-cost authority in operator outputs.

Implemented scope:

- Cost-basis baseline, coverage, P/L, validation explain, and drift audit
  summaries report their read-only Coinbase request list.
- Plan explain rows report the SELL authority source and Coinbase
  average-cost profitable quantity when the opt-in path is used.
- Dashboard P/L reports include average-cost P/L only when explicitly
  requested.

### Phase 58 - Read-Only Average-Cost Baseline Review

Status: implemented in tooling; refresh with credentials when needed.

Add a read-only baseline command for the current account.

Implemented scope:

- `python tools/run_spot_portfolio_sweep_live.py --cost-basis-baseline --summary-only`
  fetches Coinbase products, portfolios, and portfolio breakdown data.
- The command writes no local data, submits no orders, and reports zero live
  Coinbase order notional.

### Phase 59 - Cost-Basis Drift Audit

Status: implemented.

Compare local fill-ledger average basis with Coinbase average basis.

Implemented scope:

- `build_cost_basis_drift_audit` reports per-product local average,
  Coinbase average, drift, drift percentage, and status.
- `python tools/run_spot_portfolio_sweep_live.py --cost-basis-drift-audit --summary-only`
  exposes the audit without live-order approval.

### Phase 60 - Spot Feature Intake Cost-Basis Requirements

Status: implemented.

Make future feature requests state their cost-basis authority explicitly.

Implemented scope:

- `tools/run_spot_feature_intake_gate.py` requires
  `cost_basis_authority.allowed_sources`.
- If `coinbase_average_cost` is allowed, intake also requires
  `cost_basis_authority.coinbase_average_cost_profit_buffer_pct`.
- The feature-intake examples include the new cost-basis authority block.

### Phase 61 - Durable Average-Cost Snapshots

Status: implemented.

Persist read-only Coinbase average-cost snapshots locally for later operator
review.

Implemented scope:

- Cost-basis snapshot records use `spot_cost_basis_snapshot` audit records.
- `tools/run_spot_portfolio_sweep_live.py` supports
  `--record-cost-basis-snapshot` and `--cost-basis-state-file`.
- `--cost-basis-status` summarizes the durable local snapshot ledger without
  Coinbase calls.

### Phase 62 - Cost-Basis Gap Triage

Status: implemented.

Triage remaining wallet-only, missing-position, stale, and local-lot gaps.

Implemented scope:

- `build_cost_basis_gap_triage` summarizes unresolved cost-basis gaps from
  inventory coverage plus drift audit output.
- `--cost-basis-triage` builds coverage, drift, and triage in one read-only
  Coinbase-backed command.
- Triage summaries report zero live Coinbase order notional.

### Phase 63 - Cost-Basis Config Validation

Status: implemented.

Make average-cost authority choices stricter before live use.

Implemented scope:

- `--allow-coinbase-average-cost-basis` is valid only for SELL.
- It now requires `--require-known-profitable-inventory`; otherwise the flag
  would be inert and misleading.
- Recording an inventory-coverage cost-basis snapshot requires
  `--include-coinbase-average-cost`.

### Phase 64 - Release Gate Cost-Basis Checks

Status: implemented.

Add cost-basis checks to the opt-in read-only Coinbase release gate.

Implemented scope:

- `python tools/run_spot_release_gate.py --include-coinbase-readonly` now runs
  average-cost inventory coverage and cost-basis drift audit checks in addition
  to sweep status and P/L.
- The release gate still never submits live Coinbase orders.

### Phase 65 - Dashboard Cost-Basis Summaries

Status: implemented.

Expose cost-basis state to operators from durable local snapshots.

Implemented scope:

- `dashboard_server.py` responds to `request_spot_cost_basis_status` by reading
  `runtime_state/spot_cost_basis_snapshots.jsonl` by default.
- `ui_stealth_orders_manager.html` shows a read-only Spot Cost Basis panel with
  latest baseline, coverage, drift, and triage summary counts.
- The dashboard request reads local state only; it does not call Coinbase.

### Phase 66 - Scheduled Job Overlap Protection

Status: implemented.

Prevent scheduled sweep and cost-basis snapshot jobs from overlapping.

Implemented scope:

- `tools/run_spot_portfolio_sweep_live.py` uses an exclusive local operation
  lock for live/ledger-writing paths and cost-basis snapshot recording.
- `--operation-lock-file`, `--lock-stale-after-seconds`, and
  `--disable-run-lock` are available for controlled operator use.
- Local-read-only status/P&L/config-registry modes do not take the lock.

### Phase 67 - Formal Spot Campaign Intake Artifact

Status: implemented.

Create a concrete feature-intake artifact for the all-USDC notional buy/sell
campaign before campaign-specific implementation begins.

Implemented scope:

- `business.spot_campaign.build_spot_campaign_intake_request` generates the
  existing spot feature-intake request shape from a campaign config.
- `tools/run_spot_campaign.py --intake` validates the generated request through
  the existing `tools/run_spot_feature_intake_gate.py` logic.
- Campaign intake remains local-only and reports zero live Coinbase order
  notional.

### Phase 68 - Campaign Config Schema

Status: implemented.

Define a stable campaign config schema for side, notional, cadence, max runs,
product scope, safety caps, inventory retention, and cost-basis authority.

Implemented scope:

- `business.spot_campaign.normalize_spot_campaign_config` validates versioned
  campaign JSON.
- Campaign config normalizes to a stable campaign id and existing sweep config
  id.
- `tools/run_spot_campaign.py --write-sweep-config-file` renders the equivalent
  existing sweep config schema for live canary execution through the sweep
  runner.

### Phase 69 - Durable Campaign P/L Snapshots

Status: implemented.

Persist per-run campaign P/L snapshots so tracking does not depend only on
rebuilding from fill-ledger state later.

Implemented scope:

- Campaign snapshots append to `runtime_state/spot_campaigns.jsonl` by default.
- Snapshot records include plan, safety evaluation, automation due-state,
  summarized P/L, cost-basis summary, release gate, and submitted/executed
  notional fields.
- `tools/run_spot_campaign.py --record-snapshot` records dry-run or release
  gate snapshots.

### Phase 70 - Campaign Dry-Run Matrix

Status: implemented.

Add a read-only campaign dry-run matrix across all eligible USDC products.

Implemented scope:

- `tools/run_spot_campaign.py --dry-run-matrix` reads products/wallets, builds
  the existing sweep plan, evaluates sweep safety, and emits per-product explain
  data.
- The matrix can include Coinbase average cost basis for read-only P/L,
  coverage, drift, and SELL authority explanation when explicitly configured.
- The dry-run matrix never submits live Coinbase orders.

### Phase 71 - Campaign Dashboard Status

Status: implemented.

Expose campaign config, due state, latest run, P/L snapshot, and recovery state
in the dashboard as read-only operator status.

Implemented scope:

- `dashboard_server.py` handles `request_spot_campaign_status` by reading the
  local campaign snapshot ledger.
- `ui_stealth_orders_manager.html` renders a Spot Campaigns panel with latest
  campaign, plan, gate, notional, and P/L summary.
- Dashboard campaign status does not call Coinbase.

### Phase 72 - Campaign Release Gate

Status: implemented.

Add a campaign release gate that checks config validation, product universe,
coverage, drift, P/L, scheduler lock, and recovery readiness.

Implemented scope:

- `tools/run_spot_campaign.py --release-gate` validates intake, dry-run plan,
  safety policy, operation-lock state, and recovery readiness.
- `tools/run_spot_release_gate.py --campaign-config-file <path>` includes the
  campaign release gate in the read-only release wrapper.
- Focused regression now includes `tests/regression/test_spot_campaign.py`.

### Phase 73 - One-Product Campaign Live Canary

Status: implemented.

Run the campaign config path against one eligible USDC product with explicit
live approval and reported submitted/executed notional.

Implemented live result:

- Live Coinbase run: yes.
- Product: `00-USDC`.
- Submitted notional: `1` USDC.
- Executed notional: `0.999288` USDC.
- Fill backfill: 1 fetched, 1 appended.
- Reconciliation: matched.

### Phase 74 - Small Allowlist Campaign Canary

Status: implemented.

Run the campaign path against a small allowlist, likely 3-5 products, with hard
notional caps and full reconciliation/backfill.

Implemented live result:

- Live Coinbase run: yes.
- Products: `00-USDC`, `1INCH-USDC`, `2Z-USDC`, `A8-USDC`, `AAVE-USDC`.
- Submitted notional: `5` USDC.
- Executed notional: `4.937607` USDC.
- Fill backfill: 6 fetched, 6 appended across 5 orders.
- Reconciliation: 5 matched orders.

### Phase 75 - Campaign Post-Live Recovery Gate

Status: implemented.

After campaign canaries, run reconciliation, fill backfill, P/L snapshot, and
cost-basis drift snapshot as one recovery gate.

Implemented scope:

- Recovery gate reconciled the one-product and five-product live canaries.
- Follow-up recovery reconciled the ten-product partial run and the zero-notional
  SELL safety-blocked run.
- Cost-basis triage snapshot was refreshed after live runs.

### Phase 76 - Staged Campaign Expansion

Status: implemented through all-eligible USDC live stage.

Expand from 10 products to 25 products to all eligible USDC products only if
prior stages pass.

Implemented live result:

- 10-product stage live Coinbase run: yes.
- Submitted notional: `9` USDC.
- Executed notional: `8.900615702619` USDC.
- Result: partial. `ACX-USDC` was blocked before placement when Coinbase
  returned HTTP 503 during the pre-execution wallet guard.
- Reconciliation: 9 matched filled orders and 1 not-submitted blocked item.
- The `ACX-USDC` retry in Phase 79 submitted `1` USDC and executed
  `0.9906352335` USDC, making the recovered 10-product stage `10` USDC
  submitted and `9.891250936119` USDC executed.
- 25-product stage live Coinbase run: yes.
- 25-product submitted notional: `25` USDC.
- 25-product executed notional: `24.81686323945694321` USDC.
- 25-product recovery gate: passed with 25 matched orders and matched fill
  ledger evidence.
- All-eligible USDC stage live Coinbase run: yes.
- All-eligible plan selected 387 products, submitted 385 orders, and skipped
  `API3-USDC` and `CTX-USDC` because the 1 USDC request rounded below each
  product's `quote_min_size`.
- All-eligible submitted notional: `385` USDC.
- All-eligible executed notional from live summary:
  `381.4362450472677185` USDC.
- All-eligible recovery gate: passed with 385 matched orders, matched fill
  ledger evidence, and no pending backfill.
- Sweep and campaign status now classify planned skips as audit rows instead
  of execution failures, while preserving raw recorded status when historical
  rows were written before that fix.

### Phase 77 - SELL Campaign Canary

Status: implemented as guarded zero-notional canary.

Run SELL canaries using exact local lots first and Coinbase average-cost
authority only through the explicit opt-in buffer path.

Implemented result:

- 1 USDC SELL canary was blocked at release gate because the first selected
  product rounded below quote minimum.
- 2 USDC SELL canary reached exact local lot authority and was blocked as not
  known profitable.
- Live runner was invoked with explicit approval and recorded a safety-blocked
  run with no Coinbase SELL order submitted.
- Submitted notional: `0` USDC.
- Executed notional: `0` USDC.

### Phase 78 - All-USDC Campaign Readiness Review

Status: implemented after staged live rollout and recovery.

Review campaign safety, durability, reconciliation, P/L tracking, cost-basis
coverage, and dashboard visibility before treating broad all-USDC campaign
automation as stable.

Review result:

- Campaign config, intake, dry-run matrix, durable campaign snapshots, dashboard
  campaign status, release gate, and latest sweep-run recording are implemented.
- Live BUY canaries and staged campaign runs submitted `426` USDC total and
  executed `422.08125422284366171` USDC total across one-product,
  five-product, recovered ten-product, 25-product, and all-eligible stages.
- SELL canary submitted and executed `0` USDC because known-profit authority
  correctly blocked the planned sell.
- Broad all-eligible BUY execution has now passed release gate, live execution,
  fill backfill, recovery reconciliation, and campaign snapshot recording.
- Remaining stability work should focus on repeated scheduled operation,
  dashboard/operator ergonomics, and future SELL authority policy rather than
  basic all-USDC BUY execution.

### Phase 79 - Partial Campaign Retry Planning

Status: implemented with one-product live retry canary.

Build a targeted retry path for partial campaign sweep runs before broadening
to 25-product or all-eligible USDC execution.

Implemented scope:

- Sweep planning now applies product allow/deny scope before `max_products`
  selection, so scoped retry configs plan the intended product instead of the
  first alphabetic eligible USDC product.
- Sweep config ids now include non-empty product allow/deny scope to prevent
  targeted retry configs from colliding with ordinary one-product configs.
- `business.spot_campaign.build_spot_campaign_retry_plan` classifies source
  run orders and generates retry config only for products with no exchange
  order id and zero submitted/executed notional.
- Planned skips such as below-minimum quote-notional rows are not retry
  candidates and do not block campaign readiness by themselves.
- `tools/run_spot_campaign.py --retry-plan` can print the retry plan and write
  a normal campaign retry config with `--write-retry-config-file`.
- Retry planning submits no Coinbase orders. Live retry execution still uses
  the existing sweep runner and its explicit `--approved-live-orders` gate.

Implemented live retry result:

- Live Coinbase run: yes.
- Product: `ACX-USDC`.
- Submitted notional: `1` USDC.
- Executed notional: `0.9906352335` USDC.
- Fill backfill: 1 fetched, 1 appended.
- Reconciliation: matched order, matched fill ledger, no pending backfill.

### Phase 80 - Post-Live State Audit

Status: completed.

Verify that durable local state agrees after the all-eligible BUY rollout.

Scope:

- Compare sweep ledger, campaign ledger, fill ledger, recovery records,
  dashboard summaries, and P/L outputs for the live BUY rollout.
- Audit submission evidence consistency across direct dashboard placement,
  stealth reveal placement, and portfolio sweep live placement.
- Verify live sweep `client_order_id` values remain UUID text and that sweep
  identity comes from the JSONL ledger/event payloads rather than prefixed
  Coinbase-facing ids.
- Confirm all skipped products are explainable planned skips, not hidden
  exchange failures.
- Confirm no pending recovery/backfill work exists for the live BUY campaign.
- Run the contextless blind-agent gate and record any repo-context gaps.

Current blind-gate cleanup:

- Direct dashboard response normalization now handles SDK objects,
  `to_dict()`, and nested `success_response.order_id`.
- Live sweep defaults now generate UUID `client_order_id` values.
- Live sweep execution can publish `order_submitted` / `rest_submit` evidence
  through the shared event-stream publisher and records
  `submission_event_recorded` per submitted order.

Acceptance:

- Read-only audit reports no unresolved state mismatch.
- Any submission-evidence gap is either fixed in code or documented as a
  blocker before adding new spot order-creation surfaces.
- Blind-agent result either passes or produces concrete docs/code cleanup work
  that is completed before Phase 81 is treated as ready.

Result on 2026-06-09:

- Read-only release gate passed, including the focused spot readiness
  regression gate (`172 passed`) and Coinbase read-only sweep/campaign checks.
- The all-eligible BUY rollout remained explainable: 385 submitted live BUY
  orders for `385` USDC submitted notional, `381.4362450472677185` USDC
  executed notional, and two planned below-minimum skips.
- Recovery gating reported no unresolved reconciliation or backfill work for
  the all-eligible BUY campaign. Historical no-submission/skip records can
  still appear in `runs_needing_backfill`, but candidate backfill count is `0`
  and the gate status is `passed`.
- Submission evidence gaps from the blind-gate cleanup are closed for new
  direct dashboard and live sweep placements. Historical all-eligible BUY
  ledger rows still contain pre-fix `sswp-*` client ids, but new live sweep
  placements use UUID `client_order_id` values and keep sweep identity in the
  JSONL/event payloads.
- Blind-agent gate passed. The fresh agent identified the canonical direct
  dashboard, stealth, sweep, campaign, wallet, cost-basis, submission-evidence,
  and reconciliation paths without coaching.

### Phase 81 - Scheduled Automation Rehearsal

Status: completed.

Exercise recurring campaign behavior without placing Coinbase orders.

Scope:

- Validate run-if-due behavior, max-runs, disabled automation, stale lock
  handling, duplicate-run prevention, and recovery readiness from config files.
- Rehearse both BUY and SELL configs in read-only/dry-run modes.
- Verify dashboard/operator summaries show due state, lock state, and latest
  recovery state clearly.
- Rerun the blind-agent gate if the automation entry points or docs change.

Acceptance:

- Repeated invocations cannot double-submit or bypass max-runs.
- A contextless reader can identify how scheduled operation is invoked and
  stopped.

Result on 2026-06-09:

- The real all-product BUY campaign dry-run reported
  `automation_due.decision: max_runs_reached` for its exhausted
  `max_runs: 1` config and made no live Coinbase requests.
- The SELL campaign release gate blocked correctly with `no_planned_orders`
  when its `1` USDC plan rounded below Coinbase `quote_min_size`; this was an
  operator-visible planning block, not an exchange failure.
- The five-product BUY sweep config validated as allowed for five planned
  orders and `5` USDC planned notional.
- The automation primitive check returned `not_due`, `max_runs_reached`,
  `disabled`, and stale-lock visibility as expected. No Coinbase live orders
  were submitted during this rehearsal.

### Phase 82 - Limited Scheduled Live BUY Canary

Status: completed.

Validate cadence with small live BUY notional before trusting recurring broad
operation.

Scope:

- Use a small allowlist, likely 5-10 USDC products at `1` USDC each.
- Configure `max_runs: 2` and a short operator-approved cadence.
- Run recovery/backfill/reconciliation after each live run.
- Report live Coinbase submitted/executed notional per run and total.

Acceptance:

- Both scheduled live runs respect cadence, max-runs, operation lock, and
  recovery gates.
- No live order runs without explicit approval.

Result on 2026-06-09:

- Config id: `spot-scheduled-buy-canary-20260609-phase82`.
- Allowlist: `00-USDC`, `1INCH-USDC`, `2Z-USDC`, `A8-USDC`, `AAVE-USDC`.
- Run 1 (`spot-sweep-2370f5db-e963-46e2-b473-11d09ac408db`) submitted five
  live Coinbase BUY orders for `5` USDC submitted notional and
  `4.9582638` USDC executed notional. Fill backfill appended six fills and
  recovery matched all five orders.
- Run 2 (`spot-sweep-540b9fa7-d48b-4876-bd43-295516cbe3fe`) submitted five
  live Coinbase BUY orders for `5` USDC submitted notional and
  `4.957788` USDC executed notional. Fill backfill appended six fills and
  recovery matched all five orders.
- A third invocation with live approval skipped before Coinbase submission with
  `automation_decision.decision: max_runs_reached`, submitted `0` USDC, and
  later received a zero-order reconciliation marker.
- Total live Coinbase BUY notional for this phase: `10` USDC submitted and
  `9.9160518` USDC executed.
- All ten live BUY placements used UUID `client_order_id` values and recorded
  `order_submitted` / `rest_submit` submission evidence.

### Phase 83 - SELL Authority Readiness Review

Status: completed.

Classify which USDC spot products are safely sell-eligible under each authority
mode before broad SELL execution.

Scope:

- Build a read-only matrix for wallet balance, exact fill-ledger lots, imported
  baselines, unknown-cost inventory, Coinbase average-cost authority, and
  current profitability buffer.
- Separate sellability from known-profit authority in operator output.
- Identify products eligible for exact local-lot SELL canaries and products
  eligible only through explicit Coinbase average-cost authority.
- Include blind-agent review if SELL authority docs or code paths change.

Acceptance:

- SELL candidates are explained by authority source and buffer.
- Wallet-only inventory is not treated as profitable inventory.

Result on 2026-06-09:

- Strict `1` USDC SELL validation against the Phase 82 allowlist produced only
  planned skips because rounded sell sizes fell below Coinbase
  `quote_min_size`.
- Raising the read-only validation notional to `1.05` USDC proved wallet
  sellability for the same products, but exact local-lot authority blocked all
  five because known profitable quantity was zero or insufficient. Wallet-only
  inventory was not treated as profitable inventory.
- A full read-only SELL matrix at `1.05` USDC, with explicit Coinbase
  average-cost authority enabled only for classification, planned 376 products,
  skipped 11, found 84 authority-eligible products, and blocked 292 as
  `insufficient_known_profitable`.
- Of the 84 authority-eligible products, 50 had non-stale drift status and 34
  had stale local-vs-Coinbase average-cost drift status.
- Exact local fill-ledger candidates existed, so the next live SELL canary did
  not need Coinbase average-cost authority. `ACX-USDC` validated as an exact
  fill-ledger candidate with `24.7` planned base size, `1.04975` estimated USDC
  notional, and `71.1` known-profitable quantity.

### Phase 84 - Small Live SELL Canary

Status: completed.

Execute tightly scoped SELL orders only for products that passed Phase 83.

Scope:

- Prefer exact local fill-ledger lot authority first.
- Coinbase average-cost authority remains an explicit opt-in path with extra
  buffer and separate reporting.
- Use small notional, strict allowlist, recovery gate, fill backfill, and P/L
  review.
- Report live Coinbase submitted/executed notional.

Acceptance:

- SELL canary proves wallet checks, profitability authority, live placement,
  reconciliation, and P/L update without relying on futures short semantics.

Result on 2026-06-09:

- Config id: `spot-sell-canary-20260609-phase84`.
- Product: `ACX-USDC`.
- Authority source: exact local fill-ledger known-profitable inventory.
  Coinbase average-cost authority was not enabled for the live SELL.
- Live Coinbase SELL run
  (`spot-sweep-030922cf-2d47-4923-ab14-51fea8b99ed0`) submitted one market IOC
  SELL order with UUID `client_order_id`
  `30138784-eda8-4e0c-826a-1c2ec02e02ea`.
- Submitted notional: `1.04975` USDC.
- Executed notional: `1.04732262479` USDC.
- Fill backfill appended one fill, recovery reconciliation matched the
  Coinbase order and local fill-ledger row, and `submission_event_recorded` was
  true.
- Post-SELL read-only ACX average-cost P/L reported `71.8` ACX quantity,
  `2.95760585436333742` USDC cost basis, `3.0515` USDC mark value, and
  `0.09389414563666258` USDC unrealized P/L. This remains operational P/L, not
  tax accounting.

### Phase 85 - Campaign P/L Reconciliation Review

Status: completed.

Verify P/L views after retained inventory, repeated BUYs, and any SELL canary.

Scope:

- Compare per-product, all-USDC, since-last-purchase, FIFO realized-lot, and
  Coinbase average-cost P/L scopes.
- Confirm campaign snapshots are durable and reproducible from fill-ledger
  evidence.
- Document any P/L scope that is operational-only and not tax accounting.

Acceptance:

- Operators can explain realized vs unrealized movement without inspecting raw
  fill rows.

Result on 2026-06-09:

- A read-only `ACX-USDC` P/L run initially exposed a local P/L defect:
  Coinbase average-cost P/L and fill-ledger health showed valid inventory, but
  the fill-ledger P/L snapshot was empty.
- Root cause: persisted `fill_ledger` rows use `instrument` as the product
  identifier and the current DB schema has no `product_id` column. The
  fill-ledger/P&L boundary now normalizes `product_id` from `instrument` and
  P/L grouping explicitly falls back to `instrument` when `product_id` is null.
- Post-fix read-only ACX local fill-ledger P/L reported:
  - buy notional `2.97175522209` USDC;
  - sell notional `1.04732262479` USDC;
  - net base `46.4` ACX;
  - mark value `1.98128` USDC;
  - total P/L `0.0542350127` USDC;
  - FIFO realized-lot P/L `0.01354037222333333333333333343` USDC;
  - since-last-purchase P/L `0.01272382908` USDC.
- The same read-only report included Coinbase average-cost P/L for comparison:
  `71.8` ACX quantity, `2.94262361029000308` USDC cost basis,
  `3.06586` USDC mark value, and `0.12323638970999692` USDC unrealized P/L.
- No live Coinbase orders were submitted for this phase. Submitted notional:
  `0` USDC. Executed notional: `0` USDC.

### Phase 86 - Dashboard Operator Hardening

Status: completed.

Make the dashboard sufficient for routine spot operation review.

Scope:

- Surface latest campaign readiness, planned skips, next due time, lock state,
  recovery state, submitted/executed notional, and P/L summary.
- Keep dashboard read-only for campaign status and release readiness.
- Run browser smoke and blind-agent review if the user-facing workflow changes.

Acceptance:

- A human can determine whether spot automation is ready, blocked, due, or
  recovering without reading CLI JSON.

Result on 2026-06-09:

- `build_spot_campaign_operator_status` now exposes:
  `latest_readiness_snapshot`, `latest_live_snapshot`, and
  `operator_summary`.
- `operator_summary` includes readiness/gate state, automation decision,
  next-run time, run count, max runs, operation-lock state, recovery counts,
  planned/skipped order counts, safety decision, latest live run id/status,
  submitted/executed notional, and P/L summary.
- The campaign dashboard panel renders the operator state, campaign, plan,
  automation, lock, recovery, latest live run, notional, and P/L without
  requiring raw CLI JSON.
- The status response remains read-only and local-ledger-only; it does not call
  Coinbase and cannot approve or submit live orders.
- No live Coinbase orders were submitted for this phase. Submitted notional:
  `0` USDC. Executed notional: `0` USDC.

### Phase 87 - Spot Feature Intake For The New Feature

Status: completed.

Before implementing the next requested spot-specific feature, run it through
the feature-intake gate and the blind-agent readability gate.

Scope:

- Capture exact USDC product scope, side(s), order policy, cadence, max runs,
  inventory retention, cost-basis authority, live approval rule, notional caps,
  and required audit evidence.
- Reject feature shapes that require a parallel placement path or ambiguous
  spot short semantics.

Acceptance:

- The feature can be described using existing spot sweep/campaign/order
  primitives, or the roadmap explicitly records why new primitives are needed.

Result on 2026-06-09:

- The requested feature shape is captured as
  `docs/examples/spot-feature-intake-usdc-campaign.json`.
- Scope: USDC-only, Coinbase US-customer-available crypto spot products via
  `all_coinbase_usdc_spot_us_customer_available`.
- Sides: `BUY` and `SELL`.
- Order policies: `market_ioc`, `limit_gtc`, and `limit_gtc_post_only`.
- Cadence/default cap fixture: repeat every `6` hours, max `4` runs.
- Safety fixture: max `1` USDC per order and max `10` USDC per run, with
  operator-configurable fields recorded for notional, cadence, max runs,
  allow/deny product scope, and order policy.
- Inventory retention: `retain`.
- Cost-basis authority: `fill_ledger`, `imported_baseline`, and explicit
  `coinbase_average_cost` with `0.5` percent profit buffer.
- Required audit evidence: `client_order_id`, `exchange_order_id`,
  submitted/executed notional, and fill-ledger reconciliation.
- `python tools/run_spot_feature_intake_gate.py --request-file docs\examples\spot-feature-intake-usdc-campaign.json --summary-only`
  passed with `phase_50_ready: true`.
- The only warning was expected: the all-product selection rule resolves to
  concrete eligible product ids at run time.
- No new placement primitive is needed. The feature maps to the existing spot
  campaign layer plus the existing USDC portfolio sweep live runner.
- No live Coinbase orders were submitted for this phase. Submitted notional:
  `0` USDC. Executed notional: `0` USDC.

### Phase 88 - Contextless Documentation Repair Loop

Status: completed for this batch and persistent for future spot changes.

Treat blind-agent failures as first-class readiness failures.

Scope:

- Run the prompt in `docs/SPOT_CONTEXTLESS_AGENT_TESTING.md` after substantial
  spot order-flow changes.
- Record missing concepts and fix the repository, not the prompt.
- Prefer entry-doc, docs-index, and examples improvements before code
  reorganization.

Acceptance:

- A fresh agent or human can correctly explain how to create a spot order,
  where safety checks happen, and which paths must never be bypassed.

Result on 2026-06-09:

- First blind-agent review failed. The agent correctly identified
  `place_hotpoint_test_order` as an undocumented dashboard live-order path that
  could call `REST_CLIENT.limit_order_gtc` directly and was not covered by the
  documented spot capability/action-guard boundary.
- Repository repair completed:
  - `place_hotpoint_test_order` is now runtime-admission gated.
  - The handler requires `ProductCapability.HOTPOINT_AUTO_PLACEMENT` before
    parent insertion or REST placement. Spot remains blocked by default.
  - The handler validates size, runs planning-phase `ActionConditionGuard`,
    pre-inserts the opt-in parent row only after guards pass, tracks the REST
    placement as in-flight work, records `order_submitted` / `rest_submit`
    submission evidence when available, and marks the pre-inserted parent row
    `FAILED` if the later exchange submission path fails.
  - `agent.md`, `README.spot-trading.md`,
    `genai_data/API_REFERENCE.md`, and
    `docs/SPOT_CONTEXTLESS_AGENT_TESTING.md` now enumerate the hotpoint seed
    order as a live-submitting surface and document its guard boundary.
- New regression coverage proves the former bypass is closed: spot hotpoint
  seed orders block before DB/REST by default, explicit hotpoint capability
  still does not bypass the action guard, successful seed orders record
  submission evidence, and the message is included in runtime originating-work
  admission.
- Second blind-agent review passed. The fresh agent identified direct
  dashboard, stealth reveal, hotpoint seed placement, sweep live execution,
  campaign read-only orchestration, action guards, wallet-vs-cost-basis
  semantics, `client_order_id` identity, durable P/L/reconciliation, and the
  all-USDC campaign mapping without coaching.
- No live Coinbase orders were submitted for this phase. Submitted notional:
  `0` USDC. Executed notional: `0` USDC.

## Deferred Until After Readiness

- Spot-specific strategy features that depend on lot-aware exits.
- Auto-hotpoint placement for spot.
- Spot move/reprice UX beyond explicit disabled/conditional feedback.
- Tax/reporting semantics for realized spot lots.
- Multi-currency quote balancing beyond the configured product metadata.
