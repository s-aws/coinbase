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
def test_list_orders_forwards_exact_retail_portfolio_scope():
    """The backend wrapper must preserve Coinbase's profile filter."""

    from external.coinbase_client import CoinbaseRestClient

    client = CoinbaseRestClient.__new__(CoinbaseRestClient)
    client._client = MagicMock()
    client._client.list_orders.return_value = {"orders": [], "has_next": False}

    response = client.list_orders(
        order_status=["OPEN"],
        product_type="SPOT",
        retail_portfolio_id="test-portfolio-id",
        limit=100,
    )

    assert response == {"orders": [], "has_next": False}
    client._client.list_orders.assert_called_once_with(
        order_status=["OPEN"],
        order_ids=None,
        product_ids=None,
        limit=100,
        start_date=None,
        end_date=None,
        cursor=None,
        product_type="SPOT",
        retail_portfolio_id="test-portfolio-id",
    )


@pytest.mark.regression
def test_cancel_order_accepts_explicit_success_true_payload():
    from external.coinbase_client import CoinbaseRestClient

    fake_sdk_response = MagicMock()
    fake_sdk_response.to_dict.return_value = {
        "results": [{"success": True, "order_id": "client-order-1"}]
    }
    client = CoinbaseRestClient.__new__(CoinbaseRestClient)
    client._client = MagicMock()
    client._client.cancel_orders.return_value = fake_sdk_response

    assert client.cancel_order("client-order-1") is True
    client._client.cancel_orders.assert_called_once_with(["client-order-1"])


@pytest.mark.regression
def test_cancel_order_rejects_success_false_cancel_payload():
    from external.coinbase_client import CoinbaseRestClient

    fake_sdk_response = MagicMock()
    fake_sdk_response.to_dict.return_value = {
        "results": [
            {
                "success": False,
                "failure_reason": "ORDER_NOT_FOUND",
                "order_id": "client-order-1",
            }
        ]
    }
    client = CoinbaseRestClient.__new__(CoinbaseRestClient)
    client._client = MagicMock()
    client._client.cancel_orders.return_value = fake_sdk_response

    assert client.cancel_order("client-order-1") is False
    client._client.cancel_orders.assert_called_once_with(["client-order-1"])


@pytest.mark.regression
def test_cancel_order_rejects_non_empty_payload_without_success_flag():
    from external.coinbase_client import CoinbaseRestClient

    client = CoinbaseRestClient.__new__(CoinbaseRestClient)
    client._client = MagicMock()
    client._client.cancel_orders.return_value = [{"order_id": "client-order-1"}]

    assert client.cancel_order("client-order-1") is False
    client._client.cancel_orders.assert_called_once_with(["client-order-1"])


@pytest.mark.regression
def test_cancel_order_evidence_distinguishes_rejection_from_unknown():
    from external.coinbase_client import coinbase_cancel_response_evidence

    rejected = coinbase_cancel_response_evidence(
        {
            "results": [
                {
                    "success": False,
                    "failure_reason": "ORDER_NOT_FOUND",
                    "order_id": "client-order-1",
                }
            ]
        }
    )
    unknown = coinbase_cancel_response_evidence(
        {"results": [{"order_id": "client-order-1"}]}
    )
    non_identity_failure = coinbase_cancel_response_evidence(
        {
            "results": [
                {
                    "success": False,
                    "failure_reason": "RATE_LIMITED",
                    "order_id": "client-order-1",
                }
            ]
        },
        expected_order_id="client-order-1",
    )

    assert rejected["outcome"] == "explicitly_rejected"
    assert rejected["explicit_rejection"] is True
    assert unknown["outcome"] == "unknown"
    assert unknown["explicit_rejection"] is False
    assert non_identity_failure["outcome"] == "unknown"
    assert non_identity_failure["identity_rejection"] is False


