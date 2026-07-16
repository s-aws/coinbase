from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from types import SimpleNamespace
from typing import Any

import pytest

from application.admin_api.futures_terminal_roundtrip_coinbase import (
    SLICE3_COINBASE_PRODUCT_ID,
    Slice3CoinbaseAccountBinding,
    Slice3CoinbasePortError,
    Slice3CoinbaseReadError,
    StrictSlice3CoinbasePort,
    sanitized_mutation_evidence,
)
from application.admin_api.futures_terminal_roundtrip import (
    Slice3MutationOutcome,
)
from core.enums import AdminFuturesPositionSide, OrderSide, OrderStatus


NOW = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
ORDER_LOOKUP_START = NOW - timedelta(minutes=1)
ORDER_LOOKUP_END = NOW + timedelta(minutes=5)
CREATE_CLIENT_ORDER_ID = "00000000-0000-4000-8000-000000000311"
CLOSE_CLIENT_ORDER_ID = "00000000-0000-4000-8000-000000000312"
PREVIEW_ID = "preview-private-synthetic-port"
CREATE_EXCHANGE_ORDER_ID = "exchange-private-synthetic-create"
CLOSE_EXCHANGE_ORDER_ID = "exchange-private-synthetic-close"
LIMIT_PRICE = "6.40"
PORTFOLIO_ID = "portfolio-private-synthetic-port"
SESSION_BINDING_TOKEN = "00000000-0000-4000-8000-000000000313"
SHA_A = "a" * 64
SHA_B = "b" * 64
OPENING_CONFIGURATION = {
    "limit_limit_gtc": {
        "base_size": "1",
        "limit_price": LIMIT_PRICE,
        "post_only": True,
    }
}


class FakeDelegate:
    def __init__(self) -> None:
        adapter = SimpleNamespace(
            max_retries=SimpleNamespace(
                total=0,
                connect=None,
                read=None,
                redirect=None,
                status=None,
                other=None,
            )
        )
        self._client = SimpleNamespace(
            base_url="api.coinbase.com",
            timeout=30,
            rate_limit_headers=False,
            session=SimpleNamespace(
                adapters={
                    "https://": adapter,
                    "http://": adapter,
                },
                max_redirects=0,
                trust_env=False,
                verify=(
                    "/usr/local/lib/python3.13/site-packages/certifi/cacert.pem"
                ),
                proxies={},
            )
        )
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.create_response: object = {
            "success": True,
            "success_response": {
                "order_id": CREATE_EXCHANGE_ORDER_ID,
                "client_order_id": CREATE_CLIENT_ORDER_ID,
                "product_id": SLICE3_COINBASE_PRODUCT_ID,
                "side": "BUY",
                "private_field": "PRIVATE_CREATE_RESPONSE",
            },
        }
        self.cancel_response: object = {
            "outcome": "succeeded",
            "succeeded": True,
            "explicit_rejection": False,
            "identity_match": True,
            "result_count": 1,
            "operator_identity_key": "client_order_id",
            "operator_identity_value": CREATE_CLIENT_ORDER_ID,
            "exchange_order_id_evidence_only": True,
            "exchange_order_id": CREATE_EXCHANGE_ORDER_ID,
            "submitted_identity_key": "exchange_order_id",
            "failure_reasons": [],
        }
        self.close_response: object = {
            "success": True,
            "success_response": {
                "order_id": CLOSE_EXCHANGE_ORDER_ID,
                "client_order_id": CLOSE_CLIENT_ORDER_ID,
                "product_id": SLICE3_COINBASE_PRODUCT_ID,
                "side": "SELL",
                "private_field": "PRIVATE_CLOSE_RESPONSE",
            },
        }
        self.orders_response: object = {
            "orders": [],
            "has_next": False,
            "cursor": "",
        }
        self.orders_response_queue: list[object] = []
        self.positions_response: object = {"positions": []}
        self.market_response: object = {
            "pricebooks": [
                {
                    "product_id": SLICE3_COINBASE_PRODUCT_ID,
                    "bids": [{"price": "6.39", "size": "2"}],
                    "asks": [{"price": "6.41", "size": "3"}],
                    "time": NOW.isoformat().replace("+00:00", "Z"),
                }
            ]
        }
        self.margin_response: object = _margin_snapshot()

    @staticmethod
    def _return_or_raise(value: object) -> object:
        if isinstance(value, Exception):
            raise value
        return value

    def create_order(self, **kwargs: object) -> object:
        self.calls.append(("create_order", dict(kwargs)))
        return self._return_or_raise(self.create_response)

    def cancel_order(self, **kwargs: object) -> object:
        self.calls.append(("cancel_order", dict(kwargs)))
        return self._return_or_raise(self.cancel_response)

    def close_position(self, **kwargs: object) -> object:
        self.calls.append(("close_position", dict(kwargs)))
        return self._return_or_raise(self.close_response)

    def list_orders(self, **kwargs: object) -> object:
        self.calls.append(("list_orders", dict(kwargs)))
        response = (
            self.orders_response_queue.pop(0)
            if self.orders_response_queue
            else self.orders_response
        )
        return self._return_or_raise(response)

    def list_futures_positions(self) -> object:
        self.calls.append(("list_futures_positions", {}))
        return self._return_or_raise(self.positions_response)

    def get_futures_margin_collateral_snapshot(self) -> object:
        self.calls.append(("get_futures_margin_collateral_snapshot", {}))
        return self._return_or_raise(self.margin_response)

    def get_best_bid_ask(self, **kwargs: object) -> object:
        self.calls.append(("get_best_bid_ask", dict(kwargs)))
        return self._return_or_raise(self.market_response)

    def cancel_orders(self, **kwargs: object) -> object:
        self.calls.append(("forbidden_cancel_orders", dict(kwargs)))
        raise AssertionError("raw cancel fallback must not run")

    def cancel_order_by_exchange_order_id(self, **kwargs: object) -> object:
        self.calls.append(("forbidden_cancel_order_by_exchange_order_id", dict(kwargs)))
        raise AssertionError("exchange-id fallback must not run")

    def reduce_position(self, **kwargs: object) -> object:
        self.calls.append(("forbidden_reduce_position", dict(kwargs)))
        raise AssertionError("reduce must not run")


def _account_binding() -> Slice3CoinbaseAccountBinding:
    return Slice3CoinbaseAccountBinding.build(
        portfolio_id=PORTFOLIO_ID,
        session_binding_token=SESSION_BINDING_TOKEN,
        permission_evidence_sha256=SHA_A,
        portfolio_catalog_sha256=SHA_B,
    )


