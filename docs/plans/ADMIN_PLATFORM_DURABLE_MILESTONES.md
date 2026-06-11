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
| M6 - Non-Spot Command Draft Contracts | Pending | Add disabled drafts/dry-submit contracts only after read contracts are stable. |
| M7 - Production Auth And Operations Hardening | Pending | Finish enterprise auth, deployment, observability, and operator runbooks. |
| M8 - Controlled Live Enablement | Pending | Enable live execution only per approved backend path, cap, and reconciliation gate. |
| M9 - Enterprise Release Candidate | Pending | Prove the whole admin platform with release, security, contextless, and regression gates. |
| M10 - Public Maintainer Handoff | Pending | Make onboarding, contribution, and contextless-agent operation durable. |

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

Done when the approved live path has passing focused tests, full regression,
contextless review, live evidence under cap, and post-live reconciliation.

## M9 - Enterprise Release Candidate

Purpose: prove the admin platform is complete enough for controlled external
use.

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

Done when:

- Root READMEs stay concise and route readers to ordered docs.
- Feature docs, examples, route inventory, generated API rules, ownership
  maps, and contextless review logs are current.
- A fresh agent can add a small read-only module slice by following docs and
  passing gates without asking for hidden context.
- Historical roadmap notes do not contradict the current platform state.

## Objective Completion

The durable objective is complete only when the enterprise admin frontend/API
path covers the trading engine modules that make sense for admin operation,
with unsupported actions explicitly marked unsupported. Completion requires
backend-owned contracts, generated frontend consumption, tests, release gates,
and contextless review evidence across the platform, not just spot.
