# Autonomous Work Queue

This document records durable approval for unattended work on this project.
It exists so a contextless maintainer or agent can continue approved work
without relying on chat history.

## Active Approval

- Approved phase range: **601-620**.
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

## Approved Phases 601-620

### Phase 601 - Advance Active Queue Range

- Move the durable autonomous queue from completed phases 581-600 to active
  phases 601-620 while preserving the same live cap and stop-condition policy.

### Phase 602 - Navigation Anchor Contract

- Replace inert admin navigation links with stable in-page anchors for the
  existing frontend sections.

### Phase 603 - Section Landmark Structure

- Add accessible section landmarks/headings for overview, spot operations,
  orders, campaigns, audit, settings, and admin evidence.

### Phase 604 - Active Navigation Semantics

- Keep a clear current-section hint without creating client-only routing or a
  second navigation implementation.

### Phase 605 - Overview Section Polish

- Group environment, runtime, session, and status evidence under the overview
  section.

### Phase 606 - Spot Operations Anchor

- Make spot readiness/sweep/P&L/cost-basis/campaign status evidence reachable
  from the Spot Operations nav link.

### Phase 607 - Orders Anchor

- Make order list/detail read models reachable from the Orders nav link while
  preserving `client_order_id` identity.

### Phase 608 - Campaigns Anchor

- Make campaign read models and disabled campaign draft evidence reachable from
  the Campaigns nav link.

### Phase 609 - Audit Anchor

- Keep audit trail and direct-order audit anchors reachable without exchange id
  navigation.

### Phase 610 - Settings And Admin Evidence

- Add settings/admin evidence sections for runtime mode, diagnostics, session,
  RBAC, OIDC readiness, and release posture.

### Phase 611 - Responsive Navigation Coverage

- Ensure the anchored navigation works on desktop and mobile without overflow.

### Phase 612 - Accessibility Coverage

- Add/update tests for unique ids, section landmarks, nav hrefs, and disabled
  live controls.

### Phase 613 - Documentation Sync

- Update admin frontend, testing, operator runbook, and examples for navigable
  admin shell sections.

### Phase 614 - Contextless Navigation Review

- Run a blind/contextless review asking whether a maintainer can navigate the
  frontend sections without chat history or frontend trading behavior.

### Phase 615 - Contextless Remediation

- Fix unclear navigation, section, docs, tests, or no-live evidence found by
  the review.

### Phase 616 - Frontend Focused Verification

- Run focused admin-shell, accessibility, operator read-model, docs/sentinel,
  and Playwright checks.

### Phase 617 - Frontend Release Gate

- Run full `npm run release:gate`.

### Phase 618 - Backend Queue And Regression Gate

- Run backend autonomous queue validation and full backend regression after
  backend queue/doc/checker changes.

### Phase 619 - No-Live Evidence Discipline

- Confirm navigation, release, and regression evidence ran no live Coinbase
  execution with notional `$0`.

### Phase 620 - Commit And Final Batch Summary

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
