# External Testing Runbook

## Purpose

This runbook defines the standard way to run external Coinbase integration tests safely.
It covers REST contract tests, WebSocket contract tests, and opt-in live WebSocket smoke tests.

## Scope

- Test files: `tests/external/`
- Reference contracts: `api_reference/`, `websocket_reference/`
- Markers: `external`, `rest_api`, `websocket`, `coinbase`

## Safety Rules

1. Standard external tests always run in sandbox mode.
2. Never enable live WebSocket smoke tests unless explicitly needed.
3. Keep external tests isolated from normal local regression runs.
4. Live spot order smoke is allowed only as a manual, explicitly approved
   release-readiness exception. It must report every live order and all
   submitted/executed notional.
5. Enterprise admin frontend release checks are separate dry/no-live checks;
   they must report live Coinbase execution as not run with notional `$0` and
   do not approve any live smoke command in this runbook.

## Required Environment Variables

### Required for External Tests

PowerShell:

```powershell
$env:COINBASE_API_KEY = "your_key"
$env:COINBASE_API_SECRET = "your_secret"
$env:COINBASE_USE_SANDBOX = "true"
```

Bash:

```bash
export COINBASE_API_KEY="your_key"
export COINBASE_API_SECRET="your_secret"
export COINBASE_USE_SANDBOX=true
```

### Optional for Live WebSocket Smoke Tests

PowerShell:

```powershell
$env:COINBASE_ENABLE_WEBSOCKET_EXTERNAL = "true"
```

Bash:

```bash
export COINBASE_ENABLE_WEBSOCKET_EXTERNAL=true
```

### Optional for Approved Live Spot Smoke

Live spot smoke does not use `tests/external/` sandbox fixtures. It uses the
live Coinbase Advanced Trade API and places real spot orders.

PowerShell:

```powershell
$env:COINBASE_API_KEY = "your_live_key"
$env:COINBASE_API_SECRET = "your_live_secret"
python tools/run_live_spot_usdc_smoke.py --approved-live-orders
python tools/run_live_spot_usdc_smoke.py --approved-live-orders --validation-matrix
python tools/run_live_spot_usdc_smoke.py --approved-live-orders --validation-matrix --reconciliation-gate
```

Bash:

```bash
export COINBASE_API_KEY="your_live_key"
export COINBASE_API_SECRET="your_live_secret"
python tools/run_live_spot_usdc_smoke.py --approved-live-orders
python tools/run_live_spot_usdc_smoke.py --approved-live-orders --validation-matrix
python tools/run_live_spot_usdc_smoke.py --approved-live-orders --validation-matrix --reconciliation-gate
```

## Standard Commands

### Run All External Tests

```bash
pytest tests/external/ -v -m external --tb=short
```

### Run REST External Tests Only

```bash
pytest tests/external/test_coinbase_api.py -v -m rest_api --tb=short
```

### Run WebSocket External Tests Only

```bash
pytest tests/external/test_coinbase_api.py -v -m websocket --tb=short
```

Notes:
- With no opt-in flag, deterministic WebSocket contract/wrapper tests run and live smoke tests skip.
- With `COINBASE_ENABLE_WEBSOCKET_EXTERNAL=true`, live ticker smoke test is enabled.
- Live spot smoke is not a pytest default. Run
  `python tools/run_live_spot_usdc_smoke.py --approved-live-orders` only after
  explicit approval, and report the `LIVE_COINBASE_SPOT_SMOKE_SUMMARY`
  notional totals.
- The approved live validation matrix is:
  `python tools/run_live_spot_usdc_smoke.py --approved-live-orders --validation-matrix`.
  It places market BUY, post-only limit BUY cancel, post-only limit SELL
  cancel, and market SELL on the cheapest previewable USDC spot product.
  Report every order plus total submitted/executed notional from the summary.
- The approved live reconciliation gate is:
  `python tools/run_live_spot_usdc_smoke.py --approved-live-orders --validation-matrix --reconciliation-gate`.
  It places the same live orders and also requires executed market orders to
  have Coinbase REST fills that can be backfilled into local `fill_ledger`.
  Report the gate status and all notional totals from the summary.
- Live spot smoke does not have to return inventory to zero. Use
  `--retain-inventory` when bought base should remain available for future
  sell-path tests.

## What Is Covered

### REST Coverage

- Accounts contract checks against `api_reference/accounts/`
- Product contract checks against `api_reference/products/`
- Orders contract checks including both `client_order_id` and `order_id`

### WebSocket Coverage

- Authenticated user-message reference contract checks from `websocket_reference/authenticated/`
- Wrapper behavior checks for `external/coinbase_websocket.py` without network dependency
- Opt-in live ticker smoke test for channel connectivity and payload basics

## CI/Automation Recommendations

1. Run `-m "not external"` on every commit/PR.
2. Run `-m external` on protected branches or scheduled jobs with sandbox secrets.
3. Keep `COINBASE_ENABLE_WEBSOCKET_EXTERNAL` disabled in default CI jobs.
4. Add a separate manual job for live WebSocket smoke tests.
5. Keep live spot order smoke out of default CI. If automated later, make it a
   protected manual job with strict notional caps and summary artifact capture.

## Troubleshooting

### "Coinbase API credentials not set"

- Ensure `COINBASE_API_KEY` and `COINBASE_API_SECRET` are set in the current shell.

### "External tests require COINBASE_USE_SANDBOX=true"

- Set `COINBASE_USE_SANDBOX=true` and rerun.

### Live WebSocket tests are skipped

- Set `COINBASE_ENABLE_WEBSOCKET_EXTERNAL=true`.
- Confirm network access to Coinbase WebSocket endpoints.

### Contract mismatch due to field naming drift

- Prefer stable required-field assertions for live payloads.
- Keep static reference files in `api_reference/` and `websocket_reference/` up to date.

### Live spot order submitted but fill backfill failed

- Treat the Coinbase order as live exchange truth.
- Use the summary `exchange_order_id` values to inspect Coinbase directly.
- Dry-run candidate recovery with:
  `python tools/run_spot_fill_backfill_recovery.py --dry-run --summary-only`.
- Retry recorded fill backfill with:
  `python tools/run_spot_fill_backfill_recovery.py --source sweep --run-id <run_id>`.
- Run `python tools/run_spot_portfolio_sweep_live.py --reconcile --run-id <run_id>`
  for sweep runs, or run
  `python tools/run_spot_sweep_recovery_gate.py --run-id <run_id>` to combine
  reconciliation and fill-backfill retry after fixing DB credentials/connectivity.
- Do not infer that the order did not fill from a local backfill error.

### Live validation matrix leaves inventory in the account

- This is acceptable when `--retain-inventory` was used or when a sell leg
  failed/skipped.
- Record retained base from the summary and reuse it for future SELL tests
  instead of forcing an immediate zero-out order.
