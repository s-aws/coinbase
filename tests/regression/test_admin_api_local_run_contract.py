from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from application.admin_api.auth import oidc_jwt_required_env_vars
from core.enums import AdminApiAuthMode
from tools import run_admin_api


def _retained_uvicorn_stub(calls: list[dict[str, object]]) -> SimpleNamespace:
    class FakeConfig:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class FakeServer:
        def __init__(self, config) -> None:
            self.config = config
            self.should_exit = False

        def run(self) -> None:
            calls.append(self.config.kwargs)

    return SimpleNamespace(
        Config=FakeConfig,
        Server=FakeServer,
        run=lambda **kwargs: calls.append(kwargs),
    )


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
        "workers": 1,
    }


@pytest.mark.regression
def test_admin_api_non_reload_server_registers_ingress_as_runtime_stop_hook(
    monkeypatch,
):
    from core.runtime_controller import RuntimeController

    controller = RuntimeController()
    servers: list[object] = []
    legacy_run_calls: list[dict[str, object]] = []

    class FakeConfig:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class FakeServer:
        def __init__(self, config) -> None:
            self.config = config
            self.should_exit = False
            self.run_calls = 0
            servers.append(self)

        def run(self) -> None:
            self.run_calls += 1

    monkeypatch.setattr(
        run_admin_api,
        "get_runtime_controller",
        lambda: controller,
        raising=False,
    )
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        SimpleNamespace(
            Config=FakeConfig,
            Server=FakeServer,
            run=lambda **kwargs: legacy_run_calls.append(kwargs),
        ),
    )

    run_admin_api.run_uvicorn_server(run_admin_api.parse_run_config([]))

    assert legacy_run_calls == []
    assert len(servers) == 1
    server = servers[0]
    assert server.config.kwargs == run_admin_api.build_uvicorn_kwargs(
        run_admin_api.parse_run_config([])
    )
    assert server.run_calls == 1
    assert server.should_exit is False

    result = controller.drain_and_stop(timeout_seconds=0.01)

    assert result.drained_clean is True
    assert server.should_exit is True


@pytest.mark.regression
def test_admin_api_reload_server_preserves_uvicorn_reload_supervisor(monkeypatch):
    legacy_run_calls: list[dict[str, object]] = []
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        SimpleNamespace(
            Config=lambda **_kwargs: pytest.fail(
                "reload must remain owned by uvicorn.run"
            ),
            Server=lambda _config: pytest.fail(
                "reload must remain owned by uvicorn.run"
            ),
            run=lambda **kwargs: legacy_run_calls.append(kwargs),
        ),
    )
    config = run_admin_api.parse_run_config(["--reload"])

    run_admin_api.run_uvicorn_server(config)

    assert legacy_run_calls == [run_admin_api.build_uvicorn_kwargs(config)]


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
def test_admin_api_runner_uses_deployment_tier_as_environment_default():
    config = run_admin_api.parse_run_config([])
    environ = {run_admin_api.DEPLOYMENT_TIER_ENV: "staging"}

    applied = run_admin_api.apply_local_environment(config, environ=environ)

    assert environ[run_admin_api.ENVIRONMENT_ENV] == "staging"
    assert applied[run_admin_api.ENVIRONMENT_ENV] == "staging"

    environ[run_admin_api.ENVIRONMENT_ENV] = "production"
    run_admin_api.apply_local_environment(config, environ=environ)

    assert environ[run_admin_api.ENVIRONMENT_ENV] == "production"


@pytest.mark.regression
@pytest.mark.parametrize("outer_authority", [None, "0", "true", "yes", "01"])
def test_admin_api_runner_does_not_hydrate_credentials_without_exact_authority(
    outer_authority,
):
    environ = {run_admin_api.LIVE_RUNTIME_ENABLED_ENV: "true"}
    if outer_authority is not None:
        environ[run_admin_api.EXECUTION_AUTHORITY_ENV] = outer_authority
    calls = []

    source = run_admin_api.prepare_live_coinbase_credentials(
        environ=environ,
        credential_hydrator=lambda target: calls.append(target)
        or SimpleNamespace(source="unexpected"),
    )

    assert source == "disabled"
    assert calls == []


