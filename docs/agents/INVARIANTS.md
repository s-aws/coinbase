# Public Engineering Invariants

These are the minimum rules every specialist agent must keep in context.
Expanded local context may exist in `genai_data/`, but these public rules are
authoritative enough for fresh public clones.

## IDs

- Use `client_order_id` for internal tracking, parent/child linkage, orderbook
  maps, dashboard references, follow-up claims, fill ledger ownership, and DB
  local rows.
- Use `order_id` only for exchange-facing operations and exchange-native
  evidence.
- Do not use exchange `order_id` as proof of local ownership. Resolve ownership
  through local submission evidence.

## Parent/Child Hierarchy

- Parent/child hierarchy is flat.
- Every child points to the original root parent.
- Children must not become parents of later children.

## Stealth Exchange Truth

- `HIDDEN`, `PENDING`, and `TRIGGERED` stealth orders must not have a live
  Coinbase placement.
- `REVEALED` means a placement was submitted and may still be live.
- A revealed order cannot become hidden, cancelled, or moved by local mutation
  alone. The live placement must be cancelled, replaced, filled, moved, or
  reconciled closed first.
- Cancel/re-entry is a narrow policy for no-fill revealed placements. It is not
  general hide-again behavior.

## Single Path

- Use one code path per behavior.
- Do not add local dashboard-only, SQL-only, strategy-only, or bridge-only
  variants of domain behavior.
- Do not recreate deleted pass-through bridge/orchestrator layers.

## Enums and Configuration

- Use enums from `core/enums.py` for shared statuses, policies, channels,
  lifecycle events, runtime states, and strategy values.
- Do not hard-code product ids, increments, min sizes, or product types in
  strategy code. Use `products.json`, `configuration.py`, and calculation
  helpers.

## Locks and Claims

- Respect existing module locks.
- `OrderEngine.orderbook_lock` guards in-memory order/parent/child mutations.
- Per-COID locks serialize order-event processing for the same
  `client_order_id`.
- `PostgresDB._cursor_lock` serializes DB cursor and transaction access.
- Runtime inflight work must use `RuntimeController.track_inflight` where the
  existing path requires graceful pause/drain/shutdown safety.
- Do not bypass claim ledgers for follow-ups, replacement slots, or stealth
  mutations.

## Tests

- Non-agent-file changes require:

```powershell
pytest tests/regression/ -v --tb=short
```

- Focused tests in `.agents/ownership.yaml` are development checks only. They
  do not replace the regression gate.

