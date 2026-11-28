# Design Spec: Execution Core Command/Query Boundary

| Field | Value |
|---|---|
| Status | `IMPLEMENTING` |
| Operator approval | Accepted 2026-11-26; stages 5.1-5.3 and 5.4A approved 2026-11-27; stages 5.4B-5.6 require separate approval |
| Checklist or objective | Modular-monolith boundary checklist item 5 |
| Last evidence review | 2026-11-27, current worktree based on `dbd7dba3` |
| Implementation | Stages 5.1-5.4A implemented and validated; stages 5.4B-5.6 not started |

> This spec records the accepted item-5 design. Current behavior is established
> only by the implementation mapping and tests below. Approval through stage
> 5.4A does not authorize stages 5.4B-5.6.

## Problem

The current runtime has authoritative execution owners, but its application
commands and queries are not expressed through one transport-neutral boundary.
The embedded dashboard performs application work directly, mutable runtime
state can escape through shallow query copies, and execution modules import
dashboard, persistence, exchange, and global-hook capabilities in the reverse
direction of the intended modular-monolith dependency map.

A future secure CLI or console command client would otherwise have to duplicate
dashboard behavior, including its admission, validation, ownership, and error
rules.

## Evidence From the Current Checkout

- `main.py::build_application_runtime` is the sole composition root and already
  constructs the shared REST client, `OrderBook`, `StealthOrderManager`,
  `StealthOrderBridge`, `ExecutionCore`, `OrderEngine`, and `RuntimeController`.
- `StealthOrderManager.create_stealth_order` declares the manager path to be the
  only creation path and models a conventional order as an immediate reveal.
- `StealthOrderBridge` coordinates spans, schedules, and serialized manager
  access. Stage 5.1 routes both its query and the manager's serializable query
  through one manager-owned deep-detachment path; neither result shares nested
  authoritative dictionaries.
- `OrderEngine` owns exchange event processing, fills, follow-ups, and
  parent/child execution behavior. Stage 5.3 removes its dashboard and
  integration-registry imports; persistence helpers and the external WebSocket
  implementation remain for later stages.
- `RuntimeController.track_admitted_inflight` provides the atomic
  admission-and-registration boundary. Stage 5.2 routes all six supported
  dashboard-originating strategy commands through it under one application
  command category; the unsupported raw-placement path remains removed.
- `dashboard_server.py` currently handles 17 supported request types; six are
  classified locally as originating work.
- `module_boundaries.toml` now assigns seven exact reverse imports to checklist
  item 5, down from 15 before stage 5.3 and eight after stage 5.3.
- Constructor changes are broad even when production wiring is small:
  `OrderEngine` construction appears in 22 Python files and
  `StealthOrderManager` construction appears in 31.
- Stage 5.4A removed the unused `ConditionalExecutionWrapper`, its wrapper-only
  `OrderInterceptionLayer`, their tests/manual demonstrations, and the exclusive
  `conditional_orders` schema. Managed stealth reveal conditions, fill-ledger
  behavior, and active profitability validation remain intact.

The exact import-debt inventory remains authoritative in
`module_boundaries.toml`; this spec does not copy that list.

## Accepted Design

Introduce a lightweight in-process application boundary, provisionally named
`ExecutionCore`, using command/query separation without adopting full CQRS,
event sourcing, another process, or a network protocol.

`ExecutionCore` will:

- expose typed methods and result objects rather than generic string dispatch;
- apply shared application admission and validation rules for every transport;
- delegate lifecycle mutations to the existing authoritative bridge, manager,
  engine, and runtime controller;
- return immutable data-transfer objects or fully detached deep snapshots;
- use `client_order_id` for all internal tracking;
- contain no SQL, exchange SDK calls, hook-registry lookup, dashboard code, or
  lifecycle state machine; and
- be constructed in `main.py` from explicit dependencies.

The accepted placement contract requires that the ordinary application
placement command creates a managed limit order through the existing lifecycle,
using immediate reveal when no delayed or conditional strategy is requested. It
does not expose Coinbase's generic raw `create_order` capability. Market, stop,
bracket, TWAP, scaled, and other exchange order types remain unavailable until a
later design gives each type explicit local lifecycle, persistence,
reconciliation, cancellation, and recovery semantics.

The intended relationship is:

```text
dashboard now / secure CLI later
                |
          ExecutionCore
        commands | queries
            _____|_____
           |     |     |
        Bridge Manager Engine
           existing lifecycle owners

main.py injects persistence adapters, hooks, projection sinks,
the REST client, and the WebSocket factory.
```

