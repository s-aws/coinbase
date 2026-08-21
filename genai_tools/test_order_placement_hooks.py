"""Tests for OrderPlacementHookRegistry integration.

Validates pre/post submission hooks for order placement with:
- Hook registration
- Pre-submission validation and modification
- Pre-submission blocking (exception handling)
- Post-submission logging/tracking
- Thread safety
- Error isolation
"""

import pytest
import uuid
from integration.order_placement_hooks import (
    OrderPlacementHookRegistry,
    get_global_placement_hook_registry,
    reset_global_placement_hook_registry,
)


class TestOrderPlacementHookRegistry:
    """Test OrderPlacementHookRegistry functionality."""

    def setup_method(self):
        """Reset global registry before each test."""
        reset_global_placement_hook_registry()

    def test_registry_creation(self):
        """Test registry can be created."""
        registry = OrderPlacementHookRegistry()
        assert registry is not None
        assert len(registry._pre_submission_hooks) == 0
        assert len(registry._post_submission_hooks) == 0

    def test_register_pre_submission_hook(self):
        """Test pre-submission hook registration."""
        registry = OrderPlacementHookRegistry()

        def my_hook(order):
            pass

        registry.register_pre_submission(my_hook)
        assert len(registry._pre_submission_hooks) == 1
        assert my_hook in registry._pre_submission_hooks

    def test_register_post_submission_hook(self):
        """Test post-submission hook registration."""
        registry = OrderPlacementHookRegistry()

        def my_hook(order, result):
            pass

        registry.register_post_submission(my_hook)
        assert len(registry._post_submission_hooks) == 1
        assert my_hook in registry._post_submission_hooks

    def test_multiple_pre_hooks_execute_in_order(self):
        """Test multiple pre-hooks execute sequentially."""
        registry = OrderPlacementHookRegistry()
        call_order = []

        def hook1(order):
            call_order.append(1)

        def hook2(order):
            call_order.append(2)

        def hook3(order):
            call_order.append(3)

        registry.register_pre_submission(hook1)
        registry.register_pre_submission(hook2)
        registry.register_pre_submission(hook3)

        order = {"product_id": "BTC-USDC", "side": "BUY"}
        registry.call_pre_submission_hooks(order)

        assert call_order == [1, 2, 3]

    def test_multiple_post_hooks_execute_in_order(self):
        """Test multiple post-hooks execute sequentially."""
        registry = OrderPlacementHookRegistry()
        call_order = []

        def hook1(order, result):
            call_order.append(1)

        def hook2(order, result):
            call_order.append(2)

        def hook3(order, result):
            call_order.append(3)

        registry.register_post_submission(hook1)
        registry.register_post_submission(hook2)
        registry.register_post_submission(hook3)

        order = {"product_id": "BTC-USDC", "side": "BUY"}
        result = {"order_id": "123"}
        registry.call_post_submission_hooks(order, result)

        assert call_order == [1, 2, 3]

    def test_pre_hook_can_modify_order(self):
        """Test pre-hook can modify order before submission."""
        registry = OrderPlacementHookRegistry()

        def normalize_price(order):
            # Round price to 2 decimals
            if "limit_price" in order:
                order["limit_price"] = round(order["limit_price"], 2)

        registry.register_pre_submission(normalize_price)

        order = {"product_id": "BTC-USDC", "side": "BUY", "limit_price": 42500.12345}
        registry.call_pre_submission_hooks(order)

        assert order["limit_price"] == 42500.12

    def test_pre_hook_can_block_submission(self):
        """Test pre-hook can block submission by raising exception."""
        registry = OrderPlacementHookRegistry()

        def validate_price(order):
            if order["limit_price"] <= 0:
                raise ValueError("Price must be positive")

        registry.register_pre_submission(validate_price)

        # Valid order
        order = {"product_id": "BTC-USDC", "side": "BUY", "limit_price": 100.0}
        registry.call_pre_submission_hooks(order)  # Should not raise

        # Invalid order
        order_invalid = {"product_id": "BTC-USDC", "side": "BUY", "limit_price": -50.0}
        with pytest.raises(ValueError, match="Price must be positive"):
            registry.call_pre_submission_hooks(order_invalid)

    def test_pre_hook_exception_stops_execution(self):
        """Test that exception in pre-hook stops further hooks."""
        registry = OrderPlacementHookRegistry()
        call_order = []

        def hook1(order):
            call_order.append(1)
            raise ValueError("Hook 1 failed")

        def hook2(order):
            call_order.append(2)

        registry.register_pre_submission(hook1)
        registry.register_pre_submission(hook2)

        order = {"product_id": "BTC-USDC"}
        with pytest.raises(ValueError, match="Hook 1 failed"):
            registry.call_pre_submission_hooks(order)

        # Only hook1 should have executed
        assert call_order == [1]
        assert 2 not in call_order

    def test_post_hook_exception_does_not_stop_others(self):
        """Test that exception in post-hook doesn't stop other hooks."""
        registry = OrderPlacementHookRegistry()
        call_order = []

        def hook1(order, result):
            call_order.append(1)
            raise ValueError("Hook 1 failed")

        def hook2(order, result):
            call_order.append(2)

        def hook3(order, result):
            call_order.append(3)

        registry.register_post_submission(hook1)
        registry.register_post_submission(hook2)
        registry.register_post_submission(hook3)

        order = {"product_id": "BTC-USDC"}
        result = {"order_id": "123"}

        # Post-hook exceptions are swallowed, so this should NOT raise
        registry.call_post_submission_hooks(order, result)

        # All hooks should have executed despite hook1 raising
        assert call_order == [1, 2, 3]

    def test_global_registry_singleton(self):
        """Test global registry is a singleton."""
        registry1 = get_global_placement_hook_registry()
        registry2 = get_global_placement_hook_registry()

        assert registry1 is registry2

    def test_global_registry_can_register_hooks(self):
        """Test hooks registered to global registry work."""
        reset_global_placement_hook_registry()
        registry = get_global_placement_hook_registry()

        call_count = []

        def my_hook(order):
            call_count.append(1)

        registry.register_pre_submission(my_hook)

        order = {"product_id": "BTC-USDC"}
        registry.call_pre_submission_hooks(order)

        assert len(call_count) == 1

    def test_hook_receives_order_reference(self):
        """Test that hooks receive order by reference."""
        registry = OrderPlacementHookRegistry()

        def add_metadata(order):
            order["hook_processed"] = True
            order["custom_field"] = "added_by_hook"

        registry.register_pre_submission(add_metadata)

        order = {"product_id": "BTC-USDC", "side": "BUY"}
        registry.call_pre_submission_hooks(order)

        assert order["hook_processed"] is True
        assert order["custom_field"] == "added_by_hook"

    def test_post_hook_receives_result(self):
        """Test post-hook receives order and result."""
        registry = OrderPlacementHookRegistry()
        received_data = {}

        def log_result(order, result):
            received_data["order"] = order
            received_data["result"] = result

        registry.register_post_submission(log_result)

        order = {"product_id": "BTC-USDC", "side": "BUY", "limit_price": 100.0}
        result = {"order_id": "123", "status": "PENDING"}

        registry.call_post_submission_hooks(order, result)

        assert received_data["order"] == order
        assert received_data["result"] == result

    def test_reset_global_registry(self):
        """Test resetting global registry clears hooks."""
        registry = get_global_placement_hook_registry()

        def my_hook(order):
            pass

        registry.register_pre_submission(my_hook)
        assert len(registry._pre_submission_hooks) == 1

        reset_global_placement_hook_registry()
        registry2 = get_global_placement_hook_registry()

        # Should be a new registry with no hooks
        assert len(registry2._pre_submission_hooks) == 0


