from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from application.admin_api.spot_portfolio_binding import (
    SpotPortfolioBindingError,
    evaluate_spot_test_portfolio_binding,
    require_spot_test_portfolio_binding,
)
from application.admin_api.command_service import (
    AdminApiCommandDependencies,
    AdminApiCommandService,
)
from application.admin_api.models import (
    AdminApiActor,
    AdminApiCommandEnvelope,
    AdminApiCommandStatus,
    AdminApiRole,
    CancelOrderCommand,
    CancelOrderRequest,
    ManualOrderCommand,
    ManualOrderRequest,
)


TEST_PORTFOLIO_ID = "11111111-2222-4333-8444-555555555555"
DEFAULT_PORTFOLIO_ID = "f4dfdb77-aa88-53d0-9c37-da3a0762ce54"


def test_command_runtime_market_reference_falls_back_to_fresh_coinbase_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from application.admin_api import command_runtime

    monkeypatch.setitem(
        sys.modules,
        "dashboard_server",
        SimpleNamespace(
            stealth_order_bridge=SimpleNamespace(
                stealth_manager=SimpleNamespace(
                    _market_cache={
                        "BTC-USD": {
                            "product_id": "BTC-USD",
                            "bid": "64197.70",
                            "source": "ticker",
                            "time": "2026-07-11T08:53:40.000000Z",
                        }
                    }
                )
            )
        ),
    )
    best_bid_calls: list[dict[str, object]] = []

    def get_best_bid_ask(**kwargs: object) -> SimpleNamespace:
        best_bid_calls.append(dict(kwargs))
        return SimpleNamespace(
            to_dict=lambda: {
                "pricebooks": [
                    {
                        "product_id": "BTC-USDC",
                        "time": "2026-07-11T08:53:40.658107Z",
                        "bids": [{"price": "64197.77", "size": "0.33691341"}],
                        "asks": [{"price": "64197.78", "size": "0.12466358"}],
                    }
                ]
            }
        )

    sdk_client = SimpleNamespace(
        get_best_bid_ask=get_best_bid_ask,
    )
    rest_client = SimpleNamespace(get_sdk_client=lambda: sdk_client)

    reference = command_runtime.get_admin_api_spot_market_reference(
        "BTC-USDC",
        rest_client=rest_client,
    )

    assert reference == {
        "product_id": "BTC-USDC",
        "best_bid": "64197.77",
        "source": "coinbase_rest_best_bid",
        "observed_at": "2026-07-11T08:53:40.658107Z",
    }
    assert best_bid_calls == [{"product_ids": ["BTC-USDC"]}]



class _PermissionsClient:
    def __init__(
        self,
        response: object,
        *,
        portfolios: list[dict[str, object]] | None = None,
    ) -> None:
        self.response = response
        self.calls = 0
        response_dict = response if isinstance(response, dict) else {}
        portfolio_id = response_dict.get("portfolio_uuid")
        portfolio_type = response_dict.get("portfolio_type")
        default_label = "Test" if portfolio_type == "CONSUMER" else "Default"
        self.portfolios = portfolios or [
            {
                "uuid": portfolio_id,
                "name": default_label,
                "type": portfolio_type,
            }
        ]

    def get_api_key_permissions(self) -> object:
        self.calls += 1
        return self.response

    def list_portfolios(self) -> list[dict[str, object]]:
        return self.portfolios


def test_spot_portfolio_binding_requires_backend_configured_test_uuid() -> None:
    client = _PermissionsClient(
        {
            "portfolio_uuid": TEST_PORTFOLIO_ID,
            "portfolio_type": "CONSUMER",
            "can_view": True,
            "can_trade": True,
        }
    )

    evidence = evaluate_spot_test_portfolio_binding(
        rest_client=client,
        expected_portfolio_id=None,
    )

    assert evidence.ready is False
    assert evidence.blocker == "spot_test_portfolio_id_missing"
    assert evidence.observed_portfolio_id is None
    assert client.calls == 0


