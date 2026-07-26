"""Public, identifier-minimized contracts for Hotpoint Operations."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.enums import (
    AdminFuturesManualCallOutcome,
    AdminFuturesManualEligibilityOutcome,
)

from .operator_hotpoint_control import (
    HOTPOINT_GOAL_ID,
    HotpointCancelState,
    HotpointControlAction,
    HotpointCreateState,
    HotpointKillSwitchState,
    HotpointWindowState,
)

_FUTURES_HOTPOINT_CANCEL_DISPOSITION_BY_ORDER_STATUS = {
    "OPEN": "REQUIRED",
    "PENDING": "DEFERRED_TRANSITIONAL",
    "QUEUED": "DEFERRED_TRANSITIONAL",
    "EDIT_QUEUED": "DEFERRED_TRANSITIONAL",
    "CANCEL_QUEUED": "ALREADY_CANCEL_REQUESTED",
    "FILLED": "NOT_REQUIRED",
    "CANCELLED": "NOT_REQUIRED",
    "EXPIRED": "NOT_REQUIRED",
    "FAILED": "NOT_REQUIRED",
}
_FUTURES_HOTPOINT_NONTERMINAL_ORDER_STATUSES = {
    "OPEN",
    "PENDING",
    "QUEUED",
    "EDIT_QUEUED",
    "CANCEL_QUEUED",
}


class OperatorHotpointControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: Literal["SPOT", "FUTURES"]
    action: HotpointControlAction
    expected_revision: int = Field(ge=0)
    confirm_control_action: bool
    parent_client_order_id: str | None = Field(default=None, min_length=1)
    authorize_one_bounded_trigger_window: bool = False
    acknowledge_unknown_outcome_consumes_create_allowance: bool = False
    acknowledge_backend_derives_child_terms: bool = False


class OperatorHotpointRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: Literal["SPOT", "FUTURES"]
    confirm_bounded_trigger_evaluation: bool
    acknowledge_unknown_outcome_consumes_create_allowance: bool


class OperatorSpotHotpointRunRequest(OperatorHotpointRunRequest):
    domain: Literal["SPOT"]


class OperatorFuturesHotpointRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: Literal["FUTURES"]
    expected_revision: int = Field(ge=0)
    expected_parent_client_order_id: str = Field(
        min_length=1,
        max_length=255,
    )
    confirm_bounded_trigger_evaluation: Literal[True]
    authorize_one_no_retry_six_category_cycle: Literal[True]
    acknowledge_cycle_is_goal_global_and_limited_to_ten: Literal[True]
    acknowledge_unsuccessful_or_unknown_cycle_fails_closed: Literal[True]
    authorize_one_preview_and_conditional_identical_create: Literal[True]
    acknowledge_unknown_preview_or_create_consumes_allowance: Literal[True]
    acknowledge_create_requires_accepted_identical_preview: Literal[True]


OperatorHotpointRunRequestBody = Annotated[
    OperatorSpotHotpointRunRequest | OperatorFuturesHotpointRunRequest,
    Field(discriminator="domain"),
]


class OperatorHotpointSafeCloseoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: Literal["SPOT", "FUTURES"]
    confirm_exact_child_safe_closeout: bool
    acknowledge_unknown_outcome_consumes_cancel_allowance: bool


class OperatorSpotHotpointSafeCloseoutRequest(
    OperatorHotpointSafeCloseoutRequest
):
    domain: Literal["SPOT"]


class OperatorFuturesHotpointSafeCloseoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: Literal["FUTURES"]
    expected_revision: int = Field(ge=0)
    expected_child_client_order_id: str = Field(
        min_length=1,
        max_length=255,
    )
    confirm_exact_child_safe_closeout: Literal[True]
    authorize_one_exact_no_retry_reconciliation: Literal[True]
    acknowledge_unknown_reconciliation_consumes_allowance: Literal[True]
    acknowledge_cancel_only_exact_authoritatively_nonterminal_child: (
        Literal[True]
    )
    acknowledge_unknown_outcome_consumes_cancel_allowance: Literal[True]


OperatorHotpointSafeCloseoutRequestBody = Annotated[
    OperatorSpotHotpointSafeCloseoutRequest
    | OperatorFuturesHotpointSafeCloseoutRequest,
    Field(discriminator="domain"),
]


class OperatorHotpointParentItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: Literal["SPOT", "FUTURES"]
    client_order_id: str
    product_id: Literal["BTC-USDC", "AVP-20DEC30-CDE"]
    side: Literal["BUY", "SELL"]
    status: Literal["OPEN"]


class OperatorHotpointParentListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: Literal["SPOT", "FUTURES"]
    type: Literal["operator_hotpoint_eligible_parent_list"] = (
        "operator_hotpoint_eligible_parent_list"
    )
    items: list[OperatorHotpointParentItem]
    returned_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    portfolio_profile_alias: Literal["Test", "Default"]
    product_scope: Literal["BTC-USDC", "AVP-20DEC30-CDE"]
    live_coinbase_orders_ran: bool = False


class OperatorHotpointRateLimitReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["GOAL_GLOBAL"] = "GOAL_GLOBAL"
    create_cap: Literal[1] = 1
    create_claims_consumed: int = Field(ge=0, le=1)
    create_claims_remaining: int = Field(ge=0, le=1)
    consumed_by_domain: Literal["SPOT", "FUTURES"] | None
    trigger_window_seconds: Literal[60] = 60


class OperatorHotpointRecentPlacementReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: Literal["SPOT", "FUTURES"]
    parent_client_order_id: str
    child_client_order_id: str | None
    create_state: Literal["CLAIMED", "ACCEPTED", "REJECTED", "UNKNOWN"]
    create_exchange_invoked: bool | None
    diagnostic_code: str
    updated_at: str


class OperatorHotpointReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: Literal["SPOT", "FUTURES"]
    type: Literal["operator_hotpoint_control"] = "operator_hotpoint_control"
    goal_id: Literal["operator_hotpoint_control_and_single_placement_v1"] = (
        HOTPOINT_GOAL_ID
    )
    revision: int = Field(ge=0)
    environment: str
    portfolio_profile_alias: Literal["Test", "Default"]
    product_scope: Literal["BTC-USDC", "AVP-20DEC30-CDE"]
    max_submitted_notional_usdc: str
    max_possible_execution_notional_usdc: str
    max_turnover_notional_usdc: str | None
    exact_size: str | None
    placement_execution_available: bool
    cancel_execution_available: bool
    rate_limit: OperatorHotpointRateLimitReadback
    recent_placement: OperatorHotpointRecentPlacementReadback | None
    kill_switch_state: HotpointKillSwitchState
    window_state: HotpointWindowState
    create_state: HotpointCreateState
    cancel_state: HotpointCancelState
    parent_client_order_id: str | None
    child_client_order_id: str | None
    side: Literal["BUY", "SELL"] | None
    window_started_at: str | None
    window_expires_at: str | None
    diagnostic_code: str
    allowed_actions: list[
        Literal[
            "ENABLE",
            "DISABLE",
            "ARM",
            "DISARM",
            "RUN_ONCE",
            "SAFE_CLOSEOUT",
        ]
    ]
    create_claim_consumed: bool
    cancel_claim_consumed: bool
    create_exchange_invoked: bool | None
    cancel_exchange_invoked: bool | None
    correlation_id: str | None
    audit_id: str | None
    updated_at: str | None
    browser_authority: Literal["display_and_forward_only"] = (
        "display_and_forward_only"
    )
    backend_authoritative: bool = True
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False


class OperatorSpotHotpointReadback(OperatorHotpointReadback):
    """The completed Goal 9 Spot contract without Goal 13 requirements."""

    domain: Literal["SPOT"]


class OperatorHistoricalFuturesHotpointReadback(OperatorHotpointReadback):
    """Historical Goal 9 Futures evidence, never Goal 13 authority."""

    domain: Literal["FUTURES"]
    portfolio_profile_alias: Literal["Default"]
    product_scope: Literal["AVP-20DEC30-CDE"]


class OperatorFuturesHotpointCandidateReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: Literal["AVP-20DEC30-CDE"]
    side: Literal["BUY"]
    order_type: Literal["LIMIT_GTC"]
    post_only: Literal[True]
    contract_count: Literal["1"]
    limit_price: str
    opening_reference_notional_usdc: str
    maximum_exposure_reference_notional_usdc: str
    buffered_close_reference_notional_usdc: str
    branch_turnover_reference_notional_usdc: str
    opening_cap_usdc: Literal["100"]
    exposure_cap_usdc: Literal["150"]
    turnover_cap_usdc: Literal["300"]
    product_policy_revision: Literal[1]
    product_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hotpoint_session_compatibility: Literal["OPEN_24X7_GTC"]
    observed_at: str


class OperatorFuturesHotpointCallReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: AdminFuturesManualCallOutcome
    call_boundary_entered: bool | None
    allowance_consumed: bool
    allowance_remaining: int = Field(ge=0, le=1)

    @model_validator(mode="after")
    def accounting_is_coherent(
        self,
    ) -> "OperatorFuturesHotpointCallReadback":
        expected_remaining = 0 if self.allowance_consumed else 1
        if (
            self.allowance_remaining != expected_remaining
            or (
                self.outcome is AdminFuturesManualCallOutcome.NOT_RUN
                and self.allowance_consumed
            )
            or (
                self.outcome is not AdminFuturesManualCallOutcome.NOT_RUN
                and not self.allowance_consumed
            )
            or (
                self.outcome is AdminFuturesManualCallOutcome.ACCEPTED
                and self.call_boundary_entered is not True
            )
            or (
                self.call_boundary_entered is True
                and not self.allowance_consumed
            )
        ):
            raise ValueError(
                "operator_futures_hotpoint_call_accounting_invalid"
            )
        return self


class OperatorFuturesHotpointExternalCommandReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["RUN_ONCE", "SAFE_CLOSEOUT"]
    status: Literal["IN_PROGRESS", "SUCCESS", "FAILED", "UNKNOWN"]
    correlation_id: str = Field(min_length=1, max_length=255)
    request_revision: int | None = Field(default=None, ge=0)
    diagnostic_code: str = Field(min_length=1, max_length=128)


_FUTURES_HOTPOINT_CATEGORY_NAMES = frozenset(
    {
        "api_key_permissions",
        "portfolio_catalog",
        "product",
        "best_bid_ask",
        "futures_positions",
        "futures_margin_collateral",
    }
)
_FUTURES_HOTPOINT_MARGIN_SUBREAD_NAMES = frozenset(
    {
        "futures_balance_summary",
        "intraday_margin_setting",
        "current_margin_window_regular",
        "current_margin_window_intraday",
    }
)


class OperatorFuturesHotpointReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: Literal["FUTURES"]
    type: Literal["operator_hotpoint_control"] = "operator_hotpoint_control"
    goal_id: Literal[
        "operator_futures_hotpoint_canonical_single_child_v2"
    ]
    revision: int = Field(ge=0)
    environment: str
    portfolio_profile_alias: Literal["Default"] = "Default"
    portfolio_profile_type: Literal["DEFAULT"] = "DEFAULT"
    product_scope: Literal["AVP-20DEC30-CDE"] = "AVP-20DEC30-CDE"
    policy_side: Literal["BUY"] = "BUY"
    order_type: Literal["LIMIT_GTC"] = "LIMIT_GTC"
    post_only: Literal[True] = True
    contract_count: Literal["1"] = "1"
    max_submitted_notional_usdc: Literal["100"] = "100"
    max_possible_execution_notional_usdc: Literal["150"] = "150"
    max_turnover_notional_usdc: Literal["300"] = "300"
    exact_size: Literal["1"] = "1"
    strict_caps: Literal[True] = True
    placement_execution_available: bool
    cancel_execution_available: bool
    kill_switch_state: HotpointKillSwitchState
    window_state: HotpointWindowState
    create_state: HotpointCreateState
    cancel_state: HotpointCancelState
    parent_client_order_id: str | None
    child_client_order_id: str | None
    side: Literal["BUY"] | None
    window_started_at: str | None
    window_expires_at: str | None
    trigger_fill_count: int = Field(ge=0, le=3)
    trigger_evidence_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    window_id_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    cycles_used: int = Field(ge=0, le=10)
    cycles_remaining: int = Field(ge=0, le=10)
    active_cycle_number: int | None = Field(default=None, ge=1, le=10)
    eligibility_outcome: AdminFuturesManualEligibilityOutcome | None
    eligibility_diagnostic_code: str
    category_attempts: dict[str, int]
    margin_subread_attempts: dict[str, int]
    latest_external_command: (
        OperatorFuturesHotpointExternalCommandReadback | None
    )
    candidate: OperatorFuturesHotpointCandidateReadback | None
    candidate_fresh_for_execution: bool
    candidate_freshness_diagnostic_code: str
    candidate_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    portfolio_id_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    eligibility_evidence_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    execution_posture_ready: bool
    execution_posture_diagnostic_code: str
    preview: OperatorFuturesHotpointCallReadback
    preview_id_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    create: OperatorFuturesHotpointCallReadback
    exchange_order_id_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    reconciliation: OperatorFuturesHotpointCallReadback
    order_status: str | None
    authoritatively_nonterminal: bool | None
    cancel_disposition: (
        Literal[
            "REQUIRED",
            "NOT_REQUIRED",
            "DEFERRED_TRANSITIONAL",
            "ALREADY_CANCEL_REQUESTED",
        ]
        | None
    )
    cancel: OperatorFuturesHotpointCallReadback
    diagnostic_code: str
    allowed_actions: list[
        Literal[
            "ENABLE",
            "DISABLE",
            "ARM",
            "DISARM",
            "RUN_ONCE",
            "SAFE_CLOSEOUT",
        ]
    ]
    correlation_id: str | None
    audit_id: str | None
    updated_at: str | None
    raw_responses_included: Literal[False] = False
    raw_preview_identifiers_included: Literal[False] = False
    raw_exchange_order_identifiers_included: Literal[False] = False
    private_identifiers_included: Literal[False] = False
    exception_text_included: Literal[False] = False
    browser_authority: Literal["display_and_forward_only"] = (
        "display_and_forward_only"
    )
    backend_authoritative: Literal[True] = True
    live_exchange_submitted: bool = False
    live_coinbase_orders_ran: bool = False

    @model_validator(mode="after")
    def lifecycle_accounting_is_coherent(
        self,
    ) -> "OperatorFuturesHotpointReadback":
        run_once_allowed = "RUN_ONCE" in self.allowed_actions
        safe_closeout_allowed = "SAFE_CLOSEOUT" in self.allowed_actions
        foreign_cancel_seal = (
            self.cancel_disposition == "ALREADY_CANCEL_REQUESTED"
            and self.cancel.outcome
            is AdminFuturesManualCallOutcome.NOT_RUN
            and self.diagnostic_code
            == "operator_futures_cancel_invocation_already_sealed"
        )
        if (
            self.cycles_used + self.cycles_remaining != 10
            or set(self.category_attempts)
            != _FUTURES_HOTPOINT_CATEGORY_NAMES
            or any(
                type(attempts) is not int or attempts not in {0, 1}
                for attempts in self.category_attempts.values()
            )
            or set(self.margin_subread_attempts)
            != _FUTURES_HOTPOINT_MARGIN_SUBREAD_NAMES
            or any(
                type(attempts) is not int or attempts not in {0, 1}
                for attempts in self.margin_subread_attempts.values()
            )
            or (
                any(self.margin_subread_attempts.values())
                and self.category_attempts[
                    "futures_margin_collateral"
                ]
                != 1
            )
            or (
                self.eligibility_outcome
                is AdminFuturesManualEligibilityOutcome.ELIGIBLE
                and (
                    any(
                        attempts != 1
                        for attempts in self.category_attempts.values()
                    )
                    or any(
                        attempts != 1
                        for attempts in self.margin_subread_attempts.values()
                    )
                )
            )
            or (
                self.trigger_fill_count == 3
                and self.trigger_evidence_sha256 is None
            )
            or (
                self.trigger_fill_count < 3
                and self.trigger_evidence_sha256 is not None
            )
            or (
                self.candidate is not None
                and (
                    self.candidate_sha256 is None
                    or self.portfolio_id_sha256 is None
                    or self.eligibility_evidence_sha256 is None
                    or self.trigger_evidence_sha256 is None
                )
            )
            or (
                self.candidate is None
                and (
                    self.candidate_fresh_for_execution
                    or self.candidate_sha256 is not None
                )
            )
            or (
                self.candidate_fresh_for_execution
                and self.candidate is None
            )
            or (
                self.preview.outcome
                is AdminFuturesManualCallOutcome.ACCEPTED
                and self.preview_id_sha256 is None
            )
            or (
                self.preview.outcome
                is not AdminFuturesManualCallOutcome.ACCEPTED
                and self.preview_id_sha256 is not None
            )
            or (
                self.create.allowance_consumed
                and self.preview.outcome
                is not AdminFuturesManualCallOutcome.ACCEPTED
            )
            or (
                self.reconciliation.allowance_consumed
                and self.create.outcome
                not in {
                    AdminFuturesManualCallOutcome.ACCEPTED,
                    AdminFuturesManualCallOutcome.UNKNOWN,
                }
            )
            or (
                self.authoritatively_nonterminal is not None
                and self.reconciliation.outcome
                is not AdminFuturesManualCallOutcome.ACCEPTED
            )
            or (
                self.reconciliation.outcome
                is AdminFuturesManualCallOutcome.ACCEPTED
                and (
                    self.order_status is None
                    or self.authoritatively_nonterminal is None
                )
            )
            or (
                self.reconciliation.outcome
                is not AdminFuturesManualCallOutcome.ACCEPTED
                and (
                    self.order_status is not None
                    or self.authoritatively_nonterminal is not None
                    or (
                        self.cancel_disposition is not None
                        and not foreign_cancel_seal
                    )
                )
            )
            or (
                self.reconciliation.outcome
                is AdminFuturesManualCallOutcome.ACCEPTED
                and (
                    self.order_status
                    not in _FUTURES_HOTPOINT_CANCEL_DISPOSITION_BY_ORDER_STATUS
                    or self.authoritatively_nonterminal
                    is not (
                        self.order_status
                        in _FUTURES_HOTPOINT_NONTERMINAL_ORDER_STATUSES
                    )
                    or (
                        self.cancel_disposition
                        != _FUTURES_HOTPOINT_CANCEL_DISPOSITION_BY_ORDER_STATUS.get(
                            self.order_status
                        )
                        and not (
                            foreign_cancel_seal
                            and self.authoritatively_nonterminal is True
                        )
                    )
                )
            )
            or (
                self.cancel_disposition == "NOT_REQUIRED"
                and (
                    self.cancel_state is not HotpointCancelState.NOT_REQUIRED
                    or self.cancel.outcome
                    is not AdminFuturesManualCallOutcome.NOT_RUN
                    or self.cancel.allowance_consumed
                    or "SAFE_CLOSEOUT" in self.allowed_actions
                )
            )
            or (
                self.cancel_state is HotpointCancelState.NOT_REQUIRED
                and self.cancel_disposition != "NOT_REQUIRED"
            )
            or (
                self.cancel_disposition
                in {
                    "DEFERRED_TRANSITIONAL",
                    "ALREADY_CANCEL_REQUESTED",
                }
                and (
                    self.cancel_state is not HotpointCancelState.NOT_CLAIMED
                    or self.cancel.outcome
                    is not AdminFuturesManualCallOutcome.NOT_RUN
                    or self.cancel.allowance_consumed
                    or "SAFE_CLOSEOUT" in self.allowed_actions
                )
            )
            or (
                self.cancel.allowance_consumed
                and (
                    self.reconciliation.outcome
                    is not AdminFuturesManualCallOutcome.ACCEPTED
                    or self.authoritatively_nonterminal is not True
                )
            )
            or (
                run_once_allowed
                and (
                    self.kill_switch_state
                    is not HotpointKillSwitchState.ENABLED
                    or self.window_state is not HotpointWindowState.ARMED
                    or not self.parent_client_order_id
                    or self.trigger_fill_count != 3
                    or self.trigger_evidence_sha256 is None
                    or self.cycles_remaining < 1
                    or self.preview.allowance_consumed
                    or self.create.allowance_consumed
                    or not self.placement_execution_available
                    or not self.execution_posture_ready
                )
            )
            or (
                safe_closeout_allowed
                and (
                    not self.child_client_order_id
                    or self.create.outcome
                    not in {
                        AdminFuturesManualCallOutcome.ACCEPTED,
                        AdminFuturesManualCallOutcome.UNKNOWN,
                    }
                    or (
                        self.create.outcome
                        is AdminFuturesManualCallOutcome.UNKNOWN
                        and self.create.call_boundary_entered is not True
                    )
                    or self.reconciliation.allowance_consumed
                    or self.cancel.allowance_consumed
                    or not self.cancel_execution_available
                    or not self.execution_posture_ready
                )
            )
        ):
            raise ValueError(
                "operator_futures_hotpoint_readback_accounting_invalid"
            )
        return self


OperatorFuturesHotpointReadbackResponse = Annotated[
    OperatorHistoricalFuturesHotpointReadback
    | OperatorFuturesHotpointReadback,
    Field(discriminator="goal_id"),
]


OperatorHotpointReadbackResponse = (
    OperatorSpotHotpointReadback
    | OperatorFuturesHotpointReadbackResponse
)


class OperatorHotpointMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["operator_hotpoint_mutation"] = (
        "operator_hotpoint_mutation"
    )
    status: Literal["accepted"]
    service_method: Literal["control", "run_once", "safe_closeout"]
    operator_intent: str
    control: OperatorHotpointReadback | OperatorFuturesHotpointReadback
    correlation_id: str
    idempotency_key: str
    audit_id: str
    live_exchange_submitted: bool
    live_coinbase_orders_ran: bool


__all__ = [
    "OperatorFuturesHotpointCallReadback",
    "OperatorFuturesHotpointCandidateReadback",
    "OperatorFuturesHotpointExternalCommandReadback",
    "OperatorFuturesHotpointReadback",
    "OperatorFuturesHotpointReadbackResponse",
    "OperatorFuturesHotpointRunRequest",
    "OperatorFuturesHotpointSafeCloseoutRequest",
    "OperatorHistoricalFuturesHotpointReadback",
    "OperatorHotpointControlRequest",
    "OperatorHotpointMutationResponse",
    "OperatorHotpointParentItem",
    "OperatorHotpointParentListResponse",
    "OperatorHotpointRateLimitReadback",
    "OperatorHotpointRecentPlacementReadback",
    "OperatorHotpointReadback",
    "OperatorHotpointReadbackResponse",
    "OperatorHotpointRunRequest",
    "OperatorHotpointRunRequestBody",
    "OperatorHotpointSafeCloseoutRequest",
    "OperatorHotpointSafeCloseoutRequestBody",
    "OperatorSpotHotpointReadback",
    "OperatorSpotHotpointRunRequest",
    "OperatorSpotHotpointSafeCloseoutRequest",
]