## Ownership and Invariants

| Concern | Owner after the proposed change |
|---|---|
| Application command admission and transport-neutral dispatch | `ExecutionCore` |
| Runtime state transition and atomic in-flight registration | `RuntimeController` |
| Span coordination, scheduling, and serialized manager access | `StealthOrderBridge` |
| Strategy creation, reveal/rearm/move/cancel state machine, and its persistence ordering | `StealthOrderManager` |
| Exchange events, fills, follow-ups, and parent/child execution behavior | `OrderEngine` |
| Runtime object construction and adapter selection | `main.py` |
| Transport parsing, authentication, serialization, and connection handling | Dashboard now; future secure CLI adapter later |
| SQL implementation | Existing database modules behind narrow injected ports |

The facade must not move or duplicate lifecycle and transactional writes. Flat
parent/child hierarchy, root strategy authority, existing lock ownership,
single-code-path behavior, and the `client_order_id`/exchange-`order_id`
boundary remain non-negotiable.

## Public Contract

The exact method inventory will be finalized during an approved implementation
stage. All methods follow these rules:

- Each command has a typed request and typed success/failure result. Expected
  operational rejection is data, not an unclassified exception.
- Originating commands cross exactly one atomic application admission boundary.
  Internal reveal or hotpoint operations retain their established lifecycle
  guards; the design must prevent accidental nested registration.
- Cancellation, wind-down, queries, and appropriate administrative controls
  remain available while paused or draining according to current runtime rules.
- Active-state queries read from the authoritative in-memory owner and return
  immutable DTOs or deep detached snapshots. Historical and reconciliation
  queries are not smuggled through the active-state facade.
- Parent database-row CRUD is not proposed as a first-class application
  contract. A persistence row is not independently valid strategy behavior.
- Ordinary placement is a managed limit-order command. Immediate reveal provides
  conventional placement timing without bypassing local lifecycle ownership.
  The facade has no generic or unmanaged exchange-placement escape hatch.
- Authentication remains a transport-edge responsibility. The application
  boundary must still make it impossible for a transport to bypass admission,
  lifecycle, identifier, or ownership rules.

## Failure and Transaction Semantics

- `ExecutionCore` starts no database transaction. The existing lifecycle owner
  retains each transaction or ordered compensating sequence.
- Persistence ports are narrow, consumer-owned protocols. Their adapters call
  the existing `database.order` implementation; no SQL is copied into a new
  repository or facade.
- Admission and in-flight registration are atomic with respect to pause and
  shutdown. Either the state transition wins and rejects the command, or the
  command registers first and may finish as pre-existing work.
- Command results preserve a caller-supplied or generated `client_order_id` even
  when exchange placement fails or is indeterminate. Exchange `order_id` remains
  confined to exchange-facing operations and evidence.
- Existing fail-closed lifecycle behavior and best-effort stealth audit delivery
  remain unchanged. Durable audit delivery belongs to checklist item 9.

## Scope

- A transport-neutral command/query contract and composition in `main.py`.
- Shared atomic admission for originating application commands.
- Detached active-state query results.
- Injected projection, hook, persistence, and WebSocket-factory ports required
  to retire all item-5 reverse imports.
- Migration of the legacy `order.py` compatibility path to the accepted facade.
- Retirement of `ConditionalExecutionWrapper` and its exclusive
  `conditional_orders` persistence, configuration, test, and manual-script
  surfaces. The implementation-stage review must also remove
  `OrderInterceptionLayer` if it still has no independent production caller;
  fill-ledger behavior, the managed `ProfitValidator`, and the managed stealth
  lifecycle remain in scope for preservation.
- The dashboard raw-placement handler has been retired by the approved
  operator-surface cleanup. The future facade ordinary-placement contract
  remains managed limit-only and must not reintroduce arbitrary exchange
  configuration forwarding.
- Focused tests, complete-suite validation, living documentation, boundary-debt
  updates, and repository-graph reconciliation.

## Non-Goals

- Extracting a separate process, service, queue, or network API.
- Full CQRS, event sourcing, or a generic command bus.
- Rewriting active lifecycle state machines or active persistence schemas. The
  deliberate removal of the dormant `conditional_orders` schema is cleanup, not
  a replacement lifecycle design.
- Extracting public market-data ownership; that is checklist item 6.
- Moving dashboard parsing and all read projections; that is checklist item 7.
- Reconciliation, historical audit repair, or broad database readers; that is
  checklist item 8.
