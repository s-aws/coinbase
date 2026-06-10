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

## Release Rule

Any backend API contract change intended for frontend consumption must update:

- generated OpenAPI schema
- `README.admin-api.md` or relevant backend feature docs
- frontend generated client or contract tests
- backend regression gate when backend files changed
- frontend quality gate when frontend files changed
