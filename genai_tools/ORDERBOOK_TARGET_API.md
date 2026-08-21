# OrderBook v2 — Target API Spec

**Status:** Draft for Phase 0b review
**Source of truth for:** Phase 1a (implementation), Phase 1b (tests), Phase 2 (compat shim)
**Inventory basis:** [orderbook_inventory.json](orderbook_inventory.json)

---

## 1. Design principles

1. **Instance-scoped state** — no class-level mutable defaults. Every dict/list initialized in `__init__`.
2. **Single lock, RLock** — `self._lock` guards all mutable state. Re-entrant so composed ops can layer.
3. **No live-collection leakage** — read methods return `MappingProxyType` views or deepcopy snapshots, never the live dict. Eliminates "iterating while another thread mutates" bugs by construction.
4. **Typed entries over magic strings** — `ParentOrderEntry` dataclass replaces `dict[str, Any]` with `["orders"]`, `["current_order_replacement"]`, etc.
5. **Atomic compound ops** — operations that touch >1 map (e.g. reconciler rebuild) expose a single method, not two writes.
6. **Constructor injection** — no runtime attribute grafting. `db_helper` is a constructor arg.
7. **Backward-compatible shape** — existing dicts (`order`, `parent_order_ids`, `child_order_ids`, `positions`) keep their on-disk/in-memory shape so the Phase 2 shim can wrap without translating.
8. **Kill dead state** — drop attributes with zero consumers.

## 2. Kill list (removed in v2)

| Attribute | Reason |
|---|---|
| `cancelled` | 0 production reads, 0 production writes |
| `filled` | 0 production reads, 0 production writes |
| `active` | 0 production reads, 0 production writes |
| `transaction_summary` | 0 production reads (computed once, never used) |
| `db_client` | 0 production reads; only set to None at class level. `db_helper` is the actual attr (grafted at runtime) |
| `calculate_new_order_move` (bound method) | **Confirmed dead**. Zero external callers. The free function `calculate_new_order_move_from_snapshot` it wraps IS used and stays. |
| `default_max_order_replacement` (instance attr) | **Confirmed dead**. Only set in test fixtures. Production reads module constant `DEFAULT_MAX_ORDER_REPLACEMENT` directly. |

## 3. Constructor

```python
class OrderBook:
    def __init__(
        self,
        *,
        products: Mapping[str, dict] | None = None,
        profit: Mapping[str, dict] | None = None,
        mandatory_fee_per_contract: Mapping[str, dict] | None = None,
        should_replace: Mapping[str, bool] | None = None,
        db_helper: "DBHelper | None" = None,
    ) -> None:
        self._lock = threading.RLock()

        # Read-only references (immutable views from caller's POV)
        self._products = dict(products or {})
        self._profit = dict(profit or {})
        self._mandatory_fee_per_contract = dict(mandatory_fee_per_contract or {})
        self._should_replace = dict(should_replace or {"FILLED": True, "CANCELLED": True})
        self._db_helper = db_helper

        # Mutable state — instance-scoped (NOT class-level)
        self._orders: dict[str, dict] = {}                 # was .order
        self._parents: dict[str, ParentOrderEntry] = {}    # was .parent_order_ids
        self._child_to_parent: dict[str, str] = {}         # was .child_order_ids
        self._positions: dict[str, dict[str, dict]] = {"FUTURE": {}}  # was .positions
```

## 4. ParentOrderEntry dataclass

```python
@dataclass
class ParentOrderEntry:
    parent_id: int | None = None
    product_id: str = ""
    side: str = ""
    target_movement: dict = field(default_factory=lambda: {"movement": 0.0, "type": "P"})
    max_order_replacement: int = 0
    current_order_replacement: int = 0
    orders: list[str] = field(default_factory=list)        # child client_order_ids
    # ... any other fields currently stored as dict keys

    def as_dict(self) -> dict:
        """Compat layer: return the legacy dict shape used by JSON dumps + tests."""
        return asdict(self)
```

The shim (Phase 2) will let consumers continue accessing `parent_order_ids[coid]["orders"]` by storing dict-shaped values OR by having the new class expose `parent_order_ids` as a `dict[str, dict]` view via `as_dict()` projection. Final decision in Phase 1a.

## 5. Public API

### 5.1 Lock — exposed for composed ops

```python
@property
def lock(self) -> threading.RLock: return self._lock
```

`OrderEngine` already composes multi-step atomic operations under `self.orderbook_lock`. Keep that pattern.

