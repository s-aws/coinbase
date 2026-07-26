from __future__ import annotations

from decimal import Decimal
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from application.admin_api.command_service import (
    AdminApiCommandDependencies,
    AdminApiCommandService,
)
from application.admin_api.models import AdminApiCommandResponse
from application.admin_api.operator_hotpoint_control import (
    HOTPOINT_GOAL_ID,
    HotpointCancelPlan,
    HotpointPlacementOutcome,
    HotpointPlacementPlan,
)
from application.admin_api.operator_hotpoint_runtime import (
    AdminApiHotpointCancelExecutor,
    AdminApiHotpointPlacementExecutor,
    UnavailableFuturesHotpointControlService,
    evaluate_operator_futures_hotpoint_execution_posture,
)
from application.admin_api.live_execution import (
    CONFIGURED_LIVE_EXECUTION_SERVICE_SOURCE,
)
from application.admin_api.operator_mvp_policy import (
    OPERATOR_MVP_HOTPOINT_SINGLE_CHILD_CREATE_ROUTE,
    OPERATOR_MVP_HOTPOINT_SINGLE_CHILD_SAFE_CLOSEOUT_ROUTE,
)
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiPermission,
    AdminApiLiveExecutionStatus,
    OrderSide,
    OrderType,
    TimeInForce,
)


PARENT_ID = "11111111-1111-4111-8111-111111111111"
CHILD_ID = "22222222-2222-4222-8222-222222222222"
PORTFOLIO_ID = "66666666-6666-4666-8666-666666666666"


def _plan() -> HotpointPlacementPlan:
    return HotpointPlacementPlan(
        goal_id=HOTPOINT_GOAL_ID,
        window_id="33333333-3333-4333-8333-333333333333",
        placement_claim_id="44444444-4444-4444-8444-444444444444",
        parent_client_order_id=PARENT_ID,
        child_client_order_id=CHILD_ID,
        product_id="BTC-USDC",
        side="BUY",
        base_size=Decimal("0.00001"),
        limit_price=Decimal("100000"),
        post_only=True,
        submitted_notional_usdc=Decimal("1.00000"),
        possible_execution_notional_usdc=Decimal("1.00000"),
        max_submitted_notional_usdc=Decimal("3.10"),
        max_possible_execution_notional_usdc=Decimal("1.00"),
        evidence_sha256="a" * 64,
        portfolio_id=PORTFOLIO_ID,
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="corr-1",
        audit_id="55555555-5555-4555-8555-555555555555",
    )


def _response(
    *,
    status: AdminApiCommandStatus,
    client_order_id: str | None = CHILD_ID,
    invoked: bool,
    error: str | None = None,
) -> AdminApiCommandResponse:
    return AdminApiCommandResponse(
        status=status,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        required_permission=AdminApiPermission.ORDER_CREATE,
        service_method="place_hotpoint_test_order",
        message="fixed",
        client_order_id=client_order_id,
        live_exchange_submitted=invoked,
        live_coinbase_orders_ran=invoked,
        data={"error": error} if error else None,
    )


class _CommandService:
    def __init__(self, response: AdminApiCommandResponse) -> None:
        self.response = response
        self.commands = []
        self.cancel_commands = []

    def place_hotpoint_test_order(self, command):
        self.commands.append(command)
        return self.response

    def cancel_order_by_client_order_id(self, command):
        self.cancel_commands.append(command)
        return self.response


class _RuntimeController:
    def track_inflight(self, _name):
        return nullcontext()


class _Publisher:
    def publish_event(self, **_kwargs):
        return True


def test_executor_composes_exact_backend_owned_hotpoint_command() -> None:
    command_service = _CommandService(
        _response(
            status=AdminApiCommandStatus.ACCEPTED,
            invoked=True,
        )
    )
    executor = AdminApiHotpointPlacementExecutor(
        command_service_getter=lambda: command_service,
    )

    result = executor(_plan())

    assert result.outcome is HotpointPlacementOutcome.ACCEPTED
    assert result.child_client_order_id == CHILD_ID
    assert result.exchange_invoked is True
    [command] = command_service.commands
    assert command.hotpoint_goal_id == HOTPOINT_GOAL_ID
    assert command.hotpoint_parent_client_order_id == PARENT_ID
    assert command.hotpoint_plan_sha256 == "a" * 64
    assert command.hotpoint_portfolio_id == PORTFOLIO_ID
    assert command.allow_live_execution is True
    assert command.admin_max_submitted_notional_usdc == "3.10"
    assert command.admin_max_executed_notional_usdc == "1.00"
    assert command.request.client_order_id == CHILD_ID
    assert command.request.product_id == "BTC-USDC"
    assert command.request.side is OrderSide.BUY
    assert command.request.order_type is OrderType.LIMIT
    assert command.request.base_size == "0.00001"
    assert command.request.limit_price == "100000"
    assert command.request.post_only is True
    assert command.request.time_in_force is TimeInForce.GOOD_UNTIL_CANCELLED
    assert command.request.manual_live_acknowledgement is True


