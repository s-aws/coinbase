"""Exact outer authority for Coinbase exchange mutations.

This module is intentionally small and dependency-free so every production
mutation boundary, including legacy CLI runners, can share one fail-closed
interpretation of the operator-owned environment flag.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import re
import stat
from typing import Iterator


COINBASE_EXECUTION_AUTHORITY_ENV = "COINBASE_EXECUTION_ENABLED"
COINBASE_EXECUTION_AUTHORITY_REQUIRED_VALUE = "1"
COINBASE_EXECUTION_LEASE_PATH_ENV = "COINBASE_EXECUTION_LEASE_PATH"
COINBASE_EXECUTION_LEASE_TOKEN_ENV = "COINBASE_EXECUTION_LEASE_TOKEN"
COINBASE_EXECUTION_SCOPE_SPOT_PLACE = "canonical_admin_api_spot_place"
COINBASE_EXECUTION_SCOPE_SPOT_CANCEL = "canonical_admin_api_spot_cancel"
SOURCE_DISABLED_COINBASE_EXECUTION_ERROR = (
    "coinbase_execution_surface_source_disabled_use_authenticated_admin_api"
)
_SYNTHETIC_TEST_EXECUTION_SCOPE = "synthetic_test_only"
_CANONICAL_EXECUTION_SCOPES = frozenset(
    {
        COINBASE_EXECUTION_SCOPE_SPOT_PLACE,
        COINBASE_EXECUTION_SCOPE_SPOT_CANCEL,
    }
)
_ACTIVE_EXECUTION_SCOPE: ContextVar[str | None] = ContextVar(
    "coinbase_active_execution_scope",
    default=None,
)
_LEASE_TOKEN_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class CoinbaseExecutionAuthorityError(RuntimeError):
    """Raised before a Coinbase mutation when exact outer authority is absent."""


@contextmanager
def canonical_coinbase_execution_scope(scope: str) -> Iterator[None]:
    """Bind one authenticated canonical Admin API mutation to this context."""

    if scope not in _CANONICAL_EXECUTION_SCOPES:
        raise CoinbaseExecutionAuthorityError(
            "coinbase_execution_scope_invalid"
        )
    token = _ACTIVE_EXECUTION_SCOPE.set(scope)
    try:
        yield
    finally:
        _ACTIVE_EXECUTION_SCOPE.reset(token)


@contextmanager
def _synthetic_test_only_coinbase_execution_scope() -> Iterator[None]:
    """Permit isolated mutation-adapter tests without creating a production path."""

    token = _ACTIVE_EXECUTION_SCOPE.set(_SYNTHETIC_TEST_EXECUTION_SCOPE)
    try:
        yield
    finally:
        _ACTIVE_EXECUTION_SCOPE.reset(token)


def _verified_execution_lease_stat(
    lease_path: str,
    lease_token: str,
) -> os.stat_result | None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(lease_path, flags)
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_mode & 0o077
            or details.st_nlink != 1
            or details.st_size != 65
        ):
            return None
        if hasattr(os, "getuid") and details.st_uid != os.getuid():
            return None
        expected = f"{lease_token}\n".encode("ascii")
        payload = os.read(descriptor, len(expected) + 1)
        if payload != expected:
            return None
        return details
    except (OSError, UnicodeError):
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def coinbase_execution_authority_enabled(
    environ: Mapping[str, str] | None = None,
) -> bool:
    """Return true only for the exact flag plus a verified runtime lease."""

    source = os.environ if environ is None else environ
    if (
        source.get(COINBASE_EXECUTION_AUTHORITY_ENV, "")
        != COINBASE_EXECUTION_AUTHORITY_REQUIRED_VALUE
    ):
        return False
    lease_path = str(source.get(COINBASE_EXECUTION_LEASE_PATH_ENV, "") or "").strip()
    lease_token = str(
        source.get(COINBASE_EXECUTION_LEASE_TOKEN_ENV, "") or ""
    ).strip()
    if not lease_path or not _LEASE_TOKEN_PATTERN.fullmatch(lease_token):
        return False
    return _verified_execution_lease_stat(lease_path, lease_token) is not None


def coinbase_execution_lease_started_at(
    environ: Mapping[str, str] | None = None,
) -> datetime | None:
    """Return the active lease creation time, or ``None`` when not configured."""

    source = os.environ if environ is None else environ
    lease_path = str(source.get(COINBASE_EXECUTION_LEASE_PATH_ENV, "") or "").strip()
    if not lease_path or not coinbase_execution_authority_enabled(source):
        return None
    lease_token = str(
        source.get(COINBASE_EXECUTION_LEASE_TOKEN_ENV, "") or ""
    ).strip()
    details = _verified_execution_lease_stat(lease_path, lease_token)
    if details is None:
        return None
    try:
        return datetime.fromtimestamp(details.st_mtime, timezone.utc)
    except (OverflowError, ValueError):
        return None


def require_coinbase_execution_authority(
    environ: Mapping[str, str] | None = None,
    *,
    expected_scope: str | None = None,
) -> None:
    """Require outer authority plus a canonical request-bound mutation scope."""

    active_scope = _ACTIVE_EXECUTION_SCOPE.get()
    scope_matches = bool(
        active_scope in _CANONICAL_EXECUTION_SCOPES
        and (expected_scope is None or active_scope == expected_scope)
    ) or active_scope == _SYNTHETIC_TEST_EXECUTION_SCOPE
    if not coinbase_execution_authority_enabled(environ) or not scope_matches:
        raise CoinbaseExecutionAuthorityError(
            "coinbase_execution_authority_missing"
        )
