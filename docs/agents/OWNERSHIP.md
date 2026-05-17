# Ownership Boundaries

This file is the human-readable companion to `.agents/ownership.yaml`.

## Core Rule

Every non-trivial change has exactly one primary owner. Other owners may
coordinate, review, or update their own files, but no behavior should be
implemented in two places.

## Owners

| Owner id | Role | Main files |
| --- | --- | --- |
| `architect` | Boundary decisions and routing | `docs/agents/*`, `.agents/ownership.yaml` |
| `core_types` | Shared domain vocabulary | `core/enums.py`, `core/models.py`, `core/constants.py`, `core/exceptions.py` |
| `runtime_lifecycle` | Startup, shutdown, admission, reconciliation orchestration | `main.py`, `core/runtime_controller.py`, `core/startup_reconciler.py`, `core/periodic_reconciler.py` |
| `order_lifecycle` | Parent/child lifecycle and follow-ups | `core/order_engine.py`, `core/orderbook.py`, `business/order_progress.py`, `business/move_manager.py` |
| `stealth_lifecycle` | Stealth state machine and active placement truth | `core/stealth_order_manager.py`, stealth policy/strategy modules |
| `bridge_hook` | Bridges, hook registries, dedup entrypoints | `bridges/*`, `integration/*`, `business/event_processor.py` |
| `dashboard_contract` | WebSocket contract and operator UI | `dashboard_server.py`, `order.py`, `ui_*.html`, console UIs |
| `persistence` | Schema, SQL helpers, repositories | `database/*`, `data/*` |
| `fill_audit` | Fill ledger, fill reconciliation, event stream | `business/fill_ledger.py`, `business/fill_reconciler.py`, `business/order_event_stream.py` |
| `calculation` | Size, price, fee, product, profitability helpers | `calculation/*` |
| `configuration` | Product catalog and package/runtime config | `configuration.py`, `products.json`, `pyproject.toml` |
| `exchange_integration` | Exchange clients and websocket payloads | `external/*`, `websocket/*`, API/websocket references |
| `market_analytics` | Market metrics, charting, cross-venue intelligence | `market_intel/*`, market metric/recorder modules, chart UIs |
| `strategy` | Lot, profit, hotpoint, conditional strategy helpers | strategy modules in `business/*` |
| `test_quality` | Shared test infrastructure | `tests/conftest.py`, `tests/pytest.ini`, `tests/fixtures/*` |
| `ops_diagnostics` | Local diagnostics and historical notes | `genai_tools/*`, `docs/archive/*`, `tools/diagnostics/*`, root debug/audit scripts |

## Cross-Boundary Rules

- New enums or shared models start with `core_types`.
- Schema changes start with `persistence` and require the behavior owner.
- Dashboard messages require `dashboard_contract` plus the behavior owner.
- Stealth lifecycle changes require `stealth_lifecycle`; exchange truth cannot be
  faked locally.
- Exchange wrapper changes require `exchange_integration`; lifecycle owners
  decide local state transitions.
- Fill ownership changes require `fill_audit`; `order_id` is not ownership proof.

## Checking Ownership

```powershell
python tools/check_ownership.py
python tools/check_ownership.py --owner <owner_id>
python tools/check_ownership.py --list
```

The public CI workflow checks that changed files are owned. Private
orchestration can run the stricter `--owner <owner_id>` form before publishing.
