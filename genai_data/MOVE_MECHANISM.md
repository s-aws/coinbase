# Order Move Mechanism

## Overview

The **Order Move** mechanism is a feature for handling cancelled orders that need to be replaced with new orders. Unlike the regular parent/child follow-up mechanism, moves **replace the parent/child relationship entirely** by creating a new parent order instead of a child order.

## Key Differences: Move vs Parent/Child

### Parent/Child Mechanism (Existing)
- When a parent order fills or cancels, a **child order** is created
- Child order remains linked to the original parent via `parent_client_order_id`
- Multiple children can be created from the same parent (up to `max_order_replacement`)
- Good for: Scaling out of positions, taking profit steps, continuing existing strategies

```
┌─────────────────┐
│   Parent Order  │
│  (original)     │
└────────┬────────┘
         │
    ┌────┴─────┬──────────┐
    ▼          ▼          ▼
  Child 1    Child 2    Child 3
  (filled)   (pending)  (pending)
```

### Move Mechanism (New)
- When a parent order cancels and is "moved", a **new parent order** is created
- Original parent remains in database (status unchanged) for audit
- Move relationship is recorded in `order_moves` table
- No child orders of the original parent are affected
- Good for: Completely replacing strategy, price adjustments, manual interventions

```
┌─────────────────┐        ┌──────────────────────┐
│  Parent Order   │        │  New Parent Order    │
│  (original)     │        │  (replacement)       │
│  CANCELLED      │───────▶│  NEW STRATEGY        │
└─────────────────┘        │  PENDING             │
                           └──────────────────────┘
                                    │
                            ┌───────┴────────┐
                            ▼                ▼
                          Child 1          Child 2
                         (of new parent)
```

## Design Principle: Flat Parent-Child Hierarchy

⚠️ **All child orders ALWAYS link to their original parent, never to other children.**

This creates a **flat, single-level hierarchy**:

```
Original Parent
├── Child 1 (filled)
│   └─ Creates follow-up...
├── Child 2 (new follow-up from Child 1, still points to Original Parent)
├── Child 3 (cancelled)
│   └─ Would create follow-up if enabled...
└── Child 4 (follow-up from Child 3)
```

### Key Rules

1. **No grandchildren** - When a child order fills or cancels and creates a follow-up, the new order is still a child of the original parent
2. **Cancelled parents don't create children** - If a parent is cancelled:
   - If pre-marked with a move (`move_on_cancel=TRUE`), the move is executed instead
   - Otherwise, normal follow-up behavior applies based on `should_replace["CANCELLED"]`
3. **Child orders are links, not parents** - A child order never becomes a parent for other orders

### Benefits

- **Simpler to reason about** - Single level of nesting, easy to track
- **Clear move semantics** - Moves only work on parents; children inherit parent moves
- **Prevents infinite hierarchies** - No risk of deep nesting or orphaned orders
- **Better database integrity** - Foreign key relationships are straightforward

## Database Schema

### order_moves Table

Tracks both completed moves and pending (pre-marked) moves for automation.

```sql
CREATE TABLE order_moves (
    id SERIAL PRIMARY KEY,
    
    -- The original parent order being moved/replaced
    original_parent_client_order_id VARCHAR(40) NOT NULL,
    
    -- The new parent order (NULL for pending moves until executed)
    new_parent_client_order_id VARCHAR(40),
    
    -- If TRUE, execute move automatically when order cancels (for automation)
    move_on_cancel BOOLEAN DEFAULT FALSE,
    
    -- When the move was created
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- When the move was executed (NULL if still pending)
    moved_at TIMESTAMP,
    
    -- Why the move happened
    reason VARCHAR(50) DEFAULT 'auto_move',
    
    -- Additional context (stores config for pending moves)
    notes TEXT,
    
    -- Foreign keys to order_parent table
    FOREIGN KEY (original_parent_client_order_id) 
        REFERENCES order_parent(client_order_id) ON DELETE CASCADE,
    FOREIGN KEY (new_parent_client_order_id) 
        REFERENCES order_parent(client_order_id) ON DELETE CASCADE
);
```

### Key Constraints

