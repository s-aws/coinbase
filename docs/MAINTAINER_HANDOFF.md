# Maintainer Handoff

This guide is the backend entry point for maintainers and contextless agents
working on the enterprise admin platform.

## Scope

The backend repository owns trading behavior, Coinbase integration, guard
checks, authorization, audit evidence, OpenAPI schema generation, and all live
execution authority. The frontend repository at `C:\coinbase-frontend` owns the
browser application and must consume backend-owned contracts only.

Spot is the first complete product module, not the generic model for futures,
perpetuals, stealth orders, movement/repricing, or future modules.

## Start Here

1. Read `AGENTS.md`, then `agent.md`.
2. Read `docs/README.md` for the ordered documentation index.
3. Read `README.admin-api.md` for the Admin API boundary.
4. Read `docs/ADMIN_MODULE_CAPABILITY_MATRIX.md` before changing module scope.
5. Read `docs/plans/ADMIN_API_ROUTE_INVENTORY.md` before adding or changing a route.
6. Read `docs/LIVE_ORDER_SURFACES.md` before any live-order or cancellation work.
7. Read `docs/plans/ADMIN_API_CONTEXTLESS_REVIEW_LOG.md` before declaring a handoff complete.
8. Read `docs/plans/AUTONOMOUS_WORK_QUEUE.md` before advancing phases. Each
   active phase must map to an approved durable milestone and an explicit
   architecture or planning gap.

## Backend Authority Rules

- Use one code path per behavior.
- Use `client_order_id` for internal order identity.
- Coinbase cancellation is the explicit exception: call the project wrapper
  `cancel_order(client_order_id)` because Coinbase accepts the client id.
- Do not put trading decisions in browser code or generated frontend clients.
- Do not import spot no-shorting or wallet-inventory rules into futures or
  perpetual workflows.
- Do not mutate stealth local state unless the corresponding live exchange
  handling has gone through the existing cancel, move, or reconcile path.

## Adding An Admin Module

1. Define the backend read or command contract first.
2. Add route inventory evidence in `application/admin_api/route_inventory.py`
   and `docs/plans/ADMIN_API_ROUTE_INVENTORY.md`.
3. Add typed response/request models in `application/admin_api/models.py`.
4. Use existing shared services; do not introduce a parallel trading path.
5. Update `docs/ADMIN_MODULE_CAPABILITY_MATRIX.md`.
6. Update examples under `docs/examples/`.
7. Regenerate `openapi/coinbase-admin-api.yaml`.
8. Add focused regression coverage in `tests/regression/`.
9. Coordinate frontend generated-client changes from the OpenAPI output.
10. Run a blind/contextless review for module discoverability and authority boundaries.

## Contextless Task Card

Use this checked-in task shape when asking a fresh agent to prove the handoff
material is sufficient:

```text
Without chat history, explain how to add a read-only Admin API module for a
new backend evidence source. Identify the files you would read first, the
backend route/model/test/docs files you would change, how the frontend should
consume the generated OpenAPI contract, and which gates must pass. Do not
implement trading behavior or live Coinbase execution.
```

Passing answer requirements:

- names `docs/MAINTAINER_HANDOFF.md`, `README.admin-api.md`,
  `docs/plans/ADMIN_API_ROUTE_INVENTORY.md`, and
  `docs/ADMIN_MODULE_CAPABILITY_MATRIX.md`
- keeps backend authority over trading behavior and live execution
- sends frontend work through OpenAPI generation and canonical wrappers
- lists backend regression, frontend release gate, autonomous validation, and
  blind/contextless review
- reports live Coinbase execution as not run unless an explicit live phase is
  approved

## Required Gates

Backend changes must pass:

```powershell
pytest tests\regression\ -v --tb=short
python tools\run_autonomous_work_queue_check.py --summary-only
```

Frontend/API association changes must also pass in `C:\coinbase-frontend`:

```powershell
npm run release:gate
```

Live Coinbase execution is not part of normal handoff validation. If a live
phase is explicitly approved, report product, submitted notional, executed
notional, retained inventory, reconciliation result, and audit ids.

## Current Handoff State

- M9/M21/M23/M24/M25/M26 enterprise readiness is exposed by
  `GET /api/v1/admin/enterprise-readiness`.
