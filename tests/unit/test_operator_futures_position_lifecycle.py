from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from requests.exceptions import HTTPError

from application.admin_api.futures_public_projection import (
    opaque_futures_position_key,
)
from application.admin_api.operator_futures_position_lifecycle import (
    FUTURES_POSITION_ELIGIBILITY_CATEGORIES,
    FuturesPositionRequestContext,
    OperatorFuturesPositionLifecycleService,
    FuturesPositionEligibilityReader,
)
from core.enums import (
    AdminFuturesPositionCallOutcome,
    AdminFuturesPositionEligibilityOutcome,
)


NOW = datetime(2026, 7, 24, 14, 0, tzinfo=timezone.utc)
PORTFOLIO_ID = "11111111-1111-4111-8111-111111111111"
PRODUCT_ID = "AVP-20DEC30-CDE"
POSITION_KEY = opaque_futures_position_key(
    product_id=PRODUCT_ID,
    portfolio_identity="local-runtime-single-profile",
)


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
            "futures_buying_power": {"value": "1000.00", "currency": "USD"},
            "initial_margin": {"value": "40.00", "currency": "USD"},
            "liquidation_threshold": {"value": "80.00", "currency": "USD"},
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
            {"uuid": PORTFOLIO_ID, "name": "Default", "type": "DEFAULT"}
        ]

    def get_futures_positions(self):
        self.calls.append("futures_positions")
        return {
            PRODUCT_ID: SimpleNamespace(
                product_id=PRODUCT_ID,
                number_of_contracts="3",
                side="LONG",
            )
        }

    def get_futures_manual_eligibility_product(self, product_id):
        self.calls.append("product")
        assert product_id == PRODUCT_ID
        return {
            "product_id": PRODUCT_ID,
            "product_type": "FUTURE",
            "trading_disabled": False,
            "view_only": False,
            "cancel_only": False,
            "price_increment": "0.01",
            "base_increment": "1",
            "base_min_size": "1",
            "future_product_details": {"contract_size": "10"},
        }

    def get_best_bid_ask(self, *, product_ids):
        self.calls.append("best_bid_ask")
        assert product_ids == [PRODUCT_ID]
        return {
            "pricebooks": [
                {
                    "product_id": PRODUCT_ID,
                    "bids": [{"price": "6.45", "size": "8"}],
                    "asks": [{"price": "6.47", "size": "9"}],
                    "time": NOW.isoformat(),
                }
            ]
        }

    def get_futures_manual_eligibility_margin_collateral_snapshot(self):
        self.calls.append("futures_margin_collateral")
        return _margin_snapshot()


def test_exact_six_reads_bind_one_authoritative_position_and_bounded_actions():
    rest = _RestClient()
    claims: list[str] = []

    result = FuturesPositionEligibilityReader(
        rest_client=rest,
        position_key=POSITION_KEY,
        now=lambda: NOW,
    ).run(before_category=claims.append)

    assert result.outcome is AdminFuturesPositionEligibilityOutcome.ELIGIBLE
    assert claims == list(FUTURES_POSITION_ELIGIBILITY_CATEGORIES)
    assert rest.calls == list(FUTURES_POSITION_ELIGIBILITY_CATEGORIES)
    assert result.selection == {
        "position_key": POSITION_KEY,
        "product_id": PRODUCT_ID,
        "position_side": "LONG",
        "close_side": "SELL",
        "current_contracts": "3",
        "full_close_size": "3",
        "bounded_reduce_size": "1",
        "best_bid": "6.45",
        "best_ask": "6.47",
        "observed_at": "2026-07-24T14:00:00.000000Z",
    }
    assert len(result.portfolio_id_sha256 or "") == 64
    assert len(result.evidence_sha256 or "") == 64
    assert PORTFOLIO_ID not in repr(result.public_evidence)
    assert result.public_evidence["raw_responses_included"] is False


