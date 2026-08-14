"""Configuration module for Coinbase Advanced API trading.

This module provides:
- REST API client initialization with authentication
- Configuration dictionaries for order mapping and handling
- Utility functions for type conversion and order computation
- Product metadata fetching and caching
- Position tracking for futures contracts

Example:
    >>> from configuration import rest_get_products, rest_get_account_wallets
    >>> products = rest_get_products()
    >>> wallets = rest_get_account_wallets()
    >>> product_data = products.get('BTC-USDC', {})
"""

from os import getenv
from copy import deepcopy
import json
import logging
from pathlib import Path
from typing import Any, Optional, Union, overload
from coinbase.rest import RESTClient

from external import CoinbaseRestClient
from core.enums import OrderStatus, OrderSide, ProductType, RoundingDirection, TargetMovementType
from core.exceptions import CoinbaseAPIError
from core.constants import (  # noqa: F401  (re-exported for legacy ``from configuration import ...``)
    DERIVATIVES_PER_SIDE_FEE_DEFAULT,
    get_derivatives_per_side_fee,
    DEFAULT_MAX_ORDER_REPLACEMENT,
)

logger = logging.getLogger(__name__)

# Load products from products.json
PRODUCTS_FILE = Path(__file__).parent / "products.json"
try:
    with open(PRODUCTS_FILE, 'r') as f:
        _products_config = json.load(f)
        DERIVATIVES_PRODUCT_IDS = _products_config.get("derivatives", [])
        SPOT_PRODUCT_IDS = _products_config.get("spot", [])
        PRODUCT_METADATA = _products_config.get("metadata", {})
        TICKER_TO_TRADING = _products_config.get("ticker_to_trading", {})
except (FileNotFoundError, json.JSONDecodeError) as e:
    print(f"Warning: Failed to load products.json: {e}")
    # Fallback to hardcoded values
    DERIVATIVES_PRODUCT_IDS = []
    SPOT_PRODUCT_IDS = []
    PRODUCT_METADATA = {}
    TICKER_TO_TRADING = {}

def get_trading_product_id(ticker_product_id: str) -> str:
    """
    Convert a ticker product ID to its trading equivalent.
    
    Example:
        get_trading_product_id("BTC-USD") -> "BTC-USDC"
        get_trading_product_id("BTC-USDC") -> "BTC-USDC"  # Already a trading product
    
    Args:
        ticker_product_id: Product ID from ticker feed
        
    Returns:
        Trading product ID to use for order placement
    """
    # If it's in the mapping, use the mapped value
    if ticker_product_id in TICKER_TO_TRADING:
        return TICKER_TO_TRADING[ticker_product_id]
    # Otherwise assume it's already a trading product
    return ticker_product_id


def _local_product_dict(product_id: str, metadata: dict) -> dict:
    """Normalize cached ``products.json`` metadata to the REST product shape."""
    product_type = (
        metadata.get("product_type")
        or metadata.get("type")
        or ProductType.SPOT.value
    )
    product = {
        **metadata,
        "product_id": product_id,
        "product_type": product_type,
        "trading_disabled": bool(metadata.get("trading_disabled", False)),
    }
    if product_type == ProductType.FUTURE.value:
        product.setdefault(
            "future_product_details",
            {"contract_size": metadata.get("contract_size") or 1},
        )
    return product


def local_products_from_metadata() -> dict:
    """Return the last locally cached product catalog without network access."""
    products = {}
    for product_id in DERIVATIVES_PRODUCT_IDS + SPOT_PRODUCT_IDS:
        metadata = PRODUCT_METADATA.get(product_id) or PRODUCT_METADATA.get(
            get_trading_product_id(product_id),
            {},
        )
        products[product_id] = _local_product_dict(product_id, dict(metadata))
    return {
        product_id: product
        for product_id, product in products.items()
        if product.get("trading_disabled") is False
    }

API_KEY = getenv("COINBASE_API_KEY")
API_SECRET = getenv("COINBASE_API_SECRET")

_sdk_client = RESTClient(
    api_key=API_KEY,
    api_secret=API_SECRET,
    rate_limit_headers=True)
REST_CLIENT = CoinbaseRestClient(_sdk_client)

ORDER_SIDE_SWITCH = {
    "BUY": "SELL",
    "SELL": "BUY"
}

ORDER_POST_ONLY = {
    "BUY": False,
    "SELL": False
}

ORDER_POSITION_SIDE = {
    "SHORT": "SELL",
    "LONG": "BUY",
    "SELL": "SHORT",
    "BUY": "LONG"
}

ORDER_DIRECTION = {
    "SELL": 1,
    "BUY": -1
}

# DERIVATIVES_PER_SIDE_FEE_* and DEFAULT_MAX_ORDER_REPLACEMENT
# are imported above from ``core.constants`` (canonical source of truth).
# Do NOT redefine them here â€” see 2026-04-30 audit.


# ``safe_float`` returns ``None`` when callers explicitly pass ``default=None`` â€”
# this is exercised in the engine's market-data resolution paths (bid/ask may
# be missing). Express both shapes as overloads so Pylance's strict mode sees
# the precise return type at each call site instead of a polymorphic
# ``Optional[float]`` everywhere.


