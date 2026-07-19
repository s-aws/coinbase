# Operator Read Models

Operator read models are backend-owned Admin API responses that help humans and
agents inspect trading state without creating command authority. They are
evidence surfaces only: a browser, BFF, dashboard panel, or contextless agent
must not treat a read model as permission to place, cancel, repair, roll back,
or reconcile exchange state.

## Current Surfaces

- Spot readiness, sweep status, P/L, cost basis, campaign status, direct-order
  audit, recovery preview, recovery apply-review, recovery rollback-plan,
  recovery reconciliation-proof, and command-suite reads live under
  `GET /api/v1/spot/*`.
- Order, stealth, movement/repricing, futures/perpetuals, guard/risk policy,
  audit workbench, recovery-gate, fill-ledger health, and reconciliation-plan
  reads expose cross-module evidence under their Admin API namespaces.
- P/L checkpoint record routes are local-state review records. Their readbacks
  can link to audit, recovery, and reconciliation evidence, but those links are
  not recovery execution, reconciliation execution, Coinbase calls, or sell
  authority.

## Follow-up Operations Queue

`GET /api/v1/follow-up-operations` is the routed operator index for attached
follow-up intents. The backend applies the optional `product_id`, `state`, and
`actionability` filters, deterministic ordering, `limit`, and `offset` inside
one local PostgreSQL snapshot before pagination. The query starts from durable
intents, so missing or inconsistent joins are classified as blocked rather
than silently removed. Its evidence aggregates are limited to sources that
have attached intents. The same statement bulk-projects the latest local
live-proof record for each of the four bounded operation kinds on every page
item. It never calls the single-intent operation-set reader once per item, so
the queue has no N+1 journal-read path.

Every row uses `source_client_order_id` for Orders-detail navigation and
returns durable source/root/intent/optional-child identity, fixed reason and
blocker codes, attempt state, Create/Cancel allowance consumption, audit
correlation, and timestamps. `review_navigation_available` identifies a local
review page. `actor_authorized` independently reports whether the authenticated actor has
the required `order:create` or `order:cancel` permission. `actionable` is true
only when both are true. None of these fields is live eligibility. Any later
materialization or exact-child safe-closeout POST must perform its own fresh
backend revalidation, authority, idempotency, cap, audit, reconciliation, and
single-call checks.

The local attempt classification is exhaustive. The two numeric columns below
are durable allowance-consumption counts, not observations that an SDK or
transport boundary was reached:

| Durable evidence | Queue state | Review navigation | Create / Cancel allowance consumption |
| --- | --- | --- | --- |
| no attempt; full fill and local Spot/Test lineage consistent | `ready_for_materialization_authorization` | `materialization_review` | `0 / 0` |
| no attempt; source not fully filled | `awaiting_source_fill` | `none` | `0 / 0` |
| no attempt; terminal, unknown, inconsistent, or unproven product scope | `blocked` | `none` | `0 / 0` |
| `KNOWN_NOT_INVOKED` | `materialization_in_progress` | `none` | `0 / 0` |
| `CREATE_INVOCATION_STARTED` | `unknown_outcome` | `safe_closeout_review` | `1 / 0` |
| `CREATE_EXPLICITLY_REJECTED` | `blocked` | `none` | `1 / 0` |
| `CREATE_ACCEPTED_NONTERMINAL` | `materialized_active` | `safe_closeout_review` | `1 / 0` |
| `CREATE_ACCEPTED_TERMINAL` | `materialized_terminal` | `none` | `1 / 0` |
| `CREATE_UNKNOWN_CONSUMED`; the exact durable Create terminal proves `UNKNOWN` with `POSSIBLY_SUBMITTED` transport and unknown exchange/read accounting | `unknown_outcome` | `safe_closeout_review` | `1 / 0` |
| `CREATE_UNKNOWN_CONSUMED`; the exact durable Create terminal proves pre-SDK `BLOCKED` / `NOT_INVOKED` / `NOT_SUBMITTED` / `NOT_MUTATED` with exact zero reads | `blocked` | `none` | `1 / 0` |
| `CREATE_UNKNOWN_CONSUMED`; the required Create terminal or its identity/accounting proof is absent, partial, or inconsistent | fail-closed `blocked`, or the queue is unavailable before an unsafe projection can be returned | `none` | `1 / 0` |
| `CANCEL_INVOCATION_STARTED` | `unknown_outcome` | `none` | `1 / 1` |
| `CANCEL_NOT_REQUIRED_TERMINAL` | `materialized_terminal` | `none` | `1 / 0` |
| `CANCEL_EXPLICITLY_REJECTED` | `materialized_active` | `none` | `1 / 1` |
| `CANCEL_ACCEPTED_NONTERMINAL` | `materialized_active` | `none` | `1 / 1` |
| `CANCEL_ACCEPTED_TERMINAL` | `materialized_terminal` | `none` | `1 / 1` |
| `CANCEL_UNKNOWN_CONSUMED` | `unknown_outcome` | `none` | `1 / 1` |

