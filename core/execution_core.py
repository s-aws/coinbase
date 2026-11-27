"""Transport-neutral application boundary for execution commands and queries.

The facade deliberately owns no lifecycle state.  It exposes narrow typed
capabilities and delegates to the existing runtime and stealth lifecycle
owners supplied by the composition root.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

from core.enums import EngineState, StealthOrderStatus


StealthOrderSnapshot = Dict[str, Dict[str, Any]]


class RuntimeLifecyclePort(Protocol):
    """Runtime lifecycle capability used by the application boundary."""

    def lifecycle_snapshot(self) -> tuple[EngineState, bool, bool]:
        """Return coherent state, admission, and stopping values."""
        ...

    def request_pause(self) -> bool:
        """Request a soft pause and report whether it was accepted."""
        ...

    def resume(self) -> bool:
        """Resume a paused runtime and report whether it changed state."""
        ...


class StealthOrderQueryPort(Protocol):
    """Detached active-state query capability owned by the stealth bridge."""

    def get_stealth_orders(
        self,
        status: Optional[StealthOrderStatus] = None,
    ) -> StealthOrderSnapshot:
        """Return caller-owned logical orders, optionally filtered by status."""
        ...


@dataclass(frozen=True, slots=True)
class RuntimeStatusSnapshot:
    """Immutable view of the runtime lifecycle boundary."""

    state: EngineState
    is_admitting: bool
    is_stopping: bool


@dataclass(frozen=True, slots=True)
class RuntimeTransitionResult:
    """Typed result for one pause or resume request."""

    accepted: bool
    runtime: RuntimeStatusSnapshot


class ExecutionCore:
    """Small in-process application facade over existing execution owners."""

    def __init__(
        self,
        *,
        runtime_controller: RuntimeLifecyclePort,
        stealth_orders: StealthOrderQueryPort,
    ) -> None:
        self._runtime_controller = runtime_controller
        self._stealth_orders = stealth_orders

    def runtime_status(self) -> RuntimeStatusSnapshot:
        """Return one coherent lifecycle snapshot from the runtime owner."""

        state, is_admitting, is_stopping = (
            self._runtime_controller.lifecycle_snapshot()
        )
        return RuntimeStatusSnapshot(
            state=state,
            is_admitting=is_admitting,
            is_stopping=is_stopping,
        )

    def pause_runtime(self) -> RuntimeTransitionResult:
        """Request a soft pause without originating trading work."""

        accepted = self._runtime_controller.request_pause()
        return RuntimeTransitionResult(
            accepted=accepted,
            runtime=self.runtime_status(),
        )

    def resume_runtime(self) -> RuntimeTransitionResult:
        """Request admission to reopen without originating trading work."""

        accepted = self._runtime_controller.resume()
        return RuntimeTransitionResult(
            accepted=accepted,
            runtime=self.runtime_status(),
        )

    def snapshot_stealth_orders(
        self,
        status: Optional[StealthOrderStatus] = None,
    ) -> StealthOrderSnapshot:
        """Return detached logical orders keyed by root ``client_order_id``.

        The managed stealth root ID is also the root client order ID.  Exchange
        ``order_id`` values are supplemental evidence and never become keys at
        this application boundary.
        """

        if status is not None and not isinstance(status, StealthOrderStatus):
            raise TypeError("status must be a StealthOrderStatus or None")
        return self._stealth_orders.get_stealth_orders(status=status)
