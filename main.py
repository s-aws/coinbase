""" New Coinbase Advanced trading project """
import json
import threading
from time import sleep
from hashlib import sha256
from queue import Queue
from copy import deepcopy
from datetime import datetime, time
from concurrent.futures import ThreadPoolExecutor
from coinbase.websocket import WSClient, WSClientConnectionClosedException

import database.order as db
from configuration import Subscription, ORDERBOOK, API_KEY, API_SECRET, ORDER_POST_ONLY
from order import create_limit_order_span

TICKER = {}  # { "BTC-USD" : {} }
TICKER_LOCK = threading.Lock()
ORDERBOOK_LOCK = threading.Lock()

MAX_WORKERS = 16
EVENT_EXECUTOR = ThreadPoolExecutor(
    max_workers=MAX_WORKERS,
    thread_name_prefix="user_event_thread")
EVENT_QUEUE = {
    channel: Queue() for channel in Subscription.channels
}

SEEN_EVENTS_LOCK = threading.Lock()
SEEN_EVENTS_DEFAULT_BUCKET = 0
MAX_ROTATE_SEEN_EVENTS_BUCKETS_IN_SECONDS = 10 # how long to keep events in the seen events buckets before rotating out, adjust based on event volume and desired de-duplication window
MAX_SEEN_EVENTS_BUCKETS = 3 # bucket 0 is the newest bucket, each additional bucket is aged. Minimum 2 buckets to ensure we have a "new" and "old" bucket to compare against when de-duplicating events. Increase buckets if you want to allow for more aged events to still be considered for de-duplication, but this will increase memory usage.
SEEN_EVENTS = {
    i: set() for i in range(MAX_SEEN_EVENTS_BUCKETS)
}

WEBSOCKET_THREAD_MAXIMUM = 3
WEBSOCKET_THREAD_NAME = "websocket_thread"

WEBSOCKET_EVENTS = {
    "SNAPSHOT": {
        "type": "snapshot",
        "orders": [],
        "positions": [
            "perpetual_futures_positions",
            "expiring_futures_positions"
        ]
    },
    "OPEN": {
        "type": "open",
        "orders": []
    },
    "FILLED": {
        "type": "filled",
        "orders": []
    },
    "CANCELLED": {
        "type": "cancelled",
        "orders": []
    },
    "UPDATE": {
        "type": "update",
        "orders": [],
        "positions": [
            "perpetual_futures_positions",
            "expiring_futures_positions"
        ]
    }
}

def __on_open__():
    """ websocket open connection trigger """
    print(
        f"{datetime.now()} "
        f"{threading.current_thread().name} "
        "Connection Opened!")


def process_user_event(event):
    """Heavy user-channel processing happens off the websocket thread."""
    try:
        if event["type"].upper() not in WEBSOCKET_EVENTS:
            print(f"Non-update event received: {event}")
            return

        if "orders" in event and event["type"].upper() in ["OPEN", "FILLED", "CANCELLED", "UPDATE"]:
            for order in event["orders"]:
                if "client_order_id" not in order:
                    print(f"Missing client_order_id in order event: {order}")
                    continue
                process_user_order(order)

        if "positions" in event:
            process_user_snapshot(event)

    except Exception as e:
        print(f"user event processing error: {e}")


