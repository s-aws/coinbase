# Spot Recovery Proof Records

Spot recovery proof records are backend-owned, append-only local evidence for
the enterprise Admin API. They let an operator persist recovery exchange-state
and reconciliation proof references after route-bound approval, admission
audit, cap/guard, reconciliation plan, idempotency, and audit evidence exists.

Use this when reviewing Spot recovery state for a `client_order_id`. Do not use
it as recovery execution, rollback execution, exchange truth capture, Coinbase
read authority, browser proof authority, or order/exchange-state mutation.

## Surfaces

- `POST /api/v1/spot/recovery/exchange-state-proofs`
- `POST /api/v1/spot/recovery/reconciliation-proofs`
- `GET /api/v1/spot/recovery/reconciliation-proof`

The POST routes require `spot_recovery:record`. Apply and rollback execution
remain separate `spot_recovery:execute` routes and still fail closed until their
executors are implemented.

## Identity And Evidence

- Internal identity is `client_order_id`.
- `order_id` is not accepted as a top-level identity.
- Exchange-native ids may appear only inside backend-owned evidence references.
- Records include approval, admission audit, cap/guard, reconciliation plan,
  operator intent, idempotency, payload hash, correlation id, and audit id.
- Records report `live_exchange_submitted=false`,
  `live_coinbase_orders_ran=false`, and `coinbase_rest_read_ran=false`.

Examples live in [docs/examples/spot-recovery-proofs.md](docs/examples/spot-recovery-proofs.md).
