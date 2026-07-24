# Spot Portfolio Sweep Examples

This is a parked Spot automation reference, not the current work queue.
Standing closeout is `operator_ready_admin_mvp_runtime_v1`. Live sweep, fan-out,
cadence, and scheduler examples require explicit operator reprioritization;
their presence here does not authorize or prioritize them.

All mutation examples in this file are historical and source-disabled. The
sweep CLI retains read-only reporting modes, but no longer submits orders.
The six installed Controlled-live mutation routes are manual root place/cancel,
explicit attached-intent materialization/exact-child safe-closeout, and
operator Hotpoint run-once/exact-child safe-closeout under the manager lease
and backend per-request gates. Intent attachment is
local-only, both successor actions require fresh separate acknowledgements,
and none of these routes grants sweep, fan-out, cadence, or scheduler authority.

## Dry-Run A USDC BUY Sweep

```powershell
python3.13 tools/run_spot_portfolio_sweep_dry_run.py --side BUY --quote-notional 1
```

The command reads Coinbase public product metadata and paginated account
wallets, then prints `SPOT_PORTFOLIO_SWEEP_DRY_RUN` JSON. It does not place
live orders.

## Dry-Run A USDC SELL Sweep

```powershell
python3.13 tools/run_spot_portfolio_sweep_dry_run.py --side SELL --quote-notional 1
```

SELL planning uses each base wallet balance. Products without enough base
inventory are skipped with `skip_reason: "insufficient_base_balance"`.

## Limit The Product Count

```powershell
python3.13 tools/run_spot_portfolio_sweep_dry_run.py --side BUY --quote-notional 1 --max-products 25
```

`--max-products` is useful for reviewing a smaller deterministic slice of the
eligible USDC spot product list.

## Preview Automation Cadence

```powershell
python3.13 tools/run_spot_portfolio_sweep_dry_run.py --side BUY --quote-notional 1 --repeat-every-hours 6 --max-runs 4 --summary-only
```

The output includes `automation_preview.live_scheduler_enabled: false`.
This does not place live orders.

## Historical Live BUY Sweep (Source-Disabled)

```powershell
python3.13 tools/run_spot_portfolio_sweep_live.py --side BUY --quote-notional 1 --max-products 10 --approved-live-orders
```

This formerly placed real Coinbase market IOC orders. The command now exits
with a fixed source-disabled diagnostic. Historical output used the
`SPOT_PORTFOLIO_SWEEP_LIVE` prefix and reports submitted/executed notional.
Submitted order rows include UUID `client_order_id` values and
`submission_event_recorded`. Use the JSONL `run_id`/`config_id` and event
payload fields to identify sweep orders; do not expect a `client_order_id`
prefix.

## Historical Live Limit BUY Sweep (Source-Disabled)

```powershell
python3.13 tools/run_spot_portfolio_sweep_live.py --side BUY --quote-notional 1 --max-products 10 --order-type limit_gtc --limit-price-offset-bps 25 --approved-live-orders
```

Limit BUY uses the rounded planned base size and a limit price above the
current product mark by the configured basis-point offset.

## Historical Live SELL Sweep (Source-Disabled)

```powershell
python3.13 tools/run_spot_portfolio_sweep_live.py --side SELL --quote-notional 1 --max-products 10 --require-known-profitable-inventory --approved-live-orders
```

SELL execution submits base-size market IOC orders derived from the dry-run
planner. Each item is checked by `ActionConditionGuard` immediately before
`create_order`. Live SELL examples require explicit profit-authority policy;
wallet balance alone proves sellability, not profitability.

## Apply Artificial Safety Caps

```powershell
python3.13 tools/run_spot_portfolio_sweep_live.py --side BUY --quote-notional 1 --max-products 10 --max-total-notional-per-run 10 --max-notional-per-order 1 --approved-live-orders
```

Safety caps are evaluated after wallet-aware planning and before the first live
Coinbase `create_order` call. If the safety policy blocks the run, the JSON
summary reports `live_coinbase_orders_ran: false` and zero submitted notional.

## Required Known Profitable Inventory For Live SELL

```powershell
python3.13 tools/run_spot_portfolio_sweep_live.py --side SELL --quote-notional 1 --max-products 10 --require-known-profitable-inventory --approved-live-orders
```

Historically this SELL policy required every planned item to be covered by
known profitable fill-ledger or imported baseline lots. The mutation mode is
now source-disabled, so no Coinbase order is submitted.

`--disable-safety-policy` remains for read-only diagnostics and local
validation only. `--approved-live-orders` grants no execution authority.

## Allow Coinbase Average Cost For SELL Authority

```powershell
python3.13 tools/run_spot_portfolio_sweep_live.py --side SELL --quote-notional 1 --max-products 10 --require-known-profitable-inventory --allow-coinbase-average-cost-basis --coinbase-average-cost-profit-buffer-pct 0.5 --approved-live-orders
```

This was an explicit historical opt-in. The read-only authority calculation
can still compare local lots and Coinbase average cost, but the command cannot
submit Coinbase orders because mutation mode is source-disabled.