- Both `client_order_id`s must exist in `order_parent` table (except `new_parent_client_order_id` for pending moves)
- Move records cascade delete if either parent is deleted
- One move per original parent (latest move is used for lookups)
- For pending moves: `move_on_cancel=TRUE`, `new_parent_client_order_id=NULL`, `moved_at=NULL`
- For completed moves: `move_on_cancel=FALSE`, `new_parent_client_order_id=SET`, `moved_at=SET`

## Two Modes: Manual and Automated

The move mechanism supports both manual intervention and automation:

### Manual Mode (Default)
- Move an order anytime after it cancels
- Decision made in real-time based on market conditions
- Executed immediately with full configuration

### Automated Mode (Pending Moves)
- Pre-mark an order for move BEFORE it cancels
- When order cancels, move executes automatically
- Configuration stored for later execution
- Perfect for scheduled strategies and automation

## Usage Guide

### 1. Manual Move (Immediate)

```python
from business.move_manager import MoveManager
from configuration import OrderBook

# Initialize the move manager
move_manager = MoveManager(orderbook=OrderBook())

# Move a cancelled parent to a new parent with different strategy
result = move_manager.move_order(
    original_parent_client_order_id="550e8400-e29b-41d4-a716-446655440000",
    new_order_details={
        "product_id": "BTC-USDC",
        "side": "BUY",
        "size": 1.0,
        "price": 42500.0,
        "target_movement": 0.005,  # 0.5% profit target
        "target_movement_type": "P",  # Percentage
        "max_order_replacement": 11  # Allow up to 11 follow-ups
    },
    reason="user_cancelled_and_moved",
    notes="Cancelled due to market conditions change"
)

if result["success"]:
    print(f"Moved to: {result['new_parent_client_order_id']}")
    print(f"Move ID: {result['move_id']}")
else:
    print(f"Move failed: {result['error']}")
```

### 2. Automated Move (Pre-Mark)

Pre-mark an order for automatic move when it cancels:

```python
from business.move_manager import MoveManager

move_manager = MoveManager()

# Pre-mark order for automatic move on cancellation
result = move_manager.pre_mark_for_move(
    original_parent_client_order_id="parent_uuid",
    new_order_details={
        "product_id": "BTC-USDC",
        "side": "SELL",  # Switch direction when cancelled
        "size": 0.5,
        "price": 43000.0,
        "target_movement": 0.01,
        "max_order_replacement": 5
    },
    reason="auto_move_scheduled",
    notes="Automatic reversal if order cancels"
)

if result["success"]:
    print(f"Pre-marked for auto-move: {result['move_id']}")
    print("When order cancels, will automatically move to new strategy")
else:
    print(f"Pre-mark failed: {result['error']}")
```

When the marked order cancels, the OrderEngine automatically:
1. Detects the pending move
2. Creates the new parent order
3. Executes the move atomically
4. Logs the automatic move event

### 3. Using OrderEngine (Manual)

```python
from core.order_engine import OrderEngine

# Within order processing logic (manual intervention)
result = engine.move_cancelled_order(
    original_parent_client_order_id="old_parent_id",
    new_order_details={
        "product_id": "BTC-USDC",
        "side": "SELL",  # Switch direction!
        "size": 0.5,      # Reduce size
        "price": 43000.0,
        "target_movement": 0.01,  # Larger target
        "max_order_replacement": 5
    },
    reason="strategy_change",
    notes="User requested direction reversal"
)
```

### 4. Checking Move History

```python
move_manager = MoveManager()

# Get move history for an order
history = move_manager.get_move_history("550e8400-e29b-41d4-a716-446655440000")

print(f"Has moved: {history['has_moved']}")
print(f"Is original: {history['is_original']}")
print(f"Is replacement: {history['is_replacement']}")

if history['has_moved']:
    print(f"Original: {history['original_parent_client_order_id']}")
    print(f"New: {history['new_parent_client_order_id']}")
    print(f"Moved at: {history['moved_at']}")
    print(f"Reason: {history['reason']}")
```

### 4. Checking if Order Can Be Moved

```python
can_move, reason = move_manager.can_move_order("550e8400-e29b-41d4-a716-446655440000")

if not can_move:
    print(f"Cannot move: {reason}")
else:
    print("Order is eligible for move")
```

