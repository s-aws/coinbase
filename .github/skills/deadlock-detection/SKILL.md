---
name: deadlock-detection
description: "Detect potential deadlocks caused by recursive lock acquisition, lock ordering violations, and nested lock contexts. Use when: analyzing threading issues, finding deadlock bugs, auditing lock safety, or preventing race conditions in multithreaded code."
---

# Deadlock Detection Workflow

Inspect the current checkout and resolve current symbols before drawing a
conclusion. Root `AGENTS.md` and `agent.md` control validation: run the complete
local non-external suite; focused selections require an explicit user request.

## Catalog locks

Use `rg` to find lock definitions and acquisition points:

```bash
rg -n 'threading\.(Lock|RLock|Semaphore|Condition)\(' --glob '*.py'
rg -n '\.acquire\(|\.release\(|with .*lock' --glob '*.py'
```

For each lock, record its owner, type, protected state, and acquisition and
release sites. Follow aliases and shared instances; similar names do not prove
two callers use the same lock.

- A `Lock` blocks recursive acquisition by its owning thread.
- An `RLock` permits recursion by that thread but can still participate in
  deadlocks involving other locks or threads.
- Conditions and semaphores need their own wait, notification, and release
  analysis.

## Trace calls while locked

Read every function that acquires the target lock. Trace all calls executed
before release, including callbacks and conditional, loop, exception, and
early-return paths. Resolve the implementation at each call; static graph
edges are navigation candidates rather than proof of runtime dispatch.

Record whether each downstream call acquires the same lock, acquires another
lock, performs I/O, waits for a worker, or can call back into the owner. A call
that acquires a lock after an earlier context has released it is not recursive
acquisition.

For multiple locks, compare their acquisition order across threads. Identify
a concrete wait cycle before reporting a confirmed deadlock. A long lock hold
or database call alone establishes contention risk, not a deadlock.

## Check release and wait behavior

Confirm explicit acquisitions release on every path, including exceptions.
Context managers handle release on exit, but do not prove the enclosed work
is safe. Check whether joins, futures, queue operations, condition waits, or
callbacks need a lock currently held by their caller.

Keep database and exchange I/O outside locks where the current ownership and
consistency contract permits it. Moving work outside a lock requires reviewing
state races and commit boundaries; never bypass an established lock to silence
an audit finding.

## Record evidence and validate

For each finding, record current symbols and lines, the lock identity, the
thread or callback path, the wait cycle or contention mechanism, impact, and
reproduction conditions. Distinguish confirmed defects from unresolved paths.

Choose a correction that preserves the existing single behavior path and
ownership contract. Reentrancy, consistent lock order, shorter critical
sections, or callbacks outside locks may help, depending on the actual cause.
Do not introduce parallel implementations as a locking workaround.

Run the repository's complete local gate after a change:

```powershell
.\.venv\Scripts\python.exe -m pytest -c tests/pytest.ini tests -m "not external" -v --tb=short
```

Passing tests support the exercised paths; they do not prove deadlock freedom.
Update affected current documentation and graph evidence with the reviewed
ownership and lock contracts.
