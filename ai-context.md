# Versioned AI Context Index

This file routes agents to versioned context in `genai_data/`.

CONTEXT_DIRECTORY=genai_data/

## Authority Boundary

- `AGENTS.md` and `agent.md` contain the active agent constraints.
- Current code, schema, configuration, and tests are the evidence for current
  behavior. Documentation describes intended design and navigation, but a
  behavioral claim must be verified before it drives a change.
- Do not bulk-load `genai_data/`. Topical completion notes and fix summaries
  may be historical or branch-specific.
- `agent_state.md` is authoritative only when it explicitly names an active,
  operator-approved objective for the current checkout. Otherwise treat it as
  having no active handoff.

## Core read order

1. `genai_data/README.md` - Project overview and navigation
2. `genai_data/ORDER_ID_HANDLING.md` - `client_order_id` vs `order_id` rules (critical)
3. `genai_data/agent_state.md` - Active handoff only when its own status says one exists

Then read only what the task needs:

- `genai_data/ARCHITECTURE.md` - Runtime architecture, threading, and data flow
- `genai_data/MODULES.md` - Module ownership and where behavior lives
- `genai_data/DATA_MODELS.md` - Dataclasses, enums, and database schema snapshots
- `genai_data/CONFIGURATION.md` - Environment variables, products config, runtime knobs
- `genai_data/API_REFERENCE.md` - REST wrapper and dashboard WebSocket message contracts
- `genai_data/DEBUGGING_STRATEGY.md` - Practical debugging workflow for this codebase
- `genai_data/TESTING_STRATEGY.md` - Test inventory and validation guidance; `AGENTS.md` controls when the full gate is mandatory
- `genai_data/COMPREHENSIVE_TEST_SUITE.md` - Suite inventory and coverage map
- `genai_data/AGENT_CONSISTENCY_PROTOCOL.md` - Session context and pruning rules
- `genai_data/AGENT_HANDOFF_TEMPLATE.md` - Standard pause/resume handoff format

## Companion Files in Repo Root

- [AGENTS.md](AGENTS.md) - Session entry point + hard constraints
- [agent.md](agent.md) - Project-specific constraints and operational rules

## Temporary Debugging Tools

Reviewed source in `genai_tools/` is tracked; generated/runtime artifacts are
ignored. Open only a specifically relevant tool, inspect it before execution,
and never treat it as design authority. See `agent.md` section
"genai_tools Workflow".
