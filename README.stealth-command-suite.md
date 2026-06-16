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
  truth or lifecycle-write guard, disabled live adapter, and post-live
  reconciliation
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
Those same exact command responses may include `execution_candidate` and
`execution_preflight`. `execution_preflight` is not a second preflight engine
or command gate; it is read-only evidence derived from the backend candidate
and unresolved blocker chain. It keeps execution blocked while proving that
manager invocation, Coinbase submit/cancel/read, active-placement
cancel/replace, reconciliation execution, state mutation, browser approval,
and BFF execution authority did not run.

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
- `execution_candidate` and `execution_preflight` are exact command-response
  evidence only. They must not be converted into executable adapters,
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
