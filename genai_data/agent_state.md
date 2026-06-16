# Agent State

Use this file as the single durable source of truth for active engineering work.
Keep it short. Keep it factual.

## Metadata

- Last updated (ET): 2026-06-16
- Updated by: Codex
- Branch: main
- Commit (optional): completed range `3041-3060` is captured by the
  synchronized backend/frontend commits for this handoff; previous completed
  range `3021-3040` is backend `dc120798` and frontend `b8f3727`.

## Current Objective

- One-sentence objective: Build the enterprise admin frontend/API path for
  the entire Coinbase trading engine, with Spot as the first complete product
  module but not the generic model.

- Durable objective detail: Every new admin module must use backend-owned
  contracts, preserve the single trading behavior path, avoid importing
  spot-only rules into non-spot domains, and remain understandable to
  contextless/blind agents through docs, capability matrices, tests, and
  review logs.

## Hard Constraints

- Use `client_order_id` for internal tracking.
- Use `order_id` only for exchange-facing operations that require it; the
  project Coinbase wrapper `cancel_order(client_order_id)` is the cancellation
  exception because Coinbase accepts the client id there.
- Single code path per behavior.
- Use enums from `core/enums.py`.
- Respect locks and thread-safety invariants.
- Must pass `pytest tests/regression/ -v --tb=short` for non-agent-file changes.
- Exception: if only agent-instruction/context files changed (`AGENTS.md`, `agent.md`, `ai-context.md`, `genai_data/AGENT_*.md`, `genai_data/agent_state.md`), regression tests may be skipped.

## Latest Completed Scope

- Latest completed autonomous range: `3101-3120`; active range is
  `3121-3140`.
- Latest completed milestone slice: M55 - Stealth Full Admin Command Suite.
- Completed files through `3021-3040`: backend/frontend typed execution
  live-readiness closure evidence for guarded stealth command families,
  OpenAPI, frontend schema/mocks/runtime/read-model display, docs/tests, full
  gates, browser check, and contextless reviews. The closure derives from
  `execution_transition_barrier` and remains blocked, no-live, backend-owned,
  display-only, and BFF forward-only.
- Completed `3041-3060` work: typed backend decision-ledger evidence derived
  from execution live-readiness closure evidence. The ledger maps each
  required backend decision to an owner, required artifact, missing reason,
  and blocked no-live/no-write proof while staying backend-owned,
  route-bound, command-context-bound, display-only, and BFF forward-only.
- Completed `3061-3080` work: added explicit resolution artifacts, backend contract
  references, evidence references, and disabled resolver/writer flags to each
  blocked backend decision row. This is display evidence only and must not
  resolve decisions or enable live execution.
- Completed `3081-3100` work: added ordered decision-resolution planning steps,
  dependency refs, verification gates, and disabled plan-execution flags to
  each blocked backend decision row. This is planning/display evidence only
  and must not resolve decisions or enable live execution.
- Completed `3101-3120` work: expanded those plan-step/dependency/gate strings
  into structured blocked readiness rows with source, order, missing reason,
  authority, and no-execution evidence.
- Active `3121-3140` work: add backend-derived readiness summaries over those
  blocked readiness rows while preserving no-live, display-only, and
  forward-only authority.
- Out-of-scope files: product catalogs, local order span JSON artifacts, and
  live Coinbase execution unless an approved phase explicitly requires it.
- Interfaces or modules that must not change without tests: dashboard
  WebSocket contract, FastAPI Admin API contracts, stealth lifecycle, BFF
  mutation allowlist, command services, and DB write paths.
- M55 2321-2340 added backend-owned admission context requirements to each
  stealth command-suite admission-readiness row. Static route context is
  present, but exact command-envelope fields (`stealth_order_id`, actor id,
  idempotency key, operator intent, and payload hash) remain missing on the
  read-only command suite. Resolver lookup and proof resolution remain false.
  The batch did not approve, execute, reconcile, read Coinbase, call
  `StealthOrderManager`, cancel/replace active placements, mutate state, grant
  browser/BFF command authority, add a live switch, or create a parallel
  command path.
- M55 2341-2360 added `stealth_admission_context` to concrete
  live-disabled stealth command responses. Command-suite reads still show
  missing exact command-envelope context because they have no request envelope;
  command responses may echo exact route, identity, actor, idempotency,
  operator-intent, and payload-hash context as backend-owned display evidence.
  The echo does not approve, execute, reconcile, read Coinbase, call
  `StealthOrderManager`, cancel/replace active placements, mutate state, grant
  browser/BFF command authority, add a live switch, or create a parallel
  command path.
  The batch completed in backend commit `f441fbe` and frontend commit
  `6122dba`.
- M55 2361-2380 added backend-owned stealth create lifecycle-write guard proof
  records, readback, proof writer, command-suite proof-route linkage, OpenAPI,
  frontend schema/mocks/runtime/read evidence, docs/tests, full gates, and a
  blind/contextless review. The proof evidence remains no-live and no-write:
  it does not approve admission, execute commands, reconcile, read Coinbase,
  submit/cancel Coinbase orders, call `StealthOrderManager`, write
  `stealth_orders` or `order_parent` rows, dispatch lifecycle events, mutate
  stealth/order/exchange state, grant browser authority, or grant BFF
  execution authority. The batch completed in backend commit `ce4a6d6` and
  frontend commit `ae83166`.
