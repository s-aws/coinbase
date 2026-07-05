# Coinbase Admin MVP Rebuild Goal

## Objective

Build a local, continuously deployable Coinbase Admin MVP from `origin/prod`,
preserving only the useful MVP-critical frontend and backend pieces from the
current work. The product must let an operator use the admin frontend locally to
operate the backend through auditable Admin API/BFF paths, including controlled
live Coinbase execution when explicitly enabled, authorized, capped, and
recorded by the backend.

An entirely new main branch may be created from prod if necessary to keep a
clean starting point instead of correcting the current main branch.

## Non-Negotiables

- Local deployment target is `coinbase-local` unless a real deployment target is
  explicitly configured later.
- Continuous deployment must always leave a functional local product.
- The frontend is operator UI only. It must not call Coinbase directly or create
  trading API calls outside the Admin/BFF/backend path.
- The backend owns Coinbase calls, live-action authorization, guard checks,
  wallet checks, approvals, caps, idempotency, and audit correlation.
- Live Coinbase execution is allowed only through backend Admin interfaces with
  explicit operator intent and auditable backend decision evidence.
- `live_coinbase_execution` and `notional_usdc` are recorded outputs of a run.
  They must reflect what actually happened; they are not hardcoded MVP limits.
- CI/CD must not execute live trades by default. Any live execution validation
  must be manual, explicit, capped, and separately auditable.
- Avoid carrying forward evidence-tightening, phase-range, docs, or platform
  expansion work unless it directly blocks MVP operation, local deployment,
  controlled live execution, or demo readiness.

## MVP Acceptance

An operator can run the local frontend and backend, use the UI to perform the
intended admin workflow through backend Admin APIs, see backend decisions and
audit correlation evidence, and verify deployment evidence that records the
actual frontend commit, backend commit, live execution posture, and notional
used for that run.

## Current Evidence

- `origin/prod` is the clean baseline but only has the legacy
  `dashboard_server.py` WebSocket command path for direct dashboard operation.
- `origin/prod` does not contain the current Admin API packages, generated
  OpenAPI contract, backend local deployment scripts, or backend CI/CD local
  deployment workflow.
- Current backend `main` contains useful MVP pieces that should be harvested
  selectively:
  - `dashboard_server.py` bridge from legacy dashboard commands into
    `AdminApiCommandService`.
  - `api/v1/app.py` and the minimal Admin API route set needed for the local
    operator workflow.
  - `application/admin_api/models.py`, `auth.py`, `command_runtime.py`,
    `command_service.py`, `idempotency.py`, `live_execution.py`, and audit or
    decision services required by that workflow.
  - `openapi/coinbase-admin-api.yaml` and route inventory generation, trimmed
    only if the frontend contract remains satisfied.
  - `tools/run_admin_api.py`,
    `tools/run_admin_api_controlled_live_mvp_smoke.py`,
    `tools/write_admin_api_deployment_manifest.py`, and
    `tools/apply_admin_api_local_deployment.py`.
  - `.github/workflows/deploy.yml` and public checks only insofar as they keep
    a local `coinbase-local` backend deployment functional.
- Current frontend `main` contains useful MVP pieces that should be preserved:
  - Admin/BFF-only operator UI behavior.
  - Generated-client/OpenAPI contract checks.
  - Local deployment manifest generation and `coinbase-local` frontend apply.
  - Backend local release manifest matching in frontend deployment evidence.

## Explicit Exclusions By Default

- Do not import futures/perpetual semantic proof expansions unless they are
  required by the first local operator MVP workflow.
- Do not import phase-range or autonomous queue bookkeeping unless it directly
  gates local MVP operation.
- Do not import broad documentation expansion unless it is needed to run,
  deploy, or demo the local MVP.
- Do not preserve the legacy dashboard direct Coinbase path as the product
  authority path. It may only be used as a compatibility input that delegates to
  the Admin API command service.

## Immediate Build Order

1. Keep this prod-based branch clean and runnable.
2. Harvest the smallest backend Admin API command path needed for one local
   operator workflow.
3. Add backend local deployment packaging/apply for `coinbase-local/backend`.
4. Align the frontend backend contract reference to this prod-based backend
   branch.
5. Prove local frontend-to-backend operation through Admin/BFF, including audit
   correlation and recorded live execution posture.
6. Add continuous deployment that applies only to the local target by default.
