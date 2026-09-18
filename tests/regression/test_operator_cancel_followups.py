"""An accepted project cancel stops new automation, not exchange accounting."""

import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import core.order_engine as engine_module
from bridges.stealth_order_bridge import StealthOrderBridge
from core.enums import FollowUpKind, StealthOrderStatus
from core.runtime_controller import RuntimeController
from tests.regression.test_cancel_followup_stealth_id_passthrough import _wire_cancel_path
from tests.unit.test_filled_followup_partial_size_adjustment import (
    _attach_stealth_bridge,
    _configure_common_followup_mocks,
    _filled_order,
)
from tests.unit.test_partial_fill_followups import _build_engine_for_partial_fill_tests


pytestmark = pytest.mark.regression
SID = "f6c0b89c-cf9a-45ed-a2af-a554ad155d87"
PLACEMENT = "a7a23c22-fbc3-454b-b6b0-507fe3c5e032"
CHILD = "1a7c077b-ce8a-4710-a38c-870aee13f8a0"


def _stop(order):
    order["status"] = StealthOrderStatus.CANCELLED.value
    order.setdefault("anchor_repricing_state_json", {})[
        "operator_cancel_requested_at"
    ] = "2026-09-18T12:00:00"


def _bridge(order):
    manager = SimpleNamespace(
        _get_stealth_order=Mock(side_effect=lambda sid: order if sid == SID else None),
        find_stealth_order_by_placed_order_id=Mock(return_value=order),
        create_follow_up_stealth_order=Mock(return_value=CHILD),
        cancel_stealth_order=Mock(side_effect=lambda *_args, **_kwargs: _stop(order) or True),
    )
    bridge = StealthOrderBridge.__new__(StealthOrderBridge)
    bridge.stealth_manager = manager
    bridge._order_action_locks_guard = threading.Lock()
    bridge._order_action_locks = {}
    return bridge


@pytest.mark.parametrize("stopped", [False, True])
def test_followup_factory_honors_persisted_intent_not_cancelled_status(stopped):
    order = {"stealth_order_id": SID, "status": StealthOrderStatus.CANCELLED.value}
    if stopped:
        _stop(order)
    bridge = _bridge(json.loads(json.dumps(order)))

    result = bridge.create_follow_up_stealth_order(
        original_stealth_order_id=SID, follow_up_stealth_order_id=CHILD
    )

    assert result == (None if stopped else CHILD)
    assert bridge.stealth_manager.create_follow_up_stealth_order.call_count == (0 if stopped else 1)


def test_missing_managed_source_does_not_admit_new_automation():
    bridge = _bridge(None)

    with bridge.guard_follow_up_creation(SID) as allowed:
        assert allowed is False
    assert bridge.create_follow_up_stealth_order(
        original_stealth_order_id=SID, follow_up_stealth_order_id=CHILD
    ) is None
    bridge.stealth_manager.create_follow_up_stealth_order.assert_not_called()


@pytest.mark.parametrize("cancel_first", [False, True])
def test_factory_and_cancel_have_one_source_sid_lock_winner(cancel_first):
    order = {"stealth_order_id": SID}
    bridge = _bridge(order)
    entered, release, second_started = (threading.Event() for _ in range(3))
    actions, results, errors = [], [], []

    def create(**_kwargs):
        if not cancel_first:
            entered.set()
            assert release.wait(2)
        actions.append("created")
        return CHILD

    def cancel(*_args, **_kwargs):
        if cancel_first:
            entered.set()
            assert release.wait(2)
        _stop(order)
        actions.append("cancelled")
        return True

    bridge.stealth_manager.create_follow_up_stealth_order.side_effect = create
    bridge.stealth_manager.cancel_stealth_order.side_effect = cancel

    def run(is_cancel, *, second=False):
        try:
            if second:
                second_started.set()
            if is_cancel:
                bridge.cancel_stealth_order(SID)
            else:
                results.append(bridge.create_follow_up_stealth_order(
                    original_stealth_order_id=SID, follow_up_stealth_order_id=CHILD
                ))
        except BaseException as error:
            errors.append(error)

    first = threading.Thread(target=run, args=(cancel_first,))
    second = threading.Thread(target=run, args=(not cancel_first,), kwargs={"second": True})
    first.start()
    try:
        assert entered.wait(2)
        second.start()
        assert second_started.wait(2)
        source_lock = bridge._get_order_action_lock(SID)
        acquired = source_lock.acquire(blocking=False)
        if acquired:
            source_lock.release()
        assert not acquired
    finally:
        release.set()
        first.join(2)
        if second.ident is not None:
            second.join(2)
    assert not first.is_alive() and not second.is_alive()
    assert errors == []
    assert actions == (["cancelled"] if cancel_first else ["created", "cancelled"])
    assert results == ([None] if cancel_first else [CHILD])


