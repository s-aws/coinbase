# Coinbase Trading Backend

## Goal 14 — parent move Premark lifecycle

Goal `operator_parent_move_premark_lifecycle_v1` provides one backend-owned
local PREMARK action for an exact approved-Test, `BTC-USDC`, system-owned,
direct `ADMIN_MANUAL_ROOT`, zero-fill source. It reserves one distinct
successor `client_order_id`, quantizes an immutable Product Catalog-bound plan,
and enforces fixed `3.10 USDC` submitted / `1.00 USDC` possible-execution
caps. PREMARK is a PostgreSQL mutation and makes no Coinbase call.

A separate Goal 14 ledger owns the ten-cycle budget, source/successor linkage,
plan hash, idempotency, correlation, append-only events, three
non-transferable future mutation claims, pre-boundary reclaim, and
boundary-crossed unknown recovery. The canonical Order Engine uses a
fail-closed source-cancellation follow-up suppression checker, and the legacy
dashboard `move_order`/`premark_move` commands are source-disabled.

The Goal 14 addendum did not enumerate the prerequisite live
profile/product/wallet/market/exact-order reads. Execute and exact-successor
closeout therefore reject before service, ledger, runtime, or Coinbase access
with `operator_parent_move_live_authority_terms_incomplete`. All source Cancel,
replacement Create, and successor Cancel allowances remain unconsumed. See
[the Goal 14 design](docs/OPERATOR_PARENT_MOVE_PREMARK_LIFECYCLE_V1.md).

## Completed independent Goal 13 — operator-ready Controlled-live closeout

Goal `operator_futures_hotpoint_canonical_single_child_v2` provides the
backend-owned Default-profile Futures lane for authenticated `/hotpoint`. Its
fixed policy is `Default` / `DEFAULT`, `AVP-20DEC30-CDE`, BUY, one generated
post-only LIMIT/GTC child contract, and strict `<100 / <150 / <300 USDC`
caps. Dedicated Goal 13 PostgreSQL authority and call ledgers reuse the shared
canonical Futures lifecycle serialization lock and exact-child Cancel seal;
they do not create a parallel Futures placement or cancellation path.

Persistent startup selects the approved Futures Default credential source
independently from the Spot/Test source, but accepts no externally configured
raw Futures portfolio UUID and makes no Coinbase call. If the source-parent
prerequisite is later satisfied, the first authorized eligibility cycle uses
its permissions and portfolio-catalog reads to resolve exactly one
credential-bound `Default` / `DEFAULT` row. The backend must match that
row's SHA-256 to the selected canonical source parent's process-local
portfolio SHA-256 before it can accept a candidate, then atomically binds only
the matching hash in the Goal 13 ledger. Restart, Preview/Create admission,
and every later claim enforce that durable hash. Exact closeout sends no
portfolio identifier.

Implementation, generated-contract synchronization, focused and full
backend/frontend gates, installed deployment validation, independent safety
and blind-contextless audits, and persistent Controlled-live handoff pass. The
installed state has no legitimately registered, reconciled, nonterminal AVP
source parent with more than three contracts of remaining capacity. The
operator readback exposes that local blocker, ARM/RUN fail closed before any
eligibility read, and the inherited exact-V3 flat-position rule remains a
future eligibility condition rather than a currently evaluated result. All ten
eligibility cycles and the Preview, Create, reconciliation, and Cancel
allowances remain unconsumed. No Goal 13 Coinbase call or live proof occurred.

Historical comparison used
`origin/prod:business/hotpoint_detector.py`,
`business/hotpoint_rate_limiter.py`, `business/hotpoint_placer.py`,
`business/hotpoint_decay_sweeper.py`, `dashboard_server.py`, and
`external/coinbase_client.py`. Current official Coinbase and pinned-SDK
contracts retain the Preview/Create/List Orders/Cancel and CFM eligibility
shapes used here. Modern CDP credentials are portfolio-bound and the
order-level `retail_portfolio_id` field is deprecated, so it is not sent.
Cancel success is treated only as request-initiation evidence until
authoritative reconciliation.

The terminal workflow preserves that truthful blocker without manufacturing
source provenance or transferring predecessor authority. See
[the Goal 13 design](docs/OPERATOR_FUTURES_HOTPOINT_CANONICAL_SINGLE_CHILD_V2.md).

## Completed Goal 12 Spot order truth and exact operations

Goal `operator_spot_order_truth_and_exact_cancel_reconcile_v1` provides
backend authority for the authenticated approved-Test Spot order inventory,
one no-retry catalog-refresh-or-exact-reconciliation cycle, and one
independent exact Cancel through the existing canonical route. PostgreSQL owns
claims, projections, restart recovery, audit, sanitized evidence, and exact
call accounting. Implementation and validation made zero Coinbase calls; both
allowances remain unconsumed.

## Completed Operator Spot recovery execution UI

Goal `operator_spot_recovery_execution_ui_v1` is independent Goal 6 of the
authorized operator UI sequence. It provides the backend authority for normal
authenticated recovery create, exact order/fill refresh, immutable-plan
review, PostgreSQL apply, safe rollback, and conditional exact active-orphan
Cancel controls at `/spot/recovery`.

