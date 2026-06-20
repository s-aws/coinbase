# Stealth Order Reads And Command-Suite Evidence

Stealth Admin API reads expose backend lifecycle evidence without mutating
stealth orders or exchange state. They are part of the enterprise admin
platform, not the legacy dashboard command plane.

## Read Routes

- `GET /api/v1/stealth/orders`
- `GET /api/v1/stealth/orders/{stealth_order_id}`
- `GET /api/v1/stealth/orders/{stealth_order_id}/reveal-trigger-proof`
- `GET /api/v1/stealth/orders/{stealth_order_id}/recovery-proof`
- `GET /api/v1/stealth/orders/{stealth_order_id}/mutation-claim-proof`
- `GET /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-execution-policy`
- `GET /api/v1/stealth/orders/{stealth_order_id}/reconciliation-proof`
- `GET /api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proof`
- `GET /api/v1/stealth/command-suite`

The list/detail routes read local stealth lifecycle rows and report active
placement evidence, mutation-claim evidence, and reveal-trigger evidence when
present. The command-suite route reports M55 readiness for stealth create,
cancel, reveal, move, reprice, recovery, and reconciliation workflows.
For phases 4581-4600, the M55 blocker-closure ledger also reports partial
proof/readback evidence for all concrete blocker rows. Partial evidence is
readback only: it does not change blocker status, missing backend contracts,
live-service or live-adapter flags, Coinbase/manager authority,
repair/rollback authority, reconciliation execution, or state-mutation
authority.

## Identity Rules

Use `stealth_order_id` as the command identity for stealth Admin API evidence.
Active placement client ids and exchange order ids may be displayed as
evidence, but they are not internal tracking keys and are not cancellation
authority for the enterprise Admin API.

## Command-Suite Semantics

`GET /api/v1/stealth/command-suite` is read-only evidence. It derives existing
command rows and gap rows from backend route inventory and live-enablement
evidence:

- `POST /api/v1/stealth/orders` is linked as a live-disabled create command
  draft and does not invoke `StealthOrderManager` or create local lifecycle
  state.
- `POST /api/v1/stealth/orders/{stealth_order_id}/reveal` is linked as a
  live-disabled reveal command draft and does not invoke `reveal_order_slice`,
  submit Coinbase orders, or mutate lifecycle state.
- `POST /api/v1/stealth/orders/{stealth_order_id}/move` is linked as a
  live-disabled cancel/replace-shaped move command draft and does not invoke
  `build_stealth_move_plan`, call `execute_stealth_move`, submit/cancel
  Coinbase orders, perform cancel/replace, or mutate lifecycle state.
- `POST /api/v1/stealth/orders/{stealth_order_id}/cancel` is linked as a
  live-disabled command row.
- `POST /api/v1/stealth/orders/{stealth_order_id}/recovery` is linked as a
  live-disabled recovery command contract and does not execute recovery
  repair, rollback, proof writing, Coinbase reads, Coinbase orders,
  `StealthOrderManager` mutations, local lifecycle mutations, or exchange
  mutation.
- `POST /api/v1/stealth/orders/{stealth_order_id}/reconciliation` is linked
  as a live-disabled reconciliation command contract and does not execute
  reconciliation, resolve or write proof records, read Coinbase, submit
  Coinbase orders, mutate order/lifecycle/exchange state, or grant browser/BFF
  reconciliation authority.
- `POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice` is
  linked as a live-disabled movement/repricing command row.
- Workflow gaps remain blocked until backend-owned contracts exist for create
  lifecycle writes, reveal trigger/exchange placement, cancel exchange
  handling, move revealed, reprice completion, recovery, and reconciliation.

