from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
import sys
import uuid

import pytest

from application.admin_api.command_service import (
    CONTROLLED_FIRST_CHILD_CANCEL_OPERATOR_INTENT,
    CONTROLLED_FIRST_CHILD_REVEAL_OPERATOR_INTENT,
    CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT,
    CONTROLLED_V15_FIRST_CHILD_REVEAL_OPERATOR_INTENT,
    AdminApiCommandDependencies,
    AdminApiCommandService,
)
from application.admin_api.command_runtime import (
    AdminApiControlledFirstChildRuntimeAdapter,
)
from application.admin_api.models import (
    AdminApiActor,
    AdminApiCommandEnvelope,
    StealthCancelCommand,
    StealthCancelRequest,
    StealthRevealCommand,
    StealthRevealRequest,
)
from core.enums import AdminApiCommandStatus, OrderStatus
from core.exceptions import (
    ControlledChildPrePlacementError,
    OrderPersistenceError,
)


TEST_PORTFOLIO_ID = "62f28f44-8e72-4fe0-ace7-d71a01f54883"
ROOT_ID = "11111111-1111-4111-8111-111111111111"
CHILD_ID = str(
    uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"coinbase://filled-follow-up/{ROOT_ID}/{ROOT_ID}",
    )
)
EXCHANGE_ID = "33333333-3333-4333-8333-333333333333"
BATCH_ID = "test-profile-root-child-repeatability-20260711"
PLAN_SHA256 = "a" * 64
SEALED_PLAN_SHA256 = "b" * 64


@pytest.fixture(autouse=True)
def _exact_live_execution_authority(
    monkeypatch: pytest.MonkeyPatch,
    coinbase_execution_lease,
) -> None:
    monkeypatch.setenv("COINBASE_EXECUTION_ENABLED", "1")


class _ClaimTrackingCoordinator:
    def __init__(self, *, uncertainties=None):
        self.claimed = False
        self.claim_observations = []
        self.uncertainties = list(uncertainties or [])
        self.recorded_uncertainties = []

    @contextmanager
    def claim(self, _portfolio_id):
        assert self.claimed is False
        self.claimed = True
        try:
            yield
        finally:
            self.claimed = False

    def uncertainty_snapshot(self, _portfolio_id):
        return list(self.uncertainties)

    def record_uncertainty(self, **kwargs):
        self.recorded_uncertainties.append(dict(kwargs))
        return None

    def resolve_uncertainty(self, **_kwargs):
        return None


def _envelope(operator_intent: str) -> AdminApiCommandEnvelope:
    return AdminApiCommandEnvelope(
        idempotency_key=f"idem-{operator_intent}",
        correlation_id=f"corr-{operator_intent}",
        operator_intent=operator_intent,
        actor=AdminApiActor(
            actor_id="operator@example.com",
            roles=["trader"],
        ),
    )


def _portfolio_binding() -> SimpleNamespace:
    evidence = {
        "ready": True,
        "status": "matched",
        "profile_alias": "Test",
        "expected_portfolio_id": TEST_PORTFOLIO_ID,
        "observed_portfolio_id": TEST_PORTFOLIO_ID,
    }
    return SimpleNamespace(
        ready=True,
        observed_portfolio_id=TEST_PORTFOLIO_ID,
        to_dict=lambda: dict(evidence),
    )


def _reveal_command(
    *,
    allow_live_execution: bool = True,
    operator_intent: str = CONTROLLED_FIRST_CHILD_REVEAL_OPERATOR_INTENT,
    max_notional: str = "2.00",
    prior_preparation_sha256: str | None = None,
    controlled_plan_sha256: str | None = None,
) -> StealthRevealCommand:
    return StealthRevealCommand(
        envelope=_envelope(operator_intent),
        stealth_order_id=CHILD_ID,
        request=StealthRevealRequest(
            reason="controlled Test-profile first-child submission",
            manual_live_acknowledgement=True,
            expected_root_client_order_id=ROOT_ID,
            controlled_limit_price="102400.00",
            controlled_batch_id=BATCH_ID,
            controlled_batch_slot=1,
            controlled_plan_sha256=controlled_plan_sha256,
            controlled_prior_preparation_sha256=(
                prior_preparation_sha256
            ),
        ),
        allow_live_execution=allow_live_execution,
        admin_approval_snapshot_id="approval-child-1",
        admission_audit_id="audit-child-1",
        admin_cap_guard_decision_id="cap-child-1",
        admin_reconciliation_plan_id="recon-child-1",
        admin_max_submitted_notional_usdc=max_notional,
    )


def _cancel_command(
    *,
    allow_live_execution: bool = True,
    operator_intent: str = CONTROLLED_FIRST_CHILD_CANCEL_OPERATOR_INTENT,
    controlled_plan_sha256: str | None = None,
) -> StealthCancelCommand:
    return StealthCancelCommand(
        envelope=_envelope(operator_intent),
        stealth_order_id=CHILD_ID,
        request=StealthCancelRequest(
            reason="cancel controlled Test-profile first child before next root",
            manual_live_acknowledgement=True,
            expected_root_client_order_id=ROOT_ID,
            controlled_batch_id=BATCH_ID,
            controlled_batch_slot=1,
            controlled_plan_sha256=controlled_plan_sha256,
        ),
        allow_live_execution=allow_live_execution,
        admin_approval_snapshot_id="approval-cancel-1",
        admission_audit_id="audit-cancel-1",
        admin_cap_guard_decision_id="cap-cancel-1",
        admin_reconciliation_plan_id="recon-cancel-1",
    )


def _deps(
    runtime: MagicMock,
    rest_client: MagicMock | None = None,
    *,
    controlled_cancel_plan: dict | None = None,
):
    rest_client = rest_client or MagicMock()
    rest_client.list_orders.return_value = {
        "orders": [],
        "has_next": False,
    }
    dependencies = AdminApiCommandDependencies(
        rest_client=rest_client,
        rest_client_available=True,
        live_runtime_enabled=True,
        command_runtime_ready=True,
        spot_portfolio_id=TEST_PORTFOLIO_ID,
        spot_portfolio_label="Test",
        stealth_order_runtime_getter=lambda: runtime,
        order_event_publisher_getter=lambda: SimpleNamespace(
            enabled=True,
            publish_event=MagicMock(return_value=True),
        ),
        order_root_registrar_getter=lambda: SimpleNamespace(
            mark_submission_status=MagicMock(return_value=1),
        ),
    )
    if controlled_cancel_plan is not None:
        dependencies.controlled_v15_plan_authority_getter = lambda: {
            "plan": controlled_cancel_plan,
        }
    return dependencies


def _controlled_cancel_recovery_plan(schema_version: str) -> dict:
    authority_kind = {
        "23": "selected_chain_child_cancel_recovery_v15r5",
        "24": "selected_chain_child_cancel_recovery_v15r6",
    }[schema_version]
    cancel_command = {
        "root_client_order_id": ROOT_ID,
        "child_client_order_id": CHILD_ID,
        "active_exchange_order_id_evidence": EXCHANGE_ID,
        "operator_intent": CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT,
        "idempotency_key": (
            f"idem-{CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT}"
        ),
        "correlation_id": (
            f"corr-{CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT}"
        ),
        "approval_snapshot_id": "approval-cancel-1",
        "cap_guard_decision_id": "cap-cancel-1",
        "reconciliation_plan_id": "recon-cancel-1",
    }
    return {
        "schema_version": schema_version,
        "authority_kind": authority_kind,
        "plan_sha256": SEALED_PLAN_SHA256,
        "batch_id": f"sealed-v15r{schema_version}-batch",
        "actor_id": "operator@example.com",
        "actor_roles": ["trader"],
        "exchange_cancel_submission_identity": (
            "authoritative_exchange_order_id_resolved_from_client_order_id"
        ),
        "cancel_command": cancel_command,
        "child": {
            "client_order_id": CHILD_ID,
            "parent_client_order_id": ROOT_ID,
            "active_exchange_order_id": EXCHANGE_ID,
            "origin_controlled_plan_sha256": PLAN_SHA256,
            "origin_controlled_batch_id": BATCH_ID,
        },
        "v15r2_active_child_binding": {
            "r2_plan_sha256": PLAN_SHA256,
            "r2_batch_id": BATCH_ID,
            "root_client_order_id": ROOT_ID,
            "child_client_order_id": CHILD_ID,
            "child_exchange_order_id": EXCHANGE_ID,
        },
        "local_active_child_binding": {
            "root_client_order_id": ROOT_ID,
            "child_client_order_id": CHILD_ID,
            "child_exchange_order_id": EXCHANGE_ID,
            "active_placement_client_order_id": CHILD_ID,
            "active_exchange_order_id": EXCHANGE_ID,
            "controlled_plan_sha256": PLAN_SHA256,
            "controlled_batch_id": BATCH_ID,
        },
    }


@pytest.mark.parametrize(
    "lineage_drift",
    [
        "child_origin_plan",
        "child_origin_batch",
        "local_runtime_plan",
        "local_runtime_batch",
    ],
)
def test_v15r6_verified_exchange_submission_rejects_runtime_lineage_drift(
    monkeypatch,
    lineage_drift,
):
    from application.admin_api import command_service as command_service_module

    plan = _controlled_cancel_recovery_plan("24")
    if lineage_drift == "child_origin_plan":
        plan["child"]["origin_controlled_plan_sha256"] = "c" * 64
    elif lineage_drift == "child_origin_batch":
        plan["child"]["origin_controlled_batch_id"] = "other-batch"
    elif lineage_drift == "local_runtime_plan":
        plan["local_active_child_binding"]["controlled_plan_sha256"] = "c" * 64
    else:
        plan["local_active_child_binding"]["controlled_batch_id"] = "other-batch"
    monkeypatch.setattr(
        command_service_module,
        "validate_controlled_child_cancel_plan_scope",
        lambda _plan: None,
    )
    dependencies = SimpleNamespace(
        controlled_v15_plan_authority_getter=lambda: {"plan": plan},
    )

    assert command_service_module._root_child_cancel_v15r6_exchange_submission_context(
        dependencies,
        _cancel_command(
            operator_intent=CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT,
            controlled_plan_sha256=PLAN_SHA256,
        ),
        submission_required=True,
        sealed_cancel_plan_sha256=SEALED_PLAN_SHA256,
        exchange_order_id=EXCHANGE_ID,
    ) == (True, False)


