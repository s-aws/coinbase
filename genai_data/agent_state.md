# Agent State

Use this file as the single durable source of truth for active engineering work.
Keep it short. Keep it factual.

## Metadata

- Last updated (ET): 2026-06-25
- Updated by: Codex
- Branch: codex/stealth-live-service-decision-3501
- Commit (optional): current active range is `7001-7020`.

## Current Objective

- One-sentence objective: Build the enterprise admin frontend/API path for
  the entire Coinbase trading engine, with Spot as the first complete product
  module but not the generic model.

- Durable objective detail: Every new admin module must use backend-owned
  contracts, preserve the single trading behavior path, avoid importing
  spot-only rules into non-spot domains, and remain understandable to
  contextless/blind agents through docs, capability matrices, tests, and
  review logs.

## Current Phase Override

- Latest completed autonomous range before current work: `6981-7000`.
- Active autonomous range: `7001-7020`.
- Current direction: complete phases `7001-7020` with futures request payload validation record execution-eligibility semantic closure evidence.
- Exact active evidence phrase: futures request payload validation record execution-eligibility semantic closure evidence.
- Active `7001-7020` adds backend-owned disabled semantic closure fields to futures request payload validation record execution-eligibility and blocker rows through `application/admin_api/futures_request_payload_validation_record_execution_eligibilities.py`, `application/admin_api/futures_request_payload_validation_record_execution_eligibility_blockers.py`, Admin API models/read-service serialization, OpenAPI, generated frontend schema, frontend adapter/display, and bounded mock fixtures.
- Execution-eligibility rows expose ten `validation_record_*_semantics_contract_ref` fields, `validation_record_semantic_contract_refs`, `validation_record_semantic_contract_ref_count`, `validation_record_semantic_contracts_present=true`, and `validation_record_semantic_contracts_ready=false`.
- Blocker rows expose `semantic_contract_ref`, `semantic_contract_present=true`, and `semantic_contract_ready=false` while preserving existing `required_backend_artifact_ref` values for downstream semantic-artifact evidence.
- Every readiness, execution, live Coinbase, browser, BFF, and spot-rule authority flag remains false or display-only. Semantic contract presence is not runtime acceptance, command admission, reconciliation execution, Coinbase execution, or futures/order/exchange mutation authority. Lowercase durability token: semantic contract presence is not runtime acceptance. Active M57 `7001-7020` evidence adds futures request payload validation record execution-eligibility semantic closure evidence while completed M57 `6981-7000` carries forward disabled futures request payload validation record reconciliation semantics.
- Completed `6981-7000` carries forward disabled futures request payload validation record reconciliation semantics through `application/admin_api/futures_request_payload_validation_record_reconciliation_semantics.py`, `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_RECONCILIATION_SEMANTIC_CONTRACTS`, and `iter_futures_request_payload_validation_record_reconciliation_semantics`.
## Hard Constraints

- Use `client_order_id` for internal tracking.
- Use `order_id` only for exchange-facing operations that require it; the
  project Coinbase wrapper `cancel_order(client_order_id)` is the cancellation
  exception because Coinbase accepts the client id there.
- Single code path per behavior.
- Use enums from `core/enums.py`.
- Respect locks and thread-safety invariants.
- Ordinary phase work must run focused tests and validators that cover the
  changed behavior.
- Full regression is reserved for durable milestone closeout,
  public/release-candidate handoff, deployment approval/closeout,
  release-hardening closeout, Admin API/backend association closeout, or
  explicit user request. Canonical command:
  `python tools/run_parallel_regression.py --workers 4`.
- Use `pytest tests/regression/ -v --tb=short` only as an intentional
  sequential fallback when `pytest-xdist` is unavailable.
- If only agent-instruction/context files changed (`AGENTS.md`, `agent.md`,
  `ai-context.md`, `docs/agents/*.md`, `genai_data/AGENT_*.md`,
  `genai_data/agent_state.md`), regression tests may be skipped.
- At phase end, close subagents spawned for that phase and any stale or
  previously unused subagents from earlier phases or milestones found during
  the sweep after their findings have been consumed, remediated, or explicitly
  deferred. At durable milestone closeout, perform a final stale-subagent sweep;
  this is an audit sweep, not the first cleanup point. Do not close a subagent
  that is still running required validation, producing required evidence, or
  awaiting a user decision. Any intentionally open handoff agent must have
  recorded owner, purpose, and expected next action. Record the phase-end or
  milestone-closeout sweep result in the phase evidence, handoff, or closeout
  summary before advancing.

