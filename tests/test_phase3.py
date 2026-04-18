"""Phase 3 Business Logic Extraction Tests.

Tests for OrderCalculator, OrderProcessor, and EventProcessor modules.
These tests validate high-level business logic without external dependencies.

Run with: python -m pytest tests/test_phase3.py -v
"""

import pytest
from business.order_calculator import OrderCalculator
from business.order_processor import OrderProcessor
from business.event_processor import EventProcessor


class TestOrderCalculator:
    """Test OrderCalculator for order computations and metrics."""

    def test_calculate_follow_up_price_from_buy_order(self):
        """Test calculating SELL price for a filled BUY order."""
        calc = OrderCalculator()
        parent_order = {
            "order_side": "BUY",
            "avg_price": "100.00",
            "product_id": "BTC-USD",
        }
        
        result = calc.calculate_follow_up_price(
            parent_order=parent_order,
            side="SELL",
            profit_target_pct=0.01,
        )
        
        assert result["product_id"] == "BTC-USD"
        assert result["side"] == "SELL"
        assert result["price"] == 101.0  # 100 * (1 + 0.01)

    def test_calculate_follow_up_price_from_sell_order(self):
        """Test calculating BUY price for a filled SELL order."""
        calc = OrderCalculator()
        parent_order = {
            "order_side": "SELL",
            "avg_price": "100.00",
            "product_id": "BTC-USD",
        }
        
        result = calc.calculate_follow_up_price(
            parent_order=parent_order,
            side="BUY",
            profit_target_pct=0.01,
        )
        
        assert result["product_id"] == "BTC-USD"
        assert result["side"] == "BUY"
        assert abs(result["price"] - 99.01) < 0.01  # 100 / (1 + 0.01) ≈ 99.01

    def test_calculate_follow_up_price_with_zero_price(self):
        """Test follow-up price calculation with invalid parent price."""
        calc = OrderCalculator()
        parent_order = {
            "order_side": "BUY",
            "avg_price": "0",
            "product_id": "BTC-USD",
        }
        
        result = calc.calculate_follow_up_price(
            parent_order=parent_order,
            side="SELL",
            profit_target_pct=0.01,
        )
        
        assert result["price"] == 0.0

    def test_calculate_follow_up_size_from_filled_size(self):
        """Test extracting follow-up size from filled_size field."""
        calc = OrderCalculator()
        parent_order = {"filled_size": "0.5"}
        
        result = calc.calculate_follow_up_size(parent_order)
        
        assert result["size"] == 0.5
        assert result["source_field"] == "filled_size"

    def test_calculate_follow_up_size_from_cumulative_quantity(self):
        """Test extracting follow-up size from cumulative_quantity field."""
        calc = OrderCalculator()
        parent_order = {"cumulative_quantity": "1.0"}
        
        result = calc.calculate_follow_up_size(parent_order)
        
        assert result["size"] == 1.0
        assert result["source_field"] == "cumulative_quantity"

    def test_calculate_follow_up_size_no_size_fields(self):
        """Test follow-up size with no size fields present."""
        calc = OrderCalculator()
        parent_order = {"product_id": "BTC-USD"}
        
        result = calc.calculate_follow_up_size(parent_order)
        
        assert result["size"] == 0.0
        assert result["source_field"] is None

    def test_calculate_position_change_buy_order_empty_position(self):
        """Test position change from a BUY order on empty position."""
        calc = OrderCalculator()
        order = {
            "order_side": "BUY",
            "filled_size": "0.5",
            "avg_price": "100.0",
        }
        
        result = calc.calculate_position_change(order, position=None)
        
        assert result["new_size"] == 0.5
        assert result["size_change"] == 0.5
        assert result["entry_vwap"] == 100.0

    def test_calculate_position_change_buy_order_existing_position(self):
        """Test position change from a BUY order on existing long position."""
        calc = OrderCalculator()
        order = {
            "order_side": "BUY",
            "filled_size": "0.5",
            "avg_price": "102.0",
        }
        position = {"net_size": "0.5", "entry_vwap": "100.0"}
        
        result = calc.calculate_position_change(order, position)
        
        assert result["new_size"] == 1.0
        assert result["size_change"] == 0.5
        assert result["entry_vwap"] == 101.0  # (0.5*100 + 0.5*102) / 1.0

    def test_calculate_position_change_sell_order(self):
        """Test position change from a SELL order."""
        calc = OrderCalculator()
        order = {
            "order_side": "SELL",
            "filled_size": "0.3",
            "avg_price": "100.0",
        }
        position = {"net_size": "0.5", "entry_vwap": "100.0"}
        
        result = calc.calculate_position_change(order, position)
        
        assert result["new_size"] == 0.2
        assert result["size_change"] == -0.3

    def test_calculate_fees_with_commission_only(self):
        """Test fee calculation with commission rate only."""
        calc = OrderCalculator()
        order = {
            "filled_size": "1.0",
            "avg_price": "100.0",
        }
        
        result = calc.calculate_fees(order, fee_rate=0.001)
        
        assert result["commission"] == 0.1  # 1.0 * 100.0 * 0.001
        assert result["mandatory_fees"] == 0.0
        assert result["total_fees"] == 0.1

    def test_calculate_fees_with_mandatory_fees(self):
        """Test fee calculation with both commission and mandatory fees."""
        calc = OrderCalculator()
        order = {
            "filled_size": "1.0",
            "avg_price": "100.0",
        }
        
        result = calc.calculate_fees(
            order,
            fee_rate=0.001,
            derivatives_mandatory_fee_per_contract=0.15,
        )
        
        assert result["commission"] == 0.1
        assert result["mandatory_fees"] == 0.15
        assert result["total_fees"] == 0.25

    def test_should_create_follow_up_for_filled_order(self):
        """Test that filled orders should create follow-ups."""
        calc = OrderCalculator()
        order = {"status": "FILLED", "filled_size": "0.5"}
        
        assert calc.should_create_follow_up(order) is True

    def test_should_create_follow_up_for_open_order(self):
        """Test that open orders should not create follow-ups."""
        calc = OrderCalculator()
        order = {"status": "OPEN", "filled_size": "0.5"}
        
        assert calc.should_create_follow_up(order) is False

    def test_should_create_follow_up_for_zero_fill(self):
        """Test that zero fills should not create follow-ups."""
        calc = OrderCalculator()
        order = {"status": "FILLED", "filled_size": "0.0"}
        
        assert calc.should_create_follow_up(order) is False


