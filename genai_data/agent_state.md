# Agent State

## Status

- Last updated (ET): 2026-08-28.
- Checkout baseline: `prod` at `49db0fb73f` (`part 11`).
- Active operator-approved objective: simplify the committed `part 11` test
  expansion while preserving its production correction. The working tree
  changes only tests and authoritative agent context; production code remains
  untouched. The separate cancellation/parent-truth correction remains out of
  scope.
- Implementation is committed through `5a8d50b70` (`part 6`), the initial graph
  baseline through `9a85ee36a` (`part 7`), the earlier live-evidence context at
  `814167fb0` (`part 8`), and the deterministic full-suite gate at `41d4e3c33`
  (`part 9`). `0a364e27f3` (`part 10`) commits the corrected guarded evidence and
  the two approved read-only correction audits. `49db0fb73f` (`part 11`)
  commits the minimal admission-retry ownership correction and its original
  expanded test coverage.

## Fixed design constraints

- Keep redundant public `WSClient` connections for ticker/heartbeat and exactly
  one authenticated `WSUserClient` connection for user, futures-balance, and
  private-heartbeat payloads.
- Reduce authenticated envelopes in connection-global sequence order on one
  private reducer queue. Keep wire kinds (`snapshot`, `update`, `patch`)
  separate from row lifecycle statuses.
- Bootstrap paginated order snapshots without database, fill-accounting, or
  follow-up side effects. Admit live order rows atomically to bounded FIFO lanes
  keyed by `client_order_id`.
- Fail closed and reconnect on sequence corruption, malformed known payloads,
  dispatcher rejection/overflow, or snapshot timeout. Ignore stale generations.
- `EXPIRED` receives terminal cleanup only; it is not a fill/cancel replacement
  trigger.
- Live validation remains PAUSED unless the operator explicitly authorizes
  resume. PAUSED is an origination-admission boundary, not database read-only.
- Scheduler decisions use ordered market evidence plus deadlines derived from
  durable condition/anchor state. Perl distance/external-signal timing was not
  ported and is not implied future scope.

## Automated validation

- Complete local non-external suite: 1,544 passed, 11 external tests deselected
  for the current working tree (47.43 seconds).
- No focused test selection was run. Focused test files, name filters, or
  individual cases now require an explicit user request.
- Pytest gate now rejects unknown config, reports warnings, treats unhandled
  thread exceptions as errors, and has a deterministic scheduler concurrency
  test (`part 9`).
- Current repository graph build: 2,060 commits, 37,464 edges, 507 files, and
  183 semantic records, with zero fatal/history/parse findings. The final
  `--check` must remain clean at handoff.
- The ordinary port-9876 `coinbase_engine` test database is not a clean live
  fixture: the full suite left 933 parent rows, 40 HIDDEN stealth rows, and 48
  pending move rows. Stateful live validation therefore used a new schema-only
  database instead.

## Correction to the part-8 passive live evidence

- The earlier commands used Bash inline `COINBASE_DB_*` assignments before a
  Windows Python executable. In this WSL/Windows environment those variables do
  not cross that process boundary. A reproduction showed the Windows process
  received no port override and retained database `coinbase_engine`; archived
  probes also resolved the nominal 9876 and 5432 runs to server port 5432.
- Therefore the part-8 claim that its four-minute passive run targeted the
  port-9876 clone is not accepted. Its general runtime observations may be
  informative, but they are not isolated-9876/database evidence and must not be
  cited as such.
- While correcting the launch method, one synthetic HIDDEN stealth row and its
  PENDING parent were accidentally written to the host-5432 `coinbase_engine`.
  The engine was stopped, the row had no exchange pointer or dependent records,
  and exactly those two marker-matched synthetic rows were permanently deleted
  in one validated transaction. Post-delete counts for that identifier were
  zero. No user row or exchange order was touched.
- Correct Windows launches must originate in PowerShell with `$env:` variables,
  then prove `PostgresDB().port`, `PostgresDB().database`, `current_database()`,
  and the container-side `inet_server_port()` before any stateful work.

## Guarded active-row live validation (2026-08-28)

- Created schema-only database `coinbase_validation_part9` in
  `coinbase-test-postgres` (`127.0.0.1:9876 -> container 5432`). An in-process
  identity gate proved configured host port 9876, database
  `coinbase_validation_part9`, and server-side port 5432 before seeding and on
  every observer/audit process.
- Seeded exactly one canonical BIP-20DEC30-CDE BUY through
  `StealthOrderManager.create_stealth_order`: size 1, tick-valid limit 5,
  price-below threshold 1,000,000,000, continuous hold 5 seconds, fixed sizing,
  configured-limit pricing, zero replacements/movement, and anchor/hotpoint/
  partial-fill behavior disabled. Preflight proved zero other stealth/parent
  rows, zero active exchange pointers, and zero hotpoint-cancel candidates.
- The validation process monkeypatched all five `CoinbaseRestClient` mutation
  methods and all non-GET Coinbase SDK transport requests to record and raise.
  Static inspection found no current production mutation path outside that
  boundary. Final count: zero attempted REST mutations.