## Validate A Sweep Config File

Example `runtime_state/spot_sweep_buy.json`:

```json
{
  "version": 1,
  "side": "BUY",
  "quote_notional": "1",
  "max_products": 10,
  "order_type": "market_ioc",
  "repeat_every_hours": "6",
  "max_runs": 4,
  "safety_policy": {
    "max_total_notional_per_run": "10",
    "max_notional_per_order": "1",
    "allow_coinbase_average_cost_basis": false,
    "coinbase_average_cost_profit_buffer_pct": "0.5"
  }
}
```

Read-only validation:

```powershell
python3.13 tools/run_spot_portfolio_sweep_live.py --config-file runtime_state/spot_sweep_buy.json --validate-config
```

This prints a wallet-aware plan, safety evaluation, and per-product explain
rows. It does not require `--approved-live-orders`.
For generated SELL allowlist configs, validation reports
`sell_authority_allowlist_freshness`; stale or invalid allowlist metadata is a
validation error. Omit `--summary-only` for detailed offline review when you
need exact product ids, base sizes, estimated notional, and `sell_authority`
rows.

For a SELL config that explicitly allows Coinbase average-cost authority during
validation:

```powershell
python3.13 tools/run_spot_portfolio_sweep_live.py --config-file runtime_state/spot_sweep_sell.json --validate-config --allow-coinbase-average-cost-basis
```

Validation is still read-only. It fetches fresh products, wallets, portfolios,
and portfolio breakdown data, then reports the SELL authority source in the
plan explain output.

## Historical Run-If-Due Automation (Source-Disabled)

The old run-if-due and Task Scheduler recipes are intentionally not provided as
runnable commands. Sweep mutation mode is source-disabled, and
`--approved-live-orders` cannot grant authority. Durable ledger status,
validation, P/L, and reconciliation review remain available as read-only or
local-evidence operations.

## Disable A Recurring Sweep

```powershell
python3.13 tools/run_spot_portfolio_sweep_live.py --side BUY --quote-notional 1 --repeat-every-hours 6 --max-runs 4 --disable-automation
```

This writes a local stop record for the config id and exits without live
orders. No live-order approval flag is required for disable.

## Show Durable Sweep Status

```powershell
python3.13 tools/run_spot_portfolio_sweep_live.py --status
```

This reads `runtime_state/spot_portfolio_sweeps.jsonl` and prints operator
status. It does not call Coinbase and does not require live-order approval.

## Show Sweep P/L

```powershell
python3.13 tools/run_spot_portfolio_sweep_live.py --pnl-report
```

This reads Coinbase public product marks and local `fill_ledger` rows, then
prints product, portfolio, since-last-purchase, and FIFO realized-lot P/L
scopes. It does not submit orders and does not require
`--approved-live-orders`. The realized-lot view is operational reporting, not
tax accounting.

To include a separate Coinbase average-cost P/L scope:

```powershell
python3.13 tools/run_spot_portfolio_sweep_live.py --pnl-report --include-coinbase-average-cost
```

This adds authenticated read-only Coinbase portfolio calls. The output includes
`average_cost_pnl` separately from the local fill-ledger P/L snapshot.

## Show Coinbase Average-Cost Baseline

```powershell
python3.13 tools/run_spot_portfolio_sweep_live.py --cost-basis-baseline --summary-only
```

This reads Coinbase portfolios and portfolio breakdown data, maps asset-level
spot positions to eligible `BASE-USDC` products, and reports the average-cost
baseline. It does not submit orders or write local data.

To persist a local snapshot for later dashboard/status review:

```powershell
python3.13 tools/run_spot_portfolio_sweep_live.py --cost-basis-baseline --summary-only --record-cost-basis-snapshot
```

The snapshot is appended to
`runtime_state/spot_cost_basis_snapshots.jsonl` by default.

## Show Inventory Coverage

```powershell
python3.13 tools/run_spot_portfolio_sweep_live.py --inventory-coverage --summary-only
```

This compares eligible USDC spot wallet balances against local fill-ledger and
imported baseline evidence. It requires Coinbase read credentials for wallets
and writes no Coinbase orders.
The report includes `baseline_freshness_audit`, which flags imported baseline
rows with stale, missing, or invalid source freshness metadata.

To include Coinbase average-cost authority in coverage:

```powershell
python3.13 tools/run_spot_portfolio_sweep_live.py --inventory-coverage --include-coinbase-average-cost --summary-only
```

Coverage rows can then show `coverage_status: "coinbase_average_cost"` when a
wallet balance is explained by Coinbase average cost but not by exact local
lots.

## Audit Cost-Basis Drift

```powershell
python3.13 tools/run_spot_portfolio_sweep_live.py --cost-basis-drift-audit --summary-only
```

This compares local fill-ledger average basis with Coinbase average basis per
eligible USDC product and reports drift status. It is read-only and submits no
orders.
When Coinbase average cost is explicitly enabled as SELL authority, stale
drift blocks only planned rows whose `sell_authority.cost_basis_authority` is
`coinbase_average_cost`.