@pytest.mark.regression
def test_admin_api_runner_hydrates_credentials_only_for_exact_controlled_live():
    environ = {
        run_admin_api.EXECUTION_AUTHORITY_ENV: "1",
        run_admin_api.LIVE_RUNTIME_ENABLED_ENV: "true",
    }
    calls = []

    source = run_admin_api.prepare_live_coinbase_credentials(
        environ=environ,
        credential_hydrator=lambda target: calls.append(target)
        or SimpleNamespace(source="secrets_manager"),
    )

    assert source == "secrets_manager"
    assert calls == [environ]


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
    from core.runtime_controller import RuntimeController

    uvicorn_calls: list[dict[str, object]] = []
    startup_events: list[str] = []
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED",
        "1",
    )
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
        _retained_uvicorn_stub(uvicorn_calls),
    )
    monkeypatch.setattr(
        run_admin_api,
        "get_runtime_controller",
        lambda: RuntimeController(),
    )
    monkeypatch.setattr(
        run_admin_api,
        "initialize_order_follow_up_intent_schema",
        lambda: startup_events.append("follow_up_intent_schema"),
    )

    exit_code = run_admin_api.main(["--host", "0.0.0.0", "--port", "8787"])

    assert exit_code == 0
    assert startup_events == ["follow_up_intent_schema"]
    assert uvicorn_calls == [
        {
            "app": "api.v1.app:app",
            "host": "0.0.0.0",
            "port": 8787,
            "reload": False,
            "workers": 1,
        }
    ]


@pytest.mark.regression
def test_admin_api_local_runner_fails_closed_when_follow_up_intent_schema_init_fails(
    monkeypatch,
    capsys,
):
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED",
        "1",
    )
    monkeypatch.setenv(run_admin_api.AUTH_TOKEN_ENV, "local-test-token")
    monkeypatch.setattr(
        run_admin_api,
        "initialize_order_follow_up_intent_schema",
        lambda: (_ for _ in ()).throw(RuntimeError("withheld database detail")),
    )
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        SimpleNamespace(run=lambda **_kwargs: pytest.fail("uvicorn must not start")),
    )

    exit_code = run_admin_api.main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.err.strip() == run_admin_api.FOLLOW_UP_INTENT_SCHEMA_STARTUP_ERROR
    assert "withheld database detail" not in captured.err


@pytest.mark.regression
def test_admin_api_local_runner_skips_follow_up_intent_schema_when_feature_disabled(
    monkeypatch,
):
    from core.runtime_controller import RuntimeController

    uvicorn_calls: list[dict[str, object]] = []
    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED", "0")
    monkeypatch.setenv(run_admin_api.AUTH_TOKEN_ENV, "local-test-token")
    monkeypatch.setattr(
        run_admin_api,
        "initialize_order_follow_up_intent_schema",
        lambda: pytest.fail("disabled feature must not initialize its schema"),
    )
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        _retained_uvicorn_stub(uvicorn_calls),
    )
    monkeypatch.setattr(
        run_admin_api,
        "get_runtime_controller",
        lambda: RuntimeController(),
    )

    exit_code = run_admin_api.main([])

    assert exit_code == 0
    assert len(uvicorn_calls) == 1


@pytest.mark.regression
def test_admin_api_local_runner_initializes_operator_automation_schema_only_for_exact_flag(
    monkeypatch,
):
    from core.runtime_controller import RuntimeController

    uvicorn_calls: list[dict[str, object]] = []
    startup_events: list[str] = []
    monkeypatch.setenv(run_admin_api.AUTH_TOKEN_ENV, "local-test-token")
    monkeypatch.setenv(
        run_admin_api.OPERATOR_AUTOMATION_ENABLED_ENV,
        "1",
    )
    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED", "0")
    monkeypatch.setattr(
        run_admin_api,
        "initialize_operator_automation_schema",
        lambda: startup_events.append("operator_automation_schema"),
    )
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        _retained_uvicorn_stub(uvicorn_calls),
    )
    monkeypatch.setattr(
        run_admin_api,
        "get_runtime_controller",
        lambda: RuntimeController(),
    )

    exit_code = run_admin_api.main([])

    assert exit_code == 0
    assert startup_events == ["operator_automation_schema"]
    assert len(uvicorn_calls) == 1


