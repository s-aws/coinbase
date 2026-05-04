"""Back-compat re-export of the canonical EventBridge.

The single source of truth for ``EventBridge`` lives in
``bridges.event_bridge``. This module previously contained a near-identical
duplicate of that class, which on 2026-05-04 caused a runtime crash: a method
(``claim_event``) was added to one copy but not the other, regression tests
exercised the patched copy, and production hit the unpatched copy on every
WebSocket message.

To prevent that class of incident from recurring, this module is now a
re-export shim. New consumers should ``from bridges.event_bridge import
EventBridge`` directly. Once the remaining ``integration``-side callers are
migrated, this shim can be deleted.
"""

from bridges.event_bridge import EventBridge

__all__ = ["EventBridge"]
