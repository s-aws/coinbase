# Stealth Reveal-Trigger Proofs

Stealth reveal-trigger proofs are backend-owned, append-only local evidence for
the enterprise Admin API. They let an operator persist one route-bound proof
record for a future stealth reveal command without evaluating triggers, calling
`should_trigger_reveal`, calling `reveal_order_slice`, invoking managers,
calling Coinbase, executing reconciliation, or mutating lifecycle state.

Use this only after the backend has built the exact guarded command context for
`POST /api/v1/stealth/orders/{stealth_order_id}/reveal`. The proof is local
evidence for command-execution posture; it is not trigger evaluation, exchange
submission, active-placement creation, browser authority, or live execution
approval.

## Surfaces

- `GET /api/v1/stealth/orders/{stealth_order_id}/reveal-trigger-proof`
- `POST /api/v1/stealth/orders/{stealth_order_id}/reveal-trigger-proofs`

The POST route requires `stealth_reveal_trigger:record`. It is authenticated,
authorized, idempotent, audited, and guarded by existing backend evidence
records for the proof route. It writes only local append-only evidence. It
does not call Coinbase, read Coinbase orders, invoke `StealthOrderManager`,
evaluate triggers, call `should_trigger_reveal`, call `reveal_order_slice`,
submit or cancel orders, execute reconciliation, cancel/replace active
placements, or mutate order, exchange, or lifecycle state.

## Identity And Guarded Context

- Internal identity is the path `stealth_order_id`.
- `client_order_id`, exchange ids, and `order_id` are not accepted as command
  identities.
- The request must include the guarded command context for exactly one reveal
  command:
  - `guarded_command_route`
  - `guarded_command_method`
  - `guarded_service_method`
  - `guarded_actor_id`
  - `guarded_operator_intent`
  - `guarded_idempotency_key`
  - `guarded_payload_hash`
  - `reveal_condition_ref`
  - `trigger_evidence_ref`
  - `condition_snapshot_ref`
- Accepted guarded command route:
  - `/api/v1/stealth/orders/{stealth_order_id}/reveal` with
    `reveal_stealth_order_by_stealth_order_id`
- Proof records must be dry-run evidence and must not include manual live
  acknowledgement.

The proof route itself still needs its own backend approval snapshot,
admission audit, cap/guard decision, reconciliation plan, idempotency key,
operator intent, payload hash, and audit record. The guarded command fields
bind the proof to the later reveal command; they do not replace the proof
route's own gate chain.

## Resolver Behavior

Stealth reveal command execution posture may resolve
`reveal_trigger_evidence` from this proof store after the common backend gate
chain is present. Resolution is read-only and fail-closed.

The resolver reads the latest proof for the same `stealth_order_id`. If that
latest proof is unsafe, stale, or bound to a different route, actor,
idempotency key, operator intent, service method, or payload hash, the
prerequisite is reported missing. An older matching proof is not used to
override a newer unsafe or stale proof.

Accepted proof records keep `reveal_trigger_verified=false`,
`manager_invocation_ran=false`, `trigger_evaluation_ran=false`,
`should_trigger_reveal_called=false`, `reveal_order_slice_called=false`,
`coinbase_read_attempted=false`, `coinbase_read_succeeded=false`,
`coinbase_rest_read_ran=false`, `coinbase_order_submitted=false`,
`coinbase_order_cancel_submitted=false`,
`active_placement_cancel_replace_ran=false`,
`reconciliation_executed=false`, `order_state_mutated=false`,
`lifecycle_state_mutated=false`, `exchange_state_mutated=false`,
`live_exchange_submitted=false`, and `live_coinbase_orders_ran=false`.

## Key Files

- `application/admin_api/stealth_reveal_trigger_proof.py`
- `application/admin_api/stealth_reveal_trigger_proof_service.py`
- `application/admin_api/command_service.py`
- `application/admin_api/models.py`
- `application/admin_api/route_inventory.py`
- `application/admin_api/stealth_command_execution.py`
- `application/admin_api/read_service.py`
- `api/v1/routes/stealth.py`
- `docs/examples/stealth-reveal-trigger-proofs.md`

Examples live in
[docs/examples/stealth-reveal-trigger-proofs.md](docs/examples/stealth-reveal-trigger-proofs.md).
