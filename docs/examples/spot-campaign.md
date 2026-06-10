# Spot Campaign Examples

## Example Campaign Config

Example `runtime_state/spot_campaign_buy.json`:

```json
{
  "version": 1,
  "campaign_name": "all_usdc_buy_campaign",
  "side": "BUY",
  "quote_notional": "1",
  "max_products": 10,
  "order_type": "market_ioc",
  "automation": {
    "enabled": true,
    "repeat_every_hours": "6",
    "max_runs": 4
  },
  "product_scope": {
    "quote_currency": "USDC",
    "us_customer_available": true,
    "selection_rule": "all_coinbase_usdc_spot_us_customer_available"
  },
  "safety_policy": {
    "max_total_notional_per_run": "10",
    "max_notional_per_order": "1",
    "max_planned_orders": 10
  },
  "inventory_policy": {
    "retention": "retain"
  },
  "cost_basis_authority": {
    "allowed_sources": [
      "fill_ledger",
      "imported_baseline"
    ]
  }
}
```

## Validate Campaign Intake

```powershell
python tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_buy.json --intake
```

This validates the campaign against the existing spot feature-intake gate. It
does not call Coinbase.

## Write A Canonical Template

```powershell
python tools/run_spot_campaign.py --template-profile buy_canary --write-template-file runtime_state/spot_campaign_buy_canary.json
python tools/run_spot_campaign.py --template-profile buy_all_usdc --write-template-file runtime_state/spot_campaign_buy_all_usdc.json
python tools/run_spot_campaign.py --template-profile sell_canary --write-template-file runtime_state/spot_campaign_sell_canary.json
python tools/run_spot_campaign.py --template-profile sell_all_usdc --write-template-file runtime_state/spot_campaign_sell_all_usdc.json
```

Templates are normalized campaign configs. They submit no Coinbase orders.

## Map The USDC Campaign Feature To Config Fields

Use one campaign config for the requested operator intent:

```json
{
  "side": "BUY",
  "quote_notional": "1.01",
  "automation": {
    "enabled": true,
    "repeat_every_hours": "6",
    "max_runs": 4
  },
  "product_scope": {
    "quote_currency": "USDC",
    "us_customer_available": true,
    "selection_rule": "all_coinbase_usdc_spot_us_customer_available"
  },
  "safety_policy": {
    "max_total_notional_per_run": "500",
    "max_notional_per_order": "2",
    "max_planned_orders": 500,
    "max_skipped_orders": 500,
    "require_wallet_check": true
  }
}
```

Switch `side` to `SELL` only when `safety_policy.require_known_profitable_inventory`
is true and a SELL authority profile is set. Broad BUY readiness can pass the
all-USDC gate. Broad SELL readiness should be converted to a fresh authority
allowlist before live execution.

The durable tracking surfaces are:

```powershell
python tools/run_spot_campaign.py --status --summary-only
python tools/run_spot_campaign.py --run-index --summary-only
python tools/run_spot_campaign.py --pnl-checkpoints --summary-only
python tools/run_spot_portfolio_sweep_live.py --pnl-report --include-coinbase-average-cost --summary-only
python tools/run_spot_portfolio_sweep_live.py --cost-basis-status --summary-only
```

## Validate Config Safety

```powershell
python tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_buy_all_usdc.json --validate-config-report
```

The validation report is local-only. It fails configs that omit explicit
per-order, total-notional, or planned-order caps.

## Apply A SELL Authority Profile

```powershell
python tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_sell.json --sell-authority-profile coinbase_average_cost_buffered --write-profiled-config-file runtime_state/spot_campaign_sell.profiled.json
```

`fill_ledger_strict` requires local/imported known profitable lots.
`coinbase_average_cost_buffered` explicitly enables Coinbase average-cost
authority and its extra buffer.

## Build A SELL Authority Allowlist

Strict local-fill-ledger authority:

```powershell
python tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_sell.json --sell-authority-profile fill_ledger_strict --sell-authority-allowlist --write-allowlist-file runtime_state/spot_campaign_sell.strict.allowlist.json --write-allowlist-config-file runtime_state/spot_campaign_sell.strict.allowlist.config.json --write-allowlist-sweep-config-file runtime_state/spot_campaign_sell.strict.allowlist.sweep.json --record-snapshot --summary-only
```

Coinbase average-cost-buffered authority:

```powershell
python tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_sell.json --sell-authority-profile coinbase_average_cost_buffered --sell-authority-allowlist --write-allowlist-file runtime_state/spot_campaign_sell.average.allowlist.json --write-allowlist-config-file runtime_state/spot_campaign_sell.average.allowlist.config.json --write-allowlist-sweep-config-file runtime_state/spot_campaign_sell.average.allowlist.sweep.json --record-snapshot --summary-only
```

The campaign command is read-only with respect to Coinbase orders. It writes a
narrowed config whose `allow_products` contain only rows with passing SELL
authority. Strict authority uses local/imported known profitable inventory
after prior local SELL fills have consumed earlier BUY lots. Average-cost
authority adds Coinbase portfolio average cost as an explicitly configured
source with the extra buffer. Average-cost allowlists exclude rows blocked by
the average-cost freshness or local-drift gate.