The new PostgreSQL goal ledger owns one non-transferable ten-cycle refresh
budget and one goal-global exact Cancel allowance. Existing recovery rows are
preserved under
`operator_spot_recovery_and_reconciliation_execution_v1`; their cases, events,
cycles, and Cancel authority cannot appear in or authorize Goal 6. The browser
supplies only explicit intent and reasons, and ambiguous mutation readback
freezes further commands until authoritative reload.

Historical comparison used `origin/prod:business/fill_reconciler.py`,
`origin/prod:core/periodic_reconciler.py`, and
`origin/prod:core/startup_reconciler.py`. Background auto-heal, retry, legacy
WebSocket authority, and browser exchange behavior were not copied. See
[the Goal 6 design](docs/OPERATOR_SPOT_RECOVERY_EXECUTION_UI_V1.md).

Goal 6 permits at most ten no-retry exact order/fill refresh cycles and one
canonical exact-order Cancel only when reconciliation proves it necessary.
No Goal 6 Coinbase call has run; all Goal 6 live/read allowances remain
unconsumed pending full validation and both independent audits.

## Completed operator Futures fill-triggered follow-up activation

Goal `operator_futures_fill_triggered_follow_up_activation_v1` adds
PostgreSQL-owned enable, disable, pause, resume, drain, and status controls
for one attached Default-profile Futures intent. Exact source reconciliation
must first persist `FILLED`, `size=filled_size=1`, one-contract,
exchange-hash-bound evidence before the backend can claim one trigger.

The independent Goal 5 ledger runs one no-retry six-category eligibility
cycle, derives the opposite-side passive one-contract child under strict
`<100 / <150 / <300 USDC` caps, and permits one Preview, identical Create
only after acceptance, exact reconciliation, and conditional exact-child
Cancel. PostgreSQL owns one goal-global delegated authority, restart recovery,
call accounting, child identity, and fixed sanitized readback. Page loads and
control transitions make zero Coinbase calls.

Current official CFM endpoints and the pinned SDK show no published
maintenance-specific breaking change. Any eligibility or Preview
response-shape mismatch is nevertheless classified separately and fails
closed without raw response, identifier, or exception text. See
[the Goal 5 design](docs/OPERATOR_FUTURES_FILL_TRIGGERED_FOLLOW_UP_V1.md).

Goal 5 passed focused validation, both independent audits, the full backend
regression (1,286 parallel-safe plus 896 serial tests), and the complete
frontend release/deployment/E2E gate (1,774 unit/component tests). No
authoritative fully filled attached intent existed, so no Goal 5 Coinbase call
ran and every live allowance remains unconsumed.

## Operator Futures follow-up intent attachment

Goal `operator_futures_follow_up_intent_attachment_v1` adds one normal
authenticated local action to the exact Futures order-detail workflow. For an
eligible configured Default-profile `OPEN`, authoritative, one-contract
source projection, the backend derives the opposite side and persists one
immutable root/source-bound intent plus audit event in PostgreSQL.

The UI forwards only the exact backend observation/hash binding and two
explicit acknowledgements. Duplicate source attachment and changed
idempotency reuse fail closed. The action makes zero Coinbase calls, creates
no child, and grants no materialization authority. See
[the Goal 4 design](docs/OPERATOR_FUTURES_FOLLOW_UP_INTENT_V1.md).

Goal 4 passed focused contracts, the full backend regression (1,286
parallel-safe plus 890 serial tests), the full frontend
release/deployment/E2E gate, and both independent audits. The next authorized
goal is `operator_futures_fill_triggered_follow_up_activation_v1`. Current
official CFM routes and pinned SDK signatures show no established published
maintenance-era break, but the successor must still validate documented
compatibility and fail closed on schema drift before any live-capable
boundary.

## Operator Futures product policy and selected ticket

Goal `operator_futures_product_policy_and_ticket_expansion_v1` adds an
independent Default-profile CFM workflow for configured
`AVP-20DEC30-CDE` and `BIP-20DEC30-CDE` products. PostgreSQL owns immutable
approve/enable/disable/retire/select policy revisions and atomically
invalidates an unconsumed candidate whenever policy changes.

The backend derives exact product increments, contract size, one-contract
terms, current documented margin rates, required margin, and strict
`<100 / <150 / <300 USDC` evidence from one no-retry six-category cycle.
Only a fresh policy-bound candidate may enter the single-use
Preview/identical-Create/reconciliation/conditional-exact-Cancel sequence.
The browser supplies no portfolio, price, size, margin, cap, or exchange
identity.

Current official Coinbase product, Preview, and Futures margin schemas were
checked after the July 2026 maintenance window; post-maintenance
Default-profile reads showed no established breaking change. The validator
continues to fail closed on any documented-field or response-shape drift.
See [the Goal 3 design](docs/OPERATOR_FUTURES_PRODUCT_POLICY_AND_TICKET_V1.md).

The installed proof stopped after four no-retry cycles with the fixed
`margin_window_documented_but_v3_ineligible` classification. The returned
margin-window shape and state were documented, but the exact operator-defined
V3 profile/state pair was not present. Six cycles and all
Preview/Create/reconciliation/Cancel allowances remain unused.

## Completed Futures order inventory and exact operations

