# Stealth Command Suite Readiness

The stealth command-suite readiness contract exposes backend-owned evidence for
M55 stealth administration. It is a read-only Admin API surface for planning
create, cancel, reveal, move, reprice, recovery, and reconciliation work.

Use this feature when an operator or frontend needs to understand which stealth
command workflows are modeled, which are live-disabled, and which backend
contracts still block execution.

## Route

`GET /api/v1/stealth/command-suite`

The route requires Admin API authentication and `analytics:read`. It returns
`StealthCommandSuiteResponse` with:

- blocked command rows for live-disabled stealth create, reveal, move, cancel,
  recovery, reconciliation, and movement reprice
- exchange-truth prerequisite rows for those same seven command routes,
  including accepted `stealth_order_id` identity, rejected placement/exchange
  identities, and the active-placement-required commands
- typed `exchange_truth_checks.current_read_evidence` rows for existing
  read-only evidence behind blocked exchange-truth prerequisites
- per-order active-placement exchange-truth readback evidence from
  `GET /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proof`
  plus backend-owned snapshot/proof writer contracts for route-bound local
  evidence
- `cancel_replace_boundaries` rows for cancel, move, and reprice that name
  the canonical future backend behavior path, required proof contracts,
  accepted/rejected identities, and no-live/no-mutation flags without
  invoking managers or Coinbase
- per-order cancel/replace proof readback evidence from
  `GET /api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proof`
  plus the backend-owned proof writer contract
  `POST /api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proofs`
  for route-bound local evidence
- `admission_readiness` rows that bind each command route to required
  backend proof evidence: approval request, approval decision, admission
  audit, cap/guard decision, reconciliation plan, active-placement exchange
  truth or lifecycle-write guard, live adapter evidence, and post-live
  reconciliation. The stealth reveal route may show one configured dry-run
  adapter and one configured dry-run live-service contract as present
  evidence, but admission and execution remain blocked.
- admission context requirements showing which static route fields are present
  and which exact command-envelope fields are still missing before proof
  resolver lookup is allowed
- typed `execution_candidate` evidence on exact create and non-create command
  responses. This names the future backend manager path and unresolved blocker
  chain but remains `blocked`, non-executable, no-live, backend-owned,
  route-bound, command-context-bound, browser `display_only`, and BFF
  `forward_only_no_execution`
- typed `execution_preflight` evidence on exact create and non-create command
  responses. This is derived from the same `execution_candidate` and remaining
  blocker chain, reports blocked checks for candidate readiness, live service,
  live adapter, manager invocation, Coinbase exchange actions,
  post-write reconciliation, state mutation, and browser/BFF authority, and
  does not call managers, Coinbase, reconciliation, cancel/replace, or state
  mutation paths
- typed `execution_transition_barrier` evidence on exact create and
  non-create command responses. This is derived from `execution_preflight`,
  names the first blocking check and ordered clearance requirements, keeps
  `transition_allowed` and `transition_executable` false, and remains
  backend-owned, no-live, browser `display_only`, and BFF
  `forward_only_no_execution`. It does not call managers, Coinbase,
  cancel/replace, reconciliation, or state mutation paths
- typed `execution_live_readiness` evidence on exact create and non-create
  command responses. This is derived from `execution_transition_barrier`,
  keeps the M55 completion claim false, lists required backend decisions,
  handoff blockers, forbidden execution claims, and a typed
  `backend_decisions` ledger. Each ledger row names the backend decision,
  owner, required artifact, missing reason, and blocked no-live/no-write
  proof while remaining backend-owned, no-live, browser `display_only`, and
  BFF `forward_only_no_execution`
- `blocker_closures` and `blocker_closure_summary` on the read-only
  command-suite response. These M55 rows name the concrete backend blockers
  that still prevent live stealth execution: live service enablement, live
  adapter construction, active-placement cancel/replace execution, reveal
  exchange submission, recovery repair/rollback execution, and post-write
  reconciliation execution. Every row is backend-owned evidence only with
  `resolved=false`, `blocking=true`, browser `display_only`, BFF
  `forward_only_no_execution`, all manager/Coinbase/reconciliation/state
  execution flags false, and submitted/executed notional `0`. A configured
  reveal dry-run adapter does not clear full M55 adapter construction or make
  stealth live paths executable.
