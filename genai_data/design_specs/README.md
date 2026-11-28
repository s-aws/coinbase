# Design Specs

## Purpose

Design specs preserve the reviewed rationale, intended contracts, blast radius,
and acceptance criteria for substantial cross-cutting changes. They are tracked
with the code so a normal Git review or revert includes both the implementation
and the design it is meant to satisfy.

They are not transcripts, implementation evidence, project-status logs, or a
second copy of the living architecture documentation.

## Authority

Current code, schema, configuration, and tests remain the evidence for current
behavior. A design spec has authority only within its declared status:

- `DRAFT`: proposal under discussion. It authorizes no implementation.
- `ACCEPTED`: operator-approved intent, scope, constraints, and acceptance
  criteria. It is not proof that any behavior exists.
- `IMPLEMENTING`: accepted design with an explicitly active implementation
  objective in `genai_data/agent_state.md`.
- `IMPLEMENTED`: design reconciled with completed code, tests, living docs, and
  repository-graph evidence. Current behavior must still be verified from those
  implementation artifacts.

The existence of a spec never activates work by itself. `agent_state.md` must
name the active objective, and any per-stage approval required by the spec still
applies. `genai_data/AGENT_CHANGE_WORKFLOW.md` governs investigation, planning,
approval boundaries, implementation, validation, and closeout for every spec
stage.

## Current Spec Index

| Spec | Status | Scope | Read when |
|---|---|---|---|
| [Execution Core](EXECUTION_CORE.md) | `IMPLEMENTING` | Modular-monolith checklist item 5; stages 5.1-5.4B.4 implemented | Reviewing commands, queries, execution ownership, dependency inversion, or future dashboard/CLI command paths |
| [Operator Console](OPERATOR_CONSOLE.md) | `ACCEPTED` | Stage 1 JSON-RPC and Stage 2A complete bidirectional schema implemented; no remaining stage is active | Reviewing operator UI, protocol, frontend tooling, static delivery, or deployment prerequisites |
| [Operator Protocol](OPERATOR_PROTOCOL.md) | `IMPLEMENTED` | Stage 1 framing plus Stage 2A method-result/notification contracts and producer validation | Reviewing operator wire framing, method dispatch, identifiers, errors, results, notifications, or backup versions |

Read only the task-relevant spec. Do not bulk-load this directory.

## Lifecycle

1. Review current code, tests, documentation, and graph evidence before writing
   a spec.
2. Record unresolved choices explicitly and keep the status `DRAFT`.
3. Change to `ACCEPTED` only after explicit operator approval of the material
   decisions and staged plan.
4. Change to `IMPLEMENTING` only when `agent_state.md` names that implementation
   as active. An accepted multi-stage spec may still require separate approval
   before each stage.
5. Update the spec in the same change set when implementation evidence changes
   its contract, blast radius, or acceptance criteria. Never silently rewrite an
   accepted decision.
6. Change to `IMPLEMENTED` only after code, required tests, living docs, and the
   repository graph are reconciled and validated.
7. Remove rejected or superseded specs from the active tree after recording the
   replacement where applicable. Git history is the durable archive.

Approval of investigation, findings, or a design status is not implementation
approval unless the immediately proposed stage and implementation boundary were
explicitly approved under the reviewed change workflow.

## Content Rules

- Describe decisions and externally meaningful contracts, not line-by-line code.
- Link to source, tests, living docs, boundary declarations, and graph tasks
  instead of copying inventories that already have one authoritative owner.
- State ownership, identifier, concurrency, transaction, failure, and recovery
  semantics explicitly when they are relevant.
- Separate scope from non-goals and distinguish current evidence from proposed
  behavior.
- Use `client_order_id` for internal order identity and enums from
  `core/enums.py` in every proposed runtime contract.
- Keep progress and immediate next actions in `agent_state.md`, not in the spec.

Start new specs from [TEMPLATE.md](TEMPLATE.md).
