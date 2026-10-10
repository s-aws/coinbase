# External Testing Runbook

Reconciled with the checkout on 2026-10-09. External tests require separate
operator authorization and are excluded from the required local gate:

```powershell
.\.venv\Scripts\python.exe -m pytest -c tests/pytest.ini tests -m "not external" -v --tb=short
```

## Actual routing boundary

`tests/external/conftest.py` requires API credentials and a true
`COINBASE_USE_SANDBOX` flag before constructing the REST wrapper. It records
`COINBASE_SANDBOX_URL` (default `https://api-sandbox.coinbase.com`) but does not
pass that URL to the SDK `RESTClient` constructor. The flag and URL therefore
DO NOT establish sandbox routing. The production configuration also ignores
these external-test settings.

The optional public ticker smoke creates a normal SDK `WSClient`, with no
sandbox WebSocket URL. `COINBASE_ENABLE_WEBSOCKET_EXTERNAL=true` enables that
live public-feed test. Static WebSocket contract/wrapper checks in the external
directory also carry the `external` marker.

## Authorized execution

Before network execution, the operator must establish the intended account,
endpoint routing, credential scope, and database target. This documentation
update does not configure SDK routing or authorize external runs.

After those boundaries are explicitly approved, set credentials and any approved
routing configuration in the same PowerShell session as Windows Python. The
current fixture's expected opt-in assertion and full external command are:

```powershell
$env:COINBASE_USE_SANDBOX = "true"
.\.venv\Scripts\python.exe -m pytest -c tests/pytest.ini tests/external/ -v -m external --tb=short
```

Focused `rest_api` or `websocket` selections require an explicit user request.
Do not enable the live smoke merely to remove a skip.

## Coverage and evidence

`tests/external/test_coinbase_api.py` includes credentials/opt-in assertions,
live accounts/products/orders reads, stored user-message shape checks, wrapper
behavior checks, and an optional live ticker smoke. Passing stored shape checks
is not proof of live subscription ordering or placement/cancellation behavior.

`api_reference/` and `websocket_reference/` contain captured/reference fixtures;
they are not a live Coinbase specification. A contract mismatch requires review
of the actual response and source, not automatic fixture rewriting.

The test DB guard in `tests/conftest.py` defaults to localhost port 9876 and
rejects localhost port 5432. Preserve that guard and verify inherited overrides.
