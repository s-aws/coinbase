# Admin Platform Durable Milestones

This plan defines completion-oriented milestones for the enterprise admin
platform across the whole Coinbase trading engine. It is not a spot roadmap.
Spot remains the first complete product module and the proving ground for the
platform pattern, but future modules must define their own backend-owned
contracts and risk semantics.

## Completion Model

A milestone is complete only when all of these are true:

- Backend-owned contracts, docs, and examples describe the module without
  relying on chat history.
- `docs/ADMIN_MODULE_CAPABILITY_MATRIX.md` accurately reflects the module
  status.
- OpenAPI and generated frontend clients are updated when routes change.
- Tests cover the contract or UI behavior that the milestone claims.
- Required gates pass: focused Admin API tests, backend regression when
  behavior changes, frontend `npm run release:gate` when consumed, and
  blind/contextless review for non-spot or live-action broadening.
- Final evidence states whether live Coinbase execution ran. Default is
  no-live with notional `$0`.

Do not mark a milestone complete because the docs exist. Completion requires
working contract, test, gate, and review evidence for the claimed scope.

## Milestone Status

| Milestone | Status | Purpose |
| --- | --- | --- |
| M0 - Platform Pivot Baseline | Complete | Reframe admin as whole-project platform with Spot as first complete module. |
| M1 - First Non-Spot Read Module | Complete | Add a backend-owned read-only Stealth Orders Admin API/frontend module. |
| M2 - Movement And Repricing Reads | Complete | Add read-only movement/repricing evidence without command authority. |
| M3 - Futures/Perpetuals Read Foundation | Complete | Add futures/perpetual account, position, funding, and risk read contracts. |
| M4 - Guard And Risk Policy Evidence | Complete | Expose backend guard/risk decisions as read-only evidence across modules. |
| M5 - Cross-Module Audit Workbench | Complete | Unify operator audit, reconciliation, and correlation evidence across modules. |
| M6 - Non-Spot Command Draft Contracts | Complete | Add disabled drafts/dry-submit contracts only after read contracts are stable. |
| M7 - Production Auth And Operations Hardening | Complete | Finish enterprise auth, deployment, observability, and operator runbooks. |
| M8 - Controlled Live Enablement | Readiness prep complete; live execution pending | Enable live execution only per approved backend path, cap, and reconciliation gate. |
| M9 - Enterprise Release Candidate | Evidence complete | Prove the whole admin platform with release, security, contextless, and regression gates. |
| M10 - Public Maintainer Handoff | Complete | Make onboarding, contribution, and contextless-agent operation durable. |
| M11 - Read-Only Module Onboarding Proof | Active | Prove the handoff playbook with release, spot/direct-order recovery, and fill-ledger health reads. |

## M0 - Platform Pivot Baseline

Purpose: establish the platform/module boundary.

Completed evidence:

- Backend and frontend `docs/ADMIN_PLATFORM_ARCHITECTURE.md`.
- Backend and frontend `docs/ADMIN_MODULE_CAPABILITY_MATRIX.md`.
- Contextless review logs record the platform pivot and remediation.
- Spot is documented as first complete module, not the generic model.
- Backend Admin API is documented as current live-disabled contract, not
  merely planned future work.
- Backend `python tools\check_ownership.py --owner architect` passed for the
  M0 milestone docs.
- Frontend `npm run release:gate` passed after the final M0 remediation with
  no live Coinbase execution and notional `$0`.

## M1 - First Non-Spot Read Module

Purpose: prove the platform can host a non-spot module without copying spot
rules. The preferred first module is Stealth Orders because legacy dashboard
functionality exists and carries strict exchange-reality invariants.

Backend scope:

- Add read-only Admin API routes for stealth order summary/detail evidence.
- Define response models with identity fields, active placement evidence,
  exchange evidence, visibility state, policy state, and audit/correlation
  fields.
- Keep all routes read-only; no create, cancel, move, reprice, hide, reveal,
  or live Coinbase behavior.
- Reuse existing stealth lifecycle/read sources. Do not duplicate state
  machines or bypass locks.
- Update OpenAPI, route inventory, examples, architecture docs, and capability
  matrix.

Frontend scope:

- Regenerate generated client from backend OpenAPI.
- Add canonical `BackendApiClient` wrapper methods and BFF allowlist coverage.
- Add read-only Stealth Orders module UI that displays backend-shaped evidence.
- Keep command buttons absent or disabled until M6.

