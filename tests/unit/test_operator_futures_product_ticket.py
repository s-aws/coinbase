from __future__ import annotations

from datetime import datetime, timezone

from application.admin_api.operator_futures_product_ticket import (
    FUTURES_PRODUCT_TICKET_ELIGIBILITY_CATEGORIES,
    FuturesProductPolicySelection,
    FuturesProductTicketEligibilityReader,
    build_futures_product_ticket_candidate,
)
from core.enums import AdminFuturesManualEligibilityOutcome


NOW = datetime(2026, 7, 25, 20, 0, 10, tzinfo=timezone.utc)
PORTFOLIO_ID = "11111111-2222-4333-8444-555555555555"
PRODUCT_ID = "BIP-20DEC30-CDE"
POLICY_SHA256 = "a" * 64


def _product() -> dict[str, object]:
    return {
        "product_id": PRODUCT_ID,
        "display_name": "Bitcoin Perp Futures",
        "product_type": "FUTURE",
        "product_venue": "FCM",
        "status": "",
        "price": "500",
        "price_increment": "1",
        "base_increment": "1",
        "base_min_size": "1",
        "trading_disabled": False,
        "view_only": False,
        "cancel_only": False,
        "fcm_trading_session_details": {
            "is_session_open": True,
            "after_hours_order_entry_disabled": False,
            "session_state": "FCM_TRADING_SESSION_STATE_OPEN",
        },
        "future_product_details": {
            "contract_size": "0.1",
            "contract_code": "BIP",
            "venue": "cde",
            "risk_managed_by": "MANAGED_BY_FCM",
            "contract_expiry": "2030-12-20T16:00:00Z",
            "contract_expiry_type": "EXPIRING",
            "intraday_margin_rate": {
                "long_margin_rate": "0.25",
                "short_margin_rate": "0.30",
            },
            "overnight_margin_rate": {
                "long_margin_rate": "0.50",
                "short_margin_rate": "0.55",
            },
        },
    }


def _book() -> dict[str, object]:
    return {
        "pricebooks": [
            {
                "product_id": PRODUCT_ID,
                "bids": [{"price": "499", "size": "8"}],
                "asks": [{"price": "501", "size": "9"}],
                "time": "2026-07-25T20:00:00Z",
            }
        ]
    }


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


def _selection() -> FuturesProductPolicySelection:
    return FuturesProductPolicySelection(
        product_id=PRODUCT_ID,
        policy_revision=7,
        policy_sha256=POLICY_SHA256,
        lifecycle="ENABLED",
    )


class _RestClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

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

    def get_futures_manual_eligibility_product(self, product_id):
        self.calls.append("product")
        assert product_id == PRODUCT_ID
        return _product()

    def get_best_bid_ask(self, *, product_ids):
        self.calls.append("best_bid_ask")
        assert product_ids == [PRODUCT_ID]
        return _book()

    def get_futures_positions(self):
        self.calls.append("futures_positions")
        return {}

    def get_futures_manual_eligibility_margin_collateral_snapshot(self):
        self.calls.append("futures_margin_collateral")
        return _margin_snapshot()


def test_dynamic_candidate_derives_contract_increment_margin_and_caps() -> None:
    candidate = build_futures_product_ticket_candidate(
        selection=_selection(),
        product=_product(),
        book=_book(),
        positions={},
        available_margin_usdc="250",
        observed_at=NOW,
    )

    assert candidate["product_id"] == PRODUCT_ID
    assert candidate["contract_code"] == "BIP"
    assert candidate["contract_size"] == "0.1"
    assert candidate["price_increment"] == "1"
    assert candidate["limit_price"] == "498"
    assert candidate["opening_reference_notional_usdc"] == "50.10"
    assert candidate["worst_case_margin_rate"] == "0.5"
    assert candidate["required_margin_reference_usdc"] == "25.05"
    assert candidate["product_policy_revision"] == "7"
    assert candidate["product_policy_sha256"] == POLICY_SHA256
    assert candidate["opening_cap_usdc"] == "100"
    assert candidate["exposure_cap_usdc"] == "150"
    assert candidate["turnover_cap_usdc"] == "300"


def test_reader_uses_each_default_profile_category_once_and_sanitizes() -> None:
    rest = _RestClient()
    claims: list[str] = []

    result = FuturesProductTicketEligibilityReader(
        rest_client=rest,
        selection_reader=_selection,
        now=lambda: NOW,
    ).run(before_category=claims.append)

    expected = list(FUTURES_PRODUCT_TICKET_ELIGIBILITY_CATEGORIES)
    assert rest.calls == expected
    assert claims == expected
    assert result.category_attempts == {category: 1 for category in expected}
    assert result.outcome is AdminFuturesManualEligibilityOutcome.ELIGIBLE
    assert result.diagnostic_code == "operator_futures_product_ticket_eligible"
    assert result.candidate is not None
    assert result.candidate["product_id"] == PRODUCT_ID
    assert result.public_evidence["profile_alias"] == "Default"
    assert result.public_evidence["selection_authority"] == (
        "backend_enabled_futures_product_policy"
    )
    assert result.public_evidence["raw_responses_included"] is False
    assert result.public_evidence["private_identifiers_included"] is False
    assert result.public_evidence["exception_text_included"] is False
    assert PORTFOLIO_ID not in repr(result.public_evidence)
    assert "250.00" not in repr(result.public_evidence)


