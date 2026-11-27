# Design Spec: Unified Operator Console

| Field | Value |
|---|---|
| Status | `ACCEPTED` |
| Operator approval | Accepted 2026-11-27; TypeScript/build-chain decision confirmed 2026-11-27 |
| Checklist or objective | Replace the experimental browser UIs after the application command boundary is stable |
| Last evidence review | 2026-11-27, current worktree based on `c84d3b0d` |
| Implementation | Workflow contract accepted; source implementation not started |

> `ACCEPTED` records the reviewed target and constraints. The current HTML
> prototypes remain the supported clients until an implementation stage is
> separately reviewed, validated, and cut over.

## Problem

The two retained browser pages were experiments in AI-assisted frontend
development, not a deliberately designed operator workstation. They duplicate
connection state, payload parsing, forms, and lifecycle interpretation; they
also consume message names that are not consistently emitted by the server.
Rearranging those pages would preserve the wrong boundary: today the WebSocket
transport also performs application admission, mutation coordination, and read
projection work.

The replacement must optimize for safe operator decisions, not preserve the
prototype layout or implementation. It must also be reproducible on a fresh
deployment. A TypeScript source tree that is built only on a developer machine
would not meet that requirement.

## Evidence From the Current Checkout

- `dashboard_server.py` is an embedded, unauthenticated WebSocket transport and
  large mixed command/projection adapter.
- `ui_stealth_orders_manager.html` and `ui_order_span_builder.html` are the only
  retained browser clients. Both are standalone HTML/JavaScript prototypes.
- The repository currently has no `package.json`, lockfile, pinned Node
  version, frontend build, or Node prerequisite in `setup.sh`, release
  validation, or deployment.
- The current clients contain listeners for response/update names that the
  server does not emit. Import/export also omits
  `enable_hotpoint_replication`, so a replay is not yet a lossless protocol.
- `scripts/deploy_runtime.sh` validates, bootstraps, and starts the Python
  runtime, but it neither builds nor verifies browser assets.
- Execution Core stage 5.2 supplies the atomic application-admission boundary
  required before a replacement transport can safely originate commands.

## Accepted Design

Build one unified operator console from a new TypeScript source tree using
Vite. The old pages are feature references only; their DOM, CSS, and JavaScript
are not compatibility constraints.

The console is organized around operator workflows:

1. runtime health, admission state, connectivity, and in-flight work;
2. strategy composition for one managed limit order or a span;
3. active strategy/execution monitoring with parent/child context;
4. explicit interventions: cancel, Rehide, reprice, and move;
5. backup/import with a reviewable summary; and
6. recovery/audit evidence when an exchange-side outcome is uncertain.

One responsive application owns connection state, typed protocol decoding,
request correlation, projections, forms, and notifications. Separate views may
exist inside that application, but there is one client runtime and no second
implementation of a command.

## Ownership and Invariants

| Concern | Owner |
|---|---|
| Application admission and command dispatch | `ExecutionCore` |
| WebSocket authentication, parsing, serialization, and request correlation | operator transport adapter |
| Authoritative lifecycle/persistence mutation | existing bridge, manager, engine, and runtime owners |
| Browser connection/session state and presentation | TypeScript console |
| Production frontend build | one canonical repository script reused by setup, validation, and deployment |
| Static asset delivery | runtime adapter composed by `main.py`; never the Vite development server in production |

The console never infers exchange truth from command acceptance. It renders
authoritative projections and exposes pending/uncertain outcomes explicitly.
Internal tracking remains `client_order_id`; exchange `order_id` is display and
exchange evidence only. Parent/child strategy authority and the flat hierarchy
remain unchanged.

## Protocol Contract

- Commands and queries use versioned, typed envelopes with a caller-generated
  request ID and one correlated terminal response.
- Server-pushed projections/events are distinct from command responses.
- Unknown message versions or variants fail visibly; they are not silently
  ignored as successful operations.
- Lifecycle and permission state control which actions are enabled, but the
  server remains authoritative and must still reject races.
- Validation errors identify fields; operational failures preserve actionable
  stage/evidence such as whether a cancel succeeded before replacement failed.
- Initial connection obtains runtime status plus authoritative order
  projections before mutation controls become available.

Exact envelope schemas belong to the focused protocol-normalization stage and
must be reviewed before implementation.

## Build and Deployment Contract

The frontend gate must include all of the following in the same change that
introduces TypeScript source:

- a repository-pinned supported Node.js LTS version and documented Linux
  installation prerequisite;
- `package.json` plus a committed npm lockfile; deployments use `npm ci`, never
  dependency resolution without the lockfile;
- strict TypeScript configuration, Vite production configuration, lint/type
  checks, unit tests, and a production build command;
- one canonical frontend bootstrap/build script reused by `setup.sh`,
  `scripts/validate_release.sh`, and `scripts/deploy_runtime.sh` rather than
  three independent command sequences;
- regression coverage proving those entrypoints call the canonical path and
  fail clearly when the pinned Node/npm prerequisites are absent or wrong;
