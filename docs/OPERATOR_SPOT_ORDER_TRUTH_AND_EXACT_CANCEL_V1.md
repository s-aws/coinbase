# Operator Spot Order Truth and Exact Cancel V1

Goal ID: `operator_spot_order_truth_and_exact_cancel_reconcile_v1`.

Status: `terminal_operator_ready_controlled_live`.
Focused and canonical regression validation plus independent safety and blind
contextless audits pass, including the final remediation delta. The canonical
release gate, installed deployment check, and persistent Controlled-live
status verification pass. The frontend listens on `0.0.0.0:3000`; the backend
remains loopback-only on `127.0.0.1:8787`. The one global read-only truth cycle
and the independent exact Cancel allowance are both unconsumed. No Coinbase
call or exchange mutation was made during implementation, validation,
deployment, or audit.

## Operator outcome

The authenticated Orders workspace provides a normal Spot-operations workflow
for system-owned manual roots in the approved Test portfolio:

1. inspect the call-free PostgreSQL inventory;
2. explicitly spend the goal's single truth cycle on either an `OPEN` catalog
   refresh or one exact-order reconciliation;
3. select the order by canonical `client_order_id`;
4. review backend-owned portfolio, ownership, exchange-identity-hash,
   nonterminal, evidence, revision, and execution-posture readback; and
5. when every existing live-admission gate passes, explicitly submit one exact
   Cancel through the canonical order-cancel route.

The browser supplies no portfolio, exchange order ID, ownership classification,
status, product type, or alternate target. Page loading and ordinary
navigation make zero Coinbase calls.

## Fixed scope and allowances

This goal is restricted to:

- the configured approved `Test` / `CONSUMER` portfolio;
- Coinbase product type `SPOT`;
- canonical lowercase UUID `client_order_id` values;
- local `ADMIN_MANUAL_ROOT` ownership;
- a parentless `order_parent` row; and
- an exact hash match between the locally retained exchange order ID and the
  Coinbase order observation.

Children, follow-ups, Automation orders, Hotpoint orders, recovery orders,
Stealth placements, movement/repricing replacements, externally observed
orders, legacy rows without exact provenance, and unrelated portfolio rows do
not become owned or cancelable through this goal.

The PostgreSQL ledger has two non-transferable allowances:

- one goal-global read-only truth cycle; and
- one independent exact Cancel.

The truth cycle may be spent by `REFRESH_CATALOG` or `RECONCILE_EXACT`, not
both. The Cancel allowance does not create another Goal 12 truth cycle and
does not grant Create, replacement, follow-up, retry, fallback, redirect,
batch, fan-out, Futures, Close, Reduce, or any other exchange authority.

## Official Coinbase boundary

Coinbase's Advanced Trade
[List Orders](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/list-orders)
contract supplies product-type, status, product, creation-time, and cursor
scope. The backend, not the browser, selects the Goal 12 filters and follows
the documented cursor contract.

[Cancel Orders](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/cancel-order)
requires an exchange `order_id`. The operator route therefore remains keyed by
`client_order_id`; the backend resolves the exact locally retained exchange
ID, revalidates its hash against the authoritative observation, and uses the
raw value only for the one canonical wrapper call.

## Read boundary

One truth cycle may claim each of these categories at most once:

1. API-key permissions;
2. portfolio catalog; and
3. one logical Spot order catalog.

For every category, the ledger separates durable claim from actual invocation.
The wrapper callback marks `call_boundary_entered` immediately before its SDK
method. A local construction, lookup, or validation failure before that
callback cannot be reported as a Coinbase call. A failure after the callback
records the category outcome as `UNKNOWN`.

The logical order catalog may follow Coinbase cursor pagination. Every page is
claimed first and marked invoked only by its immediate SDK callback. A
pre-boundary page failure is not counted as an invocation; a post-boundary
failure is terminal unknown. Each page may be invoked only once, and there is
no individual-call or page retry.

Catalog refresh asks only for `OPEN` Spot orders and retains only observations
that match the exact local ownership, portfolio, product, and exchange-ID-hash
evidence. A previously observed projection missing from a later successful
refresh is retained as history but loses nonterminal and Cancel eligibility;
absence is not converted into an invented terminal status.

