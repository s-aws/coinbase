# Agent State

Use this file as the single durable source of truth for active engineering work.
Keep it short. Keep it factual.

## Metadata

- Last updated (ET): 2026-06-25
- Updated by: Codex
- Branch: codex/stealth-live-service-decision-3501
- Commit (optional): current active range is `6881-6900`.

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

- Latest completed autonomous range before current work: `6861-6880`.
- Active autonomous range: `6881-6900`.
- Current direction: complete phases `6881-6900` with futures request payload
  validation record reduce-only semantics.
- Exact active evidence phrase: futures request payload validation record reduce-only semantics.
- Active `6881-6900` adds disabled futures request payload validation record
  reduce-only semantics through
  `application/admin_api/futures_request_payload_validation_record_reduce_only_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REDUCE_ONLY_SEMANTIC_CONTRACTS`,
  and
  `iter_futures_request_payload_validation_record_reduce_only_semantics`.
  It exposes `request_payload_validation_record_reduce_only_semantic_count`,
  `blocking_request_payload_validation_record_reduce_only_semantic_count`,
  `ready_request_payload_validation_record_reduce_only_semantic_count`,
  `runtime_observed_request_payload_validation_record_reduce_only_semantic_count`,
  `request_payload_validation_record_reduce_only_semantics`,
  `reduce_only_semantics_ref`, `reduce_only_semantics_contract_ref`,
  `evidence_routes`, `reduce_only_semantics_contract_available`,
  `reduce_only_semantics_contract_ready`, `reduce_only_flag_bound`,
  `reduce_only_position_side_bound`, `reduce_only_position_size_bound`,
  `reduce_only_order_side_bound`, `runtime_reduce_only_evidence_observed`,
  `runtime_evidence_satisfies_reduce_only_semantics`, and
  `validation_record_reduce_only_semantics_ready`; every readiness,
  execution, live Coinbase, browser, BFF, and spot-rule authority flag remains
  false or display-only.
- Completed `6861-6880` carries forward disabled futures request payload
  validation record liquidation semantics through
  `application/admin_api/futures_request_payload_validation_record_liquidation_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_LIQUIDATION_SEMANTIC_CONTRACTS`,
  and
  `iter_futures_request_payload_validation_record_liquidation_semantics`.
- Completed `6841-6860` carries forward disabled futures request payload
  validation record collateral semantics through
  `application/admin_api/futures_request_payload_validation_record_collateral_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_COLLATERAL_SEMANTIC_CONTRACTS`,
  and
  `iter_futures_request_payload_validation_record_collateral_semantics`.
- Completed `6821-6840` carries forward disabled futures request payload
  validation record margin semantics through
  `application/admin_api/futures_request_payload_validation_record_margin_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_MARGIN_SEMANTIC_CONTRACTS`,
  and
  `iter_futures_request_payload_validation_record_margin_semantics`.
- Completed `6801-6820` carries forward disabled futures request payload
  validation record position semantics through
  `application/admin_api/futures_request_payload_validation_record_position_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_POSITION_SEMANTIC_CONTRACTS`,
  and
  `iter_futures_request_payload_validation_record_position_semantics`.
- Completed `6781-6800` carries forward disabled futures request payload
  validation record semantic artifact runtime evidence acceptance through
  `application/admin_api/futures_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS`,
  and
  `iter_futures_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances`.
- Completed `6761-6780` carries forward disabled futures request payload
  validation record semantic artifact runtime evidence binding through
  `application/admin_api/futures_request_payload_validation_record_semantic_artifact_runtime_evidences.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_CONTRACTS`,
  and
  `iter_futures_request_payload_validation_record_semantic_artifact_runtime_evidences`.

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

- Latest completed autonomous range before current work: `6861-6880`.
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

- Active autonomous range: `6881-6900`.
- Active milestone: M57 - Futures/Perpetuals Contract Foundation And Commands.
- Current direction: complete phases `6881-6900` with backend-owned futures
  request payload validation record reduce-only semantics and matching frontend
  display.
