# Agent State

Use this file as the single durable source of truth for active engineering work.
Keep it short. Keep it factual.

## Metadata

- Last updated (ET): 2026-06-14
- Updated by: Codex
- Branch: main
- Commit (optional):

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

- Latest completed autonomous range: `2181-2200`.
- Latest completed milestone: M54 - Stealth Create Lifecycle Audit Evidence.
- Completed files: Admin API stealth create lifecycle-write audit evidence,
  OpenAPI, command-suite docs, frontend generated schema, mock/runtime
  evidence, Stealth Orders read-model rendering, frontend docs/tests, full
  backend regression, frontend release gate, and contextless review.
- Out-of-scope files: product catalogs, local order span JSON artifacts, and
  live Coinbase execution unless an approved phase explicitly requires it.
- Interfaces or modules that must not change without tests: dashboard
  WebSocket contract, FastAPI Admin API contracts, stealth lifecycle, BFF
  mutation allowlist, command services, and DB write paths.
- M54 made stealth create lifecycle-write audit evidence visible on
  `GET /api/v1/stealth/command-suite` and in the frontend read model. It did
  not invoke `StealthOrderManager`, write stealth/order_parent/lifecycle
  state, call Coinbase, execute reconciliation, create proof records, grant
  browser/BFF authority, add a live switch, or create a parallel command path.

## Active Scope

- Active autonomous range: `2241-2260`.
- Active milestone: M55 - Exchange-Truth Evidence-Route Linkage.
- Current direction: link stealth command-suite `exchange_truth_checks` to
  backend-owned typed `current_read_evidence` route metadata and consume it in
  the frontend as display-only evidence. Do not claim Coinbase reads ran,
  prove active-placement exchange truth, cancel/replace placements, reveal
  orders, create proof records, mutate approval/admission-audit/cap-guard/
  reconciliation stores, invoke `StealthOrderManager`, write
  stealth/order_parent/lifecycle state, mutate exchange state, call Coinbase,
  execute reconciliation, add browser proof authority, add BFF execution
  authority, or enable live commands.

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

- Last backend focused Admin API/readiness run: 2026-06-14
  `python -m pytest tests\regression\test_admin_api_contract.py::test_admin_api_openapi_schema_file_matches_generated_contract tests\regression\test_admin_api_contract.py::test_admin_api_stealth_command_suite_is_read_only_backend_evidence tests\regression\test_spot_readiness_gate.py::test_autonomous_work_queue_check_covers_approved_20_phase_batch -q --tb=short --basetemp=runtime_state\pytest_tmp`
- Result: Passed for M55 focused checks, 3 tests, 1 warning.
- Last backend autonomous queue check: 2026-06-14
  `python tools\run_autonomous_work_queue_check.py --summary-only`
- Result: M55 completed range `2201-2220` passed. Live Coinbase execution
  `not_run`, submitted/executed notional `0` USDC.
- Last backend full regression: 2026-06-14
  `python -m pytest tests\regression\ -v --tb=short --basetemp=runtime_state\pytest_tmp`
- Result: Passed, 828 tests, 1 warning.
- Last frontend focused run: 2026-06-14
  `npm run typecheck`, `npm run api:check`, `npm run autonomous:check`,
  `npm run security:commands`, `npm run lint`, and focused Vitest.
- Result: Passed focused M55 frontend checks after updating brittle exact-count
  assertions for the new proof-route rows. Full frontend release gate passed
  with 215 unit tests and 3 Playwright tests.
- Last blind/contextless M55 review: 2026-06-14
- Result: Passed with no blockers. Reviewer confirmed backend proof-route
  linkage is read-only, frontend rendering is display-only, no manager/
  lifecycle/Coinbase/reconciliation/proof-store authority was added, and
  generated/mock/UI docs align with the durable no-live objective.
- Live Coinbase execution for M55: not run. Submitted notional `0` USDC.
  Executed notional `0` USDC.

## Next 3 Actions

1. Complete synchronized M55 exchange-truth evidence-route linkage for active
   range `2241-2260`, then rerun focused backend/frontend checks,
   blind/contextless review, full backend regression, and frontend release
   gate.
2. Preserve stealth create proof-route linkage and coverage-gap read-evidence
   linkage as read-only evidence without proof creation, store mutation,
   manager invocation, lifecycle writes, Coinbase calls, reconciliation
   execution, browser authority, BFF execution authority, or unapproved live
   execution.
3. Keep contextless blind-review in the release loop for new spot order,
   campaign, live-action, approval-snapshot, approval-store, admission-audit,
   or cap/guard behavior.

## Handoff Notes

- What is done through M54: backend and frontend expose live-disabled stealth
  create lifecycle-write audit evidence as read-only command-suite evidence.
  The evidence names the existing command route, shared service method,
  manager method, identity discipline, no-write/no-live posture, and missing
  lifecycle contracts without creating a second lifecycle path.
- Admin API/frontend status: backend Admin API mutating routes remain
  auth/RBAC-gated, idempotent, audited, and HTTP-live-disabled. Frontend
  renders approval snapshot, approval-store, admission-audit, cap/guard,
  reconciliation proof, live execution service boundary, command admission
  decision, admission audit proof, and stealth command-suite evidence as
  display evidence only. No command controls, guard evaluator, audit storage,
  approval storage, reconciliation execution, BFF mutation broadening,
  Coinbase call, browser approval, or reconciliation behavior is allowed.
- What is in progress: M55 exchange-truth evidence-route linkage for active
  approved range `2241-2260`.
- What is blocked: Nothing currently known.
- Exact next command: run focused backend/frontend checks for the 2241-2260
  exchange-truth evidence-route linkage, resolve drift, run blind/contextless review, then
  full gates before commit/push.
