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

Goal `operator_spot_automation_single_child_execution_adapter_v1` is complete.
Status: `complete`.
Current action: `complete_zero_candidate_all_live_allowances_unconsumed`.
Default action: `await_operator_direction_for_next_mvp`.

The Eight-category single-child adapter remains installed behind backend-owned
authority. Aggregate primary evidence: definitions `0`, plans `0`, runs `0`, eligibility cycles `0`, claims `0`, and candidates `0`.
State-refresh cycles consumed: `0/10`.
Coinbase Create calls: `0`; Coinbase Cancel calls: `0`.
All live allowances remain unconsumed.

Validation evidence: backend full `1179 passed, 6 skipped` parallel and `664 passed, 150 skipped` serial; focused backend `367 passed`; frontend full `1555 passed`; E2E `15/15`; focused frontend `177 passed`; independent safety audit `PASS`; blind-contextless audit `PASS`.
Release/deployment gate: `PASS` (canonical rerun complete).
No Coinbase API call or exchange mutation was made for this closeout. Every immutable
R1-R12 artifact byte and documented hash remains preserved, and R8 content and
hash remain inaccessible.

### Historical pre-closeout implementation checkpoint

Before terminal closeout, goal
`operator_spot_automation_single_child_execution_adapter_v1` was
at a canonical-single-child-execution-implemented, validation-pending
checkpoint. Durable PostgreSQL plan/run binding, a goal-global ten-cycle
ledger, the fixed no-retry Eight-category eligibility coordinator (including
the account-wide active Spot-order catalog), generated readback, and the
explicit operator refresh are implemented. Navigation remains call-free.

Exact-run authorization owns a separate final authorization refresh of the
same bound eight categories before its durable Create claim. The canonical
domain-owned one-child Create coordinator and the distinct
exact-child safe-closeout Cancel coordinator delegate through the existing
Spot command service with typed admission, RBAC, caps, idempotency,
reconciliation, and fixed sanitized call accounting. No bare enablement flag,
untyped gateway, alternate placement path, retry, scheduler, or fan-out was
added.

Historical checkpoint status was `canonical_single_child_execution_implemented_validation_pending`;
its action was
`complete_validation_audits_deployment_and_bounded_live_proof`. No goal-scoped
Coinbase call has run. Eligibility-cycle, final-authorization-read, Create, and
Cancel allowances remain unconsumed. Full validation, independent audits,
installed deployment validation, and the bounded live proof remained pending.
The previous source-gated checkpoint and its gate counts remain historical
evidence. See
[the adapter record](docs/OPERATOR_SPOT_AUTOMATION_SINGLE_CHILD_ADAPTER.md).

## Completed Automation control-plane predecessor

Historical status: `complete`.
Completed goal `operator_automation_control_plane_origin_prod_alignment_v1`
turned the routed Automation surface into an authenticated PostgreSQL-backed
operator workflow. Current action is
`complete_operator_automation_control_plane_origin_prod_alignment`; the
historical default was `await_operator_direction_for_next_mvp`. Definitions,
actor-scoped lifecycle and posture controls, review-only schedules, one-shot
local claims, restart recovery, pagination, and correlated definition/control/
run audit history are implemented through generated Admin API contracts.
Diagnostics remains separate.

Completed predecessor: Goal
`operator_core_workspaces_origin_prod_alignment_v1` is complete. Its historical
record has Status: `complete`. Its historical action is
`complete_core_operator_workspaces_origin_prod_alignment`; default action is
`await_operator_direction_for_next_mvp`. It delivered the persistent
authenticated operator shell and routed Portfolio, Spot Operations, Futures
Operations, Orders-detail, Automation, and System Operations workspaces while
keeping Diagnostics separate. Its historical Automation is GET-only posture is
superseded by the current goal; it remains evidence, not current authority.

The one authorized account-reality refresh completed and is consumed and
sealed; its evidence is stale for live eligibility and cannot be rerun under
this goal. No goal-scoped Create, Cancel, or live proof has run. The optional
Spot Create and exact-order Cancel allowances remain unconsumed. Futures is
source-disabled and call-free; its workspace exposes sanitized local evidence
only. Automation mutations from that predecessor are local PostgreSQL
control-plane operations and make zero Coinbase calls. Its domain adapters were
unavailable at closeout, so one-shot claims terminated `BLOCKED`; no Automation
live proof, Create, or Cancel ran and its goal-scoped live allowance remained
unconsumed. The installed successor is the separate `SOURCE_GATED` checkpoint
described above.

Historical core-workspaces validation evidence was backend full `1109 passed,
6 skipped` parallel and `599 passed, 150 skipped` serial, frontend full `1440
passed`, E2E `13 passed`, and independent safety audit `PASS`. The final blind
re-audit is not claimed as passed for that historical checkpoint.

Historical control-plane predecessor closeout evidence is backend full `1156 passed, 6 skipped` parallel and `609
passed, 150 skipped` serial, frontend full `1499 passed`, browser E2E `15/15`,
independent safety and blind-contextless audits `PASS`, and the canonical
release gate `PASS`. Packaged and installed validation includes a fresh real
Controlled-live entrypoint on an empty PostgreSQL database, durable Automation
readback, and zero Coinbase calls, Create calls, Cancel calls, or notional.

Historical predecessor
`operator_follow_up_operations_queue_and_single_live_proof` completed with
status `complete_zero_candidates`. The deployed passive local-SQL
Follow-up Operations workspace passed its focused/full, deployment, safety, and
blind-contextless gates. The exact post-gate local `materialization_review`
candidate count is `0`. The queue made no Coinbase read, Create, or Cancel call;
the goal-scoped proof claim was not created or required; and eligibility,
reconciliation, Create, and Cancel did not run. All live allowances remain
unconsumed, but that completed goal grants no continuing proof call. Keep the
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
