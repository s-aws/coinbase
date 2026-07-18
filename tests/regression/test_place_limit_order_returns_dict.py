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
   ``StealthOrderManager.reveal_order_slice``,
   ``StealthOrderManager._apply_revealed_anchor_reprice``, and
   ``StealthOrderManager.execute_stealth_move`` all index into
   ``result["success_response"]["order_id"]``; switching to ``Order``
   would silently break them again.

2. ``Order.from_dict`` is **not** invoked anywhere inside
   ``place_limit_order``'s body. Static-source guard so the fix can't
   be silently re-broken.
"""
from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _synthetic_execution_authority(
    monkeypatch: pytest.MonkeyPatch,
    coinbase_execution_lease,
) -> None:
    monkeypatch.setenv("COINBASE_EXECUTION_ENABLED", "1")


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
