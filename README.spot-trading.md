# Spot Trading

Spot trading uses the same order lifecycle, stealth lifecycle, sizing, fee,
dashboard, and reconciliation paths as futures. There is no separate spot
engine.

## When To Use

Use spot products when the trade should settle against the spot wallet balance
instead of a Coinbase Derivatives position. Spot orders use base-asset size
increments and quote-notional minimums from `products.json`.

## Key Concepts

- `products.json` is the product catalog. Add spot products under `spot` and
  keep metadata under `metadata`.
- Product type must resolve to `ProductType.SPOT` through
  `configuration.normalize_product_type`.
- `ticker_to_trading` is only for products where ticker and tradable product IDs
  are genuinely different. Do not map `BTC-USD` to `BTC-USDC` unless the target
  product is live and tradable in Coinbase product metadata.
- Spot profitability uses the spot fee multiplier in `calculation/fee_manager.py`
  and does not apply derivatives per-contract fees.
- Spot wallet availability is checked by the action-condition guard during
  stealth planning and again immediately before reveal placement when Coinbase
  REST credentials are configured. Direct dashboard `place_order` also runs the
  planning-phase guard before REST submission. Wallet reads follow Coinbase
  account pagination before evaluating availability.
- Local planned-budget accounting subtracts HIDDEN, PENDING, and TRIGGERED spot
  stealth commitments from wallet availability before admitting another spot
  action. REVEALED orders are not counted locally because Coinbase wallet
  availability should already reflect the live exchange hold.
- Product capability policy keeps spot feature availability explicit. Spot
  direct placement, stealth planning, and stealth reveal are enabled; spot
  move/reprice replacement, cancel/re-entry, and hotpoint auto-placement are
  disabled by default until their spot-specific safety work is complete.
- Spot replacement guards are replace-aware. If spot move or revealed reprice
  is explicitly enabled, the guard checks only the net new wallet requirement
  above the existing Coinbase hold and rechecks immediately before canceling
  the live placement.
- Spot follow-ups are classified before creation. BUY-fill to SELL is treated
  as an `exit`; SELL-fill to BUY is treated as `rebuy` and is blocked unless
  `SPOT_FOLLOW_UP_POLICY_JSON` or `products.json::spot_follow_up_policy`
  explicitly enables it.
- Spot inventory authority separates wallet sellability from known profitable
  inventory. `SPOT_INVENTORY_BASELINES_JSON` or
  `products.json::spot_inventory_baselines` can import pre-existing inventory;
  baseline lots without positive known entry price are marked unknown cost
  basis and cannot satisfy known-profit checks.
- `known_inventory_available` is an optional action-condition guard. When
  enabled, spot `SELL` admission can require known profitable lots in addition
  to wallet availability. It is disabled by default.
- Dashboard spot readiness feedback is available through the
  `request_spot_readiness` websocket message and the Spot Readiness panel in
  `ui_stealth_orders_manager.html`. The panel shows capability reasons,
  guard phase coverage, wallet snapshot balances, planned local spot budget,
  and imported baseline inventory split between known and unknown cost basis.
- USDC-only portfolio sweep planning and durable P/L reporting live in
  [Spot Portfolio Sweep](README.spot-portfolio-sweep.md). That feature also
  owns sweep automation status, inventory coverage, fill-backfill recovery, and
  sweep recovery gates. USD pairs remain out of scope for that feature.
- Internal order tracking still uses `client_order_id`; Coinbase `order_id`
  remains exchange-facing only.

## Outputs And Artifacts

- Orders are still persisted in `order_parent`.
- Stealth plans are still persisted in `stealth_orders`.
- Product precision and minimums come from `products.json::metadata`.
- Dashboard product refresh updates `products.json`.

## Safety Constraints

- Do not add a spot-only placement path.
- Do not hard-code spot product IDs, increments, or fee rules in strategy code.
- Do not bypass `core.product_capability.evaluate_product_capability` from new
  order-entry, replacement, or strategy surfaces.
- Validate size with `calculation.size_validation.validate_and_quantize_size`
  before placement.
- Do not treat a planning wallet pass as sufficient for reveal. External
  Coinbase/dashboard orders can consume wallet balance after planning, so reveal
  must recheck.
- Do not add mutable spot reservation state unless derived planned-budget
  accounting from stealth order status and remaining size is proven insufficient.
- Do not let spot follow-ups inherit futures short/close semantics. Route new
  follow-up behavior through `core.spot_follow_up_policy`.
- Do not apply full-order wallet checks to no-fill spot replacements. Use the
  shared replacement action guard so Coinbase holds are credited and cancel
  failure leaves local state conservative.
- Do not treat wallet inventory as profitable inventory. Wallet balance proves
  sellability; only fill-ledger or imported known-cost lots can prove known
  profitable inventory.
- Run `pytest tests/regression/ -v --tb=short` after non-agent-file changes.

## Examples

See [Spot Trading Examples](docs/examples/spot-trading.md).
For USDC-only portfolio sweep dry runs, see
[Spot Portfolio Sweep Examples](docs/examples/spot-portfolio-sweep.md).
For account-level guard configuration, see
[Action Condition Guards](README.action-condition-guards.md).

## Test Gate

Run the focused spot readiness gate with:

```powershell
python tools/run_spot_readiness_regression.py
```

Run the optional browser smoke gate with:

```powershell
python tools/run_spot_readiness_browser_smoke.py
```

The browser gate uses `pytest-playwright` and installed Chromium to open
`ui_stealth_orders_manager.html`, verify the readiness request is sent, and
verify a dashboard-shaped readiness payload renders in the panel.

This does not replace the required full regression command:
`pytest tests/regression/ -v --tb=short`.

Run the read-only spot release wrapper with:

```powershell
python tools/run_spot_release_gate.py
```

Approved live Coinbase spot smoke is available as a manual release-readiness
check:

```powershell
python tools/run_live_spot_usdc_smoke.py --approved-live-orders
```

For the approved live matrix plus fill-ledger reconciliation gate:

```powershell
python tools/run_live_spot_usdc_smoke.py --approved-live-orders --validation-matrix --reconciliation-gate
```

This command places real Coinbase spot orders and prints submitted/executed
notional in `LIVE_COINBASE_SPOT_SMOKE_SUMMARY`. Add `--retain-inventory` when
the bought base should remain in the account for future sell-path tests.

## Roadmap

Spot trading is not yet treated as a blanket equivalent to futures/perpetuals.
Before adding spot-specific strategy features, follow the tracked
[Spot Readiness Roadmap](docs/SPOT_READINESS_ROADMAP.md).
