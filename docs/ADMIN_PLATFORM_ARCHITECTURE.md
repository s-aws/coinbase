# Admin Platform Architecture

The Admin API is the backend contract layer for the enterprise admin platform
across the whole Coinbase trading engine. Spot is the first complete product
module consumed by the frontend; it is not the generic model for every
backend feature.

## Objective

Expose professional backend-owned contracts that let the separate frontend
operate project modules without moving trading authority into browser code.
The backend owns OpenAPI, auth/RBAC, idempotency, audit, approval, caps,
guards, wallet or position authority, Coinbase calls, reconciliation, and
live execution gates.

## Platform Primitives

These primitives apply across modules:

- FastAPI routes and backend-owned OpenAPI generation
- generated frontend client association
- auth, RBAC, OIDC/JWT readiness, CSRF, and CORS boundaries
- idempotency stores, request ids, correlation ids, and audit ids
- command service boundaries and fail-closed live-disabled posture
- structured errors and observability headers
- BFF/session bridge expectations and response-evidence headers
- route inventory, release evidence, regression gates, and no-live proof
- contextless review before broadening order, campaign, live-action, or
  non-spot module behavior

Platform primitives describe authority flow and evidence. They do not encode
domain-specific trading rules.

## Domain Modules

Domain modules keep their own contracts and risk semantics:

- Spot Operations
- Futures / Perpetuals
- Stealth Orders
- Order Movement / Repricing
- Campaigns / Sweeps
- P/L, Ledger, And Reconciliation
- Guard / Risk Policy
- Admin / System Health

Spot rules include wallet inventory, USDC scope, no shorting, cost basis,
average-cost evidence, and known profitable inventory. Those are spot-only.
Futures/perpetual modules need position, margin, leverage, liquidation,
reduce-only, close-only, funding, collateral, and position P/L contracts
before the frontend can safely model them.

## Extension Rule

Before adding or broadening an Admin API module:

1. Classify the feature as platform primitive or domain module.
2. Identify the owner and backend service boundary.
3. Define read routes before frontend read models.
4. Define command routes before frontend drafts or dry-submit.
5. State identity keys, exchange evidence fields, cancellation keys, and audit
   evidence.
6. State product-specific risk rules.
7. Regenerate OpenAPI and frontend client output when contracts change.
8. Run focused Admin API tests, backend regression when required, frontend
   release gates when consumed, and a blind/contextless review.

## Contextless Review Questions

A reviewer with no chat history should be able to answer:

- Is this behavior a platform primitive or domain module?
- Which backend route and service own it?
- Which fields are identity and which are exchange evidence?
- Which product-specific rules apply?
- Which spot-only rules must not be copied?
- Which command routes are live-disabled, dry-submit only, or live-approved?
- Which tests and release gates prove the boundary?

If any answer is unclear, update contracts, route inventory, or docs before
adding UI behavior.

## Durable Milestones

Use [Admin Platform Durable Milestones](plans/ADMIN_PLATFORM_DURABLE_MILESTONES.md)
as the completion-oriented plan for broadening the platform beyond spot. The
milestones define what counts as done, which evidence is required, and why the
next non-spot slice should start with read-only backend-owned contracts.
