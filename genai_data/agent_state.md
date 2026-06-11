# Agent State

Use this file as the single durable source of truth for active engineering work.
Keep it short. Keep it factual.

## Metadata

- Last updated (ET): 2026-06-11
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

## Active Scope

- In-scope files: Admin API contracts, admin platform docs, command/auth
  boundaries, frontend association docs, regression tests, and agent context
  needed for local-agent accuracy.
- Out-of-scope files: product catalogs, local order span JSON artifacts, and
  live Coinbase execution unless an approved phase explicitly requires it.
- Interfaces or modules that must not change without tests: dashboard
  WebSocket contract, FastAPI Admin API contracts, stealth lifecycle, BFF
  mutation allowlist, command services, and DB write paths.

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

- Last focused Admin API/exchange run: 2026-06-10
  `python tools\generate_admin_api_openapi.py; pytest tests\regression\test_admin_api_contract.py tests\regression\test_dashboard_action_condition_guard.py tests\regression\test_list_fills_param_mapping.py -v --tb=short`
- Result: Passed, 44 tests.
- Last frontend quality run: 2026-06-10 `npm run quality`
- Result: Passed; typecheck, lint, generated API schema freshness,
  command-fetch guard, 103 unit tests, and 3 Playwright tests.
- Last contextless Admin API/frontend review: 2026-06-10
- Result: Passed after legacy WebSocket docs were clarified for enterprise
  frontend work and HTTP cancel approval inventory wording was aligned with
  the current fail-closed gate.
- Last regression run: 2026-06-10 `pytest tests\regression\ -v --tb=short`
- Result: Passed, 758 tests.
- Spot readiness regression: passed, 223 tests.
- Spot release gate: passed; no live Coinbase orders run, submitted/executed
  notional `0` USDC.
- Last contextless spot order review: 2026-06-10
- Result: Passed after live SELL sweep was hardened to require
  `--require-known-profitable-inventory`, direct audit fields were clarified,
  and the contextless checklist was updated.
- Browser smoke: passed,
  `tests\e2e\test_direct_order_ui_smoke.py` and
  `tests\e2e\test_spot_readiness_ui_smoke.py`.
- Ownership check passed.
- Backend and frontend `git diff --check` passed with CRLF warnings only.
- Failing tests (if any): None.

## Next 3 Actions

1. Continue the approved enterprise API/frontend phase work without enabling
   live HTTP execution.
2. Keep broad SELL blocked. The current Phase 184/195 `PERP-USDC` canary packet
   is documentation only; its allowlist is expired and must be regenerated
   immediately before any later live approval.
3. For any later live USDC sweep SELL, require
   `--require-known-profitable-inventory`; the runner now rejects approved live
   SELL without that policy.
4. Keep contextless blind-review in the release loop for new spot order,
   campaign, or live-action UI behavior.

## Handoff Notes

- What is done: SELL authority allowlist generation, Phase 125 live SELL
  canary, reconciliation, lot-consumption fix, allowlist freshness enforcement,
  imported baseline freshness audit, average-cost authority gate, Phase 134
  strict SELL preflight, Phase 136 blind-agent review, Phase 138 live strict
  SELL canary for `ALT-USDC` / `B3-USDC` / `BLEND-USDC`, post-live strict
  allowlist consumption check, average-cost allowlist gate fix, blind-agent
  rerun with direct-order docs clarified, direct-order audit tooling, strict
  reconciliation ownership regression, Phase 153 live strict SELL canary for
  `AERGO-USDC` / `AI-USDC` / `ALLO-USDC` with `3.026224` USDC submitted and
  `3.021097` USDC executed, post-canary reconciliation, stealth reveal payload
  readability helper, public release gate, feature intake gate, Phase 160
  broad/narrow decision gate, direct spot manual acknowledgement/UI smoke,
  broad BUY/SELL read-only snapshots, USDC campaign design lock, automation
  rehearsal, Phase 170 live strict SELL canary for `1INCH-USDC` /
  `AAVE-USDC` / `ACH-USDC` with `3.0216716` USDC submitted and
  `3.022123640498578` USDC executed, post-canary reconciliation/P&L, and
  Phase 172 blind-agent/full validation, and Phase 173-184 read-only campaign
  operator reports/dashboard audit/contextless harness/strict SELL proposal,
  and Phase 185-196 dashboard direct-audit UI, campaign cleanup apply gate,
  retry fixture, direct spot gate hardening, mandatory live SELL sweep
  known-profit policy, contextless blind-review pass, and release gates.
- Phase 173-196 live execution: none. Submitted notional `0` USDC. Executed
  notional `0` USDC.
- Phase 184/195 current proposal: strict allowlist generated
  `2026-06-10T14:32:37Z`, one eligible product `PERP-USDC`, validator passed
  with `max_products=1`, `max_total_notional_per_run=1`,
  `max_notional_per_order=1`, and `max_planned_orders=1`; the allowlist is now
  expired and must be regenerated immediately before any later live approval.
- Admin API/frontend status: backend Admin API mutating routes are
  auth/RBAC-gated, idempotent, audited, and still HTTP-live-disabled with
  OpenAPI documenting `501` rather than `200`; read-only spot operator routes
  are auth/RBAC-gated and document `401`/`403`; auth mode evidence and
  read-only CSRF contract evidence are exposed for BFF/session deployments;
  dashboard `place_order`/`cancel_order` delegates to the shared command
  service but remains legacy compatibility for frontend product flows; the
  Coinbase single-order cancel wrapper remains `client_order_id` keyed and
  rejects non-explicit-success cancel payloads; frontend generated schema and
  read-only spot operator views are current. No live Coinbase execution was run.
- What is in progress: approved Admin API/frontend roadmap work continues after
  this backend/frontend contract hardening batch is committed and pushed.
- What is blocked: Nothing currently known.
- Exact next command: `pytest tests\regression\ -v --tb=short` for the next non-agent-file change.