Done when:

- Focused Admin API contract tests prove the read routes and no-live posture.
- Backend regression passes if behavior/source code changed.
- Frontend API coverage, unit tests, and `npm run release:gate` pass after
  consuming the routes.
- A blind/contextless review can explain stealth identity, placement evidence,
  exchange-reality rules, and why no frontend trading path exists.
- Live Coinbase execution is not run; notional `$0`.

Completed evidence:

- Backend read-only stealth list/detail routes, OpenAPI, route inventory,
  examples, and architecture docs are implemented.
- `AdminApiReadService` maps active placement/exchange evidence only from
  active anchor state and preserves historical `revealed_orders` as historical
  evidence.
- Frontend generated schema, canonical `BackendApiClient` wrappers, BFF
  allowlist, mock fixtures, runtime snapshot, read-only UI, docs, and route
  coverage are implemented.
- Backend `pytest tests\regression\ -v --tb=short` passed with `775 passed,
  1 warning`.
- Frontend `npm run release:gate` passed after remediation, including build,
  typecheck, lint, API freshness/route coverage, command guard, artifacts,
  dry smokes, unit tests, and Playwright e2e.
- Blind/contextless review initially found active placement evidence and
  matrix-shape blockers; both were remediated. Final blind review found no
  blockers.
- Live Coinbase execution was not run; notional `$0`.

## M2 - Movement And Repricing Reads

Purpose: make order movement and repricing inspectable before any command UI.

Backend scope:

- Add read-only movement/repricing route contracts over existing evidence.
- Expose mutation claims, replacement slots, move history, reprice policy
  state, and exchange evidence without allowing mutation.
- Preserve flat hierarchy and revealed-placement exchange truth.

Frontend scope:

- Add read-only movement/repricing views linked from order and stealth rows.
- Keep move/reprice actions disabled or absent.

Done when focused tests, frontend release gate, backend regression when
required, and contextless review prove movement/repricing is inspectable but
not executable through the frontend.

Completed evidence:

- Backend read-only movement/repricing routes, response models, route
  inventory, OpenAPI, examples, feature README, and expanded API/architecture
  docs are implemented.
- `AdminApiReadService` maps durable `order_moves`,
  `stealth_order_moves`, stealth anchor repricing state, runtime mutation
  claims, and replacement-slot evidence without creating command authority.
- Runtime replacement claims are observed only when the existing order engine
  lock is available; otherwise they are reported as unobserved.
- Frontend generated schema, canonical `BackendApiClient` wrappers, BFF
  allowlist, mock fixtures, runtime snapshot, read-only UI, row links, docs,
  quality artifacts, and route coverage are implemented.
- Backend `pytest tests\regression\ -v --tb=short` passed with `777 passed,
  1 warning`.
- Frontend `npm run release:gate` passed with build, typecheck, lint, API
  freshness/route coverage, command guard, release/deployment/runtime
  artifacts, dry smokes, unit tests, and Playwright e2e.
- Blind/contextless backend and frontend reviews found no blockers. A
  backend hardening note about reading pending replacement claims without a
  lock was remediated.
- Live Coinbase execution was not run for M2; notional `$0`.

## M3 - Futures/Perpetuals Read Foundation

Purpose: introduce futures/perpetuals as a separate domain module, not a spot
variant.

Backend scope:

- Define read contracts for account, collateral, margin, position, funding,
  liquidation, reduce-only/close-only, and position P/L evidence.
- Define identity keys for positions and orders separately from spot
  `client_order_id` usage.
- Avoid wallet/no-shorting/cost-basis assumptions.

Frontend scope:

- Render futures/perpetuals read models only after backend contracts exist.
- Keep all command drafting disabled until domain semantics are proven.

Done when a contextless reviewer can explain futures/perpetual-specific risk
semantics without using spot wallet or cost-basis rules.

Completed evidence:

- Backend read-only futures/perpetual account, position list, and position
  detail routes are implemented as `GET` Admin API routes delegated to
  `AdminApiReadService`; no command behavior was added.
- Futures/perpetual response models use position-domain identity,
  position-side, margin, liquidation, P/L, reduce-only/close-only, and funding
  evidence without spot wallet, no-shorting, USDC-only, average-cost, or
  cost-basis assumptions.
- Dashboard fallback filtering refuses unknown/non-futures rows unless product
  metadata or explicit product-type evidence proves the row is futures.
