# Admin API

This repository exposes the professional backend API for the separate
enterprise admin platform at `C:\coinbase-frontend`.
Spot is the first complete product module consumed by that platform; it is not
the generic contract shape for every backend feature.
The repository association is documented in
[Frontend Association](docs/FRONTEND_ASSOCIATION.md).
Maintainer handoff for contextless agents starts at
[Maintainer Handoff](docs/MAINTAINER_HANDOFF.md).

## Current Status

The repository now contains an Admin API contract, generated OpenAPI and
route-inventory artifacts, fail-closed auth/RBAC bootstrap, durable JSONL
idempotency/audit stores, structured error payloads, observability headers,
read-only admin diagnostics, order read routes, read-only stealth lifecycle
routes, read-only stealth command-suite readiness evidence, live-disabled
stealth create, reveal, move, cancel, recovery, and reconciliation command contracts, movement/repricing evidence routes, a
live-disabled movement reprice command contract, read-only futures/perpetual
account and position routes, read-only guard/risk policy evidence, read-only
cross-module audit workbench evidence, backend-owned approval, cap/guard,
admission audit, and reconciliation plan record routes, and read-only spot
operator routes. Live-shaped trading command HTTP routes still return
`not_implemented` after auth, permission, idempotency, and audit handling;
they do not submit orders, cancel orders, or call Coinbase.

The generated OpenAPI contract documents the eventual `200` accepted/replayed
command response shape and the current `501` live-disabled response shape.
The current runtime still returns `501` for create, order cancel, stealth
create, stealth reveal, stealth move, stealth cancel, stealth recovery,
stealth reconciliation, movement reprice,
campaign execution, and spot sweep automation
commands because HTTP live execution is not approved. Read routes document
typed `200` payloads plus structured `401` and `403` errors.
Enterprise-readiness evidence also includes structured per-module
`command_gaps` and a top-level `command_gap_count` so unsupported, not
modeled, and live-disabled command paths are visible without relying on
free-form unsupported-action strings. The same readiness payload now includes
M48 `mutation_taxonomy` rows and aggregate counts. Each row maps a command
route or legacy command surface to exactly one backend-owned mutation family
with identity keys, RBAC permission, idempotency, operator intent, approval,
cap/guard, admission audit, reconciliation, and owning service evidence.
Taxonomy rows are read-only evidence; they do not create approval mutation,
route-local execution, live adapters, BFF execution authority, or Coinbase
calls.
M49 adds a backend-owned approval request and decision lifecycle through the
existing append-only approval store. Approval requests, approve/reject
decisions, revocations, and expiry-derived status are typed Admin API
contracts. Approved decisions link the existing resolver-compatible approval
snapshot record, but browser approval remains insufficient for live execution:
cap/guard, admission audit, reconciliation, disabled live service, and live
adapter gates still fail closed.
M50 adds backend-owned cap/guard decision execution records. These records
persist the backend decision envelope that binds route, method, module,
identity, actor, operator intent, payload hash, approval snapshot, admission
audit id, and cap/guard policy refs. They are evidence and resolver input
only; the browser and BFF do not evaluate wallet, margin, profitability,
inventory, account-limit, or spot-specific guard rules.
M51 adds backend-owned admission audit records. These records append exact
resolver-eligible audit proof that binds route, identity, payload hash,
idempotency, actor, operator intent, approval snapshot, expected cap/guard
decision ref, expected reconciliation plan ref, and disabled live-intent
evidence. The writer rejects records that claim live admission is allowed;
browser audit, BFF audit, and the audit row itself remain insufficient for
live execution.
M52 adds backend-owned reconciliation plan records. These records bind the
exact live-shaped route envelope to approval snapshot, admission audit,
cap/guard decision, reconciliation policy, product scope, retained-inventory
requirement, and notional caps. Only `allowed=true` with `status=passed` is
resolver-eligible. The routes do not execute reconciliation, mutate order or
exchange state, submit Coinbase orders, or create browser/BFF reconciliation
authority.
M53 adds one route-bound dry-run pilot adapter for `POST /api/v1/orders`
through the shared `AdminApiCommandService.place_manual_order` method. It is
configured evidence only and remains non-executable. M54 starts the Spot
command-suite with `GET /api/v1/spot/command-suite`, a read-only readiness
contract for manual order placement, cancel by `client_order_id`, spot
campaign execution, and spot sweep automation. The route reports blockers,
missing gate-chain evidence, proof routes for backend approval/audit/cap/
reconciliation records, `readiness_preconditions` copied from live-enablement
evidence, aggregate `readiness_precondition_count`,
`blocking_readiness_precondition_count`, and
`passed_readiness_precondition_count` fields, and frontend/BFF display
boundaries; it does not add live controls or execute Coinbase orders. Proof
routes are derived from `ADMIN_API_ROUTE_INVENTORY` and are local-state
evidence requirements only. They are not browser authorization, BFF execution
authority, live reconciliation execution, or Coinbase calls. The
`POST /api/v1/spot/sweep/automation-runs` command route is keyed by
`sweep_config_id`, requires `spot_sweep:execute`, and returns
`501 not_implemented` until durable scheduler, run-limit, recovery,
reconciliation, and live execution gates pass.
Spot P/L checkpoint records add a separate local-state mutation surface:
`POST /api/v1/spot/pnl/checkpoints`, with read evidence at
`GET /api/v1/spot/pnl/checkpoints` and
`GET /api/v1/spot/pnl/checkpoints/{checkpoint_id}`. Checkpoints are durable
operator-review records sourced from `/api/v1/spot/sweep/pnl`; they do not
submit Coinbase orders, approve sells, prove profitability, execute
reconciliation, or create tax-accounting authority.
When `average_cost_snapshot` is present, the same checkpoint is also the
average-cost review evidence path. Responses expose
`average_cost_reviewed`, `average_cost_review_source`,
`average_cost_review_detail`, and list-level `average_cost_review_count`.
Those fields are review evidence only; they do not make Coinbase average cost
sell authority, profit authority, tax accounting, browser guard evidence, or
Coinbase execution evidence.
Accepted checkpoint records also expose verified append-only Admin API audit
link readback for the local-state mutation through `audit_id`, `audit_linked`,
`audit_source`, `audit_detail`, and list-level `audit_linked_count`. That
link is operator review evidence only; it does not execute recovery,
reconciliation, Coinbase orders, or browser authority.
Accepted checkpoint records also expose read-only recovery-link evidence
through `recovery_linked`, `recovery_source`, `recovery_routes`,
`recovery_detail`, and list-level `recovery_linked_count`. This links the
checkpoint to backend-owned `/api/v1/admin/recovery-gate` and
`/api/v1/admin/fill-ledger-health` reads for triage only; it does not execute
recovery, apply repairs, roll back state, run reconciliation, call Coinbase,
or create browser recovery authority.
The recovery-link fields are response/read-model evidence derived from those
backend reads, not separately persisted recovery state in the checkpoint
ledger.
Accepted checkpoint records also expose read-only reconciliation-plan link
evidence through `reconciliation_linked`, `reconciliation_source`,
`reconciliation_routes`, `reconciliation_detail`, and list-level
`reconciliation_linked_count`. This links the checkpoint read model to
backend-owned `/api/v1/admin/reconciliation/plans` reads for operator triage
only; it does not execute reconciliation, mutate order or exchange state,
apply repairs, roll back state, call Coinbase, or create browser
reconciliation authority. The separate Spot reconciliation workflow remains a
backend-contract-required gap until reconciliation execution exists. Durable
proof persistence is backend-owned local evidence and is not reconciliation
execution.