def test_spot_portfolio_binding_rejects_default_profile_key() -> None:
    client = _PermissionsClient(
        {
            "portfolio_uuid": DEFAULT_PORTFOLIO_ID,
            "portfolio_type": "DEFAULT",
            "can_view": True,
            "can_trade": True,
        }
    )

    evidence = evaluate_spot_test_portfolio_binding(
        rest_client=client,
        expected_portfolio_id=TEST_PORTFOLIO_ID,
    )

    assert evidence.ready is False
    assert evidence.blocker == "spot_test_portfolio_mismatch"
    assert evidence.expected_portfolio_id == TEST_PORTFOLIO_ID
    assert evidence.observed_portfolio_id == DEFAULT_PORTFOLIO_ID
    assert evidence.observed_portfolio_type == "DEFAULT"
    assert evidence.observed_portfolio_label == "Default"
    assert evidence.selection_authority == "cdp_api_key_permissioned_portfolio"
    assert evidence.request_portfolio_override_allowed is False
    assert client.calls == 1


def test_spot_portfolio_binding_requires_consumer_view_and_trade_permissions() -> None:
    wrong_type = evaluate_spot_test_portfolio_binding(
        rest_client=_PermissionsClient(
            {
                "portfolio_uuid": TEST_PORTFOLIO_ID,
                "portfolio_type": "DEFAULT",
                "can_view": True,
                "can_trade": True,
            }
        ),
        expected_portfolio_id=TEST_PORTFOLIO_ID,
    )
    no_view = evaluate_spot_test_portfolio_binding(
        rest_client=_PermissionsClient(
            {
                "portfolio_uuid": TEST_PORTFOLIO_ID,
                "portfolio_type": "CONSUMER",
                "can_view": False,
                "can_trade": True,
            }
        ),
        expected_portfolio_id=TEST_PORTFOLIO_ID,
    )
    no_trade = evaluate_spot_test_portfolio_binding(
        rest_client=_PermissionsClient(
            {
                "portfolio_uuid": TEST_PORTFOLIO_ID,
                "portfolio_type": "CONSUMER",
                "can_view": True,
                "can_trade": False,
            }
        ),
        expected_portfolio_id=TEST_PORTFOLIO_ID,
    )

    assert wrong_type.blocker == "spot_test_portfolio_type_mismatch"
    assert no_view.blocker == "spot_test_portfolio_view_permission_missing"
    assert no_trade.blocker == "spot_test_portfolio_trade_permission_missing"


def test_spot_portfolio_binding_requires_coinbase_observed_test_label() -> None:
    evidence = evaluate_spot_test_portfolio_binding(
        rest_client=_PermissionsClient(
            {
                "portfolio_uuid": TEST_PORTFOLIO_ID,
                "portfolio_type": "CONSUMER",
                "can_view": True,
                "can_trade": True,
            },
            portfolios=[
                {
                    "uuid": TEST_PORTFOLIO_ID,
                    "name": "Not Test",
                    "type": "CONSUMER",
                }
            ],
        ),
        expected_portfolio_id=TEST_PORTFOLIO_ID,
        expected_portfolio_label="Test",
    )

    assert evidence.ready is False
    assert evidence.blocker == "spot_test_portfolio_label_mismatch"
    assert evidence.observed_portfolio_label == "Not Test"


def test_spot_portfolio_binding_normalizes_sdk_response_and_passes() -> None:
    client = _PermissionsClient(
        SimpleNamespace(
            to_dict=lambda: {
                "portfolio_uuid": TEST_PORTFOLIO_ID,
                "portfolio_type": "CONSUMER",
                "can_view": True,
                "can_trade": True,
                "can_transfer": False,
            }
        ),
        portfolios=[
            {
                "uuid": TEST_PORTFOLIO_ID,
                "name": "Test",
                "type": "CONSUMER",
            }
        ],
    )

    evidence = require_spot_test_portfolio_binding(
        rest_client=client,
        expected_portfolio_id=TEST_PORTFOLIO_ID,
        expected_portfolio_label="Test",
    )

    assert evidence.ready is True
    assert evidence.blocker is None
    assert evidence.expected_portfolio_label == "Test"
    assert evidence.observed_portfolio_id == TEST_PORTFOLIO_ID
    assert evidence.observed_portfolio_type == "CONSUMER"
    assert evidence.observed_portfolio_label == "Test"
    assert evidence.can_view is True
    assert evidence.can_trade is True
    assert evidence.source == "coinbase_get_api_key_permissions"
    assert evidence.to_dict()["portfolio_id"] == TEST_PORTFOLIO_ID


