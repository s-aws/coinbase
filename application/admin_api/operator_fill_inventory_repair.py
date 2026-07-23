"""Operator-safe fill-ledger import and inventory reconstruction contracts.

The live boundary in this module is read-only. Coinbase fill pages are
normalized in memory into allowlisted values and one-way identifier hashes.
Raw responses, response bodies, exception messages, and raw exchange
identifiers are never part of a model returned by this module.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from core.enums import FillInventoryRepairSelectorType
from core.enums import (
    AdminApiCommandStatus,
    AdminApiPermission,
    FillInventoryRepairAction,
    FillInventoryRepairCaseState,
)


APPROVED_FILL_REPAIR_PRODUCT_ID = "BTC-USDC"
MAX_FILL_REPAIR_WINDOW = timedelta(hours=24)
_UUID = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$"
)
_SHA256 = r"^[0-9a-f]{64}$"
_PUBLIC_EVENT_TYPES = frozenset(
    {
        "CASE_CREATED",
        "CATALOG_REFRESH_CLAIMED",
        "CATALOG_REFRESH_COMPLETED",
        "CATALOG_REFRESH_FAILED",
        "IMPORT_APPLY_CLAIMED",
        "IMPORT_APPLIED",
        "IMPORT_APPLY_FAILED",
        "IMPORT_ROLLBACK_CLAIMED",
        "IMPORT_ROLLED_BACK",
        "IMPORT_ROLLBACK_FAILED",
    }
)
_PUBLIC_EVENT_EVIDENCE_KEYS = frozenset(
    {
        "revision",
        "cycle_count",
        "fill_read_logical_count",
        "fill_read_page_count",
        "catalog_fill_count",
        "missing_fill_count",
        "existing_fill_count",
        "unmatched_fill_count",
        "affected_product_count",
        "imported_fill_count",
        "rolled_back_fill_count",
        "state",
        "plan_sha256",
        "diagnostic_code",
        "coinbase_read_ran",
        "coinbase_read_state",
        "coinbase_order_mutation_ran",
    }
)
_PUBLIC_FIXED_VALUE = re.compile(r"^[A-Za-z][A-Za-z0-9._:-]{0,127}$")
_PUBLIC_EVIDENCE_ID = r"^[A-Za-z0-9._:-]{1,255}$"
_PUBLIC_SERVICE_METHOD_VALUES = frozenset(
    {
        "get_operator_fill_inventory_repair_case",
        "create_operator_fill_inventory_repair_case",
        "refresh_operator_fill_inventory_repair_case",
        "apply_operator_fill_inventory_repair_case",
        "rollback_operator_fill_inventory_repair_case",
    }
)
_PUBLIC_CODE_VALUES = frozenset(
    {
        "operator_fill_inventory_repair_case_loaded",
        "create_operator_fill_inventory_repair_case_accepted",
        "refresh_operator_fill_inventory_repair_case_accepted",
        "apply_operator_fill_inventory_repair_case_accepted",
        "rollback_operator_fill_inventory_repair_case_accepted",
        "fill_inventory_apply_acknowledgement_required",
        "fill_inventory_apply_baseline_changed",
        "fill_inventory_apply_conflict",
        "fill_inventory_apply_identity_alias_conflict",
        "fill_inventory_apply_identity_conflict",
        "fill_inventory_apply_existing_projection_invalid",
        "fill_inventory_apply_not_available",
        "fill_inventory_apply_ownership_mismatch",
        "fill_inventory_apply_plan_required",
        "fill_inventory_apply_projection_changed",
        "fill_inventory_case_conflict",
        "fill_inventory_case_created",
        "fill_inventory_case_not_found",
        "fill_inventory_catalog_call_failed",
        "fill_inventory_catalog_client_order_mismatch",
        "fill_inventory_catalog_duplicate_identity",
        "fill_inventory_catalog_fee_invalid",
        "fill_inventory_catalog_identity_invalid",
        "fill_inventory_catalog_normalization_failed",
        "fill_inventory_catalog_order_mismatch",
        "fill_inventory_catalog_schema_invalid",
        "fill_inventory_catalog_scope_mismatch",
        "fill_inventory_catalog_side_invalid",
        "fill_inventory_catalog_size_mode_invalid",
        "fill_inventory_catalog_time_invalid",
        "fill_inventory_catalog_unavailable",
        "fill_inventory_catalog_unknown",
        "fill_inventory_catalog_value_invalid",
        "fill_inventory_catalog_window_mismatch",
        "fill_inventory_cursor_invalid",
        "fill_inventory_cursor_missing",
        "fill_inventory_cursor_repeated",
        "fill_inventory_cycles_exhausted",
        "fill_inventory_fee_invalid",
        "fill_inventory_goal_cycles_exhausted",
        "fill_inventory_idempotency_conflict",
        "fill_inventory_identity_aliases_invalid",
        "fill_inventory_import_applied",
        "fill_inventory_import_rolled_back",
        "fill_inventory_internal_failure",
        "fill_inventory_negative_inventory",
        "fill_inventory_order_not_eligible",
        "fill_inventory_order_not_found",
        "fill_inventory_page_accounting_mismatch",
        "fill_inventory_page_claim_conflict",
        "fill_inventory_page_claim_sequence_invalid",
        "fill_inventory_page_cursor_hash_invalid",
        "fill_inventory_page_ordinal_invalid",
        "fill_inventory_page_return_conflict",
        "fill_inventory_page_return_incomplete",
        "fill_inventory_pagination_incomplete",
        "fill_inventory_pagination_limit_invalid",
        "fill_inventory_plan_ready",
        "fill_inventory_plan_binding_invalid",
        "fill_inventory_plan_unknown",
        "fill_inventory_portfolio_binding_stale",
        "fill_inventory_portfolio_not_configured",
        "fill_inventory_product_mismatch",
        "fill_inventory_product_not_approved",
        "fill_inventory_refresh_acknowledgement_required",
        "fill_inventory_refresh_claimed",
        "fill_inventory_refresh_failed",
        "fill_inventory_refresh_interrupted_before_call",
        "fill_inventory_refresh_interrupted_returned",
        "fill_inventory_refresh_interrupted_unknown",
        "fill_inventory_refresh_not_available",
        "fill_inventory_refresh_not_claimed",
        "fill_inventory_repository_row_count_invalid",
        "fill_inventory_rest_client_unavailable",
        "fill_inventory_revision_conflict",
        "fill_inventory_rollback_acknowledgement_required",
        "fill_inventory_rollback_alias_count_mismatch",
        "fill_inventory_rollback_alias_ownership_mismatch",
        "fill_inventory_rollback_already_complete",
        "fill_inventory_rollback_baseline_changed",
        "fill_inventory_rollback_conflict",
        "fill_inventory_rollback_fill_count_mismatch",
        "fill_inventory_rollback_fill_ownership_mismatch",
        "fill_inventory_rollback_ledger_changed",
        "fill_inventory_rollback_plan_required",
        "fill_inventory_rollback_prior_projection_changed",
        "fill_inventory_rollback_prior_projection_unverified",
        "fill_inventory_rollback_provenance_missing",
        "fill_inventory_rollback_superseded",
        "fill_inventory_schema_invalid",
        "fill_inventory_selector_invalid",
        "fill_inventory_storage_precision_invalid",
        "fill_inventory_timestamp_invalid",
        "fill_inventory_unmatched_system_order",
        "fill_inventory_value_invalid",
        "fill_inventory_window_invalid",
        "fill_inventory_window_too_wide",
    }
)
_PUBLIC_CODE_PATTERN = (
    r"^(?:"
    + "|".join(re.escape(value) for value in sorted(_PUBLIC_CODE_VALUES))
    + r")$"
)
_PUBLIC_SERVICE_METHOD_PATTERN = (
    r"^(?:"
    + "|".join(
        re.escape(value)
        for value in sorted(_PUBLIC_SERVICE_METHOD_VALUES)
    )
    + r")$"
)
PUBLIC_FILL_INVENTORY_REPAIR_CODES = tuple(sorted(_PUBLIC_CODE_VALUES))


class OperatorFillInventoryRepairError(ValueError):
    """Fixed-code failure that carries no Coinbase or operator-provided text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class OperatorFillInventoryRepairCaseCreateRequest(BaseModel):
    """Create a bounded operator-selected fill and inventory repair case."""

    model_config = ConfigDict(extra="forbid")

    selector_type: FillInventoryRepairSelectorType
    client_order_id: str | None = Field(
        default=None,
        min_length=36,
        max_length=36,
        pattern=_UUID,
    )
    product_id: str | None = Field(default=None, min_length=1, max_length=255)
    window_start: datetime | None = None
    window_end: datetime | None = None
    operator_reason: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def validate_selector(self) -> "OperatorFillInventoryRepairCaseCreateRequest":
        if self.selector_type is FillInventoryRepairSelectorType.EXACT_ORDER:
            valid = (
                self.client_order_id is not None
                and self.product_id is None
                and self.window_start is None
                and self.window_end is None
            )
        elif self.selector_type is FillInventoryRepairSelectorType.PRODUCT:
            valid = (
                self.client_order_id is None
                and self.product_id == APPROVED_FILL_REPAIR_PRODUCT_ID
                and self.window_start is None
                and self.window_end is None
            )
        else:
            valid = (
                self.client_order_id is None
                and self.product_id == APPROVED_FILL_REPAIR_PRODUCT_ID
                and self.window_start is not None
                and self.window_end is not None
            )
            if valid:
                start = _aware_utc(self.window_start)
                end = _aware_utc(self.window_end)
                if end <= start:
                    raise ValueError("fill_inventory_window_invalid")
                if end - start > MAX_FILL_REPAIR_WINDOW:
                    raise ValueError("fill_inventory_window_too_wide")
        if not valid:
            raise ValueError("fill_inventory_selector_invalid")
        return self