@pytest.mark.regression
def test_admin_api_local_runner_initializes_product_catalog_schema_only_for_exact_flag(
    monkeypatch,
):
    from core.runtime_controller import RuntimeController

    uvicorn_calls: list[dict[str, object]] = []
    startup_events: list[str] = []
    monkeypatch.setenv(run_admin_api.AUTH_TOKEN_ENV, "local-test-token")
    monkeypatch.setenv(
        run_admin_api.OPERATOR_PRODUCT_CATALOG_ENABLED_ENV,
        "1",
    )
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED",
        "0",
    )
    monkeypatch.setattr(
        run_admin_api,
        "initialize_operator_product_catalog_schema",
        lambda: startup_events.append("operator_product_catalog_schema"),
    )
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        _retained_uvicorn_stub(uvicorn_calls),
    )
    monkeypatch.setattr(
        run_admin_api,
        "get_runtime_controller",
        lambda: RuntimeController(),
    )

    exit_code = run_admin_api.main([])

    assert exit_code == 0
    assert startup_events == ["operator_product_catalog_schema"]
    assert len(uvicorn_calls) == 1


@pytest.mark.regression
def test_admin_api_local_runner_initializes_parent_strategy_schema_only_for_exact_flag(
    monkeypatch,
):
    from core.runtime_controller import RuntimeController

    uvicorn_calls: list[dict[str, object]] = []
    startup_events: list[str] = []
    monkeypatch.setenv(run_admin_api.AUTH_TOKEN_ENV, "local-test-token")
    monkeypatch.setenv(
        run_admin_api.OPERATOR_PARENT_STRATEGIES_ENABLED_ENV,
        "1",
    )
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED",
        "0",
    )
    monkeypatch.setattr(
        run_admin_api,
        "initialize_operator_parent_strategy_schema",
        lambda: startup_events.append("operator_parent_strategy_schema"),
    )
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        _retained_uvicorn_stub(uvicorn_calls),
    )
    monkeypatch.setattr(
        run_admin_api,
        "get_runtime_controller",
        lambda: RuntimeController(),
    )

    exit_code = run_admin_api.main([])

    assert exit_code == 0
    assert startup_events == ["operator_parent_strategy_schema"]
    assert len(uvicorn_calls) == 1


@pytest.mark.regression
def test_admin_api_local_runner_initializes_parent_move_premark_schema_only_for_exact_flag(
    monkeypatch,
):
    from core.runtime_controller import RuntimeController

    uvicorn_calls: list[dict[str, object]] = []
    startup_events: list[str] = []
    monkeypatch.setenv(run_admin_api.AUTH_TOKEN_ENV, "local-test-token")
    monkeypatch.setenv(
        run_admin_api.OPERATOR_PARENT_MOVE_PREMARK_ENABLED_ENV,
        "1",
    )
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED",
        "0",
    )
    monkeypatch.setattr(
        run_admin_api,
        "initialize_operator_parent_move_premark_schema",
        lambda: startup_events.append("operator_parent_move_premark_schema"),
    )
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        _retained_uvicorn_stub(uvicorn_calls),
    )
    monkeypatch.setattr(
        run_admin_api,
        "get_runtime_controller",
        lambda: RuntimeController(),
    )

    exit_code = run_admin_api.main([])

    assert exit_code == 0
    assert startup_events == ["operator_parent_move_premark_schema"]
    assert len(uvicorn_calls) == 1


