from __future__ import annotations

from copy import deepcopy
import json
import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.v1.app import create_app
from application.admin_api import futures_order_preview as preview_module
from application.admin_api.futures_order_preview import (
    DEFAULT_FUTURES_PREVIEW_ARTIFACT_PATH,
    FUTURES_PREVIEW_PREDECESSOR_ARTIFACT_PATH,
    FUTURES_PREVIEW_PREDECESSOR_DEVICE,
    FUTURES_PREVIEW_PREDECESSOR_EVIDENCE_SHA256,
    FUTURES_PREVIEW_PREDECESSOR_FILE_SHA256,
    FUTURES_PREVIEW_R3_ARTIFACT_PATH,
    FUTURES_PREVIEW_R3_DEVICE,
    FUTURES_PREVIEW_R3_EVIDENCE_SHA256,
    FUTURES_PREVIEW_R3_FILE_SHA256,
    FUTURES_PREVIEW_R3_INODE,
    FUTURES_PREVIEW_R3_MODE,
    FUTURES_PREVIEW_R3_MTIME_NS,
    FUTURES_PREVIEW_R3_PREDECESSOR_BINDING,
    FUTURES_PREVIEW_R3_SIZE,
    FUTURES_PREVIEW_R4_ARTIFACT_PATH,
    FUTURES_PREVIEW_R4_ARTIFACT_TYPE,
    FUTURES_PREVIEW_R4_DEVICE,
    FUTURES_PREVIEW_R4_EVIDENCE_SHA256,
    FUTURES_PREVIEW_R4_FILE_SHA256,
    FUTURES_PREVIEW_R4_INODE,
    FUTURES_PREVIEW_R4_MODE,
    FUTURES_PREVIEW_R4_MTIME_NS,
    FUTURES_PREVIEW_R4_PREDECESSOR_BINDING,
    FUTURES_PREVIEW_R4_SIZE,
    FUTURES_PREVIEW_R5_ARTIFACT_PATH,
    FUTURES_PREVIEW_R5_ARTIFACT_TYPE,
    FUTURES_PREVIEW_ACTOR_ID,
    FUTURES_PREVIEW_DOCUMENTED_MARGIN_SETTINGS,
    FUTURES_PREVIEW_OPERATIONAL_MARGIN_SETTINGS,
    FUTURES_PREVIEW_DOCUMENTED_CURRENT_MARGIN_WINDOW_TYPES,
    FUTURES_PREVIEW_SLICE2_OPERATOR_MARGIN_WINDOW_POLICY,
    FUTURES_PREVIEW_PRODUCT_ID,
    FuturesOrderPreviewArtifactError,
    FuturesOrderPreviewArtifactStore,
    FuturesOrderPreviewProducer,
    build_futures_order_preview_candidate,
    canonical_sha256,
    configured_futures_order_preview_artifact_path,
    _margin_windows_terminal_context,
    slice2_preview_margin_windows_policy_context,
    _notional_text,
    validate_futures_order_preview_predecessor,
    validate_production_futures_order_preview_r3_predecessor,
    validate_production_futures_order_preview_r4_predecessor,
    validate_margin_collateral_evidence,
    validate_slice2_preview_margin_collateral_evidence,
    validate_preview_response,
)
from application.admin_api.models import (
    AdminFuturesOrderPreviewResponse,
    AdminFuturesPreviewMarginWindowsEvidence,
    AdminFuturesPreviewMarginWindowsPolicyEvidenceV2,
)
from external.coinbase_client import CoinbaseRestClient
from tools import run_admin_api_futures_no_live_preview as preview_tool
from tools import run_admin_api_futures_no_live_preview_r5 as r5_preview_tool
from tools import run_admin_api_futures_no_live_preview_r6 as r6_preview_tool


NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
MISSING = object()
ORIGINAL_SLICE2_BINDING = {
    "artifact_name": "futures_exact_no_live_preview_slice_2.jsonl",
    "file_sha256": "9b15da86c172eca46d4b3dc0fc2b81e9b325df9a1e2f75fef79362f538e2d5ff",
    "evidence_sha256": "3b09cb9dfe02991dc886a1c6f041330d417ff11a0f1d45e3734bdc59bfb219b8",
    "device": "66305",
    "inode": "42312964",
    "size_bytes": 3043,
    "mode": "0400",
    "mtime_ns": "1783968539951853688",
    "status": "blocked",
    "outcome": "blocked",
    "preview_order_attempt_count": 0,
    "exchange_submission_attempt_count": 0,
    "submitted_notional_usdc": "0",
    "executed_notional_usdc": "0",
    "preservation": "immutable_no_modify_delete_or_reuse",
}
R1_SLICE2_BINDING = {
    "artifact_name": "futures_exact_no_live_preview_slice_2r1.jsonl",
    "file_sha256": "55c09c6d4819f2d03dd679ae4c952e203cf540d1a141e13035459821f1b680d7",
    "evidence_sha256": "a1b7820aa217b7119a6353a8f4fbffa5227ebfe5e4c8d8a1cde5449d370fc6f0",
    "device": "66305",
    "inode": "42312970",
    "size_bytes": 4197,
    "mode": "0400",
    "mtime_ns": "1783980960753782357",
    "status": "blocked",
    "outcome": "blocked",
    "preview_order_attempt_count": 0,
    "exchange_submission_attempt_count": 0,
    "submitted_notional_usdc": "0",
    "executed_notional_usdc": "0",
    "preservation": "immutable_no_modify_delete_or_reuse",
    "original_predecessor_binding": ORIGINAL_SLICE2_BINDING,
}
TEST_PREDECESSOR_BINDING = {
    "artifact_name": "futures_exact_no_live_preview_slice_2r2.jsonl",
    "file_sha256": FUTURES_PREVIEW_PREDECESSOR_FILE_SHA256,
    "evidence_sha256": FUTURES_PREVIEW_PREDECESSOR_EVIDENCE_SHA256,
    "device": "66305",
    "inode": "42312480",
    "size_bytes": 6002,
    "mode": "0400",
    "mtime_ns": "1783991637010957407",
    "status": "blocked",
    "outcome": "blocked",
    "preview_order_attempt_count": 0,
    "exchange_submission_attempt_count": 0,
    "submitted_notional_usdc": "0",
    "executed_notional_usdc": "0",
    "preservation": "immutable_no_modify_delete_or_reuse",
    "original_predecessor_binding": R1_SLICE2_BINDING,
}
TEST_R3_PREDECESSOR_BINDING = {
    "artifact_name": "futures_exact_no_live_preview_slice_2r3.jsonl",
    "file_sha256": FUTURES_PREVIEW_R3_FILE_SHA256,
    "evidence_sha256": FUTURES_PREVIEW_R3_EVIDENCE_SHA256,
    "device": str(FUTURES_PREVIEW_R3_DEVICE),
    "inode": str(FUTURES_PREVIEW_R3_INODE),
    "size_bytes": FUTURES_PREVIEW_R3_SIZE,
    "mode": f"{FUTURES_PREVIEW_R3_MODE:04o}",
    "mtime_ns": str(FUTURES_PREVIEW_R3_MTIME_NS),
    "status": "blocked",
    "outcome": "blocked",
    "preview_order_attempt_count": 0,
    "exchange_submission_attempt_count": 0,
    "submitted_notional_usdc": "0",
    "executed_notional_usdc": "0",
    "preservation": "immutable_no_modify_delete_or_reuse",
    "original_predecessor_binding": TEST_PREDECESSOR_BINDING,
}
TEST_R4_PREDECESSOR_BINDING = {
    "artifact_name": "futures_exact_no_live_preview_slice_2r4.jsonl",
    "file_sha256": (
        "90691e5b24c17fca5f3d1a67f942ea0b4b067e262435bcdf37e516f79ebb66cf"
    ),
    "evidence_sha256": (
        "0edeffdb0702ba119a7d9c3e32874b75e295ee596538432df5f7be0a67a4af3e"
    ),
    "device": "66305",
    "inode": "42321812",
    "size_bytes": 9508,
    "mode": "0400",
    "mtime_ns": "1784087822854381595",
    "status": "blocked",
    "outcome": "blocked",
    "preview_order_attempt_count": 0,
    "exchange_submission_attempt_count": 0,
    "submitted_notional_usdc": "0",
    "executed_notional_usdc": "0",
    "preservation": "immutable_no_modify_delete_or_reuse",
    "original_predecessor_binding": TEST_R3_PREDECESSOR_BINDING,
}


def _terminal_predecessor(path: Path) -> tuple[str, str]:
    store = FuturesOrderPreviewArtifactStore(path)
    claim_sha256 = store.reserve(
        {
            "artifact_type": "futures_exact_no_live_preview_slice_2r1",
            "claim_status": "reserved",
            "predecessor_binding": ORIGINAL_SLICE2_BINDING,
        }
    )
    evidence: dict[str, object] = {
        "artifact_type": "futures_exact_no_live_preview_slice_2r1",
        "status": "blocked",
        "outcome": "blocked",
        "claim_sha256": claim_sha256,
        "blocker": (
            "preflight_or_preview_blocked:ValueError:"
            "futures_preview_margin_setting_ambiguous"
        ),
        "predecessor_binding": ORIGINAL_SLICE2_BINDING,
        "attempt_counters": {
            "preview_order": 0,
            "retry": 0,
            "fallback": 0,
            "create_order": 0,
            "cancel_order": 0,
            "close_position": 0,
            "reduce_position": 0,
        },
        "read_counters": {
            "api_key_permissions": 1,
            "portfolio_catalog": 1,
            "product": 1,
            "best_bid_ask": 1,
            "futures_positions": 1,
            "futures_margin_collateral": 1,
        },
        "exchange_submission_attempt_count": 0,
        "submitted_notional_usdc": "0",
        "executed_notional_usdc": "0",
        "artifacts": {
            "execution_marker_created": False,
            "attempt_ledger_created": False,
            "runtime_created": False,
        },
    }
    evidence["evidence_sha256"] = canonical_sha256(evidence)
    store.append_result(evidence)
    return (
        hashlib.sha256(path.read_bytes()).hexdigest(),
        str(evidence["evidence_sha256"]),
    )


def _rewrite_terminal_evidence(
    path: Path,
    evidence: dict[str, object],
) -> None:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    evidence["evidence_sha256"] = canonical_sha256(
        {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    )
    rows[1]["record"] = evidence
    rows[1]["outcome"] = evidence["outcome"]
    rows[1]["record_sha256"] = canonical_sha256(
        {key: value for key, value in rows[1].items() if key != "record_sha256"}
    )
    path.chmod(0o600)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    path.chmod(0o400)


def _permissions(*, can_trade: bool = True) -> dict[str, object]:
    return {
        "portfolio_uuid": "default-portfolio-uuid",
        "portfolio_type": "DEFAULT",
        "can_view": True,
        "can_trade": can_trade,
    }


def _portfolios(*, name: str = "Default") -> list[dict[str, object]]:
    return [
        {
            "uuid": "default-portfolio-uuid",
            "name": name,
            "type": "DEFAULT",
        }
    ]


def _product(
    *,
    price: str = "6.47",
    contract_size: str = "10",
    status: str = "",
) -> dict[str, object]:
    return {
        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
        "display_name": "AVAX PERP",
        "product_type": "FUTURE",
        "status": status,
        "price": price,
        "price_increment": "0.01",
        "base_increment": "1",
        "base_min_size": "1",
        "trading_disabled": False,
        "view_only": False,
        "cancel_only": False,
        "future_product_details": {
            "contract_size": contract_size,
            "contract_code": "AVP",
            "group_description": "Avalanche Perp Futures",
            "group_short_description": "Avalanche Perp",
            "venue": "cde",
            "risk_managed_by": "MANAGED_BY_FCM",
            "contract_expiry": "2030-12-20T16:00:00Z",
            "contract_expiry_type": "EXPIRING",
        },
    }


def _book() -> dict[str, object]:
    return {
        "pricebooks": [
            {
                "product_id": FUTURES_PREVIEW_PRODUCT_ID,
                "bids": [{"price": "6.46", "size": "8"}],
                "asks": [{"price": "6.48", "size": "9"}],
                "time": "2026-07-13T12:00:00Z",
            }
        ]
    }


def _preview() -> dict[str, object]:
    return {
        "preview_id": "preview-avp-1",
        "errs": [],
        "warning": [],
        "order_total": "64.50",
        "commission_total": "0.12",
        "quote_size": "64.50",
        "base_size": "1",
        "best_bid": "6.46",
        "best_ask": "6.48",
        "order_margin_total": "10.00",
        "current_liquidation_buffer": "0.80",
        "projected_liquidation_buffer": "0.75",
        "max_leverage": "4",
        "slippage": "0",
    }


class FakePreviewRestClient:
    def __init__(
        self,
        *,
        preview_error: Exception | None = None,
        preview_response: dict[str, object] | None = None,
        permissions_response: dict[str, object] | None = None,
        portfolios_response: list[dict[str, object]] | None = None,
    ) -> None:
        self.preview_error = preview_error
        self.preview_response = preview_response or _preview()
        self.permissions_response = permissions_response or _permissions()
        self.portfolios_response = portfolios_response or _portfolios()
        self.preview_calls: list[dict[str, object]] = []
        self.forbidden_calls: list[str] = []
        self.read_calls: list[str] = []

    def get_api_key_permissions(self) -> dict[str, object]:
        self.read_calls.append("api_key_permissions")
        return self.permissions_response

    def list_portfolios(self) -> list[dict[str, object]]:
        self.read_calls.append("portfolio_catalog")
        return self.portfolios_response

    def get_product_dict(self, product_id: str) -> dict[str, object]:
        self.read_calls.append("product")
        assert product_id == FUTURES_PREVIEW_PRODUCT_ID
        return _product()

    def get_best_bid_ask(self, *, product_ids: list[str]) -> dict[str, object]:
        self.read_calls.append("best_bid_ask")
        assert product_ids == [FUTURES_PREVIEW_PRODUCT_ID]
        return _book()

    def get_futures_positions(self) -> dict[str, object]:
        self.read_calls.append("futures_positions")
        return {}

    def get_futures_margin_collateral_snapshot(self) -> dict[str, object]:
        self.read_calls.append("futures_margin_collateral")
        return {
            "status": "ready",
            "account_family": "coinbase_futures_us_cfm",
            "source": "backend_rest_client",
            "source_read_attempts": {
                "get_futures_balance_summary": 1,
                "get_intraday_margin_setting": 1,
                "get_current_margin_window": 2,
                "list_futures_sweeps": 1,
            },
            "balance_summary": {
                "available_margin": {"value": "250.00", "currency": "USD"},
                "total_usd_balance": {"value": "500.00", "currency": "USD"},
                "cfm_usd_balance": {"value": "500.00", "currency": "USD"},
                "futures_buying_power": {
                    "value": "1000.00",
                    "currency": "USD",
                },
                "initial_margin": {"value": "40.00", "currency": "USD"},
                "liquidation_threshold": {
                    "value": "80.00",
                    "currency": "USD",
                },
                "intraday_margin_window_measure": {
                    "margin_window_type": "FCM_MARGIN_WINDOW_TYPE_INTRADAY",
                    "maintenance_margin": "20.00",
                    "liquidation_buffer": "420.00",
                },
            },
            "intraday_margin_setting": {
                "setting": "INTRADAY_MARGIN_SETTING_STANDARD",
            },
            "current_margin_windows": [
                {
                    "profile": "MARGIN_PROFILE_TYPE_RETAIL_REGULAR",
                    "status": "ready",
                    "margin_window": {
                        "margin_window_type": "MARGIN_WINDOW_TYPE_INTRADAY",
                    },
                    "is_intraday_margin_killswitch_enabled": False,
                    "is_intraday_margin_enrollment_killswitch_enabled": False,
                },
                {
                    "profile": "MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1",
                    "status": "ready",
                    "margin_window": {
                        "margin_window_type": "MARGIN_WINDOW_TYPE_INTRADAY",
                    },
                    "is_intraday_margin_killswitch_enabled": False,
                    "is_intraday_margin_enrollment_killswitch_enabled": False,
                },
            ],
            "futures_sweeps": [],
            "errors": [],
            "intx_applicability": "not_applicable_us_account",
        }

    def preview_order(self, **kwargs: object) -> dict[str, object]:
        self.read_calls.append("preview_order")
        self.preview_calls.append(dict(kwargs))
        if self.preview_error is not None:
            raise self.preview_error
        return self.preview_response

    def __getattr__(self, name: str):
        if name in {
            "create_order",
            "place_limit_order",
            "limit_order_gtc",
            "cancel_order",
            "cancel_orders",
            "close_position",
        }:
            def forbidden(*_args: object, **_kwargs: object) -> None:
                self.forbidden_calls.append(name)
                raise AssertionError(f"forbidden mutation called: {name}")

            return forbidden
        raise AttributeError(name)


def _producer(
    tmp_path: Path,
    rest_client: FakePreviewRestClient,
    *,
    artifact_type: str = "futures_exact_no_live_preview_slice_2r3",
    predecessor_binding: dict[str, object] | None = None,
):
    path = tmp_path / "futures-preview.jsonl"
    store = FuturesOrderPreviewArtifactStore(path)
    bound_predecessor = predecessor_binding or TEST_PREDECESSOR_BINDING
    producer = FuturesOrderPreviewProducer(
        rest_client=rest_client,
        store=store,
        predecessor_binding=bound_predecessor,
        predecessor_validator=lambda: dict(bound_predecessor),
        artifact_type=artifact_type,
        now=lambda: NOW,
        correlation_id_factory=lambda: "8f604e56-0a23-4bda-b244-11ebc0194241",
        idempotency_key_factory=lambda: "2d8327f6-826c-4f73-82a4-822e29f73065",
    )
    return producer, store, path


@pytest.mark.parametrize(
    ("price", "contract_size", "expected"),
    [
        ("6.47", "10", ("64.80", "77.76", "142.56")),
        ("10", "10", None),  # opening/reference equality at 100 is blocked
        ("12.50", "10", None),  # exposure and buffered-close cap boundary
    ],
)
def test_candidate_uses_one_contract_and_strict_slice_caps(
    price: str,
    contract_size: str,
    expected: tuple[str, str, str] | None,
):
    if expected is None:
        with pytest.raises(ValueError, match="cap"):
            build_futures_order_preview_candidate(
                product=_product(price=price, contract_size=contract_size),
                book=_book(),
                positions={},
                observed_at=NOW,
            )
        return

    candidate = build_futures_order_preview_candidate(
        product=_product(price=price, contract_size=contract_size),
        book=_book(),
        positions={},
        observed_at=NOW,
    )

    assert candidate["product_id"] == FUTURES_PREVIEW_PRODUCT_ID
    assert candidate["contract_count"] == "1"
    assert candidate["limit_price"] == "6.45"
    assert candidate["opening_reference_notional_usdc"] == expected[0]
    assert candidate["maximum_exposure_reference_notional_usdc"] == expected[0]
    assert candidate["buffered_close_reference_notional_usdc"] == expected[1]
    assert candidate["branch_turnover_reference_notional_usdc"] == expected[2]
    assert Decimal(candidate["opening_cap_usdc"]) == Decimal("100")
    assert Decimal(candidate["exposure_cap_usdc"]) == Decimal("150")
    assert Decimal(candidate["turnover_cap_usdc"]) == Decimal("300")


def test_candidate_truthfully_classifies_exact_cfm_avp_contract_as_perp_style():
    candidate = build_futures_order_preview_candidate(
        product=_product(),
        book=_book(),
        positions={},
        observed_at=NOW,
    )

    assert candidate["product_classification"] == "PERP_STYLE_FUTURE"
    assert candidate["contract_expiry_type"] == "EXPIRING"
    assert candidate["contract_expiry"] == "2030-12-20T16:00:00Z"
    assert candidate["risk_managed_by"] == "MANAGED_BY_FCM"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda product: product.pop("status"),
        lambda product: product.update(status="offline"),
        lambda product: product["future_product_details"].pop("contract_code"),
        lambda product: product["future_product_details"].update(
            contract_code="BTC"
        ),
        lambda product: product["future_product_details"].pop(
            "group_description"
        ),
        lambda product: product["future_product_details"].update(
            group_description="Avalanche Futures"
        ),
        lambda product: product["future_product_details"].pop(
            "group_short_description"
        ),
        lambda product: product["future_product_details"].update(
            group_short_description="Avalanche"
        ),
        lambda product: product["future_product_details"].pop("venue"),
        lambda product: product["future_product_details"].update(venue="intx"),
        lambda product: product["future_product_details"].pop(
            "risk_managed_by"
        ),
        lambda product: product["future_product_details"].update(
            risk_managed_by="MANAGED_BY_VENUE"
        ),
        lambda product: product["future_product_details"].pop(
            "contract_expiry"
        ),
        lambda product: product["future_product_details"].update(
            contract_expiry="2026-12-20T16:00:00Z"
        ),
        lambda product: product["future_product_details"].pop(
            "contract_expiry_type"
        ),
        lambda product: product["future_product_details"].update(
            contract_expiry_type="PERPETUAL"
        ),
        lambda product: product["future_product_details"].update(
            contract_size="5"
        ),
    ],
)
def test_candidate_rejects_missing_or_mismatched_cfm_perp_style_identity(mutation):
    product = _product()
    mutation(product)

    with pytest.raises(ValueError, match="product|avp|trad|perp|contract"):
        build_futures_order_preview_candidate(
            product=product,
            book=_book(),
            positions={},
            observed_at=NOW,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda product: product.pop("view_only"),
        lambda product: product.update(view_only=True),
        lambda product: product.update(display_name="AVP Future"),
        lambda product: product.update(status="offline"),
        lambda product: product.update(cancel_only=True),
    ],
)
def test_candidate_fails_closed_on_ambiguous_avax_perp_tradability(mutation):
    product = _product()
    mutation(product)

    with pytest.raises(ValueError, match="product|avp|trad"):
        build_futures_order_preview_candidate(
            product=product,
            book=_book(),
            positions={},
            observed_at=NOW,
        )


