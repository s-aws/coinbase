# Spot Portfolio Sweep Examples

## Dry-Run A USDC BUY Sweep

```powershell
python tools/run_spot_portfolio_sweep_dry_run.py --side BUY --quote-notional 1
```

The command reads Coinbase public product metadata and paginated account
wallets, then prints `SPOT_PORTFOLIO_SWEEP_DRY_RUN` JSON. It does not place
live orders.

## Dry-Run A USDC SELL Sweep

```powershell
python tools/run_spot_portfolio_sweep_dry_run.py --side SELL --quote-notional 1
```

SELL planning uses each base wallet balance. Products without enough base
inventory are skipped with `skip_reason: "insufficient_base_balance"`.

## Limit The Product Count

```powershell
python tools/run_spot_portfolio_sweep_dry_run.py --side BUY --quote-notional 1 --max-products 25
```

`--max-products` is useful for reviewing a smaller deterministic slice of the
eligible USDC spot product list.

## Preview Automation Cadence

```powershell
python tools/run_spot_portfolio_sweep_dry_run.py --side BUY --quote-notional 1 --repeat-every-hours 6 --max-runs 4 --summary-only
```

The output includes `automation_preview.live_scheduler_enabled: false`.
This does not place live orders.

## Run One Live BUY Sweep

```powershell
python tools/run_spot_portfolio_sweep_live.py --side BUY --quote-notional 1 --max-products 10 --approved-live-orders
```

This can place real Coinbase market IOC orders. The output uses the
`SPOT_PORTFOLIO_SWEEP_LIVE` prefix and reports submitted/executed notional.

## Run One Live Limit BUY Sweep

```powershell
python tools/run_spot_portfolio_sweep_live.py --side BUY --quote-notional 1 --max-products 10 --order-type limit_gtc --limit-price-offset-bps 25 --approved-live-orders
```

Limit BUY uses the rounded planned base size and a limit price above the
current product mark by the configured basis-point offset.

## Run One Live SELL Sweep

```powershell
python tools/run_spot_portfolio_sweep_live.py --side SELL --quote-notional 1 --max-products 10 --approved-live-orders
```

SELL execution submits base-size market IOC orders derived from the dry-run
planner. Each item is checked by `ActionConditionGuard` immediately before
`create_order`.

## Apply Artificial Safety Caps

```powershell
python tools/run_spot_portfolio_sweep_live.py --side BUY --quote-notional 1 --max-products 10 --max-total-notional-per-run 10 --max-notional-per-order 1 --approved-live-orders
```

Safety caps are evaluated after wallet-aware planning and before the first live
Coinbase `create_order` call. If the safety policy blocks the run, the JSON
summary reports `live_coinbase_orders_ran: false` and zero submitted notional.

## Require Known Profitable Inventory For SELL

```powershell
python tools/run_spot_portfolio_sweep_live.py --side SELL --quote-notional 1 --max-products 10 --require-known-profitable-inventory --approved-live-orders
```