Spot recovery now has read-only contract evidence routes:
`GET /api/v1/spot/recovery/preview`,
`GET /api/v1/spot/recovery/apply-review`,
`GET /api/v1/spot/recovery/rollback-plan`, and
`GET /api/v1/spot/recovery/reconciliation-proof`. The preview aggregates
recovery-gate, fill-ledger-health, and optional direct-order audit candidates.
The apply-review, rollback-plan, and reconciliation-proof routes expose the
client-order-id candidate identity, gate chain, rollback prerequisites, and
proof-field requirements without adding execution authority. They also expose
read-only state-repair taxonomy, repair targets, pre-apply snapshots, dry-run
repair plans, and completion-state evidence so operators can inspect why a
candidate is blocked or journal-accepted without applying local state changes.
They remove the read-contract gap and can read back guarded backend local
repair-result journals and guarded post-apply reconciliation completion
records. Completion records are append-only backend local evidence created
only after matching proof, apply journal, repair-result, approval, admission
audit, cap/guard, reconciliation-plan, idempotency, operator-intent, and
payload-hash evidence. The reconciliation-proof readback also exposes
fail-closed reconciliation execution boundary rows that name the route-bound
POST contract, required inputs, and remaining blockers. The route
`POST /api/v1/spot/recovery/reconciliation-executions` exists only as a
disabled shared-command-service boundary: it is idempotent, audited, and
RBAC-protected, but it returns rejected evidence until the backend
reconciliation executor and live Coinbase read authority exist. The backend
snapshot record contract exists as no-live local evidence through
`POST /api/v1/spot/recovery/exchange-state-snapshots`; it does not read
Coinbase or prove live exchange truth. Order/exchange-state mutation,
Coinbase reads, Coinbase submissions, and actual reconciliation execution
remain blockers.
Disabled POST contracts exist for recovery apply and rollback; proof POST
contracts persist append-only backend local evidence only after route-bound
approval, admission audit, cap/guard, reconciliation plan, idempotency, and
audit prerequisites match. The snapshot POST contract persists append-only
local snapshot evidence only after the same backend chain plus proof and
completion evidence match. Apply/rollback POST routes may persist guarded
local repair-result evidence when the backend repair guard matches exactly.
Reconciliation-proof POST may also persist a guarded completion record when
the existing proof, apply journal, and repair-result chain matches exactly.
These routes and their execution-boundary readback do not roll back order
state, execute reconciliation, mutate order or exchange state, call Coinbase,
or authorize browser/BFF recovery.

