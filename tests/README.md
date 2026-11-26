# Test Suite

Reconciled with the checkout on 2026-11-26. The required gate for every
non-agent-file change is the complete local non-external suite, including
regression tests. Run it from the repository root on Linux:

```bash
./setup.sh
./scripts/run_tests.sh
```

For a committed clean worktree, `./scripts/validate_release.sh` wraps that same
suite with repository-graph, diff, and final cleanliness checks. It does not
run external tests or deploy the runtime.

`AGENTS.md` and `agent.md` control the execution policy. Focused test files,
name filters, and single cases require an explicit user request. Run the suite
sequentially; tests share process globals, files, and a test database.

## Environment

The runtime requires Python 3.14. `tests/pytest.ini` enables strict config and
markers, reports warnings, and treats unhandled thread exceptions as errors.
`pytest-timeout` supplies the configured 30-second per-test timeout.

`tests/conftest.py` supplies common mock/sample fixtures and forces PostgreSQL
to the isolated `127.0.0.1:9876/postgres` target, with `postgres` user/password.
Some tests use mocks; others connect to this real test PostgreSQL instance.
There is no SQLite test backend. On Linux, `scripts/test_database.sh` creates a
user-owned cluster under `.local/test-postgres`; pytest starts it on demand and
non-destructively initializes the complete schema before collection. Container
names are operator-managed, not a code requirement.

The test guard rejects localhost port 5432 unless `ALLOW_PROD_DB=1`; leave that
override unset. Runtime `COINBASE_DB_*` variables are deliberately ignored by
pytest. Override an isolated test target only with `COINBASE_TEST_DB_*`.
Set `COINBASE_TEST_DB_AUTOSTART=0` only when another process manages that test
server.

Two exchange-free Linux resource checks are available outside the required
gate: `./scripts/run_cancel_stress.sh` exercises dashboard publication alone;
`./scripts/run_cancel_pipeline_stress.sh` traverses authenticated user-event
reduction, the engine worker pool, the isolated database, and the dashboard;
`./scripts/run_user_recovery_stress.sh` exercises private-feed generation
fencing and database-backed process restart recovery.

## Inventory

| Directory | Test files | Purpose |
| --- | ---: | --- |
| `unit/` | 38 | Component logic, concurrency primitives, graph contracts |
| `integration/` | 7 | Cross-module workflows and bridge wiring |
| `regression/` | 83 | Lifecycle, persistence, deployment, UI, ID, and race boundaries |
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
