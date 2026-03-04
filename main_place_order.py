""" New Coinbase Advanced trading project """
from order import create_limit_order_span

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
    # orders = create_limit_order_span( #size=2, diff=25, count=100, 
    #     delay_in_secs=0,
    #     product_id="BIP-20DEC30-CDE",
    #     side="SELL",
    #     order_base_size=25,
    #     order_price_difference=1000,
    #     start_price=71400,
    #     max_order_count=10
    # )
    # print(f"Count: {len(orders)}")
    # print(orders[-1])

    orders = create_limit_order_span( #size=2, diff=25, count=100, 
        delay_in_secs=0,
        product_id="BIP-20DEC30-CDE",
        side="BUY",
        order_base_size=2,
        order_price_difference=100,
        start_price=71000,
        max_order_count=50
    )
    print(f"Count: {len(orders)}")
    print(orders[-1])

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
