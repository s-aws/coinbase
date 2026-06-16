# Stealth Manager-Invocation Policy

Stealth manager-invocation policy records are backend-owned, append-only local
evidence for the enterprise Admin API. They let an operator persist one
route-bound proof record for a future guarded stealth command without invoking
`StealthOrderManager`, reading Coinbase, submitting or cancelling Coinbase
orders, cancelling/replacing active placements, executing reconciliation, or
mutating order, exchange, or lifecycle state.

Use this only after the backend has built the exact guarded command context
for the stealth command being reviewed. The proof is local evidence for
command-execution posture; it is not manager invocation, exchange-state truth,
browser authority, or live execution approval.

## Surfaces

- `GET /api/v1/stealth/orders/{stealth_order_id}/manager-invocation-policy`
- `POST /api/v1/stealth/orders/{stealth_order_id}/manager-invocation-policy-proofs`

The POST route requires `stealth_manager_policy:record`. It is
authenticated, authorized, idempotent, audited, and guarded by existing
backend evidence records for the proof route. It writes only local
append-only evidence. It does not call Coinbase, read Coinbase orders, invoke
`StealthOrderManager`, submit or cancel orders, cancel/replace active
placements, execute reconciliation, or mutate order, exchange, or lifecycle
state.

## Identity And Guarded Context

- Internal identity is the path `stealth_order_id`.
- `client_order_id`, exchange ids, active placement ids, and `order_id` are
  evidence only.
- The request must include the guarded command context for exactly one
  supported stealth command:
  - `guarded_command_route`
  - `guarded_command_method`
  - `guarded_service_method`
  - `guarded_actor_id`
  - `guarded_operator_intent`
  - `guarded_idempotency_key`
  - `guarded_payload_hash`
  - `manager_policy_ref`
  - `mutation_lock_policy_ref`
  - `exchange_reality_policy_ref`
- Proof records must be dry-run evidence and must not include manual live
  acknowledgement.

The proof route itself still needs its own backend approval snapshot,
admission audit, cap/guard decision, reconciliation plan, idempotency key,
operator intent, payload hash, and audit record. The guarded command fields
bind the proof to the reviewed command; they do not replace the proof route's
own gate chain.

## Boundary

Accepted proof records keep `manager_invocation_allowed=false`,
`manager_invocation_ran=false`, `coinbase_read_attempted=false`,
`coinbase_read_succeeded=false`, `coinbase_rest_read_ran=false`,
`coinbase_order_submitted=false`, `coinbase_order_cancel_submitted=false`,
`active_placement_cancel_replace_ran=false`,
`reconciliation_executed=false`, `order_state_mutated=false`,
`lifecycle_state_mutated=false`, `exchange_state_mutated=false`,
`live_exchange_submitted=false`, and `live_coinbase_orders_ran=false`.

## Key Files

- `application/admin_api/stealth_manager_policy.py`
- `application/admin_api/stealth_manager_policy_service.py`
- `application/admin_api/command_service.py`
- `application/admin_api/models.py`
- `application/admin_api/route_inventory.py`
- `application/admin_api/read_service.py`
- `api/v1/routes/stealth.py`
- `docs/examples/stealth-manager-invocation-policy.md`

Examples live in
[docs/examples/stealth-manager-invocation-policy.md](docs/examples/stealth-manager-invocation-policy.md).
