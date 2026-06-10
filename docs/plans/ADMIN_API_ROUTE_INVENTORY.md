# Admin API Route Inventory

This inventory must be updated before implementation adds, removes, or changes
an enterprise Admin API route or legacy dashboard compatibility message.

Every row names the action class, permission, idempotency requirement, approval
requirement, cap policy, audit requirement, shared command-service method, and
parity test target.

| Surface | Action class | Permission | Idempotency | Approval | Caps | Audit | Shared method | Parity test | Compatibility mode |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `POST /api/v1/orders` | `live_exchange_place` | `order:create` | required | required | required | required | `place_manual_order` | HTTP vs `place_order` guard/result parity | |
| `place_order` WebSocket | `live_exchange_place` | compatibility policy | enterprise-gated or compatibility-only | enterprise-gated or compatibility-only | required | required | `place_manual_order` | WebSocket vs HTTP guard/result parity | `compatibility_only` |
| `POST /api/v1/orders/{client_order_id}/cancel` | `live_exchange_cancel` | `order:cancel` | required | not required unless policy adds approval | required for rate/session controls | required | `cancel_order_by_client_order_id` | HTTP vs `cancel_order` parity | |
| `cancel_order` WebSocket | `live_exchange_cancel` | compatibility policy | enterprise-gated or compatibility-only | not required unless policy adds approval | required for rate/session controls | required | `cancel_order_by_client_order_id` | WebSocket vs HTTP parity | `compatibility_only` |
| read-only status routes | `read_only` | `analytics:read` | not required | not required | not applicable | optional read audit | read service method | no Coinbase REST placement | |

Legacy WebSocket live commands that are not passed through enterprise
idempotency, approval, and cap gates must stay compatibility-only, constrained
to localhost/operator mode, and excluded from new frontend product workflows.