M55 starts the Stealth command-suite with
`GET /api/v1/stealth/command-suite`, a read-only readiness contract for
stealth create, cancel, reveal, move, reprice, recovery, and reconciliation
workflows. The route links live-disabled stealth create, reveal, move, cancel,
recovery, reconciliation, and movement/reprice command routes, reports missing
workflow contracts, and makes exchange-truth
blockers explicit. It does not create stealth orders, reveal orders, cancel
active placements, move/reprice revealed orders, execute reconciliation,
mutate stealth/order/exchange state, read Coinbase, call Coinbase, or grant
browser/BFF command authority.
The per-order stealth detail route
`GET /api/v1/stealth/orders/{stealth_order_id}` also exposes
`active_placement_audit` as local evidence for whether the current stealth row
has an active placement pointer, which mutation families require future
exchange-truth proof, and which contracts are still missing. That audit is not
a Coinbase read, cancel/replace attempt, reconciliation run, lifecycle
mutation, or browser/BFF approval gate.
The same detail route exposes `mutation_claim_audit` as a backend-owned
snapshot of safely observable runtime mutation claims for move and repricing
families. It explains active or unavailable claim state without acquiring,
releasing, or clearing claims, without creating command inputs, and without
granting browser/BFF lifecycle authority.
Stealth mutation-claim snapshot proof evidence is exposed through
`GET /api/v1/stealth/orders/{stealth_order_id}/mutation-claim-proof` and
persisted through
`POST /api/v1/stealth/orders/{stealth_order_id}/mutation-claim-proofs`.
The writer route requires `stealth_mutation_claim:record`, uses path
`stealth_order_id` as the command identity, and persists append-only local
proof evidence only after backend admission prerequisites match. It does not
acquire or release runtime claims, invoke `StealthOrderManager`, read
Coinbase, submit or cancel orders, cancel/replace active placements, execute
reconciliation, mutate order/exchange/lifecycle state, or authorize browser/
BFF proof authority. Move and movement/reprice execution-posture resolution
uses the latest proof for the same `stealth_order_id` and fails closed when
that latest proof is unsafe, stale, or bound to different guarded command
context; older matching proofs are not used to override the latest failed
proof.
Stealth recovery proof evidence is exposed through
`GET /api/v1/stealth/orders/{stealth_order_id}/recovery-proof` and persisted
through `POST /api/v1/stealth/orders/{stealth_order_id}/recovery-proofs`.
The writer route requires `stealth_recovery:record`, uses path
`stealth_order_id` as the command identity, and persists append-only local
proof evidence only after backend admission prerequisites match. It does not
build recovery plans, repair state, roll back state, invoke managers, read
Coinbase, submit or cancel orders, cancel/replace active placements, execute
reconciliation, mutate order/exchange/lifecycle state, or authorize browser/
BFF proof authority. Recovery execution-posture resolution uses the latest
proof for the same `stealth_order_id` and fails closed when that latest proof
is unsafe, stale, or bound to different guarded command context.
Stealth reveal-trigger proof evidence is exposed through
`GET /api/v1/stealth/orders/{stealth_order_id}/reveal-trigger-proof` and
persisted through
`POST /api/v1/stealth/orders/{stealth_order_id}/reveal-trigger-proofs`.
The writer route requires `stealth_reveal_trigger:record`, uses path
`stealth_order_id` as the command identity, and persists append-only local
proof evidence only after backend admission prerequisites match. It does not
evaluate triggers, call `should_trigger_reveal`, call `reveal_order_slice`,
invoke managers, read Coinbase, submit or cancel orders, cancel/replace
active placements, execute reconciliation, mutate order/exchange/lifecycle
state, or authorize browser/BFF proof authority. Reveal execution-posture
resolution uses the latest proof for the same `stealth_order_id` and fails
closed when that latest proof is unsafe, stale, or bound to different guarded
command context.
The same detail route also exposes `reveal_trigger_audit` as local
reveal-condition evidence for the reveal workflow. It reports whether a
condition is present, the condition type/payload when available, missing
trigger-guard contracts, and fail-closed no-live flags. It does not evaluate
triggers, call `should_trigger_reveal`, call `reveal_order_slice`, submit
Coinbase orders, mutate lifecycle state, execute reconciliation, or grant
browser/BFF reveal authority.
The same detail route also exposes `reveal_submission_audit` as read-only
evidence for the future backend reveal submission adapter. It reports the
route, shared service method, manager method, local active-placement evidence,
missing submission/reconciliation contracts, and fail-closed no-live flags. It
does not call `reveal_order_slice`, create active placements, submit or cancel
Coinbase orders, read Coinbase, mutate lifecycle state, execute
reconciliation, or grant browser/BFF reveal authority.
The same detail route also exposes `reveal_reconciliation_audit` as read-only
evidence for the future reveal post-submit reconciliation proof. It reports
required plan/proof posture, local active-placement evidence, read-evidence
routes, missing proof contracts, and fail-closed no-live flags. It does not
read Coinbase, resolve or write proof records, execute reconciliation, mutate
order or lifecycle state, or grant browser/BFF reveal authority.
Active-placement exchange-truth evidence is exposed through
`GET /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proof`
and persisted through
`POST /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-snapshots`
and
`POST /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proofs`.
Those writer routes require `stealth_exchange_truth:record`, use path
`stealth_order_id` as the command identity, and persist append-only local
evidence only after backend admission prerequisites match. They do not read
Coinbase, verify exchange truth, cancel/replace active placements, execute
reconciliation, mutate order/exchange/lifecycle state, or authorize browser/BFF
proof authority.
Stealth create lifecycle-write guard evidence is exposed through
`GET /api/v1/stealth/orders/{stealth_order_id}/lifecycle-write-guard-proof`
and persisted through
`POST /api/v1/stealth/orders/{stealth_order_id}/lifecycle-write-guard-proofs`.
The writer route requires `stealth_lifecycle_write:record`, uses path
`stealth_order_id` as the command identity, and persists append-only local
proof evidence only after backend admission prerequisites match. It does not
invoke `StealthOrderManager`, write `stealth_orders` or `order_parent` rows,
dispatch lifecycle events, submit or read Coinbase, execute reconciliation, or
authorize browser/BFF lifecycle-write authority.
The stealth command-suite `create_lifecycle_write_audit` also includes an
`execution_contract` object for the future create execution boundary. The
live-disabled `POST /api/v1/stealth/orders` response may include the same
evidence as `stealth_lifecycle_execution_contract` with exact command context
present. Both shapes are blocked evidence only: they report required
prerequisites, resolved and missing prerequisites, read-only prerequisite
resolver rows, blockers, accepted/rejected identity keys, and proof that no
manager invocation, row write, Coinbase call, or reconciliation execution ran.
The resolver rows can report local exact-context-bound lookups for approval,
admission audit, cap/guard, reconciliation, and lifecycle-write guard proof
evidence, but they never create proof records, run live service/adapter code,
read Coinbase, execute reconciliation, or grant browser/BFF authority.
The Admin API service method name `create_stealth_order` is a live-disabled
command wrapper. It is intentionally distinct from the legacy dashboard/engine
manager path that can create local stealth lifecycle state.
The same command-suite response now includes `admission_readiness` rows that
bind each stealth command route to the backend-owned evidence required before
execution can ever be considered: approval request/decision, admission audit,
cap/guard decision, reconciliation plan, active-placement exchange truth or
lifecycle-write guard, disabled live adapter, and post-live reconciliation.
Those rows are blocked read evidence only. They do not approve commands,
execute commands, read Coinbase, invoke `StealthOrderManager`,
cancel/replace active placements, execute reconciliation, mutate state, or
grant browser/BFF command authority.
Admission-readiness rows also expose `context_requirements`. Static route
metadata is present, but exact command-envelope fields remain missing:
`stealth_order_id`, `actor_id`, `idempotency_key`, `operator_intent`, and
`payload_hash`. Until those fields come from the backend mutating command
path, resolver lookup and proof resolution remain disabled.
Concrete live-disabled stealth command responses may include
`stealth_admission_context`. That response echo is different from the
read-only command-suite row: the command path has route, identity, actor,
idempotency, operator-intent, and payload-hash context, so resolver/proof
lookup evidence can report that exact context was present. It is still
display evidence only and does not approve admission, enable execution, read
Coinbase, submit/cancel orders, cancel/replace active placements, execute
reconciliation, mutate state, or grant browser/BFF authority.
Non-create live-disabled stealth command responses for reveal, cancel, move,
recovery, reconciliation, and movement/reprice may also include
`stealth_command_execution_contract`. That contract reports exact command
context, common admission prerequisites, command-specific prerequisites such
as reveal-trigger or active-placement exchange truth, disabled live
service/adapter posture, blockers, and no-live/no-write flags. It is response
evidence only: no stealth manager method is invoked, no active placement is
cancelled or replaced, no Coinbase order is submitted/cancelled/read, no
reconciliation runs, and no lifecycle/order/exchange state is mutated.
The disabled live rows also expose route-specific evidence fields such as
`live_execution_service_source`, `live_execution_adapter_source`,
`post_write_reconciliation_route`, `post_write_reconciliation_source`,
`canonical_execution_path`, and `execution_boundary_authority`. These fields
document the backend-owned future handoff; they do not resolve prerequisites,
construct adapters, execute reconciliation, or authorize browser/BFF commands.
Stealth create lifecycle execution contracts expose the same boundary fields
so create and non-create command posture share one disabled execution model.
Both contracts also expose `live_execution_service_contract`, a nested
route-bound projection of the disabled backend live execution service state.
It is produced through the shared backend live-execution helper, reports
`present=true` only as disabled service evidence, and keeps `enabled=false`,
`executable=false`, no live exchange submission, forbidden execution methods,
and display/forward-only browser/BFF authority. It is not a service
implementation, live switch, Coinbase caller, manager path, or BFF execution
grant.
Exact stealth command responses may also expose
`live_execution_intent_contract`, a nested projection of
`admission_decision.live_execution_intent`. It is payload-bound,
idempotency-bound, actor-bound, disabled, and non-executable. Read-only
command-suite rows without exact actor/idempotency/operator-intent/payload-hash
context must not fabricate this object. The intent contract is not live
approval, Coinbase submission, adapter invocation, or browser/BFF authority.
Both create and non-create contracts also expose
`post_write_reconciliation_boundary`, a nested backend-owned evidence object
for the future post-write reconciliation plan/completion handoff. It names
`POST /api/v1/admin/reconciliation/plans`, required missing evidence, command
context binding, and no-run proof flags. It does not record a reconciliation
plan, execute reconciliation, call Coinbase, invoke managers, cancel/replace
active placements, mutate state, or grant browser/BFF authority.
Post-write reconciliation proof evidence is persisted through
`POST /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-proofs`
and read back through
`GET /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-proof`.
Those records are backend-owned append-only evidence for guarded stealth
command families. They can record reviewed plan, journal, and completion
references. A proof record alone does not resolve the
`post_write_reconciliation` prerequisite evidence, call Coinbase, invoke
managers, mutate state, execute reconciliation, or grant browser/BFF authority.
Execution prerequisite resolvers may read proof, execution-journal, and
verification records for exact command context. A safe proof without an
accepted journal reports `no_matching_post_write_execution_journal`; a safe
proof and journal without a verification reports
`no_matching_post_write_reconciliation_verification`; only the exact safe
proof, accepted journal, and verification chain may resolve
`post_write_reconciliation` prerequisite evidence. Live execution service,
adapter, manager, Coinbase, reconciliation execution, cancel/replace, and state
mutation boundaries remain disabled.
Both create and non-create execution contracts also expose
`remaining_execution_blocker_count` and `remaining_execution_blockers`. These
typed rows are derived from the same prerequisite resolver output and disabled
boundary evidence. They remain blocked even when `post_write_reconciliation`
is resolved, and explicitly keep live service, live adapter, manager
invocation, Coinbase submit/cancel/read, active-placement cancel/replace,
reconciliation execution, and lifecycle/order/exchange state mutation blocked.
The `post_write_reconciliation_missing` blocker is omitted only when the exact
safe proof, accepted journal, and verification chain resolves that prerequisite.
The blocker chain is display evidence only and does not create execution,
proof lookup, Coinbase, manager, reconciliation, browser, or BFF authority.
Execution live-readiness backend decision rows also expose ordered resolution
plan steps, missing plan steps, dependency refs, verification gates, and
disabled plan-execution flags. These fields are sequencing evidence for future
backend-owned resolver work only; they are not an executable plan, browser/BFF
resolver, decision writer, live adapter, Coinbase caller, or M55 completion
claim.
The same rows expose `resolution_readiness_items` as a structured readiness
matrix over those plan-step, dependency, and verification-gate strings. Each
item is blocked, unresolved, backend-owned, route-bound, command-context-bound,
no-live, browser `display_only`, BFF `forward_only_no_execution`, and has
`execution_allowed=false` plus `executed=false`.
The rows also expose `resolution_readiness_summary`, a backend-derived
aggregate over that matrix with total/blocked/resolved/type counts,
first-blocking item, missing reasons, summary authority, and disabled
execution/resolver/writer flags. The summary is read-only evidence and must
not become a browser evaluator, decision resolver, plan executor, Coinbase
path, reconciliation executor, or BFF execution authority.
The same rows expose `resolution_handoff`, a backend-derived classification
over the readiness summary. It reports clearance categories, blocked clearance
refs, first clearance evidence, handoff authority, and disabled
resolution/execution/writer flags. `resolution_handoff.clearance_actions`
names the source readiness item type/order, clearance sequence, predecessor
refs, successor refs, backend contract, route, method, service, required
artifact, evidence ref, dependency authority, dependency readiness, action
authority, and disabled execution/resolver/writer flags that would be required
to clear each blocked handoff ref. `clearance_dependency_summary` aggregates
those action rows with blocked/ready/dependency-ready counts, predecessor and
successor edge counts, dependency-blocked refs, clearable refs, terminal refs,
and disabled graph/clearance/resolver/writer/execution flags. The handoff,
action rows, and summary are context for future backend work only; they are
not a resolver, decision writer, live service switch, live adapter, manager
invocation path, Coinbase path, reconciliation executor, state mutation path,
browser authority, or BFF execution authority.
Post-write execution-journal acceptance evidence is persisted through
`POST /api/v1/stealth/orders/{stealth_order_id}/post-write-execution-journals`
and read back through
`GET /api/v1/stealth/orders/{stealth_order_id}/post-write-execution-journals`.
The writer route requires `reconciliation:record`, uses path
`stealth_order_id` as the identity, requires exact guarded command context,
and only accepts a journal when it matches an existing safe post-write proof.
It stores append-only backend evidence only. It does not execute
reconciliation, verify reconciliation, call Coinbase, invoke managers,
cancel/replace active placements, mutate lifecycle/order/exchange state, or
grant browser/BFF authority.
Post-write reconciliation verification evidence is persisted through
`POST /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-verifications`
and read back through
`GET /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-verifications`.
The readback route lists persisted records but counts a verification as
verified only when it matches an exact safe post-write proof plus accepted
execution journal chain. The writer route requires `reconciliation:record`,
uses path `stealth_order_id` as the identity, requires exact guarded command
context, and accepts only the same exact safe chain. It stores append-only
backend evidence only and may participate in resolving only
`post_write_reconciliation` prerequisite evidence as part of the exact safe
proof, accepted journal, and verification chain. It does not execute
reconciliation, call Coinbase, invoke managers, cancel/replace active
placements, mutate lifecycle/order/exchange state, or grant browser/BFF
authority.
Both create and non-create execution contracts also expose
`post_write_completion_verifier_contract`. It is backend-owned and route-bound.
It reports blocked while safe proof, accepted journal, or verification evidence
is missing, and passed only when the exact safe proof, accepted journal, and
verification chain exists. Passed verifier evidence still reports no manager
invocation, Coinbase submit/cancel/read, reconciliation execution,
cancel/replace, lifecycle/order/exchange mutation, browser authority, or BFF
execution authority.
Both contracts also expose `live_execution_adapter_contract`, a nested
route-bound adapter evidence object produced by the shared backend
`build_live_execution_adapter_contract` helper. It names the
`AdminApiCommandService.*` method, route, module id, action class, forbidden
execution methods, and display-only browser/BFF authority while remaining
disabled and non-executable. It is not an adapter implementation, live switch,
Coinbase caller, manager invocation path, or BFF execution grant.
For commands that require active-placement exchange truth, the contract may
resolve that single prerequisite from the existing append-only backend proof
store when a safe same-`stealth_order_id` proof record exists. That resolver
does not verify Coinbase, resolve reveal-trigger or mutation-claim evidence,
resolve recovery/reconciliation proof, approve execution, or grant browser/BFF
authority.
Those exact command responses also expose
`active_placement_exchange_truth_contract`, a nested projection of the same
backend-owned exchange-truth boundary used by command-suite
`exchange_truth_checks`. It may show route, method, mutation family, resolved
local proof id, current read evidence routes, rejected command identities,
missing contracts, and no-live flags. It is display evidence only; it does not
read Coinbase, prove live exchange truth, invoke managers, execute recovery or
reconciliation, mutate state, or grant browser/BFF authority. Create and
reveal command responses leave this nested active-placement prerequisite
contract absent because those exact command drafts do not consume an existing
active placement.
Exact non-create stealth command responses also expose
`command_specific_proof_contracts`, a list of blocked backend-owned proof
routes for the command family. Reveal names the reveal-trigger proof route;
move and movement/reprice name the mutation-claim proof route; recovery names
the recovery-proof route; reconciliation names the reconciliation-proof route;
cancel leaves the list empty because its additional boundaries are
active-placement exchange truth and cancel/replace. These rows are the same
proof-route contract shape used by command-suite reads. They may show route,
method, permission, shared backend method, identity key, and display-only
authority, but they do not record proofs, resolve proof authority through the
frontend, read Coinbase, invoke managers, execute recovery or reconciliation,
mutate state, or grant browser/BFF authority.
Exact non-create stealth command responses also expose
`execution_readiness_stages`, an ordered ledger derived from the same
prerequisite resolver rows. Each stage maps the exact command to its stealth
workflow family, prerequisite, lookup status, next required backend contract,
and display/forward-only authority. The stage ledger is not a second
resolver, live preflight, proof writer, Coinbase verification path, manager
invocation path, reconciliation executor, or state mutation authority.
Stealth create responses expose the same ordered stage pattern on
`stealth_lifecycle_execution_contract.execution_readiness_stages`, derived
from the existing create prerequisite resolver. Those stage rows are
create-lifecycle evidence only: they do not invoke `StealthOrderManager`,
write `stealth_orders` or `order_parent`, dispatch lifecycle events, submit
or read Coinbase orders, execute reconciliation, or authorize browser/BFF
execution.
Exact stealth create and non-create command responses also expose
`execution_candidate`, `execution_preflight`, and
`execution_transition_barrier`. The candidate names the future backend manager
path and unresolved blocker chain, the preflight derives blocked checks from
that candidate, and the transition barrier derives the first blocking check
and clearance order from preflight. All three are backend-owned display
evidence only; they do not invoke managers, call Coinbase, cancel/replace
active placements, execute reconciliation, mutate state, or authorize
browser/BFF execution.
For stealth reconciliation, the same contract may resolve
`reconciliation_proof` from
`GET /api/v1/stealth/orders/{stealth_order_id}/reconciliation-proof` and
`POST /api/v1/stealth/orders/{stealth_order_id}/reconciliation-proofs` proof
records when the latest same-`stealth_order_id` record exactly matches route,
method, service method, actor, operator intent, idempotency key, and payload
hash. The writer requires `stealth_reconciliation:record` and persists
append-only local evidence only. It does not execute reconciliation, invoke
managers, build plans, read Coinbase, submit/cancel orders, cancel/replace
active placements, mutate order/exchange/lifecycle state, or authorize
browser/BFF proof authority.
Stealth cancel/replace proof evidence is exposed through
`GET /api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proof` and
persisted through
`POST /api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proofs`.
The writer requires `stealth_cancel_replace:record`, supports exact guarded
contexts for stealth cancel, stealth move, and movement reprice, and persists
append-only local evidence only. It does not build cancel/replace plans,
invoke managers, read Coinbase, submit/cancel Coinbase orders, cancel or
replace active placements, execute reconciliation, mutate
order/exchange/lifecycle state, or authorize browser/BFF proof authority.
Live-disabled stealth cancel, stealth move, and movement reprice command
responses may resolve only the `cancel_replace_proof` prerequisite from the
latest safe same-`stealth_order_id` proof record when it exactly matches
route, method, service method, actor, operator intent, idempotency key,
payload hash, and mutation family. A resolved proof does not resolve
active-placement exchange truth, mutation claims, live service, live adapter,
or post-write reconciliation. Unsafe latest proof evidence remains
missing/stale and does not fall back to older records.
Those exact command responses also expose
`active_placement_cancel_replace_contract`, a nested projection of the same
backend-owned cancel/replace boundary used by command-suite
`cancel_replace_boundaries`. It may show route, method, mutation family,
resolved local proof ids, rejected command identities, missing contracts, and
no-run flags. It is display evidence only; it does not invoke managers, call
Coinbase, build cancel/replace plans, execute reconciliation, mutate state, or
grant browser/BFF authority.

