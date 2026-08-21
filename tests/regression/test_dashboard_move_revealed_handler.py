"""Regression tests for the ``move_revealed_stealth_order`` dashboard
WebSocket handler.

Covers:

1. Message type is registered in ``_ORIGINATING_MSG_TYPES`` (so it is
   correctly admission-gated when the engine is paused / draining).
2. Happy path → ``stealth_order_moved`` success response with new
   exchange order id and broadcasts to all connected clients.
3. ``StealthMoveError`` raised by the executor surfaces the failing
   ``stage`` to the UI verbatim — this is what tells the operator
   whether they need to take recovery action (``stage="place"`` after
   a successful cancel leaves an off-book stealth order).
4. Unknown ``reason`` value is rejected at the boundary with stage
   ``"validate"`` (P2 rule #5: enums, not magic strings).

The handler is exercised through the real ``handle_client_message``
coroutine; only the bridge / runtime controller / websocket are
mocked. This guards against the bridge wiring or admission gate
silently regressing.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_websocket() -> MagicMock:
    """A websocket double whose ``send`` records every payload."""
    ws = MagicMock()
    ws.send = AsyncMock()
    return ws


def _admitting_controller() -> MagicMock:
    """Runtime controller that admits originating work."""
    ctrl = MagicMock()
    ctrl.is_admitting.return_value = True
    ctrl.is_stopping.return_value = False
    ctrl.state = MagicMock(value="RUNNING")
    return ctrl


def _sent_payloads(ws: MagicMock) -> list[dict]:
    return [json.loads(call.args[0]) for call in ws.send.await_args_list]


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# 1) Admission gate registration
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_move_revealed_is_registered_as_originating_msg_type():
    """The handler creates new exchange work (cancel + place), so it
    must be admission-gated by the runtime controller. If this fact
    regresses, paused / draining engines would silently accept moves
    and burn through the inflight cap during shutdown."""
    import dashboard_server

    assert "move_revealed_stealth_order" in dashboard_server._ORIGINATING_MSG_TYPES, (
        "move_revealed_stealth_order must be in _ORIGINATING_MSG_TYPES so "
        "it is gated on EngineState.RUNNING. Without this, a move can be "
        "issued while the engine is paused or draining, leaking exchange "
        "work past the admission boundary."
    )


# ---------------------------------------------------------------------------
# 2) Happy path
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_handler_happy_path_returns_success_and_broadcasts():
    """End-to-end: bridge.build → bridge.execute → broadcast a success
    payload to every connected client."""
    import dashboard_server

    ws = _make_websocket()
    other_client = _make_websocket()

    plan = MagicMock()
    plan.old_exchange_order_id = "old_ex_123"
    plan.new_configured_limit_price = 101.5

    from core.models import StealthMoveResult
    bridge = MagicMock()
    bridge.stealth_manager.build_stealth_move_plan.return_value = plan
    bridge.stealth_manager.execute_stealth_move.return_value = StealthMoveResult(
        new_placement_client_order_id="new_placement_coid_456",
        new_exchange_order_id="new_ex_789",
        new_submitted_price=101.5,
    )

    message = json.dumps({
        "type": "move_revealed_stealth_order",
        "stealth_order_id": "sid_happy",
        "new_limit_price": 101.5,
        "reason": "manual_user_move",
        "notes": "ui-test",
    })

    with patch.object(dashboard_server, "stealth_order_bridge", bridge), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "connected_clients", {ws, other_client}), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(ws, message))

    # Build + execute called with the correct sid + price.
    bridge.stealth_manager.build_stealth_move_plan.assert_called_once()
    build_args = bridge.stealth_manager.build_stealth_move_plan.call_args
    assert build_args.args[0] == "sid_happy"
    assert build_args.args[1] == 101.5
    bridge.stealth_manager.execute_stealth_move.assert_called_once_with(plan)

    # Broadcast — both clients received the success payload.
    for client in (ws, other_client):
        assert client.send.await_count >= 1
    payloads = _sent_payloads(ws)
    success = [p for p in payloads if p.get("type") == "stealth_order_moved"]
    assert len(success) == 1, f"expected one stealth_order_moved payload, got {payloads}"
    body = success[0]
    assert body["success"] is True
    assert body["stealth_order_id"] == "sid_happy"
    assert body["old_exchange_order_id"] == "old_ex_123"
    assert body["new_placement_client_order_id"] == "new_placement_coid_456"
    assert body["new_exchange_order_id"] == "new_ex_789"
    assert body["new_submitted_price"] == 101.5


# ---------------------------------------------------------------------------
# 3) StealthMoveError surfaces stage
# ---------------------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize("stage", ["validate", "claim", "cancel", "place", "persist"])
def test_handler_surfaces_stealth_move_error_stage_to_ui(stage):
    """Each terminal failure stage must be surfaced verbatim so the
    UI can decide whether to prompt the operator for recovery action.

    ``stage="place"`` is the critical one: the cancel succeeded so the
    stealth order has been transitioned to CANCELLED with no replacement
    on the exchange. The dashboard must surface this distinctly.
    """
    import dashboard_server
    from core.exceptions import StealthMoveError

    ws = _make_websocket()

    bridge = MagicMock()
    # Either build or execute can raise; exercise via build to keep the test
    # simple. The handler treats both call sites identically.
    bridge.stealth_manager.build_stealth_move_plan.side_effect = StealthMoveError(
        f"forced {stage} failure",
        stealth_order_id="sid_fail",
        stage=stage,
    )

    message = json.dumps({
        "type": "move_revealed_stealth_order",
        "stealth_order_id": "sid_fail",
        "new_limit_price": 100.0,
    })

    with patch.object(dashboard_server, "stealth_order_bridge", bridge), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "connected_clients", {ws}), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(ws, message))

    payloads = _sent_payloads(ws)
    move_payloads = [p for p in payloads if p.get("type") == "stealth_order_moved"]
    assert len(move_payloads) == 1
    body = move_payloads[0]
    assert body["success"] is False
    assert body["stage"] == stage, (
        f"handler dropped or rewrote the stage tag (got {body.get('stage')!r}, "
        f"expected {stage!r}). The UI uses this to decide recovery action."
    )
    assert "forced" in body["error"]


# ---------------------------------------------------------------------------
# 4) Unknown reason is validated at the boundary
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_handler_rejects_unknown_reason_with_validate_stage():
    """``reason`` is resolved through StealthMoveReason at the WS
    boundary. An unknown value must be rejected immediately with
    ``stage="validate"`` and never reach the bridge — otherwise a
    typo'd reason would silently degrade the audit trail."""
    import dashboard_server

    ws = _make_websocket()

    bridge = MagicMock()
    # If the bridge is invoked at all, the test fails.
    bridge.stealth_manager.build_stealth_move_plan.side_effect = AssertionError(
        "build_stealth_move_plan must NOT be called when reason is invalid"
    )

    message = json.dumps({
        "type": "move_revealed_stealth_order",
        "stealth_order_id": "sid_bad_reason",
        "new_limit_price": 100.0,
        "reason": "totally_made_up",
    })

    with patch.object(dashboard_server, "stealth_order_bridge", bridge), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "connected_clients", {ws}), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(ws, message))

    payloads = _sent_payloads(ws)
    move_payloads = [p for p in payloads if p.get("type") == "stealth_order_moved"]
    assert len(move_payloads) == 1
    body = move_payloads[0]
    assert body["success"] is False
    assert body["stage"] == "validate"
    assert "totally_made_up" in body["error"]
    bridge.stealth_manager.build_stealth_move_plan.assert_not_called()


