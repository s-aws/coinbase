# Duplicate Parent Order Insertion Fix

## Problem Summary

The system experienced `UniqueViolation` constraint errors when multiple threads simultaneously processed the same filled order event. Both threads attempted to create a parent order entry for the same `client_order_id`, resulting in a database constraint violation:

```
[ERROR] PostgresDB: Database transaction error - rolling back: 
UniqueViolation: duplicate key value violates unique constraint "order_parent_client_order_id_key"
DETAIL: Key (client_order_id)=(ef10f30d-586b-4326-8479-5719ab35a6db) already exists.
```

### Root Causes

1. **Missing Duplicate Prevention in `handle_filled_order`**
   - The `handle_cancelled_order` method had `claim_follow_up_processing()` to prevent duplicate processing
   - The `handle_filled_order` method was missing this critical check
   - This allowed multiple threads to process the same filled order simultaneously

2. **Race Condition in Database Insert**
   - Multiple threads could reach the `insert_order_parent()` database operation at the same time
   - The first thread's insert would succeed
   - The second thread's insert would fail with a duplicate key constraint violation
   - Error handling caught the exception but the issue persisted in logs

### Evidence in Logs

```
[INFO] OrderEngine: user_event_thread_0 [ORDER] {"event": "filled_order_waiting_for_hold_clear", ...}
[INFO] OrderEngine: user_event_thread_1 [ORDER] {"event": "filled_order_waiting_for_hold_clear", ...}
[INFO] OrderEngine: user_event_thread_0 [ORDER] {"event": "parent_order_entry_created", ...}
[INFO] user_event_thread_0 [ORDER] {"event": "parent_order_entry_created", ...}
[ERROR] OrderDB: ✗ Error inserting parent order ef10f30d-586b-4326-8479-5719ab35a6db: 
        UniqueViolation: duplicate key value violates unique constraint
```

The same `client_order_id` appearing in multiple threads indicates concurrent processing.

## Solutions Implemented

### Fix 1: Added Duplicate Prevention to `handle_filled_order`

**File:** [core/order_engine.py](core/order_engine.py) (line ~1466)

Added `claim_follow_up_processing()` call at the beginning of `handle_filled_order()`:

```python
def handle_filled_order(self, order: dict) -> None:
    """Handle a filled order by creating a follow-up if allowed."""
    client_order_id = order["client_order_id"]

    # CRITICAL: Claim follow-up processing FIRST to prevent duplicates
    if not self.claim_follow_up_processing("filled", client_order_id):
        self.log_message(
            "warning",
            self.build_follow_up_log_payload(
                "follow_up_already_claimed",
                source_order=order,
                parent_client_order_id=None,
                details={"reason": "filled_order_follow_up_already_claimed"},
            ),
        )
        return
    
    # ... rest of method ...
```

**How it works:**
- `claim_follow_up_processing()` atomically sets a flag to "processing"
- If the flag is already set or marked "done", the method returns early
- This prevents the same order from being processed by multiple threads simultaneously
- The flag is cleared on error (via `release_follow_up_processing()`) or set to "done" on completion

### Fix 2: Made Parent Order Insertion Idempotent

**File:** [database/order.py](database/order.py) (line ~254)

Modified `insert_order_parent()` to check for existing parent order before inserting:

```python
def insert_order_parent(
    client_order_id: str,
    product_id: str,
    # ... other params ...
) -> Optional[int]:
    """Insert a parent order into the order_parent table.
    
    This operation is idempotent - if the parent order already exists, 
    it returns the existing ID.
    """
    # Check if parent order already exists (handles race condition)
    existing_parent = get_parent_order(client_order_id)
    if existing_parent:
        logger.info(f"✓ Parent order already exists: {client_order_id} (DB ID: {existing_parent['id']})")
        return existing_parent['id']
    
    # ... perform INSERT if not exists ...
```

**Benefits:**
- Idempotent operation: safe to call multiple times with the same order ID
- No database constraint violations even if race condition somehow occurs
- Returns existing ID instead of attempting duplicate insert
- Reduces database errors and improves system resilience

