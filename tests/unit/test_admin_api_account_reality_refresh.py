from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import multiprocessing
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api.v1.routes import admin as admin_routes
from application.admin_api.auth import get_authenticated_actor
from application.admin_api.audit import FileAdminApiAuditStore
from application.admin_api.idempotency import FileIdempotencyStore
from application.admin_api.models import (
    AdminApiActor,
    AdminAccountRealityRefreshResponse,
    AdminFeesReadResponse,
    AdminProductsReadResponse,
    AdminWalletReadResponse,
)
from application.admin_api.route_inventory import ADMIN_API_ROUTE_INVENTORY
from application.admin_api.read_service import AdminApiReadService
from core.enums import (
    AdminApiActionClass,
    AdminApiCommandStatus,
    AdminApiPermission,
    AdminApiRole,
)
from application.admin_api.mvp_service import (
    AdminMvpDependencies,
    AdminMvpEvidenceLog,
    AdminMvpRequestContext,
    AdminMvpService,
)


PRIVATE_PORTFOLIO_UUID = "11111111-2222-4333-8444-555555555555"
PRIVATE_EXCEPTION_TEXT = "withheld-account-refresh-detail"
HOSTILE_EXTERNAL_TEXT = f"{PRIVATE_PORTFOLIO_UUID}:{PRIVATE_EXCEPTION_TEXT}"


@dataclass
class _StrictReadClient:
    calls: list[str] = field(default_factory=list)
    fail_category: str | None = None
    wallet_complete: bool = True

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if self.fail_category == name:
            raise RuntimeError(f"{PRIVATE_EXCEPTION_TEXT}:{PRIVATE_PORTFOLIO_UUID}")

    def get_api_key_permissions(self) -> dict[str, object]:
        self._call("api_key_permissions")
        return {
            "portfolio_uuid": PRIVATE_PORTFOLIO_UUID,
            "portfolio_type": "CONSUMER",
            "can_view": True,
            "can_trade": True,
        }

    def list_portfolios(self) -> list[dict[str, object]]:
        self._call("portfolio_catalog")
        return [
            {
                "uuid": PRIVATE_PORTFOLIO_UUID,
                "name": "Test",
                "type": "CONSUMER",
            }
        ]

    def get_account_wallets_strict(self) -> dict[str, object]:
        self._call("wallets")
        return {
            "wallets": {
                "USDC": {
                    "currency": "USDC",
                    "available_balance": "12.34",
                    "total_balance": "15.00",
                    "hold_balance": "2.66",
                }
            },
            "complete": self.wallet_complete,
            "page_count": 2,
            "request_count": 2,
            "blocker": None if self.wallet_complete else "account_cursor_repeated",
            "portfolio_ids": [PRIVATE_PORTFOLIO_UUID],
        }

    def get_products_batch(self, product_ids: list[str]) -> dict[str, object]:
        self._call("product_metadata")
        return {
            product_id: {
                "product_id": product_id,
                "product_type": (
                    "SPOT" if product_id == "BTC-USDC" else "FUTURE"
                ),
                "base_currency": "BTC" if product_id == "BTC-USDC" else "AVP",
                "quote_currency": "USDC",
                "status": "online",
                "base_increment": "0.00000001" if product_id == "BTC-USDC" else "1",
                "quote_increment": "0.01",
                "price_increment": "0.01",
                "base_min_size": "0.00000001" if product_id == "BTC-USDC" else "1",
                "quote_min_size": "1",
                "trading_disabled": False,
                "private_extension": {"portfolio_uuid": PRIVATE_PORTFOLIO_UUID},
            }
            for product_id in product_ids
        }

    def get_best_bid_ask(self, *, product_ids: list[str]) -> dict[str, object]:
        self._call("best_bid_ask")
        return {
            "pricebooks": [
                {
                    "product_id": product_id,
                    "bids": [{"price": "6.90", "size": "1"}],
                    "asks": [{"price": "6.91", "size": "1"}],
                    "time": "2026-07-19T12:00:00Z",
                    "private_extension": PRIVATE_PORTFOLIO_UUID,
                }
                for product_id in product_ids
            ]
        }

    def get_spot_transaction_summary(self) -> dict[str, object]:
        self._call("fee_summary")
        return {
            "fee_tier": {
                "name": "Advanced",
                "maker_fee_rate": "0.0040",
                "taker_fee_rate": "0.0060",
            },
            "volume_30day": {"value": "100.00", "currency": "USD"},
            "portfolio_uuid": PRIVATE_PORTFOLIO_UUID,
        }

    def get_futures_positions(self) -> None:
        raise AssertionError("Futures positions are outside refresh authority")

    def get_futures_margin_collateral_snapshot(self) -> None:
        raise AssertionError("Futures margin is outside refresh authority")


def _context(*, idempotency_key: str = "account-reality-refresh-1") -> AdminMvpRequestContext:
    return AdminMvpRequestContext(
        idempotency_key=idempotency_key,
        correlation_id="account-reality-refresh-correlation",
        operator_intent="refresh_account_reality",
        actor_id="operator-account-reality",
        roles=("operator",),
    )


def _service(
    tmp_path: Path,
    client: _StrictReadClient,
    *,
    now: datetime | None = None,
    now_factory: Callable[[], datetime] | None = None,
    audit_store: FileAdminApiAuditStore | None = None,
) -> AdminMvpService:
    evidence_path = tmp_path / "audit-and-account-reality.jsonl"
    return AdminMvpService(
        AdminMvpDependencies(
            rest_client=client,
            rest_client_available=True,
            now_factory=(
                now_factory
                or (lambda: now or datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc))
            ),
        ),
        evidence_log=AdminMvpEvidenceLog(
            {"account_reality_refreshes": evidence_path}
        ),
        idempotency_store=FileIdempotencyStore(tmp_path / "idempotency.jsonl"),
        audit_store=(
            audit_store
            or FileAdminApiAuditStore(tmp_path / "command-audit.jsonl")
        ),
    )


def _refresh_from_independent_worker(
    root: str,
    start,
    ready,
    results,
) -> None:
    client = _StrictReadClient()
    service = _service(Path(root), client)
    ready.put(True)
    if not start.wait(timeout=10):
        results.put(("timeout", None, []))
        return
    result = service.refresh_account_reality(
        {"reason": "cross-worker one-use claim"},
        _context(
            idempotency_key=(
                f"cross-worker-refresh-{multiprocessing.current_process().pid}"
            )
        ),
    )
    results.put(
        (
            result.status_code,
            result.body.get("diagnostic_code"),
            client.calls,
        )
    )


