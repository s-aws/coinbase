# Stealth State-Mutation Policy

Stealth state-mutation policy records are backend-owned, append-only local
evidence for the enterprise Admin API. They let an operator persist one
route-bound proof record for a future guarded stealth command without
authorizing or performing lifecycle, order, or exchange-state mutation.

Use this only after the backend has built the exact guarded command context
for the stealth command being reviewed. The proof is local evidence for a
future state-mutation policy resolver. It is not state mutation, Coinbase
exchange truth, live Coinbase approval, reconciliation execution, browser
authority, or BFF execution authority.

## Surfaces

- `GET /api/v1/stealth/orders/{stealth_order_id}/state-mutation-policy`
- `POST /api/v1/stealth/orders/{stealth_order_id}/state-mutation-policy-proofs`

The POST route requires `stealth_state_mutation_policy:record`. It is
authenticated, authorized, idempotent, audited, and guarded by existing backend
admission evidence records for the proof route. It writes only local
append-only evidence. It does not mutate lifecycle, order, or exchange state;
call Coinbase; read Coinbase orders; submit or cancel orders; invoke
`StealthOrderManager`; cancel/replace active placements; or execute
reconciliation.

## Identity And Guarded Context

- Internal identity is the path `stealth_order_id`.
- `client_order_id`, active placement ids, exchange ids, and `order_id` are
  evidence only.
- The request must include the guarded command context for exactly one
  supported stealth command:
  - `guarded_command_route`
  - `guarded_command_method`
  - `guarded_service_method`
  - `guarded_mutation_family`
  - `guarded_actor_id`
  - `guarded_operator_intent`
  - `guarded_idempotency_key`
  - `guarded_payload_hash`
  - `state_mutation_policy_ref`
  - `lifecycle_state_policy_ref`
  - `order_state_policy_ref`
  - `exchange_state_policy_ref`
  - `post_write_reconciliation_policy_ref`
- Proof records must be dry-run evidence and must not include manual live
  acknowledgement.

The proof route itself still needs its own backend approval snapshot,
admission audit, cap/guard decision, reconciliation plan, idempotency key,
operator intent, payload hash, and audit record. The guarded command fields
bind the proof to the reviewed command; they do not replace the proof route's
own gate chain.

## Boundary

Accepted proof records keep `state_mutation_policy_verified=false`,
`state_mutation_allowed=false`, `lifecycle_state_mutation_allowed=false`,
`order_state_mutation_allowed=false`, `exchange_state_mutation_allowed=false`,
`manager_invocation_ran=false`, `coinbase_read_attempted=false`,
`coinbase_read_succeeded=false`, `coinbase_rest_read_ran=false`,
`coinbase_order_submitted=false`, `coinbase_order_cancel_submitted=false`,
`active_placement_cancel_replace_ran=false`,
`reconciliation_executed=false`, `order_state_mutated=false`,
`lifecycle_state_mutated=false`, `exchange_state_mutated=false`,
`live_exchange_submitted=false`, and `live_coinbase_orders_ran=false`.

Browser surfaces may display the evidence only. The BFF may forward to the
backend route only; it must not become a state-mutation executor,
reconciliation executor, manager invoker, or Coinbase caller.

## Artifacts

- Default store:
  `runtime_state/admin_api_stealth_state_mutation_policy_proofs.jsonl`
- Override:
  `COINBASE_ADMIN_API_STEALTH_STATE_MUTATION_POLICY_LOG_PATH`

## Key Files

- `application/admin_api/stealth_state_mutation_policy.py`
- `application/admin_api/stealth_state_mutation_policy_service.py`
- `application/admin_api/command_service.py`
- `application/admin_api/models.py`
- `application/admin_api/route_inventory.py`
- `application/admin_api/read_service.py`
- `api/v1/routes/stealth.py`
- `docs/examples/stealth-state-mutation-policy.md`

Examples live in
[docs/examples/stealth-state-mutation-policy.md](docs/examples/stealth-state-mutation-policy.md).

Focused verification:

```bash
python -m pytest tests/regression/test_admin_api_contract.py::test_admin_api_stealth_state_mutation_policy_proof_is_no_live_and_path_keyed -q --tb=short
```
