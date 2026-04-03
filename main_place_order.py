""" New Coinbase Advanced trading project """
from order import create_limit_order_span

if __name__ == "__main__":
    ##################### PERP
    # BTC
    orders = create_limit_order_span( #size=2, diff=25, count=100, 
        delay_in_secs=0,
        product_id="BIP-20DEC30-CDE",
        side="SELL",
        order_base_size_range={"start": 10, "stop": 10},
        order_price_difference=150,
        start_price=67050,
        max_order_count=9,
        post_only=True
    )
    print(f"Count: {len(orders)}")
    print(orders[-1])

    # orders = create_limit_order_span( #size=2, diff=25, count=100, 
    #     delay_in_secs=0,
    #     product_id="BIP-20DEC30-CDE",
    #     side="BUY",
    #     order_base_size_range={"start": 1, "stop": 10},
    #     order_price_difference=2,
    #     start_price=66500,
    #     max_order_count=1,
    #     post_only=True
    # )
    # print(f"Count: {len(orders)}")
    # print(orders[-1])


    # ETH

    # orders = create_limit_order_span( #size=5, diff=1 (0.05%), count=20, 
    #     delay_in_secs=0,
    #     product_id="ETP-20DEC30-CDE",
    #     side="BUY",
    #     order_base_size_range={"start": 10, "stop": 10},
    #     order_price_difference=2,
    #     start_price=2000,
    #     max_order_count=20,
    #     post_only=True
    # )
    # print(f"Count: {len(orders)}")
    # print(orders[-1])

    # PAXG
    # orders = create_limit_order_span( #size=1, diff=4.5 (0.1%), count=10,
    #     delay_in_secs=0,
    #     product_id="PAU-20DEC30-CDE",
    #     side="SELL",
    #     order_base_size_range={"start": 1, "stop": 1},
    #     order_price_difference=4.5,
    #     start_price=4580,
    #     max_order_count=8,
    #     post_only=True
    # )
    # print(f"Count: {len(orders)}")
    # print(orders[-1])


    ##################### SPOT

    # orders = create_limit_order_span(
    #     delay_in_secs=1,
    #     product_id="BTC-USDC",
    #     side="BUY",
    #     order_base_size_range={"start": 0.001, "stop": 0.005},
    #     order_price_difference=10,
    #     start_price=67450.33,
    #     max_order_count=200,
    #     post_only=True
    # )

    # print(f"Count: {len(orders)}")
    # print(orders[-1])

