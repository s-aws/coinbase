# Stealth Reconciliation Proofs

Stealth reconciliation proofs are backend-owned, append-only local evidence for
the enterprise Admin API. They let an operator persist one route-bound proof
record for a future stealth reconciliation command without running
reconciliation, invoking managers, reading Coinbase, cancelling/replacing
active placements, submitting Coinbase orders, or mutating order, exchange, or
lifecycle state.

Use this only after the backend has built the exact guarded command context for
`POST /api/v1/stealth/orders/{stealth_order_id}/reconciliation`. The proof is
local evidence for command-execution posture; it is not reconciliation
execution, exchange-state truth, browser authority, or live execution approval.

## Surfaces

- `GET /api/v1/stealth/orders/{stealth_order_id}/reconciliation-proof`
- `POST /api/v1/stealth/orders/{stealth_order_id}/reconciliation-proofs`

The POST route requires `stealth_reconciliation:record`. It is authenticated,
authorized, idempotent, audited, and guarded by existing backend evidence
records for the proof route. It writes only local append-only evidence. It
does not call Coinbase, read Coinbase orders, invoke `StealthOrderManager`,
build or execute reconciliation plans, submit or cancel orders, cancel/replace
active placements, execute reconciliation, or mutate order, exchange, or
lifecycle state.

## Identity And Guarded Context

- Internal identity is the path `stealth_order_id`.
- `client_order_id`, exchange ids, and `order_id` are not accepted as command
  identities.
- The request must include the guarded command context for exactly one
  reconciliation command:
  - `guarded_command_route`
  - `guarded_command_method`
  - `guarded_service_method`
  - `guarded_actor_id`
  - `guarded_operator_intent`
  - `guarded_idempotency_key`
  - `guarded_payload_hash`
  - `reconciliation_evidence_ref`
  - `reconciliation_plan_ref`
  - `active_placement_evidence_ref`
- Accepted guarded command route:
  - `/api/v1/stealth/orders/{stealth_order_id}/reconciliation` with
    `reconcile_stealth_order_by_stealth_order_id`
- Proof records must be dry-run evidence and must not include manual live
  acknowledgement.

The proof route itself still needs its own backend approval snapshot,
admission audit, cap/guard decision, reconciliation plan, idempotency key,
operator intent, payload hash, and audit record. The guarded command fields
bind the proof to the later reconciliation command; they do not replace the
proof route's own gate chain.

## Resolver Behavior

Stealth reconciliation command execution posture may resolve
`reconciliation_proof` from this proof store after the common backend gate
chain and active-placement exchange-truth prerequisite are present. Resolution
is read-only and fail-closed.

The resolver reads the latest proof for the same `stealth_order_id`. If that
latest proof is unsafe, stale, or bound to a different route, actor,
idempotency key, operator intent, service method, or payload hash, the
prerequisite is reported missing. An older matching proof is not used to
override a newer unsafe or stale proof.

Accepted proof records keep `reconciliation_proof_verified=false`,
`manager_invocation_ran=false`, `reconciliation_plan_built=false`,
`reconciliation_execution_ran=false`, `coinbase_read_attempted=false`,
`coinbase_read_succeeded=false`, `coinbase_rest_read_ran=false`,
`coinbase_order_submitted=false`, `coinbase_order_cancel_submitted=false`,
`active_placement_cancel_replace_ran=false`,
`reconciliation_executed=false`, `order_state_mutated=false`,
`lifecycle_state_mutated=false`, `exchange_state_mutated=false`,
`live_exchange_submitted=false`, and `live_coinbase_orders_ran=false`.

## Key Files

- `application/admin_api/stealth_reconciliation_proof.py`
- `application/admin_api/stealth_reconciliation_proof_service.py`
- `application/admin_api/command_service.py`
- `application/admin_api/models.py`
- `application/admin_api/route_inventory.py`
- `application/admin_api/stealth_command_execution.py`
- `application/admin_api/read_service.py`
- `api/v1/routes/stealth.py`
- `docs/examples/stealth-reconciliation-proofs.md`

Examples live in
[docs/examples/stealth-reconciliation-proofs.md](docs/examples/stealth-reconciliation-proofs.md).
