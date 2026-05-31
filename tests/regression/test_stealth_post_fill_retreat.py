from pathlib import Path
from unittest.mock import MagicMock

import pytest

from business.post_fill_retreat_policy import PostFillRetreatPolicy
from core.enums import PostFillRetreatScope, StealthOrderStatus
from core.stealth_order_manager import StealthOrderManager


RETREAT_PRODUCT_ID = "BIP-20DEC30-CDE"


def _manager() -> StealthOrderManager:
    manager = StealthOrderManager(db_client=None, log_callback=MagicMock())
    manager._update_stealth_order = MagicMock()
    return manager


def _source_order() -> dict:
    return {
        "stealth_order_id": "source-sell",
        "product_id": RETREAT_PRODUCT_ID,
        "side": "SELL",
        "limit_price": 90.0,
        "status": StealthOrderStatus.REVEALED.value,
        "anchor_repricing_state_json": {
            "active_placement_client_order_id": "source-placement",
            "active_exchange_price": 90.0,
        },
    }


def _hidden_order(stealth_order_id: str, price: float, *, enabled: bool = True) -> dict:
    return {
        "stealth_order_id": stealth_order_id,
        "product_id": RETREAT_PRODUCT_ID,
        "side": "SELL",
        "limit_price": price,
        "status": StealthOrderStatus.HIDDEN.value,
        "reveal_condition_json": {
            "type": "price",
            "price_threshold": price - 2.0,
            "direction": "above",
        },
        "anchor_repricing_state_json": {},
        "post_fill_retreat_policy_json": {
            "enabled": enabled,
            "scope": PostFillRetreatScope.SAME_PRODUCT_SAME_SIDE.value,
            "retreat_ticks": 1,
        },
    }


@pytest.mark.regression
def test_post_fill_retreat_policy_round_trip():
    raw = {
        "enabled": True,
        "scope": "same_product_same_side",
        "retreat_ticks": 2,
        "inherit_to_follow_ups": False,
    }

    policy = PostFillRetreatPolicy.from_dict(raw)

    assert policy.enabled is True
    assert policy.scope is PostFillRetreatScope.SAME_PRODUCT_SAME_SIDE
    assert policy.retreat_ticks == 2
    assert policy.to_dict() == raw
    assert PostFillRetreatPolicy.from_dict(None).to_dict() == {"enabled": False}


@pytest.mark.regression
def test_create_stealth_order_stores_post_fill_retreat_policy(monkeypatch):
    manager = _manager()
    monkeypatch.setattr("core.stealth_order_manager.insert_order_parent", lambda **kwargs: None)

    stealth_id = manager.create_stealth_order(
        product_id=RETREAT_PRODUCT_ID,
        side="SELL",
        total_size=1.0,
        limit_price=100.0,
        reveal_condition={"type": "time_delay", "delay_seconds": 0},
        target_movement=0.0,
        post_fill_retreat_policy={
            "enabled": True,
            "scope": "same_product_same_side",
            "retreat_ticks": 2,
        },
    )

    order = manager.in_memory_orders[stealth_id]
    assert order["post_fill_retreat_policy_json"]["enabled"] is True
    assert order["post_fill_retreat_policy_json"]["retreat_ticks"] == 2


@pytest.mark.regression
def test_same_side_post_fill_retreat_moves_nearest_hidden_order_and_threshold():
    manager = _manager()
    source = _source_order()
    nearest = _hidden_order("hidden-nearest", 100.0)
    farther = _hidden_order("hidden-farther", 110.0)
    manager.in_memory_orders = {
        "source-sell": source,
        "hidden-nearest": nearest,
        "hidden-farther": farther,
    }

    result = manager.apply_same_side_post_fill_retreat(
        source,
        filled_placement_client_order_id="source-placement",
        filled_price=90.0,
    )

    assert result["stealth_order_id"] == "hidden-nearest"
    assert nearest["limit_price"] == 105.0
    assert nearest["reveal_condition_json"]["price_threshold"] == 103.0
    assert nearest["condition_first_met_at"] is None
    assert nearest["condition_confirmed_at"] is None
    assert nearest["anchor_repricing_state_json"]["post_fill_retreat_offset"] == 5.0
    assert nearest["anchor_repricing_state_json"]["post_fill_retreat_count"] == 1
    assert "source-placement" in nearest["anchor_repricing_state_json"]["post_fill_retreat_source_order_ids"]
    assert farther["limit_price"] == 110.0
    manager._update_stealth_order.assert_called_once_with(nearest)


