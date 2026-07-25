from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from application.admin_api.operator_futures_manual_runtime import (
    AdminApiFuturesManualExchangeExecutor,
)
from core.enums import AdminFuturesManualCallOutcome


PRODUCT_ID = "AVP-20DEC30-CDE"
CLIENT_ORDER_ID = "futures-goal-10-child"
EXCHANGE_ORDER_ID = "private-exchange-order-id"
PREVIEW_ID = "private-preview-id"


def _candidate() -> dict[str, str]:
    return {
        "product_id": PRODUCT_ID,
        "side": "BUY",
        "order_type": "LIMIT_GTC",
        "post_only": "true",
        "contract_count": "1",
        "contract_size": "10",
        "limit_price": "6.90",
        "opening_reference_notional_usdc": "69.20",
        "maximum_exposure_reference_notional_usdc": "69.20",
        "buffered_close_reference_notional_usdc": "83.04",
        "branch_turnover_reference_notional_usdc": "152.24",
        "opening_cap_usdc": "100",
        "exposure_cap_usdc": "150",
        "turnover_cap_usdc": "300",
    }


def _preview_response(*, errs=None, warning=None):
    return SimpleNamespace(
        order_total="69.00",
        commission_total="0.20",
        errs=[] if errs is None else errs,
        warning=[] if warning is None else warning,
        quote_size="69.00",
        base_size="1",
        best_bid="6.91",
        best_ask="6.92",
        is_max=False,
        order_margin_total="10.00",
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
                "filled_size": "0",
            }
        }
        self.cancel_response = SimpleNamespace(
            results=[
                SimpleNamespace(
                    success=True,
                    order_id=EXCHANGE_ORDER_ID,
                    failure_reason="",
                )
            ]
        )
        self.preview_calls: list[dict[str, object]] = []
        self.create_calls: list[dict[str, object]] = []
        self.order_calls: list[dict[str, object]] = []
        self.cancel_calls: list[dict[str, object]] = []

    def preview_futures_order(self, **kwargs):
        self.preview_calls.append(dict(kwargs))
        kwargs["before_sdk_call"]()
        return self.preview_response

    def create_futures_order(self, **kwargs):
        self.create_calls.append(dict(kwargs))
        kwargs["before_sdk_call"]()
        return self.create_response

    def get_order(self, order_id, *, before_sdk_call):
        self.order_calls.append(
            {"order_id": order_id, "before_sdk_call": before_sdk_call}
        )
        before_sdk_call()
        return deepcopy(self.order_response)

    def cancel_futures_order(self, **kwargs):
        self.cancel_calls.append(dict(kwargs))
        kwargs["before_sdk_call"]()
        return self.cancel_response


def test_preview_validates_raw_sdk_envelope_and_withholds_private_identity(
    monkeypatch,
) -> None:
    rest = _RestClient()
    executor = AdminApiFuturesManualExchangeExecutor(rest_client=rest)
    scopes: list[str] = []
    monkeypatch.setattr(
        "application.admin_api.operator_futures_manual_runtime."
        "canonical_coinbase_execution_scope",
        lambda scope: _Scope(scopes, scope),
    )
    claims: list[str] = []

    result = executor.preview(
        _candidate(),
        before_call=lambda: claims.append("preview_claimed"),
    )

    assert result.outcome is AdminFuturesManualCallOutcome.ACCEPTED
    assert result.private_preview_id == PREVIEW_ID
    assert result.preview_id_sha256 is not None
    assert len(result.preview_id_sha256) == 64
    assert PREVIEW_ID not in repr(result.public_evidence)
    assert result.public_evidence["candidate_binding"]["contract_count"] == "1"
    assert claims == ["preview_claimed"]
    assert scopes == ["canonical_admin_api_futures_preview"]
    assert len(rest.preview_calls) == 1
    request = {
        key: value
        for key, value in rest.preview_calls[0].items()
        if key != "before_sdk_call"
    }
    assert request == {
        "product_id": PRODUCT_ID,
        "side": "BUY",
        "order_configuration": {
            "limit_limit_gtc": {
                "base_size": "1",
                "limit_price": "6.90",
                "post_only": True,
            }
        },
    }


def test_rejected_preview_is_terminal_and_never_exposes_documented_enum(
    monkeypatch,
) -> None:
    rest = _RestClient()
    rest.preview_response = _preview_response(
        errs=["PREVIEW_INVALID_MARGIN_HEALTH"]
    )
    executor = AdminApiFuturesManualExchangeExecutor(rest_client=rest)
    monkeypatch.setattr(
        "application.admin_api.operator_futures_manual_runtime."
        "canonical_coinbase_execution_scope",
        lambda scope: _Scope([], scope),
    )

    result = executor.preview(_candidate(), before_call=lambda: None)

    assert result.outcome is AdminFuturesManualCallOutcome.REJECTED
    assert result.private_preview_id is None
    assert result.preview_id_sha256 is None
    assert result.diagnostic_code == (
        "operator_futures_manual_preview_exchange_rejected"
    )
    assert "PREVIEW_INVALID_MARGIN_HEALTH" not in repr(result)


