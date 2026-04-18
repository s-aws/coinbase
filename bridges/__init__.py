"""Bridge modules for connecting OrderEngine with business logic components.

This package provides bridges (adapters) that connect the OrderEngine with
specialized business logic modules:
- OrderCalculator: Order value computations
- OrderProcessor: Order validation and enrichment
- EventProcessor: WebSocket event deduplication and routing

Bridges follow the Adapter pattern to provide clean interfaces between
layers while keeping concerns separated.

Example:
    >>> from bridges.engine_integration import OrderEngineIntegration
    >>> from main import OrderEngine
    >>> engine = OrderEngine(...)
    >>> integrated = OrderEngineIntegration(engine)
    >>> integrated.run_forever()
"""

from bridges.engine_integration import OrderEngineIntegration
from bridges.calculator_bridge import CalculatorBridge
from bridges.processor_bridge import ProcessorBridge
from bridges.event_bridge import EventBridge

__all__ = [
    'OrderEngineIntegration',
    'CalculatorBridge',
    'ProcessorBridge',
    'EventBridge',
]
