# Stealth Orders Target Movement Feature

## Summary

Extended `ui_stealth_orders_manager.html` and `dashboard_server.py` to support updating target movement for stealth orders. This allows users to specify custom profit targets (as a percentage or absolute amount) that will be used when follow-up orders are created from stealth order reveals.

## What Was Added

### 1. Database Changes ([database/order.py](database/order.py))

**New Migration Function:**
- `add_missing_stealth_orders_target_movement_columns()` - Safely adds `target_movement` and `target_movement_type` columns to existing `stealth_orders` table
- Safe to run repeatedly (uses `IF NOT EXISTS`)
- Updates applied:
  - `target_movement NUMERIC` - The profit target value
  - `target_movement_type VARCHAR(1)` - Type: "P" for percentage, "A" for absolute amount

**New Database Functions:**
- `update_stealth_order_target_movement(stealth_order_id, target_movement, target_movement_type)` - Updates target movement for a stealth order
- `get_stealth_order_by_id(stealth_order_id)` - Retrieves a stealth order by ID with all fields including target movement

**Schema Update:**
- The `create_stealth_orders_table()` function now includes target_movement fields in new table creation

### 2. UI Changes ([ui_stealth_orders_manager.html](ui_stealth_orders_manager.html))

**Table Updates:**
- Added "Target Movement" column (10th column) to the stealth orders table
- Column displays the target movement value with its type (% or Abs)
- Updated colspan from 10 to 11 columns

