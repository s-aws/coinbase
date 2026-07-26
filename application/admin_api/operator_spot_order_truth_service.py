"""Durable coordinator for the approved-Test Spot Orders workspace."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Callable, Protocol

from .operator_spot_order_truth import SpotOrderCatalogReader, SpotOrderCatalogResult


_CANONICAL_CLIENT_ORDER_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$"
)


def _exact_client_order_id(value: str) -> str:
    exact = str(value or "").strip()
    if _CANONICAL_CLIENT_ORDER_ID_RE.fullmatch(exact) is None:
        raise ValueError("operator_spot_order_truth_identity_invalid")
    return exact


def _exact_scope_created_at(value: Any) -> str | None:
    if isinstance(value, datetime):
        parsed = value
        if parsed.tzinfo is None:
            # ``order_parent.created_at`` is a PostgreSQL TIMESTAMP whose
            # established storage convention is UTC.
            parsed = parsed.replace(tzinfo=timezone.utc)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
    else:
        return None
    return (
        parsed.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


@dataclass(frozen=True, slots=True)
class SpotOrderTruthRequestContext:
    actor_id: str
    roles: tuple[str, ...]
    expected_revision: int
    idempotency_key: str
    correlation_id: str
    audit_id: str
    operator_intent: str
    authorize_one_no_retry_cycle: bool
    acknowledge_cycle_is_goal_global_and_limited_to_one: bool
    acknowledge_unknown_read_fails_closed: bool
    acknowledge_unknown_cancel_consumes_allowance: bool = False


@dataclass(frozen=True, slots=True)
class SpotOrderTruthGoalRecord:
    goal_id: str
    revision: int
    cycles_used: int
    active_cycle_number: int | None
    last_action: str | None
    last_target_client_order_id: str | None
    last_outcome: str
    diagnostic_code: str
    category_attempts: dict[str, int]
    page_count: int
    order_count: int
    portfolio_id_sha256: str | None
    evidence_sha256: str | None
    cancel_outcome: str
    cancel_exchange_invoked: bool | None
    cancel_target_client_order_id: str | None
    cancel_exchange_order_id_sha256: str | None
    correlation_id: str | None
    audit_id: str | None
    refreshed_at: str | None
    updated_at: str | None


class SpotOrderTruthRepository(Protocol):
    def read_goal(self) -> SpotOrderTruthGoalRecord: ...

    def read_cycle_result(
        self,
        *,
        correlation_id: str,
        actor_id: str,
    ) -> tuple[
        bool,
        bool,
        SpotOrderTruthGoalRecord | None,
    ]: ...

    def begin_cycle(
        self,
        *,
        context: SpotOrderTruthRequestContext,
        action: str,
        target_client_order_id: str | None,
    ) -> tuple[SpotOrderTruthGoalRecord, int | None, bool]: ...

    def claim_category(self, *, cycle_number: int, category: str) -> None: ...

    def mark_category_invoked(
        self, *, cycle_number: int, category: str
    ) -> None: ...

    def finish_category(
        self, *, cycle_number: int, category: str, outcome: str
    ) -> None: ...

    def claim_page(
        self,
        *,
        cycle_number: int,
        page_ordinal: int,
        cursor_sha256: str | None,
    ) -> None: ...

    def mark_page_invoked(
        self, *, cycle_number: int, page_ordinal: int
    ) -> None: ...

    def mark_catalog_page_invoked(
        self, *, cycle_number: int, page_ordinal: int
    ) -> None: ...

    def finish_page(
        self, *, cycle_number: int, page_ordinal: int
    ) -> None: ...

    def fail_page(
        self, *, cycle_number: int, page_ordinal: int
    ) -> None: ...

    def finish_cycle(
        self,
        *,
        cycle_number: int,
        result: SpotOrderCatalogResult,
        context: SpotOrderTruthRequestContext,
        action: str,
        target_client_order_id: str | None,
    ) -> SpotOrderTruthGoalRecord: ...

    def claim_cancel(
        self,
        *,
        context: SpotOrderTruthRequestContext,
        client_order_id: str,
        exchange_order_id_sha256: str,
        payload_sha256: str | None = None,
        expected_evidence_sha256: str | None = None,
        expected_portfolio_id_sha256: str | None = None,
    ) -> tuple[SpotOrderTruthGoalRecord, str, bool]: ...

    def mark_cancel_exchange_invoked(self, *, claim_id: str) -> None: ...

    def release_cancel_before_exchange(
        self, *, claim_id: str
    ) -> SpotOrderTruthGoalRecord: ...

    def restore_cancel_before_sdk(
        self, *, claim_id: str
    ) -> SpotOrderTruthGoalRecord: ...

    def finish_cancel(
        self, *, claim_id: str, execution: Any
    ) -> SpotOrderTruthGoalRecord: ...

    def list_orders(
        self,
        *,
        product_id: str | None,
        order_status: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]: ...

    def get_order(self, client_order_id: str) -> dict[str, Any] | None: ...


class OperatorSpotOrderTruthService:
    """Coordinate explicit refresh, exact reconciliation, and one Cancel."""

    def __init__(
        self,
        *,
        repository: SpotOrderTruthRepository,
        catalog_reader: SpotOrderCatalogReader,
        local_order_loader: (
            Callable[[str], dict[str, Any] | None] | None
        ) = None,
    ) -> None:
        self.repository = repository
        self.catalog_reader = catalog_reader
        self.local_order_loader = local_order_loader

    def read_goal(self) -> SpotOrderTruthGoalRecord:
        return self.repository.read_goal()

    def read_cycle_result(
        self,
        *,
        correlation_id: str,
        actor_id: str,
    ) -> tuple[
        bool,
        bool,
        SpotOrderTruthGoalRecord | None,
    ]:
        return self.repository.read_cycle_result(
            correlation_id=correlation_id,
            actor_id=actor_id,
        )

    def list_orders(
        self,
        *,
        product_id: str | None,
        order_status: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        return self.repository.list_orders(
            product_id=product_id,
            order_status=order_status,
            limit=limit,
            offset=offset,
        )

    def get_order(self, client_order_id: str) -> dict[str, Any] | None:
        return self.repository.get_order(client_order_id)

    def refresh_catalog(
        self,
        *,
        context: SpotOrderTruthRequestContext,
    ) -> SpotOrderTruthGoalRecord:
        record, _result = self._run_cycle(
            context=context,
            action="REFRESH_CATALOG",
            target_client_order_id=None,
        )
        return record

    def reconcile_exact(
        self,
        *,
        context: SpotOrderTruthRequestContext,
        client_order_id: str,
    ) -> SpotOrderTruthGoalRecord:
        exact_id = _exact_client_order_id(client_order_id)
        record, _result = self._run_cycle(
            context=context,
            action="RECONCILE_EXACT",
            target_client_order_id=exact_id,
        )
        return record

    def _run_cycle(
        self,
        *,
        context: SpotOrderTruthRequestContext,
        action: str,
        target_client_order_id: str | None,
    ) -> tuple[
        SpotOrderTruthGoalRecord,
        SpotOrderCatalogResult | None,
    ]:
        if (
            not context.authorize_one_no_retry_cycle
            or not context.acknowledge_cycle_is_goal_global_and_limited_to_one
            or not context.acknowledge_unknown_read_fails_closed
        ):
            raise ValueError(
                "operator_spot_order_truth_refresh_confirmation_required"
            )
        current, cycle_number, replayed = self.repository.begin_cycle(
            context=context,
            action=action,
            target_client_order_id=target_client_order_id,
        )
        if replayed or cycle_number is None:
            return current, None
        target_projection = (
            self.repository.get_order(target_client_order_id)
            if target_client_order_id
            else None
        )
        if (
            target_projection is None
            and target_client_order_id is not None
            and self.local_order_loader is not None
        ):
            target_projection = self.local_order_loader(
                target_client_order_id
            )
        target_product_id = (
            str(target_projection.get("product_id") or "").strip() or None
            if target_projection is not None
            else None
        )
        target_created_at = (
            _exact_scope_created_at(target_projection.get("created_at"))
            if target_projection is not None
            else None
        )
        result = self.catalog_reader.run(
            before_category=lambda category: (
                self.repository.claim_category(
                    cycle_number=cycle_number,
                    category=category,
                )
            ),
            on_category_call_boundary=lambda category: (
                self.repository.mark_category_invoked(
                    cycle_number=cycle_number,
                    category=category,
                )
            ),
            after_category=lambda category, outcome: (
                self.repository.finish_category(
                    cycle_number=cycle_number,
                    category=category,
                    outcome=outcome,
                )
            ),
            before_page=lambda ordinal, cursor_sha256: (
                self.repository.claim_page(
                    cycle_number=cycle_number,
                    page_ordinal=ordinal,
                    cursor_sha256=cursor_sha256,
                )
            ),
            on_page_call_boundary=lambda ordinal: (
                self.repository.mark_catalog_page_invoked(
                    cycle_number=cycle_number,
                    page_ordinal=ordinal,
                )
            ),
            after_page=lambda ordinal: self.repository.finish_page(
                cycle_number=cycle_number,
                page_ordinal=ordinal,
            ),
            page_failed=lambda ordinal: self.repository.fail_page(
                cycle_number=cycle_number,
                page_ordinal=ordinal,
            ),
            exact_scope_required=(target_client_order_id is not None),
            target_client_order_id=target_client_order_id,
            target_product_id=target_product_id,
            target_created_at=target_created_at,
        )
        record = self.repository.finish_cycle(
            cycle_number=cycle_number,
            result=result,
            context=context,
            action=action,
            target_client_order_id=target_client_order_id,
        )
        return record, result

__all__ = [
    "SpotOrderTruthGoalRecord",
    "SpotOrderTruthRequestContext",
    "OperatorSpotOrderTruthService",
]
