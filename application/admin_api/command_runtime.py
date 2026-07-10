"""Runtime dependency composition for Admin API command services."""

from __future__ import annotations

from dataclasses import dataclass
import os
from threading import Lock
from typing import Any, Callable
import uuid

from core.action_condition_guard import rest_credentials_configured
from core.runtime_controller import get_runtime_controller
from logging_service import get_logger

from .command_service import AdminApiCommandDependencies, AdminApiCommandService
from .live_execution import LIVE_EXECUTION_RUNTIME_ENABLED_ENV


ORDER_EVENT_STREAM_DISABLED_ENV = "COINBASE_ADMIN_API_ORDER_EVENT_STREAM_DISABLED"

logger = get_logger("AdminApiCommandRuntime")

_order_event_stream_lock = Lock()
_order_event_stream_publisher: Any | None = None


@dataclass(frozen=True, slots=True)
class AdminApiRestClientBinding:
    """Bound REST client plus availability evidence."""

    client: Any | None
    available: bool


@dataclass(frozen=True, slots=True)
class AdminApiCommandRuntimeReadiness:
    """Backend command-runtime readiness for controlled-live Admin API placement."""

    live_runtime_enabled: bool
    rest_client_available: bool
    runtime_ready: bool
    missing_reason: str | None
    source: str = "application/admin_api/command_runtime.py"


