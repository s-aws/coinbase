# Command Workflows

This backend document explains how enterprise admin command evidence is exposed
without creating a second trading path.

The Admin API may expose command contracts, dry-submit evidence, and readiness
coverage for order, cancel, stealth, movement/repricing, approval, audit,
cap/guard, reconciliation, and campaign workflows. The backend remains the only
authority for trading behavior, wallet checks, guard checks, approval state,
reconciliation state, live adapter execution, and Coinbase calls.

Dry-submit means an audited, idempotent command-shaped Admin API POST may be
sent to the backend and may create backend audit/idempotency evidence. It is
still no-live: the expected command result is live-disabled or prerequisite
rejection evidence, not Coinbase submission.

## Current Contract

- Backend route inventory is the source of command route identity, action class,
  permissions, shared service method, and live designation.
- OpenAPI schemas are generated from backend FastAPI models and must be
  regenerated after contract changes.
- The frontend consumes generated contracts or typed wrappers only. It may
  display evidence, draft requests, and forward requests to backend routes when
  those routes exist, but it must not compute trading authority or call
  Coinbase.
- Live command execution stays disabled unless a backend route explicitly
  reports passing approval, cap/guard, admission audit, reconciliation, live
  adapter, and operator-intent gates.

## Spot Command Suite

`GET /api/v1/spot/command-suite` is read-only M54 evidence. It reports whether
manual spot order placement, spot cancel, spot campaign execution, and spot
sweep automation have the required backend gates and shared command-service
wiring.

This route does not submit orders, cancel orders, launch campaigns, mutate
wallet or order state, or call Coinbase. Command rows use `mutation_family`
enum values such as `spot_manual_order`, `spot_order_cancel`, and
`spot_campaign_execution`, and `spot_sweep_automation`. A row's `status` is
gate status, while `live_execution_status` is the live-execution posture.

Each command row also reports `proof_routes` for the backend-owned local-state
records that must exist before the command can become executable: approval
request/decision, admission audit, cap/guard decision, and reconciliation
plan. Those proof routes are derived from `ADMIN_API_ROUTE_INVENTORY`; the
frontend may display them but must not evaluate the gates, synthesize proof,
or treat them as live approval.

Each command row also reports `readiness_preconditions` by reusing
`AdminLiveReadinessPreconditionItem` from live-enablement evidence. These
preconditions show source, expected source, blocker, configured/blocking
state, and browser/BFF boundary for approval-store, approval snapshot,
admission audit, cap/guard, reconciliation, live adapter, execution-intent,
browser/BFF boundary, and live service gates. They are status evidence only;
they do not create proof records, evaluate gates in the browser, enable BFF
execution, or call Coinbase.

Website command workflow draft cards may display the same backend-owned
`readiness_preconditions` beside draft payload evidence for spot manual order,
cancel by `client_order_id`, campaign execution, and sweep automation. That
display is a trace back to command-suite evidence only; it must not evaluate
readiness, create proof records, enable commands, launch sweep tools, create a
browser scheduler, or copy spot wallet/no-shorting rules into non-spot modules.

The command-suite response also reports `coverage_gaps` for remaining M54 spot
families that are not command-complete: sweep automation, recovery workflow,
and reconciliation workflow. Gap rows are separate from
`mutation_family` command rows. They may name current read evidence,
checkpoint record evidence, missing backend contracts, required gate chains,
and browser/BFF boundaries, but they must not become command workflow drafts,
BFF mutation routes, browser profitability or sell authority, reconciliation
execution, tax accounting, or Coinbase calls.