def test_create_is_preview_bound_and_returns_private_exchange_id_ephemerally(
    monkeypatch,
) -> None:
    rest = _RestClient()
    executor = AdminApiFuturesManualExchangeExecutor(rest_client=rest)
    scopes: list[str] = []
    monkeypatch.setattr(
        "application.admin_api.operator_futures_manual_runtime."
        "canonical_coinbase_execution_scope",
        lambda scope: _Scope(scopes, scope),
    )
    claims: list[str] = []

    result = executor.create(
        candidate=_candidate(),
        client_order_id=CLIENT_ORDER_ID,
        private_preview_id=PREVIEW_ID,
        before_call=lambda: claims.append("create_claimed"),
    )

    assert result.outcome is AdminFuturesManualCallOutcome.ACCEPTED
    assert result.private_exchange_order_id == EXCHANGE_ORDER_ID
    assert result.exchange_order_id_sha256 is not None
    assert len(result.exchange_order_id_sha256) == 64
    assert EXCHANGE_ORDER_ID not in repr(result.public_evidence)
    assert claims == ["create_claimed"]
    assert scopes == ["canonical_admin_api_futures_place"]
    request = {
        key: value
        for key, value in rest.create_calls[0].items()
        if key != "before_sdk_call"
    }
    assert request == {
        "client_order_id": CLIENT_ORDER_ID,
        "product_id": PRODUCT_ID,
        "side": "BUY",
        "order_configuration": {
            "limit_limit_gtc": {
                "base_size": "1",
                "limit_price": "6.90",
                "post_only": True,
            }
        },
        "preview_id": PREVIEW_ID,
    }


def test_exact_order_reconciliation_and_cancel_use_one_exchange_identity(
    monkeypatch,
) -> None:
    rest = _RestClient()
    executor = AdminApiFuturesManualExchangeExecutor(rest_client=rest)
    scopes: list[str] = []
    monkeypatch.setattr(
        "application.admin_api.operator_futures_manual_runtime."
        "canonical_coinbase_execution_scope",
        lambda scope: _Scope(scopes, scope),
    )
    reconcile_claims: list[str] = []
    cancel_claims: list[str] = []

    reconciliation = executor.reconcile(
        client_order_id=CLIENT_ORDER_ID,
        private_exchange_order_id=EXCHANGE_ORDER_ID,
        before_call=lambda: reconcile_claims.append("reconcile_claimed"),
    )
    cancellation = executor.cancel(
        client_order_id=CLIENT_ORDER_ID,
        private_exchange_order_id=EXCHANGE_ORDER_ID,
        before_call=lambda: cancel_claims.append("cancel_claimed"),
    )

    assert reconciliation.outcome is AdminFuturesManualCallOutcome.ACCEPTED
    assert reconciliation.order_status == "OPEN"
    assert reconciliation.authoritatively_nonterminal is True
    assert EXCHANGE_ORDER_ID not in repr(reconciliation.public_evidence)
    assert cancellation.outcome is AdminFuturesManualCallOutcome.ACCEPTED
    assert cancellation.exchange_order_id_sha256 == (
        reconciliation.exchange_order_id_sha256
    )
    assert EXCHANGE_ORDER_ID not in repr(cancellation.public_evidence)
    assert reconcile_claims == ["reconcile_claimed"]
    assert cancel_claims == ["cancel_claimed"]
    assert scopes == ["canonical_admin_api_futures_cancel"]
    assert [call["order_id"] for call in rest.order_calls] == [
        EXCHANGE_ORDER_ID
    ]
    assert [
        call["exchange_order_id"] for call in rest.cancel_calls
    ] == [EXCHANGE_ORDER_ID]


def test_mismatched_success_and_unknown_exceptions_fail_closed(
    monkeypatch,
) -> None:
    rest = _RestClient()
    rest.create_response.success_response.client_order_id = "different-child"
    executor = AdminApiFuturesManualExchangeExecutor(rest_client=rest)
    monkeypatch.setattr(
        "application.admin_api.operator_futures_manual_runtime."
        "canonical_coinbase_execution_scope",
        lambda scope: _Scope([], scope),
    )
    mismatched = executor.create(
        candidate=_candidate(),
        client_order_id=CLIENT_ORDER_ID,
        private_preview_id=PREVIEW_ID,
        before_call=lambda: None,
    )
    assert mismatched.outcome is AdminFuturesManualCallOutcome.UNKNOWN
    assert mismatched.private_exchange_order_id is None

    def unknown_preview(**_kwargs):
        raise RuntimeError("withheld private exception text")

    rest.preview_futures_order = unknown_preview
    unknown = executor.preview(_candidate(), before_call=lambda: None)
    assert unknown.outcome is AdminFuturesManualCallOutcome.UNKNOWN
    assert "withheld private exception text" not in repr(unknown)


class _Scope:
    def __init__(self, calls: list[str], scope: str) -> None:
        self.calls = calls
        self.scope = scope

    def __enter__(self):
        self.calls.append(self.scope)
        return None

    def __exit__(self, *_args):
        return False
