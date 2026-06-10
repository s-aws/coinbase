"""
Position Lot Builder - Derives position lots from immutable fill ledger.

This service maintains the mapping between fills and position lots, enabling:
1. FIFO lot construction (standard accounting)
2. Lot history reconstruction at any point
3. Profit threshold computation per lot

Design Pattern:
- Immutable source: fill_ledger table (append-only)
- Derived state: position_lots (cached, can be regenerated)
- Service: PositionLotBuilder (stateless, query-based)

The lot builder is stateless - it derives lots from the fill ledger
on demand, ensuring consistency without maintaining separate state.

Example:
    >>> from business.fill_ledger import FillLedgerRepository
    >>> from business.lot_builder import PositionLotBuilder
    >>>
    >>> repo = FillLedgerRepository(db_client)
    >>> builder = PositionLotBuilder(repo)
    >>> position = builder.build_position_by_product('BTC-USDC', profit_target_pct=0.5)
    >>> position.instrument
    'BTC-USDC'
"""

from typing import Any, List, Dict, Optional
from datetime import datetime
import uuid
from business.fill_ledger import FillLedger, FillLedgerRepository
from business.position_lot import PositionLot, LotPosition
from core.enums import InventoryCostBasisStatus, InventoryLotSource, OrderSide
from logging_service import get_logger

logger = get_logger("PositionLotBuilder")


