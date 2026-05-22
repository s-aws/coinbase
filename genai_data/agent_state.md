# Agent State

Use this file as the single durable source of truth for active engineering work.
Keep it short. Keep it factual.

## Metadata

- Last updated (ET): 2026-05-17
- Updated by: Codex
- Branch: main
- Commit (optional):

## Current Objective

- One-sentence objective: Define and maintain strict specialist ownership boundaries for this codebase.

## Hard Constraints

- Use `client_order_id` for internal tracking.
- Use `order_id` only for exchange-facing operations.
- Single code path per behavior.
- Use enums from `core/enums.py`.
- Respect locks and thread-safety invariants.
- Must pass `pytest tests/regression/ -v --tb=short` for non-agent-file changes.
- Exception: if only agent-instruction/context files changed (`AGENTS.md`, `agent.md`, `ai-context.md`, `genai_data/AGENT_*.md`, `genai_data/agent_state.md`), regression tests may be skipped.

## Active Scope

- In-scope files: `genai_data/AGENT_ARCHITECT.md`, `ai-context.md`, `genai_data/agent_state.md`, canonical docs in `genai_data/`, `agent.md`, and documentation needed for local-agent accuracy.
- Out-of-scope files: product catalogs and local order span JSON artifacts unless explicitly requested.
- Interfaces or modules that must not change without tests: dashboard WebSocket contract, stealth lifecycle, DB write paths.

## Decisions (Durable)

- [2026-05-16] Decision: Treat cancel/re-entry as policy-cancel/re-entry, not general hide-again behavior.
  - Reason: It cancels no-fill revealed placements and later re-enters through the normal reveal path, but it is not a general operator hide-again feature.
  - Impact: Docs must distinguish cancel/re-entry from the older UI Hide action and from any future standalone hide-again feature.

- [2026-05-16] Decision: Local test DB is `coinbase-dev-postgres` on host `127.0.0.1:9876` mapped to container port `5432`.
  - Reason: Postgres listens on container port `5432`; mapping host `9876` to container `9876` causes connection failures.
  - Impact: Regression DB tests should connect to port `9876` successfully when Docker is healthy.

- [2026-05-16] Decision: `order_parent` identifiers must be UUID text.
  - Reason: Downstream stealth joins use UUID-typed columns; non-UUID test ids can poison reconciliation.
  - Impact: `insert_order_parent` validates IDs before DB lookup/insert, and reconciliation skips legacy polluted non-UUID rows.

- [2026-05-17] Decision: `genai_data/AGENT_ARCHITECT.md` is the primary ownership-boundary document.
  - Reason: Specialist agents need one source of truth for module ownership, dependency rules, test routing, and coding conventions.
  - Impact: Future work should name one primary specialist owner, files in scope/out of scope, coordinating owners, canonical behavior path, and required tests before implementation.

- [2026-05-17] Decision: Public agent contracts live in tracked `docs/agents/` and `.agents/ownership.yaml`; `genai_data/` remains local expanded context.
  - Reason: The public repo needs repeatable ownership boundaries without publishing private model routing, prompts, evals, release gates, or private roadmap details.
  - Impact: Smaller public-facing agents should use the specialist packs plus the ownership manifest; private orchestration can map owner ids to models outside this repo.

- [2026-05-17] Decision: Root historical notes, diagnostics, manual demo tests, experimental UI, runtime output, and UI export JSON are archived or moved out of root.
  - Reason: Smaller agents need a cleaner root and fewer ambiguous files in their operating context.
  - Impact: Historical/public artifacts live under `docs/archive/v2/`; diagnostic/manual scripts live under `tools/diagnostics/`; CI rejects the cleaned root clutter categories.

## Open Risks

- Risk: Active-looking root UI files still need a Dashboard Contract Agent review before any move.
  - Severity: Medium
  - Mitigation: Keep them in root until route/bookmark/operator assumptions are checked.
  - Owner: Dashboard Contract Agent.

## Validation Status

- Last regression run: 2026-05-17 `pytest tests\regression\ -v --tb=short`
- Result: Passed, 505 tests. Public agent boundary update and cleanup also passed ownership checks, `python -m compileall -q tools`, and root-clutter guard checks.
- Failing tests (if any): None.

## Next 3 Actions

1. Have Dashboard Contract Agent review the remaining active root UI files before any move.
2. Use `docs/agents/AGENT_ARCHITECT.md` and `.agents/ownership.yaml` to assign one primary owner before non-trivial implementation work.
3. Run the root-clutter guard before adding new root-level artifacts.

## Handoff Notes

- What is done: Public agent contracts, ownership manifest, cleanup classifier, CI checks, and first cleanup batches are in place.
- What is in progress: Root UI cleanup remains intentionally conservative.
- What is blocked: Nothing currently known.
- Exact next command: `pytest tests\regression\ -v --tb=short` for the next non-agent-file change.
