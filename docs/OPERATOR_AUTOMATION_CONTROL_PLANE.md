# Operator Automation Control Plane v1

## Goal

`operator_automation_control_plane_origin_prod_alignment_v1` adds a normal
authenticated operator workflow for durable automation definitions, schedules,
lifecycle controls, one-shot run claims, history, and audit readback.

The control plane is an orchestration primitive. It does not contain Spot or
Futures trading rules and it never calls Coinbase directly. A run may cross an
exchange boundary only through a separately ready domain adapter and the
canonical domain admission/execution coordinator.

The installed Admin API enables this surface only when
`COINBASE_ADMIN_API_OPERATOR_AUTOMATION_ENABLED=1` is present exactly. Startup
creates the additive PostgreSQL schema, performs deterministic run recovery,
and only then binds the server. It fails closed with a fixed diagnostic if
schema initialization or recovery cannot complete.

## V1 scope

The backend owns:

- PostgreSQL definition, control-posture, run, event, audit, and idempotency
  records;
- typed domain and job-kind validation;
- state transitions, pagination, filters, schedules, due-state calculation,
  claims, restart recovery, and duplicate prevention;
- the current approved Spot product scope for definition classification, plus
  RBAC, local actionability, audit, and fixed diagnostics;
- exact `client_order_id` linkage fields reserved for a future domain adapter.

The control plane does not claim current portfolio, wallet, inventory, cap,
order-admission, exchange-call, or reconciliation evidence. Before any future
run can cross a domain boundary, its typed backend adapter must independently
revalidate those rules through the owning Spot or Orders service and persist
exact child linkage. The adapter cannot inherit authority from definition
metadata or browser confirmation.

The browser displays generated backend contracts and forwards explicit
operator requests. It does not calculate products, sizes, prices, caps,
schedule eligibility, retry timing, or next-run timing.

Spot definitions must bind at least one product and may contain only the shared
backend-approved normal Spot scope (`BTC-USDC` in the current policy).
Follow-up definitions carry no product scope. Persisted out-of-policy Spot
metadata fails closed on readback and cannot become adapter authority.

V1 job kinds are classifications, not generic executable payloads:

| Kind | Domain owner | V1 execution posture |
| --- | --- | --- |
| Spot campaign | Spot backend | definition/control-plane ready; domain execution adapter unavailable |
| Spot sweep | Spot backend | definition/control-plane ready; domain execution adapter unavailable |
| Spot ladder | Spot backend | definition/control-plane ready; typed planner unavailable |
| Follow-up | Existing Orders/follow-up backend | definition/control-plane ready; operator must use existing attach/materialize controls |

Futures automation is not modeled in v1. Spot policy must never be copied into
a future Futures adapter.

## Routes

Read routes:

- `GET /api/v1/automation/control-plane`
- `GET /api/v1/automation/control-plane/events`
- `GET /api/v1/automation/definitions`
- `GET /api/v1/automation/definitions/{definition_id}`
- `GET /api/v1/automation/definitions/{definition_id}/events`
- `GET /api/v1/automation/runs`
- `GET /api/v1/automation/runs/{run_id}`
- `GET /api/v1/automation/runs/{run_id}/events`

Local control-plane mutations:

- `POST /api/v1/automation/definitions`
- `POST /api/v1/automation/definitions/{definition_id}/enable`
- `POST /api/v1/automation/definitions/{definition_id}/disable`
- `POST /api/v1/automation/definitions/{definition_id}/pause`
- `POST /api/v1/automation/definitions/{definition_id}/resume`
- `POST /api/v1/automation/definitions/{definition_id}/drain`
- `POST /api/v1/automation/definitions/{definition_id}/schedule`
- `POST /api/v1/automation/definitions/{definition_id}/schedule/clear`
- `POST /api/v1/automation/control-plane/pause`
- `POST /api/v1/automation/control-plane/resume`
- `POST /api/v1/automation/control-plane/drain`
- `POST /api/v1/automation/control-plane/shutdown`

Explicit one-shot run claim:

- `POST /api/v1/automation/definitions/{definition_id}/runs`