- Engine startup completed with `ENGINE_START_PAUSED=true`. Two independent
  dashboard status samples proved `PAUSED`, `is_admitting=false`,
  `is_stopping=false`, and `total_inflight=0` before and after trigger commit.
- Ordered ticker evidence persisted `HIDDEN -> PENDING` at
  2026-08-28 16:44:06.675810 UTC and `PENDING -> TRIGGERED` at
  16:44:11.845914 UTC (5.170104 seconds). The observer received three ticker
  broadcasts. The next Coinbase event timestamp crossed the hold deadline
  before the derived local monotonic wake fired, so it correctly invalidated
  that disposable wake and committed TRIGGERED; a timer alone would not have
  proved continuous market truth.
- The row stayed unexposed: revealed/executed size zero, remaining size one,
  empty `revealed_orders`, no active placement/exchange pointer, no reveal
  history, no child row, and no submission event. Event-stream evidence was
  limited to `stealth_condition_watching` and `stealth_condition_met`.
- After proving no exchange pointer, dashboard cancellation changed only the
  validation stealth row to CANCELLED. Dashboard shutdown was accepted from
  PAUSED; the process reached STOPPED with zero in-flight work and released
  port 8765. No traceback, ERROR, or CRITICAL record appeared in captured
  process output.

## Measured pre-correction boundary from the stateful run

- A TRIGGERED row deferred by PAUSED is not quiescent. In roughly 45 seconds,
  one row produced 844 `ADMISSION_RETRY` schedules and 421 delivered wakes at
  the 100 ms retry constant. It also repeatedly invalidated every condition
  generation. Pre-correction bridge control flow scheduled once in
  `_evaluate_scheduled_order_locked` and again in `_handle_deadline_wake`, so
  one delivered retry creates two replacement generations.
- This did not bypass admission or call Coinbase, but it was avoidable scheduler
  and lock churn that scaled linearly with paused TRIGGERED rows and amplified
  debug/log noise. The current working-tree correction addresses exactly this
  measured boundary.

## Approved admission-retry correction (working tree)

- `RuntimeController` now owns named, insertion-ordered admission-open hooks.
  Actual `STARTING -> RUNNING` and `PAUSED -> RUNNING` transitions notify a
  snapshot outside controller locks; registration while already RUNNING is
  level-triggered. Shutdown rejects registration, stop can unregister, one
  callback cannot block the state lock, and generic callback failures are
  isolated and logged.
- `StealthOrderBridge` registers its hook only after the sole scheduler worker
  is live and decision readiness is published, then clears readiness and
  unregisters before stop cleanup. Opening admission scans authoritative local
  active rows and schedules exactly one zero-delay `ADMISSION_RETRY` for each
  positive-remaining TRIGGERED row. It never reveals, writes the database, or
  calls REST from the hook.
- A TRIGGERED row schedules no admission retry while runtime admission is
  closed. A wake already captured when pause wins may drain once, but cannot
  rearm. On a real admission-open transition the zero-delay wake replaces any
  older generation.
- The manager callback, evaluator fallback, and deadline-handler fallback use
  scheduler generations as one ownership fence. A synchronous manager rebuild
  suppresses both fallbacks; an evaluator rebuild suppresses the outer
  fallback; only an otherwise-unowned or failed evaluation receives one normal
  100 ms successor. Active RUNNING cadence remains 100 ms.
- Admission-open schedule reconstruction failure is fail-closed: decision
  readiness clears, the scheduler stops, and runtime returns to PAUSED. The
  scheduler implementation, condition semantics, placement path, database
  state, REST behavior, and cancellation semantics are unchanged.
- This correction has deterministic automated proof but has not been exercised
  by a new live resume/order-placement run. The earlier guarded run remains the
  live evidence for the original symptom only.

## Still-open cancellation/parent-truth boundary

- Direct cancellation left the paired root `order_parent` row PENDING while the
  stealth row became CANCELLED. The read-only audit confirmed that pre-reveal
  divergence is intentional, but this terminal divergence is not: direct
  `cancel_stealth_order` updates only the stealth row, skips the existing
  CANCELLED lifecycle event, ignores stealth persistence failure, and the
  dashboard reports success without checking its boolean result. Startup
  reconciliation deliberately excludes the stale PENDING parent, so it will not
  heal the mismatch. Hydration and scheduling still exclude the CANCELLED
  stealth row, making the observed execution risk low but leaving durable
  parent/audit truth wrong.
- Any cancellation correction must distinguish a proven pre-reveal order from a
  revealed order. Revealed-order REST cancellation is currently best-effort;
  terminalizing its parent without exchange confirmation could conceal a live
  Coinbase order. The safe minimal boundary is the same-SID pre-reveal parent,
  the existing CANCELLED lifecycle event, honest persistence/result handling,
  and a dashboard response that honors failure.

## Other open boundaries

