from __future__ import annotations

import ast
from collections import Counter
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from core.coinbase_execution_authority import (
    COINBASE_EXECUTION_SCOPE_FUTURES_CANCEL,
    COINBASE_EXECUTION_SCOPE_FUTURES_CLOSE_POSITION,
    COINBASE_EXECUTION_SCOPE_FUTURES_PLACE,
    COINBASE_EXECUTION_SCOPE_FUTURES_PREVIEW,
    COINBASE_EXECUTION_SCOPE_SPOT_PLACE,
    CoinbaseExecutionAuthorityError,
    canonical_coinbase_execution_scope,
)
from application.admin_api.command_service import exact_coinbase_order_readback
from application.admin_api.live_execution import (
    LiveServiceDecisionRecord,
    OPERATOR_READY_MVP_DEPLOYMENT_REF,
    OPERATOR_READY_MVP_RUNTIME_CONFIGURATION_REF,
    live_service_decision_allows_backend_admission,
)
from core.enums import AdminApiGateStatus, AdminApiLiveExecutionStatus
from external.coinbase_client import (
    CoinbaseRestClient,
    coinbase_cancel_response_evidence,
)


class _MutationSdk:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def cancel_orders(self, order_ids):
        self.calls.append(("cancel_orders", list(order_ids)))
        return {"results": [{"success": True, "order_id": order_ids[0]}]}

    def close_position(self, **kwargs):
        self.calls.append(("close_position", dict(kwargs)))
        return SimpleNamespace(
            success=True,
            success_response={
                "order_id": "exchange-close-1",
            },
        )

    def limit_order_gtc(self, **kwargs):
        self.calls.append(("limit_order_gtc", dict(kwargs)))
        return {"success": True}

    def create_order(self, **kwargs):
        self.calls.append(("create_order", dict(kwargs)))
        return {"success": True}

    def preview_order(self, **kwargs):
        self.calls.append(("preview_order", dict(kwargs)))
        return {"errs": [], "warning": [], "preview_id": "private-preview-id"}


def test_canonical_wrapper_hardens_sdk_to_zero_retry_no_redirect_transport(
    requests_mock,
) -> None:
    import requests

    session = requests.Session()
    assert session.max_redirects > 0
    assert session.trust_env is True
    sdk = SimpleNamespace(session=session)

    CoinbaseRestClient(sdk)

    assert session.max_redirects == 0
    assert session.trust_env is False
    assert session.proxies == {}
    assert set(session.adapters) == {"http://", "https://"}
    assert all(
        type(adapter.max_retries.total) is int
        and adapter.max_retries.total == 0
        for adapter in session.adapters.values()
    )
    requests_mock.get(
        "https://coinbase.invalid/first",
        status_code=307,
        headers={"Location": "https://coinbase.invalid/second"},
    )
    requests_mock.get("https://coinbase.invalid/second", status_code=200)
    with pytest.raises(requests.TooManyRedirects):
        session.get("https://coinbase.invalid/first")
    assert requests_mock.call_count == 1


def test_canonical_wrapper_rejects_any_nonzero_transport_retry_policy() -> None:
    import requests
    from requests.adapters import HTTPAdapter

    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=1))

    with pytest.raises(ValueError, match="coinbase_sdk_transport_retry_forbidden"):
        CoinbaseRestClient(SimpleNamespace(session=session))


_RAW_SDK_MUTATION_METHODS = frozenset({
    "cancel_orders",
    "close_position",
    "create_order",
    "edit_order",
    "limit_order_gtc",
    "market_order_buy",
    "market_order_sell",
})


def _assigned_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        return {
            name
            for element in node.elts
            for name in _assigned_names(element)
        }
    return set()


def _getattr_name(node: ast.AST, expected: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value == expected
    )


def _raw_sdk_mutation_calls(source: str) -> list[tuple[int, str]]:
    """Find mutation calls reachable from raw SDK construction or extraction."""

    tree = ast.parse(source)
    rest_client_names = {"RESTClient"}
    raw_names: set[str] = set()
    sdk_factory_names: set[str] = set()
    raw_surface_present = False

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "coinbase.rest":
            for alias in node.names:
                if alias.name == "RESTClient":
                    rest_client_names.add(alias.asname or alias.name)
                    raw_surface_present = True
        elif (
            isinstance(node, ast.Attribute)
            and node.attr in {"get_sdk_client", "_client"}
        ):
            raw_surface_present = True
        elif _getattr_name(node, "get_sdk_client") or _getattr_name(
            node,
            "_client",
        ):
            raw_surface_present = True

    assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
    ]
    changed = True
    while changed:
        changed = False
        for assignment in assignments:
            targets = (
                assignment.targets
                if isinstance(assignment, ast.Assign)
                else [assignment.target]
            )
            names = {
                name
                for target in targets
                for name in _assigned_names(target)
            }
            value = assignment.value
            if value is None:
                continue
            marks_factory = _getattr_name(value, "get_sdk_client")
            marks_raw = (
                isinstance(value, ast.Name) and value.id in raw_names
            ) or (
                isinstance(value, ast.Attribute) and value.attr == "_client"
            ) or _getattr_name(value, "_client")
            if isinstance(value, ast.Call):
                marks_raw = marks_raw or (
                    isinstance(value.func, ast.Name)
                    and value.func.id in rest_client_names | sdk_factory_names
                ) or (
                    isinstance(value.func, ast.Attribute)
                    and value.func.attr == "get_sdk_client"
                )
            if marks_factory and not names.issubset(sdk_factory_names):
                sdk_factory_names.update(names)
                changed = True
            if marks_raw and not names.issubset(raw_names):
                raw_names.update(names)
                changed = True

    discovered: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        method = node.func.attr
        if method not in _RAW_SDK_MUTATION_METHODS:
            continue
        receiver = node.func.value
        receiver_is_raw = (
            isinstance(receiver, ast.Name) and receiver.id in raw_names
        ) or (
            isinstance(receiver, ast.Attribute) and receiver.attr == "_client"
        ) or (
            isinstance(receiver, ast.Call)
            and isinstance(receiver.func, ast.Attribute)
            and receiver.func.attr == "get_sdk_client"
        )
        if (
            not receiver_is_raw
            and raw_surface_present
            and isinstance(receiver, ast.Name)
            and receiver.id not in {"self", "cls"}
        ):
            receiver_is_raw = True
        if receiver_is_raw:
            discovered.append((node.lineno, method))
    return sorted(discovered)


