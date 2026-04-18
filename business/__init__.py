"""Business logic layer for Coinbase trading engine.

This module provides high-level business logic for order and event processing,
including:
- Order calculation (follow-ups, fees, position changes)
- Order processing (state validation, enrichment)
- Event processing (deduplication, routing, filtering)

Modules:
    order_calculator: OrderCalculator class for order computations
    order_processor: OrderProcessor class for order event handling
    event_processor: EventProcessor class for WebSocket event processing

Example:
    >>> from business.order_calculator import OrderCalculator
    >>> from business.order_processor import OrderProcessor
    >>> from business.event_processor import EventProcessor
    >>> 
    >>> calculator = OrderCalculator()
    >>> processor = OrderProcessor()
    >>> event_handler = EventProcessor()
"""

from business.order_calculator import OrderCalculator
from business.order_processor import OrderProcessor
from business.event_processor import EventProcessor

__all__ = [
    "OrderCalculator",
    "OrderProcessor",
    "EventProcessor",
]