def test_spot_portfolio_binding_fails_closed_when_permissions_are_unavailable() -> None:
    class _UnavailableClient:
        def get_api_key_permissions(self) -> object:
            raise RuntimeError("synthetic permissions failure")

    evidence = evaluate_spot_test_portfolio_binding(
        rest_client=_UnavailableClient(),
        expected_portfolio_id=TEST_PORTFOLIO_ID,
    )

    assert evidence.ready is False
    assert evidence.blocker == "spot_test_portfolio_permissions_unavailable"
    assert evidence.observed_portfolio_id is None
    with pytest.raises(
        SpotPortfolioBindingError,
        match="spot_test_portfolio_permissions_unavailable",
    ):
        require_spot_test_portfolio_binding(
            rest_client=_UnavailableClient(),
            expected_portfolio_id=TEST_PORTFOLIO_ID,
        )


def _live_spot_command() -> ManualOrderCommand:
    return ManualOrderCommand(
        envelope=AdminApiCommandEnvelope(
            idempotency_key="idem-spot-test-profile",
            correlation_id="corr-spot-test-profile",
            operator_intent="bounded_spot_test_order",
            actor=AdminApiActor(
                actor_id="operator-001",
                roles=[AdminApiRole.ADMIN],
            ),
        ),
        request=ManualOrderRequest.model_validate(
            {
                "client_order_id": "22daf1ea-4c57-4c03-98c5-e74459576228",
                "product_id": "BTC-USDC",
                "side": "BUY",
                "order_type": "LIMIT",
                "base_size": "0.00002",
                "limit_price": "65000.00",
                "post_only": True,
                "manual_live_acknowledgement": True,
            }
        ),
        admin_cap_guard_decision_id="cap-spot-test-profile",
        admin_max_submitted_notional_usdc="9.99",
        allow_live_execution=True,
    )


def test_manual_spot_order_fails_before_submit_when_key_is_bound_to_default() -> None:
    class _DefaultKeyClient(_PermissionsClient):
        def __init__(self) -> None:
            super().__init__(
                {
                    "portfolio_uuid": DEFAULT_PORTFOLIO_ID,
                    "portfolio_type": "DEFAULT",
                    "can_view": True,
                    "can_trade": True,
                }
            )
            self.create_order_calls: list[dict[str, object]] = []

        def create_order(self, **kwargs: object) -> object:
            self.create_order_calls.append(dict(kwargs))
            return {"success": True}

    rest_client = _DefaultKeyClient()
    service = AdminApiCommandService(
        AdminApiCommandDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_runtime_enabled=True,
            command_runtime_ready=True,
            spot_portfolio_id=TEST_PORTFOLIO_ID,
            spot_portfolio_label="Test",
        )
    )

    response = service.place_manual_order(_live_spot_command())

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "portfolio_scope"
    assert response.live_exchange_submitted is False
    assert response.live_coinbase_orders_ran is False
    assert response.data["portfolio_scope"]["blocker"] == (
        "spot_test_portfolio_mismatch"
    )
    assert response.data["portfolio_scope"]["observed_portfolio_id"] == (
        DEFAULT_PORTFOLIO_ID
    )
    assert rest_client.create_order_calls == []


def test_manual_spot_order_fails_before_permissions_read_without_configured_scope() -> None:
    rest_client = _PermissionsClient(
        {
            "portfolio_uuid": TEST_PORTFOLIO_ID,
            "portfolio_type": "CONSUMER",
            "can_view": True,
            "can_trade": True,
        }
    )
    service = AdminApiCommandService(
        AdminApiCommandDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_runtime_enabled=True,
            command_runtime_ready=True,
            spot_portfolio_id=None,
        )
    )

    response = service.place_manual_order(_live_spot_command())

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "portfolio_scope"
    assert response.data["portfolio_scope"]["blocker"] == (
        "spot_test_portfolio_id_missing"
    )
    assert rest_client.calls == 0