## Latest Completed Scope

- Latest completed autonomous range before current work: `6981-7000`.
- Completed `6961-6980` added disabled futures request payload validation
  record cancel semantics through
  `application/admin_api/futures_request_payload_validation_record_cancel_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_CANCEL_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_cancel_semantics`.
- Completed `6941-6960` added disabled futures request payload validation
  record order semantics through
  `application/admin_api/futures_request_payload_validation_record_order_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_ORDER_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_order_semantics`.
- Completed `6921-6940` added disabled futures request payload validation
  record funding semantics through
  `application/admin_api/futures_request_payload_validation_record_funding_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_FUNDING_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_funding_semantics`.
- Completed `6901-6920` added disabled futures request payload validation
  record close-only semantics through
  `application/admin_api/futures_request_payload_validation_record_close_only_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_CLOSE_ONLY_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_close_only_semantics`.
- Completed `6881-6900` added disabled futures request payload validation
  record reduce-only semantics through
  `application/admin_api/futures_request_payload_validation_record_reduce_only_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REDUCE_ONLY_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_reduce_only_semantics`.
- Completed `6861-6880` added disabled futures request payload validation
  record liquidation semantics through
  `application/admin_api/futures_request_payload_validation_record_liquidation_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_LIQUIDATION_SEMANTIC_CONTRACTS`,
  and
  `iter_futures_request_payload_validation_record_liquidation_semantics`.
  It exposed
  `request_payload_validation_record_liquidation_semantic_count`,
  `blocking_request_payload_validation_record_liquidation_semantic_count`,
  `ready_request_payload_validation_record_liquidation_semantic_count`,
  `runtime_observed_request_payload_validation_record_liquidation_semantic_count`,
  `request_payload_validation_record_liquidation_semantics`,
  `liquidation_semantics_ref`, `liquidation_semantics_contract_ref`,
  `liquidation_semantics_contract_available`,
  `liquidation_semantics_contract_ready`, `liquidation_buffer_bound`,
  `liquidation_price_bound`, `liquidation_distance_bound`,
  `liquidation_threshold_bound`,
  `runtime_liquidation_evidence_observed`,
  `runtime_evidence_satisfies_liquidation_semantics`, and
  `validation_record_liquidation_semantics_ready` as disabled evidence.
- Completed `6841-6860` added disabled futures request payload validation
  record collateral semantics through
  `application/admin_api/futures_request_payload_validation_record_collateral_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_COLLATERAL_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_collateral_semantics`.
- Completed `6821-6840` added disabled futures request payload validation
  record margin semantics through
  `application/admin_api/futures_request_payload_validation_record_margin_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_MARGIN_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_margin_semantics`.
- Completed `6801-6820` added disabled futures request payload validation
  record position semantics through
  `application/admin_api/futures_request_payload_validation_record_position_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_POSITION_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_position_semantics`.
- Completed `6781-6800` added disabled futures request payload validation
  record semantic artifact runtime evidence acceptance through
  `application/admin_api/futures_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS`,
  and
  `iter_futures_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances`.
- Completed `6761-6780` added disabled futures request payload validation
  record semantic artifact runtime evidence binding through
  `application/admin_api/futures_request_payload_validation_record_semantic_artifact_runtime_evidences.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_CONTRACTS`,
  and
  `iter_futures_request_payload_validation_record_semantic_artifact_runtime_evidences`.
- Earlier completed ranges remain historical carried-forward evidence:
  `6741-6760` semantic artifact definition review output acceptance,
  `6721-6740` semantic artifact definition review output, `6701-6720`
  semantic artifact definition review input, `6681-6700` semantic artifact
  definition review, and `6661-6680` semantic artifact definition.

## Active Scope

