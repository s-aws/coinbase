# Stealth Cancel/Replace Proofs

Stealth cancel/replace proofs are backend-owned, append-only local evidence for
the enterprise Admin API. They let an operator persist one route-bound proof
record for a future stealth cancel, stealth move, or movement reprice command
without building cancel/replace plans, invoking managers, reading Coinbase,
submitting or cancelling Coinbase orders, executing reconciliation, or
mutating order, exchange, or lifecycle state.

Use this only after the backend has built the exact guarded command context for
one of these commands:

- `POST /api/v1/stealth/orders/{stealth_order_id}/cancel`
- `POST /api/v1/stealth/orders/{stealth_order_id}/move`
- `POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice`

The proof is local evidence for command-execution posture. It is not
cancel/replace execution, exchange-state truth, browser authority, or live
execution approval.

## Surfaces

- `GET /api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proof`
- `POST /api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proofs`

The POST route requires `stealth_cancel_replace:record`. It is authenticated,
authorized, idempotent, audited, and guarded by existing backend evidence
records for the proof route. It writes only local append-only evidence. It
does not call Coinbase, read Coinbase orders, invoke `StealthOrderManager`,
build cancel/replace plans, submit or cancel orders, cancel/replace active
placements, execute reconciliation, or mutate order, exchange, or lifecycle
state.

## Identity And Guarded Context

- Internal identity is the path `stealth_order_id`.
- `client_order_id`, exchange ids, and `order_id` are not accepted as command
  identities.
- The request must include the guarded command context for exactly one
  supported command:
  - `guarded_command_route`
  - `guarded_command_method`
  - `guarded_service_method`
  - `guarded_mutation_family`
  - `guarded_actor_id`
  - `guarded_operator_intent`
  - `guarded_idempotency_key`
  - `guarded_payload_hash`
  - `active_placement_evidence_ref`
  - `mutation_claim_evidence_ref` for move and reprice
  - `cancel_replace_evidence_ref`
- Accepted guarded command routes:
  - `/api/v1/stealth/orders/{stealth_order_id}/cancel` with
    `cancel_stealth_order_by_stealth_order_id`
  - `/api/v1/stealth/orders/{stealth_order_id}/move` with
    `move_stealth_order_by_stealth_order_id`
  - `/api/v1/movement-repricing/stealth/{stealth_order_id}/reprice` with
    `reprice_stealth_order_by_stealth_order_id`
- Proof records must be dry-run evidence and must not include manual live
  acknowledgement.

The proof route itself still needs its own backend approval snapshot,
admission audit, cap/guard decision, reconciliation plan, idempotency key,
operator intent, payload hash, and audit record. The guarded command fields
bind the proof to the later cancel, move, or reprice command; they do not
replace the proof route's own gate chain.

`active_placement_evidence_ref`, `mutation_claim_evidence_ref`, and
`cancel_replace_evidence_ref` are opaque operator/backend references in this
writer. The service validates that required refs are present and that the
guarded command context matches a supported route, but it does not dereference
those refs, verify another proof-store row, read Coinbase, or make the refs
execution authority.

## Readback Behavior

The readback route returns recent proof records for one `stealth_order_id` and
the latest proof id. It is read-only evidence for operators and frontend
display. It does not resolve proof records as execution authority, call
Coinbase, build plans, invoke managers, cancel or replace placements, execute
reconciliation, mutate state, or grant browser/BFF execution authority.
Live-disabled command responses may also expose disabled live-service,
live-adapter, post-write reconciliation, canonical execution path, and
boundary-authority fields alongside `cancel_replace_proof` resolver evidence.
Those fields describe the backend-owned future handoff only; they do not
construct adapters, call managers or Coinbase, execute reconciliation, mutate
state, or authorize browser/BFF commands.

Accepted proof records keep `cancel_replace_proof_verified=false`,
`manager_invocation_ran=false`, `cancel_replace_plan_built=false`,
`coinbase_read_attempted=false`, `coinbase_read_succeeded=false`,
`coinbase_rest_read_ran=false`, `coinbase_order_submitted=false`,
`coinbase_order_cancel_submitted=false`,
`active_placement_cancel_replace_ran=false`,
`reconciliation_executed=false`, `order_state_mutated=false`,
`lifecycle_state_mutated=false`, `exchange_state_mutated=false`,
`live_exchange_submitted=false`, and `live_coinbase_orders_ran=false`.

## Execution-Contract Resolver Behavior

Live-disabled stealth cancel, stealth move, and movement reprice command
responses may resolve the `cancel_replace_proof` prerequisite from this store.
Resolution is exact-context and fail-closed: the latest same-`stealth_order_id`
record must match the command route, method, shared service method, actor,
operator intent, idempotency key, payload hash, and mutation family. The record
must also remain safe no-live evidence with no manager invocation, no
cancel/replace plan, no Coinbase read/submit/cancel, no active-placement
cancel/replace, no reconciliation execution, and no state mutation.

A resolved `cancel_replace_proof` removes only that missing prerequisite. It
does not resolve active-placement exchange truth, mutation-claim snapshots,
live service, live adapter, or post-write reconciliation. An unsafe or
mismatched latest record is reported as stale/invalid and the prerequisite
stays missing.

## Key Files

- `application/admin_api/stealth_cancel_replace_proof.py`
- `application/admin_api/stealth_cancel_replace_proof_service.py`
- `application/admin_api/command_service.py`
- `application/admin_api/models.py`
- `application/admin_api/route_inventory.py`
- `application/admin_api/read_service.py`
- `api/v1/routes/stealth.py`
- `docs/examples/stealth-cancel-replace-proofs.md`

Examples live in
[docs/examples/stealth-cancel-replace-proofs.md](docs/examples/stealth-cancel-replace-proofs.md).