def test_refresh_reads_each_authorized_category_once_and_replay_is_call_free(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PRIVATE_PORTFOLIO_UUID)
    client = _StrictReadClient()
    service = _service(tmp_path, client)

    first = service.refresh_account_reality({"reason": "operator_refresh"}, _context())
    replay = service.refresh_account_reality({"reason": "operator_refresh"}, _context())

    expected_calls = [
        "api_key_permissions",
        "portfolio_catalog",
        "wallets",
        "product_metadata",
        "best_bid_ask",
        "fee_summary",
    ]
    assert client.calls == expected_calls
    assert first.status_code == 200
    assert first.body["status"] == "ready"
    assert first.body["admission_ready"] is True
    assert first.body["product_scope"] == ["BTC-USDC"]
    assert first.body["live_coinbase_read_ran"] is True
    assert first.body["live_coinbase_orders_ran"] is False
    assert replay.status_code == 200
    assert replay.body == first.body
    assert replay.headers["X-Idempotency-Replayed"] == "true"
    AdminAccountRealityRefreshResponse.model_validate(first.body)

    categories = first.body["categories"]
    assert set(categories) == {
        "api_key_permissions",
        "portfolio_catalog",
        "wallets",
        "product_metadata",
        "best_bid_ask",
        "fee_summary",
    }
    assert all(item["logical_call_count"] == 1 for item in categories.values())
    assert categories["wallets"]["http_request_count"] == 2
    assert categories["wallets"]["complete"] is True

    durable = (tmp_path / "audit-and-account-reality.jsonl").read_text(
        encoding="utf-8"
    )
    idempotency = (tmp_path / "idempotency.jsonl").read_text(encoding="utf-8")
    serialized = json.dumps(first.body, sort_keys=True) + durable + idempotency
    assert PRIVATE_PORTFOLIO_UUID not in serialized
    assert PRIVATE_EXCEPTION_TEXT not in serialized
    assert "private_extension" not in serialized


def test_refresh_allowance_is_durably_consumed_for_new_keys_after_restart(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PRIVATE_PORTFOLIO_UUID)
    client = _StrictReadClient()
    service = _service(tmp_path, client)

    before = service.get_read_response(
        "/api/v1/admin/account-management",
        {},
        _context(idempotency_key="allowance-before-read"),
    ).body["permissions"]
    first = service.refresh_account_reality(
        {"reason": "one authorized refresh"},
        _context(idempotency_key="durable-refresh-first"),
    )
    same_process_new_key = service.refresh_account_reality(
        {"reason": "must not dispatch again"},
        _context(idempotency_key="durable-refresh-second"),
    )
    exact_replay = service.refresh_account_reality(
        {"reason": "one authorized refresh"},
        _context(idempotency_key="durable-refresh-first"),
    )

    restarted = _service(tmp_path, client)
    after_restart = restarted.get_read_response(
        "/api/v1/admin/account-management",
        {},
        _context(idempotency_key="allowance-after-read"),
    ).body["permissions"]
    restarted_new_key = restarted.refresh_account_reality(
        {"reason": "reload must remain sealed"},
        _context(idempotency_key="durable-refresh-after-restart"),
    )

    assert before["account_reality_refresh_allowed"] is True
    assert before["account_reality_refresh_state"] == "available"
    assert before["account_reality_refresh_remaining_uses"] == 1
    assert before["account_reality_refresh_blocker"] == "none"
    assert first.status_code == 200
    assert first.body["status"] == "ready"
    for blocked in (same_process_new_key, restarted_new_key):
        assert blocked.status_code == 409
        assert blocked.body["status"] == "blocked"
        assert blocked.body["diagnostic_code"] == (
            "account_reality_refresh_allowance_consumed"
        )
        assert blocked.body["live_coinbase_read_ran"] is False
        assert blocked.body["local_state_mutated"] is False
    assert exact_replay.status_code == 200
    assert exact_replay.body == first.body
    assert exact_replay.headers["X-Idempotency-Replayed"] == "true"
    assert after_restart["account_reality_refresh_allowed"] is False
    assert after_restart["account_reality_refresh_state"] == "consumed"
    assert after_restart["account_reality_refresh_remaining_uses"] == 0
    assert after_restart["account_reality_refresh_blocker"] == (
        "account_reality_refresh_allowance_consumed"
    )
    assert after_restart["mutation_permissions_granted"] == []
    assert client.calls == [
        "api_key_permissions",
        "portfolio_catalog",
        "wallets",
        "product_metadata",
        "best_bid_ask",
        "fee_summary",
    ]


def test_refresh_allowance_has_one_winner_across_independent_workers(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PRIVATE_PORTFOLIO_UUID)
    context = multiprocessing.get_context("fork")
    start = context.Event()
    ready = context.Queue()
    results = context.Queue()
    workers = [
        context.Process(
            target=_refresh_from_independent_worker,
            args=(str(tmp_path), start, ready, results),
        )
        for _ in range(2)
    ]

    for worker in workers:
        worker.start()
    assert [ready.get(timeout=10) for _ in workers] == [True, True]
    start.set()
    for worker in workers:
        worker.join(timeout=15)

    assert [worker.exitcode for worker in workers] == [0, 0]
    outcomes = [results.get(timeout=10) for _ in workers]
    assert sorted(item[0] for item in outcomes) == [200, 409]
    blocked = next(item for item in outcomes if item[0] == 409)
    assert blocked[1] == "account_reality_refresh_allowance_consumed"
    assert sum(len(item[2]) for item in outcomes) == 6


def test_refresh_allowance_state_corruption_fails_closed_without_reads(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PRIVATE_PORTFOLIO_UUID)
    (tmp_path / "idempotency.jsonl").write_text(
        "malformed durable authority row\n",
        encoding="utf-8",
    )
    client = _StrictReadClient()
    service = _service(tmp_path, client)

    permissions = service.get_read_response(
        "/api/v1/admin/account-management",
        {},
        _context(idempotency_key="corrupt-authority-read"),
    ).body["permissions"]
    result = service.refresh_account_reality(
        {"reason": "must remain sealed"},
        _context(idempotency_key="corrupt-authority-refresh"),
    )

    assert permissions["account_reality_refresh_allowed"] is False
    assert permissions["account_reality_refresh_state"] == "unavailable"
    assert permissions["account_reality_refresh_remaining_uses"] == 0
    assert permissions["account_reality_refresh_blocker"] == (
        "account_reality_refresh_allowance_state_unavailable"
    )
    assert permissions["mutation_permissions_granted"] == []
    assert result.status_code == 503
    assert result.body["status"] == "blocked"
    assert result.body["diagnostic_code"] == (
        "account_reality_refresh_allowance_state_unavailable"
    )
    assert result.body["live_coinbase_read_ran"] is False
    assert client.calls == []


