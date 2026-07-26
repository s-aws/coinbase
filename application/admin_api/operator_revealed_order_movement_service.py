"""Operator-owned review and execution for one revealed-order movement."""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field

from application.admin_api.operator_mvp_policy import (
    OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_TEXT,
    OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_USDC,
    OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_TEXT,
    OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_USDC,
)


GOAL_ID = "operator_revealed_order_movement_and_repricing_v1"
_UUID = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SHA256 = r"^[0-9a-f]{64}$"
_EVIDENCE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,255}$")
_DIAGNOSTIC = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
_TERMINAL_STATES = frozenset(
    {
        "SOURCE_FILLED",
        "CANCEL_REJECTED",
        "CANCEL_UNKNOWN",
        "CREATE_REJECTED",
        "CREATE_UNKNOWN",
        "REPLACED",
    }
)
_PLAN_FIELDS = frozenset(
    {
        "stealth_order_id",
        "definition_revision",
        "definition_sha256",
        "portfolio_scope_sha256",
        "source_client_order_id",
        "source_exchange_order_id_sha256",
        "replacement_client_order_id",
        "root_client_order_id",
        "product_id",
        "side",
        "base_size",
        "old_limit_price",
        "requested_limit_price",
        "replacement_limit_price",
        "price_increment",
        "target_movement",
        "target_movement_type",
        "post_only",
        "submitted_notional_usdc",
        "possible_execution_notional_usdc",
        "profitability_validated",
        "zero_fill_validated",
    }
)


