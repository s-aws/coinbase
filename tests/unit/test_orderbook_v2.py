"""Unit tests for the v2 :mod:`core.orderbook` module.

These tests exercise the new instance-scoped, thread-safe ``OrderBook`` class
in isolation.  They are intentionally independent of the legacy
``configuration.OrderBook`` shim — the shim has its own integration tests in
the wider regression suite.

Coverage targets every public method on :class:`core.orderbook.OrderBook` and
the :class:`core.orderbook.ParentOrderEntry` dataclass.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from core.enums import OrderStatus
from core.orderbook import OrderBook, OrderBookReadOnlyError, ParentOrderEntry


# ---------------------------------------------------------------------------
# ParentOrderEntry
# ---------------------------------------------------------------------------


class TestParentOrderEntry:
    def test_defaults_are_instance_scoped(self):
        a = ParentOrderEntry()
        b = ParentOrderEntry()
        a.orders.append("c")
        a.target_movement["movement"] = 9.0
        a.extra["foo"] = 1
        assert b.orders == []
        assert b.target_movement == {"movement": 0.0, "type": "P"}
        assert b.extra == {}

    def test_as_dict_round_trips_known_fields(self):
        entry = ParentOrderEntry(
            product_id="BTC-USDC",
            side="BUY",
            parent_id=42,
            target_movement={"movement": 0.005, "type": "P"},
            max_order_replacement=10,
            current_order_replacement=2,
            orders=["c1", "c2"],
        )
        d = entry.as_dict()
        assert d["product_id"] == "BTC-USDC"
        assert d["orders"] == ["c1", "c2"]
        assert d["current_order_replacement"] == 2
        assert "extra" not in d

    def test_from_dict_preserves_unknown_keys_in_extra(self):
        legacy = {
            "product_id": "ETH-USDC",
            "side": "SELL",
            "orders": ["x"],
            "stealth_id": "abc",
            "audit_note": "n/a",
        }
        entry = ParentOrderEntry.from_dict(legacy)
        assert entry.product_id == "ETH-USDC"
        assert entry.orders == ["x"]
        assert entry.extra == {"stealth_id": "abc", "audit_note": "n/a"}

    def test_from_dict_then_as_dict_flattens_extra(self):
        legacy = {"product_id": "X", "side": "BUY", "stealth_id": "abc"}
        entry = ParentOrderEntry.from_dict(legacy)
        d = entry.as_dict()
        assert d["stealth_id"] == "abc"
        assert "extra" not in d


# ---------------------------------------------------------------------------
# Construction & defaults
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_blank_orderbook_has_empty_state(self):
        ob = OrderBook()
        assert ob.snapshot_orders() == {}
        assert ob.parents_snapshot() == {}
        assert ob.children_snapshot() == {}
        assert dict(ob.get_future_positions()) == {}

    def test_default_should_replace(self):
        ob = OrderBook()
        assert dict(ob.should_replace) == {"FILLED": True, "CANCELLED": True}

    def test_constructor_args_are_stored_as_independent_copies(self):
        external = {"BTC-USDC": {"price_increment": "0.01"}}
        ob = OrderBook(products=external)
        external["BTC-USDC"]["price_increment"] = "MUTATED"
        assert ob.products["BTC-USDC"]["price_increment"] == "0.01"

    def test_two_instances_do_not_share_mutable_state(self):
        a = OrderBook()
        b = OrderBook()
        a.upsert_order("x", {"status": "OPEN"})
        a.add_child("p", "c")
        a.upsert_future_position("Y", {"side": "LONG", "number_of_contracts": "1"})
        assert b.snapshot_orders() == {}
        assert b.parents_snapshot() == {}
        assert dict(b.get_future_positions()) == {}


# ---------------------------------------------------------------------------
# Live orders
# ---------------------------------------------------------------------------


class TestLiveOrders:
    def test_upsert_then_get(self):
        ob = OrderBook()
        ob.upsert_order("a", {"status": "OPEN", "size": "1"})
        assert ob.get_order("a") == {"status": "OPEN", "size": "1"}
        assert ob.has_order("a") is True

    def test_upsert_replaces(self):
        ob = OrderBook()
        ob.upsert_order("a", {"status": "OPEN"})
        ob.upsert_order("a", {"status": "FILLED"})
        assert ob.get_order("a")["status"] == "FILLED"

    def test_evict_returns_payload_and_removes(self):
        ob = OrderBook()
        ob.upsert_order("a", {"status": "OPEN"})
        evicted = ob.evict_order("a")
        assert evicted == {"status": "OPEN"}
        assert ob.has_order("a") is False
        assert ob.evict_order("a") is None  # idempotent

    def test_evict_missing_returns_none(self):
        assert OrderBook().evict_order("nope") is None

    def test_get_missing_returns_none(self):
        assert OrderBook().get_order("nope") is None

    def test_order_keys_returns_snapshot(self):
        ob = OrderBook()
        ob.upsert_order("a", {})
        ob.upsert_order("b", {})
        keys = ob.order_keys()
        assert sorted(keys) == ["a", "b"]
        # Mutating returned list does not affect orderbook.
        keys.append("zzz")
        assert "zzz" not in ob.order_keys()

    def test_snapshot_orders_is_deep_copy(self):
        ob = OrderBook()
        ob.upsert_order("a", {"status": "OPEN", "nested": {"k": 1}})
        snap = ob.snapshot_orders()
        snap["a"]["nested"]["k"] = 999
        assert ob.get_order("a")["nested"]["k"] == 1

    @pytest.mark.parametrize(
        "status,should_appear",
        [
            (OrderStatus.OPEN.value, True),
            (OrderStatus.UPDATE.value, True),
            (OrderStatus.FILLED.value, False),
            (OrderStatus.CANCELLED.value, False),
            (OrderStatus.PENDING.value, False),
            (OrderStatus.FAILED.value, False),
            (OrderStatus.CANCEL_QUEUED.value, False),
            (OrderStatus.SNAPSHOT.value, False),
            (OrderStatus.EXPIRED.value, False),
        ],
    )
    def test_snapshot_open_orders_filters_by_status(self, status, should_appear):
        ob = OrderBook()
        ob.upsert_order("x", {"status": status})
        snap = ob.snapshot_open_orders()
        if should_appear:
            assert "x" in snap
        else:
            assert "x" not in snap

    def test_snapshot_open_orders_handles_missing_status(self):
        ob = OrderBook()
        ob.upsert_order("x", {})  # no status key
        assert ob.snapshot_open_orders() == {}


# ---------------------------------------------------------------------------
# Parent / child relationships
# ---------------------------------------------------------------------------


class TestParentChildLinks:
    def test_register_parent_with_dataclass(self):
        ob = OrderBook()
        ob.register_parent("p", ParentOrderEntry(product_id="BTC-USDC", side="BUY"))
        p = ob.get_parent("p")
        # Storage is dict shape; ParentOrderEntry was converted via as_dict().
        assert isinstance(p, dict)
        assert p["product_id"] == "BTC-USDC"
        assert p["side"] == "BUY"

    def test_register_parent_with_dict(self):
        ob = OrderBook()
        ob.register_parent(
            "p",
            {
                "product_id": "ETH-USDC",
                "side": "SELL",
                "orders": ["c1"],
                "custom_audit": "abc",
            },
        )
        p = ob.get_parent("p")
        assert p["product_id"] == "ETH-USDC"
        assert p["orders"] == ["c1"]
        # Unknown keys preserved at top level (legacy semantics).
        assert p["custom_audit"] == "abc"

    def test_is_parent_and_is_child(self):
        ob = OrderBook()
        ob.add_child("p", "c1")
        assert ob.is_parent("p") is True
        assert ob.is_child("c1") is True
        assert ob.is_parent("c1") is False
        assert ob.is_child("p") is False

    def test_get_parent_of(self):
        ob = OrderBook()
        ob.add_child("p", "c1")
        assert ob.get_parent_of("c1") == "p"
        assert ob.get_parent_of("nope") is None

    def test_add_child_creates_parent_if_missing(self):
        ob = OrderBook()
        added = ob.add_child("p", "c1")
        assert added is True
        p = ob.get_parent("p")
        assert p["orders"] == ["c1"]
        assert p["current_order_replacement"] == 1

    def test_add_child_increments_only_for_new_children(self):
        ob = OrderBook()
        ob.add_child("p", "c1")
        ob.add_child("p", "c2")
        assert ob.add_child("p", "c1") is False  # duplicate
        p = ob.get_parent("p")
        assert p["orders"] == ["c1", "c2"]
        assert p["current_order_replacement"] == 2

    def test_add_child_repairs_missing_back_link(self):
        ob = OrderBook()
        ob.register_parent("p", ParentOrderEntry(orders=["c1"]))
        # Back-link not yet recorded.
        assert ob.get_parent_of("c1") is None
        result = ob.add_child("p", "c1")
        assert result is False  # already in orders
        # But the back-link was repaired.
        assert ob.get_parent_of("c1") == "p"
        # Counter was NOT incremented (idempotent).
        assert ob.get_parent("p")["current_order_replacement"] == 0

    def test_parents_snapshot_returns_legacy_dict_shape(self):
        ob = OrderBook()
        ob.register_parent(
            "p",
            ParentOrderEntry(product_id="BTC-USDC", side="BUY", orders=["c1"]),
        )
        snap = ob.parents_snapshot()
        assert "p" in snap
        assert snap["p"]["product_id"] == "BTC-USDC"
        assert snap["p"]["orders"] == ["c1"]
        assert isinstance(snap["p"], dict)

    def test_parents_snapshot_is_deep_copy(self):
        ob = OrderBook()
        ob.register_parent("p", ParentOrderEntry(orders=["c1"]))
        snap = ob.parents_snapshot()
        snap["p"]["orders"].append("c_leak")
        assert ob.get_parent("p")["orders"] == ["c1"]

    def test_children_snapshot_is_copy(self):
        ob = OrderBook()
        ob.add_child("p", "c1")
        snap = ob.children_snapshot()
        snap["leak"] = "x"
        assert ob.get_parent_of("leak") is None

    def test_atomic_replace_links_swaps_both_maps(self):
        ob = OrderBook()
        ob.add_child("old_p", "old_c")
        ob.atomic_replace_links(
            new_parents={"new_p": ParentOrderEntry(orders=["new_c"])},
            new_children={"new_c": "new_p"},
        )
        assert ob.is_parent("old_p") is False
        assert ob.is_child("old_c") is False
        assert ob.is_parent("new_p") is True
        assert ob.get_parent_of("new_c") == "new_p"

    def test_atomic_replace_links_accepts_dict_entries(self):
        ob = OrderBook()
        ob.atomic_replace_links(
            new_parents={"p": {"product_id": "ETH", "orders": ["c"]}},
            new_children={"c": "p"},
        )
        assert ob.get_parent("p")["product_id"] == "ETH"


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------


class TestPositions:
    def test_get_future_positions_returns_readonly_view(self):
        ob = OrderBook()
        ob.upsert_future_position("BTC-USDC", {"side": "LONG", "number_of_contracts": "1"})
        view = ob.get_future_positions()
        assert "BTC-USDC" in view
        with pytest.raises(TypeError):
            view["LEAK"] = {}  # type: ignore[index]

    def test_get_future_position(self):
        ob = OrderBook()
        ob.upsert_future_position("X", {"side": "LONG", "number_of_contracts": "5"})
        assert ob.get_future_position("X")["side"] == "LONG"
        assert ob.get_future_position("nope") is None

    def test_replace_future_positions(self):
        ob = OrderBook()
        ob.upsert_future_position("A", {"side": "LONG", "number_of_contracts": "1"})
        ob.replace_future_positions({"B": {"side": "SHORT", "number_of_contracts": "2"}})
        assert ob.get_future_position("A") is None
        assert ob.get_future_position("B")["side"] == "SHORT"

    def test_iter_future_positions_yields_snapshot(self):
        ob = OrderBook()
        ob.upsert_future_position("A", {"side": "LONG", "number_of_contracts": "1"})
        ob.upsert_future_position("B", {"side": "SHORT", "number_of_contracts": "2"})
        items = dict(ob.iter_future_positions())
        # Mutating orderbook after taking the iterator does not affect already-collected items.
        ob.upsert_future_position("C", {"side": "LONG", "number_of_contracts": "3"})
        assert sorted(items.keys()) == ["A", "B"]

    def test_snapshot_positions_is_deep_copy(self):
        ob = OrderBook()
        ob.upsert_future_position("X", {"side": "LONG", "number_of_contracts": "1"})
        snap = ob.snapshot_positions()
        snap["FUTURE"]["X"]["side"] = "MUTATED"
        assert ob.get_future_position("X")["side"] == "LONG"

    @pytest.mark.parametrize(
        "position,expected",
        [
            ({"side": "LONG", "number_of_contracts": "5"}, "LONG"),
            ({"side": "SHORT", "number_of_contracts": "5"}, "SHORT"),
            ({"side": "LONG", "number_of_contracts": "0"}, None),
            ({"side": "LONG", "number_of_contracts": "0.0"}, None),
            ({"side": "LONG", "number_of_contracts": "0.00000001"}, None),  # at threshold
            ({"side": "LONG", "number_of_contracts": "not-a-number"}, None),
            ({"side": "LONG"}, None),  # missing contracts → 0 → None
            ({}, None),
        ],
    )
    def test_get_position_side(self, position, expected):
        ob = OrderBook()
        ob.upsert_future_position("X", position)
        assert ob.get_position_side("X") == expected

    def test_get_position_side_missing_product_returns_none(self):
        assert OrderBook().get_position_side("nope") is None

    def test_apply_position_update_no_op_for_falsy(self):
        ob = OrderBook()
        ob.upsert_future_position("X", {"side": "LONG", "number_of_contracts": "5"})
        before = ob.snapshot_positions()
        ob.apply_position_update(None)
        ob.apply_position_update({})
        assert ob.snapshot_positions() == before


# ---------------------------------------------------------------------------
# Static reference data
# ---------------------------------------------------------------------------


class TestStaticReferences:
    def test_products_returns_readonly_view(self):
        ob = OrderBook(products={"BTC-USDC": {"price_increment": "0.01"}})
        assert ob.products["BTC-USDC"]["price_increment"] == "0.01"
        with pytest.raises(TypeError):
            ob.products["leak"] = {}  # type: ignore[index]

    def test_profit_returns_readonly_view(self):
        ob = OrderBook(profit={"SPOT": {"BUY": 0.001}})
        with pytest.raises(TypeError):
            ob.profit["leak"] = {}  # type: ignore[index]

    def test_mandatory_fee_per_contract_returns_readonly_view(self):
        ob = OrderBook(mandatory_fee_per_contract={"X": {"mandatory_fee_per_contract": 1.0}})
        with pytest.raises(TypeError):
            ob.mandatory_fee_per_contract["leak"] = {}  # type: ignore[index]

    def test_should_replace_returns_readonly_view(self):
        ob = OrderBook()
        with pytest.raises(TypeError):
            ob.should_replace["leak"] = True  # type: ignore[index]

    def test_set_products_replaces_atomically(self):
        ob = OrderBook(products={"old": {}})
        ob.set_products({"new": {"price_increment": "0.1"}})
        assert "old" not in ob.products
        assert ob.products["new"]["price_increment"] == "0.1"

    def test_set_profit_set_fees_set_should_replace(self):
        ob = OrderBook()
        ob.set_profit({"SPOT": {"BUY": 0.5}})
        ob.set_mandatory_fee_per_contract({"X": {"mandatory_fee_per_contract": 2.0}})
        ob.set_should_replace({"FILLED": False, "CANCELLED": True})
        assert ob.profit["SPOT"]["BUY"] == 0.5
        assert ob.mandatory_fee_per_contract["X"]["mandatory_fee_per_contract"] == 2.0
        assert ob.should_replace["FILLED"] is False

    def test_db_helper_default_none(self):
        assert OrderBook().db_helper is None

    def test_set_db_helper(self):
        sentinel = object()
        ob = OrderBook()
        ob.set_db_helper(sentinel)
        assert ob.db_helper is sentinel


# ---------------------------------------------------------------------------
# Diagnostic snapshot
# ---------------------------------------------------------------------------


class TestDiagnosticSnapshot:
    def test_shape_matches_legacy_block(self):
        ob = OrderBook(
            products={"BTC-USDC": {"price_increment": "0.01"}},
            profit={"SPOT": {"BUY": 0.001}},
            mandatory_fee_per_contract={"X": {"mandatory_fee_per_contract": 1.0}},
        )
        ob.upsert_order("a", {"status": "OPEN"})
        ob.add_child("p", "c")
        ob.upsert_future_position("X", {"side": "LONG", "number_of_contracts": "1"})

        snap = ob.diagnostic_snapshot()
        assert set(snap.keys()) == {
            "order",
            "positions",
            "product",
            "profit",
            "mandatory_fee_per_contract",
            "parent_order_ids",
            "child_order_ids",
        }
        assert snap["order"] == {"a": {"status": "OPEN"}}
        assert snap["child_order_ids"] == {"c": "p"}
        assert snap["parent_order_ids"]["p"]["orders"] == ["c"]
        assert snap["product"]["BTC-USDC"]["price_increment"] == "0.01"

    def test_snapshot_is_deep_copy(self):
        ob = OrderBook()
        ob.upsert_order("a", {"status": "OPEN", "nested": {"k": 1}})
        snap = ob.diagnostic_snapshot()
        snap["order"]["a"]["nested"]["k"] = 999
        assert ob.get_order("a")["nested"]["k"] == 1


# ---------------------------------------------------------------------------
# Lock contract — exposed for composed atomic ops
# ---------------------------------------------------------------------------


class TestLock:
    def test_lock_property_returns_rlock(self):
        ob = OrderBook()
        # An RLock supports being acquired multiple times by the same thread.
        with ob.lock:
            with ob.lock:
                ob.upsert_order("a", {"status": "OPEN"})
        assert ob.has_order("a")

    def test_methods_are_reentrant_under_caller_lock(self):
        # Caller holds the lock then calls a method that takes the lock again.
        # An RLock makes this safe; a plain Lock would deadlock.
        ob = OrderBook()
        completed = threading.Event()

        def composed():
            with ob.lock:
                ob.upsert_order("a", {"status": "OPEN"})
                ob.add_child("p", "c")
                completed.set()

        t = threading.Thread(target=composed)
        t.start()
        t.join(timeout=2.0)
        assert completed.is_set(), "Composed op deadlocked under self-lock"

    def test_concurrent_writes_do_not_corrupt_state(self):
        ob = OrderBook()
        N = 200

        def writer(i):
            ob.upsert_order(f"o{i}", {"status": "OPEN", "i": i})
            ob.add_child("parent", f"o{i}")

        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(writer, range(N)))

        assert len(ob.order_keys()) == N
        parent = ob.get_parent("parent")
        assert len(parent["orders"]) == N
        assert parent["current_order_replacement"] == N
        assert sorted(parent["orders"]) == sorted([f"o{i}" for i in range(N)])


# ---------------------------------------------------------------------------
# Read-only mode
# ---------------------------------------------------------------------------


class TestReadOnlyMode:
    def test_default_is_writable(self):
        ob = OrderBook()
        assert ob.read_only is False
        ob.upsert_order("a", {"status": "OPEN"})  # does not raise

    def test_read_only_property_reflects_constructor(self):
        assert OrderBook(read_only=True).read_only is True

    def test_pre_populated_state_is_observable_in_read_only(self):
        # Construct writable, populate, then build a read-only copy from the
        # snapshot.  This is the realistic shadow-instance pattern.
        writer = OrderBook()
        writer.upsert_order("a", {"status": "OPEN"})
        writer.add_child("p", "c")
        writer.upsert_future_position("X", {"side": "LONG", "number_of_contracts": "1"})

        reader = OrderBook(
            products={"BTC-USDC": {"price_increment": "0.01"}},
            positions=writer.snapshot_positions(),
            read_only=True,
        )
        # Reads work.
        assert reader.read_only is True
        assert reader.get_future_position("X") == {"side": "LONG", "number_of_contracts": "1"}
        assert reader.products["BTC-USDC"]["price_increment"] == "0.01"
        assert reader.snapshot_orders() == {}
        assert reader.diagnostic_snapshot()["positions"]["FUTURE"]["X"]["side"] == "LONG"

    @pytest.mark.parametrize(
        "op_name,call",
        [
            ("upsert_order", lambda ob: ob.upsert_order("a", {})),
            ("evict_order", lambda ob: ob.evict_order("a")),
            ("register_parent", lambda ob: ob.register_parent("p", {})),
            ("add_child", lambda ob: ob.add_child("p", "c")),
            ("atomic_replace_links", lambda ob: ob.atomic_replace_links({}, {})),
            ("upsert_future_position", lambda ob: ob.upsert_future_position("X", {})),
            ("replace_future_positions", lambda ob: ob.replace_future_positions({})),
            ("apply_position_update", lambda ob: ob.apply_position_update({"foo": 1})),
            ("set_products", lambda ob: ob.set_products({})),
            ("set_profit", lambda ob: ob.set_profit({})),
            ("set_mandatory_fee_per_contract", lambda ob: ob.set_mandatory_fee_per_contract({})),
            ("set_should_replace", lambda ob: ob.set_should_replace({})),
            ("set_db_helper", lambda ob: ob.set_db_helper(None)),
        ],
    )
    def test_every_mutator_raises_in_read_only(self, op_name, call):
        ob = OrderBook(read_only=True)
        with pytest.raises(OrderBookReadOnlyError, match=op_name):
            call(ob)

    def test_apply_position_update_falsy_is_a_noop_even_in_read_only(self):
        # Falsy update returns before the writability check \u2014 calling with
        # None on a read-only orderbook must not raise.
        ob = OrderBook(read_only=True)
        ob.apply_position_update(None)
        ob.apply_position_update({})

    def test_read_only_blocks_state_mutation(self):
        ob = OrderBook(read_only=True)
        with pytest.raises(OrderBookReadOnlyError):
            ob.upsert_order("a", {"status": "OPEN"})
        # State unchanged.
        assert ob.snapshot_orders() == {}
