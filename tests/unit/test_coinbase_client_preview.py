from __future__ import annotations

import pytest
from coinbase.rest.types.orders_types import PreviewOrderResponse

from external.coinbase_client import CoinbaseRestClient


class _RetryPolicy:
    def __init__(self) -> None:
        self.total = 0


class _Adapter:
    def __init__(self) -> None:
        self.max_retries = _RetryPolicy()


class _Session:
    def __init__(self) -> None:
        self.adapters = {"http://": _Adapter(), "https://": _Adapter()}
        self.max_redirects = 9
        self.trust_env = True
        self.proxies: dict[str, str] = {"https": "private-proxy"}
        self.verify: object = True


class _PreviewSdk:
    def __init__(self) -> None:
        self.session = _Session()
        self.base_url = "api.coinbase.com"
        self.timeout: object = 10
        self.preview_calls: list[dict[str, object]] = []

    def preview_order(self, **kwargs: object) -> PreviewOrderResponse:
        self.preview_calls.append(dict(kwargs))
        return PreviewOrderResponse(
            {
                "order_total": "0.5005",
                "commission_total": "0.0005",
                "errs": [],
                "warning": [],
                "quote_size": "0.5",
                "base_size": "0.00001",
                "best_bid": "49999",
                "best_ask": "50000",
                "is_max": False,
                "preview_id": "private-preview-identity",
            }
        )


def test_preview_order_hardens_transport_and_calls_sdk_once_without_legacy_portfolio_override() -> None:
    sdk = _PreviewSdk()
    client = CoinbaseRestClient(sdk)  # type: ignore[arg-type]
    sdk.session.max_redirects = 9
    sdk.session.trust_env = True
    sdk.session.proxies = {"https": "private-proxy"}

    response = client.preview_order(
        product_id="BTC-USDC",
        side="BUY",
        order_configuration={
            "limit_limit_gtc": {
                "base_size": "0.00001",
                "limit_price": "50000",
                "post_only": False,
            }
        },
    )

    assert isinstance(response, PreviewOrderResponse)
    assert sdk.preview_calls == [
        {
            "product_id": "BTC-USDC",
            "side": "BUY",
            "order_configuration": {
                "limit_limit_gtc": {
                    "base_size": "0.00001",
                    "limit_price": "50000",
                    "post_only": False,
                }
            },
        }
    ]
    assert sdk.session.max_redirects == 0
    assert sdk.session.trust_env is False
    assert sdk.session.proxies == {}


@pytest.mark.parametrize(
    ("drift", "expected_code"),
    [
        ("timeout", "coinbase_sdk_transport_timeout_forbidden"),
        ("base_url", "coinbase_sdk_transport_base_url_forbidden"),
        ("tls", "coinbase_sdk_transport_tls_verification_required"),
        ("retry", "coinbase_sdk_transport_retry_forbidden"),
    ],
)
def test_preview_order_revalidates_bounded_transport_before_wire_call(
    drift: str,
    expected_code: str,
) -> None:
    sdk = _PreviewSdk()
    client = CoinbaseRestClient(sdk)  # type: ignore[arg-type]
    if drift == "timeout":
        sdk.timeout = None
    elif drift == "base_url":
        sdk.base_url = "example.invalid"
    elif drift == "tls":
        sdk.session.verify = False
    else:
        sdk.session.adapters["https://"].max_retries.total = 1

    with pytest.raises(ValueError, match=f"^{expected_code}$"):
        client.preview_order(
            product_id="BTC-USDC",
            side="BUY",
            order_configuration={
                "limit_limit_gtc": {
                    "base_size": "0.00001",
                    "limit_price": "50000",
                    "post_only": False,
                }
            },
        )

    assert sdk.preview_calls == []