- M55 2381-2400 added backend-owned stealth create lifecycle-write execution
  contract evidence to command-suite reads and live-disabled create command
  responses. The evidence reports exact-context presence, missing
  prerequisites, rejected `order_id` and `client_order_id` command identities,
  no-live/no-write proof flags, and blockers, and links the boundary into
  enterprise readiness and mutation taxonomy. Frontend schema, mocks,
  dry-submit evidence, read-model rendering, examples, and handoff docs now
  consume the same evidence as display/readback only. The batch did not
  approve admission, execute commands, resolve proof records as authority,
  reconcile, read Coinbase, submit/cancel Coinbase orders, call
  `StealthOrderManager`, write `stealth_orders` or `order_parent`, dispatch
  lifecycle events, mutate stealth/order/exchange state, grant browser
  authority, or grant BFF execution authority.
- M55 2401-2420 added backend-owned stealth create execution-prerequisite
  resolver evidence as exact-context-bound, read-only, no-live/no-write
  evidence. The resolver can report local prerequisite lookup status and
  matching evidence ids, but it does not approve admission, execute commands,
  reconcile, read Coinbase, submit/cancel Coinbase orders, call
  `StealthOrderManager`, write stealth/order rows, mutate state, grant browser
  authority, or grant BFF execution authority. The batch completed in backend
  commit `4372a40` and frontend commit `7c911c9`.
- M55 2421-2440 added backend-owned non-create stealth command execution
  posture evidence for reveal, cancel, move, recovery, reconciliation, and
  movement/reprice responses. The evidence reports exact command context,
  common admission prerequisites, command-specific missing prerequisites,
  disabled live service/adapter posture, blockers, and no-live/no-write
  flags. It did not invoke `StealthOrderManager`, call `reveal_order_slice`,
  build or execute stealth move plans, clear repricing cooldowns, write
  lifecycle rows, submit/read/cancel Coinbase, replace active placements,
  execute reconciliation, mutate stealth/order/exchange state, approve live
  admission, or grant browser/BFF execution authority. The batch completed in
  backend commit `ea1aff7` and frontend commit `0ab54bf`.
- M55 2441-2460 added resolver-backed active-placement exchange-truth proof
  evidence to non-create stealth command execution responses. The resolver may
  remove only the `active_placement_exchange_truth` missing prerequisite when
  the latest same-`stealth_order_id` proof-store record is safe no-live,
  no-Coinbase, no-cancel/replace, no-reconciliation, no-state-mutation
  evidence. Latest unsafe proof records fail closed as missing/stale. The
  resolver does not verify Coinbase, resolve reveal-trigger evidence,
  mutation-claim snapshots, recovery proof, or reconciliation proof, approve
  admission, execute commands, call `StealthOrderManager`, cancel/replace
  active placements, mutate state, grant browser/BFF authority, or run live
  commands.
- M55 2461-2480 added resolver-backed mutation-claim snapshot proof evidence
  for move and movement/reprice command posture. The resolver may remove only
  the `mutation_claim_snapshot` missing prerequisite when the latest same-
  `stealth_order_id` proof record exactly matches route, method, service
  method, actor, operator intent, idempotency key, and payload hash and is
  safe no-live, no-manager, no-claim-acquire/release, no-Coinbase,
  no-reconciliation, and no-state-mutation evidence. Latest unsafe proof
  records fail closed as missing/stale. The resolver does not acquire or
  release mutation claims, invoke `StealthOrderManager`, build or execute move
  plans, clear repricing cooldowns, cancel/replace active placements,
  submit/read/cancel Coinbase, execute reconciliation, mutate state, grant
  browser/BFF authority, or run live commands. The batch completed in backend
  commit `a3560dc` and frontend commit `0fe6b8d`.
- M55 2481-2500 added backend-owned stealth recovery proof records, readback,
  command-suite proof-route linkage, and exact-context resolver evidence for
  stealth recovery posture. The resolver may remove only the `recovery_proof`
  missing prerequisite when the latest same-`stealth_order_id` proof record
  exactly matches route, method, service method, actor, operator intent,
  idempotency key, and payload hash and is safe no-live, no-manager,
  no-repair/rollback, no-Coinbase, no-reconciliation, and no-state-mutation
  evidence. Latest unsafe proof records fail closed as missing/stale. The
  resolver does not repair state, roll back state, invoke managers, build
  recovery plans, cancel/replace active placements, submit/read/cancel
  Coinbase, execute reconciliation, mutate state, grant browser/BFF
  authority, or run live commands. The batch completed in backend commit
  `d148e66` and frontend commit `1471e8f`.
- M55 2501-2520 added backend-owned stealth reveal-trigger proof records,
  readback, command-suite proof-route linkage, and exact-context resolver
  evidence for stealth reveal posture. The resolver may remove only the
  `reveal_trigger_evidence` missing prerequisite when the latest same-
  `stealth_order_id` proof record exactly matches route, method, service
  method, actor, operator intent, idempotency key, and payload hash and is
  safe no-live, no-trigger-evaluation, no-manager, no-Coinbase,
  no-reconciliation, and no-state-mutation evidence. Latest unsafe proof
  records fail closed as missing/stale. The resolver does not evaluate
  triggers, call `should_trigger_reveal`, call `reveal_order_slice`, invoke
  managers, submit/read/cancel Coinbase, execute reconciliation, mutate state,
  grant browser/BFF authority, or run live commands. The batch completed in
  backend commit `3933d2f` and frontend commit `67c8d5d`.
- M55 2521-2540 added backend-owned stealth reconciliation proof records,
  readback, command-suite proof-route linkage, and exact-context resolver
  evidence for stealth reconciliation posture. The resolver may remove only
  the `reconciliation_proof` missing prerequisite when the latest same-
  `stealth_order_id` proof record exactly matches route, method, service
  method, actor, operator intent, idempotency key, and payload hash and is
  safe no-live, no-manager, no-active-placement-cancel/replace, no-Coinbase,
  no-reconciliation-execution, and no-state-mutation evidence. Latest unsafe
  proof records fail closed as missing/stale. The resolver does not execute
  reconciliation, invoke managers, submit/read/cancel Coinbase,
  cancel/replace active placements, mutate state, grant browser/BFF
  authority, or run live commands. The batch completed in backend commit
  `f6c8c01` and frontend commit `6dfd833`.
