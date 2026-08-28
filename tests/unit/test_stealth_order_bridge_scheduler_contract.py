"""Focused contract tests for the event-driven stealth-order bridge.

These tests keep database and REST behavior behind small fakes.  The bridge is
responsible only for publishing ordered market snapshots, selecting the orders
affected by an event or deadline, respecting runtime admission, and owning the
scheduler lifecycle.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
import threading
import time
from typing import Any, Dict, Iterable, Mapping, Optional
from unittest.mock import Mock
import uuid

import pytest

import bridges.stealth_order_bridge as bridge_module
from bridges.stealth_event_deadline_scheduler import (
    DeadlineWake,
    MarketEvent,
    StealthEventDeadlineScheduler,
)
from core.enums import EngineState, RevealConditionType, StealthOrderStatus, StealthWakePurpose
from core.exceptions import StealthOrderPersistenceError
from core.runtime_controller import EngineNotAdmittingError
from core.stealth_order_manager import StealthOrderManager


def _time_delay_order(
    stealth_order_id: str,
    product_id: str,
    *,
    delay_seconds: float = 60.0,
    status: StealthOrderStatus = StealthOrderStatus.HIDDEN,
) -> Dict[str, Any]:
    now = datetime.utcnow()
    return {
        "stealth_order_id": stealth_order_id,
        "product_id": product_id,
        "status": status.value,
        "remaining_size": 1.0,
        "created_at": now,
        "updated_at": now,
        "condition_first_met_at": None,
        "condition_confirmed_at": None,
        "reveal_condition_type": RevealConditionType.TIME_DELAY.value,
        "reveal_condition_json": {
            "type": RevealConditionType.TIME_DELAY.value,
            "delay_seconds": delay_seconds,
            "jitter_seconds": 0,
        },
        "anchor_repricing_policy_json": {"enabled": False},
        "anchor_repricing_state_json": {},
    }


def _pending_price_order(
    stealth_order_id: str,
    product_id: str,
) -> Dict[str, Any]:
    now = datetime.utcnow()
    return {
        "stealth_order_id": stealth_order_id,
        "product_id": product_id,
        "status": StealthOrderStatus.PENDING.value,
        "remaining_size": 1.0,
        "created_at": now,
        "updated_at": now,
        "condition_first_met_at": now,
        "condition_confirmed_at": None,
        "reveal_condition_type": RevealConditionType.PRICE_THRESHOLD.value,
        "reveal_condition_json": {
            "type": RevealConditionType.PRICE_THRESHOLD.value,
            "price_threshold": 100.0,
            "direction": "above",
            "hold_duration_seconds": 5.0,
        },
        "anchor_repricing_policy_json": {"enabled": False},
        "anchor_repricing_state_json": {},
    }


class FakeStealthManager:
    """Minimal manager surface used by ``StealthOrderBridge``."""

    def __init__(self, orders: Iterable[Mapping[str, Any]] = ()) -> None:
        self.in_memory_orders = {
            str(order["stealth_order_id"]): dict(order) for order in orders
        }
        self.db_client = None
        self.log_callback = None
        self._market_cache: Dict[str, Dict[str, Any]] = {}
        self.schedule_change_callback = None

        self.actions = []
        self.snapshot_products = []
        self.evaluated_ids = []
        self.evaluated_market_prices = []
        self.evaluation_event = threading.Event()
        self.revealed_ids = []
        self.anchor_products = []
        self.anchor_calls = []
        self.trigger_on_evaluation = set()
        self.raise_on_evaluation = set()

    def set_schedule_invalidation_callback(self, callback) -> None:
        self.schedule_change_callback = callback

    @contextmanager
    def _get_orders_cache_lock(self):
        yield

    def load_all_active_orders_from_db(self) -> int:
        self.actions.append(("load", None))
        return len(self.in_memory_orders)

    def publish_market_data(
        self,
        product_id: str,
        market_data: Mapping[str, Any],
    ) -> Dict[str, Any]:
        snapshot = dict(market_data)
        self._market_cache[product_id] = snapshot
        self.actions.append(("publish", product_id, snapshot.get("price")))
        return dict(snapshot)

    def snapshot_active_stealth_orders(
        self,
        product_id: Optional[str] = None,
    ) -> list[str]:
        self.snapshot_products.append(product_id)
        active_statuses = {
            StealthOrderStatus.HIDDEN.value,
            StealthOrderStatus.PENDING.value,
            StealthOrderStatus.TRIGGERED.value,
            StealthOrderStatus.REVEALED.value,
        }
        return [
            sid
            for sid, order in self.in_memory_orders.items()
            if order.get("status") in active_statuses
            and (product_id is None or order.get("product_id") == product_id)
        ]

    # Compatibility seam for an accidental regression to the old global scan.
    # The scoped-evaluation test will fail because this records ``None`` and
    # returns both products.
    def _get_active_stealth_orders(self) -> list[str]:
        return self.snapshot_active_stealth_orders()

    def _get_stealth_order(
        self,
        stealth_order_id: str,
        raise_if_missing: bool = False,
    ) -> Optional[Dict[str, Any]]:
        order = self.in_memory_orders.get(stealth_order_id)
        if order is None and raise_if_missing:
            raise KeyError(stealth_order_id)
        return order

    def _get_current_market_data(self, product_id: str) -> Dict[str, Any]:
        return dict(self._market_cache.get(product_id, {}))

    def should_trigger_reveal(
        self,
        stealth_order_id: str,
        market_data: Optional[Mapping[str, Any]] = None,
        evaluation_time: Optional[datetime] = None,
    ) -> tuple[bool, Optional[str]]:
        del evaluation_time
        self.evaluated_ids.append(stealth_order_id)
        self.evaluated_market_prices.append(
            None if market_data is None else market_data.get("price")
        )
        self.actions.append(("evaluate", stealth_order_id))
        if stealth_order_id in self.raise_on_evaluation:
            raise RuntimeError(f"synthetic evaluation failure: {stealth_order_id}")
        if stealth_order_id in self.trigger_on_evaluation:
            self.in_memory_orders[stealth_order_id]["status"] = (
                StealthOrderStatus.TRIGGERED.value
            )
            result = (True, "condition committed by fake manager")
        else:
            result = (False, "condition not met")
        self.evaluation_event.set()
        return result

    def reset_continuous_condition(
        self,
        stealth_order_id: str,
        *,
        reason: str,
        market_data=None,
        evaluation_time=None,
    ) -> bool:
        del market_data, evaluation_time
        order = self.in_memory_orders.get(stealth_order_id)
        if not order:
            return False
        if order.get("reveal_condition_type") not in {
            RevealConditionType.PRICE_THRESHOLD.value,
            RevealConditionType.SPREAD.value,
        }:
            return False
        if order.get("status") not in {
            StealthOrderStatus.HIDDEN.value,
            StealthOrderStatus.PENDING.value,
        }:
            return False
        if not (
            order.get("status") == StealthOrderStatus.PENDING.value
            or order.get("condition_first_met_at") is not None
            or order.get("condition_confirmed_at") is not None
        ):
            return False

        order["status"] = StealthOrderStatus.HIDDEN.value
        order["condition_first_met_at"] = None
        order["condition_confirmed_at"] = None
        self.actions.append(("reset", stealth_order_id, reason))
        return True

    def reveal_order_slice(self, stealth_order_id: str) -> Optional[str]:
        self.revealed_ids.append(stealth_order_id)
        return f"placed-{stealth_order_id}"

    @staticmethod
    def _normalize_anchor_repricing_state(value) -> Dict[str, Any]:
        return dict(value or {})

    def process_anchor_repricing_for_product(
        self,
        product_id: str,
        stealth_order_ids=None,
        market_data=None,
    ) -> int:
        self.anchor_products.append(product_id)
        self.anchor_calls.append(
            (
                product_id,
                tuple(stealth_order_ids or ()),
                dict(market_data or {}),
            )
        )
        return 0


class PausedRuntimeController:
    state = EngineState.PAUSED

    def is_admitting(self) -> bool:
        return False

    @contextmanager
    def track_inflight(self, _category: str):
        yield

    @contextmanager
    def track_admitted_inflight(self, category: str):
        raise EngineNotAdmittingError(self.state, category)
        yield


class MockRuntimeController:
    def __init__(self) -> None:
        self.pause_requests = 0

    def request_pause(self) -> bool:
        self.pause_requests += 1
        return True

    def is_admitting(self) -> bool:
        return self.pause_requests == 0

    @contextmanager
    def track_admitted_inflight(self, category: str):
        if not self.is_admitting():
            raise EngineNotAdmittingError(EngineState.PAUSED, category)
        yield


class MutableRuntimeController:
    def __init__(self, state: EngineState = EngineState.RUNNING) -> None:
        self.state = state
        self.pause_requests = 0

    def is_admitting(self) -> bool:
        return self.state == EngineState.RUNNING

    def request_pause(self) -> bool:
        self.pause_requests += 1
        self.state = EngineState.PAUSED
        return True

    @contextmanager
    def track_inflight(self, _category: str):
        yield

    @contextmanager
    def track_admitted_inflight(self, category: str):
        if not self.is_admitting():
            raise EngineNotAdmittingError(self.state, category)
        yield


class RejectAtAtomicAdmissionController(MutableRuntimeController):
    """Let optimistic reads pass, then make pause win atomic admission once."""

    def __init__(self) -> None:
        super().__init__(EngineState.RUNNING)
        self.reject_next_atomic_admission = True

    @contextmanager
    def track_admitted_inflight(self, category: str):
        if self.reject_next_atomic_admission:
            self.reject_next_atomic_admission = False
            self.state = EngineState.PAUSED
            raise EngineNotAdmittingError(self.state, category)
        if not self.is_admitting():
            raise EngineNotAdmittingError(self.state, category)
        yield


def _new_bridge(
    manager: FakeStealthManager,
) -> tuple[bridge_module.StealthOrderBridge, StealthEventDeadlineScheduler]:
    scheduler = StealthEventDeadlineScheduler()
    bridge = bridge_module.StealthOrderBridge(
        manager,
        order_engine=None,
        scheduler=scheduler,
    )
    # Most tests exercise the handler contract directly without bridge.start().
    # Tests for startup gating explicitly call start() (which clears this) or
    # clear it themselves.
    bridge._decisions_ready.set()
    return bridge, scheduler


class MutableMonotonicClock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def test_market_evaluation_rechecks_readiness_after_sid_lock_wait() -> None:
    manager = FakeStealthManager(
        (_pending_price_order("sid-a", "CONTRACT-A"),)
    )
    bridge, scheduler = _new_bridge(manager)
    selected = threading.Event()
    original_snapshot = manager.snapshot_active_stealth_orders

    def snapshot_active(product_id=None):
        result = original_snapshot(product_id)
        selected.set()
        return result

    manager.snapshot_active_stealth_orders = snapshot_active
    action_lock = bridge._get_order_action_lock("sid-a")
    action_lock.acquire()
    worker = threading.Thread(
        target=bridge._handle_market_event,
        args=(
            MarketEvent(
                sequence=1,
                product_id="CONTRACT-A",
                payload={
                    "product_id": "CONTRACT-A",
                    "price": 101.0,
                    "bid": 100.0,
                    "ask": 102.0,
                    "time": datetime.utcnow(),
                    "source": "ticker",
                },
                published_monotonic=time.monotonic(),
            ),
        ),
    )
    worker.start()

    try:
        assert selected.wait(timeout=0.75)
        bridge._decisions_ready.clear()
    finally:
        action_lock.release()
    worker.join(timeout=0.75)

    assert not worker.is_alive()
    assert manager.evaluated_ids == []
    assert manager.revealed_ids == []
    assert manager.in_memory_orders["sid-a"]["status"] == (
        StealthOrderStatus.PENDING.value
    )
    scheduler.stop()


def test_continuity_reset_rechecks_readiness_after_sid_lock_wait() -> None:
    manager = FakeStealthManager(
        (_pending_price_order("sid-a", "CONTRACT-A"),)
    )
    bridge, scheduler = _new_bridge(manager)
    selected = threading.Event()
    original_snapshot = manager.snapshot_active_stealth_orders

    def snapshot_active(product_id=None):
        result = original_snapshot(product_id)
        selected.set()
        return result

    manager.snapshot_active_stealth_orders = snapshot_active
    action_lock = bridge._get_order_action_lock("sid-a")
    action_lock.acquire()
    worker = threading.Thread(
        target=bridge._handle_market_event,
        args=(
            MarketEvent(
                sequence=1,
                product_id="CONTRACT-A",
                payload={
                    "time": datetime.utcnow(),
                    "source": "continuity_reset",
                },
                published_monotonic=time.monotonic(),
                contains_market_snapshot=False,
                continuity_reset=True,
                discarded_event_count=1,
                continuity_reset_counts=(("CONTRACT-A", 1),),
            ),
        ),
    )
    worker.start()

    try:
        assert selected.wait(timeout=0.75)
        bridge._decisions_ready.clear()
    finally:
        action_lock.release()
    worker.join(timeout=0.75)

    assert not worker.is_alive()
    assert not any(action[0] == "reset" for action in manager.actions)
    assert manager.in_memory_orders["sid-a"]["status"] == (
        StealthOrderStatus.PENDING.value
    )
    scheduler.stop()


def test_root_creation_stays_serialized_through_created_publication() -> None:
    manager = FakeStealthManager()
    bridge, scheduler = _new_bridge(manager)
    cache_published = threading.Event()
    release_creation = threading.Event()
    sid_selected = threading.Event()
    created_ids = []

    def blocking_create_stealth_order(*, stealth_order_id=None, **_kwargs):
        order = _pending_price_order(stealth_order_id, "CONTRACT-A")
        order["status"] = StealthOrderStatus.HIDDEN.value
        order["condition_first_met_at"] = None
        manager.in_memory_orders[stealth_order_id] = order
        created_ids.append(stealth_order_id)
        manager.actions.append(("cache_published", stealth_order_id))
        cache_published.set()
        assert release_creation.wait(timeout=0.75)
        manager.actions.append(("created", stealth_order_id))
        return stealth_order_id

    manager.create_stealth_order = blocking_create_stealth_order
    original_snapshot = manager.snapshot_active_stealth_orders

    def snapshot_active(product_id=None):
        result = original_snapshot(product_id)
        sid_selected.set()
        return result

    manager.snapshot_active_stealth_orders = snapshot_active
    creation_result = []
    creation_thread = threading.Thread(
        target=lambda: creation_result.append(
            bridge.create_stealth_order(product_id="CONTRACT-A")
        )
    )
    creation_thread.start()
    assert cache_published.wait(timeout=0.75)

    market_thread = threading.Thread(
        target=bridge._handle_market_event,
        args=(
            MarketEvent(
                sequence=1,
                product_id="CONTRACT-A",
                payload={
                    "product_id": "CONTRACT-A",
                    "price": 101.0,
                    "bid": 100.0,
                    "ask": 102.0,
                    "time": datetime.utcnow(),
                    "source": "ticker",
                },
                published_monotonic=time.monotonic(),
            ),
        ),
    )
    market_thread.start()

    try:
        assert sid_selected.wait(timeout=0.75)
        assert manager.evaluated_ids == []
    finally:
        release_creation.set()
    creation_thread.join(timeout=0.75)
    market_thread.join(timeout=0.75)

    assert not creation_thread.is_alive()
    assert not market_thread.is_alive()
    assert creation_result == created_ids
    assert manager.evaluated_ids == created_ids
    action_names = [action[0] for action in manager.actions]
    assert action_names.index("created") < action_names.index("evaluate")
    scheduler.stop()


def test_follow_up_creation_lock_covers_post_create_fields() -> None:
    manager = FakeStealthManager()
    bridge, scheduler = _new_bridge(manager)
    cache_published = threading.Event()
    release_post_create = threading.Event()
    sid_selected = threading.Event()
    follow_up_ids = []

    def blocking_create_follow_up(
        *,
        follow_up_stealth_order_id=None,
        **_kwargs,
    ):
        order = _pending_price_order(
            follow_up_stealth_order_id,
            "CONTRACT-A",
        )
        order["status"] = StealthOrderStatus.HIDDEN.value
        order["condition_first_met_at"] = None
        manager.in_memory_orders[follow_up_stealth_order_id] = order
        follow_up_ids.append(follow_up_stealth_order_id)
        manager.actions.append(
            ("follow_up_cache_published", follow_up_stealth_order_id)
        )
        cache_published.set()
        assert release_post_create.wait(timeout=0.75)
        order["follow_up_audit"] = {"complete": True}
        manager.actions.append(
            ("follow_up_postfields", follow_up_stealth_order_id)
        )
        return follow_up_stealth_order_id

    manager.create_follow_up_stealth_order = blocking_create_follow_up
    original_snapshot = manager.snapshot_active_stealth_orders

    def snapshot_active(product_id=None):
        result = original_snapshot(product_id)
        sid_selected.set()
        return result

    manager.snapshot_active_stealth_orders = snapshot_active
    creation_result = []
    creation_thread = threading.Thread(
        target=lambda: creation_result.append(
            bridge.create_follow_up_stealth_order(
                original_stealth_order_id="original-sid"
            )
        )
    )
    creation_thread.start()
    assert cache_published.wait(timeout=0.75)

    market_thread = threading.Thread(
        target=bridge._handle_market_event,
        args=(
            MarketEvent(
                sequence=1,
                product_id="CONTRACT-A",
                payload={
                    "product_id": "CONTRACT-A",
                    "price": 101.0,
                    "bid": 100.0,
                    "ask": 102.0,
                    "time": datetime.utcnow(),
                    "source": "ticker",
                },
                published_monotonic=time.monotonic(),
            ),
        ),
    )
    market_thread.start()

    try:
        assert sid_selected.wait(timeout=0.75)
        assert manager.evaluated_ids == []
    finally:
        release_post_create.set()
    creation_thread.join(timeout=0.75)
    market_thread.join(timeout=0.75)

    assert not creation_thread.is_alive()
    assert not market_thread.is_alive()
    assert creation_result == follow_up_ids
    assert manager.evaluated_ids == follow_up_ids
    follow_up = manager.in_memory_orders[follow_up_ids[0]]
    assert follow_up["follow_up_audit"] == {"complete": True}
    action_names = [action[0] for action in manager.actions]
    assert action_names.index("follow_up_postfields") < action_names.index(
        "evaluate"
    )
    scheduler.stop()


@pytest.mark.parametrize(
    ("bridge_method", "manager_method", "id_keyword"),
    (
        (
            "create_stealth_order",
            "create_stealth_order",
            "stealth_order_id",
        ),
        (
            "create_follow_up_stealth_order",
            "create_follow_up_stealth_order",
            "follow_up_stealth_order_id",
        ),
    ),
)
def test_explicit_creation_id_is_normalized_before_lock_ownership(
    bridge_method: str,
    manager_method: str,
    id_keyword: str,
) -> None:
    manager = FakeStealthManager()
    bridge, scheduler = _new_bridge(manager)
    explicit_id = uuid.uuid4()
    received_ids = []

    def create_with_schedule_callback(**kwargs):
        order_id = kwargs[id_keyword]
        received_ids.append(order_id)
        manager.in_memory_orders[order_id] = _time_delay_order(
            order_id,
            "CONTRACT-A",
        )
        manager.schedule_change_callback(order_id)
        return order_id

    setattr(manager, manager_method, create_with_schedule_callback)

    try:
        result = getattr(bridge, bridge_method)(
            **{id_keyword: explicit_id}
        )

        normalized_id = str(explicit_id)
        assert result == normalized_id
        assert received_ids == [normalized_id]
        assert set(bridge._order_action_locks) == {normalized_id}
    finally:
        scheduler.stop()


def test_exchange_id_sync_re_resolves_under_sid_action_lock() -> None:
    order = _time_delay_order("sid-a", "CONTRACT-A")
    order["revealed_orders"] = [
        {"placed_order_id": "placed-old", "exchange_order_id": None}
    ]
    order["anchor_repricing_state_json"] = {
        "active_placement_client_order_id": "placed-old",
        "active_exchange_order_id": None,
    }
    manager = FakeStealthManager((order,))
    bridge, scheduler = _new_bridge(manager)
    initial_lookup_complete = threading.Event()
    sync_started = threading.Event()
    find_calls = []

    def find_by_placed_order_id(placed_order_id):
        find_calls.append(placed_order_id)
        if len(find_calls) == 1:
            initial_lookup_complete.set()
        return manager.in_memory_orders["sid-a"]

    def sync_exchange_order_id(placed_order_id, exchange_order_id):
        sync_started.set()
        current = manager.in_memory_orders["sid-a"]
        current["revealed_orders"][0]["exchange_order_id"] = exchange_order_id
        state = dict(current["anchor_repricing_state_json"])
        if state.get("active_placement_client_order_id") == placed_order_id:
            state["active_exchange_order_id"] = exchange_order_id
            current["anchor_repricing_state_json"] = state
        return True

    manager.find_stealth_order_by_placed_order_id = find_by_placed_order_id
    manager.sync_exchange_order_id_for_placed_order = sync_exchange_order_id
    action_lock = bridge._get_order_action_lock("sid-a")
    action_lock.acquire()
    results = []
    worker = threading.Thread(
        target=lambda: results.append(
            bridge.sync_exchange_order_id_for_placed_order(
                "placed-old",
                "exchange-old",
            )
        )
    )
    worker.start()

    try:
        assert initial_lookup_complete.wait(timeout=0.75)
        assert not sync_started.is_set()
        manager.in_memory_orders["sid-a"][
            "anchor_repricing_state_json"
        ] = {
            "active_placement_client_order_id": "placed-new",
            "active_exchange_order_id": "exchange-new",
        }
    finally:
        action_lock.release()
    worker.join(timeout=0.75)

    assert not worker.is_alive()
    assert results == [True]
    assert find_calls == ["placed-old", "placed-old"]
    assert manager.in_memory_orders["sid-a"][
        "anchor_repricing_state_json"
    ] == {
        "active_placement_client_order_id": "placed-new",
        "active_exchange_order_id": "exchange-new",
    }
    scheduler.stop()


def test_price_condition_updates_for_one_order_are_serialized() -> None:
    manager = FakeStealthManager((_pending_price_order("sid-a", "CONTRACT-A"),))
    bridge, scheduler = _new_bridge(manager)
    first_entered = threading.Event()
    release_first = threading.Event()
    second_attempting = threading.Event()
    second_entered = threading.Event()
    calls = []
    errors = []

    def update_price_condition(
        stealth_order_id,
        *,
        price_threshold,
        hold_duration_seconds=None,
    ):
        del hold_duration_seconds
        calls.append((stealth_order_id, price_threshold))
        if price_threshold == 101.0:
            first_entered.set()
            assert release_first.wait(timeout=1)
        else:
            second_entered.set()
        return True

    manager.update_price_condition = update_price_condition

    def update(threshold, *, attempting_event=None):
        if attempting_event is not None:
            attempting_event.set()
        try:
            bridge.update_price_condition(
                "sid-a",
                price_threshold=threshold,
            )
        except Exception as exc:  # pragma: no cover - assertion reports details
            errors.append(exc)

    first = threading.Thread(target=update, args=(101.0,))
    second = threading.Thread(
        target=update,
        args=(102.0,),
        kwargs={"attempting_event": second_attempting},
    )

    try:
        first.start()
        assert first_entered.wait(timeout=1)
        second.start()
        assert second_attempting.wait(timeout=1)
        assert second_entered.wait(timeout=0.1) is False

        release_first.set()
        first.join(timeout=1)
        second.join(timeout=1)

        assert first.is_alive() is False
        assert second.is_alive() is False
        assert errors == []
        assert calls == [("sid-a", 101.0), ("sid-a", 102.0)]
    finally:
        release_first.set()
        first.join(timeout=1)
        second.join(timeout=1)
        scheduler.stop()


def test_schedule_change_producers_for_one_order_are_serialized(
    monkeypatch,
) -> None:
    manager = FakeStealthManager((_pending_price_order("sid-a", "CONTRACT-A"),))
    bridge, scheduler = _new_bridge(manager)
    first_entered = threading.Event()
    release_first = threading.Event()
    second_attempting = threading.Event()
    second_entered = threading.Event()
    calls = []

    def rebuild(_stealth_order_id, **_kwargs):
        calls.append(threading.current_thread().name)
        if len(calls) == 1:
            first_entered.set()
            assert release_first.wait(timeout=1)
        else:
            second_entered.set()

    monkeypatch.setattr(bridge, "_schedule_order_locked", rebuild)

    def publish_change(*, attempting_event=None):
        if attempting_event is not None:
            attempting_event.set()
        bridge._handle_order_schedule_change("sid-a")

    first = threading.Thread(target=publish_change, name="first-producer")
    second = threading.Thread(
        target=publish_change,
        kwargs={"attempting_event": second_attempting},
        name="second-producer",
    )

    try:
        first.start()
        assert first_entered.wait(timeout=1)
        second.start()
        assert second_attempting.wait(timeout=1)
        assert second_entered.wait(timeout=0.1) is False

        release_first.set()
        first.join(timeout=1)
        second.join(timeout=1)

        assert first.is_alive() is False
        assert second.is_alive() is False
        assert calls == ["first-producer", "second-producer"]
    finally:
        release_first.set()
        first.join(timeout=1)
        second.join(timeout=1)
        scheduler.stop()


def test_deadline_rebuild_cannot_overwrite_concurrent_authoritative_schedule(
    monkeypatch,
) -> None:
    manager = FakeStealthManager((_time_delay_order("sid-a", "CONTRACT-A"),))
    bridge, scheduler = _new_bridge(manager)
    evaluation_entered = threading.Event()
    release_evaluation = threading.Event()
    update_attempting = threading.Event()
    update_completed = threading.Event()
    rebuild_order = []
    errors = []

    def evaluate_locked(_stealth_order_id, **_kwargs):
        evaluation_entered.set()
        assert release_evaluation.wait(timeout=1)

    def record_condition_rebuild(_stealth_order_id, **_kwargs):
        rebuild_order.append(threading.current_thread().name)

    monkeypatch.setattr(
        bridge,
        "_evaluate_scheduled_order_locked",
        evaluate_locked,
    )
    monkeypatch.setattr(
        bridge,
        "_schedule_condition_wake",
        record_condition_rebuild,
    )
    generation = scheduler.schedule_after(
        "sid-a",
        StealthWakePurpose.TIME_DELAY,
        0,
    )
    wake = DeadlineWake(
        stealth_order_id="sid-a",
        purpose=StealthWakePurpose.TIME_DELAY,
        generation=generation,
        deadline_monotonic=time.monotonic(),
    )

    def handle_deadline():
        try:
            bridge._handle_deadline_wake(wake)
        except Exception as exc:  # pragma: no cover - assertion reports details
            errors.append(exc)

    def publish_authoritative_update():
        update_attempting.set()
        try:
            bridge._schedule_order("sid-a")
        except Exception as exc:  # pragma: no cover - assertion reports details
            errors.append(exc)
        finally:
            update_completed.set()

    deadline_thread = threading.Thread(
        target=handle_deadline,
        name="deadline-rebuild",
    )
    update_thread = threading.Thread(
        target=publish_authoritative_update,
        name="authoritative-update",
    )

    try:
        deadline_thread.start()
        assert evaluation_entered.wait(timeout=1)
        update_thread.start()
        assert update_attempting.wait(timeout=1)
        assert update_completed.wait(timeout=0.1) is False

        release_evaluation.set()
        deadline_thread.join(timeout=1)
        update_thread.join(timeout=1)

        assert deadline_thread.is_alive() is False
        assert update_thread.is_alive() is False
        assert errors == []
        assert rebuild_order == [
            "deadline-rebuild",
            "authoritative-update",
        ]
    finally:
        release_evaluation.set()
        deadline_thread.join(timeout=1)
        update_thread.join(timeout=1)
        scheduler.stop()


def test_reconciliation_publishes_schedule_for_new_database_order() -> None:
    manager = FakeStealthManager()
    bridge, scheduler = _new_bridge(manager)

    class ReconciliationDB:
        @staticmethod
        def execute_query(_query):
            return [{"stealth_order_id": "sid-new"}]

    manager.db_client = ReconciliationDB()

    def load_new_order(stealth_order_id, raise_if_missing=False):
        del raise_if_missing
        order = _time_delay_order(stealth_order_id, "CONTRACT-A")
        manager.in_memory_orders[stealth_order_id] = order
        manager.schedule_change_callback(stealth_order_id)
        return order

    manager._get_stealth_order = load_new_order

    try:
        changed = bridge._reconcile_stealth_orders()

        assert changed is True
        assert "sid-new" in manager.in_memory_orders
        assert scheduler.current_generation(
            "sid-new",
            StealthWakePurpose.TIME_DELAY,
        ) > 0
    finally:
        scheduler.stop()


def test_websocket_market_publication_preserves_every_event_in_order() -> None:
    manager = FakeStealthManager()
    bridge, scheduler = _new_bridge(manager)

    returned_products = [
        bridge.publish_ticker_update(
            "CONTRACT-A",
            {
                "price": str(price),
                "best_bid": str(price - 1),
                "best_ask": str(price + 1),
                "volume_24_h": "1440",
            },
        )
        for price in (101, 102, 103)
    ]

    batch = scheduler.run_due()

    assert returned_products == ["CONTRACT-A", "CONTRACT-A", "CONTRACT-A"]
    assert [event.product_id for event in batch.market_events] == returned_products
    assert [event.payload["price"] for event in batch.market_events] == [
        101.0,
        102.0,
        103.0,
    ]
    assert [event.sequence for event in batch.market_events] == [1, 2, 3]
    scheduler.stop()


def test_ticker_publication_preserves_coinbase_event_time() -> None:
    manager = FakeStealthManager()
    bridge, scheduler = _new_bridge(manager)

    bridge.publish_ticker_update(
        "CONTRACT-A",
        {
            "price": "101",
            "best_bid": "100",
            "best_ask": "102",
        },
        event_time="2026-08-27T12:34:56.123Z",
    )
    event = scheduler.run_due().market_events[0]

    assert event.payload["time"] == datetime(
        2026,
        8,
        27,
        12,
        34,
        56,
        123000,
    )
    scheduler.stop()


def test_out_of_order_ticker_breaks_continuity_without_overwriting_cache() -> None:
    manager = FakeStealthManager(
        (_pending_price_order("sid-pending", "CONTRACT-A"),)
    )
    bridge, scheduler = _new_bridge(manager)

    newer_time = "2026-08-27T12:34:57Z"
    older_time = "2026-08-27T12:34:56Z"
    bridge.publish_ticker_update(
        "CONTRACT-A",
        {"price": "102", "best_bid": "101", "best_ask": "103"},
        event_time=newer_time,
    )
    bridge.publish_ticker_update(
        "CONTRACT-A",
        {"price": "99", "best_bid": "98", "best_ask": "100"},
        event_time=older_time,
    )

    batch = scheduler.run_due(on_market_event=bridge._handle_market_event)

    assert len(batch.market_events) == 2
    assert batch.market_events[0].continuity_reset is False
    assert batch.market_events[0].payload["price"] == 102.0
    assert batch.market_events[1].continuity_reset is True
    assert batch.market_events[1].contains_market_snapshot is False
    assert batch.market_events[1].payload["source"] == "continuity_reset"
    assert manager._market_cache["CONTRACT-A"]["price"] == 102.0
    assert manager.in_memory_orders["sid-pending"]["status"] == (
        StealthOrderStatus.HIDDEN.value
    )
    scheduler.stop()


def test_timestamp_check_cache_and_fifo_append_are_one_publication(
    monkeypatch,
) -> None:
    manager = FakeStealthManager()
    bridge, scheduler = _new_bridge(manager)
    first_append_entered = threading.Event()
    release_first_append = threading.Event()
    original_publish = scheduler.publish_market_event
    errors = []

    def delayed_publish(product_id, payload=None):
        if payload.get("price") == 101.0:
            first_append_entered.set()
            assert release_first_append.wait(timeout=0.75)
        return original_publish(product_id, payload)

    monkeypatch.setattr(scheduler, "publish_market_event", delayed_publish)

    def publish(price: int, event_time: str) -> None:
        try:
            bridge.publish_ticker_update(
                "CONTRACT-A",
                {
                    "price": str(price),
                    "best_bid": str(price - 1),
                    "best_ask": str(price + 1),
                },
                event_time=event_time,
            )
        except Exception as error:  # pragma: no cover - asserted below
            errors.append(error)

    first = threading.Thread(
        target=publish,
        args=(101, "2026-08-27T12:00:01Z"),
    )
    second = threading.Thread(
        target=publish,
        args=(102, "2026-08-27T12:00:02Z"),
    )
    first.start()
    assert first_append_entered.wait(timeout=0.75)
    second.start()

    try:
        time.sleep(0.05)
        assert second.is_alive()
    finally:
        release_first_append.set()
        first.join(timeout=0.75)
        second.join(timeout=0.75)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    batch = scheduler.run_due()
    assert [event.payload["price"] for event in batch.market_events] == [
        101.0,
        102.0,
    ]
    assert manager._market_cache["CONTRACT-A"]["price"] == 102.0
    scheduler.stop()


def test_fifo_overflow_replaces_backlog_and_resets_hold_before_newest_tick() -> None:
    manager = FakeStealthManager(
        (_pending_price_order("sid-pending", "CONTRACT-A"),)
    )
    scheduler = StealthEventDeadlineScheduler(market_queue_limit=2)
    bridge = bridge_module.StealthOrderBridge(
        manager,
        order_engine=None,
        scheduler=scheduler,
    )
    bridge._decisions_ready.set()

    try:
        for price in (101, 102, 90):
            bridge.publish_ticker_update(
                "CONTRACT-A",
                {
                    "price": str(price),
                    "best_bid": str(price - 1),
                    "best_ask": str(price + 1),
                },
            )

        assert scheduler.pending_market_event_count == 1

        batch = scheduler.run_due(on_market_event=bridge._handle_market_event)

        assert len(batch.market_events) == 1
        recovery_event = batch.market_events[0]
        assert recovery_event.product_id == "CONTRACT-A"
        assert recovery_event.payload["price"] == 90.0
        assert recovery_event.continuity_reset is True
        assert manager.evaluated_market_prices == [90.0]

        order = manager.in_memory_orders["sid-pending"]
        assert order["status"] == StealthOrderStatus.HIDDEN.value
        assert order["condition_first_met_at"] is None
        assert order["condition_confirmed_at"] is None

        reset_index = next(
            index
            for index, action in enumerate(manager.actions)
            if action[:2] == ("reset", "sid-pending")
        )
        evaluation_index = manager.actions.index(("evaluate", "sid-pending"))
        assert reset_index < evaluation_index
    finally:
        scheduler.stop()


def test_fifo_overflow_resets_every_product_whose_events_are_discarded() -> None:
    manager = FakeStealthManager(
        (
            _pending_price_order("sid-a", "CONTRACT-A"),
            _pending_price_order("sid-b", "CONTRACT-B"),
        )
    )
    scheduler = StealthEventDeadlineScheduler(market_queue_limit=2)
    bridge = bridge_module.StealthOrderBridge(
        manager,
        order_engine=None,
        scheduler=scheduler,
    )
    bridge._decisions_ready.set()

    try:
        bridge.publish_ticker_update(
            "CONTRACT-B",
            {"price": "101", "best_bid": "100", "best_ask": "102"},
        )
        bridge.publish_ticker_update(
            "CONTRACT-A",
            {"price": "102", "best_bid": "101", "best_ask": "103"},
        )
        bridge.publish_ticker_update(
            "CONTRACT-A",
            {"price": "90", "best_bid": "89", "best_ask": "91"},
        )

        batch = scheduler.run_due(on_market_event=bridge._handle_market_event)

        assert len(batch.market_events) == 1
        recovery_event = batch.market_events[0]
        assert recovery_event.product_id == "CONTRACT-A"
        assert recovery_event.payload["price"] == 90.0
        assert recovery_event.continuity_reset is True
        assert recovery_event.continuity_reset_counts == (
            ("CONTRACT-B", 1),
            ("CONTRACT-A", 1),
        )
        assert manager.in_memory_orders["sid-a"]["status"] == (
            StealthOrderStatus.HIDDEN.value
        )
        assert manager.in_memory_orders["sid-b"]["status"] == (
            StealthOrderStatus.HIDDEN.value
        )
        reset_ids = [
            action[1] for action in manager.actions if action[0] == "reset"
        ]
        assert reset_ids == ["sid-b", "sid-a"]
    finally:
        scheduler.stop()


def test_one_order_evaluation_error_does_not_suppress_same_product_peer() -> None:
    manager = FakeStealthManager(
        (
            _time_delay_order("sid-bad", "CONTRACT-A"),
            _time_delay_order("sid-peer", "CONTRACT-A"),
        )
    )
    manager.raise_on_evaluation.add("sid-bad")
    bridge, scheduler = _new_bridge(manager)

    try:
        bridge.publish_ticker_update(
            "CONTRACT-A",
            {"price": "101", "best_bid": "100", "best_ask": "102"},
        )

        batch = scheduler.run_due(on_market_event=bridge._handle_market_event)

        assert len(batch.market_events) == 1
        assert manager.evaluated_ids == ["sid-bad", "sid-peer"]
        assert manager.evaluated_market_prices == [101.0, 101.0]
        assert manager.evaluation_event.is_set()
        assert scheduler.worker_error is None
    finally:
        scheduler.stop()


def test_continuous_evaluation_error_resets_hold_without_suppressing_peer() -> None:
    manager = FakeStealthManager(
        (
            _pending_price_order("sid-bad", "CONTRACT-A"),
            _pending_price_order("sid-peer", "CONTRACT-A"),
        )
    )
    manager.raise_on_evaluation.add("sid-bad")
    bridge, scheduler = _new_bridge(manager)

    try:
        bridge.publish_ticker_update(
            "CONTRACT-A",
            {"price": "101", "best_bid": "100", "best_ask": "102"},
            event_time="2026-08-27T12:00:00Z",
        )

        batch = scheduler.run_due(on_market_event=bridge._handle_market_event)

        assert len(batch.market_events) == 1
        assert manager.evaluated_ids == ["sid-bad", "sid-peer"]
        assert manager.in_memory_orders["sid-bad"]["status"] == (
            StealthOrderStatus.HIDDEN.value
        )
        assert manager.in_memory_orders["sid-bad"]["condition_first_met_at"] is None
        assert (
            "reset",
            "sid-bad",
            "Continuous condition evaluation failed for ordered market event: "
            "RuntimeError: synthetic evaluation failure: sid-bad",
        ) in manager.actions
        assert manager.in_memory_orders["sid-peer"]["status"] == (
            StealthOrderStatus.PENDING.value
        )
    finally:
        scheduler.stop()


def test_continuity_reset_persistence_failure_resets_peers_then_latches(
    monkeypatch,
) -> None:
    manager = FakeStealthManager(
        (
            _pending_price_order("sid-fails", "CONTRACT-A"),
            _pending_price_order("sid-peer", "CONTRACT-A"),
        )
    )
    bridge, scheduler = _new_bridge(manager)
    bridge.running = True
    bridge._decisions_ready.set()
    controller = MutableRuntimeController(EngineState.RUNNING)
    monkeypatch.setattr(
        bridge_module,
        "get_runtime_controller",
        lambda: controller,
    )
    attempted_resets = []
    original_reset = manager.reset_continuous_condition

    def reset_with_one_persistence_failure(stealth_order_id, **kwargs):
        attempted_resets.append(stealth_order_id)
        if stealth_order_id == "sid-fails":
            raise RuntimeError("synthetic reset persistence failure")
        return original_reset(stealth_order_id, **kwargs)

    manager.reset_continuous_condition = reset_with_one_persistence_failure
    event = MarketEvent(
        sequence=1,
        product_id="CONTRACT-A",
        payload={
            "product_id": "CONTRACT-A",
            "price": 101.0,
            "bid": 100.0,
            "ask": 102.0,
            "source": "ticker",
            "time": datetime(2026, 8, 27, 12, 0, 0),
        },
        published_monotonic=time.monotonic(),
        contains_market_snapshot=True,
        continuity_reset=True,
        discarded_event_count=1,
        continuity_reset_counts=(("CONTRACT-A", 1),),
    )

    try:
        with pytest.raises(
            RuntimeError,
            match="synthetic reset persistence failure",
        ):
            bridge._handle_market_event(event)

        assert attempted_resets == ["sid-fails", "sid-peer"]
        assert manager.in_memory_orders["sid-peer"]["status"] == (
            StealthOrderStatus.HIDDEN.value
        )
        assert manager.evaluated_ids == []
        assert scheduler.stopped is True
        assert bridge._decisions_ready.is_set() is False
        assert controller.pause_requests == 1
        assert controller.state == EngineState.PAUSED
    finally:
        bridge.stop()


def test_websocket_execution_update_waits_for_continuity_reset_ownership() -> None:
    manager = FakeStealthManager(
        (_pending_price_order("sid-a", "CONTRACT-A"),)
    )
    bridge, scheduler = _new_bridge(manager)
    reset_entered = threading.Event()
    release_reset = threading.Event()
    execution_entered = threading.Event()
    execution_finished = threading.Event()
    original_reset = manager.reset_continuous_condition

    def blocking_reset(stealth_order_id, **kwargs):
        reset_entered.set()
        assert release_reset.wait(timeout=1)
        return original_reset(stealth_order_id, **kwargs)

    def update_execution(
        stealth_order_id,
        executed_size,
        order_status,
    ):
        execution_entered.set()
        order = manager.in_memory_orders[stealth_order_id]
        order["executed_size"] = executed_size
        order["status"] = order_status

    manager.reset_continuous_condition = blocking_reset
    manager.update_execution = update_execution
    event = MarketEvent(
        sequence=1,
        product_id="CONTRACT-A",
        payload={"source": "continuity_reset", "time": datetime.utcnow()},
        published_monotonic=time.monotonic(),
        contains_market_snapshot=False,
        continuity_reset=True,
        discarded_event_count=1,
        continuity_reset_counts=(("CONTRACT-A", 1),),
    )

    reset_thread = threading.Thread(
        target=bridge._handle_market_event,
        args=(event,),
    )

    def publish_execution():
        bridge.update_execution(
            "sid-a",
            executed_size=1.0,
            order_status=StealthOrderStatus.EXECUTED.value,
        )
        execution_finished.set()

    execution_thread = threading.Thread(target=publish_execution)

    try:
        reset_thread.start()
        assert reset_entered.wait(timeout=1)
        execution_thread.start()
        assert execution_entered.wait(timeout=0.1) is False

        release_reset.set()
        reset_thread.join(timeout=1)
        execution_thread.join(timeout=1)

        assert reset_thread.is_alive() is False
        assert execution_thread.is_alive() is False
        assert execution_finished.is_set()
        assert manager.in_memory_orders["sid-a"]["status"] == (
            StealthOrderStatus.EXECUTED.value
        )
    finally:
        release_reset.set()
        reset_thread.join(timeout=1)
        execution_thread.join(timeout=1)
        scheduler.stop()


def test_mutable_compatibility_condition_is_not_also_evaluated_per_ticker() -> None:
    order = _time_delay_order("sid-volume", "CONTRACT-A")
    order["reveal_condition_type"] = (
        RevealConditionType.CUMULATIVE_VOLUME.value
    )
    order["reveal_condition_json"] = {
        "type": RevealConditionType.CUMULATIVE_VOLUME.value,
        "product_id": "CONTRACT-A",
        "price_level": 100.0,
        "volume_threshold": 10.0,
        "lookback_seconds": 30,
    }
    manager = FakeStealthManager((order,))
    bridge, scheduler = _new_bridge(manager)

    try:
        bridge._handle_market_event(
            bridge_module.MarketEvent(
                sequence=1,
                product_id="CONTRACT-A",
                payload={
                    "product_id": "CONTRACT-A",
                    "price": 100.0,
                    "trade_volume": 1.0,
                    "time": datetime.utcnow(),
                    "source": "ticker",
                },
                published_monotonic=time.monotonic(),
            )
        )

        assert manager.evaluated_ids == []

        generation = scheduler.schedule_after(
            "sid-volume",
            StealthWakePurpose.COMPATIBILITY_RECHECK,
            0,
        )
        bridge._handle_deadline_wake(
            DeadlineWake(
                stealth_order_id="sid-volume",
                purpose=StealthWakePurpose.COMPATIBILITY_RECHECK,
                generation=generation,
                deadline_monotonic=time.monotonic(),
            )
        )

        assert manager.evaluated_ids == ["sid-volume"]
    finally:
        scheduler.stop()


def test_stopped_scheduler_pauses_originating_work_once_without_tick_log_loop(
    monkeypatch,
) -> None:
    manager = FakeStealthManager()
    bridge, scheduler = _new_bridge(manager)
    controller = MockRuntimeController()
    monkeypatch.setattr(
        bridge_module,
        "get_runtime_controller",
        lambda: controller,
    )
    bridge.running = True
    scheduler.stop()

    bridge.publish_ticker_update(
        "CONTRACT-A",
        {"price": "101", "best_bid": "100", "best_ask": "102"},
    )
    bridge.publish_ticker_update(
        "CONTRACT-A",
        {"price": "102", "best_bid": "101", "best_ask": "103"},
    )

    assert controller.pause_requests == 1
    assert bridge._scheduler_failure_reported is True
    bridge.stop()


def test_runtime_schedule_rebuild_failure_pauses_originating_work(
    monkeypatch,
) -> None:
    manager = FakeStealthManager()
    bridge, scheduler = _new_bridge(manager)
    controller = MockRuntimeController()
    monkeypatch.setattr(
        bridge_module,
        "get_runtime_controller",
        lambda: controller,
    )
    monkeypatch.setattr(
        bridge,
        "_schedule_order",
        lambda _stealth_order_id: (_ for _ in ()).throw(
            ValueError("malformed runtime condition")
        ),
    )
    bridge.running = True
    bridge._decisions_ready.set()

    bridge._handle_order_schedule_change("sid-malformed")

    assert controller.pause_requests == 1
    assert bridge._scheduler_failure_reported is True
    assert bridge._decisions_ready.is_set() is False
    assert scheduler.stopped is True
    bridge.stop()


def test_decisions_wait_for_activation_then_evaluate_only_event_product() -> None:
    manager = FakeStealthManager(
        (
            _time_delay_order("sid-a", "CONTRACT-A"),
            _time_delay_order("sid-b", "CONTRACT-B"),
        )
    )
    bridge, _scheduler = _new_bridge(manager)

    try:
        bridge.start()
        bridge.publish_ticker_update(
            "CONTRACT-A",
            {"price": "101", "best_bid": "100", "best_ask": "102"},
        )

        assert not manager.evaluation_event.wait(timeout=0.05)
        assert manager.evaluated_ids == []

        bridge.activate_decisions()

        assert manager.evaluation_event.wait(timeout=0.75)
        bridge.stop()

        assert manager.evaluated_ids == ["sid-a"]
        assert "CONTRACT-A" in manager.snapshot_products
        assert manager.actions[0] == ("load", None)
        assert manager.actions.index(("load", None)) < manager.actions.index(
            ("evaluate", "sid-a")
        )
    finally:
        bridge.stop()


def test_failed_or_partial_hydration_blocks_bridge_start() -> None:
    manager = FakeStealthManager()
    manager._last_hydration_complete = False
    bridge, scheduler = _new_bridge(manager)

    with pytest.raises(
        RuntimeError,
        match="database hydration did not complete",
    ):
        bridge.start()

    assert bridge.running is False
    assert bridge.reconciliation_thread is None
    assert manager.schedule_change_callback is None
    scheduler.stop()


def test_activation_does_not_start_worker_if_any_order_cannot_be_scheduled(
    monkeypatch,
) -> None:
    manager = FakeStealthManager(
        (_time_delay_order("sid-a", "CONTRACT-A"),)
    )
    bridge, scheduler = _new_bridge(manager)

    try:
        bridge.start()

        def fail_schedule(*_args, **_kwargs):
            raise RuntimeError("synthetic schedule failure")

        monkeypatch.setattr(scheduler, "schedule_after", fail_schedule)

        with pytest.raises(RuntimeError, match="synthetic schedule failure"):
            bridge.activate_decisions()

        assert bridge._decisions_ready.is_set() is False
        assert bridge.evaluation_thread is None
    finally:
        bridge.stop()


def test_activation_rejects_fixed_time_order_without_creation_timestamp() -> None:
    malformed = _time_delay_order("sid-a", "CONTRACT-A")
    malformed["created_at"] = None
    manager = FakeStealthManager((malformed,))
    bridge, _scheduler = _new_bridge(manager)

    try:
        bridge.start()

        with pytest.raises(
            ValueError,
            match="Invalid time_delay condition",
        ):
            bridge.activate_decisions()

        assert bridge._decisions_ready.is_set() is False
        assert bridge.evaluation_thread is None
    finally:
        bridge.stop()


def test_activation_rejects_jittered_time_order_without_creation_timestamp() -> None:
    malformed = _time_delay_order("sid-a", "CONTRACT-A")
    malformed["created_at"] = None
    malformed["reveal_condition_json"]["jitter_seconds"] = 2
    manager = FakeStealthManager((malformed,))
    bridge, _scheduler = _new_bridge(manager)

    try:
        bridge.start()

        with pytest.raises(
            ValueError,
            match="Invalid time_delay condition",
        ):
            bridge.activate_decisions()
    finally:
        bridge.stop()


def test_activation_rejects_malformed_continuous_condition() -> None:
    malformed = _pending_price_order("sid-a", "CONTRACT-A")
    malformed["reveal_condition_json"].pop("price_threshold")
    manager = FakeStealthManager((malformed,))
    bridge, _scheduler = _new_bridge(manager)

    try:
        bridge.start()

        with pytest.raises(
            ValueError,
            match="Invalid price condition",
        ):
            bridge.activate_decisions()
    finally:
        bridge.stop()


@pytest.mark.parametrize(
    ("condition_type", "condition_config"),
    (
        (
            RevealConditionType.CUMULATIVE_VOLUME.value,
            {
                "product_id": "CONTRACT-A",
                "price_level": 100,
                # volume_threshold is required.
            },
        ),
        (
            RevealConditionType.PRODUCT_RATIO.value,
            {
                "product_a": "CONTRACT-A",
                "product_b": "CONTRACT-B",
                "ratio_threshold": "not-a-number",
            },
        ),
        (
            RevealConditionType.COMPOSITE.value,
            {"operator": "AND", "conditions": ["not-an-object"]},
        ),
    ),
)
def test_activation_rejects_malformed_compatibility_condition(
    condition_type,
    condition_config,
) -> None:
    malformed = _time_delay_order("sid-a", "CONTRACT-A")
    malformed["reveal_condition_type"] = condition_type
    malformed["reveal_condition_json"] = condition_config
    manager = FakeStealthManager((malformed,))
    bridge, _scheduler = _new_bridge(manager)

    try:
        bridge.start()

        with pytest.raises(
            ValueError,
            match=f"Invalid {condition_type} condition",
        ):
            bridge.activate_decisions()

        assert bridge._decisions_ready.is_set() is False
        assert bridge.evaluation_thread is None
    finally:
        bridge.stop()


def test_scheduler_failure_during_activation_clears_readiness_and_pauses(
    monkeypatch,
) -> None:
    manager = FakeStealthManager()
    bridge, scheduler = _new_bridge(manager)
    controller = MutableRuntimeController()
    monkeypatch.setattr(
        bridge_module,
        "get_runtime_controller",
        lambda: controller,
    )

    try:
        bridge.start()

        def broken_clock() -> float:
            raise RuntimeError("synthetic scheduler failure")

        scheduler._clock = broken_clock
        original_start = scheduler.start

        def start_after_worker_failure(**kwargs):
            worker = original_start(**kwargs)
            deadline = time.monotonic() + 0.75
            while scheduler.worker_error is None and time.monotonic() < deadline:
                time.sleep(0.005)
            return worker

        monkeypatch.setattr(scheduler, "start", start_after_worker_failure)

        with pytest.raises(
            RuntimeError,
            match="failed during activation",
        ):
            bridge.activate_decisions()

        deadline = time.monotonic() + 0.75
        while controller.pause_requests == 0 and time.monotonic() < deadline:
            time.sleep(0.005)

        assert controller.pause_requests == 1
        assert bridge._scheduler_failure_reported is True
        assert bridge._decisions_ready.is_set() is False
        assert isinstance(scheduler.worker_error, RuntimeError)
    finally:
        bridge.stop()


def test_later_scheduler_death_clears_readiness_and_repauses_after_resume(
    monkeypatch,
) -> None:
    manager = FakeStealthManager()
    bridge, scheduler = _new_bridge(manager)
    controller = MutableRuntimeController()
    monkeypatch.setattr(
        bridge_module,
        "get_runtime_controller",
        lambda: controller,
    )

    try:
        bridge.start()
        bridge.activate_decisions()
        assert bridge._decisions_ready.is_set() is True

        def broken_clock() -> float:
            raise RuntimeError("synthetic later scheduler failure")

        scheduler._clock = broken_clock
        with scheduler._condition:
            scheduler._condition.notify_all()

        deadline = time.monotonic() + 0.75
        while controller.pause_requests == 0 and time.monotonic() < deadline:
            time.sleep(0.005)

        assert controller.pause_requests == 1
        assert controller.state == EngineState.PAUSED
        assert bridge._decisions_ready.is_set() is False
        assert isinstance(scheduler.worker_error, RuntimeError)

        controller.state = EngineState.RUNNING
        bridge.publish_ticker_update(
            "CONTRACT-A",
            {"price": "101", "best_bid": "100", "best_ask": "102"},
        )

        assert controller.pause_requests == 2
        assert controller.state == EngineState.PAUSED
        assert bridge._decisions_ready.is_set() is False
    finally:
        bridge.stop()


def test_schedule_change_reschedules_only_the_named_active_order() -> None:
    manager = FakeStealthManager(
        (
            _time_delay_order("sid-a", "CONTRACT-A", delay_seconds=60),
            _time_delay_order("sid-b", "CONTRACT-B", delay_seconds=60),
        )
    )
    bridge, scheduler = _new_bridge(manager)

    try:
        bridge.start()
        assert manager.schedule_change_callback is not None

        sid_b_generation = scheduler.schedule_after(
            "sid-b", StealthWakePurpose.TIME_DELAY, 600
        )

        manager.schedule_change_callback("sid-a")
        first_sid_a_generation = scheduler.current_generation(
            "sid-a", StealthWakePurpose.TIME_DELAY
        )

        manager.in_memory_orders["sid-a"]["reveal_condition_json"][
            "delay_seconds"
        ] = 120
        manager.schedule_change_callback("sid-a")
        second_sid_a_generation = scheduler.current_generation(
            "sid-a", StealthWakePurpose.TIME_DELAY
        )

        assert first_sid_a_generation > 0
        assert second_sid_a_generation > first_sid_a_generation
        assert scheduler.active_deadline_count == 2
        assert scheduler.current_generation(
            "sid-b", StealthWakePurpose.TIME_DELAY
        ) == sid_b_generation
    finally:
        bridge.stop()


def test_frequent_market_events_do_not_postpone_retry_or_anchor_deadlines() -> None:
    triggered = _time_delay_order(
        "sid-triggered",
        "CONTRACT-A",
        status=StealthOrderStatus.TRIGGERED,
    )
    anchored = _time_delay_order("sid-anchor", "CONTRACT-A")
    anchored["anchor_repricing_policy_json"] = {
        "enabled": True,
        "target_distance": 0.001,
    }
    anchored["anchor_repricing_state_json"] = {
        "next_reprice_at": datetime.utcnow().replace(microsecond=0)
    }
    manager = FakeStealthManager((triggered, anchored))
    bridge, scheduler = _new_bridge(manager)

    try:
        bridge.start()
        manager.schedule_change_callback("sid-triggered")
        manager.schedule_change_callback("sid-anchor")
        admission_generation = scheduler.current_generation(
            "sid-triggered",
            StealthWakePurpose.ADMISSION_RETRY,
        )
        anchor_generation = scheduler.current_generation(
            "sid-anchor",
            StealthWakePurpose.ANCHOR_REPRICE,
        )

        for price in range(101, 121):
            bridge._handle_market_event(
                bridge_module.MarketEvent(
                    sequence=price,
                    product_id="CONTRACT-A",
                    payload={
                        "product_id": "CONTRACT-A",
                        "price": float(price),
                        "bid": float(price - 1),
                        "ask": float(price + 1),
                        "time": datetime.utcnow(),
                        "source": "ticker",
                    },
                    published_monotonic=time.monotonic(),
                )
            )

        assert scheduler.current_generation(
            "sid-triggered",
            StealthWakePurpose.ADMISSION_RETRY,
        ) == admission_generation
        assert scheduler.current_generation(
            "sid-anchor",
            StealthWakePurpose.ANCHOR_REPRICE,
        ) == anchor_generation
    finally:
        bridge.stop()


def test_condition_hold_deadline_waits_for_next_ordered_market_event() -> None:
    manager = FakeStealthManager(
        (_pending_price_order("sid-pending", "CONTRACT-A"),)
    )
    bridge, scheduler = _new_bridge(manager)

    generation = scheduler.schedule_after(
        "sid-pending",
        StealthWakePurpose.CONDITION_HOLD,
        0,
    )
    wake = DeadlineWake(
        stealth_order_id="sid-pending",
        purpose=StealthWakePurpose.CONDITION_HOLD,
        generation=generation,
        deadline_monotonic=time.monotonic(),
    )

    bridge._handle_deadline_wake(wake)

    assert manager.evaluated_ids == []
    assert (
        manager.in_memory_orders["sid-pending"]["status"]
        == StealthOrderStatus.PENDING.value
    )
    scheduler.stop()


def test_captured_stale_deadline_generation_is_ignored() -> None:
    manager = FakeStealthManager(
        (_time_delay_order("sid-a", "CONTRACT-A"),)
    )
    bridge, scheduler = _new_bridge(manager)

    old_generation = scheduler.schedule_after(
        "sid-a",
        StealthWakePurpose.TIME_DELAY,
        0,
    )
    scheduler.schedule_after(
        "sid-a",
        StealthWakePurpose.TIME_DELAY,
        60,
    )
    bridge._handle_deadline_wake(
        DeadlineWake(
            stealth_order_id="sid-a",
            purpose=StealthWakePurpose.TIME_DELAY,
            generation=old_generation,
            deadline_monotonic=time.monotonic(),
        )
    )
    assert manager.evaluated_ids == []
    scheduler.stop()


def test_anchor_deadline_waits_for_live_ticker_then_reschedules() -> None:
    anchored = _time_delay_order("sid-anchor", "CONTRACT-A")
    anchored["anchor_repricing_policy_json"] = {
        "enabled": True,
        "target_distance": 0.001,
    }
    anchored["anchor_repricing_state_json"] = {
        "next_reprice_at": datetime.utcnow(),
    }
    manager = FakeStealthManager((anchored,))
    bridge, scheduler = _new_bridge(manager)
    bridge._decisions_ready.set()

    generation = scheduler.schedule_after(
        "sid-anchor",
        StealthWakePurpose.ANCHOR_REPRICE,
        0,
    )
    bridge._handle_deadline_wake(
        DeadlineWake(
            stealth_order_id="sid-anchor",
            purpose=StealthWakePurpose.ANCHOR_REPRICE,
            generation=generation,
            deadline_monotonic=time.monotonic(),
        )
    )

    # Elapsed time alone cannot execute manager/REST/database work.
    assert manager.anchor_calls == []

    bridge.process_due_anchor_repricing(
        "CONTRACT-A",
        {"price": "101", "best_bid": "100", "best_ask": "102"},
    )

    assert len(manager.anchor_calls) == 1
    product_id, stealth_order_ids, market_data = manager.anchor_calls[0]
    assert product_id == "CONTRACT-A"
    assert stealth_order_ids == ("sid-anchor",)
    assert market_data["price"] == 101.0
    assert market_data["source"] == "ticker"
    assert scheduler.current_generation(
        "sid-anchor",
        StealthWakePurpose.ANCHOR_REPRICE,
    ) > generation
    assert scheduler.active_deadline_count == 1
    scheduler.stop()


def test_pre_activation_ticker_cannot_claim_due_anchor(monkeypatch) -> None:
    clock = MutableMonotonicClock(100.0)
    anchored = _time_delay_order("sid-anchor", "CONTRACT-A")
    manager = FakeStealthManager((anchored,))
    scheduler = StealthEventDeadlineScheduler(clock=clock)
    bridge = bridge_module.StealthOrderBridge(
        manager,
        order_engine=None,
        scheduler=scheduler,
    )
    controller = MutableRuntimeController(EngineState.RUNNING)
    monkeypatch.setattr(
        bridge_module,
        "get_runtime_controller",
        lambda: controller,
    )
    generation = scheduler.schedule_deadline(
        "sid-anchor",
        StealthWakePurpose.ANCHOR_REPRICE,
        100.0,
    )
    ticker = {"price": "101", "best_bid": "100", "best_ask": "102"}

    try:
        assert bridge.process_due_anchor_repricing(
            "CONTRACT-A",
            ticker,
            received_monotonic=100.0,
        ) == 0
        assert manager.anchor_calls == []
        assert scheduler.current_generation(
            "sid-anchor",
            StealthWakePurpose.ANCHOR_REPRICE,
        ) == generation
        assert scheduler.active_deadline_count == 1

        bridge._decisions_ready.set()
        bridge.process_due_anchor_repricing(
            "CONTRACT-A",
            ticker,
            received_monotonic=100.0,
        )
        assert len(manager.anchor_calls) == 1
    finally:
        scheduler.stop()


def test_anchor_rechecks_readiness_after_sid_lock_and_retains_due_work(
    monkeypatch,
) -> None:
    anchored = _time_delay_order("sid-anchor", "CONTRACT-A")
    anchored["anchor_repricing_policy_json"] = {
        "enabled": True,
        "target_distance": 0.001,
    }
    manager = FakeStealthManager((anchored,))
    bridge, scheduler = _new_bridge(manager)
    controller = MutableRuntimeController(EngineState.RUNNING)
    monkeypatch.setattr(
        bridge_module,
        "get_runtime_controller",
        lambda: controller,
    )
    generation = scheduler.schedule_after(
        "sid-anchor",
        StealthWakePurpose.ANCHOR_REPRICE,
        0,
    )
    deadline_monotonic = time.monotonic()
    bridge._handle_deadline_wake(
        DeadlineWake(
            stealth_order_id="sid-anchor",
            purpose=StealthWakePurpose.ANCHOR_REPRICE,
            generation=generation,
            deadline_monotonic=deadline_monotonic,
        )
    )

    action_lock = bridge._get_order_action_lock("sid-anchor")
    action_lock.acquire()
    reached_action_lock = threading.Event()
    original_get_lock = bridge._get_order_action_lock

    def signaling_get_lock(stealth_order_id):
        reached_action_lock.set()
        return original_get_lock(stealth_order_id)

    monkeypatch.setattr(bridge, "_get_order_action_lock", signaling_get_lock)
    ticker = {"price": "101", "best_bid": "100", "best_ask": "102"}
    worker = threading.Thread(
        target=bridge.process_due_anchor_repricing,
        args=("CONTRACT-A", ticker),
    )
    worker.start()

    try:
        assert reached_action_lock.wait(timeout=0.75)
        bridge._decisions_ready.clear()
    finally:
        action_lock.release()
    worker.join(timeout=0.75)

    assert not worker.is_alive()
    assert manager.anchor_calls == []
    assert "sid-anchor" in bridge._anchor_due_generations

    bridge._decisions_ready.set()
    bridge.process_due_anchor_repricing("CONTRACT-A", ticker)

    assert len(manager.anchor_calls) == 1
    assert manager.anchor_calls[0][1] == ("sid-anchor",)
    scheduler.stop()


def test_pre_deadline_ticker_cannot_claim_anchor_after_handler_delay(
    monkeypatch,
) -> None:
    clock = MutableMonotonicClock(100.0)
    anchored = _time_delay_order("sid-anchor", "CONTRACT-A")
    manager = FakeStealthManager((anchored,))
    scheduler = StealthEventDeadlineScheduler(clock=clock)
    bridge = bridge_module.StealthOrderBridge(
        manager,
        order_engine=None,
        scheduler=scheduler,
    )
    bridge._decisions_ready.set()
    controller = MutableRuntimeController(EngineState.RUNNING)
    monkeypatch.setattr(
        bridge_module,
        "get_runtime_controller",
        lambda: controller,
    )
    scheduler.schedule_deadline(
        "sid-anchor",
        StealthWakePurpose.ANCHOR_REPRICE,
        101.0,
    )
    ticker = {"price": "101", "best_bid": "100", "best_ask": "102"}

    try:
        # Simulate dashboard/metrics work advancing the host clock after this
        # ticker was received but before anchor processing reached the bridge.
        clock.value = 102.0
        assert bridge.process_due_anchor_repricing(
            "CONTRACT-A",
            ticker,
            received_monotonic=100.0,
        ) == 0
        assert manager.anchor_calls == []
        assert scheduler.active_deadline_count == 1

        bridge.process_due_anchor_repricing(
            "CONTRACT-A",
            ticker,
            received_monotonic=101.0,
        )
        assert len(manager.anchor_calls) == 1
    finally:
        scheduler.stop()


def test_worker_anchor_handoff_retains_original_deadline_eligibility(
    monkeypatch,
) -> None:
    clock = MutableMonotonicClock(102.0)
    anchored = _time_delay_order("sid-anchor", "CONTRACT-A")
    manager = FakeStealthManager((anchored,))
    scheduler = StealthEventDeadlineScheduler(clock=clock)
    bridge = bridge_module.StealthOrderBridge(
        manager,
        order_engine=None,
        scheduler=scheduler,
    )
    bridge._decisions_ready.set()
    controller = MutableRuntimeController(EngineState.RUNNING)
    monkeypatch.setattr(
        bridge_module,
        "get_runtime_controller",
        lambda: controller,
    )
    generation = scheduler.schedule_deadline(
        "sid-anchor",
        StealthWakePurpose.ANCHOR_REPRICE,
        101.0,
    )
    bridge._handle_deadline_wake(
        DeadlineWake(
            stealth_order_id="sid-anchor",
            purpose=StealthWakePurpose.ANCHOR_REPRICE,
            generation=generation,
            deadline_monotonic=101.0,
        )
    )
    handoff = bridge._anchor_due_generations["sid-anchor"]
    ticker = {"price": "101", "best_bid": "100", "best_ask": "102"}

    try:
        bridge.process_due_anchor_repricing(
            "CONTRACT-A",
            ticker,
            received_monotonic=100.0,
        )
        assert manager.anchor_calls == []
        assert bridge._anchor_due_generations == {"sid-anchor": handoff}

        bridge.process_due_anchor_repricing(
            "CONTRACT-A",
            ticker,
            received_monotonic=101.0,
        )
        assert len(manager.anchor_calls) == 1
        assert bridge._anchor_due_generations == {}
    finally:
        scheduler.stop()


def test_first_live_ticker_claims_anchor_wake_captured_by_worker(
    monkeypatch,
) -> None:
    anchored = _time_delay_order("sid-anchor", "CONTRACT-A")
    anchored["anchor_repricing_policy_json"] = {
        "enabled": True,
        "target_distance": 0.001,
    }
    anchored["anchor_repricing_state_json"] = {
        "next_reprice_at": datetime.utcnow(),
    }
    manager = FakeStealthManager((anchored,))
    bridge, scheduler = _new_bridge(manager)
    bridge._decisions_ready.set()
    controller = MutableRuntimeController(EngineState.RUNNING)
    monkeypatch.setattr(
        bridge_module,
        "get_runtime_controller",
        lambda: controller,
    )
    worker_captured = threading.Event()
    release_worker_callback = threading.Event()
    callback_finished = threading.Event()

    def delayed_deadline_callback(wake: DeadlineWake) -> None:
        worker_captured.set()
        assert release_worker_callback.wait(timeout=0.75)
        bridge._handle_deadline_wake(wake)
        callback_finished.set()

    scheduler.start(
        on_market_event=lambda _event: None,
        on_deadline=delayed_deadline_callback,
    )

    try:
        scheduler.schedule_after(
            "sid-anchor",
            StealthWakePurpose.ANCHOR_REPRICE,
            0,
        )
        assert worker_captured.wait(timeout=0.75)

        # This is the only ticker delivered after the deadline.  It must not
        # miss merely because the scheduler worker has captured, but not yet
        # dispatched, the corresponding wake.
        bridge.process_due_anchor_repricing(
            "CONTRACT-A",
            {"price": "101", "best_bid": "100", "best_ask": "102"},
        )

        assert len(manager.anchor_calls) == 1
        assert manager.anchor_calls[0][1] == ("sid-anchor",)

        release_worker_callback.set()
        assert callback_finished.wait(timeout=0.75)
        assert len(manager.anchor_calls) == 1
        assert bridge._anchor_due_generations == {}
    finally:
        release_worker_callback.set()
        scheduler.stop(join_timeout=0.75)


def test_condition_schedule_rebuild_has_no_anchor_handoff_gap(
    monkeypatch,
) -> None:
    anchored = _time_delay_order("sid-anchor", "CONTRACT-A")
    anchored["anchor_repricing_policy_json"] = {
        "enabled": True,
        "target_distance": 0.001,
    }
    anchored["anchor_repricing_state_json"] = {
        "next_reprice_at": datetime.utcnow(),
    }
    manager = FakeStealthManager((anchored,))
    bridge, scheduler = _new_bridge(manager)
    bridge._decisions_ready.set()
    controller = MutableRuntimeController(EngineState.RUNNING)
    monkeypatch.setattr(
        bridge_module,
        "get_runtime_controller",
        lambda: controller,
    )
    bridge._schedule_order("sid-anchor")

    condition_rebuild_entered = threading.Event()
    release_condition_rebuild = threading.Event()
    original_schedule_condition = bridge._schedule_condition_wake

    def delayed_condition_rebuild(*args, **kwargs) -> None:
        condition_rebuild_entered.set()
        assert release_condition_rebuild.wait(timeout=0.75)
        original_schedule_condition(*args, **kwargs)

    monkeypatch.setattr(
        bridge,
        "_schedule_condition_wake",
        delayed_condition_rebuild,
    )
    rebuild_thread = threading.Thread(
        target=bridge._schedule_order,
        args=("sid-anchor",),
    )
    rebuild_thread.start()

    try:
        assert condition_rebuild_entered.wait(timeout=0.75)

        # Rebuilding an unrelated condition lane must not temporarily remove
        # the due anchor deadline seen by this sole live ticker.
        bridge.process_due_anchor_repricing(
            "CONTRACT-A",
            {"price": "101", "best_bid": "100", "best_ask": "102"},
        )

        assert len(manager.anchor_calls) == 1
        assert manager.anchor_calls[0][1] == ("sid-anchor",)
    finally:
        release_condition_rebuild.set()
        rebuild_thread.join(timeout=0.75)
        scheduler.stop()

    assert not rebuild_thread.is_alive()


def test_due_anchor_is_retained_while_paused_then_runs_once_after_resume(
    monkeypatch,
) -> None:
    anchored = _time_delay_order("sid-anchor", "CONTRACT-A")
    anchored["anchor_repricing_policy_json"] = {
        "enabled": True,
        "target_distance": 0.001,
    }
    anchored["anchor_repricing_state_json"] = {
        "next_reprice_at": datetime.utcnow(),
    }
    manager = FakeStealthManager((anchored,))
    bridge, scheduler = _new_bridge(manager)
    bridge._decisions_ready.set()
    controller = MutableRuntimeController(EngineState.PAUSED)
    monkeypatch.setattr(
        bridge_module,
        "get_runtime_controller",
        lambda: controller,
    )

    generation = scheduler.schedule_after(
        "sid-anchor",
        StealthWakePurpose.ANCHOR_REPRICE,
        0,
    )
    bridge._handle_deadline_wake(
        DeadlineWake(
            stealth_order_id="sid-anchor",
            purpose=StealthWakePurpose.ANCHOR_REPRICE,
            generation=generation,
            deadline_monotonic=time.monotonic(),
        )
    )
    handoff_generation = bridge._anchor_due_generations["sid-anchor"]

    ticker = {"price": "101", "best_bid": "100", "best_ask": "102"}
    assert bridge.process_due_anchor_repricing("CONTRACT-A", ticker) == 0
    assert manager.anchor_calls == []
    assert handoff_generation[0] > generation
    assert bridge._anchor_due_generations == {
        "sid-anchor": handoff_generation
    }

    controller.state = EngineState.RUNNING
    bridge.process_due_anchor_repricing("CONTRACT-A", ticker)
    bridge.process_due_anchor_repricing("CONTRACT-A", ticker)

    assert len(manager.anchor_calls) == 1
    assert bridge._anchor_due_generations == {}
    scheduler.stop()


def test_due_anchor_is_rebuilt_when_pause_wins_atomic_admission(
    monkeypatch,
) -> None:
    anchored = _time_delay_order("sid-anchor", "CONTRACT-A")
    anchored["anchor_repricing_policy_json"] = {
        "enabled": True,
        "target_distance": 0.001,
    }
    anchored["anchor_repricing_state_json"] = {
        "next_reprice_at": datetime.utcnow(),
    }
    manager = FakeStealthManager((anchored,))
    bridge, scheduler = _new_bridge(manager)
    controller = RejectAtAtomicAdmissionController()
    monkeypatch.setattr(
        bridge_module,
        "get_runtime_controller",
        lambda: controller,
    )

    generation = scheduler.schedule_after(
        "sid-anchor",
        StealthWakePurpose.ANCHOR_REPRICE,
        0,
    )
    bridge._handle_deadline_wake(
        DeadlineWake(
            stealth_order_id="sid-anchor",
            purpose=StealthWakePurpose.ANCHOR_REPRICE,
            generation=generation,
            deadline_monotonic=time.monotonic(),
        )
    )
    ticker = {"price": "101", "best_bid": "100", "best_ask": "102"}

    assert bridge.process_due_anchor_repricing("CONTRACT-A", ticker) == 0
    assert controller.state is EngineState.PAUSED
    assert manager.anchor_calls == []
    assert scheduler.current_generation(
        "sid-anchor",
        StealthWakePurpose.ANCHOR_REPRICE,
    ) > generation
    assert scheduler.active_deadline_count == 1

    controller.state = EngineState.RUNNING
    bridge.process_due_anchor_repricing("CONTRACT-A", ticker)

    assert len(manager.anchor_calls) == 1
    scheduler.stop()


def test_anchor_batch_stops_after_first_action_pauses_and_retains_peers(
    monkeypatch,
) -> None:
    orders = []
    for stealth_order_id in ("sid-a", "sid-b"):
        order = _time_delay_order(stealth_order_id, "CONTRACT-A")
        order["anchor_repricing_policy_json"] = {
            "enabled": True,
            "target_distance": 0.001,
        }
        order["anchor_repricing_state_json"] = {
            "next_reprice_at": datetime.utcnow(),
        }
        orders.append(order)

    manager = FakeStealthManager(orders)
    bridge, scheduler = _new_bridge(manager)
    bridge._decisions_ready.set()
    controller = MutableRuntimeController(EngineState.RUNNING)
    monkeypatch.setattr(
        bridge_module,
        "get_runtime_controller",
        lambda: controller,
    )
    action_ids = []

    def pause_after_first(
        _product_id,
        stealth_order_ids=None,
        market_data=None,
    ):
        del market_data
        action_ids.extend(stealth_order_ids or ())
        if len(action_ids) == 1:
            controller.request_pause()
        return 1

    manager.process_anchor_repricing_for_product = pause_after_first
    for stealth_order_id in ("sid-a", "sid-b"):
        generation = scheduler.schedule_after(
            stealth_order_id,
            StealthWakePurpose.ANCHOR_REPRICE,
            0,
        )
        bridge._handle_deadline_wake(
            DeadlineWake(
                stealth_order_id=stealth_order_id,
                purpose=StealthWakePurpose.ANCHOR_REPRICE,
                generation=generation,
                deadline_monotonic=time.monotonic(),
            )
        )

    ticker = {"price": "101", "best_bid": "100", "best_ask": "102"}

    try:
        assert bridge.process_due_anchor_repricing(
            "CONTRACT-A",
            ticker,
        ) == 1
        assert action_ids == ["sid-a"]
        assert "sid-b" in bridge._anchor_due_generations

        controller.state = EngineState.RUNNING
        assert bridge.process_due_anchor_repricing(
            "CONTRACT-A",
            ticker,
        ) == 1
        assert action_ids == ["sid-a", "sid-b"]
        assert "sid-b" not in bridge._anchor_due_generations
    finally:
        scheduler.stop()


def test_new_anchor_generation_revokes_due_handoff_before_manager_call(
    monkeypatch,
) -> None:
    anchored = _time_delay_order("sid-anchor", "CONTRACT-A")
    anchored["anchor_repricing_policy_json"] = {
        "enabled": True,
        "target_distance": 0.001,
    }
    manager = FakeStealthManager((anchored,))
    bridge, scheduler = _new_bridge(manager)
    bridge._decisions_ready.set()

    generation = scheduler.schedule_after(
        "sid-anchor",
        StealthWakePurpose.ANCHOR_REPRICE,
        0,
    )
    bridge._handle_deadline_wake(
        DeadlineWake(
            stealth_order_id="sid-anchor",
            purpose=StealthWakePurpose.ANCHOR_REPRICE,
            generation=generation,
            deadline_monotonic=time.monotonic(),
        )
    )
    handoff_generation = bridge._anchor_due_generations["sid-anchor"]

    claim_reached = threading.Event()
    allow_claim = threading.Event()
    original_invalidate = scheduler.invalidate_deadline

    def paused_invalidate(*args, **kwargs):
        if kwargs.get("expected_generation") == handoff_generation[0]:
            claim_reached.set()
            assert allow_claim.wait(timeout=0.75)
        return original_invalidate(*args, **kwargs)

    monkeypatch.setattr(scheduler, "invalidate_deadline", paused_invalidate)
    worker = threading.Thread(
        target=bridge.process_due_anchor_repricing,
        args=(
            "CONTRACT-A",
            {"price": "101", "best_bid": "100", "best_ask": "102"},
        ),
    )
    worker.start()

    assert claim_reached.wait(timeout=0.75)
    replacement_generation = scheduler.schedule_after(
        "sid-anchor",
        StealthWakePurpose.ANCHOR_REPRICE,
        60,
    )
    allow_claim.set()
    worker.join(timeout=0.75)

    assert not worker.is_alive()
    assert manager.anchor_calls == []
    assert scheduler.current_generation(
        "sid-anchor",
        StealthWakePurpose.ANCHOR_REPRICE,
    ) == replacement_generation
    assert scheduler.active_deadline_count == 1
    scheduler.stop()


def test_revealed_anchor_without_reprice_permission_has_no_anchor_wake() -> None:
    anchored = _time_delay_order(
        "sid-anchor",
        "CONTRACT-A",
        status=StealthOrderStatus.REVEALED,
    )
    anchored["anchor_repricing_policy_json"] = {
        "enabled": True,
        "allow_revealed_reprice": False,
        "target_distance": 0.001,
    }
    anchored["remaining_size"] = 0.0
    manager = FakeStealthManager((anchored,))
    bridge, scheduler = _new_bridge(manager)

    bridge._schedule_order("sid-anchor")

    assert scheduler.active_deadline_count == 0
    scheduler.stop()


def test_fully_revealed_order_with_permission_keeps_anchor_wake() -> None:
    anchored = _time_delay_order(
        "sid-anchor",
        "CONTRACT-A",
        status=StealthOrderStatus.REVEALED,
    )
    anchored["remaining_size"] = 0.0
    anchored["anchor_repricing_policy_json"] = {
        "enabled": True,
        "allow_revealed_reprice": True,
        "target_distance": 0.001,
    }
    manager = FakeStealthManager((anchored,))
    bridge, scheduler = _new_bridge(manager)

    bridge._schedule_order("sid-anchor")

    assert scheduler.active_deadline_count == 1
    scheduler.stop()


def test_manual_reprice_is_scoped_and_rebuilds_only_named_anchor_lane() -> None:
    orders = []
    for stealth_order_id in ("sid-a", "sid-b"):
        order = _time_delay_order(stealth_order_id, "CONTRACT-A")
        order["anchor_repricing_policy_json"] = {
            "enabled": True,
            "target_distance": 0.001,
        }
        order["anchor_repricing_state_json"] = {
            "next_reprice_at": datetime.utcnow(),
        }
        orders.append(order)

    manager = FakeStealthManager(orders)
    bridge, scheduler = _new_bridge(manager)
    bridge._decisions_ready.set()
    bridge._schedule_order("sid-a")
    bridge._schedule_order("sid-b")
    sid_a_generation = scheduler.current_generation(
        "sid-a",
        StealthWakePurpose.ANCHOR_REPRICE,
    )
    sid_b_generation = scheduler.current_generation(
        "sid-b",
        StealthWakePurpose.ANCHOR_REPRICE,
    )

    bridge.reprice_stealth_order_now("sid-a")

    assert manager.anchor_calls[-1][1] == ("sid-a",)
    assert scheduler.current_generation(
        "sid-a",
        StealthWakePurpose.ANCHOR_REPRICE,
    ) > sid_a_generation
    assert scheduler.current_generation(
        "sid-b",
        StealthWakePurpose.ANCHOR_REPRICE,
    ) == sid_b_generation
    scheduler.stop()


def test_due_wake_evaluates_only_its_named_stealth_order() -> None:
    manager = FakeStealthManager(
        (
            _time_delay_order("sid-a", "CONTRACT-A"),
            _time_delay_order("sid-b", "CONTRACT-B"),
        )
    )
    bridge, scheduler = _new_bridge(manager)

    try:
        bridge.start()
        bridge.activate_decisions()
        scheduler.schedule_after("sid-a", StealthWakePurpose.TIME_DELAY, 0)

        assert manager.evaluation_event.wait(timeout=0.75)
        bridge.stop()

        assert manager.evaluated_ids == ["sid-a"]
    finally:
        bridge.stop()


def test_terminal_schedule_change_invalidates_named_order_without_touching_peer() -> None:
    manager = FakeStealthManager(
        (
            _time_delay_order("sid-a", "CONTRACT-A"),
            _time_delay_order("sid-b", "CONTRACT-B"),
        )
    )
    bridge, scheduler = _new_bridge(manager)

    try:
        bridge.start()
        sid_a_generations = {
            purpose: scheduler.schedule_after("sid-a", purpose, 600)
            for purpose in StealthWakePurpose
        }
        sid_b_generations = {
            purpose: scheduler.schedule_after("sid-b", purpose, 600)
            for purpose in StealthWakePurpose
        }
        assert scheduler.active_deadline_count == 2 * len(StealthWakePurpose)

        manager.in_memory_orders["sid-a"]["status"] = (
            StealthOrderStatus.CANCELLED.value
        )
        manager.schedule_change_callback("sid-a")

        assert scheduler.active_deadline_count == len(StealthWakePurpose)
        for purpose in StealthWakePurpose:
            assert (
                scheduler.current_generation("sid-a", purpose)
                > sid_a_generations[purpose]
            )
            assert (
                scheduler.current_generation("sid-b", purpose)
                == sid_b_generations[purpose]
            )
    finally:
        bridge.stop()


def test_reveal_failure_terminal_status_invalidates_anchor_lane() -> None:
    order = _time_delay_order("sid-error", "CONTRACT-A", delay_seconds=0)
    order["anchor_repricing_policy_json"] = {"enabled": True}
    manager = FakeStealthManager((order,))
    manager.trigger_on_evaluation.add("sid-error")
    bridge, scheduler = _new_bridge(manager)
    anchor_generation = scheduler.schedule_after(
        "sid-error",
        StealthWakePurpose.ANCHOR_REPRICE,
        60,
    )

    def fail_reveal(_stealth_order_id: str):
        manager.in_memory_orders["sid-error"]["status"] = (
            StealthOrderStatus.ERROR.value
        )
        return None

    manager.reveal_order_slice = fail_reveal

    try:
        bridge._evaluate_scheduled_order(
            "sid-error",
            market_data={
                "product_id": "CONTRACT-A",
                "price": 101.0,
                "bid": 100.0,
                "ask": 102.0,
                "source": "ticker",
                "time": datetime.utcnow(),
            },
        )

        assert manager.in_memory_orders["sid-error"]["status"] == (
            StealthOrderStatus.ERROR.value
        )
        assert scheduler.active_deadline_count == 0
        assert scheduler.current_generation(
            "sid-error",
            StealthWakePurpose.ANCHOR_REPRICE,
        ) > anchor_generation
    finally:
        scheduler.stop()


def test_paused_runtime_may_commit_triggered_but_never_reveals(monkeypatch) -> None:
    manager = FakeStealthManager((_time_delay_order("sid-a", "CONTRACT-A"),))
    manager.trigger_on_evaluation.add("sid-a")
    monkeypatch.setattr(
        bridge_module,
        "get_runtime_controller",
        lambda: PausedRuntimeController(),
    )
    bridge, _scheduler = _new_bridge(manager)

    try:
        bridge.start()
        bridge.activate_decisions()
        bridge.publish_ticker_update(
            "CONTRACT-A",
            {"price": "101", "best_bid": "100", "best_ask": "102"},
        )

        assert manager.evaluation_event.wait(timeout=0.75)
        bridge.stop()

        assert (
            manager.in_memory_orders["sid-a"]["status"]
            == StealthOrderStatus.TRIGGERED.value
        )
        assert manager.revealed_ids == []
    finally:
        bridge.stop()


def test_reveal_defers_when_pause_wins_atomic_admission(monkeypatch) -> None:
    """A pause between the optimistic read and admission must win."""

    stealth_order_id = "sid-atomic-reveal"
    manager = FakeStealthManager(
        (_time_delay_order(stealth_order_id, "CONTRACT-A"),)
    )
    manager.trigger_on_evaluation.add(stealth_order_id)
    controller = RejectAtAtomicAdmissionController()
    monkeypatch.setattr(
        bridge_module,
        "get_runtime_controller",
        lambda: controller,
    )
    bridge, scheduler = _new_bridge(manager)

    try:
        bridge._evaluate_scheduled_order(
            stealth_order_id,
            market_data={
                "product_id": "CONTRACT-A",
                "price": 101.0,
                "bid": 100.0,
                "ask": 102.0,
                "source": "ticker",
                "time": datetime.utcnow(),
            },
        )

        assert controller.state == EngineState.PAUSED
        assert manager.in_memory_orders[stealth_order_id]["status"] == (
            StealthOrderStatus.TRIGGERED.value
        )
        assert manager.revealed_ids == []
        assert scheduler.current_generation(
            stealth_order_id,
            StealthWakePurpose.ADMISSION_RETRY,
        ) > 0
    finally:
        scheduler.stop()


def test_committed_trigger_reveals_once_after_runtime_resumes(monkeypatch) -> None:
    order = _time_delay_order("sid-a", "CONTRACT-A", delay_seconds=0)
    manager = FakeStealthManager((order,))
    manager.trigger_on_evaluation.add("sid-a")
    controller = MutableRuntimeController(EngineState.PAUSED)
    monkeypatch.setattr(
        bridge_module,
        "get_runtime_controller",
        lambda: controller,
    )

    def reveal_once(stealth_order_id: str) -> str:
        manager.revealed_ids.append(stealth_order_id)
        manager.in_memory_orders[stealth_order_id]["status"] = (
            StealthOrderStatus.REVEALED.value
        )
        manager.in_memory_orders[stealth_order_id]["remaining_size"] = 0.0
        return f"placed-{stealth_order_id}"

    manager.reveal_order_slice = reveal_once
    bridge, _scheduler = _new_bridge(manager)

    try:
        bridge.start()
        bridge.activate_decisions()

        deadline = time.monotonic() + 0.75
        while (
            manager.in_memory_orders["sid-a"]["status"]
            != StealthOrderStatus.TRIGGERED.value
            and time.monotonic() < deadline
        ):
            time.sleep(0.005)

        assert manager.in_memory_orders["sid-a"]["status"] == (
            StealthOrderStatus.TRIGGERED.value
        )
        assert manager.revealed_ids == []

        controller.state = EngineState.RUNNING
        deadline = time.monotonic() + 0.75
        while not manager.revealed_ids and time.monotonic() < deadline:
            time.sleep(0.005)

        assert manager.revealed_ids == ["sid-a"]
        time.sleep(0.15)
        assert manager.revealed_ids == ["sid-a"]
    finally:
        bridge.stop()


def test_stop_interrupts_bridge_and_far_future_scheduler_wait_promptly() -> None:
    manager = FakeStealthManager()
    bridge, scheduler = _new_bridge(manager)
    bridge.start()
    bridge.activate_decisions()
    scheduler.schedule_after("sid-future", StealthWakePurpose.TIME_DELAY, 60)

    started = time.monotonic()
    bridge.stop()
    elapsed = time.monotonic() - started

    assert elapsed < 0.5
    assert scheduler.stopped is True
    assert bridge.evaluation_thread is None or not bridge.evaluation_thread.is_alive()
    assert not bridge.reconciliation_thread.is_alive()


def test_due_time_persistence_failure_never_reveals_and_rebuilds_wake(
    monkeypatch,
) -> None:
    product_id = "PERSISTENCE-FAILURE-PRODUCT"
    stealth_order_id = "persistence-failure-order"
    manager = StealthOrderManager(db_client=None, log_callback=Mock())
    manager._validate_local_price_read_only = Mock(return_value=True)
    manager._update_stealth_order = Mock(return_value=False)
    manager._dispatch_lifecycle_event = Mock()
    manager.reveal_order_slice = Mock(return_value="must-not-be-placed")
    manager.in_memory_orders[stealth_order_id] = {
        **_time_delay_order(
            stealth_order_id,
            product_id,
            delay_seconds=0.0,
        ),
        "side": "BUY",
        "total_size": 1.0,
        "revealed_size": 0.0,
        "executed_size": 0.0,
        "limit_price": 100.0,
        "revealed_orders": [],
        "reason": "deadline persistence failure contract",
    }
    manager.publish_market_data(
        product_id,
        {
            "product_id": product_id,
            "price": 100.0,
            "bid": 99.0,
            "ask": 101.0,
            "time": datetime.utcnow(),
            "source": "ticker",
        },
    )
    controller = MutableRuntimeController()
    monkeypatch.setattr(
        bridge_module,
        "get_runtime_controller",
        lambda: controller,
    )
    monkeypatch.setattr(
        "core.stealth_order_manager.get_runtime_controller",
        lambda: controller,
    )
    clock = MutableMonotonicClock(100.0)
    scheduler = StealthEventDeadlineScheduler(clock=clock)
    bridge = bridge_module.StealthOrderBridge(
        manager,
        order_engine=None,
        scheduler=scheduler,
    )
    bridge._decisions_ready.set()
    initial_generation = scheduler.schedule_after(
        stealth_order_id,
        StealthWakePurpose.TIME_DELAY,
        0.0,
    )
    errors = []

    try:
        batch = scheduler.run_due(
            on_deadline=bridge._handle_deadline_wake,
            on_error=lambda error, item: errors.append((error, item)),
        )

        assert len(batch.deadline_wakes) == 1
        assert len(errors) == 1
        assert isinstance(errors[0][0], StealthOrderPersistenceError)
        order = manager.in_memory_orders[stealth_order_id]
        assert order["status"] == StealthOrderStatus.HIDDEN.value
        assert order["condition_first_met_at"] is None
        assert order["condition_confirmed_at"] is None
        assert controller.pause_requests == 1
        manager.reveal_order_slice.assert_not_called()
        manager._dispatch_lifecycle_event.assert_not_called()
        assert scheduler.current_generation(
            stealth_order_id,
            StealthWakePurpose.TIME_DELAY,
        ) > initial_generation
        assert scheduler.next_deadline_monotonic == pytest.approx(100.1)
    finally:
        scheduler.stop()


def test_real_manager_continuous_hold_rebuilds_and_reveals_on_next_tick(
    monkeypatch,
) -> None:
    """Exercise the actual manager/bridge callback and generation boundary."""

    product_id = "INTEGRATION-PRODUCT"
    stealth_order_id = "real-manager-hold"
    first_event_time = datetime.utcnow()
    manager = StealthOrderManager(db_client=None, log_callback=Mock())
    manager._validate_local_price_read_only = Mock(return_value=True)
    manager._update_stealth_order = Mock(return_value=True)
    manager._dispatch_lifecycle_event = Mock()
    manager.reveal_order_slice = Mock(return_value="revealed-client-order")
    manager.in_memory_orders[stealth_order_id] = {
        "stealth_order_id": stealth_order_id,
        "product_id": product_id,
        "side": "BUY",
        "total_size": 1.0,
        "revealed_size": 0.0,
        "remaining_size": 1.0,
        "executed_size": 0.0,
        "limit_price": 100.0,
        "status": StealthOrderStatus.HIDDEN.value,
        "reveal_condition_type": RevealConditionType.PRICE_THRESHOLD.value,
        "reveal_condition_json": {
            "type": RevealConditionType.PRICE_THRESHOLD.value,
            "direction": "below",
            "price_threshold": 100.0,
            "hold_duration_seconds": 2.0,
        },
        "anchor_repricing_policy_json": {"enabled": False},
        "anchor_repricing_state_json": {},
        "condition_first_met_at": None,
        "condition_confirmed_at": None,
        "created_at": first_event_time,
        "revealed_orders": [],
        "reason": "real manager scheduler integration",
    }
    controller = MutableRuntimeController()
    monkeypatch.setattr(
        bridge_module,
        "get_runtime_controller",
        lambda: controller,
    )
    scheduler = StealthEventDeadlineScheduler()
    bridge = bridge_module.StealthOrderBridge(
        manager,
        order_engine=None,
        scheduler=scheduler,
    )
    bridge.record_reveal_event = Mock()
    bridge._decisions_ready.set()

    try:
        bridge.publish_ticker_update(
            product_id,
            {"price": "99", "best_bid": "98", "best_ask": "100"},
            event_time=first_event_time,
        )
        scheduler.run_due(on_market_event=bridge._handle_market_event)

        order = manager.in_memory_orders[stealth_order_id]
        assert order["status"] == StealthOrderStatus.PENDING.value
        first_generation = scheduler.current_generation(
            stealth_order_id,
            StealthWakePurpose.CONDITION_HOLD,
        )
        assert first_generation > 0

        bridge.publish_ticker_update(
            product_id,
            {"price": "99", "best_bid": "98", "best_ask": "100"},
            event_time=first_event_time + timedelta(seconds=2),
        )
        scheduler.run_due(on_market_event=bridge._handle_market_event)

        assert order["status"] == StealthOrderStatus.TRIGGERED.value
        assert order["condition_confirmed_at"] == (
            first_event_time + timedelta(seconds=2)
        )
        manager.reveal_order_slice.assert_called_once_with(stealth_order_id)
        bridge.record_reveal_event.assert_called_once_with(
            stealth_order_id,
            "revealed-client-order",
            "Price threshold currently met; continuous hold deadline reached",
        )
        assert scheduler.current_generation(
            stealth_order_id,
            StealthWakePurpose.CONDITION_HOLD,
        ) > first_generation
    finally:
        scheduler.stop()