- Latest completed autonomous range: `3481-3500` under M55.
- Active autonomous range: `3501-3520` under M55.
- Completed 3421-3440 work consumes backend-owned stealth state-mutation
  policy proof/readback evidence as exact-command resolver evidence. Safe
  exact proof rows may resolve the `state_mutation_policy` prerequisite row,
  but live-readiness decisions remain unresolved and fail-closed with no
  mutation or execution authority. Completed 3441-3460 work expanded the existing
  disabled `live_execution_service_contract` with backend-only enablement
  preconditions, missing artifacts, verification gates, and blockers. Those
  fields are evidence-only and do not enable live service construction,
  Coinbase calls, manager invocation, reconciliation execution,
  active-placement cancel/replace, state mutation, browser authority, or BFF
  execution authority. Completed 3461-3480 work expanded the existing disabled
  `live_execution_adapter_contract` with backend-only construction
  preconditions, missing artifacts, verification gates, and blockers. Those
  fields are evidence-only and do not construct adapters, create a second
  adapter path, call Coinbase, invoke managers, execute reconciliation,
  cancel/replace active placements, mutate lifecycle/order/exchange state,
  grant browser authority, or grant BFF execution authority. Completed
  3481-3500 work adds backend-owned traceability from remaining execution
  blocker rows to the disabled live-service and live-adapter contracts. Trace
  fields identify authority, contract/evidence refs, required/missing
  artifacts, gates, and blockers; they do not resolve live service or adapter
  blockers. Active 3501-3520 work adds append-only backend-owned live-service
  decision evidence and must keep service enabled false, live Coinbase
  approval false, status blocked, submitted/executed notional zero, and all
  execution authority disabled.
