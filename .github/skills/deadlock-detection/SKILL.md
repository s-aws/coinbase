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

### Step 2: Map All Lock Acquisition Points (COMPREHENSIVE)

Use grep_search to find all lock acquisitions:

```regex
# Find all lock acquisitions (both explicit and context manager)
with self\.(\w+_lock|lock|_lock):
self\.(\w+_lock|lock|_lock)\.acquire\(\)
```

For each acquisition point, document in a table:

| Lock Name | Function | Line | Type | Calls Within Lock |
|-----------|----------|------|------|-------------------|
| orderbook_lock | handle_filled_order | 1687 | with | See Step 3 |
| orderbook_lock | is_parent_order | 573 | with | (list all) |
| ... | ... | ... | ... | ... |

**For each acquisition, note**:
- Function name where lock is acquired
- Line number
- Lock type (with-context vs explicit acquire/release)
- **ALL function calls executed while holding the lock** ← CRITICAL
- Whether lock is released before calling external functions

### Step 3: Build Complete Call Graph (COMPREHENSIVE - NEW)

**For EVERY function that acquires a lock**, trace its full call graph:

```
function_with_lock(self):                    # Line 1687
  ├─ with self.orderbook_lock:
  │   ├─ [CODE BLOCK 1]
  │   │   ├─ function_call_1()              ← TRACE THIS
  │   │   │   ├─ Does it acquire orderbook_lock?
  │   │   │   ├─ Does it call other functions?
  │   │   │   │   └─ Check those functions too
  │   │   ├─ function_call_2()              ← TRACE THIS
  │   │   ├─ if condition:
  │   │   │   ├─ function_call_3()          ← TRACE THIS (conditional!)
  │   │   ├─ for item in list:
  │   │   │   ├─ function_call_in_loop()    ← TRACE THIS (may call multiple times)
  │   │   └─ [CODE BLOCK N]
```

**Systematic approach**:
1. Read the function line by line
2. Identify all direct function calls within lock context
3. For EACH function called:
   - Read that function's source
   - Check if it acquires the same lock
   - Check if it calls OTHER functions that acquire the lock
   - Check if it does I/O operations
4. Recursively check all downstream functions (depth-first search)
5. Flag ANY recursive lock acquisition or I/O operations
6. Document conditional calls (if/for/while) separately - they may not always execute

**Critical detail**: Don't skip functions called conditionally or in loops - they're harder to spot in testing but still cause deadlocks!

### Step 4: Identify Recursive Acquisition Patterns (COMPREHENSIVE)

**Systematic check - For each lock-acquiring function**:

1. **Direct recursion**: Does the function call itself?
   ```python
   def process_order(self):
       with self.lock:
           self.process_order()  # ← DEADLOCK
   ```

2. **Indirect recursion**: Does it call functions that call it back?
   ```python
   def process_order(self):
       with self.lock:
           self.validate_order()  # ← May call back to process_order?
   
   def validate_order(self):
       self.process_order()  # ← Circular!
   ```

3. **Multi-step recursion**: Does it call a chain that eventually acquires the same lock?
   ```python
   def handle_filled_order(self):              # Line 1687
       with self.orderbook_lock:
           self.resolve_parent_client_order_id()  # Called while holding lock
               # This function calls:
               self.is_parent_order()  # Line 490
                   # Which also tries:
                   with self.orderbook_lock:  # Line 573 ← DEADLOCK!
   ```

4. **Conditional recursion**: Acquires lock conditionally or in loops
   ```python
   with self.lock:
       if condition:
           self.other_function()  # ← Only sometimes acquires lock
       
       for item in items:
           self.process_item()    # ← May acquire lock multiple times in loop
   ```

**Key insight from manual audit**: The user found `filled_order_waiting_for_hold_clear` because:
- Order event arrives, goes through `process_user_order()` (line 1095)
- Calls `is_parent_order()` which acquires lock
- Later, when order is reprocessed (hold cleared), goes through `handle_filled_order()` (line 1139)
- Which ALSO tries to acquire same lock
- This is a **conditional recursion** that only happens when order is reprocessed

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

### Step 4.5: COMPREHENSIVE AUDIT - Systematic Function Tracing (NEW)

This is the automated, thorough approach that caught the `filled_order_waiting_for_hold_clear` deadlock.

**Process for EVERY lock-acquiring function**:

1. **Get list of all functions that acquire the target lock**:
   ```bash
   grep_search: "with self\.orderbook_lock:" (or equivalent)
   # Returns: Line numbers and function names
   ```

