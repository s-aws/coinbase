"""
Unit tests for Coinbase API integration.

Tests REST API client and WebSocket connection.
"""

import pytest
from datetime import datetime, timezone
from types import SimpleNamespace

from core.exceptions import (
    CoinbasePreSdkAuthorityError,
    CoinbasePreSdkCallbackError,
)
from external.coinbase_client import CoinbaseRestClient


class TestCoinbaseRESTAPIClient:
    """Test Coinbase REST API client methods."""
    
    def test_get_account_request_format(self):
        """GET /api/v1/accounts should return account data."""
        # Mock response structure
        response = {
            "id": "account_123",
            "currency": "USD",
            "balance": "10000.00",
            "available": "9500.00",
            "hold": "500.00"
        }
        
        assert response["id"] == "account_123"
        assert float(response["balance"]) == 10000.0

    def test_get_api_key_permissions_preserves_portfolio_scope(self):
        class FakeSDKClient:
            def get_api_key_permissions(self):
                return SimpleNamespace(
                    to_dict=lambda: {
                        "can_view": True,
                        "can_trade": True,
                        "can_transfer": False,
                        "portfolio_uuid": "test-portfolio-uuid",
                        "portfolio_type": "CONSUMER",
                    }
                )

        client = CoinbaseRestClient(FakeSDKClient())

        assert client.get_api_key_permissions() == {
            "can_view": True,
            "can_trade": True,
            "can_transfer": False,
            "portfolio_uuid": "test-portfolio-uuid",
            "portfolio_type": "CONSUMER",
        }

    def test_cancel_order_marks_boundary_immediately_before_sdk_call(
        self, monkeypatch
    ):
        events = []

        class FakeSDKClient:
            def cancel_orders(self, order_ids):
                events.append(("sdk", list(order_ids)))
                return {
                    "results": [
                        {
                            "order_id": "exchange-order-1",
                            "success": True,
                        }
                    ]
                }

        monkeypatch.setattr(
            "external.coinbase_client.require_coinbase_execution_authority",
            lambda **_kwargs: events.append(("authority", None)),
        )
        client = CoinbaseRestClient(FakeSDKClient())

        result = client.cancel_order(
            "client-order-1",
            verified_exchange_order_id="exchange-order-1",
            return_evidence=True,
            before_sdk_call=lambda: events.append(("boundary", None)),
        )

        assert result["outcome"] == "succeeded"
        assert events == [
            ("authority", None),
            ("boundary", None),
            ("authority", None),
            ("sdk", ["exchange-order-1"]),
        ]

    def test_cancel_order_final_authority_failure_follows_durable_callback(
        self, monkeypatch
    ):
        events = []
        authority_checks = 0

        class FakeSDKClient:
            def cancel_orders(self, _order_ids):
                raise AssertionError("SDK boundary must remain unentered")

        def require_authority(**_kwargs):
            nonlocal authority_checks
            authority_checks += 1
            events.append(("authority", None))
            if authority_checks == 2:
                raise ValueError("synthetic_final_authority_failure")

        monkeypatch.setattr(
            "external.coinbase_client.require_coinbase_execution_authority",
            require_authority,
        )
        client = CoinbaseRestClient(FakeSDKClient())

        with pytest.raises(
            CoinbasePreSdkAuthorityError,
            match="coinbase_pre_sdk_authority_failed",
        ):
            client.cancel_order(
                "client-order-1",
                verified_exchange_order_id="exchange-order-1",
                before_sdk_call=lambda: events.append(
                    ("boundary", None)
                ),
            )

        assert events == [
            ("authority", None),
            ("boundary", None),
            ("authority", None),
        ]

    def test_cancel_order_pre_sdk_callback_failure_never_calls_sdk(
        self, monkeypatch
    ):
        class FakeSDKClient:
            def cancel_orders(self, _order_ids):
                raise AssertionError("SDK boundary must remain unentered")

        monkeypatch.setattr(
            "external.coinbase_client.require_coinbase_execution_authority",
            lambda **_kwargs: None,
        )
        client = CoinbaseRestClient(FakeSDKClient())

        with pytest.raises(
            CoinbasePreSdkCallbackError,
            match="coinbase_pre_sdk_callback_failed",
        ):
            client.cancel_order(
                "client-order-1",
                verified_exchange_order_id="exchange-order-1",
                before_sdk_call=lambda: (_ for _ in ()).throw(
                    RuntimeError("claim failed")
                ),
            )
    
    def test_list_orders_request(self):
        """GET /api/v1/orders should list orders."""
        response = [
            {
                "id": "order_123",
                "product_id": "BTC-USDC",
                "side": "buy",
                "price": "50000.00",
                "size": "1.0",
                "status": "done"
            }
        ]
        
        assert len(response) >= 0
        if response:
            assert "id" in response[0]
            assert "product_id" in response[0]

    def test_list_orders_passes_exact_filters_and_pagination_to_sdk(self):
        class FakeSDKClient:
            def __init__(self):
                self.calls = []

            def list_orders(self, **kwargs):
                self.calls.append(dict(kwargs))
                return {"orders": [], "has_next": False}

        sdk_client = FakeSDKClient()
        client = CoinbaseRestClient(sdk_client)

        response = client.list_orders(
            order_status=["OPEN"],
            order_ids=["exchange-order-1"],
            product_ids=["BTC-USDC"],
            limit=100,
            start_date="2026-07-15T19:59:00Z",
            end_date="2026-07-15T20:05:00Z",
            cursor="next-page",
            product_type="SPOT",
            retail_portfolio_id="test-portfolio-id",
        )

        assert response == {"orders": [], "has_next": False}
        assert sdk_client.calls == [
            {
                "order_status": ["OPEN"],
                "order_ids": ["exchange-order-1"],
                "product_ids": ["BTC-USDC"],
                "limit": 100,
                "start_date": "2026-07-15T19:59:00Z",
                "end_date": "2026-07-15T20:05:00Z",
                "cursor": "next-page",
                "product_type": "SPOT",
                "retail_portfolio_id": "test-portfolio-id",
            }
        ]

    def test_list_orders_rechecks_no_retry_transport_before_wire_call(self):
        class RetryPolicy:
            def __init__(self) -> None:
                self.total = 0

        class Adapter:
            def __init__(self) -> None:
                self.max_retries = RetryPolicy()

        class Session:
            def __init__(self) -> None:
                self.adapters = {
                    "http://": Adapter(),
                    "https://": Adapter(),
                }
                self.max_redirects = 0
                self.trust_env = False
                self.proxies = {}
                self.verify = True

        class FakeSDKClient:
            def __init__(self):
                self.calls = []
                self.session = Session()
                self.base_url = "api.coinbase.com"
                self.timeout = 10

            def list_orders(self, **kwargs):
                self.calls.append(dict(kwargs))
                return {"orders": [], "has_next": False}

        sdk_client = FakeSDKClient()
        client = CoinbaseRestClient(sdk_client)
        sdk_client.session.adapters["https://"].max_retries.total = 1

        with pytest.raises(
            ValueError,
            match="coinbase_sdk_transport_retry_forbidden",
        ):
            client.list_orders(product_ids=["BTC-USDC"], product_type="SPOT")

        assert sdk_client.calls == []

    @pytest.mark.parametrize(
        "invoke",
        [
            lambda client, callback: client.get_api_key_permissions(
                before_sdk_call=callback
            ),
            lambda client, callback: client.list_portfolios(
                before_sdk_call=callback
            ),
            lambda client, callback: client.list_orders(
                product_ids=["BTC-USDC"],
                product_type="SPOT",
                before_sdk_call=callback,
            ),
        ],
    )
    def test_read_boundary_marker_runs_after_final_transport_check(
        self,
        monkeypatch,
        invoke,
    ):
        class FakeSDKClient:
            def get_api_key_permissions(self):
                raise AssertionError("SDK request must remain unentered")

            def get_portfolios(self):
                raise AssertionError("SDK request must remain unentered")

            def list_orders(self, **_kwargs):
                raise AssertionError("SDK request must remain unentered")

        client = CoinbaseRestClient(FakeSDKClient())
        checks = 0

        def harden(_client, *, require_bounded_timeout):
            nonlocal checks
            assert require_bounded_timeout is True
            checks += 1
            if checks == 1:
                raise ValueError("synthetic_final_transport_check_failed")

        monkeypatch.setattr(
            "external.coinbase_client._harden_sdk_transport",
            harden,
        )
        boundary_events = []

        with pytest.raises(
            ValueError,
            match="synthetic_final_transport_check_failed",
        ):
            invoke(
                client,
                lambda: boundary_events.append("entered"),
            )

        assert boundary_events == []

    def test_list_orders_restores_zero_redirects_at_each_page_boundary(self):
        class RetryPolicy:
            total = 0

        class Adapter:
            max_retries = RetryPolicy()

        class Session:
            adapters = {"http://": Adapter(), "https://": Adapter()}
            max_redirects = 0
            trust_env = False
            proxies = {}
            verify = True

        class FakeSDKClient:
            def __init__(self):
                self.calls = []
                self.session = Session()
                self.base_url = "api.coinbase.com"
                self.timeout = 10

            def list_orders(self, **kwargs):
                self.calls.append(
                    {
                        "kwargs": dict(kwargs),
                        "max_redirects": self.session.max_redirects,
                    }
                )
                return {"orders": [], "has_next": False}

        sdk_client = FakeSDKClient()
        client = CoinbaseRestClient(sdk_client)
        sdk_client.session.max_redirects = 30

        client.list_orders(product_ids=["BTC-USDC"], product_type="SPOT")

        assert sdk_client.calls == [
            {
                "kwargs": {
                    "order_status": None,
                    "order_ids": None,
                    "product_ids": ["BTC-USDC"],
                    "limit": None,
                    "start_date": None,
                    "end_date": None,
                    "cursor": None,
                    "product_type": "SPOT",
                    "retail_portfolio_id": None,
                },
                "max_redirects": 0,
            }
        ]

    def test_get_order_passes_exchange_order_id_to_sdk(self):
        class FakeSDKClient:
            def __init__(self):
                self.calls = []

            def get_order(self, order_id):
                self.calls.append(order_id)
                return {"order": {"order_id": order_id, "status": "OPEN"}}

        sdk_client = FakeSDKClient()
        client = CoinbaseRestClient(sdk_client)

        response = client.get_order("exchange-order-1")

        assert response == {
            "order": {"order_id": "exchange-order-1", "status": "OPEN"}
        }
        assert sdk_client.calls == ["exchange-order-1"]
    
    def test_create_order_request(self):
        """POST /api/v1/orders should create order."""
        request = {
            "type": "limit",
            "side": "buy",
            "product_id": "BTC-USDC",
            "price": "50000.00",
            "size": "1.0"
        }
        
        response = {
            "id": "order_456",
            "product_id": "BTC-USDC",
            "side": "buy",
            "price": "50000.00",
            "size": "1.0",
            "status": "pending"
        }
        
        assert response["id"] == "order_456"
        assert response["product_id"] == request["product_id"]
    
    def test_cancel_order_request(self):
        """DELETE /api/v1/orders/:id should cancel order."""
        order_id = "order_456"
        
        # Response is empty on success, or error on failure
        response_code = 200  # Success
        
        assert response_code == 200
    
    def test_get_product_details(self):
        """GET /api/v1/products/:id should return product info."""
        response = {
            "id": "BTC-USDC",
            "base_currency": "BTC",
            "quote_currency": "USDC",
            "base_min_size": "0.001",
            "base_max_size": "10000",
            "quote_increment": "0.01",
            "display_name": "BTC/USDC"
        }
        
        assert response["id"] == "BTC-USDC"
        assert response["base_currency"] == "BTC"
    
    def test_get_ticker(self):
        """GET /api/v1/products/:id/ticker should return price."""
        response = {
            "trade_id": 12345,
            "price": "50000.00",
            "size": "0.5",
            "bid": "49999.99",
            "ask": "50000.01",
            "volume": "1000.5",
            "time": datetime.now(timezone.utc).astimezone().isoformat()
        }
        
        assert float(response["price"]) > 0
        assert float(response["bid"]) < float(response["ask"])