Cancel eligibility additionally requires a concrete allowlisted order type.
Missing, sentinel, or undocumented order types remain visible as sanitized
`UNKNOWN_ORDER_TYPE` history but are never actionable. PostgreSQL repairs any
stale pre-fix eligibility bit during schema startup, enforces coherence between
`OPEN`, authoritatively nonterminal, concrete order type, and
`cancel_eligible`, and repeats those predicates in the durable Cancel claim.

Exact reconciliation derives product and inclusive creation-time scope from
the canonical local row, uses no operator-supplied query scope, and does not
apply the `OPEN` filter. Missing or ambiguous local scope fails before the
Coinbase order read. The legacy `order_parent.created_at` column is a
PostgreSQL `TIMESTAMP` under the repository's UTC storage convention, so a
driver-returned naive `datetime` is normalized to UTC before building the
documented List Orders `start_date`; an unzoned string is not trusted.

An interrupted cycle is terminal `UNKNOWN` and consumes the single cycle. A
failed, incomplete, schema-invalid, or ineligible result fails closed. It does
not create mutation authority or permit another cycle.

If a persistence callback fails after an SDK boundary was durably entered,
terminal cycle accounting converts every still-`CLAIMED` invoked category or
page to `UNKNOWN`; it never leaves a boundary-entered subrecord looking
pending after the parent cycle becomes terminal.

## Canonical Cancel boundary

Goal 12 adds no second live Cancel endpoint or adapter. Its sole mutation
boundary is:

`POST /api/v1/orders/{client_order_id}/cancel`

The Goal 12 read service exposes no `cancel_exact` method, callable Cancel
runner, or unrouted mutation helper. Removing those parallel helpers is part of
the enforced single-path boundary; neither tests nor later route wiring may
use the Goal 12 service to bypass the existing command route.

The request remains operator-keyed by `client_order_id`. The optional strict
Goal 12 binding carries the exact goal ID, expected revision, evidence
SHA-256, approved-portfolio SHA-256, and the acknowledgement that an unknown
post-boundary result consumes the allowance.

The existing route remains authoritative for authentication, RBAC, operator
intent, payload-bound idempotency, approval, cap/guard decision,
reconciliation proof, audit, manager-owned execution lease, current
Controlled-live service decision, and the canonical Spot Cancel command
service. Goal 12 claims its independent allowance only after that ordinary
route admission is allowed.

Typed recovery cancellation remains governed by its existing recovery case
and plan binding and is not silently reinterpreted as a Goal 12 cancellation.
An unbound canonical Cancel target that is present in the Goal 12 projection
must supply the complete Goal 12 binding; a safe predecessor identity that the
backend reports as absent remains eligible only for its pre-existing generic
backend-authorized surface.

Immediately before the wrapper invokes Coinbase `cancel_orders`, the backend
durably records the prepared SDK marker and then performs one final execution-
authority check. A marker callback failure releases the Goal 12 claim. A typed
failure of that final authority check also restores the canonical and Goal 12
pre-SDK claims because the wrapper proves that `cancel_orders` was not invoked;
the ledger records the marker plus
`sdk_invocation_proven_absent=true`. An accepted, explicitly rejected, or
unknown result after actual SDK invocation consumes the allowance. A process
loss after the durable marker has no typed no-invocation proof, closes the
claim as `UNKNOWN`, and is never retried. The exchange-native order ID remains
ephemeral within the Goal 12 Cancel call, while the Goal 12 ledger retains only
its SHA-256 binding. The pre-existing canonical `order_parent` remains the
backend source of that exchange evidence; Goal 12 does not copy it into its
ledger or expose it to the browser.

## PostgreSQL and replay contract

The separate Goal 12 PostgreSQL ledger stores:

- one singleton goal revision and one-cycle counter;
- immutable actor-, role-, action-, target-, correlation-, intent-, and
  idempotency-bound cycle records;
- separate category and cursor-page claim, actual SDK-boundary, and outcome
  accounting;
- sanitized `ADMIN_MANUAL_ROOT` projections keyed by `client_order_id`;
- a separate immutable Cancel request/result record;
- one exact Cancel claim and SDK-boundary marker; and
- fixed sanitized audit events and evidence hashes.

