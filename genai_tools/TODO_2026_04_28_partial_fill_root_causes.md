# Scope-creep TODO — 2026-04-28 partial_fill_progress FK incident

The 2026-04-28 audit revealed three bugs in the same window. The exception
constructor bug (the one that *masked* the real failure) has been fixed and
guarded by a regression test. The remaining two are architectural and were
not in scope for the initial request — captured here so they aren't lost.

## TODO 1: Event ordering — fill processed before parent is persisted  ✅ FIXED 2026-04-28

**Evidence (per audit):** for all 6 affected COIDs, `upsert_partial_fill_progress`
fired *before* the corresponding `order_parent` row was inserted. The two
FILLED parents had real fills land in `fill_ledger` (no FK there) and then
the watermark write blew up on `partial_fill_progress.client_order_id_fkey`.

**Root cause:** `process_user_order` called `_process_ws_order_delta`
(which writes the watermark) immediately after stashing the order in the
in-memory orderbook, *before* the FILLED/CANCELLED routing inside
`handle_filled_order` / `handle_cancelled_order` that would have created
the parent row for an externally-placed order.

**Fix:**
- Added `_ensure_order_parent_row_exists(normalized_order)` to
  `core/order_engine.py` — idempotently creates the parent row if missing.
- Hoisted the call into `process_user_order` as Step 3a, *before*
  `_process_ws_order_delta` (Step 3b).
- Tagged hoist-created cache entries with `externally_created=True` so
  `_is_external_order` keeps returning True for externally-placed orders
  and the downstream `_handle_external_order_tracking` event path still
  fires correctly (`external_order_filled` / `external_order_cancelled`).

**Verified by:** `tests/regression/test_parent_row_before_ws_delta.py`:
1. Pin call order — `ensure_parent` runs before `process_delta`; the COID
   is in `parent_order_ids` by the time the watermark write happens.
   Without the hoist, the test fails with the exact 2026-04-28 message.
2. Idempotency — already-tracked orders trigger no DB calls.
3. DB-hydration path — pre-existing parent rows are loaded into cache
   without re-inserting.
4. External-order routing — hoist-created entries remain classified as
   external by `_is_external_order`.

## TODO 2: Transaction poisoning — InFailedSqlTransaction cascades to siblings  ✅ FIXED 2026-04-28

**Evidence:** COIDs `23077e38-…` and `bd2123d8-…` were never genuine FK
violators. Their `order_parent` rows existed at audit time (DB ids 21, 22).
They failed solely with `InFailedSqlTransaction`, meaning a previous error
on the same connection (from `fa295dc5-…`) had aborted the transaction,
and the next two rows in the batch were rejected without rollback in between.

**Root cause:** The global `DB_CLIENT = PostgresDB()` is a single instance
with one underlying psycopg2 connection, shared by `user_event_thread_*`
threads. When thread A's `cursor.execute` aborts the transaction, thread B
mid-execute on the same connection sees `InFailedSqlTransaction` *before*
A's rollback runs.

**Fix:** Added `threading.RLock` to `PostgresDB.__init__` and wrapped the
entire `get_cursor` body (begin → execute → commit/rollback) in it. The
lock is re-entrant so nested calls from the same thread still work.

**Verified by:** `tests/regression/test_db_cursor_thread_safety.py` —
reproduces the cascade with two concurrent threads (one FK violator, one
innocent writer); without the lock the innocent writer sees ~50%
`InFailedSqlTransaction` errors, with the lock it sees zero.

## TODO 3: One-off — `42ec9eeb-ff4f-44ac-9f3e-e43ae147e633` reconciliation

The dry-run reconciliation script is at
`genai_tools/reconcile_2026_04_28_fk_violations.py`. Live exchange order has
been cancelled out-of-band by the operator; DB still has:
- no `order_parent` row for `42ec9eeb…`
- 6 missing `partial_fill_progress` rows (5 with parent present, 1 with parent missing)
- 17 dangling `order_event_stream` rows that reference COIDs above

Decide whether to leave the historical DB inconsistency or run the script with `--apply`.
