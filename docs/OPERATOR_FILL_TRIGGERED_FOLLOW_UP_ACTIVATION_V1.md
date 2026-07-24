# Operator Fill-Triggered Follow-Up Activation V1

Goal ID: `operator_fill_triggered_follow_up_activation_v1`.

This goal lets an authenticated operator enable, disable, pause, or drain one
previously attached follow-up intent. The control command is a PostgreSQL
local-state mutation. It is revision-bound, idempotent, audited, and accepts
no child order terms. `ENABLE` requires explicit acknowledgements and durably
delegates at most one future canonical Create after the backend proves the
displayed Controlled-live, approved Test-portfolio, full-fill, wallet, policy,
and exact current `3.10/1.00 USDC` cap boundaries. The other control actions
delegate no Create authority.

When the source reaches the backend order engine's authoritative full-fill
boundary, the activation repository requires:

- control state `ENABLED` and trigger state `UNCLAIMED`;
- source order state exactly `FILLED` with positive source size;
- positive fill-ledger rows whose exact sum equals source size;
- no negative fill-ledger row; and
- zero prior partial-fill children.

A Goal 8 PostgreSQL advisory lock is held continuously across the trigger
claim, canonical materialization, and activation terminal persistence. The
compare-and-set produces at most one trigger winner without leaving a recovery
gap. That winner delegates to the existing canonical operator follow-up
materializer with a fresh backend-owned authorization, deterministic
claim-bound idempotency, the approved Test-portfolio policy, current caps, and
Goal 8's distinct live-proof ledger. No second child, retry, fallback,
redirect, partial-fill fan-out, or alternate placement path exists.

Every attached intent remains managed by this interlock even when disabled,
paused, drained, blocked, or unknown. Those states cannot fall through into
the legacy automatic follow-up path. Unknown materialization or persistence
outcomes are terminal and cannot be replayed.

At startup, a stranded claimed activation is recovered under the same Goal 8
advisory lock from the canonical local materialization ledger. An accepted
canonical child is rebound to the activation; a definitely uninvoked attempt
is blocked; and invoked, unknown, or unrecognized evidence becomes terminal
unknown. Recovery makes no Coinbase call and cannot replay Create.

The Admin API exposes:

- call-free activation readback;
- call-free enable, disable, pause, and drain commands, with ENABLE's future
  one-use delegated Create authority displayed explicitly;
- call-free Goal 8 materialization/exact-child readback; and
- a separately confirmed one-use Cancel only for the exact bound child when
  backend reconciliation says safe closeout is eligible.

Readback withholds operator identity/roles, the trigger claim ID, evidence
hashes, raw Coinbase responses, exchange-private identifiers, and exception
text. The browser renders generated contracts and forwards explicit operator
intent only.

## Origin/prod translation

`origin/prod:core/order_engine.py` supplied historical context for full-fill
and partial-fill follow-up event flow. The translation retains the event
boundary but replaces implicit legacy behavior with explicit operator control,
PostgreSQL claims, canonical Admin API authority, and fixed sanitized
evidence. Legacy dashboard/WebSocket authority, partial-fill fan-out, retries,
and browser trading decisions were not copied.

## Focused validation

Focused tests cover control revision/idempotency, concurrent single-winner
claiming, exact full-fill rejection, terminal unknown behavior, canonical
materializer delegation, Goal 8-separated exchange-call ledgers, order-engine
legacy interlock, Admin API contracts, generated OpenAPI/route inventory, and
the Orders-detail UI controls.

Milestone closeout passed:

- canonical backend regression: `1,282 passed, 6 skipped` in the parallel lane
  and `819 passed, 150 skipped` in the serial lane;
- frontend full regression: `1,692/1,692`;
- installed Playwright workflows: `23/23`;
- generated contract coverage: `214` Admin API paths;
- the canonical release and installed deployment gates; and
- independent safety plus blind-contextless audits.

The safety remediation holds the Goal 8 advisory lock continuously across
claim, canonical materialization, and activation terminal persistence. A
barrier regression proves startup recovery cannot acquire that lock while
dispatch is inside the canonical materializer.

A count-only read of the operator PostgreSQL database found zero attached
intents and zero exact full-fill candidates. The goal therefore made no
Coinbase call or exchange mutation, and its one Create plus conditional
exact-child Cancel allowances remain unconsumed.
