"""Typed service boundary for operator stealth-definition administration."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from application.admin_api.operator_stealth_definition import (
    OperatorStealthDefinitionError,
    StealthDefinitionTerms,
    normalize_stealth_definition_terms,
)


_UUID = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_PRODUCT_ID = r"^[A-Z0-9]{1,32}(?:-[A-Z0-9]{1,32}){1,3}$"
_DECIMAL = r"^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,18})?$"
_EVIDENCE_ID = r"^[A-Za-z0-9._:-]{1,255}$"
_ACTOR_ID = r"^[A-Za-z0-9._:@|/-]{1,255}$"
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")


class StealthDefinitionTermsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    product_id: str = Field(pattern=_PRODUCT_ID)
    side: Literal["BUY", "SELL"]
    total_size: str = Field(pattern=_DECIMAL)
    limit_price: str = Field(pattern=_DECIMAL)
    reveal_condition_type: Literal["PRICE", "TIME_DELAY"]
    reveal_price_threshold: str | None = Field(
        default=None,
        pattern=_DECIMAL,
    )
    reveal_direction: Literal["ABOVE", "BELOW"] | None = None
    hold_duration_seconds: int = Field(ge=0, le=86_400)
    delay_seconds: int | None = Field(default=None, ge=0, le=604_800)
    reveal_pricing_policy: Literal[
        "CONFIGURED_LIMIT", "TOP_OF_BOOK", "MIDPOINT"
    ]
    sizing_mode: Literal["FIXED"]
    follow_up_reveal_direction: Literal["SAME", "OPPOSITE"]
    target_movement: str = Field(pattern=_DECIMAL)
    target_movement_type: Literal["P", "A"]
    max_order_replacements: int = Field(ge=0, le=100)
    allow_partial_fills: bool
    post_only: Literal[True]

    @model_validator(mode="after")
    def validate_condition_shape(self) -> "StealthDefinitionTermsRequest":
        if self.reveal_condition_type == "PRICE":
            valid = (
                self.reveal_price_threshold is not None
                and self.reveal_direction is not None
                and self.delay_seconds is None
            )
        else:
            valid = (
                self.reveal_price_threshold is None
                and self.reveal_direction is None
                and self.delay_seconds is not None
                and self.hold_duration_seconds == 0
            )
        if not valid:
            raise ValueError("stealth_definition_condition_shape_invalid")
        return self


class StealthDefinitionCreateRequest(StealthDefinitionTermsRequest):
    definition_id: str | None = Field(default=None, pattern=_UUID)
    operator_reason: str = Field(min_length=1, max_length=240)
    confirm_stealth_definition_create: Literal[True]


class StealthDefinitionEditRequest(StealthDefinitionTermsRequest):
    expected_revision: int = Field(ge=1)
    operator_reason: str = Field(min_length=1, max_length=240)
    confirm_stealth_definition_edit: Literal[True]


class StealthDefinitionCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    operator_reason: str = Field(min_length=1, max_length=240)
    confirm_stealth_definition_cancel: Literal[True]


class StealthDefinitionSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition_id: str = Field(pattern=_UUID)
    expected_revision: int = Field(ge=1)


class StealthDefinitionClearRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selections: list[StealthDefinitionSelection] = Field(
        min_length=1,
        max_length=100,
    )
    operator_reason: str = Field(min_length=1, max_length=240)
    confirm_stealth_definition_clear: Literal[True]


class StealthDefinitionExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition_ids: list[str] = Field(min_length=1, max_length=100)
    operator_reason: str = Field(min_length=1, max_length=240)
    confirm_stealth_definition_export: Literal[True]

    @model_validator(mode="after")
    def validate_ids(self) -> "StealthDefinitionExportRequest":
        if len(set(self.definition_ids)) != len(self.definition_ids):
            raise ValueError("stealth_definition_export_selection_invalid")
        for definition_id in self.definition_ids:
            if re.fullmatch(_UUID, definition_id) is None:
                raise ValueError("stealth_definition_identity_invalid")
        return self


class StealthDefinitionImportItem(StealthDefinitionTermsRequest):
    definition_id: str = Field(pattern=_UUID)


class StealthDefinitionImportPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[StealthDefinitionImportItem] = Field(
        min_length=1,
        max_length=100,
    )
    operator_reason: str = Field(min_length=1, max_length=240)
    confirm_stealth_definition_import_preview: Literal[True]


class StealthDefinitionImportApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    operator_reason: str = Field(min_length=1, max_length=240)
    confirm_stealth_definition_import_apply: Literal[True]


class StealthDefinitionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition_id: str = Field(pattern=_UUID)
    name: str
    portfolio_scope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    admitted_product_catalog_revision_id: str = Field(pattern=_UUID)
    admitted_product_catalog_snapshot_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    product_id: str = Field(pattern=_PRODUCT_ID)
    side: Literal["BUY", "SELL"]
    total_size: str
    limit_price: str
    reveal_condition_type: Literal["PRICE", "TIME_DELAY"]
    reveal_price_threshold: str | None
    reveal_direction: Literal["ABOVE", "BELOW"] | None
    hold_duration_seconds: int = Field(ge=0, le=86_400)
    delay_seconds: int | None = Field(default=None, ge=0, le=604_800)
    reveal_pricing_policy: Literal[
        "CONFIGURED_LIMIT", "TOP_OF_BOOK", "MIDPOINT"
    ]
    sizing_mode: Literal["FIXED"]
    follow_up_reveal_direction: Literal["SAME", "OPPOSITE"]
    target_movement: str
    target_movement_type: Literal["P", "A"]
    max_order_replacements: int = Field(ge=0, le=100)
    allow_partial_fills: bool
    post_only: Literal[True]
    lifecycle_state: Literal["DRAFT", "CANCELLED", "CLEARED"]
    revision: int = Field(ge=1)
    definition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    imported_from_preview_id: str | None = Field(default=None, pattern=_UUID)
    runtime_status: str | None
    runtime_classification: Literal[
        "UNMATERIALIZED", "ACTIVE", "REVEALED", "TERMINAL", "UNKNOWN"
    ]
    blocked_navigation: (
        Literal["REVEAL_CLOSEOUT", "MOVEMENT_REPRICING"] | None
    )
    local_mutation_allowed: bool
    allowed_actions: list[
        Literal["EDIT", "CANCEL", "EXPORT", "CLEAR"]
    ]
    created_at: str
    updated_at: str
    terminal_at: str | None
    trading_authority_granted: Literal[False] = False
    exchange_call_count: Literal[0] = 0
    exchange_mutation_count: Literal[0] = 0


class StealthDefinitionCommandEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal[
        "CREATE",
        "EDIT",
        "CANCEL",
        "CLEAR",
        "EXPORT",
        "IMPORT_PREVIEW",
        "IMPORT_APPLY",
    ]
    state: Literal["IN_PROGRESS", "COMPLETED", "REJECTED"]
    diagnostic_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,95}$")
    definition_id: str | None = Field(default=None, pattern=_UUID)
    result_revision: int | None = Field(default=None, ge=1)
    actor_id: str = Field(pattern=_ACTOR_ID)
    correlation_id: str = Field(pattern=_EVIDENCE_ID)
    idempotency_key: str = Field(pattern=_EVIDENCE_ID)
    created_at: str
    updated_at: str


class StealthDefinitionEventEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lifecycle_state: Literal["DRAFT", "CANCELLED", "CLEARED"] | None = None
    revision: int | None = Field(default=None, ge=1)
    import_preview_id: str | None = Field(default=None, pattern=_UUID)
    export_id: str | None = Field(default=None, pattern=_UUID)
    manifest_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )


class StealthDefinitionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(pattern=_UUID)
    definition_id: str = Field(pattern=_UUID)
    event_type: Literal[
        "STEALTH_DEFINITION_CREATED",
        "STEALTH_DEFINITION_EDITED",
        "STEALTH_DEFINITION_CANCELLED",
        "STEALTH_DEFINITION_CLEARED",
        "STEALTH_DEFINITION_EXPORTED",
        "STEALTH_DEFINITION_IMPORTED",
    ]
    revision: int = Field(ge=1)
    actor_id: str = Field(pattern=_ACTOR_ID)
    correlation_id: str = Field(pattern=_EVIDENCE_ID)
    evidence: StealthDefinitionEventEvidence
    recorded_at: str


class StealthDefinitionImportPreviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ordinal: int = Field(ge=1, le=100)
    definition_id: str | None = Field(default=None, pattern=_UUID)
    valid: bool
    diagnostic_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,95}$")


class StealthDefinitionImportPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_id: str = Field(pattern=_UUID)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: Literal["PREVIEWED", "REJECTED", "APPLIED"]
    item_count: int = Field(ge=1, le=100)
    valid_item_count: int = Field(ge=0, le=100)
    all_items_valid: bool
    items: list[StealthDefinitionImportPreviewItem]
    created_at: str
    updated_at: str
    applied_at: str | None
    local_state_mutated: bool
    trading_authority_granted: Literal[False] = False
    exchange_call_count: Literal[0] = 0
    exchange_mutation_count: Literal[0] = 0


class StealthDefinitionExportManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    export_id: str = Field(pattern=_UUID)
    schema_version: Literal["operator-stealth-definition/v1"]
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    item_count: int = Field(ge=1, le=100)
    items: list[StealthDefinitionImportItem]


class StealthDefinitionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[StealthDefinitionItem]
    total_matching_count: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    next_offset: int | None = Field(default=None, ge=0)
    lifecycle_filter: Literal["DRAFT", "CANCELLED", "CLEARED"] | None
    product_filter: str | None
    commands: list[StealthDefinitionCommandEvidence]
    command_total_count: int = Field(ge=0)
    command_limit: int = Field(ge=1, le=100)
    command_offset: int = Field(ge=0)
    command_next_offset: int | None = Field(default=None, ge=0)
    trading_authority_granted: Literal[False] = False
    exchange_call_count: Literal[0] = 0
    exchange_mutation_count: Literal[0] = 0


class StealthDefinitionDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: StealthDefinitionItem
    events: list[StealthDefinitionEvent]
    event_total_count: int = Field(ge=0)
    event_limit: int = Field(ge=1, le=100)
    event_offset: int = Field(ge=0)
    event_next_offset: int | None = Field(default=None, ge=0)
    trading_authority_granted: Literal[False] = False
    exchange_call_count: Literal[0] = 0
    exchange_mutation_count: Literal[0] = 0


class StealthDefinitionMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["accepted", "rejected", "conflict"]
    message: str = Field(pattern=r"^[a-z][a-z0-9_]{0,95}$")
    service_method: Literal[
        "create_definition",
        "edit_definition",
        "cancel_definition",
        "clear_definitions",
        "export_definitions",
        "preview_import",
        "apply_import",
    ]
    definition: StealthDefinitionItem | None = None
    definitions: list[StealthDefinitionItem] = Field(default_factory=list)
    cleared_count: int = Field(default=0, ge=0, le=100)
    imported_count: int = Field(default=0, ge=0, le=100)
    export: StealthDefinitionExportManifest | None = None
    preview: StealthDefinitionImportPreview | None = None
    correlation_id: str = Field(pattern=_EVIDENCE_ID)
    idempotency_key: str = Field(pattern=_EVIDENCE_ID)
    command_replayed: bool = False
    local_state_mutated: bool
    audit_state_mutated: bool = True
    trading_authority_granted: Literal[False] = False
    exchange_call_count: Literal[0] = 0
    exchange_mutation_count: Literal[0] = 0


class OperatorStealthDefinitionService:
    """Backend authority for definition policy and PostgreSQL commands."""

    def __init__(
        self,
        *,
        repository: Any,
        configured_spot_portfolio_id: str,
    ) -> None:
        try:
            normalized = str(uuid.UUID(configured_spot_portfolio_id))
        except (TypeError, ValueError, AttributeError):
            raise OperatorStealthDefinitionError(
                "stealth_definition_portfolio_not_configured"
            ) from None
        self.repository = repository
        self.portfolio_scope_sha256 = hashlib.sha256(
            normalized.encode()
        ).hexdigest()

    def list_definitions(
        self,
        *,
        lifecycle_state: str | None,
        product_id: str | None,
        limit: int,
        offset: int,
        command_limit: int,
        command_offset: int,
    ) -> StealthDefinitionListResponse:
        items, total = self.repository.list_definitions(
            lifecycle_state=lifecycle_state,
            product_id=product_id,
            limit=limit,
            offset=offset,
        )
        commands, command_total = self.repository.list_commands(
            limit=command_limit,
            offset=command_offset,
        )
        return StealthDefinitionListResponse(
            items=items,
            total_matching_count=total,
            limit=limit,
            offset=offset,
            next_offset=_next(offset, limit, total),
            lifecycle_filter=lifecycle_state,
            product_filter=product_id,
            commands=commands,
            command_total_count=command_total,
            command_limit=command_limit,
            command_offset=command_offset,
            command_next_offset=_next(
                command_offset,
                command_limit,
                command_total,
            ),
        )

    def get_definition(
        self,
        *,
        definition_id: str,
        event_limit: int,
        event_offset: int,
    ) -> StealthDefinitionDetailResponse:
        definition = self.repository.get_definition(definition_id)
        events, total = self.repository.list_events(
            definition_id=definition_id,
            limit=event_limit,
            offset=event_offset,
        )
        return StealthDefinitionDetailResponse(
            definition=definition,
            events=events,
            event_total_count=total,
            event_limit=event_limit,
            event_offset=event_offset,
            event_next_offset=_next(event_offset, event_limit, total),
        )

    def get_import_preview(
        self,
        *,
        preview_id: str,
    ) -> StealthDefinitionImportPreview:
        return StealthDefinitionImportPreview.model_validate(
            self.repository.get_import_preview(preview_id)
        )

    def create_definition(
        self,
        *,
        body: StealthDefinitionCreateRequest,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> StealthDefinitionMutationResponse:
        result = self.repository.create_definition(
            definition_id=body.definition_id,
            terms=_terms(body),
            portfolio_scope_sha256=self.portfolio_scope_sha256,
            actor_id=actor_id,
            operator_reason=body.operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=body.confirm_stealth_definition_create,
        )
        return _mutation(
            service_method="create_definition",
            message="stealth_definition_created",
            result=result,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            definition=result,
        )

    def edit_definition(
        self,
        *,
        definition_id: str,
        body: StealthDefinitionEditRequest,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> StealthDefinitionMutationResponse:
        result = self.repository.edit_definition(
            definition_id=definition_id,
            expected_revision=body.expected_revision,
            terms=_terms(body),
            actor_id=actor_id,
            operator_reason=body.operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=body.confirm_stealth_definition_edit,
        )
        return _mutation(
            service_method="edit_definition",
            message="stealth_definition_edited",
            result=result,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            definition=result,
        )

    def cancel_definition(
        self,
        *,
        definition_id: str,
        body: StealthDefinitionCancelRequest,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> StealthDefinitionMutationResponse:
        result = self.repository.cancel_definition(
            definition_id=definition_id,
            expected_revision=body.expected_revision,
            actor_id=actor_id,
            operator_reason=body.operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=body.confirm_stealth_definition_cancel,
        )
        return _mutation(
            service_method="cancel_definition",
            message="stealth_definition_cancelled",
            result=result,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            definition=result,
        )

    def clear_definitions(
        self,
        *,
        body: StealthDefinitionClearRequest,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> StealthDefinitionMutationResponse:
        result = self.repository.clear_definitions(
            selections=[
                (item.definition_id, item.expected_revision)
                for item in body.selections
            ],
            actor_id=actor_id,
            operator_reason=body.operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=body.confirm_stealth_definition_clear,
        )
        return _mutation(
            service_method="clear_definitions",
            message="stealth_definitions_cleared",
            result=result,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            definitions=result["definitions"],
            cleared_count=result["cleared_count"],
        )

    def export_definitions(
        self,
        *,
        body: StealthDefinitionExportRequest,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> StealthDefinitionMutationResponse:
        result = self.repository.export_definitions(
            definition_ids=body.definition_ids,
            actor_id=actor_id,
            operator_reason=body.operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=body.confirm_stealth_definition_export,
        )
        return _mutation(
            service_method="export_definitions",
            message="stealth_definitions_exported",
            result=result,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            export={
                key: result[key]
                for key in (
                    "export_id",
                    "schema_version",
                    "manifest_sha256",
                    "item_count",
                    "items",
                )
            },
        )

    def preview_import(
        self,
        *,
        body: StealthDefinitionImportPreviewRequest,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> StealthDefinitionMutationResponse:
        items = [
            item.model_dump(mode="json")
            for item in body.items
        ]
        manifest_sha256 = hashlib.sha256(
            json.dumps(
                items,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        result = self.repository.create_import_preview(
            items=items,
            manifest_sha256=manifest_sha256,
            portfolio_scope_sha256=self.portfolio_scope_sha256,
            actor_id=actor_id,
            operator_reason=body.operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=(
                body.confirm_stealth_definition_import_preview
            ),
        )
        return _mutation(
            service_method="preview_import",
            message=(
                "stealth_definition_import_previewed"
                if result["state"] == "PREVIEWED"
                else "stealth_definition_import_preview_rejected"
            ),
            result=result,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            preview=result,
        )

    def apply_import(
        self,
        *,
        preview_id: str,
        body: StealthDefinitionImportApplyRequest,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> StealthDefinitionMutationResponse:
        result = self.repository.apply_import_preview(
            preview_id=preview_id,
            expected_manifest_sha256=body.expected_manifest_sha256,
            portfolio_scope_sha256=self.portfolio_scope_sha256,
            actor_id=actor_id,
            operator_reason=body.operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=body.confirm_stealth_definition_import_apply,
        )
        return _mutation(
            service_method="apply_import",
            message="stealth_definitions_imported",
            result=result,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            definitions=result["definitions"],
            imported_count=result["imported_count"],
        )


def _terms(body: StealthDefinitionTermsRequest) -> StealthDefinitionTerms:
    return normalize_stealth_definition_terms(
        **{
            field: getattr(body, field)
            for field in StealthDefinitionTermsRequest.model_fields
        }
    )


def _mutation(
    *,
    service_method: str,
    message: str,
    result: dict[str, Any],
    correlation_id: str,
    idempotency_key: str,
    definition: dict[str, Any] | None = None,
    definitions: list[dict[str, Any]] | None = None,
    cleared_count: int = 0,
    imported_count: int = 0,
    export: dict[str, Any] | None = None,
    preview: dict[str, Any] | None = None,
) -> StealthDefinitionMutationResponse:
    normalized_definition = (
        _without_command_metadata(definition) if definition else None
    )
    normalized_definitions = [
        _without_command_metadata(item)
        for item in (definitions or [])
    ]
    normalized_preview = (
        _without_command_metadata(preview) if preview else None
    )
    return StealthDefinitionMutationResponse(
        status="accepted",
        message=message,
        service_method=service_method,
        definition=normalized_definition,
        definitions=normalized_definitions,
        cleared_count=cleared_count,
        imported_count=imported_count,
        export=export,
        preview=normalized_preview,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        command_replayed=bool(result.get("command_replayed")),
        local_state_mutated=bool(result.get("local_state_mutated", True)),
        audit_state_mutated=bool(result.get("audit_state_mutated", True)),
    )


def _without_command_metadata(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if key not in {"command_replayed", "audit_state_mutated"}
    }


def rejected_stealth_definition_mutation(
    *,
    service_method: str,
    code: str,
    correlation_id: str,
    idempotency_key: str,
) -> StealthDefinitionMutationResponse:
    code = safe_stealth_definition_code(code)
    is_conflict = any(
        token in code
        for token in (
            "conflict",
            "materialized",
            "not_found",
            "not_draft",
            "not_applicable",
            "changed",
            "terminal",
        )
    )
    return StealthDefinitionMutationResponse(
        status="conflict" if is_conflict else "rejected",
        message=code,
        service_method=service_method,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        local_state_mutated=False,
    )


def safe_stealth_definition_code(value: Any) -> str:
    code = str(value or "").strip().lower()
    if _SAFE_CODE.fullmatch(code) is None:
        return "stealth_definition_unknown"
    return code


def _next(offset: int, limit: int, total: int) -> int | None:
    candidate = offset + limit
    return candidate if candidate < total else None