def _port(
    delegate: FakeDelegate,
    *,
    order_lookup_start_at: datetime = ORDER_LOOKUP_START,
    order_lookup_end_at: datetime = ORDER_LOOKUP_END,
) -> StrictSlice3CoinbasePort:
    account_binding = _account_binding()
    return StrictSlice3CoinbasePort(
        delegate,
        create_client_order_id=CREATE_CLIENT_ORDER_ID,
        close_client_order_id=CLOSE_CLIENT_ORDER_ID,
        preview_id=PREVIEW_ID,
        limit_price=LIMIT_PRICE,
        contract_size="10",
        order_lookup_start_at=order_lookup_start_at,
        order_lookup_end_at=order_lookup_end_at,
        account_binding=account_binding,
        expected_portfolio_id_sha256=hashlib.sha256(
            PORTFOLIO_ID.encode("utf-8")
        ).hexdigest(),
        expected_permission_evidence_sha256=SHA_A,
        expected_portfolio_catalog_sha256=SHA_B,
        expected_adapter_evidence_sha256=(account_binding.adapter_evidence_sha256),
    )


def _create(port: StrictSlice3CoinbasePort):  # type: ignore[no-untyped-def]
    return port.create_order(
        client_order_id=CREATE_CLIENT_ORDER_ID,
        product_id=SLICE3_COINBASE_PRODUCT_ID,
        side="BUY",
        order_configuration=deepcopy(OPENING_CONFIGURATION),
        preview_id=PREVIEW_ID,
    )


def _order_row(
    *,
    client_order_id: str = CREATE_CLIENT_ORDER_ID,
    exchange_order_id: str = CREATE_EXCHANGE_ORDER_ID,
    side: str = "BUY",
    configuration: dict[str, object] | None = None,
    status: str = "OPEN",
    filled_size: str = "0.25",
    filled_value: str = "16.00",
    number_of_fills: object = "1",
    total_fees: str = "0.02",
) -> dict[str, object]:
    return {
        "order_id": exchange_order_id,
        "client_order_id": client_order_id,
        "product_id": SLICE3_COINBASE_PRODUCT_ID,
        "side": side,
        "status": status,
        "order_configuration": configuration or deepcopy(OPENING_CONFIGURATION),
        "filled_size": filled_size,
        "filled_value": filled_value,
        "number_of_fills": number_of_fills,
        "total_fees": total_fees,
        "withheld_private_order_field": "PRIVATE_ORDER_RESPONSE",
    }


def _margin_snapshot() -> dict[str, object]:
    return {
        "status": "ready",
        "account_family": "coinbase_futures_us_cfm",
        "source": "backend_rest_client",
        "source_read_attempts": {
            "get_futures_balance_summary": 1,
            "get_intraday_margin_setting": 1,
            "get_current_margin_window": 2,
            "list_futures_sweeps": 1,
        },
        "balance_summary": {
            "available_margin": {"value": "250.00", "currency": "USD"},
            "total_usd_balance": {"value": "500.00", "currency": "USD"},
            "initial_margin": {"value": "40.00", "currency": "USD"},
            "liquidation_threshold": {
                "value": "80.00",
                "currency": "USD",
            },
            "withheld_private_balance": {"value": "999", "currency": "USD"},
        },
        "intraday_margin_setting": {
            "setting": "INTRADAY_MARGIN_SETTING_INTRADAY",
        },
        "current_margin_windows": [
            {
                "profile": "MARGIN_PROFILE_TYPE_RETAIL_REGULAR",
                "status": "ready",
                "margin_window": {
                    "margin_window_type": "MARGIN_WINDOW_TYPE_UNSPECIFIED",
                },
                "is_intraday_margin_killswitch_enabled": False,
                "is_intraday_margin_enrollment_killswitch_enabled": False,
            },
            {
                "profile": "MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1",
                "status": "ready",
                "margin_window": {
                    "margin_window_type": "MARGIN_WINDOW_TYPE_INTRADAY",
                },
                "is_intraday_margin_killswitch_enabled": False,
                "is_intraday_margin_enrollment_killswitch_enabled": False,
            },
        ],
        "futures_sweeps": [],
        "errors": [],
        "intx_applicability": "not_applicable_us_account",
        "private_profile_id": "PRIVATE_PROFILE",
    }


def test_port_is_dormant_injected_and_repr_does_not_disclose_bindings() -> None:
    delegate = FakeDelegate()
    port = _port(delegate)

    assert delegate.calls == []

    assert not hasattr(port, "reduce_position")
    rendered = repr(port)
    assert CREATE_CLIENT_ORDER_ID not in rendered
    assert CLOSE_CLIENT_ORDER_ID not in rendered
    assert PREVIEW_ID not in rendered


def test_active_transition_statuses_are_canonical_core_enums() -> None:
    assert OrderStatus.QUEUED.value == "QUEUED"
    assert OrderStatus.CANCEL_QUEUED.value == "CANCEL_QUEUED"
    assert OrderStatus.EDIT_QUEUED.value == "EDIT_QUEUED"


@pytest.mark.parametrize(
    ("lookup_start", "lookup_end"),
    [
        (ORDER_LOOKUP_START.replace(tzinfo=None), ORDER_LOOKUP_END),
        (ORDER_LOOKUP_START, ORDER_LOOKUP_START),
        (ORDER_LOOKUP_START, ORDER_LOOKUP_START + timedelta(minutes=15, microseconds=1)),
    ],
)
def test_port_rejects_unsealed_or_overwide_order_lookup_window(
    lookup_start: datetime,
    lookup_end: datetime,
) -> None:
    delegate = FakeDelegate()

    with pytest.raises(
        Slice3CoinbasePortError,
        match="slice3_coinbase_order_lookup_window_invalid",
    ):
        _port(
            delegate,
            order_lookup_start_at=lookup_start,
            order_lookup_end_at=lookup_end,
        )

    assert delegate.calls == []


