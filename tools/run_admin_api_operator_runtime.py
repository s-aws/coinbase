"""Start the controlled-live Admin API with dormant canonical dependencies.

This is the installed controlled-live entrypoint. It validates the exact outer
execution authority and manager lease, hydrates backend-only credentials, and
constructs the canonical order root registrar plus durable event publisher.
It deliberately does not start the legacy order engine, stealth bridge,
websocket, reveal, reprice, re-entry, hotpoint, or follow-up loops. Operator
place/cancel requests remain synchronous, route-scoped, and guarded by the
Admin API proof chain.
"""

from __future__ import annotations

from collections.abc import Callable, MutableMapping, Sequence
from dataclasses import dataclass
import os
import sys
from typing import Any
import uuid

from application.admin_api.spot_portfolio_binding import (
    DEFAULT_SPOT_PORTFOLIO_LABEL,
    SPOT_PORTFOLIO_ID_ENV,
    SPOT_PORTFOLIO_LABEL_ENV,
)
from application.admin_api.futures_default_rest_client import (
    FuturesDefaultRestClientError,
    configure_futures_default_rest_client,
    validate_coinbase_domain_credential_bindings,
)
from core.coinbase_execution_authority import (
    COINBASE_EXECUTION_LEASE_PATH_ENV,
    COINBASE_EXECUTION_LEASE_TOKEN_ENV,
    CoinbaseExecutionAuthorityError,
    coinbase_execution_authority_enabled,
)
from tools.coinbase_live_credentials import ensure_live_coinbase_credentials
from tools.run_admin_api import (
    AdminApiRunConfig,
    OPERATOR_AUTOMATION_ENABLED_ENV,
    OPERATOR_HOTPOINT_ENABLED_ENV,
    OPERATOR_PRODUCT_CATALOG_ENABLED_ENV,
    OPERATOR_PARENT_STRATEGIES_ENABLED_ENV,
    OPERATOR_SPOT_ORDER_TRUTH_ENABLED_ENV,
    OPERATOR_STEALTH_DEFINITIONS_ENABLED_ENV,
    apply_local_environment,
    initialize_operator_automation_schema,
    initialize_operator_hotpoint_schema,
    initialize_operator_product_catalog_schema,
    initialize_operator_parent_strategy_schema,
    initialize_operator_spot_order_truth_schema,
    initialize_operator_stealth_definition_schema,
    parse_run_config,
    prepare_live_coinbase_credentials,
    run_uvicorn_server,
    startup_auth_error_message,
)


class OperatorAdminRuntimeError(RuntimeError):
    """Fixed-diagnostic controlled-live operator startup failure."""


_FIXED_STARTUP_DIAGNOSTICS = frozenset(
    {
        "operator_admin_auth_missing",
        "operator_automation_schema_init_failed",
        "operator_canonical_runtime_incomplete",
        "operator_command_runtime_not_ready",
        "operator_execution_lease_missing",
        "operator_futures_hotpoint_default_portfolio_invalid",
        "operator_futures_hotpoint_default_portfolio_required",
        "operator_futures_hotpoint_v2_init_failed",
        "operator_hotpoint_gate_unavailable",
        "operator_hotpoint_schema_init_failed",
        "operator_live_runtime_disabled",
        "operator_parent_strategy_schema_init_failed",
        "operator_product_catalog_schema_init_failed",
        "operator_runtime_reload_forbidden",
        "operator_spot_order_truth_schema_init_failed",
        "operator_spot_portfolio_label_invalid",
        "operator_spot_portfolio_scope_missing",
        "operator_spot_products_missing",
        "operator_stealth_definition_schema_init_failed",
    }
)


def _startup_failure_diagnostic(exc: Exception) -> str:
    """Return only an allowlisted fixed startup diagnostic or its exception type."""

    if isinstance(exc, OperatorAdminRuntimeError):
        diagnostic = str(exc)
        if diagnostic in _FIXED_STARTUP_DIAGNOSTICS:
            return diagnostic
    return type(exc).__name__


