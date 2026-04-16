""" Main trading engine """

import json
import threading
from time import sleep
from hashlib import sha256
from queue import Queue, Full
from copy import deepcopy
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from coinbase.websocket import WSClient, WSClientConnectionClosedException

from configuration import (
    Subscription,
    ORDERBOOK,
    API_KEY,
    API_SECRET,
    ORDER_POST_ONLY,
    calculate_new_order_move_from_snapshot,
    apply_calculated_position_update,
    get_futures_positions,
)

from order import create_limit_order_span
import database.order as DB_CLIENT


class OrderEngine:
    def __init__(
        self,
        orderbook,
        db_client,
        subscription,
        api_key,
        api_secret,
        order_post_only,
        websocket_thread_maximum=3,
        max_workers=16,
        max_rotate_seen_events_bucket_seconds=60,
        max_seen_event_buckets=3,
        queue_maxsize=10000,
    ):
        self.orderbook = orderbook
        self.db_client = db_client
        self.subscription = subscription
        self.api_key = api_key
        self.api_secret = api_secret
        self.order_post_only = order_post_only

        self.websocket_thread_maximum = websocket_thread_maximum
        self.max_rotate_seen_events_bucket_seconds = max_rotate_seen_events_bucket_seconds
        self.max_seen_event_buckets = max_seen_event_buckets
        self.seen_events_default_bucket = 0
        self.queue_maxsize = queue_maxsize

        self.ticker = {}
        self.ticker_lock = threading.Lock()
        self.orderbook_lock = threading.Lock()
        self.seen_events_lock = threading.Lock()

        self.event_executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="user_event_thread",
        )

        self.event_queue = {
            channel: Queue(maxsize=self.queue_maxsize)
            for channel in self.subscription.channels
        }

        self.seen_events = {
            i: set() for i in range(self.max_seen_event_buckets)
        }

        self.logging_flags = {
            "snapshot": False,
            "open": True,
            "filled": True,
            "cancelled": True,
            "update": True,
            "user": False,
            "ticker": False,
            "connection": True,
            "event": True,
            "order": True,
            "database": True,
            "warning": True,
            "error": True,
            "reconcile": True,
        }

        self.websocket_events = {
            "SNAPSHOT": {
                "type": "snapshot",
                "orders": [],
                "positions": [
                    "perpetual_futures_positions",
                    "expiring_futures_positions",
                ],
            },
            "OPEN": {"type": "open", "orders": []},
            "FILLED": {"type": "filled", "orders": []},
            "CANCELLED": {"type": "cancelled", "orders": []},
            "UPDATE": {
                "type": "update",
                "orders": [],
                "positions": [
                    "perpetual_futures_positions",
                    "expiring_futures_positions",
                ],
            },
        }

        self.orderbook.db_client = self.db_client

    def log_message(self, log_type, message):
        if not self.logging_flags.get(log_type, False):
            return
        print(f"{datetime.now()} {threading.current_thread().name} [{log_type.upper()}] {message}")

    @staticmethod
    def hash_dict(dictionary):
        dict_string = json.dumps(dictionary, sort_keys=True)
        return sha256(dict_string.encode()).hexdigest()

    @staticmethod
    def order_limit_price_or_avg_price(order):
        if order.get("limit_price") and float(order["limit_price"]) > 0:
            return float(order["limit_price"])
        return float(order["avg_price"])

    def get_orderbook_snapshot(self):
        with self.orderbook_lock:
            return {
                "order": deepcopy(self.orderbook.order),
                "positions": deepcopy(self.orderbook.positions),
                "product": self.orderbook.product,
                "profit": self.orderbook.profit,
                "mandatory_fee_per_contract": self.orderbook.mandatory_fee_per_contract,
                "parent_order_ids": deepcopy(self.orderbook.parent_order_ids),
                "child_order_ids": deepcopy(self.orderbook.child_order_ids),
            }

    def refresh_positions_if_needed(self, product_id):
        with self.orderbook_lock:
            future_positions = self.orderbook.positions.setdefault("FUTURE", {})
            if product_id in future_positions:
                return

        try:
            refreshed_positions = get_futures_positions()
        except Exception as e:
            self.log_message("error", f"Failed to refresh futures positions for {product_id}: {e}")
            return

        with self.orderbook_lock:
            self.orderbook.positions["FUTURE"] = refreshed_positions

    def resolve_parent_client_order_id(self, client_order_id, order=None, create_parent=False, status=None):
        is_parent = False
        parent_client_order_id = None

        if client_order_id in self.orderbook.parent_order_ids:
            is_parent = True
            parent_client_order_id = client_order_id

        elif client_order_id in self.orderbook.child_order_ids:
            parent_client_order_id = self.orderbook.child_order_ids[client_order_id]

        elif create_parent and order is not None:
            self.orderbook.parent_order_ids[client_order_id] = {
                "orders": [],
                "target_movement": {
                    "movement": self.orderbook.profit[order["product_type"]][order["order_side"]],
                    "type": "P",
                },
            }

            self.log_message("order", f"Creating parent order entry for client_order_id: {client_order_id}")

            parent_id = self.db_client.insert_order_parent(
                client_order_id=client_order_id,
                product_id=order["product_id"],
                side=order["order_side"],
                size=float(order["cumulative_quantity"]),
                price=float(self.order_limit_price_or_avg_price(order)),
                target_movement=float(
                    self.orderbook.parent_order_ids[client_order_id]["target_movement"]["movement"]
                ),
                status=status or order.get("status"),
            )

            self.orderbook.parent_order_ids[client_order_id]["parent_id"] = parent_id
            is_parent = True
            parent_client_order_id = client_order_id

        return is_parent, parent_client_order_id

    def on_open(self):
        self.log_message("connection", "Connection Opened!")

    def on_message(self, msg):
        try:
            json_msg = json.loads(msg)
            channel = json_msg.get("channel")

            if any((
                "events" not in json_msg,
                channel == "subscriptions",
                not channel,
                channel not in self.event_queue,
            )):
                return

            for event in json_msg["events"]:
                event_hash = self.hash_dict(event)

                with self.seen_events_lock:
                    if any(event_hash in bucket for bucket in self.seen_events.values()):
                        continue

                try:
                    self.event_queue[channel].put(deepcopy(event), timeout=0.01)

                    with self.seen_events_lock:
                        self.seen_events[self.seen_events_default_bucket].add(event_hash)

                except Full:
                    self.log_message("warning", f"Event queue full for channel {channel}; dropping event")

        except Exception as e:
            self.log_message("error", f"Exception processing message: {e}: raw: {msg}")

    def process_user_event(self, event):
        try:
            if event["type"].upper() not in self.websocket_events:
                self.log_message("event", f"Ignoring user event received: {event}")
                return

            if "orders" in event and event["type"].upper() in ["OPEN", "FILLED", "CANCELLED", "UPDATE"]:
                for order in event["orders"]:
                    if "client_order_id" not in order:
                        self.log_message("warning", f"Missing client_order_id in order event: {order}")
                        continue
                    self.process_user_order(order)

            elif "positions" in event:
                self.process_user_snapshot(event)

        except Exception as e:
            self.log_message(
                "error",
                f"user event processing error: {e} event: {json.dumps(event, indent=4, skipkeys=True)}"
            )

    def process_user_snapshot(self, snapshot):
        for _, items in snapshot["positions"].items():
            if not items:
                continue

            for item in items:
                with self.orderbook_lock:
                    self.orderbook.positions["FUTURE"][item["product_id"]] = {
                        "side": item["side"].upper(),
                        "number_of_contracts": item["number_of_contracts"],
                        "realized_pnl": item["realized_pnl"],
                        "unrealized_pnl": item["unrealized_pnl"],
                        "entry_price": item["entry_price"],
                    }

                self.log_message(
                    "snapshot",
                    f"updated snapshot for position: {item['product_id']} "
                    f"{self.orderbook.positions['FUTURE'][item['product_id']]}"
                )

    def process_user_order(self, order):
        client_order_id = order.get("client_order_id")
        status = order.get("status")

        if all((
            status == "FILLED",
            "outstanding_hold_amount" in order,
            float(order["outstanding_hold_amount"]) > 0,
        )):
            self.log_message(
                "order",
                f"Order {client_order_id} has outstanding hold amount {order['outstanding_hold_amount']} "
                "will not treat as FILLED until hold clears"
            )
            return

        with self.orderbook_lock:
            self.orderbook.order[client_order_id] = order

        try:
            if client_order_id in self.orderbook.child_order_ids:
                self.db_client.update_order_child_status(
                    client_order_id=client_order_id,
                    status=status,
                )
            elif client_order_id in self.orderbook.parent_order_ids:
                self.db_client.update_order_parent_status(
                    client_order_id=client_order_id,
                    status=status,
                )
        except Exception as e:
            self.log_message(
                "error",
                f"Error updating order status in database: {e}, "
                f"order data: {json.dumps(order, indent=4, skipkeys=True)}"
            )

        if status == "SNAPSHOT":
            return
        if status == "CANCEL_QUEUED":
            return
        if status == "PENDING":
            return
        if status == "FAILED":
            self.log_message("error", f"Order failed: {order}")
            with self.orderbook_lock:
                self.orderbook.order.pop(client_order_id, None)
            return
        if status == "OPEN":
            return
        if status == "CANCELLED":
            self.handle_cancelled_order(order)
            return
        if status == "FILLED":
            self.handle_filled_order(order)
            return

        self.log_message("warning", f"UNRECOGNIZED STATUS {status}")

    def apply_position_update(self, order_template):
        position_update = order_template.get("position_update")
        if not position_update:
            return
        with self.orderbook_lock:
            apply_calculated_position_update(self.orderbook.positions, position_update)

    def compute_order_template(self, client_order_id, target_movement=None):
        snapshot = self.get_orderbook_snapshot()
        order = snapshot["order"].get(client_order_id)
        if not order:
            return {}

        if order.get("product_type") == "FUTURE":
            product_id = order.get("product_id")
            if product_id not in snapshot.get("positions", {}).get("FUTURE", {}):
                self.refresh_positions_if_needed(product_id)
                snapshot = self.get_orderbook_snapshot()

        return calculate_new_order_move_from_snapshot(
            snapshot,
            order_id=client_order_id,
            target_movement=target_movement,
        )

    def child_order_already_exists(self, parent_client_order_id, order_template):
        if not parent_client_order_id:
            return False

        if hasattr(self.db_client, "child_order_exists"):
            try:
                return bool(self.db_client.child_order_exists(
                    parent_client_order_id=parent_client_order_id,
                    product_id=order_template["product_id"],
                    side=order_template["side"],
                    size=float(order_template["order_base_size"]),
                    price=float(order_template["start_price"]),
                ))
            except TypeError:
                try:
                    return bool(self.db_client.child_order_exists(parent_client_order_id, order_template))
                except Exception as e:
                    self.log_message("warning", f"child_order_exists check failed: {e}")
            except Exception as e:
                self.log_message("warning", f"child_order_exists check failed: {e}")

        return False

    def resolve_parent_target_movement(self, parent_client_order_id):
        with self.orderbook_lock:
            parent = self.orderbook.parent_order_ids.get(parent_client_order_id, {})
            return deepcopy(parent.get("target_movement"))

    def handle_cancelled_order(self, order):
        client_order_id = order["client_order_id"]

        with self.orderbook_lock:
            if self.orderbook.should_replace["CANCELLED"] is not True:
                return
            if self.orderbook.cancelled.get(client_order_id):
                return
            _, parent_client_order_id = self.resolve_parent_client_order_id(client_order_id)

        order_template = self.compute_order_template(client_order_id)
        if not order_template:
            self.log_message("warning", f"Could not compute follow-up order template for cancelled order {client_order_id}")
            return

        if self.child_order_already_exists(parent_client_order_id, order_template):
            self.log_message("warning", f"Skipping duplicate child order for parent {parent_client_order_id}")
            return

        new_order = create_limit_order_span(
            product_id=order_template["product_id"],
            side=order_template["side"],
            order_base_size=order_template["order_base_size"],
            order_price_difference=order_template["order_price_difference"],
            start_price=order_template["start_price"],
            post_only=self.order_post_only[order_template["side"]],
        )

        self.record_follow_up_order(
            order,
            new_order,
            order_template,
            parent_client_order_id,
            processed_flag_name="cancelled",
        )

    def handle_filled_order(self, order):
        client_order_id = order["client_order_id"]

        with self.orderbook_lock:
            if any((
                self.orderbook.should_replace["FILLED"] is not True,
                self.orderbook.filled.get(client_order_id),
            )):
                return

            _, parent_client_order_id = self.resolve_parent_client_order_id(
                client_order_id,
                order=order,
                create_parent=True,
                status="FILLED",
            )

        target_movement = self.resolve_parent_target_movement(parent_client_order_id)
        order_template = self.compute_order_template(client_order_id, target_movement=target_movement)
        if not order_template:
            self.log_message("warning", f"Could not compute follow-up order template for filled order {client_order_id}")
            return

        if self.child_order_already_exists(parent_client_order_id, order_template):
            self.log_message("warning", f"Skipping duplicate child order for parent {parent_client_order_id}")
            return

        new_order = create_limit_order_span(
            product_id=order_template["product_id"],
            side=order_template["side"],
            order_base_size=order_template["order_base_size"],
            order_price_difference=order_template["order_price_difference"],
            start_price=order_template["start_price"],
            post_only=self.order_post_only[order_template["side"]],
        )

        self.record_follow_up_order(
            order,
            new_order,
            order_template,
            parent_client_order_id,
            processed_flag_name="filled",
        )

    def record_follow_up_order(
        self,
        source_order,
        new_order,
        order_template,
        parent_client_order_id,
        processed_flag_name=None,
    ):
        client_order_id = source_order["client_order_id"]

        if new_order[0]["success"] is not True:
            self.log_message(
                "error",
                f"{client_order_id}:{source_order['order_id']} FAILED TO PLACE "
                f"{order_template['side']} {order_template['order_base_size']} @ {order_template['start_price']}"
            )
            return

        success_response = new_order[0]["success_response"]
        limit_cfg = new_order[0]["order_configuration"]["limit_limit_gtc"]

        new_order_client_order_id = success_response["client_order_id"]
        new_order_product_id = success_response["product_id"]
        new_order_side = success_response["side"]
        new_order_size = limit_cfg["base_size"]
        new_order_price = self.order_limit_price_or_avg_price(limit_cfg)

        self.log_message(
            "order",
            f"{client_order_id}:{source_order['order_id']} => "
            f"{new_order_side} {new_order_size} @ {new_order_price}"
        )

        if not parent_client_order_id:
            self.log_message(
                "warning",
                f"Order {client_order_id} not found in parent or child order book. Order data: {source_order}"
            )
            return

        with self.orderbook_lock:
            self.orderbook.parent_order_ids[parent_client_order_id]["orders"].append(new_order_client_order_id)
            self.orderbook.child_order_ids[new_order_client_order_id] = parent_client_order_id

            if processed_flag_name:
                processed_flags = getattr(self.orderbook, processed_flag_name, None)
                if isinstance(processed_flags, dict):
                    processed_flags[client_order_id] = True

        self.apply_position_update(order_template)

        self.log_message(
            "database",
            f"Inserting child order for parent client_order_id: {parent_client_order_id} / "
            f"new child client_order_id: {new_order_client_order_id}"
        )
        self.db_client.insert_order_child(
            parent_client_order_id=parent_client_order_id,
            client_order_id=new_order_client_order_id,
            product_id=new_order_product_id,
            side=new_order_side,
            size=float(new_order_size),
            price=float(new_order_price),
        )

    def build_parent_child_order_ids_snapshot(self):
        parent_order_ids = {}
        child_order_ids = {}

        parent_orders = self.db_client.get_parent_orders()

        for parent in parent_orders:
            parent_client_order_id = parent["client_order_id"]

            parent_order_ids[parent_client_order_id] = {
                "parent_id": parent["id"],
                "orders": [],
                "target_movement": {
                    "movement": float(parent["target_movement"]),
                    "type": parent.get("target_movement_type", "P"),
                },
            }

            child_orders = self.db_client.get_child_orders(parent_client_order_id)
            for child in child_orders:
                child_client_order_id = child["client_order_id"]
                parent_order_ids[parent_client_order_id]["orders"].append(child_client_order_id)
                child_order_ids[child_client_order_id] = parent_client_order_id

        return parent_order_ids, child_order_ids

    def load_parent_child_order_ids(self, force_log=False):
        if force_log:
            self.log_message("reconcile", "Reconciling parent/child order ids from database")

        try:
            new_parent_order_ids, new_child_order_ids = self.build_parent_child_order_ids_snapshot()
        except Exception as e:
            self.log_message("error", f"Failed building parent/child snapshot from database: {e}")
            return False

        loaded_parent_count = len(new_parent_order_ids)
        loaded_child_count = len(new_child_order_ids)

        with self.orderbook_lock:
            if all((
                self.orderbook.parent_order_ids == new_parent_order_ids,
                self.orderbook.child_order_ids == new_child_order_ids,
            )):
                if force_log:
                    self.log_message(
                        "reconcile",
                        f"Parent/child order ids already in sync "
                        f"({loaded_parent_count} parents / {loaded_child_count} children)"
                    )
                return False

            self.orderbook.parent_order_ids = new_parent_order_ids
            self.orderbook.child_order_ids = new_child_order_ids

        self.log_message(
            "reconcile",
            f"Reconciled parent/child order ids from database "
            f"({loaded_parent_count} parents / {loaded_child_count} children)"
        )
        return True

    def reconcile_parent_child_order_ids_periodically(self, interval_seconds=30):
        while True:
            try:
                self.load_parent_child_order_ids(force_log=False)
            except Exception as e:
                self.log_message("error", f"Periodic reconcile error: {e}")
            sleep(interval_seconds)

    def rotate_seen_events_buckets(self):
        while True:
            with self.seen_events_lock:
                for i in range(self.max_seen_event_buckets - 1, 0, -1):
                    self.seen_events[i] = self.seen_events[i - 1]
                self.seen_events[self.seen_events_default_bucket] = set()
            sleep(self.max_rotate_seen_events_bucket_seconds)

    def generate_process_event_worker(self, channel):
        def worker():
            while True:
                event = self.event_queue[channel].get()
                try:
                    if channel == "ticker":
                        with self.ticker_lock:
                            self.log_message("ticker", json.dumps(event, indent=4))
                            for tickr in event["tickers"]:
                                self.ticker[tickr["product_id"]] = tickr

                    elif channel == "user":
                        self.log_message("user", json.dumps(event, indent=4))
                        self.event_executor.submit(self.process_user_event, event)

                finally:
                    self.event_queue[channel].task_done()

        return worker

    def connect_to_websocket(self):
        ws_client = WSClient(
            verbose=True,
            api_key=self.api_key,
            api_secret=self.api_secret,
            on_open=self.on_open,
            on_message=self.on_message,
        )

        ws_client.open()
        ws_client.subscribe(
            product_ids=self.subscription.product_ids,
            channels=self.subscription.channels,
        )

        try:
            while True:
                if ws_client.sleep_with_exception_check(1):
                    break
        except WSClientConnectionClosedException as e:
            self.log_message("connection", f"Connection Closed! {e}")

    def start_background_threads(self):
        self.load_parent_child_order_ids(force_log=True)

        threading.Thread(
            name="parent_child_reconcile_thread",
            target=self.reconcile_parent_child_order_ids_periodically,
            kwargs={"interval_seconds": 30},
            daemon=True,
        ).start()

        threading.Thread(
            name="rotate_seen_events_buckets_thread",
            target=self.rotate_seen_events_buckets,
            daemon=True,
        ).start()

        for channel in self.subscription.channels:
            threading.Thread(
                name=f"{channel}_worker",
                target=self.generate_process_event_worker(channel),
                daemon=True,
            ).start()

        for websocket in range(self.websocket_thread_maximum):
            threading.Thread(
                name=f"websocket_thread_{websocket}",
                target=self.connect_to_websocket,
                daemon=True,
            ).start()

    def run_forever(self):
        self.start_background_threads()
        while True:
            sleep(1)


if __name__ == "__main__":
    engine = OrderEngine(
        orderbook=ORDERBOOK,
        db_client=DB_CLIENT,
        subscription=Subscription,
        api_key=API_KEY,
        api_secret=API_SECRET,
        order_post_only=ORDER_POST_ONLY,
    )
    engine.run_forever()