def admin_api_live_runtime_enabled() -> bool:
    """Return whether backend Admin API live runtime wiring is enabled."""

    return os.environ.get(LIVE_EXECUTION_RUNTIME_ENABLED_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def admin_api_order_event_stream_disabled() -> bool:
    """Return whether Admin API should fail before order-event publishing."""

    return os.environ.get(ORDER_EVENT_STREAM_DISABLED_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def load_admin_api_rest_client() -> AdminApiRestClientBinding:
    """Load the canonical Coinbase REST client when Admin API live runtime is on."""

    if not admin_api_live_runtime_enabled() or not rest_credentials_configured():
        return AdminApiRestClientBinding(client=None, available=False)

    try:
        import configuration

        client = configuration.get_rest_client()
    except Exception as exc:
        logger.warning("Admin API REST client unavailable: %s", exc)
        return AdminApiRestClientBinding(client=None, available=False)

    return AdminApiRestClientBinding(client=client, available=client is not None)


def build_admin_api_command_runtime_readiness() -> AdminApiCommandRuntimeReadiness:
    """Return fail-closed command-runtime evidence for controlled-live placement."""

    live_runtime_enabled = admin_api_live_runtime_enabled()
    if not live_runtime_enabled:
        return AdminApiCommandRuntimeReadiness(
            live_runtime_enabled=False,
            rest_client_available=False,
            runtime_ready=False,
            missing_reason="live_runtime_disabled",
        )
    if not rest_credentials_configured():
        return AdminApiCommandRuntimeReadiness(
            live_runtime_enabled=True,
            rest_client_available=False,
            runtime_ready=False,
            missing_reason="coinbase_rest_credentials_missing",
        )

    rest_client = load_admin_api_rest_client()
    if not rest_client.available:
        return AdminApiCommandRuntimeReadiness(
            live_runtime_enabled=True,
            rest_client_available=False,
            runtime_ready=False,
            missing_reason="coinbase_rest_client_unavailable",
        )
    return AdminApiCommandRuntimeReadiness(
        live_runtime_enabled=True,
        rest_client_available=True,
        runtime_ready=True,
        missing_reason=None,
    )


def get_admin_api_order_event_stream_publisher() -> Any | None:
    """Return the shared durable order-event publisher for Admin API placement."""

    if admin_api_order_event_stream_disabled():
        return None

    global _order_event_stream_publisher
    if _order_event_stream_publisher is not None:
        return _order_event_stream_publisher

    with _order_event_stream_lock:
        if _order_event_stream_publisher is not None:
            return _order_event_stream_publisher
        try:
            import database.order as order_db
            from business.order_event_stream import OrderEventStreamPublisher

            _order_event_stream_publisher = OrderEventStreamPublisher(order_db)
        except Exception as exc:
            logger.warning("Admin API order_event_stream publisher unavailable: %s", exc)
            _order_event_stream_publisher = None
        return _order_event_stream_publisher


def log_admin_api_command(level: str, message: str) -> None:
    """Write Admin API command-service runtime messages through canonical logging."""

    log_method = getattr(logger, str(level).strip().lower(), logger.info)
    log_method(message)


class AdminApiFillFollowUpRuntimeExecutor:
    """Backend adapter for the existing filled-order follow-up engine path."""

    source = "dashboard_server.stealth_order_bridge.order_engine.handle_filled_order"

    def __init__(self, order_engine: Any) -> None:
        self.order_engine = order_engine

    def trigger_filled_follow_up(
        self,
        *,
        order: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        handle_filled_order = getattr(self.order_engine, "handle_filled_order", None)
        if not callable(handle_filled_order):
            raise RuntimeError("order_engine_handle_filled_order_unavailable")
        handle_filled_order(dict(order))
        client_order_id = str(order.get("client_order_id") or "")
        claim_state_after = None
        orderbook = getattr(self.order_engine, "orderbook", None)
        claim_state = getattr(orderbook, "follow_up_claim_state", None)
        if callable(claim_state) and client_order_id:
            claim_state_after = claim_state("filled", client_order_id)
        return {
            "status": "executed",
            "source": self.source,
            "client_order_id": client_order_id or None,
            "audit_correlation_id": context.get("audit_correlation_id"),
            "execution_scope": "local_stealth_follow_up",
            "exchange_submission_mode": "hidden_stealth_order_no_exchange_submit",
            "order_engine_handle_filled_order_called": True,
            "claim_acquired": claim_state_after in {"processing", "done"},
            "claim_state_after": claim_state_after,
            "coinbase_order_submit_ran": False,
            "coinbase_order_cancel_submitted": False,
            "live_coinbase_orders_ran": False,
            "live_exchange_submitted": False,
            "exchange_state_mutated": False,
        }


def get_admin_api_fill_follow_up_executor() -> Any | None:
    """Return the runtime fill-follow-up executor when the bridge is available."""

    try:
        import dashboard_server

        bridge = getattr(dashboard_server, "stealth_order_bridge", None)
        order_engine = getattr(bridge, "order_engine", None) if bridge else None
        handle_filled_order = getattr(order_engine, "handle_filled_order", None)
        if order_engine is None or not callable(handle_filled_order):
            return None
        return AdminApiFillFollowUpRuntimeExecutor(order_engine)
    except Exception as exc:
        logger.warning("Admin API fill follow-up executor unavailable: %s", exc)
        return None


def build_admin_api_command_dependencies(
    *,
    read_service_getter: Callable[[], Any | None] | None = None,
) -> AdminApiCommandDependencies:
    """Compose backend-owned dependencies for the shared Admin API command service."""

    live_runtime_enabled = admin_api_live_runtime_enabled()
    credentials_configured = rest_credentials_configured()
    rest_client = (
        load_admin_api_rest_client()
        if live_runtime_enabled and credentials_configured
        else AdminApiRestClientBinding(client=None, available=False)
    )
    if not live_runtime_enabled:
        missing_reason = "live_runtime_disabled"
    elif not credentials_configured:
        missing_reason = "coinbase_rest_credentials_missing"
    elif not rest_client.available:
        missing_reason = "coinbase_rest_client_unavailable"
    else:
        missing_reason = None
    return AdminApiCommandDependencies(
        rest_client=rest_client.client,
        rest_client_available=rest_client.available,
        live_runtime_enabled=live_runtime_enabled,
        command_runtime_ready=live_runtime_enabled and rest_client.available,
        command_runtime_missing_reason=missing_reason,
        runtime_controller_factory=get_runtime_controller,
        add_log_entry=log_admin_api_command,
        order_event_publisher_getter=get_admin_api_order_event_stream_publisher,
        fill_follow_up_executor_getter=get_admin_api_fill_follow_up_executor,
        read_service_getter=read_service_getter,
        uuid_factory=lambda: str(uuid.uuid4()),
    )


def build_admin_api_command_service(
    *,
    read_service_getter: Callable[[], Any | None] | None = None,
) -> AdminApiCommandService:
    """Build the route-facing Admin API command-service boundary."""

    return AdminApiCommandService(
        build_admin_api_command_dependencies(
            read_service_getter=read_service_getter
        )
    )