@overload
def safe_float(value: Any) -> float: ...
@overload
def safe_float(value: Any, default: float) -> float: ...
@overload
def safe_float(value: Any, default: None) -> Optional[float]: ...
def safe_float(
    value: Any, default: Union[float, None] = 0.0
) -> Optional[float]:
    """Safely convert a value to float, returning ``default`` on error.

    Handles ``None``, empty strings, and invalid types gracefully. Useful for
    converting API responses where numeric fields may be missing or invalid.

    Args:
        value: The value to convert (any type).
        default: The default value to return if conversion fails (default: 0.0).
            Pass ``None`` explicitly to opt into ``Optional[float]`` returns
            (used by the engine when a missing bid/ask should propagate as
            ``None`` rather than ``0.0``).

    Returns:
        The converted float value, or ``default`` if conversion fails. The
        return type matches the type of ``default``: pass a ``float`` to get
        a guaranteed ``float`` back, or pass ``None`` to allow ``None``.

    Examples:
        >>> safe_float('123.45')
        123.45
        >>> safe_float(None)
        0.0
        >>> safe_float('')
        0.0
        >>> safe_float('invalid')
        0.0
        >>> safe_float('99.99', default=1.0)
        99.99
        >>> safe_float('invalid', default=1.0)
        1.0
        >>> safe_float(None, default=None) is None
        True
    """
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_product_type(order: dict, products: dict = None) -> str:
    """Normalize product type from an order payload and configured products.
    
    Determines if an order is for SPOT or FUTURE trading by checking multiple
    sources: order payload, product metadata, and product ID suffix patterns.
    Uses fallback logic to handle incomplete order data.
    
    Args:
        order: Order dictionary with optional 'product_type', 'product_id' fields.
        products: Optional product metadata dict keyed by product_id.
    
    Returns:
        'SPOT' or 'FUTURE' - the normalized product type.
    
    Examples:
        >>> order = {'product_type': 'SPOT', 'product_id': 'BTC-USDC'}
        >>> normalize_product_type(order)
        'SPOT'
        >>> order = {'product_id': 'BIP-20DEC30-CDE'}
        >>> normalize_product_type(order)
        'FUTURE'
        >>> order = {'product_id': 'BTC-USDC'}
        >>> normalize_product_type(order)
        'SPOT'
    """
    product_type = str(order.get("product_type") or "").upper()
    if product_type in {ProductType.SPOT.value, ProductType.FUTURE.value}:
        return product_type

    product_id = order.get("product_id")
    product = (products or {}).get(product_id, {})
    configured_product_type = str(product.get("product_type") or "").upper()
    if configured_product_type in {ProductType.SPOT.value, ProductType.FUTURE.value}:
        return configured_product_type

    if product_id and product_id.endswith("-CDE"):
        return "FUTURE"
    return "SPOT"


def resolve_order_size(order: dict) -> float:
    """Resolve order size from the best available quantity field.
    
    Attempts to extract order size from multiple possible fields in priority order.
    Different API responses and order states use different field names. Returns 0.0
    if no valid size field is found.
    
    Args:
        order: Order dictionary that may contain size in various fields.
    
    Returns:
        The order size as a float, or 0.0 if not found.
    
    Examples:
        >>> order = {'leaves_quantity': 10.5}
        >>> resolve_order_size(order)
        10.5
        >>> order = {'cumulative_quantity': 5.0}
        >>> resolve_order_size(order)
        5.0
        >>> order = {'base_size': 2.5}
        >>> resolve_order_size(order)
        2.5
        >>> order = {}
        >>> resolve_order_size(order)
        0.0
    """
    leaves_quantity = safe_float(order.get("leaves_quantity"), default=0.0)
    cumulative_quantity = safe_float(order.get("cumulative_quantity"), default=0.0)
    if leaves_quantity > 0:
        return leaves_quantity
    if cumulative_quantity > 0:
        return cumulative_quantity
    for field in ("filled_size", "base_size", "size"):
        value = safe_float(order.get(field), default=0.0)
        if value > 0:
            return value
    return 0.0


def resolve_profit_move_pct(order: dict, profits: dict, products: dict) -> float:
    """Resolve configured profit target for an order.
    
    Determines the profit/fee movement percentage for an order by checking
    product-specific and product-type-level configurations. Falls back to
    product type (SPOT/FUTURE) if product-specific settings not available.
    
    Args:
        order: Order dict with 'product_id' and 'order_side' fields.
        profits: Profit config dict with structure:
                 {product_type: {side: percentage}, product_id: {side: percentage}}
        products: Product metadata dict keyed by product_id.
    
    Returns:
        The profit movement percentage as float (e.g., 0.002 for 0.2%).
    
    Examples:
        >>> order = {'product_id': 'BTC-USDC', 'order_side': 'BUY'}
        >>> profits = {'SPOT': {'BUY': 0.004, 'SELL': 0.004}}
        >>> products = {'BTC-USDC': {'product_type': 'SPOT'}}
        >>> resolve_profit_move_pct(order, profits, products)
        0.004
        >>> order = {'product_id': 'BIP-20DEC30-CDE', 'order_side': 'SELL'}
        >>> profits = {'FUTURE': {'SELL': 0.002}, 'BIP-20DEC30-CDE': {'SELL': 0.028}}
        >>> resolve_profit_move_pct(order, profits, products)
        0.028
    """
    product_id = order.get("product_id")
    product_type = normalize_product_type(order, products=products)
    order_side = order.get("order_side")

    product_profit = profits.get(product_id)
    if isinstance(product_profit, dict) and order_side in product_profit:
        return product_profit[order_side]

    type_profit = profits.get(product_type, {})
    return type_profit[order_side]


