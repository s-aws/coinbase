# Command Workflows

This backend document explains how enterprise admin command evidence is exposed
without creating a second trading path.

The Admin API may expose command contracts, dry-submit evidence, and readiness
coverage for order, cancel, stealth, movement/repricing, approval, audit,
cap/guard, reconciliation, and campaign workflows. The backend remains the only
authority for trading behavior, wallet checks, guard checks, approval state,
reconciliation state, live adapter execution, and Coinbase calls.

## Current Contract

- Backend route inventory is the source of command route identity, action class,
  permissions, shared service method, and live designation.
- OpenAPI schemas are generated from backend FastAPI models and must be
  regenerated after contract changes.
- The frontend consumes generated contracts or typed wrappers only. It may
  display evidence, draft requests, and forward requests to backend routes when
  those routes exist, but it must not compute trading authority or call
  Coinbase.
- Live command execution stays disabled unless a backend route explicitly
  reports passing approval, cap/guard, admission audit, reconciliation, live
  adapter, and operator-intent gates.

## Spot Command Suite

`GET /api/v1/spot/command-suite` is read-only M54 evidence. It reports whether
manual spot order placement, spot cancel, spot campaign execution, and spot
sweep automation have the required backend gates and shared command-service
wiring.

This route does not submit orders, cancel orders, launch campaigns, mutate
wallet or order state, or call Coinbase. Command rows use `mutation_family`
enum values such as `spot_manual_order`, `spot_order_cancel`, and
`spot_campaign_execution`, and `spot_sweep_automation`. A row's `status` is
gate status, while `live_execution_status` is the live-execution posture.

Each command row also reports `proof_routes` for the backend-owned local-state
records that must exist before the command can become executable: approval
request/decision, admission audit, cap/guard decision, and reconciliation
plan. Those proof routes are derived from `ADMIN_API_ROUTE_INVENTORY`; the
frontend may display them but must not evaluate the gates, synthesize proof,
or treat them as live approval.

Each command row also reports `readiness_preconditions` by reusing
`AdminLiveReadinessPreconditionItem` from live-enablement evidence. These
preconditions show source, expected source, blocker, configured/blocking
state, and browser/BFF boundary for approval-store, approval snapshot,
admission audit, cap/guard, reconciliation, live adapter, execution-intent,
browser/BFF boundary, and live service gates. They are status evidence only;
they do not create proof records, evaluate gates in the browser, enable BFF
execution, or call Coinbase.

Website command workflow draft cards may display the same backend-owned
`readiness_preconditions` beside draft payload evidence for spot manual order,
cancel by `client_order_id`, campaign execution, and sweep automation. That
display is a trace back to command-suite evidence only; it must not evaluate
readiness, create proof records, enable commands, launch sweep tools, create a
browser scheduler, or copy spot wallet/no-shorting rules into non-spot modules.

The command-suite response also reports `coverage_gaps` for remaining M54 spot
families that are not command-complete: sweep automation, recovery workflow,
and reconciliation workflow. Gap rows are separate from
`mutation_family` command rows. They may name current read evidence,
checkpoint record evidence, missing backend contracts, required gate chains,
and browser/BFF boundaries, but they must not become command workflow drafts,
BFF mutation routes, browser profitability or sell authority, reconciliation
execution, tax accounting, or Coinbase calls.

Gap rows also report typed `current_read_evidence` rows derived from
`ADMIN_API_ROUTE_INVENTORY`. These rows identify the existing read-only Admin
API route, method, permission, shared read-service method, documentation refs,
and display/forward-only boundary that supports the gap. They are navigation
and traceability evidence only; they do not create command routes or satisfy
the missing backend contracts.
The stealth command-suite uses the same pattern for blocked recovery and
reconciliation gaps. Those rows may point to
`GET /api/v1/admin/recovery-gate`,
`GET /api/v1/admin/reconciliation/plans`,
`GET /api/v1/admin/reconciliation/plans/{plan_id}`, and stealth read
surfaces. They remain backend-owned read evidence only; they must not create
stealth recovery or reconciliation commands, write proof records, execute
reconciliation, mutate stealth/order/exchange state, call Coinbase, trust
browser exchange evidence, or grant browser/BFF execution authority.

