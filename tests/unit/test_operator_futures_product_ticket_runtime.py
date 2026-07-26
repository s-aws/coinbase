from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from application.admin_api.operator_futures_product_ticket_runtime import (
    AdminApiFuturesProductTicketExchangeExecutor,
)
from application.admin_api.operator_futures_product_ticket_service_runtime import (
    _DeferredFuturesDefaultRestClient,
)
from core.enums import AdminFuturesManualCallOutcome


PRODUCT_ID = "BIP-20DEC30-CDE"
CLIENT_ORDER_ID = "operator-futures-product-ticket-child"
EXCHANGE_ORDER_ID = "private-exchange-order-id"
PREVIEW_ID = "private-preview-id"


def _candidate() -> dict[str, str]:
    return {
        "product_id": PRODUCT_ID,
        "side": "BUY",
        "order_type": "LIMIT_GTC",
        "post_only": "true",
        "contract_count": "1",
        "contract_size": "0.1",
        "limit_price": "498",
        "opening_reference_notional_usdc": "50.10",
        "maximum_exposure_reference_notional_usdc": "50.10",
        "buffered_close_reference_notional_usdc": "60.12",
        "branch_turnover_reference_notional_usdc": "110.22",
        "opening_cap_usdc": "100",
        "exposure_cap_usdc": "150",
        "turnover_cap_usdc": "300",
        "product_policy_revision": "7",
        "product_policy_sha256": "a" * 64,
    }


def _preview_response(*, errs=None):
    return SimpleNamespace(
        order_total="49.80",
        commission_total="0.20",
        errs=[] if errs is None else errs,
        warning=[],
        quote_size="49.80",
        base_size="1",
        best_bid="499",
        best_ask="501",
        is_max=False,
        order_margin_total="25.05",
        preview_id=PREVIEW_ID,
        margin_ratio_data={
            "current_margin_ratio": "2",
            "projected_margin_ratio": "1.5",
        },
    )


class _RestClient:
    def __init__(self) -> None:
        self.preview_response = _preview_response()
        self.create_response = SimpleNamespace(
            success=True,
            success_response=SimpleNamespace(
                order_id=EXCHANGE_ORDER_ID,
                product_id=PRODUCT_ID,
                side="BUY",
                client_order_id=CLIENT_ORDER_ID,
            ),
        )
        self.order_response = {
            "order": {
                "order_id": EXCHANGE_ORDER_ID,
                "client_order_id": CLIENT_ORDER_ID,
                "product_id": PRODUCT_ID,
                "side": "BUY",
                "status": "OPEN",
            }
        }
        self.cancel_response = SimpleNamespace(
            results=[
                SimpleNamespace(
                    success=True,
                    order_id=EXCHANGE_ORDER_ID,
                )
            ]
        )
        self.preview_calls: list[dict[str, object]] = []
        self.create_calls: list[dict[str, object]] = []

    def preview_futures_order(self, **kwargs):
        self.preview_calls.append(dict(kwargs))
        kwargs["before_sdk_call"]()
        return self.preview_response

    def create_futures_order(self, **kwargs):
        self.create_calls.append(dict(kwargs))
        kwargs["before_sdk_call"]()
        return self.create_response

    def get_order(self, order_id, *, before_sdk_call):
        assert order_id == EXCHANGE_ORDER_ID
        before_sdk_call()
        return deepcopy(self.order_response)

    def cancel_futures_order(self, **kwargs):
        assert kwargs["exchange_order_id"] == EXCHANGE_ORDER_ID
        kwargs["before_sdk_call"]()
        return self.cancel_response


def test_dynamic_preview_and_create_use_identical_backend_owned_product_terms(
    monkeypatch,
) -> None:
    rest = _RestClient()
    scopes: list[str] = []
    monkeypatch.setattr(
        "application.admin_api.operator_futures_product_ticket_runtime."
        "canonical_coinbase_execution_scope",
        lambda scope: _Scope(scopes, scope),
    )
    executor = AdminApiFuturesProductTicketExchangeExecutor(
        rest_client=rest
    )
    claims: list[str] = []

    preview = executor.preview(
        _candidate(),
        before_call=lambda: claims.append("preview"),
    )
    created = executor.create(
        candidate=_candidate(),
        client_order_id=CLIENT_ORDER_ID,
        private_preview_id=preview.private_preview_id or "",
        before_call=lambda: claims.append("create"),
    )

    assert preview.outcome is AdminFuturesManualCallOutcome.ACCEPTED
    assert created.outcome is AdminFuturesManualCallOutcome.ACCEPTED
    assert claims == ["preview", "create"]
    assert scopes == [
        "canonical_admin_api_futures_preview",
        "canonical_admin_api_futures_place",
    ]
    for call in (rest.preview_calls[0], rest.create_calls[0]):
        assert call["product_id"] == PRODUCT_ID
        assert call["side"] == "BUY"
        assert call["order_configuration"] == {
            "limit_limit_gtc": {
                "base_size": "1",
                "limit_price": "498",
                "post_only": True,
            }
        }
    assert rest.create_calls[0]["preview_id"] == PREVIEW_ID
    assert PREVIEW_ID not in repr(preview.public_evidence)
    assert EXCHANGE_ORDER_ID not in repr(created.public_evidence)