- `enablement_candidate_reviews` and
  `enablement_candidate_review_summary` on the read-only command-suite
  response. These rows rank the seven existing stealth command routes by
  exchange-facing blocker count, blocker-closure count, admission evidence,
  missing gates, and route. The first current review target is
  `stealth_create` at `POST /api/v1/stealth/orders` because it has no
  active-placement or Coinbase-facing blocker, but it remains blocked and
  non-executable. The review does not call managers, Coinbase,
  reconciliation, cancel/replace, proof resolvers, or state mutation paths.
- `selected_order_action_states` on the read-only command-suite response.
  These rows give the frontend one backend-derived command-family action-state
  template per stealth command family: create, reveal, cancel, move, movement
  reprice, recovery, and reconciliation. The command-suite route is not
  parameterized by one selected order, so each row sets
  `scope=command_family_template` and
  `order_specific_adjudication=false`. The frontend may bind the displayed
  identity to the selected `stealth_order_id`, but that is not backend
  acceptance or rejection of that exact order. Each row reports
  `action_state` using the enum vocabulary `usable`, `blocked`,
  `unsupported`, or `not_modeled`, plus the command route, `stealth_order_id`
  identity key, selected identity-value source, live execution status,
  required/missing gate chains, blockers, next required contract, and a
  no-browser/no-BFF boundary. Current Release 0.1 rows are blocked evidence
  only and do not grant execution authority.
- `action_state_handoff_audits` and
  `action_state_handoff_audit_summary` on the read-only command-suite
  response. These Phase 8106 rows prove that the seven expected stealth command
  families are represented across backend command-suite rows, selected
  action-state rows, and Command Workflows dry-submit tabs. Create is
  Command-Workflow-only and does not require a selected-order handoff; reveal,
  cancel, move, movement reprice, recovery, and reconciliation require
  selected-order prefill handoffs. All rows remain blocked, prefill-only,
  backend-owned, route-bound, not live-enabled, non-executable, and keyed by
  `stealth_order_id`. Reveal preserves the backend command row's
  `live_execution_status=approval_required` dry-run posture; the other six
  rows report `live_disabled`. These rows do not grant browser/BFF execution,
  manager invocation, Coinbase submit/cancel/read authority, reconciliation
  execution, local state mutation, exchange `order_id` command identity, or
  command enablement.
- coverage gaps for missing stealth create, reveal, cancel exchange handling,
  move, reprice, recovery, and reconciliation contracts
- typed `coverage_gaps.current_read_evidence` rows for existing read-only
  evidence behind blocked gaps, including recovery-gate, reconciliation-plan,
  stealth order detail, movement/repricing detail, and command-suite reads
- required gate chains for approval, cap/guard, admission audit,
  reconciliation, mutation claims, active-placement exchange truth, and live
  execution service evidence
- per-order reveal-trigger audit evidence on the stealth detail route so
  operators can inspect local reveal-condition evidence without triggering a
  reveal
- per-order reveal submission-adapter audit evidence on the stealth detail
  route so operators can inspect the future backend reveal path and local
  placement blockers without submitting orders
- no-live Coinbase posture with submitted/executed notional `0`

Per-order active-placement audit evidence is exposed by
`GET /api/v1/stealth/orders/{stealth_order_id}` as
`active_placement_audit`. The command-suite route points at that read evidence,
but it does not own per-order Coinbase truth and must not be treated as a
cancel/replace or reconciliation path.
The same detail route exposes `mutation_claim_audit` as display-only runtime
claim evidence for move and repricing families. It does not acquire, release,
clear, or prove mutation claims, and it must not become a command input source
or browser/BFF mutation authority.
The detail route also exposes `reveal_submission_audit` as display-only
evidence for the future backend reveal route, shared service method, manager
method, active-placement blockers, and missing submission/reconciliation
contracts. It does not call `reveal_order_slice`, create active placements,
submit or cancel Coinbase orders, read Coinbase, execute reconciliation, or
mutate lifecycle state.
The detail route also exposes `reveal_reconciliation_audit` as display-only
evidence for future reveal reconciliation proof. It reports required
plan/proof posture, local active-placement evidence, read-evidence routes, and
missing proof contracts. It does not read Coinbase, write proof records,
execute reconciliation, mutate order/lifecycle state, or grant browser/BFF
reveal authority.