## Database Functions

### Insert Move

```python
from database.order import insert_order_move

move_id = insert_order_move(
    original_parent_client_order_id="old_parent_id",
    new_parent_client_order_id="new_parent_id",
    reason="user_requested",
    notes="Manual intervention"
)
```

### Query Move History

```python
from database.order import (
    get_order_move,
    get_order_moves_by_original_parent,
    get_order_moves_by_new_parent,
    has_order_moved
)

# Get latest move for an original parent
move = get_order_move("original_parent_id")

# Get all moves of an original parent
moves = get_order_moves_by_original_parent("original_parent_id")

# Get all moves that resulted in a new parent
moves = get_order_moves_by_new_parent("new_parent_id")

# Check if order has been moved
moved = has_order_moved("any_parent_id")
```

## Move Reasons

Common reason values:

- `"cancelled_move"` - Generic move due to cancellation
- `"user_cancelled"` - User manually cancelled and replaced
- `"user_move"` - User initiated move
- `"strategy_change"` - Strategy was changed mid-execution
- `"price_adjustment"` - Price moved significantly, cancelling and replacing
- `"size_adjustment"` - Order size needs to change
- `"direction_reversal"` - Switching from BUY to SELL (or vice versa)
- `"auto_move"` - Automatic system move (default)

## Order Status in order_parent Table

After a move:

| Column | Before | After |
|--------|--------|-------|
| `client_order_id` | Original UUID | Unchanged |
| `status` | CANCELLED | CANCELLED (unchanged) |
| `created_at` | Original timestamp | Unchanged |

A new row is created in `order_parent` for the replacement order with:
- New `client_order_id` (UUID)
- `status` = "pending"
- `created_at` = current timestamp
- Configured settings (product, side, size, price, target_movement, etc.)

## Query Examples

### Find All Moved Orders

```sql
SELECT 
    m.original_parent_client_order_id,
    m.new_parent_client_order_id,
    m.moved_at,
    m.reason,
    op.status as original_status,
    op.product_id,
    op.side
FROM order_moves m
JOIN order_parent op ON m.original_parent_client_order_id = op.client_order_id
ORDER BY m.moved_at DESC;
```

### Find Replacement Orders

```sql
SELECT 
    m.original_parent_client_order_id,
    m.new_parent_client_order_id,
    m.reason,
    COUNT(c.client_order_id) as child_count
FROM order_moves m
LEFT JOIN order_child c ON m.new_parent_client_order_id = c.parent_client_order_id
GROUP BY m.original_parent_client_order_id, m.new_parent_client_order_id
ORDER BY m.moved_at DESC;
```

### Audit Trail

```sql
SELECT 
    om.original_parent_client_order_id,
    om.new_parent_client_order_id,
    om.moved_at,
    om.reason,
    om.notes,
    op.status as original_status,
    np.status as new_status
FROM order_moves om
JOIN order_parent op ON om.original_parent_client_order_id = op.client_order_id
JOIN order_parent np ON om.new_parent_client_order_id = np.client_order_id
WHERE om.original_parent_client_order_id = '550e8400-e29b-41d4-a716-446655440000'
ORDER BY om.moved_at;
```

## Integration Points

### OrderEngine

Use `engine.move_cancelled_order()` to move an order from within order processing logic:

```python
def handle_special_cancellation(self, order: dict):
    """Custom handler for special cancellations that need moves."""
    parent_id = self.resolve_parent_client_order_id(order["client_order_id"])[1]
    
    # Get original order details
    original_parent = get_parent_order(parent_id)
    
    # Create replacement with modified settings
    result = self.move_cancelled_order(
        original_parent_client_order_id=parent_id,
        new_order_details={
            "product_id": original_parent["product_id"],
            "side": original_parent["side"],
            "size": float(original_parent["size"]) * 0.5,  # Reduce size 50%
            "price": float(original_parent["price"]),
            "target_movement": original_parent["target_movement"],
            "target_movement_type": original_parent["target_movement_type"],
            "max_order_replacement": original_parent["max_order_replacement"]
        },
        reason="size_adjustment",
        notes="Size reduced due to margin constraints"
    )
```