@pytest.mark.parametrize(
    ("family", "category", "blocker"),
    (
        ("wallet_values", "wallets", "wallet_inventory_values_invalid"),
        ("wallet_currency", "wallets", "wallet_inventory_values_invalid"),
        (
            "product_identity",
            "product_metadata",
            "product_metadata_values_invalid",
        ),
        ("product_values", "product_metadata", "product_metadata_values_invalid"),
        ("market_prices", "best_bid_ask", "best_bid_ask_scope_incomplete"),
        ("market_time", "best_bid_ask", "best_bid_ask_scope_incomplete"),
        ("fee_rates", "fee_summary", "fee_summary_evidence_incomplete"),
        ("fee_name", "fee_summary", "fee_summary_evidence_incomplete"),
        ("fee_pricing", "fee_summary", "fee_summary_evidence_incomplete"),
        ("fee_money", "fee_summary", "fee_summary_evidence_incomplete"),
    ),
)
def test_refresh_bounds_all_external_strings_before_persistence_and_readback(
    monkeypatch,
    tmp_path,
    family: str,
    category: str,
    blocker: str,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PRIVATE_PORTFOLIO_UUID)

    class _HostileExternalStringClient(_StrictReadClient):
        def __init__(self, hostile_family: str) -> None:
            super().__init__()
            self.hostile_family = hostile_family

        def get_account_wallets_strict(self) -> dict[str, object]:
            value = super().get_account_wallets_strict()
            wallets = value["wallets"]
            if self.hostile_family == "wallet_values":
                wallets["USDC"].update(  # type: ignore[index, union-attr]
                    {
                        "available_balance": HOSTILE_EXTERNAL_TEXT,
                        "total_balance": HOSTILE_EXTERNAL_TEXT,
                        "hold_balance": HOSTILE_EXTERNAL_TEXT,
                        "updated_at": HOSTILE_EXTERNAL_TEXT,
                    }
                )
            elif self.hostile_family == "wallet_currency":
                wallets["USDC"].update(  # type: ignore[index, union-attr]
                    {
                        "currency": HOSTILE_EXTERNAL_TEXT,
                        "available_balance": HOSTILE_EXTERNAL_TEXT,
                        "total_balance": HOSTILE_EXTERNAL_TEXT,
                        "hold_balance": HOSTILE_EXTERNAL_TEXT,
                        "updated_at": HOSTILE_EXTERNAL_TEXT,
                    }
                )
            return value

        def get_products_batch(self, product_ids: list[str]) -> dict[str, object]:
            products = super().get_products_batch(product_ids)
            if self.hostile_family == "product_identity":
                products["BTC-USDC"]["product_id"] = (  # type: ignore[index]
                    HOSTILE_EXTERNAL_TEXT
                )
            elif self.hostile_family == "product_values":
                products["BTC-USDC"].update(  # type: ignore[union-attr]
                    {
                        "product_type": HOSTILE_EXTERNAL_TEXT,
                        "base_currency": HOSTILE_EXTERNAL_TEXT,
                        "quote_currency": HOSTILE_EXTERNAL_TEXT,
                        "base_increment": HOSTILE_EXTERNAL_TEXT,
                        "quote_increment": HOSTILE_EXTERNAL_TEXT,
                        "price_increment": HOSTILE_EXTERNAL_TEXT,
                        "base_min_size": HOSTILE_EXTERNAL_TEXT,
                        "quote_min_size": HOSTILE_EXTERNAL_TEXT,
                        "display_name": HOSTILE_EXTERNAL_TEXT,
                        "status": HOSTILE_EXTERNAL_TEXT,
                        "mid_price": HOSTILE_EXTERNAL_TEXT,
                        "contract_size": HOSTILE_EXTERNAL_TEXT,
                        "expiry": HOSTILE_EXTERNAL_TEXT,
                    }
                )
            return products

        def get_best_bid_ask(self, *, product_ids: list[str]) -> dict[str, object]:
            value = super().get_best_bid_ask(product_ids=product_ids)
            pricebook = value["pricebooks"][0]  # type: ignore[index]
            if self.hostile_family == "market_prices":
                pricebook["bids"][0]["price"] = (  # type: ignore[index]
                    HOSTILE_EXTERNAL_TEXT
                )
                pricebook["asks"][0]["price"] = (  # type: ignore[index]
                    HOSTILE_EXTERNAL_TEXT
                )
            elif self.hostile_family == "market_time":
                pricebook["time"] = HOSTILE_EXTERNAL_TEXT
            return value

        def get_spot_transaction_summary(self) -> dict[str, object]:
            value = super().get_spot_transaction_summary()
            if self.hostile_family == "fee_rates":
                value["fee_tier"].update(  # type: ignore[union-attr]
                    {
                        "maker_fee_rate": HOSTILE_EXTERNAL_TEXT,
                        "taker_fee_rate": HOSTILE_EXTERNAL_TEXT,
                    }
                )
            elif self.hostile_family == "fee_name":
                value["fee_tier"]["name"] = (  # type: ignore[index]
                    HOSTILE_EXTERNAL_TEXT
                )
            elif self.hostile_family == "fee_pricing":
                value["fee_tier"]["pricing_tier"] = (  # type: ignore[index]
                    HOSTILE_EXTERNAL_TEXT
                )
            elif self.hostile_family == "fee_money":
                value["volume_30day"] = {
                    "value": HOSTILE_EXTERNAL_TEXT,
                    "currency": HOSTILE_EXTERNAL_TEXT,
                }
                value["perpetuals_volume_30day"] = {
                    "value": HOSTILE_EXTERNAL_TEXT,
                    "currency": HOSTILE_EXTERNAL_TEXT,
                }
            return value

    service = _service(tmp_path, _HostileExternalStringClient(family))
    result = service.refresh_account_reality(
        {},
        _context(idempotency_key=f"hostile-external-strings-{family}"),
    )
    wallet_read = service.get_read_response(
        "/api/v1/admin/wallet",
        {},
        _context(idempotency_key="hostile-wallet-read"),
    ).body
    products_read = service.get_read_response(
        "/api/v1/admin/products",
        {"product_id": ["BTC-USDC"]},
        _context(idempotency_key="hostile-products-read"),
    ).body
    fees_read = service.get_read_response(
        "/api/v1/admin/fees",
        {},
        _context(idempotency_key="hostile-fees-read"),
    ).body

    assert result.body["status"] == "blocked"
    assert result.body["categories"][category] == {
        "status": "blocked",
        "complete": False,
        "logical_call_count": 1,
        "http_request_count": 2 if category == "wallets" else 1,
        "blocker": blocker,
    }
    normal_wallets = [
        {
            "currency": "USDC",
            "available_balance": "12.34",
            "total_balance": "15.00",
            "hold_balance": "2.66",
            "updated_at": None,
        }
    ]
    if family == "wallet_values":
        assert result.body["wallets"] == [
            {
                "currency": "USDC",
                "available_balance": "0",
                "total_balance": "0",
                "hold_balance": "0",
                "updated_at": None,
            }
        ]
        assert result.body["products"] == []
        assert result.body["market"] == []
        assert result.body["fees"]["status"] == "blocked"
    elif family == "wallet_currency":
        assert result.body["wallets"] == []
        assert result.body["products"] == []
        assert result.body["market"] == []
        assert result.body["fees"]["status"] == "blocked"
    else:
        assert result.body["wallets"] == normal_wallets
        product = result.body["products"][0]
        assert product["product_id"] == "BTC-USDC"
        assert product["display_name"] == "BTC-USDC"

        if family == "product_identity":
            assert product["read_status"] == "blocked"
            assert product["read_error"] == "product_metadata_scope_mismatch"
            assert product["status"] == "ONLINE"
        elif family == "product_values":
            assert product["read_status"] == "blocked"
            assert product["read_error"] == "product_metadata_values_invalid"
            assert product["status"] == "UNKNOWN"
            for field_name in (
                "base_currency",
                "quote_currency",
                "base_increment",
                "quote_increment",
                "price_increment",
                "base_min_size",
                "quote_min_size",
                "mid_price",
                "contract_size",
                "expiry",
            ):
                assert product[field_name] is None

        if family in {"market_prices", "market_time"}:
            assert result.body["market"] == []
            assert product["market_observed_at"] is None

        fee_tier = result.body["fees"]["fee_tier"]
        if family == "fee_rates":
            assert fee_tier["status"] == "blocked"
            assert fee_tier["maker_fee_rate"] is None
            assert fee_tier["taker_fee_rate"] is None
            assert fee_tier["read_error"] == "fee_tier_rate_missing"
        elif family == "fee_name":
            assert fee_tier["status"] == "blocked"
            assert fee_tier["name"] is None
            assert fee_tier["read_error"] == "fee_tier_name_invalid"
        elif family == "fee_pricing":
            assert fee_tier["status"] == "blocked"
            assert fee_tier["pricing_tier"] is None
            assert fee_tier["read_error"] == "fee_tier_pricing_tier_invalid"
        elif family == "fee_money":
            assert result.body["fees"]["status"] == "blocked"
            assert result.body["fees"]["volume_30day"] == {
                "value": "0",
                "currency": "USD",
            }
            assert result.body["fees"]["perpetuals_volume_30day"] == {
                "value": "0",
                "currency": "USD",
                "status": "blocked",
                "read_error": "futures_coinbase_read_not_authorized",
            }
    AdminAccountRealityRefreshResponse.model_validate(result.body)

    audit = (tmp_path / "command-audit.jsonl").read_text(encoding="utf-8")
    durable = (tmp_path / "audit-and-account-reality.jsonl").read_text(
        encoding="utf-8"
    )
    idempotency = (tmp_path / "idempotency.jsonl").read_text(encoding="utf-8")
    durable_record = next(reversed(service.store.account_reality_refreshes.values()))
    serialized = json.dumps(
        [
            result.body,
            durable_record,
            wallet_read,
            products_read,
            fees_read,
        ],
        sort_keys=True,
    )
    serialized += audit + durable + idempotency
    assert PRIVATE_PORTFOLIO_UUID not in serialized
    assert PRIVATE_EXCEPTION_TEXT not in serialized
    assert len(serialized) < 100_000


