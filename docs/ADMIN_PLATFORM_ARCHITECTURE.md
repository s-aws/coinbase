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
- enterprise-readiness command-gap evidence for unsupported, not modeled, and
  live-disabled command paths
- enterprise-readiness module registry evidence for module ids, owners,
  contract refs, docs, identity keys, and spot-rule boundaries
- route inventory and capability `module_id` evidence that binds Admin API
  routes to enterprise modules
- enterprise-readiness action posture evidence derived from route-inventory
  `module_id`, not broad path prefixes
- live-enablement governance linkage that binds live-shaped command routes to
  module ownership, identity keys, required gate controls, reconciliation
  blockers, capability evidence, and no-browser-authority proof
- controlled-live preflight evidence that names passed and blocking
  prerequisites per live-shaped command route without approving execution
- route-specific approval snapshot evidence that names missing durable,
  backend-owned, expiring, payload-bound approval fields without creating
  approval storage or browser approval
- approval-store contract evidence that names configured durable backend store
  infrastructure without creating approval mutation, command authority, or
  browser approval
- live-admission audit trail evidence that names missing append-only backend
  audit facts without creating audit storage, command authority, or browser
  approval
- route-specific cap/guard contract evidence that names missing backend
  cap, guard, payload, approval, admission-audit, and product-scope bindings
  without creating guard execution, command authority, or browser approval

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
- Audit Workbench
- Admin / System Health

Spot rules include wallet inventory, USDC scope, no shorting, cost basis,
average-cost evidence, and known profitable inventory. Those are spot-only.
Futures/perpetual modules need position, margin, leverage, liquidation,
reduce-only, close-only, funding, collateral, and position P/L contracts
before the frontend can safely model them.
Guard / Risk Policy is a platform evidence module over
`GET /api/v1/admin/guard-risk-policy`; it reports backend guard, cap,
live-execution, product capability, profitability, authority, and rejection
posture without becoming a second evaluator or performing Coinbase wallet
reads.
Audit Workbench is a platform evidence module over
`GET /api/v1/admin/audit-workbench`; it normalizes route, command,
correlation, audit, module, and exchange evidence without becoming a command
replay path, audit mutation path, or Coinbase reader.

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
- Which enterprise `module_id` owns the route?
- Does module action posture come from backend `module_id` evidence rather
  than frontend path inference?
- Which fields are identity and which are exchange evidence?
- Which product-specific rules apply?
- Which spot-only rules must not be copied?
- Which command routes are live-disabled, dry-submit only, or live-approved?
- Which tests and release gates prove the boundary?

If any answer is unclear, update contracts, route inventory, or docs before
adding UI behavior.
For command paths that are not implemented, start with structured
`command_gaps` evidence from `GET /api/v1/admin/enterprise-readiness`; do not
infer support from absent buttons or historical chat context.
For module ownership and extension work, start with the same route's registry
fields. A fresh maintainer should not need chat history to find the owner,
backend contract refs, frontend contract refs, docs, or spot-rule boundary.
For module action posture, use the backend `action_posture` object from
`GET /api/v1/admin/enterprise-readiness`. Do not infer command authority from
route counts, and do not group `/api/v1/admin/*` paths by prefix when a
specific `module_id` exists.
The frontend Enterprise Module Catalog is a read-only rendering of the same
enterprise-readiness payload. Do not add a parallel module-catalog endpoint or
move module authority into the browser.
The frontend Enterprise Module Traceability surface also uses that same
payload for route lists, command gaps, contracts, docs, identity keys, and
spot boundaries. Do not add a parallel traceability endpoint or infer browser
command authority from trace evidence.
The frontend Enterprise Command Gap Triage surface uses the same
enterprise-readiness payload plus capability rows to group unsupported,
not-modeled, and command-draft-live-disabled gaps across modules. Do not add a
parallel triage endpoint, command path, BFF mutation, direct dashboard
WebSocket call, Coinbase call, or browser approval workflow from this
evidence.
The frontend Enterprise Module Capability Linkage surface combines
`GET /api/v1/admin/capabilities` with enterprise-readiness module rows to show
per-module capability rows, command contracts, shared methods, permissions,
and disabled command workflow posture. Do not add a parallel linkage endpoint
or treat capability rows as browser approval for live execution.
The frontend Enterprise Live-Action Governance Linkage surface combines
`GET /api/v1/admin/live-enablement`, `GET /api/v1/admin/capabilities`, and
`GET /api/v1/admin/enterprise-readiness` to show per-route gate controls,
module ownership, identity keys, reconciliation blockers, and no-browser
authority. Do not add a parallel governance endpoint or change live-disabled
HTTP command behavior from this evidence.
The controlled-live preflight matrix is a read-only refinement of
`GET /api/v1/admin/live-enablement`. It may show which prerequisites are
passed or blocking, but it must not become a separate preflight endpoint,
browser approval workflow, live switch, Coinbase call, or reconciliation
path.
Route-specific approval snapshot evidence is another read-only refinement of
the same route. It may show required approval fields and their expected
backend sources, but it must not become approval storage, a browser approval
workflow, command authority, Coinbase execution, or reconciliation evidence.
Approval-store contract evidence is the next read-only refinement of the same
route. It may show backend store requirements and expected authority sources,
but it must not become an approval database, browser approval workflow,
command authority, Coinbase execution, or reconciliation evidence.
Live-admission audit trail evidence is a read-only refinement of the same
route. It may show required append-only admission facts and expected backend
sources, but it must not become audit storage, approval storage, browser
approval workflow, command authority, Coinbase execution, or reconciliation
authority.
Route-specific cap/guard contract evidence is a read-only refinement of the
same route. It may show required backend cap/guard bindings and expected
authority sources, but it must not become guard execution, browser wallet or
profitability authority, command authority, Coinbase execution, or
reconciliation evidence.

## Durable Milestones

Use [Admin Platform Durable Milestones](plans/ADMIN_PLATFORM_DURABLE_MILESTONES.md)
as the completion-oriented plan for broadening the platform beyond spot. The
milestones define what counts as done, which evidence is required, and why the
next non-spot slice should start with read-only backend-owned contracts.