class FillInventoryCatalogSelector(BaseModel):
    """Resolved internal selector bound to the configured Test portfolio."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    selector_type: FillInventoryRepairSelectorType
    product_id: str = Field(pattern=r"^BTC-USDC$")
    portfolio_id_sha256: str = Field(pattern=_SHA256)
    client_order_id: str | None = Field(default=None, pattern=_UUID)
    exchange_order_id: str | None = Field(default=None, min_length=1)
    window_start: datetime | None = None
    window_end: datetime | None = None

    @model_validator(mode="after")
    def validate_selector(self) -> "FillInventoryCatalogSelector":
        if self.selector_type is FillInventoryRepairSelectorType.EXACT_ORDER:
            if (
                self.client_order_id is None
                or not self.exchange_order_id
                or self.window_start is not None
                or self.window_end is not None
            ):
                raise ValueError("fill_inventory_selector_invalid")
        elif self.selector_type is FillInventoryRepairSelectorType.PRODUCT:
            if (
                self.client_order_id is not None
                or self.exchange_order_id is not None
                or self.window_start is not None
                or self.window_end is not None
            ):
                raise ValueError("fill_inventory_selector_invalid")
        else:
            if (
                self.client_order_id is not None
                or self.exchange_order_id is not None
                or self.window_start is None
                or self.window_end is None
            ):
                raise ValueError("fill_inventory_selector_invalid")
            start = _aware_utc(self.window_start)
            end = _aware_utc(self.window_end)
            if end <= start:
                raise ValueError("fill_inventory_window_invalid")
            if end - start > MAX_FILL_REPAIR_WINDOW:
                raise ValueError("fill_inventory_window_too_wide")
        return self


class FillInventoryProjectionEntry(BaseModel):
    """Minimal immutable fill values consumed by the FIFO projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fill_identity_sha256: str = Field(pattern=_SHA256)
    product_id: str = Field(pattern=r"^BTC-USDC$")
    side: str = Field(pattern=r"^(BUY|SELL)$")
    quantity: str
    price: str
    fees: str
    trade_time: datetime
    portfolio_id_sha256: str = Field(pattern=_SHA256)

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, value: str) -> str:
        parsed = _decimal(value, code="fill_inventory_value_invalid")
        if parsed <= 0:
            raise ValueError("fill_inventory_value_invalid")
        _require_storage_decimal(parsed, precision=16, scale=8)
        return _format_decimal(parsed)

    @field_validator("price")
    @classmethod
    def validate_price(cls, value: str) -> str:
        parsed = _decimal(value, code="fill_inventory_value_invalid")
        if parsed <= 0:
            raise ValueError("fill_inventory_value_invalid")
        _require_storage_decimal(parsed, precision=24, scale=12)
        return _format_decimal(parsed)

    @field_validator("fees")
    @classmethod
    def validate_nonnegative_decimal(cls, value: str) -> str:
        parsed = _decimal(value, code="fill_inventory_fee_invalid")
        if parsed < 0:
            raise ValueError("fill_inventory_fee_invalid")
        _require_storage_decimal(parsed, precision=16, scale=8)
        return _format_decimal(parsed)

    @field_validator("trade_time")
    @classmethod
    def canonicalize_trade_time(cls, value: datetime) -> datetime:
        return _aware_utc(value)