- Active autonomous range: `7001-7020`.
- Approved milestone: M57 - Futures/Perpetuals Contract Foundation And Commands.
- Current direction: complete phases `7001-7020` with backend-owned futures request payload validation record execution-eligibility semantic closure evidence and matching frontend display.
- Active evidence phrase: futures request payload validation record execution-eligibility semantic closure evidence.
- Active display phrase: futures request payload validation record execution-eligibility semantic closure display.
- Boundary: no validators, no runtime acceptance, no command admission, no Coinbase execution, no reconciliation execution, no futures/order/exchange mutation, no browser/BFF execution authority, and no spot-rule authority.
## Decisions (Durable)

- [2026-06-21] Decision: Subagent cleanup is a phase-end hygiene gate with a
  final durable milestone sweep.
  - Reason: Completed, failed, superseded, or unused subagents create stale
    context and can confuse later contextless agents.
  - Impact: Each phase must close phase-spawned subagents and stale/unused
    subagents after their findings are consumed, remediated, or explicitly
    deferred. Milestone closeout must run a final sweep. Agents still running
    required validation, producing required evidence, or awaiting a user
    decision stay open.

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


## Active M57 Machine-Check Evidence Terms

Current direction: complete phases `7001-7020` with futures request payload validation record execution-eligibility semantic closure evidence.

Active evidence phrases: futures request payload validation record execution-eligibility semantic closure evidence; futures request payload validation record execution-eligibility semantic closure display.

Current backend symbols: application/admin_api/futures_request_payload_validation_record_execution_eligibilities.py; application/admin_api/futures_request_payload_validation_record_execution_eligibility_blockers.py; validation_record_position_semantics_contract_ref; validation_record_margin_semantics_contract_ref; validation_record_collateral_semantics_contract_ref; validation_record_liquidation_semantics_contract_ref; validation_record_reduce_only_semantics_contract_ref; validation_record_close_only_semantics_contract_ref; validation_record_funding_semantics_contract_ref; validation_record_order_semantics_contract_ref; validation_record_cancel_semantics_contract_ref; validation_record_reconciliation_semantics_contract_ref; validation_record_semantic_contract_refs; validation_record_semantic_contract_ref_count; validation_record_semantic_contracts_present; validation_record_semantic_contracts_ready; semantic_contract_ref; semantic_contract_present; semantic_contract_ready.

Carried-forward evidence phrases: futures request payload contract registry evidence; futures request payload validation gate evidence; futures request payload validator contract registry evidence; futures request payload validator input-schema evidence; futures request payload validator output-schema evidence; futures request payload validator registration evidence; futures request payload validation evidence; futures request payload validation evidence record contract evidence; futures request payload validation record schema evidence; futures request payload validation record replay guard evidence; futures request payload validation record audit-link evidence; futures request payload validation record admission-link evidence; futures request payload validation record execution-eligibility blocker evidence; futures request payload validation record semantic artifact evidence; futures request payload validation record semantic artifact definition evidence; futures request payload validation record semantic artifact definition review evidence; futures request payload validation record semantic artifact definition review input evidence; futures request payload validation record semantic artifact definition review output evidence; futures request payload validation record semantic artifact definition review output acceptance evidence; futures request payload validation record semantic artifact runtime evidence binding; futures request payload validation record semantic artifact runtime evidence acceptance; futures request payload validation record position semantics; futures request payload validation record margin semantics; futures request payload validation record collateral semantics; futures request payload validation record liquidation semantics; futures request payload validation record reduce-only semantics; futures request payload validation record close-only semantics; futures request payload validation record funding semantics; futures request payload validation record order semantics; futures request payload validation record cancel semantics; futures request payload validation record reconciliation semantics.
## Validation Status