- production static-asset serving and health verification before the runtime is
  declared deployable; and
- a documented generated-asset policy. TypeScript source, configuration, and
  the lockfile are tracked. Reproducible `dist/` output is ignored and rebuilt
  during validation/deployment unless a later packaging design explicitly
  changes that decision.

`setup.sh` prepares development dependencies. Release validation runs frontend
checks and a production build. Deployment repeats/reuses the canonical locked
build before process startup, verifies that the expected asset manifest exists,
and then launches only the built production assets. The Vite development server
is never a production dependency or deployment entrypoint.

## Failure and Safety Semantics

- A disconnected or stale console disables mutations and does not queue hidden
  trading commands for automatic replay.
- Timeouts remain unknown until a correlated response or refreshed projection
  proves the outcome. Retrying a non-idempotent command requires an explicit
  idempotency contract.
- Pause/shutdown races are resolved by `ExecutionCore` atomic admission, not by
  a browser-side precheck.
- Import reports every entry and partial failure; it never implies an atomic
  multi-order transaction.
- Build, typecheck, test, missing manifest, or static-health failure aborts
  deployment before the engine is started.

## Scope

- One TypeScript/Vite console replacing both current pages.
- Versioned operator protocol and typed client bindings.
- Runtime/status, strategy creation, active monitoring, interventions,
  import/export, and recovery/audit workflows.
- Production static delivery and complete setup/release/deployment integration.
- Accessibility, responsive layout, focused UI tests, complete Python release
  validation, living documentation, and repository-graph reconciliation.

## Non-Goals

- Preserving prototype HTML/CSS/JavaScript structure.
- Adding new exchange order types or changing strategy economics.
- Moving lifecycle authority into the browser.
- Exposing the unauthenticated operator transport beyond a trusted boundary.
  Authentication/secure remote access requires its own threat-model review.
- Implementing the future CLI, although the protocol/application contracts must
  remain reusable by it.

## Alternatives Rejected

- Continue patching both standalone pages: preserves duplicated protocol and
  connection logic and makes operator state diverge between tabs.
- Buildless JavaScript: smaller initial tooling change, but loses strict typed
  protocol exhaustiveness and does not match the approved maintainable-console
  direction.
- Vite development server in deployment: adds a development process and
  dependency resolver to production instead of serving deterministic assets.
- Browser calls directly into bridge/manager-shaped endpoints: recreates the
  application-boundary problem and prevents a secure CLI from sharing behavior.

## Staged Plan and Blast Radius

Each implementation stage requires a focused current-checkout search and blast
radius review before source changes.

1. **Protocol normalization:** inventory supported commands/projections, remove
   ghost variants, add version/request IDs, close import/export field loss, and
   define typed failure envelopes. Blast radius: dashboard protocol, tests,
   current clients, API documentation.
2. **Build and delivery foundation:** add the pinned Node/npm prerequisites,
   TypeScript/Vite source shell, locked dependency/bootstrap path, production
   static adapter, and setup/release/deployment integration. Blast radius:
   repository root configuration, scripts, `main.py`, operator transport,
   deployment tests/docs.
3. **Read projections and navigation:** runtime health, active strategy tree,
   execution evidence, connection state, and bounded update handling.
4. **Strategy composer:** single managed-limit and span workflows with shared
   validation and review-before-submit.
5. **Interventions and recovery:** cancel, Rehide, reprice, move, import/export,
   partial/uncertain outcome presentation, and audit evidence.
6. **Cutover:** feature-parity review, production static health, delete both
   prototypes and their exclusive tests/assets, complete-suite/release/graph
   validation, and documentation reconciliation.

## Acceptance Criteria

- One console covers every retained operator workflow without parallel command
  implementations.
- Every mutation reaches `ExecutionCore`; client state cannot bypass atomic
  admission or lifecycle ownership.
- Protocol variants are typed, versioned, correlated, and covered by server and
  client contract tests.
- A clean Linux host following documented prerequisites can run `setup.sh`, the
  release gate, and deployment without an undocumented manual frontend step.
- Deployment uses the pinned Node/npm version and lockfile, builds production
  assets, verifies them, and never starts the Vite development server.
- The console distinguishes accepted intent, pending exchange confirmation,
  partial failure, indeterminate outcome, and authoritative terminal truth.
- The old pages and exclusive assets are removed only after validated parity.
- Complete non-external tests, frontend checks/build, living docs, and generated
  repository graph all pass.

## Open Decisions

No behavioral choice remains open. The exact supported Node.js LTS version and
package versions are implementation-time supply-chain selections: the focused
stage review must verify then-current support, pin them, and may not weaken the
locked/reproducible deployment contract.

## Implementation Mapping

No console source has been implemented. Execution Core stage 5.2 is a required
backend prerequisite and is mapped in `EXECUTION_CORE.md`; it does not itself
establish the protocol, frontend, static delivery, or deployment behavior
described here.
