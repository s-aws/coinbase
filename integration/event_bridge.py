"""Compatibility re-export of the canonical bridges.event_bridge.EventBridge.

All import paths use the same implementation. New consumers should import
EventBridge directly from bridges.event_bridge.
"""

from bridges.event_bridge import EventBridge

__all__ = ["EventBridge"]
