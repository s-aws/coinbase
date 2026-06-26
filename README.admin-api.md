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
account, position, command-suite contract, and risk-proof record read routes,
a no-live append-only futures/perpetual risk-proof record route, read-only guard/risk policy evidence, read-only
cross-module audit workbench evidence, backend-owned approval, cap/guard,
admission audit, reconciliation plan, and live-service decision evidence
routes, and read-only spot
operator routes. Live-shaped trading command HTTP routes still return
`not_implemented` after auth, permission, idempotency, and audit handling;
they do not submit orders, cancel orders, or call Coinbase.

`POST /api/v1/orders` is the enterprise manual Spot order command contract, but
today it is a dry-submit/review path only. The route requires backend auth,
RBAC, idempotency, correlation, and operator-intent headers, may derive a
backend-owned `client_order_id` before admission when the request omits one,
and then returns live-disabled evidence. It does not reach the live branch that
checks Spot wallet inventory, no-short sell authority, product capability,
event-stream audit, or REST submission unless a future HTTP live-execution gate
explicitly passes `allow_live_execution=true`. The UI label "operator" names a
human workflow role; backend order creation still requires `trader` or `admin`
RBAC authority.

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
M55 adds backend-owned live-service decision evidence routes at
`/api/v1/admin/live-execution/service-decisions`. The `POST` route records an
append-only disabled-service decision only: it rejects enabled service,
live Coinbase approval, `passed` status, and nonzero submitted or executed
notional. List/detail routes are read-only evidence. These routes do not
enable live service, construct adapters, call Coinbase, invoke managers,
execute reconciliation, mutate state, clear execution blockers, or create
browser/BFF execution authority.
The existing disabled `live_execution_service_contract` may also show the
latest disabled live-service decision record as local readback evidence. That
readback keeps `enablement_precondition_resolved=false`,
`latest_service_decision_resolves_enablement=false`, all enablement artifacts
missing, and all live execution authority disabled. The readback also
separates recorded decision artifacts from satisfied enablement artifacts:
`latest_service_decision_recorded_artifacts_satisfy_enablement=false`,
`latest_service_decision_satisfied_enablement_artifacts=[]`, and
`latest_service_decision_unsatisfied_enablement_artifacts` still names the
required enablement artifacts when a disabled decision is present.
M55 also adds backend-owned live-adapter decision evidence routes at
`/api/v1/admin/live-execution/adapter-decisions`. The `POST` route records an
append-only disabled adapter-construction decision only: it rejects
constructed adapters, enabled adapters, live Coinbase approval, `passed`
status, nonzero submitted or executed notional, and route bindings that do
not match the route inventory. The reviewed target must be a `POST`
non-read-only command surface whose `shared_method` exists on
`AdminApiCommandService`; read-only routes and unrelated local-state services
are rejected. List/detail routes are read-only evidence. These routes do not
construct adapters, enable live service, call Coinbase, invoke managers,
execute reconciliation, mutate state, clear execution blockers, or create
browser/BFF execution authority. When projected into the disabled
`live_execution_adapter_contract`, the latest adapter decision is
readback-only evidence: it keeps
`latest_adapter_decision_recorded_artifacts_satisfy_construction=false`,
`latest_adapter_decision_satisfied_construction_artifacts=[]`, and required
construction artifacts unsatisfied. It also reports
`latest_adapter_decision_resolution_status`,
`latest_adapter_decision_non_resolution_reason`,
`latest_adapter_decision_required_resolution_artifacts`,
`latest_adapter_decision_missing_resolution_artifacts`,
`latest_adapter_decision_forbidden_resolution_claims`, and
`latest_adapter_decision_next_required_contract` so a decision record cannot
be confused with adapter construction authority.
The current `latest_adapter_decision_next_required_contract` is
`backend_live_adapter_construction_contract`. M55 phases 3621-3640 expose that
contract as typed read-only evidence under `live_execution_adapter_contract`.
M55 phases 3641-3660 add per-artifact acceptance requirements to the same
contract: required evidence ids, source refs, checks, negative checks,
evidence presence, and satisfaction blockers. These fields do not construct
adapters, satisfy construction artifacts, enable live service, call Coinbase,
invoke managers, execute reconciliation, mutate state, or grant browser/BFF
authority.
M55 phases 3661-3680 add blocked per-artifact acceptance evidence readback rows
for those requirements. M55 phases 3681-3700 add a blocked contract-level
aggregate over those rows with total, missing, and accepted counts, blockers,
next evidence ids, false construction satisfaction, and no-live authority.
M55 phases 3701-3720 add a blocked producer contract over those missing
acceptance evidence ids so future backend work knows which contract must
create or record each evidence id. M55 phases 3721-3740 add blocked
producer-readiness rows for the missing route, append-only store, and
validation/replay gate. M55 phases 3741-3760 add a blocked contract-level
aggregate over those producer-readiness rows with total, missing, and
satisfied readiness counts, category lists, producer contract ids, next
required readiness item ids, blockers, first blocker, disabled route/store/
validation/replay/writer/acceptance flags, false satisfaction, and no-live
authority. M55 phases 3761-3780 add blocked clearance-action rows for each
missing producer-readiness item so future backend work can see the exact
required ref, route/method, verification gate, source blocker, and disabled
writer/acceptance/construction flags. M55 phases 3781-3800 add a blocked
dependency summary over those clearance actions with action counts,
dependency-blocked refs, clearable refs, terminal refs, first blocked action,
and disabled route/store/validation/replay/writer/acceptance/construction/
clearance/execution flags. M55 phases 3801-3820 add blocked producer-
clearance work items and a queue summary derived from each producer
contract's first blocked clearance action. M55 phases 3821-3840 add blocked
producer-clearance claim traces and a summary mapping forbidden producer-route
availability claims back to those work items. M55 phases 3841-3860 add
blocked producer-route requirements and a summary mapping those claim traces
to the missing backend route contract evidence. M55 phases 3861-3880 add
blocked producer-route contract proposals and a summary mapping those
requirements to missing route contract, route inventory, and shared
command-service evidence. Completed phases 3881-3900 add blocked producer-route
contract validation rows and a summary mapping those proposals to missing
route contract, route registration, route inventory, shared service, handler,
store, validation/replay, writer, and acceptance prerequisites. Completed
phases 3901-3920 add blocked remediation rows and a summary mapping failed
validation rows to missing backend work without performing that work. Completed
phases 3921-3940 add blocked remediation-dependency rows and a summary that
order those remediation items by route contract without performing that work.
Completed phases 3941-3960 add blocked remediation work-item rows and a
work-queue summary that name required backend work, required backend refs, and
handoff blockers without performing that work. Completed phases 3961-3980 add
blocked remediation work-item claim traces and a claim-trace summary that map
those work items back to unresolved producer-route contract availability
claims without resolving those claims. Completed phases 3981-4000 add blocked
producer-route contract clearance plans and a clearance-plan summary that turn
those unresolved claim traces into backend-owned sequencing evidence for the
route, inventory, shared-service, handler, store, validation/replay, writer,
and acceptance-path work required before the claim could ever resolve. Completed
phases 4001-4020 expand those clearance plans into blocked ordered clearance
steps and a step summary without performing any of the named backend work.
Completed phases 4021-4040 add blocked clearance-step review rows and a
review summary that list the backend-owned review inputs and gates required
before those steps could ever become ready. Completed phases 4041-4060 add
blocked clearance-step review-input rows and a review-input summary derived
from those review rows without creating, accepting, validating, or completing
any input. Completed phases 4061-4080 add blocked clearance-step review-input
store requirement rows and a store-requirement summary derived from those
review-input rows without creating stores, writing evidence, accepting
records, validating records, completing inputs, completing reviews, resolving
claims, satisfying construction, constructing adapters, or executing live
paths. Completed phases 4081-4100 add blocked clearance-step review-input store
record-contract rows and a record-contract summary derived from those store
requirements without creating records, binding idempotency, validating
payloads, accepting evidence, completing inputs, resolving claims,
constructing adapters, or executing live paths. Completed phases 4101-4120
add blocked clearance-step review-input store record-validation rows and a
record-validation summary derived from those record contracts without creating
validators, binding idempotency, validating payloads, protecting replay,
accepting records, completing reviews, resolving claims, constructing
adapters, or executing live paths. Completed phases 4121-4140 add blocked
record-validation remediation rows and a remediation summary derived from
those validation rows without performing remediation, creating validators,
writing evidence, accepting records, completing reviews, resolving claims,
constructing adapters, or executing live paths. Completed phases 4141-4160 add
blocked record-validation remediation dependency rows and a dependency summary
derived from those remediation rows with immediate predecessor/successor links
only, without resolving dependencies, performing remediation, creating
validators, writing evidence, accepting records, completing reviews, resolving
claims, constructing adapters, or executing live paths. Completed phases
4161-4180 add blocked dependency work items and a work-queue summary derived
from those dependency rows, without performing remediation, accepting records,
resolving claims, constructing adapters, or executing live paths. Completed
phases 4181-4200 add blocked dependency work-item claim traces and a
claim-trace summary derived from those work items, without resolving claims,
clearing work items or dependencies, performing remediation, accepting
records, constructing adapters, or executing live paths. Completed phases
4201-4220 add blocked dependency work-item claim-trace clearance plans and a
clearance-plan summary derived from those claim traces, without resolving
claims, clearing claim traces, clearing work items or dependencies, performing
remediation, accepting records, constructing adapters, or executing live
paths. Completed phases 4221-4240 add blocked dependency work-item claim-trace
clearance steps and a clearance-step summary derived from those plans, without
completing steps, resolving claims, clearing claim traces, clearing work items
or dependencies, performing remediation, accepting records, constructing
adapters, or executing live paths. Completed phases 4241-4260 add blocked
dependency work-item claim-trace clearance-step reviews and a clearance-step
review summary derived from those steps, without completing reviews, accepting
review inputs, passing review gates, completing steps, resolving claims,
clearing claim traces, clearing work items or dependencies, performing
remediation, accepting records, constructing adapters, or executing live
paths. Completed phases 4261-4280 add blocked dependency work-item claim-trace
clearance-step review inputs and a review-input summary derived from those
reviews, without making inputs present, accepting inputs, validating inputs,
completing reviews, completing steps, resolving claims, clearing claim traces,
clearing work items or dependencies, performing remediation, accepting
records, constructing adapters, or executing live paths. Completed phases
4281-4300 add blocked dependency work-item claim-trace clearance-step
review-input store requirements and a store-requirement summary derived from
those review inputs, without creating stores, allowing writers, writing or
accepting records, validating records, accepting inputs, validating inputs,
completing reviews, completing steps, resolving claims, clearing claim traces,
clearing work items or dependencies, performing remediation, constructing
adapters, or executing live paths. Completed phases 4301-4320 add blocked
dependency work-item claim-trace clearance-step review-input store record
contracts and a record-contract summary derived from those store requirements,
without making record contracts available, making schemas available, making
append-only logs available, binding idempotency, validating payloads,
protecting replay, creating stores, allowing writers, writing or accepting
records, validating records, accepting inputs, validating inputs, completing
reviews, completing steps, resolving claims, clearing claim traces, clearing
work items or dependencies, performing remediation, constructing adapters, or
executing live paths. Completed phases 4321-4340 add blocked dependency
work-item claim-trace clearance-step review-input store record validations and
a record-validation summary derived from those record contracts, without
making validations ready or enabling live paths. Completed phases 4341-4360 add
blocked dependency work-item claim-trace clearance-step review-input store
record-validation remediation items and a remediation summary derived from
those validation rows, without making remediation ready, performing
remediation, recording remediation, making validations ready, writing or
accepting records, constructing adapters, or executing live paths. Completed
phases 4361-4380 add blocked dependency work-item claim-trace clearance-step
review-input store record-validation remediation dependency rows and a
dependency summary derived from those remediation rows, without making
dependency graphs ready, making predecessors ready, making remediation ready,
writing or accepting records, constructing adapters, or executing live paths.
Completed phases 4381-4400 add blocked dependency work items and a work-queue
summary derived from those dependency rows, without making work items ready,
handoffs ready, dependency graphs ready, predecessors ready, remediation
ready, writing or accepting records, constructing adapters, or executing live
paths. Completed phases 4401-4420 add blocked dependency work-item claim
traces and a claim-trace summary derived from those dependency work items,
without making claim traces ready, resolving claims, clearing work items or
dependencies, writing or accepting records, constructing adapters, or
executing live paths. Completed phases 4421-4440 add blocked dependency
work-item claim-trace clearance plans and a clearance-plan summary derived
from those claim traces, without making plans ready, making sequences ready,
resolving claims, clearing claim traces or work items, writing or accepting
records, constructing adapters, or executing live paths. Completed phases
4441-4460 add blocked dependency work-item claim-trace clearance steps and a
clearance-step summary derived from those clearance plans, without making
steps ready, completing steps, allowing next steps, completing prior steps,
making plans ready, resolving claims, clearing claim traces or work items,
writing or accepting records, constructing adapters, or executing live paths.
Completed phases 4461-4480 add blocked dependency work-item claim-trace
clearance-step reviews and a review summary derived from those clearance
steps, without making reviews ready, completing reviews, accepting inputs,
passing review gates, completing steps, resolving claims, clearing work
items, constructing adapters, or executing live paths. Completed phases
4481-4500 add blocked dependency work-item claim-trace clearance-step review
inputs and a review-input summary derived from those reviews, without making
inputs present, accepting inputs, validating inputs, completing reviews,
passing gates, completing steps, resolving claims, clearing work items,
constructing adapters, or executing live paths. Completed phases 4501-4520 add
a concrete M55 blocker-closure ledger naming live-service, live-adapter,
active-placement cancel/replace, reveal submission, recovery repair/rollback,
and post-write reconciliation blockers without enabling Coinbase, managers,
repair, rollback, reconciliation, state mutation, browser, or BFF authority.
Completed phases 4521-4540 added one route-bound, non-executable dry-run
adapter for stealth reveal. Completed phases 4541-4560 added route-bound,
non-executable dry-run live-service evidence for the same reveal route.
Completed phases 4561-4580 classify those reveal dry-run service and adapter
surfaces as partial blocker evidence while keeping exact proof, manager,
Coinbase, reconciliation, browser, and BFF execution authority blocked.
Completed phases 4581-4600 expand partial evidence to the remaining concrete M55
blocker rows for active-placement cancel/replace, reveal exchange submission,
recovery repair/rollback, and post-write reconciliation execution while
keeping every blocker unresolved and no-live. Completed phases 4601-4620 add
structured closure-readiness criteria, missing criteria, verification gates,
and readiness blockers to the same six rows while keeping every blocker
unresolved and every live/manager/Coinbase/reconciliation/state-mutation flag
false. Completed phases 4621-4640 add criterion-level source/dependency
traceability for those readiness criteria while keeping every dependency
unresolved and every execution authority flag false. Completed phases 4641-4660
classify those trace dependencies as backend contract, proof route, or
gate-chain dependencies while keeping every dependency unresolved and every
execution authority flag false. Completed phases 4661-4680 assign each
classified dependency to a backend-owned clearance plan row with an owner,
required artifact, clearance order, blocked status, and no-execution authority
flags. Completed phases 4681-4700 derive blocked backend clearance-step rows
from those plans without clearing dependencies or changing execution authority.
Completed phases 4701-4720 derive blocked backend clearance-step review rows
from those steps without completing reviews, making steps ready, clearing
dependencies, or changing execution authority. Completed phases 4721-4740
derive blocked backend review-input rows from those reviews without accepting
inputs, validating inputs, completing reviews, making steps ready, clearing
dependencies, or changing execution authority. Completed phases 4741-4760
derive blocked backend review-input store-requirement rows from those inputs
without making stores available, allowing writers, writing records, validating
records, accepting inputs, completing reviews, making steps ready, clearing
dependencies, or changing execution authority. Completed phases 4761-4780 derive
blocked backend review-input store record-contract rows from those store
requirements without creating record contracts, schemas, logs, idempotency
bindings, payload validation, replay protection, records, stores, accepted
inputs, completed reviews, ready steps, cleared dependencies, or execution
authority. Completed phases 4781-4800 derive blocked backend review-input
store record-validation rows from those record contracts without validating
records or changing execution authority. Completed phases 4801-4820 derive
blocked backend review-input store record-validation remediation rows from
those validations without remediating records, readying validations, clearing
dependencies, or changing execution authority. Completed phases 4821-4840 derive
blocked backend review-input store record-validation remediation dependency
rows from those remediations without resolving dependency order, performing
remediation, readying validations, clearing dependencies, or changing
execution authority. Completed phases 4841-4860 derive blocked backend
review-input store record-validation remediation dependency work-item rows from
those dependencies without claiming work items, performing work items,
resolving dependency order, performing remediation, readying validations,
clearing dependencies, or changing execution authority. Completed phases
4861-4880 derive blocked backend claim-trace rows from those work items without
resolving claims, allowing claim resolution, clearing dependencies, performing
remediation, validating records, or changing execution authority. Completed
phases 4881-4900 derive blocked backend claim-trace clearance-plan rows from
those claim traces without executing plans, resolving claims, clearing claim
traces, clearing work items or dependencies, writing evidence, reconciling,
calling Coinbase, invoking managers, or changing execution authority.
Completed phases 4901-4920 derive blocked backend claim-trace clearance-step
rows from those clearance plans without executing plan steps, resolving
claims, clearing claim traces, clearing work items or dependencies, writing
evidence, reconciling, calling Coinbase, invoking managers, or changing
execution authority. Completed phases 4921-4940 derive blocked backend
claim-trace clearance-step review rows from those clearance steps without
completing reviews, executing plan steps, resolving claims, clearing claim
traces, clearing work items or dependencies, writing evidence, reconciling,
calling Coinbase, invoking managers, or changing execution authority.
Completed phases 4961-4980 derive blocked backend claim-trace clearance-step
review-input store-requirement rows from those review inputs without creating
stores, allowing writers, writing records, accepting inputs, validating inputs,
completing reviews, executing plan steps, resolving claims, clearing claim
traces, clearing work items or dependencies, writing evidence, reconciling,
calling Coinbase, invoking managers, or changing execution authority. Completed
phases 4981-5000 derive blocked backend claim-trace clearance-step
review-input store record-contract rows from those store requirements without
creating contracts, schemas, logs, binding idempotency, validating payloads,
protecting replay, writing records, accepting inputs, completing reviews,
executing steps, resolving claims, reconciling, calling Coinbase, invoking
managers, or changing execution authority. Completed phases 5001-5020 derive
blocked backend claim-trace clearance-step review-input store record-validation
rows from those record contracts without validating records or changing
execution authority. Completed phases 5021-5040 derive blocked backend
claim-trace clearance-step review-input store record-validation remediation
rows from those validations without performing remediation, validating records,
writing evidence, reconciling, calling Coinbase, invoking managers, or changing
execution authority. Completed phases 5041-5060 derive blocked backend
claim-trace clearance-step review-input store record-validation remediation
dependency rows from those remediations without resolving dependency order,
performing remediation, validating records, writing evidence, reconciling,
calling Coinbase, invoking managers, or changing execution authority. Completed
phases 5061-5080 derive blocked backend claim-trace clearance-step
review-input store record-validation remediation dependency work-item rows
from those dependency rows without claiming work items, performing work items,
resolving dependencies, validating records, writing evidence, reconciling,
calling Coinbase, invoking managers, or changing execution authority.
Completed phases 5081-5100 derive blocked backend claim-trace clearance-step
review-input store record-validation remediation dependency work-item claim
traces from those dependency work-item rows without resolving claims, claiming
or performing work items, clearing dependencies, performing remediation,
validating records, writing evidence, reconciling, calling Coinbase, invoking
managers, or changing execution authority.
Completed phases 5101-5120 reconcile M55 route-level stealth command
enablement candidates across existing create, reveal, move, cancel, recovery,
reconciliation, and movement reprice routes without enabling any command,
calling managers, reconciling, mutating state, calling Coinbase, or granting
browser/BFF execution authority. The command-suite response now includes
`enablement_candidate_reviews` and `enablement_candidate_review_summary`.
Every row is blocked and non-executable; the current first review target is
`stealth_create` at `/api/v1/stealth/orders` because it has zero
exchange-facing blockers, not because create is executable.
Completed phases 5121-5140 turn that selected `stealth_create` planning target
into backend-owned pre-execution contract evidence on the command-suite read
route while keeping manager invocation, lifecycle writes, reconciliation
execution, Coinbase interaction, and browser/BFF authority blocked.
The command-suite response exposes that work as
`selected_create_pre_execution_contract`. It is a read-only contract object
for the selected create route only; it lists route identity, payload,
approval/admission, guard, lifecycle-write, manager, idempotency/audit,
reconciliation, and Coinbase non-interaction boundaries, but it does not call
`StealthOrderManager`, write `stealth_orders` or `order_parent`, execute
reconciliation, call Coinbase, or allow browser/BFF execution.
Completed phases 5141-5160 bind that same selected-create pre-execution contract
to the exact dry `POST /api/v1/stealth/orders` command response, including
correlation id, idempotency key, actor id, operator intent, request identity,
and payload-present fields. The command still returns live-disabled evidence
and remains no-manager, no-write, no-reconciliation, no-Coinbase, display-only,
and BFF forward-only.
Completed phases 5161-5180 started M57 by exposing read-only futures/perpetual
command-suite contract evidence for placement, close/reduce, cancel, and
reconciliation. The route registers no futures command routes, permits no
command drafts, executes no reconciliation, calls no Coinbase reads or writes,
mutates no state, and explicitly rejects spot wallet, no-shorting, USDC quote,
cost-basis, and inventory-lot assumptions as futures/perpetual authority.
The long claim-trace review-input, review-input store-requirement, store
record-contract, store record-validation, and store record-validation
remediation detail arrays are bounded representative readbacks. Their
summaries keep full logical totals in `total_input_count`,
`total_requirement_count`, `total_record_contract_count`,
`total_record_validation_count`, remediation totals, `missing_input_count`,
`missing_store_count`, `missing_record_contract_count`, and
`missing_record_validation_count`, while
`materialized_input_count`, `materialized_requirement_count`,
`materialized_record_contract_count`, `materialized_record_validation_count`,
remediation materialized counts, `detail_row_limit`, and `detail_rows_limited`
describe the capped detail rows.
These layers
do not accept or validate review inputs, complete reviews, make steps ready, register routes, bind route
inventory, bind shared command services, register handlers, create stores,
configure validation/replay, create writers, construct adapters, write or
accept evidence, satisfy construction artifacts, enable live service, call
Coinbase, invoke managers, execute reconciliation, mutate state, or grant
browser/BFF authority.
M57 phases 5781-5800 add `/api/v1/futures/risk-proofs` list/detail readbacks
and a `POST` append-only local proof-record route. The record route is bound to
`AdminApiCommandService.record_futures_risk_proof`, route inventory, RBAC,
idempotency, approval, cap/guard, and audit evidence, but it does not accept
proof requirements, register futures command routes, create command drafts,
call Coinbase, execute reconciliation, mutate futures/order/exchange state, or
grant browser/BFF authority.
M57 phases 5801-5820 consume those persisted proof records as read-only
command-suite resolver evidence. Exact safe latest records may be displayed as
resolver evidence, while missing or stale/invalid records fail closed. Resolver
evidence does not satisfy risk proof requirements, register futures command
routes, create command drafts, call Coinbase, execute reconciliation, mutate
state, or grant browser/BFF authority.
M57 phases 5821-5840 add explicit proof-acceptance blocker evidence to the
same futures/perpetual command-suite rows. A safe resolved proof record can be
shown as display evidence, but `proof_record_resolves_acceptance` remains
false and blocker fields explain the missing futures semantic contracts,
blocking acceptance criteria, missing command route, disabled command draft,
and disabled live execution posture.
M57 phases 5841-5860 add semantic contract requirement rows below each
futures/perpetual risk-proof requirement. These rows enumerate the exact
missing contract refs derived from existing futures semantic guards, expose
runtime-observed evidence as display-only, and keep semantic contract
registration, proof acceptance, command route registration, command drafting,
Coinbase activity, reconciliation execution, state mutation, browser
authority, and BFF execution authority disabled.
M57 phases 5861-5880 add semantic contract definition rows for those refs.
Each row names the missing backend definition contract, validation gate,
acceptance gate, required/missing evidence refs, definition readiness false,
validation readiness false, and runtime-evidence-satisfies-definition false.
These rows remain backend-owned display evidence and do not register semantic
contracts, satisfy proof acceptance, enable command routes, create drafts, call
Coinbase, execute reconciliation, mutate state, or grant browser/BFF authority.
M57 phases 5881-5900 add semantic contract validation gate rows for those
definitions. Each row names the missing backend validator contract,
validation input refs, required/missing evidence refs, validation readiness
false, validator registered false, and runtime-evidence-satisfies-validation
false. These rows remain backend-owned display evidence and do not register
validators, make definitions ready, satisfy proof acceptance, enable command
routes, create drafts, call Coinbase, execute reconciliation, mutate state, or
grant browser/BFF authority.
M57 phases 5901-5920 add semantic validator contract rows for those validation
gates. Each row names the missing backend validator contract, input schema ref,
output schema ref, registration ref, required/missing evidence refs, validator
contract registered false, validator registered false, validation readiness
false, and runtime-evidence-satisfies-validator-contract false. These rows
remain backend-owned display evidence and do not register validator contracts,
register schemas, register validators, satisfy proof acceptance, enable command
routes, create drafts, call Coinbase, execute reconciliation, mutate state, or
grant browser/BFF authority.
M57 phases 5921-5940 add semantic validator input schema rows for those
validator contracts. Each row names the missing backend input schema contract,
input schema field refs, schema registration evidence, required/missing
evidence refs, input-schema registered false, validator-contract registered
false, validator registered false, validation readiness false, and
runtime-evidence-satisfies-input-schema false. These rows remain backend-owned
display evidence and do not satisfy input schemas, register schemas, register
validator contracts, register validators, satisfy proof acceptance, enable
command routes, create drafts, call Coinbase, execute reconciliation, mutate
state, or grant browser/BFF authority.
M57 phases 5941-5960 add semantic validator output schema rows for those
validator contracts. Each row names the missing backend output schema contract,
output schema field refs, schema registration evidence, required/missing
evidence refs, output-schema registered false, validator-contract registered
false, validator registered false, validation readiness false, and
runtime-evidence-satisfies-output-schema false. These rows remain backend-owned
display evidence and do not satisfy output schemas, register schemas, register
validator contracts, register validators, satisfy proof acceptance, enable
command routes, create drafts, call Coinbase, execute reconciliation, mutate
state, or grant browser/BFF authority.
M57 phases 5961-5980 add semantic validator registration rows for those
validator contracts. Each row names the missing backend registration contract,
registry record, validator contract ref, input schema ref, output schema ref,
registration field refs, required/missing evidence refs, validator registration
ready false, validator registered false, validation readiness false, and
runtime-evidence-satisfies-validator-registration false. These rows remain
backend-owned display evidence and do not satisfy validator registration,
register validators, satisfy proof acceptance, enable command routes, create
drafts, call Coinbase, execute reconciliation, mutate state, or grant
browser/BFF authority.
M57 phases 5981-6000 add disabled futures/perpetual command-service contract
evidence. `place_futures_order`, `close_or_reduce_futures_position`, and
`cancel_futures_order` now exist as disabled backend service methods and the
command-suite marks the backend command-service prerequisite resolved for those
commands. This is not execution authority: futures risk guard, reconciliation,
command routes, command drafts, live adapters, Coinbase calls, reconciliation
execution, state mutation, browser authority, BFF authority, and spot-rule
authority remain blocked. The command-suite keeps the service contracts in
`required_backend_contracts` while removing them from
`missing_backend_contracts`; the next missing backend contracts are the futures
risk guard and reconciliation plan contracts.
M57 phases 6001-6020 add disabled futures/perpetual risk-guard contract
evidence. `evaluate_futures_margin_collateral_liquidation` now exists as a
disabled backend risk-guard method and the command-suite keeps the risk-guard
contract required but no longer reports it missing. This is not proof
acceptance or execution authority: reconciliation, command routes, command
drafts, live adapters, Coinbase calls, reconciliation execution, state
mutation, browser authority, BFF authority, and spot-rule authority remain
blocked. The next missing backend contract is
`application/admin_api/futures_reconciliation.py::record_futures_reconciliation_plan`.
M57 phases 6021-6040 completed that reconciliation gap by adding disabled
backend-owned `record_futures_reconciliation_plan` contract evidence only.
Reconciliation remains required and is no longer the missing backend contract.
M57 phases 6041-6060 completed disabled futures route-registration contract
metadata only. Route refs are required/present disabled evidence, but no futures
command route is registered. M57 phases 6061-6080 add disabled futures
live-adapter contract metadata only. Adapter contract refs are
required/present disabled evidence, but no adapter is configured, constructed,
or invokable. M57 phases 6081-6100 add disabled futures adapter-construction
contract metadata only. Adapter-construction refs are required/present disabled
evidence, but no adapter is constructed or invokable. M57 phases 6101-6120 add
disabled futures adapter-decision contract metadata only. Adapter-decision refs
are required/present disabled evidence. M57 phases 6121-6140 add disabled
futures adapter-decision-record contract metadata only. Adapter decision-record
refs are required/present disabled evidence. M57 phases 6141-6160 add disabled
futures adapter-invocation contract metadata only. Adapter invocation refs are
required/present disabled evidence. M57 phases 6161-6180 add disabled futures
adapter-execution contract metadata only. Adapter execution refs are
required/present disabled evidence. M57 phases 6181-6200 add disabled futures
Coinbase exchange-submission contract metadata only. Coinbase
exchange-submission refs are required/present disabled evidence. M57 phases
6201-6220 add disabled futures post-exchange-submission reconciliation contract
metadata only. Post-exchange-submission reconciliation refs are
required/present disabled evidence and no live reconciliation or trading
authority is created. M57 phases 6221-6240 add aggregate command enablement
blocker summaries to the read-only futures command suite so operators can see
why unresolved prerequisites, request payload contracts, semantic guard
evidence, risk proof acceptance, admin command routes, live service adapters,
and contextless review still block command authority. M57 phases 6241-6260 add
backend-owned command enablement sequence steps to the same read-only command
suite. The sequence is derived from existing readiness closure steps and does
not register command routes, create drafts, configure adapters, call Coinbase,
execute reconciliation, mutate futures/order/exchange state, or grant browser
or BFF authority. M57 phases 6261-6280 add backend-owned
`command_enablement_sequence_command_traces` derived from the same readiness
closure steps so each aggregate sequence step can be traced to exact
per-command evidence without creating route, draft, Coinbase, reconciliation,
state-mutation, browser, BFF, or spot-rule authority. M57 phases 6281-6300 add
disabled reconciliation command-service parity evidence through
`reconcile_futures_position` while preserving
`record_futures_reconciliation_plan` as the separate required reconciliation
contract. M57 phases 6301-6320 add disabled futures/perpetual proof
route/writer contract registry evidence through `FUTURES_PROOF_ROUTE_CONTRACTS`
and `FUTURES_PROOF_WRITER_CONTRACTS`; those registries do not register proof
routes, create proof writers, accept proof records, or grant execution
authority. M57 phases 6321-6340 add disabled futures/perpetual proof
payload-field contract registry evidence through
`FUTURES_PROOF_PAYLOAD_FIELD_CONTRACTS` and
`iter_futures_proof_payload_field_contracts`; those registry rows do not
validate submitted proof payloads, register validators, accept proof records,
create proof writers, create command drafts, call Coinbase, execute
reconciliation, mutate futures/order/exchange state, or grant browser/BFF
authority. M57 phases 6341-6360 added route-bound no-live futures/perpetual
command drafts for placement, close/reduce, cancel by `client_order_id`, and
reconciliation through the shared Admin API command service. These routes
return disabled command responses and do not bind live adapters, submit or
cancel Coinbase orders, acknowledge exchange orders, execute reconciliation,
mutate futures/order/exchange state, accept proof records as command
readiness, or grant browser/BFF authority. Completed M57 phases 6361-6380 added
disabled futures/perpetual request payload contract registry evidence through
`FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS` and
`iter_futures_request_payload_contracts`; command-suite `request_field_count`,
`blocking_request_field_count`, and request-field `required_backend_contracts`
derive from that backend-owned registry. Route/draft flags remain true while
execution remains false. Completed M57 phases 6381-6400 added explicit
disabled validation gate refs, validator refs, and false readiness flags to
those request fields. Completed M57 phases 6401-6420 added disabled
futures request payload validator contract registry evidence through
`application/admin_api/futures_request_payload_validators.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATOR_CONTRACTS`, and
`iter_futures_request_payload_validator_contracts`; command-suite
`request_payload_validator_contract_count`,
`blocking_request_payload_validator_contract_count`, and
`request_payload_validator_contracts` expose validator input/output schema refs
and false schema/validator registration flags. Completed M57 phases 6421-6440 add
disabled futures request payload validator input-schema evidence through
`application/admin_api/futures_request_payload_validator_input_schemas.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATOR_INPUT_SCHEMA_CONTRACTS`, and
`iter_futures_request_payload_validator_input_schemas`; command-suite
`request_payload_validator_input_schema_count`,
`blocking_request_payload_validator_input_schema_count`,
`request_payload_validator_input_schemas`, `input_schema_field_refs`,
`input_schema_field_count`, and `input_schema_registered=false` remain
backend-owned display evidence while preserving no validation, no validator
registration, no Coinbase calls, no reconciliation execution, no
futures/order/exchange state mutation, and no browser/BFF or spot-rule
authority. Completed M57 phases 6441-6460 add disabled futures request
payload validator output-schema evidence through
`application/admin_api/futures_request_payload_validator_output_schemas.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATOR_OUTPUT_SCHEMA_CONTRACTS`, and
`iter_futures_request_payload_validator_output_schemas`; command-suite
`request_payload_validator_output_schema_count`,
`blocking_request_payload_validator_output_schema_count`,
`request_payload_validator_output_schemas`, `output_schema_field_refs`,
`output_schema_field_count`, and `output_schema_registered=false` remain
backend-owned display evidence. Completed M57 phases 6461-6480 add disabled
futures request payload validator registration evidence through
`application/admin_api/futures_request_payload_validator_registrations.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATOR_REGISTRATION_CONTRACTS`, and
`iter_futures_request_payload_validator_registrations`; command-suite
`request_payload_validator_registration_count`,
`blocking_request_payload_validator_registration_count`,
`request_payload_validator_registrations`,
`validator_registration_field_refs`, `validator_registration_field_count`,
`validator_registration_ready=false`, and
`runtime_evidence_satisfies_validator_registration=false` remain backend-owned
display evidence while preserving no validator registration, no payload
validation, no Coinbase calls, no reconciliation execution, no futures/order/
exchange state mutation, and no browser/BFF or spot-rule authority.
Completed M57 phases 6481-6500 add disabled futures request payload validation
evidence through
`application/admin_api/futures_request_payload_validation_evidence.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_CONTRACTS`, and
`iter_futures_request_payload_validation_evidence`; command-suite
`request_payload_validation_evidence_count`,
`blocking_request_payload_validation_evidence_count`,
`ready_request_payload_validation_evidence_count`,
`recorded_request_payload_validation_evidence_count`,
`runtime_observed_request_payload_validation_evidence_count`, and
`request_payload_validation_evidence` remain backend-owned display evidence.
Rows expose `validation_evidence_contract_ref`,
`validation_evidence_field_refs`, `validation_evidence_field_count`,
`runtime_evidence_satisfies_validation_evidence=false`,
`validation_evidence_ready=false`, and
`validation_evidence_recorded=false` while preserving no validation evidence
recording, no payload validation, no Coinbase calls, no reconciliation
execution, no futures/order/exchange state mutation, and no browser/BFF or
spot-rule authority.
Completed M57 phases 6501-6520 add disabled futures request payload validation
evidence record contract evidence through
`application/admin_api/futures_request_payload_validation_evidence_records.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_RECORD_CONTRACTS`, and
`iter_futures_request_payload_validation_evidence_records`; command-suite
`request_payload_validation_evidence_record_count`,
`blocking_request_payload_validation_evidence_record_count`,
`ready_request_payload_validation_evidence_record_count`,
`stored_request_payload_validation_evidence_record_count`,
`runtime_observed_request_payload_validation_evidence_record_count`, and
`request_payload_validation_evidence_records` remain backend-owned display
evidence. Rows expose `validation_record_contract_ref`,
`validation_record_store_ref`, `validation_record_writer_ref`,
`validation_record_replay_guard_ref`, `validation_record_field_refs`,
`validation_record_field_count`,
`runtime_evidence_satisfies_validation_record=false`,
`validation_record_contract_ready=false`,
`validation_record_store_ready=false`,
`validation_record_writer_enabled=false`,
`validation_record_replay_guard_ready=false`, `validation_recorded=false`,
`append_only_validation_record=false`,
`validation_record_idempotency_bound=false`, and
`request_payload_validated=false` while preserving no validation record
writing, no payload validation, no Coinbase calls, no reconciliation execution,
no futures/order/exchange state mutation, and no browser/BFF or spot-rule
authority.
Completed M57 phases 6541-6560 add disabled futures request payload validation
record replay guard evidence through
`application/admin_api/futures_request_payload_validation_record_replay_guards.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REPLAY_GUARD_CONTRACTS`, and
`iter_futures_request_payload_validation_record_replay_guards`; command-suite
`request_payload_validation_record_replay_guard_count`,
`blocking_request_payload_validation_record_replay_guard_count`,
`ready_request_payload_validation_record_replay_guard_count`,
`idempotency_bound_request_payload_validation_record_count`,
`runtime_observed_request_payload_validation_record_replay_guard_count`, and
`request_payload_validation_record_replay_guards` remain backend-owned display
evidence. Rows expose `validation_record_replay_guard_contract_ref`,
`validation_record_idempotency_contract_ref`,
`validation_record_replay_window_ref`,
`validation_record_duplicate_policy_ref`,
`validation_record_replay_guard_field_refs`,
`validation_record_replay_guard_field_count`,
`runtime_evidence_satisfies_validation_record_replay_guard=false`,
`validation_record_replay_guard_contract_ready=false`,
`validation_record_idempotency_contract_ready=false`,
`validation_record_replay_protected=false`, and
`validation_record_idempotency_bound=false` while preserving no idempotency
binding, no replay protection, no payload validation, no Coinbase calls, no
reconciliation execution, no futures/order/exchange state mutation, and no
browser/BFF or spot-rule authority. Carried-forward schema/log evidence from
6521-6540 remains exposed through
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SCHEMA_CONTRACTS` and
`iter_futures_request_payload_validation_record_schemas`.
Current M57 phases 7321-7340 add futures request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation dependency work-item claim-trace clearance-step review input store
requirement evidence through
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_input_store_requirements.py`,
Admin API models/read-service serialization, OpenAPI, generated frontend
schema, and frontend display. These rows are disabled evidence only: they do
not make stores available, configure writers, bind record keys, pass validation
or replay gates, accept or validate inputs, pass review gates, complete
clearance-step reviews, complete clearance steps, clear claim traces, admit
commands, execute reconciliation, call Coinbase, mutate futures/order/exchange
state, or grant browser/BFF or spot-rule authority. Completed M57 phases
7301-7320 carry forward futures request payload validation record
execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input evidence.