# ---------------------------------------------------------------------------
# 5) Missing required fields short-circuit before touching the bridge
# ---------------------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize("missing", ["stealth_order_id", "new_limit_price"])
def test_handler_rejects_missing_required_fields(missing):
    import dashboard_server

    ws = _make_websocket()
    bridge = MagicMock()

    payload = {
        "type": "move_revealed_stealth_order",
        "stealth_order_id": "sid_x",
        "new_limit_price": 100.0,
    }
    payload.pop(missing)

    with patch.object(dashboard_server, "stealth_order_bridge", bridge), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "connected_clients", {ws}), \
         patch.object(dashboard_server, "add_log_entry"):
        _run(dashboard_server.handle_client_message(ws, json.dumps(payload)))

    payloads = _sent_payloads(ws)
    move_payloads = [p for p in payloads if p.get("type") == "stealth_order_moved"]
    assert len(move_payloads) == 1
    assert move_payloads[0]["success"] is False
    assert move_payloads[0]["stage"] == "validate"
    bridge.stealth_manager.build_stealth_move_plan.assert_not_called()


# ---------------------------------------------------------------------------
# 6) End-to-end smoke: REAL build + execute through the WS handler
# ---------------------------------------------------------------------------
#
# The earlier tests mock the bridge, so they pin the *handler contract*
# but not the *integration*. This test plugs a real StealthOrderManager
# (no mocks on build_stealth_move_plan / execute_stealth_move) into the
# bridge, mocks only the REST client and DB persistence boundaries, and
# drives it through handle_client_message. If any of the seams between
# the WS handler, the bridge, the plan builder, the executor, the
# mutation claim ledger, the inflight tracker, or the audit insertion
# regress, this test fails.


