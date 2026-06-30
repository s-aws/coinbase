from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from application.admin_api.auth import oidc_jwt_required_env_vars
from core.enums import AdminApiAuthMode
from tools import run_admin_api


@pytest.mark.regression
def test_admin_api_local_runner_defaults_to_existing_fastapi_app():
    config = run_admin_api.parse_run_config([])

    assert config.app == "api.v1.app:app"
    assert config.host == "127.0.0.1"
    assert config.port == 8787
    assert config.reload is False
    assert config.cors_origins == ("http://127.0.0.1:3000",)
    assert run_admin_api.build_uvicorn_kwargs(config) == {
        "app": "api.v1.app:app",
        "host": "127.0.0.1",
        "port": 8787,
        "reload": False,
    }


@pytest.mark.regression
def test_admin_api_local_runner_applies_local_environment_without_secret_overwrite():
    config = run_admin_api.parse_run_config(
        [
            "--port",
            "8790",
            "--cors-origin",
            "http://127.0.0.1:3000",
            "--cors-origin",
            "http://localhost:3000",
            "--dev-token",
            "local-admin-token",
        ]
    )
    environ: dict[str, str] = {}

    applied = run_admin_api.apply_local_environment(config, environ=environ)

    assert environ["COINBASE_ADMIN_API_BEARER_TOKEN"] == "local-admin-token"
    assert (
        environ["COINBASE_ADMIN_API_CORS_ORIGINS"]
        == "http://127.0.0.1:3000,http://localhost:3000"
    )
    assert environ["COINBASE_ADMIN_API_ENVIRONMENT"] == "local"
    assert applied["COINBASE_ADMIN_API_BEARER_TOKEN"] == "set_from_dev_token"

    environ["COINBASE_ADMIN_API_BEARER_TOKEN"] = "already-configured"
    run_admin_api.apply_local_environment(config, environ=environ)

    assert environ["COINBASE_ADMIN_API_BEARER_TOKEN"] == "already-configured"


@pytest.mark.regression
def test_admin_api_local_runner_fails_closed_without_backend_auth(monkeypatch, capsys):
    monkeypatch.delenv(run_admin_api.AUTH_MODE_ENV, raising=False)
    monkeypatch.delenv(run_admin_api.AUTH_TOKEN_ENV, raising=False)
    monkeypatch.delenv(run_admin_api.CORS_ORIGINS_ENV, raising=False)
    monkeypatch.delenv(run_admin_api.ENVIRONMENT_ENV, raising=False)

    exit_code = run_admin_api.main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "COINBASE_ADMIN_API_BEARER_TOKEN is required" in captured.err


@pytest.mark.regression
def test_admin_api_local_runner_auth_contract_matches_oidc_verifier():
    assert run_admin_api.OIDC_REQUIRED_ENV_VARS == oidc_jwt_required_env_vars()


@pytest.mark.regression
def test_admin_api_local_runner_fails_closed_when_oidc_startup_config_is_missing():
    environ = {run_admin_api.AUTH_MODE_ENV: AdminApiAuthMode.OIDC_JWT.value}

    missing_env_vars = run_admin_api.missing_startup_auth_env_vars(environ=environ)
    error_message = run_admin_api.startup_auth_error_message(environ=environ)

    assert missing_env_vars == run_admin_api.OIDC_REQUIRED_ENV_VARS
    assert error_message is not None
    assert "Admin API OIDC/JWT startup auth is not configured" in error_message
    assert "COINBASE_ADMIN_API_OIDC_ISSUER" in error_message
    assert run_admin_api.AUTH_TOKEN_ENV not in error_message


@pytest.mark.regression
def test_admin_api_local_runner_starts_with_oidc_auth_without_bootstrap_token(monkeypatch):
    uvicorn_calls: list[dict[str, object]] = []
    monkeypatch.delenv(run_admin_api.AUTH_TOKEN_ENV, raising=False)
    monkeypatch.setenv(run_admin_api.AUTH_MODE_ENV, AdminApiAuthMode.OIDC_JWT.value)
    monkeypatch.setenv("COINBASE_ADMIN_API_OIDC_ISSUER", "https://issuer.example.test")
    monkeypatch.setenv("COINBASE_ADMIN_API_OIDC_AUDIENCE", "coinbase-admin-api")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OIDC_JWKS_URL",
        "https://issuer.example.test/.well-known/jwks.json",
    )
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        SimpleNamespace(run=lambda **kwargs: uvicorn_calls.append(kwargs)),
    )

    exit_code = run_admin_api.main(["--host", "0.0.0.0", "--port", "8787"])

    assert exit_code == 0
    assert uvicorn_calls == [
        {
            "app": "api.v1.app:app",
            "host": "0.0.0.0",
            "port": 8787,
            "reload": False,
        }
    ]


@pytest.mark.regression
def test_admin_api_local_runner_is_not_a_trading_path():
    source = Path(run_admin_api.__file__).read_text(encoding="utf-8")

    assert "CoinbaseRestClient" not in source
    assert ".create_order(" not in source
    assert ".place_limit_order(" not in source
    assert "REST_CLIENT" not in source