def test_command_runtime_readiness_requires_the_same_test_profile(monkeypatch) -> None:
    from application.admin_api import command_runtime

    monkeypatch.setenv(command_runtime.LIVE_EXECUTION_RUNTIME_ENABLED_ENV, "true")
    monkeypatch.setenv(command_runtime.SPOT_PORTFOLIO_ID_ENV, TEST_PORTFOLIO_ID)
    monkeypatch.setenv(command_runtime.SPOT_PORTFOLIO_LABEL_ENV, "Test")
    monkeypatch.setattr(command_runtime, "rest_credentials_configured", lambda: True)

    default_client = _PermissionsClient(
        {
            "portfolio_uuid": DEFAULT_PORTFOLIO_ID,
            "portfolio_type": "DEFAULT",
            "can_view": True,
            "can_trade": True,
        }
    )
    monkeypatch.setattr(
        command_runtime,
        "load_admin_api_rest_client",
        lambda: command_runtime.AdminApiRestClientBinding(
            client=default_client,
            available=True,
        ),
    )

    blocked = command_runtime.build_admin_api_command_runtime_readiness()

    assert blocked.runtime_ready is False
    assert blocked.missing_reason == "spot_test_portfolio_mismatch"
    assert blocked.spot_portfolio_scope["status"] == "blocked"
    assert blocked.spot_portfolio_scope["observed_portfolio_id"] == (
        DEFAULT_PORTFOLIO_ID
    )

    test_client = _PermissionsClient(
        {
            "portfolio_uuid": TEST_PORTFOLIO_ID,
            "portfolio_type": "CONSUMER",
            "can_view": True,
            "can_trade": True,
        }
    )
    monkeypatch.setattr(
        command_runtime,
        "load_admin_api_rest_client",
        lambda: command_runtime.AdminApiRestClientBinding(
            client=test_client,
            available=True,
        ),
    )

    ready = command_runtime.build_admin_api_command_runtime_readiness()

    assert ready.runtime_ready is True
    assert ready.missing_reason is None
    assert ready.spot_portfolio_scope["status"] == "matched"
    assert ready.spot_portfolio_scope["portfolio_id"] == TEST_PORTFOLIO_ID


def test_command_dependencies_report_test_profile_mismatch_as_not_ready(
    monkeypatch,
) -> None:
    from application.admin_api import command_runtime

    monkeypatch.setenv(command_runtime.LIVE_EXECUTION_RUNTIME_ENABLED_ENV, "true")
    monkeypatch.setenv(command_runtime.SPOT_PORTFOLIO_ID_ENV, TEST_PORTFOLIO_ID)
    monkeypatch.setenv(command_runtime.SPOT_PORTFOLIO_LABEL_ENV, "Test")
    monkeypatch.setattr(command_runtime, "rest_credentials_configured", lambda: True)
    monkeypatch.setattr(
        command_runtime,
        "load_admin_api_rest_client",
        lambda: command_runtime.AdminApiRestClientBinding(
            client=_PermissionsClient(
                {
                    "portfolio_uuid": DEFAULT_PORTFOLIO_ID,
                    "portfolio_type": "DEFAULT",
                    "can_view": True,
                    "can_trade": True,
                }
            ),
            available=True,
        ),
    )

    dependencies = command_runtime.build_admin_api_command_dependencies()

    assert dependencies.rest_client_available is True
    assert dependencies.command_runtime_ready is False
    assert dependencies.command_runtime_missing_reason == (
        "spot_test_portfolio_mismatch"
    )


