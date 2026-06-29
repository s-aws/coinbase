# Movement And Repricing

This feature exposes movement and repricing evidence through the enterprise
Admin API. Read routes remain read-only. One live-disabled reprice command
draft exists so operators and frontend agents can review the eventual contract
without creating a second live repricing path.

## When To Use

Use these routes when an operator needs to inspect why an order or stealth
placement moved, what replacement-slot evidence exists, what repricing state is
durable, and whether runtime mutation claims were observable.

The routes are useful before command UI work because they make the existing
movement/repricing behavior inspectable without granting frontend authority.

## Routes

- `GET /api/v1/movement-repricing/evidence`
- `GET /api/v1/movement-repricing/orders/{client_order_id}`
- `GET /api/v1/movement-repricing/stealth/{stealth_order_id}`
- `POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice`

Read routes require Admin API authentication and `audit:read` permission. They
return `read_only=true`, `command_routes_mode=live_disabled`, and
`live_coinbase_orders_ran=false`. List and detail responses also return
`action_state_count` and `action_states`, which are backend-owned rows for the
Movement/Repricing action-state matrix.

The reprice command draft requires Admin API authentication, `order:cancel`,
idempotency headers, operator intent, and audit. The cancel-class permission
and action class are intentional: future live repricing is cancel/replace
shaped and must preserve revealed-placement exchange truth. The current
runtime returns HTTP `501` with `status=not_implemented`,
`service_method=reprice_stealth_order_by_stealth_order_id`, and
`live_exchange_submitted=false`.
For this module, dry-submit means posting the live-disabled command contract
and preserving the backend `501`, idempotency, audit, operator-intent, and
no-live evidence. It is not live repricing approval.

## Evidence Sources

- `order_moves`: parent move and premark history keyed by
  `original_parent_client_order_id` and `new_parent_client_order_id`.
- `stealth_order_moves`: revealed stealth cancel-and-replace audit rows keyed
  by `stealth_order_id`.
- `stealth_orders.anchor_repricing_state_json`: active placement, repricing,
  retreat, and exchange evidence for stealth orders.
- Runtime manager snapshots when available: in-flight
  `StealthMutationKind` claim states and pending replacement-slot claims.

Runtime claim evidence is marked with `runtime_observed`. If the runtime
manager is unavailable, the response reports that instead of pretending the
database proves no claim exists.

## Action-State Rows

Movement/Repricing action states are part of the backend contract. Frontend
code must render these rows and must not infer movement eligibility locally.

Rows use `AdminApiActionState` only:

- `usable`: read-only audit/evidence inspection is available.
- `blocked`: a route or workflow exists conceptually, but required backend
  gates or proofs are missing.
- `unsupported`: the workflow is intentionally not supported from the
  enterprise admin frontend.
- `not_modeled`: no enterprise admin command contract exists for the workflow.

The backend currently returns eight row families:

- `move`
- `premark`
- `reprice`
- `cooldown`
- `claim`
- `cancel_replace`
- `audit`
- `recovery`

`live_disabled` is a live-execution posture reported in
`live_execution_status` or `command_routes_mode`; it is not an action-state
value. The reprice row is `blocked` while the route remains a live-disabled
HTTP `501` command draft.

## Identity Rules

- Use `client_order_id` for order/placement tracking.
- Use `stealth_order_id` for stealth lifecycle tracking.
- Exchange-native ids are exposed as `active_exchange_order_id`,
  `old_exchange_order_id`, or `new_exchange_order_id` evidence only.
- Do not use exchange ids as local identity or cancellation keys.

## Safety Constraints

- The enterprise Admin API does not expose move, premark, or move-revealed
  command routes in this feature.
- The live-disabled reprice draft must not clear cooldowns, call
  `process_anchor_repricing_for_product`, cancel placements, replace
  placements, or invoke `StealthOrderManager` until the exchange-reality
  reconciliation path is explicitly wired.
- Legacy dashboard WebSocket commands remain compatibility surfaces.
- Revealed stealth placement truth must continue to come from the existing
  cancel/move/reprice/reconcile paths.
- Spot wallet, USDC, cost-basis, and no-shorting rules are not generic
  movement/repricing rules.

## Examples

See [Movement And Repricing Examples](docs/examples/movement-repricing.md).