def test_port_binds_same_default_account_session_and_rechecks_before_access() -> None:
    delegate = FakeDelegate()
    account_binding = _account_binding()
    evidence = json.dumps(account_binding.sanitized_evidence(), sort_keys=True)

    assert PORTFOLIO_ID not in evidence
    assert SESSION_BINDING_TOKEN not in evidence
    assert (
        account_binding.portfolio_id_sha256
        == hashlib.sha256(PORTFOLIO_ID.encode("utf-8")).hexdigest()
    )
    assert account_binding.credential_binding == {
        "source": "secrets_manager",
        "secret_id": "coinbase",
        "region": "us-east-1",
    }

    with pytest.raises(Slice3CoinbasePortError, match="account_binding_invalid"):
        StrictSlice3CoinbasePort(
            delegate,
            create_client_order_id=CREATE_CLIENT_ORDER_ID,
            close_client_order_id=CLOSE_CLIENT_ORDER_ID,
            preview_id=PREVIEW_ID,
            limit_price=LIMIT_PRICE,
            contract_size="10",
            order_lookup_start_at=ORDER_LOOKUP_START,
            order_lookup_end_at=ORDER_LOOKUP_END,
            account_binding=account_binding,
            expected_portfolio_id_sha256="c" * 64,
            expected_permission_evidence_sha256=SHA_A,
            expected_portfolio_catalog_sha256=SHA_B,
            expected_adapter_evidence_sha256=(account_binding.adapter_evidence_sha256),
        )
    assert delegate.calls == []

    port = _port(delegate)
    port._delegate = FakeDelegate()  # noqa: SLF001 - adversarial drift proof
    with pytest.raises(Slice3CoinbasePortError, match="account_binding_invalid"):
        _create(port)
    assert delegate.calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("total", 1),
        ("connect", 1),
        ("read", 1),
        ("redirect", 1),
        ("status", 1),
        ("other", 1),
        ("max_redirects", 1),
        ("base_url", "example.invalid"),
        ("timeout", None),
        ("trust_env", True),
        ("verify", True),
        ("proxies", {"https": "http://127.0.0.1:1"}),
        ("adapter_extra", object()),
        ("session_identity", object()),
    ],
)
def test_port_rechecks_zero_retry_redirect_transport_before_every_call(
    field: str,
    value: object,
) -> None:
    delegate = FakeDelegate()
    port = _port(delegate)
    if field == "max_redirects":
        delegate._client.session.max_redirects = value
    elif field in {"base_url", "timeout"}:
        setattr(delegate._client, field, value)
    elif field in {"trust_env", "verify", "proxies"}:
        setattr(delegate._client.session, field, value)
    elif field == "adapter_extra":
        delegate._client.session.adapters["https://api.coinbase.com"] = value
    elif field == "session_identity":
        delegate._client.session = SimpleNamespace(
            adapters=delegate._client.session.adapters,
            max_redirects=0,
            trust_env=False,
            verify=(
                "/usr/local/lib/python3.13/site-packages/certifi/cacert.pem"
            ),
            proxies={},
        )
    else:
        retry = delegate._client.session.adapters["https://"].max_retries
        setattr(retry, field, value)

    with pytest.raises(Slice3CoinbasePortError, match="transport_policy_invalid"):
        _create(port)
    assert delegate.calls == []


def test_port_rejects_delegate_without_provable_transport_policy() -> None:
    delegate = FakeDelegate()
    del delegate._client

    with pytest.raises(Slice3CoinbasePortError, match="transport_policy_invalid"):
        _port(delegate)
    assert delegate.calls == []


def test_create_submits_exact_preview_bound_post_only_gtc_once() -> None:
    delegate = FakeDelegate()
    port = _port(delegate)

    result = _create(port)

    assert result.outcome is Slice3MutationOutcome.ACCEPTED
    assert result.reason_code == "create_accepted"
    assert result.exchange_order_id == CREATE_EXCHANGE_ORDER_ID
    assert delegate.calls == [
        (
            "create_order",
            {
                "client_order_id": CREATE_CLIENT_ORDER_ID,
                "product_id": SLICE3_COINBASE_PRODUCT_ID,
                "side": "BUY",
                "order_configuration": OPENING_CONFIGURATION,
                "preview_id": PREVIEW_ID,
            },
        )
    ]
    sanitized = sanitized_mutation_evidence(result)
    assert sanitized == {
        "schema_version": "slice3-coinbase-mutation-result-v1",
        "outcome": "accepted",
        "reason_code": "create_accepted",
        "exchange_order_id_present": True,
        "raw_response_included": False,
        "identifier_values_included": False,
    }
    assert CREATE_EXCHANGE_ORDER_ID not in json.dumps(sanitized)
    with pytest.raises(Slice3CoinbasePortError, match="create_attempt_consumed"):
        _create(port)
    assert len(delegate.calls) == 1


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"client_order_id": "wrong"}, "create_scope_invalid"),
        ({"product_id": "BTC-USD"}, "create_scope_invalid"),
        ({"side": "SELL"}, "create_scope_invalid"),
        ({"preview_id": "wrong"}, "create_scope_invalid"),
        (
            {
                "order_configuration": {
                    "limit_limit_gtc": {
                        "base_size": "2",
                        "limit_price": LIMIT_PRICE,
                        "post_only": True,
                    }
                }
            },
            "create_scope_invalid",
        ),
        (
            {
                "order_configuration": {
                    "limit_limit_gtc": {
                        "base_size": "1",
                        "limit_price": LIMIT_PRICE,
                        "post_only": False,
                    }
                }
            },
            "create_scope_invalid",
        ),
    ],
)
def test_create_scope_drift_is_blocked_before_delegate(
    overrides: dict[str, object],
    reason: str,
) -> None:
    delegate = FakeDelegate()
    port = _port(delegate)
    kwargs: dict[str, object] = {
        "client_order_id": CREATE_CLIENT_ORDER_ID,
        "product_id": SLICE3_COINBASE_PRODUCT_ID,
        "side": "BUY",
        "order_configuration": deepcopy(OPENING_CONFIGURATION),
        "preview_id": PREVIEW_ID,
    }
    kwargs.update(overrides)

    with pytest.raises(Slice3CoinbasePortError, match=reason):
        port.create_order(**kwargs)

    assert delegate.calls == []


@pytest.mark.parametrize(
    ("response", "outcome", "reason"),
    [
        (
            {"success": False, "failure_reason": "PRIVATE_REJECTION_TEXT"},
            Slice3MutationOutcome.REJECTED,
            "create_explicitly_rejected",
        ),
        (
            {"success": True, "success_response": {"order_id": "wrong"}},
            Slice3MutationOutcome.UNKNOWN,
            "create_outcome_unknown",
        ),
        (
            RuntimeError("PRIVATE_CREATE_EXCEPTION"),
            Slice3MutationOutcome.UNKNOWN,
            "create_outcome_unknown",
        ),
    ],
)
def test_create_response_is_allowlisted_and_exception_text_is_withheld(
    response: object,
    outcome: Slice3MutationOutcome,
    reason: str,
) -> None:
    delegate = FakeDelegate()
    delegate.create_response = response

    result = _create(_port(delegate))

    assert result.outcome is outcome
    assert result.reason_code == reason
    assert "PRIVATE" not in json.dumps(sanitized_mutation_evidence(result))