def test_producer_reserves_before_one_exact_preview_and_never_mutates(tmp_path: Path):
    rest_client = FakePreviewRestClient()
    producer, store, path = _producer(tmp_path, rest_client)

    evidence = producer.run()

    assert rest_client.read_calls == [
        "api_key_permissions",
        "portfolio_catalog",
        "product",
        "best_bid_ask",
        "futures_positions",
        "futures_margin_collateral",
        "preview_order",
    ]
    assert len(rest_client.preview_calls) == 1
    assert rest_client.preview_calls[0] == evidence["preview_request"]
    assert rest_client.preview_calls[0] == {
        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
        "side": "BUY",
        "order_configuration": {
            "limit_limit_gtc": {
                "base_size": "1",
                "limit_price": "6.45",
                "post_only": True,
            }
        },
    }
    assert rest_client.forbidden_calls == []
    assert evidence["actor_id"] == FUTURES_PREVIEW_ACTOR_ID
    assert evidence["roles"] == ["trader"]
    assert evidence["attempt_counters"] == {
        "preview_order": 1,
        "retry": 0,
        "fallback": 0,
        "create_order": 0,
        "cancel_order": 0,
        "close_position": 0,
        "reduce_position": 0,
    }
    assert evidence["submitted_notional_usdc"] == "0"
    assert evidence["executed_notional_usdc"] == "0"
    assert evidence["live_execution"] == "not_run"
    assert evidence["live_coinbase_execution"] == "not_run"
    assert evidence["live_coinbase_read_ran"] is True
    assert evidence["exchange_submission_attempt_count"] == 0
    assert evidence["artifacts"] == {
        "execution_marker_created": False,
        "attempt_ledger_created": False,
        "runtime_created": False,
    }
    assert evidence["preview_response"]["preview_id"] == "preview-avp-1"
    assert evidence["preview_response"]["commission_total"] == "0.12"
    assert evidence["preview_response"]["order_margin_total"] == "10.00"
    assert evidence["preview_response"]["current_liquidation_buffer"] == "0.80"
    assert evidence["preview_response"]["projected_liquidation_buffer"] == "0.75"
    assert evidence["margin_collateral_evidence"]["status"] == "ready"
    assert evidence["margin_collateral_evidence"]["sanitized"] is True
    assert evidence["margin_collateral_evidence"]["raw_response_included"] is False
    assert evidence["position_evidence"] == {
        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
        "observed_contract_count": "0",
        "sanitized": True,
        "raw_response_included": False,
    }
    assert evidence["read_counters"] == {
        "api_key_permissions": 1,
        "portfolio_catalog": 1,
        "product": 1,
        "best_bid_ask": 1,
        "futures_positions": 1,
        "futures_margin_collateral": 1,
    }
    assert evidence["seal_ready_plan_sha256"] == canonical_sha256(
        evidence["seal_ready_plan"]
    )
    authoritative_preview = evidence["seal_ready_plan"]["authoritative_preview"]
    assert authoritative_preview["preview_id"] == "preview-avp-1"
    assert authoritative_preview["preview_response"] == evidence["preview_response"]
    assert authoritative_preview["preview_response_sha256"] == evidence[
        "preview_response_sha256"
    ]
    assert authoritative_preview["candidate_binding"] == evidence[
        "preview_response"
    ]["candidate_binding"]
    assert authoritative_preview["commission_total"] == "0.12"
    assert authoritative_preview["order_margin_total"] == "10.00"
    assert authoritative_preview["liquidation_evidence_source"] == (
        "current_and_projected_liquidation_buffer"
    )
    assert evidence["evidence_sha256"] == canonical_sha256(
        {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    )
    assert store.read_completed() == evidence
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_attempt_artifact_withholds_raw_margin_and_account_payloads(
    tmp_path: Path,
):
    rest_client = FakePreviewRestClient(
        permissions_response={
            **_permissions(),
            "credential_material": "must-not-be-persisted-permission",
        },
        portfolios_response=[
            {
                **_portfolios()[0],
                "private_account_label": "must-not-be-persisted-portfolio",
            }
        ],
    )
    snapshot = rest_client.get_futures_margin_collateral_snapshot()
    snapshot["raw_account_payload"] = "must-not-be-persisted-margin"
    snapshot["balance_summary"]["unneeded_private_balance"] = {
        "value": "999999.99",
        "currency": "USD",
    }
    rest_client.read_calls.clear()
    rest_client.get_futures_margin_collateral_snapshot = (  # type: ignore[method-assign]
        lambda: snapshot
    )
    producer, _store, path = _producer(tmp_path, rest_client)

    evidence = producer.run()
    serialized = path.read_text(encoding="utf-8")

    assert "must-not-be-persisted" not in serialized
    assert evidence["permission_evidence"]["sanitized"] is True
    assert evidence["permission_evidence"]["raw_response_included"] is False
    assert evidence["portfolio_catalog_evidence"]["sanitized"] is True
    assert evidence["portfolio_catalog_evidence"]["raw_response_included"] is False
    assert evidence["margin_collateral_evidence"]["sanitized"] is True
    assert evidence["margin_collateral_evidence"]["raw_response_included"] is False


def test_producer_reserves_before_first_coinbase_read(tmp_path: Path):
    rest_client = FakePreviewRestClient()
    producer, _store, path = _producer(tmp_path, rest_client)

    def permission_read() -> dict[str, object]:
        assert path.is_file()
        rows = path.read_text(encoding="utf-8").splitlines()
        assert len(rows) == 1
        assert json.loads(rows[0])["record_type"] == "claim"
        return _permissions()

    rest_client.get_api_key_permissions = permission_read  # type: ignore[method-assign]

    producer.run()


@pytest.mark.parametrize(
    ("identifier_field", "consumed_identifier"),
    [
        (identifier_field, consumed_identifier)
        for identifier_field in ("correlation_id", "idempotency_key")
        for consumed_identifier in (
            "9c26aed6-fce5-470b-b57e-b89423ecc0ed",
            "1396cd8f-d258-446f-92e1-fc53f6b93c71",
            "5dcd3d52-95bf-4fd3-93ca-83e8be28f132",
            "d1a930f2-0e91-42e0-8a22-a20444575585",
            "6cfffc61-2d69-4559-8729-ad3c5a8f9751",
            "f26dbcc6-4336-4bb1-a317-6c5a3d87d2d0",
            "5eaffbc0-4db9-40d5-b17a-3ec7c56bf700",
            "f5285420-6891-4daf-885d-f3ffeacd7218",
            "f32948c1-6bf1-421a-9267-6138ec2228ae",
            "77016c90-d1e1-4344-84c7-53b3c2dca70b",
        )
    ],
)
def test_r3_rejects_every_consumed_identifier_before_claim_or_coinbase_read(
    tmp_path: Path,
    identifier_field: str,
    consumed_identifier: str,
):
    path = tmp_path / "slice2r3.jsonl"
    rest_client = FakePreviewRestClient()
    fresh_correlation_id = "8f604e56-0a23-4bda-b244-11ebc0194241"
    fresh_idempotency_key = "2d8327f6-826c-4f73-82a4-822e29f73065"
    producer = FuturesOrderPreviewProducer(
        rest_client=rest_client,
        store=FuturesOrderPreviewArtifactStore(path),
        predecessor_binding=TEST_PREDECESSOR_BINDING,
        predecessor_validator=lambda: dict(TEST_PREDECESSOR_BINDING),
        now=lambda: NOW,
        correlation_id_factory=lambda: (
            consumed_identifier
            if identifier_field == "correlation_id"
            else fresh_correlation_id
        ),
        idempotency_key_factory=lambda: (
            consumed_identifier
            if identifier_field == "idempotency_key"
            else fresh_idempotency_key
        ),
    )

    with pytest.raises(FuturesOrderPreviewArtifactError, match="fresh"):
        producer.run()

    assert rest_client.read_calls == []
    assert not path.exists()


def test_missing_default_trade_permission_and_margin_ambiguity_block_pre_preview(
    tmp_path: Path,
):
    no_trade = FakePreviewRestClient()
    no_trade.get_api_key_permissions = (  # type: ignore[method-assign]
        lambda: _permissions(can_trade=False)
    )
    producer, store, _path = _producer(tmp_path / "no-trade", no_trade)
    with pytest.raises(FuturesOrderPreviewArtifactError, match="blocked"):
        producer.run()
    assert no_trade.preview_calls == []
    assert store.read_completed()["status"] == "blocked"
    assert store.read_completed()["attempt_counters"]["preview_order"] == 0

    ambiguous_margin = FakePreviewRestClient()
    ambiguous_margin.get_futures_margin_collateral_snapshot = (  # type: ignore[method-assign]
        lambda: {
            "status": "blocked",
            "account_family": "coinbase_futures_us_cfm",
            "errors": [{"method": "get_futures_balance_summary"}],
        }
    )
    producer, store, _path = _producer(
        tmp_path / "ambiguous-margin",
        ambiguous_margin,
    )
    with pytest.raises(FuturesOrderPreviewArtifactError, match="blocked"):
        producer.run()
    assert ambiguous_margin.preview_calls == []
    assert store.read_completed()["read_counters"]["futures_margin_collateral"] == 1


def test_margin_setting_enum_matches_official_coinbase_docs_exactly():
    assert FUTURES_PREVIEW_DOCUMENTED_MARGIN_SETTINGS == {
        "INTRADAY_MARGIN_SETTING_UNSPECIFIED",
        "INTRADAY_MARGIN_SETTING_STANDARD",
        "INTRADAY_MARGIN_SETTING_INTRADAY",
    }
    assert FUTURES_PREVIEW_OPERATIONAL_MARGIN_SETTINGS == {
        "INTRADAY_MARGIN_SETTING_STANDARD",
        "INTRADAY_MARGIN_SETTING_INTRADAY",
    }


@pytest.mark.parametrize(
    "setting",
    [
        "INTRADAY_MARGIN_SETTING_STANDARD",
        "INTRADAY_MARGIN_SETTING_INTRADAY",
    ],
)
def test_exact_operational_margin_settings_may_reach_preview(
    tmp_path: Path,
    setting: str,
):
    rest_client = FakePreviewRestClient()
    private_product = _product()
    private_product["private_product_payload"] = "PRIVATE_R5_PRODUCT_PAYLOAD"
    rest_client.get_product_dict = (  # type: ignore[method-assign]
        lambda _product_id: private_product
    )
    snapshot = rest_client.get_futures_margin_collateral_snapshot()
    snapshot["intraday_margin_setting"] = {"setting": setting}
    rest_client.read_calls.clear()
    rest_client.get_futures_margin_collateral_snapshot = (  # type: ignore[method-assign]
        lambda: snapshot
    )
    producer, _store, _path = _producer(tmp_path, rest_client)

    evidence = producer.run()

    assert evidence["status"] == "accepted"
    assert evidence["attempt_counters"]["preview_order"] == 1
    assert evidence["margin_setting_evidence"]["allowlist_match"] is True
    assert evidence["margin_setting_evidence"]["operationally_resolved"] is True
    assert len(rest_client.preview_calls) == 1


@pytest.mark.parametrize(
    "setting",
    [
        "INTRADAY_MARGIN_SETTING_UNSPECIFIED",
        "INTRADAY_MARGIN_SETTING_ENABLED",
        "INTRADAY_MARGIN_SETTING_DISABLED",
    ],
)
def test_non_operational_margin_settings_stop_before_preview(
    tmp_path: Path,
    setting: str,
):
    rest_client = FakePreviewRestClient()
    snapshot = rest_client.get_futures_margin_collateral_snapshot()
    snapshot["intraday_margin_setting"] = {"setting": setting}
    rest_client.read_calls.clear()
    rest_client.get_futures_margin_collateral_snapshot = (  # type: ignore[method-assign]
        lambda: snapshot
    )
    producer, store, _path = _producer(tmp_path, rest_client)

    with pytest.raises(FuturesOrderPreviewArtifactError, match="blocked"):
        producer.run()

    terminal = store.read_completed()
    diagnostic = terminal["margin_setting_evidence"]
    expected_documented = setting == "INTRADAY_MARGIN_SETTING_UNSPECIFIED"
    assert terminal["attempt_counters"]["preview_order"] == 0
    assert rest_client.preview_calls == []
    assert diagnostic["allowlist_match"] is expected_documented
    assert diagnostic["operationally_resolved"] is False
    assert terminal["blocker"] == "preflight_or_preview_stage_blocked"
    if not expected_documented:
        assert diagnostic["observed_token"] is None
        assert setting not in json.dumps(terminal)


@pytest.mark.parametrize(
    ("setting", "expected_value"),
    [
        ("INTRADAY_MARGIN_SETTING_STANDARD", "INTRADAY_MARGIN_SETTING_STANDARD"),
        ("private\nvalue", None),
    ],
)
def test_margin_setting_block_preserves_only_sanitized_pre_preview_evidence(
    tmp_path: Path,
    setting: str,
    expected_value: str | None,
):
    rest_client = FakePreviewRestClient()
    snapshot = rest_client.get_futures_margin_collateral_snapshot()
    snapshot["intraday_margin_setting"] = {
        "setting": setting,
        "credential_material": "must-never-reach-artifact-or-api",
    }
    rest_client.read_calls.clear()
    rest_client.get_futures_margin_collateral_snapshot = (  # type: ignore[method-assign]
        lambda: snapshot
    )
    producer, store, _path = _producer(tmp_path, rest_client)

    with pytest.raises(FuturesOrderPreviewArtifactError, match="blocked"):
        producer.run()

    terminal = store.read_completed()
    diagnostic = terminal["margin_setting_evidence"]
    assert terminal["attempt_counters"]["preview_order"] == 0
    assert rest_client.preview_calls == []
    assert "margin_collateral_evidence" not in terminal
    assert diagnostic == {
        "source": "backend_rest_client.get_intraday_margin_setting",
        "stage": "margin_collateral_validation",
        "field_path": "intraday_margin_setting.setting",
        "container_present": True,
        "container_type": "mapping",
        "field_present": True,
        "value_type": "string",
        "token_form": (
            "safe_enum_token" if expected_value is not None else "malformed_string"
        ),
        "observed_token": expected_value,
        "allowlist_match": expected_value is not None,
        "operationally_resolved": expected_value is not None,
        "enum_authority": "official_coinbase_advanced_trade_api_docs",
        "classification": (
            "recognized_string"
            if expected_value is not None
            else "malformed_string"
        ),
        "unexpected_field_count": 1,
        "sanitized": True,
        "raw_response_included": False,
    }
    assert terminal["margin_setting_evidence_sha256"] == canonical_sha256(
        diagnostic
    )
    assert "must-never-reach-artifact-or-api" not in json.dumps(terminal)
    AdminFuturesOrderPreviewResponse.model_validate(terminal)


@pytest.mark.parametrize(
    (
        "container",
        "container_type",
        "value_type",
        "classification",
    ),
    [
        (MISSING, "missing", "missing", "missing_container"),
        (None, "null", "missing", "non_mapping_container"),
        ("not-a-container", "string", "missing", "non_mapping_container"),
        ({}, "mapping", "missing", "missing_field"),
        ({"setting": None}, "mapping", "null", "null_value"),
        ({"setting": True}, "mapping", "boolean", "non_string_value"),
        ({"setting": 1}, "mapping", "number", "non_string_value"),
        ({"setting": {}}, "mapping", "mapping", "non_string_value"),
        ({"setting": []}, "mapping", "sequence", "non_string_value"),
    ],
)
def test_margin_setting_shape_failures_are_controlled_and_never_echo_raw_values(
    tmp_path: Path,
    container: object,
    container_type: str,
    value_type: str,
    classification: str,
):
    rest_client = FakePreviewRestClient()
    snapshot = rest_client.get_futures_margin_collateral_snapshot()
    if container is MISSING:
        snapshot.pop("intraday_margin_setting")
    else:
        snapshot["intraday_margin_setting"] = container
    rest_client.read_calls.clear()
    rest_client.get_futures_margin_collateral_snapshot = (  # type: ignore[method-assign]
        lambda: snapshot
    )
    producer, store, _path = _producer(tmp_path, rest_client)

    with pytest.raises(FuturesOrderPreviewArtifactError, match="blocked"):
        producer.run()

    terminal = store.read_completed()
    diagnostic = terminal["margin_setting_evidence"]
    assert terminal["blocker"] == "preflight_or_preview_stage_blocked"
    assert terminal["attempt_counters"]["preview_order"] == 0
    assert rest_client.preview_calls == []
    assert diagnostic["container_type"] == container_type
    assert diagnostic["value_type"] == value_type
    assert diagnostic["classification"] == classification
    assert diagnostic["observed_token"] is None
    assert diagnostic["allowlist_match"] is False
    assert diagnostic["operationally_resolved"] is False
    assert diagnostic["enum_authority"] == (
        "official_coinbase_advanced_trade_api_docs"
    )
    assert diagnostic["raw_response_included"] is False
    assert "not-a-container" not in json.dumps(terminal)
    AdminFuturesOrderPreviewResponse.model_validate(terminal)


def test_external_preflight_exception_text_is_never_persisted(
    tmp_path: Path,
):
    rest_client = FakePreviewRestClient()

    def permission_read() -> dict[str, object]:
        raise RuntimeError("PRIVATE_HTTP_RESPONSE_BODY_MUST_NOT_PERSIST")

    rest_client.get_api_key_permissions = permission_read  # type: ignore[method-assign]
    producer, store, path = _producer(tmp_path, rest_client)

    with pytest.raises(FuturesOrderPreviewArtifactError, match="blocked"):
        producer.run()

    terminal = store.read_completed()
    assert terminal["blocker"] == "preflight_or_preview_blocked:RuntimeError"
    assert "PRIVATE_HTTP_RESPONSE_BODY_MUST_NOT_PERSIST" not in path.read_text(
        encoding="utf-8"
    )


def test_remaining_margin_stage_reports_only_allowlisted_sanitized_reason(
    tmp_path: Path,
):
    rest_client = FakePreviewRestClient()
    snapshot = rest_client.get_futures_margin_collateral_snapshot()
    snapshot["balance_summary"]["available_margin"]["currency"] = (
        "PRIVATE_CURRENCY_VALUE_MUST_NOT_PERSIST"
    )
    rest_client.read_calls.clear()
    rest_client.get_futures_margin_collateral_snapshot = (  # type: ignore[method-assign]
        lambda: snapshot
    )
    producer, store, path = _producer(tmp_path, rest_client)

    with pytest.raises(FuturesOrderPreviewArtifactError, match="blocked"):
        producer.run()

    terminal = store.read_completed()
    diagnostic = terminal["pre_preview_stage_evidence"]
    assert diagnostic == {
        "schema_version": "1",
        "source": "backend_futures_preview_producer",
        "stages": [
            {
                "stage": "remaining_margin_validation",
                "status": "blocked",
                "reason_code": (
                    "futures_preview_available_margin_currency_invalid"
                ),
            }
        ],
        "sanitized": True,
        "raw_response_included": False,
        "external_exception_text_included": False,
        "identifier_values_included": False,
    }
    assert terminal["pre_preview_stage_evidence_sha256"] == canonical_sha256(
        diagnostic
    )
    assert terminal["attempt_counters"] == {
        "preview_order": 0,
        "retry": 0,
        "fallback": 0,
        "create_order": 0,
        "cancel_order": 0,
        "close_position": 0,
        "reduce_position": 0,
    }
    assert terminal["blocker"] == "preflight_or_preview_stage_blocked"
    assert rest_client.preview_calls == []
    assert "PRIVATE_CURRENCY_VALUE_MUST_NOT_PERSIST" not in path.read_text(
        encoding="utf-8"
    )
    AdminFuturesOrderPreviewResponse.model_validate(terminal)


def test_candidate_stage_reports_passed_margin_and_allowlisted_reason(
    tmp_path: Path,
):
    rest_client = FakePreviewRestClient()
    secret_product = _product(price="PRIVATE_PRODUCT_VALUE_MUST_NOT_PERSIST")
    rest_client.get_product_dict = (  # type: ignore[method-assign]
        lambda _product_id: secret_product
    )
    producer, store, path = _producer(tmp_path, rest_client)

    with pytest.raises(FuturesOrderPreviewArtifactError, match="blocked"):
        producer.run()

    terminal = store.read_completed()
    diagnostic = terminal["pre_preview_stage_evidence"]
    assert diagnostic["stages"] == [
        {
            "stage": "remaining_margin_validation",
            "status": "passed",
            "reason_code": None,
        },
        {
            "stage": "candidate_construction",
            "status": "blocked",
            "reason_code": "futures_preview_product_price_invalid",
        },
    ]
    assert terminal["pre_preview_stage_evidence_sha256"] == canonical_sha256(
        diagnostic
    )
    assert terminal["attempt_counters"]["preview_order"] == 0
    assert rest_client.preview_calls == []
    assert "PRIVATE_PRODUCT_VALUE_MUST_NOT_PERSIST" not in path.read_text(
        encoding="utf-8"
    )
    AdminFuturesOrderPreviewResponse.model_validate(terminal)


@pytest.mark.parametrize(
    ("attribute", "expected_stages", "fallback_reason"),
    [
        (
            "_margin_setting_terminal_context",
            [],
            "futures_preview_remaining_margin_validation_unclassified",
        ),
        (
            "validate_margin_collateral_evidence",
            [],
            "futures_preview_remaining_margin_validation_unclassified",
        ),
        (
            "build_futures_order_preview_candidate",
            ["remaining_margin_validation"],
            "futures_preview_candidate_construction_unclassified",
        ),
        (
            "_preview_request",
            ["remaining_margin_validation", "candidate_construction"],
            "futures_preview_request_construction_unclassified",
        ),
        (
            "_terminal_attempt_context",
            [
                "remaining_margin_validation",
                "candidate_construction",
                "preview_request_construction",
            ],
            "futures_preview_terminal_context_sanitization_unclassified",
        ),
    ],
    ids=("margin-context", "margin", "candidate", "request", "context"),
)
def test_each_pre_preview_stage_withholds_unexpected_exception_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
    expected_stages: list[str],
    fallback_reason: str,
):
    secret = f"PRIVATE_{attribute.upper()}_EXCEPTION_MUST_NOT_PERSIST"

    def fail(*_args, **_kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(preview_module, attribute, fail)
    rest_client = FakePreviewRestClient()
    producer, store, path = _producer(tmp_path, rest_client)

    with pytest.raises(FuturesOrderPreviewArtifactError, match="blocked"):
        producer.run()

    terminal = store.read_completed()
    rows = terminal["pre_preview_stage_evidence"]["stages"]
    assert [row["stage"] for row in rows[:-1]] == expected_stages
    assert all(
        row == {"stage": stage, "status": "passed", "reason_code": None}
        for row, stage in zip(rows[:-1], expected_stages, strict=True)
    )
    assert rows[-1]["status"] == "blocked"
    assert rows[-1]["reason_code"] == fallback_reason
    assert terminal["attempt_counters"]["preview_order"] == 0
    assert terminal["exchange_submission_attempt_count"] == 0
    assert terminal["submitted_notional_usdc"] == "0"
    assert terminal["executed_notional_usdc"] == "0"
    assert rest_client.preview_calls == []
    assert terminal["blocker"] == "preflight_or_preview_stage_blocked"
    serialized = path.read_text(encoding="utf-8")
    assert secret not in serialized
    assert "RuntimeError" not in serialized


def test_safe_looking_unknown_value_error_is_not_promoted_to_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    secret = "SAFE_LOOKING_PRIVATE_VALIDATION_TOKEN"

    def fail(_candidate):
        raise ValueError(secret)

    monkeypatch.setattr(preview_module, "_preview_request", fail)
    rest_client = FakePreviewRestClient()
    producer, store, path = _producer(tmp_path, rest_client)

    with pytest.raises(FuturesOrderPreviewArtifactError, match="blocked"):
        producer.run()

    terminal = store.read_completed()
    assert terminal["pre_preview_stage_evidence"]["stages"][-1] == {
        "stage": "preview_request_construction",
        "status": "blocked",
        "reason_code": "futures_preview_request_construction_unclassified",
    }
    assert secret not in path.read_text(encoding="utf-8")
    assert rest_client.preview_calls == []


def test_margin_snapshot_normalization_failure_is_sanitized_as_first_stage(
    tmp_path: Path,
):
    secret = "PRIVATE_MARGIN_CONVERTER_FAILURE_MUST_NOT_PERSIST"

    class ExplodingSnapshot:
        def to_dict(self):
            raise RuntimeError(secret)

    rest_client = FakePreviewRestClient()
    rest_client.get_futures_margin_collateral_snapshot = (  # type: ignore[method-assign]
        lambda: ExplodingSnapshot()
    )
    producer, store, path = _producer(tmp_path, rest_client)

    with pytest.raises(FuturesOrderPreviewArtifactError, match="blocked"):
        producer.run()

    terminal = store.read_completed()
    assert terminal["pre_preview_stage_evidence"]["stages"] == [
        {
            "stage": "remaining_margin_validation",
            "status": "blocked",
            "reason_code": (
                "futures_preview_remaining_margin_validation_unclassified"
            ),
        }
    ]
    assert terminal["blocker"] == "preflight_or_preview_stage_blocked"
    assert terminal["attempt_counters"]["preview_order"] == 0
    assert terminal["read_counters"] == {
        "api_key_permissions": 1,
        "portfolio_catalog": 1,
        "product": 1,
        "best_bid_ask": 1,
        "futures_positions": 1,
        "futures_margin_collateral": 1,
    }
    assert secret not in path.read_text(encoding="utf-8")
    AdminFuturesOrderPreviewResponse.model_validate(terminal)


def test_stage_diagnostic_readback_rejects_hash_order_and_authority_drift(
    tmp_path: Path,
):
    rest_client = FakePreviewRestClient()
    rest_client.get_product_dict = (  # type: ignore[method-assign]
        lambda _product_id: _product(price="not-a-price")
    )
    producer, store, _path = _producer(tmp_path, rest_client)
    with pytest.raises(FuturesOrderPreviewArtifactError, match="blocked"):
        producer.run()
    terminal = store.read_completed()

    def mutated() -> dict[str, object]:
        return json.loads(json.dumps(terminal))

    def rehash(evidence: dict[str, object]) -> None:
        diagnostic = evidence["pre_preview_stage_evidence"]
        evidence["pre_preview_stage_evidence_sha256"] = canonical_sha256(
            diagnostic
        )
        evidence["evidence_sha256"] = canonical_sha256(
            {
                key: value
                for key, value in evidence.items()
                if key != "evidence_sha256"
            }
        )

    attacks: list[dict[str, object]] = []

    wrong_hash = mutated()
    wrong_hash["pre_preview_stage_evidence_sha256"] = "0" * 64
    wrong_hash["evidence_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in wrong_hash.items()
            if key != "evidence_sha256"
        }
    )
    attacks.append(wrong_hash)

    reordered = mutated()
    reordered_diagnostic = reordered["pre_preview_stage_evidence"]
    assert isinstance(reordered_diagnostic, dict)
    reordered_diagnostic["stages"].reverse()
    rehash(reordered)
    attacks.append(reordered)

    passed_reason = mutated()
    passed_reason_diagnostic = passed_reason["pre_preview_stage_evidence"]
    assert isinstance(passed_reason_diagnostic, dict)
    passed_reason_diagnostic["stages"][0]["reason_code"] = (
        "futures_preview_product_price_invalid"
    )
    rehash(passed_reason)
    attacks.append(passed_reason)

    authority_expansion = mutated()
    authority_diagnostic = authority_expansion["pre_preview_stage_evidence"]
    assert isinstance(authority_diagnostic, dict)
    authority_diagnostic["retry_allowed"] = True
    rehash(authority_expansion)
    attacks.append(authority_expansion)

    post_preview = mutated()
    post_preview["attempt_counters"]["preview_order"] = 1
    rehash(post_preview)
    attacks.append(post_preview)

    raw_blocker = mutated()
    raw_blocker["blocker"] = "PRIVATE_EXCEPTION_TYPE_AND_TEXT"
    rehash(raw_blocker)
    attacks.append(raw_blocker)

    raw_attempt_context = mutated()
    raw_product = {"PRIVATE_PRODUCT_PAYLOAD": "MUST_NOT_RETURN"}
    raw_attempt_context["product_evidence"] = raw_product
    raw_attempt_context["product_evidence_sha256"] = canonical_sha256(
        raw_product
    )
    rehash(raw_attempt_context)
    attacks.append(raw_attempt_context)

    missing_required_r3_diagnostic = mutated()
    missing_required_r3_diagnostic.pop("pre_preview_stage_evidence")
    missing_required_r3_diagnostic.pop("pre_preview_stage_evidence_sha256")
    missing_required_r3_diagnostic["blocker"] = (
        "preflight_or_preview_blocked:ValueError"
    )
    missing_required_r3_diagnostic["evidence_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in missing_required_r3_diagnostic.items()
            if key != "evidence_sha256"
        }
    )
    attacks.append(missing_required_r3_diagnostic)

    for attack in attacks:
        with pytest.raises(ValidationError):
            AdminFuturesOrderPreviewResponse.model_validate(attack)


def test_terminal_failure_context_cannot_override_fixed_invariants():
    producer, _store, _path = _producer(
        Path("unused-for-record-only-test"),
        FakePreviewRestClient(),
    )
    claim = producer.build_claim()
    result = preview_module._terminal_failure_record(
        claim=claim,
        claim_sha256=canonical_sha256(claim),
        counters=preview_module._zero_attempt_counters(),
        read_counters=preview_module._zero_read_counters(),
        outcome="blocked",
        blocker="fixed_blocker",
        context={
            "status": "accepted",
            "outcome": "accepted",
            "attempt_counters": {"preview_order": 99},
            "read_only": False,
            "browser_authority": "execute",
            "bff_authority": "execute",
            "artifacts": {"runtime_created": True},
            "retry_allowed": True,
        },
    )

    assert result["status"] == "blocked"
    assert result["outcome"] == "blocked"
    assert result["attempt_counters"] == preview_module._zero_attempt_counters()
    assert result["read_only"] is True
    assert result["browser_authority"] == "display_only"
    assert result["bff_authority"] == "forward_only_no_execution"
    assert result["artifacts"] == {
        "execution_marker_created": False,
        "attempt_ledger_created": False,
        "runtime_created": False,
    }
    assert "retry_allowed" not in result


def test_stage_diagnostic_get_route_is_read_only_and_hides_raw_blocker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    rest_client = FakePreviewRestClient()
    rest_client.get_product_dict = (  # type: ignore[method-assign]
        lambda _product_id: _product(price="PRIVATE_VALUE_MUST_NOT_RETURN")
    )
    producer, _store, path = _producer(tmp_path, rest_client)
    with pytest.raises(FuturesOrderPreviewArtifactError, match="blocked"):
        producer.run()
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-token")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_FUTURES_ORDER_PREVIEW_ARTIFACT_PATH",
        str(path),
    )

    response = TestClient(create_app()).get(
        "/api/v1/futures/order-preview",
        headers={
            "Authorization": "Bearer test-token",
            "X-Admin-Actor": "operator-1",
            "X-Admin-Roles": "viewer",
        },
    )

    assert response.status_code == 200
    assert response.headers["X-Live-Execution-Enabled"] == "false"
    assert response.json()["pre_preview_stage_evidence"]["stages"][-1] == {
        "stage": "candidate_construction",
        "status": "blocked",
        "reason_code": "futures_preview_product_price_invalid",
    }
    assert response.json()["attempt_counters"]["preview_order"] == 0
    assert rest_client.preview_calls == []
    assert "PRIVATE_VALUE_MUST_NOT_RETURN" not in response.text


