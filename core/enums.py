"""Enums for trading engine - Order states, product types, etc."""

from enum import Enum


class OrderSide(str, Enum):
    """Direction of an order - BUY or SELL."""
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    """Status of an order throughout its lifecycle."""
    PENDING = "PENDING"
    OPEN = "OPEN"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    UPDATE = "UPDATE"
    SNAPSHOT = "SNAPSHOT"


class ProductType(str, Enum):
    """Type of trading product."""
    SPOT = "SPOT"
    FUTURE = "FUTURE"


class TargetMovementType(str, Enum):
    """How profit target is specified."""
    PERCENTAGE = "P"       # As percentage (e.g., 0.004 = 0.4%)
    ABSOLUTE = "A"         # As absolute amount (e.g., $500)
