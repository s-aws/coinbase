from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread
from types import SimpleNamespace
from typing import Any

import pytest

from application.admin_api.command_service import (
    AdminApiCommandDependencies,
    AdminApiCommandService,
    SpotProfileOrderAdmissionCoordinator,
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


@pytest.fixture(autouse=True)
def _disable_unrelated_action_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    import configuration

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

    def register_manual_spot_root(self, **kwargs: Any) -> dict[str, Any]:
        row = {
            **kwargs,
            "parent_order_id": None,
            "ownership_provenance": "ADMIN_MANUAL_ROOT",
            "status": "PENDING",
        }
        self.rows[str(kwargs["client_order_id"])] = row
        return {
            "registered": True,
            "client_order_id": kwargs["client_order_id"],
            "retail_portfolio_id": kwargs["retail_portfolio_id"],
            "ownership_provenance": "ADMIN_MANUAL_ROOT",
        }

    def mark_submission_status(self, *, client_order_id: str, status: str) -> None:
        self.status_calls.append((client_order_id, status))
        self.rows[client_order_id]["status"] = status

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


class _SpotRestClient:
    def __init__(self) -> None:
        self.open_orders: list[dict[str, Any]] = []
        self.history: list[dict[str, Any]] = []
        self.api_key_permission_calls = 0
        self.portfolio_calls = 0
        self.create_calls: list[dict[str, Any]] = []
        self.get_calls: list[str] = []
        self.list_calls: list[dict[str, Any]] = []
        self.cancel_client_calls: list[str] = []
        self.cancel_exchange_calls: list[str] = []
        self.create_result: Any = {
            "success": True,
            "success_response": {"order_id": "exchange-order-1"},
        }
        self.cancel_client_result: Any = True
        self.cancel_exchange_result: Any = True

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

    def create_order(self, **kwargs: Any) -> Any:
        self.create_calls.append(dict(kwargs))
        if isinstance(self.create_result, BaseException):
            raise self.create_result
        return self.create_result

    def cancel_order(self, client_order_id: str) -> Any:
        self.cancel_client_calls.append(client_order_id)
        if isinstance(self.cancel_client_result, BaseException):
            raise self.cancel_client_result
        return self.cancel_client_result

    def cancel_order_by_exchange_order_id(self, order_id: str) -> Any:
        self.cancel_exchange_calls.append(order_id)
        if isinstance(self.cancel_exchange_result, BaseException):
            raise self.cancel_exchange_result
        return self.cancel_exchange_result


def _manual_command(
    client_order_id: str = "22daf1ea-4c57-4c03-98c5-e74459576228",
    *,
    limit_price: str = "50.00",
) -> ManualOrderCommand:
    return ManualOrderCommand(
        envelope=AdminApiCommandEnvelope(
            idempotency_key=f"idem-{client_order_id}",
            correlation_id=f"corr-{client_order_id}",
            operator_intent="bounded_spot_test_order",
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
                "base_size": "0.02",
                "limit_price": limit_price,
                "post_only": True,
                "manual_live_acknowledgement": True,
            }
        ),
        admin_cap_guard_decision_id="cap-spot-test-profile",
        admin_max_submitted_notional_usdc="9.99",
        allow_live_execution=True,
    )


def _cancel_command(client_order_id: str) -> CancelOrderCommand:
    return CancelOrderCommand(
        envelope=AdminApiCommandEnvelope(
            idempotency_key=f"idem-cancel-{client_order_id}",
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
            manual_live_acknowledgement=True,
        ),
        allow_live_execution=True,
    )


