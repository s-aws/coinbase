# AI Context Marker

This file marks `genai_data/` as the canonical AI context directory for this project.

CONTEXT_DIRECTORY=genai_data/

## Read in this order

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
13. `genai_data/agent_state.md` - Durable handoff state
14. `genai_data/AGENT_HANDOFF_TEMPLATE.md` - Standard pause/resume handoff format

## Companion Files in Repo Root

- [AGENTS.md](AGENTS.md) - Session entry point + hard constraints
- [agent.md](agent.md) - Project-specific constraints and operational rules

## Temporary Debugging Tools

`genai_tools/` (gitignored) is for ad-hoc debugging scripts and scoped probes.
See `agent.md` section "genai_tools Workflow".
