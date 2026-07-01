"""Runtime dependency composition for Admin API command services."""

from __future__ import annotations

from dataclasses import dataclass
import os
from threading import Lock
from typing import Any
import uuid

from core.action_condition_guard import rest_credentials_configured
from core.runtime_controller import get_runtime_controller
from logging_service import get_logger

from .command_service import AdminApiCommandDependencies, AdminApiCommandService
from .live_execution import LIVE_EXECUTION_RUNTIME_ENABLED_ENV


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


def build_admin_api_command_dependencies() -> AdminApiCommandDependencies:
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
        uuid_factory=lambda: str(uuid.uuid4()),
    )


def build_admin_api_command_service() -> AdminApiCommandService:
    """Build the route-facing Admin API command-service boundary."""

    return AdminApiCommandService(build_admin_api_command_dependencies())