class TestOrderProcessor:
    """Test OrderProcessor for order event handling."""

    def test_build_order_context_with_complete_order(self):
        """Test building context from complete order data."""
        processor = OrderProcessor()
        order = {
            "client_order_id": "client-123",
            "order_id": "order-456",
            "product_id": "BTC-USDC",
            "order_side": "BUY",
            "status": "FILLED",
            "limit_price": "42500.00",
            "filled_size": "0.5",
            "number_of_fills": 1,
        }
        
        context = processor.build_order_context(order)
        
        assert context["order_id"] == "order-456"
        assert context["product_id"] == "BTC-USDC"
        assert context["side"] == "BUY"
        assert context["status"] == "FILLED"
        assert context["price"] == 42500.00
        assert context["filled_size"] == 0.5
        assert context["number_of_fills"] == 1

    def test_build_order_context_with_avg_price_fallback(self):
        """Test context building falls back to avg_price when limit_price not available."""
        processor = OrderProcessor()
        order = {
            "order_id": "order-456",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "status": "FILLED",
            "avg_price": "42400.00",
            "filled_size": "0.5",
        }
        
        context = processor.build_order_context(order)
        
        assert context["price"] == 42400.00

    def test_build_order_context_with_debug_fields(self):
        """Test context building includes debug fields when requested."""
        processor = OrderProcessor()
        order = {
            "order_id": "order-456",
            "product_id": "BTC-USDC",
            "status": "FILLED",
            "side": "BUY",
            "time_in_force": "GTC",
            "order_type": "LIMIT",
            "created_at": "2024-01-15T10:00:00Z",
            "total_fees": "50.00",
        }
        
        context = processor.build_order_context(order, include_debug=True)
        
        assert "debug" in context
        assert context["debug"]["time_in_force"] == "GTC"
        assert context["debug"]["type"] == "LIMIT"

    def test_is_filled_order_true(self):
        """Test detection of filled orders."""
        processor = OrderProcessor()
        order = {"status": "FILLED", "filled_size": "0.5"}
        
        assert processor.is_filled_order(order) is True

    def test_is_filled_order_false_for_open(self):
        """Test that open orders are not filled."""
        processor = OrderProcessor()
        order = {"status": "OPEN", "filled_size": "0.5"}
        
        assert processor.is_filled_order(order) is False

    def test_is_filled_order_false_for_zero_fill(self):
        """Test that zero-filled orders are not considered filled."""
        processor = OrderProcessor()
        order = {"status": "FILLED", "filled_size": "0.0"}
        
        assert processor.is_filled_order(order) is False

    def test_is_cancelled_order_true(self):
        """Test detection of cancelled orders."""
        processor = OrderProcessor()
        order = {"status": "CANCELLED"}
        
        assert processor.is_cancelled_order(order) is True

    def test_is_open_order_true_for_open_status(self):
        """Test detection of open orders."""
        processor = OrderProcessor()
        order = {"status": "OPEN"}
        
        assert processor.is_open_order(order) is True

    def test_is_open_order_true_for_pending_status(self):
        """Test detection of pending orders."""
        processor = OrderProcessor()
        order = {"status": "PENDING"}
        
        assert processor.is_open_order(order) is True

    def test_order_matches_product_true(self):
        """Test product matching for orders."""
        processor = OrderProcessor()
        order = {"product_id": "BTC-USDC"}
        
        assert processor.order_matches_product(order, "BTC-USDC") is True

    def test_order_matches_product_false(self):
        """Test product mismatch detection."""
        processor = OrderProcessor()
        order = {"product_id": "BTC-USDC"}
        
        assert processor.order_matches_product(order, "ETH-USDC") is False

    def test_validate_order_fields_all_present(self):
        """Test validation with all required fields present."""
        processor = OrderProcessor()
        order = {
            "order_id": "123",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "status": "FILLED",
        }
        
        is_valid, missing = processor.validate_order_fields(order)
        
        assert is_valid is True
        assert missing == []

    def test_validate_order_fields_missing_fields(self):
        """Test validation detects missing required fields."""
        processor = OrderProcessor()
        order = {
            "order_id": "123",
            "product_id": "BTC-USDC",
        }
        
        is_valid, missing = processor.validate_order_fields(order)
        
        assert is_valid is False
        assert "side" in missing
        assert "status" in missing

    def test_enrich_order_with_calculated_fields(self):
        """Test enriching order with calculated data."""
        processor = OrderProcessor()
        order = {"order_id": "123", "product_id": "BTC-USDC"}
        calculator_results = {"price": 42500.0, "size": 0.1, "fees": 50.0}
        
        enriched = processor.enrich_order_with_calculated_fields(order, calculator_results)
        
        assert enriched["order_id"] == "123"
        assert enriched["price"] == 42500.0
        assert enriched["size"] == 0.1
        assert enriched["fees"] == 50.0