Every mutation requires authenticated backend RBAC, `Idempotency-Key`,
`X-Correlation-Id`, and `X-Operator-Intent`. Exact replay returns the original
claim result or the newer durable terminal restart result for an interrupted
claim; it never re-transitions a recovered run. Payload or actor drift
conflicts. `automation:read` owns reads, `automation:configure` owns definition
changes, `automation:trigger` owns one-shot claims, `automation:control` owns
stop-side posture changes, and the narrower `automation:resume` permission
owns global resume. Emergency actors can stop admission but cannot resume it.
Public `allowed_actions` and `definition_create_allowed` are scoped by the
authenticated actor in the backend.

## State machines

Control posture:

```text
ACTIVE -> PAUSED|DRAINING|SHUTDOWN
PAUSED -> ACTIVE|DRAINING|SHUTDOWN
DRAINING -> ACTIVE|SHUTDOWN
SHUTDOWN -> ACTIVE only through explicit resume
```

Definition lifecycle:

```text
DRAFT -> ENABLED|DISABLED
ENABLED -> PAUSED|DRAINING|DISABLED
PAUSED -> ENABLED|DRAINING|DISABLED
DRAINING -> ENABLED|DISABLED
DISABLED -> ENABLED
```

Run lifecycle reserves states needed for a future domain adapter:

```text
CLAIMED -> PREPARING -> AWAITING_OPERATOR_AUTHORIZATION
        -> BLOCKED|ABORTED
AWAITING_OPERATOR_AUTHORIZATION -> INVOCATION_STARTED
INVOCATION_STARTED -> ACTIVE|TERMINAL|UNKNOWN_CONSUMED
ACTIVE -> TERMINAL|UNKNOWN_CONSUMED
```

V1 finalizes a one-shot run as `BLOCKED` when its typed domain adapter is not
ready. It does not reinterpret that result as a live attempt. A process loss
before invocation is terminally classified `BLOCKED` with
`restart_pre_invocation_blocked`, freeing the definition without retrying the
claim. Any state at or after `INVOCATION_STARTED` is quarantined as
`UNKNOWN_CONSUMED` and is never retried automatically. Exact replay after
either recovery returns the durable current terminal evidence and does not
attempt a second transition.

## PostgreSQL durability

The schema is additive and versioned without introducing a competing migration
framework:

- `automation_control_plane_state`
- `automation_definition`
- `automation_idempotency`
- `automation_run`
- `automation_event_outbox`

Mutations use short transactions, row/advisory locks, typed constraints, and
append-only event evidence. Raw idempotency keys and actor identifiers are
hashed before persistence. Exchange identifiers are not stored. Exact child
linkage through `client_order_id` is reserved in the contract but remains null
while every v1 domain adapter is unavailable.

Legacy automation JSONL files are not imported, rewritten, deleted, or treated
as live authority. They remain compatibility/diagnostic evidence. Rollback
disables the new routes/runtime and leaves inert additive tables in place.

The application layer adapts these records into the strict public Admin API
models. Database records and persistence command types never become browser
contracts, and the route layer cannot pass a generic executor payload into the
repository.

Definition, global-control, and run event routes expose backend-paginated,
append-only transition evidence with fixed diagnostics plus audit and
correlation identifiers. Raw actor values, idempotency keys, responses,
exceptions, and exchange identifiers are never exposed.

## Scheduling and live boundaries

Definitions may store `MANUAL_ONLY` or `INTERVAL_REVIEW_ONLY` schedules. The
backend calculates due posture. V1 starts no recurring worker and performs no
automatic POST, Create, Cancel, fan-out, or fill-trigger action.

The separately authorized optional proof can proceed only if a typed Spot
domain adapter, exact eligible definition, all backend gates, and a durable
single-use proof claim exist. Otherwise all proof allowances remain
unconsumed.

## Historical source comparison

Reviewed source material from `origin/prod`:

- `dashboard_server.py` for pause/resume/drain and kill-switch semantics;
- `core/order_engine.py` for legacy in-memory workers and automatic follow-ups;
- `business/hotpoint_rate_limiter.py`, `business/hotpoint_placer.py`, and
  `business/hotpoint_decay_sweeper.py` for acquire/commit/rollback and
  restart-hydration ideas;
- `business/move_manager.py` and `database/order.py` for pending-move history.

Direct WebSocket authority, daemon-side REST calls, generic JSON executor
payloads, automatic fill actions, movement/repricing, and in-memory-only claims
are not copied into the Admin MVP.
