""" Configuration """

from os import getenv
from copy import deepcopy
from coinbase.rest import RESTClient

API_KEY = getenv("COINBASE_API_KEY")
API_SECRET = getenv("COINBASE_API_SECRET")

REST_CLIENT = RESTClient(
    api_key=API_KEY,
    api_secret=API_SECRET,
    rate_limit_headers=True)

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

DERIVATIVES_PRODUCT_IDS = [
    "BIP-20DEC30-CDE",
    "ETP-20DEC30-CDE",
    "XPP-20DEC30-CDE",
    "SLP-20DEC30-CDE",
    "ADP-20DEC30-CDE",
    "DOP-20DEC30-CDE",
    "BCP-20DEC30-CDE",
    "SUP-20DEC30-CDE",
    "AVP-20DEC30-CDE",
    "XLP-20DEC30-CDE",
    "LNP-20DEC30-CDE",
    "LCP-20DEC30-CDE",
    "POP-20DEC30-CDE",
    "HEP-20DEC30-CDE",
    "PAU-20DEC30-CDE",
    "SLR-28APR26-CDE",
    "GOL-27MAR26-CDE",
    "NOL-19MAR26-CDE",
    "PT-27MAR26-CDE",
    "CU-28APR26-CDE",
    "BIT-24APR26-CDE"
]

SPOT_PRODUCT_IDS = [
    "DOT-BTC",
    "NCT-USDC",
    "BTC-USDC",
    "LTC-USDC",
    "ETH-USDC",
    "MON-USDC",
    "ZKP-USDC",
    "WET-USDC",
    "XPL-USDC",
    "DOGE-USDC",
    "SENT-USDC"
]

def format_based_on_reference(value_to_format: float, reference_float: str) -> str:
    """
    Format a float to match the number of decimal places of a reference float.
    
    Args:
        value_to_format: The numeric value to format.
        reference_float: A reference string representing the target format.
    
    Returns:
        A formatted string representation of the value with appropriate decimal places.
    """
    result = f"{value_to_format:.{len(str(reference_float).rsplit('.', maxsplit=1)[-1]) if '.' in str(reference_float) else 0}f}"
    return result


def quantize_to_increment(value: float, increment: str, direction: str = "nearest") -> float:
    """
    Quantize a value to the nearest valid increment.
    
    Rounds, floors, or ceils a numeric value to match a specified price/size increment.
    
    Args:
        value: The value to quantize.
        increment: The increment step as a string (e.g., "0.01").
        direction: Rounding direction - "down" (floor), "up" (ceil), or "nearest" (round).
    
    Returns:
        The quantized value as a float.
    
    Raises:
        ValueError: If increment is <= 0 or direction is unsupported.
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
    """
    Retrieve all active account wallets from Coinbase.
    
    Returns:
        A dictionary mapping currency codes to wallet data dictionaries.
    """
    accounts_list = REST_CLIENT.get_accounts()["accounts"]

    account_wallets = {
        item["currency"]: item for item in accounts_list if item["deleted_at"] is None
    }

    return account_wallets

def rest_get_products() -> dict:
    """
    Retrieve all trading products from Coinbase.
    
    Fetches product information for all configured derivatives and spot products,
    filtering out trading-disabled products.
    
    Returns:
        A dictionary mapping product IDs to product data dictionaries.
    """
    products_list = [
        REST_CLIENT.get_product(product_id) for
            product_id in DERIVATIVES_PRODUCT_IDS + SPOT_PRODUCT_IDS]

    products = {
        item["product_id"]: item for item in products_list if item["trading_disabled"] is False
    }

    return products

def get_futures_positions() -> dict:
    """
    Retrieve all futures positions from Coinbase.
    
    Returns:
        A dictionary mapping product IDs to futures position data dictionaries.
        Returns empty dict if no positions exist.
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
    """
    Retrieve all open orders from Coinbase.
    
    Returns:
        A dictionary mapping client order IDs to order data dictionaries.
    """
    orders_list = REST_CLIENT.list_orders(order_status=["OPEN"]).to_dict()["orders"]

    orders = {
        order["client_order_id"]: order for order in orders_list
    }

    return orders