Gap rows also report typed `current_read_evidence` rows derived from
`ADMIN_API_ROUTE_INVENTORY`. These rows identify the existing read-only Admin
API route, method, permission, shared read-service method, documentation refs,
and display/forward-only boundary that supports the gap. They are navigation
and traceability evidence only; they do not create command routes or satisfy
the missing backend contracts.
The stealth command-suite uses the same pattern for blocked recovery and
reconciliation gaps. Those rows may point to
`GET /api/v1/admin/recovery-gate`,
`GET /api/v1/admin/reconciliation/plans`,
`GET /api/v1/admin/reconciliation/plans/{plan_id}`, and stealth read
surfaces. They remain backend-owned read evidence only; they must not execute
stealth recovery or reconciliation commands, write proof records, execute
reconciliation, mutate stealth/order/exchange state, call Coinbase, trust
browser exchange evidence, or grant browser/BFF execution authority.
Stealth `exchange_truth_checks` also expose typed `current_read_evidence`
rows. These rows are read-only traceability for the local evidence currently
available behind blocked create, reveal, cancel, move, recovery,
reconciliation, and reprice
prerequisites. They do not run Coinbase reads, prove active placement exchange
truth, cancel/replace placements, reveal orders, satisfy missing backend
contracts, execute reconciliation, mutate state, or grant browser/BFF
execution authority.
Stealth `admission_readiness` rows bind each command route to its exact
backend-owned proof requirements: approval request/decision, admission audit,
cap/guard decision, reconciliation plan, active-placement exchange truth or
lifecycle-write guard, disabled live adapter, and post-live reconciliation.
They remain blocked display evidence. They do not approve commands, execute
commands, read Coinbase, invoke `StealthOrderManager`, cancel/replace
placements, execute reconciliation, mutate state, or grant browser/BFF
execution authority.
Those rows also report command-envelope context requirements. Static route
metadata is present, but `stealth_order_id`, `actor_id`, `idempotency_key`,
`operator_intent`, and `payload_hash` are missing in the read-only response,
so resolver lookup and proof resolution remain disabled.
When a live-disabled stealth command is dry-submitted through the backend
command path, the response may include `stealth_admission_context`. That echo
uses the concrete request envelope to report exact route, identity, actor,
idempotency, operator-intent, and payload-hash context plus resolver/proof
lookup posture. The echo is not a guard result or approval source; command
workflow surfaces may display it only and must not use it to execute, call
Coinbase, cancel/replace placements, reconcile, mutate state, or broaden BFF
authority.
The read-only stealth command-suite may also expose
`selected_create_pre_execution_contract` from completed phases 5121-5140 as a
selected-create planning/read review aid. For active phases 5141-5160, the dry
`POST /api/v1/stealth/orders` command response may expose the same contract
with exact command-envelope and payload-present fields. It names the backend route,
payload, approval/admission, lifecycle-write, manager, idempotency/audit,
guard/account-condition, reconciliation, and Coinbase non-interaction
boundaries required before future create execution. It must not become a
browser create control, BFF executor, proof input writer, manager invocation,
Coinbase call, reconciliation executor, or lifecycle/order state mutation.

`POST /api/v1/spot/sweep/automation-runs` is the route-bound sweep automation
command contract. It is keyed by `sweep_config_id`, requires
`spot_sweep:execute`, records idempotency/audit/admission evidence, and
currently returns `501 not_implemented` with `live_exchange_submitted=false`.
It must not call `tools/run_spot_portfolio_sweep_live.py`, invoke Coinbase,
create a browser scheduler, or close the wider sweep automation gap until the
durable scheduler, run-limit, recovery, and reconciliation contracts exist.

`POST /api/v1/spot/pnl/checkpoints` is a backend-owned local-state mutation
for durable operator-review records sourced from
`/api/v1/spot/sweep/pnl`. It requires `spot_pnl:record`, idempotency, and
audit evidence, and read evidence is available through
`GET /api/v1/spot/pnl/checkpoints` and
`GET /api/v1/spot/pnl/checkpoints/{checkpoint_id}`. It is not a command
workflow draft, sell guard, profitability authority, reconciliation executor,
tax-accounting ledger, or Coinbase order path.
When the request includes `average_cost_snapshot`, the same checkpoint path is
the average-cost review evidence contract. It must not be replaced with a
second average-cost writer or interpreted as sell/profit authority.
Accepted checkpoint records also expose verified append-only Admin API audit
link readback for the local-state mutation. That link must not be replaced
with a second checkpoint audit writer or interpreted as browser audit
authority, recovery execution, reconciliation execution, or Coinbase execution
authority. A checkpoint with an `audit_id` but no matching audit row is
reported as unverified checkpoint evidence.
Accepted checkpoint records also expose read-only recovery-link evidence to
`GET /api/v1/admin/recovery-gate` and
`GET /api/v1/admin/fill-ledger-health`. That link is triage evidence only; it
must not be interpreted as recovery execution, repair apply, rollback,
reconciliation execution, Coinbase execution, browser recovery authority, or a
separate checkpoint writer.
The dedicated recovery read-contract routes,
`GET /api/v1/spot/recovery/preview`,
`GET /api/v1/spot/recovery/apply-review`,
`GET /api/v1/spot/recovery/rollback-plan`, and
`GET /api/v1/spot/recovery/reconciliation-proof`, extend that read-only
evidence with preview candidates from recovery-gate, fill-ledger-health,
optional direct-order audit lookup, apply-review gate dependencies, rollback
prerequisites, reconciliation-proof field requirements, state-repair taxonomy,
repair-target evidence, pre-apply snapshots, dry-run repair plans, and
completion-state evidence. They close the read-contract gap only. POST
contracts also exist for recovery apply execution, rollback execution,
exchange-state proof recording, exchange-state snapshot recording, and
reconciliation-proof recording. Apply and rollback remain fail-closed for
order/exchange-state mutation, Coinbase activity, and reconciliation
execution; guarded backend local repair-result journals are allowed only when
the repair guard matches exactly. The proof and snapshot POST routes persist
append-only backend local evidence only after approval, admission audit,
cap/guard, reconciliation plan, idempotency, and audit prerequisites match.
The snapshot route also requires the matching proof and completion chain and
records `coinbase_read_attempted=false`/`coinbase_read_succeeded=false`.
Reconciliation-proof POST may also persist a guarded post-apply completion
record when the existing proof, apply journal, repair-result, approval,
admission audit, cap/guard, reconciliation-plan, idempotency,
operator-intent, and payload-hash evidence matches exactly. The
reconciliation-proof read route also exposes
fail-closed reconciliation execution boundary rows keyed by `client_order_id`;
these rows name the disabled
`POST /api/v1/spot/recovery/reconciliation-executions` route, the
`execute_spot_recovery_reconciliation` service boundary, required inputs, and
remaining blockers including `coinbase_live_read_disabled`. That route is
audited, idempotent, RBAC-protected, and fail-closed; it must not roll back
order state, execute reconciliation, mutate order/exchange state, call
Coinbase, or authorize browser/BFF recovery.
Accepted checkpoint records also expose read-only reconciliation-plan link
evidence to `GET /api/v1/admin/reconciliation/plans` and
`GET /api/v1/admin/reconciliation/plans/{plan_id}`. That link is triage
evidence only; it must not be interpreted as reconciliation execution,
order/exchange-state mutation, recovery execution, repair apply, rollback,
Coinbase execution, browser reconciliation authority, or a separate
checkpoint writer.
The word "operator" in checkpoint text means the human reviewing the evidence;
the backend RBAC role named `operator` can read checkpoint evidence but cannot
record it. Recording requires `spot_pnl:record`, currently granted to `trader`
and `admin`.