def test_single_contract_position_allows_full_close_but_not_reduce():
    rest = _RestClient()
    original = rest.get_futures_positions

    def one_contract():
        value = original()
        value[PRODUCT_ID].number_of_contracts = "1"
        return value

    rest.get_futures_positions = one_contract
    result = FuturesPositionEligibilityReader(
        rest_client=rest,
        position_key=POSITION_KEY,
        now=lambda: NOW,
    ).run(before_category=lambda _category: None)

    assert result.outcome is AdminFuturesPositionEligibilityOutcome.ELIGIBLE
    assert result.selection is not None
    assert result.selection["full_close_size"] == "1"
    assert result.selection["bounded_reduce_size"] == ""


def test_position_row_with_conflicting_private_portfolio_fails_closed():
    rest = _RestClient()

    def conflicting_position():
        rest.calls.append("futures_positions")
        return {
            PRODUCT_ID: {
                "product_id": PRODUCT_ID,
                "number_of_contracts": "3",
                "side": "LONG",
                "portfolio_uuid": (
                    "22222222-2222-4222-8222-222222222222"
                ),
            }
        }

    rest.get_futures_positions = conflicting_position
    result = FuturesPositionEligibilityReader(
        rest_client=rest,
        position_key=POSITION_KEY,
        now=lambda: NOW,
    ).run(before_category=lambda _category: None)

    assert result.outcome is AdminFuturesPositionEligibilityOutcome.INELIGIBLE
    assert result.diagnostic_code == (
        "operator_futures_position_selection_ineligible"
    )


def test_position_read_403_is_fixed_value_blind_unknown_boundary():
    rest = _RestClient()

    def forbidden():
        response = SimpleNamespace(status_code=403)
        raise HTTPError("must not be persisted", response=response)

    rest.get_futures_positions = forbidden
    result = FuturesPositionEligibilityReader(
        rest_client=rest,
        position_key=POSITION_KEY,
        now=lambda: NOW,
    ).run(before_category=lambda _category: None)

    assert result.outcome is AdminFuturesPositionEligibilityOutcome.UNKNOWN
    assert result.diagnostic_code == (
        "operator_futures_position_futures_positions_http_forbidden"
    )
    assert "must not be persisted" not in repr(result)


class _Repository:
    def __init__(self, *, mode: str) -> None:
        self.mode = mode
        self.events: list[str] = []
        self.record = SimpleNamespace(diagnostic_code="initial")

    def claim_action(self, *, context, mode):
        self.events.append(f"claim:{mode}")
        return self.record, SimpleNamespace(
            claim_id="claim-1",
            client_order_id="futures-position-close-1",
            mode=mode,
            product_id=PRODUCT_ID,
            position_key=POSITION_KEY,
            action_size=None if mode == "CLOSE_FULL" else "1",
            expected_contracts="3",
            close_side="SELL",
        )

    def mark_action_exchange_invoked(self, *, claim_id):
        self.events.append("invoke:action")

    def finish_action_and_claim_order_reconciliation(self, *, claim_id, execution):
        self.events.append("finish:action")
        return self.record

    def mark_order_reconciliation_invoked(self, *, claim_id):
        self.events.append("invoke:order")

    def finish_order_and_claim_position_reconciliation(self, *, claim_id, execution):
        self.events.append("finish:order")
        return self.record

    def mark_position_reconciliation_invoked(self, *, claim_id):
        self.events.append("invoke:position")

    def finish_position_reconciliation(self, *, claim_id, execution):
        self.events.append("finish:position")
        return self.record

    def finish_position_and_claim_cancel(self, *, claim_id, execution):
        self.events.append("claim:cancel")
        return self.record

    def mark_cancel_exchange_invoked(self, *, claim_id):
        self.events.append("invoke:cancel")

    def finish_cancel(self, *, claim_id, execution):
        self.events.append("finish:cancel")
        return self.record

    def finish_action(self, *, claim_id, execution):
        self.events.append("finish:action-terminal")
        return self.record

    def finish_order_reconciliation(self, *, claim_id, execution):
        self.events.append("finish:order-terminal")
        return self.record

    def is_cancel_invocation_sealed(self):
        return False


