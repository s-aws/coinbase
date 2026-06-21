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
python tools/check_ownership.py
```

To enforce one owner explicitly:

```powershell
python tools/check_ownership.py --owner stealth_lifecycle
```

Pull requests use `.github/PULL_REQUEST_TEMPLATE.md` to record the primary
owner, canonical behavior path, focused tests, and public/private boundary
check. GitHub Actions runs `.github/workflows/public-agent-checks.yml` to make
sure changed files are covered by `.agents/ownership.yaml`.

Use the cleanup classifier before moving or archiving files:

```powershell
python tools/classify_repo_files.py --format markdown
```

Focused checks are the normal validation path for ordinary phase work. Full
regression is reserved for durable milestone closeout, public/release-candidate
handoff, deployment approval/closeout, release-hardening closeout,
Admin API/backend association closeout, or explicit user request:

```powershell
python tools/run_parallel_regression.py --workers 4
```

Use `pytest tests/regression/ -v --tb=short` only as an intentional sequential
fallback when `pytest-xdist` is unavailable.