def test_refresh_changed_payload_conflicts_without_another_read(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PRIVATE_PORTFOLIO_UUID)
    client = _StrictReadClient()
    service = _service(tmp_path, client)

    first = service.refresh_account_reality({"reason": "first"}, _context())
    conflict = service.refresh_account_reality({"reason": "changed"}, _context())

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.body["status"] == "conflict"
    assert conflict.body["diagnostic_code"] == "account_reality_refresh_idempotency_conflict"
    assert len(client.calls) == 6


def test_refresh_failure_uses_fixed_diagnostics_and_persists_no_exception_text(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PRIVATE_PORTFOLIO_UUID)
    client = _StrictReadClient(fail_category="fee_summary")
    service = _service(tmp_path, client)

    result = service.refresh_account_reality({"reason": "operator_refresh"}, _context())

    assert result.status_code == 200
    assert result.body["status"] == "blocked"
    assert result.body["admission_ready"] is False
    assert result.body["categories"]["fee_summary"] == {
        "status": "blocked",
        "complete": False,
        "logical_call_count": 1,
        "http_request_count": 1,
        "blocker": "fee_summary_read_failed",
    }
    serialized = json.dumps(result.body, sort_keys=True)
    serialized += (tmp_path / "audit-and-account-reality.jsonl").read_text(
        encoding="utf-8"
    )
    assert PRIVATE_EXCEPTION_TEXT not in serialized
    assert PRIVATE_PORTFOLIO_UUID not in serialized
    assert "RuntimeError" not in serialized


def test_incomplete_wallet_pagination_is_never_admission_ready(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PRIVATE_PORTFOLIO_UUID)
    client = _StrictReadClient(wallet_complete=False)
    service = _service(tmp_path, client)

    result = service.refresh_account_reality({}, _context())

    assert result.body["status"] == "blocked"
    assert result.body["admission_ready"] is False
    assert result.body["categories"]["wallets"]["blocker"] == (
        "wallet_inventory_pagination_incomplete"
    )