def test_cancel_uses_exact_verified_pair_once_without_fallback() -> None:
    delegate = FakeDelegate()
    port = _port(delegate)

    result = port.cancel_order(
        client_order_id=CREATE_CLIENT_ORDER_ID,
        verified_exchange_order_id=CREATE_EXCHANGE_ORDER_ID,
    )

    assert result.outcome is Slice3MutationOutcome.ACCEPTED
    assert result.reason_code == "cancel_accepted"
    assert result.exchange_order_id == CREATE_EXCHANGE_ORDER_ID
    assert delegate.calls == [
        (
            "cancel_order",
            {
                "client_order_id": CREATE_CLIENT_ORDER_ID,
                "verified_exchange_order_id": CREATE_EXCHANGE_ORDER_ID,
                "return_evidence": True,
            },
        )
    ]
    with pytest.raises(Slice3CoinbasePortError, match="cancel_attempt_consumed"):
        port.cancel_order(
            client_order_id=CREATE_CLIENT_ORDER_ID,
            verified_exchange_order_id=CREATE_EXCHANGE_ORDER_ID,
        )
    assert len(delegate.calls) == 1


@pytest.mark.parametrize(
    ("client_order_id", "exchange_order_id"),
    [
        ("wrong", CREATE_EXCHANGE_ORDER_ID),
        (CREATE_CLIENT_ORDER_ID, ""),
        (CREATE_CLIENT_ORDER_ID, CREATE_CLIENT_ORDER_ID),
    ],
)
def test_cancel_identity_drift_is_blocked_before_delegate(
    client_order_id: str,
    exchange_order_id: str,
) -> None:
    delegate = FakeDelegate()
    port = _port(delegate)

    with pytest.raises(Slice3CoinbasePortError, match="cancel_scope_invalid"):
        port.cancel_order(
            client_order_id=client_order_id,
            verified_exchange_order_id=exchange_order_id,
        )

    assert delegate.calls == []


def test_cancel_malformed_or_exception_response_is_generic_unknown() -> None:
    delegate = FakeDelegate()
    delegate.cancel_response = RuntimeError("PRIVATE_CANCEL_EXCEPTION")
    port = _port(delegate)

    result = port.cancel_order(
        client_order_id=CREATE_CLIENT_ORDER_ID,
        verified_exchange_order_id=CREATE_EXCHANGE_ORDER_ID,
    )

    assert result.outcome is Slice3MutationOutcome.UNKNOWN
    assert result.reason_code == "cancel_outcome_unknown"
    assert "PRIVATE" not in json.dumps(sanitized_mutation_evidence(result))
    assert [name for name, _kwargs in delegate.calls] == ["cancel_order"]


def test_cancel_boolean_result_count_cannot_masquerade_as_one() -> None:
    delegate = FakeDelegate()
    assert isinstance(delegate.cancel_response, dict)
    delegate.cancel_response["result_count"] = True

    result = _port(delegate).cancel_order(
        client_order_id=CREATE_CLIENT_ORDER_ID,
        verified_exchange_order_id=CREATE_EXCHANGE_ORDER_ID,
    )

    assert result.outcome is Slice3MutationOutcome.UNKNOWN
    assert result.reason_code == "cancel_outcome_unknown"


def test_close_uses_distinct_prebound_coid_exact_product_and_bounded_size() -> None:
    delegate = FakeDelegate()
    port = _port(delegate)

    result = port.close_position(
        client_order_id=CLOSE_CLIENT_ORDER_ID,
        product_id=SLICE3_COINBASE_PRODUCT_ID,
        size="1.0",
    )

    assert result.outcome is Slice3MutationOutcome.ACCEPTED
    assert result.reason_code == "close_accepted"
    assert result.exchange_order_id == CLOSE_EXCHANGE_ORDER_ID
    assert delegate.calls == [
        (
            "close_position",
            {
                "client_order_id": CLOSE_CLIENT_ORDER_ID,
                "product_id": SLICE3_COINBASE_PRODUCT_ID,
                "size": "1",
            },
        )
    ]
    assert all(name != "forbidden_reduce_position" for name, _ in delegate.calls)
    with pytest.raises(Slice3CoinbasePortError, match="close_attempt_consumed"):
        port.close_position(
            client_order_id=CLOSE_CLIENT_ORDER_ID,
            product_id=SLICE3_COINBASE_PRODUCT_ID,
            size="1",
        )
    assert len(delegate.calls) == 1


@pytest.mark.parametrize(
    ("client_order_id", "product_id", "size"),
    [
        (CREATE_CLIENT_ORDER_ID, SLICE3_COINBASE_PRODUCT_ID, "1"),
        (CLOSE_CLIENT_ORDER_ID, "BTC-USD", "1"),
        (CLOSE_CLIENT_ORDER_ID, SLICE3_COINBASE_PRODUCT_ID, "0"),
        (CLOSE_CLIENT_ORDER_ID, SLICE3_COINBASE_PRODUCT_ID, "1.0001"),
        (CLOSE_CLIENT_ORDER_ID, SLICE3_COINBASE_PRODUCT_ID, "NaN"),
    ],
)
def test_close_scope_or_size_drift_is_blocked_before_delegate(
    client_order_id: str,
    product_id: str,
    size: str,
) -> None:
    delegate = FakeDelegate()
    port = _port(delegate)

    with pytest.raises(Slice3CoinbasePortError, match="close_scope_invalid"):
        port.close_position(
            client_order_id=client_order_id,
            product_id=product_id,
            size=size,
        )

    assert delegate.calls == []


def test_close_exception_is_generic_unknown_and_consumes_method() -> None:
    delegate = FakeDelegate()
    delegate.close_response = RuntimeError("PRIVATE_CLOSE_EXCEPTION")
    port = _port(delegate)

    result = port.close_position(
        client_order_id=CLOSE_CLIENT_ORDER_ID,
        product_id=SLICE3_COINBASE_PRODUCT_ID,
        size="0.5",
    )

    assert result.outcome is Slice3MutationOutcome.UNKNOWN
    assert result.reason_code == "close_outcome_unknown"
    assert "PRIVATE" not in json.dumps(sanitized_mutation_evidence(result))
    with pytest.raises(Slice3CoinbasePortError, match="close_attempt_consumed"):
        port.close_position(
            client_order_id=CLOSE_CLIENT_ORDER_ID,
            product_id=SLICE3_COINBASE_PRODUCT_ID,
            size="0.5",
        )
    assert len(delegate.calls) == 1