def test_v15r6_real_plan_shape_authorizes_its_delegated_r2_child_lineage():
    from application.admin_api import command_service as command_service_module
    from tests.unit.test_admin_api_root_child_cancel_v15r3 import _v15r6_plan

    plan = _v15r6_plan()
    cancel = dict(plan["cancel_command"])
    lineage = command_service_module._root_child_cancel_delegate_lineage(
        plan,
        command_plan_sha256=str(plan["plan_sha256"]),
        command_batch_id=str(plan["batch_id"]),
    )
    command = StealthCancelCommand(
        envelope=AdminApiCommandEnvelope(
            idempotency_key=str(cancel["idempotency_key"]),
            correlation_id=str(cancel["correlation_id"]),
            operator_intent=str(cancel["operator_intent"]),
            actor=AdminApiActor(
                actor_id=str(plan["actor_id"]),
                roles=list(plan["actor_roles"]),
            ),
        ),
        stealth_order_id=str(plan["child"]["client_order_id"]),
        request=StealthCancelRequest(
            reason="cancel exact sealed V15R6 child",
            manual_live_acknowledgement=True,
            expected_root_client_order_id=str(
                plan["root_evidence"]["client_order_id"]
            ),
            controlled_batch_id=str(lineage["controlled_batch_id"]),
            controlled_batch_slot=1,
            controlled_plan_sha256=str(lineage["controlled_plan_sha256"]),
        ),
        allow_live_execution=True,
        admin_approval_snapshot_id=str(cancel["approval_snapshot_id"]),
        admission_audit_id="route-bound-audit",
        admin_cap_guard_decision_id=str(cancel["cap_guard_decision_id"]),
        admin_reconciliation_plan_id=str(cancel["reconciliation_plan_id"]),
    )
    dependencies = SimpleNamespace(
        controlled_v15_plan_authority_getter=lambda: {"plan": plan},
    )

    assert lineage["controlled_plan_sha256"] == (
        plan["v15r2_active_child_binding"]["r2_plan_sha256"]
    )
    assert lineage["controlled_plan_sha256"] != plan["plan_sha256"]
    assert command_service_module._root_child_cancel_v15r6_exchange_submission_context(
        dependencies,
        command,
        submission_required=True,
        sealed_cancel_plan_sha256=str(plan["plan_sha256"]),
        exchange_order_id=str(plan["child"]["active_exchange_order_id"]),
    ) == (True, True)


def _runtime_adapter_success_evidence():
    authority = SimpleNamespace(
        prepared_limit_price=102400.0,
        total_size=0.00001718,
        reference_notional_usdc=1.759232,
    )
    order = {
        "stealth_order_id": CHILD_ID,
        "parent_order_id": ROOT_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "total_size": 0.00001718,
        "status": "REVEALED",
        "revealed_orders": [
            {
                "placed_order_id": CHILD_ID,
                "exchange_order_id": EXCHANGE_ID,
                "placement_success": True,
                "placement_status": "placed",
                "submitted_limit_price": 102400.0,
            }
        ],
    }
    return authority, order


def _submit_runtime_adapter(
    adapter,
    *,
    prior_preparation_sha256=None,
    controlled_plan_sha256=None,
):
    return adapter.submit_controlled_first_child(
        stealth_order_id=CHILD_ID,
        expected_root_client_order_id=ROOT_ID,
        expected_portfolio_id=TEST_PORTFOLIO_ID,
        submitted_limit_price="102400.00",
        max_notional_usdc="2.00",
        approval_snapshot_id="approval-child-1",
        admission_audit_id="audit-child-1",
        cap_guard_decision_id="cap-child-1",
        reconciliation_plan_id="recon-child-1",
        controlled_batch_id=BATCH_ID,
        controlled_batch_slot=1,
        controlled_plan_sha256=controlled_plan_sha256,
        expected_prior_preparation_sha256=prior_preparation_sha256,
    )


def test_controlled_child_reveal_stays_disabled_without_route_admission():
    runtime = MagicMock()
    service = AdminApiCommandService(_deps(runtime))

    response = service.reveal_stealth_order_by_stealth_order_id(
        _reveal_command(allow_live_execution=False)
    )

    assert response.status == AdminApiCommandStatus.NOT_IMPLEMENTED
    assert response.live_exchange_submitted is False
    runtime.submit_controlled_first_child.assert_not_called()


@pytest.mark.parametrize(
    "mutation",
    [
        {"operator_intent": "generic_stealth_reveal"},
        {"manual_live_acknowledgement": False},
        {"expected_root_client_order_id": None},
        {"controlled_limit_price": None},
        {"controlled_batch_id": None},
        {"controlled_batch_slot": None},
    ],
)
def test_controlled_child_reveal_rejects_incomplete_exact_context(
    monkeypatch,
    mutation,
):
    monkeypatch.setattr(
        "application.admin_api.command_service.evaluate_spot_test_portfolio_binding",
        lambda **_kwargs: _portfolio_binding(),
    )
    runtime = MagicMock()
    command = _reveal_command(operator_intent=mutation.pop("operator_intent", CONTROLLED_FIRST_CHILD_REVEAL_OPERATOR_INTENT))
    if mutation:
        command.request = command.request.model_copy(update=mutation)
    service = AdminApiCommandService(_deps(runtime))

    response = service.reveal_stealth_order_by_stealth_order_id(command)

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.live_exchange_submitted is False
    runtime.submit_controlled_first_child.assert_not_called()