Completed M57 phases 7301-7320 add futures request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation dependency work-item claim-trace clearance-step review input
evidence through
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_inputs.py`,
Admin API models/read-service serialization, OpenAPI, generated frontend schema,
and frontend display. Completed M57 phases 7281-7300 carry forward futures
request payload validation record
execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review evidence.

Completed M57 phases 7281-7300 add futures request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation dependency work-item claim-trace clearance-step review evidence through
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_reviews.py`,
Admin API models/read-service serialization, OpenAPI, generated frontend schema,
and frontend display. Command-suite rows expose
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_ref`,
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_contract_ref`,
`record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_gate`,
`required_clearance_step_contract`,
`required_clearance_step_review_input_ref`,
`clearance_step_review_claim`,
`clearance_step_review_target_ref`,
`clearance_step_review_source_ref`,
`predecessor_clearance_step_review_refs`,
`successor_clearance_step_review_refs`,
`record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_required=true`,
`record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_ready=false`,
`record_validation_remediation_dependency_work_item_claim_trace_clearance_step_review_completed=false`,
`clearance_step_review_input_present=false`,
`clearance_step_review_input_accepted=false`,
`clearance_step_review_input_validated=false`,
`clearance_step_review_gate_passed=false`,
`clearance_step_ready=false`,
`clearance_step_completed=false` while carrying forward completed M57 phases
7261-7280 futures request payload validation record execution-eligibility
resolution-plan step review input store record-validation remediation
dependency work-item claim-trace clearance step evidence through
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_steps.py`,
Admin API models/read-service serialization, OpenAPI, generated frontend schema,
and frontend display. Command-suite rows expose
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_ref`,
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_step_contract_ref`,
`record_validation_remediation_dependency_work_item_claim_trace_clearance_step_gate`,
`required_clearance_plan_contract`,
`required_clearance_step_review_ref`,
`clearance_step_name`, `clearance_step_index`,
`clearance_step_review_ready=false`, `clearance_step_review_complete=false`,
`clearance_step_review_inputs_present=false`,
`clearance_step_review_gates_passed=false`,
`prior_clearance_step_complete=false`, and
`next_clearance_step_enabled=false` while carrying forward completed M57 phases
7241-7260 futures request payload validation record execution-eligibility
resolution-plan step review input store record-validation remediation
dependency work-item claim-trace clearance plan evidence through
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_plans.py`,
Admin API models/read-service serialization, OpenAPI, generated frontend schema,
and frontend display. Command-suite rows expose
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_plan_ref`,
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_trace_clearance_plan_contract_ref`,
`record_validation_remediation_dependency_work_item_claim_trace_clearance_plan_gate`,
`required_claim_trace_contract`,
`required_clearance_plan_store_ref`,
`clearance_plan_claim`, `clearance_plan_target_ref`,
`clearance_plan_source_ref`,
`record_validation_remediation_dependency_work_item_claim_trace_clearance_plan_ready=false`,
`record_validation_remediation_dependency_work_item_claim_trace_clearance_plan_created=false`,
`claim_trace_ready=false`, `claim_allowed=false`, `claim_resolved=false`,
`claim_review_accepted=false`, `contextless_review_passed=false`,
`execution_allowed=false`, and `live_order_submitted=false` while carrying
forward completed M57 phases 7221-7240 futures request payload validation
record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim trace evidence through
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_claim_traces.py`
and completed M57 phases 7201-7220 futures request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation dependency work-item evidence through
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_items.py`,
Admin API models/read-service serialization, OpenAPI, generated frontend schema,
and frontend display. Carried-forward command-suite rows expose
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_ref`,
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_work_item_contract_ref`,
`review_input_store_record_validation_remediation_dependency_work_item_kind`,
`record_validation_remediation_dependency_work_item_gate`,
`record_validation_remediation_dependency_work_item_action_refs`,
`record_validation_remediation_dependency_work_item_blockers`,
`record_validation_remediation_dependency_work_item_required=true`,
`record_validation_remediation_dependency_work_item_ready=false`,
`record_validation_remediation_dependency_work_item_created=false`,
`record_validation_remediation_dependency_work_item_claimed=false`,
`claim_ledger_registered=false`, `owner_review_accepted=false`,
`contextless_review_passed=false`, `accepts_evidence=false`, and
`writes_evidence=false` while carrying forward completed M57 phases 7181-7200
futures request payload validation record execution-eligibility resolution-plan
step review input store record-validation remediation dependency evidence
through
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependencies.py`,
Admin API models/read-service serialization, OpenAPI, generated frontend schema,
and frontend display. Command-suite rows expose
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_ref`,
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_dependency_contract_ref`,
`review_input_store_record_validation_remediation_dependency_kind`,
`record_validation_remediation_dependency_gate`,
`record_validation_remediation_dependency_action_refs`,
`record_validation_remediation_dependency_blockers`,
`record_validation_remediation_dependency_required=true`,
`record_validation_remediation_dependency_ready=false`,
`record_validation_remediation_dependency_resolved=false`,
`record_validation_remediation_dependency_performed=false`,
`record_validation_remediation_dependency_graph_ready=false`,
`record_validation_remediation_dependency_work_item_created=false`,
`record_validation_remediation_dependency_work_item_claimed=false`, and
`record_validation_remediation_dependency_claim_trace_created=false` while
carrying forward completed M57 phases 7161-7180 futures request payload
validation record execution-eligibility resolution-plan step review input store
record-validation remediation evidence through
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediations.py`,
Admin API models/read-service serialization, OpenAPI, generated frontend schema,
and frontend display. Parent remediation rows expose
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_ref`,
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediation_contract_ref`,
`review_input_store_record_validation_remediation_kind`,
`record_validation_remediation_required=true`,
`record_validation_remediation_ready=false`,
`record_validation_remediation_configured=false`,
`record_validation_remediation_performed=false`,
`record_validation_remediation_recorded=false`,
`record_validation_remediation_accepted=false`,
`record_validation_remediation_work_item_created=false`, and
`record_validation_remediation_dependency_ready=false` while carrying forward
completed M57 phases 7141-7160 futures request payload validation record
execution-eligibility resolution-plan step review input store record-validation
evidence through
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validations.py`,
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_ref`,
`execution_eligibility_resolution_plan_step_review_input_store_record_validation_contract_ref`,
`review_input_store_record_validation_kind`,
`record_validation_required=true`, `record_validation_ready=false`,
`record_validation_configured=false`, `record_validation_registered=false`,
`record_validation_gate_ready=false`, `record_validation_gate_passed=false`,
`record_validation_replay_guard_ready=false`,
`record_validation_schema_ready=false`,
`record_validation_append_only_log_ready=false`,
`record_validation_idempotency_bound=false`,
`record_validation_payload_bound=false`,
`record_validation_contextless_review_passed=false`,
`record_validation_performed=false`, `record_validation_accepted=false`, and
`record_validation_recorded=false` while carrying forward
`execution_eligibility_resolution_plan_step_review_input_store_record_contract_ref`,
`execution_eligibility_resolution_plan_step_review_input_store_record_contract_contract_ref`,
`review_input_store_record_contract_kind`,
`record_contract_required=true`, `record_contract_available=false`,
`record_schema_available=false`, `append_only_log_available=false`,
`idempotency_key_bound=false`, `payload_schema_validated=false`,
`replay_protected=false`, `store_available=false`,
`writer_available=false`, `writer_allowed=false`, `write_allowed=false`,
`record_present=false`, `record_accepted=false`, `record_validated=false`,
`validation_configured=false`, and `replay_protection_configured=false`.
Resolution plan step review input store record-validation remediation
dependency presence is disabled evidence only; it does not create dependency
graphs, create work items, claim work, create claim traces, perform
remediation, resolve blockers, create a store, configure a writer, allow
writes, accept records, validate records, accept runtime evidence, admit
commands, call Coinbase, execute reconciliation, mutate futures/order/exchange
state, or grant browser/BFF or spot-rule authority. Resolution plan step review
input store record-validation remediation presence
is disabled evidence only; it does not perform remediation, resolve blockers,
create a store, configure a writer, allow writes, accept records, validate
records, accept runtime evidence, admit commands, call Coinbase, execute
reconciliation, mutate futures/order/exchange state, or grant browser/BFF or
spot-rule authority. Resolution plan step review input store record-validation
presence is disabled
evidence only; it does not resolve blockers, create a store, configure a
writer, allow writes, accept records, validate records, accept runtime evidence,
admit commands, call Coinbase, execute reconciliation, mutate
futures/order/exchange state, or grant browser/BFF or spot-rule authority.
Active M57 `7321-7340` evidence adds futures request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation dependency work-item claim-trace clearance-step review input store
requirement evidence while completed M57 `7301-7320` carries forward futures
request payload validation record execution-eligibility resolution-plan step
review input store record-validation remediation dependency work-item
claim-trace clearance-step review input evidence.
Completed M57 `7301-7320` evidence adds futures request payload validation
record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance-step
review input evidence while completed M57 `7281-7300` carries forward futures
request payload validation record execution-eligibility resolution-plan step
review input store record-validation remediation dependency work-item
claim-trace clearance-step review evidence.
Completed M57 `7281-7300` evidence adds futures request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation dependency work-item claim-trace clearance-step review evidence while
completed M57 `7261-7280` carries forward futures request payload validation
record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance step
evidence and completed M57 `7241-7260` carries forward futures request payload validation
record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim-trace clearance plan
evidence and completed M57 `7221-7240` carries forward futures request payload validation
record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item claim trace evidence,
completed M57 `7201-7220` carries forward futures request payload validation
record execution-eligibility resolution-plan step review input store
record-validation remediation dependency work-item evidence, and completed M57
`7181-7200` carries forward futures request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation dependency evidence.
Completed M57 phases 7161-7180 add futures request payload validation record
execution-eligibility resolution-plan step review input store record-validation
remediation evidence through
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validation_remediations.py`.
Completed M57 phases 7141-7160 add futures request payload validation record
execution-eligibility resolution-plan step review input store record-validation
evidence through
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_validations.py`.
Completed M57 phases 7121-7140 add futures request payload validation record
execution-eligibility resolution-plan step review input store record-contract
evidence through
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_record_contracts.py`.
Completed M57 phases 7101-7120 add futures request payload validation record
execution-eligibility resolution-plan step review input store requirement
evidence through
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plans.py`,
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_steps.py`,
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_reviews.py`,
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_inputs.py`,
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_input_store_requirements.py`,
Admin API models/read-service serialization, OpenAPI, generated frontend schema,
and frontend display. Command-suite rows expose
`execution_eligibility_resolution_plan_ref`,
`execution_eligibility_resolution_plan_contract_ref`,
`execution_eligibility_resolution_plan_step_ref`,
`execution_eligibility_resolution_plan_step_contract_ref`,
`execution_eligibility_resolution_plan_step_review_ref`,
`execution_eligibility_resolution_plan_step_review_contract_ref`,
`execution_eligibility_resolution_plan_step_review_input_ref`,
`execution_eligibility_resolution_plan_step_review_input_contract_ref`,
`execution_eligibility_resolution_plan_step_review_input_store_requirement_ref`,
`execution_eligibility_resolution_plan_step_review_input_store_requirement_contract_ref`,
`resolution_plan_step_kind`, `resolution_plan_step_ready=false`,
`resolution_plan_step_accepted=false`,
`resolution_plan_step_review_required=true`,
`resolution_plan_step_review_ready=false`,
`resolution_plan_step_reviewed=false`,
`resolution_plan_step_review_accepted=false`, `review_input_kind`,
`review_input_index`, `input_evidence_store`,
`resolution_plan_step_review_input_required=true`,
`resolution_plan_step_review_input_present=false`,
`resolution_plan_step_review_input_accepted=false`,
`resolution_plan_step_review_input_validated=false`,
`resolution_plan_step_review_input_store_requirement_required=true`,
`resolution_plan_step_review_input_store_available=false`,
`resolution_plan_step_review_input_writer_available=false`,
`resolution_plan_step_review_input_record_key_available=false`,
`resolution_plan_step_review_input_validation_gate_ready=false`,
`resolution_plan_step_review_input_replay_gate_ready=false`,
`ordered_resolution_step_ref`,
`ordered_resolution_step_refs`, `ordered_resolution_step_count`,
`resolution_plan_present=true`, `resolution_plan_ready=false`,
`resolution_plan_accepted=false`,
`runtime_evidence_satisfies_semantic_contract=false`,
`validation_record_admission_link_ready=false`, and
`blocker_resolved=false`. Resolution plan step review input store requirement
presence is disabled evidence only; it does not resolve blockers, create a
store, configure a writer, create a record key, enable validation or replay
gates, accept runtime evidence, admit commands, call Coinbase, execute
reconciliation, mutate futures/order/exchange state, or grant browser/BFF or
spot-rule authority. Resolution plan step review input presence is not blocker
resolution. Resolution plan step review presence is not blocker resolution.
Completed M57 phases 7081-7100 add futures request payload validation record
execution-eligibility resolution-plan step review input evidence through
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_review_inputs.py`.
Completed M57 phases 7061-7080 add futures request payload validation record
execution-eligibility resolution-plan step review evidence through
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_step_reviews.py`.
Completed M57 phases 7041-7060 add futures request payload validation record
execution-eligibility resolution-plan step evidence through
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_steps.py`.
Completed M57 phases 7021-7040 add futures request payload validation record
execution-eligibility resolution-plan evidence through
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plans.py`.
Completed M57 phases 7001-7020 add futures request payload validation record
execution-eligibility semantic closure evidence through
`application/admin_api/futures_request_payload_validation_record_execution_eligibilities.py`,
`application/admin_api/futures_request_payload_validation_record_execution_eligibility_blockers.py`,
Admin API models/read-service serialization, OpenAPI, generated frontend schema,
and frontend display. Command-suite execution-eligibility rows expose the ten
`validation_record_*_semantics_contract_ref` fields,
`validation_record_semantic_contract_refs`,
`validation_record_semantic_contract_ref_count`,
`validation_record_semantic_contracts_present=true`, and
`validation_record_semantic_contracts_ready=false`. Blocker rows expose
`semantic_contract_ref`, `semantic_contract_present=true`, and
`semantic_contract_ready=false` while preserving the existing
`required_backend_artifact_ref` shape for downstream semantic-artifact evidence.
Semantic contract presence is disabled evidence only; it does not accept runtime
evidence, admit commands, call Coinbase, execute reconciliation, mutate
futures/order/exchange state, or grant browser/BFF or spot-rule authority.
Completed M57 `6981-7000` carries forward disabled futures request payload
validation record reconciliation semantics through
`application/admin_api/futures_request_payload_validation_record_reconciliation_semantics.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_RECONCILIATION_SEMANTIC_CONTRACTS`,
and `iter_futures_request_payload_validation_record_reconciliation_semantics`.
Completed M57 `6961-6980` carries forward disabled futures request payload
validation record cancel semantics through
`application/admin_api/futures_request_payload_validation_record_cancel_semantics.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_CANCEL_SEMANTIC_CONTRACTS`, and
`iter_futures_request_payload_validation_record_cancel_semantics`.
Completed M57 `6941-6960` carries forward disabled futures request payload
validation record order semantics through
`application/admin_api/futures_request_payload_validation_record_order_semantics.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_ORDER_SEMANTIC_CONTRACTS`, and
`iter_futures_request_payload_validation_record_order_semantics`.
Completed M57 phases 6921-6940 carry forward disabled futures request payload
validation record funding semantics through
`application/admin_api/futures_request_payload_validation_record_funding_semantics.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_FUNDING_SEMANTIC_CONTRACTS`,
and `iter_futures_request_payload_validation_record_funding_semantics`.
Command-suite
`request_payload_validation_record_funding_semantic_count`,
`blocking_request_payload_validation_record_funding_semantic_count`,
`ready_request_payload_validation_record_funding_semantic_count`,
`runtime_observed_request_payload_validation_record_funding_semantic_count`,
and `request_payload_validation_record_funding_semantics` remain
backend-owned display evidence. Rows expose `funding_semantics_ref`,
`funding_semantics_contract_ref`, `evidence_routes`,
`funding_semantics_contract_available=false`,
`funding_semantics_contract_ready=false`, `funding_rate_bound=false`,
`funding_fee_bound=false`, `funding_interval_bound=false`,
`funding_cost_bound=false`, `runtime_funding_evidence_observed=false`,
`runtime_evidence_satisfies_funding_semantics=false`, and
`validation_record_funding_semantics_ready=false` while preserving no payload
validation, no funding semantics acceptance, no live account/risk evidence
binding, no contextless review authority, no command admission, no Coinbase
calls, no reconciliation execution, no futures/order/exchange state mutation,
and no browser/BFF or spot-rule authority.
Completed M57 phases 6901-6920 carry forward disabled futures request payload
validation record close-only semantics through
`application/admin_api/futures_request_payload_validation_record_close_only_semantics.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_CLOSE_ONLY_SEMANTIC_CONTRACTS`,
and `iter_futures_request_payload_validation_record_close_only_semantics`.
Completed M57 phases 6881-6900 carry forward disabled futures request payload
validation record reduce-only semantics through
`application/admin_api/futures_request_payload_validation_record_reduce_only_semantics.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REDUCE_ONLY_SEMANTIC_CONTRACTS`,
and `iter_futures_request_payload_validation_record_reduce_only_semantics`.
Completed M57 phases 6861-6880 carry forward disabled futures request payload
validation record liquidation semantics through
`application/admin_api/futures_request_payload_validation_record_liquidation_semantics.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_LIQUIDATION_SEMANTIC_CONTRACTS`,
and `iter_futures_request_payload_validation_record_liquidation_semantics`.
Completed M57 phases 6841-6860 carry forward disabled futures request payload
validation record collateral semantics through
`application/admin_api/futures_request_payload_validation_record_collateral_semantics.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_COLLATERAL_SEMANTIC_CONTRACTS`,
and `iter_futures_request_payload_validation_record_collateral_semantics`.
Completed M57 phases 6821-6840 carry forward disabled futures request payload
validation record margin semantics through
`application/admin_api/futures_request_payload_validation_record_margin_semantics.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_MARGIN_SEMANTIC_CONTRACTS`,
and `iter_futures_request_payload_validation_record_margin_semantics`.
Completed M57 phases 6801-6820 carry forward disabled futures request payload
validation record position semantics through
`application/admin_api/futures_request_payload_validation_record_position_semantics.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_POSITION_SEMANTIC_CONTRACTS`,
and `iter_futures_request_payload_validation_record_position_semantics`.
Command-suite
`request_payload_validation_record_position_semantic_count`,
`blocking_request_payload_validation_record_position_semantic_count`,
`ready_request_payload_validation_record_position_semantic_count`,
`runtime_observed_request_payload_validation_record_position_semantic_count`,
and `request_payload_validation_record_position_semantics` remain
backend-owned display evidence. Rows expose `position_semantics_ref`,
`position_semantics_contract_ref`, `evidence_routes`,
`position_semantics_contract_available=false`,
`position_semantics_contract_ready=false`, `position_identity_bound=false`,
`position_scope_bound=false`, `position_side_derivation_bound=false`,
`position_size_bound=false`, `position_notional_bound=false`,
`runtime_position_evidence_observed=false`,
`runtime_evidence_satisfies_position_semantics=false`, and
`validation_record_position_semantics_ready=false` while preserving no payload
validation, no position semantics acceptance, no live position evidence
binding, no command admission, no Coinbase calls, no reconciliation execution,
no futures/order/exchange state mutation, and no browser/BFF or spot-rule
authority.
Completed M57 phases 6781-6800 carry forward disabled futures request payload validation
record semantic artifact runtime evidence acceptance through
`application/admin_api/futures_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS`,
and
`iter_futures_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances`.
Completed M57 phases 6761-6780 carry forward disabled futures request payload validation
record semantic artifact runtime evidence binding through
`application/admin_api/futures_request_payload_validation_record_semantic_artifact_runtime_evidences.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_CONTRACTS`,
and
`iter_futures_request_payload_validation_record_semantic_artifact_runtime_evidences`;
command-suite
`request_payload_validation_record_semantic_artifact_runtime_evidence_count`,
`blocking_request_payload_validation_record_semantic_artifact_runtime_evidence_count`,
`ready_request_payload_validation_record_semantic_artifact_runtime_evidence_count`,
`runtime_observed_request_payload_validation_record_semantic_artifact_runtime_evidence_count`,
and
`request_payload_validation_record_semantic_artifact_runtime_evidences`
remain backend-owned display evidence. Rows expose
`semantic_artifact_runtime_evidence_ref`,
`semantic_artifact_runtime_evidence_contract_ref`,
`semantic_artifact_runtime_evidence_available=false`,
`semantic_artifact_runtime_evidence_bound=false`, and
`semantic_artifact_runtime_evidence_accepted=false` while preserving no
payload validation, no review input/output acceptance, no runtime evidence
binding or acceptance, no contextless review pass, no command admission, no
Coinbase calls, no reconciliation execution, no futures/order/exchange state
mutation, and no browser/BFF or spot-rule authority. Completed 6741-6760
output-acceptance evidence remains available through
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_ACCEPTANCE_CONTRACTS`
and
`iter_futures_request_payload_validation_record_semantic_artifact_definition_review_output_acceptances`.
Completed output-acceptance command-suite fields include
`request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count`,
`blocking_request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count`,
`ready_request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count`,
`runtime_observed_request_payload_validation_record_semantic_artifact_definition_review_output_acceptance_count`,
and
`request_payload_validation_record_semantic_artifact_definition_review_output_acceptances`
as backend-owned display evidence. Rows expose
`semantic_artifact_definition_review_output_acceptance_ref`,
`semantic_artifact_definition_review_output_acceptance_contract_ref`,
`semantic_artifact_definition_review_output_ref`,
`semantic_artifact_definition_review_output_contract_ref`,
`semantic_artifact_definition_review_ref`,
`semantic_artifact_definition_review_contract_ref`,
`semantic_artifact_definition_ref`,
`semantic_artifact_definition_contract_ref`,
`contextless_review_required=true`,
`semantic_artifact_definition_review_output_acceptance_available=false`,
and `semantic_artifact_definition_review_output_acceptance_accepted=false`.
Completed 6721-6740 review-output evidence remains available through
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_OUTPUT_CONTRACTS`
and
`iter_futures_request_payload_validation_record_semantic_artifact_definition_review_outputs`.
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
Stealth post-write reconciliation execution-policy evidence is exposed through
`GET /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-execution-policy`
and persisted through
`POST /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-execution-policy-proofs`.
The writer route requires `stealth_post_write_reconciliation_policy:record`,
uses path `stealth_order_id` as the command identity, and persists append-only
local proof evidence only after exact backend admission prerequisites match.
It does not execute reconciliation, invoke managers, call Coinbase,
submit/cancel/read Coinbase orders, cancel/replace active placements, mutate
order/lifecycle/exchange state, or grant browser/BFF authority.
Stealth state-mutation policy evidence is exposed through
`GET /api/v1/stealth/orders/{stealth_order_id}/state-mutation-policy` and
persisted through
`POST /api/v1/stealth/orders/{stealth_order_id}/state-mutation-policy-proofs`.
The writer route requires `stealth_state_mutation_policy:record`, uses path
`stealth_order_id` as the command identity, and persists append-only local
proof evidence only after exact backend admission prerequisites match. It
does not authorize or perform lifecycle, order, or exchange-state mutation,
invoke managers, call Coinbase, submit/cancel/read Coinbase orders,
cancel/replace active placements, execute reconciliation, or grant browser/BFF
authority. Create and non-create execution prerequisite resolvers may consume the
newest exact safe proof row as `state_mutation_policy` prerequisite evidence.
That still does not clear live-readiness decisions or authorize execution by
itself.
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
and display/forward-only browser/BFF authority. It also reports unresolved
backend-only enablement preconditions: the explicit live-enablement decision,
configured Admin API live execution service, runtime live-service
configuration, deployment enablement record, verification gates, and blockers.
If an append-only disabled live-service decision has been recorded, the
contract may show it as latest decision readback with `resolves=false`; this
does not remove any missing artifact or clear the live-service blocker. The
contract must show recorded decision artifacts separately from satisfied
enablement artifacts so a reader cannot treat readback as service
enablement.
Those fields are blockers, not authority. They are not a service
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
action rows, and summary are context for future backend work only.
`backend_decision_resolution_summary` aggregates the full backend decision
ledger with blocked decision counts, owners, required artifacts, missing
reasons, first blocker, and clearance action totals while keeping resolver,
writer, completion, execution, manager, Coinbase, reconciliation, mutation,
browser, and BFF authority disabled.
`forbidden_execution_claim_evidence` and
`forbidden_execution_claim_summary` map each raw forbidden execution claim to
the backend decision, required clearance category/ref, work queue ref, backend
contract/route/method/service, evidence ref, and disabled claim-cleared,
resolver, writer, and execution flags that keep it blocked. These rows are
traceability only; they do not clear claims, write decisions, execute
resolvers, invoke managers, call Coinbase, cancel/replace placements,
reconcile, mutate state, or grant browser/BFF authority.
`backend_decision_resolution_work_items` and
`backend_decision_resolution_work_queue_summary` expose the first blocked
clearance action for each unresolved backend decision as a cross-decision
read-only work queue with owner, artifact, contract, evidence ref, dependency
state, and disabled resolver/writer/execution flags. These summaries and work
queue rows are not a resolver, decision writer, live service switch, live
adapter, manager invocation path, Coinbase path, reconciliation executor,
state mutation path, browser authority, or BFF execution authority.
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
disabled and non-executable. It also reports backend-only construction
preconditions, required/missing construction artifacts, verification gates, and
blockers while keeping `construction_precondition_resolved` false until a
future approved backend phase binds the adapter through the shared command
service. It also separates route-mapping/configuration evidence from satisfied
construction artifacts: `route_mapping_satisfies_construction=false`,
`adapter_configuration_satisfies_construction=false`,
`satisfied_construction_artifacts=[]`, and
`unsatisfied_construction_artifacts` still names the required construction
artifacts. It is not an adapter implementation, live switch, Coinbase caller,
manager invocation path, or BFF execution grant.
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
The `remaining_execution_blockers` rows inside those contracts also carry
trace fields for live-service and live-adapter blockers. Trace fields identify
the blocker authority, backend contract refs, evidence refs, required and
missing artifacts, verification gates, and contract blockers that keep live
service enablement and adapter construction unresolved. They are diagnostic
evidence only; they do not resolve live readiness, construct adapters, call
Coinbase, invoke managers, execute reconciliation, mutate state, or grant
browser/BFF execution authority.
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
active-placement exchange truth, mutation claims, state-mutation policy, live
service, live adapter, or post-write reconciliation. Unsafe latest proof evidence remains
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
- `GET /api/v1/futures/command-suite`
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
are not backend approval to trade. These checks do not replace focused backend
checks for ordinary backend changes or the full backend regression gate when a
durable milestone, release/deployment handoff, release-hardening closeout,
Admin API/backend association closeout, or explicit user request requires it.
When that full backend gate is required, use
`python tools/run_parallel_regression.py --workers 4`; sequential
`pytest tests/regression/ -v --tb=short` is fallback-only when the parallel
runner cannot be used.
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
- Idempotency replay stores normal command responses inline in JSONL. If a
  response is large enough to make the JSONL store unsafe, the same store
  writes the response body to a sibling gzip blob, records the blob hash and
  relative path, and hydrates that response only for a same-hash replay. The
  replay behavior stays on the same idempotency path; the gzip blob is storage
  compaction, not a second command or audit implementation.
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

