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
from core.periodic_reconciler import PeriodicReconciler
from core.runtime_controller import get_runtime_controller
from core.startup_reconciler import run_startup_reconciliation
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
        # Use the engine's shared ProfitValidator for reveal-time revalidation.
        if hasattr(engine, "profit_validator"):
            stealth_bridge.stealth_manager.profit_validator = engine.profit_validator
            logger.info("StealthOrderManager wired with OrderEngine profit_validator")

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

    # ------------------------------------------------------------------
    # Lifecycle controller, signal handlers, startup reconciliation.
    # Industry-standard ordering: register stop hooks BEFORE the first
    # signal can fire; reconcile exchange vs DB BEFORE accepting work.
    # ------------------------------------------------------------------
    controller = get_runtime_controller()

    if stealth_bridge is not None:
        controller.register_stop_hook(
            "stealth_bridge", stealth_bridge.stop
        )

    # Register the OrderEngine stop hook AFTER the stealth bridge so producers
    # (reveal loop) wind down before consumers (event workers) — matches the
    # industry-standard "stop producers first, then consumers" drain order.
    controller.register_stop_hook("order_engine", engine.stop)

    import signal as _signal

    def _shutdown_signal_handler(signum, _frame):
        signame = _signal.Signals(signum).name if signum in _signal.Signals.__members__.values() else str(signum)
        logger.warning(f"Received {signame}; initiating graceful shutdown")
        # Run drain in a background thread so the signal handler returns
        # promptly. drain_and_stop is idempotent.
        from threading import Thread as _Thread
        _Thread(
            target=controller.drain_and_stop,
            kwargs={"timeout_seconds": 30.0},
            daemon=False,  # block process exit until drain completes
            name="signal-shutdown-drain",
        ).start()

    # SIGINT and SIGTERM exist on both POSIX and Windows; SIGBREAK is
    # Windows-specific (Ctrl+Break). Register defensively.
    for _signame in ("SIGINT", "SIGTERM", "SIGBREAK"):
        _sig = getattr(_signal, _signame, None)
        if _sig is None:
            continue
        try:
            _signal.signal(_sig, _shutdown_signal_handler)
        except (ValueError, OSError) as _exc:
            # signal.signal raises ValueError off the main thread on some
            # platforms; that's fine, we registered everywhere we could.
            logger.debug(f"Could not install handler for {_signame}: {_exc}")

    # Reconcile against the exchange BEFORE running.
    #
    # auto_heal=True: marks the safe drift bucket
    # (closed-on-exchange / open-locally) as RECONCILED_CLOSED so they
    # stop being treated as live. Risky buckets (unknown to local /
    # terminal locally but open on exchange) are NEVER auto-healed —
    # those are logged for operator review only.
    #
    # audit_fills=True: cross-checks REST historical fills against the
    # local fill_ledger to surface any fills the WS pipeline missed.
    # Read-only — operators decide whether to backfill.
    #
    # Set fail_on_drift=True in stricter environments to block startup
    # when ANY drift is detected.
    try:
        run_startup_reconciliation(
            fail_on_drift=False,
            auto_heal=True,
            audit_fills=True,
        )
    except Exception:
        logger.exception("Startup reconciliation raised; continuing")

    # Periodic deep-audit against exchange truth. Mirrors the startup
    # configuration so drift that develops at runtime is healed on the
    # same cadence (every 15 minutes by default). Registered as a stop
    # hook so a graceful drain joins the audit thread cleanly.
    periodic_reconciler = PeriodicReconciler(
        auto_heal=True,
        audit_fills=True,
    )
    controller.register_stop_hook("periodic_reconciler", periodic_reconciler.stop)
    periodic_reconciler.start()

    orchestrator.run_forever()