`operator_futures_order_inventory_detail_cancel_reconcile_v1` adds a
PostgreSQL-backed Default-profile Futures order inventory and exact
`client_order_id` detail workflow. Explicit refresh/reconciliation uses at
most ten no-retry logical catalogs. One freshly observed `OPEN` order may
consume the independent single-use canonical Cancel allowance. Raw exchange
identity is process-local and only its SHA-256 binding persists. See
[the Goal 2 design](docs/OPERATOR_FUTURES_ORDER_OPERATIONS_V1.md).
Actor-bound immutable request-result readback remains call-free and lets a
frozen operator session resolve its exact terminal cycle after a later
operator advances the mutable singleton.

The terminal Default-profile proof succeeded on cycle 6 with one page and
exactly three approved reads. Four cycles and the independent Cancel allowance
remain unused; no exchange mutation ran. The next authorized independent goal
is `operator_futures_product_policy_and_ticket_expansion_v1`.

## Completed independent Goal 11 — Futures position Close/Reduce

Status: `complete_operator_workflow_cfm_access_blocked_allowances_unconsumed`.
Current action:
`complete_goal11_position_lifecycle_cfm_access_blocked_allowances_unconsumed`.
Default action: `await_operator_direction_for_next_mvp`.

`operator_futures_position_close_reduce_and_reconciliation_v1` adds an
authenticated PostgreSQL-backed lifecycle for one selected Default-profile
Futures position. The backend binds one opaque `position_key`, claims each of
six approved eligibility categories at most once per cycle, derives the
closing side and either omitted-size full Close or exact one-contract Reduce,
and grants one mutually exclusive action claim. Exact order and position
reconciliation and at most one exact nonterminal Cancel are part of the same
durable coordinator. Restart recovery, call accounting, fixed diagnostics,
hash-only exchange evidence, and audit readback are backend owned. See
[the Goal 11 design](docs/OPERATOR_FUTURES_POSITION_CLOSE_REDUCE_V1.md).

## Completed independent Goal 10 — Futures manual order lifecycle

`operator_futures_manual_order_lifecycle_v1` adds an authenticated,
PostgreSQL-backed Futures workspace for the exact credential-bound Default
profile, `AVP-20DEC30-CDE`, one post-only BUY contract, and strict V3
`<100/<150/<300 USDC` caps. Operators can run one of ten no-retry six-category
eligibility cycles and explicitly authorize one Preview-gated lifecycle.
Accepted Preview may lead to one identical Create, one exact reconciliation,
and at most one exact nonterminal Cancel. Candidate freshness, single-use call
claims, atomic Create-to-reconciliation and reconciliation-to-Cancel handoff,
restart recovery, dedicated Futures execution posture, fixed diagnostics,
conservative call-boundary accounting, and hash-only private identity readback
are backend owned. See
[the Goal 10 design](docs/OPERATOR_FUTURES_MANUAL_ORDER_LIFECYCLE_V1.md).

## Completed independent Goal 9 — Hotpoint control and single placement

`operator_hotpoint_control_and_single_placement_v1` adds authenticated
PostgreSQL-backed Hotpoint controls for separate Spot and Futures domains.
Each domain owns its product/profile/cap policy and bounded parent window,
while a shared durable goal allowance permits at most one Create claim total.
Spot is Test/BTC-USDC under `3.10/1.00 USDC`; Futures is
Default/AVP-20DEC30-CDE, exactly one contract, under strict V3
`<100/<150/<300 USDC`. The Futures placement adapter remains unavailable
until the separately authorized canonical Futures lifecycle is activated.

## Completed independent Goal 8 — Fill-triggered follow-up activation

`operator_fill_triggered_follow_up_activation_v1` adds PostgreSQL-backed
enable, disable, pause, and drain controls for one previously attached
follow-up intent. The order engine claims only an enabled authoritative full
fill, proves exact fill-ledger equality and zero partial-fill child, and
delegates one backend-derived child to the canonical follow-up materializer.
Goal 8 uses a distinct single-use exchange-call ledger, fixed sanitized
diagnostics, restart-safe readback, and conditional exact-child safe closeout.
Managed attached intents never fall through to the legacy automatic
follow-up path. Control/read routes make no Coinbase call; ENABLE explicitly
delegates at most one future canonical Create under the displayed
Controlled-live, approved Test-portfolio, policy, wallet, and exact current
`3.10/1.00 USDC` cap boundaries.

## Completed independent Goal 7 — Revealed-order movement and repricing

`operator_revealed_order_movement_and_repricing_v1` adds one authenticated
operator-controlled movement for an exact zero-fill revealed placement.
PostgreSQL owns the immutable quantized post-only plan, definition and approved
Test-portfolio bindings, source/root/replacement `client_order_id` linkage,
canonical active-placement size and system-owned root evidence,
single-use Cancel and conditional Create claims, exact read accounting, restart
recovery, exact replay, and fixed sanitized readback. The canonical manager
durably persists a background-mutation fence before Cancel and may run one
non-configurable, durably claimed full-wallet check and Create only after exact
authoritative zero-fill `CANCELLED` evidence; it never credits the cancelled
source hold. Replacement reconciliation also proves the frozen order terms.
Rejected, unknown, or race-ambiguous cancellation prohibits replacement, and
the Goal 7 placement stays excluded from background repricing and
cancel/reentry. See
[the Goal 7 design](docs/OPERATOR_REVEALED_ORDER_MOVEMENT_AND_REPRICING_V1.md).

## Completed independent Goal 6 — Stealth reveal and exact closeout

