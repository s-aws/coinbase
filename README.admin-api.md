# Admin API

This repository will expose the professional backend API for the separate
enterprise admin frontend at `C:\coinbase-frontend`.
The repository association is documented in
[Frontend Association](docs/FRONTEND_ASSOCIATION.md).

## Current Status

The repository now contains an Admin API contract, generated OpenAPI artifact,
fail-closed auth/RBAC bootstrap, durable JSONL idempotency/audit stores, and
read-only spot operator routes. Mutating HTTP routes still return
`not_implemented` after auth, permission, idempotency, and audit handling; they
do not submit orders, cancel orders, or call Coinbase.

The generated OpenAPI contract intentionally documents `501` as the current
default mutating-route response, not `200`. Read-only spot routes document
`401` and `403` because they use the same fail-closed auth/RBAC dependency.

The legacy dashboard `place_order`, `cancel_order`, and
`place_hotpoint_test_order` WebSocket messages now delegate to
`application.admin_api.command_service.AdminApiCommandService` as compatibility
adapters. New product UI must use the HTTP API contract, not the dashboard
WebSocket.

Mutating HTTP command responses include the current fail-closed live execution
gate decision. The gate reports that approval snapshots, cap evaluation, and
durable audit are required before HTTP live execution can be enabled.

The current operational dashboard is still the proof-of-concept WebSocket and
HTML surface documented in `agent.md` and `genai_data/API_REFERENCE.md`.
For the current boundary between legacy live WebSocket commands, read-only
HTTP routes, and sweep/campaign execution, see
[Live Order Surfaces](docs/LIVE_ORDER_SURFACES.md).

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
- Configure `COINBASE_ADMIN_API_BEARER_TOKEN` before exercising HTTP routes.
  Without it, routes fail closed with `401`.

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
