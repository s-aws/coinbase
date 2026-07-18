# Action Condition Guard Examples

These examples exercise offline/local guard evaluation and historical
regression fixtures. They do not grant exchange authority. Legacy dashboard,
stealth/reveal, replacement, sweep, and engine mutation paths are
source-disabled; Controlled-live manual Spot LIMIT/GTC place/cancel is admitted
only by the authenticated Admin API chain.

## Enable Default Spot Wallet Checks

With Coinbase REST credentials configured, `wallet_available` is enabled by
default for stealth planning and reveal. This explicit config only changes the
blocked-reveal retry interval:

```powershell
$env:ACTION_CONDITION_GUARDS_JSON = '{"wallet_available":{"enabled":true,"blocked_retry_seconds":5}}'
```

Spot checks:

- `SELL`: base currency available balance must cover order size.
- `BUY`: quote currency available balance must cover `size * limit_price`.

Wallet checks follow Coinbase account pagination before evaluating balances.

When a stealth manager is attached, the guard also subtracts local pre-exchange
spot commitments. HIDDEN, PENDING, and TRIGGERED stealth orders count;
REVEALED, EXECUTED, and CANCELLED orders do not.

Spot follow-up stealth orders run the planning check by default. To opt out
deliberately:

```powershell
$env:ACTION_CONDITION_GUARDS_JSON = '{"wallet_available":{"enabled":true,"check_follow_up_planning":false}}'
```

## Block Without REST Credentials

Use this when the process must never admit stealth spot wallet checks unless
authenticated account state is available:

```powershell
$env:ACTION_CONDITION_GUARDS_JSON = '{"wallet_available":{"enabled":true,"block_without_credentials":true}}'
```

## Add A Spot Notional Cap

```powershell
$env:ACTION_CONDITION_GUARDS_JSON = '{"limits":[{"name":"btc_spot_cap","product_id":"BTC-USD","max_notional":5000,"phases":["planning","reveal"]}]}'
```

A synthetic `BTC-USD` stealth action with `size * limit_price > 5000` is
blocked before offline planning persistence or simulated reveal. Historical
raw-dashboard fixtures can assert the same guard result, but the dashboard
mutation message itself returns a fixed source-disabled response before guard
or REST lookup.

For a direct spot-only cap across configured spot products, scope the rule by
product type and planning phase:

```powershell
$env:ACTION_CONDITION_GUARDS_JSON = '{"limits":[{"name":"direct_spot_cap","product_type":"SPOT","max_notional":100,"phases":["planning"]}]}'
```

The checked-in `products.json` intentionally does not include an account-wide
direct-order cap. A planning-phase `max_notional` policy can be used for
offline guard evidence, but it cannot enable raw-dashboard placement or mint
the canonical Admin API request scope.

## Offline Direct Spot Guard Baseline

Use this shape to test a direct-order planning cap and known-profitable-
inventory policy against configured spot products in `products.json`.
USDC sweep/campaign fixtures have separate run-level caps and authority
allowlists. This configuration is guard input only; it does not enable an
exchange submission surface.

```powershell
$env:ACTION_CONDITION_GUARDS_JSON = '{"wallet_available":{"enabled":true,"block_without_credentials":true},"known_inventory_available":{"enabled":true,"phases":["planning"]},"limits":[{"name":"direct_spot_order_cap","product_type":"SPOT","max_notional":25,"phases":["planning"]}]}'
```

The same object can be stored in `products.json` under
`action_condition_guards`:

```json
{
  "action_condition_guards": {
    "wallet_available": {
      "enabled": true,
      "block_without_credentials": true
    },
    "known_inventory_available": {
      "enabled": true,
      "phases": ["planning"]
    },
    "limits": [
      {
        "name": "direct_spot_order_cap",
        "product_type": "SPOT",
        "max_notional": 25,
        "phases": ["planning"]
      }
    ]
  }
}
```

## Add A Futures Contract Cap

```powershell
$env:ACTION_CONDITION_GUARDS_JSON = '{"limits":[{"name":"btc_future_contract_cap","product_type":"FUTURE","max_base_size":10,"phases":["planning","reveal"]}]}'
```

Any configured futures product with size above `10` contracts is blocked at the
same two stealth boundaries.

## Require Known Profitable Inventory For Spot SELL

This is opt-in. It is useful only after fill-ledger persistence and any imported
baseline inventory are configured:

```powershell
$env:ACTION_CONDITION_GUARDS_JSON = '{"known_inventory_available":{"enabled":true,"phases":["planning","reveal"]}}'
```

With this enabled, a spot `SELL` must be covered by known profitable `BUY` lots.
Wallet balance is still checked separately by `wallet_available`; unknown-cost
inventory does not satisfy known-profit authority.

Imported baseline inventory can be supplied when the account already holds spot
assets before this project recorded the fills:

```powershell
$env:SPOT_INVENTORY_BASELINES_JSON = '[{"product_id":"BTC-USD","quantity":0.25,"entry_price":90000,"source_id":"manual-2026-06-08"}]'
```

If `entry_price` is omitted or non-positive, the baseline lot is imported as
unknown cost basis. It appears in inventory reports but blocks
`known_inventory_available` until replaced by a known-cost import.

## Inspect A Historical Dashboard Market-BUY Fixture

Historical regression fixtures for market BUY payloads that use `quote_size`
can evaluate configured notional caps and quote-wallet checks:

```json
{
  "type": "place_order",
  "params": {
    "product_id": "BTC-USD",
    "side": "BUY",
    "manual_live_acknowledgement": true,
    "order_configuration": {
      "market_market_ioc": {
        "quote_size": "250"
      }
    }
  }
}
```

With `max_notional` below `250`, the guard fixture records a blocked result. If
synthetic hidden stealth orders reserve most of the quote wallet, it records
`block_category: "planned_budget_available"`. These assertions preserve legacy
calculation coverage only: the installed dashboard `place_order` message always
returns the fixed source-disabled response and never reaches REST.

## Inspect A Spot Replacement Delta

The synthetic replacement calculator credits an existing same-currency hold
instead of checking the full replacement notional:

```powershell
python3.13 -c "from core.action_condition_guard import estimate_spot_replacement_budget_delta; from core.enums import OrderSide; print(estimate_spot_replacement_budget_delta(product_id='BTC-USD', side=OrderSide.BUY.value, size=0.1, limit_price=110000, existing_size=0.1, existing_limit_price=100000))"
```

Expected shape: `currency` is `USD`, `new_required` is `11000`, and `amount`
is the net delta `1000`.

## File-Backed Default

The same shape may be stored in `products.json`:

```json
{
  "action_condition_guards": {
    "wallet_available": {
      "enabled": true,
      "blocked_retry_seconds": 5
    },
    "limits": [
      {
        "name": "btc_spot_cap",
        "product_id": "BTC-USD",
        "max_notional": 5000,
        "phases": ["planning", "reveal"]
      }
    ]
  }
}
```

`ACTION_CONDITION_GUARDS_JSON` overrides the file-backed default.