- M55 2541-2560 added reconciliation-proof read-evidence parity and
  active-placement cancel/replace proof boundary planning for cancel, move,
  and reprice. It remained no-live/no-write and did not execute
  reconciliation or cancel/replace placements.
- M55 2561-2580 added append-only cancel/replace proof records and readback
  for stealth cancel, stealth move, and movement reprice while keeping
  manager invocation, Coinbase cancel/replace, reconciliation execution, and
  state mutation disabled.
- M55 2581-2600 added exact-context resolver linkage for cancel/replace proof
  records. The resolver may remove only the `cancel_replace_proof` missing
  prerequisite from the latest safe same-order exact-context proof.
- M55 2601-2620 made disabled `live_execution_service`,
  `live_execution_adapter`, `post_write_reconciliation`, and canonical
  execution-path evidence route-specific and contextless for non-create
  stealth command posture.
- M55 2621-2640 brought stealth create lifecycle execution contracts and
  command-suite admission evidence into parity with the same disabled boundary
  fields. The batch completed in backend commit `0209fb6` and frontend commit
  `8bd5a9c`.
- M55 2641-2660 added nested, route-bound
  `post_write_reconciliation_boundary` evidence to stealth create lifecycle
  and non-create execution contracts. The boundary names the backend
  reconciliation-plan route and required missing completion evidence while
  keeping plan writes, reconciliation execution, manager invocation, live
  Coinbase reads/writes/cancels, active-placement cancel/replace, lifecycle
  mutations, order mutations, exchange-state mutations, browser authority, and
  BFF execution authority disabled. Backend regression and frontend
  `release:gate` passed; live Coinbase execution was not run and notional was
  `0` USDC.
- M55 2661-2680 added nested, route-bound `live_execution_adapter_contract`
  evidence to stealth create lifecycle and non-create execution contracts by
  reusing the shared backend `build_live_execution_adapter_contract` helper.
  The evidence names the route, module id, service method,
  `AdminApiCommandService.*` adapter reference, forbidden methods, disabled
  status, `executable=false`, and display/forward-only authority. It did not
  construct executable adapters, invoke managers, call Coinbase,
  cancel/replace active placements, record reconciliation plans, execute
  reconciliation, mutate state, or grant browser/BFF authority. Backend
  regression and frontend `release:gate` passed; live Coinbase execution was
  not run and notional was `0` USDC.

## Active Scope

- Active autonomous range: `3121-3140`.
- Active milestone: M55 - Stealth Full Admin Command Suite.
- Current direction: complete decision-resolution readiness-summary evidence
  for `3121-3140`. Do not run live Coinbase execution unless a future
  approved phase explicitly authorizes it.

## Decisions (Durable)

- [2026-05-16] Decision: Treat cancel/re-entry as policy-cancel/re-entry, not general hide-again behavior.
  - Reason: It cancels no-fill revealed placements and later re-enters through the normal reveal path, but it is not a general operator hide-again feature.
  - Impact: Docs must distinguish cancel/re-entry from the older UI Hide action and from any future standalone hide-again feature.

- [2026-05-16] Decision: Local test DB is `coinbase-dev-postgres` on host `127.0.0.1:9876` mapped to container port `5432`.
  - Reason: Postgres listens on container port `5432`; mapping host `9876` to container `9876` causes connection failures.
  - Impact: Regression DB tests should connect to port `9876` successfully when Docker is healthy.

- [2026-05-16] Decision: `order_parent` identifiers must be UUID text.
  - Reason: Downstream stealth joins use UUID-typed columns; non-UUID test ids can poison reconciliation.
  - Impact: `insert_order_parent` validates IDs before DB lookup/insert, and reconciliation skips legacy polluted non-UUID rows.

- [2026-05-17] Decision: `genai_data/AGENT_ARCHITECT.md` is the primary ownership-boundary document.
  - Reason: Specialist agents need one source of truth for module ownership, dependency rules, test routing, and coding conventions.
  - Impact: Future work should name one primary specialist owner, files in scope/out of scope, coordinating owners, canonical behavior path, and required tests before implementation.

- [2026-05-17] Decision: Public agent contracts live in tracked `docs/agents/` and `.agents/ownership.yaml`; `genai_data/` remains local expanded context.
  - Reason: The public repo needs repeatable ownership boundaries without publishing private model routing, prompts, evals, release gates, or private roadmap details.
  - Impact: Smaller public-facing agents should use the specialist packs plus the ownership manifest; private orchestration can map owner ids to models outside this repo.

- [2026-05-17] Decision: Root historical notes, diagnostics, manual demo tests, experimental UI, runtime output, and UI export JSON are archived or moved out of root.
  - Reason: Smaller agents need a cleaner root and fewer ambiguous files in their operating context.
  - Impact: Historical/public artifacts live under `docs/archive/v2/`; diagnostic/manual scripts live under `tools/diagnostics/`; CI rejects the cleaned root clutter categories.

- [2026-06-10] Decision: Strict USDC spot SELL authority must subtract prior local SELL fills from known BUY lots before authorizing another SELL.
  - Reason: A live SELL canary exposed that counting BUY rows without consuming prior SELL rows can overstate remaining known profitable inventory.
  - Impact: `PositionLotBuilder` reads all product fills, applies opposing-side fills as FIFO exits, and regression covers both inventory-authority and sweep-safety paths.

- [2026-06-10] Decision: Future live SELL stages must regenerate the SELL authority allowlist immediately before live approval and then run `--validate-config` on the rendered sweep config.
  - Reason: Market price drift can invalidate an allowlist within minutes.
  - Impact: Stale allowlists are audit artifacts only. Use the newest strict or average-cost-buffered allowlist sweep config for any approved live SELL execution.

