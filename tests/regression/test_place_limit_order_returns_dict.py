"""Regression: ``CoinbaseClient.place_limit_order`` must return the SDK's
raw dict response, not an :class:`Order` instance.

History (2026-04-29 incident)
=============================

The original implementation called ``Order.from_dict(response.to_dict())``.
The SDK's ``CreateOrderResponse.to_dict()`` produces:

.. code-block:: python

    {
        "success": True,
        "success_response": {
            "order_id": "...",
            "client_order_id": "...",
            "product_id": "...",
            "side": "BUY" | "SELL",
        },
        ...
    }

But ``Order.from_dict`` reads ``data.get('order_side') or data.get('side')``
at the top level. The top-level dict has neither (they're nested under
``success_response``) so every successful place call raised:

    ``Order.from_dict: missing or invalid 'order_side'/'side' (got None)``

``StealthOrderManager.reveal_order_slice`` swallowed the exception via a
broad ``except Exception`` block and recorded the placement as
``placement_success=False``. The order *was* placed on the exchange but
the stealth manager lost the linkage \u2014 incoming fills arrived as
``external_order_no_follow_up`` and no follow-up logic ran.

Two contract guarantees pinned here:

1. ``place_limit_order`` returns the **raw SDK response dict**, not an
   ``Order`` object. Callers in
   ``StealthOrderManager.reveal_order_slice`` and
   ``StealthOrderManager.execute_stealth_move`` both index into
   ``result["success_response"]["order_id"]``; switching to ``Order``
   would silently break them again.

2. ``Order.from_dict`` is **not** invoked anywhere inside
   ``place_limit_order``'s body. Static-source guard so the fix can't
   be silently re-broken.
"""
from __future__ import annotations

import ast
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import HTTPError
from requests.exceptions import Timeout as RequestsTimeout


@pytest.mark.regression
def test_place_limit_order_returns_raw_dict_not_order_instance():
    """A real SDK response should round-trip through
    ``place_limit_order`` as a dict containing ``success_response`` \u2014
    the shape every existing caller already destructures."""
    from external.coinbase_client import CoinbaseRestClient

    # Build an SDK response stand-in: anything with .to_dict() that
    # returns the canonical CreateOrderResponse shape.
    fake_sdk_response = MagicMock()
    fake_sdk_response.to_dict.return_value = {
        "success": True,
        "success_response": {
            "order_id": "exchange-id-abc",
            "client_order_id": "internal-id-xyz",
            "product_id": "BTC-USD",
            "side": "BUY",
        },
        "order_configuration": {"limit_limit_gtc": {}},
    }

    client = CoinbaseRestClient.__new__(CoinbaseRestClient)
    client._client = MagicMock()
    client._client.limit_order_gtc.return_value = fake_sdk_response

    result = client.place_limit_order(
        product_id="BTC-USD",
        side="BUY",
        limit_price="40000.00",
        base_size="0.1",
        client_order_id="internal-id-xyz",
    )

    # Must be a dict (the SDK's to_dict() output), NOT an Order.
    assert isinstance(result, dict), (
        f"place_limit_order must return the raw SDK dict, got {type(result)!r}. "
        f"Switching back to Order causes the stealth manager to lose placement "
        f"linkage on every successful place call \u2014 see the 2026-04-29 incident."
    )
    assert result["success"] is True
    # Every caller indexes this exact path.
    assert result["success_response"]["order_id"] == "exchange-id-abc"
    assert result["success_response"]["client_order_id"] == "internal-id-xyz"


@pytest.mark.regression
@pytest.mark.parametrize(
    "transport_error",
    (
        RequestsConnectionError("credential-shaped-marker-must-not-be-logged"),
        RequestsTimeout("credential-shaped-marker-must-not-be-logged"),
    ),
    ids=("connection_error", "timeout"),
)
def test_transport_failure_retries_exact_same_order_request(
    monkeypatch,
    caplog,
    transport_error,
):
    """A lost create-order response is retried without changing its identity."""
    from external.coinbase_client import CoinbaseRestClient

    fake_sdk_response = MagicMock()
    fake_sdk_response.to_dict.return_value = {
        "success": True,
        "success_response": {
            "order_id": "exchange-id-after-retry",
            "client_order_id": "same-client-order-id",
        },
    }

    client = CoinbaseRestClient.__new__(CoinbaseRestClient)
    client._client = MagicMock()
    client._client.limit_order_gtc.side_effect = [
        transport_error,
        fake_sdk_response,
    ]
    observed_delays = []
    monkeypatch.setattr(
        "external.coinbase_client.time.sleep",
        observed_delays.append,
    )
    caplog.set_level("WARNING", logger="CoinbaseRestClient")

    result = client.place_limit_order(
        product_id="BTC-USD",
        side="BUY",
        limit_price="40000.00",
        base_size="0.1",
        client_order_id="same-client-order-id",
        post_only=True,
    )

    assert result["success"] is True
    assert client._client.limit_order_gtc.call_count == 2
    first_request = client._client.limit_order_gtc.call_args_list[0].kwargs
    retry_request = client._client.limit_order_gtc.call_args_list[1].kwargs
    assert retry_request == first_request
    assert retry_request["client_order_id"] == "same-client-order-id"
    assert retry_request["post_only"] is True
    assert observed_delays == [0.25]
    assert type(transport_error).__name__ in caplog.text
    assert "credential-shaped-marker-must-not-be-logged" not in caplog.text


