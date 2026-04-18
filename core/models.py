"""Data models - Core dataclasses for orders, positions, products."""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime

from core.enums import OrderSide, OrderStatus, ProductType, TargetMovementType


@dataclass
class Product:
    """Trading product metadata."""
    product_id: str
    product_type: ProductType
    base_increment: str
    quote_increment: str
    price_increment: str
    base_min_size: str = "0"
    trading_disabled: bool = False
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Product':
        """Create Product from API response dict."""
        return cls(
            product_id=data.get('product_id'),
            product_type=ProductType(data.get('product_type', 'SPOT').upper()),
            base_increment=data.get('base_increment', '0'),
            quote_increment=data.get('quote_increment', '0'),
            price_increment=data.get('price_increment', '0'),
            base_min_size=data.get('base_min_size', '0'),
            trading_disabled=data.get('trading_disabled', False),
        )


@dataclass
class Position:
    """Futures position - contract holdings."""
    product_id: str
    side: str  # 'LONG' or 'SHORT'
    number_of_contracts: str
    current_price: Optional[str] = None
    entry_price: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Position':
        """Create Position from API response dict."""
        return cls(
            product_id=data.get('product_id'),
            side=data.get('side'),
            number_of_contracts=str(data.get('number_of_contracts', '0')),
            current_price=data.get('current_price'),
            entry_price=data.get('entry_price'),
        )


@dataclass
class Wallet:
    """Account wallet - currency balance."""
    currency: str
    available_balance: str
    total_balance: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    deleted_at: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Wallet':
        """Create Wallet from API response dict."""
        return cls(
            currency=data.get('currency'),
            available_balance=str(data.get('available_balance', '0')),
            total_balance=str(data.get('total_balance', '0')),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            deleted_at=data.get('deleted_at'),
        )


@dataclass
class Order:
    """Trading order - spot or futures."""
    client_order_id: str
    product_id: str
    order_side: OrderSide
    status: OrderStatus
    size: float = 0.0
    price: float = 0.0
    filled_size: float = 0.0
    limit_price: Optional[float] = None
    avg_price: Optional[float] = None
    order_id: Optional[str] = None
    product_type: ProductType = ProductType.SPOT
    created_at: Optional[datetime] = None
    custom_metadata: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Order':
        """Create Order from API response dict."""
        from calculation.resolver import safe_float, normalize_product_type
        
        side = data.get('order_side') or data.get('side')
        status_str = data.get('status', 'OPEN').upper()
        
        return cls(
            client_order_id=data.get('client_order_id'),
            product_id=data.get('product_id'),
            order_side=OrderSide(side) if isinstance(side, str) else side,
            status=OrderStatus(status_str) if status_str in [e.value for e in OrderStatus] else OrderStatus.OPEN,
            size=safe_float(data.get('size'), 0.0),
            price=safe_float(data.get('price'), 0.0),
            filled_size=safe_float(data.get('filled_size'), 0.0),
            limit_price=safe_float(data.get('limit_price')),
            avg_price=safe_float(data.get('avg_price')),
            order_id=data.get('order_id'),
            product_type=ProductType(normalize_product_type(data)),
            created_at=data.get('created_at'),
            custom_metadata=data,
        )


@dataclass
class FollowUpOrderTemplate:
    """Template for creating a follow-up order after fill/cancellation."""
    product_id: str
    side: OrderSide
    order_base_size: str
    start_price: str
    order_price_difference: str
    profit_move_pct: float
    mandatory_fee: float = 0.0
    current_contract_count: str = "N/A"
    position_update: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for API placement."""
        return {
            'product_id': self.product_id,
            'side': self.side.value,
            'order_base_size': self.order_base_size,
            'start_price': self.start_price,
            'order_price_difference': self.order_price_difference,
            'profit_move_pct': self.profit_move_pct,
            'mandatory_fee': self.mandatory_fee,
            'current_contract_count': self.current_contract_count,
            'position_update': self.position_update,
        }