- M49 approval lifecycle, M50 cap/guard records, M51 admission audits, and
  M52 reconciliation plan records are complete. M53 closed with a single
  dry-run pilot adapter for `POST /api/v1/orders` through
  `AdminApiCommandService.place_manual_order`. M54 completed the first
  read-only Spot command-suite slice, backend-owned proof-route linkage, and
  backend-owned readiness preconditions at
  `GET /api/v1/spot/command-suite` for manual order, cancel by
  `client_order_id`, and campaign execution readiness, then bound those rows
  into website command workflow draft evidence. M54 then added typed
  `coverage_gaps` for spot sweep automation, recovery workflow, and
  reconciliation workflow so missing spot admin families are explicit before
  new command routes or live controls exist. M54 then linked those gap rows to
  typed `current_read_evidence` rows derived from route inventory and added
  durable Spot P/L checkpoint records at `/api/v1/spot/pnl/checkpoints`. M54
  then extended that same checkpoint path with average-cost review evidence,
  verified append-only Admin API audit-link readback, read-only recovery-link
  evidence to backend-owned recovery gate and fill-ledger-health reads, and
  read-only reconciliation-plan link evidence to backend-owned reconciliation
  plan reads. P/L tracking is no longer a current command-suite coverage gap.
  M54 then added the read-only Spot recovery-preview route, and the 1821-1840
  range extended that foundation with read-only recovery apply-review,
  rollback-plan, and reconciliation-proof routes. The completed 1841-1860 range added
  disabled/no-live POST contracts for recovery apply execution, rollback
  execution, exchange-state proof recording, and reconciliation-proof
  recording. The completed 1861-1880 range added durable proof persistence,
  proof readback, and the `spot_recovery:record` permission for proof
  recording. The completed 1881-1900 range added no-live recovery
  apply/rollback execution journal plumbing and post-apply reconciliation
  boundaries. The completed 1901-1920 range added guarded local repair-result
  evidence and clarified that recovery-state evidence is not order/exchange
  mutation, Coinbase activity, or browser authority. The completed 1921-1940 range adds
  backend-owned post-apply reconciliation completion evidence: reconciliation
  proof recording can append a guarded local completion record only after
  matching proof, apply journal, repair-result, approval, admission audit,
  cap/guard, reconciliation-plan, idempotency, operator-intent, and
  payload-hash evidence. Recovery apply/rollback journal acceptance, guarded
  repair-result evidence, and completion records are durable after exact
  backend prerequisites match. The completed 1941-1960 range added the
  route-bound fail-closed reconciliation execution boundary at
  `POST /api/v1/spot/recovery/reconciliation-executions`; that route is
  audited, idempotent, RBAC/proof-gated, and rejected until backend executor
  and live Coinbase read authority exist. The completed 1961-1980 range adds
  backend-owned no-live snapshot records; those records do not read Coinbase
  or prove live exchange truth. The completed 1981-2000 range started M55 by
  adding read-only stealth command-suite readiness evidence for create,
  cancel, reveal, move, reprice, recovery, and reconciliation workflows and
  linked existing live-disabled stealth cancel and movement/reprice route
  evidence without enabling them. The completed 2001-2020 range added a
  route-bound, live-disabled `POST /api/v1/stealth/orders` create command draft
  keyed by `stealth_order_id`, with backend-owned identity derivation, route
  inventory, command-suite linkage, frontend generated types, BFF forwarding,
  and dry-submit evidence. The completed 2021-2040 range added a
  route-bound, live-disabled
  `POST /api/v1/stealth/orders/{stealth_order_id}/reveal` command draft keyed
  by `stealth_order_id` without invoking `reveal_order_slice`, calling
  `StealthOrderManager`, submitting Coinbase orders, mutating local lifecycle
  state, or executing reconciliation. The completed 2041-2060 range continues M55
  by adding a route-bound, live-disabled
  `POST /api/v1/stealth/orders/{stealth_order_id}/move` command draft keyed by
  `stealth_order_id`. Move is `live_exchange_cancel` shaped, but it must not
  invoke `build_stealth_move_plan`, call `execute_stealth_move`, call
  `StealthOrderManager`, submit or cancel Coinbase orders, perform
  cancel/replace, create or mutate local stealth/order/exchange state, execute
  reconciliation, read Coinbase, or grant browser/BFF stealth command
  authority. This foundation must not add
  a parallel writer,
  browser P/L authority, sell authority, tax accounting, browser audit
  authority, browser recovery authority, browser reconciliation authority,
  recovery execution, repair apply, rollback execution, reconciliation
  execution, order/exchange-state mutation, or Coinbase execution. Live
  Coinbase execution
  remains disabled unless a later phase explicitly runs under the carried cap
  policy.
  Browser approval, BFF forwarding, linked snapshots, cap/guard records, audit
  records, reconciliation plans, command-suite proof routes, command draft
  evidence, or pilot adapter evidence are not sufficient live execution
  authority by themselves.
  The completed 2061-2080 range added a read-only exchange-truth prerequisite
  ledger to `GET /api/v1/stealth/command-suite`. The ledger must keep
  `stealth_order_id` as the only accepted command identity, list active
  placement client ids and exchange order ids as evidence-only rejected command
  keys, and show required/missing active-placement, mutation-claim,
  cancel/replace, lifecycle-write, trigger/submission, and reconciliation
  contracts without granting browser, BFF, Coinbase, or local mutation
  authority. The completed 2081-2100 range added a no-live active-placement audit
  block to the existing `GET /api/v1/stealth/orders/{stealth_order_id}` detail
  response. The audit may show local active-placement evidence and required
  contracts for cancel, move, and movement/reprice, but it must not read
  Coinbase, cancel or replace active placements, mutate lifecycle state,
  execute reconciliation, add a new endpoint, or grant browser/BFF
  exchange-truth authority. The completed 2101-2120 range added no-live
  mutation-claim audit evidence to that same existing detail route. The audit
  may reuse existing runtime mutation-claim snapshots for move/reprice
  readiness, but it must not acquire claims, release claims, bypass manager
  locks, execute cancel/replace, mutate lifecycle state, execute
  reconciliation, call Coinbase, add a new endpoint, or grant browser/BFF
  claim authority. The completed 2121-2140 range added no-live reveal-trigger
  audit evidence to that same existing detail route. The audit may show local
  reveal-condition evidence and missing trigger-guard contracts for reveal
  readiness, but it must not evaluate triggers, call `should_trigger_reveal`,
  call `reveal_order_slice`, submit Coinbase orders, mutate lifecycle state,
  execute reconciliation, add a new endpoint, or grant browser/BFF trigger or
  reveal authority. The completed 2141-2160 range added no-live reveal
  submission-adapter audit evidence to that same existing detail route. The
  audit may show the future backend reveal route, shared service method,
  manager method, local active-placement blockers, missing
  submission/reconciliation contracts, and no-live flags, but it must not call
  `reveal_order_slice`, create active placements, submit or cancel Coinbase
  orders, read Coinbase, mutate lifecycle state, execute reconciliation, add a
  new endpoint, or grant browser/BFF reveal authority. The completed 2161-2180
  range added no-live reveal reconciliation audit evidence to that same detail
  route. The audit may show required reconciliation plan/proof posture, local
  active-placement evidence, missing proof contracts, read-evidence routes,
  and no-live flags, but it must not read Coinbase, resolve or write proof
  records, execute reconciliation, mutate order or lifecycle state, add a new
  endpoint, or grant browser/BFF reveal authority. The completed 2181-2200 range
  added read-only stealth create lifecycle-write audit evidence to the existing
  `GET /api/v1/stealth/command-suite` route. That audit may show the
  live-disabled create route, shared service method, existing manager method,
  accepted/rejected identity keys, required lifecycle-write/admission/
  reconciliation contracts, blockers, and no-live/no-write flags, but it must
  not invoke `StealthOrderManager`, write stealth rows, write `order_parent`
  rows, dispatch lifecycle events, submit Coinbase orders, read Coinbase,
  execute reconciliation, mutate lifecycle state, add a new endpoint, or grant
  browser/BFF lifecycle-write authority. The completed 2201-2220 range added
  proof-route and gate-chain linkage to that same audit. It may show backend
  proof routes, required permissions, shared methods, and missing gates, but it
  must not create proof records, mutate proof stores, evaluate guards, execute
  reconciliation, invoke the manager, write lifecycle state, call Coinbase, add
  a new endpoint, or grant browser/BFF proof or lifecycle-write authority. The
  completed 2221-2240 range linked the remaining stealth command-suite coverage
  gaps, especially recovery and reconciliation, to typed backend-owned read
  evidence routes. It may show route, method, permission, shared method,
  documentation refs, and display/read-only authority, but it must not create
  recovery/reconciliation commands, write proof records, mutate stealth/order/
  exchange state, execute reconciliation, call Coinbase, trust browser
  exchange evidence, or grant browser/BFF execution authority. The completed
  2241-2260 range linked the stealth command-suite `exchange_truth_checks` to
  typed backend-owned read evidence rows. It may show route, method,
  permission, shared method, documentation refs, and display/read-only
  authority, but it must not claim Coinbase reads ran, prove active-placement
  exchange truth, cancel/replace placements, reveal orders, execute
  reconciliation, mutate stealth/order/exchange state, create proof records,
  or grant browser/BFF execution authority. The completed 2261-2280 range
  added route-bound, live-disabled stealth recovery and reconciliation command
  contracts keyed by `stealth_order_id`. It added request/command models,
  FastAPI adapters, shared service fail-closed responses, route inventory,
  OpenAPI, command-suite metadata, frontend schema, mocks, and dry-submit
  display evidence, but it did not execute recovery repair, rollback,
  reconciliation, proof writers, Coinbase reads, Coinbase orders,
  `StealthOrderManager` mutations, local stealth/order lifecycle mutations,
  exchange-state mutations, or browser/BFF command authority. The completed
  2281-2300 range added backend-owned append-only active-placement
  exchange-truth snapshot/proof evidence and readback keyed by
  `stealth_order_id`. It may persist local evidence records and link them to
  command-suite blockers, but it must not run Coinbase reads, cancel/replace
  active placements, execute reconciliation, mark exchange truth verified,
  mutate stealth/order/exchange state, or grant browser/BFF command authority.
  The completed 2301-2320 range added a backend-owned
  `admission_readiness` ledger to the existing
  `GET /api/v1/stealth/command-suite` response. It binds each stealth command
  route to required approval, admission-audit, cap/guard, reconciliation,
  active-placement exchange-truth or lifecycle-write, disabled live adapter,
  and post-live reconciliation evidence. It must not approve, execute,
  reconcile, read Coinbase, call `StealthOrderManager`, cancel/replace active
  placements, mutate lifecycle/order/exchange state, or grant browser/BFF
  command authority. The completed 2321-2340 range added command-envelope
  context requirements to those admission-readiness rows. The completed
  2341-2360 range added command-response context echo evidence for
  live-disabled stealth dry-submit responses. Command-suite reads still show
  missing exact context, while a concrete command response may show exact
  route, identity, actor, idempotency, operator-intent, and payload-hash
  context as backend evidence. It must not approve admission, execute
  commands, reconcile, read Coinbase, call `StealthOrderManager`,
  cancel/replace active placements, mutate lifecycle/order/exchange state, or
  grant browser/BFF authority. The completed 2361-2380 range added
  backend-owned stealth create lifecycle-write guard proof records, readback,
  command-suite proof-route linkage, OpenAPI/frontend sync, tests, and blind
  review. The completed 2381-2400 range added stealth create lifecycle-write
  execution-contract boundary evidence as no-live readiness. The completed
  2401-2420 range advanced the missing stealth create
  execution-prerequisite resolver boundary as exact-context read evidence
  only. It must not invoke `StealthOrderManager`, write `stealth_orders` or
  `order_parent` rows, dispatch lifecycle events, submit/read/cancel
  Coinbase, replace active placements, execute reconciliation, mutate
  stealth/order/exchange state, approve live admission, use proof lookup as
  execution authority, or grant browser/BFF execution authority. The completed
  2421-2440 range added typed backend-owned non-create stealth command
  execution posture on reveal, cancel, move, recovery, reconciliation, and
  movement/reprice responses without invoking managers, canceling/replacing
  active placements, calling Coinbase, executing reconciliation, mutating
  lifecycle/order/exchange state, or granting browser/BFF execution authority.
  The completed 2441-2460 range added resolver-backed active-placement
  exchange-truth proof evidence to those command responses using only the
  existing append-only backend proof store. It resolves only
  `active_placement_exchange_truth` for the latest safe
  same-`stealth_order_id` proof record, fails closed on latest unsafe proof
  records, and must not verify Coinbase, resolve reveal-trigger/
  mutation-claim/recovery/reconciliation proof, execute commands, or grant
  browser/BFF authority.
  The completed 2461-2480 range added backend-owned mutation-claim snapshot
  proof records, readback, command-suite proof-route linkage, and exact-context
  resolver evidence for move and movement/reprice posture. It may resolve only
  `mutation_claim_snapshot` from the latest safe same-`stealth_order_id`
  proof record and must not acquire or release runtime claims, invoke
  `StealthOrderManager`, cancel/replace placements, call Coinbase, execute
  reconciliation, mutate state, or grant browser/BFF authority. The completed
  2481-2500 range added backend-owned recovery proof records, readback,
  command-suite proof-route linkage, and exact-context resolver evidence for
  stealth recovery posture only. It may resolve only `recovery_proof` from the
  latest safe same-`stealth_order_id` proof record and must not repair state,
  roll back state, invoke managers, call Coinbase, cancel/replace placements,
  execute reconciliation, mutate state, or grant browser/BFF authority. The
  completed 2501-2520 range added backend-owned reveal-trigger proof records,
  readback, command-suite proof-route linkage, and exact-context resolver
  evidence for stealth reveal posture only. It may resolve only
  `reveal_trigger_evidence` from the latest safe same-`stealth_order_id`
  proof record and must not evaluate triggers, call `should_trigger_reveal`,
  call `reveal_order_slice`, invoke managers, call Coinbase, execute
  reconciliation, mutate state, or grant browser/BFF authority. The completed
  2521-2540 range added backend-owned reconciliation proof records, readback,
  proof-route linkage, and exact-context resolver evidence for stealth
  reconciliation posture only. It may resolve only `reconciliation_proof`
  from the latest safe same-`stealth_order_id` proof record and must not run
  reconciliation, build reconciliation plans, invoke managers, call Coinbase,
  cancel/replace active placements, mutate state, or grant browser/BFF
  authority. The completed 2541-2560 range closed reconciliation-proof current
  read-evidence parity and planned active-placement cancel/replace proof
  boundaries for cancel, move, and reprice without adding execution authority.
  The completed 2561-2580 range added append-only cancel/replace proof records
  and readback for stealth cancel, stealth move, and movement reprice while
  keeping manager invocation, Coinbase cancel/replace, reconciliation
  execution, and state mutation disabled. The completed 2581-2600 range added
  exact-context resolver linkage for those proof records. The completed
  2601-2620 range made disabled `live_execution_service`,
  `live_execution_adapter`, `post_write_reconciliation`, and canonical backend
  execution-path evidence route-specific and contextless for non-create
  stealth command posture. The completed 2621-2640 range brought stealth create
  lifecycle execution contracts and command-suite admission evidence into
  parity with the same disabled boundary fields. The completed 2641-2660 range
  added nested `post_write_reconciliation_boundary` evidence. The completed
  2661-2680 range added nested `live_execution_adapter_contract` evidence from
  the shared backend adapter builder. The completed 2681-2700 range added
  nested `live_execution_service_contract` evidence projected from the
  disabled backend live execution service state. The completed 2701-2720 range
  added nested `live_execution_intent_contract` evidence from the existing
  admission-decision intent when exact command context exists. The completed
  2721-2740 range added nested `active_placement_cancel_replace_contract`
  evidence for exact stealth cancel, stealth move, and movement/reprice
  command responses by reusing the command-suite cancel/replace boundary
  builder. The completed 2741-2760 range added nested
  `active_placement_exchange_truth_contract` evidence for exact stealth
  cancel, stealth move, recovery, reconciliation, and movement/reprice command
  responses by reusing the command-suite exchange-truth boundary builder. It
  must not read Coinbase, prove live exchange truth, execute cancel/replace,
  construct executable adapters, record reconciliation plans, execute
  recovery or reconciliation, invoke managers, call Coinbase, mutate state, or
  grant browser/BFF authority. The completed 2761-2780 range added
  `command_specific_proof_contracts` evidence for exact stealth reveal, move,
  reprice, recovery, and reconciliation command responses by reusing the
  command-suite proof-route shape. The completed 2781-2800 range added
  ordered `execution_readiness_stages` evidence derived from the existing
  non-create prerequisite resolver output. The completed 2801-2820 range added
  the same ordered stage parity to stealth create lifecycle-write execution
  contracts. The completed 2821-2840 range added append-only post-write
  reconciliation proof evidence and readback. The completed 2841-2860 range
  made create and non-create execution prerequisite resolvers aware of
  exact-context post-write proof records while keeping
  `post_write_reconciliation` missing. The completed 2861-2880 range added an
  explicit post-write completion verifier. The completed 2881-2900 range added
  backend-owned post-write execution-journal acceptance evidence that can
  satisfy only the journal-acceptance part of the verifier. The completed
  2901-2920 range added backend-owned post-write reconciliation verification
  records that can satisfy only the verifier's
  `verified_post_write_reconciliation` display gate when they match the same
  safe proof and accepted journal. The completed 2921-2940 range made create
  and non-create post-write prerequisite resolvers consume the exact safe
  proof, accepted journal, and verification chain. That chain may resolve
  only `post_write_reconciliation`; live service/adapter execution, Coinbase
  calls, manager invocation, active-placement cancel/replace, reconciliation
  execution, lifecycle/order/exchange mutation, and browser/BFF authority
  remain disabled. The completed 2941-2960 range added typed remaining
  execution blocker-chain evidence so contextless readers can see those live
  and state-mutating blockers after post-write evidence resolves. The
  completed 2961-2980 range names the backend execution candidate that would
  run only after every blocker resolves, while keeping the candidate blocked,
  no-live, backend-owned, and display-only. The completed 2981-3000 range
  binds read-only pre-execution preflight checks to that candidate. The
  completed 3001-3020 range adds an explicit execution-transition barrier
  derived from preflight without enabling live service, adapters, managers,
  Coinbase, reconciliation, state mutation, browser authority, or BFF
  execution authority. The completed 3021-3040 range added blocked
  live-readiness closure evidence after that barrier, naming required backend
  decisions, handoff blockers, and forbidden execution claims while keeping
  live execution disabled. The completed 3041-3060 range added a typed backend
  decision ledger derived from that live-readiness evidence so required
  decisions name their owner, required artifact, missing reason, and blocked
  no-live/no-write proof without adding execution authority. The completed
  3061-3080 range added explicit resolution artifacts, backend contract
  references, evidence references, and disabled resolver/writer flags to each
  backend decision row; these criteria are display evidence only and do not
  resolve decisions or enable live execution. The completed 3081-3100 range
  added ordered backend planning steps, dependency refs, verification gates,
  and disabled plan-execution flags to those rows; sequencing is planning
  evidence only and does not resolve decisions or enable live execution. The
  completed 3101-3120 range expanded those strings into structured blocked
  readiness rows with source, order, missing reason, authority, and
  no-execution evidence. The completed 3121-3140 range added backend-derived
  readiness summaries over those rows while preserving blocked/no-live
  display-only authority. The completed 3141-3160 range added backend-owned
  decision-resolution handoff classification over those summaries. The
  completed 3161-3180 range added blocked backend-owned clearance action
  contracts for each handoff ref. The completed 3181-3200 range bound those
  clearance actions to source readiness items and predecessor/successor
  dependency evidence. The completed 3201-3220 range added backend-derived
  clearance dependency summaries while preserving blocked/no-live display-only
  authority. The completed 3221-3240 range added a backend-derived decision
  resolution summary over the full backend decision ledger without granting
  resolver, writer, completion, execution, browser, or BFF authority. The
  completed 3241-3260 range added backend-derived decision resolution work
  queue rows over each unresolved decision's first blocked clearance action.
  The completed 3261-3280 range added backend-derived forbidden execution
  claim traceability that maps each forbidden claim to the backend decision and
  clearance action that keeps it blocked without granting resolver, writer,
  execution, browser, or BFF authority. The completed 3281-3300 range added
  backend-owned manager-invocation policy proof/readback evidence without
  granting manager invocation, Coinbase, reconciliation, browser, or BFF
  authority. The completed 3301-3320 range consumes that proof surface as
  exact-command prerequisite resolver evidence for stealth create and
  non-create command execution contracts while keeping manager invocation,
  Coinbase, reconciliation, browser, and BFF authority disabled. The completed
  3321-3340 range adds backend-owned Coinbase exchange submission-policy
  proof/readback evidence for guarded stealth commands while keeping Coinbase
  submit, cancel, read, manager invocation, reconciliation, state mutation,
  browser, and BFF authority disabled. The completed 3341-3360 range adds
  backend-owned post-write reconciliation execution-policy proof/readback
  evidence while keeping reconciliation execution, Coinbase activity, manager
  invocation, active-placement cancel/replace, state mutation, browser, and
  BFF authority disabled. The completed 3361-3380 range consumes the Coinbase
  exchange submission-policy and post-write reconciliation execution-policy
  proof/readback records as exact-command prerequisite resolver evidence only,
  while keeping Coinbase activity, manager invocation, reconciliation
  execution, active-placement cancel/replace, state mutation, browser, and BFF
  authority disabled. Resolver lookups use the newest exact-command policy
  proof row, ignore newer rows for other guarded command contexts, and block
  on a newer unsafe exact-command row.
  The completed 3381-3400 range consumes those resolver rows inside
  `execution_live_readiness` decision artifact evidence. Completed phases
  3401-3420 added backend-owned state-mutation policy proof/readback evidence;
  completed phases 3421-3440 consume it as resolver-only prerequisite
  evidence. Completed phases 3441-3460 added backend-only enablement
  precondition evidence to the existing disabled `live_execution_service_contract`.
  Completed phases 3461-3480 added backend-only construction precondition
  evidence to the existing disabled `live_execution_adapter_contract`.
  Completed phases 3481-3500 add blocker-chain traceability for those disabled
  live service and adapter contracts. Active phases 3501-3520 add disabled
  live-service decision evidence only. Backend decisions remain blocked and
  live execution, Coinbase, manager, reconciliation, state mutation, browser,
  and BFF authority remain disabled.
