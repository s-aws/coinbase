"""Backend-owned parent-strategy operator workflow."""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator

from application.admin_api.operator_parent_strategy import (
    OperatorParentStrategyError,
    normalize_parent_strategy_terms,
)


_UUID = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_PRODUCT_ID = r"^[A-Z0-9]{1,32}(?:-[A-Z0-9]{1,32}){1,3}$"
_DECIMAL = r"^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,18})?$"
_EVIDENCE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,255}$")
_ACTOR_ID = re.compile(r"^[A-Za-z0-9._:@|/-]{1,255}$")
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")


class ParentStrategyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    product_id: str = Field(pattern=_PRODUCT_ID)
    side: Literal["BUY", "SELL"]
    reference_size: str = Field(pattern=_DECIMAL)
    reference_price: str = Field(pattern=_DECIMAL)
    target_movement: str = Field(pattern=_DECIMAL)
    target_movement_type: Literal["P", "A"]
    max_order_replacement: int = Field(ge=0, le=100)
    allow_partial_fills: bool
    child_order_type: Literal["LIMIT"]
    child_time_in_force: Literal["GOOD_UNTIL_CANCELLED"]
    child_post_only: Literal[True]
    operator_reason: str = Field(min_length=1, max_length=240)
    confirm_parent_strategy_create: Literal[True]


class ParentStrategyEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=80)
    target_movement: str = Field(pattern=_DECIMAL)
    target_movement_type: Literal["P", "A"]
    max_order_replacement: int = Field(ge=0, le=100)
    allow_partial_fills: bool
    child_order_type: Literal["LIMIT"]
    child_time_in_force: Literal["GOOD_UNTIL_CANCELLED"]
    child_post_only: Literal[True]
    operator_reason: str = Field(min_length=1, max_length=240)
    confirm_parent_strategy_edit: Literal[True]


class ParentStrategyDeactivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    operator_reason: str = Field(min_length=1, max_length=240)
    confirm_parent_strategy_deactivate: Literal[True]


class ParentStrategyDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    operator_reason: str = Field(min_length=1, max_length=240)
    confirm_parent_strategy_delete: Literal[True]


class ParentStrategyItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_id: str = Field(pattern=_UUID)
    name: str
    portfolio_scope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    admitted_product_catalog_revision_id: str = Field(pattern=_UUID)
    admitted_product_catalog_snapshot_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    product_id: str = Field(pattern=_PRODUCT_ID)
    side: Literal["BUY", "SELL"]
    reference_size: str
    reference_price: str
    target_movement: str
    target_movement_type: Literal["P", "A"]
    max_order_replacement: int = Field(ge=0, le=100)
    allow_partial_fills: bool
    child_order_type: Literal["LIMIT"]
    child_time_in_force: Literal["GOOD_UNTIL_CANCELLED"]
    child_post_only: Literal[True]
    lifecycle_state: Literal["ACTIVE", "DEACTIVATED", "DELETED"]
    revision: int = Field(ge=1)
    use_count: int = Field(ge=0)
    materialized_root_client_order_id: str | None = None
    unused_or_terminal: bool
    active_placement_count: int = Field(ge=0)
    child_count: int = Field(ge=0)
    unresolved_claim_count: int = Field(ge=0)
    reconciliation_required: bool
    delete_allowed: bool
    delete_blockers: list[str]
    allowed_actions: list[Literal["EDIT", "DEACTIVATE", "DELETE"]]
    created_at: str
    updated_at: str
    trading_authority_granted: Literal[False] = False
    exchange_call_count: Literal[0] = 0
    exchange_mutation_count: Literal[0] = 0


class ParentStrategyCommandEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["CREATE", "EDIT", "DEACTIVATE", "DELETE"]
    state: Literal["COMPLETED", "REJECTED"]
    diagnostic_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,95}$")
    strategy_id: str | None = Field(default=None, pattern=_UUID)
    result_revision: int | None = Field(default=None, ge=1)
    actor_id: str = Field(pattern=_ACTOR_ID.pattern)
    correlation_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,255}$")
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,255}$")
    created_at: str
    updated_at: str


class ParentStrategyCreatedEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lifecycle_state: Literal["ACTIVE"]
    child_order_type: Literal["LIMIT"]
    child_time_in_force: Literal["GOOD_UNTIL_CANCELLED"]
    child_post_only: Literal[True]


class ParentStrategyEditedRevisionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lifecycle_state: Literal["ACTIVE", "DEACTIVATED"]
    revision: int = Field(ge=1)


class ParentStrategyDeactivatedRevisionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lifecycle_state: Literal["DEACTIVATED"]
    revision: int = Field(ge=1)


class ParentStrategyDeletedRevisionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lifecycle_state: Literal["DELETED"]
    revision: int = Field(ge=1)


class ParentStrategyMaterializedEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use_count: int = Field(ge=1)


class _ParentStrategyEventBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(pattern=_UUID)
    revision: int = Field(ge=1)
    actor_id: str = Field(pattern=_ACTOR_ID.pattern)
    correlation_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,255}$")
    recorded_at: str


class ParentStrategyCreatedEvent(_ParentStrategyEventBase):
    event_type: Literal["PARENT_STRATEGY_CREATED"]
    revision: Literal[1]
    evidence: ParentStrategyCreatedEvidence


class ParentStrategyEditedEvent(_ParentStrategyEventBase):
    event_type: Literal["PARENT_STRATEGY_EDITED"]
    evidence: ParentStrategyEditedRevisionEvidence

    @model_validator(mode="after")
    def revision_matches_evidence(self) -> "ParentStrategyEditedEvent":
        if self.revision != self.evidence.revision:
            raise ValueError("parent_strategy_event_revision_mismatch")
        return self


class ParentStrategyDeactivatedEvent(_ParentStrategyEventBase):
    event_type: Literal["PARENT_STRATEGY_DEACTIVATED"]
    evidence: ParentStrategyDeactivatedRevisionEvidence

    @model_validator(mode="after")
    def revision_matches_evidence(self) -> "ParentStrategyDeactivatedEvent":
        if self.revision != self.evidence.revision:
            raise ValueError("parent_strategy_event_revision_mismatch")
        return self


class ParentStrategyDeletedEvent(_ParentStrategyEventBase):
    event_type: Literal["PARENT_STRATEGY_DELETED"]
    evidence: ParentStrategyDeletedRevisionEvidence

    @model_validator(mode="after")
    def revision_matches_evidence(self) -> "ParentStrategyDeletedEvent":
        if self.revision != self.evidence.revision:
            raise ValueError("parent_strategy_event_revision_mismatch")
        return self


class ParentStrategyMaterializedEvent(_ParentStrategyEventBase):
    event_type: Literal["PARENT_STRATEGY_MATERIALIZED"]
    evidence: ParentStrategyMaterializedEvidence


_ParentStrategyEventValue = Annotated[
    ParentStrategyCreatedEvent
    | ParentStrategyEditedEvent
    | ParentStrategyDeactivatedEvent
    | ParentStrategyDeletedEvent
    | ParentStrategyMaterializedEvent,
    Field(discriminator="event_type"),
]


class ParentStrategyEvent(RootModel[_ParentStrategyEventValue]):
    pass


class ParentStrategyListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ParentStrategyItem]
    total_matching_count: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    next_offset: int | None = Field(default=None, ge=0)
    lifecycle_filter: Literal["ACTIVE", "DEACTIVATED", "DELETED"] | None
    product_filter: str | None
    commands: list[ParentStrategyCommandEvidence]
    command_total_count: int = Field(ge=0)
    command_limit: int = Field(ge=1, le=100)
    command_offset: int = Field(ge=0)
    command_next_offset: int | None = Field(default=None, ge=0)
    trading_authority_granted: Literal[False] = False
    exchange_call_count: Literal[0] = 0
    exchange_mutation_count: Literal[0] = 0


class ParentStrategyDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: ParentStrategyItem
    events: list[ParentStrategyEvent]
    event_total_count: int = Field(ge=0)
    event_limit: int = Field(ge=1, le=100)
    event_offset: int = Field(ge=0)
    event_next_offset: int | None = Field(default=None, ge=0)
    trading_authority_granted: Literal[False] = False
    exchange_call_count: Literal[0] = 0
    exchange_mutation_count: Literal[0] = 0


class ParentStrategyMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["accepted", "replayed", "rejected", "conflict"]
    message: str
    service_method: Literal[
        "create_strategy",
        "edit_strategy",
        "deactivate_strategy",
        "delete_strategy",
    ]
    strategy: ParentStrategyItem | None = None
    correlation_id: str
    idempotency_key: str
    local_state_mutated: bool
    trading_authority_granted: Literal[False] = False
    exchange_call_count: Literal[0] = 0
    exchange_mutation_count: Literal[0] = 0


