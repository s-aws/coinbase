# Scope-creep TODO — 2026-05-02 status reducer + deferred post-only saturation work

This note exists to preserve intent for a future agent.

The current implementation around parent/root status writes and failed `post_only`
handling is **not** an accidental patch pile. It is a deliberate simplification that
was introduced while diagnosing a live bug so the team could first prove the engine
tracks the right placement rows, preserves follow-up linkage, and never silently
changes operator intent.

Do not approach the current state as "clean up obvious mistakes" without carrying
forward the constraints below.

## What is intentional in the current state

### 1. Simplified failed `post_only` handling was by design

The current reveal placement logic in `core/stealth_order_manager.py` uses a simple,
operator-safe rule:

- place the intended passive order
- if Coinbase rejects it as `post_only`, retry with a fresh `client_order_id`
- step exactly one safer tick per retry
- stop after a small bounded ladder
- never silently demote to taker

This was chosen during diagnosis because the immediate priority was correctness and
forensics, not optimal saturation behavior.

What this simplification protected:

- the exchange-facing placement row remains auditable
- each retry has its own `client_order_id`
- rejected attempts can be marked failed without corrupting the live attempt
- follow-up creation is not lost behind ambiguous duplicate-COID behavior
- the operator's maker-only intent is preserved

### 2. Parent/root status propagation was simplified to prove placement tracking

In the current implementation, both root parents and reveal placement rows live in
`order_parent`. For stealth-managed flows, a reveal child placement can therefore have
two meanings in play at once:

- the placement row is the exchange truth for that specific `client_order_id`
- the chain root is the logical order that dashboards and reporting often read

The current code writes status changes to the placement row and may also propagate the
same status to the root. This was a deliberate simplification to keep the dashboard and
logical-chain visibility usable while diagnosing a bug in reveal/follow-up handling.

It is known to allow `PENDING`/`OPEN` oscillation when out-of-order websocket events
arrive, because the helper currently accepts the last write without a transition guard.

That oscillation is a known tradeoff of the temporary simplification, not evidence that
the original diagnostic direction was wrong.

## Constraints a future agent must preserve

1. Do not silently demote a failed `post_only` order into a taker order.
2. Do not reuse `client_order_id` across retries.
3. Do not remove exchange-truth placement rows in the name of "cleaner" lineage.
4. Do not conflate placement-row lifecycle with logical-root lifecycle.
5. Do not break the flat hierarchy rule: all follow-ups still link to the original root.
6. Do not remove root propagation unless dashboards/reporting get a replacement source
   of truth in the same change.

## Recommended first work item

Build a monotonic status reducer for logical parent status.

This should be done before replacing the simple `post_only` retry ladder with a more
adaptive saturation strategy.

Why this goes first:

- status correctness is foundational OMS behavior
- the current oscillation is a real state-machine weakness
- an adaptive retry policy will create more event-order complexity, not less
- fixing state precedence first reduces the risk of misreading later post-only tests

## Plan for the first work item: monotonic status reducer

### Goal

Prevent lower-confidence or earlier-lifecycle statuses from rewinding a logical order
after it has already advanced.

Concrete symptom to eliminate:

- `OPEN -> PENDING` on the same logical order due to out-of-order event arrival

### Design intent

Split the two state surfaces cleanly:

- **placement row status**: raw exchange lifecycle for that exact placement COID
- **logical root status**: reduced, monotonic status for the root order chain

The placement row may still receive raw exchange updates. The root row should only be
updated through a guarded reducer.

### Proposed implementation steps

1. Add a status precedence / transition policy in one place.

   Minimum expected ordering:

   - `PENDING < OPEN < FILLED`
   - `PENDING < OPEN < CANCEL_QUEUED < CANCELLED`
   - duplicate writes are idempotent
   - lower-ranked statuses cannot overwrite higher-ranked statuses

   Do not scatter this rule across multiple call sites.

2. Add a dedicated DB helper for guarded logical-root updates.

   Preferred shape:

   - current status read or compared atomically
   - update only when transition is valid or rank is non-decreasing
   - return whether the write was applied or skipped

   The existing unconditional helper can remain for raw placement-row writes if needed,
   but logical-root writes should stop using it directly.

3. Update `core/order_engine.py` so root propagation routes through the guarded helper.

   Keep placement-row writes explicit.
   Guard only the logical-root update path.

4. Add logging that distinguishes:

   - placement status write applied
   - root reducer write applied
   - root reducer write skipped as stale/regressive

   This is necessary so future incident review can tell whether a "missing" root update
   was intentionally rejected.

5. Add regression coverage for the exact known race shapes.

   Required cases:

   - `PENDING` then `OPEN` then stale `PENDING` on the same root
   - duplicate `OPEN` is harmless
   - child placement status updates still update the placement row even when root skip
     logic rejects a regressive root write
   - terminal states are not overwritten by stale earlier lifecycle events

6. Validate dashboards after the reducer lands.

   The existing simplification was partly to keep dashboards readable. If dashboards are
   reading the root row only, confirm they still show the intended logical status after
   reducer changes.

### Acceptance criteria

1. No `OPEN -> PENDING` rewinds for logical root rows under replayed event ordering.
2. Placement rows still reflect the raw exchange lifecycle for the exact COID.
3. Follow-up and reconciliation behavior remains unchanged.
4. `pytest tests/regression/ -v --tb=short` passes.

## Deferred second work item

After the status reducer is in place, revisit the `post_only` retry ladder under
saturation.

That later change should likely move from "previous rejected price plus one safer tick"
to a strategy anchored to the live passive boundary, while keeping the existing safety
properties:

- maker-only intent preserved
- bounded retries
- fresh `client_order_id` per attempt
- no silent taker fallback

Do not start that work by deleting the current ladder. Replace it only after the status
surface is stable enough to interpret the new behavior correctly.