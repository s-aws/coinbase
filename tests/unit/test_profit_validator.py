"""Unit tests for ProfitValidator shared target-to-price helpers."""

from calculation.profit_validator import ProfitValidator


class TestDeriveFollowUpPriceFromTarget:
    def test_buy_percentage_target(self):
        validator = ProfitValidator()
        price = validator.derive_follow_up_price_from_target(
            parent_filled_price=100.0,
            parent_side="BUY",
            target_movement=0.01,
            target_movement_type="P",
        )
        assert price == 101.0

    def test_sell_percentage_target(self):
        validator = ProfitValidator()
        price = validator.derive_follow_up_price_from_target(
            parent_filled_price=100.0,
            parent_side="SELL",
            target_movement=0.01,
            target_movement_type="P",
        )
        assert price == 99.0

    def test_buy_absolute_target(self):
        validator = ProfitValidator()
        price = validator.derive_follow_up_price_from_target(
            parent_filled_price=100.0,
            parent_side="BUY",
            target_movement=2.5,
            target_movement_type="A",
        )
        assert price == 102.5

    def test_invalid_side_returns_none(self):
        validator = ProfitValidator()
        price = validator.derive_follow_up_price_from_target(
            parent_filled_price=100.0,
            parent_side="HOLD",
            target_movement=0.01,
            target_movement_type="P",
        )
        assert price is None

    def test_invalid_target_type_defaults_to_percentage(self):
        validator = ProfitValidator()
        price = validator.derive_follow_up_price_from_target(
            parent_filled_price=100.0,
            parent_side="BUY",
            target_movement=0.01,
            target_movement_type="UNKNOWN",
        )
        assert price == 101.0