- M48 mutation taxonomy and authority map is complete for phases `1461-1480`.
  The existing `GET /api/v1/admin/enterprise-readiness` route reports
  backend-owned `mutation_taxonomy` rows that map every current command route,
  approval lifecycle local-state mutation route, and legacy command surface to
  exactly one mutation family.
- M47 backend functionality inventory and gap ledger is complete for phases
  `1441-1460`. The existing `GET /api/v1/admin/enterprise-readiness` route
  reports backend-owned workflow inventory rows for read, command, live,
  recovery, repair, automation, and legacy compatibility surfaces.
- M46 live readiness precondition evidence is complete for phases
  `1421-1440`.
  `GET /api/v1/admin/live-enablement` may report a normalized backend-owned
  checklist for approval store, approval snapshot, admission audit, cap/guard,
  reconciliation, live execution adapter, execution intent envelope,
  browser/BFF boundary, and disabled live execution service prerequisites.
  The checklist is read-only evidence. Do not call command admission with
  synthetic values, create a new preflight endpoint, remove command blockers,
  mark paths live eligible, add browser approval, broaden BFF execution
  authority, or call Coinbase from this evidence.
- M45 live execution intent envelope evidence is complete for phases
  `1401-1420`. Existing command
  admission decisions may report a backend-owned execution intent that binds
  route, identity, payload hash, idempotency key, actor, operator intent, and
  shared `AdminApiCommandService` method, but the intent remains disabled, not
  prepared, non-executable, and display only. Do not add route-local
  execution, browser approval, BFF execution authority, or Coinbase calls.
