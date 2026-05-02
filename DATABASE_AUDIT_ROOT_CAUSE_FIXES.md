> Documentation status (2026-05-02): **Archival (historical implementation note)**
> This file records point-in-time analysis or implementation history and may not match current runtime behavior.
> Canonical living docs: genai_data/README.md, genai_data/ARCHITECTURE.md, genai_data/ORDER_ID_HANDLING.md, genai_data/TESTING_STRATEGY.md.
# Database State Audit & Root Cause Analysis (2026-04-25)

## Issue Reported
Orders showing replacement count incrementing multiple times per fill event (5→6→7→8→9→10), indicating either:
1. Race conditions causing duplicate processing
2. Double-registration of child orders  
3. Code changes not applied properly

## Database Audit Findings

### Current Database State
- ✅ Schema columns (anchor_repricing_policy_json, anchor_repricing_state_json) DO exist in stealth_orders
- ✅ order_parent table exists with all expected columns
- **CRITICAL**: Parent order ID 12 (cd341f8d-01f0-4c...) shows:
  - current_order_replacement = **10**
  - max_order_replacement = 11
  - Actual child orders in database = **4**
  - **Mismatch**: 10 increments recorded but only 4 children!

### Root Cause Identified

**Three layers of the issue:**

#### Layer 1: Duplicate register_child_order Calls (FOUND & FIXED)
In `handle_filled_order()` at line 2670, there was a SECOND call to register_child_order:

```python
# Line 2528: First registration (protected by claim check)
if original_stealth_order and original_stealth_order.get("parent_order_id"):
    parent_client_order_id_stealth = original_stealth_order["parent_order_id"]
    self.register_child_order(client_order_id, parent_client_order_id_stealth)

# ... later code ...

# Line 2670: DUPLICATE registration (NOT protected, happened when parent was "corrected")
if original_stealth_order and parent_client_order_id == client_order_id:
    explicit_parent = original_stealth_order.get("parent_order_id")
    if explicit_parent and explicit_parent != client_order_id:
        parent_client_order_id = explicit_parent
        self.register_child_order(client_order_id, parent_client_order_id)  # ← CALLED TWICE
```

This would call register_child_order twice per FILLED event on the same order with the same parent.

#### Layer 2: Incomplete Duplicate Prevention in register_child_order (FIXED)
The `register_child_order()` method checked if child was already in the in-memory list BEFORE adding:

```python
if child_client_order_id not in self.orderbook.parent_order_ids[parent][orders]:
    self.orderbook.parent_order_ids[parent]["orders"].append(child_client_order_id)
    self.orderbook.parent_order_ids[parent]["current_order_replacement"] += 1  # Memory OK
    
# BUT: Database increment happened OUTSIDE the check!
from database.order import increment_order_parent_replacement_count
new_count = increment_order_parent_replacement_count(parent_client_order_id)  # ← ALWAYS INCREMENTS
```

**Result**: If called twice:
1. First call: adds to list, increments both memory and database → count = 2
2. Second call: skips adding (duplicate check), but STILL increments database → count = 3

#### Layer 3: Logs Show Per-Fill Double Registration
From user-provided logs, EACH FILL generates TWO "child_order_registered" events with consecutive replacement counts:
- 17:28:25,288 - child_order_registered, new_replacement_count=2
- 17:28:25,294 - child_order_registered, new_replacement_count=3 (same order, 6ms later!)
- 17:28:26,288 - child_order_registered, new_replacement_count=5
- 17:28:26,297 - child_order_registered, new_replacement_count=6 (same order, 9ms later!)

This pattern confirms: same child being registered twice per fill event.

---

## Fixes Applied

### Fix #1: Remove Duplicate register_child_order Call (Line 2670)
**Status**: ✅ APPLIED

Changed line 2670 in `handle_filled_order()`:
```python
# OLD (caused duplicate registration):
if original_stealth_order and parent_client_order_id == client_order_id:
    explicit_parent = original_stealth_order.get("parent_order_id")
    if explicit_parent and explicit_parent != client_order_id:
        parent_client_order_id = explicit_parent
        self.register_child_order(client_order_id, parent_client_order_id)  # ← REMOVED

# NEW (just updates the variable, no duplicate registration):
if original_stealth_order and parent_client_order_id == client_order_id:
    explicit_parent = original_stealth_order.get("parent_order_id")
    if explicit_parent and explicit_parent != client_order_id:
        parent_client_order_id = explicit_parent
        # NOTE: Child registration already happened at line 2528, so don't call again
```

