# Admin API E2E Plan

This plan defines how the backend repository moves from proof-of-concept
dashboard surfaces to a professional enterprise API consumed by the separate
admin frontend repository at `C:\coinbase-frontend`.

## Non-Negotiable Direction

Do not add a second trading path. FastAPI handlers must not implement live
placement, cancellation, wallet checks, guard logic, or Coinbase calls beside
the existing engine paths. The migration must extract shared command services
first, then make the legacy WebSocket handlers and new HTTP handlers call the
same backend behavior.

## Target Architecture

Canonical request path:

```text
frontend request
-> FastAPI route
-> auth/RBAC
-> idempotency and approval gate
-> shared command service
-> existing domain/bridge/exchange path
-> durable audit
-> typed response
```

Legacy dashboard compatibility path:

```text
dashboard WebSocket message
-> compatibility adapter
-> compatibility idempotency/approval/cap treatment for live commands
-> shared command service
-> existing domain/bridge/exchange path
-> dashboard response/state update
```

## Planned Module Boundary

Implementation must introduce the service boundary before adding live HTTP
routes.

Target modules:

- `application/admin_api/command_service.py`: shared command entrypoints used by
  FastAPI routes and legacy WebSocket adapters.
- `application/admin_api/models.py`: Pydantic-compatible command DTOs and typed
  results, using enums from `core/enums.py`.
- `application/admin_api/idempotency.py`: durable idempotency lookup, conflict
  detection, replay handling, and `client_order_id` reuse.
- `application/admin_api/approval.py`: approval snapshot hashing and execution
  matching.
- `application/admin_api/audit.py`: durable accepted/rejected command audit
  writer.
- `api/v1/routes/*.py`: thin FastAPI route adapters only.
- `openapi/coinbase-admin-api.yaml`: generated schema artifact consumed by
  `C:\coinbase-frontend`.
- `docs/plans/ADMIN_API_ROUTE_INVENTORY.md`: checked-in route/message
  inventory synchronized with `application/admin_api/route_inventory.py`.

Initial command service methods:

- `place_manual_order(command)`: extracted from the current dashboard
  `place_order` branch.
- `cancel_order_by_client_order_id(command)`: extracted from the current
  dashboard `cancel_order` branch and still calling the project
  `cancel_order(client_order_id)` wrapper.
- `place_hotpoint_test_order(command)`: extracted from the current dashboard
  hotpoint test placement branch if that workflow is exposed over HTTP.

The first extraction target is direct manual placement and cancellation because
those are the current live dashboard branches most likely to become enterprise
API endpoints.

## Initial Route And Message Inventory

Before implementation, create a checked-in inventory table with one row per
route or legacy message. Each row must include action class, permission,
idempotency requirement, approval requirement, cap policy, audit event, command
service method, and parity test.

Initial target inventory:

| Surface | Action class | Permission | Idempotency | Approval | Caps | Audit | Shared method | Parity test |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `POST /api/v1/orders` | `live_exchange_place` | `order:create` | Required | Required | Required | Required | `place_manual_order` | HTTP vs `place_order` guard/result parity |
| `place_order` WebSocket | `live_exchange_place` | compatibility policy | Required for enterprise mode or explicitly compatibility-only | Required for enterprise mode or explicitly compatibility-only | Required | Required | `place_manual_order` | WebSocket vs HTTP guard/result parity |
| `place_hotpoint_test_order` WebSocket | `live_exchange_place` | compatibility policy | Required for enterprise mode or explicitly compatibility-only | Required for enterprise mode or explicitly compatibility-only | Required | Required | `place_hotpoint_test_order` | WebSocket vs shared-service hotpoint guard/result parity |
| `POST /api/v1/orders/{client_order_id}/cancel` | `live_exchange_cancel` | `order:cancel` | Required | Not required unless policy adds approval | Required for rate/session controls | Required | `cancel_order_by_client_order_id` | HTTP vs `cancel_order` parity |
| `cancel_order` WebSocket | `live_exchange_cancel` | compatibility policy | Required for enterprise mode or explicitly compatibility-only | Not required unless policy adds approval | Required for rate/session controls | Required | `cancel_order_by_client_order_id` | WebSocket vs HTTP parity |
| read-only status routes | `read_only` | route-specific read permission | Not required | Not required | Not applicable | Optional read audit | read service method | no Coinbase REST placement |

If a legacy WebSocket live command is not passed through enterprise
idempotency/approval/cap gates, it must be explicitly labeled
compatibility-only, constrained to localhost/operator mode, and excluded from
new frontend product workflows.

## Phase 1 - Contract Boundary

Status: implemented for the initial order/cancel contract and read-only spot
operator routes. OpenAPI is generated from FastAPI models and consumed by the
frontend repository.

- Add a versioned API namespace, initially `/api/v1`.
- Use FastAPI with Pydantic request/response models.
- Generate and snapshot OpenAPI under `openapi/coinbase-admin-api.yaml`.
- Use enums from `core/enums.py`; do not duplicate magic strings.
- Represent money, sizes, fees, and prices as `Decimal` or serialized strings,
  not floats.