This optional safety policy requires every planned SELL item to be covered by
known profitable fill-ledger or imported baseline lots before any Coinbase
order is submitted. Wallet balance alone is not treated as profit authority.

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
    "max_notional_per_order": "1"
  }
}
```

Read-only validation:

```powershell
python tools/run_spot_portfolio_sweep_live.py --config-file runtime_state/spot_sweep_buy.json --validate-config
```

This prints a wallet-aware plan, safety evaluation, and per-product explain
rows. It does not require `--approved-live-orders`.

## Run If Due

```powershell
python tools/run_spot_portfolio_sweep_live.py --side BUY --quote-notional 1 --repeat-every-hours 6 --max-runs 4 --approved-live-orders --summary-only
```

Each invocation checks `runtime_state/spot_portfolio_sweeps.jsonl`, runs at
most one due sweep, records the result, and exits. Use Windows Task Scheduler
or another supervisor to invoke this command periodically.

Submitted live sweep orders backfill Coinbase REST fills into `fill_ledger` by
default. Use `--skip-fill-backfill` only when deliberately testing without a
local database write.

## Windows Task Scheduler Recipe

Use a config file for repeatable automation and let Task Scheduler invoke the
run-if-due command more frequently than the configured interval:

```powershell
schtasks /Create /TN "Coinbase Spot Sweep BUY" /SC HOURLY /MO 1 /TR "py -3.13 C:\coinbase\tools\run_spot_portfolio_sweep_live.py --config-file C:\coinbase\runtime_state\spot_sweep_buy.json --approved-live-orders --summary-only" /F
```

The tool still enforces `repeat_every_hours` and `max_runs` from the durable
ledger. The scheduled task only starts the process; it does not bypass the
CLI's approval flag, action guard, safety policy, fill backfill, or run ledger.

## Disable A Recurring Sweep

```powershell
python tools/run_spot_portfolio_sweep_live.py --side BUY --quote-notional 1 --repeat-every-hours 6 --max-runs 4 --disable-automation
```

This writes a local stop record for the config id and exits without live
orders. No live-order approval flag is required for disable.

## Show Durable Sweep Status

```powershell
python tools/run_spot_portfolio_sweep_live.py --status
```

This reads `runtime_state/spot_portfolio_sweeps.jsonl` and prints operator
status. It does not call Coinbase and does not require live-order approval.

## Show Sweep P/L

```powershell
python tools/run_spot_portfolio_sweep_live.py --pnl-report
```

This reads Coinbase public product marks and local `fill_ledger` rows, then
prints product, portfolio, since-last-purchase, and FIFO realized-lot P/L
scopes. It does not submit orders and does not require
`--approved-live-orders`. The realized-lot view is operational reporting, not
tax accounting.

## Show Inventory Coverage

```powershell
python tools/run_spot_portfolio_sweep_live.py --inventory-coverage --summary-only
```

This compares eligible USDC spot wallet balances against local fill-ledger and
imported baseline evidence. It requires Coinbase read credentials for wallets
and writes no Coinbase orders.

## Show The Sweep Config Registry

```powershell
python tools/run_spot_portfolio_sweep_live.py --config-registry
```

This reads the durable sweep JSONL ledger and prints config ids, disabled
state, latest run, latest reconciliation, and latest fill-backfill status. It
does not call Coinbase.

## Reconcile Recorded Runs

```powershell
python tools/run_spot_portfolio_sweep_live.py --reconcile --config-id spot-sweep-example --run-id spot-sweep-run-example
```

Reconciliation reads Coinbase order/fill evidence for recorded exchange order
ids and appends `sweep_reconciliation` records to the JSONL ledger. It requires
Coinbase credentials but does not require `--approved-live-orders` because it
does not submit orders. When `fill_ledger` is available, each order also
reports whether local rows match Coinbase REST fills.

## Recover Fill-Ledger Backfill

Dry-run scan of existing smoke and sweep audit files:

```powershell
python tools/run_spot_fill_backfill_recovery.py --dry-run --summary-only
```

Retry REST-fill backfill for a recorded sweep run:

```powershell
python tools/run_spot_fill_backfill_recovery.py --source sweep --run-id spot-sweep-run-example
```

This calls Coinbase `list_fills` and writes local `fill_ledger` rows through
the existing idempotent backfill path. It never submits live orders.

## Run The Sweep Recovery Gate

```powershell
python tools/run_spot_sweep_recovery_gate.py --dry-run --summary-only
```

Without `--dry-run`, the gate appends missing sweep reconciliation records and
retries fill-ledger backfill for runs whose durable record lacks clean backfill
evidence:

```powershell
python tools/run_spot_sweep_recovery_gate.py --config-id spot-sweep-example
```

The gate reports `SPOT_SWEEP_RECOVERY_GATE`, zero live order notional, and any
remaining reconciliation or fill-backfill failures.

## Run The Read-Only Spot Release Gate

```powershell
python tools/run_spot_release_gate.py
```

This runs the focused spot readiness regression gate and prints
`SPOT_RELEASE_GATE_SUMMARY`. Add `--include-browser` for the Playwright smoke
gate and `--include-coinbase-readonly` for read-only sweep status/P/L checks.

## Run The Approved Live Validation Matrix

```powershell
python tools/run_live_spot_usdc_smoke.py --approved-live-orders --validation-matrix
```

This places real Coinbase orders on the cheapest previewable USDC spot product:
market BUY, post-only limit BUY cancel, post-only limit SELL cancel, and market
SELL. The summary reports every live order and total submitted/executed USDC
notional. Use `--retain-inventory` to leave the bought base in the account and
skip the final market SELL.

For the Phase 34 reconciliation gate:

```powershell
python tools/run_live_spot_usdc_smoke.py --approved-live-orders --validation-matrix --reconciliation-gate
```

This still places live Coinbase orders. It exits nonzero if executed market
orders cannot fetch REST fills and backfill local `fill_ledger` evidence.

## Required Environment

The dry-run tool needs Coinbase credentials because wallet availability is part
of the plan:

```powershell
$env:COINBASE_API_KEY = "..."
$env:COINBASE_API_SECRET = "..."
```

The dry-run tool has no live order approval flag because it is read-only. The
live tool requires `--approved-live-orders` for any path that can submit
Coinbase orders.
