"""Hook registries for OrderEngine and StealthOrderManager extension points.

This package provides hook registry modules that the engine and manager use
to fan out lifecycle events (placements, fills, websocket messages, state
transitions) to opt-in subscribers.

All consumers import the specific hook module they need directly, e.g.:

    from integration.websocket_hooks import WebSocketHookRegistry
    from integration.fill_event_hooks import get_global_fill_event_hook_registry

This package previously also contained a parallel set of bridge wrappers
(``CalculatorBridge``, ``ProcessorBridge``, ``EventBridge``) and an
unwired ``OrderEngineIntegration`` orchestrator. Those were duplicates of
classes in ``bridges/`` that nothing outside this package imported. They
were deleted on 2026-05-04 after one of them (``EventBridge``) caused a
runtime crash by silently diverging from its live twin in ``bridges/``.

The ``bridges/`` package was then audited the same day and the
``OrderEngineOrchestrator`` + ``CalculatorBridge`` + ``ProcessorBridge``
trio there was also deleted as completed strangler-fig scaffolding from
the v2 OrderEngine refactor. ``main.py`` now drives ``OrderEngine``
directly via ``engine.run_forever()``.
"""
