# Agent State

## Status

- Last updated (ET): 2026-11-26.
- Repository baseline before the current uncommitted item-3 work: local `prod`
  and `origin/prod` are at `f88d1111`; that commit completed removal of the
  superseded `OrderInventory` and dormant `OrderStateHookRegistry` surfaces.
- Completed operator-approved objective: freeze all statically observable
  module dependency and broad capability debt without changing runtime wiring.
  `module_boundaries.toml` now classifies every supported runtime module and
  records exact reverse-zone imports, the current strongly connected import
  component, broad/untyped constructor capability surfaces, and reflection
  escape signatures. The regression contract rejects expansion or stale debt.
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
- The automation reuses `scripts/run_tests.sh`, `database.schema`, and
  `python -m main` rather than introduce parallel validation, schema, or engine
  paths.

## Completed Automation Checklist

1. `scripts/validate_release.sh` provides the clean-worktree complete-suite,
   graph, diff, and final-cleanliness release gate.
2. `scripts/bootstrap_runtime_database.sh` accepts no confirmation argument;
   it derives the target from all five required `COINBASE_DB_*` values and
   rejects unknown tables or trading rows while permitting candle/tick data.
3. `scripts/deploy_runtime.sh` serializes supported launchers, probes for an
   existing dashboard before and after validation, bootstraps the database,
   forces paused canonical startup, proves stable dashboard health, and owns
   the child in the foreground with graceful signal forwarding.
4. Regression coverage, living documentation, setup guidance, and curated and
   generated repository-graph records are updated. Destructive reset, resume,
   order activity, Git push, and daemonization remain manual or excluded.

## Completed Rollout Checklist

1. Track and commit `scripts/bootstrap_runtime_database.sh`: complete in the
   closeout change that contains this handoff.
2. Refresh the durable handoff: complete in this file.
3. Verify a fresh operator-prepared target read-only, run the guarded additive
   bootstrap, start the engine paused, and observe startup/reconciliation:
   complete against `127.0.0.1:5432/coinbase`.

## Modular Monolith Boundary Checklist

Items 1 through 3 are complete. Every later item requires a focused source/test
search, blast-radius evaluation, context discussion, and separate operator
approval before code changes.

1. Remove the abandoned `StateManager` and generic repository implementation:
   complete and validated; canonical product-type coverage is retained.
2. Remove the superseded `OrderInventory` authority model and dormant
   `OrderStateHookRegistry`; retain and accurately document best-effort stealth
   lifecycle auditing: complete and validated.
3. Declare and enforce the in-process module dependency map: complete and
   validated. The source-only contract freezes 43 reverse-zone import edges,
   one six-module strongly connected import component, 34 broad/untyped
   constructor capability surfaces, and eight reflection/namespace escape
   signatures. It explicitly does not claim to prove arbitrary runtime aliases
   or dynamic dispatch.
4. Make `main.py` the sole explicit composition root and make configuration
   imports passive: next; focused review and blast-radius discussion are
   required before implementation approval.
5. Add an Execution Core command/query facade while retaining lifecycle and
   transactional writes under one owner.
6. Extract public market-data ownership into an in-process component.
7. Separate operator WebSocket transport from application commands and read
   projections.
8. Isolate reconciliation and historical auditing behind injected readers and
   explicit repair commands.
9. Reassess process boundaries and durable messaging only after the in-process
   contracts and failure semantics are stable. This item must explicitly make
   every stealth lifecycle audit transition eventually durable through an
   atomic outbox/delivery design with idempotent replay and per-`client_order_id`
   ordering; current hook delivery remains best effort until then.

## Validation and Maintenance

- Full local non-external suite after the StateManager/repository removal: 1,927
  passed, 17 skipped, 11 external deselected, exit 0 on Python 3.14. Database
  success/failure cases use isolated per-test schemas and never clear the suite's
  shared state.
- Bash syntax for all deployment scripts and Python compilation for the schema
  and healthcheck modules: pass. Final diff check: pass.
- The clean-worktree release wrapper passed after the graph closeout at
  `8e8bd8ad`: 1,932 passed, 17 skipped, and 11 external tests deselected.
  Repository-graph validation reported zero parse findings, fatal errors, or
  mismatches, and the final worktree cleanliness check passed.
- Item-2 focused coverage passed 64 tests. The complete local non-external gate
  passed 1,874 tests with 17 skipped and 11 external tests deselected. The lower
  total reflects deletion of obsolete inventory/state-hook tests; retained
  stealth-audit and canonical product-resolution behavior remains covered.
- Item-3 changed no runtime behavior. Its first complete-suite run correctly
  exposed that two apparent subcycles were joined through the eager `external`
  package re-export; the reviewed baseline was corrected to one six-module
  strongly connected component. The final complete local non-external gate
  passed 1,878 tests with 17 skipped and 11 external tests deselected.
- Historical fresh-target proof at rollout time: all 12 trading tables contained
  zero rows before bootstrap; only `market_candle_1m` and `market_tick` retained
  operator-created telemetry/backfill data.
- Historical guarded additive bootstrap: pass; connected identity was database
  `coinbase`, user `postgres`, server `127.0.0.1:5432`, and all 12 required
  tables verified.
- Historical live startup: `STARTING -> PAUSED`; dashboard authority reported
  admission closed, no stop in progress, no pending startup pause, and zero
  in-flight work. Startup reconciliation found no exchange/DB order drift,
  parent/child hydration was empty and in sync, and authenticated user snapshots
  contained zero open orders. All 12 trading tables remained empty after startup.
- The missed-fill audit classified 148 recent REST fills across 106 orders as
  unowned pre-wipe/off-engine history, so it did not backfill them. This is not
  current local order state and will age out of the audit window.
- No production database bootstrap/deployment, destructive database command,
  order placement/cancellation, or delegated agent was used for this feature.
  The pre-existing engine session was left running and untouched; later runtime
  activity means its database must not be assumed fresh for a future launch.

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
derives the target solely from them. It verifies identity and fresh trading
state before schema work; duplicate target confirmation is intentionally
absent. `main.py` does not provision the full schema. Deployment forces
`ENGINE_START_PAUSED` until reconciliation and readiness evidence are reviewed.
The wrapper's lock serializes supported launchers and its repeated dashboard
probe narrows startup overlap, but it cannot fence a concurrent direct/manual
`python -m main` process or an independent database writer. Those bypasses
remain unsupported operational races.

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
   owner for every state mutation. Stealth lifecycle audit transitions are an
   explicit durability consumer; their current synchronous fail-soft callback
   path is accepted only as the interim best-effort implementation.
7. Prefer multiple processes or systems for independent scaling; Python threads
   remain suitable for I/O concurrency but are not the primary answer to
   CPU-bound scaling.
8. If an operator console is added, expose a restricted administrative command
   API. Do not add an unrestricted runtime REPL that can bypass lifecycle,
   locking, admission, or persistence boundaries.
