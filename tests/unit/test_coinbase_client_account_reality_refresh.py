from __future__ import annotations

import logging

import external.coinbase_client as coinbase_client_module
from external.coinbase_client import CoinbaseRestClient


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def to_dict(self) -> dict[str, object]:
        return self._payload


class _RefreshSdk:
    def __init__(self) -> None:
        self.account_calls: list[dict[str, object]] = []
        self.product_calls: list[dict[str, object]] = []
        self.fee_calls: list[dict[str, object]] = []

    def get_accounts(self, **kwargs: object) -> _Response:
        self.account_calls.append(dict(kwargs))
        cursor = kwargs.get("cursor")
        if cursor is None:
            return _Response(
                {
                    "accounts": [
                        {
                            "currency": "BTC",
                            "available_balance": {"value": "0.1", "currency": "BTC"},
                            "hold": {"value": "0", "currency": "BTC"},
                            "deleted_at": None,
                            "active": True,
                            "ready": True,
                            "retail_portfolio_id": "private-test-profile",
                        }
                    ],
                    "has_next": True,
                    "cursor": "page-2",
                }
            )
        return _Response(
            {
                "accounts": [
                    {
                        "currency": "USDC",
                        "available_balance": {"value": "10", "currency": "USDC"},
                        "hold": {"value": "1", "currency": "USDC"},
                        "deleted_at": None,
                        "active": True,
                        "ready": True,
                        "retail_portfolio_id": "private-test-profile",
                    }
                ],
                "has_next": False,
                "cursor": None,
            }
        )

    def get_products(self, **kwargs: object) -> _Response:
        self.product_calls.append(dict(kwargs))
        return _Response(
            {
                "products": [
                    {
                        "product_id": product_id,
                        "product_type": "SPOT",
                        "trading_disabled": False,
                    }
                    for product_id in kwargs["product_ids"]  # type: ignore[index]
                ]
            }
        )

    def get_transaction_summary(self, **kwargs: object) -> _Response:
        self.fee_calls.append(dict(kwargs))
        return _Response({"fee_tier": {"maker_fee_rate": "0.1"}})


def test_strict_wallet_read_completes_cursor_chain_once_per_page() -> None:
    sdk = _RefreshSdk()
    client = CoinbaseRestClient(sdk)  # type: ignore[arg-type]

    result = client.get_account_wallets_strict()

    assert result.complete is True
    assert result.blocker is None
    assert result.page_count == 2
    assert result.request_count == 2
    assert set(result.wallets) == {"BTC", "USDC"}
    assert result.portfolio_ids == frozenset({"private-test-profile"})
    assert sdk.account_calls == [
        {"limit": 250},
        {"limit": 250, "cursor": "page-2"},
    ]


def test_strict_wallet_read_fails_closed_on_repeated_cursor_without_retry() -> None:
    class _RepeatedCursorSdk(_RefreshSdk):
        def get_accounts(self, **kwargs: object) -> _Response:
            self.account_calls.append(dict(kwargs))
            return _Response(
                {
                    "accounts": [],
                    "has_next": True,
                    "cursor": "same-cursor",
                }
            )

    sdk = _RepeatedCursorSdk()
    client = CoinbaseRestClient(sdk)  # type: ignore[arg-type]

    result = client.get_account_wallets_strict()

    assert result.complete is False
    assert result.blocker == "account_cursor_repeated"
    assert result.page_count == 2
    assert result.request_count == 2
    assert sdk.account_calls == [
        {"limit": 250},
        {"limit": 250, "cursor": "same-cursor"},
    ]


def test_product_batch_uses_one_sdk_request_for_exact_scope() -> None:
    sdk = _RefreshSdk()
    client = CoinbaseRestClient(sdk)  # type: ignore[arg-type]

    result = client.get_products_batch(["BTC-USDC", "AVP-20DEC30-CDE"])

    assert set(result) == {"BTC-USDC", "AVP-20DEC30-CDE"}
    assert sdk.product_calls == [
        {"product_ids": ["BTC-USDC", "AVP-20DEC30-CDE"]}
    ]


