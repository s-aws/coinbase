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


def coinbase_sdk_response_to_dict(response: Any) -> Any:
    """Return a plain dict for Coinbase SDK response objects when possible."""
    converter = getattr(response, "to_dict", None)
    if callable(converter):
        return converter()
    return response


def list_all_account_dicts(
    sdk_client: RESTClient,
    *,
    limit: int = 250,
) -> List[Dict[str, Any]]:
    """Return every account from Coinbase, following list-account cursors."""
    accounts: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    seen_cursors: set[str] = set()

    while True:
        response = coinbase_sdk_response_to_dict(
            sdk_client.get_accounts(limit=limit, cursor=cursor)
        )
        page_accounts = response.get("accounts") or []
        accounts.extend(page_accounts)

        if not response.get("has_next"):
            break

        next_cursor = response.get("cursor")
        if not next_cursor or next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    return accounts


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
        accounts_list = list_all_account_dicts(self._client)
        
        wallets = {}
        for account in accounts_list:
            if account.get("deleted_at") is None:
                currency = account.get("currency")
                wallet = Wallet.from_wallet_dict(account)
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
        return coinbase_sdk_response_to_dict(response)
    
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
            data = coinbase_sdk_response_to_dict(response)
            return Product.from_product_dict(data)
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
        response = self._client.list_orders(order_status=["OPEN"])
        orders_list = coinbase_sdk_response_to_dict(response)["orders"]
        
        orders = {}
        for order_data in orders_list:
            client_order_id = order_data.get("client_order_id")
            order = Order.from_order_dict(order_data)
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
    ) -> Dict[str, Any]:
        """Place a limit order.

        Returns the SDK response shape (Coinbase Advanced Trade
        ``CreateOrderResponse``):

        .. code-block:: python

            {
                "success": True,
                "success_response": {
                    "order_id": "...",        # exchange-assigned id
                    "client_order_id": "...", # the id we sent
                    "product_id": "...",
                    "side": "BUY" | "SELL",
                },
                "order_configuration": {...},
                "failure_reason": "...",        # only on success=False
                "error_response": {...},        # only on success=False
            }

        NOTE: Earlier versions of this method tried to coerce the
        response into an :class:`Order` via ``Order.from_dict``, but
        ``Order.from_dict`` expects ``side``/``order_side`` at the top
        level whereas the SDK nests them under ``success_response``.
        That coercion raised on every successful place call (silently
        swallowed by the broad ``except`` in
        ``StealthOrderManager.reveal_order_slice``), causing the
        stealth manager to lose the link between the placement and the
        stealth order it belongs to. The fix is to return the raw dict
        \u2014 every existing caller already treats it as such.
        """
        # Use limit_order_gtc() which works with the current SDK
        # (time_in_force param is ignored as SDK uses GTC for this method)
        response = self.limit_order_gtc(
            product_id=product_id,
            side=side,
            limit_price=limit_price,
            base_size=base_size,
            quote_size=quote_size,
            client_order_id=client_order_id,
            post_only=post_only
        )

        return coinbase_sdk_response_to_dict(response)

    def cancel_order(self, client_order_id: str) -> bool:
        """Cancel a single order by client order ID.
        
        Coinbase accepts either order_id (exchange-assigned) or client_order_id (ours).
        We use client_order_id because:
        - We always have it (we generate it for every order)
        - It works for both revealed and unrevealed orders
        - More robust than relying on exchange-assigned order_id
        
        Args:
            client_order_id: The client order ID we generated for this order
        
        Returns:
            True if cancel successful, False if order not found
        
        Raises:
            Exception: If API call fails
        
        Examples:
            >>> success = client.cancel_order('550e8400-e29b-41d4-a716-446655440000')
            >>> if success:
            ...     print("Order cancelled")
        """
        result = self._client.cancel_orders([client_order_id])
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
        response = self._client.list_futures_positions()
        futures_response = coinbase_sdk_response_to_dict(response)
        futures_list = futures_response.get("positions", [])
        
        positions = {}
        for position_data in futures_list:
            product_id = position_data.get("product_id")
            position = Position.from_position_dict(position_data)
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
        getter = getattr(self._client, "get_portfolio_breakdown", None)
        if callable(getter):
            response = getter(portfolio_id)
        else:
            response = self._client.get_portfolio(portfolio_id)
        return coinbase_sdk_response_to_dict(response)
    
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
        lister = getattr(self._client, "get_portfolios", None)
        if callable(lister):
            response = lister()
        else:
            response = self._client.list_portfolios()
        return coinbase_sdk_response_to_dict(response).get("portfolios", [])
    
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
            return coinbase_sdk_response_to_dict(response)
        except Exception as e:
            if "404" in str(e) or "not found" in str(e).lower():
                return None
            raise
    
    def get_accounts(
        self,
        *,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get raw accounts data from SDK.

        Args:
            limit: Optional Coinbase page size.
            cursor: Optional Coinbase pagination cursor.
        
        Returns:
            Raw response dict with 'accounts' key
        
        Raises:
            Exception: If API call fails
        """
        kwargs: Dict[str, Any] = {}
        if limit is not None:
            kwargs["limit"] = limit
        if cursor is not None:
            kwargs["cursor"] = cursor
        response = self._client.get_accounts(**kwargs)
        return coinbase_sdk_response_to_dict(response)
    
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

    def list_fills(
        self,
        *,
        order_id: Optional[str] = None,
        product_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """List historical fills (per-match trade records).

        Wraps Coinbase's ``GET /api/v3/brokerage/orders/historical/fills``.
        Used by startup reconciliation and the periodic auditor to detect
        fills the WebSocket pipeline may have missed during downtime or
        reconnects, and to recover the authoritative ``trade_id`` /
        ``entry_id`` pair for ledger rows.

        Args:
            order_id: Filter to a single exchange order id.
            product_id: Filter to one product (e.g. ``"BTC-USDC"``).
            start_date: ISO-8601 lower bound for ``trade_time``.
            end_date: ISO-8601 upper bound for ``trade_time``.
            cursor: Opaque pagination cursor returned by a prior call.
            limit: Page size; Coinbase caps at 100.

        Returns:
            Raw dict with shape ``{"fills": [...], "cursor": "...", "has_next": bool}``.
            Fields per fill match ``api_reference/orders/list_fills_response.json``.

        Raises:
            Exception: Propagated from the SDK on transport / auth failure.
        """
        # Filter out None values so we don't override SDK defaults.
        # NOTE: parameter names below MUST match the SDK signature
        # ``RESTClient.get_fills(order_ids, product_ids,
        # start_sequence_timestamp, end_sequence_timestamp, ...)``.
        # The SDK accepts ``**kwargs`` and silently DROPS unknown
        # parameter names — passing the user-facing names ``product_id``,
        # ``start_date``, ``end_date`` here makes the filter a no-op and
        # the call returns ALL historical fills. (2026-04-30 incident:
        # the 24h fee report and the startup missed-fills audit were
        # both reading unfiltered all-time data.)
        kwargs: Dict[str, Any] = {"limit": limit}
        if order_id is not None:
            kwargs["order_ids"] = [order_id]
        if product_id is not None:
            kwargs["product_ids"] = [product_id]
        if start_date is not None:
            kwargs["start_sequence_timestamp"] = start_date
        if end_date is not None:
            kwargs["end_sequence_timestamp"] = end_date
        if cursor is not None:
            kwargs["cursor"] = cursor

        response = self._client.get_fills(**kwargs)
        return coinbase_sdk_response_to_dict(response)

    def get_candles(
        self,
        product_id: str,
        start: int,
        end: int,
        granularity: str = "ONE_MINUTE",
    ) -> List[Dict[str, Any]]:
        """Fetch historical OHLC candles for a product.

        Wraps Coinbase's ``GET /api/v3/brokerage/products/{product_id}/candles``.
        Used by the slide-calibration backfill tool to populate
        ``market_candle_1m`` so the calibration chart has historical
        market context before the live tick recorder accumulates a day.

        Coinbase caps each call at **350 candles**, so callers wanting a
        full day of 1-minute data (1440 candles) must page in <=350-candle
        windows. The backfill tool in ``genai_tools/backfill_candles.py``
        does this paging.

        Args:
            product_id: e.g. ``"BTC-USDC"`` or ``"BIT-29MAY26-CDE"``.
            start: Window start as a Unix epoch (seconds).
            end: Window end as a Unix epoch (seconds).
            granularity: One of Coinbase's documented granularity strings;
                ``"ONE_MINUTE"`` (default), ``"FIVE_MINUTE"``, ``"FIFTEEN_MINUTE"``,
                ``"THIRTY_MINUTE"``, ``"ONE_HOUR"``, ``"TWO_HOUR"``,
                ``"SIX_HOUR"``, ``"ONE_DAY"``.

        Returns:
            List of candle dicts ordered newest-first, each with keys
            ``start, low, high, open, close, volume`` (all as strings per
            Coinbase's response shape).

        Raises:
            Exception: Propagated from the SDK on transport / auth failure.
        """
        response = self._client.get_candles(
            product_id=product_id,
            start=str(int(start)),
            end=str(int(end)),
            granularity=granularity,
        )
        data = coinbase_sdk_response_to_dict(response)
        return list(data.get("candles", []) or [])

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
