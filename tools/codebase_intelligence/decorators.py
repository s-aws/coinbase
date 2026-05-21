"""Opt-in decorators for executable codebase-intelligence bindings."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar


F = TypeVar("F", bound=Callable[..., object])


def codebase_tool(
    *,
    name: str | None = None,
    description: str | None = None,
    read_only: bool = True,
) -> Callable[[F], F]:
    """Mark a callable as eligible for explicit allowlisted binding.

    The marker alone is not enough. ``ToolRegistry.register_callable`` also
    requires a matching symbol allowlist entry and static safety checks.
    """

    def decorate(func: F) -> F:
        setattr(func, "__codebase_tool__", True)
        setattr(func, "__codebase_tool_name__", name or func.__name__)
        setattr(func, "__codebase_tool_description__", description or "")
        setattr(func, "__codebase_tool_read_only__", read_only)
        return func

    return decorate


def codebase_read_tool(
    *,
    name: str | None = None,
    description: str | None = None,
) -> Callable[[F], F]:
    """Shortcut for read-only codebase tool bindings."""

    return codebase_tool(name=name, description=description, read_only=True)