def test_manual_spot_root_is_registered_with_test_scope_before_rest_submit(
    monkeypatch,
) -> None:
    import configuration

    events: list[tuple[str, dict[str, object]]] = []

    class _TestKeyClient(_PermissionsClient):
        def __init__(self) -> None:
            super().__init__(
                {
                    "portfolio_uuid": TEST_PORTFOLIO_ID,
                    "portfolio_type": "CONSUMER",
                    "can_view": True,
                    "can_trade": True,
                }
            )
            self.submitted_order: dict[str, object] | None = None

        def create_order(self, **kwargs: object) -> object:
            events.append(("rest", dict(kwargs)))
            self.submitted_order = {
                "client_order_id": kwargs["client_order_id"],
                "order_id": "exchange-test-root",
                "product_id": "BTC-USDC",
                "status": "OPEN",
            }
            return SimpleNamespace(success=True, order_id="exchange-test-root")

        def get_order(self, order_id: str):
            assert order_id == "exchange-test-root"
            return {"order": dict(self.submitted_order or {})}

        def list_orders(self, **kwargs: object):
            if kwargs.get("order_status") is not None:
                return {"orders": [], "has_next": False}
            return {
                "orders": [self.submitted_order] if self.submitted_order else [],
                "has_next": False,
            }

    class _RootRegistrar:
        def register_manual_spot_root(self, **kwargs: object) -> dict[str, object]:
            events.append(("root", dict(kwargs)))
            return {
                "registered": True,
                "source": "test_root_registrar",
                "parent_row_id": 41,
                "client_order_id": kwargs["client_order_id"],
                "retail_portfolio_id": kwargs["retail_portfolio_id"],
                "ownership_provenance": "ADMIN_MANUAL_ROOT",
            }

        def mark_submission_status(self, **kwargs: object) -> None:
            events.append(("status", dict(kwargs)))

        def get_unresolved_admin_manual_root_submissions(
            self,
            _retail_portfolio_id: str,
        ) -> list[dict[str, object]]:
            return []

    class _RuntimeController:
        def track_inflight(self, _name: str):
            return self

        def __enter__(self):
            return None

        def __exit__(self, *_args: object) -> bool:
            return False

    event_publisher = SimpleNamespace(
        enabled=True,
        publish_event=lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        configuration,
        "ACTION_CONDITION_GUARDS",
        {"wallet_available": False, "limits": []},
        raising=False,
    )
    service = AdminApiCommandService(
        AdminApiCommandDependencies(
            rest_client=_TestKeyClient(),
            rest_client_available=True,
            live_runtime_enabled=True,
            command_runtime_ready=True,
            spot_portfolio_id=TEST_PORTFOLIO_ID,
            spot_portfolio_label="Test",
            spot_market_reference_getter=lambda _product_id: {
                "best_bid": "130000.00",
                "source": "ticker",
                "observed_at": datetime.now(timezone.utc),
            },
            runtime_controller_factory=lambda: _RuntimeController(),
            order_event_publisher_getter=lambda: event_publisher,
            order_root_registrar_getter=lambda: _RootRegistrar(),
        )
    )

    response = service.place_manual_order(_live_spot_command())

    assert response.status == AdminApiCommandStatus.ACCEPTED
    assert [name for name, _payload in events] == ["root", "rest", "status"]
    root_payload = events[0][1]
    assert root_payload["retail_portfolio_id"] == TEST_PORTFOLIO_ID
    assert root_payload["client_order_id"] == (
        "22daf1ea-4c57-4c03-98c5-e74459576228"
    )
    assert root_payload["correlation_id"] == "corr-spot-test-profile"
    assert root_payload["audit_id"] is None
    assert Decimal(str(root_payload["base_size"])) == Decimal("0.00002")
    assert root_payload["limit_price"] == "65000.00"
    assert events[2][1]["status"] == "OPEN"
    assert response.data["root_registration"]["parent_row_id"] == 41


def test_manual_spot_root_registration_failure_prevents_rest_submit(
    monkeypatch,
) -> None:
    import configuration

    class _TestKeyClient(_PermissionsClient):
        def __init__(self) -> None:
            super().__init__(
                {
                    "portfolio_uuid": TEST_PORTFOLIO_ID,
                    "portfolio_type": "CONSUMER",
                    "can_view": True,
                    "can_trade": True,
                }
            )
            self.create_order_calls: list[dict[str, object]] = []

        def create_order(self, **kwargs: object) -> object:
            self.create_order_calls.append(dict(kwargs))
            return SimpleNamespace(success=True, order_id="must-not-submit")

        def list_orders(self, **_kwargs: object):
            return {"orders": [], "has_next": False}

    class _FailingRootRegistrar:
        def get_unresolved_admin_manual_root_submissions(
            self,
            _retail_portfolio_id: str,
        ) -> list[dict[str, object]]:
            return []

        def register_manual_spot_root(self, **_kwargs: object) -> dict[str, object]:
            raise RuntimeError("synthetic root persistence failure")

    monkeypatch.setattr(
        configuration,
        "ACTION_CONDITION_GUARDS",
        {"wallet_available": False, "limits": []},
        raising=False,
    )
    rest_client = _TestKeyClient()
    event_publisher = SimpleNamespace(enabled=True)
    service = AdminApiCommandService(
        AdminApiCommandDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_runtime_enabled=True,
            command_runtime_ready=True,
            spot_portfolio_id=TEST_PORTFOLIO_ID,
            spot_portfolio_label="Test",
            spot_market_reference_getter=lambda _product_id: {
                "best_bid": "130000.00",
                "source": "ticker",
                "observed_at": datetime.now(timezone.utc),
            },
            order_event_publisher_getter=lambda: event_publisher,
            order_root_registrar_getter=lambda: _FailingRootRegistrar(),
        )
    )

    response = service.place_manual_order(_live_spot_command())

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "order_root_registration"
    assert "synthetic root persistence failure" in response.message
    assert response.live_exchange_submitted is False
    assert rest_client.create_order_calls == []