- Existing authenticated snapshot hydration reports but does not evict a local
  OPEN row absent from a completed Coinbase snapshot, returns early for an
  empty snapshot, and leaves same-status quantity differences untouched.
- Coinbase emitted no authenticated live order/PATCH envelope during the
  bounded runs. Canonical PATCH dispatch remains automated-test evidence.
- Perpetual-position rows use a different field schema from expiring futures;
  existing position handling logs/drops that mismatch while order processing
  remains isolated.
- Fully revealed anchor repricing still conflates hidden `remaining_size` with
  venue exposure. Cumulative-volume evaluation still has ticker-field and
  evaluator-lifetime mismatches. These are separately indexed hazards.
- External tests remain deselected. Their configured sandbox URL does not yet
  prove that every SDK call is sandbox-routed, so running them is not authorized
  by the local full-suite result.

## Next actions

1. Review and commit the admission-retry correction as one isolated boundary.
2. Do not begin the cancellation/parent-truth correction until the scheduler
   boundary is committed and the operator explicitly continues that phase.
3. Any new live resume or exchange-order validation still requires explicit
   operator authorization and its own guarded procedure.

This file is branch-scoped context, not a substitute for current code and test
evidence. Confirm branch, HEAD, and worktree at session entry.

## Minimal pricing-persistence and cancellation-cap correction (2026-08-29)

- The approved scope corrected two pre-existing defects only. It did not alter
  dashboard/UI payloads, websocket topology, scheduler cadence, fee behavior,
  follow-up direction persistence, generic parent terminal projection, or the
  initial placement counter model.
- `stealth_orders.reveal_pricing_policy` is now a first-class non-null column
  with the fail-safe default `configured_limit`. The existing creation path
  normalizes the value once, insert/update persistence uses that same
  normalization boundary, and both startup and lazy hydration restore it.
  `top_of_book` therefore survives a manager/process restart and rebuilds a
  post-only reveal plan. Existing rows are not inferred or backfilled; rows
  without historical policy truth retain `configured_limit` by design.
- Normal cancellation follow-ups now claim one slot through the existing
  atomic root replacement-cap gate immediately before creation. Cancellation
  truth is recorded before a cap-denied return. A denied claim creates no
  child; a creator `None` result or exception releases the pending slot; and a
  successful child registration consumes the claim against the same canonical
  root. Pending-move, duplicate, non-stealth, filled, and partial-fill branches
  were not changed.
- Regression coverage proves additive schema creation/migration, normalized
  insert and presence-guarded update behavior, startup and lazy hydration,
  post-only plan reconstruction, legacy safe fallback, cap exhaustion, and
  slot release for both `None` and exception outcomes.
- Required automated gate passed on Windows Python 3.13.2: 1,551 passed,
  11 deselected, 0 failed in 44.92 seconds using the complete non-external
  suite. No focused selection was used.
- Repository graph rebuild/check passed with 2,061 commits, 37,546 edges,
  507 files, 183 semantic records, and zero fatal/history/parse findings;
  deterministic check reported `mismatches=[]` before this context update.

## Live validation boundary for this correction

- The approved fresh-schema port-9876 exchange canary has not run. Preflight
  found an existing Windows `-m main` engine owning dashboard port 8765,
  connected to host PostgreSQL port 5432 and Coinbase. Launching a second
  authenticated user websocket risks the repository's documented duplicate
  private-subscription conflict; routing the canary through the existing
  process would violate the approved database-isolation boundary.
- No exchange mutation and no canary database/schema mutation was performed.
  The safe next step is operator-coordinated shutdown of the existing engine,
  followed by the already approved fresh-schema 9876 restart/hydration,
  one-order post-only placement, exact-order cancellation, zero-follow-up,
  zero-fill/fee/position-delta canary. A REST-confirmed/manual-event hybrid is
  a materially weaker procedure and requires explicit approval because it
  would deviate from the approved authenticated-websocket plan.

## Stealth-manager resume control (2026-08-29)

- `create_stealth_order` is originating work, so the dashboard admission gate
  rejects it before the stealth handler, manager, or database whenever runtime
  state is not RUNNING. This explains the observed UI submission that never
  reached the engine while startup-default pause was active.
- `ui_stealth_orders_manager.html` now displays the authoritative engine state
  and uses the existing `admin_status` / `admin_resume` websocket protocol.
  Resume is enabled only while the socket is open and the exact state is
  PAUSED; STARTING, RUNNING, DRAINING, STOPPED, unknown, and disconnected
  states remain fail-closed. The operator must confirm that resuming enables
  new order placement, and an in-flight request disables duplicate clicks.
- No backend lifecycle, startup-default, stealth creation, persistence,
  scheduling, or placement behavior changed. The page's pre-existing lack of
  a dedicated `admission_rejected` toast remains out of this minimal change.
- Complete non-external suite passed after the UI change: 1,552 passed,
  11 deselected, 0 failed in 45.62 seconds. One static UI contract verifies
  exact-PAUSED gating and canonical admin message wiring; no focused pytest
  command was run.