def format_based_on_reference(value_to_format: float, reference_float: str) -> str:
    """Format a float to match the number of decimal places of a reference float.
    
    Extracts the number of decimal places from a reference string and formats
    the input value to match. Useful for matching price/size precision to
    exchange-specific increments.

    Args:
        value_to_format: The numeric value to format (float or convertible).
        reference_float: A reference string (e.g., '0.01', '1') representing target precision.

    Returns:
        A formatted string representation with matching decimal places.
    
    Examples:
        >>> format_based_on_reference(123.456, '0.01')
        '123.46'
        >>> format_based_on_reference(123.456, '0.001')
        '123.456'
        >>> format_based_on_reference(123.456, '1')
        '123'
        >>> format_based_on_reference(10.5, '0.0001')
        '10.5000'
    """
    result = f"{value_to_format:.{len(str(reference_float).rsplit('.', maxsplit=1)[-1]) if '.' in str(reference_float) else 0}f}"
    return result


# Single canonical implementation lives in calculation.formatter.
# Re-exported here for back-compat with callers doing
# ``from configuration import quantize_to_increment``. P2 #1: DRY.
from calculation.formatter import quantize_to_increment  # noqa: E402,F401

def rest_get_account_wallets() -> dict:
    """Retrieve all active account wallets from Coinbase REST API.

    Fetches account information for all currencies with active wallets.
    Filters out deleted accounts. Performs a single REST API call.
    
    Returns:
        A dictionary mapping currency codes (e.g., 'BTC', 'USDC') to wallet data.
        Structure: {'BTC': {...wallet_data...}, 'USDC': {...}, ...}
    
    Raises:
        APIError: If REST API call fails (authentication, network, etc.).
    
    Examples:
        >>> wallets = rest_get_account_wallets()
        >>> btc_wallet = wallets.get('BTC')
        >>> if btc_wallet:
        ...     print(f"BTC balance: {btc_wallet['available_balance']}")
        >>> all_currencies = list(wallets.keys())
    """
    accounts_list = REST_CLIENT.get_accounts()["accounts"]

    account_wallets = {
        item["currency"]: item for item in accounts_list if item["deleted_at"] is None
    }

    return account_wallets

def rest_get_products() -> dict:
    """Retrieve all trading products from Coinbase REST API.

    Fetches product information for all configured derivatives (futures) and
    spot products. Filters out any trading-disabled products. Useful for
    extracting price/size increments, min/max order sizes, etc.

    Returns:
        A dictionary mapping product IDs (e.g., 'BTC-USDC') to product data.
        Each product dict contains fields like: product_id, base_increment,
        quote_increment, price_increment, product_type, etc.
    
    Raises:
        APIError: If any REST API call fails.
    
    Examples:
        >>> products = rest_get_products()
        >>> btc_usdc = products.get('BTC-USDC')
        >>> price_increment = btc_usdc['price_increment']
        >>> base_increment = btc_usdc['base_increment']
        >>> print(f"Can trade {base_increment} BTC increments")
    """
    products = {}
    for requested_product_id in DERIVATIVES_PRODUCT_IDS + SPOT_PRODUCT_IDS:
        item = REST_CLIENT.get_product_dict(requested_product_id)
        if not isinstance(item, dict):
            raise CoinbaseAPIError(
                "Coinbase returned a malformed product response",
                api_error_code="malformed_product_response",
            )

        product_id = item.get("product_id")
        if not product_id:
            raise CoinbaseAPIError(
                "Coinbase product response omitted product_id",
                api_error_code="malformed_product_response",
            )

        if item.get("trading_disabled") is False:
            products[product_id] = item

    return products

def get_futures_positions() -> dict:
    """Retrieve all open futures positions from Coinbase REST API.

    Fetches current perpetual and expiring futures positions. Returns empty
    dict if no open positions. Used to initialize and update position tracking.

    Returns:
        A dictionary mapping product IDs (e.g., 'BIP-20DEC30-CDE') to position data.
        Structure: {'product_id': {position_data...}, ...}
        Returns {} if no positions exist.
    
    Raises:
        APIError: If REST API call fails.
    
    Examples:
        >>> positions = get_futures_positions()
        >>> if 'BIP-20DEC30-CDE' in positions:
        ...     pos = positions['BIP-20DEC30-CDE']
        ...     print(f"Contracts: {pos['number_of_contracts']}")
    """
    futures_list = REST_CLIENT.list_futures_positions().to_dict()["positions"]

    if futures_list:
        positions = {
            position["product_id"]: position for position in futures_list
        }
    else:
        positions = {}

    return positions

def get_open_orders() -> dict:
    """Retrieve all open orders from Coinbase REST API.

    Fetches orders with OPEN status. Returns empty dict if no open orders.
    Maps results by client_order_id for fast lookup in order tracking.

    Returns:
        A dictionary mapping client_order_id to order data dictionaries.
        Structure: {'client_order_id': {order_data...}, ...}
    
    Raises:
        APIError: If REST API call fails.
    
    Examples:
        >>> open_orders = get_open_orders()
        >>> for client_id, order_data in open_orders.items():
        ...     print(f"Order {client_id}: {order_data['product_id']} {order_data['side']}")
    """
    orders_list = REST_CLIENT.list_orders(order_status=["OPEN"]).to_dict()["orders"]

    orders = {
        order["client_order_id"]: order for order in orders_list
    }

    return orders


