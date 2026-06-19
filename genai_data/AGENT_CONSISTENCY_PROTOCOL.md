# Agent Consistency Protocol

## Why This Exists

Long chat history reduces coding-agent reliability. This protocol keeps context short, explicit, and testable so behavior stays consistent across sessions.

## P0 - Honest Feedback, Not Engagement Optimization

The user has explicitly opted out of yes-man behavior and validation-seeking responses.
Apply to every non-trivial decision, design proposal, business idea, or "what do you think" question:

- **Lead with the disagreement, the risk, or the unflattering numbers.** Do not bury them under
  three paragraphs of qualifiers.
- **Compare against industry standards, named competitors, or known-better practices** when
  those exist.
- **Surface what the user did NOT ask** when it materially affects the answer (regulatory burden,
  hidden costs, distribution problems, second-order effects).
- **Recommend against** when the evidence supports it. "Don't" is a valid first word.
- **No empty validation** ("Great question!", "That's a really interesting idea!"). No softening
  preambles. No artificial enthusiasm.
- Honesty is **respect**, not rudeness. Stay professional, stay specific, skip the cushioning.

If a recommendation would land softer than the evidence warrants, the recommendation is wrong.

## Non-Negotiable Rules

1. Use a durable state file: `genai_data/agent_state.md`.
2. Rehydrate at session start from:
   - `agent.md`
   - `ai-context.md`
   - `genai_data/README.md`
   - `genai_data/ORDER_ID_HANDLING.md`
   - `genai_data/agent_state.md`
3. Keep active working context limited to:
   - Current goal
   - Hard constraints
   - Files in scope
   - Open risks
   - Next 3 actions
4. Prune context every 20-30 minutes or after each milestone.
5. Do not carry unresolved assumptions forward. Convert them to explicit risks in `agent_state.md`.
6. Use one code path per behavior. Do not implement parallel logic.
7. Run focused tests and validators for the changed behavior before marking
   ordinary phase work complete. Reserve full `pytest tests/regression/ -v`
   for durable milestone closeout, public/release-candidate handoff, or
   explicit user request. If the change set is limited to
   agent-instruction/context files only (`AGENTS.md`, `agent.md`,
   `ai-context.md`, `docs/agents/*.md`, `genai_data/AGENT_*.md`,
   `genai_data/agent_state.md`), regression tests may be skipped.

## Session Start Checklist

1. Read required docs in order.
2. Open `genai_data/agent_state.md`.
3. Confirm:
   - Current objective
   - Hard constraints
   - In-scope files
   - Pending risks
4. If objective changed, start a fresh session and archive old handoff notes.

## In-Session Operating Rules

1. Every substantial step updates one of these:
   - `Decisions`
   - `Open Risks`
   - `Next Actions`
2. Keep intermediate notes short and factual.
3. If scope expands, record it before coding.
4. If state is unclear, stop and rehydrate from `agent_state.md` and canonical docs.

## Handoff Standard

At pause or completion, write a handoff using `genai_data/AGENT_HANDOFF_TEMPLATE.md` and copy durable facts into `genai_data/agent_state.md`.

## Forced Reset Triggers

Start a new session when any of these happens:

1. Scope changes from bugfix to feature work (or vice versa).
2. More than 10 files become active without a clear single objective.
3. Repeated contradictory decisions appear in notes.
4. The agent cannot state the current objective in one sentence.

## What Not To Do

1. Do not rely on raw chat history as the source of truth.
2. Do not store long reasoning dumps in the state file.
3. Do not skip focused validation for "small" behavior changes; choose the
   narrowest test or validator that proves the changed path.
4. Do not leave assumptions undocumented.