**Edit Button:**
- Added edit button (⚙️) to each order row
- Styled in gold (#ffd700) for visibility
- Opens a modal dialog for editing target movement

**Modal Dialog:**
- New modal for editing target movement
- Fields:
  - Target Movement Value (numeric input)
  - Type selector (Percentage % or Absolute Amount)
  - Helpful descriptions of each type
- Keyboard support (Enter to confirm)
- Click-outside-to-close functionality
- Cancel and Update buttons

**Styling:**
- Added CSS for modal (`.modal`, `.modal-content`, `.modal-header`, `.modal-footer`)
- Added CSS for edit button (`.edit-btn`)
- Consistent with existing dark theme
- Smooth animations (fade-in for modal, slide-in for content)

**JavaScript Functions:**
- `openEditTargetMovementModal(stealthOrderId, currentValue, currentType)` - Opens the edit modal with current values
- `closeEditTargetMovementModal()` - Closes the modal and clears stored data
- `confirmEditTargetMovement()` - Sends update to server via WebSocket
- Event handlers for modal interactions (close on outside click, Enter key support)

### 3. WebSocket Handler ([dashboard_server.py](dashboard_server.py))

**New Message Type: `update_stealth_target_movement`**

Handles incoming update requests from the UI:
```javascript
{
    "type": "update_stealth_target_movement",
    "stealth_order_id": "550e8400-e29b-41d4-a716-446655440000",
    "target_movement": 0.005,           // float value
    "target_movement_type": "P"         // "P" or "A"
}
```

**Handler Flow:**
1. Validates request parameters
2. Calls `update_stealth_order_target_movement()` to update database
3. Updates in-memory engine state
4. Broadcasts `stealth_order_updated` message to all connected clients
5. Sends confirmation to requesting client
6. Logs operation for audit trail

**Response Types:**
- Success: `stealth_order_updated` broadcast to all clients
- Error: Error message with details

## How to Use

### For UI Users

1. **View Target Movement:**
   - Open the Stealth Orders Manager
   - Look at the "Target Movement" column (10th column)
   - Displays current target movement value with type indicator (% or Abs)

2. **Edit Target Movement:**
   - Click the ⚙️ edit button on any stealth order row
   - Modal dialog opens with current values
   - Enter new target movement value
   - Select type: Percentage (%) or Absolute Amount
   - Click "Update" to apply or "Cancel" to discard

3. **Clear Target Movement:**
   - Leave the value field empty when editing
   - Click "Update"
   - Target movement will be cleared (None)

### For Developers

#### Applying the Migration

If upgrading an existing installation:

```python
from database.order import add_missing_stealth_orders_target_movement_columns

# Run once to add columns to existing tables
add_missing_stealth_orders_target_movement_columns()
```

Or use the provided test script:
```bash
python genai_tools/test_stealth_target_movement.py
```

#### Programmatically Update Target Movement

```python
from database.order import update_stealth_order_target_movement

# Set percentage target (0.5%)
update_stealth_order_target_movement(
    stealth_order_id="550e8400-e29b-41d4-a716-446655440000",
    target_movement=0.005,
    target_movement_type="P"
)

# Set absolute amount ($100)
update_stealth_order_target_movement(
    stealth_order_id="550e8400-e29b-41d4-a716-446655440000",
    target_movement=100.0,
    target_movement_type="A"
)

# Clear target movement
update_stealth_order_target_movement(
    stealth_order_id="550e8400-e29b-41d4-a716-446655440000",
    target_movement=None
)
```

#### Retrieving Target Movement

```python
from database.order import get_stealth_order_by_id

order = get_stealth_order_by_id(stealth_order_id)
if order:
    print(f"Target: {order['target_movement']} {order['target_movement_type']}")
```

## Feature Behavior

### Target Movement Types

- **Percentage (P)**: Profit target as % of current order price
  - Example: 0.005 (0.5%) means move target is 0.5% of current price
  - Used for follow-up orders created from filled reveals

- **Absolute Amount (A)**: Fixed dollar/USDC amount
  - Example: 100.0 means $100 per unit
  - Used for follow-up orders created from filled reveals

### When Target Movement is Used

Target movement is applied when:
1. Stealth order is revealed (placed on exchange)
2. The revealed order gets filled
3. A follow-up order is created based on the reveal conditions
4. The follow-up order price is calculated using the target movement

### Persistence

- Target movement is stored in the `stealth_orders` table
- Survives across application restarts
- Included in database backups
- Can be modified at any time

## Testing

A comprehensive test suite is provided: [genai_tools/test_stealth_target_movement.py](genai_tools/test_stealth_target_movement.py)

**Tests Included:**
1. **Database Migration** - Verifies columns are added correctly
2. **Update Function** - Tests all three scenarios:
   - Update with percentage
   - Update with absolute amount
   - Clear target movement (set to None)
3. **Realistic UI Scenario** - Tests multi-order workflows

**Run Tests:**
```bash
python genai_tools/test_stealth_target_movement.py
```

**Output:**
```
✅ ALL TESTS PASSED

Feature is ready for use! You can now:
1. Create stealth orders with target movement
2. Update target movement via the UI edit button (⚙️)
3. View target movement values in the orders table
```

## Files Modified

1. **[database/order.py](database/order.py)**
   - Added `add_missing_stealth_orders_target_movement_columns()` migration function
   - Added `update_stealth_order_target_movement()` database function
   - Added `get_stealth_order_by_id()` database function
   - Updated `create_stealth_orders_table()` schema

2. **[ui_stealth_orders_manager.html](ui_stealth_orders_manager.html)**
   - Added "Target Movement" table column
   - Added CSS for modal and edit button
   - Added modal HTML structure
   - Added JavaScript event handlers:
     - `openEditTargetMovementModal()`
     - `closeEditTargetMovementModal()`
     - `confirmEditTargetMovement()`
   - Added modal interaction handlers (click-outside, Enter key)

3. **[dashboard_server.py](dashboard_server.py)**
   - Added WebSocket handler for `update_stealth_target_movement` message type
   - Integrated with database update functions
   - Added broadcast of `stealth_order_updated` messages
   - Added logging for audit trail

## Backward Compatibility

- Existing stealth orders without target_movement will show as "-" (None)
- Migration is safe to run on existing databases
- No breaking changes to existing APIs or data structures
- UI gracefully handles orders without target movement

## Related Features

- **Parent Orders Target Movement**: The inspiration for this feature
  - See [ui_order_manager.html](ui_order_manager.html) for similar parent order implementation
  - Parent orders already support target movement for their follow-up children

- **Stealth Order Reveals**: Target movement is applied when reveals are converted to follow-ups
  - See [core/stealth_order_manager.py](core/stealth_order_manager.py) for reveal logic

## Future Enhancements

Possible future improvements:
1. Bulk update target movement for multiple orders
2. Template target movements (save/apply presets)
3. Conditional target movements (different values for different markets)
4. Historical tracking of target movement changes
5. Analytics on target movement effectiveness
