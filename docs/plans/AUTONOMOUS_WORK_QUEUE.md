# Autonomous Work Queue

This document records durable approval for unattended work on this project.
It exists so a contextless maintainer or agent can continue approved work
without relying on chat history.

## Active Approval

- Approved phase range: **721-740**.
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

## Completed Phases 641-660

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

## Completion Evidence - Phases 641-660

- Phase range 641-660 completed the M6 non-spot command draft contracts and
  M7 production auth/operations hardening evidence.
- Backend command contracts remain live-disabled for stealth cancel and
  movement reprice; both route through the shared Admin API command service,
  auth/RBAC, idempotency, audit, and approval gates.
- Frontend BFF mutation forwarding now rejects missing mutation evidence
  headers and rejects OIDC/JWT cookie-backed unsafe requests without
  same-origin browser evidence before forwarding.
- Command fetch guard hardening passed and continues to require canonical
  frontend wrappers for command routes.
- Blind/contextless review found M6 documentation ambiguity and an M7
  OIDC/CSRF browser-boundary blocker; both were remediated and follow-up
  review found no remaining blockers.
- Backend focused Admin API contract tests passed with `54 passed,
  1 warning`.
- Backend full regression passed with `789 passed, 1 warning`.
- Backend autonomous queue validation passed with status `passed`.
- Frontend focused command/auth contract tests passed with `72 passed`.
- Frontend `npm run security:commands` passed.
- Frontend `npm run release:gate` passed with `177` unit tests and `3`
  Playwright tests.
- Live Coinbase execution was not run; submitted notional `$0`, executed
  notional `$0`.

## Completed Phases 661-680

### Phase 661 - Advance Active Queue Range

- Move the durable autonomous queue from completed phases 641-660 to active
  phases 661-680 while preserving the same live cap and stop-condition policy.

### Phase 662 - M8 Live Path Inventory

- Define the backend-owned list of command paths that could ever become live
  through controlled M8 enablement, with every path still live-disabled by
  default.

### Phase 663 - Live Enablement Read Contract

- Add a read-only Admin API contract that exposes live path eligibility,
  cap posture, approval requirements, guard requirements, audit requirements,
  reconciliation requirements, and no-live evidence.

### Phase 664 - Backend Route Inventory Sync

- Sync route inventory, capabilities, OpenAPI, fixtures, and examples with
  the live-enablement readiness contract.

### Phase 665 - Backend No-Live Regression

- Add regression coverage proving the live-enablement route is read-only,
  reports submitted/executed notional `$0`, and does not enable any command
  path.

### Phase 666 - Frontend Schema And BFF Sync

- Regenerate the frontend schema, add canonical client/BFF read coverage, and
  keep the route out of mutation allowlists.

### Phase 667 - Frontend Live Evidence Surface

- Display live-enablement readiness as operator evidence only, including cap,
  eligible paths, required gates, and no-live posture.

### Phase 668 - Runtime And Mock Evidence

- Add runtime snapshot and mock-backend support so local, BFF, and backend
  modes all expose the same no-live M8 evidence shape.

### Phase 669 - Release Artifact Live Posture

- Extend release/runtime/deployment artifacts so M8 evidence appears in
  release proof without approving frontend live execution.

### Phase 670 - Human Operator M8 Runbook

- Document how operators should read M8 live-enablement evidence and why it is
  not live approval.

### Phase 671 - Capability Matrix M8 Sync

- Update backend/frontend capability matrices so controlled live enablement is
  a platform primitive, not a spot-only concept.

### Phase 672 - Reconciliation Gate Detail

- Document the per-path reconciliation evidence that must exist before any
  future live enablement can be marked complete.

### Phase 673 - Live Cap Drift Checks

- Add static/read-only checks that fail if approved cap values drift between
  queue docs, backend readiness, frontend artifacts, and tests.

### Phase 674 - Contextless M8 Review

- Run blind/contextless review focused on whether a fresh agent can explain
  the M8 path, no-live posture, cap policy, and reconciliation requirement.

### Phase 675 - Review Remediation

- Resolve any blocker from contextless M8 review before advancing to release
  candidate work.

### Phase 676 - Focused Backend Verification

- Run focused backend Admin API contract tests and queue validation for the
  M8 readiness surface.

### Phase 677 - Focused Frontend Verification

