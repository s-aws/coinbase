# Partial Fill Follow-Ups

Reconciled on 2026-10-09. The canonical path is OrderEngine's
`_process_ws_order_delta` -> `_maybe_create_partial_fill_follow_up` ->
`_create_partial_fill_follow_up`, using `business/order_progress.py` and the
existing stealth bridge factory. Every child remains linked to the original
root `client_order_id`.

## Admission and quantities

`allow_partial_fills` is a per-root flag, read from the parent cache with DB
fallback. It enables nonterminal fill-delta follow-ups; creation defaults vary
by caller, so inspect the supplied payload rather than assuming a global opt-in
value. The dashboard's stealth-create handler defaults it to true.

The progress tracker derives monotonic cumulative-quantity deltas and carries
unconsumed quantity. `_resolve_min_order_size` reads the product's
`base_increment` from the in-memory product catalog. The final stealth-creation
boundary still validates exchange minimum size and notional.

Available carry is reserved atomically with `claim_follow_up_units` before
slow child creation. One call creates a single child sized
`claimed_units * min_order_size`, not one separate child per unit. With a 0.01
unit and 0.025 carry, a successful two-unit claim creates one 0.02 child and
leaves 0.005 carry. No-ID outcomes and exceptions release the claim.

Partial-fill children deliberately bypass `max_order_replacement`: their
budget is accumulated fill carry. Normal full-fill/cancel replacements use the
separate root replacement-cap gate. Do not merge or duplicate these budgets.

## Intentional stop and lifecycle ordering

A source stealth order with durable operator-stop intent cannot create a new
partial-fill child. The bridge's source-SID action lock serializes cancellation
against the child factory; if cancellation wins after carry reservation, the
no-ID result refunds the units. Existing children are not retroactively stopped.
Fill ledger, audit, and execution recording continue for real fills.

Canonical authenticated live rows execute through the bounded per-COID FIFO,
with narrower parent-assurance/delta locks and the progress tracker's per-order
lock. Snapshot bootstrap hydrates in-memory order state without invoking fill
or follow-up side effects. Wire UPDATE/PATCH is separate from each row's OPEN,
FILLED, CANCELLED, FAILED, or EXPIRED lifecycle status.

`_finalize_partial_fill_progress` removes tracker state and marks persisted
progress terminal. EXPIRED is cleanup only, never a replacement trigger.

## Persistence and audit

`partial_fill_progress` stores restart watermarks and carry; engine startup
loads them through `_hydrate_order_progress_tracker_from_db`. The live delta
path also appends fill-ledger and order-match audit evidence and publishes
partial-fill event-stream records when that publisher is enabled. Internal
keys and parent lineage always use `client_order_id`.

## Tests and related references

Checked-in coverage includes `tests/unit/test_partial_fill_followups.py`,
`tests/unit/test_filled_followup_dedup.py`, and
`tests/regression/test_partial_fill_follow_up_atomic_claim.py`, plus operator
cancel follow-up tests. Run the complete gate in `TESTING_STRATEGY.md`; focused
selections require an explicit user request. See `ORDER_ID_HANDLING.md` and
`DATA_MODELS.md` for identifiers and persisted schema.