def test_exact_opening_order_lookup_binds_config_fill_and_fees_without_raw_ids() -> (
    None
):
    delegate = FakeDelegate()
    delegate.orders_response = {
        "orders": [_order_row()],
        "has_next": False,
        "cursor": "",
    }
    port = _port(delegate)

    evidence = port.read_exact_order(
        client_order_id=CREATE_CLIENT_ORDER_ID,
        exchange_order_id=CREATE_EXCHANGE_ORDER_ID,
        observed_at=NOW,
    )

    observation = evidence.observation
    assert observation.authoritative is True
    assert observation.pagination_complete is True
    assert observation.product_id == SLICE3_COINBASE_PRODUCT_ID
    assert observation.client_order_id == CREATE_CLIENT_ORDER_ID
    assert observation.exchange_order_id == CREATE_EXCHANGE_ORDER_ID
    assert observation.status is OrderStatus.OPEN
    assert observation.filled_contracts == "0.25"
    assert observation.remaining_contracts == "0.75"
    assert observation.active_order_count == 1
    assert observation.resolution_source.value == "authoritative_order_read"
    assert observation.exact_client_order_match_count == 1
    assert evidence.side is OrderSide.BUY
    assert evidence.filled_value == "16"
    assert evidence.total_fees == "0.02"
    assert evidence.number_of_fills == 1
    assert evidence.side_exact is True
    assert evidence.configuration_exact is True
    assert len(evidence.order_configuration_sha256) == 64
    assert delegate.calls == [
        (
            "list_orders",
            {
                "order_ids": [CREATE_EXCHANGE_ORDER_ID],
                "product_ids": [SLICE3_COINBASE_PRODUCT_ID],
                "limit": 100,
                "product_type": "FUTURE",
            },
        )
    ]
    sanitized = evidence.sanitized_evidence()
    serialized = json.dumps(sanitized, sort_keys=True)
    assert CREATE_CLIENT_ORDER_ID not in serialized
    assert CREATE_EXCHANGE_ORDER_ID not in serialized
    assert "PRIVATE_ORDER_RESPONSE" not in serialized
    assert sanitized["identifier_values_included"] is False
    assert sanitized["raw_response_included"] is False
    assert len(str(sanitized["client_order_id_sha256"])) == 64
    assert len(str(sanitized["exchange_order_id_sha256"])) == 64


def test_order_lookup_allows_only_documented_configuration_superset() -> None:
    delegate = FakeDelegate()
    configuration = deepcopy(OPENING_CONFIGURATION)
    configuration["limit_limit_gtc"].update(  # type: ignore[union-attr]
        quote_size="64.00",
        rfq_disabled=False,
    )
    delegate.orders_response = {
        "orders": [_order_row(configuration=configuration)],
        "has_next": False,
        "cursor": "",
    }

    evidence = _port(delegate).read_exact_order(
        client_order_id=CREATE_CLIENT_ORDER_ID,
        exchange_order_id=CREATE_EXCHANGE_ORDER_ID,
        observed_at=NOW,
    )

    assert evidence.configuration_exact is True
    assert evidence.observation.status is OrderStatus.OPEN


@pytest.mark.parametrize(
    "configuration",
    [
        {
            "limit_limit_gtc": {
                "base_size": "1",
                "limit_price": LIMIT_PRICE,
                "post_only": True,
                "undocumented_field": "PRIVATE",
            }
        },
        {
            "limit_limit_gtc": deepcopy(OPENING_CONFIGURATION["limit_limit_gtc"]),
            "market_market_ioc": {"base_size": "1"},
        },
        {
            "limit_limit_gtc": {
                "base_size": "1",
                "limit_price": LIMIT_PRICE,
                "post_only": True,
                "rfq_disabled": "false",
            }
        },
    ],
)
def test_order_lookup_rejects_undocumented_wrong_branch_or_typed_contradiction(
    configuration: dict[str, object],
) -> None:
    delegate = FakeDelegate()
    delegate.orders_response = {
        "orders": [_order_row(configuration=configuration)],
        "has_next": False,
        "cursor": "",
    }

    with pytest.raises(
        Slice3CoinbaseReadError,
        match="slice3_order_read_unavailable",
    ):
        _port(delegate).read_exact_order(
            client_order_id=CREATE_CLIENT_ORDER_ID,
            exchange_order_id=CREATE_EXCHANGE_ORDER_ID,
            observed_at=NOW,
        )


def test_unknown_create_resolves_exact_client_order_id_from_one_page() -> None:
    delegate = FakeDelegate()
    delegate.orders_response = {
        "orders": [_order_row()],
        "has_next": False,
        "cursor": "",
    }
    port = _port(delegate)

    evidence = port.resolve_exact_order_by_client_order_id(
        client_order_id=CREATE_CLIENT_ORDER_ID,
        observed_at=NOW,
    )

    assert evidence.observation.client_order_id == CREATE_CLIENT_ORDER_ID
    assert evidence.observation.exchange_order_id == CREATE_EXCHANGE_ORDER_ID
    assert evidence.observation.resolution_source.value == (
        "exact_client_order_id_lookup"
    )
    assert evidence.observation.exact_client_order_match_count == 1
    assert delegate.calls == [
        (
            "list_orders",
            {
                "product_ids": [SLICE3_COINBASE_PRODUCT_ID],
                "limit": 100,
                "start_date": "2026-07-15T19:59:00Z",
                "end_date": "2026-07-15T20:05:00Z",
                "product_type": "FUTURE",
            },
        )
    ]


@pytest.mark.parametrize(
    "observed_at",
    [ORDER_LOOKUP_START - timedelta(microseconds=1), ORDER_LOOKUP_END],
)
def test_unknown_client_lookup_rejects_read_outside_sealed_window(
    observed_at: datetime,
) -> None:
    delegate = FakeDelegate()

    with pytest.raises(
        Slice3CoinbaseReadError,
        match="slice3_order_read_unavailable",
    ):
        _port(delegate).resolve_exact_order_by_client_order_id(
            client_order_id=CREATE_CLIENT_ORDER_ID,
            observed_at=observed_at,
        )

    assert delegate.calls == []


