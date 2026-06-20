# Public Engineering Invariants

These are the minimum rules every specialist agent must keep in context.
Expanded local context may exist in `genai_data/`, but these public rules are
authoritative enough for fresh public clones.

## Domain Boundaries

- Do not edit files outside the owned files listed in the agent Owns section.
- If a change requires editing files owned by another agent, route the change to
  that owner or coordinate through the architect.
- Read-only access to files outside the domain for context is always allowed.

## IDs

- Use `client_order_id` for internal tracking, parent/child linkage, orderbook
  maps, dashboard references, follow-up claims, fill ledger ownership, and DB
  local rows.
- Use `order_id` only for exchange-facing operations and exchange-native
  evidence.
- Coinbase cancellation is an explicit exception when using this repo's
  `cancel_order(client_order_id)` wrapper; Coinbase accepts our
  `client_order_id` there, while raw batch `cancel_orders(order_ids=[...])`
  remains an exchange-id-oriented API.
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
- Same-side post-fill retreat applies only to opted-in hidden orders with no
  active exchange placement. It moves the hidden order's limit/reveal prices and
  persists the cumulative anchor offset; it must not mutate a live revealed
  placement directly.

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

## Invariant Escalation Rule

- If a request conflicts with any invariant in this document, do not implement it.
- Name the invariant, explain the conflict, and route the decision to the Architect Agent.
- Rejecting the request is the correct default. Invariant changes are architectural decisions, not implementation details.

## Conditional Planning Rule

- For invariant-conflicting requests, you may provide impact analysis and an exchange-truth-preserving design sketch, but label it conditional.
- Do not present conditional plans as approved implementation work.
- A conditional plan exists to inform the user's decision, not to do the work.

## Tests

- Ordinary phase work requires focused tests and validators for the changed
  behavior.
- Full regression is reserved for durable milestone closeout,
  public/release-candidate handoff, deployment approval/closeout,
  release-hardening closeout, Admin API/backend association closeout, or
  explicit user request:

```powershell
pytest tests/regression/ -v --tb=short
```

- Focused tests in `.agents/ownership.yaml` are the normal phase-level checks.
  They do not replace full regression when a milestone is being marked
  complete.