def test_r3_predecessor_and_r4_fallback_readback_are_version_bound():
    source = Path(preview_module.__file__).read_text(encoding="utf-8")
    assert "futures_exact_no_live_preview_slice_2r3" in source
    assert DEFAULT_FUTURES_PREVIEW_ARTIFACT_PATH.name == (
        "futures_exact_no_live_preview_slice_2r4.jsonl"
    )
    assert FUTURES_PREVIEW_R3_ARTIFACT_PATH.name == (
        "futures_exact_no_live_preview_slice_2r3.jsonl"
    )
    assert FUTURES_PREVIEW_R4_ARTIFACT_PATH.name == (
        "futures_exact_no_live_preview_slice_2r4.jsonl"
    )
    assert FUTURES_PREVIEW_R3_ARTIFACT_PATH != (
        DEFAULT_FUTURES_PREVIEW_ARTIFACT_PATH
    )
    assert FUTURES_PREVIEW_R4_ARTIFACT_PATH == (
        DEFAULT_FUTURES_PREVIEW_ARTIFACT_PATH
    )
    tool_source = Path(preview_tool.__file__).read_text(
        encoding="utf-8"
    )
    assert "--confirm-one-r4-preview" in tool_source
    assert "--confirm-one-r5-preview" not in tool_source
    assert "--confirm-one-r3-preview" not in tool_source
    r5_tool_source = Path(r5_preview_tool.__file__).read_text(encoding="utf-8")
    assert "--confirm-one-r5-preview" in r5_tool_source
    assert "--confirm-one-r4-preview" not in r5_tool_source


def test_consumed_r3_is_immutable_and_remains_compatible_r4_predecessor():
    observed = FUTURES_PREVIEW_R3_ARTIFACT_PATH.lstat()
    file_sha256 = hashlib.sha256(
        FUTURES_PREVIEW_R3_ARTIFACT_PATH.read_bytes()
    ).hexdigest()
    assert file_sha256 == FUTURES_PREVIEW_R3_FILE_SHA256
    assert observed.st_dev == FUTURES_PREVIEW_R3_DEVICE
    assert observed.st_ino == FUTURES_PREVIEW_R3_INODE
    assert observed.st_size == FUTURES_PREVIEW_R3_SIZE
    assert observed.st_mode & 0o777 == FUTURES_PREVIEW_R3_MODE
    assert observed.st_mtime_ns == FUTURES_PREVIEW_R3_MTIME_NS
    assert validate_production_futures_order_preview_r3_predecessor() == (
        FUTURES_PREVIEW_R3_PREDECESSOR_BINDING
    )
    evidence = FuturesOrderPreviewArtifactStore(
        FUTURES_PREVIEW_R3_ARTIFACT_PATH
    ).read_completed()
    assert evidence["evidence_sha256"] == FUTURES_PREVIEW_R3_EVIDENCE_SHA256
    assert "margin_windows_evidence" not in evidence
    AdminFuturesOrderPreviewResponse.model_validate(evidence)


def test_default_get_route_exposes_consumed_r5_terminal_evidence(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv(
        "COINBASE_ADMIN_API_FUTURES_ORDER_PREVIEW_ARTIFACT_PATH",
        raising=False,
    )
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-token")
    assert hashlib.sha256(
        FUTURES_PREVIEW_R5_ARTIFACT_PATH.read_bytes()
    ).hexdigest() == (
        "4988e23886d218d25be518203676bec4f27a2199a0ed2e7f36d0d7e1d8e6bbf7"
    )

    response = TestClient(create_app()).get(
        "/api/v1/futures/order-preview",
        headers={
            "Authorization": "Bearer test-token",
            "X-Admin-Actor": "operator-1",
            "X-Admin-Roles": "viewer",
        },
    )

    assert response.status_code == 200
    assert response.headers["X-Live-Execution-Enabled"] == "false"
    payload = response.json()
    assert payload["artifact_type"] == FUTURES_PREVIEW_R5_ARTIFACT_TYPE
    assert payload["status"] == "blocked"
    assert payload["outcome"] == "blocked"
    assert payload["predecessor_binding"]["file_sha256"] == (
        FUTURES_PREVIEW_R4_FILE_SHA256
    )
    assert payload["attempt_counters"] == {
        "preview_order": 0,
        "retry": 0,
        "fallback": 0,
        "create_order": 0,
        "cancel_order": 0,
        "close_position": 0,
        "reduce_position": 0,
    }
    assert payload["margin_setting_evidence"]["operationally_resolved"] is True
    assert "margin_windows_evidence" not in payload
    assert payload["margin_windows_policy_evidence"]["classification"] == (
        "margin_window_type_documented_but_operator_rejected"
    )
    assert payload["margin_windows_policy_evidence"]["rows"] == [
        {
            "policy_row_index": 0,
            "recognized_profile": "retail_regular",
            "observed_token": "MARGIN_WINDOW_TYPE_UNSPECIFIED",
            "documented_allowlist_match": True,
            "operator_policy_match": False,
            "classification": "documented_but_operator_rejected",
        },
        {
            "policy_row_index": 1,
            "recognized_profile": "retail_intraday_margin_1",
            "observed_token": "MARGIN_WINDOW_TYPE_INTRADAY",
            "documented_allowlist_match": True,
            "operator_policy_match": True,
            "classification": "accepted",
        },
    ]
    assert payload["pre_preview_stage_evidence"]["stages"][-1] == {
        "stage": "remaining_margin_validation",
        "status": "blocked",
        "reason_code": "futures_preview_margin_windows_ambiguous",
    }
    assert payload["exchange_submission_attempt_count"] == 0
    assert payload["submitted_notional_usdc"] == "0"
    assert payload["executed_notional_usdc"] == "0"
    assert payload["evidence_sha256"] == (
        "194cdd842944f8a453408051c04ff8e117b6b2b3ab6dcd7b1e78f44f4a5a467f"
    )
    assert "preview_response" not in payload
    assert "seal_ready_plan" not in payload
    assert "PRIVATE" not in response.text


def test_consumed_r5_terminal_is_physically_bound_before_default_readback():
    observed = FUTURES_PREVIEW_R5_ARTIFACT_PATH.lstat()

    assert preview_module.FUTURES_PREVIEW_R5_FILE_SHA256 == (
        "4988e23886d218d25be518203676bec4f27a2199a0ed2e7f36d0d7e1d8e6bbf7"
    )
    assert preview_module.FUTURES_PREVIEW_R5_EVIDENCE_SHA256 == (
        "194cdd842944f8a453408051c04ff8e117b6b2b3ab6dcd7b1e78f44f4a5a467f"
    )
    assert (
        observed.st_dev,
        observed.st_ino,
        observed.st_size,
        observed.st_mode & 0o777,
        observed.st_mtime_ns,
    ) == (
        preview_module.FUTURES_PREVIEW_R5_DEVICE,
        preview_module.FUTURES_PREVIEW_R5_INODE,
        preview_module.FUTURES_PREVIEW_R5_SIZE,
        preview_module.FUTURES_PREVIEW_R5_MODE,
        preview_module.FUTURES_PREVIEW_R5_MTIME_NS,
    )
    assert preview_module.validate_production_futures_order_preview_r5_terminal() == (
        preview_module.FUTURES_PREVIEW_R5_TERMINAL_BINDING
    )
    assert configured_futures_order_preview_artifact_path() == (
        FUTURES_PREVIEW_R5_ARTIFACT_PATH
    )


def test_r6_policy_accepts_only_the_exact_authorized_profile_state_pair():
    snapshot = FakePreviewRestClient().get_futures_margin_collateral_snapshot()
    snapshot["current_margin_windows"][0]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = "MARGIN_WINDOW_TYPE_UNSPECIFIED"
    snapshot["current_margin_windows"][1]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = "MARGIN_WINDOW_TYPE_INTRADAY"

    context = preview_module.slice2_preview_margin_windows_pair_policy_context(
        snapshot
    )
    evidence = context["margin_windows_policy_evidence"]

    assert evidence["schema_version"] == "3"
    assert evidence["policy_id"] == (
        "slice2_preview_margin_window_exact_pair_policy_v3"
    )
    assert evidence["pair_policy_mode"] == "exact_profile_state_pair"
    assert evidence["profile_state_mapping_documented_by_coinbase"] is False
    assert evidence["r6_attempt_authority_granted"] is False
    assert evidence["execution_allowed"] is False
    assert evidence["create_order_eligibility_granted"] is False
    assert evidence["later_live_eligibility_granted"] is False
    assert evidence["classification"] == "ready"
    assert evidence["margin_window_policy_satisfied"] is True
    assert evidence["rows"] == [
        {
            "policy_row_index": 0,
            "recognized_profile": "retail_regular",
            "observed_token": "MARGIN_WINDOW_TYPE_UNSPECIFIED",
            "documented_allowlist_match": True,
            "operator_policy_match": True,
            "classification": "accepted",
        },
        {
            "policy_row_index": 1,
            "recognized_profile": "retail_intraday_margin_1",
            "observed_token": "MARGIN_WINDOW_TYPE_INTRADAY",
            "documented_allowlist_match": True,
            "operator_policy_match": True,
            "classification": "accepted",
        },
    ]
    assert context["margin_windows_policy_evidence_sha256"] == canonical_sha256(
        evidence
    )
    assert preview_module.validate_slice2_preview_r6_margin_collateral_evidence(
        snapshot
    ) == Decimal("250.00")


def test_r6_policy_rejects_other_v2_accepted_pairs_without_preview():
    snapshot = FakePreviewRestClient().get_futures_margin_collateral_snapshot()
    snapshot["current_margin_windows"][0]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = "MARGIN_WINDOW_TYPE_OVERNIGHT"
    snapshot["current_margin_windows"][1]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = "MARGIN_WINDOW_TYPE_INTRADAY"

    assert validate_slice2_preview_margin_collateral_evidence(snapshot) == (
        Decimal("250.00")
    )
    with pytest.raises(
        ValueError,
        match="^futures_preview_margin_windows_ambiguous$",
    ):
        preview_module.validate_slice2_preview_r6_margin_collateral_evidence(
            snapshot
        )
    evidence = preview_module.slice2_preview_margin_windows_pair_policy_context(
        snapshot
    )["margin_windows_policy_evidence"]
    assert evidence["classification"] == (
        "margin_window_type_documented_but_operator_rejected"
    )
    assert evidence["failing_policy_row_index"] == 0
    assert evidence["rows"][0]["operator_policy_match"] is False


def test_r6_fake_preview_binds_exact_consumed_r5_and_v3_policy(tmp_path: Path):
    assert preview_module.FUTURES_PREVIEW_R6_ARTIFACT_PATH.name == (
        "futures_exact_no_live_preview_slice_2r6.jsonl"
    )
    assert not preview_module.FUTURES_PREVIEW_R6_ARTIFACT_PATH.exists()
    rest_client = FakePreviewRestClient()
    snapshot = rest_client.get_futures_margin_collateral_snapshot()
    snapshot["current_margin_windows"][0]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = "MARGIN_WINDOW_TYPE_UNSPECIFIED"
    rest_client.read_calls.clear()
    rest_client.get_futures_margin_collateral_snapshot = (  # type: ignore[method-assign]
        lambda: snapshot
    )
    producer, store, _path = _producer(
        tmp_path,
        rest_client,
        artifact_type=preview_module.FUTURES_PREVIEW_R6_ARTIFACT_TYPE,
        predecessor_binding=preview_module.FUTURES_PREVIEW_R5_TERMINAL_BINDING,
    )

    evidence = producer.run()

    assert evidence == store.read_completed()
    assert evidence["artifact_type"] == (
        preview_module.FUTURES_PREVIEW_R6_ARTIFACT_TYPE
    )
    assert evidence["predecessor_binding"] == (
        preview_module.FUTURES_PREVIEW_R5_TERMINAL_BINDING
    )
    assert evidence["margin_windows_policy_evidence"]["schema_version"] == "3"
    assert evidence["attempt_counters"]["preview_order"] == 1
    assert evidence["exchange_submission_attempt_count"] == 0
    assert evidence["submitted_notional_usdc"] == "0"
    assert evidence["executed_notional_usdc"] == "0"
    assert rest_client.forbidden_calls == []
    AdminFuturesOrderPreviewResponse.model_validate(evidence)


@pytest.mark.parametrize(
    "token",
    [
        "MARGIN_WINDOW_TYPE_OVERNIGHT",
        "FCM_MARGIN_WINDOW_TYPE_INTRADAY",
        "MARGIN_WINDOW_TYPE_PRIVATE_UNKNOWN",
        " malformed ",
        None,
        7,
    ],
)
def test_r6_policy_rejects_and_withholds_every_nonexact_regular_token(
    token: object,
):
    snapshot = FakePreviewRestClient().get_futures_margin_collateral_snapshot()
    snapshot["current_margin_windows"][0]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = token
    evidence = preview_module.slice2_preview_margin_windows_pair_policy_context(
        snapshot
    )["margin_windows_policy_evidence"]

    assert evidence["classification"] != "ready"
    assert evidence["margin_window_policy_satisfied"] is False
    assert evidence["rows"][0]["operator_policy_match"] is False
    if token == "MARGIN_WINDOW_TYPE_OVERNIGHT":
        assert evidence["rows"][0]["observed_token"] == token
        assert evidence["rows"][0]["classification"] == (
            "documented_but_operator_rejected"
        )
    else:
        assert evidence["rows"][0]["observed_token"] is None
        assert evidence["rows"][0]["classification"] == (
            "undocumented_or_malformed"
        )
    assert str(token) not in json.dumps(evidence) or token == (
        "MARGIN_WINDOW_TYPE_OVERNIGHT"
    )


def test_r6_claim_binds_v3_policy_and_rejects_consumed_r5_identifiers(
    tmp_path: Path,
):
    producer, _store, _path = _producer(
        tmp_path,
        FakePreviewRestClient(),
        artifact_type=preview_module.FUTURES_PREVIEW_R6_ARTIFACT_TYPE,
        predecessor_binding=preview_module.FUTURES_PREVIEW_R5_TERMINAL_BINDING,
    )
    claim = producer.build_claim()
    preview_module._validate_r6_claim_record(claim)
    assert claim["margin_window_policy_binding"] == (
        preview_module.FUTURES_PREVIEW_R6_MARGIN_WINDOW_POLICY_BINDING
    )

    tampered = deepcopy(claim)
    tampered["margin_window_policy_binding"]["profile_state_pairs"][0][
        "margin_window_type"
    ] = "MARGIN_WINDOW_TYPE_OVERNIGHT"
    with pytest.raises(
        FuturesOrderPreviewArtifactError,
        match="R6 claim authority",
    ):
        preview_module._validate_r6_claim_record(tampered)

    producer.correlation_id_factory = (
        lambda: "aafa0078-be77-4b41-a2aa-672c8b26ecb3"
    )
    with pytest.raises(
        FuturesOrderPreviewArtifactError,
        match="identifiers are not fresh",
    ):
        producer.build_claim()
    r5 = FuturesOrderPreviewArtifactStore(
        FUTURES_PREVIEW_R5_ARTIFACT_PATH
    ).read_completed()
    AdminFuturesOrderPreviewResponse.model_validate(r5)


def test_r6_unknown_preview_is_consumed_once_without_retry(tmp_path: Path):
    rest_client = FakePreviewRestClient(preview_error=TimeoutError("PRIVATE"))
    snapshot = rest_client.get_futures_margin_collateral_snapshot()
    snapshot["current_margin_windows"][0]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = "MARGIN_WINDOW_TYPE_UNSPECIFIED"
    rest_client.read_calls.clear()
    rest_client.get_futures_margin_collateral_snapshot = (  # type: ignore[method-assign]
        lambda: snapshot
    )
    producer, store, path = _producer(
        tmp_path,
        rest_client,
        artifact_type=preview_module.FUTURES_PREVIEW_R6_ARTIFACT_TYPE,
        predecessor_binding=preview_module.FUTURES_PREVIEW_R5_TERMINAL_BINDING,
    )

    with pytest.raises(
        FuturesOrderPreviewArtifactError,
        match="outcome is unknown; attempt consumed",
    ):
        producer.run()
    evidence = store.read_completed()
    assert evidence["outcome"] == "unknown"
    assert evidence["attempt_counters"] == {
        "preview_order": 1,
        "retry": 0,
        "fallback": 0,
        "create_order": 0,
        "cancel_order": 0,
        "close_position": 0,
        "reduce_position": 0,
    }
    assert len(rest_client.preview_calls) == 1
    assert "PRIVATE" not in path.read_text(encoding="utf-8")
    with pytest.raises(
        FuturesOrderPreviewArtifactError,
        match="already consumed",
    ):
        producer.run()
    AdminFuturesOrderPreviewResponse.model_validate(evidence)


def test_r6_response_rejects_policy_authority_and_seal_binding_tampering(
    tmp_path: Path,
):
    rest_client = FakePreviewRestClient()
    snapshot = rest_client.get_futures_margin_collateral_snapshot()
    snapshot["current_margin_windows"][0]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = "MARGIN_WINDOW_TYPE_UNSPECIFIED"
    rest_client.get_futures_margin_collateral_snapshot = (  # type: ignore[method-assign]
        lambda: snapshot
    )
    producer, _store, _path = _producer(
        tmp_path,
        rest_client,
        artifact_type=preview_module.FUTURES_PREVIEW_R6_ARTIFACT_TYPE,
        predecessor_binding=preview_module.FUTURES_PREVIEW_R5_TERMINAL_BINDING,
    )
    evidence = producer.run()

    authority_attack = deepcopy(evidence)
    authority_attack["margin_windows_policy_evidence"][
        "r6_attempt_authority_granted"
    ] = True
    authority_attack["margin_windows_policy_evidence_sha256"] = canonical_sha256(
        authority_attack["margin_windows_policy_evidence"]
    )
    authority_attack["evidence_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in authority_attack.items()
            if key != "evidence_sha256"
        }
    )
    with pytest.raises(ValidationError):
        AdminFuturesOrderPreviewResponse.model_validate(authority_attack)

    seal_attack = deepcopy(evidence)
    seal_attack["seal_ready_plan"]["margin_window_policy_binding"][
        "profile_state_pairs"
    ][0]["margin_window_type"] = "MARGIN_WINDOW_TYPE_OVERNIGHT"
    seal_attack["seal_ready_plan_sha256"] = canonical_sha256(
        seal_attack["seal_ready_plan"]
    )
    seal_attack["evidence_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in seal_attack.items()
            if key != "evidence_sha256"
        }
    )
    with pytest.raises(ValidationError, match="r5_seal_plan_invalid"):
        AdminFuturesOrderPreviewResponse.model_validate(seal_attack)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("source"),
        lambda value: value.pop("errors"),
        lambda value: value.pop("intraday_margin_setting"),
        lambda value: value.pop("current_margin_windows"),
        lambda value: value.pop("futures_sweeps"),
        lambda value: value["futures_sweeps"].append({"status": "PENDING"}),
        lambda value: value.pop("source_read_attempts"),
        lambda value: value["source_read_attempts"].update(
            get_current_margin_window=3
        ),
        lambda value: value["balance_summary"].pop("initial_margin"),
        lambda value: value["balance_summary"].pop("liquidation_threshold"),
        lambda value: value["balance_summary"].pop(
            "intraday_margin_window_measure"
        ),
        lambda value: value["current_margin_windows"].pop(),
        lambda value: value["current_margin_windows"][0].update(status="blocked"),
    ],
)
def test_margin_collateral_evidence_requires_explicit_complete_cfm_risk_state(
    mutation,
):
    evidence = FakePreviewRestClient().get_futures_margin_collateral_snapshot()
    mutation(evidence)

    with pytest.raises(ValueError, match="margin|collateral|liquidation"):
        validate_margin_collateral_evidence(evidence)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["balance_summary"][
            "intraday_margin_window_measure"
        ].update(margin_window_type="FCM_MARGIN_WINDOW_TYPE_UNSPECIFIED"),
        lambda value: value["current_margin_windows"][0]["margin_window"].update(
            margin_window_type="MARGIN_WINDOW_TYPE_UNSPECIFIED"
        ),
        lambda value: value["current_margin_windows"][0]["margin_window"].update(
            margin_window_type="MARGIN_WINDOW_TYPE_UNKNOWN"
        ),
        lambda value: value["current_margin_windows"][0]["margin_window"].update(
            margin_window_type="MARGIN_WINDOW_TYPE_BOGUS"
        ),
        lambda value: value["current_margin_windows"][0].pop(
            "is_intraday_margin_killswitch_enabled"
        ),
        lambda value: value["current_margin_windows"][0].update(
            is_intraday_margin_killswitch_enabled="false"
        ),
        lambda value: value["current_margin_windows"][0].update(
            is_intraday_margin_killswitch_enabled=True
        ),
        lambda value: value["current_margin_windows"][1].pop(
            "is_intraday_margin_enrollment_killswitch_enabled"
        ),
        lambda value: value["current_margin_windows"][1].update(
            is_intraday_margin_enrollment_killswitch_enabled=True
        ),
    ],
)
def test_margin_window_sentinels_and_killswitch_ambiguity_block_pre_preview(
    mutation,
):
    evidence = FakePreviewRestClient().get_futures_margin_collateral_snapshot()
    mutation(evidence)

    with pytest.raises(ValueError, match="margin.*window|killswitch"):
        validate_margin_collateral_evidence(evidence)


def test_earlier_row_killswitch_precedes_later_window_ambiguity():
    evidence = FakePreviewRestClient().get_futures_margin_collateral_snapshot()
    evidence["current_margin_windows"][0][
        "is_intraday_margin_killswitch_enabled"
    ] = True
    evidence["current_margin_windows"][1]["margin_window"].update(
        margin_window_type="MARGIN_WINDOW_TYPE_PRIVATE_ACCOUNT"
    )

    with pytest.raises(
        ValueError,
        match="^futures_preview_margin_killswitch_enabled$",
    ):
        validate_margin_collateral_evidence(evidence)


@pytest.mark.parametrize(
    ("mutation", "classification", "failing_field", "failing_value_type"),
    [
        (
            lambda value: value.pop("current_margin_windows"),
            "missing_container",
            "current_margin_windows",
            "missing",
        ),
        (
            lambda value: value.update(
                current_margin_windows="PRIVATE_WINDOW_RESPONSE"
            ),
            "non_list_container",
            "current_margin_windows",
            "string",
        ),
        (
            lambda value: value.update(
                current_margin_windows=tuple(value["current_margin_windows"])
            ),
            "non_list_container",
            "current_margin_windows",
            "sequence",
        ),
        (
            lambda value: value["current_margin_windows"].clear(),
            "unexpected_row_count",
            "current_margin_windows",
            "sequence",
        ),
        (
            lambda value: value["current_margin_windows"].pop(),
            "unexpected_row_count",
            "current_margin_windows",
            "sequence",
        ),
        (
            lambda value: value["current_margin_windows"].append(
                {"profile": "PRIVATE_OVERFLOW_ROW"}
            ),
            "unexpected_row_count",
            "current_margin_windows",
            "sequence",
        ),
        (
            lambda value: value["current_margin_windows"].__setitem__(
                0,
                "PRIVATE_WINDOW_ROW",
            ),
            "non_mapping_row",
            "row",
            "string",
        ),
        (
            lambda value: value["current_margin_windows"][0].pop("profile"),
            "profile_missing",
            "profile",
            "missing",
        ),
        (
            lambda value: value["current_margin_windows"][0].update(
                profile=None
            ),
            "profile_null",
            "profile",
            "null",
        ),
        (
            lambda value: value["current_margin_windows"][0].update(
                profile=True
            ),
            "profile_non_string",
            "profile",
            "boolean",
        ),
        (
            lambda value: value["current_margin_windows"][0].update(
                profile=" PRIVATE_PROFILE\n"
            ),
            "profile_malformed_string",
            "profile",
            "string",
        ),
        (
            lambda value: value["current_margin_windows"][0].update(
                profile="MARGIN_PROFILE_TYPE_PRIVATE_ACCOUNT"
            ),
            "profile_unrecognized_enum_token",
            "profile",
            "string",
        ),
        (
            lambda value: value["current_margin_windows"][1].update(
                profile="MARGIN_PROFILE_TYPE_RETAIL_REGULAR"
            ),
            "duplicate_profile",
            "profile",
            "string",
        ),
        (
            lambda value: value["current_margin_windows"][0].pop("status"),
            "status_missing",
            "status",
            "missing",
        ),
        (
            lambda value: value["current_margin_windows"][0].update(
                status=None
            ),
            "status_null",
            "status",
            "null",
        ),
        (
            lambda value: value["current_margin_windows"][0].update(
                status=False
            ),
            "status_non_string",
            "status",
            "boolean",
        ),
        (
            lambda value: value["current_margin_windows"][0].update(
                status="PRIVATE_BLOCKED_STATUS"
            ),
            "status_not_ready",
            "status",
            "string",
        ),
        (
            lambda value: value["current_margin_windows"][0].pop(
                "margin_window"
            ),
            "margin_window_missing",
            "margin_window",
            "missing",
        ),
        (
            lambda value: value["current_margin_windows"][0].update(
                margin_window=None
            ),
            "margin_window_null",
            "margin_window",
            "null",
        ),
        (
            lambda value: value["current_margin_windows"][0].update(
                margin_window="PRIVATE_WINDOW_CONTAINER"
            ),
            "margin_window_non_mapping",
            "margin_window",
            "string",
        ),
        (
            lambda value: value["current_margin_windows"][0][
                "margin_window"
            ].pop("margin_window_type"),
            "margin_window_type_missing",
            "margin_window_type",
            "missing",
        ),
        (
            lambda value: value["current_margin_windows"][0][
                "margin_window"
            ].update(margin_window_type=None),
            "margin_window_type_null",
            "margin_window_type",
            "null",
        ),
        (
            lambda value: value["current_margin_windows"][0][
                "margin_window"
            ].update(margin_window_type=1),
            "margin_window_type_non_string",
            "margin_window_type",
            "number",
        ),
        (
            lambda value: value["current_margin_windows"][0][
                "margin_window"
            ].update(margin_window_type=" PRIVATE_WINDOW_TYPE\n"),
            "margin_window_type_malformed_string",
            "margin_window_type",
            "string",
        ),
        (
            lambda value: value["current_margin_windows"][0][
                "margin_window"
            ].update(
                margin_window_type="MARGIN_WINDOW_TYPE_PRIVATE_ACCOUNT"
            ),
            "margin_window_type_not_exact_operational_enum_token",
            "margin_window_type",
            "string",
        ),
        (
            lambda _value: None,
            "ready",
            None,
            None,
        ),
    ],
)
def test_margin_windows_diagnostic_classifies_without_echoing_raw_values(
    mutation,
    classification: str,
    failing_field: str | None,
    failing_value_type: str | None,
):
    snapshot = FakePreviewRestClient().get_futures_margin_collateral_snapshot()
    mutation(snapshot)

    context = _margin_windows_terminal_context(snapshot)
    diagnostic = context["margin_windows_evidence"]

    assert diagnostic["classification"] == classification
    assert diagnostic["failing_field"] == failing_field
    assert diagnostic["failing_value_type"] == failing_value_type
    assert diagnostic["sanitized"] is True
    assert diagnostic["raw_response_included"] is False
    assert diagnostic["external_exception_text_included"] is False
    assert diagnostic["unknown_identifier_values_included"] is False
    assert context["margin_windows_evidence_sha256"] == canonical_sha256(
        diagnostic
    )
    AdminFuturesPreviewMarginWindowsEvidence.model_validate(diagnostic)
    serialized = json.dumps(context)
    assert "PRIVATE" not in serialized


