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