The legacy dashboard `place_order`, `cancel_order`, and
`place_hotpoint_test_order` WebSocket messages now delegate to
`application.admin_api.command_service.AdminApiCommandService` as compatibility
adapters. New product UI must use the HTTP API contract, not the dashboard
WebSocket.

Mutating HTTP command responses include the current fail-closed live execution
gate decision and M34 route-bound admission decision evidence. M35 persists
that same admission decision in the existing append-only Admin API audit log
and exposes it through the read-only Audit Workbench. M36 adds the
backend-owned append-only approval-store foundation while approval snapshots
remain absent and HTTP live execution remains disabled. M37 adds backend-only
approval snapshot resolver infrastructure over that store without making the
resolver an approval endpoint, browser approval, command authority, or live
execution path. M38 wires existing command admission evidence to that resolver
so a command response can report whether an exact unexpired snapshot was found
without enabling live execution. M39 wires existing command admission evidence
to backend-owned append-only admission audit proof so a command response can
report whether an exact audit event was found. The admission decision binds
the route, method, module id, identity key, identity value, requesting actor,
idempotency key, operator intent, and payload hash to the approval snapshot,
admission audit, cap/guard, and reconciliation blockers before HTTP live
execution can be enabled.
For `POST /api/v1/orders`, the route attaches a stable backend-owned
`client_order_id` before admission when the request omits one. The id is
derived from endpoint, actor, idempotency key, and the payload hash so replay
evidence is stable while the browser still does not create or override order
identity. The command remains live-disabled and returns `501`.

