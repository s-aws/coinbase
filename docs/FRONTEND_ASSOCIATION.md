# Frontend Association

Current cross-repository closeout is
`operator_ready_admin_mvp_runtime_v1`. This association document defines that
boundary; it grants no additional exchange or Slice authority. Slice 2R12 is
terminal consumed.

The approved enterprise admin frontend repository is:

```text
s-aws/coinbase-frontend
```

Expected local sibling checkout:

```text
/home/developer/coinbase/coinbase
/home/developer/coinbase/coinbase-frontend
```

Backend maintainer handoff starts at [Maintainer Handoff](MAINTAINER_HANDOFF.md).
Frontend maintainer handoff lives in
`/home/developer/coinbase/coinbase-frontend/docs/MAINTAINER_HANDOFF.md`.

## Contract Boundary

- Backend owns the Admin API, OpenAPI schema, auth/RBAC enforcement,
  idempotency, approval gates, caps, guard decisions, Coinbase calls, and
  durable audit.
- Frontend owns browser UI, operator intent capture, generated TypeScript API
  client, mocks, and browser tests.
- New product UI must consume the HTTP Admin API contract generated from this
  repository. It must not call the legacy dashboard WebSocket.
- HTTP command posture is route-specific. Manual Spot placement can reach the
  shared live service only after exact backend admission; other routes remain
  in No-live mode unless their route inventory and implementation prove
  otherwise.
- The enterprise admin surface is a platform plus domain modules. Spot is the
  first complete module; futures/perpetuals, stealth orders, repricing, and
  other modules need their own backend-owned contracts before frontend UI
  broadening.

## Schema Association

Backend schema source:

```text
openapi/coinbase-admin-api.yaml
```

Frontend generated output:

```text
/home/developer/coinbase/coinbase-frontend/src/shared/api/generated/schema.ts
```

Local Docker frontend validation reads this sibling backend checkout and fails
when generated output is stale. The retired GitHub-hosted workflow is not a
contract authority or routine validation path.

## Runtime Association

Local frontend runtime points at the Admin API base URL:

```text
NEXT_PUBLIC_ADMIN_API_BASE_URL=http://127.0.0.1:8787
```

This is an origin, not a credential. Do not expose backend bearer tokens,
Coinbase credentials, account secrets, or private prompts to the browser.

Deployment-like frontend runtime should use the same-origin BFF mode:

```text
NEXT_PUBLIC_ADMIN_API_MODE=bff
ADMIN_API_BASE_URL=http://127.0.0.1:8787
ADMIN_API_BEARER_TOKEN=<server-only backend token>
ADMIN_API_ACTOR_ID=<server-side actor>
ADMIN_API_ROLES=<server-side roles>
ADMIN_API_CSRF_TOKEN=<server-only csrf token when required>
```

Only `NEXT_PUBLIC_ADMIN_API_MODE` is browser-visible in that configuration.
The `ADMIN_API_*` values are server-only BFF authority and must not be exposed
through `NEXT_PUBLIC_*`.

The installed Linux operator review stack is managed from the sibling frontend with
`npm run review:refresh`, `npm run review:status`, and
`npm run review:stop`. It uses a protected random local Admin token per start.
Exact `COINBASE_EXECUTION_ENABLED=1` is the outer Controlled-live opt-in; every
other value selects No-live mode. Backend internal live flags cannot bypass it, and the
flag does not replace the manager-issued execution lease or command-specific
backend authorization.
Manager startup/status probes use call-free health and session routes. Once an
operator uses the UI, backend-authorized Coinbase reads or mutations may occur
only through the existing route-specific proof and execution path.

## Read Model Interaction Scope

The read-model sub-surface is read-only and uses this backend's Admin API
contract as the source of truth. The broader browser remains non-authoritative:
separately labeled operator controls may forward explicit requests through the
BFF, but every decision, Coinbase call, and mutation remains backend-owned. The
frontend may provide local display affordances over already-loaded
backend-shaped data:

- filter and sort order rows already returned by the read route
- select order detail evidence keyed by `client_order_id`
- render audit anchors for `client_order_id`, optional correlation id, and
  optional audit id
- switch campaign evidence tabs and filter evidence rows
- show deterministic empty, loading, auth-blocked, and backend-error states
- display Settings diagnostics and responsive table scroll regions

These are browser UX behaviors only. They are not wallet authority, guard
authority, Coinbase execution approval, profitability validation, or cancel
identity. Future mutations must still come from backend-owned command
contracts with auth, RBAC, idempotency, approval, cap, guard, and audit
evidence.

## Release Rule

Any backend API contract change intended for frontend consumption must update:

