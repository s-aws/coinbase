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
from pathlib import Path
from coinbase.rest import RESTClient

from external import CoinbaseRestClient

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

DERIVATIVES_MANDATORY_FEE_PER_CONTRACT = 0.15
DEFAULT_MAX_ORDER_REPLACEMENT = 11

def safe_float(value, default: float = 0.0) -> float:
    """Safely convert a value to float, returning default on error.
    
    Handles None, empty strings, and invalid types gracefully. Useful for
    converting API responses where numeric fields may be missing or invalid.
    
    Args:
        value: The value to convert (any type).
        default: The default value to return if conversion fails (default: 0.0).
    
    Returns:
        The converted float value, or default if conversion fails.
    
    Raises:
        None - always returns a float.
    
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
    """
    try:
        if value in (None, ""):
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
    if product_type in {"SPOT", "FUTURE"}:
        return product_type

    product_id = order.get("product_id")
    product = (products or {}).get(product_id, {})
    configured_product_type = str(product.get("product_type") or "").upper()
    if configured_product_type in {"SPOT", "FUTURE"}:
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


def quantize_to_increment(value: float, increment: str, direction: str = "nearest") -> float:
    """Quantize a value to the nearest valid increment.

    Rounds, floors, or ceils a numeric value to match a specified price/size increment.
    Essential for ensuring orders comply with exchange minimum price/size requirements.

    Args:
        value: The value to quantize (e.g., a price or size).
        increment: The increment step as a string (e.g., "0.01" for cent precision).
        direction: Rounding direction:
                   - "down": floor to lower increment (conservative for price).
                   - "up": ceil to higher increment (conservative for sell price).
                   - "nearest": round to nearest increment (default).

    Returns:
        The quantized value as a float.

    Raises:
        ValueError: If increment <= 0 or direction not in {"up", "down", "nearest"}.
    
    Examples:
        >>> quantize_to_increment(100.126, "0.01")
        100.13
        >>> quantize_to_increment(100.124, "0.01", direction="down")
        100.12
        >>> quantize_to_increment(100.126, "0.01", direction="up")
        100.13
        >>> quantize_to_increment(100.126, "0.01", direction="nearest")
        100.13
        >>> quantize_to_increment(50.5, "1", direction="down")
        50.0
    """
    increment_float = float(increment)
    if increment_float <= 0:
        raise ValueError("increment must be greater than 0")

    remainder = value % increment_float

    if remainder == 0:
        return value

    if direction == "down":
        return value - remainder

    if direction == "up":
        return value + (increment_float - remainder)

    if direction == "nearest":
        down_value = value - remainder
        up_value = value + (increment_float - remainder)
        return down_value if remainder < (increment_float / 2) else up_value

    raise ValueError(f"Unsupported direction: {direction}")

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
    products_list = [
        REST_CLIENT.get_product_dict(product_id) for
            product_id in DERIVATIVES_PRODUCT_IDS + SPOT_PRODUCT_IDS]

    products = {
        item["product_id"]: item for item in products_list if item["trading_disabled"] is False
    }

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

    if order_status == "FILLED":
        order_side = ORDER_SIDE_SWITCH[order_side]

    if order_status == "CANCELLED":
        order_size = safe_float(order.get("leaves_quantity"), default=0.0)

    if safe_float(order.get("limit_price"), default=0.0) > 0:
        order_float_price = safe_float(order.get("limit_price"), default=0.0)
    elif safe_float(order.get("avg_price"), default=0.0) > 0:
        order_float_price = safe_float(order.get("avg_price"), default=0.0)
    else:
        return {}

    if target_movement is not None:
        if target_movement.get("type") == "P":
            profit_move_pct = target_movement["movement"]
        elif target_movement.get("type") == "A":
            minimum_move_amount = float(target_movement["movement"])

    fee_move_calculated_from_pct = order_float_price * profit_move_pct
    order_move_amount = fee_move_calculated_from_pct if minimum_move_amount < fee_move_calculated_from_pct else minimum_move_amount
    order_move_difference = order_move_amount * ORDER_DIRECTION[order_side]

    position_update = None

    if order_product_type == "FUTURE":
        product_positions = positions.get(order_product_type, {})
        position = deepcopy(product_positions.get(order_product_id))

        if order_status == "FILLED" and position:
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

    round_direction = "up" if order_side == "SELL" else "down"
    order_new_price = quantize_to_increment(
        order_new_price,
        price_increment,
        direction=round_direction,
    )

    price_increment_len = len(price_increment) - 2 if len(price_increment) > 3 else 1
    base_increment_len = len(base_increment) - 2 if len(base_increment) > 3 else 1

    current_contract_count = "N/A"
    if order_product_type == "FUTURE":
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