def process_user_order(order):
    client_order_id = order["client_order_id"]
    status = order["status"]

    with ORDERBOOK_LOCK:
        ORDERBOOK.order[client_order_id] = order

    if status == "SNAPSHOT":
        pass # handled in process_user_snapshot()

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
                f"{threading.current_thread().name} "
                f"{client_order_id} "
                f"{order['product_id']} "
                f"{order['order_side']} "
                f"{order['cumulative_quantity']} @ {order['limit_price']} => "
                f"{order_template['side']} "
                f"{order_template['order_base_size']} @ {order_template['start_price']} "
                f"\tfee_move_calculated_from_pct({order_template['profit_move_pct']}): "
                f"{order_template['fee_move_calculated_from_pct']} "
                f"minimum_move_amount: {order_template['minimum_move_amount']} "
                f"total_fees:{order.get('total_fees', 'N/A')} "
                f"avg_price:{order.get('avg_price', 'N/A')} "
                f"current_contract_count: {order_template['current_contract_count']} "
            )
        else:
            print(
                f"{datetime.now()} "
                f"{threading.current_thread().name} "
                f"{client_order_id} "
                f"{order['product_id']} "
                f"{order['order_side']} "
                f"{order['cumulative_quantity']} @ {order['limit_price']} => FAILED TO PLACE "
                f"\tfee_move_calculated_from_pct({order_template['profit_move_pct']}): "
                f"{order_template['fee_move_calculated_from_pct']} "
                f"minimum_move_amount: {order_template['minimum_move_amount']} "
                f"total_fees:{order.get('total_fees', 'N/A')} "
                f"avg_price:{order.get('avg_price', 'N/A')} "
                f"current_contract_count: {order_template['current_contract_count']} "
            )

    elif status == "PENDING":
        return

    elif status == "FAILED":
        return

    elif status == "OPEN":
        with ORDERBOOK_LOCK:
            ORDERBOOK.order[client_order_id] = order
        try:
            db.insert_order_parent(
                client_order_id=client_order_id,
                product_id=order["product_id"],
                side=order["order_side"],
                size=float(order["leaves_quantity"]),
                price=float(order["limit_price"]),
                target_movement=float(ORDERBOOK.profit[order["product_type"]][order["order_side"]]),
                status=status)
        except Exception as e:
            print(f"Error inserting parent order into database: {e}, order data: {json.dumps(order, indent=4, skipkeys=True)}")

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
                f"{threading.current_thread().name} "
                f"{client_order_id} "
                f"{order['order_side']} "
                f"{order['product_id']} "
                f"{order['cumulative_quantity']} @ {order['limit_price']} => "
                f"{order_template['side']} "
                f"{order_template['order_base_size']} @ {order_template['start_price']} "
                f"\tfee_move_calculated_from_pct({order_template['profit_move_pct']}): "
                f"{order_template['fee_move_calculated_from_pct']} "
                f"minimum_move_amount: {order_template['minimum_move_amount']} "
                f"total_fees:{order['total_fees']} "
                f"avg_price:{order['avg_price']} "
                f"current_contract_count: {order_template['current_contract_count']} "
            )
        else:
            print(
                f"{datetime.now()} "
                f"{threading.current_thread().name} "
                f"{client_order_id} "
                f"{order['order_side']} "
                f"{{order['product_id']}} "
                f"{order['cumulative_quantity']} @ {order['limit_price']} => FAILED TO PLACE "
                f"\tfee_move_calculated_from_pct({order_template['profit_move_pct']}): "
                f"{order_template['fee_move_calculated_from_pct']} "
                f"minimum_move_amount: {order_template['minimum_move_amount']} "
                f"total_fees:{order['total_fees']} "
                f"avg_price:{order['avg_price']} "
                f"current_contract_count: {order_template['current_contract_count']} "
            )

    else:
        print(f"UNRECOGNIZED STATUS {status}")

def process_user_snapshot(snapshot):
    """process the user snapshot event from the websocket / user channel
    
    {'product_id': 'BIT-24APR26-CDE', 'side': 'Long', 'number_of_contracts': '776', 'realized_pnl': '-197.19190281971428568', 'unrealized_pnl': '-14201.408099180285714064', 'entry_price': '72955.0783632964285714'}
    
    """
    for _, items in snapshot["positions"].items():
        if items:
            for item in items:
                with ORDERBOOK_LOCK:
                    ORDERBOOK.positions["FUTURE"][item["product_id"]] = {
                        "side": item["side"].upper(),
                        "number_of_contracts": item["number_of_contracts"],
                        "realized_pnl": item["realized_pnl"],
                        "unrealized_pnl": item["unrealized_pnl"],
                        "entry_price": item["entry_price"]
                    }
                    # print(f"updated snapshot for position: {item['product_id']} {ORDERBOOK.positions['FUTURE'][item['product_id']]}")


