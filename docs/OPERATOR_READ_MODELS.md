# Operator Read Models

Operator read models are backend-owned Admin API responses that help humans and
agents inspect trading state without creating command authority. They are
evidence surfaces only: a browser, BFF, dashboard panel, or contextless agent
must not treat a read model as permission to place, cancel, repair, roll back,
or reconcile exchange state.

## Current Surfaces

- Spot readiness, sweep status, P/L, cost basis, campaign status, direct-order
  audit, recovery preview, recovery apply-review, recovery rollback-plan,
  recovery reconciliation-proof, and command-suite reads live under
  `GET /api/v1/spot/*`.
- Order, stealth, movement/repricing, futures/perpetuals, guard/risk policy,
  audit workbench, recovery-gate, fill-ledger health, and reconciliation-plan
  reads expose cross-module evidence under their Admin API namespaces.
- P/L checkpoint record routes are local-state review records. Their readbacks
  can link to audit, recovery, and reconciliation evidence, but those links are
  not recovery execution, reconciliation execution, Coinbase calls, or sell
  authority.

## Spot Recovery Contracts

The Spot recovery routes are read-only operator models for recovery triage:

- `GET /api/v1/spot/recovery/preview`
- `GET /api/v1/spot/recovery/apply-review`
- `GET /api/v1/spot/recovery/rollback-plan`
- `GET /api/v1/spot/recovery/reconciliation-proof`

The preview route aggregates direct-order audit, recovery-gate, and
fill-ledger health evidence into candidate rows keyed by `client_order_id`
when a candidate identity exists. The apply-review, rollback-plan, and
reconciliation-proof routes expose gate dependencies, rollback prerequisites,
and required proof fields for those same client-order-id candidates. The
reconciliation-proof route also reads guarded post-apply completion evidence:
`persisted_completion_count`, `persisted_completions`, `latest_completion_id`,
post-apply satisfied/completed counts, and the fail-closed reconciliation
execution boundary: `reconciliation_execution_boundary_available`,
`reconciliation_execution_boundary_count`,
`reconciliation_execution_boundaries`, and
`latest_reconciliation_execution_boundary_id`. Completion fields prove only
that a backend-owned local completion record exists. Boundary fields prove
only that execution authority is still blocked until the backend execution
route, service contract, Coinbase evidence snapshot contract, and exact input
chain exist. Neither field group proves reconciliation execution or
exchange-state mutation.
Within each boundary row, `action_class` and `required_permission` describe
the current read evidence route; `future_action_class` and
`future_required_permission` describe the blocked executor contract that does
not yet exist.

The recovery read-contract routes do not:

- apply repair rows
- roll back state
- write reconciliation proof records
- execute reconciliation
- mutate order or exchange state
- read from Coinbase
- place or cancel Coinbase orders
- authorize browser recovery
- authorize BFF recovery

Each route reports this boundary through `read_only`, `backend_owned`,
`live_coinbase_orders_ran`, `live_coinbase_read_ran`,
`submitted_notional_usdc`, `executed_notional_usdc`, `browser_authority`, and
`bff_authority` fields. A consumer should render those fields as evidence, not
recompute or override them.

## Maintenance Rules

- Add a read model only through the backend Admin API contract and route
  inventory.
- Keep `docs/plans/ADMIN_API_ROUTE_INVENTORY.md`, generated OpenAPI artifacts,
  examples, and frontend generated schema in sync with route changes.
- Use `client_order_id` for internal order identity. Exchange ids are evidence
  only unless an exchange endpoint explicitly requires them.
- Do not copy spot wallet, no-shorting, cost-basis, or average-cost rules into
  non-spot read models.
- Add focused tests for dangerous boundaries before exposing a read model to
  the frontend.
