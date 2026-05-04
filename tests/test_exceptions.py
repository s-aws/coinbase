"""
Comprehensive tests for custom exception system.

Tests exception raising behavior, context preservation, and recovery scenarios
across all custom exception classes in core/exceptions.py.
"""

import pytest
from core.exceptions import (
    CoinbaseEngineError,
    RevealConditionEvaluationError,
    OrderProcessingError,
    OrderCalculationError,
    DuplicateEventError,
    WebSocketMessageError,
    DatabaseConnectionError,
    OrderPersistenceError,
    DatabaseTransactionError,
    StealthOrderNotFoundError,
    RevealPricingError,
    RevealOrderSliceError,
)
from business.stealth_condition_evaluator import PriceThresholdEvaluator, get_evaluator
from business.event_processor import EventProcessor
from bridges.event_bridge import EventBridge


class TestRevealConditionEvaluationError:
    """Test RevealConditionEvaluationError raising and context."""

    def test_raises_on_missing_price_threshold(self):
        """Test that PriceThresholdEvaluator raises when price_threshold missing."""
        evaluator = PriceThresholdEvaluator()
        condition_config = {
            "direction": "below",
            "hold_duration_seconds": 2,
            # Missing: price_threshold
        }
        
        with pytest.raises(RevealConditionEvaluationError) as exc_info:
            evaluator.evaluate({}, condition_config, {})
        
        assert "price_threshold" in str(exc_info.value).lower()
        assert exc_info.value.condition_type == "PRICE_THRESHOLD"

    def test_raises_on_missing_cumulative_volume_fields(self):
        """Test that CumulativeVolumeEvaluator raises when required fields missing."""
        evaluator = get_evaluator("cumulative_volume")
        condition_config = {
            "product_id": "BTC-USDC",
            # Missing: price_level and volume_threshold
        }
        
        with pytest.raises(RevealConditionEvaluationError) as exc_info:
            evaluator.evaluate({}, condition_config, {})
        
        error_msg = str(exc_info.value).lower()
        assert "price_level" in error_msg or "volume_threshold" in error_msg
        assert exc_info.value.condition_type == "CUMULATIVE_VOLUME"

    def test_raises_on_empty_composite_conditions(self):
        """Test that CompositeEvaluator raises when conditions list empty."""
        evaluator = get_evaluator("composite")
        condition_config = {
            "operator": "AND",
            "conditions": [],  # Empty list
        }
        
        with pytest.raises(RevealConditionEvaluationError) as exc_info:
            evaluator.evaluate({}, condition_config, {})
        
        error_msg = str(exc_info.value).lower()
        assert "conditions" in error_msg
        assert exc_info.value.condition_type == "COMPOSITE"

    def test_exception_inherits_from_base(self):
        """Test that RevealConditionEvaluationError is subclass of CoinbaseEngineError."""
        assert issubclass(RevealConditionEvaluationError, CoinbaseEngineError)


class TestOrderProcessingError:
    """Test OrderProcessingError raising and context."""

    def test_exception_preserves_client_order_id(self):
        """Test that exception preserves client_order_id when available."""
        exc = OrderProcessingError(
            message="test",
            client_order_id="client-123"
        )
        assert exc.client_order_id == "client-123"

    def test_exception_inherits_from_base(self):
        """Test that OrderProcessingError is subclass of CoinbaseEngineError."""
        assert issubclass(OrderProcessingError, CoinbaseEngineError)


class TestOrderCalculationError:
    """Test OrderCalculationError raising and context."""

    def test_calculation_error_context(self):
        """Test that OrderCalculationError preserves context."""
        exc = OrderCalculationError(
            message="Failed to calculate price",
            client_order_id="client-order-123"
        )
        
        assert exc.client_order_id == "client-order-123"
        assert "price" in str(exc).lower()

    def test_inherits_from_order_processing_error(self):
        """Test that OrderCalculationError is subclass of OrderProcessingError."""
        assert issubclass(OrderCalculationError, OrderProcessingError)


