> Documentation status (2026-05-02): **Archival (historical implementation note)**
> This file records point-in-time analysis or implementation history and may not match current runtime behavior.
> Canonical living docs: genai_data/README.md, genai_data/ARCHITECTURE.md, genai_data/ORDER_ID_HANDLING.md, genai_data/TESTING_STRATEGY.md.
# Partial Fills Loop - FIX APPLIED

## The Problem

Partial fill orders were getting stuck in an endless loop:
1. Order placed → immediately cancelled (0.0 executed) 
2. Cancellation triggers follow-up creation
3. Follow-up placed → immediately cancelled
4. New follow-up created...
5. Replacement count keeps incrementing: 5 → 6 → 7 → 8 → 9 → ...

## Root Cause

**Race condition in order event processing**: Same order was being processed by multiple concurrent threads, causing:
- Same child order registered TWICE (increment count twice)
- "follow_up_already_claimed" warnings when second thread detected it was already processing

**Location of bug**: core/order_engine.py
- `handle_cancelled_order()` method (~line 2154)
- `handle_filled_order()` method (~line 2481)

**The Issue**: 
- `register_child_order()` was called BEFORE `claim_follow_up_processing()`
- This allowed a race condition where two threads could both register the same child
- Then one thread would claim processing, and the other would fail the claim but damage was already done

## The Fix

### Applied to `handle_cancelled_order()` (line ~2154)

**BEFORE (WRONG ORDER):**
```python
# Line 2163-2169: REGISTER FIRST
if original_stealth_order and original_stealth_order.get("parent_order_id"):
    self.register_child_order(client_order_id, parent_client_order_id_stealth)

# Line 2173: COMMENT SAYS CLAIM FIRST
# CRITICAL: Claim follow-up processing FIRST to prevent duplicates

# Line 2175-2184: TRY TO CLAIM AFTER REGISTRATION
if not self.claim_follow_up_processing("cancelled", client_order_id):
    return
```

**AFTER (CORRECT ORDER):**
```python
# Line 2154-2168: CLAIM FIRST (atomically prevents duplicates)
if not self.claim_follow_up_processing("cancelled", client_order_id):
    return

# Line 2170-2195: THEN REGISTER CHILD (only if we claimed processing)
if original_stealth_order and original_stealth_order.get("parent_order_id"):
    self.register_child_order(client_order_id, parent_client_order_id_stealth)
```

### Applied to `handle_filled_order()` (line ~2481)

**BEFORE (WRONG ORDER):**
```python
# Line 2505-2511: REGISTER FIRST
if original_stealth_order and original_stealth_order.get("parent_order_id"):
    self.register_child_order(client_order_id, parent_client_order_id_stealth)

# Line 2514-2551: FILL RECORDING (lots of code)
# ... fill recording logic ...

# Line 2553-2565: THEN TRY TO CLAIM
if not self.claim_follow_up_processing("filled", client_order_id):
    return
```

**AFTER (CORRECT ORDER):**
```python
# Line 2481-2496: CLAIM FIRST (atomically prevents duplicates)
if not self.claim_follow_up_processing("filled", client_order_id):
    return

# Line 2498-2512: THEN REGISTER CHILD (only if we claimed processing)
if original_stealth_order and original_stealth_order.get("parent_order_id"):
    self.register_child_order(client_order_id, parent_client_order_id_stealth)

# Line 2514-2551: FILL RECORDING (happens after claim, before follow-up creation)
# ... fill recording logic ...

# Note: Removed the second claim_follow_up_processing call that was redundant
```

## How This Fixes the Loop

**Atomicity**: `claim_follow_up_processing()` uses `orderbook_lock` for atomic check-and-set:
```python
with self.orderbook_lock:
    state = processed_flags.get(client_order_id)
    if state in {"processing", "done", True}:
        return False  # Already claimed
    processed_flags[client_order_id] = "processing"  # Mark as processing
    return True
```

**Race Condition Prevented**:
1. Thread A: Claims successfully, sets to "processing"
2. Thread B: Tries to claim, gets False immediately
3. Thread B: Exits before registering child
4. Result: Same child only registered ONCE (count incremented once)

**No more loop**:
- Each order processed only once
- Replacement count increments by 1 (not 2+)
- Follow-up orders created correctly
- No more "follow_up_already_claimed" warnings in normal operation

## Files Modified

- **core/order_engine.py**:
  - `handle_cancelled_order()` method: Moved claim before registration (line ~2154)
  - `handle_filled_order()` method: Moved claim to very start, removed duplicate claim (line ~2481)

## Testing Requirements

After deployment, verify:
1. ✓ Replacement count increments by 1 (not 2+)
2. ✓ No "follow_up_already_claimed" warnings in logs
3. ✓ Orders execute instead of endless cancel loop
4. ✓ Partial fills work correctly with follow-ups
5. ✓ Single threaded processing of same order

## Backward Compatibility

✓ 100% backward compatible
✓ No API changes
✓ No database changes
✓ No configuration needed

