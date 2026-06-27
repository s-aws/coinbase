# Account And Market Inventory

`GET /api/v1/admin/account-market-inventory` is the Release 0.1 read model for
account and market inventory coverage.

The route is backend-owned, read-only, and authenticated with
`analytics:read`. It does not call Coinbase, submit orders, inspect browser
wallet state, or grant BFF execution authority. Its job is to tell the admin
frontend which account/market inventory families are usable now and which
families remain explicit `not_modeled` or `unsupported` gaps.

## Current Coverage

- ready read evidence: orders, spot readiness, spot cost basis, futures account,
  futures positions, guard/risk policy, and audit workbench
- live-disabled command draft evidence: spot campaign status and execution
  posture
- Release 0.1 blockers: product catalog, spot wallets, spot balances, and spot
  fills remain `not_modeled`

Each family row includes the backend module id, route when available, source,
record count, release-blocking flag, documentation refs, and the next backend
contract needed to close a gap.

## Safety Rules

- Frontend code must render this payload as evidence only.
- Missing inventory families must stay visible as `not_modeled` or
  `unsupported`; do not fill them from browser logic or dashboard calls.
- Live Coinbase execution fields stay `not_run` and notional stays `0`.
- The route inventory row lives under `admin_system_health`; domain-specific
  module ids are carried inside the family rows.

## Examples

See [docs/examples/account-market-inventory.md](docs/examples/account-market-inventory.md).
