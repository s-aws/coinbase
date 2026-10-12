"""Business logic layer for the Coinbase trading engine.

Exports EventProcessor, the atomic WebSocket event deduplicator used by
bridges.event_bridge.EventBridge at OrderEngine.on_message ingress.
"""

from business.event_processor import EventProcessor

__all__ = [
    "EventProcessor",
]
