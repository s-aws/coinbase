"""Test fixtures loaded from API reference JSON files.

This module loads example API responses and WebSocket messages from the
api_reference/ and websocket_reference/ directories, making them available
as test fixtures throughout the test suite.

This ensures tests use realistic data that matches the actual Coinbase API
specification, improving test reliability and catching schema changes early.

Usage:
    >>> from tests.fixtures import load_order_response, load_user_message
    >>> 
    >>> # Load real API response examples
    >>> order_resp = load_order_response('create')
    >>> print(order_resp['example_success'])
    >>> 
    >>> # Load WebSocket message examples
    >>> user_msg = load_user_message()
    >>> print(user_msg['response_structure'])
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional, List


class APIReferenceLoader:
    """Loads API reference JSON files from api_reference/ directory."""
    
    def __init__(self):
        """Initialize loader with path to api_reference directory."""
        self.base_path = Path(__file__).parent.parent / "api_reference"
        if not self.base_path.exists():
            raise FileNotFoundError(f"api_reference directory not found at {self.base_path}")
    
    def load_json(self, relative_path: str) -> Dict[str, Any]:
        """Load a JSON file from api_reference directory.
        
        Args:
            relative_path: Path relative to api_reference/ (e.g., "orders/create_order_response.json")
        
        Returns:
            Parsed JSON data as dictionary
        
        Raises:
            FileNotFoundError: If file doesn't exist
            json.JSONDecodeError: If file is invalid JSON
        """
        file_path = self.base_path / relative_path
        if not file_path.exists():
            raise FileNotFoundError(f"Reference file not found: {file_path}")
        
        with open(file_path, 'r') as f:
            return json.load(f)
    
    # ========================================================================
    # Order References
    # ========================================================================
    
    def load_order_response(self, action: str) -> Dict[str, Any]:
        """Load order response reference (create, cancel, list).
        
        Args:
            action: 'create', 'cancel', or 'list'
        
        Returns:
            Reference schema with examples
        
        Examples:
            >>> resp = loader.load_order_response('create')
            >>> example = resp['example_success']
        """
        return self.load_json(f"orders/{action}_order_response.json")
    
    def load_order_request(self, action: str) -> Dict[str, Any]:
        """Load order request reference.
        
        Args:
            action: 'create', 'cancel', or 'list'
        
        Returns:
            Request schema with examples
        """
        return self.load_json(f"orders/{action}_order_request.json")
    
    def load_fills_reference(self) -> Dict[str, Any]:
        """Load fills response reference."""
        return self.load_json("orders/list_fills_response.json")
    
    # ========================================================================
    # Product References
    # ========================================================================
    
    def load_product_response(self) -> Dict[str, Any]:
        """Load product response reference."""
        return self.load_json("products/get_product_response.json")
    
    def load_products_list(self) -> Dict[str, Any]:
        """Load products list response reference."""
        return self.load_json("products/list_products_response.json")
    
    def load_candles_response(self) -> Dict[str, Any]:
        """Load candles response reference."""
        return self.load_json("products/get_candles_response.json")
    
    # ========================================================================
    # Account References
    # ========================================================================
    
    def load_account_response(self) -> Dict[str, Any]:
        """Load single account response reference."""
        return self.load_json("accounts/get_account_response.json")
    
    def load_accounts_list(self) -> Dict[str, Any]:
        """Load accounts list response reference."""
        return self.load_json("accounts/list_accounts_response.json")
    
    # ========================================================================
    # Futures References
    # ========================================================================
    
    def load_positions_response(self) -> Dict[str, Any]:
        """Load futures positions response reference."""
        return self.load_json("perpetuals/list_perpetual_positions_response.json")
    
    def load_perpetual_orders(self) -> Dict[str, Any]:
        """Load perpetual orders reference."""
        return self.load_json("perpetuals/list_perpetual_orders_response.json")
    
    # ========================================================================
    # Portfolio References
    # ========================================================================
    
    def load_portfolio_response(self) -> Dict[str, Any]:
        """Load portfolio response reference."""
        return self.load_json("portfolios/get_portfolio_response.json")
    
    def load_portfolios_list(self) -> Dict[str, Any]:
        """Load portfolios list response reference."""
        return self.load_json("portfolios/list_portfolios_response.json")


class WebSocketReferenceLoader:
    """Loads WebSocket reference JSON files from websocket_reference/ directory."""
    
    def __init__(self):
        """Initialize loader with path to websocket_reference directory."""
        self.base_path = Path(__file__).parent.parent / "websocket_reference"
        if not self.base_path.exists():
            raise FileNotFoundError(f"websocket_reference directory not found at {self.base_path}")
    
    def load_json(self, relative_path: str) -> Dict[str, Any]:
        """Load a JSON file from websocket_reference directory.
        
        Args:
            relative_path: Path relative to websocket_reference/
        
        Returns:
            Parsed JSON data as dictionary
        """
        file_path = self.base_path / relative_path
        if not file_path.exists():
            raise FileNotFoundError(f"Reference file not found: {file_path}")
        
        with open(file_path, 'r') as f:
            return json.load(f)
    
    # ========================================================================
    # Authenticated Channels
    # ========================================================================
    
    def load_user_message(self) -> Dict[str, Any]:
        """Load user channel message reference.
        
        Contains order snapshots and updates.
        """
        return self.load_json("authenticated/user_message.json")
    
    def load_user_subscription(self) -> Dict[str, Any]:
        """Load user channel subscription reference."""
        return self.load_json("authenticated/user_subscription.json")
    
    def load_futures_balance_message(self) -> Dict[str, Any]:
        """Load futures balance summary message reference."""
        return self.load_json("authenticated/futures_balance_summary_message.json")
    
    # ========================================================================
    # Public Channels
    # ========================================================================
    
    def load_ticker_message(self) -> Dict[str, Any]:
        """Load ticker message reference."""
        return self.load_json("public/ticker_message.json")
    
    def load_ticker_batch_message(self) -> Dict[str, Any]:
        """Load ticker batch message reference."""
        return self.load_json("public/ticker_batch_message.json")
    
    def load_level2_message(self) -> Dict[str, Any]:
        """Load level2 (order book) message reference."""
        return self.load_json("public/level2_message.json")
    
    def load_candles_message(self) -> Dict[str, Any]:
        """Load candles message reference."""
        return self.load_json("public/candles_message.json")
    
    def load_market_trades_message(self) -> Dict[str, Any]:
        """Load market trades message reference."""
        return self.load_json("public/market_trades_message.json")
    
    def load_status_message(self) -> Dict[str, Any]:
        """Load status message reference."""
        return self.load_json("public/status_message.json")
    
    def load_heartbeat_message(self) -> Dict[str, Any]:
        """Load heartbeat message reference."""
        return self.load_json("public/heartbeats_message.json")


# Global loaders for convenient access
_api_loader: Optional[APIReferenceLoader] = None
_ws_loader: Optional[WebSocketReferenceLoader] = None


def get_api_loader() -> APIReferenceLoader:
    """Get or create APIReferenceLoader singleton."""
    global _api_loader
    if _api_loader is None:
        _api_loader = APIReferenceLoader()
    return _api_loader


def get_ws_loader() -> WebSocketReferenceLoader:
    """Get or create WebSocketReferenceLoader singleton."""
    global _ws_loader
    if _ws_loader is None:
        _ws_loader = WebSocketReferenceLoader()
    return _ws_loader


# Convenience functions for test imports
def load_order_response(action: str = 'create') -> Dict[str, Any]:
    """Load order response reference (convenience function).
    
    Args:
        action: 'create', 'cancel', or 'list'
    
    Returns:
        Reference schema with examples
    """
    return get_api_loader().load_order_response(action)


def load_user_message() -> Dict[str, Any]:
    """Load user channel message reference (convenience function)."""
    return get_ws_loader().load_user_message()


def load_ticker_message() -> Dict[str, Any]:
    """Load ticker message reference (convenience function)."""
    return get_ws_loader().load_ticker_message()