def test_runtime_root_registrar_persists_and_hydrates_exact_test_scope() -> None:
    from application.admin_api.command_runtime import (
        AdminApiOrderRootRuntimeRegistrar,
    )

    class _DbModule:
        def __init__(self) -> None:
            self.insert_calls: list[dict[str, object]] = []
            self.status_calls: list[tuple[str, str]] = []
            self.unresolved_calls: list[str] = []

        def insert_order_parent(self, **kwargs: object) -> int:
            self.insert_calls.append(dict(kwargs))
            return 73

        def update_order_parent_status(self, client_order_id: str, status: str) -> None:
            self.status_calls.append((client_order_id, status))

        def get_unresolved_admin_manual_root_submissions(
            self,
            retail_portfolio_id: str,
        ) -> list[dict[str, object]]:
            self.unresolved_calls.append(retail_portfolio_id)
            return [{"client_order_id": "unresolved-root", "status": "OPEN"}]

    db_module = _DbModule()
    engine = SimpleNamespace(
        db_module=db_module,
        orderbook=SimpleNamespace(default_max_order_replacement=11),
        resolve_profit_target=lambda _order: 0.004,
        _seed_parent_order_cache_from_db=lambda _client_order_id: True,
    )
    registrar = AdminApiOrderRootRuntimeRegistrar(engine)

    evidence = registrar.register_manual_spot_root(
        client_order_id="22daf1ea-4c57-4c03-98c5-e74459576228",
        product_id="BTC-USDC",
        side="BUY",
        base_size="0.00001",
        limit_price="65000.00",
        retail_portfolio_id=TEST_PORTFOLIO_ID,
    )
    registrar.mark_submission_status(
        client_order_id="22daf1ea-4c57-4c03-98c5-e74459576228",
        status="SUBMITTED",
    )
    unresolved = registrar.get_unresolved_admin_manual_root_submissions(
        TEST_PORTFOLIO_ID
    )

    assert evidence["parent_row_id"] == 73
    assert evidence["retail_portfolio_id"] == TEST_PORTFOLIO_ID
    assert db_module.insert_calls[0]["retail_portfolio_id"] == TEST_PORTFOLIO_ID
    assert db_module.insert_calls[0]["target_movement"] == 0.004
    assert db_module.insert_calls[0]["max_order_replacement"] == 11
    assert db_module.insert_calls[0]["ownership_provenance"] == (
        "ADMIN_MANUAL_ROOT"
    )
    assert evidence["ownership_provenance"] == "ADMIN_MANUAL_ROOT"
    assert db_module.status_calls == [
        ("22daf1ea-4c57-4c03-98c5-e74459576228", "SUBMITTED")
    ]
    assert unresolved == [
        {"client_order_id": "unresolved-root", "status": "OPEN"}
    ]
    assert db_module.unresolved_calls == [TEST_PORTFOLIO_ID]


