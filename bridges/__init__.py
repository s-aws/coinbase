"""Bridge and Orchestrator modules for coordinating OrderEngine with business logic.

This package provides bridges (adapters) and an orchestrator that coordinate
the OrderEngine with specialized business logic modules:
- OrderCalculator: Order value computations
- OrderProcessor: Order validation and enrichment
- EventProcessor: WebSocket event deduplication and routing

Bridges follow the Adapter pattern to provide clean interfaces between layers.
The OrderEngineOrchestrator (Facade pattern) coordinates multiple bridges without
coupling them directly to the engine.

Example:
    >>> from bridges.engine_orchestrator import OrderEngineOrchestrator
    >>> from main import OrderEngine
    >>> engine = OrderEngine(...)
    >>> orchestrator = OrderEngineOrchestrator(engine)
    >>> orchestrator.run_forever()
"""

from bridges.engine_orchestrator import OrderEngineOrchestrator
from bridges.calculator_bridge import CalculatorBridge
from bridges.processor_bridge import ProcessorBridge
from bridges.event_bridge import EventBridge

__all__ = [
    'OrderEngineOrchestrator',
    'CalculatorBridge',
    'ProcessorBridge',
    'EventBridge',
]
