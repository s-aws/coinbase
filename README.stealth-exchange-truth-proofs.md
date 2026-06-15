# Stealth Active-Placement Exchange-Truth Evidence

Stealth active-placement exchange-truth evidence records are backend-owned,
append-only local evidence for the enterprise Admin API. They let an operator
persist a route-bound snapshot reference and proof reference for one revealed
stealth order's active placement after approval, admission audit, cap/guard,
reconciliation plan, idempotency, and audit prerequisites match.

Use this when reviewing whether a revealed stealth order has durable local
evidence for its active placement before future cancel, move, reprice,
recovery, or reconciliation execution work is considered. Do not use it as a
Coinbase read, exchange truth verification, active-placement cancel/replace,
reconciliation execution, browser proof authority, or lifecycle mutation.

## Surfaces

- `GET /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proof`
- `POST /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-snapshots`
- `POST /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proofs`

The POST routes require `stealth_exchange_truth:record`. They are authenticated,
authorized, idempotent, audited, and guarded by existing backend evidence
records. They write only local append-only evidence. They do not call Coinbase,
read Coinbase orders, submit or cancel orders, execute reconciliation,
cancel/replace active placements, or mutate order/exchange/lifecycle state.

## Identity And Evidence

- Internal identity is the path `stealth_order_id`.
- `client_order_id`, `active_placement_client_order_id`, exchange ids, and
  `order_id` are not accepted as command identities.
- Active placement client ids and exchange order ids may appear only as
  evidence fields inside the backend-owned record.
- Snapshot records include source timestamp, evidence source, snapshot
  evidence reference, reconciliation plan, approval snapshot, admission audit,
  cap/guard decision, operator intent, idempotency, payload hash, correlation
  id, and audit id.
- Proof records must reference an existing snapshot for the same
  `stealth_order_id`.
- Accepted records keep `exchange_truth_verified=false`,
  `coinbase_read_attempted=false`, `coinbase_read_succeeded=false`,
  `coinbase_rest_read_ran=false`, `coinbase_order_submitted=false`,
  `coinbase_order_cancel_submitted=false`,
  `active_placement_cancel_replace_ran=false`,
  `reconciliation_executed=false`, `order_state_mutated=false`,
  `lifecycle_state_mutated=false`, `exchange_state_mutated=false`,
  `live_exchange_submitted=false`, and `live_coinbase_orders_ran=false`.

Examples live in
[docs/examples/stealth-exchange-truth-proofs.md](docs/examples/stealth-exchange-truth-proofs.md).
