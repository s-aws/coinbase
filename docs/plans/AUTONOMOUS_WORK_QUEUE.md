# Autonomous Work Queue

This document records durable approval for unattended work on this project.
It exists so a contextless maintainer or agent can continue approved work
without relying on chat history.

## Active Approval

- Approved phase range: **521-540**.
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

## Approved Phases 521-540

### Phase 521 - Advance Active Queue Range

- Move the durable autonomous queue from completed phases 501-520 to active
  phases 521-540 while preserving the same live cap and stop-condition policy.

### Phase 522 - Backend Route Coverage Sentinel

- Add or extend backend regression evidence proving the OpenAPI schema,
  route inventory, and route docs include every current Admin API route.

### Phase 523 - OIDC Readiness Frontend Contract Sync

- Ensure frontend route lists include `GET /api/v1/admin/oidc-readiness`.

### Phase 524 - Typed OIDC Readiness Wrapper

- Add a canonical frontend `BackendApiClient` wrapper for the OIDC readiness
  route instead of relying on ad hoc smoke-script access.

### Phase 525 - Frontend Route Coverage Check

- Add a no-live frontend check that fails when generated OpenAPI paths are
  missing from frontend contract paths or typed wrappers.

### Phase 526 - API Check Gate Inclusion

- Include the route coverage check in `npm run api:check` and release/CI
  gates without introducing a parallel API-client path.

### Phase 527 - Mock Fixture Parity

- Add OIDC readiness mock fixture coverage so local frontend mode mirrors the
  backend read contract.

### Phase 528 - Runtime Snapshot Parity

- Include OIDC readiness in the shared admin runtime read snapshot where it
  belongs with bootstrap, health, session, capabilities, and CSRF evidence.

### Phase 529 - UI Evidence Surface

- Surface OIDC readiness status in the admin shell as backend evidence only;
  do not create frontend authorization authority.

### Phase 530 - Documentation Sync

- Update frontend API docs, backend examples if needed, and documentation
  indexes so contextless maintainers can find the route-coverage gate.

### Phase 531 - Contextless Route Sync Review

- Run a blind/contextless review asking whether a smaller agent can create or
  inspect a spot/admin route without missing generated-contract sync.

### Phase 532 - Contextless Remediation

- Fix any unclear route-sync docs, scripts, or wrappers found by the review.

### Phase 533 - Backend Focused Verification

- Run focused Admin API contract tests and queue validation after backend
  changes.

### Phase 534 - Frontend Focused Verification

- Run focused frontend API-client, mock, runtime, and route-coverage tests.

### Phase 535 - Frontend Release Gate

- Run full `npm run release:gate` after frontend release/API changes.

### Phase 536 - Backend Regression Gate

- Run full backend regression after backend changes.

### Phase 537 - No-Live Evidence Discipline

- Confirm all frontend release, artifact, smoke, and route-coverage checks
  report no live Coinbase execution with `$0` notional.

### Phase 538 - Cross-Repo Clean Tree Check

- Verify both repositories are clean before final summary or next batch.

### Phase 539 - Commit Backend And Frontend

- Commit completed backend and frontend work separately.

### Phase 540 - Final Batch Summary

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
