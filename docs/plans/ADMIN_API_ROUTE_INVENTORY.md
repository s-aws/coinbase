# Admin API Route Inventory

This inventory must be updated before implementation adds, removes, or changes
an enterprise Admin API route or legacy dashboard compatibility message.

Every row names the action class, permission, idempotency requirement, approval
requirement, cap policy, audit requirement, shared command-service method, and
parity test target.

| Surface | Action class | Permission | Idempotency | Approval | Caps | Audit | Shared method | Parity test | Compatibility mode |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `POST /api/v1/orders` | `live_exchange_place` | `order:create` | required | required | required | required | `place_manual_order` | HTTP vs `place_order` guard/result parity | |
| `GET /api/v1/orders` | `read_only` | `audit:read` | not required | not required | not applicable | optional read audit | `build_order_list` | no Coinbase REST placement | |
| `GET /api/v1/orders/{client_order_id}` | `read_only` | `audit:read` | not required | not required | not applicable | optional read audit | `build_order_detail` | client_order_id identity only | |
| `place_order` WebSocket | `live_exchange_place` | compatibility policy | enterprise-gated or compatibility-only | enterprise-gated or compatibility-only | required | required | `place_manual_order` | WebSocket vs HTTP guard/result parity | `compatibility_only` |
| `place_hotpoint_test_order` WebSocket | `live_exchange_place` | compatibility policy | enterprise-gated or compatibility-only | enterprise-gated or compatibility-only | required | required | `place_hotpoint_test_order` | WebSocket vs shared-service hotpoint guard/result parity | `compatibility_only` |
| `POST /api/v1/orders/{client_order_id}/cancel` | `live_exchange_cancel` | `order:cancel` | required | required by current HTTP live-disabled gate | required for rate/session controls | required | `cancel_order_by_client_order_id` | HTTP vs `cancel_order` parity | |
| `POST /api/v1/spot/campaign/executions` | `live_exchange_place` | `campaign:execute` | required | required | required | required | `execute_spot_campaign` | campaign execution remains fail-closed until live gates pass | |
| `cancel_order` WebSocket | `live_exchange_cancel` | compatibility policy | enterprise-gated or compatibility-only | not required unless policy adds approval | required for rate/session controls | required | `cancel_order_by_client_order_id` | WebSocket vs HTTP parity | `compatibility_only` |
| `GET /api/v1/admin/bootstrap` | `read_only` | `analytics:read` | not required | not required | not applicable | optional read audit | `build_admin_bootstrap` | backend association and live-disabled posture | |
| `GET /api/v1/admin/health` | `read_only` | `analytics:read` | not required | not required | not applicable | optional read audit | `build_admin_health` | no Coinbase REST placement | |
| `GET /api/v1/admin/session` | `read_only` | authenticated actor | not required | not required | not applicable | optional read audit | `build_admin_session` | backend RBAC evidence only | |
| `GET /api/v1/admin/oidc-readiness` | `read_only` | `analytics:read` | not required | not required | not applicable | optional read audit | `build_oidc_jwt_readiness` | backend OIDC verifier readiness evidence only | |
| `GET /api/v1/admin/capabilities` | `read_only` | `analytics:read` | not required | not required | not applicable | optional read audit | `build_admin_capabilities` | route inventory derived registry | |
| `GET /api/v1/admin/csrf` | `read_only` | `analytics:read` | not required | not required | not applicable | optional read audit | `build_csrf_contract` | does not disclose token value | |
| `GET /api/v1/admin/release-gate` | `read_only` | `analytics:read` | not required | not required | not applicable | optional read audit | `build_release_gate` | browser does not run pytest | |
| `GET /api/v1/admin/recovery-gate` | `read_only` | `audit:read` | not required | not required | not applicable | optional read audit | `build_recovery_gate` | read-only recovery evidence | |
| `GET /api/v1/admin/fill-ledger-health` | `read_only` | `audit:read` | not required | not required | not applicable | optional read audit | `build_fill_ledger_health` | no ledger repair mutation | |
| `GET /api/v1/admin/frontend-fixtures` | `read_only` | `analytics:read` | not required | not required | not applicable | optional read audit | `build_frontend_fixtures` | backend-owned mock fixture examples | |
| `GET /api/v1/spot/readiness` | `read_only` | `analytics:read` | not required | not required | not applicable | optional read audit | `build_spot_readiness` | no Coinbase REST placement | |
| `GET /api/v1/spot/sweep/status` | `read_only` | `analytics:read` | not required | not required | not applicable | optional read audit | `build_spot_sweep_status` | no Coinbase REST placement | |
| `GET /api/v1/spot/sweep/pnl` | `read_only` | `analytics:read` | not required | not required | not applicable | optional read audit | `build_spot_sweep_pnl` | no Coinbase REST placement | |
| `GET /api/v1/spot/cost-basis/status` | `read_only` | `analytics:read` | not required | not required | not applicable | optional read audit | `build_spot_cost_basis_status` | no Coinbase REST placement | |
| `GET /api/v1/spot/campaign/status` | `read_only` | `campaign:read` | not required | not required | not applicable | optional read audit | `build_spot_campaign_status` | no Coinbase REST placement | |
| `GET /api/v1/spot/direct-orders/{client_order_id}/audit` | `read_only` | `audit:read` | not required | not required | not applicable | optional read audit | `build_spot_direct_order_audit` | no Coinbase REST placement | |

Legacy WebSocket live commands that are not passed through enterprise
idempotency, approval, and cap gates must stay compatibility-only, constrained
to localhost/operator mode, and excluded from new frontend product workflows.
