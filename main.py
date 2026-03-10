""" New Coinbase Advanced trading project """
import json
import threading
from copy import deepcopy
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from coinbase.websocket import WSClient, WSClientConnectionClosedException

from configuration import Subscription, ORDERBOOK, API_KEY, API_SECRET, ORDER_POST_ONLY
from order import create_limit_order_span

TICKER = {}  # { "BTC-USD" : {} }

TICKER_LOCK = threading.Lock()
ORDERBOOK_LOCK = threading.Lock()

MAX_WORKERS = 16
EVENT_EXECUTOR = ThreadPoolExecutor(max_workers=MAX_WORKERS)


def __on_open__():
    """ websocket open connection trigger """
    print(f"{datetime.now()} Connection Opened!")


def process_user_event(event):
    """Heavy user-channel processing happens off the websocket thread."""
    try:
        if event["type"] != "update":
            return

        for order in event["orders"]:
            process_user_order(order)

    except Exception as e:
        print(f"user event processing error: {e}")


def process_user_order(order):
    client_order_id = order["client_order_id"]
    status = order["status"]

    with ORDERBOOK_LOCK:
        ORDERBOOK.order[client_order_id] = order

    if status == "SNAPSHOT":
        return

    elif status == "CANCEL_QUEUED":
        return

    elif status == "CANCELLED":
        with ORDERBOOK_LOCK:
            if ORDERBOOK.should_replace[status] is not True:
                return

            if ORDERBOOK.cancelled.get(client_order_id):
                return

            ORDERBOOK.cancelled[client_order_id] = True
            order_template = deepcopy(
                ORDERBOOK.calculate_new_order_move(client_order_id)
            )

        new_order = create_limit_order_span(
            product_id=order_template["product_id"],
            side=order_template["side"],
            order_base_size=order_template["order_base_size"],
            order_price_difference=order_template["order_price_difference"],
            start_price=order_template["start_price"],
            post_only=ORDER_POST_ONLY[order_template["side"]],
        )

        if new_order[0]["success"] is True:

            print(
                f"{datetime.now()} "
                f"{client_order_id} "
                f"|fee_move_calculated_from_pct({order_template['profit_move_pct']}): "
                f"{order_template['fee_move_calculated_from_pct']} "
                f"minimum_move_amount: {order_template['minimum_move_amount']}| "
                f"{order['order_side']}:{order['product_id']} "
                f"total_fees:{order.get('total_fees', 'N/A')} "
                f"avg_price:{order.get('avg_price', 'N/A')} "
                f"{order['cumulative_quantity']} @ {order['limit_price']} => "
                f"{order_template['side']}:{order_template['product_id']} "
                f"{order_template['order_base_size']} @ {order_template['start_price']}"
            )
        else:
            print(
                f"{datetime.now()} "
                f"{client_order_id} "
                f"|fee_move_calculated_from_pct({order_template['profit_move_pct']}): "
                f"{order_template['fee_move_calculated_from_pct']} "
                f"minimum_move_amount: {order_template['minimum_move_amount']}| "
                f"{order['order_side']}:{order['product_id']} "
                f"total_fees:{order.get('total_fees', 'N/A')} "
                f"avg_price:{order.get('avg_price', 'N/A')} "
                f"{order['cumulative_quantity']} @ {order['limit_price']} => FAILED TO PLACE"
            )

    elif status == "PENDING":
        return

    elif status == "FAILED":
        return

    elif status == "OPEN":
        with ORDERBOOK_LOCK:
            ORDERBOOK.order[client_order_id] = order
        return

    elif status == "FILLED":
        with ORDERBOOK_LOCK:
            if ORDERBOOK.should_replace[status] is not True:
                return

            if ORDERBOOK.filled.get(client_order_id):
                return

            ORDERBOOK.filled[client_order_id] = True
            order_template = deepcopy(
                ORDERBOOK.calculate_new_order_move(client_order_id)
            )

        new_order = create_limit_order_span(
            product_id=order_template["product_id"],
            side=order_template["side"],
            order_base_size=order_template["order_base_size"],
            order_price_difference=order_template["order_price_difference"],
            start_price=order_template["start_price"],
            post_only=ORDER_POST_ONLY[order_template["side"]],
        )

        if new_order[0]["success"] is True:
            print(
                f"{datetime.now()} "
                f"{client_order_id} "
                f"|fee_move_calculated_from_pct({order_template['profit_move_pct']}): "
                f"{order_template['fee_move_calculated_from_pct']} "
                f"minimum_move_amount: {order_template['minimum_move_amount']}| "
                f"{order['order_side']}:{order['product_id']} "
                f"total_fees:{order['total_fees']} "
                f"avg_price:{order['avg_price']} "
                f"{order['cumulative_quantity']} @ {order['limit_price']} => "
                f"{order_template['side']}:{order_template['product_id']} "
                f"{order_template['order_base_size']} @ {order_template['start_price']}"
            )
        else:
            print(
                f"{datetime.now()} "
                f"{client_order_id} "
                f"|fee_move_calculated_from_pct({order_template['profit_move_pct']}): "
                f"{order_template['fee_move_calculated_from_pct']} "
                f"minimum_move_amount: {order_template['minimum_move_amount']}| "
                f"{order['order_side']}:{order['product_id']} "
                f"total_fees:{order['total_fees']} "
                f"avg_price:{order['avg_price']} "
                f"{order['cumulative_quantity']} @ {order['limit_price']} => FAILED TO PLACE")

    else:
        print(f"UNRECOGNIZED STATUS {status}")


def __on_message__(msg):
    """message trigger"""
    try:
        json_msg = json.loads(msg)
        channel = json_msg.get("channel")

        if "events" not in json_msg:
            return

        for event in json_msg["events"]:
            if channel == "subscriptions":
                pass

            elif channel == "heartbeats":
                pass

            elif channel == "ticker":
                pass

            elif channel == "market_trades":
                pass

            elif channel == "tickers":
                for tickr in event["tickers"]:
                    with TICKER_LOCK:
                        TICKER[tickr["product_id"]] = tickr

            elif channel == "l2_data":
                pass

            elif channel == "user":
                # Offload expensive processing immediately
                EVENT_EXECUTOR.submit(process_user_event, deepcopy(event))

            else:
                print(f"UNRECOGNIZED CHANNEL {channel}")

    except Exception as e:
        print(e)


def connect_to_websocket():
    """ Connect to websocket """
    ws_client = WSClient(
        verbose=True,
        api_key=API_KEY,
        api_secret=API_SECRET,
        on_open=__on_open__,
        on_message=__on_message__,
    )

    ws_client.open()
    ws_client.subscribe(
        product_ids=Subscription.product_ids,
        channels=Subscription.channels,
    )

    try:
        while True:
            if ws_client.sleep_with_exception_check(1):
                break
    except WSClientConnectionClosedException as e:
        print(f"Connection Closed! {e}")
    finally:
        EVENT_EXECUTOR.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    connect_to_websocket()