def _make_real_manager_with_revealed_order(stealth_order_id: str = "sid_smoke"):
    """Bare-instance StealthOrderManager configured with a single
    REVEALED stealth order ready to be moved.

    Mirrors the fixture pattern used by
    ``tests/regression/test_stealth_move_revealed.py`` so any future
    schema drift in `_get_stealth_order` payloads surfaces in both
    suites simultaneously.
    """
    from core.enums import StealthMutationKind, StealthOrderStatus
    from core.orderbook import ClaimLedger
    from core.stealth_order_manager import StealthOrderManager
    from logging_service import get_logger

    mgr = StealthOrderManager.__new__(StealthOrderManager)
    mgr._mutation_claims = ClaimLedger(StealthMutationKind)
    mgr._placed_order_index = {}
    mgr.log_callback = lambda *a, **k: None
    mgr.logger = get_logger("StealthOrderManager.test")

    order = {
        "stealth_order_id": stealth_order_id,
        "parent_order_id": "root_parent_coid",
        "product_id": "BTC-USD",
        "side": "BUY",
        "status": StealthOrderStatus.REVEALED.value,
        "executed_size": 0.0,
        "remaining_size": 1.0,
        "limit_price": 100.0,
        "anchor_repricing_state_json": {
            "active_placement_client_order_id": "old_placement",
            "active_exchange_order_id": "old_exchange",
            "active_exchange_price": 100.0,
            "reprice_history": [{"at": "x", "price": 99.5}],
        },
        "anchor_repricing_policy_json": {"enabled": True},
        "revealed_orders": [{"reveal_number": 1, "placed_order_id": "old_placement"}],
        "max_order_replacements": 0,
        "allow_partial_fills": False,
    }
    return mgr, order