`CREATE_UNKNOWN_CONSUMED` records only that the one-use Create allowance is
consumed; the attempt state alone never grants safe-closeout review. That
review requires the identity-bound durable Create slot to be terminal with
outcome `UNKNOWN`, zero individual retries, SDK state `INVOKED` or `UNKNOWN`,
transport state `POSSIBLY_SUBMITTED`, exchange state `UNKNOWN`, and unknown
read accounting with no fabricated count. A contract-valid conservative
legacy projection may supply that tuple only under the all-null rule described
below. An exact terminal `BLOCKED` proof with `NOT_INVOKED`, `NOT_SUBMITTED`,
`NOT_MUTATED`, and exact zero reads is instead blocked with no action even
though the allowance count remains `1`. Missing, misbound, nonterminal,
partially explicit, or contradictory proof fails closed as blocked/unproven or
makes the queue unavailable; it never becomes safe-closeout navigation.

Every queue response has a top-level `current_request_activity` with
`NOT_INVOKED`, `NOT_SUBMITTED`, `NOT_MUTATED`, `EXACT`, and an observed read
count of `0`. That is the activity of this passive HTTP request, not a summary
of an older attempt. Each item separately exposes
`durable_live_proof_activity` with named `eligibility_read`, `create`,
`reconciliation_read`, and `cancel` slots. A present slot reports its journal
event state and outcome, retry count, evidence origin, SDK mutation-invocation
state, transport-submission state, exchange-mutation state, and exact or
unknown read accounting. It exposes no raw exchange response, private
identifier, idempotency value, or withheld exception text.

Canonical `create_allowance_consumption_count` /
`create_allowance_consumed` and their Cancel counterparts describe the durable
one-use budget. The older `create_call_*` and `cancel_call_*` queue fields are
deprecated compatibility names for the same allowance consumption; they are
not authoritative observed-call counters. Observed activity comes only from
the typed current-request and durable-operation activity objects.

New journal events use an explicit five-field accounting tuple. An older row
may receive `conservative_legacy_projection` only when every explicit
accounting column is null. If even one explicit field is present, the complete
tuple and its exact/unknown read-count invariant must validate; partial or
incoherent explicit evidence fails the entire queue read closed with the fixed
unavailable classification. Slot kind and source, root, intent,
materialization, and child bindings are also validated before readback.

Configured Spot-product scope gates only a new, no-attempt materialization
review. Once a durable attempt exists, later local catalog drift cannot hide
its immutable allowance accounting or the exact-child risk-reduction review.
The fresh detail action remains authoritative about whether any Cancel is
allowed.
The response explicitly reports `read_only=true`, `local_sql_only=true`,
`local_state_mutated=false`, zero Coinbase reads/Create/Cancel calls, and no
exchange mutation.

Materialization command responses separate request receipts from durable
operation evidence. Top-level `correlation_id` and `audit_id` identify the
current HTTP request and receipt. Nested attempt fields preserve the stable
operation correlation/audit binding, so a same-operation replay may have new
top-level trace values without changing the durable operation identity.
Materialization read, Create, and safe-closeout responses also expose the same
`current_request_activity` / `durable_live_proof_activity` split. A replay has
exact-zero current activity while retaining the original durable journal and
allowance consumption; it never appears to invoke or submit again.

Follow-up mutation failures use the specialized
`AdminOrderFollowUpMaterializationErrorResponse`. It adds sanitized
current-request activity to the normal fixed error envelope. A failure proven
before the SDK boundary reports exact zero; an incomplete boundary reports
typed unknown/possible activity rather than fabricated calls or submissions.
Raw SDK responses, exception text, private identifiers, and journal internals
are never reflected.

The implementation compared current-main
`database/order.py::get_parent_orders_page` with the historical
`origin/prod:dashboard_server.py` `request_parent_orders` read. It retained the
useful operator list/read concept but not the legacy WebSocket, unpaginated
whole-table load, browser-keyed dictionary authority, or reflected exception
text. The Admin API contract and local PostgreSQL repository are the only
current authorities.

