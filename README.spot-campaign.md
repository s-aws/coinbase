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
- persist durable campaign P/L and cost-basis snapshots
- expose campaign readiness in the dashboard
- render an equivalent sweep config for explicitly approved live canaries
- build a targeted retry config for products that were not submitted during a
  partial campaign sweep run

## Key Concepts

- Scope is USDC-only spot products. USD pairs are not included.
- Campaign config is versioned JSON. The stable config maps to the existing
  versioned sweep config used by `tools/run_spot_portfolio_sweep_live.py`.
- `tools/run_spot_campaign.py` is read-only with respect to Coinbase orders.
  It can read Coinbase products, wallets, and optional average cost basis, but
  it never calls `create_order`.
- Live campaign canaries use a rendered sweep config and the existing sweep
  runner with `--approved-live-orders`.
- The campaign dry-run matrix reuses `build_usdc_portfolio_sweep_plan`,
  `evaluate_sweep_safety_policy`, and `build_sweep_plan_explain`.
- Durable campaign snapshots are local JSONL records in
  `runtime_state/spot_campaigns.jsonl` by default.
- After a live sweep canary runs, `--record-latest-sweep-run` records the latest
  matching sweep run into the campaign ledger without calling Coinbase.
- If a live canary is partial, `--retry-plan` can derive a normal campaign and
  sweep config for only the products with no exchange order id and zero
  submitted/executed notional.
- Planned sweep skips are not retry candidates and do not make a live campaign
  canary blocked by themselves. Campaign recording uses the effective sweep
  outcome while preserving the raw recorded sweep status in the snapshot.
- Dashboard campaign status reads only the local campaign ledger through
  `request_spot_campaign_status`.
- Dashboard campaign status exposes a derived `operator_summary` plus separate
  `latest_readiness_snapshot` and `latest_live_snapshot` fields. A later live
  canary can be the newest ledger record while the most useful readiness data
  still lives in the latest dry-run or release-gate snapshot.
- SELL campaigns still need known profitable inventory authority when that
  safety policy is configured. Coinbase average cost can be used only through
  the explicit opt-in average-cost authority path and extra buffer.

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
- Retry plans exclude any product with submission evidence. A product with an
  exchange order id, successful response, submitted notional, or executed
  notional is not eligible for retry.
- Retry plans also exclude planned skips such as below-minimum quote notional
  rows, because no Coinbase placement was expected for those products.
- Keep artificial limits in the campaign safety policy: per-order notional,
  per-run notional, planned-order count, skipped-order count, and product
  allow/deny lists.
- Do not treat wallet inventory as profitable inventory.
- Do not use Coinbase average cost as SELL authority unless the campaign
  explicitly opts in and configures the extra profit buffer.
- Do not broaden campaign scope to USD pairs without reopening the roadmap.

## Examples

See [Spot Campaign Examples](docs/examples/spot-campaign.md).
