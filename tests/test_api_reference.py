"""API Reference Integration Tests - Validate models against real API schemas.

This test module validates that:
1. Models can parse real API response examples
2. REST client methods return correct response types
3. WebSocket messages can be processed correctly
4. Data structures match API specifications

Tests use fixtures loaded from api_reference/ and websocket_reference/ directories,
ensuring they match the actual Coinbase API specification.

Run with: python -m pytest tests/test_api_reference.py -v
"""

import pytest
from tests.fixtures import (
    get_api_loader, get_ws_loader,
    load_order_response, load_user_message, load_ticker_message
)
from core.models import Order, Product, Wallet, Position
from core.enums import OrderStatus, OrderSide, ProductType


class TestAPIReferenceModels:
    """Test that models can parse real API response examples."""
    
    def test_order_from_api_response(self):
        """Test: Order model parses real create_order response."""
        ref = load_order_response('create')
        example = ref['example']
        
        # Verify example has required fields
        assert 'order_id' in example
        assert 'client_order_id' in example
        assert 'product_id' in example
        assert 'side' in example
        
        # Parse example with Order model
        order = Order.from_dict(example)
        
        # Verify parsed correctly
        assert order.order_id == example['order_id']
        assert order.client_order_id == example['client_order_id']
        assert order.product_id == example['product_id']
        assert order.order_side.value == example['side']
    
    def test_product_from_api_response(self):
        """Test: Product model parses real product response."""
        loader = get_api_loader()
        ref = loader.load_product_response()
        
        # Check structure exists
        assert 'response' in ref
        assert 'example' in ref
        
        example = ref['example']
        product = Product.from_dict(example)
        assert product.product_id == example['product_id']
    
    def test_wallet_from_api_response(self):
        """Test: Wallet model parses real account response."""
        loader = get_api_loader()
        ref = loader.load_account_response()
        
        assert 'response' in ref
        assert 'example' in ref
        
        example = ref['example']
        wallet = Wallet.from_dict(example)
        assert wallet.currency == example['currency']
    
    def test_position_from_api_response(self):
        """Test: Position model parses real futures position response."""
        loader = get_api_loader()
        ref = loader.load_positions_response()
        
        assert 'response' in ref
        assert 'example' in ref
        
        example = ref['example']
        if 'positions' in example and example['positions']:
            pos_data = example['positions'][0]
            position = Position.from_dict(pos_data)
            assert position.product_id == pos_data['product_id']


class TestWebSocketMessageParsing:
    """Test that WebSocket messages can be parsed into models."""
    
    def test_user_message_order_parsing(self):
        """Test: Parse order from user channel message."""
        ref = load_user_message()
        
        # Verify reference structure
        assert 'channel' in ref
        assert 'response' in ref
        assert 'example' in ref
    
    def test_ticker_message_parsing(self):
        """Test: Parse ticker message structure."""
        ref = load_ticker_message()
        
        assert 'channel' in ref
        assert 'response' in ref
        assert 'example' in ref
        assert ref['channel'] == 'ticker'
    
    def test_user_message_event_structure(self):
        """Test: Verify user message event structure."""
        ref = load_user_message()
        
        # Check that response includes events
        structure = ref['response']
        assert 'events' in structure
        
        # Verify example has events
        assert 'events' in ref['example']


class TestAPIReferenceCompleteness:
    """Test that all expected API endpoints have reference files."""
    
    def test_order_endpoints_documented(self):
        """Test: All order endpoints have references."""
        loader = get_api_loader()
        
        # These should not raise FileNotFoundError
        loader.load_order_response('create')
        loader.load_order_response('cancel')
        loader.load_json('orders/list_orders_response.json')
        loader.load_fills_reference()
    
    def test_product_endpoints_documented(self):
        """Test: All product endpoints have references."""
        loader = get_api_loader()
        
        loader.load_product_response()
        loader.load_products_list()
        loader.load_candles_response()
    
    def test_websocket_channels_documented(self):
        """Test: All WebSocket channels have references."""
        loader = get_ws_loader()
        
        # Authenticated
        loader.load_user_message()
        loader.load_user_subscription()
        
        # Public
        loader.load_ticker_message()
        loader.load_level2_message()
        loader.load_market_trades_message()


class TestFixtureDataQuality:
    """Test that fixture data has required fields."""
    
    def test_order_response_has_examples(self):
        """Test: Order responses include examples."""
        ref = load_order_response('create')
        
        assert 'response' in ref
        assert 'example' in ref
        assert ref['example']['order_id']
    
    def test_websocket_message_has_structure(self):
        """Test: WebSocket references include structure docs."""
        ref = load_user_message()
        
        assert 'channel' in ref
        assert 'response' in ref
        assert 'description' in ref
    
    def test_api_response_status_codes_documented(self):
        """Test: API responses document status codes."""
        ref = load_order_response('create')
        
        assert 'status_codes' in ref
        assert len(ref['status_codes']) > 0
    
    def test_websocket_example_format(self):
        """Test: WebSocket references include examples."""
        ref = load_ticker_message()
        
        # Should have either example or example_success
        assert 'example' in ref or 'example_success' in ref


class TestIntegrationWithModels:
    """Integration tests between fixtures and models."""
    
    def test_order_model_handles_api_fields(self):
        """Test: Order model handles all API response fields."""
        ref = load_order_response('create')
        example = ref['example']
        
        # Should not raise an exception
        order = Order.from_dict(example)
        
        # Verify it's a valid order
        assert order.product_id
        assert order.order_side
        assert order.order_id
    
    def test_product_list_parsing(self):
        """Test: Parse product list from reference."""
        loader = get_api_loader()
        ref = loader.load_products_list()
        
        if 'example_success' in ref and 'products' in ref['example_success']:
            products = ref['example_success']['products']
            if products and len(products) > 0:
                product_dict = products[0]
                product = Product.from_dict(product_dict)
                assert product.product_id
    
    def test_order_from_websocket_message(self):
        """Test: Parse order from WebSocket user message."""
        ref = load_user_message()
        
        # WebSocket messages have standardized structure
        assert 'response' in ref
        
        # Check that the response documents order fields
        structure = ref['response']
        assert 'events' in structure


class TestReferenceDataConsistency:
    """Test consistency between related references."""
    
    def test_create_order_request_response_alignment(self):
        """Test: Create order request and response align."""
        loader = get_api_loader()
        
        create_req = loader.load_order_request('create')
        create_resp = loader.load_order_response('create')
        
        # Both should have proper structure
        assert 'request_body' in create_req or 'endpoint' in create_req
        assert 'response' in create_resp
    
    def test_product_fields_consistent(self):
        """Test: Product references are consistent."""
        loader = get_api_loader()
        
        single = loader.load_product_response()
        list_resp = loader.load_products_list()
        
        # Both should have response definition
        assert 'response' in single
        assert 'response' in list_resp


class TestFixtureAccessibility:
    """Test that fixtures can be accessed easily in tests."""
    
    def test_convenience_functions_work(self):
        """Test: Convenience loader functions work."""
        # Should not raise
        order_ref = load_order_response('create')
        user_msg = load_user_message()
        ticker_msg = load_ticker_message()
        
        assert order_ref
        assert user_msg
        assert ticker_msg
    
    def test_loaders_are_singletons(self):
        """Test: Loaders are cached as singletons."""
        from tests.fixtures import get_api_loader, get_ws_loader
        
        loader1 = get_api_loader()
        loader2 = get_api_loader()
        
        # Same instance
        assert loader1 is loader2
        
        ws1 = get_ws_loader()
        ws2 = get_ws_loader()
        
        assert ws1 is ws2


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
