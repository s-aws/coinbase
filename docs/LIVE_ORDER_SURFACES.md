# Live Order Surfaces

This project has several operator and test surfaces. They do not have equal
live authority, and a backend-only live runner is not proof that the matching
HTTP or browser workflow is live-capable.

The standing integration goal is `operator_ready_admin_mvp_runtime_v1`.
Historical R1-R12 Preview artifacts and terminal results remain immutable and
grant no new Futures Preview, R13, Slice 3/4/5, or mutation authority. The
operator runtime described below activates only the two supported Spot Admin
routes; it does not activate the legacy engine's autonomous trading loops.
Slice 1 uses only
authoritative GET account/position reads. R7 consumed the sole authorized
non-ordering Coinbase successor call after consumed R6. Exactly one
Preview-only call returned control before a sanitized post-Preview `ValueError`
and no accepted Preview evidence was appended. It retained the V3
regular=`UNSPECIFIED` plus intraday-profile=`INTRADAY` pair, one contract,
strict `<100 / <150 / <300 USDC` caps, and the corrected official
liquidation-response schema. The repeatable Admin API/UI path exposes exact
immutable R8 through a documented-SHA/stat-metadata-only zero-call forensic
contract, never opens R8, and cannot call Coinbase. R9 is terminal blocked
after all six fixed reads and one
returned Preview reached response validation; it made zero retries, fallbacks,
redirects, Create, Cancel, Close, Reduce, marker, ledger, runtime, or exchange
mutations. R10 later consumed its one Preview and blocked at sanitized
economics validation, again with zero retries, fallbacks, redirects,
submissions, or mutations. R10 is permanently disabled, no Preview or R11
authority remains, Slice 3 did not run, and Slices 4/5 are unauthorized. Default
release and deployment checks remain no-live and report live Coinbase execution
as not run with notional `0`.

## Admin HTTP Surfaces

- Ordinary operator bootstrap and refresh GETs are local and call-free in both
  No-live and Controlled-live modes. Account-management, wallet, product, fee,
  Spot readiness, and Futures panels cannot inherit the REST client retained
  for an explicit action. Fresh Coinbase reads occur only inside separately
  acknowledged, route-specific backend actions.
- `POST /api/v1/orders` is the live-capable manual Spot placement route. It may
  pass `allow_live_execution=true` to the shared command service only after the
  route-bound backend admission decision allows the exact request. The command
  service accepts only exact LIMIT/GTC base-size semantics and still enforces
  runtime opt-in, product capability, size, wallet, inventory/no-short, audit,
  event-stream, Coinbase response checks, and the stricter of the approved
  submitted- and possible-executed-notional caps before submission.
- `POST /api/v1/orders/{client_order_id}/cancel` is the live-capable Spot
  cancellation route. It passes the route-bound admission decision to the
  shared cancel service, which still requires exact runtime authority, RBAC,
  intent, idempotency, approval, cap/rate, audit, reconciliation, portfolio,
  and order-identity evidence before Coinbase cancellation. The request must
  also carry exact `manual_live_acknowledgement=true`; a missing or false
  acknowledgement is rejected before any Coinbase read. Immediately before
  crossing the Coinbase cancel boundary, the service must durably mark the root
  `SUBMISSION_UNKNOWN`; a failed mark prevents the call, while process loss
  after the mark leaves the root quarantined until explicit reconciliation.
- `POST /api/v1/orders/{client_order_id}/fill-follow-up/trigger` is a guarded
  no-live local-state compatibility route. It can invoke the existing
  fill-follow-up executor after exact prerequisites and must prove one accepted
  child through parent/child readback. It does not submit or cancel Coinbase
  orders and is not automatic fill-event processing.
- Historical Slice 1 used bounded Futures account/position reads. The installed
  `GET /api/v1/futures/account`, positions, exact position, risk-proof,
  command-suite, and fill-readback surfaces now return local sanitized or fixed
  source-disabled evidence and make zero Coinbase calls. Futures place,
  close/reduce, cancel, and reconciliation routes are fixed source-disabled
  boundaries. Any later successor requires source restoration, implementation,
  audit/preparation authority, and separate explicit authorization.
- Generic stealth create/reveal/move/cancel/recovery/reconciliation, movement
  reprice, campaign, sweep, fill-follow-up, and controlled-batch HTTP/CLI
  mutations are no-live, local-evidence, or source-disabled surfaces. The old
  deterministic first-child and schema-24 controlled-recovery procedures are
  completed historical evidence only: they cannot reveal/cancel a child, send
  a process signal, mint the canonical SDK scope, or advance a batch. There is
  no installed stealth or batch execution exception.

## Supported Controlled-Live Surface

Only the installed authenticated Admin API manual Spot LIMIT/GTC place and
cancel routes can enter Controlled-live mode. The browser forwards operator
requests but holds no exchange credentials or execution authority. The backend
requires the exact outer flag, manager-issued owner-only lease, current
lease-bound service decision, RBAC, intent, idempotency, approval, caps,
portfolio/wallet evidence, audit, and reconciliation at each request.

Historical raw Spot smoke/sweep tools, legacy controlled-batch runners,
dashboard WebSocket mutations, and legacy `main.py` Controlled-live startup
are source-disabled. Other legacy live scripts are not supported operator
surfaces and cannot mint the canonical route-bound execution scope.

M58 is not in that operator-live set. Its local/synthetic readiness, validator,
and historical readback evidence remain available, but all three M58 Admin API
exchange routes use a source-parked dependency and return typed
`501 m58_operator_workflow_unavailable` before any Coinbase executor or new
submission-record write. Test-only dependency overrides validate sanitized
fixtures; they are not installed runtime configuration or browser authority.

Each live run must record the actual product, `client_order_id`, environment,
account or portfolio scope, submitted/executed notional, backend decisions,
audit ids, and cancel/rollback/readback result.

## Legacy Compatibility Surfaces

- Dashboard WebSocket `place_order`, `cancel_order`, and
  `place_hotpoint_test_order` return a fixed source-disabled response and make
  no exchange mutation.
- The legacy engine may remain useful for read/compatibility behavior, but
  startup with exact Controlled-live authority is source-disabled.
- Spot portfolio sweep/campaign tooling retains read-only reporting and
  historical reference helpers; mutation modes are source-disabled.

New frontend product work must use generated Admin API contracts and canonical
BFF wrappers. Do not use the dashboard WebSocket, a backend CLI, or an exchange
`order_id` as a shortcut around route authority.

## Current Fill/Follow-Up Boundary

The guarded no-live operator chain is implemented. Automatic/live fill-event
parity uses the same authority as every other live order: the current goal's
explicit side, price, notional, rate, and cancellation limits plus
backend-owned authorization, wallet/cap, duplicate-order, audit-correlation,
reconciliation, rollback, and readback gates. Whether an order fills is an
outcome, not a separate permission category. Fan-out, scheduler,
retry/runtime-control, wallet-ledger, and ladder/grid work is parked and cannot
make itself current by producing more evidence about its own blockers.
