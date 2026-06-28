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
- `live_coinbase_read_ran` is `false` unless the backend explicitly enabled
  read-only Coinbase account/market inventory reads
- `submitted_notional_usdc` and `executed_notional_usdc` are `0`
- `spot_balances`, `spot_wallets`, `spot_fills`, and `product_catalog` are
  `read_only_ready`
- when `COINBASE_ADMIN_API_ACCOUNT_MARKET_INVENTORY_READS` is not enabled, the
  same four families report `data_status=blocked`, empty `records`, and a
  `data_fetch_error` explaining the disabled read
- ready families include backend route refs such as `/api/v1/orders` and
  `/api/v1/futures/account`

This command reads backend evidence only by default. When backend Coinbase
reads are explicitly enabled, it may make read-only product, account, and fill
requests from the backend. It never mutates orders, balances, fills, products,
campaigns, or futures state.