Every command row remains `live_enabled=false` and `executable=false`. Required
gates include idempotency, operator intent, payload hash, approval snapshot,
approval-store contract, admission audit, cap/guard decision, reconciliation
plan, mutation claim, live execution adapter, live execution service, and
post-live reconciliation. Move, cancel, recovery, reconciliation, and reprice
additionally require active-placement exchange truth; create and reveal drafts
remain blocked on lifecycle/trigger evidence before execution can be
considered.
Exchange-truth rows also expose typed `current_read_evidence` metadata for
the existing read routes behind each blocked prerequisite. Those rows name the
read route, method, permission, shared read-service method, documentation
refs, and display/read-only authority. They do not run Coinbase reads, prove
active-placement exchange truth, cancel/replace placements, reveal orders,
execute reconciliation, mutate stealth/order/exchange state, create proof
records, or authorize browser/BFF execution.
Exact stealth command responses that require an existing active placement now
reuse that exchange-truth row shape as
`active_placement_exchange_truth_contract`. The nested object is still
blocked evidence: it may report a resolved local proof id and evidence routes,
but it does not read Coinbase, prove live exchange truth, execute
cancel/replace, invoke managers, execute recovery or reconciliation, mutate
state, or authorize browser/BFF execution. Create and reveal responses do not
fabricate this active-placement prerequisite object.
Exact non-create stealth command responses now also expose
`command_specific_proof_contracts`. The rows reuse the command-suite
proof-route shape for reveal-trigger, mutation-claim, recovery-proof, or
reconciliation-proof route evidence. They are blocked, backend-owned,
display-only rows and do not record proofs, resolve proof authority through
the frontend, read Coinbase, invoke managers, execute recovery or
reconciliation, mutate state, or authorize browser/BFF execution. Stealth
cancel returns an empty command-specific proof list.
Exact non-create command responses now also expose
`execution_readiness_stages`. The ordered rows reuse backend prerequisite
resolver evidence to show each required stage, workflow family, lookup status,
next required backend contract, and no-live authority boundary. They are
display-only evidence and do not record proofs, query Coinbase, execute
cancel/replace, invoke managers, execute recovery/reconciliation, mutate
state, or authorize browser/BFF execution.
Stealth create exposes the same ordered stage shape on
`stealth_lifecycle_execution_contract.execution_readiness_stages`, derived
from the create lifecycle prerequisite resolver. It is display-only
create-lifecycle evidence and does not authorize stealth row writes,
`order_parent` writes, lifecycle event dispatch, Coinbase submit/read,
reconciliation execution, or browser/BFF execution.