@pytest.mark.parametrize("configured_value", [None, "", "0", "true", "yes", "01"])
@pytest.mark.parametrize(
    "invoke",
    [
        lambda client: client.cancel_order("client-order-id"),
        lambda client: client.cancel_order_by_exchange_order_id(
            "exchange-order-id"
        ),
        lambda client: client.cancel_orders(["exchange-order-id"]),
        lambda client: client.close_position(
            client_order_id="client-order-id",
            product_id="AVP-20DEC30-CDE",
            size="1",
        ),
        lambda client: client.limit_order_gtc(
            client_order_id="client-order-id",
            product_id="BTC-USDC",
            side="BUY",
            base_size="0.0001",
            limit_price="10000",
        ),
        lambda client: client.create_order(
            client_order_id="client-order-id",
            product_id="BTC-USDC",
            side="BUY",
            order_configuration={"market_market_ioc": {"quote_size": "1"}},
        ),
    ],
)
def test_canonical_mutation_boundary_requires_exact_outer_authority(
    monkeypatch: pytest.MonkeyPatch,
    configured_value: str | None,
    invoke,
) -> None:
    if configured_value is None:
        monkeypatch.delenv("COINBASE_EXECUTION_ENABLED", raising=False)
    else:
        monkeypatch.setenv("COINBASE_EXECUTION_ENABLED", configured_value)
    sdk = _MutationSdk()
    client = CoinbaseRestClient(sdk)

    with pytest.raises(
        CoinbaseExecutionAuthorityError,
        match="^coinbase_execution_authority_missing$",
    ):
        invoke(client)

    assert sdk.calls == []


def test_canonical_mutation_boundary_rejects_exact_one_without_verified_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COINBASE_EXECUTION_ENABLED", "1")
    sdk = _MutationSdk()
    client = CoinbaseRestClient(sdk)

    with pytest.raises(
        CoinbaseExecutionAuthorityError,
        match="^coinbase_execution_authority_missing$",
    ):
        client.create_order(
            client_order_id="client-order-id",
            product_id="BTC-USDC",
            side="BUY",
            order_configuration={"market_market_ioc": {"quote_size": "1"}},
        )

    assert sdk.calls == []


