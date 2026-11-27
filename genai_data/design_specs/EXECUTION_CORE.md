# Design Spec: Execution Core Command/Query Boundary

| Field | Value |
|---|---|
| Status | `IMPLEMENTING` |
| Operator approval | Accepted 2026-11-26; stage 5.1 approved 2026-11-27; later stages require separate approval |
| Checklist or objective | Modular-monolith boundary checklist item 5 |
| Last evidence review | 2026-11-27, current worktree based on `89c72573` |
| Implementation | Stage 5.1 implemented and validated; stages 5.2-5.6 not started |

> This spec records the accepted item-5 design. Current behavior is established
> only by the implementation mapping and tests below. Approval of stage 5.1
> does not authorize any later implementation stage.

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
  parent/child execution behavior, while directly importing dashboard
  publication functions, integration registries, persistence helpers, and the
  external WebSocket implementation.
- `RuntimeController.track_admitted_inflight` provides the required atomic
  admission-and-registration boundary. The dashboard raw `place_order` branch
  instead performs an optimistic message-level check followed by
  `track_inflight`, leaving a pause race.
- `dashboard_server.py` currently handles 36 command/query/admin message types;
  11 are classified locally as originating work.
- `module_boundaries.toml` assigns 15 exact reverse imports to checklist item 5.
- Constructor changes are broad even when production wiring is small:
  `OrderEngine` construction appears in 22 Python files and
  `StealthOrderManager` construction appears in 31.
- `ConditionalExecutionWrapper` has no production caller. Its references are
  its own module, one integration test, and two manual root-level logging tests.

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
- Retirement or migration of the dashboard's raw placement handler when the
  operator transport adopts the facade. The target contract excludes raw
  placement; the implementation-stage review must assign the change to item 5
  or the systematic dashboard extraction in item 7 without leaving two
  supported behaviors.
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

Route originating facade commands through the controller's atomic admission
boundary. Preserve the intentional paused/draining availability of cancellation,
queries, and wind-down operations. Audit internal guards to prevent double
registration.

Primary blast radius: command methods, runtime-controller categories,
dashboard/future-adapter behavior, pause/shutdown race tests, and in-flight
metrics.

### 5.3 Projection and hook ports

Inject a typed execution projection sink and explicit hook capabilities into
`OrderEngine` and the manager. Compose dashboard and no-op adapters in `main.py`.
Preserve callback ordering and current best-effort audit behavior.

Primary blast radius: `OrderEngine`, `StealthOrderManager`, `main.py`, dashboard
publication adapters, integration registries, and their numerous fixtures.

### 5.4 Persistence ports and dormant conditional cleanup

Remove `ConditionalExecutionWrapper` and its exclusive persistence surface
instead of creating a port for a lifecycle with no production caller. Audit the
wrapper-only `OrderInterceptionLayer` at the same boundary. Then define narrow
consumer-owned persistence protocols for the bridge, manager, engine, fill
ledger, move manager, and event stream. Implement structural adapters over the
retained database functions and construct them in `main.py`.

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

Stage 5.1 is mapped as follows:

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
  shared bridge and `RuntimeController` and retains it in `ApplicationRuntime`.
  The dashboard is not migrated or given another global in this stage.
- `tests/regression/test_execution_core_contract.py` verifies immutable admin
  results, rejection-as-data, enum filtering, nested detachment, internal
  client-ID indexing, serializable snapshot isolation, and composition.

No originating command, atomic-admission category, lifecycle mutation,
database/exchange call, dashboard handler, or item-5 reverse-import debt entry
changes in stage 5.1.

Validation: the complete local non-external gate passed 1,883 tests with 17
skipped and 11 external tests deselected. Repository-graph build/check passed
with 468 files, 7,590 symbols, 1,568 indexed tests, 183 semantic records, no
parse findings, no fatal errors, and no check mismatches.

Relevant current navigation:

- `genai_data/MODULE_DEPENDENCIES.md`
- `module_boundaries.toml`
- `core/execution_core.py::ExecutionCore`
- `main.py::build_application_runtime`
- `core/runtime_controller.py::RuntimeController.track_admitted_inflight`
- `core/stealth_order_manager.py::StealthOrderManager.create_stealth_order`
- `bridges/stealth_order_bridge.py::StealthOrderBridge`
- `core/order_engine.py::OrderEngine`
- `dashboard_server.py::handler`
