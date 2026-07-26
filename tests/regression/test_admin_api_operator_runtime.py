from __future__ import annotations

from pathlib import Path
import inspect
import sys
from types import SimpleNamespace

import pytest

from core.coinbase_execution_authority import CoinbaseExecutionAuthorityError
from tools import run_admin_api_operator_runtime as operator_runtime


def _authorized_environment(tmp_path: Path) -> dict[str, str]:
    token = "a" * 64
    lease = tmp_path / "coinbase-execution.lease"
    lease.write_text(f"{token}\n", encoding="ascii")
    lease.chmod(0o600)
    return {
        "COINBASE_EXECUTION_ENABLED": "1",
        "COINBASE_EXECUTION_LEASE_PATH": str(lease),
        "COINBASE_EXECUTION_LEASE_TOKEN": token,
        "COINBASE_ADMIN_API_LIVE_EXECUTION_ENABLED": "true",
        "COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID": (
            "11111111-2222-4333-8444-555555555555"
        ),
        "COINBASE_ADMIN_API_BEARER_TOKEN": "operator-review-token",
        "COINBASE_ADMIN_API_OS_TRUSTSTORE": "disabled",
        "COINBASE_SECRETS_MANAGER_SECRET_ID": "coinbase/Test",
        "COINBASE_SECRETS_MANAGER_REGION": "us-east-1",
        "COINBASE_SPOT_SECRETS_MANAGER_SECRET_ID": "coinbase/Test",
        "COINBASE_SPOT_SECRETS_MANAGER_REGION": "us-east-1",
        "COINBASE_FUTURES_SECRETS_MANAGER_SECRET_ID": "coinbase",
        "COINBASE_FUTURES_SECRETS_MANAGER_REGION": "us-east-1",
    }


@pytest.mark.parametrize("outer_authority", [None, "0", "true", "yes", "01"])
def test_operator_runtime_rejects_before_credential_hydration_without_exact_authority(
    tmp_path: Path,
    outer_authority: str | None,
) -> None:
    environment = _authorized_environment(tmp_path)
    if outer_authority is None:
        environment.pop("COINBASE_EXECUTION_ENABLED")
    else:
        environment["COINBASE_EXECUTION_ENABLED"] = outer_authority
    hydration_calls: list[dict[str, str]] = []

    with pytest.raises(CoinbaseExecutionAuthorityError):
        operator_runtime.prepare_operator_runtime(
            [],
            environ=environment,
            credential_hydrator=lambda target: hydration_calls.append(dict(target)),
        )

    assert hydration_calls == []


def test_operator_runtime_prepares_route_scoped_server_after_backend_hydration(
    tmp_path: Path,
) -> None:
    environment = _authorized_environment(tmp_path)
    hydration_calls: list[dict[str, str]] = []

    prepared = operator_runtime.prepare_operator_runtime(
        ["--host", "127.0.0.1", "--port", "8877", "--cors-origin", "http://127.0.0.1:3000"],
        environ=environment,
        credential_hydrator=lambda target: hydration_calls.append(dict(target))
        or SimpleNamespace(source="synthetic-test"),
    )

    assert prepared.host == "127.0.0.1"
    assert prepared.port == 8877
    assert prepared.credential_source == "synthetic-test"
    assert hydration_calls
    assert environment["COINBASE_ADMIN_API_CORS_ORIGINS"] == "http://127.0.0.1:3000"
    assert "COINBASE_ADMIN_API_EMBEDDED_ENABLED" not in environment


def test_operator_runtime_prepares_domain_separated_futures_client_when_enabled(
    tmp_path: Path,
) -> None:
    environment = _authorized_environment(tmp_path)
    environment["COINBASE_ADMIN_API_OPERATOR_FUTURES_MANUAL_ENABLED"] = "1"
    futures_preparations: list[dict[str, str]] = []

    prepared = operator_runtime.prepare_operator_runtime(
        [],
        environ=environment,
        credential_hydrator=lambda target: target.update(
            {
                "COINBASE_API_KEY": "spot-key",
                "COINBASE_API_SECRET": "spot-secret",
            }
        )
        or SimpleNamespace(source="secrets_manager"),
        futures_client_preparer=lambda target: futures_preparations.append(
            dict(target)
        )
        or SimpleNamespace(),
    )

    assert prepared.credential_source == "secrets_manager"
    assert len(futures_preparations) == 1
    assert futures_preparations[0]["COINBASE_API_KEY"] == "spot-key"
    assert (
        futures_preparations[0][
            "COINBASE_FUTURES_SECRETS_MANAGER_SECRET_ID"
        ]
        == "coinbase"
    )


