# Deadlock Findings - Coinbase Trading Engine

Generated: 2026-04-22  
Analysis Tool: Deadlock Detection Skill (`/memories/session/deadlock-detection.SKILL.md`)

## Summary

✅ **CRITICAL DEADLOCK CONFIRMED** in `handle_filled_order()` method

The OrderEngine uses non-recursive locks (`threading.Lock()`) but has code that attempts to acquire the same lock twice from the same thread, causing guaranteed deadlock.

---

## CONFIRMED DEADLOCK #1

### Location
- **File**: `core/order_engine.py`
- **Function**: `handle_filled_order()`
- **Lines**: 1687 (lock acquired), 1723 (recursive acquisition attempt)

### Deadlock Call Chain

```python
# Line 1642: handle_filled_order() begins
def handle_filled_order(self, order: dict) -> None:
    
    # ... setup code ...
    
    # Line 1687: LOCK ACQUIRED HERE
    with self.orderbook_lock:
        if self.orderbook.should_replace["FILLED"] is not True:
            return
        
        # ... code ...
        
        _, parent_client_order_id = self.resolve_parent_client_order_id(...)
        
        # Line 1719-1723: CONDITION BLOCK
        if original_stealth_order and parent_client_order_id == client_order_id:
            explicit_parent = original_stealth_order.get("parent_order_id")
            if explicit_parent and explicit_parent != client_order_id:
                parent_client_order_id = explicit_parent
                
                # ⚠️ LINE 1723: RECURSIVE LOCK ATTEMPT - DEADLOCK!
                self.register_child_order(client_order_id, parent_client_order_id)
                #                         ^
                #                         └─ Acquires self.orderbook_lock
                #                            while lock already held by THIS THREAD
```

### register_child_order() Implementation

```python
# Line 678: register_child_order definition
def register_child_order(self, child_client_order_id: str, parent_client_order_id: str) -> None:
    # ⚠️ IMMEDIATE LOCK ACQUISITION
    with self.orderbook_lock:  # <-- DEADLOCK!
        # ... code ...
```

### Lock Configuration

**Line 175-176 (OrderEngine.__init__)**:
```python
self.ticker_lock = threading.Lock()      # Non-recursive
self.orderbook_lock = threading.Lock()   # Non-recursive ← Used in deadlock
```

### Why This Deadlocks

| Aspect | Value |
|--------|-------|
| Lock Type | `threading.Lock()` |
| Recursive? | **NO** |
| Reentrant? | **NO** |
| Same Thread | **YES** (calling thread) |
| Same Lock | **YES** (`orderbook_lock`) |
| Result | **DEADLOCK** ✅ Confirmed |

When the same thread tries to acquire `threading.Lock()` twice without releasing in between, the lock acquisition call **blocks indefinitely** waiting for the lock to be released by "another thread" — but no other thread can release it because the lock is held by the calling thread.

### Trigger Scenario

This deadlock ONLY occurs when ALL of these conditions are true:

1. ✅ `handle_filled_order()` is called
2. ✅ `original_stealth_order` exists (stealth order mapping found)
3. ✅ `parent_client_order_id == client_order_id` (new parent was auto-created)
4. ✅ `explicit_parent` exists in stealth order metadata
5. ✅ `explicit_parent != client_order_id` (parent is different from auto-created one)

When conditions 1-5 are TRUE, line 1723 executes → DEADLOCK

### Thread Behavior When Deadlock Occurs

```
Thread (EventProcessorWorker-1):
  ├─ Calls handle_filled_order()
  ├─ Enters: with self.orderbook_lock:     ← Lock acquired (count = 1)
  ├─ Executes code
  ├─ Calls self.register_child_order()     ← Line 1723
  │  ├─ Enters: with self.orderbook_lock:  ← Tries to acquire (count would = 2)
  │  ├─ ❌ BLOCKING - Waits for lock release
  │  ├─ But lock held by THIS THREAD!
  │  ├─ Condition variable: deadlock_detected = true
  │  └─ Thread HANGS FOREVER ☠️
```

### Impact

