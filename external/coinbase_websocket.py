"""Coinbase WebSocket client wrapper.

Provides a clean abstraction layer for WebSocket connections to Coinbase.
Encapsulates the SDK WebSocket client and provides type-safe event handling.

This allows:
- Testing with mock implementations
- Swapping implementations without affecting business logic
- Consistent event handling across subscriptions
- Clear documentation of event flows

Usage:
    >>> from external.coinbase_websocket import CoinbaseWebSocketClient
    >>> from coinbase.websocket import WSClient
    >>> 
    >>> def on_message(message):
    ...     print(f"Received: {message}")
    >>> 
    >>> ws_client = WSClient(api_key=..., api_secret=...)
    >>> client = CoinbaseWebSocketClient(ws_client)
    >>> 
    >>> client.subscribe(
    ...     products=['BTC-USDC', 'ETH-USDC'],
    ...     channels=['ticker', 'level2'],
    ...     on_message=on_message
    ... )
    >>> client.connect()
"""

from typing import Callable, List, Dict, Any, Optional
from coinbase.websocket import WSClient


class CoinbaseWebSocketClient:
    """Wrapper around Coinbase WebSocket SDK client.
    
    Provides a clean interface for WebSocket subscriptions and event handling.
    Manages connection lifecycle and message routing.
    """
    
    def __init__(self, sdk_client: WSClient):
        """Initialize with a Coinbase SDK WSClient.
        
        Args:
            sdk_client: Initialized coinbase.websocket.WSClient instance
        
        Raises:
            ValueError: If sdk_client is None
        """
        if sdk_client is None:
            raise ValueError("sdk_client cannot be None")
        self._client = sdk_client
        self._is_connected = False
        self._message_callbacks: List[Callable] = []
        self._error_callbacks: List[Callable] = []
    
    # ========================================================================
    # Connection Management
    # ========================================================================
    
    def connect(self) -> None:
        """Establish WebSocket connection.
        
        Initiates the WebSocket connection. Call subscribe() before this
        to set up subscriptions.
        
        Raises:
            Exception: If connection fails
        
        Examples:
            >>> client = CoinbaseWebSocketClient(ws_client)
            >>> client.subscribe(products=['BTC-USDC'], channels=['ticker'])
            >>> client.connect()  # Blocks until disconnected
        """
        self._is_connected = True
        self._client.open()
    
    def disconnect(self) -> None:
        """Disconnect from WebSocket.
        
        Closes the connection gracefully. Safe to call multiple times.
        
        Examples:
            >>> client.disconnect()
        """
        self._is_connected = False
        self._client.close()
    
    def is_connected(self) -> bool:
        """Check if currently connected.
        
        Returns:
            True if connected to WebSocket, False otherwise
        
        Examples:
            >>> if client.is_connected():
            ...     print("Connected")
        """
        return self._is_connected
    
    # ========================================================================
    # Subscription Management
    # ========================================================================
    
    def subscribe(
        self,
        products: List[str],
        channels: List[str],
        on_message: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_error: Optional[Callable[[str], None]] = None
    ) -> None:
        """Subscribe to WebSocket channels.
        
        Sets up subscriptions for specified products and channels.
        Call before connect().
        
        Args:
            products: List of product IDs (e.g., ['BTC-USDC', 'ETH-USDC'])
            channels: List of channels (e.g., ['ticker', 'level2', 'user'])
            on_message: Callback function for messages (optional)
            on_error: Callback function for errors (optional)
        
        Raises:
            ValueError: If products or channels list is empty
        
        Examples:
            >>> def handle_message(msg):
            ...     print(f"Got message: {msg}")
            >>> 
            >>> client.subscribe(
            ...     products=['BTC-USDC', 'ETH-USDC'],
            ...     channels=['ticker', 'level2'],
            ...     on_message=handle_message
            ... )
        """
        if not products:
            raise ValueError("products list cannot be empty")
        if not channels:
            raise ValueError("channels list cannot be empty")
        
        # Register callbacks if provided
        if on_message:
            self.on_message(on_message)
        if on_error:
            self.on_error(on_error)
        
        # Configure subscription
        for channel in channels:
            if channel == "user":
                # User channel requires authentication (default)
                self._client.subscribe(
                    product_ids=products,
                    channel=channel
                )
            else:
                # Public channels don't require specific auth
                self._client.subscribe(
                    product_ids=products,
                    channel=channel
                )
    
    def unsubscribe(
        self,
        products: Optional[List[str]] = None,
        channels: Optional[List[str]] = None
    ) -> None:
        """Unsubscribe from channels.
        
        Args:
            products: Specific products to unsubscribe from (optional, all if None)
            channels: Specific channels to unsubscribe from (optional, all if None)
        
        Examples:
            >>> client.unsubscribe(products=['BTC-USDC'], channels=['ticker'])
            >>> client.unsubscribe(channels=['level2'])  # Unsubscribe from all products
        """
        if products or channels:
            self._client.unsubscribe(
                product_ids=products,
                channel=channels[0] if channels else None
            )
        else:
            # Unsubscribe from everything
            self._client.close()
    
    # ========================================================================
    # Event Handling
    # ========================================================================
    
    def on_message(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register a callback for WebSocket messages.
        
        The callback will be called with each message dict received.
        
        Args:
            callback: Function(message_dict) -> None
        
        Examples:
            >>> def handle_message(msg):
            ...     print(f"Message type: {msg.get('type')}")
            >>> 
            >>> client.on_message(handle_message)
        """
        self._message_callbacks.append(callback)
        # Register with SDK client
        self._client.on_message(callback)
    
    def on_error(self, callback: Callable[[str], None]) -> None:
        """Register a callback for WebSocket errors.
        
        The callback will be called with error messages.
        
        Args:
            callback: Function(error_message: str) -> None
        
        Examples:
            >>> def handle_error(error):
            ...     print(f"WebSocket error: {error}")
            >>> 
            >>> client.on_error(handle_error)
        """
        self._error_callbacks.append(callback)
        # Register with SDK client
        self._client.on_error(callback)
    
    def on_open(self, callback: Callable[[], None]) -> None:
        """Register a callback for when connection opens.
        
        Args:
            callback: Function() -> None
        
        Examples:
            >>> def on_connect():
            ...     print("Connected to WebSocket")
            >>> 
            >>> client.on_open(on_connect)
        """
        self._client.on_open(callback)
    
    def on_close(self, callback: Callable[[], None]) -> None:
        """Register a callback for when connection closes.
        
        Args:
            callback: Function() -> None
        
        Examples:
            >>> def on_disconnect():
            ...     print("Disconnected from WebSocket")
            >>> 
            >>> client.on_close(on_disconnect)
        """
        self._client.on_close(callback)
    
    # ========================================================================
    # Utility Methods
    # ========================================================================
    
    def get_sdk_client(self) -> WSClient:
        """Get the underlying SDK client (for advanced use only).
        
        Use with caution - direct SDK access bypasses abstraction.
        
        Returns:
            The underlying coinbase.websocket.WSClient
        
        Examples:
            >>> sdk_client = client.get_sdk_client()
            >>> # Advanced operations...
        """
        return self._client
