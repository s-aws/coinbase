# Design Spec: Execution Core Command/Query Boundary

| Field | Value |
|---|---|
| Status | `DRAFT` |
| Operator approval | Durable-spec process approved; item-5 design decisions pending |
| Checklist or objective | Modular-monolith boundary checklist item 5 |
| Last evidence review | 2026-11-26, current staged worktree based on `1a451f1d` |
| Implementation | Not started |

> This draft preserves the reviewed proposal. It authorizes no item-5 source
> implementation and does not establish current runtime behavior.

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
  `StealthOrderBridge`, `OrderEngine`, and `RuntimeController`.
- `StealthOrderManager.create_stealth_order` declares the manager path to be the
  only creation path and models a conventional order as an immediate reveal.
- `StealthOrderBridge` already coordinates spans, schedules, and serialized
  manager access, but `get_stealth_orders` copies only the outer mapping; nested
  authoritative dictionaries remain shared.
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

## Decision Under Review

Introduce a lightweight in-process application boundary, provisionally named
`ExecutionCore`, using command/query separation without adopting full CQRS,
event sourcing, another process, or a network protocol.

If accepted, `ExecutionCore` will:

- expose typed methods and result objects rather than generic string dispatch;
- apply shared application admission and validation rules for every transport;
- delegate lifecycle mutations to the existing authoritative bridge, manager,
  engine, and runtime controller;
- return immutable data-transfer objects or fully detached deep snapshots;
- use `client_order_id` for all internal tracking;
- contain no SQL, exchange SDK calls, hook-registry lookup, dashboard code, or
  lifecycle state machine; and
- be constructed in `main.py` from explicit dependencies.

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

## Proposed Public Contract

The final method inventory remains subject to the open placement-path decision.
The contract should nevertheless follow these rules:

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
- Focused tests, complete-suite validation, living documentation, boundary-debt
  updates, and repository-graph reconciliation.

## Non-Goals

- Extracting a separate process, service, queue, or network API.
- Full CQRS, event sourcing, or a generic command bus.
- Rewriting the lifecycle state machines or database schema.
- Extracting public market-data ownership; that is checklist item 6.
- Moving dashboard parsing and all read projections; that is checklist item 7.
- Reconciliation, historical audit repair, or broad database readers; that is
  checklist item 8.
- Durable lifecycle-audit messaging; that is checklist item 9.
- Designing the future CLI transport or its authentication mechanism.

## Alternatives Rejected by This Draft

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

Add the typed command/query boundary, detached query results, focused contract
tests, and explicit `main.py` composition. Move no lifecycle behavior and perform
no database or exchange call in the facade.

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

### 5.4 Persistence ports

Define narrow consumer-owned persistence protocols for the bridge, manager,
engine, fill ledger, move manager, and event stream. Implement structural
adapters over the existing database functions and construct them in `main.py`.

Primary blast radius: six execution owners, database adapter wiring, constructor
fixtures, transaction/failure tests, and item-5 boundary debt. The disposition of
`ConditionalExecutionWrapper` must be decided before this stage.

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

## Open Decisions

1. **Ordinary placement path:** Should a future CLI and the dashboard represent a
   plain order as an immediate-reveal managed order, or retain the raw Coinbase
   `create_order` path? Recommendation: use immediate reveal and eventually
   remove the raw path so lifecycle ownership and admission have one code path.
2. **Dormant conditional execution:** Is `ConditionalExecutionWrapper` an
   abandoned experiment or a retained future feature? Recommendation: delete it
   if abandoned rather than add and maintain a persistence port for code with no
   production caller.

Either answer changes the supported command contract or stage-5.4 scope, so
both decisions block `ACCEPTED` status.

## Implementation Mapping

No item-5 implementation exists yet. Populate this section only when an approved
stage begins, linking each accepted contract to its source owner and tests.

Relevant current navigation:

- `genai_data/MODULE_DEPENDENCIES.md`
- `module_boundaries.toml`
- `main.py::build_application_runtime`
- `core/runtime_controller.py::RuntimeController.track_admitted_inflight`
- `core/stealth_order_manager.py::StealthOrderManager.create_stealth_order`
- `bridges/stealth_order_bridge.py::StealthOrderBridge`
- `core/order_engine.py::OrderEngine`
- `dashboard_server.py::handler`
