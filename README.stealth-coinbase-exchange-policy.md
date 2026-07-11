# Stealth Coinbase Exchange Policy

Stealth Coinbase exchange policy records are backend-owned, append-only local
evidence for the enterprise Admin API. They let an operator persist one
route-bound proof record for a future guarded stealth command without reading
Coinbase, submitting or cancelling Coinbase orders, invoking
`StealthOrderManager`, cancelling/replacing active placements, executing
reconciliation, or mutating order, exchange, or lifecycle state.

Use this only after the backend has built the exact guarded command context
for the stealth command being reviewed. The proof is local evidence for
command-execution posture; it is not Coinbase exchange truth, live Coinbase
execution approval, browser authority, or BFF execution authority.

## Surfaces

- `GET /api/v1/stealth/orders/{stealth_order_id}/coinbase-exchange-submission-policy`
- `POST /api/v1/stealth/orders/{stealth_order_id}/coinbase-exchange-submission-policy-proofs`

The POST route requires `stealth_coinbase_exchange_policy:record`. It is
authenticated, authorized, idempotent, audited, and guarded by existing
backend evidence records for the proof route. It writes only local append-only
evidence. It does not call Coinbase, read Coinbase orders, submit or cancel
orders, invoke `StealthOrderManager`, cancel/replace active placements,
execute reconciliation, or mutate order, exchange, or lifecycle state.

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
  - `exchange_submission_policy_ref`
  - `coinbase_cancel_policy_ref`
  - `live_coinbase_read_policy_ref`
  - `live_cap_evidence_ref`
- Proof records must be dry-run evidence and must not include manual live
  acknowledgement.

The proof route itself still needs its own backend approval snapshot,
admission audit, cap/guard decision, reconciliation plan, idempotency key,
operator intent, payload hash, and audit record. The guarded command fields
bind the proof to the reviewed command; they do not replace the proof route's
own gate chain.

## Boundary

Accepted proof records keep `exchange_submission_policy_verified=false`,
`coinbase_submit_allowed=false`, `coinbase_cancel_allowed=false`,
`live_coinbase_read_allowed=false`, `live_cap_verified=false`,
`manager_invocation_ran=false`, `coinbase_read_attempted=false`,
`coinbase_read_succeeded=false`, `coinbase_rest_read_ran=false`,
`coinbase_order_submitted=false`, `coinbase_order_cancel_submitted=false`,
`active_placement_cancel_replace_ran=false`,
`reconciliation_executed=false`, `order_state_mutated=false`,
`lifecycle_state_mutated=false`, `exchange_state_mutated=false`,
`live_exchange_submitted=false`, and `live_coinbase_orders_ran=false`.

## Key Files

- `application/admin_api/stealth_coinbase_exchange_policy.py`
- `application/admin_api/stealth_coinbase_exchange_policy_service.py`
- `application/admin_api/command_service.py`
- `application/admin_api/models.py`
- `application/admin_api/route_inventory.py`
- `application/admin_api/read_service.py`
- `api/v1/routes/stealth.py`
- `docs/examples/stealth-coinbase-exchange-policy.md`

Examples live in
[docs/examples/stealth-coinbase-exchange-policy.md](docs/examples/stealth-coinbase-exchange-policy.md).

Focused verification:

```bash
pytest tests/regression/test_admin_api_contract.py::test_admin_api_stealth_coinbase_exchange_policy_proof_is_no_live_and_path_keyed -q --tb=short
```