Same-key replay returns the immutable durable terminal result and never calls
the command service or Coinbase. It is not a byte-for-byte reconstruction of
the original HTTP response: the replay request receives its own unique route
audit ID, while the embedded Goal 12 result retains the original ledger audit
binding. A later filesystem-idempotency replay returns that already recorded
route response without appending another audit event. Changed actor, role set,
action, target, correlation, payload, revision, evidence hash, portfolio hash,
or exchange identity fails closed. The actor-bound mutation-result read
remains available after the mutable singleton advances and makes zero Coinbase
calls.

## Routes

Call-free PostgreSQL readback:

- `GET /api/v1/spot/order-operations`
- `GET /api/v1/spot/order-operations/{client_order_id}`
- `GET /api/v1/spot/order-operations/mutation-results/{request_correlation_id}`

Explicit no-retry reads:

- `POST /api/v1/spot/order-operations/refresh`
- `POST /api/v1/spot/order-operations/{client_order_id}/reconciliation`

Sole exchange mutation:

- `POST /api/v1/orders/{client_order_id}/cancel` with the optional complete
  Goal 12 binding

There is intentionally no
`POST /api/v1/spot/order-operations/{client_order_id}/cancel`.

The call-free detail route also accepts a safe predecessor `client_order_id`
outside Goal 12's canonical UUID domain and returns `found=false`. This is
backend authority for the existing generic Cancel surface; it does not add the
predecessor row to Goal 12 or make it eligible for the Goal 12 allowance.

## Public evidence and privacy

Public readback is limited to fixed diagnostics, call counts and outcomes,
sanitized order fields, backend authority, canonical `client_order_id`,
portfolio and exchange identity hashes, correlations, and audit identity.
Raw Coinbase responses, response bodies, cursors, portfolio UUIDs, secrets,
exception messages, private identifiers, and withheld text are neither
persisted nor returned. Raw exchange order IDs are not copied into the Goal 12
ledger and are never returned by its public contract.

Every R1-R12 and V1-V15 predecessor artifact, identity, hash, allowance, and
call record remains immutable. R8 content and its hash remain inaccessible and
were not read, recomputed, compared, copied, displayed, or logged for this
goal.

## `origin/prod` translation

The implementation review inspected:

- `origin/prod:dashboard_server.py`;
- `origin/prod:external/coinbase_client.py`;
- `origin/prod:database/order.py`;
- `origin/prod:database/order_dashboard_helpers.py`;
- `origin/prod:core/order_engine.py`; and
- related legacy order, dashboard, cancellation, and reconciliation tests.

Accepted concepts were `client_order_id` as operator identity, durable local
order ownership and hierarchy, order inventory, and exact exchange-side
evidence for cancellation. Rejected concepts were WebSocket/browser mutation
authority, passing a client ID as an exchange order ID, generic or batch
Cancel, inferred ownership, background cancellation, retry/fallback behavior,
parallel exchange adapters, and raw exception/response exposure.

The current Admin API, generated contract, PostgreSQL claims, existing route
admission, and canonical Spot command service—not the legacy dashboard—are
product authority.

## Validation and live-proof stop

The terminal implementation/validation checkpoint passed:

- 242 focused consolidated backend tests;
- the canonical backend regression with 1,294 passed and 6 skipped in the
  parallel lane, followed by 920 passed, 150 skipped, and 1,300 deselected in
  the serial lane;
- 1,829 frontend unit/component tests;
- 33 full authenticated frontend E2E tests; and
- independent safety and blind-contextless audits, including the final
  remediation-delta review.

All of that evidence is synthetic or local. It consumed zero Coinbase calls,
zero truth cycles, and zero exact Cancel allowances. Every immutable
predecessor boundary remains unchanged, and R8 content and its hash remained
inaccessible.

The installed deployment check and persistent Controlled-live status
verification pass. Runtime execution authority is armed, while no current
service decision or eligible path exists and deployment validation records
zero Coinbase execution and zero notional. The truth-cycle and Cancel
allowances remain unconsumed unless an independently authorized operator
action actually spends them. An eligible Cancel must not be invented merely
to consume the authorization.
