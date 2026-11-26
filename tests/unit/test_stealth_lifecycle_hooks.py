"""Contracts for the retained best-effort stealth lifecycle audit registry."""

import threading

import pytest

from core.enums import StealthLifecycleEvent
from integration.stealth_lifecycle_hooks import (
    StealthLifecycleHookRegistry,
    get_global_stealth_lifecycle_hook_registry,
    reset_global_stealth_lifecycle_hook_registry,
)


@pytest.fixture(autouse=True)
def reset_registry():
    reset_global_stealth_lifecycle_hook_registry()
    yield
    reset_global_stealth_lifecycle_hook_registry()


def test_register_and_call_on_transition():
    registry = StealthLifecycleHookRegistry()
    received = []
    context = {"product_id": "BTC-USDC"}

    registry.register_on_transition(
        lambda stealth_order_id, event, ctx: received.append(
            (stealth_order_id, event, ctx)
        )
    )
    registry.call_on_transition(
        "stealth-001",
        StealthLifecycleEvent.CREATED,
        context,
    )

    assert received == [
        ("stealth-001", StealthLifecycleEvent.CREATED, context)
    ]


def test_exception_in_hook_does_not_propagate():
    registry = StealthLifecycleHookRegistry()

    def failing_hook(stealth_order_id, event, context):
        raise RuntimeError("audit callback failed")

    registry.register_on_transition(failing_hook)

    registry.call_on_transition(
        "stealth-001",
        StealthLifecycleEvent.REVEAL_FAILED,
        {},
    )


def test_later_hooks_run_after_an_exception():
    registry = StealthLifecycleHookRegistry()
    calls = []

    def failing_hook(stealth_order_id, event, context):
        calls.append("failed")
        raise RuntimeError("audit callback failed")

    registry.register_on_transition(failing_hook)
    registry.register_on_transition(
        lambda stealth_order_id, event, context: calls.append("completed")
    )

    registry.call_on_transition(
        "stealth-001",
        StealthLifecycleEvent.CREATED,
        {},
    )

    assert calls == ["failed", "completed"]


def test_global_registry_returns_the_same_instance():
    first = get_global_stealth_lifecycle_hook_registry()
    second = get_global_stealth_lifecycle_hook_registry()

    assert first is second


def test_reset_replaces_the_global_registry():
    first = get_global_stealth_lifecycle_hook_registry()

    reset_global_stealth_lifecycle_hook_registry()

    second = get_global_stealth_lifecycle_hook_registry()
    assert first is not second


def test_registry_uses_a_reentrant_lock():
    registry = StealthLifecycleHookRegistry()

    assert isinstance(registry._lock, type(threading.RLock()))
