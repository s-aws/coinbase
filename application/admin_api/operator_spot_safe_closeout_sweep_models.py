"""Strict generated-contract source for the Goal 16 Spot closeout sweep."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


GOAL_ID = "operator_spot_sweep_safe_closeout_v1"
POLICY_REVISION = "OPERATOR_SPOT_SWEEP_SAFE_CLOSEOUT_V1"
LIVE_AUTHORITY_BLOCKER = (
    "operator_spot_sweep_live_read_authority_incomplete"
)

_UUID = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$"
)
_SHA256 = r"^[0-9a-f]{64}$"
_DIAGNOSTIC = r"^operator_spot_sweep_[a-z0-9_]{1,75}$"
_EVIDENCE_ID = r"^[A-Za-z0-9._:@|/-]{1,255}$"

OperatorSpotSafeCloseoutStatus = Literal["PENDING", "OPEN", "QUEUED"]
OperatorSpotSafeCloseoutProvenance = Literal[
    "ADMIN_FILL_FOLLOW_UP",
    "ADMIN_HOTPOINT_CHILD",
]
OperatorSpotSafeCloseoutSweepState = Literal[
    "READY",
    "PAUSED",
    "IN_PROGRESS",
    "COMPLETE",
    "ABORTED",
    "QUARANTINED",
]
OperatorSpotSafeCloseoutSweepItemState = Literal[
    "PENDING",
    "IN_FLIGHT",
    "CANCELLED",
    "NOT_REQUIRED",
    "REJECTED",
    "UNKNOWN",
    "QUARANTINED",
    "ABORTED",
]
OperatorSpotSafeCloseoutAllowedAction = Literal[
    "CREATE_SWEEP",
    "PAUSE",
    "RESUME",
    "ABORT",
]


class OperatorSpotSafeCloseoutCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_order_id: str = Field(pattern=_UUID)
    root_client_order_id: str = Field(pattern=_UUID)
    product_id: Literal["BTC-USDC"]
    status: OperatorSpotSafeCloseoutStatus
    ownership_provenance: OperatorSpotSafeCloseoutProvenance
    portfolio_scope_sha256: str = Field(pattern=_SHA256)
    predecessor_evidence_sha256: str = Field(pattern=_SHA256)
    candidate_evidence_sha256: str = Field(pattern=_SHA256)
    created_at: datetime


class OperatorSpotSafeCloseoutCandidatePage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["operator_spot_safe_closeout_candidates"] = (
        "operator_spot_safe_closeout_candidates"
    )
    goal_id: Literal["operator_spot_sweep_safe_closeout_v1"] = GOAL_ID
    items: list[OperatorSpotSafeCloseoutCandidate]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    status_filter: OperatorSpotSafeCloseoutStatus | None = None
    ownership_provenance_filter: (
        OperatorSpotSafeCloseoutProvenance | None
    ) = None
    configured_portfolio_scope_sha256: str = Field(pattern=_SHA256)
    diagnostic_code: str = Field(pattern=_DIAGNOSTIC)
    allowed_actions: list[Literal["CREATE_SWEEP"]] = Field(
        default_factory=list,
        max_length=1,
    )
    page_load_coinbase_calls: Literal[0] = 0
    total_exchange_call_count: Literal[0] = 0
    browser_authority: Literal["display_and_forward_only"] = (
        "display_and_forward_only"
    )
    command_service_method: Literal[
        "list_safe_closeout_candidates"
    ] = "list_safe_closeout_candidates"

    @model_validator(mode="after")
    def validate_page(
        self,
    ) -> "OperatorSpotSafeCloseoutCandidatePage":
        if self.total < len(self.items):
            raise ValueError("operator_spot_sweep_candidate_page_invalid")
        if self.allowed_actions and (self.total == 0 or not self.items):
            raise ValueError(
                "operator_spot_sweep_candidate_action_invalid"
            )
        return self


class OperatorSpotSafeCloseoutSweepSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_order_id: str = Field(pattern=_UUID)
    expected_candidate_evidence_sha256: str = Field(pattern=_SHA256)


class OperatorSpotSafeCloseoutSweepCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[OperatorSpotSafeCloseoutSweepSelectionRequest] = Field(
        min_length=1,
        max_length=3,
    )
    operator_reason: str = Field(min_length=10, max_length=240)
    confirm_create_cancel_only_sweep: Literal[True]

    @model_validator(mode="after")
    def validate_unique_items(
        self,
    ) -> "OperatorSpotSafeCloseoutSweepCreateRequest":
        identities = [item.client_order_id for item in self.items]
        if len(set(identities)) != len(identities):
            raise ValueError("operator_spot_sweep_duplicate_candidate")
        return self


class OperatorSpotSafeCloseoutSweepActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    expected_plan_sha256: str = Field(pattern=_SHA256)
    operator_reason: str = Field(min_length=10, max_length=240)
    confirm_local_control_action: Literal[True]


class OperatorSpotSafeCloseoutSweepAdvanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    expected_plan_sha256: str = Field(pattern=_SHA256)
    confirm_advance_cancel_only_sweep: Literal[True]
    acknowledge_unknown_or_partial_result_quarantines_sweep: Literal[True]


class OperatorSpotSafeCloseoutSweepItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: int = Field(ge=1, le=3)
    client_order_id: str = Field(pattern=_UUID)
    root_client_order_id: str = Field(pattern=_UUID)
    product_id: Literal["BTC-USDC"]
    status: OperatorSpotSafeCloseoutStatus
    ownership_provenance: OperatorSpotSafeCloseoutProvenance
    portfolio_scope_sha256: str = Field(pattern=_SHA256)
    predecessor_evidence_sha256: str = Field(pattern=_SHA256)
    candidate_evidence_sha256: str = Field(pattern=_SHA256)
    state: OperatorSpotSafeCloseoutSweepItemState
    diagnostic_code: str = Field(pattern=_DIAGNOSTIC)
    cancel_allowance_state: Literal["NOT_GRANTED"] = "NOT_GRANTED"
    cancel_allowance_consumed: Literal[False] = False
    pre_cancel_exact_read_call_count: Literal[0] = 0
    cancel_call_count: Literal[0] = 0
    post_cancel_exact_read_call_count: Literal[0] = 0
    last_event_sequence: int = Field(ge=1)
    updated_at: datetime


class OperatorSpotSafeCloseoutSweepEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(pattern=_UUID)
    event_sequence: int = Field(ge=1)
    event_type: Literal[
        "PLAN_CREATED",
        "SWEEP_PAUSED",
        "SWEEP_RESUMED",
        "SWEEP_ABORTED",
        "SWEEP_QUARANTINED",
    ]
    diagnostic_code: str = Field(pattern=_DIAGNOSTIC)
    correlation_id: str = Field(pattern=_EVIDENCE_ID)
    evidence_sha256: str = Field(pattern=_SHA256)
    recorded_at: datetime


class OperatorSpotSafeCloseoutAllowance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal[
        "API_KEY_PERMISSIONS",
        "PORTFOLIO_CATALOG",
        "PRE_CANCEL_EXACT_ORDER_READ",
        "CANCEL",
        "POST_CANCEL_EXACT_ORDER_READ",
    ]
    state: Literal["NOT_GRANTED"] = "NOT_GRANTED"
    executable: Literal[False] = False
    consumed: Literal[False] = False
    call_count: Literal[0] = 0


class OperatorSpotSafeCloseoutSweepReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["operator_spot_safe_closeout_sweep"] = (
        "operator_spot_safe_closeout_sweep"
    )
    goal_id: Literal["operator_spot_sweep_safe_closeout_v1"] = GOAL_ID
    policy_revision: Literal[
        "OPERATOR_SPOT_SWEEP_SAFE_CLOSEOUT_V1"
    ] = POLICY_REVISION
    sweep_id: str = Field(pattern=_UUID)
    revision: int = Field(ge=1)
    state: OperatorSpotSafeCloseoutSweepState
    diagnostic_code: str = Field(pattern=_DIAGNOSTIC)
    plan_sha256: str = Field(pattern=_SHA256)
    configured_portfolio_scope_sha256: str = Field(pattern=_SHA256)
    items: list[OperatorSpotSafeCloseoutSweepItem] = Field(
        min_length=1,
        max_length=3,
    )
    events: list[OperatorSpotSafeCloseoutSweepEvent] = Field(
        min_length=1,
        max_length=32,
    )
    candidate_count: int = Field(ge=1, le=3)
    allowed_actions: list[
        Literal["PAUSE", "RESUME", "ABORT"]
    ] = Field(default_factory=list, max_length=2)
    blocker_codes: list[
        Literal[
            "operator_spot_sweep_live_read_authority_incomplete"
        ]
    ] = Field(default_factory=lambda: [LIVE_AUTHORITY_BLOCKER])
    allowances: list[OperatorSpotSafeCloseoutAllowance] = Field(
        min_length=5,
        max_length=5,
    )
    local_cycles_used: int = Field(ge=1, le=10)
    local_cycles_max: Literal[10] = 10
    exchange_cycles_started: Literal[0] = 0
    partial_result_quarantine: bool
    live_read_authority_complete: Literal[False] = False
    live_cancel_authority_complete: Literal[False] = False
    read_allowances_consumed: Literal[False] = False
    cancel_allowance_consumed: Literal[False] = False
    exact_read_call_count: Literal[0] = 0
    cancel_call_count: Literal[0] = 0
    create_call_count: Literal[0] = 0
    total_exchange_call_count: Literal[0] = 0
    page_load_coinbase_calls: Literal[0] = 0
    zero_creates: Literal[True] = True
    latest_idempotency_key_sha256: str = Field(pattern=_SHA256)
    latest_payload_sha256: str = Field(pattern=_SHA256)
    latest_actor_id_sha256: str = Field(pattern=_SHA256)
    latest_evidence_sha256: str = Field(pattern=_SHA256)
    command_replayed: bool = False
    correlation_id: str = Field(pattern=_EVIDENCE_ID)
    operator_intent: Literal[
        "create_operator_spot_safe_closeout_sweep",
        "pause_operator_spot_safe_closeout_sweep",
        "resume_operator_spot_safe_closeout_sweep",
        "abort_operator_spot_safe_closeout_sweep",
    ] | None
    command_service_method: Literal[
        "get_safe_closeout_sweep",
        "get_current_safe_closeout_sweep",
        "create_safe_closeout_sweep",
        "pause_safe_closeout_sweep",
        "resume_safe_closeout_sweep",
        "abort_safe_closeout_sweep",
    ]
    browser_authority: Literal["display_and_forward_only"] = (
        "display_and_forward_only"
    )
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_readback(
        self,
    ) -> "OperatorSpotSafeCloseoutSweepReadback":
        expected_actions = {
            "READY": ["PAUSE", "ABORT"],
            "PAUSED": ["RESUME", "ABORT"],
            "IN_PROGRESS": [],
            "COMPLETE": [],
            "ABORTED": [],
            "QUARANTINED": [],
        }[self.state]
        if (
            len(set(self.allowed_actions)) != len(self.allowed_actions)
            or any(
                action not in expected_actions
                for action in self.allowed_actions
            )
            or self.allowed_actions != [
                action
                for action in expected_actions
                if action in self.allowed_actions
            ]
        ):
            raise ValueError(
                "operator_spot_sweep_allowed_actions_invalid"
            )
        if self.local_cycles_used >= self.local_cycles_max and (
            self.allowed_actions
        ):
            raise ValueError(
                "operator_spot_sweep_cycle_cap_actions_invalid"
            )
        if self.partial_result_quarantine != (
            self.state == "QUARANTINED"
        ):
            raise ValueError(
                "operator_spot_sweep_quarantine_state_invalid"
            )
        if self.candidate_count != len(self.items):
            raise ValueError("operator_spot_sweep_item_count_invalid")
        if [item.position for item in self.items] != list(
            range(1, len(self.items) + 1)
        ):
            raise ValueError("operator_spot_sweep_item_order_invalid")
        event_sequences = [
            event.event_sequence for event in self.events
        ]
        if any(
            current >= following
            for current, following in zip(
                event_sequences,
                event_sequences[1:],
                strict=False,
            )
        ):
            raise ValueError("operator_spot_sweep_event_order_invalid")
        if len(self.events) != self.revision:
            raise ValueError(
                "operator_spot_sweep_event_revision_invalid"
            )
        if any(
            item.last_event_sequence not in event_sequences
            for item in self.items
        ):
            raise ValueError(
                "operator_spot_sweep_item_event_reference_invalid"
            )
        if self.blocker_codes != [LIVE_AUTHORITY_BLOCKER]:
            raise ValueError("operator_spot_sweep_blocker_invalid")
        expected_categories = [
            "API_KEY_PERMISSIONS",
            "PORTFOLIO_CATALOG",
            "PRE_CANCEL_EXACT_ORDER_READ",
            "CANCEL",
            "POST_CANCEL_EXACT_ORDER_READ",
        ]
        if [
            allowance.category for allowance in self.allowances
        ] != expected_categories:
            raise ValueError("operator_spot_sweep_allowances_invalid")
        if self.state == "ABORTED" and any(
            item.state != "ABORTED" for item in self.items
        ):
            raise ValueError("operator_spot_sweep_abort_state_invalid")
        if self.state == "QUARANTINED" and not any(
            item.state == "QUARANTINED" for item in self.items
        ):
            raise ValueError(
                "operator_spot_sweep_quarantine_items_invalid"
            )
        if self.state == "QUARANTINED" and any(
            item.state in {"PENDING", "IN_FLIGHT", "UNKNOWN"}
            for item in self.items
        ):
            raise ValueError(
                "operator_spot_sweep_quarantine_items_invalid"
            )
        if self.command_service_method in {
            "get_safe_closeout_sweep",
            "get_current_safe_closeout_sweep",
        }:
            if self.operator_intent is not None:
                raise ValueError(
                    "operator_spot_sweep_read_method_invalid"
                )
        elif self.operator_intent is None:
            raise ValueError(
                "operator_spot_sweep_mutation_method_invalid"
            )
        return self


__all__ = [
    "GOAL_ID",
    "LIVE_AUTHORITY_BLOCKER",
    "POLICY_REVISION",
    "OperatorSpotSafeCloseoutAllowance",
    "OperatorSpotSafeCloseoutCandidate",
    "OperatorSpotSafeCloseoutCandidatePage",
    "OperatorSpotSafeCloseoutSweepActionRequest",
    "OperatorSpotSafeCloseoutSweepAdvanceRequest",
    "OperatorSpotSafeCloseoutSweepCreateRequest",
    "OperatorSpotSafeCloseoutSweepEvent",
    "OperatorSpotSafeCloseoutSweepItem",
    "OperatorSpotSafeCloseoutSweepReadback",
    "OperatorSpotSafeCloseoutSweepSelectionRequest",
]
