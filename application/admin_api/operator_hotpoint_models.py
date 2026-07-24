"""Public, identifier-minimized contracts for Hotpoint Operations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .operator_hotpoint_control import (
    HOTPOINT_GOAL_ID,
    HotpointCancelState,
    HotpointControlAction,
    HotpointCreateState,
    HotpointKillSwitchState,
    HotpointWindowState,
)


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


class OperatorHotpointSafeCloseoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: Literal["SPOT", "FUTURES"]
    confirm_exact_child_safe_closeout: bool
    acknowledge_unknown_outcome_consumes_cancel_allowance: bool


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


class OperatorHotpointMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["operator_hotpoint_mutation"] = (
        "operator_hotpoint_mutation"
    )
    status: Literal["accepted"]
    service_method: Literal["control", "run_once", "safe_closeout"]
    operator_intent: str
    control: OperatorHotpointReadback
    correlation_id: str
    idempotency_key: str
    audit_id: str
    live_exchange_submitted: bool
    live_coinbase_orders_ran: bool


__all__ = [
    "OperatorHotpointControlRequest",
    "OperatorHotpointMutationResponse",
    "OperatorHotpointParentItem",
    "OperatorHotpointParentListResponse",
    "OperatorHotpointRateLimitReadback",
    "OperatorHotpointRecentPlacementReadback",
    "OperatorHotpointReadback",
    "OperatorHotpointRunRequest",
    "OperatorHotpointSafeCloseoutRequest",
]
