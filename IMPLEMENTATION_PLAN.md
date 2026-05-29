# Implementation Plan for Documentation Changes

## Executive Summary
This document provides a focused implementation plan for the documentation changes required based on the documentation change plan. The plan prioritizes the most critical documentation updates that directly address the identified gaps in the codebase documentation.

## Priority 1: Core Data Model Documentation (High Priority)

### 1. core/models.py - Enhanced Documentation

#### RepricingState TypedDict
**Current Status**: Partially documented
**Required Changes**:
- Add comprehensive field documentation for all fields in RepricingState
- Document the purpose and semantics of each field
- Include examples of when each field is populated
- Add information about persistence (JSONB in stealth_orders.anchor_repricing_state_json)

#### Product Class
**Current Status**: Partially documented
**Required Changes**:
- Add detailed docstring explaining the purpose of the class
- Document all fields with their meanings and data types
- Include information about from_dict method usage

#### Position Class
**Current Status**: Partially documented
**Required Changes**:
- Add detailed docstring explaining the purpose of the class
- Document all fields with their meanings and data types
- Include information about from_dict method usage

#### Wallet Class
**Current Status**: Partially documented
**Required Changes**:
- Add detailed docstring explaining the purpose of the class
- Document all fields with their meanings and data types
- Include information about from_dict method usage

#### Order Class
**Current Status**: Partially documented
**Required Changes**:
- Add comprehensive docstring explaining the purpose of the class
- Document all fields with their meanings and data types
- Include information about from_dict method usage and special handling for order_side

#### RevealExecutionPlan Class
**Current Status**: Partially documented
**Required Changes**:
- Add comprehensive documentation for all attributes and their purposes
- Document the class's role in stealth order reveal planning
- Include information about how it's used in the reveal process

#### StealthMovePlan Class
**Current Status**: Partially documented
**Required Changes**:
- Add detailed documentation for all attributes and their purposes
- Document the move process and its constraints
- Include information about audit-friendliness requirements

#### RepricingPolicy Class
**Current Status**: Partially documented
**Required Changes**:
- Add comprehensive documentation for all fields and behavior helpers
- Document the policy's role in anchor-repricing
- Include information about from_dict and to_dict methods
- Document all behavior helpers like compute_distance_bands, clamp_to_step, etc.

## Priority 2: Agent Architecture and Invariants (High Priority)

### 2. docs/agents/INVARIANTS.md
**Current Status**: Likely exists but may need enhancement
**Required Changes**:
- Document all key invariants from the change plan
- Include specific rules about client_order_id vs order_id usage
- Document single code path per behavior requirements
- Add information about enum usage and thread-safety
- Include stealth order state management requirements

### 3. docs/agents/AGENT_ARCHITECT.md
**Current Status**: Likely exists but may need enhancement
**Required Changes**:
- Document the agent architecture in detail
- Include information about agent ownership boundaries
- Add coding invariants and public test commands
- Document public roadmap items and non-secret agent role descriptions

## Priority 3: Business Logic Components (Medium Priority)

### 4. business/cancel_reentry_policy.py
**Current Status**: Likely lacks comprehensive documentation
**Required Changes**:
- Add comprehensive documentation for the CancelReentryPolicy class
- Document the cancel/re-entry flow for no-fill revealed stealth placements
- Include information about policy-cancelled hidden state
- Document the specific use case and constraints

### 5. business/hotpoint_detector.py
**Current Status**: Likely lacks comprehensive documentation
**Required Changes**:
- Document the HotpointDetector functionality
- Include information about thread-safe windowed fill-rate trigger
- Add details about log-spaced buckets
- Document the purpose and usage in the system

### 6. business/hotpoint_rate_limiter.py
**Current Status**: Likely lacks comprehensive documentation
**Required Changes**:
- Document the HotpointRateLimiter functionality
- Include information about sliding-window rate limiting
- Document the purpose and usage in the system

### 7. business/position_lot.py
**Current Status**: Likely lacks comprehensive documentation
**Required Changes**:
- Add documentation for PositionLot class
- Document the immutable position lot concept
- Include information about its role in the system

## Priority 4: Integration Components (Medium Priority)

### 8. bridges/stealth_order_bridge.py
**Current Status**: Likely lacks comprehensive documentation
**Required Changes**:
- Document the bridge functionality between stealth orders and the system
- Include information about the dashboard_server.py integration
- Document the purpose and usage of the bridge

### 9. integration/fill_event_hooks.py
**Current Status**: Likely lacks comprehensive documentation
**Required Changes**:
- Add documentation for fill event hooks
- Include information about integration with the system
- Document the purpose and usage of hooks

### 10. integration/order_placement_hooks.py
**Current Status**: Likely lacks comprehensive documentation
**Required Changes**:
- Document order placement hooks
- Include information about pre-submission validation
- Document the purpose and usage of hooks

## Priority 5: Configuration and Enums (Low Priority)

### 11. configuration.py
**Current Status**: Likely lacks comprehensive documentation
**Required Changes**:
- Document configuration parameters and their usage
- Include information about default values and validation
- Document the purpose of each configuration setting

### 12. core/enums.py
**Current Status**: Likely lacks comprehensive documentation
**Required Changes**:
- Add comprehensive documentation for all enums
- Include information about OrderSide, OrderStatus, ProductType, etc.
- Document the purpose and usage of each enum value

## Implementation Timeline

### Phase 1: Core Data Models (Week 1)
- Complete documentation for all classes in core/models.py
- Focus on RepricingState, Product, Position, Wallet, Order, RevealExecutionPlan, StealthMovePlan, RepricingPolicy
- Ensure all field documentation is complete and accurate

### Phase 2: Agent Architecture (Week 2)
- Update docs/agents/INVARIANTS.md with all key invariants
- Update or create docs/agents/AGENT_ARCHITECT.md
- Update docs/agents/OWNERSHIP.md with ownership boundaries

### Phase 3: Business Logic (Week 3)
- Add documentation to business/cancel_reentry_policy.py
- Document business/hotpoint_detector.py and business/hotpoint_rate_limiter.py
- Add documentation to business/position_lot.py

### Phase 4: Integration Components (Week 4)
- Update bridges/stealth_order_bridge.py documentation
- Document integration/fill_event_hooks.py and integration/order_placement_hooks.py
- Add configuration.py documentation

### Phase 5: Configuration and Enums (Week 5)
- Add documentation to configuration.py
- Add comprehensive documentation to core/enums.py

## Verification Process

1. **Code Review**: All documentation changes must be reviewed against actual code
2. **Consistency Check**: New documentation must be consistent with existing documentation style
3. **Invariance Verification**: All key invariants must be clearly stated and easily discoverable
4. **Example Integration**: Include examples and usage patterns where appropriate
5. **Cross-Reference Validation**: Ensure all cross-references between documentation and code are accurate

## Success Criteria

- All core data models have comprehensive documentation
- All key invariants are clearly documented and easily discoverable
- Agent architecture documentation is complete and accurate
- Business logic components have appropriate documentation
- Integration components are well-documented
- Configuration and enum documentation is complete
- All documentation follows repository style and format