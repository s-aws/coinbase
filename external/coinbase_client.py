"""Coinbase REST API client wrapper.

Provides a clean abstraction layer for all Coinbase REST API interactions.
Encapsulates the SDK client and provides type-safe methods for API operations.

This allows:
- Testing with mock implementations
- Swapping implementations without affecting business logic
- Consistent error handling across API calls
- Clear documentation of what data flows between layers

Usage:
    >>> from external.coinbase_client import CoinbaseRestClient
    >>> from coinbase.rest import RESTClient
    >>> 
    >>> sdk_client = RESTClient(api_key=..., api_secret=...)
    >>> client = CoinbaseRestClient(sdk_client)
    >>> 
    >>> products = client.get_products(['BTC-USDC', 'ETH-USDC'])
    >>> wallets = client.get_account_wallets()
"""

from typing import Dict, List, Optional, Any
from coinbase.rest import RESTClient
from core.models import Product, Wallet, Position, Order
from core.enums import OrderSide, TimeInForce


class CoinbaseRestClient:
    """Wrapper around Coinbase REST SDK client.
    
    Provides type-safe methods for interacting with Coinbase Advanced API.
    Handles response parsing and error handling consistently.
    """
    
    def __init__(self, sdk_client: RESTClient):
        """Initialize with a Coinbase SDK RESTClient.
        
        Args:
            sdk_client: Initialized coinbase.rest.RESTClient instance
        
        Raises:
            ValueError: If sdk_client is None
        """
        if sdk_client is None:
            raise ValueError("sdk_client cannot be None")
        self._client = sdk_client
    
    # ========================================================================
    # Account & Wallet Methods
    # ========================================================================
    
    def get_account_wallets(self) -> Dict[str, Wallet]:
        """Retrieve all active account wallets.
        
        Fetches account information for all currencies with active wallets.
        Filters out deleted accounts.
        
        Returns:
            Dictionary mapping currency codes (e.g., 'BTC', 'USDC') to Wallet instances.
            Structure: {'BTC': Wallet(...), 'USDC': Wallet(...), ...}
        
        Raises:
            Exception: If API call fails (authentication, network, etc.)
        
        Examples:
            >>> wallets = client.get_account_wallets()
            >>> btc_wallet = wallets.get('BTC')
            >>> if btc_wallet:
            ...     print(f"BTC available: {btc_wallet.available_balance}")
        """
        accounts_list = self._client.get_accounts()["accounts"]
        
        wallets = {}
        for account in accounts_list:
            if account.get("deleted_at") is None:
                currency = account.get("currency")
                wallet = Wallet.from_dict(account)
                wallets[currency] = wallet
        
        return wallets
    
    def get_transaction_summary(self) -> Dict[str, Any]:
        """Retrieve account transaction summary.
        
        Gets aggregate data on transaction fees and volumes.
        
        Returns:
            Dictionary with transaction summary data
        
        Raises:
            Exception: If API call fails
        
        Examples:
            >>> summary = client.get_transaction_summary()
            >>> fees = summary.get('total_fees')
        """
        response = self._client.get_transaction_summary()
        return response.to_dict() if hasattr(response, 'to_dict') else response
    
    # ========================================================================
    # Product Methods
    # ========================================================================
    
    def get_product(self, product_id: str) -> Optional[Product]:
        """Retrieve a single product by ID.
        
        Args:
            product_id: The product identifier (e.g., 'BTC-USDC', 'BIP-20DEC30-CDE')
        
        Returns:
            Product instance if found, None if product doesn't exist
        
        Raises:
            Exception: If API call fails
        
        Examples:
            >>> product = client.get_product('BTC-USDC')
            >>> if product:
            ...     print(f"Price increment: {product.price_increment}")
        """
        try:
            response = self._client.get_product(product_id)
            data = response.to_dict() if hasattr(response, 'to_dict') else response
            return Product.from_dict(data)
        except Exception as e:
            # Check if it's a 404 - product not found
            if "404" in str(e) or "not found" in str(e).lower():
                return None
            raise
    
    def get_products(self, product_ids: List[str]) -> Dict[str, Product]:
        """Retrieve multiple products by ID.
        
        Filters out trading-disabled products.
        
        Args:
            product_ids: List of product identifiers
        
        Returns:
            Dictionary mapping product_id to Product instances.
            Trading-disabled products are excluded.
        
        Raises:
            Exception: If any API call fails
        
        Examples:
            >>> products = client.get_products(['BTC-USDC', 'ETH-USDC'])
            >>> btc = products['BTC-USDC']
            >>> print(f"BTC price increment: {btc.price_increment}")
        """
        products = {}
        
        for product_id in product_ids:
            try:
                product = self.get_product(product_id)
                if product and not product.trading_disabled:
                    products[product_id] = product
            except Exception:
                # Skip products that fail to load
                continue
        
        return products
    
    # ========================================================================
    # Order Methods
    # ========================================================================
    
    def get_open_orders(self) -> Dict[str, Order]:
        """Retrieve all open orders.
        
        Returns:
            Dictionary mapping client_order_id to Order instances
        
        Raises:
            Exception: If API call fails
        
        Examples:
            >>> open_orders = client.get_open_orders()
            >>> for client_id, order in open_orders.items():
            ...     print(f"Order {client_id}: {order.product_id} {order.order_side}")
        """
        orders_list = self._client.list_orders(order_status=["OPEN"]).to_dict()["orders"]
        
        orders = {}
        for order_data in orders_list:
            client_order_id = order_data.get("client_order_id")
            order = Order.from_dict(order_data)
            orders[client_order_id] = order
        
        return orders
    
    def place_limit_order(
        self,
        product_id: str,
        side: str,
        limit_price: str,
        base_size: str = None,
        quote_size: str = None,
        client_order_id: str = None,
        post_only: bool = False,
        time_in_force: str = TimeInForce.GOOD_UNTIL_CANCELLED.value
    ) -> Order:
        """Place a limit order.
        
        Args:
            product_id: Trading pair (e.g., 'BTC-USDC')
            side: 'BUY' or 'SELL'
            limit_price: Limit price as string (e.g., '40000.00')
            base_size: Size in base currency (mutually exclusive with quote_size)
            quote_size: Size in quote currency (mutually exclusive with base_size)
            client_order_id: Custom order ID for idempotency
            post_only: If True, order rejected if it would immediately fill
            time_in_force: 'GOOD_TILL_CANCELLED', 'IMMEDIATE_OR_CANCEL', etc.
        
        Returns:
            Order instance with order confirmation data
        
        Raises:
            ValueError: If invalid parameters
            Exception: If API call fails (e.g., INSUFFICIENT_FUNDS)
        
        Examples:
            >>> order = client.place_limit_order(
            ...     product_id='BTC-USDC',
            ...     side='BUY',
            ...     limit_price='40000.00',
            ...     base_size='0.1',
            ...     client_order_id='my_order_123'
            ... )
            >>> print(f"Order {order.order_id} placed")
        """
        response = self._client.create_order(
            product_id=product_id,
            side=side,
            order_type="LIMIT",
            limit_price=limit_price,
            base_size=base_size,
            quote_size=quote_size,
            client_order_id=client_order_id,
            post_only=post_only,
            time_in_force=time_in_force
        )
        
        return Order.from_dict(response)
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order by order ID.
        
        Args:
            order_id: The order ID to cancel (not client_order_id)
        
        Returns:
            True if cancel successful, False if order not found
        
        Raises:
            Exception: If API call fails
        
        Examples:
            >>> success = client.cancel_order('abc123def456')
            >>> if success:
            ...     print("Order cancelled")
        """
        result = self._client.cancel_orders([order_id])
        return result and len(result) > 0
    
    # ========================================================================
    # Futures Methods
    # ========================================================================
    
    def get_futures_positions(self) -> Dict[str, Position]:
        """Retrieve all open futures positions.
        
        Returns empty dict if no open positions.
        
        Returns:
            Dictionary mapping product_id to Position instances
        
        Raises:
            Exception: If API call fails
        
        Examples:
            >>> positions = client.get_futures_positions()
            >>> if 'BIP-20DEC30-CDE' in positions:
            ...     pos = positions['BIP-20DEC30-CDE']
            ...     print(f"Contracts: {pos.number_of_contracts}")
        """
        futures_response = self._client.list_futures_positions().to_dict()
        futures_list = futures_response.get("positions", [])
        
        positions = {}
        for position_data in futures_list:
            product_id = position_data.get("product_id")
            position = Position.from_dict(position_data)
            positions[product_id] = position
        
        return positions
    
    # ========================================================================
    # Portfolio Methods
    # ========================================================================
    
    def get_portfolio(self, portfolio_id: str) -> Dict[str, Any]:
        """Retrieve a specific portfolio.
        
        Args:
            portfolio_id: The portfolio ID
        
        Returns:
            Portfolio data dictionary
        
        Raises:
            Exception: If API call fails
        
        Examples:
            >>> portfolio = client.get_portfolio('default')
            >>> balance = portfolio.get('breakdown', {}).get('total_balance')
        """
        return self._client.get_portfolio(portfolio_id).to_dict()
    
    def list_portfolios(self) -> List[Dict[str, Any]]:
        """List all portfolios.
        
        Returns:
            List of portfolio data dictionaries
        
        Raises:
            Exception: If API call fails
        
        Examples:
            >>> portfolios = client.list_portfolios()
            >>> for portfolio in portfolios:
            ...     print(f"Portfolio: {portfolio['name']}")
        """
        response = self._client.list_portfolios()
        return response.to_dict().get("portfolios", [])
    
    # ========================================================================
    # Pass-through Methods (Raw SDK Access)
    # ========================================================================
    
    def get_product_dict(self, product_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single product by ID as a raw dict.
        
        Raw pass-through to SDK for use cases that need dict instead of Product object.
        
        Args:
            product_id: The product identifier (e.g., 'BTC-USDC')
        
        Returns:
            Product data dict if found, None if not found
        
        Raises:
            Exception: If API call fails
        """
        try:
            response = self._client.get_product(product_id)
            return response.to_dict() if hasattr(response, 'to_dict') else response
        except Exception as e:
            if "404" in str(e) or "not found" in str(e).lower():
                return None
            raise
    
    def get_accounts(self) -> Dict[str, Any]:
        """Get raw accounts data from SDK.
        
        Returns:
            Raw response dict with 'accounts' key
        
        Raises:
            Exception: If API call fails
        """
        response = self._client.get_accounts()
        return response.to_dict() if hasattr(response, 'to_dict') else response
    
    def list_orders(self, order_status: Optional[List[str]] = None) -> Dict[str, Any]:
        """List orders with optional status filter.
        
        Args:
            order_status: List of order statuses to filter (e.g., ['OPEN', 'FILLED'])
        
        Returns:
            Raw SDK response object (call .to_dict() to get dict)
        
        Raises:
            Exception: If API call fails
        """
        return self._client.list_orders(order_status=order_status)
    
    def list_futures_positions(self):
        """List all futures positions (raw SDK response).
        
        Returns:
            Raw SDK response object (call .to_dict() to get dict)
        
        Raises:
            Exception: If API call fails
        """
        return self._client.list_futures_positions()
    
    def cancel_orders(self, order_ids: List[str]) -> List[Dict[str, Any]]:
        """Cancel multiple orders by order IDs.
        
        Args:
            order_ids: List of order IDs to cancel
        
        Returns:
            List of cancel results
        
        Raises:
            Exception: If API call fails
        """
        return self._client.cancel_orders(order_ids)
    
    def limit_order_gtc(
        self,
        product_id: str,
        side: str,
        base_size: Optional[str] = None,
        quote_size: Optional[str] = None,
        limit_price: Optional[str] = None,
        client_order_id: Optional[str] = None,
        post_only: bool = False,
        **kwargs
    ):
        """Place a Good-Till-Cancelled (GTC) limit order.
        
        Convenience method that wraps the SDK limit_order_gtc for the most common order type.
        Accepts the parameter names used by the Coinbase SDK.
        
        Args:
            product_id: Trading pair (e.g., 'BTC-USDC')
            side: 'BUY' or 'SELL'
            base_size: Order size in base currency (required)
            quote_size: Order size in quote currency (optional, alternative to base_size)
            limit_price: Limit price as string (required)
            client_order_id: Custom order ID for idempotency
            post_only: If True, order rejected if it would immediately fill
            **kwargs: Additional parameters passed to SDK
        
        Returns:
            Raw SDK response object (call .to_dict() to get dict)
        
        Raises:
            Exception: If API call fails or required parameters missing
        """
        if not client_order_id:
            import uuid
            client_order_id = str(uuid.uuid4())
        
        if not base_size and not quote_size:
            raise ValueError("Either base_size or quote_size must be provided")
        
        if not limit_price:
            raise ValueError("limit_price is required")
        
        # SDK requires positional args: client_order_id, product_id, side, base_size, limit_price
        return self._client.limit_order_gtc(
            client_order_id=client_order_id,
            product_id=product_id,
            side=side,
            base_size=base_size or quote_size,
            limit_price=limit_price,
            post_only=post_only,
            **kwargs
        )
    
    def create_order(
        self,
        product_id: str,
        side: str,
        order_type: Optional[str] = None,
        client_order_id: Optional[str] = None,
        order_configuration: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Create an order via SDK.
        
        Flexible pass-through to SDK for all order types.
        Accepts either old-style (order_type) or new-style (order_configuration) parameters.
        
        Args:
            product_id: Trading pair
            side: 'BUY' or 'SELL'
            order_type: Order type (e.g., 'LIMIT', 'MARKET') for old-style orders
            client_order_id: Custom order ID for idempotency
            order_configuration: Order configuration dict (new-style API)
            **kwargs: Additional order parameters
        
        Returns:
            Raw SDK response (may need .to_dict() call)
        
        Raises:
            Exception: If API call fails
        """
        params = {
            'product_id': product_id,
            'side': side,
        }
        
        if order_type:
            params['order_type'] = order_type
        if client_order_id:
            params['client_order_id'] = client_order_id
        if order_configuration:
            params['order_configuration'] = order_configuration
        
        params.update(kwargs)
        
        return self._client.create_order(**params)
    
    def get_sdk_client(self) -> RESTClient:
        """Get the underlying SDK client (for advanced use only).
        
        Use with caution - direct SDK access bypasses abstraction.
        
        Returns:
            The underlying coinbase.rest.RESTClient
        
        Examples:
            >>> sdk_client = client.get_sdk_client()
            >>> # Advanced operations...
        """
        return self._client
