from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.enums import StealthOrderStatus
from core.models import RevealExecutionPlan
from core.stealth_order_manager import StealthOrderManager
from core.stealth_order_manager import OperatorStealthMaterializationContext


STEALTH_ORDER_ID = "11111111-1111-4111-8111-111111111111"
PORTFOLIO_ID = "22222222-2222-4222-8222-222222222222"


def _manager() -> StealthOrderManager:
    manager = StealthOrderManager(db_client=None, log_callback=MagicMock())
    manager.expected_retail_portfolio_id = PORTFOLIO_ID
    manager.in_memory_orders[STEALTH_ORDER_ID] = {
        "stealth_order_id": STEALTH_ORDER_ID,
        "product_id": "BTC-USDC",
        "side": "BUY",
        "total_size": 0.0001,
        "revealed_size": 0.0,
        "remaining_size": 0.0001,
        "executed_size": 0.0,
        "limit_price": 60000.0,
        "status": StealthOrderStatus.HIDDEN.value,
        "visibility_score": 0.0,
        "reveal_condition_type": "time_delay",
        "reveal_condition_json": {
            "type": "time_delay",
            "delay_seconds": 0,
            "operator_manual_reveal_required": True,
        },
        "reveal_pricing_policy": "top_of_book",
        "target_movement": 0.005,
        "target_movement_type": "P",
        "follow_up_reveal_direction": "opposite",
        "sizing_strategy_json": {"type": "fixed"},
        "parent_order_id": None,
        "reason": "operator_stealth_definition",
        "notes": "",
        "revealed_orders": [],
        "condition_confirmed_at": None,
        "condition_first_met_at": None,
        "allow_partial_fills": False,
        "anchor_repricing_policy_json": {},
        "anchor_repricing_state_json": {},
        "cancel_reentry_policy_json": {},
        "cancel_reentry_state_json": {},
        "post_fill_retreat_policy_json": {"enabled": False},
    }
    return manager


def _plan() -> RevealExecutionPlan:
    return RevealExecutionPlan(
        configured_limit_price=60000.0,
        submitted_limit_price=59999.99,
        reveal_pricing_policy="top_of_book",
        reveal_price_source="best_bid",
        fallback_used=False,
        market_source="ticker",
        market_bid=59999.99,
        market_ask=60000.01,
        target_movement=0.005,
        target_movement_type="P",
        target_movement_source="operator_definition",
        post_only=True,
    )


def _plan_payload() -> dict[str, object]:
    return {
        "product_id": "BTC-USDC",
        "side": "BUY",
        "base_size": "0.0001",
        "limit_price": "59999.99",
        "configured_limit_price": "60000",
        "submitted_limit_price": "59999.99",
        "reveal_pricing_policy": "top_of_book",
        "reveal_price_source": "best_bid",
        "fallback_used": False,
        "market_source": "ticker",
        "market_bid": "59999.99",
        "market_ask": "60000.01",
        "target_movement": "0.005",
        "target_movement_type": "P",
        "target_movement_source": "operator_definition",
        "post_only": True,
    }


