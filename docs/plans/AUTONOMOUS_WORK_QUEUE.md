# Autonomous Work Queue

This document records durable approval for unattended work on this project.
It exists so a contextless maintainer or agent can continue approved work
without relying on chat history.

## Active Approval

- Approved phase range: **581-600**.
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

## Approved Phases 581-600

### Phase 581 - Advance Active Queue Range

- Move the durable autonomous queue from completed phases 561-580 to active
  phases 581-600 while preserving the same live cap and stop-condition policy.

### Phase 582 - Command Draft Model

- Add a typed frontend command draft model for manual order, cancel by
  `client_order_id`, and spot campaign execution without adding trading logic.

### Phase 583 - Manual Order Draft UX

- Render operator intent, product, side, order type, notional/size, post-only,
  and acknowledgement fields for manual order drafts while keeping submit
  disabled unless backend evidence later enables it.

### Phase 584 - Cancel Draft UX

- Render cancel-by-`client_order_id` draft fields with no exchange `order_id`
  cancellation path.

### Phase 585 - Campaign Execution Draft UX

- Render campaign execution draft fields for schedule/scope/caps as
  backend-owned intent evidence only.

### Phase 586 - Draft Validation

- Add frontend-only validation for required draft evidence and unsafe missing
  acknowledgement states without deciding wallet, guard, or trading authority.

### Phase 587 - Idempotency And Correlation Preview

- Generate deterministic request id, idempotency key, and operator-intent
  preview evidence from the draft state.

### Phase 588 - Dry-Submit Payload Mapping

- Map validated drafts to the existing canonical dry-submit helpers and
  generated backend request shapes without feature-local fetch calls.

### Phase 589 - Per-Workflow Evidence Panels

- Render per-workflow backend decision, validation, idempotency, audit, and
  live-disabled evidence instead of relying only on one shared preview panel.

### Phase 590 - Disabled Submit Semantics

- Keep command submit controls disabled in mock/local and incomplete-auth
  backend modes, with visible backend-owned enablement requirements.

### Phase 591 - Backend And BFF Consistency

- Verify direct backend and BFF modes use the same command draft mapping,
  headers, dry-submit helpers, and no-live evidence.

### Phase 592 - Command Documentation Sync

- Update command workflow, spot order flow, runbook, and example docs for the
  draft UX and disabled dry-submit evidence.

### Phase 593 - Browser And Accessibility Coverage

- Add or update unit and Playwright coverage for command draft fields,
  disabled buttons, mobile layout, and no exchange-id cancel input.

### Phase 594 - Contextless Command UX Review

- Run a blind/contextless review asking how to draft a spot order/cancel/campaign
  command without inventing frontend trading behavior.

### Phase 595 - Contextless Remediation

- Fix unclear command UX docs, code organization, tests, or evidence found by
  the review.

### Phase 596 - Frontend Focused Verification

- Run focused command workflow tests, command dry-submit tests, security guard,
  and browser tests.

### Phase 597 - Frontend Release Gate

- Run full `npm run release:gate`.

### Phase 598 - Backend Queue And Regression Gate

- Run backend autonomous queue validation and full backend regression after
  backend queue/doc/checker changes.

### Phase 599 - No-Live Evidence Discipline

- Confirm command UX, dry-submit, release, and regression evidence ran no live
  Coinbase execution with notional `$0`.

### Phase 600 - Commit And Final Batch Summary

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
