from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

import pytest

from core.enums import StealthMutationKind
from core.orderbook import ClaimLedger
from core.stealth_order_manager import (
    OperatorStealthMoveAuthority,
    StealthOrderManager,
)


STEALTH_ID = "11111111-1111-4111-8111-111111111111"
SOURCE_CLIENT_ID = "22222222-2222-4222-8222-222222222222"
REPLACEMENT_CLIENT_ID = "33333333-3333-4333-8333-333333333333"
PORTFOLIO_ID = "44444444-4444-4444-8444-444444444444"
RAW_SOURCE_ID = "raw-source-exchange-id"
RAW_REPLACEMENT_ID = "raw-replacement-exchange-id"


def _authority() -> OperatorStealthMoveAuthority:
    return OperatorStealthMoveAuthority(
        stealth_order_id=STEALTH_ID,
        definition_revision=4,
        definition_sha256="a" * 64,
        portfolio_id=PORTFOLIO_ID,
        plan_sha256="b" * 64,
        source_client_order_id=SOURCE_CLIENT_ID,
        source_exchange_order_id=RAW_SOURCE_ID,
        source_exchange_order_id_sha256=hashlib.sha256(
            RAW_SOURCE_ID.encode()
        ).hexdigest(),
        replacement_client_order_id=REPLACEMENT_CLIENT_ID,
        root_client_order_id=STEALTH_ID,
        product_id="BTC-USDC",
        side="BUY",
        base_size="0.00001",
        old_limit_price="50000",
        replacement_limit_price="50000.12",
        target_movement="0.01",
        target_movement_type="P",
        post_only=True,
    )


def _manager() -> StealthOrderManager:
    manager = StealthOrderManager.__new__(StealthOrderManager)
    manager.expected_retail_portfolio_id = PORTFOLIO_ID
    manager._mutation_claims = ClaimLedger(StealthMutationKind)
    order = {
        "stealth_order_id": STEALTH_ID,
        "product_id": "BTC-USDC",
        "side": "BUY",
        "status": "REVEALED",
        "executed_size": 0.0,
        "remaining_size": 0.0,
        "total_size": 0.00001,
        "limit_price": 50000.0,
        "target_movement": 0.01,
        "target_movement_type": "P",
        "max_order_replacements": 0,
        "allow_partial_fills": False,
        "parent_order_id": STEALTH_ID,
        "anchor_repricing_state_json": {
            "active_placement_client_order_id": SOURCE_CLIENT_ID,
            "active_exchange_order_id": RAW_SOURCE_ID,
            "active_exchange_price": 50000.0,
            "reprice_history": [],
        },
        "revealed_orders": [],
    }
    manager.in_memory_orders = {STEALTH_ID: order}
    manager._placed_order_index = {SOURCE_CLIENT_ID: order}
    manager._get_stealth_order = lambda value: (
        manager.in_memory_orders.get(value)
    )
    source_placement = {
        "client_order_id": SOURCE_CLIENT_ID,
        "product_id": "BTC-USDC",
        "side": "BUY",
        "size": "0.00001",
        "price": "50000",
        "status": "OPEN",
        "parent_order_id": STEALTH_ID,
        "retail_portfolio_id": PORTFOLIO_ID,
        "exchange_order_id": None,
        "allow_partial_fills": False,
        "ownership_provenance": None,
    }
    root_order = {
        "client_order_id": STEALTH_ID,
        "retail_portfolio_id": PORTFOLIO_ID,
        "ownership_provenance": "ADMIN_MANUAL_ROOT",
    }
    manager._get_operator_move_parent_order = MagicMock(
        side_effect=lambda value: (
            source_placement if value == SOURCE_CLIENT_ID else root_order
        )
    )
    manager._source_placement = source_placement
    manager._root_order = root_order
    manager._update_stealth_order = MagicMock(return_value=True)
    manager._record_reveal_event = MagicMock()
    manager._get_account_wallets_for_action_guard = MagicMock(
        return_value={
            "USDC": {"available_balance": {"value": "100"}},
            "BTC": {"available_balance": {"value": "100"}},
        }
    )
    manager._rest_credentials_configured = MagicMock(return_value=True)
    manager._evaluate_action_condition_guard = MagicMock(
        side_effect=lambda **kwargs: (
            kwargs["wallet_fetcher"](),
            (True, None),
        )[1]
    )
    manager._evaluate_replacement_action_condition_guard = MagicMock(
        return_value=(True, None)
    )
    manager._resolve_target_movement_for_plan = MagicMock(
        return_value=(0.01, "P", "operator_definition")
    )
    manager._resolve_operator_stealth_move_target_binding = MagicMock(
        return_value=(0.01, "P", "order_parent")
    )
    manager.log_callback = MagicMock()
    return manager


