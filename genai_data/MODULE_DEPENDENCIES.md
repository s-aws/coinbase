# Module Dependency Contract

Reconciled with the current checkout on 2026-11-28. Current source and tests
remain the evidence for runtime behavior.

## Purpose and Authority

`module_boundaries.toml` is the machine-readable in-process dependency
contract. `tests/regression/test_module_boundaries.py` inspects source syntax
without importing runtime modules and enforces that contract in the normal
test gate.

The contract freezes statically observable dependency and capability debt. It
does **not** claim complete runtime isolation. Python aliasing, monkeypatching,
objects returned by calls, and arbitrary dynamic dispatch can escape a local
AST analysis. Those limits are why later checklist work replaces broad object
and module injection with narrow consumer-owned contracts.

Changing the TOML baseline merely makes a change visible; it does not make a
new dependency architecturally acceptable. Adding or widening a debt entry
requires the same focused search, blast-radius review, and operator approval as
other modular-monolith boundary work.

## Supported Runtime Scope

The contract covers the installed runtime packages plus these supported root
modules:

- composition: `main.py`, `configuration.py`;
- operator modules: `dashboard_server.py`, `operator_api/`, `order.py`;
- shared logging adapter: `logging_service.py`.

Tests, `genai_tools/`, repository-graph tooling, scripts, and unsupported root
diagnostics are not runtime components. Covered runtime modules are forbidden
from importing them. Adding a supported root entry point requires explicitly
adding it to the contract.

## Target Dependency Direction

The current directories are not layers. In particular, `core/` contains both
low-level domain vocabulary and high-level execution orchestration. The
contract therefore classifies modules, with exact overrides, into these zones:

| Zone | Intended responsibility | May depend on |
|---|---|---|
| composition | construct and wire the process | every zone |
| operator | inbound commands and read presentation | operator, execution, domain, market data, reconciliation, logging |
| execution | authoritative trading orchestration | execution, domain, logging |
| reconciliation | drift detection and explicit repair orchestration | reconciliation, execution, domain, logging |
| market data | public market ingestion and derived state | market data, domain, logging |
| persistence | concrete database adapters | persistence, domain, logging |
| exchange | concrete exchange transports/adapters | exchange, market data, domain, logging |
| integration | application hook adapters | integration, execution, domain, logging |
| domain | shared vocabulary and calculation/policy code | domain, logging |
| logging | shared logging adapter | logging |

Stages 5.1-5.4B.3 place `core.execution_core` and `core.execution_ports` in the
execution zone. The facade depends on
domain enums/models, the runtime admission contract, and consumer-owned stealth
command/query protocols; `main.py` supplies the shared runtime controller and
bridge. The facade receives no persistence, exchange, dashboard, or integration
capability. Stage 5.2 moves dashboard origination behind the facade. Stage 5.3
adds narrow projection and hook protocols, makes `main.py` resolve concrete
dashboard/registry adapters, and retires seven exact item-5 reverse imports.
The same stage removes one previously broad manager hook capability because its
constructor parameter is now typed. Stage 5.4A removes the dormant conditional
execution lifecycle, its reverse database import, and its broad database-client
capability. Stage 5.4B.1 then introduces the consumer-owned
`FillLedgerPersistence` protocol and a concrete
`database.execution_persistence.DatabaseOrderPersistenceAdapter`. The fill
repository contains no SQL or database import; the adapter delegates to the
canonical `database.order` helpers without widening their lock or transaction
scope. Stage 5.4B.2 adds `OrderEventStreamPersistence` to the same adapter and
removes the publisher's database module and lazy database import. Event,
lifecycle-history, snapshot, and latest-marker writes remain independent and
best effort. `main.py` supplies both required capabilities to `OrderEngine`.
Stage 5.4B.3 adds `SpanParentOrderReader`; the bridge requires that one-method
capability for deterministic span retry verification and no longer imports
`database.order`. `main.py` supplies the same adapter, and the canonical helper
retains its SQL, lock, exception, and transaction behavior. The frozen totals
are 12 reverse imports, zero runtime import cycles, 31 broad
constructor capabilities, and seven reflection signatures.

Operator Console stages 1 and 2A place `operator_api` in the operator zone. It
owns JSON-RPC framing plus committed inbound param, method-correlated outbound
result, and notification schemas. Lifecycle, persistence, exchange, and
admission remain behind the existing application/domain owners. Result
validation selects a schema using the already-decoded enum method and adds no
reverse dependency into execution owners.

These directions describe the target modular monolith. Existing reverse edges
are exact debt entries rather than broad package exemptions. Item 4 retired
every forbidden configuration edge and the former runtime import cycle; its
empty group remains in the machine contract so regression is visible. The
remaining edges are grouped by the later checklist item expected to retire
them:

- item 5: direct execution-to-database/exchange/integration/dashboard edges;
- item 6: market-data persistence and direct venue ownership;
- item 7: operator transport directly reading persistence;
- item 8: reconciliation directly constructing persistence access.

Allowed-direction edges may be added without expanding architectural debt.
Every runtime module must still have one declared zone, and any new reverse
edge fails the regression contract.

## Frozen Cycles

The covered runtime import graph currently has no strongly connected
components. The former six-module cycle was retired by making configuration
passive, moving exchange construction/fetching to `external/runtime.py`, and
making `core/orderbook.py` the sole `OrderBook` implementation. The regression
test compares the cycle set exactly, so any new cycle fails review.

## Capability and Reflection Debt

Imports do not expose the full runtime dependency graph. For example, an
injected module or engine instance can provide arbitrary methods through
ordinary attribute access, `getattr`, callbacks, or aliases.

The contract therefore also inventories constructor parameters that are
unannotated or typed as `Any`, `object`, or `ModuleType` and stored directly on
an instance. For each such field it freezes the directly visible:

- member names, including literal `getattr`/`hasattr`/`setattr` probes;
- callable use;
- non-literal attribute lookup;
- direct pass/return/assignment escape targets.

It separately freezes dynamic attribute-name lookup, `locals`/`globals`/`vars`,
dynamic imports/evaluation, `sys.modules`, and direct `__dict__` access. New
uses fail unless the reviewed contract is deliberately changed.

This is a debt budget, not a type system. A previously escaped object can still
be aliased and used beyond what local syntax proves. New component boundaries
must therefore use narrow annotated protocols or facades. New `ModuleType`,
whole-engine, untyped host, or equivalent broad injection is prohibited unless
explicitly reviewed as new architectural debt.

## Maintenance Procedure

When a boundary changes:

1. inspect the source and identify whether the change follows an allowed
   direction or expands debt;
2. prefer removing the dependency or introducing a narrow consumer-owned
   contract;
3. remove stale import, cycle, capability, or reflection entries when debt is
   retired;
4. do not add an exception merely to make the test pass;
5. update this document, `ARCHITECTURE.md`, `MODULES.md`, the repository graph,
   and the modular-monolith checklist when ownership changes;
6. run the complete local non-external validation gate.

---

Last reconciled with checkout: 2026-11-28