- Durable lifecycle-audit messaging; that is checklist item 9.
- Designing the future CLI transport or its authentication mechanism.
- Supporting market, stop, bracket, TWAP, scaled, or any other exchange order
  type before that type has an approved managed-lifecycle design.

## Rejected Alternatives

- One large facade that absorbs lifecycle state, SQL, exchange calls, and hook
  dispatch: it would become a new god object and split existing ownership.
- A second placement implementation for a CLI: it violates the single-code-path
  rule and would reproduce the current dashboard inconsistency.
- Returning manager dictionaries through the facade: shallow copies leak mutable
  authoritative state.
- A generic `execute(command_name, payload)` API: it moves dashboard string
  dispatch into the core and discards type and capability boundaries.
- Premature service extraction: the in-process interfaces and failure semantics
  are not yet stable enough for distributed consistency.

## Staged Plan and Blast Radius

Each stage requires a fresh focused source/test search, blast-radius discussion,
and separate operator approval before source changes.

### 5.1 Contract and facade shell

Status: implemented and validated 2026-11-27.

Add the typed command/query boundary, detached query results, focused contract
tests, and explicit `main.py` composition. Move no lifecycle behavior and perform
no database or exchange call in the facade.

Approved scope refinement: stage 5.1 exposes runtime status, pause, resume, and
detached active stealth-order queries only. It deliberately exposes no
originating placement or strategy command before stage 5.2 supplies the atomic
application-admission boundary. Detached order results are caller-owned but are
not advertised as a transactionally coherent multi-order database snapshot.

Primary blast radius: one new execution module, `main.py`, the runtime aggregate,
focused tests, documentation, and graph records.

### 5.2 Atomic application admission

Status: implemented and validated 2026-11-27.

Route originating facade commands through the controller's atomic admission
boundary. Preserve the intentional paused/draining availability of cancellation,
queries, and wind-down operations. Audit internal guards to prevent double
registration.

Primary blast radius: command methods, runtime-controller categories,
dashboard/future-adapter behavior, pause/shutdown race tests, and in-flight
metrics.

### 5.3 Projection and hook ports

Status: implemented and validated 2026-11-27.

Inject a typed execution projection sink and explicit hook capabilities into
`OrderEngine` and the manager. Compose dashboard and no-op adapters in `main.py`.
Preserve callback ordering and current best-effort audit behavior.

Primary blast radius: `OrderEngine`, `StealthOrderManager`, `main.py`, dashboard
publication adapters, integration registries, and their numerous fixtures.

### 5.4 Persistence ports and dormant conditional cleanup

#### 5.4A Dormant lifecycle retirement

Status: implemented and validated 2026-11-27.

Remove `ConditionalExecutionWrapper`, its wrapper-only
`OrderInterceptionLayer`, and their exclusive persistence, configuration,
test, and manual-tool surfaces. Reduce the fresh canonical schema from 12 to 11
required tables without issuing a destructive migration. Preserve managed
stealth reveal conditions plus active fill-ledger, lot, threshold, and
profitability behavior.

#### 5.4B Peripheral persistence ports

Status: reviewed but not approved for implementation.

Define narrow consumer-owned persistence protocols for the bridge, fill
ledger, move manager, and event stream. Consolidate existing fill-ledger SQL
behind retained database functions, implement a structural persistence adapter,
and compose it in `main.py` without changing failure or transaction semantics.

#### 5.4C Authoritative-owner persistence ports

Status: reviewed but not approved for implementation.

Define narrow manager and engine persistence protocols, move their raw SQL and
module-shaped database access behind the retained database implementation, and
remove the dead `OrderBook.db_module` capability. Preserve lock ownership,
fail-closed creation ordering, atomic database guards, and best-effort audit
policy.

Primary blast radius: six execution owners, database adapter wiring, constructor
fixtures, transaction/failure tests, the conditional module and schema helpers,
bootstrap schema expectations, manual utilities, living documentation, and
item-5 boundary debt.

### 5.5 WebSocket factory

Inject the authenticated Coinbase WebSocket wrapper factory while leaving
connection lifecycle ownership in `OrderEngine`.

Primary blast radius: engine construction, reconnect tests, and the external
reverse import.

### 5.6 Compatibility and closeout

Move the `order.py` compatibility path behind the accepted facade without
creating a second implementation. Remove retired debt entries and reconcile
tests, living documentation, design status, and graph evidence.

