> Documentation status (2026-05-02): **Archival (historical implementation note)**
> This file records point-in-time analysis or implementation history and may not match current runtime behavior.
> Canonical living docs: genai_data/README.md, genai_data/ARCHITECTURE.md, genai_data/ORDER_ID_HANDLING.md, genai_data/TESTING_STRATEGY.md.
# Root Cause Analysis: Partial Fills Loop

## The Loop Pattern

```
Order placed → Order cancelled (0.0 executed) → Follow-up created → Follow-up placed → 
Follow-up cancelled (0.0 executed) → New follow-up created → ...
```

Replacement count keeps incrementing: 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14...

## Root Cause: Race Condition in handle_cancelled_order()

**File:** core/order_engine.py, method `handle_cancelled_order()`
**Lines:** 2163-2184

### The Bug

**CURRENT (WRONG) ORDER:**
```python
# Line 2163-2169: REGISTER CHILD FIRST
if original_stealth_order and original_stealth_order.get("parent_order_id"):
    parent_client_order_id_stealth = original_stealth_order["parent_order_id"]
    self.register_child_order(client_order_id, parent_client_order_id_stealth)  # ← INCREMENTS COUNT

# Line 2173: Comment says "CLAIM FIRST TO PREVENT DUPLICATES"
# CRITICAL: Claim follow-up processing FIRST to prevent duplicates

# Line 2175-2184: TRY TO CLAIM AFTER REGISTRATION
if not self.claim_follow_up_processing("cancelled", client_order_id):  # ← TOO LATE!
    return
```

### Why This Creates a Loop

1. **Thread A** processes cancelled order:
   - Registers child (replacement count increments: 5 → 6)
   - Claims follow-up processing (succeeds)
   - Creates new follow-up order

2. **Thread B** processes THE SAME cancelled order (race condition):
   - Registers child (replacement count increments again: 6 → 7)  ← DUPLICATE!
   - Tries to claim follow-up processing (fails - already claimed by A)
   - Logs "follow_up_already_claimed" warning and returns

3. **Result**: Same order registered twice, replacement count incremented twice, but follow-up created only once

### Why Orders Get Cancelled Immediately

With partial fills enabled:
- Stealth order is revealed and placed on exchange
- Any cancellation event (from WebSocket) triggers `handle_cancelled_order()`
- This creates a follow-up order
- If the follow-up also gets cancelled (which it does immediately), it creates another follow-up
- This repeats endlessly because:
  - The same order keeps getting registered as a child multiple times
  - Replacement count keeps incrementing
  - System thinks there should be another follow-up
  - But the cancellation loop prevents any fills from happening

## The Fix

**Move `claim_follow_up_processing()` BEFORE `register_child_order()`**

**CORRECT ORDER:**
```python
# FIRST: Claim processing rights atomically
if not self.claim_follow_up_processing("cancelled", client_order_id):
    return  # ← Exit before registering anything

# SECOND: Register child (only if we claimed processing)
if original_stealth_order and original_stealth_order.get("parent_order_id"):
    parent_client_order_id_stealth = original_stealth_order["parent_order_id"]
    self.register_child_order(client_order_id, parent_client_order_id_stealth)

# Continue with follow-up creation...
```

## Why This Works

- **Atomicity**: `claim_follow_up_processing()` uses orderbook_lock for atomic check-and-set
- **Early exit**: If already processing, return BEFORE any registration
- **No duplicates**: Same order can only be registered once (by the thread that claimed it)
- **Prevents race conditions**: Only one thread can pass the claim check

## Database Impact

The replacement count increments in both:
1. Memory: `self.orderbook.parent_order_ids[parent]["current_order_replacement"]`
2. Database: `increment_order_parent_replacement_count(parent_client_order_id)`

With the race condition, both threads call `increment_order_parent_replacement_count()`, which is why the DB shows count jumping by 2 at a time in some entries.

## Files to Fix

- **core/order_engine.py**: `handle_cancelled_order()` method (~line 2140-2240)
- **core/order_engine.py**: `handle_filled_order()` method (same issue likely exists here)

## Testing Requirement

After fix:
- Run test with partial fills enabled
- Monitor replacement count - should increment by 1, not by 2+
- Verify no "follow_up_already_claimed" warnings in normal operation
- Verify orders eventually execute instead of endless cancel loop

