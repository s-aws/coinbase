# Maintainer Handoff

## Completed independent Goal 13 — operator-ready Controlled-live closeout

Goal `operator_futures_hotpoint_canonical_single_child_v2` adds a separate
backend-owned canonical Futures Hotpoint lifecycle to authenticated
`/hotpoint`. It preserves every Goal 9 and Goal 12 row, event, claim,
allowance, identity, and terminal result. Dedicated Goal 13 PostgreSQL goal,
control, command, cycle, candidate, Preview, Create, reconciliation, Cancel,
and audit identities reuse the shared canonical Futures lifecycle
serialization lock and shared exact-child Cancel invocation seal. Ledger
separation must not be described as a dedicated advisory-lock identity.

The fixed scope is the credential-bound `Default` / `DEFAULT` profile,
`AVP-20DEC30-CDE`, BUY, exactly one generated post-only LIMIT/GTC child
contract, and strict `<100 / <150 / <300 USDC` caps. Explicit `RUN_ONCE`
owns at most ten no-retry six-category cycles, including four individually
accounted margin subreads, one Preview, and a conditional identical Create.
Explicit `SAFE_CLOSEOUT` owns one exact one-page List Orders reconciliation
and a conditional exact-child Cancel. Final-page cursors are accepted only
with `has_next=false` and are never followed. Coinbase Cancel success is
request-initiation evidence, not terminal cancellation.

Implementation, generated-contract synchronization, focused and full
backend/frontend gates, installed deployment validation, independent safety
and blind-contextless audits, and persistent Controlled-live handoff pass.
Focused validation passed 266 backend tests and 216 frontend tests. Canonical
regression passed 1,317 backend tests with 6 skipped in parallel and 977 with
150 skipped and 1,323 deselected in serial, plus 1,905 frontend
unit/component tests and 34 authenticated managed browser tests.
The installed stack has no legitimately
registered, reconciled, nonterminal Default-profile AVP source parent with
more than three contracts of remaining capacity. Existing routed Futures
proofs create only one contract and close it, and catalog refresh may
reconcile exchange truth but cannot forge `order_parent` provenance. The
UI shows this durable source blocker and ARM/RUN stop locally before any
eligibility read. The inherited exact-V3 flat-position rule remains a future
eligibility condition rather than a currently evaluated result. All ten
eligibility cycles remain unused, and Preview, Create, reconciliation, and
Cancel remain unconsumed. No Goal 13 Coinbase call or live proof occurred.

The final installed-launcher remediation established the approved
domain-separated Futures Default credential source independently from the
Spot/Test source. Persistent startup accepts no externally configured raw
Futures portfolio UUID, makes no Coinbase call, restricts diagnostics to
fixed allowlisted codes, and withholds arbitrary exception text. If the
source-parent prerequisite is later met, the first authorized
permissions/catalog eligibility cycle resolves the exact credential-bound
`Default` / `DEFAULT` row. It must match that row's SHA-256 to the selected
canonical source parent's process-local portfolio SHA-256 before accepting a
candidate, then atomically binds only the matching hash in the Goal 13 ledger.
Restart and Preview/Create admission revalidate it. Exact closeout sends no
portfolio identifier. The launcher passes no credential value to the
frontend or BFF and does not broaden live authority. Independent safety and
blind-contextless delta audits passed with no P1/P2 finding. Installed
manifests and smoke evidence bind frontend
`252a47bbcf50b261f236e6903b19bb59d7df3038` and backend
`7ebe9de3325d8298c6517b5e6c851f8c1b187b3d`, with Coinbase execution
`not_run` and notional `0`.

Historical translation inspected
`origin/prod:business/hotpoint_detector.py`,
`business/hotpoint_rate_limiter.py`, `business/hotpoint_placer.py`,
`business/hotpoint_decay_sweeper.py`, `dashboard_server.py`, and
`external/coinbase_client.py`. Current official Coinbase Product, BBO,
permissions, portfolio, CFM position/margin, Preview, Create, List Orders,
Cancel, market-hours, and pinned SDK references were compared. No published
post-maintenance breaking change was identified. Current CDP credentials are
portfolio-bound and the documented order-level `retail_portfolio_id` field is
deprecated, so Goal 13 omits that argument and every other portfolio ID from
exact closeout. The authorized eligibility permissions/catalog boundary
establishes the exact credential/catalog match and durable portfolio SHA-256.

Preserve `0/10` and every unconsumed allowance unless an independently
authorized predecessor creates and registers a coherent source parent. The
terminal workflow made no Coinbase call or live proof and did not manufacture
source provenance. See
[Operator Futures Hotpoint Canonical Single Child V2](OPERATOR_FUTURES_HOTPOINT_CANONICAL_SINGLE_CHILD_V2.md).

## Completed independent Goal 12 — operator-ready Controlled-live

Goal `operator_spot_order_truth_and_exact_cancel_reconcile_v1` adds the
approved-Test `CONSUMER` / `SPOT` order-operations workflow. A separate
PostgreSQL ledger owns one goal-global truth cycle and one independent exact
Cancel allowance. The operator must choose whether the single no-retry cycle
performs an `OPEN` catalog refresh or one exact reconciliation. Call-free
list, detail, and actor-bound mutation-result GETs read sanitized PostgreSQL
projections only.

Only a canonical lowercase-UUID, parentless `ADMIN_MANUAL_ROOT` whose local
Test-portfolio and raw exchange-identity hash match the Coinbase observation
can become Cancel-eligible. The browser cannot create or upgrade ownership.
Refresh/reconcile claims API-key permissions, portfolio catalog, and one
logical paginated Spot order catalog once each, with no call or page retry.
Each category and page records its durable claim separately from the wrapper's
immediate pre-SDK `call_boundary_entered` callback. Pre-boundary failures
cannot be reported as Coinbase invocations; post-boundary failures are fixed
unknown evidence.

The goal deliberately does not add a live
`/spot/order-operations/{client_order_id}/cancel` route. The optional strict
Goal 12 revision/evidence/portfolio-hash binding passes through the existing
`POST /api/v1/orders/{client_order_id}/cancel` admission, audit, idempotency,
lease, and canonical Spot Cancel service. A pre-SDK-boundary failure releases
the Goal 12 claim. Accepted, rejected, or unknown evidence after the actual
SDK boundary consumes the independent allowance; restart after that marker is
terminal unknown and never retried.
The Goal 12 service has no `cancel_exact` method, live runner, or unrouted
Cancel helper; the existing command route is the only callable mutation path.

Historical comparison inspected `origin/prod:dashboard_server.py`,
`external/coinbase_client.py`, `database/order.py`,
`database/order_dashboard_helpers.py`, `core/order_engine.py`, and related
legacy tests. Only internal `client_order_id`, durable ownership/hierarchy,
inventory, and exact exchange evidence were retained. WebSocket authority,
client-ID-as-exchange-ID Cancel, generic/batch/background mutation,
retry/fallback, inferred ownership, and raw error/response exposure were
rejected.

The terminal implementation/validation checkpoint is complete. Focused
backend validation passed 242 tests. Canonical backend regression passed
1,294 tests with 6 skipped in its parallel lane, followed by 920 passed,
150 skipped, and 1,300 deselected in its serial lane. Frontend validation
passed 1,829 unit/component tests and 33 full authenticated E2E tests.
Independent safety and blind-contextless audits pass, including the final
remediation delta.

Goal 12 made zero Coinbase calls during implementation, validation, and audit;
its truth-cycle and exact Cancel allowances remain unconsumed. Every immutable
predecessor evidence boundary remains preserved, and R8 content and its hash
remained inaccessible. The canonical release gate, installed deployment, and
persistent Controlled-live status verification pass. The frontend listens on
`0.0.0.0:3000`, the backend remains loopback-only, runtime authority is armed,
and no current service decision or eligible path exists. See
[Operator Spot Order Truth and Exact Cancel V1](OPERATOR_SPOT_ORDER_TRUTH_AND_EXACT_CANCEL_V1.md).

## Completed Goal 6 — Operator Spot recovery execution UI

Goal `operator_spot_recovery_execution_ui_v1` is a distinct successor to
`operator_spot_recovery_and_reconciliation_execution_v1`. The normal
authenticated `/spot/recovery` workflow supports create, exact order/fill
refresh, immutable-plan review, explicit-reason PostgreSQL apply, safe
rollback, and conditional canonical exact-order Cancel.

The migration assigns existing rows to the predecessor goal and adds an
independent `operator_spot_recovery_goal` ledger. Goal 6 owns one goal-global
ten-cycle no-retry refresh budget and one exact Cancel outcome. List, detail,
mutation, and event reads are goal-scoped; predecessor cases cannot borrow or
multiply successor allowances. The predecessor ledger is sealed exhausted
with terminal unknown Cancel authority so even explicit maintenance
instantiation cannot reopen it. Restart converts an interrupted successor
Cancel to terminal `UNKNOWN`.

The frontend requires exact generated Goal 6 fields, rejects predecessor or
contradictory allowance readback, requires explicit operator reasons for
local mutations, and freezes commands after an ambiguous BFF result. It never
derives recovery or exchange authority.

Historical comparison used `origin/prod:business/fill_reconciler.py`,
`origin/prod:core/periodic_reconciler.py`, and
`origin/prod:core/startup_reconciler.py`; no automatic reconciliation,
implicit retry, WebSocket authority, or browser Coinbase path was copied. See
[Operator Spot Recovery Execution UI V1](OPERATOR_SPOT_RECOVERY_EXECUTION_UI_V1.md).

Focused backend/frontend and managed synthetic BFF gates pass with zero
Coinbase calls. Full backend regression passed 1,286 parallel-safe tests with
6 skips and 908 serial tests with 150 skips. The canonical frontend gate
passed 125 files and 1,783 tests plus the complete installed/authenticated E2E
matrix. Independent safety and blind-contextless re-audits pass after typed
Cancel outcome, exact operator-intent, and exact request/readback binding
remediation. All Goal 6 refresh and Cancel allowances are unconsumed.

## Completed operator Futures fill-triggered follow-up activation

Goal `operator_futures_fill_triggered_follow_up_activation_v1` owns a separate
PostgreSQL control and call ledger for one immutable Goal 4 intent. It adds
enable, disable, pause, resume, drain, and status readback on the routed
Futures order detail. Exact source reconciliation persists Coinbase evidence
before an enabled activation can claim `FILLED`, `size=filled_size=1`.

Eligibility and execution use the Default profile, configured Futures product
policy, current one-contract position, fresh passive opposite-side price,
margin evidence, strict `<100 / <150 / <300 USDC` caps, and the canonical
single-use Preview/Create/reconciliation/conditional-Cancel adapter. The
browser supplies no child term or exchange identity.

Maintenance-related API drift remains a separately classified hypothesis.
Schema-invalid evidence is fixed and value-blind and is not mapped to
credentials, entitlement, policy ineligibility, or exchange rejection. See
[Operator Futures Fill-Triggered Follow-Up V1](OPERATOR_FUTURES_FILL_TRIGGERED_FOLLOW_UP_V1.md).

Closeout passed focused contracts, the full backend regression (1,286
parallel-safe plus 896 serial tests), the frontend release/deployment/E2E gate
(1,774 unit/component tests), and both independent audits. The audit
remediation fixed shared lifecycle diagnostic compatibility, made operator
intent and the exact numeric caps mandatory generated readback, and added
restart, global-authority, terminal-idempotency, and full-fill dispatch
coverage. No authoritative fully filled attached intent existed, so Goal 5
made zero Coinbase calls and Preview, Create, reconciliation, and Cancel
remain unconsumed.

## Completed operator Futures follow-up intent attachment

Goal `operator_futures_follow_up_intent_attachment_v1` adds the local
`GET/POST /api/v1/futures/order-operations/{client_order_id}/follow-up-intent`
route pair and the normal authenticated Futures order-detail control.

The backend revalidates an exact configured Default-profile source projection
as `OPEN`, authoritative, one-contract, side-valid, observed, and
exchange-hash-bound. It derives the opposite side, fixes one contract, and
atomically stores one immutable intent/event. PostgreSQL owns source locking,
unique-source duplicate prevention, payload-bound idempotency, root/source
linkage, actor/roles, and audit correlation.

This feature is local in either installed posture: it invokes no Coinbase
client and creates no child. The operator acknowledgements do not become live
authority. Historical comparison used `origin/prod:core/order_engine.py` and
`origin/prod:dashboard_server.py`; no WebSocket or automatic execution path
was copied. The separately authorized Goal 5 owns any later authoritative
fill-triggered activation.

Terminal closeout passed focused contracts, 1,286 parallel-safe plus 890
serial backend regression tests, the complete frontend
release/deployment/E2E gate, and both independent audits. Goal 4 made zero
Coinbase calls.

Current official CFM routes and installed
`coinbase-advanced-py==1.8.4` signatures do not establish a published
maintenance-era break. Goal 5 must still validate documented compatibility
before a live-capable boundary and classify schema drift separately from
credentials, entitlement, maintenance, and V3-policy ineligibility.

## Operator Futures product policy and selected ticket

Goal `operator_futures_product_policy_and_ticket_expansion_v1` adds immutable
PostgreSQL approve/enable/disable/retire/select policy for configured
`AVP-20DEC30-CDE` and `BIP-20DEC30-CDE`, then binds one enabled selection to
fresh Default-profile product, market, position, and margin evidence.

The backend derives one contract, increments, price, documented margin rates,
required margin, and strict `<100 / <150 / <300 USDC` evidence. Policy change
atomically invalidates an unconsumed candidate. Execution revalidates the
current policy under the same advisory lock before claiming one Preview, an
accepted-identical Create, exact reconciliation, and conditional exact-child
Cancel. The UI supplies no trading term or exchange identifier.