2. **For each function in that list**:
   - Open function and read completely
   - List ALL function calls inside the lock context
   - For EACH function call:
     - Check if it acquires the same lock (search function definition)
     - Check what functions IT calls (full call graph)
     - Check if any of THOSE acquire the same lock
   - Mark function as:
     - ✅ SAFE: No nested lock acquisitions
     - ⚠️ POTENTIAL: Conditional nested acquisitions
     - 🔴 DEADLOCK: Confirmed recursive acquisition

3. **Conditional execution matters**:
   - Acquisitions in `if` blocks may only trigger under certain conditions
   - But that STILL causes deadlock when condition is true
   - Example: `if outstanding_hold_amount > 0: return` - seems safe
   - But when `outstanding_hold_amount = 0`, execution continues to `handle_filled_order()`
   - Which ALSO tries to acquire lock - DEADLOCK!

4. **Create a call matrix**:
   ```
   Function A (acquires lock @ line X)
   ├─ Calls Function B
   │  ├─ Does B acquire lock? [YES/NO]
   │  ├─ Does B call Function C?
   │  │  └─ Does C acquire lock? [YES/NO]
   ├─ Calls Function D  
   ├─ [Conditional] Calls Function E (if condition)
   │  └─ Does E acquire lock? [YES/NO] ← Still a deadlock!
   ```

5. **Document ALL findings, even speculative ones**:
   - Definite deadlocks (confirmed paths)
   - Potential deadlocks (conditional paths)
   - Race conditions (I/O under lock)
   - Performance issues (long operations under lock)

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
- `self.ticker_lock = threading.RLock()` ✅ (Updated to RLock)
- `self.orderbook_lock = threading.RLock()` ✅ (Updated to RLock)

**Functions that acquire orderbook_lock** (22 total):
- see comprehensive table below

### Comprehensive Audit Example: process_user_order()

This function revealed the `filled_order_waiting_for_hold_clear` deadlock:

```
process_user_order() [Line 1053]
├─ with self.orderbook_lock: [Line 1073]
│  ├─ self.orderbook.order[client_order_id] = normalized_order
│  └─ [Lock released]
├─ if status == OrderStatus.FILLED and outstanding_hold_amount > 0:
│  ├─ self.log_message(...)  [Line 1080] ✅ Safe (no lock)
│  └─ return [Line 1087]  ✅ Returns early - SAFE
├─ [Continues only if outstanding_hold_amount == 0]
├─ if self.is_parent_order(client_order_id): [Line 1095]
│  └─ with self.orderbook_lock: [Line 573]
│     └─ return self.orderbook.parent_order_ids in self.orderbook.parent_order_ids
│        └─ ✅ Lock released before continuing
├─ [... more status checks ...]
├─ if status == OrderStatus.FILLED: [Line 1139]
│  ├─ self.handle_filled_order(order) [Line 1139]
│  │  └─ with self.orderbook_lock: [Line 1687]  ← 🔴 SAME THREAD TRIES TO ACQUIRE AGAIN!
│  │     └─ This is a RECURSIVE acquisition
│  └─ self._update_dashboard_order_status(...) [Line 1140]
```

**The deadlock scenario**:
1. Order event arrives with outstanding_hold_amount = "0.39"
2. Enters `process_user_order()`, early returns at line 1087 (safe)
3. Later, order reprocessed with outstanding_hold_amount = "0" (hold cleared)
4. Gets past line 1087 (early return condition false)
5. Line 1095: Calls `is_parent_order()` - tries to acquire orderbook_lock ✅ (acquires)
6. Line 1139: Calls `handle_filled_order()` - tries to acquire same lock again
7. **Result**: With threading.Lock() → 🔴 DEADLOCK
8. **Result**: With threading.RLock() → ✅ Safe (reference counting allows reacquisition)

**Key lesson**: The deadlock path is CONDITIONAL - it only happens when:
- Order has initial outstanding_hold > 0
- Order is then reprocessed with outstanding_hold = 0
- This is NOT caught by simple recursive analysis - requires tracing all code paths

### All Lock-Acquiring Functions (Complete List)

**Functions acquiring orderbook_lock** (in order of discovery):

