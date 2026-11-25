# Agent State

## Status

- Last updated (ET): 2026-11-23.
- Checkout baseline: `prod` at `0c0f7307`.
- Active operator-approved objective: none.
- Completed objective: extracted authenticated private-feed generation,
  sequencing, reduction, bounded per-order dispatch, and operational metrics
  into the instance-owned `core/user_feed_processor.py`. `OrderEngine` retains
  thin compatibility delegates and remains the owner of trading policy and
  order lifecycle behavior. The operator also approved the accompanying
  `products.json` rollover in the same implementation commit.
- Retention policy: current documentation and handoff only; remove superseded
  material instead of archiving it.
- Order lifecycle behavior is intended to remain unchanged. Dashboard
  `engine_status` now includes the nested `user_feed` metrics snapshot, and the
  configured derivative product catalog was refreshed.

## Validation and Maintenance

- Full local non-external suite: 1,869 passed, 17 skipped, 11 deselected,
  exit 0 on Python 3.14.8 via `.venv/bin/python3.14`.
- Exchange-free cancellation-pipeline stress: pass; 300 measured
  cancellations, zero dispatcher residue, zero resource-limit violations.
- Exchange-free user recovery stress: pass; 100 reconnect cycles, 100 stale
  messages dropped, zero generation/dispatcher residue, zero resource-limit
  violations.
- `git diff --check`: pass.
- Graph evidence uses current source and current documentation only. Rebuild
  and run `build_graph.py --check` after editing this file or other sources.
- No external tests, live engine, exchange mutations, or delegated agents were
  run. No open subagent handoff remains.

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
