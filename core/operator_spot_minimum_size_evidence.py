"""Canonical sanitized evidence for V7-V9 minimum-size preparation."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


MINIMUM_SIZE_POLICY_REVISION = (
    "BTC_USDC_POST_ONLY_BEST_BID_MINIMUM_SIZE_V2"
)

_PLAN_FIELDS = (
    "base_size",
    "limit_price",
    "max_possible_execution_notional_usdc",
    "max_submitted_notional_usdc",
    "possible_execution_notional_usdc",
    "post_only",
    "portfolio_id_sha256",
    "product_id",
    "side",
    "submitted_notional_usdc",
    "v4_boundary_classification",
)


def minimum_size_preparation_evidence_sha256(
    *,
    call_count: int,
    categories: Sequence[str],
    diagnostic_code: str,
    outcome: str,
    policy_revision: str,
    plan: Mapping[str, Any] | None,
) -> str:
    """Hash the full sanitized outcome without private source values."""

    canonical_plan = (
        {field: plan[field] for field in _PLAN_FIELDS}
        if plan is not None
        else None
    )
    public = {
        "call_count": call_count,
        "categories": list(categories),
        "diagnostic_code": diagnostic_code,
        "outcome": outcome,
        "policy_revision": policy_revision,
        "plan": canonical_plan,
    }
    return hashlib.sha256(
        json.dumps(
            public,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()

