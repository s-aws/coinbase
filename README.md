# Coinbase Advanced Trading Engine

This repository contains the Coinbase Advanced Trading engine, which provides functionality for managing stealth orders, fills, and lifecycle control for trading on Coinbase Advanced Trade.

## What To Expect

- Multithreaded Coinbase Advanced Trade automation.
- Spot and Coinbase Derivatives product support through one shared order path.
- Stealth order lifecycle, reveal, repricing, cancel/re-entry, and fill reconciliation.
- Browser and terminal dashboard surfaces.

The checked-in `products.json` is a minimal local catalog, not the full
Coinbase spot universe. Direct dashboard and stealth order entry use configured
products from that catalog. USDC portfolio sweep and campaign workflows fetch
eligible Coinbase `BASE-USDC` spot products dynamically and have their own
dry-run, cap, approval, retry, audit, and P/L surfaces.

For the ordered documentation index, start at [docs/README.md](docs/README.md).
For spot setup notes, see [README.spot-trading.md](README.spot-trading.md).
For USDC-only spot portfolio sweep planning, see
[README.spot-portfolio-sweep.md](README.spot-portfolio-sweep.md).
For account-level stealth planning/reveal guards, see
[README.action-condition-guards.md](README.action-condition-guards.md).
For the enterprise admin API boundary, see
[README.admin-api.md](README.admin-api.md).
For backend maintainer handoff, see
[docs/MAINTAINER_HANDOFF.md](docs/MAINTAINER_HANDOFF.md).

## Setup

To set up the environment, install the package in development mode:

```bash
py -3.13 -m pip install -e .
```

## Configuration

The engine uses the following environment variables:

- `COINBASE_API_KEY` - Coinbase API key for authentication
- `COINBASE_API_SECRET` - Coinbase API secret for authentication
- `COINBASE_USE_SANDBOX` - Set to "true" to use Coinbase sandbox environment

Backend-only Admin smoke and controlled-live tools can also load live
credentials from the default AWS Secrets Manager secret id `coinbase`. Override
it with `COINBASE_SECRETS_MANAGER_SECRET_ID`,
`COINBASE_API_CREDENTIALS_SECRET_ID`, or `COINBASE_LIVE_CREDENTIALS_SECRET_ID`
in the backend shell, plus `COINBASE_SECRETS_MANAGER_REGION` when needed.
Verify redacted availability without printing values:

```bash
python tools/coinbase_live_credentials.py --check
```

## Runtime

The trading engine runs with the following components:

- WebSocket server: `ws://localhost:8765`
- Main entry point: `main.py`
- Dashboard UI: `ui_stealth_orders_manager.html`

## Tested Environment

This project is tested on:
- Windows 11 + VS Code
- Python 3.13
- Coinbase Advanced Trade API (REST + WebSocket)

Run focused tests and validators for ordinary changes. Full regression is a
durable milestone closeout, public/release-candidate handoff, deployment
approval/closeout, release-hardening closeout, Admin API/backend association
closeout, or explicit user request gate. See
[Regression Process](docs/REGRESSION_PROCESS.md) for the durable policy.

Use the process-parallel runner for that closeout gate:
```powershell
python tools\run_parallel_regression.py --workers 4
```

Sequential pytest is a fallback only when the runner cannot be used:
```powershell
pytest tests/regression/ -v --tb=short
```
