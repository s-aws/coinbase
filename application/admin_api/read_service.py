"""Read-only Admin API service wrappers."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from core.enums import (
    ActionConditionType,
    ActionGuardPhase,
    AdminApiActionClass,
    AdminApiAuthMode,
    AdminFuturesEvidenceSource,
    AdminFuturesEvidenceStatus,
    AdminFuturesPositionSide,
    AdminApiGateStatus,
    AdminApiHealthStatus,
    AdminMovementRepricingEvidenceType,
    AdminApiPermission,
    AdminApiRouteAvailability,
    AdminApiSessionStatus,
    AdminApiVerifierReadinessStatus,
    OrderSide,
    ProductCapability,
    ProductType,
    StealthOrderStatus,
    StealthMutationKind,
    AdminRiskEvidenceSource,
    AdminRiskEvidenceStatus,
)

from .approval import evaluate_live_execution_gate
from .auth import (
    build_oidc_jwt_readiness,
    check_oidc_jwks_reachability,
    configured_auth_mode,
)
from .models import (
    AdminApiActor,
    AdminBootstrapResponse,
    AdminCapabilityItem,
    AdminCapabilityRegistryResponse,
    AdminCsrfContractResponse,
    AdminFrontendFixturesResponse,
    AdminFuturesAccountReadResponse,
    AdminFuturesEvidenceItem,
    AdminFuturesPositionDetailResponse,
    AdminFuturesPositionListResponse,
    AdminFuturesPositionReadItem,
    AdminGateCheck,
    AdminGateReadResponse,
    AdminHealthResponse,
    AdminMovementRepricingDetailResponse,
    AdminMovementRepricingEvidenceItem,
    AdminMovementRepricingListResponse,
    AdminMutationClaimEvidence,
    AdminOidcJwtReadinessResponse,
    AdminOrderDetailResponse,
    AdminOrderListResponse,
    AdminOrderReadItem,
    AdminReplacementSlotEvidence,
    AdminProductCapabilityDecisionItem,
    AdminRiskEvidenceItem,
    AdminRiskPolicyReadResponse,
    AdminRiskPolicyRuleItem,
    AdminRiskRejectionCategoryItem,
    AdminSessionResponse,
    AdminStealthOrderDetailResponse,
    AdminStealthOrderListResponse,
    AdminStealthOrderReadItem,
)
from .route_inventory import ADMIN_API_ROUTE_INVENTORY


ROOT = Path(__file__).resolve().parents[2]
API_VERSION = "0.1.0"
SCHEMA_VERSION = "0.1.0"


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _csrf_required() -> bool:
    return os.environ.get(
        "COINBASE_ADMIN_API_CSRF_REQUIRED",
        "",
    ).strip().lower() in {"1", "true", "yes"}


def _surface_method_and_path(surface: str) -> tuple[str, str]:
    first, _, rest = surface.partition(" ")
    if rest.startswith("/"):
        return first, rest
    if "WebSocket" in surface:
        return "WEBSOCKET", surface
    return "UNKNOWN", surface


def _route_availability(surface: str, action_class: AdminApiActionClass) -> AdminApiRouteAvailability:
    if "WebSocket" in surface:
        return AdminApiRouteAvailability.CONTRACT_PENDING
    if surface.startswith("POST /api/v1") and action_class in {
        AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
    }:
        return AdminApiRouteAvailability.LIVE_DISABLED
    return AdminApiRouteAvailability.AVAILABLE


def _frontend_safe(surface: str, action_class: AdminApiActionClass) -> bool:
    if "WebSocket" in surface:
        return False
    return action_class == AdminApiActionClass.READ_ONLY or surface.startswith("POST /api/v1")


def _order_item_from_row(row: dict[str, Any]) -> AdminOrderReadItem:
    return AdminOrderReadItem(
        client_order_id=str(row.get("client_order_id") or ""),
        product_id=_string_or_none(row.get("product_id")),
        side=_string_or_none(row.get("side")),
        status=_string_or_none(row.get("status")),
        order_type=_string_or_none(row.get("order_type")),
        size=_string_or_none(row.get("size")),
        price=_string_or_none(row.get("price")),
        parent_client_order_id=_string_or_none(row.get("parent_order_id")),
        created_at=_string_or_none(row.get("created_at")),
        updated_at=_string_or_none(row.get("updated_at")),
        exchange_order_id=_string_or_none(
            row.get("exchange_order_id")
            or row.get("coinbase_order_id")
            or row.get("active_exchange_order_id")
        ),
        correlation_id=_string_or_none(row.get("correlation_id")),
        audit_id=_string_or_none(row.get("audit_id")),
    )


def _json_object_or_none(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return {"raw": value}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    return {"value": value}


def _json_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [
            dict(item) if isinstance(item, dict) else {"value": item}
            for item in value
        ]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return [{"raw": value}]
        if isinstance(parsed, list):
            return [
                dict(item) if isinstance(item, dict) else {"value": item}
                for item in parsed
            ]
        return [{"value": parsed}]
    return [{"value": value}]


def _stealth_item_from_row(row: dict[str, Any]) -> AdminStealthOrderReadItem:
    revealed_orders = _json_list(row.get("revealed_orders"))
    anchor_state = _json_object_or_none(row.get("anchor_repricing_state_json")) or {}
    active_placement_client_order_id = _string_or_none(
        anchor_state.get("active_placement_client_order_id")
        or anchor_state.get("active_placement_order_id")
        or anchor_state.get("active_placed_order_id")
    )
    active_exchange_order_id = _string_or_none(
        anchor_state.get("active_exchange_order_id")
    )
    return AdminStealthOrderReadItem(
        stealth_order_id=str(row.get("stealth_order_id") or ""),
        parent_stealth_order_id=_string_or_none(row.get("parent_order_id")),
        product_id=_string_or_none(row.get("product_id")),
        side=_string_or_none(row.get("side")),
        status=_string_or_none(row.get("status")),
        total_size=_string_or_none(row.get("total_size")),
        revealed_size=_string_or_none(row.get("revealed_size")),
        remaining_size=_string_or_none(row.get("remaining_size")),
        executed_size=_string_or_none(row.get("executed_size")),
        limit_price=_string_or_none(row.get("limit_price")),
        target_movement=_string_or_none(row.get("target_movement")),
        target_movement_type=_string_or_none(row.get("target_movement_type")),
        visibility_score=_string_or_none(row.get("visibility_score")),
        reveal_condition_type=_string_or_none(row.get("reveal_condition_type")),
        reveal_condition=_json_object_or_none(row.get("reveal_condition_json")),
        sizing_strategy=_json_object_or_none(row.get("sizing_strategy_json")),
        revealed_orders=revealed_orders,
        active_placement_client_order_id=active_placement_client_order_id,
        active_exchange_order_id=active_exchange_order_id,
        last_placement_at=_string_or_none(row.get("last_placement_at")),
        last_lifecycle_event=_string_or_none(row.get("last_lifecycle_event")),
        failure_reason=_string_or_none(row.get("failure_reason")),
        cancel_reentry_policy=_json_object_or_none(row.get("cancel_reentry_policy_json")),
        cancel_reentry_state=_json_object_or_none(row.get("cancel_reentry_state_json")),
        post_fill_retreat_policy=_json_object_or_none(row.get("post_fill_retreat_policy_json")),
        anchor_repricing_policy=_json_object_or_none(row.get("anchor_repricing_policy_json")),
        anchor_repricing_state=anchor_state,
        created_at=_string_or_none(row.get("created_at")),
        updated_at=_string_or_none(row.get("updated_at")),
    )


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes"}:
            return True
        if normalized in {"0", "false", "no"}:
            return False
    return bool(value)


def _list_or_empty(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _runtime_order_engine() -> Any | None:
    bridge = _runtime_bridge()
    return getattr(bridge, "order_engine", None) if bridge else None


def _runtime_orderbook() -> Any | None:
    engine = _runtime_order_engine()
    orderbook = getattr(engine, "orderbook", None) if engine else None
    if orderbook is not None:
        return orderbook
    try:
        import configuration

        orderbook_proxy = getattr(configuration, "ORDERBOOK", None)
        return getattr(orderbook_proxy, "_real", None)
    except Exception:
        return None


def _dashboard_state_snapshot() -> dict[str, Any]:
    try:
        import dashboard_server

        engine_state = getattr(dashboard_server, "engine_state", None)
        state_lock = getattr(dashboard_server, "state_lock", None)
        if not isinstance(engine_state, dict) or state_lock is None:
            return {}
        with state_lock:
            return deepcopy(engine_state)
    except Exception:
        return {}


def _orderbook_product_metadata(orderbook: Any | None) -> dict[str, dict[str, Any]]:
    products = getattr(orderbook, "products", None)
    if products is None:
        products = getattr(orderbook, "product", None)
    if not isinstance(products, dict) and not hasattr(products, "items"):
        return {}
    metadata: dict[str, dict[str, Any]] = {}
    try:
        for product_id, payload in products.items():
            metadata[str(product_id)] = _dict_or_empty(payload)
    except Exception:
        return {}
    return metadata


def _products_json_metadata() -> dict[str, dict[str, Any]]:
    products_path = ROOT / "products.json"
    try:
        payload = json.loads(products_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    items: dict[str, dict[str, Any]] = {}
    for product_id, product_payload in metadata.items():
        item = _dict_or_empty(product_payload)
        if "product_type" not in item and "type" in item:
            item["product_type"] = item.get("type")
        item.setdefault("product_id", product_id)
        items[str(product_id)] = item
    return items


def _normalize_admin_product_type(
    product_id: str,
    product_metadata: dict[str, Any] | None,
) -> str:
    try:
        from calculation.resolver import normalize_product_type

        return normalize_product_type(
            {
                "product_id": product_id,
                "product_type": _dict_or_empty(product_metadata).get("product_type")
                or _dict_or_empty(product_metadata).get("type"),
            },
            products={product_id: _dict_or_empty(product_metadata)}
            if product_metadata
            else None,
        )
    except Exception:
        return ProductType.FUTURE.value if product_id.endswith("-CDE") else ProductType.SPOT.value


def _futures_product_metadata() -> dict[str, dict[str, Any]]:
    orderbook = _runtime_orderbook()
    metadata = _products_json_metadata()
    metadata.update(_orderbook_product_metadata(orderbook))
    return {
        product_id: payload
        for product_id, payload in metadata.items()
        if _normalize_admin_product_type(product_id, payload) == ProductType.FUTURE.value
    }


def _runtime_fee_info(product_id: str | None = None) -> dict[str, Any]:
    engine = _runtime_order_engine()
    fee_manager = getattr(engine, "fee_manager", None) if engine else None
    if fee_manager is not None:
        try:
            return _dict_or_empty(fee_manager.get_fee_info(product_id=product_id))
        except TypeError:
            try:
                return _dict_or_empty(fee_manager.get_fee_info())
            except Exception:
                pass
        except Exception:
            pass
    dashboard_snapshot = _dashboard_state_snapshot()
    engine_status = _dict_or_empty(dashboard_snapshot.get("engine_status"))
    return {
        key: engine_status.get(key)
        for key in (
            "margin_window_type",
            "overnight_margin_active",
            "effective_fee_rate",
            "target_movement_factor",
            "fee_regime_factor",
            "volume_ratio",
        )
        if key in engine_status
    }


def _snapshot_future_positions() -> tuple[dict[str, dict[str, Any]], AdminFuturesEvidenceSource]:
    orderbook = _runtime_orderbook()
    if orderbook is not None:
        try:
            snapshot = orderbook.snapshot_positions()
            futures_positions = _dict_or_empty(snapshot.get(ProductType.FUTURE.value))
            return {
                str(product_id): _dict_or_empty(position)
                for product_id, position in futures_positions.items()
            }, AdminFuturesEvidenceSource.RUNTIME_ORDERBOOK
        except Exception:
            pass
        try:
            items = orderbook.iter_future_positions()
            return {
                str(product_id): _dict_or_empty(position)
                for product_id, position in items
            }, AdminFuturesEvidenceSource.RUNTIME_ORDERBOOK
        except Exception:
            pass
    dashboard_snapshot = _dashboard_state_snapshot()
    positions = _dict_or_empty(dashboard_snapshot.get("positions"))
    if positions:
        products = _futures_product_metadata()
        filtered_positions: dict[str, dict[str, Any]] = {}
        for product_id, position in positions.items():
            normalized_product_id = str(product_id)
            normalized_position = _dict_or_empty(position)
            if normalized_product_id in products or (
                _normalize_admin_product_type(
                    normalized_product_id,
                    normalized_position,
                )
                == ProductType.FUTURE.value
            ):
                filtered_positions[normalized_product_id] = normalized_position
        return filtered_positions, AdminFuturesEvidenceSource.DASHBOARD_ENGINE_STATE
    return {}, AdminFuturesEvidenceSource.RUNTIME_UNAVAILABLE


def _decimal_string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _numeric_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _derive_position_side(position: dict[str, Any]) -> str | None:
    for field_name in ("side", "position_side", "position_direction"):
        value = position.get(field_name)
        if value:
            normalized = str(value).upper()
            if normalized in {
                AdminFuturesPositionSide.LONG.value,
                AdminFuturesPositionSide.SHORT.value,
            }:
                return normalized
    net_size = _numeric_float_or_none(position.get("net_size"))
    if net_size is not None:
        if net_size > 0:
            return AdminFuturesPositionSide.LONG.value
        if net_size < 0:
            return AdminFuturesPositionSide.SHORT.value
        return AdminFuturesPositionSide.FLAT.value
    return None


def _derive_number_of_contracts(position: dict[str, Any]) -> str | None:
    for field_name in ("number_of_contracts", "contracts", "size"):
        value = position.get(field_name)
        if value is not None:
            return str(value)
    net_size = _numeric_float_or_none(position.get("net_size"))
    if net_size is not None:
        return str(abs(net_size))
    return None


def _position_key(product_id: str, position: dict[str, Any]) -> str:
    portfolio_uuid = _string_or_none(position.get("portfolio_uuid")) or "runtime"
    return f"futures_position:{portfolio_uuid}:{product_id}"


def _futures_position_item_from_raw(
    *,
    product_id: str,
    position: dict[str, Any],
    product_metadata: dict[str, Any] | None,
    mandatory_fee_per_contract: str | None,
    source: AdminFuturesEvidenceSource,
) -> AdminFuturesPositionReadItem:
    position_side = _derive_position_side(position)
    number_of_contracts = _derive_number_of_contracts(position)
    open_order_side: str | None = None
    close_order_side: str | None = None
    if position_side in {
        AdminFuturesPositionSide.LONG.value,
        AdminFuturesPositionSide.SHORT.value,
    }:
        try:
            from configuration import determine_open_close_sides

            open_order_side, close_order_side = determine_open_close_sides(
                ProductType.FUTURE.value,
                position_side=position_side,
                position_size=_numeric_float_or_none(number_of_contracts),
            )
        except Exception:
            if position_side == AdminFuturesPositionSide.SHORT.value:
                open_order_side = OrderSide.SELL.value
                close_order_side = OrderSide.BUY.value
            else:
                open_order_side = OrderSide.BUY.value
                close_order_side = OrderSide.SELL.value

    position_pnl: dict[str, Any] = {}
    for field_name in ("unrealized_pnl", "realized_pnl"):
        if field_name in position:
            position_pnl[field_name] = position[field_name]

    return AdminFuturesPositionReadItem(
        position_key=_position_key(product_id, position),
        product_id=product_id,
        product_type=ProductType.FUTURE.value,
        portfolio_uuid=_string_or_none(position.get("portfolio_uuid")),
        position_side=position_side,
        number_of_contracts=number_of_contracts,
        net_size=_decimal_string_or_none(position.get("net_size")),
        entry_price=_decimal_string_or_none(position.get("entry_price")),
        entry_vwap=_decimal_string_or_none(position.get("entry_vwap")),
        current_price=_decimal_string_or_none(position.get("current_price")),
        margin_type=_string_or_none(position.get("margin_type")),
        margin_amount=_json_object_or_none(position.get("margin_amt")),
        leverage=_decimal_string_or_none(position.get("leverage")),
        liquidation_buffer_percentage=_decimal_string_or_none(
            position.get("liquidation_buffer_percentage")
        ),
        open_order_side=open_order_side,
        close_order_side=close_order_side,
        reduce_only_order_side=close_order_side,
        close_only_order_side=close_order_side,
        position_pnl=position_pnl or None,
        product_metadata=_dict_or_empty(product_metadata) or None,
        mandatory_fee_per_contract=mandatory_fee_per_contract,
        raw_position=dict(position),
        source=source,
        updated_at=_string_or_none(position.get("updated_at")),
    )


def _mandatory_fee_map(orderbook: Any | None) -> dict[str, dict[str, Any]]:
    fees = getattr(orderbook, "mandatory_fee_per_contract", None)
    if not isinstance(fees, dict) and not hasattr(fees, "items"):
        return {}
    try:
        return {
            str(product_id): _dict_or_empty(payload)
            for product_id, payload in fees.items()
        }
    except Exception:
        return {}


def _futures_position_items() -> list[AdminFuturesPositionReadItem]:
    products = _futures_product_metadata()
    positions, source = _snapshot_future_positions()
    orderbook = _runtime_orderbook()
    mandatory_fees = _mandatory_fee_map(orderbook)
    items: list[AdminFuturesPositionReadItem] = []
    for product_id, position in positions.items():
        product_metadata = products.get(product_id, {})
        metadata_product_type = _normalize_admin_product_type(
            product_id,
            product_metadata,
        ) if product_metadata else None
        position_product_type = _normalize_admin_product_type(product_id, position)
        if metadata_product_type and metadata_product_type != ProductType.FUTURE.value:
            continue
        if (
            not metadata_product_type
            and source == AdminFuturesEvidenceSource.DASHBOARD_ENGINE_STATE
            and position_product_type != ProductType.FUTURE.value
        ):
            continue
        fee_payload = mandatory_fees.get(product_id, {})
        items.append(
            _futures_position_item_from_raw(
                product_id=product_id,
                position=position,
                product_metadata=product_metadata,
                mandatory_fee_per_contract=_decimal_string_or_none(
                    fee_payload.get("mandatory_fee_per_contract")
                ),
                source=source,
            )
        )
    return items


def _futures_evidence(
    *,
    name: str,
    status: AdminFuturesEvidenceStatus,
    source: AdminFuturesEvidenceSource,
    value: Any | None = None,
    detail: str | None = None,
) -> AdminFuturesEvidenceItem:
    return AdminFuturesEvidenceItem(
        name=name,
        status=status,
        source=source,
        value=value,
        detail=detail,
    )


def _risk_evidence(
    *,
    name: str,
    status: AdminRiskEvidenceStatus,
    source: AdminRiskEvidenceSource,
    value: Any | None = None,
    detail: str | None = None,
) -> AdminRiskEvidenceItem:
    return AdminRiskEvidenceItem(
        name=name,
        status=status,
        source=source,
        value=value,
        detail=detail,
    )


def _normalize_guard_phases(value: Any) -> list[str]:
    if value is None:
        return [
            ActionGuardPhase.PLANNING.value,
            ActionGuardPhase.REVEAL.value,
        ]
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = [value]
    phases: list[str] = []
    for item in values:
        try:
            phase = ActionGuardPhase(str(item)).value
        except ValueError:
            phase = str(item)
        if phase not in phases:
            phases.append(phase)
    return phases


def _configured_limit_rules(policy: dict[str, Any]) -> list[AdminRiskPolicyRuleItem]:
    limits = policy.get("limits") or []
    if isinstance(limits, dict):
        limits = list(limits.values())
    if not isinstance(limits, list):
        return []

    items: list[AdminRiskPolicyRuleItem] = []
    for index, raw_rule in enumerate(limits):
        if not isinstance(raw_rule, dict):
            continue
        rule = dict(raw_rule)
        policy_id = str(rule.get("name") or f"limit_{index}")
        max_notional = rule.get(ActionConditionType.MAX_NOTIONAL.value)
        max_base_size = rule.get(ActionConditionType.MAX_BASE_SIZE.value)
        items.append(
            AdminRiskPolicyRuleItem(
                policy_id=policy_id,
                enabled=rule.get("enabled", True) is not False,
                product_id=_string_or_none(rule.get("product_id")),
                product_type=rule.get("product_type"),
                side=rule.get("side"),
                phases=_normalize_guard_phases(rule.get("phases")),
                max_notional=(
                    str(max_notional) if max_notional is not None else None
                ),
                max_base_size=(
                    str(max_base_size) if max_base_size is not None else None
                ),
                raw_rule=rule,
            )
        )
    return items


def _product_capability_decisions(
    product_id: str | None,
) -> tuple[list[AdminProductCapabilityDecisionItem], list[str]]:
    if not product_id:
        return [], []
    try:
        from core.product_capability import evaluate_product_capability
    except Exception as exc:
        return [], [f"import_error:{type(exc).__name__}: {exc}"]

    decisions: list[AdminProductCapabilityDecisionItem] = []
    errors: list[str] = []
    for capability in ProductCapability:
        try:
            decision = evaluate_product_capability(
                product_id=product_id,
                capability=capability,
            )
        except Exception as exc:
            errors.append(f"{capability.value}:{type(exc).__name__}: {exc}")
            continue
        decisions.append(
            AdminProductCapabilityDecisionItem(
                product_id=decision.product_id,
                product_type=decision.product_type,
                capability=capability,
                mode=decision.mode,
                allowed=decision.allowed,
                reason=decision.reason,
            )
        )
    return decisions, errors


def _risk_rejection_categories() -> list[AdminRiskRejectionCategoryItem]:
    return [
        AdminRiskRejectionCategoryItem(
            condition=ActionConditionType.MANUAL_LIVE_ACKNOWLEDGEMENT,
            source=AdminRiskEvidenceSource.ACTION_CONDITION_GUARD,
            applies_to_product_type=ProductType.SPOT,
            detail="Direct spot placement requires explicit manual live acknowledgement before REST submission.",
        ),
        AdminRiskRejectionCategoryItem(
            condition=ActionConditionType.DIRECT_SPOT_CAP_REQUIRED,
            source=AdminRiskEvidenceSource.ACTION_CONDITION_GUARD,
            applies_to_product_type=ProductType.SPOT,
            detail="Direct spot placement requires a planning-phase max_notional cap before REST submission.",
        ),
        AdminRiskRejectionCategoryItem(
            condition=ActionConditionType.MAX_NOTIONAL,
            source=AdminRiskEvidenceSource.ACTION_CONDITION_GUARD,
            detail="Configured max_notional rules block oversized actions before exchange work.",
        ),
        AdminRiskRejectionCategoryItem(
            condition=ActionConditionType.MAX_BASE_SIZE,
            source=AdminRiskEvidenceSource.ACTION_CONDITION_GUARD,
            detail="Configured max_base_size rules block oversized actions before exchange work.",
        ),
        AdminRiskRejectionCategoryItem(
            condition=ActionConditionType.WALLET_AVAILABLE,
            source=AdminRiskEvidenceSource.ACTION_CONDITION_GUARD,
            applies_to_product_type=ProductType.SPOT,
            detail="Spot wallet availability is evaluated at backend action boundaries only.",
        ),
        AdminRiskRejectionCategoryItem(
            condition=ActionConditionType.PLANNED_BUDGET_AVAILABLE,
            source=AdminRiskEvidenceSource.ACTION_CONDITION_GUARD,
            applies_to_product_type=ProductType.SPOT,
            detail="Spot planned budget commitments are subtracted at planning and reveal boundaries.",
        ),
        AdminRiskRejectionCategoryItem(
            condition=ActionConditionType.KNOWN_INVENTORY_AVAILABLE,
            source=AdminRiskEvidenceSource.SPOT_INVENTORY_AUTHORITY,
            applies_to_product_type=ProductType.SPOT,
            detail="Known profitable inventory authority applies only to spot SELL actions.",
        ),
        AdminRiskRejectionCategoryItem(
            condition=ActionConditionType.DURABLE_AUDIT_AVAILABLE,
            source=AdminRiskEvidenceSource.LIVE_EXECUTION_GATE,
            detail="Durable audit evidence is required before approved live command execution.",
        ),
    ]


def _query_admin_rows(
    query: str,
    params: tuple[Any, ...] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        from database import order as order_module

        rows = order_module.DB_CLIENT.execute_query(query, params) or []
        return [dict(row) for row in rows], None
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"


def _runtime_bridge() -> Any | None:
    try:
        import dashboard_server

        return getattr(dashboard_server, "stealth_order_bridge", None)
    except Exception:
        return None


def _runtime_mutation_claims_for(
    stealth_order_id: str | None,
) -> list[AdminMutationClaimEvidence]:
    if not stealth_order_id:
        return []
    bridge = _runtime_bridge()
    manager = getattr(bridge, "stealth_manager", None) if bridge else None
    claim_ledger = getattr(manager, "_mutation_claims", None) if manager else None
    if claim_ledger is None:
        return [
            AdminMutationClaimEvidence(
                kind=kind,
                state=None,
                runtime_observed=False,
                source="runtime_stealth_manager_unavailable",
            )
            for kind in StealthMutationKind
        ]
    claims: list[AdminMutationClaimEvidence] = []
    for kind in StealthMutationKind:
        try:
            state = _string_or_none(claim_ledger.state(kind, stealth_order_id))
        except Exception as exc:
            state = f"unavailable:{type(exc).__name__}"
        claims.append(
            AdminMutationClaimEvidence(
                kind=kind,
                state=state,
                runtime_observed=True,
                source="stealth_manager._mutation_claims",
            )
        )
    return claims


def _runtime_pending_replacement_claims(
    client_order_id: str | None,
) -> tuple[int | None, bool]:
    if not client_order_id:
        return None, False
    bridge = _runtime_bridge()
    engine = getattr(bridge, "order_engine", None) if bridge else None
    claims = getattr(engine, "_pending_replacement_claims", None) if engine else None
    if claims is None:
        return None, False
    lock = getattr(engine, "orderbook_lock", None)
    if lock is None:
        return None, False
    try:
        with lock:
            return _int_or_none(claims.get(client_order_id, 0)), True
    except Exception:
        return None, False


def _parent_order_row(client_order_id: str | None) -> dict[str, Any] | None:
    if not client_order_id:
        return None
    try:
        from database import order as order_module

        row = order_module.get_parent_order(client_order_id)
        return dict(row) if row else None
    except Exception:
        return None


def _stealth_order_row(stealth_order_id: str | None) -> dict[str, Any] | None:
    if not stealth_order_id:
        return None
    try:
        from database import order as order_module

        row = order_module.get_stealth_order_by_id(stealth_order_id)
        return dict(row) if row else None
    except Exception:
        return None


def _replacement_slot_evidence(
    client_order_id: str | None,
) -> AdminReplacementSlotEvidence | None:
    if not client_order_id:
        return None
    pending_claims, pending_observed = _runtime_pending_replacement_claims(
        client_order_id
    )
    row = _parent_order_row(client_order_id)
    if row:
        return AdminReplacementSlotEvidence(
            client_order_id=client_order_id,
            max_order_replacement=_int_or_none(row.get("max_order_replacement")),
            current_order_replacement=_int_or_none(
                row.get("current_order_replacement")
            ),
            pending_replacement_claims=pending_claims,
            pending_claims_runtime_observed=pending_observed,
            source="order_parent",
        )
    if pending_observed:
        return AdminReplacementSlotEvidence(
            client_order_id=client_order_id,
            pending_replacement_claims=pending_claims,
            pending_claims_runtime_observed=True,
            source="runtime_order_engine",
        )
    return AdminReplacementSlotEvidence(
        client_order_id=client_order_id,
        pending_replacement_claims=None,
        pending_claims_runtime_observed=False,
        source="order_parent_missing",
    )


def _replacement_slots_for(
    *client_order_ids: str | None,
) -> list[AdminReplacementSlotEvidence]:
    slots: list[AdminReplacementSlotEvidence] = []
    seen: set[str] = set()
    for client_order_id in client_order_ids:
        if not client_order_id or client_order_id in seen:
            continue
        seen.add(client_order_id)
        slot = _replacement_slot_evidence(client_order_id)
        if slot:
            slots.append(slot)
    return slots


def _parent_move_item_from_row(row: dict[str, Any]) -> AdminMovementRepricingEvidenceItem:
    original_parent_client_order_id = _string_or_none(
        row.get("original_parent_client_order_id")
    )
    new_parent_client_order_id = _string_or_none(row.get("new_parent_client_order_id"))
    move_on_cancel = _bool_or_none(row.get("move_on_cancel"))
    status = (
        "pending_move"
        if move_on_cancel and not new_parent_client_order_id
        else "completed_move"
    )
    parent_row = (
        _parent_order_row(original_parent_client_order_id)
        or _parent_order_row(new_parent_client_order_id)
        or {}
    )
    return AdminMovementRepricingEvidenceItem(
        evidence_id=f"parent_move:{row.get('id') or original_parent_client_order_id}",
        evidence_type=AdminMovementRepricingEvidenceType.PARENT_MOVE,
        client_order_id=original_parent_client_order_id,
        original_parent_client_order_id=original_parent_client_order_id,
        new_parent_client_order_id=new_parent_client_order_id,
        product_id=_string_or_none(parent_row.get("product_id")),
        side=_string_or_none(parent_row.get("side")),
        status=status,
        move_on_cancel=move_on_cancel,
        reason=_string_or_none(row.get("reason")),
        notes=_string_or_none(row.get("notes")),
        replacement_slots=_replacement_slots_for(
            original_parent_client_order_id,
            new_parent_client_order_id,
        ),
        created_at=_string_or_none(row.get("created_at")),
        moved_at=_string_or_none(row.get("moved_at")),
        source="order_moves",
    )


def _stealth_move_item_from_row(row: dict[str, Any]) -> AdminMovementRepricingEvidenceItem:
    stealth_order_id = _string_or_none(row.get("stealth_order_id"))
    stealth_row = _stealth_order_row(stealth_order_id) or {}
    new_placement_client_order_id = _string_or_none(
        row.get("new_placement_client_order_id")
    )
    old_placement_client_order_id = _string_or_none(
        row.get("old_placement_client_order_id")
    )
    return AdminMovementRepricingEvidenceItem(
        evidence_id=f"stealth_move:{row.get('id') or stealth_order_id}",
        evidence_type=AdminMovementRepricingEvidenceType.STEALTH_MOVE,
        client_order_id=new_placement_client_order_id or old_placement_client_order_id,
        stealth_order_id=stealth_order_id,
        product_id=_string_or_none(stealth_row.get("product_id")),
        side=_string_or_none(stealth_row.get("side")),
        status=_string_or_none(row.get("status")),
        reason=_string_or_none(row.get("reason")),
        notes=_string_or_none(row.get("notes")),
        old_placement_client_order_id=old_placement_client_order_id,
        old_exchange_order_id=_string_or_none(row.get("old_exchange_order_id")),
        old_submitted_price=_string_or_none(row.get("old_submitted_price")),
        new_placement_client_order_id=new_placement_client_order_id,
        new_exchange_order_id=_string_or_none(row.get("new_exchange_order_id")),
        new_submitted_price=_string_or_none(row.get("new_submitted_price")),
        mutation_claims=_runtime_mutation_claims_for(stealth_order_id),
        market_bid=_string_or_none(row.get("market_bid")),
        market_ask=_string_or_none(row.get("market_ask")),
        error_message=_string_or_none(row.get("error_message")),
        moved_at=_string_or_none(row.get("moved_at")),
        source="stealth_order_moves",
    )


def _stealth_repricing_item_from_row(
    row: dict[str, Any],
) -> AdminMovementRepricingEvidenceItem:
    stealth_order_id = _string_or_none(row.get("stealth_order_id"))
    parent_order_id = _string_or_none(row.get("parent_order_id"))
    anchor_state = _json_object_or_none(row.get("anchor_repricing_state_json")) or {}
    active_placement_client_order_id = _string_or_none(
        anchor_state.get("active_placement_client_order_id")
        or anchor_state.get("active_placement_order_id")
        or anchor_state.get("active_placed_order_id")
    )
    active_exchange_order_id = _string_or_none(
        anchor_state.get("active_exchange_order_id")
    )
    return AdminMovementRepricingEvidenceItem(
        evidence_id=f"stealth_repricing_state:{stealth_order_id}",
        evidence_type=AdminMovementRepricingEvidenceType.STEALTH_REPRICING_STATE,
        client_order_id=active_placement_client_order_id,
        stealth_order_id=stealth_order_id,
        product_id=_string_or_none(row.get("product_id")),
        side=_string_or_none(row.get("side")),
        status=_string_or_none(row.get("status")),
        active_placement_client_order_id=active_placement_client_order_id,
        active_exchange_order_id=active_exchange_order_id,
        active_exchange_price=_string_or_none(anchor_state.get("active_exchange_price")),
        target_movement=_string_or_none(row.get("target_movement")),
        target_movement_type=_string_or_none(row.get("target_movement_type")),
        replacement_slots=_replacement_slots_for(parent_order_id, stealth_order_id),
        mutation_claims=_runtime_mutation_claims_for(stealth_order_id),
        anchor_repricing_policy=_json_object_or_none(
            row.get("anchor_repricing_policy_json")
        ),
        anchor_repricing_state=anchor_state,
        reprice_history=_list_or_empty(anchor_state.get("reprice_history")),
        reprice_reason=_string_or_none(anchor_state.get("reprice_reason")),
        last_reprice_at=_string_or_none(anchor_state.get("last_reprice_at")),
        next_reprice_at=_string_or_none(anchor_state.get("next_reprice_at")),
        post_fill_retreat_offset=_string_or_none(
            anchor_state.get("post_fill_retreat_offset")
        ),
        created_at=_string_or_none(row.get("created_at")),
        updated_at=_string_or_none(row.get("updated_at")),
        source="stealth_orders",
    )


def _movement_evidence_type_value(
    evidence_type: AdminMovementRepricingEvidenceType | str | None,
) -> str | None:
    if evidence_type is None:
        return None
    if isinstance(evidence_type, AdminMovementRepricingEvidenceType):
        return evidence_type.value
    return str(evidence_type)


def _movement_item_matches(
    item: AdminMovementRepricingEvidenceItem,
    *,
    product_id: str | None,
    client_order_id: str | None,
    stealth_order_id: str | None,
    evidence_type: AdminMovementRepricingEvidenceType | str | None,
) -> bool:
    if product_id and item.product_id != product_id:
        return False
    if stealth_order_id and item.stealth_order_id != stealth_order_id:
        return False
    if evidence_type and item.evidence_type.value != _movement_evidence_type_value(
        evidence_type
    ):
        return False
    if client_order_id:
        client_fields = {
            item.client_order_id,
            item.original_parent_client_order_id,
            item.new_parent_client_order_id,
            item.old_placement_client_order_id,
            item.new_placement_client_order_id,
            item.active_placement_client_order_id,
        }
        if client_order_id not in client_fields:
            return False
    return True


class AdminApiReadService:
    """Read-only status service for operator views.

    The current implementation delegates to existing dashboard payload builders
    without using the dashboard WebSocket transport. These methods must remain
    read-only.
    """

    def build_admin_bootstrap(self) -> AdminBootstrapResponse:
        """Return backend association and live-action posture."""

        cors_configured = bool(os.environ.get("COINBASE_ADMIN_API_CORS_ORIGINS", "").strip())
        return AdminBootstrapResponse(
            backend_repository="s-aws/coinbase",
            api_version=API_VERSION,
            schema_version=SCHEMA_VERSION,
            environment=os.environ.get("COINBASE_ADMIN_API_ENVIRONMENT", "local"),
            mutating_routes_live_disabled=True,
            live_execution_enabled=False,
            auth_required=True,
            auth_mode=configured_auth_mode(),
            cors_configured=cors_configured,
            csrf_required=_csrf_required(),
            capabilities_route="/api/v1/admin/capabilities",
            session_route="/api/v1/admin/session",
        )

    def build_admin_health(self) -> AdminHealthResponse:
        """Return read-only API health without probing Coinbase."""

        diagnostics = []
        for item in ADMIN_API_ROUTE_INVENTORY:
            method, path = _surface_method_and_path(item.surface)
            if "WebSocket" in item.surface:
                continue
            availability = _route_availability(item.surface, item.action_class)
            diagnostics.append({
                "path": path,
                "method": method,
                "status": availability,
                "message": (
                    "Live execution disabled by backend contract"
                    if availability == AdminApiRouteAvailability.LIVE_DISABLED
                    else "Route contract is available"
                ),
            })
        failed_route_count = sum(
            1
            for diagnostic in diagnostics
            if diagnostic["status"] == AdminApiRouteAvailability.BACKEND_BLOCKED
        )
        return AdminHealthResponse(
            status=(
                AdminApiHealthStatus.BLOCKED
                if failed_route_count
                else AdminApiHealthStatus.HEALTHY
            ),
            api_version=API_VERSION,
            diagnostics=diagnostics,
            failed_route_count=failed_route_count,
        )

    def build_admin_session(
        self,
        *,
        actor: AdminApiActor,
        permissions: list[AdminApiPermission],
    ) -> AdminSessionResponse:
        """Return authenticated actor and permission evidence."""

        return AdminSessionResponse(
            status=AdminApiSessionStatus.SIGNED_IN,
            actor=actor,
            permissions=permissions,
            auth_mode=configured_auth_mode(),
        )

    def build_oidc_jwt_readiness(self) -> AdminOidcJwtReadinessResponse:
        """Return backend OIDC/JWT verifier readiness evidence."""

        readiness = build_oidc_jwt_readiness()
        jwks_reachability = "not_checked"
        jwks_failure_reason: str | None = None
        status = readiness.status
        failure_reason = readiness.failure_reason
        if not readiness.missing_env_vars:
            jwks_reachability, jwks_failure_reason = check_oidc_jwks_reachability()
            if jwks_reachability != "reachable":
                status = AdminApiVerifierReadinessStatus.BLOCKED
                failure_reason = jwks_failure_reason

        return AdminOidcJwtReadinessResponse(
            active_auth_mode=configured_auth_mode(),
            mode=readiness.mode,
            status=status,
            verifier_implemented=readiness.verifier_implemented,
            required_env_vars=list(readiness.required_env_vars),
            missing_env_vars=list(readiness.missing_env_vars),
            claims_contract=dict(readiness.claims_contract),
            failure_reason=failure_reason,
            jwks_reachability=jwks_reachability,
            jwks_failure_reason=jwks_failure_reason,
            live_coinbase_execution=readiness.live_coinbase_execution,
            notional_usdc=readiness.notional_usdc,
        )

    def build_admin_capabilities(self) -> AdminCapabilityRegistryResponse:
        """Return route capability metadata derived from the owned inventory."""

        capabilities: list[AdminCapabilityItem] = []
        for item in ADMIN_API_ROUTE_INVENTORY:
            method, path = _surface_method_and_path(item.surface)
            availability = _route_availability(item.surface, item.action_class)
            capabilities.append(
                AdminCapabilityItem(
                    route=path,
                    method=method,
                    action_class=item.action_class,
                    permission=item.permission,
                    availability=availability,
                    live_enabled=False,
                    frontend_safe=_frontend_safe(item.surface, item.action_class),
                    shared_method=item.shared_method,
                    notes=(
                        "Compatibility-only legacy dashboard surface"
                        if "WebSocket" in item.surface
                        else "Backend-owned Admin API route"
                    ),
                )
            )
        return AdminCapabilityRegistryResponse(capabilities=capabilities)

    def build_guard_risk_policy(
        self,
        *,
        product_id: str | None = None,
    ) -> AdminRiskPolicyReadResponse:
        """Return read-only guard/risk policy evidence without Coinbase reads."""

        from core.action_condition_guard import (
            get_action_condition_guard_policy,
            normalize_action_guard_known_inventory_policy,
            normalize_action_guard_wallet_policy,
            rest_credentials_configured,
        )
        from core.product_capability import get_product_capability_policy

        action_policy = get_action_condition_guard_policy()
        wallet_policy = normalize_action_guard_wallet_policy(action_policy)
        known_inventory_policy = normalize_action_guard_known_inventory_policy(
            action_policy
        )
        limit_rules = _configured_limit_rules(action_policy)
        product_capability_policy = get_product_capability_policy()
        live_gate = evaluate_live_execution_gate(allow_live_execution=False)

        action_policy_value = {
            "policy_configured": bool(action_policy),
            "wallet_available": wallet_policy,
            "known_inventory_available": known_inventory_policy,
            "limit_rule_count": len(limit_rules),
            "limit_policy_ids": [rule.policy_id for rule in limit_rules],
            "rest_credentials_configured": rest_credentials_configured(),
            "coinbase_wallet_fetch_performed": False,
            "decision_boundary": (
                "ActionConditionGuard.evaluate at planning/reveal/command "
                "boundaries; this read route reports policy only."
            ),
        }

        capability_decisions, capability_errors = _product_capability_decisions(product_id)
        capability_value: dict[str, Any] = {
            "configured_overrides": product_capability_policy,
            "decision_product_id": product_id,
            "decision_count": len(capability_decisions),
            "decision_error_count": len(capability_errors),
            "decision_errors": capability_errors,
            "conditional_modes_are_not_live_authority": True,
        }
        if not product_id:
            capability_value["decision_detail"] = (
                "Pass product_id to inspect product-specific capability "
                "decisions; defaults remain backend-owned."
            )

        authority_sources = [
            _risk_evidence(
                name="wallet_authority",
                status=(
                    AdminRiskEvidenceStatus.OBSERVED
                    if wallet_policy.get("enabled", True) is not False
                    else AdminRiskEvidenceStatus.NOT_MODELED
                ),
                source=AdminRiskEvidenceSource.ACTION_CONDITION_GUARD,
                value={
                    "policy": wallet_policy,
                    "coinbase_wallet_fetch_performed": False,
                },
                detail=(
                    "Spot wallet availability is evaluated by the backend "
                    "action guard at command/reveal boundaries; this route "
                    "does not fetch Coinbase wallets."
                ),
            ),
            _risk_evidence(
                name="planned_budget_authority",
                status=AdminRiskEvidenceStatus.OBSERVED,
                source=AdminRiskEvidenceSource.ACTION_CONDITION_GUARD,
                value={
                    "hidden_statuses_counted": [
                        StealthOrderStatus.HIDDEN.value,
                        StealthOrderStatus.PENDING.value,
                        StealthOrderStatus.TRIGGERED.value,
                    ],
                    "revealed_orders_excluded": True,
                },
                detail=(
                    "Local pre-exchange spot commitments are subtracted by "
                    "the existing planned-budget guard."
                ),
            ),
            _risk_evidence(
                name="spot_known_inventory_authority",
                status=(
                    AdminRiskEvidenceStatus.OBSERVED
                    if known_inventory_policy.get("enabled", False) is not False
                    else AdminRiskEvidenceStatus.NOT_MODELED
                ),
                source=AdminRiskEvidenceSource.SPOT_INVENTORY_AUTHORITY,
                value={"policy": known_inventory_policy},
                detail=(
                    "Known profitable inventory authority is spot SELL only; "
                    "it is not imported into futures/perpetual modules."
                ),
            ),
            _risk_evidence(
                name="position_authority",
                status=AdminRiskEvidenceStatus.OBSERVED,
                source=AdminRiskEvidenceSource.BACKEND_CONTRACT,
                value={
                    "futures_position_identity": "position_key",
                    "spot_inventory_identity": "client_order_id_and_lot_authority",
                },
                detail=(
                    "Position authority is product-domain specific. Futures "
                    "uses position evidence; spot uses wallet/lot authority."
                ),
            ),
        ]

        return AdminRiskPolicyReadResponse(
            filters={"product_id": product_id},
            action_condition_policy=_risk_evidence(
                name="action_condition_policy",
                status=AdminRiskEvidenceStatus.OBSERVED,
                source=AdminRiskEvidenceSource.ACTION_CONDITION_GUARD,
                value=action_policy_value,
                detail=(
                    "Configured guard policy and cap rules are exposed as "
                    "read-only evidence; no guard decision is trusted to the browser."
                ),
            ),
            configured_limit_rules=limit_rules,
            live_execution_gate=_risk_evidence(
                name="live_execution_gate",
                status=AdminRiskEvidenceStatus.FAIL_CLOSED,
                source=AdminRiskEvidenceSource.LIVE_EXECUTION_GATE,
                value=live_gate.model_dump(mode="json"),
                detail=(
                    "HTTP live execution remains fail-closed until approval, "
                    "cap evaluation, and durable audit gates are enforced."
                ),
            ),
            product_capability_policy=_risk_evidence(
                name="product_capability_policy",
                status=(
                    AdminRiskEvidenceStatus.UNAVAILABLE
                    if capability_errors
                    else AdminRiskEvidenceStatus.OBSERVED
                ),
                source=AdminRiskEvidenceSource.PRODUCT_CAPABILITY_POLICY,
                value=capability_value,
                detail=(
                    "Product capability decisions come from core.product_capability; "
                    "the frontend may display but not override them."
                ),
            ),
            product_capability_decisions=capability_decisions,
            profitability_policy=_risk_evidence(
                name="profitability_policy",
                status=AdminRiskEvidenceStatus.OBSERVED,
                source=AdminRiskEvidenceSource.PROFIT_VALIDATOR,
                value={
                    "validator": "calculation.profit_validator.ProfitValidator",
                    "product_specific": True,
                    "browser_calculation_allowed": False,
                    "known_contract_gaps": [
                        "futures_margin_validation",
                        "futures_liquidation_distance",
                        "perpetual_funding_cost_accounting",
                    ],
                },
                detail=(
                    "Profitability evidence is backend-owned and product-specific; "
                    "M4 exposes policy posture, not a browser calculator."
                ),
            ),
            authority_sources=authority_sources,
            rejection_categories=_risk_rejection_categories(),
        )

    def build_csrf_contract(self) -> AdminCsrfContractResponse:
        """Return CSRF posture without disclosing a token value."""

        return AdminCsrfContractResponse(csrf_required=_csrf_required())

    def build_order_list(
        self,
        *,
        product_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> AdminOrderListResponse:
        """Return a read-only order list from local order_parent evidence."""

        normalized_limit = max(1, min(limit, 500))
        normalized_offset = max(0, offset)
        filters: dict[str, Any] = {
            "product_id": product_id,
            "status": status,
            "limit": normalized_limit,
            "offset": normalized_offset,
        }
        try:
            from database.order import get_parent_orders

            rows = get_parent_orders() or []
        except Exception as exc:
            filters["backend_read_error"] = f"{type(exc).__name__}: {exc}"
            rows = []

        filtered: list[dict[str, Any]] = []
        for row in rows:
            if product_id and row.get("product_id") != product_id:
                continue
            if status and str(row.get("status") or "").lower() != status.lower():
                continue
            filtered.append(row)
        page_rows = filtered[normalized_offset:normalized_offset + normalized_limit]
        items = [_order_item_from_row(row) for row in page_rows]
        next_offset = normalized_offset + len(items)
        has_more = next_offset < len(filtered)
        return AdminOrderListResponse(
            filters=filters,
            count=len(items),
            pagination={
                "limit": normalized_limit,
                "offset": normalized_offset,
                "returned_count": len(items),
                "total_matching_count": len(filtered),
                "next_offset": next_offset if has_more else None,
                "has_more": has_more,
            },
            items=items,
        )

    def build_order_detail(self, *, client_order_id: str) -> AdminOrderDetailResponse:
        """Return one read-only order row by ``client_order_id``."""

        try:
            from database.order import get_parent_order

            row = get_parent_order(client_order_id)
        except Exception:
            row = None
        return AdminOrderDetailResponse(
            client_order_id=client_order_id,
            found=row is not None,
            order=_order_item_from_row(row) if row else None,
        )

    def build_stealth_order_list(
        self,
        *,
        product_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> AdminStealthOrderListResponse:
        """Return read-only stealth order evidence from local persistence."""

        normalized_limit = max(1, min(limit, 500))
        normalized_offset = max(0, offset)
        filters: dict[str, Any] = {
            "product_id": product_id,
            "status": status,
            "limit": normalized_limit,
            "offset": normalized_offset,
        }
        try:
            from database import order as order_module

            rows = order_module.DB_CLIENT.execute_query(
                "SELECT * FROM stealth_orders ORDER BY updated_at DESC, created_at DESC"
            ) or []
        except Exception as exc:
            filters["backend_read_error"] = f"{type(exc).__name__}: {exc}"
            rows = []

        filtered: list[dict[str, Any]] = []
        for row in rows:
            if product_id and row.get("product_id") != product_id:
                continue
            if status and str(row.get("status") or "").lower() != status.lower():
                continue
            filtered.append(row)

        page_rows = filtered[normalized_offset:normalized_offset + normalized_limit]
        items = [_stealth_item_from_row(row) for row in page_rows]
        next_offset = normalized_offset + len(items)
        has_more = next_offset < len(filtered)
        return AdminStealthOrderListResponse(
            filters=filters,
            count=len(items),
            pagination={
                "limit": normalized_limit,
                "offset": normalized_offset,
                "returned_count": len(items),
                "total_matching_count": len(filtered),
                "next_offset": next_offset if has_more else None,
                "has_more": has_more,
            },
            items=items,
        )

    def build_stealth_order_detail(
        self,
        *,
        stealth_order_id: str,
    ) -> AdminStealthOrderDetailResponse:
        """Return one read-only stealth order row by ``stealth_order_id``."""

        try:
            from database.order import get_stealth_order_by_id

            row = get_stealth_order_by_id(stealth_order_id)
        except Exception:
            row = None
        return AdminStealthOrderDetailResponse(
            stealth_order_id=stealth_order_id,
            found=row is not None,
            order=_stealth_item_from_row(row) if row else None,
        )

    def build_movement_repricing_evidence(
        self,
        *,
        product_id: str | None = None,
        client_order_id: str | None = None,
        stealth_order_id: str | None = None,
        evidence_type: AdminMovementRepricingEvidenceType | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> AdminMovementRepricingListResponse:
        """Return read-only movement/repricing evidence from owned sources."""

        normalized_limit = max(1, min(limit, 500))
        normalized_offset = max(0, offset)
        filters: dict[str, Any] = {
            "product_id": product_id,
            "client_order_id": client_order_id,
            "stealth_order_id": stealth_order_id,
            "evidence_type": _movement_evidence_type_value(evidence_type),
            "limit": normalized_limit,
            "offset": normalized_offset,
        }
        read_errors: list[str] = []

        order_move_rows, error = _query_admin_rows(
            "SELECT * FROM order_moves ORDER BY created_at DESC, moved_at DESC"
        )
        if error:
            read_errors.append(f"order_moves:{error}")

        stealth_move_rows, error = _query_admin_rows(
            "SELECT * FROM stealth_order_moves ORDER BY moved_at DESC"
        )
        if error:
            read_errors.append(f"stealth_order_moves:{error}")

        stealth_rows, error = _query_admin_rows(
            "SELECT * FROM stealth_orders ORDER BY updated_at DESC, created_at DESC"
        )
        if error:
            read_errors.append(f"stealth_orders:{error}")
        if read_errors:
            filters["backend_read_errors"] = read_errors

        items: list[AdminMovementRepricingEvidenceItem] = []
        items.extend(_parent_move_item_from_row(row) for row in order_move_rows)
        items.extend(_stealth_move_item_from_row(row) for row in stealth_move_rows)
        items.extend(_stealth_repricing_item_from_row(row) for row in stealth_rows)

        filtered = [
            item
            for item in items
            if _movement_item_matches(
                item,
                product_id=product_id,
                client_order_id=client_order_id,
                stealth_order_id=stealth_order_id,
                evidence_type=evidence_type,
            )
        ]
        page_items = filtered[normalized_offset:normalized_offset + normalized_limit]
        next_offset = normalized_offset + len(page_items)
        has_more = next_offset < len(filtered)
        return AdminMovementRepricingListResponse(
            filters=filters,
            count=len(page_items),
            pagination={
                "limit": normalized_limit,
                "offset": normalized_offset,
                "returned_count": len(page_items),
                "total_matching_count": len(filtered),
                "next_offset": next_offset if has_more else None,
                "has_more": has_more,
            },
            items=page_items,
        )

    def build_movement_repricing_order_detail(
        self,
        *,
        client_order_id: str,
    ) -> AdminMovementRepricingDetailResponse:
        """Return movement/repricing evidence linked to one ``client_order_id``."""

        evidence = self.build_movement_repricing_evidence(
            client_order_id=client_order_id,
            limit=500,
            offset=0,
        )
        return AdminMovementRepricingDetailResponse(
            scope="client_order_id",
            client_order_id=client_order_id,
            found=bool(evidence.items),
            items=evidence.items,
        )

    def build_movement_repricing_stealth_detail(
        self,
        *,
        stealth_order_id: str,
    ) -> AdminMovementRepricingDetailResponse:
        """Return movement/repricing evidence linked to one ``stealth_order_id``."""

        evidence = self.build_movement_repricing_evidence(
            stealth_order_id=stealth_order_id,
            limit=500,
            offset=0,
        )
        return AdminMovementRepricingDetailResponse(
            scope="stealth_order_id",
            stealth_order_id=stealth_order_id,
            found=bool(evidence.items),
            items=evidence.items,
        )

    def build_futures_account(self) -> AdminFuturesAccountReadResponse:
        """Return read-only futures/perpetual account and risk evidence."""

        products = _futures_product_metadata()
        positions = _futures_position_items()
        configured_product_scope = sorted(products.keys())
        observed_position_scope = sorted({item.product_id for item in positions})
        fee_info = _runtime_fee_info()

        margin_value = {
            key: fee_info.get(key)
            for key in (
                "margin_window_type",
                "overnight_margin_active",
                "profit_validation_fee_rate",
                "effective_fee_rate",
                "target_movement_factor",
                "fee_regime_factor",
                "volume_ratio",
            )
            if key in fee_info
        }
        margin = (
            _futures_evidence(
                name="margin",
                status=AdminFuturesEvidenceStatus.OBSERVED,
                source=AdminFuturesEvidenceSource.FEE_MANAGER,
                value=margin_value,
                detail="Margin-window regime is observed from the runtime fee manager.",
            )
            if margin_value
            else _futures_evidence(
                name="margin",
                status=AdminFuturesEvidenceStatus.UNAVAILABLE,
                source=AdminFuturesEvidenceSource.RUNTIME_UNAVAILABLE,
                detail="No runtime fee-manager or margin-window evidence is currently available.",
            )
        )

        collateral_keys = (
            "futures_buying_power",
            "total_usd_balance",
            "cfm_usd_balance",
            "available_margin",
            "initial_margin",
            "total_open_orders_hold_amount",
        )
        collateral_value = {
            key: fee_info.get(key)
            for key in collateral_keys
            if fee_info.get(key) is not None
        }
        collateral = (
            _futures_evidence(
                name="collateral",
                status=AdminFuturesEvidenceStatus.OBSERVED,
                source=AdminFuturesEvidenceSource.FEE_MANAGER,
                value=collateral_value,
                detail="Collateral fields are present in runtime futures balance evidence.",
            )
            if collateral_value
            else _futures_evidence(
                name="collateral",
                status=AdminFuturesEvidenceStatus.UNAVAILABLE,
                source=AdminFuturesEvidenceSource.RUNTIME_UNAVAILABLE,
                detail="The engine does not currently retain a futures balance summary snapshot.",
            )
        )

        liquidation_keys = (
            "liquidation_threshold",
            "liquidation_buffer_amount",
            "liquidation_buffer_percentage",
        )
        liquidation_value = {
            key: fee_info.get(key)
            for key in liquidation_keys
            if fee_info.get(key) is not None
        }
        liquidation = (
            _futures_evidence(
                name="liquidation",
                status=AdminFuturesEvidenceStatus.OBSERVED,
                source=AdminFuturesEvidenceSource.FEE_MANAGER,
                value=liquidation_value,
                detail="Liquidation evidence is present in runtime futures balance evidence.",
            )
            if liquidation_value
            else _futures_evidence(
                name="liquidation",
                status=AdminFuturesEvidenceStatus.UNAVAILABLE,
                source=AdminFuturesEvidenceSource.RUNTIME_UNAVAILABLE,
                detail="Liquidation threshold and buffer are not retained in the current runtime snapshot.",
            )
        )

        pnl_items = [
            {
                "position_key": item.position_key,
                "product_id": item.product_id,
                "position_pnl": item.position_pnl,
            }
            for item in positions
            if item.position_pnl
        ]
        position_pnl = (
            _futures_evidence(
                name="position_pnl",
                status=AdminFuturesEvidenceStatus.OBSERVED,
                source=AdminFuturesEvidenceSource.RUNTIME_POSITIONS,
                value={"positions": pnl_items},
                detail="Position P/L is sourced from runtime futures position payloads.",
            )
            if pnl_items
            else _futures_evidence(
                name="position_pnl",
                status=AdminFuturesEvidenceStatus.UNAVAILABLE,
                source=AdminFuturesEvidenceSource.RUNTIME_UNAVAILABLE,
                detail="No runtime futures position P/L is currently available.",
            )
        )

        reduce_only_close_only = (
            _futures_evidence(
                name="reduce_only_close_only",
                status=AdminFuturesEvidenceStatus.OBSERVED,
                source=AdminFuturesEvidenceSource.POSITION_SIDE_DERIVATION,
                value={
                    item.position_key: {
                        "product_id": item.product_id,
                        "position_side": item.position_side,
                        "reduce_only_order_side": item.reduce_only_order_side,
                        "close_only_order_side": item.close_only_order_side,
                    }
                    for item in positions
                },
                detail=(
                    "Close/reduce sides are backend-derived from observed futures "
                    "position side; they are not exchange-observed order flags."
                ),
            )
            if positions
            else _futures_evidence(
                name="reduce_only_close_only",
                status=AdminFuturesEvidenceStatus.UNAVAILABLE,
                source=AdminFuturesEvidenceSource.RUNTIME_UNAVAILABLE,
                detail="No open futures positions are currently available for close-side derivation.",
            )
        )

        funding = _futures_evidence(
            name="funding",
            status=AdminFuturesEvidenceStatus.NOT_MODELED,
            source=AdminFuturesEvidenceSource.BACKEND_CONTRACT,
            detail="Funding-rate evidence is a named contract gap for M3; no browser or spot fallback is used.",
        )

        return AdminFuturesAccountReadResponse(
            configured_product_scope=configured_product_scope,
            observed_position_scope=observed_position_scope,
            collateral=collateral,
            margin=margin,
            funding=funding,
            liquidation=liquidation,
            reduce_only_close_only=reduce_only_close_only,
            position_pnl=position_pnl,
            position_count=len(positions),
        )

    def build_futures_positions(
        self,
        *,
        product_id: str | None = None,
        position_side: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> AdminFuturesPositionListResponse:
        """Return read-only futures/perpetual positions from runtime evidence."""

        normalized_limit = max(1, min(limit, 500))
        normalized_offset = max(0, offset)
        filters: dict[str, Any] = {
            "product_id": product_id,
            "position_side": position_side,
            "limit": normalized_limit,
            "offset": normalized_offset,
        }
        items = _futures_position_items()
        filtered: list[AdminFuturesPositionReadItem] = []
        for item in items:
            if product_id and item.product_id != product_id:
                continue
            if (
                position_side
                and str(item.position_side or "").upper() != position_side.upper()
            ):
                continue
            filtered.append(item)
        page_items = filtered[normalized_offset:normalized_offset + normalized_limit]
        next_offset = normalized_offset + len(page_items)
        has_more = next_offset < len(filtered)
        return AdminFuturesPositionListResponse(
            filters=filters,
            count=len(page_items),
            pagination={
                "limit": normalized_limit,
                "offset": normalized_offset,
                "returned_count": len(page_items),
                "total_matching_count": len(filtered),
                "next_offset": next_offset if has_more else None,
                "has_more": has_more,
            },
            items=page_items,
        )

    def build_futures_position_detail(
        self,
        *,
        position_key: str,
    ) -> AdminFuturesPositionDetailResponse:
        """Return one read-only futures/perpetual position by ``position_key``."""

        positions = _futures_position_items()
        for position in positions:
            if position.position_key == position_key:
                return AdminFuturesPositionDetailResponse(
                    position_key=position_key,
                    found=True,
                    position=position,
                )
        return AdminFuturesPositionDetailResponse(
            position_key=position_key,
            found=False,
            position=None,
        )

    def build_release_gate(self) -> AdminGateReadResponse:
        """Return release-gate evidence without running tests from the browser."""

        openapi_path = ROOT / "openapi" / "coinbase-admin-api.yaml"
        checks = [
            AdminGateCheck(
                name="openapi_schema_artifact",
                status=(
                    AdminApiGateStatus.PASSED
                    if openapi_path.exists()
                    else AdminApiGateStatus.BLOCKED
                ),
                detail=str(openapi_path),
            ),
            AdminGateCheck(
                name="backend_regression_gate",
                status=AdminApiGateStatus.NOT_APPLICABLE,
                detail="The browser may view release status, but it must not run pytest.",
            ),
            AdminGateCheck(
                name="live_coinbase_execution",
                status=AdminApiGateStatus.PASSED,
                detail="No live Coinbase execution is performed by this read route.",
            ),
        ]
        status = (
            AdminApiGateStatus.BLOCKED
            if any(check.status == AdminApiGateStatus.BLOCKED for check in checks)
            else AdminApiGateStatus.PASSED
        )
        return AdminGateReadResponse(
            type="admin_release_gate",
            status=status,
            checks=checks,
        )

    def build_recovery_gate(self) -> AdminGateReadResponse:
        """Return recovery-readiness route evidence."""

        return AdminGateReadResponse(
            type="admin_recovery_gate",
            status=AdminApiGateStatus.PASSED,
            checks=[
                AdminGateCheck(
                    name="direct_order_audit_route",
                    status=AdminApiGateStatus.PASSED,
                    detail="/api/v1/spot/direct-orders/{client_order_id}/audit is read-only.",
                ),
                AdminGateCheck(
                    name="repair_mutations",
                    status=AdminApiGateStatus.NOT_APPLICABLE,
                    detail="Recovery repair actions remain outside the frontend mutation surface.",
                ),
            ],
        )

    def build_fill_ledger_health(self) -> AdminGateReadResponse:
        """Return fill-ledger health posture without mutating ledger rows."""

        return AdminGateReadResponse(
            type="admin_fill_ledger_health",
            status=AdminApiGateStatus.PASSED,
            checks=[
                AdminGateCheck(
                    name="read_surface",
                    status=AdminApiGateStatus.PASSED,
                    detail="Fill-ledger health is exposed as a read-only contract.",
                ),
                AdminGateCheck(
                    name="repair_surface",
                    status=AdminApiGateStatus.NOT_APPLICABLE,
                    detail="Ledger repair remains CLI/operator controlled, not browser-triggered.",
                ),
                AdminGateCheck(
                    name="observed_at",
                    status=AdminApiGateStatus.PASSED,
                    detail=_now_iso(),
                ),
            ],
        )

    def build_frontend_fixtures(self) -> AdminFrontendFixturesResponse:
        """Return backend-owned fixtures for frontend mock alignment."""

        return AdminFrontendFixturesResponse(
            schema_version=SCHEMA_VERSION,
            fixtures={
                "admin.bootstrap": self.build_admin_bootstrap().model_dump(mode="json"),
                "admin.health": self.build_admin_health().model_dump(mode="json"),
                "admin.capabilities": self.build_admin_capabilities().model_dump(mode="json"),
                "admin.csrf": self.build_csrf_contract().model_dump(mode="json"),
                "orders.list": self.build_order_list().model_dump(mode="json"),
                "orders.detail.empty": self.build_order_detail(
                    client_order_id="00000000-0000-0000-0000-000000000000"
                ).model_dump(mode="json"),
                "movementRepricing.evidence": self.build_movement_repricing_evidence().model_dump(mode="json"),
                "movementRepricing.order.empty": self.build_movement_repricing_order_detail(
                    client_order_id="00000000-0000-0000-0000-000000000000"
                ).model_dump(mode="json"),
                "movementRepricing.stealth.empty": self.build_movement_repricing_stealth_detail(
                    stealth_order_id="00000000-0000-0000-0000-000000000000"
                ).model_dump(mode="json"),
                "futures.account": self.build_futures_account().model_dump(mode="json"),
                "futures.positions": self.build_futures_positions().model_dump(mode="json"),
                "futures.position.empty": self.build_futures_position_detail(
                    position_key="futures_position:runtime:UNKNOWN"
                ).model_dump(mode="json"),
                "admin.guardRiskPolicy": self.build_guard_risk_policy().model_dump(mode="json"),
                "release.gate": self.build_release_gate().model_dump(mode="json"),
                "recovery.gate": self.build_recovery_gate().model_dump(mode="json"),
                "fillLedger.health": self.build_fill_ledger_health().model_dump(mode="json"),
            },
        )

    def build_spot_readiness(
        self,
        *,
        product_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        from dashboard_server import _build_spot_readiness_payload

        return _build_spot_readiness_payload(product_ids=product_ids)

    def build_spot_sweep_status(self, *, state_file: str | None = None) -> dict[str, Any]:
        from dashboard_server import _build_spot_sweep_status_payload

        return _build_spot_sweep_status_payload(state_file=state_file)

    def build_spot_sweep_pnl(
        self,
        *,
        product_ids: list[str] | None = None,
        include_coinbase_average_cost: bool = False,
    ) -> dict[str, Any]:
        from dashboard_server import _build_spot_sweep_pnl_payload

        return _build_spot_sweep_pnl_payload(
            product_ids=product_ids,
            include_coinbase_average_cost=include_coinbase_average_cost,
        )

    def build_spot_cost_basis_status(
        self,
        *,
        state_file: str | None = None,
    ) -> dict[str, Any]:
        from dashboard_server import _build_spot_cost_basis_payload

        return _build_spot_cost_basis_payload(state_file=state_file)

    def build_spot_campaign_status(
        self,
        *,
        state_file: str | None = None,
    ) -> dict[str, Any]:
        from dashboard_server import _build_spot_campaign_payload

        return _build_spot_campaign_payload(state_file=state_file)

    def build_spot_direct_order_audit(
        self,
        *,
        client_order_id: str,
        include_events: bool = True,
        include_fills: bool = True,
        event_limit: int = 100,
        fill_limit: int = 1000,
    ) -> dict[str, Any]:
        from dashboard_server import _build_spot_direct_order_audit_payload

        return _build_spot_direct_order_audit_payload(
            client_order_id=client_order_id,
            include_events=include_events,
            include_fills=include_fills,
            event_limit=event_limit,
            fill_limit=fill_limit,
        )
