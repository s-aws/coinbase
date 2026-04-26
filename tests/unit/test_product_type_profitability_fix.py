"""Regression tests for product-type-aware profitability validation (Option A).

Architecture under test:
- ProfitValidator owns product context resolution. When constructed with an
  orderbook, it auto-resolves product_type, contract_size, and position_side
  from a product_id via its private `_resolve_product_context()` helper.
- StealthOrderManager and OrderEngine no longer perform manual lookups; they
  pass only `product_id` and trust the validator to resolve the rest.

These tests verify:
1. Manager call sites only pass `product_id` (clean API contract).
2. ProfitValidator with an injected orderbook correctly resolves FUTURE
   contract_size from runtime orderbook data (NOT static products.json).
3. SPOT product paths return contract_size=None.
4. Backward compatibility: ProfitValidator works without an orderbook when
   callers supply context explicitly.
"""

from unittest.mock import Mock, patch

import pytest

from calculation.profit_validator import ProfitValidator
from core.enums import ProductType
from core.stealth_order_manager import StealthOrderManager


# ---------------------------------------------------------------------------
# StealthOrderManager: clean API contract — passes product_id only
# ---------------------------------------------------------------------------

class TestStealthManagerPassesOnlyProductId:
    """Manager must NOT supply product_type / contract_size / position_side."""

    @pytest.fixture
    def stealth_manager(self):
        manager = StealthOrderManager(
            db_client=Mock(),
            profit_validator=Mock(),
        )
        manager.profit_validator.derive_follow_up_price_from_target = Mock(
            return_value=77540.0
        )
        manager.profit_validator.validate_order_profitability = Mock(
            return_value={
                "is_profitable": True,
                "net_profit": 17.23,
                "total_fees": 12.77,
            }
        )
        return manager

    def test_anchor_reprice_passes_only_product_id(self, stealth_manager):
        order = {
            "stealth_order_id": "anchor-1",
            "product_id": "BIP-20DEC30-CDE",
            "side": "BUY",
            "total_size": 20.0,
            "remaining_size": 20.0,
            "target_movement": 0.002,
            "target_movement_type": "P",
        }
        stealth_manager.in_memory_orders["anchor-1"] = order

        stealth_manager._validate_anchor_reprice_profitability(
            order=order, candidate_entry_price=77390.0
        )

        call_kwargs = stealth_manager.profit_validator.validate_order_profitability.call_args[1]
        assert call_kwargs["product_id"] == "BIP-20DEC30-CDE"
        # Manager must NOT pre-resolve product context — that's the validator's job.
        assert "product_type" not in call_kwargs
        assert "contract_size" not in call_kwargs
        assert "position_side" not in call_kwargs

    def test_reveal_passes_only_product_id(self, stealth_manager):
        from core.models import RevealExecutionPlan

        order = {
            "stealth_order_id": "reveal-1",
            "product_id": "BIP-20DEC30-CDE",
            "side": "SELL",
            "total_size": 20.0,
            "remaining_size": 20.0,
            "target_movement": 0.002,
            "target_movement_type": "P",
            "limit_price": 77540.0,
            "reveal_pricing_policy": "top_of_book",
            "reveal_condition_json": {},
        }
        stealth_manager.in_memory_orders["reveal-1"] = order

        plan = RevealExecutionPlan(
            configured_limit_price=77540.0,
            submitted_limit_price=77540.0,
            reveal_pricing_policy="top_of_book",
            reveal_price_source="ticker_best_bid",
            fallback_used=False,
            market_source="ticker",
            market_bid=77540.0,
            market_ask=77545.0,
            target_movement=0.002,
            target_movement_type="P",
            target_movement_source="order_parent",
        )

        stealth_manager._validate_reveal_profitability(
            stealth_order_id="reveal-1", reveal_execution_plan=plan
        )

        call_kwargs = stealth_manager.profit_validator.validate_order_profitability.call_args[1]
        assert call_kwargs["product_id"] == "BIP-20DEC30-CDE"
        assert "product_type" not in call_kwargs
        assert "contract_size" not in call_kwargs
        assert "position_side" not in call_kwargs


# ---------------------------------------------------------------------------
# ProfitValidator: auto-resolves product context from injected orderbook
# ---------------------------------------------------------------------------