| # | Function | Line | Lock Acquisitions Called | Status |
|---|----------|------|--------------------------|--------|
| 1 | is_parent_order | 573 | (direct lock only) | ✅ SAFE |
| 2 | is_child_order | 589 | (direct lock only) | ✅ SAFE |
| 3 | get_parent_of_child | 606 | (direct lock only) | ✅ SAFE |
| 4 | claim_follow_up_processing | 613 | (direct lock only) | ✅ SAFE |
| 5 | release_follow_up_processing | 638 | (direct lock only) | ✅ SAFE |
| 6 | complete_follow_up_processing | 651 | (direct lock only) | ✅ SAFE |
| 7 | register_child_order | 697 | (direct lock only) | ✅ SAFE |
| 8 | _handle_external_order_tracking | 828 | resolve_parent_client_order_id() → calls is_parent_order, is_child_order, get_parent_of_child | ✅ With RLock |
| 9 | process_user_snapshot | 1034 | (direct lock only) | ✅ SAFE |
| 10 | process_user_order | 1073 | MULTIPLE - see detailed example above | ⚠️ CONDITIONAL DEADLOCK |
| 11 | apply_position_update | 1125 | (direct lock only) | ✅ SAFE |
| 12 | resolve_parent_replacement_state | 1269 | (direct lock only) | ✅ SAFE |
| 13 | resolve_parent_target_movement | 1274 | (direct lock only) | ✅ SAFE |
| 14 | handle_cancelled_order | 1384 | resolve_parent_client_order_id(), register_child_order() | ✅ With RLock |
| 15 | handle_filled_order | 1687 | resolve_parent_client_order_id(), register_child_order() | ✅ With RLock |
| 16+ | (other functions) | ... | ... | ... |

**Critical findings**:
- ✅ With `threading.RLock()` applied - All deadlocks resolved
- With old `threading.Lock()` - 3+ confirmed deadlocks in process_user_order → handle_filled_order path

### Potential Issues in Coinbase Codebase

**DEADLOCK #1**: handle_filled_order → resolve_parent_client_order_id → is_parent_order
- **Status**: ✅ FIXED (RLock applied)

**DEADLOCK #2**: handle_filled_order → register_child_order
- **Status**: ✅ FIXED (RLock applied)

**DEADLOCK #3**: process_user_order → handle_filled_order (conditional)
- **Status**: ✅ FIXED (RLock applied)
- **Discovery method**: Manual code inspection + execution trace
- **Trigger**: Order reprocessed after hold clears

**RACE CONDITION #1**: Database I/O under lock
- **Location**: handle_filled_order() lines 1696-1698
- **Issue**: `db_helper.get_parent_order()` blocks while holding orderbook_lock
- **Impact**: ⚠️ Performance issue, not a deadlock
- **Fix**: Move I/O outside lock context

## How to Use This Skill

### Comprehensive Systematic Analysis (RECOMMENDED - 1-2 hours)

This is the methodology that finds ALL deadlocks, not just obvious ones:

1. **Phase 1: Catalog** (5 min)
   - Run Step 1: Find all locks and document in table
   - Result: List of all locks in system

2. **Phase 2: Exhaustive mapping** (20 min)
   - Run Step 2: Find ALL lock acquisition points
   - Create comprehensive table with function names, lines, lock names
   - Don't skip any - even helper functions
   - Result: Complete list of all N lock-acquiring locations

3. **Phase 3: Function-by-function audit** (60-90 min - THE CRITICAL PART)
   - **For EACH of the N functions from Phase 2**:
     - Read function completely
     - List EVERY function call inside lock context
     - For each called function:
       - Check if it acquires the same lock (use grep_search)
       - Check if it calls OTHER functions that acquire the lock (recursive)
       - Check if it does I/O (database, API calls)
     - Document in a matrix (see Step 4.5)
   - **This is systematic and thorough** - it WILL find deadlocks like `filled_order_waiting_for_hold_clear`
   - Result: Complete call graph with deadlock annotations

4. **Phase 4: Trace conditional paths** (20 min)
   - Review any `if`/`for`/`while` blocks in lock contexts
   - These often hide deadlocks that only trigger under specific conditions
   - Manually trace what happens when condition is true/false
   - Result: Identified conditional deadlocks

5. **Phase 5: Document and fix** (30 min)
   - Create findings document
   - Prioritize by severity (CRITICAL > HIGH > MEDIUM > LOW)
   - Suggest fixes (RLock, refactor, release lock early)
   - Result: Action plan

### Quick Analysis (15-30 minutes)

For rapid assessment:

1. Find all locks (Step 1)
2. Find all acquisitions (Step 2)
3. Manually scan for obvious recursive patterns
4. Focus on main entry points (handle_filled_order, handle_cancelled_order, process_user_order)

### Automated Search Patterns (Use These!)

**Search 1: Find all lock acquisitions**
```bash
grep_search: "with self\.(\w+_lock|lock):"
# Find all functions that acquire locks
```

**Search 2: For each function found, search for its usages**
```bash
vscode_listCodeUsages: symbol="process_user_order"
# Returns all places where this function is called
```