def test_spot_fee_summary_uses_one_exact_spot_filtered_sdk_request() -> None:
    sdk = _RefreshSdk()
    result = CoinbaseRestClient(sdk).get_spot_transaction_summary()  # type: ignore[arg-type]

    assert result == {"fee_tier": {"maker_fee_rate": "0.1"}}
    assert sdk.fee_calls == [{"product_type": "SPOT"}]


def test_strict_wallet_second_page_exception_reports_exact_attempt_count() -> None:
    class _SecondPageFailureSdk(_RefreshSdk):
        def get_accounts(self, **kwargs: object) -> _Response:
            if kwargs.get("cursor") is not None:
                self.account_calls.append(dict(kwargs))
                raise RuntimeError("withheld second page response")
            return super().get_accounts(**kwargs)

    sdk = _SecondPageFailureSdk()
    client = CoinbaseRestClient(sdk)  # type: ignore[arg-type]

    result = client.get_account_wallets_strict()

    assert result.complete is False
    assert result.blocker == "account_page_read_failed"
    assert result.page_count == 2
    assert result.request_count == 2
    assert len(sdk.account_calls) == 2


def test_strict_wallet_fails_closed_on_malformed_or_duplicate_currency() -> None:
    class _InvalidRowsSdk(_RefreshSdk):
        def get_accounts(self, **kwargs: object) -> _Response:
            self.account_calls.append(dict(kwargs))
            return _Response(
                {
                    "accounts": [
                        {
                            "currency": "USDC",
                            "available_balance": {"value": "1", "currency": "USDC"},
                            "hold": {"value": "0", "currency": "USDC"},
                            "deleted_at": None,
                            "active": True,
                            "ready": True,
                            "retail_portfolio_id": "private-test-profile",
                        },
                        {
                            "currency": "USDC",
                            "available_balance": {"value": "2", "currency": "USDC"},
                            "hold": {"value": "0", "currency": "USDC"},
                            "deleted_at": None,
                            "active": True,
                            "ready": True,
                            "retail_portfolio_id": "private-test-profile",
                        },
                    ],
                    "has_next": False,
                }
            )

    result = CoinbaseRestClient(  # type: ignore[arg-type]
        _InvalidRowsSdk()
    ).get_account_wallets_strict()

    assert result.complete is False
    assert result.wallets == {}
    assert result.blocker == "account_currency_duplicate"


def test_strict_wallet_requires_complete_currency_bound_money_fields() -> None:
    invalid_rows = (
        {
            "currency": "USDC",
            "hold": {"value": "1", "currency": "USDC"},
            "deleted_at": None,
            "active": True,
            "ready": True,
        },
        {
            "currency": "USDC",
            "available_balance": {"value": "1", "currency": "USDC"},
            "deleted_at": None,
            "active": True,
            "ready": True,
        },
        {
            "currency": "USDC",
            "available_balance": {"value": "1", "currency": "BTC"},
            "hold": {"value": "0", "currency": "USDC"},
            "deleted_at": None,
            "active": True,
            "ready": True,
        },
        {
            "currency": "USDC",
            "available_balance": {"value": "10", "currency": "USDC"},
            "hold": {"value": "1", "currency": "USDC"},
            "total_balance": {"value": "1", "currency": "USDC"},
            "deleted_at": None,
            "active": True,
            "ready": True,
        },
    )

    for invalid_row in invalid_rows:
        class _InvalidMoneySdk(_RefreshSdk):
            def get_accounts(self, **kwargs: object) -> _Response:
                self.account_calls.append(dict(kwargs))
                return _Response(
                    {
                        "accounts": [invalid_row],
                        "has_next": False,
                    }
                )

        result = CoinbaseRestClient(  # type: ignore[arg-type]
            _InvalidMoneySdk()
        ).get_account_wallets_strict()

        assert result.complete is False
        assert result.wallets == {}
        assert result.blocker == "account_balance_invalid"


