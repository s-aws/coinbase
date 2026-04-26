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
import json
import threading
from pathlib import Path
from unittest.mock import Mock

from coinbase.websocket import WSClient

from external import CoinbaseWebSocketClient


def _load_contract_example(api_reference_root: Path, *parts):
    """Load an api_reference JSON file and return its example payload."""
    payload = json.loads((api_reference_root / Path(*parts)).read_text(encoding="utf-8"))
    return payload.get("example", {})


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

    def test_get_accounts_matches_contract_shape(self, coinbase_rest_client, api_reference_root):
        """Live contract check for GET accounts endpoint."""
        accounts_response = coinbase_rest_client.get_accounts()
        assert isinstance(accounts_response, dict)
        assert "accounts" in accounts_response
        assert isinstance(accounts_response["accounts"], list)

        if accounts_response["accounts"]:
            account = accounts_response["accounts"][0]
            contract_example = _load_contract_example(
                api_reference_root,
                "accounts",
                "list_accounts_response.json",
            )
            contract_account_keys = set(contract_example.get("accounts", [{}])[0].keys())
            assert contract_account_keys.issubset(set(account.keys()))
            assert "currency" in account
            assert "uuid" in account

    def test_get_product_dict_matches_contract_shape(self, coinbase_rest_client, api_reference_root):
        """Live contract check for GET single product endpoint."""
        product = coinbase_rest_client.get_product_dict("BTC-USD")
        assert product is not None
        assert isinstance(product, dict)
        assert product.get("product_id") == "BTC-USD"

        contract_example = _load_contract_example(
            api_reference_root,
            "products",
            "get_product_response.json",
        )
        # Coinbase responses evolve field names over time (e.g., best_bid_price vs best_bid).
        # Assert a stable minimum contract instead of exact schema parity.
        required_keys = {
            "product_id",
            "price",
            "base_increment",
            "quote_increment",
            "status",
            "product_type",
        }
        assert required_keys.issubset(set(product.keys()))
        assert contract_example.get("product_id") == product.get("product_id")

    def test_list_orders_response_contains_both_order_ids(self, coinbase_rest_client, api_reference_root):
        """Live contract check that orders include both client_order_id and order_id."""
        # Coinbase rejects OPEN mixed with other statuses in one request.
        orders_response = coinbase_rest_client.list_orders(order_status=["OPEN"])
        orders_dict = orders_response.to_dict() if hasattr(orders_response, "to_dict") else orders_response

        assert isinstance(orders_dict, dict)
        assert "orders" in orders_dict
        assert isinstance(orders_dict["orders"], list)

        contract_example = _load_contract_example(
            api_reference_root,
            "orders",
            "list_orders_response.json",
        )
        contract_order_keys = set(contract_example.get("orders", [{}])[0].keys())

        if orders_dict["orders"]:
            first_order = orders_dict["orders"][0]
            assert contract_order_keys.issubset(set(first_order.keys()))
            assert "client_order_id" in first_order
            assert "order_id" in first_order

    def test_get_products_wrapper_returns_typed_products(self, coinbase_rest_client):
        """Wrapper-level contract check for typed Product conversion path."""
        products = coinbase_rest_client.get_products(["BTC-USD", "ETH-USD"])
        assert isinstance(products, dict)

        if products:
            for product_id, product in products.items():
                assert product.product_id == product_id
                assert product.base_increment is not None
                assert product.quote_increment is not None


@pytest.mark.external
@pytest.mark.coinbase
@pytest.mark.websocket
class TestCoinbaseWebSocket:
    """Test Coinbase WebSocket integration."""

    def test_websocket_reference_contains_order_modal_fields(self, project_root):
        """Contract check for authenticated user message payload key fields."""
        payload = json.loads(
            (Path(project_root) / "websocket_reference" / "authenticated" / "user_message.json").read_text(
                encoding="utf-8"
            )
        )
        example_order = payload["example"]["events"][0]["orders"][0]

        required_fields = {
            "client_order_id",
            "order_id",
            "product_id",
            "status",
            "order_side",
            "time_in_force",
            "limit_price",
            "total_fees",
        }
        assert required_fields.issubset(set(example_order.keys()))
        assert example_order["client_order_id"] != example_order["order_id"]

    def test_websocket_wrapper_subscribe_and_callbacks(self):
        """Wrapper behavior contract without network I/O."""
        sdk_client = Mock()
        ws_client = CoinbaseWebSocketClient(sdk_client)

        on_message_cb = Mock()
        on_error_cb = Mock()
        ws_client.subscribe(
            products=["BTC-USD"],
            channels=["ticker", "user"],
            on_message=on_message_cb,
            on_error=on_error_cb,
        )

        sdk_client.on_message.assert_called_once_with(on_message_cb)
        sdk_client.on_error.assert_called_once_with(on_error_cb)
        assert sdk_client.subscribe.call_count == 2

    def test_websocket_subscribe_ticker_live_opt_in(
        self,
        coinbase_credentials,
        coinbase_websocket_external_enabled,
    ):
        """Live ticker smoke test, gated by COINBASE_ENABLE_WEBSOCKET_EXTERNAL=true."""
        if not coinbase_websocket_external_enabled:
            pytest.skip("Set COINBASE_ENABLE_WEBSOCKET_EXTERNAL=true to run live websocket tests")

        message_seen = threading.Event()
        received = {"ticker": None}

        def on_message(message):
            data = json.loads(message) if isinstance(message, str) else message
            if isinstance(data, dict) and data.get("channel") == "ticker":
                events = data.get("events") or []
                if events:
                    tickers = events[0].get("tickers") or []
                    if tickers:
                        received["ticker"] = tickers[0]
                        message_seen.set()

        sdk_client = WSClient(
            verbose=False,
            api_key=coinbase_credentials["api_key"],
            api_secret=coinbase_credentials["api_secret"],
            on_message=on_message,
        )
        ws_client = CoinbaseWebSocketClient(sdk_client)

        try:
            ws_client.connect()
            ws_client.subscribe(products=["BTC-USD"], channels=["ticker"])

            for _ in range(15):
                if message_seen.is_set():
                    break
                if ws_client.sleep_with_exception_check(1):
                    break
        finally:
            ws_client.disconnect()

        assert message_seen.is_set(), "No ticker message received during live websocket smoke window"
        assert received["ticker"] is not None
        assert "product_id" in received["ticker"]
        assert "price" in received["ticker"]

    def test_websocket_receive_done_message(self, coinbase_websocket_external_enabled):
        """Reserved for future authenticated order lifecycle websocket tests."""
        if not coinbase_websocket_external_enabled:
            pytest.skip("Set COINBASE_ENABLE_WEBSOCKET_EXTERNAL=true to run live websocket tests")
        pytest.skip("User-channel done-message live scenario not yet implemented")

    def test_websocket_reconnect_on_disconnect(self, coinbase_websocket_external_enabled):
        """Reserved for future reconnect behavior test under forced disconnect."""
        if not coinbase_websocket_external_enabled:
            pytest.skip("Set COINBASE_ENABLE_WEBSOCKET_EXTERNAL=true to run live websocket tests")
        pytest.skip("Reconnect simulation requires controlled websocket proxy/harness")


# Skip all external tests in normal test runs
# Run with: pytest tests/external/ -v -m external