def test_source_stop_does_not_cascade_to_preexisting_child():
    order = {"stealth_order_id": SID}
    child = {"stealth_order_id": CHILD, "parent_order_id": SID}
    _stop(order)
    bridge = _bridge(order)
    bridge.stealth_manager._get_stealth_order.side_effect = {
        SID: order, CHILD: child
    }.get

    assert bridge.create_follow_up_stealth_order(original_stealth_order_id=CHILD) == CHILD
    assert "anchor_repricing_state_json" not in child


@pytest.mark.parametrize("stopped", [False, True])
def test_exchange_cancel_replaces_but_project_cancel_suppresses(monkeypatch, stopped):
    engine = _build_engine_for_partial_fill_tests()
    bridge, order = _wire_cancel_path(
        engine, placement_uuid=PLACEMENT, stealth_root_id=SID,
        parent_db_row={"target_movement": 0.001, "target_movement_type": "P"},
    )
    order["status"] = StealthOrderStatus.CANCELLED.value
    if stopped:
        _stop(order)
    bridge.create_follow_up_stealth_order.return_value = CHILD
    monkeypatch.setattr("database.order.has_pending_move", lambda *_args: False)
    monkeypatch.setattr("database.order.get_parent_order", lambda *_args: {})

    engine.handle_cancelled_order({"client_order_id": PLACEMENT})

    assert bridge.create_follow_up_stealth_order.call_count == (0 if stopped else 1)
    assert engine.register_child_order.call_count == (0 if stopped else 1)


def test_cancel_race_refunds_reserved_replacement_slot(monkeypatch):
    engine = _build_engine_for_partial_fill_tests()
    bridge, order = _wire_cancel_path(
        engine, placement_uuid=PLACEMENT, stealth_root_id=SID,
        parent_db_row={"target_movement": 0.001, "target_movement_type": "P"},
    )
    bridge.create_follow_up_stealth_order.side_effect = lambda **_kwargs: _stop(order)
    engine.complete_follow_up_processing = Mock()
    monkeypatch.setattr("database.order.has_pending_move", lambda *_args: False)
    monkeypatch.setattr("database.order.get_parent_order", lambda *_args: {})

    engine.handle_cancelled_order({"client_order_id": PLACEMENT})

    assert engine._pending_replacement_claims.get(SID, 0) == 0
    engine.register_child_order.assert_not_called()
    engine.complete_follow_up_processing.assert_called_once_with(FollowUpKind.CANCELLED, PLACEMENT)


