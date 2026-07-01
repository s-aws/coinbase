"""Run the local enterprise Admin API.

This helper is intentionally limited to starting the existing FastAPI app. It
does not import trading clients, submit orders, cancel orders, or mutate
exchange state.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
import os
import sys
from typing import Any

from core.enums import AdminApiAuthMode


APP_IMPORT_PATH = "api.v1.app:app"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_CORS_ORIGIN = "http://127.0.0.1:3000"
AUTH_MODE_ENV = "COINBASE_ADMIN_API_AUTH_MODE"
AUTH_TOKEN_ENV = "COINBASE_ADMIN_API_BEARER_TOKEN"
CORS_ORIGINS_ENV = "COINBASE_ADMIN_API_CORS_ORIGINS"
ENVIRONMENT_ENV = "COINBASE_ADMIN_API_ENVIRONMENT"
DEPLOYMENT_TIER_ENV = "COINBASE_BACKEND_DEPLOYMENT_TIER"
OIDC_REQUIRED_ENV_VARS = (
    "COINBASE_ADMIN_API_OIDC_ISSUER",
    "COINBASE_ADMIN_API_OIDC_AUDIENCE",
    "COINBASE_ADMIN_API_OIDC_JWKS_URL",
)
STARTUP_AUTH_MODE_VALUES = tuple(mode.value for mode in AdminApiAuthMode)


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


def apply_local_environment(
    config: AdminApiRunConfig,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> dict[str, str]:
    """Apply local runner environment defaults without overwriting secrets."""

    target = environ if environ is not None else os.environ
    applied: dict[str, str] = {}

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


def build_uvicorn_kwargs(config: AdminApiRunConfig) -> dict[str, Any]:
    """Return uvicorn keyword arguments for the Admin API app."""

    return {
        "app": config.app,
        "host": config.host,
        "port": config.port,
        "reload": config.reload,
    }


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


def main(argv: Sequence[str] | None = None) -> int:
    """Run the local Admin API server."""

    config = parse_run_config(argv)
    apply_local_environment(config)

    auth_error = startup_auth_error_message()
    if auth_error:
        print(auth_error, file=sys.stderr)
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

    print(
        "Starting Coinbase Admin API at "
        f"http://{config.host}:{config.port}; live Coinbase execution is disabled."
    )
    uvicorn.run(**build_uvicorn_kwargs(config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
