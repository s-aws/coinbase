from __future__ import annotations

from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
from threading import Event, Lock, Thread
from types import SimpleNamespace
from typing import Any, Callable, Mapping

import pytest

from core.enums import OrderStatus
from application.admin_api.command_service import (
    AdminApiCommandDependencies,
    AdminApiCommandService,
    SpotAutomationMarketEvidence,
    SpotAutomationWalletEvidence,
    SpotAutomationZeroActiveOrderEvidence,
    SpotProfileAdmissionLeaseError,
    SpotProfileOrderAdmissionCoordinator,
    ValidatedSpotAutomationAdmissionEvidence,
    ValidatedSpotAutomationOwnershipEvidence,
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
    ReconcileOrderCommand,
    ReconcileOrderRequest,
)
from application.admin_api.spot_portfolio_binding import (
    SpotPortfolioBindingEvidence,
)


TEST_PORTFOLIO_ID = "11111111-2222-4333-8444-555555555555"


@pytest.fixture(autouse=True)
def _disable_unrelated_action_guards(
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


class _RuntimeController:
    def track_inflight(self, _name: str):
        return nullcontext()


class _Publisher:
    enabled = True

    def __init__(self, *, persisted: bool = True) -> None:
        self.persisted = persisted
        self.calls: list[dict[str, Any]] = []

    def publish_event(self, **kwargs: Any) -> bool:
        self.calls.append(dict(kwargs))
        return self.persisted


class _RootRegistrar:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.status_calls: list[tuple[str, str]] = []
        self.exchange_status_calls: list[dict[str, Any]] = []

    def register_manual_spot_root(self, **kwargs: Any) -> dict[str, Any]:
        return self._register_spot_root(
            ownership_provenance="ADMIN_MANUAL_ROOT",
            **kwargs,
        )

    def register_automation_spot_root(self, **kwargs: Any) -> dict[str, Any]:
        return self._register_spot_root(
            ownership_provenance="ADMIN_AUTOMATION_ROOT",
            **kwargs,
        )

    def _register_spot_root(
        self,
        *,
        ownership_provenance: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        row = {
            **kwargs,
            "parent_order_id": None,
            "ownership_provenance": ownership_provenance,
            "status": "PENDING",
        }
        self.rows[str(kwargs["client_order_id"])] = row
        return {
            "registered": True,
            "client_order_id": kwargs["client_order_id"],
            "retail_portfolio_id": kwargs["retail_portfolio_id"],
            "ownership_provenance": ownership_provenance,
            "target_movement": kwargs.get("target_movement_override"),
            "target_movement_source": (
                "fee_aware_intentional_fill_target"
                if kwargs.get("target_movement_override") is not None
                else "canonical_orderbook_profit_target"
            ),
        }

    def build_intentional_fill_target_movement(
        self,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        return {
            "ready": True,
            "blocker": None,
            "target_movement": "0.03",
            "target_movement_type": "P",
            "profitability_preflight_passed": True,
            "source": "test_fee_aware_intentional_fill_target",
        }

    def mark_submission_status(
        self,
        *,
        client_order_id: str,
        status: str,
        exchange_order_id: str | None = None,
    ) -> None:
        self.status_calls.append((client_order_id, status))
        self.exchange_status_calls.append(
            {
                "client_order_id": client_order_id,
                "status": status,
                "exchange_order_id": exchange_order_id,
            }
        )
        self.rows[client_order_id]["status"] = status
        if exchange_order_id is not None:
            self.rows[client_order_id]["exchange_order_id"] = exchange_order_id

    def read_registered_order(self, client_order_id: str) -> dict[str, Any] | None:
        row = self.rows.get(client_order_id)
        return dict(row) if row is not None else None

    def get_unresolved_admin_manual_root_submissions(
        self,
        retail_portfolio_id: str,
    ) -> list[dict[str, Any]]:
        terminal = {"FILLED", "CANCELLED", "EXPIRED", "FAILED"}
        return [
            dict(row)
            for row in self.rows.values()
            if row.get("retail_portfolio_id") == retail_portfolio_id
            and row.get("ownership_provenance") == "ADMIN_MANUAL_ROOT"
            and row.get("parent_order_id") is None
            and row.get("status") not in terminal
        ]

    def get_unresolved_admin_spot_root_submissions(
        self,
        retail_portfolio_id: str,
    ) -> list[dict[str, Any]]:
        terminal = {"FILLED", "CANCELLED", "EXPIRED", "FAILED"}
        return [
            dict(row)
            for row in self.rows.values()
            if row.get("retail_portfolio_id") == retail_portfolio_id
            and row.get("ownership_provenance")
            in {"ADMIN_MANUAL_ROOT", "ADMIN_AUTOMATION_ROOT"}
            and row.get("parent_order_id") is None
            and row.get("status") not in terminal
        ]


class _SpotRestClient:
    def __init__(self) -> None:
        self.open_orders: list[dict[str, Any]] = []
        self.history: list[dict[str, Any]] = []
        self.api_key_permission_calls = 0
        self.portfolio_calls = 0
        self.create_calls: list[dict[str, Any]] = []
        self.get_calls: list[str] = []
        self.list_calls: list[dict[str, Any]] = []
        self.list_fills_calls: list[dict[str, Any]] = []
        self.cancel_client_calls: list[str] = []
        self.cancel_exchange_calls: list[str] = []
        self.create_result: Any = {
            "success": True,
            "success_response": {"order_id": "exchange-order-1"},
        }
        self.cancel_client_result: Any = True
        self.cancel_exchange_result: Any = True
        self.fills: list[dict[str, Any]] = []
        self.fills_have_more_pages = False

    def get_api_key_permissions(self) -> dict[str, Any]:
        self.api_key_permission_calls += 1
        return {
            "portfolio_uuid": TEST_PORTFOLIO_ID,
            "portfolio_type": "CONSUMER",
            "can_view": True,
            "can_trade": True,
        }

    def list_portfolios(self) -> list[dict[str, Any]]:
        self.portfolio_calls += 1
        return [
            {
                "uuid": TEST_PORTFOLIO_ID,
                "name": "Test",
                "type": "CONSUMER",
            }
        ]

    def list_orders(self, **kwargs: Any) -> dict[str, Any]:
        self.list_calls.append(dict(kwargs))
        order_ids = {str(value) for value in kwargs.get("order_ids") or []}
        rows = (
            self.open_orders
            if kwargs.get("order_status") is not None
            else self.history
        )
        if order_ids:
            rows = [row for row in rows if str(row.get("order_id")) in order_ids]
        return {"orders": [dict(row) for row in rows], "has_next": False}

    def get_order(self, order_id: str) -> dict[str, Any]:
        self.get_calls.append(order_id)
        rows = [
            dict(row)
            for row in self.history
            if str(row.get("order_id")) == str(order_id)
        ]
        return {"order": rows[0] if len(rows) == 1 else {}}

    def list_fills(self, **kwargs: Any) -> dict[str, Any]:
        self.list_fills_calls.append(dict(kwargs))
        return {
            "fills": [dict(row) for row in self.fills],
            "has_next": self.fills_have_more_pages,
        }

    def create_order(self, **kwargs: Any) -> Any:
        self.create_calls.append(dict(kwargs))
        if isinstance(self.create_result, BaseException):
            raise self.create_result
        return self.create_result

    def cancel_order(
        self,
        client_order_id: str,
        *,
        verified_exchange_order_id: str | None = None,
        return_evidence: bool = False,
    ) -> Any:
        if verified_exchange_order_id is not None:
            self.cancel_exchange_calls.append(verified_exchange_order_id)
            result = self.cancel_exchange_result
        else:
            self.cancel_client_calls.append(client_order_id)
            result = self.cancel_client_result
        if isinstance(result, BaseException):
            raise result
        if not return_evidence:
            return result
        if result is True:
            return {
                "outcome": "succeeded",
                "explicit_rejection": False,
                "identity_rejection": False,
                "identity_match": True,
            }
        if result is False:
            return {
                "outcome": "explicitly_rejected",
                "explicit_rejection": True,
                "identity_rejection": True,
                "identity_match": True,
            }
        return {
            "outcome": "unknown",
            "explicit_rejection": False,
            "identity_rejection": False,
            "identity_match": False,
        }

    def cancel_order_by_exchange_order_id(
        self,
        order_id: str,
        *,
        return_evidence: bool = False,
    ) -> Any:
        self.cancel_exchange_calls.append(order_id)
        if isinstance(self.cancel_exchange_result, BaseException):
            raise self.cancel_exchange_result
        if not return_evidence:
            return self.cancel_exchange_result
        if self.cancel_exchange_result is True:
            return {
                "outcome": "succeeded",
                "explicit_rejection": False,
                "identity_rejection": False,
                "identity_match": True,
            }
        if self.cancel_exchange_result is False:
            return {
                "outcome": "explicitly_rejected",
                "explicit_rejection": True,
                "identity_rejection": True,
                "identity_match": True,
            }
        return {
            "outcome": "unknown",
            "explicit_rejection": False,
            "identity_rejection": False,
            "identity_match": False,
        }


def _manual_command(
    client_order_id: str = "22daf1ea-4c57-4c03-98c5-e74459576228",
    *,
    limit_price: str = "50.00",
    operator_intent: str = "bounded_spot_test_order",
    post_only: bool = True,
    time_in_force: str = "GOOD_UNTIL_CANCELLED",
    approval_snapshot_id: str | None = None,
    max_submitted_notional_usdc: str = "9.99",
    max_executed_notional_usdc: str | None = None,
    base_size: str = "0.02",
    order_configuration_override: dict[str, Any] | None = None,
) -> ManualOrderCommand:
    return ManualOrderCommand(
        envelope=AdminApiCommandEnvelope(
            idempotency_key=f"idem-{client_order_id}",
            correlation_id=f"corr-{client_order_id}",
            operator_intent=operator_intent,
            actor=AdminApiActor(
                actor_id="operator-001",
                roles=[AdminApiRole.ADMIN],
            ),
        ),
        request=ManualOrderRequest.model_validate(
            {
                "client_order_id": client_order_id,
                "product_id": "BTC-USDC",
                "side": "BUY",
                "order_type": "LIMIT",
                "base_size": base_size,
                "limit_price": limit_price,
                "post_only": post_only,
                "time_in_force": time_in_force,
                "manual_live_acknowledgement": True,
            }
        ),
        order_configuration_override=order_configuration_override,
        admin_approval_snapshot_id=approval_snapshot_id,
        admin_cap_guard_decision_id="cap-spot-test-profile",
        admin_max_submitted_notional_usdc=max_submitted_notional_usdc,
        admin_max_executed_notional_usdc=max_executed_notional_usdc,
        admission_audit_id="audit-spot-test-profile",
        allow_live_execution=True,
    )


def _cancel_command(
    client_order_id: str,
    *,
    idempotency_key: str | None = None,
    manual_live_acknowledgement: bool = True,
) -> CancelOrderCommand:
    return CancelOrderCommand(
        envelope=AdminApiCommandEnvelope(
            idempotency_key=(
                idempotency_key or f"idem-cancel-{client_order_id}"
            ),
            correlation_id=f"corr-cancel-{client_order_id}",
            operator_intent="cancel_bounded_test_order",
            actor=AdminApiActor(
                actor_id="operator-001",
                roles=[AdminApiRole.ADMIN],
            ),
        ),
        client_order_id=client_order_id,
        request=CancelOrderRequest(
            reason="cancel before another order",
            manual_live_acknowledgement=manual_live_acknowledgement,
        ),
        allow_live_execution=True,
    )


def _reconcile_command(client_order_id: str) -> ReconcileOrderCommand:
    return ReconcileOrderCommand(
        envelope=AdminApiCommandEnvelope(
            idempotency_key=f"idem-reconcile-{client_order_id}",
            correlation_id=f"corr-reconcile-{client_order_id}",
            operator_intent="reconcile_selected_spot_root",
            actor=AdminApiActor(
                actor_id="operator-001",
                roles=[AdminApiRole.ADMIN],
            ),
        ),
        client_order_id=client_order_id,
        request=ReconcileOrderRequest(
            reason="refresh authoritative selected-root status",
            manual_live_acknowledgement=True,
        ),
        allow_live_read=True,
        audit_id=f"audit-reconcile-{client_order_id}",
    )


@pytest.mark.parametrize(
    ("request_patch", "expected_blocker"),
    [
        (
            {
                "order_type": "MARKET",
                "base_size": None,
                "quote_size": "1.00",
                "limit_price": None,
                "time_in_force": "IMMEDIATE_OR_CANCEL",
            },
            "manual_spot_order_type_not_supported",
        ),
        (
            {"order_type": "STOP_LIMIT"},
            "manual_spot_order_type_not_supported",
        ),
        (
            {"time_in_force": "IMMEDIATE_OR_CANCEL"},
            "manual_spot_time_in_force_not_supported",
        ),
        (
            {"time_in_force": "FILL_OR_KILL"},
            "manual_spot_time_in_force_not_supported",
        ),
        (
            {"quote_size": "1.00"},
            "manual_spot_quote_size_not_supported",
        ),
    ],
)
def test_manual_order_rejects_semantics_instead_of_silently_rewriting_them(
    request_patch: dict[str, Any],
    expected_blocker: str,
) -> None:
    rest_client = _SpotRestClient()
    registrar = _RootRegistrar()
    command = _manual_command()
    request = ManualOrderRequest.model_validate(
        {**command.request.model_dump(mode="json"), **request_patch}
    )

    response = _service(rest_client, registrar).place_manual_order(
        command.model_copy(update={"request": request})
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "manual_order_semantics"
    assert response.data == {
        "semantic_contract": "durable_spot_limit_gtc_root",
        "blocker": expected_blocker,
    }
    assert rest_client.api_key_permission_calls == 0
    assert rest_client.portfolio_calls == 0
    assert rest_client.create_calls == []
    assert registrar.rows == {}


def test_manual_order_rejects_off_increment_base_size_without_rewriting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import configuration

    metadata = dict(configuration.PRODUCT_METADATA["BTC-USDC"])
    monkeypatch.setitem(
        configuration.PRODUCT_METADATA,
        "BTC-USDC",
        {
            **metadata,
            "base_increment": "0.01",
            "base_min_size": "0.01",
            "quote_min_size": "0.01",
            "price_increment": "0.01",
        },
    )
    rest_client = _SpotRestClient()
    registrar = _RootRegistrar()

    response = _service(rest_client, registrar).place_manual_order(
        _manual_command(base_size="0.025")
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "base_size_increment"
    assert response.data == {
        "blocker": "manual_spot_base_size_increment_misaligned"
    }
    assert rest_client.create_calls == []
    assert registrar.rows == {}


def test_manual_order_rejects_below_minimum_base_size_without_internal_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import configuration

    metadata = dict(configuration.PRODUCT_METADATA["BTC-USDC"])
    monkeypatch.setitem(
        configuration.PRODUCT_METADATA,
        "BTC-USDC",
        {
            **metadata,
            "base_increment": "0.00001",
            "base_min_size": "0.00002",
            "quote_min_size": "1.00",
            "price_increment": "0.01",
        },
    )
    rest_client = _SpotRestClient()
    registrar = _RootRegistrar()

    response = _service(rest_client, registrar).place_manual_order(
        _manual_command(base_size="0.00001", limit_price="50000.00")
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "size_validation"
    assert response.data == {
        "blocker": "manual_spot_base_size_validation_failed"
    }
    assert rest_client.create_calls == []
    assert registrar.rows == {}


def test_legacy_explicit_quote_size_is_rejected_instead_of_rewritten(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import configuration

    metadata = dict(configuration.PRODUCT_METADATA["BTC-USDC"])
    monkeypatch.setitem(
        configuration.PRODUCT_METADATA,
        "BTC-USDC",
        {
            **metadata,
            "quote_increment": "0.01",
            "quote_min_size": "0.01",
        },
    )
    rest_client = _SpotRestClient()
    registrar = _RootRegistrar()
    command = _manual_command(
        order_configuration_override={
            "market_market_ioc": {"quote_size": "1.005"}
        }
    )
    request = ManualOrderRequest.model_validate(
        {
            **command.request.model_dump(mode="json"),
            "order_type": "MARKET",
            "base_size": None,
            "quote_size": "1.005",
            "limit_price": None,
            "time_in_force": "IMMEDIATE_OR_CANCEL",
        }
    )

    response = _service(rest_client, registrar).place_manual_order(
        command.model_copy(update={"request": request})
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "quote_size_increment"
    assert response.data == {
        "blocker": "manual_spot_quote_size_increment_misaligned"
    }
    assert rest_client.create_calls == []
    assert registrar.rows == {}


def test_manual_order_planning_guard_rejects_above_stricter_executed_cap() -> None:
    rest_client = _SpotRestClient()
    registrar = _RootRegistrar()

    response = _service(rest_client, registrar).place_manual_order(
        _manual_command(
            base_size="0.021",
            limit_price="50.00",
            max_submitted_notional_usdc="3.10",
            max_executed_notional_usdc="1.00",
        )
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "action_condition_guard"
    assert response.guard["condition"] == "max_notional"
    assert response.guard["configured_limit"] == 1.0
    assert registrar.rows == {}
    assert rest_client.create_calls == []


def test_manual_order_planning_guard_accepts_exact_stricter_executed_cap() -> None:
    rest_client = _SpotRestClient()
    rest_client.history = [
        {
            "client_order_id": "22daf1ea-4c57-4c03-98c5-e74459576228",
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    registrar = _RootRegistrar()

    response = _service(rest_client, registrar).place_manual_order(
        _manual_command(
            base_size="0.02",
            limit_price="50.00",
            max_submitted_notional_usdc="3.10",
            max_executed_notional_usdc="1.00",
        )
    )

    assert response.status == AdminApiCommandStatus.ACCEPTED
    assert response.failure_stage is None
    assert len(rest_client.create_calls) == 1


def test_manual_order_planning_guard_rejects_notional_above_submitted_cap() -> None:
    rest_client = _SpotRestClient()
    registrar = _RootRegistrar()

    response = _service(rest_client, registrar).place_manual_order(
        _manual_command(
            base_size="0.063",
            limit_price="50.00",
            max_submitted_notional_usdc="3.10",
            max_executed_notional_usdc=None,
        )
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "action_condition_guard"
    assert response.guard["condition"] == "max_notional"
    assert response.guard["configured_limit"] == 3.1
    assert registrar.rows == {}
    assert rest_client.create_calls == []


@pytest.mark.parametrize("terminal_status", ["FILLED", "CANCELLED", "EXPIRED", "FAILED"])
def test_reconcile_selected_root_persists_exact_terminal_without_exchange_mutation(
    terminal_status: str,
) -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": terminal_status,
        }
    ]
    if terminal_status == "FILLED":
        rest_client.fills = [
            {
                "entry_id": "entry-evidence-only",
                "trade_id": "trade-evidence-only",
                "order_id": "exchange-order-1",
                "product_id": "BTC-USDC",
                "size": "0.01",
                "price": "100.00",
            }
        ]
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)
    recorded_proofs: list[dict[str, Any]] = []

    def record_proof(proof: Mapping[str, Any]) -> str:
        recorded_proofs.append(dict(proof))
        return "spot_fill_readback:proof-ref"

    response = _service(
        rest_client,
        registrar,
        fill_readback_proof_recorder=record_proof,
    ).reconcile_order_by_client_order_id(
        _reconcile_command(client_order_id)
    )

    assert response.status == AdminApiCommandStatus.ACCEPTED
    assert response.action_class.value == "local_state_mutation"
    assert response.required_permission.value == "order:cancel"
    assert response.live_exchange_submitted is False
    assert response.live_coinbase_orders_ran is False
    assert response.live_coinbase_read_ran is True
    assert rest_client.cancel_client_calls == []
    assert rest_client.cancel_exchange_calls == []
    assert rest_client.create_calls == []
    assert registrar.status_calls[-1] == (client_order_id, terminal_status)
    assert response.data["authoritative_status"] == terminal_status
    assert response.data["terminal_status_proven"] is True
    assert response.data["live_coinbase_read_ran"] is True
    assert response.data["order_status_persisted"] is True
    if terminal_status == "FILLED":
        assert rest_client.list_fills_calls == [
            {
                "order_id": "exchange-order-1",
                "product_id": "BTC-USDC",
                "limit": 100,
            }
        ]
        assert response.data["fill_closeout_proven"] is True
        assert response.data["live_fill_readback_proof_ref"] == (
            "spot_fill_readback:proof-ref"
        )
        assert len(recorded_proofs) == 1
        proof = recorded_proofs[0]
        assert proof["module_id"] == "spot_operations"
        assert proof["order_read_attempted"] is True
        assert proof["order_read_succeeded"] is True
        assert proof["fill_read_attempted"] is True
        assert proof["fill_read_succeeded"] is True
        assert proof["fill_count"] == 1
        assert proof["fill_order_id_matches_exchange_order_id"] is True
        assert proof["fill_product_id_matches_order"] is True
        assert proof["exchange_order_id_present"] is True
        assert proof["exchange_order_id_evidence_only"] is True
        assert "exchange_order_id" not in proof
        assert proof["audit_id"] == f"audit-reconcile-{client_order_id}"
        assert proof["correlation_id"] == f"corr-reconcile-{client_order_id}"
        assert proof["idempotency_key"] == f"idem-reconcile-{client_order_id}"
    else:
        assert rest_client.list_fills_calls == []
        assert recorded_proofs == []


def test_reconcile_resolves_create_unknown_to_exact_nonterminal_status() -> None:
    """Exact OPEN proof can resolve an uncertain Create without cancelling."""

    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)
    registrar.rows[client_order_id].update(
        {
            "status": OrderStatus.SUBMISSION_UNKNOWN.value,
            "exchange_order_id": "exchange-order-1",
        }
    )
    service = _service(rest_client, registrar)

    blocked_cancel = service.cancel_order_by_client_order_id(
        _cancel_command(client_order_id, idempotency_key="cancel-before-create-reconcile")
    )
    reconciled = service.reconcile_order_by_client_order_id(
        _reconcile_command(client_order_id)
    )

    assert blocked_cancel.status == AdminApiCommandStatus.REJECTED
    assert blocked_cancel.failure_stage == "cancellation_uncertainty"
    assert blocked_cancel.live_coinbase_read_ran is False
    assert blocked_cancel.live_coinbase_orders_ran is False
    assert reconciled.status == AdminApiCommandStatus.ACCEPTED
    assert reconciled.data["authoritative_status"] == OrderStatus.OPEN.value
    assert reconciled.data["terminal_status_proven"] is False
    assert reconciled.data["order_status_persisted"] is True
    assert registrar.rows[client_order_id]["status"] == OrderStatus.OPEN.value
    assert registrar.status_calls == [(client_order_id, OrderStatus.OPEN.value)]
    assert rest_client.cancel_client_calls == []
    assert rest_client.cancel_exchange_calls == []


def test_reconcile_preserves_cancel_unknown_on_nonterminal_readback() -> None:
    """An OPEN read cannot clear a durable prior Cancel uncertainty claim."""

    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)
    registrar.rows[client_order_id].update(
        {
            "status": OrderStatus.CANCELLATION_UNKNOWN.value,
            "exchange_order_id": "exchange-order-1",
        }
    )
    service = _service(rest_client, registrar)

    reconciled = service.reconcile_order_by_client_order_id(
        _reconcile_command(client_order_id)
    )
    cancelled = service.cancel_order_by_client_order_id(
        _cancel_command(client_order_id, idempotency_key="cancel-after-open-read")
    )

    assert reconciled.status == AdminApiCommandStatus.REJECTED
    assert reconciled.failure_stage == "reconciliation_cancel_unknown_nonterminal"
    assert reconciled.data["order_status_persisted"] is False
    assert reconciled.data["terminal_status_proven"] is False
    assert reconciled.data["recovery_disposition"] == (
        "quarantined_cancel_outcome_unknown_nonterminal"
    )
    assert reconciled.data["safe_to_submit_another_root"] is False
    assert registrar.rows[client_order_id]["status"] == (
        OrderStatus.CANCELLATION_UNKNOWN.value
    )
    assert registrar.status_calls == []
    assert cancelled.status == AdminApiCommandStatus.REJECTED
    assert cancelled.failure_stage == "cancellation_uncertainty"
    assert cancelled.live_coinbase_read_ran is False
    assert cancelled.live_coinbase_orders_ran is False
    assert rest_client.cancel_client_calls == []
    assert rest_client.cancel_exchange_calls == []


def test_reconcile_terminal_proof_may_clear_cancel_unknown() -> None:
    """Exact terminal proof can safely replace the durable Cancel quarantine."""

    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "CANCELLED",
        }
    ]
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)
    registrar.rows[client_order_id].update(
        {
            "status": OrderStatus.CANCELLATION_UNKNOWN.value,
            "exchange_order_id": "exchange-order-1",
        }
    )

    response = _service(rest_client, registrar).reconcile_order_by_client_order_id(
        _reconcile_command(client_order_id)
    )

    assert response.status == AdminApiCommandStatus.ACCEPTED
    assert response.data["terminal_status_proven"] is True
    assert response.data["authoritative_status"] == "CANCELLED"
    assert registrar.rows[client_order_id]["status"] == OrderStatus.CANCELLED.value
    assert registrar.status_calls == [
        (client_order_id, OrderStatus.CANCELLED.value)
    ]
    assert rest_client.cancel_client_calls == []
    assert rest_client.cancel_exchange_calls == []


@pytest.mark.parametrize(
    ("fills", "has_next"),
    [
        ([], False),
        (
            [
                {
                    "order_id": "different-exchange-order",
                    "product_id": "BTC-USDC",
                }
            ],
            False,
        ),
        (
            [
                {
                    "order_id": "exchange-order-1",
                    "product_id": "BTC-USDC",
                }
            ],
            True,
        ),
    ],
)
def test_reconcile_filled_root_fails_closed_without_complete_exact_fill_proof(
    fills: list[dict[str, Any]],
    has_next: bool,
) -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "FILLED",
        }
    ]
    rest_client.fills = fills
    rest_client.fills_have_more_pages = has_next
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)
    recorded_proofs: list[dict[str, Any]] = []

    response = _service(
        rest_client,
        registrar,
        fill_readback_proof_recorder=lambda proof: (
            recorded_proofs.append(dict(proof)) or "unexpected-proof"
        ),
    ).reconcile_order_by_client_order_id(_reconcile_command(client_order_id))

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "reconciliation_fill_readback"
    assert response.live_coinbase_read_ran is True
    assert response.data["order_status_persisted"] is True
    assert response.data["fill_closeout_proven"] is False
    assert response.data["recovery_disposition"] == (
        "quarantined_incomplete_fill_evidence"
    )
    assert response.data["safe_to_submit_another_root"] is False
    assert recorded_proofs == []


def test_reconcile_filled_root_fails_closed_when_sanitized_proof_cannot_persist() -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "FILLED",
        }
    ]
    rest_client.fills = [
        {"order_id": "exchange-order-1", "product_id": "BTC-USDC"}
    ]
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)

    response = _service(
        rest_client,
        registrar,
        fill_readback_proof_recorder=lambda _proof: None,
    ).reconcile_order_by_client_order_id(_reconcile_command(client_order_id))

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "reconciliation_fill_proof_persistence"
    assert response.data["order_status_persisted"] is True
    assert response.data["fill_read_succeeded"] is True
    assert response.data["fill_closeout_proven"] is False
    assert response.data["recovery_disposition"] == (
        "quarantined_fill_proof_persistence_failed"
    )
    assert response.data["safe_to_submit_another_root"] is False


