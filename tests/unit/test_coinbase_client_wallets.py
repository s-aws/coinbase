from __future__ import annotations

import pytest

from external.coinbase_client import CoinbaseRestClient


class FakeAccount:
    def __init__(self, data: dict):
        self._data = data

    def to_dict(self) -> dict:
        return dict(self._data)


class FakeAccountsResponse:
    def __init__(
        self,
        accounts: list,
        *,
        has_next: bool = False,
        cursor: str | None = None,
    ):
        self._accounts = accounts
        self._has_next = has_next
        self._cursor = cursor

    def to_dict(self) -> dict:
        return {
            "accounts": list(self._accounts),
            "has_next": self._has_next,
            "cursor": self._cursor,
        }


class FakeSdkClient:
    def __init__(self, accounts: list):
        self._accounts = accounts
        self.account_calls: list[dict] = []

    def get_accounts(self, **kwargs) -> FakeAccountsResponse:
        self.account_calls.append(dict(kwargs))
        return FakeAccountsResponse(self._accounts)


class FakePaginatedAccountsSdkClient(FakeSdkClient):
    def __init__(self, pages: list[dict]):
        super().__init__([])
        self._pages = pages

    def get_accounts(self, **kwargs) -> FakeAccountsResponse:
        self.account_calls.append(dict(kwargs))
        cursor = kwargs.get("cursor")
        page_index = 0 if cursor is None else int(str(cursor).removeprefix("page-"))
        page = self._pages[page_index]
        return FakeAccountsResponse(
            page["accounts"],
            has_next=page.get("has_next", False),
            cursor=page.get("cursor"),
        )


class FakePortfoliosResponse:
    def __init__(self, portfolios: list[dict]):
        self._portfolios = portfolios

    def to_dict(self) -> dict:
        return {"portfolios": list(self._portfolios)}


class FakePortfolioSdkClient(FakeSdkClient):
    def __init__(self, portfolios: list[dict]):
        super().__init__([])
        self._portfolios = portfolios

    def get_portfolios(self) -> FakePortfoliosResponse:
        return FakePortfoliosResponse(self._portfolios)


class FakeResponse:
    def __init__(self, data: dict):
        self._data = data

    def to_dict(self) -> dict:
        return dict(self._data)


class FakeFuturesSdkClient(FakeSdkClient):
    def __init__(
        self,
        *,
        balance_summary: dict | None = None,
        balance_error: Exception | None = None,
    ):
        super().__init__([])
        self.balance_summary = balance_summary or {
            "balance_summary": {
                "available_margin": {"value": "250.00", "currency": "USD"},
                "total_usd_balance": {"value": "500.00", "currency": "USD"},
                "initial_margin": {"value": "40.00", "currency": "USD"},
                "intraday_margin_window_measure": {
                    "margin_window_type": "FCM_MARGIN_WINDOW_TYPE_INTRADAY",
                },
            }
        }
        self.balance_error = balance_error
        self.margin_window_profiles: list[str] = []
        self.futures_sweeps_calls = 0
        self.close_position_calls: list[dict] = []

    def get_futures_balance_summary(self) -> FakeResponse:
        if self.balance_error is not None:
            raise self.balance_error
        return FakeResponse(self.balance_summary)

    def get_intraday_margin_setting(self) -> FakeResponse:
        return FakeResponse({"setting": "INTRADAY_MARGIN_SETTING_STANDARD"})

    def get_current_margin_window(self, margin_profile_type: str) -> FakeResponse:
        self.margin_window_profiles.append(margin_profile_type)
        return FakeResponse(
            {
                "margin_window": {
                    "margin_window_type": "MARGIN_WINDOW_TYPE_INTRADAY",
                },
                "is_intraday_margin_killswitch_enabled": False,
                "is_intraday_margin_enrollment_killswitch_enabled": False,
            }
        )

    def list_futures_sweeps(self) -> FakeResponse:
        self.futures_sweeps_calls += 1
        return FakeResponse({"sweeps": []})

    def close_position(self, **kwargs) -> FakeResponse:
        self.close_position_calls.append(dict(kwargs))
        return FakeResponse(
            {
                "success": True,
                "success_response": {
                    "order_id": "exchange-close-position-1",
                },
            }
        )


def test_get_account_wallets_normalizes_sdk_account_objects():
    client = CoinbaseRestClient(
        FakeSdkClient(
            [
                FakeAccount(
                    {
                        "currency": "USD",
                        "available_balance": {"value": "9.25", "currency": "USD"},
                        "total_balance": {"value": "10.00", "currency": "USD"},
                        "deleted_at": None,
                        "updated_at": "2026-07-03T00:02:00Z",
                    }
                ),
                FakeAccount(
                    {
                        "currency": "BTC",
                        "available_balance": {"value": "0.01", "currency": "BTC"},
                        "total_balance": {"value": "0.01", "currency": "BTC"},
                        "deleted_at": "2026-07-03T00:03:00Z",
                    }
                ),
            ]
        )
    )

    wallets = client.get_account_wallets()

    assert sorted(wallets) == ["USD"]
    assert wallets["USD"].available_balance == "9.25"
    assert wallets["USD"].total_balance == "10.00"


