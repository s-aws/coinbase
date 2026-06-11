# Admin API Contextless Review Log

This log records blind reviews for the Admin API/backend association work.

## Enterprise Admin Platform Pivot Review

Review scope:

- `C:\coinbase`
- `C:\coinbase-frontend`
- No chat history supplied to reviewers.

Reviewer tasks:

- verify the backend Admin API is documented as the current live-disabled
  contract layer for an enterprise admin platform across the whole trading
  engine
- verify Spot is the first complete product module but not the generic module
  shape
- verify non-spot modules require backend-owned contracts and must not import
  spot-only rules
- verify frontend/backend boundaries, ownership/testing gates, and release
  gate wording are discoverable

Findings:

- The platform pivot and capability matrix were discoverable.
- Initial backend blind review found stale `planned`, `future`, and `skeleton`
  wording in required entry docs and expanded local context that could imply
  the Admin API was future-only.
- A follow-up review found `genai_data/API_REFERENCE.md` still called the
  Admin API a skeleton.
- A final frontend-focused review found the human operator runbook still
  described `npm run quality` as the full frontend gate.

Resolution:

- Added backend admin platform architecture and module capability matrix docs.
- Updated Admin API README, docs index, frontend association, examples, agent
  contract, ownership docs, and expanded local context to use current
  live-disabled-contract language.
- Replaced stale skeleton labels with current live-disabled command wording.
- Mirrored the frontend release-gate correction so contextless agents see
  `npm run release:gate` as the canonical full/release gate.

Status:

- Final blind blocker review found no remaining blocker-level contradictions.
- Backend checks passed: `python tools\check_ownership.py --owner architect`
  and `python tools\run_autonomous_work_queue_check.py --summary-only`.
- Backend regression was not rerun because the backend change set is docs,
  expanded local context, and ownership metadata only.
- Live Coinbase execution was not run; backend notional `$0`.

## Runtime Evidence Review - Phases 541-560

Review scope:

- `C:\coinbase`
- `C:\coinbase-frontend`
- No chat history supplied to reviewers.

Reviewer task:

- determine whether a contextless maintainer can find the command that writes
  saved runtime/UI evidence
- confirm `artifacts/runtime-evidence.json` naming and no-live Coinbase
  posture
- find active queue range `541-560`, live cap, and stop conditions
- verify OIDC readiness, canonical wrappers, visual smoke targets, and route
  evidence are represented clearly enough to prevent parallel implementations

Findings:

- First blind review failed the batch. The saved runtime evidence artifact
  listed only the narrow admin wrapper/route subset and under-represented
  order, spot, and command wrappers documented by the API contract. That could
  mislead a contextless maintainer into inventing parallel order/spot paths.
- Remediation expanded runtime evidence to include canonical admin, order,
  spot, and command wrappers plus all generated Admin API route evidence.
  Runtime evidence validators, release/deployment checks, and unit tests now
  require the broader surface.
- Follow-up blind review passed with no blockers. It confirmed
  `npm run runtime:evidence`, `artifacts/runtime-evidence.json`, no-live
  notional `$0`, OIDC readiness, visual smoke targets, route evidence, and the
  active queue range/caps are discoverable.
- Non-blocking concern: `runtime-evidence.json` itself does not embed the
  queue range/cap/stop posture. That posture remains centralized in
  `docs/plans/AUTONOMOUS_WORK_QUEUE.md` and queue validators to avoid a
  second source of truth.

Status:

- Findings resolved. No live Coinbase execution was run in this batch;
  notional `$0`.

## Backend Sync Review - Phases 241-270

Review scope:

- `C:\coinbase`
- `C:\coinbase-frontend`
- No chat history supplied to reviewer.

Reviewer task:

- identify the backend-owned OpenAPI source
- explain manual spot order create, cancel, campaign execution, order reads,
  and direct spot audit through Admin API
- confirm live Coinbase execution posture
- confirm `client_order_id` versus exchange id usage
- identify required gates
- report code/docs gaps that would mislead a contextless agent or human

Findings:

- Backend OpenAPI source and frontend generated-client flow were discoverable.
- Manual create, cancel, campaign execution, order list/detail, and direct
  order audit routes were discoverable.
- Live HTTP Coinbase execution was clearly disabled through the app headers,
  approval gate, command service, and regression tests.
- `client_order_id` identity rules were clear. Exchange ids were exposed only
  as evidence fields.
- Required backend and frontend quality gates were discoverable.
- The frontend command UI is still intentionally disabled; this is expected.
- Frontend command mock tests used stale service method names.
- Backend Admin API agent context still described implemented files as
  future/planned.
- Frontend command workflow docs used wording that could imply current HTTP
  commands already run guard/cap checks instead of short-circuiting at the
  live-disabled gate.

Resolution:

- Updated frontend mock command responses to use `place_manual_order` and
  `cancel_order_by_client_order_id`.