def test_operator_plan_is_call_free_and_skips_wallet_replacement_guard() -> None:
    manager = _manager()
    manager._get_current_market_data = MagicMock(
        side_effect=AssertionError("operator planning must be call-free")
    )

    with patch(
        "core.stealth_order_manager.evaluate_product_capability",
        return_value=MagicMock(allowed=True),
    ):
        plan = manager.build_operator_stealth_move_plan(
            STEALTH_ID,
            50000.12,
            notes="operator-goal7-reviewed-move",
        )

    assert plan.stealth_order_id == STEALTH_ID
    assert plan.old_exchange_order_id == RAW_SOURCE_ID
    assert plan.new_configured_limit_price == 50000.12
    assert plan.reveal_plan.post_only is True
    manager._evaluate_action_condition_guard.assert_not_called()
    manager._evaluate_replacement_action_condition_guard.assert_not_called()
    manager._get_current_market_data.assert_not_called()


def test_operator_plan_rejects_terminal_or_drifted_source_placement() -> None:
    manager = _manager()
    placement = dict(manager._source_placement)
    placement["status"] = "FILLED"
    manager._source_placement.update(placement)

    with patch(
        "core.stealth_order_manager.evaluate_product_capability",
        return_value=MagicMock(allowed=True),
    ), pytest.raises(
        Exception,
        match="operator_move_source_not_eligible",
    ):
        manager.build_operator_stealth_move_plan(
            STEALTH_ID,
            50000.12,
            notes="operator-goal7-reviewed-move",
        )


def test_operator_plan_rejects_non_goal6_root_provenance() -> None:
    manager = _manager()
    manager._root_order["ownership_provenance"] = "ADMIN_AUTOMATION_ROOT"

    with patch(
        "core.stealth_order_manager.evaluate_product_capability",
        return_value=MagicMock(allowed=True),
    ), pytest.raises(
        Exception,
        match="operator_move_source_not_eligible",
    ):
        manager.build_operator_stealth_move_plan(
            STEALTH_ID,
            50000.12,
            notes="operator-goal7-reviewed-move",
        )


def test_operator_plan_accepts_goal6_root_placement_identity() -> None:
    manager = _manager()
    order = manager.in_memory_orders[STEALTH_ID]
    order["anchor_repricing_state_json"][
        "active_placement_client_order_id"
    ] = STEALTH_ID
    order["limit_price"] = 60000.0
    root_placement = {
        "client_order_id": STEALTH_ID,
        "product_id": "BTC-USDC",
        "side": "BUY",
        "size": "0.00001",
        "price": "60000",
        "status": "OPEN",
        "parent_order_id": None,
        "retail_portfolio_id": PORTFOLIO_ID,
        "exchange_order_id": None,
        "allow_partial_fills": False,
        "ownership_provenance": "ADMIN_MANUAL_ROOT",
    }
    manager._get_operator_move_parent_order.side_effect = (
        lambda _value: root_placement
    )

    with patch(
        "core.stealth_order_manager.evaluate_product_capability",
        return_value=MagicMock(allowed=True),
    ):
        plan = manager.build_operator_stealth_move_plan(
            STEALTH_ID,
            50000.12,
            notes="operator-goal7-reviewed-move",
        )

    assert plan.root_parent_client_order_id == STEALTH_ID
    assert plan.old_exchange_order_id == RAW_SOURCE_ID