- Run focused frontend API, runtime, BFF, artifact, and UI tests for the M8
  readiness surface.

### Phase 678 - Full Release Gates

- Run full backend regression and frontend release gate after the M8 no-live
  readiness surface is complete.

### Phase 679 - Milestone Evidence

- Mark M8 readiness prep complete only if gates and reviews pass, while
  keeping actual controlled live enablement pending until a live phase is
  explicitly approved.

### Phase 680 - Commit And Final Batch Summary

- Commit backend and frontend work separately, then summarize implementation,
  verification, live posture, commits, and the next approved phase range.

## Completion Evidence - Phases 661-680

- Phase range 661-680 completed M8 live-enablement readiness prep while
  keeping controlled live execution pending.
- Backend `GET /api/v1/admin/live-enablement` now exposes read-only M8
  readiness, cap, approval, guard, audit, per-path, and reconciliation
  evidence.
- Live-place and live-cancel Admin API paths remain `live_enabled=false`,
  `live_eligible=false`, and `status=live_disabled`.
- Dynamic evidence maps use an open-object schema while preserving plain dict
  runtime behavior.
- Backend examples now show `paths`, `checks`, `read_only`,
  `reconciliation_required`, and `live_eligible_path_count`.
- Blind/contextless M8 review found no blockers. It found two clarity gaps;
  both were remediated before completion.
- Backend autonomous queue validation passed with approved phase range
  `661-680`.
- Backend focused Admin API contract checks passed with `62 passed,
  1 warning`.
- Backend full regression passed with `789 passed, 1 warning`.
- Frontend `npm run release:gate` passed with `177` unit tests and `3`
  Playwright tests.
- Live Coinbase execution was not run; submitted notional `$0`, executed
  notional `$0`.

## Completed Phases 681-700

### Phase 681 - Advance Active Queue Range

- Move the durable autonomous queue from completed phases 661-680 to active
  phases 681-700 while preserving the same live cap and stop-condition policy.

### Phase 682 - M9 Enterprise Module Contract

- Add a backend-owned read contract that reports enterprise admin module
  support status, unsupported actions, identity keys, constraints, and
  verification evidence.

### Phase 683 - M9 Security Posture Evidence

- Include browser-authority, server-secret, command-bypass, and no-live
  security checks in the backend readiness contract.

### Phase 684 - M9 Release Gate Evidence

- Record backend regression, frontend release gate, and contextless review as
  external release checks that must be run outside the browser.

### Phase 685 - Backend Route Inventory Sync

- Sync route inventory, OpenAPI, fixtures, capability metadata, examples, and
  docs with `GET /api/v1/admin/enterprise-readiness`.

### Phase 686 - Backend Regression Coverage

- Add Admin API regression coverage proving the M9 route is read-only,
  no-live, backend-owned, and explicit about unsupported modules/actions.

### Phase 687 - Frontend Schema And BFF Sync

- Regenerate frontend schema and add canonical client, BFF, route-coverage,
  runtime, and mock support for the enterprise-readiness route.

### Phase 688 - Frontend Enterprise Evidence Surface

- Surface M9 module support, unsupported actions, release checks, and security
  checks as operator evidence without adding trading authority.

### Phase 689 - Release Artifact Enterprise Posture

- Extend release/runtime/deployment artifacts and validators so supported and
  unsupported module posture is captured in release evidence.

### Phase 690 - Documentation And Runbook Sync

- Update admin API/frontend docs, examples, capability matrices, and runbooks
  so contextless readers can understand the M9 enterprise boundary.

### Phase 691 - Module Onboarding Contract

- Add contextless onboarding guidance for future modules that requires
  backend-owned contracts, capability-matrix updates, tests, and review logs.

### Phase 692 - Unsupported Action Drift Check

- Add checks that fail if release docs or frontend artifacts omit unsupported
  actions for legacy dashboard, live commands, or module-specific gaps.

### Phase 693 - Security Review Pass

- Run a security-focused review for browser authority, secret exposure, BFF
  forwarding, command bypass, and live execution posture.

### Phase 694 - Contextless M9 Review

- Run blind/contextless reviews focused on enterprise-readiness discoverability
  and whether a fresh agent can explain supported and unsupported modules.

### Phase 695 - Review Remediation

- Resolve any blocker or ambiguity from security/contextless review before
  advancing to release gates.