- M44 live execution adapter contract evidence is complete for phases
  `1381-1400`. Existing
  live-enablement path rows may report a backend-owned adapter contract that
  maps a live-shaped route to its shared `AdminApiCommandService` method, but
  the adapter remains disabled, unconfigured, non-executable, and display
  only. Do not add route-local execution, browser approval, BFF execution
  authority, or Coinbase calls.
- M43 disabled live execution service foundation is complete for phases
  `1361-1380`. Existing Admin API command admission evidence consumes a
  backend-owned disabled service descriptor reporting the service as present
  but `live_disabled` with source `disabled_backend_service`. The descriptor
  must not expose create, cancel, submit, execute, Coinbase, route-local
  execution, browser approval, or BFF execution authority methods.
- M42 command admission live execution service boundary evidence is complete
  for phases `1341-1360`. Existing Admin API command admission evidence may
  report that the
  backend live execution service is required but disabled/unconfigured. It
  must not remove `live_execution_disabled`, add a live switch, authorize
  browser evidence, broaden BFF mutation authority, call Coinbase, or create
  a second command path.
- M41 command admission reconciliation plan proof wiring is complete for
  phases `1321-1340`. Existing Admin API command admission evidence may
  consult backend-owned append-only reconciliation plan proof after exact
  approval snapshot, admission-audit, and cap/guard proof resolution. A
  resolved reconciliation proof may remove only
  `reconciliation_plan_missing`; live-disabled and browser-authority blockers
  remain. It must not add reconciliation execution, a reconciliation mutation
  endpoint, browser approval, BFF reconciliation authority, live admission
  endpoint, Coinbase calls, direct dashboard WebSocket reconciliation, browser
  reconciliation writer, or order/exchange-state mutation.
