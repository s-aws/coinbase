""" New Coinbase Advanced trading project """
import json
from datetime import datetime, UTC

from coinbase.websocket import WSClient, WSClientConnectionClosedException

from configuration import Subscription, ORDERBOOK, API_KEY, API_SECRET, ORDER_POST_ONLY

from order import create_limit_order_span

TICKER = {} # { "BTC-USD" : {} }

def __on_open__():
    """ websocket open connection trigger """
    print(f"{datetime.now(UTC)} Connection Opened!")

def __on_message__(msg):
    """ message trigger"""

    try:

        json_msg = json.loads(msg)

        if "events" in json_msg:
            for event in json_msg["events"]:

                if json_msg["channel"] == "subscriptions":
                    pass

                elif json_msg["channel"] == "heartbeats":
                    pass

                elif json_msg["channel"] == "ticker": #there is a ticker AND tickers?
                    pass

                elif json_msg["channel"] == "tickers":
                    for tickr in event["tickers"]:
                        TICKER.update({tickr["product_id"]: tickr})

                elif json_msg["channel"] == "l2_data":
                    pass # do something
                    # print(f"CHANNEL: {json_msg["channel"]}")
                    # print(json.dumps(event, indent=2))

                elif json_msg["channel"] == "user":
                    # function processing_user_channel goes here
                    # print(event)
                    if event["type"] == "update":
                        for order in event["orders"]:
                            ORDERBOOK.order[order["client_order_id"]] = order

                            if order["status"] == "SNAPSHOT":
                                pass
                                # print(order)

                            elif order["status"] == "CANCEL_QUEUED":
                                pass
                                # print(order)

                            elif order["status"] == "CANCELLED":
                                if ORDERBOOK.should_replace[order["status"]] is not True:
                                    continue

                                if not ORDERBOOK.cancelled.get(order.get("client_order_id")):
                                    ORDERBOOK.cancelled[order["client_order_id"]] = True
                                    # print(f"STATUS CANCELLED: {order["cancel_reason"]}")

                                    order_template = ORDERBOOK.calculate_new_order_move(
                                        order["client_order_id"])

                                    create_limit_order_span(
                                        product_id=order_template["product_id"],
                                        side=order_template["side"],
                                        order_base_size=order_template["order_base_size"],
                                        order_price_difference=order_template[
                                            "order_price_difference"],
                                        start_price=order_template["start_price"],
                                        fill_fees=order.get("total_fees", "0"),
                                        post_only=ORDER_POST_ONLY[order_template["side"]]
                                    )

                                    print(f"{datetime.now(UTC)} " \
                                            f"{order['client_order_id']} " \
                                            f"{order['order_side']}:{order['product_id']} " \
                                            f"total_fees:{order.get('total_fees', 'N/A')} " \
                                            f"avg_price:{order.get('avg_price', 'N/A')} " \
                                            f"{order['cumulative_quantity']} @ {order['limit_price']} => " \
                                            f"{order_template['side']}:" \
                                            f"{order_template['product_id']} " \
                                            f"{order_template['order_base_size']} @ {order_template['start_price']}")


                            elif order["status"] == "PENDING":
                                pass
                                # print(order)

                            elif order["status"] == "FAILED":
                                pass
                                # print(f"STATUS FAILED: {order}")

                            elif order["status"] == "OPEN":
                                if ORDERBOOK.order.get(order["client_order_id"]):
                                    pass
                                    #print(f"ORDER MOVED: {order['lient_order_id']}")
                                else:
                                    pass
                                    #print(f"ORDER PLACED: {order['client_order_id']}")
                                ORDERBOOK.order[order['client_order_id']] = order

                            elif order["status"] == "FILLED":
                                if ORDERBOOK.should_replace[order["status"]] is not True:
                                    continue
                                if not ORDERBOOK.filled.get(order["client_order_id"]):
                                    #and order["order_side"] == "BUY": # temp restriction for replacement
                                    # print(f"ORDER FILLED: {order['client_order_id']}")
                                    ORDERBOOK.filled[order["client_order_id"]] = True

                                    order_template = ORDERBOOK.calculate_new_order_move(
                                        order["client_order_id"])

                                    create_limit_order_span(
                                        product_id=order_template["product_id"],
                                        side=order_template["side"],
                                        order_base_size=order_template["order_base_size"],
                                        order_price_difference=order_template[
                                            "order_price_difference"],
                                        start_price=order_template["start_price"],
                                        post_only=ORDER_POST_ONLY[order_template["side"]]
                                    )

                                    print(f"{datetime.now(UTC)} " \
                                            f"{order['client_order_id']} " \
                                            f"{order['order_side']}:{order['product_id']} " \
                                            f"total_fees:{order['total_fees']} " \
                                            f"avg_price:{order['avg_price']} " \
                                            f"{order['cumulative_quantity']} @ {order['limit_price']} => " \
                                            f"{order_template['side']}:"\
                                            f"{order_template['product_id']} " \
                                            f"{order_template['order_base_size']} @ {order_template['start_price']}")
                            else:
                                print(f"UNRECOGNIZED STATUS {order['status']}")
                else:
                    print(f"UNRECOGNIZED CHANNEL {json_msg['channel']}")




    except Exception as e:
        print(e)

def connect_to_websocket():
    """ Connect to websocket """
    try:
        ws_client = WSClient(
            verbose = True,
            api_key = API_KEY,
            api_secret = API_SECRET,
            on_open = __on_open__,
            on_message = __on_message__)
    except Exception as e:
        print(e)

    ws_client.open()
    ws_client.subscribe(
        product_ids=Subscription.product_ids,
        channels = Subscription.channels)
    try:
        while True:
            if ws_client.sleep_with_exception_check(1):
                break
    except WSClientConnectionClosedException as e:
        print(f"Conection Closed! {e}")

if __name__ == "__main__":
    #print(ORDERBOOK.product["BIP-20DEC30-CDE"]["price_increment"])
    connect_to_websocket()

