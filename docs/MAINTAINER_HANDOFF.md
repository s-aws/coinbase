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
8. Read `docs/plans/AUTONOMOUS_WORK_QUEUE.md` before advancing phases. Each
   active phase must map to an approved durable milestone and an explicit
   architecture or planning gap.

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
- Active autonomous range: `2001-2020`.
- M49 approval lifecycle, M50 cap/guard records, M51 admission audits, and
  M52 reconciliation plan records are complete. M53 closed with a single
  dry-run pilot adapter for `POST /api/v1/orders` through
  `AdminApiCommandService.place_manual_order`. M54 completed the first
  read-only Spot command-suite slice, backend-owned proof-route linkage, and
  backend-owned readiness preconditions at
  `GET /api/v1/spot/command-suite` for manual order, cancel by
  `client_order_id`, and campaign execution readiness, then bound those rows
  into website command workflow draft evidence. M54 then added typed
  `coverage_gaps` for spot sweep automation, recovery workflow, and
  reconciliation workflow so missing spot admin families are explicit before
  new command routes or live controls exist. M54 then linked those gap rows to
  typed `current_read_evidence` rows derived from route inventory and added
  durable Spot P/L checkpoint records at `/api/v1/spot/pnl/checkpoints`. M54
  then extended that same checkpoint path with average-cost review evidence,
  verified append-only Admin API audit-link readback, read-only recovery-link
  evidence to backend-owned recovery gate and fill-ledger-health reads, and
  read-only reconciliation-plan link evidence to backend-owned reconciliation
  plan reads. P/L tracking is no longer a current command-suite coverage gap.
  M54 then added the read-only Spot recovery-preview route, and the 1821-1840
  range extended that foundation with read-only recovery apply-review,
  rollback-plan, and reconciliation-proof routes. The completed 1841-1860 range added
  disabled/no-live POST contracts for recovery apply execution, rollback
  execution, exchange-state proof recording, and reconciliation-proof
  recording. The completed 1861-1880 range added durable proof persistence,
  proof readback, and the `spot_recovery:record` permission for proof
  recording. The completed 1881-1900 range added no-live recovery
  apply/rollback execution journal plumbing and post-apply reconciliation
  boundaries. The completed 1901-1920 range added guarded local repair-result
  evidence and clarified that recovery-state evidence is not order/exchange
  mutation, Coinbase activity, or browser authority. The completed 1921-1940 range adds
  backend-owned post-apply reconciliation completion evidence: reconciliation
  proof recording can append a guarded local completion record only after
  matching proof, apply journal, repair-result, approval, admission audit,
  cap/guard, reconciliation-plan, idempotency, operator-intent, and
  payload-hash evidence. Recovery apply/rollback journal acceptance, guarded
  repair-result evidence, and completion records are durable after exact
  backend prerequisites match. The completed 1941-1960 range added the
  route-bound fail-closed reconciliation execution boundary at
  `POST /api/v1/spot/recovery/reconciliation-executions`; that route is
  audited, idempotent, RBAC/proof-gated, and rejected until backend executor
  and live Coinbase read authority exist. The completed 1961-1980 range adds
  backend-owned no-live snapshot records; those records do not read Coinbase
  or prove live exchange truth. The completed 1981-2000 range started M55 by
  adding read-only stealth command-suite readiness evidence for create,
  cancel, reveal, move, reprice, recovery, and reconciliation workflows and
  linked existing live-disabled stealth cancel and movement/reprice route
  evidence without enabling them. The active 2001-2020 range continues M55 by
  adding a route-bound, live-disabled `POST /api/v1/stealth/orders` create
  command draft keyed by `stealth_order_id`. It may expose typed request
  shape, backend-owned identity derivation, route inventory, command-suite
  linkage, frontend generated types, BFF forwarding, and dry-submit evidence,
  but it must not invoke `StealthOrderManager`, create local stealth state,
  reveal orders, cancel active placements, move/reprice revealed orders,
  mutate stealth/order/exchange state, execute reconciliation, read Coinbase,
  or grant browser/BFF stealth command authority. This foundation must not add
  a parallel writer,
  browser P/L authority, sell authority, tax accounting, browser audit
  authority, browser recovery authority, browser reconciliation authority,
  recovery execution, repair apply, rollback execution, reconciliation
  execution, order/exchange-state mutation, or Coinbase execution. Live
  Coinbase execution
  remains disabled unless a later phase explicitly runs under the carried cap
  policy.
  Browser approval, BFF forwarding, linked snapshots, cap/guard records, audit
  records, reconciliation plans, command-suite proof routes, command draft
  evidence, or pilot adapter evidence are not sufficient live execution
  authority by themselves.
  The active 2001-2020 range must keep stealth create as no-live draft
  evidence before any lifecycle-write, create/reveal/cancel/move/reprice/
  recovery/reconciliation behavior can be considered through the enterprise
  Admin API.
- M48 mutation taxonomy and authority map is complete for phases `1461-1480`.
  The existing `GET /api/v1/admin/enterprise-readiness` route reports
  backend-owned `mutation_taxonomy` rows that map every current command route,
  approval lifecycle local-state mutation route, and legacy command surface to
  exactly one mutation family.
