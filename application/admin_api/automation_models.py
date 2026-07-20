"""Strict public models for the local operator automation control plane.

The models deliberately contain no generic executor payload and no exchange
identifier.  A job kind determines its backend domain; callers cannot select a
domain independently or use a Spot definition to imply Futures authority.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Self

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
_V1_RUN_DIAGNOSTICS = {
    AutomationRunState.CLAIMED: frozenset(
        {"one_shot_run_claimed"}
    ),
    AutomationRunState.BLOCKED: frozenset(
        {
            "automation_domain_adapter_unavailable",
            "restart_pre_invocation_blocked",
        }
    ),
    AutomationRunState.UNKNOWN_CONSUMED: frozenset(
        {"restart_unknown_consumed"}
    ),
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
    """Fixed current-request accounting for all v1 control-plane routes."""

    model_config = ConfigDict(extra="forbid")

    coinbase_api_call_count: Literal[0] = 0
    exchange_mutation_count: Literal[0] = 0
    create_call_count: Literal[0] = 0
    cancel_call_count: Literal[0] = 0
    recurring_worker_started: Literal[False] = False


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


class AutomationDefinitionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=120)
    job_kind: AutomationJobKind
    product_ids: list[str] = Field(default_factory=list, max_length=100)

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
        return self


class AutomationDefinitionLifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

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


class AutomationControlPlaneItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    posture: AutomationControlPosture
    local_admission_enabled: bool
    recurring_worker_started: Literal[False] = False
    live_scheduler_enabled: Literal[False] = False
    coinbase_api_call_count: Literal[0] = 0
    exchange_mutation_count: Literal[0] = 0
    definition_create_allowed: bool = False
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


class AutomationDefinitionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition_id: str = Field(pattern=_CANONICAL_UUID_PATTERN)
    revision: int = Field(ge=1)
    display_name: str = Field(min_length=1, max_length=120)
    domain: AutomationDomain
    job_kind: AutomationJobKind
    lifecycle_state: AutomationDefinitionState
    product_ids: list[str] = Field(default_factory=list, max_length=100)
    schedule: AutomationDefinitionSchedule
    adapter_status: Literal["UNAVAILABLE"] = "UNAVAILABLE"
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
    adapter_status: Literal["UNAVAILABLE"] = "UNAVAILABLE"
    live_attempt_consumed: bool = False
    coinbase_api_call_count: int = Field(default=0, ge=0)
    create_call_count: int = Field(default=0, ge=0)
    cancel_call_count: int = Field(default=0, ge=0)
    client_order_id: str | None = Field(
        default=None,
        pattern=_CANONICAL_UUID_PATTERN,
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
    def validate_v1_run_readback(self) -> Self:
        if self.domain is not domain_for_job_kind(self.job_kind):
            raise ValueError("automation_run_domain_kind_mismatch")
        diagnostics = _V1_RUN_DIAGNOSTICS.get(self.state)
        if diagnostics is None:
            raise ValueError("automation_v1_run_state_not_readable")
        if self.diagnostic_code not in diagnostics:
            raise ValueError("automation_v1_run_diagnostic_invalid")
        expected_consumed = self.state is AutomationRunState.UNKNOWN_CONSUMED
        if self.live_attempt_consumed is not expected_consumed:
            raise ValueError("automation_v1_run_consumption_invalid")
        if any(
            (
                self.coinbase_api_call_count,
                self.create_call_count,
                self.cancel_call_count,
            )
        ):
            raise ValueError("automation_v1_run_call_evidence_invalid")
        if self.client_order_id is not None:
            raise ValueError("automation_v1_run_child_forbidden")
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
    activity: AutomationNoExchangeActivity = Field(
        default_factory=AutomationNoExchangeActivity
    )


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
