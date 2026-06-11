# Admin API

This repository will expose the professional backend API for the separate
enterprise admin frontend at `C:\coinbase-frontend`.
The repository association is documented in
[Frontend Association](docs/FRONTEND_ASSOCIATION.md).

## Current Status

The repository now contains an Admin API contract, generated OpenAPI artifact,
fail-closed auth/RBAC bootstrap, durable JSONL idempotency/audit stores,
structured error payloads, observability headers, read-only admin diagnostics,
order read routes, and read-only spot operator routes. Mutating HTTP routes
still return `not_implemented` after auth, permission, idempotency, and audit
handling; they do not submit orders, cancel orders, or call Coinbase.

The generated OpenAPI contract documents the eventual `200` accepted/replayed
command response shape and the current `501` live-disabled response shape.
The current runtime still returns `501` for create, cancel, and campaign
execution commands because HTTP live execution is not approved. Read routes
document typed `200` payloads plus structured `401` and `403` errors.

The legacy dashboard `place_order`, `cancel_order`, and
`place_hotpoint_test_order` WebSocket messages now delegate to
`application.admin_api.command_service.AdminApiCommandService` as compatibility
adapters. New product UI must use the HTTP API contract, not the dashboard
WebSocket.

Mutating HTTP command responses include the current fail-closed live execution
gate decision. The gate reports that approval snapshots, cap evaluation, and
durable audit are required before HTTP live execution can be enabled.

Current read-only HTTP surfaces include:

- `GET /api/v1/admin/bootstrap`
- `GET /api/v1/admin/health`
- `GET /api/v1/admin/session`
- `GET /api/v1/admin/oidc-readiness`
- `GET /api/v1/admin/capabilities`
- `GET /api/v1/admin/csrf`
- `GET /api/v1/admin/release-gate`
- `GET /api/v1/admin/recovery-gate`
- `GET /api/v1/admin/fill-ledger-health`
- `GET /api/v1/admin/frontend-fixtures`
- `GET /api/v1/orders`
- `GET /api/v1/orders/{client_order_id}`
- `GET /api/v1/spot/readiness`
- `GET /api/v1/spot/sweep/status`
- `GET /api/v1/spot/sweep/pnl`
- `GET /api/v1/spot/cost-basis/status`
- `GET /api/v1/spot/campaign/status`
- `GET /api/v1/spot/direct-orders/{client_order_id}/audit`

Current mutating HTTP command surfaces are:

- `POST /api/v1/orders`
- `POST /api/v1/orders/{client_order_id}/cancel`
- `POST /api/v1/spot/campaign/executions`

The current operational dashboard is still the proof-of-concept WebSocket and
HTML surface documented in `agent.md` and `genai_data/API_REFERENCE.md`.
For the current boundary between legacy live WebSocket commands, read-only
HTTP routes, and sweep/campaign execution, see
[Live Order Surfaces](docs/LIVE_ORDER_SURFACES.md).

The frontend release-hardening gate is owned by `C:\coinbase-frontend` and is
the canonical no-live command:

```powershell
npm run release:gate
```

That gate expands to build, typecheck, lint, generated API freshness, command
security, release/deployment checks, release artifact generation, runtime
evidence, autonomous queue validation, unit tests, dry read/command/BFF/OIDC
smokes, and Playwright e2e. Those checks are no-live checks and must report
live Coinbase execution as not run with notional `$0`. They are not approval
for live Coinbase execution. The release artifact is written in the frontend
repository at
`artifacts/release-readiness.json`; the package manifest is
`artifacts/deployment-package-manifest.json`; and the route/header drill is
`artifacts/observability-drill.json`. Synthetic probe evidence is written to
`artifacts/synthetic-probes.json`, and the public release checklist is written
to `artifacts/public-release-checklist.json`. Runtime/UI evidence is written
to `artifacts/runtime-evidence.json`. They are uploaded by frontend CI; they
are not backend approval to trade. These checks do not replace this
repository's required backend regression gate when backend files change.
In short: runtime evidence is saved, and these artifacts are not approval for
live Coinbase execution.
No-live release artifacts are not approval for live Coinbase execution.

The current frontend read-model interaction batch consumes backend-shaped
admin, order, spot, campaign, audit, and diagnostics reads as display evidence
only. The frontend may locally filter/sort already-loaded rows, select
`client_order_id` details, render audit anchors for client order id,
correlation id, and audit id, switch campaign evidence tabs, show named
empty/error states, and keep tables usable on narrow viewports. None of those
interactions create frontend trading authority, wallet checks, guard
decisions, order profitability checks, Coinbase calls, or exchange
`order_id` identity.

## Direction

- Use FastAPI with backend-owned OpenAPI.
- Keep the backend as the only authority for trading behavior.
- Keep HTTP live-order execution disabled until approval/cap gates are complete.
- Keep legacy dashboard WebSocket handlers as compatibility adapters.
- If a legacy WebSocket live command does not pass through enterprise
  idempotency, approval, and cap gates, label it compatibility-only and exclude
  it from new frontend workflows.
- Use `client_order_id` for internal and operator-facing order tracking.
- Preserve Coinbase cancellation through the project wrapper
  `cancel_order(client_order_id)`, which accepts only explicit Coinbase
  `success: true` cancel evidence as success.
