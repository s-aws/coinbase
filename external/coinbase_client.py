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

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import logging
import math
from typing import Dict, List, Optional, Any
from coinbase.rest import RESTClient
from core.models import Product, Wallet, Position, Order
from core.enums import OrderSide, TimeInForce
from core.coinbase_execution_authority import (
    COINBASE_EXECUTION_SCOPE_SPOT_CANCEL,
    COINBASE_EXECUTION_SCOPE_SPOT_PLACE,
    require_coinbase_execution_authority,
)


ACCOUNT_PAGE_LIMIT = 250
MAX_ACCOUNT_REFRESH_PAGES = 100
MAX_COINBASE_REFRESH_TIMEOUT_SECONDS = 30
_CANCEL_IDENTITY_REJECTION_REASONS = {
    "ORDER_NOT_FOUND",
    "UNKNOWN_CANCEL_ORDER",
}


@dataclass(frozen=True)
class StrictAccountWalletRead:
    """One no-retry cursor walk with explicit completeness evidence."""

    wallets: Dict[str, Wallet]
    complete: bool
    page_count: int
    request_count: int
    blocker: str | None
    portfolio_ids: frozenset[str]


class _CoinbaseSdkValueBlindLogFilter(logging.Filter):
    """Prevent the pinned SDK from logging raw response bodies or JSON."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = "Coinbase SDK transport detail withheld."
        record.args = ()
        return True


def _install_coinbase_sdk_value_blind_logging() -> None:
    sdk_logger = logging.getLogger("coinbase.RESTClient")
    if not any(
        isinstance(item, _CoinbaseSdkValueBlindLogFilter)
        for item in sdk_logger.filters
    ):
        sdk_logger.addFilter(_CoinbaseSdkValueBlindLogFilter())


def _harden_sdk_transport(
    sdk_client: Any,
    *,
    require_bounded_timeout: bool = False,
) -> None:
    """Fail closed on retries and prevent Requests from following redirects.

    The Coinbase SDK delegates to ``requests.Session.request`` without setting
    ``allow_redirects``.  A zero ``max_redirects`` therefore allows the first
    bounded request to receive a redirect response but raises before Requests
    can emit a redirected second wire request.  Test doubles without a Session
    remain supported; the canonical production SDK always exposes one.
    """

    _install_coinbase_sdk_value_blind_logging()
    session = getattr(sdk_client, "session", None)
    if session is None:
        return
    if require_bounded_timeout:
        timeout = getattr(sdk_client, "timeout", None)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
            or timeout > MAX_COINBASE_REFRESH_TIMEOUT_SECONDS
        ):
            raise ValueError("coinbase_sdk_transport_timeout_forbidden")
        if getattr(sdk_client, "base_url", None) != "api.coinbase.com":
            raise ValueError("coinbase_sdk_transport_base_url_forbidden")
        if getattr(session, "verify", None) is not True:
            raise ValueError("coinbase_sdk_transport_tls_verification_required")
    adapters = getattr(session, "adapters", None)
    if not isinstance(adapters, Mapping) or set(adapters) != {
        "http://",
        "https://",
    }:
        raise ValueError("coinbase_sdk_transport_invalid")
    for adapter in adapters.values():
        retry_total = getattr(getattr(adapter, "max_retries", None), "total", None)
        if type(retry_total) is not int or retry_total != 0:
            raise ValueError("coinbase_sdk_transport_retry_forbidden")
    session.max_redirects = 0
    session.trust_env = False
    session.proxies = {}


def coinbase_sdk_response_to_dict(response: Any) -> Any:
    """Return a plain dict for Coinbase SDK response objects when possible."""
    converter = getattr(response, "to_dict", None)
    if callable(converter):
        return converter()
    return response


def coinbase_cancel_response_evidence(
    response: Any,
    *,
    expected_order_id: str | None = None,
) -> Dict[str, Any]:
    """Classify one cancel response as success, explicit rejection, or unknown.

    A boolean ``False`` is intentionally unknown: it does not prove Coinbase
    rejected the supplied identity. A structured result is required to classify
    an explicit rejection for reconciliation; rejection never authorizes an
    identity fallback or second submission.
    """

    data = coinbase_sdk_response_to_dict(response)

    def classify(item: Any) -> tuple[str, Optional[str]]:
        item = coinbase_sdk_response_to_dict(item)
        if item is True:
            return "succeeded", None
        if item is False or item is None or not isinstance(item, dict):
            return "unknown", None
        if item.get("success") is True:
            return "succeeded", None
        if item.get("success") is False:
            reason = str(
                item.get("failure_reason")
                or item.get("error")
                or item.get("message")
                or ""
            ).strip()
            if reason.upper() in _CANCEL_IDENTITY_REJECTION_REASONS:
                return "explicitly_rejected", "cancel_identity_rejected"
            return (
                "unknown",
                "unclassified_exchange_rejection" if reason else None,
            )
        return "unknown", None

    if isinstance(data, dict) and isinstance(data.get("results"), list):
        items = list(data["results"])
    elif isinstance(data, list):
        items = list(data)
    else:
        items = [data]

    normalized_items = [coinbase_sdk_response_to_dict(item) for item in items]
    identity_match = bool(
        expected_order_id is None
        or (
            len(normalized_items) == 1
            and isinstance(normalized_items[0], dict)
            and str(normalized_items[0].get("order_id") or "")
            == str(expected_order_id)
        )
    )
    classified = [classify(item) for item in normalized_items]
    outcomes = [outcome for outcome, _reason in classified]
    reasons = [reason for _outcome, reason in classified if reason]
    if items and outcomes and all(outcome == "succeeded" for outcome in outcomes):
        outcome = "succeeded"
    elif items and outcomes and all(
        item_outcome == "explicitly_rejected" for item_outcome in outcomes
    ):
        outcome = "explicitly_rejected"
    else:
        outcome = "unknown"
    if not identity_match:
        outcome = "unknown"
    return {
        "outcome": outcome,
        "succeeded": outcome == "succeeded",
        "explicit_rejection": outcome == "explicitly_rejected",
        "identity_rejection": outcome == "explicitly_rejected",
        "identity_match": identity_match,
        "failure_reasons": reasons,
        "result_count": len(items),
    }


def coinbase_cancel_response_succeeded(response: Any) -> bool:
    """Return whether a Coinbase cancel response explicitly succeeded.

    The Advanced Trade cancel API can return a batch-style payload with
    per-order ``success`` booleans. Treat unknown or failure-shaped responses as
    failed so callers do not locally accept a rejected exchange cancel.
    """

    return coinbase_cancel_response_evidence(response)["succeeded"] is True


def list_all_account_dicts(
    sdk_client: RESTClient,
    *,
    limit: int = ACCOUNT_PAGE_LIMIT,
) -> List[Dict[str, Any]]:
    """Return every account from Coinbase, following list-account cursors."""
    accounts: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    seen_cursors: set[str] = set()

    while True:
        kwargs: Dict[str, Any] = {"limit": limit}
        if cursor is not None:
            kwargs["cursor"] = cursor
        response = coinbase_sdk_response_to_dict(sdk_client.get_accounts(**kwargs))
        if not isinstance(response, dict):
            return accounts
        page_accounts = response.get("accounts") or []
        accounts.extend(
            account for account in (_object_to_dict(item) for item in page_accounts) if account
        )

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
        _harden_sdk_transport(sdk_client)
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
            account_data = _object_to_dict(account)
            if account_data.get("deleted_at") is None:
                currency = account_data.get("currency")
                wallet = Wallet.from_wallet_dict(account_data)
                wallets[currency] = wallet
        
        return wallets

    def get_account_wallets_strict(self) -> StrictAccountWalletRead:
        """Read every wallet page once and fail closed on cursor anomalies.

        Unlike the compatibility ``get_account_wallets`` helper, this method
        retains explicit completeness and wire-request accounting for an
        operator-authorized account-reality refresh. It never retries a page.
        Concrete portfolio identifiers are returned only as internal binding
        input; callers must not persist or expose them.
        """

        accounts: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        seen_cursors: set[str] = set()
        page_count = 0

        def failed(blocker: str) -> StrictAccountWalletRead:
            return StrictAccountWalletRead(
                wallets={},
                complete=False,
                page_count=page_count,
                request_count=page_count,
                blocker=blocker,
                portfolio_ids=frozenset(),
            )

        while True:
            if page_count >= MAX_ACCOUNT_REFRESH_PAGES:
                return failed("account_page_limit_exceeded")
            kwargs: Dict[str, Any] = {"limit": ACCOUNT_PAGE_LIMIT}
            if cursor is not None:
                kwargs["cursor"] = cursor
            try:
                _harden_sdk_transport(
                    self._client,
                    require_bounded_timeout=True,
                )
            except ValueError:
                return failed("account_transport_policy_invalid")
            page_count += 1
            try:
                response = coinbase_sdk_response_to_dict(
                    self._client.get_accounts(**kwargs)
                )
            except Exception:
                return failed("account_page_read_failed")
            if not isinstance(response, dict):
                return failed("account_page_invalid")
            page_accounts = response.get("accounts")
            if not isinstance(page_accounts, list):
                return failed("account_page_accounts_invalid")
            for raw_account in page_accounts:
                account = _object_to_dict(raw_account)
                if not account:
                    return failed("account_row_invalid")
                accounts.append(account)
            has_next = response.get("has_next")
            if type(has_next) is not bool:
                return failed("account_pagination_metadata_invalid")
            if has_next is False:
                break

            raw_cursor = response.get("cursor")
            if not isinstance(raw_cursor, str) or not raw_cursor.strip():
                return failed("account_cursor_missing")
            next_cursor = raw_cursor.strip()
            if next_cursor in seen_cursors:
                return failed("account_cursor_repeated")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        wallets: Dict[str, Wallet] = {}
        portfolio_ids: set[str] = set()
        for account in accounts:
            if account.get("deleted_at") is not None:
                continue
            if account.get("active") is not True or account.get("ready") is not True:
                return failed("account_row_invalid")
            currency = str(account.get("currency") or "").strip().upper()
            if not currency:
                return failed("account_row_invalid")
            if currency in wallets:
                return failed("account_currency_duplicate")
            available_money = _object_to_dict(account.get("available_balance"))
            hold_money = _object_to_dict(account.get("hold"))
            if (
                "value" not in available_money
                or "value" not in hold_money
                or not str(available_money.get("value") or "").strip()
                or not str(hold_money.get("value") or "").strip()
                or str(available_money.get("currency") or "").strip().upper()
                != currency
                or str(hold_money.get("currency") or "").strip().upper()
                != currency
            ):
                return failed("account_balance_invalid")
            try:
                available = Decimal(str(available_money["value"]))
                hold = Decimal(str(hold_money["value"]))
                wallet = Wallet.from_wallet_dict(account)
                total = Decimal(wallet.total_balance)
            except (InvalidOperation, TypeError, ValueError):
                return failed("account_balance_invalid")
            if (
                not available.is_finite()
                or not hold.is_finite()
                or not total.is_finite()
                or available < 0
                or hold < 0
                or total < 0
                or total != available + hold
            ):
                return failed("account_balance_invalid")
            explicit_total = account.get("total_balance", account.get("balance"))
            if explicit_total not in (None, ""):
                explicit_money = _object_to_dict(explicit_total)
                if (
                    "value" not in explicit_money
                    or not str(explicit_money.get("value") or "").strip()
                    or str(explicit_money.get("currency") or "").strip().upper()
                    != currency
                ):
                    return failed("account_balance_invalid")
            portfolio_id = str(
                account.get("retail_portfolio_id")
                or account.get("portfolio_uuid")
                or ""
            ).strip()
            if not portfolio_id:
                return failed("account_row_invalid")
            wallets[currency] = wallet
            portfolio_ids.add(portfolio_id)
        return StrictAccountWalletRead(
            wallets=wallets,
            complete=True,
            page_count=page_count,
            request_count=page_count,
            blocker=None,
            portfolio_ids=frozenset(portfolio_ids),
        )
    
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
        _harden_sdk_transport(self._client, require_bounded_timeout=True)
        response = self._client.get_transaction_summary()
        return coinbase_sdk_response_to_dict(response)

    def get_spot_transaction_summary(self) -> Dict[str, Any]:
        """Read the Spot-only fee summary once for account-reality refresh."""

        _harden_sdk_transport(self._client, require_bounded_timeout=True)
        response = self._client.get_transaction_summary(product_type="SPOT")
        return coinbase_sdk_response_to_dict(response)

    def get_api_key_permissions(self) -> Dict[str, Any]:
        """Return the current credential's authoritative portfolio scope.

        Coinbase CDP keys select their portfolio through key permissions; the
        order-level ``retail_portfolio_id`` field is deprecated for those keys.
        Keep this read on the canonical REST wrapper so runtime admission does
        not create a second SDK client or infer scope from order payloads.
        """

        _harden_sdk_transport(self._client, require_bounded_timeout=True)
        response = self._client.get_api_key_permissions()
        data = coinbase_sdk_response_to_dict(response)
        return data if isinstance(data, dict) else {}
    
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

    def get_products_batch(self, product_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Read one exact product scope through one SDK request."""

        exact_scope = list(dict.fromkeys(str(item).strip() for item in product_ids))
        if not exact_scope or any(not product_id for product_id in exact_scope):
            raise ValueError("product_batch_scope_invalid")
        _harden_sdk_transport(self._client, require_bounded_timeout=True)
        response = coinbase_sdk_response_to_dict(
            self._client.get_products(product_ids=exact_scope)
        )
        if not isinstance(response, dict):
            raise ValueError("product_batch_response_invalid")
        rows = response.get("products")
        if not isinstance(rows, list):
            raise ValueError("product_batch_rows_invalid")
        products: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            data = _object_to_dict(row)
            product_id = str(data.get("product_id") or "").strip()
            if not product_id or product_id not in exact_scope:
                raise ValueError("product_batch_identity_invalid")
            if product_id in products:
                raise ValueError("product_batch_identity_duplicate")
            products[product_id] = data
        return products

    def get_best_bid_ask(self, *, product_ids: List[str]) -> Dict[str, Any]:
        """Return exact best-bid/ask evidence for the requested products."""

        _harden_sdk_transport(self._client, require_bounded_timeout=True)
        response = self._client.get_best_bid_ask(product_ids=product_ids)
        data = coinbase_sdk_response_to_dict(response)
        return data if isinstance(data, dict) else {}

    def preview_order(
        self,
        *,
        product_id: str,
        side: str,
        order_configuration: Dict[str, Any],
        leverage: Optional[str] = None,
        margin_type: Optional[str] = None,
    ) -> Any:
        """Call Coinbase Preview Order without creating an order.

        Optional values are omitted rather than serialized as null.  CDP key
        permissions bind the portfolio, so this canonical method deliberately
        has no ``retail_portfolio_id`` argument.
        """

        kwargs: Dict[str, Any] = {
            "product_id": product_id,
            "side": side,
            "order_configuration": order_configuration,
        }
        if leverage is not None:
            kwargs["leverage"] = leverage
        if margin_type is not None:
            kwargs["margin_type"] = margin_type
        _harden_sdk_transport(self._client, require_bounded_timeout=True)
        # The R11 Preview boundary must inspect the SDK's shallow raw envelope
        # before any recursive ``to_dict`` conversion.  Older producer
        # generations still normalize this return value themselves, so keeping
        # this one canonical method raw preserves their behavior while making
        # the ordering invariant enforceable for R11.
        return self._client.preview_order(**kwargs)
    
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

    def cancel_order(
        self,
        client_order_id: str,
        *,
        verified_exchange_order_id: str | None = None,
        return_evidence: bool = False,
    ) -> bool | Dict[str, Any]:
        """Cancel one operator-selected order through the canonical wrapper.

        The wrapper is intentionally called with client_order_id first because:
        - We always have it (we generate it for every order)
        - It is the operator-facing identity
        - Exchange-assigned order_id remains evidence, not the local identity

        Coinbase's batch-cancel boundary accepts exchange ``order_id`` values.
        A controlled-live caller that has already proved the exact exchange
        identity through authoritative readback can supply it here so this
        wrapper makes one exchange-id submission without changing the operator
        identity or adding a fallback attempt. Calls without that evidence keep
        the existing client-id behavior.

        Args:
            client_order_id: The client order ID we generated for this order
            verified_exchange_order_id: Exact exchange ID proved by the caller's
                authoritative order readback.
        
        Returns:
            True if cancel successful, False if order not found
        
        Raises:
            Exception: If API call fails
        
        Examples:
            >>> success = client.cancel_order('550e8400-e29b-41d4-a716-446655440000')
            >>> if success:
            ...     print("Order cancelled")
        """
        submitted_order_id = client_order_id
        if verified_exchange_order_id is not None:
            submitted_order_id = str(verified_exchange_order_id).strip()
            if not submitted_order_id:
                raise ValueError("verified_exchange_order_id cannot be empty")
        require_coinbase_execution_authority(
            expected_scope=COINBASE_EXECUTION_SCOPE_SPOT_CANCEL
        )
        result = self._client.cancel_orders([submitted_order_id])
        evidence = coinbase_cancel_response_evidence(
            result,
            expected_order_id=submitted_order_id,
        )
        if verified_exchange_order_id is not None:
            evidence = {
                **evidence,
                "operator_identity_key": "client_order_id",
                "operator_identity_value": client_order_id,
                "exchange_order_id_evidence_only": True,
                "exchange_order_id": submitted_order_id,
                "submitted_identity_key": "exchange_order_id",
            }
        return evidence if return_evidence else evidence["succeeded"] is True

    def cancel_order_by_exchange_order_id(
        self,
        order_id: str,
        *,
        return_evidence: bool = False,
    ) -> bool | Dict[str, Any]:
        """Historical/internal direct exchange-id cancellation helper."""

        require_coinbase_execution_authority(
            expected_scope=COINBASE_EXECUTION_SCOPE_SPOT_CANCEL
        )
        result = self._client.cancel_orders([order_id])
        evidence = coinbase_cancel_response_evidence(
            result,
            expected_order_id=order_id,
        )
        return evidence if return_evidence else evidence["succeeded"] is True
    
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
        if not isinstance(futures_response, dict):
            raise ValueError("futures positions evidence is not an object")
        if "positions" not in futures_response:
            raise ValueError("futures positions evidence is missing")
        futures_list = futures_response["positions"]
        if not isinstance(futures_list, list):
            raise ValueError("futures positions evidence is not a list")
        
        positions = {}
        for position_data in futures_list:
            if not isinstance(position_data, dict):
                raise ValueError("futures position row is invalid")
            product_id = position_data.get("product_id")
            if (
                not isinstance(product_id, str)
                or not product_id.strip()
                or product_id != product_id.strip()
            ):
                raise ValueError("futures position product_id is missing")
            if product_id in positions:
                raise ValueError(
                    f"duplicate futures position product_id: {product_id}"
                )
            side = position_data.get("side")
            if side not in {"LONG", "SHORT"}:
                raise ValueError("futures position side is invalid")
            if "number_of_contracts" not in position_data:
                raise ValueError("futures position contract count is missing")
            try:
                contract_count = Decimal(str(position_data["number_of_contracts"]))
            except (InvalidOperation, ValueError) as exc:
                raise ValueError("futures position contract count is invalid") from exc
            if not contract_count.is_finite() or contract_count < 0:
                raise ValueError("futures position contract count is invalid")
            position = Position.from_position_dict(position_data)
            positions[product_id] = position
        
        return positions

    def get_futures_margin_collateral_snapshot(self) -> Dict[str, Any]:
        """Read US Coinbase Futures CFM margin and collateral evidence.

        The US futures account uses the ``/cfm`` API family. It is separate from
        the INTX perps portfolio endpoints, which are not applicable to US
        accounts. This method performs only read calls and records per-item
        failures so the Admin API can expose exact blockers without crashing the
        whole wallet inventory read.

        Returns:
            Dictionary containing the CFM balance summary plus auxiliary margin
            setting, margin window, and sweep evidence.
        """

        return self._get_futures_margin_collateral_snapshot(
            include_futures_sweeps=True,
        )

    def get_futures_preview_eligibility_margin_collateral_snapshot(
        self,
    ) -> Dict[str, Any]:
        """Read only the four margin calls authorized for Preview eligibility."""

        return self._get_futures_margin_collateral_snapshot(
            include_futures_sweeps=False,
        )

    def _get_futures_margin_collateral_snapshot(
        self,
        *,
        include_futures_sweeps: bool,
    ) -> Dict[str, Any]:
        """Build the CFM snapshot with an explicit sweep-read boundary."""

        balance_summary, balance_error = _sdk_dict_or_error(
            self._client.get_futures_balance_summary
        )
        errors = []
        if balance_error is not None:
            errors.append(
                {
                    "method": "get_futures_balance_summary",
                    "error": balance_error,
                }
            )
        normalized_balance = _object_to_dict(balance_summary.get("balance_summary"))
        if not normalized_balance and balance_summary:
            normalized_balance = balance_summary

        intraday_margin_setting, intraday_error = _sdk_dict_or_error(
            self._client.get_intraday_margin_setting
        )
        if intraday_error is not None:
            errors.append(
                {
                    "method": "get_intraday_margin_setting",
                    "error": intraday_error,
                }
            )

        current_margin_windows = []
        for profile in (
            "MARGIN_PROFILE_TYPE_RETAIL_REGULAR",
            "MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1",
        ):
            margin_window, margin_window_error = _sdk_dict_or_error(
                self._client.get_current_margin_window,
                profile,
            )
            if margin_window_error is None:
                current_margin_windows.append(
                    {
                        "profile": profile,
                        "status": "ready",
                        **margin_window,
                    }
                )
                continue
            current_margin_windows.append(
                {
                    "profile": profile,
                    "status": "blocked",
                    "error": margin_window_error,
                }
            )
            errors.append(
                {
                    "method": "get_current_margin_window",
                    "profile": profile,
                    "error": margin_window_error,
                }
            )

        source_read_attempts = {
            "get_futures_balance_summary": 1,
            "get_intraday_margin_setting": 1,
            "get_current_margin_window": 2,
        }
        result = {
            "status": "ready" if normalized_balance and balance_error is None else "blocked",
            "account_family": "coinbase_futures_us_cfm",
            "source": "backend_rest_client",
            "source_read_attempts": source_read_attempts,
            "balance_summary": normalized_balance,
            "intraday_margin_setting": intraday_margin_setting,
            "current_margin_windows": current_margin_windows,
            "intx_applicability": "not_applicable_us_account",
            "errors": errors,
        }
        if include_futures_sweeps:
            futures_sweeps_response, futures_sweeps_error = _sdk_dict_or_error(
                self._client.list_futures_sweeps
            )
            source_read_attempts["list_futures_sweeps"] = 1
            if futures_sweeps_error is not None:
                errors.append(
                    {
                        "method": "list_futures_sweeps",
                        "error": futures_sweeps_error,
                    }
                )
            futures_sweeps = futures_sweeps_response.get("sweeps")
            if not isinstance(futures_sweeps, list):
                errors.append(
                    {
                        "method": "list_futures_sweeps",
                        "error": "futures_sweeps_missing_or_invalid",
                    }
                )
                futures_sweeps = []
            result["futures_sweeps"] = futures_sweeps
        return result
    
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
        _harden_sdk_transport(self._client, require_bounded_timeout=True)
        lister = getattr(self._client, "get_portfolios", None)
        if callable(lister):
            response = lister()
        else:
            response = self._client.list_portfolios()
        return coinbase_sdk_response_to_dict(response).get("portfolios", [])

    def get_futures_preview_eligibility_portfolios(
        self,
    ) -> List[Dict[str, Any]]:
        """Use the one pinned 1.8.4 portfolio-catalog SDK hook."""

        response = self._client.get_portfolios()
        data = coinbase_sdk_response_to_dict(response)
        portfolios = data.get("portfolios")
        if not isinstance(portfolios, list):
            raise ValueError("portfolio catalog evidence is not a list")
        return portfolios
    
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
    
    def list_orders(
        self,
        order_status: Optional[List[str]] = None,
        *,
        order_ids: Optional[List[str]] = None,
        product_ids: Optional[List[str]] = None,
        limit: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        cursor: Optional[str] = None,
        product_type: Optional[str] = None,
        retail_portfolio_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List orders with exact identity, scope, and pagination filters.
        
        Args:
            order_status: List of order statuses to filter (e.g., ['OPEN', 'FILLED']).
            order_ids: Optional exchange-assigned order ids for exact readback.
            product_ids: Optional product scope.
            limit: Optional Coinbase page size.
            start_date: Optional inclusive UTC order-history window start.
            end_date: Optional UTC order-history window end.
            cursor: Optional Coinbase pagination cursor.
            product_type: Optional Coinbase product-type scope.
            retail_portfolio_id: Optional exact Coinbase profile scope.
        
        Returns:
            Raw SDK response object (call .to_dict() to get dict)
        
        Raises:
            Exception: If API call fails
        """
        _harden_sdk_transport(self._client, require_bounded_timeout=True)
        return self._client.list_orders(
            order_status=order_status,
            order_ids=order_ids,
            product_ids=product_ids,
            limit=limit,
            start_date=start_date,
            end_date=end_date,
            cursor=cursor,
            product_type=product_type,
            retail_portfolio_id=retail_portfolio_id,
        )

    def get_order(self, order_id: str) -> Dict[str, Any]:
        """Get one order by its exchange-assigned order id."""

        response = self._client.get_order(order_id)
        data = coinbase_sdk_response_to_dict(response)
        return data if isinstance(data, dict) else {}

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
        require_coinbase_execution_authority(
            expected_scope=COINBASE_EXECUTION_SCOPE_SPOT_CANCEL
        )
        return self._client.cancel_orders(order_ids)

    def close_position(
        self,
        client_order_id: str,
        product_id: str,
        size: Optional[str] = None,
        **kwargs
    ):
        """Close or reduce a Futures position by product ID.

        Args:
            client_order_id: Custom order ID for idempotency
            product_id: Futures product identifier
            size: Optional number of contracts to close or reduce
            **kwargs: Additional parameters passed to the SDK

        Returns:
            Raw SDK close-position response

        Raises:
            Exception: If API call fails
        """
        params = {
            "client_order_id": client_order_id,
            "product_id": product_id,
        }
        if size is not None:
            params["size"] = size
        params.update(kwargs)
        require_coinbase_execution_authority(
            expected_scope="source_disabled_futures_close"
        )
        return self._client.close_position(**params)
    
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
        require_coinbase_execution_authority(
            expected_scope="source_disabled_legacy_limit_order"
        )
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

        require_coinbase_execution_authority(
            expected_scope=COINBASE_EXECUTION_SCOPE_SPOT_PLACE
        )
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


def _object_to_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        converted = converter()
        return dict(converted) if isinstance(converted, dict) else {}
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _sdk_dict_or_error(method: Any, *args: Any) -> tuple[Dict[str, Any], str | None]:
    try:
        return _object_to_dict(method(*args)), None
    except Exception as exc:
        return {}, _safe_exception_label(exc)


def _safe_exception_label(exc: Exception) -> str:
    text = str(exc)
    upper = text.upper()
    for token in (
        "PERMISSION_DENIED",
        "UNAUTHORIZED",
        "FORBIDDEN",
        "INVALID_ARGUMENT",
        "NOT_FOUND",
        "ACCOUNT_RESTRICTED",
    ):
        if token in upper:
            return f"{type(exc).__name__}:{token}"
    if "403" in text:
        return f"{type(exc).__name__}:HTTP_403"
    if "401" in text:
        return f"{type(exc).__name__}:HTTP_401"
    if "404" in text:
        return f"{type(exc).__name__}:HTTP_404"
    return type(exc).__name__


def _accounts_from_response(response: Any) -> List[Any]:
    response_data = _object_to_dict(response)
    accounts = response_data.get("accounts")
    if isinstance(accounts, list):
        return accounts
    if isinstance(response, dict) and isinstance(response.get("accounts"), list):
        return response["accounts"]
    return []


def _all_accounts_from_client(client: Any) -> List[Any]:
    accounts: List[Any] = []
    cursor: Optional[str] = None
    while True:
        kwargs: Dict[str, Any] = {"limit": ACCOUNT_PAGE_LIMIT}
        if cursor:
            kwargs["cursor"] = cursor
        response = client.get_accounts(**kwargs)
        response_data = _object_to_dict(response)
        accounts.extend(_accounts_from_response(response))
        if not bool(response_data.get("has_next")):
            return accounts
        next_cursor = response_data.get("cursor")
        if not next_cursor:
            return accounts
        cursor = str(next_cursor)
