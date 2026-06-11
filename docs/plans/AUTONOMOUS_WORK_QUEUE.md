# Autonomous Work Queue

This document records durable approval for unattended work on this project.
It exists so a contextless maintainer or agent can continue approved work
without relying on chat history.

## Active Approval

- Approved phase range: **641-660**.
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

## Approved Phases 641-660

### Phase 641 - Advance Active Queue Range

- Move the durable autonomous queue from completed phases 621-640 to active
  phases 641-660 while preserving the same live cap and stop-condition policy.

### Phase 642 - M6 Command Draft Inventory Closure

- Update M6 milestone evidence so stealth cancel and movement reprice drafts
  are both documented as live-disabled command contracts.

### Phase 643 - Command Draft Capability Matrix Sync

- Sync the command-capability matrix across manual order, cancel, stealth
  cancel, movement reprice, and campaign execution drafts.

### Phase 644 - Command Workflow Evidence Matrix

- Add or refine frontend/backend evidence that shows each command draft's
  route, identity key, live-disabled posture, and audit/idempotency contract.

### Phase 645 - Dry Submit Consistency

- Ensure frontend dry-submit and backend command responses surface live
  evidence, correlation/audit ids, and fail-closed status consistently.

### Phase 646 - BFF Command Boundary Hardening

- Validate that command routes cannot be broadened accidentally through BFF
  or undocumented backend paths.

### Phase 647 - Command Fetch Guard Hardening

- Strengthen static command-fetch guard expectations around canonical
  frontend/backend command wrappers.

### Phase 648 - Operator Intent Audit Evidence

- Verify command drafts and docs preserve operator intent, idempotency, and
  audit evidence without using exchange ids as application identity.

### Phase 649 - M6 Contextless Command Review

- Run a blind/contextless review focused on command draft discoverability,
  backend authority, BFF boundaries, and no-live posture.

### Phase 650 - M6 Review Remediation

- Fix any blocker or unclear command-draft path found by the M6 review before
  advancing into production-auth work.

### Phase 651 - M7 Auth Boundary Inventory

- Inventory frontend, BFF, and backend auth boundaries for production OIDC,
  CSRF, CORS, session, role, and server-only secret handling.

### Phase 652 - Server Secret Exposure Tests

- Add or refine tests that prove Admin API bearer tokens, actor headers,
  roles, and CSRF authority stay server-side in BFF mode.

### Phase 653 - OIDC Readiness Operator UX

- Improve operator-facing OIDC/JWT readiness evidence without simulating
  browser-trusted production auth.

### Phase 654 - CSRF And CORS Deployment Evidence

- Strengthen deployment docs/artifacts for CSRF and CORS posture while keeping
  unsafe methods fail-closed.

### Phase 655 - Release Artifact Operations Evidence

- Expand release/deployment/runtime artifacts with auth, observability,
  command, and no-live evidence needed by enterprise operators.

### Phase 656 - Observability Correlation UX

- Improve request/correlation/audit evidence in diagnostics and command
  outputs without adding frontend data authority.

### Phase 657 - Human Operator Runbook Auth Path

- Update human operator runbooks for production auth/deployment setup,
  failure modes, and no-live verification.

### Phase 658 - Focused Verification

- Run focused frontend/backend checks for command drafts, BFF/auth
  boundaries, diagnostics, docs, and Playwright production-start smoke.

### Phase 659 - Backend Queue, Regression, And No-Live Evidence

- Run backend autonomous queue validation and full backend regression after
  backend queue/doc/checker changes, then confirm release and regression
  evidence ran no live Coinbase execution with notional `$0`.

### Phase 660 - Commit And Final Batch Summary

- Commit completed backend and frontend work separately, then summarize
  implementation, verification, live posture, commits, and next approved phase
  range.

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
