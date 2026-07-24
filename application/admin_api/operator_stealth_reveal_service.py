"""Backend-owned operator workflow for one stealth reveal and exact closeout."""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from database.operator_stealth_reveal import (
    GOAL_ID,
    OperatorStealthRevealConflict,
    OperatorStealthRevealError,
)
from application.admin_api.operator_mvp_policy import (
    OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_USDC,
    OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_TEXT,
    OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_USDC,
    OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_TEXT,
)


_UUID = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SHA256 = r"^[0-9a-f]{64}$"
_EVIDENCE_ID = r"^[A-Za-z0-9._:-]{1,255}$"
_STATES = Literal[
    "UNCONSUMED",
    "MATERIALIZING",
    "MATERIALIZED",
    "PREVIEW_CLAIMED",
    "PREVIEW_ACCEPTED",
    "PREVIEW_REJECTED",
    "PREVIEW_UNKNOWN",
    "CREATE_CLAIMED",
    "REVEALED",
    "CREATE_REJECTED",
    "CREATE_UNKNOWN",
    "CANCEL_CLAIMED",
    "CANCELLED",
    "FILLED",
    "CANCEL_UNKNOWN",
]
_TERMINAL_OR_WAITING = {
    "PREVIEW_CLAIMED",
    "PREVIEW_REJECTED",
    "PREVIEW_UNKNOWN",
    "CREATE_CLAIMED",
    "REVEALED",
    "CREATE_REJECTED",
    "CREATE_UNKNOWN",
    "CANCEL_CLAIMED",
    "CANCELLED",
    "FILLED",
    "CANCEL_UNKNOWN",
}


class OperatorStealthRevealRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    expected_definition_sha256: str = Field(pattern=_SHA256)
    operator_reason: str = Field(min_length=10, max_length=240)
    confirm_operator_stealth_reveal: Literal[True]


class OperatorStealthCloseoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_plan_sha256: str = Field(pattern=_SHA256)
    operator_reason: str = Field(min_length=10, max_length=240)
    confirm_operator_stealth_closeout: Literal[True]


class OperatorStealthResumeAcceptedCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_plan_sha256: str = Field(pattern=_SHA256)
    operator_reason: str = Field(min_length=10, max_length=240)
    confirm_operator_stealth_resume_create: Literal[True]


class OperatorStealthRevealPlanEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    side: Literal["BUY", "SELL"]
    base_size: str
    limit_price: str
    configured_limit_price: str
    submitted_limit_price: str
    reveal_pricing_policy: str
    reveal_price_source: str
    fallback_used: Literal[False]
    market_source: str
    market_bid: str | None
    market_ask: str | None
    target_movement: str
    target_movement_type: Literal["P", "A"]
    target_movement_source: str
    post_only: bool


class OperatorStealthRevealExecutionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_id: Literal["operator_stealth_reveal_and_exact_closeout_v1"]
    state: _STATES
    definition_id: str = Field(pattern=_UUID)
    definition_revision: int = Field(ge=1)
    definition_sha256: str = Field(pattern=_SHA256)
    portfolio_scope_sha256: str = Field(pattern=_SHA256)
    client_order_id: str = Field(pattern=_UUID)
    product_id: str
    side: Literal["BUY", "SELL"]
    plan: OperatorStealthRevealPlanEvidence | None
    plan_sha256: str | None = Field(default=None, pattern=_SHA256)
    prepreview_admission_sha256: str | None = Field(
        default=None,
        pattern=_SHA256,
    )
    submitted_notional_usdc: str | None = None
    max_submitted_notional_usdc: Literal["3.10"] = (
        OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_TEXT
    )
    max_possible_execution_notional_usdc: Literal["1.00"] = (
        OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_TEXT
    )
    preview_allowance_consumed: bool
    create_allowance_consumed: bool
    cancel_allowance_consumed: bool
    preview_call_count: int = Field(ge=0, le=1)
    create_call_count: int = Field(ge=0, le=1)
    cancel_call_count: int = Field(ge=0, le=1)
    read_call_count: int = Field(ge=0, le=31)
    preview_outcome: Literal["ACCEPTED", "REJECTED", "UNKNOWN"] | None
    create_outcome: Literal["ACCEPTED", "REJECTED", "UNKNOWN"] | None
    cancel_outcome: Literal["CANCELLED", "FILLED", "UNKNOWN"] | None
    exchange_order_id_sha256: str | None = Field(
        default=None,
        pattern=_SHA256,
    )
    exchange_order_id_withheld: Literal[True] = True
    diagnostic_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,95}$")
    correlation_id: str | None = Field(default=None, pattern=_EVIDENCE_ID)
    command_idempotency_key_sha256: str | None = Field(
        default=None,
        pattern=_SHA256,
    )
    command_identity_bound: bool
    command_cycle_status: Literal["IN_FLIGHT", "COMPLETED"] | None = None
    command_cycle_phase: (
        Literal["REVEAL", "RESUME_CREATE", "CLOSEOUT"] | None
    ) = None
    command_cycle_number: int | None = Field(default=None, ge=1, le=10)
    command_cycle_correlation_id: str | None = Field(
        default=None,
        pattern=_EVIDENCE_ID,
    )
    command_cycle_idempotency_key_sha256: str | None = Field(
        default=None,
        pattern=_SHA256,
    )
    command_cycle_payload_sha256: str | None = Field(
        default=None,
        pattern=_SHA256,
    )
    command_cycle_terminal_goal_state: _STATES | None = None
    command_cycle_terminal_diagnostic_code: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]{0,95}$",
    )
    command_cycle_preview_call_count: int | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    command_cycle_create_call_count: int | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    command_cycle_cancel_call_count: int | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    command_cycle_read_call_count: int | None = Field(
        default=None,
        ge=0,
        le=31,
    )
    command_cycle_evidence_sha256: str | None = Field(
        default=None,
        pattern=_SHA256,
    )
    execution_authority_enabled: bool
    allowed_actions: list[
        Literal["REVEAL", "RESUME_ACCEPTED_CREATE", "CLOSEOUT"]
    ]
    browser_authority: Literal["display_and_forward_only"] = (
        "display_and_forward_only"
    )
    raw_response_persisted: Literal[False] = False
    raw_exception_persisted: Literal[False] = False


