# Agent State

## Status

- Last updated (ET): 2026-11-26.
- Objective baseline: `prod` and `origin/prod` at ownership commit `4651848d`.
- Active operator-approved objective: close the runtime-database rollout by
  tracking the guarded bootstrap entry point, refreshing this handoff, and
  deploying only to an operator-prepared fresh database before observing a
  paused startup and reconciliation cycle.
- Completed implementation sequence: follow-up reveal-direction persistence,
  parent/child strategy authority, percentage-relative follow-up threshold
  inversion, programmatic span consistency, deterministic span planning, and
  durable execution-ownership status projection are committed through
  `4651848d`.
- Retention policy: current documentation and handoff only; remove superseded
  material instead of archiving it.
- Deployment boundary: `__dangerous_delete_all_tables__.py` is an operator-only
  development/reset utility and is never a deployment command. Deployment will
  not run over an existing instance; it uses the guarded additive bootstrap on
  a fresh database explicitly prepared by the operator.
- After rollout closeout, the next feature to raise for review is automation of
  `tests/DEPLOYMENT_CHECKLIST.md`. No automation implementation is approved yet.

## Active Checklist

1. Track and commit `scripts/bootstrap_runtime_database.sh`: complete in the
   closeout change that contains this handoff.
2. Refresh the durable handoff: complete in this file.
3. Verify a fresh operator-prepared target read-only, run the guarded additive
   bootstrap, start the engine paused, and observe startup/reconciliation:
   pending operator preparation and live execution evidence.

## Validation and Maintenance

- Full local non-external suite for the ownership/schema worktree, including
  the bootstrap script: 1,919 passed, 17 skipped, 11 deselected, exit 0 on
  Python 3.14.
- Bootstrap shell syntax validation: pass.
- Repository graph check before this handoff refresh: pass with zero fatal
  errors and zero mismatches; rebuild and recheck before committing.
- No external tests, live engine, exchange mutations, destructive database
  command, or delegated agent was used for this rollout closeout.
- Remaining required checks: read-only proof that the chosen deployment target
  is fresh, guarded schema bootstrap, paused startup/reconciliation observation,
  final graph check, and final worktree review.

## Local Environment

- `.venv/bin/python3.14` is the supported project interpreter. Setup,
  validation, stress launchers, and documented commands use that explicit
  path; the local generic virtual-environment links target the same binary.
- The installed PostgreSQL package exposes a broken `/usr/bin/pg_config`
  symlink. The validated Python 3.14 environment uses `psycopg2-binary`; no
  tracked dependency declaration was changed.

## Runtime Boundaries

Current boundaries are documented in `ARCHITECTURE.md` and graph hazards:
pre-reveal parent projection after a logical stop, direct dashboard admission
races, legacy direct cancel evidence, compatibility volume evaluation, and
single-placement zero-fill rearm limits. External-test sandbox settings do not
establish SDK endpoint routing. Behavioral fixes or live validation require a
separate operator-approved objective.

The guarded bootstrap requires all five explicit `COINBASE_DB_*` variables and
an exact `HOST:PORT/DATABASE` confirmation. `main.py` does not provision the
full schema. A live start must keep `ENGINE_START_PAUSED` enabled until startup
reconciliation and readiness evidence have been reviewed.

## Durable Architecture Recommendation

Status: operator-approved architectural direction, not an active implementation
objective. Future work still requires explicit operator approval and must preserve
the existing lifecycle and identifier invariants.

1. Evolve the current process into a modular monolith before creating networked
   microservices. Each component must have one instance-owned state boundary,
   an explicit interface, bounded queues, backpressure, and operational metrics.
2. Keep `OrderEngine` as the sole authoritative order-lifecycle host while
   boundaries are extracted. `UserFeedProcessor` is the first completed example:
   it owns authenticated-feed sequencing and dispatch, but calls the engine for
   trading policy and lifecycle mutation.
3. Use `client_order_id` as the internal partitioning, FIFO-ordering, and
   idempotency key. Use exchange `order_id` only at exchange-facing boundaries.
4. Extract deployment units only after their in-process interfaces and failure
   semantics are stable. Preferred candidates, in order, are:
   - public market-data ingestion;
   - dashboard publication and the operator UI gateway;
   - reconciliation and historical auditing;
   - strategy evaluation workers partitioned by product;
   - authenticated user-feed processing only after durable ordered messaging is
     available.
5. Initially keep order placement/cancellation, parent-child lifecycle, fill
   accounting, stealth lifecycle truth, and their transactional database writes
   together under one authoritative owner. Splitting these prematurely creates
   duplicate-order and distributed-consistency risk.
6. Before any process split, provide a durable event bus or transactional outbox,
   bounded consumers, dead-letter handling, replay-safe/idempotent handlers,
   per-`client_order_id` ordering, queue-depth/health telemetry, and one declared
   owner for every state mutation.
7. Prefer multiple processes or systems for independent scaling; Python threads
   remain suitable for I/O concurrency but are not the primary answer to
   CPU-bound scaling.
8. If an operator console is added, expose a restricted administrative command
   API. Do not add an unrestricted runtime REPL that can bypass lifecycle,
   locking, admission, or persistence boundaries.