- OpenAPI, route inventory, capability matrix, feature README, examples,
  agent contract, expanded local API/architecture docs, ownership metadata,
  and regression tests are updated.
- Backend focused Admin API contract tests passed with `45 passed, 1 warning`;
  backend full regression passed with `780 passed, 1 warning`.
- Frontend generated schema, canonical wrappers, BFF allowlist, mock/runtime
  fixtures, read-only UI, docs, and release gate consume the backend contract.
- Blind/contextless backend and frontend reviews found no blockers after
  remediation of dashboard fallback filtering and partial-response rejection
  handling.
- Live Coinbase execution was not run for M3; notional `$0`.

## M4 - Guard And Risk Policy Evidence

Purpose: make backend authority visible without moving guard calculations into
the browser.

Backend scope:

- Add read contracts for guard policies, cap decisions, profitability checks,
  wallet/position authority sources, and rejection evidence.
- Link decisions to request ids, correlation ids, and audit ids.

Frontend scope:

- Display backend decisions and explanations as evidence only.
- Do not compute wallet, margin, profitability, cap, or approval authority in
  browser code.

Done when tests prove guard/risk evidence is rendered from backend responses
and contextless review finds no browser-trusted authority.

Completed evidence:

- Backend `GET /api/v1/admin/guard-risk-policy` is implemented as a
  read-only `analytics:read` route delegated to `AdminApiReadService`.
- Response models expose action-condition guard phases, configured limit
  rules, product capability policy decisions, live execution posture,
  profitability policy, authority sources, and rejection categories as
  evidence only.
- Capability decision evaluation now reports degraded/unavailable evidence if
  backend policy evaluation raises instead of silently presenting a clean
  observed status.
- OpenAPI, route inventory, capability matrix, feature README, examples,
  agent contract, expanded local API/architecture docs, ownership metadata,
  and regression tests are updated.
- Frontend generated schema, canonical `BackendApiClient` wrapper, BFF
  allowlist, mock/runtime fixtures, read-only UI, docs, and release gate
  consume the backend contract.
- Backend focused Admin API contract tests passed with `48 passed, 1 warning`;
  backend full regression passed with `783 passed, 1 warning`.
- Frontend focused guard/risk checks passed after wording remediation;
  frontend `npm run release:gate` passed with `157` unit tests and `3`
  Playwright tests.
- Blind/contextless backend and frontend reviews found no blockers. Backend
  review hardening around policy-evaluation errors was remediated. Frontend
  review wording risk around capability decisions was remediated.
- Live Coinbase execution was not run for M4; notional `$0`.

## M5 - Cross-Module Audit Workbench

Purpose: give operators one evidence surface across modules.

Backend scope:

- Normalize audit read contracts across admin, spot, stealth,
  movement/repricing, futures/perpetuals, and campaigns where available.
- Preserve `client_order_id` discipline for order identity and label exchange
  ids as evidence only.

Frontend scope:

- Add module-aware audit filtering, correlation links, and detail panels.
- Carry module/product scope into related evidence reads, including
  guard/risk policy `product_id` filters, without moving authority into the
  browser.
- Keep audit UI display-only.

Done when audit evidence can trace a command or read model across modules
without inventing a second command path.

Completed evidence:

- Backend `GET /api/v1/admin/audit-workbench` is implemented as a read-only
  `audit:read` route delegated to `AdminApiReadService`.
- Response models normalize route inventory, command audit events, order,
  stealth, movement/repricing, futures/perpetuals, guard/risk, and campaign
  route/command-audit evidence into one workbench.
- Identity remains module-specific: order evidence uses `client_order_id`,
  stealth evidence uses `stealth_order_id`, futures/perpetual evidence uses
  `position_key`, and exchange ids are normalized as evidence only.
- Backend filtering is alias-aware for movement/repricing evidence, including
  parent and placement client id aliases.
- OpenAPI, route inventory, capability matrix, feature README, examples,
  agent contract, expanded local API/architecture docs, ownership metadata,
  and regression tests are updated.
- Frontend generated schema, canonical `getAdminAuditWorkbench` wrapper, BFF
  allowlist, mock/runtime fixtures, read-only UI, route coverage, release
  artifacts, docs, and examples consume the backend contract.
- Frontend mock audit workbench reads now apply backend-like filters and
  pagination instead of only echoing query parameters.
- Initial blind/contextless review found two blockers: movement/repricing
  client alias filtering and frontend mock filtering/pagination. Both were
  remediated, and follow-up blind review found no blockers.
