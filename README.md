# Coinbase Advanced Trading Engine

This repository contains the Coinbase Advanced Trading engine, which provides functionality for managing stealth orders, fills, and lifecycle control for trading on Coinbase Advanced Trade.

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