`POST /api/v1/spot/sweep/automation-runs` is the route-bound sweep automation
command contract. It is keyed by `sweep_config_id`, requires
`spot_sweep:execute`, records idempotency/audit/admission evidence, and
currently returns `501 not_implemented` with `live_exchange_submitted=false`.
It must not call `tools/run_spot_portfolio_sweep_live.py`, invoke Coinbase,
create a browser scheduler, or close the wider sweep automation gap until the
durable scheduler, run-limit, recovery, and reconciliation contracts exist.

`POST /api/v1/spot/pnl/checkpoints` is a backend-owned local-state mutation
for durable operator-review records sourced from
`/api/v1/spot/sweep/pnl`. It requires `spot_pnl:record`, idempotency, and
audit evidence, and read evidence is available through
`GET /api/v1/spot/pnl/checkpoints` and
`GET /api/v1/spot/pnl/checkpoints/{checkpoint_id}`. It is not a command
workflow draft, sell guard, profitability authority, reconciliation executor,
tax-accounting ledger, or Coinbase order path.
When the request includes `average_cost_snapshot`, the same checkpoint path is
the average-cost review evidence contract. It must not be replaced with a
second average-cost writer or interpreted as sell/profit authority.
Accepted checkpoint records also expose verified append-only Admin API audit
link readback for the local-state mutation. That link must not be replaced
with a second checkpoint audit writer or interpreted as browser audit
authority, recovery execution, reconciliation execution, or Coinbase execution
authority. A checkpoint with an `audit_id` but no matching audit row is
reported as unverified checkpoint evidence.
Accepted checkpoint records also expose read-only recovery-link evidence to
`GET /api/v1/admin/recovery-gate` and
`GET /api/v1/admin/fill-ledger-health`. That link is triage evidence only; it
must not be interpreted as recovery execution, repair apply, rollback,
reconciliation execution, Coinbase execution, browser recovery authority, or a
separate checkpoint writer.
The dedicated recovery read-contract routes,
`GET /api/v1/spot/recovery/preview`,
`GET /api/v1/spot/recovery/apply-review`,
`GET /api/v1/spot/recovery/rollback-plan`, and
`GET /api/v1/spot/recovery/reconciliation-proof`, extend that read-only
evidence with preview candidates from recovery-gate, fill-ledger-health,
optional direct-order audit lookup, apply-review gate dependencies, rollback
prerequisites, reconciliation-proof field requirements, state-repair taxonomy,
repair-target evidence, pre-apply snapshots, dry-run repair plans, and
completion-state evidence. They close the read-contract gap only. POST
contracts also exist for recovery apply execution, rollback execution,
exchange-state proof recording, exchange-state snapshot recording, and
reconciliation-proof recording. Apply and rollback remain fail-closed for
order/exchange-state mutation, Coinbase activity, and reconciliation
execution; guarded backend local repair-result journals are allowed only when
the repair guard matches exactly. The proof and snapshot POST routes persist
append-only backend local evidence only after approval, admission audit,
cap/guard, reconciliation plan, idempotency, and audit prerequisites match.
The snapshot route also requires the matching proof and completion chain and
records `coinbase_read_attempted=false`/`coinbase_read_succeeded=false`.
Reconciliation-proof POST may also persist a guarded post-apply completion
record when the existing proof, apply journal, repair-result, approval,
admission audit, cap/guard, reconciliation-plan, idempotency,
operator-intent, and payload-hash evidence matches exactly. The
reconciliation-proof read route also exposes
fail-closed reconciliation execution boundary rows keyed by `client_order_id`;
these rows name the disabled
`POST /api/v1/spot/recovery/reconciliation-executions` route, the
`execute_spot_recovery_reconciliation` service boundary, required inputs, and
remaining blockers including `coinbase_live_read_disabled`. That route is
audited, idempotent, RBAC-protected, and fail-closed; it must not roll back
order state, execute reconciliation, mutate order/exchange state, call
Coinbase, or authorize browser/BFF recovery.
Accepted checkpoint records also expose read-only reconciliation-plan link
evidence to `GET /api/v1/admin/reconciliation/plans` and
`GET /api/v1/admin/reconciliation/plans/{plan_id}`. That link is triage
evidence only; it must not be interpreted as reconciliation execution,
order/exchange-state mutation, recovery execution, repair apply, rollback,
Coinbase execution, browser reconciliation authority, or a separate
checkpoint writer.
The word "operator" in checkpoint text means the human reviewing the evidence;
the backend RBAC role named `operator` can read checkpoint evidence but cannot
record it. Recording requires `spot_pnl:record`, currently granted to `trader`
and `admin`.

