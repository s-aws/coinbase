# Autonomous Work Queue

This document records durable approval for unattended work on this project.
It exists so a contextless maintainer or agent can continue approved work
without relying on chat history.

## Active Approval

- Approved phase range: **541-560**.
- Work may continue through the approved range without asking for another
  approval when the work stays inside the phase scope and cap policy below.
- The prior live Coinbase cap posture is carried forward, but live execution
  remains exceptional. Default work is dry/no-live.
- If any stop condition occurs, resolve it before advancing to the next phase.

## Live Coinbase Cap Policy

Default: no live Coinbase execution.

When a phase explicitly requires live Coinbase evidence under the carried
forward cap approval:

- Product scope: cheapest Coinbase `USDC` spot product available to US
  customers.
- Maximum total submitted notional: `3.10` USDC.
- Maximum total executed notional: `1.00` USDC.
- Retain inventory unless a phase explicitly says otherwise.
- Reconciliation gate must pass before the phase can be considered complete.
- Final summary must state product, submitted notional, executed notional,
  retained inventory, and reconciliation result.
- Frontend release, deployment, artifact, and smoke gates remain no-live and
  must report `$0` notional.

## Stop Conditions

Stop advancement to the next phase until fixed when any of these occur:

- `pytest tests\regression\ -v --tb=short` fails after backend changes.
- Frontend `npm run release:gate` fails after frontend release/BFF/API work.
- A blind/contextless review finds a blocking ambiguity or unsafe path.
- A security review finds browser-trusted authority, secret exposure, or live
  command bypass risk.
- Live Coinbase reconciliation fails, live notional exceeds the cap, or exact
  product/notional evidence is missing.
- The worktree contains unrelated changes that affect the files in scope.
- A requested change would create a parallel implementation for existing
  behavior.

## Approved Phases 541-560

### Phase 541 - Advance Active Queue Range

- Move the durable autonomous queue from completed phases 521-540 to active
  phases 541-560 while preserving the same live cap and stop-condition policy.

### Phase 542 - Runtime Evidence Contract

- Define a machine-readable frontend runtime/UI evidence artifact contract for
  admin shell readiness, route coverage, OIDC readiness, and visual smoke
  targets.

### Phase 543 - Runtime Evidence Artifact Builder

- Add shared artifact builder code so TypeScript and Node release tooling use
  one runtime evidence shape.

### Phase 544 - Runtime Evidence Writer

- Add a no-live frontend script that writes `artifacts/runtime-evidence.json`.

### Phase 545 - Runtime Evidence Check

- Add release/deployment checks that fail when runtime evidence scripts,
  artifact paths, UI surfaces, or no-live posture drift.

### Phase 546 - CI Artifact Upload

- Include runtime evidence generation and upload in frontend CI.

### Phase 547 - Release Gate Inclusion

- Include runtime evidence generation in `npm run release:gate`.

### Phase 548 - Visual Target Documentation

- Record the UI surfaces proven by Playwright visual smoke without storing
  browser screenshots in source control.

### Phase 549 - Documentation Sync

- Update testing, API, deployment, and roadmap docs for runtime evidence.

### Phase 550 - Unit Coverage

- Cover runtime evidence artifact building and required artifact paths in unit
  tests.

### Phase 551 - Contextless Runtime Evidence Review

- Run a blind/contextless review asking whether saved runtime/UI evidence is
  discoverable without chat history.

### Phase 552 - Contextless Remediation

- Fix unclear runtime evidence docs, scripts, or gates found by the review.

### Phase 553 - Frontend Focused Verification

- Run focused frontend quality/runtime evidence tests and checks.

### Phase 554 - Backend Queue Validation

- Run backend autonomous queue validation and focused regression coverage for
  changed backend files.

### Phase 555 - Frontend Release Gate

- Run full `npm run release:gate`.

### Phase 556 - Backend Regression Gate

- Run full backend regression after backend changes.

### Phase 557 - No-Live Evidence Discipline

- Confirm runtime evidence and release artifacts report no live Coinbase
  execution with `$0` notional.

### Phase 558 - Cross-Repo Clean Tree Check

- Verify both repositories are clean before final summary or next batch.

### Phase 559 - Commit Backend And Frontend

- Commit completed backend and frontend work separately.

### Phase 560 - Final Batch Summary

- Summarize implementation, verification, live posture, commits, and next
  approved phase range.

## Required Final Gates

Backend changes:

```powershell
pytest tests\regression\ -v --tb=short
```

Bash equivalent when running from a Linux shell:

```bash
python3 -m pytest tests/regression/ -v
```

Frontend release/BFF/API/deployment changes:

```powershell
npm run release:gate
```

Autonomous queue validation:

```powershell
python tools\run_autonomous_work_queue_check.py --summary-only
```