def apply_calculated_position_update(positions: dict, position_update: dict) -> dict:
    """Apply a position update returned by calculate_new_order_move_from_snapshot.

    Updates or creates position entries in the positions dictionary with new values.
    Mutates the positions dict and returns it for convenience.

    Args:
        positions: The positions dictionary to update (e.g., {'FUTURE': {...}}).
        position_update: Dict with 'product_type', 'product_id', and 'fields' keys.
                         Example: {'product_type': 'FUTURE', 'product_id': 'BIP-20DEC30-CDE',
                                   'fields': {'side': 'LONG', 'number_of_contracts': '100'}}

    Returns:
        The updated positions dictionary (same object as input).
    
    Examples:
        >>> positions = {'FUTURE': {'BIP-20DEC30-CDE': {'side': 'LONG', 'number_of_contracts': '50'}}}
        >>> update = {'product_type': 'FUTURE', 'product_id': 'BIP-20DEC30-CDE',
        ...           'fields': {'side': 'SHORT', 'number_of_contracts': '100'}}
        >>> positions = apply_calculated_position_update(positions, update)
        >>> positions['FUTURE']['BIP-20DEC30-CDE']['side']
        'SHORT'
    """
    if not position_update:
        return positions

    product_type = position_update["product_type"]
    product_id = position_update["product_id"]

    if product_type not in positions:
        positions[product_type] = {}
    if product_id not in positions[product_type]:
        positions[product_type][product_id] = {}

    positions[product_type][product_id].update(position_update["fields"])
    return positions


def calculate_new_order_move_from_snapshot(snapshot: dict, order_id: str, target_movement: dict = None) -> dict:
    """Calculate the template for a follow-up order based on a caller-provided snapshot.

    Computes pricing, sizing, and position updates for the next order in a trading strategy
    without making REST calls or mutating the input snapshot. Core calculation logic for
    automated follow-up order creation after fills/cancellations.

    Args:
        snapshot: A snapshot dict with keys:
                  - 'order': {client_order_id: order_data, ...}
                  - 'positions': {'FUTURE': {product_id: position_data, ...}}
                  - 'product': {product_id: product_data, ...}
                  - 'profit': {product_type/id: {side: percentage, ...}}
                  - 'mandatory_fee_per_contract': {product_id: {...}}
        order_id: The client order ID to compute next move for.
        target_movement: Optional override dict with 'type' ("P"/"A") and 'movement' (value).
                         Type "P" = percentage, "A" = absolute amount.

    Returns:
        A dictionary with keys:
        - 'current_contract_count': Position size for futures (or "N/A" for spot)
        - 'mandatory_fee': Fee amount for futures contracts
        - 'profit_move_pct': Computed profit movement percentage
        - 'fee_move_calculated_from_pct': Fee from percentage calculation
        - 'minimum_move_amount': Minimum price move
        - 'product_id': The product ID
        - 'side': Order side (BUY/SELL)
        - 'order_base_size': New order size (formatted string)
        - 'order_price_difference': Price difference from original (formatted string)
        - 'start_price': New order price (formatted string)
        - 'position_update': Optional position update dict (None if no change)
        Returns {} if order_id not found or insufficient data.
    
    Examples:
        >>> snapshot = {
        ...     'order': {'order123': {'product_id': 'BTC-USDC', 'status': 'FILLED',
        ...                            'order_side': 'BUY', 'limit_price': '40000.00'}},
        ...     'positions': {'FUTURE': {}},
        ...     'product': {'BTC-USDC': {'base_increment': '0.001', 'price_increment': '1',
        ...                              'quote_increment': '0.01'}},
        ...     'profit': {'SPOT': {'BUY': 0.004, 'SELL': 0.004}},
        ...     'mandatory_fee_per_contract': {}
        ... }
        >>> result = calculate_new_order_move_from_snapshot(snapshot, 'order123')
        >>> print(result['product_id'], result['side'], result['start_price'])
    """
    orders = snapshot.get("order", {})
    positions = deepcopy(snapshot.get("positions", {}))
    products = snapshot.get("product", {})
    profits = snapshot.get("profit", {})
    mandatory_fees = snapshot.get("mandatory_fee_per_contract", {})

    order = orders.get(order_id)
    if not order:
        return {}

    order_product_id = order["product_id"]
    order_product_type = normalize_product_type(order, products=products)
    order_status = order["status"]
    order_side = order["order_side"]
    order_size = resolve_order_size(order)

    mandatory_fee = safe_float(
        mandatory_fees.get(order_product_id, {}).get("mandatory_fee_per_contract"),
        default=0.0,
    )
    base_increment = products[order_product_id]["base_increment"]
    quote_increment = products[order_product_id]["quote_increment"]
    price_increment = products[order_product_id]["price_increment"]
    minimum_move_amount = float(price_increment)
    profit_move_pct = resolve_profit_move_pct(order, profits, products)

    if order_status == OrderStatus.FILLED.value:
        order_side = ORDER_SIDE_SWITCH[order_side]

    if order_status == OrderStatus.CANCELLED.value:
        order_size = safe_float(order.get("leaves_quantity"), default=0.0)

    if safe_float(order.get("limit_price"), default=0.0) > 0:
        order_float_price = safe_float(order.get("limit_price"), default=0.0)
    elif safe_float(order.get("avg_price"), default=0.0) > 0:
        order_float_price = safe_float(order.get("avg_price"), default=0.0)
    else:
        return {}

    if target_movement is not None:
        if target_movement.get("type") == TargetMovementType.PERCENTAGE.value:
            profit_move_pct = target_movement["movement"]
        elif target_movement.get("type") == TargetMovementType.ABSOLUTE.value:
            minimum_move_amount = float(target_movement["movement"])

    fee_move_calculated_from_pct = order_float_price * profit_move_pct
    order_move_amount = fee_move_calculated_from_pct if minimum_move_amount < fee_move_calculated_from_pct else minimum_move_amount
    order_move_difference = order_move_amount * ORDER_DIRECTION[order_side]

    position_update = None

    if order_product_type == ProductType.FUTURE.value:
        product_positions = positions.get(order_product_type, {})
        position = deepcopy(product_positions.get(order_product_id))

        if order_status == OrderStatus.FILLED.value and position:
            number_of_contracts = float(position["number_of_contracts"])

            if ORDER_POSITION_SIDE[position["side"]] == order_side:
                number_of_contracts -= order_size
                mandatory_fee *= ORDER_DIRECTION[order_side]

                if number_of_contracts < 0:
                    number_of_contracts = abs(number_of_contracts)
                    position["side"] = ORDER_POSITION_SIDE[ORDER_SIDE_SWITCH[order_side]]
            else:
                number_of_contracts += order_size
                mandatory_fee *= ORDER_DIRECTION[order_side]

            position["number_of_contracts"] = str(number_of_contracts)
            position_update = {
                "product_type": order_product_type,
                "product_id": order_product_id,
                "fields": {
                    "side": position["side"],
                    "number_of_contracts": position["number_of_contracts"],
                },
            }
            product_positions[order_product_id] = position
            positions[order_product_type] = product_positions

    order_new_price = order_float_price + order_move_difference + mandatory_fee
    order_new_price = float(format_based_on_reference(order_new_price, quote_increment))
    order_new_size = float(format_based_on_reference(order_size, base_increment))

    round_direction = RoundingDirection.UP.value if order_side == OrderSide.SELL.value else RoundingDirection.DOWN.value
    order_new_price = quantize_to_increment(
        order_new_price,
        price_increment,
        direction=round_direction,
    )

    price_increment_len = len(price_increment) - 2 if len(price_increment) > 3 else 1
    base_increment_len = len(base_increment) - 2 if len(base_increment) > 3 else 1

    current_contract_count = "N/A"
    if order_product_type == ProductType.FUTURE.value:
        updated_position = positions.get(order_product_type, {}).get(order_product_id)
        if updated_position:
            current_contract_count = updated_position.get("number_of_contracts", "N/A")

    return {
        "current_contract_count": current_contract_count,
        "mandatory_fee": mandatory_fee,
        "profit_move_pct": profit_move_pct,
        "fee_move_calculated_from_pct": fee_move_calculated_from_pct,
        "minimum_move_amount": minimum_move_amount,
        "product_id": order_product_id,
        "side": order_side,
        "order_base_size": f"{order_new_size:.{base_increment_len}f}",
        "order_price_difference": f"{abs(order_move_difference):.{price_increment_len}f}",
        "start_price": f"{order_new_price:.{price_increment_len}f}",
        "position_update": position_update,
    }


