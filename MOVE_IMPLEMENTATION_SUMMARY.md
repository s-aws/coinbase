# Order Move Mechanism - Implementation Summary

## ✅ Completed Implementation

I have successfully implemented a **move mechanism for cancelled orders** in the Coinbase trading system. This allows cancelled parent orders to be replaced with new parent orders, replacing the parent/child relationship entirely.

## What Was Implemented

### 1. **Database Schema** (`database/order.py`)
- **New Table: `order_moves`** - Tracks relationships between cancelled orders and their replacements
  - Stores original parent → new parent mappings
  - Records move timestamp, reason, and notes
  - Cascading foreign keys to `order_parent` table

### 2. **Database Functions** (`database/order.py`)
- `create_order_moves_table()` - Create the new table
- `insert_order_move()` - Record a move relationship
- `get_order_move()` - Retrieve move record by original parent ID
- `get_order_moves_by_original_parent()` - Get all moves from an original parent
- `get_order_moves_by_new_parent()` - Get all orders that replaced a parent
- `has_order_moved()` - Check if an order was involved in a move

### 3. **Business Logic** (`business/move_manager.py`)
- **MoveManager Class** - Complete move orchestration
  - `move_order()` - Execute a move (create new parent, record relationship)
  - `can_move_order()` - Validate move prerequisites
  - `get_move_history()` - Check move status and history
  - Integrated with OrderBook for state management

### 4. **OrderEngine Integration** (`core/order_engine.py`)
- `move_cancelled_order()` - Method to move cancelled orders with logging
- Logs move events for audit trail
- Integrates with existing order processing pipeline

### 5. **Comprehensive Testing** (`tests/unit/test_order_moves.py`)
- **18 unit tests** - All passing ✅
  - MoveManager functionality tests
  - Database operation tests
  - Integration tests with OrderBook
  - Move history tracking tests

### 6. **Documentation** (`genai_data/MOVE_MECHANISM.md`)
- Complete guide on move mechanism
- Differences vs parent/child mechanism
- Database schema details
- Usage examples and code samples
- Query examples
- Integration patterns

## Key Design Decisions

### Move vs Parent/Child
| Aspect | Parent/Child | Move |
|--------|-------------|------|
| **When Used** | Fill or cancel → create follow-up | Cancel → replace strategy |
| **Structure** | Multiple children under one parent | New independent parent |
| **Database** | FK relationship maintained | Separate move record |
| **Use Case** | Scaling out, taking profits | Strategy changes, adjustments |

### Database Integrity
- Both original and new parent remain in database
- Original parent status unchanged (for audit)
- Move recorded with timestamp and reason
- Cascading deletes handle orphans

### OrderBook State
- New parent added to `orderbook.parent_order_ids`
- New parent gets independent `max_order_replacement` counter
- Original parent unaffected
- Child orders of original NOT automatically moved

## How to Use

### Simple Example
```python
from business.move_manager import MoveManager

move_manager = MoveManager()

# Move a cancelled order to a new one with different strategy
result = move_manager.move_order(
    original_parent_client_order_id="old_parent_uuid",
    new_order_details={
        "product_id": "BTC-USDC",
        "side": "SELL",  # Can switch direction!
        "size": 0.5,     # Can adjust size!
        "price": 43000.0,
        "target_movement": 0.01,
        "max_order_replacement": 5
    },
    reason="user_cancelled_and_moved",
    notes="Strategy change due to market conditions"
)

if result["success"]:
    print(f"New parent: {result['new_parent_client_order_id']}")
```

### From OrderEngine
```python
# Within order processing
result = engine.move_cancelled_order(
    original_parent_client_order_id=parent_id,
    new_order_details={...},
    reason="strategy_change"
)
```

### Check Move History
```python
history = move_manager.get_move_history("550e8400-e29b-41d4-a716-446655440000")
print(f"Has moved: {history['has_moved']}")
print(f"Moved to: {history['new_parent_client_order_id']}")
```

## Database Changes

### New Table: `order_moves`
```sql
CREATE TABLE order_moves (
    id SERIAL PRIMARY KEY,
    original_parent_client_order_id VARCHAR(40) NOT NULL,
    new_parent_client_order_id VARCHAR(40) NOT NULL,
    moved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reason VARCHAR(50) DEFAULT 'auto_move',
    notes TEXT,
    FOREIGN KEY (original_parent_client_order_id) 
        REFERENCES order_parent(client_order_id) ON DELETE CASCADE,
    FOREIGN KEY (new_parent_client_order_id) 
        REFERENCES order_parent(client_order_id) ON DELETE CASCADE
);
```

The table is automatically created when running:
```bash
python __dangerous_delete_all_tables__.py
```

## Files Changed/Created

### New Files
- `business/move_manager.py` - MoveManager class
- `tests/unit/test_order_moves.py` - Comprehensive test suite
- `genai_data/MOVE_MECHANISM.md` - Full documentation

### Modified Files
- `database/order.py` - Added move table and functions
- `core/order_engine.py` - Added move_cancelled_order() method
- `__dangerous_delete_all_tables__.py` - Added move table initialization

## Validation

✅ **All 18 tests passing**
- MoveManager functionality verified
- Database operations tested
- Integration with OrderBook confirmed
- Error handling validated

## Future Enhancements

- [ ] Add `move_on_cancel` flag to `order_parent` table for automatic moves
- [ ] Add move scheduling (move at specific price/time)
- [ ] Add UI for managing moves in dashboard
- [ ] Add bulk move operations
- [ ] Add move templates for common patterns

## Query Examples

```sql
-- Find all moved orders
SELECT * FROM order_moves ORDER BY moved_at DESC;

-- Find replacement count for an order
SELECT COUNT(*) FROM order_moves 
WHERE new_parent_client_order_id = '550e8400-e29b-41d4-a716-446655440000';

-- Audit trail
SELECT 
    om.original_parent_client_order_id,
    om.new_parent_client_order_id,
    om.moved_at,
    om.reason,
    op.status as original_status
FROM order_moves om
JOIN order_parent op ON om.original_parent_client_order_id = op.client_order_id
ORDER BY om.moved_at DESC;
```

## Next Steps

1. **Initialize Database**: Run `python __dangerous_delete_all_tables__.py` to create the order_moves table
2. **Review Documentation**: Read `genai_data/MOVE_MECHANISM.md` for complete details
3. **Test Locally**: Run tests: `pytest tests/unit/test_order_moves.py -v`
4. **Integrate with UI**: Add move endpoints to dashboard_server.py if needed
5. **Deploy**: Follow your standard deployment process

## Support

For detailed information:
- Move mechanism guide: `genai_data/MOVE_MECHANISM.md`
- API examples: See documentation file for code samples
- Test examples: `tests/unit/test_order_moves.py`