Coverage-gap evidence routes are also display-only. Recovery gaps may point to
`GET /api/v1/admin/recovery-gate`,
`GET /api/v1/stealth/orders/{stealth_order_id}`, and
`GET /api/v1/stealth/command-suite`. Reconciliation gaps may point to
`GET /api/v1/admin/reconciliation/plans`,
`GET /api/v1/admin/reconciliation/plans/{plan_id}`,
`GET /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proof`,
`GET /api/v1/stealth/orders/{stealth_order_id}/reconciliation-proof`, and
`GET /api/v1/stealth/command-suite`. These rows name route, method, action
class, required permission, shared read-service method, documentation refs,
and browser/BFF authority so operators can trace what evidence already
exists. These evidence rows do not execute recovery or reconciliation, write
proofs, mutate exchange-state inputs, call Coinbase, or grant browser/BFF
command authority.
Stealth recovery and reconciliation also have live-disabled command contracts:
`POST /api/v1/stealth/orders/{stealth_order_id}/recovery` and
`POST /api/v1/stealth/orders/{stealth_order_id}/reconciliation`. These routes
pass through the Admin API RBAC, idempotency, audit, and shared command-service
path, but they return fail-closed `not_implemented` responses. They do not
execute recovery repair, rollback, reconciliation, proof writers, Coinbase
reads, Coinbase orders, `StealthOrderManager` mutations, local lifecycle
mutations, exchange-state mutations, or browser/BFF command authority.
Exchange-truth evidence routes use the same read-only shape for create,
reveal, cancel, move, and reprice prerequisites. They identify where current
local read evidence exists, but they do not run Coinbase reads, prove active
placement exchange truth, cancel/replace placements, reveal orders, execute
reconciliation, mutate state, or authorize browser/BFF command execution.
Active-placement exchange-truth snapshot/proof writer routes persist local
evidence only after backend admission prerequisites match. They do not verify
exchange truth, read Coinbase, cancel/replace active placements, execute
reconciliation, mutate lifecycle state, or grant browser/BFF proof authority.
Cancel/replace boundary rows are blocked read evidence for cancel, move, and
reprice. They name the single future backend path that must be used after
approval, admission-audit, cap/guard, reconciliation-plan, and active-placement
proofs exist. They do not call Coinbase, invoke `StealthOrderManager`, build
or execute move/reprice plans, cancel/replace placements, mutate lifecycle,
order, or exchange state, or grant browser/BFF authority.
Cancel/replace proof records are append-only local evidence for the guarded
cancel, move, or reprice command context. The writer requires
`stealth_cancel_replace:record`, remains path-keyed by `stealth_order_id`, and
keeps `cancel_replace_plan_built=false` and
`active_placement_cancel_replace_ran=false`. It does not call Coinbase,
invoke managers, build plans, cancel or replace placements, execute
reconciliation, mutate lifecycle/order/exchange state, or grant browser/BFF
authority.
Admission-readiness rows are blocked read evidence over the same backend proof
chain. They do not approve admission, execute commands, read Coinbase, invoke
`StealthOrderManager`, cancel/replace active placements, execute
reconciliation, mutate lifecycle/order/exchange state, or grant browser/BFF
authority.
Each admission-readiness row also reports command-envelope context
requirements. Static route context (`route`, `method`, `module_id`,
`mutation_family`, `action_class`, and `required_permission`) is present from
backend inventory, but exact command context (`stealth_order_id`, `actor_id`,
`idempotency_key`, `operator_intent`, and `payload_hash`) remains missing in
this read model. Therefore `exact_context_present=false`,
`resolver_lookup_allowed=false`, `resolver_lookup_ran=false`, and
`proof_resolution_attempted=false`.
Concrete live-disabled command responses may separately return
`stealth_admission_context` after a backend command envelope exists. That
echo can show all eleven context fields present, resolver lookup attempted,
and proof resolution attempted, but it remains no-live evidence. It must not
be treated as approval, execution authority, Coinbase read/cancel/submit
authority, active-placement cancel/replace authority, reconciliation
execution, lifecycle/order/exchange mutation, browser approval, or BFF
execution authority.
Those same exact command responses may include `execution_candidate`,
`execution_preflight`, `execution_transition_barrier`, and
`execution_live_readiness`. `execution_preflight` is not a second preflight
engine or command gate; it is read-only evidence derived from the backend
candidate and unresolved blocker chain. `execution_live_readiness` is the
blocked M55 handoff closure after the transition barrier; it names the
backend decisions still required before live authority can exist and exposes
typed `backend_decisions` rows for those decisions. The ledger is display
evidence only; it does not create a decision writer, satisfy a missing
artifact, construct adapters, or approve execution. These fields keep
execution blocked while proving that manager invocation, Coinbase
submit/cancel/read, active-placement cancel/replace, reconciliation
execution, state mutation, browser approval, and BFF execution authority did
not run.
The command-suite response also exposes `blocker_closures` as the current M55
backend blocker-closure ledger. This is a route-level, read-only summary over
the concrete blockers that still prevent the future executable stealth path.
It is not a replacement for the exact command-response
`execution_live_readiness` ledger and it is not a command gate. It names the
missing backend contracts and next backend steps, but it keeps live service
enablement, live adapter construction, manager invocation, Coinbase
submit/cancel/read, active-placement cancel/replace, repair/rollback,
reconciliation execution, and state mutation disabled.
The command-suite response also exposes `enablement_candidate_reviews` as the
current M55 route-level candidate review. This is not another recursive
evidence ledger and it is not a command gate. It ranks existing command routes
so backend work can select the next no-live implementation target. Every
candidate keeps `candidate_executable=false`,
`candidate_execution_allowed=false`, `manager_invocation_allowed=false`,
`coinbase_submit_allowed=false`, `coinbase_cancel_allowed=false`,
`coinbase_read_allowed=false`, `reconciliation_execution_allowed=false`,
`state_mutation_allowed=false`, browser `display_only`, and BFF
`forward_only_no_execution`.
The command-suite response also exposes `selected_order_action_states` for
the admin frontend's selected-row matrix. These rows are derived from the
same backend `commands` evidence and are command-family templates, not
order-specific adjudication. The frontend may bind display identity to the
selected `stealth_order_id`; exchange `order_id` and active-placement client
ids remain evidence only. The frontend may render these states and link to
command drafts, but it must not decide action usability locally or execute
from the browser/BFF.
The command-suite response also exposes `action_state_handoff_audits` and
`action_state_handoff_audit_summary` for Phase 8106. This audit connects the
backend command-suite rows, selected action-state matrix, and Command Workflows
dry-submit tabs without making any command usable. Create is the only
command-workflow-only row; the other six rows are selected-order prefill
handoffs. Reveal may report `live_execution_status=approval_required` because
it mirrors backend dry-run service posture, but it remains `live_enabled=false`
and `executable=false`.
The command-suite response also exposes `create_cancel_draft_readiness` and
`create_cancel_draft_readiness_summary` for Phase 8107. These rows narrow the
operator-facing draft handoff to stealth create and stealth cancel without
changing execution authority. Create stays blocked on
`lifecycle_write_guard`, does not require a selected-order handoff, and cannot
submit Coinbase orders or mutate lifecycle state. Cancel stays blocked on
`active_placement_exchange_truth`, requires selected-order prefill, and may
only reach exchange cancellation through the backend-owned
`cancel_order(client_order_id)` path after active-placement evidence passes.
Both rows are read-only, prefill-only, non-executable, live-disabled, keyed by
`stealth_order_id`, and treat exchange `order_id` as evidence only.

