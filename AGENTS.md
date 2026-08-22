# AGENTS.md - Session Entry Point

This project runs on **Windows 11 + VS Code**. Linux/bash commands may not work as-is.

## Required Reading (in this order)

1. **[agent.md](agent.md)** - Project-specific constraints (flat hierarchy, never-edit files, testing commands, dashboard architecture)
2. **[ai-context.md](ai-context.md)** - Index and authority rules for versioned context in `genai_data/`
3. Read only the task-relevant `genai_data/` files routed by `ai-context.md`; do not load the directory wholesale.
4. Inspect a `genai_tools/` file only when the task names it or evidence gathering requires it. The directory is never authoritative context.
5. **Codex only:** route non-trivial repository work through `codex_repo_graph/ENTRYPOINT.md`; other agents do not need to load that directory.

## Hard Constraints (non-negotiable)

- Use `client_order_id` for all internal tracking; use `order_id` only for exchange APIs.
  Full rules: `genai_data/ORDER_ID_HANDLING.md`.
- Single code path per behavior; do not introduce parallel implementations.
- Use enums (`core/enums.py`), not magic strings.
- Respect existing module locks; never bypass thread-safety.
- All non-agent-file changes must pass `pytest tests/regression/ -v` before being considered done.
  Exception: if the change set is limited to agent-instruction/context files only (`AGENTS.md`, `agent.md`, `ai-context.md`, `genai_data/AGENT_*.md`, `genai_data/agent_state.md`), regression tests may be skipped.

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