def test_dynamic_exact_child_reconcile_and_cancel_preserve_identity(
    monkeypatch,
) -> None:
    rest = _RestClient()
    scopes: list[str] = []
    monkeypatch.setattr(
        "application.admin_api.operator_futures_product_ticket_runtime."
        "canonical_coinbase_execution_scope",
        lambda scope: _Scope(scopes, scope),
    )
    executor = AdminApiFuturesProductTicketExchangeExecutor(
        rest_client=rest
    )

    reconciled = executor.reconcile(
        candidate=_candidate(),
        client_order_id=CLIENT_ORDER_ID,
        private_exchange_order_id=EXCHANGE_ORDER_ID,
        before_call=lambda: None,
    )
    cancelled = executor.cancel(
        candidate=_candidate(),
        client_order_id=CLIENT_ORDER_ID,
        private_exchange_order_id=EXCHANGE_ORDER_ID,
        before_call=lambda: None,
    )

    assert reconciled.outcome is AdminFuturesManualCallOutcome.ACCEPTED
    assert reconciled.order_status == "OPEN"
    assert reconciled.authoritatively_nonterminal is True
    assert cancelled.outcome is AdminFuturesManualCallOutcome.ACCEPTED
    assert scopes == ["canonical_admin_api_futures_cancel"]
    assert EXCHANGE_ORDER_ID not in repr(reconciled.public_evidence)
    assert EXCHANGE_ORDER_ID not in repr(cancelled.public_evidence)


def test_dynamic_executor_preserves_backend_owned_sell_side() -> None:
    rest = _RestClient()
    rest.create_response.success_response.side = "SELL"
    rest.order_response["order"]["side"] = "SELL"
    candidate = {
        **_candidate(),
        "side": "SELL",
        "source_client_order_id": "source-order-id",
        "root_client_order_id": "source-order-id",
        "follow_up_intent_id": "00000000-0000-4000-8000-000000000502",
        "trigger_evidence_sha256": "b" * 64,
        "position_side": "LONG",
        "position_contract_count": "1",
    }
    executor = AdminApiFuturesProductTicketExchangeExecutor(
        rest_client=rest
    )

    preview = executor.preview(
        candidate,
        before_call=lambda: None,
    )
    created = executor.create(
        candidate=candidate,
        client_order_id=CLIENT_ORDER_ID,
        private_preview_id=preview.private_preview_id or "",
        before_call=lambda: None,
    )
    reconciled = executor.reconcile(
        candidate=candidate,
        client_order_id=CLIENT_ORDER_ID,
        private_exchange_order_id=EXCHANGE_ORDER_ID,
        before_call=lambda: None,
    )

    assert preview.outcome is AdminFuturesManualCallOutcome.ACCEPTED
    assert created.outcome is AdminFuturesManualCallOutcome.ACCEPTED
    assert reconciled.outcome is AdminFuturesManualCallOutcome.ACCEPTED
    assert rest.preview_calls[0]["side"] == "SELL"
    assert rest.create_calls[0]["side"] == "SELL"
    assert created.public_evidence["side"] == "SELL"
    assert reconciled.public_evidence["side"] == "SELL"


def test_dynamic_executor_rejects_unbound_sell_before_call() -> None:
    rest = _RestClient()
    executor = AdminApiFuturesProductTicketExchangeExecutor(
        rest_client=rest
    )

    result = executor.preview(
        {**_candidate(), "side": "SELL"},
        before_call=lambda: None,
    )

    assert result.outcome is AdminFuturesManualCallOutcome.UNKNOWN
    assert rest.preview_calls == []


def test_dynamic_executor_classifies_documented_response_schema_drift() -> None:
    rest = _RestClient()
    del rest.preview_response.commission_total
    executor = AdminApiFuturesProductTicketExchangeExecutor(
        rest_client=rest
    )

    result = executor.preview(
        _candidate(),
        before_call=lambda: None,
    )

    assert result.outcome is AdminFuturesManualCallOutcome.UNKNOWN
    assert result.diagnostic_code == (
        "operator_futures_product_ticket_preview_schema_invalid"
    )
    assert result.public_evidence == {
        "raw_response_included": False,
        "private_identifiers_included": False,
    }


def test_dynamic_executor_rejects_unconfigured_product_before_call() -> None:
    rest = _RestClient()
    candidate = {**_candidate(), "product_id": "OTHER-20DEC30-CDE"}
    executor = AdminApiFuturesProductTicketExchangeExecutor(
        rest_client=rest
    )

    result = executor.preview(candidate, before_call=lambda: None)

    assert result.outcome is AdminFuturesManualCallOutcome.UNKNOWN
    assert rest.preview_calls == []


def test_default_client_resolution_is_deferred_until_exchange_use() -> None:
    resolutions: list[str] = []
    rest = _RestClient()
    deferred = _DeferredFuturesDefaultRestClient(
        resolver=lambda: resolutions.append("resolved") or rest
    )

    assert resolutions == []
    deferred.get_order(
        EXCHANGE_ORDER_ID,
        before_sdk_call=lambda: None,
    )
    assert resolutions == ["resolved"]


class _Scope:
    def __init__(self, calls: list[str], scope: str) -> None:
        self.calls = calls
        self.scope = scope

    def __enter__(self):
        self.calls.append(self.scope)

    def __exit__(self, *_args):
        return False
