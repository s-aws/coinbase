from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import TypeAdapter, ValidationError

from application.admin_api.operator_hotpoint_models import (
    OperatorFuturesHotpointCallReadback,
    OperatorFuturesHotpointReadback,
    OperatorHistoricalFuturesHotpointReadback,
    OperatorHotpointMutationResponse,
    OperatorHotpointReadbackResponse,
    OperatorHotpointRunRequestBody,
    OperatorHotpointSafeCloseoutRequestBody,
)


def _spot_run_payload() -> dict[str, object]:
    return {
        "domain": "SPOT",
        "confirm_bounded_trigger_evaluation": True,
        "acknowledge_unknown_outcome_consumes_create_allowance": True,
    }


def _futures_run_payload() -> dict[str, object]:
    return {
        "domain": "FUTURES",
        "expected_revision": 7,
        "expected_parent_client_order_id": (
            "11111111-1111-4111-8111-111111111111"
        ),
        "confirm_bounded_trigger_evaluation": True,
        "authorize_one_no_retry_six_category_cycle": True,
        "acknowledge_cycle_is_goal_global_and_limited_to_ten": True,
        "acknowledge_unsuccessful_or_unknown_cycle_fails_closed": True,
        "authorize_one_preview_and_conditional_identical_create": True,
        "acknowledge_unknown_preview_or_create_consumes_allowance": True,
        "acknowledge_create_requires_accepted_identical_preview": True,
    }


def _spot_closeout_payload() -> dict[str, object]:
    return {
        "domain": "SPOT",
        "confirm_exact_child_safe_closeout": True,
        "acknowledge_unknown_outcome_consumes_cancel_allowance": True,
    }


def _futures_closeout_payload() -> dict[str, object]:
    return {
        "domain": "FUTURES",
        "expected_revision": 11,
        "expected_child_client_order_id": (
            "22222222-2222-4222-8222-222222222222"
        ),
        "authorize_one_exact_no_retry_reconciliation": True,
        "acknowledge_unknown_reconciliation_consumes_allowance": True,
        "confirm_exact_child_safe_closeout": True,
        "acknowledge_cancel_only_exact_authoritatively_nonterminal_child": True,
        "acknowledge_unknown_outcome_consumes_cancel_allowance": True,
    }


def _call(
    *,
    outcome: str = "NOT_RUN",
    invoked: bool | None = False,
    consumed: bool = False,
) -> dict[str, object]:
    return {
        "outcome": outcome,
        "call_boundary_entered": invoked,
        "allowance_consumed": consumed,
        "allowance_remaining": 0 if consumed else 1,
    }


