from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from application.admin_api.operator_futures_order_operations import (
    FuturesOrderCatalogReader,
)
from application.admin_api.operator_futures_order_operations_service import (
    FuturesOrderOperationsRequestContext,
    OperatorFuturesOrderOperationsService,
)
from application.admin_api.operator_futures_order_operations_runtime import (
    AdminApiFuturesOrderOperationsExchangeExecutor,
)


CLIENT_ORDER_ID = "operator-futures-order-001"
EXCHANGE_ORDER_ID = "private-exchange-order-001"


class _RestClient:
    def __init__(self) -> None:
        self.can_trade = True
        self.pages = {
            None: {
                "orders": [
                    {
                        "order_id": EXCHANGE_ORDER_ID,
                        "client_order_id": CLIENT_ORDER_ID,
                        "product_id": "AVP-20DEC30-CDE",
                        "side": "BUY",
                        "status": "OPEN",
                        "order_type": "LIMIT",
                        "time_in_force": "GOOD_UNTIL_CANCELLED",
                        "created_time": "2026-07-25T08:00:00Z",
                        "last_update_time": "2026-07-25T08:00:01Z",
                        "filled_size": "0",
                    }
                ],
                "has_next": True,
                "cursor": "private-cursor-1",
            },
            "private-cursor-1": {
                "orders": [
                    {
                        "order_id": "private-exchange-order-002",
                        "client_order_id": "operator-futures-order-002",
                        "product_id": "AVP-20DEC30-CDE",
                        "side": "SELL",
                        "status": "FILLED",
                        "order_type": "LIMIT",
                        "time_in_force": "GOOD_UNTIL_CANCELLED",
                        "created_time": "2026-07-25T07:00:00Z",
                        "last_update_time": "2026-07-25T07:01:00Z",
                        "filled_size": "1",
                    }
                ],
                "has_next": False,
                "cursor": "",
            },
        }
        self.list_calls: list[dict[str, object]] = []
        self.cancel_calls: list[dict[str, object]] = []

    def get_api_key_permissions(self):
        return {
            "portfolio_uuid": "11111111-1111-4111-8111-111111111111",
            "portfolio_type": "DEFAULT",
            "can_view": True,
            "can_trade": self.can_trade,
        }

    def get_futures_preview_eligibility_portfolios(self):
        return [
            {
                "uuid": "11111111-1111-4111-8111-111111111111",
                "name": "Default",
                "type": "DEFAULT",
            }
        ]

    def list_orders(self, **kwargs):
        callback = kwargs.pop("before_sdk_call")
        callback()
        self.list_calls.append(dict(kwargs))
        return deepcopy(self.pages[kwargs.get("cursor")])

    def cancel_futures_order(self, **kwargs):
        callback = kwargs.pop("before_sdk_call")
        callback()
        self.cancel_calls.append(dict(kwargs))
        return SimpleNamespace(
            results=[
                SimpleNamespace(
                    success=True,
                    order_id=kwargs["exchange_order_id"],
                    failure_reason="",
                )
            ]
        )


def test_catalog_reader_binds_default_profile_and_paginates_without_raw_ids():
    rest = _RestClient()
    categories: list[str] = []
    page_claims: list[tuple[int, str | None]] = []
    reader = FuturesOrderCatalogReader(
        rest_client=rest,
        now=lambda: datetime(2026, 7, 25, 8, 1, tzinfo=timezone.utc),
    )

    result = reader.run(
        before_category=categories.append,
        before_page=lambda ordinal, cursor_hash: page_claims.append(
            (ordinal, cursor_hash)
        ),
    )

    assert result.outcome == "SUCCEEDED"
    assert result.diagnostic_code == "operator_futures_orders_catalog_refreshed"
    assert categories == [
        "api_key_permissions",
        "portfolio_catalog",
        "futures_order_catalog",
    ]
    assert len(page_claims) == 2
    assert page_claims[0] == (1, None)
    assert page_claims[1][0] == 2
    assert len(page_claims[1][1] or "") == 64
    assert [order.client_order_id for order in result.orders] == [
        CLIENT_ORDER_ID,
        "operator-futures-order-002",
    ]
    assert result.orders[0].exchange_order_id_sha256
    assert EXCHANGE_ORDER_ID not in repr(result.public_evidence)
    assert "private-cursor-1" not in repr(result.public_evidence)
    assert [call["product_type"] for call in rest.list_calls] == [
        "FUTURE",
        "FUTURE",
    ]
    assert [call["limit"] for call in rest.list_calls] == [100, 100]
    assert [call["retail_portfolio_id"] for call in rest.list_calls] == [
        None,
        None,
    ]