def test_manual_spot_buy_above_half_bid_is_rejected_before_root_or_rest(
    monkeypatch,
) -> None:
    import configuration

    class _TestKeyClient(_PermissionsClient):
        def __init__(self) -> None:
            super().__init__(
                {
                    "portfolio_uuid": TEST_PORTFOLIO_ID,
                    "portfolio_type": "CONSUMER",
                    "can_view": True,
                    "can_trade": True,
                }
            )
            self.create_order_calls: list[dict[str, object]] = []

        def list_orders(self, order_status=None):
            return {"orders": []}

        def create_order(self, **kwargs: object) -> object:
            self.create_order_calls.append(dict(kwargs))
            return SimpleNamespace(success=True, order_id="must-not-submit")

    root_registrar = SimpleNamespace(
        register_manual_spot_root=Mock(return_value={"registered": True}),
    )
    monkeypatch.setattr(
        configuration,
        "ACTION_CONDITION_GUARDS",
        {"wallet_available": False, "limits": []},
        raising=False,
    )
    rest_client = _TestKeyClient()
    service = AdminApiCommandService(
        AdminApiCommandDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_runtime_enabled=True,
            command_runtime_ready=True,
            spot_portfolio_id=TEST_PORTFOLIO_ID,
            spot_portfolio_label="Test",
            spot_market_reference_getter=lambda _product_id: {
                "best_bid": "100.00",
                "source": "ticker",
                "observed_at": datetime.now(timezone.utc),
            },
            order_event_publisher_getter=lambda: SimpleNamespace(enabled=True),
            order_root_registrar_getter=lambda: root_registrar,
        )
    )
    command = _live_spot_command()
    command.request = command.request.model_copy(
        update={"base_size": "0.02", "limit_price": "60.00"}
    )

    response = service.place_manual_order(command)

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "standing_price_limit"
    assert response.data["standing_price_limit"]["maximum_limit_price"] == (
        "50.000"
    )
    assert root_registrar.register_manual_spot_root.call_count == 0
    assert rest_client.create_order_calls == []


def test_manual_spot_submit_requires_no_existing_open_order(monkeypatch) -> None:
    import configuration

    class _TestKeyClient(_PermissionsClient):
        def __init__(self) -> None:
            super().__init__(
                {
                    "portfolio_uuid": TEST_PORTFOLIO_ID,
                    "portfolio_type": "CONSUMER",
                    "can_view": True,
                    "can_trade": True,
                }
            )
            self.create_order_calls: list[dict[str, object]] = []

        def list_orders(self, **_kwargs: object):
            return {
                "orders": [
                    {
                        "client_order_id": "existing-test-order",
                        "order_id": "exchange-existing-test-order",
                        "status": "OPEN",
                        "product_id": "BTC-USDC",
                    }
                ],
                "has_next": False,
            }

        def create_order(self, **kwargs: object) -> object:
            self.create_order_calls.append(dict(kwargs))
            return SimpleNamespace(success=True, order_id="must-not-submit")

    root_registrar = SimpleNamespace(
        register_manual_spot_root=Mock(return_value={"registered": True}),
        get_unresolved_admin_manual_root_submissions=Mock(return_value=[]),
    )
    monkeypatch.setattr(
        configuration,
        "ACTION_CONDITION_GUARDS",
        {"wallet_available": False, "limits": []},
        raising=False,
    )
    rest_client = _TestKeyClient()
    service = AdminApiCommandService(
        AdminApiCommandDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_runtime_enabled=True,
            command_runtime_ready=True,
            spot_portfolio_id=TEST_PORTFOLIO_ID,
            spot_portfolio_label="Test",
            spot_market_reference_getter=lambda _product_id: {
                "best_bid": "100.00",
                "source": "ticker",
                "observed_at": datetime.now(timezone.utc),
            },
            order_event_publisher_getter=lambda: SimpleNamespace(enabled=True),
            order_root_registrar_getter=lambda: root_registrar,
        )
    )
    command = _live_spot_command()
    command.request = command.request.model_copy(
        update={"base_size": "0.02", "limit_price": "50.00"}
    )

    response = service.place_manual_order(command)

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "active_order_limit"
    assert response.data["active_order_limit"]["open_order_count"] == 1
    assert response.data["active_order_limit"]["cancel_before_next"] is True
    assert root_registrar.register_manual_spot_root.call_count == 0
    assert rest_client.create_order_calls == []


