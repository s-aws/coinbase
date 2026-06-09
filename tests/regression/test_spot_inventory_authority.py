"""Regression tests for spot inventory and known-cost lot authority."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from business.fill_ledger import FillLedgerRepository
from business.lot_builder import PositionLotBuilder
from business.spot_inventory_authority import evaluate_spot_sell_lot_authority
from core.action_condition_guard import ActionConditionGuard
from core.enums import (
    ActionConditionType,
    ActionGuardPhase,
    InventoryAuthorityStatus,
    InventoryCostBasisStatus,
    InventoryLotSource,
    OrderSide,
)


pytestmark = pytest.mark.regression


def _repo_with_fills(rows):
    repo = FillLedgerRepository.__new__(FillLedgerRepository)
    repo.db_client = MagicMock()
    repo.db_client.execute_query.return_value = rows
    return repo


def _fill_row(
    *,
    key="fill-1",
    product_id="BTC-USD",
    side=OrderSide.BUY.value,
    quantity=0.1,
    price=90000.0,
    fees=0.0,
):
    timestamp = datetime(2026, 1, 1, 12, 0, 0)
    return {
        "derived_trade_key": key,
        "instrument": product_id,
        "product_id": product_id,
        "side": side,
        "quantity": quantity,
        "price": price,
        "timestamp": timestamp,
        "fees": fees,
        "commission_percentage": 0.0,
        "client_order_id": f"coid-{key}",
        "reconciliation_status": "WS_DERIVED",
    }


def test_fill_ledger_repository_exposes_get_fills_by_instrument():
    repo = _repo_with_fills([_fill_row(key="a"), _fill_row(key="b")])

    fills = repo.get_fills_by_instrument("BTC-USD")

    assert len(fills) == 2
    assert fills[0].derived_trade_key == "a"
    repo.db_client.execute_query.assert_called_once()
    query, params = repo.db_client.execute_query.call_args.args
    assert "WHERE instrument = %s" in query
    assert params == ("BTC-USD",)


def test_imported_unknown_cost_basis_lot_is_not_profitable():
    repo = _repo_with_fills([])
    builder = PositionLotBuilder(
        repo,
        inventory_baselines=[
            {
                "product_id": "BTC-USD",
                "quantity": 0.25,
                "cost_basis_status": InventoryCostBasisStatus.UNKNOWN.value,
                "source_id": "external-wallet",
            },
        ],
    )

    position = builder.build_position_by_product("BTC-USD")

    assert position.remaining_quantity == pytest.approx(0.25)
    lot = position.lots[0]
    assert lot.cost_basis_status == InventoryCostBasisStatus.UNKNOWN
    assert lot.lot_source == InventoryLotSource.IMPORTED_BASELINE
    assert lot.can_exit_profitably_at(100000.0) is False


def test_known_baseline_inventory_can_satisfy_spot_sell_authority():
    repo = _repo_with_fills([])

    decision = evaluate_spot_sell_lot_authority(
        product_id="BTC-USD",
        side=OrderSide.SELL.value,
        size=0.1,
        limit_price=100000.0,
        fill_ledger_repo=repo,
        inventory_baselines=[
            {
                "product_id": "BTC-USD",
                "quantity": 0.25,
                "entry_price": 90000.0,
                "source_id": "baseline-known",
            },
        ],
        profit_target_pct=0.5,
    )

    assert decision.allowed is True
    assert decision.status == InventoryAuthorityStatus.KNOWN_PROFITABLE.value
    assert decision.known_profitable_quantity == pytest.approx(0.25)
    assert decision.unknown_cost_basis_quantity == pytest.approx(0.0)


def test_fill_ledger_lots_can_satisfy_spot_sell_authority():
    repo = _repo_with_fills([
        _fill_row(key="fill-known", quantity=0.15, price=90000.0),
    ])

    decision = evaluate_spot_sell_lot_authority(
        product_id="BTC-USD",
        side=OrderSide.SELL.value,
        size=0.1,
        limit_price=100000.0,
        fill_ledger_repo=repo,
        profit_target_pct=0.5,
    )

    assert decision.allowed is True
    assert decision.status == InventoryAuthorityStatus.KNOWN_PROFITABLE.value
    assert decision.known_profitable_quantity == pytest.approx(0.15)
    assert decision.unknown_cost_basis_quantity == pytest.approx(0.0)


def test_unknown_baseline_inventory_blocks_known_profit_authority():
    repo = _repo_with_fills([])

    decision = evaluate_spot_sell_lot_authority(
        product_id="BTC-USD",
        side=OrderSide.SELL.value,
        size=0.1,
        limit_price=100000.0,
        fill_ledger_repo=repo,
        inventory_baselines=[
            {
                "product_id": "BTC-USD",
                "quantity": 0.25,
                "cost_basis_status": InventoryCostBasisStatus.UNKNOWN.value,
                "source_id": "baseline-unknown",
            },
        ],
        profit_target_pct=0.5,
    )

    assert decision.allowed is False
    assert decision.status == InventoryAuthorityStatus.UNKNOWN_COST_BASIS.value
    assert decision.known_profitable_quantity == pytest.approx(0.0)
    assert decision.unknown_cost_basis_quantity == pytest.approx(0.25)


def test_action_guard_known_inventory_condition_blocks_spot_sell():
    guard = ActionConditionGuard(
        policy={
            ActionConditionType.WALLET_AVAILABLE.value: {"enabled": False},
            ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value: {
                "enabled": True,
            },
        },
        lot_authority_evaluator=lambda **kwargs: {
            "allowed": False,
            "status": InventoryAuthorityStatus.UNKNOWN_COST_BASIS.value,
            "reason": "inventory has unknown cost basis",
            "unknown_cost_basis_quantity": 0.25,
        },
    )

    ok, failure = guard.evaluate(
        phase=ActionGuardPhase.PLANNING,
        product_id="BTC-USD",
        side=OrderSide.SELL.value,
        size=0.1,
        limit_price=100000.0,
    )

    assert ok is False
    assert failure["block_category"] == (
        ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value
    )
    assert failure["inventory_authority"]["status"] == (
        InventoryAuthorityStatus.UNKNOWN_COST_BASIS.value
    )


def test_action_guard_known_inventory_condition_allows_non_spot_and_buy():
    evaluator = MagicMock()
    guard = ActionConditionGuard(
        policy={
            ActionConditionType.WALLET_AVAILABLE.value: {"enabled": False},
            ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value: {
                "enabled": True,
            },
        },
        lot_authority_evaluator=evaluator,
    )

    futures_ok, _ = guard.evaluate(
        phase=ActionGuardPhase.PLANNING,
        product_id="BIP-20DEC30-CDE",
        side=OrderSide.SELL.value,
        size=1.0,
        limit_price=100000.0,
    )
    buy_ok, _ = guard.evaluate(
        phase=ActionGuardPhase.PLANNING,
        product_id="BTC-USD",
        side=OrderSide.BUY.value,
        size=0.1,
        limit_price=100000.0,
    )

    assert futures_ok is True
    assert buy_ok is True
    evaluator.assert_not_called()
