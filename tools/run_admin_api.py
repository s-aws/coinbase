"""Run the local enterprise Admin API.

This helper starts the existing FastAPI app. Exact controlled-live startup may
hydrate backend-only credentials before the app is imported; startup itself
does not submit orders, cancel orders, or mutate exchange state.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
import os
import sys
from typing import Any

from core.enums import AdminApiAuthMode
from core.operator_follow_up_intent import operator_follow_up_intent_enabled
from core.runtime_controller import get_runtime_controller
from tools.coinbase_live_credentials import ensure_live_coinbase_credentials


APP_IMPORT_PATH = "api.v1.app:app"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_CORS_ORIGIN = "http://127.0.0.1:3000"
AUTH_MODE_ENV = "COINBASE_ADMIN_API_AUTH_MODE"
AUTH_TOKEN_ENV = "COINBASE_ADMIN_API_BEARER_TOKEN"
CORS_ORIGINS_ENV = "COINBASE_ADMIN_API_CORS_ORIGINS"
ENVIRONMENT_ENV = "COINBASE_ADMIN_API_ENVIRONMENT"
DEPLOYMENT_TIER_ENV = "COINBASE_BACKEND_DEPLOYMENT_TIER"
OS_TRUSTSTORE_ENV = "COINBASE_ADMIN_API_OS_TRUSTSTORE"
EXECUTION_AUTHORITY_ENV = "COINBASE_EXECUTION_ENABLED"
LIVE_RUNTIME_ENABLED_ENV = "COINBASE_ADMIN_API_LIVE_EXECUTION_ENABLED"
OPERATOR_AUTOMATION_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_AUTOMATION_ENABLED"
)
OPERATOR_PRODUCT_CATALOG_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_PRODUCT_CATALOG_ENABLED"
)
OPERATOR_PARENT_STRATEGIES_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_PARENT_STRATEGIES_ENABLED"
)
OPERATOR_STEALTH_DEFINITIONS_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_STEALTH_DEFINITIONS_ENABLED"
)
OPERATOR_HOTPOINT_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_HOTPOINT_ENABLED"
)
OPERATOR_SPOT_ORDER_TRUTH_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_SPOT_ORDER_TRUTH_ENABLED"
)
OPERATOR_PARENT_MOVE_PREMARK_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_PARENT_MOVE_PREMARK_ENABLED"
)
OPERATOR_SINGLE_ORDER_REPRICE_NOW_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_SINGLE_ORDER_REPRICE_NOW_ENABLED"
)
OPERATOR_SPOT_SAFE_CLOSEOUT_SWEEP_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_SPOT_SAFE_CLOSEOUT_SWEEP_ENABLED"
)
DISABLED_ENV_VALUES = {"0", "false", "no", "off", "disabled"}
ENABLED_ENV_VALUES = {"1", "true", "yes", "on"}
OIDC_REQUIRED_ENV_VARS = (
    "COINBASE_ADMIN_API_OIDC_ISSUER",
    "COINBASE_ADMIN_API_OIDC_AUDIENCE",
    "COINBASE_ADMIN_API_OIDC_JWKS_URL",
)
STARTUP_AUTH_MODE_VALUES = tuple(mode.value for mode in AdminApiAuthMode)
FOLLOW_UP_INTENT_SCHEMA_STARTUP_ERROR = (
    "Admin API follow-up intent schema initialization failed."
)
OPERATOR_AUTOMATION_SCHEMA_STARTUP_ERROR = (
    "Admin API operator automation schema initialization failed."
)
OPERATOR_PRODUCT_CATALOG_SCHEMA_STARTUP_ERROR = (
    "Admin API operator product catalog schema initialization failed."
)
OPERATOR_PARENT_STRATEGY_SCHEMA_STARTUP_ERROR = (
    "Admin API operator parent strategy schema initialization failed."
)
OPERATOR_STEALTH_DEFINITION_SCHEMA_STARTUP_ERROR = (
    "Admin API operator stealth definition schema initialization failed."
)
OPERATOR_HOTPOINT_SCHEMA_STARTUP_ERROR = (
    "Admin API operator Hotpoint schema initialization failed."
)
OPERATOR_SPOT_ORDER_TRUTH_SCHEMA_STARTUP_ERROR = (
    "Admin API operator Spot order truth schema initialization failed."
)
OPERATOR_PARENT_MOVE_PREMARK_SCHEMA_STARTUP_ERROR = (
    "Admin API operator parent move premark schema initialization failed."
)
OPERATOR_SINGLE_ORDER_REPRICE_NOW_SCHEMA_STARTUP_ERROR = (
    "Admin API operator single-order Reprice Now schema initialization "
    "failed."
)
OPERATOR_SPOT_SAFE_CLOSEOUT_SWEEP_SCHEMA_STARTUP_ERROR = (
    "Admin API operator Spot safe-closeout sweep schema initialization "
    "failed."
)


@dataclass(frozen=True)
class AdminApiRunConfig:
    """Validated local Admin API server settings."""

    app: str
    host: str
    port: int
    reload: bool
    cors_origins: tuple[str, ...]
    dev_token: str | None


def build_parser() -> argparse.ArgumentParser:
    """Create the local Admin API runner parser."""

    parser = argparse.ArgumentParser(
        description="Run the local Coinbase enterprise Admin API."
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Bind host. Defaults to {DEFAULT_HOST}.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Bind port. Defaults to {DEFAULT_PORT}.",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable uvicorn reload for local development.",
    )
    parser.add_argument(
        "--cors-origin",
        action="append",
        dest="cors_origins",
        help=(
            "Allowed browser origin. Can be repeated. Defaults to "
            f"{DEFAULT_CORS_ORIGIN}."
        ),
    )
    parser.add_argument(
        "--dev-token",
        help=(
            "Local-only Admin API bearer token to set when "
            f"{AUTH_TOKEN_ENV} is not already configured."
        ),
    )
    return parser


def parse_run_config(argv: Sequence[str] | None = None) -> AdminApiRunConfig:
    """Parse command-line arguments into a testable run config."""

    args = build_parser().parse_args(argv)
    cors_origins = tuple(args.cors_origins or (DEFAULT_CORS_ORIGIN,))
    return AdminApiRunConfig(
        app=APP_IMPORT_PATH,
        host=args.host,
        port=args.port,
        reload=args.reload,
        cors_origins=cors_origins,
        dev_token=args.dev_token,
    )


def parse_args(argv: Sequence[str] | None = None) -> AdminApiRunConfig:
    """Parse local runner arguments for frontend stack compatibility tests."""

    return parse_run_config(argv)


def apply_local_environment(
    config: AdminApiRunConfig,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> dict[str, str]:
    """Apply local runner environment defaults without overwriting secrets."""

    target = environ if environ is not None else os.environ
    applied: dict[str, str] = {}

    if target.get(OS_TRUSTSTORE_ENV, "").strip().lower() in DISABLED_ENV_VALUES:
        applied[OS_TRUSTSTORE_ENV] = "disabled"
    else:
        truststore_status = enable_os_truststore()
        target[OS_TRUSTSTORE_ENV] = truststore_status
        applied[OS_TRUSTSTORE_ENV] = truststore_status

    if config.dev_token and not target.get(AUTH_TOKEN_ENV, "").strip():
        target[AUTH_TOKEN_ENV] = config.dev_token
        applied[AUTH_TOKEN_ENV] = "set_from_dev_token"

    if config.cors_origins:
        target[CORS_ORIGINS_ENV] = ",".join(config.cors_origins)
        applied[CORS_ORIGINS_ENV] = target[CORS_ORIGINS_ENV]

    if not target.get(ENVIRONMENT_ENV, "").strip():
        environment = resolve_admin_api_environment(target)
        target[ENVIRONMENT_ENV] = environment
        applied[ENVIRONMENT_ENV] = environment

    return applied


def prepare_live_coinbase_credentials(
    *,
    environ: MutableMapping[str, str] | None = None,
    credential_hydrator: Callable[[MutableMapping[str, str]], Any] = (
        ensure_live_coinbase_credentials
    ),
) -> str:
    """Hydrate backend credentials only for exact controlled-live startup."""

    target = environ if environ is not None else os.environ
    exact_authority = target.get(EXECUTION_AUTHORITY_ENV, "") == "1"
    internal_runtime_enabled = (
        target.get(LIVE_RUNTIME_ENABLED_ENV, "").strip().lower()
        in ENABLED_ENV_VALUES
    )
    if not (exact_authority and internal_runtime_enabled):
        return "disabled"
    resolution = credential_hydrator(target)
    return str(getattr(resolution, "source", "configured") or "configured")


def enable_os_truststore() -> str:
    """Enable OS certificate verification for local Coinbase REST reads."""

    try:
        import truststore
    except Exception:
        return "unavailable"
    try:
        truststore.inject_into_ssl()
    except Exception:
        return "failed"
    return "enabled"


def build_uvicorn_kwargs(config: AdminApiRunConfig) -> dict[str, Any]:
    """Return uvicorn keyword arguments for the Admin API app."""

    return {
        "app": config.app,
        "host": config.host,
        "port": config.port,
        "reload": config.reload,
        "workers": 1,
    }


def run_uvicorn_server(config: AdminApiRunConfig) -> None:
    """Serve with a retained ingress handle for queued runtime shutdown."""

    import uvicorn

    kwargs = build_uvicorn_kwargs(config)
    if config.reload:
        # Uvicorn owns the reload supervisor and its child-process lifecycle.
        uvicorn.run(**kwargs)
        return

    server = uvicorn.Server(uvicorn.Config(**kwargs))

    def stop_admin_api_ingress() -> None:
        server.should_exit = True

    get_runtime_controller().register_stop_hook(
        "admin_api",
        stop_admin_api_ingress,
    )
    server.run()


def _read_env_value(source: Mapping[str, str | None], key: str) -> str | None:
    value = source.get(key)
    value = value.strip() if value else ""
    return value or None


def resolve_admin_api_environment(source: Mapping[str, str | None]) -> str:
    """Return the operator-visible Admin API environment label."""

    return (
        _read_env_value(source, ENVIRONMENT_ENV)
        or _read_env_value(source, DEPLOYMENT_TIER_ENV)
        or "local"
    )


def _configured_auth_mode_value(source: Mapping[str, str | None]) -> str:
    return (
        _read_env_value(source, AUTH_MODE_ENV)
        or AdminApiAuthMode.BOOTSTRAP_BEARER.value
    )


def missing_startup_auth_env_vars(
    *,
    environ: Mapping[str, str | None] | None = None,
) -> tuple[str, ...]:
    """Return missing auth settings required before the Admin API can start."""

    source = os.environ if environ is None else environ
    auth_mode = _configured_auth_mode_value(source)
    if auth_mode == AdminApiAuthMode.BOOTSTRAP_BEARER.value:
        return () if _read_env_value(source, AUTH_TOKEN_ENV) else (AUTH_TOKEN_ENV,)
    if auth_mode == AdminApiAuthMode.OIDC_JWT.value:
        return tuple(
            key for key in OIDC_REQUIRED_ENV_VARS if not _read_env_value(source, key)
        )
    return (AUTH_MODE_ENV,)


def startup_auth_error_message(
    *,
    environ: Mapping[str, str | None] | None = None,
) -> str | None:
    """Return a startup auth error message, or None when auth is configured."""

    source = os.environ if environ is None else environ
    auth_mode = _configured_auth_mode_value(source)
    if auth_mode not in STARTUP_AUTH_MODE_VALUES:
        return (
            f"{AUTH_MODE_ENV} must be one of "
            f"{', '.join(STARTUP_AUTH_MODE_VALUES)}."
        )

    missing_env_vars = missing_startup_auth_env_vars(environ=source)
    if not missing_env_vars:
        return None
    if missing_env_vars == (AUTH_TOKEN_ENV,):
        return (
            f"{AUTH_TOKEN_ENV} is required. Set it in the environment or pass "
            "--dev-token for local-only development."
        )
    return (
        "Admin API OIDC/JWT startup auth is not configured. Missing: "
        f"{', '.join(missing_env_vars)}."
    )


def initialize_order_follow_up_intent_schema() -> None:
    """Create the durable single-slot follow-up-intent schema before serving."""

    from database.order_follow_up_intent import (
        create_order_follow_up_intent_tables,
    )
    from database.operator_fill_triggered_follow_up_activation import (
        create_operator_fill_triggered_follow_up_activation_tables,
    )

    create_order_follow_up_intent_tables()
    create_operator_fill_triggered_follow_up_activation_tables()


def initialize_operator_automation_schema() -> None:
    """Create the durable operator automation schema before serving."""

    from database.operator_automation import (
        initialize_operator_automation_schema as initialize_schema,
    )

    initialize_schema()


def initialize_operator_hotpoint_schema() -> None:
    """Create and recover the bounded Hotpoint control schema."""

    from database.operator_hotpoint_control import (
        initialize_operator_hotpoint_control_schema,
    )

    initialize_operator_hotpoint_control_schema()


def initialize_operator_product_catalog_schema() -> None:
    """Create and recover the Product Catalog schema before serving."""

    from database.operator_product_catalog import (
        initialize_operator_product_catalog_schema as initialize_schema,
    )

    initialize_schema()


def initialize_operator_parent_strategy_schema() -> None:
    """Create the durable parent-strategy schema before serving."""

    from database.operator_parent_strategy import (
        initialize_operator_parent_strategy_schema as initialize_schema,
    )

    initialize_schema()


def initialize_operator_stealth_definition_schema() -> None:
    """Create the durable local stealth-definition schema before serving."""

    from database.operator_stealth_definition import (
        initialize_operator_stealth_definition_schema as initialize_schema,
    )

    initialize_schema()


def initialize_operator_spot_order_truth_schema() -> None:
    """Create and recover the Goal 12 Spot order-truth schema."""

    from database.operator_spot_order_truth import (
        get_default_operator_spot_order_truth_repository,
    )

    get_default_operator_spot_order_truth_repository().ensure_schema()


def initialize_operator_parent_move_premark_schema() -> None:
    """Create and recover the Goal 14 parent-move ledger."""

    from application.admin_api.operator_parent_move_premark_runtime import (
        initialize_operator_parent_move_premark_runtime as initialize_runtime,
    )

    initialize_runtime()


def initialize_operator_single_order_reprice_now_schema() -> None:
    """Create the call-free Goal 15 Reprice Now intent ledger."""

    from database.operator_single_order_reprice_now import (
        initialize_operator_single_order_reprice_now_schema as initialize_schema,
    )

    initialize_schema()


def initialize_operator_spot_safe_closeout_sweep_runtime() -> None:
    """Create and recover the call-free Goal 16 sweep ledger."""

    from application.admin_api.operator_spot_safe_closeout_sweep_runtime import (
        initialize_operator_spot_safe_closeout_sweep_runtime as initialize,
    )

    initialize()


def main(argv: Sequence[str] | None = None) -> int:
    """Run the local Admin API server."""

    config = parse_run_config(argv)
    apply_local_environment(config)

    auth_error = startup_auth_error_message()
    if auth_error:
        print(auth_error, file=sys.stderr)
        return 2

    try:
        credential_source = prepare_live_coinbase_credentials()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if operator_follow_up_intent_enabled():
        try:
            initialize_order_follow_up_intent_schema()
        except Exception:
            print(FOLLOW_UP_INTENT_SCHEMA_STARTUP_ERROR, file=sys.stderr)
            return 2

    if os.environ.get(OPERATOR_AUTOMATION_ENABLED_ENV) == "1":
        try:
            initialize_operator_automation_schema()
        except Exception:
            print(OPERATOR_AUTOMATION_SCHEMA_STARTUP_ERROR, file=sys.stderr)
            return 2

    if os.environ.get(OPERATOR_HOTPOINT_ENABLED_ENV) == "1":
        try:
            initialize_operator_hotpoint_schema()
        except Exception:
            print(OPERATOR_HOTPOINT_SCHEMA_STARTUP_ERROR, file=sys.stderr)
            return 2

    if os.environ.get(OPERATOR_SPOT_ORDER_TRUTH_ENABLED_ENV) == "1":
        try:
            initialize_operator_spot_order_truth_schema()
        except Exception:
            print(
                OPERATOR_SPOT_ORDER_TRUTH_SCHEMA_STARTUP_ERROR,
                file=sys.stderr,
            )
            return 2

    if os.environ.get(OPERATOR_PARENT_MOVE_PREMARK_ENABLED_ENV) == "1":
        try:
            initialize_operator_parent_move_premark_schema()
        except Exception:
            print(
                OPERATOR_PARENT_MOVE_PREMARK_SCHEMA_STARTUP_ERROR,
                file=sys.stderr,
            )
            return 2

    if (
        os.environ.get(OPERATOR_SINGLE_ORDER_REPRICE_NOW_ENABLED_ENV)
        == "1"
    ):
        try:
            initialize_operator_single_order_reprice_now_schema()
        except Exception:
            print(
                OPERATOR_SINGLE_ORDER_REPRICE_NOW_SCHEMA_STARTUP_ERROR,
                file=sys.stderr,
            )
            return 2

    if (
        os.environ.get(OPERATOR_SPOT_SAFE_CLOSEOUT_SWEEP_ENABLED_ENV)
        == "1"
    ):
        try:
            initialize_operator_spot_safe_closeout_sweep_runtime()
        except Exception:
            print(
                OPERATOR_SPOT_SAFE_CLOSEOUT_SWEEP_SCHEMA_STARTUP_ERROR,
                file=sys.stderr,
            )
            return 2

    if os.environ.get(OPERATOR_PRODUCT_CATALOG_ENABLED_ENV) == "1":
        try:
            initialize_operator_product_catalog_schema()
        except Exception:
            print(
                OPERATOR_PRODUCT_CATALOG_SCHEMA_STARTUP_ERROR,
                file=sys.stderr,
            )
            return 2

    if os.environ.get(OPERATOR_PARENT_STRATEGIES_ENABLED_ENV) == "1":
        try:
            initialize_operator_parent_strategy_schema()
        except Exception:
            print(
                OPERATOR_PARENT_STRATEGY_SCHEMA_STARTUP_ERROR,
                file=sys.stderr,
            )
            return 2

    if os.environ.get(OPERATOR_STEALTH_DEFINITIONS_ENABLED_ENV) == "1":
        try:
            initialize_operator_stealth_definition_schema()
        except Exception:
            print(
                OPERATOR_STEALTH_DEFINITION_SCHEMA_STARTUP_ERROR,
                file=sys.stderr,
            )
            return 2

    try:
        import uvicorn
    except ModuleNotFoundError:
        print(
            "uvicorn is required to run the Admin API locally. Install the "
            "project development dependencies, then retry.",
            file=sys.stderr,
        )
        return 2

    execution_posture = (
        "disabled"
        if credential_source == "disabled"
        else f"enabled with backend credential source {credential_source}"
    )
    print(
        "Starting Coinbase Admin API at "
        f"http://{config.host}:{config.port}; controlled-live authority is "
        f"{execution_posture}."
    )
    run_uvicorn_server(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