## Triage Cost-Basis Gaps

```powershell
python3.13 tools/run_spot_portfolio_sweep_live.py --cost-basis-triage --summary-only
```

This combines average-cost baseline, inventory coverage, and drift audit into
one read-only summary for wallet-only, missing-position, stale, and local-lot
unavailable gaps.

To persist the triage snapshot:

```powershell
python3.13 tools/run_spot_portfolio_sweep_live.py --cost-basis-triage --summary-only --record-cost-basis-snapshot
```

## Show Durable Cost-Basis Status

```powershell
python3.13 tools/run_spot_portfolio_sweep_live.py --cost-basis-status
```

This reads the local cost-basis snapshot ledger only. It does not call Coinbase
and does not submit orders.

## Show The Sweep Config Registry

```powershell
python3.13 tools/run_spot_portfolio_sweep_live.py --config-registry
```

This reads the durable sweep JSONL ledger and prints config ids, disabled
state, latest run, latest reconciliation, and latest fill-backfill status. It
does not call Coinbase.

## Reconcile Recorded Runs

```powershell
python3.13 tools/run_spot_portfolio_sweep_live.py --reconcile --config-id spot-sweep-example --run-id spot-sweep-run-example
```

Reconciliation reads Coinbase order/fill evidence for recorded exchange order
ids and appends `sweep_reconciliation` records to the JSONL ledger. It requires
Coinbase credentials but does not require `--approved-live-orders` because it
does not submit orders. When `fill_ledger` is available, each order also
reports whether local rows match Coinbase REST fills.

## Recover Fill-Ledger Backfill

Dry-run scan of existing smoke and sweep audit files:

```powershell
python3.13 tools/run_spot_fill_backfill_recovery.py --dry-run --summary-only
```

Retry REST-fill backfill for a recorded sweep run:

```powershell
python3.13 tools/run_spot_fill_backfill_recovery.py --source sweep --run-id spot-sweep-run-example
```

This calls Coinbase `list_fills` and writes local `fill_ledger` rows through
the existing idempotent backfill path. It never submits live orders.

## Run The Sweep Recovery Gate

```powershell
python3.13 tools/run_spot_sweep_recovery_gate.py --dry-run --summary-only
```

Without `--dry-run`, the gate appends missing sweep reconciliation records and
retries fill-ledger backfill for runs whose durable record lacks clean backfill
evidence:

```powershell
python3.13 tools/run_spot_sweep_recovery_gate.py --config-id spot-sweep-example
```

The gate reports `SPOT_SWEEP_RECOVERY_GATE`, zero live order notional, and any
remaining reconciliation or fill-backfill failures.

## Audit Fill-Ledger Health

```powershell
python3.13 tools/run_spot_fill_ledger_health.py --summary-only
```

This scans local USDC `fill_ledger` rows for data hazards such as zero price,
zero notional, missing `client_order_id`, and reconciled rows without exchange
evidence. It does not call Coinbase and does not write local corrections.

## Plan Or Apply Fill-Ledger Repair

Local-only candidate scan:

```powershell
python3.13 tools/run_spot_fill_ledger_repair.py --plan-only --summary-only
```

Dry-run exact repair planning from Coinbase REST fill evidence:

```powershell
python3.13 tools/run_spot_fill_ledger_repair.py --summary-only
```

Apply exact local corrections and append a durable repair record:

```powershell
python3.13 tools/run_spot_fill_ledger_repair.py --apply --summary-only
```

The repair command never submits Coinbase orders. Non-plan dry-runs and apply
runs call Coinbase `list_fills` for already-recorded exchange order ids only.

## Run The Read-Only Spot Release Gate

```powershell
python3.13 tools/run_spot_release_gate.py
```

This runs the focused spot readiness regression gate and prints
`SPOT_RELEASE_GATE_SUMMARY`. Add `--include-browser` for the Playwright smoke
gate and `--include-coinbase-readonly` for read-only sweep status, P/L,
average-cost coverage, and drift checks.

## Historical Live Validation Matrix (Source-Disabled)

```powershell
python3.13 tools/run_live_spot_usdc_smoke.py --approved-live-orders --validation-matrix
```

This historically placed market/limit BUY and SELL orders. It is retained only
for traceability and now exits before SDK construction with a fixed
source-disabled diagnostic.

For the Phase 34 reconciliation gate:

```powershell
python3.13 tools/run_live_spot_usdc_smoke.py --approved-live-orders --validation-matrix --reconciliation-gate
```

This historical combination is also source-disabled and cannot place or
reconcile new live orders.

## Required Environment

The dry-run tool needs Coinbase credentials because wallet availability is part
of the plan:

```powershell
$env:COINBASE_API_KEY = "..."
$env:COINBASE_API_SECRET = "..."
```

The dry-run tool is read-only. The historical live CLI is source-disabled;
`--approved-live-orders` cannot enable submission.