@pytest.mark.parametrize(
    "status",
    ["QUEUED", "CANCEL_QUEUED", "EDIT_QUEUED"],
)
def test_exact_order_read_recognizes_active_transition_statuses(status: str) -> None:
    delegate = FakeDelegate()
    delegate.orders_response = {
        "orders": [
            _order_row(
                status=status,
                filled_size="0",
                filled_value="0",
                number_of_fills="0",
                total_fees="0",
            )
        ],
        "has_next": False,
        "cursor": "",
    }

    evidence = _port(delegate).read_exact_order(
        client_order_id=CREATE_CLIENT_ORDER_ID,
        exchange_order_id=CREATE_EXCHANGE_ORDER_ID,
        observed_at=NOW,
    )

    assert evidence.observation.status is OrderStatus(status)
    assert evidence.observation.active_order_count == 1


@pytest.mark.parametrize(
    "response",
    [
        {"orders": [], "has_next": False, "cursor": ""},
        {
            "orders": [_order_row(), _order_row()],
            "has_next": False,
            "cursor": "",
        },
        {
            "orders": [_order_row()],
            "has_next": True,
            "cursor": "PRIVATE_CURSOR",
        },
    ],
)
def test_unknown_create_client_lookup_rejects_zero_duplicate_or_pagination(
    response: dict[str, object],
) -> None:
    delegate = FakeDelegate()
    delegate.orders_response = response
    port = _port(delegate)

    with pytest.raises(
        Slice3CoinbaseReadError,
        match="slice3_order_read_unavailable",
    ) as captured:
        port.resolve_exact_order_by_client_order_id(
            client_order_id=CREATE_CLIENT_ORDER_ID,
            observed_at=NOW,
        )

    assert "PRIVATE" not in str(captured.value)
    assert [name for name, _kwargs in delegate.calls] == ["list_orders"]
    assert all(
        name not in {"create_order", "cancel_order", "close_position"}
        for name, _kwargs in delegate.calls
    )


def test_exact_close_order_lookup_binds_terminal_fees_after_close_attempt() -> None:
    delegate = FakeDelegate()
    port = _port(delegate)
    port.close_position(
        client_order_id=CLOSE_CLIENT_ORDER_ID,
        product_id=SLICE3_COINBASE_PRODUCT_ID,
        size="1",
    )
    delegate.calls.clear()
    delegate.orders_response = {
        "orders": [
            _order_row(
                client_order_id=CLOSE_CLIENT_ORDER_ID,
                exchange_order_id=CLOSE_EXCHANGE_ORDER_ID,
                side="SELL",
                configuration={
                    "market_market_ioc": {
                        "base_size": "1",
                        "quote_size": "64.00",
                        "rfq_disabled": False,
                    }
                },
                status="FILLED",
                filled_size="1",
                filled_value="64.00",
                number_of_fills=1,
                total_fees="0.03",
            )
        ],
        "has_next": False,
        "cursor": "",
    }

    evidence = port.read_exact_order(
        client_order_id=CLOSE_CLIENT_ORDER_ID,
        exchange_order_id=CLOSE_EXCHANGE_ORDER_ID,
        observed_at=NOW,
    )

    assert evidence.observation.status is OrderStatus.FILLED
    assert evidence.observation.filled_contracts == "1"
    assert evidence.observation.remaining_contracts == "0"
    assert evidence.observation.active_order_count == 0
    assert evidence.side is OrderSide.SELL
    assert evidence.total_fees == "0.03"
    assert evidence.filled_value == "64"
    assert evidence.number_of_fills == 1


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(has_next=True, cursor="PRIVATE_CURSOR"),
        lambda payload: payload["orders"].append(deepcopy(payload["orders"][0])),
        lambda payload: payload["orders"][0].update(client_order_id="wrong"),
        lambda payload: payload["orders"][0].update(order_id="wrong"),
        lambda payload: payload["orders"][0].update(product_id="BTC-USD"),
        lambda payload: payload["orders"][0].update(side="SELL"),
        lambda payload: payload["orders"][0].update(total_fees="NaN"),
        lambda payload: payload["orders"][0].update(filled_size="1.1"),
        lambda payload: payload["orders"][0].update(number_of_fills="private"),
        lambda payload: payload["orders"][0]["order_configuration"][
            "limit_limit_gtc"
        ].update(post_only=False),
    ],
)
def test_exact_order_lookup_fails_closed_without_pagination_or_ambiguity(
    mutation: Any,
) -> None:
    delegate = FakeDelegate()
    response = {
        "orders": [_order_row()],
        "has_next": False,
        "cursor": "",
    }
    mutation(response)
    delegate.orders_response = response

    with pytest.raises(
        Slice3CoinbaseReadError,
        match="slice3_order_read_unavailable",
    ) as captured:
        _port(delegate).read_exact_order(
            client_order_id=CREATE_CLIENT_ORDER_ID,
            exchange_order_id=CREATE_EXCHANGE_ORDER_ID,
            observed_at=NOW,
        )

    assert "PRIVATE" not in str(captured.value)
    assert [name for name, _kwargs in delegate.calls] == ["list_orders"]


def test_position_read_normalizes_exact_product_and_flat_absence() -> None:
    delegate = FakeDelegate()
    delegate.positions_response = {
        "positions": [
            {
                "product_id": SLICE3_COINBASE_PRODUCT_ID,
                "side": "LONG",
                "number_of_contracts": "1.0",
                "current_price": "6.45",
                "private_position_field": "PRIVATE_POSITION",
            }
        ]
    }
    port = _port(delegate)

    position = port.read_position(observed_at=NOW)

    assert position.authoritative is True
    assert position.product_id == SLICE3_COINBASE_PRODUCT_ID
    assert position.side is AdminFuturesPositionSide.LONG
    assert position.contracts == "1"
    assert position.reference_price == "6.45"
    assert position.contract_size == "10"
    assert len(position.snapshot_sha256) == 64

    flat_delegate = FakeDelegate()
    flat = _port(flat_delegate).read_position(observed_at=NOW)
    assert flat.side is AdminFuturesPositionSide.FLAT
    assert flat.contracts == "0"
    assert flat.reference_price is None


@pytest.mark.parametrize(
    "pagination_claim",
    [
        {"has_next": False},
        {"cursor": ""},
        {"has_next": True, "cursor": "PRIVATE_CURSOR"},
    ],
)
def test_position_read_rejects_bogus_pagination_claims(
    pagination_claim: dict[str, object],
) -> None:
    delegate = FakeDelegate()
    delegate.positions_response = {"positions": [], **pagination_claim}

    with pytest.raises(
        Slice3CoinbaseReadError,
        match="slice3_position_read_unavailable",
    ):
        _port(delegate).read_position(observed_at=NOW)