The installed operator proof is terminal and fail-closed. Four no-retry
six-category cycles were used. The final sanitized classification is
`operator_futures_product_ticket_margin_window_documented_but_v3_ineligible`:
the official response shape remains documented, but the observed current
window did not satisfy the exact operator V3 profile/state pair. Six cycles
remain unused. No candidate was created and Preview, Create, reconciliation,
and Cancel remain `NOT_RUN`.

## Completed operator Futures order operations

Goal `operator_futures_order_inventory_detail_cancel_reconcile_v1` adds the
canonical `/api/v1/futures/order-operations` route family. PostgreSQL owns ten
no-retry Default-profile catalog cycles, cursor-page claims, sanitized order
projections, the independent one-use Cancel claim, restart recovery, and fixed
audit evidence. UI navigation is call-free. Explicit refresh/reconciliation
uses permissions, Default portfolio catalog, and one logical
`product_type=FUTURE` order read. Cancel resolves one exact raw exchange ID
ephemerally from the fresh catalog and persists only its SHA-256 binding.
Each request correlation is unique and has an authenticated, actor-bound,
call-free mutation-result GET backed by the write-once cycle row. A pending
successful Cancel read is projected as an active transition, so public
`allowed_actions` agrees with the database fence. Immutable historical
mutation results are always projected with execution posture false and no
allowed actions; current authority comes only from the current list/detail
projection.

Historical comparison used `origin/prod:dashboard_server.py` and
`origin/prod:external/coinbase_client.py`. Their WebSocket authority and unsafe
client-ID-as-exchange-ID cancellation were not copied. Official Advanced Trade
List Orders and Cancel Orders contracts and the pinned
`coinbase-advanced-py==1.8.4` wrapper are authoritative. See
[Operator Futures Order Operations V1](OPERATOR_FUTURES_ORDER_OPERATIONS_V1.md).

The terminal installed proof completed cycle 6 successfully with exactly one
permissions read, one Default portfolio-catalog read, and one single-page
`OPEN` Futures order catalog. Four cycles remain unused. No exact Cancel
authority was available, so Cancel remains `NOT_RUN`; no exchange mutation
ran. Independent safety and blind-contextless audits pass. The next authorized
goal is `operator_futures_product_policy_and_ticket_expansion_v1`.

## Current operator credential routing

The prior CFM HTTP-forbidden result is localized to installed credential
routing. One authorized Default-profile read of each of API-key permissions,
portfolio catalog, CFM balance summary, and CFM positions returned. The
Controlled-live runtime now removes direct Coinbase credentials, resolves Spot
from `coinbase/Test`, and builds an independent Futures client from the
`coinbase` Default binding. Missing or conflated bindings fail startup.

The terminal `operator_futures_manual_order_lifecycle_v1` row is preserved.
The routed manual lifecycle now uses the distinct unconsumed
`operator_futures_manual_order_lifecycle_default_profile_v2` row with the same
V3 product, one-contract scope, caps, no-retry categories, and single-use call
boundaries. Goal 11's selected-position coordinator uses the same independent
Default-profile client. Startup and ordinary readback remain Coinbase-call
free. See
[Operator Coinbase Domain Credential Routing V1](OPERATOR_COINBASE_DOMAIN_CREDENTIAL_ROUTING_V1.md).

## Completed independent Goal 11 — Futures position Close/Reduce

Status: `complete_operator_workflow_cfm_access_blocked_allowances_unconsumed`.
Current action:
`complete_goal11_position_lifecycle_cfm_access_blocked_allowances_unconsumed`.
Default action: `await_operator_direction_for_next_mvp`.

Goal `operator_futures_position_close_reduce_and_reconciliation_v1` is the
canonical selected-position workflow in `/futures`. PostgreSQL owns the
goal-global ten-cycle eligibility ledger, exact opaque position binding,
revision/idempotency, one mutually exclusive Close-or-Reduce claim, exact
order and position reconciliation, conditional exact-order Cancel, restart
recovery, fixed diagnostics, and audit readback.

Command idempotency is payload-bound to selected position, expected revision,
action mode, actor/roles, intent, and confirmations; conflicting reuse fails
closed.

The eligibility reader invokes only API-key permissions, Default portfolio
catalog, Futures positions, product, best bid/ask, and the established
margin/collateral snapshot once each. The backend derives LONG/SHORT close
side and action size. Full Close calls the documented Close Position endpoint
with size omitted; bounded Reduce supplies exact size `1` only when more than
one contract exists. Coinbase's direct and nested position response shapes
are accepted only after exact product/contract validation. Raw responses,
private portfolio identity, raw exchange identifiers, and exception text are
never persisted or exposed.

Production CFM position rows can omit portfolio UUID. Their public
`position_key` therefore uses the credential-scoped Default-profile namespace,
while the configured Default portfolio UUID is separately verified and
SHA-256-bound; any conflicting returned private identity fails closed. Close
acceptance uses only the documented success flag and nonblank order ID, then
exact-order reconciliation proves client identity, product, side, and status.

The historical installed process failed the documented CFM positions category
with `operator_futures_manual_futures_positions_http_forbidden`; all Goal 11
allowances therefore remain unconsumed. The follow-up diagnosis proved
Default-profile CFM access and corrected the local credential route. A fresh
operator-triggered eligibility cycle, not the historical 403, now determines
whether an authoritative position is actionable.

Closeout passed the canonical backend regression (`1,282 passed, 6 skipped`
parallel-safe; `852 passed, 150 skipped` serial), the canonical frontend
release gate (`1,712` unit tests plus the complete installed/browser suite),
focused PostgreSQL and contract validation, independent safety audit, and blind
contextless audit. No Coinbase call or exchange mutation ran.

Historical comparison used `origin/prod:dashboard_server.py` and
`origin/prod:external/coinbase_client.py` for refresh and close-side context.
The current documented Close Position, Get Futures Position, and Cancel
Orders endpoints and `coinbase-advanced-py==1.8.4` are the execution contract.
Legacy WebSocket authority, generic commands, background execution, retry,
fallback, and browser-side trading were not restored. See
[Operator Futures Position Close/Reduce V1](OPERATOR_FUTURES_POSITION_CLOSE_REDUCE_V1.md).

## Completed independent Goal 10 — Futures manual order lifecycle

Goal `operator_futures_manual_order_lifecycle_v1` is the canonical Futures
order workflow surfaced in the routed `/futures` workspace. PostgreSQL owns
the ten-cycle eligibility ledger, exact Default-profile hash binding,
immutable V3 candidate, 30-second execution freshness, revision/idempotency,
one-use Preview/Create/reconciliation/conditional-Cancel calls, restart
recovery, fixed diagnostics, and audit readback. The backend alone fixes
`AVP-20DEC30-CDE`, BUY, one contract, post-only LIMIT/GTC, and strict
`<100/<150/<300 USDC` caps.

The first eligible permission/catalog observation binds the exact
credential-bound Default portfolio by SHA-256; no raw UUID is persisted or
returned. The generated operator contract exposes candidate terms and
freshness, dedicated Futures execution posture, fixed call outcomes,
conservative call-boundary entry, hashed Preview/exchange evidence,
`client_order_id`, and audit correlation. Allowed actions are recomputed from
backend RBAC and current posture. Accepted Create atomically claims exact
reconciliation; accepted nonterminal reconciliation atomically claims
conditional Cancel, closing both restart gaps without retry authority.

Historical comparison used `origin/prod:dashboard_server.py` and
`origin/prod:external/coinbase_client.py` as behavior references only. The
current path does not restore legacy WebSocket authority, generic placement,
retry/fallback, background execution, or raw response handling. See
[Operator Futures Manual Order Lifecycle V1](OPERATOR_FUTURES_MANUAL_ORDER_LIFECYCLE_V1.md).

Installed proof closeout used two of ten no-retry eligibility cycles. Cycle 1
ended with the pre-remediation generic read-unknown diagnostic. After an
offline TDD-only fixed category/status classifier was installed, cycle 2
localized the same boundary to
`operator_futures_manual_futures_positions_http_forbidden`: the first five
category claims were used and margin/collateral remained unattempted. Official
Coinbase documentation requires view access for the CFM positions endpoint,
so no code correction, alternate endpoint, retry, fallback, credential change,
or remaining cycle was justified. Eight cycles, Preview, Create, exact
reconciliation, conditional Cancel, and all notional allowances remain
unconsumed. A later live Futures proof requires compatible CFM credential and
account access; it does not require a broader trading policy. The persisted
403 diagnostic durably removes refresh authority and rejects every new cycle
key after restart, while prior idempotent command replays remain readable.
Dedicated Goal 10 product and margin readers propagate typed/numeric-status
failures without using legacy exception-message classification.

Terminal closeout passed both fresh independent audits, the 41-test focused
safety suite, the canonical frontend release gate (1,707 tests and isolated
operator/viewer Futures E2Es), and the full backend regression (1,282 parallel
plus 841 serial passes). Every validation gate reported zero live Coinbase
execution and zero notional.

## Completed independent Goal 9 — Hotpoint control and single placement

Goal `operator_hotpoint_control_and_single_placement_v1` adds routed,
authenticated Hotpoint controls backed by separate Spot and Futures
PostgreSQL control tables and one shared goal-global Create allowance. Spot is
fixed to Test/BTC-USDC and `3.10/1.00 USDC`; Futures is fixed to
Default/AVP-20DEC30-CDE, one contract, and strict V3 `<100/<150/<300 USDC`
caps. Readback exposes the kill switch, bounded window, goal-global rate
limit, recent placement, adapter availability, call accounting, and exact
child without exposing private portfolio or exchange evidence.

The implementation consulted `origin/prod` Hotpoint detector, rate limiter,
placer, decay sweeper, and dashboard handlers. It does not restore the legacy
WebSocket authority, background fan-out, in-memory-only rate state, raw
exception text, or domain-generic exchange adapter. Futures remains
call-free until its separate canonical lifecycle is activated.

The installed Controlled-live runtime preserves operator visibility when the
private Default-profile portfolio binding is not configured: Futures returns
its fixed product/cap policy, zero eligible parents, no allowed actions, and a
fixed not-configured diagnostic. This readback is call-free and cannot create
a placeholder binding or actionable Futures database state.

## Completed independent Goal 8 — Fill-triggered follow-up activation

Goal `operator_fill_triggered_follow_up_activation_v1` connects one
previously attached intent to the existing order-engine full-fill boundary.
PostgreSQL owns revision-bound enable/disable/pause/drain controls,
authoritative source and fill-ledger revalidation, a single trigger claim,
terminal classification, exact child linkage, restart recovery, and audit.
The winner delegates through the existing canonical follow-up materializer
with Goal 8's distinct exchange-call ledger; no parallel Create path exists.

The order-engine interlock treats every attached intent as managed even while
disabled, paused, drained, blocked, or unknown, so it cannot fall through to
legacy automatic follow-up behavior. A full-fill claim also requires zero
partial-fill children. The Admin API exposes sanitized activation and
materialization readback, local control commands, and only the exact child's
conditional safe-closeout route.

Historical source comparison used `origin/prod:core/order_engine.py` for
full-fill and partial-fill event-flow context. It did not copy legacy
dashboard authority, implicit activation, partial-fill fan-out, retries, or
child-term derivation outside the canonical backend service.

Goal 8 closeout passed canonical backend regression (`1,282 passed, 6
skipped` parallel; `819 passed, 150 skipped` serial), frontend full regression
(`1,692/1,692`), Playwright (`23/23`), generated-contract coverage for `214`
paths, the canonical release and installed deployment gates, and independent
safety plus blind-contextless audits. The final concurrency audit proved that
one advisory-lock interval covers claim, canonical materialization, and
activation terminal persistence without a recovery gap.

A read-only count check found zero attached intents and zero exact full-fill
candidates. No Coinbase call or exchange mutation ran, so Goal 8's one Create
and conditional exact-child Cancel allowances remain unconsumed.

## Completed independent Goal 7 — Revealed-order movement and repricing

Goal `operator_revealed_order_movement_and_repricing_v1` continues one exact
Goal 6 revealed placement through backend-owned plan and execution routes.
PostgreSQL binds the definition revision/hash, approved Test-portfolio hash,
source/root/replacement `client_order_id` values, immutable quantized
post-only terms, strict profitability and `3.10/1.00 USDC` caps, one
single-use Cancel/conditional Create allowance, exact read accounting,
command-cycle evidence, exact replay, fixed operator-intent payload binding,
and restart recovery.

The active replacement size is read from the exact chain-linked
`order_parent` placement, not `stealth_orders.remaining_size`; the latter is
the still-hidden quantity and is zero for a real `REVEALED` state. Source and
root rows must prove exact identity, nonterminal state, system ownership, and
the approved Test portfolio before planning or execution can proceed.

The runtime delegates both exchange mutations to typed
`StealthOrderManager` entry points. It requires exact authoritative source
readback before and after Cancel, permits Create only after `CANCELLED`, and
requires documented exact-zero-fill evidence on both reads. The manager binds
the canonical `order_parent` target without fallback and durably persists a
background-mutation fence before Cancel. Before Create it performs a
non-configurable, durably claimed full-wallet read without cancelled-source
credit, while PostgreSQL independently requires same-cycle returned evidence.
It reconciles only after readback proves the exact frozen replacement terms and
retains a placement-level block against legacy background
repricing/cancel-reentry.
The Order Engine `CANCELLED`, `FILLED`, and partial-fill paths check that same
block before registration, carry claims, pending-move, or automatic follow-up
handling, preventing a racing exchange event from creating an unauthorized
child. The final follow-up creation boundary owns a typed `FOLLOW_UP` mutation
claim mutually exclusive with Goal 7 `MOVE`, closing the check-then-act race.
Required Stealth and reveal-history writes must each affect exactly one
PostgreSQL row; fixed unknown evidence replaces raw persistence exception text.
Raw exchange identities remain in-process only and are hash-withheld from
PostgreSQL and operator readback.
Historical comparison covered `origin/prod:dashboard_server.py` and
`origin/prod:core/stealth_order_manager.py`. See
[Operator Revealed Order Movement and Repricing V1](OPERATOR_REVEALED_ORDER_MOVEMENT_AND_REPRICING_V1.md).