def test_strict_profitability_never_fails_open() -> None:
    manager = _manager()
    manager.profit_validator = None
    assert (
        manager.validate_operator_stealth_move_profitability(
            stealth_order_id=STEALTH_ID,
            replacement_limit_price=50000.12,
            post_only=True,
        )
        is False
    )

    validator = MagicMock()
    validator.derive_follow_up_price_from_target.return_value = 50001.0
    validator.validate_order_profitability.return_value = {
        "is_profitable": True
    }
    manager.profit_validator = validator
    assert (
        manager.validate_operator_stealth_move_profitability(
            stealth_order_id=STEALTH_ID,
            replacement_limit_price=50000.12,
            post_only=True,
        )
        is True
    )


def test_cancel_uses_exact_manager_path_and_persists_move_fence() -> None:
    manager = _manager()
    claimed: list[str] = []

    def cancel(_stealth_order_id, **kwargs):
        assert kwargs["verified_exchange_order_id"] == RAW_SOURCE_ID
        assert (
            kwargs["verified_placement_client_order_id"]
            == SOURCE_CLIENT_ID
        )
        assert kwargs["value_blind_diagnostics"] is True
        assert kwargs["defer_local_terminal"] is True
        kwargs["before_cancel_call"]()
        return True

    manager.cancel_stealth_order = MagicMock(side_effect=cancel)
    result = manager.cancel_operator_stealth_move(
        authority=_authority(),
        before_cancel_call=lambda: claimed.append("cancel"),
    )

    state = manager.in_memory_orders[STEALTH_ID][
        "anchor_repricing_state_json"
    ]
    assert result is True
    assert claimed == ["cancel"]
    assert state["operator_move_cancel_returned"] is True
    assert state["operator_move_plan_sha256"] == "b" * 64
    assert (
        state["operator_move_replacement_client_order_id"]
        == REPLACEMENT_CLIENT_ID
    )
    assert manager._update_stealth_order.call_count == 2
    assert (
        manager.try_claim_mutation(StealthMutationKind.MOVE, STEALTH_ID)
        is True
    )


def test_cancel_accepts_only_the_verified_distinct_placement_identity() -> None:
    manager = _manager()
    rest_client = MagicMock()
    claimed: list[str] = []

    def cancel_orders(*, order_ids, before_sdk_call):
        assert order_ids == [RAW_SOURCE_ID]
        before_sdk_call()
        return {"results": [{"success": True}]}

    rest_client.cancel_orders.side_effect = cancel_orders

    with patch("configuration.REST_CLIENT", rest_client):
        result = manager.cancel_operator_stealth_move(
            authority=_authority(),
            before_cancel_call=lambda: claimed.append("cancel"),
        )

    assert result is True
    assert claimed == ["cancel"]
    rest_client.cancel_orders.assert_called_once()
    state = manager.in_memory_orders[STEALTH_ID][
        "anchor_repricing_state_json"
    ]
    assert state["active_placement_client_order_id"] == SOURCE_CLIENT_ID
    assert state["active_exchange_order_id"] == RAW_SOURCE_ID
    assert state["operator_move_cancel_returned"] is True


def test_cancel_fence_must_persist_before_the_coinbase_boundary() -> None:
    manager = _manager()
    manager._update_stealth_order.return_value = False
    manager.cancel_stealth_order = MagicMock()
    claimed: list[str] = []

    with pytest.raises(
        ValueError,
        match="operator_move_fence_persistence_failed",
    ):
        manager.cancel_operator_stealth_move(
            authority=_authority(),
            before_cancel_call=lambda: claimed.append("cancel"),
        )

    manager.cancel_stealth_order.assert_not_called()
    assert claimed == []
    state = manager.in_memory_orders[STEALTH_ID][
        "anchor_repricing_state_json"
    ]
    assert state["operator_move_cancel_pending"] is True
    assert state["operator_move_automatic_mutations_blocked"] is True


