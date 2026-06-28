# Admin Lifecycle Support

`GET /api/v1/admin/enterprise-readiness` exposes the backend-owned lifecycle
support classification for Release 0.1.

The purpose is explicit backend authority, not a second process-control path.
The Admin API must say whether lifecycle actions are supported, unsupported,
or not modeled before the frontend can show any lifecycle controls.

## Current Classification

| Action | Status | Backend evidence |
| --- | --- | --- |
| `status` | `platform_ready` | Existing health/status evidence from `GET /api/v1/admin/health` and `RuntimeController.state`. |
| `start` | `unsupported` | A running backend process cannot start the same process after it is stopped; this requires an external supervisor contract. |
| `stop` | `not_modeled` | `RuntimeController.drain_and_stop` exists internally, but no enterprise Admin API route models authorization, audit, operator intent, timeout, or result evidence. |
| `pause` | `platform_ready` | `POST /api/v1/admin/lifecycle/pause` models authorization, RBAC, idempotency, operator intent, audit, expected-state checks, and `RuntimeController.request_pause`. |
| `resume` | `platform_ready` | `POST /api/v1/admin/lifecycle/resume` models authorization, RBAC, idempotency, operator intent, audit, expected-state checks, and `RuntimeController.resume`. |
| `drain` | `platform_ready` | `POST /api/v1/admin/lifecycle/drain` models authorization, RBAC, idempotency, operator intent, timeout, audit, `RuntimeController.request_shutdown`, and `RuntimeController.wait_drain` without marking the runtime stopped. |

## Non-Authority Rules

- Do not expose dashboard WebSocket lifecycle commands as enterprise Admin API
  authority.
- Do not add route-local process control that bypasses auth, RBAC, operator
  intent, audit, idempotency, and result evidence.
- Do not mark lifecycle behavior supported because an internal
  `RuntimeController` method exists.
- Do not treat drain as stop. Drain enters draining mode and waits for tracked
  in-flight work; it does not invoke stop hooks or mark `STOPPED`.
- Do not call Coinbase or submit/cancel orders from lifecycle support
  classification.

## Evidence Fields

Each lifecycle row includes `action`, `support_status`, `exposure_status`,
`current_state_source`, optional `supported_route` and `supported_method`,
`release_0_1_decision`, backend/frontend/doc refs, `frontend_boundary`,
`browser_authority`, `bff_execution_authority`,
`dashboard_websocket_fallback_allowed`, `live_coinbase_execution`, and
`notional_usdc`.

Example payload:
[Admin Lifecycle Support Example](examples/admin-lifecycle-support.md)
