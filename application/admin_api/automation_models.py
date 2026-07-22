"""Strict public models for the local operator automation control plane.

The models deliberately contain no generic executor payload and no exchange
identifier.  A job kind determines its backend domain; callers cannot select a
domain independently or use a Spot definition to imply Futures authority.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import cast, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from application.admin_api.product_policy import DEFAULT_SPOT_PRODUCT_SCOPE
from core.enums import (
    OperatorAutomationControlPosture as AutomationControlPosture,
    OperatorAutomationDefinitionState as AutomationDefinitionState,
    OperatorAutomationDomain as AutomationDomain,
    OperatorAutomationJobKind as AutomationJobKind,
    OperatorAutomationRunState as AutomationRunState,
    OperatorAutomationScheduleKind as AutomationScheduleMode,
)


_VISIBLE_ASCII_PATTERN = r"^[\x21-\x7e]+$"
_CANONICAL_UUID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_PRODUCT_PATTERN = r"^[A-Z0-9][A-Z0-9._-]*$"
_POSITIVE_DECIMAL_PATTERN = r"^(0|[1-9]\d*)(\.\d+)?$"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_NEAR_MARKET_SPOT_MODES = frozenset(
    {
        "NEAR_MARKET_POST_ONLY_V4",
        "NEAR_MARKET_POST_ONLY_V5",
        "NEAR_MARKET_POST_ONLY_V6",
    }
)
_MINIMUM_SIZE_SPOT_MODES = frozenset(
    {
        "MINIMUM_SIZE_POST_ONLY_V7",
        "MINIMUM_SIZE_POST_ONLY_V8",
        "MINIMUM_SIZE_POST_ONLY_V9",
    }
)
_ATOMIC_MARKET_SNAPSHOT_SPOT_MODES = frozenset(
    {
        "ATOMIC_MARKET_SNAPSHOT_V10",
        "ATOMIC_MARKET_SNAPSHOT_V11",
        "ATOMIC_MARKET_SNAPSHOT_V12",
    }
)
_POST_ONLY_SPOT_MODES = frozenset(
    {
        *_NEAR_MARKET_SPOT_MODES,
        *_MINIMUM_SIZE_SPOT_MODES,
        *_ATOMIC_MARKET_SNAPSHOT_SPOT_MODES,
    }
)
_MINIMUM_SIZE_PREPARATION_CATEGORIES = (
    "api_key_permissions",
    "portfolio_catalog",
    "wallet_balances",
    "product_metadata",
    "best_bid_ask",
    "fee_summary",
)
_MINIMUM_SIZE_STAGE_UNKNOWN_PREFIX_LENGTH = {
    "automation_minimum_size_runner_composition_unknown": 0,
    "automation_minimum_size_api_key_permissions_unknown": 0,
    "automation_minimum_size_portfolio_catalog_unknown": 1,
    "automation_minimum_size_wallet_balances_unknown": 2,
    "automation_minimum_size_product_metadata_unknown": 3,
    "automation_minimum_size_best_bid_ask_unknown": 4,
    "automation_minimum_size_fee_summary_unknown": 5,
    "automation_minimum_size_materialization_unknown": 6,
}
_MINIMUM_SIZE_UNKNOWN_DIAGNOSTICS = frozenset(
    {
        "automation_minimum_size_preparation_unknown",
        *_MINIMUM_SIZE_STAGE_UNKNOWN_PREFIX_LENGTH,
    }
)
_PREVIEW_GATED_SPOT_MODES = frozenset(
    {
        "PREVIEW_GATED_V2",
        "DOCUMENTED_MARKET_FRESHNESS_V3",
        *_POST_ONLY_SPOT_MODES,
    }
)
_EXACT_PREVIEW_UNKNOWN_FAILURE_CLASSES = frozenset(
    {
        "RESPONSE_SCHEMA_INVALID",
        "HTTP_CLIENT_RESPONSE",
        "HTTP_SERVER_RESPONSE",
        "HTTP_REDIRECT_RESPONSE",
        "HTTP_RESPONSE_INVALID",
    }
)


class AutomationDefinitionLifecycleAction(str, Enum):
    ENABLE = "ENABLE"
    DISABLE = "DISABLE"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    DRAIN = "DRAIN"


class AutomationControlAction(str, Enum):
    PAUSE = "PAUSED"
    RESUME = "ACTIVE"
    DRAIN = "DRAINING"
    SHUTDOWN = "SHUTDOWN"


class AutomationRunTrigger(str, Enum):
    ONE_SHOT = "ONE_SHOT"
    SCHEDULE_REVIEW = "SCHEDULE_REVIEW"


_SPOT_JOB_KINDS = frozenset(
    {
        AutomationJobKind.SPOT_CAMPAIGN,
        AutomationJobKind.SPOT_SWEEP,
        AutomationJobKind.SPOT_LADDER,
    }
)
_APPROVED_SPOT_PRODUCT_SCOPE = frozenset(DEFAULT_SPOT_PRODUCT_SCOPE)
_DEFINITION_ALLOWED_ACTIONS = frozenset(
    {
        "ENABLE",
        "DISABLE",
        "PAUSE",
        "RESUME",
        "DRAIN",
        "SET_SCHEDULE",
        "CLEAR_SCHEDULE",
        "RUN_ONCE",
    }
)
_CONTROL_ALLOWED_ACTIONS = frozenset({"PAUSE", "RESUME", "DRAIN", "SHUTDOWN"})
AUTOMATION_SPOT_SINGLE_CHILD_SUCCESSOR_DIAGNOSTICS = {
    AutomationRunState.BLOCKED: frozenset(
        {
            "automation_spot_eligibility_refresh_required",
            "automation_spot_eligibility_cycles_exhausted",
        }
    ),
    AutomationRunState.ACTIVE: frozenset(
        {
            "automation_spot_safe_closeout_ready",
            "automation_spot_safe_closeout_invocation_started",
        }
    ),
    AutomationRunState.TERMINAL: frozenset(
        {
            "automation_spot_safe_closeout_accepted_terminal",
            "automation_spot_safe_closeout_accepted_nonterminal",
            "automation_spot_safe_closeout_rejected",
        }
    ),
    AutomationRunState.UNKNOWN_CONSUMED: frozenset(
        {
            "automation_spot_safe_closeout_unknown_consumed",
        }
    ),
}
_V1_RUN_DIAGNOSTICS = {
    AutomationRunState.CLAIMED: frozenset(
        {"one_shot_run_claimed"}
    ),
    AutomationRunState.PREPARING: frozenset(
        {
            "preparing",
            "automation_spot_source_gate_resumed",
            "automation_spot_final_admission_started",
        }
    ),
    AutomationRunState.AWAITING_OPERATOR_AUTHORIZATION: frozenset(
        {
            "awaiting_operator_authorization",
            "automation_spot_preview_invocation_started",
            "automation_spot_preview_accepted_create_ready",
        }
    ),
    AutomationRunState.BLOCKED: frozenset(
        {
            "automation_domain_adapter_unavailable",
            "automation_single_child_plan_missing",
            "automation_active_order_catalog_read_not_authorized",
            "restart_pre_invocation_blocked",
        }
    )
    | AUTOMATION_SPOT_SINGLE_CHILD_SUCCESSOR_DIAGNOSTICS[
        AutomationRunState.BLOCKED
    ],
    AutomationRunState.UNKNOWN_CONSUMED: frozenset(
        {
            "restart_unknown_consumed",
            "unknown_consumed",
            "automation_spot_create_unknown_consumed",
            "automation_spot_cancel_unknown_consumed",
            "automation_spot_preview_unknown_consumed",
        }
    )
    | AUTOMATION_SPOT_SINGLE_CHILD_SUCCESSOR_DIAGNOSTICS[
        AutomationRunState.UNKNOWN_CONSUMED
    ],
    AutomationRunState.ABORTED: frozenset({"automation_run_aborted"}),
    AutomationRunState.INVOCATION_STARTED: frozenset(
        {
            "invocation_started",
            "automation_spot_create_invocation_started",
        }
    ),
    AutomationRunState.ACTIVE: frozenset(
        {
            "active",
            "automation_spot_create_accepted_active",
            "automation_spot_cancel_invocation_started",
        }
    )
    | AUTOMATION_SPOT_SINGLE_CHILD_SUCCESSOR_DIAGNOSTICS[
        AutomationRunState.ACTIVE
    ],
    AutomationRunState.TERMINAL: frozenset(
        {
            "terminal",
            "automation_spot_create_rejected",
            "automation_spot_create_accepted_terminal",
            "automation_spot_cancel_rejected",
            "automation_spot_cancel_accepted_terminal",
            "automation_spot_cancel_accepted_nonterminal",
            "automation_spot_preview_rejected",
        }
    )
    | AUTOMATION_SPOT_SINGLE_CHILD_SUCCESSOR_DIAGNOSTICS[
        AutomationRunState.TERMINAL
    ],
}


def _normalized_operator_text(value: object, *, code: str) -> object:
    if not isinstance(value, str):
        return value
    normalized = value.strip()
    if not normalized or "\r" in normalized or "\n" in normalized:
        raise ValueError(code)
    return normalized


def domain_for_job_kind(job_kind: AutomationJobKind) -> AutomationDomain:
    """Return the sole backend owner for a supported v1 job kind."""

    if job_kind in _SPOT_JOB_KINDS:
        return AutomationDomain.SPOT
    if job_kind is AutomationJobKind.FOLLOW_UP:
        return AutomationDomain.ORDERS
    raise ValueError("automation_job_kind_unsupported")


class AutomationNoExchangeActivity(BaseModel):
    """Truthful current-request accounting; local routes retain exact zero."""

    model_config = ConfigDict(extra="forbid")

    coinbase_api_call_count: Literal[0] = 0
    exchange_mutation_count: Literal[0] = 0
    create_call_count: Literal[0] = 0
    cancel_call_count: Literal[0] = 0
    call_count_exact: Literal[True] = True
    recurring_worker_started: Literal[False] = False


class AutomationEligibilityRefreshActivity(BaseModel):
    """Current-cycle accounting for approved read-only eligibility evidence."""

    model_config = ConfigDict(extra="forbid")

    coinbase_api_call_count: int | None = Field(default=0, ge=0)
    exchange_mutation_count: Literal[0] = 0
    create_call_count: Literal[0] = 0
    cancel_call_count: Literal[0] = 0
    call_count_exact: bool = True
    recurring_worker_started: Literal[False] = False

    @model_validator(mode="after")
    def validate_call_accounting(self) -> Self:
        if self.call_count_exact is (self.coinbase_api_call_count is None):
            raise ValueError("automation_eligibility_refresh_activity_invalid")
        return self


class AutomationRunMutationActivity(BaseModel):
    """Truthful operation-local accounting for one run mutation workflow."""

    model_config = ConfigDict(extra="forbid")

    operation: Literal[
        "LOCAL",
        "CREATE",
        "PREVIEW_GATED_CREATE",
        "SAFE_CLOSEOUT",
    ] = (
        "LOCAL"
    )
    coinbase_api_call_count: int | None = Field(default=0, ge=0)
    preview_call_count: int | None = Field(default=0, ge=0, le=1)
    read_call_count: int | None = Field(default=0, ge=0)
    exchange_mutation_count: int | None = Field(default=0, ge=0, le=1)
    create_call_count: int | None = Field(default=0, ge=0, le=1)
    cancel_call_count: int | None = Field(default=0, ge=0, le=1)
    call_count_exact: bool = True
    recurring_worker_started: Literal[False] = False

    @model_validator(mode="after")
    def validate_call_accounting(self) -> Self:
        counts = (
            self.coinbase_api_call_count,
            self.preview_call_count,
            self.read_call_count,
            self.exchange_mutation_count,
            self.create_call_count,
            self.cancel_call_count,
        )
        any_unknown = any(value is None for value in counts)
        if self.call_count_exact:
            if any_unknown:
                raise ValueError("automation_run_mutation_activity_invalid")
            total = cast(int, self.coinbase_api_call_count)
            reads = cast(int, self.read_call_count)
            preview = cast(int, self.preview_call_count)
            exchange = cast(int, self.exchange_mutation_count)
            create = cast(int, self.create_call_count)
            cancel = cast(int, self.cancel_call_count)
            if total != preview + reads + exchange:
                raise ValueError("automation_run_mutation_activity_invalid")
            if exchange != create + cancel:
                raise ValueError("automation_run_mutation_activity_invalid")
            if self.operation == "LOCAL" and (
                preview != 0 or reads != 0 or create != 0 or cancel != 0
            ):
                raise ValueError("automation_run_mutation_activity_invalid")
            if self.operation == "CREATE" and (
                preview != 0 or create not in {0, 1} or cancel != 0
            ):
                raise ValueError("automation_run_mutation_activity_invalid")
            if self.operation == "PREVIEW_GATED_CREATE" and (
                preview not in {0, 1}
                or create not in {0, 1}
                or cancel != 0
            ):
                raise ValueError("automation_run_mutation_activity_invalid")
            if self.operation == "SAFE_CLOSEOUT" and (
                preview != 0 or create != 0 or cancel not in {0, 1}
            ):
                raise ValueError("automation_run_mutation_activity_invalid")
            return self

        if not any_unknown or self.operation == "LOCAL":
            raise ValueError("automation_run_mutation_activity_invalid")
        total, preview, reads, exchange, create, cancel = counts
        if total is not None:
            raise ValueError("automation_run_mutation_activity_invalid")
        if self.operation == "CREATE" and (
            preview != 0
            or
            cancel != 0
            or create not in {0, 1, None}
            or exchange not in {0, 1, None}
            or (
                create is not None
                and exchange is not None
                and create != exchange
            )
        ):
            raise ValueError("automation_run_mutation_activity_invalid")
        if self.operation == "PREVIEW_GATED_CREATE" and (
            cancel != 0
            or preview not in {0, 1, None}
            or create not in {0, 1, None}
            or exchange not in {0, 1, None}
            or (
                create is not None
                and exchange is not None
                and create != exchange
            )
        ):
            raise ValueError("automation_run_mutation_activity_invalid")
        if self.operation == "SAFE_CLOSEOUT" and (
            preview != 0
            or create != 0
            or cancel not in {0, 1, None}
            or exchange not in {0, 1, None}
            or (
                cancel is not None
                and exchange is not None
                and cancel != exchange
            )
        ):
            raise ValueError("automation_run_mutation_activity_invalid")
        return self


class AutomationMutationContext(BaseModel):
    """Authenticated command binding passed to the durable repository."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_id: str = Field(min_length=1, max_length=255)
    roles: tuple[str, ...] = Field(min_length=1)
    idempotency_key: str = Field(
        min_length=1,
        max_length=255,
        pattern=_VISIBLE_ASCII_PATTERN,
    )
    correlation_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=_VISIBLE_ASCII_PATTERN,
    )
    operator_intent: str = Field(
        min_length=1,
        max_length=255,
        pattern=_VISIBLE_ASCII_PATTERN,
    )


class AutomationDefinitionSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: AutomationScheduleMode = AutomationScheduleMode.MANUAL_ONLY
    interval_minutes: int | None = Field(default=None, ge=1, le=525_600)
    next_review_at: datetime | None = None
    due: bool = False

    @model_validator(mode="after")
    def validate_interval_shape(self) -> Self:
        if self.mode is AutomationScheduleMode.MANUAL_ONLY:
            if self.interval_minutes is not None or self.next_review_at is not None:
                raise ValueError("automation_manual_schedule_interval_forbidden")
            if self.due:
                raise ValueError("automation_manual_schedule_due_invalid")
        elif self.interval_minutes is None:
            raise ValueError("automation_schedule_interval_required")
        elif self.next_review_at is None:
            raise ValueError("automation_schedule_next_review_required")
        return self


class AutomationSpotSingleChildOrderSpec(BaseModel):
    """One immutable Spot LIMIT/GTC child specification.

    The product and child identity are deliberately absent: product scope is
    fixed by the owning definition and ``client_order_id`` is derived by the
    backend when the run crosses its durable invocation boundary.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    side: Literal["BUY", "SELL"]
    base_size: str = Field(pattern=_POSITIVE_DECIMAL_PATTERN, max_length=64)
    limit_price: str = Field(pattern=_POSITIVE_DECIMAL_PATTERN, max_length=64)
    order_type: Literal["LIMIT"] = "LIMIT"
    time_in_force: Literal["GOOD_UNTIL_CANCELLED"] = "GOOD_UNTIL_CANCELLED"
    post_only: bool = False

    @model_validator(mode="after")
    def validate_positive_values(self) -> Self:
        try:
            values = (Decimal(self.base_size), Decimal(self.limit_price))
        except (InvalidOperation, ValueError):
            raise ValueError("automation_single_child_order_semantics_invalid") from None
        if any(not value.is_finite() or value <= 0 for value in values):
            raise ValueError("automation_single_child_order_semantics_invalid")
        return self


class AutomationSpotSingleChildOrderCreateSpec(AutomationSpotSingleChildOrderSpec):
    """Operator-supplied create terms; backend-derived maker plans are separate."""

    post_only: Literal[False] = False


class AutomationDefinitionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=120)
    job_kind: AutomationJobKind
    product_ids: list[str] = Field(default_factory=list, max_length=100)
    spot_execution_mode: Literal[
        "PREVIEW_GATED_V2",
        "DOCUMENTED_MARKET_FRESHNESS_V3",
    ] | None = None
    single_child_order: AutomationSpotSingleChildOrderCreateSpec | None = None

    @field_validator("display_name", mode="before")
    @classmethod
    def normalize_display_name(cls, value: object) -> object:
        return _normalized_operator_text(
            value,
            code="automation_display_name_invalid",
        )

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if len(set(self.product_ids)) != len(self.product_ids):
            raise ValueError("automation_product_scope_duplicate")
        for product_id in self.product_ids:
            if not product_id or len(product_id) > 255:
                raise ValueError("automation_product_id_invalid")
            import re

            if re.fullmatch(_PRODUCT_PATTERN, product_id) is None:
                raise ValueError("automation_product_id_invalid")
        if self.job_kind is AutomationJobKind.FOLLOW_UP and self.product_ids:
            raise ValueError("automation_follow_up_product_scope_forbidden")
        if self.job_kind in _SPOT_JOB_KINDS and (
            not self.product_ids
            or not set(self.product_ids).issubset(_APPROVED_SPOT_PRODUCT_SCOPE)
        ):
            raise ValueError("automation_spot_product_policy_blocked")
        if self.single_child_order is not None and (
            self.job_kind is not AutomationJobKind.SPOT_CAMPAIGN
            or self.product_ids != ["BTC-USDC"]
        ):
            raise ValueError("automation_single_child_job_kind_blocked")
        if (
            self.single_child_order is not None
            and self.single_child_order.post_only is not False
        ):
            raise ValueError("automation_spot_plan_post_only_invalid")
        if (
            self.spot_execution_mode in {
                "PREVIEW_GATED_V2",
                "DOCUMENTED_MARKET_FRESHNESS_V3",
            }
            and self.single_child_order is None
        ):
            raise ValueError("automation_preview_gated_plan_required")
        return self


class AutomationDefinitionLifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=255)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        return _normalized_operator_text(value, code="automation_reason_invalid")


class AutomationNearMarketCandidatePreparationRequest(BaseModel):
    """Explicit operator acknowledgement for one backend-derived proposal."""

    model_config = ConfigDict(extra="forbid")

    confirm_backend_derived_terms: Literal[True]
    confirm_one_no_retry_preparation_cycle: Literal[True]
    confirm_btc_usdc_test_portfolio_scope: Literal[True]
    confirm_unknown_consumes_cycle: Literal[True]
    reason: str = Field(min_length=1, max_length=255)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        return _normalized_operator_text(value, code="automation_reason_invalid")


class AutomationMinimumSizeCandidatePreparationRequest(BaseModel):
    """Explicit acknowledgement for one V7-V9 backend-derived proposal."""

    model_config = ConfigDict(extra="forbid")

    confirm_backend_derived_terms: Literal[True]
    confirm_one_no_retry_preparation_cycle: Literal[True]
    confirm_btc_usdc_test_portfolio_scope: Literal[True]
    confirm_dynamic_cap_strictly_below_3_10: Literal[True]
    confirm_unknown_consumes_cycle: Literal[True]
    reason: str = Field(min_length=1, max_length=255)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        return _normalized_operator_text(value, code="automation_reason_invalid")


class AutomationAtomicMarketSnapshotAuthorizationRequest(BaseModel):
    """One explicit operator action for atomic V10-V12 Preview/Create proof."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    confirm_atomic_final_market_snapshot_binding: Literal[True]
    confirm_one_no_retry_eight_category_cycle: Literal[True]
    confirm_single_preview: Literal[True]
    confirm_conditional_identical_single_child_create: Literal[True]
    confirm_btc_usdc_test_portfolio_scope: Literal[True]
    confirm_both_notionals_strictly_below_3_10: Literal[True]
    confirm_unknown_consumes_applicable_allowance: Literal[True]
    reason: str = Field(min_length=1, max_length=255)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        return _normalized_operator_text(value, code="automation_reason_invalid")


class AutomationDefinitionScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: AutomationScheduleMode
    interval_minutes: int | None = Field(default=None, ge=1, le=525_600)

    @model_validator(mode="after")
    def validate_interval_shape(self) -> Self:
        if (
            self.mode is AutomationScheduleMode.MANUAL_ONLY
            and self.interval_minutes is not None
        ):
            raise ValueError("automation_manual_schedule_interval_forbidden")
        if (
            self.mode is AutomationScheduleMode.INTERVAL_REVIEW_ONLY
            and self.interval_minutes is None
        ):
            raise ValueError("automation_schedule_interval_required")
        return self


class AutomationControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=255)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        return _normalized_operator_text(value, code="automation_reason_invalid")


class AutomationOneShotRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_one_shot: Literal[True]
    reason: str = Field(min_length=1, max_length=255)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        return _normalized_operator_text(value, code="automation_reason_invalid")


class AutomationSingleChildAuthorizationRequest(BaseModel):
    """Create-only exact-run acknowledgement; trading terms remain backend-owned."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    confirm_single_child_create: Literal[True]
    confirm_final_eligibility_refresh: Literal[True]
    confirm_account_wide_active_spot_order_catalog_read: Literal[True]
    confirm_unknown_consumes_allowance: Literal[True]
    expected_plan_sha256: str = Field(pattern=_SHA256_PATTERN)
    reason: str = Field(min_length=1, max_length=255)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        return _normalized_operator_text(value, code="automation_reason_invalid")


class AutomationPreviewGatedSingleChildAuthorizationRequest(BaseModel):
    """Preview-first exact-run acknowledgements; terms remain backend-owned."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    confirm_single_preview: Literal[True]
    confirm_conditional_single_child_create: Literal[True]
    confirm_final_eligibility_refresh: Literal[True]
    confirm_account_wide_active_spot_order_catalog_read: Literal[True]
    confirm_preview_unknown_consumes_allowance: Literal[True]
    confirm_create_unknown_consumes_allowance: Literal[True]
    expected_plan_sha256: str = Field(pattern=_SHA256_PATTERN)
    reason: str = Field(min_length=1, max_length=255)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        return _normalized_operator_text(value, code="automation_reason_invalid")


class AutomationEligibilityRefreshRequest(BaseModel):
    """Exact-run authorization for one bounded eight-category read cycle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    confirm_approved_eligibility_reads: Literal[True]
    confirm_account_wide_active_spot_order_catalog_read: Literal[True]
    confirm_unknown_consumes_cycle: Literal[True]
    expected_plan_sha256: str = Field(pattern=_SHA256_PATTERN)
    reason: str = Field(min_length=1, max_length=255)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        return _normalized_operator_text(value, code="automation_reason_invalid")


class AutomationSingleChildSafeCloseoutRequest(BaseModel):
    """Cancel-only exact-child safe-closeout acknowledgement."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    confirm_exact_child_safe_closeout_cancel: Literal[True]
    confirm_unknown_consumes_allowance: Literal[True]
    expected_plan_sha256: str = Field(pattern=_SHA256_PATTERN)
    reason: str = Field(min_length=1, max_length=255)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        return _normalized_operator_text(value, code="automation_reason_invalid")


AutomationEligibilityCategory = Literal[
    "api_key_permissions",
    "portfolio_catalog",
    "wallet_balances",
    "product_metadata",
    "best_bid_ask",
    "fee_summary",
    "exact_order_reconciliation",
    "active_order_catalog",
]


class AutomationSingleChildPlanReadback(BaseModel):
    """Safe backend-owned trading terms for one immutable child plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_sha256: str = Field(pattern=_SHA256_PATTERN)
    portfolio_scope: Literal["CONFIGURED_UNVERIFIED", "Test"]
    product_id: Literal["BTC-USDC"] = "BTC-USDC"
    side: Literal["BUY", "SELL"]
    base_size: str = Field(pattern=_POSITIVE_DECIMAL_PATTERN, max_length=64)
    limit_price: str = Field(pattern=_POSITIVE_DECIMAL_PATTERN, max_length=64)
    order_type: Literal["LIMIT"] = "LIMIT"
    time_in_force: Literal["GOOD_UNTIL_CANCELLED"] = "GOOD_UNTIL_CANCELLED"
    post_only: bool = False
    submitted_notional_usdc: str = Field(
        pattern=_POSITIVE_DECIMAL_PATTERN,
        max_length=64,
    )
    possible_execution_notional_usdc: str = Field(
        pattern=_POSITIVE_DECIMAL_PATTERN,
        max_length=64,
    )
    max_submitted_notional_usdc: Literal["3.10"] = "3.10"
    max_possible_execution_notional_usdc: str = Field(
        default="1.00",
        pattern=_POSITIVE_DECIMAL_PATTERN,
        max_length=64,
    )

    @model_validator(mode="after")
    def validate_caps(self) -> Self:
        values = (
            Decimal(self.base_size),
            Decimal(self.limit_price),
            Decimal(self.submitted_notional_usdc),
            Decimal(self.possible_execution_notional_usdc),
            Decimal(self.max_possible_execution_notional_usdc),
        )
        if any(not value.is_finite() or value <= 0 for value in values):
            raise ValueError("automation_single_child_plan_value_invalid")
        if (
            values[0] * values[1] != values[2]
            or values[3] > values[2]
            or values[3] > values[4]
        ):
            raise ValueError("automation_single_child_plan_notional_invalid")
        if values[2] > Decimal("3.10") or values[4] >= Decimal("3.10"):
            raise ValueError("automation_single_child_plan_cap_exceeded")
        return self


class AutomationSingleChildEligibilityReadback(BaseModel):
    """Value-blind per-run eligibility progress and call accounting."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cycle_number: int | None = Field(default=None, ge=1, le=10)
    required_categories: list[AutomationEligibilityCategory] = Field(
        default_factory=list,
        max_length=8,
    )
    completed_categories: list[AutomationEligibilityCategory] = Field(
        default_factory=list,
        max_length=8,
    )
    eligible: bool = False
    blocker_code: str | None = Field(default=None, min_length=1, max_length=96)
    coinbase_api_call_count: int | None = Field(default=0, ge=0)
    call_count_exact: bool = True

    @model_validator(mode="after")
    def validate_progress(self) -> Self:
        if len(self.required_categories) != len(set(self.required_categories)):
            raise ValueError("automation_eligibility_category_duplicate")
        if len(self.completed_categories) != len(set(self.completed_categories)):
            raise ValueError("automation_eligibility_category_duplicate")
        if not set(self.completed_categories).issubset(self.required_categories):
            raise ValueError("automation_eligibility_category_unexpected")
        if self.call_count_exact is (self.coinbase_api_call_count is None):
            raise ValueError("automation_eligibility_call_count_invalid")
        if self.eligible and (
            self.blocker_code is not None
            or self.completed_categories != self.required_categories
        ):
            raise ValueError("automation_eligibility_ready_invalid")
        return self


class AutomationControlPlaneItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    posture: AutomationControlPosture
    local_admission_enabled: bool
    recurring_worker_started: Literal[False] = False
    live_scheduler_enabled: Literal[False] = False
    coinbase_api_call_count: Literal[0] = 0
    exchange_mutation_count: Literal[0] = 0
    definition_create_allowed: bool = False
    near_market_candidate_preparation_allowed: bool = False
    minimum_size_candidate_preparation_allowed: bool = False
    atomic_market_snapshot_authorization_allowed: bool = False
    allowed_actions: list[str] = Field(default_factory=list)
    updated_at: datetime

    @model_validator(mode="after")
    def validate_posture(self) -> Self:
        if self.local_admission_enabled is not (
            self.posture is AutomationControlPosture.ACTIVE
        ):
            raise ValueError("automation_control_admission_posture_mismatch")
        if any(action not in _CONTROL_ALLOWED_ACTIONS for action in self.allowed_actions):
            raise ValueError("automation_control_action_invalid")
        if len(self.allowed_actions) != len(set(self.allowed_actions)):
            raise ValueError("automation_control_action_duplicate")
        return self


class AutomationMinimumSizePreparationReadback(BaseModel):
    """Sanitized durable V7-V9 preparation evidence for operator reloads."""

    model_config = ConfigDict(extra="forbid")

    policy_revision: Literal[
        "BTC_USDC_POST_ONLY_BEST_BID_MINIMUM_SIZE_V2"
    ] = "BTC_USDC_POST_ONLY_BEST_BID_MINIMUM_SIZE_V2"
    boundary_classification: Literal[
        "minimum_size_v4_base_minimum_conflict",
        "minimum_size_v4_quote_minimum_conflict",
        "minimum_size_v4_increment_conflict",
        "minimum_size_v4_fee_reserve_conflict",
        "minimum_size_v4_boundary_not_reproduced",
    ]
    cycle_number: int = Field(ge=1, le=10)
    completed_categories: list[
        Literal[
            "api_key_permissions",
            "portfolio_catalog",
            "wallet_balances",
            "product_metadata",
            "best_bid_ask",
            "fee_summary",
        ]
    ] = Field(min_length=6, max_length=6)
    coinbase_api_call_count: int = Field(ge=6)
    call_count_exact: Literal[True] = True
    max_submitted_notional_usdc: Literal["3.10"] = "3.10"
    max_possible_execution_notional_usdc: str = Field(
        pattern=_POSITIVE_DECIMAL_PATTERN,
        max_length=64,
    )

    @model_validator(mode="after")
    def validate_dynamic_cap(self) -> Self:
        cap = Decimal(self.max_possible_execution_notional_usdc)
        if not cap.is_finite() or cap <= 0 or cap >= Decimal("3.10"):
            raise ValueError("automation_minimum_size_preparation_cap_invalid")
        return self


class AutomationDefinitionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition_id: str = Field(pattern=_CANONICAL_UUID_PATTERN)
    revision: int = Field(ge=1)
    display_name: str = Field(min_length=1, max_length=120)
    domain: AutomationDomain
    job_kind: AutomationJobKind
    lifecycle_state: AutomationDefinitionState
    product_ids: list[str] = Field(default_factory=list, max_length=100)
    spot_execution_mode: Literal[
        "CREATE_ONLY_V1",
        "PREVIEW_GATED_V2",
        "DOCUMENTED_MARKET_FRESHNESS_V3",
        "NEAR_MARKET_POST_ONLY_V4",
        "NEAR_MARKET_POST_ONLY_V5",
        "NEAR_MARKET_POST_ONLY_V6",
        "MINIMUM_SIZE_POST_ONLY_V7",
        "MINIMUM_SIZE_POST_ONLY_V8",
        "MINIMUM_SIZE_POST_ONLY_V9",
        "ATOMIC_MARKET_SNAPSHOT_V10",
        "ATOMIC_MARKET_SNAPSHOT_V11",
        "ATOMIC_MARKET_SNAPSHOT_V12",
    ] | None = None
    single_child_order: AutomationSpotSingleChildOrderSpec | None = None
    minimum_size_preparation: AutomationMinimumSizePreparationReadback | None
    schedule: AutomationDefinitionSchedule
    adapter_status: Literal[
        "UNAVAILABLE",
        "SOURCE_GATED",
    ] = "UNAVAILABLE"
    live_execution_available: Literal[False] = False
    allowed_actions: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_domain_and_actions(self) -> Self:
        if self.domain is not domain_for_job_kind(self.job_kind):
            raise ValueError("automation_definition_domain_kind_mismatch")
        if self.job_kind is AutomationJobKind.FOLLOW_UP and self.product_ids:
            raise ValueError("automation_follow_up_product_scope_forbidden")
        if self.job_kind in _SPOT_JOB_KINDS and (
            not self.product_ids
            or not set(self.product_ids).issubset(_APPROVED_SPOT_PRODUCT_SCOPE)
        ):
            raise ValueError("automation_spot_product_policy_blocked")
        if self.single_child_order is not None and (
            self.job_kind is not AutomationJobKind.SPOT_CAMPAIGN
            or self.product_ids != ["BTC-USDC"]
        ):
            raise ValueError("automation_single_child_job_kind_blocked")
        minimum_size_mode = bool(
            self.spot_execution_mode is not None
            and self.spot_execution_mode.startswith("MINIMUM_SIZE_POST_ONLY_V")
        )
        if (self.minimum_size_preparation is not None) is not minimum_size_mode:
            raise ValueError("automation_minimum_size_preparation_binding_invalid")
        post_only = self.spot_execution_mode in _POST_ONLY_SPOT_MODES
        if post_only and (
            self.single_child_order is None
            or self.single_child_order.post_only is not True
        ):
            raise ValueError("automation_near_market_post_only_required")
        if (
            not post_only
            and self.single_child_order is not None
            and self.single_child_order.post_only is not False
        ):
            raise ValueError("automation_spot_plan_post_only_invalid")
        if any(action not in _DEFINITION_ALLOWED_ACTIONS for action in self.allowed_actions):
            raise ValueError("automation_definition_action_invalid")
        if len(self.allowed_actions) != len(set(self.allowed_actions)):
            raise ValueError("automation_definition_action_duplicate")
        if self.updated_at < self.created_at:
            raise ValueError("automation_definition_timestamp_invalid")
        return self


class AutomationRunItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(pattern=_CANONICAL_UUID_PATTERN)
    definition_id: str = Field(pattern=_CANONICAL_UUID_PATTERN)
    domain: AutomationDomain
    job_kind: AutomationJobKind
    trigger: AutomationRunTrigger
    state: AutomationRunState
    diagnostic_code: str = Field(min_length=1, max_length=96)
    adapter_status: Literal[
        "UNAVAILABLE",
        "SOURCE_GATED",
        "PREPARING",
        "AWAITING_OPERATOR_AUTHORIZATION",
        "BLOCKED",
        "INVOCATION_STARTED",
        "ACTIVE",
        "TERMINAL",
        "UNKNOWN_CONSUMED",
    ] = "UNAVAILABLE"
    live_execution_available: bool = False
    live_attempt_consumed: bool = False
    spot_execution_mode: Literal[
        "CREATE_ONLY_V1",
        "PREVIEW_GATED_V2",
        "DOCUMENTED_MARKET_FRESHNESS_V3",
        "NEAR_MARKET_POST_ONLY_V4",
        "NEAR_MARKET_POST_ONLY_V5",
        "NEAR_MARKET_POST_ONLY_V6",
        "MINIMUM_SIZE_POST_ONLY_V7",
        "MINIMUM_SIZE_POST_ONLY_V8",
        "MINIMUM_SIZE_POST_ONLY_V9",
        "ATOMIC_MARKET_SNAPSHOT_V10",
        "ATOMIC_MARKET_SNAPSHOT_V11",
        "ATOMIC_MARKET_SNAPSHOT_V12",
    ] | None = None
    preview_allowance_consumed: bool = False
    preview_outcome: Literal["ACCEPTED", "REJECTED", "UNKNOWN"] | None = None
    preview_failure_class: Literal[
        "NONE",
        "DOCUMENTED_REJECTION",
        "UNCLASSIFIED_REJECTION",
        "RESPONSE_SCHEMA_INVALID",
        "HTTP_CLIENT_RESPONSE",
        "HTTP_SERVER_RESPONSE",
        "HTTP_REDIRECT_RESPONSE",
        "HTTP_RESPONSE_INVALID",
        "TRANSPORT_UNKNOWN",
    ] | None = None
    preview_rejection_code: Literal[
        "UNKNOWN_DOCUMENTED",
        "INSUFFICIENT_FUNDS",
        "SIZE_PRECISION",
        "PRICE_PRECISION",
        "BASE_SIZE_TOO_LARGE",
        "BASE_SIZE_TOO_SMALL",
        "QUOTE_SIZE_PRECISION",
        "QUOTE_SIZE_TOO_LARGE",
        "QUOTE_SIZE_TOO_SMALL",
        "PRICE_TOO_LARGE",
        "POST_ONLY_LIMIT_PRICE",
        "LIMIT_PRICE",
        "NO_LIQUIDITY",
        "PRODUCT_PRICE_BOOK_MISSING",
        "MARKET_TRADE_DATA_MISSING",
        "PRODUCT_INVALID",
        "PRODUCT_UNTRADABLE",
        "MARKET_STATE",
        "ORDER_CONFIGURATION",
        "POLICY",
        "OTHER_DOCUMENTED",
        "MULTIPLE_DOCUMENTED",
    ] | None = None
    preview_warning_present: bool | None = None
    preview_identity_retention: Literal[
        "UNAVAILABLE",
        "HASHED",
        "WITHHELD",
    ] = "UNAVAILABLE"
    preview_call_count: int | None = Field(default=0, ge=0, le=1)
    coinbase_api_call_count: int | None = Field(default=0, ge=0)
    create_call_count: int | None = Field(default=0, ge=0, le=1)
    cancel_call_count: int | None = Field(default=0, ge=0, le=1)
    reconciliation_call_count: int | None = Field(default=0, ge=0)
    call_count_exact: bool = True
    create_allowance_consumed: bool = False
    cancel_allowance_consumed: bool = False
    client_order_id: str | None = Field(
        default=None,
        pattern=_CANONICAL_UUID_PATTERN,
    )
    child_terminal: bool | None = None
    single_child_plan: AutomationSingleChildPlanReadback | None = None
    eligibility: AutomationSingleChildEligibilityReadback | None = None
    allowed_actions: list[
        Literal[
            "REFRESH_ELIGIBILITY",
            "AUTHORIZE_SINGLE_CHILD",
            "AUTHORIZE_PREVIEW_GATED_SINGLE_CHILD",
            "SAFE_CLOSEOUT_CHILD",
        ]
    ] = Field(
        default_factory=list,
        max_length=1,
    )
    audit_id: str = Field(pattern=_CANONICAL_UUID_PATTERN)
    correlation_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=_VISIBLE_ASCII_PATTERN,
    )
    claimed_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_run_readback(self) -> Self:
        if self.domain is not domain_for_job_kind(self.job_kind):
            raise ValueError("automation_run_domain_kind_mismatch")
        diagnostics = _V1_RUN_DIAGNOSTICS.get(self.state)
        exhausted_preview_terminal = bool(
            self.state is AutomationRunState.BLOCKED
            and self.diagnostic_code == "automation_run_blocked"
            and self.spot_execution_mode in _PREVIEW_GATED_SPOT_MODES
        )
        if diagnostics is None or (
            self.diagnostic_code not in diagnostics
            and not exhausted_preview_terminal
        ):
            raise ValueError("automation_v1_run_diagnostic_invalid")
        if self.call_count_exact is (
            self.coinbase_api_call_count is None
            or self.preview_call_count is None
            or self.create_call_count is None
            or self.cancel_call_count is None
            or self.reconciliation_call_count is None
        ):
            raise ValueError("automation_run_call_count_invalid")
        if self.job_kind is AutomationJobKind.SPOT_CAMPAIGN and (
            (self.cancel_allowance_consumed and not self.create_allowance_consumed)
            or (
                not self.create_allowance_consumed
                and self.create_call_count != 0
            )
            or (
                not self.cancel_allowance_consumed
                and self.cancel_call_count != 0
            )
        ):
            raise ValueError("automation_run_allowance_invalid")
        preview_gated = self.spot_execution_mode in _PREVIEW_GATED_SPOT_MODES
        post_only = self.spot_execution_mode in _POST_ONLY_SPOT_MODES
        if post_only and (
            self.single_child_plan is None
            or self.single_child_plan.post_only is not True
        ):
            raise ValueError("automation_near_market_post_only_required")
        if (
            not post_only
            and self.single_child_plan is not None
            and self.single_child_plan.post_only is not False
        ):
            raise ValueError("automation_spot_plan_post_only_invalid")
        if self.state is AutomationRunState.UNKNOWN_CONSUMED:
            if (
                not self.live_attempt_consumed
                or (
                    self.call_count_exact
                    and not (
                        preview_gated
                        and self.preview_outcome == "UNKNOWN"
                        and self.preview_call_count == 1
                    )
                )
            ):
                raise ValueError("automation_run_unknown_call_count_invalid")
        if preview_gated:
            if (
                (
                    not self.preview_allowance_consumed
                    and (
                        self.preview_outcome is not None
                        or self.preview_call_count != 0
                        or self.preview_failure_class is not None
                        or self.preview_rejection_code is not None
                        or self.preview_warning_present is not None
                        or self.preview_identity_retention != "UNAVAILABLE"
                    )
                )
                or (
                    self.preview_allowance_consumed
                    and self.preview_outcome is None
                    and (
                        self.diagnostic_code
                        != "automation_spot_preview_invocation_started"
                        or self.preview_call_count is not None
                        or self.preview_failure_class is not None
                        or self.preview_rejection_code is not None
                        or self.preview_warning_present is not None
                        or self.preview_identity_retention != "UNAVAILABLE"
                    )
                )
                or (
                    self.preview_outcome == "ACCEPTED"
                    and self.preview_failure_class != "NONE"
                )
                or (
                    self.preview_outcome == "REJECTED"
                    and self.preview_failure_class
                    not in {
                        "DOCUMENTED_REJECTION",
                        "UNCLASSIFIED_REJECTION",
                    }
                )
                or (
                    self.preview_rejection_code is not None
                    and (
                        self.preview_outcome != "REJECTED"
                        or self.preview_failure_class
                        != "DOCUMENTED_REJECTION"
                    )
                )
                or (
                    self.preview_outcome == "UNKNOWN"
                    and self.preview_failure_class
                    not in {
                        "RESPONSE_SCHEMA_INVALID",
                        "HTTP_CLIENT_RESPONSE",
                        "HTTP_SERVER_RESPONSE",
                        "HTTP_REDIRECT_RESPONSE",
                        "HTTP_RESPONSE_INVALID",
                        "TRANSPORT_UNKNOWN",
                    }
                )
                or (
                    self.preview_outcome == "UNKNOWN"
                    and self.preview_failure_class
                    in _EXACT_PREVIEW_UNKNOWN_FAILURE_CLASSES
                    and (
                        not self.call_count_exact
                        or self.preview_call_count != 1
                    )
                )
                or (
                    self.preview_outcome == "UNKNOWN"
                    and self.preview_failure_class == "TRANSPORT_UNKNOWN"
                    and (
                        self.call_count_exact
                        or self.preview_call_count is not None
                    )
                )
                or (
                    self.preview_identity_retention == "HASHED"
                    and self.preview_outcome != "ACCEPTED"
                )
                or (
                    self.preview_identity_retention == "WITHHELD"
                    and self.preview_outcome != "ACCEPTED"
                )
                or (
                    self.preview_outcome == "ACCEPTED"
                    and self.preview_identity_retention
                    not in {"HASHED", "WITHHELD"}
                )
            ):
                raise ValueError("automation_run_preview_evidence_invalid")
        elif (
            self.preview_allowance_consumed
            or self.preview_outcome is not None
            or self.preview_failure_class is not None
            or self.preview_rejection_code is not None
            or self.preview_warning_present is not None
            or self.preview_identity_retention != "UNAVAILABLE"
            or self.preview_call_count != 0
        ):
            raise ValueError("automation_run_preview_evidence_forbidden")
        if (
            self.job_kind is AutomationJobKind.SPOT_CAMPAIGN
            and self.call_count_exact
        ):
            total = cast(int, self.coinbase_api_call_count)
            create = cast(int, self.create_call_count)
            cancel = cast(int, self.cancel_call_count)
            reconciliation = cast(int, self.reconciliation_call_count)
            preview = cast(int, self.preview_call_count)
            if (
                total < preview + create + cancel + reconciliation
            ):
                raise ValueError("automation_run_allowance_invalid")
        post_invocation = self.state in {
            AutomationRunState.INVOCATION_STARTED,
            AutomationRunState.ACTIVE,
            AutomationRunState.TERMINAL,
            AutomationRunState.UNKNOWN_CONSUMED,
        }
        attempt_consumed = (
            self.preview_allowance_consumed if preview_gated else post_invocation
        )
        if self.live_attempt_consumed is not attempt_consumed:
            raise ValueError("automation_run_consumption_invalid")
        if (
            self.job_kind is AutomationJobKind.SPOT_CAMPAIGN
            and self.create_allowance_consumed
            is not (
                post_invocation
                and self.diagnostic_code
                not in {
                    "automation_spot_preview_rejected",
                    "automation_spot_preview_unknown_consumed",
                }
            )
        ):
            raise ValueError("automation_run_consumption_invalid")
        if self.job_kind is not AutomationJobKind.SPOT_CAMPAIGN:
            if any(
                (
                    self.coinbase_api_call_count,
                    self.preview_call_count,
                    self.create_call_count,
                    self.cancel_call_count,
                    self.reconciliation_call_count,
                )
            ):
                raise ValueError("automation_v1_run_call_evidence_invalid")
            if self.create_allowance_consumed or self.cancel_allowance_consumed:
                raise ValueError("automation_v1_run_allowance_forbidden")
            if self.client_order_id is not None:
                raise ValueError("automation_v1_run_child_forbidden")
            if self.single_child_plan is not None or self.eligibility is not None:
                raise ValueError("automation_single_child_readback_forbidden")
        if self.client_order_id is None and self.child_terminal is not None:
            raise ValueError("automation_run_child_terminal_invalid")
        action = self.allowed_actions[0] if self.allowed_actions else None
        if action == "REFRESH_ELIGIBILITY":
            valid = (
                not self.live_execution_available
                and self.job_kind is AutomationJobKind.SPOT_CAMPAIGN
                and self.state is AutomationRunState.BLOCKED
                and self.diagnostic_code
                in {
                    "automation_active_order_catalog_read_not_authorized",
                    "automation_spot_eligibility_refresh_required",
                    "restart_pre_invocation_blocked",
                }
                and self.single_child_plan is not None
                and not self.live_attempt_consumed
                and not self.create_allowance_consumed
            )
        elif action == "AUTHORIZE_SINGLE_CHILD":
            preliminary_authorization_available = bool(
                self.eligibility is not None
                and (
                    self.eligibility.eligible
                    or (
                        self.eligibility.blocker_code
                        == "automation_spot_eligibility_stale"
                        and self.eligibility.call_count_exact
                        and self.eligibility.cycle_number is not None
                        and self.eligibility.completed_categories
                        == self.eligibility.required_categories
                    )
                )
            )
            valid = (
                self.live_execution_available
                and self.state
                is AutomationRunState.AWAITING_OPERATOR_AUTHORIZATION
                and self.diagnostic_code == "awaiting_operator_authorization"
                and preliminary_authorization_available
                and self.single_child_plan is not None
                and self.client_order_id is None
                and not self.create_allowance_consumed
                and not self.cancel_allowance_consumed
                and self.reconciliation_call_count == 0
                and not preview_gated
            )
        elif action == "AUTHORIZE_PREVIEW_GATED_SINGLE_CHILD":
            preliminary_authorization_available = bool(
                self.eligibility is not None
                and (
                    self.eligibility.eligible
                    or (
                        self.eligibility.blocker_code
                        == "automation_spot_eligibility_stale"
                        and self.eligibility.call_count_exact
                        and self.eligibility.cycle_number is not None
                        and self.eligibility.completed_categories
                        == self.eligibility.required_categories
                    )
                )
            )
            valid = (
                preview_gated
                and self.live_execution_available
                and self.state
                is AutomationRunState.AWAITING_OPERATOR_AUTHORIZATION
                and self.diagnostic_code
                in {
                    "awaiting_operator_authorization",
                    "automation_spot_preview_accepted_create_ready",
                }
                and preliminary_authorization_available
                and self.single_child_plan is not None
                and not self.create_allowance_consumed
                and not self.cancel_allowance_consumed
                and self.reconciliation_call_count == 0
                and (
                    not self.preview_allowance_consumed
                    or self.preview_outcome == "ACCEPTED"
                )
            )
        elif action == "SAFE_CLOSEOUT_CHILD":
            valid = (
                self.live_execution_available
                and self.state is AutomationRunState.ACTIVE
                and self.diagnostic_code == "automation_spot_safe_closeout_ready"
                and self.single_child_plan is not None
                and self.client_order_id is not None
                and self.child_terminal is False
                and self.create_allowance_consumed
                and not self.cancel_allowance_consumed
                and self.reconciliation_call_count is not None
                and self.reconciliation_call_count >= 1
            )
        else:
            valid = not self.live_execution_available
        if not valid:
            raise ValueError("automation_run_action_authority_invalid")
        if self.updated_at < self.claimed_at:
            raise ValueError("automation_run_timestamp_invalid")
        return self


class AutomationRunEventItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(pattern=_CANONICAL_UUID_PATTERN)
    run_id: str = Field(pattern=_CANONICAL_UUID_PATTERN)
    sequence: int = Field(ge=1)
    from_state: AutomationRunState | None = None
    state: AutomationRunState
    diagnostic_code: str = Field(min_length=1, max_length=96)
    audit_id: str = Field(pattern=_CANONICAL_UUID_PATTERN)
    correlation_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=_VISIBLE_ASCII_PATTERN,
    )
    recorded_at: datetime

    @model_validator(mode="after")
    def validate_transition_evidence(self) -> Self:
        allowed = {
            "one_shot_run_claimed": {
                (None, AutomationRunState.CLAIMED),
            },
            "preparing": {
                (AutomationRunState.CLAIMED, AutomationRunState.PREPARING),
            },
            "automation_spot_source_gate_resumed": {
                (AutomationRunState.BLOCKED, AutomationRunState.PREPARING),
            },
            "automation_spot_final_admission_started": {
                (
                    AutomationRunState.AWAITING_OPERATOR_AUTHORIZATION,
                    AutomationRunState.PREPARING,
                ),
            },
            "awaiting_operator_authorization": {
                (
                    AutomationRunState.PREPARING,
                    AutomationRunState.AWAITING_OPERATOR_AUTHORIZATION,
                ),
            },
            "invocation_started": {
                (
                    AutomationRunState.AWAITING_OPERATOR_AUTHORIZATION,
                    AutomationRunState.INVOCATION_STARTED,
                ),
            },
            "active": {
                (
                    AutomationRunState.INVOCATION_STARTED,
                    AutomationRunState.ACTIVE,
                ),
            },
            "terminal": {
                (
                    AutomationRunState.INVOCATION_STARTED,
                    AutomationRunState.TERMINAL,
                ),
                (AutomationRunState.ACTIVE, AutomationRunState.TERMINAL),
            },
            "unknown_consumed": {
                (
                    AutomationRunState.INVOCATION_STARTED,
                    AutomationRunState.UNKNOWN_CONSUMED,
                ),
                (
                    AutomationRunState.ACTIVE,
                    AutomationRunState.UNKNOWN_CONSUMED,
                ),
            },
            "automation_run_blocked": {
                (AutomationRunState.CLAIMED, AutomationRunState.BLOCKED),
                (AutomationRunState.PREPARING, AutomationRunState.BLOCKED),
                (
                    AutomationRunState.AWAITING_OPERATOR_AUTHORIZATION,
                    AutomationRunState.BLOCKED,
                ),
            },
            "automation_run_aborted": {
                (AutomationRunState.CLAIMED, AutomationRunState.ABORTED),
                (AutomationRunState.PREPARING, AutomationRunState.ABORTED),
                (
                    AutomationRunState.AWAITING_OPERATOR_AUTHORIZATION,
                    AutomationRunState.ABORTED,
                ),
            },
            "automation_domain_adapter_unavailable": {
                (AutomationRunState.CLAIMED, AutomationRunState.BLOCKED),
            },
            "automation_single_child_plan_missing": {
                (AutomationRunState.CLAIMED, AutomationRunState.BLOCKED),
            },
            "automation_active_order_catalog_read_not_authorized": {
                (AutomationRunState.PREPARING, AutomationRunState.BLOCKED),
                (AutomationRunState.BLOCKED, AutomationRunState.BLOCKED),
            },
            "automation_spot_eligibility_refresh_required": {
                (AutomationRunState.PREPARING, AutomationRunState.BLOCKED),
                (AutomationRunState.BLOCKED, AutomationRunState.BLOCKED),
            },
            "automation_spot_eligibility_invocation_started": {
                (AutomationRunState.PREPARING, AutomationRunState.PREPARING),
            },
            "automation_spot_eligibility_succeeded": {
                (AutomationRunState.PREPARING, AutomationRunState.PREPARING),
            },
            "automation_spot_eligibility_rejected": {
                (AutomationRunState.PREPARING, AutomationRunState.PREPARING),
            },
            "automation_spot_eligibility_unknown": {
                (AutomationRunState.PREPARING, AutomationRunState.PREPARING),
            },
            "automation_spot_create_invocation_started": {
                (
                    AutomationRunState.AWAITING_OPERATOR_AUTHORIZATION,
                    AutomationRunState.INVOCATION_STARTED,
                ),
            },
            "automation_spot_preview_invocation_started": {
                (
                    AutomationRunState.AWAITING_OPERATOR_AUTHORIZATION,
                    AutomationRunState.AWAITING_OPERATOR_AUTHORIZATION,
                ),
            },
            "automation_spot_preview_accepted_create_ready": {
                (
                    AutomationRunState.AWAITING_OPERATOR_AUTHORIZATION,
                    AutomationRunState.AWAITING_OPERATOR_AUTHORIZATION,
                ),
            },
            "automation_spot_preview_rejected": {
                (
                    AutomationRunState.AWAITING_OPERATOR_AUTHORIZATION,
                    AutomationRunState.TERMINAL,
                ),
            },
            "automation_spot_preview_unknown_consumed": {
                (
                    AutomationRunState.AWAITING_OPERATOR_AUTHORIZATION,
                    AutomationRunState.UNKNOWN_CONSUMED,
                ),
            },
            "automation_spot_create_accepted_active": {
                (
                    AutomationRunState.INVOCATION_STARTED,
                    AutomationRunState.ACTIVE,
                ),
            },
            "automation_spot_create_accepted_terminal": {
                (
                    AutomationRunState.INVOCATION_STARTED,
                    AutomationRunState.TERMINAL,
                ),
            },
            "automation_spot_create_rejected": {
                (
                    AutomationRunState.INVOCATION_STARTED,
                    AutomationRunState.TERMINAL,
                ),
            },
            "automation_spot_create_unknown_consumed": {
                (
                    AutomationRunState.INVOCATION_STARTED,
                    AutomationRunState.UNKNOWN_CONSUMED,
                ),
            },
            "automation_spot_safe_closeout_ready": {
                (AutomationRunState.ACTIVE, AutomationRunState.ACTIVE),
            },
            "automation_spot_safe_closeout_invocation_started": {
                (AutomationRunState.ACTIVE, AutomationRunState.ACTIVE),
            },
            "automation_spot_safe_closeout_accepted_terminal": {
                (AutomationRunState.ACTIVE, AutomationRunState.TERMINAL),
            },
            "automation_spot_safe_closeout_accepted_nonterminal": {
                (AutomationRunState.ACTIVE, AutomationRunState.TERMINAL),
            },
            "automation_spot_safe_closeout_rejected": {
                (AutomationRunState.ACTIVE, AutomationRunState.TERMINAL),
            },
            "automation_spot_safe_closeout_unknown_consumed": {
                (
                    AutomationRunState.ACTIVE,
                    AutomationRunState.UNKNOWN_CONSUMED,
                ),
            },
            "automation_spot_cancel_invocation_started": {
                (AutomationRunState.ACTIVE, AutomationRunState.ACTIVE),
            },
            "automation_spot_cancel_accepted_terminal": {
                (AutomationRunState.ACTIVE, AutomationRunState.TERMINAL),
            },
            "automation_spot_cancel_accepted_nonterminal": {
                (AutomationRunState.ACTIVE, AutomationRunState.TERMINAL),
            },
            "automation_spot_cancel_rejected": {
                (AutomationRunState.ACTIVE, AutomationRunState.TERMINAL),
            },
            "automation_spot_cancel_unknown_consumed": {
                (
                    AutomationRunState.ACTIVE,
                    AutomationRunState.UNKNOWN_CONSUMED,
                ),
            },
            "restart_pre_invocation_blocked": {
                (AutomationRunState.CLAIMED, AutomationRunState.BLOCKED),
                (AutomationRunState.PREPARING, AutomationRunState.BLOCKED),
                (
                    AutomationRunState.AWAITING_OPERATOR_AUTHORIZATION,
                    AutomationRunState.BLOCKED,
                ),
            },
            "restart_unknown_consumed": {
                (
                    AutomationRunState.INVOCATION_STARTED,
                    AutomationRunState.UNKNOWN_CONSUMED,
                ),
                (AutomationRunState.ACTIVE, AutomationRunState.UNKNOWN_CONSUMED),
            },
        }
        if (self.from_state, self.state) not in allowed.get(
            self.diagnostic_code, set()
        ):
            raise ValueError("automation_run_event_invalid")
        return self


class AutomationDefinitionEventItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(pattern=_CANONICAL_UUID_PATTERN)
    definition_id: str = Field(pattern=_CANONICAL_UUID_PATTERN)
    from_state: AutomationDefinitionState | None = None
    to_state: AutomationDefinitionState | AutomationScheduleMode
    diagnostic_code: str = Field(min_length=1, max_length=96)
    audit_id: str = Field(pattern=_CANONICAL_UUID_PATTERN)
    correlation_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=_VISIBLE_ASCII_PATTERN,
    )
    recorded_at: datetime

    @model_validator(mode="after")
    def validate_transition_evidence(self) -> Self:
        source = str(getattr(self.from_state, "value", self.from_state)) if self.from_state is not None else None
        target = str(getattr(self.to_state, "value", self.to_state))
        allowed_transitions = {
            "automation_definition_created": {(None, "DRAFT")},
            "automation_definition_enable": {
                ("DRAFT", "ENABLED"),
                ("DISABLED", "ENABLED"),
            },
            "automation_definition_disable": {
                ("DRAFT", "DISABLED"),
                ("ENABLED", "DISABLED"),
                ("PAUSED", "DISABLED"),
                ("DRAINING", "DISABLED"),
            },
            "automation_definition_pause": {("ENABLED", "PAUSED")},
            "automation_definition_resume": {
                ("PAUSED", "ENABLED"),
                ("DRAINING", "ENABLED"),
            },
            "automation_definition_drain": {
                ("ENABLED", "DRAINING"),
                ("PAUSED", "DRAINING"),
            },
            "automation_schedule_set": {
                (None, "MANUAL_ONLY"),
                (None, "INTERVAL_REVIEW_ONLY"),
            },
            "automation_schedule_cleared": {(None, "MANUAL_ONLY")},
        }
        if (source, target) not in allowed_transitions.get(
            self.diagnostic_code, set()
        ):
            raise ValueError("automation_definition_event_invalid")
        return self


class AutomationControlEventItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(pattern=_CANONICAL_UUID_PATTERN)
    from_state: AutomationControlPosture
    to_state: AutomationControlPosture
    diagnostic_code: str = Field(min_length=1, max_length=96)
    audit_id: str = Field(pattern=_CANONICAL_UUID_PATTERN)
    correlation_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=_VISIBLE_ASCII_PATTERN,
    )
    recorded_at: datetime

    @model_validator(mode="after")
    def validate_transition_evidence(self) -> Self:
        transition = (self.from_state.value, self.to_state.value)
        allowed_transitions = {
            "automation_control_pause": {("ACTIVE", "PAUSED")},
            "automation_control_resume": {
                ("PAUSED", "ACTIVE"),
                ("DRAINING", "ACTIVE"),
                ("SHUTDOWN", "ACTIVE"),
            },
            "automation_control_drain": {
                ("ACTIVE", "DRAINING"),
                ("PAUSED", "DRAINING"),
            },
            "automation_control_shutdown": {
                ("ACTIVE", "SHUTDOWN"),
                ("PAUSED", "SHUTDOWN"),
                ("DRAINING", "SHUTDOWN"),
            },
        }
        if transition not in allowed_transitions.get(self.diagnostic_code, set()):
            raise ValueError("automation_control_event_invalid")
        return self


class AutomationFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: AutomationDomain | None = None
    job_kind: AutomationJobKind | None = None
    lifecycle_state: AutomationDefinitionState | None = None
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)


class AutomationRunFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition_id: str | None = Field(
        default=None,
        pattern=_CANONICAL_UUID_PATTERN,
    )
    state: AutomationRunState | None = None
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)


class AutomationPagination(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    total_matching_count: int = Field(ge=0)
    next_offset: int | None = Field(default=None, ge=1)
    has_more: bool

    @model_validator(mode="after")
    def validate_page(self) -> Self:
        page_end = self.offset + self.returned_count
        if self.returned_count > self.limit or self.total_matching_count < page_end:
            raise ValueError("automation_pagination_count_invalid")
        if self.has_more:
            if (
                self.returned_count != self.limit
                or self.next_offset != page_end
                or self.total_matching_count <= page_end
            ):
                raise ValueError("automation_pagination_next_invalid")
        elif self.next_offset is not None or self.total_matching_count > page_end:
            raise ValueError("automation_pagination_terminal_invalid")
        return self


class AutomationDefinitionEventListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["automation_definition_event_list"] = (
        "automation_definition_event_list"
    )
    definition_id: str = Field(pattern=_CANONICAL_UUID_PATTERN)
    count: int = Field(ge=0)
    pagination: AutomationPagination
    items: list[AutomationDefinitionEventItem]
    activity: AutomationNoExchangeActivity = Field(
        default_factory=AutomationNoExchangeActivity
    )

    @model_validator(mode="after")
    def validate_count_and_identity(self) -> Self:
        if self.count != len(self.items) or self.count != self.pagination.returned_count:
            raise ValueError("automation_definition_event_list_count_invalid")
        if any(item.definition_id != self.definition_id for item in self.items):
            raise ValueError("automation_definition_event_identity_mismatch")
        return self


class AutomationControlEventListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["automation_control_event_list"] = "automation_control_event_list"
    count: int = Field(ge=0)
    pagination: AutomationPagination
    items: list[AutomationControlEventItem]
    activity: AutomationNoExchangeActivity = Field(
        default_factory=AutomationNoExchangeActivity
    )

    @model_validator(mode="after")
    def validate_count(self) -> Self:
        if self.count != len(self.items) or self.count != self.pagination.returned_count:
            raise ValueError("automation_control_event_list_count_invalid")
        return self


class AutomationControlPlaneResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["automation_control_plane"] = "automation_control_plane"
    control_plane: AutomationControlPlaneItem
    activity: AutomationNoExchangeActivity = Field(
        default_factory=AutomationNoExchangeActivity
    )


class AutomationDefinitionDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["automation_definition_detail"] = "automation_definition_detail"
    definition: AutomationDefinitionItem
    activity: AutomationNoExchangeActivity = Field(
        default_factory=AutomationNoExchangeActivity
    )


class AutomationDefinitionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["automation_definition_list"] = "automation_definition_list"
    filters: AutomationFilters
    count: int = Field(ge=0)
    pagination: AutomationPagination
    items: list[AutomationDefinitionItem]
    activity: AutomationNoExchangeActivity = Field(
        default_factory=AutomationNoExchangeActivity
    )

    @model_validator(mode="after")
    def validate_count(self) -> Self:
        if self.count != len(self.items) or self.count != self.pagination.returned_count:
            raise ValueError("automation_definition_list_count_invalid")
        return self


class AutomationDefinitionMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["automation_definition_mutation"] = "automation_definition_mutation"
    status: Literal["accepted"] = "accepted"
    definition: AutomationDefinitionItem
    replayed: bool = False
    audit_id: str = Field(pattern=_CANONICAL_UUID_PATTERN)
    correlation_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=_VISIBLE_ASCII_PATTERN,
    )
    activity: AutomationNoExchangeActivity = Field(
        default_factory=AutomationNoExchangeActivity
    )


class AutomationNearMarketCandidatePreparationResponse(BaseModel):
    """Sanitized result of one claimed, no-retry proposal-read cycle."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["automation_near_market_candidate_preparation"] = (
        "automation_near_market_candidate_preparation"
    )
    status: Literal["accepted"] = "accepted"
    outcome: Literal["MATERIALIZED", "BLOCKED", "UNKNOWN"]
    candidate_version: Literal[4, 5, 6]
    spot_execution_mode: Literal[
        "NEAR_MARKET_POST_ONLY_V4",
        "NEAR_MARKET_POST_ONLY_V5",
        "NEAR_MARKET_POST_ONLY_V6",
    ]
    cycle_number: int = Field(ge=1, le=10)
    policy_revision: Literal["BTC_USDC_POST_ONLY_BEST_BID_V1"] = (
        "BTC_USDC_POST_ONLY_BEST_BID_V1"
    )
    diagnostic_code: Literal[
        "automation_near_market_api_key_permissions_rejected",
        "automation_near_market_best_bid_ask_rejected",
        "automation_near_market_fee_summary_rejected",
        "automation_near_market_portfolio_catalog_rejected",
        "automation_near_market_portfolio_configuration_invalid",
        "automation_near_market_preparation_unknown",
        "automation_near_market_product_metadata_rejected",
        "automation_near_market_terms_derived",
        "automation_near_market_wallet_balances_rejected",
        "near_market_fee_invalid",
        "near_market_no_valid_size",
        "near_market_post_only_crossing",
        "near_market_product_blocked",
        "near_market_product_metadata_invalid",
        "near_market_snapshot_future",
        "near_market_snapshot_invalid",
        "near_market_snapshot_stale",
        "near_market_snapshot_timestamp_invalid",
        "near_market_wallet_insufficient",
    ]
    completed_categories: list[
        Literal[
            "api_key_permissions",
            "portfolio_catalog",
            "wallet_balances",
            "product_metadata",
            "best_bid_ask",
            "fee_summary",
        ]
    ] = Field(default_factory=list, max_length=6)
    coinbase_api_call_count: int | None = Field(default=0, ge=0)
    call_count_exact: bool = True
    definition: AutomationDefinitionItem | None = None
    preview_call_count: Literal[0] = 0
    create_call_count: Literal[0] = 0
    cancel_call_count: Literal[0] = 0
    audit_id: str = Field(pattern=_CANONICAL_UUID_PATTERN)
    correlation_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=_VISIBLE_ASCII_PATTERN,
    )
    replayed: bool = False

    @model_validator(mode="after")
    def validate_preparation_evidence(self) -> Self:
        if self.call_count_exact is (self.coinbase_api_call_count is None):
            raise ValueError(
                "automation_near_market_preparation_call_count_invalid"
            )
        expected_mode = f"NEAR_MARKET_POST_ONLY_V{self.candidate_version}"
        if self.spot_execution_mode != expected_mode:
            raise ValueError("automation_near_market_preparation_mode_invalid")
        if (self.outcome == "MATERIALIZED") is (self.definition is None):
            raise ValueError(
                "automation_near_market_preparation_definition_invalid"
            )
        if self.definition is not None and (
            self.definition.spot_execution_mode != self.spot_execution_mode
            or self.definition.single_child_order is None
            or self.definition.single_child_order.post_only is not True
        ):
            raise ValueError(
                "automation_near_market_preparation_definition_invalid"
            )
        return self


class AutomationMinimumSizeCandidatePreparationResponse(BaseModel):
    """Value-blind V4 boundary classification and optional V7-V9 plan."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["automation_minimum_size_candidate_preparation"] = (
        "automation_minimum_size_candidate_preparation"
    )
    status: Literal["accepted"] = "accepted"
    outcome: Literal["MATERIALIZED", "BLOCKED", "UNKNOWN"]
    candidate_version: Literal[7, 8, 9]
    spot_execution_mode: Literal[
        "MINIMUM_SIZE_POST_ONLY_V7",
        "MINIMUM_SIZE_POST_ONLY_V8",
        "MINIMUM_SIZE_POST_ONLY_V9",
    ]
    cycle_number: int = Field(ge=1, le=10)
    policy_revision: Literal[
        "BTC_USDC_POST_ONLY_BEST_BID_MINIMUM_SIZE_V2"
    ] = "BTC_USDC_POST_ONLY_BEST_BID_MINIMUM_SIZE_V2"
    boundary_classification: Literal[
        "minimum_size_v4_base_minimum_conflict",
        "minimum_size_v4_quote_minimum_conflict",
        "minimum_size_v4_increment_conflict",
        "minimum_size_v4_fee_reserve_conflict",
        "minimum_size_v4_boundary_not_reproduced",
    ] | None = None
    diagnostic_code: Literal[
        "automation_minimum_size_api_key_permissions_rejected",
        "automation_minimum_size_api_key_permissions_unknown",
        "automation_minimum_size_best_bid_ask_rejected",
        "automation_minimum_size_best_bid_ask_unknown",
        "automation_minimum_size_fee_summary_rejected",
        "automation_minimum_size_fee_summary_unknown",
        "automation_minimum_size_portfolio_catalog_rejected",
        "automation_minimum_size_portfolio_catalog_unknown",
        "automation_minimum_size_portfolio_configuration_invalid",
        "automation_minimum_size_materialization_unknown",
        "automation_minimum_size_preparation_unknown",
        "automation_minimum_size_product_metadata_rejected",
        "automation_minimum_size_product_metadata_unknown",
        "automation_minimum_size_runner_composition_unknown",
        "automation_minimum_size_wallet_balances_rejected",
        "automation_minimum_size_wallet_balances_unknown",
        "minimum_size_fee_invalid",
        "minimum_size_fee_reserve_cap_conflict",
        "minimum_size_increment_conflict",
        "minimum_size_post_only_crossing",
        "minimum_size_product_blocked",
        "minimum_size_product_metadata_invalid",
        "minimum_size_snapshot_future",
        "minimum_size_snapshot_invalid",
        "minimum_size_snapshot_stale",
        "minimum_size_snapshot_timestamp_invalid",
        "minimum_size_submitted_cap_conflict",
        "minimum_size_v4_base_minimum_conflict",
        "minimum_size_v4_boundary_not_reproduced",
        "minimum_size_v4_fee_reserve_conflict",
        "minimum_size_v4_increment_conflict",
        "minimum_size_v4_quote_minimum_conflict",
        "minimum_size_wallet_insufficient",
    ]
    completed_categories: list[
        Literal[
            "api_key_permissions",
            "portfolio_catalog",
            "wallet_balances",
            "product_metadata",
            "best_bid_ask",
            "fee_summary",
        ]
    ] = Field(default_factory=list, max_length=6)
    coinbase_api_call_count: int | None = Field(default=0, ge=0)
    call_count_exact: bool = True
    definition: AutomationDefinitionItem | None = None
    max_submitted_notional_usdc: Literal["3.10"] = "3.10"
    max_possible_execution_notional_usdc: str | None = Field(
        default=None,
        pattern=_POSITIVE_DECIMAL_PATTERN,
        max_length=64,
    )
    preview_call_count: Literal[0] = 0
    create_call_count: Literal[0] = 0
    cancel_call_count: Literal[0] = 0
    audit_id: str = Field(pattern=_CANONICAL_UUID_PATTERN)
    correlation_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=_VISIBLE_ASCII_PATTERN,
    )
    replayed: bool = False

    @model_validator(mode="after")
    def validate_preparation_evidence(self) -> Self:
        if self.call_count_exact is (self.coinbase_api_call_count is None):
            raise ValueError(
                "automation_minimum_size_preparation_call_count_invalid"
            )
        expected_mode = f"MINIMUM_SIZE_POST_ONLY_V{self.candidate_version}"
        if self.spot_execution_mode != expected_mode:
            raise ValueError("automation_minimum_size_preparation_mode_invalid")
        unknown_outcome = self.outcome == "UNKNOWN"
        unknown_call_count = (
            self.coinbase_api_call_count is None
            and self.call_count_exact is False
        )
        if unknown_outcome is not unknown_call_count:
            raise ValueError(
                "automation_minimum_size_preparation_call_count_invalid"
            )
        unknown_diagnostic = (
            self.diagnostic_code in _MINIMUM_SIZE_UNKNOWN_DIAGNOSTICS
        )
        if unknown_outcome is not unknown_diagnostic:
            raise ValueError(
                "automation_minimum_size_preparation_diagnostic_invalid"
            )
        unknown_prefix_length = _MINIMUM_SIZE_STAGE_UNKNOWN_PREFIX_LENGTH.get(
            self.diagnostic_code
        )
        if unknown_prefix_length is not None and self.completed_categories != list(
            _MINIMUM_SIZE_PREPARATION_CATEGORIES[:unknown_prefix_length]
        ):
            raise ValueError(
                "automation_minimum_size_preparation_unknown_stage_invalid"
            )
        boundary_expected = self.diagnostic_code.startswith("minimum_size_v4_")
        if boundary_expected is (self.boundary_classification is None) or (
            self.boundary_classification is not None
            and self.boundary_classification != self.diagnostic_code
        ):
            raise ValueError(
                "automation_minimum_size_preparation_boundary_invalid"
            )
        if unknown_outcome and self.boundary_classification is not None:
            raise ValueError(
                "automation_minimum_size_preparation_boundary_invalid"
            )
        materialized = self.outcome == "MATERIALIZED"
        if materialized is (self.definition is None):
            raise ValueError(
                "automation_minimum_size_preparation_definition_invalid"
            )
        if materialized is (self.max_possible_execution_notional_usdc is None):
            raise ValueError("automation_minimum_size_preparation_cap_invalid")
        if self.max_possible_execution_notional_usdc is not None:
            cap = Decimal(self.max_possible_execution_notional_usdc)
            if not cap.is_finite() or cap <= 0 or cap >= Decimal("3.10"):
                raise ValueError("automation_minimum_size_preparation_cap_invalid")
        if self.definition is not None and (
            self.definition.spot_execution_mode != self.spot_execution_mode
            or self.definition.single_child_order is None
            or self.definition.single_child_order.post_only is not True
        ):
            raise ValueError(
                "automation_minimum_size_preparation_definition_invalid"
            )
        return self


class AutomationControlMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["automation_control_mutation"] = "automation_control_mutation"
    status: Literal["accepted"] = "accepted"
    control_plane: AutomationControlPlaneItem
    replayed: bool = False
    audit_id: str = Field(pattern=_CANONICAL_UUID_PATTERN)
    correlation_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=_VISIBLE_ASCII_PATTERN,
    )
    activity: AutomationNoExchangeActivity = Field(
        default_factory=AutomationNoExchangeActivity
    )


class AutomationRunDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["automation_run_detail"] = "automation_run_detail"
    run: AutomationRunItem
    activity: AutomationNoExchangeActivity = Field(
        default_factory=AutomationNoExchangeActivity
    )


class AutomationEligibilityCycleMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["automation_eligibility_cycle_mutation"] = (
        "automation_eligibility_cycle_mutation"
    )
    status: Literal["accepted"] = "accepted"
    run: AutomationRunItem
    replayed: bool = False
    audit_id: str = Field(pattern=_CANONICAL_UUID_PATTERN)
    correlation_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=_VISIBLE_ASCII_PATTERN,
    )
    activity: AutomationEligibilityRefreshActivity = Field(
        default_factory=AutomationEligibilityRefreshActivity
    )


class AutomationRunMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["automation_run_mutation"] = "automation_run_mutation"
    status: Literal["accepted"] = "accepted"
    run: AutomationRunItem
    replayed: bool = False
    audit_id: str = Field(pattern=_CANONICAL_UUID_PATTERN)
    correlation_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=_VISIBLE_ASCII_PATTERN,
    )
    activity: AutomationRunMutationActivity = Field(
        default_factory=AutomationRunMutationActivity
    )


class AutomationAtomicMarketSnapshotMutationResponse(BaseModel):
    """Sanitized terminal result for one claimed V10-V12 cycle."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["automation_atomic_market_snapshot_mutation"] = (
        "automation_atomic_market_snapshot_mutation"
    )
    status: Literal["accepted"] = "accepted"
    outcome: Literal["MATERIALIZED", "BLOCKED", "UNKNOWN"]
    candidate_version: Literal[10, 11, 12]
    cycle_number: int = Field(ge=1, le=10)
    diagnostic_code: str = Field(
        min_length=1,
        max_length=96,
        pattern=r"^[a-z0-9_]+$",
    )
    completed_categories: list[AutomationEligibilityCategory] = Field(
        default_factory=list,
        max_length=8,
    )
    coinbase_api_call_count: int | None = Field(default=0, ge=0)
    call_count_exact: bool = True
    market_snapshot_binding: Literal["HASHED", "UNAVAILABLE"]
    run: AutomationRunItem | None = None
    replayed: bool = False
    audit_id: str = Field(pattern=_CANONICAL_UUID_PATTERN)
    correlation_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=_VISIBLE_ASCII_PATTERN,
    )
    activity: AutomationRunMutationActivity = Field(
        default_factory=AutomationRunMutationActivity
    )

    @model_validator(mode="after")
    def validate_atomic_result(self) -> Self:
        materialized = self.outcome == "MATERIALIZED"
        if materialized is (self.run is None):
            raise ValueError("automation_atomic_market_snapshot_run_invalid")
        if materialized is (self.market_snapshot_binding != "HASHED"):
            raise ValueError(
                "automation_atomic_market_snapshot_binding_invalid"
            )
        if self.call_count_exact is (self.coinbase_api_call_count is None):
            raise ValueError(
                "automation_atomic_market_snapshot_call_count_invalid"
            )
        return self


class AutomationRunListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["automation_run_list"] = "automation_run_list"
    filters: AutomationRunFilters
    count: int = Field(ge=0)
    pagination: AutomationPagination
    items: list[AutomationRunItem]
    activity: AutomationNoExchangeActivity = Field(
        default_factory=AutomationNoExchangeActivity
    )

    @model_validator(mode="after")
    def validate_count(self) -> Self:
        if self.count != len(self.items) or self.count != self.pagination.returned_count:
            raise ValueError("automation_run_list_count_invalid")
        return self


class AutomationRunEventListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["automation_run_event_list"] = "automation_run_event_list"
    run_id: str = Field(pattern=_CANONICAL_UUID_PATTERN)
    count: int = Field(ge=0)
    pagination: AutomationPagination
    items: list[AutomationRunEventItem]
    activity: AutomationNoExchangeActivity = Field(
        default_factory=AutomationNoExchangeActivity
    )

    @model_validator(mode="after")
    def validate_count_and_identity(self) -> Self:
        if self.count != len(self.items) or self.count != self.pagination.returned_count:
            raise ValueError("automation_event_list_count_invalid")
        if any(item.run_id != self.run_id for item in self.items):
            raise ValueError("automation_event_run_identity_mismatch")
        if not self.items:
            if self.pagination.offset == 0:
                raise ValueError("automation_event_chain_invalid")
            return self
        sequences = [item.sequence for item in self.items]
        if len(sequences) != len(set(sequences)):
            raise ValueError("automation_event_sequence_duplicate")
        expected_sequences = list(
            range(
                self.pagination.offset + 1,
                self.pagination.offset + self.count + 1,
            )
        )
        if sequences != expected_sequences:
            raise ValueError("automation_event_sequence_invalid")
        if self.items:
            if self.pagination.offset == 0:
                if self.items[0].from_state is not None:
                    raise ValueError("automation_event_chain_invalid")
            elif self.items[0].from_state is None:
                raise ValueError("automation_event_chain_invalid")
            if any(
                current.from_state is not previous.state
                for previous, current in zip(self.items, self.items[1:])
            ):
                raise ValueError("automation_event_chain_invalid")
        return self
