# Spot Campaign Public Runbook

> **Current operator boundary:** campaign and sweep exchange mutation modes are
> source-disabled. This document is historical/read-only reference. The only
> supported Controlled-live operator execution surface is authenticated Admin
> API manual Spot LIMIT/GTC place/cancel under the manager lease and backend
> per-request gates.

This is a parked operator reference, not the current work queue. Standing
closeout is `operator_ready_admin_mvp_runtime_v1`; do not run campaign, fan-out,
retry, or scheduler work from this document without explicit operator
reprioritization.

This runbook records the ordered operator path for USDC spot campaigns. Campaign
commands are read-only with respect to Coinbase orders. The former sweep live
runner mutation mode is retained only as source-disabled historical material.

## Pre-Live Checks

1. Write or refresh a canonical template:

   ```powershell
   python3.13 tools/run_spot_campaign.py --template-profile buy_canary --write-template-file runtime_state/spot_campaign_buy_canary.json
   ```

2. Validate config safety:

   ```powershell
   python3.13 tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_buy_canary.json --validate-config-report
   ```

3. Build and record a dry-run matrix:

   ```powershell
   python3.13 tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_buy_canary.json --dry-run-matrix --summary-only --record-snapshot
   ```

4. Run the campaign release gate:

   ```powershell
   python3.13 tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_buy_canary.json --release-gate --summary-only --record-snapshot
   ```

5. For broad campaigns, run the all-USDC readiness gate:

   ```powershell
   python3.13 tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_buy_all_usdc.json --all-usdc-readiness-gate --summary-only
   ```

6. Render the equivalent sweep config:

   ```powershell
   python3.13 tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_buy_canary.json --write-sweep-config-file runtime_state/spot_campaign_buy_canary.sweep.json
   ```

## Historical Live Execution (Source-Disabled)

This command formerly submitted Coinbase orders; it now exits with the fixed
source-disabled diagnostic:

```powershell
python3.13 tools/run_spot_portfolio_sweep_live.py --config-file runtime_state/spot_campaign_buy_canary.sweep.json --approved-live-orders --summary-only
```

For historical ledgers only, the following command can associate an already
recorded matching sweep summary with campaign readback. It does not authorize
or create a new live run:

```powershell
python3.13 tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_buy_canary.json --record-latest-sweep-run --summary-only
```

## Historical Post-Live Readback Checks

1. Rebuild campaign status:

   ```powershell
   python3.13 tools/run_spot_campaign.py --status
   ```

2. Build the local run index:

   ```powershell
   python3.13 tools/run_spot_campaign.py --run-index
   ```

3. Build P/L checkpoints:

   ```powershell
   python3.13 tools/run_spot_campaign.py --pnl-checkpoints
   python3.13 tools/run_spot_campaign.py --pnl-delta-report --summary-only
   ```

4. Check for unrecorded sweep runs before treating campaign state as clean:

   ```powershell
   python3.13 tools/run_spot_campaign.py --ledger-cleanup-plan --summary-only
   ```

5. Run recovery and fill-ledger health gates:

   ```powershell
   python3.13 tools/run_spot_sweep_recovery_gate.py --summary-only
   python3.13 tools/run_spot_fill_ledger_health.py --summary-only
   ```

6. Run the public release gate:

   ```powershell
   python3.13 tools/run_spot_release_gate.py --include-browser --campaign-config-file runtime_state/spot_campaign_buy_canary.json
   ```

## SELL Campaigns

Use the campaign-to-sweep path for SELL canaries. Do not use direct dashboard
`place_order` as the normal SELL canary path because it does not produce the
campaign dry-run matrix, SELL authority allowlist, sweep ledger, retry plan, or
recovery evidence.

1. Write or refresh the SELL canary template:

   ```powershell
   python3.13 tools/run_spot_campaign.py --template-profile sell_canary --write-template-file runtime_state/spot_campaign_sell_canary.json
   ```

2. Validate config safety:

   ```powershell
   python3.13 tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_sell_canary.json --validate-config-report
   ```

3. Build and record a dry-run matrix:

   ```powershell
   python3.13 tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_sell_canary.json --dry-run-matrix --record-snapshot
   ```

4. Run the campaign release gate:

   ```powershell
   python3.13 tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_sell_canary.json --release-gate --record-snapshot
   ```