The command-suite response also reports `admission_readiness` rows. This
ledger binds each stealth command route to the backend evidence that must
exist before execution can ever be considered: approval request, approval
decision, admission audit, cap/guard decision, reconciliation plan,
active-placement exchange-truth or lifecycle-write guard, disabled live
adapter, and post-live reconciliation. These rows are read evidence only. They
do not approve admission, execute commands, read Coinbase, invoke
`StealthOrderManager`, cancel/replace active placements, execute
reconciliation, mutate lifecycle/order/exchange state, or grant browser/BFF
authority.
The same rows expose `context_requirements`. Route-derived fields are present
for traceability, while exact command-envelope fields remain missing:
`stealth_order_id`, `actor_id`, `idempotency_key`, `operator_intent`, and
`payload_hash`. Resolver lookup and proof resolution must stay false until a
backend command path provides that exact context.
Live-disabled stealth command responses can provide that concrete command
context as `stealth_admission_context`. The read model should still show the
missing-envelope state; only the command response can echo exact context from
the request. The echo is display-only evidence and does not read Coinbase,
submit/cancel orders, cancel/replace active placements, reconcile, mutate
stealth/order/exchange state, or grant browser/BFF command authority.
Those same non-create command responses may include
`stealth_command_execution_contract` for reveal, cancel, move, recovery,
reconciliation, and movement/reprice. It is command-response evidence, not a
read-model prerequisite evaluator. It may display missing prerequisites,
disabled live service/adapter posture, no-manager/no-Coinbase/no-reconciliation
flags, and browser/BFF authority strings. It may resolve the
`active_placement_exchange_truth` prerequisite from the existing append-only
backend proof store when a safe same-`stealth_order_id` proof exists, but that
is local proof readback only. It may resolve `mutation_claim_snapshot` for
move/reprice and `recovery_proof` for recovery from their backend append-only
proof stores when the latest safe same-`stealth_order_id` proof exactly
matches route, method, service method, actor, operator intent, idempotency key,
and payload hash. It may also resolve `reveal_trigger_evidence` for reveal
from the backend reveal-trigger proof store under the same exact-context and
latest-safe rules. It does not verify Coinbase, evaluate triggers, call
`should_trigger_reveal`, call `reveal_order_slice`, run manager code, repair
state, roll back state, cancel/replace live
placements, execute reconciliation, mutate local or exchange state, or
authorize the frontend.
The same contract may report disabled live-service, live-adapter, post-write
reconciliation, canonical execution path, and boundary-authority fields. Those
fields are contextless evidence for the future backend handoff only; they do
not construct adapters, resolve disabled prerequisites, invoke managers, call
Coinbase, execute reconciliation, or mutate state.
The nested `post_write_reconciliation_boundary` object makes that handoff
explicit. It binds the stealth command route and exact command context, names
`POST /api/v1/admin/reconciliation/plans` as the backend-owned plan route,
lists missing post-write evidence, and reports no plan write, no reconciliation
execution, no Coinbase call, and no state mutation. It is not a reconciliation
executor and it is not browser/BFF authority.
Exact command execution contracts may also include
`post_write_completion_verifier_contract`. That object keeps the handoff
blocked after a proof id is found unless accepted execution-journal evidence
and verified post-write reconciliation are separately present. It is
display-only evidence and grants no command, Coinbase, reconciliation, state
mutation, browser, or BFF authority.
Post-write execution-journal acceptance evidence is exposed through
`GET /api/v1/stealth/orders/{stealth_order_id}/post-write-execution-journals`
and persisted through
`POST /api/v1/stealth/orders/{stealth_order_id}/post-write-execution-journals`.
The writer stores backend-owned append-only evidence only when it matches a
safe post-write reconciliation proof and exact guarded command context. It
does not execute or verify reconciliation, invoke managers, call Coinbase,
cancel/replace active placements, mutate lifecycle/order/exchange state, or
authorize browser/BFF execution.
Post-write reconciliation verification evidence is exposed through
`GET /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-verifications`
and persisted through
`POST /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-verifications`.
The readback lists persisted records but counts a verification as verified
only when it matches an exact safe post-write proof plus accepted execution
journal chain. The writer stores backend-owned append-only evidence only when
it matches that same exact guarded command context. It may participate in
resolving only the `post_write_reconciliation` prerequisite evidence as part
of the exact safe proof, accepted journal, and verification chain. It does not
execute reconciliation, invoke managers, call Coinbase, cancel/replace active
placements, mutate lifecycle/order/exchange state, or authorize browser/BFF
execution.
Post-write reconciliation proof records are exposed through
`GET /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-proof`
and persisted through
`POST /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-proofs`.
The writer route requires `reconciliation:record`, stores append-only backend
local evidence only after exact admission prerequisites match, and supports
guarded contexts for stealth create, reveal, cancel, move, reprice, recovery,
and reconciliation. A proof record alone does not satisfy the
`post_write_reconciliation` prerequisite evidence, call Coinbase, invoke
managers, execute reconciliation, cancel/replace active placements, mutate
lifecycle/order/exchange state, or authorize the frontend.
Post-write reconciliation execution-policy records are exposed through
`GET /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-execution-policy`
and persisted through
`POST /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-execution-policy-proofs`.
They are append-only local evidence for the future reconciliation execution
boundary. They do not execute reconciliation, call Coinbase, invoke managers,
cancel/replace active placements, mutate lifecycle/order/exchange state, or
authorize browser/BFF execution.
The nested `live_execution_adapter_contract` object makes the disabled adapter
construction boundary explicit. It binds the stealth command route to the
shared `AdminApiCommandService.*` reference and lists forbidden execution
methods while reporting `executable=false`, `browser_authority=display_only`,
and `bff_authority=forward_only_no_execution`. It is not an adapter
implementation, manager invocation path, Coinbase caller, or command-enablement
signal.
It may also resolve `reconciliation_proof` for reconciliation from the
backend reconciliation proof store when the latest safe same-`stealth_order_id`
proof exactly matches route, method, service method, actor, operator intent,
idempotency key, and payload hash. That resolver is local proof readback only.
It does not execute reconciliation, build reconciliation plans, invoke
managers, read Coinbase, cancel/replace active placements, mutate local or
exchange state, or authorize the frontend.