def test_margin_windows_diagnostic_covers_defensive_profile_set_incomplete(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        preview_module,
        "FUTURES_PREVIEW_EXPECTED_MARGIN_PROFILES",
        {
            **preview_module.FUTURES_PREVIEW_EXPECTED_MARGIN_PROFILES,
            "MARGIN_PROFILE_TYPE_RETAIL_FUTURE": "retail_future",
        },
    )
    snapshot = FakePreviewRestClient().get_futures_margin_collateral_snapshot()

    diagnostic = _margin_windows_terminal_context(snapshot)[
        "margin_windows_evidence"
    ]

    assert diagnostic["classification"] == "expected_profile_set_incomplete"
    assert diagnostic["failing_row_index"] is None
    assert diagnostic["recognized_profile"] is None
    assert diagnostic["failing_field"] == "expected_profile_set"
    assert diagnostic["failing_value_type"] is None
    AdminFuturesPreviewMarginWindowsEvidence.model_validate(diagnostic)


SLICE2_OPERATOR_ACCEPTED_MARGIN_WINDOW_TYPES = (
    "MARGIN_WINDOW_TYPE_OVERNIGHT",
    "MARGIN_WINDOW_TYPE_WEEKEND",
    "MARGIN_WINDOW_TYPE_INTRADAY",
    "MARGIN_WINDOW_TYPE_TRANSITION",
)


@pytest.mark.parametrize(
    ("regular_state", "intraday_profile_state"),
    [
        (regular_state, intraday_profile_state)
        for regular_state in SLICE2_OPERATOR_ACCEPTED_MARGIN_WINDOW_TYPES
        for intraday_profile_state in (
            SLICE2_OPERATOR_ACCEPTED_MARGIN_WINDOW_TYPES
        )
    ],
)
def test_slice2_preview_operator_policy_accepts_four_documented_states_for_both_profiles(
    regular_state: str,
    intraday_profile_state: str,
):
    snapshot = FakePreviewRestClient().get_futures_margin_collateral_snapshot()
    snapshot["current_margin_windows"][0]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = regular_state
    snapshot["current_margin_windows"][1]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = intraday_profile_state

    context = slice2_preview_margin_windows_policy_context(snapshot)
    evidence = context["margin_windows_policy_evidence"]

    assert evidence["classification"] == "ready"
    assert evidence["enum_authority"] == (
        "official_coinbase_advanced_trade_api_docs"
    )
    assert evidence["profile_state_policy_authority"] == (
        "operator_defined_slice_2_preview_only_not_coinbase_documented"
    )
    assert evidence["profile_state_mapping_documented_by_coinbase"] is False
    assert evidence["policy_id"] == (
        "slice2_preview_margin_window_profile_state_policy_v2"
    )
    assert evidence["margin_window_policy_satisfied"] is True
    assert evidence["eligibility_scope"] == "slice_2_preview_only"
    assert evidence["r5_attempt_authority_granted"] is False
    assert evidence["execution_allowed"] is False
    assert evidence["create_order_eligibility_granted"] is False
    assert evidence["later_live_eligibility_granted"] is False
    assert evidence["rows"] == [
        {
            "policy_row_index": 0,
            "recognized_profile": "retail_regular",
            "observed_token": regular_state,
            "documented_allowlist_match": True,
            "operator_policy_match": True,
            "classification": "accepted",
        },
        {
            "policy_row_index": 1,
            "recognized_profile": "retail_intraday_margin_1",
            "observed_token": intraday_profile_state,
            "documented_allowlist_match": True,
            "operator_policy_match": True,
            "classification": "accepted",
        },
    ]
    assert context["margin_windows_policy_evidence_sha256"] == canonical_sha256(
        evidence
    )
    AdminFuturesPreviewMarginWindowsPolicyEvidenceV2.model_validate(evidence)


def test_slice2_preview_policy_is_canonical_across_exchange_row_order():
    snapshot = FakePreviewRestClient().get_futures_margin_collateral_snapshot()
    snapshot["current_margin_windows"][0]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = "MARGIN_WINDOW_TYPE_OVERNIGHT"
    snapshot["current_margin_windows"][1]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = "MARGIN_WINDOW_TYPE_TRANSITION"

    forward = slice2_preview_margin_windows_policy_context(snapshot)
    snapshot["current_margin_windows"].reverse()  # type: ignore[union-attr]
    reverse = slice2_preview_margin_windows_policy_context(snapshot)

    assert forward == reverse


def test_slice2_preview_policy_rejection_is_canonical_across_exchange_row_order():
    snapshot = FakePreviewRestClient().get_futures_margin_collateral_snapshot()
    snapshot["current_margin_windows"][0]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = "MARGIN_WINDOW_TYPE_UNSPECIFIED"

    forward = slice2_preview_margin_windows_policy_context(snapshot)
    snapshot["current_margin_windows"].reverse()  # type: ignore[union-attr]
    reverse = slice2_preview_margin_windows_policy_context(snapshot)

    assert forward == reverse


def test_slice2_preview_structural_rejection_is_canonical_across_exchange_row_order():
    snapshot = FakePreviewRestClient().get_futures_margin_collateral_snapshot()
    snapshot["current_margin_windows"][0]["status"] = "closed"  # type: ignore[index]
    snapshot["current_margin_windows"][1].pop("margin_window")  # type: ignore[index]

    forward = slice2_preview_margin_windows_policy_context(snapshot)
    snapshot["current_margin_windows"].reverse()
    reverse = slice2_preview_margin_windows_policy_context(snapshot)

    assert forward == reverse
    assert forward["margin_windows_policy_evidence"][
        "failing_policy_row_index"
    ] == 0
    assert forward["margin_windows_policy_evidence"]["classification"] == (
        "status_not_ready"
    )


@pytest.mark.parametrize(
    ("token", "classification", "observed_token", "documented_match"),
    [
        (
            "MARGIN_WINDOW_TYPE_UNSPECIFIED",
            "margin_window_type_documented_but_operator_rejected",
            "MARGIN_WINDOW_TYPE_UNSPECIFIED",
            True,
        ),
        (
            "MARGIN_WINDOW_TYPE_PRIVATE_ACCOUNT",
            "margin_window_type_undocumented_or_malformed",
            None,
            False,
        ),
        (
            "FCM_MARGIN_WINDOW_TYPE_INTRADAY",
            "margin_window_type_undocumented_or_malformed",
            None,
            False,
        ),
        (
            " PRIVATE_MARGIN_WINDOW_TYPE\n",
            "margin_window_type_undocumented_or_malformed",
            None,
            False,
        ),
        (
            None,
            "margin_window_type_null",
            None,
            False,
        ),
        (
            7,
            "margin_window_type_non_string",
            None,
            False,
        ),
    ],
)
def test_slice2_preview_policy_rejects_and_withholds_nonoperational_states(
    token: object,
    classification: str,
    observed_token: str | None,
    documented_match: bool,
):
    snapshot = FakePreviewRestClient().get_futures_margin_collateral_snapshot()
    snapshot["current_margin_windows"][0]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = token

    context = slice2_preview_margin_windows_policy_context(snapshot)
    evidence = context["margin_windows_policy_evidence"]
    failing_row = next(
        row for row in evidence["rows"] if row["recognized_profile"] == "retail_regular"
    )

    assert evidence["classification"] == classification
    assert evidence["margin_window_policy_satisfied"] is False
    assert evidence["failing_policy_row_index"] == 0
    assert failing_row["observed_token"] == observed_token
    assert failing_row["documented_allowlist_match"] is documented_match
    assert failing_row["operator_policy_match"] is False
    assert context["margin_windows_policy_evidence_sha256"] == canonical_sha256(
        evidence
    )
    AdminFuturesPreviewMarginWindowsPolicyEvidenceV2.model_validate(evidence)
    serialized = json.dumps(context)
    if observed_token is None and isinstance(token, str):
        assert token.strip() not in serialized


@pytest.mark.parametrize("profile_index", [0, 1])
def test_slice2_preview_policy_rejects_unspecified_for_either_exact_profile(
    profile_index: int,
):
    snapshot = FakePreviewRestClient().get_futures_margin_collateral_snapshot()
    snapshot["current_margin_windows"][profile_index]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = "MARGIN_WINDOW_TYPE_UNSPECIFIED"

    evidence = slice2_preview_margin_windows_policy_context(snapshot)[
        "margin_windows_policy_evidence"
    ]

    assert evidence["margin_window_policy_satisfied"] is False
    assert evidence["classification"] == (
        "margin_window_type_documented_but_operator_rejected"
    )
    assert evidence["failing_policy_row_index"] == profile_index
    assert any(
        row["observed_token"] == "MARGIN_WINDOW_TYPE_UNSPECIFIED"
        and row["documented_allowlist_match"] is True
        and row["operator_policy_match"] is False
        for row in evidence["rows"]
    )


@pytest.mark.parametrize(
    ("mutation", "classification"),
    [
        (
            lambda snapshot: snapshot["current_margin_windows"].pop(),
            "unexpected_row_count",
        ),
        (
            lambda snapshot: snapshot["current_margin_windows"][1].update(
                profile="MARGIN_PROFILE_TYPE_RETAIL_REGULAR"
            ),
            "duplicate_profile",
        ),
        (
            lambda snapshot: snapshot["current_margin_windows"][0].update(
                profile="MARGIN_PROFILE_TYPE_PRIVATE_ACCOUNT"
            ),
            "profile_unrecognized_enum_token",
        ),
        (
            lambda snapshot: snapshot["current_margin_windows"][0].pop(
                "profile"
            ),
            "profile_missing",
        ),
        (
            lambda snapshot: snapshot["current_margin_windows"].append(
                deepcopy(snapshot["current_margin_windows"][0])
            ),
            "unexpected_row_count",
        ),
        (
            lambda snapshot: snapshot["current_margin_windows"][0].update(
                profile=" MARGIN_PROFILE_TYPE_RETAIL_REGULAR\n"
            ),
            "profile_malformed_string",
        ),
        (
            lambda snapshot: snapshot["current_margin_windows"][0].update(
                status="closed"
            ),
            "status_not_ready",
        ),
        (
            lambda snapshot: snapshot["current_margin_windows"][0][
                "margin_window"
            ].pop("margin_window_type"),
            "margin_window_type_missing",
        ),
    ],
)
def test_slice2_preview_policy_requires_exact_unique_profiles_without_leakage(
    mutation,
    classification: str,
):
    snapshot = FakePreviewRestClient().get_futures_margin_collateral_snapshot()
    mutation(snapshot)

    context = slice2_preview_margin_windows_policy_context(snapshot)
    evidence = context["margin_windows_policy_evidence"]

    assert evidence["classification"] == classification
    assert "PRIVATE" not in json.dumps(context)
    AdminFuturesPreviewMarginWindowsPolicyEvidenceV2.model_validate(evidence)


def test_slice2_preview_policy_does_not_waive_existing_killswitch_gate():
    snapshot = FakePreviewRestClient().get_futures_margin_collateral_snapshot()
    snapshot["current_margin_windows"][0][
        "is_intraday_margin_killswitch_enabled"
    ] = True

    evidence = slice2_preview_margin_windows_policy_context(snapshot)[
        "margin_windows_policy_evidence"
    ]

    assert evidence["margin_window_policy_satisfied"] is True
    with pytest.raises(
        ValueError,
        match="^futures_preview_margin_killswitch_enabled$",
    ):
        validate_margin_collateral_evidence(snapshot)


@pytest.mark.parametrize(
    "v2_only_state",
    (
        "MARGIN_WINDOW_TYPE_OVERNIGHT",
        "MARGIN_WINDOW_TYPE_WEEKEND",
        "MARGIN_WINDOW_TYPE_TRANSITION",
    ),
)
def test_slice2_preview_policy_isolated_from_consumed_r4_v1_semantics(
    v2_only_state: str,
):
    snapshot = FakePreviewRestClient().get_futures_margin_collateral_snapshot()
    snapshot["current_margin_windows"][0]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = v2_only_state

    legacy = _margin_windows_terminal_context(snapshot)[
        "margin_windows_evidence"
    ]
    v2 = slice2_preview_margin_windows_policy_context(snapshot)[
        "margin_windows_policy_evidence"
    ]

    assert legacy["schema_version"] == "1"
    assert legacy["classification"] == (
        "margin_window_type_not_exact_operational_enum_token"
    )
    assert "observed_token" not in legacy
    assert v2["schema_version"] == "2"
    assert v2["classification"] == "ready"
    assert FUTURES_PREVIEW_DOCUMENTED_CURRENT_MARGIN_WINDOW_TYPES == {
        "MARGIN_WINDOW_TYPE_UNSPECIFIED",
        *SLICE2_OPERATOR_ACCEPTED_MARGIN_WINDOW_TYPES,
    }
    assert set(FUTURES_PREVIEW_SLICE2_OPERATOR_MARGIN_WINDOW_POLICY) == {
        "MARGIN_PROFILE_TYPE_RETAIL_REGULAR",
        "MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1",
    }
    assert all(
        accepted == frozenset(SLICE2_OPERATOR_ACCEPTED_MARGIN_WINDOW_TYPES)
        for accepted in FUTURES_PREVIEW_SLICE2_OPERATOR_MARGIN_WINDOW_POLICY.values()
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (
            "profile_state_policy_authority",
            "official_coinbase_advanced_trade_api_docs",
        ),
        ("profile_state_mapping_documented_by_coinbase", True),
        ("eligibility_scope", "all_futures_order_execution"),
        ("margin_window_policy_satisfied", False),
        ("r5_attempt_authority_granted", True),
        ("execution_allowed", True),
        ("create_order_eligibility_granted", True),
        ("later_live_eligibility_granted", True),
    ],
)
def test_slice2_preview_policy_model_rejects_authority_or_scope_expansion(
    field: str,
    value: object,
):
    snapshot = FakePreviewRestClient().get_futures_margin_collateral_snapshot()
    evidence = slice2_preview_margin_windows_policy_context(snapshot)[
        "margin_windows_policy_evidence"
    ]
    evidence[field] = value

    with pytest.raises(ValidationError):
        AdminFuturesPreviewMarginWindowsPolicyEvidenceV2.model_validate(evidence)


def test_slice2_preview_policy_model_rejects_contradictory_shape_classification():
    snapshot = FakePreviewRestClient().get_futures_margin_collateral_snapshot()
    evidence = slice2_preview_margin_windows_policy_context(snapshot)[
        "margin_windows_policy_evidence"
    ]
    evidence.update(
        classification="missing_container",
        margin_window_policy_satisfied=False,
    )

    with pytest.raises(
        ValidationError,
        match="margin_window_policy_invalid",
    ):
        AdminFuturesPreviewMarginWindowsPolicyEvidenceV2.model_validate(evidence)


@pytest.mark.parametrize(
    ("classification", "failing_value_type"),
    [
        ("margin_window_type_undocumented_or_malformed", "string"),
        ("margin_window_type_null", "null"),
        ("margin_window_type_non_string", "number"),
    ],
)
def test_slice2_preview_policy_model_rejects_cross_classified_token_failure(
    classification: str,
    failing_value_type: str,
):
    snapshot = FakePreviewRestClient().get_futures_margin_collateral_snapshot()
    snapshot["current_margin_windows"][0]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = "MARGIN_WINDOW_TYPE_UNSPECIFIED"
    evidence = slice2_preview_margin_windows_policy_context(snapshot)[
        "margin_windows_policy_evidence"
    ]
    evidence.update(
        classification=classification,
        failing_value_type=failing_value_type,
    )

    with pytest.raises(
        ValidationError,
        match="margin_window_policy_invalid",
    ):
        AdminFuturesPreviewMarginWindowsPolicyEvidenceV2.model_validate(evidence)


def test_slice2_preview_policy_model_rejects_nonminimum_failed_policy_row():
    snapshot = FakePreviewRestClient().get_futures_margin_collateral_snapshot()
    snapshot["current_margin_windows"][0]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = "MARGIN_WINDOW_TYPE_UNSPECIFIED"
    snapshot["current_margin_windows"][1]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = "MARGIN_WINDOW_TYPE_PRIVATE_ACCOUNT"
    evidence = slice2_preview_margin_windows_policy_context(snapshot)[
        "margin_windows_policy_evidence"
    ]
    evidence.update(
        classification="margin_window_type_undocumented_or_malformed",
        failing_policy_row_index=1,
        recognized_profile="retail_intraday_margin_1",
        failing_value_type="string",
    )

    with pytest.raises(
        ValidationError,
        match="margin_window_policy_invalid",
    ):
        AdminFuturesPreviewMarginWindowsPolicyEvidenceV2.model_validate(evidence)


def test_slice2_preview_r5_uses_exact_r4_predecessor_and_v2_policy(
    tmp_path: Path,
):
    rest_client = FakePreviewRestClient()
    snapshot = rest_client.get_futures_margin_collateral_snapshot()
    snapshot["current_margin_windows"][0]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = "MARGIN_WINDOW_TYPE_OVERNIGHT"
    snapshot["current_margin_windows"][1]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = "MARGIN_WINDOW_TYPE_WEEKEND"
    rest_client.read_calls.clear()
    rest_client.get_futures_margin_collateral_snapshot = (  # type: ignore[method-assign]
        lambda: snapshot
    )
    producer, store, _path = _producer(
        tmp_path,
        rest_client,
        artifact_type=FUTURES_PREVIEW_R5_ARTIFACT_TYPE,
        predecessor_binding=TEST_R4_PREDECESSOR_BINDING,
    )

    evidence = producer.run()

    assert evidence == store.read_completed()
    assert evidence["artifact_type"] == FUTURES_PREVIEW_R5_ARTIFACT_TYPE
    assert evidence["predecessor_binding"] == TEST_R4_PREDECESSOR_BINDING
    assert evidence.get("margin_windows_evidence") is None
    policy = evidence["margin_windows_policy_evidence"]
    assert policy["classification"] == "ready"
    assert policy["margin_window_policy_satisfied"] is True
    assert policy["profile_state_policy_authority"] == (
        "operator_defined_slice_2_preview_only_not_coinbase_documented"
    )
    assert policy["r5_attempt_authority_granted"] is False
    assert policy["execution_allowed"] is False
    assert evidence["margin_windows_policy_evidence_sha256"] == canonical_sha256(
        policy
    )
    assert len(rest_client.preview_calls) == 1
    assert rest_client.forbidden_calls == []
    AdminFuturesOrderPreviewResponse.model_validate(evidence)


def test_slice2_preview_r5_rejects_unspecified_with_sanitized_v2_evidence(
    tmp_path: Path,
):
    rest_client = FakePreviewRestClient()
    snapshot = rest_client.get_futures_margin_collateral_snapshot()
    snapshot["current_margin_windows"][0]["margin_window"].update(  # type: ignore[index]
        margin_window_type="MARGIN_WINDOW_TYPE_UNSPECIFIED",
        private_payload="PRIVATE_MARGIN_WINDOW_PAYLOAD",
    )
    rest_client.read_calls.clear()
    rest_client.get_futures_margin_collateral_snapshot = (  # type: ignore[method-assign]
        lambda: snapshot
    )
    producer, store, path = _producer(
        tmp_path,
        rest_client,
        artifact_type=FUTURES_PREVIEW_R5_ARTIFACT_TYPE,
        predecessor_binding=TEST_R4_PREDECESSOR_BINDING,
    )

    with pytest.raises(FuturesOrderPreviewArtifactError, match="blocked"):
        producer.run()

    evidence = store.read_completed()
    policy = evidence["margin_windows_policy_evidence"]
    assert evidence["attempt_counters"]["preview_order"] == 0
    assert evidence.get("margin_windows_evidence") is None
    assert policy["classification"] == (
        "margin_window_type_documented_but_operator_rejected"
    )
    assert policy["rows"][0]["observed_token"] == (
        "MARGIN_WINDOW_TYPE_UNSPECIFIED"
    )
    assert policy["rows"][0]["operator_policy_match"] is False
    assert rest_client.preview_calls == []
    assert "PRIVATE_MARGIN_WINDOW_PAYLOAD" not in path.read_text(encoding="utf-8")
    AdminFuturesOrderPreviewResponse.model_validate(evidence)


def test_r5_response_rejects_policy_or_seal_authority_tampering(
    tmp_path: Path,
):
    rest_client = FakePreviewRestClient()
    snapshot = rest_client.get_futures_margin_collateral_snapshot()
    snapshot["current_margin_windows"][0]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = "MARGIN_WINDOW_TYPE_OVERNIGHT"
    rest_client.get_futures_margin_collateral_snapshot = (  # type: ignore[method-assign]
        lambda: snapshot
    )
    producer, _store, _path = _producer(
        tmp_path,
        rest_client,
        artifact_type=FUTURES_PREVIEW_R5_ARTIFACT_TYPE,
        predecessor_binding=TEST_R4_PREDECESSOR_BINDING,
    )
    accepted = producer.run()
    AdminFuturesOrderPreviewResponse.model_validate(accepted)

    def rehash(evidence: dict[str, object]) -> None:
        evidence["evidence_sha256"] = canonical_sha256(
            {
                key: value
                for key, value in evidence.items()
                if key != "evidence_sha256"
            }
        )

    missing_policy = deepcopy(accepted)
    missing_policy.pop("margin_windows_policy_evidence")
    missing_policy.pop("margin_windows_policy_evidence_sha256")
    rehash(missing_policy)
    with pytest.raises(ValidationError):
        AdminFuturesOrderPreviewResponse.model_validate(missing_policy)

    token_mismatch = deepcopy(accepted)
    token_mismatch["margin_windows_policy_evidence"]["rows"][0][  # type: ignore[index]
        "observed_token"
    ] = "MARGIN_WINDOW_TYPE_TRANSITION"
    token_mismatch["margin_windows_policy_evidence_sha256"] = canonical_sha256(
        token_mismatch["margin_windows_policy_evidence"]
    )
    token_mismatch["seal_ready_plan"]["preflight_evidence_hashes"][  # type: ignore[index]
        "margin_windows_policy_evidence"
    ] = token_mismatch["margin_windows_policy_evidence_sha256"]
    token_mismatch["seal_ready_plan_sha256"] = canonical_sha256(
        token_mismatch["seal_ready_plan"]
    )
    rehash(token_mismatch)
    with pytest.raises(ValidationError, match="policy_binding_invalid"):
        AdminFuturesOrderPreviewResponse.model_validate(token_mismatch)

    expanded_plan = deepcopy(accepted)
    expanded_plan["seal_ready_plan"]["no_live_posture"][  # type: ignore[index]
        "order_creation_authorized"
    ] = True
    expanded_plan["seal_ready_plan"][  # type: ignore[index]
        "later_live_eligibility_granted"
    ] = True
    expanded_plan["seal_ready_plan_sha256"] = canonical_sha256(
        expanded_plan["seal_ready_plan"]
    )
    rehash(expanded_plan)
    with pytest.raises(ValidationError, match="r5_seal_plan_invalid"):
        AdminFuturesOrderPreviewResponse.model_validate(expanded_plan)

    unbound_permission_hash = deepcopy(accepted)
    unbound_permission_hash["seal_ready_plan"]["preflight_evidence_hashes"][  # type: ignore[index]
        "permissions"
    ] = "0" * 64
    unbound_permission_hash["seal_ready_plan_sha256"] = canonical_sha256(
        unbound_permission_hash["seal_ready_plan"]
    )
    rehash(unbound_permission_hash)
    with pytest.raises(ValidationError, match="r5_seal_plan_invalid"):
        AdminFuturesOrderPreviewResponse.model_validate(unbound_permission_hash)

    expanded_candidate = deepcopy(accepted)
    expanded_candidate["candidate"][  # type: ignore[index]
        "create_order_authorized"
    ] = True
    expanded_candidate["candidate_sha256"] = canonical_sha256(
        expanded_candidate["candidate"]
    )
    expanded_candidate["seal_ready_plan"]["candidate"] = deepcopy(  # type: ignore[index]
        expanded_candidate["candidate"]
    )
    expanded_candidate["seal_ready_plan_sha256"] = canonical_sha256(
        expanded_candidate["seal_ready_plan"]
    )
    rehash(expanded_candidate)
    with pytest.raises(ValidationError, match="sanitized_evidence_binding_invalid"):
        AdminFuturesOrderPreviewResponse.model_validate(expanded_candidate)


def _rehash_self_consistent_r5_attempt_evidence(
    evidence: dict[str, object],
) -> None:
    """Rehash every R5 binding an artifact rewriter can recompute."""

    for field in ("product_evidence", "market_evidence", "candidate"):
        evidence[f"{field}_sha256"] = canonical_sha256(evidence[field])
    plan = evidence["seal_ready_plan"]
    assert isinstance(plan, dict)
    preflight_hashes = plan["preflight_evidence_hashes"]
    assert isinstance(preflight_hashes, dict)
    preflight_hashes["product"] = evidence["product_evidence_sha256"]
    preflight_hashes["market"] = evidence["market_evidence_sha256"]
    plan["candidate"] = deepcopy(evidence["candidate"])
    plan["correlation_id"] = evidence["correlation_id"]
    plan["idempotency_key"] = evidence["idempotency_key"]
    evidence["seal_ready_plan_sha256"] = canonical_sha256(plan)
    evidence["evidence_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in evidence.items()
            if key != "evidence_sha256"
        }
    )


