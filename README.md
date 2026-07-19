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

Goal `operator_follow_up_operations_queue_and_single_live_proof` has Status:
`complete_zero_candidates`. Current/default action is
`complete_zero_candidates_all_live_allowances_unconsumed`; next action is
`await_operator_direction_for_next_mvp`. The deployed passive local-SQL
Follow-up Operations workspace passed its focused/full, deployment, safety, and
blind-contextless gates. The exact post-gate local `materialization_review`
candidate count is `0`. The queue made no Coinbase read, Create, or Cancel call;
the goal-scoped proof claim was not created or required; and eligibility,
reconciliation, Create, and Cancel did not run. All live allowances remain
unconsumed, but this completed goal grants no continuing proof call. Keep the
Controlled-live review stack available under its separate runtime controls.

Historical goal `futures_preview_acceptance_recovery_r12` is
`complete_terminal_unknown_consumed`. Eligibility cycle 2 completed
`exact_v3_eligible`, created the one durable R12 claim, and left claim-only
evidence. Offline claim recovery appended terminal blocker
`claim_only_recovery_unknown_consumed` without constructing a Coinbase client
or factory. The source-bound `R12_RELEASE_READY` gate is `False`, R12 is
consumed, and no further Coinbase call is permitted. The generic
Preview-attempt counter is conservative: it records the consumed post-claim
attempt boundary as `1` but does not prove network reach. Preview network reach
is therefore unknown; retries, fallbacks, redirects, submissions, exchange
mutations, orders, and submitted/executed notional are all zero. See
[R12 terminal closeout](docs/FUTURES_SLICE_2R12_PREPARATION.md).

The predecessor goal `futures_preview_acceptance_recovery_r11` is complete.
R11 is consumed, terminal `blocked`, immutable, and cannot be retried. It stopped at
`remaining_margin_validation` before Coinbase Preview: all six bounded reads
ran once, while Preview, retry, fallback, redirect, submission, and every
exchange mutation remained `0`. The structured boundary is
`margin_window_type_documented_but_operator_rejected` at row `1`, profile
`retail_intraday_margin_1`, field `margin_window_type`, value type `string`.
This is an exact V3 operator-policy rejection, not authority to broaden schema
or acceptance. It grants no independent successor, Slice 3/4/5 activation, or
live authority; R12 remains governed only by its separate prepared boundary.
See the
[R11 terminal diagnosis](docs/FUTURES_SLICE_2R11_TERMINAL_DIAGNOSIS.md).

Historically, goal
`futures_post_r10_preview_compatibility_and_direction_selection` completed the
prospective separation of Coinbase's official Preview wire schema from the
project's stricter one-contract V3 acceptance policy. Immutable R1-R10 history
is preserved, R10 is not reinterpreted, and R8 content/hash remain inaccessible.
That historical checkpoint granted no successor or live authority and found ten
attempts unwarranted. See the
[post-R10 direction record](docs/FUTURES_POST_R10_COMPATIBILITY_DIRECTION.md)
and [Coinbase Admin MVP Goal](genai_data/AGENT_MVP_REBUILD_GOAL.md). Historical
M57 phase ranges and M58 fan-out/scheduler blockers do not select default work.

## Current Posture

- Python 3.13 is the supported backend interpreter.
- The Admin API is the modernization boundary for operator-facing product work.
- Live execution is fail-closed unless backend evidence proves authorization,
  idempotency, caps, audit, reconciliation, wallet, rollback, and runtime
  controls for the requested scope.
- `client_order_id` is the internal tracking key. Exchange `order_id` is
  exchange evidence only unless a Coinbase endpoint specifically requires it.
- Frontend code consumes generated contracts and may forward explicit operator
  requests to backend gates; Coinbase credentials, trading decisions, and
  execution authority stay backend-side.

## Runtime Boundaries

The checked-in `products.json` is a minimal local catalog, not the full
Coinbase spot universe. Legacy direct dashboard and stealth order entry use
configured products from that catalog. Ordinary Admin UI account, wallet,
product, fee, Spot-readiness, and Futures GETs are local and call-free in both
No-live and Controlled-live modes. Product refresh is source-disabled before
any Coinbase read or `products.json` write.

The legacy dashboard WebSocket remains available for read/control compatibility
and source material, but its exchange mutation messages are source-disabled.
Legacy `main.py` Controlled-live startup and historical raw smoke/sweep/batch
mutation modes are also source-disabled. The four installed Controlled-live
mutation routes are manual root place/cancel and explicit attached-intent
materialization/exact-child safe-closeout. Intent attachment is local-only and
never supplies live authority; materialization and safe-closeout each require a
fresh, separate explicit acknowledgement plus the backend's exact identity,
fill/terminal-state, Test-portfolio, wallet/cap, RBAC, idempotency, audit,
reconciliation, duplicate-prevention, and route-scope gates. No scheduler or
autonomous follow-up execution is installed. New UI work must use generated
contracts and backend read models.

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