def _futures_readback_payload() -> dict[str, object]:
    return {
        "domain": "FUTURES",
        "type": "operator_hotpoint_control",
        "goal_id": "operator_futures_hotpoint_canonical_single_child_v2",
        "revision": 7,
        "environment": "local",
        "portfolio_profile_alias": "Default",
        "portfolio_profile_type": "DEFAULT",
        "product_scope": "AVP-20DEC30-CDE",
        "policy_side": "BUY",
        "order_type": "LIMIT_GTC",
        "post_only": True,
        "contract_count": "1",
        "max_submitted_notional_usdc": "100",
        "max_possible_execution_notional_usdc": "150",
        "max_turnover_notional_usdc": "300",
        "exact_size": "1",
        "strict_caps": True,
        "placement_execution_available": True,
        "cancel_execution_available": True,
        "kill_switch_state": "ENABLED",
        "window_state": "ARMED",
        "create_state": "NOT_CLAIMED",
        "cancel_state": "NOT_CLAIMED",
        "parent_client_order_id": (
            "11111111-1111-4111-8111-111111111111"
        ),
        "child_client_order_id": None,
        "side": "BUY",
        "window_started_at": "2026-07-26T12:00:00Z",
        "window_expires_at": "2026-07-26T12:01:00Z",
        "trigger_fill_count": 3,
        "trigger_evidence_sha256": "a" * 64,
        "window_id_sha256": "b" * 64,
        "cycles_used": 1,
        "cycles_remaining": 9,
        "active_cycle_number": None,
        "eligibility_outcome": "ELIGIBLE",
        "eligibility_diagnostic_code": (
            "operator_futures_hotpoint_exact_v3_eligible"
        ),
        "category_attempts": {
            "api_key_permissions": 1,
            "portfolio_catalog": 1,
            "product": 1,
            "best_bid_ask": 1,
            "futures_positions": 1,
            "futures_margin_collateral": 1,
        },
        "margin_subread_attempts": {
            "futures_balance_summary": 1,
            "intraday_margin_setting": 1,
            "current_margin_window_regular": 1,
            "current_margin_window_intraday": 1,
        },
        "latest_external_command": {
            "action": "RUN_ONCE",
            "status": "SUCCESS",
            "correlation_id": "corr-goal13-run",
            "request_revision": 7,
            "diagnostic_code": (
                "operator_futures_hotpoint_command_succeeded"
            ),
        },
        "candidate": {
            "product_id": "AVP-20DEC30-CDE",
            "side": "BUY",
            "order_type": "LIMIT_GTC",
            "post_only": True,
            "contract_count": "1",
            "limit_price": "4.99",
            "opening_reference_notional_usdc": "49.90",
            "maximum_exposure_reference_notional_usdc": "49.90",
            "buffered_close_reference_notional_usdc": "59.88",
            "branch_turnover_reference_notional_usdc": "109.78",
            "opening_cap_usdc": "100",
            "exposure_cap_usdc": "150",
            "turnover_cap_usdc": "300",
            "product_policy_revision": 1,
            "product_policy_sha256": "c" * 64,
            "hotpoint_session_compatibility": "OPEN_24X7_GTC",
            "observed_at": "2026-07-26T12:00:01Z",
        },
        "candidate_fresh_for_execution": True,
        "candidate_freshness_diagnostic_code": (
            "operator_futures_hotpoint_candidate_fresh"
        ),
        "candidate_sha256": "d" * 64,
        "portfolio_id_sha256": "e" * 64,
        "eligibility_evidence_sha256": "f" * 64,
        "execution_posture_ready": True,
        "execution_posture_diagnostic_code": (
            "operator_futures_hotpoint_execution_posture_ready"
        ),
        "preview": _call(),
        "preview_id_sha256": None,
        "create": _call(),
        "exchange_order_id_sha256": None,
        "reconciliation": _call(),
        "order_status": None,
        "authoritatively_nonterminal": None,
        "cancel_disposition": None,
        "cancel": _call(),
        "diagnostic_code": "operator_futures_hotpoint_trigger_ready",
        "allowed_actions": ["DISABLE", "DISARM", "RUN_ONCE"],
        "correlation_id": None,
        "audit_id": None,
        "updated_at": "2026-07-26T12:00:02Z",
        "raw_responses_included": False,
        "raw_preview_identifiers_included": False,
        "raw_exchange_order_identifiers_included": False,
        "private_identifiers_included": False,
        "exception_text_included": False,
        "browser_authority": "display_and_forward_only",
        "backend_authoritative": True,
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
    }


def test_spot_run_request_preserves_goal9_shape_exactly() -> None:
    request = TypeAdapter(OperatorHotpointRunRequestBody).validate_python(
        _spot_run_payload()
    )

    assert request.model_dump() == _spot_run_payload()

    broadened = {
        **_spot_run_payload(),
        "expected_revision": 1,
    }
    with pytest.raises(ValidationError):
        TypeAdapter(OperatorHotpointRunRequestBody).validate_python(broadened)


def test_futures_run_request_requires_revision_parent_and_exact_authority() -> None:
    request = TypeAdapter(OperatorHotpointRunRequestBody).validate_python(
        _futures_run_payload()
    )

    assert request.domain == "FUTURES"
    assert request.expected_revision == 7

    for field in (
        "expected_revision",
        "expected_parent_client_order_id",
        "authorize_one_no_retry_six_category_cycle",
        "acknowledge_cycle_is_goal_global_and_limited_to_ten",
        "acknowledge_unsuccessful_or_unknown_cycle_fails_closed",
        "authorize_one_preview_and_conditional_identical_create",
        "acknowledge_unknown_preview_or_create_consumes_allowance",
        "acknowledge_create_requires_accepted_identical_preview",
    ):
        missing = _futures_run_payload()
        missing.pop(field)
        with pytest.raises(ValidationError):
            TypeAdapter(OperatorHotpointRunRequestBody).validate_python(
                missing
            )

    denied = _futures_run_payload()
    denied["authorize_one_preview_and_conditional_identical_create"] = False
    with pytest.raises(ValidationError):
        TypeAdapter(OperatorHotpointRunRequestBody).validate_python(denied)