Spot cancel identity is `client_order_id`. Coinbase cancellation is the
project-specific exception where the backend wrapper calls
`cancel_order(client_order_id)` because the exchange accepts the client id for
that operation. Do not replace this with an exchange-native `order_id` flow.

## Stealth Command Suite

`GET /api/v1/stealth/command-suite` is read-only M55 evidence. It reports
whether stealth create, cancel, reveal, move, reprice, recovery, and
reconciliation workflows have backend-owned contracts and gate evidence.

The response links live-disabled command rows for stealth create, reveal, move,
cancel, recovery, reconciliation, and movement/repricing reprice by
`stealth_order_id`. It also reports
`coverage_gaps` for create lifecycle-write, reveal trigger/exchange placement,
cancel exchange-handling, move revealed, reprice completion, recovery, and
reconciliation contracts. Gap rows identify current read evidence, missing
backend contracts, required gate chains, and browser/BFF boundaries.
The M55 concrete blocker-closure ledger may also report partial dry-run or
proof/readback evidence for all concrete blocker rows, including live-service,
live-adapter, active-placement cancel/replace, reveal exchange submission,
recovery repair/rollback, and post-write reconciliation execution. Those
fields separate existing non-executable readback evidence from still-missing
backend contracts; they do not close blockers, enable live execution, call
Coinbase, invoke managers, execute reveal, repair, rollback, reconciliation, or
mutate local/exchange state.

