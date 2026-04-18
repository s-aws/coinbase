"""External services layer - Coinbase API clients.

This module provides clean abstractions for external services:
- CoinbaseRestClient: REST API wrapper for account, products, orders, etc.
- CoinbaseWebSocketClient: WebSocket connection wrapper for real-time events

These abstractions enable:
- Easy testing with mock implementations
- Swapping implementations without business logic changes
- Consistent error handling and data transformation
- Clear dependency injection in business logic

Usage:
    >>> from external import CoinbaseRestClient, CoinbaseWebSocketClient
    >>> from coinbase.rest import RESTClient
    >>> from coinbase.websocket import WSClient
    >>> 
    >>> # Create SDK clients
    >>> rest_sdk = RESTClient(api_key=api_key, api_secret=api_secret)
    >>> ws_sdk = WSClient(api_key=api_key, api_secret=api_secret)
    >>> 
    >>> # Wrap in our abstractions
    >>> rest_client = CoinbaseRestClient(rest_sdk)
    >>> ws_client = CoinbaseWebSocketClient(ws_sdk)
    >>> 
    >>> # Use in business logic
    >>> products = rest_client.get_products(['BTC-USDC', 'ETH-USDC'])
    >>> wallets = rest_client.get_account_wallets()
"""

from .coinbase_client import CoinbaseRestClient
from .coinbase_websocket import CoinbaseWebSocketClient

__all__ = [
    'CoinbaseRestClient',
    'CoinbaseWebSocketClient',
]
