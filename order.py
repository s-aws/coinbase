""" New Coinbase Advanced trading project """
import uuid
from random import uniform as random
from json import dumps
from time import sleep
from configuration import REST_CLIENT, \
    ORDER_DIRECTION, ORDERBOOK, format_based_on_reference, quantize_to_increment

def generate_float(start: float, stop: float = None) -> float:
    """
    Generate a random float between two floats.
    
    Args:
        start: The minimum value of the float to be generated.
        stop: The maximum value of the float to be generated.
              If None, returns start value.
    
    Returns:
        A random float between start and stop (or start if stop is None).
    """
    result = random(start, stop) if stop is not None else start
    return result

def create_limit_order_span(
        order_base_size_range: dict = None,
        delay_in_secs: int = 0,
        product_id: str = "NCT-USDC",
        side: str = "SELL",
        max_order_count: int = 1,
        order_base_size: float = 1,
        order_price_difference: float = 0.00001,
        start_price: float = 0.00992,
        post_only: bool = False) -> list:
    """
    Create a series of limit orders spanning a price range.
    
    Places multiple GTC (Good-Till-Cancel) limit orders at specified price intervals,
    with optional delays between placements. Handles insufficient fund errors by retrying.
    
    Args:
        order_base_size_range: Dictionary with 'start' and optional 'stop' for size range.
                               If None, uses order_base_size as fixed size.
        delay_in_secs: Delay in seconds between order placements.
        product_id: The product ID (e.g., "BTC-USDC").
        side: Order side ("BUY" or "SELL").
        max_order_count: Number of orders to create (minimum 1).
        order_base_size: Base size for each order if range not specified.
        order_price_difference: Price difference between consecutive orders.
        start_price: Starting price for the first order.
        post_only: If True, orders will be rejected if they would immediately fill.
    
    Returns:
        A list of order response dictionaries from the API.
    """
    results = []

    if max_order_count <= 0:
        max_order_count = 1

    delay_in_secs = int(delay_in_secs)
    order_price_difference = float(order_price_difference)
    price = float(start_price)

    order_count = 0
    while order_count < max_order_count:
        order_count += 1

        while True:
            sleep(delay_in_secs)

            price = format_based_on_reference(
                float(price),
                ORDERBOOK.product[product_id]["price_increment"])

            order_base_size = format_based_on_reference(
                float(generate_float(**order_base_size_range or {"start": float(order_base_size)})),
                ORDERBOOK.product[product_id]["base_min_size"])

            order = REST_CLIENT.limit_order_gtc(
                client_order_id=str(uuid.uuid4()),
                product_id=product_id,
                side=side,
                base_size=str(order_base_size),
                limit_price=str(price),
                post_only=post_only
            ).to_dict()

            if order["success"] is False:
                print(dumps(order, indent=4))
                if order["error_response"]["error"] == "INSUFFICIENT_FUND":
                    sleep(1)
                else:
                    print(f"ERROR RESPONSE UNHANDLED: {order['error_response']['error']}")
                    break
            else:
                break

        price = float(start_price) + (order_price_difference * ORDER_DIRECTION[side] * order_count)

        round_direction = "up" if side == "SELL" else "down"
        price = quantize_to_increment(
            price,
            ORDERBOOK.product[product_id]["price_increment"],
            direction=round_direction,
        )

        results.append(order)

    return results

if __name__ == "__main__":
    print(ORDERBOOK.positions)