@pytest.mark.regression
def test_transport_retries_are_bounded_and_final_error_propagates(
    monkeypatch,
):
    """The wrapper makes at most three identical attempts, then fails closed."""
    from external.coinbase_client import CoinbaseRestClient

    client = CoinbaseRestClient.__new__(CoinbaseRestClient)
    client._client = MagicMock()
    client._client.limit_order_gtc.side_effect = [
        RequestsConnectionError("first reset"),
        RequestsTimeout("second timeout"),
        RequestsConnectionError("final reset"),
    ]
    observed_delays = []
    monkeypatch.setattr(
        "external.coinbase_client.time.sleep",
        observed_delays.append,
    )

    with pytest.raises(RequestsConnectionError, match="final reset"):
        client.limit_order_gtc(
            product_id="BTC-USD",
            side="SELL",
            limit_price="41000.00",
            base_size="0.2",
            client_order_id="bounded-client-order-id",
        )

    assert client._client.limit_order_gtc.call_count == 3
    requests = [
        sdk_call.kwargs
        for sdk_call in client._client.limit_order_gtc.call_args_list
    ]
    assert requests[1:] == [requests[0], requests[0]]
    assert observed_delays == [0.25, 1.0]


@pytest.mark.regression
@pytest.mark.parametrize(
    "non_transport_error",
    (
        HTTPError("definitive HTTP failure"),
        ValueError("programming failure"),
    ),
    ids=("http_error", "programming_error"),
)
def test_non_transport_exceptions_are_not_retried(
    monkeypatch,
    non_transport_error,
):
    """HTTP and programming failures bypass the transport retry policy."""
    from external.coinbase_client import CoinbaseRestClient

    client = CoinbaseRestClient.__new__(CoinbaseRestClient)
    client._client = MagicMock()
    client._client.limit_order_gtc.side_effect = non_transport_error
    monkeypatch.setattr(
        "external.coinbase_client.time.sleep",
        lambda _delay: pytest.fail("non-transport error unexpectedly retried"),
    )

    with pytest.raises(type(non_transport_error)):
        client.limit_order_gtc(
            product_id="BTC-USD",
            side="BUY",
            limit_price="40000.00",
            base_size="0.1",
            client_order_id="non-retry-client-order-id",
        )

    client._client.limit_order_gtc.assert_called_once()


@pytest.mark.regression
def test_explicit_exchange_rejection_is_returned_without_retry(monkeypatch):
    """A completed Coinbase response remains the caller's classification job."""
    from external.coinbase_client import CoinbaseRestClient

    rejected_response = {
        "success": False,
        "failure_reason": "INSUFFICIENT_FUND",
    }
    client = CoinbaseRestClient.__new__(CoinbaseRestClient)
    client._client = MagicMock()
    client._client.limit_order_gtc.return_value = rejected_response
    monkeypatch.setattr(
        "external.coinbase_client.time.sleep",
        lambda _delay: pytest.fail("explicit rejection unexpectedly retried"),
    )

    result = client.place_limit_order(
        product_id="BTC-USD",
        side="BUY",
        limit_price="40000.00",
        base_size="0.1",
        client_order_id="rejected-client-order-id",
    )

    assert result is rejected_response
    client._client.limit_order_gtc.assert_called_once()


@pytest.mark.regression
def test_generated_client_order_id_is_reused_for_transport_retry(monkeypatch):
    """An omitted ID is generated once, outside the retry loop."""
    from external.coinbase_client import CoinbaseRestClient

    accepted_response = {"success": True}
    client = CoinbaseRestClient.__new__(CoinbaseRestClient)
    client._client = MagicMock()
    client._client.limit_order_gtc.side_effect = [
        RequestsConnectionError("reset"),
        accepted_response,
    ]
    monkeypatch.setattr("external.coinbase_client.time.sleep", lambda _delay: None)

    result = client.limit_order_gtc(
        product_id="BTC-USD",
        side="BUY",
        limit_price="40000.00",
        base_size="0.1",
    )

    assert result is accepted_response
    first_id = client._client.limit_order_gtc.call_args_list[0].kwargs[
        "client_order_id"
    ]
    retry_id = client._client.limit_order_gtc.call_args_list[1].kwargs[
        "client_order_id"
    ]
    assert retry_id == first_id
    assert str(uuid.UUID(first_id)) == first_id


@pytest.mark.regression
def test_place_limit_order_body_does_not_call_order_from_dict():
    """Static-source guard: ensure ``Order.from_dict`` does not appear
    inside the body of ``place_limit_order``. If a future refactor
    re-introduces it, the SDK envelope mismatch will silently raise on
    every successful place and the broad ``except`` in the stealth
    manager will swallow it again. This test fails loudly first."""
    repo_root = Path(__file__).resolve().parents[2]
    src = (repo_root / "external" / "coinbase_client.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    target_func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "place_limit_order":
            target_func = node
            break

    assert target_func is not None, (
        "place_limit_order not found in external/coinbase_client.py; "
        "did you rename it? Update this test."
    )

    offenders = []
    for sub in ast.walk(target_func):
        if isinstance(sub, ast.Attribute) and sub.attr == "from_dict":
            value = sub.value
            if isinstance(value, ast.Name) and value.id == "Order":
                offenders.append(getattr(sub, "lineno", "?"))

    assert not offenders, (
        f"Order.from_dict(...) call found inside place_limit_order at "
        f"line(s) {offenders}. The SDK response is wrapped in a "
        f"`success_response` envelope that Order.from_dict does NOT "
        f"understand \u2014 it will raise on every successful place. "
        f"Return the raw dict instead. See 2026-04-29 incident docs in "
        f"this file's module docstring."
    )
