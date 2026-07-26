"""Generated-contract source models for Goal 3 Futures product tickets."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.enums import (
    AdminFuturesManualEligibilityOutcome,
)

from .operator_futures_manual_models import (
    OperatorFuturesManualCallReadback,
)


class OperatorFuturesProductPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_policy_revision: int = Field(ge=1)
    operator_reason: str = Field(min_length=1, max_length=240)
    confirm_exact_product_policy_action: Literal[True]


class OperatorFuturesProductTicketRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_ticket_revision: int = Field(ge=0)
    authorize_one_no_retry_six_category_cycle: Literal[True]
    acknowledge_cycle_is_goal_global_and_limited_to_ten: Literal[True]
    acknowledge_unsuccessful_or_unknown_cycle_fails_closed: Literal[True]


class OperatorFuturesProductTicketExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_ticket_revision: int = Field(ge=0)
    authorize_preview_create_and_safe_closeout: Literal[True]
    acknowledge_unknown_outcome_consumes_allowance: Literal[True]
    acknowledge_create_requires_accepted_identical_preview: Literal[True]
    acknowledge_cancel_is_only_for_exact_nonterminal_child: Literal[True]


class OperatorFuturesProductPolicyItemReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: Literal["AVP-20DEC30-CDE", "BIP-20DEC30-CDE"]
    lifecycle: Literal[
        "PENDING",
        "APPROVED",
        "ENABLED",
        "DISABLED",
        "RETIRED",
    ]
    selected: bool
    allowed_actions: list[
        Literal["APPROVE", "ENABLE", "DISABLE", "RETIRE", "SELECT"]
    ]


class OperatorFuturesProductTicketCandidateReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: Literal["AVP-20DEC30-CDE", "BIP-20DEC30-CDE"]
    side: Literal["BUY"]
    order_type: Literal["LIMIT_GTC"]
    post_only: Literal["true"]
    contract_count: Literal["1"]
    contract_code: str
    contract_size: str
    contract_expiry: str
    contract_expiry_type: Literal["EXPIRING", "PERPETUAL"]
    venue: Literal["cde"]
    risk_managed_by: Literal["MANAGED_BY_FCM"]
    product_price: str
    reference_price: str
    reference_price_source: Literal[
        "max_product_price_and_fresh_best_ask"
    ]
    price_increment: str
    base_increment: str
    base_min_size: str
    best_bid: str
    best_ask: str
    limit_price: str
    intraday_margin_rate: str
    overnight_margin_rate: str
    worst_case_margin_rate: str
    required_margin_reference_usdc: str
    opening_reference_notional_usdc: str
    maximum_exposure_reference_notional_usdc: str
    buffered_close_reference_notional_usdc: str
    branch_turnover_reference_notional_usdc: str
    opening_cap_usdc: Literal["100"]
    exposure_cap_usdc: Literal["150"]
    turnover_cap_usdc: Literal["300"]
    close_buffer_multiplier: Literal["1.20"]
    product_policy_revision: str
    product_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at: str


class OperatorFuturesProductTicketReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["operator_futures_product_ticket"] = (
        "operator_futures_product_ticket"
    )
    goal_id: Literal[
        "operator_futures_product_policy_and_ticket_expansion_v1"
    ]
    environment: str
    portfolio_profile_alias: Literal["Default"] = "Default"
    configured_product_scope: list[
        Literal["AVP-20DEC30-CDE", "BIP-20DEC30-CDE"]
    ]
    policy_revision: int = Field(ge=1)
    policy_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    products: list[OperatorFuturesProductPolicyItemReadback]
    selected_product_id: (
        Literal["AVP-20DEC30-CDE", "BIP-20DEC30-CDE"] | None
    )
    selected_policy_revision: int | None = Field(default=None, ge=1)
    selected_policy_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    ticket_revision: int = Field(ge=0)
    cycles_used: int = Field(ge=0, le=10)
    cycles_remaining: int = Field(ge=0, le=10)
    active_cycle_number: int | None = Field(default=None, ge=1, le=10)
    eligibility_outcome: AdminFuturesManualEligibilityOutcome | None
    eligibility_diagnostic_code: str
    category_attempts: dict[str, int]
    candidate: OperatorFuturesProductTicketCandidateReadback | None
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
        Literal[
            "APPROVE_PRODUCT",
            "ENABLE_PRODUCT",
            "DISABLE_PRODUCT",
            "RETIRE_PRODUCT",
            "SELECT_PRODUCT",
            "REFRESH_ELIGIBILITY",
            "EXECUTE_PREVIEW_GATED_PROOF",
        ]
    ]
    raw_responses_included: Literal[False] = False
    private_identifiers_included: Literal[False] = False
    exception_text_included: Literal[False] = False
    correlation_id: str | None
    audit_id: str | None
    updated_at: str | None


class OperatorFuturesProductTicketMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["operator_futures_product_ticket_mutation"] = (
        "operator_futures_product_ticket_mutation"
    )
    action: Literal[
        "APPROVE_PRODUCT",
        "ENABLE_PRODUCT",
        "DISABLE_PRODUCT",
        "RETIRE_PRODUCT",
        "SELECT_PRODUCT",
        "REFRESH_ELIGIBILITY",
        "EXECUTE_PREVIEW_GATED_PROOF",
    ]
    result: OperatorFuturesProductTicketReadback


__all__ = [
    "OperatorFuturesProductPolicyItemReadback",
    "OperatorFuturesProductPolicyRequest",
    "OperatorFuturesProductTicketCandidateReadback",
    "OperatorFuturesProductTicketExecuteRequest",
    "OperatorFuturesProductTicketMutationResponse",
    "OperatorFuturesProductTicketReadback",
    "OperatorFuturesProductTicketRefreshRequest",
]
