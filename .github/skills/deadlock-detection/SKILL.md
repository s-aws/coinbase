---
name: deadlock-detection
description: "Detect potential deadlocks caused by recursive lock acquisition, lock ordering violations, and nested lock contexts. Use when: analyzing threading issues, finding deadlock bugs, auditing lock safety, or preventing race conditions in multithreaded code."
---

# Deadlock Detection Workflow

## Overview

This skill provides a systematic methodology for finding deadlock vulnerabilities in Python multithreaded code, particularly focusing on:
- **Recursive lock acquisition**: Same thread acquiring the same lock twice
- **Lock ordering violations**: Multiple locks acquired in inconsistent orders
- **Long-hold periods**: Locks held during I/O or other blocking operations
- **Nested function deadlocks**: Functions acquiring locks while called from lock-holding contexts

## Execution Steps

### Step 1: Catalog All Lock Definitions

Search for lock initialization in the codebase:

```python
# Look for patterns:
self.lock = threading.Lock()
self.lock = threading.RLock()
self.lock = threading.Semaphore(N)
self.lock = threading.Condition()
```

**What to document**:
- Lock variable name
- Lock type (Lock vs RLock vs Semaphore vs Condition)
- Class/module where defined
- Intended purpose (documented or inferred)

**Critical distinction**:
- `threading.Lock()` - Non-recursive, will DEADLOCK on recursive acquisition
- `threading.RLock()` - Recursive, allows same thread to acquire multiple times
- `threading.Semaphore()` - Counter-based, specific release semantics

### Step 2: Map All Lock Acquisition Points

Use grep_search or semantic_search to find all lock acquisitions:

```regex
# Common patterns:
with self\.LOCKNAME:
with self\.LOCKNAME
self\.LOCKNAME\.acquire\(\)
self\.LOCKNAME\.release\(\)
```

For each match, document:
- Function name where lock is acquired
- Line number
- Whether lock is acquired in `with` context (auto-release) or explicit acquire/release
- What code is executed while holding the lock

### Step 3: Trace Call Chains Within Lock Contexts

For each function that acquires a lock, trace what it calls:

**Method 1: Manual inspection**
```python
def function_holding_lock():
    with self.orderbook_lock:
        # What happens here?
        result = self.other_function()  # <-- Does other_function acquire the same lock?
        self.register_child_order()     # <-- Check this function
```

**Method 2: Automated trace**
1. Read the lock-holding function
2. List all function calls within the lock context
3. Check each called function for lock acquisitions
4. Flag if called function acquires the SAME lock

### Step 4: Identify Recursive Acquisition Patterns

Look for these deadlock patterns:

**Pattern A: Direct recursion**
```python
def function_with_lock(self):
    with self.lock:
        self.inner_function()  # <-- May call back to this function

def inner_function(self):
    with self.lock:  # <-- DEADLOCK if called from above!
        pass
```

**Pattern B: Chained recursion**
```python
with self.lock:
    claim_follow_up_processing()  # Acquires lock
    # Later in same function:
    with self.lock:               # <-- DEADLOCK if claim_follow_up_processing still holding!
        pass
```

**Pattern C: Lock ordering violation** (only if multiple locks exist)
```python
# Thread A:
with self.lock1:
    with self.lock2:
        pass

# Thread B:
with self.lock2:
    with self.lock1:  # <-- DEADLOCK: Different order!
        pass
```

### Step 5: Validate Lock Release Semantics

For each lock acquisition, verify:

**For `with` statements**:
- ✅ Lock automatically released on exit (safe)
- Lock released even if exception occurs

**For explicit acquire/release**:
- ⚠️ Verify release is called on all code paths
- ⚠️ Verify exception handling doesn't skip release
- Flag as HIGH RISK - prefer `with` statements

### Step 6: Check Lock Hold Duration

Locks should be held for MINIMAL time:

**RED FLAGS**:
- Database queries while holding lock
- API calls while holding lock
- I/O operations while holding lock
- Loops that call potentially-blocking functions
- Long computations while lock is held

**Example of bad pattern**:
```python
with self.lock:
    data = self.compute_something()        # OK
    db_result = db_helper.query_database() # BAD - I/O while locked!
    self.update_state(db_result)          # OK
```

### Step 7: Document Findings

For each potential deadlock found, document:

1. **Deadlock Type**: (recursive acquisition, lock ordering, lock hold time)
2. **Severity**: (CRITICAL, HIGH, MEDIUM, LOW)
3. **Location**: (function name, lines)
4. **Reproduction Path**: (which function calls which)
5. **Impact**: (will hang? race condition? data corruption?)
6. **Fix**: (use RLock? refactor? release lock earlier?)

## Common Deadlock Scenarios

### Scenario 1: Function acquires lock, calls function that also acquires same lock

```
❌ DEADLOCK on threading.Lock():
function_A() 
  ├─ with self.lock:
  │   ├─ function_B()
  │   │   ├─ with self.lock:  <-- DEADLOCK! Same thread, same lock
```

✅ **Fix**: Use RLock instead of Lock, OR refactor function_B to take a parameter indicating lock already held, OR have two versions (locked/unlocked)

### Scenario 2: Multiple locks acquired in inconsistent order

```
❌ DEADLOCK:
Thread A: with lock1: with lock2: pass
Thread B: with lock2: with lock1: pass  <-- Circular wait
```

✅ **Fix**: Always acquire locks in same order across all functions (lock1, then lock2, never reverse)

### Scenario 3: Lock held during I/O operation

```
❌ DEADLOCK (potential):
with self.lock:
    data = self.db_helper.execute_query(...)  <-- Holds lock while waiting for DB
    if another_thread_tries_to_acquire_lock:  <-- Will block forever
        pass
```

✅ **Fix**: Release lock before I/O, reacquire after if needed. Or use lock-free data structures for the I/O result

## Codebase-Specific Findings

### OrderEngine Locks

**Defined** (core/order_engine.py:175-176):
- `self.ticker_lock = threading.Lock()`
- `self.orderbook_lock = threading.Lock()`

Both are **regular Lock, not RLock** - cannot be recursively acquired by same thread.

### Potential Issues in Coinbase Codebase

**[FINDINGS GO HERE - will be populated by analysis]**

1. **Location**: handle_filled_order / handle_cancelled_order (core/order_engine.py)
   - Type: Potential recursive lock acquisition
   - Pattern: claim_follow_up_processing() acquires lock, then later `with self.orderbook_lock:` in same function
   - Status: [NEEDS_VERIFICATION - depends on if locks are fully released between calls]

2. **Location**: handle_filled_order calls register_child_order (line ~1720)
   - Type: Nested lock acquisition
   - Pattern: Called while `with self.orderbook_lock:` context, register_child_order also acquires same lock
   - Status: [DEADLOCK_CONFIRMED if executed]

## How to Use This Skill

### Quick Analysis (5-15 minutes)
1. Run Step 1: Find all locks
2. Run Step 2: Find all acquisitions
3. Run Step 3: Check for obvious recursive patterns

### Thorough Analysis (30-60 minutes)
1. Run Steps 1-7 in order
2. Create detailed findings document
3. Identify top 3 priorities for fixing

### Continuous Monitoring
1. Add to code review checklist: "Check for lock acquisitions in called functions"
2. Use grep patterns to catch new locks on commit
3. Document lock ordering invariants in project docs

## Tools & Patterns to Use

**Search commands**:
```bash
# Find all locks
grep_search: "threading\.Lock\(\)|threading\.RLock\(\)|\.lock"

# Find lock acquisitions
grep_search: "with self\.\w+_lock:|self\.\w+_lock\.acquire\(\)"

# Find specific lock usage
grep_search: "orderbook_lock" includePattern="core/order_engine.py"

# Trace function calls
vscode_listCodeUsages: symbol="claim_follow_up_processing"
```

**Analysis approach**:
- Read function containing lock
- List all function calls in lock context
- Check each called function for its own lock acquisitions
- Compare with lock hierarchy map

## Prevention Checklist

When adding new code with locks:

- [ ] Is this a Lock or RLock? (Document why)
- [ ] What functions does this acquire within lock context?
- [ ] Do those functions also try to acquire the same lock?
- [ ] Is lock held during I/O? (Should it be?)
- [ ] Are multiple locks acquired? In consistent order everywhere?
- [ ] Can lock be held for shorter duration?
- [ ] Does all exception paths release the lock?

## References

- Python threading docs: https://docs.python.org/3/library/threading.html
- Lock vs RLock: https://docs.python.org/3/library/threading.html#lock-objects
- Deadlock prevention: https://en.wikipedia.org/wiki/Deadlock#Prevention
