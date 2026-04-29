"""Instance-scoped, thread-safe order book.

This is the v2 replacement for ``configuration.OrderBook``.  See
``genai_tools/ORDERBOOK_TARGET_API.md`` for the design spec and the rationale
for every method on this class.

Migration is staged:

* Phase 1 (this file): new class lives alongside the legacy one. Nothing imports it yet.
* Phase 2: ``configuration.OrderBook`` becomes a compatibility shim that
  delegates to an instance of this class.
* Phase 3: consumers migrate from legacy attribute access to the methods below.
* Phase 4: shim retired.

Thread-safety contract
----------------------
Every mutating method takes ``self._lock`` (an :class:`threading.RLock`).  The
lock is exposed as :attr:`lock` so callers that compose multi-step atomic
operations (e.g. ``OrderEngine``) can hold it across several method calls.
Read methods that return collections return either deepcopy snapshots or
``MappingProxyType`` views — never the live underlying dict — so iterating a
returned object is always safe even if another thread mutates the orderbook
concurrently.

Two intentional escape hatches that DO return live dicts:

* :meth:`get_parent` returns the live parent dict (callers must hold
  :attr:`lock` to mutate its contents).
* :meth:`get_future_position` returns the live position dict (same rule).

Both are documented at the call site.

Internal storage shape
----------------------
Parent order entries are stored as plain dicts (``dict[str, dict]``) rather
than as :class:`ParentOrderEntry` dataclass instances.  This keeps the Phase 2
compatibility shim trivial and matches the legacy on-disk shape.
:class:`ParentOrderEntry` is provided as an ergonomic constructor: callers can
build a typed entry, then pass it to :meth:`register_parent`, which stores
``entry.as_dict()``.  Phase 3+ may tighten typing once consumers migrate.
"""

from __future__ import annotations

import threading
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Iterator, Mapping

from core.enums import OrderStatus

