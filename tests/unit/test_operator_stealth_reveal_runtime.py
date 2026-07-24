from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
from typing import Any
from unittest.mock import MagicMock

import pytest
from coinbase.rest.types.orders_types import PreviewOrderResponse

from application.admin_api import operator_stealth_reveal_runtime as runtime_module
from application.admin_api.operator_stealth_reveal_runtime import (
    OperatorStealthRevealRuntime,
)
from external.coinbase_client import CoinbaseRestClient


class _RestClient:
    def __init__(self, response: PreviewOrderResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def preview_order(self, **request: Any) -> PreviewOrderResponse:
        before_sdk_call = request.pop("before_sdk_call")
        before_sdk_call()
        self.calls.append(request)
        return self.response


def _preview_response(*, quote_size: str = "0.6") -> PreviewOrderResponse:
    return PreviewOrderResponse(
        {
            "order_total": "0.6006",
            "commission_total": "0.0006",
            "errs": [],
            "warning": [],
            "quote_size": quote_size,
            "base_size": "0.00001",
            "best_bid": "59999",
            "best_ask": "60000",
            "is_max": False,
            "preview_id": "private-preview-identifier",
        }
    )


def test_preview_binds_documented_quote_size_to_base_times_limit(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        runtime_module,
        "canonical_coinbase_execution_scope",
        lambda _scope: nullcontext(),
    )
    monkeypatch.setattr(
        runtime_module,
        "require_coinbase_execution_authority",
        lambda **_kwargs: None,
    )
    client = _RestClient(_preview_response())
    runtime = OperatorStealthRevealRuntime(object(), client)
    boundaries: list[str] = []
    plan = {
        "product_id": "BTC-USDC",
        "side": "BUY",
        "base_size": "0.00001",
        "limit_price": "60000",
        "post_only": True,
    }

    outcome = runtime.preview(
        plan,
        before_call=lambda: boundaries.append("claimed"),
    )

    assert outcome == "ACCEPTED"
    assert boundaries == ["claimed"]
    assert client.calls == [
        {
            "product_id": "BTC-USDC",
            "side": "BUY",
            "order_configuration": {
                "limit_limit_gtc": {
                    "base_size": "0.00001",
                    "limit_price": "60000",
                    "post_only": True,
                }
            },
            "require_spot_preview_authority": True,
        }
    ]


def test_preview_rejects_a_quote_size_not_bound_to_frozen_plan(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        runtime_module,
        "canonical_coinbase_execution_scope",
        lambda _scope: nullcontext(),
    )
    monkeypatch.setattr(
        runtime_module,
        "require_coinbase_execution_authority",
        lambda **_kwargs: None,
    )
    client = _RestClient(_preview_response(quote_size="0.7"))
    runtime = OperatorStealthRevealRuntime(object(), client)

    outcome = runtime.preview(
        {
            "product_id": "BTC-USDC",
            "side": "BUY",
            "base_size": "0.00001",
            "limit_price": "60000",
            "post_only": True,
        },
        before_call=lambda: None,
    )

    assert outcome == "UNKNOWN"


def test_create_fails_before_manager_when_frozen_plan_binding_drifts() -> None:
    manager = MagicMock()
    runtime = OperatorStealthRevealRuntime(manager, object())
    definition = {
        "definition_id": "11111111-1111-4111-8111-111111111111",
        "revision": 1,
        "definition_sha256": "a" * 64,
        "product_id": "BTC-USDC",
        "side": "BUY",
        "total_size": "0.00001",
        "limit_price": "60000",
        "reveal_pricing_policy": "TOP_OF_BOOK",
    }
    plan = {
        "product_id": "BTC-USDC",
        "side": "BUY",
        "base_size": "0.00002",
        "limit_price": "60000",
        "post_only": True,
    }
    plan_sha256 = hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    result = runtime.reveal(
        definition,
        plan=plan,
        plan_sha256=plan_sha256,
        preview_claim_id="33333333-3333-4333-8333-333333333333",
        portfolio_id="22222222-2222-4222-8222-222222222222",
        prepreview_admission_sha256="c" * 64,
        before_create_call=lambda: None,
    )

    assert result == {
        "outcome": "REJECTED",
        "placement_attempted": False,
        "client_order_id": definition["definition_id"],
        "exchange_order_id": None,
        "diagnostic_code": "operator_stealth_preview_binding_mismatch",
    }
    manager.prepare_operator_stealth_reveal.assert_not_called()
    manager.reveal_order_slice.assert_not_called()


def test_wrapper_invocation_hooks_run_at_each_exact_sdk_boundary(
    monkeypatch,
) -> None:
    sdk = MagicMock()
    sdk.get_api_key_permissions.return_value = {}
    sdk.get_portfolios.return_value = {"portfolios": []}
    sdk.get_accounts.return_value = {
        "accounts": [],
        "has_next": False,
    }
    sdk.get_order.return_value = {"order": {}}
    sdk.preview_order.return_value = {}
    sdk.create_order.return_value = {}
    sdk.cancel_orders.return_value = {}
    monkeypatch.setattr(
        "external.coinbase_client._harden_sdk_transport",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "external.coinbase_client.require_coinbase_execution_authority",
        lambda **_kwargs: None,
    )
    client = CoinbaseRestClient(sdk)
    observed: list[str] = []

    client.get_api_key_permissions(
        before_sdk_call=lambda: observed.append("permissions")
    )
    client.list_portfolios(
        before_sdk_call=lambda: observed.append("catalog")
    )
    client.get_accounts(
        limit=250,
        before_sdk_call=lambda: observed.append("wallet"),
    )
    client.get_order(
        "exchange-id",
        before_sdk_call=lambda: observed.append("exact"),
    )
    client.preview_order(
        product_id="BTC-USDC",
        side="BUY",
        order_configuration={},
        before_sdk_call=lambda: observed.append("preview"),
    )
    client.create_order(
        product_id="BTC-USDC",
        side="BUY",
        order_configuration={},
        before_sdk_call=lambda: observed.append("create"),
    )
    client.cancel_orders(
        ["exchange-id"],
        before_sdk_call=lambda: observed.append("cancel"),
    )

    assert observed == [
        "permissions",
        "catalog",
        "wallet",
        "exact",
        "preview",
        "create",
        "cancel",
    ]
    sdk.get_api_key_permissions.assert_called_once()
    sdk.get_portfolios.assert_called_once()
    sdk.get_accounts.assert_called_once_with(limit=250)
    sdk.get_order.assert_called_once_with("exchange-id")
    sdk.preview_order.assert_called_once()
    sdk.create_order.assert_called_once()
    sdk.cancel_orders.assert_called_once_with(["exchange-id"])


def test_exact_readback_uses_one_exchange_id_read_and_preserves_identity(
) -> None:
    client_order_id = "11111111-1111-4111-8111-111111111111"
    portfolio_id = "22222222-2222-4222-8222-222222222222"
    exchange_order_id = "withheld-exchange-id"
    exchange_hash = hashlib.sha256(
        exchange_order_id.encode()
    ).hexdigest()
    manager = MagicMock()
    manager.expected_retail_portfolio_id = portfolio_id
    manager._get_stealth_order.return_value = {
        "anchor_repricing_state_json": {
            "active_placement_client_order_id": client_order_id,
            "active_exchange_order_id": exchange_order_id,
        }
    }
    calls: list[str] = []

    class _ExactClient:
        @staticmethod
        def get_order(
            order_id: str,
            *,
            before_sdk_call,
        ) -> dict[str, Any]:
            assert order_id == exchange_order_id
            before_sdk_call()
            calls.append("get_order")
            return {
                "order": {
                    "client_order_id": client_order_id,
                    "order_id": exchange_order_id,
                    "status": "OPEN",
                    "product_id": "BTC-USDC",
                    "retail_portfolio_id": portfolio_id,
                }
            }

    runtime = OperatorStealthRevealRuntime(manager, _ExactClient())

    result = runtime.exact_readback(
        client_order_id=client_order_id,
        product_id="BTC-USDC",
        expected_exchange_order_id_sha256=exchange_hash,
        before_call=lambda: calls.append("claimed"),
    )

    assert calls == ["claimed", "get_order"]
    assert result == {
        "authoritative": True,
        "client_order_id": client_order_id,
        "exchange_order_id": exchange_order_id,
        "exchange_order_id_sha256": exchange_hash,
        "portfolio_matches": True,
        "status": "OPEN",
    }


def test_exact_readback_rejects_local_exchange_hash_drift_without_wire_call(
) -> None:
    manager = MagicMock()
    manager._get_stealth_order.return_value = {
        "anchor_repricing_state_json": {
            "active_placement_client_order_id": (
                "11111111-1111-4111-8111-111111111111"
            ),
            "active_exchange_order_id": "withheld-exchange-id",
        }
    }
    client = MagicMock()
    runtime = OperatorStealthRevealRuntime(manager, client)
    claimed: list[str] = []

    with pytest.raises(
        RuntimeError,
        match="operator_stealth_exact_identity_unavailable",
    ):
        runtime.exact_readback(
            client_order_id=(
                "11111111-1111-4111-8111-111111111111"
            ),
            product_id="BTC-USDC",
            expected_exchange_order_id_sha256="f" * 64,
            before_call=lambda: claimed.append("claimed"),
        )

    assert claimed == []
    client.get_order.assert_not_called()