Goal 7 closeout passed `65` focused backend tests, `92` focused frontend
tests, the canonical backend regression (`1,294 passed, 6 skipped` parallel;
`908 passed, 150 skipped` serial), the canonical frontend release gate
(`1,786/1,786` unit/component tests and `32/32` managed Playwright scenarios),
installed deployment validation, and independent safety plus
blind-contextless audits. Validation used synthetic no-network exchange
boundaries and made zero Coinbase calls or exchange mutations.

## Completed independent Goal 6 — Stealth reveal and exact closeout

Goal `operator_stealth_reveal_and_exact_closeout_v1` is the sixth goal in the
authorized eleven-goal sequence. The routed `/stealth` workflow now has a
separate generated execution contract for one exact definition. PostgreSQL
owns definition revision/hash, Test-portfolio hash, canonical root
`client_order_id`, frozen plan, ten combined command cycles, no-retry read
claims, one-use Preview/Create/Cancel allowances, and restart-unknown
recovery.

The final Goal 6 hardening directly enforces both installed notional ceilings
before Preview and again before Create, binds the full reveal/profitability
plan rather than a scalar subset, withholds the raw exchange identity from
WebSocket hooks/events, and persists exact terminal command-cycle evidence.
The UI clears a lost-response freeze only for a matching completed cycle and
keeps `IN_FLIGHT` evidence fail-closed.

The runtime uses the canonical manager but adds a one-use explicit operator
capability. Background bridge evaluation cannot reveal an operator-
materialized row. Accepted Preview terms receive no later market read,
post-only retry, repricing, alternate identity, or hook mutation. Exact
closeout performs portfolio and order readback before the single Cancel and
does not mark local state terminal until authoritative post-Cancel evidence.
GET readback is call-free and initializes neither SDK nor runtime.

Historical comparison covered
`origin/prod:core/stealth_order_manager.py`,
`origin/prod:business/stealth_reveal_strategy.py`,
`origin/prod:bridges/stealth_order_bridge.py`,
`origin/prod:dashboard_server.py`, and
`origin/prod:external/coinbase_client.py`. Backend design:
[Operator Stealth Reveal and Exact Closeout V1](OPERATOR_STEALTH_REVEAL_AND_EXACT_CLOSEOUT_V1.md).

## Completed independent Goal 5 — Stealth definition lifecycle

Goal `operator_stealth_definition_lifecycle_v1` translates the legacy stealth
create/cancel/export/import/clear/threshold/target-movement handlers into a
normal routed lifecycle for definitions that have not entered the runtime.
PostgreSQL owns approved-portfolio hashing, active Product Catalog admission,
identity, exact revisions, command result snapshots, import previews, events,
restart recovery, and the canonical-runtime interlock.

The workflow supports list/detail/create/edit/cancel, exact-set clear/export,
and one-use preview/apply import. A matching canonical `stealth_orders` row
blocks local mutation and routes active or terminal evidence to
reveal/closeout and revealed evidence to movement/repricing. Missing or unknown
runtime evidence fails closed. The browser verifies exact durable
postconditions and freezes mutations after an unknown or unverifiable result.
No evaluator, bridge, manager, SDK, or exchange adapter is invoked. See
[Operator Stealth Definition Lifecycle V1](OPERATOR_STEALTH_DEFINITION_LIFECYCLE_V1.md).

Historical comparison covered `origin/prod:dashboard_server.py`,
`origin/prod:core/stealth_order_manager.py`, and
`origin/prod:database/order.py`. The next independent goal is
`operator_stealth_reveal_and_exact_closeout_v1`.

## Completed independent Goal 4 — Parent strategy management

Goal `operator_parent_order_management_v1` is the active fourth independent
goal. It translates the legacy parent CRUD and target-movement handlers into
an authenticated, revision-bound PostgreSQL workflow with an allowlisted
parent/child policy, approved Test-portfolio hash, active Product Catalog
admission bound to the exact Goal 3 revision/hash under lock, exact stored
replay results, durable accepted/rejected command audit, root-interlocked
dependency-aware deletion, restart recovery, and typed fixed audit readback.
The routed Admin UI supports
list/detail/create/edit/deactivate/delete and freezes after an unknown or
unverifiable command outcome, including ambiguous 5xx/BFF 502 results. It makes
zero Coinbase calls or exchange mutations. See
[Operator Parent Order Management V1](OPERATOR_PARENT_ORDER_MANAGEMENT_V1.md).

Closeout passed backend canonical regression
(`1,215 passed, 6 skipped` parallel; `783 passed, 150 skipped` serial),
frontend full regression (`1,655/1,655`), Playwright (`22/22`), generated
contract coverage for `195` paths, the canonical release and installed
deployment gates (`229` deployment-focused tests), and independent safety plus
blind-contextless audits. Validation made zero Coinbase calls and zero exchange
mutations. The next independent goal is
`operator_stealth_definition_lifecycle_v1`.

## Completed independent Goal 3 — Product Catalog administration

Goal `operator_product_catalog_administration_v1` is complete and implements immutable
PostgreSQL catalog revisions, a shared ten-cycle no-retry List Products budget,
page claims, exact metadata-diff review, approval, per-product administrative
lifecycle, rollback-as-new-revision, restart recovery, and fixed audit
readback. The route inventory binds the workflow to `account_management`; the
browser receives generated contracts and cannot grant trading authority.
Installed startup requires the review-manager-provided exact
`COINBASE_ADMIN_API_OPERATOR_PRODUCT_CATALOG_ENABLED=1` feature flag. See
[Operator Product Catalog Administration V1](OPERATOR_PRODUCT_CATALOG_ADMINISTRATION_V1.md).

Closeout passed canonical backend regression
(`1,214 passed, 6 skipped` parallel; `762 passed, 150 skipped` serial), the
frontend canonical release/deployment gate, and independent safety plus
blind-contextless audits. It made zero Coinbase calls and zero exchange
mutations; all ten production refresh cycles remain unconsumed. The next
authorized independent goal is `operator_parent_order_management_v1`.

## Completed independent Goal 2 — Fill ledger and inventory repair

`operator_fill_ledger_and_inventory_repair_v1` adds an authenticated
PostgreSQL repair case service for one exact system-owned `client_order_id`,
approved `BTC-USDC` product, or bounded time window. It durably claims one
no-retry logical fill catalog per cycle, produces an immutable missing-fill
plan and FIFO inventory/cost-basis/P&L projection, imports only missing hashed
fill identities, and rolls back only the exact import batch. Exact fill/alias
ownership and full scoped-ledger hashes are checked under the product advisory
lock shared by every production fill writer; the saved pre-apply projection
and its source case have one combined snapshot hash. Pre-binding legacy
snapshots remain explicitly unverified and non-rollbackable rather than being
trusted during migration. Public response and diagnostic evidence is
fixed-allowlisted. Historical
comparison references were `origin/prod:business/fill_ledger.py`,
`origin/prod:business/position_lot.py`, and the fill pipeline in
`origin/prod:core/order_engine.py`. See
[`OPERATOR_FILL_LEDGER_AND_INVENTORY_REPAIR_V1.md`](OPERATOR_FILL_LEDGER_AND_INVENTORY_REPAIR_V1.md).
Closeout passed backend canonical regression (`1,213 passed, 6 skipped`
parallel; `747 passed, 150 skipped` serial), frontend full regression
(`1,621/1,621`), Playwright (`20/20`), the canonical release and installed
deployment gates, and both independent audits. No Coinbase call or exchange
mutation ran; the ten-cycle fill-read allowance remains unconsumed.

Independent Goal 1 Spot recovery is complete; its optional exact-order Cancel
allowance remains unconsumed.

## Current V13-V15 transport-explainability goal

`operator_spot_automation_transport_explainability_and_successor_proof_v13_v15`
passed validation, installed deployment checks, safety audit, and blind audit.
V13 is terminal at `TRANSPORT_UNKNOWN` after one successful no-HTTP DNS/TCP/TLS
sequence, one eight-category cycle, eight exact eligibility reads, and one consumed Preview
allowance with exact wire count withheld. Create and Cancel remain unconsumed.
V14/V15 remain unused and fail-closed: official Coinbase, pinned SDK, and
Requests documentation provide no concrete correction for the generic
connection boundary. See
[`OPERATOR_SPOT_AUTOMATION_TRANSPORT_EXPLAINABILITY_V13_V15.md`](OPERATOR_SPOT_AUTOMATION_TRANSPORT_EXPLAINABILITY_V13_V15.md).
Current action: `close_v13_transport_unknown_v14_v15_unused`.

## Terminal V10-V12 atomic-snapshot goal

`operator_spot_automation_atomic_market_snapshot_binding_and_successor_proof_v10_v12`
is terminal after V10-V12. Each candidate completed eight exact reads,
atomically bound final terms, and consumed its distinct Preview allowance at
terminal `TRANSPORT_UNKNOWN`, with exact Preview wire count withheld. The
aggregate ledger is 3/10 cycles and 24 exact reads. Create and Cancel remain
unconsumed with zero calls and no exchange mutation.
Backend policy revision 5 derives final
price, size, fee-reserved cap, plan/child identities, evidence, and the
single-use Preview claim from one fresh documented Get Market Trades snapshot
and commits them with the eight-read ledger in one PostgreSQL transaction.
The canonical command service independently requires post-only BUY at the
exact same-snapshot bid and both actual notionals strictly below 3.10 USDC.
The V12 correction uses the pinned SDK exception type and response status
family only: client, server, and blocked-redirect responses prove one exact
Preview call without inspecting the message or body; all other invocation
exceptions remain inexact `TRANSPORT_UNKNOWN`. The generated Admin UI sends
acknowledgements only. V12 is distinct rather than a V10 or V11 retry, and no
successor remains. The append-only V12 event chain begins at the atomic
Preview-claim transaction and is projected without rewriting stored events.
See
[Operator Spot Automation Atomic Market Snapshot V10-V12](OPERATOR_SPOT_AUTOMATION_ATOMIC_MARKET_SNAPSHOT_V10_V12.md).

This guide is the backend entry point for maintainers and contextless agents
working on the enterprise admin platform.

## Current Handoff State

Goal
`operator_spot_automation_minimum_size_explainability_and_successor_proof_v7_v9`
is complete at `complete_terminal_eligibility_cycles_exhausted_v7`.
Current action: `complete_v7_cycle_10_best_bid_ask_rejected_preview_create_cancel_unconsumed`.
Default action: `await_operator_direction_for_next_mvp`.
Policy `BTC_USDC_POST_ONLY_BEST_BID_MINIMUM_SIZE_V2` is backend-owned and
derives the smallest valid post-only fresh Get Market Trades best-bid terms and
fee-reserved execution cap strictly below 3.10 USDC. Six-category preparation
and eight-category eligibility share `10/10` durable no-retry cycles. Cycles
1–5 remain immutable generic `automation_minimum_size_preparation_unknown`
records with zero completed categories and conservatively withheld exact call
count; the first approved category was not confirmed. Cycle 3 exposed an
unprotected REST-client method lookup, and cycle 4 exposed response processing
outside the fixed stage envelope. The deployed outer-boundary split classified
cycle 6 as `automation_minimum_size_materialization_unknown` after all six
read categories completed. Schema-only inspection localized two obsolete
fixed-1.00-USDC PostgreSQL CHECK constraints beside the dynamic-cap
constraints. The completed migration removed only those legacy checks. Cycle
7 materialized V7 with the dynamic 1.01-USDC cap. Cycles 8–10 each used five
exact reads and stopped at Get Market Trades `BEST_BID_ASK` after four
successful categories. The terminal backend readback is
`automation_spot_eligibility_cycles_exhausted` with no action.
Preview/Create/Cancel calls are `0/0/0`; all allowances remain unconsumed, no
child exists, and V8–V9 were not created. See
[Operator Spot Automation Minimum Size V7-V9](OPERATOR_SPOT_AUTOMATION_MINIMUM_SIZE_V7_V9.md).

### V4 near-market predecessor handoff

Goal
`operator_spot_automation_near_market_policy_and_successor_proof_v4_v6`
is complete at `complete_terminal_no_valid_size`. Current action:
`complete_v4_no_valid_size_preview_create_cancel_unconsumed`.
Default action: `await_operator_policy_or_cap_decision`.

The narrow `BTC_USDC_POST_ONLY_BEST_BID_V1` policy and durable V4-V6
preparation path are implemented. The backend alone derives quantized
best-bid `post_only=true` terms and size under product, wallet, fee, and
3.10/1.00 USDC cap evidence. Complete backend regression, the canonical
frontend release gate, installed smoke, and both independent audits pass. The
installed operator workflow completed one V4 preparation cycle and all six
approved read categories with `6` exact Coinbase read calls, then terminated
as `near_market_no_valid_size`. No definition or child exists; goal-global
cycles are `1/10`; Preview/Create/Cancel calls are `0/0/0`, and those
allowances remain unconsumed. V5-V6 were not attempted. A later local
preparation POST failed closed with HTTP 409 before claim creation. See
[Operator Spot Automation Near-Market V4-V6](OPERATOR_SPOT_AUTOMATION_NEAR_MARKET_V4_V6.md).

### Previous Preview-explainability closeout

Goal
`operator_spot_automation_preview_explainability_and_successor_proof_v4_v6`
is complete at `complete_no_documented_successor_correction`. The Preview
classifier now exact-allowlists Coinbase's documented Preview `errs` values and
persists/projects only fixed sanitized rejection categories through
PostgreSQL, OpenAPI, the generated frontend client, and operator readback. See
[Operator Spot Automation Preview Explainability V4-V6](OPERATOR_SPOT_AUTOMATION_PREVIEW_EXPLAINABILITY_V4_V6.md).
Current action: `complete_preview_explainability_v4_v6_allowances_unconsumed`.