def test_unknown_after_reads_consumes_claim_and_replay_never_reads_again(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PRIVATE_PORTFOLIO_UUID)

    class _FailingTerminalAuditStore(FileAdminApiAuditStore):
        append_count = 0

        def append(self, event):
            self.append_count += 1
            if self.append_count == 3:
                raise RuntimeError(PRIVATE_EXCEPTION_TEXT)
            return super().append(event)

    client = _StrictReadClient()
    service = _service(
        tmp_path,
        client,
        audit_store=_FailingTerminalAuditStore(tmp_path / "failing-audit.jsonl"),
    )

    unknown = service.refresh_account_reality({}, _context())
    replay = service.refresh_account_reality({}, _context())

    assert unknown.status_code == 503
    assert unknown.body["status"] == "outcome_unknown"
    assert unknown.body["local_state_mutated"] is True
    assert unknown.body["live_coinbase_read_ran"] is True
    assert replay.status_code == 503
    assert replay.body == unknown.body
    assert replay.headers["X-Idempotency-Replayed"] == "true"
    assert len(client.calls) == 6
    assert PRIVATE_EXCEPTION_TEXT not in json.dumps(unknown.body, sort_keys=True)
    assert len(service.store.account_reality_refreshes) == 1
    retained_claim = next(
        iter(service.store.account_reality_refreshes.values())
    )
    assert retained_claim["terminal"] is False
    assert retained_claim["projection"] == {}
    wallet = service.get_read_response(
        "/api/v1/admin/wallet",
        {},
        _context(idempotency_key="unknown-wallet-read"),
    ).body
    assert wallet["account_reality"]["status"] == "unavailable"


def test_post_refresh_gets_project_latest_snapshot_without_coinbase_calls(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PRIVATE_PORTFOLIO_UUID)
    client = _StrictReadClient()
    service = _service(tmp_path, client)
    first = service.refresh_account_reality({}, _context())
    calls_after_refresh = list(client.calls)

    wallet = service.get_read_response("/api/v1/admin/wallet", {}, _context()).body
    products = service.get_read_response(
        "/api/v1/admin/products",
        {"product_id": ["BTC-USDC"]},
        _context(),
    ).body
    fees = service.get_read_response("/api/v1/admin/fees", {}, _context()).body
    readiness = service.get_read_response(
        "/api/v1/spot/readiness",
        {},
        _context(),
    ).body
    account = service.get_read_response(
        "/api/v1/admin/account-management",
        {},
        _context(),
    ).body

    assert client.calls == calls_after_refresh
    assert wallet["wallet_inventory"]["available_notional_usdc"] == "12.34"
    assert wallet["live_coinbase_read_ran"] is False
    assert wallet["account_reality"]["proof_origin_coinbase_read_ran"] is True
    assert products["products"][0]["read_status"] == "ready"
    assert products["products"][0]["best_bid"] == "6.90"
    assert fees["fee_tier"]["maker_fee_rate"] == "0.0040"
    assert readiness["status"] == "ready"
    assert readiness["live_coinbase_read_ran"] is False
    assert [item["product_id"] for item in readiness["products"]] == [
        "BTC-USDC"
    ]
    assert readiness["products"][0]["price_increment"] == "0.01"
    assert readiness["products"][0]["best_bid"] == "6.90"
    assert readiness["products"][0]["best_ask"] == "6.91"
    assert readiness["products"][0]["captured_at"] == (
        first.body["captured_at"]
    )
    assert readiness["products"][0]["fresh_until"] == (
        first.body["fresh_until"]
    )
    assert account["permissions"]["account_reality_refresh_allowed"] is False
    assert account["permissions"]["account_reality_refresh_state"] == "consumed"
    assert account["permissions"]["account_reality_refresh_remaining_uses"] == 0
    assert account["permissions"]["account_reality_refresh_blocker"] == (
        "account_reality_refresh_allowance_consumed"
    )
    assert "account_reality:refresh" not in account["permissions"][
        "mutation_permissions_granted"
    ]
    AdminWalletReadResponse.model_validate(wallet)
    AdminProductsReadResponse.model_validate(products)
    AdminFeesReadResponse.model_validate(fees)


def test_stale_snapshot_remains_call_free_and_is_not_admission_ready(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PRIVATE_PORTFOLIO_UUID)
    client = _StrictReadClient()
    captured_at = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    writer = _service(tmp_path, client, now=captured_at)
    writer.refresh_account_reality({}, _context())
    calls_after_refresh = list(client.calls)

    reader = _service(tmp_path, client, now=captured_at + timedelta(minutes=5))
    wallet = reader.get_read_response("/api/v1/admin/wallet", {}, _context()).body
    readiness = reader.get_read_response(
        "/api/v1/spot/readiness",
        {"product_id": ["BTC-USDC"]},
        _context(),
    ).body

    assert client.calls == calls_after_refresh
    assert wallet["account_reality"]["status"] == "stale"
    assert wallet["readiness"]["usable_for_spot_admission"] is False
    assert wallet["wallets"][0]["freshness_status"] == "stale"
    assert readiness["status"] != "ready"


def test_refresh_that_reaches_freshness_deadline_fails_terminal_readiness_closed(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PRIVATE_PORTFOLIO_UUID)
    started_at = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    clock_values = iter((started_at, started_at + timedelta(seconds=60)))
    client = _StrictReadClient()
    service = _service(
        tmp_path,
        client,
        now_factory=lambda: next(clock_values),
    )

    result = service.refresh_account_reality(
        {},
        _context(idempotency_key="refresh-expired-at-terminal"),
    )

    assert client.calls == [
        "api_key_permissions",
        "portfolio_catalog",
        "wallets",
        "product_metadata",
        "best_bid_ask",
        "fee_summary",
    ]
    assert result.status_code == 200
    assert result.body["status"] == "blocked"
    assert result.body["diagnostic_code"] == "account_reality_refresh_expired"
    assert result.body["admission_ready"] is False
    assert set(result.body["categories"]) == {
        "api_key_permissions",
        "portfolio_catalog",
        "wallets",
        "product_metadata",
        "best_bid_ask",
        "fee_summary",
    }
    assert all(
        evidence["logical_call_count"] == 1 and evidence["complete"] is True
        for evidence in result.body["categories"].values()
    )
    assert result.body["account_reality"]["status"] == "stale"
    assert result.body["wallet_inventory"]["quote_wallet_status"] == "blocked"
    assert result.body["products"][0]["read_status"] == "blocked"
    assert result.body["fees"]["status"] == "blocked"