- Updated `docs/agents/AGENT_ADMIN_API_CONTRACT.md` to describe current
  implemented modules, routes, and tests.
- Updated frontend command workflow docs to say guard/cap evidence is required
  before live enablement and current HTTP commands short-circuit at the
  live-disabled gate.

Status:

- Findings resolved. No live Coinbase execution was run.

## Runtime Hardening Review - Phases 371-390

Review scope:

- `C:\coinbase`
- `C:\coinbase-frontend`
- No chat history supplied to reviewer.

Reviewer task:

- explain how the enterprise frontend creates or dry-submits a spot order
  without inventing frontend trading behavior
- identify the backend OpenAPI source and frontend generated contract
- identify BFF server-only authority and CSRF handling
- identify manual create/cancel wrappers and `client_order_id` identity
- identify backend route/service/gate flow
- identify dry-submit, audit, idempotency, and correlation evidence rendering
- identify order pagination and direct-order audit identity rules
- list proof commands and surface misleading docs/code

Findings:

- Review passed. The frontend still has no live trading path; command buttons
  remain disabled and dry-submit/live-disabled evidence is backend-owned.
- The reviewer found the contract path:
  backend OpenAPI -> generated frontend schema -> `BackendApiClient` wrappers.
- BFF mode was clear: browser selects `/api/admin`, while server-only
  `ADMIN_API_*` variables supply backend authority and optional CSRF.
- Manual create/cancel flow was clear:
  `CommandWorkflowShell` -> `commandDrySubmit.ts` -> `BackendApiClient` ->
  backend `api/v1/routes/orders.py` -> `AdminApiCommandService`.
- Cancel, order reads, pagination, and direct-order audit remain keyed by
  `client_order_id`; exchange ids are evidence only.
- Dry-submit evidence renders HTTP status, command status, idempotency key,
  `client_order_id`, audit id, correlation id, and live Coinbase execution
  false.
- Risk identified: legacy dashboard WebSocket docs are accurate but can
  mislead a contextless frontend agent if read without the frontend/Admin API
  boundary docs.
- Risk identified: cancel route inventory wording understated the current HTTP
  live-disabled approval gate.

Resolution:

- Added explicit warnings to legacy spot/dashboard docs that enterprise
  frontend product flows must use the HTTP Admin API/BFF contract, not the
  dashboard WebSocket.
- Updated route inventory wording for HTTP cancel to match the current
  fail-closed approval gate.

Status:

- Findings resolved. No live Coinbase execution was run. Notional `$0`.

## Autonomous Work Queue Review - Phases 501-520

Review scope:

- `C:\coinbase`
- `C:\coinbase-frontend`
- No chat history supplied to reviewer.

Reviewer task:

- determine whether a smaller local agent or human can continue approved
  unattended phases 501-520 from repository docs alone
- identify the autonomous queue docs, approved phases, live caps, stop
  conditions, backend/frontend gates, no-live frontend posture, and stale or
  contradictory docs

Findings:

- The queue was discoverable in both repos:
  `docs/plans/AUTONOMOUS_WORK_QUEUE.md`, linked from ordered docs indexes.
- Approved phases were clear: 501-520.
- Live cap posture was clear: default no live execution; if a phase explicitly
  needs backend live evidence, cap at `3.10` USDC submitted and `1.00` USDC
  executed on the cheapest Coinbase `USDC` spot product available to US
  customers, retain inventory, and require reconciliation.
- Frontend no-live posture was clear: frontend release/artifact/smoke gates
  must report live Coinbase execution not run and notional `$0`.
- Findings requiring remediation:
  - Worktrees were dirty with intended in-progress queue changes; this must be
    resolved by final commit/clean-tree check before claiming phase 520 or
    advancing to the next batch.
  - Frontend `AGENTS.md` called its shorter command list the full quality gate
    while release/deployment docs use the broader `npm run release:gate`.
  - Backend regression command spelling varied between Windows and Bash
    contexts.

Resolution:

- Frontend `AGENTS.md` now calls the shorter list the baseline gate and points
  release/BFF/deployment/autonomous/API work to `npm run release:gate`.
- Backend and frontend autonomous queue docs now list both Windows
  `pytest tests\regression\ -v --tb=short` and Bash
  `python3 -m pytest tests/regression/ -v` backend regression commands.
- Backend and frontend autonomous queue validators now enforce the command
  clarity and the approved cap posture.

Status:

- Findings remediated in the active change set. Live Coinbase execution: not
  run; notional `$0`.

## Route Coverage Sync Review - Phases 521-540

Review scope:

- `C:\coinbase`
- `C:\coinbase-frontend`
- No chat history supplied to reviewer.

Reviewer tasks:

- Inspect whether `GET /api/v1/admin/oidc-readiness` is discoverable from
  backend OpenAPI/route inventory and frontend contract paths, typed wrapper,
  mock backend, runtime snapshot, UI evidence, docs, and checks.
- Inspect whether the active autonomous queue range `521-540`, no-live
  default, and carried-forward live Coinbase caps are clear.