- M40 command admission cap/guard proof wiring is complete. Existing Admin
  API command admission evidence may consult backend-owned append-only
  cap/guard decision proof and expose whether an exact approval-snapshot-bound
  and admission-audit-bound decision was found. A resolved cap/guard proof may
  remove only `cap_guard_missing`; live-disabled, reconciliation, and
  browser-authority blockers remain. It must not add a guard mutation
  endpoint, browser approval, BFF guard authority, live admission endpoint,
  guard evaluator, Coinbase call, direct dashboard WebSocket guard path,
  browser guard writer, or reconciliation authority.
- M39 command admission audit resolver wiring is complete. Existing Admin API
  command admission evidence may consult backend-owned append-only audit proof
  and expose whether an exact approval-snapshot-bound audit event was found. A
  resolved audit proof may remove only `admission_audit_missing`;
  live-disabled, cap/guard, reconciliation, and browser-authority blockers
  remain. It did not add an audit mutation endpoint, browser approval, BFF
  audit authority, live admission endpoint, guard evaluator, Coinbase call,
  direct dashboard WebSocket audit path, browser approval workflow, browser
  audit writer, or reconciliation authority.
- M38 command admission snapshot resolver wiring is complete. Existing Admin
  API command admission evidence can consult the backend-owned approval
  snapshot resolver and expose whether an exact unexpired snapshot was found.
  A resolved snapshot removes only `approval_snapshot_missing`; live-disabled,
  admission-audit, cap/guard, reconciliation, and browser-authority blockers
  remain. It did not add an approval endpoint, approval mutation, live
  admission endpoint, guard evaluator, Coinbase call, direct dashboard
  WebSocket approval path, BFF resolver authority, browser approval workflow,
  browser approval writer, or reconciliation authority.
