"""Focused tests for the controlled root-fill wallet propagation barrier."""

import inspect
from decimal import Decimal

import pytest

from tools import run_controlled_admin_spot_root_child_batch as runner


PORTFOLIO_ID = "62f28f44-8e72-4fe0-ace7-d71a01f54883"


def _accounts(*, btc: str, usdc: str) -> dict:
    return {
        "accounts": [
            {
                "currency": "BTC",
                "retail_portfolio_id": PORTFOLIO_ID,
                "available_balance": {"value": btc},
            },
            {
                "currency": "USDC",
                "retail_portfolio_id": PORTFOLIO_ID,
                "available_balance": {"value": usdc},
            },
        ]
    }


class _WalletClient:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def get_accounts(self, *, limit: int) -> dict:
        assert limit == 250
        self.calls += 1
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]


def test_waits_for_just_filled_root_to_reach_wallet_before_child() -> None:
    client = _WalletClient(
        [
            _accounts(btc="0.00003653", usdc="994.6539324752378277"),
            _accounts(btc="0.00005364", usdc="993.5555405222068583"),
        ]
    )

    wallets, evidence = runner._wait_for_root_wallet_propagation(
        client,
        expected_portfolio_id=PORTFOLIO_ID,
        wallets_before={
            "BTC": Decimal("0.00003653"),
            "USDC": Decimal("994.6539324752378277"),
        },
        filled_size=Decimal("0.00001711"),
        filled_value=Decimal("1.0974591127851021"),
        total_fees=Decimal("0.0009328402458673"),
        base_increment=Decimal("0.00000001"),
        timeout_seconds=1,
        poll_interval_seconds=0,
    )

    assert client.calls == 2
    assert wallets == {
        "BTC": Decimal("0.00005364"),
        "USDC": Decimal("993.5555405222068583"),
    }
    assert evidence == {
        "wallet_delta_kind": "new_root_fill",
        "wallet_btc_delta": "0.00001711",
        "wallet_usdc_delta": "-1.0983919530309694",
        "wallet_propagation_read_count": 2,
        "wallet_propagation_proven": True,
    }


def test_wallet_propagation_timeout_fails_closed() -> None:
    client = _WalletClient(
        [_accounts(btc="0.00003653", usdc="994.6539324752378277")]
    )

    with pytest.raises(runner.ProofFailure, match="root_wallet_propagation_timeout"):
        runner._wait_for_root_wallet_propagation(
            client,
            expected_portfolio_id=PORTFOLIO_ID,
            wallets_before={
                "BTC": Decimal("0.00003653"),
                "USDC": Decimal("994.6539324752378277"),
            },
            filled_size=Decimal("0.00001711"),
            filled_value=Decimal("1.0974591127851021"),
            total_fees=Decimal("0.0009328402458673"),
            base_increment=Decimal("0.00000001"),
            timeout_seconds=0,
            poll_interval_seconds=0,
        )

    assert client.calls == 1


def test_wallet_propagation_rejects_the_observed_two_satoshi_shortfall() -> None:
    client = _WalletClient(
        [_accounts(btc="0.00005362", usdc="993.5555405222068583")]
    )

    with pytest.raises(runner.ProofFailure, match="root_wallet_propagation_timeout"):
        runner._wait_for_root_wallet_propagation(
            client,
            expected_portfolio_id=PORTFOLIO_ID,
            wallets_before={
                "BTC": Decimal("0.00003653"),
                "USDC": Decimal("994.6539324752378277"),
            },
            filled_size=Decimal("0.00001711"),
            filled_value=Decimal("1.0974591127851021"),
            total_fees=Decimal("0.0009328402458673"),
            base_increment=Decimal("0.00000001"),
            timeout_seconds=0,
            poll_interval_seconds=0,
        )

    assert client.calls == 1


def test_wallet_propagation_precedes_every_child_authority_boundary() -> None:
    source = inspect.getsource(runner.execute_controlled_batch)

    propagation = source.index(
        "_, root_wallet_propagation = _wait_for_root_wallet_propagation("
    )
    initial_child_context = source.index(
        "_, initial_child_reveal, _ = runtime.request("
    )
    child_ledger = source.index("child_attempt = consume_batch_attempt(")
    child_http = source.index(
        "child_status_code, child_response, child_headers = runtime.request("
    )

    assert propagation < initial_child_context < child_ledger < child_http
