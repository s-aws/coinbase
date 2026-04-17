""" New Coinbase Advanced trading project """
import json
from order import create_limit_order_span

if __name__ == "__main__":
    """
    Example script demonstrating limit order placement for various products.
    
    Creates sample limit orders for derivatives and spot trading pairs.
    Includes configurable parameters for order sizing, pricing, and delays.
    """

    ##################### PERP 

    # BTC

    # orders = create_limit_order_span(
    #     delay_in_secs=0,
    #     product_id="BIP-20DEC30-CDE",
    #     side="BUY",
    #     order_base_size_range={"start": 10, "stop": 10},
    #     order_price_difference=250,
    #     start_price=76000,
    #     max_order_count=10,
    #     post_only=True
    # )
    # print(json.dumps(orders))
    # print(f"Count: {len(orders)}")

    # ETH
    # orders = create_limit_order_span(
    #     delay_in_secs=0,
    #     product_id="ETP-20DEC30-CDE",
    #     side="SELL",
    #     order_base_size_range={"start": 100, "stop": 100},
    #     order_price_difference=1,
    #     start_price=2044,
    #     max_order_count=1,
    #     post_only=True
    # )
    # print(f"Count: {len(orders)}")
    # print(orders[-1])

    # PAXG
    # orders = create_limit_order_span(
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

    ##################### 24 APR 26 #####################

    # BTC
    orders = create_limit_order_span(
        delay_in_secs=0,
        product_id="BIT-24APR26-CDE",
        side="BUY",
        order_base_size_range={"start": 10, "stop": 10},
        order_price_difference=500,
        start_price=75600,
        max_order_count=10,
        post_only=True
    )
    print(json.dumps(orders))
    print(f"Count: {len(orders)}")

    ##################### SPOT #####################

    # BTC
    # orders = create_limit_order_span(
    #     delay_in_secs=1,
    #     product_id="BTC-USDC",
    #     side="BUY",
    #     order_base_size_range={"start": 0.00001336, "stop": 0.00002},
    #     order_price_difference=9.93,
    #     start_price=75500,
    #     max_order_count=50,
    #     post_only=True
    # )

    # print(f"Count: {len(orders)}")
    # print(orders[-1])
