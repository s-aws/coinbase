# Test Suite

Reconciled with the checkout on 2026-10-09. The required gate for every
non-agent-file change is the complete local non-external suite, including
regression tests. Run it from the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r tests\requirements.txt
.\.venv\Scripts\python.exe -m pytest -c tests/pytest.ini tests -m "not external" -v --tb=short
```

`AGENTS.md` and `agent.md` control the execution policy. Focused test files,
name filters, and single cases require an explicit user request. Run the suite
sequentially; tests share process globals, files, and a test database.

## Environment

The runtime requires Python 3.13. `tests/pytest.ini` enables strict config and
markers, reports warnings, and treats unhandled thread exceptions as errors.
`pytest-timeout` supplies the configured 30-second per-test timeout.

`tests/conftest.py` supplies common mock/sample fixtures and defaults PostgreSQL
to `127.0.0.1:9876/postgres`, with `postgres` user/password. Some tests use mocks;
others connect to this real test PostgreSQL instance. There is no SQLite test
backend. Host port 9876 must map to the server's PostgreSQL port 5432.
Container names are operator-managed, not a code requirement.

The test guard rejects localhost port 5432 unless `ALLOW_PROD_DB=1`; leave that
override unset. Defaults use `setdefault`, so inherited environment overrides
still matter. Set Windows `$env:` values in the same PowerShell process that
launches Windows Python; WSL inline environment assignments do not establish
that Windows process's database target.

## Inventory

| Directory | Test files | Purpose |
| --- | ---: | --- |
| `unit/` | 38 | Component logic, concurrency primitives, graph contracts |
| `integration/` | 7 | Cross-module workflows and bridge wiring |
| `regression/` | 78 | Lifecycle, persistence, UI, ID, and race boundaries |
| `e2e/` | 2 | In-process trading/user-message workflows |
| `external/` | 1 | Opt-in Coinbase contracts and network smoke |
| `tests/` root | 2 | Exception and lot-tracking integration checks |

See [TEST_FILES_INDEX.md](TEST_FILES_INDEX.md) for the exact file inventory and
[TEST_COVERAGE_SUMMARY.md](TEST_COVERAGE_SUMMARY.md) for domain navigation.
File counts are not collected case counts or measured coverage percentages.
Root repository `test_*.py` diagnostics outside `tests/` are not part of this gate.

## External tests

External tests are deselected by the default command, including static contracts
located in that directory. Credentials and opt-in assertions do not prove
sandbox routing: the fixture records a sandbox URL but does not pass it to
`RESTClient`. The live WebSocket smoke uses a production public feed. External
execution requires separately authorized routing and account scope; see
[the external runbook](../docs/EXTERNAL_TESTING_RUNBOOK.md).

## Adding coverage

Use the existing domain file where possible. Test the observed failure and
outcome, including lock/claim ownership, ID lineage, persistence failure, and
exchange acknowledgement when they apply. Do not infer production coverage
from a static call edge, a passing mock, or a historical completion note.

Fixtures in `api_reference/` and `websocket_reference/` are stored examples;
check their shape against the behavior under test before reusing them.
