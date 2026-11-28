"""Canonical composition root for the Coinbase trading runtime.

Importing this module is passive. ``main()`` is the only supported process
entrypoint and explicitly loads configuration, constructs live adapters,
wires application components, and crosses the reconciliation/readiness gate::

    python -m main
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from types import ModuleType
from typing import Any, Mapping, Optional

from bridges.stealth_order_bridge import StealthOrderBridge
from configuration import (
    ProductConfiguration,
    RuntimeSettings,
    Subscription,
    load_runtime_settings,
    persist_product_configuration,
)
from core.constants import get_derivatives_per_side_fee
from core.enums import EngineState, ProductType
from core.execution_core import ExecutionCore
from core.order_engine import OrderEngine
from core.orderbook import OrderBook
from core.periodic_reconciler import PeriodicReconciler
from core.runtime_controller import RuntimeController, get_runtime_controller
from core.startup_reconciler import run_startup_reconciliation
from core.stealth_order_manager import StealthOrderManager
from dashboard_server import (
    DashboardExecutionProjectionSink,
    add_log_entry,
    configure_runtime_dependencies,
    set_stealth_order_bridge,
    start_dashboard_server,
)
from database import order as order_db
from external.runtime import (
    build_rest_client,
    fetch_futures_positions,
    fetch_products,
)
from integration.order_placement_hooks import (
    get_global_placement_hook_registry,
)
from integration.fill_event_hooks import (
    get_global_fill_event_hook_registry,
)
from integration.stealth_lifecycle_hooks import (
    get_global_stealth_lifecycle_hook_registry,
)
from integration.websocket_hooks import get_global_hook_registry
from logging_service import set_backend


logger = logging.getLogger(__name__)

_TRUE_ENV_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_ENV_VALUES = frozenset({"0", "false", "no", "off"})

_DEFAULT_PROFIT_TARGETS = {
    ProductType.SPOT.value: {"BUY": 0.001, "SELL": 0.001},
    ProductType.FUTURE.value: {"BUY": 0.001, "SELL": 0.001},
    "BIP-20DEC30-CDE": {"BUY": 0.001, "SELL": 0.001},
}


@dataclass(frozen=True)
class ApplicationRuntime:
    """Fully wired resources owned by one invocation of ``main()``."""

    settings: RuntimeSettings
    rest_client: Any
    db_module: ModuleType
    orderbook: OrderBook
    stealth_manager: StealthOrderManager
    stealth_bridge: StealthOrderBridge
    execution_core: ExecutionCore
    engine: OrderEngine
    controller: RuntimeController


def _read_strict_boolean_env(
    name: str,
    *,
    default: bool,
    environ: Optional[Mapping[str, str]] = None,
) -> bool:
    """Read one boolean environment variable with an explicit safe default."""

    source = os.environ if environ is None else environ
    configured_value = source.get(name)
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


def _raise_if_startup_is_stopping(controller: Any, stage: str) -> None:
    """Prevent a completed blocking stage from reviving a shutdown startup."""

    if controller.is_stopping():
        raise RuntimeError(
            f"Startup aborted during {stage}: engine state is "
            f"{controller.state.value}"
        )


def _mandatory_fee_offsets(
    products: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, float]]:
    """Build the legacy round-trip fixed-fee price offsets once."""

    offsets: dict[str, dict[str, float]] = {}
    for product_id, product in products.items():
        product_type = str(product.get("product_type") or "").upper()
        if product_type == ProductType.FUTURE.value:
            details = product.get("future_product_details")
            contract_size = (
                details.get("contract_size", 1)
                if isinstance(details, Mapping)
                else 1
            )
            try:
                normalized_contract_size = float(contract_size)
            except (TypeError, ValueError):
                normalized_contract_size = 1.0
            if normalized_contract_size <= 0:
                normalized_contract_size = 1.0
            fee = (
                2.0 * get_derivatives_per_side_fee(product_id)
            ) / normalized_contract_size
        else:
            fee = 0.0
        offsets[product_id] = {"mandatory_fee_per_contract": fee}
    return offsets


def _load_startup_products(
    rest_client: Any,
    product_configuration: ProductConfiguration,
) -> dict[str, dict[str, Any]]:
    """Prefer one live catalog fetch and fail over to the cached snapshot."""

    try:
        products = fetch_products(
            rest_client,
            product_configuration.product_ids,
        )
        if not products:
            raise RuntimeError("Coinbase returned an empty product catalog")
    except Exception as exc:
        products = product_configuration.local_products()
        logger.warning(
            "Coinbase product refresh unavailable during startup; using "
            "cached products.json metadata (%s)",
            type(exc).__name__,
        )
        return products

    try:
        persist_product_configuration(
            products,
            ticker_to_trading=product_configuration.ticker_to_trading,
            path=product_configuration.path,
        )
    except Exception:
        # The live in-memory catalog remains usable; persistence is a cache.
        logger.warning(
            "Live product catalog loaded but products.json persistence failed",
            exc_info=True,
        )
    return products


def _load_startup_positions(rest_client: Any) -> dict[str, dict[str, Any]]:
    """Load futures positions without making catalog startup unavailable."""

    try:
        return fetch_futures_positions(rest_client)
    except Exception as exc:
        logger.error(
            "Coinbase futures positions unavailable during startup; starting "
            "with an empty position snapshot (%s)",
            type(exc).__name__,
        )
        return {}


def build_application_runtime(settings: RuntimeSettings) -> ApplicationRuntime:
    """Construct and wire every live application resource explicitly."""

    rest_client = build_rest_client(settings.api_key, settings.api_secret)
    db_module = order_db
    products = _load_startup_products(rest_client, settings.products)
    positions = _load_startup_positions(rest_client)
    orderbook = OrderBook(
        products=products,
        profit=_DEFAULT_PROFIT_TARGETS,
        mandatory_fee_per_contract=_mandatory_fee_offsets(products),
        should_replace={"FILLED": True, "CANCELLED": True},
        positions={ProductType.FUTURE.value: positions},
        ticker_to_trading=settings.products.ticker_to_trading,
        db_module=db_module,
    )

    websocket_hooks = get_global_hook_registry()
    fill_event_hooks = get_global_fill_event_hook_registry()
    placement_hooks = get_global_placement_hook_registry()
    stealth_lifecycle_hooks = (
        get_global_stealth_lifecycle_hook_registry()
    )
    projection_sink = DashboardExecutionProjectionSink()
    stealth_manager = StealthOrderManager(
        db_module.DB_CLIENT,
        order_placement_hooks=placement_hooks,
        stealth_lifecycle_hooks=stealth_lifecycle_hooks,
        rest_client=rest_client,
        product_metadata_reader=orderbook.get_product_metadata,
    )
    stealth_bridge = StealthOrderBridge(
        stealth_manager,
        None,
        rest_client=rest_client,
        trading_product_resolver=orderbook.get_trading_product_id,
    )
    engine = OrderEngine(
        orderbook=orderbook,
        db_module=db_module,
        subscription=Subscription.from_products(settings.products),
        api_key=settings.api_key,
        api_secret=settings.api_secret,
        order_post_only=settings.order_post_only,
        stealth_order_bridge=stealth_bridge,
        websocket_hooks=websocket_hooks,
        fill_event_hooks=fill_event_hooks,
        order_placement_hooks=placement_hooks,
        stealth_lifecycle_hooks=stealth_lifecycle_hooks,
        projection_sink=projection_sink,
        rest_client=rest_client,
        futures_positions_reader=lambda: fetch_futures_positions(rest_client),
    )
    stealth_bridge.order_engine = engine
    stealth_manager.profit_validator = engine.profit_validator
    controller = get_runtime_controller()
    execution_core = ExecutionCore(
        runtime_controller=controller,
        stealth_commands=stealth_bridge,
        stealth_queries=stealth_bridge,
    )

    configure_runtime_dependencies(
        orderbook=orderbook,
        execution_core=execution_core,
        state_publish_interval_seconds=(
            settings.dashboard_state_publish_interval_seconds
        ),
    )

    return ApplicationRuntime(
        settings=settings,
        rest_client=rest_client,
        db_module=db_module,
        orderbook=orderbook,
        stealth_manager=stealth_manager,
        stealth_bridge=stealth_bridge,
        execution_core=execution_core,
        engine=engine,
        controller=controller,
    )


def _run_reconciled_engine(
    *,
    reconciler_disabled: bool,
    stealth_bridge: StealthOrderBridge,
    controller: Any,
    engine: OrderEngine,
    rest_client: Any,
) -> None:
    """Cross the startup safety barrier, then run the engine."""

    if reconciler_disabled:
        logger.warning(
            "DISABLE_RECONCILER is set; skipping startup reconciliation "
            "AND periodic audits. Drift detection is OFF until unset."
        )
    else:
        report = run_startup_reconciliation(
            rest_client=rest_client,
            fail_on_drift=False,
            auto_heal=True,
            audit_fills=True,
        )
        if report is None:
            raise RuntimeError(
                "Startup reconciliation could not verify exchange/local state"
            )

    _raise_if_startup_is_stopping(controller, "startup reconciliation")
    stealth_bridge.activate_decisions()
    _raise_if_startup_is_stopping(controller, "stealth decision activation")

    if not reconciler_disabled:
        periodic_reconciler = PeriodicReconciler(
            rest_client=rest_client,
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
        raise RuntimeError(
            "Startup readiness publication refused in engine state "
            f"{controller.state.value}"
        )

    engine.run_forever(
        on_background_threads_started=_publish_startup_readiness,
    )


def _install_shutdown_signal_handlers(controller: Any) -> None:
    """Install bounded graceful-shutdown handlers for this controller."""

    import signal as _signal

    def _shutdown_signal_handler(signum, _frame):
        controller.request_shutdown_from_signal()
        signame = (
            _signal.Signals(signum).name
            if signum in _signal.Signals.__members__.values()
            else str(signum)
        )
        logger.warning("Received %s; initiating graceful shutdown", signame)
        from threading import Thread as _Thread

        _Thread(
            target=controller.drain_and_stop,
            kwargs={"timeout_seconds": 30.0},
            daemon=False,
            name="signal-shutdown-drain",
        ).start()

    for signal_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        candidate = getattr(_signal, signal_name, None)
        if candidate is None:
            continue
        try:
            _signal.signal(candidate, _shutdown_signal_handler)
        except (ValueError, OSError) as exc:
            logger.debug("Could not install handler for %s: %s", signal_name, exc)


def _run_application(
    *,
    reconciler_disabled: bool,
    start_paused: bool,
    stealth_bridge: StealthOrderBridge,
    controller: Any,
    engine: OrderEngine,
    rest_client: Any,
    dashboard_host: str = "localhost",
    dashboard_port: int = 8765,
) -> None:
    """Own the startup barrier from passive hydration to readiness."""

    if controller.state is not EngineState.STARTING:
        raise RuntimeError(
            "Application startup requires a fresh STARTING runtime controller; "
            f"found {controller.state.value}"
        )

    if start_paused and not controller.request_pause():
        raise RuntimeError("Could not latch ENGINE_START_PAUSED during startup")

    controller.register_stop_hook(
        "order_engine_quiesce",
        engine.prepare_for_global_drain,
    )
    controller.register_stop_hook("stealth_bridge", stealth_bridge.stop)
    controller.register_stop_hook("order_engine", engine.stop)

    try:
        _install_shutdown_signal_handlers(controller)
        set_stealth_order_bridge(stealth_bridge)
        stealth_bridge.start()
        _raise_if_startup_is_stopping(controller, "stealth bridge hydration")

        start_dashboard_server(dashboard_host, dashboard_port)
        _run_reconciled_engine(
            reconciler_disabled=reconciler_disabled,
            stealth_bridge=stealth_bridge,
            controller=controller,
            engine=engine,
            rest_client=rest_client,
        )
    except Exception:
        controller.drain_and_stop(timeout_seconds=30.0)
        raise


def main(*, environ: Optional[Mapping[str, str]] = None) -> None:
    """Load settings, compose one runtime, and run it until shutdown."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    set_backend(add_log_entry)
    source = os.environ if environ is None else environ
    settings = load_runtime_settings(environ=source)
    runtime = build_application_runtime(settings)

    _run_application(
        reconciler_disabled=_read_strict_boolean_env(
            "DISABLE_RECONCILER",
            default=False,
            environ=source,
        ),
        start_paused=_read_strict_boolean_env(
            "ENGINE_START_PAUSED",
            default=True,
            environ=source,
        ),
        stealth_bridge=runtime.stealth_bridge,
        controller=runtime.controller,
        engine=runtime.engine,
        rest_client=runtime.rest_client,
        dashboard_host=settings.dashboard_host,
        dashboard_port=settings.dashboard_port,
    )


if __name__ == "__main__":
    main()
