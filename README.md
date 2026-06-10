# Coinbase Advanced Trading Engine

This repository contains the Coinbase Advanced Trading engine, which provides functionality for managing stealth orders, fills, and lifecycle control for trading on Coinbase Advanced Trade.

## What To Expect

- Multithreaded Coinbase Advanced Trade automation.
- Spot and Coinbase Derivatives product support through one shared order path.
- Stealth order lifecycle, reveal, repricing, cancel/re-entry, and fill reconciliation.
- Browser and terminal dashboard surfaces.
- A self-contained portfolio site: [Netflix AI Engineer Workbench](README.netflix-ai-engineer-site.md).

For the ordered documentation index, start at [docs/README.md](docs/README.md).
For spot setup notes, see [README.spot-trading.md](README.spot-trading.md).
For USDC-only spot portfolio sweep planning, see
[README.spot-portfolio-sweep.md](README.spot-portfolio-sweep.md).
For account-level stealth planning/reveal guards, see
[README.action-condition-guards.md](README.action-condition-guards.md).
For the planned enterprise admin API boundary, see
[README.admin-api.md](README.admin-api.md).

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

To run tests:
```powershell
pytest tests/regression/ -v --tb=short
```
