""" New Coinbase Advanced trading project """
from order import create_limit_order_span

if __name__ == "__main__":
    ##################### PERP
    # BTC
    orders = create_limit_order_span( #size=2, diff=25, count=100, 
        delay_in_secs=0,
        product_id="BIP-20DEC30-CDE",
        side="SELL",
        order_base_size_range={"start": 2, "stop": 10},
        order_price_difference=95,
        start_price=70100,
        max_order_count=10,
        post_only=True
    )
    print(f"Count: {len(orders)}")
    print(orders[-1])

    # orders = create_limit_order_span( #size=2, diff=25, count=100, 
    #     delay_in_secs=0,
    #     product_id="BIP-20DEC30-CDE",
    #     side="BUY",
    #     order_base_size_range={"start": 1, "stop": 10},
    #     order_price_difference=100,
    #     start_price=69600,
    #     max_order_count=100,
    #     post_only=True
    # )
    # print(f"Count: {len(orders)}")
    # print(orders[-1])


    # PAXG
    # orders = create_limit_order_span(
    #     delay_in_secs=0,
    #     product_id="PAU-20DEC30-CDE",
    #     side="BUY",
    #     order_base_size_range={"start": 2, "stop": 5},
    #     order_price_difference=35,
    #     start_price=4350,
    #     max_order_count=10,
    #     post_only=True
    # )
    # print(f"Count: {len(orders)}")
    # print(orders[-1])


    ##################### SPOT

    # orders = create_limit_order_span(
    #     delay_in_secs=0,
    #     product_id="BTC-USDC",
    #     side="SELL",
    #     order_base_size_range={"start": 0.0001, "stop": 0.001},
    #     order_price_difference=21.01,
    #     start_price=71050.51,
    #     max_order_count=100,
    #     post_only=True
    # )

    # print(f"Count: {len(orders)}")
    # print(orders[-1])

