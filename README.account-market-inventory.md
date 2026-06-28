# Account And Market Inventory

`GET /api/v1/admin/account-market-inventory` is the Release 0.1 read model for
account and market inventory coverage.

The route is backend-owned, read-only, and authenticated with
`analytics:read`. It never submits orders, cancels orders, inspects browser
wallet state, or grants BFF execution authority. Its job is to tell the admin
frontend which account/market inventory families are usable now, which bounded
records are currently loaded, and whether any data reads are blocked.

## Current Coverage

- ready backend read contracts: product catalog, spot wallets, spot balances,
  spot fills, orders, spot readiness, spot cost basis, futures account, futures
  positions, guard/risk policy, and audit workbench
- live-disabled command draft evidence: spot campaign status and execution
  posture
- data posture: Coinbase product, wallet, balance, and fill records are read
  by the backend only when `COINBASE_ADMIN_API_ACCOUNT_MARKET_INVENTORY_READS`
  is truthy; otherwise those families stay `read_only_ready` with
  `data_status=blocked`

Each family row includes the backend module id, route when available, source,
record count, data status, data source, record limit, truncation flag, optional
fetch error, bounded records, release-blocking flag, and documentation refs.

## Safety Rules

- Frontend code must render this payload as evidence only.
- Incomplete data must stay visible through `data_status`, `data_fetch_error`,
  and empty `records`; do not fill it from browser logic or dashboard calls.
- Live Coinbase order execution fields stay `not_run` and notional stays `0`.
- `live_coinbase_read_ran` may be true only when the backend performed an
  explicitly enabled read-only Coinbase product, account, or fill request.
- The route inventory row lives under `admin_system_health`; domain-specific
  module ids are carried inside the family rows.

## Examples

See [docs/examples/account-market-inventory.md](docs/examples/account-market-inventory.md).