def test_spot_safe_closeout_request_preserves_goal9_shape_exactly() -> None:
    request = TypeAdapter(
        OperatorHotpointSafeCloseoutRequestBody
    ).validate_python(_spot_closeout_payload())

    assert request.model_dump() == _spot_closeout_payload()

    broadened = {
        **_spot_closeout_payload(),
        "authorize_one_exact_no_retry_reconciliation": True,
    }
    with pytest.raises(ValidationError):
        TypeAdapter(OperatorHotpointSafeCloseoutRequestBody).validate_python(
            broadened
        )


def test_futures_safe_closeout_requires_exact_child_reconciliation_authority() -> None:
    request = TypeAdapter(
        OperatorHotpointSafeCloseoutRequestBody
    ).validate_python(_futures_closeout_payload())

    assert request.domain == "FUTURES"
    assert request.expected_revision == 11

    for field in (
        "expected_revision",
        "expected_child_client_order_id",
        "authorize_one_exact_no_retry_reconciliation",
        "acknowledge_unknown_reconciliation_consumes_allowance",
        "confirm_exact_child_safe_closeout",
        "acknowledge_cancel_only_exact_authoritatively_nonterminal_child",
        "acknowledge_unknown_outcome_consumes_cancel_allowance",
    ):
        missing = _futures_closeout_payload()
        missing.pop(field)
        with pytest.raises(ValidationError):
            TypeAdapter(
                OperatorHotpointSafeCloseoutRequestBody
            ).validate_python(
                missing
            )


def test_goal13_readback_is_domain_safe_and_value_blind() -> None:
    readback = TypeAdapter(OperatorHotpointReadbackResponse).validate_python(
        _futures_readback_payload()
    )

    assert isinstance(readback, OperatorFuturesHotpointReadback)
    assert readback.goal_id == (
        "operator_futures_hotpoint_canonical_single_child_v2"
    )
    assert readback.portfolio_profile_alias == "Default"
    assert readback.product_scope == "AVP-20DEC30-CDE"
    assert readback.contract_count == "1"
    assert readback.preview.allowance_remaining == 1
    assert readback.raw_responses_included is False
    assert readback.raw_preview_identifiers_included is False
    assert readback.raw_exchange_order_identifiers_included is False

    unsafe = _futures_readback_payload()
    unsafe["raw_preview_id"] = "withheld"
    with pytest.raises(ValidationError):
        TypeAdapter(OperatorHotpointReadbackResponse).validate_python(unsafe)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("goal_id",), "operator_hotpoint_control_and_single_placement_v1"),
        (("portfolio_profile_alias",), "Test"),
        (("product_scope",), "BTC-USDC"),
        (("contract_count",), "2"),
        (("max_submitted_notional_usdc",), "100.01"),
        (("max_possible_execution_notional_usdc",), "149"),
        (("max_turnover_notional_usdc",), "299"),
        (("candidate_sha256",), "not-a-hash"),
        (("category_attempts", "unapproved_category"), 1),
        (("margin_subread_attempts", "unapproved_subread"), 1),
    ],
)
def test_goal13_readback_rejects_scope_or_evidence_drift(
    path: tuple[str, ...],
    value: object,
) -> None:
    payload = deepcopy(_futures_readback_payload())
    target: dict[str, object] = payload
    for segment in path[:-1]:
        target = target[segment]  # type: ignore[assignment]
    target[path[-1]] = value

    with pytest.raises(ValidationError):
        TypeAdapter(OperatorHotpointReadbackResponse).validate_python(payload)


def test_goal13_readback_rejects_incoherent_external_command_evidence() -> None:
    payload = _futures_readback_payload()
    payload["latest_external_command"] = {
        "action": "RUN_ONCE",
        "status": "UNKNOWN",
        "correlation_id": "corr-goal13-run",
        "request_revision": -1,
        "diagnostic_code": (
            "operator_futures_hotpoint_command_outcome_unknown"
        ),
    }
    with pytest.raises(ValidationError):
        TypeAdapter(OperatorHotpointReadbackResponse).validate_python(payload)


