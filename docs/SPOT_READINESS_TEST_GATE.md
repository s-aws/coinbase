# Spot Readiness Test Gate

Use this gate when changing spot trading behavior or preparing to add a
spot-specific feature:

```powershell
python3.13 tools/run_spot_readiness_regression.py
```

The focused gate covers:

- spot product sizing and fee resolution
- product capability defaults and overrides
- action-condition wallet and artificial-limit guards
- planned-budget overcommit and reveal-time wallet drain
- spot follow-up classification
- replace-aware move/reprice guards
- lot reconstruction, imported inventory, and unknown cost basis
- paper-mode spot replay across planning, reveal, and known-inventory sell
- dashboard guard/readiness responses

For public-release readiness or dashboard changes, run the browser smoke gate:

```powershell
python3.13 tools/run_spot_readiness_browser_smoke.py
```

The browser smoke gate uses `pytest-playwright` with Chromium. It opens
`ui_stealth_orders_manager.html`, stubs the dashboard websocket, verifies the UI
sends `request_spot_readiness`, and verifies a server-shaped spot readiness
payload renders into the operator panel.

This focused gate is the ordinary phase-level check for spot behavior. It does
not replace the full repository regression gate when closing a durable
milestone, preparing public/release-candidate handoff, deployment
approval/closeout, release-hardening closeout, Admin API/backend association
closeout, or handling an explicit full-gate request:

```powershell
python3.13 tools/run_parallel_regression.py --workers 4
```

Use `pytest tests/regression/ -v --tb=short` only as an intentional sequential
fallback when `pytest-xdist` is unavailable.

External Coinbase sandbox, wallet smoke, metadata refresh, and paper-mode
scenario replay checks remain opt-in. They must not become default regression
requirements because they depend on credentials, network state, or account
fixtures. Browser smoke can become a public-release/CI gate once Playwright and
Chromium installation are documented for contributors.

Campaign release readiness can be included in the public release wrapper:

```powershell
python3.13 tools/run_spot_release_gate.py --campaign-config-file runtime_state/spot_campaign_buy.json
```

For broad all-USDC campaign stages, include the all-USDC gate:

```powershell
python3.13 tools/run_spot_release_gate.py --campaign-config-file runtime_state/spot_campaign_buy_all_usdc.json --campaign-all-usdc-readiness
```

This remains read-only. It validates campaign release readiness and the broad
all-USDC intent. Rendered sweep configs are review artifacts; the historical
sweep mutation mode is source-disabled.

The historical raw live-smoke command was:

```powershell
python3.13 tools/run_live_spot_usdc_smoke.py --approved-live-orders
```

It is retained only for traceability and now exits before SDK construction with
a fixed source-disabled diagnostic. Do not run it as an operator workflow.
Controlled-live testing uses only authenticated Admin API manual Spot
LIMIT/GTC place/cancel under the manager lease and backend per-request gates.
