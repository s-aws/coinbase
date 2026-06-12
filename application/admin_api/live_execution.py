"""Live execution service posture for Admin API command admission.

This module intentionally exposes service-state evidence only. It does not
place, cancel, move, reconcile, or submit Coinbase orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.enums import AdminApiLiveExecutionStatus


@dataclass(frozen=True, slots=True)
class AdminApiLiveExecutionServiceState:
    """Backend-owned live execution service posture."""

    required: bool = True
    present: bool = False
    status: AdminApiLiveExecutionStatus = AdminApiLiveExecutionStatus.LIVE_DISABLED
    source: str = "not_configured"
    missing_reason: str | None = "live_execution_disabled"


class AdminApiLiveExecutionService(Protocol):
    """Protocol for service-state providers used by admission evidence."""

    def admission_state(self) -> AdminApiLiveExecutionServiceState:
        """Return backend-owned live execution service posture."""
        ...


class DisabledAdminApiLiveExecutionService:
    """Disabled service boundary for future live Admin API execution.

    The current implementation is evidence-only. Keeping this object separate
    from command routes makes the final execution boundary visible without
    adding an executable path.
    """

    def admission_state(self) -> AdminApiLiveExecutionServiceState:
        return AdminApiLiveExecutionServiceState(
            required=True,
            present=True,
            status=AdminApiLiveExecutionStatus.LIVE_DISABLED,
            source="disabled_backend_service",
            missing_reason="live_execution_disabled",
        )


def get_disabled_live_execution_service() -> DisabledAdminApiLiveExecutionService:
    """Return the default backend-owned disabled live execution service."""

    return DisabledAdminApiLiveExecutionService()
