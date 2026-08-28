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

Run the application through this module so reconciliation and the readiness
barrier cannot be bypassed::

    python -m main
"""

import logging
import os

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
from core.enums import EngineState
from core.periodic_reconciler import PeriodicReconciler
from core.runtime_controller import get_runtime_controller
from core.startup_reconciler import run_startup_reconciliation
from dashboard_server import start_dashboard_server, set_stealth_order_bridge, update_order, update_position, add_log_entry, update_engine_status

# Set up custom logging backend to use dashboard's add_log_entry function
set_backend(add_log_entry)


_TRUE_ENV_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_ENV_VALUES = frozenset({"0", "false", "no", "off"})


def _read_strict_boolean_env(name: str, *, default: bool) -> bool:
    """Read one boolean environment variable with an explicit safe default."""

    configured_value = os.getenv(name)
    if configured_value is None or not configured_value.strip():
        return default

    raw_value = configured_value.strip().lower()
    if raw_value in _TRUE_ENV_VALUES:
        return True
    if raw_value in _FALSE_ENV_VALUES:
        return False
    raise RuntimeError(
        f"{name} must be unset/empty or one of "
        f"{sorted(_TRUE_ENV_VALUES | _FALSE_ENV_VALUES)}, got {raw_value!r}"
    )


def _raise_if_startup_is_stopping(controller, stage: str) -> None:
    """Prevent a completed blocking stage from reviving a shutdown startup."""

    if controller.is_stopping():
        raise RuntimeError(
            f"Startup aborted during {stage}: engine state is "
            f"{controller.state.value}"
        )

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

    _raise_if_startup_is_stopping(controller, "startup reconciliation")

    if stealth_bridge is not None:
        stealth_bridge.activate_decisions()

    _raise_if_startup_is_stopping(controller, "stealth decision activation")

    if not reconciler_disabled:
        periodic_reconciler = PeriodicReconciler(
            auto_heal=True,
            audit_fills=True,
        )
        if not controller.start_startup_component(
            "periodic_reconciler",
            periodic_reconciler.start,
            periodic_reconciler.stop,
        ):
            raise RuntimeError(
                "Periodic reconciliation startup refused in engine state "
                f"{controller.state.value}"
            )

    _raise_if_startup_is_stopping(controller, "periodic reconciliation startup")

    def _publish_startup_readiness() -> None:
        if controller.complete_startup():
            return
        # Shutdown won while workers were being launched. Raising lets the
        # engine unwind its short lifecycle commit before canonical cleanup.
        raise RuntimeError(
            "Startup readiness publication refused in engine state "
            f"{controller.state.value}"
        )

    engine.run_forever(
        on_background_threads_started=_publish_startup_readiness,
    )


def _install_shutdown_signal_handlers(controller) -> None:
    """Install bounded graceful-shutdown handlers for this controller."""

    import signal as _signal

    def _shutdown_signal_handler(signum, _frame):
        # This assignment must be the first handler action. It closes
        # admission without re-entering a lock that the interrupted main
        # thread may already own.
        controller.request_shutdown_from_signal()
        signame = (
            _signal.Signals(signum).name
            if signum in _signal.Signals.__members__.values()
            else str(signum)
        )
        logger.warning(f"Received {signame}; initiating graceful shutdown")
        # Keep lock-taking lifecycle work off the Python signal handler. An
        # RLock acquisition here can re-enter an interrupted state transition
        # on the main thread. The single-owner drain thread performs cleanup.
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
            logger.debug(f"Could not install handler for {_signame}: {_exc}")


def _run_application(
    *,
    reconciler_disabled,
    start_paused,
    stealth_bridge,
    controller,
    engine,
):
    """Own the testable startup barrier from passive hydration to readiness."""

    if controller.state is not EngineState.STARTING:
        raise RuntimeError(
            "Application startup requires a fresh STARTING runtime controller; "
            f"found {controller.state.value}"
        )

    if start_paused and not controller.request_pause():
        raise RuntimeError("Could not latch ENGINE_START_PAUSED during startup")

    # Prevent incomplete startup from activating workers while a bounded
    # bridge join delays full engine cleanup. Once background startup is
    # complete, this hook preserves the established producer-before-consumer
    # order: it publishes DRAINING status but leaves fill/event workers alive
    # until bridge cleanup returns and the later engine.stop hook runs.
    controller.register_stop_hook(
        "order_engine_quiesce",
        engine.prepare_for_global_drain,
    )
    if stealth_bridge is not None:
        controller.register_stop_hook("stealth_bridge", stealth_bridge.stop)
    controller.register_stop_hook("order_engine", engine.stop)

    try:
        # Signals must close admission even while passive bridge hydration is
        # blocked. Hooks already exist, so the delegated drain owns every
        # component that could have partially started.
        _install_shutdown_signal_handlers(controller)

        # Passive DB hydration precedes dashboard exposure. Decisions remain
        # disabled until _run_reconciled_engine crosses the strict barrier.
        if stealth_bridge is not None:
            set_stealth_order_bridge(stealth_bridge)
            stealth_bridge.start()
            _raise_if_startup_is_stopping(
                controller,
                "stealth bridge hydration",
            )

        start_dashboard_server()

        _run_reconciled_engine(
            reconciler_disabled=reconciler_disabled,
            stealth_bridge=stealth_bridge,
            controller=controller,
            engine=engine,
        )
    except Exception:
        # Always join or become the single drain owner. DRAINING alone does not
        # prove that the asynchronous admin/signal worker was successfully
        # created, while an existing owner returns one shared terminal result.
        controller.drain_and_stop(timeout_seconds=30.0)
        raise


if __name__ == "__main__":
    _start_paused = _read_strict_boolean_env(
        "ENGINE_START_PAUSED",
        default=True,
    )
    _reconciler_disabled = os.getenv(
        "DISABLE_RECONCILER", ""
    ).strip().lower() in ("1", "true", "yes", "on")
    
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

    # ------------------------------------------------------------------
    # Lifecycle controller, signal handlers, startup reconciliation.
    # Industry-standard ordering: register stop hooks BEFORE the first
    # signal can fire; reconcile exchange vs DB BEFORE accepting work.
    # ------------------------------------------------------------------
    controller = get_runtime_controller()

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
    # _run_application performs passive hydration before dashboard exposure.
    # Only a completed startup reconciliation (or the explicit operator
    # bypass) can activate decisions; worker launch then publishes readiness.
    _run_application(
        reconciler_disabled=_reconciler_disabled,
        start_paused=_start_paused,
        stealth_bridge=stealth_bridge,
        controller=controller,
        engine=engine,
    )
