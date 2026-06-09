# Spot Trading Examples

## Verify The Configured BTC Spot Product

```powershell
python -c "from configuration import SPOT_PRODUCT_IDS, get_trading_product_id; print(SPOT_PRODUCT_IDS); print(get_trading_product_id('BTC-USD'))"
```

Expected result: `BTC-USD` appears in `SPOT_PRODUCT_IDS`, and
`get_trading_product_id('BTC-USD')` returns `BTC-USD`.

## Validate A BTC Spot Size

```powershell
python -c "from calculation.size_validation import validate_and_quantize_size; print(validate_and_quantize_size(0.00123456, product_id='BTC-USD', price=100000.0))"
```

The result should be truthy when the quantized base size and quote notional meet
the product metadata minimums.

## Resolve Product Type

```powershell
python -c "from configuration import normalize_product_type; print(normalize_product_type({'product_id': 'BTC-USD'}))"
```

Expected result: `SPOT`.

## Configure Spot Wallet Guarding

Spot wallet checks are part of the action-condition guard. With Coinbase REST
credentials configured, the default guard checks base balance for spot `SELL`
and quote balance for spot `BUY` during stealth planning and reveal.

To make missing credentials a hard block:

```powershell
$env:ACTION_CONDITION_GUARDS_JSON = '{"wallet_available":{"enabled":true,"block_without_credentials":true}}'
```

See [Action Condition Guard Examples](action-condition-guards.md) for configured
notional caps and futures/perpetual caps.

## Inspect Planned Spot Budget

Planned budget is derived from current stealth order state, not a separate
reservation table:

```powershell
python -c "from core.action_condition_guard import collect_spot_planned_budget_commitments; from core.enums import OrderSide, StealthOrderStatus; orders={'a': {'stealth_order_id':'a','product_id':'BTC-USD','side':OrderSide.SELL.value,'remaining_size':0.25,'limit_price':100000,'status':StealthOrderStatus.HIDDEN.value}}; print(collect_spot_planned_budget_commitments(orders))"
```

Expected result: `{'BTC': 0.25}`. Change the status to `REVEALED`,
`EXECUTED`, or `CANCELLED` and the commitment drops out.

## Inspect Spot Capabilities

Spot capabilities are evaluated through the shared product capability policy:

```powershell
python -c "from core.enums import ProductCapability; from core.product_capability import evaluate_product_capability; print(evaluate_product_capability(product_id='BTC-USD', capability=ProductCapability.MOVE_REVEALED).to_dict())"
```

Expected default: `move_revealed` is `disabled` for `SPOT`.

Temporary overrides can be supplied with `PRODUCT_CAPABILITIES_JSON`:

```powershell
$env:PRODUCT_CAPABILITIES_JSON = '{"product_type":{"SPOT":{"move_revealed":"enabled"}}}'
```

Move/reprice replacement now has replace-aware wallet guarding, but the default
spot capability policy still leaves it disabled. Only enable it deliberately;
lot/inventory authority and dashboard readiness are still later roadmap work.

## Inspect Spot Follow-Up Intent

Spot follow-ups are classified before creation:

```powershell
python -c "from core.enums import OrderSide, SpotFollowUpTrigger; from core.spot_follow_up_policy import evaluate_spot_follow_up_policy; print(evaluate_spot_follow_up_policy(product_id='BTC-USD', source_side=OrderSide.SELL.value, follow_up_side=OrderSide.BUY.value, trigger=SpotFollowUpTrigger.FILLED).to_dict())"
```

Expected default: `SELL` fill to `BUY` follow-up is `rebuy` and blocked.

To deliberately enable spot rebuy follow-ups:

```powershell
$env:SPOT_FOLLOW_UP_POLICY_JSON = '{"allow_rebuy":true}'
```

Same-side replacement follow-ups remain blocked unless
`allow_same_side_replacement` is explicitly enabled and the action-condition
guard can satisfy wallet/planned-budget checks.

## Import Existing Spot Inventory

Pre-existing wallet inventory can be made visible to lot authority with an
imported baseline:

```powershell
$env:SPOT_INVENTORY_BASELINES_JSON = '[{"product_id":"BTC-USD","quantity":0.25,"entry_price":90000,"source_id":"manual-baseline"}]'
```

Known `entry_price` makes the baseline eligible for known-profit checks.
Missing or non-positive `entry_price` imports the quantity with unknown cost
basis; it remains visible but cannot be treated as profitable.

To require known profitable lots for spot sells:

```powershell
$env:ACTION_CONDITION_GUARDS_JSON = '{"known_inventory_available":{"enabled":true}}'
```

## Direct Dashboard Spot Order Guarding

Raw dashboard `place_order` messages also run the planning-phase action guard
after size validation and before REST placement:

```json
{
  "type": "place_order",
  "params": {
    "product_id": "BTC-USD",
    "side": "BUY",
    "order_configuration": {
      "market_market_ioc": {
        "quote_size": "250"
      }
    }
  }
}
```

## Request Spot Readiness Feedback

The stealth orders dashboard requests this automatically. For websocket tests or
operator tooling, send:

```json
{"type": "request_spot_readiness"}
```

The response includes spot capability modes and reasons, planned local spot
budget by currency, wallet snapshot age when credentials are available,
enabled guard policy blocks, guard phase coverage, and imported baseline
inventory split by known and unknown cost basis.

## Refresh Product Metadata From The Dashboard

Send the existing dashboard request:

```json
{"type": "update_products_list"}
```

The dashboard updates `products.json` through the existing product refresh path.
After refresh, verify any `ticker_to_trading` mapping still points only to live,
tradable products.
