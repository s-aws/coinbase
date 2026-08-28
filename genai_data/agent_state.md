# Agent State

## Status

- Last updated (ET): 2026-08-28
- Active operator-approved objective: review the completed bounded
  default-PAUSED live validation and decide whether its passive evidence closes
  the current milestone or whether a separately approved stateful validation is
  warranted.
- Active implementation status: runtime changes are committed through
  `5a8d50b70` (`part 6`), and the context/graph baseline is committed as
  `9a85ee36a` (`part 7`). The bounded live validation is complete. No runtime
  correction was made as a result of the run; this evidence update is
  uncommitted pending operator review.

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
- Any further live validation remains PAUSED unless the operator separately
  authorizes resume; hydration, reconciliation, websocket ingress, and
  scheduler activation may be observed without originating new placements.
- The approved scheduler uses ordered market evidence plus deadlines derived
  from stored condition and anchor state. Perl-style distance-based or
  external-signal timing augmentation was not ported and is not implied future
  scope.

## Automated validation state

- Mandatory regression suite after the final source correction: 767 passed;
  rerun after this live-evidence/graph update: 767 passed.
- Focused scheduler/ticker suite after the final source correction: 108 passed.
- Focused authenticated routing audit: 78 passed; no remaining in-scope defect
  or lock-order inversion found.
- Python compilation and `git diff --check`: passed.
- Repository graph baseline build/check committed at `9a85ee36a`: 2,055 commits
  and 179 semantic records indexed with zero mismatches, fatal errors, or parse
  findings.
- Current live-evidence graph rebuild/check: 2,056 commits and 180 semantic
  records indexed with zero mismatches, fatal errors, or parse findings.
- Existing `server_log.txt` predates the committed scheduler/PATCH sequence and
  is not live-validation evidence for the current implementation.

## Bounded live validation (2026-08-28)

- Ran the committed engine against the isolated PostgreSQL clone on host port
  `9876` from approximately 11:04:42 through 11:08:43 ET with
  `ENGINE_START_PAUSED=true`. The engine completed hydration and reconciliation,
  activated the stealth deadline scheduler and periodic reconciler, then entered
  PAUSED with admission disabled and zero in-flight operations.
- Three public ticker websocket clients and one authenticated user websocket
  generation logged successful connections. The private generation remained
  connected beyond its bootstrap deadline with no logged desynchronization or
  reconnect; because the snapshot was empty, this is inferred bootstrap success
  rather than an explicit snapshot-success log.
- Two dashboard observation windows received 995 accepted ticker broadcasts.
  The instrumented 400-event window contained no repeated
  `(product_id, price, cb_time_ms)` keys and no per-product `cb_time_ms`
  regression. This validates accepted output in that window, not the absence of
  duplicate raw messages arriving from the redundant sockets.
- `market_tick` increased by 1,137 rows during the observation window, spanning
  all eight configured products. The seven monitored lifecycle tables began and
  ended at zero, so no run-attributable lifecycle row appeared; no placement or
  cancellation was observed, and the dashboard log probe observed no warning,
  error, or critical entries.
- One Ctrl+C produced an orderly `PAUSED -> DRAINING -> STOPPED` transition,
  stopped the stealth bridge and periodic reconciler, exited with code 0, and
  released dashboard port `8765`. The worktree and tracked `server_log.txt`
  remained unchanged by the runtime.

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
- The live clone had no active stealth row, so no condition hold, reveal,
  re-hide, anchor reprice, or exchange placement was exercised. Coinbase also
  emitted no live authenticated `PATCH` envelope, so canonical PATCH dispatch
  remains automated-test evidence rather than direct live evidence.
- PAUSED is an origin-admission boundary, not a read-only mode. Ticker
  persistence, reconciliation, authenticated fill/cancel handling, and scheduler
  condition/snapshot transitions can still write state. The hotpoint decay
  sweeper can also issue live REST cancellation calls for eligible persisted
  rows without RuntimeController admission. The empty clone had no candidate,
  but a future live test must preflight this independently rather than treating
  PAUSED as a universal no-side-effects guarantee.

## Next actions

- Inspect and commit this live-evidence context/graph diff after operator review.
- Decide whether to close the passive live-validation milestone or separately
  approve a controlled stateful test with an active stealth row and/or captured
  authenticated PATCH envelope. Do not seed state, resume trading, place, or
  cancel an order without that approval.

This file is intentionally short and branch-neutral. Confirm the current Git
branch and working tree at session start. Do not infer active work from chat
history, topical fix summaries, or files under `genai_data/history/`.

When an operator explicitly approves work that must survive a session handoff,
record only the objective, fixed constraints, in-scope files, verified facts,
open risks, validation state, and next actions here. Remove or archive that
state when the work is completed, reverted, or abandoned.
