"""Generated-contract source models for Goal 5 Futures activation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


FuturesFillTriggeredAction = Literal[
    "ENABLE",
    "DISABLE",
    "PAUSE",
    "RESUME",
    "DRAIN",
]


class OperatorFuturesFillTriggeredCapsReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opening_usdc: Literal["100"] = "100"
    exposure_usdc: Literal["150"] = "150"
    turnover_usdc: Literal["300"] = "300"
    comparison: Literal["strictly_less_than"] = "strictly_less_than"


class OperatorFuturesFillTriggeredFollowUpReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal[
        "operator_futures_fill_triggered_follow_up_readback"
    ] = "operator_futures_fill_triggered_follow_up_readback"
    goal_id: Literal[
        "operator_futures_fill_triggered_follow_up_activation_v1"
    ]
    source_client_order_id: str
    follow_up_intent_id: str
    environment: str
    portfolio_profile_alias: Literal["Default"] = "Default"
    operator_intent: Literal[
        "control_futures_fill_triggered_follow_up"
    ] = "control_futures_fill_triggered_follow_up"
    caps: OperatorFuturesFillTriggeredCapsReadback = (
        OperatorFuturesFillTriggeredCapsReadback()
    )
    control_state: Literal[
        "DISABLED", "ENABLED", "PAUSED", "DRAINING", "DRAINED"
    ]
    trigger_state: Literal[
        "UNCLAIMED", "CLAIMED", "COMPLETED", "BLOCKED", "UNKNOWN"
    ]
    revision: int = Field(ge=0)
    delegated_live_authority: bool
    trigger_claim_present: bool
    trigger_evidence_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    lifecycle_revision: int = Field(ge=0)
    child_client_order_id: str | None
    preview_outcome: str
    create_outcome: str
    reconciliation_outcome: str
    cancel_outcome: str
    diagnostic_code: str
    execution_posture_ready: bool
    allowed_actions: list[FuturesFillTriggeredAction]
    correlation_id: str
    audit_id: str
    recorded_at: str
    updated_at: str
    readback_source: Literal["postgresql_authority"] = (
        "postgresql_authority"
    )
    page_load_coinbase_calls: Literal[0] = 0
    raw_responses_included: Literal[False] = False
    private_identifiers_included: Literal[False] = False
    exception_text_included: Literal[False] = False


class OperatorFuturesFillTriggeredFollowUpControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: FuturesFillTriggeredAction
    expected_revision: int = Field(ge=0)
    authorize_one_preview_create_and_safe_closeout: bool = False
    acknowledge_unknown_outcome_consumes_allowance: bool = False
    acknowledge_child_terms_are_backend_derived: bool = False


class OperatorFuturesFillTriggeredFollowUpControlResponse(
    OperatorFuturesFillTriggeredFollowUpReadback
):
    type: Literal[
        "operator_futures_fill_triggered_follow_up_control"
    ] = "operator_futures_fill_triggered_follow_up_control"
    operator_intent: Literal[
        "control_futures_fill_triggered_follow_up"
    ] = "control_futures_fill_triggered_follow_up"


__all__ = [
    "OperatorFuturesFillTriggeredCapsReadback",
    "OperatorFuturesFillTriggeredFollowUpControlRequest",
    "OperatorFuturesFillTriggeredFollowUpControlResponse",
    "OperatorFuturesFillTriggeredFollowUpReadback",
]