@pytest.mark.regression
def test_admin_api_local_runner_initializes_single_order_reprice_now_schema_only_for_exact_flag(
    monkeypatch,
):
    from core.runtime_controller import RuntimeController

    uvicorn_calls: list[dict[str, object]] = []
    startup_events: list[str] = []
    monkeypatch.setenv(run_admin_api.AUTH_TOKEN_ENV, "local-test-token")
    monkeypatch.setenv(
        run_admin_api.OPERATOR_SINGLE_ORDER_REPRICE_NOW_ENABLED_ENV,
        "1",
    )
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED",
        "0",
    )
    monkeypatch.setattr(
        run_admin_api,
        "initialize_operator_single_order_reprice_now_schema",
        lambda: startup_events.append(
            "operator_single_order_reprice_now_schema"
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        _retained_uvicorn_stub(uvicorn_calls),
    )
    monkeypatch.setattr(
        run_admin_api,
        "get_runtime_controller",
        lambda: RuntimeController(),
    )

    exit_code = run_admin_api.main([])

    assert exit_code == 0
    assert startup_events == [
        "operator_single_order_reprice_now_schema"
    ]
    assert len(uvicorn_calls) == 1


@pytest.mark.regression
def test_admin_api_local_runner_initializes_stealth_definition_schema_only_for_exact_flag(
    monkeypatch,
):
    from core.runtime_controller import RuntimeController

    uvicorn_calls: list[dict[str, object]] = []
    startup_events: list[str] = []
    monkeypatch.setenv(run_admin_api.AUTH_TOKEN_ENV, "local-test-token")
    monkeypatch.setenv(
        run_admin_api.OPERATOR_STEALTH_DEFINITIONS_ENABLED_ENV,
        "1",
    )
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED",
        "0",
    )
    monkeypatch.setattr(
        run_admin_api,
        "initialize_operator_stealth_definition_schema",
        lambda: startup_events.append("operator_stealth_definition_schema"),
        raising=False,
    )
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        _retained_uvicorn_stub(uvicorn_calls),
    )
    monkeypatch.setattr(
        run_admin_api,
        "get_runtime_controller",
        lambda: RuntimeController(),
    )

    exit_code = run_admin_api.main([])

    assert exit_code == 0
    assert startup_events == ["operator_stealth_definition_schema"]
    assert len(uvicorn_calls) == 1


@pytest.mark.regression
@pytest.mark.parametrize("feature_value", [None, "0", "true", "yes", "01"])
def test_admin_api_local_runner_skips_operator_automation_schema_without_exact_flag(
    monkeypatch,
    feature_value,
):
    from core.runtime_controller import RuntimeController

    uvicorn_calls: list[dict[str, object]] = []
    monkeypatch.setenv(run_admin_api.AUTH_TOKEN_ENV, "local-test-token")
    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED", "0")
    if feature_value is None:
        monkeypatch.delenv(
            run_admin_api.OPERATOR_AUTOMATION_ENABLED_ENV,
            raising=False,
        )
    else:
        monkeypatch.setenv(
            run_admin_api.OPERATOR_AUTOMATION_ENABLED_ENV,
            feature_value,
        )
    monkeypatch.setattr(
        run_admin_api,
        "initialize_operator_automation_schema",
        lambda: pytest.fail("disabled feature must not initialize its schema"),
    )
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        _retained_uvicorn_stub(uvicorn_calls),
    )
    monkeypatch.setattr(
        run_admin_api,
        "get_runtime_controller",
        lambda: RuntimeController(),
    )

    exit_code = run_admin_api.main([])

    assert exit_code == 0
    assert len(uvicorn_calls) == 1


@pytest.mark.regression
def test_admin_api_local_runner_fails_closed_when_operator_automation_schema_init_fails(
    monkeypatch,
    capsys,
):
    startup_events: list[str] = []
    monkeypatch.setenv(run_admin_api.AUTH_TOKEN_ENV, "local-test-token")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED",
        "1",
    )
    monkeypatch.setenv(
        run_admin_api.OPERATOR_AUTOMATION_ENABLED_ENV,
        "1",
    )
    monkeypatch.setattr(
        run_admin_api,
        "initialize_order_follow_up_intent_schema",
        lambda: startup_events.append("follow_up_intent_schema"),
    )
    monkeypatch.setattr(
        run_admin_api,
        "initialize_operator_automation_schema",
        lambda: (_ for _ in ()).throw(RuntimeError("withheld database detail")),
    )
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        SimpleNamespace(run=lambda **_kwargs: pytest.fail("uvicorn must not start")),
    )

    exit_code = run_admin_api.main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert startup_events == ["follow_up_intent_schema"]
    assert captured.err.strip() == run_admin_api.OPERATOR_AUTOMATION_SCHEMA_STARTUP_ERROR
    assert "withheld database detail" not in captured.err


@pytest.mark.regression
def test_admin_api_local_runner_is_not_a_trading_path():
    source = Path(run_admin_api.__file__).read_text(encoding="utf-8")

    assert "CoinbaseRestClient" not in source
    assert ".create_order(" not in source
    assert ".place_limit_order(" not in source
    assert "REST_CLIENT" not in source
