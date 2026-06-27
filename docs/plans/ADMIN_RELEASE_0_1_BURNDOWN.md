# Admin Release 0.1 Burn-Down

This document is the release-control pivot for the enterprise admin platform.
It replaces evidence-only roadmap expansion as the active planning surface
until a private operator admin release candidate can manage the project without
falling back to `dashboard.py` for normal administration.

## Release Goal

Release 0.1 is a private operator MVP. It is not the public release.

The release is usable when an operator can open the admin frontend, inspect the
engine, run backend-supported commands through backend-owned contracts, see
unsupported behavior as explicit `unsupported` or `not_modeled` state, and use
audit/reconciliation evidence to understand what happened.

The governing question for every phase is:

> Does this make the frontend able to manage the project?

If the answer is no, the phase is not Release 0.1 work.

## Drift Stop Rule

No new evidence-only phase may be created unless it directly closes a named
Release 0.1 blocker below. Existing futures/perpetual proof evidence remains
historical context, but it is no longer the active roadmap driver.

Future agents must not add generic polish, recommendation-only phases, or more
proof-summary batches unless the work is tied to an operator workflow needed
for Release 0.1. A missing backend behavior must be surfaced as `unsupported`
or `not_modeled`; it must not be implemented in the browser, BFF, or route-local
FastAPI code.

## Release Blockers

P0 blockers must be cleared before Release 0.1 can be called a usable private
operator admin.

| Area | P0 Release Requirement | Current Rule |
| --- | --- | --- |
| Admin shell | Operator can see backend health, lifecycle state, and safe start/stop/pause/resume status where backend supports it. | No direct browser process authority unless backend-owned lifecycle contracts exist. |
| Account inventory | Products, accounts, balances, orders, fills, positions, and relevant funding/risk reads are visible from backend-owned contracts. | Missing or unsupported rows are explicit. |
| Spot commands | Spot buy, sell, and cancel workflows are usable through backend gates where already supported. | Spot no-shorting, wallet, cost-basis, and USDC rules stay spot-only. |
| Stealth commands | Create, cancel, reveal, move, reprice, recovery, and exchange-truth status are manageable where backend support exists. | No hide-again shortcut and no local stealth mutation without exchange cancel/move/reconcile proof. |
| Movement and repricing | Move, premark, reprice, cooldown, claim, cancel/replace, audit, and recovery workflows are manageable where backend support exists. | Existing mutation locks and replacement-slot rules remain authoritative. |
| Automation and campaigns | Operators can inspect scheduler/campaign state and use safe controls for supported runs, limits, pause/resume, and retry behavior. | No browser scheduler or unbounded loop authority. |
| Audit and reconciliation | Operators can correlate command attempts, approvals, cap/guard decisions, exchange intent, fills, and reconciliation status. | Audit/reconciliation authority stays backend-owned. |
| Settings and policy | Operators can inspect configuration and safely edit only backend-supported settings with audit and validation. | No secret exposure and no direct browser database repair. |
| Unsupported behavior | Every incomplete backend route or workflow appears as `unsupported` or `not_modeled` with a reason and next owning module. | Hidden gaps block release. |
| Validation | Focused tests pass per slice; full backend regression and frontend release gate run only at Release 0.1 closeout or another major gate. | Full regression is not an ordinary phase gate. |

## Non-Goals

- Public release readiness.
- More proof-summary expansion that does not unlock an operator workflow.
- Futures/perpetual live execution.
- Browser-owned trading authority or BFF execution authority.
- A second trading path beside the existing backend/domain/exchange path.
- Importing spot-only rules into stealth, futures/perpetuals, or movement
  modules.

## Active Phases 7981-8000

Batch label: Release 0.1 Operator Admin Pivot.

Active Release 0.1 `7981-8000` pivots the admin platform to product-managing
operator workflows while completed M57 `7961-7980` carries forward futures
risk-proof record validation remediation summary evidence.

Exact autonomous phrase: Active Release 0.1 `7981-8000` pivots the admin platform to product-managing operator workflows while completed M57 `7961-7980` carries forward futures risk-proof record validation remediation summary evidence.

### Phase 7981 - Close Proof Expansion

- Mark `7961-7980` complete and freeze further futures/perpetual proof-summary
  expansion unless a future proof field directly closes a Release 0.1 blocker.

### Phase 7982 - Release Blocker Inventory

- Inventory backend and frontend gaps against the Release 0.1 blocker table.

### Phase 7983 - Admin Shell Operability Map

- Map health, lifecycle, pause/resume, stop/drain, and operator status flows
  from backend route to frontend surface.

### Phase 7984 - Account And Market Coverage Map

- Map product, account, balance, order, fill, position, funding, and risk reads
  to the frontend surfaces that need them.

### Phase 7985 - Spot Command Usability Map

- Identify the smallest backend-owned spot buy/sell/cancel workflow needed for
  the private operator MVP.

### Phase 7986 - Stealth Command Usability Map

- Identify supported stealth create/cancel/reveal/move/reprice/recovery flows
  and unsupported gaps that must surface as `unsupported` or `not_modeled`.

### Phase 7987 - Movement/Repricing Usability Map

- Identify supported move, premark, reprice, cooldown, claim, cancel/replace,
  audit, and recovery flows.

### Phase 7988 - Automation And Campaign Usability Map

- Identify supported scheduler, campaign, retry, pause/resume, run-limit, and
  recovery flows.

### Phase 7989 - Audit, Reconciliation, And Settings Map

- Identify audit, reconciliation, settings, policy, and safe-edit paths needed
  before private operator release.

### Phase 7990 - Backend Route-To-UI Release Matrix

- Produce a route-to-frontend matrix that classifies each admin workflow as
  usable, blocked, `unsupported`, or `not_modeled`.

### Phase 7991 - Frontend Workflow Release Matrix

- Produce a navigation/workflow matrix that shows which operator tasks can be
  completed end to end in the frontend.

### Phase 7992 - Unsupported Gap Classification

- Ensure unsupported and not-modeled gaps are visible in both backend and
  frontend evidence instead of implied by missing UI.

### Phase 7993 - Next Implementation Slice Selection

- Select the next implementation slice strictly by release impact and state the
  blocker it clears.

### Phase 7994 - Operator Runbook Update

- Update the operator runbook so a contextless maintainer can start the admin
  API/frontend and understand what Release 0.1 can and cannot do.

### Phase 7995 - Documentation Index Update

- Link the burn-down, milestones, handoff, and work queue from the ordered docs
  index.

### Phase 7996 - Autonomous Validator Pivot

- Update autonomous validators and artifacts so active work is `7981-8000` and
  proof-only drift fails validation.

### Phase 7997 - Backend Contextless Review

- Run a blind/contextless backend review focused on whether Release 0.1 scope
  and next work are understandable without chat history.

### Phase 7998 - Frontend Contextless Review

- Run a blind/contextless frontend review focused on whether Release 0.1 scope,
  blockers, and backend association are understandable without chat history.

### Phase 7999 - Focused Validation And Hygiene

- Run focused validators/tests for changed docs, artifacts, and quality gates.
  Run stale-process checks if any backend/frontend test command is interrupted
  or times out.

### Phase 8000 - Commit And Push Evidence

- Commit and push synchronized backend/frontend pivot changes and record live
  Coinbase execution status. Default evidence for this pivot is no live
  Coinbase execution, submitted notional `0` USDC, executed notional `0` USDC.
