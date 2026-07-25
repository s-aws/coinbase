from __future__ import annotations

from application.admin_api.operator_futures_position_lifecycle import (
    FuturesPositionExecutionPlan,
)
from application.admin_api.operator_futures_position_runtime import (
    AdminApiFuturesPositionExchangeExecutor,
)
from core.enums import AdminFuturesPositionCallOutcome


PRODUCT_ID = "AVP-20DEC30-CDE"
POSITION_KEY = "futures_position:v1:" + ("a" * 64)


class _RestClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def close_operator_futures_position(
        self,
        *,
        client_order_id,
        product_id,
        size,
        before_sdk_call,
    ):
        before_sdk_call()
        self.calls.append(("close", size))
        return {
            "success": True,
            "success_response": {
                "order_id": "exchange-close-1",
            },
        }

    def get_order(self, order_id, *, before_sdk_call):
        before_sdk_call()
        self.calls.append(("order", order_id))
        return {
            "order": {
                "order_id": order_id,
                "client_order_id": "client-close-1",
                "product_id": PRODUCT_ID,
                "side": "SELL",
                "status": "OPEN",
            }
        }

    def get_operator_futures_position(self, *, product_id, before_sdk_call):
        before_sdk_call()
        self.calls.append(("position", product_id))
        return {
            "position": {
                "product_id": product_id,
                "number_of_contracts": "3",
                "side": "LONG",
            }
        }

    def cancel_operator_futures_position_order(
        self,
        *,
        exchange_order_id,
        before_sdk_call,
    ):
        before_sdk_call()
        self.calls.append(("cancel", exchange_order_id))
        return {
            "results": [
                {
                    "success": True,
                    "order_id": exchange_order_id,
                }
            ]
        }


class _DirectPositionRestClient(_RestClient):
    def get_operator_futures_position(self, *, product_id, before_sdk_call):
        before_sdk_call()
        self.calls.append(("position", product_id))
        return {
            "product_id": product_id,
            "number_of_contracts": "3",
            "side": "LONG",
        }


def _plan(mode: str) -> FuturesPositionExecutionPlan:
    return FuturesPositionExecutionPlan(
        claim_id="claim-1",
        client_order_id="client-close-1",
        mode=mode,
        product_id=PRODUCT_ID,
        position_key=POSITION_KEY,
        action_size=None if mode == "CLOSE_FULL" else "1",
        expected_contracts="3",
        close_side="SELL",
        portfolio_id_sha256="b" * 64,
    )


def test_executor_full_close_uses_omitted_size_and_fixed_public_evidence():
    rest = _RestClient()
    executor = AdminApiFuturesPositionExchangeExecutor(rest_client=rest)
    invoked: list[str] = []

    result = executor.close_or_reduce(
        plan=_plan("CLOSE_FULL"),
        before_call=lambda: invoked.append("action"),
    )

    assert result.outcome is AdminFuturesPositionCallOutcome.ACCEPTED
    assert rest.calls == [("close", None)]
    assert invoked == ["action"]
    assert result.private_exchange_order_id == "exchange-close-1"
    assert len(result.exchange_order_id_sha256 or "") == 64
    assert "exchange-close-1" not in repr(result.public_evidence)


def test_executor_reduce_passes_exact_one_contract_size():
    rest = _RestClient()
    executor = AdminApiFuturesPositionExchangeExecutor(rest_client=rest)

    result = executor.close_or_reduce(
        plan=_plan("REDUCE_ONE_CONTRACT"),
        before_call=lambda: None,
    )

    assert result.outcome is AdminFuturesPositionCallOutcome.ACCEPTED
    assert rest.calls == [("close", "1")]


def test_executor_reconciles_exact_order_and_position_then_cancels_exact_order():
    rest = _RestClient()
    executor = AdminApiFuturesPositionExchangeExecutor(rest_client=rest)
    plan = _plan("CLOSE_FULL")

    order = executor.reconcile_order(
        plan=plan,
        private_exchange_order_id="exchange-close-1",
        before_call=lambda: None,
    )
    position = executor.reconcile_position(
        plan=plan,
        before_call=lambda: None,
    )
    cancel = executor.cancel(
        plan=plan,
        private_exchange_order_id="exchange-close-1",
        before_call=lambda: None,
    )

    assert order.outcome is AdminFuturesPositionCallOutcome.ACCEPTED
    assert order.authoritatively_nonterminal is True
    assert position.outcome is AdminFuturesPositionCallOutcome.ACCEPTED
    assert position.remaining_contracts == "3"
    assert cancel.outcome is AdminFuturesPositionCallOutcome.ACCEPTED
    assert rest.calls == [
        ("order", "exchange-close-1"),
        ("position", PRODUCT_ID),
        ("cancel", "exchange-close-1"),
    ]


def test_executor_accepts_documented_direct_futures_position_response():
    rest = _DirectPositionRestClient()
    executor = AdminApiFuturesPositionExchangeExecutor(rest_client=rest)

    position = executor.reconcile_position(
        plan=_plan("CLOSE_FULL"),
        before_call=lambda: None,
    )

    assert position.outcome is AdminFuturesPositionCallOutcome.ACCEPTED
    assert position.remaining_contracts == "3"
    assert rest.calls == [("position", PRODUCT_ID)]


class _HostilePositionRestClient(_RestClient):
    def __init__(self, position_response):
        super().__init__()
        self.position_response = position_response

    def get_operator_futures_position(self, *, product_id, before_sdk_call):
        before_sdk_call()
        self.calls.append(("position", product_id))
        return self.position_response


def test_executor_rejects_empty_or_null_position_reconciliation():
    for response in ({}, {"position": None}):
        executor = AdminApiFuturesPositionExchangeExecutor(
            rest_client=_HostilePositionRestClient(response)
        )

        result = executor.reconcile_position(
            plan=_plan("CLOSE_FULL"),
            before_call=lambda: None,
        )

        assert result.outcome is AdminFuturesPositionCallOutcome.UNKNOWN
        assert result.remaining_contracts is None


def test_executor_rejects_wrong_side_or_portfolio_position_reconciliation():
    hostile_rows = [
        {
            "position": {
                "product_id": PRODUCT_ID,
                "number_of_contracts": "3",
                "side": "SHORT",
            }
        },
        {
            "position": {
                "product_id": PRODUCT_ID,
                "number_of_contracts": "3",
                "side": "LONG",
                "portfolio_uuid": "wrong-private-portfolio",
            }
        },
    ]
    for response in hostile_rows:
        executor = AdminApiFuturesPositionExchangeExecutor(
            rest_client=_HostilePositionRestClient(response)
        )

        result = executor.reconcile_position(
            plan=_plan("CLOSE_FULL"),
            before_call=lambda: None,
        )

        assert result.outcome is AdminFuturesPositionCallOutcome.UNKNOWN
        assert result.remaining_contracts is None