- Keep order-facing identifiers centered on `client_order_id`.
- Make cancellation client-order-id keyed, for example:
  `POST /api/v1/orders/{client_order_id}/cancel`.
- Do not expose raw Coinbase pass-through payloads as the primary API contract.

Exit criteria:

- OpenAPI schema exists and is generated from backend models.
- Frontend can generate a TypeScript client without hand-maintained schema.
- Contract tests cover schema generation and representative typed responses.

## Phase 2 - Shared Command Services

Status: implemented for legacy dashboard `place_order`, `cancel_order`, and
`place_hotpoint_test_order`. These messages now delegate to
`AdminApiCommandService`; HTTP mutating routes call the same service with live
execution disabled.

- Extract live command handling out of `dashboard_server.py` into shared
  application services.
- Keep WebSocket handlers operational as compatibility adapters.
- Make new HTTP handlers call the same services.
- Preserve existing runtime admission, product capability, size validation,
  manual spot acknowledgement, action-condition guards, `track_inflight`, and
  `order_event_stream` submission evidence.
- Preserve the Coinbase cancellation exception: call the project wrapper
  `cancel_order(client_order_id)`.
- Start with the `place_order`, `cancel_order`, and hotpoint test placement
  branches before exposing equivalent HTTP routes.

Exit criteria:

- WebSocket and HTTP parity tests prove equivalent guard failures and command
  results.
- No new behavior exists only in `dashboard_server.py` or only in FastAPI.
- The route/message inventory is checked in and names the command service
  method for every live route or message.

## Phase 3 - Command Classification

Status: implemented for initial order, cancel, and read-only spot routes in
`application/admin_api/route_inventory.py`.

Classify every API operation as one of:

- `read_only`
- `local_state_mutation`
- `live_exchange_place`
- `live_exchange_cancel`
- `admin_runtime`
- `audit`

Read-only status operations such as spot readiness, sweep status, campaign
status, cost-basis status, and direct order audit must remain read-only unless
renamed and redesigned as mutating commands.

Exit criteria:

- Route inventory documents action class, permission, audit behavior, and live
  exchange risk for every route.
- Tests prove read-only routes cannot submit Coinbase REST orders.

## Phase 4 - Auth And RBAC

Status: bootstrap implemented. Routes fail closed unless
`COINBASE_ADMIN_API_BEARER_TOKEN` is configured and requests include
backend-recognized role evidence. Production OIDC/JWT verification is still a
future hardening step.

- Define backend-enforced roles before implementation: viewer, operator,
  trader, admin, auditor, and emergency if needed.
- Map every route to permissions.
- Use backend-verifiable bearer/OIDC-style tokens or equivalent.
- Lock CORS to approved frontend origins.
- Keep Coinbase credentials exclusively on backend hosts.
- Treat frontend button hiding as usability only.

Exit criteria:

- Auth denial and RBAC denial regression tests exist for representative read
  and mutating routes.
- Mutating routes fail closed without authenticated actor identity.

## Phase 5 - Idempotency

Status: implemented for HTTP mutating routes with a durable JSONL repository.
Replays return the stored response; payload drift returns conflict.

- Require `Idempotency-Key` on live POST commands.
- Persist command key, actor, role, endpoint, payload hash, generated
  `client_order_id`, status, response, failure stage, and timestamps.
- Replays with the same key and same payload hash return the original result.
- Replays with the same key and different payload hash return conflict.
- Never mint a second `client_order_id` for a retried placement.

Exit criteria:

- Regression covers idempotent retry, conflict, and no duplicate Coinbase call.
- Audit history links idempotency records to command outcomes.

## Phase 6 - Approval Gates And Live Caps

Status: approval snapshot hashing and structured live-execution gate responses
exist, but live HTTP execution remains disabled until approval matching and cap
enforcement are wired into the route admission path.

- Live placement requires server-side approval, not only a frontend checkbox.
- Approval binds to product, side, size, price, order config, cap result, actor,
  generated `client_order_id`, and payload hash.
- Execution rejects when the submitted payload differs from the approved
  snapshot.
- Keep manual spot live acknowledgement, but do not treat it as sufficient
  enterprise approval.
- Enforce caps before Coinbase REST calls:
  - max notional per order
  - max orders per minute/session/day
  - max product exposure
  - max open live orders
  - role-specific limits
- Placement is impossible outside the required runtime state.
- Cancellations remain available while paused or draining when policy allows,
  but they are still RBAC-gated and inflight-tracked.

Exit criteria:

- Regression covers approval mismatch, cap rejection, runtime rejection, and no
  REST call when gates fail.
- Live Coinbase tests remain separately approved and must report notional.

## Phase 7 - Durable Audit

Status: implemented for HTTP mutating command attempts with a durable JSONL
audit repository. Database-backed retention remains a future production
hardening step.

- Add durable command audit records as a new table or a clearly separated
  `order_event_stream` event family.
- Log successful and rejected commands.
- Capture actor, role, endpoint, request id, idempotency key, approval id,
  guard decisions, REST attempt/result, `client_order_id`, Coinbase `order_id`,
  failure stage, IP, user agent, and correlation id where applicable.

Exit criteria:

- Regression covers audit row creation for accepted and rejected commands.
- Operator responses include correlation id and audit reference.