def apply_calculated_position_update(positions: dict, position_update: dict) -> dict:
    """
    Apply a position update returned by calculate_new_order_move_from_snapshot.
    
    Updates or creates position entries in the positions dictionary with new values.
    
    Args:
        positions: The positions dictionary to update.
        position_update: The position update dict with product_type, product_id, and fields.
    
    Returns:
        The updated positions dictionary.
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
    """
    Calculate the template for a follow-up order based on a caller-provided snapshot.
    
    Computes pricing, sizing, and position updates for the next order in a trading strategy
    without making REST calls or mutating the input snapshot.
    
    Args:
        snapshot: A snapshot dictionary with order, positions, product, profit, and fee data.
        order_id: The client order ID to compute template for.
        target_movement: Optional override for target movement (type "P" or "A" and amount).
    
    Returns:
        A dictionary with computed order template (pricing, sizing) and optional position_update.
        Returns empty dict if order not found.
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
    order_product_type = order["product_type"]
    order_status = order["status"]
    order_side = order["order_side"]
    order_size = float(
        order["leaves_quantity"] if float(order["leaves_quantity"]) > 0
        else order["cumulative_quantity"]
    )

    mandatory_fee = mandatory_fees[order_product_id]["mandatory_fee_per_contract"]
    base_increment = products[order_product_id]["base_increment"]
    quote_increment = products[order_product_id]["quote_increment"]
    price_increment = products[order_product_id]["price_increment"]
    minimum_move_amount = float(price_increment)
    profit_move_pct = profits[order_product_type][order_side]

    if order_status == "FILLED":
        order_side = ORDER_SIDE_SWITCH[order_side]

    if order_status == "CANCELLED":
        order_size = float(order["leaves_quantity"])

    if order.get("limit_price"):
        order_float_price = float(order["limit_price"])
    elif order.get("avg_price") != "0":
        order_float_price = float(order["avg_price"])
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
    """
    Container and state manager for order tracking and position management.
    
    Maintains in-memory state of parent/child orders, positions, profit targets,
    and product metadata for a trading engine.
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
                DERIVATIVES_MANDATORY_FEE_PER_CONTRACT / float(this.to_dict().get("future_product_details", {}).get("contract_size", 1))
            ) if this["product_type"] == "FUTURE" else 0
        } for product_id, this in product.items()
    }

    active = {}

    profit = {
        "SPOT": {
            "BUY": float(transaction_summary["fee_tier"]["taker_fee_rate"]) * 4,
            "SELL": float(transaction_summary["fee_tier"]["taker_fee_rate"]) * 4
        },
        "FUTURE": {
            "BUY": 0.0021,
            "SELL": 0.0021
        },
        "BIP-20DEC30-CDE": {
            "BUY": float(transaction_summary["fee_tier"]["taker_fee_rate"]) * 14,
            "SELL": float(transaction_summary["fee_tier"]["taker_fee_rate"]) * 14
        }
    }

    positions = {
        "FUTURE": get_futures_positions()
    }

    db_client = None

    def calculate_new_order_move(self, order_id: str, target_movement: dict = None) -> dict:
        """
        Calculate a new order move using current orderbook snapshot.
        
        Args:
            order_id: The client order ID to compute template for.
            target_movement: Optional target movement override.
        
        Returns:
            A dictionary with computed order template and applied position updates.
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
    """
    Configuration for websocket connection to Coinbase.
    
    Defines which products and channels to subscribe to for real-time market
    and account updates.
    """
    product_ids = DERIVATIVES_PRODUCT_IDS + SPOT_PRODUCT_IDS
    derivatives_product_ids = DERIVATIVES_PRODUCT_IDS

    channels = [
        "heartbeats",
        "user",
        "ticker",
    ]

ORDERBOOK = OrderBook()
