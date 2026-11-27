# Design Spec: Operator JSON-RPC Protocol

| Field | Value |
|---|---|
| Status | `IMPLEMENTED` |
| Operator approval | Approved 2026-11-27 as Operator Console stage 1 |
| Checklist or objective | Normalize the operator transport before the TypeScript/Vite build foundation |
| Last evidence review | 2026-11-27, current worktree |
| Implementation | Source, retained clients, healthcheck, tests, living docs, and repository graph implemented and validated |

## Decision

Use strict JSON-RPC 2.0 over the existing plain WebSocket listener. Application
methods have explicit `v1.*` names. Every client request supplies a canonical
lowercase UUID, object params, and receives exactly one correlated terminal
response. Server publications are named JSON-RPC notifications. Batch requests
and client notifications are unsupported.

The request UUID is correlation only. It does not grant replay safety or
generic idempotency. Domain keys such as deterministic `span_id` and caller
supplied create `client_order_id` retain their own contracts.

## Ownership

| Concern | Owner |
|---|---|
| Fixed methods, notifications, outcomes, reasons, and error codes | `core/enums.py` |
| Executable wire and method-param schema | `operator_api/schema.json` |
| Decode/validate/encode framing | `operator_api/protocol.py` |
| Explicit application dispatch and projection publication | `dashboard_server.py` |
| Atomic originating-command admission | `ExecutionCore` |
| Lifecycle/persistence/exchange truth | Existing engine, manager, bridge, and persistence owners |
| Browser correlation and presentation | Current retained pages; future unified console |

`operator_api` is transport-only. It must not acquire lifecycle, persistence,
exchange, or admission behavior. `dashboard_server.py` must not dispatch by
reflection or by transforming untrusted method strings into attribute access.

## Identifier Contract

- Wire and internal logical-order references use `client_order_id`.
- `order_id` appears only as exchange evidence or at exchange API boundaries.
- The JSON-RPC `id` is not an order ID.
- A new single-order create supplies its logical `client_order_id` in params.
- Span rung IDs remain deterministically derived from `span_id` by the existing
  planner.

## Session and Framing

`v1.session.bootstrap` is the initial client gate. It returns protocol
capabilities, runtime status, products, dashboard state, and the enriched
stealth-order projection. Connection registration emits no uncorrelated
bootstrap fragments. Current clients keep mutations unavailable until bootstrap
succeeds.

Requests permit only `jsonrpc`, `id`, `method`, and `params`. Unknown versions,
methods, variants, top-level fields, or method params fail visibly. Parse and
invalid-request errors use `id=null` when no trustworthy correlation ID exists.

Success results contain one of:

- `succeeded`: the synchronous application operation completed;
- `accepted_pending`: durable intent or drain was accepted, but later truth is
  still pending; or
- `partial`: a documented non-atomic multi-entry operation partially
  completed.

Errors use standard JSON-RPC codes plus the reserved application range in
`OperatorRpcErrorCode`. `error.data.reason` is stable machine vocabulary;
field validation includes paths and operational failures retain stage,
identity, retryability, or retained-order evidence when available.

## Supported Surface

The authoritative method and notification inventories are the enums and
committed schema, checked against `dashboard_server._RPC_HANDLERS` by regression
tests. The living human-readable table is in `API_REFERENCE.md`.

The originating set remains exactly single create, span create, import,
Rehide, manual reprice, and move-revealed. This stage does not silently move
the other retained dashboard mutations through `ExecutionCore`; that is
separate modular-boundary work requiring its own review.

Runtime, stealth-order, ticker, and spread publications are server
notifications and never command responses. Mutation handlers send the
correlated response before best-effort projection publication; a projection
publication failure does not rewrite a successful command result.

## Backup Versioning

Export document version 2 is lossless for the retained create contract,
including `enable_hotpoint_replication`. It exports active logical roots, not
derived follow-ups. Import version 2 requires the canonical
`coinbase.stealth-orders` schema marker.

Version 1 import is an explicit migration. Both an explicit `version: 1`
document and the historical unversioned
`export_active_stealth_orders_response` file are recognized. Its legacy
logical ID field maps to `client_order_id`, and
`enable_hotpoint_replication` defaults to `false` because the old format could
not preserve that choice. The result warns the operator.
Import is admitted once but remains per-entry/non-atomic and reports every
entry.

## Security and Recovery

JSON-RPC adds no authentication, authorization, TLS, origin check, or network
isolation. Supported deployment remains loopback-only. Secure remote or future
CLI access requires a separate threat model and authentication design.

A disconnected client does not queue commands for replay. A timeout is
indeterminate until a correlated response or authoritative projection proves
the outcome. Clients must not automatically retry a non-idempotent request
merely with a new JSON-RPC ID.

## Scope and Non-Goals

In scope:

- protocol enums, committed JSON Schema, strict framing, explicit dispatch;
- both retained browser clients and deployment healthcheck;
- removal of ghost wire variants;
- backup versioning, contract regression tests, docs, and graph evidence.

Not in scope:

- the TypeScript/Vite toolchain or unified console;
- static asset serving;
- operator authentication or remote exposure;
- new order types or strategy-economic changes;
- full extraction of application handlers/projection readers from
  `dashboard_server.py`; or
- replay/deduplication for generic requests.

## Acceptance Evidence

- Schema method inventory, protocol enums, and explicit dispatch are equal.
- Malformed JSON, batch/non-object input, client notifications, unknown
  methods, legacy identifier names, and invalid params fail structurally.
- One request produces one response with the same UUID; notifications have no
  ID.
- Both retained pages bootstrap, correlate requests, use `client_order_id`, and
  contain no legacy `data.type`/ghost branches.
- Runtime deployment health uses `v1.runtime.status`.
- Backup v2 round-trips `enable_hotpoint_replication`; v1 migration is tested.
- The complete non-external suite passed on 2026-11-27 with 1,859 tests,
  17 skipped tests, and 11 external tests deselected. Python compilation,
  schema smoke checks, diff validation, living documentation, and the
  repository graph were reconciled in the same change.