class TestOrderPlacementHookIntegration:
    """Integration tests for order placement hooks with realistic scenarios."""

    def setup_method(self):
        """Reset global registry before each test."""
        reset_global_placement_hook_registry()

    def test_profitability_validation_pre_submission(self):
        """Test realistic scenario: validate profitability before submission."""
        registry = OrderPlacementHookRegistry()

        def check_profitability(order):
            """Block orders that won't be profitable."""
            minimum_profit_margin = 0.002  # 0.2%

            # In real scenario, would fetch actual prices
            # For test, we embed expected prices
            entry_price = order.get("entry_price", 100.0)
            exit_price = order.get("limit_price", 100.0)

            if order["side"] == "BUY":
                expected_profit = (exit_price - entry_price) / entry_price
            else:  # SELL
                expected_profit = (entry_price - exit_price) / entry_price

            if expected_profit < minimum_profit_margin:
                raise ValueError(
                    f"Order profit {expected_profit:.4%} below minimum {minimum_profit_margin:.2%}"
                )

        registry.register_pre_submission(check_profitability)

        # Profitable order
        order_good = {
            "product_id": "BTC-USDC",
            "side": "BUY",
            "entry_price": 100.0,
            "limit_price": 100.5,  # 0.5% profit
        }
        registry.call_pre_submission_hooks(order_good)  # Should pass

        # Unprofitable order
        order_bad = {
            "product_id": "BTC-USDC",
            "side": "BUY",
            "entry_price": 100.0,
            "limit_price": 100.1,  # 0.1% profit (below 0.2% minimum)
        }
        with pytest.raises(ValueError, match="below minimum"):
            registry.call_pre_submission_hooks(order_bad)

    def test_position_limit_validation(self):
        """Test validation: don't exceed position limits."""
        registry = OrderPlacementHookRegistry()

        # Simulated position tracking
        positions = {"BTC-USDC": {"BUY": 10.0}}  # Already have 10 BTC

        def check_position_limits(order):
            """Ensure order doesn't exceed max position."""
            max_position = 50.0  # Max 50 BTC per side

            product = order["product_id"]
            side = order["side"]
            size = float(order.get("base_size", 0))

            if product not in positions:
                positions[product] = {"BUY": 0, "SELL": 0}

            current = positions[product].get(side, 0)
            if current + size > max_position:
                raise ValueError(
                    f"Position limit exceeded: {current} + {size} > {max_position}"
                )

        registry.register_pre_submission(check_position_limits)

        # Order within limits
        order_ok = {
            "product_id": "BTC-USDC",
            "side": "BUY",
            "base_size": 20.0,  # 10 + 20 = 30 (OK)
        }
        registry.call_pre_submission_hooks(order_ok)

        # Order exceeds limit
        order_bad = {
            "product_id": "BTC-USDC",
            "side": "BUY",
            "base_size": 50.0,  # 10 + 50 = 60 (exceeds 50)
        }
        with pytest.raises(ValueError, match="Position limit exceeded"):
            registry.call_pre_submission_hooks(order_bad)

    def test_real_time_price_adjustment(self):
        """Test modifying order price based on real-time market data."""
        registry = OrderPlacementHookRegistry()

        # Simulated market data
        market_data = {
            "BTC-USDC": {"last_price": 100.50, "bid": 100.48, "ask": 100.52}
        }

        def adjust_to_market(order):
            """Adjust limit price to be competitive."""
            product = order["product_id"]
            side = order["side"]

            if product not in market_data:
                return

            market = market_data[product]
            current_limit = float(order.get("limit_price", 0))

            if side == "BUY":
                # BUY orders: use bid as reference, maybe 0.1% higher to be competitive
                competitive_price = market["bid"] * 1.001
                if current_limit < competitive_price:
                    order["limit_price"] = round(competitive_price, 2)
            else:  # SELL
                # SELL orders: use ask as reference, maybe 0.1% lower to be competitive
                competitive_price = market["ask"] * 0.999
                if current_limit > competitive_price:
                    order["limit_price"] = round(competitive_price, 2)

        registry.register_pre_submission(adjust_to_market)

        order = {
            "product_id": "BTC-USDC",
            "side": "BUY",
            "limit_price": 100.40,  # Below competitive price
        }
        registry.call_pre_submission_hooks(order)

        # Should have been adjusted to competitive price (100.48 * 1.001 = 100.57648 → 100.58)
        assert order["limit_price"] == 100.58

    def test_chained_validation_and_modification(self):
        """Test multiple hooks that both validate and modify."""
        registry = OrderPlacementHookRegistry()

        def validate_size(order):
            """Ensure size is reasonable."""
            if float(order.get("base_size", 0)) <= 0:
                raise ValueError("Size must be positive")

        def round_size(order):
            """Round size to trading increment."""
            base_size = float(order.get("base_size", 0))
            # Round to nearest 0.01
            order["base_size"] = round(base_size, 2)

        def validate_price(order):
            """Ensure price is reasonable."""
            if float(order.get("limit_price", 0)) <= 0:
                raise ValueError("Price must be positive")

        def round_price(order):
            """Round price to 2 decimals."""
            limit_price = float(order.get("limit_price", 0))
            order["limit_price"] = round(limit_price, 2)

        registry.register_pre_submission(validate_size)
        registry.register_pre_submission(round_size)
        registry.register_pre_submission(validate_price)
        registry.register_pre_submission(round_price)

        order = {
            "product_id": "BTC-USDC",
            "side": "BUY",
            "base_size": 10.1234567,
            "limit_price": 100.123456,
        }

        registry.call_pre_submission_hooks(order)

        # Should be rounded
        assert order["base_size"] == 10.12
        assert order["limit_price"] == 100.12


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
