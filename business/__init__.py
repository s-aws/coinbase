"""Business logic layer for Coinbase trading engine.

Live modules:
    event_processor: ``EventProcessor`` — WebSocket event dedup with atomic
        claim-and-mark; wrapped by ``bridges.event_bridge.EventBridge`` and
        used at ``OrderEngine.on_message`` ingress.

Historical note (2026-05-04):
    ``order_calculator.OrderCalculator`` and ``order_processor.OrderProcessor``
    were removed. Both were the underlying classes wrapped by the
    ``CalculatorBridge`` / ``ProcessorBridge`` strangler-fig scaffolding
    deleted earlier the same day. After the bridges went, neither class had
    a single production caller — only self-tests inside
    ``tests/test_exceptions.py``. Deleted to remove the false impression
    that they participated in any live path.
"""

from business.event_processor import EventProcessor

__all__ = [
    "EventProcessor",
]