def determine_open_close_sides(product_type: str, position_side: str = None, parent_order_side: str = None, 
                                position_size: float = None, order_size: float = None) -> tuple:
    """Determine which order side is 'open' and which is 'close' based on product type and position.
    
    For SPOT products: All BUY orders are OPEN, all SELL orders are CLOSE (always).
    
    For FUTURE/PERPETUAL products: Depends on account position:
    - If position is LONG: BUY=open (add), SELL=close (reduce)
    - If position is SHORT: SELL=open (add), BUY=close (reduce)
    - If position is None/closed: Use parent_order_side to determine:
      * If parent was BUY: BUY=open (new position opening), SELL=close (future)
      * If parent was SELL: SELL=open (new position opening), BUY=close (future)
      * If parent_order_side not provided: Default to BUY=open, SELL=close
    - POSITION FLIP (order_size > position_size): Partial close + partial open
      * First portion closes existing position (opposite order closes position)
      * Remaining portion opens new position in opposite direction
      * Fee applies only to closing portion
    
    CRITICAL: When account position reaches 0 contracts, the next order opens a new position.
    Position resets when balance â†’ 0, so the direction of that next order determines whether
    it's opening LONG or SHORT.
    
    POSITION FLIP SCENARIO:
    - Current: LONG 5 contracts
    - Order: SELL 10 contracts
    - Interpretation: 5 SELL to close LONG + 5 SELL to open SHORT
    - New position: SHORT 5
    
    Args:
        product_type: 'SPOT', 'FUTURE', or 'PERPETUAL'
        position_side: Current position ('LONG', 'SHORT', or None if closed)
        parent_order_side: The side of the parent/opening order ('BUY' or 'SELL') for context
        position_size: Current position size (contracts) - for flip detection
        order_size: New order size (contracts) - for flip detection
    
    Returns:
        Tuple of (open_side, close_side) where each is 'BUY' or 'SELL'
        Example: ('BUY', 'SELL') or ('SELL', 'BUY')
        
    Important for Flips:
        When flip is detected, the open_side/close_side still represents the IMMEDIATE
        behavior of this order. For LONG 5 + SELL 10:
        - First 5 SELL close LONG (use current logic)
        - Next 5 SELL open SHORT (determined by position_side that will result)
        This function returns close_side for the closing portion.
    
    Examples:
        >>> # SPOT: always same regardless of position
        >>> determine_open_close_sides('SPOT')
        ('BUY', 'SELL')
        
        >>> # FUTURE LONG: BUY opens, SELL closes
        >>> determine_open_close_sides('FUTURE', position_side='LONG')
        ('BUY', 'SELL')
        
        >>> # FUTURE SHORT: SELL opens, BUY closes
        >>> determine_open_close_sides('FUTURE', position_side='SHORT')
        ('SELL', 'BUY')
        
        >>> # Position flip: LONG 5 + SELL 10 â†’ SHORT 5
        >>> determine_open_close_sides('FUTURE', position_side='LONG', 
        ...                              parent_order_side='SELL', 
        ...                              position_size=5.0, order_size=10.0)
        ('BUY', 'SELL')  # SELL closes LONG portion (fee applies here)
        
        >>> # After flip completes, position is SHORT
        >>> determine_open_close_sides('FUTURE', position_side='SHORT')
        ('SELL', 'BUY')  # SELL opens, BUY closes SHORT
    """
    # SPOT products always use BUY=open, SELL=close
    if product_type == ProductType.SPOT.value:
        return ('BUY', 'SELL')
    
    # FUTURE/PERPETUAL: Check if position exists
    if position_side == 'SHORT':
        return ('SELL', 'BUY')
    elif position_side == 'LONG':
        return ('BUY', 'SELL')
    
    # Position is None/closed (position_side is None)
    # The parent order determines the new opening direction
    if parent_order_side == 'SELL':
        # Parent was SELL (opening SHORT), so SELL=open, BUY=close
        return ('SELL', 'BUY')
    
    # Default: BUY=open, SELL=close
    # Covers parent_order_side='BUY' or unknown/None cases
    return ('BUY', 'SELL')


