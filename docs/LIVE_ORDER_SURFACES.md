# Live Order Surfaces

This project has multiple operator surfaces, but they do not have equal live
trading authority.

The enterprise admin frontend release path is not a live-order surface. Its
release checks are dry/no-live validation and must report live Coinbase
execution as not run with notional `$0`.

## Current Live-Capable Surfaces

- Legacy dashboard WebSocket `place_order` is a compatibility-only manual live
  surface. Spot direct orders require explicit
  `manual_live_acknowledgement=true`, product capability, size validation,
  planning-phase action-condition guard, an explicit direct spot notional cap,
  and an enabled local `order_event_stream` publisher before REST submission.
  Direct spot `SELL` also requires `known_inventory_available`.
- Admin HTTP `POST /api/v1/orders` is the enterprise manual Spot order surface.
  It is disabled by default, but it can reach the shared command-service live
  branch when backend auth/RBAC, idempotency, approval, admission-audit,
  cap/guard, reconciliation, manual acknowledgement, configured live-service,
  REST client, and order-event-stream gates pass. It uses the same
  action-condition guard with durable `stealth_orders` planned-budget reads and
  shared fill-ledger/imported-baseline spot SELL authority.
- Legacy dashboard WebSocket `cancel_order` is a compatibility-only manual
  live cancellation surface. It accepts `client_order_id` and calls the project
  wrapper `cancel_order(client_order_id)`.
- Legacy dashboard WebSocket `place_hotpoint_test_order` is a compatibility
  seed-order surface. It uses the shared command service and existing hotpoint
  admission path.
- `tools/run_spot_portfolio_sweep_live.py --approved-live-orders` is the live
  USDC spot sweep and campaign execution surface. Campaigns render configs for
  this runner; they do not place live Coinbase orders directly. Live SELL
  sweeps additionally require `--require-known-profitable-inventory`, so wallet
  balance alone cannot authorize a live SELL sweep.

## Read-Only Or Disabled Surfaces

- Admin HTTP mutating routes other than the configured manual order exception
  fail closed after auth/RBAC, idempotency, approval-gate, and audit handling.
  They do not submit or cancel Coinbase orders yet.
- Admin HTTP `POST /api/v1/orders` remains no-live unless the manual-order
  live-service gate is explicitly configured and exact backend admission
  evidence passes. Backend `trader` or `admin` authority is required for the
  command route; a human "operator" label in the frontend is not enough RBAC
  authority.
- Admin HTTP read-only spot routes can report readiness, sweep status, P/L,
  cost-basis status, campaign status, and direct-order audit evidence.
- The enterprise frontend must use the HTTP Admin API contract. It must not
  build new product workflows on the legacy dashboard WebSocket.
- `tools/run_spot_campaign.py` is read-only with respect to Coinbase orders.
  It owns campaign intake, dry-run matrices, rendered sweep configs, status,
  and reports.
- Direct-order audit commands and dashboard audit requests are read-only local
  evidence readers. They do not submit, cancel, retry, or reconcile Coinbase
  orders.

## Operator Rule

For new frontend or automation work, route live spot execution through the
approved sweep runner until the HTTP live execution gate is completed. Keep
legacy dashboard live commands compatibility-only.