### Phase 696 - Focused Backend Verification

- Run focused backend Admin API contract, route inventory, and autonomous
  queue checks for the M9 readiness surface.

### Phase 697 - Focused Frontend Verification

- Run focused frontend API, runtime, BFF, artifact, and UI tests for the M9
  readiness surface.

### Phase 698 - Full Release Gates

- Run full backend regression and frontend release gate after the M9 no-live
  readiness surface is complete.

### Phase 699 - Milestone Evidence

- Mark M9 readiness evidence complete only if gates and reviews pass, while
  keeping the broader enterprise admin objective open until handoff is proven.

### Phase 700 - Commit And Final Batch Summary

- Commit backend and frontend work separately, then summarize implementation,
  verification, live posture, commits, and the next approved phase range.

## Completion Evidence - Phases 681-700

- Phase range 681-700 completed M9 enterprise-readiness prep while keeping
  live Coinbase execution disabled by default.
- Backend `GET /api/v1/admin/enterprise-readiness` exposes read-only evidence
  for supported modules, unsupported actions, identity keys, constraints,
  security checks, release checks, frontend authority, live posture, and
  no-live notional.
- The readiness evidence scopes browser authority to the enterprise admin
  frontend/Admin HTTP path and references `docs/LIVE_ORDER_SURFACES.md` for
  compatibility-only legacy live browser surfaces.
- Frontend operational diagnostics display module status, unsupported
  actions, identity keys, security checks, and release checks from the
  backend-owned readiness payload.
- Blind/contextless M9 review found two blockers; both were remediated and
  follow-up review found no remaining blockers.
- Backend focused Admin API contract coverage passed.
- Backend full regression passed with `789 passed, 1 warning`.
- Frontend `npm run release:gate` passed with `177` unit tests and `3`
  Playwright tests.
- Live Coinbase execution was not run; submitted notional `$0`, executed
  notional `$0`.

## Completed Phases 701-720

### Phase 701 - Advance Active Queue Range

- Move the durable autonomous queue from completed phases 681-700 to active
  phases 701-720 while preserving the same live cap and stop-condition policy.

### Phase 702 - M9 Completion Evidence

- Preserve M9 completion evidence in roadmap, review log, and release notes so
  future agents know enterprise readiness was reviewed and remediated.

### Phase 703 - Ordered Documentation Index

- Verify the root README and `docs/README.md` route maintainers to the current
  backend handoff, route inventory, capability matrix, examples, and review
  logs.

### Phase 704 - Maintainer Handoff Guide

- Add or refine backend maintainer handoff guidance for contextless agents,
  including authority boundaries, live-surface rules, and required gates.

### Phase 705 - Module Onboarding Playbook

- Document the sequence for adding an admin module without creating parallel
  behavior or importing spot-only rules into non-spot domains.

### Phase 706 - Authority Boundary Handoff

- Ensure handoff docs state that backend services own trading behavior,
  Coinbase credentials, guard checks, audit persistence, and live authority.

### Phase 707 - Live Surface Handoff

- Keep `docs/LIVE_ORDER_SURFACES.md` linked from handoff material and make the
  compatibility-only dashboard status explicit.

### Phase 708 - Route Inventory Handoff

- Validate that handoff docs point maintainers to route inventory before any
  Admin API route change.

### Phase 709 - Generated Contract Handoff

- Document the OpenAPI/frontend generation flow and the rule against hand
  editing generated API clients.

### Phase 710 - Handoff Validator Coverage

- Extend autonomous queue validation so missing handoff docs or missing index
  links block the batch.

### Phase 711 - Frontend Association Handoff

- Sync backend handoff language with the frontend association boundary and
  required frontend release gate.

### Phase 712 - Public Release Artifact Handoff

- Document which release artifacts are frontend-owned no-live evidence and
  which backend gates remain required.

### Phase 713 - Contextless Task Cards

- Add handoff guidance that lets a fresh agent add a small read-only module
  slice using only checked-in docs and tests.

### Phase 714 - Stale Roadmap Audit

- Search for current-state contradictions around M9/M10, active phase range,
  live posture, and frontend/backend authority.

### Phase 715 - Security Boundary Review

- Review handoff docs for browser authority, secret exposure, command bypass,
  and live execution ambiguity.

### Phase 716 - Contextless M10 Review

