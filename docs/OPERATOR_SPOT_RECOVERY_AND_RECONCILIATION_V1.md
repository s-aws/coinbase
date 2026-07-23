# Operator Spot Recovery and Reconciliation V1

Goal: `operator_spot_recovery_and_reconciliation_execution_v1`

This goal translates the useful recovery invariants from
`origin/prod:business/fill_reconciler.py`,
`origin/prod:core/periodic_reconciler.py`, and
`origin/prod:core/startup_reconciler.py` into an explicit authenticated
operator workflow. Historical background reconciliation and auto-heal are
comparison material only. Current authority is the generated Admin API,
PostgreSQL claims, canonical Spot services, and explicit operator intent.

## Operator workflow

The routed Admin UI creates and selects a case by canonical
`client_order_id`. The backend verifies that the local order is system-owned
and bound to the configured approved Test portfolio. A confirmed refresh
claims one of ten goal-scoped cycles before external work, then permits:

- one logical exact-order read, including required cursor pages;
- one logical fill read, including required cursor pages;
- no retry of an individual call or page.

The backend creates a fixed immutable plan:

- `NO_CHANGE` when local and authoritative exchange state agree;
- `SET_LOCAL_STATUS` when authoritative terminal truth safely corrects local
  status;
- `CANCEL_ACTIVE_ORPHAN` only when Coinbase proves the exact order is active,
  local state is terminal, and authoritative fill count is zero;
- `BLOCKED` for absent, ambiguous, unsafe, externally owned, partially filled,
  or otherwise unsupported evidence.

The operator may apply a reviewed terminal local-status repair and may roll it
back only while the exact stored pre-apply and applied terminal states still
match. Local apply and rollback do not call Coinbase.

## Cancel boundary

`CANCEL_ACTIVE_ORPHAN` does not introduce a second exchange adapter. The
frontend passes the backend-issued case id, revision, and plan SHA-256 through
the existing exact-`client_order_id` Cancel proof chain. After ordinary live
admission, the backend atomically claims the case, revalidates local identity,
provenance, product, status, immutable plan, approved portfolio binding, fresh
exact Coinbase order truth, and a documented zero-fill indicator, then
delegates to the canonical Spot Cancel service.

The goal permits at most one Cancel call for the exact selected order. A
pre-boundary rejection releases the claim without consuming the allowance. An
accepted or unknown result after the boundary consumes it; an unknown result
cannot be retried. No Create or unrelated exchange mutation is part of this
goal.

## Durability and public evidence

`operator_spot_recovery_case` and `operator_spot_recovery_event` store case
revision, state, counters, plan, safe rollback snapshot, call allowance, and
append-only events. PostgreSQL row locks and revision checks make claims and
transitions restart-safe and duplicate-resistant. Startup closes an interrupted
refresh as `BLOCKED` while preserving its consumed cycle; it closes an
interrupted Cancel claim as terminal `UNKNOWN` with the one-use allowance
consumed, and never replays either operation. A partial unique index plus a
transaction advisory lock prevents two active cases for the same order.

Public models expose only approved Test binding status, fixed diagnostics,
plan terms, counts, action availability, and allowlisted events. Portfolio
identity is stored as a hash and not returned. Operator reasons are stored as
hashes and not returned. Raw Coinbase responses, response bodies,
exchange-native identifiers, exception messages, secrets, and private
identifiers are outside the contract.

## Routes

- `GET /api/v1/spot/recovery/cases`
- `GET /api/v1/spot/recovery/cases/{case_id}`
- `POST /api/v1/spot/recovery/cases`
- `POST /api/v1/spot/recovery/cases/{case_id}/refresh`
- `POST /api/v1/spot/recovery/cases/{case_id}/apply`
- `POST /api/v1/spot/recovery/cases/{case_id}/rollback`
- `POST /api/v1/orders/{client_order_id}/cancel` with an optional complete
  backend-issued recovery binding

Authentication, RBAC, mutation idempotency, operator intent, audit, and fixed
error classification remain backend-enforced. Ordinary navigation and case
readback are Coinbase-call-free.

## Closeout evidence

- Focused backend recovery validation: `32 passed`.
- Canonical backend regression: `1212 passed, 6 skipped` in the parallel-safe
  lane and `718 passed, 150 skipped` in the serial lane.
- Frontend full suite: `1607 passed`; generated API coverage: `177` paths.
- Authenticated BFF E2E: `8 passed`, including create, exact refresh, local
  apply, and safe rollback through the routed `/spot/recovery` workspace.
- Canonical frontend release gate, installed Controlled-live deployment
  smokes, restart checks, command-security checks, and real PostgreSQL smoke:
  `PASS`.
- Live Coinbase execution during validation: `not_run`; notional: `0 USDC`.
  The optional exact-order Cancel proof allowance remains unconsumed.

Independent safety audit: `PASS`. The final allowlist scan and contract review
found no browser Coinbase path, raw response/body exposure, exception-text
persistence, secret/private-identifier exposure, alternate Cancel adapter, or
R8 access.

Blind contextless audit: `PASS`. The feature is a Spot-specific domain module,
not a reusable cross-domain trading primitive; its API is generated from the
backend OpenAPI contract; operator tracking is by `client_order_id`; admin or
trader actions require backend RBAC and fixed evidence; tests cover claims,
restart recovery, public projection, BFF forwarding, and the routed workflow;
and the only exchange mutation path is the canonical exact-order Cancel
service.
