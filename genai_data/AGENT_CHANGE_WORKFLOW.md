# Reviewed Change Workflow

## Purpose and Authority

This is the mandatory operating contract for non-trivial repository work. It
exists so a new agent or session can reproduce the project's reviewed workflow
without relying on chat history.

`AGENTS.md` and `agent.md` remain higher-authority instructions. Current code,
schema, configuration, and tests remain the evidence for implemented behavior.
Task-relevant accepted design specs govern approved intent only. This workflow
governs how evidence, plans, approvals, implementation, validation, and
closeout move between those authorities.

## Applicability

Use the complete workflow for any change that can affect runtime behavior,
data, schema, concurrency, transactions, recovery, deployment, operator
interfaces, architecture, or a tracked checklist. Use the same approval rules
for substantial documentation or design decisions.

Purely mechanical edits may compress the investigation and plan into a short
statement when their scope and consequences are self-evident. They do not bypass
validation, documentation, graph, tracking, or commit requirements applicable
to their changed files.

Read-only questions, investigations, and plans stop before implementation and
do not create empty commits.

## Approval Contract

Every task is in exactly one workflow stage:

1. `INVESTIGATING`
2. `PLANNING`
3. `AWAITING_IMPLEMENTATION_APPROVAL`
4. `IMPLEMENTING`
5. `VALIDATING`
6. `COMPLETE`
7. `BLOCKED` or `DEFERRED` when applicable

Approval is stage- and scope-specific; it is never transitive.

- Approval to investigate authorizes read-only evidence gathering only.
- Approval of findings authorizes planning only when that is the proposal being
  approved.
- Agreement with a plan does not by itself authorize implementation; explicit
  implementation approval authorizes only the plan's stated boundary.
- Approval of one checklist item does not authorize another item.
- A plain `approved` applies to the immediately preceding proposed stage and
  scope, not to the surrounding backlog.
- Tests, living-documentation reconciliation, repository-graph maintenance,
  tracking task files, and the task-ending commit are included in an approved
  implementation unless the operator explicitly excludes them.
- Deployment, database mutation, exchange activity, destructive commands,
  Git push, and other external side effects always require their own authority
  when they are not already explicit in the approved objective.

If new evidence materially changes behavior, scope, transaction semantics,
existing-data compatibility, operator workflow, or blast radius, stop before
the expanded implementation. Report the evidence, revise the plan, and obtain
renewed approval. Mechanical consequences required to finish the already
approved behavior do not constitute scope expansion.

## 1. Rehydrate and Establish the Baseline

Before non-trivial work:

1. Follow the required reading order in `AGENTS.md` and `ai-context.md`.
2. Read the current workflow state in `genai_data/agent_state.md`.
3. For Codex, validate and route through `codex_repo_graph/ENTRYPOINT.md`.
4. Confirm the branch, HEAD, worktree status, and pre-existing user changes.
5. Identify the current checklist item, workflow stage, approval boundary,
   open risks, and next required operator decision.
6. State the current objective in one sentence.

Raw chat history is supporting context, never the sole durable authority. When
chat and the checkout disagree, stop and reconcile the difference.

## 2. Perform a Focused Investigation

Investigation is read-only unless the operator has separately authorized a
diagnostic mutation. Inspect enough of the current checkout to establish the
whole behavior path, including where relevant:

- Supported entrypoints and every production caller.
- Producers, consumers, state ownership, and persistence ownership.
- `client_order_id` and exchange `order_id` boundaries.
- Database schema, constraints, existing-data shape, and transaction scope.
- Locks, concurrency, retries, idempotency, duplicate delivery, and ordering.
- Failure, rollback, restart, recovery, reconciliation, and operator evidence.
- UI, API, CLI, protocol, deployment, bootstrap, reset, and migration effects.
- Existing coverage and missing success, failure, and race cases.
- Task-relevant documentation and graph evidence.
- Git history when it clarifies intent, regression origin, or superseded design.

Do not infer safety from a single function or a happy-path test. Do not run a
live tool merely because it exists in `genai_tools/`.

## 3. Report Findings

Lead with the material disagreement, risk, or unflattering fact. Explain:

- What the operator means and the intended outcome.
- What the checkout actually does.
- The evidence for any discrepancy.
- Whether the fault is isolated or coupled to other faults.
- What a superficially smaller fix would leave unsafe.
- Material facts the operator did not ask about.
- Verified facts, inferences, historical claims, and unknowns as distinct
  categories.