Reveal-trigger proof evidence is exposed through
`GET /api/v1/stealth/orders/{stealth_order_id}/reveal-trigger-proof` and
persisted through
`POST /api/v1/stealth/orders/{stealth_order_id}/reveal-trigger-proofs`.
The writer route requires `stealth_reveal_trigger:record`, stores append-only
backend local evidence only after exact admission prerequisites match, and
does not evaluate triggers, invoke managers, call Coinbase, execute
reconciliation, or mutate lifecycle/order/exchange state.

Stealth reconciliation proof evidence is exposed through
`GET /api/v1/stealth/orders/{stealth_order_id}/reconciliation-proof` and
persisted through
`POST /api/v1/stealth/orders/{stealth_order_id}/reconciliation-proofs`.
The writer route requires `stealth_reconciliation:record`, stores append-only
backend local evidence only after exact admission prerequisites match, and
does not execute reconciliation, invoke managers, build plans, read Coinbase,
cancel/replace active placements, submit/cancel orders, or mutate lifecycle,
order, or exchange state.

Stealth cancel/replace proof evidence is exposed through
`GET /api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proof` and
persisted through
`POST /api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proofs`.
The writer route requires `stealth_cancel_replace:record`, stores append-only
backend local evidence only after exact admission prerequisites match, and
supports guarded contexts for stealth cancel, stealth move, and movement
reprice. It does not build cancel/replace plans, invoke managers, read
Coinbase, cancel or replace active placements, submit/cancel orders, execute
reconciliation, or mutate lifecycle, order, or exchange state.
Live-disabled stealth cancel, stealth move, and movement reprice command
responses may resolve only the `cancel_replace_proof` prerequisite when the
latest same-`stealth_order_id` proof record is safe and exactly matches route,
method, service method, actor, operator intent, idempotency key, payload hash,
and mutation family. If the latest same-order proof record is unsafe, stale, or
not an exact-context match, the resolver reports the prerequisite missing/stale
and does not fall back to an older safe record. That read-only resolver does not
resolve active-placement exchange truth or mutation claims, does not call
Coinbase, does not invoke managers, and does not make the command executable.

