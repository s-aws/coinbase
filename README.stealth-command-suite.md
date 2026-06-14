# Stealth Command Suite Readiness

The stealth command-suite readiness contract exposes backend-owned evidence for
M55 stealth administration. It is a read-only Admin API surface for planning
create, cancel, reveal, move, reprice, recovery, and reconciliation work.

Use this feature when an operator or frontend needs to understand which stealth
command workflows are modeled, which are live-disabled, and which backend
contracts still block execution.

## Route

`GET /api/v1/stealth/command-suite`

The route requires Admin API authentication and `analytics:read`. It returns
`StealthCommandSuiteResponse` with:

- blocked command rows for live-disabled stealth create, reveal, move, cancel,
  and movement reprice
- exchange-truth prerequisite rows for those same five command routes,
  including accepted `stealth_order_id` identity, rejected placement/exchange
  identities, and the three active-placement-required commands
- typed `exchange_truth_checks.current_read_evidence` rows for existing
  read-only evidence behind blocked exchange-truth prerequisites
- coverage gaps for missing stealth create, reveal, cancel exchange handling,
  move, reprice, recovery, and reconciliation contracts
- typed `coverage_gaps.current_read_evidence` rows for existing read-only
  evidence behind blocked gaps, including recovery-gate, reconciliation-plan,
  stealth order detail, movement/repricing detail, and command-suite reads
- required gate chains for approval, cap/guard, admission audit,
  reconciliation, mutation claims, active-placement exchange truth, and live
  execution service evidence
- per-order reveal-trigger audit evidence on the stealth detail route so
  operators can inspect local reveal-condition evidence without triggering a
  reveal
- per-order reveal submission-adapter audit evidence on the stealth detail
  route so operators can inspect the future backend reveal path and local
  placement blockers without submitting orders
- no-live Coinbase posture with submitted/executed notional `0`

Per-order active-placement audit evidence is exposed by
`GET /api/v1/stealth/orders/{stealth_order_id}` as
`active_placement_audit`. The command-suite route points at that read evidence,
but it does not own per-order Coinbase truth and must not be treated as a
cancel/replace or reconciliation path.
The same detail route exposes `mutation_claim_audit` as display-only runtime
claim evidence for move and repricing families. It does not acquire, release,
clear, or prove mutation claims, and it must not become a command input source
or browser/BFF mutation authority.
The detail route also exposes `reveal_submission_audit` as display-only
evidence for the future backend reveal route, shared service method, manager
method, active-placement blockers, and missing submission/reconciliation
contracts. It does not call `reveal_order_slice`, create active placements,
submit or cancel Coinbase orders, read Coinbase, execute reconciliation, or
mutate lifecycle state.
The detail route also exposes `reveal_reconciliation_audit` as display-only
evidence for future reveal reconciliation proof. It reports required
plan/proof posture, local active-placement evidence, read-evidence routes, and
missing proof contracts. It does not read Coinbase, write proof records,
execute reconciliation, mutate order/lifecycle state, or grant browser/BFF
reveal authority.

Coverage-gap evidence routes are also display-only. Recovery gaps may point to
`GET /api/v1/admin/recovery-gate`,
`GET /api/v1/stealth/orders/{stealth_order_id}`, and
`GET /api/v1/stealth/command-suite`. Reconciliation gaps may point to
`GET /api/v1/admin/reconciliation/plans`,
`GET /api/v1/admin/reconciliation/plans/{plan_id}`, and
`GET /api/v1/stealth/command-suite`. These rows name route, method, action
class, required permission, shared read-service method, documentation refs,
and browser/BFF authority so operators can trace what evidence already
exists. They do not create recovery or reconciliation command routes, proof
writers, exchange-state inputs, reconciliation executors, Coinbase calls, or
browser/BFF command authority.
Exchange-truth evidence routes use the same read-only shape for create,
reveal, cancel, move, and reprice prerequisites. They identify where current
local read evidence exists, but they do not run Coinbase reads, prove active
placement exchange truth, cancel/replace placements, reveal orders, execute
reconciliation, mutate state, or authorize browser/BFF command execution.

## Safety Constraints

- `stealth_order_id` is the command identity.
- Active placement client ids and exchange order ids are evidence only.
- Revealed stealth orders cannot be locally hidden, cancelled, moved, or
  repriced unless the active Coinbase placement is cancelled, replaced,
  filled, moved, or reconciled first.
- The route does not create stealth orders, reveal orders, cancel placements,
  move/reprice revealed orders, execute reconciliation, mutate state, read
  Coinbase, or call Coinbase.
- Browser and BFF consumers may display or forward backend evidence only; they
  must not evaluate exchange-truth, mutation-claim, or reveal-trigger
  authority.
- `coverage_gaps.current_read_evidence` is traceability evidence only. It
  does not close missing backend contracts and must not be converted into
  recovery/reconciliation command controls, proof writing, exchange-state
  mutation, reconciliation execution, Coinbase reads, Coinbase submissions, or
  BFF execution authority.
- `exchange_truth_checks.current_read_evidence` is traceability evidence only.
  It does not prove exchange truth and must not be converted into Coinbase
  reads, active-placement truth resolution, cancel/replace behavior, reveal
  execution, state mutation, reconciliation execution, or BFF execution
  authority.
- `reveal_trigger_audit` is detail-route evidence only. It does not evaluate
  triggers, call `should_trigger_reveal`, call `reveal_order_slice`, submit
  Coinbase orders, mutate lifecycle state, or authorize browser/BFF reveal
  execution.
- `reveal_submission_audit` is detail-route evidence only. It does not call
  `reveal_order_slice`, create active placements, submit or cancel Coinbase
  orders, read Coinbase, execute reconciliation, mutate lifecycle state, or
  authorize browser/BFF reveal execution.
- `reveal_reconciliation_audit` is detail-route evidence only. It does not
  read Coinbase, resolve or write proof records, execute reconciliation,
  mutate order/lifecycle state, or authorize browser/BFF reveal execution.

## References

- [Stealth Order Reads](docs/STEALTH_ORDER_READS.md)
- [Command Workflows](docs/COMMAND_WORKFLOWS.md)
- [Stealth Command Suite Examples](docs/examples/stealth-command-suite.md)
- [Public Invariants](docs/agents/INVARIANTS.md)
