"""Lifecycle-safe FastAPI server for the canonical engine process."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from threading import Event, Lock, Thread
from time import monotonic
from typing import Any, Callable, Mapping

from .command_runtime import get_admin_api_fill_follow_up_executor


logger = logging.getLogger(__name__)

EMBEDDED_ADMIN_API_ENABLED_ENV = "COINBASE_ADMIN_API_EMBEDDED_ENABLED"
EMBEDDED_ADMIN_API_HOST_ENV = "COINBASE_ADMIN_API_EMBEDDED_HOST"
EMBEDDED_ADMIN_API_PORT_ENV = "COINBASE_ADMIN_API_EMBEDDED_PORT"
DEFAULT_EMBEDDED_ADMIN_API_HOST = "127.0.0.1"
DEFAULT_EMBEDDED_ADMIN_API_PORT = 8787
DEFAULT_STARTUP_TIMEOUT_SECONDS = 10.0
DEFAULT_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = 30.0
DEFAULT_SHUTDOWN_TIMEOUT_SECONDS = 35.0
_ENABLED_VALUES = {"1", "true", "yes", "on"}
_DISABLED_VALUES = {"", "0", "false", "no", "off"}


class EmbeddedAdminApiStartupError(RuntimeError):
    """Raised when embedded Admin API startup cannot fail closed."""


class EmbeddedAdminApiShutdownError(RuntimeError):
    """Raised when embedded Admin API ingress does not stop in time."""


class EmbeddedAdminApiReadinessGate:
    """Allow reads while blocking mutations until live producers are ready."""

    _SAFE_HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

    def __init__(
        self,
        app: Any,
        *,
        mutation_readiness_check: Callable[[], bool] | None = None,
    ) -> None:
        self._app = app
        self._runtime_ready = Event()
        self._mutation_readiness_check = mutation_readiness_check

    @property
    def runtime_ready(self) -> bool:
        return self._runtime_ready.is_set()

    def mark_runtime_ready(self) -> None:
        self._runtime_ready.set()

    def mark_runtime_not_ready(self) -> None:
        self._runtime_ready.clear()

    @property
    def mutations_ready(self) -> bool:
        """Whether mutating routes may reach the canonical runtime now."""
        if not self.runtime_ready:
            return False
        if self._mutation_readiness_check is None:
            return True
        try:
            return bool(self._mutation_readiness_check())
        except Exception:
            logger.exception("Embedded Admin API mutation readiness check failed")
            return False

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        scope_type = scope.get("type")
        method = str(scope.get("method") or "").upper()
        if (
            self.mutations_ready
            or scope_type == "lifespan"
            or (scope_type == "http" and method in self._SAFE_HTTP_METHODS)
        ):
            await self._app(scope, receive, send)
            return
        if scope_type == "websocket":
            await send({"type": "websocket.close", "code": 1013})
            return
        if scope_type == "http":
            body = b'{"detail":"canonical_engine_runtime_not_ready"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self._app(scope, receive, send)


@dataclass(frozen=True, slots=True)
class EmbeddedAdminApiConfig:
    """Validated, single-process embedded server configuration."""

    host: str
    port: int
    workers: int = 1
    reload: bool = False
    graceful_shutdown_timeout_seconds: float = (
        DEFAULT_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS
    )


def _read_value(source: Mapping[str, str | None], key: str) -> str:
    value = source.get(key)
    return value.strip() if value else ""


def build_embedded_admin_api_config(
    *,
    environ: Mapping[str, str | None] | None = None,
) -> EmbeddedAdminApiConfig | None:
    """Return validated opt-in settings, or ``None`` when disabled."""

    source = os.environ if environ is None else environ
    enabled_value = _read_value(source, EMBEDDED_ADMIN_API_ENABLED_ENV).lower()
    if enabled_value in _DISABLED_VALUES:
        return None
    if enabled_value not in _ENABLED_VALUES:
        accepted = sorted(_ENABLED_VALUES | (_DISABLED_VALUES - {""}))
        raise EmbeddedAdminApiStartupError(
            f"{EMBEDDED_ADMIN_API_ENABLED_ENV} must be one of: "
            f"{', '.join(accepted)}"
        )

    from tools.run_admin_api import startup_auth_error_message

    auth_error = startup_auth_error_message(environ=source)
    if auth_error:
        raise EmbeddedAdminApiStartupError(auth_error)

    host = _read_value(source, EMBEDDED_ADMIN_API_HOST_ENV)
    host = host or DEFAULT_EMBEDDED_ADMIN_API_HOST
    raw_port = _read_value(source, EMBEDDED_ADMIN_API_PORT_ENV)
    try:
        port = int(raw_port or DEFAULT_EMBEDDED_ADMIN_API_PORT)
    except ValueError as exc:
        raise EmbeddedAdminApiStartupError(
            f"{EMBEDDED_ADMIN_API_PORT_ENV} must be an integer"
        ) from exc
    if not 1 <= port <= 65535:
        raise EmbeddedAdminApiStartupError(
            f"{EMBEDDED_ADMIN_API_PORT_ENV} must be between 1 and 65535"
        )
    return EmbeddedAdminApiConfig(host=host, port=port)


def _build_uvicorn_server(
    config: EmbeddedAdminApiConfig,
    app_gate: EmbeddedAdminApiReadinessGate,
) -> Any:
    import uvicorn

    uvicorn_config = uvicorn.Config(
        app=app_gate,
        host=config.host,
        port=config.port,
        reload=False,
        workers=1,
        timeout_graceful_shutdown=config.graceful_shutdown_timeout_seconds,
    )
    return uvicorn.Server(uvicorn_config)


class EmbeddedAdminApiServer:
    """Retained Uvicorn server handle with bounded start/stop semantics."""

    def __init__(
        self,
        server: Any,
        app_gate: EmbeddedAdminApiReadinessGate,
        *,
        startup_timeout_seconds: float,
        shutdown_timeout_seconds: float,
        unexpected_exit_callback: Callable[[BaseException | None], None] | None,
    ) -> None:
        if startup_timeout_seconds <= 0 or shutdown_timeout_seconds <= 0:
            raise EmbeddedAdminApiStartupError(
                "Embedded Admin API lifecycle timeouts must be positive"
            )
        self._server = server
        self._app_gate = app_gate
        self._startup_timeout_seconds = startup_timeout_seconds
        self._shutdown_timeout_seconds = shutdown_timeout_seconds
        self._thread: Thread | None = None
        self._thread_failure: BaseException | None = None
        self._finished = Event()
        self._stop_requested = Event()
        self._state_lock = Lock()
        self._unexpected_exit_callback = unexpected_exit_callback

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return bool(
            thread is not None
            and thread.is_alive()
            and getattr(self._server, "started", False)
            and not getattr(self._server, "should_exit", False)
        )

    @property
    def runtime_ready(self) -> bool:
        return self._app_gate.runtime_ready

    def _run(self) -> None:
        try:
            self._server.run()
        except BaseException as exc:
            self._thread_failure = exc
        finally:
            self._finished.set()
            if (
                not self._stop_requested.is_set()
                and self._unexpected_exit_callback is not None
            ):
                try:
                    self._unexpected_exit_callback(self._thread_failure)
                except Exception:
                    logger.exception(
                        "Embedded Admin API unexpected-exit callback failed"
                    )

    def start(self) -> None:
        """Start one server thread and wait until bind/readiness is known."""

        with self._state_lock:
            if self.is_running:
                return
            if self._thread is not None:
                raise EmbeddedAdminApiStartupError(
                    "Embedded Admin API server cannot be restarted"
                )
            self._thread = Thread(
                target=self._run,
                name="embedded-admin-api",
                daemon=False,
            )
            self._thread.start()

        deadline = monotonic() + self._startup_timeout_seconds
        while not getattr(self._server, "started", False):
            if self._finished.is_set():
                message = "Embedded Admin API server failed before startup"
                if self._thread_failure is not None:
                    raise EmbeddedAdminApiStartupError(message) from self._thread_failure
                raise EmbeddedAdminApiStartupError(message)
            remaining = deadline - monotonic()
            if remaining <= 0:
                self.stop()
                raise EmbeddedAdminApiStartupError(
                    "Embedded Admin API server startup timed out"
                )
            self._finished.wait(timeout=min(0.01, remaining))
        if not self.is_running or self._thread_failure is not None:
            message = "Embedded Admin API server failed after socket startup"
            if self._thread_failure is not None:
                raise EmbeddedAdminApiStartupError(message) from self._thread_failure
            raise EmbeddedAdminApiStartupError(message)
        logger.info("Embedded Admin API accepting requests")

    def mark_runtime_ready(self) -> None:
        """Open mutating routes only after all canonical producers started."""

        if not self.is_running or self._thread_failure is not None:
            raise EmbeddedAdminApiStartupError(
                "Embedded Admin API cannot become ready after server exit"
            )
        self._app_gate.mark_runtime_ready()
        logger.info("Embedded Admin API canonical runtime ready")

    def stop(self) -> None:
        """Stop ingress and join the retained server thread within a bound."""

        self._app_gate.mark_runtime_not_ready()
        self._stop_requested.set()
        thread = self._thread
        if thread is None or not thread.is_alive():
            return
        self._server.should_exit = True
        thread.join(timeout=self._shutdown_timeout_seconds)
        if thread.is_alive():
            self._server.force_exit = True
            thread.join(timeout=min(0.25, self._shutdown_timeout_seconds))
        if thread.is_alive():
            raise EmbeddedAdminApiShutdownError(
                "Embedded Admin API server did not stop within the shutdown timeout"
            )
        logger.info("Embedded Admin API stopped")


def prepare_embedded_admin_api_server(
    *,
    order_engine: Any,
    stealth_order_bridge: Any,
    stealth_order_manager: Any,
    runtime_ready: bool,
    environ: Mapping[str, str | None] | None = None,
    server_factory: Callable[
        [EmbeddedAdminApiConfig, EmbeddedAdminApiReadinessGate],
        Any,
    ] = _build_uvicorn_server,
    unexpected_exit_callback: Callable[[BaseException | None], None] | None = None,
    startup_timeout_seconds: float = DEFAULT_STARTUP_TIMEOUT_SECONDS,
    shutdown_timeout_seconds: float = DEFAULT_SHUTDOWN_TIMEOUT_SECONDS,
) -> EmbeddedAdminApiServer | None:
    """Prepare the server only for the exact registered canonical runtime."""

    config = build_embedded_admin_api_config(environ=environ)
    if config is None:
        return None
    if not runtime_ready:
        raise EmbeddedAdminApiStartupError(
            "Embedded Admin API canonical engine runtime is not ready"
        )

    import dashboard_server

    if getattr(dashboard_server, "stealth_order_bridge", None) is not stealth_order_bridge:
        raise EmbeddedAdminApiStartupError(
            "Embedded Admin API cannot prove the registered stealth bridge"
        )
    if getattr(stealth_order_bridge, "order_engine", None) is not order_engine:
        raise EmbeddedAdminApiStartupError(
            "Embedded Admin API bridge does not reference the canonical order engine"
        )
    if getattr(order_engine, "stealth_order_bridge", None) is not stealth_order_bridge:
        raise EmbeddedAdminApiStartupError(
            "Embedded Admin API engine does not reference the canonical stealth bridge"
        )
    if getattr(stealth_order_bridge, "stealth_manager", None) is not stealth_order_manager:
        raise EmbeddedAdminApiStartupError(
            "Embedded Admin API bridge does not reference the canonical stealth manager"
        )

    executor = get_admin_api_fill_follow_up_executor()
    if executor is None or getattr(executor, "order_engine", None) is not order_engine:
        raise EmbeddedAdminApiStartupError(
            "Embedded Admin API cannot resolve the canonical order engine executor"
        )
    if getattr(executor.order_engine, "orderbook", None) is not getattr(
        order_engine,
        "orderbook",
        None,
    ):
        raise EmbeddedAdminApiStartupError(
            "Embedded Admin API executor does not share canonical claim authority"
        )

    from api.v1.app import app

    monitoring_readiness_check = getattr(
        order_engine,
        "is_event_monitoring_ready",
        None,
    )
    if not callable(monitoring_readiness_check):
        monitoring_readiness_check = None
    app_gate = EmbeddedAdminApiReadinessGate(
        app,
        mutation_readiness_check=monitoring_readiness_check,
    )
    server = server_factory(config, app_gate)
    return EmbeddedAdminApiServer(
        server,
        app_gate,
        startup_timeout_seconds=startup_timeout_seconds,
        shutdown_timeout_seconds=shutdown_timeout_seconds,
        unexpected_exit_callback=unexpected_exit_callback,
    )