- M47 backend functionality inventory and gap ledger is complete for phases
  `1441-1460`. The existing `GET /api/v1/admin/enterprise-readiness` route
  reports backend-owned workflow inventory rows for read, command, live,
  recovery, repair, automation, and legacy compatibility surfaces.
- M46 live readiness precondition evidence is complete for phases
  `1421-1440`.
  `GET /api/v1/admin/live-enablement` may report a normalized backend-owned
  checklist for approval store, approval snapshot, admission audit, cap/guard,
  reconciliation, live execution adapter, execution intent envelope,
  browser/BFF boundary, and disabled live execution service prerequisites.
  The checklist is read-only evidence. Do not call command admission with
  synthetic values, create a new preflight endpoint, remove command blockers,
  mark paths live eligible, add browser approval, broaden BFF execution
  authority, or call Coinbase from this evidence.
- M45 live execution intent envelope evidence is complete for phases
  `1401-1420`. Existing command
  admission decisions may report a backend-owned execution intent that binds
  route, identity, payload hash, idempotency key, actor, operator intent, and
  shared `AdminApiCommandService` method, but the intent remains disabled, not
  prepared, non-executable, and display only. Do not add route-local
  execution, browser approval, BFF execution authority, or Coinbase calls.
- M44 live execution adapter contract evidence is complete for phases
  `1381-1400`. Existing
  live-enablement path rows may report a backend-owned adapter contract that
  maps a live-shaped route to its shared `AdminApiCommandService` method, but
  the adapter remains disabled, unconfigured, non-executable, and display
  only. Do not add route-local execution, browser approval, BFF execution
  authority, or Coinbase calls.
- M43 disabled live execution service foundation is complete for phases
  `1361-1380`. Existing Admin API command admission evidence consumes a
  backend-owned disabled service descriptor reporting the service as present
  but `live_disabled` with source `disabled_backend_service`. The descriptor
  must not expose create, cancel, submit, execute, Coinbase, route-local
  execution, browser approval, or BFF execution authority methods.
- M42 command admission live execution service boundary evidence is complete
  for phases `1341-1360`. Existing Admin API command admission evidence may
  report that the
  backend live execution service is required but disabled/unconfigured. It
  must not remove `live_execution_disabled`, add a live switch, authorize
  browser evidence, broaden BFF mutation authority, call Coinbase, or create
  a second command path.
- M41 command admission reconciliation plan proof wiring is complete for
  phases `1321-1340`. Existing Admin API command admission evidence may
  consult backend-owned append-only reconciliation plan proof after exact
  approval snapshot, admission-audit, and cap/guard proof resolution. A
  resolved reconciliation proof may remove only
  `reconciliation_plan_missing`; live-disabled and browser-authority blockers
  remain. It must not add reconciliation execution, a reconciliation mutation
  endpoint, browser approval, BFF reconciliation authority, live admission
  endpoint, Coinbase calls, direct dashboard WebSocket reconciliation, browser
  reconciliation writer, or order/exchange-state mutation.
- M40 command admission cap/guard proof wiring is complete. Existing Admin
  API command admission evidence may consult backend-owned append-only
  cap/guard decision proof and expose whether an exact approval-snapshot-bound
  and admission-audit-bound decision was found. A resolved cap/guard proof may
  remove only `cap_guard_missing`; live-disabled, reconciliation, and
  browser-authority blockers remain. It must not add a guard mutation
  endpoint, browser approval, BFF guard authority, live admission endpoint,
  guard evaluator, Coinbase call, direct dashboard WebSocket guard path,
  browser guard writer, or reconciliation authority.
- M39 command admission audit resolver wiring is complete. Existing Admin API
  command admission evidence may consult backend-owned append-only audit proof
  and expose whether an exact approval-snapshot-bound audit event was found. A
  resolved audit proof may remove only `admission_audit_missing`;
  live-disabled, cap/guard, reconciliation, and browser-authority blockers
  remain. It did not add an audit mutation endpoint, browser approval, BFF
  audit authority, live admission endpoint, guard evaluator, Coinbase call,
  direct dashboard WebSocket audit path, browser approval workflow, browser
  audit writer, or reconciliation authority.
- M38 command admission snapshot resolver wiring is complete. Existing Admin
  API command admission evidence can consult the backend-owned approval
  snapshot resolver and expose whether an exact unexpired snapshot was found.
  A resolved snapshot removes only `approval_snapshot_missing`; live-disabled,
  admission-audit, cap/guard, reconciliation, and browser-authority blockers
  remain. It did not add an approval endpoint, approval mutation, live
  admission endpoint, guard evaluator, Coinbase call, direct dashboard
  WebSocket approval path, BFF resolver authority, browser approval workflow,
  browser approval writer, or reconciliation authority.
- M37 approval snapshot resolver foundation added backend-only resolver
  infrastructure that derives immutable approval snapshot evidence from an
  exact unexpired approval-store record without approving or executing
  commands.
- Approval-store JSONL rows without M37 `requested_by_actor_id` fail closed
  during strict reads and are ignored by resolver lookup.
- M36 durable approval-store foundation added backend append-only
  approval-store infrastructure and evidence only. It did not add approval
  mutation, browser approval, live admission, or live Coinbase execution.
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