## Safety Constraints

- `stealth_order_id` is the command identity.
- Active placement client ids and exchange order ids are evidence only.
- Revealed stealth orders cannot be locally hidden, cancelled, moved, or
  repriced unless the active Coinbase placement is cancelled, replaced,
  filled, moved, or reconciled first.
- The route does not create stealth orders, reveal orders, cancel placements,
  move/reprice revealed orders, execute reconciliation, mutate state, read
  Coinbase, or call Coinbase.
- Browser and BFF consumers may display or forward backend evidence only; they
  must not evaluate exchange-truth, mutation-claim, or reveal-trigger
  authority.
- `coverage_gaps.current_read_evidence` is traceability evidence only. It
  does not close missing backend contracts and must not be converted into
  executable recovery/reconciliation controls, proof writing, exchange-state
  mutation, reconciliation execution, Coinbase reads, Coinbase submissions, or
  BFF execution authority.
- `POST /api/v1/stealth/orders/{stealth_order_id}/recovery` and
  `POST /api/v1/stealth/orders/{stealth_order_id}/reconciliation` are
  live-disabled command contracts. They may provide typed admission evidence,
  but they do not execute recovery, reconciliation, proof writing, state
  mutation, Coinbase reads, or Coinbase orders.
- `exchange_truth_checks.current_read_evidence` is traceability evidence only.
  It does not prove exchange truth and must not be converted into Coinbase
  reads, active-placement truth resolution, cancel/replace behavior, reveal
  execution, state mutation, reconciliation execution, or BFF execution
  authority.
