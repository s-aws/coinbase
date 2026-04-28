"""Regression: anchor reprice must not create a phantom 0-size order_parent.

Production incident 2026-04-27: stealth order ``df4ff32c`` had its
``remaining_size`` driven to 0 by an exchange fill, but the next
anchor-reprice tick (running on a 2-minute timer) did not consult
``remaining_size`` before issuing a cancel-and-replace.  The result was a
``REST_CLIENT.cancel_orders([already_filled_order_id])`` call followed by a
``place_limit_order(base_size="0", limit_price=...)`` and an
``insert_order_parent(size=0.0, ...)`` row.  See ``order_parent`` row 225 for
``71b744bf-4fb8-47d6-bf7e-35ba690c90df`` in the production audit.

The fix in ``StealthOrderManager._apply_revealed_anchor_reprice`` is a
precondition guard: when ``remaining_size <= 0`` the function clears the
stale ``active_*`` fields in the reprice state and returns ``False`` without
making any REST call or DB write.
"""

from unittest.mock import MagicMock

from core.stealth_order_manager import StealthOrderManager


def _make_manager():
    manager = StealthOrderManager(db_client=None, log_callback=MagicMock())
    manager._save_stealth_order_to_db = MagicMock()
    manager._update_stealth_order = MagicMock()
    return manager


def test_anchor_reprice_skips_when_remaining_size_zero(monkeypatch):
    """No cancel, no place, no DB write when there is nothing left to reprice."""
    manager = _make_manager()

    # `REST_CLIENT` is imported lazily inside the function from `configuration`,
    # so we patch the canonical module attribute.  ``insert_order_parent`` is
    # imported at module top of `core.stealth_order_manager`.
    import configuration as _configuration
    rest_client = MagicMock()
    monkeypatch.setattr(_configuration, "REST_CLIENT", rest_client, raising=True)

    insert_parent_calls = []
    monkeypatch.setattr(
        "core.stealth_order_manager.insert_order_parent",
        lambda **kwargs: insert_parent_calls.append(kwargs),
        raising=True,
    )

    order = {
        "stealth_order_id": "stealth-1",
        "product_id": "BIP-20DEC30-CDE",
        "side": "SELL",
        "limit_price": 77150.0,
        "remaining_size": 0.0,        # <-- precondition that must short-circuit
        "revealed_size": 25.0,
        "anchor_repricing_policy_json": {"enabled": True, "post_only_required": True},
    }
    state = {
        "active_exchange_order_id": "stale-exchange-id",  # left over from filled order
        "active_exchange_price": 77150.0,
        "active_placement_client_order_id": "stale-placement-uuid",
    }
    market_data = {"bid": 77105.0, "ask": 77115.0, "price": 77110.0, "source": "ticker"}

    result = manager._apply_revealed_anchor_reprice(
        order=order,
        policy=order["anchor_repricing_policy_json"],
        state=state,
        market_data=market_data,
        desired_price=77110.0,
        target_price=77110.0,
        max_boundary_price=77200.0,
        reprice_reason="reference_price_updated_slide_step",
    )

    # Function returned without doing work.
    assert result is False

    # No REST calls — would have hit a filled order on the exchange.
    rest_client.cancel_orders.assert_not_called()
    rest_client.place_limit_order.assert_not_called()

    # No DB write — would have produced a phantom size-0 order_parent row.
    assert insert_parent_calls == []

    # Stale state cleared so the next reveal cycle starts clean.
    assert state["active_exchange_order_id"] is None
    assert state["active_placement_client_order_id"] is None


def test_anchor_reprice_proceeds_when_remaining_size_positive(monkeypatch):
    """Sanity: the guard does not block legitimate reprice attempts."""
    manager = _make_manager()

    # The function early-returns at the second guard
    # (`if not exchange_order_id or current_price is None`) when the
    # exchange-id field is missing — that is enough to confirm the new
    # remaining-size guard does NOT short-circuit a positive remaining_size.
    import configuration as _configuration
    monkeypatch.setattr(_configuration, "REST_CLIENT", MagicMock(), raising=True)
    insert_parent_calls = []
    monkeypatch.setattr(
        "core.stealth_order_manager.insert_order_parent",
        lambda **kwargs: insert_parent_calls.append(kwargs),
        raising=True,
    )

    order = {
        "stealth_order_id": "stealth-2",
        "product_id": "BIP-20DEC30-CDE",
        "side": "SELL",
        "limit_price": 77150.0,
        "remaining_size": 25.0,        # <-- positive: guard must NOT short-circuit
        "revealed_size": 0.0,
        "anchor_repricing_policy_json": {"enabled": True, "post_only_required": True},
    }
    state = {
        # No active_exchange_order_id -> second guard triggers, but only
        # after the new remaining_size guard has been crossed.
        "active_exchange_order_id": None,
        "active_exchange_price": 77150.0,
        "active_placement_client_order_id": "placement-uuid",
    }
    market_data = {"bid": 77105.0, "ask": 77115.0, "price": 77110.0, "source": "ticker"}

    result = manager._apply_revealed_anchor_reprice(
        order=order,
        policy=order["anchor_repricing_policy_json"],
        state=state,
        market_data=market_data,
        desired_price=77110.0,
        target_price=77110.0,
        max_boundary_price=77200.0,
        reprice_reason="reference_price_updated_slide_step",
    )

    assert result is False  # still False, but for the existing reason (no exchange id)

    # The remaining-size guard would have nulled `active_placement_client_order_id`.
    # The fact that it survives proves the new guard didn't fire on a positive remaining_size.
    assert state["active_placement_client_order_id"] == "placement-uuid"
