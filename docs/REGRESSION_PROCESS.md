# Regression Process

This is the canonical backend regression policy for contextless maintainers and
agents. Historical plans may show older commands; use this page when there is a
conflict.

## Normal Phase Work

Ordinary phase work uses focused tests and validators that cover the changed
behavior. Do not run the full regression suite by default for every phase.

Examples of ordinary checks:

```powershell
python -m pytest tests/regression/test_admin_api_contract.py -q --tb=short
python tools/run_autonomous_work_queue_check.py --summary-only
python tools/generate_admin_api_openapi.py
```

Choose checks from the files, owners, and behavior touched by the change. The
focused checks must be strong enough to cover the changed behavior; a narrow
check must not be used as evidence for a broad claim.

## Full Regression Gate

Run the full backend regression suite before:

- marking a durable milestone complete
- public or release-candidate handoff
- deployment approval or deployment closeout
- release-hardening closeout
- Admin API/backend association closeout
- an explicit user request for full regression

Canonical closeout command:

```powershell
python tools/run_parallel_regression.py --workers 4
```

The runner rejects `--workers auto` and any value above `4`. Raise that code
cap only after measuring peak memory on the target host and updating this
policy and the runner tests. The regression suite is process-parallel, so each
worker imports project and test state independently; unbounded worker fan-out
can multiply memory use even when individual tests are not leaking.

This runner is process-parallel. It must not be replaced with thread-based
parallelism. Many regression files touch Python process globals, monkeypatch
environment variables, bind local services, use shared temp paths, or exercise
database resources that are unsafe inside one threaded interpreter. Separate
pytest worker processes isolate that state; the serial lane keeps tests with
shared external resources out of the parallel-safe lane.

## Test Process Hygiene

Interrupted or externally timed-out test commands can leave child workers
running after the parent shell exits. Before starting a full closeout gate, and
after any interrupted or timed-out backend/frontend test command, run the stale
process checker:

```powershell
python tools/check_stale_test_processes.py --include-sibling-frontend
```

The checker is report-only by default and only matches pytest, Vitest,
Playwright, npm test, release-gate, or local Next.js test-server command lines
that include this repository or the sibling `coinbase-frontend` path. If it
reports stale workers that are no longer part of an active validation run,
terminate only those matched process trees explicitly:

```powershell
python tools/check_stale_test_processes.py --include-sibling-frontend --kill
```

Do not manually kill generic `node.exe`, `python.exe`, `Code.exe`, `Codex.exe`,
Chrome, or VS Code extension processes based only on process name. Use command
line, repository path, age, and active validation state as the evidence.

## Serial Lane Classification

The process-parallel runner validates serial-lane classification before running
pytest. Regression files must use `pytest.mark.serial` when they touch:

- shared database cursors or fixed database resources
- fixed service ports or long-lived local services
- process-global state such as environment variables or working directory
- other resources that are unsafe across process workers

When the static classifier reports a false positive, add a documented comment:

```python
# parallel-regression: serial-safe: explain why this file is process-safe
```

Run only the classification preflight with:

```powershell
python tools/run_parallel_regression.py --check-serial-classification-only
```

## Sequential Fallback

Use the sequential pytest fallback only when `pytest-xdist` is unavailable and
the fallback is intentional:

```powershell
pytest tests/regression/ -v --tb=short
```

Do not treat the fallback as the preferred closeout command.

## Live Coinbase Scope

The regression gate is not a live Coinbase execution gate. External/live tests
remain explicitly approved, isolated, and outside normal regression. Regression
evidence should state that live Coinbase execution was not run unless a live
phase was explicitly approved.