class OrderBook():
    """Container and state manager for order tracking and position management.

    Maintains in-memory state of parent/child orders, positions, profit targets,
    and product metadata for a trading engine. Acts as the source-of-truth for
    the OrderEngine's order and position data.
    
    Attributes:
        transaction_summary: Fee tier and trading stats from Coinbase.
        should_replace: Dict mapping order status to whether to create follow-up order.
        parent_order_ids: Dict mapping parent client_order_id to metadata:
                          {'client_id': {'orders': [...children], 'target_movement': {...}, ...}}
        child_order_ids: Dict mapping child client_order_id to parent client_order_id.
        cancelled: Dict tracking cancelled orders (for deduplication).
        filled: Dict tracking filled orders (for deduplication).
        order: Dict mapping client_order_id to full order data from API.
        price: Dict mapping product_id to last known price (for ticker updates).
        product: Dict mapping product_id to product metadata (increments, types, etc.).
        mandatory_fee_per_contract: Dict mapping product_id to fee per contract for futures.
        active: Dict tracking active orders (for processing state).
        default_max_order_replacement: Max number of follow-up orders per parent.
        profit: Dict mapping product_type/id to {'BUY': percent, 'SELL': percent}.
        positions: Dict with 'FUTURE' key containing open futures positions.
        db_client: PostgreSQL client for persistence (set by OrderEngine).
    
    Example:
        >>> orderbook = OrderBook()
        >>> orderbook.order['client_order_123'] = {...order_data...}
        >>> parent_id = orderbook.parent_order_ids.get('parent_order_456')
        >>> positions = orderbook.positions['FUTURE']
    """
    transaction_summary = REST_CLIENT.get_transaction_summary()

    should_replace = {
        "CANCELLED": True,
        "FILLED": True
    }

    parent_order_ids = {}
    child_order_ids = {}
    cancelled = {}
    filled = {}
    order = {}
    price = {}
    product = rest_get_products()
    mandatory_fee_per_contract = {
        product_id: {
            "mandatory_fee_per_contract": (
                DERIVATIVES_MANDATORY_FEE_PER_CONTRACT / float(this.get("future_product_details", {}).get("contract_size", 1))
            ) if this["product_type"] == "FUTURE" else 0
        } for product_id, this in product.items()
    }

    active = {}
    default_max_order_replacement = DEFAULT_MAX_ORDER_REPLACEMENT

    profit = {
        "SPOT": {
            "BUY": 0.004,
            "SELL": 0.004
        },
        "FUTURE": {
            "BUY": 0.004,
            "SELL": 0.004
        },
        "BIP-20DEC30-CDE": {
            "BUY": 0.004,
            "SELL": 0.004
        }
    }

    positions = {
        "FUTURE": get_futures_positions()
    }

    db_client = None

    def calculate_new_order_move(self, order_id: str, target_movement: dict = None) -> dict:
        """Calculate a new order move using current orderbook snapshot.

        Convenience wrapper around calculate_new_order_move_from_snapshot that uses
        the orderbook's current state. Applies position updates atomically after
        computation.

        Args:
            order_id: The client order ID to compute template for.
            target_movement: Optional override dict with 'type' and 'movement' keys.

        Returns:
            A dictionary with computed order template (same structure as
            calculate_new_order_move_from_snapshot, minus position_update key
            since it's applied directly to self.positions).
        
        Example:
            >>> template = orderbook.calculate_new_order_move('order_123')
            >>> print(template['start_price'])
        """
        snapshot = {
            "order": deepcopy(self.order),
            "positions": deepcopy(self.positions),
            "product": self.product,
            "profit": self.profit,
            "mandatory_fee_per_contract": self.mandatory_fee_per_contract,
        }
        result = calculate_new_order_move_from_snapshot(snapshot, order_id, target_movement=target_movement)
        position_update = result.pop("position_update", None)
        apply_calculated_position_update(self.positions, position_update)
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
    ]

ORDERBOOK = OrderBook()
