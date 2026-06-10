from __future__ import annotations

from pathlib import Path

import pytest

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
    monkeypatch.delenv("COINBASE_ADMIN_API_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("COINBASE_ADMIN_API_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("COINBASE_ADMIN_API_ENVIRONMENT", raising=False)

    exit_code = run_admin_api.main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "COINBASE_ADMIN_API_BEARER_TOKEN is required" in captured.err


@pytest.mark.regression
def test_admin_api_local_runner_is_not_a_trading_path():
    source = Path(run_admin_api.__file__).read_text(encoding="utf-8")

    assert "CoinbaseRestClient" not in source
    assert ".create_order(" not in source
    assert ".place_limit_order(" not in source
    assert "REST_CLIENT" not in source