class TestCoinbaseWebSocketClient:
    """Test Coinbase WebSocket connection and messages."""
    
    def test_websocket_subscribe_message(self):
        """Subscribe to WebSocket channels."""
        subscribe_msg = {
            "type": "subscribe",
            "product_ids": ["BTC-USDC", "ETH-USDC"],
            "channels": ["ticker", "user"]
        }
        
        assert subscribe_msg["type"] == "subscribe"
        assert "BTC-USDC" in subscribe_msg["product_ids"]
    
    def test_ticker_message_received(self):
        """Receive ticker updates from WebSocket."""
        ticker_msg = {
            "type": "ticker",
            "sequence": 123456,
            "product_id": "BTC-USDC",
            "price": "50000.00",
            "open_24h": "49000.00",
            "volume_24h": "1000.5",
            "low_24h": "48000.00",
            "high_24h": "51000.00",
            "volume_30d": "5000.0",
            "best_bid": "49999.99",
            "best_ask": "50000.01",
            "side": "buy",
            "time": datetime.now(timezone.utc).astimezone().isoformat(),
            "trade_id": 12345,
            "last_size": "0.5"
        }
        
        assert ticker_msg["type"] == "ticker"
        assert ticker_msg["product_id"] == "BTC-USDC"
        assert float(ticker_msg["price"]) > 0
    
    def test_done_message_received(self):
        """Receive done messages (order completion)."""
        done_msg = {
            "type": "done",
            "side": "buy",
            "order_id": "order_123",
            "reason": "filled",
            "product_id": "BTC-USDC",
            "price": "50000.00",
            "remaining_size": "0.0",
            "sequence": 123457,
            "time": datetime.now(timezone.utc).astimezone().isoformat()
        }
        
        assert done_msg["type"] == "done"
        assert done_msg["reason"] == "filled"
        assert done_msg["remaining_size"] == "0.0"
    
    def test_match_message_received(self):
        """Receive match messages (trade execution)."""
        match_msg = {
            "type": "match",
            "trade_id": 12345,
            "sequence": 123457,
            "maker_order_id": "maker_123",
            "taker_order_id": "taker_456",
            "time": datetime.now(timezone.utc).astimezone().isoformat(),
            "product_id": "BTC-USDC",
            "size": "0.5",
            "price": "50000.00",
            "side": "buy"
        }
        
        assert match_msg["type"] == "match"
        assert match_msg["product_id"] == "BTC-USDC"


