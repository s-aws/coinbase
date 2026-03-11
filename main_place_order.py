""" New Coinbase Advanced trading project """
from order import create_limit_order_span

if __name__ == "__main__":
    ##################### PERP
    # BTC
    # orders = create_limit_order_span( #size=2, diff=25, count=100, 
    #     delay_in_secs=0,
    #     product_id="BIP-20DEC30-CDE",
    #     side="SELL",
    #     order_base_size_range={"start": 1, "stop": 5},
    #     order_price_difference=75,
    #     start_price=69275,
    #     max_order_count=20
    # )
    # print(f"Count: {len(orders)}")
    # print(orders[-1])

    orders = create_limit_order_span( #size=2, diff=25, count=100, 
        delay_in_secs=0,
        product_id="BIP-20DEC30-CDE",
        side="BUY",
        order_base_size_range={"start": 1, "stop": 3},
        order_price_difference=100,
        start_price=71000,
        max_order_count=10
    )
    print(f"Count: {len(orders)}")
    # print(orders[-1])

    ##################### SPOT

    # orders = create_limit_order_span(
    #     delay_in_secs=0,
    #     product_id="BTC-USDC",
    #     side="BUY",
    #     order_base_size=0.001,
    #     order_price_difference=100,
    #     start_price=68022,
    #     max_order_count=1,
    #     post_only=True
    # )

    # print(f"Count: {len(orders)}")
    # print(orders[-1])
