from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from application.admin_api import futures_default_rest_client
from application.admin_api import operator_futures_manual_service_runtime
from application.admin_api import operator_futures_position_service_runtime


def _environment() -> dict[str, str]:
    return {
        "COINBASE_API_KEY": "spot-key-must-not-be-reused",
        "COINBASE_API_SECRET": "spot-secret-must-not-be-reused",
        "COINBASE_SECRETS_MANAGER_SECRET_ID": "coinbase/Test",
        "COINBASE_SECRETS_MANAGER_REGION": "us-east-1",
        "COINBASE_SPOT_SECRETS_MANAGER_SECRET_ID": "coinbase/Test",
        "COINBASE_SPOT_SECRETS_MANAGER_REGION": "us-east-1",
        "COINBASE_FUTURES_SECRETS_MANAGER_SECRET_ID": "coinbase",
        "COINBASE_FUTURES_SECRETS_MANAGER_REGION": "us-east-1",
        "AWS_PROFILE": "default",
    }


def test_futures_client_uses_only_canonical_default_secret_and_not_spot_credentials() -> None:
    resolver_inputs: list[dict[str, str]] = []
    sdk_inputs: list[dict[str, object]] = []
    wrapped = object()

    def resolve(controlled):
        resolver_inputs.append(dict(controlled))
        return SimpleNamespace(
            source="secrets_manager",
            secret_id_env="COINBASE_SECRETS_MANAGER_SECRET_ID",
            credentials={
                "COINBASE_API_KEY": "default-key",
                "COINBASE_API_SECRET": "default-secret",
            },
            missing=(),
        )

    def sdk_factory(**kwargs):
        sdk_inputs.append(dict(kwargs))
        return object()

    result = futures_default_rest_client.build_futures_default_rest_client(
        environ=_environment(),
        credential_resolver=resolve,
        sdk_factory=sdk_factory,
        wrapper_factory=lambda sdk: wrapped if sdk is not None else None,
    )

    assert result is wrapped
    assert resolver_inputs == [
        {
            "AWS_PROFILE": "default",
            "COINBASE_SECRETS_MANAGER_SECRET_ID": "coinbase",
            "COINBASE_SECRETS_MANAGER_REGION": "us-east-1",
        }
    ]
    assert sdk_inputs == [
        {
            "api_key": "default-key",
            "api_secret": "default-secret",
            "base_url": "api.coinbase.com",
            "rate_limit_headers": False,
            "timeout": 10,
        }
    ]


@pytest.mark.parametrize(
    ("updates", "diagnostic"),
    [
        (
            {"COINBASE_FUTURES_SECRETS_MANAGER_SECRET_ID": ""},
            "operator_futures_default_credential_binding_missing",
        ),
        (
            {"COINBASE_FUTURES_SECRETS_MANAGER_SECRET_ID": "coinbase/Other"},
            "operator_futures_default_credential_binding_invalid",
        ),
        (
            {"COINBASE_SPOT_SECRETS_MANAGER_SECRET_ID": "coinbase"},
            "operator_coinbase_domain_credential_bindings_conflated",
        ),
    ],
)
def test_futures_client_binding_fails_closed(
    updates: dict[str, str],
    diagnostic: str,
) -> None:
    environment = {**_environment(), **updates}

    with pytest.raises(
        futures_default_rest_client.FuturesDefaultRestClientError,
        match=diagnostic,
    ):
        futures_default_rest_client.build_futures_default_rest_client(
            environ=environment,
            credential_resolver=lambda _controlled: pytest.fail(
                "invalid binding must fail before credential resolution"
            ),
            sdk_factory=lambda **_kwargs: pytest.fail(
                "invalid binding must fail before SDK construction"
            ),
            wrapper_factory=lambda _sdk: pytest.fail(
                "invalid binding must fail before wrapper construction"
            ),
        )


def test_futures_client_rejects_non_secrets_manager_resolution() -> None:
    with pytest.raises(
        futures_default_rest_client.FuturesDefaultRestClientError,
        match="operator_futures_default_credential_source_invalid",
    ):
        futures_default_rest_client.build_futures_default_rest_client(
            environ=_environment(),
            credential_resolver=lambda _controlled: SimpleNamespace(
                source="environment",
                secret_id_env=None,
                credentials={
                    "COINBASE_API_KEY": "unexpected",
                    "COINBASE_API_SECRET": "unexpected",
                },
                missing=(),
            ),
            sdk_factory=lambda **_kwargs: pytest.fail(
                "invalid credential source must fail before SDK construction"
            ),
            wrapper_factory=lambda _sdk: pytest.fail(
                "invalid credential source must fail before wrapper construction"
            ),
        )


def test_installed_futures_services_never_import_the_process_wide_spot_client() -> None:
    for runtime_module in (
        operator_futures_manual_service_runtime,
        operator_futures_position_service_runtime,
    ):
        source = inspect.getsource(runtime_module)
        assert "from configuration import REST_CLIENT" not in source
        assert "from configuration import API_KEY" not in source
        assert "get_futures_default_rest_client" in source