## Phase 8 - Compatibility And Migration

- Freeze the current WebSocket message contract in docs before migration.
- Introduce HTTP endpoints behind shared services without removing POC
  dashboards.
- Add parity tests before switching frontend workflows.
- Mark legacy dashboard-only paths as compatibility surfaces once HTTP parity
  exists.

Exit criteria:

- Existing dashboard tests still pass.
- New HTTP tests pass.
- `pytest tests/regression/ -v --tb=short` passes.

## Phase 9 - Frontend Integration

- Frontend consumes only generated OpenAPI client and typed read-only stream
  contracts.
- Frontend displays backend guard decisions, not locally inferred safety.
- Frontend uses mocks for local development and real backend only by explicit
  environment configuration.

Exit criteria:

- Frontend quality gate passes.
- Backend regression gate passes for every backend API change.
- Browser tests prove live controls are disabled without backend authority.

## Phase 10 - Contextless Blind-Agent Gate

Before broadening order or campaign API behavior, run a fresh contextless agent
review against:

- `README.admin-api.md`
- this plan
- `genai_data/API_REFERENCE.md`
- `genai_data/ORDER_ID_HANDLING.md`
- `docs/agents/AGENT_ADMIN_API_CONTRACT.md`

The agent must explain:

- how a frontend request reaches existing backend order behavior
- where auth and RBAC are enforced
- how idempotency prevents duplicate `client_order_id` minting
- how approval snapshots and live caps prevent unsafe execution
- how cancel-by-`client_order_id` works
- which tests prove the path

If it cannot, fix docs or code organization before implementation continues.

## Required Regression Tests

When implementation starts, add focused tests for:

- OpenAPI schema generation
- auth denial
- RBAC denial
- route command classification
- approval mismatch
- idempotent retry
- idempotency conflict
- live cap rejection
- no REST call on guard failure
- cancel by `client_order_id`
- audit row creation for accepted and rejected commands
- WebSocket/HTTP parity

The full backend gate remains:

```powershell
pytest tests/regression/ -v --tb=short
```

## Approved Backend Sync Roadmap

Phases 241-270 are approved to sync the backend Admin API with the current
enterprise frontend state. These phases do not authorize live Coinbase
execution. Live order execution remains a separate explicit approval.

### Phase 241 - Backend/Frontend Contract Gap Audit

- Compare current frontend wrappers, docs, and tests against backend OpenAPI,
  route inventory, command service, and Admin API docs.
- Produce an explicit backend gap list.

Exit criteria:

- Backend docs name which frontend expectations are implemented,
  contract-pending, or intentionally blocked.

### Phase 242 - Command Response Contract Normalization

- Make backend command responses consistently expose status, action class,
  permission, message, `client_order_id`, correlation id, idempotency key,
  audit id, guard evidence, and live-submission evidence.

Exit criteria:

- Regression covers representative accepted, rejected, not-implemented,
  replayed, and conflict command responses.

### Phase 243 - Manual Order Accepted Response Contract

- Add explicit accepted/replayed 2xx OpenAPI responses for
  `POST /api/v1/orders`.
- Keep live execution gated/disabled unless separately approved.

Exit criteria:

- OpenAPI includes the accepted response contract without enabling live
  Coinbase execution.

### Phase 244 - Cancel Accepted Response Contract

- Add explicit accepted/replayed 2xx OpenAPI responses for
  `POST /api/v1/orders/{client_order_id}/cancel`.
- Keep cancellation keyed by `client_order_id`.

Exit criteria:

- OpenAPI includes the accepted response contract and no `order_id`
  cancellation path exists.

### Phase 245 - Command Idempotency Contract Tightening

- Document and test replay success, payload drift conflict, and required
  idempotency headers for all command routes.

Exit criteria:

- Regression covers replay/conflict behavior and required headers.

### Phase 246 - Backend Order Read Routes

- Add order list, filter, and detail read routes keyed by `client_order_id`.
- Expose exchange `order_id` only as exchange evidence.

Exit criteria:

- Read routes are authenticated, read-only, and tested.

### Phase 247 - Campaign Execution Command Contract

- Define a backend-owned campaign execution review/approval route.
- Keep live execution gated and disabled by default.

Exit criteria:

- Route exists in OpenAPI as a command contract and cannot submit live orders.

### Phase 248 - Recovery And Readiness Read Routes

- Expose release gate, recovery gate, and fill-ledger health read routes for
  frontend recovery/readiness panels.

Exit criteria:

- Routes are authenticated, read-only, and tested.

### Phase 249 - Observability Headers And Error Shape

- Standardize request id, correlation id, audit id, structured error code,
  severity, guard name, and field path across Admin API routes.

Exit criteria:

- Representative success and error responses include observable metadata.

### Phase 250 - Auth/RBAC Contract Sync

- Make backend route permissions match frontend role-hint docs while
  preserving backend enforcement as authority.

Exit criteria:

- Permission matrix is documented and tested.

### Phase 251 - OpenAPI Regeneration And Drift Tests

- Regenerate `openapi/coinbase-admin-api.yaml`.
- Add or adjust regression tests proving schema matches implemented routes.