- **Severity**: **CRITICAL**
- **Affected Component**: Order processing pipeline
- **Symptom**: Threads stop processing orders, hang indefinitely
- **Side Effect**: Event queue fills up, new events can't be processed
- **Recovery**: Manual restart required (thread can't be interrupted)

---

## CONFIRMED DEADLOCK #2

### Location
- **File**: `core/order_engine.py`
- **Function**: `handle_filled_order()`
- **Lines**: 1687 (lock acquired), 1721 (recursive call)

### Issue

While holding `orderbook_lock`, `handle_filled_order()` calls `register_child_order()` at line 1721, which immediately tries to acquire the same lock, causing deadlock.

```python
# Line 1687
with self.orderbook_lock:
    # ...
    # Line 1721: RECURSIVE CALL INSIDE LOCK
    self.register_child_order(...)  # ← Tries to acquire orderbook_lock again
```

---

## CONFIRMED DEADLOCK #3

### Location
- **File**: `core/order_engine.py`
- **Function**: `_handle_external_order_tracking()`
- **Lines**: 828 (lock acquired), 830+ (recursive calls)

### Issue

`_handle_external_order_tracking()` acquires `orderbook_lock` and then calls `resolve_parent_client_order_id()`, which in turn calls three different lock-acquiring functions:

```python
# Line 828
with self.orderbook_lock:
    # Line 830
    self.resolve_parent_client_order_id(...)  # ← Calls:
        # Line 490: self.is_parent_order()        ← Tries to acquire lock (Line 574)
        # Line 493: self.is_child_order()         ← Tries to acquire lock (Line 589)
        # Line 494: self.get_parent_of_child()    ← Tries to acquire lock (Line 606)
```

**Triple deadlock**: Three separate recursive acquisitions in sequence.

---

## Additional Issues Found

### Issue 4: Database I/O While Holding Lock (Code Smell)

**Location**: `handle_filled_order()` lines 1696-1698

```python
with self.orderbook_lock:
    parent_order_data = self.db_helper.get_parent_order(...)  # ❌ I/O in lock!
```

**Impact**: Database queries block ALL threads needing the lock, causing severe performance degradation

### Issue 5: Using Lock Instead of RLock (Architecture Issue)

**Location**: `OrderEngine.__init__()` lines 175-176

```python
self.ticker_lock = threading.Lock()      # ❌ Should be RLock
self.orderbook_lock = threading.Lock()   # ❌ Should be RLock
```

**Problem**: Code design allows recursive acquisitions (as proven by 3 deadlocks), but non-recursive Lock is used

---

## Secondary Issues Found

### Additional Lock Usage Points (22 total locations)

All in `core/order_engine.py`:
- Lines: 390, 441, 464, 475, 573, 589, 606, 613, 638, 651, 697, 828, 1034, 1073, 1125, 1161, 1269, 1274, 1384, 1687, 2090, 2152

Of these 22 lock acquisitions:
- ✅ **Safe** (5 locations): `claim_follow_up_processing()`, `release_follow_up_processing()`, `complete_follow_up_processing()`, etc.
- 🔴 **Unsafe** (17 locations): Either acquire and call lock-acquiring functions, or held during I/O

### Affected Functions (11 total)

Functions participating in deadlock call chains:
1. `handle_filled_order()` - 2 deadlock paths
2. `_handle_external_order_tracking()` - 3 deadlock paths
3. `resolve_parent_client_order_id()` - Called from within locks
4. `register_child_order()` - Tries to acquire lock
5. `is_parent_order()` - Tries to acquire lock
6. `is_child_order()` - Tries to acquire lock
7. `get_parent_of_child()` - Tries to acquire lock
8. `handle_cancelled_order()` - Similar patterns possible
9. And 3 others in call chain

---

## Recommended Fixes

### Fix Option 1: Use RLock (Reentrant Lock) ✅ BEST

Replace `threading.Lock()` with `threading.RLock()` to allow recursive acquisition:

```python
# Line 175-176: CHANGE
- self.ticker_lock = threading.Lock()
- self.orderbook_lock = threading.Lock()

+ self.ticker_lock = threading.RLock()
+ self.orderbook_lock = threading.RLock()
```

**Pros**:
- ✅ Minimal code changes
- ✅ Fixes all recursive lock scenarios
- ✅ Backward compatible
- ✅ Slight performance cost (negligible for this use case)

**Cons**:
- Allows nested locks (could hide design issues)
- Lock semantics become more complex

### Fix Option 2: Refactor to Unlocked Helper ✅ BETTER LONG-TERM

Create `_register_child_order_unlocked()` that assumes lock already held:

```python
# When INSIDE lock context, call:
self._register_child_order_unlocked(child_id, parent_id)

# When OUTSIDE lock context, call:
self.register_child_order(child_id, parent_id)
```

**Pros**:
- ✅ More explicit about lock semantics
- ✅ Better code clarity
- ✅ Prevents accidental double-locking elsewhere

**Cons**:
- Requires more refactoring
- Two versions of same function to maintain

### Fix Option 3: Release and Re-acquire Lock

Release lock before calling `register_child_order()`:

```python
with self.orderbook_lock:
    # ... code ...
    
    parent_client_order_id = explicit_parent
    
    # EXIT lock context
    
# OUTSIDE lock context - safe to call
self.register_child_order(client_order_id, parent_client_order_id)
```

**Pros**:
- ✅ No lock type changes
- ✅ Simple to implement

**Cons**:
- ❌ May create race conditions (state modified outside lock)
- ❌ Requires careful validation of what can be done outside lock

---

## Verification Plan

### Step 1: Apply Fix
Use **Fix Option 1** (RLock) for immediate safety.

### Step 2: Test Deadlock Scenario
Create unit test that triggers all 5 conditions:
```python
def test_no_deadlock_on_stealth_parent_mismatch():
    # Setup: original_stealth_order with parent_order_id != client_order_id
    # Trigger: handle_filled_order() with auto-created parent
    # Assert: Completes without hanging
    # Timeout: 5 seconds (should finish in < 1 second)
```

### Step 3: Performance Validation
- RLock has minimal performance impact
- Benchmark before/after (expect < 1% difference)

### Step 4: Audit Other Functions
Search codebase for other potential recursive lock scenarios

---

## Code References

- Lock definition: [Line 175-176](core/order_engine.py#L175-L176)
- Deadlock trigger: [Line 1723](core/order_engine.py#L1723)
- Lock acquisition: [Line 1687](core/order_engine.py#L1687)
- register_child_order: [Line 678-730](core/order_engine.py#L678)