@dataclass(frozen=True, slots=True)
class PreparedOperatorRuntime:
    host: str
    port: int
    credential_source: str
    config: AdminApiRunConfig


def prepare_operator_runtime(
    argv: Sequence[str] | None = None,
    *,
    environ: MutableMapping[str, str] | None = None,
    credential_hydrator: Callable[[MutableMapping[str, str]], Any] = (
        ensure_live_coinbase_credentials
    ),
    futures_client_preparer: Callable[
        [MutableMapping[str, str]], Any
    ] = configure_futures_default_rest_client,
) -> PreparedOperatorRuntime:
    """Validate and prepare one canonical embedded operator runtime."""

    target = os.environ if environ is None else environ
    config: AdminApiRunConfig = parse_run_config(argv)
    if config.reload:
        raise OperatorAdminRuntimeError("operator_runtime_reload_forbidden")

    if not str(target.get(COINBASE_EXECUTION_LEASE_PATH_ENV) or "").strip() or not str(
        target.get(COINBASE_EXECUTION_LEASE_TOKEN_ENV) or ""
    ).strip():
        raise OperatorAdminRuntimeError("operator_execution_lease_missing")

    # The installed operator entrypoint always requires the manager-owned
    # lease in addition to the exact case-sensitive outer value.
    if not coinbase_execution_authority_enabled(target):
        raise CoinbaseExecutionAuthorityError(
            "coinbase_execution_authority_missing"
        )
    if not str(target.get(SPOT_PORTFOLIO_ID_ENV) or "").strip():
        raise OperatorAdminRuntimeError("operator_spot_portfolio_scope_missing")
    configured_label = str(target.get(SPOT_PORTFOLIO_LABEL_ENV) or "").strip()
    if configured_label and configured_label != DEFAULT_SPOT_PORTFOLIO_LABEL:
        raise OperatorAdminRuntimeError("operator_spot_portfolio_label_invalid")
    target[SPOT_PORTFOLIO_LABEL_ENV] = DEFAULT_SPOT_PORTFOLIO_LABEL

    apply_local_environment(config, environ=target)
    auth_error = startup_auth_error_message(environ=target)
    if auth_error:
        raise OperatorAdminRuntimeError("operator_admin_auth_missing")

    futures_hotpoint_v2_enabled = (
        target.get(
            "COINBASE_ADMIN_API_OPERATOR_FUTURES_HOTPOINT_V2_ENABLED"
        )
        == "1"
    )
    futures_enabled = (
        target.get("COINBASE_ADMIN_API_OPERATOR_FUTURES_MANUAL_ENABLED")
        == "1"
        or target.get(
            "COINBASE_ADMIN_API_OPERATOR_FUTURES_POSITION_ENABLED"
        )
        == "1"
        or target.get(
            "COINBASE_ADMIN_API_OPERATOR_FUTURES_PRODUCT_TICKET_ENABLED"
        )
        == "1"
        or futures_hotpoint_v2_enabled
    )
    if futures_hotpoint_v2_enabled:
        portfolio_id = str(
            target.get("COINBASE_ADMIN_API_FUTURES_PORTFOLIO_ID")
            or ""
        ).strip()
        if not portfolio_id:
            raise OperatorAdminRuntimeError(
                "operator_futures_hotpoint_default_portfolio_required"
            )
        try:
            uuid.UUID(portfolio_id)
        except (AttributeError, TypeError, ValueError):
            raise OperatorAdminRuntimeError(
                "operator_futures_hotpoint_default_portfolio_invalid"
            ) from None
    if futures_enabled:
        try:
            validate_coinbase_domain_credential_bindings(target)
        except FuturesDefaultRestClientError as exc:
            raise OperatorAdminRuntimeError(str(exc)) from None

    credential_source = prepare_live_coinbase_credentials(
        environ=target,
        credential_hydrator=credential_hydrator,
    )
    if credential_source == "disabled":
        raise OperatorAdminRuntimeError("operator_live_runtime_disabled")
    if futures_enabled:
        try:
            futures_client_preparer(target)
        except FuturesDefaultRestClientError as exc:
            raise OperatorAdminRuntimeError(str(exc)) from None

    return PreparedOperatorRuntime(
        host=config.host,
        port=config.port,
        credential_source=credential_source,
        config=config,
    )