### 5.2 Live orders (`order` dict replacement)

```python
def upsert_order(self, client_order_id: str, payload: dict) -> None
def evict_order(self, client_order_id: str) -> dict | None
def get_order(self, client_order_id: str) -> dict | None
def has_order(self, client_order_id: str) -> bool
def order_keys(self) -> list[str]            # snapshot, not view
def snapshot_orders(self) -> dict[str, dict] # deepcopy
def snapshot_open_orders(self) -> dict[str, dict]
    # NEW — returns only entries whose status ∈ {OPEN, UPDATE}.
    # Eliminates the v2 drift-checker filter we just added in snapshot_drift_check.
```

### 5.3 Parent/child links

```python
def register_parent(self, client_order_id: str, entry: ParentOrderEntry) -> None
def get_parent(self, client_order_id: str) -> ParentOrderEntry | None
def is_parent(self, client_order_id: str) -> bool
def is_child(self, client_order_id: str) -> bool
def get_parent_of(self, child_client_order_id: str) -> str | None
def add_child(self, parent_client_order_id: str, child_client_order_id: str) -> bool
    # Returns True if newly added, False if already present.
    # Increments current_order_replacement on success.
def parents_snapshot(self) -> dict[str, dict]   # legacy dict shape via as_dict()
def children_snapshot(self) -> dict[str, str]   # deepcopy
def atomic_replace_links(
    self,
    new_parents: dict[str, ParentOrderEntry] | dict[str, dict],
    new_children: dict[str, str],
) -> None
    # Single-lock swap. Fixes core/order_engine.py:3465-3466 TOCTOU.
```

### 5.4 Positions

```python
def get_future_positions(self) -> dict[str, dict]
    # Returns MappingProxyType view; OK for reads, raises on mutation.
def upsert_future_position(self, product_id: str, position: dict) -> None
def get_future_position(self, product_id: str) -> dict | None
def apply_position_update(self, update) -> None
    # Wraps the existing apply_calculated_position_update helper.
def iter_future_positions(self) -> Iterator[tuple[str, dict]]
def snapshot_positions(self) -> dict[str, dict[str, dict]]  # deepcopy
def get_position_side(self, product_id: str) -> str | None  # PRESERVED (existing semantics)
```

### 5.5 Static reference data (read-only)

```python
@property
def products(self) -> Mapping[str, dict]: return MappingProxyType(self._products)
@property
def profit(self) -> Mapping[str, dict]: return MappingProxyType(self._profit)
@property
def mandatory_fee_per_contract(self) -> Mapping[str, dict]: return MappingProxyType(self._mandatory_fee_per_contract)
@property
def should_replace(self) -> Mapping[str, bool]: return MappingProxyType(self._should_replace)
@property
def db_helper(self) -> "DBHelper | None": return self._db_helper
```

Setters (`set_products`, `set_profit`, etc.) provided for startup loaders but each holds the lock and replaces the underlying dict atomically.

### 5.6 Diagnostic snapshot

```python
def diagnostic_snapshot(self) -> dict
    # Replaces the deepcopy block at core/order_engine.py:1245-1251.
    # Single lock acquisition; returns the same shape OrderEngine builds today.
```

## 6. Mapping: legacy attribute → new method

