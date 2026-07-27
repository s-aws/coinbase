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
    get_rest_client,
)

import database.order as DB_MODULE
from application.admin_api.embedded_server import (
    build_embedded_admin_api_config,
    prepare_embedded_admin_api_server,
)
from application.admin_api.spot_portfolio_binding import (
    SPOT_PORTFOLIO_ID_ENV,
    SPOT_PORTFOLIO_LABEL_ENV,
    require_spot_test_portfolio_binding,
)
from core.periodic_reconciler import PeriodicReconciler
from core.runtime_composition import (
    build_canonical_order_runtime,
    hydrate_canonical_order_runtime,
)
from core.runtime_controller import get_runtime_controller
from core.startup_reconciler import run_startup_reconciliation
from core.coinbase_execution_authority import (
    SOURCE_DISABLED_COINBASE_EXECUTION_ERROR,
)
from dashboard_server import start_dashboard_server, set_stealth_order_bridge, update_order, update_position, add_log_entry, update_engine_status

# Set up custom logging backend to use dashboard's add_log_entry function
set_backend(add_log_entry)

if __name__ == "__main__":
    import os
    import sys

    if os.environ.get("COINBASE_EXECUTION_ENABLED") == "1":
        raise RuntimeError(SOURCE_DISABLED_COINBASE_EXECUTION_ERROR)

    embedded_admin_api_requested = (
        build_embedded_admin_api_config() is not None
    )

    embedded_runtime_subscription = Subscription
    if embedded_admin_api_requested:
        spot_portfolio_binding = require_spot_test_portfolio_binding(
            rest_client=get_rest_client(),
            expected_portfolio_id=os.environ.get(SPOT_PORTFOLIO_ID_ENV),
            expected_portfolio_label=os.environ.get(
                SPOT_PORTFOLIO_LABEL_ENV,
                "Test",
            ),
        )
        spot_product_ids = [
            product_id
            for product_id in Subscription.product_ids
            if product_id not in Subscription.derivatives_product_ids
        ]
        if not spot_product_ids:
            raise RuntimeError(
                "Embedded Admin API Spot runtime requires configured Spot products"
            )

        class EmbeddedSpotSubscription:
            product_ids = spot_product_ids
            derivatives_product_ids = []
            retail_portfolio_id = spot_portfolio_binding.observed_portfolio_id
            channels = [
                channel
                for channel in Subscription.channels
                if channel != "futures_balance_summary"
            ]

        embedded_runtime_subscription = EmbeddedSpotSubscription
        logger.info(
            "Embedded Admin API bound to Spot profile %s (%s)",
            spot_portfolio_binding.expected_portfolio_label,
            spot_portfolio_binding.observed_portfolio_id,
        )

    from application.admin_api.operator_parent_move_premark_runtime import (
        get_default_operator_parent_move_premark_goal_repository,
        initialize_operator_parent_move_premark_runtime,
    )

    initialize_operator_parent_move_premark_runtime()
    parent_move_repository = (
        get_default_operator_parent_move_premark_goal_repository()
    )
    cancelled_follow_up_suppression_checker = (
        parent_move_repository.should_suppress_source_cancel_follow_up
    )
    cancelled_follow_up_suppression_acknowledger = (
        parent_move_repository.acknowledge_source_cancel_event_suppression
    )

    # Construct the one engine/bridge authority used by the live runtime and
    # its opt-in embedded Admin API.
    runtime = build_canonical_order_runtime(
        orderbook=ORDERBOOK,
        db_module=DB_MODULE,
        subscription=embedded_runtime_subscription,
        api_key=API_KEY,
        api_secret=API_SECRET,
        order_post_only=ORDER_POST_ONLY,
        require_stealth_bridge=embedded_admin_api_requested,
        cancelled_follow_up_suppression_checker=(
            cancelled_follow_up_suppression_checker
        ),
        cancelled_follow_up_suppression_acknowledger=(
            cancelled_follow_up_suppression_acknowledger
        ),
    )
    engine = runtime.order_engine
    stealth_bridge = runtime.stealth_order_bridge
    stealth_bridge_ready = False

    if stealth_bridge:
        if hasattr(engine, "profit_validator"):
            logger.info("StealthOrderManager wired with OrderEngine profit_validator")
        if hasattr(engine, "fill_repo"):
            logger.info("StealthOrderManager wired with OrderEngine fill ledger")

    # The default legacy runtime keeps its original dashboard/bridge startup
    # ordering. Embedded mode defers all command ingress and live producers
    # until strict hydration and the Admin API bind have succeeded.
    if not embedded_admin_api_requested:
        start_dashboard_server()

    if stealth_bridge:
        try:
            set_stealth_order_bridge(stealth_bridge)
            if embedded_admin_api_requested:
                # The legacy hotpoint placer is a parallel order-origination
                # path and is outside the single fill/follow-up slice. Disable
                # it before hydration or any live producer can observe fills.
                engine.set_hotpoint_auto_place_enabled(False)
                hydrate_canonical_order_runtime(runtime)
            else:
                stealth_bridge.start()
            stealth_bridge_ready = True
        except Exception:
            if embedded_admin_api_requested:
                engine.stop()
                raise
            import traceback
            traceback.print_exc()

    # ------------------------------------------------------------------
    # Lifecycle controller, signal handlers, startup reconciliation.
    # Industry-standard ordering: register stop hooks BEFORE the first
    # signal can fire; reconcile exchange vs DB BEFORE accepting work.
    # ------------------------------------------------------------------
    controller = get_runtime_controller()

    def handle_embedded_admin_api_unexpected_exit(failure):
        logger.error(
            "Embedded Admin API exited unexpectedly; draining canonical runtime",
            exc_info=(
                type(failure),
                failure,
                failure.__traceback__,
            ) if failure is not None else None,
        )
        controller.request_shutdown()
        from threading import Thread

        Thread(
            target=controller.drain_and_stop,
            kwargs={"timeout_seconds": 30.0},
            daemon=False,
            name="embedded-admin-api-failure-drain",
        ).start()

    def handle_embedded_event_monitoring_lost():
        logger.critical(
            "Authenticated Coinbase user-event monitoring was lost; "
            "draining canonical runtime"
        )
        controller.request_shutdown()
        from threading import Thread

        Thread(
            target=controller.drain_and_stop,
            kwargs={"timeout_seconds": 30.0},
            daemon=False,
            name="event-monitoring-loss-drain",
        ).start()

    if embedded_admin_api_requested:
        engine.set_event_monitoring_lost_callback(
            handle_embedded_event_monitoring_lost
        )

    try:
        embedded_admin_api_server = prepare_embedded_admin_api_server(
            order_engine=engine,
            stealth_order_bridge=stealth_bridge,
            stealth_order_manager=runtime.stealth_order_manager,
            runtime_ready=stealth_bridge_ready,
            unexpected_exit_callback=(
                handle_embedded_admin_api_unexpected_exit
                if embedded_admin_api_requested
                else None
            ),
        )
    except Exception:
        if stealth_bridge is not None:
            stealth_bridge.stop()
        engine.stop()
        raise

    if embedded_admin_api_server is not None:
        controller.register_stop_hook("admin_api", embedded_admin_api_server.stop)

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
    if _reconciler_disabled:
        if embedded_admin_api_requested:
            controller.drain_and_stop(timeout_seconds=30.0)
            raise RuntimeError(
                "Embedded Admin API requires startup reconciliation; "
                "DISABLE_RECONCILER cannot be set"
            )
        logger.warning(
            "DISABLE_RECONCILER is set; skipping startup reconciliation "
            "AND periodic audits. Drift detection is OFF until unset."
        )
    else:
        try:
            startup_reconciliation_report = run_startup_reconciliation(
                fail_on_drift=embedded_admin_api_requested,
                auto_heal=True,
                audit_fills=True,
            )
            if (
                embedded_admin_api_requested
                and startup_reconciliation_report is None
            ):
                raise RuntimeError(
                    "Embedded Admin API requires successful startup reconciliation"
                )
        except Exception:
            logger.exception("Startup reconciliation raised")
            if embedded_admin_api_requested:
                controller.drain_and_stop(timeout_seconds=30.0)
                raise
            logger.warning("Continuing without successful startup reconciliation")

    # Periodic deep-audit against exchange truth. Mirrors the startup
    # configuration so drift that develops at runtime is healed on the
    # same cadence (every 15 minutes by default). Registered as a stop
    # hook so a graceful drain joins the audit thread cleanly.
    if not _reconciler_disabled:
        periodic_reconciler = PeriodicReconciler(
            auto_heal=True,
            audit_fills=True,
        )
        controller.register_stop_hook("periodic_reconciler", periodic_reconciler.stop)
        periodic_reconciler.start()

    try:
        if embedded_admin_api_server is not None:
            # Prove the HTTP bind before any bridge/websocket producer. Reads
            # are available during startup, while the ASGI readiness gate
            # rejects mutations until every producer has started.
            embedded_admin_api_server.start()

            def mark_embedded_admin_api_runtime_ready():
                if not engine.wait_for_event_monitoring_ready(
                    timeout_seconds=30.0
                ):
                    raise RuntimeError(
                        "Embedded Admin API cannot prove Coinbase event "
                        "monitoring readiness"
                    )
                # Start the final order-producing bridge only after the user
                # channel is authenticated. Keep HTTP mutations closed until
                # the bridge has also started successfully.
                stealth_bridge.start()
                embedded_admin_api_server.mark_runtime_ready()

            engine.run_forever(on_started=mark_embedded_admin_api_runtime_ready)
        else:
            engine.run_forever()
    except Exception:
        controller.drain_and_stop(timeout_seconds=30.0)
        raise
    finally:
        if embedded_admin_api_server is not None:
            embedded_admin_api_server.stop()