def test_r5_response_recomputes_candidate_from_sanitized_exchange_evidence(
    tmp_path: Path,
):
    producer, _store, _path = _producer(
        tmp_path,
        FakePreviewRestClient(),
        artifact_type=FUTURES_PREVIEW_R5_ARTIFACT_TYPE,
        predecessor_binding=TEST_R4_PREDECESSOR_BINDING,
    )
    accepted = producer.run()
    AdminFuturesOrderPreviewResponse.model_validate(accepted)

    attacks: list[dict[str, object]] = []

    disabled = deepcopy(accepted)
    disabled["product_evidence"]["trading_disabled"] = True  # type: ignore[index]
    attacks.append(disabled)

    two_contract_minimum = deepcopy(accepted)
    two_contract_minimum["product_evidence"]["base_min_size"] = "2"  # type: ignore[index]
    attacks.append(two_contract_minimum)

    wrong_expiry = deepcopy(accepted)
    wrong_expiry["product_evidence"]["future_product_details"][  # type: ignore[index]
        "contract_expiry"
    ] = "2020-12-20T16:00:00Z"
    attacks.append(wrong_expiry)

    crossed_book = deepcopy(accepted)
    crossed_book["market_evidence"]["best_bid"] = crossed_book[  # type: ignore[index]
        "market_evidence"
    ]["best_ask"]
    attacks.append(crossed_book)

    stale_market = deepcopy(accepted)
    stale_market["market_evidence"][  # type: ignore[index]
        "exchange_observed_at"
    ] = "2000-01-01T00:00:00Z"
    attacks.append(stale_market)

    historical_pair = deepcopy(accepted)
    historical_pair["market_evidence"][  # type: ignore[index]
        "exchange_observed_at"
    ] = "2000-01-01T00:00:00Z"
    historical_pair["candidate"]["observed_at"] = (  # type: ignore[index]
        "2000-01-01T00:00:00Z"
    )
    attacks.append(historical_pair)

    for attack in attacks:
        _rehash_self_consistent_r5_attempt_evidence(attack)
        with pytest.raises(
            ValidationError,
            match="sanitized_evidence_binding_invalid|timestamp_invalid",
        ):
            AdminFuturesOrderPreviewResponse.model_validate(attack)


def test_r5_claim_and_response_reject_consumed_identifiers_and_bad_timestamps(
    tmp_path: Path,
):
    producer, _store, _path = _producer(
        tmp_path,
        FakePreviewRestClient(),
        artifact_type=FUTURES_PREVIEW_R5_ARTIFACT_TYPE,
        predecessor_binding=TEST_R4_PREDECESSOR_BINDING,
    )
    claim = producer.build_claim()
    claim["correlation_id"] = "f32948c1-6bf1-421a-9267-6138ec2228ae"
    with pytest.raises(FuturesOrderPreviewArtifactError, match="identifier"):
        preview_module._validate_r5_claim_record(claim)

    accepted = producer.run()
    attacks: list[dict[str, object]] = []

    consumed_ids = deepcopy(accepted)
    consumed_ids["correlation_id"] = "f32948c1-6bf1-421a-9267-6138ec2228ae"
    consumed_ids["idempotency_key"] = "77016c90-d1e1-4344-84c7-53b3c2dca70b"
    attacks.append(consumed_ids)

    noncanonical_time = deepcopy(accepted)
    noncanonical_time["reserved_at"] = str(noncanonical_time["reserved_at"]).replace(
        "Z", "+00:00"
    )
    attacks.append(noncanonical_time)

    reversed_time = deepcopy(accepted)
    reversed_time["completed_at"] = "2000-01-01T00:00:00Z"
    attacks.append(reversed_time)

    for attack in attacks:
        _rehash_self_consistent_r5_attempt_evidence(attack)
        with pytest.raises(
            ValidationError,
            match="identifier|timestamp",
        ):
            AdminFuturesOrderPreviewResponse.model_validate(attack)


def test_r5_artifact_store_rejects_self_consistent_claim_identity_drift(
    tmp_path: Path,
):
    producer, _store, path = _producer(
        tmp_path,
        FakePreviewRestClient(),
        artifact_type=FUTURES_PREVIEW_R5_ARTIFACT_TYPE,
        predecessor_binding=TEST_R4_PREDECESSOR_BINDING,
    )
    producer.run()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    evidence = rows[1]["record"]
    evidence["correlation_id"] = "changed-but-self-consistently-rehashed"
    evidence["evidence_sha256"] = canonical_sha256(
        {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    )
    rows[1]["record_sha256"] = canonical_sha256(
        {key: value for key, value in rows[1].items() if key != "record_sha256"}
    )
    path.chmod(0o600)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    path.chmod(0o400)

    with pytest.raises(FuturesOrderPreviewArtifactError, match="claim identity"):
        FuturesOrderPreviewArtifactStore(path).read_completed()


def test_r5_unknown_preview_outcome_is_consumed_once_with_ready_policy(
    tmp_path: Path,
):
    rest_client = FakePreviewRestClient(
        preview_error=TimeoutError("PRIVATE_UNKNOWN_PREVIEW_RESPONSE")
    )
    producer, store, path = _producer(
        tmp_path,
        rest_client,
        artifact_type=FUTURES_PREVIEW_R5_ARTIFACT_TYPE,
        predecessor_binding=TEST_R4_PREDECESSOR_BINDING,
    )

    with pytest.raises(FuturesOrderPreviewArtifactError, match="unknown"):
        producer.run()

    evidence = store.read_completed()
    assert evidence["outcome"] == "unknown"
    assert evidence["attempt_counters"] == {
        "preview_order": 1,
        "retry": 0,
        "fallback": 0,
        "create_order": 0,
        "cancel_order": 0,
        "close_position": 0,
        "reduce_position": 0,
    }
    assert evidence["margin_windows_policy_evidence"]["classification"] == "ready"
    assert len(rest_client.preview_calls) == 1
    assert "PRIVATE_UNKNOWN" not in path.read_text(encoding="utf-8")
    AdminFuturesOrderPreviewResponse.model_validate(evidence)
    with pytest.raises(FuturesOrderPreviewArtifactError, match="consumed"):
        producer.run()
    assert len(rest_client.preview_calls) == 1


def test_r5_nonaccepted_readback_rejects_invented_authority_and_raw_content(
    tmp_path: Path,
):
    rest_client = FakePreviewRestClient(
        preview_error=TimeoutError("PRIVATE_UNKNOWN_PREVIEW_RESPONSE")
    )
    producer, store, _path = _producer(
        tmp_path,
        rest_client,
        artifact_type=FUTURES_PREVIEW_R5_ARTIFACT_TYPE,
        predecessor_binding=TEST_R4_PREDECESSOR_BINDING,
    )
    with pytest.raises(FuturesOrderPreviewArtifactError, match="unknown"):
        producer.run()
    unknown = store.read_completed()
    AdminFuturesOrderPreviewResponse.model_validate(unknown)

    attacks: list[dict[str, object]] = []

    invented_plan = deepcopy(unknown)
    invented_plan["seal_ready_plan"] = {
        "no_live_posture": {"order_creation_authorized": True},
        "create_order_attempt_max": 1,
    }
    invented_plan["seal_ready_plan_sha256"] = canonical_sha256(
        invented_plan["seal_ready_plan"]
    )
    attacks.append(invented_plan)

    invented_response = deepcopy(unknown)
    invented_response["preview_response"] = {
        "create_order_authorized": True,
        "raw_private": "PRIVATE_RESPONSE_MUST_NOT_READ_BACK",
    }
    invented_response["preview_response_sha256"] = canonical_sha256(
        invented_response["preview_response"]
    )
    attacks.append(invented_response)

    raw_blocker = deepcopy(unknown)
    raw_blocker["blocker"] = "PRIVATE EXCEPTION TEXT MUST NOT READ BACK"
    attacks.append(raw_blocker)

    false_read_trace = deepcopy(unknown)
    false_read_trace["live_coinbase_read_ran"] = False
    attacks.append(false_read_trace)

    for attack in attacks:
        attack["evidence_sha256"] = canonical_sha256(
            {
                key: value
                for key, value in attack.items()
                if key != "evidence_sha256"
            }
        )
        with pytest.raises(ValidationError):
            AdminFuturesOrderPreviewResponse.model_validate(attack)


def test_r5_blocked_after_preview_withholds_preview_response_content(
    tmp_path: Path,
):
    response = _preview()
    response["best_bid"] = "7.00"
    rest_client = FakePreviewRestClient(preview_response=response)
    producer, store, path = _producer(
        tmp_path,
        rest_client,
        artifact_type=FUTURES_PREVIEW_R5_ARTIFACT_TYPE,
        predecessor_binding=TEST_R4_PREDECESSOR_BINDING,
    )

    with pytest.raises(FuturesOrderPreviewArtifactError, match="blocked"):
        producer.run()

    blocked = store.read_completed()
    assert blocked["outcome"] == "blocked"
    assert blocked["attempt_counters"]["preview_order"] == 1
    assert "preview_response" not in blocked
    assert "preview_response_sha256" not in blocked
    assert "PRIVATE" not in path.read_text(encoding="utf-8")
    AdminFuturesOrderPreviewResponse.model_validate(blocked)


@pytest.mark.parametrize(
    ("correlation_id", "idempotency_key"),
    [
        ("not-a-uuid", "2d8327f6-826c-4f73-82a4-822e29f73065"),
        (
            "8f604e56-0a23-1bda-b244-11ebc0194241",
            "2d8327f6-826c-4f73-82a4-822e29f73065",
        ),
        (
            "8F604E56-0A23-4BDA-B244-11EBC0194241",
            "2d8327f6-826c-4f73-82a4-822e29f73065",
        ),
    ],
)
def test_r5_claim_rejects_noncanonical_or_non_v4_identifiers_before_reserve(
    tmp_path: Path,
    correlation_id: str,
    idempotency_key: str,
):
    path = tmp_path / "invalid-r5-identifiers.jsonl"
    producer = FuturesOrderPreviewProducer(
        rest_client=FakePreviewRestClient(),
        store=FuturesOrderPreviewArtifactStore(path),
        predecessor_binding=TEST_R4_PREDECESSOR_BINDING,
        predecessor_validator=lambda: dict(TEST_R4_PREDECESSOR_BINDING),
        artifact_type=FUTURES_PREVIEW_R5_ARTIFACT_TYPE,
        now=lambda: NOW,
        correlation_id_factory=lambda: correlation_id,
        idempotency_key_factory=lambda: idempotency_key,
    )

    with pytest.raises(FuturesOrderPreviewArtifactError, match="UUIDv4"):
        producer.run()
    assert not path.exists()


def test_r5_fixed_path_and_r4_predecessor_match_the_sealed_artifact():
    before = FUTURES_PREVIEW_R4_ARTIFACT_PATH.stat()

    assert FUTURES_PREVIEW_R5_ARTIFACT_PATH.name == (
        "futures_exact_no_live_preview_slice_2r5.jsonl"
    )
    assert FUTURES_PREVIEW_R4_PREDECESSOR_BINDING == TEST_R4_PREDECESSOR_BINDING
    assert validate_production_futures_order_preview_r4_predecessor() == (
        TEST_R4_PREDECESSOR_BINDING
    )
    assert FUTURES_PREVIEW_R4_FILE_SHA256 == TEST_R4_PREDECESSOR_BINDING[
        "file_sha256"
    ]
    assert FUTURES_PREVIEW_R4_EVIDENCE_SHA256 == TEST_R4_PREDECESSOR_BINDING[
        "evidence_sha256"
    ]
    assert (
        FUTURES_PREVIEW_R4_DEVICE,
        FUTURES_PREVIEW_R4_INODE,
        FUTURES_PREVIEW_R4_SIZE,
        FUTURES_PREVIEW_R4_MODE,
        FUTURES_PREVIEW_R4_MTIME_NS,
    ) == (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mode & 0o777,
        before.st_mtime_ns,
    )


def test_default_readback_stays_r4_until_valid_immutable_r5_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    r4_path = tmp_path / "default-r4.jsonl"
    r5_path = tmp_path / "candidate-r5.jsonl"
    monkeypatch.delenv(
        "COINBASE_ADMIN_API_FUTURES_ORDER_PREVIEW_ARTIFACT_PATH",
        raising=False,
    )
    monkeypatch.setattr(
        preview_module,
        "DEFAULT_FUTURES_PREVIEW_ARTIFACT_PATH",
        r4_path,
    )
    monkeypatch.setattr(
        preview_module,
        "FUTURES_PREVIEW_R5_ARTIFACT_PATH",
        r5_path,
    )

    assert configured_futures_order_preview_artifact_path() == r4_path

    claim_store = FuturesOrderPreviewArtifactStore(r5_path)
    claim_store.reserve(
        {
            "artifact_type": FUTURES_PREVIEW_R5_ARTIFACT_TYPE,
            "claim_status": "reserved",
        }
    )
    assert r5_path.stat().st_mode & 0o777 == 0o600
    assert configured_futures_order_preview_artifact_path() == r4_path

    r5_path.unlink()
    producer, _store, produced_path = _producer(
        tmp_path,
        FakePreviewRestClient(),
        artifact_type=FUTURES_PREVIEW_R5_ARTIFACT_TYPE,
        predecessor_binding=TEST_R4_PREDECESSOR_BINDING,
    )
    monkeypatch.setattr(
        preview_module,
        "FUTURES_PREVIEW_R5_ARTIFACT_PATH",
        produced_path,
    )
    producer.run()
    assert produced_path.stat().st_mode & 0o777 == 0o400
    monkeypatch.setattr(
        preview_module,
        "validate_production_futures_order_preview_r5_terminal",
        lambda: preview_module.FUTURES_PREVIEW_R5_TERMINAL_BINDING,
    )
    assert configured_futures_order_preview_artifact_path() == produced_path


def test_r5_policy_validator_is_separate_from_exact_r4_v1_validator():
    snapshot = FakePreviewRestClient().get_futures_margin_collateral_snapshot()
    snapshot["current_margin_windows"][0]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = "MARGIN_WINDOW_TYPE_TRANSITION"

    assert validate_slice2_preview_margin_collateral_evidence(snapshot) == (
        Decimal("250.00")
    )
    with pytest.raises(
        ValueError,
        match="^futures_preview_margin_windows_ambiguous$",
    ):
        validate_margin_collateral_evidence(snapshot)


def test_margin_windows_ambiguity_persists_only_typed_sanitized_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    rest_client = FakePreviewRestClient()
    snapshot = rest_client.get_futures_margin_collateral_snapshot()
    snapshot["current_margin_windows"][0]["margin_window"].update(
        margin_window_type="MARGIN_WINDOW_TYPE_PRIVATE_ACCOUNT",
        private_response_body="PRIVATE_HTTP_RESPONSE_BODY",
    )
    rest_client.read_calls.clear()
    rest_client.get_futures_margin_collateral_snapshot = (  # type: ignore[method-assign]
        lambda: snapshot
    )
    producer, store, path = _producer(
        tmp_path,
        rest_client,
        artifact_type="futures_exact_no_live_preview_slice_2r4",
        predecessor_binding=TEST_R3_PREDECESSOR_BINDING,
    )

    with pytest.raises(FuturesOrderPreviewArtifactError, match="blocked"):
        producer.run()

    terminal = store.read_completed()
    diagnostic = terminal["margin_windows_evidence"]
    assert terminal["artifact_type"] == (
        "futures_exact_no_live_preview_slice_2r4"
    )
    assert terminal["predecessor_binding"] == TEST_R3_PREDECESSOR_BINDING
    assert terminal["blocker"] == "preflight_or_preview_stage_blocked"
    assert terminal["attempt_counters"]["preview_order"] == 0
    assert rest_client.preview_calls == []
    assert "margin_collateral_evidence" not in terminal
    assert diagnostic == {
        "schema_version": "1",
        "source": "backend_rest_client.get_current_margin_window",
        "stage": "margin_collateral_validation",
        "field_path": "current_margin_windows",
        "container_present": True,
        "container_type": "sequence",
        "row_count_bucket": "expected_two",
        "expected_row_count": 2,
        "failing_row_index": 0,
        "recognized_profile": "retail_regular",
        "failing_field": "margin_window_type",
        "failing_value_type": "string",
        "classification": (
            "margin_window_type_not_exact_operational_enum_token"
        ),
        "sanitized": True,
        "raw_response_included": False,
        "external_exception_text_included": False,
        "unknown_identifier_values_included": False,
    }
    assert terminal["margin_windows_evidence_sha256"] == canonical_sha256(
        diagnostic
    )
    assert "PRIVATE" not in path.read_text(encoding="utf-8")
    AdminFuturesOrderPreviewResponse.model_validate(terminal)
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-token")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_FUTURES_ORDER_PREVIEW_ARTIFACT_PATH",
        str(path),
    )
    response = TestClient(create_app()).get(
        "/api/v1/futures/order-preview",
        headers={
            "Authorization": "Bearer test-token",
            "X-Admin-Actor": "operator-1",
            "X-Admin-Roles": "viewer",
        },
    )
    assert response.status_code == 200
    assert response.headers["X-Live-Execution-Enabled"] == "false"
    assert response.json()["margin_windows_evidence"] == diagnostic
    assert response.json()["attempt_counters"]["preview_order"] == 0
    assert "PRIVATE" not in response.text

    hash_drift = deepcopy(terminal)
    hash_drift["margin_windows_evidence"]["failing_row_index"] = 1
    hash_drift["evidence_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in hash_drift.items()
            if key != "evidence_sha256"
        }
    )
    with pytest.raises(ValidationError, match="margin_windows.*hash"):
        AdminFuturesOrderPreviewResponse.model_validate(hash_drift)

    raw_expansion = deepcopy(terminal)
    raw_expansion["margin_windows_evidence"]["raw_profile"] = (
        "MARGIN_PROFILE_TYPE_PRIVATE_ACCOUNT"
    )
    raw_expansion["margin_windows_evidence_sha256"] = canonical_sha256(
        raw_expansion["margin_windows_evidence"]
    )
    raw_expansion["evidence_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in raw_expansion.items()
            if key != "evidence_sha256"
        }
    )
    with pytest.raises(ValidationError):
        AdminFuturesOrderPreviewResponse.model_validate(raw_expansion)

    wrong_reason = deepcopy(terminal)
    wrong_reason["pre_preview_stage_evidence"]["stages"][-1][
        "reason_code"
    ] = "futures_preview_margin_killswitch_ambiguous"
    wrong_reason["pre_preview_stage_evidence_sha256"] = canonical_sha256(
        wrong_reason["pre_preview_stage_evidence"]
    )
    wrong_reason["evidence_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in wrong_reason.items()
            if key != "evidence_sha256"
        }
    )
    with pytest.raises(ValidationError, match="margin_windows_evidence_invalid"):
        AdminFuturesOrderPreviewResponse.model_validate(wrong_reason)

    ready_claim = deepcopy(terminal)
    ready_claim["margin_windows_evidence"].update(
        classification="ready",
        failing_row_index=None,
        recognized_profile=None,
        failing_field=None,
        failing_value_type=None,
    )
    ready_claim["margin_windows_evidence_sha256"] = canonical_sha256(
        ready_claim["margin_windows_evidence"]
    )
    ready_claim["evidence_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in ready_claim.items()
            if key != "evidence_sha256"
        }
    )
    with pytest.raises(ValidationError, match="margin_windows_evidence_invalid"):
        AdminFuturesOrderPreviewResponse.model_validate(ready_claim)

    stripped_diagnostic = deepcopy(terminal)
    stripped_diagnostic.pop("margin_windows_evidence")
    stripped_diagnostic.pop("margin_windows_evidence_sha256")
    stripped_diagnostic["evidence_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in stripped_diagnostic.items()
            if key != "evidence_sha256"
        }
    )
    with pytest.raises(ValidationError, match="margin_windows_evidence_missing"):
        AdminFuturesOrderPreviewResponse.model_validate(stripped_diagnostic)

    attempted_preview = deepcopy(terminal)
    attempted_preview["attempt_counters"]["preview_order"] = 1
    attempted_preview["evidence_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in attempted_preview.items()
            if key != "evidence_sha256"
        }
    )
    with pytest.raises(ValidationError, match="stage_evidence_invalid"):
        AdminFuturesOrderPreviewResponse.model_validate(attempted_preview)

    incomplete_reads = deepcopy(terminal)
    incomplete_reads["read_counters"]["futures_margin_collateral"] = 0
    incomplete_reads["evidence_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in incomplete_reads.items()
            if key != "evidence_sha256"
        }
    )
    with pytest.raises(ValidationError, match="stage_evidence_invalid"):
        AdminFuturesOrderPreviewResponse.model_validate(incomplete_reads)

    missing_prior_margin_setting = deepcopy(terminal)
    missing_prior_margin_setting.pop("margin_setting_evidence")
    missing_prior_margin_setting.pop("margin_setting_evidence_sha256")
    missing_prior_margin_setting["evidence_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in missing_prior_margin_setting.items()
            if key != "evidence_sha256"
        }
    )
    with pytest.raises(ValidationError, match="r4_margin_setting_evidence_invalid"):
        AdminFuturesOrderPreviewResponse.model_validate(
            missing_prior_margin_setting
        )


@pytest.mark.parametrize(
    ("permissions", "portfolios"),
    [
        (
            {
                **_permissions(),
                "portfolio_uuid": "wrong-default-portfolio",
            },
            _portfolios(),
        ),
        (
            {
                **_permissions(),
                "portfolio_type": "CONSUMER",
            },
            [
                {
                    "uuid": "default-portfolio-uuid",
                    "name": "Test",
                    "type": "CONSUMER",
                }
            ],
        ),
        (
            _permissions(),
            [*_portfolios(), *_portfolios()],
        ),
        (
            _permissions(can_trade=False),
            _portfolios(),
        ),
    ],
    ids=("wrong", "test-profile", "ambiguous", "no-trade"),
)
def test_invalid_default_binding_stops_before_all_downstream_coinbase_reads(
    tmp_path: Path,
    permissions: dict[str, object],
    portfolios: list[dict[str, object]],
):
    rest_client = FakePreviewRestClient(
        permissions_response=permissions,
        portfolios_response=portfolios,
    )
    producer, store, path = _producer(tmp_path, rest_client)

    with pytest.raises(FuturesOrderPreviewArtifactError, match="blocked"):
        producer.run()

    assert rest_client.read_calls == [
        "api_key_permissions",
        "portfolio_catalog",
    ]
    assert rest_client.preview_calls == []
    terminal = store.read_completed()
    assert terminal["status"] == "blocked"
    assert terminal["outcome"] == "blocked"
    assert terminal["attempt_counters"]["preview_order"] == 0
    assert terminal["read_counters"] == {
        "api_key_permissions": 1,
        "portfolio_catalog": 1,
        "product": 0,
        "best_bid_ask": 0,
        "futures_positions": 0,
        "futures_margin_collateral": 0,
    }
    assert terminal["exchange_submission_attempt_count"] == 0
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_preview_accepts_documented_margin_ratio_liquidation_replacement():
    response = _preview()
    response.pop("current_liquidation_buffer")
    response.pop("projected_liquidation_buffer")
    response["margin_ratio_data"] = {
        "current_margin_ratio": "0.20",
        "projected_margin_ratio": "0.25",
    }
    response["predicted_liquidation_price"] = "3.10"

    normalized = validate_preview_response(response)

    assert normalized["liquidation_evidence_source"] == (
        "margin_ratio_data_and_predicted_liquidation_price"
    )


@pytest.mark.parametrize("field", ["errs", "warning"])
def test_preview_requires_explicit_empty_error_and_warning_collections(field: str):
    missing = _preview()
    missing.pop(field)
    malformed = _preview()
    malformed[field] = ""

    with pytest.raises(ValueError, match="response"):
        validate_preview_response(missing)
    with pytest.raises(ValueError, match="response"):
        validate_preview_response(malformed)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda response: response.update(order_margin_total="NaN"),
        lambda response: response.update(current_liquidation_buffer="NaN"),
        lambda response: response.update(projected_liquidation_buffer="Infinity"),
        lambda response: (
            response.pop("current_liquidation_buffer"),
            response.pop("projected_liquidation_buffer"),
            response.update(
                margin_ratio_data={
                    "current_margin_ratio": "NaN",
                    "projected_margin_ratio": "0.25",
                },
                predicted_liquidation_price="3.10",
            ),
        ),
        lambda response: (
            response.pop("current_liquidation_buffer"),
            response.pop("projected_liquidation_buffer"),
            response.update(
                margin_ratio_data={
                    "current_margin_ratio": "0.20",
                    "projected_margin_ratio": "0.25",
                },
                predicted_liquidation_price="NaN",
            ),
        ),
    ],
)
def test_preview_rejects_nonfinite_margin_and_liquidation(mutation):
    response = _preview()
    mutation(response)

    with pytest.raises(ValueError, match="margin|liquidation|finite"):
        validate_preview_response(response)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("base_size", "2"),
        ("order_total", "100"),
        ("quote_size", "100"),
        ("best_ask", "10"),
    ],
)
def test_preview_size_and_notional_drift_is_terminal_blocked(
    tmp_path: Path,
    field: str,
    value: str,
):
    response = _preview()
    response[field] = value
    rest_client = FakePreviewRestClient(preview_response=response)
    producer, store, _path = _producer(tmp_path, rest_client)

    with pytest.raises(FuturesOrderPreviewArtifactError, match="blocked"):
        producer.run()

    terminal = store.read_completed()
    assert terminal["status"] == "blocked"
    assert terminal["attempt_counters"]["preview_order"] == 1
    assert terminal["exchange_submission_attempt_count"] == 0
    assert terminal["candidate_sha256"] == canonical_sha256(terminal["candidate"])
    assert terminal["preview_request_sha256"] == canonical_sha256(
        terminal["preview_request"]
    )
    assert terminal["preview_response"][field] == value
    assert terminal["preview_response_sha256"] == canonical_sha256(
        terminal["preview_response"]
    )
    assert terminal["product_evidence_sha256"] == canonical_sha256(
        terminal["product_evidence"]
    )


