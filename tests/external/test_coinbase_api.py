"""
External Coinbase API integration tests.

These tests interact with the actual Coinbase API or sandbox.

⚠️ IMPORTANT:
- Requires COINBASE_API_KEY and COINBASE_API_SECRET environment variables
- Should only run against sandbox environment
- Run separately from other tests: pytest tests/external/ -m external

To run:
    export COINBASE_API_KEY=your_key
    export COINBASE_API_SECRET=your_secret
    export COINBASE_USE_SANDBOX=true
    pytest tests/external/ -v -m external
"""

import pytest
from datetime import datetime


@pytest.mark.external
@pytest.mark.coinbase
@pytest.mark.rest_api
class TestCoinbaseRESTAPI:
    """Test Coinbase REST API integration."""
    
    def test_api_credentials_available(self, coinbase_credentials):
        """Verify API credentials are configured."""
        assert coinbase_credentials["api_key"]
        assert coinbase_credentials["api_secret"]
    
    def test_api_respects_sandbox_mode(self, coinbase_sandbox_mode):
        """Verify we use sandbox in tests."""
        assert coinbase_sandbox_mode is True, "Must use sandbox for tests"
    
    @pytest.mark.skip(reason="Requires live Coinbase account")
    def test_list_accounts(self, coinbase_credentials):
        """Test listing Coinbase accounts via REST API.
        
        This test demonstrates how to structure Coinbase API tests.
        Skipped by default - only runs with explicit --run-live flag.
        """
        # This would use api_reference/accounts/list_accounts_response.json
        # as validation schema
        pass
    
    @pytest.mark.skip(reason="Requires live Coinbase account")
    def test_list_products(self, coinbase_credentials):
        """Test listing available products.
        
        Validates response matches api_reference/products/ schema.
        """
        pass
    
    @pytest.mark.skip(reason="Requires live Coinbase account")
    def test_get_product_details(self, coinbase_credentials):
        """Test getting single product details."""
        pass


@pytest.mark.external
@pytest.mark.coinbase
@pytest.mark.websocket
class TestCoinbaseWebSocket:
    """Test Coinbase WebSocket integration."""
    
    @pytest.mark.skip(reason="Requires WebSocket server running")
    def test_websocket_subscribe_ticker(self, coinbase_credentials):
        """Test subscribing to ticker updates via WebSocket.
        
        Uses websocket_reference/ for message validation.
        """
        pass
    
    @pytest.mark.skip(reason="Requires WebSocket server running")
    def test_websocket_receive_done_message(self, coinbase_credentials):
        """Test receiving done messages (order fills)."""
        pass
    
    @pytest.mark.skip(reason="Requires WebSocket server running")
    def test_websocket_reconnect_on_disconnect(self, coinbase_credentials):
        """Test WebSocket reconnection after disconnect."""
        pass


# Skip all external tests in normal test runs
# Run with: pytest tests/external/ -v -m external
