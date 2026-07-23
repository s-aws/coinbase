"""Backend-owned Product Catalog operator workflow."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from application.admin_api.operator_product_catalog import (
    OperatorProductCatalogError,
    ProductCatalogLifecycle,
    read_operator_product_catalog,
)
from database.operator_product_catalog import (
    OperatorProductCatalogRepository,
)


_UUID = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$"
)
_SHA256 = r"^[0-9a-f]{64}$"
_EVIDENCE_ID = r"^[A-Za-z0-9._:-]{1,255}$"
_PRODUCT_ID = r"^[A-Z0-9]{1,32}(?:-[A-Z0-9]{1,32}){1,3}$"
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
_UUID_VALUE = re.compile(_UUID)
_EVENT_EVIDENCE_KEYS: dict[str, frozenset[str]] = {
    "CATALOG_REFRESH_CLAIMED": frozenset({"cycle_number"}),
    "CATALOG_REFRESH_PROPOSED": frozenset(
        {
            "product_count",
            "added_count",
            "changed_count",
            "removed_count",
            "page_count",
        }
    ),
    "CATALOG_REFRESH_FAILED": frozenset(
        {"state", "read_state", "diagnostic_code"}
    ),
    "CATALOG_REFRESH_RECOVERED_UNKNOWN": frozenset(
        {"state", "read_state", "diagnostic_code"}
    ),
    "CATALOG_REFRESH_RECOVERED_NOT_RETURNED": frozenset(
        {"state", "read_state", "diagnostic_code"}
    ),
    "CATALOG_REFRESH_RECOVERED_INCOMPLETE": frozenset(
        {"state", "read_state", "diagnostic_code"}
    ),
    "CATALOG_COMMAND_REJECTED": frozenset(
        {"operation", "diagnostic_code"}
    ),
    "CATALOG_REVISION_APPROVED": frozenset(
        {"revision", "product_count"}
    ),
    "PRODUCT_ENABLED": frozenset({"action", "lifecycle"}),
    "PRODUCT_DISABLED": frozenset({"action", "lifecycle"}),
    "PRODUCT_RETIRED": frozenset({"action", "lifecycle"}),
    "CATALOG_REVISION_ROLLED_BACK": frozenset(
        {"target_revision_id"}
    ),
}


class ProductCatalogRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_active_revision_id: str | None = Field(
        default=None,
        pattern=_UUID,
    )
    operator_reason: str = Field(min_length=1, max_length=240)
    confirm_one_no_retry_product_catalog_read: Literal[True]


class ProductCatalogApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    snapshot_sha256: str = Field(pattern=_SHA256)
    operator_reason: str = Field(min_length=1, max_length=240)
    confirm_catalog_approval: Literal[True]


class ProductCatalogLifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_active_revision_id: str = Field(pattern=_UUID)
    expected_active_revision: int = Field(ge=1)
    operator_reason: str = Field(min_length=1, max_length=240)
    confirm_product_lifecycle_change: Literal[True]


class ProductCatalogRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_active_revision_id: str = Field(pattern=_UUID)
    expected_active_revision: int = Field(ge=1)
    target_snapshot_sha256: str = Field(pattern=_SHA256)
    operator_reason: str = Field(min_length=1, max_length=240)
    confirm_exact_catalog_rollback: Literal[True]


class ProductCatalogGoalBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_count: int = Field(ge=0, le=10)
    cycle_limit: Literal[10] = 10
    logical_read_count: int = Field(ge=0, le=10)
    page_count: int = Field(ge=0, le=1000)
    trading_authority_granted: Literal[False] = False
    portfolio_scope_expanded: Literal[False] = False
    exchange_mutation_count: Literal[0] = 0


class ProductCatalogRevisionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision_id: str = Field(pattern=_UUID)
    sequence_number: int = Field(ge=1)
    revision: int = Field(ge=1)
    state: Literal["PROPOSED", "APPROVED", "APPLIED", "ROLLED_BACK"]
    source: Literal["COINBASE_CATALOG", "OPERATOR_LIFECYCLE", "ROLLBACK"]
    source_cycle_id: str | None = Field(default=None, pattern=_UUID)
    parent_revision_id: str | None = Field(default=None, pattern=_UUID)
    rollback_of_revision_id: str | None = Field(default=None, pattern=_UUID)
    snapshot_sha256: str = Field(pattern=_SHA256)
    diff_sha256: str = Field(pattern=_SHA256)
    product_count: int = Field(ge=0)
    added_count: int = Field(ge=0)
    changed_count: int = Field(ge=0)
    removed_count: int = Field(ge=0)
    unchanged_count: int = Field(ge=0)
    active: bool
    allowed_actions: list[
        Literal["APPROVE", "ROLLBACK"]
    ] = Field(default_factory=list)
    trading_authority_granted: Literal[False] = False
    portfolio_scope_expanded: Literal[False] = False
    exchange_mutation_count: Literal[0] = 0
    created_at: str
    updated_at: str


class ProductCatalogProductItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(pattern=_PRODUCT_ID)
    product_type: Literal["SPOT", "FUTURE"]
    base_currency: str
    quote_currency: str
    base_increment: str
    quote_increment: str
    price_increment: str
    base_min_size: str
    base_max_size: str
    quote_min_size: str
    quote_max_size: str
    display_name: str
    exchange_status: Literal["ONLINE", "OFFLINE", "DELISTED", "UNKNOWN"]
    exchange_disabled: bool
    cancel_only: bool
    limit_only: bool
    post_only: bool
    view_only: bool
    lifecycle: ProductCatalogLifecycle
    change_type: Literal[
        "ADDED",
        "CHANGED",
        "REMOVED",
        "UNCHANGED",
        "LIFECYCLE_CHANGED",
        "ROLLBACK_RESTORED",
    ]
    allowed_actions: list[
        Literal["ENABLE", "DISABLE", "RETIRE"]
    ] = Field(default_factory=list)


class ProductCatalogEventItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(pattern=_UUID)
    event_type: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,95}$")
    revision_id: str | None = Field(default=None, pattern=_UUID)
    cycle_id: str | None = Field(default=None, pattern=_UUID)
    product_id: str | None = Field(default=None, pattern=_PRODUCT_ID)
    correlation_id: str = Field(pattern=_EVIDENCE_ID)
    evidence: dict[str, Any] = Field(default_factory=dict)
    recorded_at: str


class ProductCatalogCycleItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: str = Field(pattern=_UUID)
    cycle_number: int = Field(ge=1, le=10)
    state: Literal["CLAIMED", "READING", "PROPOSED", "FAILED", "UNKNOWN"]
    read_state: Literal[
        "NOT_STARTED",
        "IN_PROGRESS",
        "RETURNED",
        "RETURNED_INCOMPLETE",
        "NOT_RETURNED",
        "UNKNOWN_AFTER_PAGE_CLAIM",
    ]
    expected_active_revision_id: str | None = Field(
        default=None,
        pattern=_UUID,
    )
    proposed_revision_id: str | None = Field(
        default=None,
        pattern=_UUID,
    )
    logical_read_count: Literal[1] = 1
    page_count: int = Field(ge=0, le=100)
    diagnostic_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,95}$")
    correlation_id: str = Field(pattern=_EVIDENCE_ID)
    events: list[ProductCatalogEventItem] = Field(default_factory=list)
    created_at: str
    updated_at: str


class ProductCatalogListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["operator_product_catalog"] = "operator_product_catalog"
    status: Literal["ready"] = "ready"
    items: list[ProductCatalogRevisionItem]
    total_count: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    next_offset: int | None = Field(default=None, ge=0)
    active_revision_id: str | None = Field(default=None, pattern=_UUID)
    active_revision: ProductCatalogRevisionItem | None = None
    cycles: list[ProductCatalogCycleItem] = Field(default_factory=list)
    events: list[ProductCatalogEventItem] = Field(default_factory=list)
    event_total_count: int = Field(ge=0)
    event_returned_count: int = Field(ge=0)
    event_limit: int = Field(ge=1, le=100)
    event_offset: int = Field(ge=0)
    event_next_offset: int | None = Field(default=None, ge=0)
    goal_budget: ProductCatalogGoalBudget
    allowed_actions: list[Literal["REFRESH"]] = Field(default_factory=list)
    live_coinbase_read_ran: Literal[False] = False
    live_coinbase_orders_ran: Literal[False] = False
    live_coinbase_execution: Literal["not_run"] = "not_run"
    notional_usdc: Literal["0"] = "0"


class ProductCatalogRevisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal[
        "operator_product_catalog_revision"
    ] = "operator_product_catalog_revision"
    status: Literal["ready"] = "ready"
    revision: ProductCatalogRevisionItem
    products: list[ProductCatalogProductItem]
    events: list[ProductCatalogEventItem]
    goal_budget: ProductCatalogGoalBudget
    live_coinbase_read_ran: Literal[False] = False
    live_coinbase_orders_ran: Literal[False] = False
    live_coinbase_execution: Literal["not_run"] = "not_run"
    notional_usdc: Literal["0"] = "0"


class ProductCatalogMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal[
        "operator_product_catalog_mutation"
    ] = "operator_product_catalog_mutation"
    status: Literal["accepted", "replayed", "rejected", "conflict"]
    message: str = Field(pattern=r"^[a-z][a-z0-9_]{0,95}$")
    service_method: Literal[
        "refresh_catalog",
        "approve_revision",
        "change_product_lifecycle",
        "rollback_revision",
    ]
    required_permission: Literal["config:update"] = "config:update"
    revision: ProductCatalogRevisionItem | None = None
    correlation_id: str = Field(pattern=_EVIDENCE_ID)
    idempotency_key: str = Field(pattern=_EVIDENCE_ID)
    coinbase_read_state: Literal[
        "NOT_RUN",
        "RETURNED",
        "NOT_RETURNED",
        "RETURNED_INCOMPLETE",
        "UNKNOWN_AFTER_PAGE_CLAIM",
    ] = "NOT_RUN"
    live_coinbase_read_ran: bool | None = False
    local_state_mutated: bool = True
    trading_authority_granted: Literal[False] = False
    portfolio_scope_expanded: Literal[False] = False
    exchange_mutation_count: Literal[0] = 0
    live_coinbase_orders_ran: Literal[False] = False
    live_coinbase_execution: Literal["not_run"] = "not_run"
    notional_usdc: Literal["0"] = "0"


class OperatorProductCatalogService:
    def __init__(
        self,
        *,
        repository: OperatorProductCatalogRepository,
        rest_client: Any,
        rest_client_available: bool,
    ) -> None:
        self.repository = repository
        self.rest_client = rest_client
        self.rest_client_available = rest_client_available

    def list_catalog(
        self,
        *,
        limit: int,
        offset: int,
        event_limit: int,
        event_offset: int,
    ) -> dict[str, Any]:
        records, total = self.repository.list_revisions(
            limit=limit,
            offset=offset,
        )
        budget = self.repository.get_goal_budget()
        active_revision_id = self.repository.get_active_revision_id()
        active_revision = (
            self._revision_item(
                self.repository.get_revision(active_revision_id)
            )
            if active_revision_id is not None
            else None
        )
        cycles = [
            self._cycle_item(record)
            for record in self.repository.list_cycles()
        ]
        event_records = self.repository.list_events(
            limit=event_limit,
            offset=event_offset,
        )
        event_total = self.repository.count_events()
        return ProductCatalogListResponse(
            items=[
                self._revision_item(record)
                for record in records
            ],
            total_count=total,
            returned_count=len(records),
            limit=limit,
            offset=offset,
            next_offset=(
                offset + len(records)
                if offset + len(records) < total
                else None
            ),
            active_revision_id=active_revision_id,
            active_revision=active_revision,
            cycles=cycles,
            events=[
                self._event_item(record)
                for record in event_records
            ],
            event_total_count=event_total,
            event_returned_count=len(event_records),
            event_limit=event_limit,
            event_offset=event_offset,
            event_next_offset=(
                event_offset + len(event_records)
                if event_offset + len(event_records) < event_total
                else None
            ),
            goal_budget=budget,
            allowed_actions=(
                ["REFRESH"] if int(budget["cycle_count"]) < 10 else []
            ),
        ).model_dump(mode="json")

    def get_revision(self, *, revision_id: str) -> dict[str, Any]:
        record = self.repository.get_revision(revision_id)
        active = bool(record.get("active"))
        products = [
            self._product_item(row, active=active)
            for row in self.repository.list_revision_products(revision_id)
        ]
        event_records = self.repository.list_events(
            revision_id=revision_id,
            limit=500,
        )
        if record.get("source_cycle_id"):
            event_records.extend(
                self.repository.list_events(
                    cycle_id=str(record["source_cycle_id"]),
                    limit=500,
                )
            )
        events_by_id = {
            str(row["event_id"]): row
            for row in event_records
        }
        events = [
            self._event_item(row)
            for row in sorted(
                events_by_id.values(),
                key=lambda item: str(item["recorded_at"]),
                reverse=True,
            )
        ]
        return ProductCatalogRevisionResponse(
            revision=self._revision_item(record),
            products=products,
            events=events,
            goal_budget=self.repository.get_goal_budget(),
        ).model_dump(mode="json")

    def refresh_catalog(
        self,
        *,
        body: ProductCatalogRefreshRequest,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> ProductCatalogMutationResponse:
        claim = self.repository.begin_refresh(
            expected_active_revision_id=body.expected_active_revision_id,
            actor_id=actor_id,
            operator_reason=body.operator_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            acknowledgement=(
                body.confirm_one_no_retry_product_catalog_read
            ),
        )
        if claim.get("command_replayed") and claim.get(
            "proposed_revision_id"
        ):
            revision = self.repository.get_revision(
                str(claim["proposed_revision_id"])
            )
            return self._mutation(
                status="replayed",
                message="product_catalog_refresh_replayed",
                service_method="refresh_catalog",
                revision=revision,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                coinbase_read_state="RETURNED",
                live_coinbase_read_ran=True,
                local_state_mutated=False,
            )
        if claim.get("command_replayed"):
            persisted_read_state = str(
                claim.get("read_state") or "NOT_STARTED"
            )
            read_state, ran = _replayed_read_state(
                persisted_read_state
            )
            in_progress = persisted_read_state in {
                "NOT_STARTED",
                "IN_PROGRESS",
            }
            return self._mutation(
                status="conflict" if in_progress else "replayed",
                message=(
                    "product_catalog_refresh_in_progress"
                    if in_progress
                    else "product_catalog_refresh_terminal_replayed"
                ),
                service_method="refresh_catalog",
                revision=None,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                coinbase_read_state=read_state,
                live_coinbase_read_ran=ran,
                local_state_mutated=False,
            )
        if not self.rest_client_available or self.rest_client is None:
            self.repository.fail_refresh(
                cycle_id=claim["cycle_id"],
                diagnostic_code="product_catalog_read_failed",
                read_state="NOT_RETURNED",
                actor_id=actor_id,
                correlation_id=correlation_id,
            )
            return self._mutation(
                status="rejected",
                message="product_catalog_reader_unavailable",
                service_method="refresh_catalog",
                revision=None,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                coinbase_read_state="NOT_RETURNED",
                live_coinbase_read_ran=False,
            )
        try:
            result = read_operator_product_catalog(
                self.rest_client,
                on_page_call=lambda ordinal, cursor_sha256: (
                    self.repository.record_page_call(
                        cycle_id=claim["cycle_id"],
                        page_ordinal=ordinal,
                        cursor_sha256=cursor_sha256,
                    )
                ),
                on_page_returned=lambda ordinal: (
                    self.repository.record_page_returned(
                        cycle_id=claim["cycle_id"],
                        page_ordinal=ordinal,
                    )
                ),
            )
            revision = self.repository.complete_refresh(
                cycle_id=claim["cycle_id"],
                read_result=result,
                actor_id=actor_id,
                correlation_id=correlation_id,
            )
        except OperatorProductCatalogError as exc:
            page_counts = self.repository.get_cycle_page_state_counts(
                claim["cycle_id"]
            )
            if page_counts["CLAIMED"] or page_counts["UNKNOWN"]:
                read_state = "UNKNOWN_AFTER_PAGE_CLAIM"
                ran: bool | None = None
            elif page_counts["RETURNED"]:
                read_state = "RETURNED_INCOMPLETE"
                ran = True
            else:
                read_state = "NOT_RETURNED"
                ran = False
            self.repository.fail_refresh(
                cycle_id=claim["cycle_id"],
                diagnostic_code=_safe_code(exc.code),
                read_state=read_state,
                actor_id=actor_id,
                correlation_id=correlation_id,
            )
            return self._mutation(
                status="rejected",
                message=_safe_code(exc.code),
                service_method="refresh_catalog",
                revision=None,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                coinbase_read_state=read_state,
                live_coinbase_read_ran=ran,
            )
        return self._mutation(
            status="accepted",
            message="product_catalog_refresh_proposed",
            service_method="refresh_catalog",
            revision=revision,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            coinbase_read_state="RETURNED",
            live_coinbase_read_ran=True,
        )

    def approve_revision(
        self,
        *,
        revision_id: str,
        body: ProductCatalogApproveRequest,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> ProductCatalogMutationResponse:
        try:
            record = self.repository.approve_revision(
                revision_id=revision_id,
                expected_revision=body.expected_revision,
                snapshot_sha256=body.snapshot_sha256,
                actor_id=actor_id,
                operator_reason=body.operator_reason,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                acknowledgement=body.confirm_catalog_approval,
            )
        except OperatorProductCatalogError as exc:
            self.repository.record_local_command_rejection(
                operation="APPROVE",
                command_fields={
                    "revision_id": revision_id,
                    "expected_revision": body.expected_revision,
                    "snapshot_sha256": body.snapshot_sha256,
                },
                actor_id=actor_id,
                operator_reason=body.operator_reason,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                acknowledgement=body.confirm_catalog_approval,
                diagnostic_code=_safe_code(exc.code),
            )
            raise
        return self._mutation(
            status=(
                "replayed"
                if record.get("command_replayed")
                else "accepted"
            ),
            message=(
                "product_catalog_revision_approval_replayed"
                if record.get("command_replayed")
                else "product_catalog_revision_approved"
            ),
            service_method="approve_revision",
            revision=record,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            local_state_mutated=not bool(
                record.get("command_replayed")
            ),
        )

    def change_product_lifecycle(
        self,
        *,
        product_id: str,
        action: Literal["ENABLE", "DISABLE", "RETIRE"],
        body: ProductCatalogLifecycleRequest,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> ProductCatalogMutationResponse:
        try:
            record = self.repository.change_product_lifecycle(
                product_id=product_id,
                action=action,
                expected_active_revision_id=(
                    body.expected_active_revision_id
                ),
                expected_active_revision=body.expected_active_revision,
                actor_id=actor_id,
                operator_reason=body.operator_reason,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                acknowledgement=body.confirm_product_lifecycle_change,
            )
        except OperatorProductCatalogError as exc:
            self.repository.record_local_command_rejection(
                operation=action,
                command_fields={
                    "product_id": product_id,
                    "expected_active_revision_id":
                        body.expected_active_revision_id,
                    "expected_active_revision":
                        body.expected_active_revision,
                },
                actor_id=actor_id,
                operator_reason=body.operator_reason,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                acknowledgement=body.confirm_product_lifecycle_change,
                diagnostic_code=_safe_code(exc.code),
            )
            raise
        return self._mutation(
            status=(
                "replayed"
                if record.get("command_replayed")
                else "accepted"
            ),
            message=(
                "product_catalog_lifecycle_change_replayed"
                if record.get("command_replayed")
                else f"product_catalog_product_{action.lower()}d"
            ),
            service_method="change_product_lifecycle",
            revision=record,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            local_state_mutated=not bool(
                record.get("command_replayed")
            ),
        )

    def rollback_revision(
        self,
        *,
        target_revision_id: str,
        body: ProductCatalogRollbackRequest,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> ProductCatalogMutationResponse:
        try:
            record = self.repository.rollback_revision(
                target_revision_id=target_revision_id,
                expected_active_revision_id=(
                    body.expected_active_revision_id
                ),
                expected_active_revision=body.expected_active_revision,
                target_snapshot_sha256=body.target_snapshot_sha256,
                actor_id=actor_id,
                operator_reason=body.operator_reason,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                acknowledgement=body.confirm_exact_catalog_rollback,
            )
        except OperatorProductCatalogError as exc:
            self.repository.record_local_command_rejection(
                operation="ROLLBACK",
                command_fields={
                    "target_revision_id": target_revision_id,
                    "expected_active_revision_id":
                        body.expected_active_revision_id,
                    "expected_active_revision":
                        body.expected_active_revision,
                    "target_snapshot_sha256":
                        body.target_snapshot_sha256,
                },
                actor_id=actor_id,
                operator_reason=body.operator_reason,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                acknowledgement=body.confirm_exact_catalog_rollback,
                diagnostic_code=_safe_code(exc.code),
            )
            raise
        return self._mutation(
            status=(
                "replayed"
                if record.get("command_replayed")
                else "accepted"
            ),
            message=(
                "product_catalog_rollback_replayed"
                if record.get("command_replayed")
                else "product_catalog_revision_rolled_back"
            ),
            service_method="rollback_revision",
            revision=record,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            local_state_mutated=not bool(
                record.get("command_replayed")
            ),
        )

    def _mutation(
        self,
        *,
        status: Literal["accepted", "replayed", "rejected", "conflict"],
        message: str,
        service_method: Literal[
            "refresh_catalog",
            "approve_revision",
            "change_product_lifecycle",
            "rollback_revision",
        ],
        revision: dict[str, Any] | None,
        correlation_id: str,
        idempotency_key: str,
        coinbase_read_state: Literal[
            "NOT_RUN",
            "RETURNED",
            "NOT_RETURNED",
            "RETURNED_INCOMPLETE",
            "UNKNOWN_AFTER_PAGE_CLAIM",
        ] = "NOT_RUN",
        live_coinbase_read_ran: bool | None = False,
        local_state_mutated: bool = True,
    ) -> ProductCatalogMutationResponse:
        return ProductCatalogMutationResponse(
            status=status,
            message=_safe_code(message),
            service_method=service_method,
            revision=(
                self._revision_item(revision)
                if revision is not None
                else None
            ),
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            coinbase_read_state=coinbase_read_state,
            live_coinbase_read_ran=live_coinbase_read_ran,
            local_state_mutated=local_state_mutated,
        )

    def _revision_item(
        self,
        record: dict[str, Any],
    ) -> ProductCatalogRevisionItem:
        active = bool(record.get("active"))
        allowed_actions: list[str] = []
        if record["state"] == "PROPOSED":
            allowed_actions.append("APPROVE")
        elif not active and record["state"] in {
            "APPROVED",
            "APPLIED",
            "ROLLED_BACK",
        } and self.repository.get_active_revision_id() is not None:
            allowed_actions.append("ROLLBACK")
        return ProductCatalogRevisionItem.model_validate(
            {
                key: (
                    _iso_text(record.get(key))
                    if key in {"created_at", "updated_at"}
                    else record.get(key)
                )
                for key in ProductCatalogRevisionItem.model_fields
                if key != "allowed_actions"
            }
            | {"allowed_actions": allowed_actions}
        )

    def _product_item(
        self,
        record: dict[str, Any],
        *,
        active: bool,
    ) -> ProductCatalogProductItem:
        lifecycle = ProductCatalogLifecycle(record["lifecycle"])
        actions: list[str] = []
        if active:
            if (
                lifecycle is not ProductCatalogLifecycle.RETIRED
                and not bool(record["exchange_disabled"])
                and record["exchange_status"] == "ONLINE"
                and lifecycle is not ProductCatalogLifecycle.ENABLED
            ):
                actions.append("ENABLE")
            if lifecycle not in {
                ProductCatalogLifecycle.DISABLED,
                ProductCatalogLifecycle.RETIRED,
            }:
                actions.append("DISABLE")
            if lifecycle is not ProductCatalogLifecycle.RETIRED:
                actions.append("RETIRE")
        return ProductCatalogProductItem.model_validate(
            {**record, "allowed_actions": actions}
        )

    def _cycle_item(
        self,
        record: dict[str, Any],
    ) -> ProductCatalogCycleItem:
        cycle_id = str(record["cycle_id"])
        return ProductCatalogCycleItem.model_validate(
            {
                key: (
                    _iso_text(record.get(key))
                    if key in {"created_at", "updated_at"}
                    else record.get(key)
                )
                for key in ProductCatalogCycleItem.model_fields
                if key != "events"
            }
            | {
                "events": [
                    self._event_item(event)
                    for event in self.repository.list_events(
                        cycle_id=cycle_id,
                        limit=100,
                    )
                ]
            }
        )

    def _event_item(
        self,
        record: dict[str, Any],
    ) -> ProductCatalogEventItem:
        event_type = str(record.get("event_type") or "")
        if event_type not in _EVENT_EVIDENCE_KEYS:
            event_type = "CATALOG_EVENT_WITHHELD"
        return ProductCatalogEventItem.model_validate(
            {
                key: (
                    event_type
                    if key == "event_type"
                    else _safe_event_evidence(
                        event_type,
                        record.get("evidence"),
                    )
                    if key == "evidence"
                    else _iso_text(record.get(key))
                    if key == "recorded_at"
                    else record.get(key)
                )
                for key in ProductCatalogEventItem.model_fields
            }
        )


def _safe_code(value: str) -> str:
    return (
        value
        if _SAFE_CODE.fullmatch(value)
        else "product_catalog_internal_failure"
    )


def _replayed_read_state(
    value: str,
) -> tuple[
    Literal[
        "NOT_RUN",
        "RETURNED",
        "NOT_RETURNED",
        "RETURNED_INCOMPLETE",
        "UNKNOWN_AFTER_PAGE_CLAIM",
    ],
    bool | None,
]:
    if value == "RETURNED":
        return "RETURNED", True
    if value == "RETURNED_INCOMPLETE":
        return "RETURNED_INCOMPLETE", True
    if value == "NOT_RETURNED":
        return "NOT_RETURNED", False
    if value in {"IN_PROGRESS", "UNKNOWN_AFTER_PAGE_CLAIM"}:
        return "UNKNOWN_AFTER_PAGE_CLAIM", None
    return "NOT_RUN", False


def _iso_text(value: Any) -> str:
    isoformat = getattr(value, "isoformat", None)
    return str(isoformat()) if callable(isoformat) else str(value)


def _safe_event_evidence(
    event_type: str,
    raw: Any,
) -> dict[str, int | str]:
    if not isinstance(raw, dict):
        return {}
    allowed_keys = _EVENT_EVIDENCE_KEYS.get(event_type, frozenset())
    safe: dict[str, int | str] = {}
    for key in allowed_keys:
        value = raw.get(key)
        if key in {
            "cycle_number",
            "product_count",
            "added_count",
            "changed_count",
            "removed_count",
            "page_count",
            "revision",
        }:
            if type(value) is int and 0 <= value <= 1_000_000:
                safe[key] = value
        elif key == "state" and value in {
            "FAILED",
            "UNKNOWN",
        }:
            safe[key] = value
        elif key == "read_state" and value in {
            "NOT_RETURNED",
            "RETURNED_INCOMPLETE",
            "UNKNOWN_AFTER_PAGE_CLAIM",
        }:
            safe[key] = value
        elif key == "diagnostic_code" and isinstance(value, str):
            safe[key] = _safe_code(value)
        elif key == "operation" and value in {
            "approve",
            "enable",
            "disable",
            "retire",
            "rollback",
        }:
            safe[key] = value
        elif key == "action" and value in {
            "ENABLE",
            "DISABLE",
            "RETIRE",
        }:
            safe[key] = value
        elif key == "lifecycle" and value in {
            "ENABLED",
            "DISABLED",
            "RETIRED",
        }:
            safe[key] = value
        elif (
            key == "target_revision_id"
            and isinstance(value, str)
            and _UUID_VALUE.fullmatch(value) is not None
        ):
            safe[key] = value
    return safe
