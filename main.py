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
    >>> import database.order as DB_HELPER
    >>> 
    >>> engine = OrderEngine(
    ...     orderbook=ORDERBOOK,
    ...     db_helper=DB_HELPER,
    ...     subscription=Subscription,
    ...     api_key=API_KEY,
    ...     api_secret=API_SECRET,
    ...     order_post_only=ORDER_POST_ONLY
    ... )
    >>> orchestrator = OrderEngineOrchestrator(engine)
    >>> orchestrator.run_forever()  # Blocks indefinitely, runs all background threads
"""

import logging

# Configure logging for all modules
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Initialize custom logging service
from logging_service import set_backend

from configuration import (
    Subscription,
    ORDERBOOK,
    API_KEY,
    API_SECRET,
    ORDER_POST_ONLY,
)

import database.order as DB_HELPER
from core.order_engine import OrderEngine
from bridges.engine_orchestrator import OrderEngineOrchestrator
from dashboard_server import start_dashboard_server, set_stealth_order_bridge, update_order, update_position, add_log_entry, update_engine_status

# Set up custom logging backend to use dashboard's add_log_entry function
set_backend(add_log_entry)

if __name__ == "__main__":
    import sys
    
    # Initialize stealth order system first (before OrderEngine)
    stealth_bridge = None
    try:
        from bridges.stealth_order_bridge import StealthOrderBridge
        from core.stealth_order_manager import StealthOrderManager
        
        stealth_manager = StealthOrderManager(DB_HELPER.DB_CLIENT)
        stealth_bridge = StealthOrderBridge(stealth_manager, None)  # engine will be set later
    except Exception as e:
        import traceback
        traceback.print_exc()
    
    engine = OrderEngine(
        orderbook=ORDERBOOK,
        db_helper=DB_HELPER,
        subscription=Subscription,
        api_key=API_KEY,
        api_secret=API_SECRET,
        order_post_only=ORDER_POST_ONLY,
        stealth_order_bridge=stealth_bridge,
    )
    
    # Update stealth bridge with engine reference if it exists
    if stealth_bridge:
        stealth_bridge.order_engine = engine

    orchestrator = OrderEngineOrchestrator(engine)
    
    # Start dashboard server
    import sys
    start_dashboard_server()
    
    # Start stealth order system if it was initialized
    if stealth_bridge:
        try:
            set_stealth_order_bridge(stealth_bridge)
            stealth_bridge.start()
        except Exception as e:
            import traceback
            traceback.print_exc()
    
    orchestrator.run_forever()
