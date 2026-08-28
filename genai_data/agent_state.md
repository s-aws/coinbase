# Agent State

## Status

- Last updated (ET): 2026-08-28
- Active operator-approved objective: correct the authenticated Coinbase user
  websocket path without changing pricing, fees, database ownership, dashboard
  readiness, or public market-data behavior.
- Active implementation plan: implemented but uncommitted; awaiting operator
  review/commit.

## Fixed design constraints

- Keep redundant public `WSClient` connections for ticker/heartbeat and exactly
  one authenticated `WSUserClient` connection for `user`, futures balance, and
  heartbeat payloads.
- Reduce authenticated envelopes in connection-global sequence order on one
  private reducer queue. Preserve row lifecycle status independently from wire
  kinds (`snapshot`, `update`, `patch`).
- Bootstrap paginated order snapshots without database, fill-accounting, or
  follow-up side effects. Admit live order rows atomically to bounded FIFO lanes
  keyed by `client_order_id`.
- Fail closed and reconnect on sequence corruption, malformed payloads,
  dispatcher rejection/overflow, or snapshot timeout. Ignore stale generations.
- `EXPIRED` receives terminal cleanup only; do not route it through filled or
  cancelled replacement behavior.

## Validation state

- Mandatory regression suite: 765 passed.
- Complete `tests/` suite: 1537 passed, 3 skipped.
- Focused authenticated routing audit: 78 passed; no remaining in-scope defect
  or lock-order inversion found.
- Python compilation and `git diff --check`: passed.
- Repository graph build/check: passed with zero fatal or parse findings.

## Open boundary

- Existing snapshot hydration does not evict a local OPEN row absent from a
  completed Coinbase snapshot, returns early for an empty snapshot, and leaves
  same-status quantity differences untouched. This was not changed because it
  is a separate reconciliation/database-correction design decision.
- Perpetual-position rows use a different field schema from expiring futures;
  the existing position snapshot handler catches/logs that mismatch and drops
  the perpetual update while order processing remains isolated. Supporting
  that schema requires a separate position-model correction.

## Next actions

- Inspect the final diff and leave the implementation uncommitted for operator
  review.

This file is intentionally short and branch-neutral. Confirm the current Git
branch and working tree at session start. Do not infer active work from chat
history, topical fix summaries, or files under `genai_data/history/`.

When an operator explicitly approves work that must survive a session handoff,
record only the objective, fixed constraints, in-scope files, verified facts,
open risks, validation state, and next actions here. Remove or archive that
state when the work is completed, reverted, or abandoned.
