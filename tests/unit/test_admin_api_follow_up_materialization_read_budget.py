"""Proof-specific read budgets for follow-up materialization.

All Coinbase-facing objects in this module are synthetic.  The two-page
fixtures prove the materialization proof path never follows a continuation
cursor and cannot reach a Create or Cancel method.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

from application.admin_api.operator_follow_up_materialization import (
    ChildExchangeState,
)
from application.admin_api.operator_follow_up_materialization_runtime import (
    ProductionFollowUpMaterializationRuntime,
    _BoundedMaterializationReadClient,
    _read_single_page_materialization_wallets,
    _single_page_materialization_order_readback,
)


SOURCE_ID = "8cbe2f03-acde-4fe9-a4fd-71752cfbdfc7"
ROOT_ID = "6410dd1d-15a5-4e6d-afc4-80905e02b154"
CHILD_ID = "2ada1ec3-891c-5ccd-a13e-9d69decc7e1a"
INTENT_ID = "bf57f399-05e6-425f-bd2b-f423a117e17e"
MATERIALIZATION_ID = "5c81a93f-7bfc-49e7-9dbb-5ae949349af6"
AUDIT_ID = "7205acd0-dc76-4fe8-93e3-03862de412c9"
PORTFOLIO_ID = "abbfd6d3-ebae-46e0-83fe-c0d21b0c0087"
SOURCE_EXCHANGE_ID = "9bd25702-bc03-4173-9796-6fe94aad5604"
CHILD_EXCHANGE_ID = "6497c186-cff6-4f66-aa87-405d0a265519"
OPERATION_KEY_SHA256 = hashlib.sha256(b"one-use-closeout").hexdigest()


class _TwoPageCoinbaseClient:
    def __init__(self) -> None:
        self.account_calls: list[dict[str, object]] = []
        self.order_calls: list[dict[str, object]] = []
        self.create_calls = 0
        self.cancel_calls = 0

    def get_accounts(self, **kwargs):
        self.account_calls.append(dict(kwargs))
        if kwargs.get("cursor"):
            raise AssertionError("materialization wallet proof followed a cursor")
        return {
            "accounts": [
                {
                    "currency": "BTC",
                    "available_balance": {"value": "1", "currency": "BTC"},
                    "deleted_at": None,
                }
            ],
            "has_next": True,
            "cursor": "withheld-second-page",
        }

    def list_orders(self, **kwargs):
        self.order_calls.append(dict(kwargs))
        if kwargs.get("cursor"):
            raise AssertionError("materialization child proof followed a cursor")
        return {
            "orders": [
                {
                    "client_order_id": CHILD_ID,
                    "order_id": CHILD_EXCHANGE_ID,
                    "product_id": "BTC-USDC",
                    "side": "SELL",
                    "status": "OPEN",
                    "retail_portfolio_id": PORTFOLIO_ID,
                    "order_configuration": {
                        "limit_limit_gtc": {
                            "base_size": "0.00001",
                            "limit_price": "100000.00",
                            "post_only": False,
                        }
                    },
                }
            ],
            "has_next": True,
            "cursor": "withheld-second-page",
        }

    def create_order(self, **_kwargs):
        self.create_calls += 1
        raise AssertionError("paginated eligibility must not lead to Create")

    def cancel_order(self, *_args, **_kwargs):
        self.cancel_calls += 1
        raise AssertionError("paginated reconciliation must not lead to Cancel")


class _EligibilityRepository:
    def read_materialization(self, source_client_order_id: str):
        assert source_client_order_id == SOURCE_ID
        return SimpleNamespace(
            readiness=SimpleNamespace(
                source_client_order_id=SOURCE_ID,
                root_client_order_id=ROOT_ID,
                follow_up_intent_id=INTENT_ID,
                deterministic_child_client_order_id=CHILD_ID,
                eligible=True,
                blockers=(),
                product_id="BTC-USDC",
                source_side="BUY",
                derived_follow_up_side="SELL",
                base_size="0.00001",
            ),
            attempt=None,
        )


def _source_order(client_order_id: str) -> dict[str, object]:
    if client_order_id == CHILD_ID:
        return {
            "client_order_id": CHILD_ID,
            "product_id": "BTC-USDC",
            "side": "SELL",
            "size": "0.00001",
            "price": "100000.00",
            "status": "SUBMISSION_UNKNOWN",
            "retail_portfolio_id": PORTFOLIO_ID,
            "exchange_order_id": None,
        }
    return {
        "client_order_id": SOURCE_ID,
        "product_id": "BTC-USDC",
        "side": "BUY",
        "size": "0.00001",
        "price": "90000.00",
        "status": "FILLED",
        "retail_portfolio_id": PORTFOLIO_ID,
        "exchange_order_id": SOURCE_EXCHANGE_ID,
    }


def _runtime(
    client: _TwoPageCoinbaseClient,
    *,
    wallet_reader,
    source_order_readback,
) -> ProductionFollowUpMaterializationRuntime:
    return ProductionFollowUpMaterializationRuntime(
        native_repository=_EligibilityRepository(),
        rest_client=client,
        configured_portfolio_id=PORTFOLIO_ID,
        environment="controlled_live",
        runtime_authority_check=lambda: True,
        local_order_reader=_source_order,
        template_resolver=lambda _source, _root: {
            "product_id": "BTC-USDC",
            "side": "SELL",
            "order_base_size": "0.00001",
            "start_price": "100000.00",
        },
        product_reader=lambda _client, _product: {
            "product_id": "BTC-USDC",
            "product_type": "SPOT",
            "trading_disabled": False,
            "base_increment": "0.00001",
            "quote_increment": "0.01",
        },
        portfolio_binding_evaluator=lambda _client, expected: SimpleNamespace(
            ready=True,
            observed_portfolio_id=expected,
        ),
        source_order_readback=source_order_readback,
        source_fill_readback=lambda _client, **_kwargs: {
            "authoritative": True,
            "fill_read_succeeded": True,
            "pagination_complete": True,
            "fill_count": 1,
        },
        market_reference_reader=lambda _client, _product: {
            "best_bid": "50000",
            "source": "coinbase_rest_best_bid",
            "observed_at": "2026-07-19T00:00:00+00:00",
        },
        standing_price_evaluator=lambda **_kwargs: {"allowed": True},
        wallet_reader=lambda read_client: wallet_reader(read_client),
        action_guard_evaluator=lambda **_kwargs: True,
        child_persister=lambda _order: (1, True),
        local_stealth_reader=lambda _child: None,
    )


def test_paginated_wallet_page_fails_closed_after_one_network_method_call() -> None:
    client = _TwoPageCoinbaseClient()
    runtime = _runtime(
        client,
        wallet_reader=_read_single_page_materialization_wallets,
        source_order_readback=lambda _client, **_kwargs: {
            "authoritative": True,
            "exact_identity_match": True,
            "authoritative_status": "FILLED",
            "retail_portfolio_id_matches_expected": True,
            "exchange_order_id": SOURCE_EXCHANGE_ID,
            "matched_order": {
                "client_order_id": SOURCE_ID,
                "order_id": SOURCE_EXCHANGE_ID,
                "product_id": "BTC-USDC",
                "side": "BUY",
                "status": "FILLED",
                "filled_size": "0.00001",
            },
        },
    )

    evidence = runtime.resolve_fresh_materialization_eligibility(
        source_client_order_id=SOURCE_ID
    )

    assert evidence.candidate is None
    assert evidence.fresh is False
    assert evidence.ambiguous is True
    assert evidence.coinbase_read_started is True
    assert evidence.blockers == ("follow_up_materialization_eligibility_unavailable",)
    assert client.account_calls == [{"limit": 250}]
    assert client.create_calls == 0


def test_paginated_unknown_child_fails_closed_after_one_network_method_call() -> None:
    client = _TwoPageCoinbaseClient()
    runtime = _runtime(
        client,
        wallet_reader=lambda _client: {
            "BTC": {"available_balance": {"value": "1"}}
        },
        source_order_readback=_single_page_materialization_order_readback,
    )

    evidence = runtime.read_authoritative_child_state(
        child_client_order_id=CHILD_ID,
        materialization_id=MATERIALIZATION_ID,
        operation_audit_id=AUDIT_ID,
        operation_idempotency_key_sha256=OPERATION_KEY_SHA256,
    )

    assert evidence.state is ChildExchangeState.UNKNOWN
    assert evidence.authoritative is False
    assert evidence.ambiguous is True
    assert evidence.fresh is False
    assert evidence.coinbase_read_started is True
    assert evidence.read_count == 1
    assert evidence.individual_retry_count == 0
    assert client.order_calls == [
        {
            "limit": 100,
            "product_ids": ["BTC-USDC"],
            "product_type": "SPOT",
        }
    ]
    assert client.cancel_calls == 0


def test_bounded_read_client_refuses_an_eleventh_sdk_method_call() -> None:
    class Client:
        def get_product(self):
            return {"ok": True}

    bounded = _BoundedMaterializationReadClient(Client(), maximum_calls=10)

    for _ in range(10):
        assert bounded.get_product() == {"ok": True}

    try:
        bounded.get_product()
    except RuntimeError as exc:
        assert str(exc) == "follow_up_materialization_read_budget_exhausted"
    else:  # pragma: no cover - fail clearly if the budget regresses
        raise AssertionError("eleventh SDK method call was not blocked")
    assert bounded.call_count == 10
