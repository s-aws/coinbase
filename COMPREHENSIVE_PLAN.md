# Comprehensive Documentation Plan for Coinbase AGENTS Repository

## Overview
This document outlines the comprehensive plan for implementing documentation changes based on the documentation change plan. The changes focus on improving documentation for key components, data models, and agent functionality in the Coinbase AGENTS repository.

## Key Files and Changes Required

### 1. Core Data Models Documentation
Based on the change plan, several core data models need enhanced documentation:

#### core/models.py
- **RepricingState TypedDict**: Add detailed documentation for all fields including:
  - active_placement_client_order_id / active_exchange_order_id
  - active_exchange_price
  - current_logical_limit_price
  - last_reprice_at / next_reprice_at
  - reprice_reason
  - reprice_history
  - last_profitability_block_reason
  - reveal_condition_price_offsets
  - post_fill_retreat_offset / post_fill_retreat_count

- **Product class**: Document all fields:
  - product_id, product_type, base_increment, quote_increment, price_increment
  - base_min_size, trading_disabled

- **Position class**: Document all fields:
  - product_id, side, number_of_contracts, current_price, entry_price

- **Wallet class**: Document all fields:
  - currency, available_balance, total_balance, created_at, updated_at, deleted_at

- **Order class**: Document all fields:
  - client_order_id, product_id, order_side, status, size, price, filled_size, limit_price, avg_price, order_id, product_type, created_at, custom_metadata

- **RevealExecutionPlan class**: Add comprehensive documentation for all attributes and their purposes

- **StealthMovePlan class**: Add detailed documentation for all attributes and their purposes

- **RepricingPolicy class**: Add comprehensive documentation for all fields and behavior helpers

### 2. Agent Architecture Documentation
Based on the change plan, several agent-related documentation files need updates:

#### docs/agents/README.md
- Add documentation for agent contracts and ownership
- Include information about coding invariants
- Document public test commands
- Add information about public roadmap items
- Include non-secret agent role descriptions

#### docs/agents/AGENT_ARCHITECT.md
- Document the agent architecture in detail
- Include information about agent ownership boundaries
- Add coding invariants and public test commands
- Document public roadmap items and non-secret agent role descriptions

#### docs/agents/INVARIANTS.md
- Document the key invariants that must be followed
- Include specific rules about client_order_id vs order_id usage
- Document single code path per behavior requirements
- Add information about enum usage and thread-safety
- Include stealth order state management requirements

#### docs/agents/OWNERSHIP.md
- Document the ownership boundaries for agent files
- Include information about the ownership checker
- Add details about enforcement mechanisms

### 3. Business Logic Documentation
Based on the change plan, several business logic components need documentation:

#### business/cancel_reentry_policy.py
- Add comprehensive documentation for the CancelReentryPolicy class
- Document the cancel/re-entry flow for no-fill revealed stealth placements
- Include information about policy-cancelled hidden state

#### business/hotpoint_detector.py
- Document the HotpointDetector functionality
- Include information about thread-safe windowed fill-rate trigger
- Add details about log-spaced buckets

#### business/hotpoint_rate_limiter.py
- Document the HotpointRateLimiter functionality
- Include information about sliding-window rate limiting

#### business/position_lot.py
- Add documentation for PositionLot class
- Document the immutable position lot concept

### 4. Integration and Bridge Documentation
Based on the change plan, several integration components need documentation:

#### bridges/stealth_order_bridge.py
- Document the bridge functionality between stealth orders and the system
- Include information about the dashboard_server.py integration

#### integration/fill_event_hooks.py
- Add documentation for fill event hooks
- Include information about integration with the system

#### integration/order_placement_hooks.py
- Document order placement hooks
- Include information about pre-submission validation

### 5. API and Configuration Documentation
Based on the change plan, several API and configuration files need documentation:

#### configuration.py
- Document configuration parameters and their usage
- Include information about default values and validation

#### core/enums.py
- Add comprehensive documentation for all enums
- Include information about OrderSide, OrderStatus, ProductType, etc.

### 6. Test and Quality Documentation
Based on the change plan, several test and quality documentation files need updates:

#### tests/README.md
- Document test structure and organization
- Include information about regression testing requirements

#### docs/agents/AGENT_TEST_QUALITY.md
- Document test quality requirements for agents
- Include information about test coverage and validation

### 7. Specific Implementation Requirements from Change Plan

#### Key Invariants to Document
- Use `client_order_id` for all internal tracking; use `order_id` only for exchange APIs
- Single code path per behavior; do not introduce parallel implementations
- Use enums (`core/enums.py`), not magic strings
- Respect existing module locks; never bypass thread-safety
- Stealth order local state must reflect live exchange reality
- Cancel/re-entry is not general hide-again behavior - it's a narrower policy for no-fill revealed stealth placements
- Same-side post-fill retreat is a hidden-order policy only

#### Key Features to Document
- Stealth order lifecycle management
- Reveal condition evaluation
- Adaptive slice sizing
- Pre/post submission hook pipeline
- In-memory cache plus database persistence
- Parent-child integration through order_parent table
- O(1) revealed-order reverse lookup

### 8. Implementation Approach

#### Phase 1: Core Data Model Documentation
1. Update core/models.py with detailed docstrings for all classes and TypedDicts
2. Add comprehensive field documentation for RepricingState, Product, Position, Wallet, Order, etc.
3. Document behavior helpers in RepricingPolicy class

#### Phase 2: Agent Architecture Documentation
1. Update docs/agents/README.md with comprehensive agent contracts
2. Create or update AGENT_ARCHITECT.md with detailed architecture
3. Document INVARIANTS.md with all key invariants
4. Update OWNERSHIP.md with ownership boundaries

#### Phase 3: Business Logic Documentation
1. Add documentation to business/cancel_reentry_policy.py
2. Document business/hotpoint_detector.py and business/hotpoint_rate_limiter.py
3. Add documentation to business/position_lot.py

#### Phase 4: Integration Documentation
1. Update bridges/stealth_order_bridge.py documentation
2. Document integration/fill_event_hooks.py and integration/order_placement_hooks.py
3. Add configuration.py documentation

#### Phase 5: Test and Quality Documentation
1. Update tests/README.md with test structure
2. Document AGENT_TEST_QUALITY.md with test quality requirements

### 9. Verification Requirements
- All documentation changes must be verified against actual code
- Changes must follow the repository's documentation style and format
- All new documentation must be consistent with existing documentation
- Key invariants and requirements must be clearly stated and easily discoverable
- Examples and usage patterns should be included where appropriate

### 10. Priority Order
1. Core data models (highest priority)
2. Agent architecture and invariants (high priority)
3. Business logic components (medium priority)
4. Integration components (medium priority)
5. Test and quality documentation (low priority)
