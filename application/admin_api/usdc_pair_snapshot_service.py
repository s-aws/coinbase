"""Backend-owned M58 USDC pair snapshot dry-run service."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from enum import Enum
from typing import Any
from uuid import uuid4

from configuration import local_products_from_metadata
from core.enums import OrderSide, OrderType, ProductType, TimeInForce

from .models import (
    UsdcPairSnapshotOrderPlanItem,
    UsdcPairSnapshotOrderPlanProofRefreshRequest,
    UsdcPairSnapshotOrderPlanRequest,
    UsdcPairSnapshotOrderPlanRowItem,
    UsdcPairSnapshotRunItem,
    UsdcPairSnapshotRunRequest,
    UsdcPairSnapshotRowItem,
)
from .usdc_pair_snapshot import (
    FileUsdcPairSnapshotOrderPlanStore,
    FileUsdcPairSnapshotRunStore,
    UsdcPairSnapshotOrderPlanRecord,
    UsdcPairSnapshotRunRecord,
)


QUOTE_CURRENCY = "USDC"
DISQUALIFYING_PRODUCT_FLAGS = (
    "trading_disabled",
    "is_disabled",
    "cancel_only",
    "view_only",
    "auction_mode",
)
USDC_PAIR_ORDER_PLAN_PROOF_CHAIN_BLOCKERS = (
    "approval_snapshot_missing",
    "admission_audit_missing",
    "cap_guard_decision_missing",
    "reconciliation_plan_missing",
    "live_service_decision_missing",
)


class UsdcPairSnapshotError(ValueError):
    """Raised when a dry-run snapshot request cannot be recorded."""


ProductProvider = Callable[[], Iterable[Mapping[str, Any]]]
PriceProvider = Callable[[Mapping[str, Any]], Mapping[str, Any] | None]
OrderPlanProofChainRecorder = Callable[
    [UsdcPairSnapshotOrderPlanRowItem, Mapping[str, Any]],
    Mapping[str, Any] | None,
]
OrderPlanProofChainRefresher = Callable[
    [UsdcPairSnapshotOrderPlanRecord, UsdcPairSnapshotOrderPlanRowItem],
    Mapping[str, Any] | None,
]


class AdminApiUsdcPairSnapshotService:
    """Service boundary for backend-owned M58 dry-run snapshot records."""

    def __init__(
        self,
        *,
        product_provider: ProductProvider | None = None,
        price_provider: PriceProvider | None = None,
    ) -> None:
        self._product_provider = product_provider or _default_product_provider
        self._price_provider = price_provider or _default_price_provider

    def record_snapshot_run(
        self,
        *,
        store: FileUsdcPairSnapshotRunStore,
        body: UsdcPairSnapshotRunRequest,
        actor_id: str,
        operator_intent: str,
        idempotency_key: str,
        payload_hash: str,
        audit_id: str,
        now: datetime | None = None,
    ) -> UsdcPairSnapshotRunItem:
        recorded_at = _normalize_now(now).isoformat()
        requested_notional = _decimal(body.max_notional_per_product_usdc)
        if not body.dry_run:
            raise UsdcPairSnapshotError(
                "USDC pair snapshot automation currently accepts dry_run=true only."
            )
        if requested_notional <= 0:
            raise UsdcPairSnapshotError(
                "max_notional_per_product_usdc must be greater than zero."
            )

        run_id = body.run_id or f"m58-usdc-snapshot-{uuid4()}"
        if store.find_by_run_id(run_id) is not None:
            raise UsdcPairSnapshotError("USDC pair snapshot run already exists.")

        products = _scoped_products(self._product_provider(), body.product_ids)
        rows = [
            self._snapshot_row(
                product=product,
                requested_notional=requested_notional,
                captured_at=recorded_at,
            )
            for product in products
        ]
        record = UsdcPairSnapshotRunRecord(
            run_id=run_id,
            recorded_at=recorded_at,
            side=body.side.value,
            max_notional_per_product_usdc=_format_decimal(requested_notional) or "0",
            product_ids=[_product_id(product) for product in products],
            account_id=body.account_id,
            portfolio_id=body.portfolio_id,
            dry_run=body.dry_run,
            snapshot_rows=rows,
            actor_id=actor_id,
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            audit_id=audit_id,
            operator_notes=body.operator_notes,
        )
        store.append(record)
        return item_from_record(record)

    def record_order_plan(
        self,
        *,
        snapshot_store: FileUsdcPairSnapshotRunStore,
        order_plan_store: FileUsdcPairSnapshotOrderPlanStore,
        run_id: str,
        body: UsdcPairSnapshotOrderPlanRequest,
        actor_id: str,
        operator_intent: str,
        idempotency_key: str,
        payload_hash: str,
        audit_id: str,
        proof_chain_recorder: OrderPlanProofChainRecorder | None = None,
        now: datetime | None = None,
    ) -> UsdcPairSnapshotOrderPlanItem:
        planned_at = _normalize_now(now).isoformat()
        if not body.dry_run:
            raise UsdcPairSnapshotError(
                "USDC pair snapshot order planning currently accepts "
                "dry_run=true only."
            )
        max_total_notional = _decimal(body.max_total_notional_usdc)
        if max_total_notional <= 0:
            raise UsdcPairSnapshotError(
                "max_total_notional_usdc must be greater than zero."
            )

        snapshot_record = snapshot_store.find_by_run_id(run_id)
        if snapshot_record is None:
            raise UsdcPairSnapshotError("USDC pair snapshot run was not found.")
        if not snapshot_record.dry_run:
            raise UsdcPairSnapshotError(
                "USDC pair snapshot order planning requires a dry-run snapshot."
            )

        plan_id = body.plan_id or f"m58-usdc-order-plan-{uuid4()}"
        if order_plan_store.find_by_plan_id(plan_id) is not None:
            raise UsdcPairSnapshotError(
                "USDC pair snapshot order plan already exists."
            )

        time_in_force = TimeInForce(body.time_in_force)
        planned_total = Decimal("0")
        order_plan_rows: list[UsdcPairSnapshotOrderPlanRowItem] = []
        for snapshot_row in snapshot_record.snapshot_rows:
            order_plan_row, row_notional = _order_plan_row(
                snapshot_row=snapshot_row,
                snapshot_record=snapshot_record,
                plan_id=plan_id,
                idempotency_key=idempotency_key,
                time_in_force=time_in_force,
                max_total_notional=max_total_notional,
                planned_total=planned_total,
                proof_chain_recorder=proof_chain_recorder,
            )
            order_plan_rows.append(order_plan_row)
            planned_total += row_notional

        record = UsdcPairSnapshotOrderPlanRecord(
            plan_id=plan_id,
            snapshot_run_id=snapshot_record.run_id,
            planned_at=planned_at,
            side=snapshot_record.side,
            max_notional_per_product_usdc=(
                snapshot_record.max_notional_per_product_usdc
            ),
            max_total_notional_usdc=(
                _format_decimal(max_total_notional) or "0"
            ),
            planned_total_notional_usdc=_format_decimal(planned_total) or "0",
            product_ids=snapshot_record.product_ids,
            account_id=snapshot_record.account_id,
            portfolio_id=snapshot_record.portfolio_id,
            time_in_force=time_in_force.value,
            dry_run=body.dry_run,
            order_plan_rows=order_plan_rows,
            actor_id=actor_id,
            operator_intent=operator_intent,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            audit_id=audit_id,
            operator_notes=body.operator_notes,
        )
        order_plan_store.append(record)
        return order_plan_item_from_record(record)

    def refresh_order_plan_proof_chain(
        self,
        *,
        order_plan_store: FileUsdcPairSnapshotOrderPlanStore,
        plan_id: str,
        body: UsdcPairSnapshotOrderPlanProofRefreshRequest,
        audit_id: str,
        proof_chain_refresher: OrderPlanProofChainRefresher | None = None,
    ) -> UsdcPairSnapshotOrderPlanItem:
        if not body.dry_run:
            raise UsdcPairSnapshotError(
                "USDC pair snapshot proof refresh currently accepts "
                "dry_run=true only."
            )
        if body.manual_live_acknowledgement:
            raise UsdcPairSnapshotError(
                "USDC pair snapshot proof refresh cannot acknowledge live "
                "execution."
            )

        record = order_plan_store.find_by_plan_id(plan_id)
        if record is None:
            raise UsdcPairSnapshotError("USDC pair snapshot order plan was not found.")

        refreshed_rows: list[UsdcPairSnapshotOrderPlanRowItem] = []
        for row in record.order_plan_rows:
            if row.plan_status != "planned" or proof_chain_refresher is None:
                refreshed_rows.append(row)
                continue
            proof_chain_fields = proof_chain_refresher(record, row)
            if proof_chain_fields:
                refreshed_rows.append(
                    row.model_copy(update=dict(proof_chain_fields))
                )
            else:
                refreshed_rows.append(row)

        refreshed_record = record.model_copy(
            update={
                "order_plan_rows": refreshed_rows,
                "audit_id": audit_id,
                "operator_notes": body.operator_notes or record.operator_notes,
            }
        )
        order_plan_store.append(refreshed_record)
        return order_plan_item_from_record(refreshed_record)

    def _snapshot_row(
        self,
        *,
        product: Mapping[str, Any],
        requested_notional: Decimal,
        captured_at: str,
    ) -> UsdcPairSnapshotRowItem:
        product_id = _product_id(product)
        product_type = _text(_get_value(product, "product_type", "type")).upper()
        base_currency = _base_currency(product)
        quote_currency = _quote_currency(product)
        trading_status = _text(_get_value(product, "status"))
        price_increment = _positive_decimal_or_none(
            _get_value(product, "price_increment")
        )
        base_increment = _positive_decimal_or_none(
            _get_value(product, "base_increment")
        )
        quote_increment = _positive_decimal_or_none(
            _get_value(product, "quote_increment")
        )
        min_base_size = _positive_decimal_or_none(_get_value(product, "base_min_size"))
        min_quote_size = _positive_decimal_or_none(
            _get_value(product, "quote_min_size")
        )
        price_snapshot = self._price_provider(product) or _default_price_provider(
            product
        )
        observed_price = _positive_decimal_or_none(
            _get_value(price_snapshot or {}, "price", "observed_price")
        )
        price_source = _text(_get_value(price_snapshot or {}, "source", "price_source"))
        price_captured_at = _text(
            _get_value(price_snapshot or {}, "captured_at", "snapshot_captured_at")
        ) or captured_at

        skip_reason = _skip_reason(
            product_id=product_id,
            product_type=product_type,
            base_currency=base_currency,
            quote_currency=quote_currency,
            trading_status=trading_status,
            product=product,
            requested_notional=requested_notional,
            price_increment=price_increment,
            base_increment=base_increment,
            quote_increment=quote_increment,
            min_base_size=min_base_size,
            min_quote_size=min_quote_size,
            observed_price=observed_price,
        )
        return UsdcPairSnapshotRowItem(
            product_id=product_id or "unknown",
            base_currency=base_currency or None,
            quote_currency=quote_currency or None,
            product_type=product_type or None,
            trading_status=trading_status or None,
            price_increment=_format_decimal(price_increment),
            base_increment=_format_decimal(base_increment),
            quote_increment=_format_decimal(quote_increment),
            min_base_size=_format_decimal(min_base_size),
            min_quote_size=_format_decimal(min_quote_size),
            requested_notional_usdc=_format_decimal(requested_notional) or "0",
            observed_price=_format_decimal(observed_price),
            price_source=price_source or None,
            snapshot_captured_at=price_captured_at,
            eligibility_status="skipped" if skip_reason else "eligible",
            skip_reason=skip_reason,
        )


def item_from_record(record: UsdcPairSnapshotRunRecord) -> UsdcPairSnapshotRunItem:
    """Return the API read model for a stored snapshot run."""

    eligible_count = sum(
        1 for row in record.snapshot_rows if row.eligibility_status == "eligible"
    )
    skipped_count = len(record.snapshot_rows) - eligible_count
    return UsdcPairSnapshotRunItem(
        run_id=record.run_id,
        recorded_at=record.recorded_at,
        side=OrderSide(record.side),
        max_notional_per_product_usdc=record.max_notional_per_product_usdc,
        product_ids=record.product_ids,
        account_id=record.account_id,
        portfolio_id=record.portfolio_id,
        dry_run=record.dry_run,
        snapshot_row_count=len(record.snapshot_rows),
        eligible_count=eligible_count,
        skipped_count=skipped_count,
        snapshot_rows=record.snapshot_rows,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        payload_hash=record.payload_hash,
        audit_id=record.audit_id,
        operator_notes=record.operator_notes,
        detail=(
            "M58 USDC pair snapshot dry-run evidence is backend-owned and "
            "does not derive order payloads, allocate wallet balance, call "
            "Coinbase order endpoints, or grant browser execution authority."
        ),
    )


def order_plan_item_from_record(
    record: UsdcPairSnapshotOrderPlanRecord,
) -> UsdcPairSnapshotOrderPlanItem:
    """Return the API read model for a stored order-plan record."""

    planned_count = sum(
        1 for row in record.order_plan_rows if row.plan_status == "planned"
    )
    skipped_count = sum(
        1 for row in record.order_plan_rows if row.plan_status == "skipped"
    )
    rejected_count = sum(
        1 for row in record.order_plan_rows if row.plan_status == "rejected"
    )
    return UsdcPairSnapshotOrderPlanItem(
        plan_id=record.plan_id,
        snapshot_run_id=record.snapshot_run_id,
        planned_at=record.planned_at,
        side=OrderSide(record.side),
        max_notional_per_product_usdc=record.max_notional_per_product_usdc,
        max_total_notional_usdc=record.max_total_notional_usdc,
        planned_total_notional_usdc=record.planned_total_notional_usdc,
        product_ids=record.product_ids,
        account_id=record.account_id,
        portfolio_id=record.portfolio_id,
        time_in_force=TimeInForce(record.time_in_force),
        dry_run=record.dry_run,
        plan_row_count=len(record.order_plan_rows),
        planned_count=planned_count,
        skipped_count=skipped_count,
        rejected_count=rejected_count,
        order_plan_rows=record.order_plan_rows,
        actor_id=record.actor_id,
        operator_intent=record.operator_intent,
        idempotency_key=record.idempotency_key,
        payload_hash=record.payload_hash,
        audit_id=record.audit_id,
        operator_notes=record.operator_notes,
        detail=(
            "M58 USDC pair snapshot order-plan evidence is backend-owned and "
            "does not allocate wallet balance, call Coinbase order endpoints, "
            "or grant browser execution authority."
        ),
    )


def _order_plan_row(
    *,
    snapshot_row: UsdcPairSnapshotRowItem,
    snapshot_record: UsdcPairSnapshotRunRecord,
    plan_id: str,
    idempotency_key: str,
    time_in_force: TimeInForce,
    max_total_notional: Decimal,
    planned_total: Decimal,
    proof_chain_recorder: OrderPlanProofChainRecorder | None = None,
) -> tuple[UsdcPairSnapshotOrderPlanRowItem, Decimal]:
    base_fields = {
        "product_id": snapshot_row.product_id,
        "side": OrderSide(snapshot_record.side),
        "order_type": OrderType.LIMIT,
        "time_in_force": time_in_force,
        "requested_notional_usdc": snapshot_row.requested_notional_usdc,
        "max_notional_per_product_usdc": (
            snapshot_record.max_notional_per_product_usdc
        ),
        "snapshot_price": snapshot_row.observed_price,
        "price_source": snapshot_row.price_source,
        "price_increment": snapshot_row.price_increment,
        "base_increment": snapshot_row.base_increment,
        "quote_increment": snapshot_row.quote_increment,
        "min_base_size": snapshot_row.min_base_size,
        "min_quote_size": snapshot_row.min_quote_size,
        "snapshot_captured_at": snapshot_row.snapshot_captured_at,
        **_proof_chain_not_applicable_fields(),
    }
    if snapshot_row.eligibility_status != "eligible":
        reason = snapshot_row.skip_reason or snapshot_row.eligibility_status
        return (
            UsdcPairSnapshotOrderPlanRowItem(
                **base_fields,
                plan_status="skipped",
                skip_reason=f"snapshot_not_eligible:{reason}",
            ),
            Decimal("0"),
        )

    requested_notional = _decimal(snapshot_row.requested_notional_usdc)
    observed_price = _positive_decimal_or_none(snapshot_row.observed_price)
    price_increment = _positive_decimal_or_none(snapshot_row.price_increment)
    base_increment = _positive_decimal_or_none(snapshot_row.base_increment)
    quote_increment = _positive_decimal_or_none(snapshot_row.quote_increment)
    min_base_size = _positive_decimal_or_none(snapshot_row.min_base_size)
    min_quote_size = _positive_decimal_or_none(snapshot_row.min_quote_size)
    if not all(
        (
            observed_price,
            price_increment,
            base_increment,
            quote_increment,
            min_base_size,
            min_quote_size,
        )
    ):
        return (
            UsdcPairSnapshotOrderPlanRowItem(
                **base_fields,
                plan_status="rejected",
                reject_reason="missing_order_plan_inputs",
            ),
            Decimal("0"),
        )

    limit_price = _floor_to_increment(observed_price, price_increment)
    if limit_price is None or limit_price <= 0:
        return (
            UsdcPairSnapshotOrderPlanRowItem(
                **base_fields,
                plan_status="rejected",
                reject_reason="invalid_limit_price",
            ),
            Decimal("0"),
        )

    base_size = _floor_to_increment(requested_notional / limit_price, base_increment)
    if base_size is None or base_size <= 0 or base_size < min_base_size:
        return (
            UsdcPairSnapshotOrderPlanRowItem(
                **base_fields,
                plan_status="rejected",
                limit_price=_format_decimal(limit_price),
                reject_reason="below_min_base_size",
            ),
            Decimal("0"),
        )

    planned_notional = _floor_to_increment(base_size * limit_price, quote_increment)
    if (
        planned_notional is None
        or planned_notional <= 0
        or planned_notional < min_quote_size
        or planned_notional > requested_notional
    ):
        return (
            UsdcPairSnapshotOrderPlanRowItem(
                **base_fields,
                plan_status="rejected",
                limit_price=_format_decimal(limit_price),
                base_size=_format_decimal(base_size),
                reject_reason="below_min_quote_size",
            ),
            Decimal("0"),
        )

    if planned_total + planned_notional > max_total_notional:
        return (
            UsdcPairSnapshotOrderPlanRowItem(
                **base_fields,
                plan_status="skipped",
                skip_reason="run_total_cap_exceeded",
            ),
            Decimal("0"),
        )

    planned_row = UsdcPairSnapshotOrderPlanRowItem(
        **{
            **base_fields,
            **_proof_chain_blocked_fields(),
        },
        plan_status="planned",
        client_order_id=f"{plan_id}-{snapshot_row.product_id}",
        idempotency_key=f"{idempotency_key}:{snapshot_row.product_id}",
        limit_price=_format_decimal(limit_price),
        base_size=_format_decimal(base_size),
        quote_size=_format_decimal(planned_notional),
        planned_notional_usdc=_format_decimal(planned_notional) or "0",
    )
    if proof_chain_recorder is not None:
        proof_chain_fields = proof_chain_recorder(
            planned_row,
            {
                "automation_run_id": snapshot_record.run_id,
                "order_plan_id": plan_id,
                "product_id": snapshot_row.product_id,
                "account_id": snapshot_record.account_id,
                "portfolio_id": snapshot_record.portfolio_id,
                "requested_notional_usdc": snapshot_row.requested_notional_usdc,
                "planned_notional_usdc": _format_decimal(planned_notional) or "0",
                "max_notional_per_product_usdc": (
                    snapshot_record.max_notional_per_product_usdc
                ),
                "max_total_notional_usdc": _format_decimal(max_total_notional) or "0",
                "snapshot_price": snapshot_row.observed_price,
                "limit_price": _format_decimal(limit_price),
                "price_source": snapshot_row.price_source,
                "snapshot_captured_at": snapshot_row.snapshot_captured_at,
            },
        )
        if proof_chain_fields:
            planned_row = planned_row.model_copy(update=dict(proof_chain_fields))
    return planned_row, planned_notional


def _proof_chain_not_applicable_fields() -> dict[str, Any]:
    return {
        "proof_chain_status": "not_applicable",
        "proof_chain_blockers": [],
        "approval_request_required": False,
        "approval_request_id": None,
        "approval_snapshot_required": False,
        "approval_snapshot_id": None,
        "admission_audit_required": False,
        "admission_audit_id": None,
        "cap_guard_decision_required": False,
        "cap_guard_decision_id": None,
        "reconciliation_plan_required": False,
        "reconciliation_plan_id": None,
        "live_service_decision_required": False,
        "live_service_decision_id": None,
    }


def _proof_chain_blocked_fields() -> dict[str, Any]:
    return {
        "proof_chain_status": "blocked",
        "proof_chain_blockers": list(USDC_PAIR_ORDER_PLAN_PROOF_CHAIN_BLOCKERS),
        "approval_request_required": True,
        "approval_request_id": None,
        "approval_snapshot_required": True,
        "approval_snapshot_id": None,
        "admission_audit_required": True,
        "admission_audit_id": None,
        "cap_guard_decision_required": True,
        "cap_guard_decision_id": None,
        "reconciliation_plan_required": True,
        "reconciliation_plan_id": None,
        "live_service_decision_required": True,
        "live_service_decision_id": None,
    }


def _default_product_provider() -> Iterable[Mapping[str, Any]]:
    return local_products_from_metadata().values()


def _default_price_provider(product: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for field in ("price", "mid_price", "mid_market_price", "mark_price"):
        price = _get_value(product, field)
        if _positive_decimal_or_none(price) is not None:
            return {
                "price": price,
                "source": f"product_metadata.{field}",
            }
    best_bid = _positive_decimal_or_none(_get_value(product, "best_bid"))
    best_ask = _positive_decimal_or_none(_get_value(product, "best_ask"))
    if best_bid is not None and best_ask is not None:
        return {
            "price": _format_decimal((best_bid + best_ask) / Decimal("2")),
            "source": "product_metadata.best_bid_best_ask_midpoint",
        }
    return None


def _scoped_products(
    products: Iterable[Mapping[str, Any]],
    product_ids: Iterable[str] | None,
) -> list[Mapping[str, Any]]:
    product_by_id = {
        _product_id(product).upper(): dict(product)
        for product in products
        if _product_id(product)
    }
    if product_ids:
        scoped: list[Mapping[str, Any]] = []
        for product_id in product_ids:
            normalized_id = _text(product_id).upper()
            if not normalized_id:
                continue
            scoped.append(
                product_by_id.get(normalized_id)
                or {"product_id": normalized_id, "missing_product_metadata": True}
            )
        return scoped
    return [product_by_id[key] for key in sorted(product_by_id)]


def _skip_reason(
    *,
    product_id: str,
    product_type: str,
    base_currency: str,
    quote_currency: str,
    trading_status: str,
    product: Mapping[str, Any],
    requested_notional: Decimal,
    price_increment: Decimal | None,
    base_increment: Decimal | None,
    quote_increment: Decimal | None,
    min_base_size: Decimal | None,
    min_quote_size: Decimal | None,
    observed_price: Decimal | None,
) -> str | None:
    if not product_id or _truthy(_get_value(product, "missing_product_metadata")):
        return "missing_product_metadata"
    if product_type != ProductType.SPOT.value:
        return "non_spot_product"
    if quote_currency != QUOTE_CURRENCY:
        return "non_usdc_quote"
    if not base_currency or base_currency == QUOTE_CURRENCY:
        return "invalid_base_currency"
    for flag in DISQUALIFYING_PRODUCT_FLAGS:
        if _truthy(_get_value(product, flag)):
            return flag
    if trading_status and trading_status.lower() not in {"online", "open"}:
        return "not_trading"
    if not all((price_increment, base_increment, quote_increment)):
        return "missing_increment"
    if not all((min_base_size, min_quote_size)):
        return "missing_min_size"
    if requested_notional < min_quote_size:
        return "below_min_quote_size"
    if observed_price is None:
        return "missing_price"
    return None


def _get_value(source: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(source, Mapping) and name in source:
            return source[name]
        if hasattr(source, name):
            return getattr(source, name)
    return default


def _product_id(product: Mapping[str, Any]) -> str:
    return _text(_get_value(product, "product_id", "id"))


def _base_currency(product: Mapping[str, Any]) -> str:
    base = _text(_get_value(product, "base_currency_id", "base_currency"))
    if base:
        return base.upper()
    product_id = _product_id(product)
    if "-" in product_id:
        return product_id.rsplit("-", 1)[0].upper()
    return ""


def _quote_currency(product: Mapping[str, Any]) -> str:
    quote = _text(_get_value(product, "quote_currency_id", "quote_currency"))
    if quote:
        return quote.upper()
    product_id = _product_id(product)
    if "-" in product_id:
        return product_id.rsplit("-", 1)[1].upper()
    return ""


def _text(value: Any) -> str:
    value = _enum_value(value)
    if value is None:
        return ""
    return str(value).strip()


def _enum_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _decimal(value: Any) -> Decimal:
    value = _enum_value(value)
    if isinstance(value, Mapping) and "value" in value:
        value = value.get("value")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise UsdcPairSnapshotError(f"Invalid decimal value: {value!r}") from exc


def _positive_decimal_or_none(value: Any) -> Decimal | None:
    try:
        parsed = _decimal(value)
    except UsdcPairSnapshotError:
        return None
    return parsed if parsed > 0 else None


def _floor_to_increment(value: Decimal, increment: Decimal) -> Decimal | None:
    if increment <= 0:
        return None
    units = (value / increment).to_integral_value(rounding=ROUND_FLOOR)
    return units * increment


def _format_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float, Decimal)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _normalize_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)
