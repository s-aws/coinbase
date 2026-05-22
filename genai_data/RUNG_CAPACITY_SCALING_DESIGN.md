# Rung Capacity Scaling — By-Design Plan

> **Status:** design only, not implemented.
> **Pattern name (this repo):** *rung capacity scaling*.
> **Pattern in the literature:** flow-following / adaptive depth in market making
> (Avellaneda-Stoikov reactive variants, Hummingbot `inventory_skew`).

---

## 1. Problem statement

Given a multi-rung ladder (e.g. `A@$1, B@$2, C@$3`), if a single rung
demonstrates repeated fills inside a recent window, **add additional working
orders at that rung's price** so the ladder captures more of the demonstrated
flow before the price moves away.

This is **not** re-anchoring (price stays put) and **not** martingale-into-loss
(only triggered by *successful* fills, not by un-filled chase).

## 2. Vocabulary

| Term | Meaning |
|------|---------|
| **Rung** | A logical price level inside a ladder. Identified by `(parent_chain_id, rung_index)`, not by `client_order_id`. |
| **Rung replacement** | Replacing the working order at a rung after it fills, to keep baseline capacity = 1. *Completion of existing exposure.* |
| **Rung capacity add** | Adding an Nth working order at the same rung price. *New exposure.* |
| **Fill window** | Rolling time window `T` over which fills are counted per rung. |
| **Adverse-selection check** | Post-fill price action signal — did price revert (good) or trend through the rung (bad)? |

## 3. Triggers (all must hold)

A rung capacity add fires iff:

1. `fills_in_window(rung) >= N`  — windowed, not cumulative.
2. `adverse_selection_score(rung) <= S_max` — last `K` fills did not see price trend through the rung by more than `D` bps within `t` seconds post-fill.
3. `live_orders_at_rung(rung) < cap_per_rung` — hard inventory cap.
4. `total_open_exposure(parent_chain) + order_size <= chain_exposure_cap` — chain-level cap.

If any check fails: no add. Counter is **not** consumed.

## 4. Decay

When `fills_in_window(rung) < N` after the next window slide:
- Existing extra orders at the rung are **not auto-replaced on fill** (replacement happens only up to baseline = 1).
- No active cancellation (avoid cancel-storms); shrinkage is passive via fills.

## 5. State model — what must persist

Everything that drives a re-stack decision MUST be on disk before the next
add-trigger evaluation. In-memory-only is what stranded you on restart last
time.

### 5.1 Schema additions

Add to `order_parent` (per-order rung membership only):

```sql
ALTER TABLE order_parent
    ADD COLUMN IF NOT EXISTS rung_index INTEGER;
```

> **Pivot note (Step 3 of impl):** an earlier draft also put
> `rung_baseline_size`, `rung_capacity_cap`, and `rung_capacity_used` on
> `order_parent`. That was wrong — those counters are **per-rung**, not
> per-order. Storing them on every child row creates ambiguity (which
> row is authoritative?) and breaks the single-row atomic claim in §7.
> Verified empty in the live DB before pivoting; columns dropped.

New table — per-rung counter, keyed by rung identity:

```sql
CREATE TABLE IF NOT EXISTS rung_state (
    parent_chain_id      VARCHAR(40) NOT NULL,
    rung_index           INTEGER     NOT NULL,
    rung_price           NUMERIC,
    rung_baseline_size   NUMERIC,
    rung_capacity_cap    INTEGER     NOT NULL DEFAULT 1,
    rung_capacity_used   INTEGER     NOT NULL DEFAULT 0,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (parent_chain_id, rung_index)
);
```

Row created lazily when the first order at a new rung is placed.

New table — append-only fill log scoped to rung-level analytics:

```sql
CREATE TABLE IF NOT EXISTS rung_fill_events (
    id              BIGSERIAL PRIMARY KEY,
    parent_chain_id VARCHAR(40) NOT NULL,   -- top-level client_order_id
    rung_index      INTEGER     NOT NULL,
    rung_price      NUMERIC     NOT NULL,
    fill_size       NUMERIC     NOT NULL,
    fill_price      NUMERIC     NOT NULL,
    filled_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    post_fill_mark  NUMERIC,                -- mark price T_pf seconds later
    post_fill_at    TIMESTAMPTZ,
    client_order_id VARCHAR(40) NOT NULL    -- which working order filled
);
CREATE INDEX IF NOT EXISTS idx_rung_fill_window
    ON rung_fill_events (parent_chain_id, rung_index, filled_at DESC);
```

### 5.2 Why Postgres, not S3 / local-only

Your 10-years-ago instinct (where do I put it?) has a clean answer in 2026:

- **S3** — wrong tool. Object storage. No transactional reads, no row-level locks, eventual consistency on overwrites. Use for log archival, never for OLTP state.
- **Local SQLite / files** — fine for dev, fails on multi-process / multi-host.
- **RDS / managed Postgres** — correct. You already have Postgres. The same DB that holds `order_parent` should hold rung state. One transactional boundary, no cross-store consistency problem.

Rule of thumb: **state that gates a placement decision belongs in the same transaction as the placement record.**

## 6. Rehydration on restart

On engine startup, before opening the placement gate:

```
1. SELECT all order_parent rows WHERE status IN (OPEN, PENDING).
2. Group by parent_chain_id → rebuild ladder + rung membership.
3. For each rung:
     live_orders_at_rung   = count(open orders at that rung)
     rung_capacity_used    = live_orders_at_rung   ← reconcile, do not trust DB column blindly
     fills_in_window(rung) = SELECT COUNT(*) FROM rung_fill_events
                              WHERE parent_chain_id=? AND rung_index=?
                                AND filled_at > now() - INTERVAL 'T'
4. Reconcile against REST list_orders for the product (existing reconciliation path).
5. Only after reconcile completes: enable add-trigger evaluation.
```

Reconciliation against `list_orders` (already in the codebase) is the
authoritative source for "what's actually live." The DB columns are
the source of truth for **intent and history**.

## 7. API split (mirrors the `budget-vs-completion-cap` fix)

In `core/order_engine.py` / `register_child_order`, two distinct kinds.
Named ``RungFollowUpKind`` (not ``FollowUpKind``) because the latter is
already taken in [core/enums.py](../core/enums.py) for terminal-event
claim namespacing (FILLED vs CANCELLED).

```python
class RungFollowUpKind(Enum):
    REANCHOR           = "reanchor"           # chain re-anchor; consumes max_order_replacement
    PARTIAL_COMPLETION = "partial_completion" # carry-remainder; bypasses max_order_replacement
    RUNG_REPLACEMENT   = "rung_replacement"   # baseline=1; bypasses both caps
    RUNG_CAPACITY_ADD  = "rung_capacity_add"  # +1 at hot rung; consumes rung_capacity_cap only
```

`register_child_order(kind=RUNG_CAPACITY_ADD)`:
- Atomic SQL (single row, single statement):
  ```sql
  UPDATE rung_state
     SET rung_capacity_used = rung_capacity_used + 1,
         updated_at = NOW()
   WHERE parent_chain_id = ?
     AND rung_index = ?
     AND rung_capacity_used < rung_capacity_cap
  RETURNING rung_capacity_used;
  ```
- If `RETURNING` is empty → cap reached, abort placement.
- Else → proceed. Place order. On placement-failure, decrement in same transaction.
- If the row does not exist yet, insert it with `rung_capacity_used = 1`
  inside the same transaction (lazy creation on first placement at the rung).

`register_child_order(kind=RUNG_REPLACEMENT)`:
- No counter mutation.
- Distinct audit event (`rung.replacement.placed`), not the duplicate-detector warning.

This is the same shape as the partial-fill bypass already shipped in
`_create_partial_fill_follow_up`. Reuse the pattern; do not invent a parallel one.

## 8. Atomicity / race handling

Two failure modes worth wiring:

1. **Concurrent fills on the same rung trigger two adds.** Mitigated by the
   `RETURNING` claim above — only one transaction can move
   `used: 1 → 2`; the loser sees no row and skips.

2. **Place succeeds, ack lost, restart.** Rehydration step (§6) reconciles
   `rung_capacity_used` from observed live orders, not the stale column.
   Column is corrected post-reconcile.

Both must have regression tests under `tests/regression/`.

## 9. Risk knobs (config, not code)

| Knob | Where | Default suggestion |
|------|-------|--------------------|
| `N` (fills-in-window threshold) | per-strategy config | 3 |
| `T` (window seconds) | per-strategy config | 60 |
| `cap_per_rung` | per-rung override, default per-strategy | 3 |
| `chain_exposure_cap` | per-chain | derived from risk budget |
| `S_max`, `K`, `D`, `t` (adverse-selection) | per-strategy | start permissive, tighten with data |

All knobs surfaced in `configuration.py` enums/dataclasses. No magic strings.

## 10. Audit / observability

Every capacity-add event emits one structured log line + one DB row:

```
event="rung.capacity.add"
parent_chain_id=...
rung_index=...
rung_price=...
fills_in_window=...
window_seconds=...
adverse_selection_score=...
new_used=...
cap=...
client_order_id=<new child>
```

Without this, you cannot post-hoc tell whether the pattern earned its keep
versus a flat ladder.

## 11. What this plan does NOT cover (deliberate)

- Initial ladder construction (assumed pre-existing).
- Rung migration when the ladder rebuilds at new prices (separate spec).
- Cross-product flow correlation (premature).
- Fee-tier optimization on stacked makers (premature; revisit after observability ships).

## 12. Implementation order (suggested)

1. Schema migrations (§5.1) + idempotent `ALTER`s.
2. Append-only `rung_fill_events` writer in the existing fill handler.
3. Rehydration (§6) — must land before the gate is enabled.
4. `FollowUpKind` enum + `register_child_order` atomic claim path (§7).
5. Trigger evaluator (§3) — fed by `rung_fill_events`, not in-memory counters.
6. Adverse-selection scorer (§3, item 2) — start as a stub returning 0; tighten later.
7. Regression tests for: cap claim race, rehydration after lost ack, decay
   passes (no auto-replace beyond baseline), `RUNG_REPLACEMENT` does not
   consume cap.
8. Config surfaces (§9) + audit log (§10).
9. Enable behind a strategy-level feature flag. Run flat-ladder vs
   capacity-scaling A/B before defaulting on.

---

## Appendix A — Why count-since-forever is wrong (one-liner)

Cumulative fill count rewards old, stale liquidity. A rung that filled
50 times yesterday and 0 times today should not be the place you stack
size right now. Window the counter or the pattern degrades into
"stack the rungs that have been around the longest."
