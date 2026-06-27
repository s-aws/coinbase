# Account And Market Inventory Examples

Read inventory coverage:

```powershell
curl.exe -H "Authorization: Bearer local-admin-token" `
  -H "X-Admin-Actor: operator-001" `
  -H "X-Admin-Roles: viewer" `
  http://127.0.0.1:8787/api/v1/admin/account-market-inventory
```

Expected operator signals:

- `type` is `admin_account_market_inventory`
- `live_coinbase_orders_ran` is `false`
- `submitted_notional_usdc` and `executed_notional_usdc` are `0`
- `spot_balances`, `spot_wallets`, `spot_fills`, and `product_catalog` are
  currently `not_modeled`
- ready families include backend route refs such as `/api/v1/orders` and
  `/api/v1/futures/account`

This command reads backend evidence only. It does not call Coinbase or mutate
orders, balances, fills, products, campaigns, or futures state.
