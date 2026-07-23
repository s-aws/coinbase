# Operator Parent Order Management V1

Goal `operator_parent_order_management_v1` is independent Goal 4 of the
authorized eleven-goal sequence.

## Operator outcome

An authenticated, `config:update`-authorized operator can use the routed
Parent Strategies workspace to:

- list and filter backend-owned definitions with stable pagination;
- review one exact definition, its current revision, dependency projection,
  allowed actions, deletion blockers, and paginated audit history;
- create one active definition for an enabled Spot product in the approved
  Test-portfolio scope;
- edit only its name, target movement, movement type, replacement limit,
  partial-fill policy, and fixed child policy;
- deactivate an exact revision so it cannot be selected for future use; and
- tombstone an exact deactivated revision only when the backend proves the
  parent is unused or terminal and has no active placement, child, unresolved
  claim, or reconciliation requirement.

These are local configuration commands. They grant no trading authority and
make zero Coinbase calls or exchange mutations.

## Historical source translation

The implementation compared current `main` with these `origin/prod`
references:

- `dashboard_server.py::request_parent_orders`;
- `dashboard_server.py::create_parent_order`;
- `dashboard_server.py::update_parent_order`;
- `dashboard_server.py::update_parent_target_movement`;
- `dashboard_server.py::delete_parent_order`; and
- `database/order_dashboard_helpers.py` parent CRUD helpers.

The useful behavior was operator management of target movement, replacement
limits, partial-fill policy, and child strategy fields. The legacy handlers
accepted browser-composed rows, performed broad direct updates and
unconditional deletion, and exposed raw exception text. The current workflow
does not copy those authority boundaries. It uses backend validation,
allowlisted mutations, exact revisions, PostgreSQL command claims, fixed
diagnostics, dependency-aware tombstoning, RBAC, and generated Admin API
contracts.

## Backend routes

Call-free PostgreSQL reads:

- `GET /api/v1/parent-strategies`
- `GET /api/v1/parent-strategies/{strategy_id}`

PostgreSQL-only commands:

- `POST /api/v1/parent-strategies`
- `POST /api/v1/parent-strategies/{strategy_id}/edit`
- `POST /api/v1/parent-strategies/{strategy_id}/deactivate`
- `POST /api/v1/parent-strategies/{strategy_id}/delete`

Reads require `analytics:read`. Commands require `config:update`, an exact
action-specific `X-Operator-Intent`, correlation ID, idempotency key, bounded
operator reason, and literal acknowledgement. Button visibility is not
authority.

## PostgreSQL durability

`database/operator_parent_strategy.py` owns:

- `operator_parent_strategy`, with immutable product, side, reference size,
  reference price, and approved-portfolio hash;
- an allowlisted mutable policy and one-way `ACTIVE`, `DEACTIVATED`, `DELETED`
  lifecycle;
- exact optimistic revisions and a domain-only materialized-root binding;
- `operator_parent_strategy_command`, which durably binds accepted and rejected
  commands to actor, hashed reason, payload digest, correlation, and
  idempotency, and retains the exact accepted result snapshot so a later replay
  cannot be reinterpreted as the strategy's newer state;
- a paginated public command-audit projection covering completed, rejected, and
  restart-terminalized commands without reason text or internal payload hashes;
- `operator_parent_strategy_event`, with an event-type-discriminated public
contract that fixes created child policy, lifecycle transitions, matching
top-level/evidence revisions, active-or-deactivated edit evidence, and
positive materialization counts; and
- restart recovery that terminalizes any interrupted command without
  re-executing it.

Schema initialization is feature-gated by the exact
`COINBASE_ADMIN_API_OPERATOR_PARENT_STRATEGIES_ENABLED=1` value. Both the local
and installed Controlled-live runners initialize the schema before serving
traffic. The review manager installs the exact feature flag in both
Controlled-live and explicitly requested execution-disabled postures.

## Backend authority and deletion

Creation derives a SHA-256 scope from the configured approved Test portfolio;
the raw portfolio UUID is not persisted in the definition. The product must
exist in the exact `operator_product_catalog_administration_v1` active Product
Catalog revision as enabled, online, Spot,
non-disabled, non-cancel-only, and non-view-only. The definition fixes child
orders to `LIMIT`, `GOOD_UNTIL_CANCELLED`, and `post_only=true`. Admission takes
a PostgreSQL share lock against the Goal 3 active pointer and persists the
admitted revision ID and snapshot hash; a concurrent catalog transition cannot
race command commit.

The dependency projection checks the bound root, current root status, children,
semantic claims, follow-up materialization attempts, partial-fill progress, and
the definition's reconciliation flag when those domain tables exist. Missing
dependency tables fail closed for a used definition. Delete takes the same
root advisory transaction lock used by follow-up lineage writers before
rechecking every dependency and committing the soft tombstone. Deletion is
never a physical removal.

The Admin API exposes only fixed diagnostic codes. It does not return raw
database errors, exception messages, secrets, private portfolio identity, or
exchange response material. Every response states
`trading_authority_granted=false`, `exchange_call_count=0`, and
`exchange_mutation_count=0`. Actor evidence uses the same bounded, printable
identity contract at authentication, service, repository, generated OpenAPI,
and browser validation boundaries.

## Frontend authority boundary

The routed `/parent-strategies` workspace uses generated OpenAPI types and the
canonical `BackendApiClient`. It renders backend pagination, lifecycle,
revision, dependency, deletion, and audit evidence. It forwards only explicit
operator intent and allowlisted request fields.

After an accepted command, the page reloads the exact definition and verifies
the durable revision and lifecycle postcondition before reporting success. A
transport error or successful response with unverifiable correlation,
idempotency, identity, revision, lifecycle, or zero-exchange evidence freezes
all further page mutations. HTTP 408, 425, 429, and 5xx results—including the
BFF's fixed upstream-outcome-unknown 502—also freeze the page. It never retries
automatically. The routed view exposes approved-portfolio hash, admitted
catalog revision/hash, accepted and rejected command history, and typed
event actor/time/correlation/evidence readback. Event evidence is accepted
only when its generated event discriminator, exact lifecycle, revision, and
fixed policy literals agree.

## Live-call accounting

Goal 4 authorizes zero Coinbase calls and zero exchange mutations. Page loads,
validation, deployment checks, creation, editing, deactivation, and deletion
are all local PostgreSQL operations.

## Closeout validation

The completed goal passed backend canonical regression
(`1,215 passed, 6 skipped` parallel; `783 passed, 150 skipped` serial),
frontend full regression (`1,655/1,655`), Playwright (`22/22`), generated
contract coverage for `195` paths, the canonical release and installed
deployment gates (`229` deployment-focused tests), and independent safety plus
blind-contextless audits. The canonical gate reported zero live Coinbase
execution and zero notional.

The next independent goal is `operator_stealth_definition_lifecycle_v1`.