Spot cancel identity is `client_order_id`. Coinbase cancellation is the
project-specific exception where the backend wrapper calls
`cancel_order(client_order_id)` because the exchange accepts the client id for
that operation. Do not replace this with an exchange-native `order_id` flow.

## Stealth Command Suite

`GET /api/v1/stealth/command-suite` is read-only M55 evidence. It reports
whether stealth create, cancel, reveal, move, reprice, recovery, and
reconciliation workflows have backend-owned contracts and gate evidence.

The response links live-disabled command rows for stealth create, reveal, move,
cancel, and movement/repricing reprice by `stealth_order_id`. It also reports
`coverage_gaps` for create lifecycle-write, reveal trigger/exchange placement,
cancel exchange-handling, move revealed, reprice completion, recovery, and
reconciliation contracts. Gap rows identify current read evidence, missing
backend contracts, required gate chains, and browser/BFF boundaries.

Stealth command rows require mutation-claim evidence in addition to the normal
approval, cap/guard, admission audit, reconciliation, idempotency,
payload-hash, and operator-intent chain. Move, cancel, and reprice also
require active-placement exchange truth before execution can be considered.
Create and reveal are command drafts that do not require active-placement
evidence before the draft response, but they still remain blocked until
lifecycle/trigger, live adapter, and reconciliation gates exist. The stealth
detail route may expose `reveal_trigger_audit` for local reveal-condition
evidence, but command workflows must not treat that panel as trigger
evaluation, `should_trigger_reveal`, `reveal_order_slice`, Coinbase
submission, lifecycle mutation, or browser/BFF reveal authority. The same
detail route may expose `reveal_submission_audit` for the future backend
reveal route, shared service method, manager method, local active-placement
evidence, and missing submission/reconciliation contracts, but command
workflows must not treat that panel as `reveal_order_slice` execution,
Coinbase submission/cancellation, active-placement creation, reconciliation
execution, lifecycle mutation, or browser/BFF reveal authority. The same
detail route may expose `reveal_reconciliation_audit` for required
reconciliation plan/proof posture, local active-placement evidence,
read-evidence routes, and missing proof contracts, but command workflows must
not treat that panel as Coinbase read authority, proof-writing authority,
reconciliation execution, order/lifecycle mutation, or browser/BFF reveal
authority. Move is a
cancel/replace-shaped draft that returns no-live evidence only; it must not
call `build_stealth_move_plan`, `execute_stealth_move`, or
`StealthOrderManager`, submit/cancel Coinbase orders, perform cancel/replace,
or mutate local lifecycle state. A revealed stealth order cannot be marked
hidden, cancelled, moved, or repriced by local mutation unless the live
placement is cancelled, replaced, filled, moved, or reconciled first.

The stealth command-suite route does not create stealth orders, reveal orders,
cancel active placements, move/reprice revealed orders, execute
reconciliation, mutate local state, read Coinbase, call Coinbase, or authorize
browser/BFF command execution.

## Boundaries

- Spot-only wallet, USDC, no-shorting, cost-basis, and average-cost rules must
  not become futures/perpetual, stealth, movement/repricing, or generic admin
  defaults.
- Frontend and BFF code remain display/forwarding surfaces. Button visibility
  is not authorization.
- Legacy dashboard WebSocket command surfaces are compatibility evidence only
  for enterprise admin planning and must not become the new frontend command
  path.

## Related References

- [Admin API](../README.admin-api.md)
- [Admin API Examples](examples/admin-api.md)
- [Admin API Route Inventory](plans/ADMIN_API_ROUTE_INVENTORY.md)
- [Admin Platform Durable Milestones](plans/ADMIN_PLATFORM_DURABLE_MILESTONES.md)
- [Agent Invariants](agents/INVARIANTS.md)