def test_goal13_readback_rejects_incoherent_cycle_and_call_accounting() -> None:
    payload = _futures_readback_payload()
    payload["cycles_remaining"] = 8
    with pytest.raises(ValidationError):
        TypeAdapter(OperatorHotpointReadbackResponse).validate_python(payload)

    payload = _futures_readback_payload()
    payload["preview"] = _call(
        outcome="CLAIMED",
        invoked=False,
        consumed=True,
    )
    payload["allowed_actions"] = ["DISABLE"]
    claimed = TypeAdapter(
        OperatorHotpointReadbackResponse
    ).validate_python(payload)
    assert claimed.preview.call_boundary_entered is False

    payload = _futures_readback_payload()
    payload["preview"] = _call(
        outcome="ACCEPTED",
        invoked=False,
        consumed=True,
    )
    payload["preview_id_sha256"] = "0" * 64
    payload["allowed_actions"] = ["DISABLE"]
    with pytest.raises(ValidationError):
        TypeAdapter(OperatorHotpointReadbackResponse).validate_python(payload)

    payload = _futures_readback_payload()
    payload["preview"] = _call(
        outcome="ACCEPTED",
        invoked=True,
        consumed=False,
    )
    with pytest.raises(ValidationError):
        TypeAdapter(OperatorHotpointReadbackResponse).validate_python(payload)


@pytest.mark.parametrize("outcome", ["CLAIMED", "REJECTED", "UNKNOWN"])
def test_goal13_consumed_nonaccepted_call_can_be_pre_boundary(
    outcome: str,
) -> None:
    call = OperatorFuturesHotpointCallReadback.model_validate(
        _call(
            outcome=outcome,
            invoked=False,
            consumed=True,
        )
    )

    assert call.allowance_consumed is True
    assert call.call_boundary_entered is False


def test_goal13_readback_requires_exact_category_and_trigger_accounting() -> None:
    payload = _futures_readback_payload()
    payload["category_attempts"] = {
        "api_key_permissions": 1,
        "portfolio_catalog": 1,
        "product": 1,
        "best_bid_ask": 1,
        "futures_positions": 1,
    }
    with pytest.raises(ValidationError):
        TypeAdapter(OperatorHotpointReadbackResponse).validate_python(payload)

    payload = _futures_readback_payload()
    payload["margin_subread_attempts"] = {
        "futures_balance_summary": 1,
        "intraday_margin_setting": 1,
        "current_margin_window_regular": 1,
    }
    with pytest.raises(ValidationError):
        TypeAdapter(OperatorHotpointReadbackResponse).validate_python(payload)

    payload = _futures_readback_payload()
    payload["margin_subread_attempts"] = {
        "futures_balance_summary": 1,
        "intraday_margin_setting": 1,
        "current_margin_window_regular": 0,
        "current_margin_window_intraday": 0,
    }
    payload["eligibility_outcome"] = "UNKNOWN"
    payload["candidate"] = None
    payload["candidate_fresh_for_execution"] = False
    payload["candidate_sha256"] = None
    payload["portfolio_id_sha256"] = None
    payload["eligibility_evidence_sha256"] = None
    payload["allowed_actions"] = ["DISABLE", "DISARM", "RUN_ONCE"]
    readback = TypeAdapter(
        OperatorHotpointReadbackResponse
    ).validate_python(payload)
    assert readback.margin_subread_attempts == {
        "futures_balance_summary": 1,
        "intraday_margin_setting": 1,
        "current_margin_window_regular": 0,
        "current_margin_window_intraday": 0,
    }

    payload = _futures_readback_payload()
    payload["trigger_fill_count"] = 2
    with pytest.raises(ValidationError):
        TypeAdapter(OperatorHotpointReadbackResponse).validate_python(payload)


def test_goal13_readback_rejects_candidate_and_action_authority_drift() -> None:
    payload = _futures_readback_payload()
    payload["candidate"] = None
    payload["candidate_fresh_for_execution"] = False
    payload["execution_posture_ready"] = False
    with pytest.raises(ValidationError):
        TypeAdapter(OperatorHotpointReadbackResponse).validate_python(payload)

    payload = _futures_readback_payload()
    payload["allowed_actions"] = ["SAFE_CLOSEOUT"]
    with pytest.raises(ValidationError):
        TypeAdapter(OperatorHotpointReadbackResponse).validate_python(payload)


