# AI Context Marker

This file marks `genai_data/` as the local expanded AI context directory for this project.
Public, tracked agent contracts live in `docs/agents/` and `.agents/ownership.yaml`.

CONTEXT_DIRECTORY=genai_data/

## Public Tracked Agent Context

1. `docs/agents/README.md` - Public agent contract entry point
2. `docs/agents/AGENT_ARCHITECT.md` - Architect role and assignment checklist
3. `docs/agents/INVARIANTS.md` - Public engineering invariants
4. `docs/agents/OWNERSHIP.md` - Human-readable ownership boundaries
5. `.agents/ownership.yaml` - Machine-readable ownership manifest
6. `docs/agents/AGENT_<ROLE>.md` - Specialist context packs
7. `docs/agents/PUBLIC_PRIVATE_SPLIT.md` - Public/private repository split rules

## Local Expanded Context Read Order

1. `genai_data/README.md` - Project overview and navigation
2. `genai_data/ARCHITECTURE.md` - Runtime architecture, threading, and data flow
3. `genai_data/ORDER_ID_HANDLING.md` - `client_order_id` vs `order_id` rules (critical)
4. `genai_data/MODULES.md` - Module ownership and where behavior lives
5. `genai_data/DATA_MODELS.md` - Dataclasses, enums, and database schema snapshots
6. `genai_data/CONFIGURATION.md` - Environment variables, products config, runtime knobs
7. `genai_data/API_REFERENCE.md` - REST wrapper and dashboard WebSocket message contracts
8. `genai_data/DEBUGGING_STRATEGY.md` - Practical debugging workflow for this codebase
9. `genai_data/TESTING_STRATEGY.md` - Required test commands and change validation workflow
10. `genai_data/COMPREHENSIVE_TEST_SUITE.md` - Current suite inventory and coverage map
11. `genai_data/AGENT_CONSISTENCY_PROTOCOL.md` - Session context and pruning rules
12. `genai_data/AGENT_ARCHITECT.md` - Specialist ownership boundaries and dependency rules
13. `genai_data/AGENT_MVP_REBUILD_GOAL.md` - Current MVP scope and stop rules
14. `genai_data/agent_state.md` - Historical M57 handoff snapshot; not current authority
15. `genai_data/AGENT_HANDOFF_TEMPLATE.md` - Standard pause/resume handoff format

## Companion Files in Repo Root

- [AGENTS.md](AGENTS.md) - Session entry point + hard constraints
- [agent.md](agent.md) - Project-specific constraints and operational rules
- Backend `origin/prod` is legacy source material for MVP translation; inspect
  it before inventing behavior, then implement only through backend-owned Admin
  API/BFF contracts with audit, caps, local deployment evidence, and tests.

## Temporary Debugging Tools

`genai_tools/` (gitignored) is for ad-hoc debugging scripts and scoped probes.
See `agent.md` section "genai_tools Workflow".