`operator_stealth_reveal_and_exact_closeout_v1` adds the authenticated
operator-controlled runtime transition for one eligible Goal 5 definition.
PostgreSQL owns the exact definition/runtime identity, ten combined command
cycles, no-retry read accounting, frozen Preview/Create plan, one-use
Preview/Create/Cancel claims, restart recovery, and fixed sanitized readback.
The canonical manager suppresses background reveal, accepts one explicit
operator capability, performs no post-Preview market read or retry, rejects
hook payload drift, and defers local closeout until exact terminal readback.
See [the Goal 6 design](docs/OPERATOR_STEALTH_REVEAL_AND_EXACT_CLOSEOUT_V1.md).

## Completed independent Goal 5 — Stealth definition lifecycle

`operator_stealth_definition_lifecycle_v1` adds the authenticated Stealth
Operations workflow for PostgreSQL-backed list/detail/create/edit/cancel,
exact-set clear/export, and schema-validated preview/apply import. The backend
owns Product Catalog admission, approved-portfolio hashing, revisions,
idempotency, runtime interlocks, restart recovery, and fixed audit readback.
Active or revealed canonical placements fail closed into their separate domain
workflows. Goal 5 invokes no stealth runtime component, grants no trading
authority, and makes zero Coinbase calls or exchange mutations. See
[the Goal 5 design](docs/OPERATOR_STEALTH_DEFINITION_LIFECYCLE_V1.md).

## Completed independent Goal 4 — Parent strategy management

`operator_parent_order_management_v1` adds the authenticated Parent Strategies
workflow. PostgreSQL owns backend-validated create/edit/deactivate/delete
commands, exact revisions, fixed child policy, approved-portfolio hashing,
Product Catalog admission, dependency-aware tombstoning, idempotency, restart
recovery, and fixed audit readback. It grants no trading authority and makes
zero Coinbase calls or exchange mutations. See
[the Goal 4 design](docs/OPERATOR_PARENT_ORDER_MANAGEMENT_V1.md).
Closeout passed the complete backend/frontend regression, release, installed
deployment, safety, and blind-contextless gates. The next independent goal is
`operator_stealth_definition_lifecycle_v1`.

## Completed independent Goal 3 — Product Catalog administration

`operator_product_catalog_administration_v1` adds the authenticated Product
Administration workflow. PostgreSQL owns immutable product-catalog revisions,
one shared ten-cycle/no-retry refresh ledger, page claims, metadata diffs,
approval, enable/disable/retire lifecycle, rollback-as-new-revision, restart
recovery, idempotency, and fixed audit readback. Catalog lifecycle grants no
trading authority and makes no exchange mutation. See
[the Goal 3 design](docs/OPERATOR_PRODUCT_CATALOG_ADMINISTRATION_V1.md).

## Completed independent Goal 2

Goal `operator_fill_ledger_and_inventory_repair_v1` provides an authenticated
PostgreSQL workflow for an operator-selected exact `client_order_id`,
`BTC-USDC` product, or bounded time window. One explicit no-retry logical fill
catalog produces an immutable missing-fill plan and FIFO inventory/cost-basis/
P&L projection; the operator can apply and roll back the exact import batch.
Exact ownership and scoped-ledger hashes plus a product advisory lock shared
by every production fill writer prevent same-count substitution, stale
projection restoration, saved prior-projection/provenance drift, and a
concurrent writer commit across the repair boundary. It permits no Coinbase
order mutation. See
[`docs/OPERATOR_FILL_LEDGER_AND_INVENTORY_REPAIR_V1.md`](docs/OPERATOR_FILL_LEDGER_AND_INVENTORY_REPAIR_V1.md).
Its canonical backend regression, complete frontend release gate, installed
deployment checks, and independent safety plus blind-contextless audits pass.
No Coinbase call ran and its ten-cycle fill-read allowance remains unconsumed.

Completed independent Goal 1 is documented in
[`docs/OPERATOR_SPOT_RECOVERY_AND_RECONCILIATION_V1.md`](docs/OPERATOR_SPOT_RECOVERY_AND_RECONCILIATION_V1.md);
its optional exact-order Cancel allowance remains unconsumed.

## Current operator MVP

Goal
`operator_spot_automation_transport_explainability_and_successor_proof_v13_v15`
implements prospective value-blind Preview transport classification, a
separate durable V13-V15 ten-cycle ledger, and one DNS/TCP/TLS readiness
sequence that sends no HTTP bytes. Validation, deployment, and both audits
passed. V13 is terminal at `TRANSPORT_UNKNOWN` after one successful no-HTTP
DNS/TCP/TLS sequence, one eight-category cycle, eight exact eligibility reads,
and one consumed Preview allowance with exact wire count withheld. Create and
Cancel remain unconsumed. V14/V15 remain unused because official Coinbase,
SDK, and Requests documentation establishes no concrete correction for the
generic connection boundary. See
[`docs/OPERATOR_SPOT_AUTOMATION_TRANSPORT_EXPLAINABILITY_V13_V15.md`](docs/OPERATOR_SPOT_AUTOMATION_TRANSPORT_EXPLAINABILITY_V13_V15.md).
Current action: `close_v13_transport_unknown_v14_v15_unused`.

