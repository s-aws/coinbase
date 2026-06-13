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
- execute a rendered spot campaign config through the existing live sweep path
- report P/L from durable fill-ledger rows by product, portfolio, and since
  last purchase
- inspect FIFO realized P/L from known local lots without treating it as tax
  accounting
- inspect wallet inventory coverage against fill-ledger and imported baseline
  evidence
- optionally compare Coinbase portfolio average cost basis against local
  evidence for operational coverage, P/L, and drift review

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
- Live sweep orders use UUID `client_order_id` values so websocket,
  `order_parent`, fill-ledger, and reconciliation paths can share the same
  internal identifier contract.
- The live runner passes an `OrderEventStreamPublisher` into the sweep executor
  so accepted placements can publish `order_submitted` / `rest_submit`
  ownership evidence when the local event stream is available. Each order
  report includes `submission_event_recorded` so an unavailable event stream is
  visible as an audit gap without rewriting the Coinbase submission outcome.
- A sweep safety policy can enforce artificial per-run, per-order, product
  allow/deny, planned-count, and skipped-count limits before execution starts.
- Product allow/deny scope is applied before `max_products` selection. This
  lets campaign retry configs target a specific not-submitted product without
  planning the first alphabetic USDC product and failing later in safety.
- Versioned JSON config files can define the same sweep fields used by the live
  CLI. `--validate-config` loads the config, rebuilds a fresh wallet-aware plan,
  evaluates safety, and prints per-product explain rows without live approval.
- Spot campaign configs can render this sweep config schema. Campaigns own
  intake, dry-run matrices, durable campaign snapshots, release gates, and
  dashboard campaign status; live placement still runs here.
- Durable sweep reconciliation reads live Coinbase order/fill evidence for
  recorded runs and appends reconciliation records to the same JSONL ledger.
  When local `fill_ledger` is available, reconciliation also compares REST fill
  notional against local rows by `client_order_id`.
- Live sweep execution backfills Coinbase REST fills into `fill_ledger` after
  submitted orders unless `--skip-fill-backfill` is supplied. The backfill is
  idempotent and is reported in the durable run ledger.
- Products skipped during planning remain visible as audit rows in execution
  summaries, but they are not counted as live execution failures. A sweep with
  submitted orders plus only planned skips is treated as completed; blocked
  guards, placement errors, or submitted orders with post-submit audit errors
  still produce partial or failed status.
- Fill-ledger schema preserves low-price spot fills with high-scale price
  precision so local notional reconciliation works for products priced below
  one USDC.
- The dashboard exposes read-only sweep ledger status through
  `request_spot_sweep_status` and read-only sweep P/L through
  `request_spot_sweep_pnl`; live sweep approval remains CLI-only.
- The Admin API exposes `POST /api/v1/spot/sweep/automation-runs` as a
  route-bound, live-disabled command contract keyed by `sweep_config_id`. It
  records admin envelope/idempotency/audit/admission evidence and currently
  returns `501 not_implemented`; it must not run the live sweep CLI, create a
  browser scheduler, or submit Coinbase orders until scheduler, run-limit,
  recovery, reconciliation, and live execution gates pass.
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
- The Admin API can persist operator-review P/L checkpoint records through
  `POST /api/v1/spot/pnl/checkpoints` and read them through
  `GET /api/v1/spot/pnl/checkpoints` and
  `GET /api/v1/spot/pnl/checkpoints/{checkpoint_id}`. These records are
  durable local-state evidence for snapshots sourced from
  `/api/v1/spot/sweep/pnl`; they are not sell eligibility, profitability
  authority, tax accounting, reconciliation execution, or Coinbase order
  evidence.
- Inventory coverage reports compare eligible USDC spot wallet balances against
  local fill-ledger and imported baseline evidence. Wallet-only balances are
  sellable only if the action guard passes; they are not known-cost inventory.
- Coinbase portfolio average cost basis is a separate operational authority
  source. It comes from portfolio breakdown `spot_positions`, is mapped from
  asset to eligible `BASE-USDC` products, and is not exact local FIFO lot
  evidence.
- Read-only coverage and P/L reports can include Coinbase average cost with
  `--include-coinbase-average-cost`.