V3 retained only its broad documented-rejection class, so the exact enum is
not recoverable without prohibited raw-response access. Its sanitized
`10,000 USDC` BUY limit also cannot be moved near market without changing the
installed standing-price policy. Goal-global V4-V6 eligibility cycles are
`0/10`; Preview/Create/Cancel calls `0/0/0`; all successor allowances remain
unconsumed. The stop boundary is `no documented correction remains`. No
Coinbase call or exchange mutation occurred in this goal. Default action:
`await_operator_policy_decision`.

The active eight-category proof budget remained unused (`0/10`) because the
stop condition applied before candidate creation.

### V3 predecessor terminal record

Goal `operator_spot_automation_documented_market_freshness_successor_v3` is
complete and terminal. The V3 market category is one no-retry authenticated
Get Market Trades request for exact `BTC-USDC`, `limit=1`; the matching trade's
Coinbase event time must pass the unchanged 30-second guard; V3 alone permits
at most one second of positive Coinbase-to-host clock skew while retaining the
original event time and clamping expiry to 30 seconds. Other sources retain
zero future tolerance. The best bid/ask must come from that same response.
Receipt time and unrelated
proxy fields remain forbidden. See
[Operator Spot Automation Documented Market Freshness V3](OPERATOR_SPOT_AUTOMATION_DOCUMENTED_MARKET_FRESHNESS_V3.md).
Status: `complete_terminal_preview_rejected`.
Current action: `complete_v3_terminal_preview_rejected_create_cancel_unconsumed`.
Default action: `await_operator_direction_for_next_mvp`.

The one distinct V3 candidate completed eight no-retry eligibility cycles with
exact read distribution `8, 8, 8, 5, 8, 5, 8, 8` (`58` reads). Cycle 8 was
exactly eligible. One Preview was claimed and invoked once, then terminated as
`automation_spot_preview_rejected` with allowlisted `REJECTED` /
`DOCUMENTED_REJECTION` evidence and warning-present readback. Preview identity
retention is `UNAVAILABLE`; raw response and withheld text were not retained.
Create and Cancel were not reached, no child exists, and no action remains.
Canonical terminal marker: V3 eligibility cycles `8/10`; exact Coinbase reads
`58`; Preview/Create/Cancel calls `1/0/0`; allowances
`consumed/unconsumed/unconsumed`; allowed actions `0`.

V3 validation evidence: backend full `1182 passed, 6 skipped` parallel and
`669 passed, 150 skipped` serial; frontend full `1565 passed`; E2E `15/15`;
build, typecheck, lint, generated-contract, command-security, and release gates
`PASS`; independent safety and blind-contextless audits `PASS`.
V3 release/deployment gate: `PASS` (canonical rerun complete). All validation
and deployment-smoke phases reported no live Coinbase execution.

### V2 predecessor terminal record

Goal `operator_spot_automation_preview_gated_successor_candidate_v2` is complete.
Status: `complete_terminal_eligibility_cycles_exhausted`.
Current action: `complete_terminal_eligibility_exhausted_preview_create_cancel_unconsumed`.
Default action: `await_operator_direction_for_next_mvp`.

The distinct V2 candidate exhausted all ten no-retry Eight-category cycles
with exact distribution `8, 5, 5, 4, 5, 5, 5, 5, 5, 8`. Durable accounting is
`55` Coinbase reads and zero Preview/Create/Cancel calls. Terminal readback is
`BLOCKED` / `automation_run_blocked`, no actions, no Preview claim, and all
live allowances unconsumed.

The sanitized boundary is Coinbase Best Bid/Ask source-time freshness under
the unchanged 30-second guard. Do not substitute receipt time, Product fields,
or an eleventh cycle without a separately bounded successor decision. V1 and
all predecessor evidence remain sealed.

Validation evidence: backend full `1180 passed, 6 skipped` parallel and
`668 passed, 150 skipped` serial; focused backend `240 passed`; frontend full
`1563 passed`; E2E `15/15`; build, typecheck, lint, generated-contract, and
command-security gates `PASS`; independent safety and blind-contextless audits
`PASS`.
Release/deployment gate: `PASS` (canonical rerun complete).
Every immutable R1-R12 and predecessor artifact byte and documented hash
remains preserved, and R8 content and hash remain inaccessible.
Canonical terminal marker: V2 eligibility cycles `10/10`; exact Coinbase reads
`55`; Preview/Create/Cancel calls `0/0/0`; allowances
`unconsumed/unconsumed/unconsumed`; allowed actions `0`.

### Historical pre-closeout handoff checkpoint

Before terminal closeout, goal
`operator_spot_automation_single_child_execution_adapter_v1` was at an
eight-category, canonical-single-child-execution-implemented,
validation-pending checkpoint. The explicit operator refresh owns a durable goal-global
ten-cycle ledger and eight approved fixed-order/no-retry read categories,
including the account-wide active Spot-order catalog. Exact-run authorization
owns a separate final authorization refresh of the same bound evidence.

The canonical domain-owned one-child Create and exact-child safe-closeout
Cancel coordinators are implemented through typed admission and the existing
Spot command service. Historical checkpoint status was
`canonical_single_child_execution_implemented_validation_pending`; its
checkpoint action was `complete_validation_audits_deployment_and_bounded_live_proof`. No
goal-scoped Coinbase call had run. Eligibility-cycle, final-authorization-read,
Create, and Cancel allowances remain unconsumed. Full validation, independent
audits, installed deployment validation, and the bounded live proof remained
pending. The former source-gated checkpoint and gate counts remain historical.
See [Operator Spot Automation Single-Child Adapter
v1](OPERATOR_SPOT_AUTOMATION_SINGLE_CHILD_ADAPTER.md).

Completed predecessor `operator_automation_control_plane_origin_prod_alignment_v1`
established the PostgreSQL control plane; its historical status is `complete`.

## Scope

The backend repository owns trading behavior, Coinbase integration, guard
checks, authorization, audit evidence, OpenAPI schema generation, and all live
execution authority. The frontend repository at
`/home/developer/coinbase/coinbase-frontend` in the local Linux Docker
workspace owns the browser application and must consume backend-owned
contracts only.

Spot is the first complete product module, not the generic model for futures,
perpetuals, stealth orders, movement/repricing, or future modules.

Historical status: `complete`.
Goal `operator_core_workspaces_origin_prod_alignment_v1` is complete. Its
historical action is `complete_core_operator_workspaces_origin_prod_alignment`;
its historical default was `await_operator_direction_for_next_mvp`. It delivered the persistent
authenticated operator shell and routed Portfolio, Spot Operations, Futures
Operations, Orders-detail, Automation, and System Operations workspaces while
keeping Diagnostics separate.

The one authorized account-reality refresh completed and is consumed and
sealed; its evidence is stale for live eligibility and cannot be rerun under
this goal. No goal-scoped Create, Cancel, or live proof has run. The optional
Spot Create and exact-order Cancel allowances remain unconsumed. Futures is
source-disabled and call-free; its workspace exposes sanitized local evidence
only. At that predecessor closeout, the statement `Automation is GET-only`
meant one local `GET /api/v1/admin/capabilities`; that is historical evidence,
not current successor posture.

Current validation evidence is backend full `1109 passed, 6 skipped` parallel
and `599 passed, 150 skipped` serial, frontend full `1440 passed`, E2E
`13 passed`, and independent safety audit `PASS`. The final blind re-audit is
not claimed as passed; neither are the canonical release gate or final
installed Controlled-live stack verification.

## Start Here

1. Read `AGENTS.md`, then `agent.md`.
2. Read `genai_data/AGENT_MVP_REBUILD_GOAL.md` for current scope and stop rules.
3. Read the frontend canonical goal and Origin Prod Feature MVP Map before
   translating legacy behavior.
4. Read `docs/README.md` for the ordered documentation index.
5. Read `README.admin-api.md` for the Admin API boundary.
6. Read `docs/ADMIN_MODULE_CAPABILITY_MATRIX.md` before changing module scope.
7. Read `docs/plans/ADMIN_API_ROUTE_INVENTORY.md` before adding or changing a route.
8. Read `docs/LIVE_ORDER_SURFACES.md` before any live-order or cancellation work.
9. Read `docs/plans/ADMIN_API_CONTEXTLESS_REVIEW_LOG.md` before declaring a handoff complete.
10. Read the historical autonomous queue only when the operator explicitly
    reactivates phase-range work.

## Subagent Hygiene

Phase-end cleanup is the canonical timing. Close subagents spawned for the
completed phase after their findings have been consumed, remediated, or
explicitly deferred, and close stale or previously unused subagents from
earlier phases or milestones discovered during that sweep. Durable milestone
closeout is a final audit sweep, not the first cleanup point. Do not close a
subagent that is still running required validation, producing required
evidence, or awaiting a user decision. Any intentionally open handoff agent
must have recorded owner, purpose, and expected next action. Record the
phase-end or milestone-closeout sweep result before advancing.

## Backend Authority Rules

- Use one code path per behavior.
- Use `client_order_id` for internal order identity.
- Cancellation remains operator- and local-state keyed by `client_order_id`.
  Authoritative pre-read must prove the exact active `exchange_order_id`, then
  the installed route calls the project wrapper as
  `cancel_order(client_order_id, verified_exchange_order_id=...)` exactly once.
  No retry, identity fallback, or second cancel submission is permitted.
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
  `genai_data/AGENT_MVP_REBUILD_GOAL.md`,
  `docs/plans/ADMIN_API_ROUTE_INVENTORY.md`, and
  `docs/ADMIN_MODULE_CAPABILITY_MATRIX.md`
- keeps backend authority over trading behavior and live execution
- sends frontend work through OpenAPI generation and canonical wrappers
- lists focused backend/frontend checks for ordinary changes and applies the
  current goal's direct-blocker rule before broadening scope
- reserves full backend regression and frontend release gate for durable
  milestone closeout, public/release-candidate handoff, deployment
  approval/closeout, release-hardening closeout, Admin API/backend association
  closeout, or explicit request
- reports live Coinbase execution as not run unless an explicit live phase is
  approved

## Required Gates

Backend changes must pass focused tests and validators for the changed
behavior. Full regression is a durable milestone-closeout, public/release-
candidate handoff, deployment approval/closeout, release-hardening closeout,
Admin API/backend association closeout, or explicit-request gate:

```powershell
python3.13 tools/run_parallel_regression.py --workers 4
python3.13 tools/run_autonomous_work_queue_check.py --summary-only
```

Frontend/API association changes must pass focused frontend checks for the
changed behavior. Full release gate is a durable milestone-closeout,
public/release-candidate handoff, deployment approval/closeout,
release-hardening closeout, Admin API/backend association closeout, or
explicit-request gate:

```powershell
npm run release:gate
```

Live Coinbase execution is not part of normal handoff validation. Terminal R12
grants no live-order authority. If a future, separately authorized scope
permits a live order under complete backend gates, report product, submitted
notional, executed notional, retained inventory, reconciliation result, and
audit ids. Expected fill status does not create a separate approval class.

## Historical handoff records

- Historical completed goal: `operator_follow_up_operations_queue_and_single_live_proof`
  has Status: `complete_zero_candidates`. Current work mode and current/default
  action are `complete_zero_candidates_all_live_allowances_unconsumed`; next
  action is `await_operator_direction_for_next_mvp`. The routed passive
  backend-owned Follow-up Operations workspace is deployed, and focused/full
  validation, deployment validation, independent safety audit, and
  blind-contextless audit passed. Its one-statement local-SQL queue remains
  never live eligibility. The exact post-gate local `materialization_review`
  candidate count is `0`; the passive queue made `0` Coinbase reads, `0` Create
  calls, and `0` Cancel calls. The goal-scoped single-candidate proof claim was
  not created and was not required. Eligibility, reconciliation, Create, and
  Cancel did not run. All one-use proof allowances and all live allowances
  remain unconsumed. The goal authority is closed and grants no continuing
  proof call. A durable terminal-goal seal now makes any later candidate
  non-actionable with fixed reason `follow_up_live_proof_goal_terminal` and
  blocks transactionally before eligibility reads or new proof acquisition,
  while attached-intent navigation and already-existing exact-child closeout
  readback remain available. A preexisting fixed-goal claim makes startup fail
  closed rather than sealing over it. A future proof requires a distinct goal
  identity and explicit operator authorization; the completed identity cannot
  be reopened. Operator wording: Follow-up Operations workspace deployed; exact
  post-gate candidate count 0; all live allowances remain unconsumed. Keep the
  Controlled-live operator stack available; its posture supplies no authority
  from this completed goal.
- Historical completed predecessor: Goal
  `operator_authorize_and_materialize_follow_up_intent` has Status: `complete`.
  The backend-owned, separately acknowledged materialization and exact-child
  safe-closeout paths are implemented and integrated through generated
  contracts. Attachment acknowledgement remains local-only and supplies no
  live authority. The proof found no eligible filled attached intent;
  candidate count: `0`; Coinbase eligibility/reconciliation reads: `0`;
  Coinbase Create calls: `0`; Coinbase Cancel calls: `0`; durable
  materialization attempts/claims: `0`; materialized children: `0`; and
  submitted/executed notional: `0 USDC` / `0 USDC`. There was no unknown live
  outcome and the live-proof allowances remain unconsumed. Synthetic tests are
  not live proof.
  Validation completed with backend focused: `164 passed`; backend canonical
  full: `1102 passed, 6 skipped` parallel and `457 passed, 150 skipped`
  serial, runner status `passed`, live execution `false`, notional `0`;
  frontend focused: `179 passed`; independent safety audit: `PASS`; and
  blind-contextless audit: `PASS`. Its terminal work mode was
  `operator_materialization_terminal_closeout_complete`; current action is
  `await_operator_direction_for_next_mvp`.
- Bounded Controlled-live observation for candidate counting: the audited
  installed operator review stack reported runtime mode `controlled_live`, frontend
  `0.0.0.0:3000`, backend `127.0.0.1:8787`, and approved Test portfolio
  configuration without exposing its identifier. This observation made zero
  Coinbase calls and does not claim final post-closeout deployment health.
  Release, startup, and status made zero Coinbase calls and consumed no
  live-proof allowance.
