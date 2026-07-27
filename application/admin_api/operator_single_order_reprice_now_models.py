"""Strict generated-contract source for Goal 15 Reprice Now intent."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


_UUID = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_UUID5 = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SHA256 = r"^[0-9a-f]{64}$"
_DIAGNOSTIC = r"^operator_reprice_now_[a-z0-9_]{1,75}$"
_EVIDENCE_ID = r"^[A-Za-z0-9._:@|/-]{1,255}$"


class OperatorSingleOrderRepriceNowIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_definition_revision: int = Field(ge=1)
    expected_definition_sha256: str = Field(pattern=_SHA256)
    expected_source_evidence_sha256: str = Field(pattern=_SHA256)
    operator_reason: str = Field(min_length=10, max_length=240)
    confirm_prepare_reprice_now_intent: Literal[True]


class OperatorSingleOrderRepriceNowExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_intent_sha256: str = Field(pattern=_SHA256)
    confirm_execute_reprice_now: Literal[True]


class OperatorSingleOrderRepriceNowIntentPlan(BaseModel):
    """Immutable non-market plan; no product, portfolio, size, or price."""

    model_config = ConfigDict(extra="forbid")

    goal_id: Literal["operator_single_order_reprice_now_v1"]
    policy_revision: Literal["SINGLE_ORDER_REPRICE_NOW_INTENT_V1"]
    stealth_order_id: str = Field(pattern=_UUID)
    source_client_order_id: str = Field(pattern=_UUID)
    reserved_successor_client_order_id: str = Field(pattern=_UUID5)
    root_client_order_id: str = Field(pattern=_UUID)
    definition_revision: int = Field(ge=1)
    definition_sha256: str = Field(pattern=_SHA256)
    source_evidence_sha256: str = Field(pattern=_SHA256)
    source_status: Literal["REVEALED"]
    zero_fill_proven: Literal[True]
    system_owned: Literal[True]
    direct_parent: Literal[True]


class OperatorSingleOrderRepriceNowSourceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stealth_order_id: str = Field(pattern=_UUID)
    source_client_order_id: str = Field(pattern=_UUID)
    found: bool
    eligible: bool
    diagnostic_code: str = Field(pattern=_DIAGNOSTIC)
    definition_revision: int | None = Field(default=None, ge=1)
    definition_sha256: str | None = Field(default=None, pattern=_SHA256)
    root_client_order_id: str | None = Field(default=None, pattern=_UUID)
    source_status: str | None = None
    zero_fill_proven: bool = False
    system_owned: bool = False
    direct_parent: bool = False
    source_evidence_sha256: str | None = Field(
        default=None,
        pattern=_SHA256,
    )

    @model_validator(mode="after")
    def validate_selection(
        self,
    ) -> "OperatorSingleOrderRepriceNowSourceSelection":
        if self.eligible and not (
            self.found
            and self.diagnostic_code
            == "operator_reprice_now_source_eligible"
            and self.definition_revision is not None
            and self.definition_sha256 is not None
            and self.root_client_order_id == self.stealth_order_id
            and self.source_status == "REVEALED"
            and self.zero_fill_proven
            and self.system_owned
            and self.direct_parent
            and self.source_evidence_sha256 is not None
        ):
            raise ValueError(
                "operator_reprice_now_source_selection_invalid"
            )
        return self


class OperatorSingleOrderRepriceNowEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(pattern=_UUID)
    event_type: Literal["REPRICE_NOW_INTENT_PREPARED"]
    cycle_number: int = Field(ge=1, le=10)
    diagnostic_code: str = Field(pattern=_DIAGNOSTIC)
    correlation_id: str = Field(pattern=_EVIDENCE_ID)
    evidence_sha256: str = Field(pattern=_SHA256)
    recorded_at: datetime


class OperatorSingleOrderRepriceNowReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["operator_single_order_reprice_now"] = (
        "operator_single_order_reprice_now"
    )
    goal_id: Literal["operator_single_order_reprice_now_v1"] = (
        "operator_single_order_reprice_now_v1"
    )
    state: Literal[
        "UNCONSUMED",
        "GOAL_ALREADY_BOUND",
        "INTENT_PREPARED",
    ]
    diagnostic_code: str = Field(pattern=_DIAGNOSTIC)
    stealth_order_id: str = Field(pattern=_UUID)
    source_client_order_id: str = Field(pattern=_UUID)
    source_client_order_id_sha256: str = Field(pattern=_SHA256)
    reserved_successor_client_order_id: str | None = Field(
        default=None,
        pattern=_UUID5,
    )
    reserved_successor_client_order_id_sha256: str | None = Field(
        default=None,
        pattern=_SHA256,
    )
    source_selection: OperatorSingleOrderRepriceNowSourceSelection
    intent: OperatorSingleOrderRepriceNowIntentPlan | None = None
    intent_sha256: str | None = Field(default=None, pattern=_SHA256)
    events: list[OperatorSingleOrderRepriceNowEvent] = Field(
        default_factory=list,
        max_length=10,
    )
    allowed_actions: list[Literal["PREPARE_REPRICE_NOW"]] = Field(
        default_factory=list,
        max_length=1,
    )
    local_cycles_used: int = Field(ge=0, le=10)
    local_cycles_max: Literal[10] = 10
    latest_cycle_idempotency_key_sha256: str | None = Field(
        default=None,
        pattern=_SHA256,
    )
    latest_cycle_payload_sha256: str | None = Field(
        default=None,
        pattern=_SHA256,
    )
    latest_cycle_actor_id_sha256: str | None = Field(
        default=None,
        pattern=_SHA256,
    )
    latest_cycle_evidence_sha256: str | None = Field(
        default=None,
        pattern=_SHA256,
    )
    market_terms_bound: Literal[False] = False
    cap_policy_bound: Literal[False] = False
    live_authority_terms_complete: Literal[False] = False
    execution_authority_enabled: Literal[False] = False
    source_cancel_allowance_consumed: Literal[False] = False
    source_cancel_call_count: Literal[0] = 0
    replacement_create_allowance_consumed: Literal[False] = False
    replacement_create_call_count: Literal[0] = 0
    total_exchange_call_count: Literal[0] = 0
    page_load_coinbase_calls: Literal[0] = 0
    browser_authority: Literal["display_and_forward_only"] = (
        "display_and_forward_only"
    )
    raw_response_persisted: Literal[False] = False
    raw_exception_persisted: Literal[False] = False
    private_exchange_identifiers_persisted: Literal[False] = False
    command_replayed: bool = False
    correlation_id: str | None = Field(
        default=None,
        pattern=_EVIDENCE_ID,
    )
    operator_intent: Literal[
        "prepare_single_order_reprice_now"
    ] | None = None
    command_service_method: Literal[
        "get_single_order_reprice_now",
        "prepare_reprice_now_intent",
    ]

    @model_validator(mode="after")
    def validate_lifecycle(
        self,
    ) -> "OperatorSingleOrderRepriceNowReadback":
        if (
            self.source_selection.stealth_order_id
            != self.stealth_order_id
            or self.source_selection.source_client_order_id
            != self.source_client_order_id
            or self.source_client_order_id_sha256
            != hashlib.sha256(
                self.source_client_order_id.encode()
            ).hexdigest()
        ):
            raise ValueError("operator_reprice_now_identity_invalid")
        if self.state == "UNCONSUMED":
            if (
                self.intent is not None
                or self.intent_sha256 is not None
                or self.reserved_successor_client_order_id is not None
                or self.reserved_successor_client_order_id_sha256 is not None
                or self.events
                or self.local_cycles_used != 0
                or self.latest_cycle_idempotency_key_sha256 is not None
                or self.latest_cycle_payload_sha256 is not None
                or self.latest_cycle_actor_id_sha256 is not None
                or self.latest_cycle_evidence_sha256 is not None
            ):
                raise ValueError(
                    "operator_reprice_now_unconsumed_state_invalid"
                )
            return self
        if self.state == "GOAL_ALREADY_BOUND":
            if (
                self.diagnostic_code
                != "operator_reprice_now_goal_already_bound"
                or self.intent is not None
                or self.intent_sha256 is not None
                or self.reserved_successor_client_order_id is not None
                or self.reserved_successor_client_order_id_sha256 is not None
                or self.events
                or self.allowed_actions
                or self.local_cycles_used < 1
                or self.latest_cycle_idempotency_key_sha256 is not None
                or self.latest_cycle_payload_sha256 is not None
                or self.latest_cycle_actor_id_sha256 is not None
                or self.latest_cycle_evidence_sha256 is not None
                or self.operator_intent is not None
                or self.command_service_method
                != "get_single_order_reprice_now"
            ):
                raise ValueError(
                    "operator_reprice_now_goal_binding_state_invalid"
                )
            return self
        if (
            self.intent is None
            or self.intent_sha256 is None
            or self.reserved_successor_client_order_id is None
            or self.reserved_successor_client_order_id_sha256 is None
            or self.local_cycles_used < 1
            or not self.events
            or self.allowed_actions
            or self.latest_cycle_idempotency_key_sha256 is None
            or self.latest_cycle_payload_sha256 is None
            or self.latest_cycle_actor_id_sha256 is None
            or self.latest_cycle_evidence_sha256 is None
        ):
            raise ValueError(
                "operator_reprice_now_prepared_state_invalid"
            )
        payload = self.intent.model_dump(mode="json")
        expected_hash = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if (
            expected_hash != self.intent_sha256
            or self.intent.stealth_order_id != self.stealth_order_id
            or self.intent.source_client_order_id
            != self.source_client_order_id
            or self.intent.reserved_successor_client_order_id
            != self.reserved_successor_client_order_id
            or self.intent.source_evidence_sha256
            != self.source_selection.source_evidence_sha256
            or self.reserved_successor_client_order_id_sha256
            != hashlib.sha256(
                self.reserved_successor_client_order_id.encode()
            ).hexdigest()
        ):
            raise ValueError(
                "operator_reprice_now_intent_binding_invalid"
            )
        return self


__all__ = [
    "OperatorSingleOrderRepriceNowEvent",
    "OperatorSingleOrderRepriceNowExecuteRequest",
    "OperatorSingleOrderRepriceNowIntentPlan",
    "OperatorSingleOrderRepriceNowIntentRequest",
    "OperatorSingleOrderRepriceNowReadback",
    "OperatorSingleOrderRepriceNowSourceSelection",
]
