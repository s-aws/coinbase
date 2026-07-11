"""Construct the single canonical order engine and stealth bridge runtime."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Callable


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CanonicalOrderRuntime:
    """The one process-local engine, bridge, and manager authority."""

    order_engine: Any
    stealth_order_bridge: Any | None
    stealth_order_manager: Any | None


def hydrate_canonical_order_runtime(runtime: CanonicalOrderRuntime) -> None:
    """Strictly hydrate state required by embedded Admin follow-up handling.

    This is deliberately separate from the legacy best-effort startup methods.
    An enabled embedded API must prove placement lookup, root/child links, and
    partial-fill progress before it binds operator ingress.
    """

    manager = runtime.stealth_order_manager
    if manager is None:
        raise RuntimeError(
            "Canonical embedded Admin runtime requires a stealth order manager"
        )
    manager.load_all_active_orders_from_db(raise_on_error=True)

    engine = runtime.order_engine
    engine.load_parent_child_order_ids(force_log=True, raise_on_error=True)
    engine._hydrate_order_progress_tracker_from_db(raise_on_error=True)
    engine._canonical_state_strictly_hydrated = True


def build_canonical_order_runtime(
    *,
    orderbook: Any,
    db_module: Any,
    subscription: Any,
    api_key: str | None,
    api_secret: str | None,
    order_post_only: Any,
    require_stealth_bridge: bool = True,
    stealth_order_manager_factory: Callable[[Any], Any] | None = None,
    stealth_order_bridge_factory: Callable[[Any, Any | None], Any] | None = None,
    order_engine_factory: Callable[..., Any] | None = None,
) -> CanonicalOrderRuntime:
    """Build one engine and wire its exact bridge/manager identity.

    Construction does not start dashboard, bridge, websocket, reconciler, fee,
    or order-engine loops. Callers decide which lifecycle is authorized.
    """

    if stealth_order_manager_factory is None:
        from core.stealth_order_manager import StealthOrderManager

        stealth_order_manager_factory = StealthOrderManager
    if stealth_order_bridge_factory is None:
        from bridges.stealth_order_bridge import StealthOrderBridge

        stealth_order_bridge_factory = StealthOrderBridge
    if order_engine_factory is None:
        from core.order_engine import OrderEngine

        order_engine_factory = OrderEngine

    create_order_parent_table = getattr(
        db_module,
        "create_order_parent_table",
        None,
    )
    if not callable(create_order_parent_table):
        raise RuntimeError(
            "Canonical order runtime requires db_module.create_order_parent_table"
        )
    create_order_parent_table()

    stealth_manager = None
    stealth_bridge = None
    try:
        stealth_manager = stealth_order_manager_factory(db_module.DB_CLIENT)
        stealth_bridge = stealth_order_bridge_factory(stealth_manager, None)
    except Exception:
        if require_stealth_bridge:
            raise
        logger.exception("Stealth runtime construction failed; continuing without bridge")
        stealth_manager = None
        stealth_bridge = None

    engine = order_engine_factory(
        orderbook=orderbook,
        db_module=db_module,
        subscription=subscription,
        api_key=api_key,
        api_secret=api_secret,
        order_post_only=order_post_only,
        stealth_order_bridge=stealth_bridge,
    )

    if stealth_bridge is not None:
        stealth_bridge.order_engine = engine
        if getattr(engine, "stealth_order_bridge", None) is not stealth_bridge:
            engine.stealth_order_bridge = stealth_bridge
        if hasattr(engine, "profit_validator"):
            stealth_manager.profit_validator = engine.profit_validator
        if hasattr(engine, "fill_repo"):
            stealth_manager.fill_ledger_repo = engine.fill_repo

    return CanonicalOrderRuntime(
        order_engine=engine,
        stealth_order_bridge=stealth_bridge,
        stealth_order_manager=stealth_manager,
    )
