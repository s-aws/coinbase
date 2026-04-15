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

from configuration import Subscription, ORDERBOOK, API_KEY, API_SECRET, ORDER_POST_ONLY
from order import create_limit_order_span
import database.order as DB_CLIENT

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
MAX_ROTATE_SEEN_EVENTS_BUCKETS_IN_SECONDS = 60 # how long to keep events in the seen events buckets before rotating out, adjust based on event volume and desired de-duplication window
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

ORDERBOOK.db_client = DB_CLIENT # set the db client in the orderbook to allow for database interactions when processing events

def __hash_dict__(dictionary):
    """return a sha256 hash of a dictionary (json serialized)"""
    dict_string = json.dumps(dictionary, sort_keys=True)
    return sha256(dict_string.encode()).hexdigest()


def __order__limit_price_or_avg_price__(order):
    """helper function to get the limit price of an order if it exists, otherwise return the average price"""
    if order.get("limit_price") and float(order["limit_price"]) > 0:
        return float(order["limit_price"])
    else:
        return float(order["avg_price"])
    
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
            print(f"Ignoring user event received: {event}")
            return

        if "orders" in event and event["type"].upper() in ["OPEN", "FILLED", "CANCELLED", "UPDATE"]:
            for order in event["orders"]:
                if "client_order_id" not in order:
                    print(f"Missing client_order_id in order event: {order}")
                    continue
                process_user_order(order)

        elif "positions" in event:
            process_user_snapshot(event)

    except Exception as e:
        print(f"user event processing error: {e} event: {json.dumps(event, indent=4, skipkeys=True)}")