Stealth command rows require command-specific proof evidence in addition to
the normal approval, cap/guard, admission audit, reconciliation, idempotency,
payload-hash, and operator-intent chain. Move and reprice require
mutation-claim evidence; recovery requires recovery proof evidence; reveal
requires reveal-trigger proof evidence. Move, cancel, recovery,
reconciliation, and reprice also
require active-placement exchange truth before execution can be considered.
Create and reveal are command drafts that do not require active-placement
evidence before the draft response, but they still remain blocked until
lifecycle/trigger, live adapter, and reconciliation gates exist. The stealth
create lifecycle execution contract now reports the same disabled live
service, adapter, post-write reconciliation, canonical execution path, and
boundary-authority evidence used by non-create contracts; this is evidence
only and does not make create execution callable.
Both create and non-create execution contracts include a nested
`live_execution_service_contract`. It is a projection of
`DisabledAdminApiLiveExecutionService.admission_state()` for the route, not a
live service implementation. Workflows may display its disabled status,
service reference, forbidden methods, enabled false, executable false, and
browser/BFF authority only. It does not enable the service, construct
adapters, call Coinbase, invoke managers, execute reconciliation, mutate
state, or make the command executable. If it includes
`latest_service_decision_id`, that is local disabled-decision readback only;
`latest_service_decision_resolves_enablement` remains false and missing
enablement artifacts remain blockers. The contract also exposes
`latest_service_decision_recorded_artifacts_satisfy_enablement=false`,
empty `latest_service_decision_satisfied_enablement_artifacts`, and
unsatisfied enablement artifact names so recorded readback cannot be confused
with satisfied live-service enablement.
Exact create and non-create command responses may include
`live_execution_intent_contract`. It is the existing backend admission
decision's disabled intent envelope and is bound to route, identity, actor,
idempotency key, operator intent, and payload hash. Command-suite reads that do
not have those exact command fields must leave the intent absent. Workflows may
display the intent only; it is not live approval, service enablement, adapter
execution, Coinbase submission, reconciliation execution, or browser/BFF
authority.
Both create and non-create execution contracts include a nested
`post_write_reconciliation_boundary`. It is a route-bound plan/completion
handoff contract for `POST /api/v1/admin/reconciliation/plans`, not a plan
writer or reconciliation executor. Workflows must treat its missing evidence,
no-plan-write, no-reconciliation, no-Coinbase, and no-state-mutation flags as
blocking evidence until a future backend-owned executor is explicitly wired.
The backend can now persist post-write reconciliation proof evidence through
`POST /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-proofs`
and read it through
`GET /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-proof`.
Workflows may display those reviewed plan, execution-journal, and completion
references only. The records do not execute reconciliation, do not call
Coinbase, do not invoke managers, do not mutate lifecycle/order/exchange
state, and do not grant browser/BFF authority.
The backend can now persist post-write reconciliation execution-policy
evidence through
`POST /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-execution-policy-proofs`
and read it through
`GET /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-execution-policy`.
Workflows may display route-bound execution-policy, plan, journal,
verification, and safe-chain references only. The records do not execute
reconciliation, call Coinbase, invoke managers, submit/cancel/read orders,
cancel/replace active placements, mutate lifecycle/order/exchange state, or
grant browser/BFF authority.
The backend can now persist state-mutation policy evidence through
`POST /api/v1/stealth/orders/{stealth_order_id}/state-mutation-policy-proofs`
and read it through
`GET /api/v1/stealth/orders/{stealth_order_id}/state-mutation-policy`.
Workflows may display route-bound state, lifecycle, order, exchange, and
post-write policy references only. The records do not authorize or perform
lifecycle/order/exchange-state mutation, call Coinbase, invoke managers,
submit/cancel/read orders, cancel/replace active placements, execute
reconciliation, or grant browser/BFF authority. Create and non-create
execution prerequisite resolvers may now consume the newest exact safe proof
row as `state_mutation_policy` prerequisite evidence. The corresponding
live-readiness backend decision remains unresolved and fail-closed; the proof
does not grant mutation or execution authority.
Create and non-create execution prerequisite resolvers may now read the
post-write proof, execution-journal, and verification stores for exact
command-context records. A safe proof without a matching accepted journal is
reported with `missing_reason=no_matching_post_write_execution_journal`. A
safe proof and accepted journal without a matching verification is reported
with `missing_reason=no_matching_post_write_reconciliation_verification`. Only
the exact safe proof, accepted journal, and verification chain may resolve the
`post_write_reconciliation` prerequisite evidence, while live execution,
manager invocation, Coinbase calls, reconciliation execution, and state
mutation remain disabled.
Create and non-create execution contracts also expose
`remaining_execution_blocker_count` and `remaining_execution_blockers`. These
rows are typed backend evidence for the blockers that still prevent execution
after prerequisite lookup. A resolved post-write chain removes only the
`post_write_reconciliation_missing` blocker from that list. It does not remove
live service, live adapter, manager invocation, Coinbase submit/cancel/read,
active-placement cancel/replace, reconciliation execution, or state-mutation
blockers, and it does not grant browser/BFF authority.
The backend can now persist post-write execution-journal acceptance evidence
through
`POST /api/v1/stealth/orders/{stealth_order_id}/post-write-execution-journals`
and read it through the same path with `GET`. The writer is path-keyed by
`stealth_order_id`, requires `reconciliation:record`, idempotency, operator
intent, admission/audit/cap prerequisites, exact guarded command context, and
no-live posture. It does not execute reconciliation, verify reconciliation,
invoke managers, call Coinbase, cancel/replace placements, mutate
lifecycle/order/exchange state, or authorize browser/BFF execution.
The backend can now persist post-write reconciliation verification evidence
through
`POST /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-verifications`
and read it through the same path with `GET`. The writer is path-keyed by
`stealth_order_id`, requires the same guarded admission chain, and accepts a
verification record only when it exactly matches a safe proof plus accepted
journal. It can participate in resolving the
`post_write_reconciliation` prerequisite evidence only as part of that exact
safe chain. It does not execute reconciliation, invoke managers, call
Coinbase, cancel/replace placements, mutate lifecycle/order/exchange state, or
authorize browser/BFF execution.
Both exact create and non-create contracts may also include
`post_write_completion_verifier_contract`. Workflows may display proof id,
proof safety, matching journal acceptance id when present, matching
verification id when present, no-run flags, state-mutation flags, and
display/forward-only authority. The verifier is not command enablement,
Coinbase authority, manager authority, state-mutation authority, or BFF
execution authority.
Both contracts also include a nested `live_execution_adapter_contract` from
the shared live-execution adapter evidence builder. Workflows may display its
route, `AdminApiCommandService.*` reference, forbidden methods, disabled
status, and browser/BFF authority only. It does not construct an adapter,
invoke managers, call Coinbase, cancel/replace active placements, execute
reconciliation, mutate state, or make the command executable. Route mapping
and M53 pilot configuration remain separate from construction satisfaction:
`route_mapping_satisfies_construction=false`,
`adapter_configuration_satisfies_construction=false`, and satisfied
construction artifacts stay empty while required construction artifacts remain
unsatisfied.
The nested construction contract may also expose
`acceptance_evidence_producer_clearance_dependency_summary`, a blocked
backend-derived aggregate over producer-readiness clearance action rows.
Workflows may display counts, dependency-blocked refs, clearable refs,
terminal refs, first blocker, graph readiness, clearance allowance, and
disabled route/store/validation/replay/writer/acceptance/construction flags
only, plus `execution_allowed=false` and `executed=false`. The summary does
not clear readiness, write or accept evidence, satisfy
producer contracts, construct adapters, invoke managers, call Coinbase, mutate
state, or grant browser/BFF execution authority.
The nested construction contract may also expose
`acceptance_evidence_producer_clearance_work_items` and
`acceptance_evidence_producer_clearance_work_queue_summary`, backend-derived
queue evidence over each producer contract's first blocked clearance action.
It may also expose `acceptance_evidence_producer_clearance_claim_traces` and
`acceptance_evidence_producer_clearance_claim_trace_summary`, backend-derived
traceability evidence mapping the forbidden
`producer_route_contract_available` claim to each blocked work item. Workflows
may display the claim ids, work item refs, producer contract ids, evidence
ids, required refs/routes/methods, blockers, false claim resolution, false
work-item clearance, false producer satisfaction, disabled route/store/
validation/replay/writer/acceptance/construction/clearance/execution flags,
and display/forward-only authority only. These rows do not resolve claims,
clear work items, write or accept evidence, satisfy producer contracts,
construct adapters, invoke managers, call Coinbase, mutate state, or grant
browser/BFF execution authority.
The nested construction contract may also expose
`acceptance_evidence_producer_route_requirements` and
`acceptance_evidence_producer_route_requirement_summary`, backend-derived
route requirement evidence over those unresolved claim traces. Workflows may
display route requirement ids, route contract refs, claim ids, work item refs,
producer contract ids, evidence ids, required refs/routes/methods, blockers,
false route-contract availability, false route registration, false route
inventory binding, false shared service binding, false claim resolution, false
work-item clearance, false producer satisfaction, disabled store/validation/
replay/writer/acceptance/construction/clearance/execution flags, and
display/forward-only authority only. These rows do not register routes, bind
route inventory, bind shared command services, resolve claims, clear work
items, write or accept evidence, satisfy producer contracts, construct
adapters, invoke managers, call Coinbase, mutate state, or grant browser/BFF
execution authority.
The nested construction contract may also expose
`acceptance_evidence_producer_route_contract_proposals` and
`acceptance_evidence_producer_route_contract_proposal_summary`, backend-
derived proposal evidence over those unresolved route requirements. Workflows
may display route contract ids, route requirement ids, route contract refs,
route inventory refs, shared command-service refs, claim ids, work item refs,
producer contract ids, evidence ids, required refs/routes/methods, blockers,
false route-contract availability, false route registration, false route
inventory binding, false shared service binding, false route-handler
presence, false requirement resolution, false claim resolution, false
work-item clearance, false producer satisfaction, disabled store/validation/
replay/writer/acceptance/construction/clearance/execution flags, and
display/forward-only authority only. These rows do not register routes, bind
route inventory, bind shared command services, resolve requirements or
claims, clear work items, write or accept evidence, satisfy producer
contracts, construct adapters, invoke managers, call Coinbase, mutate state,
or grant browser/BFF execution authority.
The same nested construction contract may also expose
`acceptance_evidence_producer_route_contract_validation_items` and
`acceptance_evidence_producer_route_contract_validation_summary`, backend-
derived validation evidence over those unresolved route-contract proposals.
Workflows may display validation ids, route contract ids, route requirement
ids, check keys, blockers, route inventory refs, shared command-service refs,
handler/store/validation/replay/writer/acceptance readiness flags, false
observed state, false pass state, false requirement and claim resolution, and
display/forward-only authority only. These rows do not register routes, bind
route inventory, bind shared command services, register handlers, resolve
requirements or claims, clear work items, write or accept evidence, satisfy
producer contracts, construct adapters, invoke managers, call Coinbase, mutate
state, or grant browser/BFF execution authority.
The same nested construction contract may also expose
`acceptance_evidence_producer_route_contract_remediation_items` and
`acceptance_evidence_producer_route_contract_remediation_summary`, backend-
derived remediation evidence over failed route-contract validation rows.
Workflows may display remediation ids, validation ids, route contract ids,
route requirement ids, check keys, required/observed state, remediation
actions, validation blockers, false readiness, false route registration,
false route-inventory binding, false shared-service binding, false handler/
store/validation/replay/writer/evidence-acceptance state, false requirement
and claim resolution, and display/forward-only authority only. These rows do
not perform remediation, register routes, bind route inventory, bind shared
command services, register handlers, resolve requirements or claims, clear
work items, write or accept evidence, satisfy producer contracts, construct
adapters, invoke managers, call Coinbase, execute reconciliation, mutate state,
or grant browser/BFF execution authority.
Exact command responses that require active-placement exchange truth also
include a nested `active_placement_exchange_truth_contract`. It is the same
backend-owned evidence shape used by command-suite `exchange_truth_checks`.
Workflows may display its route, resolved local proof id, evidence routes,
missing contracts, rejected identities, no-live flags, and browser/BFF
authority only. It does not read Coinbase, prove live exchange truth, invoke
managers, execute recovery or reconciliation, mutate state, or make the
command executable. Create and reveal responses must leave this nested
active-placement prerequisite absent.
Exact non-create stealth command responses also include
`command_specific_proof_contracts`. Workflows may display the blocked
reveal-trigger, mutation-claim, recovery-proof, or reconciliation-proof route
that applies to the exact command family, along with method, permission,
shared backend method, identity key, and display/forward-only authority.
Workflows must not treat these rows as proof-writing authority, proof
resolution authority, Coinbase read authority, manager authority,
reconciliation execution, state mutation, or command execution. Stealth cancel
has an empty list because its additional proof boundaries are exchange truth
and cancel/replace.
Exact non-create stealth command responses also include
`execution_readiness_stages`. Workflows may display stage order,
prerequisite, lookup status, workflow family, next required backend contract,
and display/forward-only authority only. The rows are derived from the
backend prerequisite resolver and must not become proof lookup, Coinbase
read/write, manager invocation, recovery/reconciliation execution, state
mutation, or browser/BFF command authority.
Stealth create uses
`stealth_lifecycle_execution_contract.execution_readiness_stages` from the
separate create lifecycle resolver. Workflows may display those create stage
rows and no-write flags only; they must not become lifecycle-write authority,
Coinbase submit/read authority, manager authority, reconciliation authority,
or browser/BFF execution authority.
detail route may expose `reveal_trigger_audit` for local reveal-condition
evidence, but command workflows must not treat that panel as trigger
evaluation, `should_trigger_reveal`, `reveal_order_slice`, Coinbase
submission, lifecycle mutation, or browser/BFF reveal authority. The same
detail route may expose `reveal_submission_audit` for the future backend
reveal route, shared service method, manager method, local active-placement
evidence, and missing submission/reconciliation contracts, but command
workflows must not treat that panel as `reveal_order_slice` execution,
Coinbase submission/cancellation, active-placement creation, reconciliation
execution, lifecycle mutation, or browser/BFF reveal authority. The same
detail route may expose `reveal_reconciliation_audit` for required
reconciliation plan/proof posture, local active-placement evidence,
read-evidence routes, and missing proof contracts, but command workflows must
not treat that panel as Coinbase read authority, proof-writing authority,
reconciliation execution, order/lifecycle mutation, or browser/BFF reveal
authority. Move is a
cancel/replace-shaped draft that returns no-live evidence only; it must not
call `build_stealth_move_plan`, `execute_stealth_move`, or
`StealthOrderManager`, submit/cancel Coinbase orders, perform cancel/replace,
or mutate local lifecycle state. A revealed stealth order cannot be marked
hidden, cancelled, moved, or repriced by local mutation unless the live
placement is cancelled, replaced, filled, moved, or reconciled first.
Stealth recovery and reconciliation are local-state-mutation-shaped command
contracts that return fail-closed no-live evidence only; they must not execute
recovery repair, rollback, reconciliation, proof writers, Coinbase reads,
Coinbase orders, `StealthOrderManager` mutations, local lifecycle mutations,
exchange-state mutations, or browser/BFF command authority.
The response also exposes `admission_readiness` rows for the same seven
routes. Those rows aggregate proof-route requirements, active-placement or
lifecycle-write requirements, disabled live-adapter evidence, and post-live
reconciliation requirements so operators can see why a command remains
blocked. They are not a preflight endpoint, gate evaluator, proof writer,
Coinbase reader, executor, reconciler, or browser/BFF authority source.
They also expose `context_requirements` to separate static route metadata from
the exact command envelope needed for future proof lookup. Missing
`stealth_order_id`, actor, idempotency, operator-intent, and payload-hash
context keeps resolver lookup blocked.
The create lifecycle-write audit also exposes a nested `execution_contract`.
In command-suite readback, that contract has no exact command context and
stays blocked. In the live-disabled create draft response, the same evidence
appears as `stealth_lifecycle_execution_contract` with exact command context
present. Neither form is executable: both are no-live/no-write evidence that
the manager was not invoked, stealth and `order_parent` rows were not written,
lifecycle events were not dispatched, Coinbase was not read or submitted to,
and reconciliation did not run.
The same exact stealth command contracts may expose `execution_candidate`,
`execution_preflight`, `execution_transition_barrier`, and
`execution_live_readiness`. These fields show the future backend path, blocked
preflight checks, first blocking check, clearance order, blocked M55
completion claim, required backend decisions, backend decision-ledger rows,
handoff blockers, and forbidden execution claims as read-only evidence. Each
decision-ledger row names the backend decision, owner, required artifact,
missing reason, resolution artifacts, missing resolution artifacts, backend
contract refs, evidence refs, disabled resolver flags, disabled writer flags,
ordered resolution plan steps, missing plan steps, dependency refs,
verification gates, disabled plan-execution flags, and no-live/no-write proof.
The same decision rows also expose `resolution_readiness_items`, a structured
blocked matrix over the plan steps, dependencies, and verification gates. The
plan and readiness fields are sequencing evidence for future backend-owned
resolver work; they are not an executable plan. They must not become a browser
gate evaluator, decision resolver, decision writer, manager invocation path,
Coinbase call, cancel/replace path, reconciliation executor, local state
mutation, M55 completion authority, or BFF execution authority.
The decision rows also expose `resolution_readiness_summary`, which aggregates
the matrix into backend-owned total, blocked, resolved, type-count,
first-blocker, missing-reason, and no-execution evidence. The summary is for
operator orientation only and must not become a browser-computed readiness
gate or BFF execution path.
The decision rows also expose `resolution_handoff`, which classifies the
blocked backend decision into clearance categories and blocked clearance refs
derived from the readiness summary. The handoff is operator/contextless-agent
orientation only. Its `clearance_actions` rows name the source readiness item
type/order, clearance sequence, predecessor refs, successor refs, backend
contract, route, method, service, artifact, evidence ref, dependency
authority, dependency readiness, action authority, and disabled
execution/resolver/writer flags needed to clear each blocked ref. The handoff
also includes `clearance_dependency_summary`, which aggregates those action
rows into blocked/ready counts, edge counts, dependency-blocked refs,
clearable refs, terminal refs, and disabled graph readiness, clearance,
resolver, writer, and execution flags. The handoff, action rows, and summary
must not become a decision resolver, decision writer, live service switch,
live adapter, manager invocation, Coinbase path, reconciliation executor,
local state mutation, browser authority, or BFF execution path.
`backend_decision_resolution_summary` then aggregates the full backend
decision ledger with blocked decision counts, blocking owners, required
artifacts, missing reasons, first blocker, and clearance action totals. That
aggregate is still backend-owned display evidence only and must not become a
resolver, writer, completion claim, execution switch, browser authority, or
BFF execution path.
`backend_decision_resolution_work_items` and
`backend_decision_resolution_work_queue_summary` expose the first blocked
clearance action for each unresolved backend decision as a cross-decision work
queue. The queue names the owner, required artifact, backend contract, route,
method, service, evidence ref, dependency state, and disabled execution locks,
but it is still backend-owned display evidence only and must not become a
resolver, writer, completion claim, execution switch, browser authority, or
BFF execution path.
`forbidden_execution_claim_evidence` and
`forbidden_execution_claim_summary` map the raw forbidden execution claims to
the backend decision, required clearance category/ref, work queue ref, backend
contract/route/method/service, evidence ref, and disabled
claim-cleared/resolver/writer/execution flags that keep each claim blocked.
The summary aggregates blocked/cleared counts, blocking decisions, owners,
clearance refs, work queue refs, first claim evidence, and false
all-cleared/M55/live/executable flags. These rows are backend-owned
traceability only and must not clear claims, resolve or write decisions,
execute resolvers, invoke managers, call Coinbase, cancel/replace placements,
reconcile, mutate state, or grant browser/BFF execution authority.
The contract also exposes `resolved_prerequisites`,
`prerequisite_resolver_lookup_ran`, `prerequisite_resolver_authority`, and
`prerequisite_resolution` rows. Those rows are backend-owned read evidence
only. They may show exact-context-bound local lookup results and missing
reasons, but they do not create approvals, write proof records, invoke live
execution services, call adapters, read Coinbase, execute reconciliation, or
grant frontend/BFF execution authority.
Non-create live-disabled stealth command responses may include
`stealth_command_execution_contract`. That response evidence covers reveal,
cancel, move, recovery, reconciliation, and movement/reprice. It lists common
admission prerequisites, command-specific prerequisites, disabled live
service/adapter posture, blockers, and no-live/no-write flags. It must remain
separate from the create lifecycle-write contract and must not invoke manager
methods, cancel/replace active placements, call Coinbase, execute
reconciliation, mutate lifecycle/order/exchange state, or grant browser/BFF
execution authority.
The disabled live prerequisites also expose route-specific evidence fields for
the live service source, disabled live adapter source/status, post-write
reconciliation route/source, canonical backend execution path, and boundary
authority. Those fields explain the backend-owned future handoff only; they do
not resolve disabled prerequisites, build adapters, call managers or Coinbase,
execute reconciliation, or enable browser/BFF commands.
For active-placement-sensitive commands, the contract may resolve only
`active_placement_exchange_truth` from the existing backend append-only proof
store when a safe same-`stealth_order_id` record exists. The resolver is local
proof readback only; it is not Coinbase verification, manager invocation,
cancel/replace execution, or reconciliation authority.
Stealth cancel/replace proof evidence is exposed through
`GET /api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proof` and
persisted through
`POST /api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proofs`.
The writer supports guarded contexts for stealth cancel, stealth move, and
movement reprice and requires `stealth_cancel_replace:record`. It is
append-only local evidence only; it does not invoke `StealthOrderManager`,
build cancel/replace plans, call Coinbase, cancel or replace active
placements, execute reconciliation, mutate lifecycle/order/exchange state, or
grant browser/BFF authority.
Its `active_placement_evidence_ref`, `mutation_claim_evidence_ref`, and
`cancel_replace_evidence_ref` values are opaque operator/backend references:
the writer validates required presence and guarded-context matching, but does
not dereference them, verify another proof-store row, or treat them as
execution authority.
For stealth cancel, stealth move, and movement reprice command responses, the
same command execution contract may resolve only the `cancel_replace_proof`
prerequisite from the backend append-only cancel/replace proof store. The
latest same-`stealth_order_id` proof record must exactly match route, method,
service method, actor, operator intent, idempotency key, payload hash, and
mutation family, and it must be safe no-live/no-manager/no-state-mutation
evidence. This resolver does not build cancel/replace plans, invoke managers,
call Coinbase, cancel/replace active placements, execute reconciliation, or
grant browser/BFF authority. Unsafe latest records stay missing/stale instead
of falling back to older proof evidence.
Those same exact command responses may expose a nested
`active_placement_cancel_replace_contract`. It is built from the same
backend-owned helper as command-suite `cancel_replace_boundaries`, so the
command-suite read model and exact command response share one boundary
contract. Workflows may display its proof-resolution state, rejected
identities, missing contracts, and no-run flags only. It is not a manager path,
Coinbase caller, cancel/replace executor, reconciliation executor, state
mutation path, or browser/BFF authority source.
For recovery commands, the same contract may resolve only `recovery_proof`
from the backend append-only recovery proof store when the latest safe
same-`stealth_order_id` record exactly matches route, method, service method,
actor, operator intent, idempotency key, and payload hash. The resolver is
local proof readback only; it is not recovery repair, rollback, manager
invocation, Coinbase verification, cancel/replace execution, state mutation,
or reconciliation authority.
For reveal commands, the same contract may resolve only
`reveal_trigger_evidence` from the backend append-only reveal-trigger proof
store when the latest safe same-`stealth_order_id` record exactly matches
route, method, service method, actor, operator intent, idempotency key, and
payload hash. The resolver is local proof readback only; it is not trigger
evaluation, `should_trigger_reveal`, `reveal_order_slice`, Coinbase
verification, exchange submission, state mutation, or reconciliation
authority.
For reconciliation commands, the same contract may resolve only
`reconciliation_proof` from the backend append-only reconciliation proof store
when the latest safe same-`stealth_order_id` record exactly matches route,
method, service method, actor, operator intent, idempotency key, and payload
hash. The resolver is local proof readback only; it is not reconciliation
execution, reconciliation-plan building, Coinbase verification, manager
invocation, cancel/replace execution, state mutation, or browser/BFF
authority.

The stealth command-suite route does not create stealth orders, reveal orders,
cancel active placements, move/reprice revealed orders, execute
reconciliation, mutate local state, read Coinbase, call Coinbase, or authorize
browser/BFF command execution.

## Boundaries

- Spot-only wallet, USDC, no-shorting, cost-basis, and average-cost rules must
  not become futures/perpetual, stealth, movement/repricing, or generic admin
  defaults.
- Frontend and BFF code remain display/forwarding surfaces. Button visibility
  is not authorization.
- Legacy dashboard WebSocket command surfaces are compatibility evidence only
  for enterprise admin planning and must not become the new frontend command
  path.

## Related References

- [Admin API](../README.admin-api.md)
- [Admin API Examples](examples/admin-api.md)
- [Stealth Reconciliation Proof Examples](examples/stealth-reconciliation-proofs.md)
- [Admin API Route Inventory](plans/ADMIN_API_ROUTE_INVENTORY.md)
- [Admin Platform Durable Milestones](plans/ADMIN_PLATFORM_DURABLE_MILESTONES.md)
- [Agent Invariants](agents/INVARIANTS.md)