class NormalizedFillCatalogEntry(FillInventoryProjectionEntry):
    """Allowlisted catalog entry with one-way exchange identity evidence."""

    exchange_order_id_sha256: str = Field(pattern=_SHA256)
    fill_identity_aliases_sha256: list[str] = Field(
        min_length=1,
        max_length=3,
    )
    client_order_id: str = Field(pattern=_UUID)
    portfolio_id_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def validate_identity_aliases(self) -> "NormalizedFillCatalogEntry":
        if (
            len(self.fill_identity_aliases_sha256)
            != len(set(self.fill_identity_aliases_sha256))
            or self.fill_identity_sha256
            not in self.fill_identity_aliases_sha256
            or any(
                re.fullmatch(_SHA256, value) is None
                for value in self.fill_identity_aliases_sha256
            )
        ):
            raise ValueError("fill_inventory_identity_aliases_invalid")
        return self


class FillInventoryCatalogReadResult(BaseModel):
    """Internal no-retry logical catalog result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entries: list[NormalizedFillCatalogEntry] = Field(default_factory=list)
    page_count: int = Field(ge=1, le=200)
    pagination_complete: bool
    unmatched_fill_count: int = Field(ge=0)


class FillInventoryLotProjection(BaseModel):
    """Rebuilt open FIFO inventory lot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lot_identity_sha256: str = Field(pattern=_SHA256)
    product_id: str = Field(pattern=r"^BTC-USDC$")
    remaining_quantity: str
    unit_cost_basis: str
    remaining_cost_basis: str
    acquired_at: datetime