Primary blast radius: `order.py`, legacy/manual consumers, boundary tests,
documentation, and generated/curated graph artifacts. Systematic dashboard
handler extraction remains item 7.

## Acceptance Criteria

- One transport-neutral command/query contract exists and is composed only by
  `main.py`.
- Every supported transport reaches the same application behavior; no parallel
  placement, cancellation, or strategy implementation is introduced.
- The supported ordinary placement contract creates a managed limit order; no
  facade command forwards arbitrary Coinbase order configuration. The legacy
  dashboard raw-placement migration is explicitly assigned and cannot remain a
  second supported behavior after transport extraction.
- `ConditionalExecutionWrapper`, its exclusive `conditional_orders` schema, and
  its parallel lifecycle surfaces are removed rather than ported. Future
  conditional execution extends the managed limit-order lifecycle.
- Lifecycle and persistence ordering remain with their existing authoritative
  owners.
- All originating facade commands use a race-free admission contract, with
  explicit tests for pause and shutdown interleavings.
- Query results cannot mutate authoritative runtime state.
- Internal identity uses `client_order_id`; exchange `order_id` appears only at
  exchange-facing boundaries.
- All 15 item-5 reverse imports are retired from `module_boundaries.toml`
  without weakening the equality-based debt contract.
- Required focused coverage and `./scripts/run_tests.sh` pass.
- Living docs, this spec, and curated/generated repository-graph artifacts are
  reconciled with the implemented checkout.

## Resolved Decisions

1. **Ordinary placement path — approved 2026-11-26:** A plain application order
   is a managed limit order. Immediate reveal supplies conventional placement
   timing. Generic raw Coinbase placement is not part of the facade, and other
   exchange order types are deferred until their lifecycle is integrated.
2. **Dormant conditional execution — approved 2026-11-26:** Remove
   `ConditionalExecutionWrapper` and its exclusive persistence/configuration
   surfaces rather than porting an unused parallel lifecycle. Preserve active
   fill-ledger and profitability behavior. Any future conditional order is a
   managed limit-order strategy using the established lifecycle.

No material design decisions remain open. Discovery during an implementation
stage may return the spec to review rather than silently widening its scope.

## Implementation Mapping

Stages 5.1 through 5.3 are mapped as follows:

- `core/execution_core.py::ExecutionCore` owns the narrow transport-neutral
  shell. It exposes typed runtime status and transition results plus an
  enum-filtered detached stealth-order query. It has no database, exchange,
  dashboard, registry, or lifecycle-state-machine dependency.
- `core/stealth_order_manager.py::StealthOrderManager.snapshot_stealth_orders`
  owns deep detachment from the authoritative cache. It captures structural
  membership under the existing short cache lock and promises isolation from
  caller mutation, not cross-order transactional consistency.
- `bridges/stealth_order_bridge.py::StealthOrderBridge.get_stealth_orders`
  delegates to that one snapshot path and accepts `StealthOrderStatus`, not an
  untyped status string.
- `main.py::build_application_runtime` constructs one `ExecutionCore` from the
  shared bridge and `RuntimeController`, retains it in `ApplicationRuntime`,
  and explicitly installs that same instance in the embedded dashboard.
- `tests/regression/test_execution_core_contract.py` verifies immutable admin
  results, rejection-as-data, enum filtering, nested detachment, internal
  client-ID indexing, serializable snapshot isolation, composition, all six
  command admission outcomes, drain accounting, and exception cleanup.

Stage 5.2 adds:

- `ExecutionCore` typed requests and explicit methods for single create, span,
  import, Rehide, manual reprice, and revealed-order move. Every method crosses
  the same `INFLIGHT_APPLICATION_COMMAND` registration exactly once.
- `dashboard_server.py` parses transport payloads into those request types and
  translates typed admission rejection back to `admission_rejected`. Its former
  check-then-act lifecycle precheck is removed.
- `StealthOrderBridge.move_revealed_stealth_order` is the explicit move
  mutation capability. Dashboard code no longer reaches through the bridge to
  invoke manager move methods.
- `StealthOrderBridge.rehide_stealth_order` retains readiness checks and the
  per-`client_order_id` action lock but no longer performs a nested admission
  registration. An already-admitted Rehide may therefore finish if pause wins
  while it waits for that lock.
- Autonomous reveal, anchor-repricing, and Hotpoint admission guards are
  unchanged; they remain separate worker-originated operations.
