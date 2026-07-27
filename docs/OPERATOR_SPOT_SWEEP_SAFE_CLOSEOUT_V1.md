# Operator Spot Sweep Safe Closeout V1

Goal `operator_spot_sweep_safe_closeout_v1` provides one authenticated,
operator-reviewed, Cancel-only closeout plan for at most three active
system-owned `BTC-USDC` children in the exact configured `Test` portfolio.
The implemented workflow is local and call-free. It makes zero Coinbase
calls, grants no live-read or Cancel allowance, and has no Create authority.

## Routes and authority

| Route | Permission | Implemented authority |
|---|---|---|
| `GET /api/v1/spot/safe-closeout-sweeps/candidates` | `analytics:read` | Canonical PostgreSQL candidate page |
| `GET /api/v1/spot/safe-closeout-sweeps/current` | `analytics:read` | Goal-global singleton recovery read |
| `POST /api/v1/spot/safe-closeout-sweeps` | `spot_sweep:execute` and `order:cancel` | Persist the singleton immutable plan |
| `GET /api/v1/spot/safe-closeout-sweeps/{sweep_id}` | `analytics:read` | Plan, projection, items, and events |
| `POST .../{sweep_id}/pause` | both mutation permissions | Local revision-bound pause |
| `POST .../{sweep_id}/resume` | both mutation permissions | Local revision-bound resume |
| `POST .../{sweep_id}/abort` | both mutation permissions | Local revision-bound abort |
| `POST .../{sweep_id}/advance` | both mutation permissions | Fixed `409 operator_spot_sweep_live_read_authority_incomplete` |

Readback `allowed_actions` is also RBAC-aware. A reader without either
mutation permission receives no mutation action even when the lifecycle state
would otherwise permit one.

The feature is disabled unless
`COINBASE_ADMIN_API_OPERATOR_SPOT_SAFE_CLOSEOUT_SWEEP_ENABLED=1`. Enabling
Controlled-live or setting `COINBASE_EXECUTION_ENABLED=1` does not clear the
fixed ADVANCE blocker.

The call-free `current` read is the recovery path when a CREATE response is
lost before the browser learns `sweep_id`. It returns the one durable
singleton with GET semantics (`operator_intent=null`) or fixed
`operator_spot_sweep_not_found`; it never replays a POST or calls Coinbase.

## Candidate evidence

Candidate discovery uses canonical PostgreSQL evidence only. Every candidate
has a canonical child and flat root UUID, exact configured portfolio UUID and
SHA-256, product `BTC-USDC`, active child status `PENDING`, `OPEN`, or
`QUEUED`, and provenance `ADMIN_FILL_FOLLOW_UP` or
`ADMIN_HOTPOINT_CHILD`.

Fill-follow-up children require the exact materialization attempt and latest
`CREATE_ACCEPTED_NONTERMINAL` event. The event's exchange-order SHA-256 must
match the current child exchange identity. Hotpoint children require the
canonical Goal 9 goal ID, accepted and invoked Create evidence, unclaimed
Cancel state, valid plan/portfolio evidence, and an exact `rest_submit`
`order_submitted` event linking child, root, product, and current exchange
identity. A Hotpoint parent is normally `OPEN` at placement, but a later
terminal parent does not invalidate an independently active accepted child.

Unknown/latest-nonaccepted materialization outcomes, mismatched evidence,
wrong Goal 9 ownership, duplicate or already-planned children, non-Test
portfolios, non-flat lineage, and unknown provenance fail closed.

Raw exchange `order_id` values are never persisted in the Goal 16 ledger or
returned by the API. A private SHA-256 binding may be stored in the immutable
plan-item table solely as internal exchange evidence; it is excluded from the
public plan payload and `plan_sha256`.

## Ledger and lifecycle

