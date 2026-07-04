# AGENTS.md - Session Entry Point

This project runs on **Windows 11 + VS Code**. Linux/bash commands may not work as-is.

## Required Reading (in this order)

1. **[agent.md](agent.md)** - Project-specific constraints (flat hierarchy, never-edit files, testing commands, dashboard architecture)
2. **[ai-context.md](ai-context.md)** - Index into canonical docs in `genai_data/`
3. **`genai_data/`** - Authoritative project docs (`README.md`, `ARCHITECTURE.md`, `ORDER_ID_HANDLING.md`, `TESTING_STRATEGY.md`, and related references)
4. **`genai_tools/`** - Temporary debugging scripts and scoped investigation notes

## Hard Constraints (non-negotiable)

- Use `client_order_id` for all internal tracking; use `order_id` only for exchange APIs.
  Full rules: `genai_data/ORDER_ID_HANDLING.md`.
- Single code path per behavior; do not introduce parallel implementations.
- Use enums (`core/enums.py`), not magic strings.
- Respect existing module locks; never bypass thread-safety.
- All non-agent-file changes must pass `pytest tests/regression/ -v` before being considered done.
  Exception: if the change set is limited to agent-instruction/context files only (`AGENTS.md`, `agent.md`, `ai-context.md`, `genai_data/AGENT_*.md`, `genai_data/agent_state.md`), regression tests may be skipped.

## Legacy Source Material

- The branch `origin/prod` may contain useful information about the legacy
  system, especially `dashboard_server.py`, `core/order_engine.py`,
  `core/stealth_order_manager.py`, Coinbase wrapper behavior, product/account/
  fill references, and historical regression tests.
- Treat `origin/prod` as source material, not as product authority. Do not
  restore direct dashboard/WebSocket trading authority or bypass Admin API
  authorization, caps, idempotency, audit, and local deployment evidence.
- When a current MVP behavior is unclear, compare the current branch with
  `origin/prod` using non-destructive reads such as `git show origin/prod:<path>`
  or a temporary worktree, then translate only MVP-aligned behavior into the
  backend Admin API/BFF path with focused tests.
- When available, also read
  `C:\coinbase-frontend\docs\ORIGIN_PROD_FEATURE_MVP_MAP.md` before translating
  legacy behavior into Admin MVP work.

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