- Active-placement exchange-truth snapshot/proof records are local evidence
  only. They keep `exchange_truth_verified=false` and must not be converted
  into Coinbase read authority, cancel/replace behavior, reconciliation
  execution, lifecycle mutation, or browser/BFF exchange-truth authority.
- `cancel_replace_boundaries` is traceability evidence only. It does not close
  missing cancel/replace proof contracts and must not be converted into
  Coinbase cancel/submit/read authority, manager invocation, move/reprice
  execution, lifecycle/order/exchange-state mutation, reconciliation
  execution, command enablement, or BFF execution authority.
- `GET /api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proof` and
  `POST /api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proofs` are
  local proof evidence surfaces only. They must not be converted into
  Coinbase reads, active-placement cancel/replace behavior, manager
  invocation, plan building, reconciliation execution, state mutation, command
  enablement, or BFF execution authority.
- `admission_readiness` is blocked read evidence only. It must not be
  converted into approval, execution, reconciliation, Coinbase reads,
  `StealthOrderManager` invocation, active-placement cancel/replace behavior,
  lifecycle/order/exchange-state mutation, or browser/BFF authority.
- `execution_candidate`, `execution_preflight`, `execution_transition_barrier`,
  and `execution_live_readiness` are exact command-response evidence only.
  They must not be converted into executable adapters, manager invocation,
  Coinbase reads/submits/cancels, active-placement cancel/replace behavior,
  reconciliation execution, lifecycle/order/exchange mutation, browser
  approval, M55 completion claims, or BFF execution authority.
- `blocker_closures` is a read-only M55 blocker ledger on
  `GET /api/v1/stealth/command-suite`. It must not be converted into backend
  live-service enablement, adapter construction, manager invocation, Coinbase
  reads/submits/cancels, active-placement cancel/replace behavior, recovery
  repair/rollback, reconciliation execution, lifecycle/order/exchange
  mutation, browser approval, or BFF execution authority.
- `enablement_candidate_reviews` is a read-only route-ranking ledger on
  `GET /api/v1/stealth/command-suite`. It must not be converted into route
  execution, proof lookup, live-service enablement, adapter construction,
  manager invocation, Coinbase reads/submits/cancels, active-placement
  cancel/replace behavior, reconciliation execution, lifecycle/order/exchange
  mutation, browser approval, or BFF execution authority.
- `admission_readiness.context_requirements` is not proof lookup. Missing
  command-envelope context must keep resolver lookup and proof resolution
  disabled until the backend mutating command path supplies an exact envelope.
- `reveal_trigger_audit` is detail-route evidence only. It does not evaluate
  triggers, call `should_trigger_reveal`, call `reveal_order_slice`, submit
  Coinbase orders, mutate lifecycle state, or authorize browser/BFF reveal
  execution.
- `reveal_submission_audit` is detail-route evidence only. It does not call
  `reveal_order_slice`, create active placements, submit or cancel Coinbase
  orders, read Coinbase, execute reconciliation, mutate lifecycle state, or
  authorize browser/BFF reveal execution.
- `reveal_reconciliation_audit` is detail-route evidence only. It does not
  read Coinbase, resolve or write proof records, execute reconciliation,
  mutate order/lifecycle state, or authorize browser/BFF reveal execution.

## References

- [Stealth Order Reads](docs/STEALTH_ORDER_READS.md)
- [Command Workflows](docs/COMMAND_WORKFLOWS.md)
- [Stealth Command Suite Examples](docs/examples/stealth-command-suite.md)
- [Stealth Active-Placement Exchange-Truth Evidence](README.stealth-exchange-truth-proofs.md)
- [Stealth Active-Placement Exchange-Truth Examples](docs/examples/stealth-exchange-truth-proofs.md)
- [Stealth Cancel/Replace Proofs](README.stealth-cancel-replace-proofs.md)
- [Stealth Cancel/Replace Proof Examples](docs/examples/stealth-cancel-replace-proofs.md)
- [Public Invariants](docs/agents/INVARIANTS.md)