- Confirm whether live Coinbase execution was run based only on repo evidence.
- Do not edit files.

Findings:

- No blocker. The reviewer found the route discoverable end to end from the
  backend route, route inventory, OpenAPI, sync regression test, frontend
  contract path, typed wrapper, mock fixture, runtime snapshot, UI evidence,
  route coverage check, package script, and docs.
- Low evidence-packaging gap: saved frontend runtime/UI artifacts are not
  obvious under `artifacts/` or `test-results/`. Existing source-level UI
  evidence and runtime tests cover the route; this is not a route-sync blocker.
- The active queue range `521-540` and no-live/cap posture are clear in both
  repos and enforced by the queue validators.
- Repository evidence includes the earlier approved live Coinbase canary
  against `MOG-USDC` from phase 478, but this route-sync batch did not run live
  Coinbase execution.

Status:

- No blocker. Live Coinbase execution was not run in this batch; notional `$0`.

## OIDC Release Readiness Closure Review - Phases 491-500

Review scope:

- `C:\coinbase`
- `C:\coinbase-frontend`
- No chat history supplied to reviewers.

Reviewer tasks:

- explain backend OIDC readiness proof and no-live smoke command
- verify frontend release artifacts include OIDC smoke evidence
- verify CI uploads release artifacts only after OIDC smoke and e2e pass
- verify production BFF fails closed without `backend_oidc_jwt` and verifier
  readiness evidence
- verify frontend release/smoke gates run no live Coinbase execution
- confirm the frontend cannot directly create or cancel spot orders

Findings:

- First blind review failed the batch because Node release artifact generation
  omitted `npm run smoke:oidc:dry`, CI uploaded artifacts before OIDC smoke,
  and production auth validation was split enough to mislead a contextless
  maintainer.
- Remediation centralized release command and CI-step evidence in
  `src/shared/quality/artifactContract.json`, moved CI artifact upload after
  OIDC smoke and e2e, and made production BFF config fail closed unless
  `backend_oidc_jwt`, `ADMIN_API_BACKEND_OIDC_VERIFIER_READY=true`, and an
  explicit OIDC cookie name are configured.
- Second blind review passed. It found no blocking documentation, code, or
  security gaps after remediation.

Status:

- Findings resolved. Backend OIDC readiness smoke and frontend OIDC dry smoke
  are no-live checks. Live Coinbase execution was not run in this batch;
  notional `$0`.

## OIDC Bridge And Live Canary Review - Phases 471-490

Review scope:

- `C:\coinbase`
- `C:\coinbase-frontend`
- No chat history supplied to reviewers.

Reviewer tasks:

- explain the frontend-to-backend spot order flow without inventing frontend
  trading behavior
- review Admin API OIDC/JWT verifier, frontend BFF OIDC session bridge, and
  production readiness evidence
- review live Coinbase USDC spot smoke auditability
- surface stale docs or contract drift

Findings:

- Spot-order flow passed. The frontend cannot create a live Coinbase spot
  order today; it can dry-submit through the HTTP Admin API/BFF path and
  display backend `501` live-disabled command evidence.
- OIDC/BFF forwarding passed. `backend_oidc_jwt` mode forwards only the
  configured OIDC cookie value as backend Bearer authority and does not trust
  browser actor/role headers.
- Live Coinbase canary evidence was auditable: `MOG-USDC`, submitted
  `3.09020044` USDC, executed `0.99935033` USDC, retained `9085003` MOG,
  fetched/appended `1` fill, and passed reconciliation.
- Review findings requiring fixes:
  - OpenAPI marked `X-Admin-Actor` and `X-Admin-Roles` globally required even
    though OIDC derives actor/roles from JWT claims.
  - Backend docs still described OIDC as future-only.
  - Frontend production readiness needed backend evidence beyond a manual
    boolean.
  - The frontend spot-order flow doc omitted `npm run release:gate` and full
    backend regression guidance.

Resolution:

- Regenerated backend OpenAPI and frontend generated schema.
- Updated OpenAPI customization and tests so `Authorization` is required while
  bootstrap actor/role headers are optional and documented as bootstrap-only.
- Added `GET /api/v1/admin/oidc-readiness`, `AdminOidcJwtReadinessResponse`,
  route inventory entry, OpenAPI schema, docs, and tests.
- Updated backend/frontend docs and frontend readiness artifacts to reference
  backend `/api/v1/admin/oidc-readiness` evidence.
- Updated frontend spot-order flow proof commands.

Status:

- Findings resolved. Focused Admin API contract tests passed with `35 passed`;
  focused frontend BFF/readiness tests passed with `26 passed`; frontend
  `api:check`, release check, deployment check, and typecheck passed.
  Frontend `npm run release:gate` passed with no live Coinbase execution and
  frontend notional `$0`. Backend full regression passed with `769 passed,
  1 warning`.
  Live Coinbase execution did run for the backend canary above with submitted
  notional `3.09020044` USDC and executed notional `0.99935033` USDC.