def test_stealth_update_requires_exactly_one_durable_row() -> None:
    manager = _manager()
    manager.db_client = MagicMock()
    manager.db_client.execute_update.return_value = 0
    order = manager.in_memory_orders[STEALTH_ID]

    assert StealthOrderManager._update_stealth_order(manager, order) is False

    manager.db_client.execute_update.return_value = 1
    assert StealthOrderManager._update_stealth_order(manager, order) is True


def test_goal7_reveal_history_failure_is_value_blind_and_observable() -> None:
    manager = _manager()
    manager.db_client = MagicMock()
    manager.db_client.execute_update.side_effect = RuntimeError(
        "withheld-private-reveal-history-error"
    )

    with pytest.raises(
        ValueError,
        match="stealth_reveal_event_recording_failed",
    ):
        StealthOrderManager._record_reveal_event(
            manager,
            manager.in_memory_orders[STEALTH_ID],
            {
                "reveal_number": 1,
                "placement_client_order_id": REPLACEMENT_CLIENT_ID,
                "placement_status": "moved",
                "placement_success": True,
            },
            raise_on_error=True,
        )

    assert "withheld-private-reveal-history-error" not in str(
        manager.log_callback.call_args_list
    )


def test_unknown_cancel_retains_the_durable_automatic_mutation_fence() -> None:
    manager = _manager()
    claimed: list[str] = []

    def cancel(_stealth_order_id, **kwargs):
        kwargs["before_cancel_call"]()
        return False

    manager.cancel_stealth_order = MagicMock(side_effect=cancel)

    with pytest.raises(RuntimeError, match="operator_move_cancel_unknown"):
        manager.cancel_operator_stealth_move(
            authority=_authority(),
            before_cancel_call=lambda: claimed.append("cancel"),
        )

    assert claimed == ["cancel"]
    state = manager.in_memory_orders[STEALTH_ID][
        "anchor_repricing_state_json"
    ]
    assert state["operator_move_cancel_pending"] is True
    assert state["operator_move_automatic_mutations_blocked"] is True
    assert state["operator_move_plan_sha256"] == "b" * 64
    assert manager._update_stealth_order.call_count == 1


def test_cancel_rejects_canonical_parent_target_drift_before_coinbase() -> None:
    manager = _manager()
    manager._resolve_operator_stealth_move_target_binding.return_value = (
        0.02,
        "P",
        "order_parent",
    )
    manager.cancel_stealth_order = MagicMock()

    with pytest.raises(
        ValueError,
        match="operator_move_authority_binding_invalid",
    ):
        manager.cancel_operator_stealth_move(
            authority=_authority(),
            before_cancel_call=lambda: None,
        )

    manager.cancel_stealth_order.assert_not_called()
    manager._update_stealth_order.assert_not_called()