def test_goal13_initial_run_action_does_not_require_preexisting_candidate() -> None:
    payload = _futures_readback_payload()
    payload["candidate"] = None
    payload["candidate_fresh_for_execution"] = False
    payload["candidate_sha256"] = None

    readback = TypeAdapter(
        OperatorHotpointReadbackResponse
    ).validate_python(payload)

    assert "RUN_ONCE" in readback.allowed_actions
    assert readback.candidate is None

    payload["preview"] = _call(
        outcome="UNKNOWN",
        invoked=True,
        consumed=True,
    )
    with pytest.raises(ValidationError):
        TypeAdapter(OperatorHotpointReadbackResponse).validate_python(payload)


def test_goal13_safe_closeout_action_requires_unused_exact_child_boundaries() -> None:
    payload = _futures_readback_payload()
    payload.update(
        {
            "allowed_actions": ["DISABLE", "SAFE_CLOSEOUT"],
            "create_state": "ACCEPTED",
            "child_client_order_id": (
                "22222222-2222-4222-8222-222222222222"
            ),
            "preview": _call(
                outcome="ACCEPTED",
                invoked=True,
                consumed=True,
            ),
            "preview_id_sha256": "1" * 64,
            "create": _call(
                outcome="ACCEPTED",
                invoked=True,
                consumed=True,
            ),
            "exchange_order_id_sha256": "2" * 64,
        }
    )

    readback = TypeAdapter(
        OperatorHotpointReadbackResponse
    ).validate_python(payload)
    assert "SAFE_CLOSEOUT" in readback.allowed_actions

    payload["reconciliation"] = _call(
        outcome="UNKNOWN",
        invoked=True,
        consumed=True,
    )
    with pytest.raises(ValidationError):
        TypeAdapter(OperatorHotpointReadbackResponse).validate_python(payload)


@pytest.mark.parametrize(
    ("create_outcome", "create_invoked", "posture_ready"),
    [
        ("UNKNOWN", False, True),
        ("UNKNOWN", None, True),
        ("ACCEPTED", True, False),
    ],
)
def test_goal13_safe_closeout_rejects_unentered_create_or_unready_posture(
    create_outcome: str,
    create_invoked: bool | None,
    posture_ready: bool,
) -> None:
    payload = _futures_readback_payload()
    payload.update(
        {
            "allowed_actions": ["DISABLE", "SAFE_CLOSEOUT"],
            "create_state": create_outcome,
            "child_client_order_id": (
                "22222222-2222-4222-8222-222222222222"
            ),
            "preview": _call(
                outcome="ACCEPTED",
                invoked=True,
                consumed=True,
            ),
            "preview_id_sha256": "1" * 64,
            "create": _call(
                outcome=create_outcome,
                invoked=create_invoked,
                consumed=True,
            ),
            "exchange_order_id_sha256": (
                "2" * 64 if create_outcome == "ACCEPTED" else None
            ),
            "execution_posture_ready": posture_ready,
        }
    )

    with pytest.raises(ValidationError):
        TypeAdapter(OperatorHotpointReadbackResponse).validate_python(payload)


def _accepted_create_readback_payload() -> dict[str, object]:
    payload = _futures_readback_payload()
    payload.update(
        {
            "allowed_actions": ["DISABLE"],
            "create_state": "ACCEPTED",
            "child_client_order_id": (
                "22222222-2222-4222-8222-222222222222"
            ),
            "preview": _call(
                outcome="ACCEPTED",
                invoked=True,
                consumed=True,
            ),
            "preview_id_sha256": "1" * 64,
            "create": _call(
                outcome="ACCEPTED",
                invoked=True,
                consumed=True,
            ),
            "exchange_order_id_sha256": "2" * 64,
        }
    )
    return payload


def test_goal13_terminal_reconciliation_reports_cancel_not_required() -> None:
    payload = _accepted_create_readback_payload()
    payload.update(
        {
            "reconciliation": _call(
                outcome="ACCEPTED",
                invoked=True,
                consumed=True,
            ),
            "order_status": "FILLED",
            "authoritatively_nonterminal": False,
            "cancel_disposition": "NOT_REQUIRED",
            "cancel_state": "NOT_REQUIRED",
        }
    )

    readback = TypeAdapter(
        OperatorHotpointReadbackResponse
    ).validate_python(payload)
    assert readback.cancel_disposition == "NOT_REQUIRED"
    assert readback.cancel.outcome.value == "NOT_RUN"
    assert "SAFE_CLOSEOUT" not in readback.allowed_actions

    payload["cancel_disposition"] = "REQUIRED"
    with pytest.raises(ValidationError):
        TypeAdapter(OperatorHotpointReadbackResponse).validate_python(payload)