def detect_position_flip(position_side: str, position_size: float, order_side: str, order_size: float) -> dict:
    """Detect if an order will cause a position to flip direction.
    
    When order size exceeds current position size and opposes it, the position flips.
    This has implications for profit calculation:
    - Portion that closes: Fee applies, profit/loss realized
    - Portion that opens: No fee yet, future profit depends on follow-up
    
    Args:
        position_side: Current position ('LONG', 'SHORT', or None)
        position_size: Current position size in contracts (e.g., 5.0)
        order_side: New order side ('BUY' or 'SELL')
        order_size: New order size in contracts (e.g., 10.0)
    
    Returns:
        Dict with keys:
            'will_flip': bool - True if position flips after this order
            'closing_size': float - Size that closes existing position
            'opening_size': float - Size that opens new position
            'new_position_side': str - Side after order ('LONG', 'SHORT', or None)
            'new_position_size': float - Size after order
    
    Examples:
        >>> # LONG 5 + SELL 10 â†’ SHORT 5
        >>> detect_position_flip('LONG', 5.0, 'SELL', 10.0)
        {
            'will_flip': True,
            'closing_size': 5.0,  # 5 SELL to close LONG
            'opening_size': 5.0,  # 5 SELL to open SHORT
            'new_position_side': 'SHORT',
            'new_position_size': 5.0
        }
        
        >>> # LONG 5 + SELL 3 (no flip, just reduce)
        >>> detect_position_flip('LONG', 5.0, 'SELL', 3.0)
        {
            'will_flip': False,
            'closing_size': 3.0,
            'opening_size': 0.0,
            'new_position_side': 'LONG',
            'new_position_size': 2.0
        }
        
        >>> # LONG 5 + SELL 5 (closes completely)
        >>> detect_position_flip('LONG', 5.0, 'SELL', 5.0)
        {
            'will_flip': False,
            'closing_size': 5.0,
            'opening_size': 0.0,
            'new_position_side': None,
            'new_position_size': 0.0
        }
    """
    if position_side is None or position_size == 0:
        # No position to flip from
        return {
            'will_flip': False,
            'closing_size': 0.0,
            'opening_size': order_size,
            'new_position_side': 'LONG' if order_side == 'BUY' else 'SHORT',
            'new_position_size': order_size
        }
    
    # Determine if order opposes current position
    order_opposes = (
        (position_side == 'LONG' and order_side == 'SELL') or
        (position_side == 'SHORT' and order_side == 'BUY')
    )
    
    if not order_opposes:
        # Order increases position, no flip possible
        return {
            'will_flip': False,
            'closing_size': 0.0,
            'opening_size': order_size,
            'new_position_side': position_side,
            'new_position_size': position_size + order_size
        }
    
    # Order opposes position - check if it flips
    if order_size > position_size:
        # FLIP: portion closes, portion opens opposite
        closing_size = position_size
        opening_size = order_size - position_size
        new_side = 'SHORT' if position_side == 'LONG' else 'LONG'
        return {
            'will_flip': True,
            'closing_size': closing_size,
            'opening_size': opening_size,
            'new_position_side': new_side,
            'new_position_size': opening_size
        }
    else:
        # No flip: just reduces position
        new_size = position_size - order_size
        return {
            'will_flip': False,
            'closing_size': order_size,
            'opening_size': 0.0,
            'new_position_side': position_side if new_size > 0 else None,
            'new_position_size': new_size
        }