class TestDuplicateEventError:
    """Test DuplicateEventError raising and context."""

    def test_raises_via_event_bridge_strict_check(self):
        """Test that EventBridge.check_duplicate_strict raises DuplicateEventError."""
        bridge = EventBridge()
        event = {'type': 'filled', 'id': 'event-123'}
        
        # Mark as seen
        bridge.mark_event_seen(event)
        
        # Strict check should raise
        with pytest.raises(DuplicateEventError) as exc_info:
            bridge.check_duplicate_strict(event)
        
        assert exc_info.value.event_hash is not None

    def test_exception_includes_event_hash(self):
        """Test that DuplicateEventError includes event hash."""
        exc = DuplicateEventError(
            message="Event already processed",
            event_hash="abc123def456"
        )
        
        assert exc.event_hash == "abc123def456"

    def test_exception_inherits_from_base(self):
        """Test that DuplicateEventError is subclass of CoinbaseEngineError."""
        assert issubclass(DuplicateEventError, CoinbaseEngineError)

    def test_recoverable_with_skip_logic(self):
        """Test that duplicate events can be recovered with skip logic."""
        bridge = EventBridge()
        event = {'type': 'filled', 'order_id': 'order-123'}
        bridge.mark_event_seen(event)
        
        # Simulating recovery: skip duplicate
        try:
            if bridge.is_duplicate_event(event):
                pass  # Skip processing
        except DuplicateEventError:
            pytest.fail("Should not raise in normal flow")
        
        assert bridge.is_duplicate_event(event)


class TestWebSocketMessageError:
    """Test WebSocketMessageError raising and context."""

    def test_exception_preserves_raw_data(self):
        """Test that WebSocketMessageError preserves raw_data."""
        exc = WebSocketMessageError(
            message="Invalid JSON",
            raw_data='{"invalid": json}'
        )
        
        assert exc.raw_data == '{"invalid": json}'

    def test_exception_inherits_from_base(self):
        """Test that WebSocketMessageError is subclass of CoinbaseEngineError."""
        assert issubclass(WebSocketMessageError, CoinbaseEngineError)


class TestDatabaseExceptions:
    """Test database exception hierarchy and raising."""

    def test_connection_error_context(self):
        """Test that DatabaseConnectionError works."""
        exc = DatabaseConnectionError("Connection timeout after 30s")
        assert "timeout" in str(exc).lower()

    def test_persistence_error_context(self):
        """Test that OrderPersistenceError preserves context."""
        exc = OrderPersistenceError(
            message="Query failed",
            operation="insert",
            table="order_parent",
            client_order_id="client-456"
        )
        
        assert exc.client_order_id == "client-456"
        assert exc.operation == "insert"
        assert exc.table == "order_parent"

    def test_transaction_error_context(self):
        """Test that DatabaseTransactionError preserves context."""
        exc = DatabaseTransactionError(
            message="Transaction rolled back",
            rollback_reason="Constraint violation"
        )
        
        assert exc.rollback_reason == "Constraint violation"

    def test_all_inherit_from_base(self):
        """Test that all database exceptions inherit from CoinbaseEngineError."""
        assert issubclass(DatabaseConnectionError, CoinbaseEngineError)
        assert issubclass(OrderPersistenceError, CoinbaseEngineError)
        assert issubclass(DatabaseTransactionError, CoinbaseEngineError)


class TestStealthOrderExceptions:
    """Test stealth order-specific exceptions."""

    def test_stealth_order_not_found_error(self):
        """Test that StealthOrderNotFoundError preserves lookup context."""
        exc = StealthOrderNotFoundError(
            lookup_type="stealth_order_id",
            lookup_value="stealth-123"
        )
        
        assert exc.lookup_type == "stealth_order_id"
        assert exc.lookup_value == "stealth-123"
        assert "not found" in str(exc).lower()

    def test_reveal_pricing_error(self):
        """Test that RevealPricingError preserves pricing context."""
        exc = RevealPricingError(
            message="Would not meet profit target",
            configured_price=42500.0,
            fallback_used=True,
            stealth_order_id="stealth-456"
        )
        
        assert exc.stealth_order_id == "stealth-456"
        assert exc.configured_price == 42500.0
        assert exc.fallback_used is True

    def test_reveal_order_slice_error(self):
        """Test that RevealOrderSliceError is creatable."""
        exc = RevealOrderSliceError("Failed to calculate slice")
        assert "slice" in str(exc).lower()

    def test_all_inherit_from_base(self):
        """Test that all stealth exceptions inherit from CoinbaseEngineError."""
        assert issubclass(StealthOrderNotFoundError, CoinbaseEngineError)
        assert issubclass(RevealPricingError, CoinbaseEngineError)
        assert issubclass(RevealOrderSliceError, CoinbaseEngineError)


