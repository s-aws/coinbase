"""Stealth Order Bridge - Integrates the unified order system with OrderEngine.

Provides background tasks for:
- Condition evaluation (checks if reveal conditions are met)
- Reveal trigger management (executes reveals when conditions trigger)
- Database reconciliation (syncs in-memory state with PostgreSQL)

The bridge connects StealthOrderManager (responsible for order creation and state)
with OrderEngine (responsible for event processing and follow-up creation).
"""

import threading
from time import sleep
from datetime import datetime
from typing import Dict, Any, Optional

from core.stealth_order_manager import StealthOrderManager
from calculation.formatter import safe_float
from logging_service import get_logger


logger = get_logger("StealthOrderBridge")


class StealthOrderBridge:
    """Bridges StealthOrderManager with OrderEngine.
    
    Runs background tasks to evaluate conditions and trigger reveals
    based on market data updates.
    """
    
    def __init__(self, stealth_manager: StealthOrderManager, order_engine):
        """
        Initialize the stealth order bridge.
        
        Args:
            stealth_manager: StealthOrderManager instance
            order_engine: OrderEngine instance for market data and order placement
        """
        self.stealth_manager = stealth_manager
        self.order_engine = order_engine
        # Pass order_engine's log_message to stealth_manager for consistent logging
        if hasattr(order_engine, 'log_message'):
            self.stealth_manager.log_callback = order_engine.log_message
        self.evaluation_thread = None
        self.running = False
    
    def start(self):
        """Start background evaluation and reconciliation threads.
        
        Initializes:
        - Loads existing orders from database
        - Starts evaluation thread (100ms condition checks)
        - Starts reconciliation thread (30s database sync)
        """
        if self.running:
            return
        
        # Load existing stealth orders from database
        try:
            loaded_count = self.stealth_manager.load_all_active_orders_from_db()
            logger.info(f"Loaded {loaded_count} existing stealth orders from database")
        except Exception as e:
            logger.error(f"Failed to load stealth orders from database: {e}")
        
        self.running = True
        
        # Start evaluation thread (condition checks every 100ms)
        self.evaluation_thread = threading.Thread(
            target=self._evaluation_loop,
            daemon=True,
            name="StealthOrderBridge-Evaluator"
        )
        self.evaluation_thread.start()
        
        # Start reconciliation thread (sync with database every 30s)
        self.reconciliation_thread = threading.Thread(
            target=self.reconcile_stealth_orders_periodically,
            kwargs={"interval_seconds": 30},
            daemon=True,
            name="StealthOrderBridge-Reconciliation"
        )
        self.reconciliation_thread.start()
        
        logger.info("Stealth order bridge started (evaluation + reconciliation)")
    
    def stop(self):
        """Stop background evaluation and reconciliation threads."""
        self.running = False
        if self.evaluation_thread:
            self.evaluation_thread.join(timeout=5)
        if hasattr(self, 'reconciliation_thread') and self.reconciliation_thread:
            self.reconciliation_thread.join(timeout=5)
        logger.info("Stealth order bridge stopped")
    
    def _evaluation_loop(self):
        """Background loop that evaluates stealth order conditions.
        
        Runs every 100ms to check if conditions are met for reveals.
        """
        while self.running:
            try:
                # Get all active stealth orders
                active_orders = self.stealth_manager._get_active_stealth_orders()
                
                for stealth_order_id in active_orders:
                    try:
                        should_reveal, reason = self.stealth_manager.should_trigger_reveal(stealth_order_id)
                        
                        if should_reveal:
                            logger.debug(f"Stealth order {stealth_order_id} ready to reveal: {reason}")
                            
                            # Reveal order slice
                            client_order_id = self.stealth_manager.reveal_order_slice(stealth_order_id)
                            
                            if client_order_id:
                                logger.debug(f"Revealed slice: {client_order_id}")
                                self.record_reveal_event(stealth_order_id, client_order_id, reason)
                        
                    except Exception as e:
                        logger.error(f"Error evaluating stealth order {stealth_order_id}: {e}")
                
                # Check every 100ms for responsive evaluation
                sleep(0.1)
                
            except Exception as e:
                logger.error(f"Stealth order evaluation loop error: {e}")
                sleep(1)
    
    def reconcile_stealth_orders_periodically(self, interval_seconds: int = 30) -> None:
        """Periodically load stealth orders from database and sync with memory.
        
        Runs in daemon thread, loops forever. Ensures that orders created
        externally (via other clients or processes) are loaded and tracked.
        
        Args:
            interval_seconds: Sleep duration between syncs (default 30).
            
        Returns:
            None (infinite loop)
        """
        while self.running:
            try:
                self._reconcile_stealth_orders(force_log=False)
            except Exception as e:
                logger.error(f"Stealth order reconciliation error: {e}")
            
            sleep(interval_seconds)
    
    def _reconcile_stealth_orders(self, force_log: bool = False) -> bool:
        """Load active stealth orders from database and merge with in-memory state.
        
        Args:
            force_log: Whether to log reconciliation events
            
        Returns:
            True if state changed, False if already in sync
        """
        if force_log:
            logger.info("Stealth order reconciliation started")
        
        try:
            # Load all active orders from database
            loaded_count = 0
            changed = False
            
            # Get current in-memory order IDs
            current_ids = set(self.stealth_manager.in_memory_orders.keys())
            
            # Query database for active orders
            if self.stealth_manager.db_client:
                try:
                    db_results = self.stealth_manager.db_client.execute_query(
                        """SELECT stealth_order_id FROM stealth_orders 
                           WHERE status IN ('HIDDEN', 'PENDING', 'TRIGGERED', 'REVEALED')"""
                    )
                    
                    db_ids = set(str(row['stealth_order_id']) for row in db_results)
                    
                    # Find new orders in database that aren't in memory
                    new_ids = db_ids - current_ids
                    
                    if new_ids:
                        logger.info(f"Found {len(new_ids)} new stealth orders in database")
                        
                        # Load each new order from database
                        for order_id in new_ids:
                            try:
                                order_data = self.stealth_manager._load_stealth_order_from_db(order_id)
                                if order_data:
                                    self.stealth_manager.in_memory_orders[order_id] = order_data
                                    loaded_count += 1
                                    changed = True
                            except Exception as e:
                                logger.error(f"Failed to load order {order_id}: {e}")
                    
                    if force_log or changed:
                        logger.info(
                            f"Stealth order reconciliation complete - "
                            f"database: {len(db_ids)}, memory: {len(self.stealth_manager.in_memory_orders)}, "
                            f"loaded: {loaded_count}"
                        )
                    
                    return changed
                    
                except Exception as e:
                    logger.error(f"Database query failed during reconciliation: {e}")
                    return False
            
            return False
            
        except Exception as e:
            logger.error(f"Reconciliation error: {e}")
            return False
    
    def process_ticker_update(self, product_id: str, ticker_data: Dict[str, Any]):
        """
        Process ticker update to feed market data to evaluators.
        
        Should be called from OrderEngine's ticker processing.
        
        Args:
            product_id: Product that was updated (may be ticker product like BTC-USD)
            ticker_data: Latest ticker data from Coinbase
        """
        from configuration import get_trading_product_id
        
        # Convert ticker product to trading product if necessary
        trading_product_id = get_trading_product_id(product_id)
        
        # Extract relevant fields for stealth order evaluation
        market_data = {
            "product_id": trading_product_id,
            "price": safe_float(ticker_data.get("price"), 0),
            "bid": safe_float(ticker_data.get("best_bid"), 0),
            "ask": safe_float(ticker_data.get("best_ask"), 0),
            "volume_1m": safe_float(ticker_data.get("volume_24_h"), 0) / 1440,  # Approximate 1m volume
            "time": datetime.utcnow(),
            "source": "ticker",
        }
        
        # Store market data in cache for evaluators
        self._update_market_cache(trading_product_id, market_data)
        self.stealth_manager.process_anchor_repricing_for_product(trading_product_id)
    
    def record_reveal_event(self, stealth_order_id: str, client_order_id: str, reason: str):
        """Record a reveal event to the database."""
        order = self.stealth_manager._get_stealth_order(stealth_order_id)
        
        if not order:
            return
        
        reveal_data = {
            "stealth_order_id": stealth_order_id,
            "reveal_number": len(order["revealed_orders"]),
            "placed_order_id": client_order_id,
            "reveal_trigger_reason": reason,
            "timestamp": datetime.utcnow(),
        }
        
        # Persist to database
        self._save_reveal_event_to_db(reveal_data)
    
    def get_stealth_orders(self, status: str = None) -> Dict[str, Dict[str, Any]]:
        """
        Get all stealth orders, optionally filtered by status.
        
        Args:
            status: Optional status filter (HIDDEN, PENDING, TRIGGERED, REVEALED, EXECUTED, CANCELLED)
            
        Returns:
            Dict mapping stealth_order_id to order data
        """
        all_orders = self.stealth_manager.in_memory_orders
        
        if status:
            return {
                sid: order for sid, order in all_orders.items()
                if order.get("status") == status
            }
        
        return all_orders
    
    def create_stealth_order(self, stealth_order_id: Optional[str] = None, **kwargs) -> str:
        """Convenience method to create stealth order.
        
        Args:
            stealth_order_id: Optional UUID for the stealth order. If not provided, one will be generated.
            **kwargs: Additional arguments passed to stealth_manager.create_stealth_order()
            
        Returns:
            The stealth_order_id (either provided or newly generated)
        """
        return self.stealth_manager.create_stealth_order(stealth_order_id=stealth_order_id, **kwargs)
    
    def cancel_stealth_order(self, stealth_order_id: str, reason: str = "User cancelled") -> bool:
        """Cancel a stealth order."""
        return self.stealth_manager.cancel_stealth_order(stealth_order_id, reason)
    
    # ===================== PRIVATE METHODS =====================
    
    def _update_market_cache(self, product_id: str, market_data: Dict[str, Any]):
        """Update market data cache for evaluators."""
        self.stealth_manager._market_cache[product_id] = market_data
    
    def _save_reveal_event_to_db(self, reveal_data: Dict[str, Any]):
        """Save reveal event to stealth_order_reveal_history table."""
        # SQL INSERT implementation would go here
        pass