### Dashboard/Web UI

```javascript
// Example: Web UI endpoint to move an order
async function moveOrder(originalParentId, newOrderDetails, reason) {
    const response = await fetch('/api/orders/move', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            original_parent_client_order_id: originalParentId,
            new_order_details: newOrderDetails,
            reason: reason
        })
    });
    return response.json();
}

// Usage
const result = await moveOrder(
    "550e8400-e29b-41d4-a716-446655440000",
    {
        product_id: "BTC-USDC",
        side: "BUY",
        size: 1.0,
        price: 42500,
        target_movement: 0.005,
        max_order_replacement: 11
    },
    "user_cancelled_and_moved"
);
```

## Error Handling

### Common Errors

```python
result = move_manager.move_order(...)

# Check for success
if not result["success"]:
    error = result["error"]
    
    if "not found" in error:
        # Parent order doesn't exist
        print("Original parent order not found")
    elif "already moved" in error:
        # Order was already moved
        print("Order already has a replacement")
    elif "Missing required fields" in error:
        # Invalid new order details
        print("Invalid order configuration")
    else:
        # Database or other error
        print(f"Unexpected error: {error}")
```

## Testing

### Unit Tests

```python
def test_move_order():
    """Test moving a parent order to a new parent."""
    move_manager = MoveManager()
    
    # Create original parent
    insert_order_parent(
        client_order_id="original_uuid",
        product_id="BTC-USDC",
        side="BUY",
        size=1.0,
        price=42000.0,
        target_movement=0.005,
        max_order_replacement=11
    )
    
    # Move it
    result = move_manager.move_order(
        original_parent_client_order_id="original_uuid",
        new_order_details={
            "product_id": "BTC-USDC",
            "side": "SELL",  # Switch direction
            "size": 0.5,
            "price": 43000.0,
            "target_movement": 0.01,
            "max_order_replacement": 5
        },
        reason="direction_reversal"
    )
    
    # Verify
    assert result["success"] == True
    assert result["move_id"] is not None
    assert get_order_move("original_uuid") is not None
    
    # Verify new parent exists
    new_parent = get_parent_order(result["new_parent_client_order_id"])
    assert new_parent["product_id"] == "BTC-USDC"
    assert new_parent["side"] == "SELL"
    assert float(new_parent["size"]) == 0.5
```

## Important Notes

⚠️ **Key Points**

1. **Original parent remains unchanged** - The original parent's status, created_at, and all fields remain as they were
2. **New parent is independent** - It has its own max_order_replacement counter and replacement tracking
3. **No child adoption** - Moving an order does NOT affect any child orders of the original parent
4. **Audit trail** - All moves are recorded with timestamp, reason, and notes for compliance
5. **One move per original** - Each original parent can only have one active move (latest one is used for lookups)
6. **Idempotent IDs** - Both old and new parent must have valid `client_order_id`s (UUIDs)

### Pending Move Automation ✅ **IMPLEMENTED**

**Pending moves are fully supported for automation:**
- `pre_mark_for_move()` - Mark an order for automatic move before cancellation
- `execute_pending_move_for_order()` - Execute pending move when order cancels
- `has_pending_move()` - Check if order has pending move
- OrderEngine automatically detects and executes pending moves
- Configuration is stored and executed atomically

**When an order with a pending move cancels:**
1. OrderEngine detects the pending move flag
2. Automatically creates the new parent order
3. Sets the new parent_client_order_id
4. Marks the move as executed
5. Prevents normal follow-up child order creation

## Future Enhancements

Potential improvements:

- [ ] Add UI for managing moves in order manager dashboard
- [ ] Add move scheduling (move at specific price/time)
- [ ] Add bulk move operations
- [ ] Add move templates for common patterns
- [ ] Add move history visualization
- [ ] Add conditional pending moves (move if price hits X)
- [ ] Add pending move cancellation/modification

## See Also

- [ORDER_ID_HANDLING.md](ORDER_ID_HANDLING.md) - Understanding client_order_id vs order_id
- [DATA_MODELS.md](DATA_MODELS.md) - Order and parent/child relationship models
- [MODULES.md](MODULES.md) - Business logic modules reference