def test_strict_wallet_requires_explicit_active_and_ready_account_state() -> None:
    invalid_states = (
        {"active": False, "ready": True},
        {"active": True, "ready": False},
        {"ready": True},
        {"active": True},
    )

    for state in invalid_states:
        class _InvalidStateSdk(_RefreshSdk):
            def get_accounts(self, **kwargs: object) -> _Response:
                self.account_calls.append(dict(kwargs))
                return _Response(
                    {
                        "accounts": [
                            {
                                "currency": "USDC",
                                "available_balance": {
                                    "value": "10",
                                    "currency": "USDC",
                                },
                                "hold": {"value": "0", "currency": "USDC"},
                                "deleted_at": None,
                                **state,
                            }
                        ],
                        "has_next": False,
                    }
                )

        result = CoinbaseRestClient(  # type: ignore[arg-type]
            _InvalidStateSdk()
        ).get_account_wallets_strict()

        assert result.complete is False
        assert result.wallets == {}
        assert result.blocker == "account_row_invalid"


def test_strict_wallet_cursor_walk_has_a_hard_page_bound(monkeypatch) -> None:
    class _InfiniteCursorSdk(_RefreshSdk):
        def get_accounts(self, **kwargs: object) -> _Response:
            self.account_calls.append(dict(kwargs))
            page = len(self.account_calls)
            return _Response(
                {
                    "accounts": [],
                    "has_next": True,
                    "cursor": f"page-{page + 1}",
                }
            )

    monkeypatch.setattr(coinbase_client_module, "MAX_ACCOUNT_REFRESH_PAGES", 2)
    sdk = _InfiniteCursorSdk()
    result = CoinbaseRestClient(sdk).get_account_wallets_strict()  # type: ignore[arg-type]

    assert result.complete is False
    assert result.blocker == "account_page_limit_exceeded"
    assert result.request_count == 2
    assert len(sdk.account_calls) == 2


def test_strict_wallet_requires_boolean_pagination_and_string_cursor() -> None:
    invalid_pagination = (
        {},
        {"has_next": None},
        {"has_next": "false"},
        {"has_next": 0},
        {"has_next": True, "cursor": 123},
    )

    for pagination in invalid_pagination:
        class _InvalidPaginationSdk(_RefreshSdk):
            def get_accounts(self, **kwargs: object) -> _Response:
                self.account_calls.append(dict(kwargs))
                return _Response({"accounts": [], **pagination})

        result = CoinbaseRestClient(  # type: ignore[arg-type]
            _InvalidPaginationSdk()
        ).get_account_wallets_strict()

        assert result.complete is False
        assert result.request_count == 1
        assert result.blocker in {
            "account_pagination_metadata_invalid",
            "account_cursor_missing",
        }


def test_refresh_transport_timeout_drift_fails_before_wire_call() -> None:
    class _RetryPolicy:
        total = 0

    class _Adapter:
        max_retries = _RetryPolicy()

    class _Session:
        adapters = {"http://": _Adapter(), "https://": _Adapter()}
        max_redirects = 0
        trust_env = False
        proxies: dict[str, str] = {}
        verify = True

    sdk = _RefreshSdk()
    sdk.session = _Session()  # type: ignore[attr-defined]
    sdk.base_url = "api.coinbase.com"  # type: ignore[attr-defined]
    sdk.timeout = 10  # type: ignore[attr-defined]
    client = CoinbaseRestClient(sdk)  # type: ignore[arg-type]
    sdk.timeout = None  # type: ignore[attr-defined]

    result = client.get_account_wallets_strict()

    assert result.complete is False
    assert result.blocker == "account_transport_policy_invalid"
    assert result.request_count == 0
    assert sdk.account_calls == []


