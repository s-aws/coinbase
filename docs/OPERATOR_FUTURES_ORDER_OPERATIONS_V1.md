# Operator Futures Order Operations V1

Goal ID:
`operator_futures_order_inventory_detail_cancel_reconcile_v1`.

## Operator outcome

An authenticated operator can use the routed Admin UI to:

- list and filter durable Default-profile Futures orders;
- open one detail page by `client_order_id`;
- explicitly refresh the order catalog;
- explicitly reconcile one exact order; and
- invoke at most one exact Cancel after a fresh `OPEN` observation.

Ordinary page load reads PostgreSQL and makes zero Coinbase calls.

## Official contract

Coinbase Advanced Trade
[List Orders](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/list-orders)
documents `product_type=FUTURE`, order status/type/time-in-force fields,
`client_order_id`, `order_id`, `has_next`, and cursor pagination. For CDP keys,
`retail_portfolio_id` is deprecated and the key's permissioned portfolio is
used. The implementation proves the credential-bound portfolio is exactly the
Default profile before listing orders.

Refresh uses only the documented `OPEN` status filter. It inventories current
cancellation candidates instead of walking an unbounded terminal-order
history. Pending, queued, unknown, and terminal transitions are not inferred
from this refresh; exact reconciliation and Cancel remain status-complete. The
backend reads the selected durable projection first, then scopes the same
single logical List Orders category to that backend-owned product and inclusive
creation timestamp without an order-status filter. The UI cannot supply or
override these filters. If either durable product or normalized creation time
is absent, the exact cycle ends locally as
`operator_futures_orders_exact_catalog_scope_incomplete` before any Coinbase
read.

After a successful refresh, any prior durable projection absent from the
returned `OPEN` catalog has `authoritatively_nonterminal` and
`cancel_eligible` revoked. The row is retained as last-observed history rather
than deleted or assigned an inferred terminal status, and its `observed_at`
continues to identify when Coinbase last reported that status. The operator
inventory displays this timestamp. Only an exact Reconcile or Cancel action
may acquire newer terminal or indeterminate truth for that routed
`client_order_id`.

The 100-page fail-closed ceiling remains unchanged. Cycle 4 reached that
ceiling while reading the unfiltered historical Futures catalog, returned only
`operator_futures_orders_futures_order_catalog_page_limit_exceeded`, and left
Cancel `NOT_RUN`. Current official documentation still describes
`product_type`, `order_status`, `product_ids`, inclusive `start_date`,
`has_next`, and `cursor`; no maintenance-specific contract change was
documented. Cycle 5 then tested the documented multi-status plus `end_date`
profile exactly once and received only the fixed
`operator_futures_orders_futures_order_catalog_http_client_error`
classification. It made no retry and left Cancel `NOT_RUN`. Because the
withheld response cannot safely attribute the 4xx to one parameter, the
successor uses the minimal documented and legacy-proven `OPEN` refresh and
omits the optional `end_date`. Exact actions retain product and inclusive
creation-time scope. The correction does not raise page or call ceilings.

The documented
`UNKNOWN_ORDER_STATUS` value remains visible in inventory but is neither
authoritatively nonterminal nor Cancel-eligible. This preserves truthful
readback during an indeterminate or maintenance-adjacent exchange state
without converting uncertainty into mutation authority. An exact Cancel
attempt against that projection terminates locally as
`operator_futures_order_exact_order_status_unknown`; it is not mislabeled as
a terminal exchange order and never claims the Cancel allowance.

Catalog schema failures use fixed, value-blind boundary diagnostics for the
response envelope, order collection/mapping, required identities, documented
enum fields, and pagination state. No rejected value is interpolated or
retained. This lets a later bounded cycle distinguish a documented
compatibility change from a malformed response without inspecting, persisting,
or reconstructing raw Coinbase evidence.

If Coinbase returns a nonempty order type outside the currently documented
enum, the backend stores only the documented `UNKNOWN_ORDER_TYPE` fallback and
marks that exact projection non-cancelable. The undocumented value is neither
persisted nor displayed. A Cancel cycle that encounters this degraded
projection terminates locally as
`operator_futures_order_exact_order_type_unknown` with the Cancel allowance
unclaimed.

[Cancel Orders](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/cancel-order)
accepts exchange `order_ids` and returns one result with `success`,
`failure_reason`, and `order_id`. The UI therefore never supplies a Coinbase
order ID. The backend resolves one raw ID from the same fresh catalog,
compares its SHA-256 binding, uses it only for the immediate call, and discards
it afterward.

The pinned SDK remains `coinbase-advanced-py==1.8.4`. The canonical wrapper
uses `list_orders` and `cancel_orders` with bounded transport and no retry.

## Backend routes