def compose_canonical_operator_runtime(
    *,
    environ: MutableMapping[str, str] | None = None,
    configuration_module: Any | None = None,
    db_module: Any | None = None,
    runtime_builder: Callable[..., Any] | None = None,
    bridge_setter: Callable[[Any], None] | None = None,
    runtime_hydrator: Callable[[Any], None] | None = None,
    readiness_builder: Callable[[], Any] | None = None,
) -> Any:
    """Compose route-scoped command dependencies without autonomous loops."""

    target = os.environ if environ is None else environ
    if configuration_module is None:
        import configuration as configuration_module
    if db_module is None:
        import database.order as db_module
    if runtime_builder is None:
        from core.runtime_composition import build_canonical_order_runtime

        runtime_builder = build_canonical_order_runtime
    if bridge_setter is None:
        from dashboard_server import set_stealth_order_bridge

        bridge_setter = set_stealth_order_bridge
    if runtime_hydrator is None:
        from core.runtime_composition import hydrate_canonical_order_runtime

        runtime_hydrator = hydrate_canonical_order_runtime
    if readiness_builder is None:
        from application.admin_api.command_runtime import (
            build_admin_api_command_runtime_readiness,
        )

        readiness_builder = build_admin_api_command_runtime_readiness

    configured_portfolio_id = str(target.get(SPOT_PORTFOLIO_ID_ENV) or "").strip()
    if not configured_portfolio_id:
        raise OperatorAdminRuntimeError("operator_spot_portfolio_scope_missing")
    product_ids = [
        product_id
        for product_id in configuration_module.Subscription.product_ids
        if product_id
        not in configuration_module.Subscription.derivatives_product_ids
    ]
    if not product_ids:
        raise OperatorAdminRuntimeError("operator_spot_products_missing")

    subscription = type(
        "OperatorAdminSpotSubscription",
        (),
        {
            "product_ids": product_ids,
            "derivatives_product_ids": [],
            # This is configuration only. Exact CDP-key permission/catalog
            # binding is intentionally deferred to each admitted operator
            # action and runs before its exchange mutation.
            "retail_portfolio_id": configured_portfolio_id,
            # No engine/websocket worker is started by this process. Keeping
            # channels empty makes accidental engine startup inert by default.
            "channels": [],
        },
    )
    runtime = runtime_builder(
        orderbook=configuration_module.ORDERBOOK,
        db_module=db_module,
        subscription=subscription,
        api_key=configuration_module.API_KEY,
        api_secret=configuration_module.API_SECRET,
        order_post_only=configuration_module.ORDER_POST_ONLY,
        require_stealth_bridge=True,
    )
    engine = getattr(runtime, "order_engine", None)
    bridge = getattr(runtime, "stealth_order_bridge", None)
    manager = getattr(runtime, "stealth_order_manager", None)
    if engine is None or bridge is None or manager is None:
        raise OperatorAdminRuntimeError("operator_canonical_runtime_incomplete")
    disable_hotpoint = getattr(engine, "set_hotpoint_auto_place_enabled", None)
    if not callable(disable_hotpoint):
        raise OperatorAdminRuntimeError("operator_hotpoint_gate_unavailable")
    disable_hotpoint(False)
    bridge_setter(bridge)
    runtime_hydrator(runtime)

    readiness = readiness_builder()
    if getattr(readiness, "runtime_ready", False) is not True:
        raise OperatorAdminRuntimeError("operator_command_runtime_not_ready")
    return runtime


