"""Migration Guide: Transitioning to Refactored Coinbase Advanced Trading Engine

This guide explains how to migrate from the original monolithic OrderEngine
to the refactored modular architecture with Phase 1-4 modules.

## Migration Path Overview

The migration is designed to be **incremental and non-breaking**:

```
Step 1: No Changes
├─ Use original OrderEngine as-is
└─ All code works unchanged

Step 2: Optional Integration
├─ Wrap OrderEngine with OrderEngineIntegration
├─ Identical interface to original
└─ Access bridges for specialized operations

Step 3: Gradual Bridge Adoption
├─ Use CalculatorBridge for calculations
├─ Use ProcessorBridge for validation
├─ Use EventBridge for deduplication
└─ Replace OrderEngine methods incrementally

Step 4: Full Refactoring (Breaking Change)
├─ Refactor OrderEngine to use bridges directly
├─ Requires code updates in main.py
└─ Cleaner separation of concerns
```

## Step-by-Step Migration

### Migration Level 0: No Changes (Current State)

**Effort**: None
**Risk**: None
**Benefits**: None

```python
# main.py - Original code works as-is
from main import OrderEngine
from configuration import ORDERBOOK, ORDER_POST_ONLY, Subscription, API_KEY, API_SECRET
import database.order as DB_CLIENT

engine = OrderEngine(
    orderbook=ORDERBOOK,
    db_client=DB_CLIENT,
    subscription=Subscription,
    api_key=API_KEY,
    api_secret=API_SECRET,
    order_post_only=ORDER_POST_ONLY,
)
engine.run_forever()
```

### Migration Level 1: Add Integration Wrapper

**Effort**: 5 minutes (1 line change)
**Risk**: Negligible (wrapper only, no logic changes)
**Benefits**: Access to bridges, path to Phase 3 modules

```python
# main.py - Minimal changes
from main import OrderEngine
from configuration import ORDERBOOK, ORDER_POST_ONLY, Subscription, API_KEY, API_SECRET
import database.order as DB_CLIENT

engine = OrderEngine(
    orderbook=ORDERBOOK,
    db_client=DB_CLIENT,
    subscription=Subscription,
    api_key=API_KEY,
    api_secret=API_SECRET,
    order_post_only=ORDER_POST_ONLY,
)

# NEW: Wrap with integration (identical interface)
integrated = OrderEngineIntegration(engine)

# Same as before - all methods delegated
integrated.run_forever()
```

### Migration Level 2: Use Calculator Bridge

**Effort**: 30 minutes (refactor follow-up calculation)
**Risk**: Low (isolated domain)
**Benefits**: Cleaner order calculation logic, reusable across components

**Before**:
```python
# In OrderEngine.compute_order_template()
def calculate_order_template(...):
    # Inline calculation logic
    profit_target = self.resolve_profit_target(order)
    
    # Price calculation embedded
    if order['order_side'] == 'BUY':
        new_price = float(order['avg_price']) * (1 + profit_target)
    else:
        new_price = float(order['avg_price']) / (1 + profit_target)
    
    # Size extraction embedded
    filled_size = 0.0
    for field in ('filled_size', 'cumulative_quantity', 'base_size'):
        if field in order:
            filled_size = float(order[field])
            break
```

**After**:
```python
# In OrderEngine.__init__()
from integration.calculator_bridge import CalculatorBridge
self.calc_bridge = CalculatorBridge()

# In OrderEngine.compute_order_template()
def calculate_order_template(...):
    profit_target = self.resolve_profit_target(order)
    
    # Use bridge for calculation
    price_result = self.calc_bridge.calculate_follow_up_price(
        order, 
        opposite_side,
        profit_target
    )
    new_price = price_result['price']
    
    # Use bridge for size extraction
    filled_size = self.calc_bridge.calculate_follow_up_size(order)
```

### Migration Level 3: Use Processor Bridge

**Effort**: 45 minutes (refactor order processing)
**Risk**: Low (isolated domain)
**Benefits**: Reusable validation and enrichment logic

**Before**:
```python
# In OrderEngine.process_user_order()
def process_user_order(self, order):
    # Inline context building
    context = {
        "order_id": order.get("order_id"),
        "product_id": order.get("product_id"),
        "side": order.get("order_side") or order.get("side"),
        "status": order.get("status"),
        "price": self.order_limit_price_or_avg_price(order),
    }
    
    # Inline validation
    if "order_id" not in order:
        self.log_message("warning", "Missing order_id")
        return
```

**After**:
```python
# In OrderEngine.__init__()
from integration.processor_bridge import ProcessorBridge
self.proc_bridge = ProcessorBridge()

# In OrderEngine.process_user_order()
def process_user_order(self, order):
    # Use bridge for context
    context = self.proc_bridge.build_order_context(order)
    
    # Use bridge for validation
    is_valid, missing = self.proc_bridge.validate_order_fields(
        order,
        required_fields=['order_id', 'product_id', 'side', 'status']
    )
    if not is_valid:
        self.log_message("warning", f"Invalid order: missing {missing}")
        return
```

### Migration Level 4: Use Event Bridge

**Effort**: 60 minutes (refactor event deduplication)
**Risk**: Low (isolated domain)
**Benefits**: Reusable event deduplication, cleaner code

**Before**:
```python
# In OrderEngine.__init__()
self.seen_events = {
    i: set() for i in range(self.max_seen_event_buckets)
}

# In OrderEngine.on_message()
def on_message(self, msg):
    for event in json_msg["events"]:
        event_hash = self.hash_dict(event)  # Inline hashing
        
        # Inline dedup check
        with self.seen_events_lock:
            if any(event_hash in bucket for bucket in self.seen_events.values()):
                continue
        
        # ... enqueue ...
        
        # Inline mark seen
        with self.seen_events_lock:
            self.seen_events[self.seen_events_default_bucket].add(event_hash)

# In OrderEngine.rotate_seen_events_buckets()
def rotate_seen_events_buckets(self):
    # Inline rotation logic
    with self.seen_events_lock:
        for i in range(self.max_seen_event_buckets - 1, 0, -1):
            self.seen_events[i] = self.seen_events[i - 1]
        self.seen_events[0] = set()
```

**After**:
```python
# In OrderEngine.__init__()
from integration.event_bridge import EventBridge
self.evt_bridge = EventBridge(
    max_dedup_buckets=self.max_seen_event_buckets,
    dedup_bucket_duration_secs=self.max_rotate_seen_events_bucket_seconds,
)

# In OrderEngine.on_message()
def on_message(self, msg):
    for event in json_msg["events"]:
        # Use bridge for dedup check
        if self.evt_bridge.is_duplicate_event(event):
            continue
        
        # ... enqueue ...
        
        # Use bridge to mark seen
        self.evt_bridge.mark_event_seen(event)

# In OrderEngine.rotate_seen_events_buckets()
def rotate_seen_events_buckets(self):
    # Use bridge to rotate
    self.evt_bridge.rotate_dedup_buckets()
```

### Migration Level 5: Full Refactoring (Breaking Change)

**Effort**: 2-3 hours (complete OrderEngine refactoring)
**Risk**: High (breaking change, requires testing)
**Benefits**: Cleaner architecture, better separation of concerns

This would involve:
1. Removing duplicate logic from OrderEngine
2. Injecting bridges in constructor
3. Refactoring all method calls to use bridges
4. Comprehensive testing
5. Updating all consuming code

**Not recommended for most users** - Levels 0-4 provide all benefits.

## Migration Checklist

### Pre-Migration

- [ ] Review current code and understand dependencies
- [ ] Set up development environment
- [ ] Run original test suite: `pytest tests/test_phase*.py -v`
- [ ] Verify all 189 tests pass before migration
- [ ] Create feature branch for migration

### Migration Level 1: Integration Wrapper

- [ ] Import OrderEngineIntegration
- [ ] Wrap OrderEngine instance
- [ ] Update run call: `integrated.run_forever()`
- [ ] Test: All original functionality works
- [ ] Commit: "Add OrderEngineIntegration wrapper"

### Migration Level 2: Calculator Bridge

- [ ] Import CalculatorBridge
- [ ] Initialize in OrderEngine.__init__()
- [ ] Identify calculation methods (calculate_follow_up_price, etc.)
- [ ] Replace inline logic with bridge calls
- [ ] Test: `pytest tests/test_integration.py::TestCalculatorBridge -v`
- [ ] Commit: "Integrate CalculatorBridge for order calculations"

### Migration Level 3: Processor Bridge

- [ ] Import ProcessorBridge
- [ ] Initialize in OrderEngine.__init__()
- [ ] Identify validation/enrichment methods
- [ ] Replace inline logic with bridge calls
- [ ] Test: `pytest tests/test_integration.py::TestProcessorBridge -v`
- [ ] Commit: "Integrate ProcessorBridge for order processing"

### Migration Level 4: Event Bridge

- [ ] Import EventBridge
- [ ] Initialize in OrderEngine.__init__()
- [ ] Replace seen_events dedup logic with bridge calls
- [ ] Update rotation logic to use bridge
- [ ] Test: `pytest tests/test_integration.py::TestEventBridge -v`
- [ ] Commit: "Integrate EventBridge for event deduplication"

### Post-Migration

- [ ] Run complete test suite: `pytest tests/ -v`
- [ ] Verify all 189 tests pass
- [ ] Code review
- [ ] Deploy to staging
- [ ] Monitor performance and logs
- [ ] Deploy to production

## Testing During Migration

### Unit Test Migration

1. **Keep existing tests**: All Phase 1-3 tests remain unchanged
2. **Add integration tests**: Phase 4 tests verify bridges work
3. **No regression**: Original functionality preserved

### Running Tests at Each Level

```bash
# Level 0: Original code only
pytest tests/test_phase1.py tests/test_phase2.py tests/test_phase3.py -v

# Level 1: With integration wrapper
pytest tests/ -v  # All 189 tests

# Level 2: With calculator bridge
pytest tests/test_integration.py::TestCalculatorBridge -v

# Level 3: With processor bridge
pytest tests/test_integration.py::TestProcessorBridge -v

# Level 4: With event bridge
pytest tests/test_integration.py::TestEventBridge -v
```

## Rollback Plan

### Level 1 Rollback (Easy - 1 minute)

```python
# Simply remove the wrapper
# From:
integrated = OrderEngineIntegration(engine)
integrated.run_forever()

# To:
engine.run_forever()
```

### Level 2-4 Rollback (Moderate - 15 minutes)

1. Remove bridge initialization from __init__()
2. Revert method calls to original inline logic
3. Remove bridge imports
4. Re-run tests to verify

### Emergency Rollback

Keep a backup of the original main.py and database state. Restore both to return to pre-migration state.

## Performance Impact

### Expected Performance Changes

| Operation | Level 0 | Level 1 | Level 2-4 |
|-----------|---------|---------|-----------|
| Order processing | Baseline | +1% (wrapper overhead) | +0-2% (bridge overhead) |
| Event dedup | Baseline | +1% (wrapper overhead) | +0-1% (optimized dedup) |
| Memory usage | Baseline | Baseline | Baseline |
| Startup time | Baseline | +50ms (imports) | +100ms (imports) |

**Verdict**: Migration has negligible performance impact (<2% in all scenarios).

## Troubleshooting

### Issue: Import Error: "No module named 'integration'"

**Solution**: Ensure integration directory and __init__.py exist
```bash
ls integration/
# Should show: __init__.py, calculator_bridge.py, processor_bridge.py, event_bridge.py, engine_integration.py
```

### Issue: AttributeError: 'OrderEngineIntegration' has no attribute 'X'

**Solution**: OrderEngineIntegration delegates to wrapped engine. Check:
1. Method exists in OrderEngine
2. Spelling is correct
3. Method is not private (starts with _)

### Issue: Bridge initialization fails

**Solution**: Ensure Phase 3 modules are installed
```bash
python -c "from business.order_calculator import OrderCalculator; print('OK')"
python -c "from business.order_processor import OrderProcessor; print('OK')"
python -c "from business.event_processor import EventProcessor; print('OK')"
```

### Issue: Tests fail after migration

**Solution**: Common causes
1. Dependency not installed: `pip install -e .`
2. PYTHONPATH not set: Include project root
3. Database connection: Verify PostgreSQL is running
4. API credentials: Check configuration.py

## Success Criteria

✅ Successful migration when:
1. All 189 tests pass
2. No regressions in order processing
3. No regressions in follow-up creation
4. No regressions in event handling
5. Performance within 2% of baseline
6. Code review approved
7. Deployed to staging without issues

## Recommended Approach

**For most users**: Stop at **Level 1** (Integration Wrapper)
- Provides path to Phase 3 modules
- No breaking changes
- Can adopt bridges gradually
- Maintains original OrderEngine functionality

**For advanced users**: Proceed to **Level 4**
- Cleaner code organization
- Fully leverages Phase 3 modules
- Better separation of concerns
- Requires comprehensive testing

**For contributors**: Implement **Level 5** (Full Refactoring)
- Requires deep understanding of architecture
- Breaking change to OrderEngine
- Better long-term maintainability
- Recommended post-1.0 release

## Support and Questions

For migration questions:
1. Review this guide
2. Check tests/ directory for examples
3. Review architecture documentation
4. Open an issue with context

---

**Document Version**: 1.0
**Last Updated**: April 2026
**Migration Difficulty**: Easy (Level 1) to Moderate (Level 4)
**Estimated Total Time**: 30 minutes to 2 hours (depending on level)
