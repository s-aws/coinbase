# OrderBook Refactor Roadmap

**Goal:** Eliminate the class-level mutable defaults in `configuration.py::OrderBook` (every `OrderBook()` instance currently shares the same dicts) and give consumers an encapsulated API instead of reaching into raw dicts.

**Constraint:** Engine runs in pseudo-production with real money. **No phase may break the running system.** Pattern: Fowler's *parallel change* / Feathers' *branch by abstraction* / strangler fig.

**Started:** 2026-04-27. **Status tracker:** see "Phase status" table at the bottom.

---

## Hard Rules (apply to every phase)

1. `pytest tests/regression/ -v` must be green before and after every phase.
2. Old `OrderBook` keeps working until Phase 4. No consumer changes outside the active phase's scope.
3. No phase introduces a behavior change. Refactor and behavior change never share a commit.
4. Subagents may NOT extend the new API ad-hoc — if a method is missing, they STOP and report.

---

## Phase 0 — Inventory + Target API design

**Owner:** subagent for inventory; **you** for target API design.
**Risk:** none (read-only).
**Output:** `genai_tools/orderbook_inventory.json` + a target-API draft appended to this doc.

### 0a. Inventory subagent prompt

```
Task: Build a complete inventory of every read or write to OrderBook
attributes across the workspace.

Scope: every .py file under e:\coinbase (production code AND tests).

OrderBook attributes to track:
  order, parent_order_ids, child_order_ids, cancelled, filled,
  price, active, positions, product, mandatory_fee_per_contract,
  profit, should_replace, transaction_summary, db_client,
  default_max_order_replacement

For each access, record:
  - file (workspace-relative path)
  - line number
  - attribute name
  - operation: read | write | mutate (e.g. .pop, .update, [k] = v, del)
  - 1-line surrounding context

Do not modify any files. Do not propose API designs.

Output to: genai_tools/orderbook_inventory.json with shape:
{
  "by_attribute": {
    "order": [
      {"file": "...", "line": 123, "op": "write", "context": "..."},
      ...
    ],
    ...
  },
  "by_module": {
    "core/order_engine.py": [...],
    ...
  },
  "summary": {
    "total_sites": N,
    "by_attribute_count": {...},
    "by_module_count": {...}
  }
}
```

### 0b. Target API design (you)

After reviewing the inventory, draft the new `OrderBook` public surface in this doc. Likely shape (refine after seeing inventory):

```python
class OrderBook:
    def __init__(self): ...                       # instance-scoped state

    # --- live order state ---
    def upsert(self, coid: str, data: dict) -> None
    def evict(self, coid: str) -> dict | None
    def get(self, coid: str) -> dict | None
    def snapshot_open(self) -> dict[str, dict]    # status in {OPEN, UPDATE}
    def snapshot_all(self) -> dict[str, dict]     # for diagnostics only
    def __contains__(self, coid: str) -> bool

    # --- parent/child ---
    def register_parent(self, coid: str, meta: dict) -> None
    def register_child(self, child_coid: str, parent_coid: str) -> None
    def is_parent(self, coid: str) -> bool
    def is_child(self, coid: str) -> bool
    def get_parent_of(self, child_coid: str) -> str | None

    # --- positions / market ---
    def get_position(self, product_id: str) -> dict | None
    def get_position_side(self, product_id: str) -> str | None
    def update_price(self, product_id: str, price: float) -> None
    def get_price(self, product_id: str) -> float | None

    # --- product metadata (read-only after init) ---
    @property
    def products(self) -> Mapping[str, dict]
    @property
    def transaction_summary(self) -> Mapping[str, Any]

    # --- raw access escape hatch (DEPRECATED, removed in Phase 4) ---
    @property
    def order(self) -> dict[str, dict]   # WARN on access in Phase 2 shim
```

**Lock policy:** the new class owns its own `RLock`. All mutating methods acquire internally. `snapshot_*` methods return deep copies under the lock.

---

## Phase 1 — Build new alongside old

**Owner:** two subagents in parallel (independent files).
**Risk:** none (only new files).

### 1a. Subagent A — implement new OrderBook

```
Task: Create core/orderbook.py implementing the OrderBook class per the
target API in genai_tools/ORDERBOOK_REFACTOR_ROADMAP.md (Phase 0b).

Constraints:
- Read /memories/repo/00-README.md and 08-critical-patterns.md first.
- Implement EXACTLY the API in Phase 0b. No extras.
- All mutable state in __init__, never at class scope.
- All mutating methods acquire self._lock (RLock).
- snapshot_* methods return deep copies under the lock.
- Migrate get_position_side() and calculate_new_order_move() verbatim
  from configuration.py::OrderBook (keep behavior bit-identical).
- Type hints required on every public method.

Do not modify configuration.py or any consumer.
Do not import from anywhere except core/, calculation/, and stdlib.
```

### 1b. Subagent B — unit tests for new class

```
Task: Create tests/unit/test_orderbook_v2.py with comprehensive unit
tests for core/orderbook.py.

Coverage required:
- Two OrderBook() instances do NOT share state (the bug we are fixing)
- Concurrent upsert/evict from 4 threads stays consistent
- snapshot_open() returns only OPEN/UPDATE-status entries
- snapshot_open() returns a deep copy (mutating it does not affect state)
- evict() of nonexistent coid is a no-op
- register_child / get_parent_of round-trip correctness
- get_position_side returns None for closed positions (contracts <= 1e-8)
  - parametrize: SPOT product, FUTURE long, FUTURE short, FUTURE closed

Do not modify core/orderbook.py. If a test reveals a bug, STOP and report.
```

