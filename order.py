""" New Coinbase Advanced trading project """
import uuid
from random import uniform as random
from json import dumps
from time import sleep
from configuration import REST_CLIENT, \
    ORDER_DIRECTION, ORDERBOOK, format_based_on_reference

def generate_float(start: float, stop: float=None) -> float:
    """ Generate a random float between two floats
    Args:
        start (float): The minimum value of the float to be generated.
        stop (float): The maximum value of the float to be generated.
        Returns:
            float: A random float between start and stop.

    If stop is missing, return `start`.
    """

    result = random(start, stop) if stop is not None else start

    return result

def create_order(
        client_order_id = str(uuid.uuid4()),
        product_id = "BIP-20DEC30-CDE",
        side = "SELL",
        post_only: bool=False,
        order_configuration={}) -> dict:
    """ Create a limit order """
    pass


def create_limit_order_span(
        order_base_size_range: dict=None,
        delay_in_secs: int=0,
        product_id: str="NCT-USDC",
        side: str="SELL",
        max_order_count: int=1,
        order_base_size: float=1,
        order_price_difference: float=0.00001,
        start_price: float=0.00992,
        post_only: bool=False) -> list:
    """ Create a series of limit orders """

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
            sleep(delay_in_secs) # this is done first so you can delay a single order

            # print(product_id)
            # print(ORDERBOOK.product[product_id]["price_increment"])

            price = format_based_on_reference(
                float(price),
                ORDERBOOK.product[product_id]["price_increment"])

            order_base_size = format_based_on_reference(
                float(generate_float(**order_base_size_range or {"start": float(order_base_size)})),
                ORDERBOOK.product[product_id]["base_min_size"]) # type: ignore

            order = REST_CLIENT.limit_order_gtc(
                client_order_id = str(uuid.uuid4()),
                product_id = product_id,
                side = side,
                base_size = str(order_base_size),
                limit_price = str(price),
                post_only = post_only
            ).to_dict()

            if order["success"] is False:
                print(dumps(order, indent=4))
                if order["error_response"]["error"] == "INSUFFICIENT_FUND": # wait
                    sleep(1)
                else:
                    print(f"ERROR RESPONSE UNHANDLED: {order['error_response']['error']}")
                    break
            else:
                break

        price = float(start_price) + (order_price_difference * ORDER_DIRECTION[side] * order_count)

        # make price pretty (perpetual requirement)
        price = price - (price % float(ORDERBOOK.product[product_id]["price_increment"])) + \
            float(ORDERBOOK.product[product_id]["price_increment"])

        results.append(order)
        # print(f"RAW RESULT: {order}")


    return results

if __name__ == "__main__":
    print(ORDERBOOK.positions)