The command-suite `create_lifecycle_write_audit.execution_contract` block
reports the backend-owned stealth create execution-contract boundary without
executing it. It lists exact-context requirements, missing prerequisite
evidence, rejected `order_id` and `client_order_id` command identities,
blockers, and no-live/no-write proof flags. Live-disabled create command
responses may also return the same evidence as
`stealth_lifecycle_execution_contract` with exact request context present.
The same block exposes read-only prerequisite resolver evidence:
`resolved_prerequisites`, `prerequisite_resolver_lookup_ran`,
`prerequisite_resolver_authority`, and per-prerequisite lookup rows with
status, resolved evidence id or missing reason, no-write flags, and no-Coinbase
read flags. It also exposes the same disabled `live_execution_service`,
`live_execution_adapter`, `post_write_reconciliation`, canonical execution
path, and `execution_boundary_authority` fields used by non-create stealth
execution contracts.
They also expose the same nested `live_execution_service_contract` object,
which projects the disabled backend live execution service state for the
route and remains enabled false and non-executable.
Exact command responses may expose `live_execution_intent_contract`, which is
the disabled backend admission intent bound to actor, idempotency key, operator
intent, and payload hash. Command-suite reads without exact command context do
not fabricate it.
They also expose the same nested `post_write_reconciliation_boundary` object,
which names the reconciliation-plan route and remains blocked/no-run.
They also expose the same nested `live_execution_adapter_contract`, which names
the shared command-service reference and remains disabled/non-executable.
They also expose `remaining_execution_blocker_count` and
`remaining_execution_blockers`, a typed blocker-chain derived from backend
prerequisite resolver rows and disabled execution-boundary evidence. A
resolved exact post-write proof/journal/verification chain can remove only the
`post_write_reconciliation_missing` blocker. Live service, live adapter,
manager invocation, Coinbase submit/cancel/read, cancel/replace,
reconciliation execution, local write, and state-mutation blockers remain
visible and blocked.
Exact stealth cancel, stealth move, and movement/reprice command responses may
also expose `active_placement_cancel_replace_contract`. It is the same
backend-owned cancel/replace boundary contract used by command-suite
`cancel_replace_boundaries`, with exact-command proof-resolution fields when
local proof records match. It is read/display evidence only and does not call
Coinbase, invoke managers, execute cancel/replace, execute reconciliation,
mutate state, or grant browser/BFF authority.
Both surfaces remain evidence only: they do not resolve proof records as
authority, invoke `StealthOrderManager`, write `stealth_orders` or
`order_parent` rows, dispatch lifecycle events, read/submit/cancel Coinbase,
execute reconciliation, mutate exchange state, or grant browser/BFF execution
authority.

## Detail Audit Semantics

`GET /api/v1/stealth/orders/{stealth_order_id}` may include
`active_placement_audit`, `mutation_claim_audit`, and `reveal_trigger_audit`.
These panels are read evidence only:

- `active_placement_audit` reports local active-placement pointers and missing
  exchange-truth contracts; it is not Coinbase truth or cancel/replace
  authority.
- `mutation_claim_audit` reports safely observable runtime mutation-claim
  snapshots; it does not acquire, release, clear, or prove claims.
- `reveal_trigger_audit` reports local reveal-condition presence, type, and
  payload plus missing trigger-guard contracts; it does not evaluate triggers,
  call `should_trigger_reveal`, call `reveal_order_slice`, submit Coinbase
  orders, mutate lifecycle state, or authorize browser/BFF reveal execution.
- `reveal_submission_audit` reports the future backend reveal route, shared
  service method, manager method, local active-placement evidence, missing
  submission/reconciliation contracts, and no-live flags; it does not call
  `reveal_order_slice`, create active placements, submit or cancel Coinbase
  orders, read Coinbase, execute reconciliation, mutate lifecycle state, or
  authorize browser/BFF reveal execution.
- `reveal_reconciliation_audit` reports required reveal reconciliation
  plan/proof posture, local active-placement evidence, read-evidence routes,
  missing proof contracts, and no-live flags; it does not read Coinbase,
  resolve or write proof records, execute reconciliation, mutate order or
  lifecycle state, or authorize browser/BFF reveal execution.

## Exchange-Truth Boundary

`HIDDEN`, `PENDING`, and `TRIGGERED` stealth orders must not have a live
Coinbase placement. `REVEALED` means a placement was submitted and may still be
live. A revealed order cannot become hidden, cancelled, moved, or repriced by
local mutation alone; the active placement must be cancelled, replaced, filled,
moved, or reconciled first through the existing backend path.

The command-suite route does not read Coinbase, submit orders, cancel orders,
reveal orders, execute reconciliation, mutate local state, or grant browser/BFF
authority.

## Verification

Focused backend coverage:

```powershell
python -m pytest tests\regression\test_admin_api_contract.py -v --tb=short
```

Full backend regression is a durable milestone closeout gate, not an ordinary
phase gate. Run it before marking a milestone complete, before
public/release-candidate handoff, or when explicitly requested:

```powershell
python -m pytest tests\regression\ -v --tb=short
```
