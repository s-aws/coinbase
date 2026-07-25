"""Backend-only Coinbase Default-profile client for Futures workflows.

The installed operator runtime hydrates the Spot/Test credential into the
process environment for the canonical Spot runtime. Futures must never inherit
that credential. This module constructs and retains a second client from the
explicit canonical Default secret while ignoring direct Coinbase credentials
and generic Spot secret selection already present in the process.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import os
from threading import Lock
from typing import Any

from tools.coinbase_live_credentials import (
    CoinbaseCredentialResolution,
    resolve_live_coinbase_credentials,
)


FUTURES_DEFAULT_SECRET_ID = "coinbase"
FUTURES_DEFAULT_REGION = "us-east-1"
SPOT_TEST_SECRET_ID = "coinbase/Test"
SPOT_SECRET_ID_ENV = "COINBASE_SPOT_SECRETS_MANAGER_SECRET_ID"
SPOT_SECRET_REGION_ENV = "COINBASE_SPOT_SECRETS_MANAGER_REGION"
FUTURES_SECRET_ID_ENV = "COINBASE_FUTURES_SECRETS_MANAGER_SECRET_ID"
FUTURES_SECRET_REGION_ENV = "COINBASE_FUTURES_SECRETS_MANAGER_REGION"
FUTURES_REST_TIMEOUT_SECONDS = 10


class FuturesDefaultRestClientError(RuntimeError):
    """Fixed-diagnostic failure at the domain credential/client boundary."""


_CLIENT: Any | None = None
_CLIENT_LOCK = Lock()


def _text(value: object) -> str:
    return str(value or "").strip()


def validate_coinbase_domain_credential_bindings(
    environ: Mapping[str, str],
) -> None:
    """Require exact, distinct installed Spot/Test and Futures/Default bindings."""

    spot_secret_id = _text(environ.get(SPOT_SECRET_ID_ENV))
    futures_secret_id = _text(environ.get(FUTURES_SECRET_ID_ENV))
    if not futures_secret_id:
        raise FuturesDefaultRestClientError(
            "operator_futures_default_credential_binding_missing"
        )
    if spot_secret_id and spot_secret_id == futures_secret_id:
        raise FuturesDefaultRestClientError(
            "operator_coinbase_domain_credential_bindings_conflated"
        )
    if futures_secret_id != FUTURES_DEFAULT_SECRET_ID:
        raise FuturesDefaultRestClientError(
            "operator_futures_default_credential_binding_invalid"
        )
    if spot_secret_id != SPOT_TEST_SECRET_ID:
        raise FuturesDefaultRestClientError(
            "operator_spot_test_credential_binding_invalid"
        )
    if (
        _text(environ.get(FUTURES_SECRET_REGION_ENV))
        != FUTURES_DEFAULT_REGION
        or _text(environ.get(SPOT_SECRET_REGION_ENV))
        != FUTURES_DEFAULT_REGION
    ):
        raise FuturesDefaultRestClientError(
            "operator_coinbase_domain_credential_region_invalid"
        )


def _controlled_futures_credential_environment(
    environ: Mapping[str, str],
) -> dict[str, str]:
    """Select only AWS context plus the explicit Futures Default binding."""

    controlled = {
        str(name): str(value)
        for name, value in environ.items()
        if str(name).startswith("AWS_") and _text(value)
    }
    controlled["COINBASE_SECRETS_MANAGER_SECRET_ID"] = (
        _text(environ.get(FUTURES_SECRET_ID_ENV))
    )
    controlled["COINBASE_SECRETS_MANAGER_REGION"] = (
        _text(environ.get(FUTURES_SECRET_REGION_ENV))
    )
    return controlled


def build_futures_default_rest_client(
    *,
    environ: Mapping[str, str] | None = None,
    credential_resolver: Callable[
        [Mapping[str, str]], CoinbaseCredentialResolution
    ] = resolve_live_coinbase_credentials,
    sdk_factory: Callable[..., Any] | None = None,
    wrapper_factory: Callable[[Any], Any] | None = None,
) -> Any:
    """Build one Default-profile client without consulting Spot credentials."""

    source = os.environ if environ is None else environ
    validate_coinbase_domain_credential_bindings(source)
    controlled = _controlled_futures_credential_environment(source)
    try:
        resolution = credential_resolver(controlled)
    except Exception:
        raise FuturesDefaultRestClientError(
            "operator_futures_default_credential_resolution_failed"
        ) from None
    if (
        resolution.source != "secrets_manager"
        or resolution.secret_id_env
        != "COINBASE_SECRETS_MANAGER_SECRET_ID"
        or tuple(resolution.missing)
    ):
        raise FuturesDefaultRestClientError(
            "operator_futures_default_credential_source_invalid"
        )
    api_key = _text(resolution.credentials.get("COINBASE_API_KEY"))
    api_secret = _text(resolution.credentials.get("COINBASE_API_SECRET"))
    if not api_key or not api_secret:
        raise FuturesDefaultRestClientError(
            "operator_futures_default_credentials_missing"
        )
    if sdk_factory is None:
        from coinbase.rest import RESTClient

        sdk_factory = RESTClient
    if wrapper_factory is None:
        from external.coinbase_client import CoinbaseRestClient

        wrapper_factory = CoinbaseRestClient
    try:
        sdk_client = sdk_factory(
            api_key=api_key,
            api_secret=api_secret,
            base_url="api.coinbase.com",
            rate_limit_headers=False,
            timeout=FUTURES_REST_TIMEOUT_SECONDS,
        )
        return wrapper_factory(sdk_client)
    except Exception:
        raise FuturesDefaultRestClientError(
            "operator_futures_default_rest_client_unavailable"
        ) from None


def configure_futures_default_rest_client(
    environ: Mapping[str, str] | None = None,
) -> Any:
    """Construct and retain the process-local Futures/Default client."""

    global _CLIENT
    with _CLIENT_LOCK:
        _CLIENT = build_futures_default_rest_client(environ=environ)
        return _CLIENT


def futures_default_rest_client_configured() -> bool:
    return _CLIENT is not None


def get_futures_default_rest_client() -> Any:
    if _CLIENT is None:
        raise FuturesDefaultRestClientError(
            "operator_futures_default_rest_client_not_configured"
        )
    return _CLIENT


def reset_futures_default_rest_client_for_tests() -> None:
    global _CLIENT
    with _CLIENT_LOCK:
        _CLIENT = None


__all__ = [
    "FUTURES_DEFAULT_REGION",
    "FUTURES_DEFAULT_SECRET_ID",
    "FUTURES_SECRET_ID_ENV",
    "FUTURES_SECRET_REGION_ENV",
    "FuturesDefaultRestClientError",
    "SPOT_SECRET_ID_ENV",
    "SPOT_SECRET_REGION_ENV",
    "SPOT_TEST_SECRET_ID",
    "build_futures_default_rest_client",
    "configure_futures_default_rest_client",
    "futures_default_rest_client_configured",
    "get_futures_default_rest_client",
    "reset_futures_default_rest_client_for_tests",
    "validate_coinbase_domain_credential_bindings",
]
