"""Sanitized Goal 12 exact Spot Cancel result shape."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class SpotOrderTruthCancelExecution:
    outcome: Literal["ACCEPTED", "REJECTED", "UNKNOWN"]
    diagnostic_code: str
    call_boundary_entered: bool
    exchange_order_id_sha256: str
    public_evidence: dict[str, Any]


__all__ = [
    "SpotOrderTruthCancelExecution",
]