Exit criteria:

- Generated schema matches checked-in schema.

### Phase 252 - Frontend Contract Verification Pass

- From the backend side, verify frontend expected paths, methods, response
  states, and identity rules are represented in OpenAPI.

Exit criteria:

- Backend regression asserts the frontend contract surface is present.

### Phase 253 - Backend Docs Sync

- Update `README.admin-api.md`, route inventory, examples, and docs index for
  the synced contract.

Exit criteria:

- Contextless readers can find current Admin API contracts and examples.

### Phase 254 - Contextless Blind-Agent Backend Review

- Run a fresh contextless review asking how to create, cancel, and audit a
  spot order through Admin API.
- Fix docs/code if it fails.

Exit criteria:

- Review findings are recorded and resolved or explicitly deferred.

### Phase 255 - Full Backend Regression Gate

- Run the full backend regression suite.

Exit criteria:

- `pytest tests/regression/ -v --tb=short` passes.

### Phase 256 - Admin Bootstrap Endpoint

- Expose environment, backend source, live-action posture, schema version, and
  feature flags for the frontend shell.

Exit criteria:

- Frontend can render shell posture from backend evidence.

### Phase 257 - Backend Health/Diagnostics Endpoint

- Expose backend health, API latency evidence, failed-route diagnostics,
  request id, and correlation id support.

Exit criteria:

- Diagnostics route is authenticated, read-only, and tested.

### Phase 258 - Admin Session/RBAC Evidence Contract

- Define how frontend receives actor, roles, permissions, and
  forbidden/expired session states without browser-visible bearer tokens.

Exit criteria:

- Session evidence route is authenticated and tested.

### Phase 259 - Spot Read-Only Payload Schemas

- Make readiness, sweep status, P/L, cost-basis, campaign status, and
  direct-order audit payloads explicit instead of loose `unknown` schemas.

Exit criteria:

- OpenAPI exposes typed spot read-only payload schemas.

### Phase 260 - Structured Error Contract Everywhere

- Standardize `code`, `message`, `severity`, `guard_name`, `field_path`,
  `correlation_id`, and `audit_id` across Admin API.

Exit criteria:

- Representative auth, RBAC, validation, command, and read errors use the
  structured error contract.

### Phase 261 - Release/Recovery/Health Read Models

- Backend endpoints for release gate, recovery gate, fill-ledger health, and
  repairable-state summaries.

Exit criteria:

- Frontend recovery/readiness panels have backend-owned read models.

### Phase 262 - Admin Capability Registry Endpoint

- Expose which routes/actions are available, disabled, live-disabled,
  contract-pending, or backend-blocked.

Exit criteria:

- Frontend can render disabled/available posture from backend registry
  evidence.

### Phase 263 - Security/CORS/CSRF Contract

- Document and implement deployment-safe CORS/session/CSRF expectations for
  the frontend origin model.

Exit criteria:

- CORS/session/CSRF posture is documented and represented in backend config.

### Phase 264 - Observability Headers Middleware

- Ensure every Admin API response carries request/correlation metadata
  consistently.

Exit criteria:

- Tests cover metadata headers on read, command, and error responses.

### Phase 265 - Backend Fixtures For Frontend Mocks

- Provide backend-owned example payloads so frontend mocks do not drift from
  real backend response shapes.

Exit criteria:

- Example fixtures exist and are referenced by docs/tests.

### Phase 266 - OpenAPI Examples Coverage

- Add examples for every read and command route, including rejected, replayed,
  conflict, guard failure, auth failure, and not implemented.

Exit criteria:

- OpenAPI and docs expose representative examples for frontend implementers.

### Phase 267 - Backend Contract CI Artifact

- Make schema generation/checking a first-class backend CI artifact so
  frontend can consume it reliably.

Exit criteria:

- Backend docs/CI contract explain how schema freshness is enforced.

### Phase 268 - Frontend Contract Re-Sync Pass

- Regenerate frontend types from the updated backend schema and remove fixture
  assumptions that are now covered by real schemas.

Exit criteria:

- Frontend API freshness check passes against the updated backend schema.

### Phase 269 - Cross-Repo Quality Gate

- Run backend regression plus frontend typecheck, lint, API check, unit tests,
  and browser tests as one documented release gate.

Exit criteria:

- Cross-repo gate command sequence is documented and passes locally.

### Phase 270 - Final Blind-Agent Review

- Run contextless backend and frontend reviews after both repos are synced.
- Fix any unclear order, cancel, or audit path.

Exit criteria:

- Final review is recorded with no unresolved contract clarity blockers.

## Approved Integration Completion Roadmap

Phases 271-300 are approved to move the Admin API/frontend work from synced
contracts to integrated local operation and release-candidate evidence. These
phases do not authorize live Coinbase execution. HTTP commands remain
live-disabled unless a later phase is explicitly approved for live execution.

### Phase 271 - Local Admin API Run Contract

- Document and test how to run the FastAPI Admin API locally for frontend
  integration.

Exit criteria:

- A contextless developer can start the backend Admin API and identify the
  required local environment variables.

### Phase 272 - Frontend Runtime API Client Wiring