5. Generate a strict narrowed SELL authority allowlist:

   ```powershell
   python3.13 tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_sell_canary.json --sell-authority-profile fill_ledger_strict --sell-authority-allowlist --write-allowlist-file runtime_state/spot_campaign_sell_canary.strict.allowlist.json --write-allowlist-config-file runtime_state/spot_campaign_sell_canary.strict.allowlist.config.json --write-allowlist-sweep-config-file runtime_state/spot_campaign_sell_canary.strict.allowlist.sweep.json --record-snapshot --summary-only
   ```

6. If an older allowlist is under consideration, compare it against the fresh
   allowlist first:

   ```powershell
   python3.13 tools/run_spot_campaign.py --sell-authority-drift-report --baseline-allowlist-file runtime_state/spot_campaign_sell_canary.previous.strict.allowlist.json --current-allowlist-file runtime_state/spot_campaign_sell_canary.strict.allowlist.json --summary-only
   ```

   A product-removal result means the older allowlist is stale. Keep it only as
   historical evidence.

7. Select strict SELL candidates for offline review from the fresh allowlist:

   ```powershell
   python3.13 tools/run_spot_campaign.py --strict-sell-canary-candidates --input-allowlist-file runtime_state/spot_campaign_sell_canary.strict.allowlist.json --summary-only
   ```

   Use the candidate count reported by the current allowlist. Do not force a
   three-product review when only one product currently has strict authority.

8. Validate the rendered allowlist sweep config for offline review. Do not use
   `--summary-only` here when the operator needs to inspect
   exact product ids, base sizes, estimated notionals, and `sell_authority`
   rows:

   ```powershell
   python3.13 tools/run_spot_portfolio_sweep_live.py --config-file runtime_state/spot_campaign_sell_canary.strict.allowlist.sweep.json --validate-config --max-products 1 --max-total-notional-per-run 1 --max-notional-per-order 1 --max-planned-orders 1 --max-skipped-orders 500
   ```

9. Historical execution command (now source-disabled; do not run as an
   operator workflow):

   ```powershell
   python3.13 tools/run_spot_portfolio_sweep_live.py --config-file runtime_state/spot_campaign_sell_canary.strict.allowlist.sweep.json --require-known-profitable-inventory --approved-live-orders --max-products 1 --max-total-notional-per-run 1 --max-notional-per-order 1 --max-planned-orders 1 --max-skipped-orders 500
   ```

10. Inspect or associate an already-recorded historical result:

   ```powershell
   python3.13 tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_sell_canary.json --record-latest-sweep-run --summary-only
   python3.13 tools/run_spot_sweep_recovery_gate.py --summary-only
   python3.13 tools/run_spot_fill_ledger_health.py --summary-only
   ```

SELL configs can also name authority policy explicitly when they use a profile:

```powershell
python3.13 tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_sell.json --sell-authority-profile fill_ledger_strict --write-profiled-config-file runtime_state/spot_campaign_sell.profiled.json
```

Use `coinbase_average_cost_buffered` only when Coinbase average-cost authority
is intentionally allowed and the configured buffer is acceptable for the run.
Average-cost allowlists exclude rows blocked by Coinbase average-cost
freshness or local-drift gates. Rendered configs are offline review artifacts.

For non-canary SELL configs, generate a narrowed SELL authority allowlist for
offline review:

```powershell
python3.13 tools/run_spot_campaign.py --config-file runtime_state/spot_campaign_sell.profiled.json --sell-authority-allowlist --write-allowlist-file runtime_state/spot_campaign_sell.allowlist.json --write-allowlist-config-file runtime_state/spot_campaign_sell.allowlist.config.json --write-allowlist-sweep-config-file runtime_state/spot_campaign_sell.allowlist.sweep.json --record-snapshot --summary-only
```

Validate the rendered allowlist sweep config offline. Omit `--summary-only` for
detailed inspection:

```powershell
python3.13 tools/run_spot_portfolio_sweep_live.py --config-file runtime_state/spot_campaign_sell.allowlist.sweep.json --validate-config
```

Historical SELL command (now source-disabled):

```powershell
python3.13 tools/run_spot_portfolio_sweep_live.py --config-file runtime_state/spot_campaign_sell.allowlist.sweep.json --require-known-profitable-inventory --approved-live-orders --summary-only
```

Strict fill-ledger authority subtracts prior local SELL fills from known BUY
lots before authorizing another SELL. Imported baseline lots are trusted as
operator-provided state, including `remaining_quantity`; stale baselines can
overstate SELL authority and must be refreshed or marked unknown before use.
Baseline freshness is reported for operator review. No allowlist can enable an
exchange mutation through the source-disabled campaign/sweep path.