def test_replacement_is_exact_post_only_one_call_and_value_blind() -> None:
    manager = _manager()
    manager.profit_validator = MagicMock()
    manager.profit_validator.derive_follow_up_price_from_target.return_value = (
        50001.0
    )
    manager.profit_validator.validate_order_profitability.return_value = {
        "is_profitable": True
    }
    state = manager.in_memory_orders[STEALTH_ID][
        "anchor_repricing_state_json"
    ]
    state["operator_move_cancel_returned"] = True
    state["operator_move_plan_sha256"] = "b" * 64
    state["operator_move_replacement_client_order_id"] = REPLACEMENT_CLIENT_ID
    rest_client = MagicMock()

    class _SuccessResponse:
        order_id = RAW_REPLACEMENT_ID

    class _SdkCreateResponse:
        success = True
        success_response = _SuccessResponse()

        def to_dict(self):
            raise AssertionError("shallow documented fields must be sufficient")

    def create_order(**kwargs):
        kwargs["before_sdk_call"]()
        return _SdkCreateResponse()

    rest_client.create_order.side_effect = create_order
    claimed: list[str] = []

    with (
        patch("configuration.REST_CLIENT", rest_client),
        patch("core.stealth_order_manager.insert_order_parent"),
        patch("core.stealth_order_manager.update_order_parent_status"),
    ):
        result = manager.place_operator_stealth_move_replacement(
            authority=_authority(),
            before_create_call=lambda: claimed.append("create"),
            before_wallet_read=lambda: claimed.append("wallet"),
            after_wallet_read=lambda result: claimed.append(result),
        )

    assert result == {
        "outcome": "ACCEPTED",
        "exchange_order_id": RAW_REPLACEMENT_ID,
    }
    assert claimed == ["wallet", "RETURNED", "create"]
    rest_client.create_order.assert_called_once()
    request = rest_client.create_order.call_args.kwargs
    assert request["client_order_id"] == REPLACEMENT_CLIENT_ID
    assert request["order_configuration"]["limit_limit_gtc"] == {
        "base_size": "0.00001",
        "limit_price": "50000.12",
        "post_only": True,
    }
    updated = manager.in_memory_orders[STEALTH_ID]
    anchor = updated["anchor_repricing_state_json"]
    assert anchor["active_placement_client_order_id"] == REPLACEMENT_CLIENT_ID
    assert anchor["active_exchange_order_id"] == RAW_REPLACEMENT_ID
    assert "operator_move_cancel_returned" not in anchor
    assert anchor["operator_move_reconciliation_pending"] is True
    assert anchor["operator_move_automatic_mutations_blocked"] is True
    assert anchor["operator_move_plan_sha256"] == "b" * 64
    assert (
        anchor["operator_move_replacement_client_order_id"]
        == REPLACEMENT_CLIENT_ID
    )
    manager._evaluate_action_condition_guard.assert_called_once()
    guard = manager._evaluate_action_condition_guard.call_args.kwargs
    assert guard["size"] == 0.00001
    assert guard["limit_price"] == 50000.12
    assert "existing_size" not in guard
    manager._evaluate_replacement_action_condition_guard.assert_not_called()
    assert updated["revealed_orders"][-1]["exchange_order_id"] is None
    assert updated["revealed_orders"][-1][
        "previous_exchange_order_id"
    ] is None
    assert RAW_SOURCE_ID not in str(updated["revealed_orders"])
    assert RAW_REPLACEMENT_ID not in str(updated["revealed_orders"])
    assert (
        manager.try_claim_mutation(StealthMutationKind.MOVE, STEALTH_ID)
        is True
    )


def test_replacement_rejects_target_drift_before_wallet_or_create() -> None:
    manager = _manager()
    state = manager.in_memory_orders[STEALTH_ID][
        "anchor_repricing_state_json"
    ]
    state["operator_move_cancel_returned"] = True
    state["operator_move_plan_sha256"] = "b" * 64
    state["operator_move_replacement_client_order_id"] = REPLACEMENT_CLIENT_ID
    manager._resolve_operator_stealth_move_target_binding.return_value = (
        0.02,
        "P",
        "order_parent",
    )

    with pytest.raises(
        ValueError,
        match="operator_move_authority_binding_invalid",
    ):
        manager.place_operator_stealth_move_replacement(
            authority=_authority(),
            before_create_call=lambda: None,
            before_wallet_read=lambda: None,
            after_wallet_read=lambda _: None,
        )

    manager._evaluate_action_condition_guard.assert_not_called()


def test_replacement_wallet_read_is_mandatory_and_fails_closed() -> None:
    manager = _manager()
    state = manager.in_memory_orders[STEALTH_ID][
        "anchor_repricing_state_json"
    ]
    state["operator_move_cancel_returned"] = True
    state["operator_move_plan_sha256"] = "b" * 64
    state["operator_move_replacement_client_order_id"] = REPLACEMENT_CLIENT_ID
    manager._get_account_wallets_for_action_guard.side_effect = RuntimeError(
        "withheld-private-wallet-error"
    )
    rest_client = MagicMock()
    reads: list[str] = []

    with patch("configuration.REST_CLIENT", rest_client):
        result = manager.place_operator_stealth_move_replacement(
            authority=_authority(),
            before_create_call=lambda: pytest.fail(
                "Create must not be claimed after an unknown wallet read"
            ),
            before_wallet_read=lambda: reads.append("wallet"),
            after_wallet_read=lambda value: reads.append(value),
        )

    assert result == {
        "outcome": "WALLET_UNKNOWN",
        "exchange_order_id": None,
    }
    assert reads == ["wallet", "UNKNOWN"]
    rest_client.create_order.assert_not_called()
    assert "withheld-private-wallet-error" not in str(
        manager.log_callback.call_args_list
    )