def test_reconcile_fill_converter_exception_is_value_blind_quarantine() -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"

    class _RaisingFillEnvelope:
        def to_dict(self) -> dict[str, Any]:
            raise RuntimeError("withheld raw fill response")

    class _RaisingFillClient(_SpotRestClient):
        def list_fills(self, **kwargs: Any) -> Any:
            self.list_fills_calls.append(dict(kwargs))
            return _RaisingFillEnvelope()

    rest_client = _RaisingFillClient()
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "FILLED",
        }
    ]
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)

    response = _service(rest_client, registrar).reconcile_order_by_client_order_id(
        _reconcile_command(client_order_id)
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "reconciliation_fill_readback"
    assert response.data["fill_readback"]["blocker"] == (
        "fill_read_normalization_failed"
    )
    assert response.data["fill_readback"]["detail"] == (
        "Coinbase fill response normalization failed: exception_class:RuntimeError"
    )
    assert "withheld raw" not in str(response.model_dump(mode="json"))
    assert response.data["order_status_persisted"] is True
    assert response.data["safe_to_submit_another_root"] is False


def test_reconcile_read_exception_is_fixed_quarantine_without_status_persistence() -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"

    class _RaisingRestClient(_SpotRestClient):
        def list_orders(self, **_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("withheld private transport text")

    rest_client = _RaisingRestClient()
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)

    response = _service(rest_client, registrar).reconcile_order_by_client_order_id(
        _reconcile_command(client_order_id)
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "reconciliation_readback"
    assert response.data["readback"]["detail"] == (
        "Coinbase order read failed: exception_class:RuntimeError"
    )
    assert "withheld" not in str(response.model_dump(mode="json"))
    assert response.data["order_status_persisted"] is False
    assert response.data["recovery_disposition"] == (
        "quarantined_ambiguous_readback"
    )
    assert response.data["safe_to_submit_another_root"] is False


def test_reconcile_status_persistence_failure_is_explicit_quarantine() -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"

    class _FailingRegistrar(_RootRegistrar):
        def mark_submission_status(self, **_kwargs: Any) -> None:
            raise RuntimeError("withheld database detail")

    rest_client = _SpotRestClient()
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    registrar = _FailingRegistrar()
    _registered_root(registrar, client_order_id)

    response = _service(rest_client, registrar).reconcile_order_by_client_order_id(
        _reconcile_command(client_order_id)
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "reconciliation_status_persistence"
    assert response.data["order_status_persisted"] is False
    assert response.data["recovery_disposition"] == (
        "quarantined_status_persistence_failed"
    )
    assert response.data["safe_to_submit_another_root"] is False
    assert "withheld database" not in str(response.model_dump(mode="json"))


def test_reconcile_selected_root_fails_closed_on_authoritative_absence() -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)

    response = _service(rest_client, registrar).reconcile_order_by_client_order_id(
        _reconcile_command(client_order_id)
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "reconciliation_readback"
    assert response.live_exchange_submitted is False
    assert response.live_coinbase_orders_ran is False
    assert response.live_coinbase_read_ran is True
    assert registrar.status_calls == []
    assert response.data["recovery_disposition"] == (
        "quarantined_unresolved_absence"
    )
    assert response.data["safe_to_submit_another_root"] is False


def test_reconcile_selected_root_cross_binds_stored_exchange_identity() -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "different-exchange-order",
            "product_id": "BTC-USDC",
            "status": "FILLED",
        }
    ]
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)
    registrar.rows[client_order_id]["exchange_order_id"] = "stored-exchange-order"

    response = _service(rest_client, registrar).reconcile_order_by_client_order_id(
        _reconcile_command(client_order_id)
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "reconciliation_readback"
    assert rest_client.get_calls == ["stored-exchange-order"]
    assert registrar.status_calls == []


def _service(
    rest_client: _SpotRestClient,
    registrar: _RootRegistrar,
    *,
    publisher: _Publisher | None = None,
    coordinator: SpotProfileOrderAdmissionCoordinator | None = None,
    market_reference: dict[str, Any] | None = None,
    fill_readback_proof_recorder: Callable[[Mapping[str, Any]], str | None] | None = None,
) -> AdminApiCommandService:
    publisher = publisher or _Publisher()
    resolved_market_reference = market_reference or {
        "product_id": "BTC-USDC",
        "best_bid": "100.00",
        "best_ask": "100.01",
        "source": "ticker",
        "observed_at": datetime.now(timezone.utc),
    }
    return AdminApiCommandService(
        AdminApiCommandDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_runtime_enabled=True,
            command_runtime_ready=True,
            spot_portfolio_id=TEST_PORTFOLIO_ID,
            spot_portfolio_label="Test",
            spot_market_reference_getter=lambda _product_id: dict(
                resolved_market_reference
            ),
            order_event_publisher_getter=lambda: publisher,
            order_root_registrar_getter=lambda: registrar,
            runtime_controller_factory=lambda: _RuntimeController(),
            spot_order_admission_coordinator=(
                coordinator or SpotProfileOrderAdmissionCoordinator()
            ),
            spot_fill_readback_proof_recorder=(
                fill_readback_proof_recorder or (lambda _proof: None)
            ),
        )
    )