## Release Hardening Review - Phases 391-410

Review scope:

- `C:\coinbase`
- `C:\coinbase-frontend`
- No chat history supplied to reviewer.

Reviewer task:

- identify frontend release-readiness commands
- identify machine-readable release evidence
- verify BFF mode keeps backend bearer tokens server-only
- verify BFF smoke command-route expectations
- identify backend regression responsibility
- surface confusing docs/code likely to imply live Coinbase execution is
  approved

Findings:

- Release commands were discoverable: frontend quality pieces, release check,
  dry read smoke, dry command smoke, dry BFF smoke, and Playwright.
- Machine-readable frontend evidence lives in
  `src/shared/quality/releaseReadiness.ts` and is checked by
  `scripts/check-release-readiness.mjs`.
- BFF mode was clear: browser calls same-origin `/api/admin`, and server-only
  `ADMIN_API_*` variables supply backend authority.
- BFF smoke command routes expect backend `501` live-disabled responses,
  `x-live-execution-enabled=false`, and `live_exchange_submitted=false`.
- Backend regression remains required when backend files change.
- Clarity gaps found:
  - frontend agent/root README docs omitted some release/dry-smoke checks
  - frontend admin README omitted `smoke:bff:dry`
  - backend live testing docs could be skimmed as frontend release approval

Resolution:

- Updated frontend AGENTS and README docs to include release-aware checks and
  dry-smoke commands.
- Updated backend live-surface and external-testing docs to explicitly separate
  frontend dry/no-live release checks from manually approved live smoke tools.

Status:

- Findings resolved. No live Coinbase execution was run. Notional `$0`.

## Release Candidate Parity Review - Phases 561-580

Review scope:

- `C:\coinbase`
- `C:\coinbase-frontend`
- No chat history supplied to reviewers.

Reviewer tasks:

- identify the current approved autonomous phase range and live cap posture
- identify the canonical frontend release-candidate gate
- verify saved runtime/UI evidence is documented for release candidates
- verify backend public docs and examples do not publish stale frontend smoke
  subsets as the release gate
- verify docs make clear that frontend release artifacts are no-live evidence,
  not approval for live Coinbase execution

Findings:

- First blind review failed the batch because backend
  `docs/PUBLIC_RELEASE_READINESS.md` and `docs/FRONTEND_ASSOCIATION.md`
  still described a stale frontend release-gate subset and omitted
  `artifacts/runtime-evidence.json`.
- Remediation updated those backend docs to point to canonical
  `npm run release:gate`, include runtime evidence, reference the autonomous
  queue, and preserve no-live `$0` posture.
- Follow-up blind review failed the batch because `README.admin-api.md` and
  `docs/examples/admin-api.md` still published the old narrower frontend
  smoke/check sequence.
- Second remediation updated the admin API README and example docs, then
  widened the backend autonomous queue sentinel to require release-gate,
  runtime-evidence, autonomous-queue, artifact-path, `$0` notional, and
  non-approval-for-live-execution language in all backend frontend-release
  references.
- Final blind review passed with no blockers and no non-blocking concerns.

Status:

- Findings resolved. Frontend release-candidate docs, backend public admin
  docs, release/deployment sentinels, and autonomous queue checks align on
  `npm run release:gate`, `artifacts/runtime-evidence.json`, active phases
  `561-580`, and no-live evidence. Live Coinbase execution was not run in this
  batch; notional `$0`.

## Command Draft UX Review - Phases 581-600

Review scope:

- `C:\coinbase-frontend`
- Backend queue and Admin API roadmap references in `C:\coinbase`
- No chat history supplied to reviewers.

Reviewer tasks:

- explain how a contextless operator drafts manual order, cancel, and campaign
  commands without frontend trading behavior
- verify draft validation and payload mapping are discoverable
- verify dry-submit helpers use canonical `BackendApiClient` wrappers
- verify BFF/OIDC mode does not rely on browser-supplied actor or role
  authority
- verify cancel remains keyed only by `client_order_id`
- verify live Coinbase execution remains disabled/no-live

Findings:

- First blind review failed the batch because frontend docs overstated UI
  dry-submit: the shell renders draft/review controls and blocked/submitted
  evidence, but no UI button calls `drySubmitManualOrder`,
  `drySubmitCancelOrder`, or `drySubmitSpotCampaign`.
- The same review found that `time_in_force` existed in the draft model and
  backend payload mapping but was not exposed in the UI or documented clearly.
- The same review found bad copy-paste examples in smoke/test payloads:
  campaign payloads used `dry_run=false`, and one backend wrapper test used
  `manual_live_acknowledgement=true`.

Resolution:

- Updated frontend command and spot-order-flow docs to state that UI buttons
  remain disabled and do not call dry-submit helpers today; dry-submit helpers
  are for tests, smoke scripts, and future explicitly approved UI enablement.