def test_get_account_wallets_paginates_until_quote_wallet_is_loaded():
    sdk = FakePaginatedAccountsSdkClient(
        [
            {
                "accounts": [
                    FakeAccount(
                        {
                            "currency": "BTC",
                            "available_balance": {"value": "0.01", "currency": "BTC"},
                            "total_balance": {"value": "0.01", "currency": "BTC"},
                            "deleted_at": None,
                        }
                    )
                ],
                "has_next": True,
                "cursor": "page-1",
            },
            {
                "accounts": [
                    FakeAccount(
                        {
                            "currency": "USD",
                            "available_balance": {"value": "9.25", "currency": "USD"},
                            "total_balance": {"value": "10.00", "currency": "USD"},
                            "deleted_at": None,
                        }
                    )
                ],
                "has_next": False,
                "cursor": None,
            },
        ]
    )
    client = CoinbaseRestClient(sdk)

    wallets = client.get_account_wallets()

    assert sorted(wallets) == ["BTC", "USD"]
    assert wallets["USD"].available_balance == "9.25"
    assert sdk.account_calls == [
        {"limit": 250},
        {"limit": 250, "cursor": "page-1"},
    ]


def test_list_portfolios_uses_current_sdk_get_portfolios_method():
    client = CoinbaseRestClient(
        FakePortfolioSdkClient(
            [
                {
                    "uuid": "portfolio-real-1",
                    "name": "Real Backend Portfolio",
                }
            ]
        )
    )

    assert client.list_portfolios() == [
        {
            "uuid": "portfolio-real-1",
            "name": "Real Backend Portfolio",
        }
    ]


def test_preview_eligibility_portfolios_uses_only_pinned_sdk_method():
    portfolios = [{"uuid": "portfolio-1", "name": "Default"}]
    client = CoinbaseRestClient(FakePortfolioSdkClient(portfolios))

    assert client.get_futures_preview_eligibility_portfolios() == portfolios


def test_get_futures_margin_collateral_snapshot_uses_us_cfm_readers():
    sdk = FakeFuturesSdkClient()
    client = CoinbaseRestClient(sdk)

    snapshot = client.get_futures_margin_collateral_snapshot()

    assert snapshot["status"] == "ready"
    assert snapshot["account_family"] == "coinbase_futures_us_cfm"
    assert snapshot["source"] == "backend_rest_client"
    assert snapshot["intx_applicability"] == "not_applicable_us_account"
    assert snapshot["balance_summary"]["available_margin"]["value"] == "250.00"
    assert snapshot["intraday_margin_setting"]["setting"] == (
        "INTRADAY_MARGIN_SETTING_STANDARD"
    )
    assert snapshot["source_read_attempts"] == {
        "get_futures_balance_summary": 1,
        "get_intraday_margin_setting": 1,
        "get_current_margin_window": 2,
        "list_futures_sweeps": 1,
    }
    assert snapshot["futures_sweeps"] == []
    assert sdk.margin_window_profiles == [
        "MARGIN_PROFILE_TYPE_RETAIL_REGULAR",
        "MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1",
    ]
    assert sdk.futures_sweeps_calls == 1


def test_get_futures_preview_eligibility_margin_snapshot_excludes_sweeps():
    sdk = FakeFuturesSdkClient()
    client = CoinbaseRestClient(sdk)

    snapshot = (
        client.get_futures_preview_eligibility_margin_collateral_snapshot()
    )

    assert snapshot["status"] == "ready"
    assert snapshot["account_family"] == "coinbase_futures_us_cfm"
    assert snapshot["source"] == "backend_rest_client"
    assert snapshot["intx_applicability"] == "not_applicable_us_account"
    assert snapshot["source_read_attempts"] == {
        "get_futures_balance_summary": 1,
        "get_intraday_margin_setting": 1,
        "get_current_margin_window": 2,
    }
    assert "futures_sweeps" not in snapshot
    assert sdk.margin_window_profiles == [
        "MARGIN_PROFILE_TYPE_RETAIL_REGULAR",
        "MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1",
    ]
    assert sdk.futures_sweeps_calls == 0


@pytest.mark.parametrize("sweeps_payload", [{}, {"sweeps": {}}])
def test_get_futures_margin_collateral_snapshot_flags_ambiguous_sweeps(
    sweeps_payload: dict,
):
    class AmbiguousSweepsSdk(FakeFuturesSdkClient):
        def list_futures_sweeps(self) -> FakeResponse:
            return FakeResponse(sweeps_payload)

    snapshot = CoinbaseRestClient(
        AmbiguousSweepsSdk()
    ).get_futures_margin_collateral_snapshot()

    assert snapshot["futures_sweeps"] == []
    assert snapshot["errors"] == [
        {
            "method": "list_futures_sweeps",
            "error": "futures_sweeps_missing_or_invalid",
        }
    ]


def test_get_futures_margin_collateral_snapshot_blocks_on_missing_cfm_balance_summary():
    client = CoinbaseRestClient(
        FakeFuturesSdkClient(balance_error=RuntimeError("PERMISSION_DENIED"))
    )

    snapshot = client.get_futures_margin_collateral_snapshot()

    assert snapshot["status"] == "blocked"
    assert snapshot["account_family"] == "coinbase_futures_us_cfm"
    assert snapshot["balance_summary"] == {}
    assert snapshot["errors"][0]["method"] == "get_futures_balance_summary"
    assert snapshot["errors"][0]["error"] == "RuntimeError:PERMISSION_DENIED"


def test_close_position_passes_us_cfm_position_payload_to_sdk():
    sdk = FakeFuturesSdkClient()
    client = CoinbaseRestClient(sdk)

    result = client.close_position(
        client_order_id="futures-close-reduce-client-id",
        product_id="AVP-20DEC30-CDE",
        size="1",
    )

    assert result.to_dict()["success"] is True
    assert sdk.close_position_calls == [
        {
            "client_order_id": "futures-close-reduce-client-id",
            "product_id": "AVP-20DEC30-CDE",
            "size": "1",
        }
    ]
