# Autonomous Work Queue

This document records durable approval for unattended work on this project.
It exists so a contextless maintainer or agent can continue approved work
without relying on chat history.

## Active Approval

- Approved phase range: **561-580**.
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

## Approved Phases 561-580

### Phase 561 - Advance Active Queue Range

- Move the durable autonomous queue from completed phases 541-560 to active
  phases 561-580 while preserving the same live cap and stop-condition policy.

### Phase 562 - V1 Release Candidate Gate Parity

- Align the frontend V1 release-candidate document with the current canonical
  release gate, runtime evidence, autonomous queue, and dry-smoke commands.

### Phase 563 - Runtime Evidence Release Candidate Docs

- Ensure the V1 release candidate explains `artifacts/runtime-evidence.json`
  and its no-live `$0` posture.

### Phase 564 - Production Readiness Runtime Evidence

- Update production-readiness docs so runtime evidence and autonomous queue
  checks are part of the release evidence set.

### Phase 565 - Public Checklist Documentation Parity

- Confirm public release checklist docs agree with current artifacts and
  conditional OIDC/JWT production posture.

### Phase 566 - Release Readiness Doc Sentinel

- Add no-live release-readiness checks that fail when V1 release-candidate docs
  omit required scripts, artifacts, runtime evidence, or autonomous queue
  posture.

### Phase 567 - Deployment Readiness Doc Sentinel

- Add deployment-readiness checks that fail when production-readiness docs omit
  runtime evidence, public checklist, OIDC readiness, or no-live posture.

### Phase 568 - Unit Coverage

- Extend focused unit coverage for the release-candidate artifact and queue
  parity expectations.

### Phase 569 - CI Artifact Parity

- Confirm CI still runs and uploads every release artifact after smoke/browser
  gates.

### Phase 570 - Ordered Documentation Sync

- Keep ordered docs and README surfaces pointing at the current release
  candidate, production readiness, and runtime evidence docs.

### Phase 571 - Contextless Release Candidate Review

- Run a blind/contextless review asking whether the release candidate can be
  understood without chat history and without inventing frontend trading
  behavior.

### Phase 572 - Contextless Remediation

- Fix unclear release-candidate docs, scripts, checks, or artifact references
  found by the review.

### Phase 573 - Frontend Focused Verification

- Run focused frontend release/deployment/doc parity checks and tests.

### Phase 574 - Backend Queue Validation

- Run backend autonomous queue validation and focused regression coverage for
  changed backend files.

### Phase 575 - Frontend Release Gate

- Run full `npm run release:gate`.

### Phase 576 - Backend Regression Gate

- Run full backend regression after backend changes.

### Phase 577 - No-Live Evidence Discipline

- Confirm release-candidate parity, runtime evidence, and release artifacts
  report no live Coinbase execution with `$0` notional.

### Phase 578 - Cross-Repo Clean Tree Check

- Verify both repositories are clean before final summary or next batch.

### Phase 579 - Commit Backend And Frontend

- Commit completed backend and frontend work separately.

### Phase 580 - Final Batch Summary

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