- Added the manual `time_in_force` select, documented draft fields, and covered
  its payload mapping with unit and browser-facing tests.
- Corrected command smoke, BFF smoke, and backend wrapper tests to use
  `dry_run=true` and `manual_live_acknowledgement=false`.
- Clamped campaign payload building to `dry_run=true` so direct builder use
  cannot produce a frontend campaign live-execution payload.

Status:

- Follow-up blind review found no blockers. Live Coinbase execution was not
  run in this batch; notional `$0`.

## Admin Navigation Review - Phases 601-620

Review scope:

- `C:\coinbase-frontend`
- Backend queue and Admin API roadmap references in `C:\coinbase`
- No chat history supplied to reviewers.

Reviewer tasks:

- identify the approved autonomous phase range and live cap posture
- verify admin shell navigation is discoverable from contextless docs
- verify section links are real anchors for overview, spot operations, orders,
  campaigns, audit, settings, and admin evidence
- verify unavailable backend capability posture does not disable section links
- verify desktop and mobile Playwright coverage exercises the anchors
- verify no frontend path implies Coinbase execution authority

Findings:

- First blind review failed the batch because Playwright only clicked Orders
  and Admin on desktop, checked Admin on mobile, and did not exercise all
  seven section anchors on both viewport sizes while docs claimed stable
  anchor coverage for every section.
- The same review found two non-blocking clarity issues: the header Audit
  button was dead UI, and the frontend live-action gate helper could be read
  as trading authority if taken out of context.

Resolution:

- Expanded frontend Playwright coverage with a shared navigation target matrix
  that clicks Overview, Spot Operations, Orders, Campaigns, Audit, Settings,
  and Admin on both desktop and mobile, then verifies the expected named
  region for each target.
- Converted the frontend header Audit control to a real `#audit` link with a
  distinct accessible name.
- Clarified the frontend live-action gate helper, its unit test, and command
  workflow docs so a true gate result is described as a UI affordance signal
  only, never authority to submit a Coinbase order without backend acceptance.
- Updated frontend nav `aria-current` to follow the active hash section and
  covered the hydrated active-state behavior in unit tests after the follow-up
  review flagged the static Overview current state as misleading. Playwright
  remains focused on clickability, URL hashes, and visible region targets.

Status:

- Follow-up blind review found no blockers. The remaining accessibility
  concern was remediated. Live Coinbase execution was not run in this
  remediation; notional `$0`.

## Read Model Interaction Review - Phases 621-640

Review scope:

- `C:\coinbase-frontend`
- `C:\coinbase`
- No chat history supplied to reviewers.

Reviewer tasks:

- determine whether a contextless maintainer can understand the current
  frontend read-model interactions without inventing frontend trading behavior
- explain the future spot order creation path from the frontend using repo
  docs/code only
- identify backend Admin API path, service boundary, auth/RBAC/idempotency,
  audit evidence, live-disabled posture, `client_order_id` identity, cancel
  behavior, and required gates

Findings:

- Read-model review passed with no blockers. The reviewer found frontend and
  backend docs aligned on display-only filtering, sorting, detail selection,
  audit anchors, campaign tabs, diagnostics, empty/error states, responsive
  scrolling, and no Coinbase execution authority.
- Spot-order path was discoverable:
  `CommandWorkflowShell` -> `commandDrySubmit.ts` ->
  `BackendApiClient.createManualOrder` -> backend `POST /api/v1/orders` ->
  `AdminApiCommandService.place_manual_order`.
- Intentional current blockers were clear: frontend command buttons remain
  disabled, UI buttons do not call dry-submit helpers, and backend HTTP
  command routes return live-disabled `501` until approval/cap/audit/live HTTP
  gates are completed.
- Remediation items accepted:
  - clarify current frontend command draft scope as crypto-USDC spot pairs
  - clarify disabled command review wording
  - surface backend-derived live Coinbase evidence in frontend dry-submit
    results instead of hardcoding false for submitted responses
  - enforce a frontend BFF Admin API route allowlist before forwarding
  - rename a shortened frontend example gate that was labelled as a full gate

Resolution:

- Frontend code/docs were updated for BFF route allowlisting,
  backend-derived live evidence, disabled command review copy, USDC draft
  scope, and focused-gate wording.
- Backend association docs now mirror that the frontend BFF allowlist is a
  transport control and that current browser draft scope remains crypto-USDC
  until backend contracts/tests define a broader scope.

Status:

- Findings resolved. Focused frontend remediation and read-model verification
  checks passed, including BFF proxy/route, dry-submit, command shell, admin
  shell, read-model, spot read-only, accessibility, command-fetch guard, API
  route coverage, deployment/autonomous sentinels, and admin-shell Playwright
  smoke. Live Coinbase execution was not run; notional `$0`.

## M1 Stealth Orders Read Module Review

Review scope:

- `C:\coinbase`
- `C:\coinbase-frontend`
- No chat history supplied to reviewers.

