# Spot Phases 185-196 Report

Status: completed.

This is a historical phase report. Raw dashboard, smoke, sweep, campaign, and
legacy engine mutation paths described below are now source-disabled; they are
not current operator instructions.

No live Coinbase execution is approved or run in this phase group. Submitted
notional: `0` USDC. Executed notional: `0` USDC.

## Scope

These phases harden the existing USDC spot campaign and direct-order surfaces.
They did not add a second Spot execution path. The former sweep mutation mode
is now source-disabled. Current Controlled-live testing uses only authenticated
Admin API manual Spot LIMIT/GTC place/cancel under the manager lease and
backend per-request gates.

## Phase Results

- Phase 185, Dashboard Direct Audit UI Panel: dashboard now has a direct spot
  order audit panel keyed by `client_order_id`; browser smoke covers request
  emission and response rendering.
- Phase 186, Campaign Cleanup Apply Gate Design: campaign ledger cleanup apply
  is local-only, dry-run by default, and appends records only when explicit run
  ids are approved with `--execute-local-cleanup-apply`.
- Phase 187, Strict SELL Authority Shrinkage Triage: current strict authority
  narrowing is expected. The generated strict proposal planned three rows,
  allowed `PERP-USDC`, blocked `RARE-USDC` and `SXT-USDC`, and skipped `384`
  rows below quote minimum.
- Phase 188, Exact Next SELL Canary Proposal: the current proposal is one
  `market_ioc` SELL for `PERP-USDC`, requested notional `1` USDC, planned base
  size `50`, estimated price `0.02`, and strict fill-ledger authority of
  `104.619` known profitable units.
- Phase 189, Product P/L Payload Control: campaign dry-run P/L summaries omit
  per-product rows by default; operators must opt in with
  `--include-pnl-products`.
- Phase 190, Dashboard SELL Authority Telemetry: campaign dashboard summary now
  distinguishes strict fill-ledger count, Coinbase average-cost count, blocked
  count, and stale/drift blocked count.
- Phase 191, Scheduler Dry-Run Rehearsal: `--scheduler-status` now exits `0`
  only when the recurring campaign is due. Not-due or disabled scheduler
  states return `1` while still printing the JSON status payload.
- Phase 192, Retry Plan Public Fixture Expansion: public retry-plan fixture is
  available at `docs/examples/spot-campaign-retry-plan-fixture.json` and is
  covered by regression tests.
- Phase 193, Contextless Blind-Agent Rerun: passed after repository fixes. The
  final blind run identified the correct direct dashboard gates, cancellation
  by `client_order_id`, live sweep BUY/SELL boundaries, mandatory live SELL
  known-profit policy, Admin HTTP live-disabled status, direct-audit
  `audited_order_*` fields, and no remaining
  `--disable-safety-policy --approved-live-orders` path.
- Phase 194, Direct Manual Order Audit Backfill Review: older direct dashboard
  orders should be audited by `client_order_id` with the direct audit command
  or dashboard audit panel. There is no broad local mutation or synthetic
  backfill path in this phase group.
- Phase 195, Phase 184 Live Approval Packet: exact packet is documented below.
  It is not approval to execute.
- Phase 196, Full Release Gate: passed. Backend regression, spot readiness
  release gate, dashboard e2e smoke, and the separate frontend quality gate all
  passed after the blind-agent rerun.

## Verification

- `pytest tests/regression/ -v --tb=short`: `745 passed`.
- `python tools/run_spot_readiness_regression.py`: `223 passed`.
- `python tools/run_spot_release_gate.py`: `status: "passed"`;
  `live_coinbase_orders_ran: false`; submitted/executed notional `0` USDC.
- `pytest tests/e2e/test_direct_order_ui_smoke.py tests/e2e/test_spot_readiness_ui_smoke.py -v --tb=short`:
  `3 passed`.
- Frontend quality gate in `C:\coinbase-frontend`: `npm run typecheck`,
  `npm run lint`, `npm run api:check`, `npm run test`, and
  `npm run test:e2e` all passed.

## Phase 184/195 SELL Canary Packet

Current source artifacts:

- `runtime_state/phase184_sell_strict_proposal_allowlist.json`
- `runtime_state/phase184_sell_strict_proposal_allowlist.config.json`
- `runtime_state/phase184_sell_strict_proposal_allowlist.sweep.json`

The existing Phase 184 allowlist was generated at
`2026-06-10T14:32:37.400322+00:00` and expired at
`2026-06-10T14:37:37.400322+00:00`. It must be regenerated and revalidated
immediately before any later live approval.

Current proposal values:

- Side: `SELL`
- Order type: `market_ioc`
- Product: `PERP-USDC`
- Requested notional: `1` USDC
- Max submitted notional cap for the packet: `1` USDC
- Planned base size from the source proposal: `50`
- Estimated price from the source proposal: `0.02`
- Authority source: `fill_ledger`
- Authority status: `known_profitable`
- Known profitable quantity: `104.619`
- Blocked rows in the source proposal: `RARE-USDC`, `SXT-USDC`
- Skipped rows in the source proposal: `384`, all below quote minimum in the
  captured artifact

Historical pre-live regeneration/validation shape:

```powershell
python tools/run_spot_campaign.py --config-file runtime_state/phase184_sell_strict_proposal_allowlist.config.json --sell-authority-profile fill_ledger_strict --sell-authority-allowlist --write-allowlist-file runtime_state/phase195_perp_sell_canary.allowlist.json --write-allowlist-config-file runtime_state/phase195_perp_sell_canary.config.json --write-allowlist-sweep-config-file runtime_state/phase195_perp_sell_canary.sweep.json --summary-only
python tools/run_spot_portfolio_sweep_live.py --config-file runtime_state/phase195_perp_sell_canary.sweep.json --validate-config --max-products 1 --max-total-notional-per-run 1 --max-notional-per-order 1 --max-planned-orders 1
```

Historical live command shape (now source-disabled):

```powershell
python tools/run_spot_portfolio_sweep_live.py --config-file runtime_state/phase195_perp_sell_canary.sweep.json --require-known-profitable-inventory --approved-live-orders --max-products 1 --max-total-notional-per-run 1 --max-notional-per-order 1 --max-planned-orders 1 --summary-only
```

Historical post-live evidence requirements were:

- Report `LIVE COINBASE EXECUTION`.
- Report submitted and executed notional.
- Report product id, `client_order_id`, exchange order id, and fill-backfill
  result.
- Run direct audit by `client_order_id`.
- Record the latest sweep run into the campaign ledger.
- Rebuild P/L and fill-ledger health.

## Direct Manual Order Audit Backfill Review

Direct dashboard spot orders are manual one-offs. They are not the normal
campaign automation path and they do not bypass the shared action-condition
guard. For older direct orders, the durable backfill approach is:

```powershell
python tools/run_spot_direct_order_audit.py --client-order-id <client_order_id>
```

The dashboard panel sends the same audit request with `client_order_id`. If an
older order lacks a known `client_order_id`, this phase does not invent one or
mutate local ledgers. Use exchange-native evidence only as audit evidence, not
as an internal tracking replacement.