- `GET /api/v1/futures/order-operations`
- `GET /api/v1/futures/order-operations/{client_order_id}`
- `GET /api/v1/futures/order-operations/mutation-results/{request_correlation_id}`
- `POST /api/v1/futures/order-operations/refresh`
- `POST /api/v1/futures/order-operations/{client_order_id}/reconciliation`
- `POST /api/v1/futures/order-operations/{client_order_id}/cancel`

The historical generic
`POST /api/v1/futures/orders/{client_order_id}/cancel` remains a fixed
source-disabled `501` compatibility route. It is not reused or broadened.

## Durable authority

PostgreSQL stores:

- one goal singleton with revision and ten-cycle budget;
- one row per claimed cycle;
- one claim per approved category;
- one claim and boundary state per cursor page;
- sanitized order projections keyed by `client_order_id`;
- one independent single-use Cancel claim; and
- fixed audit events.

The three approved read categories are:

1. API-key permissions;
2. Default-profile portfolio catalog; and
3. one logical `product_type=FUTURE` order catalog.

Each category is claimed at most once per cycle. Each cursor page is claimed,
marked immediately before its SDK boundary, and returned once. No individual
or page retry exists. A restart with an active read boundary records
`UNKNOWN`. A Cancel restart after the SDK boundary records `UNKNOWN` and
consumes the allowance. A Cancel blocked before that boundary is durably
released with `operator_futures_order_cancel_pre_call_blocked`. The successful
read cycle and its Cancel claim are one fenced transition: no later cycle may
start while the Cancel is claimed, its originating cycle number remains fixed,
and its idempotency result is written once only after a terminal Cancel or
proven no-call result. Restart before claim records
`operator_futures_order_cancel_interrupted_before_claim`.

Cycle idempotency binds actor, normalized roles, correlation, action, exact
target, expected revision, intent, and every acknowledgement. Each completed
cycle stores its own sanitized result snapshot, so replay returns the original
result rather than mutable singleton state. A pending replay or a changed
actor, role set, target, or payload fails closed.

Request correlations are unique within the Goal 2 ledger. The authenticated
mutation-result GET resolves only the exact correlation owned by the current
actor and returns pending, absent, or the immutable terminal cycle snapshot
with zero Coinbase calls. This remains queryable after later operators advance
the mutable singleton. Historical terminal snapshots are explicitly
non-actionable: their execution posture is false and their allowed-action list
is empty, so they cannot advertise authority from either their old revision or
the current singleton. A successful Cancel read awaiting its one-use claim is
projected as an active transition with no allowed actions, matching the
database fence. Fixed same-request pre-cycle conflicts remain distinct from
unknown or in-flight results.

Read-only Default credentials may still build an inventory, but every
projection is non-cancelable and the service refuses to claim Cancel unless
the same fresh binding proves `can_trade=true`. Repeated catalog rows are
accepted only when every normalized field and the process-local raw identity
are identical; conflicting status or other duplicate evidence fails closed.

## Sanitized projection

The projection retains only:

- `client_order_id`;
- product, side, status, order type, and time in force;
- sanitized decimal size/price/fill fields;
- exchange timestamps and local observation time;
- SHA-256 of the exchange order ID;
- nonterminal classification; and
- exact `OPEN` Cancel eligibility.

Raw responses, cursors, raw exchange IDs, portfolio UUIDs, secrets, exception
messages, and withheld text are neither persisted nor returned.

## Historical translation

`origin/prod:dashboard_server.py` used `client_order_id` as the operator
tracking identity and exposed order cancellation through a dashboard
WebSocket. It also passed that client ID directly in an `order_ids` request.
`origin/prod:external/coinbase_client.py` exposed list/cancel helpers without
the current durable claims. `origin/prod:configuration.py` and
`origin/prod:core/startup_reconciler.py` used an `OPEN` status filter for
operational order reads. The MVP preserves only the useful tracking,
inventory, and exact-operation concepts. It does not restore WebSocket
authority, direct browser commands, client-ID-as-exchange-ID behavior,
background cancellation, retry, fallback, or raw exception logging.

## Validation

Focused validation includes:

- reader schema, pagination, duplicate identity, and private-data tests;
- canonical Cancel adapter and call-boundary tests;
- PostgreSQL projection, schema-upgrade, replay, restart, and single-use claim
  tests;
- authenticated route, RBAC, legacy-route, OpenAPI, and route-inventory tests;
- generated frontend contract/runtime/workspace/BFF tests; and
- an isolated PostgreSQL no-network E2E covering catalog refresh, exact
  Cancel, and terminal reconciliation.

Synthetic proof is not a live Coinbase proof and consumes no live allowance.
Before dispatch, the frontend writes a session-persistent mutation freeze
shared by the Futures order pages. The freeze includes the exact UUID used for
both idempotency and correlation headers. The UI permits only call-free durable
readback while frozen and clears the freeze only when exact action, target,
revision, request correlation, and terminal backend evidence resolve it.
Intermediate `CLAIMED` or eager `NOT_RUN` readback cannot clear the freeze.
