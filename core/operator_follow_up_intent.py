"""Fail-closed activation boundary for operator follow-up intent support."""

from __future__ import annotations

import os
from typing import Mapping


OPERATOR_FOLLOW_UP_INTENT_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_FOLLOW_UP_INTENT_ENABLED"
)


def operator_follow_up_intent_enabled(
    env: Mapping[str, str] | None = None,
) -> bool:
    """Return true only for the exact, explicit local-feature opt-in."""

    source = os.environ if env is None else env
    return source.get(OPERATOR_FOLLOW_UP_INTENT_ENABLED_ENV) == "1"