class TestEventProcessor:
    """Test EventProcessor for WebSocket event handling."""

    def test_hash_event_consistency(self):
        """Test that same event produces same hash."""
        processor = EventProcessor()
        event1 = {"type": "filled", "order_id": "123"}
        event2 = {"type": "filled", "order_id": "123"}
        
        assert processor.hash_event(event1) == processor.hash_event(event2)

    def test_hash_event_differs_for_different_events(self):
        """Test that different events produce different hashes."""
        processor = EventProcessor()
        event1 = {"type": "filled", "order_id": "123"}
        event2 = {"type": "filled", "order_id": "456"}
        
        assert processor.hash_event(event1) != processor.hash_event(event2)

    def test_is_duplicate_event_false_for_new_event(self):
        """Test that new events are not duplicates."""
        processor = EventProcessor()
        event = {"type": "filled", "order_id": "123"}
        
        assert processor.is_duplicate_event(event) is False

    def test_is_duplicate_event_true_after_marking_seen(self):
        """Test that marked events are detected as duplicates."""
        processor = EventProcessor()
        event = {"type": "filled", "order_id": "123"}
        
        processor.mark_event_seen(event)
        assert processor.is_duplicate_event(event) is True

    def test_rotate_dedup_buckets_advances_index(self):
        """Test that bucket rotation advances current bucket index."""
        processor = EventProcessor(max_dedup_buckets=3)
        assert processor.current_bucket == 0
        
        processor.rotate_dedup_buckets()
        assert processor.current_bucket == 1
        
        processor.rotate_dedup_buckets()
        assert processor.current_bucket == 2
        
        processor.rotate_dedup_buckets()
        assert processor.current_bucket == 0

    def test_rotate_dedup_buckets_clears_old_events(self):
        """Test that rotation clears old events from overwritten buckets."""
        processor = EventProcessor(max_dedup_buckets=2)
        event = {"type": "filled", "order_id": "123"}
        
        # Mark event in bucket 0
        processor.mark_event_seen(event)
        assert processor.is_duplicate_event(event) is True
        
        # Rotate twice (full cycle for 2 buckets)
        processor.rotate_dedup_buckets()  # current=1, bucket 1 cleared
        processor.rotate_dedup_buckets()  # current=0, bucket 0 cleared
        
        # Event should be forgotten
        assert processor.is_duplicate_event(event) is False

    def test_filter_events_by_channel(self):
        """Test filtering events by channel."""
        processor = EventProcessor()
        events = [
            {"channel": "user", "type": "filled"},
            {"channel": "ticker", "type": "snapshot"},
            {"channel": "user", "type": "cancelled"},
        ]
        
        user_events = processor.filter_events_by_channel(events, "user")
        
        assert len(user_events) == 2
        assert all(e["channel"] == "user" for e in user_events)

    def test_filter_events_by_product(self):
        """Test filtering events by product_id."""
        processor = EventProcessor()
        events = [
            {"product_id": "BTC-USDC", "type": "filled"},
            {"product_id": "ETH-USDC", "type": "filled"},
            {"product_id": "BTC-USDC", "type": "cancelled"},
        ]
        
        btc_events = processor.filter_events_by_product(events, "BTC-USDC")
        
        assert len(btc_events) == 2
        assert all(e["product_id"] == "BTC-USDC" for e in btc_events)

    def test_should_process_event_true_for_valid_event(self):
        """Test that valid events should be processed."""
        processor = EventProcessor()
        event = {"channel": "user", "product_id": "BTC-USDC"}
        
        should_process = processor.should_process_event(
            event,
            subscribed_products=["BTC-USDC", "ETH-USDC"],
            subscribed_channels=["user", "ticker"],
        )
        
        assert should_process is True

    def test_should_process_event_false_for_duplicate(self):
        """Test that duplicate events are not processed."""
        processor = EventProcessor()
        event = {"channel": "user", "product_id": "BTC-USDC"}
        
        # Mark as duplicate
        processor.mark_event_seen(event)
        
        should_process = processor.should_process_event(
            event,
            subscribed_products=["BTC-USDC"],
            subscribed_channels=["user"],
        )
        
        assert should_process is False

    def test_should_process_event_false_for_unsubscribed_channel(self):
        """Test that unsubscribed channels are not processed."""
        processor = EventProcessor()
        event = {"channel": "heartbeats", "product_id": "BTC-USDC"}
        
        should_process = processor.should_process_event(
            event,
            subscribed_products=["BTC-USDC"],
            subscribed_channels=["user", "ticker"],
        )
        
        assert should_process is False

    def test_should_process_event_false_for_unsubscribed_product(self):
        """Test that unsubscribed products are not processed."""
        processor = EventProcessor()
        event = {"channel": "user", "product_id": "XRP-USDC"}
        
        should_process = processor.should_process_event(
            event,
            subscribed_products=["BTC-USDC", "ETH-USDC"],
            subscribed_channels=["user"],
        )
        
        assert should_process is False

    def test_extract_orders_from_event(self):
        """Test extracting orders from user channel event."""
        processor = EventProcessor()
        event = {
            "events": [
                {
                    "orders": [
                        {"order_id": "1", "status": "FILLED"},
                        {"order_id": "2", "status": "OPEN"},
                    ]
                }
            ]
        }
        
        orders = processor.extract_orders_from_event(event)
        
        assert len(orders) == 2
        assert orders[0]["order_id"] == "1"
        assert orders[1]["order_id"] == "2"

    def test_extract_orders_from_event_empty(self):
        """Test extracting from event with no orders."""
        processor = EventProcessor()
        event = {"events": []}
        
        orders = processor.extract_orders_from_event(event)
        
        assert orders == []

    def test_extract_product_id_from_event_direct(self):
        """Test extracting product_id from direct field."""
        processor = EventProcessor()
        event = {"product_id": "BTC-USDC"}
        
        product_id = processor.extract_product_id_from_event(event)
        
        assert product_id == "BTC-USDC"