def _plan_sha256() -> str:
    return hashlib.sha256(
        json.dumps(
            _plan_payload(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _admission_sha256(
    manager: StealthOrderManager,
    *,
    revision: int,
    definition_sha256: str,
) -> str:
    plan = _plan_payload()
    return manager.operator_prepreview_admission_sha256(
        stealth_order_id=STEALTH_ORDER_ID,
        definition_revision=revision,
        definition_sha256=definition_sha256,
        portfolio_id=PORTFOLIO_ID,
        plan_sha256=_plan_sha256(),
        product_id=str(plan["product_id"]),
        side=str(plan["side"]),
        base_size=str(plan["base_size"]),
        limit_price=str(plan["limit_price"]),
        post_only=True,
    )


def test_operator_manual_definition_never_auto_triggers() -> None:
    manager = _manager()

    should_reveal, reason = manager.should_trigger_reveal(STEALTH_ORDER_ID)

    assert should_reveal is False
    assert reason == "Operator confirmation is required"
    assert manager.in_memory_orders[STEALTH_ORDER_ID]["status"] == "HIDDEN"


def test_operator_manual_definition_cannot_reveal_without_exact_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager()
    create = MagicMock()
    monkeypatch.setattr(
        "configuration.REST_CLIENT",
        SimpleNamespace(create_order=create),
    )

    returned = manager.reveal_order_slice(
        STEALTH_ORDER_ID,
        before_create_call=lambda: None,
    )

    assert returned is None
    create.assert_not_called()


def test_operator_reveal_authority_is_one_use_and_freezes_exact_plan() -> None:
    manager = _manager()
    plan = _plan()

    authority = manager.prepare_operator_stealth_reveal(
        stealth_order_id=STEALTH_ORDER_ID,
        definition_revision=3,
        definition_sha256="a" * 64,
        portfolio_id=PORTFOLIO_ID,
        preview_claim_id="33333333-3333-4333-8333-333333333333",
        plan_sha256=_plan_sha256(),
        prepreview_admission_sha256=_admission_sha256(
            manager,
            revision=3,
            definition_sha256="a" * 64,
        ),
        plan=_plan_payload(),
        reveal_plan=plan,
    )

    allowed, resolved_plan, reason = (
        manager._consume_operator_stealth_reveal_authority(
            stealth_order_id=STEALTH_ORDER_ID,
            order=manager.in_memory_orders[STEALTH_ORDER_ID],
            authority=authority,
        )
    )
    repeated, repeated_plan, repeated_reason = (
        manager._consume_operator_stealth_reveal_authority(
            stealth_order_id=STEALTH_ORDER_ID,
            order=manager.in_memory_orders[STEALTH_ORDER_ID],
            authority=authority,
        )
    )

    assert allowed is True
    assert resolved_plan == plan
    assert resolved_plan is not plan
    assert reason is None
    assert repeated is False
    assert repeated_plan is None
    assert repeated_reason == "operator_stealth_authority_not_issued"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("submitted_limit_price", 60000.01),
        ("configured_limit_price", 60000.01),
        ("post_only", False),
        ("reveal_pricing_policy", "configured_limit"),
        ("reveal_price_source", "unexpected_source"),
        ("target_movement", 0.006),
        ("target_movement_type", "A"),
        ("target_movement_source", "unavailable"),
    ],
)
def test_operator_authority_rejects_reveal_plan_drift(
    field: str,
    value: object,
) -> None:
    manager = _manager()
    drifted = _plan()
    setattr(drifted, field, value)

    with pytest.raises(
        ValueError,
        match="operator_stealth_reveal_plan_mismatch",
    ):
        manager.prepare_operator_stealth_reveal(
            stealth_order_id=STEALTH_ORDER_ID,
            definition_revision=1,
            definition_sha256="a" * 64,
            portfolio_id=PORTFOLIO_ID,
            preview_claim_id="33333333-3333-4333-8333-333333333333",
            plan_sha256=_plan_sha256(),
            prepreview_admission_sha256=_admission_sha256(
                manager,
                revision=1,
                definition_sha256="a" * 64,
            ),
            plan=_plan_payload(),
            reveal_plan=drifted,
        )


def test_operator_reveal_uses_frozen_plan_and_disables_post_only_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager()
    plan = _plan()
    authority = manager.prepare_operator_stealth_reveal(
        stealth_order_id=STEALTH_ORDER_ID,
        definition_revision=1,
        definition_sha256="a" * 64,
        portfolio_id=PORTFOLIO_ID,
        preview_claim_id="33333333-3333-4333-8333-333333333333",
        plan_sha256=_plan_sha256(),
        prepreview_admission_sha256=_admission_sha256(
            manager,
            revision=1,
            definition_sha256="a" * 64,
        ),
        plan=_plan_payload(),
        reveal_plan=plan,
    )
    manager.profit_validator = object()
    manager._validate_reveal_profitability = MagicMock(
        return_value=(True, None)
    )
    manager._calculate_reveal_size = MagicMock(return_value=0.0001)
    manager.build_reveal_execution_plan = MagicMock(
        side_effect=AssertionError("frozen plan must be used")
    )
    manager._get_action_guard_blocked_until = MagicMock(return_value=0)
    manager._resolve_admin_fill_follow_up_reveal_authority = MagicMock(
        return_value={"required": False, "ready": True, "blockers": []}
    )
    manager._evaluate_action_condition_guard = MagicMock(
        return_value=(True, None)
    )
    manager._get_current_market_data = MagicMock(
        side_effect=AssertionError(
            "accepted Preview terms must not trigger a later market read"
        )
    )
    manager._update_stealth_order = MagicMock()
    manager._dispatch_lifecycle_event = MagicMock()
    manager.order_placement_hooks = SimpleNamespace(
        call_pre_submission_hooks=lambda _payload: None,
        call_post_submission_hooks=lambda _payload, _result: None,
    )
    capability = SimpleNamespace(
        allowed=True,
        reason="enabled",
        to_dict=lambda: {"allowed": True},
    )
    monkeypatch.setattr(
        "core.stealth_order_manager.evaluate_product_capability",
        MagicMock(return_value=capability),
    )
    place = MagicMock()

    def create_order(**kwargs):
        kwargs.pop("before_sdk_call")()
        place(**kwargs)
        return {
            "success": False,
            "failure_reason": "POST_ONLY",
        }

    monkeypatch.setattr(
        "configuration.REST_CLIENT",
        SimpleNamespace(create_order=create_order),
    )
    claimed: list[str] = []
    assert (
        manager.reveal_order_slice(
            STEALTH_ORDER_ID,
            operator_stealth_authority=authority,
            before_create_call=lambda: claimed.append("create"),
        )
        is None
    )

    place.assert_called_once()
    validated_plan = (
        manager._validate_reveal_profitability.call_args.kwargs[
            "reveal_execution_plan"
        ]
    )
    assert validated_plan.target_movement == 0.005
    assert validated_plan.target_movement_type == "P"
    assert (
        validated_plan.target_movement_source
        == "operator_definition"
    )
    assert claimed == ["create"]
    assert place.call_args.kwargs["product_id"] == "BTC-USDC"
    assert place.call_args.kwargs["side"] == "BUY"
    assert place.call_args.kwargs["client_order_id"] == STEALTH_ORDER_ID
    assert place.call_args.kwargs["order_configuration"] == {
        "limit_limit_gtc": {
            "base_size": "0.0001",
            "limit_price": "59999.99",
            "post_only": True,
        }
    }


def test_operator_reveal_keeps_raw_exchange_id_only_in_exact_child_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager()
    authority = manager.prepare_operator_stealth_reveal(
        stealth_order_id=STEALTH_ORDER_ID,
        definition_revision=1,
        definition_sha256="a" * 64,
        portfolio_id=PORTFOLIO_ID,
        preview_claim_id="33333333-3333-4333-8333-333333333333",
        plan_sha256=_plan_sha256(),
        prepreview_admission_sha256=_admission_sha256(
            manager,
            revision=1,
            definition_sha256="a" * 64,
        ),
        plan=_plan_payload(),
        reveal_plan=_plan(),
    )
    manager.profit_validator = None
    manager._get_action_guard_blocked_until = MagicMock(return_value=0)
    manager._resolve_admin_fill_follow_up_reveal_authority = MagicMock(
        return_value={"required": False, "ready": True, "blockers": []}
    )
    manager._get_current_market_data = MagicMock(
        side_effect=AssertionError(
            "accepted Preview terms must not trigger a later market read"
        )
    )
    manager._update_stealth_order = MagicMock()
    manager._record_reveal_event = MagicMock()
    manager._dispatch_lifecycle_event = MagicMock()
    manager.order_placement_hooks = SimpleNamespace(
        call_pre_submission_hooks=lambda _payload: None,
        call_post_submission_hooks=MagicMock(),
    )
    capability = SimpleNamespace(
        allowed=True,
        reason="enabled",
        to_dict=lambda: {"allowed": True},
    )
    monkeypatch.setattr(
        "core.stealth_order_manager.evaluate_product_capability",
        MagicMock(return_value=capability),
    )
    raw_exchange_id = "private-exchange-order-id"

    def create_order(**kwargs):
        kwargs.pop("before_sdk_call")()
        return {
            "success": True,
            "success_response": {"order_id": raw_exchange_id},
        }

    monkeypatch.setattr(
        "configuration.REST_CLIENT",
        SimpleNamespace(create_order=create_order),
    )

    assert manager.reveal_order_slice(
        STEALTH_ORDER_ID,
        operator_stealth_authority=authority,
        before_create_call=lambda: None,
    ) == STEALTH_ORDER_ID

    state = manager.in_memory_orders[STEALTH_ORDER_ID]
    assert (
        state["anchor_repricing_state_json"]["active_exchange_order_id"]
        == raw_exchange_id
    )
    assert all(
        event.get("exchange_order_id") is None
        for event in state["revealed_orders"]
    )
    manager.order_placement_hooks.call_post_submission_hooks.assert_not_called()
    serialized_logs = repr(manager.log_callback.call_args_list)
    serialized_lifecycle = repr(
        manager._dispatch_lifecycle_event.call_args_list
    )
    serialized_events = repr(manager._record_reveal_event.call_args_list)
    assert raw_exchange_id not in serialized_logs
    assert raw_exchange_id not in serialized_lifecycle
    assert raw_exchange_id not in serialized_events


def test_operator_websocket_sync_keeps_raw_exchange_id_only_in_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager()
    order = manager.in_memory_orders[STEALTH_ORDER_ID]
    order["revealed_orders"] = [
        {
            "placed_order_id": STEALTH_ORDER_ID,
            "exchange_order_id": None,
        }
    ]
    order["anchor_repricing_state_json"] = {
        "active_placement_client_order_id": STEALTH_ORDER_ID,
        "active_exchange_order_id": None,
    }
    manager._placed_order_index[STEALTH_ORDER_ID] = order
    manager.db_client = object()
    audit_updates: list[object] = []
    monkeypatch.setattr(
        "database.order.update_stealth_audit_exchange_order_id",
        lambda **kwargs: audit_updates.append(kwargs),
    )
    persisted: list[dict[str, object]] = []
    manager._update_stealth_order = lambda value: persisted.append(
        value
    )

    assert manager.sync_exchange_order_id_for_placed_order(
        STEALTH_ORDER_ID,
        "private-exchange-order-id",
    )
    assert order["anchor_repricing_state_json"][
        "active_exchange_order_id"
    ] == "private-exchange-order-id"
    assert order["revealed_orders"][0]["exchange_order_id"] is None
    assert persisted == [order]
    assert audit_updates == []


def test_operator_reveal_rejects_pre_submission_payload_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager()
    authority = manager.prepare_operator_stealth_reveal(
        stealth_order_id=STEALTH_ORDER_ID,
        definition_revision=1,
        definition_sha256="a" * 64,
        portfolio_id=PORTFOLIO_ID,
        preview_claim_id="33333333-3333-4333-8333-333333333333",
        plan_sha256=_plan_sha256(),
        prepreview_admission_sha256=_admission_sha256(
            manager,
            revision=1,
            definition_sha256="a" * 64,
        ),
        plan=_plan_payload(),
        reveal_plan=_plan(),
    )
    manager.profit_validator = None
    manager._calculate_reveal_size = MagicMock(return_value=0.0001)
    manager._get_action_guard_blocked_until = MagicMock(return_value=0)
    manager._resolve_admin_fill_follow_up_reveal_authority = MagicMock(
        return_value={"required": False, "ready": True, "blockers": []}
    )
    manager._evaluate_action_condition_guard = MagicMock(
        return_value=(True, None)
    )
    manager._get_current_market_data = MagicMock(
        side_effect=AssertionError(
            "accepted Preview terms must not trigger a later market read"
        )
    )
    manager._update_stealth_order = MagicMock()
    manager._dispatch_lifecycle_event = MagicMock()

    def drift(payload: dict[str, object]) -> None:
        payload["limit_price"] = 60001.0

    manager.order_placement_hooks = SimpleNamespace(
        call_pre_submission_hooks=drift,
        call_post_submission_hooks=lambda _payload, _result: None,
    )
    capability = SimpleNamespace(
        allowed=True,
        reason="enabled",
        to_dict=lambda: {"allowed": True},
    )
    monkeypatch.setattr(
        "core.stealth_order_manager.evaluate_product_capability",
        MagicMock(return_value=capability),
    )
    place = MagicMock(return_value={"success": True})

    def create_order(**kwargs):
        kwargs.pop("before_sdk_call")()
        return place(**kwargs)

    monkeypatch.setattr(
        "configuration.REST_CLIENT",
        SimpleNamespace(create_order=create_order),
    )

    assert (
        manager.reveal_order_slice(
            STEALTH_ORDER_ID,
            operator_stealth_authority=authority,
            before_create_call=lambda: None,
        )
        is None
    )
    place.assert_not_called()


def test_operator_definition_materializes_through_strict_canonical_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = StealthOrderManager(db_client=MagicMock(), log_callback=MagicMock())
    manager.expected_retail_portfolio_id = PORTFOLIO_ID
    persisted = MagicMock(return_value=(17, True))
    monkeypatch.setattr(
        "database.order.persist_operator_stealth_root_atomic",
        persisted,
    )
    size_result = SimpleNamespace(ok=True, size=0.0001, reason=None)
    monkeypatch.setattr(
        "calculation.size_validation.validate_and_quantize_size",
        MagicMock(return_value=size_result),
    )
    capability = SimpleNamespace(
        allowed=True,
        reason="enabled",
        to_dict=lambda: {"allowed": True},
    )
    monkeypatch.setattr(
        "core.stealth_order_manager.evaluate_product_capability",
        MagicMock(return_value=capability),
    )
    manager._evaluate_action_condition_guard = MagicMock(
        return_value=(True, None)
    )
    manager._dispatch_lifecycle_event = MagicMock()

    returned = manager.create_stealth_order(
        product_id="BTC-USDC",
        side="BUY",
        total_size=0.0001,
        limit_price=60000.0,
        reveal_condition={
            "type": "time_delay",
            "delay_seconds": 0,
            "operator_manual_reveal_required": True,
        },
        sizing_strategy={"type": "fixed"},
        reason="operator_stealth_definition",
        notes="operator-goal-6",
        stealth_order_id=STEALTH_ORDER_ID,
        max_order_replacements=0,
        target_movement=0.0,
        target_movement_type="P",
        reveal_pricing_policy="top_of_book",
        require_persistence=True,
        operator_materialization_context=(
            OperatorStealthMaterializationContext(
                definition_revision=1,
                definition_sha256="a" * 64,
                portfolio_id=PORTFOLIO_ID,
                correlation_id="goal6-correlation",
                audit_id="goal6-audit",
            )
        ),
    )

    assert returned == STEALTH_ORDER_ID
    persisted.assert_called_once()
    persisted_kwargs = persisted.call_args.kwargs
    assert persisted_kwargs["order"]["stealth_order_id"] == STEALTH_ORDER_ID
    assert (
        persisted_kwargs["order"]["reveal_condition_json"][
            "operator_manual_reveal_required"
        ]
        is True
    )
    assert persisted_kwargs["portfolio_id"] == PORTFOLIO_ID
    assert persisted_kwargs["correlation_id"] == "goal6-correlation"
    assert persisted_kwargs["audit_id"] == "goal6-audit"
    assert STEALTH_ORDER_ID in manager.in_memory_orders


def test_operator_closeout_defers_local_terminal_until_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager()
    order = manager.in_memory_orders[STEALTH_ORDER_ID]
    order["status"] = StealthOrderStatus.REVEALED.value
    order["anchor_repricing_state_json"] = {
        "active_placement_client_order_id": STEALTH_ORDER_ID,
        "active_exchange_order_id": "withheld-exchange-id",
        "active_exchange_price": 59999.99,
    }
    cancel = MagicMock(return_value={"success": True})
    monkeypatch.setattr(
        "configuration.REST_CLIENT",
        SimpleNamespace(cancel_orders=cancel),
    )
    manager._update_stealth_order = MagicMock()

    result = manager.cancel_stealth_order(
        STEALTH_ORDER_ID,
        reason="operator_goal6_exact_closeout",
        cancel_exchange=True,
        defer_local_terminal=True,
        value_blind_diagnostics=True,
        verified_exchange_order_id="withheld-exchange-id",
        before_cancel_call=lambda: None,
    )

    assert result is True
    cancel.assert_called_once()
    assert cancel.call_args.kwargs["order_ids"] == [
        "withheld-exchange-id"
    ]
    assert callable(cancel.call_args.kwargs["before_sdk_call"])
    assert order["status"] == StealthOrderStatus.REVEALED.value
    assert (
        order["anchor_repricing_state_json"][
            "active_placement_client_order_id"
        ]
        == STEALTH_ORDER_ID
    )


def test_operator_closeout_rejects_unverified_exchange_identity_before_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager()
    order = manager.in_memory_orders[STEALTH_ORDER_ID]
    order["status"] = StealthOrderStatus.REVEALED.value
    order["anchor_repricing_state_json"] = {
        "active_placement_client_order_id": STEALTH_ORDER_ID,
        "active_exchange_order_id": "withheld-exchange-id",
    }
    cancel = MagicMock()
    claimed: list[str] = []
    monkeypatch.setattr(
        "configuration.REST_CLIENT",
        SimpleNamespace(cancel_orders=cancel),
    )

    result = manager.cancel_stealth_order(
        STEALTH_ORDER_ID,
        cancel_exchange=True,
        defer_local_terminal=True,
        value_blind_diagnostics=True,
        verified_exchange_order_id="different-exchange-id",
        before_cancel_call=lambda: claimed.append("cancel"),
    )

    assert result is False
    assert claimed == []
    cancel.assert_not_called()
