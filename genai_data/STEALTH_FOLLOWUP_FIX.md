# Stealth Order Follow-Up Fix

## Problem
When stealth orders were revealed and filled, the system marked them as "external orders" and did NOT create follow-up orders. The logs showed:
```
external_order_filled: {reason: "external_order_no_follow_up"}
```

## Root Cause
The issue was in the order of operations in `handle_filled_order()` and `handle_cancelled_order()`:

1. **Early external check** (lines ~1415): Orders were checked against the orderbook to determine if they were "external"
2. **Revealed stealth orders not in orderbook**: When a stealth order revealed a slice, the `client_order_id` was not registered in `orderbook.child_order_ids` or `orderbook.parent_order_ids`
3. **Marked as external**: Since the revealed slice's `client_order_id` wasn't found in the orderbook, it was marked as external
4. **Early return**: The function returned before checking if this was actually a stealth-revealed order (line ~1443)
5. **Late stealth check** (line ~1512): The code to detect and handle stealth reveals was unreachable because the function had already returned

### Flow (BEFORE FIX)
```
handle_filled_order():
  1. client_order_id = "08f0605d-..." (revealed slice)
  2. is_external_order = check orderbook ✗ not found
  3. if is_external_order: return  ← EXITS HERE
  4. Later (NEVER REACHED): Check if this is a stealth order reveal
```

## Solution
Move the stealth order lookup BEFORE the external order check, and register the revealed slice in the orderbook:

### Flow (AFTER FIX)
```
handle_filled_order():
  1. client_order_id = "08f0605d-..." (revealed slice)
  2. Check for stealth order ✓ FOUND
  3. If stealth with parent_order_id:
     - Register as child in orderbook.child_order_ids[client_order_id] = parent_order_id
     - Add to orderbook.parent_order_ids[parent_order_id]["orders"]
  4. is_external_order = check orderbook ✓ NOW FOUND
  5. Continue with normal follow-up processing
```

## Changes Made

### File: `core/order_engine.py`

#### Change 1: `handle_filled_order()` (lines 1398-1475)
- **Lines 1414-1424**: Added early stealth order lookup
- **Lines 1426-1450**: Register revealed slice in orderbook if it's a stealth-revealed order
- **Removed (old line 1539-1547)**: Duplicate stealth order lookup (now at function start)

#### Change 2: `handle_cancelled_order()` (lines 1130-1208)
- Same pattern as `handle_filled_order()`
- Early stealth order lookup before external check
- Register in orderbook before external determination

## Why This Works

1. **Stealth-revealed orders are now recognized**: They're registered in the orderbook when the fill event arrives
2. **External order check passes**: Since they're now in `child_order_ids`, they're not marked as external
3. **Follow-up creation continues**: The function doesn't return early, allowing follow-up order creation
4. **Stealth follow-up detection**: The stealth order is already found, so stealth follow-ups are created instead of regular child orders

## Tested
- ✅ All 10 regression tests pass
- ✅ Custom test: `genai_tools/test_stealth_followup_fix.py` verifies:
  - Revealed orders are registered in orderbook
  - They're linked to their parent order
  - They're NOT marked as external
  - Follow-up processing is claimed

## Impact
- Stealth order revealed slices now correctly trigger follow-up orders
- Regular orders (non-stealth) are unaffected
- External orders (created in Coinbase UI) still correctly skip follow-ups
