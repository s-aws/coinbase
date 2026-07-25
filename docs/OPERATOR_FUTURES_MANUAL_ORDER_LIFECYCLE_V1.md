# Operator Futures Manual Order Lifecycle V1

Goal ID: `operator_futures_manual_order_lifecycle_v1`.

## Operator outcome

The authenticated Futures workspace provides a normal operator workflow for
one exact US CFM lifecycle: refresh bounded eligibility, review the
backend-derived candidate, explicitly authorize one Preview-gated proof, and
read the durable terminal result. The fixed scope is the credential-bound
`Default` / `DEFAULT` profile, `AVP-20DEC30-CDE`, `BUY`, one contract,
`LIMIT_GTC`, post-only, and strict `<100` opening, `<150` exposure, and `<300`
turnover USDC caps.

Close and Reduce remain unavailable. They belong to the independent Goal 11
position-lifecycle workflow.

## Backend authority

`OperatorFuturesManualLifecycleRepository` owns one PostgreSQL goal row,
revision-bound idempotent commands, at most ten eligibility cycles, one claim
per approved category and cycle, and one-use Preview, Create, reconciliation,
and conditional Cancel states. Every exchange step is durably `CLAIMED` before
its wrapper callback can cross the SDK boundary. Restart recovery converts an
in-flight cycle or call to fixed `UNKNOWN` evidence; it never recreates an
allowance. An accepted Create and its exact reconciliation claim are committed
atomically. An accepted nonterminal reconciliation and its conditional Cancel
claim are also committed atomically. A restart therefore cannot expose an
accepted mutation whose required next step is still unclaimed or replayable.

The first eligible cycle binds the exact permissioned Default portfolio by
SHA-256. Later cycles must match that binding. A server-supplied UUID may
pre-bind the same hash, but a raw portfolio UUID is not required or persisted.
The public contract reports only the hash, fixed profile alias/type, permission
result, call accounting, diagnostics, and audit correlation.

Eligibility invokes these six categories at most once per cycle:

1. API-key permissions.
2. Portfolio catalog.
3. Exact product metadata.
4. Exact product best bid/ask.
5. Futures positions.
6. Futures margin/collateral through the established one balance-summary, one
   intraday-margin-setting, and two official-profile margin-window reads.

There is no retry, fallback, redirect, sweep, Preview, or mutation in an
eligibility cycle. The backend reuses the validated V3 candidate builder and
margin/collateral validator. It binds the credential-permissioned UUID to one
catalog row whose alias/type are exactly `Default`/`DEFAULT`, requires view and
trade permission, zero existing product exposure, exact product/contract
metadata, one contract, the strict caps, and fresh market evidence.

Read-boundary failures persist only a fixed, value-blind category and failure
class. The allowlist distinguishes the exact category plus HTTP authorization,
rate-limit, client/server, timeout, TLS, proxy, connection, schema, or unknown
class using exception type and numeric status only. It never inspects,
persists, returns, or logs an exception message or response body. Dedicated
Goal 10 product and margin readers propagate typed SDK failures directly and
do not use the legacy message-labeling wrappers.

## Preview-gated execution

Execution is available only while the stored candidate observation is no more
than 30 seconds old. A stale, future-dated, missing, or invalid timestamp
withholds the action and fails before a Preview claim.

The backend then:

1. creates one durable claim and canonical `client_order_id`;
2. invokes at most one Futures Preview;
3. validates the shallow pinned-SDK response before recursive normalization;
4. stops on rejected or unknown Preview;
5. passes the ephemeral Preview identity to at most one identical Create only
   after accepted, error-free Preview;
6. reads the exact created order once; and
7. invokes at most one Cancel only when that exact child is authoritatively
   nonterminal.

The canonical wrapper has distinct Futures Preview, Place, and Cancel execution
scopes, rechecks the owner-only execution lease after each durable claim, and
uses the hardened zero-retry/no-redirect bounded transport. Raw Preview and
Create responses, raw Preview identifiers, raw exchange identifiers,
exception messages, secrets, and private portfolio identifiers never enter
PostgreSQL or the generated operator contract. Only fixed outcomes and
SHA-256 identity bindings persist.

