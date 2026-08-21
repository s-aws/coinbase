# Child Order Adoption

## Overview

The child order adoption feature allows you to reassign a child order to a different parent order. This is useful for dynamic trading strategies where orders need to be reorganized based on market conditions without losing the ability to track their original ownership.

## The Problem This Solves

In complex trading strategies, you might have:
- Multiple parent orders, each managing a set of follow-up (child) orders
- Need to rebalance orders when a parent order is cancelled but its children should continue
- Need to consolidate children from multiple parents into a single parent
- Need to change the target profit movement by switching parents

Without adoption, you would need to either:
- Cancel and recreate orders (expensive, loses history)
- Create new parent-child links manually (error-prone, inconsistent)
- Keep orphaned orders that are no longer tracked (messy)

## Solution: Clean Adoption Pattern

The adoption function provides:
1. **Atomic Updates**: Both database and in-memory structures updated together
2. **Audit Trail**: Old parent preserved for historical reference
3. **Validation**: Ensures both child and new parent exist before proceeding
4. **Clean Semantics**: Standard database pattern using nullable `previous_parent_client_order_id` column

### Why This Approach is Standard

This pattern follows database best practices:
- **Nullable Foreign Key**: Allows historical tracking without complex versioning
- **Timestamp**: Records when adoption occurred (audit trail)
- **Separation of Concerns**: Active relationship (current parent) vs. history (previous parent)
- **No Data Loss**: Can always query adoption history

## Database Schema

The `order_child` table has been extended with adoption tracking:

```sql
CREATE TABLE order_child (
    id SERIAL PRIMARY KEY,
    parent_client_order_id VARCHAR(40) NOT NULL,  -- Current parent (FK)
    client_order_id VARCHAR(40) UNIQUE NOT NULL,
    product_id VARCHAR(255) NOT NULL,
    side VARCHAR(10) NOT NULL,
    size NUMERIC NOT NULL,
    price NUMERIC NOT NULL,
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Adoption tracking (NEW)
    previous_parent_client_order_id VARCHAR(40) DEFAULT NULL,  -- Original parent (history)
    adopted_at TIMESTAMP DEFAULT NULL,                          -- When adoption occurred

    FOREIGN KEY (parent_client_order_id) REFERENCES order_parent(client_order_id)
);
```

## Usage

### Via Python API (OrderEngine)

```python
from core.order_engine import OrderEngine

# ... engine initialization ...

# Adopt a child to a new parent
success = engine.adopt_child_to_new_parent(
    child_client_order_id="child-uuid-123",
    new_parent_client_order_id="parent-uuid-456",
    keep_adoption_history=True  # Keep track of original parent
)

if success:
    print("Child adopted successfully")
else:
    print("Adoption failed")
```

### Via Database API

```python
from database.order import adopt_child_to_parent

# Setup adoption tracking columns (one-time)
from database.order import add_adoption_tracking_columns
add_adoption_tracking_columns()

# Adopt a child order
success = adopt_child_to_parent(
    child_client_order_id="child-uuid-123",
    new_parent_client_order_id="parent-uuid-456",
    keep_adoption_history=True  # Optional: default is True
)

if success:
    print(f"Adoption successful")
else:
    print(f"Adoption failed - see database log")
```

### Via CLI Tool

```bash
# Setup (one-time)
python genai_tools/adopt_child_order.py --setup

# Show current parent
python genai_tools/adopt_child_order.py --show-parent <child_order_id>

# Show adoption path (history)
python genai_tools/adopt_child_order.py --path <child_order_id>

# Perform adoption with history tracking
python genai_tools/adopt_child_order.py \
    --child <child_order_id> \
    --new-parent <new_parent_order_id> \
    --keep-history

# Perform adoption without history
python genai_tools/adopt_child_order.py \
    --child <child_order_id> \
    --new-parent <new_parent_order_id>
```

## Adoption Behavior

### What Happens During Adoption

1. **Validation Phase**
   - Checks that child order exists
   - Checks that new parent order exists
   - Aborts if either is missing

2. **Database Update**
   - Updates `order_child.parent_client_order_id` to point to new parent
   - If `keep_adoption_history=True`:
     - Stores current parent in `previous_parent_client_order_id`
     - Records timestamp in `adopted_at`

3. **In-Memory Update** (OrderEngine only)
   - Removes child from old parent's children list
   - Adds child to new parent's children list
   - Updates `child_order_ids` mapping

4. **Logging**
   - Emits `child_order_adopted` event with full audit info
   - Includes old parent, new parent, and history flag

### Old Parent Link Handling