@pytest.mark.parametrize(
    "positions",
    [
        [
            {
                "product_id": SLICE3_COINBASE_PRODUCT_ID,
                "side": "LONG",
                "number_of_contracts": "2",
                "current_price": "6.45",
            }
        ],
        [
            {
                "product_id": SLICE3_COINBASE_PRODUCT_ID,
                "side": "UNKNOWN",
                "number_of_contracts": "1",
                "current_price": "6.45",
            }
        ],
        [
            {
                "product_id": SLICE3_COINBASE_PRODUCT_ID,
                "side": "LONG",
                "number_of_contracts": "1",
                "current_price": "6.45",
            },
            {
                "product_id": SLICE3_COINBASE_PRODUCT_ID,
                "side": "LONG",
                "number_of_contracts": "1",
                "current_price": "6.45",
            },
        ],
        ["PRIVATE_MALFORMED_POSITION_ROW"],
    ],
)
def test_position_read_rejects_oversize_invalid_or_ambiguous_rows(
    positions: list[object],
) -> None:
    delegate = FakeDelegate()
    delegate.positions_response = {"positions": positions}

    with pytest.raises(
        Slice3CoinbaseReadError,
        match="slice3_position_read_unavailable",
    ):
        _port(delegate).read_position(observed_at=NOW)


def test_open_order_zero_proof_requires_one_complete_empty_page() -> None:
    delegate = FakeDelegate()
    port = _port(delegate)

    proof = port.prove_zero_open_orders(observed_at=NOW)

    assert proof.authoritative is True
    assert proof.pagination_complete is True
    assert proof.scope == "exact_product_active_transitional_orders"
    assert proof.product_id == SLICE3_COINBASE_PRODUCT_ID
    assert proof.exact_product_active_order_count == 0
    assert proof.observed_at == NOW
    assert len(proof.snapshot_sha256) == 64
    assert delegate.calls == [
        (
            "list_orders",
            {
                "order_status": [
                    "PENDING",
                    "OPEN",
                    "QUEUED",
                    "CANCEL_QUEUED",
                    "EDIT_QUEUED",
                ],
                "product_ids": [SLICE3_COINBASE_PRODUCT_ID],
                "limit": 100,
                "product_type": "FUTURE",
            },
        ),
    ]
    assert CREATE_CLIENT_ORDER_ID not in json.dumps(proof.sanitized_evidence())


def test_open_order_proof_reports_nonzero_active_transitional_rows() -> None:
    delegate = FakeDelegate()
    delegate.orders_response = {
        "orders": [_order_row(status="EDIT_QUEUED", filled_size="0", filled_value="0", number_of_fills="0")],
        "has_next": False,
        "cursor": "",
    }

    proof = _port(delegate).prove_zero_open_orders(observed_at=NOW)

    assert proof.exact_product_active_order_count == 1
    assert [kwargs["order_status"] for _name, kwargs in delegate.calls] == [[
        "PENDING",
        "OPEN",
        "QUEUED",
        "CANCEL_QUEUED",
        "EDIT_QUEUED",
    ]]


def test_open_order_proof_rejects_wrong_product_row_conservatively() -> None:
    delegate = FakeDelegate()
    row = _order_row(status="QUEUED", filled_size="0", filled_value="0", number_of_fills="0")
    row["product_id"] = "BTC-USD"
    delegate.orders_response = {
        "orders": [row],
        "has_next": False,
        "cursor": "",
    }

    with pytest.raises(
        Slice3CoinbaseReadError,
        match="slice3_open_order_proof_unavailable",
    ):
        _port(delegate).prove_zero_open_orders(observed_at=NOW)


@pytest.mark.parametrize(
    "response",
    [
        {"orders": [], "has_next": True, "cursor": "PRIVATE_CURSOR"},
        {"orders": [], "has_next": False, "cursor": "PRIVATE_CURSOR"},
    ],
)
def test_open_order_zero_proof_rejects_nonzero_or_incomplete_results(
    response: dict[str, object],
) -> None:
    delegate = FakeDelegate()
    delegate.orders_response = response

    with pytest.raises(
        Slice3CoinbaseReadError,
        match="slice3_open_order_proof_unavailable",
    ) as captured:
        _port(delegate).prove_zero_open_orders(observed_at=NOW)

    assert "PRIVATE" not in str(captured.value)
    assert [name for name, _kwargs in delegate.calls] == ["list_orders"]


def test_margin_summary_is_strict_allowlist_without_private_snapshot_fields() -> None:
    delegate = FakeDelegate()
    summary = _port(delegate).read_margin_summary(observed_at=NOW)

    assert summary.status == "ready"
    assert summary.account_family == "coinbase_futures_us_cfm"
    assert summary.available_margin_usdc == "250"
    assert summary.total_usd_balance_usdc == "500"
    assert summary.initial_margin_usdc == "40"
    assert summary.liquidation_threshold_usdc == "80"
    assert summary.retail_regular_margin_window == ("MARGIN_WINDOW_TYPE_UNSPECIFIED")
    assert summary.retail_intraday_margin_window == ("MARGIN_WINDOW_TYPE_INTRADAY")
    assert summary.intraday_margin_setting == (
        "INTRADAY_MARGIN_SETTING_INTRADAY"
    )
    assert summary.intraday_margin_killswitch_enabled is False
    assert summary.intraday_margin_enrollment_killswitch_enabled is False
    assert summary.observed_at == NOW
    assert len(summary.snapshot_sha256) == 64
    sanitized = summary.sanitized_evidence()
    serialized = json.dumps(sanitized, sort_keys=True)
    assert "PRIVATE_PROFILE" not in serialized
    assert "withheld_private_balance" not in serialized
    assert sanitized["raw_response_included"] is False
    assert sanitized["identifier_values_included"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(status="blocked"),
        lambda value: value["errors"].append(
            {"method": "private", "error": "PRIVATE_MARGIN_ERROR"}
        ),
        lambda value: value["balance_summary"]["available_margin"].update(
            currency="EUR"
        ),
        lambda value: value["balance_summary"]["available_margin"].update(value="NaN"),
        lambda value: value["current_margin_windows"].append(
            deepcopy(value["current_margin_windows"][0])
        ),
        lambda value: value.pop("intraday_margin_setting"),
        lambda value: value["intraday_margin_setting"].update(
            setting="INTRADAY_MARGIN_SETTING_UNSPECIFIED"
        ),
        lambda value: value["current_margin_windows"][0].pop(
            "is_intraday_margin_killswitch_enabled"
        ),
        lambda value: value["current_margin_windows"][0].update(
            is_intraday_margin_killswitch_enabled=True
        ),
        lambda value: value["current_margin_windows"][1].update(
            is_intraday_margin_enrollment_killswitch_enabled="false"
        ),
        lambda value: value.update(source="private_source"),
        lambda value: value["source_read_attempts"].update(get_current_margin_window=1),
        lambda value: value["source_read_attempts"].update(
            get_futures_balance_summary=True
        ),
        lambda value: value.update(intx_applicability="applicable"),
        lambda value: value["futures_sweeps"].append({"id": "PRIVATE_SWEEP"}),
    ],
)
def test_margin_summary_failure_is_generic_without_raw_error_text(
    mutation: Any,
) -> None:
    delegate = FakeDelegate()
    snapshot = _margin_snapshot()
    mutation(snapshot)
    delegate.margin_response = snapshot

    with pytest.raises(
        Slice3CoinbaseReadError,
        match="slice3_margin_read_unavailable",
    ) as captured:
        _port(delegate).read_margin_summary(observed_at=NOW)

    assert "PRIVATE" not in str(captured.value)


