"""Durable coordinator for the Default-profile Futures Orders workspace."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Protocol

from .operator_futures_order_operations import (
    FuturesOrderCatalogReader,
    FuturesOrderCatalogResult,
)
from .operator_futures_order_operations_runtime import (
    AdminApiFuturesOrderOperationsExchangeExecutor,
)


@dataclass(frozen=True, slots=True)
class FuturesOrderOperationsRequestContext:
    actor_id: str
    roles: tuple[str, ...]
    expected_revision: int
    idempotency_key: str
    correlation_id: str
    audit_id: str
    operator_intent: str
    authorize_one_no_retry_cycle: bool
    acknowledge_cycle_is_goal_global_and_limited_to_ten: bool
    acknowledge_unknown_read_fails_closed: bool
    acknowledge_unknown_cancel_consumes_allowance: bool = False


@dataclass(frozen=True, slots=True)
class FuturesOrderOperationsGoalRecord:
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


class FuturesOrderOperationsRepository(Protocol):
    def read_goal(self) -> FuturesOrderOperationsGoalRecord: ...

    def read_cycle_result(
        self,
        *,
        correlation_id: str,
        actor_id: str,
    ) -> tuple[
        bool,
        bool,
        FuturesOrderOperationsGoalRecord | None,
    ]: ...

    def begin_cycle(
        self,
        *,
        context: FuturesOrderOperationsRequestContext,
        action: str,
        target_client_order_id: str | None,
    ) -> tuple[FuturesOrderOperationsGoalRecord, int | None, bool]: ...

    def claim_category(self, *, cycle_number: int, category: str) -> None: ...

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

    def finish_page(
        self, *, cycle_number: int, page_ordinal: int
    ) -> None: ...

    def finish_cycle(
        self,
        *,
        cycle_number: int,
        result: FuturesOrderCatalogResult,
        context: FuturesOrderOperationsRequestContext,
        action: str,
        target_client_order_id: str | None,
    ) -> FuturesOrderOperationsGoalRecord: ...

    def claim_cancel(
        self,
        *,
        context: FuturesOrderOperationsRequestContext,
        client_order_id: str,
        exchange_order_id_sha256: str,
    ) -> tuple[FuturesOrderOperationsGoalRecord, str]: ...

    def mark_cancel_exchange_invoked(self, *, claim_id: str) -> None: ...

    def release_cancel_before_exchange(
        self, *, claim_id: str
    ) -> FuturesOrderOperationsGoalRecord: ...

    def finish_cancel(
        self, *, claim_id: str, execution: Any
    ) -> FuturesOrderOperationsGoalRecord: ...

    def list_orders(
        self,
        *,
        product_id: str | None,
        order_status: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]: ...

    def get_order(self, client_order_id: str) -> dict[str, Any] | None: ...


class OperatorFuturesOrderOperationsService:
    """Coordinate explicit refresh, exact reconciliation, and one Cancel."""

    def __init__(
        self,
        *,
        repository: FuturesOrderOperationsRepository,
        catalog_reader: FuturesOrderCatalogReader,
        exchange_executor: AdminApiFuturesOrderOperationsExchangeExecutor,
        authoritative_fill_dispatcher: (
            Callable[[str], object] | None
        ) = None,
    ) -> None:
        self.repository = repository
        self.catalog_reader = catalog_reader
        self.exchange_executor = exchange_executor
        self.authoritative_fill_dispatcher = (
            authoritative_fill_dispatcher
        )

    def read_goal(self) -> FuturesOrderOperationsGoalRecord:
        return self.repository.read_goal()

    def read_cycle_result(
        self,
        *,
        correlation_id: str,
        actor_id: str,
    ) -> tuple[
        bool,
        bool,
        FuturesOrderOperationsGoalRecord | None,
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
        context: FuturesOrderOperationsRequestContext,
    ) -> FuturesOrderOperationsGoalRecord:
        record, _result = self._run_cycle(
            context=context,
            action="REFRESH_CATALOG",
            target_client_order_id=None,
        )
        return record

    def reconcile_exact(
        self,
        *,
        context: FuturesOrderOperationsRequestContext,
        client_order_id: str,
    ) -> FuturesOrderOperationsGoalRecord:
        exact_id = str(client_order_id or "").strip()
        if not exact_id:
            raise ValueError("operator_futures_order_identity_invalid")
        record, result = self._run_cycle(
            context=context,
            action="RECONCILE_EXACT",
            target_client_order_id=exact_id,
        )
        if (
            self.authoritative_fill_dispatcher is not None
            and result is not None
            and result.outcome == "SUCCEEDED"
            and record.last_outcome == "SUCCEEDED"
            and any(
                item.client_order_id == exact_id
                for item in result.orders
            )
        ):
            self.authoritative_fill_dispatcher(exact_id)
        return record

    def cancel_exact(
        self,
        *,
        context: FuturesOrderOperationsRequestContext,
        client_order_id: str,
    ) -> FuturesOrderOperationsGoalRecord:
        exact_id = str(client_order_id or "").strip()
        if not exact_id:
            raise ValueError("operator_futures_order_identity_invalid")
        if not context.acknowledge_unknown_cancel_consumes_allowance:
            raise ValueError(
                "operator_futures_order_cancel_confirmation_required"
            )
        record, result = self._run_cycle(
            context=context,
            action="CANCEL_EXACT",
            target_client_order_id=exact_id,
        )
        if (
            result is None
            or result.outcome != "SUCCEEDED"
            or result.credential_can_trade is not True
            or record.last_outcome != "SUCCEEDED"
        ):
            return record
        observation = next(
            (
                item
                for item in result.orders
                if item.client_order_id == exact_id
            ),
            None,
        )
        exchange_order_id = result.private_exchange_order_ids.get(exact_id)
        if (
            observation is None
            or not observation.cancel_eligible
            or not exchange_order_id
        ):
            return record
        claimed, claim_id = self.repository.claim_cancel(
            context=context,
            client_order_id=exact_id,
            exchange_order_id_sha256=(
                observation.exchange_order_id_sha256
            ),
        )
        if claimed.cancel_outcome != "CLAIMED":
            return claimed
        execution = self.exchange_executor.cancel(
            client_order_id=exact_id,
            private_exchange_order_id=exchange_order_id,
            expected_exchange_order_id_sha256=(
                observation.exchange_order_id_sha256
            ),
            before_call=lambda: (
                self.repository.mark_cancel_exchange_invoked(
                    claim_id=claim_id
                )
            ),
        )
        if not execution.call_boundary_entered:
            return self.repository.release_cancel_before_exchange(
                claim_id=claim_id
            )
        return self.repository.finish_cancel(
            claim_id=claim_id,
            execution=execution,
        )

    def _run_cycle(
        self,
        *,
        context: FuturesOrderOperationsRequestContext,
        action: str,
        target_client_order_id: str | None,
    ) -> tuple[
        FuturesOrderOperationsGoalRecord,
        FuturesOrderCatalogResult | None,
    ]:
        if (
            not context.authorize_one_no_retry_cycle
            or not context.acknowledge_cycle_is_goal_global_and_limited_to_ten
            or not context.acknowledge_unknown_read_fails_closed
        ):
            raise ValueError(
                "operator_futures_orders_refresh_confirmation_required"
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
        target_product_id = (
            str(target_projection.get("product_id") or "").strip() or None
            if target_projection is not None
            else None
        )
        target_created_at = (
            str(target_projection.get("created_at") or "").strip() or None
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
            before_page=lambda ordinal, cursor_sha256: (
                self._claim_and_enter_page(
                    cycle_number=cycle_number,
                    page_ordinal=ordinal,
                    cursor_sha256=cursor_sha256,
                )
            ),
            after_page=lambda ordinal: self.repository.finish_page(
                cycle_number=cycle_number,
                page_ordinal=ordinal,
            ),
            exact_scope_required=(target_client_order_id is not None),
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

    def _claim_and_enter_page(
        self,
        *,
        cycle_number: int,
        page_ordinal: int,
        cursor_sha256: str | None,
    ) -> None:
        self.repository.claim_page(
            cycle_number=cycle_number,
            page_ordinal=page_ordinal,
            cursor_sha256=cursor_sha256,
        )
        self.repository.mark_page_invoked(
            cycle_number=cycle_number,
            page_ordinal=page_ordinal,
        )


__all__ = [
    "FuturesOrderOperationsGoalRecord",
    "FuturesOrderOperationsRequestContext",
    "OperatorFuturesOrderOperationsService",
]
