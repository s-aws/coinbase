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
        return self._client.get_transaction_summary()
    
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
            data = self._client.get_product(product_id)
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