- Historical R12 terminal: Goal `futures_preview_acceptance_recovery_r12` is
  `complete_terminal_unknown_consumed`. Eligibility cycle 2 completed
  `exact_v3_eligible`, the durable R12 claim was created and consumed, and
  offline claim recovery appended `claim_only_recovery_unknown_consumed`
  without constructing a Coinbase client or factory. The generic
  Preview-attempt counter is conservative: `1` marks the consumed post-claim
  boundary but does not prove network reach. Preview network reach is unknown;
  retry, fallback, redirect, submission, mutation, order, and submitted/
  executed-notional counts are zero. The fractional external market timestamp
  mismatch was remediated before cycle 2 without changing policy or call
  bounds. The runner is source-bound to `R12_RELEASE_READY=False`; no further
  Coinbase call, R13 attempt, or Slice 3/4/5 activation is permitted. The
  separately authorized routed Orders workspace, zero-notional local
  follow-up-intent attachment, and completed materialization successor do not
  change that historical boundary.
  See
  `docs/FUTURES_SLICE_2R12_PREPARATION.md`.
- Historical predecessor: Goal `futures_preview_acceptance_recovery_r11` is complete.
  R11 is consumed, terminal `blocked`, immutable, and cannot be retried. It
  stopped at `remaining_margin_validation` before Preview after all six reads
  ran once; Preview, retry, fallback, redirect, submission, and mutation counts
  remained `0`. The exact boundary is
  `margin_window_type_documented_but_operator_rejected`: row `1`, profile
  `retail_intraday_margin_1`, field `margin_window_type`, value type `string`.
  The immutable R11 file/evidence SHA-256 pair is
  `effb4bd037b853e06da14a0327d71eb8104e2b7edb2f56970b4c47ef855b6061` /
  `548bbb02709c70dc320219bc15520b40ed948309ad09ec0f8af8f812d63bedea`.
  During the completed R12 successor workflow, default API/UI readback did not
  select or open the historical R11 terminal. It bound directly to the fixed
  R12 singleton and returned the strict recovered R12 terminal.
  It grants no schema/acceptance broadening, Slice 3/4/5, or other live
  authority. R12 is governed by its completed terminal boundary. See
  `docs/FUTURES_SLICE_2R11_TERMINAL_DIAGNOSIS.md`.
- Historical post-R10 checkpoint: goal
  `futures_post_r10_preview_compatibility_and_direction_selection` completed the
  prospective separation of the official Preview wire schema from stricter
  project acceptance while preserving immutable R1-R10 history. R8 content/hash
  remain inaccessible, and R10's value-blind terminal category is not
  reinterpreted. That checkpoint granted no successor authority by itself. Its
  ranked recommendation was at most one separately authorized successor after
  all no-live gates passed, then official clarification or parking; ten attempts
  were not warranted. See `docs/FUTURES_POST_R10_COMPATIBILITY_DIRECTION.md`.
- Historical R7 terminal action was
  `await_operator_scope_change_decision_after_slice_2r7_closeout`. R7 ran
  exactly once after focused validation and independent safety plus blind
  audits. Its sole Preview call returned control, then the backend stopped
  blocked with sanitized `preflight_or_preview_blocked:ValueError` before
  accepted Preview evidence was appended. Its file/evidence SHA-256 pair is
  `8e7bdf1a1efa67df9b1081cc8270dc9607e0b8c7285053d06985dcab195115e4` /
  `65791ec5aae8bd9db7c623042e3238f80a54067209aeeb1916801ca1d02369c3`.
  All six fixed reads and Preview are `1`; retry, fallback, redirect, Create,
  Cancel, Close, Reduce, exchange submission, and submitted/executed notional
  are zero; live execution is `not_run`. R7 retains immutable R6 ancestry, the
  unchanged V3 exact pair, one `AVP-20DEC30-CDE` contract, strict
  `<100 / <150 / <300 USDC` caps, and the corrected official Preview
  liquidation schema.
- The derived terminal classification is
  `sdk_returned__post_preview_value_error__before_acceptance`, boundary
  `after_preview_return_before_accepted_evidence_append`, exact-reason status
  `not_persisted_and_unrecoverable`. It is computed from validated immutable
  terminal structure, not persisted in R7, and excluded from the evidence
  SHA-256. It does not prove a schema, cap, available-margin, candidate,
  sealing, or other exact cause. See
  `docs/FUTURES_SLICE_2R7_TERMINAL_DIAGNOSIS.md`.
- The historical recovery goal completed with terminal non-acceptance. R8 is
  terminal blocked and immutable with zero Preview, real Coinbase, AWS-service,
  or mutation calls.
  R9 is also terminal blocked and immutable. All six fixed read categories ran
  once and exactly one Coinbase Preview returned before the first post-return
  `preview_response_validation` stage blocked. Retry, fallback, redirect,
  Create, Cancel, Close, Reduce, exchange submission, and submitted/executed
  notional are zero; Slice 3 remained `not_run`. The R9 file/evidence SHA-256
  pair is
  `5c7dd3f27605b623edc910a87dcc4b6c9ea6621aa9ee63dbfcc4b2994990dacf` /
  `2fd73aa0059da49dfe6c836f6dea29b12158fb3dfbe8abdd6d8f4f0f7d702464`.
  See `docs/FUTURES_SLICE_2R9_TERMINAL_DIAGNOSIS.md` for the complete immutable
  binding and value-blind diagnosis.
- R10 is terminal blocked and immutable. Its one Preview returned before the
  first post-return stage blocked with sanitized category
  `futures_preview_response_economics_invalid`. The file/evidence SHA-256 pair
  is `5dd010a706c61e78454caeec478e05cafb1a50761e9e5a9a3d485051c4efee64` /
  `5121e980ec9da81f44d9a3b14b9bbcaa7bdaf41c99189cd9234cedc08d652005`.
  All six reads and Preview are `1`; retry, fallback, redirect, Create, Cancel,
  Close, Reduce, exchange submission, and submitted/executed notional are zero.
  No normalized Preview, Preview identifier, or seal-ready plan was persisted.
  At that historical checkpoint, default API/UI readback selected this exact
  R10 terminal while preserving R8 through documented-SHA/stat-metadata-only
  validation. See
  `docs/FUTURES_SLICE_2R10_TERMINAL_DIAGNOSIS.md`.
- The standalone and composite R10 entrypoints are permanently hard-false.
  R10 has no remaining Preview authority; no R11 existed at that historical
  checkpoint, and Slice 3 did not run. Its handoff, admission, activation,
  action-journal, read-journal, and terminal artifacts are absent. Never invoke
  any R7-R10 runner again. R11 later consumed its claim before Preview and its
  runner is likewise permanently tombstoned.
- R6 predecessor state: Slice 2 remained blocked after the authorized R6
  attempt was consumed without accepted Preview evidence. The
  consumed immutable R5 file/evidence SHA-256 pair remains
  `4988e23886d218d25be518203676bec4f27a2199a0ed2e7f36d0d7e1d8e6bbf7` /
  `194cdd842944f8a453408051c04ff8e117b6b2b3ab6dcd7b1e78f44f4a5a467f`.
  R6 made exactly one Preview call after the V3 exact profile/state policy
  passed, then stopped with sanitized
  `preflight_or_preview_blocked:ValueError`. Its file/evidence SHA-256 pair is
  `df5959e95ed4a6027e6c0a6980045fc685e7dd201158b39ff5fcc9577bf73904` /
  `bf26fa6b0f67499dea02f337517c1ebd42ae9a20c88fbb5cfbe45e3f30f9e4f9`.
  It persisted no Preview response or seal-ready plan. Retry, fallback, Create,
  Cancel, Close, Reduce, exchange-submission, submitted-notional, and
  executed-notional values are zero; live execution is `not_run`. Do not retry
  R6. Slice 2 is not accepted and Slice 3 remains inactive pending a distinct
  operator scope-change decision.
  The operator subsequently approved that wording and a separate no-live
  migration-aware re-preparation. The S3 migration package restored the exact
  consumed R1-R5 bytes and hashes into the Docker workspace. Their original
  nanosecond mtimes were restored; only physical device/inode bindings may be
  rebound for Docker. Historical EC2 ancestry embedded in consumed evidence
  remains unchanged and must still validate. These facts are predecessor
  evidence for R7; the consumed R6 path must never be retried.
  Focused backend and frontend validation passed. Independent safety and blind
  contextless reviews found one P2 contract issue: OpenAPI initially exposed
  restored/historical device and inode values as independent enums. The
  remediated models emit correlated `allOf`/`oneOf` pairs, generated TypeScript
  preserves those pairs, hybrid identities are test-rejected, and both
  reviewers re-reviewed the remediation with no remaining findings.
- Current goal id: `operator_follow_up_operations_queue_and_single_live_proof`
  (Status: `complete_zero_candidates`).
- Current work mode:
  `complete_zero_candidates_all_live_allowances_unconsumed`.
- Current/default action:
  `complete_zero_candidates_all_live_allowances_unconsumed`.
- Next action: `await_operator_direction_for_next_mvp`; keep historical
  `R12_RELEASE_READY=False`, make no further R12 Coinbase call, and do not use
  the completed goal's unconsumed allowances without distinct authority.
- Historical predecessor slice: Default-profile Futures readback -> exact AVAX US CFM Coinbase
  Preview Order -> immutable operator-visible no-live preview readback. The
  one-shot R1 artifact terminated before
  Preview on `futures_preview_margin_setting_ambiguous`; Preview and every
  exchange/retry/fallback counter are zero, submitted/executed notional is
  `0`, and its evidence SHA-256 is
  `a1b7820aa217b7119a6353a8f4fbffa5227ebfe5e4c8d8a1cde5449d370fc6f0`.
  R1 cannot be retried, and Slice 3 is inactive unless R2 is accepted. The
  operator explicitly authorized official-primary-source enum verification,
  an exact documented-versus-operational allowlist, focused validation,
  independent audit, and—only after those gates—one new immutable R2
  Preview-only attempt. R2 preserves typed bounded margin diagnostics while
  excluding raw account/margin payloads and external exception text. The R2
  artifact was then consumed exactly once and stopped after enum-diagnostic
  capture but before complete candidate/request context or Preview. File SHA-256 is
  `1831b2feaac69b9d3d64377123833831c1b1c1f26c1c0445ed17f334746b4053`;
  evidence SHA-256 is
  `afebf81c4d95c0abd7635fd700f6618e92191423173df3e2db0f875102b6f1c9`.
  Its typed diagnostic proves
  `INTRADAY_MARGIN_SETTING_INTRADAY` is documented and operationally eligible,
  so the enum itself did not block. The exact remaining-margin,
  candidate/request-construction, or context-sanitization condition is not
  persisted and must not be inferred. All aggregate reads are `1`; Preview,
  retry, fallback, mutation, exchange-submission, and notional counters are
  `0`. API readback is HTTP `200` with live execution disabled. R2 cannot be
  retried, Slice 2 is not accepted, and Slice 3 remains inactive pending a new
  explicit operator decision. Offline R3 diagnostic preparation is now
  implemented without creating an R3 claim or artifact and without invoking a
  producer or Coinbase client. A blocked pre-Preview record can carry a hashed,
  strictly ordered stage prefix covering remaining-margin validation,
  candidate construction, Preview-request construction, and terminal-context
  sanitization. Exact internal validation reasons are allowlisted per stage;
  every other exception maps to a fixed stage fallback, and the stage
  diagnostic never persists exception text, type/module, traceback,
  identifiers, or raw input. The optional schema
  preserves exact readback of the consumed R2 evidence, while future evidence
  rejects reordered or authority-expanding diagnostics and diagnostics after a
  Preview attempt.
- The operator granted the proposed R3 authorization. After focused validation,
  synchronized `main` commits (`18f4b04b` backend and `33105b9a` frontend),
  immutable-predecessor checks, and independent safety plus blind contextless
  audits passed, the version-bound R3 command ran exactly once. It stopped
  before Preview at sanitized stage
  `remaining_margin_validation` with reason
  `futures_preview_margin_windows_ambiguous`. The immutable R3 artifact file
  SHA-256 is
  `7ccd5411878842f883b78a99a4103b9b7b1f9aa000ebdde29cdecf2ac894b61c`;
  evidence SHA-256 is
  `e79beb3d9f1324cf8f90ba78cd45869fec5b7963afe3745bd6e26617313718e8`.
  All six aggregate reads are `1`; Preview, retry, fallback, Create, Cancel,
  Close, Reduce, exchange-submission, and notional counters are `0`. API
  readback is HTTP `200` with live execution disabled. R3 is consumed and
  cannot be retried; Slice 2 is not accepted and Slice 3 remains inactive.
- The operator granted the fixed R4 authorization. Backend commit `8435bf0b`
  bound the only production command to R4, the exact immutable R3 -> R2 -> R1
  -> original chain, and a composition facade exposing only the six fixed reads
  plus one exact Preview. The facade exposes no SDK accessor or Create, Cancel,
  Close, Reduce, retry, fallback, or alternate-scope method. Focused tests and
  two independent pre-execution audits passed after adversarial review caused
  raw Preview-response persistence and claim-only terminal failure paths to be
  removed.