def _run_admin_server(config: AdminApiRunConfig) -> None:
    run_uvicorn_server(config)


def initialize_operator_futures_hotpoint_v2_runtime() -> None:
    """Construct and recover exact Goal 13 dependencies before serving."""

    from application.admin_api.operator_hotpoint_runtime import (
        initialize_operator_futures_hotpoint_v2_runtime as initialize,
    )

    initialize()


def initialize_enabled_operator_schemas(
    *,
    environ: MutableMapping[str, str] | None = None,
) -> None:
    """Initialize enabled durable operator schemas before serving traffic."""

    target = os.environ if environ is None else environ
    if target.get(OPERATOR_AUTOMATION_ENABLED_ENV) == "1":
        try:
            initialize_operator_automation_schema()
        except Exception:
            raise OperatorAdminRuntimeError(
                "operator_automation_schema_init_failed"
            ) from None
    if target.get(OPERATOR_HOTPOINT_ENABLED_ENV) == "1":
        try:
            initialize_operator_hotpoint_schema()
        except Exception:
            raise OperatorAdminRuntimeError(
                "operator_hotpoint_schema_init_failed"
            ) from None
    if (
        target.get(
            "COINBASE_ADMIN_API_OPERATOR_FUTURES_HOTPOINT_V2_ENABLED"
        )
        == "1"
    ):
        try:
            initialize_operator_futures_hotpoint_v2_runtime()
        except Exception:
            raise OperatorAdminRuntimeError(
                "operator_futures_hotpoint_v2_init_failed"
            ) from None
    if target.get(OPERATOR_PRODUCT_CATALOG_ENABLED_ENV) == "1":
        try:
            initialize_operator_product_catalog_schema()
        except Exception:
            raise OperatorAdminRuntimeError(
                "operator_product_catalog_schema_init_failed"
            ) from None
    if target.get(OPERATOR_PARENT_STRATEGIES_ENABLED_ENV) == "1":
        try:
            initialize_operator_parent_strategy_schema()
        except Exception:
            raise OperatorAdminRuntimeError(
                "operator_parent_strategy_schema_init_failed"
            ) from None
    if target.get(OPERATOR_STEALTH_DEFINITIONS_ENABLED_ENV) == "1":
        try:
            initialize_operator_stealth_definition_schema()
        except Exception:
            raise OperatorAdminRuntimeError(
                "operator_stealth_definition_schema_init_failed"
            ) from None
    if target.get(OPERATOR_SPOT_ORDER_TRUTH_ENABLED_ENV) == "1":
        try:
            initialize_operator_spot_order_truth_schema()
        except Exception:
            raise OperatorAdminRuntimeError(
                "operator_spot_order_truth_schema_init_failed"
            ) from None


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: MutableMapping[str, str] | None = None,
    credential_hydrator: Callable[[MutableMapping[str, str]], Any] = (
        ensure_live_coinbase_credentials
    ),
    runtime_composer: Callable[[], Any] | None = None,
    server_runner: Callable[[AdminApiRunConfig], None] = _run_admin_server,
) -> int:
    """Prepare and serve the route-scoped runtime with value-blind failures."""

    try:
        prepared = prepare_operator_runtime(
            argv,
            environ=environ,
            credential_hydrator=credential_hydrator,
        )
        initialize_enabled_operator_schemas(environ=environ)
        if runtime_composer is None:
            compose_canonical_operator_runtime(environ=environ)
        else:
            runtime_composer()
        print(
            "Starting route-scoped Coinbase operator Admin API at "
            f"http://{prepared.host}:{prepared.port}; autonomous trading "
            "loops are disabled."
        )
        server_runner(prepared.config)
    except Exception as exc:
        print(
            "operator_admin_runtime_startup_failed:"
            f"{_startup_failure_diagnostic(exc)}",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