## Completed M57 Validation Record Schema Evidence

Completed phases `6501-6520` add disabled futures request payload validation
evidence record contract evidence through
`application/admin_api/futures_request_payload_validation_evidence_records.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_RECORD_CONTRACTS`, and
`iter_futures_request_payload_validation_evidence_records`. The command suite
continues to expose validation-evidence, input-schema, output-schema, and
registration evidence and now also exposes
`request_payload_validation_evidence_record_count`,
`blocking_request_payload_validation_evidence_record_count`,
`ready_request_payload_validation_evidence_record_count`,
`stored_request_payload_validation_evidence_record_count`,
`runtime_observed_request_payload_validation_evidence_record_count`,
`request_payload_validation_evidence_records`,
`validation_record_contract_ref`, `validation_record_store_ref`,
`validation_record_writer_ref`, `validation_record_replay_guard_ref`,
`validation_record_field_refs`, `validation_record_field_count`,
`required_evidence_refs`, `missing_evidence_refs`,
`runtime_evidence_satisfies_validation_record=false`,
`validation_record_contract_ready=false`,
`validation_record_store_ready=false`,
`validation_record_writer_enabled=false`,
`validation_record_replay_guard_ready=false`, `validation_recorded=false`,
`append_only_validation_record=false`, and
`validation_record_idempotency_bound=false`. These rows are backend-owned
display evidence only; they do not validate command request payloads, write
validation records, register record stores, call Coinbase, execute
reconciliation, mutate futures/order/exchange state, or grant browser/BFF
authority.

Completed phases `6521-6540` add disabled futures request payload validation
record schema and append-only log evidence through
`application/admin_api/futures_request_payload_validation_record_schemas.py`,
`FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SCHEMA_CONTRACTS`, and
`iter_futures_request_payload_validation_record_schemas`. The command suite
continues to expose validation-evidence record rows and now also exposes
`request_payload_validation_record_schema_count`,
`blocking_request_payload_validation_record_schema_count`,
`ready_request_payload_validation_record_schema_count`,
`registered_request_payload_validation_record_schema_count`,
`runtime_observed_request_payload_validation_record_schema_count`,
`request_payload_validation_record_schemas`,
`validation_record_schema_ref`, `validation_record_append_only_log_ref`,
`validation_record_schema_field_refs`, `validation_record_schema_field_count`,
`runtime_evidence_satisfies_validation_record_schema=false`,
`validation_record_schema_ready=false`,
`validation_record_schema_registered=false`, and
`validation_record_append_only_log_ready=false`. These rows are backend-owned
display evidence only; they do not register schemas, write append-only
validation logs, validate command request payloads, write validation records,
call Coinbase, execute reconciliation, mutate futures/order/exchange state, or
grant browser/BFF authority.
