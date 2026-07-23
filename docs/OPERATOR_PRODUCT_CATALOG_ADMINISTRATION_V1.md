# Operator Product Catalog Administration V1

Goal `operator_product_catalog_administration_v1` is independent Goal 3 of
the authorized eleven-goal sequence.

## Operator outcome

An authenticated, `config:update`-authorized operator can use the routed
Admin UI Product Administration workspace to:

- inspect backend-paginated immutable catalog revisions;
- review each product as `ADDED`, `CHANGED`, `REMOVED`, `UNCHANGED`,
  `LIFECYCLE_CHANGED`, or `ROLLBACK_RESTORED`;
- explicitly claim one bounded, no-retry logical Coinbase List Products read;
- approve one exact proposed revision by revision number and snapshot SHA-256;
- enable, disable, or retire one exact product in the active administrative
  catalog; and
- restore one reviewed historical snapshot as a new rollback revision.

Catalog lifecycle is administrative metadata. It does not edit the installed
Spot or Futures product policy, approve a portfolio, satisfy wallet/admission
checks, grant trading authority, or authorize an exchange mutation.

## Historical source translation

The current implementation inspected these `origin/prod` references as
historical behavior:

- `dashboard_server.py::update_products_json_from_api`;
- `configuration.py::rest_get_products`;
- `external/coinbase_client.py`; and
- `core/models.py::Product`.

The useful behavior was the ability to retrieve and classify product metadata.
The current implementation does not copy the legacy dashboard WebSocket or
rewrite `products.json`. It translates catalog refresh into an authenticated
Admin API command, strict allowlisted normalization, immutable PostgreSQL
revision review, explicit approval, lifecycle control, rollback, and audit
readback.

## Backend routes

Call-free PostgreSQL reads:

- `GET /api/v1/product-catalog`
- `GET /api/v1/product-catalog/revisions/{revision_id}`

Explicit commands:

- `POST /api/v1/product-catalog/refresh`
- `POST /api/v1/product-catalog/revisions/{revision_id}/approve`
- `POST /api/v1/product-catalog/products/{product_id}/enable`
- `POST /api/v1/product-catalog/products/{product_id}/disable`
- `POST /api/v1/product-catalog/products/{product_id}/retire`
- `POST /api/v1/product-catalog/revisions/{target_revision_id}/rollback`

Reads require backend `analytics:read`; commands require backend
`config:update`. Every command requires an exact `X-Operator-Intent`,
idempotency key, correlation ID, bounded operator reason, and action-specific
literal acknowledgement. Browser visibility is not authority.

## PostgreSQL durability

`database/operator_product_catalog.py` owns:

- one goal-global ledger capped at ten refresh cycles and ten logical reads;
- refresh cycles and page-level claims;
- durable returned, incomplete, not-returned, and unknown read states;
- immutable catalog revisions and revision products;
- one active-revision pointer;
- idempotent command claims and result revision binding; and
- fixed sanitized audit events.

The installed runner initializes and recovers the schema before accepting
traffic when
`COINBASE_ADMIN_API_OPERATOR_PRODUCT_CATALOG_ENABLED=1`. The controlled-live
review manager installs that exact flag. Schema startup idempotently upgrades
the pre-rejection command table with the sanitized diagnostic column and
terminal `REJECTED` state before recovery. Startup converts a claimed page to an
unknown terminal state without replaying it. A refresh interrupted before its
first page call becomes terminal not-returned. A refresh interrupted after one
or more pages returned but before revision creation becomes terminal
returned-incomplete. All recovery paths append a fixed audit event and close
the command claim.

Terminal idempotency replay is call-free. Replaying a failed or unknown refresh
key can never re-enter List Products. Successful local command replay returns
the original revision with `status=replayed` and
`local_state_mutated=false`. Rejected local approval, lifecycle, and rollback
commands are also durably claimed by actor, hashed reason, acknowledgement, and
exact command fields. Their fixed rejection classification and correlation are
available through paginated operator event readback, and replay cannot silently
re-evaluate a different command. Event pages use timestamp plus event identity
ordering so equal transaction timestamps cannot duplicate or omit evidence
across offsets.

## Catalog read boundary

One refresh cycle may call the canonical
`CoinbaseRestClient.get_product_catalog_page` once per required cursor page.
There is no page retry. A page claim is committed before invocation, a returned
marker is committed immediately after the SDK method returns, and only then is
the response normalized.

Only documented, stable metadata fields survive normalization: product and
currency identity, increments, minimums/maximums, display name, exchange
status, documented restrictions, and local lifecycle. Raw responses, response
bodies, cursors, portfolio identifiers, market prices, extension fields,
exception messages, secrets, and private identifiers are neither persisted
nor returned. Cursor evidence is a SHA-256 digest only.

The source snapshot preserves reviewed lifecycle for existing products, puts
new products in `PENDING`, and marks products missing from a refresh
`RETIRED`. Approval makes the reviewed revision active. Lifecycle changes and
rollback create new immutable revisions rather than editing prior rows.
Approval, lifecycle, and rollback recompute the stored revision snapshot digest
before mutation and fail closed if persisted product rows no longer match the
reviewed hash.

## Frontend authority boundary

The frontend uses generated OpenAPI types and the canonical
`BackendApiClient`. It strictly binds revision and event pagination to the
requested offsets and fixed page size, renders all goal-global refresh cycles
plus paginated fixed command events, and uses dedicated active-revision
readback even when an operator is viewing a historical page. It renders exact
revision and product diffs, allowed actions, goal budget, fixed events, and
correlation evidence. It forwards explicit operator intent only.

Any transport/server outcome, or any successful response that does not
strictly bind action, permission, correlation, idempotency, revision, read
state, action-specific identity and lineage, zero exchange mutation, and zero
notional freezes further mutations in that page session. After acceptance, the
page verifies the full durable revision evidence and exact lifecycle
postcondition before reporting success. It never retries a command
automatically.

## Live-call accounting

Goal 3 authorizes at most ten independent refresh cycles, but validation,
deployment, page loading, and ordinary navigation invoke no Coinbase endpoint.
Approval, lifecycle changes, and rollback are PostgreSQL-only. The goal permits
zero exchange mutation.
