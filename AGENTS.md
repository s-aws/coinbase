# AGENTS.md - Session Entry Point

This project runs on **Windows 11 + VS Code**. Linux/bash commands may not work as-is.

## Required Reading (in this order)

1. **[agent.md](agent.md)** - Project-specific constraints (flat hierarchy, never-edit files, testing commands, dashboard architecture)
2. **[docs/agents/README.md](docs/agents/README.md)** - Public agent contracts and ownership entry point
3. **[.agents/ownership.yaml](.agents/ownership.yaml)** - Machine-readable owner map for changed files
4. **[ai-context.md](ai-context.md)** - Index into expanded docs in `genai_data/` when present
5. **`genai_data/`** - Local expanded project docs (`README.md`, `ARCHITECTURE.md`, `ORDER_ID_HANDLING.md`, `TESTING_STRATEGY.md`, and related references) when present
6. **`genai_tools/`** - Temporary debugging scripts and scoped investigation notes

## Hard Constraints (non-negotiable)

- Use `client_order_id` for all internal tracking; use `order_id` only for exchange-native evidence and endpoints that require it. Coinbase cancellation is the explicit exception: use the project wrapper `cancel_order(client_order_id)` because Coinbase accepts our client id for that operation.
  Public rules: `docs/agents/INVARIANTS.md`. Expanded local rules: `genai_data/ORDER_ID_HANDLING.md` when present.
- Single code path per behavior; do not introduce parallel implementations.
- Use enums (`core/enums.py`), not magic strings.
- Respect existing module locks; never bypass thread-safety.
- Stealth order local state must reflect live exchange reality. Do not mark a revealed order hidden, cancelled, or moved unless the corresponding live Coinbase placement has been handled through the existing cancel/move/reconcile path.
- Cancel/re-entry is not general hide-again behavior. It is a narrower policy for no-fill revealed stealth placements: cancel the active placement, hold in policy-cancelled hidden state, then re-enter through the normal reveal path.
- Same-side post-fill retreat is a hidden-order policy only. It may retreat opted-in hidden orders and update their reveal/anchor state, but it must not locally mutate live revealed placements.

## P0 - Honest Feedback, Not Engagement Optimization

The user has explicitly opted out of yes-man behavior and validation-seeking responses.
Apply to every non-trivial decision, design proposal, business idea, or "what do you think" question:

- **Lead with the disagreement, the risk, or the unflattering numbers.** Do not bury them under three paragraphs of qualifiers.
- **Compare against industry standards, named competitors, or known-better practices** when those exist.
- **Surface what the user did NOT ask** when it materially affects the answer (regulatory burden, hidden costs, distribution problems, second-order effects).
- **Recommend against** when the evidence supports it. "Don't" is a valid first word.
- **No empty validation** ("Great question!", "That's a really interesting idea!"). No softening preambles. No artificial enthusiasm.
- Honesty is **respect**, not rudeness. Stay professional, stay specific, skip the cushioning.

If a recommendation would land softer than the evidence warrants, the recommendation is wrong.


## Verification Gate Requirements

- Documentation, roadmap, prompt catalog metadata, or agent-instruction-only changes: validate formatting/links or targeted validators as applicable; regression may be skipped.
- Leaf validation scripts, isolated acceptance policies, or narrow tests: run the focused unit/regression tests and validator commands that cover the changed file.
- Workflow-local controller changes: run focused controller/regression tests and live prompt proof when runtime-facing.
- Shared controller, router, formatter, tool-selection, model-routing, mutation, fixture, or approval behavior: run focused tests that cover the changed behavior before completion.
- Runtime-facing behavior: run focused tests, live validation through the relevant localhost ports, AnythingLLM proof when applicable, and both frozen fixture checks when those surfaces are affected.
- Cross-cutting, release-candidate, model-portability, skill-library-scale, or unbounded-blast-radius changes: run the focused checks that cover the changed behavior before ordinary phase completion.
- Full `tests/regression/` is a durable milestone closeout gate, not an ordinary phase gate. The canonical policy is [docs/REGRESSION_PROCESS.md](docs/REGRESSION_PROCESS.md): run it before durable milestone closeout, public/release-candidate handoff, deployment approval/closeout, release-hardening closeout, Admin API/backend association closeout, or explicit user request. The canonical runner validates the regression serial-lane classification before running pytest; regression files that touch shared DB cursors, fixed service ports, process-global state, or other process-shared resources must use `pytest.mark.serial`, while false positives require a `parallel-regression: serial-safe` comment with the reason.

Canonical full regression closeout command:

```bash
python tools/run_parallel_regression.py --workers 4
```

Use the sequential fallback only when `pytest-xdist` is unavailable and the
fallback is intentional:

```bash
pytest tests/regression/ -v --tb=short
```

## Subagent Hygiene

- At the end of each phase, close subagents that were spawned for that phase after their findings have been consumed, remediated, or explicitly deferred.
- At durable milestone closeout, perform a final stale-subagent sweep and leave no completed, failed, or superseded subagents open unless they are part of an active handoff.
- Do not close a subagent that is still running required validation, producing required evidence, or awaiting a user decision.
