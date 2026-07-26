"""Generated-contract source models for Futures follow-up attachment."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OperatorFuturesFollowUpIntentEligibilityReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eligible: bool
    blockers: list[str]
    source_found: bool
    source_product_configured: bool
    source_status_open: bool
    source_authoritatively_nonterminal: bool
    source_exactly_one_contract: bool
    source_side_valid: bool
    follow_up_intent_absent: bool
    product_id: str | None
    source_side: Literal["BUY", "SELL"] | None
    derived_follow_up_side: Literal["BUY", "SELL"] | None
    contract_count: Literal["1"] | None
    source_status: str | None
    source_observed_at: str | None
    source_evidence_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )


class OperatorFuturesFollowUpIntentItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_id: Literal["operator_futures_follow_up_intent_attachment_v1"]
    follow_up_intent_id: str
    source_client_order_id: str
    root_client_order_id: str
    product_id: str
    source_side: Literal["BUY", "SELL"]
    derived_follow_up_side: Literal["BUY", "SELL"]
    contract_count: Literal["1"]
    state: Literal["ATTACHED"]
    source_status_at_attach: Literal["OPEN"]
    source_observed_at: str
    source_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason_code: Literal["FULL_FILL_OPPOSITE_ONE_CONTRACT"]
    correlation_id: str
    audit_id: str
    created_at: str


class OperatorFuturesFollowUpIntentReadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["operator_futures_follow_up_intent_readback"] = (
        "operator_futures_follow_up_intent_readback"
    )
    goal_id: Literal["operator_futures_follow_up_intent_attachment_v1"]
    source_client_order_id: str
    environment: str
    portfolio_profile_alias: Literal["Default"] = "Default"
    eligibility: OperatorFuturesFollowUpIntentEligibilityReadback
    follow_up_intent: OperatorFuturesFollowUpIntentItem | None
    allowed_actions: list[Literal["ATTACH_FOLLOW_UP_INTENT"]]
    readback_source: Literal["postgresql_projection"] = (
        "postgresql_projection"
    )
    page_load_coinbase_calls: Literal[0] = 0
    coinbase_calls: Literal[0] = 0
    child_created: Literal[False] = False
    raw_responses_included: Literal[False] = False
    private_identifiers_included: Literal[False] = False
    exception_text_included: Literal[False] = False


class OperatorFuturesFollowUpIntentAttachRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_source_observed_at: str = Field(min_length=1, max_length=128)
    expected_source_evidence_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    reason_code: Literal["FULL_FILL_OPPOSITE_ONE_CONTRACT"]
    acknowledge_future_materialization_requires_fresh_authorization: (
        Literal[True]
    )
    acknowledge_no_coinbase_call_or_child_creation: Literal[True]


class OperatorFuturesFollowUpIntentAttachResponse(
    OperatorFuturesFollowUpIntentReadResponse
):
    type: Literal["operator_futures_follow_up_intent_attach"] = (
        "operator_futures_follow_up_intent_attach"
    )
    replayed: bool


__all__ = [
    "OperatorFuturesFollowUpIntentAttachRequest",
    "OperatorFuturesFollowUpIntentAttachResponse",
    "OperatorFuturesFollowUpIntentEligibilityReadback",
    "OperatorFuturesFollowUpIntentItem",
    "OperatorFuturesFollowUpIntentReadResponse",
]