def test_read_exceptions_are_mapped_to_generic_unknown_without_text() -> None:
    delegate = FakeDelegate()
    delegate.orders_response = RuntimeError("PRIVATE_READ_EXCEPTION")

    with pytest.raises(
        Slice3CoinbaseReadError,
        match="slice3_order_read_unavailable",
    ) as captured:
        _port(delegate).read_exact_order(
            client_order_id=CREATE_CLIENT_ORDER_ID,
            exchange_order_id=CREATE_EXCHANGE_ORDER_ID,
            observed_at=NOW,
        )

    assert "PRIVATE_READ_EXCEPTION" not in str(captured.value)


def test_market_reference_uses_exact_product_best_ask_once() -> None:
    delegate = FakeDelegate()

    market = _port(delegate).read_market_reference(observed_at=NOW)

    assert market.product_id == SLICE3_COINBASE_PRODUCT_ID
    assert market.reference_price == "6.41"
    assert market.observed_at == NOW
    assert len(market.snapshot_sha256) == 64
    assert delegate.calls == [
        (
            "get_best_bid_ask",
            {"product_ids": [SLICE3_COINBASE_PRODUCT_ID]},
        )
    ]


@pytest.mark.parametrize(
    "response",
    [
        {"pricebooks": []},
        {
            "pricebooks": [
                {
                    "product_id": SLICE3_COINBASE_PRODUCT_ID,
                    "bids": [{"price": "6.42"}],
                    "asks": [{"price": "6.41"}],
                }
            ]
        },
        {
            "pricebooks": [
                {
                    "product_id": "BTC-USD",
                    "bids": [{"price": "6.39"}],
                    "asks": [{"price": "6.41"}],
                }
            ]
        },
    ],
)
def test_market_reference_rejects_ambiguous_crossed_or_wrong_product(
    response: dict[str, object],
) -> None:
    delegate = FakeDelegate()
    delegate.market_response = response

    with pytest.raises(
        Slice3CoinbaseReadError,
        match="slice3_market_read_unavailable",
    ):
        _port(delegate).read_market_reference(observed_at=NOW)


def test_market_reference_rejects_stale_exchange_timestamp() -> None:
    delegate = FakeDelegate()
    delegate.market_response["pricebooks"][0]["time"] = (
        (  # type: ignore[index]
            NOW - timedelta(seconds=31)
        )
        .isoformat()
        .replace("+00:00", "Z")
    )

    with pytest.raises(
        Slice3CoinbaseReadError,
        match="slice3_market_read_unavailable",
    ):
        _port(delegate).read_market_reference(observed_at=NOW)


def test_unknown_close_resolves_once_by_exact_close_client_identity() -> None:
    delegate = FakeDelegate()
    delegate.close_response = RuntimeError("PRIVATE_CLOSE_EXCEPTION")
    port = _port(delegate)
    close = port.close_position(
        client_order_id=CLOSE_CLIENT_ORDER_ID,
        product_id=SLICE3_COINBASE_PRODUCT_ID,
        size="0.25",
    )
    assert close.outcome is Slice3MutationOutcome.UNKNOWN
    delegate.orders_response = {
        "orders": [
            _order_row(
                client_order_id=CLOSE_CLIENT_ORDER_ID,
                exchange_order_id=CLOSE_EXCHANGE_ORDER_ID,
                side="SELL",
                configuration={"market_market_ioc": {"base_size": "0.25"}},
                status="FILLED",
                filled_size="0.25",
                filled_value="16.02",
                total_fees="0.03",
            )
        ],
        "has_next": False,
        "cursor": "",
    }

    evidence = port.resolve_exact_close_order_by_client_order_id(
        client_order_id=CLOSE_CLIENT_ORDER_ID,
        observed_at=NOW,
    )

    assert evidence.observation.client_order_id == CLOSE_CLIENT_ORDER_ID
    assert evidence.observation.exchange_order_id == CLOSE_EXCHANGE_ORDER_ID
    assert evidence.observation.resolution_source.value == (
        "exact_client_order_id_lookup"
    )
    list_calls = [call for call in delegate.calls if call[0] == "list_orders"]
    assert list_calls == [
        (
            "list_orders",
            {
                "product_ids": [SLICE3_COINBASE_PRODUCT_ID],
                "limit": 100,
                "start_date": "2026-07-15T19:59:00Z",
                "end_date": "2026-07-15T20:05:00Z",
                "product_type": "FUTURE",
            },
        )
    ]


def test_fresh_port_reads_close_using_durably_bound_explicit_size() -> None:
    delegate = FakeDelegate()
    delegate.orders_response = {
        "orders": [
            _order_row(
                client_order_id=CLOSE_CLIENT_ORDER_ID,
                exchange_order_id=CLOSE_EXCHANGE_ORDER_ID,
                side="SELL",
                configuration={"market_market_ioc": {"base_size": "0.25"}},
                status="FILLED",
                filled_size="0.25",
                filled_value="16.02",
                total_fees="0.03",
            )
        ],
        "has_next": False,
        "cursor": "",
    }
    fresh_port = _port(delegate)

    evidence = fresh_port.read_exact_order(
        client_order_id=CLOSE_CLIENT_ORDER_ID,
        exchange_order_id=CLOSE_EXCHANGE_ORDER_ID,
        expected_close_size="0.25",
        observed_at=NOW,
    )

    assert evidence.observation.client_order_id == CLOSE_CLIENT_ORDER_ID
    assert evidence.observation.filled == Decimal("0.25")