def test_unknown_create_keeps_preinserted_evidence_nonterminal_and_value_blind() -> None:
    manager = _manager()
    manager.profit_validator = MagicMock()
    manager.profit_validator.derive_follow_up_price_from_target.return_value = (
        50001.0
    )
    manager.profit_validator.validate_order_profitability.return_value = {
        "is_profitable": True
    }
    state = manager.in_memory_orders[STEALTH_ID][
        "anchor_repricing_state_json"
    ]
    state["operator_move_cancel_returned"] = True
    state["operator_move_plan_sha256"] = "b" * 64
    state["operator_move_replacement_client_order_id"] = REPLACEMENT_CLIENT_ID
    rest_client = MagicMock()

    def create_order(**kwargs):
        kwargs["before_sdk_call"]()
        raise RuntimeError("withheld-private-exception-text")

    rest_client.create_order.side_effect = create_order
    claimed: list[str] = []

    with (
        patch("configuration.REST_CLIENT", rest_client),
        patch("core.stealth_order_manager.insert_order_parent"),
        patch(
            "core.stealth_order_manager.update_order_parent_status"
        ) as update_status,
    ):
        result = manager.place_operator_stealth_move_replacement(
            authority=_authority(),
            before_create_call=lambda: claimed.append("create"),
            before_wallet_read=lambda: claimed.append("wallet"),
            after_wallet_read=lambda result: claimed.append(result),
        )

    assert result == {"outcome": "UNKNOWN", "exchange_order_id": None}
    assert claimed == ["wallet", "RETURNED", "create"]
    update_status.assert_not_called()
    assert "withheld-private-exception-text" not in str(
        manager.log_callback.call_args_list
    )
    assert (
        manager.in_memory_orders[STEALTH_ID][
            "anchor_repricing_state_json"
        ]["operator_move_cancel_returned"]
        is True
    )


def test_exact_reconciliation_clears_pending_fence() -> None:
    manager = _manager()
    state = manager.in_memory_orders[STEALTH_ID][
        "anchor_repricing_state_json"
    ]
    state.update(
        {
            "active_placement_client_order_id": REPLACEMENT_CLIENT_ID,
            "active_exchange_order_id": RAW_REPLACEMENT_ID,
            "operator_move_reconciliation_pending": True,
            "operator_move_automatic_mutations_blocked": True,
            "operator_move_plan_sha256": "b" * 64,
            "operator_move_replacement_client_order_id": (
                REPLACEMENT_CLIENT_ID
            ),
        }
    )

    manager.complete_operator_stealth_move_reconciliation(
        authority=_authority(),
        replacement_exchange_order_id=RAW_REPLACEMENT_ID,
    )

    updated = manager.in_memory_orders[STEALTH_ID][
        "anchor_repricing_state_json"
    ]
    assert "operator_move_reconciliation_pending" not in updated
    assert "operator_move_plan_sha256" not in updated
    assert "operator_move_replacement_client_order_id" not in updated
    assert updated["operator_move_automatic_mutations_blocked"] is True
    manager._update_stealth_order.assert_called_once()


def test_reconciliation_persistence_failure_is_observable_and_keeps_block() -> None:
    manager = _manager()
    state = manager.in_memory_orders[STEALTH_ID][
        "anchor_repricing_state_json"
    ]
    state.update(
        {
            "active_placement_client_order_id": REPLACEMENT_CLIENT_ID,
            "active_exchange_order_id": RAW_REPLACEMENT_ID,
            "operator_move_reconciliation_pending": True,
            "operator_move_automatic_mutations_blocked": True,
            "operator_move_plan_sha256": "b" * 64,
            "operator_move_replacement_client_order_id": REPLACEMENT_CLIENT_ID,
        }
    )
    manager._update_stealth_order.return_value = False

    with pytest.raises(
        ValueError,
        match="operator_move_fence_persistence_failed",
    ):
        manager.complete_operator_stealth_move_reconciliation(
            authority=_authority(),
            replacement_exchange_order_id=RAW_REPLACEMENT_ID,
        )

    assert (
        manager.in_memory_orders[STEALTH_ID][
            "anchor_repricing_state_json"
        ]["operator_move_automatic_mutations_blocked"]
        is True
    )


