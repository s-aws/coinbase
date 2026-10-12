"""Bridges between OrderEngine and external subsystems.

EventBridge owns atomic WebSocket event deduplication at engine ingress.
StealthOrderBridge connects the stealth manager to main startup, scheduling,
reconciliation, and engine ticker updates.
"""

from bridges.event_bridge import EventBridge

__all__ = [
    'EventBridge',
]