The rendered `*.allowlist.sweep.json` file includes a
`sell_authority_allowlist` freshness block. Regenerate the allowlist
immediately before live approval; the sweep live runner rejects stale or
invalid allowlist metadata.

Imported baseline lots are trusted as operator-maintained inventory state,
including `remaining_quantity`. Include source freshness metadata such as
`source_updated_at`, refresh stale baselines, or mark them unknown before
relying on them for live SELL authority. Coverage and validate outputs include
`baseline_freshness_audit`. Baseline freshness is report-only today; use a
regenerated SELL authority allowlist to exclude rows without current
known-profit authority unless a future blocking baseline policy is explicitly
enabled.

## Build A Read-Only Dry-Run Matrix

```powershell
python tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_buy.json --dry-run-matrix --summary-only --record-snapshot
```

This reads Coinbase products and wallets, builds the wallet-aware sweep plan,
evaluates safety, computes local P/L if `fill_ledger` is available, appends a
campaign snapshot, and submits no Coinbase orders.

## Run The Campaign Release Gate

```powershell
python tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_buy.json --release-gate --summary-only --record-snapshot
```

The release gate checks feature intake, product planning, safety policy,
operation-lock state, recovery readiness, P/L availability, and optional
cost-basis state. It is read-only with respect to Coinbase orders.

## Compare Dry Runs

```powershell
python tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_buy_all_usdc.json --baseline-config-file runtime_state/spot_campaign_buy_canary.json --dry-run-diff --summary-only
```

The diff compares planned/skipped counts, estimated notional, product status
changes, and P/L summary fields. It reads products and wallets but never places
orders.

## Build Local Run Index And P/L Checkpoints

```powershell
python tools/run_spot_campaign.py --run-index
python tools/run_spot_campaign.py --pnl-checkpoints
python tools/run_spot_campaign.py --pnl-delta-report --summary-only
```

These commands read local JSONL ledgers only. The delta report compares the
latest recorded checkpoint against the prior checkpoint for any durable P/L
scopes present in the snapshots.

## Plan Campaign Ledger Cleanup

```powershell
python tools/run_spot_campaign.py --ledger-cleanup-plan --summary-only
```

This reads the campaign and sweep ledgers only. It identifies unrecorded sweep
runs that should be recorded with `--record-latest-sweep-run` and separates
legacy no-order runs that should be deliberately documented or ignored.

## Run A No-Order Recovery Drill

```powershell
python tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_buy_canary.json --no-order-recovery-drill --summary-only
```

The drill builds a synthetic no-submission sweep run and verifies that retry
classification targets only rows with no exchange evidence.

## Check Scheduler Due State

```powershell
python tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_buy_canary.json --scheduler-status
```

This reports whether the recurring sweep config is due according to the durable
sweep ledger. The live runner still enforces the same due-state before placing
orders.

## Gate A Broad All-USDC Campaign

```powershell
python tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_buy_all_usdc.json --all-usdc-readiness-gate --summary-only
python tools/run_spot_release_gate.py --campaign-config-file runtime_state/spot_campaign_buy_all_usdc.json --campaign-all-usdc-readiness
```

The all-USDC gate requires the canonical USDC selector, no allow/deny product
restriction, no `max_products` restriction, and explicit safety caps. It also
runs the normal campaign release gate.

## Render The Equivalent Sweep Config

```powershell
python tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_buy.json --write-sweep-config-file runtime_state/spot_campaign_buy.sweep.json
```

The rendered file uses the existing sweep config schema. It is the file to use
for live canaries.

## Run A One-Product Live Canary

```powershell
python tools/run_spot_portfolio_sweep_live.py --config-file runtime_state/spot_campaign_buy.sweep.json --max-products 1 --max-total-notional-per-run 1 --max-notional-per-order 1 --approved-live-orders --summary-only
```

This can submit real Coinbase orders. The command uses the existing sweep live
runner, not the campaign CLI. Coinbase REST credentials must be configured for
this command; the campaign CLI remains read-only with respect to Coinbase
orders.

Record the latest matching sweep run into the campaign ledger:

```powershell
python tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_buy.json --record-latest-sweep-run
```

This is local-only. It reads `runtime_state/spot_portfolio_sweeps.jsonl` and
appends a `spot_campaign_snapshot` record with submitted/executed notional.

## Build A Targeted Retry Config From A Partial Run

```powershell
python tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_buy_10.json --retry-plan --write-retry-config-file runtime_state/spot_campaign_buy_10.retry.json --summary-only
```

This is local-only. It reads the durable sweep ledger, finds the latest matching
partial run, and writes a normal campaign config scoped to products that had no
exchange order id and zero submitted/executed notional.

Planned skips, such as products below `quote_min_size`, are kept as audit rows
but are not retry targets. A live run with submitted orders plus only planned
skips records as completed when `--record-latest-sweep-run` is used.

Render the retry campaign to a sweep config:

```powershell
python tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_buy_10.retry.json --write-sweep-config-file runtime_state/spot_campaign_buy_10.retry.sweep.json
```

Validate the retry config before any live order:

```powershell
python tools/run_spot_portfolio_sweep_live.py --config-file runtime_state/spot_campaign_buy_10.retry.sweep.json --validate-config --summary-only
```

Live retry execution, when explicitly approved, still uses the existing sweep
runner:

```powershell
python tools/run_spot_portfolio_sweep_live.py --config-file runtime_state/spot_campaign_buy_10.retry.sweep.json --approved-live-orders --summary-only
```

## Compare SELL Authority Reports

Detect allowlist drift between a prior strict allowlist and a freshly generated
strict allowlist:

```powershell
python tools/run_spot_campaign.py --sell-authority-drift-report --baseline-allowlist-file runtime_state/spot_campaign_sell.previous.allowlist.json --current-allowlist-file runtime_state/spot_campaign_sell.current.allowlist.json --summary-only
```

If products were removed, the command exits blocked. Regenerate the allowlist
and validate the rendered sweep config immediately before live approval.

Compare strict fill-ledger authority against Coinbase average-cost authority:

```powershell
python tools/run_spot_campaign.py --authority-operator-report --strict-allowlist-file runtime_state/spot_campaign_sell.strict.allowlist.json --average-cost-allowlist-file runtime_state/spot_campaign_sell.average.allowlist.json --summary-only
```

This is a read-only operator report. It does not make Coinbase average cost
equivalent to strict local fill-ledger authority.

Select capped strict SELL canary candidates while avoiding recently sold
products:

```powershell
python tools/run_spot_campaign.py --strict-sell-canary-candidates --input-allowlist-file runtime_state/spot_campaign_sell.strict.allowlist.json --summary-only
```

The candidate selector is only a proposal surface. Live SELL still requires a
fresh allowlist, sweep validation, explicit caps, and `--approved-live-orders`.

## SELL Campaign With Coinbase Average-Cost Authority

Example SELL config fragment:

```json
{
  "side": "SELL",
  "quote_notional": "1",
  "safety_policy": {
    "max_total_notional_per_run": "5",
    "max_notional_per_order": "1",
    "require_known_profitable_inventory": true,
    "allow_coinbase_average_cost_basis": true,
    "coinbase_average_cost_profit_buffer_pct": "0.5"
  },
  "cost_basis_authority": {
    "allowed_sources": [
      "fill_ledger",
      "imported_baseline",
      "coinbase_average_cost"
    ],
    "coinbase_average_cost_profit_buffer_pct": "0.5"
  }
}
```

Read-only release gate:

```powershell
python tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_sell.json --release-gate --include-coinbase-average-cost --summary-only
```

Live SELL execution still uses the sweep runner and still requires
`--approved-live-orders` plus Coinbase REST credentials.

Validate a generated SELL allowlist sweep config before live execution:

```powershell
python tools/run_spot_portfolio_sweep_live.py --config-file runtime_state/spot_campaign_sell.strict.allowlist.sweep.json --validate-config --max-products 3 --max-total-notional-per-run 4 --max-notional-per-order 2 --max-planned-orders 3 --max-skipped-orders 500
```

Omit `--summary-only` for the immediate pre-live check so the exact product
ids, base sizes, estimated prices, notional, and `sell_authority` rows are
visible. The summary includes `sell_authority_allowlist_freshness`,
`inventory_baseline_freshness_audit`, `safety_evaluation`, and
`plan_explain`.

Only after explicit live approval, execute through the sweep runner:

```powershell
python tools/run_spot_portfolio_sweep_live.py --config-file runtime_state/spot_campaign_sell.strict.allowlist.sweep.json --approved-live-orders --max-products 3 --max-total-notional-per-run 4 --max-notional-per-order 2 --max-planned-orders 3 --max-skipped-orders 500
```

The live summary must report `live_coinbase_orders_ran`, submitted notional,
executed notional, product ids, `client_order_id` values, exchange order ids,
and fill-backfill results.

When `allow_coinbase_average_cost_basis` is enabled, the same validator/live
runner applies `coinbase_average_cost_authority_gate`. Only planned rows whose
SELL authority actually comes from Coinbase average cost are blocked by stale
average-cost freshness or stale local-vs-Coinbase drift.

## Preview A Broad SELL Decision Gate

Use the sweep validator for the final pre-live broad SELL decision. This reads
Coinbase products, account wallets, and Coinbase average cost data, but it
submits no orders:

```powershell
python tools/run_spot_portfolio_sweep_live.py --validate-config --side SELL --quote-notional 1.01 --order-type market_ioc --require-known-profitable-inventory --allow-coinbase-average-cost-basis --coinbase-average-cost-profit-buffer-pct 0.5 --max-total-notional-per-run 500 --max-notional-per-order 2 --max-planned-orders 400 --max-skipped-orders 500 --summary-only
```

Omit `--summary-only` when you need the per-product `sell_authority` rows. Do
not run a broad live SELL unless this read-only gate has zero safety violations,
or unless the live config is narrowed to an allowlist that has zero violations
when revalidated.