@pytest.mark.regression
def test_cancel_order_can_return_typed_evidence_from_same_wrapper():
    from external.coinbase_client import CoinbaseRestClient

    client = CoinbaseRestClient.__new__(CoinbaseRestClient)
    client._client = MagicMock()
    client._client.cancel_orders.return_value = {
        "results": [
            {
                "success": False,
                "failure_reason": "ORDER_NOT_FOUND",
                "order_id": "client-order-1",
            }
        ]
    }

    evidence = client.cancel_order("client-order-1", return_evidence=True)

    assert evidence["outcome"] == "explicitly_rejected"
    assert evidence["explicit_rejection"] is True
    client._client.cancel_orders.assert_called_once_with(["client-order-1"])


@pytest.mark.regression
def test_cancel_order_uses_one_verified_exchange_id_submission():
    from external.coinbase_client import CoinbaseRestClient

    client = CoinbaseRestClient.__new__(CoinbaseRestClient)
    client._client = MagicMock()
    client._client.cancel_orders.return_value = {
        "results": [
            {
                "success": True,
                "order_id": "exchange-order-1",
            }
        ]
    }

    evidence = client.cancel_order(
        "client-order-1",
        verified_exchange_order_id="exchange-order-1",
        return_evidence=True,
    )

    assert evidence["outcome"] == "succeeded"
    assert evidence["operator_identity_key"] == "client_order_id"
    assert evidence["operator_identity_value"] == "client-order-1"
    assert evidence["exchange_order_id_evidence_only"] is True
    assert evidence["exchange_order_id"] == "exchange-order-1"
    assert evidence["submitted_identity_key"] == "exchange_order_id"
    client._client.cancel_orders.assert_called_once_with(["exchange-order-1"])


@pytest.mark.regression
def test_verified_exchange_id_cancel_preserves_structured_rejection_evidence():
    from external.coinbase_client import CoinbaseRestClient

    client = CoinbaseRestClient.__new__(CoinbaseRestClient)
    client._client = MagicMock()
    client._client.cancel_orders.return_value = {
        "results": [
            {
                "success": False,
                "failure_reason": "UNKNOWN_CANCEL_ORDER",
                "order_id": "exchange-order-1",
            }
        ]
    }

    evidence = client.cancel_order(
        "client-order-1",
        verified_exchange_order_id="exchange-order-1",
        return_evidence=True,
    )

    assert evidence["outcome"] == "explicitly_rejected"
    assert evidence["failure_reasons"] == ["UNKNOWN_CANCEL_ORDER"]
    assert evidence["operator_identity_value"] == "client-order-1"
    assert evidence["exchange_order_id"] == "exchange-order-1"
    assert evidence["submitted_identity_key"] == "exchange_order_id"
    client._client.cancel_orders.assert_called_once_with(["exchange-order-1"])


@pytest.mark.regression
def test_exchange_id_cancel_can_return_unknown_typed_evidence():
    from external.coinbase_client import CoinbaseRestClient

    client = CoinbaseRestClient.__new__(CoinbaseRestClient)
    client._client = MagicMock()
    client._client.cancel_orders.return_value = {
        "results": [{"order_id": "exchange-order-1"}]
    }

    evidence = client.cancel_order_by_exchange_order_id(
        "exchange-order-1",
        return_evidence=True,
    )

    assert evidence["outcome"] == "unknown"
    assert evidence["explicit_rejection"] is False
    client._client.cancel_orders.assert_called_once_with(["exchange-order-1"])


@pytest.mark.regression
@pytest.mark.parametrize(
    "results",
    [
        [
            {
                "success": False,
                "failure_reason": "ORDER_NOT_FOUND",
                "order_id": "different-client-order",
            }
        ],
        [
            {
                "success": False,
                "failure_reason": "ORDER_NOT_FOUND",
                "order_id": "client-order-1",
            },
            {
                "success": False,
                "failure_reason": "ORDER_NOT_FOUND",
                "order_id": "different-client-order",
            },
        ],
    ],
)
def test_typed_cancel_evidence_rejects_wrong_or_multiple_identity_rows(results):
    from external.coinbase_client import CoinbaseRestClient

    client = CoinbaseRestClient.__new__(CoinbaseRestClient)
    client._client = MagicMock()
    client._client.cancel_orders.return_value = {"results": results}

    evidence = client.cancel_order("client-order-1", return_evidence=True)

    assert evidence["outcome"] == "unknown"
    assert evidence["identity_match"] is False
    assert evidence["identity_rejection"] is False


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