- Backend focused Admin API contract tests passed with `51 passed, 1 warning`;
  backend full regression passed with `786 passed, 1 warning`.
- Frontend focused audit workbench/client/runtime/mock/BFF/AdminShell checks
  passed with `75 passed`; frontend `npm run release:gate` passed with `161`
  unit tests and `3` Playwright tests.
- Live Coinbase execution was not run for M5; notional `$0`.

## M6 - Non-Spot Command Draft Contracts

Purpose: introduce operator intent capture for non-spot modules only after
read contracts and risk evidence are stable.

Backend scope:

- Add live-disabled command contracts for approved non-spot drafts.
- Route through auth/RBAC, idempotency, approval, cap, guard, audit, and the
  shared command service boundary.
- Return fail-closed responses until live approval is explicitly granted.

Frontend scope:

- Add disabled or review-only command drafts with backend-shaped dry-submit
  evidence.
- Show environment, actor, roles, caps, backend decision, and audit
  correlation.

Done when command paths are traceable through the single backend behavior path
and contextless review finds no parallel trading implementation.

Completed evidence:

- `stealth_cancel` is the first non-spot command draft contract.
- Backend route:
  `POST /api/v1/stealth/orders/{stealth_order_id}/cancel`.
- Shared service method:
  `cancel_stealth_order_by_stealth_order_id`.
- Identity key: `stealth_order_id`. Active placement client ids and exchange
  ids are evidence only.
- Current runtime posture: authenticated, RBAC-gated, idempotent, audited, and
  live-disabled with HTTP `501`; idempotency conflicts preserve
  `stealth_order_id` audit identity; live Coinbase execution not run,
  notional `$0`.
- `movement_reprice` is the second non-spot command draft contract.
- Backend route:
  `POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice`.
- Shared service method:
  `reprice_stealth_order_by_stealth_order_id`.
- Identity key: `stealth_order_id`. Active placement client ids and exchange
  ids are evidence only. The draft does not clear cooldowns, invoke the live
  dashboard repricer, cancel placements, or call Coinbase.
- Current runtime posture: authenticated, RBAC-gated, idempotent, audited, and
  live-disabled with HTTP `501`; idempotency conflicts preserve
  `stealth_order_id` audit identity; live Coinbase execution not run,
  notional `$0`.
- Command dry-submit evidence now preserves backend decision, service method,
  action class, required permission, failure stage, live exchange submission
  flag, operator intent, idempotency key, audit id, correlation id, and live
  Coinbase evidence.
- Frontend command drafts display backend route, backend-owned route evidence,
  identity key, live-enabled posture, audit evidence, and idempotency evidence
  for manual order, cancel, stealth cancel, movement reprice, and campaign
  execution drafts.
- Backend focused Admin API contract tests passed with `54 passed,
  1 warning`.
- Backend full regression passed with `789 passed, 1 warning`.
- Frontend focused command/auth contract tests passed with `72 passed`.
- Frontend `npm run security:commands` passed.
- Frontend `npm run release:gate` passed with `177` unit tests and `3`
  Playwright tests.
- Backend autonomous queue validation passed.
- Initial blind/contextless review found documentation/gate-evidence
  ambiguity and dry-submit wording ambiguity; remediation clarified
  movement reprice dry-submit and action-class semantics. Follow-up review
  found no remaining M6 blockers.
- Live Coinbase execution was not run for M6; notional `$0`.

## M7 - Production Auth And Operations Hardening

Purpose: make the platform deployable in a conventional enterprise setting.

Backend scope:

- Complete OIDC/JWT verifier behavior, role mapping, CSRF/CORS policy,
  structured errors, rate limits, and operational readiness routes.
- Document bootstrap-only local auth separately from production auth.

Frontend scope:

- Consume production auth/session evidence through the BFF boundary.
- Keep secrets server-only and browser-visible config non-sensitive.

Done when staging/prod readiness checks, release artifacts, deployment docs,
and contextless review prove production auth is not simulated by browser
headers.

Completed evidence:

- BFF mutation forwarding now rejects missing `Idempotency-Key`,
  `X-Correlation-Id`, or `X-Operator-Intent` before forwarding unsafe
  requests to the backend.
- BFF POST route coverage is set-equal to the backend-owned mutation
  contracts; undocumented command paths cannot be broadened through the BFF
  allowlist.