Current read-only HTTP surfaces include:

- `GET /api/v1/admin/bootstrap`
- `GET /api/v1/admin/health`
- `GET /api/v1/admin/session`
- `GET /api/v1/admin/oidc-readiness`
- `GET /api/v1/admin/capabilities`
- `GET /api/v1/admin/csrf`
- `GET /api/v1/admin/live-enablement`
- `GET /api/v1/admin/enterprise-readiness`
- `GET /api/v1/admin/guard-risk-policy`
- `GET /api/v1/admin/audit-workbench`
- `GET /api/v1/admin/release-gate`
- `GET /api/v1/admin/recovery-gate`
- `GET /api/v1/admin/fill-ledger-health`
- `GET /api/v1/admin/frontend-fixtures`
- `GET /api/v1/admin/approvals`
- `GET /api/v1/admin/approvals/requests/{approval_request_id}`
- `GET /api/v1/admin/admission-audits`
- `GET /api/v1/admin/admission-audits/{admission_audit_id}`
- `GET /api/v1/admin/cap-guard/decisions`
- `GET /api/v1/admin/cap-guard/decisions/{decision_id}`
- `GET /api/v1/admin/reconciliation/plans`
- `GET /api/v1/admin/reconciliation/plans/{plan_id}`
- `GET /api/v1/orders`
- `GET /api/v1/orders/{client_order_id}`
- `GET /api/v1/stealth/orders`
- `GET /api/v1/stealth/orders/{stealth_order_id}`
- `GET /api/v1/stealth/command-suite`
- `GET /api/v1/movement-repricing/evidence`
- `GET /api/v1/movement-repricing/orders/{client_order_id}`
- `GET /api/v1/movement-repricing/stealth/{stealth_order_id}`
- `GET /api/v1/futures/account`
- `GET /api/v1/futures/positions`
- `GET /api/v1/futures/positions/{position_key}`
- `GET /api/v1/spot/readiness`
- `GET /api/v1/spot/sweep/status`
- `GET /api/v1/spot/sweep/pnl`
- `GET /api/v1/spot/pnl/checkpoints`
- `GET /api/v1/spot/pnl/checkpoints/{checkpoint_id}`
- `GET /api/v1/spot/cost-basis/status`
- `GET /api/v1/spot/campaign/status`
- `GET /api/v1/spot/direct-orders/{client_order_id}/audit`
- `GET /api/v1/spot/command-suite`
- `GET /api/v1/spot/recovery/preview`
- `GET /api/v1/spot/recovery/apply-review`
- `GET /api/v1/spot/recovery/rollback-plan`
- `GET /api/v1/spot/recovery/reconciliation-proof`

`GET /api/v1/admin/enterprise-readiness` also exposes per-module
`action_posture` evidence. The posture counts read routes, command routes,
live-disabled/live-eligible routes, unsupported actions, and command gaps from
backend route-inventory `module_id` ownership. It is display evidence only; it
does not authorize browser-side commands or replace backend guard, wallet,
margin, approval, audit, cap, or reconciliation gates.

The same response exposes M48 `mutation_taxonomy` evidence. Current taxonomy
rows cover live-disabled HTTP command routes, backend-owned local-state
mutation routes, legacy dashboard WebSocket compatibility command surfaces,
and backend-contract-required families for futures/perpetual commands and
fill-ledger repair. Every current command surface in
`ADMIN_API_ROUTE_INVENTORY` must appear in exactly one taxonomy row.
M49 adds the `admin.approval_lifecycle` taxonomy row for approval request,
decision, and revoke local-state mutation routes.
M50 adds the `admin.cap_guard_decisions` taxonomy row for backend-owned
cap/guard decision record routes. Only records with `allowed=true` and
`status=passed` can become resolver-eligible for exact backend admission
matching; blocked and warning records remain durable fail-closed evidence.
M51 adds the `admin.admission_audits` taxonomy row for backend-owned
admission audit records. Admission audit records are exact proof input only;
they remain blocked/no-live evidence and cannot mark live admission allowed.
M52 adds the `admin.reconciliation_plans` taxonomy row for backend-owned
reconciliation plan records. Passed records are exact resolver input only;
they do not execute reconciliation or mark exchange/order state reconciled.
M54 adds the `spot.pnl_checkpoint` taxonomy row for backend-owned Spot P/L
checkpoint records. These records are local-state review evidence only; they
are not live execution, sell eligibility, profitability proof, reconciliation
execution, or tax accounting.
The checkpoint path is also the single Admin API average-cost review evidence
checkpoint audit-link evidence path, and checkpoint recovery-link evidence
path, and checkpoint reconciliation-link evidence path when an
`average_cost_snapshot` is recorded; do not add a parallel average-cost
writer, checkpoint audit writer, recovery-link writer, or reconciliation-link
writer.

Current mutating HTTP command surfaces are:

