"""Hook registries for OrderEngine and StealthOrderManager extension points.

Lifecycle events are delivered to opt-in subscribers. Consumers import the
specific hook module directly, such as integration.websocket_hooks or
integration.fill_event_hooks. Main owns reconciliation and readiness before
launching OrderEngine workers.
"""