- Support a runtime frontend client/provider around the generated
  `BackendApiClient`, including backend and mock modes.

Exit criteria:

- Frontend code has one canonical runtime client path and no ad hoc feature
  fetches.

### Phase 273 - Admin Bootstrap And Session Integration

- Use `/api/v1/admin/bootstrap` and `/api/v1/admin/session` as the source of
  shell posture and session/RBAC evidence.

Exit criteria:

- Frontend shell can render backend-sourced environment and session posture
  with mock fallback.

### Phase 274 - Backend Health And Capability Integration

- Use `/api/v1/admin/health` and `/api/v1/admin/capabilities` for diagnostics
  and route/action posture.

Exit criteria:

- Operators can distinguish backend health, route availability, and
  live-disabled routes from frontend evidence.

### Phase 275 - Order Read UI Integration

- Render order list/filter/detail data from `/api/v1/orders` and
  `/api/v1/orders/{client_order_id}`.

Exit criteria:

- UI uses `client_order_id` for order identity and treats exchange ids as
  evidence only.

### Phase 276 - Spot Read Route Integration

- Move spot readiness, sweep, P/L, cost-basis, campaign, and direct-order
  audit views to backend-read-first data loading with mock fallback.

Exit criteria:

- Spot views use canonical backend read wrappers and retain safe empty/error
  states.

### Phase 277 - Recovery And Gate Read Integration

- Wire release gate, recovery gate, and fill-ledger health panels to backend
  read routes.

Exit criteria:

- Recovery/readiness views consume backend evidence and expose no repair
  mutations.

### Phase 278 - Structured Error And Observability UX

- Render structured backend error fields and observability metadata
  consistently.

Exit criteria:

- UI displays `code`, `severity`, `field_path`, `correlation_id`,
  `X-Request-Id`, and live-disabled evidence where applicable.

### Phase 279 - Live-Disabled Command Submission UX

- Allow frontend command forms to submit to backend command routes and render
  expected `501` live-disabled responses.

Exit criteria:

- Manual order, cancel, and campaign command dry submissions are tested and do
  not enable live Coinbase execution.

### Phase 280 - Command Idempotency UX Completion

- Persist/display idempotency keys, replay results, conflict states, and retry
  safety.

Exit criteria:

- Operators can see whether a command is new, replayed, or rejected for
  payload drift.

### Phase 281 - Command Audit Evidence UX

- Surface `audit_id`, `client_order_id`, guard evidence, service method, and
  backend decision in command result panels.

Exit criteria:

- Command result UI exposes backend-owned audit and guard evidence.

### Phase 282 - Order Audit Deep Link Flow

- Link command responses and order detail rows to direct spot order audit by
  `client_order_id`.

Exit criteria:

- Operators can move from command/order evidence to read-only audit evidence
  without using exchange `order_id` as identity.

### Phase 283 - Frontend Query State Standardization

- Use one query/cache/loading/error pattern across backend reads.

Exit criteria:

- Backend-read components share the same loading, empty, error, and refresh
  behavior.

### Phase 284 - Mock Backend Fixture Sync From Backend Examples

- Keep frontend mocks aligned with backend fixture/example payloads.

Exit criteria:

- Mock payloads are traceable to backend-owned examples or fixtures.

### Phase 285 - Cross-Repo Local E2E Smoke

- Start backend and frontend locally and run browser smoke against real
  backend read routes.

Exit criteria:

- A local cross-repo smoke proves frontend reads can use the real Admin API.

### Phase 286 - Cross-Repo Command Dry-Submit E2E

- Run browser smoke against real backend command routes and verify live-disabled
  `501` responses, audit/idempotency evidence, and no live execution.

Exit criteria:

- Dry command submission is proven against the real backend without Coinbase
  execution.

### Phase 287 - Auth/RBAC UI Hardening

- Use backend session permissions for UI availability hints while preserving
  backend authority.

Exit criteria:

- UI permission state comes from backend session evidence when available and
  remains fail-closed when unavailable.

### Phase 288 - Configuration And Environment UX

- Render local, staging, sandbox, and production posture from backend evidence.

Exit criteria:

- Operators can see environment, account/portfolio scope posture, and live
  enablement state before any command.

### Phase 289 - CI Contract Sync Gate

- Ensure frontend CI fails on stale generated schema and backend CI fails on
  OpenAPI drift.

Exit criteria:

- CI contract freshness is documented and enforced.

### Phase 290 - CI Cross-Repo Smoke Gate

- Add a cross-repo smoke gate that boots backend and frontend for read-only
  contract verification.

Exit criteria:

- CI or documented local CI-equivalent smoke validates the integration path.

### Phase 291 - Accessibility Pass For Integrated Data States

- Verify loading, error, empty, and data states remain accessible.

Exit criteria:

- Accessibility tests cover backend-integrated states.

### Phase 292 - Visual Regression Refresh

- Refresh visual baselines for backend-integrated views.

Exit criteria:

- Browser screenshots remain non-empty and stable for integrated views.

### Phase 293 - Performance Budget Pass

- Check large order lists, long audit payloads, and dashboard render cost.

Exit criteria:

- Performance budget helpers account for integrated data volumes.

### Phase 294 - Security Review Pass

