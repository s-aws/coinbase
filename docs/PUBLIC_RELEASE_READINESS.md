# Public Release Readiness

> **Current operator boundary:** raw smoke, sweep, campaign, legacy dashboard,
> and legacy engine mutations are source-disabled. Release validation must use
> synthetic/no-live checks. The six installed Controlled-live mutation routes
> are manual root place/cancel, explicit attached-intent materialization/
> exact-child safe-closeout, and operator Hotpoint run-once/exact-child
> safe-closeout under the manager-issued lease and
> all backend per-request gates. Intent attachment is local-only; each successor
> mutation requires fresh, separate operator acknowledgement and cannot run
> automatically.

This is a closeout policy, not a work queue. Current scope is
`operator_ready_admin_mvp_runtime_v1`; Slice 2R12 is terminal consumed and
grants no retry or successor authority.

Use these gates when preparing the project for public release or validating a
spot-specific feature before live trading.

## Local Required Gates

Run focused tests for ordinary backend changes. Run the repository regression
gate before durable milestone closeout, public/release-candidate handoff,
deployment approval/closeout, release-hardening closeout, Admin API/backend
association closeout, or explicit full-gate request:

```powershell
python3.13 tools/run_parallel_regression.py --workers 4
```

Run the focused spot readiness gate after spot trading changes:

```powershell
python3.13 tools/run_spot_readiness_regression.py
```

The read-only spot release wrapper runs the focused gate and prints a single
summary line:

```powershell
python3.13 tools/run_spot_release_gate.py
```

Optional read-only additions:

```powershell
python3.13 tools/run_spot_release_gate.py --include-browser
python3.13 tools/run_spot_release_gate.py --include-coinbase-readonly
python3.13 tools/run_spot_release_gate.py --campaign-config-file runtime_state/spot_campaign_buy.json
python3.13 tools/run_spot_release_gate.py --campaign-config-file runtime_state/spot_campaign_buy_all_usdc.json --campaign-all-usdc-readiness
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

For the enterprise admin frontend sibling repository at
`/home/developer/coinbase/coinbase-frontend`,
run the canonical no-live release gate:

```powershell
npm run release:gate
```

This expands to build, typecheck, lint, generated API freshness, command
security, release/deployment checks, artifact generation, runtime evidence,
deployment/MVP/backend smoke evidence, unit tests, dry read/command/BFF
smokes, and Playwright e2e. These checks are dry/no-live checks. They must
report live Coinbase execution as not run with notional `$0`.

`npm run release:artifact` writes
`artifacts/release-readiness.json` in the frontend repository for local
release evidence.
`npm run deployment:package` writes
`artifacts/deployment-package-manifest.json`, and
`npm run observability:drill` writes `artifacts/observability-drill.json`.
`npm run probe:synthetic` writes `artifacts/synthetic-probes.json`, and
`npm run release:checklist` writes
`artifacts/public-release-checklist.json`. `npm run runtime:evidence` writes
`artifacts/runtime-evidence.json`.
It is release evidence for the controlled-live Admin frontend candidate, not
approval for live Coinbase execution. Default release checks remain no-live.
These checks do not replace this
repository's backend regression closeout gate when a milestone or release is
being marked complete.

The frontend `npm run autonomous:check` command remains available for
historical autonomous queue maintenance. It is not part of the local MVP
release/deployment gate.

Frontend production readiness is conditional on a real backend OIDC/JWT
session bridge. Current `server_env_static` BFF authority is local or staging
evidence, not final enterprise production auth. Backend `oidc_jwt` readiness
reports required issuer, audience, and JWKS settings and fails closed when
they are missing or when JWT verification fails.
Use `GET /api/v1/admin/oidc-readiness` as backend release evidence for active
auth mode, missing environment settings, claim mapping, JWKS reachability, and
no-live notional posture.

Backend no-live OIDC readiness smoke evidence is available as optional
production-auth evidence with:

```powershell
python3.13 tools/run_admin_oidc_readiness_smoke.py --summary-only
```

The frontend `npm run smoke:oidc:dry` command can run that backend smoke from
the sibling checkout as optional production-auth evidence. It is not part of
the local MVP release/deployment gate and must also report live Coinbase
execution as not run with notional `$0`.

## Browser Smoke Gate

Install Playwright support for the Python used by `pytest`:

```powershell
py -3.13 -m pip install playwright pytest-playwright
py -3.13 -m playwright install chromium
```

Run the browser smoke gate:

```powershell
python3.13 tools/run_spot_readiness_browser_smoke.py
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

## Historical Live Coinbase Spot Smoke (Source-Disabled)

The commands in this section are retained as historical evidence. Their raw
mutation CLI is now source-disabled and exits before constructing a Coinbase
SDK client. They must not be used as operator execution instructions.

Historical prerequisites were:

- `COINBASE_API_KEY`
- `COINBASE_API_SECRET`
- explicit human approval for live orders
- enough USDC to cover the selected product's minimum quote size and fees

Historical command (now exits source-disabled):

```powershell
python3.13 tools/run_live_spot_usdc_smoke.py --approved-live-orders
```

Historical validation/reconciliation combination (also source-disabled):

```powershell
python3.13 tools/run_live_spot_usdc_smoke.py --approved-live-orders --validation-matrix --reconciliation-gate
```

Before retirement, the runner selected a previewable USDC pair and printed a
`LIVE_COINBASE_SPOT_SMOKE_SUMMARY`. Historical summaries contained:

- product selection rule and product id
- every submitted live order
- submitted notional per order
- executed notional per order
- retained base inventory, when `--retain-inventory` is used
- total submitted and executed notional
- fill-ledger REST backfill result and reconciliation-gate status, when the
  gate is used

No current live run can originate from this CLI.

Historical smoke artifacts used short prefixed `client_order_id` values. That
historical exception grants no current order authority. The four current
Controlled-live mutation routes use the Admin API identity, route-specific
acknowledgement, audit, and reconciliation contracts described above.
