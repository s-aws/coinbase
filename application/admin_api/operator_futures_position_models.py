"""Generated-contract source models for the Goal 11 Futures workspace."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.enums import (
    AdminFuturesPositionCallOutcome,
    AdminFuturesPositionEligibilityOutcome,
)


class OperatorFuturesPositionSelectionReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position_key: str = Field(pattern=r"^fpos_[0-9a-f]{64}$")
    product_id: str
    position_side: Literal["LONG", "SHORT"]
    close_side: Literal["BUY", "SELL"]
    current_contracts: str
    full_close_size: str
    bounded_reduce_size: str
    best_bid: str
    best_ask: str


class OperatorFuturesPositionCallReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: AdminFuturesPositionCallOutcome
    call_boundary_entered: bool | None


class OperatorFuturesPositionLifecycleReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["operator_futures_position_lifecycle"] = (
        "operator_futures_position_lifecycle"
    )
    goal_id: Literal[
        "operator_futures_position_close_reduce_and_reconciliation_v1"
    ]
    revision: int = Field(ge=0)
    environment: str
    portfolio_profile_alias: Literal["Default"] = "Default"
    cycles_used: int = Field(ge=0, le=10)
    cycles_remaining: int = Field(ge=0, le=10)
    active_cycle_number: int | None = Field(default=None, ge=1, le=10)
    eligibility_outcome: AdminFuturesPositionEligibilityOutcome | None
    eligibility_diagnostic_code: str
    category_attempts: dict[str, int]
    selection: OperatorFuturesPositionSelectionReadback | None
    selection_fresh_for_execution: bool
    selection_freshness_diagnostic_code: str
    selection_sha256: str | None
    portfolio_id_sha256: str | None
    eligibility_evidence_sha256: str | None
    execution_posture_ready: bool
    execution_posture_diagnostic_code: str
    selected_mode: Literal["CLOSE_FULL", "REDUCE_ONE_CONTRACT"] | None
    client_order_id: str | None
    action_call: OperatorFuturesPositionCallReadback
    exchange_order_id_sha256: str | None
    order_reconciliation: OperatorFuturesPositionCallReadback
    order_status: str | None
    authoritatively_nonterminal: bool | None
    position_reconciliation: OperatorFuturesPositionCallReadback
    remaining_contracts: str | None
    cancel: OperatorFuturesPositionCallReadback
    diagnostic_code: str
    allowed_actions: list[
        Literal[
            "REFRESH_SELECTED_POSITION",
            "CLOSE_FULL",
            "REDUCE_ONE_CONTRACT",
        ]
    ]
    raw_responses_included: Literal[False] = False
    private_identifiers_included: Literal[False] = False
    exception_text_included: Literal[False] = False
    correlation_id: str | None
    audit_id: str | None
    updated_at: str | None


class OperatorFuturesPositionRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    position_key: str = Field(pattern=r"^fpos_[0-9a-f]{64}$")
    authorize_one_no_retry_six_category_cycle: Literal[True]
    acknowledge_cycle_is_goal_global_and_limited_to_ten: Literal[True]
    acknowledge_unsuccessful_or_unknown_cycle_fails_closed: Literal[True]


class OperatorFuturesPositionExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    mode: Literal["CLOSE_FULL", "REDUCE_ONE_CONTRACT"]
    authorize_exact_selected_position_action: Literal[True]
    acknowledge_action_is_mutually_exclusive_and_single_use: Literal[True]
    acknowledge_unknown_outcome_consumes_allowance: Literal[True]
    acknowledge_exact_order_cancel_only: Literal[True]


class OperatorFuturesPositionMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["operator_futures_position_mutation"] = (
        "operator_futures_position_mutation"
    )
    action: Literal[
        "REFRESH_SELECTED_POSITION",
        "CLOSE_FULL",
        "REDUCE_ONE_CONTRACT",
    ]
    result: OperatorFuturesPositionLifecycleReadback


__all__ = [
    "OperatorFuturesPositionCallReadback",
    "OperatorFuturesPositionExecuteRequest",
    "OperatorFuturesPositionLifecycleReadback",
    "OperatorFuturesPositionMutationResponse",
    "OperatorFuturesPositionRefreshRequest",
    "OperatorFuturesPositionSelectionReadback",
]