Public call accounting uses `call_boundary_entered`. It conservatively proves
that the durable one-use boundary was entered, including the final authority
recheck; it does not overstate that an SDK invocation or HTTP response
necessarily occurred. The fixed outcome and terminal diagnostic provide the
authoritative result classification.

## API and RBAC

- `GET /api/v1/futures/manual-lifecycle` requires `analytics:read`.
- `POST /api/v1/futures/manual-lifecycle/eligibility` requires
  `order:create`, exact no-retry/cycle acknowledgements, revision,
  idempotency key, correlation ID, and fixed operator intent.
- `POST /api/v1/futures/manual-lifecycle/execute` requires both
  `order:create` and `order:cancel`, four exact acknowledgements, revision,
  idempotency key, correlation ID, and fixed operator intent.

Installed execution additionally requires the exact Controlled-live lease,
current decision-backed backend posture, explicit Goal 10 feature flag, and the
dedicated Goal 10 PostgreSQL/candidate gates. The dedicated Futures posture
requires the lease, live runtime flag, Coinbase credentials, Futures-capable
REST client, and current route-specific service decision. It does not depend
on a Spot portfolio, Spot caps, Spot root registrar, or Spot event publisher.
The global service decision’s Spot notional fields are not Futures cap
authority.

## Frontend boundary

The frontend uses generated contracts and the same-origin BFF. It displays
profile, product, contract count, strict caps, cycle budget, candidate
freshness, current execution posture, terminal backend decision, fixed
diagnostics, call outcomes, call-boundary entry, hashed evidence, client order
identity, and audit correlation. Backend RBAC and current posture determine
the returned allowed actions. The frontend forwards only explicit
confirmations and the expected revision. It cannot provide portfolio, product,
side, price, size, cap, Preview identity, exchange identity, retry, fallback,
or alternate child terms.

## Historical source translation

`origin/prod:dashboard_server.py` and
`origin/prod:external/coinbase_client.py` were inspected for historical
Futures/account/order behavior. The modern workflow does not restore the
legacy dashboard WebSocket, generic browser-triggered order path, unbounded
SDK calls, automatic retries, background execution, or raw response display.

## Validation boundary

Focused unit, route, contract, repository/PostgreSQL, frontend runtime, and
workspace tests must pass before full backend/frontend gates. Deployment and
both independent audits must pass before any authorized live call. Validation,
schema generation, navigation, page loading, and readback make no Coinbase
call. The Controlled-live stack remains running at closeout.

## Installed proof result

The installed Controlled-live proof stopped safely after two of ten
eligibility cycles:

- Cycle 1 failed closed with the original generic
  `operator_futures_manual_eligibility_read_unknown` diagnostic after the
  Futures-positions category was claimed.
- Offline TDD remediation added the fixed value-blind category/status
  classifier without changing any existing durable row or allowance.
- Cycle 2 failed closed as
  `operator_futures_manual_futures_positions_http_forbidden`. API-key
  permissions, portfolio catalog, product, best bid/ask, and Futures positions
  were each claimed once; margin/collateral remained unattempted.

The official CFM positions endpoint requires view access. HTTP 403 is an
external credential/account-access boundary, not a response-schema or
candidate-policy defect. No alternate endpoint, credential, retry, fallback,
or remaining cycle was used. Eight eligibility cycles remain unused. No
candidate or Preview claim was created, and Preview, Create, reconciliation,
Cancel, Close, and Reduce all remain `NOT_RUN`. The exact terminal diagnostic
now durably suppresses `REFRESH_ELIGIBILITY`, and PostgreSQL rejects every new
cycle key after restart while preserving idempotent replay of a previously
recorded command.

Terminal closeout passed the 41-test classifier/route/repository focus, both
fresh independent audits, the frontend canonical release gate with 1,707
tests and isolated operator/viewer Futures E2Es, and the full backend
regression (1,282 parallel plus 841 serial passes). Every gate reported zero
live Coinbase execution and zero notional.