## Runtime Read Posture And Identifier Privacy

`controlled-live` is the default installed operator-review runtime posture;
`no-live` is an explicit-only alternate. Manager startup, status, health, and
session probes are local and call-free. Ordinary authenticated UI bootstrap
and refresh are call-free in both postures: account-management, wallet,
product, fee, Spot readiness, and every Futures read model use only local
sanitized evidence or a fixed unavailable/source-disabled classification.
Merely loading or refreshing a page never invokes Coinbase.

`controlled-live` makes only the installed, route-specific operator actions
eligible for their backend authority chains. A fresh wallet, product, order,
fill, portfolio, or market read may occur only inside an explicit action whose
RBAC, operator acknowledgement, idempotency, scope, cap, audit,
reconciliation, and per-action authorization have passed. It does not donate
read authority to ordinary GET routes. Futures account, position, risk-proof,
command-suite, and fill-readback UI surfaces remain local and source-disabled;
they never refresh Futures positions or margin/collateral from Coinbase.

Concrete Coinbase portfolio UUIDs remain backend-only enforcement inputs. The
backend retains exact credential/catalog bindings only inside explicit
authorized action boundaries and never reflects them into ordinary read
models. Public local evidence shows withheld identifiers and safe fixed
classifications; raw position, margin, wallet, product, fee, order, and fill
envelopes are never exposed. Action failures expose fixed value-blind
classifications only; exception text and response extensions are never
reflected into the Admin API.

## Spot Recovery Contracts

The Spot recovery routes are read-only operator models for recovery triage:

- `GET /api/v1/spot/recovery/preview`
- `GET /api/v1/spot/recovery/apply-review`
- `GET /api/v1/spot/recovery/rollback-plan`
- `GET /api/v1/spot/recovery/reconciliation-proof`

The preview route aggregates direct-order audit, recovery-gate, and
fill-ledger health evidence into candidate rows keyed by `client_order_id`
when a candidate identity exists. The apply-review, rollback-plan, and
reconciliation-proof routes expose gate dependencies, rollback prerequisites,
and required proof fields for those same client-order-id candidates. The
reconciliation-proof route also reads guarded post-apply completion evidence:
`persisted_completion_count`, `persisted_completions`, `latest_completion_id`,
post-apply satisfied/completed counts, and the fail-closed reconciliation
execution boundary: `reconciliation_execution_boundary_available`,
`reconciliation_execution_boundary_count`,
`reconciliation_execution_boundaries`, and
`latest_reconciliation_execution_boundary_id`. Completion fields prove only
that a backend-owned local completion record exists. Boundary fields prove
only that execution authority is still blocked. Each boundary row now names
the disabled command route
`POST /api/v1/spot/recovery/reconciliation-executions` and service method
`execute_spot_recovery_reconciliation`, but those are fail-closed boundary
contracts only. The backend reconciliation executor, live Coinbase read
authority, and exact input chain remain blockers. Local snapshot records are
no-live evidence and do not prove live Coinbase state. Neither completion
fields nor boundary fields prove reconciliation execution or exchange-state
mutation.
Within each boundary row, `action_class` and `required_permission` describe
the disabled command route, while `future_action_class` and
`future_required_permission` preserve the executor posture for generated
clients and contextless reviews.

The recovery read-contract routes do not:

- apply repair rows
- roll back state
- write reconciliation proof records
- execute reconciliation
- mutate order or exchange state
- read from Coinbase
- place or cancel Coinbase orders
- authorize browser recovery
- authorize BFF recovery

Each route reports this boundary through `read_only`, `backend_owned`,
`live_coinbase_orders_ran`, `live_coinbase_read_ran`,
`submitted_notional_usdc`, `executed_notional_usdc`, `browser_authority`, and
`bff_authority` fields. A consumer should render those fields as evidence, not
recompute or override them.

## Maintenance Rules

- Add a read model only through the backend Admin API contract and route
  inventory.
- Keep `docs/plans/ADMIN_API_ROUTE_INVENTORY.md`, generated OpenAPI artifacts,
  examples, and frontend generated schema in sync with route changes.
- Use `client_order_id` for internal order identity. Exchange ids are evidence
  only unless an exchange endpoint explicitly requires them.
- Do not copy spot wallet, no-shorting, cost-basis, or average-cost rules into
  non-spot read models.
- Add focused tests for dangerous boundaries before exposing a read model to
  the frontend.