class OrderBook():
    """Compatibility shim wrapping :class:`core.orderbook.OrderBook` (v2).

    Phase 2 of the OrderBook refactor (see
    ``genai_tools/ORDERBOOK_REFACTOR_ROADMAP.md``).  The real state lives in a
    :class:`core.orderbook.OrderBook` instance held in ``self._impl``; this
    class exposes the legacy attribute surface (``order``, ``parent_order_ids``,
    ``child_order_ids``, ``positions``, ``product``, ``profit``, etc.) as
    properties that return the *live* underlying dicts so existing consumers
    that do ``ob.order[coid] = x`` continue to mutate state.

    Behavioural goals:

    * Byte-for-byte legacy semantics for every documented attribute.
    * Class-level mutable defaults (the original design smell) eliminated:
      every instance has its own state.
    * Thread-safety inherited from the wrapped v2 class (``self._impl.lock``).
    * Phase 3 will migrate consumers off this shim; Phase 4 deletes it.
    """

    def __init__(self, *, read_only: bool = False):
        # Late import to keep ``configuration`` import order stable.  Importing
        # ``core.orderbook`` here is safe: it has no module-level side effects.
        from core.orderbook import OrderBook as _OrderBookV2

        # Prefer live metadata, but a transient upstream failure must not make
        # importing configuration terminate the entire process.  The local
        # catalog is the last validated snapshot written by the existing
        # dashboard refresh path.
        try:
            products = rest_get_products()
            if not products:
                raise CoinbaseAPIError(
                    "Coinbase returned an empty product catalog",
                    api_error_code="empty_product_catalog",
                )
        except Exception as exc:
            products = local_products_from_metadata()
            logger.warning(
                "Coinbase product refresh unavailable during startup; "
                "using cached products.json metadata (%s)",
                type(exc).__name__,
            )
        # ``mandatory_fee_per_contract`` is consumed by
        # ``calculate_new_order_move_from_snapshot`` as a price offset to
        # recover the **round-trip** mandatory commission on a single
        # contract. Coinbase's March 2026 schedule charges per side, so
        # round-trip = 2 Ã— per-side. We pre-divide by ``contract_size`` so
        # the consumer can add the value directly to a per-unit price.
        mandatory_fees = {
            product_id: {
                "mandatory_fee_per_contract": (
                    (2.0 * get_derivatives_per_side_fee(product_id))
                    / float(this.get("future_product_details", {}).get("contract_size", 1))
                ) if this["product_type"] == ProductType.FUTURE.value else 0
            } for product_id, this in products.items()
        }
        profit = {
            "SPOT": {"BUY": 0.001, "SELL": 0.001},
            "FUTURE": {"BUY": 0.001, "SELL": 0.001},
            "BIP-20DEC30-CDE": {"BUY": 0.001, "SELL": 0.001},
        }
        try:
            positions = {"FUTURE": get_futures_positions()}
        except Exception as exc:
            positions = {"FUTURE": {}}
            logger.error(
                "Coinbase futures positions unavailable during startup; "
                "starting with an empty position snapshot (%s)",
                type(exc).__name__,
            )

        self._impl = _OrderBookV2(
            products=products,
            profit=profit,
            mandatory_fee_per_contract=mandatory_fees,
            should_replace={"FILLED": True, "CANCELLED": True},
            positions=positions,
            read_only=read_only,
        )

        # Sole legacy attribute kept on the shim: production reads this via
        # getattr(self.orderbook, "default_max_order_replacement", ...) at
        # core/order_engine.py:1310 and :1553.  Tests also override it as a
        # mock-orderbook hook.  Other dead attrs (transaction_summary,
        # cancelled, filled, active, price, db_client) were removed after a
        # workspace-wide grep confirmed zero consumers (2026-04-27).
        #
        # Follow-up note (2026-04-27): the cancelled/filled cleanup BROKE
        # follow-up creation because OrderEngine.{claim,release,complete}_
        # follow_up_processing reached those dicts via getattr() on a string
        # name (invisible to grep).  Replaced by the typed claim API on the
        # v2 OrderBook (try_claim_follow_up et al), exposed below.
        self.default_max_order_replacement = DEFAULT_MAX_ORDER_REPLACEMENT

    # ------------------------------------------------------------------
    # Follow-up processing claim API â€” pass-through to v2 OrderBook
    # ------------------------------------------------------------------

    def try_claim_follow_up(self, kind, client_order_id):
        return self._impl.try_claim_follow_up(kind, client_order_id)

    def release_follow_up(self, kind, client_order_id):
        return self._impl.release_follow_up(kind, client_order_id)

    def complete_follow_up(self, kind, client_order_id):
        return self._impl.complete_follow_up(kind, client_order_id)

    def follow_up_claim_state(self, kind, client_order_id):
        return self._impl.follow_up_claim_state(kind, client_order_id)

    # ------------------------------------------------------------------
    # Legacy attribute surface \u2014 properties returning live underlying dicts
    # ------------------------------------------------------------------

    @property
    def order(self):
        if self._impl._read_only:
            from types import MappingProxyType
            return MappingProxyType(self._impl._orders)
        return self._impl._orders

    @order.setter
    def order(self, value):
        self._impl._check_writable("order=")
        with self._impl._lock:
            self._impl._orders = dict(value)

    @property
    def parent_order_ids(self):
        if self._impl._read_only:
            from types import MappingProxyType
            return MappingProxyType(self._impl._parents)
        return self._impl._parents

    @parent_order_ids.setter
    def parent_order_ids(self, value):
        self._impl._check_writable("parent_order_ids=")
        with self._impl._lock:
            self._impl._parents = {coid: dict(v) for coid, v in dict(value).items()}

    @property
    def child_order_ids(self):
        if self._impl._read_only:
            from types import MappingProxyType
            return MappingProxyType(self._impl._child_to_parent)
        return self._impl._child_to_parent

    @child_order_ids.setter
    def child_order_ids(self, value):
        self._impl._check_writable("child_order_ids=")
        with self._impl._lock:
            self._impl._child_to_parent = dict(value)

    @property
    def positions(self):
        if self._impl._read_only:
            from types import MappingProxyType
            return MappingProxyType(self._impl._positions)
        return self._impl._positions

    @positions.setter
    def positions(self, value):
        self._impl._check_writable("positions=")
        with self._impl._lock:
            self._impl._positions = dict(value)

    @property
    def product(self):
        if self._impl._read_only:
            from types import MappingProxyType
            return MappingProxyType(self._impl._products)
        return self._impl._products

    @product.setter
    def product(self, value):
        self._impl._check_writable("product=")
        with self._impl._lock:
            self._impl._products = dict(value)

    @property
    def profit(self):
        if self._impl._read_only:
            from types import MappingProxyType
            return MappingProxyType(self._impl._profit)
        return self._impl._profit

    @profit.setter
    def profit(self, value):
        self._impl._check_writable("profit=")
        with self._impl._lock:
            self._impl._profit = dict(value)

    @property
    def mandatory_fee_per_contract(self):
        if self._impl._read_only:
            from types import MappingProxyType
            return MappingProxyType(self._impl._mandatory_fee_per_contract)
        return self._impl._mandatory_fee_per_contract

    @mandatory_fee_per_contract.setter
    def mandatory_fee_per_contract(self, value):
        self._impl._check_writable("mandatory_fee_per_contract=")
        with self._impl._lock:
            self._impl._mandatory_fee_per_contract = dict(value)

    @property
    def should_replace(self):
        if self._impl._read_only:
            from types import MappingProxyType
            return MappingProxyType(self._impl._should_replace)
        return self._impl._should_replace

    @should_replace.setter
    def should_replace(self, value):
        self._impl._check_writable("should_replace=")
        with self._impl._lock:
            self._impl._should_replace = dict(value)

    @property
    def db_module(self):
        return self._impl._db_module

    @db_module.setter
    def db_module(self, value):
        # Used by ``core/order_engine.py`` line 338: the engine grafts its
        # db_module onto the orderbook at startup.  Preserved verbatim.
        self._impl.set_db_module(value)

    # ------------------------------------------------------------------
    # Legacy method surface \u2014 delegated to the v2 implementation
    # ------------------------------------------------------------------

    def get_position_side(self, product_id: str) -> str | None:
        """Delegate to :meth:`core.orderbook.OrderBook.get_position_side`.

        Behaviour preserved verbatim: returns 'LONG' / 'SHORT' for an active
        future position, ``None`` when contracts are at or near zero
        (effectively closed) so the next order is treated as opening a new
        position.
        """

        return self._impl.get_position_side(product_id)

    @property
    def read_only(self) -> bool:
        """``True`` if every mutator on this orderbook (including legacy setters) will raise."""

        return self._impl.read_only

    # ------------------------------------------------------------------
    # v2 API surface \u2014 exposed for callers that want the new methods
    # without reaching into ``self._impl``.  These delegate to
    # :class:`core.orderbook.OrderBook`.
    # ------------------------------------------------------------------

    def diagnostic_snapshot(self) -> dict:
        """Single-lock snapshot of state needed by ``calculate_new_order_move_from_snapshot``."""

        return self._impl.diagnostic_snapshot()

    def snapshot_open_orders(self) -> dict:
        """Snapshot of orders whose ``status`` is OPEN or UPDATE."""

        return self._impl.snapshot_open_orders()

    def atomic_replace_links(self, new_parents, new_children) -> None:
        """Atomically replace the parent and child link maps under one lock."""

        self._impl.atomic_replace_links(new_parents, new_children)

    def calculate_new_order_move(self, order_id: str, target_movement: dict = None) -> dict:
        """Compute a new-order template from the current orderbook snapshot.

        Thin wrapper around :func:`calculate_new_order_move_from_snapshot`
        using the v2 implementation's :meth:`diagnostic_snapshot`.  Position
        updates are applied via the v2 implementation's
        :meth:`apply_position_update`, all under one lock acquisition.
        """

        snapshot = self._impl.diagnostic_snapshot()
        result = calculate_new_order_move_from_snapshot(
            snapshot, order_id, target_movement=target_movement
        )
        self._impl.apply_position_update(result.pop("position_update", None))
        return result

class Subscription():
    """Configuration for websocket connection to Coinbase.

    Defines which products and channels to subscribe to for real-time market
    and account updates. Used by WSClient in the OrderEngine.
    
    Attributes:
        product_ids: List of product IDs to subscribe to (derivatives + spot).
        derivatives_product_ids: Subset containing only futures products.
        channels: List of channel names to subscribe to:
                  - 'heartbeats': Connection keep-alive
                  - 'user': Account-specific events (order updates, positions)
                  - 'ticker': Real-time price updates
    
    Example:
        >>> subscription = Subscription()
        >>> ws_client.subscribe(
        ...     product_ids=subscription.product_ids,
        ...     channels=subscription.channels
        ... )
    """
    product_ids = DERIVATIVES_PRODUCT_IDS + SPOT_PRODUCT_IDS
    derivatives_product_ids = DERIVATIVES_PRODUCT_IDS

    channels = [
        "heartbeats",
        "user",
        "ticker",
        "futures_balance_summary",
    ]

ORDERBOOK = OrderBook()
