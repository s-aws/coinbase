# Coinbase Trading Backend

This repository is the backend for the Coinbase trading system. The modern
direction is a backend-owned Admin API with typed contracts, append-only
evidence, generated OpenAPI, focused local validation, and explicit live
execution gates. Legacy engine and dashboard code still exists, but new product
work should move through backend-owned API contracts rather than browser-side
trading decisions or direct dashboard authority.

This README is intentionally a short orientation. It does not enumerate every
workflow or module; detailed behavior lives in the linked docs and durable MVP
plans.

## Current MVP Goal

Current goal id
`futures_preview_acceptance_recovery_r8_r10_and_conditional_terminal_roundtrip_slice_3`
records bounded Default-profile AVAX US CFM Preview-acceptance recovery under
the unchanged one-contract V3 policy and strict `<100 / <150 / <300 USDC`
limits. R8 is terminal blocked with zero Preview or real Coinbase calls; R9 is
terminal blocked after one returned Preview failed response validation, with
zero retries or exchange mutations. R10 is the current preparation-only
generation. Its Preview maximum and the remaining recovery maximum are both
one; there is no R11. Current exchange-mutation maximum is zero. Slice 3 is
conditional, but Coinbase documents no Preview expiry field or TTL, so its
pre-Create mutation gate remains fail-closed even after acceptance unless
authoritative freshness evidence becomes available; Slices 4/5 are
unauthorized. See
[Coinbase Admin MVP Goal](genai_data/AGENT_MVP_REBUILD_GOAL.md). Historical M57
phase ranges and M58 fan-out/scheduler blockers do not select default work.

## Current Posture

- Python 3.13 is the supported backend interpreter.
- The Admin API is the modernization boundary for operator-facing product work.
- Live execution is fail-closed unless backend evidence proves authorization,
  idempotency, caps, audit, reconciliation, wallet, rollback, and runtime
  controls for the requested scope.
- `client_order_id` is the internal tracking key. Exchange `order_id` is
  exchange evidence only unless a Coinbase endpoint specifically requires it.
- Frontend code consumes generated contracts and read-only evidence; Coinbase
  credentials and trading decisions stay backend-side.

## Runtime Boundaries

The checked-in `products.json` is a minimal local catalog, not the full
Coinbase spot universe. Legacy direct dashboard and stealth order entry use
configured products from that catalog. Modern USDC campaign and Admin API
workflows fetch or persist their own backend evidence and must prove dry-run,
cap, approval, retry, audit, wallet, reconciliation, and rollback posture before
live submission.

The legacy dashboard WebSocket remains available for compatibility and source
material. It is not the authority for new frontend product UI. New operator UI
work should use the generated Admin API contract and backend read models.

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

Install the package in development mode with Python 3.13:

```bash
python3.13 -m pip install -e .
```

On Windows, `py -3.13 -m pip install -e .` is also valid.

## Configuration

The engine uses the following environment variables:

- `COINBASE_API_KEY` - Coinbase API key for authentication
- `COINBASE_API_SECRET` - Coinbase API secret for authentication
- `COINBASE_USE_SANDBOX` - Set to "true" to use Coinbase sandbox environment

Backend-only Admin API smoke and controlled-live tools can also load live
credentials from the default AWS Secrets Manager secret id `coinbase`. Override
it with `COINBASE_SECRETS_MANAGER_SECRET_ID`,
`COINBASE_API_CREDENTIALS_SECRET_ID`, or `COINBASE_LIVE_CREDENTIALS_SECRET_ID`
in the backend shell, plus `COINBASE_SECRETS_MANAGER_REGION` when needed.
Verify redacted availability without printing values:

```bash
python3.13 tools/coinbase_live_credentials.py --check
```

## Runtime

Common local entry points:

- Admin API/OpenAPI contract: `api/`, `application/admin_api/`, `openapi/`
- Main engine entry point: `main.py`
- Legacy dashboard WebSocket: `ws://localhost:8765` through `dashboard_server.py`
- Legacy dashboard UI: `ui_stealth_orders_manager.html`

Generate the Admin API contract after backend model or route changes:

```bash
python3.13 tools/generate_admin_api_openapi.py
```

## Tested Environment

This project is tested on:
- Local Linux Docker
- Python 3.13
- Coinbase Advanced Trade API (REST + WebSocket)

Run focused tests and validators for ordinary changes. Full regression is a
durable milestone closeout, public/release-candidate handoff, deployment
approval/closeout, release-hardening closeout, Admin API/backend association
closeout, or explicit user request gate. See
[Regression Process](docs/REGRESSION_PROCESS.md) for the durable policy.

In the local Linux Docker environment, use `python3.13` for backend scripts,
OpenAPI generation, ownership checks, and compile checks. The `python` alias
may be unavailable, and `/usr/bin/python3` may not be the backend dependency
interpreter. Use the installed `pytest` executable directly for test targets
unless a command specifically requires module execution; the repo pytest
executable runs under Python 3.13.

Use the process-parallel runner for that closeout gate:
```powershell
python3.13 tools/run_parallel_regression.py --workers 4
```

Sequential pytest is a fallback only when the runner cannot be used:
```powershell
pytest tests/regression/ -v --tb=short
```