class _Executor:
    def __init__(self, *, nonterminal: bool) -> None:
        self.nonterminal = nonterminal
        self.calls: list[tuple[str, object]] = []

    def close_or_reduce(self, *, plan, before_call):
        before_call()
        self.calls.append(("action", plan.mode))
        return SimpleNamespace(
            outcome=AdminFuturesPositionCallOutcome.ACCEPTED,
            private_exchange_order_id="exchange-1",
        )

    def reconcile_order(self, *, plan, private_exchange_order_id, before_call):
        before_call()
        self.calls.append(("order", private_exchange_order_id))
        return SimpleNamespace(
            outcome=AdminFuturesPositionCallOutcome.ACCEPTED,
            authoritatively_nonterminal=self.nonterminal,
        )

    def reconcile_position(self, *, plan, before_call):
        before_call()
        self.calls.append(("position", plan.position_key))
        return SimpleNamespace(
            outcome=AdminFuturesPositionCallOutcome.ACCEPTED,
        )

    def cancel(self, *, plan, private_exchange_order_id, before_call):
        before_call()
        self.calls.append(("cancel", private_exchange_order_id))
        return SimpleNamespace(
            outcome=AdminFuturesPositionCallOutcome.ACCEPTED,
        )


@pytest.mark.parametrize("mode", ["CLOSE_FULL", "REDUCE_ONE_CONTRACT"])
def test_service_uses_one_mutually_exclusive_action_then_two_reads_and_safe_cancel(mode):
    repository = _Repository(mode=mode)
    executor = _Executor(nonterminal=True)
    service = OperatorFuturesPositionLifecycleService(
        repository=repository,
        eligibility_reader_factory=lambda _position_key: None,
        exchange_executor=executor,
    )
    context = FuturesPositionRequestContext(
        actor_id="operator-1",
        roles=("admin", "trader"),
        expected_revision=2,
        idempotency_key="execute-1",
        correlation_id="corr-1",
        audit_id="11111111-1111-4111-8111-111111111111",
        operator_intent="authorize_one_futures_position_close_or_reduce",
        authorize_exact_selected_position_action=True,
        acknowledge_action_is_mutually_exclusive_and_single_use=True,
        acknowledge_unknown_outcome_consumes_allowance=True,
        acknowledge_exact_order_cancel_only=True,
    )

    service.execute(context=context, mode=mode)

    assert executor.calls == [
        ("action", mode),
        ("order", "exchange-1"),
        ("position", POSITION_KEY),
        ("cancel", "exchange-1"),
    ]
    assert repository.events == [
        f"claim:{mode}",
        "invoke:action",
        "finish:action",
        "invoke:order",
        "finish:order",
        "invoke:position",
        "claim:cancel",
        "invoke:cancel",
        "finish:cancel",
    ]


def test_terminal_order_still_reconciles_position_but_never_cancels():
    repository = _Repository(mode="CLOSE_FULL")
    executor = _Executor(nonterminal=False)
    service = OperatorFuturesPositionLifecycleService(
        repository=repository,
        eligibility_reader_factory=lambda _position_key: None,
        exchange_executor=executor,
    )
    context = FuturesPositionRequestContext(
        actor_id="operator-1",
        roles=("admin", "trader"),
        expected_revision=2,
        idempotency_key="execute-1",
        correlation_id="corr-1",
        audit_id="11111111-1111-4111-8111-111111111111",
        operator_intent="authorize_one_futures_position_close_or_reduce",
        authorize_exact_selected_position_action=True,
        acknowledge_action_is_mutually_exclusive_and_single_use=True,
        acknowledge_unknown_outcome_consumes_allowance=True,
        acknowledge_exact_order_cancel_only=True,
    )

    service.execute(context=context, mode="CLOSE_FULL")

    assert [call[0] for call in executor.calls] == [
        "action",
        "order",
        "position",
    ]
    assert "invoke:cancel" not in repository.events
