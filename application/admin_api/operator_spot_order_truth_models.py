"""Generated-contract source models for the Spot Orders workspace."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OperatorSpotOrderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_order_id: str
    product_id: str
    side: Literal["BUY", "SELL"]
    status: str
    order_type: str
    time_in_force: str
    size: str | None
    limit_price: str | None
    filled_size: str | None
    created_at: str | None
    updated_at: str | None
    observed_at: str
    ownership_provenance: Literal["ADMIN_MANUAL_ROOT"]
    exchange_order_id_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authoritatively_nonterminal: bool
    cancel_eligible: bool


class OperatorSpotOrderTruthReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["operator_spot_order_truth"] = (
        "operator_spot_order_truth"
    )
    goal_id: Literal[
        "operator_spot_order_truth_and_exact_cancel_reconcile_v1"
    ]
    revision: int = Field(ge=0)
    environment: str
    portfolio_profile_alias: Literal["Test"] = "Test"
    product_type: Literal["SPOT"] = "SPOT"
    cycles_used: int = Field(ge=0, le=1)
    cycles_remaining: int = Field(ge=0, le=1)
    active_cycle_number: int | None = Field(default=None, ge=1, le=1)
    last_action: (
        Literal["REFRESH_CATALOG", "RECONCILE_EXACT", "CANCEL_EXACT"]
        | None
    )
    last_target_client_order_id: str | None
    last_outcome: Literal[
        "NOT_RUN", "CLAIMED", "SUCCEEDED", "INELIGIBLE", "UNKNOWN"
    ]
    diagnostic_code: str
    category_attempts: dict[str, int]
    page_count: int = Field(ge=0, le=100)
    order_count: int = Field(ge=0)
    portfolio_id_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    evidence_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    cancel_outcome: Literal[
        "NOT_RUN", "CLAIMED", "ACCEPTED", "REJECTED", "UNKNOWN"
    ]
    cancel_exchange_invoked: bool | None
    cancel_target_client_order_id: str | None
    cancel_exchange_order_id_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    execution_posture_ready: bool
    execution_posture_diagnostic_code: str
    allowed_actions: list[
        Literal["REFRESH_CATALOG", "RECONCILE_EXACT", "CANCEL_EXACT"]
    ]
    raw_responses_included: Literal[False] = False
    private_identifiers_included: Literal[False] = False
    exception_text_included: Literal[False] = False
    correlation_id: str | None
    audit_id: str | None
    refreshed_at: str | None
    updated_at: str | None


class OperatorSpotOrderPagination(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    total_matching_count: int = Field(ge=0)
    next_offset: int | None = Field(default=None, ge=0)
    has_more: bool


class OperatorSpotOrderFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str | None
    order_status: str | None


class OperatorSpotOrderListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["operator_spot_order_truth_list"] = (
        "operator_spot_order_truth_list"
    )
    authority: OperatorSpotOrderTruthReadback
    filters: OperatorSpotOrderFilters
    pagination: OperatorSpotOrderPagination
    items: list[OperatorSpotOrderItem]
    readback_source: Literal["postgresql_projection"] = (
        "postgresql_projection"
    )
    page_load_coinbase_calls: Literal[0] = 0
    raw_responses_included: Literal[False] = False
    private_identifiers_included: Literal[False] = False


class OperatorSpotOrderDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["operator_spot_order_truth_detail"] = (
        "operator_spot_order_truth_detail"
    )
    authority: OperatorSpotOrderTruthReadback
    client_order_id: str
    found: bool
    order: OperatorSpotOrderItem | None
    readback_source: Literal["postgresql_projection"] = (
        "postgresql_projection"
    )
    page_load_coinbase_calls: Literal[0] = 0
    raw_responses_included: Literal[False] = False
    private_identifiers_included: Literal[False] = False


class OperatorSpotOrderMutationResolutionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["operator_spot_order_truth_mutation_resolution"] = (
        "operator_spot_order_truth_mutation_resolution"
    )
    request_correlation_id: str = Field(min_length=1, max_length=255)
    found: bool
    terminal: bool
    result: OperatorSpotOrderTruthReadback | None
    readback_source: Literal["postgresql_mutation_result"] = (
        "postgresql_mutation_result"
    )
    page_load_coinbase_calls: Literal[0] = 0
    raw_responses_included: Literal[False] = False
    private_identifiers_included: Literal[False] = False
    exception_text_included: Literal[False] = False


class OperatorSpotOrderRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    authorize_one_no_retry_cycle: Literal[True]
    acknowledge_cycle_is_goal_global_and_limited_to_one: Literal[True]
    acknowledge_unknown_read_fails_closed: Literal[True]


class OperatorSpotOrderCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    acknowledge_unknown_cancel_consumes_allowance: Literal[True]


class OperatorSpotOrderMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["operator_spot_order_truth_mutation"] = (
        "operator_spot_order_truth_mutation"
    )
    action: Literal["REFRESH_CATALOG", "RECONCILE_EXACT", "CANCEL_EXACT"]
    result: OperatorSpotOrderTruthReadback


__all__ = [
    "OperatorSpotOrderCancelRequest",
    "OperatorSpotOrderDetailResponse",
    "OperatorSpotOrderItem",
    "OperatorSpotOrderListResponse",
    "OperatorSpotOrderMutationResolutionResponse",
    "OperatorSpotOrderMutationResponse",
    "OperatorSpotOrderTruthReadback",
    "OperatorSpotOrderRefreshRequest",
]
