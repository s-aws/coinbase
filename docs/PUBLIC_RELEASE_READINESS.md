# Public Release Readiness

Use these gates when preparing the project for public release or validating a
spot-specific feature before live trading.

## Local Required Gates

Run the repository regression gate after non-agent-file changes:

```powershell
pytest tests/regression/ -v --tb=short
```

Run the focused spot readiness gate after spot trading changes:

```powershell
python tools/run_spot_readiness_regression.py
```

The read-only spot release wrapper runs the focused gate and prints a single
summary line:

```powershell
python tools/run_spot_release_gate.py
```

Optional read-only additions:

```powershell
python tools/run_spot_release_gate.py --include-browser
python tools/run_spot_release_gate.py --include-coinbase-readonly
python tools/run_spot_release_gate.py --campaign-config-file runtime_state/spot_campaign_buy.json
python tools/run_spot_release_gate.py --campaign-config-file runtime_state/spot_campaign_buy_all_usdc.json --campaign-all-usdc-readiness
```

The Coinbase read-only option includes sweep status, sweep P/L, average-cost
inventory coverage, and cost-basis drift audit checks. The release wrapper
never submits live Coinbase orders.

The optional campaign config gate runs
`tools/run_spot_campaign.py --release-gate --summary-only`. It validates the
campaign intake, dry-run plan, safety policy, operation lock, recovery
readiness, and durable P/L/cost-basis surfaces without submitting live orders.
The all-USDC campaign gate additionally fails configs that are not explicitly
broad or that omit total/order/count safety caps.

## Admin Frontend Release Gate

For the enterprise admin frontend sibling repository at `C:\coinbase-frontend`,
run:

```powershell
npm run build
npm run release:check
npm run release:artifact
npm run deployment:package
npm run observability:drill
npm run probe:synthetic
npm run release:checklist
npm run deployment:check
npm run smoke:read:dry
npm run smoke:command:dry
npm run smoke:bff:dry
```

These checks are dry/no-live checks. They must report live Coinbase execution
as not run with notional `$0`. `npm run release:artifact` writes
`artifacts/release-readiness.json` in the frontend repository for CI upload.
`npm run deployment:package` writes
`artifacts/deployment-package-manifest.json`, and
`npm run observability:drill` writes `artifacts/observability-drill.json`.
`npm run probe:synthetic` writes `artifacts/synthetic-probes.json`, and
`npm run release:checklist` writes
`artifacts/public-release-checklist.json`.
It is release evidence for the read-only/disabled-command frontend candidate,
not approval for live Coinbase execution. These checks do not replace this
repository's backend regression gate when backend files changed.

Frontend production readiness remains blocked until a real backend OIDC/JWT
session bridge exists. Current `server_env_static` BFF authority is local or
staging evidence, not final enterprise production auth. Backend `oidc_jwt`
readiness reports required issuer, audience, and JWKS settings, but the
verifier remains fail-closed until implementation is complete.

## Browser Smoke Gate

Install Playwright support for the Python used by `pytest`:

```powershell
py -3.13 -m pip install playwright pytest-playwright
py -3.13 -m playwright install chromium
```

Run the browser smoke gate:

```powershell
python tools/run_spot_readiness_browser_smoke.py
```

This opens `ui_stealth_orders_manager.html` in Chromium, stubs the dashboard
websocket, verifies `request_spot_readiness` is sent, and verifies a
server-shaped readiness payload renders in the operator panel.

## External Sandbox Tests

Sandbox external tests remain isolated from local regression:

```powershell
$env:COINBASE_API_KEY = "..."
$env:COINBASE_API_SECRET = "..."
$env:COINBASE_USE_SANDBOX = "true"
pytest tests/external/ -v -m external --tb=short
```

## Live Coinbase Spot Smoke

Live spot smoke is a manual release-readiness check. It places real Coinbase
Advanced Trade spot orders and must never be part of default regression or
default CI.

Required:

- `COINBASE_API_KEY`
- `COINBASE_API_SECRET`
- explicit human approval for live orders
- enough USDC to cover the selected product's minimum quote size and fees

Command:

```powershell
python tools/run_live_spot_usdc_smoke.py --approved-live-orders
```

Validation matrix with reconciliation gate:

```powershell
python tools/run_live_spot_usdc_smoke.py --approved-live-orders --validation-matrix --reconciliation-gate
```

The runner selects the lowest-minimum-notional, lowest-price, online,
tradable USDC-quoted spot pair that previews successfully for the account. It
prints a `LIVE_COINBASE_SPOT_SMOKE_SUMMARY` JSON line with:

- product selection rule and product id
- every submitted live order
- submitted notional per order
- executed notional per order
- retained base inventory, when `--retain-inventory` is used
- total submitted and executed notional
- fill-ledger REST backfill result and reconciliation-gate status, when the
  gate is used

When a live run is reported in project discussion, call it out explicitly as a
live Coinbase run and include the notional totals from the summary.

The live smoke runner uses short prefixed `client_order_id` values for its
standalone smoke artifacts. That is a smoke-tool exception. Campaign and
portfolio sweep live orders must keep UUID `client_order_id` values and record
workflow identity through sweep/campaign ledger fields instead of Coinbase-
facing prefixes.

The smoke does not have to zero out the account. Use `--retain-inventory` when
the bought base should remain in the account for future sell-path tests instead
of being sold immediately.