Completed predecessor goal
`operator_spot_automation_atomic_market_snapshot_binding_and_successor_proof_v10_v12`
is terminal after V10-V12. Cycles 1-3 each completed all eight reads exactly,
atomically bound final terms, and consumed that candidate's distinct Preview
allowance at a terminal `TRANSPORT_UNKNOWN` boundary with exact Preview wire
count withheld. The aggregate eligibility ledger is 3/10 cycles and 24 exact
reads. Create and Cancel remain unconsumed with zero calls and no exchange
mutation. The goal replaces the terminal V7 stale-plan
coupling with backend policy revision 5: one no-retry eight-category cycle
derives the exact post-only best-bid price, minimum valid size, fee-reserved
cap, plan/child identities, evidence binding, and one-use Preview claim, then
commits them atomically before Preview. Both notionals remain strictly below
3.10 USDC. The V12 correction classifies a response-bearing HTTP or blocked-
redirect exception separately from genuine transport uncertainty using only
fixed value-blind evidence and exact-or-withheld call accounting. V12 is
distinct rather than a V10 or V11 retry, and no successor remains. See
[Operator Spot Automation Atomic Market Snapshot V10-V12](docs/OPERATOR_SPOT_AUTOMATION_ATOMIC_MARKET_SNAPSHOT_V10_V12.md).

This repository is the backend for the Coinbase trading system. The modern
direction is a backend-owned Admin API with typed contracts, append-only
evidence, generated OpenAPI, focused local validation, and explicit live
execution gates. Legacy engine and dashboard code still exists, but new product
work should move through backend-owned API contracts rather than browser-side
trading decisions or direct dashboard authority.

This README is intentionally a short orientation. It does not enumerate every
workflow or module; detailed behavior lives in the linked docs and durable MVP
plans.

## Current MVP Goal: V13-V15

