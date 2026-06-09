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
runner, not the campaign CLI.

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
`--approved-live-orders`.