class FillInventoryProductProjection(BaseModel):
    """Backend-derived inventory, cost basis, fee, and realized P/L readback."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    product_id: str = Field(pattern=r"^BTC-USDC$")
    fill_count: int = Field(ge=0)
    open_lot_count: int = Field(ge=0)
    open_quantity: str
    average_cost_basis: str
    remaining_cost_basis: str
    realized_operational_pnl: str
    total_fees: str
    lots: list[FillInventoryLotProjection] = Field(default_factory=list)


class OperatorFillInventoryRepairEventItem(BaseModel):
    """Fixed sanitized audit event for one repair case."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(pattern=_UUID)
    case_id: str = Field(pattern=_UUID)
    event_type: str
    actor_id: Literal["withheld"]
    correlation_id: str = Field(pattern=_PUBLIC_EVIDENCE_ID)
    evidence: dict[str, Any] = Field(default_factory=dict)
    recorded_at: str

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str) -> str:
        if value not in _PUBLIC_EVENT_TYPES:
            raise ValueError("fill_inventory_event_type_not_allowlisted")
        return value

    @field_validator("evidence")
    @classmethod
    def validate_evidence(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not set(value).issubset(_PUBLIC_EVENT_EVIDENCE_KEYS):
            raise ValueError("fill_inventory_event_evidence_not_allowlisted")
        for key, item in value.items():
            if key == "diagnostic_code":
                if item not in _PUBLIC_CODE_VALUES:
                    raise ValueError(
                        "fill_inventory_event_evidence_value_invalid"
                    )
                continue
            if isinstance(item, bool):
                continue
            if isinstance(item, int) and 0 <= item <= 10000:
                continue
            if isinstance(item, str) and (
                _PUBLIC_FIXED_VALUE.fullmatch(item)
                or re.fullmatch(_SHA256, item)
            ):
                continue
            raise ValueError("fill_inventory_event_evidence_value_invalid")
        return value


class OperatorFillInventoryRepairRefreshRequest(BaseModel):
    """Explicit consent for one no-retry logical fill-catalog read."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    manual_live_acknowledgement: bool = False


class OperatorFillInventoryRepairLocalActionRequest(BaseModel):
    """Explicit consent for one reviewed local apply or rollback."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    plan_sha256: str | None = Field(default=None, pattern=_SHA256)
    operator_reason: str = Field(min_length=1, max_length=240)
    operator_acknowledgement: bool = False


class OperatorFillInventoryRepairPlanItem(BaseModel):
    """Sanitized plan readback; internal import candidates are withheld."""

    model_config = ConfigDict(extra="forbid")

    selector_type: FillInventoryRepairSelectorType
    catalog_fill_count: int = Field(ge=0)
    missing_fill_count: int = Field(ge=0)
    existing_fill_count: int = Field(ge=0)
    unmatched_fill_count: int = Field(ge=0)
    affected_product_count: int = Field(ge=0, le=1)
    apply_available: bool
    projection: FillInventoryProductProjection | None = None
    diagnostic_code: str = Field(pattern=_PUBLIC_CODE_PATTERN)
    plan_sha256: str = Field(pattern=_SHA256)


class OperatorFillInventoryRepairCaseItem(BaseModel):
    """Normal operator readback for one durable repair case."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(pattern=_UUID)
    selector_type: FillInventoryRepairSelectorType
    client_order_id: str | None = Field(default=None, pattern=_UUID)
    product_id: str = Field(pattern=r"^BTC-USDC$")
    window_start: str | None = None
    window_end: str | None = None
    state: FillInventoryRepairCaseState
    revision: int = Field(ge=1)
    cycle_count: int = Field(ge=0, le=10)
    goal_cycle_count: int = Field(ge=0, le=10)
    goal_cycle_limit: int = Field(default=10, ge=10, le=10)
    goal_fill_read_logical_count: int = Field(ge=0, le=10)
    goal_fill_read_page_count: int = Field(ge=0)
    fill_read_logical_count: int = Field(ge=0, le=10)
    fill_read_page_count: int = Field(ge=0)
    last_cycle_fill_read_page_count: int = Field(ge=0, le=200)
    last_refresh_coinbase_read_state: str = Field(
        pattern=r"^(NOT_RUN|RETURNED|UNKNOWN_AFTER_PAGE_CLAIM)$"
    )
    catalog_fill_count: int = Field(ge=0)
    missing_fill_count: int = Field(ge=0)
    existing_fill_count: int = Field(ge=0)
    unmatched_fill_count: int = Field(ge=0)
    affected_product_count: int = Field(ge=0, le=1)
    imported_fill_count: int = Field(ge=0)
    rolled_back_fill_count: int = Field(ge=0)
    plan: OperatorFillInventoryRepairPlanItem | None = None
    diagnostic_code: str = Field(pattern=_PUBLIC_CODE_PATTERN)
    portfolio_binding_verified: bool
    allowed_actions: list[FillInventoryRepairAction] = Field(default_factory=list)
    correlation_id: str = Field(pattern=_PUBLIC_EVIDENCE_ID)
    created_at: str
    updated_at: str
    events: list[OperatorFillInventoryRepairEventItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_fixed_state_evidence(
        self,
    ) -> "OperatorFillInventoryRepairCaseItem":
        expected_diagnostic = {
            FillInventoryRepairCaseState.OPEN:
                "fill_inventory_case_created",
            FillInventoryRepairCaseState.REFRESHING:
                "fill_inventory_refresh_claimed",
            FillInventoryRepairCaseState.PLAN_READY:
                "fill_inventory_plan_ready",
            FillInventoryRepairCaseState.APPLIED:
                "fill_inventory_import_applied",
            FillInventoryRepairCaseState.ROLLED_BACK:
                "fill_inventory_import_rolled_back",
        }.get(self.state)
        if (
            expected_diagnostic is not None
            and self.diagnostic_code != expected_diagnostic
        ):
            raise ValueError("fill_inventory_case_state_evidence_invalid")
        if (
            self.state is FillInventoryRepairCaseState.BLOCKED
            and self.diagnostic_code
            in {
                "fill_inventory_case_created",
                "fill_inventory_refresh_claimed",
                "fill_inventory_plan_ready",
                "fill_inventory_import_applied",
                "fill_inventory_import_rolled_back",
            }
        ):
            raise ValueError("fill_inventory_case_state_evidence_invalid")
        if (
            self.cycle_count != self.fill_read_logical_count
            or self.goal_cycle_count
            != self.goal_fill_read_logical_count
            or self.fill_read_page_count
            < self.last_cycle_fill_read_page_count
            or (
                self.last_refresh_coinbase_read_state == "NOT_RUN"
                and self.last_cycle_fill_read_page_count != 0
            )
            or (
                self.last_refresh_coinbase_read_state
                in {"RETURNED", "UNKNOWN_AFTER_PAGE_CLAIM"}
                and self.last_cycle_fill_read_page_count < 1
            )
        ):
            raise ValueError("fill_inventory_case_read_evidence_invalid")
        return self


class OperatorFillInventoryRepairCaseResponse(BaseModel):
    """Mutation/read response for one repair case."""

    model_config = ConfigDict(extra="forbid")

    status: AdminApiCommandStatus
    required_permission: AdminApiPermission
    service_method: str = Field(pattern=_PUBLIC_SERVICE_METHOD_PATTERN)
    message: str = Field(pattern=_PUBLIC_CODE_PATTERN)
    case: OperatorFillInventoryRepairCaseItem | None = None
    audit_id: str | None = Field(
        default=None,
        pattern=_PUBLIC_EVIDENCE_ID,
    )
    correlation_id: str | None = Field(
        default=None,
        pattern=_PUBLIC_EVIDENCE_ID,
    )
    idempotency_key: str | None = Field(
        default=None,
        pattern=_PUBLIC_EVIDENCE_ID,
    )
    replayed: bool = False
    live_coinbase_read_ran: bool | None = False
    coinbase_read_state: str = Field(
        default="NOT_RUN",
        pattern=r"^(NOT_RUN|RETURNED|UNKNOWN_AFTER_PAGE_CLAIM)$",
    )
    live_coinbase_order_mutation_ran: bool = False


class OperatorFillInventoryRepairCaseListResponse(BaseModel):
    """Paginated repair-case list."""

    model_config = ConfigDict(extra="forbid")

    items: list[OperatorFillInventoryRepairCaseItem]
    total_count: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    next_offset: int | None = Field(default=None, ge=0)


class OperatorFillInventoryRepairService:
    """Application coordinator for one bounded fill import batch."""

    def __init__(
        self,
        *,
        repository: Any,
        rest_client: Any,
        rest_client_available: bool,
        configured_portfolio_id: str | None,
    ) -> None:
        self.repository = repository
        self.rest_client = rest_client
        self.rest_client_available = rest_client_available
        self.configured_portfolio_id = str(configured_portfolio_id or "").strip()

    def get_case(self, case_id: str) -> dict[str, Any]:
        case = self.repository.get_case(case_id)
        if not isinstance(case, dict):
            raise OperatorFillInventoryRepairError(
                "fill_inventory_case_not_found"
            )
        return case

    def list_cases(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        return self.repository.list_cases(limit=limit, offset=offset)

    def portfolio_binding_verified(self, case: Mapping[str, Any]) -> bool:
        return bool(
            self.configured_portfolio_id
            and _sha256(self.configured_portfolio_id)
            == _text(case.get("portfolio_id_sha256"))
        )

    def create_case(
        self,
        *,
        body: OperatorFillInventoryRepairCaseCreateRequest,
        actor_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        if not self.configured_portfolio_id:
            raise OperatorFillInventoryRepairError(
                "fill_inventory_portfolio_not_configured"
            )
        portfolio_hash = _sha256(self.configured_portfolio_id)
        if body.selector_type is FillInventoryRepairSelectorType.EXACT_ORDER:
            local = self.repository.resolve_exact_order(
                client_order_id=body.client_order_id,
                configured_portfolio_id=self.configured_portfolio_id,
            )
            selector = FillInventoryCatalogSelector(
                selector_type=body.selector_type,
                product_id=local["product_id"],
                client_order_id=body.client_order_id,
                exchange_order_id=str(local["exchange_order_id"]),
                portfolio_id_sha256=portfolio_hash,
            )
        else:
            selector = FillInventoryCatalogSelector(
                selector_type=body.selector_type,
                product_id=body.product_id,
                window_start=body.window_start,
                window_end=body.window_end,
                portfolio_id_sha256=portfolio_hash,
            )
        return self.repository.create_case(
            selector=selector,
            actor_id=actor_id,
            operator_reason=body.operator_reason,
            correlation_id=correlation_id,
        )

    def refresh_case(
        self,
        *,
        case_id: str,
        expected_revision: int,
        actor_id: str,
        correlation_id: str,
        manual_live_acknowledgement: bool,
    ) -> dict[str, Any]:
        if manual_live_acknowledgement is not True:
            raise OperatorFillInventoryRepairError(
                "fill_inventory_refresh_acknowledgement_required"
            )
        if not self.rest_client_available or self.rest_client is None:
            raise OperatorFillInventoryRepairError(
                "fill_inventory_rest_client_unavailable"
            )
        if not callable(getattr(self.rest_client, "get_fills", None)):
            raise OperatorFillInventoryRepairError(
                "fill_inventory_catalog_unavailable"
            )
        case = self.get_case(case_id)
        if not self.portfolio_binding_verified(case):
            raise OperatorFillInventoryRepairError(
                "fill_inventory_portfolio_binding_stale"
            )
        selector = self._selector_from_case(case)
        claimed = self.repository.begin_refresh(
            case_id=case_id,
            expected_revision=expected_revision,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        claimed_revision = int(claimed["revision"])
        try:
            catalog = read_operator_fill_catalog(
                self.rest_client,
                selector=selector,
                retail_portfolio_id=self.configured_portfolio_id,
                resolve_system_order=lambda order_id, product_id: (
                    self.repository.resolve_system_order(
                        exchange_order_id=order_id,
                        product_id=product_id,
                        portfolio_id_sha256=selector.portfolio_id_sha256,
                    )
                ),
                on_page_call=lambda ordinal, cursor_sha256: (
                    self.repository.record_fill_page_call(
                        case_id=case_id,
                        expected_revision=claimed_revision,
                        page_ordinal=ordinal,
                        cursor_sha256=cursor_sha256,
                    )
                ),
                on_page_returned=lambda ordinal: (
                    self.repository.record_fill_page_returned(
                        case_id=case_id,
                        expected_revision=claimed_revision,
                        page_ordinal=ordinal,
                    )
                ),
            )
        except OperatorFillInventoryRepairError as exc:
            return self.repository.fail_refresh(
                case_id=case_id,
                expected_revision=claimed_revision,
                diagnostic_code=exc.code,
                actor_id=actor_id,
                correlation_id=correlation_id,
            )
        except Exception:
            return self.repository.fail_refresh(
                case_id=case_id,
                expected_revision=claimed_revision,
                diagnostic_code="fill_inventory_catalog_unknown",
                actor_id=actor_id,
                correlation_id=correlation_id,
            )
        try:
            return self.repository.complete_refresh(
                case_id=case_id,
                expected_revision=claimed_revision,
                catalog=catalog,
                actor_id=actor_id,
                correlation_id=correlation_id,
            )
        except OperatorFillInventoryRepairError as exc:
            return self.repository.fail_refresh(
                case_id=case_id,
                expected_revision=claimed_revision,
                diagnostic_code=exc.code,
                actor_id=actor_id,
                correlation_id=correlation_id,
            )
        except Exception:
            return self.repository.fail_refresh(
                case_id=case_id,
                expected_revision=claimed_revision,
                diagnostic_code="fill_inventory_plan_unknown",
                actor_id=actor_id,
                correlation_id=correlation_id,
            )

    def apply_case(
        self,
        *,
        case_id: str,
        expected_revision: int,
        plan_sha256: str | None,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        operator_acknowledgement: bool,
    ) -> dict[str, Any]:
        if operator_acknowledgement is not True:
            raise OperatorFillInventoryRepairError(
                "fill_inventory_apply_acknowledgement_required"
            )
        if not plan_sha256:
            raise OperatorFillInventoryRepairError(
                "fill_inventory_apply_plan_required"
            )
        case = self.get_case(case_id)
        if not self.portfolio_binding_verified(case):
            raise OperatorFillInventoryRepairError(
                "fill_inventory_portfolio_binding_stale"
            )
        return self.repository.apply_import(
            case_id=case_id,
            expected_revision=expected_revision,
            plan_sha256=plan_sha256,
            current_portfolio_id_sha256=_sha256(
                self.configured_portfolio_id
            ),
            actor_id=actor_id,
            operator_reason=operator_reason,
            correlation_id=correlation_id,
        )

    def rollback_case(
        self,
        *,
        case_id: str,
        expected_revision: int,
        plan_sha256: str | None,
        actor_id: str,
        operator_reason: str,
        correlation_id: str,
        operator_acknowledgement: bool,
    ) -> dict[str, Any]:
        if operator_acknowledgement is not True:
            raise OperatorFillInventoryRepairError(
                "fill_inventory_rollback_acknowledgement_required"
            )
        if not plan_sha256:
            raise OperatorFillInventoryRepairError(
                "fill_inventory_rollback_plan_required"
            )
        case = self.get_case(case_id)
        if not self.portfolio_binding_verified(case):
            raise OperatorFillInventoryRepairError(
                "fill_inventory_portfolio_binding_stale"
            )
        return self.repository.rollback_import(
            case_id=case_id,
            expected_revision=expected_revision,
            plan_sha256=plan_sha256,
            current_portfolio_id_sha256=_sha256(
                self.configured_portfolio_id
            ),
            actor_id=actor_id,
            operator_reason=operator_reason,
            correlation_id=correlation_id,
        )

    def _selector_from_case(
        self,
        case: Mapping[str, Any],
    ) -> FillInventoryCatalogSelector:
        selector_type = FillInventoryRepairSelectorType(
            _text(case.get("selector_type"))
        )
        kwargs: dict[str, Any] = {
            "selector_type": selector_type,
            "product_id": _text(case.get("product_id")),
            "portfolio_id_sha256": _text(
                case.get("portfolio_id_sha256")
            ),
        }
        if selector_type is FillInventoryRepairSelectorType.EXACT_ORDER:
            local = self.repository.resolve_exact_order(
                client_order_id=_text(case.get("client_order_id")),
                configured_portfolio_id=self.configured_portfolio_id,
            )
            kwargs.update(
                client_order_id=_text(case.get("client_order_id")),
                exchange_order_id=_text(local.get("exchange_order_id")),
            )
        elif selector_type is FillInventoryRepairSelectorType.TIME_WINDOW:
            kwargs.update(
                window_start=case.get("window_start"),
                window_end=case.get("window_end"),
            )
        return FillInventoryCatalogSelector(**kwargs)


def build_operator_fill_inventory_repair_case_item(
    record: dict[str, Any],
    *,
    events: list[dict[str, Any]] | None = None,
    portfolio_binding_verified: bool,
) -> OperatorFillInventoryRepairCaseItem:
    """Project one repository record without internal catalog candidates."""

    plan_record = record.get("plan")
    stored_plan_sha256 = record.get("plan_sha256")
    if (
        isinstance(plan_record, Mapping)
        and (
            re.fullmatch(_SHA256, str(stored_plan_sha256 or "")) is None
            or _sha256_json(plan_record) != stored_plan_sha256
        )
    ) or (
        not isinstance(plan_record, Mapping)
        and stored_plan_sha256 is not None
    ):
        raise OperatorFillInventoryRepairError(
            "fill_inventory_plan_binding_invalid"
        )
    plan: OperatorFillInventoryRepairPlanItem | None = None
    if isinstance(plan_record, Mapping):
        sanitized = {
            key: plan_record.get(key)
            for key in (
                "selector_type",
                "catalog_fill_count",
                "missing_fill_count",
                "existing_fill_count",
                "unmatched_fill_count",
                "affected_product_count",
                "apply_available",
                "projection",
                "diagnostic_code",
            )
        }
        sanitized["plan_sha256"] = record.get("plan_sha256")
        plan = OperatorFillInventoryRepairPlanItem.model_validate(sanitized)
    state = FillInventoryRepairCaseState(record["state"])
    actions: list[FillInventoryRepairAction] = []
    if portfolio_binding_verified:
        if (
            state
            in {
                FillInventoryRepairCaseState.OPEN,
                FillInventoryRepairCaseState.PLAN_READY,
                FillInventoryRepairCaseState.BLOCKED,
            }
            and int(record.get("cycle_count") or 0) < 10
            and int(record.get("goal_cycle_count") or 0) < 10
        ):
            actions.append(FillInventoryRepairAction.REFRESH)
        if (
            state is FillInventoryRepairCaseState.PLAN_READY
            and plan is not None
            and plan.apply_available
        ):
            actions.append(FillInventoryRepairAction.APPLY)
        if state is FillInventoryRepairCaseState.APPLIED:
            actions.append(FillInventoryRepairAction.ROLLBACK)
    event_items = [
        OperatorFillInventoryRepairEventItem(
            event_id=str(event["event_id"]),
            case_id=str(event["case_id"]),
            event_type=str(event["event_type"]),
            actor_id="withheld",
            correlation_id=str(event["correlation_id"]),
            evidence=dict(event.get("evidence") or {}),
            recorded_at=_iso_text(event["recorded_at"]),
        )
        for event in (events or [])
    ]
    return OperatorFillInventoryRepairCaseItem(
        case_id=str(record["case_id"]),
        selector_type=record["selector_type"],
        client_order_id=record.get("client_order_id"),
        product_id=record["product_id"],
        window_start=_iso_text(record.get("window_start")),
        window_end=_iso_text(record.get("window_end")),
        state=state,
        revision=int(record["revision"]),
        cycle_count=int(record.get("cycle_count") or 0),
        goal_cycle_count=int(record.get("goal_cycle_count") or 0),
        goal_cycle_limit=10,
        goal_fill_read_logical_count=int(
            record.get("goal_fill_read_logical_count") or 0
        ),
        goal_fill_read_page_count=int(
            record.get("goal_fill_read_page_count") or 0
        ),
        fill_read_logical_count=int(
            record.get("fill_read_logical_count") or 0
        ),
        fill_read_page_count=int(record.get("fill_read_page_count") or 0),
        last_cycle_fill_read_page_count=int(
            record.get("last_cycle_fill_read_page_count") or 0
        ),
        last_refresh_coinbase_read_state=str(
            record.get("last_refresh_coinbase_read_state") or "NOT_RUN"
        ),
        catalog_fill_count=int(record.get("catalog_fill_count") or 0),
        missing_fill_count=int(record.get("missing_fill_count") or 0),
        existing_fill_count=int(record.get("existing_fill_count") or 0),
        unmatched_fill_count=int(record.get("unmatched_fill_count") or 0),
        affected_product_count=int(
            record.get("affected_product_count") or 0
        ),
        imported_fill_count=int(record.get("imported_fill_count") or 0),
        rolled_back_fill_count=int(
            record.get("rolled_back_fill_count") or 0
        ),
        plan=plan,
        diagnostic_code=str(record["diagnostic_code"]),
        portfolio_binding_verified=portfolio_binding_verified,
        allowed_actions=actions,
        correlation_id=str(record["correlation_id"]),
        created_at=_iso_text(record["created_at"]),
        updated_at=_iso_text(record["updated_at"]),
        events=event_items,
    )


def read_operator_fill_catalog(
    rest_client: Any,
    *,
    selector: FillInventoryCatalogSelector,
    retail_portfolio_id: str,
    resolve_system_order: Callable[[str, str], Mapping[str, Any] | None],
    on_page_call: Callable[[int, str | None], None] | None = None,
    on_page_returned: Callable[[int], None] | None = None,
    maximum_pages: int = 200,
) -> FillInventoryCatalogReadResult:
    """Read one complete fill catalog without retrying any page."""

    get_fills = getattr(rest_client, "get_fills", None)
    if not callable(get_fills):
        raise OperatorFillInventoryRepairError(
            "fill_inventory_catalog_unavailable"
        )
    if not retail_portfolio_id.strip():
        raise OperatorFillInventoryRepairError(
            "fill_inventory_portfolio_not_configured"
        )
    if type(maximum_pages) is not int or not 1 <= maximum_pages <= 200:
        raise OperatorFillInventoryRepairError(
            "fill_inventory_pagination_limit_invalid"
        )

    cursor: str | None = None
    seen_cursors: set[str] = set()
    entries: list[NormalizedFillCatalogEntry] = []
    unmatched_count = 0
    page_count = 0
    while True:
        page_count += 1
        if page_count > maximum_pages:
            raise OperatorFillInventoryRepairError(
                "fill_inventory_pagination_incomplete"
            )
        kwargs: dict[str, Any] = {
            "product_ids": [selector.product_id],
            "retail_portfolio_id": retail_portfolio_id,
            "limit": 100,
        }
        if selector.exchange_order_id is not None:
            kwargs["order_ids"] = [selector.exchange_order_id]
        if selector.window_start is not None:
            kwargs["start_sequence_timestamp"] = _iso_utc(
                selector.window_start
            )
        if selector.window_end is not None:
            kwargs["end_sequence_timestamp"] = _iso_utc(
                selector.window_end
            )
        if cursor is not None:
            kwargs["cursor"] = cursor
        if on_page_call is not None:
            on_page_call(
                page_count,
                _sha256(cursor) if cursor is not None else None,
            )
        try:
            response = get_fills(**kwargs)
        except OperatorFillInventoryRepairError:
            raise
        except Exception as exc:
            raise OperatorFillInventoryRepairError(
                "fill_inventory_catalog_call_failed"
            ) from exc
        if on_page_returned is not None:
            on_page_returned(page_count)
        page = _response_mapping(response)
        raw_fills = page.get("fills")
        if not isinstance(raw_fills, list):
            raise OperatorFillInventoryRepairError(
                "fill_inventory_catalog_schema_invalid"
            )

        for raw in raw_fills:
            if not isinstance(raw, Mapping):
                raise OperatorFillInventoryRepairError(
                    "fill_inventory_catalog_schema_invalid"
                )
            entry = _normalize_fill(
                raw,
                selector=selector,
                resolve_system_order=resolve_system_order,
            )
            if entry is None:
                unmatched_count += 1
            else:
                entries.append(entry)

        next_cursor = page.get("cursor")
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise OperatorFillInventoryRepairError(
                "fill_inventory_cursor_invalid"
            )
        next_cursor = (next_cursor or "").strip()
        has_next_value = page.get("has_next")
        if has_next_value is not None and not isinstance(has_next_value, bool):
            raise OperatorFillInventoryRepairError(
                "fill_inventory_catalog_schema_invalid"
            )
        has_next = (
            has_next_value
            if isinstance(has_next_value, bool)
            else bool(next_cursor)
        )
        if not has_next:
            break
        if not next_cursor:
            raise OperatorFillInventoryRepairError(
                "fill_inventory_cursor_missing"
            )
        if next_cursor in seen_cursors:
            raise OperatorFillInventoryRepairError(
                "fill_inventory_cursor_repeated"
            )
        if page_count >= maximum_pages:
            raise OperatorFillInventoryRepairError(
                "fill_inventory_pagination_incomplete"
            )
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    entries.sort(key=lambda item: (item.trade_time, item.fill_identity_sha256))
    return FillInventoryCatalogReadResult(
        entries=entries,
        page_count=page_count,
        pagination_complete=True,
        unmatched_fill_count=unmatched_count,
    )


def build_fill_inventory_projection(
    *,
    product_id: str,
    entries: list[FillInventoryProjectionEntry],
) -> FillInventoryProductProjection:
    """Rebuild deterministic FIFO lots, cost basis, fees, and realized P/L."""

    if product_id != APPROVED_FILL_REPAIR_PRODUCT_ID:
        raise OperatorFillInventoryRepairError(
            "fill_inventory_product_not_approved"
        )
    lots: list[dict[str, Any]] = []
    realized_pnl = Decimal("0")
    total_fees = Decimal("0")
    ordered = sorted(
        entries,
        key=lambda item: (item.trade_time, item.fill_identity_sha256),
    )
    for entry in ordered:
        if entry.product_id != product_id:
            raise OperatorFillInventoryRepairError(
                "fill_inventory_product_mismatch"
            )
        quantity = _decimal(entry.quantity, code="fill_inventory_value_invalid")
        price = _decimal(entry.price, code="fill_inventory_value_invalid")
        fees = _decimal(entry.fees, code="fill_inventory_fee_invalid")
        total_fees += fees
        if entry.side == "BUY":
            total_cost = quantity * price + fees
            lots.append(
                {
                    "identity": entry.fill_identity_sha256,
                    "quantity": quantity,
                    "unit_cost": total_cost / quantity,
                    "acquired_at": entry.trade_time,
                }
            )
            continue

        remaining = quantity
        sell_unit_fee = fees / quantity
        for lot in lots:
            available = lot["quantity"]
            if available <= 0:
                continue
            consumed = min(available, remaining)
            realized_pnl += consumed * (
                price - sell_unit_fee - lot["unit_cost"]
            )
            lot["quantity"] -= consumed
            remaining -= consumed
            if remaining <= 0:
                break
        if remaining > 0:
            raise OperatorFillInventoryRepairError(
                "fill_inventory_negative_inventory"
            )

    open_lots = [lot for lot in lots if lot["quantity"] > 0]
    open_quantity = sum(
        (lot["quantity"] for lot in open_lots),
        Decimal("0"),
    )
    remaining_cost = sum(
        (lot["quantity"] * lot["unit_cost"] for lot in open_lots),
        Decimal("0"),
    )
    average_cost = (
        remaining_cost / open_quantity if open_quantity > 0 else Decimal("0")
    )
    lot_models = [
        FillInventoryLotProjection(
            lot_identity_sha256=lot["identity"],
            product_id=product_id,
            remaining_quantity=_format_decimal(lot["quantity"]),
            unit_cost_basis=_format_decimal(lot["unit_cost"]),
            remaining_cost_basis=_format_decimal(
                lot["quantity"] * lot["unit_cost"]
            ),
            acquired_at=lot["acquired_at"],
        )
        for lot in open_lots
    ]
    return FillInventoryProductProjection(
        product_id=product_id,
        fill_count=len(ordered),
        open_lot_count=len(lot_models),
        open_quantity=_format_decimal(open_quantity),
        average_cost_basis=_format_decimal(average_cost),
        remaining_cost_basis=_format_decimal(remaining_cost),
        realized_operational_pnl=_format_decimal(realized_pnl),
        total_fees=_format_decimal(total_fees),
        lots=lot_models,
    )


def _normalize_fill(
    raw: Mapping[str, Any],
    *,
    selector: FillInventoryCatalogSelector,
    resolve_system_order: Callable[[str, str], Mapping[str, Any] | None],
) -> NormalizedFillCatalogEntry | None:
    order_id = _text(raw.get("order_id"))
    product_id = _text(raw.get("product_id"))
    if not order_id or product_id != selector.product_id:
        raise OperatorFillInventoryRepairError(
            "fill_inventory_catalog_identity_invalid"
        )
    if selector.exchange_order_id is not None and order_id != selector.exchange_order_id:
        raise OperatorFillInventoryRepairError(
            "fill_inventory_catalog_order_mismatch"
        )
    local = resolve_system_order(order_id, product_id)
    if not isinstance(local, Mapping):
        return None
    if not bool(local.get("system_owned")):
        return None
    if _text(local.get("product_id")) != product_id:
        return None
    if _text(local.get("portfolio_id_sha256")) != selector.portfolio_id_sha256:
        return None
    client_order_id = _text(local.get("client_order_id"))
    if re.fullmatch(_UUID, client_order_id) is None:
        return None
    if selector.client_order_id is not None and client_order_id != selector.client_order_id:
        raise OperatorFillInventoryRepairError(
            "fill_inventory_catalog_client_order_mismatch"
        )

    side = _text(raw.get("side")).upper()
    if side not in {"BUY", "SELL"}:
        raise OperatorFillInventoryRepairError(
            "fill_inventory_catalog_side_invalid"
        )
    price = _decimal(raw.get("price"), code="fill_inventory_catalog_value_invalid")
    size = _decimal(
        raw.get("size", raw.get("base_size")),
        code="fill_inventory_catalog_value_invalid",
    )
    if price <= 0 or size <= 0:
        raise OperatorFillInventoryRepairError(
            "fill_inventory_catalog_value_invalid"
        )
    size_in_quote = _parse_size_in_quote(raw.get("size_in_quote"))
    quantity = size / price if size_in_quote else size
    fees = _decimal(
        raw.get("commission", raw.get("fee", "0")),
        code="fill_inventory_catalog_fee_invalid",
    )
    if fees < 0:
        raise OperatorFillInventoryRepairError(
            "fill_inventory_catalog_fee_invalid"
        )
    trade_time = _parse_datetime(
        raw.get("trade_time", raw.get("created_at", raw.get("time")))
    )
    if selector.window_start is not None and trade_time < _aware_utc(selector.window_start):
        raise OperatorFillInventoryRepairError(
            "fill_inventory_catalog_window_mismatch"
        )
    if selector.window_end is not None and trade_time > _aware_utc(selector.window_end):
        raise OperatorFillInventoryRepairError(
            "fill_inventory_catalog_window_mismatch"
        )

    entry_id = _text(raw.get("entry_id", raw.get("fill_id")))
    trade_id = _text(raw.get("trade_id"))
    identity_material = entry_id or trade_id
    if not identity_material:
        identity_material = "|".join(
            (
                order_id,
                product_id,
                side,
                _format_decimal(quantity),
                _format_decimal(price),
                _iso_utc(trade_time),
            )
        )
    identity_aliases = list(
        dict.fromkeys(
            _sha256(value)
            for value in (entry_id, trade_id, identity_material)
            if value
        )
    )
    return NormalizedFillCatalogEntry(
        fill_identity_sha256=_sha256(identity_material),
        fill_identity_aliases_sha256=identity_aliases,
        exchange_order_id_sha256=_sha256(order_id),
        client_order_id=client_order_id,
        product_id=product_id,
        side=side,
        quantity=_format_decimal(quantity),
        price=_format_decimal(price),
        fees=_format_decimal(fees),
        trade_time=trade_time,
        portfolio_id_sha256=selector.portfolio_id_sha256,
    )


def _response_mapping(response: Any) -> Mapping[str, Any]:
    if isinstance(response, Mapping):
        return response
    converter = getattr(response, "to_dict", None)
    if not callable(converter):
        raise OperatorFillInventoryRepairError(
            "fill_inventory_catalog_schema_invalid"
        )
    try:
        converted = converter()
    except Exception as exc:
        raise OperatorFillInventoryRepairError(
            "fill_inventory_catalog_normalization_failed"
        ) from exc
    if not isinstance(converted, Mapping):
        raise OperatorFillInventoryRepairError(
            "fill_inventory_catalog_schema_invalid"
        )
    return converted


def _decimal(value: Any, *, code: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise OperatorFillInventoryRepairError(code) from exc
    if not parsed.is_finite():
        raise OperatorFillInventoryRepairError(code)
    return parsed


def _require_storage_decimal(
    value: Decimal,
    *,
    precision: int,
    scale: int,
) -> None:
    """Reject values PostgreSQL would round in the installed fill schema."""

    quantum = Decimal(1).scaleb(-scale)
    try:
        if value != value.quantize(quantum):
            raise OperatorFillInventoryRepairError(
                "fill_inventory_storage_precision_invalid"
            )
    except InvalidOperation as exc:
        raise OperatorFillInventoryRepairError(
            "fill_inventory_storage_precision_invalid"
        ) from exc
    integer_digits = max(value.adjusted() + 1, 0) if value else 0
    if integer_digits > precision - scale:
        raise OperatorFillInventoryRepairError(
            "fill_inventory_storage_precision_invalid"
        )


def _parse_size_in_quote(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise OperatorFillInventoryRepairError(
        "fill_inventory_catalog_size_mode_invalid"
    )


def _format_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    normalized = value.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _aware_utc(value)
    text = _text(value)
    if not text:
        raise OperatorFillInventoryRepairError(
            "fill_inventory_catalog_time_invalid"
        )
    try:
        return _aware_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError as exc:
        raise OperatorFillInventoryRepairError(
            "fill_inventory_catalog_time_invalid"
        ) from exc


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return _aware_utc(value).isoformat().replace("+00:00", "Z")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _iso_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _iso_utc(value)
    return str(value)
