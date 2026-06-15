# Stealth Mutation-Claim Snapshot Proofs

Stealth mutation-claim snapshot proofs are backend-owned, append-only local
evidence for the enterprise Admin API. They let an operator persist one
route-bound snapshot showing that runtime mutation claims were safely observed
for a stealth move or movement/reprice command and that the active claim count
was zero.

Use this only after the backend has built the exact guarded command context for
a stealth move or movement/reprice command. The proof is local evidence for
command-execution posture; it is not claim ownership, claim release, cooldown
clearance, active-placement cancel/replace handling, reconciliation execution,
Coinbase exchange truth, browser authority, or live execution approval.

## Surfaces

- `GET /api/v1/stealth/orders/{stealth_order_id}/mutation-claim-proof`
- `POST /api/v1/stealth/orders/{stealth_order_id}/mutation-claim-proofs`

The POST route requires `stealth_mutation_claim:record`. It is authenticated,
authorized, idempotent, audited, and guarded by existing backend evidence
records for the proof route. It writes only local append-only evidence. It
does not call Coinbase, read Coinbase orders, acquire or release mutation
claims, invoke `StealthOrderManager`, submit or cancel orders, execute
reconciliation, cancel/replace active placements, or mutate order, exchange,
or lifecycle state.

## Identity And Guarded Context

- Internal identity is the path `stealth_order_id`.
- `client_order_id`, exchange ids, and `order_id` are not accepted as command
  identities.
- The request must include the guarded command context for exactly one move or
  reprice command:
  - `guarded_command_route`
  - `guarded_command_method`
  - `guarded_service_method`
  - `guarded_actor_id`
  - `guarded_operator_intent`
  - `guarded_idempotency_key`
  - `guarded_payload_hash`
  - `mutation_kind`
- Accepted guarded command routes are:
  - `/api/v1/stealth/orders/{stealth_order_id}/move` with
    `move_stealth_order_by_stealth_order_id`
  - `/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice` with
    `reprice_stealth_order_by_stealth_order_id`
- `runtime_claims_observed` must be `true`.
- `active_claim_count` must be `0`.

The proof route itself still needs its own backend approval snapshot,
admission audit, cap/guard decision, reconciliation plan, idempotency key,
operator intent, payload hash, and audit record. The guarded command fields
bind the proof to the later move/reprice command; they do not replace the
proof route's own gate chain.

## Resolver Behavior

Move and movement/reprice command execution posture may resolve
`mutation_claim_snapshot` from this proof store after the common backend gate
chain is present. Resolution is read-only and fail-closed.

The resolver reads the latest proof for the same `stealth_order_id`. If that
latest proof is unsafe, stale, or bound to a different route, actor,
idempotency key, operator intent, service method, or payload hash, the
prerequisite is reported missing. An older matching proof is not used to
override a newer unsafe or stale proof.

Accepted proof records keep `mutation_claim_snapshot_verified=false`,
`manager_invocation_ran=false`, `claim_acquire_ran=false`,
`claim_release_ran=false`, `coinbase_read_attempted=false`,
`coinbase_read_succeeded=false`, `coinbase_rest_read_ran=false`,
`coinbase_order_submitted=false`, `coinbase_order_cancel_submitted=false`,
`active_placement_cancel_replace_ran=false`,
`reconciliation_executed=false`, `order_state_mutated=false`,
`lifecycle_state_mutated=false`, `exchange_state_mutated=false`,
`live_exchange_submitted=false`, and `live_coinbase_orders_ran=false`.

## Key Files

- `application/admin_api/stealth_mutation_claim.py`
- `application/admin_api/stealth_mutation_claim_service.py`
- `application/admin_api/command_service.py`
- `application/admin_api/models.py`
- `application/admin_api/route_inventory.py`
- `application/admin_api/stealth_command_execution.py`
- `application/admin_api/read_service.py`
- `api/v1/routes/stealth.py`
- `api/v1/routes/movement_repricing.py`
- `docs/examples/stealth-mutation-claim-proofs.md`

Examples live in
[docs/examples/stealth-mutation-claim-proofs.md](docs/examples/stealth-mutation-claim-proofs.md).