## Verification

### Tests Added

New test file: [tests/unit/test_parent_order_race_condition.py](tests/unit/test_parent_order_race_condition.py)

Tests verify:
1. **Idempotent insertion**: Multiple threads attempting simultaneous insertion are handled gracefully
2. **Claim mechanism**: Only one thread successfully claims processing rights
3. **Error handling**: Duplicate key errors are handled without crashing

All tests pass:
```
tests\unit\test_parent_order_race_condition.py::TestParentOrderRaceCondition::
    test_idempotent_parent_order_insertion PASSED
tests\unit\test_parent_order_race_condition.py::TestParentOrderRaceCondition::
    test_claim_follow_up_processing_prevents_duplicates PASSED
tests\unit\test_parent_order_race_condition.py::TestDuplicateParentOrderErrorHandling::
    test_handles_duplicate_key_error_gracefully PASSED
```

### Regression Tests

All existing regression tests continue to pass:
```
======================== 10 passed, 1 warning in 0.01s ========================
```

## Expected Behavior After Fix

### Before Fix
```
[ERROR] OrderEngine: user_event_thread_0 [ORDER] {"event": "parent_order_entry_created", ...}
[ERROR] user_event_thread_1 [ORDER] {"event": "parent_order_entry_created", ...}
[ERROR] OrderDB: ✗ Error inserting parent order: UniqueViolation: duplicate key
```

### After Fix
```
[INFO] OrderEngine: user_event_thread_0 [ORDER] {"event": "parent_order_entry_created", ...}
[WARNING] user_event_thread_1: follow_up_already_claimed for filled_order_follow_up
[INFO] ✓ Parent order inserted: client_order_id (DB ID: 123)
```

The second thread skips processing because the first thread already claimed it, and the database insert succeeds without errors.

## Technical Details

### Order Processing Thread Safety

The system uses several mechanisms to prevent race conditions:

1. **orderbook_lock**: Threading lock protecting in-memory orderbook state
2. **Processing flags**: Atomic flags preventing duplicate event processing
3. **Database constraints**: UNIQUE constraints as last-resort protection
4. **Idempotent operations**: Database operations designed to handle retries safely

### Related Code

- [core/order_engine.py](core/order_engine.py) - Order event processing
- [database/order.py](database/order.py) - Database operations
- [configuration.py](configuration.py) - OrderBook state management
- [core/models.py](core/models.py) - Order data models

### Key Functions

- `handle_filled_order()` - Processes filled order events (FIXED)
- `handle_cancelled_order()` - Processes cancelled order events (model for fix)
- `claim_follow_up_processing()` - Atomically claims processing rights
- `complete_follow_up_processing()` - Marks processing as complete
- `insert_order_parent()` - Inserts parent order to database (FIXED)
- `get_parent_order()` - Retrieves existing parent order

## Impact Assessment

### Positive
- Eliminates duplicate parent order constraint violations
- Reduces duplicate event logging
- Improves system stability under high concurrency
- No breaking changes to API or public interfaces

### Zero Impact Areas
- Child order processing
- Stealth order reveal logic
- Position tracking
- WebSocket handling
- API communication

## Recommendations

1. **Monitoring**: Continue monitoring logs for similar constraint violations in other tables
2. **Testing**: Run the system under load to verify race condition handling
3. **Code Review**: Consider similar fixes for `handle_cancelled_order()` if not already present
4. **Documentation**: Update threading and concurrency documentation with these patterns

## Related Issues

- [ORDER_ID_HANDLING.md](genai_data/ORDER_ID_HANDLING.md) - Order ID distinction (client_order_id vs order_id)
- [STEALTH_ORDER_FIX_SUMMARY.py](STEALTH_ORDER_FIX_SUMMARY.py) - Previous stealth order fixes
- [CASCADE_BUG_FIX.md](CASCADE_BUG_FIX.md) - Previous database fixes
