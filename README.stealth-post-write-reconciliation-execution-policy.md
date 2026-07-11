# Stealth Post-Write Reconciliation Execution Policy

Stealth post-write reconciliation execution-policy records are backend-owned,
append-only local evidence for the enterprise Admin API. They let an operator
persist one route-bound proof record for a future guarded stealth command
after the proof, execution-journal, and verification surfaces exist, without
executing reconciliation, reading or writing Coinbase, invoking
`StealthOrderManager`, cancelling/replacing active placements, or mutating
order, exchange, or lifecycle state.

Use this only after the backend has built the exact guarded command context
for the stealth command being reviewed. The proof is local evidence for the
future reconciliation execution boundary. It is not reconciliation execution,
Coinbase exchange truth, live Coinbase approval, browser authority, or BFF
execution authority.

## Surfaces

- `GET /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-execution-policy`
- `POST /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-execution-policy-proofs`

The POST route requires `stealth_post_write_reconciliation_policy:record`. It
is authenticated, authorized, idempotent, audited, and guarded by existing
backend evidence records for the proof route. It writes only local append-only
evidence. It does not run the post-write reconciliation executor, call
Coinbase, read Coinbase orders, submit or cancel orders, invoke
`StealthOrderManager`, cancel/replace active placements, or mutate order,
exchange, or lifecycle state.

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
  - `post_write_reconciliation_execution_policy_ref`
  - `route_bound_reconciliation_plan_ref`
  - `post_write_execution_journal_policy_ref`
  - `post_write_reconciliation_verification_policy_ref`
  - `safe_reconciliation_chain_ref`
- Proof records must be dry-run evidence and must not include manual live
  acknowledgement.

The proof route itself still needs its own backend approval snapshot,
admission audit, cap/guard decision, reconciliation plan, idempotency key,
operator intent, payload hash, and audit record. The guarded command fields
bind the proof to the reviewed command; they do not replace the proof route's
own gate chain.

## Boundary

Accepted proof records keep
`post_write_reconciliation_execution_policy_verified=false`,
`post_write_reconciliation_execution_allowed=false`,
`route_bound_reconciliation_plan_required=true`,
`execution_journal_required=true`,
`reconciliation_verification_required=true`,
`safe_reconciliation_chain_verified=false`,
`reconciliation_execution_allowed=false`,
`manager_invocation_ran=false`, `coinbase_read_attempted=false`,
`coinbase_read_succeeded=false`, `coinbase_rest_read_ran=false`,
`coinbase_order_submitted=false`, `coinbase_order_cancel_submitted=false`,
`active_placement_cancel_replace_ran=false`,
`reconciliation_executed=false`, `order_state_mutated=false`,
`lifecycle_state_mutated=false`, `exchange_state_mutated=false`,
`live_exchange_submitted=false`, and `live_coinbase_orders_ran=false`.

Browser surfaces may display the evidence only. The BFF may forward to the
backend route only; it must not become a reconciliation executor or Coinbase
caller.

## Artifacts

- Default store:
  `runtime_state/admin_api_stealth_post_write_reconciliation_execution_policy_proofs.jsonl`
- Override:
  `COINBASE_ADMIN_API_STEALTH_POST_WRITE_RECONCILIATION_POLICY_LOG_PATH`

## Key Files

- `application/admin_api/stealth_post_write_reconciliation_policy.py`
- `application/admin_api/stealth_post_write_reconciliation_policy_service.py`
- `application/admin_api/command_service.py`
- `application/admin_api/models.py`
- `application/admin_api/route_inventory.py`
- `application/admin_api/read_service.py`
- `api/v1/routes/stealth.py`
- `docs/examples/stealth-post-write-reconciliation-execution-policy.md`

Examples live in
[docs/examples/stealth-post-write-reconciliation-execution-policy.md](docs/examples/stealth-post-write-reconciliation-execution-policy.md).

Focused verification:

```bash
pytest tests/regression/test_admin_api_contract.py::test_admin_api_stealth_post_write_reconciliation_policy_proof_is_no_live_and_path_keyed -q --tb=short
```