The current goal and its no-HTTP transport-readiness boundary are summarized
under [Current operator MVP](#current-operator-mvp) and specified in
[`docs/OPERATOR_SPOT_AUTOMATION_TRANSPORT_EXPLAINABILITY_V13_V15.md`](docs/OPERATOR_SPOT_AUTOMATION_TRANSPORT_EXPLAINABILITY_V13_V15.md).

### Completed V7-V9 predecessor

Goal
`operator_spot_automation_minimum_size_explainability_and_successor_proof_v7_v9`
is complete at `complete_terminal_eligibility_cycles_exhausted_v7`.
Current action: `complete_v7_cycle_10_best_bid_ask_rejected_preview_create_cancel_unconsumed`.
Default action: `await_operator_direction_for_next_mvp`.

The backend-owned successor policy
`BTC_USDC_POST_ONLY_BEST_BID_MINIMUM_SIZE_V2` derives the smallest valid
post-only fresh Get Market Trades best-bid candidate for the approved Test
portfolio and BTC-USDC. It uses fixed sanitized minimum/increment/fee/wallet/
freshness/cap classifications and a submitted plus fee-reserved dynamic cap
strictly below 3.10 USDC. Six-category preparation and eight-category run
eligibility share `10/10` durable no-retry cycles. Cycles 1–5 remain
immutable generic `automation_minimum_size_preparation_unknown` records with
zero completed categories and exact call count conservatively withheld; the
first approved category was not confirmed. Cycle 3 exposed an unprotected
REST-client method lookup, and cycle 4 exposed response processing outside the
fixed stage envelope. The deployed outer-boundary split classified cycle 6 as
`automation_minimum_size_materialization_unknown` after all six read
categories completed. Schema-only inspection localized two obsolete fixed-
1.00-USDC PostgreSQL CHECK constraints beside the dynamic-cap constraints.
The completed migration removed only those legacy checks and proved a
synthetic 1.01-USDC dynamic-cap row survives startup migration. Cycle 7 used
six exact reads and materialized immutable V7 with that dynamic cap.
Eligibility cycles 8–10 each used five exact reads and stopped at Get Market
Trades `BEST_BID_ASK` after permissions, portfolio, wallet, and product passed.
The ten-cycle budget is exhausted; backend readback is fixed at
`automation_spot_eligibility_cycles_exhausted` with no action.
Preview/Create/Cancel calls are `0/0/0`; every live allowance remains
unconsumed, no child exists, and V8–V9 were not created.

### V4 near-market predecessor closeout

Goal
`operator_spot_automation_near_market_policy_and_successor_proof_v4_v6`
is complete at `complete_terminal_no_valid_size`. Current action:
`complete_v4_no_valid_size_preview_create_cancel_unconsumed`.
Default action: `await_operator_policy_or_cap_decision`.

The versioned `BTC_USDC_POST_ONLY_BEST_BID_V1` policy is isolated to one
approved-Test-portfolio `BTC-USDC` Automation successor. The backend derives a
post-only BUY at the quantized, fresh Get Market Trades best bid and derives
size from product minimums/increments, wallet evidence, maker-fee reserve, and
the unchanged 3.10/1.00 USDC caps. PostgreSQL owns the sequential V4-V6
preparation claims, immutable definitions, goal-global ten-cycle accounting,
eight-category run eligibility,
and existing one-use Preview/Create/Cancel allowances. The installed operator
workflow completed one V4 preparation cycle and all six
approved read categories with `6` exact Coinbase read calls, then terminated
as `near_market_no_valid_size`. No definition or child exists. Goal-global
cycles are `1/10`; Preview/Create/Cancel calls are `0/0/0`, and those
allowances remain unconsumed. V5-V6 were not attempted. Complete backend
regression, the canonical frontend release gate, installed smoke, and
independent safety plus blind-contextless audits pass. See
[the near-market V4-V6 contract](docs/OPERATOR_SPOT_AUTOMATION_NEAR_MARKET_V4_V6.md).

### Previous Preview-explainability closeout

Goal
`operator_spot_automation_preview_explainability_and_successor_proof_v4_v6`
is complete at `complete_no_documented_successor_correction`. Current action:
`complete_preview_explainability_v4_v6_allowances_unconsumed`. Default action:
`await_operator_policy_decision`.

The backend exact-allowlists Coinbase's documented Preview `errs` enum and
persists/projects only fixed sanitized rejection codes. Goal-global V4-V6
eligibility cycles are `0/10`; Preview/Create/Cancel calls `0/0/0`; all
successor allowances remain unconsumed. The authorized terminal boundary is
`no documented correction remains`: V3 has no recoverable exact enum and its
standing BUY cannot move near market without broadening installed policy. No
Coinbase call or exchange mutation occurred in this goal. See
[the V4-V6 explainability closeout](docs/OPERATOR_SPOT_AUTOMATION_PREVIEW_EXPLAINABILITY_V4_V6.md).

### V3 predecessor terminal record

Goal `operator_spot_automation_documented_market_freshness_successor_v3` is
complete and terminal. V3 uses Coinbase's documented exact-product Get
Market Trades snapshot, requires its matching trade event time to satisfy the
unchanged 30-second maximum-age guard with a V3-only one-second bound for
observed Coinbase-to-host clock skew, and takes bid/ask from the same response. The original
trade time remains authoritative and expiry is clamped to 30 seconds; receipt
time or an unrelated proxy is never substituted. V3 has
a distinct PostgreSQL goal row, definition/run identity, eligibility cycles,
idempotency keys, and Preview/Create/Cancel allowances. See
[the V3 contract](docs/OPERATOR_SPOT_AUTOMATION_DOCUMENTED_MARKET_FRESHNESS_V3.md).
Status: `complete_terminal_preview_rejected`.
Current action: `complete_v3_terminal_preview_rejected_create_cancel_unconsumed`.
Default action: `await_operator_direction_for_next_mvp`.

The authenticated operator workflow created exactly one distinct V3 candidate.
Eight-category, no-retry eligibility cycles made
`8, 8, 8, 5, 8, 5, 8, 8` reads, or
`58` eligibility reads total. Cycle 8 proved exact eligibility using the
documented trade-event source. Exactly one Preview then returned a sanitized
`REJECTED` / `DOCUMENTED_REJECTION` result with a documented warning present;
the Preview identity remained unavailable and no raw response or withheld text
was retained. Terminal diagnostic is `automation_spot_preview_rejected`.
Durable total Coinbase accounting is `59`: Preview/Create/Cancel
calls `1/0/0`, allowances `consumed/unconsumed/unconsumed`, no child, and no
remaining action. The rejection is at Coinbase Preview, not at market
freshness. V1 and V2 remain sealed.
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

The authenticated Automation UI created one distinct immutable `BTC-USDC` V2
candidate for the approved Test portfolio. All ten no-retry Eight-category
eligibility cycles are terminal, with exact call distribution
`8, 5, 5, 4, 5, 5, 5, 5, 5, 8`.

Durable terminal accounting is exact: eligibility reads `55`, Coinbase Preview
calls `0`, Coinbase Create calls `0`, Coinbase Cancel calls `0`, and total
Coinbase API calls `55`. The run is `BLOCKED` with fixed diagnostic
`automation_run_blocked`, no allowed action, no Preview claim, and all three
live allowances unconsumed.

The sanitized boundary is the unchanged 30-second freshness guard over
Coinbase Best Bid/Ask source time. Receipt time and unrelated Product fields
were not substituted. No Preview, mutation, retry, fallback, alternate
identity, candidate, or child was accepted. V1 remains sealed with its exact
prior read/Create/Cancel evidence.

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

### Historical pre-closeout implementation checkpoint

Before terminal closeout, goal
`operator_spot_automation_single_child_execution_adapter_v1` was
at a canonical-single-child-execution-implemented, validation-pending
checkpoint. Durable PostgreSQL plan/run binding, a goal-global ten-cycle
ledger, the fixed no-retry Eight-category eligibility coordinator (including
the account-wide active Spot-order catalog), generated readback, and the
explicit operator refresh are implemented. Navigation remains call-free.

Exact-run authorization owns a separate final authorization refresh of the
same bound eight categories before its durable Create claim. The canonical
domain-owned one-child Create coordinator and the distinct
exact-child safe-closeout Cancel coordinator delegate through the existing
Spot command service with typed admission, RBAC, caps, idempotency,
reconciliation, and fixed sanitized call accounting. No bare enablement flag,
untyped gateway, alternate placement path, retry, scheduler, or fan-out was
added.

Historical checkpoint status was `canonical_single_child_execution_implemented_validation_pending`;
its action was
`complete_validation_audits_deployment_and_bounded_live_proof`. No goal-scoped
Coinbase call has run. Eligibility-cycle, final-authorization-read, Create, and
Cancel allowances remain unconsumed. Full validation, independent audits,
installed deployment validation, and the bounded live proof remained pending.
The previous source-gated checkpoint and its gate counts remain historical
evidence. See
[the adapter record](docs/OPERATOR_SPOT_AUTOMATION_SINGLE_CHILD_ADAPTER.md).

## Completed Automation control-plane predecessor

Historical status: `complete`.
Completed goal `operator_automation_control_plane_origin_prod_alignment_v1`
turned the routed Automation surface into an authenticated PostgreSQL-backed
operator workflow. Current action is
`complete_operator_automation_control_plane_origin_prod_alignment`; the
historical default was `await_operator_direction_for_next_mvp`. Definitions,
actor-scoped lifecycle and posture controls, review-only schedules, one-shot
local claims, restart recovery, pagination, and correlated definition/control/
run audit history are implemented through generated Admin API contracts.
Diagnostics remains separate.

Completed predecessor: Goal
`operator_core_workspaces_origin_prod_alignment_v1` is complete. Its historical
record has Status: `complete`. Its historical action is
`complete_core_operator_workspaces_origin_prod_alignment`; default action is
`await_operator_direction_for_next_mvp`. It delivered the persistent
authenticated operator shell and routed Portfolio, Spot Operations, Futures
Operations, Orders-detail, Automation, and System Operations workspaces while
keeping Diagnostics separate. Its historical Automation is GET-only posture is
superseded by the current goal; it remains evidence, not current authority.

The one authorized account-reality refresh completed and is consumed and
sealed; its evidence is stale for live eligibility and cannot be rerun under
this goal. No goal-scoped Create, Cancel, or live proof has run. The optional
Spot Create and exact-order Cancel allowances remain unconsumed. Futures is
source-disabled and call-free; its workspace exposes sanitized local evidence
only. Automation mutations from that predecessor are local PostgreSQL
control-plane operations and make zero Coinbase calls. Its domain adapters were
unavailable at closeout, so one-shot claims terminated `BLOCKED`; no Automation
live proof, Create, or Cancel ran and its goal-scoped live allowance remained
unconsumed. The installed successor is the separate `SOURCE_GATED` checkpoint
described above.

Historical core-workspaces validation evidence was backend full `1109 passed,
6 skipped` parallel and `599 passed, 150 skipped` serial, frontend full `1440
passed`, E2E `13 passed`, and independent safety audit `PASS`. The final blind
re-audit is not claimed as passed for that historical checkpoint.

Historical control-plane predecessor closeout evidence is backend full `1156 passed, 6 skipped` parallel and `609
passed, 150 skipped` serial, frontend full `1499 passed`, browser E2E `15/15`,
independent safety and blind-contextless audits `PASS`, and the canonical
release gate `PASS`. Packaged and installed validation includes a fresh real
Controlled-live entrypoint on an empty PostgreSQL database, durable Automation
readback, and zero Coinbase calls, Create calls, Cancel calls, or notional.

Historical predecessor
`operator_follow_up_operations_queue_and_single_live_proof` completed with
status `complete_zero_candidates`. The deployed passive local-SQL
Follow-up Operations workspace passed its focused/full, deployment, safety, and
blind-contextless gates. The exact post-gate local `materialization_review`
candidate count is `0`. The queue made no Coinbase read, Create, or Cancel call;
the goal-scoped proof claim was not created or required; and eligibility,
reconciliation, Create, and Cancel did not run. All live allowances remain
unconsumed, but that completed goal grants no continuing proof call. Keep the
Controlled-live review stack available under its separate runtime controls.

Historical goal `futures_preview_acceptance_recovery_r12` is
`complete_terminal_unknown_consumed`. Eligibility cycle 2 completed
`exact_v3_eligible`, created the one durable R12 claim, and left claim-only
evidence. Offline claim recovery appended terminal blocker
`claim_only_recovery_unknown_consumed` without constructing a Coinbase client
or factory. The source-bound `R12_RELEASE_READY` gate is `False`, R12 is
consumed, and no further Coinbase call is permitted. The generic
Preview-attempt counter is conservative: it records the consumed post-claim
attempt boundary as `1` but does not prove network reach. Preview network reach
is therefore unknown; retries, fallbacks, redirects, submissions, exchange
mutations, orders, and submitted/executed notional are all zero. See
[R12 terminal closeout](docs/FUTURES_SLICE_2R12_PREPARATION.md).

The predecessor goal `futures_preview_acceptance_recovery_r11` is complete.
R11 is consumed, terminal `blocked`, immutable, and cannot be retried. It stopped at
`remaining_margin_validation` before Coinbase Preview: all six bounded reads
ran once, while Preview, retry, fallback, redirect, submission, and every
exchange mutation remained `0`. The structured boundary is
`margin_window_type_documented_but_operator_rejected` at row `1`, profile
`retail_intraday_margin_1`, field `margin_window_type`, value type `string`.
This is an exact V3 operator-policy rejection, not authority to broaden schema
or acceptance. It grants no independent successor, Slice 3/4/5 activation, or
live authority; R12 remains governed only by its separate prepared boundary.
See the
[R11 terminal diagnosis](docs/FUTURES_SLICE_2R11_TERMINAL_DIAGNOSIS.md).

Historically, goal
`futures_post_r10_preview_compatibility_and_direction_selection` completed the
prospective separation of Coinbase's official Preview wire schema from the
project's stricter one-contract V3 acceptance policy. Immutable R1-R10 history
is preserved, R10 is not reinterpreted, and R8 content/hash remain inaccessible.
That historical checkpoint granted no successor or live authority and found ten
attempts unwarranted. See the
[post-R10 direction record](docs/FUTURES_POST_R10_COMPATIBILITY_DIRECTION.md)
and [Coinbase Admin MVP Goal](genai_data/AGENT_MVP_REBUILD_GOAL.md). Historical
M57 phase ranges and M58 fan-out/scheduler blockers do not select default work.

## Current Posture

- Python 3.13 is the supported backend interpreter.
- The Admin API is the modernization boundary for operator-facing product work.
- Live execution is fail-closed unless backend evidence proves authorization,
  idempotency, caps, audit, reconciliation, wallet, rollback, and runtime
  controls for the requested scope.
- `client_order_id` is the internal tracking key. Exchange `order_id` is
  exchange evidence only unless a Coinbase endpoint specifically requires it.
- Frontend code consumes generated contracts and may forward explicit operator
  requests to backend gates; Coinbase credentials, trading decisions, and
  execution authority stay backend-side.

## Runtime Boundaries

The checked-in `products.json` is a minimal local catalog, not the full
Coinbase spot universe. Legacy direct dashboard and stealth order entry use
configured products from that catalog. Ordinary Admin UI account, wallet,
product, fee, Spot-readiness, and Futures GETs are local and call-free in both
No-live and Controlled-live modes. Product refresh is source-disabled before
any Coinbase read or `products.json` write.

The legacy dashboard WebSocket remains available for read/control compatibility
and source material, but its exchange mutation messages are source-disabled.
Legacy `main.py` Controlled-live startup and historical raw smoke/sweep/batch
mutation modes are also source-disabled. The six installed Controlled-live
mutation routes are manual root place/cancel, explicit attached-intent
materialization/exact-child safe-closeout, and operator Hotpoint run-once/
exact-child safe-closeout. Intent attachment is local-only and
never supplies live authority; materialization and safe-closeout each require a
fresh, separate explicit acknowledgement plus the backend's exact identity,
fill/terminal-state, Test-portfolio, wallet/cap, RBAC, idempotency, audit,
reconciliation, duplicate-prevention, and route-scope gates. No scheduler or
autonomous follow-up execution is installed. New UI work must use generated
contracts and backend read models.

For the ordered documentation index, start at [docs/README.md](docs/README.md).
For spot setup notes, see [README.spot-trading.md](README.spot-trading.md).
For USDC-only spot portfolio sweep planning, see
[README.spot-portfolio-sweep.md](README.spot-portfolio-sweep.md).
For account-level stealth planning/reveal guards, see
[README.action-condition-guards.md](README.action-condition-guards.md).
For the enterprise admin API boundary, see
[README.admin-api.md](README.admin-api.md).
For backend maintainer handoff, see
[docs/MAINTAINER_HANDOFF.md](docs/MAINTAINER_HANDOFF.md).

## Setup

Install the package in development mode with Python 3.13:

```bash
python3.13 -m pip install -e .
```

On Windows, `py -3.13 -m pip install -e .` is also valid.

## Configuration

The engine uses the following environment variables:

- `COINBASE_API_KEY` - Coinbase API key for authentication
- `COINBASE_API_SECRET` - Coinbase API secret for authentication
- `COINBASE_USE_SANDBOX` - Set to "true" to use Coinbase sandbox environment

Backend-only Admin API smoke and controlled-live tools can also load live
credentials from the default AWS Secrets Manager secret id `coinbase`. Override
it with `COINBASE_SECRETS_MANAGER_SECRET_ID`,
`COINBASE_API_CREDENTIALS_SECRET_ID`, or `COINBASE_LIVE_CREDENTIALS_SECRET_ID`
in the backend shell, plus `COINBASE_SECRETS_MANAGER_REGION` when needed.
Verify redacted availability without printing values:

```bash
python3.13 tools/coinbase_live_credentials.py --check
```

## Runtime

Common local entry points:

- Admin API/OpenAPI contract: `api/`, `application/admin_api/`, `openapi/`
- Main engine entry point: `main.py`
- Legacy dashboard WebSocket: `ws://localhost:8765` through `dashboard_server.py`
- Legacy dashboard UI: `ui_stealth_orders_manager.html`

Generate the Admin API contract after backend model or route changes:

```bash
python3.13 tools/generate_admin_api_openapi.py
```

## Tested Environment

This project is tested on:
- Local Linux Docker
- Python 3.13
- Coinbase Advanced Trade API (REST + WebSocket)

Run focused tests and validators for ordinary changes. Full regression is a
durable milestone closeout, public/release-candidate handoff, deployment
approval/closeout, release-hardening closeout, Admin API/backend association
closeout, or explicit user request gate. See
[Regression Process](docs/REGRESSION_PROCESS.md) for the durable policy.

In the local Linux Docker environment, use `python3.13` for backend scripts,
OpenAPI generation, ownership checks, and compile checks. The `python` alias
may be unavailable, and `/usr/bin/python3` may not be the backend dependency
interpreter. Use the installed `pytest` executable directly for test targets
unless a command specifically requires module execution; the repo pytest
executable runs under Python 3.13.

Use the process-parallel runner for that closeout gate:
```powershell
python3.13 tools/run_parallel_regression.py --workers 4
```

Sequential pytest is a fallback only when the runner cannot be used:
```powershell
pytest tests/regression/ -v --tb=short
```
