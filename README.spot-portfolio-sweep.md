# Spot Portfolio Sweep

Spot portfolio sweep is a USDC-only planning, execution, automation, and
reporting feature for buying or selling the same requested USDC notional across
eligible crypto-USDC spot pairs.

Dry-run planning is read-only. Live execution is available only through the
separate live CLI with an explicit `--approved-live-orders` flag.

## When To Use

Use this when you want to inspect or explicitly run a portfolio-wide spot sweep:

- buy up to `X` USDC notional of each eligible crypto-USDC spot pair
- sell up to `X` USDC notional of each eligible crypto-USDC spot pair
- preview an automation cadence such as every `X` hours, not to exceed `N`
  runs
- run one due recurring sweep attempt from Windows Task Scheduler or another
  supervisor
- report P/L from durable fill-ledger rows by product, portfolio, and since
  last purchase
- inspect FIFO realized P/L from known local lots without treating it as tax
  accounting
- inspect wallet inventory coverage against fill-ledger and imported baseline
  evidence

## Key Concepts

- Scope is exactly USDC-quoted spot products. USD pairs are excluded.
- Product eligibility requires `ProductType.SPOT`, `USDC` quote currency,
  online/open status, positive price, positive increments/minimums, and no
  exchange flags such as cancel-only, post-only, view-only, or auction mode.
- BUY planning uses USDC available wallet balance and plans quote size. It does
  not silently increase a request below `quote_min_size`.
- SELL planning uses each base wallet balance and estimates the base size
  needed to sell the requested USDC notional.
- Wallet reads use Coinbase account pagination through
  `external.coinbase_client.list_all_account_dicts`.
- Live execution supports Coinbase market IOC orders and limit GTC orders. Market
  BUY uses quote size; market SELL and all limit orders use base size derived
  from the plan.
- Each live item is rechecked through `ActionConditionGuard` immediately before
  `create_order`.
- A sweep safety policy can enforce artificial per-run, per-order, product
  allow/deny, planned-count, and skipped-count limits before execution starts.
- Versioned JSON config files can define the same sweep fields used by the live
  CLI. `--validate-config` loads the config, rebuilds a fresh wallet-aware plan,
  evaluates safety, and prints per-product explain rows without live approval.
- Durable sweep reconciliation reads live Coinbase order/fill evidence for
  recorded runs and appends reconciliation records to the same JSONL ledger.
  When local `fill_ledger` is available, reconciliation also compares REST fill
  notional against local rows by `client_order_id`.
- Live sweep execution backfills Coinbase REST fills into `fill_ledger` after
  submitted orders unless `--skip-fill-backfill` is supplied. The backfill is
  idempotent and is reported in the durable run ledger.
- Fill-ledger schema preserves low-price spot fills with high-scale price
  precision so local notional reconciliation works for products priced below
  one USDC.
- The dashboard exposes read-only sweep ledger status through
  `request_spot_sweep_status` and read-only sweep P/L through
  `request_spot_sweep_pnl`; live sweep approval remains CLI-only.
- Automation is a durable run-if-due CLI mode, not a daemon. Each invocation
  reloads fresh Coinbase product/wallet state, checks the JSONL run ledger, runs
  at most one due sweep, records the outcome, and exits.
- The default automation ledger is `runtime_state/spot_portfolio_sweeps.jsonl`,
  which is gitignored.
- P/L snapshots are computed from persisted `fill_ledger` rows plus supplied
  mark prices. CLI/dashboard reports use Coinbase public product marks plus the
  local fill ledger. Reports include cashflow, mark-to-market, since-last-
  purchase, and FIFO realized-lot views. They are operational P/L reports, not
  tax accounting.
- Inventory coverage reports compare eligible USDC spot wallet balances against
  local fill-ledger and imported baseline evidence. Wallet-only balances are
  sellable only if the action guard passes; they are not known-cost inventory.
- The config registry summarizes durable sweep configs, latest runs, latest
  reconciliation, and latest fill-backfill state without Coinbase calls.

## Outputs And Artifacts

- Dry-run CLI:
  `tools/run_spot_portfolio_sweep_dry_run.py`
- Live/automation CLI:
  `tools/run_spot_portfolio_sweep_live.py`
- Read-only release gate:
  `tools/run_spot_release_gate.py`
- Fill-backfill recovery CLI:
  `tools/run_spot_fill_backfill_recovery.py`
- Sweep recovery gate CLI:
  `tools/run_spot_sweep_recovery_gate.py`
- Strategy planner/reporting module:
  `business/spot_portfolio_sweep.py`
- Focused regression:
  `tests/regression/test_spot_portfolio_sweep.py`
- Dry-run summary prefix:
  `SPOT_PORTFOLIO_SWEEP_DRY_RUN`
- Live summary prefix:
  `SPOT_PORTFOLIO_SWEEP_LIVE`
- Release gate summary prefix:
  `SPOT_RELEASE_GATE_SUMMARY`
- Fill-backfill recovery summary prefix:
  `SPOT_FILL_BACKFILL_RECOVERY`
- Sweep recovery gate summary prefix:
  `SPOT_SWEEP_RECOVERY_GATE`
- Automation ledger:
  `runtime_state/spot_portfolio_sweeps.jsonl`

## Safety Constraints

- The dry-run tool must not place, preview, cancel, or modify live orders.
- Live execution requires `--approved-live-orders`.
- Live execution defaults to market IOC. Limit execution must be explicitly
  selected with `--order-type limit_gtc` or `--order-type limit_gtc_post_only`.
- Limit BUY orders use rounded planned base size and a limit price at or above
  the current mark plus `--limit-price-offset-bps`; limit SELL uses a price at
  or below the mark minus the offset.
- Safety-policy blocks are recorded with live Coinbase order notional of `0`.
- `--require-known-profitable-inventory` can require planned SELL sweep items
  to be covered by known profitable fill-ledger or imported baseline lots before
  live execution starts.
- `--validate-config` is read-only and does not bypass live approval.
- `--reconcile` and `--pnl-report` are read-only but can still fail if local DB
  or Coinbase read credentials are unavailable.
- Market SELL profitability is admission-time estimated from current metadata;
  the final fill price can differ.
- Live runs must report submitted/executed notional for every submitted order.
- Live fill backfill failure must be treated as an audit gap, not as proof that
  the Coinbase order did not fill.
- Recovery commands never submit live orders. They may read Coinbase order/fill
  evidence and write local reconciliation or fill-ledger records.
- Do not broaden this feature to USD pairs unless the roadmap explicitly
  reopens quote-currency scope.
- Do not treat wallet inventory as known profitable inventory.
- Do not use this P/L report for tax accounting.

## Examples

See [Spot Portfolio Sweep Examples](docs/examples/spot-portfolio-sweep.md).