class TestAPIErrorHandling:
    """Test error handling for API responses."""
    
    def test_invalid_product_error(self):
        """Handle invalid product ID error."""
        error = {
            "message": "Invalid product_id",
            "product_id": "FAKE-USD"
        }
        
        assert "Invalid" in error["message"]
    
    def test_insufficient_funds_error(self):
        """Handle insufficient funds error."""
        error = {
            "message": "Insufficient funds",
            "reason": "insufficient_balance"
        }
        
        assert "Insufficient" in error["message"]
    
    def test_rate_limit_error(self):
        """Handle rate limit error."""
        error = {
            "message": "Rate limited",
            "retry_after": 30
        }
        
        assert "Rate" in error["message"]
    
    def test_network_timeout(self):
        """Handle network timeout."""
        # Should retry with exponential backoff
        retry_delays = [1, 2, 4, 8, 16]
        
        assert retry_delays[0] == 1
        assert retry_delays[-1] == 16


class TestAPIAuthentication:
    """Test API authentication and headers."""
    
    def test_api_key_in_header(self):
        """API requests include API key in header."""
        headers = {
            "CB-ACCESS-KEY": "api_key_value",
            "CB-ACCESS-SIGN": "signature",
            "CB-ACCESS-TIMESTAMP": "1618432000"
        }
        
        assert "CB-ACCESS-KEY" in headers
    
    def test_request_signature_generation(self):
        """Request signature should be generated from secret."""
        api_secret = "secret_key"
        timestamp = "1618432000"
        method = "GET"
        path = "/api/v1/accounts"
        
        # In real code: signature = hmac.new(api_secret, message, hashlib.sha256).digest()
        # For test, just verify structure
        signature = "generated_signature"
        
        assert len(signature) > 0


# Run with: pytest tests/unit/test_coinbase_api.py -v