def _registered_root(
    registrar: _RootRegistrar,
    client_order_id: str,
    *,
    provenance: str = "ADMIN_MANUAL_ROOT",
    parent_order_id: str | None = None,
) -> None:
    registrar.rows[client_order_id] = {
        "client_order_id": client_order_id,
        "retail_portfolio_id": TEST_PORTFOLIO_ID,
        "ownership_provenance": provenance,
        "parent_order_id": parent_order_id,
        "status": "OPEN",
        "product_id": "BTC-USDC",
    }


AUTOMATION_RUN_ID = "7c8ca6b1-f3cf-4a02-b65b-d16966a39e28"
AUTOMATION_DEFINITION_ID = "f15c025a-8b1c-412a-8be6-88848d1bc5e2"
AUTOMATION_PLAN_SHA256 = "a" * 64


def _automation_portfolio_binding() -> SpotPortfolioBindingEvidence:
    return SpotPortfolioBindingEvidence(
        ready=True,
        blocker=None,
        expected_portfolio_id=TEST_PORTFOLIO_ID,
        expected_portfolio_label="Test",
        expected_portfolio_type="CONSUMER",
        observed_portfolio_id=TEST_PORTFOLIO_ID,
        observed_portfolio_label="Test",
        observed_portfolio_type="CONSUMER",
        can_view=True,
        can_trade=True,
    )


def _automation_ownership(
    lease: object,
    *,
    fresh_until: datetime | None = None,
    client_order_id: str = "22daf1ea-4c57-4c03-98c5-e74459576228",
    base_size: str = "0.02",
    limit_price: str = "50.00",
    post_only: bool = False,
    policy_revision: int = 2,
    standing_price_policy: str = "STANDARD_STANDING_V2",
) -> ValidatedSpotAutomationOwnershipEvidence:
    return ValidatedSpotAutomationOwnershipEvidence(
        run_id=AUTOMATION_RUN_ID,
        definition_id=AUTOMATION_DEFINITION_ID,
        definition_revision=1,
        plan_sha256=AUTOMATION_PLAN_SHA256,
        client_order_id=client_order_id,
        product_id="BTC-USDC",
        side="BUY",
        base_size=Decimal(base_size),
        limit_price=Decimal(limit_price),
        post_only=post_only,
        policy_revision=policy_revision,
        standing_price_policy=standing_price_policy,
        portfolio_id_sha256=hashlib.sha256(
            TEST_PORTFOLIO_ID.encode("utf-8")
        ).hexdigest(),
        fresh_until=fresh_until
        or datetime.now(timezone.utc) + timedelta(seconds=30),
        portfolio_binding=_automation_portfolio_binding(),
        lease=lease,
    )


def _automation_admission(
    lease: object,
    *,
    fresh_until: datetime | None = None,
    client_order_id: str = "22daf1ea-4c57-4c03-98c5-e74459576228",
    base_size: str = "0.02",
    limit_price: str = "50.00",
    post_only: bool = False,
    policy_revision: int = 2,
    standing_price_policy: str = "STANDARD_STANDING_V2",
    market_source: str = "coinbase_rest_best_bid",
    max_submitted_notional_usdc: str = "3.10",
    max_possible_execution_notional_usdc: str = "1.00",
    available_balance: str = "10.00",
) -> ValidatedSpotAutomationAdmissionEvidence:
    now = datetime.now(timezone.utc)
    expires = fresh_until or now + timedelta(seconds=30)
    transient_expires = max(expires, now + timedelta(seconds=30))
    ownership = _automation_ownership(
        lease,
        fresh_until=expires,
        client_order_id=client_order_id,
        base_size=base_size,
        limit_price=limit_price,
        post_only=post_only,
        policy_revision=policy_revision,
        standing_price_policy=standing_price_policy,
    )
    return ValidatedSpotAutomationAdmissionEvidence(
        **{
            field: getattr(ownership, field)
            for field in ownership.__dataclass_fields__
        },
        wallet_evidence=SpotAutomationWalletEvidence(
            required_currency="USDC",
            available_balance=Decimal(available_balance),
            planned_commitment=Decimal("0"),
            known_inventory_available=True,
            known_inventory_base_size=Decimal("0.02"),
            observed_at=now,
            fresh_until=transient_expires,
            source="coinbase_account_wallet_refresh",
            evidence_sha256="b" * 64,
        ),
        market_evidence=SpotAutomationMarketEvidence(
            best_bid=Decimal("100.00"),
            best_ask=Decimal("100.01"),
            observed_at=now,
            fresh_until=transient_expires,
            source=market_source,
            evidence_sha256="c" * 64,
        ),
        zero_active_order_evidence=SpotAutomationZeroActiveOrderEvidence(
            authoritative=True,
            open_order_count=0,
            logical_call_count=1,
            http_request_count=1,
            call_count_exact=True,
            pagination_complete=True,
            page_count=1,
            observed_at=now,
            fresh_until=transient_expires,
            evidence_sha256="d" * 64,
        ),
        max_submitted_notional_usdc=Decimal(max_submitted_notional_usdc),
        max_possible_execution_notional_usdc=Decimal(
            max_possible_execution_notional_usdc
        ),
    )


def test_profile_admission_claim_yields_exact_thread_bound_expiring_lease() -> None:
    coordinator = SpotProfileOrderAdmissionCoordinator()
    thread_result: list[str] = []

    with coordinator.claim(TEST_PORTFOLIO_ID) as lease:
        coordinator.require_active_lease(
            lease,
            retail_portfolio_id=TEST_PORTFOLIO_ID,
        )

        def validate_from_other_thread() -> None:
            try:
                coordinator.require_active_lease(
                    lease,
                    retail_portfolio_id=TEST_PORTFOLIO_ID,
                )
            except SpotProfileAdmissionLeaseError as exc:
                thread_result.append(str(exc))

        worker = Thread(target=validate_from_other_thread)
        worker.start()
        worker.join(timeout=2)

    assert thread_result == ["spot_profile_admission_lease_thread_mismatch"]
    with pytest.raises(
        SpotProfileAdmissionLeaseError,
        match="spot_profile_admission_lease_inactive",
    ):
        coordinator.require_active_lease(
            lease,
            retail_portfolio_id=TEST_PORTFOLIO_ID,
        )


def test_automation_submit_reuses_evidence_without_duplicate_reads_and_registers_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import configuration

    monkeypatch.setattr(
        configuration,
        "ACTION_CONDITION_GUARDS",
        {"wallet_available": True, "limits": []},
        raising=False,
    )
    monkeypatch.setattr(
        configuration,
        "rest_get_account_wallets",
        lambda: (_ for _ in ()).throw(AssertionError("duplicate wallet read")),
        raising=False,
    )
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    registrar = _RootRegistrar()
    coordinator = SpotProfileOrderAdmissionCoordinator()
    service = _service(rest_client, registrar, coordinator=coordinator)
    service.dependencies.spot_market_reference_getter = lambda _product_id: (
        (_ for _ in ()).throw(AssertionError("duplicate market read"))
    )

    with coordinator.claim(TEST_PORTFOLIO_ID) as lease:
        response = service.place_manual_order(
            _manual_command(
                client_order_id,
                approval_snapshot_id="approval-automation-1",
                max_submitted_notional_usdc="3.10",
                max_executed_notional_usdc="1.00",
                post_only=False,
            ),
            automation_admission=_automation_admission(lease),
        )

    assert response.status == AdminApiCommandStatus.ACCEPTED, (
        response.failure_stage,
        response.message,
        response.data,
    )
    assert response.live_coinbase_read_call_count == 1
    assert rest_client.api_key_permission_calls == 0
    assert rest_client.portfolio_calls == 0
    assert rest_client.list_calls == []
    assert len(rest_client.create_calls) == 1
    assert rest_client.get_calls == ["exchange-order-1"]
    assert registrar.rows[client_order_id]["ownership_provenance"] == (
        "ADMIN_AUTOMATION_ROOT"
    )


def test_near_market_automation_uses_typed_post_only_bid_policy_without_global_half_bid_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import configuration

    monkeypatch.setattr(
        configuration,
        "ACTION_CONDITION_GUARDS",
        {"wallet_available": True, "limits": []},
        raising=False,
    )
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    registrar = _RootRegistrar()
    coordinator = SpotProfileOrderAdmissionCoordinator()
    service = _service(rest_client, registrar, coordinator=coordinator)

    with coordinator.claim(TEST_PORTFOLIO_ID) as lease:
        response = service.place_manual_order(
            _manual_command(
                client_order_id,
                base_size="0.01",
                limit_price="100.00",
                post_only=True,
                approval_snapshot_id="approval-near-market-automation",
                max_submitted_notional_usdc="3.10",
                max_executed_notional_usdc="1.00",
            ),
            automation_admission=_automation_admission(
                lease,
                base_size="0.01",
                limit_price="100.00",
                post_only=True,
                policy_revision=3,
                standing_price_policy="NEAR_MARKET_POST_ONLY_V1",
                market_source="coinbase_rest_market_trade_snapshot",
            ),
        )

    assert response.status == AdminApiCommandStatus.ACCEPTED, (
        response.failure_stage,
        response.message,
        response.data,
    )
    assert len(rest_client.create_calls) == 1
    configuration = rest_client.create_calls[0]["order_configuration"]
    assert configuration["limit_limit_gtc"]["post_only"] is True


def test_minimum_size_automation_binds_backend_derived_execution_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import configuration

    monkeypatch.setattr(
        configuration,
        "ACTION_CONDITION_GUARDS",
        {"wallet_available": True, "limits": []},
        raising=False,
    )
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    coordinator = SpotProfileOrderAdmissionCoordinator()
    service = _service(rest_client, _RootRegistrar(), coordinator=coordinator)

    with coordinator.claim(TEST_PORTFOLIO_ID) as lease:
        response = service.place_manual_order(
            _manual_command(
                client_order_id,
                base_size="0.01",
                limit_price="100.00",
                post_only=True,
                approval_snapshot_id="approval-minimum-size-automation",
                max_submitted_notional_usdc="3.10",
                max_executed_notional_usdc="1.01",
            ),
            automation_admission=_automation_admission(
                lease,
                base_size="0.01",
                limit_price="100.00",
                post_only=True,
                policy_revision=4,
                standing_price_policy=(
                    "NEAR_MARKET_POST_ONLY_MINIMUM_SIZE_V2"
                ),
                market_source="coinbase_rest_market_trade_snapshot",
                max_possible_execution_notional_usdc="1.01",
            ),
        )

    assert response.status == AdminApiCommandStatus.ACCEPTED, (
        response.failure_stage,
        response.message,
        response.data,
    )
    assert len(rest_client.create_calls) == 1


