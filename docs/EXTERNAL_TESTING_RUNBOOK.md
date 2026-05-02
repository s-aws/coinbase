> Documentation status (2026-05-02): **Supplemental (non-canonical active reference)**
> This file is useful operational context but is not the canonical source of truth.
> Canonical living docs remain under genai_data/.
# External Testing Runbook

## Purpose

This runbook defines the standard way to run external Coinbase integration tests safely.
It covers REST contract tests, WebSocket contract tests, and opt-in live WebSocket smoke tests.

## Scope

- Test files: `tests/external/`
- Reference contracts: `api_reference/`, `websocket_reference/`
- Markers: `external`, `rest_api`, `websocket`, `coinbase`

## Safety Rules

1. Always run in sandbox mode.
2. Never enable live WebSocket smoke tests unless explicitly needed.
3. Keep external tests isolated from normal local regression runs.

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

