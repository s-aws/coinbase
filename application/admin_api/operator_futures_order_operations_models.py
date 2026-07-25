"""Generated-contract source models for the Futures Orders workspace."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OperatorFuturesOrderItem(BaseModel):
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
    exchange_order_id_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authoritatively_nonterminal: bool
    cancel_eligible: bool


class OperatorFuturesOrderOperationsReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["operator_futures_order_operations"] = (
        "operator_futures_order_operations"
    )
    goal_id: Literal[
        "operator_futures_order_inventory_detail_cancel_reconcile_v1"
    ]
    revision: int = Field(ge=0)
    environment: str
    portfolio_profile_alias: Literal["Default"] = "Default"
    product_type: Literal["FUTURE"] = "FUTURE"
    cycles_used: int = Field(ge=0, le=10)
    cycles_remaining: int = Field(ge=0, le=10)
    active_cycle_number: int | None = Field(default=None, ge=1, le=10)
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


class OperatorFuturesOrderPagination(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    total_matching_count: int = Field(ge=0)
    next_offset: int | None = Field(default=None, ge=0)
    has_more: bool


class OperatorFuturesOrderFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str | None
    order_status: str | None


class OperatorFuturesOrderListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["operator_futures_order_list"] = (
        "operator_futures_order_list"
    )
    authority: OperatorFuturesOrderOperationsReadback
    filters: OperatorFuturesOrderFilters
    pagination: OperatorFuturesOrderPagination
    items: list[OperatorFuturesOrderItem]
    readback_source: Literal["postgresql_projection"] = (
        "postgresql_projection"
    )
    page_load_coinbase_calls: Literal[0] = 0
    raw_responses_included: Literal[False] = False
    private_identifiers_included: Literal[False] = False


class OperatorFuturesOrderDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["operator_futures_order_detail"] = (
        "operator_futures_order_detail"
    )
    authority: OperatorFuturesOrderOperationsReadback
    client_order_id: str
    found: bool
    order: OperatorFuturesOrderItem | None
    readback_source: Literal["postgresql_projection"] = (
        "postgresql_projection"
    )
    page_load_coinbase_calls: Literal[0] = 0
    raw_responses_included: Literal[False] = False
    private_identifiers_included: Literal[False] = False


class OperatorFuturesOrderMutationResolutionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["operator_futures_order_mutation_resolution"] = (
        "operator_futures_order_mutation_resolution"
    )
    request_correlation_id: str = Field(min_length=1, max_length=255)
    found: bool
    terminal: bool
    result: OperatorFuturesOrderOperationsReadback | None
    readback_source: Literal["postgresql_cycle_result"] = (
        "postgresql_cycle_result"
    )
    page_load_coinbase_calls: Literal[0] = 0
    raw_responses_included: Literal[False] = False
    private_identifiers_included: Literal[False] = False
    exception_text_included: Literal[False] = False


class OperatorFuturesOrderRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    authorize_one_no_retry_cycle: Literal[True]
    acknowledge_cycle_is_goal_global_and_limited_to_ten: Literal[True]
    acknowledge_unknown_read_fails_closed: Literal[True]


class OperatorFuturesOrderCancelRequest(
    OperatorFuturesOrderRefreshRequest
):
    acknowledge_unknown_cancel_consumes_allowance: Literal[True]


class OperatorFuturesOrderMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["operator_futures_order_mutation"] = (
        "operator_futures_order_mutation"
    )
    action: Literal["REFRESH_CATALOG", "RECONCILE_EXACT", "CANCEL_EXACT"]
    result: OperatorFuturesOrderOperationsReadback


__all__ = [
    "OperatorFuturesOrderCancelRequest",
    "OperatorFuturesOrderDetailResponse",
    "OperatorFuturesOrderItem",
    "OperatorFuturesOrderListResponse",
    "OperatorFuturesOrderMutationResolutionResponse",
    "OperatorFuturesOrderMutationResponse",
    "OperatorFuturesOrderOperationsReadback",
    "OperatorFuturesOrderRefreshRequest",
]
