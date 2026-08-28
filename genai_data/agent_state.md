# Agent State

## Status

- Last updated (ET): 2026-08-28
- Active operator-approved objective: establish a current repository-graph
  baseline, then perform bounded default-PAUSED live validation of the committed
  Perl-inspired stealth scheduler, redundant public ticker handling, and
  authenticated Coinbase user websocket path.
- Active implementation status: runtime changes are committed through
  `5a8d50b70` (`part 6`), and the repository graph now snapshots that commit.
  Post-`part 6` live validation has not run. This context/graph baseline update
  is uncommitted pending operator review.

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
- Startup remains PAUSED throughout the bounded validation unless the operator
  separately authorizes resume; hydration, reconciliation, websocket ingress,
  and scheduler activation are observed without originating new placements.
- The approved scheduler uses ordered market evidence plus deadlines derived
  from stored condition and anchor state. Perl-style distance-based or
  external-signal timing augmentation was not ported and is not implied future
  scope.

## Automated validation state

- Mandatory regression suite after the final source correction: 767 passed.
- Focused scheduler/ticker suite after the final source correction: 108 passed.
- Focused authenticated routing audit: 78 passed; no remaining in-scope defect
  or lock-order inversion found.
- Python compilation and `git diff --check`: passed.
- Repository graph baseline build/check at `5a8d50b70`: 2,055 commits and 179
  semantic records indexed with zero mismatches, fatal errors, or parse findings.
- Existing `server_log.txt` predates the committed scheduler/PATCH sequence and
  is not live-validation evidence for the current implementation.

## Open boundary

- Existing snapshot hydration does not evict a local OPEN row absent from a
  completed Coinbase snapshot, returns early for an empty snapshot, and leaves
  same-status quantity differences untouched. This was not changed because it
  is a separate reconciliation/database-correction design decision.
- Perpetual-position rows use a different field schema from expiring futures;
  the existing position snapshot handler catches/logs that mismatch and drops
  the perpetual update while order processing remains isolated. Supporting
  that schema requires a separate position-model correction.
- Fully revealed anchor repricing still conflates unexposed `remaining_size`
  with live venue exposure, and cumulative-volume evaluation has a ticker-field
  and evaluator-lifetime mismatch. Both are separately recorded graph hazards,
  not unfinished scheduler phases.

## Next actions

- Inspect and commit the context/graph baseline diff after operator review.
- Run one bounded default-PAUSED live validation. If clean, close the approved
  scheduler milestone; any adjacent correction requires separate approval.

This file is intentionally short and branch-neutral. Confirm the current Git
branch and working tree at session start. Do not infer active work from chat
history, topical fix summaries, or files under `genai_data/history/`.

When an operator explicitly approves work that must survive a session handoff,
record only the objective, fixed constraints, in-scope files, verified facts,
open risks, validation state, and next actions here. Remove or archive that
state when the work is completed, reverted, or abandoned.
