from __future__ import annotations

from dataclasses import dataclass

import pytest

from application.admin_api.operator_single_order_reprice_now_runtime import (
    OperatorSingleOrderRepriceNowSourceResolver,
)


STEALTH_ID = "11111111-1111-4111-8111-111111111111"
SOURCE_CLIENT_ORDER_ID = "22222222-2222-4222-8222-222222222222"
RAW_EXCHANGE_ORDER_ID = "raw-exchange-order-id-never-returned"
PORTFOLIO_ID = "33333333-3333-4333-8333-333333333333"


@dataclass
class _Manager:
    status: str = "REVEALED"
    executed_size: str = "0"
    root_client_order_id: str = STEALTH_ID

    expected_retail_portfolio_id: str = PORTFOLIO_ID

    def _get_stealth_order(self, stealth_order_id: str):
        assert stealth_order_id == STEALTH_ID
        return {
            "stealth_order_id": STEALTH_ID,
            "status": self.status,
            "executed_size": self.executed_size,
            "remaining_size": "0",
            "allow_partial_fills": False,
            "anchor_repricing_state_json": {
                "active_placement_client_order_id": SOURCE_CLIENT_ORDER_ID,
                "active_exchange_order_id": RAW_EXCHANGE_ORDER_ID,
            },
        }

    def get_operator_stealth_move_source_placement(
        self,
        stealth_order_id: str,
    ):
        assert stealth_order_id == STEALTH_ID
        return {
            "client_order_id": SOURCE_CLIENT_ORDER_ID,
            "exchange_order_id": RAW_EXCHANGE_ORDER_ID,
            "status": "OPEN",
            "size": "0.00001",
            "allow_partial_fills": False,
            "retail_portfolio_id": PORTFOLIO_ID,
        }

    def resolve_operator_stealth_chain_root(
        self,
        stealth_order_id: str,
    ) -> str:
        assert stealth_order_id == STEALTH_ID
        return self.root_client_order_id


def _definition() -> dict[str, object]:
    return {
        "definition_id": STEALTH_ID,
        "revision": 7,
        "definition_sha256": "a" * 64,
    }


def test_resolves_only_exact_local_revealed_zero_fill_source() -> None:
    result = OperatorSingleOrderRepriceNowSourceResolver(
        manager=_Manager(),
        configured_portfolio_id=PORTFOLIO_ID,
    ).resolve(
        definition=_definition(),
        stealth_order_id=STEALTH_ID,
        source_client_order_id=SOURCE_CLIENT_ORDER_ID,
    )

    assert result["eligible"] is True
    assert result["diagnostic_code"] == "operator_reprice_now_source_eligible"
    assert len(result["source_evidence_sha256"]) == 64
    assert RAW_EXCHANGE_ORDER_ID not in repr(result)
    assert result["root_client_order_id"] == STEALTH_ID


@pytest.mark.parametrize(
    ("manager", "code"),
    [
        (
            _Manager(status="HIDDEN"),
            "operator_reprice_now_source_not_revealed",
        ),
        (
            _Manager(executed_size="0.1"),
            "operator_reprice_now_zero_fill_not_proven",
        ),
        (
            _Manager(root_client_order_id=SOURCE_CLIENT_ORDER_ID),
            "operator_reprice_now_source_not_direct_parent",
        ),
    ],
)
def test_resolver_fails_closed(
    manager: _Manager,
    code: str,
) -> None:
    result = OperatorSingleOrderRepriceNowSourceResolver(
        manager=manager,
        configured_portfolio_id=PORTFOLIO_ID,
    ).resolve(
        definition=_definition(),
        stealth_order_id=STEALTH_ID,
        source_client_order_id=SOURCE_CLIENT_ORDER_ID,
    )

    assert result["eligible"] is False
    assert result["diagnostic_code"] == code