if TYPE_CHECKING:  # pragma: no cover - typing-only
    from data.db_helper import DBHelper


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ParentOrderEntry:
    """Typed container for a parent order's bookkeeping state.

    Replaces the ad-hoc ``dict[str, Any]`` shape used by the legacy
    ``parent_order_ids[client_order_id]`` value.  All fields keep their legacy
    names so :meth:`as_dict` is a drop-in for code that still expects a dict.
    """

    product_id: str = ""
    side: str = ""
    parent_id: int | None = None
    target_movement: dict = field(
        default_factory=lambda: {"movement": 0.0, "type": "P"}
    )
    max_order_replacement: int = 0
    current_order_replacement: int = 0
    orders: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return the legacy dict shape used by JSON dumps and existing tests."""

        d = asdict(self)
        # Flatten ``extra`` to preserve any caller-provided keys at the top
        # level, matching the legacy behaviour where callers set arbitrary keys
        # directly on parent_order_ids[coid].
        extra = d.pop("extra", {}) or {}
        d.update(extra)
        return d

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ParentOrderEntry":
        """Construct from a legacy-shaped dict, preserving unknown keys in ``extra``."""

        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        kwargs: dict[str, Any] = {}
        extra: dict[str, Any] = {}
        for k, v in payload.items():
            if k in known and k != "extra":
                kwargs[k] = v
            else:
                extra[k] = v
        if extra:
            kwargs["extra"] = extra
        return cls(**kwargs)


# ---------------------------------------------------------------------------
# OrderBook
# ---------------------------------------------------------------------------


_OPEN_STATUSES: frozenset[str] = frozenset(
    {OrderStatus.OPEN.value, OrderStatus.UPDATE.value}
)


class OrderBookReadOnlyError(RuntimeError):
    """Raised when a mutator is called on a read-only :class:`OrderBook`.

    Constructed via :class:`OrderBook` with ``read_only=True`` (typically for
    a side-by-side validation instance running against a duplicate database
    where any state change would be unintended).
    """


class ClaimLedger:
    """Generic three-state per-key claim ledger.

    Reusable kernel of the follow-up processing claim mechanism. Each
    ``(kind, key)`` slot is in one of three states:

    - **absent**  — ``try_claim`` will succeed.
    - **processing** — owned by some thread; further claims fail until
      :meth:`release` (failure path) or :meth:`complete` (terminal).
    - **done** — terminal; further claims fail forever.

    The ``kind`` argument to every method is validated at the boundary
    against a caller-supplied :class:`enum.Enum` subclass, so a typo on
    the kind cannot silently allocate a fresh namespace.

    The ledger is **process-local bookkeeping** and not persisted; the
    underlying lock is a private :class:`threading.RLock`. Callers that
    must serialise the ledger against external state (e.g. order writes)
    should hold that external lock around the ``try_claim`` / mutation /
    ``release`` sequence.

    Two production usages exist (see :class:`core.enums.FollowUpKind` and
    :class:`core.enums.StealthMutationKind`):

    - :class:`OrderBook` owns one keyed on :class:`FollowUpKind` to
      serialise FILLED / CANCELLED follow-up creation.
    - :class:`core.stealth_order_manager.StealthOrderManager` owns one
      keyed on :class:`StealthMutationKind` to serialise REVEALED-order
      moves against the ticker-driven anchor reprice loop.

    Stealth mutations are repeatable, so callers there must use
    :meth:`release` in both success and failure paths and never call
    :meth:`complete`.
    """

    def __init__(self, kind_enum: type) -> None:
        from enum import Enum

        if not (isinstance(kind_enum, type) and issubclass(kind_enum, Enum)):
            raise TypeError(
                f"kind_enum must be an Enum subclass, got {kind_enum!r}"
            )
        self._kind_enum = kind_enum
        self._lock = threading.RLock()
        self._slots: dict[str, dict[str, str]] = {}

    def _coerce_kind(self, kind) -> str:
        if isinstance(kind, self._kind_enum):
            return kind.value
        if isinstance(kind, str):
            try:
                return self._kind_enum(kind).value
            except ValueError as exc:
                raise ValueError(
                    f"Unknown {self._kind_enum.__name__}: {kind!r}; "
                    f"expected one of {[k.value for k in self._kind_enum]}"
                ) from exc
        raise TypeError(
            f"kind must be {self._kind_enum.__name__} or str, "
            f"got {type(kind).__name__}"
        )

    def try_claim(self, kind, key: str) -> bool:
        """Atomically claim ``(kind, key)``.

        Returns ``True`` if the caller now owns the claim and must finish
        it with :meth:`release` (failure / repeatable) or :meth:`complete`
        (terminal). Returns ``False`` if the slot is already ``processing``
        or ``done``.
        """

        kind_key = self._coerce_kind(kind)
        with self._lock:
            ledger = self._slots.setdefault(kind_key, {})
            current = ledger.get(key)
            if current in {"processing", "done"}:
                return False
            ledger[key] = "processing"
            return True

    def release(self, kind, key: str) -> None:
        """Release a ``processing`` claim so it may be retried.

        No-op if the entry is absent or in any state other than
        ``processing`` — completed claims must stay completed.
        """

        kind_key = self._coerce_kind(kind)
        with self._lock:
            ledger = self._slots.get(kind_key)
            if ledger is None:
                return
            if ledger.get(key) == "processing":
                ledger.pop(key, None)

    def complete(self, kind, key: str) -> None:
        """Mark a claim as terminally ``done`` so it can never re-fire."""

        kind_key = self._coerce_kind(kind)
        with self._lock:
            ledger = self._slots.setdefault(kind_key, {})
            ledger[key] = "done"

    def state(self, kind, key: str):
        """Inspect current state — ``None``, ``"processing"`` or ``"done"``."""

        kind_key = self._coerce_kind(kind)
        with self._lock:
            ledger = self._slots.get(kind_key)
            if ledger is None:
                return None
            return ledger.get(key)


class OrderBook:
    """Instance-scoped, thread-safe order and position book.

    See module docstring for the thread-safety contract.

    Read-only mode
    --------------
    Pass ``read_only=True`` to the constructor to lock every mutator.  In that
    mode, any call that would change state (``upsert_order``, ``evict_order``,
    ``register_parent``, ``add_child``, ``atomic_replace_links``,
    ``upsert_future_position``, ``replace_future_positions``,
    ``apply_position_update``, every ``set_*``, and the legacy shim setters)
    raises :class:`OrderBookReadOnlyError`.  Reads and snapshots are
    unaffected.

    The mode is intended for shadow / validation instances pointed at a
    duplicate database where you want to confirm load + read paths without
    risking accidental writes back to the wrapped DB or to in-memory state.
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        *,
        products: Mapping[str, dict] | None = None,
        profit: Mapping[str, dict] | None = None,
        mandatory_fee_per_contract: Mapping[str, dict] | None = None,
        should_replace: Mapping[str, bool] | None = None,
        positions: Mapping[str, Mapping[str, dict]] | None = None,
        db_helper: "DBHelper | None" = None,
        read_only: bool = False,
    ) -> None:
        self._lock = threading.RLock()
        self._read_only = bool(read_only)

        # Static reference data — deep-copied so external mutation of the
        # source dict cannot leak into the orderbook (and vice versa).
        self._products: dict[str, dict] = deepcopy(dict(products or {}))
        self._profit: dict[str, dict] = deepcopy(dict(profit or {}))
        self._mandatory_fee_per_contract: dict[str, dict] = deepcopy(
            dict(mandatory_fee_per_contract or {})
        )
        self._should_replace: dict[str, bool] = dict(
            should_replace or {"FILLED": True, "CANCELLED": True}
        )
        self._db_helper = db_helper

        # Mutable runtime state — instance-scoped (NOT class-level).
        self._orders: dict[str, dict] = {}
        self._parents: dict[str, dict] = {}
        self._child_to_parent: dict[str, str] = {}
        self._positions: dict[str, dict[str, dict]] = {"FUTURE": {}}
        if positions:
            for category, by_product in positions.items():
                self._positions[category] = {
                    pid: dict(pdata) for pid, pdata in by_product.items()
                }

        # Follow-up processing claim ledger.  One namespace per
        # FollowUpKind (filled / cancelled).  Values are "processing" once
        # claimed and "done" once completed; absent keys are unclaimed.
        # Owned by OrderEngine.{try,release,complete}_follow_up_processing
        # (see those wrappers).  Backed by the generic :class:`ClaimLedger`
        # kernel so the same primitive can serve other namespaces (e.g.
        # StealthOrderManager mutation claims) without duplicating the
        # three-state state-machine and its boundary validation.
        from core.enums import FollowUpKind

        self._follow_up_ledger = ClaimLedger(FollowUpKind)

    # ------------------------------------------------------------------
    # Lock & read-only mode
    # ------------------------------------------------------------------

    @property
    def lock(self) -> threading.RLock:
        """The re-entrant lock guarding all mutable state.

        Callers composing multi-step atomic operations should ``with ob.lock:``
        and then call methods normally — the methods will re-enter the lock
        cheaply.
        """

        return self._lock

    @property
    def read_only(self) -> bool:
        """``True`` if every mutator on this orderbook will raise."""

        return self._read_only

    def _check_writable(self, op: str) -> None:
        """Raise :class:`OrderBookReadOnlyError` if ``read_only`` is set."""

        if self._read_only:
            raise OrderBookReadOnlyError(
                f"OrderBook is read-only; refusing {op}()"
            )

    # ------------------------------------------------------------------
    # Live orders
    # ------------------------------------------------------------------

    def upsert_order(self, client_order_id: str, payload: dict) -> None:
        """Insert or replace the order entry for ``client_order_id``."""

        self._check_writable("upsert_order")
        with self._lock:
            self._orders[client_order_id] = payload

    def evict_order(self, client_order_id: str) -> dict | None:
        """Remove and return the order entry, or ``None`` if absent."""

        self._check_writable("evict_order")
        with self._lock:
            return self._orders.pop(client_order_id, None)

    def get_order(self, client_order_id: str) -> dict | None:
        """Return the live order dict, or ``None`` if absent.

        The returned dict is the live underlying object; callers that mutate it
        must hold :attr:`lock`.
        """

        with self._lock:
            return self._orders.get(client_order_id)

    def has_order(self, client_order_id: str) -> bool:
        with self._lock:
            return client_order_id in self._orders

    def order_keys(self) -> list[str]:
        """Snapshot of current order ids — safe to iterate without the lock."""

        with self._lock:
            return list(self._orders.keys())

    def snapshot_orders(self) -> dict[str, dict]:
        """Deepcopy snapshot of every live order entry."""

        with self._lock:
            return deepcopy(self._orders)

    def snapshot_open_orders(self) -> dict[str, dict]:
        """Snapshot of orders whose ``status`` is OPEN or UPDATE.

        Used by drift detection: only orders the venue would also report as
        open belong in an apples-to-apples comparison with the venue's
        open-orders REST snapshot.  Centralising the filter here means callers
        cannot accidentally compare populations of different shapes.
        """

        with self._lock:
            return {
                coid: deepcopy(payload)
                for coid, payload in self._orders.items()
                if payload.get("status") in _OPEN_STATUSES
            }

    # ------------------------------------------------------------------
    # Follow-up processing claims
    # ------------------------------------------------------------------
    #
    # Backed by :class:`ClaimLedger` keyed on :class:`core.enums.FollowUpKind`.
    # The ledger validates the kind at the boundary so a typo cannot
    # silently create a fresh namespace, and serialises with its own
    # internal lock (independent of :attr:`_lock` so claim bookkeeping
    # cannot deadlock against order writes).  Read-only mode does NOT
    # block these methods because claim state is per-process bookkeeping,
    # not persistent state.

    def try_claim_follow_up(
        self, kind: "str | FollowUpKind", client_order_id: str
    ) -> bool:
        """Atomically claim follow-up processing rights.

        Returns ``True`` if the caller now owns the claim and must finish it
        with :meth:`release_follow_up` (failure) or :meth:`complete_follow_up`
        (success).  Returns ``False`` if the (kind, client_order_id) is already
        ``processing`` or ``done``.
        """

        return self._follow_up_ledger.try_claim(kind, client_order_id)

    def release_follow_up(
        self, kind: "str | FollowUpKind", client_order_id: str
    ) -> None:
        """Release a ``processing`` claim so it may be retried.

        No-op if the entry is absent or in any state other than
        ``processing`` — completed claims must stay completed.
        """

        self._follow_up_ledger.release(kind, client_order_id)

    def complete_follow_up(
        self, kind: "str | FollowUpKind", client_order_id: str
    ) -> None:
        """Mark a claim as terminally ``done`` so it can never re-fire."""

        self._follow_up_ledger.complete(kind, client_order_id)

    def follow_up_claim_state(
        self, kind: "str | FollowUpKind", client_order_id: str
    ) -> "str | None":
        """Inspect the current claim state — returns ``None``, ``"processing"`` or ``"done"``."""

        return self._follow_up_ledger.state(kind, client_order_id)

    # ------------------------------------------------------------------
    # Parent / child relationship tracking
    # ------------------------------------------------------------------

    def register_parent(
        self,
        client_order_id: str,
        entry: "ParentOrderEntry | Mapping[str, Any]",
    ) -> None:
        """Insert or replace the parent entry.

        Accepts either a :class:`ParentOrderEntry` (converted via ``as_dict``)
        or a legacy-shaped dict.  Storage is always dict shape.
        """

        self._check_writable("register_parent")
        if isinstance(entry, ParentOrderEntry):
            stored = entry.as_dict()
        else:
            stored = dict(entry)
        with self._lock:
            self._parents[client_order_id] = stored

    def get_parent(self, client_order_id: str) -> dict | None:
        """Return the live parent dict (None if absent).

        Callers mutating the returned dict must hold :attr:`lock`.
        """

        with self._lock:
            return self._parents.get(client_order_id)

    def is_parent(self, client_order_id: str) -> bool:
        with self._lock:
            return client_order_id in self._parents

    def is_child(self, client_order_id: str) -> bool:
        with self._lock:
            return client_order_id in self._child_to_parent

    def get_parent_of(self, child_client_order_id: str) -> str | None:
        with self._lock:
            return self._child_to_parent.get(child_client_order_id)

    def add_child(
        self, parent_client_order_id: str, child_client_order_id: str
    ) -> bool:
        """Link ``child`` under ``parent``.

        Returns ``True`` if the child was newly added, ``False`` if it was
        already present under that parent.  On a new add, increments the
        parent's ``current_order_replacement`` counter.

        The parent entry is created with default fields if it does not yet
        exist — matches the legacy ``setdefault``-style behaviour at
        ``core/order_engine.py:1552``.
        """

        self._check_writable("add_child")
        with self._lock:
            parent = self._parents.get(parent_client_order_id)
            if parent is None:
                parent = {"orders": [], "current_order_replacement": 0}
                self._parents[parent_client_order_id] = parent
            children = parent.setdefault("orders", [])
            if child_client_order_id in children:
                # Still record the back-link in case it was missing.
                self._child_to_parent[child_client_order_id] = parent_client_order_id
                return False
            children.append(child_client_order_id)
            parent["current_order_replacement"] = (
                parent.get("current_order_replacement", 0) + 1
            )
            self._child_to_parent[child_client_order_id] = parent_client_order_id
            return True

    def parents_snapshot(self) -> dict[str, dict]:
        """Deepcopy snapshot of every parent entry, in legacy dict shape."""

        with self._lock:
            return deepcopy(self._parents)

    def children_snapshot(self) -> dict[str, str]:
        """Deepcopy snapshot of the child→parent map."""

        with self._lock:
            return dict(self._child_to_parent)

    def atomic_replace_links(
        self,
        new_parents: "Mapping[str, ParentOrderEntry | Mapping[str, Any]]",
        new_children: Mapping[str, str],
    ) -> None:
        """Atomically replace both the parent and child maps under one lock.

        Closes the TOCTOU window present in the legacy code, where
        ``orderbook.parent_order_ids = X`` and
        ``orderbook.child_order_ids = Y`` were two separate statements.
        """

        self._check_writable("atomic_replace_links")
        normalised_parents: dict[str, dict] = {}
        for coid, entry in new_parents.items():
            if isinstance(entry, ParentOrderEntry):
                normalised_parents[coid] = entry.as_dict()
            else:
                normalised_parents[coid] = dict(entry)
        normalised_children = dict(new_children)
        with self._lock:
            self._parents = normalised_parents
            self._child_to_parent = normalised_children

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    def get_future_positions(self) -> Mapping[str, dict]:
        """Read-only view of the FUTURE positions map.

        Mutating the returned object raises ``TypeError``.  Use
        :meth:`upsert_future_position` or :meth:`apply_position_update` to
        mutate.
        """

        with self._lock:
            # MappingProxyType wraps the live dict; safe to expose because
            # MappingProxyType disallows mutation through the proxy.
            return MappingProxyType(self._positions.setdefault("FUTURE", {}))

    def get_future_position(self, product_id: str) -> dict | None:
        """Return the live FUTURE position dict for ``product_id`` (or None).

        Callers mutating the returned dict must hold :attr:`lock`.
        """

        with self._lock:
            return self._positions.get("FUTURE", {}).get(product_id)

    def upsert_future_position(self, product_id: str, position: dict) -> None:
        self._check_writable("upsert_future_position")
        with self._lock:
            self._positions.setdefault("FUTURE", {})[product_id] = position

    def replace_future_positions(self, positions: Mapping[str, dict]) -> None:
        """Atomically replace the entire FUTURE positions map."""

        self._check_writable("replace_future_positions")
        with self._lock:
            self._positions["FUTURE"] = dict(positions)

    def apply_position_update(self, position_update: dict | None) -> None:
        """Apply a position update produced by ``calculate_new_order_move_from_snapshot``.

        Wraps ``configuration.apply_calculated_position_update`` under the
        lock so callers don't need to import it separately.  Imported lazily
        to avoid an import cycle (``configuration`` constructs an OrderBook).
        """

        if not position_update:
            return
        self._check_writable("apply_position_update")
        # Late import to avoid a circular dependency with ``configuration``.
        from configuration import apply_calculated_position_update

        with self._lock:
            apply_calculated_position_update(self._positions, position_update)

    def iter_future_positions(self) -> Iterator[tuple[str, dict]]:
        """Iterate (product_id, position) over a snapshot of FUTURE positions."""

        with self._lock:
            items = list(self._positions.get("FUTURE", {}).items())
        return iter(items)

    def snapshot_positions(self) -> dict[str, dict[str, dict]]:
        """Deepcopy snapshot of the full positions structure."""

        with self._lock:
            return deepcopy(self._positions)

    def get_position_side(self, product_id: str) -> str | None:
        """Return current position side ('LONG' / 'SHORT') or ``None`` when closed.

        Preserves the exact semantics of the legacy method in
        ``configuration.OrderBook.get_position_side``: returns ``None`` when
        ``number_of_contracts`` is at or near zero so callers know the next
        order will OPEN a new position.
        """

        with self._lock:
            position = self._positions.get("FUTURE", {}).get(product_id)
            if not position:
                return None
            try:
                num_contracts = float(position.get("number_of_contracts", 0))
            except (ValueError, TypeError):
                return None
            if num_contracts <= 1e-8:
                return None
            return position.get("side")

    # ------------------------------------------------------------------
    # Static reference data
    # ------------------------------------------------------------------

    @property
    def products(self) -> Mapping[str, dict]:
        return MappingProxyType(self._products)

    @property
    def profit(self) -> Mapping[str, dict]:
        return MappingProxyType(self._profit)

    @property
    def mandatory_fee_per_contract(self) -> Mapping[str, dict]:
        return MappingProxyType(self._mandatory_fee_per_contract)

    @property
    def should_replace(self) -> Mapping[str, bool]:
        return MappingProxyType(self._should_replace)

    @property
    def db_helper(self) -> "DBHelper | None":
        return self._db_helper

    def set_products(self, products: Mapping[str, dict]) -> None:
        self._check_writable("set_products")
        with self._lock:
            self._products = deepcopy(dict(products))

    def set_profit(self, profit: Mapping[str, dict]) -> None:
        self._check_writable("set_profit")
        with self._lock:
            self._profit = deepcopy(dict(profit))

    def set_mandatory_fee_per_contract(
        self, fees: Mapping[str, dict]
    ) -> None:
        self._check_writable("set_mandatory_fee_per_contract")
        with self._lock:
            self._mandatory_fee_per_contract = deepcopy(dict(fees))

    def set_should_replace(self, mapping: Mapping[str, bool]) -> None:
        self._check_writable("set_should_replace")
        with self._lock:
            self._should_replace = dict(mapping)

    def set_db_helper(self, db_helper: "DBHelper | None") -> None:
        self._check_writable("set_db_helper")
        with self._lock:
            self._db_helper = db_helper

    # ------------------------------------------------------------------
    # Diagnostic snapshot — replaces the ad-hoc deepcopy block in OrderEngine
    # ------------------------------------------------------------------

    def diagnostic_snapshot(self) -> dict[str, Any]:
        """Single-lock snapshot of state needed by ``calculate_new_order_move_from_snapshot``.

        Replaces the eight-line ``deepcopy``-and-collect block at
        ``core/order_engine.py:1245-1251``.  The returned shape matches what
        that block produced so it can be passed straight into the calculator.
        """

        with self._lock:
            return {
                "order": deepcopy(self._orders),
                "positions": deepcopy(self._positions),
                "product": dict(self._products),
                "profit": dict(self._profit),
                "mandatory_fee_per_contract": dict(self._mandatory_fee_per_contract),
                "parent_order_ids": deepcopy(self._parents),
                "child_order_ids": dict(self._child_to_parent),
            }