def test_missing_or_mismatched_approved_portfolio_blocks_private_reads(
    monkeypatch,
    tmp_path,
) -> None:
    client = _StrictReadClient()
    monkeypatch.delenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", raising=False)
    missing = _service(tmp_path / "missing", client).refresh_account_reality(
        {},
        _context(idempotency_key="missing-approved-portfolio"),
    )
    assert missing.body["status"] == "blocked"
    assert client.calls == []

    monkeypatch.setenv(
        "COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID",
        "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
    )
    mismatch = _service(tmp_path / "mismatch", client).refresh_account_reality(
        {},
        _context(idempotency_key="mismatched-approved-portfolio"),
    )
    assert mismatch.body["status"] == "blocked"
    assert client.calls == ["api_key_permissions", "portfolio_catalog"]
    assert mismatch.body["categories"]["wallets"]["logical_call_count"] == 0
    assert mismatch.body["wallets"] == []
    assert mismatch.body["fees"]["status"] == "blocked"


def test_wallet_portfolio_mismatch_stops_all_later_category_reads(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PRIVATE_PORTFOLIO_UUID)

    class _MismatchedWalletClient(_StrictReadClient):
        def get_account_wallets_strict(self) -> dict[str, object]:
            value = super().get_account_wallets_strict()
            value["portfolio_ids"] = ["aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"]
            return value

    client = _MismatchedWalletClient()
    result = _service(tmp_path, client).refresh_account_reality({}, _context())

    assert client.calls == [
        "api_key_permissions",
        "portfolio_catalog",
        "wallets",
    ]
    assert result.body["categories"]["wallets"]["blocker"] == (
        "wallet_inventory_portfolio_scope_mismatch"
    )
    for category in ("product_metadata", "best_bid_ask", "fee_summary"):
        assert result.body["categories"][category]["logical_call_count"] == 0
        assert result.body["categories"][category]["http_request_count"] == 0


def test_mismatched_private_portfolio_label_is_withheld_everywhere(
    monkeypatch,
    tmp_path,
) -> None:
    private_label = "Private Desk 47"
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PRIVATE_PORTFOLIO_UUID)
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_LABEL", "Test")

    class _PrivateLabelClient(_StrictReadClient):
        def list_portfolios(self) -> list[dict[str, object]]:
            self._call("portfolio_catalog")
            return [
                {
                    "uuid": PRIVATE_PORTFOLIO_UUID,
                    "name": private_label,
                    "type": "CONSUMER",
                }
            ]

    service = _service(tmp_path, _PrivateLabelClient())
    result = service.refresh_account_reality(
        {},
        _context(idempotency_key="private-label-mismatch"),
    )
    projection = service.get_read_response(
        "/api/v1/admin/account-management",
        {},
        _context(idempotency_key="private-label-projection"),
    ).body
    durable_evidence = (tmp_path / "audit-and-account-reality.jsonl").read_text(
        encoding="utf-8"
    )

    assert result.body["status"] == "blocked"
    assert result.body["diagnostic_code"] == "approved_test_portfolio_binding_blocked"
    assert private_label not in json.dumps(result.body, sort_keys=True)
    assert private_label not in json.dumps(projection, sort_keys=True)
    assert private_label not in durable_evidence
    durable_record = next(reversed(service.store.account_reality_refreshes.values()))
    binding = durable_record["projection"]["spot_portfolio_binding"]
    assert binding["expected_portfolio_label"] == "Test"
    assert binding["observed_portfolio_label"] is None
    assert binding["observed_portfolio_label_matches_expected"] is False
    assert binding["blocker"] == "spot_test_portfolio_label_mismatch"


def test_invalid_market_or_zero_available_wallet_never_becomes_ready(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PRIVATE_PORTFOLIO_UUID)

    class _InvalidMarketClient(_StrictReadClient):
        def get_best_bid_ask(self, *, product_ids: list[str]) -> dict[str, object]:
            self._call("best_bid_ask")
            return {
                "pricebooks": [
                    {
                        "product_id": product_id,
                        "bids": [{"price": "7.00"}],
                        "asks": [{"price": "6.00"}],
                    }
                    for product_id in product_ids
                ]
            }

    invalid_market = _service(
        tmp_path / "market",
        _InvalidMarketClient(),
    ).refresh_account_reality({}, _context(idempotency_key="invalid-market"))
    assert invalid_market.body["admission_ready"] is False
    assert invalid_market.body["categories"]["best_bid_ask"]["blocker"] == (
        "best_bid_ask_scope_incomplete"
    )

    class _ZeroWalletClient(_StrictReadClient):
        def get_account_wallets_strict(self) -> dict[str, object]:
            value = super().get_account_wallets_strict()
            value["wallets"]["USDC"]["available_balance"] = "0"  # type: ignore[index]
            return value

    zero_wallet = _service(
        tmp_path / "wallet",
        _ZeroWalletClient(),
    ).refresh_account_reality({}, _context(idempotency_key="zero-wallet"))
    assert zero_wallet.body["admission_ready"] is False


def test_mismatched_or_restricted_spot_product_never_becomes_ready(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PRIVATE_PORTFOLIO_UUID)

    invalid_overrides = (
        {"base_currency": "ETH"},
        {"quote_currency": "USD"},
        {"product_type": "FUTURE"},
        {"is_disabled": True},
        {"cancel_only": True},
        {"view_only": True},
        {"auction_mode": True},
        {"status": "offline"},
    )

    for index, override in enumerate(invalid_overrides):
        class _InvalidProductClient(_StrictReadClient):
            def get_products_batch(
                self,
                product_ids: list[str],
            ) -> dict[str, object]:
                products = super().get_products_batch(product_ids)
                products["BTC-USDC"].update(override)  # type: ignore[union-attr]
                return products

        result = _service(
            tmp_path / f"product-{index}",
            _InvalidProductClient(),
        ).refresh_account_reality(
            {},
            _context(idempotency_key=f"invalid-product-{index}"),
        )

        assert result.body["admission_ready"] is False
        assert result.body["categories"]["product_metadata"]["blocker"] == (
            "product_metadata_values_invalid"
        )