- `POST /api/v1/orders`
- `POST /api/v1/orders/{client_order_id}/cancel`
- `POST /api/v1/stealth/orders`
- `POST /api/v1/stealth/orders/{stealth_order_id}/reveal`
- `POST /api/v1/stealth/orders/{stealth_order_id}/move`
- `POST /api/v1/stealth/orders/{stealth_order_id}/cancel`
- `POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice`
- `POST /api/v1/spot/campaign/executions`
- `POST /api/v1/spot/sweep/automation-runs`
- `POST /api/v1/spot/recovery/apply-executions`
- `POST /api/v1/spot/recovery/rollback-executions`
- `POST /api/v1/spot/recovery/exchange-state-proofs`
- `POST /api/v1/spot/recovery/exchange-state-snapshots`
- `POST /api/v1/spot/recovery/reconciliation-proofs`

`POST /api/v1/stealth/orders` is a live-disabled draft contract keyed by
`stealth_order_id`. It does not invoke `StealthOrderManager`, create local
stealth lifecycle state, accept `client_order_id` or exchange `order_id`, or
submit Coinbase orders.
`POST /api/v1/stealth/orders/{stealth_order_id}/reveal` is a live-disabled
exchange-placement draft keyed by `stealth_order_id`. It does not invoke
`reveal_order_slice`, call `StealthOrderManager`, accept order ids as command
identity, submit Coinbase orders, or mutate local lifecycle state.
`POST /api/v1/stealth/orders/{stealth_order_id}/move` is a live-disabled
cancel/replace-shaped draft keyed by `stealth_order_id`. It does not invoke
`build_stealth_move_plan`, call `execute_stealth_move` or
`StealthOrderManager`, accept active placement ids or exchange ids as command
identity, submit/cancel Coinbase orders, perform cancel/replace, or mutate
local lifecycle state.

Current local-state approval lifecycle mutation surfaces are:

- `POST /api/v1/admin/approvals/requests`
- `POST /api/v1/admin/approvals/requests/{approval_request_id}/decisions`
- `POST /api/v1/admin/approvals/{approval_id}/revoke`
- `POST /api/v1/admin/admission-audits`
- `POST /api/v1/admin/cap-guard/decisions`
- `POST /api/v1/admin/reconciliation/plans`
- `POST /api/v1/spot/pnl/checkpoints`
- `POST /api/v1/spot/recovery/exchange-state-proofs`
- `POST /api/v1/spot/recovery/exchange-state-snapshots`
- `POST /api/v1/spot/recovery/reconciliation-proofs`

These local-state routes are authenticated, authorized, idempotent, and
audited. They write backend-owned approval lifecycle, admission audit,
cap/guard decision, reconciliation plan, Spot P/L checkpoint, or Spot recovery
proof/snapshot evidence only; they do not submit orders, cancel orders,
evaluate browser guards, execute recovery, execute reconciliation, prove
profitability, create tax lots, mutate order/exchange state, or call Coinbase.

See [Admission Audit Records](README.admission-audits.md),
[Cap/Guard Decision Records](README.cap-guard-decisions.md),
[Reconciliation Plan Records](README.reconciliation-plans.md),
[Spot Recovery Proof Records](README.spot-recovery-proofs.md),
[Spot Recovery Snapshot Records](README.spot-recovery-snapshots.md), and
[Admin API Examples](docs/examples/admin-api.md) for record contracts and
payload examples.

The current operational dashboard is still the proof-of-concept WebSocket and
HTML surface documented in `agent.md` and `genai_data/API_REFERENCE.md`.
For the current boundary between legacy live WebSocket commands, read-only
HTTP routes, and sweep/campaign execution, see
[Live Order Surfaces](docs/LIVE_ORDER_SURFACES.md).

The frontend release-hardening gate is owned by `C:\coinbase-frontend` and is
the canonical no-live command:

```powershell
npm run release:gate
```

That gate expands to build, typecheck, lint, generated API freshness, command
security, release/deployment checks, release artifact generation, runtime
evidence, autonomous queue validation, unit tests, dry read/command/BFF/OIDC
smokes, and Playwright e2e. Those checks are no-live checks and must report
live Coinbase execution as not run with notional `$0`. They are not approval
for live Coinbase execution. The release artifact is written in the frontend
repository at
`artifacts/release-readiness.json`; the package manifest is
`artifacts/deployment-package-manifest.json`; and the route/header drill is
`artifacts/observability-drill.json`. Synthetic probe evidence is written to
`artifacts/synthetic-probes.json`, and the public release checklist is written
to `artifacts/public-release-checklist.json`. Runtime/UI evidence is written
to `artifacts/runtime-evidence.json`. They are uploaded by frontend CI; they
are not backend approval to trade. These checks do not replace this
repository's required backend regression gate when backend files change.
In short: runtime evidence is saved, and these artifacts are not approval for
live Coinbase execution.
No-live release artifacts are not approval for live Coinbase execution.

Enterprise readiness also acts as the backend-owned module registry. Each
module row exposes a stable `module_id`, primary owner, backend contract refs,
frontend contract refs, documentation refs, identity keys, and a
`spot_rule_boundary` so future non-spot work does not copy spot wallet,
USDC, cost-basis, or no-shorting assumptions by accident.

Route and capability evidence is module-bound too. Every route inventory row
has a backend-owned `module_id`, and `GET /api/v1/admin/capabilities` exposes
that id so the frontend can prove route ownership without deriving trading
authority in the browser.

The current frontend read-model interaction batch consumes backend-shaped
admin, order, spot, campaign, audit, and diagnostics reads as display evidence
only. The frontend may locally filter/sort already-loaded rows, select
`client_order_id` details, render audit anchors for client order id,
correlation id, and audit id, switch campaign evidence tabs, show named
empty/error states, and keep tables usable on narrow viewports. None of those
interactions create frontend trading authority, wallet checks, guard
decisions, order profitability checks, Coinbase calls, or exchange
`order_id` identity.
The current frontend command draft scope remains crypto-USDC spot pairs and
must not be broadened in browser code before backend Admin API contracts and
tests define a broader scope.
The platform/module split is documented in
[Admin Platform Architecture](docs/ADMIN_PLATFORM_ARCHITECTURE.md) and
[Admin Module Capability Matrix](docs/ADMIN_MODULE_CAPABILITY_MATRIX.md).

## Direction

- Use FastAPI with backend-owned OpenAPI.
- Keep `openapi/coinbase-admin-api-route-inventory.json` generated from
  `ADMIN_API_ROUTE_INVENTORY`; frontend route checks consume this artifact
  instead of scraping backend Python source.
- Keep the backend as the only authority for trading behavior.
- Keep HTTP live-order execution disabled until approval/cap gates are complete.
- Keep legacy dashboard WebSocket handlers as compatibility adapters.
- If a legacy WebSocket live command does not pass through enterprise
  idempotency, approval, and cap gates, label it compatibility-only and exclude
  it from new frontend workflows.
- Use `client_order_id` for internal and operator-facing order tracking.
- Manual order create may omit `client_order_id`; the backend route derives it
  before approval/admission evidence. Frontend and BFF code must display the
  returned id but must not generate or override it.
- Preserve Coinbase cancellation through the project wrapper
  `cancel_order(client_order_id)`, which accepts only explicit Coinbase
  `success: true` cancel evidence as success.
- Treat exchange-native `order_id` as exchange evidence only. The order read
  model exposes it as `exchange_order_id`; it is not an identity or cancel key.
- Order list/detail read rows may include `correlation_id` and `audit_id`
  when the backend row source has durable evidence for them. These fields are
  audit navigation evidence, not order identity.
- Stealth read rows use `stealth_order_id` for stealth lifecycle identity,
  `active_placement_client_order_id` for active placement evidence, and
  `active_exchange_order_id` as exchange evidence only. The enterprise Admin
  API has live-disabled stealth reveal, move, and cancel commands keyed by
  `stealth_order_id`; they must not use active placement ids or exchange ids
  as command keys, and they must not mutate lifecycle state until exchange
  handling and reconciliation are implemented.