def test_follow_up_creation_boundary_is_mutually_exclusive_with_goal7_move() -> None:
    manager = _manager()
    manager._create_follow_up_stealth_order_claimed = MagicMock(
        return_value="follow-up-id"
    )
    kwargs = {
        "original_stealth_order_id": STEALTH_ID,
        "side": "SELL",
        "total_size": 0.00001,
        "limit_price": 50001.0,
    }

    assert manager.try_claim_mutation(
        StealthMutationKind.MOVE,
        STEALTH_ID,
    )
    assert manager.create_follow_up_stealth_order(**kwargs) is None
    manager._create_follow_up_stealth_order_claimed.assert_not_called()
    manager.release_mutation(StealthMutationKind.MOVE, STEALTH_ID)

    state = manager.in_memory_orders[STEALTH_ID][
        "anchor_repricing_state_json"
    ]
    state["operator_move_automatic_mutations_blocked"] = True
    assert manager.create_follow_up_stealth_order(**kwargs) is None
    manager._create_follow_up_stealth_order_claimed.assert_not_called()
    state.pop("operator_move_automatic_mutations_blocked")

    def claimed_follow_up(**_kwargs):
        assert (
            manager.try_claim_mutation(
                StealthMutationKind.MOVE,
                STEALTH_ID,
            )
            is False
        )
        return "follow-up-id"

    manager._create_follow_up_stealth_order_claimed.side_effect = (
        claimed_follow_up
    )
    assert manager.create_follow_up_stealth_order(**kwargs) == "follow-up-id"
    assert manager.try_claim_mutation(
        StealthMutationKind.MOVE,
        STEALTH_ID,
    )


def test_operator_move_fences_block_background_repricing_and_reentry() -> None:
    manager = _manager()
    manager._get_active_stealth_orders = MagicMock(
        return_value=[STEALTH_ID]
    )
    manager._get_current_market_data = MagicMock(
        return_value={"source": "ticker", "bid": 50000.0, "ask": 50001.0}
    )
    manager.try_claim_mutation = MagicMock(return_value=True)
    controller = MagicMock()
    controller.is_admitting.return_value = True

    with (
        patch(
            "core.stealth_order_manager.get_runtime_controller",
            return_value=controller,
        ),
        patch(
            "core.stealth_order_manager.evaluate_product_capability",
            return_value=MagicMock(allowed=True),
        ),
    ):
        manager.in_memory_orders[STEALTH_ID][
            "anchor_repricing_state_json"
        ]["operator_move_cancel_returned"] = True
        assert manager.process_anchor_repricing_for_product("BTC-USDC") == 0
        assert manager.process_cancel_reentry_for_product("BTC-USDC") == 0
        manager.in_memory_orders[STEALTH_ID][
            "anchor_repricing_state_json"
        ].pop("operator_move_cancel_returned")
        manager.in_memory_orders[STEALTH_ID][
            "anchor_repricing_state_json"
        ]["operator_move_reconciliation_pending"] = True
        assert manager.process_anchor_repricing_for_product("BTC-USDC") == 0
        assert manager.process_cancel_reentry_for_product("BTC-USDC") == 0
        manager.in_memory_orders[STEALTH_ID][
            "anchor_repricing_state_json"
        ].pop("operator_move_reconciliation_pending")
        manager.in_memory_orders[STEALTH_ID][
            "anchor_repricing_state_json"
        ]["operator_move_automatic_mutations_blocked"] = True
        assert manager.process_anchor_repricing_for_product("BTC-USDC") == 0
        assert manager.process_cancel_reentry_for_product("BTC-USDC") == 0

    manager.try_claim_mutation.assert_not_called()