- [2026-06-10] Decision: Generated SELL authority allowlists are executable only while their embedded freshness metadata is fresh.
  - Reason: Account inventory and market prices can change outside the project between allowlist generation and live execution.
  - Impact: `--validate-config` reports `sell_authority_allowlist_freshness`, and live sweep mode rejects stale or invalid allowlist metadata before Coinbase order submission.

- [2026-06-10] Decision: Coinbase average-cost SELL authority must pass a product-specific freshness/drift gate when it is the actual authority source.
  - Reason: Coinbase average cost is portfolio-level operational authority, not exact FIFO lot evidence, and stale records or stale local drift can over-authorize sells.
  - Impact: The shared sweep/campaign gate blocks only planned SELL rows relying on Coinbase average cost when the record is stale, missing, invalid, or stale against local drift.

- [2026-06-10] Decision: Average-cost-buffered SELL allowlists must apply the average-cost authority gate before rendering live-capable allowlist configs.
  - Reason: A generated allowlist that later fails the live sweep gate is not executable authority and can mislead operators.
  - Impact: Campaign allowlist generation now excludes Coinbase-average-cost rows with freshness or drift gate violations, and live sweep validation still rechecks the same condition.

- [2026-06-10] Decision: Missed-fill ownership mapping requires `order_submitted` / `rest_submit` event-stream evidence before resolving exchange `order_id` to `client_order_id`.
  - Reason: Any loose event row containing an exchange order id is weaker evidence than the REST submission event that created the mapping.
  - Impact: Startup reconciliation now filters exchange-order mappings to submission evidence and regression covers the boundary.

- [2026-06-10] Decision: Raw dashboard `place_order` is a manual one-off path, not the scheduled or portfolio automation path.
  - Reason: Direct placement lacks campaign dry-run, allowlist rendering, sweep JSONL ledger, retry, and recovery workflow evidence.
  - Impact: Docs direct automation work to campaign/sweep, while direct placement remains guarded for explicit manual orders.

- [2026-06-10] Decision: Enterprise admin UI lives in a separate private
  frontend repository at `C:\coinbase-frontend` / `s-aws/coinbase-frontend`.
  - Reason: The existing dashboard HTML/WebSocket surfaces are proof-of-concept
    operator tools and should not become the long-term enterprise frontend
    foundation.
  - Impact: The frontend owns browser UI, generated clients, mocks, and
    frontend tests. This backend owns trading behavior, guard checks, Coinbase
    integration, audit persistence, authorization, and the OpenAPI schema.

- [2026-06-10] Decision: The enterprise API must use shared command services
  before enabling FastAPI live-order endpoints.
  - Reason: Adding FastAPI handlers beside `dashboard_server.py` would create a
    parallel live trading path and violate the single-code-path invariant.
  - Impact: API work follows `frontend request -> FastAPI route ->
    auth/RBAC -> idempotency/approval -> shared command service -> existing
    domain/bridge/exchange path -> audit -> response`.

- [2026-06-10] Decision: The Admin API exposes live-disabled FastAPI command
  routes before HTTP live execution is approved.
  - Reason: The frontend needs a generated OpenAPI artifact and typed contract
    before real UI features can be built, but live behavior must not be
    duplicated.
  - Impact: `POST /api/v1/orders` and
    `POST /api/v1/orders/{client_order_id}/cancel` currently return
    `not_implemented`, call only the shared command service, and do
    not call Coinbase.

- [2026-06-10] Decision: Broad all-USDC strict SELL remains blocked unless the
  full eligible USDC universe passes readiness without narrowed allow/deny
  scoping.
  - Reason: The current strict local-fill-ledger authority only supports a
    narrowed allowlist. A narrowed allowlist can pass release gates but is not
    the same as broad all-USDC readiness.
  - Impact: The safe SELL path is a freshly regenerated strict allowlist with
    explicit live approval and small caps. Broad readiness gates should reject
    narrowed configs.

- [2026-06-10] Decision: Raw direct spot orders need stronger operator-visible
  live acknowledgement/cap treatment before public-facing use.
  - Reason: The contextless blind-agent gate correctly identified direct
    dashboard `place_order` as live, uncapped, and easy to misuse for repeatable
    SELL work.
  - Impact: Direct spot `place_order` now requires
    `manual_live_acknowledgement=true`, direct caps stay on the shared
    action-condition guard, and browser smoke verifies the UI contract.

- [2026-06-10] Decision: A narrowed strict SELL allowlist is not broad all-USDC
  readiness, even when it has many products.
  - Reason: Strict authority depends on local profitable-lot coverage and
    current market price. Products can enter or leave the allowlist within
    minutes.
  - Impact: Broad readiness gates reject allow/deny-scoped strict configs.
    Operators must regenerate strict authority immediately before any live
    SELL approval.

- [2026-06-10] Decision: Contextless blind-agent testing is now a persistent
  spot-readiness gate.
  - Reason: Smaller local agents and humans need to understand the safe spot
    order workflow without session history.
  - Impact: Spot changes should keep docs readable from `docs/README.md`,
    `README.spot-trading.md`, `README.spot-portfolio-sweep.md`,
    `README.spot-campaign.md`, and `genai_data/ORDER_ID_HANDLING.md`.

- [2026-06-11] Decision: The durable objective is now the enterprise admin
  frontend/API path for the whole trading engine, with Spot as the first
  complete product module but not the generic model.
  - Reason: The admin platform must be extensible to stealth, movement/
    repricing, futures/perpetuals, guard/risk, audit, and future modules
    without copying spot-specific wallet or cost-basis assumptions.
  - Impact: Roadmap work follows backend-owned contracts, capability
    matrices, release gates, and blind/contextless review logs across both
    `C:\coinbase` and `C:\coinbase-frontend`.