- Stealth detail rows include `active_placement_audit` so operators can see
  local active-placement evidence, required mutation families, missing
  exchange-truth contracts, and no-live Coinbase flags without turning active
  placement ids or exchange ids into command inputs.
- Stealth detail rows also include `mutation_claim_audit` so operators can see
  runtime mutation-claim snapshot status, required move/reprice claim
  contracts, missing claim contracts, and no-live Coinbase flags without
  acquiring or releasing claims or turning claim state into browser/BFF command
  authority.
- Stealth detail rows also include `reveal_trigger_audit` so operators can see
  local reveal-condition evidence, required reveal-trigger guard contracts,
  missing trigger contracts, and no-live Coinbase flags without evaluating
  triggers, calling `should_trigger_reveal`, calling `reveal_order_slice`, or
  turning condition state into browser/BFF command authority.
- Stealth detail rows also include `reveal_submission_audit` so operators can
  see the future backend reveal route, shared service method, manager method,
  local active-placement blockers, required submission/reconciliation
  contracts, and no-live Coinbase flags without calling `reveal_order_slice`,
  submitting or cancelling Coinbase orders, creating active placements, or
  turning placement evidence into browser/BFF command authority.
- Stealth detail rows also include `reveal_reconciliation_audit` so operators
  can see required reconciliation plan/proof posture, local active-placement
  evidence, missing proof contracts, read-evidence routes, and no-live flags
  without reading Coinbase, writing proof records, executing reconciliation,
  mutating order/lifecycle state, or turning proof evidence into browser/BFF
  command authority.
- Movement/repricing read rows combine durable `order_moves`,
  `stealth_order_moves`, and `stealth_orders.anchor_repricing_state_json`
  evidence. Runtime mutation claims and pending replacement claims are shown
  only when safely observable through the existing manager/engine state; if
  unavailable, the response says so instead of treating the database as proof
  that no runtime claim exists.
- Dry-submit means an audited, idempotent backend command POST may run and
  return backend evidence. It does not mean Coinbase live execution, and it may
  still produce audit/idempotency records before the live-disabled or
  prerequisite-rejected response is returned.
- Movement repricing command draft:
  `POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice`
  is live-disabled and keyed by `stealth_order_id`. It does not clear
  cooldowns, invoke the live repricer, cancel placements, or call Coinbase.
  Its `live_exchange_cancel` action class and `order:cancel` permission are
  intentional because approved live repricing would be cancel/replace-shaped;
  no standalone browser repricing permission exists. Dry-submit for this
  command means preserving the backend `501` response, idempotency, audit,
  operator-intent, and no-live evidence.
- Futures/perpetual read rows use backend-defined `position_key` identity.
  Account evidence separates `configured_product_scope` from
  `observed_position_scope`; close/reduce sides are backend-derived from
  observed position side and are not exchange-observed order flags.
- Guard/risk policy reads expose existing backend action-condition policy,
  configured cap rules, product capability policy, live gate posture,
  profitability-validator posture, authority sources, and rejection categories
  as evidence only. They do not fetch Coinbase wallets and do not approve live
  execution.
- Capability reads expose backend route-inventory metadata, including command
  action class, permission, shared service method, idempotency, approval,
  caps, audit, compatibility, and parity evidence. This metadata is a
  frontend validation source only; it does not make command routes live.
  `frontend_safe=true` means safe for Admin frontend/BFF contract exposure
  under backend authority; it is not permission to submit, cancel, reprice, or
  execute live Coinbase orders.
- Live-enablement reads expose controlled M8 live path readiness, cap
  posture, approval requirements, guard requirements, audit requirements, and
  reconciliation requirements. They also expose per-route controlled-live
  preflight checks that separate passed backend-owned prerequisites from
  blocking approval, cap/guard, live-execution-service, and reconciliation
  prerequisites. M30 route-specific approval snapshot evidence makes the
  missing durable, backend-owned, expiring, payload-bound approval record
  explicit per live-shaped path. M36 approval-store foundation evidence makes
  configured durable backend approval-store infrastructure explicit per
  live-shaped path without creating approval snapshots. M37 approval snapshot
  resolver foundation is internal backend infrastructure for exact unexpired
  store records; it does not prove a route-specific approval snapshot is
  present. M32 live-admission audit trail evidence makes the missing
  append-only backend admission audit facts explicit per live-shaped path.
  M33 route-specific cap/guard contract evidence makes the missing backend
  cap, guard, payload, approval, admission-audit, and product-scope bindings
  explicit per live-shaped path. The
  route is read-only, reports
  `default_live_coinbase_execution=not_run`, submitted/executed notional
  `$0`, and does not enable any command path.
- M34 command admission decision evidence is emitted on live-disabled HTTP
  command responses. It is route-bound and payload-bound evidence for why the
  command remains blocked; it is not browser approval, guard execution,
  reconciliation authority, or live Coinbase execution.
- M35 command admission audit persistence writes the same admission decision
  to existing Admin API audit events and exposes it through Audit Workbench
  read evidence. It is not audit mutation, browser approval, guard execution,
  reconciliation authority, or live Coinbase execution.
- M36 durable approval-store foundation adds backend-owned append-only
  approval record storage and exact-match lookup semantics. It is not an
  approval endpoint, browser approval, BFF mutation, live admission, Coinbase
  execution, or proof that a route-specific approval snapshot exists.
- M37 approval snapshot resolver foundation can derive immutable backend
  snapshot evidence from an exact unexpired approval-store record. It is not
  an approval endpoint, browser approval, BFF mutation, live admission,
  Coinbase execution, or proof that command admission may proceed.
- M38 command admission snapshot resolver wiring lets existing live-disabled
  command responses report `approval_snapshot_present`, snapshot ids, actor
  binding, expiry, identity value, and missing-snapshot reasons. A resolved
  snapshot removes only the `approval_snapshot_missing` blocker; live-disabled,
  admission-audit, cap/guard, reconciliation, and browser-authority blockers
  still prevent Coinbase submission.
- M39 command admission audit resolver wiring lets existing live-disabled
  command responses report `admission_audit_present`, audit ids, audit source,
  recorded time, and missing-audit reasons. A resolved audit proof removes
  only the `admission_audit_missing` blocker; live-disabled, cap/guard,
  reconciliation, and browser-authority blockers still prevent Coinbase
  submission.
- M40 command admission cap/guard proof wiring lets existing live-disabled
  command responses report `cap_guard_present`, cap/guard decision ids,
  cap/guard source, recorded time, and missing-cap/guard reasons. A resolved
  cap/guard proof removes only the `cap_guard_missing` blocker; live-disabled,
  reconciliation, and browser-authority blockers still prevent Coinbase
  submission.
- M41 command admission reconciliation plan proof wiring lets existing
  live-disabled command responses report `reconciliation_plan_present`,
  reconciliation plan ids, source, recorded time, and missing-reconciliation
  reasons. A resolved reconciliation plan proof removes only the
  `reconciliation_plan_missing` blocker; live-disabled and browser-authority
  blockers still prevent Coinbase submission.
- M42 command admission live execution service boundary evidence lets
  existing live-disabled command responses report that the backend live
  execution service is required but absent/disabled. It does not remove
  `live_execution_disabled`, authorize the browser, or submit to Coinbase.
- M43 disabled live execution service foundation makes that backend service
  boundary present as evidence with source `disabled_backend_service`. The
  descriptor has no create, cancel, submit, execute, browser, BFF, or Coinbase
  authority methods, so command routes remain no-live.