New faults are added to the durable checklist or explicitly deferred. They are
never silently bundled into implementation.

## 4. Maintain the Checklist

Use these item states:

- `PENDING`
- `INVESTIGATING`
- `PLANNED`
- `APPROVED`
- `IMPLEMENTING`
- `COMPLETE`
- `DEFERRED`

Each active or deferred item records its behavior boundary and material risk.
Completed items record validation evidence. Coupled items may be grouped only
after explaining why independent changes would be unsafe and obtaining approval
for the combined boundary.

After each completed item, present the remaining checklist and recommend the
next focused review. A recommendation is not authorization to perform it.

## 5. Propose the Smallest Coherent Plan

The plan must state:

1. The intended behavioral contract.
2. The smallest safe implementation boundary.
3. Why any smaller alternative is unsafe or incomplete.
4. Expected files, interfaces, owners, and callers affected.
5. Identifier, concurrency, transaction, and existing-data consequences.
6. Failure, recovery, retry, and reconciliation semantics.
7. UI, API, CLI, protocol, deployment, bootstrap, and reset effects.
8. Tests and acceptance evidence.
9. Living-documentation and repository-graph updates.
10. Explicit non-goals and unaffected systems.
11. Unresolved operator decisions.

The blast-radius review must consider all eleven categories even when the
answer is `no change`. Do not recommend a locally small edit that transfers the
failure into a less visible state.

## 6. Stop for Implementation Approval

No source implementation begins while the workflow stage is
`INVESTIGATING`, `PLANNING`, or `AWAITING_IMPLEMENTATION_APPROVAL`.

Before coding, record in `agent_state.md`:

- The active objective.
- Checklist item or design-spec stage.
- Approved behavior and files or subsystems in scope.
- Explicit non-goals.
- Known risks accepted or deferred.
- The approval that activates implementation.

The existence of an accepted design spec, an earlier broad approval, or an old
handoff does not activate a new stage.

## 7. Implement Only the Approved Boundary

During implementation:

- Preserve one code path per behavior.
- Preserve identifier, enum, lock, ownership, and composition rules.
- Do not opportunistically fix adjacent checklist items.
- Preserve unrelated user work and inspect overlap before editing.
- Track every task file that belongs in the repository.
- Keep commentary concise and surface material discoveries promptly.
- Continue safe in-scope work while non-blocking questions are outstanding.

If an unapproved adjacent fault prevents a correct implementation, stop and
revise the plan rather than hide it with a workaround.

Delegation does not transfer approval. A subagent may gather only the evidence
or perform only the implementation explicitly delegated to it. The primary
agent remains responsible for reconciling findings, preventing overlapping
edits, performing the phase-end sweep, and enforcing this workflow.

## 8. Validate and Reconcile

Before declaring completion:

1. Add or update coverage for the fault, success contract, and material failure
   or concurrency paths.
2. Run the complete local non-external gate required by `agent.md`; focused
   selections require explicit operator instruction.
3. Run applicable syntax, type, schema, frontend, release, or deployment checks.
4. Run `git diff --check`.
5. Update living documentation when behavior or contracts changed.
6. Reconcile curated and generated repository-graph evidence and pass its
   check with no mismatch.
7. Update checklist status, workflow state, validation results, and remaining
   risks.

A failed required check means the task is not complete. Do not convert a known
failure into a documentation disclaimer merely to close the task.

## 9. Commit and Close Out

For a completed task that changes tracked files:

1. Review the final diff and staged file inventory.
2. Stage every task file that should be tracked.
3. Create one task-specific commit with a single-line summary.
4. Do not push unless explicitly requested.
5. Confirm the worktree is clean and the post-commit graph check still passes.
6. Report the outcome first, followed by material behavior changes, validation,
   commit identity, remaining risks, the updated checklist, and the recommended
   next item.

Do not amend unrelated history, create an empty commit, or describe work as
complete before its required evidence exists.

## 10. Pause and Resume

At interruption, pause, or handoff, use `AGENT_HANDOFF_TEMPLATE.md`. The durable
state must let a new agent answer without chat history:

- What stage is active?
- What exactly has been approved?
- What has not been approved?
- What changed?
- What evidence passed or remains?
- What risk or decision blocks the next stage?
- What are the next three actions?

Remove superseded handoff material rather than accumulating an alternate
history. Git remains the archive.
