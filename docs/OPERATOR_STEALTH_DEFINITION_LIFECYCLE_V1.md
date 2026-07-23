# Operator Stealth Definition Lifecycle V1

Goal `operator_stealth_definition_lifecycle_v1` translates the legacy stealth
create, cancel, export, import, clear, threshold, and target-movement handlers
into a normal authenticated operator workflow without restoring their implicit
runtime or exchange authority.

## Scope

The routed Admin UI can list, filter, page, and inspect local stealth
definitions and their command/event history. An actor with `config:update` can
explicitly:

- create one unrevealed definition;
- edit the allowlisted terms of one current draft revision;
- cancel one exact draft revision;
- clear an exact selected set of eligible drafts;
- export an exact selected set as
  `operator-stealth-definition/v1`;
- durably preview a schema-validated import; and
- apply the exact, unchanged, all-valid preview once.

Reads require `analytics:read`. Every command requires its action-specific
`X-Operator-Intent`, a correlation ID, an idempotency key, a bounded operator
reason, a literal confirmation, and any applicable exact revision or manifest
hash.

This goal creates no canonical runtime stealth order, invokes no evaluator,
bridge, `StealthOrderManager`, Coinbase SDK, or exchange adapter, grants no
trading authority, and records exactly zero Coinbase calls and zero exchange
mutations.

## Backend authority and persistence

PostgreSQL owns definition identity, revision, lifecycle, approved Test
portfolio scope hash, admitted Product Catalog revision and snapshot hash,
commands, events, import previews, result snapshots, and restart recovery.
The public contract never returns the configured portfolio UUID or operator
reason; it exposes fixed public-safe actor/correlation evidence and hashes
instead.

Definitions are fixed-size, post-only records. The backend validates the
product against the active approved Product Catalog revision and validates the
condition-specific fields:

- `PRICE` requires a positive threshold and `ABOVE` or `BELOW`, with no delay.
- `TIME_DELAY` requires a bounded delay, no threshold or direction, and zero
  hold duration.

Accepted idempotency replays return the exact stored result snapshot. A changed
payload under a used key conflicts. Startup terminalizes abandoned
in-progress commands; it does not replay them.

The canonical `stealth_orders` table has a database trigger that shares one
transaction-scoped advisory identity lock with every local definition check.
This covers all existing runtime insert paths rather than relying on each
manager or legacy writer to opt in. For a concurrent local create and runtime
insert, exactly one identity can commit: the runtime trigger rejects a UUID
already reserved by a local definition, while the local command rejects a
runtime UUID that committed first. Local edit/cancel/clear/export/import
operations hold the same identity lock through commit.

## Runtime interlock

The definition UUID reserves the future canonical `stealth_order_id`. Before
every local mutation, export, and import apply, the repository locks and checks
the canonical `stealth_orders` row:

| Canonical runtime evidence | Classification | Local action |
| --- | --- | --- |
| No matching row | `UNMATERIALIZED` | Allow only lifecycle-permitted local actions |
| `HIDDEN`, `PENDING`, or `TRIGGERED` | `ACTIVE` | Fail closed; route to reveal/closeout |
| `REVEALED` | `REVEALED` | Fail closed; route to movement/repricing |
| `EXECUTED` or `CANCELLED` | `TERMINAL` | Fail closed; route to reveal/closeout evidence |
| Runtime evidence unavailable or unknown | `UNKNOWN` | Fail closed |

Local cancellation or clearing does not reinterpret a never-materialized
definition as a runtime terminal order. Conversely, no active, revealed, or
terminal runtime placement can be edited, cancelled, cleared, exported, or
re-imported through this lifecycle.

## Import and export

Export is an audited, exact-set, versioned projection with a canonical
manifest SHA-256. Import preview validates the complete allowlisted schema,
identity uniqueness, condition fields, Product Catalog admission, and runtime
interlock before persisting only fixed per-item diagnostics. Apply requires the
same preview identity and manifest hash, requires every item to remain valid,
revalidates the currently configured approved-portfolio hash, claims the
preview exactly once, and creates one audited definition per item in one
transaction. A portfolio change after preview fails closed without applying
the preview.

The browser does not infer that apply succeeded. It re-reads the durable
preview and requires the same preview identity and manifest hash, state
`APPLIED`, a persisted apply timestamp, and durable imported-definition
readback for every exact identity, revision, definition hash, source-preview
link, and import event. Clear and export likewise require every selected
definition and event to match durable readback. Unknown or unverifiable command
outcomes persist a browser safety quarantine across refresh/remount. It can be
cleared only after the matching correlation and idempotency key appear as one
terminal backend command and the operator explicitly acknowledges that
reconciliation.

## Legacy comparison

Historical source material:

- `origin/prod:dashboard_server.py` stealth create, cancel, export, import,
  clear, threshold, and target-movement handlers;
- `origin/prod:core/stealth_order_manager.py`; and
- `origin/prod:database/order.py`.

The new path does not restore dashboard WebSocket authority, browser-owned
state, immediate evaluator eligibility, broad physical deletion, raw exception
display, or filesystem import/export durability.

## Validation

Focused coverage includes pure policy, PostgreSQL repository and restart
behavior, service/RBAC/routes, generated OpenAPI and route inventory, strict
browser validation, import preview/apply durable readback, mutation freeze,
installed feature startup, and an authenticated real-PostgreSQL Playwright
workflow. Full backend/frontend, installed deployment, safety, and
blind-contextless gates are required before closeout.