- M44 live execution adapter contract evidence maps live-shaped routes to
  shared `AdminApiCommandService` methods on read-only live-enablement path
  rows. The adapter evidence is disabled, unconfigured, and non-executable.
- M45 live execution intent envelope evidence lets command admission decisions
  report the route, identity, payload hash, idempotency key, actor, operator
  intent, service method, and disabled blockers for a command-to-live-execution
  attempt. The intent is not prepared, not executable, and display-only.
- M46 live readiness precondition evidence lets
  `GET /api/v1/admin/live-enablement` report a normalized backend-owned
  checklist for approval store, approval snapshot, admission audit, cap/guard,
  reconciliation, adapter, intent, browser/BFF, and disabled live service
  prerequisites. It is read-only evidence and does not broaden command
  admission, browser approval, BFF execution authority, or Coinbase execution.
- Approval-store rows created before M37 that lack `requested_by_actor_id`
  fail closed during strict JSONL reads. They are ignored by resolver lookup
  rather than treated as reusable approval authority.
- Audit workbench reads normalize route inventory, command audit, order,
  stealth, movement/repricing, futures/perpetual, guard/risk, and campaign
  evidence into one read-only surface. They do not mutate audit history, read
  Coinbase, or create a second command path.
- Enterprise-readiness command-gap evidence is read-only. It records action,
  status, reason, required backend contract, frontend boundary, live Coinbase
  posture, and notional for command paths that must not be implemented from
  the browser. It is not a command route registry or live approval source.
- Configure `COINBASE_ADMIN_API_BEARER_TOKEN` before exercising HTTP routes.
  Without it, routes fail closed with `401`.
- `COINBASE_ADMIN_API_AUTH_MODE=bootstrap_bearer` is the local/bootstrap
  verifier. `COINBASE_ADMIN_API_AUTH_MODE=oidc_jwt` verifies RS256 JWTs
  against the configured issuer, audience, and JWKS, then derives actor and
  role evidence from JWT claims.
- The `oidc_jwt` verifier readiness contract reports required
  `COINBASE_ADMIN_API_OIDC_ISSUER`,
  `COINBASE_ADMIN_API_OIDC_AUDIENCE`, and
  `COINBASE_ADMIN_API_OIDC_JWKS_URL` settings. Missing settings fail closed.

## Local Run

Run the existing FastAPI app directly when developing the enterprise frontend:

```powershell
python tools\run_admin_api.py --dev-token local-admin-token
```

The helper starts `api.v1.app:app` on `http://127.0.0.1:8787`, sets local CORS
for `http://127.0.0.1:3000`, and keeps live Coinbase execution disabled. It
does not import trading clients or submit/cancel exchange orders.

For a deployment-like local run, configure auth explicitly instead of using
`--dev-token`:

```powershell
$env:COINBASE_ADMIN_API_BEARER_TOKEN = "local-admin-token"
$env:COINBASE_ADMIN_API_CORS_ORIGINS = "http://127.0.0.1:3000"
python tools\run_admin_api.py --port 8787
```

`COINBASE_ADMIN_API_CORS_ORIGINS` is an allowlist, not a wildcard. The Admin
API accepts browser preflight requests only from configured origins and allows
the session/BFF bridge headers required by the frontend:
`Authorization`, `X-Admin-Actor`, `X-Admin-Roles`, `X-Correlation-Id`,
`X-Request-Id`, `X-Operator-Intent`, `Idempotency-Key`, and `X-CSRF-Token`.
Bearer tokens still belong on the backend/session boundary; do not expose them
through `NEXT_PUBLIC_*` frontend variables.

The frontend BFF may copy only documented response-evidence headers back to
browser code: `Content-Type`, `X-Correlation-Id`, `X-Request-Id`,
`X-Admin-Api-Version`, `X-Live-Execution-Enabled`, and
`X-Idempotency-Replayed`. Treat missing BFF authority as a session/transport
configuration failure, not as a live trading gate result.

For mutating HTTP commands, `X-Operator-Intent` is durable audit evidence and
part of the idempotency payload hash together with endpoint, actor/roles, body,
and path identity. Reusing an `Idempotency-Key` with changed operator intent
returns conflict instead of replaying the prior command.

Frontend `server_env_static` BFF authority is local/staging evidence only.
Production readiness requires frontend `backend_oidc_jwt` BFF mode and
backend `oidc_jwt` verifier configuration. Browser-visible RBAC remains a UI
hint; backend RBAC is the enforcement authority.
`GET /api/v1/admin/oidc-readiness` exposes backend OIDC verifier evidence for
release checks, including active auth mode, required/missing environment
settings, claim mapping, JWKS reachability, and no-live notional posture.

Run the no-live OIDC readiness smoke before treating production OIDC evidence
as usable by the frontend release gate:

```powershell
python tools\run_admin_oidc_readiness_smoke.py --summary-only
```

The smoke uses backend TestClient and temporary JWKS evidence to prove missing
config blocks, configured JWKS readiness reports ready, and `oidc_jwt`
session claims override forged browser actor/role headers. It does not contact
Coinbase and reports live Coinbase execution not run with notional `$0`.

CSRF enforcement is opt-in for cookie/session or BFF deployments:

```powershell
$env:COINBASE_ADMIN_API_CSRF_REQUIRED = "true"
$env:COINBASE_ADMIN_API_CSRF_TOKEN = "local-csrf-token"
```

When required, unsafe HTTP methods under `/api/v1/` must include
`X-CSRF-Token` matching the configured token. Read-only `GET` routes are not
blocked by CSRF middleware. Failed CSRF checks return structured `403` errors
with `X-Live-Execution-Enabled: false`.
`GET /api/v1/admin/csrf` exposes the CSRF posture, header name, token source,
and rotation policy without disclosing a token value.

## Must Not Do

- Do not implement live order behavior directly in FastAPI handlers.
- Do not duplicate guard, wallet, sizing, or Coinbase REST logic in the
  frontend.
- Do not treat frontend acknowledgement as sufficient enterprise approval.
- Do not expose Coinbase credentials to browser code.

## References

- [Admin API E2E Plan](docs/plans/ADMIN_API_E2E_PLAN.md)
- [Admin API Route Inventory](docs/plans/ADMIN_API_ROUTE_INVENTORY.md)
- [Admin Platform Architecture](docs/ADMIN_PLATFORM_ARCHITECTURE.md)
- [Admin Module Capability Matrix](docs/ADMIN_MODULE_CAPABILITY_MATRIX.md)
- [Admin API Examples](docs/examples/admin-api.md)
- [Stealth Mutation-Claim Snapshot Proofs](README.stealth-mutation-claim-proofs.md)
- [Stealth Mutation-Claim Snapshot Proof Examples](docs/examples/stealth-mutation-claim-proofs.md)
- [Stealth Recovery Proofs](README.stealth-recovery-proofs.md)
- [Stealth Recovery Proof Examples](docs/examples/stealth-recovery-proofs.md)
- [Stealth Reconciliation Proofs](README.stealth-reconciliation-proofs.md)
- [Stealth Reconciliation Proof Examples](docs/examples/stealth-reconciliation-proofs.md)
- [Movement And Repricing](README.movement-repricing.md)
- [Futures/Perpetuals Admin Reads](README.futures-perpetuals.md)
- [Guard/Risk Policy Admin Reads](README.guard-risk-policy.md)
- [Audit Workbench Admin Reads](README.audit-workbench.md)
- [Frontend Association](docs/FRONTEND_ASSOCIATION.md)
- [Live Order Surfaces](docs/LIVE_ORDER_SURFACES.md)
- [API Reference](genai_data/API_REFERENCE.md)
- [Order ID Handling](genai_data/ORDER_ID_HANDLING.md)
- [Documentation Index](docs/README.md)