class TestPhase3Integration:
    """Integration tests combining multiple business logic modules."""

    def test_order_lifecycle_buy_and_sell_followup(self):
        """Test complete order lifecycle: BUY -> fill -> calculate SELL."""
        calc = OrderCalculator()
        processor = OrderProcessor()
        
        # Parent BUY order filled
        parent_order = {
            "order_id": "parent-1",
            "client_order_id": "client-1",
            "product_id": "BTC-USDC",
            "order_side": "BUY",
            "side": "BUY",
            "status": "FILLED",
            "avg_price": "42000.00",
            "filled_size": "0.5",
        }
        
        # Validate order
        is_valid, missing = processor.validate_order_fields(parent_order)
        assert is_valid is True
        
        # Build context for logging
        context = processor.build_order_context(parent_order)
        assert context["status"] == "FILLED"
        
        # Should create follow-up
        assert calc.should_create_follow_up(parent_order) is True
        
        # Calculate follow-up
        follow_up_size = calc.calculate_follow_up_size(parent_order)
        assert follow_up_size["size"] == 0.5
        
        follow_up_price = calc.calculate_follow_up_price(
            parent_order,
            side="SELL",
            profit_target_pct=0.004,
        )
        assert follow_up_price["price"] == 42168.0  # 42000 * 1.004

    def test_event_processing_with_deduplication(self):
        """Test event processing with deduplication and filtering."""
        processor = EventProcessor()
        
        event1 = {
            "channel": "user",
            "product_id": "BTC-USDC",
            "type": "filled",
            "order_id": "123",
        }
        event2 = {
            "channel": "user",
            "product_id": "BTC-USDC",
            "type": "filled",
            "order_id": "123",
        }
        
        # First event should be processed
        assert processor.should_process_event(
            event1,
            subscribed_products=["BTC-USDC"],
            subscribed_channels=["user"],
        ) is True
        
        # Mark it seen
        processor.mark_event_seen(event1)
        
        # Duplicate should not be processed
        assert processor.should_process_event(
            event2,
            subscribed_products=["BTC-USDC"],
            subscribed_channels=["user"],
        ) is False

    def test_position_update_workflow(self):
        """Test position calculation workflow."""
        calc = OrderCalculator()
        
        # Initial position (empty)
        position = None
        
        # First BUY
        order1 = {
            "order_side": "BUY",
            "filled_size": "0.5",
            "avg_price": "100.0",
        }
        result1 = calc.calculate_position_change(order1, position)
        assert result1["new_size"] == 0.5
        assert result1["entry_vwap"] == 100.0
        
        # Second BUY
        order2 = {
            "order_side": "BUY",
            "filled_size": "0.5",
            "avg_price": "110.0",
        }
        position = {
            "net_size": str(result1["new_size"]),
            "entry_vwap": str(result1["entry_vwap"]),
        }
        result2 = calc.calculate_position_change(order2, position)
        assert result2["new_size"] == 1.0
        assert result2["entry_vwap"] == 105.0  # (0.5*100 + 0.5*110) / 1.0
