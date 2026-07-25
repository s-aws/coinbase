from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from requests.exceptions import HTTPError

from application.admin_api.operator_futures_manual_lifecycle import (
    FuturesManualEligibilityReader,
)
from core.enums import AdminFuturesManualEligibilityOutcome


NOW = datetime(2026, 7, 13, 12, 0, 10, tzinfo=timezone.utc)
PORTFOLIO_ID = "11111111-1111-4111-8111-111111111111"
PRODUCT_ID = "AVP-20DEC30-CDE"


def _margin_snapshot() -> dict[str, object]:
    return {
        "status": "ready",
        "account_family": "coinbase_futures_us_cfm",
        "source": "backend_rest_client",
        "source_read_attempts": {
            "get_futures_balance_summary": 1,
            "get_intraday_margin_setting": 1,
            "get_current_margin_window": 2,
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
            "setting": "INTRADAY_MARGIN_SETTING_INTRADAY",
        },
        "current_margin_windows": [
            {
                "profile": "MARGIN_PROFILE_TYPE_RETAIL_REGULAR",
                "status": "ready",
                "margin_window": {
                    "margin_window_type": "MARGIN_WINDOW_TYPE_UNSPECIFIED",
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
        "errors": [],
        "intx_applicability": "not_applicable_us_account",
    }


class _RestClient:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.positions: dict[str, object] = {}

    def get_api_key_permissions(self):
        self.calls.append("api_key_permissions")
        return {
            "portfolio_uuid": PORTFOLIO_ID,
            "portfolio_type": "DEFAULT",
            "can_view": True,
            "can_trade": True,
        }

    def get_futures_preview_eligibility_portfolios(self):
        self.calls.append("portfolio_catalog")
        return [
            {
                "uuid": PORTFOLIO_ID,
                "name": "Default",
                "type": "DEFAULT",
            }
        ]

    def get_product_dict(self, product_id):
        self.calls.append("product")
        assert product_id == PRODUCT_ID
        return {
            "product_id": PRODUCT_ID,
            "display_name": "AVAX PERP",
            "product_type": "FUTURE",
            "status": "",
            "price": "6.48",
            "price_increment": "0.01",
            "base_increment": "1",
            "base_min_size": "1",
            "trading_disabled": False,
            "view_only": False,
            "cancel_only": False,
            "future_product_details": {
                "contract_size": "10",
                "contract_code": "AVP",
                "group_description": "Avalanche Perp Futures",
                "group_short_description": "Avalanche Perp",
                "venue": "cde",
                "risk_managed_by": "MANAGED_BY_FCM",
                "contract_expiry": "2030-12-20T16:00:00Z",
                "contract_expiry_type": "EXPIRING",
            },
        }

    def get_futures_manual_eligibility_product(self, product_id):
        return self.get_product_dict(product_id)

    def get_best_bid_ask(self, *, product_ids):
        self.calls.append("best_bid_ask")
        assert product_ids == [PRODUCT_ID]
        return {
            "pricebooks": [
                {
                    "product_id": PRODUCT_ID,
                    "bids": [{"price": "6.46", "size": "8"}],
                    "asks": [{"price": "6.48", "size": "9"}],
                    "time": "2026-07-13T12:00:00Z",
                }
            ]
        }

    def get_futures_positions(self):
        self.calls.append("futures_positions")
        return self.positions

    def get_futures_preview_eligibility_margin_collateral_snapshot(self):
        self.calls.append("futures_margin_collateral")
        return _margin_snapshot()

    def get_futures_manual_eligibility_margin_collateral_snapshot(self):
        return (
            self.get_futures_preview_eligibility_margin_collateral_snapshot()
        )


def test_exact_six_category_reader_builds_one_v3_candidate_without_private_readback():
    rest = _RestClient()
    claims: list[str] = []
    result = FuturesManualEligibilityReader(
        rest_client=rest,
        now=lambda: NOW,
    ).run(before_category=claims.append)

    expected_categories = [
        "api_key_permissions",
        "portfolio_catalog",
        "product",
        "best_bid_ask",
        "futures_positions",
        "futures_margin_collateral",
    ]
    assert result.outcome is AdminFuturesManualEligibilityOutcome.ELIGIBLE
    assert rest.calls == expected_categories
    assert claims == expected_categories
    assert result.category_attempts == {
        category: 1 for category in expected_categories
    }
    assert result.candidate is not None
    assert result.candidate["product_id"] == PRODUCT_ID
    assert result.candidate["side"] == "BUY"
    assert result.candidate["contract_count"] == "1"
    assert result.candidate["limit_price"] == "6.45"
    assert result.candidate["opening_reference_notional_usdc"] == "64.80"
    assert len(result.portfolio_id_sha256 or "") == 64
    assert len(result.evidence_sha256 or "") == 64
    assert PORTFOLIO_ID not in repr(result.public_evidence)
    assert result.public_evidence["profile_alias"] == "Default"
    assert result.public_evidence["exact_v3_eligible"] is True
    assert result.public_evidence["raw_responses_included"] is False


def test_existing_product_exposure_is_ineligible_after_exact_six_reads():
    rest = _RestClient()
    rest.positions = {
        PRODUCT_ID: {
            "product_id": PRODUCT_ID,
            "number_of_contracts": "1",
            "side": "LONG",
        }
    }
    result = FuturesManualEligibilityReader(
        rest_client=rest,
        now=lambda: NOW,
    ).run(before_category=lambda _category: None)

    assert result.outcome is AdminFuturesManualEligibilityOutcome.INELIGIBLE
    assert result.candidate is None
    assert result.diagnostic_code == (
        "operator_futures_manual_existing_exposure_ineligible"
    )
    assert len(rest.calls) == 6


def test_market_observation_time_is_captured_immediately_after_best_bid_ask():
    rest = _RestClient()

    def capture_market_observation_time():
        rest.calls.append("market_observed_at")
        return NOW

    result = FuturesManualEligibilityReader(
        rest_client=rest,
        now=capture_market_observation_time,
    ).run(before_category=lambda _category: None)

    assert result.outcome is AdminFuturesManualEligibilityOutcome.ELIGIBLE
    assert rest.calls == [
        "api_key_permissions",
        "portfolio_catalog",
        "product",
        "best_bid_ask",
        "market_observed_at",
        "futures_positions",
        "futures_margin_collateral",
    ]


def test_read_exception_is_unknown_and_never_retries_or_exposes_text():
    rest = _RestClient()

    def fail_product(_product_id):
        rest.calls.append("product")
        raise RuntimeError("withheld private SDK exception text")

    rest.get_futures_manual_eligibility_product = fail_product
    claims: list[str] = []
    result = FuturesManualEligibilityReader(
        rest_client=rest,
        now=lambda: NOW,
    ).run(before_category=claims.append)

    assert result.outcome is AdminFuturesManualEligibilityOutcome.UNKNOWN
    assert result.diagnostic_code == (
        "operator_futures_manual_product_read_unknown"
    )
    assert rest.calls == [
        "api_key_permissions",
        "portfolio_catalog",
        "product",
    ]
    assert claims == rest.calls
    assert result.category_attempts == {
        "api_key_permissions": 1,
        "portfolio_catalog": 1,
        "product": 1,
        "best_bid_ask": 0,
        "futures_positions": 0,
        "futures_margin_collateral": 0,
    }
    assert "withheld private SDK exception text" not in repr(result)


def test_product_http_status_wins_over_misleading_withheld_message():
    rest = _RestClient()

    def fail_product(_product_id):
        rest.calls.append("product")
        raise HTTPError(
            "misleading 404 not found withheld response text",
            response=SimpleNamespace(status_code=403),
        )

    rest.get_futures_manual_eligibility_product = fail_product
    result = FuturesManualEligibilityReader(
        rest_client=rest,
        now=lambda: NOW,
    ).run(before_category=lambda _category: None)

    assert result.outcome is AdminFuturesManualEligibilityOutcome.UNKNOWN
    assert result.diagnostic_code == (
        "operator_futures_manual_product_http_forbidden"
    )
    assert rest.calls == [
        "api_key_permissions",
        "portfolio_catalog",
        "product",
    ]
    assert "misleading 404 not found withheld response text" not in repr(
        result
    )


def test_positions_http_forbidden_is_fixed_value_blind_and_never_retried():
    rest = _RestClient()

    def fail_positions():
        rest.calls.append("futures_positions")
        raise HTTPError(
            "withheld private HTTP response text",
            response=SimpleNamespace(status_code=403),
        )

    rest.get_futures_positions = fail_positions
    claims: list[str] = []
    result = FuturesManualEligibilityReader(
        rest_client=rest,
        now=lambda: NOW,
    ).run(before_category=claims.append)

    assert result.outcome is AdminFuturesManualEligibilityOutcome.UNKNOWN
    assert result.diagnostic_code == (
        "operator_futures_manual_futures_positions_http_forbidden"
    )
    assert rest.calls == [
        "api_key_permissions",
        "portfolio_catalog",
        "product",
        "best_bid_ask",
        "futures_positions",
    ]
    assert claims == rest.calls
    assert result.category_attempts == {
        "api_key_permissions": 1,
        "portfolio_catalog": 1,
        "product": 1,
        "best_bid_ask": 1,
        "futures_positions": 1,
        "futures_margin_collateral": 0,
    }
    assert "withheld private HTTP response text" not in repr(result)


def test_margin_http_status_wins_over_misleading_withheld_message():
    rest = _RestClient()

    def fail_margin():
        rest.calls.append("futures_margin_collateral")
        raise HTTPError(
            "misleading 404 not found withheld response text",
            response=SimpleNamespace(status_code=403),
        )

    rest.get_futures_manual_eligibility_margin_collateral_snapshot = (
        fail_margin
    )
    result = FuturesManualEligibilityReader(
        rest_client=rest,
        now=lambda: NOW,
    ).run(before_category=lambda _category: None)

    assert result.outcome is AdminFuturesManualEligibilityOutcome.UNKNOWN
    assert result.diagnostic_code == (
        "operator_futures_manual_futures_margin_collateral_http_forbidden"
    )
    assert rest.calls == [
        "api_key_permissions",
        "portfolio_catalog",
        "product",
        "best_bid_ask",
        "futures_positions",
        "futures_margin_collateral",
    ]
    assert "misleading 404 not found withheld response text" not in repr(
        result
    )
