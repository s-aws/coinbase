"""Integration modules for wiring Phase 3 business logic into OrderEngine.

This package provides integration points for connecting:
- OrderCalculator: Order value computations
- OrderProcessor: Order validation and enrichment
- EventProcessor: WebSocket event deduplication and routing

Example:
    >>> from integration.engine_integration import integ OrderEngineIntegration
    >>> from main import OrderEngine
    >>> engine = OrderEngine(...)
    >>> integrated = OrderEngineIntegration(engine)
    >>> integrated.run_forever()
"""

from integration.engine_integration import OrderEngineIntegration
from integration.calculator_bridge import CalculatorBridge
from integration.processor_bridge import ProcessorBridge
from integration.event_bridge import EventBridge

__all__ = [
    'OrderEngineIntegration',
    'CalculatorBridge',
    'ProcessorBridge',
    'EventBridge',
]
