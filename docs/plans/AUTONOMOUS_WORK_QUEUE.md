# Autonomous Work Queue

This document records durable approval for unattended work on this project.
It exists so a contextless maintainer or agent can continue approved work
without relying on chat history.

## Active Approval

- Approved phase range: **501-520**.
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

## Approved Phases 501-520

### Phase 501 - Autonomous Work Queue Contract

- Persist the unattended-work approval, live caps, stop conditions, and final
  gate policy in backend and frontend docs.

### Phase 502 - Machine-Readable Queue Validation

- Add a no-live validator that checks phase coverage, live caps, stop
  conditions, and required gate commands.

### Phase 503 - Frontend Queue Gate

- Add a frontend release/deployment check for the same autonomous queue
  contract.

### Phase 504 - CI Queue Parity

- Make CI/local release checks fail when the autonomous queue contract is
  missing or stale.

### Phase 505 - Long-Run Progress Format

- Define a concise progress format for unattended execution: current phase,
  gate status, live execution status, blockers, and next phase.

### Phase 506 - Live Cap Audit Proof

- Ensure live cap policy is visible beside live smoke docs and cannot be
  confused with frontend live enablement.

### Phase 507 - Backend Queue Validator Tests

- Cover the backend queue validator in regression tests.

### Phase 508 - Frontend Queue Validator Tests

- Cover the frontend queue contract in unit tests.

### Phase 509 - Contextless Review Prompt

- Run a blind/contextless review asking whether a smaller agent can continue
  phases 501-520 safely from repository docs alone.

### Phase 510 - Contextless Remediation

- Fix any unclear docs, scripts, or gates found by the review.

### Phase 511 - Release Gate Inclusion

- Include autonomous queue validation in frontend release and deployment
  gates.

### Phase 512 - Backend Regression Gate

- Run focused backend checks and full backend regression after backend file
  changes.

### Phase 513 - Frontend Release Gate

- Run focused frontend checks and full `npm run release:gate` after frontend
  file changes.

### Phase 514 - Cross-Repo Clean Tree Check

- Verify both repositories are clean before final summary or next batch.

### Phase 515 - Public Documentation Index Sync

- Link the queue contract from ordered documentation indexes.

### Phase 516 - Flight-Safe Batch Extension

- Prepare the next 20-phase candidate batch only after blockers from this
  batch are resolved.

### Phase 517 - Live Execution Summary Discipline

- If live execution occurs, record exact product/notional evidence in the
  final summary and relevant roadmap.

### Phase 518 - No-Live Frontend Evidence

- Reconfirm frontend release artifacts and smokes report no live Coinbase
  execution with `$0` notional.

### Phase 519 - Commit Backend And Frontend

- Commit completed backend and frontend work separately.

### Phase 520 - Final Batch Summary

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