- Treat exchange-native `order_id` as exchange evidence only. The order read
  model exposes it as `exchange_order_id`; it is not an identity or cancel key.
- Order list/detail read rows may include `correlation_id` and `audit_id`
  when the backend row source has durable evidence for them. These fields are
  audit navigation evidence, not order identity.
- Configure `COINBASE_ADMIN_API_BEARER_TOKEN` before exercising HTTP routes.
  Without it, routes fail closed with `401`.
- `COINBASE_ADMIN_API_AUTH_MODE=bootstrap_bearer` is the local/bootstrap
  verifier. `COINBASE_ADMIN_API_AUTH_MODE=oidc_jwt` verifies RS256 JWTs
  against the configured issuer, audience, and JWKS, then derives actor and
  role evidence from JWT claims.
- The `oidc_jwt` verifier readiness contract reports required
  `COINBASE_ADMIN_API_OIDC_ISSUER`,
  `COINBASE_ADMIN_API_OIDC_AUDIENCE`, and
  `COINBASE_ADMIN_API_OIDC_JWKS_URL` settings. Missing settings fail closed.

## Local Run

Run the existing FastAPI app directly when developing the enterprise frontend:

```powershell
python tools\run_admin_api.py --dev-token local-admin-token
```

The helper starts `api.v1.app:app` on `http://127.0.0.1:8787`, sets local CORS
for `http://127.0.0.1:3000`, and keeps live Coinbase execution disabled. It
does not import trading clients or submit/cancel exchange orders.

For a deployment-like local run, configure auth explicitly instead of using
`--dev-token`:

```powershell
$env:COINBASE_ADMIN_API_BEARER_TOKEN = "local-admin-token"
$env:COINBASE_ADMIN_API_CORS_ORIGINS = "http://127.0.0.1:3000"
python tools\run_admin_api.py --port 8787
```

`COINBASE_ADMIN_API_CORS_ORIGINS` is an allowlist, not a wildcard. The Admin
API accepts browser preflight requests only from configured origins and allows
the session/BFF bridge headers required by the frontend:
`Authorization`, `X-Admin-Actor`, `X-Admin-Roles`, `X-Correlation-Id`,
`X-Request-Id`, `X-Operator-Intent`, `Idempotency-Key`, and `X-CSRF-Token`.
Bearer tokens still belong on the backend/session boundary; do not expose them
through `NEXT_PUBLIC_*` frontend variables.

The frontend BFF may copy only documented response-evidence headers back to
browser code: `Content-Type`, `X-Correlation-Id`, `X-Request-Id`,
`X-Admin-Api-Version`, `X-Live-Execution-Enabled`, and
`X-Idempotency-Replayed`. Treat missing BFF authority as a session/transport
configuration failure, not as a live trading gate result.

Frontend `server_env_static` BFF authority is local/staging evidence only.
Production readiness requires frontend `backend_oidc_jwt` BFF mode and
backend `oidc_jwt` verifier configuration. Browser-visible RBAC remains a UI
hint; backend RBAC is the enforcement authority.
`GET /api/v1/admin/oidc-readiness` exposes backend OIDC verifier evidence for
release checks, including active auth mode, required/missing environment
settings, claim mapping, JWKS reachability, and no-live notional posture.

Run the no-live OIDC readiness smoke before treating production OIDC evidence
as usable by the frontend release gate:

```powershell
python tools\run_admin_oidc_readiness_smoke.py --summary-only
```

The smoke uses backend TestClient and temporary JWKS evidence to prove missing
config blocks, configured JWKS readiness reports ready, and `oidc_jwt`
session claims override forged browser actor/role headers. It does not contact
Coinbase and reports live Coinbase execution not run with notional `$0`.

CSRF enforcement is opt-in for cookie/session or BFF deployments:

```powershell
$env:COINBASE_ADMIN_API_CSRF_REQUIRED = "true"
$env:COINBASE_ADMIN_API_CSRF_TOKEN = "local-csrf-token"
```

When required, unsafe HTTP methods under `/api/v1/` must include
`X-CSRF-Token` matching the configured token. Read-only `GET` routes are not
blocked by CSRF middleware. Failed CSRF checks return structured `403` errors
with `X-Live-Execution-Enabled: false`.
`GET /api/v1/admin/csrf` exposes the CSRF posture, header name, token source,
and rotation policy without disclosing a token value.

## Must Not Do

- Do not implement live order behavior directly in FastAPI handlers.
- Do not duplicate guard, wallet, sizing, or Coinbase REST logic in the
  frontend.
- Do not treat frontend acknowledgement as sufficient enterprise approval.
- Do not expose Coinbase credentials to browser code.

## References

- [Admin API E2E Plan](docs/plans/ADMIN_API_E2E_PLAN.md)
- [Admin API Route Inventory](docs/plans/ADMIN_API_ROUTE_INVENTORY.md)
- [Admin API Examples](docs/examples/admin-api.md)
- [Frontend Association](docs/FRONTEND_ASSOCIATION.md)
- [Live Order Surfaces](docs/LIVE_ORDER_SURFACES.md)
- [API Reference](genai_data/API_REFERENCE.md)
- [Order ID Handling](genai_data/ORDER_ID_HANDLING.md)
- [Documentation Index](docs/README.md)
