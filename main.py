"""Main entry point for Coinbase Advanced API trading engine.

This module provides the entry point for launching the multithreaded trading engine
that manages real-time order processing with Coinbase.

Architecture:
    - OrderEngine: Main engine class (imported from core.order_engine)
    - OrderEngineOrchestrator: Facade/Orchestrator pattern (imported from bridges)
    - Background Threads:
        * websocket_threads: Maintain connections to Coinbase (configurable count)
        * event_workers: Process events from specific channels (ticker, user, heartbeats)
        * reconciliation_thread: Periodically sync parent/child orders from database
        * deduplication_thread: Rotate event deduplication buckets
    - Event Processing:
        * Thread-safe event queuing with deduplication using hash-based bucketing
        * Processing flags prevent duplicate follow-up order creation
        * Position updates applied atomically with order placements

Example:
    >>> from core.order_engine import OrderEngine
    >>> from bridges.engine_orchestrator import OrderEngineOrchestrator
    >>> from configuration import ORDERBOOK, ORDER_POST_ONLY, Subscription, API_KEY, API_SECRET
    >>> from database.order import DB_CLIENT
    >>> 
    >>> engine = OrderEngine(
    ...     orderbook=ORDERBOOK,
    ...     db_client=DB_CLIENT,
    ...     subscription=Subscription,
    ...     api_key=API_KEY,
    ...     api_secret=API_SECRET,
    ...     order_post_only=ORDER_POST_ONLY
    ... )
    >>> orchestrator = OrderEngineOrchestrator(engine)
    >>> orchestrator.run_forever()  # Blocks indefinitely, runs all background threads
"""

from configuration import (
    Subscription,
    ORDERBOOK,
    API_KEY,
    API_SECRET,
    ORDER_POST_ONLY,
)

from database.order import DB_CLIENT
from core.order_engine import OrderEngine
from bridges.engine_orchestrator import OrderEngineOrchestrator
from bridges.stealth_order_bridge import integrate_stealth_orders_with_engine
from dashboard_server import start_dashboard_server, set_stealth_order_bridge, update_order, update_position, add_log_entry, update_engine_status

if __name__ == "__main__":
    engine = OrderEngine(
        orderbook=ORDERBOOK,
        db_client=DB_CLIENT,
        subscription=Subscription,
        api_key=API_KEY,
        api_secret=API_SECRET,
        order_post_only=ORDER_POST_ONLY,
    )

    orchestrator = OrderEngineOrchestrator(engine)
    
    # Start dashboard server
    start_dashboard_server()
    
    # Initialize stealth order system
    try:
        stealth_bridge = integrate_stealth_orders_with_engine(engine, DB_CLIENT)
        set_stealth_order_bridge(stealth_bridge)
        stealth_bridge.start()
        print("Stealth order system initialized and started")
    except Exception as e:
        print(f"Warning: Failed to initialize stealth order system: {e}")
        print("Continuing without stealth orders...")
    
    orchestrator.run_forever()
