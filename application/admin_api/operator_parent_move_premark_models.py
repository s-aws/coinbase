"""Typed Admin API contract for one direct-parent move premark."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ParentMoveState = Literal[
    "UNCONSUMED",
    "PLANNED",
    "SOURCE_CANCEL_CLAIMED",
    "SOURCE_CANCEL_BOUNDARY_CROSSED",
    "SOURCE_CANCELLED",
    "SOURCE_CANCEL_REJECTED",
    "SOURCE_CANCEL_UNKNOWN",
    "REPLACEMENT_CREATE_CLAIMED",
    "REPLACEMENT_CREATE_BOUNDARY_CROSSED",
    "REPLACEMENT_CREATED",
    "REPLACEMENT_CREATE_REJECTED",
    "REPLACEMENT_CREATE_UNKNOWN",
    "SUCCESSOR_CLOSEOUT_CANCEL_CLAIMED",
    "SUCCESSOR_CLOSEOUT_CANCEL_BOUNDARY_CROSSED",
    "SUCCESSOR_CLOSED",
    "SUCCESSOR_CLOSEOUT_CANCEL_REJECTED",
    "SUCCESSOR_CLOSEOUT_CANCEL_UNKNOWN",
]
ParentMoveAction = Literal[
    "PREMARK",
    "EXECUTE_PARENT_MOVE",
    "SAFE_CLOSEOUT",
]
_SHA256 = r"^[0-9a-f]{64}$"
_UUID = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_DECIMAL = r"^(0|[1-9]\d*)(\.\d+)?$"
_DIAGNOSTIC = r"^operator_parent_move_[a-z0-9_]{1,75}$"
_EVIDENCE_ID = r"^[A-Za-z0-9._:@|/-]{1,255}$"
_LIFECYCLE_CALL_COUNTS = {
    "UNCONSUMED": frozenset({(0, 0, 0)}),
    "PLANNED": frozenset({(0, 0, 0)}),
    "SOURCE_CANCEL_CLAIMED": frozenset({(0, 0, 0)}),
    "SOURCE_CANCEL_BOUNDARY_CROSSED": frozenset({(1, 0, 0)}),
    "SOURCE_CANCELLED": frozenset({(1, 0, 0)}),
    "SOURCE_CANCEL_REJECTED": frozenset({(0, 0, 0), (1, 0, 0)}),
    "SOURCE_CANCEL_UNKNOWN": frozenset({(0, 0, 0), (1, 0, 0)}),
    "REPLACEMENT_CREATE_CLAIMED": frozenset({(1, 0, 0)}),
    "REPLACEMENT_CREATE_BOUNDARY_CROSSED": frozenset({(1, 1, 0)}),
    "REPLACEMENT_CREATED": frozenset({(1, 1, 0)}),
    "REPLACEMENT_CREATE_REJECTED": frozenset(
        {(1, 0, 0), (1, 1, 0)}
    ),
    "REPLACEMENT_CREATE_UNKNOWN": frozenset(
        {(1, 0, 0), (1, 1, 0)}
    ),
    "SUCCESSOR_CLOSEOUT_CANCEL_CLAIMED": frozenset({(1, 1, 0)}),
    "SUCCESSOR_CLOSEOUT_CANCEL_BOUNDARY_CROSSED": frozenset(
        {(1, 1, 1)}
    ),
    "SUCCESSOR_CLOSED": frozenset({(1, 1, 1)}),
    "SUCCESSOR_CLOSEOUT_CANCEL_REJECTED": frozenset(
        {(1, 1, 0), (1, 1, 1)}
    ),
    "SUCCESSOR_CLOSEOUT_CANCEL_UNKNOWN": frozenset(
        {(1, 1, 0), (1, 1, 1)}
    ),
}
_LIFECYCLE_PHASES = {
    "UNCONSUMED": frozenset({None}),
    "PLANNED": frozenset({"PLAN", "EXECUTE"}),
    "SOURCE_CANCEL_CLAIMED": frozenset({"EXECUTE"}),
    "SOURCE_CANCEL_BOUNDARY_CROSSED": frozenset({"EXECUTE"}),
    "SOURCE_CANCELLED": frozenset({"EXECUTE"}),
    "SOURCE_CANCEL_REJECTED": frozenset({"EXECUTE"}),
    "SOURCE_CANCEL_UNKNOWN": frozenset({"EXECUTE"}),
    "REPLACEMENT_CREATE_CLAIMED": frozenset({"EXECUTE"}),
    "REPLACEMENT_CREATE_BOUNDARY_CROSSED": frozenset({"EXECUTE"}),
    "REPLACEMENT_CREATED": frozenset({"EXECUTE", "CLOSEOUT"}),
    "REPLACEMENT_CREATE_REJECTED": frozenset({"EXECUTE"}),
    "REPLACEMENT_CREATE_UNKNOWN": frozenset({"EXECUTE"}),
    "SUCCESSOR_CLOSEOUT_CANCEL_CLAIMED": frozenset({"CLOSEOUT"}),
    "SUCCESSOR_CLOSEOUT_CANCEL_BOUNDARY_CROSSED": frozenset(
        {"CLOSEOUT"}
    ),
    "SUCCESSOR_CLOSED": frozenset({"CLOSEOUT"}),
    "SUCCESSOR_CLOSEOUT_CANCEL_REJECTED": frozenset({"CLOSEOUT"}),
    "SUCCESSOR_CLOSEOUT_CANCEL_UNKNOWN": frozenset({"CLOSEOUT"}),
}


class OperatorParentMovePlan(BaseModel):
    """Allowlisted immutable plan; it contains no exchange-native identity."""

    model_config = ConfigDict(extra="forbid")

    goal_id: Literal["operator_parent_move_premark_lifecycle_v1"]
    policy_revision: Literal["PARENT_MOVE_PREMARK_V1"]
    source_client_order_id: str = Field(pattern=_UUID)
    reserved_successor_client_order_id: str = Field(pattern=_UUID)
    portfolio_scope_sha256: str = Field(pattern=_SHA256)
    product_id: Literal["BTC-USDC"]
    side: Literal["BUY", "SELL"]
    base_size: str = Field(pattern=_DECIMAL)
    source_limit_price: str = Field(pattern=_DECIMAL)
    requested_limit_price: str = Field(pattern=_DECIMAL)
    replacement_limit_price: str = Field(pattern=_DECIMAL)
    price_increment: str = Field(pattern=_DECIMAL)
    base_increment: str = Field(pattern=_DECIMAL)
    base_min_size: str = Field(pattern=_DECIMAL)
    quote_min_size: str = Field(pattern=_DECIMAL)
    source_status: str
    source_filled_size: str = Field(pattern=_DECIMAL)
    source_order_type: Literal["LIMIT"]
    source_time_in_force: Literal["GOOD_UNTIL_CANCELLED"]
    source_ownership_provenance: Literal["ADMIN_MANUAL_ROOT"]
    post_only: Literal[True]
    submitted_notional: str = Field(pattern=_DECIMAL)
    possible_execution_notional: str = Field(pattern=_DECIMAL)
    submitted_notional_cap: Literal["3.10"]
    possible_execution_notional_cap: Literal["1.00"]
    zero_fill_proven: Literal[True]
    system_owned: Literal[True]
    source_evidence_sha256: str = Field(pattern=_SHA256)


class OperatorParentMoveSourceSelection(BaseModel):
    """Current call-free Goal 12 source projection and local eligibility."""

    model_config = ConfigDict(extra="forbid")

    client_order_id: str = Field(pattern=_UUID)
    found: bool
    eligible: bool
    diagnostic_code: str = Field(pattern=_DIAGNOSTIC)
    product_id: str | None = None
    side: Literal["BUY", "SELL"] | None = None
    status: str | None = None
    order_type: str | None = None
    time_in_force: str | None = None
    size: str | None = Field(default=None, pattern=_DECIMAL)
    limit_price: str | None = Field(default=None, pattern=_DECIMAL)
    filled_size: str | None = Field(default=None, pattern=_DECIMAL)
    ownership_provenance: str | None = None
    authoritatively_nonterminal: bool = False
    cancel_eligible: bool = False
    zero_fill_proven: bool = False
    system_owned: bool = False
    direct_root: bool = False
    post_only_compatible: bool = False
    legacy_pending_move: bool | None = None
    portfolio_scope_sha256: str | None = Field(
        default=None,
        pattern=_SHA256,
    )
    source_evidence_sha256: str | None = Field(
        default=None,
        pattern=_SHA256,
    )

    @model_validator(mode="after")
    def validate_source_selection(
        self,
    ) -> "OperatorParentMoveSourceSelection":
        if not self.found:
            if self.eligible or any(
                value is not None
                for value in (
                    self.product_id,
                    self.side,
                    self.status,
                    self.order_type,
                    self.time_in_force,
                    self.size,
                    self.limit_price,
                    self.filled_size,
                    self.ownership_provenance,
                    self.legacy_pending_move,
                    self.portfolio_scope_sha256,
                    self.source_evidence_sha256,
                )
            ):
                raise ValueError(
                    "operator_parent_move_source_selection_invalid"
                )
        if self.eligible and not (
            self.found
            and self.diagnostic_code
            == "operator_parent_move_source_eligible"
            and self.authoritatively_nonterminal
            and self.cancel_eligible
            and self.zero_fill_proven
            and self.system_owned
            and self.direct_root
            and self.post_only_compatible
            and self.legacy_pending_move is False
            and self.portfolio_scope_sha256 is not None
            and self.source_evidence_sha256 is not None
        ):
            raise ValueError(
                "operator_parent_move_source_eligibility_invalid"
            )
        return self


class OperatorParentMovePremarkReadback(BaseModel):
    """Truthful local lifecycle projection for the routed operator UI."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["operator_parent_move_premark"] = (
        "operator_parent_move_premark"
    )
    goal_id: Literal["operator_parent_move_premark_lifecycle_v1"] = (
        "operator_parent_move_premark_lifecycle_v1"
    )
    state: ParentMoveState
    diagnostic_code: str = Field(pattern=_DIAGNOSTIC)
    source_client_order_id: str = Field(pattern=_UUID)
    source_client_order_id_sha256: str = Field(pattern=_SHA256)
    reserved_successor_client_order_id: str | None = Field(
        default=None,
        pattern=_UUID,
    )
    reserved_successor_client_order_id_sha256: str | None = Field(
        default=None,
        pattern=_SHA256,
    )
    source_selection: OperatorParentMoveSourceSelection
    plan: OperatorParentMovePlan | None = None
    plan_sha256: str | None = Field(default=None, pattern=_SHA256)
    allowed_actions: list[ParentMoveAction] = Field(default_factory=list)
    planning_terms_complete: bool
    live_authority_terms_complete: Literal[False] = False
    execution_authority_enabled: bool
    environment: Literal["local"] = "local"
    portfolio_profile_alias: Literal["Test"] = "Test"
    max_submitted_notional_usdc: Literal["3.10"] = "3.10"
    max_possible_execution_notional_usdc: Literal["1.00"] = "1.00"
    browser_authority: Literal["display_and_forward_only"] = (
        "display_and_forward_only"
    )
    page_load_coinbase_calls: Literal[0] = 0
    raw_response_persisted: Literal[False] = False
    raw_exception_persisted: Literal[False] = False
    private_identifiers_included: Literal[False] = False
    source_follow_up_suppressed: bool = False
    source_cancel_allowance_consumed: bool = False
    source_cancel_call_count: int = Field(default=0, ge=0, le=1)
    replacement_create_allowance_consumed: bool = False
    replacement_create_call_count: int = Field(default=0, ge=0, le=1)
    successor_closeout_cancel_allowance_consumed: bool = False
    successor_closeout_cancel_call_count: int = Field(
        default=0,
        ge=0,
        le=1,
    )
    cycle_count: int = Field(default=0, ge=0, le=10)
    latest_cycle_number: int | None = Field(default=None, ge=1, le=10)
    latest_cycle_phase: Literal["PLAN", "EXECUTE", "CLOSEOUT"] | None = None
    latest_cycle_status: Literal["IN_FLIGHT", "COMPLETED"] | None = None
    latest_cycle_correlation_id: str | None = Field(
        default=None,
        pattern=_EVIDENCE_ID,
    )
    latest_cycle_actor_id_sha256: str | None = Field(
        default=None,
        pattern=_SHA256,
    )
    latest_cycle_idempotency_key_sha256: str | None = Field(
        default=None,
        pattern=_SHA256,
    )
    latest_cycle_payload_sha256: str | None = Field(
        default=None,
        pattern=_SHA256,
    )
    latest_cycle_evidence_sha256: str | None = Field(
        default=None,
        pattern=_SHA256,
    )
    active_cycle_number: int | None = Field(default=None, ge=1, le=10)
    active_cycle_phase: Literal["PLAN", "EXECUTE", "CLOSEOUT"] | None = None
    active_cycle_status: Literal["IN_FLIGHT", "COMPLETED"] | None = None
    correlation_id: str | None = Field(
        default=None,
        pattern=_EVIDENCE_ID,
    )
    command_replayed: bool = False
    created_at: str | None = None
    updated_at: str | None = None

    @model_validator(mode="after")
    def validate_readback(
        self,
    ) -> "OperatorParentMovePremarkReadback":
        if self.source_client_order_id_sha256 != _sha(
            self.source_client_order_id
        ):
            raise ValueError(
                "operator_parent_move_source_hash_invalid"
            )
        if (
            self.source_selection.client_order_id
            != self.source_client_order_id
        ):
            raise ValueError(
                "operator_parent_move_source_selection_binding_invalid"
            )
        if len(self.allowed_actions) != len(set(self.allowed_actions)):
            raise ValueError(
                "operator_parent_move_allowed_actions_invalid"
            )
        if any(
            action in {"EXECUTE_PARENT_MOVE", "SAFE_CLOSEOUT"}
            for action in self.allowed_actions
        ):
            raise ValueError(
                "operator_parent_move_live_action_not_authorized"
            )
        if "PREMARK" in self.allowed_actions and not (
            self.state == "UNCONSUMED"
            and self.plan is None
            and self.planning_terms_complete
            and self.source_selection.eligible
        ):
            raise ValueError(
                "operator_parent_move_premark_action_invalid"
            )
        for consumed, count in (
            (
                self.source_cancel_allowance_consumed,
                self.source_cancel_call_count,
            ),
            (
                self.replacement_create_allowance_consumed,
                self.replacement_create_call_count,
            ),
            (
                self.successor_closeout_cancel_allowance_consumed,
                self.successor_closeout_cancel_call_count,
            ),
        ):
            if consumed is not (count == 1):
                raise ValueError(
                    "operator_parent_move_call_accounting_invalid"
                )
        call_counts = (
            self.source_cancel_call_count,
            self.replacement_create_call_count,
            self.successor_closeout_cancel_call_count,
        )
        if (
            call_counts not in _LIFECYCLE_CALL_COUNTS[self.state]
            or self.latest_cycle_phase
            not in _LIFECYCLE_PHASES[self.state]
        ):
            raise ValueError(
                "operator_parent_move_lifecycle_evidence_invalid"
            )
        if self.active_cycle_number is None:
            if (
                self.active_cycle_phase is not None
                or self.active_cycle_status is not None
            ):
                raise ValueError(
                    "operator_parent_move_active_cycle_invalid"
                )
        elif self.active_cycle_status != "IN_FLIGHT":
            raise ValueError(
                "operator_parent_move_active_cycle_invalid"
            )
        if self.correlation_id != self.latest_cycle_correlation_id:
            raise ValueError(
                "operator_parent_move_correlation_binding_invalid"
            )
        if self.plan is None:
            if (
                self.state != "UNCONSUMED"
                or self.plan_sha256 is not None
                or self.reserved_successor_client_order_id is not None
                or self.reserved_successor_client_order_id_sha256
                is not None
                or self.cycle_count != 0
                or self.source_follow_up_suppressed
                or self.source_cancel_allowance_consumed
                or self.replacement_create_allowance_consumed
                or self.successor_closeout_cancel_allowance_consumed
            ):
                raise ValueError(
                    "operator_parent_move_unconsumed_state_invalid"
                )
            return self
        if (
            self.state == "UNCONSUMED"
            or self.plan_sha256 is None
            or self.plan_sha256
            != _canonical_sha(self.plan.model_dump(mode="json"))
            or self.plan.source_client_order_id
            != self.source_client_order_id
            or self.reserved_successor_client_order_id
            != self.plan.reserved_successor_client_order_id
            or self.reserved_successor_client_order_id_sha256
            != _sha(self.plan.reserved_successor_client_order_id)
            or self.cycle_count < 1
        ):
            raise ValueError(
                "operator_parent_move_plan_readback_invalid"
            )
        return self


class OperatorParentMovePremarkPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_limit_price: str = Field(
        pattern=_DECIMAL,
    )
    operator_reason: str = Field(min_length=10, max_length=240)
    confirm_premark: Literal[True]


class OperatorParentMoveExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_plan_sha256: str = Field(pattern=_SHA256)
    confirmation_sha256: str = Field(pattern=_SHA256)
    confirm_cancel_then_replace: Literal[True]


class OperatorParentMoveSafeCloseoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_plan_sha256: str = Field(pattern=_SHA256)
    confirmation_sha256: str = Field(pattern=_SHA256)
    confirm_exact_successor_cancel: Literal[True]


__all__ = [
    "OperatorParentMoveExecuteRequest",
    "OperatorParentMovePlan",
    "OperatorParentMovePremarkPlanRequest",
    "OperatorParentMovePremarkReadback",
    "OperatorParentMoveSafeCloseoutRequest",
    "OperatorParentMoveSourceSelection",
    "ParentMoveAction",
    "ParentMoveState",
]


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _canonical_sha(value: dict[str, object]) -> str:
    return _sha(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