class OperatorRevealedOrderMovementError(ValueError):
    """Fixed-code operator movement error."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class OperatorRevealedOrderMovementConflict(
    OperatorRevealedOrderMovementError
):
    """A durable plan, claim, or terminal state conflicts."""


class OperatorRevealedOrderMovePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_definition_revision: int = Field(ge=1)
    expected_definition_sha256: str = Field(pattern=_SHA256)
    requested_limit_price: str = Field(
        pattern=r"^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,18})?$"
    )
    operator_reason: str = Field(min_length=10, max_length=240)
    confirm_operator_move_plan: Literal[True]


class OperatorRevealedOrderMoveExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_plan_sha256: str = Field(pattern=_SHA256)
    operator_reason: str = Field(min_length=10, max_length=240)
    confirm_operator_cancel_then_replace: Literal[True]


class OperatorRevealedOrderMovePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stealth_order_id: str = Field(pattern=_UUID)
    definition_revision: int = Field(ge=1)
    definition_sha256: str = Field(pattern=_SHA256)
    portfolio_scope_sha256: str = Field(pattern=_SHA256)
    source_client_order_id: str = Field(pattern=_UUID)
    source_exchange_order_id_sha256: str = Field(pattern=_SHA256)
    replacement_client_order_id: str = Field(pattern=_UUID)
    root_client_order_id: str = Field(pattern=_UUID)
    product_id: str = Field(min_length=1, max_length=64)
    side: Literal["BUY", "SELL"]
    base_size: str
    old_limit_price: str
    requested_limit_price: str
    replacement_limit_price: str
    price_increment: str
    target_movement: str
    target_movement_type: Literal["P", "A"]
    post_only: Literal[True]
    submitted_notional_usdc: str
    possible_execution_notional_usdc: str
    profitability_validated: Literal[True]
    zero_fill_validated: Literal[True]
    plan_sha256: str = Field(pattern=_SHA256)


class OperatorRevealedOrderMovementResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_id: Literal[
        "operator_revealed_order_movement_and_repricing_v1"
    ] = GOAL_ID
    state: Literal[
        "UNCONSUMED",
        "PLANNED",
        "CANCEL_CLAIMED",
        "SOURCE_CANCELLED",
        "SOURCE_FILLED",
        "CANCEL_REJECTED",
        "CANCEL_UNKNOWN",
        "CREATE_CLAIMED",
        "REPLACED",
        "CREATE_REJECTED",
        "CREATE_UNKNOWN",
    ]
    stealth_order_id: str = Field(pattern=_UUID)
    plan: OperatorRevealedOrderMovePlan | None
    plan_sha256: str | None = Field(default=None, pattern=_SHA256)
    source_client_order_id: str | None = Field(
        default=None, pattern=_UUID
    )
    replacement_client_order_id: str | None = Field(
        default=None, pattern=_UUID
    )
    source_exchange_order_id_sha256: str | None = Field(
        default=None, pattern=_SHA256
    )
    replacement_exchange_order_id_sha256: str | None = Field(
        default=None, pattern=_SHA256
    )
    exchange_order_ids_withheld: Literal[True] = True
    max_submitted_notional_usdc: Literal["3.10"] = (
        OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_TEXT
    )
    max_possible_execution_notional_usdc: Literal["1.00"] = (
        OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_TEXT
    )
    cancel_allowance_consumed: bool
    create_allowance_consumed: bool
    cancel_call_count: int = Field(ge=0, le=1)
    create_call_count: int = Field(ge=0, le=1)
    read_call_count: int = Field(ge=0, le=30)
    diagnostic_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,95}$")
    operator_intent: Literal[
        "prepare_revealed_order_move",
        "execute_revealed_order_cancel_then_replace",
    ]
    command_service_method: Literal[
        "get_execution",
        "prepare_plan",
        "execute_move",
    ]
    correlation_id: str | None = None
    plan_idempotency_key_sha256: str | None = Field(
        default=None, pattern=_SHA256
    )
    execute_idempotency_key_sha256: str | None = Field(
        default=None, pattern=_SHA256
    )
    command_cycle_status: Literal["IN_FLIGHT", "COMPLETED"] | None
    command_cycle_phase: Literal["PLAN", "EXECUTE"] | None
    command_cycle_number: int | None = Field(default=None, ge=1, le=10)
    command_cycle_correlation_id: str | None = None
    command_cycle_evidence_sha256: str | None = Field(
        default=None, pattern=_SHA256
    )
    command_replayed: bool = False
    execution_authority_enabled: bool
    allowed_actions: list[Literal["PREPARE_PLAN", "EXECUTE_MOVE"]]
    browser_authority: Literal["display_and_forward_only"] = (
        "display_and_forward_only"
    )
    raw_response_persisted: Literal[False] = False
    raw_exception_persisted: Literal[False] = False


class OperatorRevealedOrderMovementService:
    """Bind one immutable reviewed move to ordered Cancel/Create claims."""

    def __init__(
        self,
        *,
        definition_repository: Any,
        repository: Any,
        runtime: Any,
        execution_authority_checker: Callable[[], bool],
    ) -> None:
        self.definition_repository = definition_repository
        self.repository = repository
        self.runtime = runtime
        self.execution_authority_checker = execution_authority_checker

    def get_execution(
        self,
        stealth_order_id: str,
        *,
        roles: list[str] | None = None,
    ) -> OperatorRevealedOrderMovementResponse:
        row = self.repository.get_goal(stealth_order_id)
        return self._response(
            stealth_order_id=stealth_order_id,
            row=row,
            roles=roles or [],
        )

    def prepare_plan(
        self,
        *,
        stealth_order_id: str,
        body: OperatorRevealedOrderMovePlanRequest,
        actor_id: str,
        roles: list[str],
        correlation_id: str,
        idempotency_key: str,
        operator_intent: str = "prepare_revealed_order_move",
    ) -> OperatorRevealedOrderMovementResponse:
        self._require_operator(roles)
        if operator_intent != "prepare_revealed_order_move":
            raise OperatorRevealedOrderMovementError(
                "operator_move_intent_invalid"
            )
        self._require_command_identity(
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        payload_sha256 = _hash_payload(
            {
                "stealth_order_id": stealth_order_id,
                "expected_definition_revision": (
                    body.expected_definition_revision
                ),
                "expected_definition_sha256": (
                    body.expected_definition_sha256
                ),
                "requested_limit_price": body.requested_limit_price,
                "operator_reason_sha256": hashlib.sha256(
                    body.operator_reason.encode()
                ).hexdigest(),
                "operator_intent": operator_intent,
                "confirmation": body.confirm_operator_move_plan,
            }
        )
        replay = self.repository.replay_plan(
            stealth_order_id=stealth_order_id,
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha256,
        )
        if replay is not None:
            return self._response(
                stealth_order_id=stealth_order_id,
                row=replay,
                roles=roles,
            )
        definition = self.definition_repository.get_definition(
            stealth_order_id
        )
        if (
            int(definition.get("revision") or 0)
            != body.expected_definition_revision
            or str(definition.get("definition_sha256") or "")
            != body.expected_definition_sha256
        ):
            raise OperatorRevealedOrderMovementConflict(
                "operator_move_definition_binding_conflict"
            )
        plan = self.runtime.build_plan(
            definition,
            requested_limit_price=body.requested_limit_price,
        )
        plan = self._validate_plan(
            stealth_order_id=stealth_order_id,
            definition=definition,
            raw_plan=plan,
        )
        row = self.repository.create_plan(
            plan=plan,
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha256,
        )
        return self._response(
            stealth_order_id=stealth_order_id,
            row=row,
            roles=roles,
        )

    def execute_move(
        self,
        *,
        stealth_order_id: str,
        body: OperatorRevealedOrderMoveExecuteRequest,
        actor_id: str,
        roles: list[str],
        correlation_id: str,
        idempotency_key: str,
        operator_intent: str = (
            "execute_revealed_order_cancel_then_replace"
        ),
    ) -> OperatorRevealedOrderMovementResponse:
        self._require_operator(roles)
        if (
            operator_intent
            != "execute_revealed_order_cancel_then_replace"
        ):
            raise OperatorRevealedOrderMovementError(
                "operator_move_intent_invalid"
            )
        self._require_command_identity(
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        payload_sha256 = _hash_payload(
            {
                "stealth_order_id": stealth_order_id,
                "expected_plan_sha256": body.expected_plan_sha256,
                "operator_reason_sha256": hashlib.sha256(
                    body.operator_reason.encode()
                ).hexdigest(),
                "operator_intent": operator_intent,
                "confirmation": (
                    body.confirm_operator_cancel_then_replace
                ),
            }
        )
        replay = self.repository.replay_execute(
            stealth_order_id=stealth_order_id,
            expected_plan_sha256=body.expected_plan_sha256,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha256,
        )
        if replay is not None:
            return self._response(
                stealth_order_id=stealth_order_id,
                row=replay,
                roles=roles,
            )
        self._require_live_authority()
        row = self.repository.get_goal(stealth_order_id)
        if (
            row is None
            or row.get("state") not in {"PLANNED", "SOURCE_CANCELLED"}
            or row.get("plan_sha256")
            != body.expected_plan_sha256
        ):
            raise OperatorRevealedOrderMovementConflict(
                "operator_move_plan_binding_conflict"
            )
        plan = self._plan_from_row(row)
        definition = self.definition_repository.get_definition(
            stealth_order_id
        )
        self._validate_plan(
            stealth_order_id=stealth_order_id,
            definition=definition,
            raw_plan=plan,
        )
        self.runtime.revalidate_plan(definition, plan)
        begun = self.repository.begin_execute(
            stealth_order_id=stealth_order_id,
            expected_plan_sha256=body.expected_plan_sha256,
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha256,
        )
        if begun.get("command_replayed") is True:
            return self._response(
                stealth_order_id=stealth_order_id,
                row=begun,
                roles=roles,
            )

        def claim_read(category: str) -> Callable[[], None]:
            return lambda: self.repository.claim_read(
                stealth_order_id=stealth_order_id,
                category=category,
                correlation_id=correlation_id,
            )

        def record_read(category: str) -> Callable[[str], None]:
            return lambda result: self.repository.record_read(
                stealth_order_id=stealth_order_id,
                category=category,
                correlation_id=correlation_id,
                result_code=str(result),
            )

        if row.get("state") == "PLANNED":
            cancel_outcome = self.runtime.cancel_source(
                plan,
                before_pre_cancel_read=claim_read("SOURCE_PRE_CANCEL"),
                after_pre_cancel_read=record_read("SOURCE_PRE_CANCEL"),
                before_cancel_call=lambda: self.repository.claim_cancel(
                    stealth_order_id=stealth_order_id,
                    correlation_id=correlation_id,
                ),
                before_post_cancel_read=claim_read("SOURCE_POST_CANCEL"),
                after_post_cancel_read=record_read("SOURCE_POST_CANCEL"),
            )
            if cancel_outcome != "CANCELLED":
                diagnostic = {
                    "FILLED": "operator_move_source_filled",
                    "PRE_CANCEL_UNKNOWN": (
                        "operator_move_pre_cancel_read_unknown"
                    ),
                    "REJECTED": "operator_move_cancel_rejected",
                    "UNKNOWN": "operator_move_cancel_unknown",
                }.get(cancel_outcome, "operator_move_cancel_unknown")
                self.repository.record_cancel_outcome(
                    stealth_order_id=stealth_order_id,
                    outcome=(
                        cancel_outcome
                        if cancel_outcome
                        in {"FILLED", "REJECTED", "UNKNOWN"}
                        else "UNKNOWN"
                    ),
                    diagnostic_code=diagnostic,
                )
                return self._complete_response(
                    stealth_order_id=stealth_order_id,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    roles=roles,
                )

            self.repository.record_cancel_outcome(
                stealth_order_id=stealth_order_id,
                outcome="CANCELLED",
                diagnostic_code="operator_move_source_cancelled",
            )
        create_result = self.runtime.create_replacement(
            plan,
            before_create_call=lambda: self.repository.claim_create(
                stealth_order_id=stealth_order_id,
                correlation_id=correlation_id,
            ),
            before_wallet_read=claim_read("WALLET_PRE_CREATE"),
            after_wallet_read=record_read("WALLET_PRE_CREATE"),
            before_post_create_read=claim_read("REPLACEMENT_POST_CREATE"),
            after_post_create_read=record_read(
                "REPLACEMENT_POST_CREATE"
            ),
        )
        outcome = str(create_result.get("outcome") or "UNKNOWN").upper()
        if outcome not in {
            "ACCEPTED",
            "REJECTED",
            "UNKNOWN",
            "WALLET_REJECTED",
            "WALLET_UNKNOWN",
        }:
            outcome = "UNKNOWN"
        diagnostic = {
            "ACCEPTED": "operator_move_replacement_accepted",
            "REJECTED": "operator_move_replacement_rejected",
            "UNKNOWN": "operator_move_replacement_unknown",
            "WALLET_REJECTED": "operator_move_wallet_rejected",
            "WALLET_UNKNOWN": "operator_move_wallet_read_unknown",
        }[outcome]
        self.repository.record_create_outcome(
            stealth_order_id=stealth_order_id,
            outcome=(
                "REJECTED"
                if outcome == "WALLET_REJECTED"
                else "UNKNOWN"
                if outcome == "WALLET_UNKNOWN"
                else outcome
            ),
            diagnostic_code=diagnostic,
            replacement_exchange_order_id_sha256=(
                create_result.get(
                    "replacement_exchange_order_id_sha256"
                )
                if outcome == "ACCEPTED"
                else None
            ),
        )
        return self._complete_response(
            stealth_order_id=stealth_order_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            roles=roles,
        )

    def _complete_response(
        self,
        *,
        stealth_order_id: str,
        correlation_id: str,
        idempotency_key: str,
        roles: list[str],
    ) -> OperatorRevealedOrderMovementResponse:
        row = self.repository.complete_command(
            stealth_order_id=stealth_order_id,
            phase="EXECUTE",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        return self._response(
            stealth_order_id=stealth_order_id,
            row=row,
            roles=roles,
        )

    def _validate_plan(
        self,
        *,
        stealth_order_id: str,
        definition: Mapping[str, Any],
        raw_plan: Mapping[str, Any],
    ) -> dict[str, Any]:
        plan = dict(raw_plan)
        supplied_hash = str(plan.pop("plan_sha256", "") or "")
        if set(plan) != _PLAN_FIELDS:
            raise OperatorRevealedOrderMovementError(
                "operator_move_plan_shape_invalid"
            )
        plan_hash = _hash_payload(plan)
        if supplied_hash and supplied_hash != plan_hash:
            raise OperatorRevealedOrderMovementError(
                "operator_move_plan_hash_invalid"
            )
        if (
            str(plan.get("stealth_order_id") or "") != stealth_order_id
            or str(definition.get("definition_id") or "")
            != stealth_order_id
            or int(plan.get("definition_revision") or 0)
            != int(definition.get("revision") or 0)
            or str(plan.get("definition_sha256") or "")
            != str(definition.get("definition_sha256") or "")
            or str(plan.get("portfolio_scope_sha256") or "")
            != str(definition.get("portfolio_scope_sha256") or "")
            or str(plan.get("product_id") or "")
            != str(definition.get("product_id") or "")
            or str(plan.get("side") or "").upper()
            != str(definition.get("side") or "").upper()
            or plan.get("post_only") is not True
            or plan.get("profitability_validated") is not True
            or plan.get("zero_fill_validated") is not True
        ):
            raise OperatorRevealedOrderMovementConflict(
                "operator_move_plan_binding_conflict"
            )
        try:
            submitted = Decimal(str(plan["submitted_notional_usdc"]))
            possible = Decimal(
                str(plan["possible_execution_notional_usdc"])
            )
            size = Decimal(str(plan["base_size"]))
            price = Decimal(str(plan["replacement_limit_price"]))
            increment = Decimal(str(plan["price_increment"]))
        except (InvalidOperation, KeyError, TypeError, ValueError):
            raise OperatorRevealedOrderMovementError(
                "operator_move_plan_numeric_invalid"
            ) from None
        if not all(
            value.is_finite() and value > 0
            for value in (submitted, possible, size, price, increment)
        ):
            raise OperatorRevealedOrderMovementError(
                "operator_move_plan_numeric_invalid"
            )
        if (
            price % increment != 0
            or submitted != size * price
            or possible != submitted
            or submitted > OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_USDC
            or possible > OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_USDC
        ):
            raise OperatorRevealedOrderMovementConflict(
                "operator_move_cap_or_increment_blocked"
            )
        return {**plan, "plan_sha256": plan_hash}

    @staticmethod
    def _plan_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
        nested = row.get("plan")
        if isinstance(nested, Mapping):
            return dict(nested)
        nested = row.get("plan_json")
        if isinstance(nested, Mapping):
            return dict(nested)
        return {
            key: row[key]
            for key in (*sorted(_PLAN_FIELDS), "plan_sha256")
            if key in row
        }

    def _response(
        self,
        *,
        stealth_order_id: str,
        row: Mapping[str, Any] | None,
        roles: list[str],
    ) -> OperatorRevealedOrderMovementResponse:
        live = bool(self.execution_authority_checker())
        operator = _has_operator_role(roles)
        if row is None:
            return OperatorRevealedOrderMovementResponse(
                state="UNCONSUMED",
                stealth_order_id=stealth_order_id,
                plan=None,
                plan_sha256=None,
                source_client_order_id=None,
                replacement_client_order_id=None,
                source_exchange_order_id_sha256=None,
                replacement_exchange_order_id_sha256=None,
                cancel_allowance_consumed=False,
                create_allowance_consumed=False,
                cancel_call_count=0,
                create_call_count=0,
                read_call_count=0,
                diagnostic_code="operator_move_unconsumed",
                operator_intent="prepare_revealed_order_move",
                command_service_method="get_execution",
                correlation_id=None,
                plan_idempotency_key_sha256=None,
                execute_idempotency_key_sha256=None,
                command_cycle_status=None,
                command_cycle_phase=None,
                command_cycle_number=None,
                command_cycle_correlation_id=None,
                command_cycle_evidence_sha256=None,
                command_replayed=False,
                execution_authority_enabled=live,
                allowed_actions=(
                    ["PREPARE_PLAN"] if operator else []
                ),
            )
        plan = OperatorRevealedOrderMovePlan.model_validate(
            self._plan_from_row(row)
        )
        state = str(row.get("state") or "")
        actions: list[str] = []
        if (
            state in {"PLANNED", "SOURCE_CANCELLED"}
            and row.get("command_cycle_status") != "IN_FLIGHT"
            and operator
            and live
        ):
            actions.append("EXECUTE_MOVE")
        return OperatorRevealedOrderMovementResponse(
            state=state,
            stealth_order_id=stealth_order_id,
            plan=plan,
            plan_sha256=plan.plan_sha256,
            source_client_order_id=plan.source_client_order_id,
            replacement_client_order_id=(
                plan.replacement_client_order_id
            ),
            source_exchange_order_id_sha256=(
                plan.source_exchange_order_id_sha256
            ),
            replacement_exchange_order_id_sha256=row.get(
                "replacement_exchange_order_id_sha256"
            ),
            cancel_allowance_consumed=bool(
                row.get("cancel_allowance_consumed")
            ),
            create_allowance_consumed=bool(
                row.get("create_allowance_consumed")
            ),
            cancel_call_count=int(row.get("cancel_call_count") or 0),
            create_call_count=int(row.get("create_call_count") or 0),
            read_call_count=int(row.get("read_call_count") or 0),
            diagnostic_code=str(
                row.get("diagnostic_code") or "operator_move_unknown"
            ),
            operator_intent=(
                "prepare_revealed_order_move"
                if str(row.get("command_cycle_phase") or "").upper()
                == "PLAN"
                else "execute_revealed_order_cancel_then_replace"
            ),
            command_service_method=(
                "prepare_plan"
                if str(row.get("command_cycle_phase") or "").upper()
                == "PLAN"
                else "execute_move"
            ),
            correlation_id=row.get("correlation_id"),
            plan_idempotency_key_sha256=row.get(
                "plan_idempotency_key_sha256"
            ),
            execute_idempotency_key_sha256=row.get(
                "execute_idempotency_key_sha256"
            ),
            command_cycle_status=row.get("command_cycle_status"),
            command_cycle_phase=row.get("command_cycle_phase"),
            command_cycle_number=row.get("command_cycle_number"),
            command_cycle_correlation_id=row.get(
                "command_cycle_correlation_id"
            ),
            command_cycle_evidence_sha256=row.get(
                "command_cycle_evidence_sha256"
            ),
            command_replayed=bool(row.get("command_replayed")),
            execution_authority_enabled=live,
            allowed_actions=actions,
        )

    @staticmethod
    def _require_operator(roles: list[str]) -> None:
        if not _has_operator_role(roles):
            raise OperatorRevealedOrderMovementError(
                "operator_move_permission_denied"
            )

    def _require_live_authority(self) -> None:
        if not self.execution_authority_checker():
            raise OperatorRevealedOrderMovementError(
                "operator_move_execution_authority_disabled"
            )

    @staticmethod
    def _require_command_identity(
        *,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> None:
        if (
            not actor_id
            or _EVIDENCE_ID.fullmatch(correlation_id) is None
            or _EVIDENCE_ID.fullmatch(idempotency_key) is None
        ):
            raise OperatorRevealedOrderMovementError(
                "operator_move_command_identity_invalid"
            )


def _has_operator_role(roles: list[str]) -> bool:
    return bool({"admin", "trader"} & {str(role).lower() for role in roles})


def _hash_payload(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def safe_operator_revealed_order_movement_code(value: Any) -> str:
    code = str(getattr(value, "code", "") or "")
    return code if _DIAGNOSTIC.fullmatch(code) else "operator_move_unknown"