def test_controlled_child_reveal_rejects_cap_over_hard_limit(monkeypatch):
    monkeypatch.setattr(
        "application.admin_api.command_service.evaluate_spot_test_portfolio_binding",
        lambda **_kwargs: _portfolio_binding(),
    )
    runtime = MagicMock()
    service = AdminApiCommandService(_deps(runtime))

    response = service.reveal_stealth_order_by_stealth_order_id(
        _reveal_command(max_notional="2.01")
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "controlled_child_cap"
    runtime.submit_controlled_first_child.assert_not_called()


def test_controlled_child_reveal_holds_profile_claim_during_active_order_read(
    monkeypatch,
):
    monkeypatch.setattr(
        "application.admin_api.command_service.evaluate_spot_test_portfolio_binding",
        lambda **_kwargs: _portfolio_binding(),
    )
    coordinator = _ClaimTrackingCoordinator()
    rest_client = MagicMock()

    def list_orders(**_kwargs):
        coordinator.claim_observations.append(coordinator.claimed)
        return {
            "orders": [
                {
                    "client_order_id": "active-client",
                    "order_id": "active-exchange",
                    "status": "OPEN",
                }
            ],
            "has_next": False,
        }

    rest_client.list_orders.side_effect = list_orders
    runtime = MagicMock()
    dependencies = _deps(runtime, rest_client)
    dependencies.spot_order_admission_coordinator = coordinator
    service = AdminApiCommandService(dependencies)

    response = service.reveal_stealth_order_by_stealth_order_id(_reveal_command())

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "active_order_limit"
    assert coordinator.claim_observations == [True]
    assert coordinator.claimed is False
    runtime.submit_controlled_first_child.assert_not_called()


def test_controlled_child_reveal_blocks_prior_profile_uncertainty_under_claim(
    monkeypatch,
):
    monkeypatch.setattr(
        "application.admin_api.command_service.evaluate_spot_test_portfolio_binding",
        lambda **_kwargs: _portfolio_binding(),
    )
    coordinator = _ClaimTrackingCoordinator(
        uncertainties=[
            {
                "client_order_id": "prior-child",
                "reason": "prior_submission_unknown",
            }
        ]
    )
    rest_client = MagicMock()
    runtime = MagicMock()
    dependencies = _deps(runtime, rest_client)
    dependencies.spot_order_admission_coordinator = coordinator
    service = AdminApiCommandService(dependencies)

    response = service.reveal_stealth_order_by_stealth_order_id(_reveal_command())

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "submission_uncertainty"
    assert response.data["runtime_submission_uncertainties"][0][
        "client_order_id"
    ] == "prior-child"
    rest_client.list_orders.assert_not_called()
    runtime.submit_controlled_first_child.assert_not_called()


@pytest.mark.parametrize(
    ("operator_intent", "controlled_plan_sha256"),
    [
        (CONTROLLED_FIRST_CHILD_REVEAL_OPERATOR_INTENT, None),
        (CONTROLLED_V15_FIRST_CHILD_REVEAL_OPERATOR_INTENT, PLAN_SHA256),
    ],
)
def test_controlled_child_reveal_submits_once_and_requires_exact_readback(
    monkeypatch,
    operator_intent,
    controlled_plan_sha256,
):
    monkeypatch.setattr(
        "application.admin_api.command_service.evaluate_spot_test_portfolio_binding",
        lambda **_kwargs: _portfolio_binding(),
    )
    monkeypatch.setattr(
        "application.admin_api.command_service.exact_coinbase_order_readback",
        lambda *_args, **_kwargs: {
            "authoritative": True,
            "exact_identity_match": True,
            "confirmed_absent": False,
            "authoritative_status": "OPEN",
            "exchange_order_id": EXCHANGE_ID,
            "matched_order": {
                "client_order_id": CHILD_ID,
                "order_id": EXCHANGE_ID,
                "product_id": "BTC-USDC",
                "product_type": "SPOT",
                "side": "SELL",
                "status": "OPEN",
                "retail_portfolio_id": TEST_PORTFOLIO_ID,
                "order_type": "LIMIT",
                "limit_price": "102400.00",
                "base_size": "0.00001718",
                "filled_size": "0",
                "time_in_force": "GOOD_UNTIL_CANCELLED",
                "post_only": False,
                "order_configuration": {
                    "limit_limit_gtc": {
                        "base_size": "0.00001718",
                        "limit_price": "102400.00",
                        "post_only": False,
                    }
                },
            },
        },
    )
    runtime = MagicMock()
    runtime.submit_controlled_first_child.return_value = {
        "placed_client_order_id": CHILD_ID,
        "exchange_order_id": EXCHANGE_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "base_size": "0.00001718",
        "submitted_limit_price": "102400.00",
        "post_only": False,
        "placement_attempted": True,
        "placement_succeeded": True,
        "controlled_plan_sha256": controlled_plan_sha256,
    }
    service = AdminApiCommandService(_deps(runtime))

    response = service.reveal_stealth_order_by_stealth_order_id(
        _reveal_command(
            operator_intent=operator_intent,
            controlled_plan_sha256=controlled_plan_sha256,
        )
    )

    assert response.status == AdminApiCommandStatus.ACCEPTED
    assert response.stealth_order_id == CHILD_ID
    assert response.coinbase_order_id == EXCHANGE_ID
    assert response.live_exchange_submitted is True
    assert response.data["submission_readback"]["authoritative_status"] == "OPEN"
    runtime.submit_controlled_first_child.assert_called_once()
    kwargs = runtime.submit_controlled_first_child.call_args.kwargs
    assert kwargs["stealth_order_id"] == CHILD_ID
    assert kwargs["expected_root_client_order_id"] == ROOT_ID
    assert kwargs["expected_portfolio_id"] == TEST_PORTFOLIO_ID
    assert kwargs["controlled_batch_slot"] == 1
    assert kwargs["max_notional_usdc"] == "2.00"
    assert kwargs["expected_prior_preparation_sha256"] is None
    assert kwargs["controlled_plan_sha256"] == controlled_plan_sha256
    if controlled_plan_sha256 is None:
        assert "controlled_plan_sha256" not in response.data
    else:
        assert response.data["controlled_plan_sha256"] == controlled_plan_sha256


@pytest.mark.parametrize(
    "operator_intent",
    [
        CONTROLLED_V15_FIRST_CHILD_REVEAL_OPERATOR_INTENT,
        CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT,
    ],
)
def test_v15_controlled_child_commands_require_plan_hash(operator_intent):
    runtime = MagicMock()
    service = AdminApiCommandService(_deps(runtime))

    if operator_intent == CONTROLLED_V15_FIRST_CHILD_REVEAL_OPERATOR_INTENT:
        response = service.reveal_stealth_order_by_stealth_order_id(
            _reveal_command(operator_intent=operator_intent)
        )
        runtime.submit_controlled_first_child.assert_not_called()
    else:
        response = service.cancel_stealth_order_by_stealth_order_id(
            _cancel_command(operator_intent=operator_intent)
        )
        runtime.read_controlled_first_child.assert_not_called()

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "controlled_child_context"


@pytest.mark.parametrize("outer_authority", [None, "0", "true", "yes", "01"])
@pytest.mark.parametrize("command_kind", ["reveal", "cancel"])
def test_controlled_child_live_commands_require_exact_outer_authority_without_delegating(
    monkeypatch: pytest.MonkeyPatch,
    outer_authority: str | None,
    command_kind: str,
) -> None:
    if outer_authority is None:
        monkeypatch.delenv("COINBASE_EXECUTION_ENABLED", raising=False)
    else:
        monkeypatch.setenv("COINBASE_EXECUTION_ENABLED", outer_authority)

    runtime = MagicMock()
    rest_client = MagicMock()
    dependencies = _deps(runtime, rest_client)
    rest_client.reset_mock()
    service = AdminApiCommandService(dependencies)

    if command_kind == "reveal":
        response = service.reveal_stealth_order_by_stealth_order_id(
            _reveal_command()
        )
    else:
        response = service.cancel_stealth_order_by_stealth_order_id(
            _cancel_command()
        )

    assert response.status == AdminApiCommandStatus.NOT_IMPLEMENTED
    assert response.failure_stage == "execution_authority"
    assert response.live_command_runtime_enabled is False
    assert response.live_command_runtime_ready is False
    assert response.live_command_runtime_missing_reason == (
        "coinbase_execution_authority_disabled"
    )
    runtime.assert_not_called()
    assert runtime.mock_calls == []
    assert rest_client.mock_calls == []


def test_v15_controlled_child_reveal_rejects_runtime_plan_hash_mismatch(
    monkeypatch,
):
    monkeypatch.setattr(
        "application.admin_api.command_service.evaluate_spot_test_portfolio_binding",
        lambda **_kwargs: _portfolio_binding(),
    )
    runtime = MagicMock()
    runtime.submit_controlled_first_child.return_value = {
        "placed_client_order_id": CHILD_ID,
        "exchange_order_id": EXCHANGE_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "base_size": "0.00001718",
        "submitted_limit_price": "102400.00",
        "post_only": False,
        "placement_attempted": True,
        "placement_succeeded": True,
        "controlled_plan_sha256": "b" * 64,
    }
    dependencies = _deps(runtime)
    dependencies.spot_order_admission_coordinator = _ClaimTrackingCoordinator()
    service = AdminApiCommandService(dependencies)

    response = service.reveal_stealth_order_by_stealth_order_id(
        _reveal_command(
            operator_intent=CONTROLLED_V15_FIRST_CHILD_REVEAL_OPERATOR_INTENT,
            controlled_plan_sha256=PLAN_SHA256,
        )
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "controlled_child_submission_unknown"
    assert response.live_exchange_submitted is True


@pytest.mark.parametrize(
    ("historical_product_id", "historical_product_type"),
    [
        ("BTC-USDC", "SPOT"),
        ("ETH-USDC", "SPOT"),
        ("BTC-PERP", "FUTURE"),
    ],
)
def test_controlled_child_recovery_blocks_account_wide_historical_identity(
    monkeypatch,
    historical_product_id,
    historical_product_type,
):
    monkeypatch.setattr(
        "application.admin_api.command_service.evaluate_spot_test_portfolio_binding",
        lambda **_kwargs: _portfolio_binding(),
    )
    rest_client = MagicMock()
    rest_client.list_orders.side_effect = [
        {"orders": [], "has_next": False},
        {
            "orders": [
                {
                    "client_order_id": CHILD_ID,
                    "order_id": EXCHANGE_ID,
                    "product_id": historical_product_id,
                    "product_type": historical_product_type,
                    "status": "CANCELLED",
                }
            ],
            "has_next": False,
        },
    ]
    runtime = MagicMock()
    service = AdminApiCommandService(_deps(runtime, rest_client))

    response = service.reveal_stealth_order_by_stealth_order_id(
        _reveal_command(prior_preparation_sha256="a" * 64)
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "controlled_child_recovery_exchange_absence"
    assert response.live_exchange_submitted is False
    assert response.live_coinbase_orders_ran is False
    assert response.data["recovery_exchange_absence"][
        "authoritative_status"
    ] == "CANCELLED"
    runtime.submit_controlled_first_child.assert_not_called()
    assert rest_client.list_orders.call_count == 2
    recovery_query = rest_client.list_orders.call_args_list[1].kwargs
    assert "product_ids" not in recovery_query
    assert "product_type" not in recovery_query
    assert "order_status" not in recovery_query


def test_controlled_child_recovery_blocks_full_catalog_read_failure(monkeypatch):
    monkeypatch.setattr(
        "application.admin_api.command_service.evaluate_spot_test_portfolio_binding",
        lambda **_kwargs: _portfolio_binding(),
    )
    rest_client = MagicMock()
    rest_client.list_orders.side_effect = [
        {"orders": [], "has_next": False},
        RuntimeError("full catalog unavailable"),
    ]
    runtime = MagicMock()
    coordinator = _ClaimTrackingCoordinator()
    dependencies = _deps(runtime, rest_client)
    dependencies.spot_order_admission_coordinator = coordinator
    service = AdminApiCommandService(dependencies)

    response = service.reveal_stealth_order_by_stealth_order_id(
        _reveal_command(prior_preparation_sha256="a" * 64)
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "controlled_child_recovery_exchange_absence"
    assert response.live_exchange_submitted is False
    assert response.live_coinbase_orders_ran is False
    assert response.data["recovery_exchange_absence"]["authoritative"] is False
    assert coordinator.recorded_uncertainties == []
    runtime.submit_controlled_first_child.assert_not_called()


def test_controlled_child_recovery_proves_absence_before_single_submission(
    monkeypatch,
):
    monkeypatch.setattr(
        "application.admin_api.command_service.evaluate_spot_test_portfolio_binding",
        lambda **_kwargs: _portfolio_binding(),
    )
    events = []
    readbacks = iter(
        [
            {
                "authoritative": True,
                "pagination_complete": True,
                "client_order_id": CHILD_ID,
                "exchange_order_id": None,
                "exact_identity_match": False,
                "confirmed_absent": True,
                "authoritative_status": None,
                "matched_order": None,
            },
            {
                "authoritative": True,
                "pagination_complete": True,
                "client_order_id": CHILD_ID,
                "exchange_order_id": EXCHANGE_ID,
                "exact_identity_match": True,
                "confirmed_absent": False,
                "authoritative_status": "OPEN",
                "matched_order": {
                    "client_order_id": CHILD_ID,
                    "order_id": EXCHANGE_ID,
                    "product_id": "BTC-USDC",
                    "product_type": "SPOT",
                    "side": "SELL",
                    "status": "OPEN",
                    "retail_portfolio_id": TEST_PORTFOLIO_ID,
                    "order_type": "LIMIT",
                    "limit_price": "102400.00",
                    "base_size": "0.00001718",
                    "filled_size": "0",
                    "time_in_force": "GOOD_UNTIL_CANCELLED",
                    "post_only": False,
                    "order_configuration": {
                        "limit_limit_gtc": {
                            "base_size": "0.00001718",
                            "limit_price": "102400.00",
                            "post_only": False,
                        }
                    },
                },
            },
        ]
    )

    def readback(*_args, **_kwargs):
        item = next(readbacks)
        events.append(
            "readback_absence" if item["confirmed_absent"] else "readback_post"
        )
        return item

    monkeypatch.setattr(
        "application.admin_api.command_service.exact_coinbase_order_readback",
        readback,
    )
    runtime = MagicMock()

    def submit(**_kwargs):
        events.append("submit")
        return {
            "placed_client_order_id": CHILD_ID,
            "exchange_order_id": EXCHANGE_ID,
            "product_id": "BTC-USDC",
            "side": "SELL",
            "base_size": "0.00001718",
            "submitted_limit_price": "102400.00",
            "post_only": False,
            "placement_attempted": True,
            "placement_succeeded": True,
        }

    runtime.submit_controlled_first_child.side_effect = submit
    service = AdminApiCommandService(_deps(runtime))

    response = service.reveal_stealth_order_by_stealth_order_id(
        _reveal_command(prior_preparation_sha256="a" * 64)
    )

    assert response.status == AdminApiCommandStatus.ACCEPTED
    assert events == ["readback_absence", "submit", "readback_post"]
    kwargs = runtime.submit_controlled_first_child.call_args.kwargs
    assert kwargs["expected_prior_preparation_sha256"] == "a" * 64


def test_controlled_child_pre_placement_error_is_non_live_and_not_uncertain(
    monkeypatch,
):
    monkeypatch.setattr(
        "application.admin_api.command_service.evaluate_spot_test_portfolio_binding",
        lambda **_kwargs: _portfolio_binding(),
    )
    runtime = MagicMock()
    runtime.submit_controlled_first_child.side_effect = (
        ControlledChildPrePlacementError(
            "controlled reveal prior preparation hash mismatch",
            stage="preparation",
            cause_type="OrderPersistenceError",
            stealth_order_id=CHILD_ID,
        )
    )
    coordinator = _ClaimTrackingCoordinator()
    dependencies = _deps(runtime)
    dependencies.spot_order_admission_coordinator = coordinator
    service = AdminApiCommandService(dependencies)

    response = service.reveal_stealth_order_by_stealth_order_id(_reveal_command())

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "controlled_child_pre_placement"
    assert response.live_exchange_submitted is False
    assert response.live_coinbase_orders_ran is False
    assert response.data["pre_placement_failure"]["stage"] == "preparation"
    assert coordinator.recorded_uncertainties == []


def test_controlled_child_wrong_hash_rejection_never_crosses_reveal_boundary(
    monkeypatch,
):
    monkeypatch.setattr(
        "application.admin_api.command_service.evaluate_spot_test_portfolio_binding",
        lambda **_kwargs: _portfolio_binding(),
    )
    manager = MagicMock()
    manager.prepare_controlled_admin_first_child_reveal.side_effect = (
        OrderPersistenceError("controlled reveal prior preparation hash mismatch")
    )
    runtime = AdminApiControlledFirstChildRuntimeAdapter(
        manager,
        market_reference_getter=lambda _product_id: {
            "best_bid": "64000.00",
            "source": "coinbase_rest_best_bid",
            "observed_at": datetime.now(timezone.utc),
        },
    )
    coordinator = _ClaimTrackingCoordinator()
    dependencies = _deps(runtime)
    dependencies.spot_order_admission_coordinator = coordinator
    service = AdminApiCommandService(dependencies)

    response = service.reveal_stealth_order_by_stealth_order_id(
        _reveal_command(prior_preparation_sha256="0" * 64)
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "controlled_child_pre_placement"
    assert response.live_exchange_submitted is False
    assert response.live_coinbase_orders_ran is False
    assert coordinator.recorded_uncertainties == []
    manager.reveal_order_slice.assert_not_called()


def test_controlled_child_post_boundary_exception_remains_exchange_unknown(
    monkeypatch,
):
    monkeypatch.setattr(
        "application.admin_api.command_service.evaluate_spot_test_portfolio_binding",
        lambda **_kwargs: _portfolio_binding(),
    )
    runtime = MagicMock()
    runtime.submit_controlled_first_child.side_effect = RuntimeError(
        "placement response lost"
    )
    coordinator = _ClaimTrackingCoordinator()
    dependencies = _deps(runtime)
    dependencies.spot_order_admission_coordinator = coordinator
    service = AdminApiCommandService(dependencies)

    response = service.reveal_stealth_order_by_stealth_order_id(_reveal_command())

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "controlled_child_submission_unknown"
    assert response.live_exchange_submitted is True
    assert response.live_coinbase_orders_ran is True
    assert len(coordinator.recorded_uncertainties) == 1
    assert coordinator.recorded_uncertainties[0]["client_order_id"] == CHILD_ID


def test_controlled_child_reveal_rejects_authoritative_tuple_drift(monkeypatch):
    monkeypatch.setattr(
        "application.admin_api.command_service.evaluate_spot_test_portfolio_binding",
        lambda **_kwargs: _portfolio_binding(),
    )
    monkeypatch.setattr(
        "application.admin_api.command_service.exact_coinbase_order_readback",
        lambda *_args, **_kwargs: {
            "authoritative": True,
            "exact_identity_match": True,
            "authoritative_status": "OPEN",
            "exchange_order_id": EXCHANGE_ID,
            "matched_order": {
                "client_order_id": CHILD_ID,
                "order_id": EXCHANGE_ID,
                "product_id": "BTC-USDC",
                "product_type": "SPOT",
                "side": "SELL",
                "status": "OPEN",
                "retail_portfolio_id": TEST_PORTFOLIO_ID,
                "order_type": "LIMIT",
                "time_in_force": "GOOD_UNTIL_CANCELLED",
                "limit_price": "102399.99",
                "base_size": "0.00001718",
                "filled_size": "0",
                "post_only": False,
                "order_configuration": {
                    "limit_limit_gtc": {
                        "base_size": "0.00001718",
                        "limit_price": "102399.99",
                        "post_only": False,
                    }
                },
            },
        },
    )
    runtime = MagicMock()
    runtime.submit_controlled_first_child.return_value = {
        "placed_client_order_id": CHILD_ID,
        "exchange_order_id": EXCHANGE_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "base_size": "0.00001718",
        "submitted_limit_price": "102400.00",
        "post_only": False,
        "placement_attempted": True,
        "placement_succeeded": True,
    }
    service = AdminApiCommandService(_deps(runtime))

    response = service.reveal_stealth_order_by_stealth_order_id(_reveal_command())

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "controlled_child_submission_readback"
    assert response.live_exchange_submitted is True


def test_controlled_child_cancel_stays_disabled_without_route_admission():
    runtime = MagicMock()
    service = AdminApiCommandService(_deps(runtime))

    response = service.cancel_stealth_order_by_stealth_order_id(
        _cancel_command(allow_live_execution=False)
    )

    assert response.status == AdminApiCommandStatus.NOT_IMPLEMENTED
    runtime.read_controlled_first_child.assert_not_called()


@pytest.mark.parametrize(
    (
        "canonical_cancel_result",
        "exchange_id_fallback_used",
        "canonical_cancel_unknown",
    ),
    [
        (
            {
                "outcome": "succeeded",
                "explicit_rejection": False,
                "identity_rejection": False,
                "identity_match": True,
            },
            False,
            False,
        ),
        (
            {
                "outcome": "explicitly_rejected",
                "explicit_rejection": True,
                "identity_rejection": True,
                "identity_match": True,
            },
            True,
            False,
        ),
        (
            {
                "outcome": "unknown",
                "explicit_rejection": False,
                "identity_rejection": False,
                "identity_match": True,
                "failure_reasons": ["RATE_LIMITED"],
            },
            False,
            True,
        ),
        (
            RuntimeError("cancel transport outcome unknown"),
            False,
            True,
        ),
    ],
)
@pytest.mark.parametrize(
    (
        "operator_intent",
        "controlled_plan_sha256",
        "sealed_schema_version",
        "sealed_tuple_matches",
    ),
    [
        (CONTROLLED_FIRST_CHILD_CANCEL_OPERATOR_INTENT, None, None, True),
        (
            CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT,
            PLAN_SHA256,
            None,
            True,
        ),
        (
            CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT,
            PLAN_SHA256,
            "23",
            True,
        ),
        (
            CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT,
            PLAN_SHA256,
            "24",
            True,
        ),
        (
            CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT,
            PLAN_SHA256,
            "24",
            False,
        ),
    ],
)
def test_controlled_child_cancel_uses_canonical_identity_then_reconciles(
    monkeypatch,
    canonical_cancel_result,
    exchange_id_fallback_used,
    canonical_cancel_unknown,
    operator_intent,
    controlled_plan_sha256,
    sealed_schema_version,
    sealed_tuple_matches,
):
    from application.admin_api import command_service as command_service_module

    monkeypatch.setattr(
        "application.admin_api.command_service.evaluate_spot_test_portfolio_binding",
        lambda **_kwargs: _portfolio_binding(),
    )
    monkeypatch.setattr(
        command_service_module,
        "validate_controlled_child_cancel_plan_scope",
        lambda _plan: None,
    )
    monkeypatch.setattr(
        command_service_module,
        "is_controlled_v15r6_recovery_plan",
        lambda plan: plan.get("schema_version") == "24",
        raising=False,
    )
    readbacks = iter(
        [
            {
                "authoritative": True,
                "exact_identity_match": True,
                "authoritative_status": "OPEN",
                "exchange_order_id": EXCHANGE_ID,
                "matched_order": {
                    "client_order_id": CHILD_ID,
                    "order_id": EXCHANGE_ID,
                    "product_id": "BTC-USDC",
                    "product_type": "SPOT",
                    "side": "SELL",
                    "status": "OPEN",
                    "retail_portfolio_id": TEST_PORTFOLIO_ID,
                    "filled_size": "0",
                    "filled_value": "0",
                    "total_fees": "0",
                    "number_of_fills": 0,
                },
            },
            {
                "authoritative": True,
                "exact_identity_match": True,
                "authoritative_status": "CANCELLED",
                "exchange_order_id": EXCHANGE_ID,
                "matched_order": {
                    "client_order_id": CHILD_ID,
                    "order_id": EXCHANGE_ID,
                    "product_id": "BTC-USDC",
                    "product_type": "SPOT",
                    "side": "SELL",
                    "status": "CANCELLED",
                    "retail_portfolio_id": TEST_PORTFOLIO_ID,
                    "filled_size": "0",
                    "filled_value": "0",
                    "total_fees": "0",
                    "number_of_fills": 0,
                },
            },
        ]
    )
    monkeypatch.setattr(
        "application.admin_api.command_service.exact_coinbase_order_readback",
        lambda *_args, **_kwargs: next(readbacks),
    )
    rest_client = MagicMock()
    cancel_events = []

    def _canonical_cancel(*_args, **_kwargs):
        cancel_events.append("coinbase_client_order_id_cancel")
        if isinstance(canonical_cancel_result, BaseException):
            raise canonical_cancel_result
        return canonical_cancel_result

    rest_client.cancel_order.side_effect = _canonical_cancel
    rest_client.cancel_order_by_exchange_order_id.return_value = {
        "outcome": "succeeded",
        "explicit_rejection": False,
        "identity_rejection": False,
        "identity_match": True,
    }
    runtime = MagicMock()
    runtime.read_controlled_first_child.return_value = {
        "stealth_order_id": CHILD_ID,
        "root_client_order_id": ROOT_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "retail_portfolio_id": TEST_PORTFOLIO_ID,
        "status": "REVEALED",
        "active_placement_client_order_id": CHILD_ID,
        "active_exchange_order_id": EXCHANGE_ID,
        "executed_size": "0",
        "controlled_plan_sha256": controlled_plan_sha256,
    }
    runtime.reconcile_controlled_first_child_terminal.return_value = {
        "local_status": "CANCELLED",
        "active_placement_cleared": True,
    }
    fallback_cancel = rest_client.cancel_order_by_exchange_order_id
    controlled_cancel_plan = (
        _controlled_cancel_recovery_plan(sealed_schema_version)
        if sealed_schema_version is not None
        else None
    )
    if controlled_cancel_plan is not None and not sealed_tuple_matches:
        controlled_cancel_plan["cancel_command"] = {
            **controlled_cancel_plan["cancel_command"],
            "active_exchange_order_id_evidence": "different-exchange-order-id",
        }
    if sealed_schema_version == "24" and sealed_tuple_matches:
        rest_client.cancel_order_by_exchange_order_id = None
    service = AdminApiCommandService(
        _deps(
            runtime,
            rest_client,
            controlled_cancel_plan=controlled_cancel_plan,
        )
    )

    response = service.cancel_stealth_order_by_stealth_order_id(
        _cancel_command(
            operator_intent=operator_intent,
            controlled_plan_sha256=controlled_plan_sha256,
        ),
        semantic_boundary_callback=lambda: cancel_events.append(
            "durable_exchange_boundary"
        ),
        sealed_cancel_plan_sha256=(
            SEALED_PLAN_SHA256
            if sealed_schema_version is not None
            else None
        ),
        v15r6_verified_exchange_submission_required=(
            sealed_schema_version == "24"
        ),
    )

    if sealed_schema_version == "24" and not sealed_tuple_matches:
        assert response.status == AdminApiCommandStatus.REJECTED
        assert response.failure_stage == "controlled_child_context"
        assert response.live_exchange_submitted is False
        assert cancel_events == []
        rest_client.cancel_order.assert_not_called()
        fallback_cancel.assert_not_called()
        return

    verified_exchange_submission = sealed_schema_version == "24"
    expected_cancel_kwargs = {"return_evidence": True}
    if verified_exchange_submission:
        expected_cancel_kwargs["verified_exchange_order_id"] = EXCHANGE_ID
    rest_client.cancel_order.assert_called_once_with(
        CHILD_ID,
        **expected_cancel_kwargs,
    )
    assert cancel_events[:2] == [
        "durable_exchange_boundary",
        "coinbase_client_order_id_cancel",
    ]
    if canonical_cancel_unknown:
        assert response.status == AdminApiCommandStatus.REJECTED
        assert response.failure_stage == "cancellation_unknown"
        assert response.live_exchange_submitted is True
        fallback_cancel.assert_not_called()
        if verified_exchange_submission:
            identity = response.data["cancellation_identity"]
            assert identity["unknown_boundary"] == "verified_exchange_order_id"
            assert response.coinbase_order_id == EXCHANGE_ID
            if isinstance(canonical_cancel_result, BaseException):
                assert identity["canonical_cancel_evidence"] == {
                    "outcome": "unknown",
                    "attempted": True,
                    "explicit_rejection": False,
                    "exception_type": "RuntimeError",
                }
            else:
                assert identity[
                    "canonical_cancel_evidence"
                ] == canonical_cancel_result
            assert identity["submitted_identity_key"] == "exchange_order_id"
            assert identity["exchange_id_fallback_used"] is False
        return

    v15_cancel_rejected = bool(
        controlled_plan_sha256 is not None and exchange_id_fallback_used
    )
    assert response.status == (
        AdminApiCommandStatus.REJECTED
        if v15_cancel_rejected
        else AdminApiCommandStatus.ACCEPTED
    )
    if v15_cancel_rejected:
        assert response.failure_stage == "cancellation_rejected"
        if verified_exchange_submission:
            assert response.message == (
                "Verified exchange-order-id cancellation was explicitly "
                "rejected by Coinbase."
            )
            identity = response.data["cancellation_identity"]
            assert identity["operator_identity_key"] == "client_order_id"
            assert identity["operator_identity_value"] == CHILD_ID
            assert identity["exchange_order_id_evidence_only"] is True
            assert identity["exchange_order_id"] == EXCHANGE_ID
            assert identity["canonical_cancel_evidence"] == canonical_cancel_result
            assert identity["submitted_identity_key"] == "exchange_order_id"
            assert identity["exchange_id_fallback_used"] is False
        else:
            assert response.message == (
                "Exact exchange-id cancellation was not accepted."
            )
            assert "cancellation_identity" not in response.data
        fallback_cancel.assert_not_called()
        return
    assert response.coinbase_order_id == EXCHANGE_ID
    assert response.data["cancellation_readback"]["authoritative_status"] == "CANCELLED"
    if exchange_id_fallback_used:
        rest_client.cancel_order_by_exchange_order_id.assert_called_once_with(
            EXCHANGE_ID,
            return_evidence=True,
        )
    else:
        fallback_cancel.assert_not_called()
    assert response.data["cancellation_identity"]["operator_identity_key"] == (
        "client_order_id"
    )
    assert response.data["cancellation_identity"][
        "exchange_order_id_evidence_only"
    ] is True
    assert response.data["cancellation_identity"][
        "exchange_id_fallback_used"
    ] is exchange_id_fallback_used
    if verified_exchange_submission:
        assert response.data["cancellation_identity"][
            "submitted_identity_key"
        ] == "exchange_order_id"
        assert response.data["cancellation_identity"][
            "verified_exchange_order_id_cancel_attempted"
        ] is True
        assert response.data["cancellation_identity"][
            "canonical_client_order_id_cancel_attempted"
        ] is False
    else:
        assert "submitted_identity_key" not in response.data[
            "cancellation_identity"
        ]
        assert response.data["cancellation_identity"][
            "canonical_client_order_id_cancel_attempted"
        ] is True
    if controlled_plan_sha256 is None:
        assert "controlled_plan_sha256" not in response.data
    else:
        assert response.data["controlled_plan_sha256"] == controlled_plan_sha256
    assert runtime.read_controlled_first_child.call_args.kwargs[
        "controlled_plan_sha256"
    ] == controlled_plan_sha256
    runtime.reconcile_controlled_first_child_terminal.assert_called_once_with(
        stealth_order_id=CHILD_ID,
        authoritative_status=OrderStatus.CANCELLED.value,
        executed_size="0",
        exchange_order_id=EXCHANGE_ID,
    )


@pytest.mark.parametrize(
    ("post_submit_status", "expected_failure_stage"),
    [
        ("OPEN", "cancellation_readback"),
        ("FAILED", "cancellation_terminal_status"),
        ("CANCELLED", "cancellation_status_persistence"),
    ],
)
def test_v15r6_post_submit_readback_rejection_keeps_exchange_cancel_evidence(
    monkeypatch,
    post_submit_status,
    expected_failure_stage,
):
    from application.admin_api import command_service as command_service_module

    monkeypatch.setattr(
        command_service_module,
        "evaluate_spot_test_portfolio_binding",
        lambda **_kwargs: _portfolio_binding(),
    )
    monkeypatch.setattr(
        command_service_module,
        "validate_controlled_child_cancel_plan_scope",
        lambda _plan: None,
    )
    monkeypatch.setattr(
        command_service_module,
        "is_controlled_v15r6_recovery_plan",
        lambda plan: plan.get("schema_version") == "24",
        raising=False,
    )

    def _readback(status):
        return {
            "authoritative": True,
            "exact_identity_match": True,
            "authoritative_status": status,
            "exchange_order_id": EXCHANGE_ID,
            "matched_order": {
                "client_order_id": CHILD_ID,
                "order_id": EXCHANGE_ID,
                "product_id": "BTC-USDC",
                "product_type": "SPOT",
                "side": "SELL",
                "status": status,
                "retail_portfolio_id": TEST_PORTFOLIO_ID,
                "filled_size": "0",
                "filled_value": "0",
                "total_fees": "0",
                "number_of_fills": 0,
            },
        }

    readbacks = iter([_readback("OPEN"), _readback(post_submit_status)])
    monkeypatch.setattr(
        command_service_module,
        "exact_coinbase_order_readback",
        lambda *_args, **_kwargs: next(readbacks),
    )
    if post_submit_status == "OPEN":
        monotonic_values = iter([0.0, 10_000.0])
        monkeypatch.setattr(
            command_service_module.time,
            "monotonic",
            lambda: next(monotonic_values),
        )

    canonical_evidence = {
        "outcome": "succeeded",
        "explicit_rejection": False,
        "identity_rejection": False,
        "identity_match": True,
        "operator_identity_key": "client_order_id",
        "operator_identity_value": CHILD_ID,
        "exchange_order_id_evidence_only": True,
        "exchange_order_id": EXCHANGE_ID,
        "submitted_identity_key": "exchange_order_id",
    }
    rest_client = MagicMock()
    rest_client.cancel_order.return_value = canonical_evidence
    rest_client.cancel_order_by_exchange_order_id = None
    runtime = MagicMock()
    runtime.read_controlled_first_child.return_value = {
        "stealth_order_id": CHILD_ID,
        "root_client_order_id": ROOT_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "retail_portfolio_id": TEST_PORTFOLIO_ID,
        "status": "REVEALED",
        "active_placement_client_order_id": CHILD_ID,
        "active_exchange_order_id": EXCHANGE_ID,
        "executed_size": "0",
        "controlled_plan_sha256": PLAN_SHA256,
    }
    service = AdminApiCommandService(
        _deps(
            runtime,
            rest_client,
            controlled_cancel_plan=_controlled_cancel_recovery_plan("24"),
        )
    )

    response = service.cancel_stealth_order_by_stealth_order_id(
        _cancel_command(
            operator_intent=CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT,
            controlled_plan_sha256=PLAN_SHA256,
        ),
        sealed_cancel_plan_sha256=SEALED_PLAN_SHA256,
        v15r6_verified_exchange_submission_required=True,
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == expected_failure_stage
    assert response.live_exchange_submitted is True
    assert response.coinbase_order_id == EXCHANGE_ID
    identity = response.data["cancellation_identity"]
    assert identity == {
        "operator_identity_key": "client_order_id",
        "operator_identity_value": CHILD_ID,
        "exchange_order_id_evidence_only": True,
        "exchange_order_id": EXCHANGE_ID,
        "canonical_client_order_id_cancel_attempted": False,
        "canonical_cancel_evidence": canonical_evidence,
        "fallback_cancel_evidence": {
            "outcome": "not_attempted",
            "explicit_rejection": False,
        },
        "exchange_id_fallback_used": False,
        "canonical_cancel_attempted": True,
        "verified_exchange_order_id_cancel_attempted": True,
        "submitted_identity_key": "exchange_order_id",
    }
    rest_client.cancel_order.assert_called_once_with(
        CHILD_ID,
        return_evidence=True,
        verified_exchange_order_id=EXCHANGE_ID,
    )


def test_v15r6_pre_wrapper_inflight_failure_reports_zero_exchange_attempts(
    monkeypatch,
):
    from application.admin_api import command_service as command_service_module

    monkeypatch.setattr(
        command_service_module,
        "evaluate_spot_test_portfolio_binding",
        lambda **_kwargs: _portfolio_binding(),
    )
    monkeypatch.setattr(
        command_service_module,
        "validate_controlled_child_cancel_plan_scope",
        lambda _plan: None,
    )
    monkeypatch.setattr(
        command_service_module,
        "is_controlled_v15r6_recovery_plan",
        lambda plan: plan.get("schema_version") == "24",
        raising=False,
    )
    monkeypatch.setattr(
        command_service_module,
        "exact_coinbase_order_readback",
        lambda *_args, **_kwargs: {
            "authoritative": True,
            "exact_identity_match": True,
            "authoritative_status": "OPEN",
            "exchange_order_id": EXCHANGE_ID,
            "matched_order": {
                "client_order_id": CHILD_ID,
                "order_id": EXCHANGE_ID,
                "product_id": "BTC-USDC",
                "product_type": "SPOT",
                "side": "SELL",
                "status": "OPEN",
                "retail_portfolio_id": TEST_PORTFOLIO_ID,
                "filled_size": "0",
                "filled_value": "0",
                "total_fees": "0",
                "number_of_fills": 0,
            },
        },
    )
    runtime = MagicMock()
    runtime.read_controlled_first_child.return_value = {
        "stealth_order_id": CHILD_ID,
        "root_client_order_id": ROOT_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "retail_portfolio_id": TEST_PORTFOLIO_ID,
        "status": "REVEALED",
        "active_placement_client_order_id": CHILD_ID,
        "active_exchange_order_id": EXCHANGE_ID,
        "executed_size": "0",
        "controlled_plan_sha256": PLAN_SHA256,
    }
    rest_client = MagicMock()
    dependencies = _deps(
        runtime,
        rest_client,
        controlled_cancel_plan=_controlled_cancel_recovery_plan("24"),
    )

    class BrokenInflightController:
        @contextmanager
        def track_inflight(self, _operation):
            raise RuntimeError("inflight tracking unavailable")
            yield

    dependencies.runtime_controller_factory = BrokenInflightController
    service = AdminApiCommandService(dependencies)

    response = service.cancel_stealth_order_by_stealth_order_id(
        _cancel_command(
            operator_intent=CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT,
            controlled_plan_sha256=PLAN_SHA256,
        ),
        sealed_cancel_plan_sha256=SEALED_PLAN_SHA256,
        v15r6_verified_exchange_submission_required=True,
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "cancellation_unknown"
    assert response.live_exchange_submitted is False
    assert response.live_coinbase_orders_ran is False
    assert response.coinbase_order_id is None
    identity = response.data["cancellation_identity"]
    assert identity["canonical_cancel_attempted"] is False
    assert identity["verified_exchange_order_id_cancel_attempted"] is False
    assert identity["canonical_client_order_id_cancel_attempted"] is False
    assert "submitted_identity_key" not in identity
    rest_client.cancel_order.assert_not_called()
    rest_client.cancel_order_by_exchange_order_id.assert_not_called()


@pytest.mark.parametrize(
    ("exchange_status", "expected_status"),
    [
        ("OPEN", AdminApiCommandStatus.REJECTED),
        ("CANCELLED", AdminApiCommandStatus.ACCEPTED),
    ],
)
def test_v15_child_cancel_reconciliation_or_already_cancelled_never_resubmits(
    monkeypatch,
    exchange_status,
    expected_status,
):
    from application.admin_api import command_service as command_service_module

    monkeypatch.setattr(
        "application.admin_api.command_service.evaluate_spot_test_portfolio_binding",
        lambda **_kwargs: _portfolio_binding(),
    )
    monkeypatch.setattr(
        command_service_module,
        "validate_controlled_child_cancel_plan_scope",
        lambda _plan: None,
    )
    monkeypatch.setattr(
        command_service_module,
        "is_controlled_v15r6_recovery_plan",
        lambda plan: plan.get("schema_version") == "24",
        raising=False,
    )
    monkeypatch.setattr(
        "application.admin_api.command_service.exact_coinbase_order_readback",
        lambda *_args, **_kwargs: {
            "authoritative": True,
            "pagination_complete": True,
            "exact_identity_match": True,
            "authoritative_status": exchange_status,
            "exchange_order_id": EXCHANGE_ID,
            "matched_order": {
                "client_order_id": CHILD_ID,
                "order_id": EXCHANGE_ID,
                "product_id": "BTC-USDC",
                "product_type": "SPOT",
                "side": "SELL",
                "status": exchange_status,
                "retail_portfolio_id": TEST_PORTFOLIO_ID,
                "filled_size": "0",
                "filled_value": "0",
                "total_fees": "0",
                "number_of_fills": 0,
            },
        },
    )
    runtime = MagicMock()
    runtime.read_controlled_first_child.return_value = {
        "stealth_order_id": CHILD_ID,
        "root_client_order_id": ROOT_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "retail_portfolio_id": TEST_PORTFOLIO_ID,
        "status": "REVEALED",
        "active_placement_client_order_id": CHILD_ID,
        "active_exchange_order_id": EXCHANGE_ID,
        "executed_size": "0",
        "controlled_plan_sha256": PLAN_SHA256,
    }
    runtime.reconcile_controlled_first_child_terminal.return_value = {
        "local_status": "CANCELLED",
        "active_placement_cleared": True,
    }
    rest_client = MagicMock()
    service = AdminApiCommandService(
        _deps(
            runtime,
            rest_client,
            controlled_cancel_plan=_controlled_cancel_recovery_plan("24"),
        )
    )

    response = service.cancel_stealth_order_by_stealth_order_id(
        _cancel_command(
            operator_intent=CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT,
            controlled_plan_sha256=PLAN_SHA256,
        ),
        reconciliation_only=exchange_status == "OPEN",
        sealed_cancel_plan_sha256=SEALED_PLAN_SHA256,
        v15r6_verified_exchange_submission_required=True,
    )

    assert response.status == expected_status
    rest_client.cancel_order.assert_not_called()
    rest_client.cancel_order_by_exchange_order_id.assert_not_called()
    if exchange_status == "CANCELLED":
        assert response.data["terminal_zero_fill"]["proven"] is True
        identity = response.data["cancellation_identity"]
        assert identity["canonical_cancel_attempted"] is False
        assert identity["verified_exchange_order_id_cancel_attempted"] is False
        assert identity["canonical_client_order_id_cancel_attempted"] is False
        assert "submitted_identity_key" not in identity
        assert response.data["local_reconciliation"] == {
            "local_status": "CANCELLED",
            "active_placement_cleared": True,
            "executed_size": "0",
        }
    else:
        runtime.reconcile_controlled_first_child_terminal.assert_not_called()


def test_v15_controlled_child_cancel_rejects_runtime_plan_hash_mismatch(
    monkeypatch,
):
    monkeypatch.setattr(
        "application.admin_api.command_service.evaluate_spot_test_portfolio_binding",
        lambda **_kwargs: _portfolio_binding(),
    )
    rest_client = MagicMock()
    runtime = MagicMock()
    runtime.read_controlled_first_child.return_value = {
        "stealth_order_id": CHILD_ID,
        "root_client_order_id": ROOT_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "retail_portfolio_id": TEST_PORTFOLIO_ID,
        "status": "REVEALED",
        "active_placement_client_order_id": CHILD_ID,
        "active_exchange_order_id": EXCHANGE_ID,
        "executed_size": "0",
        "controlled_plan_sha256": "b" * 64,
    }
    service = AdminApiCommandService(_deps(runtime, rest_client))

    response = service.cancel_stealth_order_by_stealth_order_id(
        _cancel_command(
            operator_intent=CONTROLLED_V15_FIRST_CHILD_CANCEL_OPERATOR_INTENT,
            controlled_plan_sha256=PLAN_SHA256,
        )
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "controlled_child_state"
    rest_client.cancel_order.assert_not_called()
    rest_client.cancel_order_by_exchange_order_id.assert_not_called()


def test_controlled_child_cancel_does_not_cancel_when_child_already_filled(monkeypatch):
    monkeypatch.setattr(
        "application.admin_api.command_service.evaluate_spot_test_portfolio_binding",
        lambda **_kwargs: _portfolio_binding(),
    )
    monkeypatch.setattr(
        "application.admin_api.command_service.exact_coinbase_order_readback",
        lambda *_args, **_kwargs: {
            "authoritative": True,
            "exact_identity_match": True,
            "authoritative_status": "FILLED",
            "exchange_order_id": EXCHANGE_ID,
            "matched_order": {
                "client_order_id": CHILD_ID,
                "order_id": EXCHANGE_ID,
                "product_id": "BTC-USDC",
                "product_type": "SPOT",
                "side": "SELL",
                "status": "FILLED",
                "retail_portfolio_id": TEST_PORTFOLIO_ID,
                "filled_size": "0.00001718",
            },
        },
    )
    rest_client = MagicMock()
    runtime = MagicMock()
    runtime.read_controlled_first_child.return_value = {
        "stealth_order_id": CHILD_ID,
        "root_client_order_id": ROOT_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "retail_portfolio_id": TEST_PORTFOLIO_ID,
        "status": "REVEALED",
        "active_placement_client_order_id": CHILD_ID,
        "active_exchange_order_id": EXCHANGE_ID,
        "executed_size": "0",
    }
    service = AdminApiCommandService(_deps(runtime, rest_client))

    response = service.cancel_stealth_order_by_stealth_order_id(_cancel_command())

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "controlled_child_already_filled"
    rest_client.cancel_order.assert_not_called()
    rest_client.cancel_order_by_exchange_order_id.assert_not_called()


@pytest.mark.parametrize(
    ("canonical_evidence", "fallback_evidence", "fallback_call_count"),
    [
        (
            {"outcome": "unknown", "explicit_rejection": False},
            None,
            0,
        ),
        (
            {
                "outcome": "explicitly_rejected",
                "explicit_rejection": True,
                "identity_rejection": True,
                "identity_match": True,
            },
            {"outcome": "unknown", "explicit_rejection": False},
            1,
        ),
    ],
)
def test_controlled_child_cancel_unknown_outcome_stops_without_another_fallback(
    monkeypatch,
    canonical_evidence,
    fallback_evidence,
    fallback_call_count,
):
    monkeypatch.setattr(
        "application.admin_api.command_service.evaluate_spot_test_portfolio_binding",
        lambda **_kwargs: _portfolio_binding(),
    )
    monkeypatch.setattr(
        "application.admin_api.command_service.exact_coinbase_order_readback",
        lambda *_args, **_kwargs: {
            "authoritative": True,
            "exact_identity_match": True,
            "authoritative_status": "OPEN",
            "exchange_order_id": EXCHANGE_ID,
            "matched_order": {
                "client_order_id": CHILD_ID,
                "order_id": EXCHANGE_ID,
                "product_id": "BTC-USDC",
                "product_type": "SPOT",
                "side": "SELL",
                "status": "OPEN",
                "retail_portfolio_id": TEST_PORTFOLIO_ID,
                "filled_size": "0",
            },
        },
    )
    rest_client = MagicMock()
    rest_client.cancel_order.return_value = canonical_evidence
    rest_client.cancel_order_by_exchange_order_id.return_value = fallback_evidence
    runtime = MagicMock()
    runtime.read_controlled_first_child.return_value = {
        "stealth_order_id": CHILD_ID,
        "root_client_order_id": ROOT_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "retail_portfolio_id": TEST_PORTFOLIO_ID,
        "status": "REVEALED",
        "active_placement_client_order_id": CHILD_ID,
        "active_exchange_order_id": EXCHANGE_ID,
        "executed_size": "0",
    }
    service = AdminApiCommandService(_deps(runtime, rest_client))

    response = service.cancel_stealth_order_by_stealth_order_id(_cancel_command())

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "cancellation_unknown"
    identity = response.data["cancellation_identity"]
    assert identity["operator_identity_key"] == "client_order_id"
    assert identity["operator_identity_value"] == CHILD_ID
    assert identity["exchange_order_id_evidence_only"] is True
    assert identity["exchange_order_id"] == EXCHANGE_ID
    assert identity["canonical_cancel_evidence"] == canonical_evidence
    assert identity["unknown_boundary"] == (
        "exchange_id_fallback"
        if fallback_call_count
        else "canonical_client_order_id"
    )
    rest_client.cancel_order.assert_called_once_with(
        CHILD_ID,
        return_evidence=True,
    )
    assert (
        rest_client.cancel_order_by_exchange_order_id.call_count
        == fallback_call_count
    )
    if fallback_call_count:
        rest_client.cancel_order_by_exchange_order_id.assert_called_once_with(
            EXCHANGE_ID,
            return_evidence=True,
        )


def test_controlled_child_partial_fill_cancelled_reconciles_then_stops(monkeypatch):
    monkeypatch.setattr(
        "application.admin_api.command_service.evaluate_spot_test_portfolio_binding",
        lambda **_kwargs: _portfolio_binding(),
    )
    rows = [
        ("OPEN", "0"),
        ("CANCELLED", "0.00000100"),
    ]

    def readback(*_args, **_kwargs):
        status, filled_size = rows.pop(0)
        return {
            "authoritative": True,
            "exact_identity_match": True,
            "authoritative_status": status,
            "exchange_order_id": EXCHANGE_ID,
            "matched_order": {
                "client_order_id": CHILD_ID,
                "order_id": EXCHANGE_ID,
                "product_id": "BTC-USDC",
                "product_type": "SPOT",
                "side": "SELL",
                "status": status,
                "retail_portfolio_id": TEST_PORTFOLIO_ID,
                "filled_size": filled_size,
            },
        }

    monkeypatch.setattr(
        "application.admin_api.command_service.exact_coinbase_order_readback",
        readback,
    )
    rest_client = MagicMock()
    rest_client.cancel_order.return_value = {
        "outcome": "explicitly_rejected",
        "explicit_rejection": True,
        "identity_rejection": True,
        "identity_match": True,
    }
    rest_client.cancel_order_by_exchange_order_id.return_value = {
        "outcome": "succeeded",
        "explicit_rejection": False,
        "identity_rejection": False,
        "identity_match": True,
    }
    runtime = MagicMock()
    runtime.read_controlled_first_child.return_value = {
        "stealth_order_id": CHILD_ID,
        "root_client_order_id": ROOT_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "retail_portfolio_id": TEST_PORTFOLIO_ID,
        "status": "REVEALED",
        "active_placement_client_order_id": CHILD_ID,
        "active_exchange_order_id": EXCHANGE_ID,
        "executed_size": "0",
    }
    runtime.reconcile_controlled_first_child_terminal.return_value = {
        "local_status": "CANCELLED",
        "active_placement_cleared": True,
    }
    service = AdminApiCommandService(_deps(runtime, rest_client))

    response = service.cancel_stealth_order_by_stealth_order_id(_cancel_command())

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "controlled_child_partial_fill_cancelled"
    rest_client.cancel_order.assert_called_once_with(
        CHILD_ID,
        return_evidence=True,
    )
    rest_client.cancel_order_by_exchange_order_id.assert_called_once_with(
        EXCHANGE_ID,
        return_evidence=True,
    )
    runtime.reconcile_controlled_first_child_terminal.assert_called_once()


def test_runtime_adapter_uses_canonical_rest_reference_when_cache_is_placeholder(
    monkeypatch,
):
    from application.admin_api import command_runtime

    now = datetime.now(timezone.utc)
    authority, order = _runtime_adapter_success_evidence()
    canonical_reference = MagicMock(
        return_value={
            "product_id": "BTC-USDC",
            "best_bid": "64000.00",
            "best_ask": "64000.01",
            "source": "coinbase_rest_best_bid",
            "observed_at": now,
        }
    )
    monkeypatch.setattr(
        command_runtime,
        "get_admin_api_spot_market_reference",
        canonical_reference,
    )
    manager = MagicMock()
    manager._get_current_market_data.return_value = {"source": "placeholder"}
    manager.prepare_controlled_admin_first_child_reveal.return_value = authority
    manager.reveal_order_slice.return_value = CHILD_ID
    manager._get_stealth_order.return_value = order
    adapter = AdminApiControlledFirstChildRuntimeAdapter(manager)

    result = _submit_runtime_adapter(adapter)

    canonical_reference.assert_called_once_with("BTC-USDC")
    manager.prepare_controlled_admin_first_child_reveal.assert_called_once()
    preparation = manager.prepare_controlled_admin_first_child_reveal.call_args.kwargs
    assert preparation["market_bid"] == "64000.00"
    assert preparation["market_source"] == "coinbase_rest_best_bid"
    assert preparation["market_observed_at"] == now
    assert preparation["expected_prior_preparation_sha256"] is None
    manager.reveal_order_slice.assert_called_once_with(
        CHILD_ID,
        controlled_admin_authority=authority,
    )
    assert result["placement_succeeded"] is True


@pytest.mark.parametrize(
    ("reference", "expected_error"),
    [
        (None, "controlled_child_fresh_bid_missing"),
        (
            {
                "best_bid": "NaN",
                "source": "coinbase_rest_best_bid",
                "observed_at": datetime.now(timezone.utc),
            },
            "controlled_child_fresh_bid_missing",
        ),
        (
            {
                "best_bid": "64000.00",
                "source": "coinbase_rest_best_bid",
                "observed_at": None,
            },
            "controlled_child_market_timestamp_missing",
        ),
        (
            {
                "best_bid": "64000.00",
                "source": "coinbase_rest_best_bid",
                "observed_at": datetime.now().replace(tzinfo=None),
            },
            "controlled_child_market_timestamp_not_aware",
        ),
        (
            {
                "best_bid": "64000.00",
                "source": "placeholder",
                "observed_at": datetime.now(timezone.utc),
            },
            "controlled_child_market_source_invalid",
        ),
    ],
)
def test_runtime_adapter_rejects_invalid_canonical_reference_before_preparation(
    monkeypatch,
    reference,
    expected_error,
):
    from application.admin_api import command_runtime

    canonical_reference = MagicMock(return_value=reference)
    monkeypatch.setattr(
        command_runtime,
        "get_admin_api_spot_market_reference",
        canonical_reference,
    )
    manager = MagicMock()
    manager._get_current_market_data.return_value = {"source": "placeholder"}
    adapter = AdminApiControlledFirstChildRuntimeAdapter(manager)

    with pytest.raises(
        ControlledChildPrePlacementError,
        match="controlled_child_market_reference_unavailable",
    ) as raised:
        _submit_runtime_adapter(adapter)

    assert raised.value.stage == "market_reference"
    assert raised.value.detail == "controlled_child_market_reference_unavailable"
    assert expected_error not in raised.value.detail
    canonical_reference.assert_called_once_with("BTC-USDC")
    manager.prepare_controlled_admin_first_child_reveal.assert_not_called()
    manager.reveal_order_slice.assert_not_called()


def test_runtime_adapter_wraps_preparation_rejection_before_reveal():
    manager = MagicMock()
    manager.prepare_controlled_admin_first_child_reveal.side_effect = (
        OrderPersistenceError("controlled reveal prior preparation hash mismatch")
    )
    adapter = AdminApiControlledFirstChildRuntimeAdapter(
        manager,
        market_reference_getter=lambda _product_id: {
            "best_bid": "64000.00",
            "source": "coinbase_rest_best_bid",
            "observed_at": datetime.now(timezone.utc),
        },
    )

    with pytest.raises(
        ControlledChildPrePlacementError,
        match="controlled_child_preparation_unavailable",
    ) as raised:
        _submit_runtime_adapter(
            adapter,
            prior_preparation_sha256="a" * 64,
        )

    assert raised.value.stage == "preparation"
    assert raised.value.cause_type == "OrderPersistenceError"
    assert "prior preparation hash mismatch" not in raised.value.detail
    manager.reveal_order_slice.assert_not_called()


def test_runtime_adapter_wraps_price_alignment_failure_before_reveal():
    manager = MagicMock()
    authority, _order = _runtime_adapter_success_evidence()
    authority.prepared_limit_price = 102400.01
    manager.prepare_controlled_admin_first_child_reveal.return_value = authority
    adapter = AdminApiControlledFirstChildRuntimeAdapter(
        manager,
        market_reference_getter=lambda _product_id: {
            "best_bid": "64000.00",
            "source": "coinbase_rest_best_bid",
            "observed_at": datetime.now(timezone.utc),
        },
    )

    with pytest.raises(
        ControlledChildPrePlacementError,
        match="controlled_child_price_alignment_unavailable",
    ) as raised:
        _submit_runtime_adapter(adapter)

    assert raised.value.stage == "price_alignment"
    assert "limit_price_not_increment_aligned" not in raised.value.detail
    manager.reveal_order_slice.assert_not_called()


def test_runtime_adapter_does_not_wrap_reveal_boundary_exception():
    manager = MagicMock()
    authority, _order = _runtime_adapter_success_evidence()
    manager.prepare_controlled_admin_first_child_reveal.return_value = authority
    manager.reveal_order_slice.side_effect = TimeoutError("SDK response lost")
    adapter = AdminApiControlledFirstChildRuntimeAdapter(
        manager,
        market_reference_getter=lambda _product_id: {
            "best_bid": "64000.00",
            "source": "coinbase_rest_best_bid",
            "observed_at": datetime.now(timezone.utc),
        },
    )

    with pytest.raises(TimeoutError, match="SDK response lost"):
        _submit_runtime_adapter(adapter)

    manager.reveal_order_slice.assert_called_once()


def test_runtime_adapter_prepares_then_submits_exact_child_from_cached_ticker(
    monkeypatch,
):
    now = datetime.now(timezone.utc)
    authority, order = _runtime_adapter_success_evidence()
    manager = MagicMock()
    manager._market_cache = {
        "BTC-USDC": {
            "bid": 64000.0,
            "ask": 64001.0,
            "time": now,
            "source": "ticker",
        }
    }
    manager.prepare_controlled_admin_first_child_reveal.return_value = authority
    manager.reveal_order_slice.return_value = CHILD_ID
    manager._get_stealth_order.return_value = order
    monkeypatch.setitem(
        sys.modules,
        "dashboard_server",
        SimpleNamespace(
            stealth_order_bridge=SimpleNamespace(stealth_manager=manager),
        ),
    )
    adapter = AdminApiControlledFirstChildRuntimeAdapter(manager)

    result = _submit_runtime_adapter(adapter)

    manager._get_current_market_data.assert_not_called()
    manager.prepare_controlled_admin_first_child_reveal.assert_called_once()
    manager.reveal_order_slice.assert_called_once_with(
        CHILD_ID,
        controlled_admin_authority=authority,
    )
    assert result == {
        "placed_client_order_id": CHILD_ID,
        "exchange_order_id": EXCHANGE_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "base_size": "0.00001718",
        "submitted_limit_price": "102400.00",
        "post_only": False,
        "placement_attempted": True,
        "placement_succeeded": True,
        "reference_notional_usdc": "1.759232",
    }


def test_runtime_adapter_forwards_v15_plan_hash_into_preparation(monkeypatch):
    now = datetime.now(timezone.utc)
    authority, order = _runtime_adapter_success_evidence()
    manager = MagicMock()
    manager._market_cache = {
        "BTC-USDC": {
            "bid": 64000.0,
            "ask": 64001.0,
            "time": now,
            "source": "ticker",
        }
    }
    manager.prepare_controlled_admin_first_child_reveal.return_value = authority
    manager.reveal_order_slice.return_value = CHILD_ID
    manager._get_stealth_order.return_value = order
    monkeypatch.setitem(
        sys.modules,
        "dashboard_server",
        SimpleNamespace(
            stealth_order_bridge=SimpleNamespace(stealth_manager=manager),
        ),
    )
    adapter = AdminApiControlledFirstChildRuntimeAdapter(manager)

    result = _submit_runtime_adapter(
        adapter,
        controlled_plan_sha256=PLAN_SHA256,
    )

    assert manager.prepare_controlled_admin_first_child_reveal.call_args.kwargs[
        "controlled_plan_sha256"
    ] == PLAN_SHA256
    assert result["controlled_plan_sha256"] == PLAN_SHA256


def test_runtime_adapter_reads_and_reconciles_exact_first_child(monkeypatch):
    child_row = {
        "client_order_id": CHILD_ID,
        "parent_order_id": ROOT_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "status": "OPEN",
        "ownership_provenance": "ADMIN_FILL_FOLLOW_UP",
        "retail_portfolio_id": TEST_PORTFOLIO_ID,
        "correlation_id": "corr-root",
        "audit_id": "audit-root",
        "exchange_order_id": EXCHANGE_ID,
    }
    root_row = {
        "client_order_id": ROOT_ID,
        "parent_order_id": None,
        "product_id": "BTC-USDC",
        "side": "BUY",
        "status": "FILLED",
        "ownership_provenance": "ADMIN_MANUAL_ROOT",
        "retail_portfolio_id": TEST_PORTFOLIO_ID,
        "correlation_id": "corr-root",
        "audit_id": "audit-root",
    }
    state = {
        "stealth_order_id": CHILD_ID,
        "parent_order_id": ROOT_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "status": "REVEALED",
        "total_size": 0.00001718,
        "executed_size": 0.0,
        "anchor_repricing_state_json": {
            "active_placement_client_order_id": CHILD_ID,
            "active_exchange_order_id": EXCHANGE_ID,
            "active_exchange_price": 102400.0,
            "controlled_admin_first_child_reveal_preparation": {
                "batch_id": BATCH_ID,
                "batch_slot": 1,
                "controlled_plan_sha256": PLAN_SHA256,
            },
        },
        "revealed_orders": [
            {
                "placed_order_id": CHILD_ID,
                "exchange_order_id": EXCHANGE_ID,
                "placement_success": True,
            }
        ],
    }
    manager = MagicMock()
    manager._get_stealth_order.return_value = state

    def update_execution(_child_id, _executed_size, order_status):
        state["status"] = order_status
        state["anchor_repricing_state_json"].update(
            {
                "active_placement_client_order_id": None,
                "active_exchange_order_id": None,
                "active_exchange_price": None,
            }
        )

    manager.update_execution.side_effect = update_execution
    monkeypatch.setattr(
        "database.order.get_parent_order",
        lambda coid: child_row if coid == CHILD_ID else root_row,
    )
    adapter = AdminApiControlledFirstChildRuntimeAdapter(manager)

    readback = adapter.read_controlled_first_child(
        stealth_order_id=CHILD_ID,
        expected_root_client_order_id=ROOT_ID,
        expected_portfolio_id=TEST_PORTFOLIO_ID,
        controlled_batch_id=BATCH_ID,
        controlled_batch_slot=1,
    )
    v15_readback = adapter.read_controlled_first_child(
        stealth_order_id=CHILD_ID,
        expected_root_client_order_id=ROOT_ID,
        expected_portfolio_id=TEST_PORTFOLIO_ID,
        controlled_batch_id=BATCH_ID,
        controlled_batch_slot=1,
        controlled_plan_sha256=PLAN_SHA256,
    )
    with pytest.raises(RuntimeError, match="controlled_child_state_mismatch"):
        adapter.read_controlled_first_child(
            stealth_order_id=CHILD_ID,
            expected_root_client_order_id=ROOT_ID,
            expected_portfolio_id=TEST_PORTFOLIO_ID,
            controlled_batch_id=BATCH_ID,
            controlled_batch_slot=1,
            controlled_plan_sha256="b" * 64,
        )
    reconciled = adapter.reconcile_controlled_first_child_terminal(
        stealth_order_id=CHILD_ID,
        authoritative_status="CANCELLED",
        executed_size="0",
        exchange_order_id=EXCHANGE_ID,
    )

    assert readback["active_exchange_order_id"] == EXCHANGE_ID
    assert readback["root_client_order_id"] == ROOT_ID
    assert readback["base_size"] == "0.00001718"
    assert readback["limit_price"] == "102400.0"
    assert "controlled_plan_sha256" not in readback
    assert v15_readback["controlled_plan_sha256"] == PLAN_SHA256
    assert reconciled == {
        "local_status": "CANCELLED",
        "active_placement_cleared": True,
        "exchange_order_id": EXCHANGE_ID,
    }


def test_runtime_adapter_accepts_exact_already_reconciled_cancelled_first_child():
    state = {
        "stealth_order_id": CHILD_ID,
        "status": "CANCELLED",
        "executed_size": 0.0,
        "anchor_repricing_state_json": {
            "active_placement_client_order_id": None,
            "active_exchange_order_id": None,
            "active_exchange_price": None,
        },
        "revealed_orders": [
            {
                "placed_order_id": CHILD_ID,
                "exchange_order_id": EXCHANGE_ID,
                "placement_success": True,
            }
        ],
    }
    manager = MagicMock()
    manager._get_stealth_order.return_value = state
    adapter = AdminApiControlledFirstChildRuntimeAdapter(manager)

    reconciled = adapter.reconcile_controlled_first_child_terminal(
        stealth_order_id=CHILD_ID,
        authoritative_status="CANCELLED",
        executed_size="0",
        exchange_order_id=EXCHANGE_ID,
    )

    manager.update_execution.assert_not_called()
    assert reconciled == {
        "local_status": "CANCELLED",
        "active_placement_cleared": True,
        "exchange_order_id": EXCHANGE_ID,
        "already_reconciled": True,
    }


def test_runtime_adapter_rejects_already_cancelled_child_with_exchange_identity_drift():
    state = {
        "stealth_order_id": CHILD_ID,
        "status": "CANCELLED",
        "executed_size": 0.0,
        "anchor_repricing_state_json": {
            "active_placement_client_order_id": None,
            "active_exchange_order_id": None,
            "active_exchange_price": None,
        },
        "revealed_orders": [
            {
                "placed_order_id": CHILD_ID,
                "exchange_order_id": "different-exchange-order-id",
                "placement_success": True,
            }
        ],
    }
    manager = MagicMock()
    manager._get_stealth_order.return_value = state
    adapter = AdminApiControlledFirstChildRuntimeAdapter(manager)

    with pytest.raises(
        RuntimeError,
        match="controlled_child_active_placement_mismatch",
    ):
        adapter.reconcile_controlled_first_child_terminal(
            stealth_order_id=CHILD_ID,
            authoritative_status="CANCELLED",
            executed_size="0",
            exchange_order_id=EXCHANGE_ID,
        )

    manager.update_execution.assert_not_called()


def test_runtime_adapter_rejects_already_cancelled_child_without_clear_state_evidence():
    state = {
        "stealth_order_id": CHILD_ID,
        "status": "CANCELLED",
        "executed_size": 0.0,
        "anchor_repricing_state_json": {},
        "revealed_orders": [
            {
                "placed_order_id": CHILD_ID,
                "exchange_order_id": EXCHANGE_ID,
                "placement_success": True,
            }
        ],
    }
    manager = MagicMock()
    manager._get_stealth_order.return_value = state
    adapter = AdminApiControlledFirstChildRuntimeAdapter(manager)

    with pytest.raises(
        RuntimeError,
        match="controlled_child_active_placement_mismatch",
    ):
        adapter.reconcile_controlled_first_child_terminal(
            stealth_order_id=CHILD_ID,
            authoritative_status="CANCELLED",
            executed_size="0",
            exchange_order_id=EXCHANGE_ID,
        )

    manager.update_execution.assert_not_called()


@pytest.mark.parametrize("local_executed_size", [None, 0.00000001])
def test_runtime_adapter_rejects_already_cancelled_child_with_executed_size_drift(
    local_executed_size,
):
    state = {
        "stealth_order_id": CHILD_ID,
        "status": "CANCELLED",
        "executed_size": local_executed_size,
        "anchor_repricing_state_json": {
            "active_placement_client_order_id": None,
            "active_exchange_order_id": None,
            "active_exchange_price": None,
        },
        "revealed_orders": [
            {
                "placed_order_id": CHILD_ID,
                "exchange_order_id": EXCHANGE_ID,
                "placement_success": True,
            }
        ],
    }
    if local_executed_size is None:
        state.pop("executed_size")
    manager = MagicMock()
    manager._get_stealth_order.return_value = state
    adapter = AdminApiControlledFirstChildRuntimeAdapter(manager)

    with pytest.raises(
        RuntimeError,
        match="controlled_child_active_placement_mismatch",
    ):
        adapter.reconcile_controlled_first_child_terminal(
            stealth_order_id=CHILD_ID,
            authoritative_status="CANCELLED",
            executed_size="0",
            exchange_order_id=EXCHANGE_ID,
        )

    manager.update_execution.assert_not_called()
