"""Spot inventory authority checks derived from lots.

Wallet balance answers whether a spot sell can be placed. Lot authority answers
whether the system knows enough cost basis to treat that sell as profitable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from calculation.formatter import safe_float
from core.enums import (
    InventoryAuthorityStatus,
    InventoryCostBasisStatus,
    OrderSide,
    ProductType,
)


@dataclass(frozen=True)
class SpotSellInventoryAuthorityDecision:
    """Decision for known-cost, profitable spot sell authority."""

    allowed: bool
    status: str
    product_id: str
    side: str
    requested_size: float
    limit_price: float
    known_quantity: float
    known_profitable_quantity: float
    unknown_cost_basis_quantity: float
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "status": self.status,
            "product_id": self.product_id,
            "side": self.side,
            "requested_size": self.requested_size,
            "limit_price": self.limit_price,
            "known_quantity": self.known_quantity,
            "known_profitable_quantity": self.known_profitable_quantity,
            "unknown_cost_basis_quantity": self.unknown_cost_basis_quantity,
            "reason": self.reason,
        }


def _is_spot_product(product_id: str) -> bool:
    try:
        from configuration import normalize_product_type

        return (
            normalize_product_type({"product_id": product_id})
            == ProductType.SPOT.value
        )
    except Exception:
        return False


def evaluate_spot_sell_lot_authority(
    *,
    product_id: str,
    side: str,
    size: Any,
    limit_price: Any,
    fill_ledger_repo: Any,
    inventory_baselines: Optional[Any] = None,
    profit_target_pct: Optional[float] = None,
) -> SpotSellInventoryAuthorityDecision:
    """Evaluate whether known profitable lots cover a spot sell.

    Non-spot products and non-sell actions are not applicable and pass through.
    Unknown-cost inventory is counted separately and never satisfies
    profitability authority.
    """
    try:
        side_value = OrderSide(str(side or "").upper()).value
    except ValueError:
        side_value = str(side or "").upper()

    requested_size = safe_float(size, default=0.0) or 0.0
    submitted_price = safe_float(limit_price, default=0.0) or 0.0
    if side_value != OrderSide.SELL.value or not _is_spot_product(product_id):
        return SpotSellInventoryAuthorityDecision(
            allowed=True,
            status=InventoryAuthorityStatus.NOT_APPLICABLE.value,
            product_id=product_id,
            side=side_value,
            requested_size=requested_size,
            limit_price=submitted_price,
            known_quantity=0.0,
            known_profitable_quantity=0.0,
            unknown_cost_basis_quantity=0.0,
            reason="inventory authority applies only to spot SELL actions",
        )

    if fill_ledger_repo is None:
        return SpotSellInventoryAuthorityDecision(
            allowed=False,
            status=InventoryAuthorityStatus.UNAVAILABLE.value,
            product_id=product_id,
            side=side_value,
            requested_size=requested_size,
            limit_price=submitted_price,
            known_quantity=0.0,
            known_profitable_quantity=0.0,
            unknown_cost_basis_quantity=0.0,
            reason="fill ledger repository is unavailable",
        )

    if requested_size <= 0 or submitted_price <= 0:
        return SpotSellInventoryAuthorityDecision(
            allowed=False,
            status=InventoryAuthorityStatus.INSUFFICIENT_KNOWN_PROFITABLE.value,
            product_id=product_id,
            side=side_value,
            requested_size=requested_size,
            limit_price=submitted_price,
            known_quantity=0.0,
            known_profitable_quantity=0.0,
            unknown_cost_basis_quantity=0.0,
            reason="positive size and limit_price are required",
        )

    from business.lot_builder import PositionLotBuilder
    from business.lot_config import get_profit_target_for_product

    profit_target = (
        safe_float(profit_target_pct, default=None)
        if profit_target_pct is not None
        else get_profit_target_for_product(product_id)
    )
    builder = PositionLotBuilder(
        fill_ledger_repo,
        inventory_baselines=inventory_baselines,
    )
    position = builder.build_position_by_product(
        product_id,
        side=OrderSide.BUY,
        profit_target_pct=profit_target,
    )

    known_quantity = 0.0
    known_profitable_quantity = 0.0
    unknown_quantity = 0.0
    for lot in position.get_unexited_lots():
        remaining = safe_float(lot.remaining_quantity, default=0.0) or 0.0
        if remaining <= 0:
            continue
        if lot.cost_basis_status != InventoryCostBasisStatus.KNOWN:
            unknown_quantity += remaining
            continue
        known_quantity += remaining
        if lot.can_exit_profitably_at(submitted_price):
            known_profitable_quantity += remaining

    epsilon = 1e-12
    if known_profitable_quantity + epsilon >= requested_size:
        return SpotSellInventoryAuthorityDecision(
            allowed=True,
            status=InventoryAuthorityStatus.KNOWN_PROFITABLE.value,
            product_id=product_id,
            side=side_value,
            requested_size=requested_size,
            limit_price=submitted_price,
            known_quantity=known_quantity,
            known_profitable_quantity=known_profitable_quantity,
            unknown_cost_basis_quantity=unknown_quantity,
            reason="known profitable lots cover requested spot sell size",
        )

    if known_quantity <= 0 and unknown_quantity <= 0:
        status = InventoryAuthorityStatus.NO_LOTS
        reason = "no known or imported inventory lots cover this spot sell"
    elif unknown_quantity > 0:
        status = InventoryAuthorityStatus.UNKNOWN_COST_BASIS
        reason = (
            "known profitable lots do not cover the sell and remaining "
            "inventory has unknown cost basis"
        )
    else:
        status = InventoryAuthorityStatus.INSUFFICIENT_KNOWN_PROFITABLE
        reason = "known lots exist but are insufficient or not profitable"

    return SpotSellInventoryAuthorityDecision(
        allowed=False,
        status=status.value,
        product_id=product_id,
        side=side_value,
        requested_size=requested_size,
        limit_price=submitted_price,
        known_quantity=known_quantity,
        known_profitable_quantity=known_profitable_quantity,
        unknown_cost_basis_quantity=unknown_quantity,
        reason=reason,
    )
