"""Pure follow-up order movement and position calculations.

This module owns the calculation behavior that historically lived in
``configuration.py``.  It performs no I/O and mutates only the position
mapping explicitly supplied to :func:`apply_calculated_position_update`.
"""

from copy import deepcopy
from typing import Any, Mapping, MutableMapping, Optional

from calculation.formatter import format_based_on_reference, quantize_to_increment, safe_float
from calculation.resolver import normalize_product_type, resolve_order_size, resolve_profit_move_pct
from core.constants import ORDER_DIRECTION, ORDER_POSITION_SIDE, ORDER_SIDE_SWITCH
from core.enums import OrderSide, OrderStatus, ProductType, RoundingDirection, TargetMovementType


def apply_calculated_position_update(
    positions: MutableMapping[str, Any],
    position_update: Optional[Mapping[str, Any]],
) -> MutableMapping[str, Any]:
    """Apply one calculated position update to the supplied mapping."""

    if not position_update:
        return positions

    product_type = str(position_update["product_type"])
    product_id = str(position_update["product_id"])
    positions.setdefault(product_type, {})
    positions[product_type].setdefault(product_id, {})
    positions[product_type][product_id].update(position_update["fields"])
    return positions


def calculate_new_order_move_from_snapshot(
    snapshot: Mapping[str, Any],
    order_id: str,
    target_movement: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Calculate a follow-up template from an isolated orderbook snapshot."""

    orders = snapshot.get("order", {})
    positions = deepcopy(snapshot.get("positions", {}))
    products = snapshot.get("product", {})
    profits = snapshot.get("profit", {})
    mandatory_fees = snapshot.get("mandatory_fee_per_contract", {})

    order = orders.get(order_id)
    if not order:
        return {}

    product_id = order["product_id"]
    product_type = normalize_product_type(order, products=products)
    order_status = order["status"]
    order_side = order["order_side"]
    order_size = resolve_order_size(order)

    mandatory_fee = safe_float(
        mandatory_fees.get(product_id, {}).get("mandatory_fee_per_contract"),
        default=0.0,
    )
    base_increment = products[product_id]["base_increment"]
    quote_increment = products[product_id]["quote_increment"]
    price_increment = products[product_id]["price_increment"]
    minimum_move_amount = float(price_increment)
    profit_move_pct = resolve_profit_move_pct(order, profits, products)

    if order_status == OrderStatus.FILLED.value:
        order_side = ORDER_SIDE_SWITCH[order_side]
    if order_status == OrderStatus.CANCELLED.value:
        order_size = safe_float(order.get("leaves_quantity"), default=0.0)

    limit_price = safe_float(order.get("limit_price"), default=0.0)
    average_price = safe_float(order.get("avg_price"), default=0.0)
    if limit_price > 0:
        order_price = limit_price
    elif average_price > 0:
        order_price = average_price
    else:
        return {}

    if target_movement is not None:
        if target_movement.get("type") == TargetMovementType.PERCENTAGE.value:
            profit_move_pct = target_movement["movement"]
        elif target_movement.get("type") == TargetMovementType.ABSOLUTE.value:
            minimum_move_amount = float(target_movement["movement"])

    fee_move = order_price * profit_move_pct
    move_amount = max(minimum_move_amount, fee_move)
    move_difference = move_amount * ORDER_DIRECTION[order_side]
    position_update = None

    if product_type == ProductType.FUTURE.value:
        product_positions = positions.get(product_type, {})
        position = deepcopy(product_positions.get(product_id))
        if order_status == OrderStatus.FILLED.value and position:
            contract_count = float(position["number_of_contracts"])
            if ORDER_POSITION_SIDE[position["side"]] == order_side:
                contract_count -= order_size
                mandatory_fee *= ORDER_DIRECTION[order_side]
                if contract_count < 0:
                    contract_count = abs(contract_count)
                    position["side"] = ORDER_POSITION_SIDE[
                        ORDER_SIDE_SWITCH[order_side]
                    ]
            else:
                contract_count += order_size
                mandatory_fee *= ORDER_DIRECTION[order_side]

            position["number_of_contracts"] = str(contract_count)
            position_update = {
                "product_type": product_type,
                "product_id": product_id,
                "fields": {
                    "side": position["side"],
                    "number_of_contracts": position["number_of_contracts"],
                },
            }
            product_positions[product_id] = position
            positions[product_type] = product_positions

    new_price = order_price + move_difference + mandatory_fee
    new_price = float(format_based_on_reference(new_price, quote_increment))
    new_size = float(format_based_on_reference(order_size, base_increment))
    rounding = (
        RoundingDirection.UP.value
        if order_side == OrderSide.SELL.value
        else RoundingDirection.DOWN.value
    )
    new_price = quantize_to_increment(
        new_price,
        price_increment,
        direction=rounding,
    )

    price_precision = len(price_increment) - 2 if len(price_increment) > 3 else 1
    size_precision = len(base_increment) - 2 if len(base_increment) > 3 else 1
    current_contract_count: Any = "N/A"
    if product_type == ProductType.FUTURE.value:
        updated = positions.get(product_type, {}).get(product_id)
        if updated:
            current_contract_count = updated.get("number_of_contracts", "N/A")

    return {
        "current_contract_count": current_contract_count,
        "mandatory_fee": mandatory_fee,
        "profit_move_pct": profit_move_pct,
        "fee_move_calculated_from_pct": fee_move,
        "minimum_move_amount": minimum_move_amount,
        "product_id": product_id,
        "side": order_side,
        "order_base_size": f"{new_size:.{size_precision}f}",
        "order_price_difference": f"{abs(move_difference):.{price_precision}f}",
        "start_price": f"{new_price:.{price_precision}f}",
        "position_update": position_update,
    }


def determine_open_close_sides(
    product_type: str,
    position_side: Optional[str] = None,
    parent_order_side: Optional[str] = None,
    position_size: Optional[float] = None,
    order_size: Optional[float] = None,
) -> tuple[str, str]:
    """Return the opening and closing sides for the supplied position.

    ``position_size`` and ``order_size`` remain accepted for API compatibility;
    quantity splitting for a flip is handled by the caller.
    """

    del position_size, order_size
    if product_type == ProductType.SPOT.value:
        return (OrderSide.BUY.value, OrderSide.SELL.value)
    if position_side == "SHORT":
        return (OrderSide.SELL.value, OrderSide.BUY.value)
    if position_side == "LONG":
        return (OrderSide.BUY.value, OrderSide.SELL.value)
    if parent_order_side == OrderSide.SELL.value:
        return (OrderSide.SELL.value, OrderSide.BUY.value)
    return (OrderSide.BUY.value, OrderSide.SELL.value)
