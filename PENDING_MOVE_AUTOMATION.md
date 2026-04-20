# Order Move Automation - Implementation Summary

## What Was Added

You asked: *"Does it make sense that the MoveManager can move opened orders as well as cancelled orders... setting a flag so that when it is cancelled, it is not handled by anything but the MoveManager?"*

**Answer: YES! This is now fully implemented.**

## Pending Move Automation ✅

The move mechanism now supports **automated moves** for cancelled orders. You can:

1. **Pre-mark** an opened/pending order for automatic move BEFORE it cancels
2. When that order cancels, OrderEngine **automatically**:
   - Detects the pending move flag
   - Creates the new parent order
   - Executes the move atomically
   - Prevents normal follow-up child order creation

## How It Works

### Step 1: Pre-Mark the Order (Before Cancellation)

```python
from business.move_manager import MoveManager

move_manager = MoveManager()

# Mark order for automatic move when it cancels
result = move_manager.pre_mark_for_move(
    original_parent_client_order_id="my_order_uuid",
    new_order_details={
        "product_id": "BTC-USDC",
        "side": "SELL",           # Can switch direction
        "size": 0.5,              # Can change size
        "price": 43000.0,
        "target_movement": 0.01,
        "max_order_replacement": 5
    },
    reason="auto_reversal",
    notes="Switch to sell if this order cancels"
)

if result["success"]:
    print(f"Pre-marked for auto-move: {result['move_id']}")
    # Order is now monitored - when it cancels, move will auto-execute
```

### Step 2: Order Cancels → Auto-Execution

When the pre-marked order is cancelled:

```
CANCELLED EVENT arrives
    ↓
OrderEngine.handle_cancelled_order() called
    ↓
Checks for pending move flag → FOUND ✓
    ↓
MoveManager.execute_pending_move_for_order()
    ├─ Creates new parent order
    ├─ Sets new_parent_client_order_id
    ├─ Marks move as executed
    └─ Logs "pending_move_auto_executed" event
    ↓
Returns immediately (NO child order created)
```

## Database Implementation

### order_moves Table Columns

```sql
-- For PENDING moves (not yet executed):
move_on_cancel = TRUE
new_parent_client_order_id = NULL      -- Will be set when executed
moved_at = NULL                        -- Will be set when executed

-- For COMPLETED moves (executed):
move_on_cancel = FALSE
new_parent_client_order_id = "uuid"    -- Set to new parent
moved_at = 2026-04-20 14:32:10        -- Execution timestamp
```

## API - MoveManager Methods

### Pre-Mark for Automation

```python
result = move_manager.pre_mark_for_move(
    original_parent_client_order_id="order_to_mark",
    new_order_details={...},
    reason="auto_move_scheduled",
    notes="Pending config stored here"
)
# Returns: {"success": bool, "move_id": int, "error": str}
```

### Execute Pending Move (Called Automatically)

```python
result = move_manager.execute_pending_move_for_order(
    original_parent_client_order_id="cancelled_order"
)
# Called by OrderEngine.handle_cancelled_order()
# Returns: {"success": bool, "new_parent_client_order_id": str}
```

### Database Functions

```python
from database.order import (
    get_pending_move,           # Get pending move record
    has_pending_move,           # Check if pending move exists
    create_pending_move,        # Pre-mark for move
    execute_pending_move        # Execute the move (set new parent)
)
```

## Test Coverage - All Passing ✅

**7 new tests for pending move automation:**

- `test_pre_mark_for_move` - Pre-marking an order
- `test_pre_mark_missing_fields` - Error handling
- `test_pre_mark_order_not_found` - Validation
- `test_pre_mark_duplicate_pending_move` - Prevents duplicate marks
- `test_execute_pending_move_for_order` - Auto-execution
- `test_execute_pending_move_no_pending` - Error when none exists
- `test_pending_move_stores_config` - Config storage

**Plus 18 existing tests for manual moves** - All 25 tests passing

## OrderEngine Integration

### Automatic Detection & Execution

The OrderEngine automatically handles pending moves:

```python
# In core/order_engine.py - handle_cancelled_order()
def handle_cancelled_order(self, order: dict) -> None:
    # ... resolve parent ...
    
    # ✨ NEW: Check for pending move
    if has_pending_move(parent_client_order_id):
        move_result = execute_pending_move_for_order(parent_client_order_id)
        if move_result["success"]:
            # Move executed automatically - return without creating child
            return
    
    # ... normal follow-up handling ...
```

**Key Behavior:**
- If pending move exists AND executes successfully → Skip normal follow-up (no child order)
- If pending move exists BUT fails → Fall through to normal follow-up
- If no pending move → Normal follow-up processing

## Use Cases

### 1. Scheduled Strategy Swaps

```python
# Monday: Create order for BTC position
order1 = place_order("BTC-USDC", "BUY", ...)

# Pre-mark for swap if it cancels
pre_mark_for_move(
    order1_id,
    new_order_details={
        "product_id": "ETH-USDC",  # Switch to ETH
        "side": "BUY",
        "size": 10.0,
        "price": 2500.0,
        ...
    },
    reason="strategy_swap_if_cancelled"
)
# If order1 cancels for any reason, automatically swap to ETH
```

### 2. Automated Failover

```python
# Primary order with aggressive settings
primary = place_order("BTC-USDC", "BUY", size=1.0, price=42000)

# If cancels, fall back to conservative strategy
pre_mark_for_move(
    primary.id,
    new_order_details={
        "size": 0.5,              # Reduce size
        "price": 41500.0,         # More conservative price
        "target_movement": 0.02,  # Higher profit target
    },
    reason="auto_failover"
)
```

### 3. Size Reduction on Market Impact

```python
# Large order with contingency
order = place_order("BTC-USDC", "BUY", size=5.0)

# If it cancels due to market conditions, try smaller order
pre_mark_for_move(
    order.id,
    new_order_details={
        "size": 2.0,  # Reduce by 60%
        "price": get_current_price()  # Use market price
    },
    reason="fallback_smaller_order"
)
```

## Manual Move Still Works

You can still move orders **manually** after they cancel:

```python
# Order cancelled, now decide what to do
result = move_manager.move_order(
    original_parent_client_order_id="cancelled_order_id",
    new_order_details={...},
    reason="manual_intervention"
)
```

**Both modes coexist:**
- Automation: Pre-mark before cancellation
- Manual: Move anytime after cancellation (or instead of pre-mark)

## Configuration Storage

Pre-marked move configurations are stored as JSON in the `notes` field:

```json
{
  "notes": "Automatic reversal\n\nPending move config: {\"product_id\": \"BTC-USDC\", \"side\": \"SELL\", \"size\": 0.5, ...}"
}
```

When executed, the config is extracted and used to create the new parent order with exact settings.

## Important Notes

⚠️ **Key Behaviors**

1. **Prevents Duplicate Marks** - Order can only have one pending move at a time
2. **Atomic Execution** - New parent creation and move recording happen together
3. **Prevents Child Order** - When pending move executes, normal follow-up is skipped
4. **Preserves Original** - Original parent order status unchanged (for audit)
5. **Fallback Logic** - If pending move fails, falls through to normal processing
6. **Configuration Preserved** - Settings stored and applied when order cancels

## Next Steps

1. ✅ **Database** - Updated `order_moves` table with `move_on_cancel` column
2. ✅ **MoveManager** - Added `pre_mark_for_move()` and `execute_pending_move_for_order()`
3. ✅ **OrderEngine** - Integrated pending move detection into `handle_cancelled_order()`
4. ✅ **Tests** - 7 new tests, all passing
5. ✅ **Documentation** - Updated MOVE_MECHANISM.md with full automation guide

## Files Changed

- `database/order.py` - Pending move functions
- `business/move_manager.py` - Pre-mark and execute methods
- `core/order_engine.py` - Pending move detection in cancellation handler
- `tests/unit/test_order_moves.py` - 7 new tests for automation
- `genai_data/MOVE_MECHANISM.md` - Automation documentation
- `__dangerous_delete_all_tables__.py` - Updated table initialization

## Testing

```bash
# Run all 25 move tests
pytest tests/unit/test_order_moves.py -v

# Run just pending move tests
pytest tests/unit/test_order_moves.py::TestPendingMoves -v
```

All tests passing ✅