def test_executor_preserves_fixed_rejected_and_unknown_boundaries() -> None:
    cases = (
        (
            _response(
                status=AdminApiCommandStatus.REJECTED,
                invoked=True,
                error="operator_hotpoint_create_rejected",
            ),
            HotpointPlacementOutcome.REJECTED,
            True,
        ),
        (
            _response(
                status=AdminApiCommandStatus.REJECTED,
                invoked=True,
                error="operator_hotpoint_create_outcome_unknown",
            ),
            HotpointPlacementOutcome.UNKNOWN,
            True,
        ),
        (
            _response(
                status=AdminApiCommandStatus.REJECTED,
                invoked=False,
            ),
            HotpointPlacementOutcome.REJECTED,
            False,
        ),
    )

    for response, expected_outcome, expected_invoked in cases:
        result = AdminApiHotpointPlacementExecutor(
            command_service_getter=lambda response=response: _CommandService(
                response
            ),
        )(_plan())
        assert result.outcome is expected_outcome
        assert result.exchange_invoked is expected_invoked
        assert result.child_client_order_id is None


def test_executor_fails_closed_on_response_identity_or_adapter_exception() -> None:
    mismatch = _response(
        status=AdminApiCommandStatus.ACCEPTED,
        client_order_id=PARENT_ID,
        invoked=True,
    )
    result = AdminApiHotpointPlacementExecutor(
        command_service_getter=lambda: _CommandService(mismatch),
    )(_plan())
    assert result.outcome is HotpointPlacementOutcome.UNKNOWN
    assert result.exchange_invoked is True

    def explode():
        raise RuntimeError("withheld")

    result = AdminApiHotpointPlacementExecutor(
        command_service_getter=explode,
    )(_plan())
    assert result.outcome is HotpointPlacementOutcome.UNKNOWN
    assert result.exchange_invoked is False


def test_goal_bound_command_service_uses_exact_child_and_provenance(
    monkeypatch: pytest.MonkeyPatch,
    coinbase_execution_lease,
) -> None:
    import configuration

    monkeypatch.setenv("COINBASE_EXECUTION_ENABLED", "1")
    monkeypatch.setattr(
        configuration,
        "ACTION_CONDITION_GUARDS",
        {"wallet_available": False, "limits": []},
        raising=False,
    )
    inserted = []
    status_updates = []

    class RestClient:
        calls = []

        def limit_order_gtc(self, **kwargs):
            self.calls.append(dict(kwargs))
            return {
                "success": True,
                "success_response": {"order_id": "exchange-evidence-1"},
            }

    rest_client = RestClient()
    command_service = AdminApiCommandService(
        AdminApiCommandDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_runtime_enabled=True,
            command_runtime_ready=True,
            spot_portfolio_id=PORTFOLIO_ID,
            spot_portfolio_label="Test",
            runtime_controller_factory=lambda: _RuntimeController(),
            order_event_publisher_getter=lambda: _Publisher(),
            insert_order_parent=lambda **kwargs: inserted.append(kwargs) or 1,
            update_order_parent_status=lambda order_id, status: (
                status_updates.append((order_id, status))
            ),
        )
    )

    result = AdminApiHotpointPlacementExecutor(
        command_service_getter=lambda: command_service,
    )(_plan())

    assert result.outcome is HotpointPlacementOutcome.ACCEPTED
    assert status_updates == []
    assert inserted == [
        {
            "client_order_id": CHILD_ID,
            "product_id": "BTC-USDC",
            "side": "BUY",
            "size": 0.00001,
            "price": 100000.0,
            "target_movement": 0.0,
            "target_movement_type": "P",
            "max_order_replacement": 0,
            "current_order_replacement": 0,
            "status": "PENDING",
            "parent_order_id": PARENT_ID,
            "allow_partial_fills": False,
            "enable_hotpoint_replication": False,
            "auto_placed_by_hotpoint": True,
            "ownership_provenance": "ADMIN_HOTPOINT_CHILD",
            "retail_portfolio_id": PORTFOLIO_ID,
        }
    ]
    assert rest_client.calls == [
        {
            "product_id": "BTC-USDC",
            "side": "BUY",
            "base_size": "1e-05",
            "limit_price": "100000.0",
            "client_order_id": CHILD_ID,
            "post_only": True,
        }
    ]