- OIDC/JWT cookie-backed unsafe requests require same-origin browser evidence
  from `Origin` or Fetch Metadata. Server-side CSRF token injection remains
  server-to-backend evidence only and is not treated as standalone browser
  CSRF protection.
- Command fetch guards reject direct frontend command-route `fetch` calls
  outside the canonical `BackendApiClient` and same-origin BFF route.
- Auth, deployment, observability, command-workflow, and human-operator
  runbook docs now describe server-only authority, OIDC cookie deployment
  settings, no-live release evidence, and BFF preflight behavior.
- Frontend focused auth/BFF tests passed with `72 passed` in the combined
  command/auth focused suite.
- Frontend `npm run release:gate` passed with `177` unit tests and `3`
  Playwright tests.
- Backend full regression passed with `789 passed, 1 warning`.
- Initial blind/contextless frontend review found a blocker: OIDC cookie mode
  could rely on server CSRF evidence without browser same-origin validation.
  The BFF boundary was remediated and follow-up blind review found no
  remaining blockers.
- Production OIDC cookie `SameSite`, `Secure`, and host/domain settings remain
  a deployment/auth-layer configuration requirement, documented in deployment
  and auth docs.
- Live Coinbase execution was not run for M7; notional `$0`.

## M8 - Controlled Live Enablement

Purpose: enable live execution only for specific backend-owned paths that have
passed cap, approval, audit, and reconciliation gates.

Rules:

- Live execution remains opt-in per module and per path.
- Each live test must state product, submitted notional, executed notional,
  retained inventory, and reconciliation result.
- Frontend gates remain no-live unless an explicit backend live phase says
  otherwise.
- No live enablement may skip M4 guard/risk evidence or M6 command contract
  proof for the path.

Current readiness prep:

- `GET /api/v1/admin/live-enablement` exposes read-only M8 evidence for
  command paths that could later be considered for controlled live enablement.
- The route reports the active phase range, carried USDC cap, product scope,
  submitted/executed notional `$0`, required approval, guard, audit, and
  reconciliation gates, and every current path as `live_enabled=false`.
- This route is not live approval and does not call Coinbase.
- Phases 661-680 completed this readiness prep. Backend and frontend gates
  passed, contextless review found no blockers after remediation, and live
  Coinbase execution was not run with submitted/executed notional `$0`.

Done when the approved live path has passing focused tests, full regression,
contextless review, live evidence under cap, and post-live reconciliation.

## M9 - Enterprise Release Candidate

Purpose: prove the admin platform is complete enough for controlled external
use.

Completed readiness work:

- Phases 681-700 add `GET /api/v1/admin/enterprise-readiness` as read-only
  M9 evidence for supported modules, unsupported actions, security posture,
  release-check posture, frontend authority, live posture, and no-live
  notional.
- M9 backend regression, frontend release gate, security/contextless review,
  and remediation completed with live Coinbase execution not run and notional
  `$0`.

Done when:

- Backend regression passes.
- Frontend `npm run release:gate` passes.
- Security review finds no browser authority, secret exposure, or command
  bypass.
- Contextless reviews for backend, frontend, and module onboarding find no
  blockers.
- Release notes state supported modules, unsupported modules, live posture,
  auth posture, and operational runbooks.

## M10 - Public Maintainer Handoff

Purpose: make the project sustainable without this chat.

Completed handoff work:

- Phases 701-720 add backend and frontend maintainer handoff guides, link them
  from ordered documentation entry points, validate they remain discoverable,
  and prove a contextless maintainer can follow the backend/frontend authority
  split without chat history.
- M10 backend regression, frontend release gate, autonomous validators, and
  contextless review completed with live Coinbase execution not run and
  notional `$0`.

Done when:

- Root READMEs stay concise and route readers to ordered docs.
- Feature docs, examples, route inventory, generated API rules, ownership
  maps, and contextless review logs are current.
- A fresh agent can add a small read-only module slice by following docs and
  passing gates without asking for hidden context.
- Historical roadmap notes do not contradict the current platform state.

## M11 - Read-Only Module Onboarding Proof

Purpose: prove the M10 handoff playbook by onboarding a small backend-owned
read-only module slice end to end.

Completion evidence:

- Phases 721-740 load existing backend release-gate, recovery-gate, and
  fill-ledger-health reads through the frontend runtime snapshot and display
  them as backend-owned operational gate evidence.
- Backend full regression passed with `789 passed, 1 warning`.
- Frontend `npm run release:gate` passed with `178` unit tests and `3`
  Playwright tests.
