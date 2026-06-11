# Autonomous Work Queue

This document records durable approval for unattended work on this project.
It exists so a contextless maintainer or agent can continue approved work
without relying on chat history.

## Active Approval

- Approved phase range: **621-640**.
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

## Approved Phases 621-640

### Phase 621 - Advance Active Queue Range

- Move the durable autonomous queue from completed phases 601-620 to active
  phases 621-640 while preserving the same live cap and stop-condition policy.

### Phase 622 - Read Model Interaction Contract

- Define the no-live interaction contract for order, campaign, audit,
  settings, and diagnostics read models.

### Phase 623 - Orders Filter State Model

- Add typed order read-model filter/sort state without adding frontend trading
  calculations.

### Phase 624 - Orders Detail Selection UX

- Let operators select fixture/backend order rows and inspect detail evidence
  keyed by `client_order_id`.

### Phase 625 - Client Order Id Deep Link

- Add a durable `client_order_id` search/deep-link path for the orders section
  without introducing exchange `order_id` identity.

### Phase 626 - Campaign Read Model Tabs

- Organize campaign status, sweep, P/L, recovery, and disabled execution
  evidence into accessible read-only views.

### Phase 627 - Campaign Evidence Filters

- Add local filter/search affordances for campaign evidence while keeping
  backend data authoritative.

### Phase 628 - Spot Operations Density

- Improve spot operations KPI density and scanability without changing backend
  contracts.

### Phase 629 - Empty Loading Error States

- Standardize empty, loading, auth-blocked, and backend-error states across
  read models.

### Phase 630 - Audit Evidence Cross Links

- Cross-link read-model rows to audit evidence by `client_order_id`,
  correlation id, and audit id where backend evidence exists.

### Phase 631 - Settings Diagnostics Drilldown

- Add diagnostics drilldown rows for runtime mode, API routes, BFF mode,
  OIDC readiness, and release evidence.

### Phase 632 - Responsive Tables And Overflow

- Make order/campaign/audit tables usable on desktop and mobile without
  horizontal page overflow.

### Phase 633 - Accessibility Keyboard Coverage

- Add/update keyboard, focus, region, and form-label coverage for read-model
  interactions.

### Phase 634 - Documentation Sync

- Update admin frontend, read-model, testing, runbook, and examples docs for
  the interaction batch.

### Phase 635 - Contextless Read Model Review

- Run a blind/contextless review asking whether a maintainer can understand
  order/campaign/audit read-model interactions without frontend trading
  behavior.

### Phase 636 - Contextless Remediation

- Fix unclear read-model interactions, docs, tests, or no-live evidence found
  by the review.

### Phase 637 - Frontend Focused Verification

- Run focused read-model, admin-shell, accessibility, docs/sentinel, and
  Playwright checks.

### Phase 638 - Frontend Release Gate

- Run full `npm run release:gate`.

### Phase 639 - Backend Queue, Regression, And No-Live Evidence

- Run backend autonomous queue validation and full backend regression after
  backend queue/doc/checker changes, then confirm release and regression
  evidence ran no live Coinbase execution with notional `$0`.

### Phase 640 - Commit And Final Batch Summary

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