def test_refresh_transport_rejects_nonfinite_timeout_before_wire_call() -> None:
    class _RetryPolicy:
        total = 0

    class _Adapter:
        max_retries = _RetryPolicy()

    class _Session:
        adapters = {"http://": _Adapter(), "https://": _Adapter()}
        max_redirects = 0
        trust_env = False
        proxies: dict[str, str] = {}
        verify = True

    for timeout in (float("nan"), float("inf"), float("-inf")):
        sdk = _RefreshSdk()
        sdk.session = _Session()  # type: ignore[attr-defined]
        sdk.timeout = timeout  # type: ignore[attr-defined]
        sdk.base_url = "api.coinbase.com"  # type: ignore[attr-defined]

        result = CoinbaseRestClient(sdk).get_account_wallets_strict()  # type: ignore[arg-type]

        assert result.complete is False
        assert result.blocker == "account_transport_policy_invalid"
        assert result.request_count == 0
        assert sdk.account_calls == []


def test_refresh_transport_rejects_host_or_tls_drift_before_wire_call() -> None:
    class _RetryPolicy:
        total = 0

    class _Adapter:
        max_retries = _RetryPolicy()

    class _Session:
        adapters = {"http://": _Adapter(), "https://": _Adapter()}
        max_redirects = 0
        trust_env = False
        proxies: dict[str, str] = {}
        verify: object = True

    for base_url, verify in (
        ("https://api.coinbase.com", True),
        ("example.invalid", True),
        ("api.coinbase.com", False),
        ("api.coinbase.com", None),
    ):
        sdk = _RefreshSdk()
        session = _Session()
        session.verify = verify
        sdk.session = session  # type: ignore[attr-defined]
        sdk.timeout = 10  # type: ignore[attr-defined]
        sdk.base_url = base_url  # type: ignore[attr-defined]

        result = CoinbaseRestClient(sdk).get_account_wallets_strict()  # type: ignore[arg-type]

        assert result.complete is False
        assert result.blocker == "account_transport_policy_invalid"
        assert result.request_count == 0
        assert sdk.account_calls == []


def test_refresh_transport_retry_drift_blocks_non_wallet_category() -> None:
    class _RetryPolicy:
        def __init__(self) -> None:
            self.total = 0

    class _Adapter:
        def __init__(self) -> None:
            self.max_retries = _RetryPolicy()

    class _Session:
        adapters = {"http://": _Adapter(), "https://": _Adapter()}
        max_redirects = 0
        trust_env = False
        proxies: dict[str, str] = {}
        verify = True

    sdk = _RefreshSdk()
    sdk.session = _Session()  # type: ignore[attr-defined]
    sdk.base_url = "api.coinbase.com"  # type: ignore[attr-defined]
    sdk.timeout = 10  # type: ignore[attr-defined]
    client = CoinbaseRestClient(sdk)  # type: ignore[arg-type]
    sdk.session.adapters["https://"].max_retries.total = 1  # type: ignore[attr-defined]

    try:
        client.get_products_batch(["BTC-USDC"])
    except ValueError as exc:
        assert str(exc) == "coinbase_sdk_transport_retry_forbidden"
    else:
        raise AssertionError("retry drift must fail closed")
    assert sdk.product_calls == []


def test_sdk_error_logging_is_value_blind(caplog) -> None:
    sentinel = "private-response-body-should-never-log"

    class _LoggingFailureSdk(_RefreshSdk):
        def get_accounts(self, **kwargs: object) -> _Response:
            self.account_calls.append(dict(kwargs))
            logging.getLogger("coinbase.RESTClient").error(sentinel)
            raise RuntimeError(sentinel)

    caplog.set_level(logging.ERROR, logger="coinbase.RESTClient")
    result = CoinbaseRestClient(  # type: ignore[arg-type]
        _LoggingFailureSdk()
    ).get_account_wallets_strict()

    assert result.blocker == "account_page_read_failed"
    assert sentinel not in caplog.text