- R4 ran exactly once on 2026-07-15 and stopped terminally before Preview at
  `remaining_margin_validation` with reason
  `futures_preview_margin_windows_ambiguous`. The immutable R4 artifact file
  SHA-256 is
  `90691e5b24c17fca5f3d1a67f942ea0b4b067e262435bcdf37e516f79ebb66cf`;
  evidence SHA-256 is
  `0edeffdb0702ba119a7d9c3e32874b75e295ee596538432df5f7be0a67a4af3e`.
  Operational margin-setting evidence resolves the documented token
  `INTRADAY_MARGIN_SETTING_INTRADAY`; the margin-window diagnostic records only
  `margin_window_type_not_exact_operational_enum_token` and withholds the
  unknown value, raw responses, external exception text, and identifiers. All
  six aggregate reads are `1`; Preview, retry, fallback, Create, Cancel, Close,
  Reduce, exchange-submission, submitted-notional, and executed-notional values
  are `0`. No marker, ledger, or runtime was created. R4 is consumed and cannot
  be retried; Slice 2 is not accepted and Slice 3 remains inactive. Any offline
  diagnosis or distinct follow-up attempt requires a new explicit operator
  decision.
- R4 operator-visible closeout selects the R4 artifact by default in Admin API
  GET readback. The terminal readback returns HTTP `200` with live execution
  disabled and the focused frontend diagnostic view passes (`11 passed`). Final
  focused backend Preview/readback coverage passes (`222 passed`), with OpenAPI
  freshness, ownership, Python compile, and diff checks clean. An independent
  post-execution audit recomputed the artifact, evidence, and diagnostic hashes,
  validated the complete predecessor chain and default GET, and returned `PASS`.
  The R4 phase-end subagent sweep found no required reviewer still running.
- The operator then authorized offline-only diagnosis of the consumed R4
  margin-window ambiguity. The exact proven boundary is row `0`, recognized
  profile `retail_regular`, ready row, nested window mapping, present trimmed
  safe string, followed by failure against the singleton operational allowlist
  `{MARGIN_WINDOW_TYPE_INTRADAY}`. R4 intentionally withholds the literal and
  therefore does not prove it, the window end time, kill switches, row `1`,
  sweeps, or final positive-margin evidence. SDK intraday/overnight semantics,
  late-evening timing, the cached official `MARGIN_WINDOW_TYPE_UNSPECIFIED`
  example, and separate `FCM_MARGIN_WINDOW_TYPE_*` values are diagnostic clues
  only; none may broaden the REST allowlist. Focused validation passed `44`
  tests, two independent offline audits agreed with the fail-closed boundary,
  and all five consumed artifacts remained byte-identical. No production code,
  schema, eligibility, R5 artifact, Coinbase call, marker, ledger, or runtime
  was created.
- The following R5 authorization wording was proposed at that checkpoint,
  subsequently granted once, and terminated before its conditional
  implementation/attempt authority activated:

  > AUTHORIZE primary-source-only online verification of the exact Coinbase
  > Advanced Trade US CFM Get Current Margin Window `margin_window_type` enum
  > and its documented profile/state semantics, limited to official Coinbase
  > documentation. Implement versioned, typed, sanitized documented-versus-
  > operational margin-window evidence and an exact profile/state policy only
  > if that primary evidence is unambiguous. Limit that policy to Slice 2
  > Preview eligibility; it grants no Create Order or later live eligibility.
  > Preserve exact V1 readback of the consumed R4 diagnostic, followed by
  > focused validation and independent audit. Effective only after those gates
  > pass, AUTHORIZE one fresh Slice 2R5
  > Preview-only evidence attempt through a fixed one-use R5 entrypoint using a
  > new immutable claim/result artifact bound to the consumed Slice 2R4 artifact
  > with file SHA-256
  > `90691e5b24c17fca5f3d1a67f942ea0b4b067e262435bcdf37e516f79ebb66cf`
  > and evidence SHA-256
  > `0edeffdb0702ba119a7d9c3e32874b75e295ee596538432df5f7be0a67a4af3e`,
  > while preserving and never modifying, deleting, reusing, or retrying the
  > consumed Slice 2, Slice 2R1, Slice 2R2, Slice 2R3, and Slice 2R4 artifacts.
  > Permit the fixed backend-owned permission, portfolio, product, market,
  > position, balance, intraday-margin-setting/window, and sweep preflight
  > reads, plus at most one Coinbase Preview Order call for the permission-
  > selected Default/DEFAULT US CFM AVAX perp-style future AVP-20DEC30-CDE,
  > exactly one contract, actor operator-controlled-futures-proof with BFF role
  > trader, strict opening/reference below 100.00 USDC, maximum exposure and
  > 1.20-buffered close each below 150.00 USDC, and branch turnover below
  > 300.00 USDC. Require the versioned diagnostic to expose an observed token
  > only when it exactly matches the verified documented allowlist; withhold
  > undocumented or malformed values, raw responses, external exception text,
  > and unknown identifiers. Zero retries, fallback calls, redirects, redirect
  > replays, Create Order, Cancel Order, Close Position, Reduce, marker, ledger,
  > replacement runtime, or other exchange-mutation attempts. If the official
  > enum or profile/state semantics are ambiguous, do not implement an allowlist
  > or profile-policy expansion and do not reserve, claim, or create R5. Only
  > after that primary evidence is unambiguous and implementation, focused
  > validation, and independent audit pass may R5 be created. After creation,
  > any ambiguity in predecessor, profile, product, contract, position,
  > margin/collateral, liquidation, freshness, diagnostic, or cap
  > evidence consumes R5 terminally before Preview. Any unknown Preview outcome
  > consumes R5 and may not be retried.