class OperatorStealthRevealService:
    """Coordinates the single-use goal around the canonical stealth manager."""

    def __init__(
        self,
        *,
        definition_repository: Any,
        reveal_repository: Any,
        runtime: Any,
        configured_portfolio_id: str,
        configured_portfolio_label: str = "Test",
        execution_authority_checker: Callable[[], bool],
    ) -> None:
        self.definition_repository = definition_repository
        self.reveal_repository = reveal_repository
        self.runtime = runtime
        self.configured_portfolio_id = str(configured_portfolio_id or "").strip()
        self.configured_portfolio_label = str(
            configured_portfolio_label or "Test"
        ).strip()
        self.execution_authority_checker = execution_authority_checker
        try:
            import uuid

            normalized = str(uuid.UUID(self.configured_portfolio_id))
        except (AttributeError, TypeError, ValueError):
            raise OperatorStealthRevealError(
                "operator_stealth_portfolio_not_configured"
            ) from None
        self.portfolio_scope_sha256 = hashlib.sha256(
            normalized.encode()
        ).hexdigest()

    def get_execution(
        self,
        definition_id: str,
        *,
        roles: list[str] | None = None,
    ) -> OperatorStealthRevealExecutionResponse:
        definition = self.definition_repository.get_definition(definition_id)
        row = self.reveal_repository.get_goal(definition_id)
        return self._response(
            definition=definition,
            row=row,
            roles=roles,
        )

    def reveal(
        self,
        *,
        definition_id: str,
        body: OperatorStealthRevealRequest,
        actor_id: str,
        roles: list[str],
        correlation_id: str,
        idempotency_key: str,
    ) -> OperatorStealthRevealExecutionResponse:
        definition = self.definition_repository.get_definition(definition_id)
        payload_sha256 = _hash_payload(
            {
                "definition_id": definition_id,
                "expected_revision": body.expected_revision,
                "expected_definition_sha256": (
                    body.expected_definition_sha256
                ),
                "operator_reason_sha256": hashlib.sha256(
                    body.operator_reason.encode()
                ).hexdigest(),
                "confirmation": body.confirm_operator_stealth_reveal,
            }
        )
        existing = self.reveal_repository.get_goal(definition_id)
        if existing is None:
            self._validate_definition(definition, body)
            self._require_local_authority(roles)
            row = self.reveal_repository.begin_materialization(
                definition_id=definition_id,
                expected_revision=body.expected_revision,
                expected_definition_sha256=body.expected_definition_sha256,
                expected_portfolio_scope_sha256=self.portfolio_scope_sha256,
                actor_id=actor_id,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                payload_sha256=payload_sha256,
            )
        else:
            self._validate_existing_goal(
                definition=definition,
                row=existing,
                body=body,
            )
        if (
            existing is not None
            and existing["state"] == "MATERIALIZED"
            and existing.get("diagnostic_code")
            == "operator_stealth_prepreview_cap_blocked"
        ):
            return self._response(
                definition=definition,
                row=existing,
                roles=roles,
            )
        if existing is not None and existing["state"] in _TERMINAL_OR_WAITING:
            row = self.reveal_repository.begin_materialization(
                definition_id=definition_id,
                expected_revision=body.expected_revision,
                expected_definition_sha256=body.expected_definition_sha256,
                expected_portfolio_scope_sha256=self.portfolio_scope_sha256,
                actor_id=actor_id,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                payload_sha256=payload_sha256,
            )
            return self._response(definition=definition, row=row, roles=roles)
        elif existing is not None:
            self._require_local_authority(roles)
            if existing["state"] in {"MATERIALIZING", "MATERIALIZED"}:
                row = existing
            else:
                row = self.reveal_repository.begin_materialization(
                    definition_id=definition_id,
                    expected_revision=body.expected_revision,
                    expected_definition_sha256=(
                        body.expected_definition_sha256
                    ),
                    expected_portfolio_scope_sha256=(
                        self.portfolio_scope_sha256
                    ),
                    actor_id=actor_id,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    payload_sha256=payload_sha256,
                )

        if row["state"] in {"MATERIALIZING", "MATERIALIZED"}:
            self.reveal_repository.begin_command_cycle(
                definition_id,
                phase="REVEAL",
                actor_id=actor_id,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                payload_sha256=payload_sha256,
            )
            binding = self._portfolio_binding_result(
                definition_id=definition_id,
                category="REVEAL_PORTFOLIO_BINDING",
                correlation_id=correlation_id,
            )
            if binding != "READY":
                return self._complete_response(
                    definition=definition,
                    definition_id=definition_id,
                    phase="REVEAL",
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    roles=roles,
                )

        if row["state"] == "MATERIALIZING":
            audit_id = (
                "operator-stealth-"
                + hashlib.sha256(correlation_id.encode()).hexdigest()[:32]
            )
            self.runtime.materialize(
                definition,
                portfolio_id=self.configured_portfolio_id,
                correlation_id=correlation_id,
                audit_id=audit_id,
            )
            row = self.reveal_repository.record_materialized(definition_id)

        if row["state"] == "MATERIALIZED":
            if not self.runtime.condition_ready(definition):
                row = self.reveal_repository.record_condition_not_ready(
                    definition_id
                )
                return self._complete_response(
                    definition=definition,
                    definition_id=definition_id,
                    phase="REVEAL",
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    roles=roles,
                )
            reveal_plan = self.runtime.build_plan(definition)
            plan = self._freeze_plan(definition, reveal_plan)
            plan_sha256 = _hash_payload(plan)
            if not self._plan_notional_is_admissible(plan):
                row = self.reveal_repository.record_prepreview_cap_blocked(
                    definition_id,
                    plan=plan,
                    plan_sha256=plan_sha256,
                )
                return self._complete_response(
                    definition=definition,
                    definition_id=definition_id,
                    phase="REVEAL",
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    roles=roles,
                )
            wallet_claimed = False

            def before_wallet_call() -> None:
                nonlocal wallet_claimed
                claim = self.reveal_repository.claim_read_call(
                    definition_id,
                    category="REVEAL_WALLET_ADMISSION",
                    correlation_id=correlation_id,
                    wire_call=True,
                )
                if not claim["invoke_required"]:
                    raise OperatorStealthRevealError(
                        "operator_stealth_wallet_read_replay_unavailable"
                    )
                wallet_claimed = True

            try:
                admission_sha256 = self.runtime.prepreview_admission(
                    definition,
                    plan=plan,
                    plan_sha256=plan_sha256,
                    portfolio_id=self.configured_portfolio_id,
                    before_wallet_call=before_wallet_call,
                )
            except Exception:
                if wallet_claimed:
                    self.reveal_repository.record_read_call_outcome(
                        definition_id,
                        category="REVEAL_WALLET_ADMISSION",
                        correlation_id=correlation_id,
                        result_code="UNKNOWN",
                    )
                return self._complete_response(
                    definition=definition,
                    definition_id=definition_id,
                    phase="REVEAL",
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    roles=roles,
                )
            self.reveal_repository.record_read_call_outcome(
                definition_id,
                category="REVEAL_WALLET_ADMISSION",
                correlation_id=correlation_id,
                result_code="READY",
            )
            row = self.reveal_repository.record_prepreview_admission(
                definition_id,
                plan=plan,
                plan_sha256=plan_sha256,
                admission_sha256=admission_sha256,
            )
            preview_claimed = False

            def before_preview_call() -> None:
                nonlocal row, preview_claimed
                row = self.reveal_repository.claim_preview(
                    definition_id,
                    plan=plan,
                    plan_sha256=plan_sha256,
                    admission_sha256=admission_sha256,
                )
                preview_claimed = True

            try:
                preview_outcome = str(
                    self.runtime.preview(
                        plan,
                        before_call=before_preview_call,
                    )
                ).upper()
            except Exception:
                preview_outcome = (
                    "UNKNOWN" if preview_claimed else "REJECTED"
                )
            if not preview_claimed:
                row = (
                    self.reveal_repository
                    .record_preview_preflight_rejection(definition_id)
                )
                return self._complete_response(
                    definition=definition,
                    definition_id=definition_id,
                    phase="REVEAL",
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    roles=roles,
                )
            if preview_outcome not in {"ACCEPTED", "REJECTED"}:
                preview_outcome = "UNKNOWN"
            row = self.reveal_repository.record_preview_outcome(
                definition_id,
                outcome=preview_outcome,
                diagnostic_code=(
                    "operator_stealth_preview_accepted"
                    if preview_outcome == "ACCEPTED"
                    else "operator_stealth_preview_rejected"
                    if preview_outcome == "REJECTED"
                    else "operator_stealth_preview_unknown"
                ),
            )
            if preview_outcome != "ACCEPTED":
                return self._complete_response(
                    definition=definition,
                    definition_id=definition_id,
                    phase="REVEAL",
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    roles=roles,
                )

        if row["state"] == "PREVIEW_ACCEPTED":
            row = self._execute_accepted_create(
                definition=definition,
                row=row,
            )
        return self._complete_response(
            definition=definition,
            definition_id=definition_id,
            phase="REVEAL",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            roles=roles,
        )

    def resume_accepted_create(
        self,
        *,
        definition_id: str,
        body: OperatorStealthResumeAcceptedCreateRequest,
        actor_id: str,
        roles: list[str],
        correlation_id: str,
        idempotency_key: str,
    ) -> OperatorStealthRevealExecutionResponse:
        definition = self.definition_repository.get_definition(definition_id)
        row = self.reveal_repository.get_goal(definition_id)
        if row is None:
            raise OperatorStealthRevealConflict(
                "operator_stealth_reveal_not_found"
            )
        self._validate_goal_binding(definition=definition, row=row)
        self._require_local_authority(roles)
        if (
            row["state"] != "PREVIEW_ACCEPTED"
            or row.get("plan_sha256") != body.expected_plan_sha256
            or row.get("preview_outcome") != "ACCEPTED"
            or row.get("preview_allowance_consumed") is not True
            or row.get("create_allowance_consumed") is not False
            or int(row.get("create_call_count") or 0) != 0
        ):
            raise OperatorStealthRevealConflict(
                "operator_stealth_resume_create_unavailable"
            )
        payload_sha256 = _hash_payload(
            {
                "definition_id": definition_id,
                "expected_plan_sha256": body.expected_plan_sha256,
                "operator_reason_sha256": hashlib.sha256(
                    body.operator_reason.encode()
                ).hexdigest(),
                "confirmation": (
                    body.confirm_operator_stealth_resume_create
                ),
            }
        )
        self.reveal_repository.begin_command_cycle(
            definition_id,
            phase="RESUME_CREATE",
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha256,
        )
        row = self._execute_accepted_create(
            definition=definition,
            row=row,
        )
        return self._complete_response(
            definition=definition,
            definition_id=definition_id,
            phase="RESUME_CREATE",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            roles=roles,
        )

    def closeout(
        self,
        *,
        definition_id: str,
        body: OperatorStealthCloseoutRequest,
        actor_id: str,
        roles: list[str],
        correlation_id: str,
        idempotency_key: str,
    ) -> OperatorStealthRevealExecutionResponse:
        definition = self.definition_repository.get_definition(definition_id)
        row = self.reveal_repository.get_goal(definition_id)
        if row is None:
            raise OperatorStealthRevealConflict(
                "operator_stealth_reveal_not_found"
            )
        self._validate_goal_binding(definition=definition, row=row)
        if row["plan_sha256"] != body.expected_plan_sha256:
            raise OperatorStealthRevealConflict(
                "operator_stealth_closeout_plan_conflict"
            )
        payload_sha256 = _hash_payload(
            {
                "definition_id": definition_id,
                "expected_plan_sha256": body.expected_plan_sha256,
                "operator_reason_sha256": hashlib.sha256(
                    body.operator_reason.encode()
                ).hexdigest(),
                "confirmation": body.confirm_operator_stealth_closeout,
            }
        )
        if row["state"] in {
            "CANCELLED",
            "FILLED",
            "CANCEL_UNKNOWN",
        }:
            row = self.reveal_repository.begin_closeout(
                definition_id,
                actor_id=actor_id,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                payload_sha256=payload_sha256,
            )
            return self._response(definition=definition, row=row, roles=roles)
        if row["state"] != "REVEALED":
            raise OperatorStealthRevealConflict(
                "operator_stealth_closeout_not_available"
            )
        self._require_local_authority(roles)
        row = self.reveal_repository.begin_closeout(
            definition_id,
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha256,
        )
        self.reveal_repository.begin_command_cycle(
            definition_id,
            phase="CLOSEOUT",
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha256,
        )
        binding = self._portfolio_binding_result(
            definition_id=definition_id,
            category="CLOSEOUT_PORTFOLIO_BINDING",
            correlation_id=correlation_id,
        )
        if binding != "READY":
            return self._complete_response(
                definition=definition,
                definition_id=definition_id,
                phase="CLOSEOUT",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                roles=roles,
            )

        try:
            readback = self._exact_readback(
                definition=definition,
                row=row,
                definition_id=definition_id,
                category="EXACT_PRE_CANCEL_READBACK",
                correlation_id=correlation_id,
            )
        except OperatorStealthRevealError:
            return self._complete_response(
                definition=definition,
                definition_id=definition_id,
                phase="CLOSEOUT",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                roles=roles,
            )
        status = readback["status"]
        if status in {"FILLED", "CANCELLED"}:
            self.runtime.reconcile_terminal(
                client_order_id=definition_id,
                status=status,
            )
            row = self.reveal_repository.record_terminal_without_cancel(
                definition_id,
                outcome=status,
                diagnostic_code=(
                    "operator_stealth_filled_confirmed"
                    if status == "FILLED"
                    else "operator_stealth_cancel_confirmed"
                ),
            )
            return self._complete_response(
                definition=definition,
                definition_id=definition_id,
                phase="CLOSEOUT",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                roles=roles,
            )
        if status not in {"OPEN", "PENDING", "CANCEL_QUEUED"}:
            raise OperatorStealthRevealError(
                "operator_stealth_closeout_state_unknown"
            )

        cancel_claimed = False

        def before_cancel_call() -> None:
            nonlocal row, cancel_claimed
            row = self.reveal_repository.claim_cancel(definition_id)
            cancel_claimed = True

        try:
            cancel_returned = self.runtime.cancel_exchange_only(
                client_order_id=definition_id,
                verified_exchange_order_id=readback["exchange_order_id"],
                before_cancel_call=before_cancel_call,
            )
        except Exception:
            cancel_returned = False
        if not cancel_claimed:
            row = self.reveal_repository.record_cancel_preflight_rejection(
                definition_id
            )
            return self._complete_response(
                definition=definition,
                definition_id=definition_id,
                phase="CLOSEOUT",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                roles=roles,
            )
        if not cancel_returned:
            row = self.reveal_repository.record_cancel_outcome(
                definition_id,
                outcome="UNKNOWN",
                diagnostic_code="operator_stealth_cancel_unknown",
            )
            return self._complete_response(
                definition=definition,
                definition_id=definition_id,
                phase="CLOSEOUT",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                roles=roles,
            )
        try:
            after_readback = self._exact_readback(
                definition=definition,
                row=row,
                definition_id=definition_id,
                category="EXACT_POST_CANCEL_READBACK",
                correlation_id=correlation_id,
            )
        except OperatorStealthRevealError:
            row = self.reveal_repository.record_cancel_outcome(
                definition_id,
                outcome="UNKNOWN",
                diagnostic_code="operator_stealth_cancel_unknown",
            )
            return self._complete_response(
                definition=definition,
                definition_id=definition_id,
                phase="CLOSEOUT",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                roles=roles,
            )
        after_status = after_readback["status"]
        if after_status not in {"CANCELLED", "FILLED"}:
            row = self.reveal_repository.record_cancel_outcome(
                definition_id,
                outcome="UNKNOWN",
                diagnostic_code="operator_stealth_cancel_unknown",
            )
            return self._complete_response(
                definition=definition,
                definition_id=definition_id,
                phase="CLOSEOUT",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                roles=roles,
            )
        self.runtime.reconcile_terminal(
            client_order_id=definition_id,
            status=after_status,
        )
        row = self.reveal_repository.record_cancel_outcome(
            definition_id,
            outcome=after_status,
            diagnostic_code=(
                "operator_stealth_cancel_confirmed"
                if after_status == "CANCELLED"
                else "operator_stealth_filled_during_cancel"
            ),
        )
        return self._complete_response(
            definition=definition,
            definition_id=definition_id,
            phase="CLOSEOUT",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            roles=roles,
        )

    def _complete_response(
        self,
        *,
        definition: dict[str, Any],
        definition_id: str,
        phase: Literal["REVEAL", "RESUME_CREATE", "CLOSEOUT"],
        correlation_id: str,
        idempotency_key: str,
        roles: list[str],
    ) -> OperatorStealthRevealExecutionResponse:
        row = self.reveal_repository.record_command_completion(
            definition_id,
            phase=phase,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        return self._response(
            definition=definition,
            row=row,
            roles=roles,
        )

    def _execute_accepted_create(
        self,
        *,
        definition: dict[str, Any],
        row: dict[str, Any],
    ) -> dict[str, Any]:
        definition_id = str(definition["definition_id"])
        if not self._plan_notional_is_admissible(row.get("plan")):
            return self.reveal_repository.record_create_cap_rejection(
                definition_id
            )
        create_claimed = False

        def before_create_call() -> None:
            nonlocal row, create_claimed
            row = self.reveal_repository.claim_create(definition_id)
            create_claimed = True

        try:
            result = self.runtime.reveal(
                definition,
                plan=dict(row["plan"]),
                plan_sha256=str(row["plan_sha256"]),
                preview_claim_id=str(row["preview_claim_id"]),
                portfolio_id=self.configured_portfolio_id,
                prepreview_admission_sha256=str(
                    row["prepreview_admission_sha256"]
                ),
                before_create_call=before_create_call,
            )
        except Exception:
            result = {
                "outcome": "UNKNOWN" if create_claimed else "REJECTED",
                "placement_attempted": create_claimed,
                "exchange_order_id": None,
            }
        if not create_claimed:
            return (
                self.reveal_repository
                .record_create_preflight_rejection(definition_id)
            )
        outcome = str(result.get("outcome") or "UNKNOWN").upper()
        if outcome not in {"ACCEPTED", "REJECTED"}:
            outcome = "UNKNOWN"
        exchange_order_id = (
            str(result.get("exchange_order_id") or "")
            if outcome == "ACCEPTED"
            else ""
        )
        if outcome == "ACCEPTED" and not exchange_order_id:
            outcome = "UNKNOWN"
        return self.reveal_repository.record_create_outcome(
            definition_id,
            outcome=outcome,
            diagnostic_code=(
                "operator_stealth_create_accepted"
                if outcome == "ACCEPTED"
                else "operator_stealth_create_rejected"
                if outcome == "REJECTED"
                else "operator_stealth_create_unknown"
            ),
            exchange_order_id_sha256=(
                hashlib.sha256(exchange_order_id.encode()).hexdigest()
                if outcome == "ACCEPTED"
                else None
            ),
        )

    def _require_local_authority(self, roles: list[str]) -> None:
        if not roles or not self.execution_authority_checker():
            raise OperatorStealthRevealError(
                "operator_stealth_live_authority_unavailable"
            )

    def _portfolio_binding_result(
        self,
        *,
        definition_id: str,
        category: str,
        correlation_id: str,
    ) -> str:
        aggregate_claim = self.reveal_repository.claim_read_call(
            definition_id,
            category=category,
            correlation_id=correlation_id,
            wire_call=False,
        )
        if not aggregate_claim["invoke_required"]:
            result_code = str(
                aggregate_claim.get("result_code") or "UNKNOWN"
            )
            return (
                result_code
                if result_code in {"READY", "NOT_READY"}
                else "UNKNOWN"
            )

        phase = "REVEAL" if category.startswith("REVEAL_") else "CLOSEOUT"
        endpoint_categories = {
            "permissions": f"{phase}_API_KEY_PERMISSIONS",
            "catalog": f"{phase}_PORTFOLIO_CATALOG",
        }
        claimed = {"permissions": False, "catalog": False}

        def claim_endpoint(name: str) -> None:
            endpoint_claim = self.reveal_repository.claim_read_call(
                definition_id,
                category=endpoint_categories[name],
                correlation_id=correlation_id,
                wire_call=True,
            )
            if not endpoint_claim["invoke_required"]:
                raise OperatorStealthRevealError(
                    "operator_stealth_portfolio_read_replay_unavailable"
                )
            claimed[name] = True

        try:
            result = self.runtime.portfolio_binding_ready(
                expected_portfolio_id=self.configured_portfolio_id,
                expected_portfolio_label=self.configured_portfolio_label,
                before_permissions_call=lambda: claim_endpoint(
                    "permissions"
                ),
                before_catalog_call=lambda: claim_endpoint("catalog"),
            )
        except Exception:
            result = {}

        permissions_returned = bool(
            result.get("permissions_returned") is True
        )
        catalog_returned = bool(result.get("catalog_returned") is True)
        for name, returned in (
            ("permissions", permissions_returned),
            ("catalog", catalog_returned),
        ):
            if claimed[name]:
                self.reveal_repository.record_read_call_outcome(
                    definition_id,
                    category=endpoint_categories[name],
                    correlation_id=correlation_id,
                    result_code="READY" if returned else "UNKNOWN",
                )

        if not all(claimed.values()) or not (
            permissions_returned and catalog_returned
        ):
            result_code = "UNKNOWN"
        else:
            result_code = (
                "READY" if result.get("ready") is True else "NOT_READY"
            )
        aggregate_claim = self.reveal_repository.record_read_call_outcome(
            definition_id,
            category=category,
            correlation_id=correlation_id,
            result_code=result_code,
        )
        result_code = str(
            aggregate_claim.get("result_code") or "UNKNOWN"
        )
        return (
            result_code
            if result_code in {"READY", "NOT_READY"}
            else "UNKNOWN"
        )

    def _exact_readback(
        self,
        *,
        definition: dict[str, Any],
        row: dict[str, Any],
        definition_id: str,
        category: str,
        correlation_id: str,
    ) -> dict[str, str]:
        expected_exchange_hash = str(
            row.get("exchange_order_id_sha256") or ""
        )
        if re.fullmatch(_SHA256, expected_exchange_hash) is None:
            raise OperatorStealthRevealError(
                "operator_stealth_closeout_identity_unproven"
            )
        read_claimed = False

        def before_read_call() -> None:
            nonlocal read_claimed
            claim = self.reveal_repository.claim_read_call(
                definition_id,
                category=category,
                correlation_id=correlation_id,
                wire_call=True,
            )
            if not claim["invoke_required"]:
                raise OperatorStealthRevealError(
                    "operator_stealth_closeout_read_replay_unavailable"
                )
            read_claimed = True

        try:
            result = self.runtime.exact_readback(
                client_order_id=definition_id,
                product_id=str(definition["product_id"]),
                expected_exchange_order_id_sha256=(
                    expected_exchange_hash
                ),
                before_call=before_read_call,
            )
        except Exception:
            result = {}
        if not read_claimed:
            raise OperatorStealthRevealError(
                "operator_stealth_closeout_readback_unavailable"
            )

        authoritative_status = str(
            result.get("status") or ""
        ).upper()
        exchange_order_id = str(
            result.get("exchange_order_id") or ""
        )
        exact = bool(
            result.get("authoritative") is True
            and result.get("client_order_id") == definition_id
            and result.get("portfolio_matches") is True
            and result.get("exchange_order_id_sha256")
            == expected_exchange_hash
            and exchange_order_id
            and hashlib.sha256(exchange_order_id.encode()).hexdigest()
            == expected_exchange_hash
            and authoritative_status
            in {
                "OPEN",
                "PENDING",
                "CANCEL_QUEUED",
                "FILLED",
                "CANCELLED",
            }
        )
        result_code = (
            "AUTHORITATIVE"
            if exact
            else "NOT_AUTHORITATIVE"
            if result
            else "UNKNOWN"
        )
        claim = self.reveal_repository.record_read_call_outcome(
            definition_id,
            category=category,
            correlation_id=correlation_id,
            result_code=result_code,
            authoritative_status=(
                authoritative_status if exact else None
            ),
        )
        if claim.get("result_code") == "UNKNOWN":
            raise OperatorStealthRevealError(
                "operator_stealth_closeout_readback_unavailable"
            )
        if claim.get("result_code") != "AUTHORITATIVE":
            raise OperatorStealthRevealError(
                "operator_stealth_closeout_identity_unproven"
            )
        return {
            "status": authoritative_status,
            "exchange_order_id": exchange_order_id,
        }

    def _validate_goal_binding(
        self,
        *,
        definition: dict[str, Any],
        row: dict[str, Any],
    ) -> None:
        if (
            int(definition.get("revision") or 0)
            != int(row.get("definition_revision") or 0)
            or definition.get("definition_sha256")
            != row.get("definition_sha256")
            or definition.get("portfolio_scope_sha256")
            != row.get("portfolio_scope_sha256")
            or row.get("portfolio_scope_sha256")
            != self.portfolio_scope_sha256
            or str(row.get("client_order_id") or "")
            != str(definition.get("definition_id") or "")
            or definition.get("post_only") is not True
            or definition.get("max_order_replacements") != 0
            or definition.get("allow_partial_fills") is not False
            or str(definition.get("sizing_mode") or "") != "FIXED"
        ):
            raise OperatorStealthRevealConflict(
                "operator_stealth_definition_binding_conflict"
            )

    def _validate_definition(
        self,
        definition: dict[str, Any],
        body: OperatorStealthRevealRequest,
    ) -> None:
        if (
            str(definition.get("lifecycle_state") or "") != "DRAFT"
            or int(definition.get("revision") or 0) != body.expected_revision
            or definition.get("definition_sha256")
            != body.expected_definition_sha256
            or definition.get("portfolio_scope_sha256")
            != self.portfolio_scope_sha256
            or definition.get("runtime_classification") != "UNMATERIALIZED"
            or definition.get("post_only") is not True
            or definition.get("max_order_replacements") != 0
            or definition.get("allow_partial_fills") is not False
            or str(definition.get("sizing_mode") or "") != "FIXED"
        ):
            raise OperatorStealthRevealConflict(
                "operator_stealth_definition_not_eligible"
            )

    def _validate_existing_goal(
        self,
        *,
        definition: dict[str, Any],
        row: dict[str, Any],
        body: OperatorStealthRevealRequest,
    ) -> None:
        self._validate_goal_binding(definition=definition, row=row)
        if (
            int(row.get("definition_revision") or 0)
            != body.expected_revision
            or row.get("definition_sha256")
            != body.expected_definition_sha256
        ):
            raise OperatorStealthRevealConflict(
                "operator_stealth_definition_binding_conflict"
            )

    @staticmethod
    def _freeze_plan(
        definition: dict[str, Any],
        reveal_plan: Any,
    ) -> dict[str, Any]:
        try:
            base_size = _decimal_text(definition["total_size"])
            limit_price = _decimal_text(
                reveal_plan.submitted_limit_price
            )
            configured_limit_price = _decimal_text(
                reveal_plan.configured_limit_price
            )
            target_movement = _decimal_text(
                reveal_plan.target_movement
            )
            definition_target_movement = Decimal(
                str(definition["target_movement"])
            )
            market_bid = (
                None
                if reveal_plan.market_bid is None
                else _decimal_text(reveal_plan.market_bid)
            )
            market_ask = (
                None
                if reveal_plan.market_ask is None
                else _decimal_text(reveal_plan.market_ask)
            )
        except (AttributeError, KeyError, InvalidOperation, ValueError):
            raise OperatorStealthRevealError(
                "operator_stealth_plan_invalid"
            ) from None
        plan = {
            "product_id": str(definition.get("product_id") or ""),
            "side": str(definition.get("side") or "").upper(),
            "base_size": base_size,
            "limit_price": limit_price,
            "configured_limit_price": configured_limit_price,
            "submitted_limit_price": limit_price,
            "reveal_pricing_policy": str(
                reveal_plan.reveal_pricing_policy
            ).lower(),
            "reveal_price_source": str(
                reveal_plan.reveal_price_source or ""
            ),
            "fallback_used": bool(reveal_plan.fallback_used),
            "market_source": str(reveal_plan.market_source or ""),
            "market_bid": market_bid,
            "market_ask": market_ask,
            "target_movement": target_movement,
            "target_movement_type": str(
                reveal_plan.target_movement_type or ""
            ).upper(),
            "target_movement_source": str(
                reveal_plan.target_movement_source or ""
            ),
            "post_only": bool(reveal_plan.post_only),
        }
        if (
            not plan["product_id"]
            or plan["side"] not in {"BUY", "SELL"}
            or plan["post_only"] is not True
            or plan["fallback_used"] is not False
            or plan["configured_limit_price"]
            != _decimal_text(definition["limit_price"])
            or plan["reveal_pricing_policy"]
            != str(
                definition.get("reveal_pricing_policy") or ""
            ).lower()
            or not plan["reveal_price_source"]
            or not plan["market_source"]
            or plan["target_movement_type"] not in {"P", "A"}
            or plan["target_movement_type"]
            != str(
                definition.get("target_movement_type") or ""
            ).upper()
            or Decimal(plan["target_movement"])
            != definition_target_movement
            or not plan["target_movement_source"]
        ):
            raise OperatorStealthRevealError(
                "operator_stealth_plan_policy_mismatch"
            )
        return plan

    def _response(
        self,
        *,
        definition: dict[str, Any],
        row: dict[str, Any] | None,
        roles: list[str] | None = None,
    ) -> OperatorStealthRevealExecutionResponse:
        if row is None:
            row = {
                "goal_id": GOAL_ID,
                "state": "UNCONSUMED",
                "definition_id": definition["definition_id"],
                "definition_revision": definition["revision"],
                "definition_sha256": definition["definition_sha256"],
                "portfolio_scope_sha256": definition[
                    "portfolio_scope_sha256"
                ],
                "client_order_id": definition["definition_id"],
                "plan": None,
                "plan_sha256": None,
                "prepreview_admission_sha256": None,
                "preview_allowance_consumed": False,
                "create_allowance_consumed": False,
                "cancel_allowance_consumed": False,
                "preview_call_count": 0,
                "create_call_count": 0,
                "cancel_call_count": 0,
                "read_call_count": 0,
                "preview_outcome": None,
                "create_outcome": None,
                "cancel_outcome": None,
                "exchange_order_id_sha256": None,
                "diagnostic_code": "operator_stealth_unconsumed",
                "correlation_id": None,
                "command_idempotency_key_sha256": None,
                "command_identity_bound": False,
                "command_cycle_status": None,
                "command_cycle_phase": None,
                "command_cycle_number": None,
                "command_cycle_correlation_id": None,
                "command_cycle_idempotency_key_sha256": None,
                "command_cycle_payload_sha256": None,
                "command_cycle_terminal_goal_state": None,
                "command_cycle_terminal_diagnostic_code": None,
                "command_cycle_preview_call_count": None,
                "command_cycle_create_call_count": None,
                "command_cycle_cancel_call_count": None,
                "command_cycle_read_call_count": None,
                "command_cycle_evidence_sha256": None,
            }
        state = str(row["state"])
        normalized_roles = {
            str(role).lower() for role in (roles or [])
        }
        can_create = bool(
            normalized_roles.intersection({"admin", "trader"})
        )
        can_cancel = can_create
        allowed_actions: list[str] = []
        if (
            state in {"UNCONSUMED", "MATERIALIZING", "MATERIALIZED"}
            and self._definition_is_actionable(
                definition,
                row=row,
                state=state,
            )
            and self.execution_authority_checker()
            and can_create
        ):
            allowed_actions = ["REVEAL"]
        elif (
            state == "PREVIEW_ACCEPTED"
            and self._definition_is_actionable(
                definition,
                row=row,
                state=state,
            )
            and row.get("preview_outcome") == "ACCEPTED"
            and row.get("preview_allowance_consumed") is True
            and row.get("create_allowance_consumed") is False
            and int(row.get("create_call_count") or 0) == 0
            and self.execution_authority_checker()
            and can_create
        ):
            allowed_actions = ["RESUME_ACCEPTED_CREATE"]
        elif (
            state == "REVEALED"
            and row.get("create_outcome") == "ACCEPTED"
            and bool(row.get("exchange_order_id_sha256"))
            and row.get("cancel_allowance_consumed") is False
            and int(row.get("cancel_call_count") or 0) == 0
            and self.execution_authority_checker()
            and can_cancel
        ):
            allowed_actions = ["CLOSEOUT"]
        plan = row.get("plan")
        submitted_notional_usdc = None
        if plan:
            try:
                submitted_notional_usdc = _decimal_text(
                    Decimal(str(plan["base_size"]))
                    * Decimal(str(plan["limit_price"]))
                )
            except (InvalidOperation, KeyError, TypeError, ValueError):
                submitted_notional_usdc = None
        return OperatorStealthRevealExecutionResponse(
            **{
                key: row.get(key)
                for key in (
                    "goal_id",
                    "state",
                    "definition_id",
                    "definition_revision",
                    "definition_sha256",
                    "portfolio_scope_sha256",
                    "client_order_id",
                    "plan",
                    "plan_sha256",
                    "prepreview_admission_sha256",
                    "preview_allowance_consumed",
                    "create_allowance_consumed",
                    "cancel_allowance_consumed",
                    "preview_call_count",
                    "create_call_count",
                    "cancel_call_count",
                    "read_call_count",
                    "preview_outcome",
                    "create_outcome",
                    "cancel_outcome",
                    "exchange_order_id_sha256",
                    "diagnostic_code",
                    "correlation_id",
                    "command_idempotency_key_sha256",
                    "command_identity_bound",
                    "command_cycle_status",
                    "command_cycle_phase",
                    "command_cycle_number",
                    "command_cycle_correlation_id",
                    "command_cycle_idempotency_key_sha256",
                    "command_cycle_payload_sha256",
                    "command_cycle_terminal_goal_state",
                    "command_cycle_terminal_diagnostic_code",
                    "command_cycle_preview_call_count",
                    "command_cycle_create_call_count",
                    "command_cycle_cancel_call_count",
                    "command_cycle_read_call_count",
                    "command_cycle_evidence_sha256",
                )
            },
            product_id=(
                plan["product_id"]
                if plan
                else str(definition["product_id"])
            ),
            side=(
                plan["side"] if plan else str(definition["side"]).upper()
            ),
            execution_authority_enabled=(
                self.execution_authority_checker()
            ),
            submitted_notional_usdc=submitted_notional_usdc,
            allowed_actions=allowed_actions,
        )

    @staticmethod
    def _definition_is_actionable(
        definition: dict[str, Any],
        *,
        row: dict[str, Any],
        state: str,
    ) -> bool:
        if (
            str(definition.get("lifecycle_state") or "") != "DRAFT"
            or definition.get("post_only") is not True
            or definition.get("max_order_replacements") != 0
            or definition.get("allow_partial_fills") is not False
            or str(definition.get("sizing_mode") or "") != "FIXED"
            or row.get("diagnostic_code")
            == "operator_stealth_prepreview_cap_blocked"
        ):
            return False
        if state == "UNCONSUMED":
            return (
                str(definition.get("runtime_classification") or "")
                == "UNMATERIALIZED"
            )
        return bool(
            state in {
                "MATERIALIZING",
                "MATERIALIZED",
                "PREVIEW_ACCEPTED",
            }
            and row.get("definition_id") == definition.get("definition_id")
            and row.get("definition_revision") == definition.get("revision")
            and row.get("definition_sha256")
            == definition.get("definition_sha256")
            and row.get("portfolio_scope_sha256")
            == definition.get("portfolio_scope_sha256")
        )

    @staticmethod
    def _plan_notional_is_admissible(plan: Any) -> bool:
        if not isinstance(plan, dict):
            return False
        try:
            base_size = Decimal(str(plan["base_size"]))
            limit_price = Decimal(str(plan["limit_price"]))
            submitted_notional = base_size * limit_price
        except (InvalidOperation, KeyError, TypeError, ValueError):
            return False
        return bool(
            base_size.is_finite()
            and base_size > 0
            and limit_price.is_finite()
            and limit_price > 0
            and submitted_notional.is_finite()
            and submitted_notional > 0
            and submitted_notional
            <= OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_USDC
            and submitted_notional
            <= OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_USDC
        )


def _decimal_text(value: Any) -> str:
    number = Decimal(str(value))
    if not number.is_finite() or number <= 0:
        raise ValueError("positive decimal required")
    normalized = format(number, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized


def _hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def safe_operator_stealth_reveal_code(value: Any) -> str:
    code = str(getattr(value, "code", value) or "")
    if re.fullmatch(r"[a-z][a-z0-9_]{0,95}", code) is None:
        return "operator_stealth_unknown"
    return code