- SELL safety can use Coinbase average cost only when
  `--allow-coinbase-average-cost-basis` is set, and it applies the additional
  `--coinbase-average-cost-profit-buffer-pct` before allowing a planned SELL.
  This path is disabled by default.
- The config registry summarizes durable sweep configs, latest runs, latest
  reconciliation, and latest fill-backfill state without Coinbase calls.
- Fill-ledger health audits flag local evidence hazards such as zero-price
  USDC fills, zero notional, missing `client_order_id`, and reconciled rows
  without exchange evidence.
- Fill-ledger repair planning uses durable smoke/sweep order records to map
  `client_order_id` to Coinbase exchange order ids, fetches REST fills read
  only, and applies local corrections only with `--apply`.
- Sweep recovery gate runs append durable `sweep_recovery` records when they
  attempt reconciliation or fill-backfill recovery.
- Cost-basis snapshots can be recorded locally with
  `--record-cost-basis-snapshot` and reviewed later with
  `--cost-basis-status`. Dashboard cost-basis status reads this local snapshot
  ledger only.
- Scheduled live/ledger-writing sweep work and cost-basis snapshot recording
  are protected by a local operation lock so overlapping task-scheduler
  invocations fail before Coinbase work or local JSONL writes.

## Outputs And Artifacts

- Dry-run CLI:
  `tools/run_spot_portfolio_sweep_dry_run.py`
- Live/automation CLI:
  `tools/run_spot_portfolio_sweep_live.py`
- Live-disabled Admin API command contract:
  `POST /api/v1/spot/sweep/automation-runs`
- Local-state Admin API P/L checkpoint contract:
  `POST /api/v1/spot/pnl/checkpoints`
- Read-only Admin API P/L checkpoint evidence:
  `GET /api/v1/spot/pnl/checkpoints` and
  `GET /api/v1/spot/pnl/checkpoints/{checkpoint_id}`
- Read-only release gate:
  `tools/run_spot_release_gate.py`
- Read-only campaign CLI:
  `tools/run_spot_campaign.py`
- Fill-backfill recovery CLI:
  `tools/run_spot_fill_backfill_recovery.py`
- Sweep recovery gate CLI:
  `tools/run_spot_sweep_recovery_gate.py`
- Fill-ledger health CLI:
  `tools/run_spot_fill_ledger_health.py`
- Fill-ledger repair CLI:
  `tools/run_spot_fill_ledger_repair.py`
- Cost-basis helper module:
  `business/spot_cost_basis.py`
- Campaign helper module:
  `business/spot_campaign.py`
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
- Fill-ledger health summary prefix:
  `SPOT_FILL_LEDGER_HEALTH`
- Fill-ledger repair summary prefix:
  `SPOT_FILL_LEDGER_REPAIR`
- Automation ledger:
  `runtime_state/spot_portfolio_sweeps.jsonl`
- Fill-ledger repair ledger:
  `runtime_state/spot_fill_ledger_repairs.jsonl`
- Cost-basis snapshot ledger:
  `runtime_state/spot_cost_basis_snapshots.jsonl`
- Admin API P/L checkpoint ledger:
  `runtime_state/admin_api_spot_pnl_checkpoint.jsonl`
- Campaign snapshot ledger:
  `runtime_state/spot_campaigns.jsonl`
- Operation lock file:
  `runtime_state/spot_portfolio_sweep.lock`

## Safety Constraints

- The dry-run tool must not place, preview, cancel, or modify live orders.
- Live execution requires `--approved-live-orders`.
- Live execution defaults to market IOC. Limit execution must be explicitly
  selected with `--order-type limit_gtc` or `--order-type limit_gtc_post_only`.
- Limit BUY orders use rounded planned base size and a limit price at or above
  the current mark plus `--limit-price-offset-bps`; limit SELL uses a price at
  or below the mark minus the offset.
- Safety-policy blocks are recorded with live Coinbase order notional of `0`.
- `--require-known-profitable-inventory` is required for live SELL sweeps. It
  requires planned SELL items to be covered by known profitable fill-ledger or
  imported baseline lots before live execution starts.
- `--disable-safety-policy` is incompatible with `--approved-live-orders`.
  It is reserved for read-only diagnostics and validation paths where no
  Coinbase order can be submitted.
