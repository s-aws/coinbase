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

- existing command rows for live-disabled stealth cancel and movement/reprice
- coverage gaps for missing stealth create, reveal, cancel exchange handling,
  move, reprice, recovery, and reconciliation contracts
- required gate chains for approval, cap/guard, admission audit,
  reconciliation, mutation claims, active-placement exchange truth, and live
  execution service evidence
- no-live Coinbase posture with submitted/executed notional `0`

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
  must not evaluate exchange-truth or mutation-claim authority.

## References

- [Stealth Order Reads](docs/STEALTH_ORDER_READS.md)
- [Command Workflows](docs/COMMAND_WORKFLOWS.md)
- [Stealth Command Suite Examples](docs/examples/stealth-command-suite.md)
- [Public Invariants](docs/agents/INVARIANTS.md)
