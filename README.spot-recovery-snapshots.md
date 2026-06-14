# Spot Recovery Snapshot Records

Spot recovery snapshot records are backend-owned, append-only local evidence
for the enterprise Admin API. They persist a route-bound exchange-state
snapshot reference for a Spot recovery candidate after approval, admission
audit, cap/guard, reconciliation plan, reconciliation proof, completion,
idempotency, and audit prerequisites match.

Use this when an operator or backend workflow needs durable no-live evidence
that a `client_order_id` has a specific exchange-state snapshot reference
ready for later reconciliation review. Do not use it as Coinbase read
authority, exchange truth capture, recovery execution, reconciliation
execution, browser proof authority, or order/exchange-state mutation.

## Surfaces

- `POST /api/v1/spot/recovery/exchange-state-snapshots`
- `GET /api/v1/spot/recovery/reconciliation-proof`

The POST route requires `spot_recovery:record`. It is authenticated,
authorized, idempotent, audited, and guarded by existing backend evidence
records. It writes only a local snapshot record. It does not call Coinbase,
read Coinbase orders, submit or cancel orders, execute reconciliation, or
mutate order/exchange state.

## Identity And Evidence

- Internal identity is `client_order_id`.
- `order_id` is not accepted as a top-level identity.
- `product_id`, `exchange_state_snapshot_id`, `source_timestamp`, and
  `snapshot_source` identify the snapshot evidence.
- Records link to approval, admission audit, cap/guard, reconciliation plan,
  reconciliation proof, completion, operator intent, idempotency, payload
  hash, correlation id, and audit id.
- Records report `snapshot_recorded=true` for accepted local records while
  keeping `source_trusted=false`, `coinbase_read_attempted=false`,
  `coinbase_read_succeeded=false`, `coinbase_rest_read_ran=false`,
  `order_state_mutated=false`, `exchange_state_mutated=false`,
  `reconciliation_executed=false`, `live_exchange_submitted=false`, and
  `live_coinbase_orders_ran=false`.

Examples live in [docs/examples/spot-recovery-snapshots.md](docs/examples/spot-recovery-snapshots.md).
