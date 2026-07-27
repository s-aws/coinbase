"""Call-free runtime wiring for the Goal 16 Spot closeout sweep."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Sequence

from application.admin_api.operator_spot_safe_closeout_sweep_service import (
    OperatorSpotSafeCloseoutSweepService,
)
from database.operator_spot_safe_closeout_sweep import (
    OperatorSpotSafeCloseoutSweepRepository,
    get_default_operator_spot_safe_closeout_sweep_repository,
)


class OperatorSpotSafeCloseoutCandidateResolver:
    """Resolve only canonical local PostgreSQL candidate evidence."""

    def __init__(
        self,
        *,
        repository: OperatorSpotSafeCloseoutSweepRepository,
    ) -> None:
        self.repository = repository

    @property
    def configured_portfolio_scope_sha256(self) -> str:
        return self.repository.configured_portfolio_scope_sha256

    def list_candidates(self, **kwargs: Any):
        return self.repository.list_candidates(**kwargs)

    def resolve_selected(
        self,
        selections: Sequence[tuple[str, str]],
    ):
        return self.repository.resolve_selected(selections)


@lru_cache(maxsize=1)
def get_default_operator_spot_safe_closeout_sweep_service(
) -> OperatorSpotSafeCloseoutSweepService:
    repository = (
        get_default_operator_spot_safe_closeout_sweep_repository()
    )
    repository.ensure_schema()
    repository.recover_stranded_work()
    return OperatorSpotSafeCloseoutSweepService(
        repository=repository,
        candidate_resolver=OperatorSpotSafeCloseoutCandidateResolver(
            repository=repository
        ),
    )


def initialize_operator_spot_safe_closeout_sweep_runtime() -> None:
    """Install the local schema and quarantine stranded partial work."""

    get_default_operator_spot_safe_closeout_sweep_service()


def reset_operator_spot_safe_closeout_sweep_runtime_for_tests() -> None:
    get_default_operator_spot_safe_closeout_sweep_service.cache_clear()
    get_default_operator_spot_safe_closeout_sweep_repository.cache_clear()


__all__ = [
    "OperatorSpotSafeCloseoutCandidateResolver",
    "get_default_operator_spot_safe_closeout_sweep_service",
    "initialize_operator_spot_safe_closeout_sweep_runtime",
    "reset_operator_spot_safe_closeout_sweep_runtime_for_tests",
]