- [2026-06-11] Decision: M6 non-spot command draft contracts and M7 production
  auth/operations hardening are complete for the current admin-platform scope.
  - Reason: Stealth cancel and movement reprice are live-disabled,
    backend-owned command drafts; BFF/auth hardening now rejects missing
    mutation evidence and OIDC/JWT cookie-backed unsafe requests without
    same-origin browser evidence.
  - Impact: M8 controlled live enablement remains pending and still requires
    explicit live approval, caps, audit, and reconciliation evidence.

- [2026-06-12] Decision: M30 route-specific approval snapshot evidence is an
  explicit missing-approval contract, not approval implementation.
  - Reason: Contextless maintainers need to see exactly which durable
    backend-owned approval fields are missing before any live HTTP command can
    be admitted.
  - Impact: `GET /api/v1/admin/live-enablement` exposes blocked
    route-specific approval snapshot requirements. Frontend surfaces may
    render those requirements only as display evidence; no browser approval,
    approval storage, BFF mutation broadening, command route, Coinbase call,
    or reconciliation authority is allowed.

- [2026-06-12] Decision: M31 approval-store contract evidence is an explicit
  missing-store contract, not approval storage.
  - Reason: Contextless maintainers need to see which durable backend store
    behaviors are required before any live HTTP command can be admitted.
  - Impact: `GET /api/v1/admin/live-enablement` exposes blocked per-route
    approval-store requirements. Frontend surfaces may render those
    requirements only as display evidence; no browser approval, approval
    storage, BFF mutation broadening, command route, Coinbase call, or
    reconciliation authority is allowed.

- [2026-06-12] Decision: M32 live-admission audit trail evidence is an
  explicit missing-audit contract, not audit storage.
  - Reason: Contextless maintainers need to see which append-only backend
    audit facts must be written and linked before any live HTTP command can be
    admitted.
  - Impact: `GET /api/v1/admin/live-enablement` exposes blocked per-route
    admission audit facts. Frontend surfaces may render those facts only as
    display evidence; no browser approval, audit storage, approval storage,
    BFF mutation broadening, command route, Coinbase call, or reconciliation
    authority is allowed.

- [2026-06-12] Decision: M33 route-specific cap/guard contract evidence is an
  explicit missing-guard contract, not guard execution.
  - Reason: Contextless maintainers need to see which backend cap, guard,
    payload, approval, admission-audit, product-scope, and browser-boundary
    bindings are missing before any live HTTP command can be admitted.
  - Impact: `GET /api/v1/admin/live-enablement` exposes blocked per-route
    cap/guard requirements. Frontend surfaces may render those requirements
    only as display evidence; no browser guard evaluator, browser wallet or
    profitability authority, approval storage, audit storage, BFF mutation
    broadening, command route, Coinbase call, or reconciliation authority is
    allowed.

- [2026-06-12] Decision: M34 command admission decision evidence is an
  explicit fail-closed admission record on command responses, not live
  admission.
  - Reason: Contextless maintainers need to see the exact route, identity,
    payload hash, idempotency key, operator intent, missing approval, missing
    cap/guard, missing audit, missing reconciliation, and browser-boundary
    blockers before any live HTTP command can be admitted.
  - Impact: Existing live-disabled Admin API command responses expose
    `admission_decision` evidence. Frontend dry-submit surfaces may render the
    evidence only; no live admission endpoint, browser approval, guard
    executor, approval storage, audit storage, BFF mutation broadening,
    command-route broadening, Coinbase call, or reconciliation authority is
    allowed.

- [2026-06-12] Decision: M35 command admission audit persistence uses the
  existing append-only Admin API audit log, not a new audit path.
  - Reason: Live admission needs durable evidence, but adding a parallel
    audit endpoint or browser-writable audit path would violate the single
    behavior path and make future live execution harder to reason about.
  - Impact: Command admission decisions are persisted on
    `AdminApiAuditEvent` and surfaced through Audit Workbench read evidence.
    Live-enablement may count the command-admission-decision audit fact as
    passed while approval, cap/guard, exchange submission, and reconciliation
    facts remain blocked.

- [2026-06-12] Decision: M36 durable approval-store foundation adds backend
  append-only approval storage without adding approval mutation or live
  admission.
  - Reason: Future live HTTP admission needs a durable backend-owned store,
    but exposing browser approval or a mutation before cap/guard and
    reconciliation are wired would create unsafe partial authority.
  - Impact: Approval-store contract evidence may report configured backend
    infrastructure. Route-specific approval snapshots remain absent, HTTP
    commands remain live-disabled, and command admission remains blocked by
    approval snapshot, admission audit, cap/guard, reconciliation, live
    disabled, and browser-rejection blockers.

- [2026-06-12] Decision: M37 approval snapshot resolver foundation is
  backend-only infrastructure, not live approval.
  - Reason: Future live HTTP admission needs a deterministic way to derive
    immutable route-bound approval snapshot evidence from an exact unexpired
    approval-store record, but exposing that resolver as an endpoint or
    browser authority before cap/guard, admission audit, and reconciliation
    are wired would create unsafe partial authority.
  - Impact: Approval snapshot resolver code may match route, method, module,
    identity, action class, permission, requesting actor, operator intent,
    idempotency key, and payload hash. It must not approve commands, write
    audit records, evaluate caps/guards, reconcile, call Coinbase, or remove
    command admission blockers by itself. Existing approval-store JSONL rows
    without `requested_by_actor_id` fail closed and are ignored by resolver
    lookup.

