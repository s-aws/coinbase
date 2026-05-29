# Coinbase AGENTS Repository

This repository contains the core agent-based trading system for Coinbase. It implements sophisticated trading strategies including stealth orders, adaptive repricing, and intelligent order management.

## Documentation Index

This README serves as the primary index for all important documentation in this repository. All documentation should be discoverable through this index or its linked documents.

## Quick Start & Installation

- [Quick Start Guide](QUICK_START.md) - Get up and running quickly
- [Installation Guide](INSTALLATION.md) - Detailed installation instructions

### Core Agent Architecture

- [Agent Architecture](docs/agents/AGENT_ARCHITECT.md) - High-level overview of the agent system design
- [Coding Invariants](docs/agents/INVARIANTS.md) - Essential rules and constraints that must be followed
- [Ownership Boundaries](docs/agents/OWNERSHIP.md) - Agent ownership and responsibility boundaries
- [Test Quality Standards](docs/agents/AGENT_TEST_QUALITY.md) - Requirements for agent testing and quality assurance

### Quick Start & Installation

- [Quick Start Guide](QUICK_START.md) - Get up and running quickly
- [Installation Guide](INSTALLATION.md) - Detailed installation instructions

### Core Data Models

- [Core Models](core/models.py) - Primary data structures used throughout the system
- [Enums](core/enums.py) - Type definitions and enumerations used in the system

### Business Logic Components

- [Cancel Reentry Policy](business/cancel_reentry_policy.py) - Logic for handling no-fill revealed stealth placements
- [Hotpoint Detector](business/hotpoint_detector.py) - Detection of market hotpoints for strategic decision making
- [Hotpoint Rate Limiter](business/hotpoint_rate_limiter.py) - Rate limiting based on hotpoint detection
- [Position Lot](business/position_lot.py) - Immutable position lot management

### Integration Components

- [Stealth Order Bridge](bridges/stealth_order_bridge.py) - Bridge between stealth orders and system components
- [Fill Event Hooks](integration/fill_event_hooks.py) - Integration points for fill events
- [Order Placement Hooks](integration/order_placement_hooks.py) - Integration points for order placement

### Configuration

- [System Configuration](configuration.py) - System configuration parameters

### Testing

- [Test Documentation](tests/README.md) - Structure and guidelines for testing

### External Resources

- [Adaptive Fee Regime Integration](docs/ADAPTIVE_FEE_REGIME_INTEGRATION.md) - Integration with adaptive fee systems
- [Coinbase WebSocket Reference](docs/COINBASE_WEBSOCKET_REFERENCE.md) - WebSocket integration details
- [Last Fill Anchored Repricing Design](docs/LAST_FILL_ANCHORED_REPRICING_DESIGN.md) - Repricing strategy documentation
- [External Testing Runbook](docs/EXTERNAL_TESTING_RUNBOOK.md) - External testing procedures
- [Public Roadmap](docs/PUBLIC_ROADMAP.md) - Public development roadmap
- [Repository Cleanup Classification](docs/REPO_CLEANUP_CLASSIFICATION.md) - Guidelines for repository cleanup

### Archived Documentation

- [Archived v2 Documentation](docs/archive/v2/) - Historical documentation and design decisions

## Repository Structure

```
.
├── bridges/                 # Bridge components connecting different systems
├── business/                # Business logic components
├── core/                    # Core data models and utilities
├── docs/                    # Documentation files
│   ├── agents/              # Agent-specific documentation
│   └── archive/             # Historical documentation
├── integration/             # Integration hooks and adapters
├── tests/                   # Test files
├── configuration.py         # System configuration
├── main.py                  # Main application entry point
├── dashboard_server.py      # Dashboard WebSocket server
└── README.md                # This file
```

## Key Invariants

All code in this repository must follow these core invariants:

1. Use `client_order_id` for all internal tracking; use `order_id` only for exchange APIs
2. Single code path per behavior; do not introduce parallel implementations
3. Use enums (`core/enums.py`), not magic strings
4. Respect existing module locks; never bypass thread-safety
5. Stealth order local state must reflect live exchange reality
6. Cancel/re-entry is not general hide-again behavior - it's a narrower policy for no-fill revealed stealth placements
7. Same-side post-fill retreat is a hidden-order policy only

## Development Workflow

1. Review the [Agent Architecture](docs/agents/AGENT_ARCHITECT.md) and [Coding Invariants](docs/agents/INVARIANTS.md) before making changes
2. Use the ownership checker to verify file ownership: `python tools/check_ownership.py`
3. Run regression tests: `pytest tests/regression/ -v --tb=short`
4. Follow the [Implementation Plan](IMPLEMENTATION_PLAN.md) for documentation updates

## Contributing

Please see the [Pull Request Template](.github/PULL_REQUEST_TEMPLATE.md) for contribution guidelines.

## Important Files

- [Main Application](main.py) - Entry point for the application
- [Dashboard Server](dashboard_server.py) - WebSocket server for UI integration
- [Order Management](order.py) - Core order handling logic
- [Test Infrastructure](tests/README.md) - Test suite documentation and structure