def test_cancel_executor_composes_exact_backend_owned_child_command() -> None:
    response = AdminApiCommandResponse(
        status=AdminApiCommandStatus.ACCEPTED,
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        required_permission=AdminApiPermission.ORDER_CANCEL,
        service_method="cancel_order_by_client_order_id",
        message="fixed",
        client_order_id=CHILD_ID,
        live_exchange_submitted=True,
        live_coinbase_orders_ran=True,
    )
    command_service = _CommandService(response)
    plan = HotpointCancelPlan(
        goal_id=HOTPOINT_GOAL_ID,
        cancel_claim_id="77777777-7777-4777-8777-777777777777",
        placement_claim_id="44444444-4444-4444-8444-444444444444",
        parent_client_order_id=PARENT_ID,
        child_client_order_id=CHILD_ID,
        product_id="BTC-USDC",
        plan_sha256="a" * 64,
        portfolio_id=PORTFOLIO_ID,
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="corr-1",
        audit_id="55555555-5555-4555-8555-555555555555",
    )

    result = AdminApiHotpointCancelExecutor(
        command_service_getter=lambda: command_service,
    )(plan)

    assert result.outcome is HotpointPlacementOutcome.ACCEPTED
    assert result.child_client_order_id == CHILD_ID
    assert result.exchange_invoked is True
    [command] = command_service.cancel_commands
    assert command.client_order_id == CHILD_ID
    assert command.allow_live_execution is True
    assert command.hotpoint_goal_id == HOTPOINT_GOAL_ID
    assert command.hotpoint_parent_client_order_id == PARENT_ID
    assert command.hotpoint_plan_sha256 == "a" * 64
    assert command.hotpoint_portfolio_id == PORTFOLIO_ID
    assert command.request.manual_live_acknowledgement is True


def test_runtime_exposes_call_free_futures_readback_without_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import application.admin_api.operator_hotpoint_runtime as runtime

    class SharedGoalService:
        def read(self):
            from application.admin_api.operator_hotpoint_control import (
                HotpointCancelState,
                HotpointCreateState,
                HotpointKillSwitchState,
                HotpointWindowState,
                OperatorHotpointControlRecord,
            )

            return OperatorHotpointControlRecord(
                goal_id=HOTPOINT_GOAL_ID,
                revision=0,
                kill_switch_state=HotpointKillSwitchState.DISABLED,
                window_state=HotpointWindowState.NONE,
                parent_client_order_id=None,
                product_id=None,
                side=None,
                window_id=None,
                window_started_at=None,
                window_expires_at=None,
                create_state=HotpointCreateState.NOT_CLAIMED,
                cancel_state=HotpointCancelState.NOT_CLAIMED,
                create_exchange_invoked=None,
                cancel_exchange_invoked=None,
                placement_claim_id=None,
                cancel_claim_id=None,
                child_client_order_id=None,
                diagnostic_code="operator_hotpoint_disabled",
                actor_id="system",
                roles=(),
                correlation_id="not_recorded",
                audit_id="00000000-0000-0000-0000-000000000000",
                recorded_at="1970-01-01T00:00:00+00:00",
                updated_at="1970-01-01T00:00:00+00:00",
            )

    shared = SharedGoalService()
    monkeypatch.delenv(
        "COINBASE_ADMIN_API_FUTURES_PORTFOLIO_ID",
        raising=False,
    )
    monkeypatch.setattr(runtime, "_DEFAULT_FUTURES_SERVICE", None)
    monkeypatch.setattr(
        runtime,
        "get_default_operator_hotpoint_control_service",
        lambda: shared,
    )

    services = runtime.get_default_operator_hotpoint_control_services()

    assert services["SPOT"] is shared
    assert isinstance(
        services["FUTURES"],
        UnavailableFuturesHotpointControlService,
    )
    readback = services["FUTURES"].read()
    assert readback.diagnostic_code == (
        "operator_futures_hotpoint_portfolio_not_configured"
    )
    assert services["FUTURES"].list_eligible_parents(
        limit=25,
        offset=0,
    ) == ([], 0)