- [2026-06-12] Decision: M38 resolver-backed command admission evidence is
  evidence only until all live gates are wired.
  - Reason: A matching approval snapshot is necessary for future live HTTP
    admission but is not sufficient without admission audit, cap/guard,
    reconciliation, live enablement, and browser-authority rejection evidence.
  - Impact: Existing Admin API command responses may report snapshot-present
    metadata and remove `approval_snapshot_missing`, but they must still
    return no-live responses while any other blocker remains. Frontend code may
    display the backend evidence but must not resolve approvals or treat it as
    command authority.

- [2026-06-12] Decision: M39 resolver-backed command admission audit evidence
  is evidence only until all live gates are wired.
  - Reason: A matching append-only audit proof is necessary for future live
    HTTP admission but is not sufficient without cap/guard, reconciliation,
    live enablement, and browser-authority rejection evidence.
  - Impact: Existing Admin API command responses may report audit-present
    metadata and remove `admission_audit_missing`, but they must still return
    no-live responses while any other blocker remains. Frontend code may
    display the backend evidence but must not resolve audit proof, mutate
    audit history, or treat it as command authority.

## Open Risks

- Risk: Broad all-USDC SELL execution still has many wallet-only or insufficient-known-profitable rows.
  - Severity: High
  - Mitigation: Do not run broad SELL as-is. Use regenerated allowlists and explicit live approval only.
  - Owner: Strategy / Architect coordination.

- Risk: Imported baseline inventory can overstate remaining SELL authority if the operator does not refresh source state.
  - Severity: Medium
  - Mitigation: `inventory_baseline_freshness_audit` reports stale, missing, or invalid source freshness metadata. Prefer explicit `source_updated_at` and refresh before live SELL use.
  - Owner: Strategy / Operator.

- Risk: Direct dashboard placement is easy for a contextless reader to mistake for the normal automation path.
  - Severity: Medium
  - Mitigation: Keep direct placement documented as manual one-off only, add
    read-only audit visibility by `client_order_id`, require manual live
    acknowledgement for direct spot placement, keep caps in shared guards, and
    continue blind-agent testing.
  - Owner: Dashboard / Strategy coordination.

- Risk: Broad all-USDC SELL remains unsafe if narrowed allowlists are treated as
  full-universe readiness.
  - Severity: High
  - Mitigation: Preserve broad readiness rejection for allow/deny-scoped
    configs and regenerate strict SELL allowlists immediately before any capped
    live SELL approval.
  - Owner: Strategy / Architect coordination.

## Validation Status

- Last backend focused Admin API/readiness run: 2026-06-16
  `python -m pytest tests\regression\test_admin_api_contract.py::test_admin_api_stealth_post_write_reconciliation_verification_is_no_live_and_path_keyed tests\regression\test_admin_api_contract.py::test_admin_api_stealth_post_write_reconciliation_verification_readback_requires_exact_chain tests\regression\test_admin_api_contract.py::test_admin_api_stealth_post_write_reconciliation_verification_rejects_unsafe_and_duplicate_records tests\regression\test_admin_api_contract.py::test_admin_api_openapi_schema_file_matches_generated_contract tests\regression\test_admin_api_contract.py::test_admin_api_route_inventory_and_openapi_paths_stay_in_sync -v --tb=short`
- Result: Passed, 5 selected tests, 1 warning.
- Last backend autonomous queue check: 2026-06-16
  `python tools\run_autonomous_work_queue_check.py --summary-only`
- Result: M55 range `3001-3020` passed. Live Coinbase
  execution `not_run`, submitted/executed notional `0` USDC.
- Last backend full regression: 2026-06-16
  `python -m pytest tests\regression\ -v --tb=short`
- Result: Passed, 853 tests, 1 warning.
- Last frontend focused run: 2026-06-16
  `npm run api:check`, `npm run api:routes:check`,
  `npm run autonomous:check`, and
  `npm run test -- backendApiClient.test.ts mockBackend.test.ts backendRuntime.test.ts mutationContracts.test.ts commandDrySubmit.test.ts StealthOrdersReadModel.test.tsx adminBffProxy.test.ts adminBffRoute.test.ts`.
- Result: Passed focused M55 verification frontend checks with 132 tests.
  Full frontend `npm run release:gate` passed with 251 unit tests and 3
  Playwright tests.
- Last blind/contextless M55 review: 2026-06-16
- Result: 3021-3040 backend and frontend execution live-readiness closure
  reviews passed after stale-doc remediation. Spot-order orientation review
  passed and confirmed current manual Spot order creation remains backend
  live-disabled.
- Live Coinbase execution for M55: not run. Submitted notional `0` USDC.
  Executed notional `0` USDC.

## Next 3 Actions

1. After restart, create the next milestone-linked M55 active range only if a
   concrete approved gap remains.
2. Keep contextless blind review in the release loop for new spot order,
   campaign, live-action, approval-snapshot, approval-store, admission-audit,
   or cap/guard behavior.
3. Preserve the no-live default and report Coinbase submitted/executed
   notional for any future live-approved phase.

## Handoff Notes

- What is done through M55 2361-2380: backend and frontend expose
  backend-owned admission-readiness rows plus command-envelope context
  requirements on command-suite reads and exact command-response context echo
  on live-disabled stealth command responses, plus lifecycle-write guard proof
  records/readback/writer evidence for stealth create. These rows and proof
  records remain blocked/no-live and do not approve, execute, reconcile, read
  Coinbase, submit/cancel Coinbase orders, call `StealthOrderManager`, write
  stealth/order rows, mutate state, grant browser authority, or grant BFF
  execution authority.