- M37 approval snapshot resolver foundation added backend-only resolver
  infrastructure that derives immutable approval snapshot evidence from an
  exact unexpired approval-store record without approving or executing
  commands.
- Approval-store JSONL rows without M37 `requested_by_actor_id` fail closed
  during strict reads and are ignored by resolver lookup.
- M36 durable approval-store foundation added backend append-only
  approval-store infrastructure and evidence only. It did not add approval
  mutation, browser approval, live admission, or live Coinbase execution.
- M35 command admission audit persistence writes admission decisions through
  the existing append-only Admin API audit log and Audit Workbench read path
  only. Persisted admission decisions can describe route, payload hash,
  idempotency, operator intent, approval snapshot, cap/guard,
  admission-audit, and reconciliation blockers, but they must not become
  browser approval, browser wallet authority, audit mutation, guard execution,
  a new command route, Coinbase execution, or reconciliation authority.
- M34 command admission decision evidence is exposed through existing
  live-disabled Admin API command responses. It must remain evidence-only:
  decisions can describe route, payload hash, idempotency, operator intent,
  approval, cap/guard, admission-audit, and reconciliation blockers, but they
  must not become browser approval, browser wallet authority, guard execution,
  a new command route, Coinbase execution, or reconciliation authority.
- M32 live-admission audit trail evidence is exposed through the existing
  `GET /api/v1/admin/live-enablement` read. It must remain evidence-only:
  facts can describe what an append-only backend admission audit trail must
  prove, but they must not become audit storage, approval storage, browser
  approval, a command route, Coinbase execution, or reconciliation authority.