def test_pinned_sdk_currency_id_product_shape_is_ready_and_futures_fee_is_blocked(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PRIVATE_PORTFOLIO_UUID)

    class _PinnedProductClient(_StrictReadClient):
        def get_products_batch(self, product_ids: list[str]) -> dict[str, object]:
            products = super().get_products_batch(product_ids)
            product = products["BTC-USDC"]
            product["base_currency_id"] = product.pop("base_currency")  # type: ignore[union-attr]
            product["quote_currency_id"] = product.pop("quote_currency")  # type: ignore[union-attr]
            return products

    result = _service(tmp_path, _PinnedProductClient()).refresh_account_reality(
        {},
        _context(idempotency_key="pinned-product-shape"),
    )

    assert result.body["status"] == "ready"
    assert result.body["products"][0]["base_currency"] == "BTC"
    assert result.body["products"][0]["quote_currency"] == "USDC"
    assert result.body["fees"]["spot_fee_input"]["status"] == "ready"
    assert result.body["fees"]["futures_fee_input"]["status"] == "blocked"
    assert result.body["fees"]["futures_fee_input"]["first_blocker"] == (
        "futures_coinbase_read_not_authorized"
    )
    assert result.body["fees"]["perpetuals_volume_30day"]["status"] == "blocked"


def test_wallet_projection_preserves_crypto_and_subcent_precision(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PRIVATE_PORTFOLIO_UUID)

    class _PreciseWalletClient(_StrictReadClient):
        def get_account_wallets_strict(self) -> dict[str, object]:
            self._call("wallets")
            return {
                "wallets": {
                    "BTC": {
                        "currency": "BTC",
                        "available_balance": "0.00000001",
                        "total_balance": "0.00000002",
                        "hold_balance": "0.00000001",
                    },
                    "USDC": {
                        "currency": "USDC",
                        "available_balance": "0.006",
                        "total_balance": "0.009",
                        "hold_balance": "0.003",
                    },
                },
                "complete": True,
                "page_count": 1,
                "request_count": 1,
                "blocker": None,
                "portfolio_ids": [PRIVATE_PORTFOLIO_UUID],
            }

    result = _service(tmp_path, _PreciseWalletClient()).refresh_account_reality(
        {},
        _context(idempotency_key="precise-wallets"),
    )
    wallets = {row["currency"]: row for row in result.body["wallets"]}

    assert wallets["BTC"]["available_balance"] == "0.00000001"
    assert wallets["BTC"]["hold_balance"] == "0.00000001"
    assert wallets["BTC"]["total_balance"] == "0.00000002"
    assert wallets["USDC"]["available_balance"] == "0.006"
    assert wallets["USDC"]["hold_balance"] == "0.003"
    assert wallets["USDC"]["total_balance"] == "0.009"
    assert result.body["wallet_inventory"]["available_notional_usdc"] == "0.006"


def test_refresh_rejects_top_level_converter_only_fee_rates(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PRIVATE_PORTFOLIO_UUID)

    class _MisnestedFeeClient(_StrictReadClient):
        def get_spot_transaction_summary(self) -> dict[str, object]:
            self._call("fee_summary")
            return {
                "maker_fee_rate": "0.0040",
                "taker_fee_rate": "0.0060",
            }

    result = _service(tmp_path, _MisnestedFeeClient()).refresh_account_reality(
        {},
        _context(idempotency_key="misnested-fee"),
    )

    assert result.body["admission_ready"] is False
    assert result.body["categories"]["fee_summary"]["blocker"] == (
        "fee_summary_evidence_incomplete"
    )
    assert result.body["fees"]["fee_tier"]["read_error"] == "fee_tier_missing"


def test_known_transport_preflight_failure_reports_zero_http_requests(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PRIVATE_PORTFOLIO_UUID)

    class _PreWireBlockedClient(_StrictReadClient):
        def get_api_key_permissions(self) -> dict[str, object]:
            raise ValueError("coinbase_sdk_transport_timeout_forbidden")

    result = _service(tmp_path, _PreWireBlockedClient()).refresh_account_reality(
        {},
        _context(idempotency_key="prewire-blocked"),
    )

    category = result.body["categories"]["api_key_permissions"]
    assert category["logical_call_count"] == 1
    assert category["http_request_count"] == 0


def test_process_loss_after_read_boundary_replays_conservative_read_accounting(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PRIVATE_PORTFOLIO_UUID)

    class _SimulatedProcessLoss(BaseException):
        pass

    class _ProcessLossClient(_StrictReadClient):
        def get_api_key_permissions(self) -> dict[str, object]:
            self.calls.append("api_key_permissions")
            raise _SimulatedProcessLoss()

    client = _ProcessLossClient()
    service = _service(tmp_path, client)
    with pytest.raises(_SimulatedProcessLoss):
        service.refresh_account_reality(
            {},
            _context(idempotency_key="process-loss-after-read-boundary"),
        )

    restarted = _service(tmp_path, client)
    replay = restarted.refresh_account_reality(
        {},
        _context(idempotency_key="process-loss-after-read-boundary"),
    )

    assert replay.status_code == 503
    assert replay.body["status"] == "outcome_unknown"
    assert replay.body["live_coinbase_read_ran"] is True
    assert replay.headers["X-Idempotency-Replayed"] == "true"
    assert client.calls == ["api_key_permissions"]
    audit_text = (tmp_path / "command-audit.jsonl").read_text(encoding="utf-8")
    assert "account_reality_refresh_reads_may_have_run" in audit_text


