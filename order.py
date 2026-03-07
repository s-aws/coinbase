""" New Coinbase Advanced trading project """
import uuid
from time import sleep
from configuration import REST_CLIENT, \
    ORDER_DIRECTION, ORDERBOOK, format_based_on_reference

def create_limit_order_span(
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
    order_base_size = float(order_base_size)
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
                float(order_base_size),
                ORDERBOOK.product[product_id]["base_min_size"])

            order = REST_CLIENT.limit_order_gtc(
                client_order_id = str(uuid.uuid4()),
                product_id = product_id,
                side = side,
                base_size = str(order_base_size),
                limit_price = str(price),
                post_only = post_only
            ).to_dict()

            if order["success"] is False:
                print(order)
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
    print(REST_CLIENT.get_fills().to_dict())
