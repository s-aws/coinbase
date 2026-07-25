"""Generated-contract source models for the Goal 10 Futures workspace."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.enums import (
    AdminFuturesManualCallOutcome,
    AdminFuturesManualEligibilityOutcome,
)


class OperatorFuturesManualCandidateReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: Literal["AVP-20DEC30-CDE"]
    side: Literal["BUY"]
    order_type: Literal["LIMIT_GTC"]
    post_only: Literal["true"]
    contract_count: Literal["1"]
    limit_price: str
    contract_size: str
    opening_reference_notional_usdc: str
    maximum_exposure_reference_notional_usdc: str
    buffered_close_reference_notional_usdc: str
    branch_turnover_reference_notional_usdc: str
    opening_cap_usdc: Literal["100"]
    exposure_cap_usdc: Literal["150"]
    turnover_cap_usdc: Literal["300"]


class OperatorFuturesManualCallReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: AdminFuturesManualCallOutcome
    call_boundary_entered: bool | None


class OperatorFuturesManualReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["operator_futures_manual_lifecycle"] = (
        "operator_futures_manual_lifecycle"
    )
    goal_id: Literal["operator_futures_manual_order_lifecycle_v1"]
    revision: int = Field(ge=0)
    environment: str
    portfolio_profile_alias: Literal["Default"] = "Default"
    product_scope: Literal["AVP-20DEC30-CDE"] = "AVP-20DEC30-CDE"
    contract_count: Literal["1"] = "1"
    strict_opening_cap_usdc: Literal["100"] = "100"
    strict_exposure_cap_usdc: Literal["150"] = "150"
    strict_turnover_cap_usdc: Literal["300"] = "300"
    cycles_used: int = Field(ge=0, le=10)
    cycles_remaining: int = Field(ge=0, le=10)
    active_cycle_number: int | None = Field(default=None, ge=1, le=10)
    eligibility_outcome: AdminFuturesManualEligibilityOutcome | None
    eligibility_diagnostic_code: str
    category_attempts: dict[str, int]
    candidate: OperatorFuturesManualCandidateReadback | None
    candidate_fresh_for_execution: bool
    candidate_freshness_diagnostic_code: str
    candidate_sha256: str | None
    portfolio_id_sha256: str | None
    eligibility_evidence_sha256: str | None
    execution_posture_ready: bool
    execution_posture_diagnostic_code: str
    client_order_id: str | None
    preview: OperatorFuturesManualCallReadback
    preview_id_sha256: str | None
    create: OperatorFuturesManualCallReadback
    exchange_order_id_sha256: str | None
    reconciliation: OperatorFuturesManualCallReadback
    order_status: str | None
    authoritatively_nonterminal: bool | None
    cancel: OperatorFuturesManualCallReadback
    diagnostic_code: str
    allowed_actions: list[
        Literal["REFRESH_ELIGIBILITY", "EXECUTE_PREVIEW_GATED_PROOF"]
    ]
    raw_responses_included: Literal[False] = False
    private_identifiers_included: Literal[False] = False
    exception_text_included: Literal[False] = False
    correlation_id: str | None
    audit_id: str | None
    updated_at: str | None


class OperatorFuturesManualRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    authorize_one_no_retry_six_category_cycle: Literal[True]
    acknowledge_cycle_is_goal_global_and_limited_to_ten: Literal[True]
    acknowledge_unsuccessful_or_unknown_cycle_fails_closed: Literal[True]


class OperatorFuturesManualExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    authorize_preview_create_and_safe_closeout: Literal[True]
    acknowledge_unknown_outcome_consumes_allowance: Literal[True]
    acknowledge_create_requires_accepted_identical_preview: Literal[True]
    acknowledge_cancel_is_only_for_exact_nonterminal_child: Literal[True]


class OperatorFuturesManualMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["operator_futures_manual_mutation"] = (
        "operator_futures_manual_mutation"
    )
    action: Literal["REFRESH_ELIGIBILITY", "EXECUTE_PREVIEW_GATED_PROOF"]
    result: OperatorFuturesManualReadback


__all__ = [
    "OperatorFuturesManualCallReadback",
    "OperatorFuturesManualCandidateReadback",
    "OperatorFuturesManualExecuteRequest",
    "OperatorFuturesManualMutationResponse",
    "OperatorFuturesManualReadback",
    "OperatorFuturesManualRefreshRequest",
]
