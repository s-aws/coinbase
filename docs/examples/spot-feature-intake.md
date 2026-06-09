# Spot Feature Intake Examples

Use the intake gate before implementing a new spot-specific feature. It is
local-only and read-only; it does not call Coinbase and cannot submit orders.

## Validate A Feature Request

```powershell
python tools/run_spot_feature_intake_gate.py --request-file runtime_state/spot_feature_request.json --summary-only
```

The output prefix is `SPOT_FEATURE_INTAKE_GATE`. A passing request sets
`phase_50_ready: true`.

The current all-USDC spot campaign intake fixture is
[`spot-feature-intake-usdc-campaign.json`](spot-feature-intake-usdc-campaign.json).
It captures the approved scope for buying or selling capped notional across
eligible Coinbase US-customer-available crypto-USDC products. The fixture uses
small numeric defaults so the gate can validate concrete cadence and notional
caps; the listed `operator_configurable_fields` are still runtime campaign
configuration values, not hard-coded limits.

## Request Template

```json
{
  "feature_name": "example_spot_feature",
  "goal": "Buy and sell approved USDC spot products under explicit caps.",
  "product_scope": {
    "quote_currency": "USDC",
    "us_customer_available": true,
    "selection_rule": "all_coinbase_usdc_spot_us_customer_available"
  },
  "order_sides": ["BUY", "SELL"],
  "order_types": ["market_ioc", "limit_gtc"],
  "automation": {
    "repeat_every_hours": "6",
    "max_runs": 3
  },
  "live_approval": {
    "required": true
  },
  "safety": {
    "max_notional_per_order": "1",
    "max_total_notional_per_run": "10"
  },
  "inventory_policy": {
    "retention": "retain"
  },
  "cost_basis_authority": {
    "allowed_sources": ["fill_ledger", "imported_baseline"]
  },
  "audit": {
    "required_evidence": [
      "client_order_id",
      "exchange_order_id",
      "submitted_notional_usdc",
      "executed_notional_usdc",
      "fill_ledger_reconciliation"
    ]
  }
}
```

Supported `order_types` are `market_ioc`, `limit_gtc`, and
`limit_gtc_post_only`. Supported inventory retention policies are `retain`,
`zero_out`, and `explicit_operator_decision`.

Supported `cost_basis_authority.allowed_sources` values are `fill_ledger`,
`imported_baseline`, `coinbase_average_cost`, and `wallet_only`. If
`coinbase_average_cost` is allowed, also include
`cost_basis_authority.coinbase_average_cost_profit_buffer_pct`.

## Check Missing Scope

```powershell
python tools/run_spot_feature_intake_gate.py --allow-incomplete --summary-only
```

This prints the missing fields without failing the shell command. Without
`--allow-incomplete`, incomplete or invalid intake exits nonzero.