def test_catalog_reader_fails_closed_on_duplicate_client_identity():
    rest = _RestClient()
    rest.pages["private-cursor-1"]["orders"][0]["client_order_id"] = (
        CLIENT_ORDER_ID
    )
    reader = FuturesOrderCatalogReader(rest_client=rest)

    result = reader.run(
        before_category=lambda _category: None,
        before_page=lambda _ordinal, _cursor_hash: None,
    )

    assert result.outcome == "UNKNOWN"
    assert (
        result.diagnostic_code
        == "operator_futures_orders_catalog_identity_ambiguous"
    )
    assert result.orders == ()
    assert EXCHANGE_ORDER_ID not in repr(result)


def test_catalog_reader_fails_closed_on_conflicting_duplicate_observation():
    rest = _RestClient()
    duplicate = deepcopy(rest.pages[None]["orders"][0])
    duplicate["status"] = "FILLED"
    duplicate["filled_size"] = "1"
    rest.pages["private-cursor-1"]["orders"][0] = duplicate
    reader = FuturesOrderCatalogReader(rest_client=rest)

    result = reader.run(
        before_category=lambda _category: None,
        before_page=lambda _ordinal, _cursor_hash: None,
    )

    assert result.outcome == "UNKNOWN"
    assert (
        result.diagnostic_code
        == "operator_futures_orders_catalog_identity_ambiguous"
    )
    assert result.orders == ()


def test_catalog_reader_keeps_documented_unknown_status_non_actionable():
    rest = _RestClient()
    rest.pages[None]["orders"][0]["status"] = "UNKNOWN_ORDER_STATUS"
    reader = FuturesOrderCatalogReader(rest_client=rest)

    result = reader.run(
        before_category=lambda _category: None,
        before_page=lambda _ordinal, _cursor_hash: None,
    )

    assert result.outcome == "SUCCEEDED"
    unknown = next(
        order
        for order in result.orders
        if order.client_order_id == CLIENT_ORDER_ID
    )
    assert unknown.status == "UNKNOWN_ORDER_STATUS"
    assert unknown.authoritatively_nonterminal is False
    assert unknown.cancel_eligible is False


def test_read_only_credential_can_inventory_but_cannot_mark_cancel_eligible():
    rest = _RestClient()
    rest.can_trade = False
    reader = FuturesOrderCatalogReader(rest_client=rest)

    result = reader.run(
        before_category=lambda _category: None,
        before_page=lambda _ordinal, _cursor_hash: None,
    )

    assert result.outcome == "SUCCEEDED"
    assert result.credential_can_trade is False
    assert all(order.cancel_eligible is False for order in result.orders)
    assert result.public_evidence["credential_can_trade"] is False


def test_cancel_service_never_invokes_executor_for_read_only_credential():
    rest = _RestClient()
    rest.can_trade = False
    result = FuturesOrderCatalogReader(rest_client=rest).run(
        before_category=lambda _category: None,
        before_page=lambda _ordinal, _cursor_hash: None,
    )
    executor = SimpleNamespace(cancel=Mock())
    service = OperatorFuturesOrderOperationsService(
        repository=SimpleNamespace(),
        catalog_reader=SimpleNamespace(),
        exchange_executor=executor,
    )
    terminal = SimpleNamespace(last_outcome="SUCCEEDED")
    service._run_cycle = lambda **_kwargs: (terminal, result)  # type: ignore[method-assign]

    returned = service.cancel_exact(
        context=FuturesOrderOperationsRequestContext(
            actor_id="operator-1",
            roles=("admin", "trader"),
            expected_revision=0,
            idempotency_key="cancel-read-only",
            correlation_id="corr-cancel-read-only",
            audit_id="audit-cancel-read-only",
            operator_intent="cancel_exact_futures_order",
            authorize_one_no_retry_cycle=True,
            acknowledge_cycle_is_goal_global_and_limited_to_ten=True,
            acknowledge_unknown_read_fails_closed=True,
            acknowledge_unknown_cancel_consumes_allowance=True,
        ),
        client_order_id=CLIENT_ORDER_ID,
    )

    assert returned is terminal
    executor.cancel.assert_not_called()


def test_catalog_reader_fails_closed_on_unpersistable_identity_length():
    rest = _RestClient()
    rest.pages[None]["orders"][0]["client_order_id"] = "x" * 129
    reader = FuturesOrderCatalogReader(rest_client=rest)

    result = reader.run(
        before_category=lambda _category: None,
        before_page=lambda _ordinal, _cursor_hash: None,
    )

    assert result.outcome == "UNKNOWN"
    assert (
        result.diagnostic_code
        == "operator_futures_orders_futures_order_catalog_schema_invalid"
    )
    assert result.orders == ()


