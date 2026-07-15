# Public Agent Contracts

This directory contains the public, non-secret operating contracts for agent
work on this repository.

The public repo may contain:

- ownership boundaries
- coding invariants
- public test commands
- public roadmap items
- non-secret agent role descriptions

The public repo must not contain:

- model names or routing rules
- private prompts
- eval logs
- private release gates
- private in-progress roadmap details
- secrets or environment-specific credentials

Private orchestration may read this repo. Public code must never import, read,
or require files from private orchestration repos.

## Read Order

1. `AGENT_ARCHITECT.md`
2. `INVARIANTS.md`
3. `OWNERSHIP.md`
4. The specialist context pack for the files in scope
5. `.agents/ownership.yaml`

The enterprise Admin API owner context is
`AGENT_ADMIN_API_CONTRACT.md`. It applies to current FastAPI/OpenAPI work and
must preserve the existing single trading behavior path.

## Enforcement

Use the ownership checker to inspect changed files:

```powershell
python3.13 tools/check_ownership.py
```

To enforce one owner explicitly:

```powershell
python3.13 tools/check_ownership.py --owner stealth_lifecycle
```

Pull requests use `.github/PULL_REQUEST_TEMPLATE.md` to record the primary
owner, canonical behavior path, focused tests, and public/private boundary
check. GitHub-hosted agent workflows are retired; run the ownership and policy
checks directly in the local Linux Docker workspace.

Use the cleanup classifier before moving or archiving files:

```powershell
python3.13 tools/classify_repo_files.py --format markdown
```

Focused checks are the normal validation path for ordinary phase work. The
canonical regression policy lives in [Regression Process](../REGRESSION_PROCESS.md).
Full regression is reserved for durable milestone closeout,
public/release-candidate handoff, deployment approval/closeout,
release-hardening closeout, Admin API/backend association closeout, or explicit
user request:

```powershell
python3.13 tools/run_parallel_regression.py --workers 4
```

Use `pytest tests/regression/ -v --tb=short` only as an intentional sequential
fallback when `pytest-xdist` is unavailable.

The parallel runner validates serial-lane classification before running pytest.
Shared DB cursor, fixed service port, process-global state, and other
process-shared regression tests must be marked `pytest.mark.serial`; regression
files importing the full FastAPI app factory are also serial-lane-only to avoid
multiplying the route-model memory footprint across workers. Documented false
positives use `parallel-regression: serial-safe`.

The runner also records per-lane peak memory samples in its summary JSON when
the Windows memory guard is active. Before pytest starts, it also fails fast
when oversized repo-local runtime artifacts under `runtime_state/` exceed
`1 GiB`. Preserve the summary line for closeout evidence.
`runtime_artifact_preflight_failed` means the gate failed before pytest; run
the runtime artifact checker, preserve evidence, and clean or archive artifacts
only after explicit operator cleanup approval. `memory_guard_aborted` means the
gate failed during pytest. Run the stale process checker, run the runtime
artifact checker, then split or reduce the offending regression surface before
retrying.

Before full closeout gates and after interrupted or timed-out backend/frontend
test commands, run:

```powershell
python3.13 tools/check_stale_test_processes.py --include-sibling-frontend
```

Use `--kill` only for matched repo-owned test command lines that are stale or
above the default high-memory threshold and not part of active validation. Do
not terminate generic `node.exe`,
`python.exe`, Codex, VS Code, or browser processes by name alone.

After a memory-guard abort or unexplained memory spike, also run:

```powershell
python3.13 tools/check_runtime_artifacts.py
```

It is report-only and identifies oversized `runtime_state/` test artifacts; do
not delete artifacts without an explicit cleanup decision.

## Subagent Hygiene

Phase-end cleanup is the canonical timing: close subagents spawned for that
phase and any stale or previously unused subagents from earlier phases or
milestones found during the sweep after their findings have been consumed,
remediated, or explicitly deferred. Durable milestone closeout is a final audit
sweep, not the first cleanup point. Do not leave completed, failed, superseded,
stale, or unused subagents open unless they are part of an active handoff with
recorded owner, purpose, and expected next action. Do not close a subagent that
is still running required validation, producing required evidence, or awaiting
a user decision. Record the phase-end or milestone-closeout sweep result in the
phase evidence, handoff, or closeout summary before advancing.
