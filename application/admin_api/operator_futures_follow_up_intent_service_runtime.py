"""Installed local-only service for Futures follow-up intent attachment."""

from __future__ import annotations

from threading import Lock

from .operator_futures_follow_up_intent import (
    OperatorFuturesFollowUpIntentService,
)


OPERATOR_FUTURES_FOLLOW_UP_INTENT_ENABLED_ENV = (
    "COINBASE_ADMIN_API_OPERATOR_FUTURES_FOLLOW_UP_INTENT_ENABLED"
)

_DEFAULT_SERVICE: OperatorFuturesFollowUpIntentService | None = None
_DEFAULT_SERVICE_LOCK = Lock()


def get_default_operator_futures_follow_up_intent_service(
) -> OperatorFuturesFollowUpIntentService:
    global _DEFAULT_SERVICE
    if _DEFAULT_SERVICE is None:
        with _DEFAULT_SERVICE_LOCK:
            if _DEFAULT_SERVICE is None:
                from database.operator_futures_follow_up_intent import (
                    get_default_operator_futures_follow_up_intent_repository,
                )

                _DEFAULT_SERVICE = OperatorFuturesFollowUpIntentService(
                    repository=(
                        get_default_operator_futures_follow_up_intent_repository()
                    )
                )
    return _DEFAULT_SERVICE


def reset_operator_futures_follow_up_intent_service_for_tests() -> None:
    global _DEFAULT_SERVICE
    with _DEFAULT_SERVICE_LOCK:
        _DEFAULT_SERVICE = None


__all__ = [
    "OPERATOR_FUTURES_FOLLOW_UP_INTENT_ENABLED_ENV",
    "get_default_operator_futures_follow_up_intent_service",
    "reset_operator_futures_follow_up_intent_service_for_tests",
]
