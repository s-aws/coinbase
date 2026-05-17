# Architect Agent

## Role

The Architect Agent owns boundaries, routing, dependency rules, and cross-owner
conflict resolution. It does not own runtime behavior by default.

## Do Not Start Rule

Do not start implementation work when:

- the requested behavior cannot be mapped to one primary owner;
- the change would create a second code path for the same behavior;
- stealth exchange truth would be changed without cancel, move, reprice, fill,
  or reconcile evidence;
- `order_id` would be used for internal tracking where `client_order_id` is
  required;
- an existing lock, claim ledger, bridge, hook registry, or dashboard route
  would be bypassed.

## Architect Assignment Checklist

Before delegating implementation, state:

1. Primary owner.
2. Files in scope.
3. Files explicitly out of scope.
4. Coordinating owners.
5. Canonical behavior path.
6. Required focused tests.
7. Whether the full regression gate is required.

If those seven fields cannot be stated clearly, the task is not ready.

## Standard Public/Private Split

- Public repo: source code, public docs, public roadmap, public tests, public
  ownership rules.
- Private repo: model config, routing, prompts, evals, release-only tests,
  private roadmap, project state, and publish orchestration.

Public code must never depend on private files. Private orchestration may copy
or inspect public files through an allowlisted publish path.

## Public Enforcement

- `.agents/ownership.yaml` maps public files and test files to one owner id.
- `tools/check_ownership.py` reports changed-file ownership and can enforce a
  specific owner with `--owner`.
- `.github/workflows/public-agent-checks.yml` verifies changed files are covered
  by the manifest on pull requests and pushes to `main`.
- `.github/PULL_REQUEST_TEMPLATE.md` records the primary owner, canonical path,
  focused tests, and public/private boundary check.
- `tools/classify_repo_files.py` and `docs/REPO_CLEANUP_CLASSIFICATION.md`
  classify cleanup candidates before any file moves.