def test_operator_runtime_prepares_default_client_for_product_ticket_alone(
    tmp_path: Path,
) -> None:
    environment = _authorized_environment(tmp_path)
    environment[
        "COINBASE_ADMIN_API_OPERATOR_FUTURES_PRODUCT_TICKET_ENABLED"
    ] = "1"
    futures_preparations: list[dict[str, str]] = []

    operator_runtime.prepare_operator_runtime(
        [],
        environ=environment,
        credential_hydrator=lambda target: target.update(
            {
                "COINBASE_API_KEY": "spot-key",
                "COINBASE_API_SECRET": "spot-secret",
            }
        )
        or SimpleNamespace(source="secrets_manager"),
        futures_client_preparer=lambda target: futures_preparations.append(
            dict(target)
        )
        or SimpleNamespace(),
    )

    assert len(futures_preparations) == 1


def test_operator_runtime_prepares_default_client_for_hotpoint_v2_alone(
    tmp_path: Path,
) -> None:
    environment = _authorized_environment(tmp_path)
    environment[
        "COINBASE_ADMIN_API_OPERATOR_FUTURES_HOTPOINT_V2_ENABLED"
    ] = "1"
    environment["COINBASE_ADMIN_API_FUTURES_PORTFOLIO_ID"] = (
        "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    )
    futures_preparations: list[dict[str, str]] = []

    prepared = operator_runtime.prepare_operator_runtime(
        [],
        environ=environment,
        credential_hydrator=lambda target: target.update(
            {
                "COINBASE_API_KEY": "spot-key",
                "COINBASE_API_SECRET": "spot-secret",
            }
        )
        or SimpleNamespace(source="secrets_manager"),
        futures_client_preparer=lambda target: futures_preparations.append(
            dict(target)
        )
        or SimpleNamespace(),
    )

    assert prepared.credential_source == "secrets_manager"
    assert len(futures_preparations) == 1
    assert futures_preparations[0][
        "COINBASE_ADMIN_API_FUTURES_PORTFOLIO_ID"
    ] == "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def test_operator_runtime_hotpoint_v2_fails_closed_before_client_on_bad_binding(
    tmp_path: Path,
) -> None:
    environment = _authorized_environment(tmp_path)
    environment[
        "COINBASE_ADMIN_API_OPERATOR_FUTURES_HOTPOINT_V2_ENABLED"
    ] = "1"
    environment["COINBASE_ADMIN_API_FUTURES_PORTFOLIO_ID"] = (
        "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    )
    environment["COINBASE_FUTURES_SECRETS_MANAGER_SECRET_ID"] = (
        "coinbase/Test"
    )

    with pytest.raises(
        operator_runtime.OperatorAdminRuntimeError,
        match="operator_coinbase_domain_credential_bindings_conflated",
    ):
        operator_runtime.prepare_operator_runtime(
            [],
            environ=environment,
            credential_hydrator=lambda _target: SimpleNamespace(
                source="unexpected"
            ),
            futures_client_preparer=lambda _target: pytest.fail(
                "invalid Default binding must fail before construction"
            ),
        )


def test_operator_runtime_hotpoint_v2_requires_default_portfolio_before_hydration(
    tmp_path: Path,
) -> None:
    environment = _authorized_environment(tmp_path)
    environment[
        "COINBASE_ADMIN_API_OPERATOR_FUTURES_HOTPOINT_V2_ENABLED"
    ] = "1"
    hydration_calls: list[dict[str, str]] = []

    with pytest.raises(
        operator_runtime.OperatorAdminRuntimeError,
        match="operator_futures_hotpoint_default_portfolio_required",
    ):
        operator_runtime.prepare_operator_runtime(
            [],
            environ=environment,
            credential_hydrator=lambda target: hydration_calls.append(
                dict(target)
            ),
        )

    assert hydration_calls == []


def test_operator_runtime_fails_closed_when_futures_and_spot_bindings_conflate(
    tmp_path: Path,
) -> None:
    environment = _authorized_environment(tmp_path)
    environment["COINBASE_ADMIN_API_OPERATOR_FUTURES_MANUAL_ENABLED"] = "1"
    environment["COINBASE_FUTURES_SECRETS_MANAGER_SECRET_ID"] = (
        "coinbase/Test"
    )

    with pytest.raises(
        operator_runtime.OperatorAdminRuntimeError,
        match="operator_coinbase_domain_credential_bindings_conflated",
    ):
        operator_runtime.prepare_operator_runtime(
            [],
            environ=environment,
            credential_hydrator=lambda _target: SimpleNamespace(
                source="unexpected"
            ),
            futures_client_preparer=lambda _target: pytest.fail(
                "conflated bindings must fail before client construction"
            ),
        )


def test_operator_runtime_requires_approved_spot_portfolio_scope(tmp_path: Path) -> None:
    environment = _authorized_environment(tmp_path)
    environment.pop("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID")

    with pytest.raises(
        operator_runtime.OperatorAdminRuntimeError,
        match="operator_spot_portfolio_scope_missing",
    ):
        operator_runtime.prepare_operator_runtime(
            [],
            environ=environment,
            credential_hydrator=lambda _target: SimpleNamespace(source="unexpected"),
        )


def test_operator_runtime_requires_manager_execution_lease(tmp_path: Path) -> None:
    environment = _authorized_environment(tmp_path)
    environment.pop("COINBASE_EXECUTION_LEASE_PATH")
    environment.pop("COINBASE_EXECUTION_LEASE_TOKEN")
    hydration_calls: list[dict[str, str]] = []

    with pytest.raises(
        operator_runtime.OperatorAdminRuntimeError,
        match="operator_execution_lease_missing",
    ):
        operator_runtime.prepare_operator_runtime(
            [],
            environ=environment,
            credential_hydrator=lambda target: hydration_calls.append(dict(target)),
        )

    assert hydration_calls == []


def test_operator_runtime_rejects_non_test_portfolio_label(tmp_path: Path) -> None:
    environment = _authorized_environment(tmp_path)
    environment["COINBASE_ADMIN_API_SPOT_PORTFOLIO_LABEL"] = "Production"
    hydration_calls: list[dict[str, str]] = []

    with pytest.raises(
        operator_runtime.OperatorAdminRuntimeError,
        match="operator_spot_portfolio_label_invalid",
    ):
        operator_runtime.prepare_operator_runtime(
            [],
            environ=environment,
            credential_hydrator=lambda target: hydration_calls.append(dict(target)),
        )

    assert hydration_calls == []


def test_operator_runtime_main_enters_canonical_main_only_after_preparation(
    tmp_path: Path,
) -> None:
    environment = _authorized_environment(tmp_path)
    lifecycle: list[object] = []

    result = operator_runtime.main(
        ["--host", "127.0.0.1", "--port", "8877"],
        environ=environment,
        credential_hydrator=lambda _target: SimpleNamespace(source="synthetic-test"),
        runtime_composer=lambda: lifecycle.append("compose") or SimpleNamespace(),
        server_runner=lambda config: lifecycle.append(
            ("serve", config.host, config.port)
        ),
    )

    assert result == 0
    assert lifecycle == ["compose", ("serve", "127.0.0.1", 8877)]


def test_operator_runtime_initializes_enabled_durable_schemas_before_composition(
    tmp_path: Path,
    monkeypatch,
) -> None:
    environment = _authorized_environment(tmp_path)
    environment["COINBASE_ADMIN_API_OPERATOR_AUTOMATION_ENABLED"] = "1"
    environment[
        "COINBASE_ADMIN_API_OPERATOR_PRODUCT_CATALOG_ENABLED"
    ] = "1"
    environment[
        "COINBASE_ADMIN_API_OPERATOR_PARENT_STRATEGIES_ENABLED"
    ] = "1"
    environment[
        "COINBASE_ADMIN_API_OPERATOR_STEALTH_DEFINITIONS_ENABLED"
    ] = "1"
    environment[
        "COINBASE_ADMIN_API_OPERATOR_SPOT_ORDER_TRUTH_ENABLED"
    ] = "1"
    lifecycle: list[object] = []
    monkeypatch.setattr(
        operator_runtime,
        "initialize_operator_automation_schema",
        lambda: lifecycle.append("operator_automation_schema"),
        raising=False,
    )
    monkeypatch.setattr(
        operator_runtime,
        "initialize_operator_product_catalog_schema",
        lambda: lifecycle.append("operator_product_catalog_schema"),
        raising=False,
    )
    monkeypatch.setattr(
        operator_runtime,
        "initialize_operator_parent_strategy_schema",
        lambda: lifecycle.append("operator_parent_strategy_schema"),
        raising=False,
    )
    monkeypatch.setattr(
        operator_runtime,
        "initialize_operator_stealth_definition_schema",
        lambda: lifecycle.append("operator_stealth_definition_schema"),
        raising=False,
    )
    monkeypatch.setattr(
        operator_runtime,
        "initialize_operator_spot_order_truth_schema",
        lambda: lifecycle.append("operator_spot_order_truth_schema"),
        raising=False,
    )

    result = operator_runtime.main(
        ["--host", "127.0.0.1", "--port", "8877"],
        environ=environment,
        credential_hydrator=lambda _target: SimpleNamespace(source="synthetic-test"),
        runtime_composer=lambda: lifecycle.append("compose") or SimpleNamespace(),
        server_runner=lambda config: lifecycle.append(
            ("serve", config.host, config.port)
        ),
    )

    assert result == 0
    assert lifecycle == [
        "operator_automation_schema",
        "operator_product_catalog_schema",
        "operator_parent_strategy_schema",
        "operator_stealth_definition_schema",
        "operator_spot_order_truth_schema",
        "compose",
        ("serve", "127.0.0.1", 8877),
    ]


@pytest.mark.parametrize("feature_value", [None, "0", "true", "yes", "01"])
def test_operator_runtime_skips_goal13_initialization_without_exact_flag(
    tmp_path: Path,
    monkeypatch,
    feature_value: str | None,
) -> None:
    environment = _authorized_environment(tmp_path)
    if feature_value is not None:
        environment[
            "COINBASE_ADMIN_API_OPERATOR_FUTURES_HOTPOINT_V2_ENABLED"
        ] = feature_value
    monkeypatch.setattr(
        operator_runtime,
        "initialize_operator_futures_hotpoint_v2_runtime",
        lambda: pytest.fail("non-exact flag must not initialize Goal13"),
        raising=False,
    )

    operator_runtime.initialize_enabled_operator_schemas(
        environ=environment
    )


def test_operator_runtime_eagerly_initializes_goal13_once_before_serving(
    tmp_path: Path,
    monkeypatch,
) -> None:
    environment = _authorized_environment(tmp_path)
    environment[
        "COINBASE_ADMIN_API_OPERATOR_FUTURES_HOTPOINT_V2_ENABLED"
    ] = "1"
    calls: list[str] = []
    monkeypatch.setattr(
        operator_runtime,
        "initialize_operator_futures_hotpoint_v2_runtime",
        lambda: calls.append("goal13_init"),
        raising=False,
    )

    operator_runtime.initialize_enabled_operator_schemas(
        environ=environment
    )

    assert calls == ["goal13_init"]


def test_operator_runtime_goal13_init_failure_prevents_serve(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    environment = _authorized_environment(tmp_path)
    environment[
        "COINBASE_ADMIN_API_OPERATOR_FUTURES_HOTPOINT_V2_ENABLED"
    ] = "1"
    environment["COINBASE_ADMIN_API_FUTURES_PORTFOLIO_ID"] = (
        "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    )
    lifecycle: list[str] = []
    monkeypatch.setattr(
        operator_runtime,
        "initialize_operator_futures_hotpoint_v2_runtime",
        lambda: (_ for _ in ()).throw(RuntimeError("withheld")),
        raising=False,
    )
    prepared_config = operator_runtime.AdminApiRunConfig(
        app="api.v1.app:app",
        host="127.0.0.1",
        port=8787,
        reload=False,
        cors_origins=("http://127.0.0.1:3000",),
        dev_token=None,
    )
    monkeypatch.setattr(
        operator_runtime,
        "prepare_operator_runtime",
        lambda *_args, **_kwargs: operator_runtime.PreparedOperatorRuntime(
            host="127.0.0.1",
            port=8787,
            credential_source="synthetic-test",
            config=prepared_config,
        ),
    )

    result = operator_runtime.main(
        [],
        environ=environment,
        credential_hydrator=lambda _target: SimpleNamespace(
            source="synthetic-test"
        ),
        runtime_composer=lambda: lifecycle.append("compose"),
        server_runner=lambda _config: lifecycle.append("serve"),
    )

    assert result == 2
    assert lifecycle == []
    assert capsys.readouterr().err.strip() == (
        "operator_admin_runtime_startup_failed:OperatorAdminRuntimeError"
    )


@pytest.mark.parametrize("feature_value", [None, "0", "true", "yes", "01"])
def test_operator_runtime_skips_automation_schema_without_exact_flag(
    tmp_path: Path,
    monkeypatch,
    feature_value: str | None,
) -> None:
    environment = _authorized_environment(tmp_path)
    if feature_value is not None:
        environment["COINBASE_ADMIN_API_OPERATOR_AUTOMATION_ENABLED"] = feature_value
    lifecycle: list[object] = []
    monkeypatch.setattr(
        operator_runtime,
        "initialize_operator_automation_schema",
        lambda: pytest.fail("non-exact feature value must not initialize schema"),
    )

    result = operator_runtime.main(
        [],
        environ=environment,
        credential_hydrator=lambda _target: SimpleNamespace(source="synthetic-test"),
        runtime_composer=lambda: lifecycle.append("compose") or SimpleNamespace(),
        server_runner=lambda _config: lifecycle.append("serve"),
    )

    assert result == 0
    assert lifecycle == ["compose", "serve"]


def test_operator_runtime_fails_closed_before_composition_when_schema_init_fails(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    environment = _authorized_environment(tmp_path)
    environment["COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED"] = "0"
    environment["COINBASE_ADMIN_API_OPERATOR_AUTOMATION_ENABLED"] = "1"
    lifecycle: list[object] = []
    monkeypatch.setattr(
        operator_runtime,
        "initialize_operator_automation_schema",
        lambda: (_ for _ in ()).throw(RuntimeError("withheld database detail")),
        raising=False,
    )

    result = operator_runtime.main(
        [],
        environ=environment,
        credential_hydrator=lambda _target: SimpleNamespace(source="synthetic-test"),
        runtime_composer=lambda: lifecycle.append("compose") or SimpleNamespace(),
        server_runner=lambda _config: lifecycle.append("serve"),
    )

    captured = capsys.readouterr()
    assert result == 2
    assert lifecycle == []
    assert captured.err.strip() == (
        "operator_admin_runtime_startup_failed:OperatorAdminRuntimeError"
    )
    assert "withheld database detail" not in captured.err


def test_operator_server_registers_uvicorn_ingress_as_runtime_stop_hook(
    monkeypatch,
) -> None:
    from core import runtime_controller as runtime_controller_module
    from tools import run_admin_api

    controller = runtime_controller_module.RuntimeController()
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
    config = operator_runtime.AdminApiRunConfig(
        app="api.v1.app:app",
        host="127.0.0.1",
        port=8877,
        reload=False,
        cors_origins=("http://127.0.0.1:3000",),
        dev_token=None,
    )

    operator_runtime._run_admin_server(config)

    assert legacy_run_calls == []
    assert len(servers) == 1
    server = servers[0]
    assert server.run_calls == 1
    assert server.should_exit is False

    result = controller.drain_and_stop(timeout_seconds=0.01)

    assert result.drained_clean is True
    assert server.should_exit is True


def test_operator_runtime_composes_dormant_canonical_dependencies_without_engine_or_bridge_loops(
    tmp_path: Path,
) -> None:
    environment = _authorized_environment(tmp_path)
    events: list[str] = []
    engine = SimpleNamespace(
        set_hotpoint_auto_place_enabled=lambda enabled: events.append(
            f"hotpoint:{enabled}"
        )
    )
    manager = SimpleNamespace()
    bridge = SimpleNamespace(order_engine=engine, stealth_manager=manager)
    runtime = SimpleNamespace(
        order_engine=engine,
        stealth_order_bridge=bridge,
        stealth_order_manager=manager,
    )
    configuration = SimpleNamespace(
        Subscription=SimpleNamespace(
            product_ids=["BTC-USDC", "AVP-20DEC30-CDE"],
            derivatives_product_ids=["AVP-20DEC30-CDE"],
        ),
        ORDERBOOK=SimpleNamespace(),
        API_KEY="synthetic-key",
        API_SECRET="synthetic-secret",
        ORDER_POST_ONLY={"BUY": True, "SELL": True},
        get_rest_client=lambda: events.append("rest") or SimpleNamespace(),
    )
    composed = operator_runtime.compose_canonical_operator_runtime(
        environ=environment,
        configuration_module=configuration,
        db_module=SimpleNamespace(),
        runtime_builder=lambda **kwargs: events.append(
            f"build:{kwargs['subscription'].product_ids}:"
            f"{kwargs['subscription'].channels}:"
            f"{kwargs['subscription'].retail_portfolio_id == environment['COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID']}"
        )
        or runtime,
        bridge_setter=lambda value: events.append(
            f"bridge:{value is bridge}"
        ),
        runtime_hydrator=lambda value: events.append(
            f"hydrate:{value is runtime}"
        ),
        readiness_builder=lambda: SimpleNamespace(
            runtime_ready=True,
            missing_reason=None,
        ),
    )

    assert composed is runtime
    assert events == [
        "build:['BTC-USDC']:[]:True",
        "hotpoint:False",
        "bridge:True",
        "hydrate:True",
    ]
    assert not hasattr(bridge, "running")


def test_operator_runtime_rejects_composition_when_command_dependencies_are_not_ready(
    tmp_path: Path,
) -> None:
    environment = _authorized_environment(tmp_path)
    engine = SimpleNamespace(set_hotpoint_auto_place_enabled=lambda _enabled: None)
    bridge = SimpleNamespace(order_engine=engine, stealth_manager=SimpleNamespace())
    runtime = SimpleNamespace(
        order_engine=engine,
        stealth_order_bridge=bridge,
        stealth_order_manager=bridge.stealth_manager,
    )
    configuration = SimpleNamespace(
        Subscription=SimpleNamespace(
            product_ids=["BTC-USDC"],
            derivatives_product_ids=[],
        ),
        ORDERBOOK=SimpleNamespace(),
        API_KEY="synthetic-key",
        API_SECRET="synthetic-secret",
        ORDER_POST_ONLY={"BUY": True, "SELL": True},
        get_rest_client=lambda: SimpleNamespace(),
    )

    with pytest.raises(
        operator_runtime.OperatorAdminRuntimeError,
        match="operator_command_runtime_not_ready",
    ):
        operator_runtime.compose_canonical_operator_runtime(
            environ=environment,
            configuration_module=configuration,
            db_module=SimpleNamespace(),
            runtime_builder=lambda **_kwargs: runtime,
            bridge_setter=lambda _bridge: None,
            runtime_hydrator=lambda _runtime: None,
            readiness_builder=lambda: SimpleNamespace(
                runtime_ready=False,
                missing_reason="order_event_publisher_unavailable",
            ),
        )


def test_operator_runtime_source_does_not_enter_legacy_main_or_start_autonomous_loops() -> None:
    source = Path(operator_runtime.__file__).read_text(encoding="utf-8")

    assert "runpy" not in source
    assert "main.py" not in source
    assert ".run_forever(" not in source
    assert "stealth_order_bridge.start(" not in source
    assert "require_spot_test_portfolio_binding" not in source


def test_operator_runtime_composition_diagnostics_are_value_blind() -> None:
    from core.order_engine import OrderEngine
    from core.stealth_order_manager import StealthOrderManager

    engine_initialization = inspect.getsource(OrderEngine.__init__)
    event_stream_initialization = inspect.getsource(
        OrderEngine._initialize_event_stream_integration
    )
    hotpoint_initialization = inspect.getsource(
        OrderEngine._initialize_hotpoint_subsystem
    )
    stealth_schema = inspect.getsource(StealthOrderManager._ensure_schema_migrations)
    stealth_hydration = inspect.getsource(
        StealthOrderManager.load_all_active_orders_from_db
    )
    stealth_single_load = inspect.getsource(
        StealthOrderManager._load_stealth_order_from_db
    )

    for source in (
        engine_initialization,
        event_stream_initialization,
        hotpoint_initialization,
        stealth_schema,
        stealth_hydration,
        stealth_single_load,
    ):
        assert "{e}" not in source
        assert "str(e)" not in source
        assert '"error": str(e)' not in source
    assert '"stealth_order_id": stealth_order_id' not in stealth_single_load