- generated OpenAPI schema
- `README.admin-api.md` or relevant backend feature docs
- frontend generated client or contract tests
- focused backend checks for ordinary backend changes
- full backend regression only for milestone, release/deployment, association
  closeout, or explicit-request gates
- when full backend regression is required, use
  `python3.13 tools/run_parallel_regression.py --workers 4`; sequential
  `pytest tests/regression/ -v --tb=short` is fallback-only when the parallel
  runner cannot be used
- frontend quality gate when frontend files changed
- frontend `npm run release:gate` for release candidates

`npm run release:gate` expands to build, typecheck, lint, generated API
freshness, command security, release/deployment checks, release artifact
generation, runtime evidence, deployment/MVP/backend smoke evidence, unit
tests, dry read/command/BFF smokes, and Playwright e2e.
Frontend release checks are dry No-live checks. They must report live Coinbase
execution as not run with notional `$0` and do not replace backend regression.
The frontend `npm run autonomous:check` command remains available for
historical autonomous queue maintenance. It is not part of the local operator
review stack release/deployment gate.
The frontend release artifact is `/home/developer/coinbase/coinbase-frontend/artifacts/release-readiness.json`;
it is generated and consumed locally rather than committed or uploaded by a
GitHub-hosted workflow. The same local artifact set includes
`/home/developer/coinbase/coinbase-frontend/artifacts/deployment-package-manifest.json` and
`/home/developer/coinbase/coinbase-frontend/artifacts/observability-drill.json`,
`/home/developer/coinbase/coinbase-frontend/artifacts/synthetic-probes.json`, and
`/home/developer/coinbase/coinbase-frontend/artifacts/public-release-checklist.json`, and
`/home/developer/coinbase/coinbase-frontend/artifacts/runtime-evidence.json`
(`artifacts/runtime-evidence.json` in the frontend checkout).
These artifacts are not approval for live Coinbase execution.
Read-only frontend rollback is a hosting/build rollback. Live-action rollback
is out of scope until live HTTP command execution is separately approved.

Frontend deployment validation must fail closed when BFF mode is missing
server-only `ADMIN_API_*` authority, when direct backend mode lacks
`NEXT_PUBLIC_ADMIN_API_BASE_URL`, or when browser-visible `NEXT_PUBLIC_*`
configuration contains secret-like keys. The backend remains the only trading
authority even when frontend deployment validation passes.

BFF response evidence back to browser code is limited to `Content-Type`,
`X-Correlation-Id`, `X-Request-Id`, `X-Admin-Api-Version`,
`X-Live-Execution-Enabled`, and `X-Idempotency-Replayed`.

Current frontend BFF authority is `server_env_static`, which is local/staging
evidence only. Production readiness requires frontend `backend_oidc_jwt` BFF
mode and backend `oidc_jwt` verifier configuration.

The backend OIDC/JWT verifier readiness contract reports required settings
for issuer, audience, and JWKS:

- `COINBASE_ADMIN_API_OIDC_ISSUER`
- `COINBASE_ADMIN_API_OIDC_AUDIENCE`
- `COINBASE_ADMIN_API_OIDC_JWKS_URL`

Backend release evidence for this boundary is available at
`GET /api/v1/admin/oidc-readiness`. It reports the active auth mode,
required/missing OIDC settings, claim mapping, JWKS reachability, and No-live
notional posture.

Machine-readable No-live backend smoke evidence is available as optional
production-auth evidence with:

```powershell
python3.13 tools/run_admin_oidc_readiness_smoke.py --summary-only
```

The frontend `npm run smoke:oidc:dry` command can run the same backend smoke
from the sibling checkout as optional production-auth evidence. It is not part
of the local operator review stack release/deployment gate and must report live Coinbase
execution as not run with notional `$0`.

Expected claim mapping is `sub` for subject, `email` for email, `roles` for
roles, `iss` for issuer, and `aud` for audience. In `backend_oidc_jwt` mode
the frontend BFF forwards only the configured OIDC cookie value as
`Authorization: Bearer <jwt>`; it must not forward browser-supplied
`X-Admin-Actor` or `X-Admin-Roles`. This is backend/session bridge evidence
only. It does not allow the frontend to enforce authorization or place backend
tokens in browser-visible variables.
The frontend BFF is also expected to enforce a documented Admin API route
allowlist before forwarding. Unsupported methods or route shapes are frontend
transport failures, not backend trading approval evidence.

Frontend staging environment template evidence may use `server_env_static`
BFF authority with server-only `ADMIN_API_*` values. Production readiness is
`conditional_on_oidc_configuration`: `backend_oidc_jwt` must be active and the
backend verifier must be configured.