def test_manual_spot_cancel_uses_client_id_and_confirms_cancelled_terminal_status() -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"

    class _TestKeyClient(_PermissionsClient):
        def __init__(self) -> None:
            super().__init__(
                {
                    "portfolio_uuid": TEST_PORTFOLIO_ID,
                    "portfolio_type": "CONSUMER",
                    "can_view": True,
                    "can_trade": True,
                }
            )
            self.cancel_exchange_calls: list[str] = []
            self.cancel_client_calls: list[str] = []
            self.order = {
                "client_order_id": client_order_id,
                "order_id": "exchange-test-order",
                "product_id": "BTC-USDC",
                "status": "OPEN",
            }

        def list_orders(self, **_kwargs: object):
            return {"orders": [dict(self.order)], "has_next": False}

        def get_order(self, order_id: str):
            assert order_id == "exchange-test-order"
            return {"order": dict(self.order)}

        def cancel_order_by_exchange_order_id(self, order_id: str) -> bool:
            self.cancel_exchange_calls.append(order_id)
            return True

        def cancel_order(self, client_order_id: str) -> bool:
            self.cancel_client_calls.append(client_order_id)
            self.order["status"] = "CANCELLED"
            return True

    class _RootRegistrar:
        def read_registered_order(self, requested_client_order_id: str):
            assert requested_client_order_id == client_order_id
            return {
                "client_order_id": client_order_id,
                "retail_portfolio_id": TEST_PORTFOLIO_ID,
                "ownership_provenance": "ADMIN_MANUAL_ROOT",
                "parent_order_id": None,
                "product_id": "BTC-USDC",
            }

        def mark_submission_status(self, **_kwargs: object) -> None:
            return None

    class _RuntimeController:
        def track_inflight(self, _name: str):
            return self

        def __enter__(self):
            return None

        def __exit__(self, *_args: object) -> bool:
            return False

    rest_client = _TestKeyClient()
    service = AdminApiCommandService(
        AdminApiCommandDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_runtime_enabled=True,
            command_runtime_ready=True,
            spot_portfolio_id=TEST_PORTFOLIO_ID,
            spot_portfolio_label="Test",
            order_root_registrar_getter=lambda: _RootRegistrar(),
            runtime_controller_factory=lambda: _RuntimeController(),
        )
    )
    command = CancelOrderCommand(
        envelope=AdminApiCommandEnvelope(
            idempotency_key="idem-cancel-test-order",
            correlation_id="corr-cancel-test-order",
            operator_intent="cancel_bounded_test_order",
            actor=AdminApiActor(
                actor_id="operator-001",
                roles=[AdminApiRole.ADMIN],
            ),
        ),
        client_order_id=client_order_id,
        request=CancelOrderRequest(
            reason="cancel before another order",
            manual_live_acknowledgement=True,
        ),
        allow_live_execution=True,
    )

    response = service.cancel_order_by_client_order_id(command)

    assert response.status == AdminApiCommandStatus.ACCEPTED
    assert rest_client.cancel_client_calls == [client_order_id]
    assert rest_client.cancel_exchange_calls == []
    assert response.data["portfolio_scope"]["status"] == "matched"
    cancellation = response.data["cancellation_readback"]
    assert cancellation["operator_identity_key"] == "client_order_id"
    assert cancellation["canonical_cancel_attempted"] is True
    assert cancellation["fallback_attempted"] is False
    assert cancellation["authoritative_status"] == "CANCELLED"
    assert cancellation["terminal_status_proven"] is True


def test_test_profile_runtime_rejects_derivatives_before_submit() -> None:
    class _TestKeyClient(_PermissionsClient):
        def __init__(self) -> None:
            super().__init__(
                {
                    "portfolio_uuid": TEST_PORTFOLIO_ID,
                    "portfolio_type": "CONSUMER",
                    "can_view": True,
                    "can_trade": True,
                }
            )
            self.create_order_calls: list[dict[str, object]] = []

        def create_order(self, **kwargs: object) -> object:
            self.create_order_calls.append(dict(kwargs))
            return {"success": True}

    rest_client = _TestKeyClient()
    service = AdminApiCommandService(
        AdminApiCommandDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_runtime_enabled=True,
            command_runtime_ready=True,
            spot_portfolio_id=TEST_PORTFOLIO_ID,
            spot_portfolio_label="Test",
        )
    )
    command = _live_spot_command()
    command.request = command.request.model_copy(
        update={
            "product_id": "BIP-20DEC30-CDE",
            "base_size": "1",
            "quote_size": None,
            "limit_price": "1",
        }
    )

    response = service.place_manual_order(command)

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "portfolio_scope"
    assert response.data["portfolio_scope"]["blocker"] == (
        "spot_test_runtime_product_type_mismatch"
    )
    assert rest_client.create_order_calls == []
