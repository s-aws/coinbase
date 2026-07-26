# Operator Spot Recovery Execution UI V1

Goal: `operator_spot_recovery_execution_ui_v1`

This is independent Goal 6 of the authorized operator UI sequence. It turns
the existing Spot recovery backend capability into a normal authenticated
operator workflow without reopening or borrowing authority from
`operator_spot_recovery_and_reconciliation_execution_v1`.

## Operator workflow

The routed Admin UI at `/spot/recovery` lets an authenticated operator:

1. create one recovery case for an exact system-owned `client_order_id`;
2. explicitly authorize one no-retry exact-order and fill refresh;
3. review the immutable backend recovery plan and fixed diagnostic;
4. supply an explicit reason and apply one backend-authorized PostgreSQL
   status repair;
5. supply an explicit reason and roll back that exact terminal-state repair
   while the stored snapshot still matches;
6. when authoritative reconciliation proves an exact active orphan with zero
   fills, enter the canonical exact-`client_order_id` Cancel workflow.

The browser renders generated contracts and forwards explicit intent. It does
not choose a portfolio, product, status transition, recovery plan, exchange
identity, retry policy, or Cancel eligibility.

## Independent successor ledger

`operator_spot_recovery_goal` owns the Goal 6 refresh and Cancel authority:

- one goal-global budget of ten no-retry refresh cycles;
- one goal-global exact Cancel outcome;
- atomic row locking before either allowance is used;
- `NOT_RUN`, `CLAIMED`, `ACCEPTED`, `REJECTED`, or `UNKNOWN` Cancel readback;
- restart conversion of an interrupted Cancel claim to terminal `UNKNOWN`;
- no transfer or multiplication of authority across cases.

The migration adds `goal_id` to recovery cases. Existing rows are assigned to
the predecessor goal, byte-for-byte immutable R1–R12 and V1–V15 artifacts are
not touched, and successor list/detail/event queries cannot return predecessor
cases or events. The predecessor ledger is durably sealed at exhausted refresh
authority and terminal unknown Cancel authority; manually selecting it cannot
reopen a read or mutation allowance. A predecessor case may still prevent an
unsafe duplicate active case for the same order; it cannot provide Goal 6
authority.

Every Goal 6 case exposes the exact goal id, goal-global refresh use, the
ten-cycle limit, and the goal-global Cancel outcome. Case-local read and call
counters remain visible so the operator can distinguish the exact case that
used an allowance from untouched cases.

## Exchange boundaries

Creating, listing, selecting, applying, and rolling back a case are
Coinbase-call-free. Each confirmed refresh may invoke:

- one logical exact Coinbase order read, with required cursor pages and no
  page retry;
- one logical exact fill read, with required cursor pages and no page retry.

The optional Cancel is permitted only when the immutable backend plan is
`CANCEL_ACTIVE_ORPHAN`, the approved Test-portfolio binding is current, the
local order remains terminal and system-owned, exact Coinbase evidence remains
active, and authoritative fill count is zero. It uses the existing canonical
Spot Cancel service and at most one exact Cancel call for the whole goal.
There is no Create, alternate order, fallback, redirect, or retry.

An interrupted or ambiguous post-claim Cancel consumes the goal allowance and
cannot be replayed. `REJECTED` is recorded only when the canonical Cancel
service returns fixed authoritative evidence that Coinbase explicitly rejected
the exact command. Every other non-accepted post-boundary result is
`UNKNOWN`. A pre-boundary rejection releases the claim. The browser freezes
further commands after an ambiguous BFF outcome until the operator reloads
authoritative backend readback.

## Security and evidence

The backend owns authentication, RBAC, system ownership, approved Test
portfolio binding, revision control, idempotency, duplicate prevention,
allowance accounting, reconciliation, restart recovery, audit, and action
projection. Every mutation requires `X-Operator-Intent` to equal the exact
backend service method for that route; an arbitrary nonblank intent is rejected
before command execution. Operator reasons are hashed before persistence.

The Admin UI accepts a successful mutation readback only when the response
header correlation, body correlation, body idempotency key, service method,
case correlation, goal, and exact requested case or `client_order_id` all bind
to the request that the browser just sent. Stale or cross-command readback
freezes further commands.

Public responses contain only fixed diagnostics, hashed portfolio binding,
sanitized immutable plan fields, counters, action availability, and
allowlisted audit events. Raw Coinbase responses, exchange-native identifiers,
exception messages, secrets, private identifiers, and withheld text are not
persisted or exposed.

## Historical comparison

The implementation compared:

- `origin/prod:business/fill_reconciler.py`;
- `origin/prod:core/periodic_reconciler.py`;
- `origin/prod:core/startup_reconciler.py`.

Only exact-state comparison and restart/reconciliation concepts were
translated. Background auto-heal, implicit retries, legacy dashboard
WebSocket authority, and browser-side exchange behavior were not copied.

## Validation status

Focused backend repository, route, policy, migration, restart, and generated
OpenAPI checks pass (42 tests). Focused frontend contract, trust-boundary,
component, type, lint, and authenticated BFF checks pass (16 tests). Full
backend regression passed 1,286 parallel-safe tests with 6 skips and 908
serial tests with 150 skips. The canonical frontend release gate passed 125
files and 1,783 tests plus the complete installed and authenticated Playwright
matrix.

Independent safety and blind-contextless re-audits both pass after the typed
Cancel-outcome, exact operator-intent, and exact request/readback binding
remediation. Every managed proof was synthetic/no-network and made zero
Coinbase calls. Goal 6 refresh use is `0/10`, Cancel is `NOT_RUN`, and every
external-call allowance remains unconsumed.