def __on_message__(msg):
    """message trigger"""
    try:
        json_msg = json.loads(msg)
        channel = json_msg.get("channel")

        if "events" not in json_msg:
            return

        for event in json_msg["events"]:
            if channel == "subscriptions":
                return

            event_hash = sha256(json.dumps(event).encode()).hexdigest()
            with SEEN_EVENTS_LOCK:
                for event_bucket in SEEN_EVENTS.values():
                    if event_hash in event_bucket: # already processed
                        return
                SEEN_EVENTS[SEEN_EVENTS_DEFAULT_BUCKET].add(event_hash)
                EVENT_QUEUE[channel].put(deepcopy(event))

    except KeyError as e:
        print(f"KeyError processing message: {e}")

def rotate_seen_events_buckets():
    """Rotate seen events buckets to allow for aging out old events and preventing memory bloat"""
    while True:
        with SEEN_EVENTS_LOCK:
            # Rotate buckets
            for i in range(MAX_SEEN_EVENTS_BUCKETS - 1, 0, -1):
                SEEN_EVENTS[i] = SEEN_EVENTS[i-1]
            SEEN_EVENTS[SEEN_EVENTS_DEFAULT_BUCKET] = set() # reset the newest bucket
            rotated_bucket_results = {i: len(bucket) for i, bucket in SEEN_EVENTS.items()}
            # print(
            #     f"{datetime.now()} {threading.current_thread().name} "
            #     "Cleared bucket index: 0, "
            #     f"current bucket index: sizes: {rotated_bucket_results}")
        sleep(MAX_ROTATE_SEEN_EVENTS_BUCKETS_IN_SECONDS) # rotate every N seconds

def generate_process_event_worker_func(channel):
    """ Worker function to process events off the queue """
    def worker():
        while True:
            event = EVENT_QUEUE[channel].get()
            # Process the event based on channel
            try:
                if channel == "heartbeat":
                    pass

                if channel == "ticker":
                    with TICKER_LOCK:
                        for tickr in event["tickers"]:
                            TICKER[tickr["product_id"]] = tickr

                elif channel == "market_trades":
                    pass

                elif channel == "l2_data":
                    pass

                elif channel == "user":
                    # print(json.dumps(event, indent=4))
#                    print(f"{datetime.now()} {threading.current_thread().name} Offloading event to worker: {event}")
                    EVENT_EXECUTOR.submit(process_user_event, event)
            finally:
                EVENT_QUEUE[channel].task_done()
    return worker

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

    # Start worker threads for each channel to process events off the queue
    for channel in Subscription.channels:
        threading.Thread(
            name=f"{channel}_thread",
            target=generate_process_event_worker_func(channel),
            daemon=True).start()

    # Keep the main thread alive to maintain the websocket connection and allow worker threads to process events
    try:
        while True:
            if ws_client.sleep_with_exception_check(1):
                break
    except WSClientConnectionClosedException as e:
        print(f"Connection Closed! {e}")

if __name__ == "__main__":

    # Start a thread to rotate seen events buckets
    threading.Thread(
        name="rotate_seen_events_buckets_thread",
        target=rotate_seen_events_buckets,
        daemon=True).start()

    # Start multiple websocket threads to increase chances of maintaining a connection and processing events in case of intermittent connection issues
    for websocket in range(WEBSOCKET_THREAD_MAXIMUM):
         threading.Thread(
            name=f"{WEBSOCKET_THREAD_NAME}_{websocket}",
            target=connect_to_websocket,
            daemon=True).start()

    while True:
        sleep(1)
        
    # EVENT_EXECUTOR.shutdown(wait=False, cancel_futures=True)