class OperatorParentStrategyService:
    """Validate authority context and delegate local atomic commands."""

    def __init__(
        self,
        *,
        repository: Any,
        configured_spot_portfolio_id: str,
    ) -> None:
        normalized = ""
        if str(configured_spot_portfolio_id or "").strip():
            try:
                normalized = str(uuid.UUID(str(configured_spot_portfolio_id)))
            except (ValueError, TypeError, AttributeError):
                raise OperatorParentStrategyError(
                    "parent_strategy_portfolio_not_configured"
                ) from None
        self.repository = repository
        self.portfolio_scope_sha256 = (
            hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            if normalized
            else None
        )

    def list_strategies(
        self,
        *,
        lifecycle_state: str | None,
        product_id: str | None,
        limit: int,
        offset: int,
        command_limit: int = 25,
        command_offset: int = 0,
    ) -> ParentStrategyListResponse:
        items, total = self.repository.list_strategies(
            lifecycle_state=lifecycle_state,
            product_id=product_id,
            limit=limit,
            offset=offset,
        )
        commands, command_total = self.repository.list_commands(
            limit=command_limit,
            offset=command_offset,
        )
        return ParentStrategyListResponse(
            items=[self._item(item) for item in items],
            total_matching_count=total,
            limit=limit,
            offset=offset,
            next_offset=offset + limit if offset + limit < total else None,
            lifecycle_filter=lifecycle_state,
            product_filter=product_id,
            commands=[
                ParentStrategyCommandEvidence.model_validate(command)
                for command in commands
            ],
            command_total_count=command_total,
            command_limit=command_limit,
            command_offset=command_offset,
            command_next_offset=(
                command_offset + command_limit
                if command_offset + command_limit < command_total
                else None
            ),
        )

    def get_strategy(
        self,
        *,
        strategy_id: str,
        event_limit: int = 25,
        event_offset: int = 0,
    ) -> ParentStrategyDetailResponse:
        strategy = self.repository.get_strategy(strategy_id)
        events, event_total = self.repository.list_events(
            strategy_id=strategy_id,
            limit=event_limit,
            offset=event_offset,
        )
        return ParentStrategyDetailResponse(
            strategy=self._item(strategy),
            events=[
                ParentStrategyEvent.model_validate(event)
                for event in events
            ],
            event_total_count=event_total,
            event_limit=event_limit,
            event_offset=event_offset,
            event_next_offset=(
                event_offset + event_limit
                if event_offset + event_limit < event_total
                else None
            ),
        )

    def create_strategy(
        self,
        *,
        body: ParentStrategyCreateRequest,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> ParentStrategyMutationResponse:
        self._context(
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        try:
            name = self._name(body.name)
            if self.portfolio_scope_sha256 is None:
                raise OperatorParentStrategyError(
                    "parent_strategy_portfolio_not_configured"
                )
            terms = normalize_parent_strategy_terms(
                product_id=body.product_id,
                side=body.side,
                reference_size=body.reference_size,
                reference_price=body.reference_price,
                target_movement=body.target_movement,
                target_movement_type=body.target_movement_type,
                max_order_replacement=body.max_order_replacement,
                allow_partial_fills=body.allow_partial_fills,
                child_order_type=body.child_order_type,
                child_time_in_force=body.child_time_in_force,
                child_post_only=body.child_post_only,
            )
        except OperatorParentStrategyError as exc:
            self.repository.record_rejected_request(
                operation="CREATE",
                strategy_id=None,
                request_payload=body.model_dump(mode="json"),
                actor_id=actor_id,
                operator_reason=body.operator_reason,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                diagnostic_code=exc.code,
            )
            raise
        record = self.repository.create_strategy(
            name=name,
            terms=terms,
            portfolio_scope_sha256=self.portfolio_scope_sha256,
            actor_id=actor_id,
            operator_reason=body.operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=body.confirm_parent_strategy_create,
        )
        return self._mutation(
            method="create_strategy",
            accepted_message="parent_strategy_created",
            replay_message="parent_strategy_create_replayed",
            record=record,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )

    def edit_strategy(
        self,
        *,
        strategy_id: str,
        body: ParentStrategyEditRequest,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> ParentStrategyMutationResponse:
        self._context(
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        try:
            current = self.repository.get_strategy(strategy_id)
            name = self._name(body.name)
            terms = normalize_parent_strategy_terms(
                product_id=current["product_id"],
                side=current["side"],
                reference_size=current["reference_size"],
                reference_price=current["reference_price"],
                target_movement=body.target_movement,
                target_movement_type=body.target_movement_type,
                max_order_replacement=body.max_order_replacement,
                allow_partial_fills=body.allow_partial_fills,
                child_order_type=body.child_order_type,
                child_time_in_force=body.child_time_in_force,
                child_post_only=body.child_post_only,
            )
        except OperatorParentStrategyError as exc:
            self.repository.record_rejected_request(
                operation="EDIT",
                strategy_id=strategy_id,
                request_payload=body.model_dump(mode="json"),
                actor_id=actor_id,
                operator_reason=body.operator_reason,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                diagnostic_code=exc.code,
            )
            raise
        record = self.repository.edit_strategy(
            strategy_id=strategy_id,
            expected_revision=body.expected_revision,
            name=name,
            terms=terms,
            actor_id=actor_id,
            operator_reason=body.operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=body.confirm_parent_strategy_edit,
        )
        return self._mutation(
            method="edit_strategy",
            accepted_message="parent_strategy_edited",
            replay_message="parent_strategy_edit_replayed",
            record=record,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )

    def deactivate_strategy(
        self,
        *,
        strategy_id: str,
        body: ParentStrategyDeactivateRequest,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> ParentStrategyMutationResponse:
        record = self.repository.deactivate_strategy(
            strategy_id=strategy_id,
            expected_revision=body.expected_revision,
            actor_id=actor_id,
            operator_reason=body.operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=body.confirm_parent_strategy_deactivate,
        )
        return self._mutation(
            method="deactivate_strategy",
            accepted_message="parent_strategy_deactivated",
            replay_message="parent_strategy_deactivate_replayed",
            record=record,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )

    def delete_strategy(
        self,
        *,
        strategy_id: str,
        body: ParentStrategyDeleteRequest,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> ParentStrategyMutationResponse:
        record = self.repository.delete_strategy(
            strategy_id=strategy_id,
            expected_revision=body.expected_revision,
            actor_id=actor_id,
            operator_reason=body.operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=body.confirm_parent_strategy_delete,
        )
        return self._mutation(
            method="delete_strategy",
            accepted_message="parent_strategy_deleted",
            replay_message="parent_strategy_delete_replayed",
            record=record,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )

    def _mutation(
        self,
        *,
        method: Literal[
            "create_strategy",
            "edit_strategy",
            "deactivate_strategy",
            "delete_strategy",
        ],
        accepted_message: str,
        replay_message: str,
        record: dict[str, Any],
        correlation_id: str,
        idempotency_key: str,
    ) -> ParentStrategyMutationResponse:
        replayed = bool(record.get("command_replayed"))
        return ParentStrategyMutationResponse(
            status="replayed" if replayed else "accepted",
            message=replay_message if replayed else accepted_message,
            service_method=method,
            strategy=self._item(record),
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            local_state_mutated=not replayed,
        )

    @staticmethod
    def _item(record: dict[str, Any]) -> ParentStrategyItem:
        allowed = [
            action
            for action in record.get("allowed_actions", [])
            if action in {"EDIT", "DEACTIVATE", "DELETE"}
        ]
        public_record = {
            field: record[field]
            for field in ParentStrategyItem.model_fields
            if field in record
        }
        return ParentStrategyItem.model_validate(
            {
                **public_record,
                "reference_size": str(record["reference_size"]),
                "reference_price": str(record["reference_price"]),
                "target_movement": str(record["target_movement"]),
                "allowed_actions": allowed,
            }
        )

    @staticmethod
    def _name(value: str) -> str:
        normalized = value.strip()
        if (
            not normalized
            or len(normalized) > 80
            or any(ord(char) < 32 or ord(char) == 127 for char in normalized)
        ):
            raise OperatorParentStrategyError(
                "parent_strategy_name_invalid"
            )
        return normalized

    @staticmethod
    def _context(
        *,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> None:
        if (
            _ACTOR_ID.fullmatch(actor_id) is None
            or _EVIDENCE_ID.fullmatch(correlation_id) is None
            or _EVIDENCE_ID.fullmatch(idempotency_key) is None
        ):
            raise OperatorParentStrategyError(
                "parent_strategy_command_context_invalid"
            )


def safe_parent_strategy_code(code: str) -> str:
    return (
        code
        if _SAFE_CODE.fullmatch(code)
        else "parent_strategy_internal_failure"
    )
