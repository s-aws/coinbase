# Spot Campaigns

Spot campaigns are read-only operator workflows for preparing, validating, and
tracking repeated USDC spot portfolio sweeps. They sit above the existing Spot
Portfolio Sweep planner and live runner; they do not introduce a second order
placement path.

## When To Use

Use a spot campaign when you want to:

- define a reusable all-USDC spot buy or sell campaign
- validate side, notional, cadence, max runs, product scope, and safety caps
- build a dry-run matrix across eligible `BASE-USDC` spot products
- compare dry-run matrices before a broad run
- persist durable campaign P/L and cost-basis snapshots
- build a local run index and P/L checkpoints from durable ledgers
- compare durable P/L checkpoints with a scoped delta report
- expose campaign readiness in the dashboard
- render an equivalent sweep config for explicitly approved live canaries
- build a targeted retry config for products that were not submitted during a
  partial campaign sweep run
- inspect unrecorded sweep runs before recording or deliberately ignoring them
- compare strict fill-ledger SELL authority against Coinbase average-cost
  authority without mixing the two approval standards

## Key Concepts

- Scope is USDC-only spot products. USD pairs are not included.
- Campaign config is versioned JSON. The stable config maps to the existing
  versioned sweep config used by `tools/run_spot_portfolio_sweep_live.py`.
- `tools/run_spot_campaign.py` is read-only with respect to Coinbase orders.
  It can read Coinbase products, wallets, and optional average cost basis, but
  it never calls `create_order`.
- Canonical templates use `--template-profile`. Current profiles are
  `buy_canary`, `buy_all_usdc`, `sell_canary`, and `sell_all_usdc`.
- Config validation reports use `--validate-config-report` and check explicit
  safety caps before a config is treated as operator-ready.
- SELL authority profiles are named policy presets. `fill_ledger_strict` uses
  only local/imported known profitable lots. `coinbase_average_cost_buffered`
  explicitly opts into Coinbase average cost with the configured extra buffer.
- `--sell-authority-allowlist` turns a SELL dry-run matrix into a narrowed
  allowlist containing only rows whose SELL authority passed. It can write the
  allowlist audit, a narrowed campaign config, and the rendered sweep config.
- Rendered SELL allowlist sweep configs include a
  `sell_authority_allowlist` freshness block. `--validate-config` reports that
  freshness state, and live sweep mode rejects stale or invalid allowlist
  metadata before any Coinbase order can be submitted.
- Strict fill-ledger SELL authority reconstructs remaining lots after prior
  local SELL fills are applied; a previous profitable BUY does not keep
  authorizing future sells after it has already been consumed.
- Imported baseline inventory is reported through
  `baseline_freshness_audit` so missing, stale, or invalid source-refresh
  metadata is visible before SELL authority is trusted.
- Coinbase average-cost SELL authority is still opt-in only. When a planned
  SELL row actually relies on that authority, the shared gate blocks stale
  average-cost records and stale local-vs-Coinbase drift for that product.
- Average-cost SELL allowlists exclude rows blocked by the average-cost
  freshness or drift gate. A rendered average-cost allowlist sweep config must
  still be validated immediately before live approval.
- Live campaign canaries use a rendered sweep config and the existing sweep
  runner with `--approved-live-orders`.
- Live campaign canaries require Coinbase REST credentials in the environment
  because the rendered sweep config is executed by
  `tools/run_spot_portfolio_sweep_live.py`. The campaign CLI itself remains
  read-only with respect to Coinbase orders.
- The campaign dry-run matrix reuses `build_usdc_portfolio_sweep_plan`,
  `evaluate_sweep_safety_policy`, and `build_sweep_plan_explain`.
- Durable campaign snapshots are local JSONL records in
  `runtime_state/spot_campaigns.jsonl` by default.
- After a live sweep canary runs, `--record-latest-sweep-run` records the latest
  matching sweep run into the campaign ledger without calling Coinbase.
- If a live canary is partial, `--retry-plan` can derive a normal campaign and
  sweep config for only the products with no exchange order id and zero
  submitted/executed notional.
- Admin API automation-service status exposes backend-owned read evidence for
  scheduler due/not-due/disabled/max-run decisions and run-limit remaining
  counts. This is not a scheduler dispatcher, retry executor, browser timer,
  BFF runner, or Coinbase authority.
- Admin API sweep automation run reviews expose backend-owned scheduler
  dispatch and retry execution contract evidence in the command response. This
  is operator blocker evidence only; it does not dispatch a scheduler, execute
  retries, reconcile, or call Coinbase.