def test_reader_classifies_non_v3_margin_setting_without_exposing_value() -> None:
    class _StandardMarginRestClient(_RestClient):
        def get_futures_manual_eligibility_margin_collateral_snapshot(self):
            self.calls.append("futures_margin_collateral")
            snapshot = _margin_snapshot()
            snapshot["intraday_margin_setting"] = {
                "setting": "INTRADAY_MARGIN_SETTING_STANDARD",
            }
            return snapshot

    result = FuturesProductTicketEligibilityReader(
        rest_client=_StandardMarginRestClient(),
        selection_reader=_selection,
        now=lambda: NOW,
    ).run(before_category=lambda _category: None)

    assert (
        result.diagnostic_code
        == "operator_futures_product_ticket_margin_setting_not_exact_v3"
    )
    assert result.outcome is AdminFuturesManualEligibilityOutcome.INELIGIBLE
    assert "STANDARD" not in repr(result.public_evidence)


def test_reader_classifies_margin_setting_schema_without_exposing_value() -> None:
    class _UnknownMarginSettingRestClient(_RestClient):
        def get_futures_manual_eligibility_margin_collateral_snapshot(self):
            self.calls.append("futures_margin_collateral")
            snapshot = _margin_snapshot()
            snapshot["intraday_margin_setting"] = {
                "setting": "UNRECOGNIZED_PRIVATE_VALUE",
            }
            return snapshot

    result = FuturesProductTicketEligibilityReader(
        rest_client=_UnknownMarginSettingRestClient(),
        selection_reader=_selection,
        now=lambda: NOW,
    ).run(before_category=lambda _category: None)

    assert (
        result.diagnostic_code
        == "operator_futures_product_ticket_margin_setting_schema_ambiguous"
    )
    assert result.outcome is AdminFuturesManualEligibilityOutcome.INELIGIBLE
    assert "UNRECOGNIZED_PRIVATE_VALUE" not in repr(result.public_evidence)


def test_reader_distinguishes_documented_window_from_schema_drift() -> None:
    class _DocumentedNonV3WindowRestClient(_RestClient):
        def get_futures_manual_eligibility_margin_collateral_snapshot(self):
            self.calls.append("futures_margin_collateral")
            snapshot = _margin_snapshot()
            regular = snapshot["current_margin_windows"][0]
            regular["margin_window"]["margin_window_type"] = (
                "MARGIN_WINDOW_TYPE_OVERNIGHT"
            )
            return snapshot

    result = FuturesProductTicketEligibilityReader(
        rest_client=_DocumentedNonV3WindowRestClient(),
        selection_reader=_selection,
        now=lambda: NOW,
    ).run(before_category=lambda _category: None)

    assert (
        result.diagnostic_code
        == (
            "operator_futures_product_ticket_"
            "margin_window_documented_but_v3_ineligible"
        )
    )
    assert result.outcome is AdminFuturesManualEligibilityOutcome.INELIGIBLE
    assert "MARGIN_WINDOW_TYPE_OVERNIGHT" not in repr(result.public_evidence)


def test_reader_fails_closed_before_coinbase_when_selection_is_not_enabled() -> None:
    rest = _RestClient()

    result = FuturesProductTicketEligibilityReader(
        rest_client=rest,
        selection_reader=lambda: FuturesProductPolicySelection(
            product_id=PRODUCT_ID,
            policy_revision=7,
            policy_sha256=POLICY_SHA256,
            lifecycle="DISABLED",
        ),
        now=lambda: NOW,
    ).run(before_category=lambda _category: None)

    assert result.outcome is AdminFuturesManualEligibilityOutcome.INELIGIBLE
    assert result.diagnostic_code == (
        "operator_futures_product_ticket_selection_not_enabled"
    )
    assert result.category_attempts == {
        category: 0
        for category in FUTURES_PRODUCT_TICKET_ELIGIBILITY_CATEGORIES
    }
    assert rest.calls == []


def test_reader_does_not_retry_or_expose_a_product_exception() -> None:
    rest = _RestClient()

    def fail_product(_product_id):
        rest.calls.append("product")
        raise RuntimeError("withheld private Coinbase exception text")

    rest.get_futures_manual_eligibility_product = fail_product

    result = FuturesProductTicketEligibilityReader(
        rest_client=rest,
        selection_reader=_selection,
        now=lambda: NOW,
    ).run(before_category=lambda _category: None)

    assert result.outcome is AdminFuturesManualEligibilityOutcome.UNKNOWN
    assert result.diagnostic_code == (
        "operator_futures_product_ticket_product_read_unknown"
    )
    assert rest.calls == [
        "api_key_permissions",
        "portfolio_catalog",
        "product",
    ]
    assert "withheld" not in repr(result.public_evidence)