@pytest.mark.regression
def test_smoke_handler_drives_real_build_and_execute_end_to_end():
    """End-to-end smoke: dashboard handler → real bridge.stealth_manager
    → real build_stealth_move_plan → real execute_stealth_move →
    REST cancel + place (mocked) → audit insert (mocked) → success
    response sent on the websocket.

    What this catches that the unit tests don't:
      * Bridge plumbing: the WS handler reaches into
        ``stealth_order_bridge.stealth_manager`` and invokes the same
        method names the executor exposes.
      * Argument shape: handler-to-builder positional/kw signature
        agreement.
      * No surprise dependencies in the real executor that the bridge
        path is missing (e.g., a future field added to the order dict
        that the build path can't construct).
    """
    import dashboard_server

    mgr, order = _make_real_manager_with_revealed_order()
    bridge = MagicMock()
    bridge.stealth_manager = mgr  # REAL manager, not a Mock.

    ws = _make_websocket()

    message = json.dumps({
        "type": "move_revealed_stealth_order",
        "stealth_order_id": "sid_smoke",
        "new_limit_price": 101.5,
        "reason": "manual_user_move",
        "notes": "smoke-test",
    })

    with patch.object(dashboard_server, "stealth_order_bridge", bridge), \
         patch.object(dashboard_server, "get_runtime_controller",
                      return_value=_admitting_controller()), \
         patch.object(dashboard_server, "connected_clients", {ws}), \
         patch.object(dashboard_server, "add_log_entry"), \
         patch.object(mgr, "_get_stealth_order", return_value=order), \
         patch.object(mgr, "_update_stealth_order") as update_mock, \
         patch.object(mgr, "_record_reveal_event"), \
         patch.object(mgr, "_get_current_market_data",
                      return_value={"source": "ticker", "bid": 99.5, "ask": 100.5, "price": 100.0}), \
         patch("configuration.REST_CLIENT") as rest_mock, \
         patch("core.stealth_order_manager.insert_order_parent"), \
         patch("core.stealth_order_manager.resolve_stealth_chain_root",
               return_value="root_parent_coid"), \
         patch("database.order.insert_stealth_order_move") as audit_mock:
        rest_mock.cancel_orders.return_value = [{"success": True}]
        rest_mock.place_limit_order.return_value = {
            "success": True,
            "success_response": {"order_id": "new_ex_smoke"},
        }

        _run(dashboard_server.handle_client_message(ws, message))

    # --- WS contract -----------------------------------------------------
    payloads = _sent_payloads(ws)
    move_payloads = [p for p in payloads if p.get("type") == "stealth_order_moved"]
    assert len(move_payloads) == 1, (
        f"expected exactly one stealth_order_moved payload, got {payloads!r}"
    )
    body = move_payloads[0]
    assert body["success"] is True, f"expected success, got {body!r}"
    assert body["stealth_order_id"] == "sid_smoke"
    assert body["old_exchange_order_id"] == "old_exchange"
    # Both ids surfaced inline:
    #   - placement_client_order_id (internal tracking, per AGENTS.md)
    #   - exchange_order_id (so operators can cross-reference Coinbase
    #     without round-tripping through the stealth_order_moves audit
    #     table)
    assert isinstance(body["new_placement_client_order_id"], str)
    assert body["new_placement_client_order_id"]  # non-empty
    assert body["new_exchange_order_id"] == "new_ex_smoke"
    assert body["new_submitted_price"] == 101.5

    # --- Real REST sequence fired through the executor -------------------
    rest_mock.cancel_orders.assert_called_once()
    rest_mock.place_limit_order.assert_called_once()
    place_kwargs = rest_mock.place_limit_order.call_args.kwargs
    assert place_kwargs["product_id"] == "BTC-USD"
    assert place_kwargs["side"] == "BUY"
    assert float(place_kwargs["limit_price"]) == 101.5

    # --- Audit row written on success ------------------------------------
    assert audit_mock.called, "audit row must be inserted on a successful move"
    audit_kwargs = audit_mock.call_args.kwargs
    assert audit_kwargs["status"] == "completed"
    assert audit_kwargs["new_exchange_order_id"] == "new_ex_smoke"

    # --- Stealth row persisted with reset state --------------------------
    assert update_mock.called, "stealth order row must be persisted after move"

    # --- Mutation claim released so a follow-up move can re-enter --------
    from core.enums import StealthMutationKind
    assert mgr.try_claim_mutation(StealthMutationKind.MOVE, "sid_smoke") is True, (
        "executor must release the MOVE claim on the success path so a "
        "subsequent move on the same sid is admissible."
    )