| Legacy access | New method |
|---|---|
| `ob.order[coid] = x` | `ob.upsert_order(coid, x)` |
| `ob.order.pop(coid, None)` | `ob.evict_order(coid)` |
| `ob.order.get(coid)` | `ob.get_order(coid)` |
| `coid in ob.order` | `ob.has_order(coid)` |
| `ob.order.keys()` | `ob.order_keys()` |
| `deepcopy(ob.order)` | `ob.snapshot_orders()` |
| `ob.parent_order_ids[coid] = {...}` | `ob.register_parent(coid, ParentOrderEntry(**...))` |
| `ob.parent_order_ids[coid]["orders"].append(c)` | `ob.add_child(coid, c)` |
| `ob.parent_order_ids[coid]["current_order_replacement"] += 1` | (handled by `add_child`) |
| `ob.parent_order_ids.get(coid, {})` | `ob.get_parent(coid)` (returns entry or None) |
| `coid in ob.parent_order_ids` | `ob.is_parent(coid)` |
| `coid in ob.child_order_ids` | `ob.is_child(coid)` |
| `ob.child_order_ids.get(c)` | `ob.get_parent_of(c)` |
| `ob.child_order_ids[c] = p` | `ob.add_child(p, c)` |
| `ob.parent_order_ids = X; ob.child_order_ids = Y` | `ob.atomic_replace_links(X, Y)` |
| `ob.positions["FUTURE"][pid] = {...}` | `ob.upsert_future_position(pid, ...)` |
| `ob.positions["FUTURE"][pid]` | `ob.get_future_position(pid)` |
| `ob.positions["FUTURE"].setdefault("FUTURE", {})` (sic, see line 1267) | `ob.get_future_positions()` (always present) |
| `ob.positions["FUTURE"] = refreshed` | iterate + `upsert_future_position` (or new `replace_future_positions(dict)`) |
| `apply_calculated_position_update(ob.positions, u)` | `ob.apply_position_update(u)` |
| `ob.product` (read) | `ob.products` |
| `ob.product.get(pid, {})` | `ob.products.get(pid, {})` |
| `ob.profit` / `.profit.get(...)` | `ob.profit` (MappingProxy) |
| `ob.should_replace["CANCELLED"]` | `ob.should_replace["CANCELLED"]` (unchanged shape) |
| `ob.mandatory_fee_per_contract` | `ob.mandatory_fee_per_contract` |
| `ob.get_position_side(pid)` | unchanged |
| `ob.db_helper = X` (graft) | constructor arg or `set_db_helper(X)` |

## 7. Phase 2 compat shim contract

`configuration.py` will keep exporting `OrderBook` (the legacy dict-attribute class) and `ORDERBOOK` (singleton) until Phase 4. The shim:

- Wraps a `core.orderbook.OrderBook` instance.
- Exposes `.order`, `.parent_order_ids`, `.child_order_ids`, `.positions` as `property` getters returning the new class's underlying dicts (NOT copies — to preserve the contract that `ob.order[coid] = x` mutates state).
- Setters (`ob.order = {}` in tests) re-initialize the underlying dict atomically.
- Static refs (`.product`, `.profit`, etc.) proxy through.
- `.get_position_side` proxies through.
- `.db_helper` setter proxies to `set_db_helper`.

This means **zero changes to consumers in Phase 2** — they keep using legacy attribute access — and we still get the new class running in production for validation. Phase 3 migrates consumers one batch at a time.

## 8. Open questions for Phase 1a

1. **`ParentOrderEntry` shape vs dict shape.** Two options:
   - (a) Internal storage as dataclass; expose dict shape via `parents_snapshot()` only. Cleaner but the shim's `parent_order_ids` property must return live dicts.
   - (b) Internal storage as dict; `register_parent` accepts dataclass and converts via `asdict()`. Simpler shim, weaker typing.
   - **Recommendation: (b) for v2.** Keeps shim trivial, lets us tighten typing in v3 once consumers are migrated.

2. **`positions` shape.** Currently `{"FUTURE": {pid: {...}}}` with only the `"FUTURE"` key in use. Keep nested wrapper for shim compat; add helper that returns the inner dict directly.

3. **Lock acquisition contract for nested mutations.** A consumer doing:
   ```python
   with engine.orderbook_lock:
       parent = ob.get_parent(coid)
       parent.orders.append(child_id)  # mutates entry under lock
   ```
   This works only if `get_parent` returns the *live* entry, not a copy. Recommended contract: **`get_parent` returns the live entry; mutations require the caller hold `ob.lock` (which `engine.orderbook_lock` IS in v2 — they're the same RLock).** Document explicitly. Snapshot methods (`parents_snapshot`) return deepcopies.

## 9. Acceptance criteria for Phase 1a

- `core/orderbook.py` exists; defines `OrderBook` and `ParentOrderEntry`.
- All methods in §5 implemented with docstrings stating thread-safety contract.
- No class-level mutable defaults.
- `from core.orderbook import OrderBook` succeeds with no import-time side effects (no DB calls, no REST).
- 100% method coverage from Phase 1b tests.
- `pytest tests/regression/ -v` still passes (it doesn't touch the new file yet — sanity check that nothing broke in import order).

## 10. Acceptance criteria for Phase 2 (shim)

- `configuration.OrderBook` and `configuration.ORDERBOOK` keep working byte-for-byte from consumer POV.
- `pytest tests/ -v` passes with no test changes.
- Optional `ORDERBOOK_DEPRECATION_WARNINGS=1` env var emits `DeprecationWarning` per legacy attribute access — off by default to avoid prod log noise.