- Review CORS, browser-visible config, bearer-token handling, Coinbase secret
  leakage, and ad hoc fetch prevention.

Exit criteria:

- Security docs/tests prove browser code does not expose backend or Coinbase
  secrets.

### Phase 295 - Operational Runbook Update

- Document local run, dry-submit commands, troubleshooting, and evidence
  collection.

Exit criteria:

- A human operator can run local integration and collect useful evidence.

### Phase 296 - Contextless Blind-Agent Review

- Run a fresh review asking how the live-disabled frontend talks to backend.

Exit criteria:

- Findings are fixed or explicitly deferred with rationale.

### Phase 297 - Frontend Release Candidate Gate

- Run full frontend quality and record the result.

Exit criteria:

- Frontend typecheck, lint, API check, unit tests, and browser tests pass.

### Phase 298 - Backend Release Candidate Gate

- Run backend regression and record the result.

Exit criteria:

- `pytest tests/regression/ -v --tb=short` passes.

### Phase 299 - Cross-Repo Release Notes

- Summarize backend/frontend contract state, live-disabled posture, and
  remaining blockers.

Exit criteria:

- Release notes are current and linked from docs.

### Phase 300 - Commit Both Repos

- Commit the completed integration batch in both repositories.

Exit criteria:

- Both repositories have clean working trees after the approved batch is
  committed.

### Progress Update - 2026-06-10

- Phase 271 completed: `tools/run_admin_api.py` documents and starts
  `api.v1.app:app` locally, fails closed without Admin API auth, and has
  regression coverage proving it is not a trading path.
- Phases 272-274 started on the frontend side: runtime selection now defaults
  to mock fixtures, can point at `NEXT_PUBLIC_ADMIN_API_BASE_URL`, and has a
  snapshot loader for bootstrap, health, session, and capabilities.
- Phase 279 started on the frontend side: command workflow UX now distinguishes
  mock mode from backend mode blocked by missing session headers, while keeping
  all command buttons disabled.
- Verification: backend regression passed with `753 passed`; frontend
  `npm run quality` passed.
- Live Coinbase execution: not run; test notional `$0`.

### Progress Update - 2026-06-10, Phases 301-325

- Frontend phases 301-314 advanced against the current backend Admin API
  surface: runtime read snapshots, backend-shaped spot/order adapters,
  observability metadata, and live-disabled command dry-submit helpers now use
  the canonical frontend API wrapper.
- Phase 325 completed for this batch: a contextless blind review confirmed the
  frontend spot-order path starts at the Admin API command workflow, does not
  call Coinbase from the browser, and keeps cancellation keyed by
  `client_order_id`.
- Review remediation removed a misleading browser live-action env example and
  tightened frontend docs/source comments around backend-only live authority.
- Backend changes in this batch remain docs/runner-contract only; no live
  Coinbase execution was run and test notional remains `$0`.

## Approved Completion Batch - Phases 301-330

These phases are approved as the next maximum aligned batch. They do not
authorize live Coinbase execution. Any live execution still requires explicit
approval naming the phase and notional cap.

### Phase 301 - Runtime Read Snapshot Contract

- Make the frontend runtime snapshot the canonical bootstrap/health/session
  read entry for integrated views.

Exit criteria:

- Snapshot behavior is documented and tested against mock and backend-missing
  auth states.

### Phase 302 - Backend-Mode Auth Boundary Stub

- Define the non-browser auth boundary required to supply Admin API read
  headers.

Exit criteria:

- Docs and tests prove browser-visible tokens are not accepted as auth.

### Phase 303 - Backend Session Evidence Sync

- Use backend session evidence for UI posture when available.

Exit criteria:

- UI distinguishes mock session hints from backend session evidence.

### Phase 304 - Health And Capability Data Mapping

- Map backend health and capability payloads into frontend view models without
  feature-level fetch calls.

Exit criteria:

- The admin shell can render health/capability state from runtime snapshots.

### Phase 305 - Order List Read Integration

- Connect order list UI to the canonical read wrapper and preserve
  `client_order_id` identity.

Exit criteria:

- Order list tests cover data, empty, auth-denied, and backend-error states.

### Phase 306 - Order Detail Read Integration

- Connect order detail/deep-link UI to backend order detail reads.

Exit criteria:

- Operators can inspect order detail by `client_order_id`; exchange ids remain
  evidence only.

### Phase 307 - Spot Readiness Data Integration

- Map spot readiness payloads into spot operator views.

Exit criteria:

- Spot readiness view supports backend-shaped data, empty, blocked, and error
  states.

### Phase 308 - Sweep Status And P/L Data Integration

- Map sweep status and P/L payloads into frontend view models.

Exit criteria:

- Sweep/P&L views render backend payloads without frontend trading
  calculations.

### Phase 309 - Cost Basis And Campaign Data Integration

- Map cost-basis and campaign status payloads into frontend view models.

Exit criteria:

- Cost-basis/campaign views show backend authority and freshness evidence.

### Phase 310 - Direct Order Audit Integration

- Connect direct-order audit UI to `client_order_id` audit reads.

Exit criteria:

- Audit reads remain read-only and keyed only by `client_order_id`.

