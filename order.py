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
        post_only: bool=False) -> dict:
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
                    print(f"ERROR RESPONSE UNHANDLED: {order["error_response"]["error"]}")
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
    ##################### PERP
    ## ETH
    # orders = create_limit_order_span(
    #     delay_in_secs=0,
    #     product_id="ETP-20DEC30-CDE",
    #     side="BUY",
    #     order_base_size=4,
    #     order_price_difference=10,
    #     start_price=2940,
    #     max_order_count=25
    # )

    # orders = create_limit_order_span(
    #     delay_in_secs=0,
    #     product_id="ETP-20DEC30-CDE",
    #     side="SELL",
    #     order_base_size=4,
    #     order_price_difference=10,
    #     start_price=2901,
    #     max_order_count=25
    # )

    ## XRP
    # orders = create_limit_order_span(
    #     delay_in_secs=0,
    #     product_id="XPP-20DEC30-CDE",
    #     side="SELL",
    #     order_base_size=1,
    #     order_price_difference=0.0019,
    #     start_price=1.9299,
    #     max_order_count=20
    # )

    # orders = create_limit_order_span(
    #     delay_in_secs=0,
    #     product_id="XPP-20DEC30-CDE",
    #     side="BUY",
    #     order_base_size=2,
    #     order_price_difference=0.0005,
    #     start_price=1.9057,
    #     max_order_count=10
    # )

    # BTC
    orders = create_limit_order_span( #size=2, diff=25, count=100, 
        delay_in_secs=0,
        product_id="BIP-20DEC30-CDE",
        side="SELL",
        order_base_size=2,
        order_price_difference=50,
        start_price=68900,
        max_order_count=100
    )
    print(f"Count: {len(orders)}")
    print(orders[-1])

    # orders = create_limit_order_span( #size=2, diff=25, count=100, 
    #     delay_in_secs=0,
    #     product_id="BIP-20DEC30-CDE",
    #     side="BUY",
    #     order_base_size=10,
    #     order_price_difference=100,
    #     start_price=67880,
    #     max_order_count=5
    # )
    # print(f"Count: {len(orders)}")
    # print(orders[-1])

    # orders = create_limit_order_span(
    #     delay_in_secs=0,
    #     product_id="SENT-USDC",
    #     side="BUY",
    #     order_base_size=500,
    #     order_price_difference=0.00007,
    #     start_price=0.02560,
    #     max_order_count=200
    # )

    # orders = create_limit_order_span(
    #     delay_in_secs=0,
    #     product_id="BTC-USDC",
    #     side="BUY",
    #     order_base_size=0.001,
    #     order_price_difference=5,
    #     start_price=67200,
    #     max_order_count=1000,
    #     post_only=True
    # )

    # print(f"Count: {len(orders)}")
    # print(orders[-1])

    # print(f"Count: {len(orders)}")
    # print(orders[-1])