def test_configured_runtime_lease_is_required_at_final_mutation_boundary(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease_path = tmp_path / "coinbase-execution.lease"
    monkeypatch.setenv("COINBASE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("COINBASE_EXECUTION_LEASE_PATH", str(lease_path))
    monkeypatch.setenv("COINBASE_EXECUTION_LEASE_TOKEN", "a" * 64)
    sdk = _MutationSdk()
    client = CoinbaseRestClient(sdk)

    with pytest.raises(CoinbaseExecutionAuthorityError):
        client.create_order(product_id="BTC-USDC", side="BUY")
    assert sdk.calls == []

    lease_path.write_text(f"{'b' * 64}\n", encoding="utf-8")
    os.chmod(lease_path, 0o600)
    with canonical_coinbase_execution_scope(COINBASE_EXECUTION_SCOPE_SPOT_PLACE):
        with pytest.raises(CoinbaseExecutionAuthorityError):
            client.create_order(product_id="BTC-USDC", side="BUY")
    assert sdk.calls == []

    lease_path.write_text(f"{'a' * 64}\n", encoding="utf-8")
    os.chmod(lease_path, 0o600)
    with pytest.raises(CoinbaseExecutionAuthorityError):
        client.create_order(product_id="BTC-USDC", side="BUY")
    assert sdk.calls == []

    with canonical_coinbase_execution_scope(COINBASE_EXECUTION_SCOPE_SPOT_PLACE):
        assert client.create_order(product_id="BTC-USDC", side="BUY") == {
            "success": True
        }
    assert [name for name, _payload in sdk.calls] == ["create_order"]


@pytest.mark.parametrize(
    ("scope", "invoke", "expected_method"),
    [
        (
            COINBASE_EXECUTION_SCOPE_FUTURES_PREVIEW,
            lambda client: client.preview_futures_order(
                product_id="AVP-20DEC30-CDE",
                side="BUY",
                order_configuration={
                    "limit_limit_gtc": {
                        "base_size": "1",
                        "limit_price": "6.90",
                        "post_only": True,
                    }
                },
            ),
            "preview_order",
        ),
        (
            COINBASE_EXECUTION_SCOPE_FUTURES_PLACE,
            lambda client: client.create_futures_order(
                client_order_id="futures-goal-10-child",
                product_id="AVP-20DEC30-CDE",
                side="BUY",
                order_configuration={
                    "limit_limit_gtc": {
                        "base_size": "1",
                        "limit_price": "6.90",
                        "post_only": True,
                    }
                },
                preview_id="private-preview-id",
            ),
            "create_order",
        ),
        (
            COINBASE_EXECUTION_SCOPE_FUTURES_CANCEL,
            lambda client: client.cancel_futures_order(
                exchange_order_id="private-exchange-order-id",
            ),
            "cancel_orders",
        ),
    ],
)
def test_futures_execution_boundaries_require_distinct_canonical_scopes(
    coinbase_execution_lease,
    monkeypatch: pytest.MonkeyPatch,
    scope: str,
    invoke,
    expected_method: str,
) -> None:
    monkeypatch.setenv("COINBASE_EXECUTION_ENABLED", "1")
    sdk = _MutationSdk()
    client = CoinbaseRestClient(sdk)

    with canonical_coinbase_execution_scope(COINBASE_EXECUTION_SCOPE_SPOT_PLACE):
        with pytest.raises(
            CoinbaseExecutionAuthorityError,
            match="^coinbase_execution_authority_missing$",
        ):
            invoke(client)
    assert sdk.calls == []

    with canonical_coinbase_execution_scope(scope):
        invoke(client)
    assert [name for name, _payload in sdk.calls] == [expected_method]


@pytest.mark.parametrize(
    ("scope", "invoke"),
    [
        (
            COINBASE_EXECUTION_SCOPE_FUTURES_PREVIEW,
            lambda client, callback: client.preview_futures_order(
                product_id="AVP-20DEC30-CDE",
                side="BUY",
                order_configuration={
                    "limit_limit_gtc": {
                        "base_size": "1",
                        "limit_price": "6.90",
                        "post_only": True,
                    }
                },
                before_sdk_call=callback,
            ),
        ),
        (
            COINBASE_EXECUTION_SCOPE_FUTURES_PLACE,
            lambda client, callback: client.create_futures_order(
                client_order_id="futures-goal-10-child",
                product_id="AVP-20DEC30-CDE",
                side="BUY",
                order_configuration={
                    "limit_limit_gtc": {
                        "base_size": "1",
                        "limit_price": "6.90",
                        "post_only": True,
                    }
                },
                preview_id="private-preview-id",
                before_sdk_call=callback,
            ),
        ),
        (
            COINBASE_EXECUTION_SCOPE_FUTURES_CANCEL,
            lambda client, callback: client.cancel_futures_order(
                exchange_order_id="private-exchange-order-id",
                before_sdk_call=callback,
            ),
        ),
    ],
)
def test_futures_execution_boundaries_recheck_authority_after_claim(
    coinbase_execution_lease,
    monkeypatch: pytest.MonkeyPatch,
    scope: str,
    invoke,
) -> None:
    monkeypatch.setenv("COINBASE_EXECUTION_ENABLED", "1")
    sdk = _MutationSdk()
    client = CoinbaseRestClient(sdk)
    claim_callbacks: list[str] = []

    def revoke_after_claim() -> None:
        claim_callbacks.append("claimed")
        monkeypatch.delenv("COINBASE_EXECUTION_ENABLED", raising=False)

    with canonical_coinbase_execution_scope(scope):
        with pytest.raises(
            CoinbaseExecutionAuthorityError,
            match="^coinbase_execution_authority_missing$",
        ):
            invoke(client, revoke_after_claim)

    assert claim_callbacks == ["claimed"]
    assert sdk.calls == []


def test_goal11_close_and_cancel_wrappers_require_distinct_scopes_and_claim_first(
    coinbase_execution_lease,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COINBASE_EXECUTION_ENABLED", "1")
    sdk = _MutationSdk()
    client = CoinbaseRestClient(sdk)
    claims: list[str] = []

    with canonical_coinbase_execution_scope(
        COINBASE_EXECUTION_SCOPE_FUTURES_CLOSE_POSITION
    ):
        result = client.close_operator_futures_position(
            client_order_id="goal11-close-1",
            product_id="AVP-20DEC30-CDE",
            size=None,
            before_sdk_call=lambda: claims.append("close"),
        )
    with canonical_coinbase_execution_scope(
        COINBASE_EXECUTION_SCOPE_FUTURES_CANCEL
    ):
        client.cancel_operator_futures_position_order(
            exchange_order_id="exchange-close-1",
            before_sdk_call=lambda: claims.append("cancel"),
        )

    assert claims == ["close", "cancel"]
    assert sdk.calls == [
        (
            "close_position",
            {
                "client_order_id": "goal11-close-1",
                "product_id": "AVP-20DEC30-CDE",
            },
        ),
        ("cancel_orders", ["exchange-close-1"]),
    ]
    assert result["success"] is True

    with canonical_coinbase_execution_scope(
        COINBASE_EXECUTION_SCOPE_FUTURES_PLACE
    ):
        with pytest.raises(
            CoinbaseExecutionAuthorityError,
            match="^coinbase_execution_authority_missing$",
        ):
            client.close_operator_futures_position(
                client_order_id="wrong-scope",
                product_id="AVP-20DEC30-CDE",
                size="1",
                before_sdk_call=lambda: None,
            )


@pytest.mark.parametrize("unsafe_shape", ["symlink", "hardlink", "crlf"])
def test_runtime_lease_rejects_aliases_and_noncanonical_bytes(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_shape: str,
) -> None:
    target = tmp_path / "target.lease"
    target.write_text(f"{'d' * 64}\n", encoding="utf-8")
    os.chmod(target, 0o600)
    lease_path = tmp_path / "coinbase-execution.lease"
    if unsafe_shape == "symlink":
        lease_path.symlink_to(target)
    elif unsafe_shape == "hardlink":
        os.link(target, lease_path)
    else:
        lease_path.write_bytes(f"{'d' * 64}\r\n".encode("ascii"))
        os.chmod(lease_path, 0o600)

    monkeypatch.setenv("COINBASE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("COINBASE_EXECUTION_LEASE_PATH", str(lease_path))
    monkeypatch.setenv("COINBASE_EXECUTION_LEASE_TOKEN", "d" * 64)
    sdk = _MutationSdk()

    with pytest.raises(CoinbaseExecutionAuthorityError):
        CoinbaseRestClient(sdk).create_order(product_id="BTC-USDC", side="BUY")
    assert sdk.calls == []


def test_create_order_rechecks_authority_after_local_argument_preparation(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RevokingConfiguration(dict):
        def __bool__(self) -> bool:
            monkeypatch.delenv("COINBASE_EXECUTION_ENABLED", raising=False)
            return True

    lease_path = tmp_path / "coinbase-execution.lease"
    lease_path.write_text(f"{'e' * 64}\n", encoding="ascii")
    os.chmod(lease_path, 0o600)
    monkeypatch.setenv("COINBASE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("COINBASE_EXECUTION_LEASE_PATH", str(lease_path))
    monkeypatch.setenv("COINBASE_EXECUTION_LEASE_TOKEN", "e" * 64)
    sdk = _MutationSdk()

    with pytest.raises(CoinbaseExecutionAuthorityError):
        CoinbaseRestClient(sdk).create_order(
            product_id="BTC-USDC",
            side="BUY",
            order_configuration=_RevokingConfiguration(
                {"market_market_ioc": {"quote_size": "1"}}
            ),
        )

    assert sdk.calls == []


@pytest.mark.parametrize(
    ("scope", "invoke"),
    [
        (
            "canonical_admin_api_spot_place",
            lambda client, callback: client.create_order(
                product_id="BTC-USDC",
                side="BUY",
                before_sdk_call=callback,
            ),
        ),
        (
            "canonical_admin_api_spot_cancel",
            lambda client, callback: client.cancel_orders(
                ["exchange-order-id"],
                before_sdk_call=callback,
            ),
        ),
    ],
)
def test_mutation_wrapper_rechecks_authority_after_durable_claim_callback(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    scope: str,
    invoke,
) -> None:
    lease_path = tmp_path / "coinbase-execution.lease"
    lease_path.write_text(f"{'f' * 64}\n", encoding="ascii")
    os.chmod(lease_path, 0o600)
    monkeypatch.setenv("COINBASE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("COINBASE_EXECUTION_LEASE_PATH", str(lease_path))
    monkeypatch.setenv("COINBASE_EXECUTION_LEASE_TOKEN", "f" * 64)
    sdk = _MutationSdk()
    claims: list[str] = []

    def revoke_after_claim() -> None:
        claims.append("claimed")
        monkeypatch.delenv("COINBASE_EXECUTION_ENABLED", raising=False)

    with canonical_coinbase_execution_scope(scope):
        with pytest.raises(
            CoinbaseExecutionAuthorityError,
            match="^coinbase_execution_authority_missing$",
        ):
            invoke(CoinbaseRestClient(sdk), revoke_after_claim)

    assert claims == ["claimed"]
    assert sdk.calls == []


@pytest.mark.parametrize(
    ("scope", "invoke"),
    [
        (
            "canonical_admin_api_spot_place",
            lambda client, callback: client.create_order(
                product_id="BTC-USDC",
                side="BUY",
                before_sdk_call=callback,
            ),
        ),
        (
            "canonical_admin_api_spot_cancel",
            lambda client, callback: client.cancel_orders(
                ["exchange-order-id"],
                before_sdk_call=callback,
            ),
        ),
    ],
)
def test_mutation_wrapper_revalidates_transport_after_claim_callback(
    monkeypatch: pytest.MonkeyPatch,
    scope: str,
    invoke,
) -> None:
    import requests
    from requests.adapters import HTTPAdapter

    monkeypatch.setenv("COINBASE_EXECUTION_ENABLED", "1")
    session = requests.Session()
    sdk = _MutationSdk()
    sdk.session = session
    sdk.timeout = 10
    sdk.base_url = "api.coinbase.com"
    session.verify = True
    client = CoinbaseRestClient(sdk)

    def drift_transport_after_claim() -> None:
        session.mount("https://", HTTPAdapter(max_retries=1))

    with canonical_coinbase_execution_scope(scope):
        with pytest.raises(
            ValueError,
            match="coinbase_sdk_transport_retry_forbidden",
        ):
            invoke(client, drift_transport_after_claim)

    assert sdk.calls == []


def test_every_raw_sdk_mutation_runner_is_source_disabled_before_client() -> None:
    repository = Path(__file__).resolve().parents[2]
    guarded_runners = {
        "run_live_spot_usdc_smoke.py": "def main(",
        "run_spot_portfolio_sweep_live.py": (
            "reports = execute_usdc_portfolio_sweep_plan("
        ),
    }
    mutation_tokens = (
        ".create_order(",
        ".cancel_orders(",
        ".limit_order_gtc(",
        ".close_position(",
        "execute_usdc_portfolio_sweep_plan(",
    )
    discovered: set[str] = set()
    for path in (repository / "tools").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "from coinbase.rest import RESTClient" not in source:
            continue
        if not any(token in source for token in mutation_tokens):
            continue
        discovered.add(path.name)
        assert "SOURCE_DISABLED_COINBASE_EXECUTION_ERROR" in source
        main_offset = source.index(
            "def _run_main("
            if path.name == "run_spot_portfolio_sweep_live.py"
            else "def main("
        )
        disabled_offset = source.index(
            "parser.error(SOURCE_DISABLED_COINBASE_EXECUTION_ERROR)",
            main_offset,
        )
        if path.name == "run_live_spot_usdc_smoke.py":
            assert "return _run_live_smoke(args)" not in source[main_offset:]
        else:
            live_operation_offset = source.index(
                guarded_runners[path.name],
                disabled_offset,
            )
            assert disabled_offset < live_operation_offset

    assert discovered == set(guarded_runners)


def test_raw_sdk_mutation_static_gate_detects_factory_and_assignment_aliases(
) -> None:
    source = """
def unsafe(wrapper):
    sdk = wrapper.get_sdk_client()
    alias = sdk
    return alias.cancel_orders(["exchange-order-id"])
"""

    assert _raw_sdk_mutation_calls(source) == [(5, "cancel_orders")]


def test_raw_sdk_mutation_sites_are_frozen_to_guarded_boundaries() -> None:
    repository = Path(__file__).resolve().parents[2]
    discovered: dict[str, Counter[str]] = {}
    call_lines: dict[str, list[tuple[int, str]]] = {}
    for directory in ("application", "business", "core", "external", "tools"):
        for path in (repository / directory).rglob("*.py"):
            source = path.read_text(encoding="utf-8-sig")
            calls = _raw_sdk_mutation_calls(source)
            if not calls:
                continue
            relative = path.relative_to(repository).as_posix()
            discovered[relative] = Counter(method for _line, method in calls)
            call_lines[relative] = calls

    assert discovered == {
        "business/spot_portfolio_sweep.py": Counter({"create_order": 1}),
        "external/coinbase_client.py": Counter({
            "cancel_orders": 5,
            "close_position": 2,
            "create_order": 2,
            "limit_order_gtc": 1,
        }),
        "tools/run_live_spot_usdc_smoke.py": Counter({
            "cancel_orders": 2,
            "limit_order_gtc": 2,
            "market_order_buy": 2,
            "market_order_sell": 2,
        }),
    }

    for relative in (
        "business/spot_portfolio_sweep.py",
        "external/coinbase_client.py",
        "tools/run_live_spot_usdc_smoke.py",
    ):
        lines = (repository / relative).read_text(encoding="utf-8").splitlines()
        for line_number, _method in call_lines[relative]:
            # A durable-call claim and transport validation may run before the
            # final authority check immediately preceding the SDK invocation.
            final_boundary_window = lines[
                max(0, line_number - 4):line_number
            ]
            assert any(
                line.strip().startswith("require_coinbase_execution_authority(")
                for line in final_boundary_window
            )


def test_live_service_decision_must_be_newer_than_runtime_execution_lease(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease_path = tmp_path / "coinbase-execution.lease"
    lease_path.write_text(f"{'c' * 64}\n", encoding="utf-8")
    os.chmod(lease_path, 0o600)
    lease_started_at = datetime.now(timezone.utc)
    os.utime(
        lease_path,
        (lease_started_at.timestamp(), lease_started_at.timestamp()),
    )
    monkeypatch.setenv("COINBASE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("COINBASE_EXECUTION_LEASE_PATH", str(lease_path))
    monkeypatch.setenv("COINBASE_EXECUTION_LEASE_TOKEN", "c" * 64)

    def decision(recorded_at: datetime) -> LiveServiceDecisionRecord:
        return LiveServiceDecisionRecord(
            recorded_at=recorded_at.isoformat(),
            status=AdminApiGateStatus.PASSED,
            requested_service_status=(
                AdminApiLiveExecutionStatus.APPROVAL_REQUIRED
            ),
            service_enabled=True,
            deployment_ref=OPERATOR_READY_MVP_DEPLOYMENT_REF,
            runtime_configuration_ref=(
                OPERATOR_READY_MVP_RUNTIME_CONFIGURATION_REF
            ),
            decision_reason="synthetic operator enablement",
            live_coinbase_execution_approved=True,
            max_submitted_notional_usdc="3.10",
            max_executed_notional_usdc="1",
        )

    assert not live_service_decision_allows_backend_admission(
        decision(lease_started_at - timedelta(seconds=1))
    )
    assert not live_service_decision_allows_backend_admission(
        decision(lease_started_at)
    )
    assert live_service_decision_allows_backend_admission(
        decision(lease_started_at + timedelta(seconds=1))
    )

    canonical = decision(lease_started_at + timedelta(seconds=1))
    for changed in (
        {"target_module_id": "spot_operations"},
        {"account_family": "consumer"},
        {"venue_scope": "coinbase_advanced_trade"},
        {"intx_applicability": "included"},
        {"product_scope": ["BTC-USDC"]},
        {"deployment_ref": "stale-deployment"},
        {"runtime_configuration_ref": "stale-runtime"},
    ):
        assert not live_service_decision_allows_backend_admission(
            canonical.model_copy(update=changed)
        )

    monkeypatch.delenv("COINBASE_EXECUTION_LEASE_PATH")
    monkeypatch.delenv("COINBASE_EXECUTION_LEASE_TOKEN")
    assert not live_service_decision_allows_backend_admission(canonical)


def test_legacy_admin_mvp_runtime_cannot_enable_exchange_mutations(
    coinbase_execution_lease,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from application.admin_api.mvp_service import (
        AdminMvpDependencies,
        AdminMvpService,
    )

    monkeypatch.setenv("COINBASE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("COINBASE_ADMIN_LIVE_COINBASE_EXECUTION", "1")
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=_MutationSdk(),
            rest_client_available=True,
            live_coinbase_execution_enabled=True,
        )
    )

    assert service._live_execution_enabled() is False
    repository = Path(__file__).resolve().parents[2]
    production_hits = []
    canonical_scope_hits = []
    for root_name in (
        "api",
        "application",
        "business",
        "core",
        "dashboard_server.py",
        "external",
        "tools",
    ):
        root = repository / root_name
        paths = [root] if root.is_file() else root.rglob("*.py")
        for path in paths:
            source = path.read_text(encoding="utf-8")
            relative = path.relative_to(repository).as_posix()
            if "_synthetic_test_only_legacy_execution_enabled" in source:
                production_hits.append(path.relative_to(repository).as_posix())
            if "canonical_coinbase_execution_scope" in source:
                canonical_scope_hits.append(relative)
    assert production_hits == ["application/admin_api/mvp_service.py"]
    assert sorted(canonical_scope_hits) == [
        "api/v1/routes/orders.py",
        "application/admin_api/operator_automation.py",
        "application/admin_api/operator_follow_up_materialization_runtime.py",
        "application/admin_api/operator_futures_manual_runtime.py",
        "application/admin_api/operator_futures_order_operations_runtime.py",
        "application/admin_api/operator_futures_position_runtime.py",
        "application/admin_api/operator_hotpoint_runtime.py",
        "application/admin_api/operator_revealed_order_movement_runtime.py",
        "application/admin_api/operator_stealth_reveal_runtime.py",
        "core/coinbase_execution_authority.py",
    ]
    materialization_runtime = (
        repository
        / "application"
        / "admin_api"
        / "operator_follow_up_materialization_runtime.py"
    ).read_text(encoding="utf-8")
    assert "COINBASE_EXECUTION_SCOPE_SPOT_PLACE" in materialization_runtime
    assert "COINBASE_EXECUTION_SCOPE_SPOT_CANCEL" in materialization_runtime
    assert 'self.inflight_scope_factory("PLACE")' in materialization_runtime
    assert 'self.inflight_scope_factory("CANCEL")' in materialization_runtime


def test_legacy_compatibility_mutation_entrypoints_are_source_disabled() -> None:
    """Only authenticated Admin API Spot place/cancel may mint execution scope."""

    from core import coinbase_execution_authority as authority

    repository = Path(__file__).resolve().parents[2]
    disabled_error = (
        "coinbase_execution_surface_source_disabled_use_authenticated_admin_api"
    )
    assert authority.SOURCE_DISABLED_COINBASE_EXECUTION_ERROR == disabled_error

    dashboard_source = (repository / "dashboard_server.py").read_text(
        encoding="utf-8"
    )
    assert "_dashboard_command_service" not in dashboard_source
    assert "AdminApiCommandService" not in dashboard_source
    assert "SOURCE_DISABLED_COINBASE_EXECUTION_ERROR" in dashboard_source
    for message_type in (
        "place_order",
        "cancel_order",
        "place_hotpoint_test_order",
    ):
        assert message_type in dashboard_source

    legacy_main_source = (repository / "main.py").read_text(
        encoding="utf-8-sig"
    )
    legacy_guard = legacy_main_source.index(
        "raise RuntimeError(SOURCE_DISABLED_COINBASE_EXECUTION_ERROR)"
    )
    runtime_construction = legacy_main_source.index(
        "runtime = build_canonical_order_runtime("
    )
    assert legacy_guard < runtime_construction

    raw_smoke_source = (
        repository / "tools" / "run_live_spot_usdc_smoke.py"
    ).read_text(encoding="utf-8")
    raw_smoke_main = raw_smoke_source[raw_smoke_source.index("def main(") :]
    assert "parser.error(SOURCE_DISABLED_COINBASE_EXECUTION_ERROR)" in raw_smoke_main
    assert "return _run_live_smoke(args)" not in raw_smoke_main

    sweep_source = (
        repository / "tools" / "run_spot_portfolio_sweep_live.py"
    ).read_text(encoding="utf-8")
    live_mode_guard = sweep_source.index(
        "if not args.approved_live_orders:"
    )
    first_live_client = sweep_source.index(
        "rest_client = configuration.get_rest_client()",
        live_mode_guard,
    )
    assert (
        "parser.error(SOURCE_DISABLED_COINBASE_EXECUTION_ERROR)"
        in sweep_source[live_mode_guard:first_live_client]
    )

    controlled_batch_source = (
        repository / "tools" / "run_controlled_admin_spot_root_child_batch.py"
    ).read_text(encoding="utf-8")
    controlled_batch_main = controlled_batch_source[
        controlled_batch_source.rindex("\ndef main() -> int:\n") :
    ]
    assert "parser.error(SOURCE_DISABLED_COINBASE_EXECUTION_ERROR)" in (
        controlled_batch_main
    )
    assert "if args.execute_controlled_batch:" in controlled_batch_main
    assert "if args.runtime_child:" in controlled_batch_main


def test_source_disabled_cli_help_does_not_advertise_exchange_mutation() -> None:
    """Compatibility flags may parse, but operator help must not offer them."""

    repository = Path(__file__).resolve().parents[2]
    raw_smoke_source = (
        repository / "tools" / "run_live_spot_usdc_smoke.py"
    ).read_text(encoding="utf-8")
    for advertised_mutation in (
        "Skip the post-only limit submit/cancel smoke.",
        "Skip the market buy/sell round-trip smoke.",
        "Run market BUY, post-only limit BUY cancel",
        "Durable JSONL audit file for live smoke summaries.",
        "after live smoke orders",
    ):
        assert advertised_mutation not in raw_smoke_source

    sweep_source = (
        repository / "tools" / "run_spot_portfolio_sweep_live.py"
    ).read_text(encoding="utf-8")
    for advertised_mutation in (
        "Sweep side to execute.",
        "Maximum live run attempts",
        "Seconds to poll each submitted order",
        "Polling interval for submitted order status.",
        "Live order reports are still included.",
        "after submitted live sweep orders",
    ):
        assert advertised_mutation not in sweep_source

    controlled_batch_source = (
        repository / "tools" / "run_controlled_admin_spot_root_child_batch.py"
    ).read_text(encoding="utf-8")
    assert "It executes Test-profile" not in controlled_batch_source
    execute_flag = controlled_batch_source.index('"--execute-controlled-batch"')
    assert "help=argparse.SUPPRESS" in controlled_batch_source[
        execute_flag : execute_flag + 240
    ]


def test_legacy_direct_service_clis_are_source_disabled_before_credentials() -> None:
    """Installed operators must use authenticated routes, not service singletons."""

    repository = Path(__file__).resolve().parents[2]
    for relative_path in (
        "tools/run_admin_api_manual_order_live_submit.py",
        "tools/run_admin_api_spot_live_cancel.py",
    ):
        source = (repository / relative_path).read_text(encoding="utf-8")
        main_source = source[source.rindex("\ndef main(") :]
        parser_source = source[
            source.index("def build_parser(") : source.index("\ndef config_from_args(")
        ]
        assert "source-disabled" in source[:500].lower()
        assert "parser.error(SOURCE_DISABLED_COINBASE_EXECUTION_ERROR)" in main_source
        assert "assert_live_credentials_present" not in main_source
        assert "get_admin_mvp_service()" not in main_source
        assert "--confirm-live" not in parser_source


def test_m58_snapshot_mutation_cli_is_source_disabled_before_credentials() -> None:
    """The historical M58 runner must not remain an installed mutation path."""

    repository = Path(__file__).resolve().parents[2]
    source = (
        repository
        / "tools"
        / "run_admin_api_usdc_pair_snapshot_live_submit.py"
    ).read_text(encoding="utf-8")
    main_source = source[source.rindex("\ndef main(") :]
    parser_source = source[
        source.index("def build_parser(") : source.index("\ndef config_from_args(")
    ]
    assert "source-disabled" in source[:500].lower()
    assert "parser.error(SOURCE_DISABLED_COINBASE_EXECUTION_ERROR)" in main_source
    assert "run_usdc_pair_snapshot_live_submit(config)" not in main_source
    assert "--confirm-live-submit" not in parser_source


@pytest.mark.parametrize(
    ("filename", "retired_flag"),
    (
        ("run_controlled_admin_spot_child_cancel_slice.py", "--execute-v15-plan"),
        (
            "run_controlled_admin_spot_child_cancel_recovery.py",
            "--execute-v15r2-plan",
        ),
        (
            "run_controlled_admin_spot_child_cancel_recovery_v15r4.py",
            "--execute-v15r4-plan",
        ),
        (
            "run_controlled_admin_spot_child_cancel_recovery_v15r5.py",
            "--execute-v15r5-plan",
        ),
        (
            "run_controlled_admin_spot_child_cancel_recovery_v15r6.py",
            "--execute-v15r6-plan",
        ),
    ),
)
def test_sealed_child_cancel_variant_direct_execution_is_source_disabled(
    filename: str,
    retired_flag: str,
) -> None:
    """A shared early guard seals direct execution without changing evidence bytes."""

    repository = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [sys.executable, str(repository / "tools" / filename), retired_flag],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    assert completed.returncode != 0
    assert (
        "coinbase_execution_surface_source_disabled_use_authenticated_admin_api"
        in output
    )


def test_futures_mutation_clis_allow_historical_refresh_only() -> None:
    """Futures artifact readback may refresh; exchange mutation is not installed."""

    repository = Path(__file__).resolve().parents[2]
    for relative_path in (
        "tools/run_admin_api_futures_live_submit.py",
        "tools/run_admin_api_futures_live_cancel.py",
        "tools/run_admin_api_futures_live_close_reduce.py",
    ):
        source = (repository / relative_path).read_text(encoding="utf-8")
        main_source = source[source.rindex("\ndef main(") :]
        assert "source-disabled" in source[:500].lower()
        assert "parser.error(SOURCE_DISABLED_COINBASE_EXECUTION_ERROR)" in main_source
        assert "assert_live_credentials_present" not in main_source
        assert "LIVE_EXECUTION_ENV" not in main_source
        assert "if config.refresh_existing_artifact" not in main_source
        assert "if not config.refresh_existing_artifact:" in main_source


def test_exact_order_readback_emits_allowlisted_evidence_only() -> None:
    private_marker = "private-response-marker-must-not-escape"

    class _ReadSdk:
        def get_order(self, order_id):
            return {
                "order": {
                    "client_order_id": "client-order-id",
                    "order_id": order_id,
                    "status": "OPEN",
                    "product_id": "BTC-USDC",
                    "product_type": "SPOT",
                    "retail_portfolio_id": "portfolio-id",
                    "side": "SELL",
                    "filled_size": "0",
                    "filled_value": "0",
                    "total_fees": "0",
                    "number_of_fills": 0,
                    "order_configuration": {
                        "limit_limit_gtc": {
                            "base_size": "0.0001",
                            "limit_price": "10000",
                            "private_extension": private_marker,
                        }
                    },
                    "private_extension": private_marker,
                },
                "private_top_level": private_marker,
            }

    readback = exact_coinbase_order_readback(
        _ReadSdk(),
        client_order_id="client-order-id",
        exchange_order_id="exchange-order-id",
        product_id="BTC-USDC",
    )

    assert readback["matched_order"]["client_order_id"] == "client-order-id"
    assert readback["matched_order"]["order_configuration"] == {
        "limit_limit_gtc": {
            "base_size": "0.0001",
            "limit_price": "10000",
        }
    }
    assert private_marker not in repr(readback)


def test_exact_order_readback_replaces_unknown_enum_values_with_fixed_unknown() -> None:
    private_marker = "private-enum-marker-must-not-escape"

    class _ReadSdk:
        def get_order(self, order_id):
            return {
                "order": {
                    "client_order_id": "client-order-id",
                    "order_id": order_id,
                    "status": private_marker,
                    "product_id": "BTC-USDC",
                    "product_type": private_marker,
                    "side": private_marker,
                    "order_type": private_marker,
                    "time_in_force": private_marker,
                }
            }

    readback = exact_coinbase_order_readback(
        _ReadSdk(),
        client_order_id="client-order-id",
        exchange_order_id="exchange-order-id",
        product_id="BTC-USDC",
    )

    assert readback["authoritative_status"] == "UNKNOWN"
    for field in (
        "status",
        "product_type",
        "side",
        "order_type",
        "time_in_force",
    ):
        assert readback["matched_order"][field] == "UNKNOWN"
    assert private_marker not in repr(readback)


def test_cancel_evidence_never_forwards_raw_exchange_failure_text() -> None:
    private_marker = "private-cancel-failure-must-not-escape"

    evidence = coinbase_cancel_response_evidence(
        {
            "results": [
                {
                    "success": False,
                    "order_id": "exchange-order-id",
                    "failure_reason": private_marker,
                }
            ]
        },
        expected_order_id="exchange-order-id",
    )

    assert evidence["outcome"] == "unknown"
    assert evidence["failure_reasons"] == ["unclassified_exchange_rejection"]
    assert private_marker not in repr(evidence)
