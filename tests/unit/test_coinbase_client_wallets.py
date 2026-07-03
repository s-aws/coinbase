from __future__ import annotations

from external.coinbase_client import CoinbaseRestClient


class FakeAccount:
    def __init__(self, data: dict):
        self._data = data

    def to_dict(self) -> dict:
        return dict(self._data)


class FakeAccountsResponse:
    def __init__(self, accounts: list):
        self._accounts = accounts

    def to_dict(self) -> dict:
        return {"accounts": list(self._accounts)}


class FakeSdkClient:
    def __init__(self, accounts: list):
        self._accounts = accounts

    def get_accounts(self) -> FakeAccountsResponse:
        return FakeAccountsResponse(self._accounts)


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

    def get_futures_balance_summary(self) -> FakeResponse:
        if self.balance_error is not None:
            raise self.balance_error
        return FakeResponse(self.balance_summary)

    def get_intraday_margin_setting(self) -> FakeResponse:
        return FakeResponse({"setting": "INTRADAY_MARGIN_SETTING_ENABLED"})

    def get_current_margin_window(self, margin_profile_type: str) -> FakeResponse:
        self.margin_window_profiles.append(margin_profile_type)
        return FakeResponse(
            {
                "margin_window": {
                    "margin_window_type": "MARGIN_WINDOW_TYPE_INTRADAY",
                }
            }
        )

    def list_futures_sweeps(self) -> FakeResponse:
        return FakeResponse({"sweeps": []})


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


def test_get_futures_margin_collateral_snapshot_uses_us_cfm_readers():
    sdk = FakeFuturesSdkClient()
    client = CoinbaseRestClient(sdk)

    snapshot = client.get_futures_margin_collateral_snapshot()

    assert snapshot["status"] == "ready"
    assert snapshot["account_family"] == "coinbase_futures_us_cfm"
    assert snapshot["source"] == "backend_rest_client"
    assert snapshot["intx_applicability"] == "not_applicable_us_account"
    assert snapshot["balance_summary"]["available_margin"]["value"] == "250.00"
    assert snapshot["intraday_margin_setting"]["setting"] == "INTRADAY_MARGIN_SETTING_ENABLED"
    assert snapshot["futures_sweeps"] == []
    assert sdk.margin_window_profiles == [
        "MARGIN_PROFILE_TYPE_RETAIL_REGULAR",
        "MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1",
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
