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
