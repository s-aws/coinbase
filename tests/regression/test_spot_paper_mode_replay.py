"""Paper-mode replay for the spot readiness path."""

from datetime import datetime

import pytest

from business.spot_inventory_authority import evaluate_spot_sell_lot_authority
from core.action_condition_guard import ActionConditionGuard
from core.enums import (
    ActionConditionType,
    ActionGuardPhase,
    InventoryAuthorityStatus,
    OrderSide,
)


pytestmark = pytest.mark.regression


PRODUCT_METADATA = {
    "BTC-USD": {
        "product_id": "BTC-USD",
        "product_type": "SPOT",
        "base_currency": "BTC",
        "quote_currency": "USD",
    },
}


def _wallet(currency, value):
    return {currency: {"available_balance": {"value": str(value)}}}


def _fill_row(
    *,
    key="paper-buy-fill",
    product_id="BTC-USD",
    quantity=0.1,
    price=90000.0,
    fees=1.0,
):
    return {
        "derived_trade_key": key,
        "instrument": product_id,
        "product_id": product_id,
        "side": OrderSide.BUY.value,
        "quantity": quantity,
        "price": price,
        "timestamp": datetime(2026, 1, 1, 12, 0, 0),
        "fees": fees,
        "commission_percentage": 0.0,
        "client_order_id": f"coid-{key}",
        "reconciliation_status": "WS_DERIVED",
    }


class PaperFillRepo:
    def __init__(self):
        self.rows = []

    def append_fill_row(self, row):
        self.rows.append(row)

    def get_fills_by_product(self, product_id, side=None):
        from business.fill_ledger import FillLedger

        rows = [
            row
            for row in self.rows
            if row["product_id"] == product_id
            and (side is None or row["side"] == side)
        ]
        return [FillLedger.from_dict(row) for row in rows]

    def get_fills_by_instrument(self, instrument):
        from business.fill_ledger import FillLedger

        return [
            FillLedger.from_dict(row)
            for row in self.rows
            if row["instrument"] == instrument
        ]


def test_paper_mode_spot_replay_covers_wallet_budget_reveal_and_lots():
    buy_guard = ActionConditionGuard(
        policy={ActionConditionType.WALLET_AVAILABLE.value: {"enabled": True}},
        credentials_configured=lambda: True,
        wallet_fetcher=lambda: _wallet("USD", 100.0),
        planned_budget_fetcher=lambda: {},
        product_metadata=PRODUCT_METADATA,
        spot_product_ids=["BTC-USD"],
    )

    ok, failure = buy_guard.evaluate(
        phase=ActionGuardPhase.PLANNING,
        product_id="BTC-USD",
        side=OrderSide.BUY.value,
        quote_size=80.0,
    )

    assert ok is True
    assert failure is None

    planned_budget_guard = ActionConditionGuard(
        policy={ActionConditionType.WALLET_AVAILABLE.value: {"enabled": True}},
        credentials_configured=lambda: True,
        wallet_fetcher=lambda: _wallet("USD", 100.0),
        planned_budget_fetcher=lambda: {"USD": 90.0},
        product_metadata=PRODUCT_METADATA,
        spot_product_ids=["BTC-USD"],
    )

    ok, failure = planned_budget_guard.evaluate(
        phase=ActionGuardPhase.PLANNING,
        product_id="BTC-USD",
        side=OrderSide.BUY.value,
        quote_size=20.0,
    )

    assert ok is False
    assert failure["block_category"] == (
        ActionConditionType.PLANNED_BUDGET_AVAILABLE.value
    )
    assert failure["available_after_planned"] == pytest.approx(10.0)

    reveal_guard = ActionConditionGuard(
        policy={ActionConditionType.WALLET_AVAILABLE.value: {"enabled": True}},
        credentials_configured=lambda: True,
        wallet_fetcher=lambda: _wallet("USD", 5.0),
        planned_budget_fetcher=lambda: {},
        product_metadata=PRODUCT_METADATA,
        spot_product_ids=["BTC-USD"],
    )

    ok, failure = reveal_guard.evaluate(
        phase=ActionGuardPhase.REVEAL,
        product_id="BTC-USD",
        side=OrderSide.BUY.value,
        quote_size=20.0,
    )

    assert ok is False
    assert failure["block_category"] == ActionConditionType.WALLET_AVAILABLE.value
    assert failure["currency"] == "USD"

    fill_repo = PaperFillRepo()
    fill_repo.append_fill_row(_fill_row())

    lot_decision = evaluate_spot_sell_lot_authority(
        product_id="BTC-USD",
        side=OrderSide.SELL.value,
        size=0.05,
        limit_price=100000.0,
        fill_ledger_repo=fill_repo,
        profit_target_pct=0.5,
    )

    assert lot_decision.allowed is True
    assert lot_decision.status == InventoryAuthorityStatus.KNOWN_PROFITABLE.value
    assert lot_decision.known_profitable_quantity == pytest.approx(0.1)

    sell_guard = ActionConditionGuard(
        policy={
            ActionConditionType.WALLET_AVAILABLE.value: {"enabled": False},
            ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value: {
                "enabled": True,
            },
        },
        lot_authority_evaluator=lambda **kwargs: evaluate_spot_sell_lot_authority(
            fill_ledger_repo=fill_repo,
            profit_target_pct=0.5,
            **kwargs,
        ).to_dict(),
        product_metadata=PRODUCT_METADATA,
        spot_product_ids=["BTC-USD"],
    )

    ok, failure = sell_guard.evaluate(
        phase=ActionGuardPhase.PLANNING,
        product_id="BTC-USD",
        side=OrderSide.SELL.value,
        size=0.05,
        limit_price=100000.0,
    )

    assert ok is True
    assert failure is None

    ok, failure = sell_guard.evaluate(
        phase=ActionGuardPhase.PLANNING,
        product_id="BTC-USD",
        side=OrderSide.SELL.value,
        size=0.2,
        limit_price=100000.0,
    )

    assert ok is False
    assert failure["block_category"] == (
        ActionConditionType.KNOWN_INVENTORY_AVAILABLE.value
    )