- The operator granted the proposed R5 authorization exactly. Official-only
  verification proved the
  [`Get Current Margin Window`](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/futures/get-current-margin-window.md)
  response enum but failed the authorization's equally mandatory profile/state
  semantics gate. The official generated Markdown defines exactly
  `MARGIN_WINDOW_TYPE_UNSPECIFIED`, `MARGIN_WINDOW_TYPE_OVERNIGHT`,
  `MARGIN_WINDOW_TYPE_WEEKEND`, `MARGIN_WINDOW_TYPE_INTRADAY`, and
  `MARGIN_WINDOW_TYPE_TRANSITION` REST tokens and the regular/intraday query
  profiles; its retrieved SHA-256 is
  `3bcf6504cb092e2565c604ff6938682de2652d662be415612d51a0c28b82db3c`.
  It provides no profile-to-state mapping or operational eligibility
  definition. The
  [official SDK](https://coinbase.github.io/coinbase-advanced-py/coinbase.rest.html#coinbase.rest.RESTClient.get_current_margin_window)
  omits weekend/transition/profile combinations. As verified on 2026-07-15,
  [official Help](https://help.coinbase.com/en/coinbase/derivatives/us-derivatives-leverage-margin)
  says `6pm-4pm ET`, while the official SDK and
  [`Set Intraday Margin Setting`](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/futures/set-intraday-margin-settings)
  documentation say `8am-4pm ET`. The operator subsequently clarified that
  `8am-4pm` applies to futures and `6pm-4pm` applies to perpetuals; these
  schedule descriptions are deliberately not converted into a local clock,
  holiday, or profile-to-state eligibility rule. The different
  `FCM_MARGIN_WINDOW_TYPE_*` balance enum is not REST profile-policy authority.
- The resulting terminal blocker is
  `futures_preview_margin_profile_state_semantics_ambiguous`. Under the exact
  authorization, no allowlist/profile-policy expansion, diagnostic V2, schema,
  R5 path, CLI, claim, or artifact was created. Coinbase API, credential,
  Preview, retry, redirect, fallback, Create, Cancel, Close, Reduce, marker,
  ledger, and runtime attempts are all `0`. Default readback and the production
  command remain fixed to R4. Independent primary-source and safety audits
  returned `PASS` on this fail-closed result. Future work requires either an
  official Coinbase source that unambiguously maps profiles to operational
  states or a new explicit operator-defined Slice-2-Preview-only policy that
  does not claim to be Coinbase-documented behavior.
- The operator then explicitly authorized the second path: a versioned,
  operator-defined, Slice-2-Preview-only policy for both exact REST profiles.
  The V2 policy independently accepts exactly
  `MARGIN_WINDOW_TYPE_OVERNIGHT`, `MARGIN_WINDOW_TYPE_WEEKEND`,
  `MARGIN_WINDOW_TYPE_INTRADAY`, or `MARGIN_WINDOW_TYPE_TRANSITION` for each of
  `MARGIN_PROFILE_TYPE_RETAIL_REGULAR` and
  `MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1`.
  `MARGIN_WINDOW_TYPE_UNSPECIFIED` is documented but rejected. Undocumented,
  malformed, non-string, and unknown profile/state values are withheld and
  rejected. Typed evidence labels the enum authority as official Coinbase
  documentation and the profile/state mapping as
  `operator_defined_slice_2_preview_only_not_coinbase_documented`; it also
  fixes R5-attempt authority, execution allowance, Create eligibility, and
  later-live eligibility to `false`.
- This policy implementation is offline and dormant. It does not alter the V1
  intraday-only R4 classifier, collateral validator, artifact schema, default
  Admin API readback, or production CLI. It does not add an R5 artifact type,
  path, claim, producer integration, credential hydration, Preview call, or
  frontend authority. Consumed R3 and R4 correlation/idempotency identifiers
  were added to the rejection set to prevent accidental reuse. A distinct
  exact authorization is still required before any R5 integration, claim,
  artifact creation, Coinbase read, or Preview attempt.
- Focused TDD validation passes the complete Futures Preview/readback unit file
  (`283 passed`), including `53` policy-focused cases, all `4 x 4` accepted
  profile/state combinations, reversed-row canonicalization, adversarial model
  coherence, identifier-reuse rejection, immutable R4/default readback, and R5
  dormancy. Python compilation, ownership, OpenAPI freshness, and diff checks
  pass. The frontend durable-goal quality test passes (`27 passed`), and its
  goal-alignment, typecheck, lint, and generated API/route freshness checks pass.
- Independent safety, adversarial model, immutable-artifact, and blind
  contextless audits all returned `PASS` after their must-fix findings were
  consumed. The artifact audit revalidated all five consumed artifact hashes,
  exact read-only metadata, zero attempt/notional/mutation counters, R4 HTTP
  payload equality, and R5 absence. The contextless review inspected historical
  `origin/prod` `dashboard_server.py` and `calculation/fee_manager.py`; neither
  contains the exact REST two-profile policy, so no legacy behavior was copied.
  The phase-end subagent sweep found no required reviewer still running.
- Offline R3 diagnostic preparation validation: focused backend Preview and
  Admin API contract coverage passed (`165 passed`), ownership, Python compile,
  OpenAPI freshness, and diff checks passed; focused frontend rendering passed
  (`9 passed`), and typecheck, lint, generated API freshness/route coverage,
  process hygiene, and diff checks passed. Independent adversarial safety and
  blind contextless reviews both finished with `PASS` after their findings were
  consumed. The phase-end subagent sweep found no required reviewer still
  running. No producer, Coinbase client, Preview, retry, fallback, mutation,
  marker, ledger, or runtime ran; submitted and executed notional remain `0`.
- Phase-end subagent sweep: the independent reviews found and caused
  correction of raw-evidence leakage, external exception-text persistence,
  permissive unknown margin-window handling, a stale authority mirror, and
  missing durable primary-source links, plus Preview cap, available-margin, and
  redirect-replay gaps. All causal findings were fixed; final independent
  safety and blind contextless re-reviews plus the consumed terminal artifact
  integrity/retry audit completed with `PASS`, and no required validation agent
  remains running.
- Historical ordered successor design: exact no-live preview (2), one terminal
  order roundtrip (3), intentional fill/position readback (4), then exact
  closeout (5). This ordering is design history, not work authority. Consumed
  blocked R10 granted no successor activation or live authority at that
  historical checkpoint; no R11 existed then, and Slice 3 did not run. R11
  subsequently consumed its claim before Preview and is governed by the
  terminal current-authority block above.
- Previous state: V14 completed the predecessor automatic/live proof for ten
  Test-profile roots and ten first-child submissions under the approved
  `30.00 USDC` reference cap. Every root was authoritatively FILLED, every child
  was authoritatively CANCELLED with zero child fill, every final chain was flat
  with active placement cleared, the final active-order count was zero, and
  shutdown was quiescent. The frontend now binds a selected root to exact
  fill-ledger/audit, exactly-once decision, terminal child, audit workbench, and
  four read-only recovery surfaces without adding mutation authority.
- Legacy translation references inspected: `origin/prod:main.py` for the one
  engine/bridge lifecycle, `origin/prod:core/order_engine.py` for authenticated
  `user` event -> `handle_filled_order` -> follow-up behavior, and
  `origin/prod:core/stealth_order_manager.py` plus
  `origin/prod:dashboard_server.py` for placement lookup, hidden-child creation,
  and historical operator authority. The legacy dashboard WebSocket was not
  reused as product authority.
- Review sweep: independent backend binding, frontend identity, successor-plan
  safety, smoke-artifact, and final cross-repository reviewers completed. All
  causal findings were consumed: synthetic empty-list identity, stale Spot
  Test-profile fixtures, legacy `ready` smoke consumers, and an
  unauthoritative dashboard-fallback assertion. Re-review found no remaining
  blocker or current live authority.
- Final validation: focused backend/frontend gates and independent audit passed
  without an order mutation. The canonical backend regression passed
  `1471/1471` tests (`1015` parallel plus `456` serial), with runtime artifact
  findings null, live execution false, and notional `0 USDC`; evidence is under
  `genai_tools/pytest-tmp/parallel-regression/d1fa4eadc89449b6a2dca5eed51e193a/`.
  The synchronized frontend passed `568/568` unit and `8/8` Playwright tests.
  Its canonical release gate, authoritative Default-account read smoke,
  deployment checks, and managed cleanup all passed with live execution
  `not_run`/false and notional `0 USDC`.
- Parked by default: M57 phase continuation, M58 fan-out/scheduler,
  runtime-control, retry/recovery, multi-product wallet-ledger work, and the
  single-product ladder/grid roadmap item.
- M9/M21/M23/M24/M25/M26 enterprise readiness is exposed by
  `GET /api/v1/admin/enterprise-readiness`.
- Historical policy metadata describes controlled-live Admin continuous
  deployment and defers `7961-7980`; it does not supersede the current goal.

### Historical Phase Snapshot

- Latest completed autonomous range: `7941-7960` under M57.
- Historical queue entry - Active autonomous range: `7961-7980` under M57.
- Historical queue scope: `7961-7980` adds futures risk-proof record validation
  remediation summary evidence derived from existing per-command risk-proof
  record-validation remediation rows. It remains disabled, no-live,
  backend-owned evidence only and cannot perform remediation, create work
  items, register record validators, run contextless reviews, configure
  validation gates, create stores, configure append-only logs, bind
  idempotency, register payload validation, register replay guards, link audit
  evidence, write validation records, write proof records, accept proof
  records, register proof routes, enable proof writers, resolve proof
  acceptance, accept risk proofs, pass command readiness, admit commands, pass
  approval, cap/guard, or reconciliation gates, execute reconciliation, call
  Coinbase, mutate futures/order/exchange state, grant browser/BFF authority,
  or import spot-only rules.
- Completed `7941-7960` added risk-proof record validation summary evidence
  derived from existing per-command risk-proof record-validation rows and
  remains carried-forward disabled, no-live, backend-owned evidence only.
- Completed `7921-7940` added risk-proof record contract summary evidence
  derived from existing per-command risk-proof record-contract rows and
  remains carried-forward disabled, no-live, backend-owned evidence only.
- Completed `7901-7920` added risk-proof payload field summary evidence
  derived from existing per-command risk-proof payload-field rows and remains
  carried-forward disabled, no-live, backend-owned evidence only.
- Completed `7881-7900` added risk-proof contract summary evidence derived
  from existing per-command risk-proof proof contracts and remains
  carried-forward disabled, no-live, backend-owned evidence only.
- Completed `7861-7880` added risk-proof acceptance criterion summary evidence
  derived from existing per-command risk-proof acceptance criteria and remains
  carried-forward disabled, no-live, backend-owned evidence only.
- Completed `7841-7860` added risk-proof acceptance blocker summary evidence
  derived from existing per-command risk-proof requirement rows and remains
  carried-forward disabled, no-live, backend-owned evidence only.
- Completed `7821-7840` added risk-proof record resolver summary evidence
  derived from existing per-command risk-proof requirement rows and remains
  carried-forward disabled, no-live, backend-owned evidence only.
- Completed `7801-7820` added command readiness-decision summary evidence
  derived from existing per-command readiness decision rows and remains
  carried-forward disabled, no-live, backend-owned evidence only.
- Completed `7781-7800` added command risk-proof requirement summary evidence
  derived from existing per-command risk-proof requirement rows and remains
  carried-forward disabled, no-live, backend-owned evidence only.
- Completed `7761-7780` added command semantic-guard summary evidence derived
  from existing per-command semantic guards and remains carried-forward
  disabled, no-live, backend-owned evidence only.
- Completed `7741-7760` added command request-field summary evidence derived
  from existing per-command request fields and validator refs. It remains
  carried-forward disabled, no-live, backend-owned evidence only and must not
  validate payloads, register validators, clear command enablement, or grant
  execution authority.
- Completed `7721-7740` added command prerequisite summary evidence derived
  from existing per-command prerequisites. It remains carried-forward disabled,
  no-live, backend-owned evidence only and must not resolve prerequisites or
  clear command enablement.
- Completed `7701-7720` added command enablement contextless-review blocker
  summary evidence derived from the latest `7681-7700` blind-review result. It
  remains carried-forward disabled, no-live, backend-owned evidence only and
  must not clear command enablement or grant execution authority.
- Completed range validation: PASS after remediation for
  validation-record acceptance contextless-review acceptance evidence and
  bounded command-suite materialized samples. Backend source serialization,
  OpenAPI generation, frontend schema sync, adapter/display, and focused
  futures read-model/mock tests are closed for `7681-7700`. Initial
  blind/contextless review blocked on the untracked registry, stale
  active-range docs, and missing direct frontend assertions. Remediation staged
  the registry, updated active docs and runtime phase metadata, regenerated
  OpenAPI, added direct tests, and reran focused backend/frontend checks. Fresh
  backend/frontend re-review passed, and phase-end subagent cleanup closed the
  reviewer. Full regression remains a durable milestone closeout gate, not an
  ordinary phase gate. No live Coinbase execution was run; submitted/executed
  notional remains `0` USDC.
- Completed range `7661-7680` added validation-record acceptance
  contextless-review evidence derived from the completed validation-record
  acceptance rows. Focused backend/frontend checks passed after remediation for
  stale docs, the staged backend registry, and direct frontend test coverage.
- Completed range `7641-7660` added validation-record acceptance evidence
  derived from the completed source-ref record-acceptance rows. Focused
  backend/frontend checks passed after remediation for stale
  `approved_phase_range` metadata and stale review-log state.
- Prior completed range validation: completed for execution-eligibility
  resolution-plan step review input store record-validation remediation
  dependency work-item claim-trace clearance-step review input store
  record-validation check output schema field-constraint source-ref acceptance
  evidence and bounded command-suite materialized samples.
  Focused backend contract/risk checks, frontend type/API checks, targeted
  frontend unit tests, and autonomous validation passed. Completed `7581-7600`
  record-validation remediation dependency work-item claim-trace clearance-step
  review input store record-validation check output schema field-constraint
  source-ref contextless-review evidence remains carried forward.
  No live Coinbase execution was run; submitted/executed notional remains `0`
  USDC.
- Completed `7581-7600` blind/contextless review: PASS after remediation for
  the newly added validation-check output schema field-constraint source-ref
  contextless-review evidence. Backend reviewer
  `019f0627-830e-77a3-9b59-838303b5b891` initially blocked on stale
  agent-state next actions, review-log status, and example metadata placement;
  frontend reviewer `019f0627-bc35-7f52-bda9-445dc07a7902` initially blocked
  on pending review-log status, premature handoff validation wording, and
  missing mock-backend assertions. Those findings were remediated and both
  reviewers passed re-review. Required boundary: source-ref contextless-review
  rows are backend-owned disabled evidence only; they do not pass contextless
  review, declare source refs, declare constraints, declare field types,
  declare field names, ready validation checks, accept records, admit
  commands, call Coinbase, mutate futures/order/exchange state, or grant
  browser/BFF or spot-rule authority. Live Coinbase execution was not run;
  submitted/executed notional remains `0` USDC. Phase-end stale-subagent sweep
  closed both reviewers after their findings were consumed; no completed,
  failed, superseded, stale, or unused phase-scoped subagent remains
  intentionally open for this slice.
- Completed `7561-7580` blind/contextless review: PASS after remediation for
  the newly added store record-validation remediation dependency work-item
  claim-trace clearance-step review input store record-validation check output
  schema field-constraint source-ref evidence. Backend reviewer
  `019f05ec-6057-7092-9f6e-e863b5fb9e5e` passed the source-ref registry,
  bounded materialization, no-live, no-browser/BFF-authority, and no-spot-rule
  posture. Frontend review initially blocked on mock fixture authority wording,
  missing mock source-ref assertions, and stale pending review-log status; the
  findings were consumed by documenting the mock boundary, adding mock tests,
  updating review evidence, and obtaining frontend re-review PASS from
  `019f05ec-9719-7941-8008-92d2e914d6b1`. Phase-end stale-subagent sweep
  closed both reviewers after their findings were consumed; no completed,
  failed, superseded, stale, or unused phase-scoped subagent remains
  intentionally open for this slice. Required boundary: source-ref rows are
  backend-owned disabled evidence only; they do not declare source refs,
  declare constraints, declare field types, declare field names, ready
  validation checks, accept records, admit commands, call Coinbase, mutate
  futures/order/exchange state, or grant browser/BFF or spot-rule authority.
- Completed `7541-7560` blind/contextless review: PASS after remediation for
  the newly added store record-validation remediation dependency work-item
  claim-trace clearance-step review input store record-validation check output
  schema field-constraint evidence. Required boundary: field-constraint rows
  are backend-owned disabled evidence only; they do not declare constraints,
  declare field types, declare field names, ready validation checks, accept
  records, admit commands, call Coinbase, mutate futures/order/exchange state,
  or grant browser/BFF or spot-rule authority.
- Completed `7521-7540` blind/contextless review: PASS after remediation for
  the newly added store record-validation remediation dependency work-item
  claim-trace clearance-step review input store record-validation check output
  schema field-type evidence. The frontend review initially blocked only
  because review logs still led with `7501-7520`; the backend review passed after stale assertions were remediated.
  The review-log remediation made `7521-7540` the leading entry and the
  phase-end stale-subagent sweep closed the backend and frontend reviewers.
  Required boundary: field-type rows are backend-owned disabled evidence only;
  they do not declare field types, declare fields, ready validation checks,
  accept records, admit commands, call Coinbase, mutate futures/order/exchange
  state, or grant browser/BFF or spot-rule authority.
- Completed `7481-7500` blind/contextless review: PASS after remediation for
  the newly added store record-validation remediation dependency work-item
  claim-trace clearance-step review input store record-validation check output
  schema field evidence. The initial frontend review blocked on a missing
  output-schema-field detail table, missing render-level assertions, stale
  autonomous checker label/tokens, and a generated docstring mismatch. The
  initial backend review blocked on the generated docstring mismatch and
  requested explicit output-schema-field assertions; the backend risk-proof
  regression already contained those assertions and the docstring was fixed.
  Re-review passed after the frontend table, row renderer, render tests,
  adapter assertions, checker tokens, backend docstring, OpenAPI, and generated
  schema were aligned. Phase-end stale-subagent sweep completed after
  validation evidence was consumed: backend reviewer
  `019f04b4-1b26-72e3-9332-58045083024f` and frontend reviewer
  `019f04b4-54d7-7303-9035-da9e6be446de` were closed after PASS results. The
  required boundary is that record-validation check
  output schema field rows are backend-owned disabled evidence only; they do
  not declare field names, field types, constraints, source refs, acceptance
  contracts, pass contextless review, ready validation-check output schema
  fields, admit commands, execute Coinbase calls, execute reconciliation,
  mutate futures/order/exchange state, grant browser authority, grant BFF
  authority, or grant spot-rule authority.
- Completed `7461-7480` blind/contextless review: phase-close local
  verification completed for the newly added store record-validation
  remediation dependency work-item claim-trace clearance-step review input
  store record-validation check output schema evidence. The required boundary
  is that record-validation check output schema rows are backend-owned disabled
  evidence only; they do not declare schemas, fields, types, constraints,
  acceptance contracts, pass contextless review, ready validation-check output
  schemas, admit commands, execute Coinbase calls, execute reconciliation,
  mutate futures/order/exchange state, grant browser authority, grant BFF
  authority, or grant spot-rule authority.
- Completed `7441-7460` blind/contextless review: phase-close local
  verification completed for the newly added store record-validation
  remediation dependency work-item claim-trace clearance-step review input
  store record-validation check input schema field evidence. The required
  boundary is that record-validation check input schema field rows are
  backend-owned disabled evidence only; they do not declare field names, field
  types, constraints, source refs, acceptance contracts, pass contextless
  review, ready validation-check input schemas, admit commands, execute
  Coinbase calls, execute reconciliation, mutate futures/order/exchange state,
  grant browser authority, grant BFF authority, or grant spot-rule authority.
- Completed `7421-7440` blind/contextless review: phase-close local
  verification completed for the newly added store record-validation remediation
  dependency work-item claim-trace clearance-step review input store
  record-validation check input schema evidence. The required boundary is that
  record-validation check input schema rows are backend-owned disabled evidence
  only; they do not declare schemas, fields, types, constraints, acceptance
  contracts, pass contextless review, ready validation-check contracts, admit
  commands, execute Coinbase calls, execute reconciliation, mutate
  futures/order/exchange state, grant browser authority, grant BFF authority,
- Completed `7401-7420` blind/contextless review: phase-close local
  verification completed for the newly added store record-validation remediation
  dependency work-item claim-trace clearance-step review input store
  record-validation check contract evidence. The required boundary is that
  record-validation check contract rows are backend-owned disabled evidence
  only; they do not declare contracts, declare schemas, declare validation or
  replay gates, bind idempotency, pass contextless review, accept records,
  admit commands, execute Coinbase calls, execute reconciliation, mutate
  futures/order/exchange state, grant browser authority, grant BFF authority,
  or grant spot-rule authority.
- Completed `7381-7400` blind/contextless review: phase-close local
  verification completed for the newly added store record-validation remediation
  dependency work-item claim-trace clearance-step review input store
  record-validation check evidence. The required boundary is that
  record-validation check rows are backend-owned disabled evidence only; they
  do not configure validators, execute checks, pass validation or replay gates,
  admit commands, execute Coinbase calls, execute reconciliation, mutate
  futures/order/exchange state, grant browser authority, grant BFF authority,
  or grant spot-rule authority.
- Completed `7361-7380` blind/contextless review: phase-close local
  verification completed for the newly added store record-validation remediation
  dependency work-item claim-trace clearance-step review input store
  record-validation evidence. Fresh
  blind/contextless backend and frontend re-review could not be started earlier
  because Codex subagent usage was exhausted; the review logs record local
  phase-close verification rather than completed fresh subagent evidence. The
  required boundary is that record-validation remediation dependency work-item
  claim-trace clearance-step review input store record-validation rows are
  backend-owned disabled evidence only; they do not configure validators, pass
  validation or replay gates, make schemas or append-only logs available, bind
  idempotency or payload validation, accept records, validate records, admit
  commands, call Coinbase, execute reconciliation, mutate futures/order/exchange state,
  or grant browser/BFF or spot-rule authority.
- Completed `7261-7280` blind/contextless review: phase-close local
  verification completed for store record-validation remediation dependency
  work-item claim-trace clearance-step evidence. Fresh subagent review was
  unavailable because of Codex usage limits; local autonomous verification is
  the recorded evidence.
- Completed `7241-7260` blind/contextless review: phase-close local
  verification completed for store record-validation remediation dependency
  work-item claim-trace clearance-plan evidence. Fresh subagent review was
  unavailable because of Codex usage limits; local autonomous verification is
  the recorded evidence.
- Completed `7201-7220` blind/contextless review: phase-close local
  verification completed for store record-validation remediation dependency
  work-item evidence. Fresh subagent review was unavailable because of Codex
  usage limits; local autonomous verification is the recorded evidence.
- Completed `7181-7200` blind/contextless review: phase-close local
  verification completed for store record-validation remediation dependency
  evidence. Fresh subagent review was unavailable because of Codex usage
  limits; local autonomous verification is the recorded evidence.
- Completed `7161-7180` blind/contextless review: phase-close local
  verification completed for store record-validation remediation evidence.
  Fresh subagent review was unavailable because of Codex usage limits; local
  autonomous verification is the recorded evidence.
- Completed `7141-7160` blind/contextless review: phase-close local
  verification completed for store record-validation evidence. Fresh subagent
  review was unavailable because of Codex usage limits; local autonomous
  verification is the recorded evidence.
- Completed `7121-7140` blind/contextless review: completed after remediation.
  The phase added backend-owned disabled store record-contract evidence and
  frontend display, preserved no-live/no-authority posture, and recorded that
  record-contract presence is not blocker resolution.
- Completed `7101-7120` blind/contextless review: completed after remediation.
  Arendt found only stale backend review-log/handoff evidence after verifying
  the store-requirement implementation as fail-closed; Hilbert found only
  stale frontend/backend review-log, frontend testing, and ignored local
  artifact evidence after verifying the frontend implementation as
  display-only. Bernoulli then found the backend read-service still emitted
  `approved_phase_range=7081-7100`; that finding was consumed by updating the
  read-service constant, backend contract assertions, OpenAPI, and generated
  frontend schema so runtime evidence now emits `7101-7120`. Parfit then found
  stale current-scope text in `docs/ADMIN_MODULE_CAPABILITY_MATRIX.md`; that
  finding was consumed by moving the matrix to `7101-7120` store-requirement
  evidence and adding the matrix to the autonomous checker. Noether performed
  the final blind/backend re-review and passed after verifying runtime
  `7101-7120` command-suite evidence, zero available/writer store requirement
  counts, and preserved no-live/no-authority posture. The findings were
  consumed by updating both review logs, frontend testing docs, and regenerated
  local release artifact evidence.
- Completed `7081-7100` blind/contextless review: completed after remediation.
  Carver initially found stale review logs plus public/raw command-suite
  payload size regression; the payload regression was remediated by bounded
  materialized detail samples. Ampere re-reviewed the remediated backend and
  found only stale review-log leadership, with no live-execution,
  reconciliation, futures-state-mutation, browser/BFF-authority, or spot-rule
  blocker. Socrates and Euler found only stale review-log leadership on the
  frontend side and no code-level authority leak.
- Completed `7081-7100` validation: focused backend/frontend checks passed for
  execution-eligibility resolution-plan step review input evidence and bounded
  command-suite materialized samples. Backend and frontend autonomous log
  validation passed after review-log and handoff updates. No live Coinbase
  execution was run; submitted/executed notional remains `0` USDC.
- Completed `7061-7080` validation: backend/frontend focused validation,
  OpenAPI and generated schema freshness, autonomous queue, ownership,
  stale-process, runtime-artifact report-only, and diff checks passed for
  execution-eligibility resolution-plan step review evidence. Full regression
  remains a durable milestone closeout gate. No live Coinbase execution was
  run; submitted/executed notional remains `0` USDC.
- Completed `7061-7080` blind/contextless review: backend and frontend fresh
  reviewers passed after remediation and confirmed resolution-plan step review
  evidence remained backend-owned, read-only, fail-closed, no-live, and
  display-only.
- Completed `7041-7060` blind/contextless review: Ohm initially failed on
  missing carried-forward resolution-plan terms in `genai_data/agent_state.md`
  and stale review-log leadership, and Plato initially failed on stale
  frontend/backend review-log leadership plus frontend quality gates still
  expecting `7021-7040`. The findings were consumed and remediated by adding
  current `7041-7060` review-log entries, moving active quality gates to
  `7041-7060`, and preserving `7021-7040` as completed history. Ohm and
  Plato re-reviewed and passed after remediation, then phase-end cleanup
  closed both agents.
- Completed `7041-7060` validation: backend focused validation, OpenAPI
  freshness, autonomous queue, ownership, stale-process, runtime-artifact
  report-only, and diff checks passed for execution-eligibility resolution-plan
  step evidence. Full regression remains a durable milestone closeout gate. No
  live Coinbase execution was run; submitted/executed notional remains `0`
  USDC.
- Completed `7021-7040` validation: backend focused validation, OpenAPI
  freshness, autonomous queue, ownership, stale-process, runtime-artifact
  report-only, and diff checks passed for execution-eligibility resolution-plan
  evidence. Full regression remains a durable milestone closeout gate. No live
  Coinbase execution was run; submitted/executed notional remains `0` USDC.
- Completed `7021-7040` blind/contextless review: Hubble initially failed on
  stale backend active-range docs, Hilbert initially failed on stale frontend
  active-range/current-phase docs, both sets of findings were remediated, both
  re-reviews passed, and phase-end subagent cleanup closed Hubble and Hilbert.
- Completed `7001-7020` validation: backend focused validation, OpenAPI
  freshness, autonomous queue, ownership, stale-process, runtime-artifact
  report-only, and diff checks passed for execution-eligibility semantic
  closure evidence. Full regression remains a durable milestone closeout gate.
  No live Coinbase execution was run; submitted/executed notional remains `0`
  USDC.
- Completed `7001-7020` blind/contextless review: the final fresh backend and
  frontend reviews passed after remediation and confirmed semantic closure
  evidence remained backend-owned disabled/read-only evidence. The frontend
  only displayed backend contracts without browser/BFF/live execution
  authority, no spot-only wallet/cost-basis/sell-guard rule was imported into
  futures/perpetuals, and phase-end subagent cleanup was completed.
- Current enterprise manual Spot order posture is route-specific. Safe No-live
  startup keeps `POST /api/v1/orders` dry-submit/review only. Controlled-live
  admission is possible only when the manager-owned execution lease, exact
  outer flag, current live decision, authenticated `trader` or `admin` RBAC,
  operator intent, idempotency, manual acknowledgement, Test portfolio/wallet,
  caps, audit, reconciliation, and final canonical route scope all pass. The
  backend derives `client_order_id`; a frontend human "operator" label alone is
  never execution authority.
- Active range adds futures request payload validation record
  execution-eligibility resolution-plan step evidence through
  `application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plan_steps.py`.
  The current fields include `execution_eligibility_resolution_plan_ref`,
  `execution_eligibility_resolution_plan_contract_ref`,
  `execution_eligibility_resolution_plan_step_ref`,
  `execution_eligibility_resolution_plan_step_contract_ref`,
  `resolution_plan_step_kind`, `resolution_plan_step_ready=false`,
  `resolution_plan_step_accepted=false`, `ordered_resolution_step_ref`,
  `ordered_resolution_step_refs`, `ordered_resolution_step_count`,
  `resolution_plan_present=true`, `resolution_plan_ready=false`,
  `resolution_plan_accepted=false`,
  `runtime_evidence_satisfies_semantic_contract=false`,
  `validation_record_admission_link_ready=false`, and
  `blocker_resolved=false`. Resolution plan step presence is not blocker
  resolution, runtime acceptance, command admission, Coinbase execution,
  reconciliation execution, futures/order/exchange mutation, browser/BFF
  execution authority, or spot-rule authority.
- Completed `7021-7040` carries forward futures request payload validation
  record execution-eligibility resolution-plan evidence through
  `application/admin_api/futures_request_payload_validation_record_execution_eligibility_resolution_plans.py`.
- Completed `7001-7020` carries forward futures request payload validation
  record execution-eligibility semantic closure evidence through
  `application/admin_api/futures_request_payload_validation_record_execution_eligibilities.py`
  and
  `application/admin_api/futures_request_payload_validation_record_execution_eligibility_blockers.py`.
- Completed `6981-7000` carries forward disabled futures request payload
  validation record reconciliation semantics through
  `application/admin_api/futures_request_payload_validation_record_reconciliation_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_RECONCILIATION_SEMANTIC_CONTRACTS`,
  and
  `iter_futures_request_payload_validation_record_reconciliation_semantics`.
- Completed `6961-6980` carries forward disabled futures request payload
  validation record cancel semantics through
  `application/admin_api/futures_request_payload_validation_record_cancel_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_CANCEL_SEMANTIC_CONTRACTS`, and
  `iter_futures_request_payload_validation_record_cancel_semantics`.
- Completed `6941-6960` carries forward disabled futures request payload validation record
  order semantics through
  `application/admin_api/futures_request_payload_validation_record_order_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_ORDER_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_order_semantics`,
  including `request_payload_validation_record_order_semantic_count`,
  `blocking_request_payload_validation_record_order_semantic_count`,
  `ready_request_payload_validation_record_order_semantic_count`,
  `runtime_observed_request_payload_validation_record_order_semantic_count`,
  `request_payload_validation_record_order_semantics`,
  `order_semantics_ref`, `order_semantics_contract_ref`,
  `evidence_routes`, `order_semantics_contract_available=false`,
  `order_semantics_contract_ready=false`, `order_identity_bound=false`,
  `order_side_bound=false`, `order_size_bound=false`,
  `order_price_bound=false`, `order_type_bound=false`,
  `runtime_order_evidence_observed=false`,
  `runtime_evidence_satisfies_order_semantics=false`, and
  `validation_record_order_semantics_ready=false`.
  Completed `6921-6940` carries forward disabled futures request payload
  validation record funding semantics through
  `application/admin_api/futures_request_payload_validation_record_funding_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_FUNDING_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_funding_semantics`,
  including `request_payload_validation_record_funding_semantic_count`,
  `blocking_request_payload_validation_record_funding_semantic_count`,
  `ready_request_payload_validation_record_funding_semantic_count`,
  `runtime_observed_request_payload_validation_record_funding_semantic_count`,
  `request_payload_validation_record_funding_semantics`,
  `funding_semantics_ref`, `funding_semantics_contract_ref`,
  `evidence_routes`, `funding_semantics_contract_available=false`,
  `funding_semantics_contract_ready=false`, `funding_rate_bound=false`,
  `funding_fee_bound=false`, `funding_interval_bound=false`,
  `funding_cost_bound=false`, `runtime_funding_evidence_observed=false`,
  `runtime_evidence_satisfies_funding_semantics=false`, and
  `validation_record_funding_semantics_ready=false`.
  Completed `6901-6920` carries forward disabled futures request payload
  validation record close-only semantics through
  `application/admin_api/futures_request_payload_validation_record_close_only_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_CLOSE_ONLY_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_close_only_semantics`.
  Completed `6881-6900` carries forward disabled futures request payload
  validation record reduce-only semantics through
  `application/admin_api/futures_request_payload_validation_record_reduce_only_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_REDUCE_ONLY_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_reduce_only_semantics`.
  Completed `6861-6880` carries forward disabled futures request payload
  validation record liquidation semantics through
  `application/admin_api/futures_request_payload_validation_record_liquidation_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_LIQUIDATION_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_liquidation_semantics`.
  Completed `6841-6860` carries forward disabled futures request payload
  validation record collateral semantics through
  `application/admin_api/futures_request_payload_validation_record_collateral_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_COLLATERAL_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_collateral_semantics`.
  Completed `6821-6840` carries forward disabled futures request payload
  validation record margin semantics through
  `application/admin_api/futures_request_payload_validation_record_margin_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_MARGIN_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_margin_semantics`.
  Completed `6801-6820` carries forward disabled futures request payload
  validation record position semantics through
  `application/admin_api/futures_request_payload_validation_record_position_semantics.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_POSITION_SEMANTIC_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_position_semantics`,
  including `request_payload_validation_record_position_semantic_count`,
  `blocking_request_payload_validation_record_position_semantic_count`,
  `ready_request_payload_validation_record_position_semantic_count`,
  `runtime_observed_request_payload_validation_record_position_semantic_count`,
  `request_payload_validation_record_position_semantics`,
  `position_semantics_ref`, `position_semantics_contract_ref`,
  `evidence_routes`, `position_semantics_contract_available=false`,
  `position_semantics_contract_ready=false`, `position_identity_bound=false`,
  `position_scope_bound=false`, `position_side_derivation_bound=false`,
  `position_size_bound=false`, `position_notional_bound=false`,
  `runtime_position_evidence_observed=false`,
  `runtime_evidence_satisfies_position_semantics=false`, and
  `validation_record_position_semantics_ready=false`.
  Completed `6781-6800` carries forward disabled futures request payload
  validation record semantic artifact runtime evidence acceptance through
  `application/admin_api/futures_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_RUNTIME_EVIDENCE_ACCEPTANCE_CONTRACTS`,
  and
  `iter_futures_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances`.
  Completed `6761-6780` carries forward disabled futures request payload
  validation record semantic artifact runtime evidence binding.
  Completed `6701-6720` carries forward disabled futures request payload
  validation record semantic artifact definition review input evidence through
  `application/admin_api/futures_request_payload_validation_record_semantic_artifact_definition_review_inputs.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_REVIEW_INPUT_CONTRACTS`,
  and
  `iter_futures_request_payload_validation_record_semantic_artifact_definition_review_inputs`.
  Completed `6661-6680`
  carries forward disabled futures request payload validation record semantic
  artifact definition evidence through
  `application/admin_api/futures_request_payload_validation_record_semantic_artifact_definitions.py`,
  `FUTURES_REQUEST_PAYLOAD_VALIDATION_RECORD_SEMANTIC_ARTIFACT_DEFINITION_CONTRACTS`,
  and `iter_futures_request_payload_validation_record_semantic_artifact_definitions`.
  Completed `6641-6660` carries forward disabled futures request payload
  validation record semantic artifact evidence.
