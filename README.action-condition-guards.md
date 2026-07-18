# Action Condition Guards

Action condition guards evaluate planning/local compatibility actions. They do
not grant exchange authority. Legacy dashboard, stealth/reveal, replacement,
sweep, and engine mutation paths are source-disabled; Controlled-live manual
Spot place/cancel is admitted only by the authenticated Admin API chain.

## When To Use

Use action condition guards when an order must satisfy account-level constraints
that are not captured by product increments, fee-floor profitability checks, or
runtime pause/drain admission.

Current offline/local invocation points include:

- stealth planning: `StealthOrderManager.create_stealth_order`
- stealth reveal: `StealthOrderManager.reveal_order_slice`
- stealth replacement planning/execution:
  `StealthOrderManager.build_stealth_move_plan`,
  `StealthOrderManager.execute_stealth_move`, and revealed anchor reprice
- historical dashboard guard regression fixtures

## Key Concepts

- `ActionGuardPhase.PLANNING` runs after size quantization and before stealth
  memory/DB persistence, including spot follow-up stealth orders.
- `ActionGuardPhase.REVEAL` remains a planning/test phase; it cannot mint the
  canonical Admin API SDK scope.
- Dashboard exchange mutation messages return a fixed source-disabled response
  before guard/runtime lookup.
- `wallet_available` checks spot account balances when Coinbase REST
  credentials are configured. It applies only to catalog-configured spot
  products, not unknown fallback product IDs.
- `planned_budget_available` subtracts local HIDDEN, PENDING, and TRIGGERED
  spot stealth commitments from the wallet balance before admitting another
  action. The currently revealing stealth order is excluded from its own reveal
  check so it is not charged twice.
- Spot replacement delta calculations remain synthetic/offline safety helpers.
- `known_inventory_available` is optional and disabled by default. When enabled,
  it applies only to spot `SELL` actions and requires known profitable lots from
  the fill ledger or imported spot inventory baselines. Unknown-cost inventory
  is reported but cannot satisfy the condition.
- `max_base_size` and `max_notional` are configured artificial limits and can
  apply to spot or futures products.
- Spot notional caps may use `limits` with `product_type=SPOT` for offline
  planning evidence. They cannot enable raw dashboard REST placement.
- Market BUY orders with `quote_size` can be checked against quote balance and
  configured notional caps even when no base size is supplied.

## Configuration

Configuration is optional. Set `ACTION_CONDITION_GUARDS_JSON` to a JSON object,
or add the same object as top-level `action_condition_guards` in `products.json`.
The environment variable wins.

Supported top-level keys:

- `wallet_available`
- `known_inventory_available`
- `limits`

`wallet_available` defaults to enabled. In local/test runs without Coinbase
REST credentials it skips the wallet check unless `block_without_credentials`
is true. If credentials are present and wallet fetch fails, reveal/planning is
blocked unless `fail_open_on_fetch_error` is true.
Spot follow-up planning is checked by default; set
`check_follow_up_planning` to false only for a deliberate policy exception.

Planned-budget subtraction has no separate configuration key. It runs when a
caller supplies local planned-budget state to `ActionConditionGuard`, currently
from `StealthOrderManager` and historical dashboard regression fixtures. The
installed dashboard mutation surface is source-disabled before guard lookup.

Known-inventory authority has no wallet fallback. If
`known_inventory_available` is enabled and the fill-ledger authority is not
available, spot `SELL` admission blocks with a structured reason.

## Safety Constraints

- Do not add a spot-only placement path.
- Do not treat planning approval as sufficient for reveal.
- Do not mark a blocked reveal cancelled or failed; it remains retryable.
- Do not bypass the shared `core.action_condition_guard.ActionConditionGuard`
  evaluator from new order-entry surfaces.
- Do not count REVEALED spot stealth orders in local planned budget; Coinbase
  wallet availability should already reflect their live exchange holds.
- Keep synthetic replacement-budget checks hold-aware; they preserve safety
  behavior for regression/reference use but grant no exchange authority.
- Treat a synthetic replacement as blocked when its modeled exchange cancel
  fails; the existing revealed placement remains the conservative local truth.
- Do not treat wallet balance as known profitable inventory. Unknown-cost
  imported inventory must stay visible but unprofitable to authority checks.

## Examples

See [Action Condition Guard Examples](docs/examples/action-condition-guards.md).
