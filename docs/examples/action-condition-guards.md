# Action Condition Guard Examples

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

A `BTC-USD` stealth action with `size * limit_price > 5000` is blocked before
planning persistence or reveal placement. A raw dashboard `place_order` with
the same notional is blocked before `REST_CLIENT.create_order`.

For a direct spot-only cap across configured spot products, scope the rule by
product type and planning phase:

```powershell
$env:ACTION_CONDITION_GUARDS_JSON = '{"limits":[{"name":"direct_spot_cap","product_type":"SPOT","max_notional":100,"phases":["planning"]}]}'
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

## Guard A Direct Dashboard Market BUY

For market BUY payloads that use `quote_size`, configured notional caps and
quote-wallet checks can still run:

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

With `max_notional` below `250`, the dashboard returns an `order_response`
error and does not submit the REST order.

Without `manual_live_acknowledgement: true`, direct spot `place_order` blocks
before the guard and before REST because the raw dashboard surface submits live
immediately.

If hidden spot stealth orders already reserve most of the quote wallet, the same
dashboard path returns `block_category: "planned_budget_available"` before REST
placement.

## Inspect A Spot Replacement Delta

Live spot replacements credit the existing same-currency Coinbase hold instead
of checking the full replacement notional:

```powershell
python -c "from core.action_condition_guard import estimate_spot_replacement_budget_delta; from core.enums import OrderSide; print(estimate_spot_replacement_budget_delta(product_id='BTC-USD', side=OrderSide.BUY.value, size=0.1, limit_price=110000, existing_size=0.1, existing_limit_price=100000))"
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