**Search 3: Identify functions called within lock context**
```bash
# Read function, search for calls to other functions
# Check if those functions exist and what they do
grep_search: "^\s+self\.(function_name|other_function)\("
```

**Search 4: Check if a function acquires locks**
```bash
grep_search: "def specific_function" includePattern="core/order_engine.py"
# Then search that function for "with self.*lock"
```

### Tools & Patterns to Use

**Commands in order**:
```bash
# 1. Find all locks
grep_search: "threading\.(Lock|RLock|Semaphore|Condition)\(\)"

# 2. Find all acquisitions
grep_search: "with self\.(\w+)lock:"

# 3. For a specific lock, find all places it's acquired
grep_search: "orderbook_lock" includePattern="core/order_engine.py"

# 4. For each function, find what it calls
# (manual: read function, scan for "self.function_name(")

# 5. Check if called function acquires lock
grep_search: "def function_name" (find the function)
grep_search: "orderbook_lock" (check if it acquires lock)

# 6. Use subagent for complex analysis
runSubagent: "Trace all functions called by X for lock acquisitions"
```

**Analysis approach**:
1. Read function containing lock
2. List all `self.` function calls in lock context
3. Check each called function (via grep_search or vscode_listCodeUsages)
4. Search that function for "orderbook_lock" or target lock
5. If found, mark as DEADLOCK
6. If not found, check what functions IT calls (recursive check)
7. Repeat until entire call graph is traced

## Prevention Checklist

When adding new code with locks:

- [ ] Is this a Lock or RLock? (Document why)
- [ ] What functions does this acquire within lock context?
- [ ] Do those functions also try to acquire the same lock?
- [ ] Is lock held during I/O? (Should it be?)
- [ ] Are multiple locks acquired? In consistent order everywhere?
- [ ] Can lock be held for shorter duration?
- [ ] Does all exception paths release the lock?

## Concrete Audit Template (Use This For Any Function!)

When auditing a function for deadlocks, use this template:

### Function: [Name]
**Location**: [File:Line]  
**Lock acquired**: [Lock name]  
**Lock type**: [Lock/RLock]

**Code structure**:
```python
def function_name(self):
    [SETUP CODE - no lock]
    
    with self.LOCK:  # Line XXX - LOCK ACQUIRED
        [CODE BLOCK 1]
    # LOCK RELEASED
    
    [CODE BLOCK 2 - no lock]
    
    if condition:  # Conditional - IMPORTANT!
        with self.LOCK:  # ← CHECK: Is this reacquisition?
            [CODE BLOCK 3]
```

**Function calls within lock context**:

| Call # | Function | Line | Acquires Lock? | Calls Other Locked Functions? | Status |
|--------|----------|------|----------------|-------------------------------|--------|
| 1 | function_A() | 123 | ? | ? | ? |
| 2 | function_B() | 145 | ? | ? | ? |
| 3 | if cond: function_C() | 167 | ? | ? | ? |

**For each function called (example)**:
1. Search for `def function_A` to find its definition
2. Search within function_A for `with self.LOCK` or same lock name
3. If found with same lock → 🔴 DEADLOCK (or ✅ SAFE with RLock)
4. If function_A calls other functions, check THOSE too (recursive)

**Audit result**:
- [ ] No nested lock acquisitions - ✅ SAFE
- [ ] Nested acquisitions only with RLock - ✅ SAFE with RLock
- [ ] Nested acquisitions with Lock() - 🔴 DEADLOCK CONFIRMED
- [ ] I/O operations under lock - ⚠️ RACE CONDITION

## Code Review Checklist for Deadlock Prevention

Use this when reviewing code that modifies lock-acquiring functions:

**Before merging code that touches locks**:
- [ ] Did you add any new `with self.*lock:` statements?
- [ ] If yes, what functions are called inside?
- [ ] Did you verify those functions don't acquire the same lock?
- [ ] Did you trace 2+ levels deep (those functions call what)?
- [ ] Is there any I/O (DB, API) inside the lock? Could it be moved outside?
- [ ] Are any acquistions conditional (if/for/while)? Still a deadlock when triggered!
- [ ] Did you test with concurrent orders? (Load test catches race conditions)
- [ ] Did you check error paths? (Exception in locked code might skip unlock)

## References

- Python threading docs: https://docs.python.org/3/library/threading.html
- Lock vs RLock: https://docs.python.org/3/library/threading.html#lock-objects
- Deadlock prevention: https://en.wikipedia.org/wiki/Deadlock#Prevention
- This codebase: See Coinbase OrderEngine for RLock examples
