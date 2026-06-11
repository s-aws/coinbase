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
- frontend `npm run build`, `npm run release:check`,
  `npm run release:artifact`, `npm run deployment:package`,
  `npm run observability:drill`, `npm run deployment:check`, and dry-run smoke
  checks for release candidates

Frontend release checks are dry/no-live checks. They must report live Coinbase
execution as not run with notional `$0` and do not replace backend regression.
The frontend release artifact is `C:\coinbase-frontend\artifacts\release-readiness.json`;
CI uploads it as `frontend-release-readiness` instead of committing it.
The same CI artifact includes
`C:\coinbase-frontend\artifacts\deployment-package-manifest.json` and
`C:\coinbase-frontend\artifacts\observability-drill.json`.
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
evidence only. Production remains blocked until a real backend OIDC/JWT
session bridge exists and backend `oidc_jwt` verification is implemented.