Reviewer tasks:

- verify the Stealth Orders Admin API/frontend module is read-only and
  backend-contract-first
- verify stealth identity is `stealth_order_id`
- verify active placement client ids and exchange ids are evidence only
- verify the frontend does not add stealth lifecycle/trading behavior
- verify spot-only wallet, USDC, cost-basis, average-cost, and no-shorting
  rules do not leak into the stealth module
- verify the OpenAPI -> generated client -> `BackendApiClient` ->
  mock/runtime -> UI path is understandable

Findings:

- First blind review found an active-placement evidence blocker:
  `AdminApiReadService` promoted the latest historical `revealed_orders`
  placement and exchange ids into `active_*` fields when active anchor state
  was absent.
- First blind review also found that the backend capability matrix still
  described the frontend Stealth Orders module as pending.
- Second blind review found the active-evidence fix sound but flagged a matrix
  shape mismatch: backend columns used different names than the frontend
  matrix and placed frontend-module status outside the read-only column.

Resolution:

- Removed the historical `revealed_orders` fallback for
  `active_placement_client_order_id` and `active_exchange_order_id`.
- Added regression coverage proving historical reveal evidence is preserved
  but terminal/cleared-anchor rows return `active_* = None`.
- Updated backend and frontend capability matrices so Stealth Orders read-only
  views are implemented, command drafts and dry-submit are not modeled, and
  live execution is not approved through the frontend.
- Added frontend read-only Stealth Orders wrappers, mock fixtures, BFF
  allowlist entries, runtime snapshot loading, route coverage metadata, UI,
  docs, examples, and ownership mapping.

Status:

- Final blind review found no blockers.
- Backend `pytest tests\regression\ -v --tb=short` passed with `775 passed,
  1 warning`.
- Frontend `npm run release:gate` passed after remediation, including build,
  typecheck, lint, API freshness/route coverage, command guard, artifacts,
  dry smokes, unit tests, and Playwright e2e.
- Live Coinbase execution was not run; notional `$0`.

## M2 Movement/Repricing Read Module Review

Review scope:

- `C:\coinbase`
- `C:\coinbase-frontend`
- No chat history supplied to reviewers.

Reviewer tasks:

- verify movement/repricing Admin API and frontend modules are read-only and
  backend-contract-first
- verify routes expose movement, replacement-slot, mutation-claim, and
  repricing evidence without command authority
- verify `client_order_id` and `stealth_order_id` remain the identity keys and
  exchange ids remain evidence only
- verify stealth exchange-reality and flat hierarchy rules are preserved
- verify frontend generated schema, wrappers, BFF allowlist, mocks, runtime,
  UI, docs, tests, and artifacts are understandable to contextless maintainers

Findings:

- Backend blind review found no blockers. It confirmed the three
  movement/repricing routes are `GET` only, `audit:read` gated, delegated to
  `AdminApiReadService`, and represented in route inventory/OpenAPI.
- Backend blind review confirmed movement/repricing reads use durable local
  evidence and runtime-safe claim evidence without creating a parallel move or
  reprice lifecycle path.
- Backend blind review confirmed exchange ids are named evidence fields and
  are not used as tracking identity.
- Backend blind review made a non-blocking hardening suggestion: if pending
  replacement claims exist but `orderbook_lock` is unavailable, mark runtime
  claims unobserved instead of reading the mutable set.
- Frontend blind review found no blockers. It confirmed generated schema,
  contract paths, canonical GET wrappers, BFF GET allowlist, mock fixtures,
  runtime loading, read-only UI, row links, docs, and tests are aligned.
- Frontend blind review found no executable move/reprice behavior, no
  spot-only wallet/cost-basis/no-shorting leakage, and no exchange-id identity
  misuse.

Resolution:

- Applied the backend hardening suggestion so pending replacement claims are
  observed only under the existing order engine lock.
- Recorded M2 as complete in backend and frontend durable milestone docs.

Status:

- Focused backend Admin API contract tests passed with `42 passed`.
- Backend full regression passed with `777 passed, 1 warning`.
- Frontend focused M2 test set passed with `74 passed`; full unit suite
  passed with `148 passed`; Playwright e2e passed with `3 passed`.
- Frontend `npm run release:gate` passed and reported no live Coinbase
  execution.
- Live Coinbase execution was not run for M2; notional `$0`.

## M3 Futures/Perpetuals Read Module Review

Review scope:

- `C:\coinbase`
- `C:\coinbase-frontend`
- No chat history supplied to reviewers.

Reviewer tasks:

- verify futures/perpetuals are M3 under the M0 platform pivot baseline, not a
  spot variant
- verify futures/perpetual Admin API routes are read-only, backend-owned, and
  delegated through the single Admin API/read-service path
- verify wallet/no-shorting, USDC-only, average-cost, cost-basis, and spot
  inventory authority rules do not leak into futures/perpetuals
- verify dashboard fallback filtering does not promote unknown/non-futures
  rows into futures positions