The separate PostgreSQL ledger has immutable plan, plan-item, event, and
command tables plus mutable sweep and item projections. Update, delete, and
truncate triggers protect immutable tables. A goal-global advisory transaction
lock and unique goal ID permit exactly one plan. Commands bind the canonical
payload hash, actor, correlation, idempotency key, intent, revision, and plan.
Each immutable command also stores its sanitized accepted result snapshot.
Exact replay returns that original revision/state/evidence snapshot even after
later commands; changed bindings conflict. Startup fails closed rather than
fabricating history if an upgraded ledger contains a command without its
snapshot, then enforces the result column as non-null.

Plan creation is local cycle 1. Pause, resume, and abort are local cycles with
a maximum of 10. The plan remains immutable. Audit event sequences are
positive, strictly increasing, unique PostgreSQL `BIGSERIAL` values; they may
start above 1 and contain rollback gaps. One committed event exists per sweep
revision, so `revision == len(events)`, while an event sequence is not a
revision number.

Startup installs the schema and runs restart recovery before the cached
service is usable. Any `IN_PROGRESS` sweep or `IN_FLIGHT`/`UNKNOWN` item is
quarantined in one append-only recovery event. Every remaining nonterminal
item becomes `QUARANTINED`; terminal evidence is preserved. Recovery is still
audited if the operator cycle cap is already 10, so revision/event count may
be 11 while `local_cycles_used` remains capped at 10. Recovery never retries
or invents an exchange result.

## Fixed live blocker

The following five allowance categories are always returned in order:

1. `API_KEY_PERMISSIONS`
2. `PORTFOLIO_CATALOG`
3. `PRE_CANCEL_EXACT_ORDER_READ`
4. `CANCEL`
5. `POST_CANCEL_EXACT_ORDER_READ`

Every allowance is `NOT_GRANTED`, non-executable, unconsumed, and has call
count zero. Exact-read, Cancel, Create, total exchange, exchange-cycle, and
page-load call counts remain zero. ADVANCE authenticates and enforces both
permissions, then returns the exact fixed diagnostic before constructing the
Goal 16 service or touching its ledger, runtime, client, or claim.

Live implementation is separate roadmap work. It requires explicit canonical
API-key permission, portfolio catalog, exact pre-read, Cancel, and exact
post-read authority. This goal does not borrow predecessor allowances or
adapters.

## Hash parity

Canonical JSON uses sorted keys, literal Unicode encoded as UTF-8
(`ensure_ascii=false`), and no whitespace.

- Public plan identity is deterministic UUIDv5 over goal ID, configured
  portfolio SHA-256, and the ordered candidate evidence hashes. The public
  plan hash excludes private exchange bindings.
- Mutation payload hashing uses
  `{route, action, sweep_id, body, operator_intent}` with the concrete route
  and uppercase action.
- Fixed CREATE payload vector SHA-256:
  `b5550df7b5be2be6a0513fd79f2d6c2a64d967537589d9fca175a409a08a9888`.
- Fixed PAUSE payload vector SHA-256:
  `cea49c8ce9c5207f1f591720153a7b58e52e9ef417a65b04cd0b01a5aba24c13`.
- Fixed Unicode PAUSE vector (reason
  `Operator reviewed résumé ✅ and astral 🚀 closeout.`) SHA-256:
  `8b75aa374179cf3f17974dc05c9424a0e6f04a19523f44ea61a5cedcbd8ec90c`.
- Fixed two-item plan vector: sweep
  `73485d6b-2133-51ea-8ea0-fbf9e9c15acf`, plan SHA-256
  `24f1f8534e5f29fec96d8c7247bad0e2197b8b67ab0b319e59b35194aa31a304`.

## Legacy source review

Historical `origin/prod` source material reviewed:

- `business/hotpoint_decay_sweeper.py`
- `dashboard_server.py`

The legacy code uses direct/readless Cancel behavior, scheduler loops,
unauthenticated dashboard transport, direct mutation, and no Goal 16
idempotency, audit, or recovery contract. None of those authority paths were
recreated. Only current-main canonical PostgreSQL lineage evidence is used.