- Planned sweep skips are not retry candidates and do not make a live campaign
  canary blocked by themselves. Campaign recording uses the effective sweep
  outcome while preserving the raw recorded sweep status in the snapshot.
- `--ledger-cleanup-plan` is local-only and reports unrecorded sweep runs that
  should be recorded into the campaign ledger or deliberately documented as
  no-order legacy runs.
- `--sell-authority-drift-report` compares a previous and current SELL
  authority allowlist. Product removals are blocking evidence that the older
  allowlist must not be used for live execution.
- `--authority-operator-report` separates strict fill-ledger authority from
  Coinbase average-cost authority, including stale or drift-blocked counts.
- `--strict-sell-canary-candidates` selects capped strict SELL candidates while
  excluding products sold by recent live SELL sweep runs.
- `--pnl-delta-report` compares durable P/L checkpoints across portfolio,
  since-last-purchase, realized-lot, product, and average-cost scopes when
  those fields are present in recorded snapshots.
- Dashboard campaign status reads only the local campaign ledger through
  `request_spot_campaign_status`.
- Dashboard campaign status exposes a derived `operator_summary` plus separate
  `latest_readiness_snapshot` and `latest_live_snapshot` fields. A later live
  canary can be the newest ledger record while the most useful readiness data
  still lives in the latest dry-run or release-gate snapshot.
- SELL campaigns still need known profitable inventory authority when that
  safety policy is configured. Coinbase average cost can be used only through
  the explicit opt-in average-cost authority path and extra buffer.

## USDC Campaign Design Lock

The all-USDC campaign feature is a configuration layer over the existing spot
portfolio sweep planner and live runner. Do not add a parallel spot campaign
executor.

Operator intent maps to fields this way:

- Buy or sell `X` notional per product:
  `side` plus `quote_notional`.
- Apply to Coinbase USDC spot products available to US customers:
  `product_scope.selection_rule =
  all_coinbase_usdc_spot_us_customer_available`,
  `quote_currency = USDC`, and `us_customer_available = true`.
- Repeat every `X` hours, not to exceed `N` runs:
  `automation.repeat_every_hours` and `automation.max_runs`.
- Limit blast radius:
  `safety_policy.max_notional_per_order`,
  `safety_policy.max_total_notional_per_run`,
  `safety_policy.max_planned_orders`, `safety_policy.max_skipped_orders`, and
  optional product allow/deny lists.
- Track durable P/L:
  campaign snapshots in `runtime_state/spot_campaigns.jsonl`, sweep runs in
  `runtime_state/spot_portfolio_sweeps.jsonl`, fill-ledger rows, and optional
  cost-basis snapshots in `runtime_state/spot_cost_basis_snapshots.jsonl`.

BUY campaigns can use the broad all-USDC gate once wallet and safety caps pass.
SELL campaigns must first prove authority. The normal live SELL path is a
freshly regenerated SELL authority allowlist rendered to a sweep config and
then executed by `tools/run_spot_portfolio_sweep_live.py` with
`--approved-live-orders`. Coinbase average cost is allowed only through the
named buffered profile and should not be used for strict fill-ledger canaries.

## Outputs And Artifacts

- Campaign CLI:
  `tools/run_spot_campaign.py`
- Campaign strategy/status module:
  `business/spot_campaign.py`
- Campaign ledger:
  `runtime_state/spot_campaigns.jsonl`
- Equivalent sweep config output:
  operator-selected path from `--write-sweep-config-file`
- Dashboard WebSocket request:
  `request_spot_campaign_status`
- Dashboard WebSocket response:
  `spot_campaign_status`
- Focused regression:
  `tests/regression/test_spot_campaign.py`
- Summary prefix:
  `SPOT_CAMPAIGN`
- Latest sweep-run recorder:
  `tools/run_spot_campaign.py --record-latest-sweep-run`
- Partial-run retry planner:
  `tools/run_spot_campaign.py --retry-plan`
- Public retry-plan fixture:
  `docs/examples/spot-campaign-retry-plan-fixture.json`
- Canonical template writer:
  `tools/run_spot_campaign.py --template-profile <profile>`
- Config validation report:
  `tools/run_spot_campaign.py --validate-config-report`
- Dry-run diff:
  `tools/run_spot_campaign.py --dry-run-diff`
- Campaign run index:
  `tools/run_spot_campaign.py --run-index`
- Campaign P/L checkpoints:
  `tools/run_spot_campaign.py --pnl-checkpoints`
