"""Regression: 2026-04-30 ``list_fills`` parameter-name mismatch.

Background
==========

``CoinbaseRestClient.list_fills`` exposes a friendly API
(``product_id``, ``start_date``, ``end_date``, ``order_id``) that
internally must be remapped to the SDK's actual parameter names
(``product_ids`` list, ``start_sequence_timestamp``,
``end_sequence_timestamp``, ``order_ids`` list).

The Coinbase SDK's ``RESTClient.get_fills`` accepts ``**kwargs`` and
**silently drops** any unknown parameter names. When this wrapper
forwarded the friendly names verbatim, the date and product filters
became no-ops and the call returned ALL historical fills (back to
2022). Symptom on 2026-04-30: a 24h fee report summed 85,695 fills
(actual: 543) and reported 141,522 in commissions for products the
user had not traded recently (actual: 1,399 across two products).

The same wrapper is used by ``startup_reconciler.py``'s missed-fills
audit, so its "clean" verdict was being computed against the entire
fill history instead of the intended recent window.

Fix
===

Map friendly names to the SDK names inside the wrapper (see
``external/coinbase_client.py::list_fills``).

These tests pin the contract:

1. The wrapper must call the SDK with the **SDK-side** parameter names.
2. A static-source guard prevents anyone from re-introducing the
   user-facing names as kwargs to ``self._client.get_fills(...)``.
"""
from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.mark.regression
def test_list_fills_maps_friendly_names_to_sdk_param_names():
    """The wrapper must translate ``product_id`` → ``product_ids``,
    ``start_date`` → ``start_sequence_timestamp``,
    ``end_date`` → ``end_sequence_timestamp``,
    ``order_id`` → ``order_ids``. Otherwise the SDK silently drops
    the filters and returns all-time fills."""
    from external.coinbase_client import CoinbaseRestClient

    fake_sdk_response = MagicMock()
    fake_sdk_response.to_dict.return_value = {"fills": [], "cursor": ""}

    client = CoinbaseRestClient.__new__(CoinbaseRestClient)
    client._client = MagicMock()
    client._client.get_fills.return_value = fake_sdk_response

    client.list_fills(
        order_id="ord-1",
        product_id="BTC-USDC",
        start_date="2026-04-29T08:00:00Z",
        end_date="2026-04-30T08:00:00Z",
        cursor="cur-1",
        limit=42,
    )

    client._client.get_fills.assert_called_once()
    forwarded = client._client.get_fills.call_args.kwargs
    assert forwarded.get("product_ids") == ["BTC-USDC"], (
        f"product_id must be mapped to product_ids list; got {forwarded!r}"
    )
    assert forwarded.get("order_ids") == ["ord-1"], (
        f"order_id must be mapped to order_ids list; got {forwarded!r}"
    )
    assert forwarded.get("start_sequence_timestamp") == "2026-04-29T08:00:00Z", (
        f"start_date must be mapped to start_sequence_timestamp; got {forwarded!r}"
    )
    assert forwarded.get("end_sequence_timestamp") == "2026-04-30T08:00:00Z", (
        f"end_date must be mapped to end_sequence_timestamp; got {forwarded!r}"
    )
    assert forwarded.get("cursor") == "cur-1"
    assert forwarded.get("limit") == 42

    # And the user-facing names must NOT appear, since the SDK silently
    # ignores them and would mask any future regression.
    for forbidden in ("product_id", "order_id", "start_date", "end_date"):
        assert forbidden not in forwarded, (
            f"User-facing name {forbidden!r} leaked through to SDK kwargs "
            f"(SDK will silently drop it). Forwarded: {forwarded!r}"
        )


@pytest.mark.regression
def test_list_fills_omits_filter_kwargs_when_none():
    """When friendly args are None, the wrapper must NOT pass the
    SDK-side keys at all (so the SDK uses its own defaults)."""
    from external.coinbase_client import CoinbaseRestClient

    fake = MagicMock()
    fake.to_dict.return_value = {"fills": []}
    client = CoinbaseRestClient.__new__(CoinbaseRestClient)
    client._client = MagicMock()
    client._client.get_fills.return_value = fake

    client.list_fills()

    forwarded = client._client.get_fills.call_args.kwargs
    for key in (
        "product_ids", "order_ids",
        "start_sequence_timestamp", "end_sequence_timestamp",
        "cursor",
    ):
        assert key not in forwarded, (
            f"{key!r} must be omitted when caller did not supply a value; "
            f"got {forwarded!r}"
        )


@pytest.mark.regression
def test_list_fills_body_does_not_pass_user_facing_names_to_sdk():
    """Static-source guard: ensure the user-facing names ``product_id``,
    ``start_date``, ``end_date``, ``order_id`` are not assigned into
    the kwargs dict that ``self._client.get_fills`` is called with.
    The SDK accepts ``**kwargs`` and silently drops unknowns, so a
    future refactor that re-introduces them would not raise — only
    this static guard catches it."""
    repo_root = Path(__file__).resolve().parents[2]
    src = (repo_root / "external" / "coinbase_client.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    target_func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "list_fills":
            target_func = node
            break

    assert target_func is not None, (
        "list_fills not found in external/coinbase_client.py; "
        "did you rename it? Update this test."
    )

    offenders: list[tuple[int, str]] = []
    for sub in ast.walk(target_func):
        # Look for subscript assignments like  kwargs["product_id"] = ...
        if (
            isinstance(sub, ast.Assign)
            and len(sub.targets) == 1
            and isinstance(sub.targets[0], ast.Subscript)
        ):
            slice_node = sub.targets[0].slice
            key = None
            if isinstance(slice_node, ast.Constant):
                key = slice_node.value
            if key in ("product_id", "start_date", "end_date", "order_id"):
                offenders.append((getattr(sub, "lineno", -1), key))

    assert not offenders, (
        f"list_fills assigns user-facing kwarg name(s) into the SDK call "
        f"dict: {offenders}. The SDK silently drops these — use the "
        f"SDK-side names (product_ids, order_ids, "
        f"start_sequence_timestamp, end_sequence_timestamp) instead. "
        f"This is the 2026-04-30 silent-filter-drop bug regressing."
    )