- Backend active source:
  `application/admin_api/futures_request_payload_validation_record_reduce_only_semantics.py`.
- Backend active registry:
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REDUCE_ONLY_SEMANTIC_CONTRACTS`
  and `iter_futures_request_payload_validation_record_reduce_only_semantics`.
- Active command-suite evidence fields:
- `request_payload_validation_record_reduce_only_semantic_count`,
  `blocking_request_payload_validation_record_reduce_only_semantic_count`,
  `ready_request_payload_validation_record_reduce_only_semantic_count`,
  `runtime_observed_request_payload_validation_record_reduce_only_semantic_count`,
  and `request_payload_validation_record_reduce_only_semantics`.
- Active evidence phrase: futures request payload validation record reduce-only semantics.
- Active display phrase: futures request payload validation record reduce-only semantics.
- Carried-forward liquidation phrase: futures request payload validation record liquidation semantics.
- Carried-forward collateral phrase: futures request payload validation record collateral semantics.
- Carried-forward margin phrase: futures request payload validation record margin semantics.
- Carried-forward position phrase: futures request payload validation record position semantics.
- Carried-forward acceptance phrase: futures request payload validation record semantic artifact runtime evidence acceptance.
- Active row evidence fields:
  `semantic_artifact_definition_review_ref`,
  `semantic_artifact_definition_review_contract_ref`,
  `semantic_artifact_definition_review_input_ref`,
  `semantic_artifact_definition_review_input_contract_ref`,
  `semantic_artifact_definition_review_output_ref`,
  `semantic_artifact_definition_review_output_contract_ref`,
  `semantic_artifact_definition_review_output_acceptance_ref`,
  `semantic_artifact_definition_review_output_acceptance_contract_ref`,
  `semantic_artifact_runtime_evidence_ref`,
  `semantic_artifact_runtime_evidence_contract_ref`,
  `semantic_artifact_runtime_evidence_acceptance_ref`,
  `semantic_artifact_runtime_evidence_acceptance_contract_ref`,
  `position_semantics_ref`,
  `position_semantics_contract_ref`,
  `margin_semantics_ref`,
  `margin_semantics_contract_ref`,
  `collateral_semantics_ref`,
  `collateral_semantics_contract_ref`,
  `liquidation_semantics_ref`,
  `liquidation_semantics_contract_ref`,
  `reduce_only_semantics_ref`,
  `reduce_only_semantics_contract_ref`,
  `evidence_routes`,
  `position_semantics_contract_available=false`,
  `position_semantics_contract_ready=false`,
  `margin_semantics_contract_available=false`,
  `margin_semantics_contract_ready=false`,
  `collateral_semantics_contract_available=false`,
  `collateral_semantics_contract_ready=false`,
  `liquidation_semantics_contract_available=false`,
  `liquidation_semantics_contract_ready=false`,
  `reduce_only_semantics_contract_available=false`,
  `reduce_only_semantics_contract_ready=false`,
  `position_identity_bound=false`,
  `position_scope_bound=false`,
  `position_side_derivation_bound=false`,
  `position_size_bound=false`,
  `position_notional_bound=false`,
  `margin_account_bound=false`,
  `margin_requirement_bound=false`,
  `margin_mode_bound=false`,
  `margin_buffer_bound=false`,
  `collateral_balance_bound=false`,
  `collateral_currency_bound=false`,
  `collateral_requirement_bound=false`,
  `collateral_source_bound=false`,
  `liquidation_buffer_bound=false`,
  `liquidation_price_bound=false`,
  `liquidation_distance_bound=false`,
  `liquidation_threshold_bound=false`,
  `reduce_only_flag_bound=false`,
  `reduce_only_position_side_bound=false`,
  `reduce_only_position_size_bound=false`,
  `reduce_only_order_side_bound=false`,
  `runtime_position_evidence_observed=false`,
  `runtime_margin_evidence_observed=false`,
  `runtime_collateral_evidence_observed=false`,
  `runtime_liquidation_evidence_observed=false`,
  `runtime_reduce_only_evidence_observed=false`,
  `runtime_evidence_satisfies_position_semantics=false`,
  `runtime_evidence_satisfies_margin_semantics=false`,
  `runtime_evidence_satisfies_collateral_semantics=false`,
  `runtime_evidence_satisfies_liquidation_semantics=false`,
  `runtime_evidence_satisfies_reduce_only_semantics=false`,
  `validation_record_position_semantics_ready=false`,
  `validation_record_margin_semantics_ready=false`,
  `validation_record_collateral_semantics_ready=false`,
  `validation_record_liquidation_semantics_ready=false`,
  `validation_record_reduce_only_semantics_ready=false`,
  `contextless_review_required=true`,
  `semantic_artifact_definition_available=false`,
  `semantic_artifact_definition_review_available=false`,
  `semantic_artifact_definition_reviewed=false`,
  `semantic_artifact_definition_review_passed=false`,
  `semantic_artifact_definition_review_input_available=false`,
  `semantic_artifact_definition_review_input_accepted=false`,
  `semantic_artifact_definition_review_output_available=false`,
  `semantic_artifact_definition_review_output_accepted=false`,
  `semantic_artifact_definition_review_output_acceptance_available=false`,
  `semantic_artifact_definition_review_output_acceptance_accepted=false`,
  `semantic_artifact_runtime_evidence_available=false`,
  `semantic_artifact_runtime_evidence_bound=false`,
  `semantic_artifact_runtime_evidence_accepted=false`,
  `semantic_artifact_runtime_evidence_acceptance_available=false`,
  `semantic_artifact_runtime_evidence_acceptance_accepted=false`,
  `runtime_evidence_satisfies_semantic_artifact_definition=false`,
  `semantic_artifact_defined=false`, `semantic_artifact_reviewed=false`,
  `execution_eligibility_blocker_resolved=false`,
  `validation_record_execution_eligible=false`, `execution_allowed=false`,
  and `live_coinbase_orders_ran=false`.
- Boundary: this active range does not validate command payloads, pass
  contextless reviews as execution authority, accept reduce-only semantics,
  bind live account/risk evidence, accept review inputs, accept review
  outputs, accept review-output acceptances, accept or bind runtime evidence,
  admit commands, accept risk proofs as command readiness, call Coinbase,
  execute reconciliation, mutate futures/order/exchange state, grant
  browser/BFF authority, or import spot-only rules into futures/perpetuals.
- Cancel command identity remains `client_order_id`.
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

Current direction: complete phases `6841-6860` with futures request payload validation record collateral semantics.

Active evidence phrases: futures request payload validation record collateral semantics; futures request payload validation record collateral semantics display.

Active backend files and constants: application/admin_api/futures_request_payload_validation_record_collateral_semantics.py; FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_COLLATERAL_SEMANTIC_CONTRACTS; iter_futures_request_payload_validation_record_collateral_semantics.

Active command-suite fields: request_payload_validation_record_collateral_semantic_count; blocking_request_payload_validation_record_collateral_semantic_count; ready_request_payload_validation_record_collateral_semantic_count; runtime_observed_request_payload_validation_record_collateral_semantic_count; request_payload_validation_record_collateral_semantics; collateral_semantics_ref; collateral_semantics_contract_ref; evidence_routes; request_payload_validation_record_margin_semantic_count; blocking_request_payload_validation_record_margin_semantic_count; ready_request_payload_validation_record_margin_semantic_count; runtime_observed_request_payload_validation_record_margin_semantic_count; request_payload_validation_record_margin_semantics; margin_semantics_ref; margin_semantics_contract_ref; request_payload_validation_record_position_semantic_count; blocking_request_payload_validation_record_position_semantic_count; ready_request_payload_validation_record_position_semantic_count; runtime_observed_request_payload_validation_record_position_semantic_count; request_payload_validation_record_position_semantics; position_semantics_ref; position_semantics_contract_ref; semantic_artifact_runtime_evidence_ref; semantic_artifact_runtime_evidence_contract_ref; semantic_artifact_runtime_evidence_acceptance_ref; semantic_artifact_runtime_evidence_acceptance_contract_ref.

Active false flags: contextless_review_required=true; collateral_semantics_contract_available=false; collateral_semantics_contract_ready=false; collateral_balance_bound=false; collateral_currency_bound=false; collateral_requirement_bound=false; collateral_source_bound=false; runtime_collateral_evidence_observed=false; runtime_evidence_satisfies_collateral_semantics=false; validation_record_collateral_semantics_ready=false; margin_semantics_contract_available=false; margin_semantics_contract_ready=false; margin_account_bound=false; margin_requirement_bound=false; margin_mode_bound=false; margin_buffer_bound=false; runtime_margin_evidence_observed=false; runtime_evidence_satisfies_margin_semantics=false; validation_record_margin_semantics_ready=false; position_semantics_contract_available=false; position_semantics_contract_ready=false; position_identity_bound=false; position_scope_bound=false; position_side_derivation_bound=false; position_size_bound=false; position_notional_bound=false; runtime_position_evidence_observed=false; runtime_evidence_satisfies_position_semantics=false; validation_record_position_semantics_ready=false; semantic_artifact_definition_available=false; semantic_artifact_definition_review_available=false; semantic_artifact_definition_reviewed=false; semantic_artifact_definition_review_passed=false; semantic_artifact_definition_review_input_available=false; semantic_artifact_definition_review_input_accepted=false; semantic_artifact_definition_review_output_available=false; semantic_artifact_definition_review_output_accepted=false; semantic_artifact_definition_review_output_acceptance_available=false; semantic_artifact_definition_review_output_acceptance_accepted=false; semantic_artifact_runtime_evidence_available=false; semantic_artifact_runtime_evidence_bound=false; semantic_artifact_runtime_evidence_accepted=false; semantic_artifact_runtime_evidence_acceptance_available=false; semantic_artifact_runtime_evidence_acceptance_accepted=false; runtime_evidence_satisfies_semantic_artifact_definition=false; semantic_artifact_defined=false; semantic_artifact_reviewed=false; execution_eligibility_blocker_resolved=false; validation_record_execution_eligible=false; execution_allowed=false; live_coinbase_orders_ran=false.

Carried-forward evidence phrases: futures request payload contract registry evidence; futures request payload validation gate evidence; futures request payload validator contract registry evidence; futures request payload validator input-schema evidence; futures request payload validator output-schema evidence; futures request payload validator registration evidence; futures request payload validation evidence; futures request payload validation evidence record contract evidence; futures request payload validation record schema evidence; futures request payload validation record replay guard evidence; futures request payload validation record audit-link evidence; futures request payload validation record admission-link evidence; futures request payload validation record execution-eligibility blocker evidence; futures request payload validation record semantic artifact evidence; futures request payload validation record semantic artifact definition evidence; futures request payload validation record semantic artifact definition review evidence; futures request payload validation record semantic artifact runtime evidence acceptance; futures request payload validation record position semantics; futures request payload validation record margin semantics.

Carried-forward backend files: application/admin_api/futures_request_payload_contracts.py; application/admin_api/futures_request_payload_validators.py; application/admin_api/futures_request_payload_validator_input_schemas.py; application/admin_api/futures_request_payload_validator_output_schemas.py; application/admin_api/futures_request_payload_validator_registrations.py; application/admin_api/futures_request_payload_validation_evidence.py; application/admin_api/futures_request_payload_validation_evidence_records.py; application/admin_api/futures_request_payload_validation_record_schemas.py; application/admin_api/futures_request_payload_validation_record_replay_guards.py; application/admin_api/futures_request_payload_validation_record_audit_links.py; application/admin_api/futures_request_payload_validation_record_admission_links.py; application/admin_api/futures_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances.py; application/admin_api/futures_request_payload_validation_record_position_semantics.py; application/admin_api/futures_request_payload_validation_record_margin_semantics.py.

Carried-forward backend constants: FUTURES_REQUEST_PAYLOAD_FIELD_CONTRACTS; iter_futures_request_payload_contracts; FUTURES_REQUEST_PAYLOAD_VALIDATOR_CONTRACTS; iter_futures_request_payload_validator_contracts; FUTURES_REQUEST_PAYLOAD_VALIDATOR_INPUT_SCHEMA_CONTRACTS; iter_futures_request_payload_validator_input_schemas; FUTURES_REQUEST_PAYLOAD_VALIDATOR_OUTPUT_SCHEMA_CONTRACTS; iter_futures_request_payload_validator_output_schemas; FUTURES_REQUEST_PAYLOAD_VALIDATOR_REGISTRATION_CONTRACTS; iter_futures_request_payload_validator_registrations; FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_CONTRACTS; iter_futures_request_payload_validation_evidence; FUTURES_REQUEST_PAYLOAD_VALIDATION_EVIDENCE_RECORD_CONTRACTS; iter_futures_request_payload_validation_evidence_records; FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SCHEMA_CONTRACTS; iter_futures_request_payload_validation_record_schemas; FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REPLAY_GUARD_CONTRACTS; iter_futures_request_payload_validation_record_replay_guards; FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS; iter_futures_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances; FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_POSITION_SEMANTIC_CONTRACTS; iter_futures_request_payload_validation_record_position_semantics; FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_MARGIN_SEMANTIC_CONTRACTS; iter_futures_request_payload_validation_record_margin_semantics.

Carried-forward command-suite fields: request_field_count; blocking_request_field_count; request_payload_validator_contract_count; blocking_request_payload_validator_contract_count; request_payload_validator_input_schema_count; blocking_request_payload_validator_input_schema_count; request_payload_validator_output_schema_count; blocking_request_payload_validator_output_schema_count; request_payload_validator_registration_count; blocking_request_payload_validator_registration_count; request_payload_validation_evidence_count; blocking_request_payload_validation_evidence_count; request_payload_validation_evidence_record_count; blocking_request_payload_validation_evidence_record_count; request_payload_validation_record_schema_count; blocking_request_payload_validation_record_schema_count; request_payload_validation_record_replay_guard_count; blocking_request_payload_validation_record_replay_guard_count; request_payload_validation_record_semantic_artifact_runtime_evidence_count; blocking_request_payload_validation_record_semantic_artifact_runtime_evidence_count; ready_request_payload_validation_record_semantic_artifact_runtime_evidence_count; runtime_observed_request_payload_validation_record_semantic_artifact_runtime_evidence_count; request_payload_validation_record_semantic_artifact_runtime_evidences; request_payload_validation_record_semantic_artifact_runtime_evidence_acceptance_count; blocking_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptance_count; ready_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptance_count; runtime_observed_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptance_count; request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances.

Carried-forward refs and flags: validation_gate_ref; validation_evidence_ref; validator_contract_ref; validator_input_schema_ref; validator_output_schema_ref; output_schema_field_refs; output_schema_field_count; validator_registration_ref; validator_registration_field_refs; validator_registration_field_count; validation_evidence_contract_ref; validation_evidence_field_refs; validation_evidence_field_count; validation_record_contract_ref; validation_record_store_ref; validation_record_writer_ref; validation_record_replay_guard_ref; validation_record_field_refs; validation_record_field_count; validation_record_schema_ref; validation_record_append_only_log_ref; validation_record_replay_guard_contract_ref; validation_record_idempotency_contract_ref; validation_record_replay_window_ref; validation_record_duplicate_policy_ref; validation_record_schema_field_refs; validation_record_schema_field_count; validation_record_replay_guard_field_refs; validation_record_replay_guard_field_count; validator_input_schema_registered; validator_output_schema_registered; output_schema_registered; validator_registration_ready; runtime_evidence_satisfies_validator_registration; runtime_evidence_satisfies_validation_evidence; validation_evidence_ready; validation_evidence_recorded; runtime_evidence_satisfies_validation_record; validation_record_contract_ready; validation_record_store_ready; validation_record_writer_enabled; validation_record_replay_guard_ready; runtime_evidence_satisfies_validation_record_schema; runtime_evidence_satisfies_validation_record_replay_guard; validation_record_schema_ready; validation_record_schema_registered; validation_record_replay_guard_contract_ready; validation_record_idempotency_contract_ready; validation_record_replay_protected; validation_record_append_only_log_ready; validation_recorded; append_only_validation_record; validation_record_idempotency_bound; validation_gate_ready; validation_gate_passed; request_payload_validated.

Futures command route reminders: route/draft flags are true while execution remains false; cancel by `client_order_id`; /api/v1/futures/orders; /api/v1/futures/positions/{position_key}/close-reduce; /api/v1/futures/orders/{client_order_id}/cancel; /api/v1/futures/positions/{position_key}/reconciliation; /api/v1/futures/command-suite; /api/v1/futures/risk-proofs; no proof acceptance; no Coinbase activity; no reconciliation execution; no futures state mutation; forbidden spot assumptions.

Legacy live-boundary reminders that remain disabled: live_execution_disabled; futures live adapter contract missing; futures reconciliation execution missing; adapter contract refs are required/present disabled evidence; adapter construction refs are required/present disabled evidence; adapter decision refs are required/present disabled evidence; adapter decision-record refs are required/present disabled evidence; adapter invocation refs are required/present disabled evidence; adapter execution refs are required/present disabled evidence; Coinbase exchange-submission refs are required/present disabled evidence; post-exchange-submission reconciliation refs are required/present disabled evidence.

## Validation Status

- Last completed backend focused validation: 2026-06-24 for phases `6741-6760`.
  Result: Passed. Commands run:
  `python -m py_compile application\admin_api\read_service.py application\admin_api\models.py application\admin_api\futures_request_payload_validation_record_semantic_artifact_definition_review_outputs.py tests\regression\test_admin_api_futures_risk_proofs.py tests\regression\test_spot_readiness_gate.py tools\run_autonomous_work_queue_check.py`;
  `pytest tests\regression\test_admin_api_futures_risk_proofs.py -q --tb=short` (17 passed);
  `pytest tests\regression\test_spot_readiness_gate.py -q --tb=short` (8 passed);
  `pytest tests\regression\test_admin_api_contract.py -q --tb=short` (135 passed);
  `python tools\run_autonomous_work_queue_check.py --summary-only` (passed).
- Completed `6721-6740` backend serializer remediation: Passed. The public
  futures command-suite API payload remains bounded while keeping semantic
  guard blocker refs visible; the offline frontend fixture preserves root
  `required_backend_contracts` / `missing_backend_contracts` summary evidence.
  Measured payloads: public command-suite `8,791,189` bytes and full frontend
  fixtures `18,493,240` bytes, both under the existing regression caps.
- Last completed frontend focused validation: 2026-06-24 for phases
  `6761-6780`. Result: Passed. Commands run:
  `npm run api:check`; `npm run typecheck`;
  `npx vitest run tests/unit/qualityGates.test.tsx tests/unit/AdminShell.test.tsx tests/unit/backendRuntime.test.ts tests/unit/mockBackend.test.ts tests/unit/FuturesPerpetualsReadModel.test.tsx` (73 passed);
  `npm run autonomous:check` (passed). Live Coinbase execution not run;
  notional `0` USDC.
- Last completed backend focused validation: 2026-06-24 for phases
  `6761-6780`. Result: Passed. Commands run:
  `python -m py_compile application\admin_api\futures_request_payload_validation_record_semantic_artifact_runtime_evidences.py application\admin_api\models.py application\admin_api\read_service.py tests\regression\test_admin_api_futures_risk_proofs.py tests\regression\test_spot_readiness_gate.py tools\run_autonomous_work_queue_check.py`;
  `python -m pytest tests\regression\test_admin_api_futures_risk_proofs.py -q --tb=short` (17 passed);
  `python -m pytest tests\regression\test_spot_readiness_gate.py -q --tb=short` (8 passed);
  `python -m pytest tests\regression\test_admin_api_contract.py::test_admin_api_openapi_schema_file_matches_generated_contract -q --tb=short` (1 passed);
  `python tools\run_autonomous_work_queue_check.py --summary-only` (passed).
- Last completed blind/contextless review: 2026-06-24 for phases `6761-6780`.
  Result: backend review PASS; frontend review initially failed because backend
  and frontend contextless review logs still led with `6741-6760`. Remediation
  updated both review logs, frontend testing docs, futures/perpetual read docs,
  and this state file. Fresh backend/frontend remediation re-review confirmed
  the runtime evidence source, fields, active range, and no-live/no-authority
  boundary are understandable without chat history.
- Phase-end stale-subagent sweep for `6761-6780`: completed. Consumed and
  remediated findings from Parfit (`019efbf8-694a-7510-94b7-de78e37958f2`),
  Gauss (`019efbf8-a80b-7f93-898c-5dd43f801cc9`), and Tesla
  (`019efc03-f938-7bc0-bfb2-d8c9c092725f`).
- Last stale process checks: 2026-06-24. Backend and frontend stale
  test-process checks passed.
- Last full backend regression: 2026-06-16 historical pass. Full regression was not rerun for this ordinary phase. Current full regression closeout remains blocked until oversized `runtime_state/test_admin_api_contract` artifacts are cleaned or archived with explicit operator approval.
- Current `6841-6860` validation: passed focused backend, frontend,
  autonomous, and contextless review gates for ordinary phase closeout.
  Backend commands run:
  `python -m py_compile application\admin_api\futures_request_payload_validation_record_collateral_semantics.py application\admin_api\models.py application\admin_api\read_service.py tests\regression\test_admin_api_futures_risk_proofs.py tools\run_autonomous_work_queue_check.py`;
  `python -m pytest tests\regression\test_admin_api_futures_risk_proofs.py tests\regression\test_admin_api_contract.py::test_admin_api_openapi_schema_file_matches_generated_contract -q --tb=short`
  (18 passed); `python tools\run_autonomous_work_queue_check.py --summary-only`
  (passed); `python tools\check_ownership.py` (passed);
  `python tools\check_stale_test_processes.py --include-sibling-frontend`
  (passed); `git diff --check` (passed with line-ending warnings only).
  Frontend commands run: `npm run api:check`; `npm run typecheck`;
  `npm run test -- FuturesPerpetualsReadModel.test.tsx mockBackend.test.ts backendRuntime.test.ts qualityGates.test.tsx AdminShell.test.tsx`
  (77 passed); `npm run autonomous:check` (passed);
  `npm run test:processes` (passed); `git diff --check` (passed with
  line-ending warnings only).
- Full backend regression was not rerun for this ordinary phase. It remains a
  durable milestone closeout gate and is currently blocked before pytest by
  the oversized `runtime_state/test_admin_api_contract` artifact unless the
  operator explicitly approves cleanup/archive.
- Live Coinbase execution for current M57 phase work: not run. Submitted notional `0` USDC. Executed notional `0` USDC.

## Next 3 Actions

1. Commit and push the backend and frontend phase `6841-6860` work after final diff review.
2. Continue the next approved M57 phase range only after this phase is committed.
3. Keep full regression reserved for durable milestone closeout or explicit request until the runtime artifact blocker is resolved.

## Handoff Notes

- Phase `6841-6860` adds backend-owned futures request payload validation
  record collateral semantics and frontend display only.
- The backend remains authoritative for trading behavior, guard checks, live execution, reconciliation, and Coinbase calls.
- The frontend consumes generated OpenAPI/backend contracts and remains display-only for this evidence surface.
- No spot-only wallet/no-shorting/cost-basis rules are imported into futures/perpetual command readiness.
- No live Coinbase execution was run; notional remains `0` USDC.