class PositionLotBuilder:
    """Builds position lots from immutable fill ledger.
    
    Processes fill events chronologically to construct position lots using
    the FIFO (First-In-First-Out) accounting method. The builder is stateless
    and derives lots on-demand from the database.
    """
    
    def __init__(
        self,
        fill_ledger_repo: FillLedgerRepository,
        inventory_baselines: Optional[Any] = None,
    ):
        """Initialize lot builder.
        
        Args:
            fill_ledger_repo: FillLedgerRepository for accessing fills
        """
        self.fill_ledger_repo = fill_ledger_repo
        self.inventory_baselines = self._resolve_inventory_baselines(
            inventory_baselines
        )

    def _resolve_inventory_baselines(self, override: Optional[Any]) -> Any:
        if override is not None:
            return override
        try:
            from configuration import SPOT_INVENTORY_BASELINES
            return SPOT_INVENTORY_BASELINES
        except Exception:
            return []

    def _baseline_entries_for_product(self, product_id: str) -> List[Dict[str, Any]]:
        raw = self.inventory_baselines or []
        if isinstance(raw, dict):
            if isinstance(raw.get(product_id), list):
                raw = raw.get(product_id) or []
            else:
                raw = raw.get("lots") or raw.get("baselines") or []
        if not isinstance(raw, list):
            return []

        entries: List[Dict[str, Any]] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            entry_product_id = (
                entry.get("product_id")
                or entry.get("instrument")
                or entry.get("symbol")
            )
            if str(entry_product_id or "") != str(product_id or ""):
                continue
            entries.append(entry)
        return entries

    def _coerce_baseline_side(self, value: Any) -> OrderSide:
        try:
            return OrderSide(str(value or OrderSide.BUY.value).upper())
        except ValueError:
            return OrderSide.BUY

    def _coerce_cost_basis_status(
        self,
        *,
        raw_status: Any,
        entry_price: float,
    ) -> InventoryCostBasisStatus:
        if raw_status is not None:
            try:
                return InventoryCostBasisStatus(str(raw_status).lower())
            except ValueError:
                return InventoryCostBasisStatus.UNKNOWN
        if entry_price > 0:
            return InventoryCostBasisStatus.KNOWN
        return InventoryCostBasisStatus.UNKNOWN

    def _build_baseline_lots(
        self,
        product_id: str,
        *,
        side: Optional[OrderSide],
        profit_target_pct: float,
    ) -> List[PositionLot]:
        from calculation.formatter import safe_float

        lots: List[PositionLot] = []
        for index, entry in enumerate(self._baseline_entries_for_product(product_id)):
            entry_side = self._coerce_baseline_side(entry.get("side"))
            if side is not None and entry_side != side:
                continue

            quantity = safe_float(entry.get("quantity"), default=0.0) or 0.0
            if quantity <= 0:
                continue
            remaining_quantity = (
                safe_float(entry.get("remaining_quantity"), default=quantity)
                or quantity
            )
            entry_price = safe_float(entry.get("entry_price"), default=0.0) or 0.0
            fees = safe_float(entry.get("fees"), default=0.0) or 0.0
            cost_basis_status = self._coerce_cost_basis_status(
                raw_status=entry.get("cost_basis_status"),
                entry_price=entry_price,
            )
            timestamp = entry.get("entry_timestamp") or entry.get("timestamp")
            if isinstance(timestamp, str):
                try:
                    timestamp = datetime.fromisoformat(
                        timestamp.replace("Z", "+00:00")
                    )
                except ValueError:
                    timestamp = datetime.utcnow()
            elif timestamp is None:
                timestamp = datetime.utcnow()

            source_id = entry.get("source_id") or entry.get("lot_id") or index
            try:
                lot_source = InventoryLotSource(
                    str(
                        entry.get("lot_source")
                        or entry.get("source")
                        or InventoryLotSource.IMPORTED_BASELINE.value
                    ).lower()
                )
            except ValueError:
                lot_source = InventoryLotSource.IMPORTED_BASELINE
            known_entry_price = (
                entry_price
                if cost_basis_status == InventoryCostBasisStatus.KNOWN
                else 0.0
            )
            lot = PositionLot(
                lot_id=f"baseline:{product_id}:{source_id}",
                instrument=product_id,
                side=entry_side,
                quantity=quantity,
                entry_price=known_entry_price,
                entry_timestamp=timestamp,
                fees=fees,
                target_profit_percentage=profit_target_pct,
                remaining_quantity=remaining_quantity,
                source_fills=[],
                cost_basis_status=cost_basis_status,
                lot_source=lot_source,
            )
            lots.append(lot)
        return lots
    
    def _coerce_fill_side(self, fill: FillLedger) -> Optional[OrderSide]:
        try:
            return OrderSide[str(fill.side or "").upper()]
        except KeyError:
            return None

    def _opposite_side(self, side: OrderSide) -> OrderSide:
        return OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY

    def _consume_exit_quantity(
        self,
        *,
        position: LotPosition,
        entry_side: OrderSide,
        quantity: float,
        exit_price: float,
    ) -> float:
        remaining_exit = quantity
        for lot in position.lots:
            if lot.side != entry_side or lot.remaining_quantity <= 0:
                continue
            matched_quantity = min(remaining_exit, lot.remaining_quantity)
            if matched_quantity <= 0:
                continue
            lot.mark_partially_exited(matched_quantity, exit_price)
            remaining_exit -= matched_quantity
            if remaining_exit <= 1e-12:
                return 0.0
        return max(0.0, remaining_exit)

    def _add_entry_fill_lot(
        self,
        *,
        position: LotPosition,
        lots_dict: Dict[str, PositionLot],
        fill: FillLedger,
        quantity: float,
        fees: float,
        profit_target_pct: float,
    ) -> None:
        if quantity <= 0:
            return

        lot_key = self._get_lot_key(fill)
        existing_lot = lots_dict.get(lot_key)
        if (
            existing_lot is not None
            and existing_lot.remaining_quantity > 0
            and existing_lot.partially_exited_quantity <= 0
        ):
            existing_lot.quantity += quantity
            existing_lot.entry_value = existing_lot.quantity * existing_lot.entry_price
            existing_lot.fees += fees
            existing_lot.remaining_quantity += quantity
            existing_lot.source_fills.append(fill.derived_trade_key)
            existing_lot._compute_exit_threshold()
            logger.debug(
                f"Extended lot {existing_lot.lot_id}: "
                f"now {existing_lot.quantity} total"
            )
            return

        lot = self._create_lot_from_fill(
            fill,
            lots_dict,
            profit_target_pct,
            quantity=quantity,
            fees=fees,
        )
        lots_dict[lot_key] = lot
        position.add_lot(lot)
        logger.debug(
            f"Created lot {lot.lot_id}: {fill.side} {quantity} @ {fill.price}"
        )

    def _apply_ordered_fills_to_position(
        self,
        *,
        position: LotPosition,
        fills: List[FillLedger],
        side: Optional[OrderSide],
        profit_target_pct: float,
    ) -> None:
        lots_dict: Dict[str, PositionLot] = {}
        for fill in fills:
            fill_side = self._coerce_fill_side(fill)
            if fill_side is None:
                continue

            fill_quantity = float(fill.quantity or 0.0)
            fill_price = float(fill.price or 0.0)
            fill_fees = float(fill.fees or 0.0)
            if fill_quantity <= 0:
                continue

            if side is not None:
                if fill_side == side:
                    self._add_entry_fill_lot(
                        position=position,
                        lots_dict=lots_dict,
                        fill=fill,
                        quantity=fill_quantity,
                        fees=fill_fees,
                        profit_target_pct=profit_target_pct,
                    )
                    continue
                self._consume_exit_quantity(
                    position=position,
                    entry_side=side,
                    quantity=fill_quantity,
                    exit_price=fill_price,
                )
                continue

            opposite_side = self._opposite_side(fill_side)
            residual_quantity = self._consume_exit_quantity(
                position=position,
                entry_side=opposite_side,
                quantity=fill_quantity,
                exit_price=fill_price,
            )
            if residual_quantity <= 0:
                continue

            residual_fee = fill_fees * (residual_quantity / fill_quantity)
            self._add_entry_fill_lot(
                position=position,
                lots_dict=lots_dict,
                fill=fill,
                quantity=residual_quantity,
                fees=residual_fee,
                profit_target_pct=profit_target_pct,
            )

    def build_position_lots(self, 
                           instrument: str, 
                           side: Optional[OrderSide] = None,
                           profit_target_pct: float = 0.5) -> LotPosition:
        """Build position lots for an instrument from its fill history.
        
        Uses FIFO accounting: fills are grouped chronologically by entry price.
        Each group with the same entry price becomes one lot.
        
        Args:
            instrument: Trading pair (e.g., 'BTC-USDC')
            side: Optional side filter (BUY/SELL) - if None, gets all fills
            profit_target_pct: Target profit margin in percentage
        
        Returns:
            Position object with derived lots
        """
        # Get all fills for the instrument. Opposing-side fills must remain
        # visible so FIFO exits can reduce remaining lot quantity.
        fills = self.fill_ledger_repo.get_fills_by_instrument(instrument)

        position = LotPosition(instrument=instrument)
        for baseline_lot in self._build_baseline_lots(
            instrument,
            side=side,
            profit_target_pct=profit_target_pct,
        ):
            position.add_lot(baseline_lot)
        
        if not fills:
            logger.info(f"No fills found for {instrument}")
            return position

        self._apply_ordered_fills_to_position(
            position=position,
            fills=fills,
            side=side,
            profit_target_pct=profit_target_pct,
        )
        
        logger.info(f"Built position for {instrument}: {len(position.lots)} lots, "
                   f"total {position.total_quantity}")
        
        return position
    
    def _get_lot_key(self, fill: FillLedger) -> str:
        """Get the lot grouping key for a fill (side + price).
        
        Fills with the same side and price are grouped into the same lot.
        
        Args:
            fill: FillLedger record
        
        Returns:
            Lot key for grouping
        """
        return f"{fill.side}:{fill.price}"
    
    def _create_lot_from_fill(self, 
                             fill: FillLedger, 
                             existing_lots: Dict,
                             profit_target_pct: float,
                             quantity: Optional[float] = None,
                             fees: Optional[float] = None) -> PositionLot:
        """Create a new PositionLot from initial fill.
        
        Args:
            fill: FillLedger record
            existing_lots: Already-created lots (for validation)
            profit_target_pct: Target profit percentage
        
        Returns:
            New PositionLot object
        """
        lot_id = str(uuid.uuid4())
        
        lot_quantity = fill.quantity if quantity is None else quantity
        lot_fees = fill.fees if fees is None else fees

        lot = PositionLot(
            lot_id=lot_id,
            instrument=fill.instrument,
            side=OrderSide[fill.side.upper()],
            quantity=lot_quantity,
            entry_price=fill.price,
            entry_timestamp=fill.timestamp,
            fees=lot_fees,
            target_profit_percentage=profit_target_pct,
            source_fills=[fill.derived_trade_key]
        )
        
        # Compute entry value and profit threshold
        lot.entry_value = lot.quantity * lot.entry_price
        lot._compute_exit_threshold()
        lot.remaining_quantity = lot.quantity
        
        return lot
    
    def build_position_by_product(self,
                                  product_id: str,
                                  side: Optional[OrderSide] = None,
                                  profit_target_pct: float = 0.5) -> LotPosition:
        """Build position lots filtered by product ID and optional side.
        
        Args:
            product_id: Product ID (e.g., 'BTC-USDC')
            side: Optional side filter (BUY/SELL)
            profit_target_pct: Target profit percentage
        
        Returns:
            Position object with derived lots
        """
        # Read all fills for this product. A side-filtered query would hide
        # prior exits and overstate remaining spot inventory.
        fills = self.fill_ledger_repo.get_fills_by_product(product_id)

        position = LotPosition(instrument=product_id)
        for baseline_lot in self._build_baseline_lots(
            product_id,
            side=side,
            profit_target_pct=profit_target_pct,
        ):
            position.add_lot(baseline_lot)
        
        if not fills:
            # Infer instrument from product_id
            logger.info(f"No fills found for {product_id}")
            return position
        
        # Build position using the fill list
        position.instrument = fills[0].instrument if fills else product_id
        self._apply_ordered_fills_to_position(
            position=position,
            fills=fills,
            side=side,
            profit_target_pct=profit_target_pct,
        )
        
        return position
    
    def get_profitable_exit_strategy(self,
                                    position: LotPosition,
                                    market_price: float) -> Dict:
        """Analyze position and return profitable exit strategy.
        
        Given current market price and position lots, determine:
        1. Which lots can exit profitably
        2. What quantity can exit
        3. What prices are needed
        
        Args:
            position: Position with lots
            market_price: Current market price
        
        Returns:
            Dictionary with exit strategy details
        """
        profitable_lots = position.get_profitable_lots_at_price(market_price)
        
        if not profitable_lots:
            return {
                'can_exit_profitably': False,
                'profitable_lots': [],
                'message': f'No lots can exit profitably at {market_price}'
            }
        
        total_profitable_qty = sum(lot.remaining_quantity for lot in profitable_lots)
        
        return {
            'can_exit_profitably': True,
            'profitable_lots': [lot.to_position_lot_dict() for lot in profitable_lots],
            'total_profitable_quantity': total_profitable_qty,
            'market_price': market_price,
            'threshold_prices': [lot.min_profitable_exit_price for lot in profitable_lots]
        }