- Run a blind/contextless review focused on whether a fresh agent can explain
  how the backend and frontend fit together without chat history.

### Phase 717 - Review Remediation

- Resolve any blocker or ambiguity from M10 security/contextless review before
  advancing to release gates.

### Phase 718 - Focused Verification

- Run focused backend autonomous, docs, and Admin API contract checks plus
  focused frontend autonomous/quality checks for handoff evidence.

### Phase 719 - Full Release Gates

- Run full backend regression and frontend release gate after M10 handoff
  evidence is complete.

### Phase 720 - Commit And Final Batch Summary

- Commit backend and frontend work separately, then summarize implementation,
  verification, live posture, commits, and remaining objective scope.

## Completion Evidence - Phases 701-720

- Phase range 701-720 completed M10 public maintainer handoff evidence.
- Backend and frontend maintainer handoff guides are linked from root READMEs,
  ordered documentation indexes, and cross-repo association docs.
- Autonomous validators now fail when handoff docs or index links are missing.
- Contextless M10 review found the handoff material understandable after the
  new docs were staged and a duplicate stale frontend queue section was
  removed.
- Backend full regression passed with `789 passed, 1 warning`.
- Frontend `npm run release:gate` passed with `177` unit tests and `3`
  Playwright tests.
- Live Coinbase execution was not run; submitted notional `$0`, executed
  notional `$0`.

## Approved Phases 721-740

### Phase 721 - Advance Active Queue Range

- Move the durable autonomous queue from completed phases 701-720 to active
  phases 721-740 while preserving the same live cap and stop-condition policy.

### Phase 722 - M11 Operational Gates Slice

- Use the handoff playbook to onboard existing backend release,
  spot/direct-order recovery, and fill-ledger health reads as a narrow
  read-only admin module slice.

### Phase 723 - Backend Range Evidence

- Update backend no-live readiness evidence so live-enablement and
  enterprise-readiness report the active 721-740 phase range.

### Phase 724 - Backend Route Contract Recheck

- Re-verify release-gate, recovery-gate, and fill-ledger-health route
  inventory and Admin API contract coverage remain read-only and no-live.

### Phase 725 - Frontend Runtime Gate Snapshot

- Load release-gate, recovery-gate, and fill-ledger-health reads through the
  canonical runtime snapshot.

### Phase 726 - Frontend Gate Evidence UI

- Display operational gate status, checks, read-only posture, and no-live
  evidence in the existing operator/readiness surfaces.

### Phase 727 - Mock And BFF Gate Parity

- Keep mock fixtures, BFF allowlist, and route coverage aligned with the gate
  reads.

### Phase 728 - Quality Artifact Range Sync

- Update frontend release/deployment/autonomous artifacts and tests to the
  721-740 active range.

### Phase 729 - Handoff Proof Documentation

- Document that this batch is the first small read-only module slice completed
  by following the M10 handoff playbook.

### Phase 730 - Operator Docs Sync

- Update operator read-model, backend association, and admin examples so gate
  evidence is described as backend-owned and no-live.

### Phase 731 - Stale Range Audit

- Search for current-state contradictions around 701-720 versus 721-740 and
  around static versus backend-loaded gate evidence.

### Phase 732 - Focused Backend Verification

- Run focused Admin API contract and autonomous queue checks for the active
  range and gate-route posture.

### Phase 733 - Focused Frontend Verification

- Run focused runtime, mock, Admin shell, BFF, and quality tests for gate
  evidence consumption.

### Phase 734 - Contextless M11 Review

- Run a blind/contextless review asking whether the operational-gates slice
  proves the handoff playbook without chat history.

### Phase 735 - Review Remediation

- Resolve blocker or ambiguity from M11 review before full gates.

### Phase 736 - Full Backend Regression

- Run full backend regression after the M11 slice and roadmap updates.

### Phase 737 - Full Frontend Release Gate

- Run full frontend release gate after gate evidence is rendered.

### Phase 738 - Final Drift Check

- Run diff, generated-file, route-range, and live-notional checks.

### Phase 739 - Milestone Evidence

- Mark M11 operational-gates onboarding proof complete if gates and review pass.

### Phase 740 - Commit And Final Batch Summary

- Commit backend and frontend work separately, then summarize implementation,
  verification, live posture, commits, and next objective scope.

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