def _service(
    rest_client: _SpotRestClient,
    registrar: _RootRegistrar,
    *,
    publisher: _Publisher | None = None,
    coordinator: SpotProfileOrderAdmissionCoordinator | None = None,
    market_reference: dict[str, Any] | None = None,
) -> AdminApiCommandService:
    publisher = publisher or _Publisher()
    resolved_market_reference = market_reference or {
        "best_bid": "100.00",
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


def test_submit_exception_is_unknown_and_durably_blocks_the_next_submit() -> None:
    rest_client = _SpotRestClient()
    rest_client.create_result = TimeoutError("synthetic timeout after write")
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
    assert registrar.status_calls[-1][1] == "SUBMISSION_UNKNOWN"
    assert second.status == AdminApiCommandStatus.REJECTED
    assert second.failure_stage == "submission_uncertainty"
    assert len(rest_client.create_calls) == 1


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


def test_cancel_calls_client_order_id_first_and_requires_cancelled_terminal_proof() -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    events: list[str] = []

    class _CancelClient(_SpotRestClient):
        def cancel_order(self, requested: str) -> bool:
            events.append("cancel_client")
            self.cancel_client_calls.append(requested)
            self.history = [
                {
                    "client_order_id": requested,
                    "order_id": "exchange-order-1",
                    "product_id": "BTC-USDC",
                    "status": "CANCELLED",
                }
            ]
            return True

        def list_orders(self, **kwargs: Any) -> dict[str, Any]:
            events.append("list_orders")
            return super().list_orders(**kwargs)

    rest_client = _CancelClient()
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)

    response = _service(rest_client, registrar).cancel_order_by_client_order_id(
        _cancel_command(client_order_id)
    )

    assert response.status == AdminApiCommandStatus.ACCEPTED
    assert events[0] == "cancel_client"
    assert rest_client.cancel_exchange_calls == []
    proof = response.data["cancellation_readback"]
    assert proof["operator_identity_key"] == "client_order_id"
    assert proof["canonical_cancel_attempted"] is True
    assert proof["fallback_attempted"] is False
    assert proof["terminal_status_proven"] is True
    assert proof["authoritative_status"] == "CANCELLED"


def test_cancel_falls_back_only_after_explicit_client_id_rejection_and_readback() -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()
    rest_client.cancel_client_result = False
    rest_client.history = [
        {
            "client_order_id": client_order_id,
            "order_id": "exchange-order-1",
            "product_id": "BTC-USDC",
            "status": "OPEN",
        }
    ]

    def fallback(order_id: str) -> bool:
        rest_client.cancel_exchange_calls.append(order_id)
        rest_client.history[0]["status"] = "CANCELLED"
        return True

    rest_client.cancel_order_by_exchange_order_id = fallback  # type: ignore[method-assign]
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)

    response = _service(rest_client, registrar).cancel_order_by_client_order_id(
        _cancel_command(client_order_id)
    )

    assert response.status == AdminApiCommandStatus.ACCEPTED
    assert rest_client.cancel_client_calls == [client_order_id]
    assert rest_client.cancel_exchange_calls == ["exchange-order-1"]
    proof = response.data["cancellation_readback"]
    assert proof["canonical_cancel_explicitly_rejected"] is True
    assert proof["fallback_attempted"] is True
    assert proof["fallback_exchange_order_id"] == "exchange-order-1"
    assert proof["exchange_order_id_evidence_only"] is True
    assert proof["terminal_status_proven"] is True


@pytest.mark.parametrize(
    ("canonical_result", "history", "expected_stage"),
    [
        (
            RuntimeError("transport uncertainty"),
            [],
            "cancellation_unknown",
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
            "cancellation_readback",
        ),
    ],
)
def test_cancel_unknown_or_missing_exchange_id_never_uses_fallback(
    canonical_result: Any,
    history: list[dict[str, Any]],
    expected_stage: str,
) -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()
    rest_client.cancel_client_result = canonical_result
    rest_client.history = history
    registrar = _RootRegistrar()
    _registered_root(registrar, client_order_id)

    response = _service(rest_client, registrar).cancel_order_by_client_order_id(
        _cancel_command(client_order_id)
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == expected_stage
    assert response.live_coinbase_orders_ran is True
    assert rest_client.cancel_exchange_calls == []
    assert all(status != "CANCELLED" for _coid, status in registrar.status_calls)


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
    assert response.failure_stage == "cancellation_readback"
    assert response.data["cancellation_readback"]["confirmed_absent"] is True
    assert response.data["cancellation_readback"]["terminal_status_proven"] is False
    assert all(status != "CANCELLED" for _coid, status in registrar.status_calls)


def test_cancel_filled_terminal_proof_does_not_fallback_or_claim_cancelled() -> None:
    client_order_id = "22daf1ea-4c57-4c03-98c5-e74459576228"
    rest_client = _SpotRestClient()
    rest_client.cancel_client_result = False
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

    response = _service(rest_client, registrar).cancel_order_by_client_order_id(
        _cancel_command(client_order_id)
    )

    assert response.status == AdminApiCommandStatus.REJECTED
    assert response.failure_stage == "cancellation_terminal_status"
    assert rest_client.cancel_exchange_calls == []
    assert registrar.status_calls[-1] == (client_order_id, "FILLED")
    assert response.data["cancellation_readback"]["authoritative_status"] == (
        "FILLED"
    )


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
    assert response.failure_stage == "cancellation_readback"
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