- verify frontend generated schema, wrappers, BFF allowlist, mocks, runtime,
  UI, docs, tests, and artifacts are understandable to contextless maintainers

Findings:

- Backend blind review found no blockers. It confirmed the three futures/
  perpetuals routes are `GET` only, `analytics:read` gated, delegated to
  `AdminApiReadService`, and represented in route inventory/OpenAPI.
- Backend blind review confirmed futures/perpetuals use position-domain
  identity, product type, position side, margin/liquidation/P/L evidence, and
  no `client_order_id`, `order_id`, or cost-basis schema fields.
- Backend blind review confirmed dashboard fallback filtering rejects unknown
  spot-like rows unless metadata or explicit product-type evidence proves the
  row is futures.
- Frontend blind review found no blockers. It confirmed generated schema,
  canonical wrappers, BFF allowlist, mock fixtures, runtime snapshot, read-only
  UI, route coverage, docs, examples, and tests are aligned.
- Frontend blind review confirmed account, positions, and selected detail
  route failures are detected before adapters assume successful response
  shapes.
- Both reviews found only the expected closeout drift: M3 still said `Next`
  before this completion record was written.

Resolution:

- Remediated the earlier backend blocker by filtering dashboard fallback rows
  to known futures products or explicit futures product-type evidence.
- Added regression coverage proving an unknown `BTC-USDC` dashboard row is not
  promoted into futures positions.
- Remediated the earlier frontend blocker by checking all integrated futures
  responses for non-2xx status before read-model mapping.
- Added frontend regression coverage for rejected futures child responses.
- Recorded M3 as complete in backend and frontend durable milestone docs.

Status:

- Backend focused Admin API contract tests passed with `45 passed, 1 warning`.
- Backend full regression passed with `780 passed, 1 warning`.
- Frontend final blind-review focused checks passed with `44` tests.
- Frontend `npm run release:gate` passed with `153` unit tests and `3`
  Playwright tests.
- Blind/contextless backend and frontend reviews found no blockers.
- Live Coinbase execution was not run for M3; notional `$0`.

## M5 Cross-Module Audit Workbench Review

Review scope:

- `C:\coinbase`
- `C:\coinbase-frontend`
- No chat history supplied to reviewers.

Reviewer tasks:

- verify the audit workbench has a canonical backend route and frontend
  wrapper
- verify the route is read-only/evidence-only and does not read or mutate
  Coinbase state
- verify `client_order_id`, `stealth_order_id`, and `position_key` identity
  boundaries remain clear and exchange ids are evidence only
- verify backend route inventory, OpenAPI, models, route, read service,
  frontend generated contract, client wrapper, BFF allowlist, mock/runtime,
  UI, docs, and tests are aligned
- identify stale wording likely to cause a contextless agent to invent a
  parallel command path, copy spot-only logic, or track by exchange `order_id`

Findings:

- Initial blind review found two blockers.
- Backend audit filtering could drop movement/repricing evidence when the
  requested `client_order_id` matched `new_parent_client_order_id`,
  `old_placement_client_order_id`, `new_placement_client_order_id`, or
  `active_placement_client_order_id` instead of the normalized display
  `client_order_id`.
- Frontend mock audit workbench reads echoed query filters but did not filter
  or paginate events, which could mask backend behavior in local tests.
- The reviewer also flagged ambiguous campaign wording: campaign workbench
  evidence currently means route summaries and command-audit rows, not a
  separate campaign-status aggregation.
- The reviewer found no doc drift toward a parallel command path, spot-only
  generic logic, or exchange-id tracking beyond those blockers.

Resolution:

- Backend audit workbench filtering now checks movement/repricing client id
  aliases from raw evidence while preserving the normalized public event
  identity.
- Added backend regression coverage for movement/repricing alias filtering.
- Frontend mock audit workbench reads now apply module/product/client/
  correlation/audit filters and pagination before returning fixture events.
- Added frontend tests proving filtered results and offset pagination.
- Clarified backend and frontend docs that campaign workbench evidence is
  route/command-audit scope; campaign-status aggregation remains in the spot
  campaign read route.
- Follow-up blind review found no blockers.

Status:

- Backend focused Admin API contract tests passed with `51 passed, 1 warning`.
- Backend full regression passed with `786 passed, 1 warning`.
- Frontend focused audit workbench/client/runtime/mock/BFF/AdminShell checks
  passed with `75 passed`.
- Frontend `npm run release:gate` passed with `161` unit tests and `3`
  Playwright tests.
- Live Coinbase execution was not run for M5; notional `$0`.

## M6 Live-Disabled Stealth Cancel Review

Review scope:

- `C:\coinbase`
- `C:\coinbase-frontend`
- No chat history supplied to reviewers.

Reviewer tasks:

- verify `POST /api/v1/stealth/orders/{stealth_order_id}/cancel` is
  authenticated, RBAC-gated, idempotent, audited, live-disabled, and routed
  through the shared command service
