# Operator Parent Move Premark Lifecycle V1

Goal ID: `operator_parent_move_premark_lifecycle_v1`.

## Operator outcome

An authenticated operator can open one exact system-owned Spot root from the
Orders workspace, review backend-owned source eligibility, and explicitly
premark one immutable replacement plan at:

`/movement-repricing?client_order_id={client_order_id}`.

Premark is a local PostgreSQL mutation. It reserves the one successor
`client_order_id`, quantizes the reviewed replacement price, binds the source
evidence and current Product Catalog terms, and records the actor,
idempotency, correlation, plan, cap, and cycle evidence. It makes zero Coinbase
calls.

The reservation is deterministically derived from the goal, canonical source,
and command key. An exact retry reads the durable command binding before
mutable source truth, so later source drift cannot change the plan or its
reserved successor. A different source cannot consume a second plan slot:
the one-plan allowance is goal-global and fails with
`operator_parent_move_goal_allowance_unavailable`.

The current Goal 14 addendum did not enumerate the Coinbase read categories
needed to revalidate profile, product, wallet, market, and exact-order truth
before a source Cancel or replacement Create. The backend therefore never
advertises `EXECUTE_PARENT_MOVE` or `SAFE_CLOSEOUT` and rejects both live
routes before ledger or runtime access with:

`operator_parent_move_live_authority_terms_incomplete`.

All Goal 14 source-Cancel, replacement-Create, and successor-closeout-Cancel
allowances remain unconsumed.

## Backend authority

Premark requires all of the following local evidence:

- the configured approved `Test` portfolio and its SHA-256 binding;
- the active PostgreSQL Product Catalog entry for `BTC-USDC`;
- a canonical system-owned `ADMIN_MANUAL_ROOT`;
- no parent identity, proving the selected order is a direct root;
- explicit authoritative nonterminal and cancel-eligible evidence;
- a nonterminal limit order with good-until-cancelled semantics;
- exactly zero filled size;
- no legacy pending-move record;
- valid price and base increments and product minimums;
- submitted notional at or below `3.10 USDC`;
- possible-execution notional at or below `1.00 USDC`.

The browser does not infer any of these conditions. It renders the backend
source-selection evidence and forwards only the operator's explicit request.

The separate Goal 14 PostgreSQL ledger owns:

- the one goal-local source and reserved successor identity;
- an immutable sanitized plan and its SHA-256;
- a maximum of ten plan, execute, and closeout cycles;
- exact request-bound command replay or conflict classification;
- three non-transferable single-use mutation claims and call counts;
- boundary-crossed restart recovery to consumed unknown;
- pre-boundary restart recovery without consuming a mutation allowance,
  including create-only continuation after a durably returned source Cancel;
- source follow-up suppression state;
- a durable source-Cancel event acknowledgement and persistent consumed-event
  seal;
- append-only fixed-code audit events;
- hash-only actor, idempotency, payload, and completion evidence.

Raw command idempotency keys, raw Coinbase responses, raw exchange identities,
exception messages, secrets, private portfolio identity, and withheld text are
neither persisted nor returned. Legacy raw idempotency columns are migrated to
SHA-256 bindings and dropped. An older plan whose exact Premark request binding
cannot be reconstructed receives an explicit legacy marker and fails replay
closed with `operator_parent_move_legacy_request_binding_unavailable`; the
column is never left nullable.

Any future runtime result after a crossed exchange boundary must bind the exact
expected `client_order_id` and parent identity and include a non-null sanitized
exchange-evidence SHA-256 for an accepted, cancelled, or rejected
classification. Exceptions or malformed returns after the boundary become
durable `UNKNOWN`; pre-boundary failures abort the claim without spending its
allowance.

## Routes

- `GET /api/v1/movement-repricing/orders/{client_order_id}/parent-move`
- `POST /api/v1/movement-repricing/orders/{client_order_id}/parent-move-plans`
- `POST /api/v1/movement-repricing/orders/{client_order_id}/execute-parent-move`
- `POST /api/v1/movement-repricing/orders/{client_order_id}/parent-move-safe-closeout`

The GET is a call-free PostgreSQL read. Premark requires `order:cancel` and
`order:create`, an idempotency key, a correlation ID, and exact operator
intent `premark_parent_move`. It is the only currently available action.

The two live-shaped routes are deliberately present so operator readback,
generated contracts, and future authority cannot drift into an alternate
path. Their controls remain visibly unavailable and their handlers fail before
the service, durable claims, runtime, or Coinbase boundary.

## Cancellation follow-up fence

The canonical Order Engine accepts Goal 14 suppression-check and durable
acknowledgement callbacks in both embedded and standalone composition. After a
future separately authorized execution has durably activated suppression, a
source `CANCELLED` event stops before the legacy pending-move path, external
tracking, Stealth handling, or generic follow-up creation. The active
suppression flag clears only in the same transaction that records the Order
Engine acknowledgement. A persistent consumed-event seal continues to block
duplicate or replayed cancellation events, including after restart. Checker or
acknowledgement failure remains fail-closed.

Schema upgrade also re-arms the active fence for any older row that proves its
source-Cancel allowance was consumed but has neither an active fence nor a
durable cancellation-event acknowledgement. This repair runs before restart
recovery or runtime ingress.

The legacy dashboard `move_order` and `premark_move` commands are
source-disabled. They cannot bypass the Admin API ledger.

## Historical translation

The implementation compared current code with:

- `origin/prod:business/move_manager.py`;
- `origin/prod:dashboard_server.py` `move_order` and `premark_move`;
- `origin/prod:core/order_engine.py` `handle_cancelled_order` and its pending
  move branch.

The useful legacy intent was retained: preserve the source, create a distinct
successor, and make the relationship auditable. The legacy browser/WebSocket
authority, float-shaped order terms, local JSON-style notes, broad exception
display, racy multi-write flow, and implicit cancellation-triggered execution
were not retained. The Admin API, PostgreSQL ledger, typed policy, explicit
operator confirmation, durable suppression, fixed diagnostics, and generated
frontend contract replace those boundaries.

## Validation boundary

Goal 14 validation uses synthetic local source, product, and ledger fixtures.
It performs no Coinbase API, Preview, Create, Cancel, Close, Reduce, or other
exchange call. Live execution remains a separately authorized future goal.

Terminal validation passed the focused backend and frontend suites, a real
authenticated browser/BFF/PostgreSQL persistence proof, the canonical full
backend regression, and the complete frontend release/deployment gate. The
browser proof persisted exactly one immutable Premark, survived reload, and
reported zero Coinbase reads, Preview calls, or exchange mutations.
Focused validation passed 83 backend tests and 164 frontend tests. Canonical
backend regression passed 1,338 tests with 6 skipped in its parallel lane and
1,000 tests with 150 skipped and 1,344 deselected in its serial lane. The
frontend gate passed 1,928 unit/component tests and 34 managed Playwright
operator scenarios.

Independent safety and blind-contextless audits both returned `PASS` after
their findings were remediated. The final safety review specifically covered
tri-state cancellation-fence retention, replay-before-mutable-read behavior,
fail-closed browser storage, canonical plan hashing, lifecycle/counter
coherence, fixed diagnostics, and exact BFF routing. The blind review
confirmed that this remains a Spot-specific domain workflow sourced from the
backend OpenAPI contract and cannot be copied into Futures or treated as
browser trading authority.