- Admin API/frontend status: backend Admin API mutating routes remain
  auth/RBAC-gated, idempotent, audited, and HTTP-live-disabled. Frontend
  renders approval snapshot, approval-store, admission-audit, cap/guard,
  reconciliation proof, live execution service boundary, command admission
  decision, admission audit proof, and stealth command-suite evidence as
  display evidence only. No command controls, guard evaluator, audit storage,
  approval storage, reconciliation execution, BFF mutation broadening,
  Coinbase call, browser approval, or reconciliation behavior is allowed.
- What is done through M55 2401-2420: backend and frontend expose stealth
  create execution-prerequisite resolver evidence as exact-context-bound,
  read-only, no-live/no-write evidence. The resolver can report local
  prerequisite lookup status and matching evidence ids, but it does not
  approve admission, execute commands, reconcile, read Coinbase, submit/cancel
  Coinbase orders, call `StealthOrderManager`, write stealth/order rows,
  mutate state, grant browser authority, or grant BFF execution authority.
- What is done through M55 2441-2460: backend and frontend expose
  resolver-backed active-placement exchange-truth proof evidence on
  non-create stealth command responses. It resolves only from the latest safe
  same-`stealth_order_id` backend proof-store row, fails closed on latest
  unsafe proof rows, and remains local readback evidence only. It does not
  invoke manager methods, cancel/replace active placements, call Coinbase,
  execute reconciliation, mutate state, or grant browser/BFF execution
  authority.
- What is done through M55 2461-2480: backend and frontend expose
  resolver-backed mutation-claim snapshot proof evidence on move and
  movement/reprice command responses. It resolves only from the latest safe
  exact-context same-`stealth_order_id` backend proof-store row, fails closed
  on latest unsafe proof rows, and remains local readback evidence only. It
  does not acquire/release claims, invoke manager methods, cancel/replace
  active placements, call Coinbase, execute reconciliation, mutate state, or
  grant browser/BFF execution authority.
- What is done through M55 2481-2500: backend and frontend expose
  resolver-backed recovery proof evidence on stealth recovery command
  responses. It resolves only from the latest safe exact-context same-
  `stealth_order_id` backend proof-store row, fails closed on latest unsafe
  proof rows, and remains local readback evidence only. It does not repair
  state, roll back state, invoke managers, build recovery plans,
  cancel/replace active placements, call Coinbase, execute reconciliation,
  mutate state, or grant browser/BFF execution authority.
- What is done through M55 2501-2520: backend and frontend expose
  resolver-backed reveal-trigger proof evidence on stealth reveal command
  responses. It resolves only from the latest safe exact-context same-
  `stealth_order_id` backend proof-store row, fails closed on latest unsafe
  proof rows, and remains local readback evidence only. It does not evaluate
  triggers, call `should_trigger_reveal`, call `reveal_order_slice`, invoke
  managers, call Coinbase, execute reconciliation, mutate state, or grant
  browser/BFF execution authority.
- What is done through M55 2521-2540: backend and frontend expose
  resolver-backed reconciliation proof evidence on stealth reconciliation
  command responses. It resolves only from the latest safe exact-context same-
  `stealth_order_id` backend proof-store row, fails closed on latest unsafe
  proof rows, and remains local readback evidence only. It does not execute
  reconciliation, build reconciliation plans, invoke managers, call Coinbase,
  cancel/replace active placements, mutate state, or grant browser/BFF
  authority.
- What is done through M55 2621-2640: backend and frontend expose create
  lifecycle execution boundary parity with the non-create disabled
  live-service, live-adapter, post-write reconciliation route, canonical path,
  and boundary-authority evidence.
- What is done through M55 2641-2660: backend and frontend expose nested
  `post_write_reconciliation_boundary` evidence to create and non-create
  stealth execution contracts. This remains local/readiness evidence only; it
  must not record plans, call Coinbase, cancel/replace active placements,
  invoke managers, execute reconciliation, mutate state, or grant browser/BFF
  authority.
- What is done through M55 2661-2680: backend and frontend expose nested
  `live_execution_adapter_contract` evidence to create and non-create stealth
  execution contracts. This names the shared backend command-service adapter
  reference and forbidden methods, but it must not construct executable
  adapters, call Coinbase, invoke managers, cancel/replace active placements,
  execute reconciliation, record plans, mutate state, or grant browser/BFF
  authority.
- What is done through M55 2681-2700: backend and frontend expose nested
  `live_execution_service_contract` evidence to create and non-create stealth
  execution contracts. This projects the disabled backend live execution
  service state and must not enable live execution, construct adapters, call
  Coinbase, invoke managers, cancel/replace active placements, execute
  reconciliation, record plans, mutate state, or grant browser/BFF authority.
- What is done through M55 2701-2720: backend and frontend expose nested
  `live_execution_intent_contract` evidence to exact stealth command
  responses by reusing `admission_decision.live_execution_intent`.
  Command-suite reads do not fabricate payload-bound intent; create lifecycle
  command-suite evidence keeps the field null. The batch did not enable live
  execution, construct adapters, call Coinbase, invoke managers, execute
  reconciliation, record plans, mutate state, or grant browser/BFF authority.
- What is done through M55 2721-2740: backend and frontend expose nested
  `active_placement_cancel_replace_contract` evidence to exact stealth cancel,
  stealth move, and movement/reprice command responses by reusing the same
  backend-owned cancel/replace boundary contract used by command-suite reads.
  The evidence remains blocked, display-only, no-manager, no-Coinbase,
  no-reconciliation-execution, no-state-mutation, and no browser/BFF execution
  authority. Create, reveal, recovery, and reconciliation do not fabricate the
  nested cancel/replace boundary.
- What is done through M55 2741-2760: backend and frontend expose nested
  `active_placement_exchange_truth_contract` evidence to exact stealth cancel,
  stealth move, recovery, reconciliation, and movement/reprice command
  responses by reusing the same backend-owned exchange-truth boundary contract
  used by command-suite reads. The evidence must remain blocked,
  display-only, no-Coinbase-read, no-manager, no-reconciliation-execution,
  no-state-mutation, and no browser/BFF execution authority. Create and
  reveal must not fabricate the nested active-placement exchange-truth
  boundary.
