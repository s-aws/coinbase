# Public Agent Contracts

This directory contains the public, non-secret operating contracts for agent
work on this repository.

The public repo may contain:

- ownership boundaries
- coding invariants
- public test commands
- public roadmap items
- non-secret agent role descriptions

The public repo must not contain:

- model names or routing rules
- private prompts
- eval logs
- private release gates
- private in-progress roadmap details
- secrets or environment-specific credentials

Private orchestration may read this repo. Public code must never import, read,
or require files from private orchestration repos.

## Documentation Index

This directory serves as the index for all agent-related documentation in the repository.

### Core Agent Documentation

- [Agent Architecture](AGENT_ARCHITECT.md) - High-level overview of the agent system design
- [Coding Invariants](INVARIANTS.md) - Essential rules and constraints that must be followed
- [Ownership Boundaries](OWNERSHIP.md) - Agent ownership and responsibility boundaries
- [Test Quality Standards](AGENT_TEST_QUALITY.md) - Requirements for agent testing and quality assurance

### Agent Component Documentation

- [Agent Bridge Hook](AGENT_BRIDGE_HOOK.md) - Documentation for bridge hooks
- [Agent Calculation](AGENT_CALCULATION.md) - Calculation agent specifications
- [Agent Configuration](AGENT_CONFIGURATION.md) - Configuration agent specifications
- [Agent Core Types](AGENT_CORE_TYPES.md) - Core type definitions for agents
- [Agent Dashboard Contract](AGENT_DASHBOARD_CONTRACT.md) - Dashboard integration contracts
- [Agent Exchange Integration](AGENT_EXCHANGE_INTEGRATION.md) - Exchange integration specifications
- [Agent Fill Audit](AGENT_FILL_AUDIT.md) - Fill audit agent specifications
- [Agent Market Analytics](AGENT_MARKET_ANALYTICS.md) - Market analytics agent specifications
- [Agent Ops Diagnostics](AGENT_OPS_DIAGNOSTICS.md) - Operations diagnostics agent specifications
- [Agent Order Lifecycle](AGENT_ORDER_LIFECYCLE.md) - Order lifecycle management
- [Agent Persistence](AGENT_PERSISTENCE.md) - Data persistence agent specifications
- [Agent Runtime Lifecycle](AGENT_RUNTIME_LIFECYCLE.md) - Runtime lifecycle management
- [Agent Stealth Lifecycle](AGENT_STEALTH_LIFECYCLE.md) - Stealth order lifecycle management
- [Agent Strategy](AGENT_STRATEGY.md) - Strategy agent specifications

## Read Order

1. [Agent Architecture](AGENT_ARCHITECT.md)
2. [Coding Invariants](INVARIANTS.md)
3. [Ownership Boundaries](OWNERSHIP.md)
4. The specialist context pack for the files in scope
5. [.agents/ownership.yaml](../../.agents/ownership.yaml)

## Enforcement

Use the ownership checker to inspect changed files:

```powershell
python tools/check_ownership.py
```

To enforce one owner explicitly:

```powershell
python tools/check_ownership.py --owner stealth_lifecycle
```

Pull requests use [.github/PULL_REQUEST_TEMPLATE.md](../../.github/PULL_REQUEST_TEMPLATE.md) to record the primary
owner, canonical behavior path, focused tests, and public/private boundary
check. GitHub Actions runs [.github/workflows/public-agent-checks.yml](../../.github/workflows/public-agent-checks.yml) to make
sure changed files are covered by [.agents/ownership.yaml](../../.agents/ownership.yaml).

Use the cleanup classifier before moving or archiving files:

```powershell
python tools/classify_repo_files.py --format markdown
```

Focused checks do not replace the required regression gate for non-agent-file
changes:

```powershell
pytest tests/regression/ -v --tb=short
```