### Phase 311 - Structured Loading/Error/Empty State Contract

- Standardize loading, empty, auth, RBAC, backend, validation, and guard
  failure states across integrated views.

Exit criteria:

- Shared error components cover every backend error class used by the UI.

### Phase 312 - Observability Header Surfacing

- Surface correlation id, request id, API version, and live-execution-disabled
  evidence from responses.

Exit criteria:

- Integrated views display or expose observability metadata for support.

### Phase 313 - Command Form State Completion

- Complete disabled command form state for manual order, cancel, and campaign
  execution.

Exit criteria:

- Forms show required evidence, idempotency preview, and blocked backend
  posture without enabling live actions.

### Phase 314 - Command Dry-Submit Contract

- Add an explicit dry-submit path against current live-disabled HTTP commands.

Exit criteria:

- Dry-submit tests verify `501`/live-disabled behavior and no Coinbase
  execution.

### Phase 315 - Idempotency Evidence UX

- Render idempotency replay/conflict evidence for command responses.

Exit criteria:

- UI distinguishes accepted, replayed, rejected, conflict, and validation
  responses.

### Phase 316 - Audit Evidence UX

- Render backend audit ids, command status, guard stage, and live execution
  evidence in one reusable panel.

Exit criteria:

- Command and read views reuse the same audit evidence component.

### Phase 317 - Local Cross-Repo Read Smoke

- Boot local backend/frontend and run browser smoke against real read routes.

Exit criteria:

- Cross-repo read smoke passes without live Coinbase execution.

### Phase 318 - Local Cross-Repo Command Dry Smoke

- Boot local backend/frontend and dry-submit live-disabled commands.

Exit criteria:

- Command dry smoke records `501`, audit/idempotency evidence, and `$0`
  live notional.

### Phase 319 - Accessibility Pass For Integrated States

- Validate integrated loading/error/empty/data states.

Exit criteria:

- Accessibility tests cover runtime and backend-integrated views.

### Phase 320 - Visual Regression Pass For Integrated States

- Refresh browser visual smoke for runtime-integrated shell/read/command
  states.

Exit criteria:

- Screenshots are non-empty and stable across desktop/mobile.

### Phase 321 - Performance Budget For Integrated Tables

- Add budget checks for order tables, audit rows, and spot evidence lists.

Exit criteria:

- Large payloads have documented UI limits or virtualization plans.

### Phase 322 - Security Review For Runtime Config

- Review runtime config, CORS, auth headers, secret names, and ad hoc fetch
  prevention.

Exit criteria:

- Tests/docs prove no browser-visible backend or Coinbase secrets are used.

### Phase 323 - CI Cross-Repo Contract Path

- Define CI or CI-equivalent steps for schema freshness and local integration.

Exit criteria:

- CI docs and scripts show how backend and frontend stay synced.

### Phase 324 - Operator Runbook Refresh

- Document local backend start, frontend runtime modes, smoke tests, and
  troubleshooting.

Exit criteria:

- A contextless operator can run local integration from docs.

### Phase 325 - Contextless Blind-Agent Review

- Run a blind review asking how to create a spot order from the frontend
  without inventing a trading path.

Exit criteria:

- Findings are fixed before moving to release notes.

### Phase 326 - Backend API Hardening Review

- Review read-route filtering, pagination, structured errors, and route
  inventory drift.

Exit criteria:

- Backend contract tests cover discovered gaps or document explicit deferrals.

### Phase 327 - Frontend Release Candidate Gate

- Run full frontend quality after integrated states.

Exit criteria:

- `npm run quality` passes.

### Phase 328 - Backend Release Candidate Gate

- Run backend regression after integration/hardening.

Exit criteria:

- `pytest tests/regression/ -v --tb=short` passes.

### Phase 329 - Cross-Repo Release Notes

- Summarize the frontend/backend integration state and remaining live-action
  blockers.

Exit criteria:

- Release notes are linked from documentation indexes.

### Phase 330 - Commit Both Repos

- Commit the completed maximum batch in both repositories.

Exit criteria:

- Both repositories have clean working trees after commit.

## Approved Runtime Integration Batch - Phases 331-350

These phases are approved as the next aligned completion batch. They do not
authorize live Coinbase execution. HTTP commands remain live-disabled and any
future live execution still requires explicit approval naming the phase and
notional cap.

### Phase 331 - Backend-Mode Session Header Bridge

- Define the session/BFF bridge that supplies Admin API headers without
  exposing backend bearer tokens to browser code.

Exit criteria:

- Frontend docs/tests show browser config cannot provide Admin API bearer
  authorization.

### Phase 332 - Runtime Provider Mounted In App Shell

- Mount the frontend runtime provider in the shell and load backend/mock
  snapshots from one path.

Exit criteria:

- The shell consumes runtime state instead of static backend posture where
  backend evidence exists.

### Phase 333 - Backend Session Evidence Shell Posture

- Use backend session evidence for actor, roles, permissions, and session
  status when available.

Exit criteria:

- Shell posture distinguishes mock session hints, backend session evidence,
  and missing-auth blocked state.

### Phase 334 - Capability-Driven Route Availability

