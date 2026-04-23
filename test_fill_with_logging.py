"""
Simplified test showing the fixed fill recording with INFO logging.
"""

import uuid
from database.database import PostgresDB
from database.order import insert_order_parent
from configuration import OrderBook
from core.order_engine import OrderEngine
from logging_service import get_logger
import logging
import sys

# Configure logging to show all INFO messages
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)


class MockSubscription:
    def __init__(self):
        self.channels = ["user"]
        self.product_ids = ["BIT-29MAY26-CDE"]


def test_fill_with_websocket_fields():
    """Test fill recording when websocket has cumulative_quantity."""
    print("\n" + "="*80)
    print("TEST: Fill with cumulative_quantity in websocket")
    print("="*80 + "\n")
    
    db = PostgresDB()
    orderbook = OrderBook()
    
    try:
        engine = OrderEngine(
            orderbook=orderbook,
            db_helper=db,
            subscription=MockSubscription(),
            api_key="test_key",
            api_secret="test_secret",
            order_post_only={"BUY": False, "SELL": False},
            websocket_thread_maximum=1,
            max_workers=2,
        )
        
        order_id = str(uuid.uuid4())
        insert_order_parent(
            client_order_id=order_id,
            product_id="BIT-29MAY26-CDE",
            side="SELL",
            size=5.0,
            price=78000.0,
            target_movement=0.005,
            target_movement_type="P"
        )
        
        # Complete websocket event WITH cumulative_quantity
        print("[SCENARIO] Websocket event with cumulative_quantity field\n")
        filled_order = {
            "client_order_id": order_id,
            "order_id": str(uuid.uuid4()),
            "product_id": "BIT-29MAY26-CDE",
            "order_side": "SELL",
            "side": "SELL",
            "status": "FILLED",
            "price": 78100.0,
            "avg_price": 78100.0,
            "cumulative_quantity": "5.0",  # ✓ Complete websocket event has this
            "total_fees": "100.0",
        }
        
        print(f"Order ID: {order_id}")
        print(f"Event has cumulative_quantity: 5.0")
        print(f"Event has total_fees: 100.0\n")
        
        try:
            engine.handle_filled_order(filled_order)
        except Exception as e:
            pass
        
        print("\n" + "="*80)
        print("Check logs above for [LOT-TRACK] Fill appended to ledger")
        print("Should show: SELL 5.0 @ 78100.0, fees=100.0")
        print("="*80 + "\n")
        
    finally:
        db.disconnect()


if __name__ == "__main__":
    test_fill_with_websocket_fields()