def process_user_order(order):
    client_order_id = order.get("client_order_id")
    status = order.get("status")

    if status == "FILLED" and "outstanding_hold_amount" in order and float(order["outstanding_hold_amount"]) > 0: # do not treat this as filled until the hold has cleared
        print(f"{datetime.now()} {threading.current_thread().name} Order {client_order_id} has outstanding hold amount {order['outstanding_hold_amount']} - will not treat as FILLED until hold clears")
        return

    with ORDERBOOK_LOCK:
        ORDERBOOK.order[client_order_id] = order

    try:
        print(f"{datetime.now()} {threading.current_thread().name} Processing user order event for client_order_id: {client_order_id} status: {status}")

        if client_order_id in ORDERBOOK.child_order_ids:
            ORDERBOOK.db_client.update_order_child_status(
                client_order_id=client_order_id,
                status=status)

        elif client_order_id in ORDERBOOK.parent_order_ids:
            ORDERBOOK.db_client.update_order_parent_status(
                client_order_id=client_order_id,
                status=status)

    except Exception as e:
        print(f"{datetime.now()} {threading.current_thread().name} Error updating parent order status in database: {e}, order data: {json.dumps(order, indent=4, skipkeys=True)}")

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
        # print(f"Order pending: {order}")
        with ORDERBOOK_LOCK:
            ORDERBOOK.order[client_order_id] = order

    elif status == "FAILED":
        print(f"Order failed: {order}")
        with ORDERBOOK_LOCK:
            ORDERBOOK.order.pop(client_order_id, None) # remove failed order from orderbook

        return

    elif status == "OPEN":
        pass

        return

    elif status == "FILLED":
        is_parent = False

        with ORDERBOOK_LOCK:
            if ORDERBOOK.should_replace[status] is not True:
                return

            if ORDERBOOK.filled.get(client_order_id):
                return

            if client_order_id not in ORDERBOOK.child_order_ids:
                if client_order_id not in ORDERBOOK.parent_order_ids:

                    ORDERBOOK.parent_order_ids[client_order_id] = {
                        "orders": [],
                        "target_movement": {
                            "movement": ORDERBOOK.profit[order["product_type"]][order["order_side"]],
                            "type": "P"
                        }
                    }

                    print(f"{datetime.now()} {threading.current_thread().name} Creating parent order entry for client_order_id: {client_order_id}")
                    parent_id = ORDERBOOK.db_client.insert_order_parent(
                            client_order_id=client_order_id,
                            product_id=order["product_id"],
                            side=order["order_side"],
                            size=float(order["cumulative_quantity"]),
                            price=float(__order__limit_price_or_avg_price__(order)),
                            target_movement=float(ORDERBOOK.parent_order_ids[client_order_id]["target_movement"]["movement"]),
                            status=status
                        )

                    ORDERBOOK.parent_order_ids[client_order_id]["parent_id"] = parent_id

                is_parent = True

            ORDERBOOK.filled[client_order_id] = True

        order_template_configuration = {
            "order_id": client_order_id
        }
        
        if is_parent:
            order_template_configuration["target_movement"] = {
                "movement": ORDERBOOK.parent_order_ids[client_order_id]["target_movement"]["movement"],
                "type": ORDERBOOK.parent_order_ids[client_order_id]["target_movement"]["type"]
            }

        order_template = deepcopy(
            ORDERBOOK.calculate_new_order_move(**order_template_configuration)
        )

        new_order_configuration = {
            "product_id": order_template["product_id"],
            "side": order_template["side"],
            "order_base_size": order_template["order_base_size"],
            "order_price_difference": order_template["order_price_difference"],
            "start_price": order_template["start_price"],
            "post_only": ORDER_POST_ONLY[order_template["side"]],
        }

        new_order = create_limit_order_span(**new_order_configuration)

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

            with ORDERBOOK_LOCK:
                new_order_client_order_id = new_order[0]["success_response"]["client_order_id"]
                new_order_product_id = new_order[0]["success_response"]["product_id"]
                new_order_side = new_order[0]["success_response"]["side"]
                new_order_size = new_order[0]["order_configuration"]["limit_limit_gtc"]["base_size"]
                new_order_price = __order__limit_price_or_avg_price__(new_order[0]["order_configuration"]["limit_limit_gtc"])

                if is_parent:
                    ORDERBOOK.parent_order_ids[client_order_id]["orders"].append(new_order_client_order_id)
                    ORDERBOOK.child_order_ids[new_order_client_order_id] = client_order_id

                    print(f"{datetime.now()} {threading.current_thread().name} Inserting child order for parent client_order_id: {client_order_id} / new child client_order_id: {new_order_client_order_id}")
                    ORDERBOOK.db_client.insert_order_child(
                            parent_client_order_id=client_order_id,
                            client_order_id=new_order_client_order_id,
                            product_id=new_order_product_id,
                            side=new_order_side,
                            size=float(new_order_size),
                            price=float(new_order_price)
                        )
                elif client_order_id in ORDERBOOK.child_order_ids:
                    ORDERBOOK.parent_order_ids[ORDERBOOK.child_order_ids[client_order_id]]["orders"].append(new_order_client_order_id)
                    ORDERBOOK.child_order_ids[new_order_client_order_id] = ORDERBOOK.child_order_ids[client_order_id]

                    print(f"{datetime.now()} {threading.current_thread().name} Inserting child order for parent client_order_id: {ORDERBOOK.child_order_ids[client_order_id]} / new child client_order_id: {new_order_client_order_id}")
                    ORDERBOOK.db_client.insert_order_child(
                            parent_client_order_id=ORDERBOOK.child_order_ids[client_order_id],
                            client_order_id=new_order_client_order_id,
                            product_id=new_order_product_id,
                            side=new_order_side,
                            size=float(new_order_size),
                            price=float(new_order_price)
                        )

                else: # this is a new parent order that has not been seen before
                    print(f"{datetime.now()} {threading.current_thread().name} WARNING: FILLED order {client_order_id} not found in parent or child order book. Order data: {order}")




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
    """message trigger with deduplication against seen events to prevent re-processing the same event multiple times"""
    try:
        json_msg = json.loads(msg)
        channel = json_msg.get("channel")

        if any((
            "events" not in json_msg,
            channel == "subscriptions",
            not channel,
            channel not in EVENT_QUEUE
        )):
            return

        for event in json_msg["events"]:
            noisy_event = any((
                "tickers" in event,
                "heartbeat_counter" in event,
                event.get("type") == "snapshot"
            ))

            event_hash = __hash_dict__(event)
            with SEEN_EVENTS_LOCK:
                if any(event_hash in event_bucket for event_bucket in SEEN_EVENTS.values()): # already processed
                    continue

                SEEN_EVENTS[SEEN_EVENTS_DEFAULT_BUCKET].add(event_hash)
                EVENT_QUEUE[channel].put(deepcopy(event))

            if not noisy_event: # for debugging we output everything that isn't a noisy event (tickers / heartbeat / snapshot)
                print(f"{datetime.now()} {threading.current_thread().name} Offloaded event to queue for channel {channel} event_hash: {event_hash}. {json.dumps(event)}")

    except Exception as e:
        print(f"Exception processing message: {e}: raw: {msg}")


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