class _PagedAccountsSDK:
    def __init__(self):
        self.calls = []
        self.pages = {
            None: {
                "accounts": [
                    {
                        "currency": "USD",
                        "available_balance": {"value": "100"},
                        "deleted_at": None,
                    },
                ],
                "has_next": True,
                "cursor": "cursor-2",
            },
            "cursor-2": {
                "accounts": [
                    {
                        "currency": "BTC",
                        "available_balance": {"value": "0.5"},
                        "deleted_at": None,
                    },
                    {
                        "currency": "OLD",
                        "available_balance": {"value": "99"},
                        "deleted_at": "2026-01-01T00:00:00Z",
                    },
                ],
                "has_next": False,
                "cursor": "",
            },
        }

    def get_accounts(self, *, limit=None, cursor=None):
        self.calls.append({"limit": limit, "cursor": cursor})
        return self.pages[cursor]


@pytest.mark.regression
def test_list_all_account_dicts_follows_account_pagination():
    from external.coinbase_client import list_all_account_dicts

    sdk = _PagedAccountsSDK()

    accounts = list_all_account_dicts(sdk)

    assert [account["currency"] for account in accounts] == ["USD", "BTC", "OLD"]
    assert sdk.calls == [
        {"limit": 250, "cursor": None},
        {"limit": 250, "cursor": "cursor-2"},
    ]


@pytest.mark.regression
def test_get_account_wallets_uses_every_account_page():
    from external.coinbase_client import CoinbaseRestClient

    client = CoinbaseRestClient.__new__(CoinbaseRestClient)
    client._client = _PagedAccountsSDK()

    wallets = client.get_account_wallets()

    assert set(wallets) == {"USD", "BTC"}
    assert wallets["BTC"].currency == "BTC"


@pytest.mark.regression
def test_rest_client_get_accounts_accepts_pagination_args():
    from external.coinbase_client import CoinbaseRestClient

    sdk = _PagedAccountsSDK()
    client = CoinbaseRestClient.__new__(CoinbaseRestClient)
    client._client = sdk

    response = client.get_accounts(limit=100, cursor="cursor-2")

    assert [account["currency"] for account in response["accounts"]] == [
        "BTC",
        "OLD",
    ]
    assert sdk.calls == [{"limit": 100, "cursor": "cursor-2"}]


@pytest.mark.regression
def test_configuration_rest_get_account_wallets_uses_every_account_page(monkeypatch):
    import configuration

    sdk = _PagedAccountsSDK()
    monkeypatch.setattr(configuration, "get_rest_client", lambda: sdk)

    wallets = configuration.rest_get_account_wallets()

    assert set(wallets) == {"USD", "BTC"}
    assert wallets["BTC"]["available_balance"]["value"] == "0.5"


@pytest.mark.regression
def test_configuration_wallet_read_rejects_cross_profile_accounts(monkeypatch):
    import configuration

    test_portfolio_id = "11111111-2222-4333-8444-555555555555"
    default_portfolio_id = "f4dfdb77-aa88-53d0-9c37-da3a0762ce54"
    sdk = _PagedAccountsSDK()
    sdk.pages[None]["accounts"][0]["retail_portfolio_id"] = test_portfolio_id
    sdk.pages["cursor-2"]["accounts"][0][
        "retail_portfolio_id"
    ] = default_portfolio_id
    monkeypatch.setattr(configuration, "get_rest_client", lambda: sdk)
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID",
        test_portfolio_id,
    )

    with pytest.raises(RuntimeError, match="wallet portfolio scope mismatch"):
        configuration.rest_get_account_wallets()
