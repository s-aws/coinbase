# Frontend Association

The approved enterprise admin frontend repository is:

```text
s-aws/coinbase-frontend
```

Expected local sibling checkout:

```text
C:\coinbase
C:\coinbase-frontend
```

## Contract Boundary

- Backend owns the Admin API, OpenAPI schema, auth/RBAC enforcement,
  idempotency, approval gates, caps, guard decisions, Coinbase calls, and
  durable audit.
- Frontend owns browser UI, operator intent capture, generated TypeScript API
  client, mocks, and browser tests.
- New product UI must consume the HTTP Admin API contract generated from this
  repository. It must not call the legacy dashboard WebSocket.
- HTTP mutating routes remain live-disabled until backend approval/cap/audit
  gates are completed and tested.

## Schema Association

Backend schema source:

```text
openapi/coinbase-admin-api.yaml
```

Frontend generated output:

```text
C:\coinbase-frontend\src\shared\api\generated\schema.ts
```

Frontend CI checks this repository out with a read-only deploy key and fails
when generated output is stale.

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

## Release Rule

Any backend API contract change intended for frontend consumption must update:

- generated OpenAPI schema
- `README.admin-api.md` or relevant backend feature docs
- frontend generated client or contract tests
- backend regression gate when backend files changed
- frontend quality gate when frontend files changed
- frontend `npm run release:gate` for release candidates

`npm run release:gate` expands to build, typecheck, lint, generated API
freshness, command security, release/deployment checks, release artifact
generation, runtime evidence, autonomous queue validation, unit tests, dry
read/command/BFF/OIDC smokes, and Playwright e2e.
Frontend release checks are dry/no-live checks. They must report live Coinbase
execution as not run with notional `$0` and do not replace backend regression.
The frontend release artifact is `C:\coinbase-frontend\artifacts\release-readiness.json`;
CI uploads it as `frontend-release-readiness` instead of committing it.
The same CI artifact includes
`C:\coinbase-frontend\artifacts\deployment-package-manifest.json` and
`C:\coinbase-frontend\artifacts\observability-drill.json`,
`C:\coinbase-frontend\artifacts\synthetic-probes.json`, and
`C:\coinbase-frontend\artifacts\public-release-checklist.json`, and
`C:\coinbase-frontend\artifacts\runtime-evidence.json`
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
required/missing OIDC settings, claim mapping, JWKS reachability, and no-live
notional posture.

Machine-readable no-live backend smoke evidence is available with:

```powershell
python tools\run_admin_oidc_readiness_smoke.py --summary-only
```

The frontend release gate runs the same backend smoke through
`npm run smoke:oidc:dry` from the sibling checkout. That cross-repo smoke must
report live Coinbase execution as not run with notional `$0`.

Expected claim mapping is `sub` for subject, `email` for email, `roles` for
roles, `iss` for issuer, and `aud` for audience. In `backend_oidc_jwt` mode
the frontend BFF forwards only the configured OIDC cookie value as
`Authorization: Bearer <jwt>`; it must not forward browser-supplied
`X-Admin-Actor` or `X-Admin-Roles`. This is backend/session bridge evidence
only. It does not allow the frontend to enforce authorization or place backend
tokens in browser-visible variables.

Frontend staging environment template evidence may use `server_env_static`
BFF authority with server-only `ADMIN_API_*` values. Production readiness is
`conditional_on_oidc_configuration`: `backend_oidc_jwt` must be active and the
backend verifier must be configured.