**Verification:** `pytest tests/unit/test_orderbook_v2.py -v` green. Regression suite still green.

---

## Phase 2 — Compatibility shim (you, single PR)

**Owner:** YOU. Do not delegate.
**Risk:** medium — this is the load-bearing step. Lock semantics, dict identity, and mutation timing must be preserved exactly.

Modify `configuration.py::OrderBook`:
1. Make it a thin wrapper that holds an inner `core.orderbook.OrderBook` instance.
2. Expose every old attribute (`order`, `parent_order_ids`, etc.) as a `@property` returning the inner state's underlying dict (NOT a copy — consumers mutate it directly today).
3. Wrap legacy methods (`get_position_side`, `calculate_new_order_move`) to delegate.
4. Optional: emit `DeprecationWarning` on raw-attribute access, gated behind env var `ORDERBOOK_DEPRECATION_WARNINGS=1`. Default OFF (no log spam in production).

**Acceptance:** full `pytest tests/` green with **zero** changes outside `configuration.py` and the new files from Phase 1.

**Why you, not an agent:** dict-identity preservation is subtle. `orderbook.order` today is a real dict that consumers mutate in-place; the property must expose that same identity, not return a copy. One mistake here corrupts every later phase.

---

## Phase 3 — Consumer migration (subagent fan-out, module-scoped)

**Owner:** one subagent per module, runnable in parallel batches of 3-4.
**Risk:** low — shim from Phase 2 means old + new coexist. A failed subagent leaves the module untouched.

### Module groupings (refine after Phase 0 inventory)

Likely batches (subject to inventory results):

**Batch 1 — high-traffic core**
- `core/order_engine.py` (~25 sites)
- `business/move_manager.py`
- `calculation/profit_validator.py`

**Batch 2 — supporting business logic**
- `business/order_processor.py`
- `business/event_processor.py`
- `business/order_calculator.py`

**Batch 3 — bridges + CLI**
- `bridges/*.py` (any that touch orderbook)
- `cli_parent_child_orders.py`
- `dashboard_server.py`

**Batch 4 — tests**
- All tests using `Mock(spec=OrderBook)` + `orderbook.order = {}`
- Migrate to real new-style instances or typed test doubles.

### Subagent prompt template (Phase 3)

```
Task: Migrate <module path> to use the new OrderBook API
(core/orderbook.py).

Constraints (non-negotiable):
- Read /memories/repo/00-README.md, 08-critical-patterns.md, and
  genai_tools/ORDERBOOK_REFACTOR_ROADMAP.md (Phase 0b API spec) first.
- Read core/orderbook.py — that is the source of truth for the API.
- Do not modify any file outside <module path>.
- Do not extend the OrderBook API. If you need a method that does not
  exist, STOP and append a question to genai_tools/ORDERBOOK_REFACTOR_ROADMAP.md
  under "API gaps discovered in Phase 3" — do NOT add to core/orderbook.py.
- After every meaningful edit, run:
  & C:\Users\heisg\AppData\Local\Programs\Python\Python313\python.exe -m pytest <test paths> -x --tb=short
- Do not mark complete unless all tests pass.

Target API: see Phase 0b in the roadmap doc.

Direct-access sites to migrate in this module:
<paste rows from genai_tools/orderbook_inventory.json filtered to this module>

Report format:
- Sites migrated: <count> / <expected>
- Tests run: <command + pass/fail>
- API gaps reported: <list or "none">
- Files modified: <list>
```

**Anti-pattern:** do NOT spawn a subagent per *attribute* (e.g. "migrate every `.order` access"). Cuts across modules → merge conflicts. Module-scoped fan-out is collision-free.

---

## Phase 4 — Convergence + retire shim (you)

**Owner:** YOU.
**Risk:** low (everything already migrated; this is the cleanup).

1. `grep_search` for any remaining direct attribute access patterns:
   - `orderbook\.order\[`
   - `orderbook\.parent_order_ids\[`
   - `orderbook\.child_order_ids\[`
   - etc.
2. If clean: remove the compatibility shim from `configuration.py`. Replace `class OrderBook(...)` with `from core.orderbook import OrderBook`. `ORDERBOOK = OrderBook()` now points at the new class directly.
3. Remove `Mock(spec=OrderBook)` patterns from tests if any remain (they should all be migrated in Phase 3 Batch 4).
4. Full `pytest tests/` green.
5. Update `/memories/repo/08-critical-patterns.md` — remove the "Design Smell — OrderBook" entry, replace with one line: "OrderBook refactored 2026-XX-XX, instance-scoped, see core/orderbook.py."
6. Delete this roadmap doc (or move to `genai_tools/output/` as a historical record).

---

## Phase status

| Phase | Owner | Status | Notes |
|-------|-------|--------|-------|
| 0a — Inventory | subagent | not started | |
| 0b — Target API | you | not started | needs 0a output |
| 1a — Implement new class | subagent A | not started | |
| 1b — Unit tests | subagent B | not started | parallel with 1a |
| 2  — Compatibility shim | YOU | not started | DO NOT DELEGATE |
| 3 batch 1 — core | subagents | not started | |
| 3 batch 2 — business | subagents | not started | |
| 3 batch 3 — bridges/CLI | subagents | not started | |
| 3 batch 4 — tests | subagent | not started | |
| 4 — Convergence | YOU | not started | |

---

## API gaps discovered in Phase 3

(Empty — populated by subagents during Phase 3 if they find missing methods.)

---

## Decision log

(Empty — record any deviations from the plan here, with rationale.)
