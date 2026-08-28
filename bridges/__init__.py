"""Bridges between OrderEngine and external subsystems.

Live bridges:
- ``EventBridge`` (``bridges/event_bridge.py``): WebSocket event dedup
  with atomic claim-and-mark used by ``OrderEngine.on_message``.
- ``StealthOrderBridge`` (``bridges/stealth_order_bridge.py``): wires the
  ``StealthOrderManager`` lifecycle into ``main.py`` and forwards ticker
  updates from the engine.

Historical note (2026-05-04):
    This package previously also contained ``OrderEngineOrchestrator``,
    ``CalculatorBridge``, and ``ProcessorBridge`` \u2014 strangler-fig
    scaffolding from the v2 OrderEngine refactor. The migration finished
    long before the audit, leaving those classes as dead code:

      - ``OrderEngineOrchestrator``: 250-line pass-through facade. Only
        ``run_forever()`` was called (one line, delegated to engine).
        Every other method was an unused delegate.
      - ``CalculatorBridge``: zero call sites outside the dead orchestrator.
      - ``ProcessorBridge``: one call site, inside the dead orchestrator.
      - The orchestrator also instantiated a *second* ``EventBridge`` with
        its own dedup buckets \u2014 a latent twin of the same race we
        had just fixed in the engine's primary ``EventBridge``.

    All three were deleted. ``main.py`` now owns reconciliation and readiness,
    then calls ``engine.run_forever`` with the readiness callback. The
    underlying business classes (``OrderCalculator``,
    ``OrderProcessor``) were also removed later the same day after the
    audit confirmed they had zero production callers once the bridges
    were gone. ``business.EventProcessor`` survives — it backs the
    live ``EventBridge``.

    See ``integration/__init__.py`` for the parallel cleanup of
    duplicate bridges that lived in ``integration/`` for the same reason.
"""

from bridges.event_bridge import EventBridge

__all__ = [
    'EventBridge',
]