- Blind/contextless review cleared after stale range, fixture key, and
  recovery-scope remediation.
- Live Coinbase execution was not run; submitted notional `$0`, executed
  notional `$0`.

Done when:

- Frontend runtime snapshot includes all three gate reads.
- Operator UI displays gate status, checks, read-only posture, and no-live
  evidence without creating browser authority.
- Backend and frontend validators used active phase range 721-740.
- Focused and full gates pass.
- Blind/contextless review confirms the module slice can be understood from
  checked-in docs and tests.

## M12 - Frontend-Fixtures Runtime Evidence

Purpose: promote the existing backend-owned frontend-fixtures route from
contract-only coverage to runtime-loaded admin evidence without making it a
browser-side source of trading behavior.

Completion evidence:

- Phases 741-760 load `GET /api/v1/admin/frontend-fixtures` through the
  frontend runtime snapshot and display fixture bundle diagnostics.
- The evidence highlights backend gate fixture keys, schema version, and
  no-live posture.
- Mock fixtures, route coverage, quality artifacts, and docs stay aligned with
  the backend route.
- Backend full regression passed with `789 passed, 1 warning`.
- Frontend `npm run release:gate` passed with `178` unit tests and `3`
  Playwright tests.
- Blind/contextless review blockers were remediated before commit.
- Live Coinbase execution was not run; submitted notional `$0`, executed
  notional `$0`.

Done when:

- Frontend runtime snapshot includes frontend-fixtures.
- Operator diagnostics display fixture count, gate fixture keys, schema
  version, and no-live evidence.
- Backend and frontend validators used active phase range 741-760.
- Focused and full gates pass.
- Blind/contextless review confirms frontend-fixtures are clearly read-only
  evidence and not a parallel trading authority.

## M13 - Read-Smoke Runtime Parity

Purpose: make direct-backend and BFF dry read smoke prove the same backend
evidence routes the enterprise admin runtime snapshot consumes.

Completion evidence:

- Phases 761-780 define a shared read-smoke route catalog for direct backend
  and BFF smoke scripts.
- The catalog covers admin evidence routes, runtime read-model routes, and
  representative detail reads without live Coinbase execution.
- Release checks fail if the catalog or smoke scripts drift from runtime
  evidence expectations.
- Backend full regression passed with `789 passed, 1 warning`.
- Frontend `npm run release:gate` passed with `178` unit tests and `3`
  Playwright tests.
- Blind/contextless M13 review blockers were remediated before commit.
- Live Coinbase execution was not run; submitted notional `$0`, executed
  notional `$0`.

Done when:

- Direct read smoke and BFF read smoke use the same shared catalog.
- Dry smoke output includes OIDC readiness, live-enablement,
  enterprise-readiness, operational gates, frontend-fixtures, read-model list
  routes, and representative detail routes.
- Backend and frontend validators used the M13 phase range 761-780.
- Focused and full gates pass.
- Blind/contextless review confirms smoke parity is read-only evidence and not
  a live execution path.

## M14 - Command-Smoke Runtime Parity

Purpose: make direct-backend and BFF dry command smoke prove the same
live-disabled backend command surfaces without creating browser trading
authority.

Current onboarding work:

- Phases 781-800 define a shared command-smoke catalog for direct backend and
  BFF smoke scripts.
- The catalog covers manual order create, order cancel by `client_order_id`,
  stealth cancel by `stealth_order_id`, movement/repricing reprice by
  `stealth_order_id`, and spot campaign execution.
- Direct and BFF command smoke continue to expect backend `501`
  live-disabled responses, `x-live-execution-enabled=false`, and
  `live_exchange_submitted=false`.
- Release checks fail if the command catalog or smoke scripts drift from the
  expected command surfaces.

Done when:

- Direct command smoke and BFF command smoke use the same shared catalog.
- Dry smoke output lists the same command surfaces with only the `/api/admin`
  BFF prefix difference.
- Backend and frontend validators use active phase range 781-800.
- Focused and full gates pass.
- Blind/contextless review confirms command smoke is disabled-command evidence
  and not a live execution or parallel trading path.

## Objective Completion

The durable objective is complete only when the enterprise admin frontend/API
path covers the trading engine modules that make sense for admin operation,
with unsupported actions explicitly marked unsupported. Completion requires
backend-owned contracts, generated frontend consumption, tests, release gates,
and contextless review evidence across the platform, not just spot.