- M31 approval-store contract evidence is exposed through the existing
  `GET /api/v1/admin/live-enablement` read. It must remain evidence-only:
  requirements can describe configured durable backend approval-store
  infrastructure, but they must not become approval mutation, browser
  approval, a command route, Coinbase execution, or reconciliation authority.
- M30 route-specific approval snapshot evidence is exposed through the
  existing `GET /api/v1/admin/live-enablement` read. It must remain
  evidence-only: required fields can describe what a durable backend approval
  snapshot must contain, but they must not become approval storage, browser
  approval, a command route, Coinbase execution, or reconciliation authority.
- M29 controlled-live preflight evidence is exposed through the existing
  `GET /api/v1/admin/live-enablement` read. It must remain evidence-only:
  passed and blocked checks can describe readiness, but they must not become a
  browser preflight approval path, live switch, command route, Coinbase call,
  or reconciliation path.
- M28 enterprise command gap triage uses existing
  `GET /api/v1/admin/enterprise-readiness` and
  `GET /api/v1/admin/capabilities` evidence. It must remain a read-only
  triage lens and must not add a parallel endpoint, command path, or browser
  approval workflow.
- M27 live-action governance linkage uses the existing
  `GET /api/v1/admin/live-enablement`, `GET /api/v1/admin/capabilities`, and
  `GET /api/v1/admin/enterprise-readiness` reads. It must remain evidence
  only and must not add a parallel governance endpoint or live command path.
- The frontend Enterprise Module Catalog consumes the existing readiness
  contract. Do not add a parallel module-catalog endpoint or browser trading
  authority.
- The frontend Enterprise Module Traceability surface also consumes the same
  readiness contract. Do not add a parallel traceability endpoint or use route
  lists, command gaps, or contract refs as browser command authority.
- The frontend Enterprise Module Capability Linkage surface consumes
  `GET /api/v1/admin/capabilities` plus enterprise readiness. Do not add a
  parallel capability-linkage endpoint or treat capability rows as browser
  command authority.
- Default live Coinbase execution: `not_run`.
- Submitted notional: `$0`.
- Executed notional: `$0`.