def test_cancel_executor_uses_ephemeral_exchange_identity_once(monkeypatch):
    rest = _RestClient()
    scopes: list[str] = []
    monkeypatch.setattr(
        "application.admin_api.operator_futures_order_operations_runtime."
        "canonical_coinbase_execution_scope",
        lambda scope: _Scope(scopes, scope),
    )
    executor = AdminApiFuturesOrderOperationsExchangeExecutor(rest_client=rest)
    claims: list[str] = []

    result = executor.cancel(
        client_order_id=CLIENT_ORDER_ID,
        private_exchange_order_id=EXCHANGE_ORDER_ID,
        expected_exchange_order_id_sha256=(
            "fddd3333bc5239de95c90b7c19da1db31754b31100cef5a669dd3c15386e6bd0"
        ),
        before_call=lambda: claims.append("cancel_claimed"),
    )

    assert result.outcome == "ACCEPTED"
    assert result.diagnostic_code == "operator_futures_order_cancel_accepted"
    assert result.call_boundary_entered is True
    assert claims == ["cancel_claimed"]
    assert len(rest.cancel_calls) == 1
    assert rest.cancel_calls[0]["exchange_order_id"] == EXCHANGE_ORDER_ID
    assert EXCHANGE_ORDER_ID not in repr(result.public_evidence)
    assert scopes == ["canonical_admin_api_futures_cancel"]


def test_cancel_executor_proves_pre_call_failure_without_consuming_boundary(
    monkeypatch,
):
    rest = _RestClient()
    monkeypatch.setattr(
        "application.admin_api.operator_futures_order_operations_runtime."
        "canonical_coinbase_execution_scope",
        lambda _scope: _FailingScope(),
    )
    executor = AdminApiFuturesOrderOperationsExchangeExecutor(rest_client=rest)

    result = executor.cancel(
        client_order_id=CLIENT_ORDER_ID,
        private_exchange_order_id=EXCHANGE_ORDER_ID,
        expected_exchange_order_id_sha256=(
            "fddd3333bc5239de95c90b7c19da1db31754b31100cef5a669dd3c15386e6bd0"
        ),
        before_call=lambda: None,
    )

    assert result.outcome == "UNKNOWN"
    assert result.call_boundary_entered is False
    assert rest.cancel_calls == []


def test_cancel_executor_returns_fixed_rejection_without_raw_reason(
    monkeypatch,
):
    rest = _RestClient()
    rest.cancel_futures_order = lambda **kwargs: (
        kwargs.pop("before_sdk_call")(),
        SimpleNamespace(
            results=[
                SimpleNamespace(
                    success=False,
                    order_id=kwargs["exchange_order_id"],
                    failure_reason="private reason must be withheld",
                )
            ]
        ),
    )[1]
    monkeypatch.setattr(
        "application.admin_api.operator_futures_order_operations_runtime."
        "canonical_coinbase_execution_scope",
        lambda scope: _Scope([], scope),
    )
    executor = AdminApiFuturesOrderOperationsExchangeExecutor(rest_client=rest)

    result = executor.cancel(
        client_order_id=CLIENT_ORDER_ID,
        private_exchange_order_id=EXCHANGE_ORDER_ID,
        expected_exchange_order_id_sha256=(
            "fddd3333bc5239de95c90b7c19da1db31754b31100cef5a669dd3c15386e6bd0"
        ),
        before_call=lambda: None,
    )

    assert result.outcome == "REJECTED"
    assert result.call_boundary_entered is True
    assert result.diagnostic_code == (
        "operator_futures_order_cancel_exchange_rejected"
    )
    assert "private reason" not in repr(result)


def test_cancel_executor_marks_post_boundary_exception_unknown(monkeypatch):
    rest = _RestClient()

    def fail_after_boundary(**kwargs):
        kwargs.pop("before_sdk_call")()
        raise RuntimeError("withheld")

    rest.cancel_futures_order = fail_after_boundary
    monkeypatch.setattr(
        "application.admin_api.operator_futures_order_operations_runtime."
        "canonical_coinbase_execution_scope",
        lambda scope: _Scope([], scope),
    )
    executor = AdminApiFuturesOrderOperationsExchangeExecutor(rest_client=rest)

    result = executor.cancel(
        client_order_id=CLIENT_ORDER_ID,
        private_exchange_order_id=EXCHANGE_ORDER_ID,
        expected_exchange_order_id_sha256=(
            "fddd3333bc5239de95c90b7c19da1db31754b31100cef5a669dd3c15386e6bd0"
        ),
        before_call=lambda: None,
    )

    assert result.outcome == "UNKNOWN"
    assert result.call_boundary_entered is True
    assert result.diagnostic_code == (
        "operator_futures_order_cancel_outcome_unknown"
    )
    assert "withheld" not in repr(result)


class _Scope:
    def __init__(self, scopes: list[str], scope: str) -> None:
        self.scopes = scopes
        self.scope = scope

    def __enter__(self):
        self.scopes.append(self.scope)

    def __exit__(self, *_args):
        return False


class _FailingScope:
    def __enter__(self):
        raise RuntimeError("not inspected")

    def __exit__(self, *_args):
        return False