def test_runtime_futures_v2_flag_selects_goal13_without_historical_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import application.admin_api.operator_hotpoint_runtime as runtime

    shared = object()
    goal13 = object()
    goal13_builds: list[str] = []
    monkeypatch.setattr(
        runtime,
        "get_default_operator_hotpoint_control_service",
        lambda: shared,
    )
    monkeypatch.setattr(runtime, "_DEFAULT_FUTURES_SERVICE", None)
    monkeypatch.setattr(
        runtime,
        "_DEFAULT_FUTURES_V2_SERVICE",
        None,
        raising=False,
    )
    monkeypatch.setattr(
        runtime,
        "_build_default_operator_futures_hotpoint_v2_service",
        lambda: goal13_builds.append("goal13") or goal13,
        raising=False,
    )

    monkeypatch.delenv(
        "COINBASE_ADMIN_API_OPERATOR_FUTURES_HOTPOINT_V2_ENABLED",
        raising=False,
    )
    historical = runtime.get_default_operator_hotpoint_control_services()
    assert isinstance(
        historical["FUTURES"],
        UnavailableFuturesHotpointControlService,
    )
    assert goal13_builds == []

    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_FUTURES_HOTPOINT_V2_ENABLED",
        "1",
    )
    selected = runtime.get_default_operator_hotpoint_control_services()
    assert selected == {"SPOT": shared, "FUTURES": goal13}
    assert goal13_builds == ["goal13"]


def test_futures_hotpoint_posture_requires_both_exact_routes_not_spot_caps(
) -> None:
    state = SimpleNamespace(
        required=True,
        present=True,
        status=AdminApiLiveExecutionStatus.APPROVAL_REQUIRED,
        source=CONFIGURED_LIVE_EXECUTION_SERVICE_SOURCE,
        missing_reason=None,
        max_submitted_notional_usdc=None,
        max_executed_notional_usdc=None,
        supported_routes=frozenset(
            {
                (
                    "POST",
                    OPERATOR_MVP_HOTPOINT_SINGLE_CHILD_CREATE_ROUTE,
                ),
                (
                    "POST",
                    OPERATOR_MVP_HOTPOINT_SINGLE_CHILD_SAFE_CLOSEOUT_ROUTE,
                ),
            }
        ),
    )
    defaults = {
        "feature_enabled": True,
        "execution_authority_enabled": True,
        "live_runtime_enabled": True,
        "credentials_configured": True,
        "rest_client_available": True,
        "portfolio_configured": True,
        "live_service_state": state,
    }

    ready = evaluate_operator_futures_hotpoint_execution_posture(**defaults)
    assert ready.ready is True
    assert ready.diagnostic_code == (
        "operator_futures_hotpoint_execution_posture_ready"
    )

    missing_closeout = evaluate_operator_futures_hotpoint_execution_posture(
        **{
            **defaults,
            "live_service_state": SimpleNamespace(
                **{
                    **vars(state),
                    "supported_routes": frozenset(
                        {
                            (
                                "POST",
                                OPERATOR_MVP_HOTPOINT_SINGLE_CHILD_CREATE_ROUTE,
                            )
                        }
                    ),
                }
            ),
        }
    )
    assert missing_closeout.ready is False
    assert missing_closeout.diagnostic_code == (
        "operator_futures_hotpoint_service_decision_unavailable"
    )


def test_goal13_schema_installs_canonical_futures_projection_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from database import operator_futures_order_operations as futures_orders_db
    from database import operator_hotpoint_control as hotpoint_db

    events: list[str] = []

    class _Repository:
        def __init__(self, name: str) -> None:
            self.name = name

        def ensure_schema(self) -> None:
            events.append(f"{self.name}:ensure")

        def recover_stranded_claim(self) -> None:
            events.append(f"{self.name}:recover")

    monkeypatch.setenv(
        "COINBASE_ADMIN_API_FUTURES_PORTFOLIO_ID",
        "11111111-2222-4333-8444-555555555555",
    )
    monkeypatch.setattr(
        hotpoint_db,
        "get_default_operator_hotpoint_control_repository",
        lambda: _Repository("spot"),
    )
    monkeypatch.setattr(
        hotpoint_db,
        "get_default_operator_futures_hotpoint_control_repository",
        lambda: _Repository("futures_hotpoint"),
    )
    monkeypatch.setattr(
        futures_orders_db,
        "get_default_operator_futures_order_operations_repository",
        lambda: _Repository("futures_projection"),
    )

    hotpoint_db.initialize_operator_hotpoint_control_schema()

    assert events == [
        "spot:ensure",
        "spot:recover",
        "futures_projection:ensure",
        "futures_hotpoint:ensure",
        "futures_hotpoint:recover",
    ]
