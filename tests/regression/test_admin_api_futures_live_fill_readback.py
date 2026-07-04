from __future__ import annotations

from dataclasses import dataclass, field

from tools.run_admin_api_futures_live_fill_readback import (
    FuturesLiveFillReadbackConfig,
    run_futures_live_fill_readback,
)


@dataclass
class FakeFuturesReadbackRestClient:
    list_orders_response: dict = field(default_factory=dict)
    list_orders_responses_by_status: dict[str, dict] = field(default_factory=dict)
    list_fills_response: dict = field(default_factory=dict)
    list_orders_calls: list[dict] = field(default_factory=list)
    list_fills_calls: list[dict] = field(default_factory=list)

    def list_orders(self, **kwargs):
        self.list_orders_calls.append(kwargs)
        statuses = kwargs.get("order_status") or []
        status = statuses[0] if statuses else ""
        if status in self.list_orders_responses_by_status:
            return self.list_orders_responses_by_status[status]
        return self.list_orders_response

    def list_fills(self, **kwargs):
        self.list_fills_calls.append(kwargs)
        return self.list_fills_response


def test_futures_live_fill_readback_proves_filled_order_by_client_order_id():
    rest_client = FakeFuturesReadbackRestClient(
        list_orders_response={
            "orders": [
                {
                    "client_order_id": "futures-live-submit-test",
                    "order_id": "exchange-order-live-1",
                    "product_id": "AVP-20DEC30-CDE",
                    "status": "FILLED",
                    "filled_size": "1",
                    "average_filled_price": "6.87",
                }
            ]
        },
        list_fills_response={
            "fills": [
                {
                    "entry_id": "entry-1",
                    "trade_id": "trade-1",
                    "order_id": "exchange-order-live-1",
                    "product_id": "AVP-20DEC30-CDE",
                    "size": "1",
                    "price": "6.87",
                    "commission": "0.01",
                }
            ],
            "has_next": False,
        },
    )

    summary = run_futures_live_fill_readback(
        rest_client,
        FuturesLiveFillReadbackConfig(
            client_order_id="futures-live-submit-test",
            product_id="AVP-20DEC30-CDE",
            backend_contract_ref="backend-ref",
        ),
    )

    assert summary["status"] == "passed"
    assert summary["live_coinbase_execution"] == "not_run"
    assert summary["live_coinbase_read_ran"] is True
    assert summary["live_coinbase_orders_ran"] is False
    assert summary["client_order_id"] == "futures-live-submit-test"
    assert summary["product_id"] == "AVP-20DEC30-CDE"
    assert summary["order_status"] == "FILLED"
    assert summary["filled_order_found"] is True
    assert summary["exchange_order_id_present"] is True
    assert summary["exchange_order_id_evidence_only"] is True
    assert summary["fill_count"] == 1
    assert summary["fill_read_status"] == "filled"
    assert summary["executed_notional_usdc"] == "68.70"
    assert summary["notional_usdc"] == "0"
    assert all(check["passed"] for check in summary["checks"])
    assert rest_client.list_orders_calls == [{"order_status": ["FILLED"]}]
    assert rest_client.list_fills_calls == [
        {"order_id": "exchange-order-live-1", "limit": 100}
    ]


def test_futures_live_fill_readback_fails_when_order_is_not_filled():
    rest_client = FakeFuturesReadbackRestClient(
        list_orders_responses_by_status={
            "FILLED": {"orders": []},
            "OPEN": {
                "orders": [
                    {
                        "client_order_id": "futures-live-submit-test",
                        "order_id": "exchange-order-live-1",
                        "product_id": "AVP-20DEC30-CDE",
                        "status": "OPEN",
                        "filled_size": "0",
                    }
                ]
            },
        },
        list_fills_response={"fills": [], "has_next": False},
    )

    summary = run_futures_live_fill_readback(
        rest_client,
        FuturesLiveFillReadbackConfig(
            client_order_id="futures-live-submit-test",
            product_id="AVP-20DEC30-CDE",
            backend_contract_ref="backend-ref",
        ),
    )

    assert summary["status"] == "failed"
    assert summary["order_status"] == "OPEN"
    assert summary["filled_order_found"] is False
    assert summary["fill_count"] == 0
    assert summary["executed_notional_usdc"] == "0"
    failed = [check["name"] for check in summary["checks"] if not check["passed"]]
    assert "futures_order_status_filled" in failed
    assert "futures_fill_records_present" in failed
    assert rest_client.list_orders_calls == [
        {"order_status": ["FILLED"]},
        {"order_status": ["OPEN"]},
    ]


def test_futures_live_fill_readback_fails_when_fill_order_id_does_not_match():
    rest_client = FakeFuturesReadbackRestClient(
        list_orders_response={
            "orders": [
                {
                    "client_order_id": "futures-live-submit-test",
                    "order_id": "exchange-order-live-1",
                    "product_id": "AVP-20DEC30-CDE",
                    "status": "FILLED",
                }
            ]
        },
        list_fills_response={
            "fills": [
                {
                    "entry_id": "entry-1",
                    "trade_id": "trade-1",
                    "order_id": "different-exchange-order",
                    "product_id": "AVP-20DEC30-CDE",
                    "size": "1",
                    "price": "6.87",
                }
            ],
            "has_next": False,
        },
    )

    summary = run_futures_live_fill_readback(
        rest_client,
        FuturesLiveFillReadbackConfig(
            client_order_id="futures-live-submit-test",
            product_id="AVP-20DEC30-CDE",
            backend_contract_ref="backend-ref",
        ),
    )

    assert summary["status"] == "failed"
    assert summary["fill_order_id_matches_exchange_order_id"] is False
    failed = [check["name"] for check in summary["checks"] if not check["passed"]]
    assert "futures_fills_match_exchange_order_id" in failed