- Campaign P/L delta report:
  `tools/run_spot_campaign.py --pnl-delta-report`
- Campaign ledger cleanup plan:
  `tools/run_spot_campaign.py --ledger-cleanup-plan`
- No-order recovery drill:
  `tools/run_spot_campaign.py --no-order-recovery-drill`
- Broad all-USDC readiness gate:
  `tools/run_spot_campaign.py --all-usdc-readiness-gate`
- Scheduler due-state report:
  `tools/run_spot_campaign.py --scheduler-status`
- Admin API automation-service read:
  `GET /api/v1/spot/sweep/automation-service`
- SELL authority allowlist:
  `tools/run_spot_campaign.py --sell-authority-allowlist`
- SELL authority drift report:
  `tools/run_spot_campaign.py --sell-authority-drift-report`
- SELL authority operator comparison:
  `tools/run_spot_campaign.py --authority-operator-report`
- Strict SELL canary candidate selector:
  `tools/run_spot_campaign.py --strict-sell-canary-candidates`
- SELL authority allowlist outputs:
  `--write-allowlist-file`, `--write-allowlist-config-file`, and
  `--write-allowlist-sweep-config-file`
- SELL allowlist freshness summary:
  `sell_authority_allowlist`
- Imported baseline freshness summary:
  `baseline_freshness_audit`
- Coinbase average-cost authority gate:
  `coinbase_average_cost_authority_gate`
- Dashboard operator summary:
  `operator_status.operator_summary`
- Latest readiness snapshot:
  `operator_status.latest_readiness_snapshot`
- Latest live snapshot:
  `operator_status.latest_live_snapshot`

## Safety Constraints

- Campaign CLI modes do not submit, cancel, or move Coinbase orders.
- Dashboard campaign status is read-only. It shows readiness, due state,
  operation-lock state, recovery state, planned skips, notional, and P/L from
  durable local snapshots; it does not approve or submit live orders.
- Live canaries must use `tools/run_spot_portfolio_sweep_live.py` with
  `--approved-live-orders`.
- Broad all-USDC campaigns must pass `--all-usdc-readiness-gate` before live
  execution. The gate requires the canonical all-USDC selector, no allow/deny
  restriction, no `max_products` restriction, and explicit total/order/count
  safety caps.
- Retry plans exclude any product with submission evidence. A product with an
  exchange order id, successful response, submitted notional, or executed
  notional is not eligible for retry.
- Retry plans also exclude planned skips such as below-minimum quote notional
  rows, because no Coinbase placement was expected for those products.
- SELL allowlists must be regenerated immediately before live SELL approval.
  Account inventory can change outside this project, and local lots can be
  consumed by earlier live sells. The rendered sweep config expires quickly and
  live mode rejects stale or invalid allowlist metadata.
- A broad BUY campaign that passes all-USDC readiness is not evidence that a
  broad SELL campaign is ready. SELL readiness is authority-bound and may
  narrow to a small current allowlist.
- A strict SELL canary proposal may shrink to one product. Do not force a
  larger canary size when current strict authority does not support it.
- Keep artificial limits in the campaign safety policy: per-order notional,
  per-run notional, planned-order count, skipped-order count, and product
  allow/deny lists.
- Do not treat wallet inventory as profitable inventory.
- Do not use Coinbase average cost as SELL authority unless the campaign
  explicitly opts in and configures the extra profit buffer. Products that rely
  on Coinbase average-cost authority are blocked when the record is stale or
  local-vs-Coinbase drift is stale for that product.
- Treat imported baseline lots as operator-maintained state. Stale
  `remaining_quantity` values can overstate SELL authority; refresh them,
  include explicit source freshness metadata such as `source_updated_at`, or
  mark them unknown before using them for live SELL decisions.
- Imported baseline freshness is currently an audit signal, not an automatic
  live-order block. Broad SELL stages should keep using generated authority
  allowlists until an explicit operator policy is added to make stale baseline
  rows blocking.
- Do not broaden campaign scope to USD pairs without reopening the roadmap.

## Examples

See [Spot Campaign Examples](docs/examples/spot-campaign.md).

The retry-plan public fixture at
[docs/examples/spot-campaign-retry-plan-fixture.json](docs/examples/spot-campaign-retry-plan-fixture.json)
shows submitted, retryable no-submission, and planned-skip rows.

## Public Runbook

See [Spot Campaign Public Runbook](docs/SPOT_CAMPAIGN_PUBLIC_RUNBOOK.md) for
the ordered pre-live, live, and post-live checks.