@pytest.mark.parametrize("late_stop", [False, True])
def test_full_fill_is_recorded_but_stopped_followup_is_not_registered(monkeypatch, late_stop):
    engine = _build_engine_for_partial_fill_tests()
    bridge = _attach_stealth_bridge(engine)
    _configure_common_followup_mocks(engine)
    order = bridge.stealth_manager.find_stealth_order_by_placed_order_id.return_value
    engine._register_stealth_placement_under_root = Mock()
    if late_stop:
        bridge.create_follow_up_stealth_order.side_effect = lambda **_kwargs: _stop(order)
    else:
        _stop(order)
    monkeypatch.setattr("database.order.get_partial_fill_progress", lambda *_args: None)
    monkeypatch.setattr("database.order.get_parent_order", lambda *_args: {})

    engine.handle_filled_order(_filled_order())

    bridge.update_execution.assert_called_once()
    assert bridge.update_execution.call_args.kwargs["executed_size"] == 40.0
    assert bridge.create_follow_up_stealth_order.call_count == (1 if late_stop else 0)
    engine.register_child_order.assert_not_called()
    engine.complete_follow_up_processing.assert_called_once_with(FollowUpKind.FILLED, "placed-1")


@pytest.mark.parametrize("late_stop", [False, True])
def test_partial_fill_stop_does_not_consume_carry_or_register_child(late_stop):
    engine = _build_engine_for_partial_fill_tests()
    bridge = _attach_stealth_bridge(engine)
    order = bridge.stealth_manager.find_stealth_order_by_placed_order_id.return_value
    engine.resolve_parent_target_movement = Mock(return_value={})
    engine.compute_partial_fill_order_template = Mock(return_value={"start_price": 100.0, "side": "SELL"})
    engine.register_child_order = Mock()
    engine.order_progress_tracker = Mock()
    engine.order_progress_tracker.claim_follow_up_units.return_value = 2
    if late_stop:
        bridge.create_follow_up_stealth_order.side_effect = lambda **_kwargs: _stop(order)
    else:
        _stop(order)

    assert engine._create_partial_fill_follow_up(PLACEMENT, SID, 1.0, 2) == 0

    engine.register_child_order.assert_not_called()
    if late_stop:
        engine.order_progress_tracker.release_follow_up_units.assert_called_once_with(PLACEMENT, 2)
    else:
        engine.order_progress_tracker.claim_follow_up_units.assert_not_called()


@pytest.mark.parametrize("stopped", [False, True])
def test_hotpoint_uses_source_stop_guard_and_does_not_skip_fill_ledger(monkeypatch, stopped):
    engine = _build_engine_for_partial_fill_tests()
    order = {"stealth_order_id": SID}
    if stopped:
        _stop(order)
    engine.stealth_order_bridge = _bridge(order)
    engine._hotpoint_detector = Mock()
    engine._hotpoint_rate_limiter = Mock()
    engine._hotpoint_policy = Mock()
    engine._get_parent_enable_hotpoint_replication = Mock(return_value=True)
    engine.is_hotpoint_auto_place_enabled = Mock(return_value=True)
    engine.fill_repo = Mock()
    engine._append_derived_fill_with_hooks = Mock()
    engine._maybe_create_partial_fill_follow_up = Mock()
    engine.order_progress_tracker = Mock()
    delta = SimpleNamespace(
        client_order_id=PLACEMENT, product_id="BTC-USDC", side="BUY",
        derived_price=100.0, is_new_match=True, is_terminal=True,
        cumulative_quantity=1.0, number_of_fills=1, completion_percentage=100.0,
    )
    engine.order_progress_tracker.ingest.return_value = delta
    controller = RuntimeController()
    controller.complete_startup()
    monkeypatch.setattr(engine_module, "get_runtime_controller", lambda: controller)
    monkeypatch.setattr(engine_module, "LOT_TRACKING_AVAILABLE", True)
    placer = Mock()
    monkeypatch.setattr("business.hotpoint_placer.place_hotpoint_order", placer)

    assert engine._process_ws_order_delta({}) is delta

    engine._append_derived_fill_with_hooks.assert_called_once_with(delta)
    engine._append_order_match_audit.assert_called_once()
    engine._persist_progress_from_record.assert_called_once()
    assert placer.call_count == (0 if stopped else 1)
    assert engine._hotpoint_detector.record_fill.call_count == (0 if stopped else 1)