- verify the command identity is `stealth_order_id`; active placement client
  ids and exchange `order_id` values remain evidence only
- verify generated OpenAPI, route inventory, docs, tests, frontend generated
  schema, wrappers, BFF allowlist, command draft, dry-submit helper, admin
  navigation, and release gates are aligned
- verify no Coinbase execution path, stealth manager mutation, spot-only
  authority, or browser-local command fetch path was introduced

Findings:

- Initial backend blind review found one blocker: same-key/different-payload
  idempotency conflicts for stealth cancel returned and audited a `409`
  response without preserving `stealth_order_id`.
- The same review found two non-blocking gaps: the no-direct-Coinbase route
  guard scanned `api.v1.routes.orders` but not `api.v1.routes.stealth`, and a
  generic cancel example used a stealth-specific reason string.
- Frontend blind review found no blockers. It flagged one stale doc sentence
  that omitted stealth cancel from the browser smoke description.

Resolution:

- The shared idempotent command executor now accepts route identity fields and
  preserves `stealth_order_id` or `client_order_id` in idempotency-conflict
  responses and audit rows.
- Added regression coverage for stealth cancel payload-drift conflict response
  and audit identity.
- The no-direct-Coinbase route guard now scans both order and stealth route
  modules.
- Backend and frontend example wording was corrected.
- Follow-up backend blind review found no blockers and independently probed
  the conflict case.

Status:

- Backend focused Admin API contract tests passed with `52 passed, 1 warning`.
- Backend full regression passed with `787 passed, 1 warning`.
- Frontend focused command/AdminShell checks passed with `17 passed`.
- Frontend `npm run release:gate` passed with `165` unit tests and `3`
  Playwright tests.
- Frontend blind review focused checks passed with `75` tests.
- Live Coinbase execution was not run for M6; notional `$0`.

## M6 Live-Disabled Movement Reprice Review

Review scope:

- `C:\coinbase`
- `C:\coinbase-frontend`
- No chat history supplied to reviewers.

Reviewer tasks:

- verify `POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice`
  is authenticated, RBAC-gated, idempotent, audited, live-disabled, and routed
  through the shared command service
- verify the command identity is the path `stealth_order_id`; body
  `client_order_id`, Coinbase `order_id`, active placement ids, cooldown
  controls, and dashboard repricer controls are not accepted
- verify operator intent is durable command audit evidence and part of the
  idempotency payload hash
- verify generated OpenAPI, route inventory, docs, tests, frontend generated
  schema, wrappers, BFF allowlist, command draft, dry-submit helper, admin
  navigation, and release gates are aligned
- verify no Coinbase execution path, cooldown clearing, dashboard repricer
  invocation, live placement cancellation, or browser-local command fetch path
  was introduced

Findings:

- Initial backend blind review found the command was fail-closed and keyed by
  `stealth_order_id`, but flagged blocker-level ambiguity: the movement route
  module docstring still said read-only, `X-Operator-Intent` was not persisted
  in command audit/idempotency evidence, and docs could let a smaller agent
  believe `allow_live_execution` or a legacy dashboard repricer path enabled
  this route.
- Initial frontend blind review found the wrapper, body shape, disabled UI, and
  no-live posture were correct, but flagged docs that omitted stealth cancel
  and movement reprice from the current `501` command list and could confuse
  helper dry-submit with a payload-level `dry_run` field.
- Follow-up frontend blind review then found two stale docs blockers:
  `docs/ADMIN_MODULE_CAPABILITY_MATRIX.md` still called movement/repricing
  command drafts and dry-submit not modeled, and `docs/STEALTH_ORDER_READS.md`
  still said reprice commands were absent from the enterprise frontend.

Resolution:

- Changed the movement route module docstring to cover read routes plus
  live-disabled command routes.
- Added `operator_intent` to durable Admin API command audit events, the shared
  idempotency payload hash, and normalized audit-workbench event output.
- Added regression coverage for operator-intent audit persistence and
  same-key changed-intent conflicts, including movement reprice.
- Regenerated `openapi/coinbase-admin-api.yaml` and the frontend generated
  TypeScript schema.
- Updated backend Admin API, examples, agent contract, E2E plan, and local
  expanded API reference docs.
- Updated frontend API/command docs so dry-submit is described as a
  helper/smoke path, not a universal `dry_run` body field.
- Updated the frontend capability matrix and stealth reads docs to point
  movement reprice to the Order Movement / Repricing module as a disabled
  `stealth_order_id` command draft.
- Follow-up backend and frontend blind reviews found no blockers.

Status:

- Backend focused Admin API contract tests passed with `54 passed, 1 warning`.
- Backend full regression passed with `789 passed, 1 warning`.
- Frontend focused movement/command/quality checks passed with `44` tests.
- Frontend `npm run release:gate` passed with `169` unit tests and `3`
  Playwright tests.
- Live Coinbase execution was not run for movement reprice; notional `$0`.
