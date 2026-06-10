# Spot Readiness Test Gate

Use this gate when changing spot trading behavior or preparing to add a
spot-specific feature:

```powershell
python tools/run_spot_readiness_regression.py
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
python tools/run_spot_readiness_browser_smoke.py
```

The browser smoke gate uses `pytest-playwright` with Chromium. It opens
`ui_stealth_orders_manager.html`, stubs the dashboard websocket, verifies the UI
sends `request_spot_readiness`, and verifies a server-shaped spot readiness
payload renders into the operator panel.

This focused gate does not replace the repository requirement:

```powershell
pytest tests/regression/ -v --tb=short
```

External Coinbase sandbox, wallet smoke, metadata refresh, and paper-mode
scenario replay checks remain opt-in. They must not become default regression
requirements because they depend on credentials, network state, or account
fixtures. Browser smoke can become a public-release/CI gate once Playwright and
Chromium installation are documented for contributors.

Campaign release readiness can be included in the public release wrapper:

```powershell
python tools/run_spot_release_gate.py --campaign-config-file runtime_state/spot_campaign_buy.json
```

For broad all-USDC campaign stages, include the all-USDC gate:

```powershell
python tools/run_spot_release_gate.py --campaign-config-file runtime_state/spot_campaign_buy_all_usdc.json --campaign-all-usdc-readiness
```

This remains read-only. It validates campaign release readiness and the broad
all-USDC intent before any rendered sweep config is handed to the live runner.

For an explicitly approved live Coinbase spot smoke, run:

```powershell
python tools/run_live_spot_usdc_smoke.py --approved-live-orders
```

This places real orders. It selects the lowest-minimum-notional tradable USDC
spot pair that previews successfully for the account, then prints
`LIVE_COINBASE_SPOT_SMOKE_SUMMARY` with submitted and executed notional for
each live order. Use `--retain-inventory` when the acquired base should remain
in the account for future sell-path tests instead of being sold immediately.