def test_projection_failure_cannot_publish_terminal_ready_idempotency(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PRIVATE_PORTFOLIO_UUID)

    class _FailingProjectionLog(AdminMvpEvidenceLog):
        account_refresh_append_count = 0

        def append(self, collection: str, key: str, record: object) -> None:
            if collection == "account_reality_refreshes":
                self.account_refresh_append_count += 1
                if self.account_refresh_append_count == 2:
                    raise RuntimeError("withheld projection write failure")
            super().append(collection, key, record)

    class _FailingUnknownOverwriteStore(FileIdempotencyStore):
        def __init__(self, path: Path) -> None:
            super().__init__(path)
            self.put_count = 0

        def put_record(self, record) -> None:
            self.put_count += 1
            if self.put_count >= 3:
                raise RuntimeError("withheld idempotency overwrite failure")
            super().put_record(record)

    evidence_path = tmp_path / "audit-and-account-reality.jsonl"
    client = _StrictReadClient()
    service = AdminMvpService(
        AdminMvpDependencies(
            rest_client=client,
            rest_client_available=True,
            now_factory=lambda: datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc),
        ),
        evidence_log=_FailingProjectionLog(
            {"account_reality_refreshes": evidence_path}
        ),
        idempotency_store=_FailingUnknownOverwriteStore(
            tmp_path / "idempotency.jsonl"
        ),
        audit_store=FileAdminApiAuditStore(tmp_path / "command-audit.jsonl"),
    )

    result = service.refresh_account_reality(
        {},
        _context(idempotency_key="projection-publication-failure"),
    )
    replay = _service(tmp_path, client).refresh_account_reality(
        {},
        _context(idempotency_key="projection-publication-failure"),
    )

    assert result.status_code == 503
    assert result.body["status"] == "outcome_unknown"
    assert replay.status_code == 503
    assert replay.body["status"] == "outcome_unknown"
    assert replay.body["live_coinbase_read_ran"] is True
    assert replay.headers["X-Idempotency-Replayed"] == "true"
    assert client.calls == [
        "api_key_permissions",
        "portfolio_catalog",
        "wallets",
        "product_metadata",
        "best_bid_ask",
        "fee_summary",
    ]
    audit_events = FileAdminApiAuditStore(
        tmp_path / "command-audit.jsonl"
    ).read_recent(limit=10)
    assert audit_events
    assert all(event.status is not AdminApiCommandStatus.ACCEPTED for event in audit_events)
    assert any(
        event.failure_stage == "account_reality_refresh_terminal_quarantined"
        for event in audit_events
    )


def _route_client(
    monkeypatch,
    service: AdminMvpService,
    *,
    role: AdminApiRole,
) -> TestClient:
    app = FastAPI()
    app.include_router(admin_routes.router, prefix="/api/v1")
    app.dependency_overrides[get_authenticated_actor] = lambda: AdminApiActor(
        actor_id="route-operator",
        roles=[role],
    )
    monkeypatch.setattr(admin_routes, "get_admin_mvp_service", lambda: service)
    return TestClient(app)


def test_refresh_route_requires_explicit_headers_and_operator_permission(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", PRIVATE_PORTFOLIO_UUID)
    client = _StrictReadClient()
    service = _service(tmp_path, client)
    operator = _route_client(
        monkeypatch,
        service,
        role=AdminApiRole.OPERATOR,
    )

    missing_headers = operator.post(
        "/api/v1/admin/account-reality/refresh",
        json={},
    )
    assert missing_headers.status_code == 422
    assert client.calls == []

    blank_headers = operator.post(
        "/api/v1/admin/account-reality/refresh",
        json={},
        headers={
            "Idempotency-Key": " ",
            "X-Correlation-Id": " ",
            "X-Operator-Intent": " ",
        },
    )
    assert blank_headers.status_code == 422
    assert client.calls == []

    accepted = operator.post(
        "/api/v1/admin/account-reality/refresh",
        json={"reason": "operator_refresh"},
        headers={
            "Idempotency-Key": "route-refresh-key",
            "X-Correlation-Id": "route-refresh-correlation",
            "X-Operator-Intent": "refresh_account_reality",
        },
    )
    assert accepted.status_code == 200
    AdminAccountRealityRefreshResponse.model_validate(accepted.json())

    viewer = _route_client(monkeypatch, service, role=AdminApiRole.VIEWER)
    denied = viewer.post(
        "/api/v1/admin/account-reality/refresh",
        json={},
        headers={
            "Idempotency-Key": "viewer-route-refresh-key",
            "X-Correlation-Id": "viewer-route-refresh-correlation",
            "X-Operator-Intent": "refresh_account_reality",
        },
    )
    assert denied.status_code == 403
    assert len(client.calls) == 6


def test_refresh_route_openapi_documents_typed_terminal_outcomes() -> None:
    app = FastAPI()
    app.include_router(admin_routes.router, prefix="/api/v1")
    operation = app.openapi()["paths"][
        "/api/v1/admin/account-reality/refresh"
    ]["post"]

    assert {"200", "401", "403", "409", "422", "503"} <= set(
        operation["responses"]
    )
    for status_code in ("409", "503"):
        assert operation["responses"][status_code]["content"][
            "application/json"
        ]["schema"]["$ref"] == (
            "#/components/schemas/AdminAccountRealityRefreshResponse"
        )
    assert "allowance is already consumed" in operation["responses"]["409"][
        "description"
    ]
    assert "authority state is unavailable" in operation["responses"]["503"][
        "description"
    ]
    required_headers = {
        parameter["name"]
        for parameter in operation["parameters"]
        if parameter.get("required") is True
    }
    assert {
        "Idempotency-Key",
        "X-Correlation-Id",
        "X-Operator-Intent",
    } <= required_headers


def test_refresh_route_is_a_dedicated_backend_owned_inventory_command() -> None:
    row = next(
        item
        for item in ADMIN_API_ROUTE_INVENTORY
        if item.surface == "POST /api/v1/admin/account-reality/refresh"
    )

    assert row.module_id == "account_management"
    assert row.action_class is AdminApiActionClass.LOCAL_STATE_MUTATION
    assert row.permission is AdminApiPermission.ACCOUNT_REALITY_REFRESH
    assert row.shared_method == "refresh_account_reality"
    assert row.idempotency == "required"

    service = AdminMvpService()
    capabilities = service.get_read_response(
        "/api/v1/admin/capabilities",
        {},
        _context(idempotency_key="refresh-capabilities"),
    ).body["capabilities"]
    capability = next(
        item
        for item in capabilities
        if item["route"] == "/api/v1/admin/account-reality/refresh"
    )
    assert capability["idempotency"] == "required"
    assert capability["approval"] == "not_required"
    assert capability["caps"] == "not_required"
    assert capability["live_enabled"] is False


def test_refresh_route_has_dedicated_enterprise_mutation_taxonomy() -> None:
    payload = AdminApiReadService().build_enterprise_readiness().model_dump(
        mode="json"
    )
    taxonomy = {
        item["mutation_id"]: item for item in payload["mutation_taxonomy"]
    }

    refresh = taxonomy["admin.account_reality_refresh"]
    assert refresh["command_surfaces"] == [
        "POST /api/v1/admin/account-reality/refresh"
    ]
    assert refresh["required_permissions"] == [
        AdminApiPermission.ACCOUNT_REALITY_REFRESH.value
    ]
    assert refresh["live_adapter_required"] is False
