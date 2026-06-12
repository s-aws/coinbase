# Maintainer Handoff

This guide is the backend entry point for maintainers and contextless agents
working on the enterprise admin platform.

## Scope

The backend repository owns trading behavior, Coinbase integration, guard
checks, authorization, audit evidence, OpenAPI schema generation, and all live
execution authority. The frontend repository at `C:\coinbase-frontend` owns the
browser application and must consume backend-owned contracts only.

Spot is the first complete product module, not the generic model for futures,
perpetuals, stealth orders, movement/repricing, or future modules.

## Start Here

1. Read `AGENTS.md`, then `agent.md`.
2. Read `docs/README.md` for the ordered documentation index.
3. Read `README.admin-api.md` for the Admin API boundary.
4. Read `docs/ADMIN_MODULE_CAPABILITY_MATRIX.md` before changing module scope.
5. Read `docs/plans/ADMIN_API_ROUTE_INVENTORY.md` before adding or changing a route.
6. Read `docs/LIVE_ORDER_SURFACES.md` before any live-order or cancellation work.
7. Read `docs/plans/ADMIN_API_CONTEXTLESS_REVIEW_LOG.md` before declaring a handoff complete.

## Backend Authority Rules

- Use one code path per behavior.
- Use `client_order_id` for internal order identity.
- Coinbase cancellation is the explicit exception: call the project wrapper
  `cancel_order(client_order_id)` because Coinbase accepts the client id.
- Do not put trading decisions in browser code or generated frontend clients.
- Do not import spot no-shorting or wallet-inventory rules into futures or
  perpetual workflows.
- Do not mutate stealth local state unless the corresponding live exchange
  handling has gone through the existing cancel, move, or reconcile path.

## Adding An Admin Module

1. Define the backend read or command contract first.
2. Add route inventory evidence in `application/admin_api/route_inventory.py`
   and `docs/plans/ADMIN_API_ROUTE_INVENTORY.md`.
3. Add typed response/request models in `application/admin_api/models.py`.
4. Use existing shared services; do not introduce a parallel trading path.
5. Update `docs/ADMIN_MODULE_CAPABILITY_MATRIX.md`.
6. Update examples under `docs/examples/`.
7. Regenerate `openapi/coinbase-admin-api.yaml`.
8. Add focused regression coverage in `tests/regression/`.
9. Coordinate frontend generated-client changes from the OpenAPI output.
10. Run a blind/contextless review for module discoverability and authority boundaries.

## Contextless Task Card

Use this checked-in task shape when asking a fresh agent to prove the handoff
material is sufficient:

```text
Without chat history, explain how to add a read-only Admin API module for a
new backend evidence source. Identify the files you would read first, the
backend route/model/test/docs files you would change, how the frontend should
consume the generated OpenAPI contract, and which gates must pass. Do not
implement trading behavior or live Coinbase execution.
```

Passing answer requirements:

- names `docs/MAINTAINER_HANDOFF.md`, `README.admin-api.md`,
  `docs/plans/ADMIN_API_ROUTE_INVENTORY.md`, and
  `docs/ADMIN_MODULE_CAPABILITY_MATRIX.md`
- keeps backend authority over trading behavior and live execution
- sends frontend work through OpenAPI generation and canonical wrappers
- lists backend regression, frontend release gate, autonomous validation, and
  blind/contextless review
- reports live Coinbase execution as not run unless an explicit live phase is
  approved

## Required Gates

Backend changes must pass:

```powershell
pytest tests\regression\ -v --tb=short
python tools\run_autonomous_work_queue_check.py --summary-only
```

Frontend/API association changes must also pass in `C:\coinbase-frontend`:

```powershell
npm run release:gate
```

Live Coinbase execution is not part of normal handoff validation. If a live
phase is explicitly approved, report product, submitted notional, executed
notional, retained inventory, reconciliation result, and audit ids.

## Current Handoff State

- M9/M21/M23/M24/M25/M26 enterprise readiness is exposed by
  `GET /api/v1/admin/enterprise-readiness`.
- Active autonomous range: `1221-1240`.
- M36 durable approval-store foundation is in progress. It may add backend
  append-only approval-store infrastructure and evidence only. It must not
  add an approval endpoint, approval mutation, live admission endpoint, guard
  evaluator, Coinbase call, direct dashboard WebSocket approval path, BFF
  mutation broadening, browser approval workflow, browser approval writer, or
  reconciliation authority.
- M35 command admission audit persistence writes admission decisions through
  the existing append-only Admin API audit log and Audit Workbench read path
  only. Persisted admission decisions can describe route, payload hash,
  idempotency, operator intent, approval snapshot, cap/guard,
  admission-audit, and reconciliation blockers, but they must not become
  browser approval, browser wallet authority, audit mutation, guard execution,
  a new command route, Coinbase execution, or reconciliation authority.
- M34 command admission decision evidence is exposed through existing
  live-disabled Admin API command responses. It must remain evidence-only:
  decisions can describe route, payload hash, idempotency, operator intent,
  approval, cap/guard, admission-audit, and reconciliation blockers, but they
  must not become browser approval, browser wallet authority, guard execution,
  a new command route, Coinbase execution, or reconciliation authority.
- M32 live-admission audit trail evidence is exposed through the existing
  `GET /api/v1/admin/live-enablement` read. It must remain evidence-only:
  facts can describe what an append-only backend admission audit trail must
  prove, but they must not become audit storage, approval storage, browser
  approval, a command route, Coinbase execution, or reconciliation authority.
- M31 approval-store contract evidence is exposed through the existing
  `GET /api/v1/admin/live-enablement` read. It must remain evidence-only:
  requirements can describe configured durable backend approval-store
  infrastructure, but they must not become approval mutation, browser
  approval, a command route, Coinbase execution, or reconciliation authority.
- M30 route-specific approval snapshot evidence is exposed through the
  existing `GET /api/v1/admin/live-enablement` read. It must remain
  evidence-only: required fields can describe what a durable backend approval
  snapshot must contain, but they must not become approval storage, browser
  approval, a command route, Coinbase execution, or reconciliation authority.
- M29 controlled-live preflight evidence is exposed through the existing
  `GET /api/v1/admin/live-enablement` read. It must remain evidence-only:
  passed and blocked checks can describe readiness, but they must not become a
  browser preflight approval path, live switch, command route, Coinbase call,
  or reconciliation path.
- M28 enterprise command gap triage uses existing
  `GET /api/v1/admin/enterprise-readiness` and
  `GET /api/v1/admin/capabilities` evidence. It must remain a read-only
  triage lens and must not add a parallel endpoint, command path, or browser
  approval workflow.
- M27 live-action governance linkage uses the existing
  `GET /api/v1/admin/live-enablement`, `GET /api/v1/admin/capabilities`, and
  `GET /api/v1/admin/enterprise-readiness` reads. It must remain evidence
  only and must not add a parallel governance endpoint or live command path.
- The frontend Enterprise Module Catalog consumes the existing readiness
  contract. Do not add a parallel module-catalog endpoint or browser trading
  authority.
- The frontend Enterprise Module Traceability surface also consumes the same
  readiness contract. Do not add a parallel traceability endpoint or use route
  lists, command gaps, or contract refs as browser command authority.
- The frontend Enterprise Module Capability Linkage surface consumes
  `GET /api/v1/admin/capabilities` plus enterprise readiness. Do not add a
  parallel capability-linkage endpoint or treat capability rows as browser
  command authority.
- Default live Coinbase execution: `not_run`.
- Submitted notional: `$0`.
- Executed notional: `$0`.