def test_goal13_nonterminal_reconciliation_reports_cancel_required() -> None:
    payload = _accepted_create_readback_payload()
    payload.update(
        {
            "reconciliation": _call(
                outcome="ACCEPTED",
                invoked=True,
                consumed=True,
            ),
            "order_status": "OPEN",
            "authoritatively_nonterminal": True,
            "cancel_disposition": "REQUIRED",
        }
    )

    readback = TypeAdapter(
        OperatorHotpointReadbackResponse
    ).validate_python(payload)
    assert readback.cancel_disposition == "REQUIRED"

    payload["cancel_disposition"] = None
    with pytest.raises(ValidationError):
        TypeAdapter(OperatorHotpointReadbackResponse).validate_python(payload)


@pytest.mark.parametrize("reconciled", [False, True])
def test_goal13_foreign_cancel_seal_is_known_fail_closed_readback(
    reconciled: bool,
) -> None:
    payload = _accepted_create_readback_payload()
    payload.update(
        {
            "cancel_disposition": "ALREADY_CANCEL_REQUESTED",
            "diagnostic_code": (
                "operator_futures_cancel_invocation_already_sealed"
            ),
        }
    )
    if reconciled:
        payload.update(
            {
                "reconciliation": _call(
                    outcome="ACCEPTED",
                    invoked=True,
                    consumed=True,
                ),
                "order_status": "OPEN",
                "authoritatively_nonterminal": True,
            }
        )

    readback = TypeAdapter(
        OperatorHotpointReadbackResponse
    ).validate_python(payload)

    assert readback.cancel_disposition == "ALREADY_CANCEL_REQUESTED"
    assert readback.cancel.outcome.value == "NOT_RUN"
    assert readback.cancel.allowance_remaining == 1
    assert "SAFE_CLOSEOUT" not in readback.allowed_actions

    payload["diagnostic_code"] = "operator_futures_hotpoint_trigger_ready"
    with pytest.raises(ValidationError):
        TypeAdapter(OperatorHotpointReadbackResponse).validate_python(payload)


def test_goal13_accepted_own_cancel_preserves_required_reconciliation_truth(
) -> None:
    payload = _accepted_create_readback_payload()
    payload.update(
        {
            "reconciliation": _call(
                outcome="ACCEPTED",
                invoked=True,
                consumed=True,
            ),
            "order_status": "OPEN",
            "authoritatively_nonterminal": True,
            "cancel_disposition": "REQUIRED",
            "cancel_state": "ACCEPTED",
            "cancel": _call(
                outcome="ACCEPTED",
                invoked=True,
                consumed=True,
            ),
        }
    )

    readback = TypeAdapter(
        OperatorHotpointReadbackResponse
    ).validate_python(payload)

    assert readback.cancel_disposition == "REQUIRED"
    assert readback.cancel.outcome.value == "ACCEPTED"
    assert readback.cancel.allowance_remaining == 0
    assert "SAFE_CLOSEOUT" not in readback.allowed_actions


@pytest.mark.parametrize(
    ("order_status", "cancel_disposition"),
    [
        ("PENDING", "DEFERRED_TRANSITIONAL"),
        ("QUEUED", "DEFERRED_TRANSITIONAL"),
        ("EDIT_QUEUED", "DEFERRED_TRANSITIONAL"),
        ("CANCEL_QUEUED", "ALREADY_CANCEL_REQUESTED"),
    ],
)
def test_goal13_transitional_reconciliation_is_truthful_and_never_recancels(
    order_status: str,
    cancel_disposition: str,
) -> None:
    payload = _accepted_create_readback_payload()
    payload.update(
        {
            "reconciliation": _call(
                outcome="ACCEPTED",
                invoked=True,
                consumed=True,
            ),
            "order_status": order_status,
            "authoritatively_nonterminal": True,
            "cancel_disposition": cancel_disposition,
        }
    )

    readback = TypeAdapter(
        OperatorHotpointReadbackResponse
    ).validate_python(payload)

    assert readback.authoritatively_nonterminal is True
    assert readback.cancel_disposition == cancel_disposition
    assert readback.cancel.outcome.value == "NOT_RUN"
    assert readback.cancel.allowance_remaining == 1
    assert "SAFE_CLOSEOUT" not in readback.allowed_actions

    payload["cancel_disposition"] = "REQUIRED"
    with pytest.raises(ValidationError):
        TypeAdapter(OperatorHotpointReadbackResponse).validate_python(payload)


