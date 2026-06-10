# Action Condition Guards

Action condition guards block unsafe stealth actions before they create local
state or exchange-visible orders.

## When To Use

Use action condition guards when an order must satisfy account-level constraints
that are not captured by product increments, fee-floor profitability checks, or
runtime pause/drain admission.

Current invocation points:

- stealth planning: `StealthOrderManager.create_stealth_order`
- stealth reveal: `StealthOrderManager.reveal_order_slice`
- stealth replacement planning/execution:
  `StealthOrderManager.build_stealth_move_plan`,
  `StealthOrderManager.execute_stealth_move`, and revealed anchor reprice
- raw dashboard placement: `dashboard_server.py` `place_order`

## Key Concepts

- `ActionGuardPhase.PLANNING` runs after size quantization and before stealth
  memory/DB persistence, including spot follow-up stealth orders.
- `ActionGuardPhase.REVEAL` runs after reveal-price planning and before
  pre-submission hooks, `order_parent` pre-insert, and REST placement.
- Direct dashboard `place_order` runs the planning-phase guard after size
  validation and before `REST_CLIENT.create_order`. For spot products, the
  dashboard handler also requires `manual_live_acknowledgement=true` before the
  planning guard and REST submission. Direct spot placement also requires a
  matching planning-phase `max_notional` limit rule. Direct spot `SELL` requires
  `known_inventory_available` to be enabled. Direct spot placement also blocks
  when the local durable audit publisher is unavailable.
- `wallet_available` checks spot account balances when Coinbase REST
  credentials are configured. It applies only to catalog-configured spot
  products, not unknown fallback product IDs.
- `planned_budget_available` subtracts local HIDDEN, PENDING, and TRIGGERED
  spot stealth commitments from the wallet balance before admitting another
  action. The currently revealing stealth order is excluded from its own reveal
  check so it is not charged twice.
- Spot replacement checks use the same policy but evaluate the net new wallet
  requirement after crediting the active same-currency Coinbase hold. Example:
  a no-fill spot `BUY` moved from `0.1 @ 100` to `0.1 @ 110` checks only the
  extra quote requirement, not the full new order notional.
- `known_inventory_available` is optional and disabled by default. When enabled,
  it applies only to spot `SELL` actions and requires known profitable lots from
  the fill ledger or imported spot inventory baselines. Unknown-cost inventory
  is reported but cannot satisfy the condition.
- `max_base_size` and `max_notional` are configured artificial limits and can
  apply to spot or futures products.
- Direct spot notional caps should use `limits` with `product_type=SPOT`,
  `max_notional`, and `phases=["planning"]` so the existing guard blocks before
  raw dashboard REST placement.
- Planning is a stale preflight. Reveal is rechecked because external Coinbase
  or dashboard orders can consume wallet availability after planning.
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
from `StealthOrderManager` and from dashboard direct placement when the stealth
manager is attached.

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
- Do not apply a naive wallet-available check to live cancel-and-replace moves
  before accounting for Coinbase holds on the existing placement.
- Do not treat a replacement as safe when exchange cancel fails; the existing
  revealed placement remains the conservative local truth.
- Do not treat wallet balance as known profitable inventory. Unknown-cost
  imported inventory must stay visible but unprofitable to authority checks.

## Examples

See [Action Condition Guard Examples](docs/examples/action-condition-guards.md).
