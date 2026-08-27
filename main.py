"""Main entry point for Coinbase Advanced API trading engine.

This module provides the entry point for launching the multithreaded trading engine
that manages real-time order processing with Coinbase.

Architecture:
    - OrderEngine: Main engine class (imported from core.order_engine)
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
    >>> from configuration import ORDERBOOK, ORDER_POST_ONLY, Subscription, API_KEY, API_SECRET
    >>> import database.order as DB_MODULE
    >>> 
    >>> engine = OrderEngine(
    ...     orderbook=ORDERBOOK,
    ...     db_module=DB_MODULE,
    ...     subscription=Subscription,
    ...     api_key=API_KEY,
    ...     api_secret=API_SECRET,
    ...     order_post_only=ORDER_POST_ONLY
    ... )
    >>> engine.run_forever()  # Blocks indefinitely, runs all background threads
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

import database.order as DB_MODULE
from core.order_engine import OrderEngine
from core.periodic_reconciler import PeriodicReconciler
from core.runtime_controller import get_runtime_controller
from core.startup_reconciler import run_startup_reconciliation
from dashboard_server import start_dashboard_server, set_stealth_order_bridge, update_order, update_position, add_log_entry, update_engine_status

# Set up custom logging backend to use dashboard's add_log_entry function
set_backend(add_log_entry)

def _run_reconciled_engine(
    *,
    reconciler_disabled,
    stealth_bridge,
    controller,
    engine,
):
    """Cross the startup safety barrier, then run the engine.

    ``DISABLE_RECONCILER`` is the sole explicit bypass. Otherwise an
    unavailable reconciliation result, a raised reconciliation error, or a
    failed stealth scheduler activation is fatal.
    """

    if reconciler_disabled:
        logger.warning(
            "DISABLE_RECONCILER is set; skipping startup reconciliation "
            "AND periodic audits. Drift detection is OFF until unset."
        )
    else:
        report = run_startup_reconciliation(
            fail_on_drift=False,
            auto_heal=True,
            audit_fills=True,
        )
        if report is None:
            raise RuntimeError(
                "Startup reconciliation could not verify exchange/local state"
            )

    if stealth_bridge is not None:
        stealth_bridge.activate_decisions()

    if not reconciler_disabled:
        periodic_reconciler = PeriodicReconciler(
            auto_heal=True,
            audit_fills=True,
        )
        controller.register_stop_hook(
            "periodic_reconciler",
            periodic_reconciler.stop,
        )
        periodic_reconciler.start()

    engine.run_forever()


if __name__ == "__main__":
    import sys
    
    # Initialize stealth order system first (before OrderEngine)
    from bridges.stealth_order_bridge import StealthOrderBridge
    from core.stealth_order_manager import StealthOrderManager

    stealth_manager = StealthOrderManager(DB_MODULE.DB_CLIENT)
    stealth_bridge = StealthOrderBridge(
        stealth_manager,
        None,
    )  # engine will be set later
    
    engine = OrderEngine(
        orderbook=ORDERBOOK,
        db_module=DB_MODULE,
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

    # Start dashboard server
    import sys
    start_dashboard_server()
    
    # Start stealth order system if it was initialized
    if stealth_bridge:
        set_stealth_order_bridge(stealth_bridge)
        stealth_bridge.start()

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
    # (reveal loop) wind down before consumers (event workers) â€” matches the
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
    # terminal locally but open on exchange) are NEVER auto-healed â€”
    # those are logged for operator review only.
    #
    # audit_fills=True: cross-checks REST historical fills against the
    # local fill_ledger to surface any fills the WS pipeline missed.
    # Read-only â€” operators decide whether to backfill.
    #
    # Set fail_on_drift=True in stricter environments to block startup
    # when ANY drift is detected.
    #
    # Operator escape hatch: set ``DISABLE_RECONCILER=1`` in the env to
    # skip BOTH the startup pass and the periodic background audits.
    # Useful when REST is flaky (e.g. backup-ISP day) and reconciler
    # noise is hiding the real problem. WS-driven state still works;
    # you just lose the periodic drift sweep until you flip it back.
    import os
    _reconciler_disabled = os.getenv("DISABLE_RECONCILER", "").strip().lower() in ("1", "true", "yes", "on")
    # Hydration above is intentionally passive. Only a completed startup
    # reconciliation (or the explicit operator bypass) can activate decision
    # processing and enter the engine loop.
    _run_reconciled_engine(
        reconciler_disabled=_reconciler_disabled,
        stealth_bridge=stealth_bridge,
        controller=controller,
        engine=engine,
    )