@pytest.mark.parametrize(
    ("limit_price", "expected_status"),
    [
        ("100.00", AdminApiCommandStatus.ACCEPTED),
        ("99.99", AdminApiCommandStatus.REJECTED),
    ],
)
def test_atomic_market_snapshot_automation_requires_exact_same_snapshot_bid(
    monkeypatch: pytest.MonkeyPatch,
    limit_price: str,
    expected_status: AdminApiCommandStatus,
) -> None:
    import configuration

    monkeypatch.setattr(
        configuration,
        "ACTION_CONDITION_GUARDS",
        {"wallet_available": True, "limits": []},
        raising=False,
    )
    rest_client = _SpotRestClient()
    rest_client.history = [
        {
            "client_order_id": "22daf1ea-4c57-4c03-98c5-e74459576228",
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    coordinator = SpotProfileOrderAdmissionCoordinator()
    service = _service(rest_client, _RootRegistrar(), coordinator=coordinator)

    with coordinator.claim(TEST_PORTFOLIO_ID) as lease:
        response = service.place_manual_order(
            _manual_command(
                base_size="0.02",
                limit_price=limit_price,
                post_only=True,
                approval_snapshot_id="approval-atomic-market-automation",
                max_submitted_notional_usdc="3.10",
                max_executed_notional_usdc="2.01",
            ),
            automation_admission=_automation_admission(
                lease,
                base_size="0.02",
                limit_price=limit_price,
                post_only=True,
                policy_revision=5,
                standing_price_policy=(
                    "ATOMIC_MARKET_SNAPSHOT_POST_ONLY_V1"
                ),
                market_source="coinbase_rest_market_trade_snapshot",
                max_possible_execution_notional_usdc="2.01",
            ),
        )

    assert response.status is expected_status
    assert len(rest_client.create_calls) == (
        1 if expected_status is AdminApiCommandStatus.ACCEPTED else 0
    )
    if expected_status is AdminApiCommandStatus.REJECTED:
        assert response.failure_stage == "standing_price_limit"


@pytest.mark.parametrize(
    ("policy_revision", "standing_price_policy", "approval_snapshot_id"),
    (
        (4, "NEAR_MARKET_POST_ONLY_MINIMUM_SIZE_V2", "approval-minimum-size-wallet"),
        (5, "ATOMIC_MARKET_SNAPSHOT_POST_ONLY_V1", "approval-atomic-market-wallet"),
    ),
)
def test_dynamic_cap_automation_requires_fee_reserved_wallet_cap(
    monkeypatch: pytest.MonkeyPatch,
    policy_revision: int,
    standing_price_policy: str,
    approval_snapshot_id: str,
) -> None:
    import configuration

    monkeypatch.setattr(
        configuration,
        "ACTION_CONDITION_GUARDS",
        {"wallet_available": True, "limits": []},
        raising=False,
    )
    rest_client = _SpotRestClient()
    coordinator = SpotProfileOrderAdmissionCoordinator()
    service = _service(rest_client, _RootRegistrar(), coordinator=coordinator)

    with coordinator.claim(TEST_PORTFOLIO_ID) as lease:
        response = service.place_manual_order(
            _manual_command(
                base_size="0.01",
                limit_price="100.00",
                post_only=True,
                approval_snapshot_id=approval_snapshot_id,
                max_submitted_notional_usdc="3.10",
                max_executed_notional_usdc="1.01",
            ),
            automation_admission=_automation_admission(
                lease,
                base_size="0.01",
                limit_price="100.00",
                post_only=True,
                policy_revision=policy_revision,
                standing_price_policy=standing_price_policy,
                market_source="coinbase_rest_market_trade_snapshot",
                max_possible_execution_notional_usdc="1.01",
                available_balance="1.00",
            ),
        )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "automation_admission"
    assert rest_client.create_calls == []


def test_minimum_size_admission_rejects_submitted_notional_at_strict_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import configuration

    monkeypatch.setattr(
        configuration,
        "ACTION_CONDITION_GUARDS",
        {"wallet_available": True, "limits": []},
        raising=False,
    )
    rest_client = _SpotRestClient()
    coordinator = SpotProfileOrderAdmissionCoordinator()
    service = _service(rest_client, _RootRegistrar(), coordinator=coordinator)

    with coordinator.claim(TEST_PORTFOLIO_ID) as lease:
        with pytest.raises(
            ValueError,
            match="^spot_automation_cap_policy_invalid$",
        ):
            _automation_admission(
                lease,
                base_size="0.031",
                limit_price="100.00",
                post_only=True,
                policy_revision=4,
                standing_price_policy=(
                    "NEAR_MARKET_POST_ONLY_MINIMUM_SIZE_V2"
                ),
                market_source="coinbase_rest_market_trade_snapshot",
                max_possible_execution_notional_usdc="3.09",
            )

    assert rest_client.create_calls == []


def test_ordinary_manual_order_rejects_dynamic_cap_without_automation_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import configuration

    monkeypatch.setattr(
        configuration,
        "ACTION_CONDITION_GUARDS",
        {"wallet_available": True, "limits": []},
        raising=False,
    )
    rest_client = _SpotRestClient()
    service = _service(
        rest_client,
        _RootRegistrar(),
        coordinator=SpotProfileOrderAdmissionCoordinator(),
    )

    response = service.place_manual_order(
        _manual_command(
            base_size="0.01",
            limit_price="100.00",
            post_only=True,
            max_submitted_notional_usdc="3.10",
            max_executed_notional_usdc="1.01",
        )
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "cap_guard"
    assert rest_client.create_calls == []


def test_near_market_automation_rejects_non_trade_snapshot_before_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import configuration

    monkeypatch.setattr(
        configuration,
        "ACTION_CONDITION_GUARDS",
        {"wallet_available": True, "limits": []},
        raising=False,
    )
    rest_client = _SpotRestClient()
    registrar = _RootRegistrar()
    coordinator = SpotProfileOrderAdmissionCoordinator()
    service = _service(rest_client, registrar, coordinator=coordinator)

    with coordinator.claim(TEST_PORTFOLIO_ID) as lease:
        response = service.place_manual_order(
            _manual_command(
                base_size="0.01",
                limit_price="100.00",
                post_only=True,
                approval_snapshot_id="approval-near-market-automation",
                max_submitted_notional_usdc="3.10",
                max_executed_notional_usdc="1.00",
            ),
            automation_admission=_automation_admission(
                lease,
                base_size="0.01",
                limit_price="100.00",
                post_only=True,
                policy_revision=3,
                standing_price_policy="NEAR_MARKET_POST_ONLY_V1",
                market_source="coinbase_rest_best_bid",
            ),
        )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "standing_price_limit"
    assert response.data["standing_price_limit"]["blocker"] == (
        "near_market_market_source_invalid"
    )
    assert rest_client.create_calls == []


def test_manual_submit_after_restart_blocks_on_unresolved_automation_root() -> None:
    automation_client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    manual_client_order_id = "0ba18a83-b30c-4c71-ad01-8f4e439d8f70"

    class _CrossPathRegistrar(_RootRegistrar):
        def __init__(self) -> None:
            super().__init__()
            self.manual_unresolved_reads = 0
            self.spot_unresolved_reads = 0

        def get_unresolved_admin_manual_root_submissions(
            self,
            retail_portfolio_id: str,
        ) -> list[dict[str, Any]]:
            self.manual_unresolved_reads += 1
            return super().get_unresolved_admin_manual_root_submissions(
                retail_portfolio_id,
            )

        def get_unresolved_admin_spot_root_submissions(
            self,
            retail_portfolio_id: str,
        ) -> list[dict[str, Any]]:
            self.spot_unresolved_reads += 1
            return super().get_unresolved_admin_spot_root_submissions(
                retail_portfolio_id,
            )

    rest_client = _SpotRestClient()
    rest_client.history = [
        {
            "client_order_id": manual_client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    registrar = _CrossPathRegistrar()
    _registered_root(
        registrar,
        automation_client_order_id,
        provenance="ADMIN_AUTOMATION_ROOT",
    )

    response = _service(
        rest_client,
        registrar,
        coordinator=SpotProfileOrderAdmissionCoordinator(),
    ).place_manual_order(_manual_command(manual_client_order_id))

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "submission_uncertainty"
    assert response.data["runtime_submission_uncertainties"] == []
    assert len(response.data["durable_unresolved_roots"]) == 1
    assert response.data["durable_unresolved_roots"][0][
        "ownership_provenance"
    ] == "ADMIN_AUTOMATION_ROOT"
    assert registrar.manual_unresolved_reads == 0
    assert registrar.spot_unresolved_reads == 1
    assert rest_client.create_calls == []


@pytest.mark.parametrize("mode", ["expired", "unlocked", "wrong_coordinator"])
def test_automation_submit_rejects_invalid_typed_evidence_before_any_call(
    mode: str,
) -> None:
    rest_client = _SpotRestClient()
    registrar = _RootRegistrar()
    coordinator = SpotProfileOrderAdmissionCoordinator()
    service = _service(rest_client, registrar, coordinator=coordinator)
    issuer = (
        SpotProfileOrderAdmissionCoordinator()
        if mode == "wrong_coordinator"
        else coordinator
    )
    with issuer.claim(TEST_PORTFOLIO_ID) as lease:
        evidence = _automation_admission(
            lease,
            fresh_until=(
                datetime.now(timezone.utc) - timedelta(seconds=1)
                if mode == "expired"
                else None
            ),
        )
        if mode != "unlocked":
            response = service.place_manual_order(
                _manual_command(
                    max_submitted_notional_usdc="3.10",
                    max_executed_notional_usdc="1.00",
                ),
                automation_admission=evidence,
            )
    if mode == "unlocked":
        response = service.place_manual_order(
            _manual_command(
                max_submitted_notional_usdc="3.10",
                max_executed_notional_usdc="1.00",
            ),
            automation_admission=evidence,
        )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "automation_admission"
    assert response.live_coinbase_read_call_count == 0
    assert rest_client.api_key_permission_calls == 0
    assert rest_client.portfolio_calls == 0
    assert rest_client.list_calls == []
    assert rest_client.get_calls == []
    assert rest_client.create_calls == []
    assert registrar.rows == {}


def test_automation_reconcile_and_cancel_reuse_typed_ownership_without_portfolio_reads() -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"

    class _TerminalizingCancelClient(_SpotRestClient):
        def cancel_order(self, *args: Any, **kwargs: Any) -> Any:
            result = super().cancel_order(*args, **kwargs)
            self.history[0]["status"] = "CANCELLED"
            return result

    rest_client = _TerminalizingCancelClient()
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    registrar = _RootRegistrar()
    _registered_root(
        registrar,
        client_order_id,
        provenance="ADMIN_AUTOMATION_ROOT",
    )
    registrar.rows[client_order_id]["exchange_order_id"] = "exchange-order-1"
    coordinator = SpotProfileOrderAdmissionCoordinator()
    service = _service(rest_client, registrar, coordinator=coordinator)

    with coordinator.claim(TEST_PORTFOLIO_ID) as lease:
        ownership = _automation_ownership(lease)
        reconciled = service.reconcile_order_by_client_order_id(
            _reconcile_command(client_order_id),
            automation_ownership=ownership,
        )
        cancelled = service.cancel_order_by_client_order_id(
            _cancel_command(client_order_id),
            automation_ownership=ownership,
        )

    assert reconciled.status == AdminApiCommandStatus.ACCEPTED
    assert cancelled.status == AdminApiCommandStatus.ACCEPTED
    assert reconciled.live_coinbase_read_call_count == 1
    assert cancelled.live_coinbase_read_call_count == 2
    assert rest_client.api_key_permission_calls == 0
    assert rest_client.portfolio_calls == 0
    assert rest_client.cancel_exchange_calls == ["exchange-order-1"]


def test_automation_cancel_counts_two_page_pre_read_and_one_page_post_read() -> None:
    """Create persistence loss must not undercount list-based safe closeout reads."""

    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"

    class _TwoPagePreReadTerminalizingCancelClient(_SpotRestClient):
        def list_orders(self, **kwargs: Any) -> dict[str, Any]:
            self.list_calls.append(dict(kwargs))
            if kwargs.get("cursor") is None:
                return {
                    "orders": [
                        {
                            "client_order_id": "unrelated-client-order",
                            "order_id": "unrelated-exchange-order",
                            "product_id": "BTC-USDC",
                            "status": "OPEN",
                        }
                    ],
                    "has_next": True,
                    "cursor": "pre-read-page-2",
                }
            assert kwargs["cursor"] == "pre-read-page-2"
            return {
                "orders": [dict(self.history[0])],
                "has_next": False,
            }

        def cancel_order(self, *args: Any, **kwargs: Any) -> Any:
            result = super().cancel_order(*args, **kwargs)
            self.history[0]["status"] = "CANCELLED"
            return result

    rest_client = _TwoPagePreReadTerminalizingCancelClient()
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    registrar = _RootRegistrar()
    _registered_root(
        registrar,
        client_order_id,
        provenance="ADMIN_AUTOMATION_ROOT",
    )
    assert "exchange_order_id" not in registrar.rows[client_order_id]
    coordinator = SpotProfileOrderAdmissionCoordinator()
    service = _service(rest_client, registrar, coordinator=coordinator)

    with coordinator.claim(TEST_PORTFOLIO_ID) as lease:
        response = service.cancel_order_by_client_order_id(
            _cancel_command(client_order_id),
            automation_ownership=_automation_ownership(lease),
        )

    assert response.status == AdminApiCommandStatus.ACCEPTED
    assert response.live_coinbase_read_call_count == 3
    cancellation = response.data["cancellation_readback"]
    assert cancellation["pre_cancel_read_page_count"] == 2
    assert cancellation["authoritative_readback"]["page_count"] == 1
    assert len(rest_client.list_calls) == 2
    assert rest_client.get_calls == ["exchange-order-1"]
    assert rest_client.cancel_exchange_calls == ["exchange-order-1"]


def test_submit_rejects_off_tick_price_before_root_or_coinbase_boundary() -> None:
    rest_client = _SpotRestClient()
    registrar = _RootRegistrar()

    response = _service(rest_client, registrar).place_manual_order(
        _manual_command(limit_price="49.999")
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "price_increment"
    assert response.data["price_increment"] == {
        "product_id": "BTC-USDC",
        "limit_price": "49.999",
        "configured_price_increment": "0.01",
        "tick_aligned": False,
    }
    assert rest_client.api_key_permission_calls == 0
    assert rest_client.portfolio_calls == 0
    assert rest_client.list_calls == []
    assert rest_client.create_calls == []
    assert registrar.rows == {}


@pytest.mark.parametrize("outer_authority", [None, "0", "true", "yes", "01"])
@pytest.mark.parametrize("command_kind", ["place", "cancel", "hotpoint"])
def test_canonical_command_boundary_requires_exact_master_before_coinbase_reads(
    monkeypatch: pytest.MonkeyPatch,
    outer_authority: str | None,
    command_kind: str,
) -> None:
    if outer_authority is None:
        monkeypatch.delenv("COINBASE_EXECUTION_ENABLED", raising=False)
    else:
        monkeypatch.setenv("COINBASE_EXECUTION_ENABLED", outer_authority)
    rest_client = _SpotRestClient()
    registrar = _RootRegistrar()
    service = _service(rest_client, registrar)

    if command_kind == "place":
        response = service.place_manual_order(_manual_command())
    elif command_kind == "cancel":
        response = service.cancel_order_by_client_order_id(
            _cancel_command("client-order-authority-test")
        )
    else:
        response = service.place_hotpoint_test_order(_manual_command())

    assert response.status == AdminApiCommandStatus.NOT_IMPLEMENTED
    assert response.failure_stage == "execution_authority"
    assert response.live_command_runtime_enabled is False
    assert response.live_command_runtime_ready is False
    assert (
        response.live_command_runtime_missing_reason
        == "coinbase_execution_authority_disabled"
    )
    assert rest_client.api_key_permission_calls == 0
    assert rest_client.portfolio_calls == 0
    assert rest_client.list_calls == []
    assert rest_client.create_calls == []
    assert rest_client.cancel_client_calls == []
    assert rest_client.cancel_exchange_calls == []
    assert registrar.rows == {}


def test_submit_preserves_on_tick_price_through_root_and_coinbase_boundary() -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"

    class _AcceptingClient(_SpotRestClient):
        def create_order(self, **kwargs: Any) -> Any:
            self.create_calls.append(dict(kwargs))
            self.history = [
                {
                    "client_order_id": kwargs["client_order_id"],
                    "order_id": "exchange-order-1",
                    "product_id": "BTC-USDC",
                    "status": "OPEN",
                }
            ]
            return self.create_result

    rest_client = _AcceptingClient()
    registrar = _RootRegistrar()

    response = _service(rest_client, registrar).place_manual_order(
        _manual_command(limit_price="50.00")
    )

    assert response.status == AdminApiCommandStatus.ACCEPTED
    assert response.live_coinbase_read_ran is True
    assert response.live_coinbase_read_call_count is None
    assert registrar.rows[client_order_id]["limit_price"] == "50.00"
    assert rest_client.create_calls[0]["order_configuration"] == {
        "limit_limit_gtc": {
            "base_size": "0.02",
            "limit_price": "50.00",
            "post_only": True,
        }
    }
    assert rest_client.get_calls == ["exchange-order-1"]
    assert not any(call.get("order_ids") for call in rest_client.list_calls)
    assert registrar.exchange_status_calls[-1] == {
        "client_order_id": client_order_id,
        "status": "OPEN",
        "exchange_order_id": "exchange-order-1",
    }
    assert registrar.rows[client_order_id]["exchange_order_id"] == (
        "exchange-order-1"
    )


def test_canonical_manual_order_rejects_intentional_fill_fok_before_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import configuration

    monkeypatch.setattr(
        configuration,
        "PRODUCT_CAPABILITIES",
        {
            "product_id": {
                "BTC-USDC": {
                    "filled_follow_up": "conditional",
                    "partial_fill_follow_up": "disabled",
                    "cancelled_follow_up": "disabled",
                    "stealth_reveal": "disabled",
                }
            }
        },
    )
    monkeypatch.setattr(
        configuration,
        "ACTION_CONDITION_GUARDS",
        {
            "wallet_available": {
                "enabled": True,
                "check_follow_up_planning": False,
                "fail_open_on_fetch_error": False,
            },
            "limits": [],
        },
    )

    class _AcceptingClient(_SpotRestClient):
        def create_order(self, **kwargs: Any) -> Any:
            self.create_calls.append(dict(kwargs))
            self.history = [
                {
                    "client_order_id": kwargs["client_order_id"],
                    "order_id": "exchange-intentional-fill-1",
                    "product_id": "BTC-USDC",
                    "status": "FILLED",
                }
            ]
            return {
                "success": True,
                "success_response": {
                    "order_id": "exchange-intentional-fill-1"
                },
            }

    rest_client = _AcceptingClient()
    registrar = _RootRegistrar()
    response = _service(rest_client, registrar).place_manual_order(
        _manual_command(
            limit_price="100.10",
            operator_intent=(
                "execute_one_approved_intentional_test_profile_spot_fill"
            ),
            post_only=False,
            time_in_force="FILL_OR_KILL",
            approval_snapshot_id="approval-intentional-fill-1",
        )
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "manual_order_semantics"
    assert response.data == {
        "semantic_contract": "durable_spot_limit_gtc_root",
        "blocker": "manual_spot_time_in_force_not_supported",
    }
    assert rest_client.api_key_permission_calls == 0
    assert rest_client.portfolio_calls == 0
    assert registrar.rows == {}
    assert rest_client.create_calls == []


def test_fok_semantic_rejection_precedes_intentional_fill_fee_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import configuration

    monkeypatch.setattr(
        configuration,
        "PRODUCT_CAPABILITIES",
        {
            "product_id": {
                "BTC-USDC": {
                    "filled_follow_up": "conditional",
                    "partial_fill_follow_up": "disabled",
                    "cancelled_follow_up": "disabled",
                    "stealth_reveal": "disabled",
                }
            }
        },
    )
    monkeypatch.setattr(
        configuration,
        "ACTION_CONDITION_GUARDS",
        {
            "wallet_available": {
                "enabled": True,
                "check_follow_up_planning": False,
                "fail_open_on_fetch_error": False,
            },
            "limits": [],
        },
    )

    class _BlockedTargetRegistrar(_RootRegistrar):
        def build_intentional_fill_target_movement(
            self,
            **_kwargs: Any,
        ) -> dict[str, Any]:
            return {
                "ready": False,
                "blocker": "intentional_fill_fee_data_stale",
            }

    rest_client = _SpotRestClient()
    registrar = _BlockedTargetRegistrar()
    response = _service(rest_client, registrar).place_manual_order(
        _manual_command(
            limit_price="100.10",
            operator_intent=(
                "execute_one_approved_intentional_test_profile_spot_fill"
            ),
            post_only=False,
            time_in_force="FILL_OR_KILL",
            approval_snapshot_id="approval-intentional-fill-1",
        )
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "manual_order_semantics"
    assert response.data["blocker"] == (
        "manual_spot_time_in_force_not_supported"
    )
    assert registrar.rows == {}
    assert rest_client.create_calls == []


def test_fok_semantic_rejection_precedes_child_reveal_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import configuration

    monkeypatch.setattr(
        configuration,
        "PRODUCT_CAPABILITIES",
        {
            "product_id": {
                "BTC-USDC": {
                    "filled_follow_up": "conditional",
                    "partial_fill_follow_up": "disabled",
                    "cancelled_follow_up": "disabled",
                    "stealth_reveal": "enabled",
                }
            }
        },
    )
    monkeypatch.setattr(
        configuration,
        "ACTION_CONDITION_GUARDS",
        {
            "wallet_available": {
                "enabled": True,
                "check_follow_up_planning": False,
                "fail_open_on_fetch_error": False,
            },
            "limits": [],
        },
    )

    rest_client = _SpotRestClient()
    registrar = _RootRegistrar()
    response = _service(rest_client, registrar).place_manual_order(
        _manual_command(
            limit_price="100.10",
            operator_intent=(
                "execute_one_approved_intentional_test_profile_spot_fill"
            ),
            post_only=False,
            time_in_force="FILL_OR_KILL",
            approval_snapshot_id="approval-intentional-fill-1",
        )
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "manual_order_semantics"
    assert response.data["blocker"] == (
        "manual_spot_time_in_force_not_supported"
    )
    assert registrar.rows == {}
    assert rest_client.create_calls == []


def test_fok_semantic_rejection_precedes_ordinary_price_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import configuration

    monkeypatch.setattr(
        configuration,
        "PRODUCT_CAPABILITIES",
        {
            "product_id": {
                "BTC-USDC": {
                    "filled_follow_up": "conditional",
                    "partial_fill_follow_up": "disabled",
                    "cancelled_follow_up": "disabled",
                    "stealth_reveal": "disabled",
                }
            }
        },
    )
    monkeypatch.setattr(
        configuration,
        "ACTION_CONDITION_GUARDS",
        {
            "wallet_available": {
                "enabled": True,
                "check_follow_up_planning": False,
                "fail_open_on_fetch_error": False,
            },
            "limits": [],
        },
    )

    rest_client = _SpotRestClient()
    registrar = _RootRegistrar()
    response = _service(rest_client, registrar).place_manual_order(
        _manual_command(
            limit_price="50.00",
            operator_intent=(
                "execute_one_approved_intentional_test_profile_spot_fill"
            ),
            post_only=False,
            time_in_force="FILL_OR_KILL",
            approval_snapshot_id="approval-intentional-fill-1",
        )
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "manual_order_semantics"
    assert response.data["blocker"] == (
        "manual_spot_time_in_force_not_supported"
    )
    assert registrar.rows == {}
    assert rest_client.create_calls == []


def test_intentional_fill_rejects_internal_order_configuration_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import configuration

    monkeypatch.setattr(
        configuration,
        "PRODUCT_CAPABILITIES",
        {
            "product_id": {
                "BTC-USDC": {
                    "filled_follow_up": "conditional",
                    "partial_fill_follow_up": "disabled",
                    "cancelled_follow_up": "disabled",
                    "stealth_reveal": "disabled",
                }
            }
        },
    )
    monkeypatch.setattr(
        configuration,
        "ACTION_CONDITION_GUARDS",
        {
            "wallet_available": {
                "enabled": True,
                "check_follow_up_planning": False,
                "fail_open_on_fetch_error": False,
            },
            "limits": [],
        },
    )

    rest_client = _SpotRestClient()
    registrar = _RootRegistrar()
    response = _service(rest_client, registrar).place_manual_order(
        _manual_command(
            limit_price="100.10",
            operator_intent=(
                "execute_one_approved_intentional_test_profile_spot_fill"
            ),
            post_only=False,
            time_in_force="FILL_OR_KILL",
            approval_snapshot_id="approval-intentional-fill-1",
            order_configuration_override={
                "limit_limit_gtc": {
                    "base_size": "0.02",
                    "limit_price": "100.10",
                    "post_only": False,
                }
            },
        )
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "standing_price_limit"
    assert response.data["standing_price_limit"][
        "intentional_fill_override"
    ]["blocker"] == "intentional_fill_order_configuration_override_forbidden"
    assert registrar.rows == {}
    assert rest_client.create_calls == []


@pytest.mark.parametrize(
    ("approval_snapshot_id", "max_notional", "best_ask", "blocker"),
    [
        (None, "9.99", "100.01", "intentional_fill_approval_missing"),
        (
            "approval-intentional-fill-1",
            "10.00",
            "100.01",
            "intentional_fill_cap_exceeds_approved_maximum",
        ),
        (
            "approval-intentional-fill-1",
            "9.99",
            None,
            "intentional_fill_best_ask_unavailable",
        ),
        (
            "approval-intentional-fill-1",
            "9.99",
            "99.99",
            "intentional_fill_best_ask_invalid",
        ),
    ],
)
def test_fok_semantic_rejection_precedes_obsolete_authority_variants(
    approval_snapshot_id: str | None,
    max_notional: str,
    best_ask: str | None,
    blocker: str,
) -> None:
    rest_client = _SpotRestClient()
    registrar = _RootRegistrar()
    market_reference = {
        "product_id": "BTC-USDC",
        "best_bid": "100.00",
        "best_ask": best_ask,
        "source": "ticker",
        "observed_at": datetime.now(timezone.utc),
    }

    response = _service(
        rest_client,
        registrar,
        market_reference=market_reference,
    ).place_manual_order(
        _manual_command(
            limit_price="100.10",
            operator_intent=(
                "execute_one_approved_intentional_test_profile_spot_fill"
            ),
            post_only=False,
            time_in_force="FILL_OR_KILL",
            approval_snapshot_id=approval_snapshot_id,
            max_submitted_notional_usdc=max_notional,
        )
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "manual_order_semantics"
    assert response.data["blocker"] == (
        "manual_spot_time_in_force_not_supported"
    )
    assert registrar.rows == {}
    assert rest_client.create_calls == []


def test_submit_rejects_stale_ticker_before_root_or_coinbase_boundary() -> None:
    rest_client = _SpotRestClient()
    registrar = _RootRegistrar()
    stale_reference = {
        "best_bid": "100.00",
        "source": "ticker",
        "observed_at": datetime.now(timezone.utc) - timedelta(seconds=31),
    }

    response = _service(
        rest_client,
        registrar,
        market_reference=stale_reference,
    ).place_manual_order(_manual_command(limit_price="50.00"))

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "standing_price_limit"
    assert response.data["standing_price_limit"]["blocker"] == (
        "live_ticker_bid_stale"
    )
    assert rest_client.list_calls == []
    assert rest_client.create_calls == []
    assert registrar.rows == {}


def test_submit_fails_closed_on_malformed_open_order_page() -> None:
    class _MalformedClient(_SpotRestClient):
        def list_orders(self, **kwargs: Any) -> dict[str, Any]:
            self.list_calls.append(dict(kwargs))
            return {"orders": "not-a-list", "has_next": False}

    rest_client = _MalformedClient()
    registrar = _RootRegistrar()

    response = _service(rest_client, registrar).place_manual_order(
        _manual_command()
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "active_order_limit"
    assert response.data["active_order_limit"]["blocker"] == (
        "open_order_read_malformed"
    )
    assert rest_client.create_calls == []
    assert registrar.rows == {}


def test_submit_reads_every_open_order_page_before_admission() -> None:
    class _PagedClient(_SpotRestClient):
        def list_orders(self, **kwargs: Any) -> dict[str, Any]:
            self.list_calls.append(dict(kwargs))
            if kwargs.get("order_status") != ["OPEN"]:
                raise RuntimeError("active orders require the OPEN aggregate query")
            if kwargs.get("cursor") == "page-2":
                return {
                    "orders": [
                        {
                            "client_order_id": "existing-admin-root",
                            "order_id": "exchange-existing-root",
                            "status": "OPEN",
                        }
                    ],
                    "has_next": False,
                }
            return {"orders": [], "has_next": True, "cursor": "page-2"}

    rest_client = _PagedClient()
    registrar = _RootRegistrar()

    response = _service(rest_client, registrar).place_manual_order(
        _manual_command()
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "active_order_limit"
    assert response.data["active_order_limit"]["open_order_count"] == 1
    assert response.data["active_order_limit"]["page_count"] == 2
    assert rest_client.create_calls == []


@pytest.mark.parametrize(
    "active_status",
    ["PENDING", "OPEN", "QUEUED", "CANCEL_QUEUED", "EDIT_QUEUED"],
)
def test_submit_blocks_every_authoritative_active_status_before_create(
    active_status: str,
) -> None:
    class _StatusFilteringClient(_SpotRestClient):
        def list_orders(self, **kwargs: Any) -> dict[str, Any]:
            self.list_calls.append(dict(kwargs))
            if kwargs.get("order_status") != ["OPEN"]:
                raise RuntimeError(
                    "Query request does not support querying active status orders"
                )
            return {
                "orders": [dict(row) for row in self.open_orders],
                "has_next": False,
            }

    rest_client = _StatusFilteringClient()
    rest_client.open_orders = [
        {
            "client_order_id": "existing-active-order",
            "order_id": "exchange-existing-active-order",
            "status": active_status,
        }
    ]
    registrar = _RootRegistrar()

    response = _service(rest_client, registrar).place_manual_order(
        _manual_command()
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "active_order_limit"
    assert response.data["active_order_limit"]["open_order_count"] == 1
    assert rest_client.list_calls == [
        {"limit": 100, "order_status": ["OPEN"], "product_type": "SPOT"}
    ]
    assert rest_client.create_calls == []
    assert registrar.rows == {}


def test_submit_requires_exact_durable_root_registration_evidence() -> None:
    class _MalformedRegistrar(_RootRegistrar):
        def register_manual_spot_root(self, **_kwargs: Any) -> dict[str, Any]:
            return {"registered": False}

    rest_client = _SpotRestClient()
    registrar = _MalformedRegistrar()

    response = _service(rest_client, registrar).place_manual_order(
        _manual_command()
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "order_root_registration"
    assert rest_client.create_calls == []


def test_submit_terminalizes_exact_inserted_root_when_registration_evidence_is_malformed() -> None:
    first_client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    second_client_order_id = "0ba18a83-b30c-4c71-ad01-8f4e439d8f70"

    class _InsertedMalformedOnceRegistrar(_RootRegistrar):
        def __init__(self) -> None:
            super().__init__()
            self.registration_calls = 0

        def register_manual_spot_root(self, **kwargs: Any) -> dict[str, Any]:
            self.registration_calls += 1
            evidence = super().register_manual_spot_root(**kwargs)
            if self.registration_calls == 1:
                return {"registered": False}
            return evidence

    rest_client = _SpotRestClient()
    registrar = _InsertedMalformedOnceRegistrar()
    service = _service(rest_client, registrar)

    first = service.place_manual_order(_manual_command(first_client_order_id))

    assert first.status == AdminApiCommandStatus.REJECTED
    assert first.failure_stage == "order_root_registration"
    assert first.data["submission_attempt"]["rest_invocation_attempted"] is False
    assert first.data["submission_attempt"]["root_recovery"] == {
        "attempted": True,
        "durable_status": "FAILED",
        "recovery_disposition": "known_not_attempted_terminalized_failed",
        "safe_to_submit_another_root": True,
    }
    assert registrar.rows[first_client_order_id]["status"] == "FAILED"
    assert rest_client.create_calls == []

    rest_client.history = [
        {
            "client_order_id": second_client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    second = service.place_manual_order(_manual_command(second_client_order_id))

    assert second.status == AdminApiCommandStatus.ACCEPTED
    assert len(rest_client.create_calls) == 1


def test_submit_terminalizes_exact_inserted_root_when_registrar_fails_after_insert() -> None:
    private_marker = "private-post-insert-registrar-detail"

    class _PostInsertFailureRegistrar(_RootRegistrar):
        def register_manual_spot_root(self, **kwargs: Any) -> dict[str, Any]:
            super().register_manual_spot_root(**kwargs)
            raise RuntimeError(private_marker)

    rest_client = _SpotRestClient()
    registrar = _PostInsertFailureRegistrar()

    response = _service(rest_client, registrar).place_manual_order(
        _manual_command()
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "order_root_registration"
    assert response.data["submission_attempt"]["root_recovery"][
        "recovery_disposition"
    ] == "known_not_attempted_terminalized_failed"
    assert registrar.rows[response.client_order_id]["status"] == "FAILED"
    assert private_marker not in str(response.model_dump(mode="json"))
    assert rest_client.create_calls == []


def test_submit_does_not_terminalize_mismatched_inserted_registration_row() -> None:
    class _MismatchedInsertedRegistrar(_RootRegistrar):
        def register_manual_spot_root(self, **kwargs: Any) -> dict[str, Any]:
            super().register_manual_spot_root(**kwargs)
            self.rows[str(kwargs["client_order_id"])]["product_id"] = "ETH-USDC"
            return {"registered": False}

    rest_client = _SpotRestClient()
    registrar = _MismatchedInsertedRegistrar()

    response = _service(rest_client, registrar).place_manual_order(
        _manual_command()
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "order_root_registration"
    assert response.data["submission_attempt"]["root_recovery"] == {
        "attempted": True,
        "durable_status": "PENDING",
        "recovery_disposition": "owned_root_binding_unproven_quarantined",
        "safe_to_submit_another_root": False,
    }
    assert registrar.rows[response.client_order_id]["status"] == "PENDING"
    assert registrar.status_calls == []
    assert rest_client.create_calls == []


def test_submit_exception_is_unknown_and_durably_blocks_the_next_submit() -> None:
    rest_client = _SpotRestClient()
    private_marker = "private-order-id-and-response-body-must-not-leak"
    rest_client.create_result = TimeoutError(private_marker)
    registrar = _RootRegistrar()
    coordinator = SpotProfileOrderAdmissionCoordinator()
    service = _service(rest_client, registrar, coordinator=coordinator)

    first = service.place_manual_order(_manual_command())
    second = service.place_manual_order(
        _manual_command("0ba18a83-b30c-4c71-ad01-8f4e439d8f70")
    )

    assert first.status == AdminApiCommandStatus.REJECTED
    assert first.failure_stage == "coinbase_submission_unknown"
    assert first.live_coinbase_orders_ran is True
    assert first.data["submission_attempt"]["rest_invocation_attempted"] is True
    assert first.data["submission_attempt"]["outcome"] == "unknown"
    assert private_marker not in first.message
    assert "TimeoutError" in first.message
    assert registrar.status_calls[-1][1] == "SUBMISSION_UNKNOWN"
    assert second.status == AdminApiCommandStatus.REJECTED
    assert second.failure_stage == "submission_uncertainty"
    assert len(rest_client.create_calls) == 1


def test_submit_response_converter_exception_is_unknown_and_value_blind() -> None:
    private_marker = "private-converter-payload-must-not-leak"

    class _ExplodingResponse:
        def to_dict(self) -> dict[str, Any]:
            raise RuntimeError(private_marker)

    rest_client = _SpotRestClient()
    rest_client.create_result = _ExplodingResponse()
    registrar = _RootRegistrar()
    coordinator = SpotProfileOrderAdmissionCoordinator()
    service = _service(rest_client, registrar, coordinator=coordinator)

    first = service.place_manual_order(_manual_command())
    second = service.place_manual_order(
        _manual_command("0ba18a83-b30c-4c71-ad01-8f4e439d8f70")
    )

    assert first.status == AdminApiCommandStatus.REJECTED
    assert first.failure_stage == "coinbase_submission_unknown"
    assert first.live_coinbase_orders_ran is True
    assert first.data["submission_attempt"]["rest_invocation_attempted"] is True
    assert first.data["submission_attempt"]["outcome"] == "unknown"
    assert first.data["submission_attempt"]["response_normalization_failed"] is True
    assert private_marker not in str(first.model_dump(mode="json"))
    assert registrar.status_calls[-1][1] == "SUBMISSION_UNKNOWN"
    assert second.status == AdminApiCommandStatus.REJECTED
    assert second.failure_stage == "submission_uncertainty"
    assert len(rest_client.create_calls) == 1


def test_submit_explicit_rejection_uses_value_blind_diagnostic() -> None:
    private_marker = "private-coinbase-rejection-detail-must-not-leak"
    rest_client = _SpotRestClient()
    rest_client.create_result = {
        "success": False,
        "error_response": {"message": private_marker},
    }
    registrar = _RootRegistrar()

    response = _service(rest_client, registrar).place_manual_order(
        _manual_command()
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "coinbase_rest"
    assert response.live_coinbase_read_ran is False
    assert response.message == (
        "Order creation failed: coinbase_order_explicitly_rejected"
    )
    assert response.data["submission_attempt"]["root_recovery"] == {
        "attempted": True,
        "durable_status": "FAILED",
        "recovery_disposition": "explicit_rejection_terminalized_failed",
        "safe_to_submit_another_root": True,
    }
    assert private_marker not in str(response.model_dump(mode="json"))


def test_submit_explicit_rejection_recovers_from_first_local_status_write_failure() -> None:
    first_client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    second_client_order_id = "0ba18a83-b30c-4c71-ad01-8f4e439d8f70"
    private_marker = "private-local-status-write-detail"

    class _FailFirstStatusWriteRegistrar(_RootRegistrar):
        def __init__(self) -> None:
            super().__init__()
            self.failed_once = False

        def mark_submission_status(
            self,
            *,
            client_order_id: str,
            status: str,
            exchange_order_id: str | None = None,
        ) -> None:
            if status == "FAILED" and not self.failed_once:
                self.failed_once = True
                raise RuntimeError(private_marker)
            super().mark_submission_status(
                client_order_id=client_order_id,
                status=status,
                exchange_order_id=exchange_order_id,
            )

    rest_client = _SpotRestClient()
    rest_client.create_result = {"success": False, "error_response": {}}
    registrar = _FailFirstStatusWriteRegistrar()
    service = _service(rest_client, registrar)

    first = service.place_manual_order(_manual_command(first_client_order_id))

    assert first.status == AdminApiCommandStatus.REJECTED
    assert first.failure_stage == "coinbase_rest"
    assert first.data["submission_attempt"]["outcome"] == "explicitly_rejected"
    assert first.data["submission_attempt"]["root_recovery"] == {
        "attempted": True,
        "durable_status": "FAILED",
        "recovery_disposition": "explicit_rejection_terminalized_failed",
        "safe_to_submit_another_root": True,
    }
    assert registrar.rows[first_client_order_id]["status"] == "FAILED"
    assert private_marker not in str(first.model_dump(mode="json"))

    rest_client.create_result = {
        "success": True,
        "success_response": {"order_id": "exchange-order-2"},
    }
    rest_client.history = [
        {
            "client_order_id": second_client_order_id,
            "order_id": "exchange-order-2",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    second = service.place_manual_order(_manual_command(second_client_order_id))

    assert second.status == AdminApiCommandStatus.ACCEPTED
    assert len(rest_client.create_calls) == 2


def test_submit_explicit_rejection_status_persistence_failure_stays_known_and_quarantined() -> None:
    private_marker = "private-persistent-local-status-write-detail"

    class _AlwaysFailStatusWriteRegistrar(_RootRegistrar):
        def mark_submission_status(
            self,
            *,
            client_order_id: str,
            status: str,
            exchange_order_id: str | None = None,
        ) -> None:
            del client_order_id, status, exchange_order_id
            raise RuntimeError(private_marker)

    rest_client = _SpotRestClient()
    rest_client.create_result = {"success": False, "error_response": {}}
    registrar = _AlwaysFailStatusWriteRegistrar()

    response = _service(rest_client, registrar).place_manual_order(
        _manual_command()
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "coinbase_rest"
    assert response.live_coinbase_orders_ran is True
    assert response.live_exchange_submitted is False
    assert response.data["submission_attempt"]["outcome"] == "explicitly_rejected"
    assert response.data["submission_attempt"]["root_recovery"] == {
        "attempted": True,
        "durable_status": "PENDING",
        "recovery_disposition": "explicit_rejection_terminalization_failed",
        "safe_to_submit_another_root": False,
    }
    assert registrar.rows[response.client_order_id]["status"] == "PENDING"
    assert private_marker not in str(response.model_dump(mode="json"))


def test_submit_requires_explicit_success_and_exchange_order_id() -> None:
    rest_client = _SpotRestClient()
    rest_client.create_result = {"success": True, "success_response": {}}
    registrar = _RootRegistrar()

    response = _service(rest_client, registrar).place_manual_order(
        _manual_command()
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "coinbase_submission_unknown"
    assert response.live_coinbase_orders_ran is True
    assert response.live_coinbase_read_ran is False
    assert response.data["submission_attempt"]["exchange_order_id"] is None
    assert registrar.status_calls[-1][1] == "SUBMISSION_UNKNOWN"


def test_submit_does_not_infer_success_from_nested_payload_without_true_flag() -> None:
    rest_client = _SpotRestClient()
    rest_client.create_result = {
        "success_response": {"order_id": "exchange-order-1"}
    }
    rest_client.history = [
        {
            "client_order_id": "22daf1ea-4c57-4c03-98c5-e74459576228",
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    registrar = _RootRegistrar()

    response = _service(rest_client, registrar).place_manual_order(
        _manual_command()
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "coinbase_submission_unknown"
    assert response.live_coinbase_read_ran is False
    assert response.data["submission_attempt"]["outcome"] == "unknown"
    assert registrar.status_calls[-1][1] == "SUBMISSION_UNKNOWN"


def test_submit_requires_authoritative_exact_identity_readback() -> None:
    rest_client = _SpotRestClient()
    rest_client.history = [
        {
            "client_order_id": "different-client-order-id",
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    registrar = _RootRegistrar()

    response = _service(rest_client, registrar).place_manual_order(
        _manual_command()
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "coinbase_submission_unknown"
    assert response.live_coinbase_read_ran is True
    assert response.data["submission_attempt"]["exchange_order_id"] == (
        "exchange-order-1"
    )
    assert response.data["submission_attempt"][
        "authoritative_readback_confirmed"
    ] is False
    assert registrar.status_calls[-1][1] == "SUBMISSION_UNKNOWN"


def test_submit_rejects_exact_order_readback_from_a_different_product() -> None:
    rest_client = _SpotRestClient()
    rest_client.history = [
        {
            "client_order_id": "22daf1ea-4c57-4c03-98c5-e74459576228",
            "order_id": "exchange-order-1",
            "product_id": "BTC-USD",
            "status": "OPEN",
        }
    ]
    registrar = _RootRegistrar()

    response = _service(rest_client, registrar).place_manual_order(
        _manual_command()
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "coinbase_submission_unknown"
    assert response.data["submission_attempt"][
        "authoritative_readback_confirmed"
    ] is False
    assert rest_client.get_calls == ["exchange-order-1"]
    assert registrar.status_calls[-1][1] == "SUBMISSION_UNKNOWN"


def test_submit_serializes_profile_open_read_through_create_outcome() -> None:
    create_entered = Event()
    release_create = Event()

    class _ConcurrentClient(_SpotRestClient):
        def create_order(self, **kwargs: Any) -> Any:
            self.create_calls.append(dict(kwargs))
            create_entered.set()
            assert release_create.wait(timeout=2)
            row = {
                "client_order_id": kwargs["client_order_id"],
                "order_id": "exchange-concurrent-order",
                "product_id": "BTC-USDC",
                "status": "OPEN",
            }
            self.history = [row]
            self.open_orders = [row]
            return {
                "success": True,
                "success_response": {"order_id": row["order_id"]},
            }

    rest_client = _ConcurrentClient()
    registrar = _RootRegistrar()
    service = _service(
        rest_client,
        registrar,
        coordinator=SpotProfileOrderAdmissionCoordinator(),
    )
    results: list[Any] = []
    results_lock = Lock()

    def run(command: ManualOrderCommand) -> None:
        result = service.place_manual_order(command)
        with results_lock:
            results.append(result)

    first = Thread(target=run, args=(_manual_command(),))
    second = Thread(
        target=run,
        args=(_manual_command("0ba18a83-b30c-4c71-ad01-8f4e439d8f70"),),
    )
    first.start()
    assert create_entered.wait(timeout=2)
    second.start()
    release_create.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert len(rest_client.create_calls) == 1
    assert sorted(result.status.value for result in results) == [
        "accepted",
        "rejected",
    ]
    rejected = next(
        result for result in results if result.status == AdminApiCommandStatus.REJECTED
    )
    assert rejected.failure_stage in {"submission_uncertainty", "active_order_limit"}


def test_proven_create_status_persistence_failure_blocks_after_restart() -> None:
    """The durable PENDING root must quarantine a proven Create across restart."""

    first_client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    second_client_order_id = "0ba18a83-b30c-4c71-ad01-8f4e439d8f70"
    private_marker = "private-root-status-write-detail-must-not-leak"

    class _FailOpenStatusRegistrar(_RootRegistrar):
        def mark_submission_status(
            self,
            *,
            client_order_id: str,
            status: str,
            exchange_order_id: str | None = None,
        ) -> None:
            if status == OrderStatus.OPEN.value:
                raise RuntimeError(private_marker)
            super().mark_submission_status(
                client_order_id=client_order_id,
                status=status,
                exchange_order_id=exchange_order_id,
            )

    rest_client = _SpotRestClient()
    rest_client.history = [
        {
            "client_order_id": first_client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": OrderStatus.OPEN.value,
        }
    ]
    registrar = _FailOpenStatusRegistrar()

    first = _service(
        rest_client,
        registrar,
        coordinator=SpotProfileOrderAdmissionCoordinator(),
    ).place_manual_order(_manual_command(first_client_order_id))
    second = _service(
        rest_client,
        registrar,
        coordinator=SpotProfileOrderAdmissionCoordinator(),
    ).place_manual_order(_manual_command(second_client_order_id))

    assert first.status == AdminApiCommandStatus.REJECTED
    assert first.failure_stage == "order_root_status_persistence"
    assert first.live_exchange_submitted is True
    assert private_marker not in str(first.model_dump(mode="json"))
    assert registrar.rows[first_client_order_id]["status"] == (
        OrderStatus.PENDING.value
    )
    assert second.status == AdminApiCommandStatus.REJECTED
    assert second.failure_stage == "submission_uncertainty"
    assert len(second.data["durable_unresolved_roots"]) == 1
    unresolved = second.data["durable_unresolved_roots"][0]
    assert unresolved["client_order_id"] == first_client_order_id
    assert unresolved["product_id"] == "BTC-USDC"
    assert unresolved["status"] == OrderStatus.PENDING.value
    assert "exchange_order_id" not in unresolved
    assert len(rest_client.create_calls) == 1


def test_submit_audit_failure_reports_proven_live_order_without_accepting() -> None:
    rest_client = _SpotRestClient()
    rest_client.history = [
        {
            "client_order_id": "22daf1ea-4c57-4c03-98c5-e74459576228",
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    registrar = _RootRegistrar()

    response = _service(
        rest_client,
        registrar,
        publisher=_Publisher(persisted=False),
    ).place_manual_order(_manual_command())

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "submission_audit_persistence"
    assert response.coinbase_order_id == "exchange-order-1"
    assert response.live_exchange_submitted is True
    assert response.live_coinbase_orders_ran is True
    assert response.submission_event_recorded is False
    assert response.data["submission_attempt"][
        "authoritative_readback_confirmed"
    ] is True


def test_cancel_reads_exact_active_state_before_exchange_order_id_cancel() -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    events: list[str] = []

    class _CancelClient(_SpotRestClient):
        def cancel_order(
            self,
            requested_client_order_id: str,
            *,
            verified_exchange_order_id: str | None = None,
            return_evidence: bool = False,
        ) -> Any:
            events.append("cancel_exchange")
            assert requested_client_order_id == client_order_id
            assert verified_exchange_order_id == "exchange-order-1"
            self.cancel_exchange_calls.append(verified_exchange_order_id)
            self.history = [
                {
                    "client_order_id": client_order_id,
                    "order_id": verified_exchange_order_id,
                    "product_id": "BTC-USDC",
                    "status": "CANCELLED",
                }
            ]
            if return_evidence:
                return {
                    "outcome": "succeeded",
                    "explicit_rejection": False,
                    "identity_rejection": False,
                    "identity_match": True,
                }
            return True

        def list_orders(self, **kwargs: Any) -> dict[str, Any]:
            events.append("list_orders")
            return super().list_orders(**kwargs)

    rest_client = _CancelClient()
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)

    response = _service(rest_client, registrar).cancel_order_by_client_order_id(
        _cancel_command(client_order_id)
    )

    assert response.status == AdminApiCommandStatus.ACCEPTED
    assert response.live_coinbase_read_ran is True
    assert events[:2] == ["list_orders", "cancel_exchange"]
    assert rest_client.cancel_client_calls == []
    assert rest_client.cancel_exchange_calls == ["exchange-order-1"]
    proof = response.data["cancellation_readback"]
    assert proof["operator_identity_key"] == "client_order_id"
    assert proof["canonical_cancel_attempted"] is True
    assert proof["fallback_attempted"] is False
    assert proof["terminal_status_proven"] is True
    assert proof["authoritative_status"] == "CANCELLED"


def test_hotpoint_cancel_binding_allows_only_exact_linked_child() -> None:
    child_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    parent_id = "11111111-1111-4111-8111-111111111111"

    class _CancelClient(_SpotRestClient):
        def cancel_order(
            self,
            requested_client_order_id: str,
            *,
            verified_exchange_order_id: str | None = None,
            return_evidence: bool = False,
        ) -> Any:
            assert requested_client_order_id == child_id
            assert verified_exchange_order_id == "exchange-order-hotpoint"
            self.history = [
                {
                    "client_order_id": child_id,
                    "order_id": verified_exchange_order_id,
                    "product_id": "BTC-USDC",
                    "status": "CANCELLED",
                }
            ]
            return {
                "outcome": "succeeded",
                "explicit_rejection": False,
                "identity_rejection": False,
                "identity_match": True,
            }

    rest_client = _CancelClient()
    rest_client.history = [
        {
            "client_order_id": child_id,
            "order_id": "exchange-order-hotpoint",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    registrar = _RootRegistrar()
    _registered_root(
        registrar,
        child_id,
        provenance="ADMIN_HOTPOINT_CHILD",
        parent_order_id=parent_id,
    )
    registrar.rows[child_id]["exchange_order_id"] = "exchange-order-hotpoint"
    command = _cancel_command(child_id).model_copy(
        update={
            "hotpoint_goal_id": (
                "operator_hotpoint_control_and_single_placement_v1"
            ),
            "hotpoint_parent_client_order_id": parent_id,
            "hotpoint_plan_sha256": "a" * 64,
            "hotpoint_portfolio_id": TEST_PORTFOLIO_ID,
        }
    )

    response = _service(
        rest_client,
        registrar,
    ).cancel_order_by_client_order_id(command)

    assert response.status == AdminApiCommandStatus.ACCEPTED
    assert response.client_order_id == child_id
    assert response.live_exchange_submitted is True
    assert registrar.rows[child_id]["status"] == "CANCELLED"


def test_cancel_uses_authoritative_exchange_id_exactly_once_without_fallback() -> None:
    """The operator client ID selects the order; only its proven exchange ID mutates."""

    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"

    class _ExactExchangeCancelClient(_SpotRestClient):
        def cancel_order_by_exchange_order_id(
            self,
            order_id: str,
            *,
            return_evidence: bool = False,
        ) -> Any:
            raise AssertionError(f"direct exchange-id helper is forbidden: {order_id}")

        def cancel_order(
            self,
            requested: str,
            *,
            verified_exchange_order_id: str | None = None,
            return_evidence: bool = False,
        ) -> Any:
            assert requested == client_order_id
            assert verified_exchange_order_id == "exchange-order-1"
            self.cancel_exchange_calls.append(verified_exchange_order_id)
            self.history[0]["status"] = "CANCELLED"
            assert return_evidence is True
            return {
                "outcome": "succeeded",
                "explicit_rejection": False,
                "identity_rejection": False,
                "identity_match": True,
                "submitted_identity_key": "exchange_order_id",
            }

    rest_client = _ExactExchangeCancelClient()
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)

    response = _service(rest_client, registrar).cancel_order_by_client_order_id(
        _cancel_command(client_order_id)
    )

    assert response.status == AdminApiCommandStatus.ACCEPTED
    assert rest_client.cancel_client_calls == []
    assert rest_client.cancel_exchange_calls == ["exchange-order-1"]
    proof = response.data["cancellation_readback"]
    assert proof["canonical_cancel_attempted"] is True
    assert proof["canonical_cancel_identity"] == "exchange_order_id"
    assert proof["fallback_attempted"] is False
    assert proof["terminal_status_proven"] is True


def test_cancel_rejects_missing_live_acknowledgement_before_any_coinbase_read() -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)

    response = _service(rest_client, registrar).cancel_order_by_client_order_id(
        _cancel_command(
            client_order_id,
            manual_live_acknowledgement=False,
        )
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "manual_live_acknowledgement"
    assert response.live_exchange_submitted is False
    assert response.live_coinbase_orders_ran is False
    assert rest_client.api_key_permission_calls == 0
    assert rest_client.portfolio_calls == 0
    assert rest_client.list_calls == []
    assert rest_client.cancel_client_calls == []
    assert rest_client.cancel_exchange_calls == []
    assert registrar.status_calls == []


def test_cancel_uses_only_exact_exchange_id_after_preflight() -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]

    def exact_cancel(
        requested_client_order_id: str,
        *,
        verified_exchange_order_id: str | None = None,
        return_evidence: bool = False,
    ) -> Any:
        assert requested_client_order_id == client_order_id
        assert verified_exchange_order_id == "exchange-order-1"
        rest_client.cancel_exchange_calls.append(verified_exchange_order_id)
        rest_client.history[0]["status"] = "CANCELLED"
        if return_evidence:
            return {
                "outcome": "succeeded",
                "explicit_rejection": False,
                "identity_rejection": False,
                "identity_match": True,
            }
        return True

    rest_client.cancel_order = exact_cancel  # type: ignore[method-assign]
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)

    response = _service(rest_client, registrar).cancel_order_by_client_order_id(
        _cancel_command(client_order_id)
    )

    assert response.status == AdminApiCommandStatus.ACCEPTED
    assert rest_client.cancel_client_calls == []
    assert rest_client.cancel_exchange_calls == ["exchange-order-1"]
    proof = response.data["cancellation_readback"]
    assert proof["canonical_cancel_accepted"] is True
    assert proof["canonical_cancel_explicitly_rejected"] is False
    assert proof["fallback_attempted"] is False
    assert proof["fallback_exchange_order_id"] is None
    assert proof["exchange_order_id_evidence_only"] is True
    assert proof["terminal_status_proven"] is True


@pytest.mark.parametrize(
    ("exact_cancel_result", "history", "expected_stage", "expected_live_call"),
    [
        (
            RuntimeError("transport uncertainty"),
            [
                {
                    "client_order_id": "22daf1ea-4c57-4c03-98c5-e74459576228",
                    "order_id": "exchange-order-1",
                    "product_id": "BTC-USDC",
                    "status": "OPEN",
                }
            ],
            "cancellation_unknown",
            True,
        ),
        (
            False,
            [
                {
                    "client_order_id": "22daf1ea-4c57-4c03-98c5-e74459576228",
                    "order_id": "",
                    "product_id": "BTC-USDC",
                    "status": "OPEN",
                }
            ],
            "cancellation_preflight_readback",
            False,
        ),
    ],
)
def test_cancel_unknown_or_missing_exchange_id_never_uses_fallback(
    exact_cancel_result: Any,
    history: list[dict[str, Any]],
    expected_stage: str,
    expected_live_call: bool,
) -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()
    rest_client.cancel_exchange_result = exact_cancel_result
    rest_client.history = history
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)

    response = _service(rest_client, registrar).cancel_order_by_client_order_id(
        _cancel_command(client_order_id)
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == expected_stage
    assert response.live_coinbase_orders_ran is expected_live_call
    assert rest_client.cancel_exchange_calls == (
        ["exchange-order-1"] if expected_live_call else []
    )
    assert rest_client.cancel_client_calls == []
    assert all(status != "CANCELLED" for _coid, status in registrar.status_calls)


def test_cancel_unknown_is_durably_quarantined_across_restart_and_new_key() -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()
    rest_client.cancel_exchange_result = RuntimeError("transport uncertainty")
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)

    first = _service(rest_client, registrar).cancel_order_by_client_order_id(
        _cancel_command(client_order_id, idempotency_key="cancel-attempt-one")
    )
    rest_client.cancel_exchange_result = True
    restarted = _service(rest_client, registrar)
    second = restarted.cancel_order_by_client_order_id(
        _cancel_command(client_order_id, idempotency_key="cancel-attempt-two")
    )

    assert first.failure_stage == "cancellation_unknown"
    assert registrar.rows[client_order_id]["status"] == (
        OrderStatus.CANCELLATION_UNKNOWN.value
    )
    assert registrar.status_calls[-1] == (
        client_order_id,
        OrderStatus.CANCELLATION_UNKNOWN.value,
    )
    assert second.status == AdminApiCommandStatus.REJECTED
    assert second.failure_stage == "cancellation_uncertainty"
    assert second.live_coinbase_read_ran is False
    assert second.live_coinbase_orders_ran is False
    assert rest_client.cancel_client_calls == []
    assert rest_client.cancel_exchange_calls == ["exchange-order-1"]
    assert len(rest_client.list_calls) == 1
    assert rest_client.api_key_permission_calls == 1
    assert rest_client.portfolio_calls == 1


def test_cancel_revalidates_unknown_local_state_after_profile_claim() -> None:
    """A waiter must not use the OPEN snapshot read before profile locking."""

    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)

    class _PriorWorkerCompletedUnknownCoordinator(
        SpotProfileOrderAdmissionCoordinator
    ):
        @contextmanager
        def claim(self, retail_portfolio_id: str):
            registrar.mark_submission_status(
                client_order_id=client_order_id,
                status=OrderStatus.CANCELLATION_UNKNOWN.value,
                exchange_order_id="exchange-order-1",
            )
            with super().claim(retail_portfolio_id):
                yield

    response = _service(
        rest_client,
        registrar,
        coordinator=_PriorWorkerCompletedUnknownCoordinator(),
    ).cancel_order_by_client_order_id(
        _cancel_command(client_order_id, idempotency_key="waiting-command-key")
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "cancellation_uncertainty"
    assert response.live_coinbase_read_ran is False
    assert response.live_coinbase_orders_ran is False
    assert rest_client.list_calls == []
    assert rest_client.cancel_client_calls == []
    assert rest_client.cancel_exchange_calls == []


def test_cancel_persists_durable_unknown_claim_before_coinbase_boundary() -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"

    class _SyntheticProcessLoss(BaseException):
        pass

    rest_client = _SpotRestClient()
    rest_client.cancel_exchange_result = _SyntheticProcessLoss()
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)

    with pytest.raises(_SyntheticProcessLoss):
        _service(rest_client, registrar).cancel_order_by_client_order_id(
            _cancel_command(client_order_id, idempotency_key="cancel-process-loss")
        )

    assert registrar.rows[client_order_id]["status"] == (
        OrderStatus.CANCELLATION_UNKNOWN.value
    )
    assert registrar.status_calls[-1] == (
        client_order_id,
        OrderStatus.CANCELLATION_UNKNOWN.value,
    )
    assert rest_client.cancel_client_calls == []
    assert rest_client.cancel_exchange_calls == ["exchange-order-1"]

    rest_client.cancel_exchange_result = True
    restarted = _service(rest_client, registrar)
    blocked = restarted.cancel_order_by_client_order_id(
        _cancel_command(client_order_id, idempotency_key="cancel-after-process-loss")
    )

    assert blocked.status == AdminApiCommandStatus.REJECTED
    assert blocked.failure_stage == "cancellation_uncertainty"
    assert blocked.live_coinbase_read_ran is False
    assert blocked.live_coinbase_orders_ran is False
    assert rest_client.cancel_client_calls == []
    assert rest_client.cancel_exchange_calls == ["exchange-order-1"]


def test_cancel_does_not_cross_coinbase_boundary_without_durable_claim() -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"

    class _ClaimWriteFailingRegistrar(_RootRegistrar):
        def mark_submission_status(
            self,
            *,
            client_order_id: str,
            status: str,
            exchange_order_id: str | None = None,
        ) -> None:
            if status == OrderStatus.CANCELLATION_UNKNOWN.value:
                raise RuntimeError("synthetic private persistence detail")
            super().mark_submission_status(
                client_order_id=client_order_id,
                status=status,
                exchange_order_id=exchange_order_id,
            )

    rest_client = _SpotRestClient()
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    registrar = _ClaimWriteFailingRegistrar()
    _registered_root(registrar, client_order_id)

    response = _service(rest_client, registrar).cancel_order_by_client_order_id(
        _cancel_command(client_order_id)
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "cancellation_claim_persistence"
    assert response.live_exchange_submitted is False
    assert response.live_coinbase_orders_ran is False
    assert response.data["cancellation_readback"][
        "durable_cancel_claim_persisted"
    ] is False
    assert "synthetic private persistence detail" not in repr(response)
    assert registrar.rows[client_order_id]["status"] == "OPEN"
    assert rest_client.cancel_client_calls == []
    assert rest_client.cancel_exchange_calls == []


def test_goal12_cancel_revalidates_claimed_exchange_hash_before_sdk() -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)
    boundary_events: list[str] = []

    response = _service(
        rest_client,
        registrar,
    ).cancel_order_by_client_order_id(
        _cancel_command(client_order_id),
        expected_goal12_exchange_order_id_sha256=hashlib.sha256(
            b"different-exchange-order"
        ).hexdigest(),
        before_cancel_sdk_call=lambda: boundary_events.append("entered"),
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "goal12_exchange_identity_binding"
    assert response.live_coinbase_orders_ran is False
    assert registrar.rows[client_order_id]["status"] == "OPEN"
    assert rest_client.cancel_client_calls == []
    assert rest_client.cancel_exchange_calls == []
    assert boundary_events == []


def test_goal12_cancel_revalidates_current_configured_portfolio_hash() -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)

    response = _service(
        rest_client,
        registrar,
    ).cancel_order_by_client_order_id(
        _cancel_command(client_order_id),
        expected_goal12_portfolio_id_sha256=hashlib.sha256(
            b"different-test-portfolio"
        ).hexdigest(),
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "goal12_portfolio_binding"
    assert response.live_coinbase_read_ran is False
    assert response.live_coinbase_orders_ran is False
    assert rest_client.api_key_permission_calls == 0
    assert rest_client.portfolio_calls == 0
    assert rest_client.list_calls == []
    assert rest_client.cancel_exchange_calls == []


def test_goal12_cancel_callback_failure_releases_local_preboundary_claim() -> None:
    from core.exceptions import CoinbasePreSdkCallbackError

    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"

    class _PreBoundaryFailureClient(_SpotRestClient):
        def cancel_order(
            self,
            requested_client_order_id: str,
            *,
            verified_exchange_order_id: str | None = None,
            return_evidence: bool = False,
            before_sdk_call=None,
        ) -> Any:
            assert requested_client_order_id == client_order_id
            assert verified_exchange_order_id == "exchange-order-1"
            assert return_evidence is True
            try:
                assert before_sdk_call is not None
                before_sdk_call()
            except Exception:
                raise CoinbasePreSdkCallbackError(
                    "coinbase_pre_sdk_callback_failed"
                ) from None
            raise AssertionError("Coinbase SDK boundary must remain unentered")

    rest_client = _PreBoundaryFailureClient()
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)
    coordinator = SpotProfileOrderAdmissionCoordinator()

    response = _service(
        rest_client,
        registrar,
        coordinator=coordinator,
    ).cancel_order_by_client_order_id(
        _cancel_command(client_order_id),
        before_cancel_sdk_call=lambda: (_ for _ in ()).throw(
            ValueError("synthetic_goal12_mark_failed")
        ),
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "cancellation_pre_sdk_callback"
    assert response.live_exchange_submitted is False
    assert response.live_coinbase_orders_ran is False
    assert registrar.rows[client_order_id]["status"] == "OPEN"
    assert coordinator.uncertainty_snapshot(TEST_PORTFOLIO_ID) == []
    assert rest_client.cancel_exchange_calls == []


@pytest.mark.parametrize("registrar_mode", ["getter", "missing_read", "read_error"])
def test_cancel_ownership_read_degradation_is_typed_and_call_free(
    registrar_mode: str,
) -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()

    if registrar_mode == "getter":
        def registrar_getter() -> Any:
            raise RuntimeError("synthetic private registrar detail")
    elif registrar_mode == "missing_read":
        registrar_getter = lambda: object()
    else:
        class _ReadFailingRegistrar(_RootRegistrar):
            def read_registered_order(
                self,
                _client_order_id: str,
            ) -> dict[str, Any] | None:
                raise RuntimeError("synthetic private ownership detail")

        registrar_getter = lambda: _ReadFailingRegistrar()

    service = AdminApiCommandService(
        AdminApiCommandDependencies(
            rest_client=rest_client,
            rest_client_available=True,
            live_runtime_enabled=True,
            command_runtime_ready=True,
            spot_portfolio_id=TEST_PORTFOLIO_ID,
            spot_portfolio_label="Test",
            order_root_registrar_getter=registrar_getter,
            runtime_controller_factory=lambda: _RuntimeController(),
            spot_order_admission_coordinator=SpotProfileOrderAdmissionCoordinator(),
        )
    )

    response = service.cancel_order_by_client_order_id(
        _cancel_command(client_order_id)
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "order_ownership"
    assert response.live_exchange_submitted is False
    assert response.live_coinbase_read_ran is False
    assert response.live_coinbase_orders_ran is False
    assert "synthetic private" not in response.message
    assert response.data["portfolio_scope"]["status"] == "not_checked"
    assert response.data["portfolio_scope"]["profile_alias"] == "Test"
    assert response.data["portfolio_scope"]["portfolio_id"] is None
    assert rest_client.api_key_permission_calls == 0
    assert rest_client.portfolio_calls == 0
    assert rest_client.cancel_client_calls == []


def test_cancel_never_infers_cancelled_from_authoritative_absence() -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()
    rest_client.cancel_client_result = True
    rest_client.history = []
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)

    response = _service(rest_client, registrar).cancel_order_by_client_order_id(
        _cancel_command(client_order_id)
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "cancellation_preflight_readback"
    assert response.live_coinbase_orders_ran is False
    assert response.data["cancellation_readback"]["confirmed_absent"] is True
    assert response.data["cancellation_readback"]["terminal_status_proven"] is False
    assert all(status != "CANCELLED" for _coid, status in registrar.status_calls)


@pytest.mark.parametrize("terminal_status", ["FILLED", "CANCELLED", "EXPIRED", "FAILED"])
def test_cancel_terminal_preflight_reconciles_without_exchange_mutation(
    terminal_status: str,
) -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()
    rest_client.cancel_client_result = False
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": terminal_status,
        }
    ]
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)

    response = _service(rest_client, registrar).cancel_order_by_client_order_id(
        _cancel_command(client_order_id)
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "cancellation_preflight_terminal_status"
    assert response.live_exchange_submitted is False
    assert response.live_coinbase_orders_ran is False
    assert response.live_coinbase_read_ran is True
    assert rest_client.cancel_client_calls == []
    assert rest_client.cancel_exchange_calls == []
    assert registrar.status_calls[-1] == (client_order_id, terminal_status)
    assert response.data["cancellation_readback"]["authoritative_status"] == terminal_status
    assert response.data["cancellation_readback"]["pre_cancel_reconciled"] is True


def test_cancel_preflight_cross_binds_stored_exchange_identity() -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "different-exchange-order",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)
    registrar.rows[client_order_id]["exchange_order_id"] = "stored-exchange-order"

    response = _service(rest_client, registrar).cancel_order_by_client_order_id(
        _cancel_command(client_order_id)
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "cancellation_preflight_readback"
    assert rest_client.get_calls == ["stored-exchange-order"]
    assert rest_client.cancel_client_calls == []
    assert rest_client.cancel_exchange_calls == []
    assert registrar.status_calls == []


@pytest.mark.parametrize("status", ["UNKNOWN", "", "CANCEL_QUEUED", "EDIT_QUEUED"])
def test_cancel_requires_a_recognized_exact_active_preflight_status(status: str) -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": status,
        }
    ]
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)

    response = _service(rest_client, registrar).cancel_order_by_client_order_id(
        _cancel_command(client_order_id)
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "cancellation_preflight_readback"
    assert response.live_exchange_submitted is False
    assert response.live_coinbase_orders_ran is False
    assert response.live_coinbase_read_ran is True
    assert rest_client.cancel_client_calls == []
    assert rest_client.cancel_exchange_calls == []


def test_cancel_fails_closed_on_incomplete_pagination_without_fallback() -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"

    class _MalformedPaginationClient(_SpotRestClient):
        def list_orders(self, **kwargs: Any) -> dict[str, Any]:
            return {"orders": [], "has_next": True, "cursor": ""}

    rest_client = _MalformedPaginationClient()
    rest_client.cancel_client_result = False
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)

    response = _service(rest_client, registrar).cancel_order_by_client_order_id(
        _cancel_command(client_order_id)
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "cancellation_preflight_readback"
    assert response.live_coinbase_orders_ran is False
    assert rest_client.cancel_exchange_calls == []
    assert all(status != "CANCELLED" for _coid, status in registrar.status_calls)


@pytest.mark.parametrize(
    ("provenance", "parent_order_id"),
    [
        ("EXTERNAL_WS_OBSERVED", None),
        ("ADMIN_MANUAL_ROOT", "22daf1ea-4c57-4c03-98c5-e74459576228"),
        ("", None),
    ],
)
def test_generic_cancel_rejects_external_child_and_legacy_rows(
    provenance: str,
    parent_order_id: str | None,
) -> None:
    client_order_id = "0ba18a83-b30c-4c71-ad01-8f4e439d8f70"
    rest_client = _SpotRestClient()
    registrar = _RootRegistrar()
    _registered_root(
        registrar,
        client_order_id,
        provenance=provenance,
        parent_order_id=parent_order_id,
    )

    response = _service(rest_client, registrar).cancel_order_by_client_order_id(
        _cancel_command(client_order_id)
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "order_ownership"
    assert rest_client.cancel_client_calls == []
    assert rest_client.cancel_exchange_calls == []
    assert rest_client.list_calls == []
