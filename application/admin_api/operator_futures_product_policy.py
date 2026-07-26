"""Durable local product-policy records for the expanded Futures ticket."""

from __future__ import annotations

from dataclasses import dataclass

from .operator_futures_product_ticket import (
    FuturesProductPolicySelection,
)


class OperatorFuturesProductPolicyError(ValueError):
    """Fixed sanitized policy failure."""

    def __init__(self, code: str, *, http_status_code: int = 409) -> None:
        self.code = code
        self.http_status_code = http_status_code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class FuturesProductPolicyItem:
    product_id: str
    lifecycle: str
    allowed_actions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FuturesProductPolicyRecord:
    revision: int
    snapshot_sha256: str
    products: tuple[FuturesProductPolicyItem, ...]
    selected_product_id: str | None
    selection: FuturesProductPolicySelection | None
    last_action: str
    last_product_id: str | None
    last_correlation_id: str | None
    allowed_actions: list[str]
    updated_at: str


__all__ = [
    "FuturesProductPolicyItem",
    "FuturesProductPolicyRecord",
    "OperatorFuturesProductPolicyError",
]
