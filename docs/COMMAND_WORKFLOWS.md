# Command Workflows

This backend document explains how enterprise admin command evidence is exposed
without creating a second trading path.

The Admin API may expose command contracts, dry-submit evidence, and readiness
coverage for order, cancel, stealth, movement/repricing, approval, audit,
cap/guard, reconciliation, and campaign workflows. The backend remains the only
authority for trading behavior, wallet checks, guard checks, approval state,
reconciliation state, live adapter execution, and Coinbase calls.

## Current Contract

- Backend route inventory is the source of command route identity, action class,
  permissions, shared service method, and live designation.
- OpenAPI schemas are generated from backend FastAPI models and must be
  regenerated after contract changes.
- The frontend consumes generated contracts or typed wrappers only. It may
  display evidence, draft requests, and forward requests to backend routes when
  those routes exist, but it must not compute trading authority or call
  Coinbase.
- Live command execution stays disabled unless a backend route explicitly
  reports passing approval, cap/guard, admission audit, reconciliation, live
  adapter, and operator-intent gates.

## Spot Command Suite

`GET /api/v1/spot/command-suite` is read-only M54 evidence. It reports whether
manual spot order placement, spot cancel, and spot campaign execution have the
required backend gates and shared command-service wiring.

This route does not submit orders, cancel orders, launch campaigns, mutate
wallet or order state, or call Coinbase. Command rows use `mutation_family`
enum values such as `spot_manual_order`, `spot_order_cancel`, and
`spot_campaign_execution`. A row's `status` is gate status, while
`live_execution_status` is the live-execution posture.

Each command row also reports `proof_routes` for the backend-owned local-state
records that must exist before the command can become executable: approval
request/decision, admission audit, cap/guard decision, and reconciliation
plan. Those proof routes are derived from `ADMIN_API_ROUTE_INVENTORY`; the
frontend may display them but must not evaluate the gates, synthesize proof,
or treat them as live approval.

Each command row also reports `readiness_preconditions` by reusing
`AdminLiveReadinessPreconditionItem` from live-enablement evidence. These
preconditions show source, expected source, blocker, configured/blocking
state, and browser/BFF boundary for approval-store, approval snapshot,
admission audit, cap/guard, reconciliation, live adapter, execution-intent,
browser/BFF boundary, and live service gates. They are status evidence only;
they do not create proof records, evaluate gates in the browser, enable BFF
execution, or call Coinbase.

Website command workflow draft cards may display the same backend-owned
`readiness_preconditions` beside draft payload evidence for spot manual order,
cancel by `client_order_id`, and campaign execution. That display is a trace
back to command-suite evidence only; it must not evaluate readiness, create
proof records, enable commands, or copy spot wallet/no-shorting rules into
non-spot modules.

Spot cancel identity is `client_order_id`. Coinbase cancellation is the
project-specific exception where the backend wrapper calls
`cancel_order(client_order_id)` because the exchange accepts the client id for
that operation. Do not replace this with an exchange-native `order_id` flow.

## Boundaries

- Spot-only wallet, USDC, no-shorting, cost-basis, and average-cost rules must
  not become futures/perpetual, stealth, movement/repricing, or generic admin
  defaults.
- Frontend and BFF code remain display/forwarding surfaces. Button visibility
  is not authorization.
- Legacy dashboard WebSocket command surfaces are compatibility evidence only
  for enterprise admin planning and must not become the new frontend command
  path.

## Related References

- [Admin API](../README.admin-api.md)
- [Admin API Examples](examples/admin-api.md)
- [Admin API Route Inventory](plans/ADMIN_API_ROUTE_INVENTORY.md)
- [Admin Platform Durable Milestones](plans/ADMIN_PLATFORM_DURABLE_MILESTONES.md)
- [Agent Invariants](agents/INVARIANTS.md)