**Why this works**: The first registration at line 2528 uses the correct explicit parent from stealth_order.parent_order_id, which is what we want. The "correction" of parent_client_order_id is only for subsequent follow-up creation logic, not for registration.

### Fix #2: Only Increment Database for New Children (Line ~1395)
**Status**: ✅ APPLIED

Changed `register_child_order()` to track if this is actually a new child:

```python
# OLD (always incremented database):
def register_child_order(self, child_client_order_id, parent_client_order_id):
    with self.orderbook_lock:
        if child_client_order_id not in parent_orders_list:
            parent_orders_list.append(child_client_order_id)
            memory_count += 1
    
    # Database increment happened OUTSIDE the check
    new_count = increment_order_parent_replacement_count(parent_client_order_id)

# NEW (only increments database for new children):
def register_child_order(self, child_client_order_id, parent_client_order_id):
    is_new_child = False
    
    with self.orderbook_lock:
        if child_client_order_id not in parent_orders_list:
            parent_orders_list.append(child_client_order_id)
            memory_count += 1
            is_new_child = True
    
    # Database increment ONLY if we actually added a new child
    if is_new_child:
        new_count = increment_order_parent_replacement_count(parent_client_order_id)
```

**Why this works**: Protects against duplicate counts even if register_child_order is called multiple times.

---

## Complete Fix Timeline

| Prior Fix | Status | Applied | Issue Fixed |
|-----------|--------|---------|------------|
| **Schema Migration** | ✅ | Session 1 | Missing anchor_repricing columns |
| **UPSERT Reveal Events** | ✅ | Session 1 | Duplicate reveal history entries |
| **Claim Order First** | ✅ | Session 1 | Race condition in handle_cancelled/filled ordering |
| **Remove Duplicate Register at 2670** | ✅ | **This Session** | Double registration per fill event |
| **Only Increment for New Children** | ✅ | **This Session** | Database count increment without duplicate check |

---

## Expected Outcome After Fixes

### Before Fixes
- One FILLED event → 2 child_order_registered logs → count increments by 2 → replacement_count jumps 2, 3, 5, 6, 8, 9, 10...
- Database replacement_count (10) ≠ Actual children (4)

### After Fixes
- One FILLED event → 1 child_order_registered log → count increments by 1
- Database replacement_count (N) = Actual children (N)
- Orders won't exceed max_order_replacement limit

---

## Testing Procedure

To verify the fix works:

1. **Wipe database**: Delete all orders via existing test script
2. **Run test scenario**: Execute the BUY/SELL stealth orders cycle
3. **Verify logs**: 
   - Should see ONE "child_order_registered" per fill event
   - replacement_count should increment by 1 each time (not by 2)
4. **Audit database**:
   - Current replacement_count should equal actual child order count
   - No more mismatches

Example of correct output:
```
17:28:25,285 - child_order_registered, count=2 (second child overall)
17:28:25,288 - (next event)
17:28:26,288 - child_order_registered, count=3 (third child overall)
17:28:26,297 - (next event)
```

NOT:
```
17:28:25,285 - child_order_registered, count=2
17:28:25,294 - child_order_registered, count=3 (SAME ORDER registered again!)
```

---

## Files Modified

1. [e:\coinbase\core\order_engine.py](e:\coinbase\core\order_engine.py)
   - Line ~2670: Removed duplicate register_child_order call
   - Line ~1368: Modified register_child_order to track new children
   - Line ~1395: Only increment database when is_new_child = True

---

## Why This Happened

The code had multiple layers of "protection" that didn't properly coordinate:

1. **Claim check** prevented concurrent event threads from processing the same order
   - ✅ This worked correctly
2. **Duplicate registration check** in register_child_order prevented adding same child twice to in-memory list
   - ✅ This worked correctly
3. **But** the database increment happened outside the duplicate check
   - ❌ This caused count mismatches
4. **Additionally** code path had TWO calls to register_child_order for the same order in the same event
   - ❌ This meant both the duplicate prevention AND the unprotected increment both happened

The fixes ensure:
- Only ONE call to register_child_order per order per event
- Database increments ONLY when actually adding a new child
- Memory and database stay synchronized