- `--allow-coinbase-average-cost-basis` is an explicit SELL authority opt-in,
  not a default. Use it only with an additional profit buffer and only when
  Coinbase average cost is acceptable for the operational decision being made.
- `--validate-config` is read-only and does not bypass live approval.
- `tools/run_spot_campaign.py` is read-only with respect to Coinbase orders.
  Rendered campaign sweep configs still require this live runner and
  `--approved-live-orders` before any order can be submitted.
- `--cost-basis-baseline`, `--cost-basis-drift-audit`, `--reconcile`, and
  `--pnl-report --include-coinbase-average-cost` are read-only but can still
  fail if local DB or Coinbase read credentials are unavailable.
- `--record-cost-basis-snapshot` writes a local JSONL snapshot but still
  submits no Coinbase orders.
- `--allow-coinbase-average-cost-basis` requires
  `--require-known-profitable-inventory` and is valid only for SELL.
- Market SELL profitability is admission-time estimated from current metadata;
  the final fill price can differ.
- Live runs must report submitted/executed notional for every submitted order.
- Live sweep `client_order_id` values must remain UUID text. Do not add
  human-readable prefixes to Coinbase-facing `client_order_id`; use the sweep
  run id, config id, JSONL record type, and event payload fields for sweep
  classification instead.
- Live fill backfill failure must be treated as an audit gap, not as proof that
  the Coinbase order did not fill.
- Recovery commands never submit live orders. They may read Coinbase order/fill
  evidence and write local reconciliation or fill-ledger records.
- Fill-ledger repair defaults to non-writing dry-run behavior. Local DB
  corrections require `--apply`; dry-run records are persisted only with
  `--record-dry-run`.
- Do not broaden this feature to USD pairs unless the roadmap explicitly
  reopens quote-currency scope.
- Do not treat wallet inventory as known profitable inventory.
- Do not use this P/L report for tax accounting.
- Do not treat Admin API P/L checkpoint records as permission to sell,
  profitability proof, reconciliation proof, tax lots, or evidence that a live
  Coinbase order ran.
- If a checkpoint includes `average_cost_snapshot`, the Admin API reports it
  through `average_cost_reviewed`, `average_cost_review_source`,
  `average_cost_review_detail`, and list-level `average_cost_review_count`.
  This is still the same checkpoint review path, not a separate average-cost
  authority store.
- Accepted checkpoint records also expose verified append-only Admin API audit
  link readback through `audit_id`, `audit_linked`, `audit_source`,
  `audit_detail`, and list-level `audit_linked_count`. This is review evidence
  only, not recovery execution, reconciliation execution, Coinbase execution,
  or browser authority. A checkpoint with an `audit_id` but no matching audit
  row is reported as unverified and does not increment `audit_linked_count`.
- Accepted checkpoint records also expose read-only recovery-link evidence
  through `recovery_linked`, `recovery_source`, `recovery_routes`,
  `recovery_detail`, and list-level `recovery_linked_count`. This links the
  checkpoint to `/api/v1/admin/recovery-gate` and
  `/api/v1/admin/fill-ledger-health` for operator triage only; it does not
  execute recovery, apply repairs, roll back state, run reconciliation, call
  Coinbase, or create browser recovery authority.
  These fields are response/read-model evidence derived from those backend
  reads, not separately persisted recovery state in the checkpoint ledger.

- Accepted checkpoint records also expose read-only reconciliation-plan link
  evidence through `reconciliation_linked`, `reconciliation_source`,
  `reconciliation_routes`, `reconciliation_detail`, and list-level
  `reconciliation_linked_count`. This links the checkpoint read model to
  `/api/v1/admin/reconciliation/plans` for operator triage only; it does not
  execute reconciliation, mutate order or exchange state, apply repairs, roll
  back state, call Coinbase, or create browser reconciliation authority. The
  separate Spot reconciliation workflow remains blocked until backend preview,
  execution, and proof contracts exist.

## Examples

See [Spot Portfolio Sweep Examples](docs/examples/spot-portfolio-sweep.md).
For reusable campaign setup and release gates, see
[Spot Campaign Examples](docs/examples/spot-campaign.md).