**Option 1: With History (Recommended)**
```python
# Old parent is preserved in database
success = adopt_child_to_parent(
    child_client_order_id="child-123",
    new_parent_client_order_id="parent-456",
    keep_adoption_history=True  # Store original parent
)

# Query to see adoption history:
# SELECT
#   parent_client_order_id,           -- Current: parent-456
#   previous_parent_client_order_id,  -- Original: parent-123
#   adopted_at                        -- When adoption happened
# FROM order_child WHERE client_order_id = 'child-123'
```

**Option 2: Without History**
```python
# Old parent link is immediately lost
success = adopt_child_to_parent(
    child_client_order_id="child-123",
    new_parent_client_order_id="parent-456",
    keep_adoption_history=False  # Don't track original
)

# For this order:
#   parent_client_order_id = parent-456
#   previous_parent_client_order_id = NULL
#   adopted_at = NULL
```

## Querying Adoption History

```sql
-- Find all adopted children
SELECT
    client_order_id,
    parent_client_order_id AS current_parent,
    previous_parent_client_order_id AS original_parent,
    adopted_at,
    status
FROM order_child
WHERE previous_parent_client_order_id IS NOT NULL
ORDER BY adopted_at DESC;

-- Show adoption path for a specific child
SELECT
    client_order_id,
    parent_client_order_id,
    previous_parent_client_order_id,
    adopted_at
FROM order_child
WHERE client_order_id = 'child-uuid-123';

-- Count adoptions per child (shows how many times a child changed parents)
SELECT
    client_order_id,
    COUNT(*) as adoption_count
FROM order_child
WHERE previous_parent_client_order_id IS NOT NULL
GROUP BY client_order_id
ORDER BY adoption_count DESC;
```

## Common Scenarios

### Scenario 1: Parent Cancelled, Children Continue

```python
# Parent order was cancelled, but we want to continue trading those children
# under a different parent with same strategy

old_parent_id = "parent-abc"
new_parent_id = "parent-xyz"

# Get all children of old parent
children = engine.db_helper.get_child_orders(old_parent_id)

# Adopt each one
for child in children:
    engine.adopt_child_to_new_parent(
        child_client_order_id=child["client_order_id"],
        new_parent_client_order_id=new_parent_id,
        keep_adoption_history=True
    )

print(f"Adopted {len(children)} orders from {old_parent_id} to {new_parent_id}")
```

### Scenario 2: Consolidate Multiple Parents

```python
# We have orders under multiple parents, want to consolidate to one

parents_to_consolidate = ["parent-1", "parent-2", "parent-3"]
primary_parent = "parent-main"

for old_parent in parents_to_consolidate:
    children = engine.db_helper.get_child_orders(old_parent)
    for child in children:
        engine.adopt_child_to_new_parent(
            child_client_order_id=child["client_order_id"],
            new_parent_client_order_id=primary_parent,
            keep_adoption_history=True
        )

print(f"Consolidated all orders to {primary_parent}")
```

### Scenario 3: Orphan a Child (No History)

```python
# A child order is now independent, no longer part of original parent
# We might make it a new parent, but keep no link to past

child_id = "child-123"
old_parent = "parent-456"  # Going to be removed from this

# Create new parent entry for this child
new_parent_id = engine.resolve_parent_client_order_id(
    client_order_id=child_id,
    create_parent=True,
    order=order_data
)

# But we don't need adoption history for this
# Just note: child is now a parent itself, not someone's child
```

## Error Handling

```python
from configuration import REST_CLIENT

try:
    success = engine.adopt_child_to_new_parent(
        child_client_order_id=child_id,
        new_parent_client_order_id=new_parent_id
    )

    if not success:
        print("Adoption validation failed - check logs")
        print(f"Child exists: {engine.db_helper.get_child_orders(child_id)}")
        print(f"Parent exists: {engine.db_helper.get_parent_order(new_parent_id)}")
    else:
        print("Adoption successful")

except Exception as e:
    print(f"Adoption error: {e}")
    # Log to monitoring system
```

## Thread Safety

The `OrderEngine.adopt_child_to_new_parent()` method is thread-safe:
- Uses `orderbook_lock` for in-memory updates
- Database operations are atomic
- Safe to call from multiple threads

## Performance Considerations

- **Adoption Cost**: O(1) database update + O(n) in-memory list updates (where n = children count)
- **Query Cost**: Index on `parent_client_order_id` ensures fast lookups
- **History Queries**: Queries on `previous_parent_client_order_id` are slow (no index) - add index if frequently queried

## See Also

- [Order ID Handling](../genai_data/ORDER_ID_HANDLING.md) - How client_order_id and order_id work
- [Parent-Child Orders](./cli_parent_child_orders.py) - CLI tool to view parent-child relationships
- [Order Engine](./core/order_engine.py) - Core trading engine
- [Database Order Module](./database/order.py) - Low-level order operations
