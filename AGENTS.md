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

- Use `client_order_id` for all internal tracking; use `order_id` only for exchange APIs.
  Public rules: `docs/agents/INVARIANTS.md`. Expanded local rules: `genai_data/ORDER_ID_HANDLING.md` when present.
- Single code path per behavior; do not introduce parallel implementations.
- Use enums (`core/enums.py`), not magic strings.
- Respect existing module locks; never bypass thread-safety.
- Stealth order local state must reflect live exchange reality. Do not mark a revealed order hidden, cancelled, or moved unless the corresponding live Coinbase placement has been handled through the existing cancel/move/reconcile path.
- Cancel/re-entry is not general hide-again behavior. It is a narrower policy for no-fill revealed stealth placements: cancel the active placement, hold in policy-cancelled hidden state, then re-enter through the normal reveal path.
- All non-agent-file changes must pass `pytest tests/regression/ -v` before being considered done.
  Exception: if the change set is limited to agent-instruction/context files only (`AGENTS.md`, `agent.md`, `ai-context.md`, `.agents/ownership.yaml`, `docs/agents/*.md`, `genai_data/AGENT_*.md`, `genai_data/agent_state.md`), regression tests may be skipped.

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