def test_post_preview_failure_persists_only_allowlisted_response_fields(
    tmp_path: Path,
):
    response = _preview()
    response["base_size"] = "2"
    response["PRIVATE_UNKNOWN_IDENTIFIER"] = (
        "PRIVATE_PREVIEW_RESPONSE_MUST_NOT_PERSIST"
    )
    rest_client = FakePreviewRestClient(preview_response=response)
    producer, store, path = _producer(tmp_path, rest_client)

    with pytest.raises(FuturesOrderPreviewArtifactError, match="blocked"):
        producer.run()

    terminal = store.read_completed()
    assert terminal["status"] == "blocked"
    assert terminal["attempt_counters"]["preview_order"] == 1
    assert set(terminal["preview_response"]) == {
        "preview_id",
        "errs",
        "warning",
        "order_total",
        "commission_total",
        "quote_size",
        "base_size",
        "best_bid",
        "best_ask",
        "order_margin_total",
        "current_liquidation_buffer",
        "projected_liquidation_buffer",
        "liquidation_evidence_source",
    }
    assert terminal["preview_response"]["base_size"] == "2"
    assert "PRIVATE" not in path.read_text(encoding="utf-8")
    AdminFuturesOrderPreviewResponse.model_validate(terminal)


def test_malformed_post_preview_response_still_appends_redacted_terminal_result(
    tmp_path: Path,
):
    response = _preview()
    response["order_total"] = float("nan")
    response["PRIVATE_UNKNOWN_IDENTIFIER"] = (
        "PRIVATE_PREVIEW_RESPONSE_MUST_NOT_PERSIST"
    )
    rest_client = FakePreviewRestClient(preview_response=response)
    producer, store, path = _producer(tmp_path, rest_client)

    with pytest.raises(FuturesOrderPreviewArtifactError, match="blocked"):
        producer.run()

    terminal = store.read_completed()
    assert terminal["status"] == "blocked"
    assert terminal["blocker"] == "preflight_or_preview_blocked:ValueError"
    assert terminal["attempt_counters"]["preview_order"] == 1
    assert "preview_response" not in terminal
    assert "preview_response_sha256" not in terminal
    artifact_text = path.read_text(encoding="utf-8")
    assert "PRIVATE" not in artifact_text
    assert "NaN" not in artifact_text
    assert len(artifact_text.splitlines()) == 2
    AdminFuturesOrderPreviewResponse.model_validate(terminal)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("90"), "90.00"),
        (Decimal("120"), "120.00"),
        (Decimal("0"), "0.00"),
        (Decimal("64.8000"), "64.80"),
    ],
)
def test_notional_text_never_strips_integral_trailing_zeroes(
    value: Decimal,
    expected: str,
):
    assert _notional_text(value) == expected


def test_claim_consumes_attempt_before_sdk_unknown_outcome_and_replay(tmp_path: Path):
    rest_client = FakePreviewRestClient(preview_error=TimeoutError("ambiguous"))
    producer, store, path = _producer(tmp_path, rest_client)

    with pytest.raises(FuturesOrderPreviewArtifactError, match="unknown"):
        producer.run()

    assert len(rest_client.preview_calls) == 1
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["record_type"] == "claim"
    assert rows[1]["record_type"] == "result"
    assert rows[1]["outcome"] == "unknown"
    with pytest.raises(FuturesOrderPreviewArtifactError, match="consumed"):
        producer.run()
    assert len(rest_client.preview_calls) == 1
    terminal = store.read_completed()
    assert terminal["status"] == "unknown"
    assert terminal["outcome"] == "unknown"
    assert terminal["attempt_counters"]["preview_order"] == 1
    assert terminal["submitted_notional_usdc"] == "0"
    assert terminal["executed_notional_usdc"] == "0"
    assert terminal["candidate_sha256"] == canonical_sha256(terminal["candidate"])
    assert terminal["preview_request"] == rest_client.preview_calls[0]
    assert terminal["preview_request_sha256"] == canonical_sha256(
        terminal["preview_request"]
    )
    assert terminal["permission_evidence_sha256"] == canonical_sha256(
        terminal["permission_evidence"]
    )
    assert terminal["portfolio_catalog_sha256"] == canonical_sha256(
        terminal["portfolio_catalog_evidence"]
    )
    assert terminal["product_evidence_sha256"] == canonical_sha256(
        terminal["product_evidence"]
    )
    assert terminal["market_evidence_sha256"] == canonical_sha256(
        terminal["market_evidence"]
    )
    assert terminal["position_evidence_sha256"] == canonical_sha256(
        terminal["position_evidence"]
    )
    assert terminal["margin_collateral_evidence_sha256"] == canonical_sha256(
        terminal["margin_collateral_evidence"]
    )


def test_claim_only_crash_state_is_consumed_and_fails_closed(tmp_path: Path):
    producer, store, path = _producer(tmp_path, FakePreviewRestClient())
    claim = producer.build_claim()
    store.reserve(claim)

    with pytest.raises(FuturesOrderPreviewArtifactError, match="not completed"):
        store.read_completed()
    with pytest.raises(FuturesOrderPreviewArtifactError, match="consumed"):
        store.reserve(claim)
    assert path.exists()


def test_concurrent_r3_reservations_allow_exactly_one_claim(tmp_path: Path):
    producer, store, path = _producer(tmp_path, FakePreviewRestClient())
    claim = producer.build_claim()

    def reserve_once() -> str:
        try:
            store.reserve(claim)
        except FuturesOrderPreviewArtifactError:
            return "blocked"
        return "reserved"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _index: reserve_once(), range(2)))

    assert sorted(outcomes) == ["blocked", "reserved"]
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_result_append_failure_consumes_r3_without_second_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    rest_client = FakePreviewRestClient()
    producer, store, path = _producer(tmp_path, rest_client)
    monkeypatch.setattr(
        store,
        "append_result",
        lambda _result: (_ for _ in ()).throw(
            FuturesOrderPreviewArtifactError(
                "futures Preview artifact result append failed"
            )
        ),
    )

    with pytest.raises(FuturesOrderPreviewArtifactError, match="append"):
        producer.run()

    assert len(rest_client.preview_calls) == 1
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
    with pytest.raises(FuturesOrderPreviewArtifactError, match="consumed"):
        producer.run()
    assert len(rest_client.preview_calls) == 1


def test_store_rejects_tamper_extra_record_and_symlink(tmp_path: Path):
    producer, store, path = _producer(tmp_path, FakePreviewRestClient())
    producer.run()

    rows = path.read_text(encoding="utf-8").splitlines()
    result = json.loads(rows[1])
    result["record"]["preview_response"]["commission_total"] = "0"
    path.chmod(0o600)
    path.write_text(rows[0] + "\n" + json.dumps(result) + "\n", encoding="utf-8")
    path.chmod(0o400)
    with pytest.raises(FuturesOrderPreviewArtifactError, match="tampered"):
        store.read_completed()

    path.unlink()
    target = tmp_path / "target.jsonl"
    target.write_text("{}\n", encoding="utf-8")
    path.symlink_to(target)
    with pytest.raises(FuturesOrderPreviewArtifactError, match="symlink"):
        store.read_completed()


def test_store_requires_read_only_terminal_mode(tmp_path: Path):
    producer, store, path = _producer(tmp_path, FakePreviewRestClient())
    producer.run()
    path.chmod(0o600)

    with pytest.raises(FuturesOrderPreviewArtifactError, match="mode"):
        store.read_completed()


def test_store_rejects_self_consistent_terminal_chain_contradictions(
    tmp_path: Path,
):
    producer, store, path = _producer(tmp_path, FakePreviewRestClient())
    producer.run()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[1]["outcome"] = "unknown"
    rows[1]["record_sha256"] = canonical_sha256(
        {key: value for key, value in rows[1].items() if key != "record_sha256"}
    )
    path.chmod(0o600)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    path.chmod(0o400)

    with pytest.raises(FuturesOrderPreviewArtifactError, match="outcome"):
        store.read_completed()

    producer, store, path = _producer(
        tmp_path / "claim-sha",
        FakePreviewRestClient(),
    )
    producer.run()
    evidence = store.read_completed()
    evidence["claim_sha256"] = "0" * 64
    _rewrite_terminal_evidence(path, evidence)

    with pytest.raises(FuturesOrderPreviewArtifactError, match="claim"):
        store.read_completed()


def test_coinbase_wrapper_preview_call_shape_and_count():
    class FakeSdk:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def get_best_bid_ask(self, **kwargs: object) -> SimpleNamespace:
            self.calls.append({"method": "get_best_bid_ask", **kwargs})
            return SimpleNamespace(to_dict=lambda: _book())

        def preview_order(self, **kwargs: object) -> SimpleNamespace:
            self.calls.append({"method": "preview_order", **kwargs})
            return SimpleNamespace(to_dict=lambda: _preview())

    sdk = FakeSdk()
    client = CoinbaseRestClient(sdk)
    request = {
        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
        "side": "BUY",
        "order_configuration": {
            "limit_limit_gtc": {
                "base_size": "1",
                "limit_price": "6.45",
                "post_only": True,
            }
        },
    }

    assert client.get_best_bid_ask(product_ids=[FUTURES_PREVIEW_PRODUCT_ID]) == _book()
    assert client.preview_order(**request) == _preview()
    assert sdk.calls == [
        {
            "method": "get_best_bid_ask",
            "product_ids": [FUTURES_PREVIEW_PRODUCT_ID],
        },
        {"method": "preview_order", **request},
    ]


@pytest.mark.parametrize(
    "payload, blocker",
    [
        ({}, "positions evidence is missing"),
        ({"positions": {}}, "positions evidence is not a list"),
        ({"positions": ["invalid"]}, "position row is invalid"),
        (
            {
                "positions": [
                    {"side": "LONG", "number_of_contracts": "1"},
                ]
            },
            "position product_id is missing",
        ),
        (
            {
                "positions": [
                    {
                        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
                        "side": "LONG",
                    },
                ]
            },
            "position contract count is missing",
        ),
        (
            {
                "positions": [
                    {
                        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
                        "side": "LONG",
                        "number_of_contracts": "NaN",
                    },
                ]
            },
            "position contract count is invalid",
        ),
        (
            {
                "positions": [
                    {
                        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
                        "side": "UNKNOWN",
                        "number_of_contracts": "1",
                    },
                ]
            },
            "position side is invalid",
        ),
        (
            {
                "positions": [
                    {
                        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
                        "side": "LONG",
                        "number_of_contracts": "1",
                    },
                    {
                        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
                        "side": "SHORT",
                        "number_of_contracts": "1",
                    },
                ]
            },
            "duplicate futures position",
        ),
    ],
)
def test_coinbase_wrapper_rejects_ambiguous_futures_position_evidence(
    payload: dict[str, object],
    blocker: str,
):
    class FakeSdk:
        def list_futures_positions(self) -> SimpleNamespace:
            return SimpleNamespace(to_dict=lambda: payload)

    with pytest.raises(ValueError, match=blocker):
        CoinbaseRestClient(FakeSdk()).get_futures_positions()