def _make_orderbook(product_id: str, *, product_type: str, contract_size,
                    position_side=None):
    """Build a minimal orderbook stub matching the real OrderBook interface."""
    ob = Mock()
    ob.product = {
        product_id: {
            "product_type": product_type,
            "future_product_details": {"contract_size": contract_size},
        }
    }
    ob.get_position_side = Mock(return_value=position_side)
    ob.positions = {}
    return ob


class TestProfitValidatorAutoResolvesContext:
    """Validator must resolve product_type / contract_size / position_side itself."""

    def test_future_resolves_contract_size_from_orderbook(self):
        ob = _make_orderbook(
            "BIP-20DEC30-CDE",
            product_type=ProductType.FUTURE.value,
            contract_size=0.01,
            position_side="LONG",
        )
        validator = ProfitValidator(orderbook=ob)

        ctx = validator._resolve_product_context("BIP-20DEC30-CDE")

        assert ctx["product_type"] == ProductType.FUTURE.value
        assert ctx["contract_size"] == 0.01
        assert ctx["position_side"] == "LONG"

    def test_spot_returns_no_contract_size(self):
        ob = _make_orderbook(
            "BTC-USDC",
            product_type=ProductType.SPOT.value,
            contract_size=None,
        )
        validator = ProfitValidator(orderbook=ob)

        ctx = validator._resolve_product_context("BTC-USDC")

        assert ctx["product_type"] == ProductType.SPOT.value
        assert ctx["contract_size"] is None

    def test_is_profitable_applies_contract_size_adjustment(self):
        """Regression: contract_size must be applied to gross_profit / fees."""
        ob = _make_orderbook(
            "BIP-20DEC30-CDE",
            product_type=ProductType.FUTURE.value,
            contract_size=0.01,
            position_side="LONG",
        )
        validator = ProfitValidator(orderbook=ob)

        # 20 contracts * 0.01 BTC/contract = 0.2 BTC effective size.
        # If contract_size were missing, fees would be ~100x too large.
        result = validator.is_profitable(
            filled_price=77390.0,
            follow_up_price=77540.0,
            side="BUY",
            order_size=20.0,
            product_id="BIP-20DEC30-CDE",
        )

        # Sanity check magnitudes: fees on 0.2 BTC notional, not 20 BTC notional.
        # 20 contracts * 0.01 * 77390 ≈ $15,478 notional × 1.2% ≈ $186 fees.
        # Without contract_size adjustment fees would be ~$18,600.
        assert result["total_fees"] < 500.0, (
            f"Fees suggest contract_size adjustment skipped: {result['total_fees']}"
        )

    def test_explicit_args_override_auto_resolution(self):
        ob = _make_orderbook(
            "BIP-20DEC30-CDE",
            product_type=ProductType.FUTURE.value,
            contract_size=0.01,
        )
        validator = ProfitValidator(orderbook=ob)

        # When explicit product_type=SPOT is passed, validator should NOT
        # apply contract_size adjustment. order_size=1.0 unit at $100 = $100 notional.
        result = validator.is_profitable(
            filled_price=100.0,
            follow_up_price=110.0,
            side="BUY",
            order_size=1.0,
            product_id="BIP-20DEC30-CDE",
            product_type=ProductType.SPOT.value,  # explicit override
            contract_size=None,
        )

        # Profit should be (110-100)*1 = $10 minus fees (~$1.20) ≈ $8.80
        assert result["gross_profit"] == pytest.approx(10.0, abs=0.01)


# ---------------------------------------------------------------------------
# Backward compatibility: validator works without an orderbook
# ---------------------------------------------------------------------------

class TestProfitValidatorBackwardCompat:
    def test_no_orderbook_no_product_id_defaults_to_spot(self):
        validator = ProfitValidator()
        result = validator.is_profitable(
            filled_price=100.0,
            follow_up_price=110.0,
            side="BUY",
            order_size=1.0,
        )
        # Without orderbook + product_id, product_type defaults to SPOT (no
        # contract_size adjustment), so gross_profit = (110-100)*1 = $10.
        assert result["gross_profit"] == pytest.approx(10.0, abs=0.01)

    def test_no_orderbook_explicit_future_context_still_works(self):
        validator = ProfitValidator()
        result = validator.is_profitable(
            filled_price=77390.0,
            follow_up_price=77540.0,
            side="BUY",
            order_size=20.0,
            product_type=ProductType.FUTURE.value,
            contract_size=0.01,
            position_side="LONG",
        )
        # 20 contracts * 0.01 * (77540 - 77390) = $30 gross profit (NOT $3000).
        assert result["gross_profit"] == pytest.approx(30.0, abs=0.01)