- Import retains its documented partial-result behavior but the validated
  batch occupies one application admission registration. The previously found
  import/export omission of `enable_hotpoint_replication` is deliberately not
  changed in this stage and remains assigned to operator-protocol cleanup.

No lifecycle state machine, database schema, exchange adapter, worker admission
guard, or item-5 reverse-import debt entry changes in stage 5.2.

Stage 5.3 adds:

- `core/execution_ports.py` defines consumer-owned structural protocols for the
  execution projection sink and WebSocket, fill, placement, and stealth
  lifecycle hook capabilities. Stateless no-op implementations support
  deliberately isolated construction without service-locator fallback.
- `main.py::build_application_runtime` is the sole production lookup and
  composition point. It resolves the four existing registries once, shares the
  placement and lifecycle instances between manager and engine, and injects one
  `DashboardExecutionProjectionSink`.
- `OrderEngine` publishes orders, positions, engine status, logs, ticker, and
  spread through the injected sink. It registers its default fill logger before
  the existing event-stream subscriber, preserving callback order and registry
  failure semantics.
- `StealthOrderManager` dispatches placement and best-effort lifecycle audit
  callbacks through injected capabilities. Existing registry implementations
  and the event-stream subscriber remain unchanged.
- The dashboard adapter delegates to the six established publisher functions;
  it creates no parallel state or serialization path. Calls remain synchronous
  and bounded because some engine call sites hold lifecycle or ticker locks.
- The executable boundary baseline removes exactly seven item-5 reverse imports
  and one broad constructor capability. The resulting frozen totals are 16
  reverse imports, zero runtime import cycles, 34 broad capabilities, and seven
  reflection signatures.

No persistence port, WebSocket factory, hook-registry redesign, audit-durability
change, callback scheduling change, or operator wire-contract change is part of
stage 5.3.

Validation: the complete local non-external gate passed 1,883 tests with 17
skipped and 11 external tests deselected. Repository-graph build/check passed
with 468 files, 7,590 symbols, 1,568 indexed tests, 183 semantic records, no
parse findings, no fatal errors, and no check mismatches.

Stage 5.2 validation: the complete local non-external gate passed 1,842 tests
with 17 skipped and 11 external tests deselected. Graph evidence is reconciled
in the stage closeout change.

Stage 5.3 validation: Python compilation and the executable source-only
boundary audit passed. The complete local non-external gate passed 1,895 tests
with 17 skipped and 11 external tests deselected. Repository-graph build/check
reported 461 files, 8,693 symbols, 1,542 indexed tests, and 186 semantic records
with no parse findings, fatal errors, or mismatches.

Stage 5.4A adds:

- The dormant `ConditionalExecutionWrapper` and wrapper-only
  `OrderInterceptionLayer` are removed. Their exclusive configuration flags,
  test demonstrations, and manual database inspection/setup tools are removed
  with them; no second conditional execution path remains.
- `database.order` no longer defines `conditional_orders` or its CRUD helpers,
  and `database.schema` now owns an 11-table canonical required set. This is an
  additive fresh-deployment contract change: no runtime migration or table
  drop is issued against an existing database.
- Managed stealth reveal conditions remain the single conditional strategy
  path. Active fill-ledger, lot construction, threshold processing, and
  profitability validation code and coverage remain in place.
- The retired module's broad capability and reverse import are removed from the
  equality-based boundary contract. The resulting frozen totals are 15 reverse
  imports, zero runtime import cycles, 33 broad capabilities, and seven
  reflection signatures.
- Stages 5.4B and 5.4C remain unimplemented and separately gated; no active
  persistence owner or transaction/failure policy is moved in 5.4A.

Stage 5.4A validation: Python compilation, the executable boundary contract,
and `git diff --check` passed. The complete local non-external gate passed 1,891
tests with 17 skipped and 11 external tests deselected. Repository-graph
build/check reported 453 files, 8,641 symbols, 1,538 indexed tests, and 186
semantic records with no parse findings, fatal errors, or mismatches.

Relevant current navigation:

- `genai_data/MODULE_DEPENDENCIES.md`
- `module_boundaries.toml`
- `core/execution_core.py::ExecutionCore`
- `main.py::build_application_runtime`
- `core/runtime_controller.py::RuntimeController.track_admitted_inflight`
- `core/stealth_order_manager.py::StealthOrderManager.create_stealth_order`
- `bridges/stealth_order_bridge.py::StealthOrderBridge`
- `core/order_engine.py::OrderEngine`
- `dashboard_server.py::handle_client_message`
