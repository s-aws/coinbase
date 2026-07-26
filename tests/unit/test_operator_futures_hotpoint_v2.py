from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace

import pytest

from application.admin_api.operator_futures_hotpoint_v2 import (
    FUTURES_HOTPOINT_GOAL_ID,
    FUTURES_HOTPOINT_POLICY_REVISION,
    FUTURES_HOTPOINT_POLICY_SHA256,
    FuturesHotpointExactCloseoutExecutor,
    FuturesHotpointEligibilityReader,
    FuturesHotpointReconciliationExecution,
    FuturesHotpointTriggerBinding,
    OperatorFuturesHotpointV2Service,
    validate_futures_hotpoint_candidate_execution_window,
    validate_futures_hotpoint_product_session,
    validate_futures_hotpoint_eligibility_evidence,
)
from application.admin_api.operator_futures_manual_lifecycle import (
    FUTURES_MANUAL_ELIGIBILITY_CATEGORIES,
    FuturesHotpointExternalCommandClaim,
    FuturesHotpointExternalCommandReadback,
    FuturesManualEligibilityResult,
    FuturesManualExecutionPlan,
    FuturesManualGoalRecord,
    FuturesManualLifecycleError,
)
from application.admin_api.operator_futures_product_ticket import (
    FuturesProductPolicySelection,
    build_futures_product_ticket_candidate,
)
from application.admin_api.operator_hotpoint_control import (
    HOTPOINT_RUN_OPERATOR_INTENT,
    HOTPOINT_SAFE_CLOSEOUT_OPERATOR_INTENT,
    HotpointCancelState,
    HotpointCreateState,
    HotpointKillSwitchState,
    HotpointWindowState,
    OperatorHotpointControlRecord,
    OperatorHotpointControlError,
    OperatorHotpointRequestContext,
)
from core.enums import (
    AdminFuturesManualCallOutcome,
    AdminFuturesManualEligibilityOutcome,
)
from core.runtime_controller import (
    INFLIGHT_REST_CANCEL,
    RuntimeController,
)

DEFAULT_PORTFOLIO_ID = "99999999-9999-4999-8999-999999999999"


def _product_session() -> dict[str, object]:
    return {
        "product_id": "AVP-20DEC30-CDE",
        "status": "ONLINE",
        "trading_disabled": False,
        "view_only": False,
        "cancel_only": False,
        "future_product_details": {
            "twenty_four_by_seven": True,
            "contract_expiry": "2030-12-20T00:00:00Z",
        },
        "fcm_trading_session_details": {
            "is_session_open": True,
            "after_hours_order_entry_disabled": False,
            "session_state": "FCM_TRADING_SESSION_STATE_OPEN",
        },
    }


def test_goal13_accepts_only_open_24x7_gtc_compatible_product_session() -> None:
    validate_futures_hotpoint_product_session(_product_session())

    for field, value in (
        ("is_session_open", False),
        ("after_hours_order_entry_disabled", True),
        ("session_state", "FCM_TRADING_SESSION_STATE_MAINTENANCE"),
    ):
        product = _product_session()
        session = product["fcm_trading_session_details"]
        assert isinstance(session, dict)
        session[field] = value
        with pytest.raises(
            ValueError,
            match="operator_futures_hotpoint_session_ineligible",
        ):
            validate_futures_hotpoint_product_session(product)


def test_goal13_rejects_product_level_maintenance_or_cancel_only() -> None:
    for field, value in (
        ("status", "OFFLINE"),
        ("trading_disabled", True),
        ("view_only", True),
        ("cancel_only", True),
    ):
        product = _product_session()
        product[field] = value
        with pytest.raises(
            ValueError,
            match="operator_futures_hotpoint_session_ineligible",
        ):
            validate_futures_hotpoint_product_session(product)

    product = _product_session()
    details = product["future_product_details"]
    assert isinstance(details, dict)
    details["twenty_four_by_seven"] = False
    with pytest.raises(
        ValueError,
        match="operator_futures_hotpoint_session_ineligible",
    ):
        validate_futures_hotpoint_product_session(product)


def test_goal13_does_not_infer_blank_product_status_as_online() -> None:
    product = _product_session()
    product["status"] = ""
    with pytest.raises(
        ValueError,
        match="operator_futures_hotpoint_session_ineligible",
    ):
        validate_futures_hotpoint_product_session(product)


def test_goal13_rejects_current_or_malformed_maintenance_evidence() -> None:
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    product = _product_session()
    session = product["fcm_trading_session_details"]
    assert isinstance(session, dict)
    session["maintenance"] = {
        "start_time": "2026-07-26T11:59:00Z",
        "end_time": "2026-07-26T12:01:00Z",
    }
    with pytest.raises(
        ValueError,
        match="operator_futures_hotpoint_session_ineligible",
    ):
        validate_futures_hotpoint_product_session(product, now=now)

    session["maintenance"] = {
        "start_time": "2026-07-26T12:01:00Z",
    }
    with pytest.raises(
        ValueError,
        match="operator_futures_hotpoint_session_ineligible",
    ):
        validate_futures_hotpoint_product_session(product, now=now)

    session["maintenance"] = {
        "start_time": "2026-07-26T12:02:00Z",
        "end_time": "2026-07-26T12:01:00Z",
    }
    with pytest.raises(
        ValueError,
        match="operator_futures_hotpoint_session_ineligible",
    ):
        validate_futures_hotpoint_product_session(product, now=now)


def test_goal13_rejects_explicit_closed_session_reason() -> None:
    product = _product_session()
    session = product["fcm_trading_session_details"]
    assert isinstance(session, dict)
    session["closed_reason"] = (
        "FCM_TRADING_SESSION_CLOSED_REASON_MAINTENANCE"
    )
    with pytest.raises(
        ValueError,
        match="operator_futures_hotpoint_session_ineligible",
    ):
        validate_futures_hotpoint_product_session(product)