- Current `7001-7020` validation: passed ordinary phase closeout for
  execution-eligibility semantic closure evidence. Backend commands run:
  `python -m py_compile application\admin_api\models.py application\admin_api\read_service.py application\admin_api\futures_request_payload_validation_record_execution_eligibilities.py application\admin_api\futures_request_payload_validation_record_execution_eligibility_blockers.py tests\regression\test_admin_api_futures_risk_proofs.py tests\regression\test_admin_api_contract.py tools\run_autonomous_work_queue_check.py`;
  `python tools\generate_admin_api_openapi.py`;
  `pytest tests\regression\test_admin_api_futures_risk_proofs.py::test_futures_request_payload_field_contracts_are_disabled tests\regression\test_admin_api_contract.py::test_admin_api_openapi_schema_file_matches_generated_contract tests\regression\test_admin_api_contract.py::test_admin_api_futures_read_routes_use_read_service_without_commands tests\regression\test_admin_api_contract.py::test_admin_api_futures_read_service_maps_runtime_positions_without_spot_rules tests\regression\test_admin_api_contract.py::test_admin_api_frontend_fixtures_are_bounded_and_offline_safe -q --tb=short --maxfail=1`
  (`5` passed, `1` warning); `python tools\run_autonomous_work_queue_check.py --summary-only`
  (passed); `python tools\check_ownership.py` (passed);
  `python tools\check_stale_test_processes.py --include-sibling-frontend`
  (passed); `python tools\check_runtime_artifacts.py --top 5` (passed,
  `0` artifacts, `0` GiB); and `git diff --check` (passed with line-ending
  warnings only). Frontend commands run: `npm run typecheck`;
  `npm run api:check`; `npm run autonomous:check`;
  `npx vitest run tests/unit/backendRuntime.test.ts tests/unit/backendApiClient.test.ts tests/unit/mockBackend.test.ts tests/unit/FuturesPerpetualsReadModel.test.tsx tests/unit/qualityGates.test.tsx --reporter=dot`
  (`121` passed); `npm run test:processes` (passed); and
  `git diff --check` (passed with line-ending warnings only).
- Current `7001-7020` blind/contextless review: first backend reviewer Boole
  (`019eff09-6b93-75c2-a756-b566e0c0ffb3`) failed on a broken autonomous
  validator, stale backend handoff text, and diff hygiene; those findings were
  remediated and Boole was closed. First frontend reviewer Bacon
  (`019eff09-946c-7140-a063-0c8ee13b6367`) failed on pending review logs and
  stale frontend handoff text; those findings were remediated and Bacon was
  closed. Fresh frontend reviewer Einstein
  (`019eff11-3f20-7151-ac86-e997b3cf318a`) passed the display-only posture.
  Fresh backend reviewer Peirce (`019eff11-2b1e-7780-a46d-4c79853df9bd`)
  failed on stale `genai_data/API_REFERENCE.md` and premature
  `genai_data/agent_state.md` pass claims; those findings were remediated and
  Peirce was closed. Fresh backend reviewer Ptolemy
  (`019eff17-ecad-79e3-85ac-dd9f970a2689`) passed after verifying the API
  reference, agent state, backend model/read-service/OpenAPI/test surface, and
  false execution/readiness flags. Ptolemy and Einstein were closed after their
  findings were consumed; no completed, failed, superseded, stale, or unused
  phase-scoped subagent remains intentionally open.
- Completed `6961-6980` validation: passed focused backend, frontend,
  autonomous, ownership, security, release-readiness, contextless review,
  stale-process, runtime-artifact report, and diff checks for ordinary phase
  closeout. Backend commands run:
  `python -m py_compile application\admin_api\models.py application\admin_api\read_service.py application\admin_api\futures_request_payload_validation_record_cancel_semantics.py tests\regression\test_admin_api_futures_risk_proofs.py tests\regression\test_admin_api_contract.py tools\run_autonomous_work_queue_check.py`;
  `pytest tests\regression\test_admin_api_futures_risk_proofs.py tests\regression\test_admin_api_contract.py::test_admin_api_openapi_schema_file_matches_generated_contract tests\regression\test_admin_api_contract.py::test_admin_api_futures_read_routes_use_read_service_without_commands tests\regression\test_admin_api_contract.py::test_admin_api_futures_read_service_maps_runtime_positions_without_spot_rules tests\regression\test_admin_api_contract.py::test_admin_api_frontend_fixtures_are_bounded_and_offline_safe -q --tb=short --maxfail=1`
  (`23` passed, `1` warning); `python tools\generate_admin_api_openapi.py`;
  `python tools\run_autonomous_work_queue_check.py --summary-only`
  (passed); `python tools\check_ownership.py` (passed);
  `python tools\check_stale_test_processes.py --include-sibling-frontend`
  (passed); `python tools\check_runtime_artifacts.py` (report-only
  `runtime_state\test_admin_api_contract` artifact found at `63.401` GiB,
  no files deleted); `git diff --check` (passed with line-ending warnings
  only). Frontend commands run: `npm run typecheck`; `npm run lint`;
  `npx vitest run tests/unit/backendApiClient.test.ts tests/unit/backendRuntime.test.ts tests/unit/mockBackend.test.ts tests/unit/FuturesPerpetualsReadModel.test.tsx tests/unit/qualityGates.test.tsx --reporter=dot`
  (`120` passed); `npm run api:generate`; `npm run api:check`;
  `npm run autonomous:check`; `npm run security:commands`;
  `npm run release:check`; `npm run test:processes`; `npm run build`;
  `git diff --check` (passed with line-ending warnings only).
