"""Migration Level 5: Full Refactoring - Implementation Plan

**Status**: PLANNED (Ready to Execute)
**Effort**: 2-3 hours
**Risk**: High (Breaking change)
**Breaking Changes**: Yes - All OrderEngine consumers must update imports

## Scope Analysis

### What Level 5 Accomplishes

1. **Removes duplicate calculation logic** - Uses CalculatorBridge exclusively
2. **Removes duplicate validation logic** - Uses ProcessorBridge exclusively  
3. **Removes duplicate event logic** - Uses EventBridge exclusively
4. **Cleaner architecture** - No redundant code, single source of truth
5. **Better maintainability** - Changes to logic happen in one place

### What Gets Removed

#### From CalculatorBridge Domain
- Inline profit target calculations in `compute_order_template()`
- Inline size extraction from multiple fields
- Inline position change calculations

#### From ProcessorBridge Domain  
- Inline order context building scattered across methods
- Inline order validation checks
- Inline order enrichment logic

#### From EventBridge Domain
- Inline event hashing and deduplication in `on_message()`
- Inline event bucket rotation in `rotate_seen_events_buckets()`
- Inline event filtering logic

### Code Metrics (Estimated)

| Metric | Current | After Level 5 |
|--------|---------|--------------|
| OrderEngine LOC | ~1700 | ~1300 |
| Duplicate logic | Multiple | Zero |
| Bridge usage | Optional | Required |
| Direct imports from Phase 3 | None | None (via bridges) |

## Implementation Plan

### Phase 1: Calculator Bridge Integration
**Goal**: Replace all calculation logic with bridge calls

#### 1.1 Refactor `compute_order_template()`
- Replace inline price calculation with `calc_bridge.calculate_follow_up_price()`
- Replace inline size extraction with `calc_bridge.calculate_follow_up_size()`
- Remove all inline profit target logic

#### 1.2 Refactor `handle_filled_order()` / `handle_cancelled_order()`
- Use `calc_bridge.should_create_follow_up()` for eligibility check
- Use `calc_bridge.calculate_position_change()` for position updates
- Remove duplicate position update logic

#### 1.3 Remove helper methods (if only used for calculation)
- Evaluate `resolve_order_size()` - move to bridge if not used elsewhere
- Evaluate `resolve_profit_target()` - move to bridge if not used elsewhere
- Clean up `order_limit_price_or_avg_price()` - consolidate with bridge

**Estimated**: 30-40 minutes | Tests after: All pass (critical phase)

### Phase 2: Processor Bridge Integration
**Goal**: Replace all validation/enrichment logic with bridge calls

#### 2.1 Refactor `process_user_order()`
- Use `proc_bridge.build_order_context()` for context
- Use `proc_bridge.validate_order_fields()` for validation
- Use status check methods (`is_filled_order()`, `is_cancelled_order()`, etc.)

#### 2.2 Refactor validation scattered throughout
- Replace inline order_id/status/product_id checks
- Use `proc_bridge.order_matches_product()` for product matching
- Use `proc_bridge.enrich_order_with_calculated_fields()` where applicable

#### 2.3 Remove/consolidate helper methods
- Consolidate `build_order_log_context()` - check if bridge provides this
- Remove `build_follow_up_order_log_context()` - redundant wrapper
- Evaluate `normalize_product_type()` - see if bridge provides

**Estimated**: 40-50 minutes | Tests after: All pass (critical phase)

### Phase 3: Event Bridge Integration
**Goal**: Replace all event deduplication/filtering with bridge calls

#### 3.1 Refactor `on_message()`
- Replace `hash_dict()` with `evt_bridge.hash_event()`
- Replace dedup check with `evt_bridge.is_duplicate_event()`
- Replace marking seen with `evt_bridge.mark_event_seen()`
- Remove `seen_events` dict and related locks (EventBridge handles this)

#### 3.2 Refactor `rotate_seen_events_buckets()`
- Replace entire implementation with `evt_bridge.rotate_dedup_buckets()`
- Remove `seen_events_default_bucket` tracking
- Remove `seen_events_lock` if not used elsewhere

#### 3.3 Refactor event filtering
- Use `evt_bridge.filter_events_by_channel()`
- Use `evt_bridge.filter_events_by_product()`
- Use `evt_bridge.should_process_event()`

#### 3.4 Clean up __init__()
- Remove: `self.seen_events = {...}`
- Remove: `self.seen_events_lock = threading.Lock()` (if only used for events)
- Remove: `self.seen_events_default_bucket = 0`
- Keep: Bridge initialization

**Estimated**: 20-30 minutes | Tests after: All pass (critical phase)

### Phase 4: Cleanup & Testing
**Goal**: Remove demonstration methods, verify all changes work

#### 4.1 Remove demonstration methods (no longer needed)
- Delete `calculate_follow_up_details_using_bridge()`
- Delete `validate_and_process_order_using_bridge()`
- Delete `process_event_using_bridge()`
- Delete `build_follow_up_order_log_context()` (thin wrapper)

#### 4.2 Remove helper methods that are now redundant
- Evaluate `safe_float()` - check if bridge handles this
- Evaluate `order_limit_price_or_avg_price()` - check if bridge provides
- Remove any other wrapper methods

#### 4.3 Comprehensive testing
- Run all 189 tests: `pytest tests/ -v`
- Test order placement: `python main_place_order.py`
- Verify websocket integration: start engine, check logs
- Manual testing of critical flows

#### 4.4 Update documentation
- Create LEVEL5_COMPLETION.md with before/after code
- Update main.py docstrings to reflect bridge-only architecture
- Document any breaking changes for consumers

**Estimated**: 30-40 minutes | Final tests: All pass + manual verification

## Breaking Changes Alert

### What Changes for Consumers

#### If You Import OrderEngine Directly
```python
# BEFORE (Current)
from main import OrderEngine
engine = OrderEngine(...) 
# Still works - all logic in OrderEngine

# AFTER (Level 5)
from main import OrderEngine
engine = OrderEngine(...)
# OrderEngine now ONLY coordinates - all logic in bridges
# Behavior is identical, but implementation is different
```

#### If You Use OrderEngine Methods
```python
# Methods that change internally (but same external interface):
- compute_order_template()
- handle_filled_order()
- handle_cancelled_order()
- process_user_order()
- on_message()
- rotate_seen_events_buckets()

# Methods that are removed (if they were dead code):
- Demonstration methods: calculate_follow_up_details_using_bridge(), etc.
- Thin wrappers: build_follow_up_order_log_context()
- Redundant helpers (identified during cleanup)
```

#### If You Access Internal State
```python
# BEFORE: Can access orderbook, db_client, bridges
engine.orderbook  # ✓ Still works
engine.calc_bridge  # ✓ Still works

# AFTER: Same access, but internal implementation cleaner
engine.orderbook  # ✓ Still works
engine.calc_bridge  # ✓ Still works
```

### Non-Breaking (Compatible)

✅ Public API (method signatures) remains the same
✅ OrderEngine initialization stays the same
✅ All configuration imports still work
✅ Database integration unchanged
✅ WebSocket integration unchanged
✅ All 189 tests should still pass

## Risk Mitigation

### How to Minimize Risk

1. **Commit frequently** - After each phase, commit with clear message
2. **Test constantly** - Run tests after EVERY significant change
3. **Revert strategy** - If tests fail, revert back and proceed slower
4. **Review carefully** - Each phase affects critical code paths

### Safety Checkpoints

- [ ] Start: All 189 tests passing
- [ ] After Phase 1: All tests still pass, calculation logic verified
- [ ] After Phase 2: All tests still pass, validation logic verified  
- [ ] After Phase 3: All tests still pass, event logic verified
- [ ] After Phase 4: All tests + manual verification pass

## Execution Strategy

### Recommended Approach

1. **Start with Phase 1** (Calculator Bridge) - most isolated
2. **If Phase 1 works**, proceed to Phase 2 (Processor Bridge) - medium isolation
3. **If Phase 2 works**, proceed to Phase 3 (Event Bridge) - most integrated
4. **If Phase 3 works**, proceed to Phase 4 (Cleanup) - final polish

### If Something Breaks

```bash
# Easy rollback
git diff  # See what changed
git checkout -- main.py  # Revert to last commit
pytest tests/ -v  # Verify tests pass again
```

## Deliverables (Post Level 5)

### Code Changes
- Complete refactored main.py
- Cleaner OrderEngine (fewer lines, no duplication)
- All bridges actively used

### Documentation
- LEVEL5_COMPLETION.md with before/after
- Updated main.py docstrings
- Breaking changes documented

### Testing
- All 189 tests passing
- Manual verification of critical flows
- Performance metrics (should be identical)

## Timeline

| Phase | Duration | Cumulative | Checkpoint |
|-------|----------|-----------|-----------|
| Setup | 5 min | 5 min | Plan review ✓ |
| Phase 1 | 35 min | 40 min | Tests pass |
| Phase 2 | 45 min | 85 min | Tests pass |
| Phase 3 | 25 min | 110 min | Tests pass |
| Phase 4 | 35 min | 145 min | Tests + manual |
| **Total** | **145 min** | **145 min** | **Production Ready** |

## Ready to Proceed?

To start Level 5, confirm:
- [ ] Plan reviewed and understood
- [ ] You have 2-3 hours available
- [ ] You're prepared for breaking changes
- [ ] You have backup/git history available
- [ ] You understand rollback procedure

Proceeding in 5, 4, 3, 2, 1...