def test_goal13_cancel_disposition_is_absent_before_accepted_reconciliation() -> None:
    payload = _accepted_create_readback_payload()
    payload["cancel_disposition"] = "NOT_REQUIRED"
    with pytest.raises(ValidationError):
        TypeAdapter(OperatorHotpointReadbackResponse).validate_python(payload)

    payload = _accepted_create_readback_payload()
    payload["cancel_state"] = "NOT_REQUIRED"
    with pytest.raises(ValidationError):
        TypeAdapter(OperatorHotpointReadbackResponse).validate_python(payload)


def test_historical_goal9_futures_readback_remains_representable() -> None:
    payload = {
        "domain": "FUTURES",
        "goal_id": "operator_hotpoint_control_and_single_placement_v1",
        "revision": 0,
        "environment": "local",
        "portfolio_profile_alias": "Default",
        "product_scope": "AVP-20DEC30-CDE",
        "max_submitted_notional_usdc": "100",
        "max_possible_execution_notional_usdc": "150",
        "max_turnover_notional_usdc": "300",
        "exact_size": "1",
        "placement_execution_available": False,
        "cancel_execution_available": False,
        "rate_limit": {
            "create_claims_consumed": 0,
            "create_claims_remaining": 1,
            "consumed_by_domain": None,
        },
        "recent_placement": None,
        "kill_switch_state": "DISABLED",
        "window_state": "NONE",
        "create_state": "NOT_CLAIMED",
        "cancel_state": "NOT_CLAIMED",
        "parent_client_order_id": None,
        "child_client_order_id": None,
        "side": None,
        "window_started_at": None,
        "window_expires_at": None,
        "diagnostic_code": "operator_hotpoint_control_ready",
        "allowed_actions": ["ENABLE"],
        "create_claim_consumed": False,
        "cancel_claim_consumed": False,
        "create_exchange_invoked": None,
        "cancel_exchange_invoked": None,
        "correlation_id": None,
        "audit_id": None,
        "updated_at": None,
    }

    readback = TypeAdapter(
        OperatorHotpointReadbackResponse
    ).validate_python(payload)

    assert isinstance(readback, OperatorHistoricalFuturesHotpointReadback)
    assert readback.goal_id == (
        "operator_hotpoint_control_and_single_placement_v1"
    )


def test_mutation_union_preserves_goal9_and_selects_goal13_readback() -> None:
    response = OperatorHotpointMutationResponse.model_validate(
        {
            "status": "accepted",
            "service_method": "run_once",
            "operator_intent": "run_operator_hotpoint_once",
            "control": _futures_readback_payload(),
            "correlation_id": "correlation-goal13",
            "idempotency_key": "idempotency-goal13",
            "audit_id": "audit-goal13",
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
        }
    )

    assert isinstance(response.control, OperatorFuturesHotpointReadback)


def test_goal13_contracts_publish_discriminated_domain_unions() -> None:
    run_schema = TypeAdapter(OperatorHotpointRunRequestBody).json_schema()
    closeout_schema = TypeAdapter(
        OperatorHotpointSafeCloseoutRequestBody
    ).json_schema()
    readback_schema = TypeAdapter(
        OperatorHotpointReadbackResponse
    ).json_schema()

    for schema in (run_schema, closeout_schema):
        assert schema["discriminator"]["propertyName"] == "domain"
        assert len(schema["oneOf"]) == 2

    assert len(readback_schema["anyOf"]) == 2

    def assert_string_discriminator_mappings(value: object) -> None:
        if isinstance(value, dict):
            discriminator = value.get("discriminator")
            if isinstance(discriminator, dict):
                mapping = discriminator.get("mapping", {})
                assert isinstance(mapping, dict)
                assert all(
                    isinstance(reference, str)
                    for reference in mapping.values()
                )
            for nested in value.values():
                assert_string_discriminator_mappings(nested)
        elif isinstance(value, list):
            for nested in value:
                assert_string_discriminator_mappings(nested)

    assert_string_discriminator_mappings(readback_schema)