- Use backend capability registry evidence to label route/action availability.

Exit criteria:

- UI availability hints come from backend capability evidence when present and
  fail closed otherwise.

### Phase 335 - Runtime Order List Read UI

- Feed order list read models from runtime order reads.

Exit criteria:

- Orders remain read-only and keyed by `client_order_id`.

### Phase 336 - Runtime Order Detail Read UI

- Feed order detail/deep-link state from runtime order detail reads.

Exit criteria:

- Detail reads display exchange ids only as evidence.

### Phase 337 - Async Spot Read Loading States

- Show loading, blocked, empty, and ready states around spot runtime reads.

Exit criteria:

- Spot views use backend-shaped data without frontend trading calculations.

### Phase 338 - Live-Disabled Command Dry-Submit UI

- Wire command UI to the dry-submit helper while keeping controls
  live-disabled.

Exit criteria:

- Dry-submit results show backend `501`/blocked evidence and run `$0`
  Coinbase notional.

### Phase 339 - Reusable Command/Audit Evidence Panel

- Reuse a shared evidence panel for command status, audit ids, guard stage,
  idempotency, and live-execution evidence.

Exit criteria:

- Command and read flows render backend evidence consistently.

### Phase 340 - Idempotency Replay/Conflict Result UI

- Render new, replayed, rejected, validation, and conflict command outcomes.

Exit criteria:

- Operators can distinguish retry-safe replay from payload drift conflict.

### Phase 341 - Cross-Repo Read Smoke Script

- Add a repeatable script or documented command for local backend/frontend
  read smoke.

Exit criteria:

- Smoke verifies read routes without live Coinbase execution.

### Phase 342 - Cross-Repo Command Dry Smoke Script

- Add a repeatable script or documented command for live-disabled command dry
  smoke.

Exit criteria:

- Smoke verifies dry command evidence and `$0` live notional.

### Phase 343 - Backend CORS/Session/CSRF Hardening

- Tighten backend docs/tests around CORS origins, session header source, and
  CSRF expectations for the frontend deployment model.

Exit criteria:

- Backend contract documents secure frontend association and fail-closed auth.

### Phase 344 - Integrated Accessibility Pass

- Cover runtime loading, blocked, and integrated data states with
  accessibility tests.

Exit criteria:

- Accessibility checks pass for the integrated shell.

### Phase 345 - Integrated Visual Smoke Refresh

- Refresh browser smoke coverage for runtime-integrated shell/read/command
  states.

Exit criteria:

- Screenshots are non-empty and no critical text overlaps.

### Phase 346 - Integrated Performance Budget

- Add budget checks for order tables, spot evidence lists, and command
  evidence panels.

Exit criteria:

- Table/evidence rendering limits are visible before production release.

### Phase 347 - Ad Hoc Command Fetch Prevention

- Add a guard that detects frontend feature-local command fetch patterns.

Exit criteria:

- Tests fail if product UI bypasses canonical command wrappers.

### Phase 348 - Operator Runbook Refresh

- Update runbooks for runtime modes, smoke scripts, dry-submit, and evidence
  collection.

Exit criteria:

- A contextless operator can run the current integrated stack safely.

### Phase 349 - Contextless Blind-Agent Review

- Run a fresh blind review against the integrated frontend/backend state.

Exit criteria:

- Findings are fixed or explicitly deferred before committing.

### Phase 350 - Full Gates And Commits

- Run backend regression and frontend quality, then commit both repositories.

Exit criteria:

- Both repos are committed with clean working trees and live Coinbase notional
  reported.

### Progress Update - 2026-06-10, Phases 331-348

- Phases 331-334 advanced on the frontend side: the app shell now mounts a
  runtime provider, loads integrated Admin API snapshots, uses backend session
  evidence, and labels route availability from capability payloads when
  present.
- Phases 335-337 advanced: order list/detail and spot operator views now render
  backend-shaped runtime data with loading/blocked/ready state evidence.
- Phases 338-340 advanced: command dry-submit UI now renders reusable evidence
  from the canonical dry-submit helper and remains blocked before request
  without mutation headers.
- Phases 341-342 advanced: frontend cross-repo smoke scripts exist for read
  routes and live-disabled command dry-submit. Dry-run smoke reports live
  Coinbase execution not run with notional `$0`.
- Phase 343 advanced: backend CORS is allowlisted by
  `COINBASE_ADMIN_API_CORS_ORIGINS`, allows the session/CSRF bridge headers,
  and is covered by regression.
- Phases 344-348 advanced: accessibility, visual-smoke expectations,
  performance evidence-row budget, command-fetch guard, and runbook docs were
  updated.
- Phase 349 completed for this batch: a contextless blind review confirmed the
  order path, no-Coinbase-browser boundary, session-header source, runtime read
  flow, dry-submit evidence, `client_order_id` cancel rule, and smoke script
  discoverability. Remediation made the frontend low-level request method
  private and expanded the command-fetch guard.
- Verification: backend regression passed with `754 passed`; frontend
  `npm run quality` passed with typecheck, lint, API freshness,
  command-fetch guard, `88` unit tests, and `3` Playwright tests.
- Live Coinbase execution: not run; test notional `$0`.
