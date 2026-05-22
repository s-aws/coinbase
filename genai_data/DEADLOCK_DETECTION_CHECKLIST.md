# Deadlock Detection Automation Checklist

Quick reference for systematically finding deadlocks and race conditions in any codebase.

---

## Quick Deadlock Audit (30 minutes)

Use this checklist for rapid assessment:

### 1. Find All Locks
```bash
SEARCH: threading\.(Lock|RLock|Semaphore|Condition)\(\)
RESULT: List all locks with line numbers and lock types
```
- [ ] Identify Lock vs RLock vs others
- [ ] Non-recursive Lock used? ⚠️ Danger zone for deadlocks

### 2. Find All Lock Acquisitions
```bash
SEARCH: "with self\.\w+lock:" (or explicit acquire/release)
RESULT: 20-50+ locations typically
```
- [ ] For each location, note the function name
- [ ] Note if lock is held during I/O (database, API calls)
- [ ] Create comprehensive table

### 3. High-Risk Function Inspection
Focus on main entry points:
```
- [ ] handle_filled_order()
- [ ] handle_cancelled_order()
- [ ] process_user_order()
- [ ] Any function called very frequently
```

For each:
- [ ] Open function
- [ ] List all calls within lock context
- [ ] Check if any of those functions acquire the same lock
- [ ] Flag as SAFE or DEADLOCK

### 4. Conditional Execution Check
```
- [ ] Any `if` statements in lock context?
- [ ] Any `for` or `while` loops in lock context?
- [ ] Do these conditional branches lead to recursive lock acquisitions?
```

### 5. Document Findings
- [ ] Create findings document with severity levels
- [ ] Prioritize CRITICAL items
- [ ] Suggest fixes (RLock, refactor, move I/O)

---

## Thorough Deadlock Audit (90-120 minutes)

Complete systematic analysis (guaranteed to find all deadlocks):

### Phase 1: Cataloging (10 min)
- [ ] Find all lock definitions
- [ ] Create table: Lock Name | Type | Line | Purpose
- [ ] Identify lock types (Lock = danger, RLock = safe)

### Phase 2: Lock Acquisition Mapping (20 min)
- [ ] Find all `with self.*lock:` statements
- [ ] Find all explicit `.acquire()` and `.release()` calls
- [ ] Create comprehensive table:
  | Function | Line | Lock | Type | Calls |
  
### Phase 3: Function-by-Function Tracing (60-90 min - THE CRITICAL PART)
- [ ] For EACH function that acquires a lock:
  - [ ] Open function definition
  - [ ] Read completely, line by line
  - [ ] List EVERY function call inside lock context
  - [ ] For EACH called function:
    - [ ] Find its definition
    - [ ] Check if it acquires the same lock
    - [ ] Check if it calls OTHER functions that acquire the lock
    - [ ] Recursively trace all downstream calls
  - [ ] Create call graph diagram
  - [ ] Mark as SAFE or DEADLOCK

### Phase 4: Conditional Path Analysis (20 min)
- [ ] Review any `if`/`for`/`while` in lock contexts
- [ ] Trace what happens when condition is TRUE
- [ ] Trace what happens when condition is FALSE
- [ ] Identify conditional deadlocks (only happen under specific conditions)

### Phase 5: Documentation & Fix (30 min)
- [ ] Create detailed findings document
- [ ] List all CRITICAL deadlocks first
- [ ] For each deadlock:
  - [ ] Explain the deadlock scenario
  - [ ] Show the call chain
  - [ ] Suggest fix
  - [ ] Estimate severity

---

## Checklist Items to Always Check

When auditing ANY function that acquires a lock:

### The Function Itself
- [ ] Does it acquire a lock? (with or explicit?)
- [ ] Does it release the lock? (with auto-releases, explicit in all paths?)
- [ ] Are there exception paths that skip unlock?
- [ ] Is there I/O (database, API, file) in lock context?

### Functions It Calls
- [ ] What functions are called inside lock context?
- [ ] Do ANY of those acquire the same lock?
- [ ] Do they call OTHER functions that acquire the lock (chain)?
- [ ] Is the call conditional (if/for/while)?

### Call Recursion
- [ ] Could this function be called recursively?
- [ ] Could function A call function B call function A?
- [ ] Are there circular dependencies in the call graph?

### Lock Ordering
- [ ] If multiple locks exist, in what order are they acquired?
- [ ] Is this order consistent across all functions?
- [ ] Could different threads acquire locks in different orders?

### Performance Issues
- [ ] Is lock held during I/O operations?
- [ ] Are there long computations in lock context?
- [ ] Could lock hold time be reduced?

---

## Red Flags - Immediate Escalation

If you see ANY of these, investigate immediately:

- [ ] `threading.Lock()` with recursive function calls nearby
- [ ] Long-running operations (database queries, API calls) in `with lock:` block
- [ ] Multiple locks acquired without consistent ordering
- [ ] Function calls within lock context without checking their definitions
- [ ] Comments like "TODO: check if this acquires the lock"
- [ ] Complex control flow (many if/for/while) inside lock contexts
- [ ] Lock acquisition inside exception handlers
- [ ] Locks acquired in one thread released in another (shouldn't happen)

---

## Automated Checks (For CI/CD Integration)

### Static Analysis: Check Lock Type
```python
# Flag all non-RLock lock acquisitions
if "threading.Lock()" in code:
    alert("Non-recursive lock in multithreaded context")
```

### Static Analysis: Find Nested Acquisitions
```python
# For each "with self.*lock:" statement
# Search downstream function definitions for same lock
# If found, flag as potential deadlock
```

### Runtime Check: Deadlock Detection
```python
# Add timeout to all lock acquisitions
with timeout(5):  # 5-second timeout
    with self.lock:
        # If this hangs > 5 seconds, deadlock detected
        pass
```

### Load Testing: Concurrent Execution
```python
# Run with ThreadPoolExecutor(max_workers=N)
# Submit 100+ tasks that would trigger deadlock
# If any timeout or hang, deadlock confirmed
```

---

## Tools to Use

### Search Tools
```
grep_search:     Find lock patterns in code
vscode_listCodeUsages: Find where functions are called
semantic_search: Find lock-related code semantically
```

### Analysis Tools
```
Python static analyzer: Check for obvious recursive calls
Call graph tool:        Visualize function dependencies
Lock profiler:          Measure lock hold times
Deadlock detector:      Runtime detection with timeouts
```

### Testing Tools
```
concurrent.futures.ThreadPoolExecutor: Multi-threaded testing
unittest.TestCase: Write tests that trigger deadlock scenarios
timeout decorator: Detect hangs in tests
```

---

## Findings Template

For each deadlock found, use this template:

```
DEADLOCK #[N]
├─ Title: [Descriptive name]
├─ Severity: CRITICAL | HIGH | MEDIUM | LOW
├─ Location: [File:Lines]
├─ Lock Type: threading.Lock() | RLock()
├─ Trigger Conditions:
│  ├─ Condition 1: [What must be true]
│  ├─ Condition 2: [What must be true]
│  └─ Example: [Real-world scenario]
├─ Call Chain:
│  ├─ function_A() at line XXX
│  │  └─ acquires lock
│  │  └─ calls function_B()
│  │     └─ function_B() acquires SAME lock ← RECURSIVE
│  └─ Result: Deadlock
├─ Impact: [What happens - thread hangs, queue overflows, etc]
├─ Status: 
│  ├─ With Lock(): 🔴 DEADLOCK
│  └─ With RLock(): ✅ SAFE
└─ Fix: [Recommended solution]
```

---

## Quick Fix Patterns

### Pattern 1: Simple Recursive Acquisition
**Problem**:
```python
with self.lock:
    self.inner_function()  # Also acquires lock
```

**Solution**: Use RLock instead
```python
self.lock = threading.RLock()  # Change this line
```

### Pattern 2: I/O Under Lock
**Problem**:
```python
with self.lock:
    db_result = db.query()  # Blocks while holding lock
    self.state = db_result
```

**Solution**: Move I/O outside lock
```python
db_result = db.query()  # Before lock
with self.lock:
    self.state = db_result  # Atomic update
```

### Pattern 3: Function Calls Within Lock
**Problem**:
```python
with self.lock:
    self.helper_function()  # Helper also acquires lock
```

**Solution**: Create unlocked version
```python
def helper_function(self):
    with self.lock:
        self._helper_function_unlocked()

def _helper_function_unlocked(self):
    # No lock, caller must hold it
    # Implementation here
```

Then call appropriately:
```python
with self.lock:
    self._helper_function_unlocked()  # Already have lock
```

---

## Success Criteria

Audit is complete when:

- [x] All lock definitions identified and documented
- [x] All lock acquisitions found and mapped
- [x] All lock-acquiring functions traced to depth of 3+ levels
- [x] All conditional code paths analyzed
- [x] All deadlocks documented with severity and call chain
- [x] All race conditions (I/O under lock) identified
- [x] Fixes applied and tested
- [x] Load tests pass without hangs/timeouts
- [x] Code review checklist updated

---

## References

- [Deadlock Detection Skill](/.github/skills/deadlock-detection/SKILL.md) - Full methodology
- [Deadlock Findings](genai_data/DEADLOCK_FINDINGS.md) - Specific deadlocks in this codebase
- [Audit Guide](genai_data/DEADLOCK_DETECTION_AUDIT_GUIDE.md) - Step-by-step instructions
- [Executive Summary](../docs/archive/v2/DEADLOCK_EXECUTIVE_SUMMARY.md) - High-level overview