def _eligible_result() -> FuturesManualEligibilityResult:
    parent_id = "11111111-1111-4111-8111-111111111111"
    window_id = "22222222-2222-4222-8222-222222222222"
    trigger_hash = "a" * 64
    candidate = {
        "product_id": "AVP-20DEC30-CDE",
        "side": "BUY",
        "order_type": "LIMIT_GTC",
        "post_only": "true",
        "contract_count": "1",
        "limit_price": "4.99",
        "contract_size": "10",
        "product_price": "5",
        "reference_price": "5.01",
        "reference_price_source": (
            "max_product_price_and_fresh_best_ask"
        ),
        "price_increment": "0.01",
        "best_bid": "5.00",
        "best_ask": "5.01",
        "opening_reference_notional_usdc": "50.10",
        "maximum_exposure_reference_notional_usdc": "50.10",
        "buffered_close_reference_notional_usdc": "60.120",
        "branch_turnover_reference_notional_usdc": "110.220",
        "opening_cap_usdc": "100",
        "exposure_cap_usdc": "150",
        "turnover_cap_usdc": "300",
        "close_buffer_multiplier": "1.20",
        "product_policy_revision": str(FUTURES_HOTPOINT_POLICY_REVISION),
        "product_policy_sha256": FUTURES_HOTPOINT_POLICY_SHA256,
        "hotpoint_parent_client_order_id": parent_id,
        "hotpoint_window_id": window_id,
        "hotpoint_trigger_evidence_sha256": trigger_hash,
        "hotpoint_session_compatibility": "OPEN_24X7_GTC",
        "contract_expiry": "2030-12-20T00:00:00+00:00",
        "session_state": "FCM_TRADING_SESSION_STATE_OPEN",
        "session_is_open": "true",
        "after_hours_order_entry_disabled": "false",
        "session_closed_reason": "",
        "twenty_four_by_seven": "true",
        "maintenance_start": "",
        "maintenance_end": "",
        "session_observed_at": "2026-07-26T12:00:00Z",
        "observed_at": "2026-07-26T12:00:00Z",
    }
    attempts = {
        category: 1 for category in FUTURES_MANUAL_ELIGIBILITY_CATEGORIES
    }
    portfolio_hash = "b" * 64
    public = {
        "goal_id": FUTURES_HOTPOINT_GOAL_ID,
        "profile_alias": "Default",
        "portfolio_type": "DEFAULT",
        "portfolio_id_sha256": portfolio_hash,
        "credential_can_view": True,
        "credential_can_trade": True,
        "selection_authority": "backend_futures_hotpoint_v2_policy",
        "product_id": "AVP-20DEC30-CDE",
        "contract_count": "1",
        "caps": {
            "opening_usdc": "100",
            "exposure_usdc": "150",
            "turnover_usdc": "300",
            "comparison": "strictly_less_than",
        },
        "candidate": candidate,
        "parent_client_order_id_sha256": hashlib.sha256(
            parent_id.encode("utf-8")
        ).hexdigest(),
        "window_id_sha256": hashlib.sha256(
            window_id.encode("utf-8")
        ).hexdigest(),
        "trigger_evidence_sha256": trigger_hash,
        "exact_v3_eligible": True,
        "diagnostic_code": "operator_futures_hotpoint_exact_v3_eligible",
        "category_attempts": attempts,
        "margin_subread_attempts": {
            "futures_balance_summary": 1,
            "intraday_margin_setting": 1,
            "current_margin_window_regular": 1,
            "current_margin_window_intraday": 1,
        },
        "raw_responses_included": False,
        "private_identifiers_included": False,
        "exception_text_included": False,
    }
    encoded = json.dumps(
        public,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return FuturesManualEligibilityResult(
        outcome=AdminFuturesManualEligibilityOutcome.ELIGIBLE,
        diagnostic_code="operator_futures_hotpoint_exact_v3_eligible",
        category_attempts=attempts,
        candidate=candidate,
        portfolio_id_sha256=portfolio_hash,
        evidence_sha256=hashlib.sha256(encoded).hexdigest(),
        public_evidence=public,
    )


def test_goal13_binds_documented_market_time_not_local_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import application.admin_api.operator_futures_hotpoint_v2 as module

    market_time = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    local_receipt = market_time + timedelta(seconds=29)

    class _Rest:
        def get_futures_manual_eligibility_product(self, product_id):
            assert product_id == "AVP-20DEC30-CDE"
            return _product_session()

        def get_best_bid_ask(self, *, product_ids):
            assert product_ids == ["AVP-20DEC30-CDE"]
            return {
                "pricebooks": [
                    {
                        "product_id": "AVP-20DEC30-CDE",
                        "time": market_time.isoformat(),
                    }
                ]
            }

    class _SharedReader:
        def __init__(self, *, rest_client, selection_reader, now):
            del selection_reader
            self.rest_client = rest_client
            self.now = now

        def run(self, *, before_category, before_margin_subread):
            del before_category
            self.rest_client.get_futures_manual_eligibility_product(
                "AVP-20DEC30-CDE"
            )
            self.rest_client.get_best_bid_ask(
                product_ids=["AVP-20DEC30-CDE"]
            )
            for subread in (
                "futures_balance_summary",
                "intraday_margin_setting",
                "current_margin_window_regular",
                "current_margin_window_intraday",
            ):
                before_margin_subread(subread)
            base = _eligible_result()
            return replace(
                base,
                candidate={
                    **(base.candidate or {}),
                    "observed_at": self.now().isoformat(),
                },
            )

    monkeypatch.setattr(
        module,
        "FuturesProductTicketEligibilityReader",
        _SharedReader,
    )
    result = FuturesHotpointEligibilityReader(
        rest_client=_Rest(),
        trigger=FuturesHotpointTriggerBinding(
            parent_client_order_id=(
                "11111111-1111-4111-8111-111111111111"
            ),
            window_id="22222222-2222-4222-8222-222222222222",
            trigger_evidence_sha256="a" * 64,
        ),
        now=lambda: local_receipt,
    ).run(
        before_category=lambda _category: None,
        before_margin_subread=lambda _subread: None,
    )

    assert result.candidate is not None
    assert result.candidate["observed_at"] == market_time.isoformat()
    assert result.candidate["session_observed_at"] == (
        local_receipt.isoformat()
    )
    validate_futures_hotpoint_candidate_execution_window(
        result.candidate,
        now=market_time + timedelta(seconds=30),
    )
    with pytest.raises(
        ValueError,
        match=(
            "operator_futures_hotpoint_candidate_"
            "execution_window_invalid"
        ),
    ):
        validate_futures_hotpoint_candidate_execution_window(
            result.candidate,
            now=market_time + timedelta(seconds=31),
        )


@pytest.mark.parametrize(
    ("candidate_update", "now"),
    (
        (
            {
                "maintenance_start": "2026-07-26T12:00:20Z",
                "maintenance_end": "2026-07-26T12:01:20Z",
            },
            datetime(2026, 7, 26, 12, 0, 20, tzinfo=timezone.utc),
        ),
        (
            {"contract_expiry": "2026-07-26T12:00:20Z"},
            datetime(2026, 7, 26, 12, 0, 20, tzinfo=timezone.utc),
        ),
        (
            {"session_observed_at": "2026-07-26T11:59:29Z"},
            datetime(2026, 7, 26, 12, 0, 0, tzinfo=timezone.utc),
        ),
    ),
)
def test_goal13_execution_window_rejects_crossed_session_boundaries(
    candidate_update,
    now,
) -> None:
    candidate = {
        **(_eligible_result().candidate or {}),
        **candidate_update,
    }

    with pytest.raises(
        ValueError,
        match=(
            "operator_futures_hotpoint_candidate_"
            "execution_window_invalid"
        ),
    ):
        validate_futures_hotpoint_candidate_execution_window(
            candidate,
            now=now,
        )


def test_goal13_eligible_evidence_binds_policy_trigger_and_privacy() -> None:
    result = _eligible_result()
    validate_futures_hotpoint_eligibility_evidence(result)

    tampered = FuturesManualEligibilityResult(
        outcome=result.outcome,
        diagnostic_code=result.diagnostic_code,
        category_attempts=result.category_attempts,
        candidate={
            **(result.candidate or {}),
            "hotpoint_window_id": (
                "33333333-3333-4333-8333-333333333333"
            ),
        },
        portfolio_id_sha256=result.portfolio_id_sha256,
        evidence_sha256=result.evidence_sha256,
        public_evidence=result.public_evidence,
    )
    with pytest.raises(
        ValueError,
        match="operator_futures_hotpoint_eligible_evidence_invalid",
    ):
        validate_futures_hotpoint_eligibility_evidence(tampered)


class _OrderCatalogClient:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def list_orders(self, **kwargs):
        callback = kwargs.pop("before_sdk_call")
        callback()
        self.calls.append(kwargs)
        return self.response


def _exact_order_page(
    *,
    has_next: bool = False,
    cursor: str = "",
    status: str = "OPEN",
) -> dict[str, object]:
    return {
        "orders": [
            {
                "order_id": "private-exchange-order-id",
                "client_order_id": "operator-futures-hotpoint-child",
                "product_id": "AVP-20DEC30-CDE",
                "side": "BUY",
                "status": status,
                "order_type": "LIMIT",
                "time_in_force": "GOOD_UNTIL_CANCELLED",
                "order_configuration": {
                    "limit_limit_gtc": {
                        "base_size": "1",
                        "limit_price": "4.99",
                        "post_only": True,
                    }
                },
                "created_time": "2026-07-26T12:00:01Z",
            }
        ],
        "has_next": has_next,
        "cursor": "next-private-cursor" if has_next else cursor,
    }


def test_goal13_closeout_resolves_one_exact_complete_order_page() -> None:
    client = _OrderCatalogClient(_exact_order_page())
    executor = FuturesHotpointExactCloseoutExecutor(
        rest_client=client,
        configured_portfolio_id=DEFAULT_PORTFOLIO_ID,
    )
    boundaries: list[str] = []

    result = executor.reconcile(
        candidate=_eligible_result().candidate or {},
        client_order_id="operator-futures-hotpoint-child",
        expected_exchange_order_id_sha256=hashlib.sha256(
            b"private-exchange-order-id"
        ).hexdigest(),
        reconciliation_catalog_end_at="2026-07-26T12:00:05Z",
        before_call=lambda: boundaries.append("list_orders"),
    )

    assert result.outcome is AdminFuturesManualCallOutcome.ACCEPTED
    assert result.order_status == "OPEN"
    assert result.authoritatively_nonterminal is True
    assert result.private_exchange_order_id == "private-exchange-order-id"
    assert boundaries == ["list_orders"]
    assert len(client.calls) == 1
    assert client.calls[0]["product_ids"] == ["AVP-20DEC30-CDE"]
    assert client.calls[0]["cursor"] is None
    assert client.calls[0]["limit"] == 100
    assert client.calls[0]["end_date"] == "2026-07-26T12:00:05Z"
    assert client.calls[0]["order_side"] == "BUY"
    assert client.calls[0]["order_types"] == "LIMIT"
    assert (
        client.calls[0]["time_in_forces"]
        == "GOOD_UNTIL_CANCELLED"
    )
    assert "retail_portfolio_id" not in client.calls[0]


def test_goal13_cancel_queued_reconciliation_is_read_only() -> None:
    client = _OrderCatalogClient(
        _exact_order_page(status="CANCEL_QUEUED")
    )
    executor = FuturesHotpointExactCloseoutExecutor(
        rest_client=client,
        configured_portfolio_id=DEFAULT_PORTFOLIO_ID,
    )
    boundaries: list[str] = []

    result = executor.reconcile(
        candidate=_eligible_result().candidate or {},
        client_order_id="operator-futures-hotpoint-child",
        expected_exchange_order_id_sha256=hashlib.sha256(
            b"private-exchange-order-id"
        ).hexdigest(),
        reconciliation_catalog_end_at="2026-07-26T12:00:05Z",
        before_call=lambda: boundaries.append("list_orders"),
    )

    assert result.outcome is AdminFuturesManualCallOutcome.ACCEPTED
    assert result.order_status == "CANCEL_QUEUED"
    assert result.authoritatively_nonterminal is True
    assert boundaries == ["list_orders"]
    assert len(client.calls) == 1


def test_goal13_closeout_fails_closed_on_pagination() -> None:
    client = _OrderCatalogClient(_exact_order_page(has_next=True))
    executor = FuturesHotpointExactCloseoutExecutor(
        rest_client=client,
        configured_portfolio_id=DEFAULT_PORTFOLIO_ID,
    )
    result = executor.reconcile(
        candidate=_eligible_result().candidate or {},
        client_order_id="operator-futures-hotpoint-child",
        expected_exchange_order_id_sha256=None,
        reconciliation_catalog_end_at="2026-07-26T12:00:05Z",
        before_call=lambda: None,
    )

    assert result.outcome is AdminFuturesManualCallOutcome.UNKNOWN
    assert result.private_exchange_order_id is None
    assert len(client.calls) == 1


def test_goal13_closeout_accepts_final_page_cursor_without_following_it() -> None:
    client = _OrderCatalogClient(
        _exact_order_page(cursor="opaque-final-page-cursor")
    )
    executor = FuturesHotpointExactCloseoutExecutor(
        rest_client=client,
        configured_portfolio_id=DEFAULT_PORTFOLIO_ID,
    )
    result = executor.reconcile(
        candidate=_eligible_result().candidate or {},
        client_order_id="operator-futures-hotpoint-child",
        expected_exchange_order_id_sha256=None,
        reconciliation_catalog_end_at="2026-07-26T12:00:05Z",
        before_call=lambda: None,
    )

    assert result.outcome is AdminFuturesManualCallOutcome.ACCEPTED
    assert len(client.calls) == 1


def _control_record() -> OperatorHotpointControlRecord:
    return OperatorHotpointControlRecord(
        goal_id=FUTURES_HOTPOINT_GOAL_ID,
        revision=2,
        kill_switch_state=HotpointKillSwitchState.ENABLED,
        window_state=HotpointWindowState.ARMED,
        parent_client_order_id="11111111-1111-4111-8111-111111111111",
        product_id="AVP-20DEC30-CDE",
        side="BUY",
        window_id="22222222-2222-4222-8222-222222222222",
        window_started_at="2026-07-26T12:00:00+00:00",
        window_expires_at="2026-07-26T12:01:00+00:00",
        create_state=HotpointCreateState.NOT_CLAIMED,
        cancel_state=HotpointCancelState.NOT_CLAIMED,
        create_exchange_invoked=None,
        cancel_exchange_invoked=None,
        placement_claim_id=None,
        cancel_claim_id=None,
        child_client_order_id=None,
        diagnostic_code="operator_futures_hotpoint_window_armed",
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="corr-1",
        audit_id="55555555-5555-4555-8555-555555555555",
        recorded_at="2026-07-26T12:00:00+00:00",
        updated_at="2026-07-26T12:00:00+00:00",
    )


def _lifecycle_record() -> FuturesManualGoalRecord:
    return FuturesManualGoalRecord(
        goal_id=FUTURES_HOTPOINT_GOAL_ID,
        revision=0,
        cycles_used=0,
        active_cycle_number=None,
        eligibility_outcome=None,
        eligibility_diagnostic_code=(
            "operator_futures_manual_not_refreshed"
        ),
        category_attempts={
            category: 0 for category in FUTURES_MANUAL_ELIGIBILITY_CATEGORIES
        },
        candidate=None,
        candidate_sha256=None,
        portfolio_id_sha256=None,
        eligibility_evidence_sha256=None,
        client_order_id=None,
        preview_outcome=AdminFuturesManualCallOutcome.NOT_RUN,
        preview_exchange_invoked=None,
        preview_id_sha256=None,
        create_outcome=AdminFuturesManualCallOutcome.NOT_RUN,
        create_exchange_invoked=None,
        exchange_order_id_sha256=None,
        reconciliation_outcome=AdminFuturesManualCallOutcome.NOT_RUN,
        reconciliation_exchange_invoked=None,
        order_status=None,
        authoritatively_nonterminal=None,
        cancel_outcome=AdminFuturesManualCallOutcome.NOT_RUN,
        cancel_exchange_invoked=None,
        diagnostic_code="operator_futures_manual_not_refreshed",
        correlation_id=None,
        audit_id=None,
        updated_at="2026-07-26T12:00:00+00:00",
    )


class _ControlRepository:
    def __init__(self) -> None:
        self.record = _control_record()
        self.closed = 0
        self.trigger_owner: str | None = None

    def claim_futures_trigger(self, **kwargs):
        if (
            self.trigger_owner is not None
            and self.trigger_owner != kwargs["idempotency_key"]
        ):
            raise ValueError(
                "operator_futures_hotpoint_trigger_owner_active"
            )
        assert kwargs["expected_revision"] == self.record.revision
        self.trigger_owner = kwargs["idempotency_key"]
        self.record = replace(
            self.record,
            revision=self.record.revision + 1,
            diagnostic_code="operator_futures_hotpoint_trigger_claimed",
            actor_id=kwargs["actor_id"],
            roles=tuple(kwargs["roles"]),
            correlation_id=kwargs["correlation_id"],
            audit_id=kwargs["audit_id"],
        )
        return self.record, FuturesHotpointTriggerBinding(
            parent_client_order_id=self.record.parent_client_order_id or "",
            window_id=self.record.window_id or "",
            trigger_evidence_sha256="a" * 64,
        )

    def revalidate_futures_trigger(self, _binding) -> bool:
        return True

    def read_futures_trigger_readback(self):
        return {
            "trigger_fill_count": 3,
            "trigger_evidence_sha256": "a" * 64,
            "window_id_sha256": hashlib.sha256(
                (self.record.window_id or "").encode("utf-8")
            ).hexdigest(),
        }

    def close_futures_control_after_attempt(self):
        self.closed += 1
        self.record = replace(
            self.record,
            revision=self.record.revision + 1,
            kill_switch_state=HotpointKillSwitchState.DISABLED,
            window_state=HotpointWindowState.TERMINAL,
            diagnostic_code="operator_futures_hotpoint_attempt_closed",
        )
        return self.record


class _ControlService:
    def __init__(self, repository: _ControlRepository) -> None:
        self.repository = repository

    def read(self):
        return self.repository.record

    def list_eligible_parents(self, *, limit, offset):
        del limit, offset
        return [], 0


class _LifecycleRepository:
    def __init__(self) -> None:
        self.record = _lifecycle_record()
        self.claim_id = "33333333-3333-4333-8333-333333333333"
        self.external_commands: dict[str, dict[str, object]] = {}
        self.fail_finish_step: str | None = None
        self.preview_invocation_validator = None
        self.create_invocation_validator = None
        self.cancel_invocation_error: str | None = None
        self.cancel_conflict_releases = 0
        self.cancel_invocation_sealed = False
        self.seal_cancel_on_mark = False

    def read(self):
        return self.record

    def is_cancel_invocation_sealed(self):
        return self.cancel_invocation_sealed

    def recover_hotpoint_external_commands(self) -> None:
        for command in self.external_commands.values():
            if command["result"] is None:
                command["result"] = FuturesHotpointExternalCommandClaim(
                    command_id=str(command["command_id"]),
                    status="UNKNOWN",
                    error_code=(
                        "operator_futures_hotpoint_command_outcome_unknown"
                    ),
                    http_status_code=503,
                )

    def read_latest_hotpoint_external_command(self):
        if not self.external_commands:
            return None
        command = tuple(self.external_commands.values())[-1]
        result = command["result"]
        status = (
            str(result.status) if result is not None else "IN_PROGRESS"
        )
        return FuturesHotpointExternalCommandReadback(
            action=str(command["action"]),
            status=status,
            correlation_id=str(command["correlation_id"]),
            request_revision=int(command["request_revision"]),
            diagnostic_code=(
                "operator_futures_hotpoint_command_succeeded"
                if status == "SUCCESS"
                else str(result.error_code)
                if result is not None
                else "operator_futures_hotpoint_command_in_progress"
            ),
        )

    def claim_hotpoint_external_command(
        self,
        *,
        action,
        context,
        request_payload,
    ):
        digest = json.dumps(
            {
                "action": action,
                "actor": context.actor_id,
                "roles": sorted(context.roles),
                "correlation": context.correlation_id,
                "audit": context.audit_id,
                "request": request_payload,
            },
            sort_keys=True,
        )
        existing = self.external_commands.get(context.idempotency_key)
        if existing is not None:
            if existing["digest"] != digest:
                raise FuturesManualLifecycleError(
                    "operator_futures_hotpoint_idempotency_conflict"
                )
            result = existing["result"]
            if result is None:
                return FuturesHotpointExternalCommandClaim(
                    command_id=str(existing["command_id"]),
                    status="IN_PROGRESS",
                )
            return result
        command_id = f"command-{len(self.external_commands) + 1}"
        self.external_commands[context.idempotency_key] = {
            "command_id": command_id,
            "digest": digest,
            "action": action,
            "correlation_id": context.correlation_id,
            "request_revision": context.expected_revision,
            "result": None,
        }
        return FuturesHotpointExternalCommandClaim(
            command_id=command_id,
            status="NEW",
        )

    def finish_hotpoint_external_command(
        self,
        *,
        command_id,
        outcome,
        result_snapshot,
        error_code,
        http_status_code,
    ) -> None:
        command = next(
            value
            for value in self.external_commands.values()
            if value["command_id"] == command_id
        )
        result = FuturesHotpointExternalCommandClaim(
            command_id=command_id,
            status=outcome,
            result_snapshot=(
                dict(result_snapshot)
                if result_snapshot is not None
                else None
            ),
            error_code=error_code,
            http_status_code=http_status_code,
        )
        if command["result"] is not None:
            assert command["result"] == result
        command["result"] = result

    def begin_eligibility_cycle(self, *, context):
        self.record = replace(
            self.record,
            revision=self.record.revision + 1,
            cycles_used=1,
            active_cycle_number=1,
        )
        return self.record, 1

    def claim_eligibility_category(self, *, cycle_number, category):
        assert cycle_number == 1
        attempts = dict(self.record.category_attempts)
        attempts[category] = 1
        self.record = replace(self.record, category_attempts=attempts)

    def claim_margin_subread(self, *, cycle_number, subread):
        assert cycle_number == 1
        attempts = dict(self.record.margin_subread_attempts)
        assert attempts[subread] == 0
        attempts[subread] = 1
        self.record = replace(
            self.record,
            margin_subread_attempts=attempts,
        )

    def finish_eligibility_cycle(self, *, cycle_number, result, context):
        del cycle_number
        self.record = replace(
            self.record,
            revision=self.record.revision + 1,
            active_cycle_number=None,
            eligibility_outcome=result.outcome,
            eligibility_diagnostic_code=result.diagnostic_code,
            candidate=result.candidate,
            candidate_sha256="b" * 64,
            portfolio_id_sha256=result.portfolio_id_sha256,
            eligibility_evidence_sha256=result.evidence_sha256,
            diagnostic_code=result.diagnostic_code,
            correlation_id=context.correlation_id,
            audit_id=context.audit_id,
        )
        return self.record

    def claim_preview(self, *, context):
        child = "operator-futures-hotpoint-v2-child"
        self.record = replace(
            self.record,
            revision=self.record.revision + 1,
            execution_claim_id=self.claim_id,
            client_order_id=child,
            preview_outcome=AdminFuturesManualCallOutcome.CLAIMED,
            preview_exchange_invoked=False,
        )
        return self.record, FuturesManualExecutionPlan(
            claim_id=self.claim_id,
            client_order_id=child,
            candidate=dict(self.record.candidate or {}),
            candidate_sha256="b" * 64,
            eligibility_evidence_sha256=(
                self.record.eligibility_evidence_sha256 or "c" * 64
            ),
        )

    def mark_preview_exchange_invoked(self, *, claim_id):
        assert claim_id == self.claim_id
        if self.preview_invocation_validator is not None:
            self.preview_invocation_validator()
        self.record = replace(
            self.record,
            preview_exchange_invoked=True,
        )

    def finish_preview_and_claim_create(self, *, claim_id, execution):
        assert claim_id == self.claim_id
        if self.fail_finish_step == "preview":
            raise FuturesManualLifecycleError(
                "operator_futures_hotpoint_preview_finish_failed",
                http_status_code=503,
            )
        self.record = replace(
            self.record,
            revision=self.record.revision + 1,
            preview_outcome=execution.outcome,
            preview_id_sha256=execution.preview_id_sha256,
            create_outcome=AdminFuturesManualCallOutcome.CLAIMED,
            create_exchange_invoked=False,
        )
        return self.record

    def finish_preview(self, *, claim_id, execution):
        self.record = replace(
            self.record,
            preview_outcome=execution.outcome,
            preview_id_sha256=getattr(
                execution, "preview_id_sha256", None
            ),
        )
        return self.record

    def mark_create_exchange_invoked(self, *, claim_id):
        assert claim_id == self.claim_id
        if self.create_invocation_validator is not None:
            self.create_invocation_validator()
        self.record = replace(self.record, create_exchange_invoked=True)

    def finish_create(self, *, claim_id, execution):
        assert claim_id == self.claim_id
        if self.fail_finish_step == "create":
            raise FuturesManualLifecycleError(
                "operator_futures_hotpoint_create_finish_failed",
                http_status_code=503,
            )
        self.record = replace(
            self.record,
            revision=self.record.revision + 1,
            create_outcome=execution.outcome,
            exchange_order_id_sha256=(
                execution.exchange_order_id_sha256
            ),
            diagnostic_code=execution.diagnostic_code,
        )
        return self.record

    def claim_reconciliation(self, *, claim_id, context=None):
        assert claim_id == self.claim_id
        assert context is not None
        self.record = replace(
            self.record,
            revision=self.record.revision + 1,
            reconciliation_outcome=(
                AdminFuturesManualCallOutcome.CLAIMED
            ),
            reconciliation_exchange_invoked=False,
            reconciliation_catalog_end_at="2026-07-26T12:00:05Z",
            correlation_id=context.correlation_id,
            audit_id=context.audit_id,
        )
        return self.record

    def mark_reconciliation_exchange_invoked(self, *, claim_id):
        self.record = replace(
            self.record,
            reconciliation_exchange_invoked=True,
        )

    def finish_reconciliation(self, *, claim_id, execution):
        if self.fail_finish_step == "reconciliation":
            raise FuturesManualLifecycleError(
                "operator_futures_hotpoint_reconciliation_finish_failed",
                http_status_code=503,
            )
        self.record = replace(
            self.record,
            revision=self.record.revision + 1,
            reconciliation_outcome=execution.outcome,
            create_outcome=(
                AdminFuturesManualCallOutcome.ACCEPTED
                if execution.outcome
                is AdminFuturesManualCallOutcome.ACCEPTED
                else self.record.create_outcome
            ),
            exchange_order_id_sha256=(
                execution.exchange_order_id_sha256
            ),
            order_status=execution.order_status,
            authoritatively_nonterminal=(
                execution.authoritatively_nonterminal
            ),
            diagnostic_code=execution.diagnostic_code,
        )
        return self.record

    def finish_reconciliation_and_claim_cancel(
        self,
        *,
        claim_id,
        execution,
    ):
        assert claim_id == self.claim_id
        self.record = replace(
            self.record,
            revision=self.record.revision + 1,
            reconciliation_outcome=execution.outcome,
            create_outcome=AdminFuturesManualCallOutcome.ACCEPTED,
            exchange_order_id_sha256=(
                execution.exchange_order_id_sha256
            ),
            order_status=execution.order_status,
            authoritatively_nonterminal=True,
            cancel_outcome=AdminFuturesManualCallOutcome.CLAIMED,
            cancel_exchange_invoked=False,
            diagnostic_code=(
                "operator_futures_hotpoint_cancel_claimed"
            ),
        )
        return self.record

    def mark_cancel_exchange_invoked(self, *, claim_id):
        assert claim_id == self.claim_id
        if self.cancel_invocation_error is not None:
            self.cancel_invocation_sealed = True
            raise FuturesManualLifecycleError(
                self.cancel_invocation_error
            )
        if self.seal_cancel_on_mark:
            self.cancel_invocation_sealed = True
        self.record = replace(
            self.record,
            cancel_exchange_invoked=True,
        )

    def release_cancel_invocation_conflict(self, *, claim_id):
        assert claim_id == self.claim_id
        assert self.record.cancel_outcome is (
            AdminFuturesManualCallOutcome.CLAIMED
        )
        assert self.record.cancel_exchange_invoked is False
        self.cancel_conflict_releases += 1
        self.record = replace(
            self.record,
            revision=self.record.revision + 1,
            cancel_outcome=AdminFuturesManualCallOutcome.NOT_RUN,
            cancel_exchange_invoked=None,
            diagnostic_code=(
                "operator_futures_cancel_invocation_already_sealed"
            ),
        )
        return self.record

    def finish_cancel(self, *, claim_id, execution):
        assert claim_id == self.claim_id
        if self.fail_finish_step == "cancel":
            raise FuturesManualLifecycleError(
                "operator_futures_hotpoint_cancel_finish_failed",
                http_status_code=503,
            )
        self.record = replace(
            self.record,
            revision=self.record.revision + 1,
            cancel_outcome=execution.outcome,
            diagnostic_code=execution.diagnostic_code,
        )
        return self.record

    def finish_unentered_claim_unknown(
        self,
        *,
        claim_id,
        step,
        diagnostic_code,
    ):
        self.record = replace(
            self.record,
            **{
                f"{step}_outcome": AdminFuturesManualCallOutcome.UNKNOWN,
                "diagnostic_code": diagnostic_code,
            },
        )
        return self.record


class _EligibilityReader:
    def run(self, *, before_category, before_margin_subread):
        for category in FUTURES_MANUAL_ELIGIBILITY_CATEGORIES:
            before_category(category)
            if category == "futures_margin_collateral":
                for subread in (
                    "futures_balance_summary",
                    "intraday_margin_setting",
                    "current_margin_window_regular",
                    "current_margin_window_intraday",
                ):
                    before_margin_subread(subread)
        return _eligible_result()


class _ExchangeExecutor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def preview(self, candidate, *, before_call):
        del candidate
        before_call()
        self.calls.append("preview")
        return SimpleNamespace(
            outcome=AdminFuturesManualCallOutcome.ACCEPTED,
            diagnostic_code="operator_futures_hotpoint_preview_accepted",
            preview_id_sha256=hashlib.sha256(
                b"ephemeral-preview"
            ).hexdigest(),
            private_preview_id="ephemeral-preview",
        )

    def create(self, **kwargs):
        kwargs["before_call"]()
        self.calls.append("create")
        return SimpleNamespace(
            outcome=AdminFuturesManualCallOutcome.ACCEPTED,
            diagnostic_code="operator_futures_hotpoint_create_accepted",
            exchange_order_id_sha256=hashlib.sha256(
                b"ephemeral-order"
            ).hexdigest(),
            private_exchange_order_id="ephemeral-order",
        )

    def cancel(self, **_kwargs):
        _kwargs["before_call"]()
        self.calls.append("cancel")
        return SimpleNamespace(
            outcome=AdminFuturesManualCallOutcome.ACCEPTED,
            diagnostic_code=(
                "operator_futures_hotpoint_cancel_accepted"
            ),
            exchange_order_id_sha256=hashlib.sha256(
                b"ephemeral-order"
            ).hexdigest(),
        )


class _TerminalCloseout:
    def __init__(self, *, nonterminal: bool = False) -> None:
        self.calls = 0
        self.nonterminal = nonterminal

    def reconcile(self, **kwargs):
        self.calls += 1
        kwargs["before_call"]()
        return FuturesHotpointReconciliationExecution(
            outcome=AdminFuturesManualCallOutcome.ACCEPTED,
            diagnostic_code=(
                "operator_futures_hotpoint_reconciliation_accepted"
            ),
            exchange_order_id_sha256=hashlib.sha256(
                b"ephemeral-order"
            ).hexdigest(),
            order_status="OPEN" if self.nonterminal else "FILLED",
            authoritatively_nonterminal=self.nonterminal,
            public_evidence={},
            private_exchange_order_id="ephemeral-order",
        )


def test_goal13_preview_raw_identity_hash_mismatch_blocks_create_boundary():
    class _MismatchedPreview(_ExchangeExecutor):
        def preview(self, candidate, *, before_call):
            del candidate
            before_call()
            self.calls.append("preview")
            return SimpleNamespace(
                outcome=AdminFuturesManualCallOutcome.ACCEPTED,
                diagnostic_code=(
                    "operator_futures_hotpoint_preview_accepted"
                ),
                preview_id_sha256="d" * 64,
                private_preview_id="ephemeral-preview",
            )

    control_repository = _ControlRepository()
    lifecycle_repository = _LifecycleRepository()
    exchange = _MismatchedPreview()
    service = OperatorFuturesHotpointV2Service(
        control_service=_ControlService(control_repository),
        control_repository=control_repository,
        lifecycle_repository=lifecycle_repository,
        eligibility_reader_factory=lambda _binding: _EligibilityReader(),
        exchange_executor=exchange,
        closeout_executor=_TerminalCloseout(),
    )

    result = _run_once(service)

    assert exchange.calls == ["preview"]
    assert result.lifecycle.preview_outcome is (
        AdminFuturesManualCallOutcome.UNKNOWN
    )
    assert result.lifecycle.create_outcome is (
        AdminFuturesManualCallOutcome.NOT_RUN
    )
    assert result.lifecycle.create_exchange_invoked is None


def test_goal13_reconciled_raw_identity_hash_mismatch_blocks_cancel_boundary():
    class _MismatchedCloseout(_TerminalCloseout):
        def reconcile(self, **kwargs):
            self.calls += 1
            kwargs["before_call"]()
            return FuturesHotpointReconciliationExecution(
                outcome=AdminFuturesManualCallOutcome.ACCEPTED,
                diagnostic_code=(
                    "operator_futures_hotpoint_reconciliation_accepted"
                ),
                exchange_order_id_sha256="e" * 64,
                order_status="OPEN",
                authoritatively_nonterminal=True,
                public_evidence={},
                private_exchange_order_id="ephemeral-order",
            )

    control_repository = _ControlRepository()
    lifecycle_repository = _LifecycleRepository()
    exchange = _ExchangeExecutor()
    closeout = _MismatchedCloseout(nonterminal=True)
    service = OperatorFuturesHotpointV2Service(
        control_service=_ControlService(control_repository),
        control_repository=control_repository,
        lifecycle_repository=lifecycle_repository,
        eligibility_reader_factory=lambda _binding: _EligibilityReader(),
        exchange_executor=exchange,
        closeout_executor=closeout,
    )
    executed = _run_once(service)

    result = _safe_closeout(
        service,
        expected_revision=executed.revision,
    )

    assert closeout.calls == 1
    assert exchange.calls == ["preview", "create"]
    assert result.lifecycle.reconciliation_outcome is (
        AdminFuturesManualCallOutcome.UNKNOWN
    )
    assert result.lifecycle.cancel_outcome is (
        AdminFuturesManualCallOutcome.NOT_RUN
    )
    assert result.lifecycle.cancel_exchange_invoked is None


def _request_context(intent: str) -> OperatorHotpointRequestContext:
    safe = intent == HOTPOINT_SAFE_CLOSEOUT_OPERATOR_INTENT
    return OperatorHotpointRequestContext(
        actor_id="operator-safe" if safe else "operator-run",
        roles=("admin", "trader"),
        idempotency_key=f"idem-{intent}",
        correlation_id="corr-safe" if safe else "corr-run",
        audit_id=(
            "66666666-6666-4666-8666-666666666666"
            if safe
            else "55555555-5555-4555-8555-555555555555"
        ),
        operator_intent=intent,
    )


def _run_once(
    service: OperatorFuturesHotpointV2Service,
    *,
    expected_revision: int = 2,
    expected_parent_client_order_id: str = (
        "11111111-1111-4111-8111-111111111111"
    ),
    context: OperatorHotpointRequestContext | None = None,
):
    return service.run_once(
        expected_revision=expected_revision,
        expected_parent_client_order_id=(
            expected_parent_client_order_id
        ),
        confirm_bounded_trigger_evaluation=True,
        authorize_one_no_retry_six_category_cycle=True,
        acknowledge_cycle_is_goal_global_and_limited_to_ten=True,
        acknowledge_unsuccessful_or_unknown_cycle_fails_closed=True,
        authorize_one_preview_and_conditional_identical_create=True,
        acknowledge_unknown_preview_or_create_consumes_allowance=True,
        acknowledge_create_requires_accepted_identical_preview=True,
        context=context
        or _request_context(HOTPOINT_RUN_OPERATOR_INTENT),
    )


def _safe_closeout(
    service: OperatorFuturesHotpointV2Service,
    *,
    expected_revision: int,
):
    return service.safe_closeout(
        expected_revision=expected_revision,
        expected_child_client_order_id=(
            "operator-futures-hotpoint-v2-child"
        ),
        authorize_one_exact_no_retry_reconciliation=True,
        acknowledge_unknown_reconciliation_consumes_allowance=True,
        confirm_exact_child_safe_closeout=True,
        acknowledge_cancel_only_exact_authoritatively_nonterminal_child=True,
        acknowledge_unknown_outcome_consumes_cancel_allowance=True,
        context=_request_context(
            HOTPOINT_SAFE_CLOSEOUT_OPERATOR_INTENT
        ),
    )


def test_goal13_coordinator_runs_preview_create_then_terminal_read_closeout():
    control_repository = _ControlRepository()
    lifecycle_repository = _LifecycleRepository()
    exchange = _ExchangeExecutor()
    closeout = _TerminalCloseout()
    service = OperatorFuturesHotpointV2Service(
        control_service=_ControlService(control_repository),
        control_repository=control_repository,
        lifecycle_repository=lifecycle_repository,
        eligibility_reader_factory=lambda _binding: _EligibilityReader(),
        exchange_executor=exchange,
        closeout_executor=closeout,
    )

    executed = _run_once(service)

    assert exchange.calls == ["preview", "create"]
    assert executed.lifecycle.create_outcome is (
        AdminFuturesManualCallOutcome.ACCEPTED
    )
    assert executed.allowed_actions == ("SAFE_CLOSEOUT",)
    assert control_repository.closed == 1
    assert executed.lifecycle.correlation_id == "corr-run"
    assert executed.lifecycle.audit_id == (
        "55555555-5555-4555-8555-555555555555"
    )
    assert executed.latest_external_command is not None
    assert executed.latest_external_command.status == "SUCCESS"
    assert executed.latest_external_command.correlation_id == "corr-run"
    assert executed.latest_external_command.request_revision == 2
    assert service.read().latest_external_command == (
        executed.latest_external_command
    )

    replayed = _run_once(service)
    assert replayed == executed
    assert replayed.lifecycle.create_outcome is (
        AdminFuturesManualCallOutcome.ACCEPTED
    )
    assert exchange.calls == ["preview", "create"]
    assert lifecycle_repository.record.cycles_used == 1
    assert control_repository.closed == 1

    for changed in (
        {
            "expected_revision": 3,
        },
        {
            "expected_parent_client_order_id": (
                "22222222-2222-4222-8222-222222222222"
            ),
        },
        {
            "context": replace(
                _request_context(HOTPOINT_RUN_OPERATOR_INTENT),
                actor_id="operator-2",
            ),
        },
    ):
        with pytest.raises(
            OperatorHotpointControlError,
            match="operator_futures_hotpoint_idempotency_conflict",
        ) as conflict:
            _run_once(service, **changed)
        assert conflict.value.http_status_code == 409
    assert exchange.calls == ["preview", "create"]
    assert lifecycle_repository.record.cycles_used == 1

    closed = service.safe_closeout(
        expected_revision=executed.revision,
        expected_child_client_order_id=(
            "operator-futures-hotpoint-v2-child"
        ),
        authorize_one_exact_no_retry_reconciliation=True,
        acknowledge_unknown_reconciliation_consumes_allowance=True,
        confirm_exact_child_safe_closeout=True,
        acknowledge_cancel_only_exact_authoritatively_nonterminal_child=True,
        acknowledge_unknown_outcome_consumes_cancel_allowance=True,
        context=_request_context(
            HOTPOINT_SAFE_CLOSEOUT_OPERATOR_INTENT
        ),
    )

    assert closed.cancel_disposition == "NOT_REQUIRED"
    assert "SAFE_CLOSEOUT" not in closed.allowed_actions
    assert closed.lifecycle.correlation_id == "corr-safe"
    assert closed.lifecycle.audit_id == (
        "66666666-6666-4666-8666-666666666666"
    )
    replayed_closeout = service.safe_closeout(
        expected_revision=executed.revision,
        expected_child_client_order_id=(
            "operator-futures-hotpoint-v2-child"
        ),
        authorize_one_exact_no_retry_reconciliation=True,
        acknowledge_unknown_reconciliation_consumes_allowance=True,
        confirm_exact_child_safe_closeout=True,
        acknowledge_cancel_only_exact_authoritatively_nonterminal_child=True,
        acknowledge_unknown_outcome_consumes_cancel_allowance=True,
        context=_request_context(
            HOTPOINT_SAFE_CLOSEOUT_OPERATOR_INTENT
        ),
    )
    assert replayed_closeout == closed
    assert replayed_closeout.cancel_disposition == "NOT_REQUIRED"
    assert closeout.calls == 1


def test_goal13_existing_position_blocks_single_cycle_before_all_live_calls():
    class _ExistingExposureReader:
        def run(self, *, before_category, before_margin_subread):
            attempts = {
                category: 0
                for category in FUTURES_MANUAL_ELIGIBILITY_CATEGORIES
            }
            for category in FUTURES_MANUAL_ELIGIBILITY_CATEGORIES:
                before_category(category)
                attempts[category] = 1
                if category == "futures_margin_collateral":
                    for subread in (
                        "futures_balance_summary",
                        "intraday_margin_setting",
                        "current_margin_window_regular",
                        "current_margin_window_intraday",
                    ):
                        before_margin_subread(subread)
            product = {
                **_product_session(),
                "product_type": "FUTURE",
                "price": "5",
                "price_increment": "0.01",
                "base_increment": "1",
                "base_min_size": "1",
            }
            details = product["future_product_details"]
            assert isinstance(details, dict)
            details.update(
                {
                    "contract_size": "10",
                    "contract_code": "AVP",
                    "venue": "cde",
                    "risk_managed_by": "MANAGED_BY_FCM",
                    "contract_expiry_type": "EXPIRING",
                    "intraday_margin_rate": {
                        "long_margin_rate": "0.25",
                        "short_margin_rate": "0.30",
                    },
                    "overnight_margin_rate": {
                        "long_margin_rate": "0.50",
                        "short_margin_rate": "0.55",
                    },
                }
            )
            with pytest.raises(
                ValueError,
                match=(
                    "operator_futures_product_ticket_existing_exposure"
                ),
            ):
                build_futures_product_ticket_candidate(
                    selection=FuturesProductPolicySelection(
                        product_id="AVP-20DEC30-CDE",
                        policy_revision=(
                            FUTURES_HOTPOINT_POLICY_REVISION
                        ),
                        policy_sha256=FUTURES_HOTPOINT_POLICY_SHA256,
                        lifecycle="ENABLED",
                    ),
                    product=product,
                    book={
                        "pricebooks": [
                            {
                                "product_id": "AVP-20DEC30-CDE",
                                "bids": [{"price": "5.00", "size": "8"}],
                                "asks": [{"price": "5.01", "size": "9"}],
                                "time": "2026-07-26T12:00:00Z",
                            }
                        ]
                    },
                    positions={
                        "positions": [
                            {
                                "product_id": "AVP-20DEC30-CDE",
                                "number_of_contracts": "1",
                            }
                        ]
                    },
                    available_margin_usdc="500",
                    observed_at=datetime(
                        2026,
                        7,
                        26,
                        12,
                        0,
                        10,
                        tzinfo=timezone.utc,
                    ),
                )
            diagnostic = (
                "operator_futures_hotpoint_existing_exposure"
            )
            public = {
                "diagnostic_code": diagnostic,
                "category_attempts": attempts,
                "raw_responses_included": False,
                "private_identifiers_included": False,
                "exception_text_included": False,
            }
            return FuturesManualEligibilityResult(
                outcome=(
                    AdminFuturesManualEligibilityOutcome.INELIGIBLE
                ),
                diagnostic_code=diagnostic,
                category_attempts=attempts,
                candidate=None,
                portfolio_id_sha256=None,
                evidence_sha256=hashlib.sha256(
                    json.dumps(
                        public,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                public_evidence=public,
            )

    control_repository = _ControlRepository()
    lifecycle_repository = _LifecycleRepository()
    exchange = _ExchangeExecutor()
    service = OperatorFuturesHotpointV2Service(
        control_service=_ControlService(control_repository),
        control_repository=control_repository,
        lifecycle_repository=lifecycle_repository,
        eligibility_reader_factory=lambda _binding: (
            _ExistingExposureReader()
        ),
        exchange_executor=exchange,
        closeout_executor=_TerminalCloseout(),
    )

    result = _run_once(service)

    assert result.trigger_fill_count == 3
    assert result.lifecycle.cycles_used == 1
    assert result.lifecycle.eligibility_outcome is (
        AdminFuturesManualEligibilityOutcome.INELIGIBLE
    )
    assert result.lifecycle.eligibility_diagnostic_code == (
        "operator_futures_hotpoint_existing_exposure"
    )
    assert result.lifecycle.preview_outcome is (
        AdminFuturesManualCallOutcome.NOT_RUN
    )
    assert result.lifecycle.create_outcome is (
        AdminFuturesManualCallOutcome.NOT_RUN
    )
    assert result.lifecycle.cancel_outcome is (
        AdminFuturesManualCallOutcome.NOT_RUN
    )
    assert exchange.calls == []


@pytest.mark.parametrize(
    ("status", "disposition"),
    (
        ("PENDING", "DEFERRED_TRANSITIONAL"),
        ("QUEUED", "DEFERRED_TRANSITIONAL"),
        ("EDIT_QUEUED", "DEFERRED_TRANSITIONAL"),
        ("CANCEL_QUEUED", "ALREADY_CANCEL_REQUESTED"),
    ),
)
def test_goal13_transitional_closeout_does_not_claim_or_invoke_cancel(
    status,
    disposition,
):
    class _TransitionalCloseout(_TerminalCloseout):
        def reconcile(self, **kwargs):
            self.calls += 1
            kwargs["before_call"]()
            return FuturesHotpointReconciliationExecution(
                outcome=AdminFuturesManualCallOutcome.ACCEPTED,
                diagnostic_code=(
                    "operator_futures_hotpoint_reconciliation_accepted"
                ),
                exchange_order_id_sha256="e" * 64,
                order_status=status,
                authoritatively_nonterminal=True,
                public_evidence={},
                private_exchange_order_id="ephemeral-order",
            )

    control_repository = _ControlRepository()
    lifecycle_repository = _LifecycleRepository()
    exchange = _ExchangeExecutor()
    closeout = _TransitionalCloseout()
    service = OperatorFuturesHotpointV2Service(
        control_service=_ControlService(control_repository),
        control_repository=control_repository,
        lifecycle_repository=lifecycle_repository,
        eligibility_reader_factory=lambda _binding: _EligibilityReader(),
        exchange_executor=exchange,
        closeout_executor=closeout,
    )
    executed = _run_once(service)

    closed = _safe_closeout(
        service,
        expected_revision=executed.revision,
    )

    assert closed.lifecycle.order_status == status
    assert closed.lifecycle.authoritatively_nonterminal is True
    assert closed.cancel_disposition == disposition
    assert closed.lifecycle.cancel_outcome is (
        AdminFuturesManualCallOutcome.NOT_RUN
    )
    assert closed.lifecycle.cancel_exchange_invoked is None
    assert exchange.calls == ["preview", "create"]
    assert closeout.calls == 1


def test_goal13_shared_cancel_seal_loser_is_known_unconsumed_and_no_sdk_call(
) -> None:
    control_repository = _ControlRepository()
    lifecycle_repository = _LifecycleRepository()
    exchange = _ExchangeExecutor()
    service = OperatorFuturesHotpointV2Service(
        control_service=_ControlService(control_repository),
        control_repository=control_repository,
        lifecycle_repository=lifecycle_repository,
        eligibility_reader_factory=lambda _binding: _EligibilityReader(),
        exchange_executor=exchange,
        closeout_executor=_TerminalCloseout(nonterminal=True),
    )
    executed = _run_once(service)
    lifecycle_repository.cancel_invocation_error = (
        "operator_futures_cancel_invocation_already_sealed"
    )

    closed = _safe_closeout(
        service,
        expected_revision=executed.revision,
    )

    assert exchange.calls == ["preview", "create"]
    assert closed.lifecycle.cancel_outcome is (
        AdminFuturesManualCallOutcome.NOT_RUN
    )
    assert closed.lifecycle.cancel_exchange_invoked is None
    assert closed.lifecycle.diagnostic_code == (
        "operator_futures_cancel_invocation_already_sealed"
    )
    assert closed.cancel_disposition == "ALREADY_CANCEL_REQUESTED"
    assert "SAFE_CLOSEOUT" not in closed.allowed_actions
    assert lifecycle_repository.cancel_conflict_releases == 1
    replayed = _safe_closeout(
        service,
        expected_revision=executed.revision,
    )
    assert replayed == closed
    assert exchange.calls == ["preview", "create"]
    assert lifecycle_repository.cancel_conflict_releases == 1


def test_goal13_own_shared_cancel_seal_preserves_accepted_cancel_readback(
) -> None:
    control_repository = _ControlRepository()
    lifecycle_repository = _LifecycleRepository()
    lifecycle_repository.seal_cancel_on_mark = True
    exchange = _ExchangeExecutor()
    service = OperatorFuturesHotpointV2Service(
        control_service=_ControlService(control_repository),
        control_repository=control_repository,
        lifecycle_repository=lifecycle_repository,
        eligibility_reader_factory=lambda _binding: _EligibilityReader(),
        exchange_executor=exchange,
        closeout_executor=_TerminalCloseout(nonterminal=True),
    )
    executed = _run_once(service)

    closed = _safe_closeout(
        service,
        expected_revision=executed.revision,
    )

    assert exchange.calls == ["preview", "create", "cancel"]
    assert closed.lifecycle.cancel_outcome is (
        AdminFuturesManualCallOutcome.ACCEPTED
    )
    assert closed.lifecycle.cancel_exchange_invoked is True
    assert closed.cancel_disposition == "REQUIRED"
    assert service.read() == closed


def test_goal13_foreign_cancel_seal_before_reconciliation_is_known_fail_closed(
) -> None:
    control_repository = _ControlRepository()
    lifecycle_repository = _LifecycleRepository()
    exchange = _ExchangeExecutor()
    service = OperatorFuturesHotpointV2Service(
        control_service=_ControlService(control_repository),
        control_repository=control_repository,
        lifecycle_repository=lifecycle_repository,
        eligibility_reader_factory=lambda _binding: _EligibilityReader(),
        exchange_executor=exchange,
        closeout_executor=_TerminalCloseout(nonterminal=True),
    )
    _run_once(service)
    lifecycle_repository.cancel_invocation_sealed = True

    readback = service.read()

    assert readback.lifecycle.reconciliation_outcome is (
        AdminFuturesManualCallOutcome.NOT_RUN
    )
    assert readback.lifecycle.cancel_outcome is (
        AdminFuturesManualCallOutcome.NOT_RUN
    )
    assert readback.cancel_disposition == "ALREADY_CANCEL_REQUESTED"
    assert readback.diagnostic_code == (
        "operator_futures_cancel_invocation_already_sealed"
    )
    assert "SAFE_CLOSEOUT" not in readback.allowed_actions


@pytest.mark.parametrize(
    ("status", "authoritatively_nonterminal", "disposition"),
    (
        ("OPEN", True, "REQUIRED"),
        ("PENDING", True, "DEFERRED_TRANSITIONAL"),
        ("QUEUED", True, "DEFERRED_TRANSITIONAL"),
        ("EDIT_QUEUED", True, "DEFERRED_TRANSITIONAL"),
        ("CANCEL_QUEUED", True, "ALREADY_CANCEL_REQUESTED"),
        ("FILLED", False, "NOT_REQUIRED"),
        ("CANCELLED", False, "NOT_REQUIRED"),
        ("EXPIRED", False, "NOT_REQUIRED"),
        ("FAILED", False, "NOT_REQUIRED"),
    ),
)
def test_goal13_cancel_disposition_is_backend_owned_by_exact_status(
    status,
    authoritatively_nonterminal,
    disposition,
) -> None:
    lifecycle = replace(
        _lifecycle_record(),
        reconciliation_outcome=(
            AdminFuturesManualCallOutcome.ACCEPTED
        ),
        reconciliation_exchange_invoked=True,
        order_status=status,
        authoritatively_nonterminal=authoritatively_nonterminal,
    )

    assert (
        OperatorFuturesHotpointV2Service._cancel_disposition(
            lifecycle
        )
        == disposition
    )


@pytest.mark.parametrize(
    ("step", "expected_exchange_calls", "nonterminal"),
    (
        ("preview", ["preview"], False),
        ("create", ["preview", "create"], False),
        ("reconciliation", ["preview", "create"], False),
        ("cancel", ["preview", "create", "cancel"], True),
    ),
)
def test_goal13_entered_unterminated_boundary_replays_unknown_without_recall(
    step,
    expected_exchange_calls,
    nonterminal,
) -> None:
    control_repository = _ControlRepository()
    lifecycle_repository = _LifecycleRepository()
    exchange = _ExchangeExecutor()
    closeout = _TerminalCloseout(nonterminal=nonterminal)
    service = OperatorFuturesHotpointV2Service(
        control_service=_ControlService(control_repository),
        control_repository=control_repository,
        lifecycle_repository=lifecycle_repository,
        eligibility_reader_factory=lambda _binding: _EligibilityReader(),
        exchange_executor=exchange,
        closeout_executor=closeout,
    )

    if step in {"preview", "create"}:
        lifecycle_repository.fail_finish_step = step
        invoke = lambda: _run_once(service)
    else:
        executed = _run_once(service)
        lifecycle_repository.fail_finish_step = step
        invoke = lambda: _safe_closeout(
            service,
            expected_revision=executed.revision,
        )

    failures: list[tuple[str, int]] = []
    for _ in range(2):
        with pytest.raises(OperatorHotpointControlError) as failure:
            invoke()
        failures.append(
            (
                failure.value.code,
                failure.value.http_status_code,
            )
        )

    expected_failure = (
        f"operator_futures_hotpoint_{step}_"
        "terminal_persistence_unknown",
        503,
    )
    assert failures == [expected_failure, expected_failure]
    assert exchange.calls == expected_exchange_calls
    assert closeout.calls == (
        1 if step in {"reconciliation", "cancel"} else 0
    )


@pytest.mark.parametrize("runtime_state", ("PAUSED", "DRAINING", "STOPPED"))
def test_goal13_run_is_blocked_before_calls_when_runtime_not_running(
    runtime_state,
) -> None:
    controller = RuntimeController()
    if runtime_state == "PAUSED":
        controller.request_pause()
    elif runtime_state == "DRAINING":
        controller.request_shutdown()
    else:
        controller.drain_and_stop(timeout_seconds=0)
    control_repository = _ControlRepository()
    lifecycle_repository = _LifecycleRepository()
    exchange = _ExchangeExecutor()
    service = OperatorFuturesHotpointV2Service(
        control_service=_ControlService(control_repository),
        control_repository=control_repository,
        lifecycle_repository=lifecycle_repository,
        eligibility_reader_factory=lambda _binding: _EligibilityReader(),
        exchange_executor=exchange,
        closeout_executor=_TerminalCloseout(),
        runtime_controller_factory=lambda: controller,
    )

    with pytest.raises(
        OperatorHotpointControlError,
        match="operator_futures_hotpoint_runtime_not_admitting",
    ):
        _run_once(service)

    assert exchange.calls == []
    assert lifecycle_repository.record.cycles_used == 0
    assert lifecycle_repository.external_commands == {}
    assert controller.inflight_snapshot() == {}


def test_goal13_pause_between_preview_and_create_blocks_create() -> None:
    controller = RuntimeController()

    class _PauseAfterPreviewExchange(_ExchangeExecutor):
        def preview(self, candidate, *, before_call):
            execution = super().preview(
                candidate,
                before_call=before_call,
            )
            assert controller.request_pause() is True
            return execution

    control_repository = _ControlRepository()
    lifecycle_repository = _LifecycleRepository()
    exchange = _PauseAfterPreviewExchange()
    service = OperatorFuturesHotpointV2Service(
        control_service=_ControlService(control_repository),
        control_repository=control_repository,
        lifecycle_repository=lifecycle_repository,
        eligibility_reader_factory=lambda _binding: _EligibilityReader(),
        exchange_executor=exchange,
        closeout_executor=_TerminalCloseout(),
        runtime_controller_factory=lambda: controller,
    )

    blocked = _run_once(service)

    assert exchange.calls == ["preview"]
    assert blocked.lifecycle.preview_outcome is (
        AdminFuturesManualCallOutcome.ACCEPTED
    )
    assert blocked.lifecycle.create_outcome is (
        AdminFuturesManualCallOutcome.UNKNOWN
    )
    assert blocked.lifecycle.create_exchange_invoked is False
    assert controller.inflight_snapshot() == {}


def test_goal13_revocation_at_preview_boundary_blocks_preview_sdk_call():
    control_repository = _ControlRepository()
    lifecycle_repository = _LifecycleRepository()

    def validate_preview_authority() -> None:
        if (
            control_repository.record.kill_switch_state
            is not HotpointKillSwitchState.ENABLED
            or control_repository.record.window_state
            is not HotpointWindowState.ARMED
        ):
            raise FuturesManualLifecycleError(
                "operator_futures_hotpoint_preview_invocation_"
                "not_authorized"
            )

    lifecycle_repository.preview_invocation_validator = (
        validate_preview_authority
    )

    class _RevokeBeforePreviewBoundary(_ExchangeExecutor):
        def preview(self, candidate, *, before_call):
            del candidate
            control_repository.record = replace(
                control_repository.record,
                kill_switch_state=HotpointKillSwitchState.DISABLED,
                window_state=HotpointWindowState.DISARMED,
            )
            before_call()
            self.calls.append("preview")
            pytest.fail("Preview SDK boundary must remain unentered")

    exchange = _RevokeBeforePreviewBoundary()
    service = OperatorFuturesHotpointV2Service(
        control_service=_ControlService(control_repository),
        control_repository=control_repository,
        lifecycle_repository=lifecycle_repository,
        eligibility_reader_factory=lambda _binding: _EligibilityReader(),
        exchange_executor=exchange,
        closeout_executor=_TerminalCloseout(),
    )

    blocked = _run_once(service)

    assert exchange.calls == []
    assert blocked.lifecycle.preview_outcome is (
        AdminFuturesManualCallOutcome.UNKNOWN
    )
    assert blocked.lifecycle.preview_exchange_invoked is False
    assert blocked.lifecycle.create_outcome is (
        AdminFuturesManualCallOutcome.NOT_RUN
    )
    assert blocked.lifecycle.create_exchange_invoked is None


def test_goal13_stale_at_preview_marker_blocks_preview_sdk_call():
    control_repository = _ControlRepository()
    lifecycle_repository = _LifecycleRepository()
    lifecycle_repository.preview_invocation_validator = lambda: (
        (_ for _ in ()).throw(
            FuturesManualLifecycleError(
                "operator_futures_manual_candidate_stale"
            )
        )
    )

    class _StaleBeforePreviewBoundary(_ExchangeExecutor):
        def preview(self, candidate, *, before_call):
            del candidate
            before_call()
            self.calls.append("preview")
            pytest.fail("Preview SDK boundary must remain unentered")

    exchange = _StaleBeforePreviewBoundary()
    service = OperatorFuturesHotpointV2Service(
        control_service=_ControlService(control_repository),
        control_repository=control_repository,
        lifecycle_repository=lifecycle_repository,
        eligibility_reader_factory=lambda _binding: _EligibilityReader(),
        exchange_executor=exchange,
        closeout_executor=_TerminalCloseout(),
    )

    blocked = _run_once(service)

    assert exchange.calls == []
    assert blocked.lifecycle.preview_outcome is (
        AdminFuturesManualCallOutcome.UNKNOWN
    )
    assert blocked.lifecycle.preview_exchange_invoked is False
    assert blocked.lifecycle.create_outcome is (
        AdminFuturesManualCallOutcome.NOT_RUN
    )


def test_goal13_stale_at_create_marker_blocks_create_sdk_call():
    control_repository = _ControlRepository()
    lifecycle_repository = _LifecycleRepository()
    lifecycle_repository.create_invocation_validator = lambda: (
        (_ for _ in ()).throw(
            FuturesManualLifecycleError(
                "operator_futures_manual_candidate_stale"
            )
        )
    )

    class _StaleBeforeCreateBoundary(_ExchangeExecutor):
        def create(self, **kwargs):
            kwargs["before_call"]()
            self.calls.append("create")
            pytest.fail("Create SDK boundary must remain unentered")

    exchange = _StaleBeforeCreateBoundary()
    service = OperatorFuturesHotpointV2Service(
        control_service=_ControlService(control_repository),
        control_repository=control_repository,
        lifecycle_repository=lifecycle_repository,
        eligibility_reader_factory=lambda _binding: _EligibilityReader(),
        exchange_executor=exchange,
        closeout_executor=_TerminalCloseout(),
    )

    blocked = _run_once(service)

    assert exchange.calls == ["preview"]
    assert blocked.lifecycle.preview_outcome is (
        AdminFuturesManualCallOutcome.ACCEPTED
    )
    assert blocked.lifecycle.create_outcome is (
        AdminFuturesManualCallOutcome.UNKNOWN
    )
    assert blocked.lifecycle.create_exchange_invoked is False


@pytest.mark.parametrize("runtime_state", ("PAUSED", "DRAINING"))
def test_goal13_safe_closeout_is_continuously_tracked_while_quiescing(
    runtime_state,
) -> None:
    controller = RuntimeController()

    class _TrackedCloseout(_TerminalCloseout):
        def reconcile(self, **kwargs):
            assert controller.inflight_snapshot() == {
                INFLIGHT_REST_CANCEL: 1
            }
            return super().reconcile(**kwargs)

    class _TrackedExchange(_ExchangeExecutor):
        def cancel(self, **kwargs):
            assert controller.inflight_snapshot() == {
                INFLIGHT_REST_CANCEL: 1
            }
            return super().cancel(**kwargs)

    control_repository = _ControlRepository()
    lifecycle_repository = _LifecycleRepository()
    exchange = _TrackedExchange()
    closeout = _TrackedCloseout(nonterminal=True)
    service = OperatorFuturesHotpointV2Service(
        control_service=_ControlService(control_repository),
        control_repository=control_repository,
        lifecycle_repository=lifecycle_repository,
        eligibility_reader_factory=lambda _binding: _EligibilityReader(),
        exchange_executor=exchange,
        closeout_executor=closeout,
        runtime_controller_factory=lambda: controller,
    )
    executed = _run_once(service)
    if runtime_state == "PAUSED":
        controller.request_pause()
    else:
        controller.request_shutdown()

    closed = _safe_closeout(
        service,
        expected_revision=executed.revision,
    )

    assert closed.lifecycle.cancel_outcome is (
        AdminFuturesManualCallOutcome.ACCEPTED
    )
    assert exchange.calls == ["preview", "create", "cancel"]
    assert closeout.calls == 1
    assert controller.inflight_snapshot() == {}


def test_goal13_safe_closeout_is_blocked_after_runtime_stops() -> None:
    controller = RuntimeController()
    control_repository = _ControlRepository()
    lifecycle_repository = _LifecycleRepository()
    exchange = _ExchangeExecutor()
    closeout = _TerminalCloseout(nonterminal=True)
    service = OperatorFuturesHotpointV2Service(
        control_service=_ControlService(control_repository),
        control_repository=control_repository,
        lifecycle_repository=lifecycle_repository,
        eligibility_reader_factory=lambda _binding: _EligibilityReader(),
        exchange_executor=exchange,
        closeout_executor=closeout,
        runtime_controller_factory=lambda: controller,
    )
    executed = _run_once(service)
    controller.drain_and_stop(timeout_seconds=0)

    with pytest.raises(
        OperatorHotpointControlError,
        match="operator_futures_hotpoint_runtime_not_admitting",
    ):
        _safe_closeout(
            service,
            expected_revision=executed.revision,
        )

    assert exchange.calls == ["preview", "create"]
    assert closeout.calls == 0


def test_goal13_runtime_drain_waits_for_safe_closeout_scope() -> None:
    controller = RuntimeController()
    entered = Event()
    release = Event()

    class _BlockingCloseout(_TerminalCloseout):
        def reconcile(self, **kwargs):
            kwargs["before_call"]()
            entered.set()
            assert release.wait(timeout=2)
            self.calls += 1
            return FuturesHotpointReconciliationExecution(
                outcome=AdminFuturesManualCallOutcome.ACCEPTED,
                diagnostic_code=(
                    "operator_futures_hotpoint_reconciliation_accepted"
                ),
                exchange_order_id_sha256="e" * 64,
                order_status="FILLED",
                authoritatively_nonterminal=False,
                public_evidence={},
                private_exchange_order_id="ephemeral-order",
            )

    control_repository = _ControlRepository()
    lifecycle_repository = _LifecycleRepository()
    service = OperatorFuturesHotpointV2Service(
        control_service=_ControlService(control_repository),
        control_repository=control_repository,
        lifecycle_repository=lifecycle_repository,
        eligibility_reader_factory=lambda _binding: _EligibilityReader(),
        exchange_executor=_ExchangeExecutor(),
        closeout_executor=_BlockingCloseout(),
        runtime_controller_factory=lambda: controller,
    )
    executed = _run_once(service)

    with ThreadPoolExecutor(max_workers=2) as pool:
        closeout_future = pool.submit(
            _safe_closeout,
            service,
            expected_revision=executed.revision,
        )
        assert entered.wait(timeout=2)
        drain_future = pool.submit(
            controller.drain_and_stop,
            2,
        )
        assert controller.inflight_snapshot() == {
            INFLIGHT_REST_CANCEL: 1
        }
        assert drain_future.done() is False
        release.set()
        closed = closeout_future.result(timeout=2)
        drained = drain_future.result(timeout=2)

    assert closed.cancel_disposition == "NOT_REQUIRED"
    assert drained.drained_clean is True
    assert drained.state_after.value == "STOPPED"
    assert controller.inflight_snapshot() == {}


def test_goal13_coordinator_closes_control_after_restart_recovery() -> None:
    control_repository = _ControlRepository()
    lifecycle_repository = _LifecycleRepository()
    lifecycle_repository.record = replace(
        lifecycle_repository.record,
        preview_outcome=AdminFuturesManualCallOutcome.UNKNOWN,
        preview_exchange_invoked=False,
        execution_claim_id="33333333-3333-4333-8333-333333333333",
        client_order_id="operator-futures-hotpoint-v2-child",
    )

    service = OperatorFuturesHotpointV2Service(
        control_service=_ControlService(control_repository),
        control_repository=control_repository,
        lifecycle_repository=lifecycle_repository,
        eligibility_reader_factory=lambda _binding: _EligibilityReader(),
        exchange_executor=_ExchangeExecutor(),
        closeout_executor=_TerminalCloseout(),
    )

    state = service.read()
    assert control_repository.closed == 1
    assert state.control.kill_switch_state is HotpointKillSwitchState.DISABLED
    assert "RUN_ONCE" not in state.allowed_actions


@pytest.mark.parametrize(
    "code",
    (
        "operator_futures_hotpoint_parent_projection_invalid",
        "operator_futures_hotpoint_fill_conservation_invalid",
        "operator_hotpoint_fill_evidence_invalid",
    ),
)
def test_goal13_prelatch_read_fails_closed_with_actionless_sanitized_state(
    code,
) -> None:
    class _IncoherentParentControl(_ControlRepository):
        def read_futures_trigger_readback(self):
            raise ValueError(code)

    control_repository = _IncoherentParentControl()
    lifecycle_repository = _LifecycleRepository()
    before = lifecycle_repository.read()
    service = OperatorFuturesHotpointV2Service(
        control_service=_ControlService(control_repository),
        control_repository=control_repository,
        lifecycle_repository=lifecycle_repository,
        eligibility_reader_factory=lambda _binding: _EligibilityReader(),
        exchange_executor=_ExchangeExecutor(),
        closeout_executor=_TerminalCloseout(),
    )

    state = service.read()

    assert state.allowed_actions == ()
    assert state.trigger_fill_count == 0
    assert state.trigger_evidence_sha256 is None
    assert state.diagnostic_code == (
        "operator_futures_hotpoint_trigger_evidence_unavailable"
    )
    assert lifecycle_repository.read() == before


def test_goal13_unknown_external_command_replays_exact_fixed_failure() -> None:
    class _ExplodingControlRepository(_ControlRepository):
        def __init__(self) -> None:
            super().__init__()
            self.claim_calls = 0

        def claim_futures_trigger(self, **_kwargs):
            self.claim_calls += 1
            raise RuntimeError("withheld")

    control_repository = _ExplodingControlRepository()
    lifecycle_repository = _LifecycleRepository()
    exchange = _ExchangeExecutor()
    service = OperatorFuturesHotpointV2Service(
        control_service=_ControlService(control_repository),
        control_repository=control_repository,
        lifecycle_repository=lifecycle_repository,
        eligibility_reader_factory=lambda _binding: _EligibilityReader(),
        exchange_executor=exchange,
        closeout_executor=_TerminalCloseout(),
    )

    failures: list[tuple[str, int]] = []
    for _ in range(2):
        with pytest.raises(OperatorHotpointControlError) as failure:
            _run_once(service)
        failures.append(
            (
                failure.value.code,
                failure.value.http_status_code,
            )
        )

    assert failures == [
        ("operator_futures_hotpoint_run_unavailable", 503),
        ("operator_futures_hotpoint_run_unavailable", 503),
    ]
    assert control_repository.claim_calls == 1
    assert exchange.calls == []


def test_goal13_fresh_command_cannot_overwrite_active_trigger_owner() -> None:
    control_repository = _ControlRepository()
    lifecycle_repository = _LifecycleRepository()
    exchange = _ExchangeExecutor()
    service = OperatorFuturesHotpointV2Service(
        control_service=_ControlService(control_repository),
        control_repository=control_repository,
        lifecycle_repository=lifecycle_repository,
        eligibility_reader_factory=lambda _binding: _EligibilityReader(),
        exchange_executor=exchange,
        closeout_executor=_TerminalCloseout(),
    )
    owner_context = _request_context(HOTPOINT_RUN_OPERATOR_INTENT)
    lifecycle_repository.claim_hotpoint_external_command(
        action="RUN_ONCE",
        context=service._external_command_context(
            context=owner_context,
            expected_revision=2,
        ),
        request_payload={"owner": "A"},
    )
    control_repository.claim_futures_trigger(
        expected_revision=2,
        expected_parent_client_order_id=(
            "11111111-1111-4111-8111-111111111111"
        ),
        idempotency_key=owner_context.idempotency_key,
        actor_id=owner_context.actor_id,
        roles=owner_context.roles,
        correlation_id=owner_context.correlation_id,
        audit_id=owner_context.audit_id,
    )
    contender = replace(
        owner_context,
        actor_id="operator-B",
        idempotency_key="idem-contender-B",
        correlation_id="corr-contender-B",
        audit_id="77777777-7777-4777-8777-777777777777",
    )

    failures: list[tuple[str, int]] = []
    for _ in range(2):
        with pytest.raises(OperatorHotpointControlError) as failure:
            _run_once(
                service,
                expected_revision=3,
                context=contender,
            )
        failures.append(
            (
                failure.value.code,
                failure.value.http_status_code,
            )
        )

    assert failures == [
        ("operator_futures_hotpoint_trigger_claim_rejected", 409),
        ("operator_futures_hotpoint_trigger_claim_rejected", 409),
    ]
    assert control_repository.record.actor_id == "operator-run"
    assert control_repository.record.correlation_id == "corr-run"
    assert lifecycle_repository.record.cycles_used == 0
    assert exchange.calls == []


def test_goal13_preinvoke_unknown_create_does_not_offer_safe_closeout() -> None:
    control_repository = _ControlRepository()
    lifecycle_repository = _LifecycleRepository()
    lifecycle_repository.record = replace(
        lifecycle_repository.record,
        preview_outcome=AdminFuturesManualCallOutcome.ACCEPTED,
        preview_exchange_invoked=True,
        create_outcome=AdminFuturesManualCallOutcome.UNKNOWN,
        create_exchange_invoked=False,
        execution_claim_id="33333333-3333-4333-8333-333333333333",
        client_order_id="operator-futures-hotpoint-v2-child",
    )
    service = OperatorFuturesHotpointV2Service(
        control_service=_ControlService(control_repository),
        control_repository=control_repository,
        lifecycle_repository=lifecycle_repository,
        eligibility_reader_factory=lambda _binding: _EligibilityReader(),
        exchange_executor=_ExchangeExecutor(),
        closeout_executor=_TerminalCloseout(),
    )

    assert "SAFE_CLOSEOUT" not in service.read().allowed_actions


def test_goal13_default_lifecycle_factory_binds_portfolio_and_claim_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import database.operator_futures_manual_lifecycle as lifecycle_module

    captured: dict[str, object] = {}

    class _Repository:
        def __init__(self, _db, **kwargs):
            captured.update(kwargs)

        def ensure_schema(self):
            captured["schema_ready"] = True

    class _Control:
        @staticmethod
        def validate_futures_candidate_claim(**_kwargs):
            return None

        @staticmethod
        def validate_futures_create_invocation(**_kwargs):
            return None

        @staticmethod
        def validate_futures_preview_invocation(**_kwargs):
            return None

    monkeypatch.setattr(
        lifecycle_module,
        "_DEFAULT_HOTPOINT_REPOSITORY",
        None,
    )
    monkeypatch.setattr(
        lifecycle_module,
        "OperatorFuturesManualLifecycleRepository",
        _Repository,
    )
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_FUTURES_PORTFOLIO_ID",
        DEFAULT_PORTFOLIO_ID,
    )

    repository = (
        lifecycle_module
        .get_default_operator_futures_hotpoint_lifecycle_repository(
            control_repository=_Control(),
        )
    )

    assert isinstance(repository, _Repository)
    assert captured["configured_portfolio_id"] == DEFAULT_PORTFOLIO_ID
    assert captured["goal_id"] == FUTURES_HOTPOINT_GOAL_ID
    assert callable(captured["eligibility_evidence_validator"])
    assert callable(captured["claim_validator"])
    assert callable(captured["preview_invocation_validator"])
    assert callable(captured["create_invocation_validator"])
    assert captured["schema_ready"] is True