@pytest.mark.regression
def test_same_side_post_fill_retreat_is_idempotent_per_filled_placement():
    manager = _manager()
    source = _source_order()
    nearest = _hidden_order("hidden-nearest", 100.0)
    farther = _hidden_order("hidden-farther", 110.0)
    manager.in_memory_orders = {
        "source-sell": source,
        "hidden-nearest": nearest,
        "hidden-farther": farther,
    }

    first = manager.apply_same_side_post_fill_retreat(
        source,
        filled_placement_client_order_id="source-placement",
        filled_price=90.0,
    )
    second = manager.apply_same_side_post_fill_retreat(
        source,
        filled_placement_client_order_id="source-placement",
        filled_price=90.0,
    )

    assert first is not None
    assert second is None
    assert nearest["limit_price"] == 105.0
    assert farther["limit_price"] == 110.0
    manager._update_stealth_order.assert_called_once()


@pytest.mark.regression
def test_same_side_post_fill_retreat_buy_moves_lower():
    manager = _manager()
    source = {
        **_source_order(),
        "stealth_order_id": "source-buy",
        "side": "BUY",
        "limit_price": 110.0,
    }
    hidden = {
        **_hidden_order("hidden-buy", 100.0),
        "side": "BUY",
        "reveal_condition_json": {
            "type": "price",
            "price_threshold": 102.0,
            "direction": "below",
        },
    }
    manager.in_memory_orders = {"source-buy": source, "hidden-buy": hidden}

    result = manager.apply_same_side_post_fill_retreat(
        source,
        filled_placement_client_order_id="source-buy-placement",
        filled_price=110.0,
    )

    assert result["stealth_order_id"] == "hidden-buy"
    assert hidden["limit_price"] == 95.0
    assert hidden["reveal_condition_json"]["price_threshold"] == 97.0
    assert hidden["anchor_repricing_state_json"]["post_fill_retreat_offset"] == -5.0


@pytest.mark.regression
def test_post_fill_retreat_offset_survives_future_anchor_reprice_targets():
    manager = _manager()
    targets = {
        "target_price": 100.0,
        "max_boundary_price": 110.0,
        "target_distance_amount": 10.0,
        "max_distance_amount": 20.0,
    }

    adjusted = manager._apply_post_fill_retreat_offset_to_target_prices(
        targets,
        {"post_fill_retreat_offset": 5.0},
    )

    assert adjusted["target_price"] == 105.0
    assert adjusted["max_boundary_price"] == 115.0
    assert targets["target_price"] == 100.0


@pytest.mark.regression
def test_post_fill_retreat_ui_and_dashboard_contract_are_wired():
    repo_root = Path(__file__).resolve().parents[2]
    manager_html = (repo_root / "ui_stealth_orders_manager.html").read_text(encoding="utf-8")
    span_html = (repo_root / "ui_order_span_builder.html").read_text(encoding="utf-8")
    dashboard = (repo_root / "dashboard_server.py").read_text(encoding="utf-8")

    for html in (manager_html, span_html):
        assert 'id="enable_post_fill_retreat_policy"' in html
        assert "function buildPostFillRetreatPolicy()" in html
        assert "post_fill_retreat_policy:" in html

    assert "post_fill_retreat_policy=order.get('post_fill_retreat_policy')" in dashboard
    assert "post_fill_retreat_policy_json" in dashboard