def test_get_route_is_authenticated_read_only_and_never_uses_coinbase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    rest_client = FakePreviewRestClient()
    producer, _store, path = _producer(tmp_path, rest_client)
    expected = producer.run()
    preview_calls_before_get = len(rest_client.preview_calls)
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-token")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_FUTURES_ORDER_PREVIEW_ARTIFACT_PATH",
        str(path),
    )
    client = TestClient(create_app())

    assert client.get("/api/v1/futures/order-preview").status_code == 401
    missing_roles = client.get(
        "/api/v1/futures/order-preview",
        headers={
            "Authorization": "Bearer test-token",
            "X-Admin-Actor": "operator-1",
        },
    )
    assert missing_roles.status_code == 403
    response = client.get(
        "/api/v1/futures/order-preview",
        headers={
            "Authorization": "Bearer test-token",
            "X-Admin-Actor": "operator-1",
            "X-Admin-Roles": "viewer",
        },
    )

    assert response.status_code == 200
    assert response.json() == expected
    assert response.json()["predecessor_binding"] == TEST_PREDECESSOR_BINDING
    assert len(rest_client.preview_calls) == preview_calls_before_get
    assert response.headers["X-Live-Execution-Enabled"] == "false"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda evidence: evidence["attempt_counters"].update(preview_order=0),
        lambda evidence: evidence["read_counters"].update(product=0),
        lambda evidence: evidence.update(live_coinbase_read_ran=False),
        lambda evidence: (
            evidence["portfolio_binding"].update(
                can_trade=False,
                credential_trade_permission_present=False,
            ),
        ),
    ],
    ids=("preview-count", "read-count", "live-read", "trade-permission"),
)
def test_accepted_readback_rejects_incomplete_attempt_and_binding_evidence(
    tmp_path: Path,
    mutation,
):
    producer, _store, _path = _producer(tmp_path, FakePreviewRestClient())
    evidence = producer.run()
    mutation(evidence)
    evidence["evidence_sha256"] = canonical_sha256(
        {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    )

    with pytest.raises(ValidationError):
        AdminFuturesOrderPreviewResponse.model_validate(evidence)


def test_accepted_readback_rejects_authoritative_preview_cap_drift(
    tmp_path: Path,
):
    producer, _store, _path = _producer(tmp_path, FakePreviewRestClient())
    evidence = producer.run()
    preview = evidence["preview_response"]
    preview["candidate_binding"]["authoritative_opening_reference_notional_usdc"] = (
        "100.00"
    )
    evidence["preview_response_sha256"] = canonical_sha256(preview)
    authoritative = evidence["seal_ready_plan"]["authoritative_preview"]
    authoritative["preview_response"] = preview
    authoritative["preview_response_sha256"] = evidence["preview_response_sha256"]
    authoritative["candidate_binding"] = preview["candidate_binding"]
    evidence["seal_ready_plan_sha256"] = canonical_sha256(
        evidence["seal_ready_plan"]
    )
    evidence["evidence_sha256"] = canonical_sha256(
        {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    )

    with pytest.raises(ValidationError):
        AdminFuturesOrderPreviewResponse.model_validate(evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("order_total", "90.00"),
        ("order_total", "150.00"),
        ("quote_size", "150.00"),
        ("commission_total", "100.00"),
        ("best_ask", "15.00"),
    ],
    ids=(
        "stale-derived-binding",
        "order-total-cap-breach",
        "quote-size-cap-breach",
        "commission-cap-breach",
        "preview-ask-cap-breach",
    ),
)
def test_accepted_readback_recomputes_preview_totals_against_caps(
    tmp_path: Path,
    field: str,
    value: str,
):
    producer, _store, _path = _producer(tmp_path, FakePreviewRestClient())
    evidence = producer.run()
    preview = evidence["preview_response"]
    preview[field] = value
    evidence["preview_response_sha256"] = canonical_sha256(preview)
    authoritative = evidence["seal_ready_plan"]["authoritative_preview"]
    authoritative["preview_response"] = preview
    authoritative["preview_response_sha256"] = evidence[
        "preview_response_sha256"
    ]
    if field == "commission_total":
        authoritative["commission_total"] = value
    evidence["seal_ready_plan_sha256"] = canonical_sha256(
        evidence["seal_ready_plan"]
    )
    evidence["evidence_sha256"] = canonical_sha256(
        {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    )

    with pytest.raises(ValidationError):
        AdminFuturesOrderPreviewResponse.model_validate(evidence)


def test_accepted_readback_rejects_preview_margin_above_available_margin(
    tmp_path: Path,
):
    producer, _store, _path = _producer(tmp_path, FakePreviewRestClient())
    evidence = producer.run()
    preview = evidence["preview_response"]
    preview["order_margin_total"] = "250.01"
    evidence["preview_response_sha256"] = canonical_sha256(preview)
    authoritative = evidence["seal_ready_plan"]["authoritative_preview"]
    authoritative["preview_response"] = preview
    authoritative["preview_response_sha256"] = evidence[
        "preview_response_sha256"
    ]
    authoritative["order_margin_total"] = "250.01"
    evidence["seal_ready_plan_sha256"] = canonical_sha256(
        evidence["seal_ready_plan"]
    )
    evidence["evidence_sha256"] = canonical_sha256(
        {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    )

    with pytest.raises(ValidationError):
        AdminFuturesOrderPreviewResponse.model_validate(evidence)


def test_accepted_readback_rejects_unknown_margin_window_token(
    tmp_path: Path,
):
    producer, _store, _path = _producer(tmp_path, FakePreviewRestClient())
    evidence = producer.run()
    evidence["margin_collateral_evidence"]["current_margin_windows"][0][
        "margin_window_type"
    ] = "MARGIN_WINDOW_TYPE_BOGUS"
    margin_hash = canonical_sha256(evidence["margin_collateral_evidence"])
    evidence["margin_collateral_evidence_sha256"] = margin_hash
    evidence["seal_ready_plan"]["authoritative_preview"][
        "margin_collateral_evidence_sha256"
    ] = margin_hash
    evidence["seal_ready_plan_sha256"] = canonical_sha256(
        evidence["seal_ready_plan"]
    )
    evidence["evidence_sha256"] = canonical_sha256(
        {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    )

    with pytest.raises(ValidationError):
        AdminFuturesOrderPreviewResponse.model_validate(evidence)


def test_attempted_readback_rejects_self_consistent_margin_diagnostic_drift(
    tmp_path: Path,
):
    producer, _store, _path = _producer(tmp_path, FakePreviewRestClient())
    evidence = producer.run()
    evidence["margin_setting_evidence"].update(
        observed_token="INTRADAY_MARGIN_SETTING_UNSPECIFIED",
        allowlist_match=True,
        operationally_resolved=False,
        classification="recognized_string",
    )
    evidence["margin_setting_evidence_sha256"] = canonical_sha256(
        evidence["margin_setting_evidence"]
    )
    evidence["evidence_sha256"] = canonical_sha256(
        {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    )

    with pytest.raises(ValidationError):
        AdminFuturesOrderPreviewResponse.model_validate(evidence)


@pytest.mark.parametrize("outcome", ["accepted", "unknown"])
def test_readback_rejects_self_consistent_predecessor_binding_drift(
    tmp_path: Path,
    outcome: str,
):
    rest_client = FakePreviewRestClient(
        preview_error=TimeoutError("ambiguous") if outcome == "unknown" else None
    )
    producer, store, _path = _producer(tmp_path, rest_client)
    if outcome == "unknown":
        with pytest.raises(FuturesOrderPreviewArtifactError, match="unknown"):
            producer.run()
        evidence = store.read_completed()
    else:
        evidence = producer.run()
    evidence["predecessor_binding"]["file_sha256"] = "0" * 64
    if evidence.get("seal_ready_plan"):
        evidence["seal_ready_plan"]["predecessor_binding"] = evidence[
            "predecessor_binding"
        ]
        evidence["seal_ready_plan_sha256"] = canonical_sha256(
            evidence["seal_ready_plan"]
        )
    evidence["evidence_sha256"] = canonical_sha256(
        {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    )

    with pytest.raises(ValidationError):
        AdminFuturesOrderPreviewResponse.model_validate(evidence)


def test_unknown_readback_requires_exact_attempted_payload_and_preflight_hashes(
    tmp_path: Path,
):
    producer, store, _path = _producer(
        tmp_path,
        FakePreviewRestClient(preview_error=TimeoutError("ambiguous")),
    )
    with pytest.raises(FuturesOrderPreviewArtifactError, match="unknown"):
        producer.run()
    evidence = store.read_completed()
    evidence.pop("preview_request")
    evidence["evidence_sha256"] = canonical_sha256(
        {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    )

    with pytest.raises(ValidationError):
        AdminFuturesOrderPreviewResponse.model_validate(evidence)


def test_blocked_readback_rejects_margin_setting_hash_and_allowlist_claim_drift(
    tmp_path: Path,
):
    rest_client = FakePreviewRestClient()
    snapshot = rest_client.get_futures_margin_collateral_snapshot()
    snapshot["intraday_margin_setting"] = {
        "setting": "INTRADAY_MARGIN_SETTING_UNSPECIFIED",
    }
    rest_client.read_calls.clear()
    rest_client.get_futures_margin_collateral_snapshot = (  # type: ignore[method-assign]
        lambda: snapshot
    )
    producer, store, _path = _producer(tmp_path, rest_client)
    with pytest.raises(FuturesOrderPreviewArtifactError, match="blocked"):
        producer.run()
    evidence = store.read_completed()

    nested_hash_drift = json.loads(json.dumps(evidence))
    nested_hash_drift["margin_setting_evidence"]["unexpected_field_count"] = 1
    nested_hash_drift["evidence_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in nested_hash_drift.items()
            if key != "evidence_sha256"
        }
    )
    with pytest.raises(ValidationError):
        AdminFuturesOrderPreviewResponse.model_validate(nested_hash_drift)

    authority_expansion = json.loads(json.dumps(evidence))
    authority_expansion["margin_setting_evidence"].update(
        allowlist_match=True,
        operationally_resolved=True,
        classification="recognized_string",
    )
    authority_expansion["margin_setting_evidence_sha256"] = canonical_sha256(
        authority_expansion["margin_setting_evidence"]
    )
    authority_expansion["evidence_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in authority_expansion.items()
            if key != "evidence_sha256"
        }
    )
    with pytest.raises(ValidationError):
        AdminFuturesOrderPreviewResponse.model_validate(authority_expansion)

    missing_client = FakePreviewRestClient()
    missing_snapshot = missing_client.get_futures_margin_collateral_snapshot()
    missing_snapshot.pop("intraday_margin_setting")
    missing_client.read_calls.clear()
    missing_client.get_futures_margin_collateral_snapshot = (  # type: ignore[method-assign]
        lambda: missing_snapshot
    )
    missing_producer, missing_store, _path = _producer(
        tmp_path / "missing-container",
        missing_client,
    )
    with pytest.raises(FuturesOrderPreviewArtifactError, match="blocked"):
        missing_producer.run()
    token_form_drift = missing_store.read_completed()
    assert token_form_drift["margin_setting_evidence"]["classification"] == (
        "missing_container"
    )
    token_form_drift["margin_setting_evidence"]["token_form"] = (
        "malformed_string"
    )
    token_form_drift["margin_setting_evidence_sha256"] = canonical_sha256(
        token_form_drift["margin_setting_evidence"]
    )
    token_form_drift["evidence_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in token_form_drift.items()
            if key != "evidence_sha256"
        }
    )
    with pytest.raises(ValidationError):
        AdminFuturesOrderPreviewResponse.model_validate(token_form_drift)


@pytest.mark.parametrize(
    ("field", "hash_field"),
    [
        ("permission_evidence", "permission_evidence_sha256"),
        ("portfolio_catalog_evidence", "portfolio_catalog_sha256"),
        ("position_evidence", "position_evidence_sha256"),
        ("margin_collateral_evidence", "margin_collateral_evidence_sha256"),
    ],
)
def test_zero_preview_blocked_readback_rejects_raw_account_evidence(
    tmp_path: Path,
    field: str,
    hash_field: str,
):
    rest_client = FakePreviewRestClient()
    snapshot = rest_client.get_futures_margin_collateral_snapshot()
    snapshot["intraday_margin_setting"] = {
        "setting": "INTRADAY_MARGIN_SETTING_UNSPECIFIED",
    }
    rest_client.read_calls.clear()
    rest_client.get_futures_margin_collateral_snapshot = (  # type: ignore[method-assign]
        lambda: snapshot
    )
    producer, store, _path = _producer(tmp_path, rest_client)
    with pytest.raises(FuturesOrderPreviewArtifactError, match="blocked"):
        producer.run()
    evidence = store.read_completed()
    raw = {"raw_private_account_payload": "DO_NOT_RETURN"}
    evidence[field] = raw
    evidence[hash_field] = canonical_sha256(raw)
    evidence["evidence_sha256"] = canonical_sha256(
        {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    )

    with pytest.raises(ValidationError):
        AdminFuturesOrderPreviewResponse.model_validate(evidence)


def test_get_route_fails_closed_for_missing_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-token")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_FUTURES_ORDER_PREVIEW_ARTIFACT_PATH",
        str(tmp_path / "missing.jsonl"),
    )
    client = TestClient(create_app())
    response = client.get(
        "/api/v1/futures/order-preview",
        headers={
            "Authorization": "Bearer test-token",
            "X-Admin-Actor": "operator-1",
            "X-Admin-Roles": "viewer",
        },
    )

    assert response.status_code == 503
    assert response.headers["X-Live-Execution-Enabled"] == "false"


def test_get_route_maps_self_consistent_but_cross_unbound_seal_to_safe_503(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    producer, _store, path = _producer(tmp_path, FakePreviewRestClient())
    producer.run()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    evidence = rows[1]["record"]
    evidence["seal_ready_plan"]["authoritative_preview"][
        "commission_total"
    ] = "0.00"
    evidence["seal_ready_plan_sha256"] = canonical_sha256(
        evidence["seal_ready_plan"]
    )
    evidence["evidence_sha256"] = canonical_sha256(
        {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    )
    rows[1]["record_sha256"] = canonical_sha256(
        {key: value for key, value in rows[1].items() if key != "record_sha256"}
    )
    path.chmod(0o600)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-token")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_FUTURES_ORDER_PREVIEW_ARTIFACT_PATH",
        str(path),
    )

    response = TestClient(create_app()).get(
        "/api/v1/futures/order-preview",
        headers={
            "Authorization": "Bearer test-token",
            "X-Admin-Actor": "operator-1",
            "X-Admin-Roles": "viewer",
        },
    )

    assert response.status_code == 503
    assert response.json()["message"] == (
        "Futures Preview evidence is unavailable or invalid"
    )
    assert "commission_total" not in response.text


def test_get_route_exposes_terminal_unknown_without_any_second_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    rest_client = FakePreviewRestClient(preview_error=TimeoutError("ambiguous"))
    producer, _store, path = _producer(tmp_path, rest_client)
    with pytest.raises(FuturesOrderPreviewArtifactError, match="unknown"):
        producer.run()
    preview_calls_before_get = len(rest_client.preview_calls)
    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-token")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_FUTURES_ORDER_PREVIEW_ARTIFACT_PATH",
        str(path),
    )

    response = TestClient(create_app()).get(
        "/api/v1/futures/order-preview",
        headers={
            "Authorization": "Bearer test-token",
            "X-Admin-Actor": "operator-1",
            "X-Admin-Roles": "viewer",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "unknown"
    assert response.json()["outcome"] == "unknown"
    assert response.json()["attempt_counters"]["preview_order"] == 1
    assert len(rest_client.preview_calls) == preview_calls_before_get


def test_producer_tool_path_is_fixed_and_has_no_path_or_scope_override(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_FUTURES_ORDER_PREVIEW_ARTIFACT_PATH",
        "/tmp/redirected-preview.jsonl",
    )

    assert (
        preview_tool.production_artifact_path()
        == FUTURES_PREVIEW_R4_ARTIFACT_PATH
    )
    assert (
        preview_tool.production_artifact_path()
        == DEFAULT_FUTURES_PREVIEW_ARTIFACT_PATH
    )
    parsed = preview_tool.build_parser().parse_args(
        ["--confirm-one-r4-preview"]
    )
    assert parsed.confirm_one_r4_preview is True
    with pytest.raises(SystemExit):
        preview_tool.build_parser().parse_args(
            ["--confirm-one-r4-preview", "--artifact-path", "/tmp/alternate"]
        )
    with pytest.raises(SystemExit):
        preview_tool.build_parser().parse_args(["--confirm-one-preview"])
    with pytest.raises(SystemExit):
        preview_tool.build_parser().parse_args(["--confirm-one-r3-preview"])
    with pytest.raises(SystemExit):
        preview_tool.build_parser().parse_args(["--confirm-one-r5-preview"])


def _install_fixed_preview_sdk_surface(instance: object) -> None:
    for method in (
        "get_api_key_permissions",
        "get_portfolios",
        "get_product",
        "get_best_bid_ask",
        "list_futures_positions",
        "get_futures_balance_summary",
        "get_intraday_margin_setting",
        "get_current_margin_window",
        "list_futures_sweeps",
        "preview_order",
    ):
        setattr(instance, method, lambda *_args, **_kwargs: None)


def test_tool_binds_one_shot_coinbase_client_to_finite_timeout(
    monkeypatch: pytest.MonkeyPatch,
):
    import coinbase.rest as coinbase_rest

    captured: dict[str, object] = {}

    class FakeSdk:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)
            _install_fixed_preview_sdk_surface(self)
            adapter = SimpleNamespace(max_retries=SimpleNamespace(total=0))
            self.session = SimpleNamespace(
                adapters={"https://": adapter, "http://": adapter}
            )
            captured["sdk"] = self

    def hydrate(environment: dict[str, str]) -> SimpleNamespace:
        assert "COINBASE_API_KEY" not in environment
        assert "COINBASE_API_SECRET" not in environment
        assert environment["COINBASE_SECRETS_MANAGER_SECRET_ID"] == "coinbase"
        assert environment["COINBASE_SECRETS_MANAGER_REGION"] == "us-east-1"
        environment["COINBASE_API_KEY"] = "organizations/test/apiKeys/key"
        environment["COINBASE_API_SECRET"] = "test-secret"
        return SimpleNamespace(
            source="secrets_manager",
            secret_id_env="COINBASE_SECRETS_MANAGER_SECRET_ID",
        )

    monkeypatch.setenv("COINBASE_API_KEY", "inherited-test-profile-key")
    monkeypatch.setenv("COINBASE_API_SECRET", "inherited-test-profile-secret")
    monkeypatch.setattr(preview_tool, "ensure_live_coinbase_credentials", hydrate)
    monkeypatch.setattr(coinbase_rest, "RESTClient", FakeSdk)

    client = preview_tool.build_rest_client()

    assert isinstance(client, preview_tool.FuturesPreviewOnlyRestClient)
    assert captured["timeout"] == preview_tool.COINBASE_PREVIEW_HTTP_TIMEOUT_SECONDS
    assert 0 < preview_tool.COINBASE_PREVIEW_HTTP_TIMEOUT_SECONDS <= 30
    assert captured["sdk"].session.max_redirects == 0
    assert not hasattr(client, "get_sdk_client")


def test_preview_only_client_allows_at_most_one_preview_and_no_mutations():
    rest_client = FakePreviewRestClient()
    client = preview_tool.FuturesPreviewOnlyRestClient(rest_client)
    request = {
        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
        "side": "BUY",
        "order_configuration": {
            "limit_limit_gtc": {
                "base_size": "1",
                "limit_price": "6.40",
                "post_only": True,
            }
        },
    }

    assert client.preview_order(**request) == rest_client.preview_response
    with pytest.raises(FuturesOrderPreviewArtifactError, match="already attempted"):
        client.preview_order(**request)

    assert len(rest_client.preview_calls) == 1
    assert rest_client.forbidden_calls == []
    for forbidden_method in (
        "create_order",
        "place_limit_order",
        "limit_order_gtc",
        "cancel_order",
        "cancel_order_by_exchange_order_id",
        "cancel_orders",
        "close_position",
        "reduce_position",
        "get_sdk_client",
    ):
        assert not hasattr(client, forbidden_method)
    assert not hasattr(client, "__dict__")


def test_preview_only_client_surface_and_scope_are_exact():
    rest_client = FakePreviewRestClient()
    client = preview_tool.FuturesPreviewOnlyRestClient(rest_client)
    public_callables = {
        name
        for name in dir(type(client))
        if not name.startswith("_") and callable(getattr(type(client), name))
    }
    assert public_callables == {
        "get_api_key_permissions",
        "list_portfolios",
        "get_product_dict",
        "get_best_bid_ask",
        "get_futures_positions",
        "get_futures_margin_collateral_snapshot",
        "preview_order",
    }

    with pytest.raises(FuturesOrderPreviewArtifactError, match="product scope"):
        client.get_product_dict("BTC-USDC")
    with pytest.raises(FuturesOrderPreviewArtifactError, match="market scope"):
        client.get_best_bid_ask(product_ids=["BTC-USDC"])
    with pytest.raises(FuturesOrderPreviewArtifactError, match="request scope"):
        client.preview_order(
            product_id=FUTURES_PREVIEW_PRODUCT_ID,
            side="SELL",
            order_configuration={
                "limit_limit_gtc": {
                    "base_size": "1",
                    "limit_price": "6.40",
                    "post_only": True,
                }
            },
        )

    assert rest_client.read_calls == []
    assert rest_client.preview_calls == []
    assert rest_client.forbidden_calls == []


def test_preview_only_client_consumes_timeout_without_second_delegate_call():
    rest_client = FakePreviewRestClient(preview_error=TimeoutError("ambiguous"))
    client = preview_tool.FuturesPreviewOnlyRestClient(rest_client)
    request = {
        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
        "side": "BUY",
        "order_configuration": {
            "limit_limit_gtc": {
                "base_size": "1",
                "limit_price": "6.40",
                "post_only": True,
            }
        },
    }

    with pytest.raises(TimeoutError):
        client.preview_order(**request)
    with pytest.raises(FuturesOrderPreviewArtifactError, match="already attempted"):
        client.preview_order(**request)

    assert len(rest_client.preview_calls) == 1
    assert rest_client.forbidden_calls == []


def test_tool_rejects_inherited_or_non_default_credential_resolution(
    monkeypatch: pytest.MonkeyPatch,
):
    import coinbase.rest as coinbase_rest

    def hydrate(environment: dict[str, str]) -> SimpleNamespace:
        environment["COINBASE_API_KEY"] = "organizations/test/apiKeys/key"
        environment["COINBASE_API_SECRET"] = "test-secret"
        return SimpleNamespace(source="environment", secret_id_env=None)

    monkeypatch.setattr(preview_tool, "ensure_live_coinbase_credentials", hydrate)
    monkeypatch.setattr(
        coinbase_rest,
        "RESTClient",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("SDK client must not be constructed")
        ),
    )

    with pytest.raises(FuturesOrderPreviewArtifactError, match="credential source"):
        preview_tool.build_rest_client()


def test_tool_suppresses_secret_bearing_coinbase_sdk_error_logs(
    caplog: pytest.LogCaptureFixture,
):
    import requests
    from coinbase.rest.rest_base import handle_exception

    secret = "PRIVATE_COINBASE_HTTP_RESPONSE_MUST_NOT_BE_LOGGED"
    response = SimpleNamespace(
        status_code=500,
        reason="Internal Server Error",
        text=secret,
    )
    sdk_logger = logging.getLogger("coinbase.RESTClient")
    previously_disabled = sdk_logger.disabled

    with caplog.at_level(logging.ERROR, logger="coinbase.RESTClient"):
        with preview_tool._suppress_coinbase_sdk_logging():
            with pytest.raises(requests.HTTPError):
                handle_exception(response)

    assert secret not in caplog.text
    assert sdk_logger.disabled is previously_disabled


def test_build_rest_client_rejects_nonzero_transport_retries(
    monkeypatch: pytest.MonkeyPatch,
):
    import coinbase.rest as coinbase_rest

    class RetryingSdk:
        def __init__(self, **_kwargs: object) -> None:
            _install_fixed_preview_sdk_surface(self)
            adapter = SimpleNamespace(max_retries=SimpleNamespace(total=1))
            self.session = SimpleNamespace(adapters={"https://": adapter})

    def hydrate(environment: dict[str, str]) -> SimpleNamespace:
        environment["COINBASE_API_KEY"] = "organizations/test/apiKeys/key"
        environment["COINBASE_API_SECRET"] = "test-secret"
        return SimpleNamespace(
            source="secrets_manager",
            secret_id_env="COINBASE_SECRETS_MANAGER_SECRET_ID",
        )

    monkeypatch.setattr(preview_tool, "ensure_live_coinbase_credentials", hydrate)
    monkeypatch.setattr(coinbase_rest, "RESTClient", RetryingSdk)

    with pytest.raises(FuturesOrderPreviewArtifactError, match="retry"):
        preview_tool.build_rest_client()


def test_build_rest_client_blocks_redirect_replay_after_first_response(
    monkeypatch: pytest.MonkeyPatch,
):
    import coinbase.rest as coinbase_rest
    import requests

    class RedirectAdapter(requests.adapters.BaseAdapter):
        max_retries = SimpleNamespace(total=0)

        def __init__(self) -> None:
            self.calls: list[str] = []

        def send(self, request, **_kwargs):
            self.calls.append(request.url)
            response = requests.Response()
            response.status_code = 307
            response.headers["location"] = "https://example.test/replayed"
            response.url = request.url
            response.request = request
            response._content = b""
            return response

        def close(self) -> None:
            return None

    adapter = RedirectAdapter()
    sdk_instances: list[object] = []

    class RedirectingSdk:
        def __init__(self, **_kwargs: object) -> None:
            _install_fixed_preview_sdk_surface(self)
            self.session = requests.Session()
            self.session.mount("https://", adapter)
            self.session.mount("http://", adapter)
            sdk_instances.append(self)

    def hydrate(environment: dict[str, str]) -> SimpleNamespace:
        environment["COINBASE_API_KEY"] = "organizations/test/apiKeys/key"
        environment["COINBASE_API_SECRET"] = "test-secret"
        return SimpleNamespace(
            source="secrets_manager",
            secret_id_env="COINBASE_SECRETS_MANAGER_SECRET_ID",
        )

    monkeypatch.setattr(preview_tool, "ensure_live_coinbase_credentials", hydrate)
    monkeypatch.setattr(coinbase_rest, "RESTClient", RedirectingSdk)

    preview_tool.build_rest_client()

    with pytest.raises(requests.TooManyRedirects):
        sdk_instances[0].session.post("https://example.test/preview")
    assert adapter.calls == ["https://example.test/preview"]


def test_build_rest_client_transport_timeout_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
):
    import coinbase.rest as coinbase_rest
    import requests

    class TimeoutAdapter(requests.adapters.BaseAdapter):
        max_retries = SimpleNamespace(total=0)

        def __init__(self) -> None:
            self.calls: list[str] = []

        def send(self, request, **_kwargs):
            self.calls.append(request.url)
            raise requests.Timeout("ambiguous")

        def close(self) -> None:
            return None

    adapter = TimeoutAdapter()
    sdk_instances: list[object] = []

    class TimingOutSdk:
        def __init__(self, **_kwargs: object) -> None:
            _install_fixed_preview_sdk_surface(self)
            self.session = requests.Session()
            self.session.mount("https://", adapter)
            self.session.mount("http://", adapter)
            sdk_instances.append(self)

    def hydrate(environment: dict[str, str]) -> SimpleNamespace:
        environment["COINBASE_API_KEY"] = "organizations/test/apiKeys/key"
        environment["COINBASE_API_SECRET"] = "test-secret"
        return SimpleNamespace(
            source="secrets_manager",
            secret_id_env="COINBASE_SECRETS_MANAGER_SECRET_ID",
        )

    monkeypatch.setattr(preview_tool, "ensure_live_coinbase_credentials", hydrate)
    monkeypatch.setattr(coinbase_rest, "RESTClient", TimingOutSdk)

    preview_tool.build_rest_client()

    with pytest.raises(requests.Timeout):
        sdk_instances[0].session.post("https://example.test/preview")
    assert adapter.calls == ["https://example.test/preview"]


def test_producer_tool_preflight_creates_no_artifact_or_coinbase_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    path = tmp_path / "fixed-production-preview.jsonl"
    monkeypatch.setattr(preview_tool, "production_artifact_path", lambda: path)
    monkeypatch.setattr(
        preview_tool,
        "validate_production_predecessor",
        lambda: dict(TEST_R3_PREDECESSOR_BINDING),
    )
    monkeypatch.setattr(
        preview_tool,
        "build_rest_client",
        lambda: (_ for _ in ()).throw(AssertionError("Coinbase client constructed")),
    )

    assert preview_tool.main(["--preflight"]) == 0

    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "ready"
    assert summary["artifact_created"] is False
    assert summary["predecessor_binding"] == TEST_R3_PREDECESSOR_BINDING
    assert summary["coinbase_read_ran"] is False
    assert summary["preview_order_attempt_count"] == 0
    assert summary["exchange_submission_attempt_count"] == 0
    assert not path.exists()


@pytest.mark.parametrize("occupied_kind", ["regular", "symlink"])
def test_r4_tool_consumed_path_blocks_before_predecessor_or_client(
    occupied_kind: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    path = tmp_path / "slice2r4.jsonl"
    if occupied_kind == "regular":
        path.write_text("consumed\n", encoding="utf-8")
    else:
        path.symlink_to(tmp_path / "missing-target")
    monkeypatch.setattr(preview_tool, "production_artifact_path", lambda: path)
    monkeypatch.setattr(
        preview_tool,
        "validate_production_predecessor",
        lambda: (_ for _ in ()).throw(
            AssertionError("predecessor checked after consumed-path gate")
        ),
    )
    monkeypatch.setattr(
        preview_tool,
        "build_rest_client",
        lambda: (_ for _ in ()).throw(
            AssertionError("Coinbase client constructed after consumed-path gate")
        ),
    )

    assert preview_tool.main(["--confirm-one-r4-preview"]) == 2

    summary = json.loads(capsys.readouterr().err)
    assert summary["status"] == "blocked"
    assert summary["blocker"] == "futures_preview_attempt_already_consumed"
    assert summary["artifact_created"] is False
    assert summary["coinbase_read_ran"] is False
    assert summary["preview_order_attempt_count"] == 0


def test_r4_tool_redacts_client_preparation_failure_before_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    path = tmp_path / "slice2r4.jsonl"
    private_text = "PRIVATE_CREDENTIAL_RESPONSE_MUST_NOT_PRINT"
    monkeypatch.setattr(preview_tool, "production_artifact_path", lambda: path)
    monkeypatch.setattr(
        preview_tool,
        "validate_production_predecessor",
        lambda: dict(TEST_R3_PREDECESSOR_BINDING),
    )
    monkeypatch.setattr(
        preview_tool,
        "build_rest_client",
        lambda: (_ for _ in ()).throw(RuntimeError(private_text)),
    )

    assert preview_tool.main(["--confirm-one-r4-preview"]) == 2

    captured = capsys.readouterr()
    summary = json.loads(captured.err)
    assert summary["status"] == "blocked"
    assert summary["blocker"] == (
        "futures_preview_client_preparation_blocked:RuntimeError"
    )
    assert summary["artifact_created"] is False
    assert summary["coinbase_read_ran"] is False
    assert summary["preview_order_attempt_count"] == 0
    assert private_text not in captured.err
    assert not path.exists()


def test_r4_tool_confirmation_produces_only_r4_preview_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    path = tmp_path / "slice2r4.jsonl"
    rest_client = FakePreviewRestClient()
    rest_client.preview_response["private_http_response_body"] = (
        "PRIVATE_ACCEPTED_PREVIEW_RESPONSE_MUST_NOT_PERSIST"
    )
    live_book = _book()
    live_book["pricebooks"][0]["time"] = datetime.now(
        timezone.utc
    ).isoformat()

    def get_best_bid_ask(*, product_ids: list[str]) -> dict[str, object]:
        rest_client.read_calls.append("best_bid_ask")
        assert product_ids == [FUTURES_PREVIEW_PRODUCT_ID]
        return live_book

    rest_client.get_best_bid_ask = get_best_bid_ask  # type: ignore[method-assign]
    monkeypatch.setattr(
        preview_tool,
        "production_artifact_path",
        lambda: path,
    )
    monkeypatch.setattr(
        preview_tool,
        "validate_production_predecessor",
        lambda: dict(TEST_R3_PREDECESSOR_BINDING),
    )
    monkeypatch.setattr(
        preview_tool,
        "build_rest_client",
        lambda: preview_tool.FuturesPreviewOnlyRestClient(rest_client),
    )

    assert preview_tool.main(["--confirm-one-r4-preview"]) == 0

    summary = json.loads(capsys.readouterr().out)
    evidence = FuturesOrderPreviewArtifactStore(path).read_completed()
    assert summary["status"] == "accepted"
    assert evidence["artifact_type"] == FUTURES_PREVIEW_R4_ARTIFACT_TYPE
    assert evidence["predecessor_binding"] == TEST_R3_PREDECESSOR_BINDING
    assert evidence["attempt_counters"] == {
        "preview_order": 1,
        "retry": 0,
        "fallback": 0,
        "create_order": 0,
        "cancel_order": 0,
        "close_position": 0,
        "reduce_position": 0,
    }
    assert evidence["exchange_submission_attempt_count"] == 0
    assert evidence["artifacts"] == {
        "execution_marker_created": False,
        "attempt_ledger_created": False,
        "runtime_created": False,
    }
    assert len(rest_client.preview_calls) == 1
    assert rest_client.read_calls == [
        "api_key_permissions",
        "portfolio_catalog",
        "product",
        "best_bid_ask",
        "futures_positions",
        "futures_margin_collateral",
        "preview_order",
    ]
    assert rest_client.preview_calls == [evidence["preview_request"]]
    assert rest_client.forbidden_calls == []
    assert "PRIVATE" not in path.read_text(encoding="utf-8")
    AdminFuturesOrderPreviewResponse.model_validate(evidence)


def test_r4_tool_margin_window_stop_is_typed_sanitized_and_pre_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    path = tmp_path / "slice2r4.jsonl"
    rest_client = FakePreviewRestClient()
    snapshot = rest_client.get_futures_margin_collateral_snapshot()
    snapshot["current_margin_windows"][0]["margin_window"].update(
        margin_window_type="MARGIN_WINDOW_TYPE_PRIVATE_ACCOUNT",
        private_response_body="PRIVATE_HTTP_RESPONSE_BODY",
    )
    rest_client.read_calls.clear()
    live_book = _book()
    live_book["pricebooks"][0]["time"] = datetime.now(
        timezone.utc
    ).isoformat()

    def get_best_bid_ask(*, product_ids: list[str]) -> dict[str, object]:
        rest_client.read_calls.append("best_bid_ask")
        assert product_ids == [FUTURES_PREVIEW_PRODUCT_ID]
        return live_book

    def get_margin_snapshot() -> dict[str, object]:
        rest_client.read_calls.append("futures_margin_collateral")
        return snapshot

    rest_client.get_best_bid_ask = get_best_bid_ask  # type: ignore[method-assign]
    rest_client.get_futures_margin_collateral_snapshot = (  # type: ignore[method-assign]
        get_margin_snapshot
    )
    monkeypatch.setattr(preview_tool, "production_artifact_path", lambda: path)
    monkeypatch.setattr(
        preview_tool,
        "validate_production_predecessor",
        lambda: dict(TEST_R3_PREDECESSOR_BINDING),
    )
    monkeypatch.setattr(
        preview_tool,
        "build_rest_client",
        lambda: preview_tool.FuturesPreviewOnlyRestClient(rest_client),
    )

    assert preview_tool.main(["--confirm-one-r4-preview"]) == 2

    summary = json.loads(capsys.readouterr().err)
    evidence = FuturesOrderPreviewArtifactStore(path).read_completed()
    diagnostic = evidence["margin_windows_evidence"]
    assert summary["status"] == "blocked"
    assert evidence["artifact_type"] == FUTURES_PREVIEW_R4_ARTIFACT_TYPE
    assert evidence["predecessor_binding"] == TEST_R3_PREDECESSOR_BINDING
    assert evidence["margin_setting_evidence"]["allowlist_match"] is True
    assert evidence["margin_setting_evidence"]["operationally_resolved"] is True
    assert evidence["margin_setting_evidence_sha256"] == canonical_sha256(
        evidence["margin_setting_evidence"]
    )
    assert diagnostic["classification"] == (
        "margin_window_type_not_exact_operational_enum_token"
    )
    assert diagnostic["failing_value_type"] == "string"
    assert diagnostic["raw_response_included"] is False
    assert diagnostic["external_exception_text_included"] is False
    assert diagnostic["unknown_identifier_values_included"] is False
    assert evidence["margin_windows_evidence_sha256"] == canonical_sha256(
        diagnostic
    )
    assert evidence["attempt_counters"]["preview_order"] == 0
    assert rest_client.preview_calls == []
    assert "PRIVATE" not in path.read_text(encoding="utf-8")
    AdminFuturesOrderPreviewResponse.model_validate(evidence)


def test_slice2r3_paths_are_fixed_distinct_and_predecessor_matches_sealed_hashes():
    assert FUTURES_PREVIEW_R3_ARTIFACT_PATH.name == (
        "futures_exact_no_live_preview_slice_2r3.jsonl"
    )
    assert FUTURES_PREVIEW_PREDECESSOR_ARTIFACT_PATH.name == (
        "futures_exact_no_live_preview_slice_2r2.jsonl"
    )
    assert (
        FUTURES_PREVIEW_R3_ARTIFACT_PATH
        != FUTURES_PREVIEW_PREDECESSOR_ARTIFACT_PATH
    )
    assert FUTURES_PREVIEW_PREDECESSOR_FILE_SHA256 == (
        "1831b2feaac69b9d3d64377123833831c1b1c1f26c1c0445ed17f334746b4053"
    )
    assert FUTURES_PREVIEW_PREDECESSOR_EVIDENCE_SHA256 == (
        "afebf81c4d95c0abd7635fd700f6618e92191423173df3e2db0f875102b6f1c9"
    )
    assert FUTURES_PREVIEW_PREDECESSOR_DEVICE == 66305
    assert preview_module.FUTURES_PREVIEW_PREDECESSOR_INODE == 42312480
    assert preview_module.FUTURES_PREVIEW_PREDECESSOR_SIZE == 6002
    assert preview_module.FUTURES_PREVIEW_PREDECESSOR_MTIME_NS == (
        1783991637010957407
    )
    assert preview_module.FUTURES_PREVIEW_R1_ARTIFACT_PATH.name == (
        "futures_exact_no_live_preview_slice_2r1.jsonl"
    )


def test_production_r2_chain_is_read_only_and_r2_readback_remains_compatible():
    paths = (
        preview_module.FUTURES_PREVIEW_ORIGINAL_ARTIFACT_PATH,
        preview_module.FUTURES_PREVIEW_R1_ARTIFACT_PATH,
        FUTURES_PREVIEW_PREDECESSOR_ARTIFACT_PATH,
    )
    before = {
        path: (
            path.stat().st_dev,
            path.stat().st_ino,
            path.stat().st_size,
            path.stat().st_mode,
            path.stat().st_mtime_ns,
        )
        for path in paths
    }

    binding = (
        preview_module.validate_production_futures_order_preview_predecessor()
    )
    r2_evidence = FuturesOrderPreviewArtifactStore(
        FUTURES_PREVIEW_PREDECESSOR_ARTIFACT_PATH
    ).read_completed()
    validated = AdminFuturesOrderPreviewResponse.model_validate(r2_evidence)

    assert binding == TEST_PREDECESSOR_BINDING
    assert validated.artifact_type == "futures_exact_no_live_preview_slice_2r2"
    assert validated.status == "blocked"
    assert validated.attempt_counters["preview_order"] == 0
    assert validated.pre_preview_stage_evidence is None
    assert before == {
        path: (
            path.stat().st_dev,
            path.stat().st_ino,
            path.stat().st_size,
            path.stat().st_mode,
            path.stat().st_mtime_ns,
        )
        for path in paths
    }


def test_predecessor_validation_is_read_only_and_binds_terminal_zero_preview(
    tmp_path: Path,
):
    path = tmp_path / "slice2r1.jsonl"
    file_sha256, evidence_sha256 = _terminal_predecessor(path)
    before = path.stat()

    binding = validate_futures_order_preview_predecessor(
        path,
        expected_file_sha256=file_sha256,
        expected_evidence_sha256=evidence_sha256,
        expected_device=before.st_dev,
        expected_inode=before.st_ino,
        expected_size=before.st_size,
        expected_mode=0o400,
        expected_mtime_ns=before.st_mtime_ns,
    )

    after = path.stat()
    assert binding == {
        "artifact_name": "slice2r1.jsonl",
        "file_sha256": file_sha256,
        "evidence_sha256": evidence_sha256,
        "device": str(before.st_dev),
        "inode": str(before.st_ino),
        "size_bytes": before.st_size,
        "mode": "0400",
        "mtime_ns": str(before.st_mtime_ns),
        "status": "blocked",
        "outcome": "blocked",
        "preview_order_attempt_count": 0,
        "exchange_submission_attempt_count": 0,
        "submitted_notional_usdc": "0",
        "executed_notional_usdc": "0",
        "preservation": "immutable_no_modify_delete_or_reuse",
        "original_predecessor_binding": ORIGINAL_SLICE2_BINDING,
    }
    assert (after.st_ino, after.st_size, after.st_mode, after.st_mtime_ns) == (
        before.st_ino,
        before.st_size,
        before.st_mode,
        before.st_mtime_ns,
    )


@pytest.mark.parametrize(
    "mutation",
    ["missing", "mode", "bytes", "accepted", "preview", "reads", "nested"],
)
def test_predecessor_validation_fails_closed_on_any_transition_ambiguity(
    tmp_path: Path,
    mutation: str,
):
    path = tmp_path / "slice2r1.jsonl"
    file_sha256, evidence_sha256 = _terminal_predecessor(path)
    observed = path.stat()
    expected_file_sha256 = file_sha256
    expected_evidence_sha256 = evidence_sha256
    if mutation == "missing":
        path.unlink()
    elif mutation == "mode":
        path.chmod(0o600)
    elif mutation == "bytes":
        path.chmod(0o600)
        path.write_bytes(path.read_bytes() + b"x")
        path.chmod(0o400)
    elif mutation in {"accepted", "preview", "reads", "nested"}:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        evidence = rows[1]["record"]
        if mutation == "accepted":
            evidence["status"] = "accepted"
            evidence["outcome"] = "accepted"
        else:
            if mutation == "preview":
                evidence["attempt_counters"]["preview_order"] = 1
            elif mutation == "reads":
                evidence["read_counters"]["futures_margin_collateral"] = 0
            else:
                evidence["predecessor_binding"]["file_sha256"] = "0" * 64
        evidence["evidence_sha256"] = canonical_sha256(
            {key: value for key, value in evidence.items() if key != "evidence_sha256"}
        )
        rows[1]["outcome"] = evidence["outcome"]
        rows[1]["record_sha256"] = canonical_sha256(
            {key: value for key, value in rows[1].items() if key != "record_sha256"}
        )
        path.chmod(0o600)
        path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        path.chmod(0o400)
        expected_file_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        expected_evidence_sha256 = str(evidence["evidence_sha256"])

    with pytest.raises(FuturesOrderPreviewArtifactError, match="predecessor"):
        validate_futures_order_preview_predecessor(
            path,
            expected_file_sha256=expected_file_sha256,
            expected_evidence_sha256=expected_evidence_sha256,
            expected_inode=observed.st_ino,
            expected_size=(path.stat().st_size if path.exists() else observed.st_size),
            expected_mode=0o400,
            expected_mtime_ns=(path.stat().st_mtime_ns if path.exists() else observed.st_mtime_ns),
        )


def test_producer_revalidates_predecessor_before_claim_or_coinbase_reads(
    tmp_path: Path,
):
    path = tmp_path / "slice2r2.jsonl"
    rest_client = FakePreviewRestClient()
    sealed_binding = {
        "artifact_name": "futures_exact_no_live_preview_slice_2r2.jsonl",
        "file_sha256": "a" * 64,
        "status": "blocked",
    }
    producer = FuturesOrderPreviewProducer(
        rest_client=rest_client,
        store=FuturesOrderPreviewArtifactStore(path),
        predecessor_binding=sealed_binding,
        predecessor_validator=lambda: (_ for _ in ()).throw(
            FuturesOrderPreviewArtifactError(
                "futures Preview predecessor changed"
            )
        ),
        now=lambda: NOW,
        correlation_id_factory=lambda: "8f604e56-0a23-4bda-b244-11ebc0194241",
        idempotency_key_factory=lambda: "2d8327f6-826c-4f73-82a4-822e29f73065",
    )

    with pytest.raises(FuturesOrderPreviewArtifactError, match="predecessor"):
        producer.run()

    assert rest_client.read_calls == []
    assert not path.exists()


def test_producer_terminally_blocks_if_predecessor_changes_after_claim(
    tmp_path: Path,
):
    path = tmp_path / "slice2r2.jsonl"
    rest_client = FakePreviewRestClient()
    sealed_binding = {
        "artifact_name": "futures_exact_no_live_preview_slice_2r2.jsonl",
        "file_sha256": "a" * 64,
        "status": "blocked",
    }
    validations = iter(
        [
            dict(sealed_binding),
            FuturesOrderPreviewArtifactError(
                "futures Preview predecessor changed after claim"
            ),
        ]
    )

    def validate_predecessor() -> dict[str, object]:
        observed = next(validations)
        if isinstance(observed, Exception):
            raise observed
        return observed

    producer = FuturesOrderPreviewProducer(
        rest_client=rest_client,
        store=FuturesOrderPreviewArtifactStore(path),
        predecessor_binding=sealed_binding,
        predecessor_validator=validate_predecessor,
        now=lambda: NOW,
        correlation_id_factory=lambda: "8f604e56-0a23-4bda-b244-11ebc0194241",
        idempotency_key_factory=lambda: "2d8327f6-826c-4f73-82a4-822e29f73065",
    )

    with pytest.raises(FuturesOrderPreviewArtifactError, match="attempt consumed"):
        producer.run()

    evidence = FuturesOrderPreviewArtifactStore(path).read_completed()
    assert evidence["status"] == "blocked"
    assert "predecessor" in evidence["blocker"]
    assert evidence["predecessor_binding"] == sealed_binding
    assert evidence["attempt_counters"]["preview_order"] == 0
    assert evidence["exchange_submission_attempt_count"] == 0
    assert rest_client.read_calls == []
    assert path.stat().st_mode & 0o777 == 0o400


def test_producer_revalidates_predecessor_chain_immediately_before_preview(
    tmp_path: Path,
):
    path = tmp_path / "slice2r2.jsonl"
    rest_client = FakePreviewRestClient()
    validation_count = 0

    def validate_predecessor() -> dict[str, object]:
        nonlocal validation_count
        validation_count += 1
        if validation_count >= 3:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview predecessor changed during preflight"
            )
        return dict(TEST_PREDECESSOR_BINDING)

    producer = FuturesOrderPreviewProducer(
        rest_client=rest_client,
        store=FuturesOrderPreviewArtifactStore(path),
        predecessor_binding=TEST_PREDECESSOR_BINDING,
        predecessor_validator=validate_predecessor,
        now=lambda: NOW,
        correlation_id_factory=lambda: "8f604e56-0a23-4bda-b244-11ebc0194241",
        idempotency_key_factory=lambda: "2d8327f6-826c-4f73-82a4-822e29f73065",
    )

    with pytest.raises(FuturesOrderPreviewArtifactError, match="blocked"):
        producer.run()

    evidence = FuturesOrderPreviewArtifactStore(path).read_completed()
    assert evidence["attempt_counters"]["preview_order"] == 0
    assert rest_client.preview_calls == []
    assert evidence["blocker"] == "preflight_or_preview_stage_blocked"
    assert evidence["pre_preview_stage_evidence"]["stages"][-1] == {
        "stage": "terminal_context_sanitization",
        "status": "blocked",
        "reason_code": (
            "futures_preview_terminal_context_sanitization_unclassified"
        ),
    }
    for raw_context_field in (
        "portfolio_binding",
        "product_evidence",
        "market_evidence",
        "position_evidence",
        "margin_collateral_evidence",
        "candidate",
        "preview_request",
        "preview_response",
    ):
        assert raw_context_field not in evidence
    AdminFuturesOrderPreviewResponse.model_validate(evidence)


def test_producer_claim_binds_revalidated_predecessor(
    tmp_path: Path,
):
    path = tmp_path / "slice2r3.jsonl"
    rest_client = FakePreviewRestClient()
    sealed_binding = {
        "artifact_name": "futures_exact_no_live_preview_slice_2r2.jsonl",
        "file_sha256": "a" * 64,
        "evidence_sha256": "b" * 64,
        "status": "blocked",
        "preview_order_attempt_count": 0,
        "preservation": "immutable_no_modify_delete_or_reuse",
    }
    producer = FuturesOrderPreviewProducer(
        rest_client=rest_client,
        store=FuturesOrderPreviewArtifactStore(path),
        predecessor_binding=sealed_binding,
        predecessor_validator=lambda: dict(sealed_binding),
        now=lambda: NOW,
        correlation_id_factory=lambda: "8f604e56-0a23-4bda-b244-11ebc0194241",
        idempotency_key_factory=lambda: "2d8327f6-826c-4f73-82a4-822e29f73065",
    )

    producer.run()

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["record"]["predecessor_binding"] == sealed_binding
    assert rows[0]["record"]["artifact_type"] == (
        "futures_exact_no_live_preview_slice_2r3"
    )
    assert rows[1]["record"]["predecessor_binding"] == sealed_binding
    assert rows[1]["record"]["seal_ready_plan"]["predecessor_binding"] == (
        sealed_binding
    )


def test_tool_blocks_invalid_predecessor_before_client_or_r4_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    r4_path = tmp_path / "slice2r4.jsonl"
    monkeypatch.setattr(preview_tool, "production_artifact_path", lambda: r4_path)
    monkeypatch.setattr(
        preview_tool,
        "validate_production_predecessor",
        lambda: (_ for _ in ()).throw(
            FuturesOrderPreviewArtifactError("predecessor invalid")
        ),
        raising=False,
    )
    monkeypatch.setattr(
        preview_tool,
        "build_rest_client",
        lambda: (_ for _ in ()).throw(AssertionError("Coinbase client constructed")),
    )

    assert preview_tool.main(["--confirm-one-r4-preview"]) == 2

    summary = json.loads(capsys.readouterr().err)
    assert "predecessor" in summary["blocker"]
    assert not r4_path.exists()


def test_tool_reports_truthful_terminal_unknown_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    r4_path = tmp_path / "slice2r4.jsonl"
    rest_client = FakePreviewRestClient(preview_error=TimeoutError("ambiguous"))
    live_book = _book()
    live_book["pricebooks"][0]["time"] = datetime.now(timezone.utc).isoformat()
    rest_client.get_best_bid_ask = lambda **_kwargs: live_book  # type: ignore[method-assign]
    monkeypatch.setattr(preview_tool, "production_artifact_path", lambda: r4_path)
    monkeypatch.setattr(
        preview_tool,
        "validate_production_predecessor",
        lambda: dict(TEST_R3_PREDECESSOR_BINDING),
    )
    monkeypatch.setattr(
        preview_tool,
        "build_rest_client",
        lambda: preview_tool.FuturesPreviewOnlyRestClient(rest_client),
    )

    assert preview_tool.main(["--confirm-one-r4-preview"]) == 2

    summary = json.loads(capsys.readouterr().err)
    assert summary["status"] == "unknown", summary
    assert summary["outcome"] == "unknown"
    assert summary["attempt_counters"]["preview_order"] == 1
    assert summary["exchange_submission_attempt_count"] == 0
    assert len(rest_client.preview_calls) == 1
    terminal = FuturesOrderPreviewArtifactStore(r4_path).read_completed()
    assert terminal["status"] == "unknown"
    assert terminal["artifact_type"] == FUTURES_PREVIEW_R4_ARTIFACT_TYPE
    assert terminal["predecessor_binding"] == TEST_R3_PREDECESSOR_BINDING


def test_r5_tool_is_a_distinct_fixed_one_use_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_FUTURES_ORDER_PREVIEW_ARTIFACT_PATH",
        "/tmp/redirected-r5-preview.jsonl",
    )

    assert r5_preview_tool.production_artifact_path() == (
        FUTURES_PREVIEW_R5_ARTIFACT_PATH
    )
    assert r5_preview_tool.production_artifact_path() != (
        preview_tool.production_artifact_path()
    )
    parsed = r5_preview_tool.build_parser().parse_args(
        ["--confirm-one-r5-preview"]
    )
    assert parsed.confirm_one_r5_preview is True
    for rejected in (
        ["--confirm-one-r4-preview"],
        ["--confirm-one-preview"],
        ["--confirm-one-r5-preview", "--product-id", "BTC-USDC"],
        ["--confirm-one-r5-preview", "--artifact-path", "/tmp/other"],
    ):
        with pytest.raises(SystemExit):
            r5_preview_tool.build_parser().parse_args(rejected)


def test_r5_tool_preflight_creates_no_artifact_or_coinbase_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    path = tmp_path / "fixed-r5-preview.jsonl"
    monkeypatch.setattr(r5_preview_tool, "production_artifact_path", lambda: path)
    monkeypatch.setattr(
        r5_preview_tool,
        "validate_production_predecessor",
        lambda: dict(TEST_R4_PREDECESSOR_BINDING),
    )
    monkeypatch.setattr(
        r5_preview_tool,
        "build_rest_client",
        lambda: (_ for _ in ()).throw(AssertionError("Coinbase client constructed")),
    )

    assert r5_preview_tool.main(["--preflight"]) == 0

    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "ready"
    assert summary["predecessor_binding"] == TEST_R4_PREDECESSOR_BINDING
    assert summary["artifact_created"] is False
    assert summary["coinbase_read_ran"] is False
    assert not path.exists()


def test_r5_confirmed_predecessor_ambiguity_consumes_terminal_before_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    path = tmp_path / "fixed-r5-preview.jsonl"
    monkeypatch.setattr(r5_preview_tool, "production_artifact_path", lambda: path)
    monkeypatch.setattr(
        r5_preview_tool,
        "validate_production_predecessor",
        lambda: (_ for _ in ()).throw(
            FuturesOrderPreviewArtifactError("predecessor ambiguous")
        ),
    )
    monkeypatch.setattr(
        r5_preview_tool,
        "build_rest_client",
        lambda: (_ for _ in ()).throw(
            AssertionError("Coinbase client constructed before predecessor gate")
        ),
    )

    assert r5_preview_tool.main(["--confirm-one-r5-preview"]) == 2

    summary = json.loads(capsys.readouterr().err)
    evidence = FuturesOrderPreviewArtifactStore(path).read_completed()
    assert summary["status"] == "blocked"
    assert evidence["artifact_type"] == FUTURES_PREVIEW_R5_ARTIFACT_TYPE
    assert evidence["attempt_counters"]["preview_order"] == 0
    assert all(value == 0 for value in evidence["read_counters"].values())
    assert evidence["exchange_submission_attempt_count"] == 0
    assert path.stat().st_mode & 0o777 == 0o400
    AdminFuturesOrderPreviewResponse.model_validate(evidence)


def test_r5_confirmed_client_preparation_error_is_terminally_consumed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    path = tmp_path / "fixed-r5-preview.jsonl"
    private_text = "PRIVATE_CLIENT_PREPARATION_ERROR"
    monkeypatch.setattr(r5_preview_tool, "production_artifact_path", lambda: path)
    monkeypatch.setattr(
        r5_preview_tool,
        "validate_production_predecessor",
        lambda: dict(TEST_R4_PREDECESSOR_BINDING),
    )
    monkeypatch.setattr(
        r5_preview_tool,
        "build_rest_client",
        lambda: (_ for _ in ()).throw(
            FuturesOrderPreviewArtifactError(private_text)
        ),
    )

    assert r5_preview_tool.main(["--confirm-one-r5-preview"]) == 2

    captured = capsys.readouterr()
    summary = json.loads(captured.err)
    evidence = FuturesOrderPreviewArtifactStore(path).read_completed()
    assert summary["status"] == "blocked"
    assert evidence["attempt_counters"]["preview_order"] == 0
    assert evidence["read_counters"]["api_key_permissions"] == 1
    assert all(
        value == 0
        for key, value in evidence["read_counters"].items()
        if key != "api_key_permissions"
    )
    assert evidence["exchange_submission_attempt_count"] == 0
    assert private_text not in captured.err
    assert private_text not in path.read_text(encoding="utf-8")
    assert path.stat().st_mode & 0o777 == 0o400
    AdminFuturesOrderPreviewResponse.model_validate(evidence)


def test_r5_tool_rejects_sdk_portfolio_method_fallback(
    monkeypatch: pytest.MonkeyPatch,
):
    sdk = SimpleNamespace()
    _install_fixed_preview_sdk_surface(sdk)
    adapter = SimpleNamespace(max_retries=SimpleNamespace(total=0))
    sdk.session = SimpleNamespace(
        adapters={"https://": adapter, "http://": adapter},
        max_redirects=0,
    )
    del sdk.get_portfolios
    canonical_delegate = SimpleNamespace(_client=sdk)
    facade = r5_preview_tool.FuturesPreviewOnlyRestClient(canonical_delegate)
    monkeypatch.setattr(
        r5_preview_tool.r4_tool,
        "build_rest_client",
        lambda: facade,
    )

    with pytest.raises(FuturesOrderPreviewArtifactError, match="SDK read surface"):
        r5_preview_tool.build_rest_client()

    sdk.get_portfolios = lambda: None
    assert r5_preview_tool.build_rest_client() is facade
    adapter.max_retries = SimpleNamespace(total=0, read=1)
    with pytest.raises(FuturesOrderPreviewArtifactError, match="retry policy"):
        r5_preview_tool.build_rest_client()


def test_r5_tool_confirmation_produces_only_r5_preview_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    path = tmp_path / "fixed-r5-preview.jsonl"
    rest_client = FakePreviewRestClient()
    snapshot = rest_client.get_futures_margin_collateral_snapshot()
    snapshot["current_margin_windows"][0]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = "MARGIN_WINDOW_TYPE_TRANSITION"
    snapshot["private_margin_payload"] = "PRIVATE_R5_MARGIN_PAYLOAD"
    rest_client.read_calls.clear()
    rest_client.get_futures_margin_collateral_snapshot = (  # type: ignore[method-assign]
        lambda: snapshot
    )
    live_book = _book()
    live_book["pricebooks"][0]["time"] = datetime.now(  # type: ignore[index]
        timezone.utc
    ).isoformat()
    live_book["private_book_payload"] = "PRIVATE_R5_BOOK_PAYLOAD"
    rest_client.get_best_bid_ask = (  # type: ignore[method-assign]
        lambda **_kwargs: live_book
    )
    monkeypatch.setattr(r5_preview_tool, "production_artifact_path", lambda: path)
    monkeypatch.setattr(
        r5_preview_tool,
        "validate_production_predecessor",
        lambda: dict(TEST_R4_PREDECESSOR_BINDING),
    )
    monkeypatch.setattr(
        r5_preview_tool,
        "build_rest_client",
        lambda: r5_preview_tool.FuturesPreviewOnlyRestClient(rest_client),
    )

    assert r5_preview_tool.main(["--confirm-one-r5-preview"]) == 0

    summary = json.loads(capsys.readouterr().out)
    evidence = FuturesOrderPreviewArtifactStore(path).read_completed()
    assert summary["status"] == "accepted"
    assert evidence["artifact_type"] == FUTURES_PREVIEW_R5_ARTIFACT_TYPE
    assert evidence["predecessor_binding"] == TEST_R4_PREDECESSOR_BINDING
    assert evidence["margin_windows_policy_evidence"]["classification"] == "ready"
    assert evidence["attempt_counters"]["preview_order"] == 1
    assert evidence["exchange_submission_attempt_count"] == 0
    assert len(rest_client.preview_calls) == 1
    assert rest_client.forbidden_calls == []
    assert "PRIVATE_R5" not in path.read_text(encoding="utf-8")
    AdminFuturesOrderPreviewResponse.model_validate(evidence)


def test_r6_tool_preflight_is_dormant_and_constructs_no_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    path = tmp_path / "fixed-r6-preview.jsonl"
    monkeypatch.setattr(r6_preview_tool, "production_artifact_path", lambda: path)
    monkeypatch.setattr(
        r6_preview_tool,
        "validate_production_predecessor",
        lambda: dict(preview_module.FUTURES_PREVIEW_R5_TERMINAL_BINDING),
    )
    monkeypatch.setattr(
        r6_preview_tool,
        "build_rest_client",
        lambda: (_ for _ in ()).throw(AssertionError("Coinbase client constructed")),
    )

    assert r6_preview_tool.main(["--preflight"]) == 0

    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "ready"
    assert summary["predecessor_binding"] == (
        preview_module.FUTURES_PREVIEW_R5_TERMINAL_BINDING
    )
    assert summary["artifact_created"] is False
    assert summary["coinbase_read_ran"] is False
    assert not path.exists()


def test_r6_confirmed_predecessor_ambiguity_consumes_before_client_or_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    path = tmp_path / "fixed-r6-preview.jsonl"
    monkeypatch.setattr(r6_preview_tool, "production_artifact_path", lambda: path)
    monkeypatch.setattr(
        r6_preview_tool,
        "validate_production_predecessor",
        lambda: (_ for _ in ()).throw(
            FuturesOrderPreviewArtifactError("predecessor ambiguous")
        ),
    )
    monkeypatch.setattr(
        r6_preview_tool,
        "build_rest_client",
        lambda: (_ for _ in ()).throw(
            AssertionError("Coinbase client constructed before claim")
        ),
    )

    assert r6_preview_tool.main(["--confirm-one-r6-preview"]) == 2

    summary = json.loads(capsys.readouterr().err)
    evidence = FuturesOrderPreviewArtifactStore(path).read_completed()
    assert summary["status"] == "blocked"
    assert evidence["artifact_type"] == (
        preview_module.FUTURES_PREVIEW_R6_ARTIFACT_TYPE
    )
    assert evidence["attempt_counters"]["preview_order"] == 0
    assert all(value == 0 for value in evidence["read_counters"].values())
    assert evidence["exchange_submission_attempt_count"] == 0
    assert path.stat().st_mode & 0o777 == 0o400
    AdminFuturesOrderPreviewResponse.model_validate(evidence)


def test_r6_tool_confirmation_uses_exact_pair_and_only_one_fake_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    path = tmp_path / "fixed-r6-preview.jsonl"
    rest_client = FakePreviewRestClient()
    snapshot = rest_client.get_futures_margin_collateral_snapshot()
    snapshot["current_margin_windows"][0]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = "MARGIN_WINDOW_TYPE_UNSPECIFIED"
    rest_client.read_calls.clear()
    rest_client.get_futures_margin_collateral_snapshot = (  # type: ignore[method-assign]
        lambda: snapshot
    )
    live_book = _book()
    live_book["pricebooks"][0]["time"] = datetime.now(  # type: ignore[index]
        timezone.utc
    ).isoformat()
    rest_client.get_best_bid_ask = lambda **_kwargs: live_book  # type: ignore[method-assign]
    monkeypatch.setattr(r6_preview_tool, "production_artifact_path", lambda: path)
    monkeypatch.setattr(
        r6_preview_tool,
        "validate_production_predecessor",
        lambda: dict(preview_module.FUTURES_PREVIEW_R5_TERMINAL_BINDING),
    )
    monkeypatch.setattr(
        r6_preview_tool,
        "build_rest_client",
        lambda: r6_preview_tool.FuturesPreviewOnlyRestClient(rest_client),
    )

    assert r6_preview_tool.main(["--confirm-one-r6-preview"]) == 0

    summary = json.loads(capsys.readouterr().out)
    evidence = FuturesOrderPreviewArtifactStore(path).read_completed()
    assert summary["status"] == "accepted"
    assert evidence["artifact_type"] == (
        preview_module.FUTURES_PREVIEW_R6_ARTIFACT_TYPE
    )
    assert evidence["predecessor_binding"] == (
        preview_module.FUTURES_PREVIEW_R5_TERMINAL_BINDING
    )
    assert evidence["margin_windows_policy_evidence"]["policy_id"] == (
        "slice2_preview_margin_window_exact_pair_policy_v3"
    )
    assert evidence["attempt_counters"]["preview_order"] == 1
    assert evidence["exchange_submission_attempt_count"] == 0
    assert len(rest_client.preview_calls) == 1
    assert rest_client.forbidden_calls == []
    AdminFuturesOrderPreviewResponse.model_validate(evidence)


def test_openapi_exposes_typed_read_only_preview_contract():
    schema = create_app().openapi()
    operation = schema["paths"]["/api/v1/futures/order-preview"]["get"]

    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AdminFuturesOrderPreviewResponse"
    }
    assert "401" in operation["responses"]
    assert "403" in operation["responses"]
    assert "503" in operation["responses"]
    response_schema = schema["components"]["schemas"][
        "AdminFuturesOrderPreviewResponse"
    ]
    assert set(response_schema["properties"]["artifact_type"]["enum"]) == {
        "futures_exact_no_live_preview_slice_2r2",
        "futures_exact_no_live_preview_slice_2r3",
        "futures_exact_no_live_preview_slice_2r4",
        "futures_exact_no_live_preview_slice_2r5",
        "futures_exact_no_live_preview_slice_2r6",
    }
    assert "margin_windows_policy_evidence" in response_schema["properties"]
    assert "predecessor_binding" in response_schema["required"]
    predecessor_refs = {
        item["$ref"]
        for item in response_schema["properties"]["predecessor_binding"][
            "anyOf"
        ]
    }
    assert predecessor_refs == {
        "#/components/schemas/AdminFuturesPreviewPredecessorBinding",
        "#/components/schemas/AdminFuturesPreviewR2PredecessorBinding",
        "#/components/schemas/AdminFuturesPreviewR3PredecessorBinding",
        "#/components/schemas/AdminFuturesPreviewR4PredecessorBinding",
        "#/components/schemas/AdminFuturesPreviewR5PredecessorBinding",
    }
    predecessor_schema = schema["components"]["schemas"][
        "AdminFuturesPreviewPredecessorBinding"
    ]
    assert predecessor_schema["properties"]["mtime_ns"] == {
        "type": "string",
        "const": "1783980960753782357",
        "title": "Mtime Ns",
    }
    r2_predecessor_schema = schema["components"]["schemas"][
        "AdminFuturesPreviewR2PredecessorBinding"
    ]
    assert r2_predecessor_schema["properties"]["mtime_ns"] == {
        "type": "string",
        "const": "1783991637010957407",
        "title": "Mtime Ns",
    }
    r3_predecessor_schema = schema["components"]["schemas"][
        "AdminFuturesPreviewR3PredecessorBinding"
    ]
    assert r3_predecessor_schema["properties"]["mtime_ns"] == {
        "type": "string",
        "const": "1784054457360155278",
        "title": "Mtime Ns",
    }
    r4_predecessor_schema = schema["components"]["schemas"][
        "AdminFuturesPreviewR4PredecessorBinding"
    ]
    assert r4_predecessor_schema["properties"]["file_sha256"]["const"] == (
        FUTURES_PREVIEW_R4_FILE_SHA256
    )
    assert r4_predecessor_schema["properties"]["evidence_sha256"]["const"] == (
        FUTURES_PREVIEW_R4_EVIDENCE_SHA256
    )
    assert r4_predecessor_schema["properties"]["mtime_ns"] == {
        "type": "string",
        "const": "1784087822854381595",
        "title": "Mtime Ns",
    }
    margin_windows_refs = {
        item["$ref"]
        for item in response_schema["properties"]["margin_windows_evidence"][
            "anyOf"
        ]
        if "$ref" in item
    }
    assert margin_windows_refs == {
        "#/components/schemas/AdminFuturesPreviewMarginWindowsEvidence"
    }
    policy_refs = {
        item["$ref"]
        for item in response_schema["properties"][
            "margin_windows_policy_evidence"
        ]["anyOf"]
        if "$ref" in item
    }
    assert policy_refs == {
        "#/components/schemas/AdminFuturesPreviewMarginWindowsPolicyEvidenceV2",
        "#/components/schemas/AdminFuturesPreviewMarginWindowsPolicyEvidenceV3",
    }
    stage_row_schema = schema["components"]["schemas"][
        "AdminFuturesPreviewStageEvidenceRow"
    ]
    reason_schema = stage_row_schema["properties"]["reason_code"]
    reason_enum = next(
        item["enum"] for item in reason_schema["anyOf"] if "enum" in item
    )
    expected_reason_codes = set().union(
        *preview_module._PRE_PREVIEW_STAGE_ALLOWLISTED_REASONS.values(),
        preview_module._PRE_PREVIEW_STAGE_FALLBACK_REASONS.values(),
    )
    assert set(reason_enum) == expected_reason_codes