class TestExceptionHandlingPatterns:
    """Test common exception handling patterns."""

    def test_catch_specific_exception_type(self):
        """Test catching specific exception type."""
        evaluator = PriceThresholdEvaluator()
        
        try:
            evaluator.evaluate({}, {"direction": "below"}, {})
            pytest.fail("Should have raised RevealConditionEvaluationError")
        except RevealConditionEvaluationError as e:
            assert "price_threshold" in str(e).lower()
        except Exception:
            pytest.fail("Wrong exception type caught")

    def test_catch_base_exception_type(self):
        """Test catching via base CoinbaseEngineError type."""
        evaluator = PriceThresholdEvaluator()
        
        caught_count = 0
        try:
            evaluator.evaluate({}, {"direction": "below"}, {})
        except CoinbaseEngineError as e:
            caught_count += 1
        
        assert caught_count == 1

    def test_exception_message_is_descriptive(self):
        """Test that exception messages are helpful."""
        evaluator = get_evaluator("composite")
        
        with pytest.raises(RevealConditionEvaluationError) as exc_info:
            evaluator.evaluate({}, {"operator": "AND"}, {})
        
        error_msg = str(exc_info.value).lower()
        assert "conditions" in error_msg

    def test_exception_context_enables_recovery(self):
        """Test that exception context enables smart recovery."""
        try:
            raise StealthOrderNotFoundError(
                lookup_type="stealth_order_id",
                lookup_value="unknown-order-123"
            )
        except StealthOrderNotFoundError as e:
            # Can recover by checking lookup type
            if e.lookup_type == "stealth_order_id":
                recovery_action = "skip_or_create_default"
                assert recovery_action == "skip_or_create_default"


class TestExceptionIntegration:
    """Integration tests for exception handling across modules."""

    def test_condition_evaluation_exception_propagates(self):
        """Test that condition evaluation exceptions propagate correctly."""
        evaluator = PriceThresholdEvaluator()
        
        with pytest.raises(RevealConditionEvaluationError):
            # Missing price_threshold will raise
            evaluator.evaluate({}, {}, {})

    def test_order_processing_exception_includes_context(self):
        """Test that order processing exceptions include context."""
        order = {"client_order_id": "client-abc-123"}
        
        with pytest.raises(OrderCalculationError) as exc_info:
            raise OrderCalculationError(
                message="Cannot calculate price",
                client_order_id=order.get("client_order_id")
            )
        
        exc = exc_info.value
        assert exc.client_order_id == "client-abc-123"

    def test_event_bridge_strict_mode_usage(self):
        """Test event bridge strict mode for critical events."""
        bridge = EventBridge()
        critical_event = {'type': 'order_filled', 'id': 'fill-001'}
        
        # First time: not seen
        assert not bridge.is_duplicate_event(critical_event)
        bridge.mark_event_seen(critical_event)
        
        # Second time: catch with strict mode
        with pytest.raises(DuplicateEventError):
            bridge.check_duplicate_strict(critical_event)

    def test_error_handling_pattern_with_fallback(self):
        """Test error handling with fallback pricing."""
        try:
            raise RevealPricingError(
                message="Configured price not achievable",
                configured_price=42500.0,
                fallback_used=True,
                stealth_order_id="stealth-123"
            )
        except RevealPricingError as e:
            # Check if fallback was used
            if e.fallback_used:
                price = e.configured_price
                assert price == 42500.0


class TestExceptionDocumentation:
    """Test that exceptions are self-documenting."""

    def test_exception_types_are_descriptive(self):
        """Test that exception class names clearly describe what they represent."""
        exception_classes = [
            RevealConditionEvaluationError,
            OrderProcessingError,
            OrderCalculationError,
            DuplicateEventError,
            WebSocketMessageError,
            DatabaseConnectionError,
            OrderPersistenceError,
            DatabaseTransactionError,
            StealthOrderNotFoundError,
            RevealPricingError,
            RevealOrderSliceError,
        ]
        
        for exc_class in exception_classes:
            name = exc_class.__name__
            # Should contain Error
            assert "Error" in name

    def test_exception_classes_are_subclasses(self):
        """Test that custom exceptions inherit from CoinbaseEngineError."""
        exception_classes = [
            RevealConditionEvaluationError,
            OrderProcessingError,
            OrderCalculationError,
            DuplicateEventError,
            WebSocketMessageError,
            DatabaseConnectionError,
            OrderPersistenceError,
            DatabaseTransactionError,
            StealthOrderNotFoundError,
            RevealPricingError,
            RevealOrderSliceError,
        ]
        
        for exc_class in exception_classes:
            assert issubclass(exc_class, CoinbaseEngineError)

    def test_base_exception_is_catchable(self):
        """Test that CoinbaseEngineError can catch all domain exceptions."""
        exceptions_to_raise = [
            RevealConditionEvaluationError("test", condition_type="PRICE_THRESHOLD"),
            OrderProcessingError("test"),
            OrderCalculationError("test"),
            DuplicateEventError("test"),
            WebSocketMessageError("test"),
            DatabaseConnectionError("test"),
            OrderPersistenceError("test", "insert", "table"),
            DatabaseTransactionError("test"),
            StealthOrderNotFoundError("stealth_order_id", "test-123"),
            RevealPricingError("test"),
            RevealOrderSliceError("test"),
        ]
        
        for exc in exceptions_to_raise:
            with pytest.raises(CoinbaseEngineError):
                raise exc


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
