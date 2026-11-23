# Agent State

## Status

- Last updated (ET): 2026-11-23.
- Checkout baseline: `prod` at `fb6fb9a8`.
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