- What is done through M55 2781-2800: backend and frontend expose ordered
  `execution_readiness_stages` evidence to exact non-create stealth command
  responses by reusing the existing prerequisite resolver output. The evidence
  remains blocked, display-only, no-proof-write, no-Coinbase-read,
  no-manager, no-reconciliation-execution, no-state-mutation, and no
  browser/BFF execution authority.
- What is done through M55 2801-2820: backend and frontend expose the same
  ordered readiness-stage pattern for stealth create lifecycle-write
  execution contracts by deriving rows from the create prerequisite resolver.
  The evidence remains display-only, no-proof-write, no-Coinbase-read or
  submit, no-manager, no stealth/order row write, no lifecycle dispatch,
  no-reconciliation-execution, no-state-mutation, and no browser/BFF
  execution authority.
- What is done through M55 2821-2840: backend and frontend expose durable
  post-write reconciliation proof evidence and readback for guarded stealth
  command families. The evidence may persist reviewed route-bound plan,
  post-write journal, and completion references, but it must not satisfy
  execution prerequisites, call Coinbase, invoke managers, execute
  reconciliation, cancel/replace active placements, mutate state, or grant
  browser/BFF authority.
- What is done through M55 2841-2860: backend and frontend make create and
  non-create execution prerequisite resolvers aware of exact-context
  post-write proof records while keeping `post_write_reconciliation`
  unresolved with `post_write_reconciliation_proof_not_sufficient`. The
  evidence remains backend-store read-only and cannot accept execution
  journals, verify reconciliation, execute Coinbase actions, invoke managers,
  mutate state, or grant browser/BFF authority.
- What is completed for M55 2861-2880: backend and frontend added explicit
  post-write completion verifier evidence that reports proof id/safety,
  accepted execution-journal requirements, missing verified reconciliation,
  no-run flags, and display-only/forward-only authority while keeping
  execution prerequisites unresolved.
- What is completed for M55 2881-2900: backend and frontend added
  backend-owned execution-journal acceptance read/write evidence and display a
  safe matching acceptance as evidence only while verified reconciliation and
  execution prerequisites remain unresolved.
- What is completed for M55 2901-2920: backend and frontend added
  backend-owned post-write reconciliation verification read/write evidence.
  Verification readback counts only exact safe proof plus accepted journal plus
  verification chains; mismatched persisted records stay visible but are not
  displayed or counted as verified. A matching verification remains evidence
  only: it may satisfy the completion verifier display field while the
  `post_write_reconciliation` execution prerequisite remains unresolved. It
  does not execute reconciliation, invoke managers, call Coinbase,
  cancel/replace active placements, mutate state, or grant browser/BFF
  authority.
- What is completed for M55 2921-2940: backend resolver completion for the
  exact proof, journal, and verification chain. The chain may resolve only
  `post_write_reconciliation`; all live and state-mutating execution gates
  remain blocked.
- What is completed for M55 2941-2960: backend and frontend expose typed
  remaining execution blocker-chain evidence so resolved post-write evidence
  still leaves live service, live adapter, manager invocation, Coinbase,
  cancel/replace, reconciliation execution, and state-mutation blockers
  visible.
- What is completed for M55 2961-2980: backend and frontend expose typed
  execution-candidate evidence that names the future backend path while
  remaining blocked, no-live, backend-owned, display-only, and bound to the
  unresolved blocker chain.
- What is completed for M55 2981-3000: backend and frontend expose typed
  candidate-bound pre-execution preflight evidence derived from the existing
  execution candidate and unresolved blocker chain. The preflight remains
  blocked, no-live, backend-owned, display-only, and BFF forward-only.
- What is completed for M55 3001-3020: backend and frontend expose typed
  execution-transition barrier evidence derived from `execution_preflight`.
  The barrier remains blocked, no-live, backend-owned, display-only, and BFF
  forward-only.
- What is completed for M55 3021-3040: backend and frontend expose typed
  execution live-readiness closure evidence derived from
  `execution_transition_barrier`. The closure keeps the M55 completion claim
  false, lists required backend decisions, handoff blockers, and forbidden
  execution claims, and remains blocked, no-live, backend-owned, display-only,
  and BFF forward-only.
- What is completed for M55 3041-3060: backend and frontend expose typed backend
  decision-ledger rows derived from execution live-readiness evidence. Each
  row names the required backend decision, owner, artifact, missing reason,
  and blocked no-live/no-write proof while keeping browser and BFF authority
  display-only/forward-only.
- What is completed for M55 3061-3080: backend and frontend expose blocked
  decision-resolution criteria for those decision rows, including resolution
  artifacts, backend contract refs, evidence refs, and disabled resolver/writer
  flags.
- What is completed for M55 3081-3100: backend and frontend expose ordered
  decision-resolution sequencing for each blocked decision row, including
  required plan steps, missing plan steps, dependency refs, verification gates,
  and disabled plan-execution flags.
- What is completed for M55 3101-3120: backend and frontend expose structured
  decision-resolution readiness rows for plan steps, dependencies, and
  verification gates while keeping every item blocked, unresolved, no-live,
  display-only, and forward-only.
- What is active for M55 3121-3140: backend and frontend expose
  backend-derived decision-resolution readiness summaries over those rows while
  keeping summaries blocked, no-live, display-only, and forward-only.
- What is blocked: Nothing currently known.
- Exact next command: continue the active 3121-3140 implementation, run
  focused gates, blind/contextless reviews, full gates, browser availability,
  then commit and push both repositories with `$0` live Coinbase execution.