- Previous `6921-6940` validation: passed focused backend, frontend,
  autonomous, ownership, security, release-readiness, contextless review, and
  stale-process gates for ordinary phase closeout. Backend commands run:
  `python -m py_compile application\admin_api\models.py application\admin_api\read_service.py application\admin_api\futures_request_payload_validation_record_funding_semantics.py tests\regression\test_admin_api_contract.py tests\regression\test_admin_api_futures_risk_proofs.py tools\run_autonomous_work_queue_check.py`;
  `pytest tests\regression\test_admin_api_futures_risk_proofs.py tests\regression\test_admin_api_contract.py::test_admin_api_openapi_schema_file_matches_generated_contract tests\regression\test_admin_api_contract.py::test_admin_api_futures_read_routes_use_read_service_without_commands tests\regression\test_admin_api_contract.py::test_admin_api_futures_read_service_maps_runtime_positions_without_spot_rules tests\regression\test_admin_api_contract.py::test_admin_api_frontend_fixtures_are_bounded_and_offline_safe -q --tb=short --maxfail=1`
  (`22` passed); `python tools\run_autonomous_work_queue_check.py --summary-only`
  (passed); `python tools\check_ownership.py` (passed);
  `python tools\check_stale_test_processes.py --include-sibling-frontend`
  (passed); `git diff --check` (passed with line-ending warnings only).
  Frontend commands run: `npm run typecheck`; `npm run lint`;
  `npm run test -- tests/unit/FuturesPerpetualsReadModel.test.tsx tests/unit/mockBackend.test.ts tests/unit/backendRuntime.test.ts tests/unit/qualityGates.test.tsx`
  (`74` passed); `npm run api:check`; `npm run autonomous:check`;
  `npm run security:commands`; `npm run release:check`; `npm run test:processes`;
  `git diff --check` (passed with line-ending warnings only).
- Completed `6961-6980` blind/contextless review: Maxwell
  (`019efea5-df2e-76b3-987c-00bca93a372f`) passed after inspecting local files
  without chat history. It confirmed completed `6961-6980` cancel-semantics
  evidence is backend-owned disabled/read-only evidence, cancellation identity
  remains `client_order_id` through `cancel_order(client_order_id)`, frontend
  display adds no browser/BFF/live execution authority, spot-only
  wallet/cost-basis/sell-guard rules are not imported into futures/perpetuals,
  and docs/capability matrices/review logs give a clear contextless starting
  point. Phase-end subagent sweep closed Maxwell after consuming findings; no
  completed, failed, superseded, stale, or unused phase-scoped subagent remains
  intentionally open.
- Full backend regression was not rerun for this ordinary phase. It remains a
  durable milestone closeout gate and is currently blocked before pytest by
  the oversized `runtime_state/test_admin_api_contract` artifact unless the
  operator explicitly approves cleanup/archive.
- Live Coinbase execution for current M57 phase work: not run. Submitted notional `0` USDC. Executed notional `0` USDC.

## Next 3 Actions

1. Commit and push the backend and frontend phase `7001-7020` semantic-closure work after final diff review.
2. Advance to the next approved M57 phase only after the phase `7001-7020` commits are complete.
3. Keep full regression reserved for durable milestone closeout or explicit request until the runtime artifact blocker is resolved.

## Handoff Notes

- Phase `6981-7000` adds backend-owned futures request payload validation
  record reconciliation semantics and frontend display only.
- The backend remains authoritative for trading behavior, guard checks, live execution, reconciliation, and Coinbase calls.
- The frontend consumes generated OpenAPI/backend contracts and remains display-only for this evidence surface.
- No spot-only wallet/no-shorting/cost-basis rules are imported into futures/perpetual command readiness.
- No live Coinbase execution was run; notional remains `0` USDC.
